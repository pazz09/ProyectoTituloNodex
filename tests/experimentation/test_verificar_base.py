"""Verificación de la base de ChromaDB (knowledge/verificar_base.py).

Las comparaciones son funciones puras y se prueban sin cargar Chroma ni el modelo
de embeddings. La prueba que SÍ abre una base con el código de NODEX está al final.
"""

import json
from pathlib import Path

import pytest

from src.experimentation.knowledge import verificar_base as vb

RAIZ = Path(__file__).resolve().parents[2]


# --- el conjunto fijo de consultas ----------------------------------------------

def test_hay_un_conjunto_fijo_de_doce_consultas_distintas():
    assert len(vb.CONSULTAS_FIJAS) == 12
    assert len(set(vb.CONSULTAS_FIJAS)) == 12


def test_las_consultas_son_ajenas_a_los_casos_del_experimento():
    case_ids = {p.stem for p in (RAIZ / "experiments" / "cases").rglob("*.json")}
    assert case_ids, "no se encontraron casos para comparar"
    for consulta in vb.CONSULTAS_FIJAS:
        for case_id in case_ids:
            assert case_id not in consulta


def test_las_consultas_no_contienen_texto_de_ningun_log_de_caso():
    """No se sacaron de los casos: ninguna línea de un caso aparece en ellas."""
    caso = next((RAIZ / "experiments" / "cases" / "bgl" / "desarrollo").glob("*.log"))
    lineas = [l.strip() for l in caso.read_text(encoding="utf-8").splitlines() if l.strip()]
    for consulta in vb.CONSULTAS_FIJAS:
        assert not any(l in consulta for l in lineas[:200])


# --- comparar resultados ----------------------------------------------------------

def _res(consultas):
    return {"consultas": consultas}


def _c(texto="q", ids=("a", "b", "c"), dist=(0.1, 0.2, 0.3), nodex=(("T1", 0.9),)):
    return {"consulta": texto, "ids": list(ids), "distancias": list(dist),
            "nodex": [{"technique_id": t, "similitud": s} for t, s in nodex]}


def test_resultados_identicos_no_reportan_diferencias():
    r = vb.comparar_resultados(_res([_c()]), _res([_c()]))
    assert r["con_mismos_ids_y_orden"] == 1
    assert r["con_mismo_resultado_para_nodex"] == 1
    assert r["diferencia_maxima_de_distancia"] == 0.0
    assert r["consultas_con_diferencias"] == []


def test_un_cambio_de_orden_se_reporta_aunque_el_conjunto_sea_el_mismo():
    r = vb.comparar_resultados(_res([_c()]), _res([_c(ids=("b", "a", "c"))]))
    c = r["consultas_con_diferencias"][0]
    assert c["mismos_ids_y_orden"] is False
    assert c["mismo_conjunto_de_ids"] is True
    assert r["con_mismos_ids_y_orden"] == 0


def test_la_mayor_diferencia_de_distancia_se_informa_aunque_los_ids_coincidan():
    r = vb.comparar_resultados(_res([_c()]), _res([_c(dist=(0.1, 0.2, 0.3000004))]))
    assert r["con_mismos_ids_y_orden"] == 1
    assert r["diferencia_maxima_de_distancia"] == pytest.approx(4e-7)


def test_una_diferencia_en_lo_que_ve_nodex_se_reporta():
    r = vb.comparar_resultados(_res([_c()]), _res([_c(nodex=(("T2", 0.9),))]))
    assert r["con_mismo_resultado_para_nodex"] == 0
    assert r["consultas_con_diferencias"][0]["nodex_viejo"] == [("T1", 0.9)]
    assert r["consultas_con_diferencias"][0]["nodex_nuevo"] == [("T2", 0.9)]


def test_comparar_consultas_distintas_es_un_error():
    with pytest.raises(ValueError):
        vb.comparar_resultados(_res([_c("a")]), _res([_c("b")]))


# --- revisar contenido ----------------------------------------------------------------

def _cont(**cambios):
    base = {"ids": ["attack-T1", "attack-T2"],
            "documents": ["uno", "dos"],
            "metadatas": [{"technique_id": "T1", "name": "n", "tactics": "x",
                           "is_subtechnique": False, "url": "u"},
                          {"technique_id": "T2", "name": "m", "tactics": "y",
                           "is_subtechnique": False, "url": "v"}]}
    base.update(cambios)
    return base


def test_un_contenido_igual_y_limpio_pasa():
    r = vb.revisar_contenido(_cont(), _cont(), {"uwf_des_a_0001"})
    assert vb.contenido_limpio(r)
    assert r["claves_de_metadatos_inesperadas"] == []


def test_un_case_id_dentro_del_contenido_se_detecta():
    sucio = _cont(documents=["uno", "texto con uwf_des_a_0001 adentro"])
    r = vb.revisar_contenido(_cont(), sucio, {"uwf_des_a_0001"})
    assert r["case_ids_encontrados_en_el_contenido"] == ["uwf_des_a_0001"]
    assert not vb.contenido_limpio(r)


def test_una_clave_de_metadatos_ajena_al_catalogo_se_detecta():
    metas = _cont()["metadatas"]
    metas[0] = metas[0] | {"feedback": "correcto"}
    r = vb.revisar_contenido(_cont(), _cont(metadatas=metas), set())
    assert r["claves_de_metadatos_inesperadas"] == ["feedback"]
    assert not vb.contenido_limpio(r)


def test_un_documento_distinto_o_un_orden_distinto_se_detectan():
    assert not vb.revisar_contenido(_cont(), _cont(documents=["uno", "otro"]), set())[
        "mismos_documentos"]
    assert not vb.revisar_contenido(_cont(), _cont(ids=["attack-T2", "attack-T1"]), set())[
        "mismos_ids_y_orden"]


# --- el control que habría detectado el defecto original ----------------------------

def _nodex_puede_abrir(chroma: Path):
    """Intenta abrir `chroma` con el código de NODEX. `None` si abre; el error si no."""
    try:
        vb.abrir_con_memoria(RAIZ, chroma)
    except RuntimeError as e:
        return str(e)
    return None


def test_la_base_v1_no_se_puede_abrir_con_el_codigo_de_nodex_y_el_control_lo_detecta():
    """Regresión del defecto: la base anterior se creó sin función de embeddings
    y `src/memory.py` no puede abrirla. La verificación de ANTES (solo contar
    documentos) no lo veía; esta sí."""
    pytest.importorskip("chromadb")
    from src.experimentation.knowledge.aislamiento import configuracion_experimental
    error = _nodex_puede_abrir(configuracion_experimental(RAIZ).chroma_v1)
    assert error is not None
    assert "embedding function" in error.lower()


def test_la_base_experimental_activa_se_abre_con_el_codigo_de_nodex():
    pytest.importorskip("chromadb")
    from src.experimentation.knowledge.aislamiento import configuracion_experimental
    activa = configuracion_experimental(RAIZ).chroma
    if not (activa / "chroma.sqlite3").is_file():
        pytest.fail(f"la base experimental activa no existe: {activa}")
    abierta = vb.abrir_con_memoria(RAIZ, activa)
    assert abierta["n_attack_techniques"] == 697
    assert len(abierta["consultas"]) == len(vb.CONSULTAS_FIJAS)
    assert all(c["ids"] for c in abierta["consultas"])     # cada consulta devolvió algo


# --- base activa, base anterior y congelación ---------------------------------------

def test_la_configuracion_aislada_apunta_a_la_base_v2_y_conserva_la_v1_aparte():
    from src.experimentation.knowledge.aislamiento import configuracion_experimental
    conf = configuracion_experimental(RAIZ)
    assert conf.chroma.name == "chroma_v2"
    assert conf.chroma_v1.name == "chroma"
    assert conf.chroma != conf.chroma_v1
    assert conf.variables_entorno()["CHROMA_PATH"] == str(conf.chroma)
    # los archivos de la v1 no se reescriben: la v2 tiene los suyos
    assert conf.inventario.name == "inventario_conocimiento_v2.json"
    assert conf.poblado.name == "poblado_chroma_v2.json"


def test_la_base_v1_sigue_intacta_segun_los_hashes_que_se_le_registraron():
    import hashlib
    registro = json.loads((RAIZ / "experiments" / "knowledge" / "poblado_chroma.json")
                          .read_text(encoding="utf-8"))
    for rel, meta in registro["snapshot"]["archivos"].items():
        real = hashlib.sha256((RAIZ / "experiments" / "knowledge" / "chroma" / rel)
                              .read_bytes()).hexdigest()
        assert real == meta["sha256"], rel


def test_la_base_v2_coincide_con_sus_hashes_registrados():
    import hashlib
    registro = json.loads((RAIZ / "experiments" / "knowledge" / "poblado_chroma_v2.json")
                          .read_text(encoding="utf-8"))
    assert registro["snapshot"]["archivos"]
    for rel, meta in registro["snapshot"]["archivos"].items():
        real = hashlib.sha256((RAIZ / "experiments" / "knowledge" / "chroma_v2" / rel)
                              .read_bytes()).hexdigest()
        assert real == meta["sha256"], rel


def test_el_informe_de_verificacion_de_la_v2_no_tiene_diferencias_ocultas():
    informe = json.loads((RAIZ / "experiments" / "knowledge" / "verificacion_chroma_v2.json")
                         .read_text(encoding="utf-8"))
    assert informe["se_abre_con_el_codigo_de_memory_py"] is True
    assert informe["n_attack_techniques"] == 697
    assert informe["colecciones_en_la_base_nueva"] == ["attack_techniques"]
    assert informe["contenido_limpio"] is True
    c = informe["comparacion_de_consultas"]
    assert c["n_consultas"] == len(vb.CONSULTAS_FIJAS) == 12
    # lo que difirió, si algo, quedó listado y no solo contado
    assert c["con_mismos_ids_y_orden"] + len([
        d for d in c["consultas_con_diferencias"] if not d["mismos_ids_y_orden"]]) == 12
    assert informe["vectores_vs_modelo"]["coseno_minimo"] > 0.9999


def test_la_configuracion_congelada_registra_los_hashes_de_la_v2_y_la_bandera_de_respaldo():
    from types import SimpleNamespace
    from src.experimentation.runtime.configuracion import PARAMETROS_CONGELADOS, congelar
    modulo = SimpleNamespace(**{nombre: "x" for nombre in PARAMETROS_CONGELADOS},
                             GEMINI_API_KEY=None, GOOGLE_API_KEY=None,
                             ABUSEIPDB_API_KEY=None, NVD_API_KEY=None)
    c = congelar("prueba", RAIZ, modulo_config=modulo)
    for clave in ("inventario_v2_sha256", "poblado_v2_sha256", "verificacion_v2_sha256"):
        assert len(c.conocimiento[clave]) == 64, clave
    assert "LLM_SIN_RESPALDO" in c.parametros
