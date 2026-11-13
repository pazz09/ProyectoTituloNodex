"""Definición del estado compartido del grafo (LogGuardState).

Migrado desde la celda 22 del notebook de Colab (sección "1. EL ESTADO DINÁMICO").
Usa typing_extensions.TypedDict (no typing.TypedDict) porque así lo hace el
notebook y porque el Informe (Tabla 8.9) lista typing-extensions>=4.0 como
dependencia explícita del prototipo.
"""

from typing import Annotated, List

from typing_extensions import TypedDict

from src.output_contract import EventoReconstruido, TecnicaAtribuida


def limpiar_o_acumular(actuales: list, nuevos: list):
    """Reducer para recordar el historial de fallos.

    Si el nodo emisor envía una lista vacía, se interpreta como "reiniciar"
    (p. ej. tras una corrección exitosa); si no, se acumula.
    """
    if nuevos == []:
        return []
    return actuales + nuevos


def acumular(actuales: list, nuevos: list):
    """Reducer de acumulación pura, sin el atajo "lista vacía = reiniciar" de
    `limpiar_o_acumular` -- acá una lista vacía significa "sin novedades en
    este nodo", no "borrar lo acumulado". Usado para las trazas de
    Plan-and-Execute (`historial_ejecucion`, `desviaciones_plan`,
    `historial_planes`), que deben sobrevivir intactas incluso a través de
    una replanificación."""
    return actuales + nuevos


class LogGuardState(TypedDict):
    resumen_logs: dict
    # --- metadatos del preprocesamiento v2 (Fase 9 del plan) ---
    # Deliberadamente NO se guardan los eventos normalizados completos: el
    # estado del grafo se serializa en cada checkpoint, así que crecería en
    # proporción al archivo de entrada. Acá van solo agregados y muestras
    # acotadas (§14 del plan, riesgo de uso de memoria).
    preprocessing_metadata: dict     # esquema, cobertura, decoders, productos, segmentos
    parsing_warnings: list           # advertencias del preprocesamiento
    raw_samples: list                # muestras de texto crudo, acotadas y filtradas
    # Catálogo acotado de registros observados para D-11, sin etiquetas/raw.
    evidencia_logs: list
    evidencia_logs_omitidos: int
    # --- NODEX final, Fase A (nov-2026) ---
    grupos_evidencia: list           # M6: grupos determinísticos G01.. con sus uids
    contenido_lote: dict             # M1: líneas (texto) o flujos minoritarios (red) para el triage
    veredicto_preliminar: str        # M8: incidente_seguridad / anomalia_operativa / normal (triage)
    justificacion_veredicto_preliminar: str
    invalid_evidence_group_count: int  # M6: grupos citados que no existen
    comandos_rechazados: Annotated[list, acumular]  # M7: comandos rechazados por el validador, con motivo
    # --- NODEX final, Fase B (nov-2026) ---
    casos_historicos: list           # B4: k casos históricos más parecidos (pipeline)
    historico_consulta: dict         # B4: representación consultada y patrones excluidos por solapamiento
    veredicto_consolidado: str       # veredicto del triage (o el corregido por el auditor, B2)
    consulta_mitre: str              # B3: texto de la hipótesis usado para consultar técnicas
    rag_omitido: str                 # B3: motivo si no se consultaron técnicas (sin hipótesis)
    diagnostico_inicial: str         # B2: diagnóstico antes de la corrección del auditor
    diagnostico_corregido: str       # B2: diagnóstico tras la corrección (evaluación del auditor)
    correcciones_auditor: int        # B2: correcciones aplicadas tras el auditor
    historial_correcciones: Annotated[list, acumular]  # B2: clase anterior y nueva por corrección
    # --- NODEX final, Fase B.1 (nov-2026) ---
    memoria_grupos: dict             # B.1-2: por grupo con señal, el grupo malicioso y el benigno más parecidos
    memoria_grupos_consulta: dict    # B.1-2: memoria usada, grupos excluidos por solapamiento
    evaluacion_grupos: list          # AUDITOR_REFORZADO: el auditor evalúa cada grupo con señal
    eventos_reconstruidos: list[EventoReconstruido]
    secuencia_temporal: list[str]
    tecnicas_atribuidas: list[TecnicaAtribuida]
    invalid_evidence_uid_count: int
    d11_warnings: list[str]
    telemetry: dict
    firma: str
    # --- Plan-and-Execute (agente_planificador, 11-sep-2026) ---
    # `plan` es la única fuente de verdad sobre qué se planificó; su
    # vocabulario de "accion" es {triage, rag, cve, mitigacion} -- selector,
    # validacion y auditoria son mecanismos internos del grafo, no pasos del
    # plan (ver docstring de agente_planificador.py). El campo "estado" de
    # cada paso se muta en vivo (pendiente -> ejecutado/omitido/fallido) por
    # `src/graph/plan_tracking.py`, no por los agentes.
    plan: dict
    plan_objetivo: str               # espejo de plan["objetivo"], para inyección directa en prompts
    # id del paso del PLAN (triage/rag/cve/mitigacion) ejecutado más
    # recientemente -- NO "el primer pendiente": durante Triage->RAG->Triage,
    # paso_actual apunta a "rag" mientras ese nodo corre, y vuelve a "triage"
    # en la segunda pasada. Los mecanismos internos (selector/validacion/
    # auditoria) no lo mueven.
    paso_actual: int
    # Un evento por cada nodo ejecutado (incluye mecanismos internos, con
    # step_id=None) -- se acumula SIEMPRE, incluso a través de
    # replanificaciones. Distintas visitas al mismo paso (p. ej. mitigación
    # reintentada) son entradas separadas con el mismo step_id.
    historial_ejecucion: Annotated[list, acumular]
    # rag/cve ejecutados sin estar contemplados en el plan vigente -- nunca
    # se insertan retroactivamente en plan["pasos"], quedan acá como
    # excepción explícita (accion, nodo, evidencia, motivo).
    desviaciones_plan: Annotated[list, acumular]
    # Una entrada por replanificación, con el plan reemplazado y un snapshot
    # de lo que produjo antes de resetear el estado activo (ver
    # `preparar_replanificacion` en agente_planificador.py).
    historial_planes: Annotated[list, acumular]
    replan_count: int
    diagnostico: str
    necesita_rag: bool               # Router 1: ¿va a ChromaDB?
    usar_cve: bool                   # Router 2: ¿va a NVD?
    razon_seleccion: str             # justificación del selector, para el reporte y la interfaz (10-sep-2026)
    contexto_rag: list
    tecnicas_mitre: list              # técnicas MITRE ATT&CK recuperadas por RAG estructurado (STIX) (3-sep-2026)
    cves_encontrados: list
    comandos_mitigacion: List[str]
    # bool | None en tiempo de ejecución: None = "aún no evaluado" (semilla
    # inicial y reseteo al replanificar -- nunca True por defecto, sería un
    # valor optimista fabricado). `not None` es `True` en Python, así que
    # router_validacion (`if not state["comandos_validos"] and ...`) sigue
    # funcionando sin cambios: None se comporta como "inválido todavía".
    comandos_validos: bool           # Router 3: ¿ciclo de corrección?
    motivos_rechazo: Annotated[List[str], limpiar_o_acumular]
    intentos_correccion: int         # evita loops infinitos en router_validacion
    confianza: float
    hay_incidente: bool              # veredicto de seguridad del auditor, independiente de confianza (3-sep-2026)
    hay_anomalia: bool               # veredicto de anomalía de sistema (seguridad u operativa) (3-sep-2026)
    evaluacion_auditor: str          # texto de justificación del auditor -- antes solo se imprimía (3-sep-2026)
    # --- señales de cobertura del Auditor (11-sep-2026) ---
    # `cobertura_auditor` es el juicio SEMÁNTICO crudo del LLM, sin mezclar
    # con nada. `cobertura_suficiente` es la señal DERIVADA que de verdad
    # gobierna router_finalizacion: cobertura_auditor AND NOT hay pasos
    # fallidos/pendientes en el plan. Separarlas es lo que permite auditar
    # si una replanificación se disparó por juicio del LLM, por una
    # verificación determinística, o por ambas (trazabilidad + evaluación
    # futura). bool | None en tiempo de ejecución -- None hasta que el
    # auditor corre, nunca True por defecto.
    cobertura_auditor: bool
    cobertura_suficiente: bool
    motivo_replanificacion: str
    requiere_replanificacion: bool   # espejo explícito de "not cobertura_suficiente", para el reporte
