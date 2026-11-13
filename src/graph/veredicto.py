"""Lógica determinística del veredicto (NODEX final, B2 y B3). Sin LLM.

- `veredicto_consolidado`: el veredicto preliminar del triage. Se calcula antes de la
  mitigación y es la referencia que el router de coherencia compara con la clase final
  del auditor (B2).
- `texto_hipotesis`: lo que se usa para consultar técnicas MITRE (B3): el diagnóstico,
  si el veredicto consolidado es un incidente de seguridad. `None` si no hay hipótesis
  de seguridad (en ese caso no se consultan técnicas).
- `clase_final`: la clase del veredicto final del auditor, para el router de
  coherencia (B2).
"""

from src.output_contract import clasificacion_detallada


def veredicto_consolidado(state) -> str | None:
    return state.get("veredicto_preliminar")


def texto_hipotesis(state) -> str | None:
    if veredicto_consolidado(state) != "incidente_seguridad":
        return None
    return str(state.get("diagnostico") or "").strip() or None


def clase_final(state) -> str | None:
    return clasificacion_detallada(state)
