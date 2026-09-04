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

# --- Cotas del agente Plan-and-Execute de referencia (src/legacy_agent.py) ---
MAX_PLAN_STEPS = int(os.environ.get("MAX_PLAN_STEPS", "6"))
MAX_TOOL_ITERS = int(os.environ.get("MAX_TOOL_ITERS", "8"))
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
# adelante.
COL_ATTACK = "attack_techniques"
TOP_K_ATTACK = int(os.environ.get("TOP_K_ATTACK", "3"))
ATTACK_MAX_CHARS_EMBED = int(os.environ.get("ATTACK_MAX_CHARS_EMBED", "800"))
# Umbral de similitud propio para `attack_techniques` -- NO reutiliza
# SIMILARITY_FLOOR (0.55). Ese umbral se calibró para comparar firmas de
# lote contra firmas de lote (mismo "género" de texto, ver `patterns`);
# acá se compara la firma de un lote contra prosa descriptiva de MITRE --
# dominios de texto distintos, y `all-MiniLM-L6-v2` no da similitudes tan
# altas entre dominios distintos aunque el contenido esté claramente
# relacionado. Bug real encontrado (4-sep-2026): con SIMILARITY_FLOOR=0.55,
# la colección quedaba cargada (697 técnicas) pero desconectada en la
# práctica -- una consulta manual de "brute force ssh failed password
# authentication" recupera T1110/Brute Force (similitud 0.523),
# T1110.003/Password Spraying (0.404) y T1021.004/SSH (0.370) por búsqueda
# semántica directa contra ChromaDB, pero las tres quedaban filtradas por
# el umbral de 0.55 -- `retrieve_attack_techniques()` devolvía [] siempre,
# para cualquier lote, incluido un ataque real. Ruido no relacionado
# (HDFS/logs operativos benignos contra las mismas técnicas) midió
# similitud 0.16-0.18 en la misma corrida -- bien por debajo de 0.35, así
# que el nuevo umbral separa limpio señal real de ruido de dominio
# distinto en los casos medidos.
SIMILARITY_FLOOR_ATTACK = float(os.environ.get("SIMILARITY_FLOOR_ATTACK", "0.35"))
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


def validate_config() -> None:
    """Lanza un error claro si falta alguna key obligatoria antes de correr el grafo."""
    if not GEMINI_API_KEY:
        raise EnvironmentError(
            "Falta GEMINI_API_KEY (o GOOGLE_API_KEY) en tu .env. "
            "Consíguela en https://aistudio.google.com/apikey"
        )
