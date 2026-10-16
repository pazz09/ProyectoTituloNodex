"""Carga de variables de entorno y constantes globales del sistema.

Migrado desde las celdas 4 y 7 del notebook de Colab (`LLM_Agente_INICIO.ipynb`).
En Colab las keys se leían desde `google.colab.userdata`; en este repo se leen
únicamente desde variables de entorno (`.env`, ver `.env.example`).
"""

import os

from dotenv import load_dotenv

load_dotenv()

# --- API keys ---
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
ABUSEIPDB_API_KEY = os.environ.get("ABUSEIPDB_API_KEY")  # opcional: fallback local si falta
NVD_API_KEY = os.environ.get("NVD_API_KEY")  # opcional: rate limit bajo si falta

# --- Motor LLM ---
# El Informe de Seminario (fuente de verdad de la arquitectura, sección 8.3.2 y
# Tabla 8.2) especifica gemini-2.5-pro para los 4 agentes LLM, temperatura 0.
# El notebook prototipo (LLM_Agente_INICIO.ipynb) corrió con gemini-2.5-flash-lite
# -- una decisión de prototipado (costo/cuota), no la especificación final.
#
# DESVIACIÓN FORZADA (23-ago-2026, confirmada de nuevo el 1-sep-2026 CON
# cuenta pagada): la familia 2.5 completa (pro, flash, flash-lite) devuelve
# 404 "no longer available to new users" -- Google restringe esos modelos
# por capacidad/antigüedad de la cuenta, no por facturación; pagar la API no
# la desbloqueó. Es una restricción definitiva para este proyecto, no una
# limitación temporal del tier gratuito.
#
# DECISIÓN FINAL (1-sep-2026), con cuenta pagada y sin límites de tier
# gratuito, medida con 6 corridas reales (HDFS/BGL, 7/7 nodos cada una):
#   - PRINCIPAL: gemini-3.1-pro-preview -- 0 fallas en 2 corridas, confianza
#     0.95 en ambas. Es el más caro (~USD 0.05/corrida chica; extrapolado a
#     los datasets completos del §9 -- HDFS 11.2M + BGL 4.7M líneas --,
#     ~USD 406) pero el de mejor calidad/estabilidad medida.
#   - RESPALDO: gemini-3.6-flash -- 0 fallas en 4 corridas, confianza
#     0.90-0.95. ~3.4x más barato que el principal (~USD 120 extrapolado a
#     los mismos datasets). Reemplaza a gemini-3.7-flash (el default
#     anterior), que fue el ÚNICO modelo que falló en las pruebas reales de
#     esta ronda (86s de latencia en un prompt trivial, tras un 503 de 64s).
# Ambos se seleccionan por versión explícita (no alias "-latest") para que
# las corridas del informe sean reproducibles.
#
# El sistema llama primero a LLM_MODEL_PRIMARY; si agota sus reintentos por
# un error reconocido (cuota o transitorio -- ver `_generate_con_fallback`
# en `src/llm.py`), reintenta automáticamente con LLM_MODEL_FALLBACK antes
# de darse por vencido. Ver README, sección "Modelo LLM en la práctica".
LLM_MODEL_PRIMARY = os.environ.get("LLM_MODEL_PRIMARY", "gemini-3.1-pro-preview")
LLM_MODEL_FALLBACK = os.environ.get("LLM_MODEL_FALLBACK", "gemini-3.6-flash")
TEMPERATURE = float(os.environ.get("TEMPERATURE", "0"))
# LLM_SIN_RESPALDO (opt-in) apaga el cambio al modelo de respaldo; se define
# más abajo, junto a los demás helpers de variables de entorno.

# --- Reintentos ante errores transitorios de la API (ver src/llm.py) ---
# Calibrado para cuenta CON CRÉDITOS (1-sep-2026): sin los límites del tier
# gratuito, no hay razón para ser conservador con los reintentos -- el techo
# de backoff (BACKOFF_MAX) evita esperas indefinidamente largas ante una
# racha de 503, y el jitter (BACKOFF_JITTER) evita que reintentos
# simultáneos (p. ej. varios nodos del grafo) se sincronicen contra la API.
# TIMEOUT_SOLICITUD_SEG cubre el caso visto el 1-sep-2026 con
# gemini-3.7-flash: una solicitud colgada 86s sin fallar ni responder --
# antes no había timeout explícito, así que ese caso no activaba ningún
# reintento.
MAX_REINTENTOS_TRANSITORIO = int(os.environ.get("MAX_REINTENTOS_TRANSITORIO", "5"))
BACKOFF_INICIAL = float(os.environ.get("BACKOFF_INICIAL", "2.0"))
BACKOFF_MAX = float(os.environ.get("BACKOFF_MAX", "30.0"))
BACKOFF_JITTER = float(os.environ.get("BACKOFF_JITTER", "0.25"))
MAX_REINTENTOS_CUOTA_MINUTO = int(os.environ.get("MAX_REINTENTOS_CUOTA_MINUTO", "3"))
TIMEOUT_SOLICITUD_SEG = float(os.environ.get("TIMEOUT_SOLICITUD_SEG", "300"))

# --- Umbrales de decisión ---
CONFIDENCE_THRESHOLD = float(os.environ.get("CONFIDENCE_THRESHOLD", "0.70"))  # bajo esto -> escala a humano
AUTO_PROMOTE = float(os.environ.get("AUTO_PROMOTE", "0.90"))  # conf >= esto -> promueve a attack_patterns

# --- Cotas del ciclo Plan-and-Execute (agente_planificador, router_finalizacion) ---
# MAX_PLAN_STEPS acota los pasos del plan: el vocabulario cerrado de acciones
# planificables tiene 4 miembros (triage, rag, cve, mitigacion -- selector,
# validacion y auditoria son mecanismos internos del grafo, no pasos del
# plan), así que 6 deja margen de sobra sin necesidad de subirlo.
MAX_PLAN_STEPS = int(os.environ.get("MAX_PLAN_STEPS", "6"))
MAX_REPLANS = int(os.environ.get("MAX_REPLANS", "1"))

# --- Ciclo de corrección de comandos (router_validacion del grafo) ---
MAX_INTENTOS_CORRECCION = int(os.environ.get("MAX_INTENTOS_CORRECCION", "2"))

# --- Reputación de IPs (categorización por score AbuseIPDB 0..100) ---
SCORE_MALICIOSO = int(os.environ.get("SCORE_MALICIOSO", "75"))  # score >= esto -> "malicioso"
SCORE_SOSPECHOSO = int(os.environ.get("SCORE_SOSPECHOSO", "25"))  # score >= esto -> "sospechoso"
IP_CACHE_PATH = os.environ.get("IP_CACHE_PATH", "./data/ip_reputation_cache.json")

# --- Acotamiento del prompt de triage (costo, ver README "Manejo de cuota") ---
# Hallazgo real (25-ago-2026): el costo en tokens del prompt de
# `agente_analista_triage` escala con la cantidad de IPs DISTINTAS del lote
# -- serializaba `por_ip`/`ips_distintas`/`reputacion_ips` completos -- no
# con el número de líneas de log. HDFS (202 IPs) disparó 58 289 tokens de
# entrada vs. 1 096 de BGL (2 IPs), para lotes del mismo tamaño (2000
# líneas). Ver `src/tools/resumen_prompt.py`: se incluyen en detalle las
# `TOP_N_IPS_PROMPT` IPs más activas, más cualquier IP con reputación
# sospechosa/maliciosa aunque tenga poca actividad; el resto se agrega en
# un solo resumen. `n_ips_distintas` nunca se trunca -- el LLM siempre ve
# la escala real del incidente.
TOP_N_IPS_PROMPT = int(os.environ.get("TOP_N_IPS_PROMPT", "20"))

# --- Acotamiento del contexto de preprocesamiento en el prompt (Fase 2 del
# cierre de auditoría, 23-sep-2026, hallazgo A2) ---
# Tope de caracteres para `contexto_preprocesamiento()`
# (src/preprocessing/prompt_context.py), que ahora se adjunta también en la
# PRIMERA pasada del triage, no solo en la segunda. Sus campos son
# distribuciones de baja cardinalidad (decoders, severidades, categorías,
# perfiles) que no escalan con el tamaño del lote -- a diferencia de
# TOP_N_IPS_PROMPT arriba, que sí existe porque `por_ip` escala con la
# cantidad de IPs distintas. Esta cota es una garantía explícita y
# auditable (ver tests/test_triage_contexto_v2.py), no una que el contenido
# actual necesite para no crecer sin techo.
CONTEXTO_PREPROCESAMIENTO_MAX_CHARS = int(os.environ.get("CONTEXTO_PREPROCESAMIENTO_MAX_CHARS", "2000"))

# --- Memoria (ChromaDB) ---
TOP_K_FEWSHOT = int(os.environ.get("TOP_K_FEWSHOT", "3"))
TOP_K_ERRORS = int(os.environ.get("TOP_K_ERRORS", "3"))
SIMILARITY_FLOOR = float(os.environ.get("SIMILARITY_FLOOR", "0.55"))
MAX_RAW_CHARS_EMBED = int(os.environ.get("MAX_RAW_CHARS_EMBED", "2000"))
COL_PATTERNS = "attack_patterns"
COL_ERRORS = "error_memory"
COL_HISTORY = "host_history"
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
CHROMA_PATH = os.environ.get("CHROMA_PATH", "./data/chroma")

# --- Integración MITRE ATT&CK / STIX 2.1 (§6.7, §8.7.2, §9 del informe; 4ta
# colección de ChromaDB, agregada 3-sep-2026) ---
# El informe cita "MITRE ATT&CK v15" como base de conocimiento, pero esa
# versión ya quedó 4 releases atrás del catálogo oficial (decisión explícita
# de Antonia, 3-sep-2026: usar la versión ACTUAL, no la citada en el texto
# del informe -- hay que actualizar esa cita al redactar la sección
# correspondiente). Se apunta al archivo "flotante" del repo oficial, que
# siempre sirve la última release -- `preparar_mitre_attack.py` registra la
# versión real (`x_mitre_version`) que encontró al correr, para que la
# corrida quede documentada y sea reproducible aunque el archivo cambie más
# adelante. La corrida real del 4-sep-2026 cargó la **v19.2** (697 técnicas:
# 222 principales + 475 sub-técnicas); queda registrada en
# `data/mitre_attack/provenance.json`.
COL_ATTACK = "attack_techniques"
TOP_K_ATTACK = int(os.environ.get("TOP_K_ATTACK", "3"))
ATTACK_MAX_CHARS_EMBED = int(os.environ.get("ATTACK_MAX_CHARS_EMBED", "800"))
# Umbral de similitud propio para `attack_techniques` -- NO reutiliza
# SIMILARITY_FLOOR (0.55). Ese umbral se calibró para comparar firmas de
# lote contra firmas de lote (mismo "género" de texto, ver `patterns`);
# acá se compara una descripción del lote contra prosa descriptiva de
# MITRE, y `all-MiniLM-L6-v2` no da similitudes tan altas entre dominios
# distintos aunque el contenido esté claramente relacionado.
#
# Historia de la calibración -- importante para la defensa, porque el
# primer valor era correcto para un texto de consulta que después cambió:
#
#   4-sep-2026, 0.55 -> 0.35. Con 0.55 la colección quedaba cargada (697
#   técnicas) pero desconectada: una consulta manual en prosa ("brute
#   force ssh failed password authentication") recuperaba T1110 (0.523),
#   T1110.003 (0.404) y T1021.004 (0.370), y las tres quedaban filtradas.
#
#   9-sep-2026, 0.35 -> 0.42. El 0.35 se calibró con consultas escritas a
#   mano, pero el sistema consultaba con `firma_lote()` -- una cadena de
#   conteos (`v1|lineas=23 ips=3 servicios=[sshd:18...]`). Medido sobre
#   corridas reales, esa firma topaba en 0.324 (auth_log) y 0.300 (BGL):
#   `retrieve_attack_techniques()` devolvía [] SIEMPRE, para cualquier
#   lote, incluido un ataque real. Se corrigió el texto de consulta
#   (`describir_lote_en_prosa()`, ver `src/tools/aggregation.py`), y con
#   prosa el 0.35 pasó a quedar DENTRO de la banda de ruido: sobre 32
#   ventanas reales de BGL y HDFS -- las mismas que usa la evaluación --
#   19 disparaban técnicas irrelevantes, incluidas 8/8 ventanas benignas
#   de HDFS con T1564.004 (NTFS File Attributes) a ~0.36.
#
# Medición del 9-sep-2026 que fija el valor actual:
#
#   ruido (32 ventanas BGL+HDFS, benignas y anómalas): máximo 0.365
#   señal (auth_log con fuerza bruta SSH real):        0.462 - 0.484
#                                                      (T1021, T1110.003)
#
#   piso   ventanas de ruido que disparan   técnicas del ataque real
#   0.35            19 / 32                          5 / 5
#   0.38             0 / 32                          5 / 5
#   0.42             0 / 32                          5 / 5
#   0.45             0 / 32                          5 / 5
#   0.47             0 / 32                          2 / 5
#
# Cualquier valor entre 0.38 y 0.45 separa limpio; se toma 0.42 por ser el
# punto medio de esa banda, con margen a los dos lados (0.055 sobre el
# ruido medido, 0.042 bajo la señal medida). Reproducible sin gastar cuota
# de LLM: la medición es agregación determinística + consulta a ChromaDB.
SIMILARITY_FLOOR_ATTACK = float(os.environ.get("SIMILARITY_FLOOR_ATTACK", "0.42"))
MITRE_ATTACK_URL = os.environ.get(
    "MITRE_ATTACK_URL",
    "https://raw.githubusercontent.com/mitre-attack/attack-stix-data/master/"
    "enterprise-attack/enterprise-attack.json",
)
# Requisito de atribución del propio MITRE (NO es licencia Creative Commons,
# pese a que algunas fuentes de terceros lo describan así -- ver
# https://attack.mitre.org/resources/terms-of-use/, verificado 3-sep-2026).
# Debe citarse textualmente donde se muestren o redistribuyan datos de
# ATT&CK -- ver README, sección "Integración MITRE ATT&CK".
MITRE_ATTACK_ATTRIBUTION = (
    "MITRE ATT&CK® data reproduced and distributed with the permission of "
    "The MITRE Corporation. © The MITRE Corporation."
)


# --- Preprocesamiento heterogéneo de logs (esquema v2, único motor desde
# el 23-sep-2026 -- ver "Preprocesamiento" en el README y
# docs/pipeline_preprocesamiento.md para el flujo completo) ---
#
# Estas variables configuran la tubería determinística de `src/preprocessing/`
# (segmentación, detección, decodificación, enriquecimiento, agregación), que
# es el único camino de preprocesamiento del sistema. Se externalizan acá,
# en vez de cablearse en el código, para poder registrar la configuración
# efectiva de cada corrida -- sin eso, dos corridas con resultados distintos
# no son comparables.
#
# A diferencia del resto del archivo, este bloque parsea con helpers que
# validan: un valor presente pero inválido lanza un error que NOMBRA la
# variable, en vez de un `ValueError: invalid literal for int()` sin
# contexto. Una variable ausente usa su default y no lanza -- importar
# `src.config` en un clon limpio no debe fallar.


def _env_int(nombre: str, default: int) -> int:
    crudo = os.environ.get(nombre)
    if crudo is None or crudo.strip() == "":
        return default
    try:
        return int(crudo)
    except ValueError:
        raise ValueError(
            f"{nombre} debe ser un entero; se recibió {crudo!r}"
        ) from None


def _env_float(nombre: str, default: float) -> float:
    crudo = os.environ.get(nombre)
    if crudo is None or crudo.strip() == "":
        return default
    try:
        return float(crudo)
    except ValueError:
        raise ValueError(
            f"{nombre} debe ser un número; se recibió {crudo!r}"
        ) from None


def _env_bool(nombre: str, default: bool) -> bool:
    crudo = os.environ.get(nombre)
    if crudo is None or crudo.strip() == "":
        return default
    valor = crudo.strip().lower()
    if valor in ("1", "true", "yes", "si", "sí", "on"):
        return True
    if valor in ("0", "false", "no", "off"):
        return False
    raise ValueError(
        f"{nombre} debe ser booleano (true/false); se recibió {crudo!r}"
    )


# Respaldo de modelo apagado (opt-in). Por omisión es False: el comportamiento
# del sistema no cambia. Con True, `_generate_con_fallback` (src/llm.py) NO
# pasa a `LLM_MODEL_FALLBACK` cuando el principal agota sus reintentos: el
# error se relanza. Solo apaga el CAMBIO DE MODELO; los reintentos con espera
# sobre el mismo modelo (503, 429 por minuto) siguen igual.
# Sirve para una campaña donde todas las corridas deben ser del mismo modelo
# (p. ej. la comparación con `gemini_externo`, que nunca tiene respaldo).
LLM_SIN_RESPALDO = _env_bool("LLM_SIN_RESPALDO", False)

# Modo «sin reputación externa» (opt-in, apagado por omisión: producción no cambia). Con True,
# `check_ip_reputation` (src/tools/reputation.py) NO consulta AbuseIPDB ni usa su heurística local:
# ninguna IP recibe puntaje y su categoría es «desconocido», igual para toda IP. Sirve para una campaña
# en que la reputación no debe formar parte de la medición (la heurística local es una función de la
# forma de la dirección, no reputación real).
REPUTACION_SIN_ENRIQUECIMIENTO = _env_bool("REPUTACION_SIN_ENRIQUECIMIENTO", False)


# Modos de detección de formato (§9 del plan):
#   batch   -- un decoder dominante para todo el lote (comportamiento v1)
#   chunked -- un decoder por bloque de LOG_DETECTION_CHUNK_SIZE registros
#   line    -- detección independiente por registro (el más lento)
#   hybrid  -- bloques, reprocesando individualmente los registros rechazados
MODOS_PARSING = ("batch", "chunked", "line", "hybrid")

# Motor de preprocesamiento. Único (23-sep-2026): el sistema tuvo, durante
# el desarrollo, un motor de adaptadores por formato más simple ("v1" en la
# bitácora del proyecto) que se retiró por ineficiente frente a lotes que
# mezclan formatos -- ver "Preprocesamiento heterogéneo" en el README. No es
# una variable de entorno: no hay entre qué elegir. Se mantiene como
# constante (no como valor hardcodeado disperso) porque `motor_preprocesamiento`
# se persiste como campo de procedencia en el historial, los resultados de
# evaluación y el informe en PDF.
LOG_PREPROCESSING_ENGINE = "heterogeneo"

LOG_PARSING_MODE = os.environ.get("LOG_PARSING_MODE", "hybrid")
LOG_DETECTION_CHUNK_SIZE = _env_int("LOG_DETECTION_CHUNK_SIZE", 50)
# Confianza mínima para aceptar un decoder como dominante de un bloque.
LOG_FORMAT_CONFIDENCE_THRESHOLD = _env_float("LOG_FORMAT_CONFIDENCE_THRESHOLD", 0.50)
# Por debajo de esto, un registro del bloque se reprocesa individualmente
# en vez de aceptarse con el decoder dominante.
LOG_LINE_FALLBACK_THRESHOLD = _env_float("LOG_LINE_FALLBACK_THRESHOLD", 0.70)

LOG_ENABLE_MULTILINE = _env_bool("LOG_ENABLE_MULTILINE", True)
# Controla la PERSISTENCIA y la EXPORTACIÓN del raw -- no lo que se envía
# al LLM (Fase 3 del cierre de auditoría, 23-sep-2026, hallazgo A3: estaba
# declarada, documentada y persistida, pero ningún componente la leía; el
# raw se conservaba siempre).
#
# Default `true` para no romper el historial existente. Con `false`:
#   - La cronología del resumen (persistida en `data/historial.db` y en el
#     PDF, ver `src/preprocessing/aggregation.py::_cronologia_v2`) arma su
#     `mensaje` desde el evento ya decodificado, nunca desde el texto
#     crudo, y enmascara IPs/usuarios/hosts (`_redactar_mensaje`) -- una
#     redacción por sustitución de lo que el propio preprocesamiento ya
#     extrajo, no un análisis de texto libre en busca de PII.
#   - En su lugar se guarda `raw_procedencia`: hash SHA-256, líneas y
#     tamaño del lote (`src/tools/aggregation.py::_procedencia_raw`).
#
# **Lo que esta variable NO controla**: las muestras de texto crudo que
# `contexto_preprocesamiento()` arma para el prompt del Triage
# (`src/preprocessing/prompt_context.py`, ver también Fase 2 del cierre)
# se construyen a partir de `raw_samples`, que llega al LLM SIN pasar por
# acá -- ni persistido ni redactado. Si se necesita que ningún log crudo
# salga hacia la API de Gemini, ese es un cambio aparte, no cubierto por
# esta variable ni por el cierre de esta auditoría.
LOG_PRESERVE_RAW = _env_bool("LOG_PRESERVE_RAW", True)
LOG_MAX_RAW_SAMPLES = _env_int("LOG_MAX_RAW_SAMPLES", 20)
LOG_MAX_UNMAPPED_FIELDS = _env_int("LOG_MAX_UNMAPPED_FIELDS", 100)

LOG_NORMALIZATION_SCHEMA_VERSION = os.environ.get("LOG_NORMALIZATION_SCHEMA_VERSION", "2.0")
# Máximo de registros que entran a la secuencia temporal del incidente
# (§8.7.1 del informe). Es un tope de PRESENTACIÓN, no de análisis: los
# conteos y distribuciones siguen calculándose sobre el lote completo, y lo
# que se recorta queda declarado en `cronologia_omitidos`. Con 40 entradas
# el JSON del historial y la sección del PDF se mantienen legibles.
# Subido de 40 a 300 el 7-oct-2026 (AJUSTES_FASE_D_NODEX.md §1).
#
# Con 40, la evidencia citable eran los primeros 40 registros del lote.
# Medido sobre los 104 casos de UWF (300 registros cada uno, con el
# incidente insertado en el 70% central): en 52 de 52 casos positivos
# NINGUN evento del incidente caia dentro de esos 40. El primero
# aparecia en la posicion 49 como minimo, mediana 139. D2 y D3 eran
# estructuralmente imposibles y D1 quedaba degradado, no por el
# sistema sino por una restriccion de posicion.
#
# La decision prioriza mantener la dificultad original del escenario,
# aun a costa de mas tokens de entrada (~18.000 por llamada en un caso
# de UWF, estimados por conteo de caracteres).
CRONOLOGIA_MAX_EVENTOS = _env_int("CRONOLOGIA_MAX_EVENTOS", 300)

LOG_MAX_FILE_BYTES = _env_int("LOG_MAX_FILE_BYTES", 52428800)   # 50 MiB
LOG_MAX_EVENTS = _env_int("LOG_MAX_EVENTS", 100000)


def validar_config_preprocesamiento() -> None:
    """Valida rangos y combinaciones de las variables `LOG_*`.

    Se invoca explícitamente desde la tubería de preprocesamiento
    (`preprocesar()`, ver `src/preprocessing/pipeline.py`), NO al importar
    el módulo: importar `src.config` con una configuración incompleta no
    debe romper la suite.
    """
    problemas: list[str] = []

    if LOG_PARSING_MODE not in MODOS_PARSING:
        problemas.append(
            f"LOG_PARSING_MODE inválido: {LOG_PARSING_MODE!r}. "
            f"Valores admitidos: {', '.join(MODOS_PARSING)}"
        )
    if LOG_DETECTION_CHUNK_SIZE < 1:
        problemas.append(
            f"LOG_DETECTION_CHUNK_SIZE debe ser >= 1; es {LOG_DETECTION_CHUNK_SIZE}"
        )
    for nombre, valor in (
        ("LOG_FORMAT_CONFIDENCE_THRESHOLD", LOG_FORMAT_CONFIDENCE_THRESHOLD),
        ("LOG_LINE_FALLBACK_THRESHOLD", LOG_LINE_FALLBACK_THRESHOLD),
    ):
        if not (0.0 <= valor <= 1.0):
            problemas.append(f"{nombre} debe estar entre 0.0 y 1.0; es {valor}")
    for nombre, valor in (
        ("LOG_MAX_RAW_SAMPLES", LOG_MAX_RAW_SAMPLES),
        ("LOG_MAX_UNMAPPED_FIELDS", LOG_MAX_UNMAPPED_FIELDS),
    ):
        if valor < 0:
            problemas.append(f"{nombre} no puede ser negativo; es {valor}")
    for nombre, valor in (
        ("LOG_MAX_FILE_BYTES", LOG_MAX_FILE_BYTES),
        ("LOG_MAX_EVENTS", LOG_MAX_EVENTS),
    ):
        if valor < 1:
            problemas.append(f"{nombre} debe ser >= 1; es {valor}")

    # Combinación que deja al modo híbrido sin su razón de ser: si ningún
    # registro puede quedar por debajo del umbral de reproceso, "hybrid"
    # se comporta exactamente como "chunked" y el reproceso individual
    # nunca ocurre. Es un no-op silencioso, así que se rechaza.
    if (LOG_PARSING_MODE == "hybrid"
            and LOG_LINE_FALLBACK_THRESHOLD <= LOG_FORMAT_CONFIDENCE_THRESHOLD):
        problemas.append(
            "En modo 'hybrid', LOG_LINE_FALLBACK_THRESHOLD "
            f"({LOG_LINE_FALLBACK_THRESHOLD}) debe ser mayor que "
            f"LOG_FORMAT_CONFIDENCE_THRESHOLD ({LOG_FORMAT_CONFIDENCE_THRESHOLD}); "
            "si no, ningún registro se reprocesa individualmente y 'hybrid' "
            "equivale a 'chunked'. Usa 'chunked' explícitamente o sube el umbral."
        )

    if problemas:
        raise ValueError(
            "Configuración de preprocesamiento inválida:\n  - "
            + "\n  - ".join(problemas)
        )


def config_preprocesamiento_efectiva() -> dict:
    """Instantánea de la configuración con la que corrió el preprocesamiento.

    Se guarda en `PreprocessingResult.config` y en los archivos de
    `results/`: sin esto, dos corridas con salidas distintas no se pueden
    comparar, porque no se sabe si cambió el código o la configuración
    (§11 y §17 del plan). Las claves van ordenadas para que la
    serialización sea determinística.
    """
    valores = {
        "LOG_PREPROCESSING_ENGINE": LOG_PREPROCESSING_ENGINE,
        "LOG_PARSING_MODE": LOG_PARSING_MODE,
        "LOG_DETECTION_CHUNK_SIZE": LOG_DETECTION_CHUNK_SIZE,
        "LOG_FORMAT_CONFIDENCE_THRESHOLD": LOG_FORMAT_CONFIDENCE_THRESHOLD,
        "LOG_LINE_FALLBACK_THRESHOLD": LOG_LINE_FALLBACK_THRESHOLD,
        "LOG_ENABLE_MULTILINE": LOG_ENABLE_MULTILINE,
        "LOG_PRESERVE_RAW": LOG_PRESERVE_RAW,
        "LOG_MAX_RAW_SAMPLES": LOG_MAX_RAW_SAMPLES,
        "LOG_MAX_UNMAPPED_FIELDS": LOG_MAX_UNMAPPED_FIELDS,
        "LOG_NORMALIZATION_SCHEMA_VERSION": LOG_NORMALIZATION_SCHEMA_VERSION,
        "LOG_MAX_FILE_BYTES": LOG_MAX_FILE_BYTES,
        "LOG_MAX_EVENTS": LOG_MAX_EVENTS,
    }
    return {k: valores[k] for k in sorted(valores)}


def validate_config() -> None:
    """Lanza un error claro si falta alguna key obligatoria antes de correr el grafo."""
    if not GEMINI_API_KEY:
        raise EnvironmentError(
            "Falta GEMINI_API_KEY (o GOOGLE_API_KEY) en tu .env. "
            "Consíguela en https://aistudio.google.com/apikey"
        )
