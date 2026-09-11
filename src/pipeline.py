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


def _metadatos_preprocesamiento(raw_logs: str) -> tuple[dict, list, list]:
    """Metadatos del preprocesamiento v2 para el estado del grafo.

    Devuelve (metadatos, advertencias, muestras). Con el motor v1 activo
    devuelve estructuras vacías: la información no existe en ese esquema y
    fabricarla sería peor que no tenerla.

    **No se devuelven los eventos normalizados.** El estado de LangGraph se
    serializa en cada checkpoint, así que guardarlos haría crecer el estado
    en proporción al archivo (§14 del plan). Solo agregados y muestras.
    """
    from src.config import LOG_MAX_RAW_SAMPLES, LOG_PREPROCESSING_ENGINE

    if LOG_PREPROCESSING_ENGINE != "v2":
        return {}, [], []

    from src.preprocessing.aggregation import agregar_v2
    from src.preprocessing.pipeline import preprocesar

    resultado = preprocesar(raw_logs)
    v2 = agregar_v2(resultado, max_muestras=LOG_MAX_RAW_SAMPLES)

    metadatos = {
        "schema_version": v2["schema_version"],
        "total_lineas_fisicas": v2["total_lineas_fisicas"],
        "total_eventos": v2["total_eventos"],
        "decoder_distribution": v2["decoder_distribution"],
        "product_distribution": v2["product_distribution"],
        "severity_distribution": v2["severity_distribution"],
        "event_categories": v2["event_categories"],
        "parsing": v2["parsing"],
        "segments": v2["segments"],
        "entities_resumen": {k: len(v) for k, v in v2["entities"].items()},
        "config": resultado.config,
    }
    # Las muestras ya vienen filtradas por `agregar_v2`: se omiten si el
    # lote trae ground truth embebido en la línea.
    muestras = v2["samples"].get("por_decoder", {})
    muestras_lista = [{"decoder": k, "texto": v} for k, v in muestras.items()]
    if "nota" in v2["samples"]:
        muestras_lista.append({"decoder": None, "texto": v2["samples"]["nota"]})
    return metadatos, v2["warnings"], muestras_lista


def _preparar_estado_inicial(raw_logs: str, thread_id: str | None = None):
    """Agregación determinística + corroboración de IPs, común a
    `analizar_lote` (CLI/informe) y `analizar_lote_stream` (interfaz web,
    ver `src/api/main.py`). Devuelve (input_inicial, config, firma)."""
    resumen = aggregate_logs(raw_logs)

    # La reputación se consulta SOLO sobre entidades de tipo IP. Con el
    # esquema v2 un lote puede no tener ninguna —un log de aplicación, por
    # ejemplo— y eso ya no impide analizarlo: antes, `ips_distintas` vacío
    # dejaba el resumen prácticamente sin contenido.
    ips = resumen.get("ips_distintas") or []
    resumen["reputacion_ips"] = corroborar_ips(ips, get_ip_cache()) if ips else {}

    metadatos, advertencias, muestras = _metadatos_preprocesamiento(raw_logs)
    firma = firma_lote(resumen, metadatos)

    input_inicial = {
        "resumen_logs": resumen,
        "preprocessing_metadata": metadatos,
        "parsing_warnings": advertencias,
        "raw_samples": muestras,
        "firma": firma,
        # --- Plan-and-Execute (agente_planificador es el primer nodo) ---
        "plan": {},
        "plan_objetivo": "",
        "paso_actual": 0,
        "historial_ejecucion": [],
        "desviaciones_plan": [],
        "historial_planes": [],
        "replan_count": 0,
        "diagnostico": "",
        "necesita_rag": False,
        "usar_cve": False,
        "contexto_rag": [],
        "tecnicas_mitre": [],
        "cves_encontrados": [],
        "comandos_mitigacion": [],
        # None, no True: "aún no evaluado" -- nada lo lee antes de que
        # tool_validar_comandos lo fije de verdad (ver src/state.py).
        "comandos_validos": None,
        "motivos_rechazo": [],
        "confianza": 0.0,
        "hay_incidente": False,
        "hay_anomalia": False,
        "evaluacion_auditor": "",
        "intentos_correccion": 0,
        "cobertura_auditor": None,
        "cobertura_suficiente": None,
        "motivo_replanificacion": "",
        "requiere_replanificacion": False,
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
            # Veredicto de AbuseIPDB por IP. Se incluye porque el informe en
            # PDF (Fase B) resume la reputación observada, y este evento es
            # lo único del resumen que la capa web persiste. Es un dict
            # chico -- una entrada por IP distinta del lote -- y el resto de
            # los campos pesados del resumen (`por_ip`, `ips_distintas`)
            # siguen sin viajar.
            "reputacion_ips": input_inicial["resumen_logs"].get("reputacion_ips") or {},
            # Elementos que el §8.7.1 del informe exige en el reporte
            # estructurado: entidades involucradas (usuarios incluidos) y la
            # secuencia temporal de los registros relevantes. Van acotados
            # desde la agregación (`usuarios` top 10, `entidades` top 8,
            # `cronologia` con tope y `cronologia_omitidos` declarando el
            # recorte), así que el evento sigue siendo chico.
            #
            # NO van al prompt del LLM: `resumen_prompt` los excluye. La
            # cronología lleva texto crudo y en BGL la etiqueta del dataset
            # es el primer token de la línea.
            "usuarios": input_inicial["resumen_logs"].get("usuarios") or {},
            "n_usuarios_distintos": input_inicial["resumen_logs"].get("n_usuarios_distintos") or 0,
            "codigos_respuesta": input_inicial["resumen_logs"].get("codigos_respuesta") or {},
            "entidades": input_inicial["resumen_logs"].get("entidades") or [],
            "cronologia": input_inicial["resumen_logs"].get("cronologia") or [],
            "cronologia_omitidos": input_inicial["resumen_logs"].get("cronologia_omitidos") or 0,
        },
        # Cómo se interpretó el archivo (Fase 12 del plan): permite que la
        # interfaz distinga un parsing completo de uno parcial o en
        # fallback, en vez de mostrar un único "formato detectado" que con
        # lotes heterogéneos sería una simplificación engañosa. Va vacío
        # con el motor v1.
        "preprocesamiento": input_inicial.get("preprocessing_metadata") or {},
        "advertencias": input_inicial.get("parsing_warnings") or [],
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
            # Evidencias utilizadas (§8.7.1): los precedentes que el RAG
            # recuperó de la memoria y que el triage tuvo a la vista.
            "precedentes": _precedentes(estado_final.get("contexto_rag")),
            "n_precedentes": len(estado_final.get("contexto_rag") or []),
            # Plan-and-Execute (11-sep-2026): campos aditivos, no rompen a
            # ningún consumidor que solo lea las claves de arriba.
            "plan": estado_final.get("plan"),
            "historial_ejecucion": estado_final.get("historial_ejecucion"),
            "desviaciones_plan": estado_final.get("desviaciones_plan"),
            "historial_planes": estado_final.get("historial_planes"),
            "replan_count": estado_final.get("replan_count"),
            "cobertura_auditor": estado_final.get("cobertura_auditor"),
            "cobertura_suficiente": estado_final.get("cobertura_suficiente"),
        },
    }


def _precedentes(contexto_rag) -> list:
    """Los precedentes que el RAG recuperó y que el triage efectivamente vio.

    El §8.7.1 exige que el reporte incluya "las evidencias utilizadas". Los
    CVEs, la reputación de IPs y las técnicas de ATT&CK ya quedaban en el
    reporte; los patrones históricos de ChromaDB, no -- así que no era
    auditable qué precedentes influyeron en el diagnóstico. Se guarda una
    versión compacta (clasificación, confianza, similitud) en vez del
    documento completo: el texto es la firma del lote precedente, que no
    aporta nada leída y sí pesa en el JSON.
    """
    salida = []
    for patron in contexto_rag or []:
        if not isinstance(patron, dict):
            continue
        meta = patron.get("meta") or {}
        salida.append({
            "clasificacion": meta.get("clasificacion"),
            "confianza": meta.get("confianza"),
            "host": meta.get("host"),
            "similitud": patron.get("similitud"),
        })
    return salida


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
