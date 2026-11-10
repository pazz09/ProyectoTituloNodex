"""Acota el `resumen_logs` que se serializa completo en el prompt del agente
de triage (`agente_analista_triage.py`).

Hallazgo real (25-ago-2026, ver README "Manejo de cuota y errores
transitorios de la API"): el costo en tokens del prompt de triage escala con
la cantidad de IPs DISTINTAS del lote -- por la serialización completa de
`por_ip`/`ips_distintas`/`reputacion_ips`, cada uno con una entrada por IP --
no con el número de líneas de log. HDFS (202 IPs) disparó 58 289 tokens de
entrada en triage vs. 1 096 de BGL (2 IPs), para lotes del mismo tamaño
(2000 líneas). Sin acotar esto, un dataset con miles de IPs distintas
dispararía el costo del prompt de forma desproporcionada al tamaño real del
incidente -- bloqueante real para la evaluación experimental sobre datasets
grandes (§9 del Informe).

Esta función NO toca `resumen_logs` en el estado del grafo -- otros nodos
(y el JSON final que se guarda en `results/`) siguen viendo el desglose
completo por IP. Solo el texto que se arma para el prompt del LLM usa la
versión acotada, vía una copia.
"""

from src.config import TOP_N_IPS_PROMPT

_CATEGORIAS_RELEVANTES = {"malicioso", "sospechoso"}

# Claves del resumen que NO van al prompt. Son de la capa de presentación:
# alimentan el informe, el PDF y la interfaz, no el razonamiento del LLM.
#
# `cronologia` además NO PUEDE ir al prompt: sus entradas incluyen un
# extracto del registro CRUDO, y en BGL la etiqueta de anomalía del dataset
# es el primer token de la línea. Mandarla reabriría exactamente la fuga de
# ground truth que cerró la Fase 7 del plan de preprocesamiento -- por eso
# `agregar_v2` ya omite las muestras crudas en los lotes con etiqueta
# embebida. La cronología existe para que la lea un humano, no el detector.
#
# `entidades` se excluye por costo y no por fuga: es una vista corta de
# `por_ip`, que el prompt ya recibe acotado, así que serializarla sería
# pagar dos veces por la misma información.
_CLAVES_FUERA_DEL_PROMPT = ("cronologia", "cronologia_omitidos", "entidades")


def _sin_claves_de_presentacion(resumen: dict) -> dict:
    """Copia del resumen sin las claves que no deben llegar al LLM."""
    if not any(clave in resumen for clave in _CLAVES_FUERA_DEL_PROMPT):
        return resumen
    return {k: v for k, v in resumen.items() if k not in _CLAVES_FUERA_DEL_PROMPT}


def acotar_resumen_para_prompt(resumen: dict, top_n: int = TOP_N_IPS_PROMPT) -> dict:
    """Devuelve una copia de `resumen` con el desglose por IP acotado.

    Se incluyen en detalle:
      1. Las `top_n` IPs más activas por `n_eventos` (ya vienen ordenadas
         así en `ips_distintas`, ver `aggregate_logs`).
      2. Cualquier IP con reputación "sospechoso"/"malicioso" (AbuseIPDB),
         aunque no esté entre las más activas -- una IP maliciosa de baja
         actividad es justo el caso que no se puede permitir esconder al
         acotar el prompt.

    El resto se agrega en un solo campo `ips_resumidas` (cantidad, total de
    eventos, total de intentos fallidos) para que el LLM sepa que existen
    sin gastar tokens en cada una individualmente.

    `n_ips_distintas` NUNCA se trunca -- sigue siendo el conteo real, para
    no subestimarle al LLM la escala del incidente.

    Si el lote tiene `top_n` IPs distintas o menos, no hay nada que acotar
    y se devuelve `resumen` sin copiar.
    """
    resumen = _sin_claves_de_presentacion(resumen)

    ips_ordenadas = resumen.get("ips_distintas", [])
    if len(ips_ordenadas) <= top_n:
        return resumen

    reputacion = resumen.get("reputacion_ips", {}) or {}
    por_ip = resumen.get("por_ip", {}) or {}

    top = ips_ordenadas[:top_n]
    cola = ips_ordenadas[top_n:]
    relevantes_extra = [
        ip for ip in cola
        if reputacion.get(ip, {}).get("categoria") in _CATEGORIAS_RELEVANTES
    ]
    incluidas = top + relevantes_extra
    incluidas_set = set(incluidas)
    resto = [ip for ip in ips_ordenadas if ip not in incluidas_set]

    resumen_acotado = dict(resumen)
    resumen_acotado["ips_distintas"] = incluidas
    resumen_acotado["por_ip"] = {ip: por_ip[ip] for ip in incluidas if ip in por_ip}
    if "reputacion_ips" in resumen:
        resumen_acotado["reputacion_ips"] = {
            ip: reputacion[ip] for ip in incluidas if ip in reputacion
        }

    if resto:
        resumen_acotado["ips_resumidas"] = {
            "cantidad": len(resto),
            "total_eventos": sum(por_ip.get(ip, {}).get("n_eventos", 0) for ip in resto),
            "total_intentos_fallidos": sum(
                por_ip.get(ip, {}).get("intentos_fallidos", 0) for ip in resto
            ),
            "nota": (
                f"{len(resto)} IPs adicionales no incluidas individualmente "
                "por límite de tamaño del prompt (ver n_ips_distintas para "
                "el total real del lote). Ninguna tiene reputación "
                "sospechosa/maliciosa conocida -- esas se incluyen siempre "
                "arriba aunque tengan poca actividad."
            ),
        }

    return resumen_acotado
