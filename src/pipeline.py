"""Punto de entrada del sistema: agrega logs, corre el grafo y guarda feedback.

Migrado desde las celdas 27 y 29 del notebook de Colab.
"""

import json
import time

from src.config import CONFIDENCE_THRESHOLD
from src.graph.build_graph import build_graph
from src.tools.aggregation import aggregate_logs, firma_lote
from src.tools.reputation import ReputationCache, corroborar_ips
from src.tools.tool_consultar_rag import ltm  # instancia compartida de LongTermMemory

_app = None
_ip_cache = None


def get_app():
    """Compila el grafo una sola vez (lazy) y reutiliza la instancia."""
    global _app
    if _app is None:
        _app = build_graph()
    return _app


def get_ip_cache():
    """Caché de reputación de IPs, compartida entre lotes (lazy, un solo proceso)."""
    global _ip_cache
    if _ip_cache is None:
        _ip_cache = ReputationCache()
    return _ip_cache


def _preparar_estado_inicial(raw_logs: str, thread_id: str | None = None):
    """Agregación determinística + corroboración de IPs, común a
    `analizar_lote` (CLI/informe) y `analizar_lote_stream` (interfaz web,
    ver `src/api/main.py`). Devuelve (input_inicial, config, firma)."""
    resumen = aggregate_logs(raw_logs)
    resumen["reputacion_ips"] = corroborar_ips(resumen["ips_distintas"], get_ip_cache())
    firma = firma_lote(resumen)

    input_inicial = {
        "resumen_logs": resumen,
        "firma": firma,
        "diagnostico": "",
        "necesita_rag": False,
        "usar_cve": False,
        "contexto_rag": [],
        "tecnicas_mitre": [],
        "cves_encontrados": [],
        "comandos_mitigacion": [],
        "comandos_validos": True,
        "motivos_rechazo": [],
        "confianza": 0.0,
        "hay_incidente": False,
        "hay_anomalia": False,
        "evaluacion_auditor": "",
        "intentos_correccion": 0,
    }
    config = {"configurable": {"thread_id": thread_id or f"incidente_{int(time.time())}"}}
    return input_inicial, config, firma


def analizar_lote(raw_logs: str, thread_id: str | None = None) -> dict:
    """Corre el pipeline completo sobre un lote de logs crudos.

    Devuelve el estado final del grafo, con el `_firma` del lote agregado
    para poder hacer `commit()` después (ver más abajo).
    """
    app = get_app()
    input_inicial, config, firma = _preparar_estado_inicial(raw_logs, thread_id)

    print("🚀 EJECUTANDO FLUJO CÍCLICO MULTIAGENTE CON PERSISTENCIA...")
    print("=" * 60)
    try:
        for update in app.stream(input_inicial, config=config, stream_mode="updates"):
            for nodo in update:
                print(f"👉 Transición completada en: '{nodo}'")
        print("=" * 60)
        print("🎯 Ejecución finalizada de manera segura.")
    except Exception as e:
        print(f"\n💥 ¡Alerta! El agente colapsó por un error de API: {e}")
        print("🕵️‍♂️ Rescatando los datos forenses de la memoria (Caja Negra)...")

    estado_final = app.get_state(config).values
    estado_final["_firma"] = firma
    estado_final["requiere_revision_humana"] = float(estado_final.get("confianza", 0)) < CONFIDENCE_THRESHOLD
    return estado_final


def analizar_lote_stream(raw_logs: str, thread_id: str | None = None):
    """Igual que `analizar_lote`, pero como generador para la interfaz web
    (`src/api/main.py`): emite un evento por cada transición del grafo en
    vez de devolver solo el resultado final, para poder mostrar el avance
    del multiagente en vivo.

    Eventos emitidos (dicts con clave "tipo"):
    - "inicio": una vez, con el resumen agregado del lote (antes de tocar el LLM).
    - "nodo": una vez por nodo ejecutado, con lo que ese nodo devolvió al
      estado (mismo payload que ve el `stream_mode="updates"` de LangGraph).
      Un nodo revisitado (p. ej. el Triage antes y después del RAG) emite
      un evento cada vez.
    - "error": si el grafo colapsa por un error de API (mismo camino que
      el bloque `except` de `analizar_lote`). Termina el generador -- NO se
      emite "final" después de un "error" (bug real del 1-sep-2026: antes
      se seguía armando y emitiendo un reporte final con los valores por
      defecto del estado -- confianza 0.0, diagnóstico "" -- lo que en la
      interfaz web se veía como "el análisis terminó" casi instantáneo en
      vez de como la falla que realmente fue).
    - "final": una vez, solo si NO hubo error, con el reporte curado --
      mismos campos que `src/tools/log_runner.py` guarda en `results/`.
    """
    app = get_app()
    input_inicial, config, firma = _preparar_estado_inicial(raw_logs, thread_id)

    yield {
        "tipo": "inicio",
        "resumen": {
            "formato_detectado": input_inicial["resumen_logs"].get("formato_detectado"),
            "total_lineas": input_inicial["resumen_logs"].get("total_lineas"),
            "n_ips_distintas": input_inicial["resumen_logs"].get("n_ips_distintas"),
            "servicios": input_inicial["resumen_logs"].get("servicios"),
            "eventos": input_inicial["resumen_logs"].get("eventos"),
            "ventana_temporal": input_inicial["resumen_logs"].get("ventana_temporal"),
        },
    }

    try:
        for update in app.stream(input_inicial, config=config, stream_mode="updates"):
            for nodo, salida in update.items():
                yield {"tipo": "nodo", "nombre": nodo, "detalle": salida}
    except Exception as e:
        mensaje = f"{type(e).__name__}: {e}"
        print(f"\n💥 ¡Alerta! El agente colapsó por un error de API: {mensaje}")
        yield {"tipo": "error", "mensaje": mensaje}
        return  # no arma ni emite "final" -- ver nota arriba

    estado_final = app.get_state(config).values
    estado_final["_firma"] = firma
    confianza = float(estado_final.get("confianza", 0) or 0)
    yield {
        "tipo": "final",
        "reporte": {
            "diagnostico": estado_final.get("diagnostico"),
            "confianza": confianza,
            "hay_incidente": estado_final.get("hay_incidente"),
            "hay_anomalia": estado_final.get("hay_anomalia"),
            "evaluacion_auditor": estado_final.get("evaluacion_auditor"),
            "tecnicas_mitre": estado_final.get("tecnicas_mitre"),
            "comandos_mitigacion": estado_final.get("comandos_mitigacion"),
            "comandos_validos": estado_final.get("comandos_validos"),
            "cves_encontrados": estado_final.get("cves_encontrados"),
            "intentos_correccion": estado_final.get("intentos_correccion"),
            "requiere_revision_humana": confianza < CONFIDENCE_THRESHOLD,
            "firma": firma,
        },
    }


def commit_feedback(estado_final: dict, host: str = "desconocido", correccion: dict | None = None) -> dict:
    """Guarda el resultado validado en ChromaDB (host_history) y, si la
    confianza supera AUTO_PROMOTE, lo promueve a attack_patterns.
    """
    firma = estado_final.get("_firma", "")
    reporte = {
        "clasificacion_global": estado_final.get("diagnostico"),
        "confianza": estado_final.get("confianza"),
    }
    if correccion:
        ltm.record_error(firma, reporte, correccion)
        reporte = {**reporte, **correccion}
    promovido = ltm.commit_validated(firma, reporte, host)
    return {
        "guardado_en": "host_history",
        "promovido_a_attack_patterns": promovido,
        "error_registrado": bool(correccion),
    }


if __name__ == "__main__":
    # Ejemplo mínimo de uso — reemplaza por logs reales o léelos de un archivo/stdin.
    logs_demo = (
        "Jan 10 13:55:36 srv sshd[1]: Failed password for invalid user admin "
        "from 203.0.113.10 port 22 ssh2\n"
        "Jan 10 13:55:39 srv sshd[2]: Failed password for root from 45.146.0.9 port 22 ssh2"
    )
    resultado = analizar_lote(logs_demo, thread_id="demo_001")
    print("\n📋 REPORTE FINAL")
    print(json.dumps({
        "diagnostico": resultado.get("diagnostico"),
        "comandos_mitigacion": resultado.get("comandos_mitigacion"),
        "confianza": resultado.get("confianza"),
        "requiere_revision_humana": resultado.get("requiere_revision_humana"),
    }, ensure_ascii=False, indent=2))
