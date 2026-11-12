"""Lógica determinística del veredicto (NODEX final, B1, B2 y B3). Sin LLM.

- `veredicto_consolidado`: `incidente_seguridad` si el triage lo dice o si el
  cazador tiene al menos un hallazgo `alto`; si no, el veredicto preliminar del
  triage. Se calcula antes de la mitigación.
- `texto_hipotesis`: lo que se usa para consultar técnicas MITRE (B3): el
  diagnóstico más los hallazgos `alto` y `medio` del cazador. `None` si no hay
  hipótesis de seguridad (en ese caso no se consultan técnicas).
- `clase_final`: la clase del veredicto final del auditor, para el router de
  coherencia (B2).
"""

from src.output_contract import clasificacion_detallada


def hallazgos_de_nivel(state, *niveles) -> list[dict]:
    return [h for h in state.get("hallazgos_cazador") or []
            if isinstance(h, dict) and h.get("nivel_sospecha") in niveles]


def veredicto_consolidado(state) -> str | None:
    preliminar = state.get("veredicto_preliminar")
    if preliminar == "incidente_seguridad" or hallazgos_de_nivel(state, "alto"):
        return "incidente_seguridad"
    return preliminar


def texto_hipotesis(state) -> str | None:
    hallazgos = hallazgos_de_nivel(state, "alto", "medio")
    if veredicto_consolidado(state) != "incidente_seguridad" and not hallazgos:
        return None
    partes = [str(state.get("diagnostico") or "").strip()]
    for h in hallazgos:
        partes.append(" ".join(filter(None, [h.get("explicacion_alternativa"), h.get("justificacion"),
                                             h.get("tecnica_candidata")])))
    texto = "\n".join(p for p in partes if p)
    return texto or None


def clase_final(state) -> str | None:
    return clasificacion_detallada(state)
