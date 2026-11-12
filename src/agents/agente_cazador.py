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


def _filas_por_grupo(state: LogGuardState) -> dict:
    filas = {}
    for registro in state.get("evidencia_logs") or []:
        if isinstance(registro, dict) and registro.get("group_id"):
            filas.setdefault(registro["group_id"], []).append(
                {k: v for k, v in registro.items() if k not in ("group_id", "record_number", "line_end")})
    return filas


def grupos_para_cazador(state: LogGuardState) -> list[dict]:
    """Grupos que el cazador examina, con sus filas (vacío = no hay nada que cazar)."""
    from src.config import CAZADOR_MAX_FILAS, CAZADOR_MAX_GRUPOS
    perfil = (state.get("resumen_logs") or {}).get("perfil_lote") or {}
    grupos = {g["group_id"]: g for g in state.get("grupos_evidencia") or [] if isinstance(g, dict)}
    if perfil.get("tipo") == "red":
        elegidos = [(f["group_id"], f.get("motivos") or [])
                    for f in (state.get("contenido_lote") or {}).get("flujos_minoritarios") or []]
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
        salida.append({"group_id": gid, "clave": g.get("clave"), "conteo": g.get("conteo"),
                       "motivos": motivos, **({"n_nodos": g["n_nodos"]} if "n_nodos" in g else {}),
                       "filas": propias, "filas_omitidas": max(0, (g.get("conteo") or 0) - len(propias))})
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
        hallazgos.append({"group_id": gid, "nivel_sospecha": nivel,
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
    respuesta = llm_json(user_content, system=_SISTEMA)
    hallazgos = normalizar_hallazgos(respuesta, {g["group_id"] for g in grupos})
    altos = sum(1 for h in hallazgos if h["nivel_sospecha"] == "alto")
    print(f"   → {len(hallazgos)} hallazgos ({altos} alto) sobre {len(grupos)} grupos.")
    return {"hallazgos_cazador": hallazgos, "cazador_ejecutado": True}
