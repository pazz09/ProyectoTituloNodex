"""Vocabularios cerrados del protocolo experimental.

Son tuplas de constantes, no `enum.Enum`, por consistencia con el resto del
repositorio (`SEVERIDADES_ADVERTENCIA` en `src/preprocessing/models.py`,
`MODOS_PARSING` en `src/config.py`): se serializan como strings planos en
JSON y se validan en el `__post_init__` de cada contrato, que lanza un
error nombrando el campo.

Cada vocabulario cerrado existe para que el código **no tenga que inventar
un criterio** cuando reciba un valor inesperado: lo rechaza.
"""

# --- arquitecturas comparadas (la variable experimental) -------------------
# `nodex_multiagente`: el grafo completo de 8 nodos (5 agentes LLM + 3
#   herramientas), tal como corre en producción.
# `gemini_externo`: Gemini usado DIRECTAMENTE, con un solo prompt y sin
#   RAG, sin herramientas y sin estado LangGraph. Es la pseudo-ablación que
#   define el proyecto (decisión del 7-oct-2026): compara el sistema
#   completo contra el modelo desnudo, no aísla una variable.
# `agente_unico`: el agente único INTEGRADO (`src/single_agent.py`), que sí
#   vive dentro de NODEX y reutiliza su preprocesamiento. Se conserva en el
#   vocabulario porque existe en el sistema, pero la campaña automatizada no
#   lo corre: la pseudo-ablación se hace con `gemini_externo`.
# `baseline_reglas`: el clasificador determinístico sin LLM
#   (`src/tools/baseline_reglas.py`), comparación interna determinística.
ARQUITECTURAS = ("nodex_multiagente", "gemini_externo", "agente_unico",
                 "baseline_reglas")

# --- datasets --------------------------------------------------------------
DATASETS = ("hdfs", "bgl", "uwf")

# --- tipo de pregunta de detección (Fase 1, acción 1 del plan) -------------
# La distinción es obligatoria: HDFS y BGL etiquetan anomalías DE SISTEMA,
# no ataques. Comparar `hay_incidente` contra esas etiquetas mide la
# pregunta equivocada (ya ocurrió: dio recall 0,0 en BGL por una razón
# metodológica, no por una falla del modelo). UWF sí etiqueta tráfico
# malicioso.
#
# `operativa`  -> ¿el sistema se comporta de forma anómala?  (HDFS, BGL)
# `seguridad`  -> ¿hay actividad maliciosa?                  (UWF)
TIPOS_DETECCION = ("operativa", "seguridad")

# Campo del estado final de NODEX que responde cada pregunta. El evaluador
# debe leer el campo que corresponde al tipo declarado por el caso y
# rechazar la comparación si no coincide.
CAMPO_VEREDICTO_POR_TIPO = {
    "operativa": "hay_anomalia",
    "seguridad": "hay_incidente",
}

# --- clasificación del contrato común de salida ----------------------------
# Vocabulario fijado por el plan para el output común (UWF/ERR). Para los
# datasets operativos se usa el mismo par, leído como
# anómalo/normal en vez de malicioso/benigno: la etiqueta del dataset y el
# tipo de detección del caso definen cómo se interpreta.
CLASIFICACIONES = ("BENIGN", "MALICIOUS")

# Etiquetas internas de la referencia de detección, heredadas de
# `src/tools/eval_deteccion.py` para no romper el evaluador existente.
ETIQUETAS_DETECCION = ("normal", "anomalo")

# --- dimensiones evaluadas (el formulario de preparación) ------------------
# D1-D5 son dimensiones POR CASO. La comparación con el agente único (D6 en
# el formulario) no es una dimensión de caso: es una comparación entre
# arquitecturas que se calcula al agregar (ver `docs/experimentacion/
# protocolo.md`, §7). Modelarla como dimensión por caso llevaría a medir
# dos veces lo mismo.
DIMENSIONES = (
    "deteccion",        # D1
    "reconstruccion",   # D2
    "mitre",            # D3
    "reporte",          # D4
    "consumo",          # D5
)

# --- estado de una dimensión en un caso concreto --------------------------
# Ninguno de estos cuatro estados puede convertirse en un acierto ni en un
# caso normal. Se cuentan y se informan por separado (plan, Fase 1 acción 5).
#
# `evaluable`            -> hay salida y hay referencia: se puede puntuar.
# `no_aplica`            -> la dimensión no corresponde a este caso POR
#                           DISEÑO (p. ej. MITRE en HDFS, que no trae
#                           etiquetas ATT&CK). Fuera de todo denominador.
# `referencia_pendiente` -> la dimensión sí corresponde, pero la anotación
#                           humana todavía no está aprobada. Fuera de los
#                           denominadores y bloquea el cierre de esa
#                           dimensión.
# `fallido`              -> la ejecución no terminó (error de API, caída,
#                           timeout). No hay predicción que evaluar.
# `no_evaluable`         -> la ejecución terminó pero la salida no cumple el
#                           contrato (falta el veredicto booleano, JSON mal
#                           formado, falta el reporte). Se separa de
#                           `fallido` porque la causa es distinta: una es de
#                           ejecución, la otra de contrato de salida.
ESTADOS_DIMENSION = (
    "evaluable",
    "no_aplica",
    "referencia_pendiente",
    "fallido",
    "no_evaluable",
)

# Estados que NUNCA entran en una matriz de confusión ni en un promedio de
# calidad. Se exponen como conteos propios.
ESTADOS_NO_PUNTUABLES = (
    "no_aplica",
    "referencia_pendiente",
    "fallido",
    "no_evaluable",
)

# --- resultado operacional de una ejecución completa ----------------------
# Distinto del estado por dimensión: una corrida puede completarse y aun así
# producir una salida `no_evaluable` en una dimensión.
ESTADOS_EJECUCION = ("completa", "error_api", "error_preprocesamiento",
                     "error_contrato", "timeout", "interrumpida")

# --- granularidad de la atribución MITRE ----------------------------------
# El plan prohíbe inferir una subtécnica para completar el ground truth: si
# la referencia no la trae, la dimensión queda `no_aplica` en ese nivel.
NIVELES_MITRE = ("tactica", "tecnica", "subtecnica")

# --- particiones ----------------------------------------------------------
# `desarrollo` existe para depurar y para el piloto. Las métricas que se
# reportan salen exclusivamente de `evaluacion`.
PARTICIONES = ("desarrollo", "evaluacion")
