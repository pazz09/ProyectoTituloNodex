"""Unicidad de los ids de documento de ChromaDB.

Los ids se armaban con `int(time.time()*1000)` a secas: dos escrituras
dentro del mismo milisegundo producían el MISMO id y ChromaDB sobrescribía
la primera en silencio. Nunca importó mientras `commit_feedback()` no tenía
llamadores; desde la Fase C es un botón que un analista puede apretar dos
veces seguidas.

Los tests fuerzan la colisión congelando `time.time()`, que es la única
forma de garantizar que las dos escrituras caigan en el mismo milisegundo
en vez de depender de que la máquina sea lo bastante rápida.
"""

import pytest

from src.memory import LongTermMemory


class ColeccionFalsa:
    """Colección con la semántica de ChromaDB que importa acá: un id
    repetido reemplaza al documento anterior en vez de agregar uno nuevo."""

    def __init__(self):
        self.docs: dict[str, tuple] = {}

    def add(self, documents, metadatas, ids):
        for i, doc, meta in zip(ids, documents, metadatas):
            self.docs[i] = (doc, meta)

    # `cargar_tecnicas_attack` usa `upsert` en vez de `add` para poder
    # actualizar de versión de ATT&CK sin duplicar; acá se comporta igual.
    upsert = add

    def count(self):
        return len(self.docs)


@pytest.fixture
def memoria(monkeypatch):
    """`LongTermMemory` sin ChromaDB ni embeddings: se saltea `__init__`
    (que abre el cliente persistente y carga el modelo) y se enchufan
    colecciones falsas."""
    m = LongTermMemory.__new__(LongTermMemory)
    m.patterns = ColeccionFalsa()
    m.errors = ColeccionFalsa()
    m.history = ColeccionFalsa()
    m.attack_techniques = ColeccionFalsa()
    return m


@pytest.fixture
def reloj_congelado(monkeypatch):
    """Garantiza la colisión: todas las llamadas ven el mismo milisegundo."""
    import src.memory
    monkeypatch.setattr(src.memory.time, "time", lambda: 1788972597.123456)


# --- el id en sí -----------------------------------------------------------

def test_dos_ids_del_mismo_milisegundo_son_distintos(reloj_congelado):
    assert LongTermMemory._nuevo_id("hist") != LongTermMemory._nuevo_id("hist")


def test_el_id_conserva_prefijo_y_timestamp(reloj_congelado):
    generado = LongTermMemory._nuevo_id("pat")
    assert generado.startswith("pat-1788972597123-")


def test_muchos_ids_seguidos_no_repiten(reloj_congelado):
    generados = [LongTermMemory._nuevo_id("err") for _ in range(500)]
    assert len(set(generados)) == 500


# --- escritura real a las colecciones --------------------------------------

def test_dos_commits_en_el_mismo_milisegundo_dejan_dos_documentos(memoria, reloj_congelado):
    memoria.commit_validated("firma", {"clasificacion_global": "a", "confianza": 0.5}, "h")
    memoria.commit_validated("firma", {"clasificacion_global": "b", "confianza": 0.5}, "h")
    assert memoria.history.count() == 2


def test_dos_promociones_en_el_mismo_milisegundo_dejan_dos_patrones(memoria, reloj_congelado):
    for clasificacion in ("a", "b"):
        memoria.commit_validated(
            "firma", {"clasificacion_global": clasificacion, "confianza": 1.0}, "h")
    assert memoria.patterns.count() == 2
    assert memoria.history.count() == 2


def test_dos_errores_en_el_mismo_milisegundo_dejan_dos_documentos(memoria, reloj_congelado):
    memoria.record_error("firma", {"x": 1}, {"corregido": "a"})
    memoria.record_error("firma", {"x": 1}, {"corregido": "b"})
    assert memoria.errors.count() == 2


def test_dos_seeds_en_el_mismo_milisegundo_dejan_dos_documentos(memoria, reloj_congelado):
    memoria.seed_pattern("firma", "clasificacion", "mitigacion")
    memoria.seed_pattern("firma", "clasificacion", "mitigacion")
    assert memoria.patterns.count() == 2


def test_dos_feedbacks_seguidos_no_se_pisan(memoria, reloj_congelado, monkeypatch):
    """El caso real: el analista aprieta el botón, se corrige y lo aprieta de
    nuevo. Las dos escrituras caen en el mismo milisegundo bajo el reloj
    congelado."""
    from src import pipeline

    monkeypatch.setattr(pipeline, "ltm", memoria)
    estado = {"_firma": "v1|lineas=23", "diagnostico": "d", "confianza": 1.0}

    pipeline.commit_feedback(estado, host="web")
    pipeline.commit_feedback(estado, host="web", correccion={
        "veredicto_humano": "incorrecto", "comentario": "me equivoqué", "confianza": 0.0})

    assert memoria.history.count() == 2
    assert memoria.patterns.count() == 1   # el negativo no promueve
    assert memoria.errors.count() == 1


# --- lo que NO debe llevar entropía ----------------------------------------

def test_las_tecnicas_de_attack_conservan_id_estable(memoria):
    """`cargar_tecnicas_attack` usa `attack-<technique_id>` a propósito: el
    `upsert` reemplaza por esa clave al actualizar de versión de ATT&CK. Si
    el id llevara azar, cada recarga duplicaría las 697 técnicas."""
    tecnica = {"technique_id": "T1110", "name": "Brute Force", "description": "..."}
    memoria.cargar_tecnicas_attack([tecnica])
    memoria.cargar_tecnicas_attack([tecnica])
    assert list(memoria.attack_techniques.docs) == ["attack-T1110"]


def test_upsert_de_attack_no_usa_nuevo_id(memoria):
    ids_generados = []
    original = LongTermMemory._nuevo_id
    try:
        LongTermMemory._nuevo_id = staticmethod(
            lambda p: ids_generados.append(p) or original(p))
        memoria.cargar_tecnicas_attack(
            [{"technique_id": "T1021", "name": "Remote Services", "description": "..."}])
    finally:
        LongTermMemory._nuevo_id = original
    assert ids_generados == []
