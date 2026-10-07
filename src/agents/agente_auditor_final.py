"""Nodo LLM: agente_auditor_final.

Migrado desde la celda 22 del notebook de Colab.

Evalúa la calidad global del análisis y asigna el nivel de confianza final.
Si `confianza < CONFIDENCE_THRESHOLD`, el resultado debe tratarse como
"requiere escalamiento a analista humano" (lo resuelve quien consuma el
estado final del grafo, ver `src/pipeline.py`).

`hay_incidente` (agregado 3-sep-2026): veredicto binario explícito de si el
lote representa una anomalía/incidente real -- **independiente** de
`confianza`. Antes de este campo, `src/tools/eval_deteccion.py` (evaluación
de Precisión/Recall/F1, §8.6.2) usaba `confianza >= CONFIDENCE_THRESHOLD`
como proxy de "el agente detectó un incidente", pero `confianza` mide la
certeza del auditor sobre SU PROPIO análisis, no la clasificación en sí --
un "esto está todo normal" bien fundamentado da confianza alta (p. ej.
1.00) y ese proxy lo contaba como "anómalo", produciendo un clasificador
que en la práctica solo podía predecir "normal" cuando el agente dudaba de
sí mismo. Hallazgo real de la primera corrida de evaluación sobre BGL
(3-sep-2026, 4 lotes): precisión 0.25 / recall 1.00, exactamente lo que da
un clasificador que siempre predice "anómalo". `hay_incidente` responde la
pregunta que la evaluación necesita medir directamente, sin inferirla de
un campo que mide otra cosa.

`hay_anomalia` (agregado 3-sep-2026, mismo día, segunda ronda): con
`hay_incidente` ya funcionando, la primera corrida real de la evaluación
sobre BGL dio recall 0.0 -- el auditor tenía razón (distinguió
correctamente un problema real de hardware/kernel de un ataque; p. ej.
"al tratarse de un problema de estabilidad y mantenimiento de hardware, no
constituye un incidente de seguridad, aunque sí una anomalía operativa que
requiere atención"), pero el ground truth de BGL (y de HDFS) marca
cualquier evento anómalo del sistema, no solo los de seguridad. La
pregunta del auditor y la etiqueta del dataset median cosas distintas.
`hay_anomalia` responde "¿el sistema se está comportando de forma anómala
u operacionalmente irregular, sea o no un problema de seguridad?" --
`hay_incidente` sigue preguntando específicamente por seguridad, y toda
anomalía de seguridad real también debería marcar `hay_anomalia=true` (la
inversa no aplica: un problema de hardware es `hay_anomalia=true` pero
`hay_incidente=false`). `src/tools/eval_deteccion.py` usa el campo que
corresponde a lo que cada dataset realmente etiqueta: `hay_anomalia` para
BGL/HDFS (datasets de anomalías de sistema), `hay_incidente` para datasets
de seguridad real (p. ej. UWF-ZeekDataFall22, con tácticas MITRE, aún sin
implementar). Ver el docstring de `eval_deteccion.py` para el detalle.

`evaluacion_auditor` (agregado 3-sep-2026, mismo día, tercera ronda): el
texto de justificación que el LLM ya devolvía en `evaluacion` se imprimía
por consola pero nunca se guardaba en el estado -- así que la primera
corrida real de 8 lotes (BGL+HDFS) no dejó registro persistente de POR QUÉ
el auditor clasificó cada lote como clasificó (necesario para explicar,
p. ej., el falso positivo real de `hdfs_negativo_001` en el informe). Se
propaga ahora por `LogGuardState`, `pipeline.py`, `log_runner.py` y se
guarda en `results/eval_deteccion_*.json` junto al resto del veredicto.

`cobertura_auditor` / `cobertura_suficiente` (agregados 11-sep-2026,
Plan-and-Execute): el auditor es también quien decide si corresponde
replanificar, pero esa decisión NO depende únicamente de su propio juicio.
`cobertura_auditor` es el juicio semántico crudo del LLM ("¿la evidencia
alcanza para una conclusión?"), sin mezclar con nada. `cobertura_suficiente`
es la señal DERIVADA que de verdad usa `router_finalizacion`: combina ese
juicio con una verificación determinística sobre `state["plan"]` (¿quedó
algún paso "fallido" o "pendiente"?). Separarlas permite auditar después si
una replanificación se disparó por el LLM, por la verificación
determinística, o por ambas -- información que `hay_incidente`/`hay_anomalia`
ya demostraron que vale la pena mantener separada en vez de colapsarla en
un único booleano.
"""

from src.llm import llm_json
from src.output_contract import PROMPT_D11, contexto_d11, normalizar_d11
from src.preprocessing.prompt_context import contexto_preprocesamiento
from src.state import LogGuardState


def agente_auditor_final(state: LogGuardState) -> dict:
    print("\n🕵️ [Agente Auditor] Evaluando calidad de la solución...")

    sys_instruction = (
        "Evalúa la solución de seguridad propuesta. Considera: "
        "precisión del diagnóstico, relevancia de los comandos y evidencia disponible. "
        "Responde CUATRO cosas por separado, sin confundirlas entre sí: "
        "(1) hay_anomalia: ¿el sistema se está comportando de forma anómala o "
        "irregular, sea o no un problema de seguridad? (p. ej. una falla de "
        "hardware, un error de infraestructura o un fallo de replicación "
        "también cuentan como anomalía, aunque no sean un ataque). "
        "(2) hay_incidente: de las anomalías anteriores, ¿esta es "
        "específicamente un incidente o amenaza de seguridad real (intrusión, "
        "abuso, actividad maliciosa)? Una anomalía puramente operativa (p. ej. "
        "mantenimiento de hardware) es hay_anomalia=true pero hay_incidente=false. "
        "(3) confianza: qué tan seguro estás de tu propia evaluación -- un "
        "diagnóstico de 'todo normal' bien fundamentado debe tener confianza "
        "alta y tanto hay_anomalia como hay_incidente en false. "
        "(4) cobertura_auditor: ¿la evidencia reunida (diagnóstico, CVEs, "
        "contexto histórico, comandos validados) alcanza para sostener esta "
        "conclusión, o falta investigar algo concreto para poder afirmarla con "
        "solidez? Esto es independiente de confianza: puedes estar muy seguro "
        "de una conclusión basada en poca evidencia real. Si cobertura_auditor "
        "es false, explica en motivo_cobertura qué falta investigar. "
        "No confundas estos cuatro campos entre sí. "
        'Responde SOLO en JSON: {"confianza": 0.0-1.0, "hay_anomalia": true/false, '
        '"hay_incidente": true/false, "evaluacion": "...", '
        '"cobertura_auditor": true/false, "motivo_cobertura": "..."}'
    )
    sys_instruction += PROMPT_D11
    # La calidad de la evidencia depende de cuánto del lote se entendió: un
    # diagnóstico sobre un lote con 30 % de cobertura no merece la misma
    # confianza que uno sobre un lote completamente decodificado. Sin este
    # dato el auditor no tiene cómo saberlo (Fase 10 del plan).
    contexto_pre = contexto_preprocesamiento(
        state.get("preprocessing_metadata"),
        state.get("parsing_warnings"),
    )
    user_content = (
        f"DIAGNÓSTICO: {state.get('diagnostico')}\n"
        f"COMANDOS VALIDADOS: {state.get('comandos_mitigacion')}\n"
        f"CVEs ENCONTRADOS: {len(state.get('cves_encontrados', []))} CVEs\n"
        f"CONTEXTO RAG: {'Sí' if state.get('contexto_rag') else 'No'}"
        + (f"\n\n{contexto_pre}" if contexto_pre else "")
    )

    user_content += contexto_d11(state)
    respuesta = llm_json(user_content, system=sys_instruction)
    d11 = normalizar_d11(respuesta, state.get("evidencia_logs"))
    d11["invalid_evidence_uid_count"] += state.get("invalid_evidence_uid_count", 0) or 0
    d11["d11_warnings"] = list(state.get("d11_warnings") or []) + d11["d11_warnings"]
    if not isinstance(respuesta, dict):
        respuesta = {}
    try:
        confianza = float(respuesta.get("confianza", 0.5))
    except Exception:
        confianza = 0.5

    hay_incidente = respuesta.get("hay_incidente")
    if not isinstance(hay_incidente, bool):
        # Respaldo si el LLM no devuelve el campo (respuesta vieja/malformada):
        # antes de que existiera hay_incidente, esto es lo más parecido a lo
        # que había -- no ideal, pero mejor que reventar. Se loggea para que
        # se note si pasa seguido (indicaría que el prompt no se está
        # respetando, no un caso esperado).
        print("   ⚠️ El auditor no devolvió 'hay_incidente' -- usando confianza como respaldo.")
        hay_incidente = confianza >= 0.70

    hay_anomalia = respuesta.get("hay_anomalia")
    if not isinstance(hay_anomalia, bool):
        # Mismo respaldo que hay_incidente. Si el auditor sí marcó un
        # incidente de seguridad, eso implica una anomalía -- usarlo antes
        # de caer a confianza, que es una señal más débil.
        print("   ⚠️ El auditor no devolvió 'hay_anomalia' -- usando hay_incidente/confianza como respaldo.")
        hay_anomalia = hay_incidente or (confianza >= 0.70)

    evaluacion = respuesta.get("evaluacion", "")

    cobertura_auditor = respuesta.get("cobertura_auditor")
    if not isinstance(cobertura_auditor, bool):
        # Respaldo si el LLM no devuelve el campo (prompt viejo/respuesta
        # malformada): asumir que sí alcanza, no al revés -- lo contrario
        # dispararía una replanificación en cualquier respuesta que no siga
        # el prompt al pie de la letra, y MAX_REPLANS=1 es un recurso escaso.
        cobertura_auditor = True

    plan = state.get("plan") or {}
    pasos = plan.get("pasos", [])
    fallidos = [p for p in pasos if p.get("estado") == "fallido"]
    pendientes = [p for p in pasos if p.get("estado") == "pendiente"]
    cobertura_suficiente = cobertura_auditor and not fallidos and not pendientes

    notas_deterministicas = []
    if fallidos:
        notas_deterministicas.append(f"pasos fallidos: {[p['accion'] for p in fallidos]}")
    if pendientes:
        notas_deterministicas.append(f"pasos sin ejecutar: {[p['accion'] for p in pendientes]}")
    motivo_llm = respuesta.get("motivo_cobertura") if not cobertura_auditor else None
    motivo_replanificacion = " | ".join(filter(None, [motivo_llm, *notas_deterministicas]))

    print(f"   → Confianza final: {confianza:.2f} | hay_anomalia={hay_anomalia} | "
          f"hay_incidente={hay_incidente} | cobertura_suficiente={cobertura_suficiente} | {evaluacion}")
    return {
        **d11,
        "confianza": confianza,
        "hay_anomalia": hay_anomalia,
        "hay_incidente": hay_incidente,
        "evaluacion_auditor": evaluacion,
        "cobertura_auditor": cobertura_auditor,
        "cobertura_suficiente": cobertura_suficiente,
        "motivo_replanificacion": motivo_replanificacion,
        "requiere_replanificacion": not cobertura_suficiente,
    }
