"""Nodo LLM: agente_cazador (NODEX final, B1).

Examina SOLO lo minoritario del lote. En desarrollo (línea base A.1), el perfil
llevó las filas de los incidentes sigilosos hasta el triage y el auditor, pero
ninguno las evaluó con criterio de seguridad: los dos describían el
comportamiento dominante. Este agente tiene una única tarea: juzgar cada grupo
minoritario por sí mismo, comparándolo con lo dominante.

Entrada (determinística, `grupos_para_cazador`):
- logs de red: los grupos que el perfil marcó con alguna SEÑAL (barrido de
  puertos, servicio o protocolo minoritario, inversión de rol), con todas sus
  filas del catálogo;
- logs de texto: los grupos de severidad alta o de plantilla minoritaria;
- un resumen breve del comportamiento dominante, para comparar.

NO recibe el diagnóstico del triage: su juicio es independiente.

Salida: `hallazgos_cazador`, una entrada por grupo con explicación benigna,
explicación maliciosa u operativa, `nivel_sospecha` (alto/medio/bajo),
justificación y técnica MITRE candidata. Las reglas del prompt son generales:
no hay ejemplos tomados de casos de desarrollo.

Fase B.1 (cada parte con su interruptor):
- `CAZADOR_MOTIVO_FACTUAL`: cada grupo trae el motivo factual de su señal
  (`motivos_factuales`, conteos del lote calculados por el perfil).
- `CAZADOR_LISTA_PATRONES`: lista de verificación general de patrones de ataque
  observables en logs, basada en MITRE ATT&CK (`PATRONES_ATAQUE`), no en los
  casos; por cada grupo, `patron_lista` dice qué patrón calza o `ninguno`.
- `MEMORIA_GRUPOS_ACTIVA`: cada grupo con señal trae el grupo malicioso y el
  benigno más parecidos de la memoria de grupos (comparación, no votación).
"""

import json
import re

from src.llm import llm_json
from src.preprocessing.perfil_lote import _SEVERIDADES_ALTAS
from src.state import LogGuardState

_SISTEMA = (
    "Eres un analista de amenazas. Examinas SOLO los grupos minoritarios o señalados de un lote de "
    "logs, uno por uno, comparándolos con el comportamiento dominante del lote. Para cada grupo: "
    "(1) explicacion_benigna: la explicación legítima más plausible; "
    "(2) explicacion_alternativa: la explicación maliciosa u operativa (falla) más plausible; "
    "(3) nivel_sospecha: alto, medio o bajo; "
    "(4) justificacion: basada en campos concretos de las filas (puertos, protocolo, estado e historia "
    "de la conexión, bytes, duración, tiempos, severidad, componente, mensaje); "
    "(5) tecnica_candidata: un ID MITRE ATT&CK (Tdddd o Tdddd.ddd) si la explicación maliciosa es "
    "plausible, o null. Reglas: usa 'alto' solo si la explicación benigna NO es plausible con la evidencia "
    "observada. Que un grupo sea minoritario no lo hace sospechoso: el tráfico de infraestructura habitual "
    "(resolución de nombres, descubrimiento de red local, asignación de direcciones, sincronización de "
    "tiempo, difusión) no es sospechoso por ser poco frecuente. Tampoco descartes un grupo solo porque el "
    "resto del lote sea normal: evalúa cada grupo por sí mismo. No inventes grupos ni campos. "
    'Responde SOLO JSON: {"hallazgos": [{"group_id": "G01", "explicacion_benigna": "...", '
    '"explicacion_alternativa": "...", "nivel_sospecha": "alto|medio|bajo", "justificacion": "...", '
    '"tecnica_candidata": "T1046" o null}]}'
)


#: B.1-3b. Patrones de ataque observables en logs, tomados de MITRE ATT&CK (descripciones
#: generales de las técnicas, no de los casos). (id, comportamiento observable, técnicas).
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


def _instrucciones_b1() -> str:
    """Partes del prompt de la Fase B.1, según sus interruptores."""
    from src.config import CAZADOR_LISTA_PATRONES, CAZADOR_MOTIVO_FACTUAL, MEMORIA_GRUPOS_ACTIVA
    partes = []
    if CAZADOR_MOTIVO_FACTUAL:
        partes.append("Cada grupo trae motivos_factuales: el hecho del lote que hizo que se señalara.")
    if CAZADOR_LISTA_PATRONES:
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


def _formato_respuesta() -> str:
    from src.config import CAZADOR_LISTA_PATRONES
    patron = ('"patron_lista": "' + "|".join(IDS_PATRONES) + '", ') if CAZADOR_LISTA_PATRONES else ""
    return (' Responde SOLO JSON: {"hallazgos": [{"group_id": "G01", "explicacion_benigna": "...", '
            '"explicacion_alternativa": "...", "nivel_sospecha": "alto|medio|bajo", ' + patron
            + '"justificacion": "...", "tecnica_candidata": "T1046" o null}]}')


def _sistema() -> str:
    from src.config import CAZADOR_LISTA_PATRONES, CAZADOR_MOTIVO_FACTUAL, MEMORIA_GRUPOS_ACTIVA
    if not (CAZADOR_LISTA_PATRONES or CAZADOR_MOTIVO_FACTUAL or MEMORIA_GRUPOS_ACTIVA):
        return _SISTEMA
    base = _SISTEMA.split(" Responde SOLO JSON:")[0]
    return base + _instrucciones_b1() + _formato_respuesta()


def _filas_por_grupo(state: LogGuardState) -> dict:
    filas = {}
    for registro in state.get("evidencia_logs") or []:
        if isinstance(registro, dict) and registro.get("group_id"):
            filas.setdefault(registro["group_id"], []).append(
                {k: v for k, v in registro.items() if k not in ("group_id", "record_number", "line_end")})
    return filas


def grupos_para_cazador(state: LogGuardState) -> list[dict]:
    """Grupos que el cazador examina, con sus filas (vacío = no hay nada que cazar)."""
    from src.config import CAZADOR_MAX_FILAS, CAZADOR_MAX_GRUPOS, CAZADOR_MOTIVO_FACTUAL, MEMORIA_GRUPOS_ACTIVA
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
    salida, restantes = [], CAZADOR_MAX_FILAS
    for gid, motivos in elegidos[:CAZADOR_MAX_GRUPOS]:
        g = grupos.get(gid) or {}
        propias = filas.get(gid, [])[:max(0, restantes)]
        restantes -= len(propias)
        item = {"group_id": gid, "clave": g.get("clave"), "conteo": g.get("conteo"),
                "motivos": motivos, **({"n_nodos": g["n_nodos"]} if "n_nodos" in g else {})}
        if CAZADOR_MOTIVO_FACTUAL and factuales.get(gid):
            item["motivos_factuales"] = factuales[gid]                       # B.1-3a
        referentes = referentes_de_grupo((state.get("memoria_grupos") or {}).get(gid))
        if MEMORIA_GRUPOS_ACTIVA and referentes:
            item["memoria"] = referentes                                     # B.1-2
        item.update(filas=propias, filas_omitidas=max(0, (g.get("conteo") or 0) - len(propias)))
        salida.append(item)
    return salida


def resumen_dominante(state: LogGuardState) -> dict:
    perfil = (state.get("resumen_logs") or {}).get("perfil_lote") or {}
    grupos = sorted((g for g in state.get("grupos_evidencia") or [] if isinstance(g, dict)),
                    key=lambda g: -g.get("conteo", 0))[:3]
    composicion = ({k: perfil.get(k) for k in ("filas", "protocolos", "servicios", "estados")}
                   if perfil.get("tipo") == "red"
                   else {k: perfil.get(k) for k in ("filas", "severidades", "componentes", "nodos_distintos")})
    return {"composicion": composicion,
            "grupos_dominantes": [{"group_id": g["group_id"], "clave": g.get("clave"), "conteo": g.get("conteo")}
                                  for g in grupos]}


def normalizar_hallazgos(respuesta, examinados: set) -> list[dict]:
    from src.config import NIVELES_SOSPECHA
    hallazgos, vistos = [], set()
    items = respuesta.get("hallazgos") if isinstance(respuesta, dict) else None
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        gid = str(item.get("group_id") or "").strip()
        nivel = str(item.get("nivel_sospecha") or "").strip().lower()
        if gid not in examinados or gid in vistos or nivel not in NIVELES_SOSPECHA:
            continue
        vistos.add(gid)
        tecnica = item.get("tecnica_candidata")
        tecnica = tecnica.strip().upper() if isinstance(tecnica, str) else None
        if tecnica and not re.fullmatch(r"T\d{4}(?:\.\d{3})?", tecnica):
            tecnica = None
        patron = str(item.get("patron_lista") or "").strip().lower()
        hallazgos.append({"group_id": gid, "nivel_sospecha": nivel,
                          "patron_lista": patron if patron in IDS_PATRONES else ("no_indicado" if not patron
                                                                                  else "fuera_de_lista"),
                          "explicacion_benigna": str(item.get("explicacion_benigna") or "")[:600],
                          "explicacion_alternativa": str(item.get("explicacion_alternativa") or "")[:600],
                          "justificacion": str(item.get("justificacion") or "")[:600],
                          "tecnica_candidata": tecnica})
    return hallazgos


def agente_cazador(state: LogGuardState) -> dict:
    print("\n🔎 [Agente Cazador] Examinando eventos minoritarios...")
    grupos = grupos_para_cazador(state)
    user_content = ("COMPORTAMIENTO DOMINANTE DEL LOTE (para comparar):\n"
                    + json.dumps(resumen_dominante(state), ensure_ascii=False)
                    + "\n\nGRUPOS A EXAMINAR (uno por uno, con todas sus filas):\n"
                    + json.dumps(grupos, ensure_ascii=False))
    respuesta = llm_json(user_content, system=_sistema())
    hallazgos = normalizar_hallazgos(respuesta, {g["group_id"] for g in grupos})
    altos = sum(1 for h in hallazgos if h["nivel_sospecha"] == "alto")
    print(f"   → {len(hallazgos)} hallazgos ({altos} alto) sobre {len(grupos)} grupos.")
    return {"hallazgos_cazador": hallazgos, "cazador_ejecutado": True}
