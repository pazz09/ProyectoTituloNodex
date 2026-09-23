"""Tests de la integración del preprocesamiento v2 con el pipeline
(Fase 9 del plan) y del enriquecedor de autenticación (Fase 6).

Criterios de aceptación de la Fase 9:
1. El grafo conserva sus nodos (originalmente siete; ocho desde Plan-and-Execute).
2. Los lotes sin IP pueden analizarse.
3. El estado no crece proporcionalmente al contenido completo del archivo.
4. El streaming informa correctamente el preprocesamiento.
"""

import src.pipeline as pipeline_mod
from src.preprocessing.pipeline import preprocesar
from src.tools.aggregation import aggregate_logs, firma_lote

AUTH = ("Jan 10 13:55:36 srv sshd[1]: Failed password for invalid user admin "
        "from 203.0.113.10 port 22 ssh2")
AUTH_OK = "Jan 10 13:56:01 srv sshd[9]: Accepted password for ana from 10.0.0.5 port 22 ssh2"
SIN_IP = '{"process": "cron", "user": "root", "msg": "tarea programada ejecutada"}'


# --- enriquecedor de autenticación (Fase 6, agregado fuera del plan) ------

def test_un_fallo_de_autenticacion_se_marca_como_tal():
    """Sin este perfil, un lote de fuerza bruta SSH —el escenario del
    informe— reportaría cero eventos críticos bajo el motor v2."""
    ev = preprocesar(AUTH + "\n", modo="line").events[0]
    assert ev.event_category == "authentication"
    assert ev.event_outcome == "failure"
    assert ev.event_action == "login"


def test_una_autenticacion_exitosa_no_se_marca_como_fallo():
    ev = preprocesar(AUTH_OK + "\n", modo="line").events[0]
    assert ev.event_outcome == "success"


def test_el_usuario_se_extrae_de_la_alternativa_mas_especifica():
    """En "for invalid user admin", el usuario real es "admin", no
    "invalid" (la alternativa que aparece primero en el texto, sin ser la
    más específica). El enriquecedor de autenticación prueba los patrones
    del más específico al más general."""
    assert preprocesar(AUTH + "\n", modo="line").events[0].source_user == "admin"
    resumen = aggregate_logs(AUTH + "\n")
    assert resumen["por_ip"]["203.0.113.10"]["usuarios_objetivo"] == ["admin"]


def test_el_enriquecedor_no_decide_que_hay_un_ataque():
    """Diez fallos seguidos pueden ser fuerza bruta o un dedo pesado: eso
    lo interpretan los agentes, no el preprocesamiento."""
    lote = "\n".join([AUTH] * 10) + "\n"
    res = preprocesar(lote, modo="line")
    assert all(e.event_outcome == "failure" for e in res.events)
    assert all(e.severity is None for e in res.events)
    assert res.ground_truth == []


def test_no_le_gana_a_un_perfil_de_formato_conocido():
    """Su condición es la más laxa: no debe desplazar a HDFS ni a BGL."""
    hdfs = ("081109 203615 148 INFO dfs.DataNode: Failed to read block "
            "blk_1 authentication failure")
    ev = preprocesar(hdfs + "\n", modo="line").events[0]
    assert ev.attributes["perfil"] == "hdfs"


# --- criterio 2: lotes sin IP se pueden analizar --------------------------

def test_un_lote_sin_ninguna_ip_produce_un_resumen_util():
    """En v1, `ips_distintas` vacío dejaba el resumen casi sin contenido."""
    res = preprocesar(SIN_IP + "\n", modo="line")
    from src.preprocessing.aggregation import agregar_v2, derivar_v1
    v2 = agregar_v2(res)
    v1 = derivar_v1(res, v2)
    assert v1["n_ips_distintas"] == 0
    assert v2["entities"]["usuario"] == {"root": 1}
    assert v2["entities"]["proceso"] == {"cron": 1}


def test_la_reputacion_no_se_consulta_si_no_hay_ips(monkeypatch):
    """Criterio de la Fase 9: la reputación es solo para entidades IP."""
    llamadas = []
    monkeypatch.setattr(pipeline_mod, "corroborar_ips",
                        lambda ips, cache: llamadas.append(ips) or {})
    estado, _, _ = pipeline_mod._preparar_estado_inicial(SIN_IP + "\n", "t1")
    assert llamadas == []                      # no se consultó nada
    assert estado["resumen_logs"]["reputacion_ips"] == {}


# --- criterio 3: el estado no crece con el archivo ------------------------

def test_el_estado_no_guarda_los_eventos_normalizados():
    """El estado se serializa en cada checkpoint del grafo: guardar los
    eventos lo haría crecer en proporción al archivo de entrada."""
    lote = "".join(f"{AUTH}\n" for _ in range(500))
    estado, _, _ = pipeline_mod._preparar_estado_inicial(lote, "t2")
    meta = estado["preprocessing_metadata"]
    assert "events" not in meta
    assert meta["total_eventos"] == 500
    # las muestras están acotadas: una por decoder, no 500 líneas
    assert len(estado["raw_samples"]) <= 5


def test_los_metadatos_siempre_se_pueblan():
    """Con un único motor de preprocesamiento, los metadatos (esquema,
    cobertura, decoders) siempre están disponibles -- no dependen de un
    motor activo distinto."""
    estado, _, _ = pipeline_mod._preparar_estado_inicial(AUTH + "\n", "t3")
    assert estado["preprocessing_metadata"] != {}
    assert estado["preprocessing_metadata"]["total_eventos"] == 1


# --- firma versionada (Fase 11) -------------------------------------------

def test_la_firma_lleva_prefijo_de_version():
    """Una firma v1 y una v2 describen el mismo lote con vocabularios
    distintos: sus embeddings no son comparables y no deben mezclarse en la
    misma búsqueda de ChromaDB."""
    resumen = aggregate_logs(AUTH + "\n")
    assert firma_lote(resumen).startswith("v1|")
    assert firma_lote(resumen, {"total_eventos": 1}).startswith("v2|")


def test_la_firma_v2_incorpora_las_senales_nuevas():
    resumen = aggregate_logs(AUTH + "\n")
    metadatos = {
        "total_eventos": 1,
        "decoder_distribution": {"syslog": 1},
        "product_distribution": {"auth": 1},
        "severity_distribution": {},
        "event_categories": {"authentication": 1},
        "parsing": {"coverage": 1.0},
    }
    firma = firma_lote(resumen, metadatos)
    assert "decoders=[syslog:1]" in firma
    assert "categorias=[authentication:1]" in firma
    assert "cobertura=1.0" in firma


def test_dos_lotes_iguales_producen_la_misma_firma():
    a = firma_lote(aggregate_logs(AUTH + "\n"))
    b = firma_lote(aggregate_logs(AUTH + "\n"))
    assert a == b


# --- criterio 1: el grafo conserva sus nodos (7 + agente_planificador, 11-sep-2026) ---

def test_el_grafo_sigue_teniendo_ocho_nodos():
    """Guardia de regresión original (Fase 9): que el motor de
    preprocesamiento heterogéneo no alterara accidentalmente la topología
    del grafo. Actualizado a 8 tras Plan-and-Execute (11-sep-2026):
    `agente_planificador` es una adición deliberada de esa migración, no
    una regresión -- ver `src/graph/build_graph.py`."""
    from src.graph.build_graph import build_graph
    grafo = build_graph().get_graph()
    nodos = [n for n in grafo.nodes if n not in ("__start__", "__end__")]
    assert len(nodos) == 8
    assert "agente_planificador" in nodos
