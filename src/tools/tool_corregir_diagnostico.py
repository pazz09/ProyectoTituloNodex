"""Nodo Tool: tool_corregir_diagnostico (NODEX final, B2). Determinístico, sin LLM.

Lo activa `router_coherencia` cuando la clase del veredicto final del auditor
(`incidente_seguridad` / `anomalia_operativa` / `normal`) difiere del
`veredicto_consolidado` con que se diseñó la mitigación. Sin este ciclo, el
reporte podía mostrar un diagnóstico que contradecía al veredicto sin
explicarlo, y comandos diseñados para un veredicto que el auditor descartó.

Qué hace:
- guarda el diagnóstico original en `diagnostico_inicial` (solo la primera vez);
- fija `diagnostico` y `diagnostico_corregido` con la evaluación del auditor;
- adopta la clase del auditor como nuevo `veredicto_consolidado`, para que la
  mitigación se rediseñe con ella;
- reinicia el contador del ciclo de comandos para que la validación vuelva a
  correr completa;
- registra la corrección (clase anterior y nueva) en `historial_correcciones`.

Después el grafo vuelve a mitigación -> validación -> auditor. El tope es
`MAX_CORRECCIONES_AUDITOR` (lo controla el router).
"""

from src.graph.veredicto import clase_final
from src.state import LogGuardState


def tool_corregir_diagnostico(state: LogGuardState) -> dict:
    anterior = state.get("veredicto_consolidado")
    nueva = clase_final(state)
    numero = (state.get("correcciones_auditor") or 0) + 1
    corregido = (state.get("evaluacion_auditor") or "").strip() or state.get("diagnostico") or ""
    print(f"\n♻️ [Corrección] El auditor cambió el veredicto ({anterior} -> {nueva}). "
          f"Rediseñando la mitigación (corrección {numero}).")
    return {
        "diagnostico_inicial": state.get("diagnostico_inicial") or state.get("diagnostico") or "",
        "diagnostico": corregido,
        "diagnostico_corregido": corregido,
        "veredicto_consolidado": nueva,
        "correcciones_auditor": numero,
        "historial_correcciones": [{"correccion": numero, "clase_anterior": anterior, "clase_nueva": nueva}],
        "intentos_correccion": 0,
        "comandos_validos": None,
        "motivos_rechazo": [],
    }
