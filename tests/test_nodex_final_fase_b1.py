"""NODEX final, Fase B.1: memoria contrastiva por lote, memoria por grupo de eventos, motivo factual
de cada grupo con señal y lista de patrones MITRE (hoy, entrada del auditor reforzado).

Sin API: el modelo se simula. Lotes sintéticos; ninguna prueba abre casos de la partición de
evaluación ni su ground truth.
"""

import json
import re
from pathlib import Path

import pytest

import src.config as config
from tests.test_nodex_final_fase_a import estado_de, lote_bgl, lote_red

RAIZ = Path(__file__).resolve().parents[1]


class ColeccionConDocumentos:
    """Colección falsa con documentos (para leer el tipo de lote de cada patrón)."""

    def __init__(self, patrones):
        self.patrones = patrones          # [(id, distancia, documento, metadatos)]

    def count(self):
        return len(self.patrones)

    def query(self, query_texts, n_results):
        orden = sorted(self.patrones, key=lambda p: p[1])[:n_results]
        return {"ids": [[p[0] for p in orden]], "distances": [[p[1] for p in orden]],
                "documents": [[p[2] for p in orden]], "metadatas": [[p[3] for p in orden]]}


def _patron(pid, dist, tipo, etiqueta, huellas=()):
    doc = ("Grupos con señal: x" if tipo == "red" else "Eventos destacados: x")
    return (pid, dist, doc, {"historical_case_id": pid, "etiqueta": etiqueta, "descripcion": f"d-{pid}",
                             "huellas": json.dumps(list(huellas))})


COLECCION = ColeccionConDocumentos([
    _patron("propio", 0.00, "red", "normal", ["uid:A"]),
    _patron("n1", 0.01, "red", "normal"), _patron("n2", 0.02, "red", "normal"), _patron("n3", 0.03, "red", "normal"),
    _patron("t1", 0.04, "texto", "anomalo"),
    _patron("m1", 0.20, "red", "malicioso"), _patron("m2", 0.30, "red", "malicioso"),
    _patron("m3", 0.40, "red", "malicioso"),
])


# --- B.1-1: memoria contrastiva por lote --------------------------------------------------

def test_contrastiva_devuelve_k_por_clase_del_mismo_tipo_y_sin_solapamiento():
    from src.tools.memoria_historica import consultar_historicos
    r = consultar_historicos(COLECCION, "q", ["uid:A"], 3, k_por_clase=2, tipo="red")
    assert [c["id"] for c in r["casos"]] == ["n1", "n2", "m1", "m2"]
    assert {c["clase"] for c in r["casos"]} == {"normal", "anomala"}
    assert r["excluidos_por_solapamiento"] == ["propio"] and r["omitidos_otro_tipo"] == 1
    assert r["contrastiva"] is True and r["k_por_clase"] == 2


def test_sin_contrastiva_se_mantiene_la_consulta_de_la_fase_b():
    from src.tools.memoria_historica import consultar_historicos
    r = consultar_historicos(COLECCION, "q", ["uid:A"], 3)
    assert [c["id"] for c in r["casos"]] == ["n1", "n2", "n3"] and "contrastiva" not in r


def test_el_bloque_contrastivo_separa_clases_y_no_muestra_similitud(monkeypatch):
    from src.tools.memoria_historica import consultar_historicos, contexto_historico
    casos = consultar_historicos(COLECCION, "q", ["uid:A"], 3, k_por_clase=2, tipo="red")["casos"]
    texto = contexto_historico(casos)
    assert "CASOS HISTÓRICOS DE LA ORGANIZACIÓN" in texto and "no una votación" in texto
    assert texto.index("d-n1") < texto.index("ANÓMALOS") < texto.index("d-m1")
    assert "similitud" not in texto
    monkeypatch.setattr(config, "HISTORICO_CONTRASTIVO", False)
    assert "similitud" in contexto_historico(casos)


def test_el_pipeline_pide_la_consulta_contrastiva_con_el_tipo_del_lote(monkeypatch):
    import src.pipeline as pipeline
    import src.tools.memoria_historica as mh
    visto = {}

    def falsa(coleccion, representacion, huellas, k, **kwargs):
        visto.update(kwargs)
        return {"casos": [], "excluidos_por_solapamiento": [], "consultados": 0}

    monkeypatch.setattr(mh, "consultar_historicos", falsa)
    estado_de(lote_red())
    assert visto == {"k_por_clase": config.HISTORICO_K_POR_CLASE, "tipo": "red"}
    visto.clear()
    monkeypatch.setattr(config, "HISTORICO_CONTRASTIVO", False)
    estado_de(lote_red())
    assert visto == {}


# --- B.1-3a: motivo factual -------------------------------------------------------------

def test_motivo_factual_de_cada_senal_y_no_llega_al_triage():
    from src.preprocessing.prompt_context import contexto_contenido_lote
    estado = estado_de(lote_red())
    flujos = {f["group_id"]: f for f in estado["contenido_lote"]["flujos_minoritarios"]}
    textos = " | ".join(t for f in flujos.values() for t in f["motivos_factuales"])
    assert "20 puertos de destino distintos de un mismo destino (tcp)" in textos
    assert "actúa como origen en" in textos and "como destino solo en" in textos
    assert "motivos_factuales" not in contexto_contenido_lote(estado["contenido_lote"])


# --- B.1-2: memoria por grupo de eventos ---------------------------------------------------

def test_la_representacion_de_grupo_describe_comportamiento_sin_ip():
    from src.preprocessing.pipeline import preprocesar
    from src.tools.memoria_grupos import representacion_grupo_red
    eventos = [e for e in preprocesar(lote_red()).events if e.protocol == "tcp" and e.destination_port >= 1000]
    texto = representacion_grupo_red(eventos, ["barrido_de_puertos"], ["un mismo origen contactó 20 puertos"])
    assert "barrido_de_puertos" in texto and "20 puertos de destino distintos" in texto and "REJ 20" in texto
    assert not re.search(r"\d+\.\d+\.\d+\.\d+", texto)


def _embed_falso(textos):
    return [[1.0, 0.0] if "dns" in t else [0.0, 1.0] for t in textos]


MEMORIA = {"nombre": "prueba", "entradas": [
    {"id": "c1:G1", "case_id": "c1", "etiqueta": "malicioso", "tacticas": ["Reconnaissance"],
     "representacion": "dns ráfaga", "huellas": ["uid:Z"], "embedding": [1.0, 0.0]},
    {"id": "c2:G1", "case_id": "c2", "etiqueta": "malicioso", "tacticas": ["Discovery"],
     "representacion": "barrido", "huellas": ["uid:Y"], "embedding": [0.0, 1.0]},
    {"id": "c3:G2", "case_id": "c3", "etiqueta": "benigno", "tacticas": [],
     "representacion": "dns normal", "huellas": ["uid:Q"], "embedding": [0.9, 0.1]},
]}


def test_consulta_de_grupos_contrastiva_con_exclusion_por_solapamiento():
    from src.tools.memoria_grupos import consultar_memoria_grupos
    r = consultar_memoria_grupos(MEMORIA, [{"group_id": "G05", "representacion": "dns x"}], ["uid:Z"], _embed_falso)
    assert r["excluidos_por_solapamiento"] == ["c1:G1"]
    item = r["por_grupo"]["G05"]
    assert item["malicioso"]["id"] == "c2:G1" and item["benigno"]["id"] == "c3:G2"
    assert item["malicioso"]["tacticas"] == ["Discovery"]


def test_los_grupos_con_senal_traen_motivo_factual_y_referentes(monkeypatch):
    from src.tools.grupos_con_senal import grupos_con_senal
    estado = estado_de(lote_red())
    gid = estado["contenido_lote"]["flujos_minoritarios"][0]["group_id"]
    estado["memoria_grupos"] = {gid: {"representacion": "r", "malicioso": {
        "id": "c2:G1", "etiqueta": "malicioso", "tacticas": ["Discovery"], "comportamiento": "barrido",
        "similitud": 0.9}, "benigno": None}}
    grupo = next(g for g in grupos_con_senal(estado) if g["group_id"] == gid)
    assert grupo["motivos_factuales"]
    assert grupo["memoria"] == {"malicioso_mas_parecido": {"tacticas": ["Discovery"], "comportamiento": "barrido"},
                                "benigno_mas_parecido": None}
    monkeypatch.setattr(config, "GRUPOS_MOTIVO_FACTUAL", False)
    monkeypatch.setattr(config, "MEMORIA_GRUPOS_ACTIVA", False)
    grupo = next(g for g in grupos_con_senal(estado) if g["group_id"] == gid)
    assert "motivos_factuales" not in grupo and "memoria" not in grupo


def test_en_texto_no_hay_memoria_de_grupos():
    estado = estado_de(lote_bgl())
    assert estado["memoria_grupos"] == {}


def test_la_memoria_de_grupos_construida_no_tiene_ip_ni_casos_de_evaluacion():
    archivo = RAIZ / "experiments/knowledge/memoria_grupos_v1/memoria_grupos.json"
    if not archivo.exists():
        pytest.skip("memoria de grupos no construida")
    memoria = json.loads(archivo.read_text(encoding="utf-8"))
    assert memoria["entradas"]
    for e in memoria["entradas"]:
        assert "_des_" in e["case_id"] and "_eva_" not in e["case_id"]
        assert not re.search(r"\d+\.\d+\.\d+\.\d+", e["representacion"])
        assert e["etiqueta"] in ("malicioso", "benigno") and len(e["embedding"]) > 0


# --- B.1-3b: lista de patrones ----------------------------------------------------------------

def test_las_instrucciones_traen_la_lista_y_piden_patron():
    from src.tools.grupos_con_senal import IDS_PATRONES, instrucciones_grupos
    texto = instrucciones_grupos()
    assert "LISTA DE VERIFICACIÓN" in texto and "patron_lista" in texto
    for pid in IDS_PATRONES[:-1]:
        assert pid in texto
    assert "T1046" in texto and "T1110" in texto


def test_con_los_interruptores_apagados_no_hay_instrucciones_de_grupos(monkeypatch):
    from src.tools.grupos_con_senal import instrucciones_grupos
    for nombre in ("GRUPOS_MOTIVO_FACTUAL", "LISTA_PATRONES_MITRE", "MEMORIA_GRUPOS_ACTIVA"):
        monkeypatch.setattr(config, nombre, False)
    assert instrucciones_grupos() == ""


# --- agente único --------------------------------------------------------------------------------

def test_el_agente_unico_recibe_la_memoria_de_grupos_y_la_contrastiva(monkeypatch):
    import src.pipeline as pipeline
    import src.single_agent as single
    monkeypatch.setattr(pipeline, "_consultar_memoria_grupos", lambda r, a: {
        "por_grupo": {"G02": {"representacion": "Señal: barrido", "benigno": None, "malicioso": {
            "id": "c2:G1", "etiqueta": "malicioso", "tacticas": ["Discovery"], "comportamiento": "barrido",
            "similitud": 0.9}}}, "excluidos_por_solapamiento": [], "consultados": 3})
    original = pipeline._consultar_memoria_historica
    monkeypatch.setattr(pipeline, "_consultar_memoria_historica", lambda r, a: dict(
        original(r, a), casos=[{"id": "h", "etiqueta": "normal", "clase": "normal", "descripcion": "dn"},
                               {"id": "m", "etiqueta": "malicioso", "clase": "anomala", "descripcion": "dm"}]))
    visto = {}

    def falso(prompt, system=None, **_):
        visto["prompt"] = prompt
        return {"diagnostico": "x", "hay_anomalia": False, "hay_incidente": False, "confianza": 0.9,
                "evaluacion": "x", "comandos_mitigacion": [], "eventos_reconstruidos": [],
                "secuencia_temporal": [], "tecnicas_atribuidas": []}

    monkeypatch.setattr(single, "llm_json", falso)
    single.analizar_lote_agente_unico(lote_red())
    assert "MEMORIA DE GRUPOS ETIQUETADOS" in visto["prompt"] and "malicioso más parecido (Discovery)" in visto["prompt"]
    assert "casos ANÓMALOS o MALICIOSOS" in visto["prompt"]


# --- arnés: exclusión por incidente --------------------------------------------------------------

def test_el_arnes_filtra_el_mismo_incidente_antes_de_elegir_por_clase(tmp_path, monkeypatch):
    import src.tools.memoria_grupos as mg
    import src.tools.memoria_historica as mh
    from tools import evaluar_desarrollo_fase_b as arnes
    monkeypatch.setattr(mh, "consultar_historicos", mh.consultar_historicos)
    monkeypatch.setattr(mg, "consultar_memoria_grupos", mg.consultar_memoria_grupos)
    ruta = tmp_path / "excluir.json"
    ruta.write_text(json.dumps(["m1", "c2"]), encoding="utf-8")
    arnes._instalar_exclusion(str(ruta))
    r = mh.consultar_historicos(COLECCION, "q", ["uid:A"], 3, k_por_clase=2, tipo="red")
    assert [c["id"] for c in r["casos"]] == ["n1", "n2", "m2", "m3"] and r["excluidos_mismo_incidente"] == ["m1"]
    g = mg.consultar_memoria_grupos(MEMORIA, [{"group_id": "G05", "representacion": "barrido"}], [], _embed_falso)
    assert g["excluidos_mismo_incidente"] == ["c2:G1"] and g["por_grupo"]["G05"]["malicioso"]["id"] == "c1:G1"
