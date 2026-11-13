"""Grupos con señal del lote y lista de verificación de patrones MITRE (NODEX final). Sin LLM.

Lo que el auditor reforzado (`AUDITOR_REFORZADO`) recibe en un bloque destacado para evaluar
cada grupo antes del veredicto:

- `grupos_con_senal`: en logs de red, los grupos que el perfil marcó con alguna SEÑAL (barrido
  de puertos, servicio o protocolo minoritario, inversión de rol); en logs de texto, los grupos
  de severidad alta o de plantilla minoritaria. Cada grupo lleva todas sus filas del catálogo
  (con topes), el motivo factual de su señal (`GRUPOS_MOTIVO_FACTUAL`) y sus referentes de la
  memoria de grupos (`MEMORIA_GRUPOS_ACTIVA`).
- `resumen_dominante`: el comportamiento dominante del lote, para comparar.
- `PATRONES_ATAQUE`: lista de verificación general de patrones de ataque observables en logs,
  tomada de MITRE ATT&CK (descripciones generales de las técnicas, no de los casos)
  (`LISTA_PATRONES_MITRE`).

Origen: era la entrada del agente cazador de las Fases B y B.1, eliminado del sistema final
(docs/experimentacion/bitacora_desarrollo_nodex_final.md). El contenido y el texto de las
instrucciones son los mismos con que se evaluó la configuración final.
"""

from src.preprocessing.perfil_lote import _SEVERIDADES_ALTAS
from src.state import LogGuardState

#: Patrones de ataque observables en logs, tomados de MITRE ATT&CK.
#: (id, comportamiento observable, técnicas).
PATRONES_ATAQUE = (
    ("barrido_descubrimiento_servicios",
     "un origen prueba muchos puertos o muchos equipos en poco tiempo, con conexiones cortas, rechazadas, "
     "reiniciadas o sin respuesta", "T1046, T1595"),
    ("enumeracion_reconocimiento_dns",
     "consultas DNS en volumen o en ráfaga desde un mismo origen, enumeración de nombres o de direcciones "
     "(incluida la resolución inversa), transferencias de zona (DNS sobre TCP), o consultas a servidores que no "
     "son los que usa el resto del lote", "T1590.002, T1018, T1595"),
    ("fuerza_bruta_autenticacion",
     "muchos intentos de autenticación o de conexión a un servicio de acceso (SSH, RDP, SMB, LDAP, Kerberos, "
     "formularios web) desde un origen, con fallos repetidos o sesiones muy cortas", "T1110"),
    ("beaconing_c2",
     "conexiones repetidas a intervalos regulares hacia un mismo destino, con tamaños parecidos y poca carga, o "
     "un protocolo de aplicación usado como canal de control", "T1071, T1573"),
    ("transferencia_exfiltracion_atipica",
     "un volumen enviado desde el origen muy superior a lo recibido o al resto del lote, hacia un destino poco "
     "habitual o por un canal no usual", "T1041, T1048"),
    ("ejecucion_remota_movimiento_lateral",
     "conexiones entre equipos internos a servicios de administración o ejecución remota (SMB, RDP, WinRM, SSH, "
     "RPC/DCOM) que el resto del lote no muestra", "T1021, T1570, T1047"),
    ("puerto_no_estandar",
     "un protocolo de aplicación en un puerto que no le corresponde, o un servicio en un puerto inusual",
     "T1571"),
)
IDS_PATRONES = tuple(p[0] for p in PATRONES_ATAQUE) + ("ninguno",)


def instrucciones_grupos() -> str:
    """Instrucciones sobre el contenido de cada grupo, según sus interruptores."""
    from src.config import GRUPOS_MOTIVO_FACTUAL, LISTA_PATRONES_MITRE, MEMORIA_GRUPOS_ACTIVA
    partes = []
    if GRUPOS_MOTIVO_FACTUAL:
        partes.append("Cada grupo trae motivos_factuales: el hecho del lote que hizo que se señalara.")
    if LISTA_PATRONES_MITRE:
        partes.append(
            "LISTA DE VERIFICACIÓN de patrones de ataque observables en logs (MITRE ATT&CK): "
            + " ".join(f"[{pid}] {desc} ({tec})." for pid, desc, tec in PATRONES_ATAQUE)
            + " Para cada grupo indica en patron_lista qué patrón de la lista calza con lo observado, o "
            "'ninguno' si ninguno calza; un calce exige que la forma observable coincida (volumen, ritmo, "
            "dirección, puertos, estados), no solo el servicio. La regla sobre el tráfico de infraestructura "
            "se refiere a la rareza: un grupo de infraestructura también puede calzar con un patrón por su forma.")
    if MEMORIA_GRUPOS_ACTIVA:
        partes.append(
            "Algunos grupos traen memoria: el grupo malicioso y el grupo benigno de casos pasados de la "
            "organización más parecidos en comportamiento. Es una comparación, no una votación: decide qué "
            "referente comparte los rasgos que importan y justifícalo con las filas.")
    return (" " + " ".join(partes)) if partes else ""


def _filas_por_grupo(state: LogGuardState) -> dict:
    filas = {}
    for registro in state.get("evidencia_logs") or []:
        if isinstance(registro, dict) and registro.get("group_id"):
            filas.setdefault(registro["group_id"], []).append(
                {k: v for k, v in registro.items() if k not in ("group_id", "record_number", "line_end")})
    return filas


def grupos_con_senal(state: LogGuardState) -> list[dict]:
    """Grupos con señal del lote, con sus filas (vacío = no hay grupos que evaluar)."""
    from src.config import GRUPOS_MOTIVO_FACTUAL, GRUPOS_SENAL_MAX_FILAS, GRUPOS_SENAL_MAX_GRUPOS, \
        MEMORIA_GRUPOS_ACTIVA
    from src.tools.memoria_grupos import referentes_de_grupo
    perfil = (state.get("resumen_logs") or {}).get("perfil_lote") or {}
    grupos = {g["group_id"]: g for g in state.get("grupos_evidencia") or [] if isinstance(g, dict)}
    factuales = {}
    if perfil.get("tipo") == "red":
        flujos = (state.get("contenido_lote") or {}).get("flujos_minoritarios") or []
        elegidos = [(f["group_id"], f.get("motivos") or []) for f in flujos]
        factuales = {f["group_id"]: f.get("motivos_factuales") or [] for f in flujos}
    else:
        total = max(1, sum(g.get("conteo", 0) for g in grupos.values()))
        elegidos = []
        for gid, g in grupos.items():
            motivos = []
            if str((g.get("clave") or {}).get("severidad", "")).strip().lower() in _SEVERIDADES_ALTAS:
                motivos.append("severidad_alta")
            if g.get("conteo", 0) / total < 0.05:
                motivos.append("plantilla_minoritaria")
            if motivos:
                elegidos.append((gid, motivos))
    filas = _filas_por_grupo(state)
    salida, restantes = [], GRUPOS_SENAL_MAX_FILAS
    for gid, motivos in elegidos[:GRUPOS_SENAL_MAX_GRUPOS]:
        g = grupos.get(gid) or {}
        propias = filas.get(gid, [])[:max(0, restantes)]
        restantes -= len(propias)
        item = {"group_id": gid, "clave": g.get("clave"), "conteo": g.get("conteo"),
                "motivos": motivos, **({"n_nodos": g["n_nodos"]} if "n_nodos" in g else {})}
        if GRUPOS_MOTIVO_FACTUAL and factuales.get(gid):
            item["motivos_factuales"] = factuales[gid]
        referentes = referentes_de_grupo((state.get("memoria_grupos") or {}).get(gid))
        if MEMORIA_GRUPOS_ACTIVA and referentes:
            item["memoria"] = referentes
        item.update(filas=propias, filas_omitidas=max(0, (g.get("conteo") or 0) - len(propias)))
        salida.append(item)
    return salida


def resumen_dominante(state: LogGuardState) -> dict:
    """Composición del lote y sus grupos más grandes, para comparar cada grupo con señal."""
    perfil = (state.get("resumen_logs") or {}).get("perfil_lote") or {}
    grupos = sorted((g for g in state.get("grupos_evidencia") or [] if isinstance(g, dict)),
                    key=lambda g: -g.get("conteo", 0))[:3]
    composicion = ({k: perfil.get(k) for k in ("filas", "protocolos", "servicios", "estados")}
                   if perfil.get("tipo") == "red"
                   else {k: perfil.get(k) for k in ("filas", "severidades", "componentes", "nodos_distintos")})
    return {"composicion": composicion,
            "grupos_dominantes": [{"group_id": g["group_id"], "clave": g.get("clave"), "conteo": g.get("conteo")}
                                  for g in grupos]}
