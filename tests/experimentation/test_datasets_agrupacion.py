"""Agrupación y partición de datasets (Fase 2).

**ESCRITAS, NO EJECUTADAS** (ver `tests/experimentation/__init__.py`).

Las pruebas centrales son las que bloquean los tres defectos medidos del
generador anterior: atribuir una línea a un solo `blk_`, reutilizar grupos
entre lotes y forzar un positivo por lote.
"""

import pytest

from src.experimentation.datasets.agrupacion import (
    agrupar_bgl,
    agrupar_hdfs,
    etiqueta_bgl,
)
from src.experimentation.datasets.generador import (
    EspecificacionCasos,
    generar_campana,
    generar_casos,
)
from src.experimentation.datasets.particion import (
    particionar_grupos,
    verificar_sin_fuga,
)

# --- HDFS: una línea con varios bloques ----------------------------------

#: Reproduce el caso real: la línea 3 menciona dos bloques, así que los
#: dos tienen que caer en el MISMO grupo. Si se separaran, la línea se
#: duplicaría entre dos casos.
_HDFS_LOG = """\
081109 203615 148 INFO dfs.DataNode$PacketResponder: Receiving block blk_1 src: /10.0.0.1 dest: /10.0.0.2
081109 203807 222 INFO dfs.DataNode$PacketResponder: Received block blk_2 of size 67108864 from /10.0.0.3
081109 204005 308 INFO dfs.FSNamesystem: BLOCK* ask 10.0.0.4 to delete blk_2 blk_3
081109 204132 401 INFO dfs.DataNode$DataXceiver: Served block blk_4 to /10.0.0.5
"""

_HDFS_LABELS = """\
BlockId,Label
blk_1,Normal
blk_2,Anomaly
blk_3,Normal
blk_4,Normal
"""


@pytest.fixture
def hdfs(tmp_path):
    log = tmp_path / "HDFS_mini.log"
    log.write_text(_HDFS_LOG, encoding="utf-8")
    etiquetas = tmp_path / "labels.csv"
    etiquetas.write_text(_HDFS_LABELS, encoding="utf-8")
    return agrupar_hdfs(log, etiquetas)


def test_los_bloques_que_comparten_una_linea_quedan_en_un_solo_grupo(hdfs):
    """`re.search` atribuía la línea al primer `blk_` y perdía el resto. En
    `HDFS_2k.log` eso afecta a 266 de 2000 líneas."""
    por_miembro = {m: g for g in hdfs for m in g.miembros}
    assert por_miembro["blk_2"].grupo == por_miembro["blk_3"].grupo


def test_ninguna_linea_pertenece_a_dos_grupos(hdfs):
    vistas = [l.linea_original for g in hdfs for l in g.lineas]
    assert len(vistas) == len(set(vistas))


def test_el_grupo_es_positivo_si_alguno_de_sus_bloques_lo_es(hdfs):
    """`blk_2` es anómalo y comparte grupo con `blk_3`, que es normal: el
    grupo mixto cuenta como positivo, porque el veredicto del caso afirma
    'hay al menos una anomalía acá'."""
    mixto = next(g for g in hdfs if "blk_2" in g.miembros)
    assert mixto.es_positivo is True
    assert "blk_3" in mixto.miembros


def test_el_nombre_del_grupo_declara_cuantos_bloques_agrupa(hdfs):
    mixto = next(g for g in hdfs if len(g.miembros) > 1)
    assert mixto.grupo.endswith("+1")


def test_el_contenido_de_hdfs_no_lleva_etiqueta(hdfs):
    """HDFS trae la etiqueta en un CSV aparte, así que la línea va íntegra;
    lo que no puede pasar es que aparezca la palabra de la etiqueta."""
    for grupo in hdfs:
        for linea in grupo.lineas:
            assert "Anomaly" not in linea.contenido


# --- BGL: la etiqueta viene embebida -------------------------------------

_BGL_LOG = "\n".join(
    [f"- 114961{i:02d} 2005.06.03 R02-M1-N0-C:J12-U11 INFO instruction cache {i}"
     for i in range(4)]
    + [f"KERNDTLB 114961{i:02d} 2005.06.03 R02-M1-N0-C:J12-U11 FATAL data TLB error {i}"
       for i in range(4, 6)]
) + "\n"


@pytest.fixture
def bgl(tmp_path):
    log = tmp_path / "BGL_mini.log"
    log.write_text(_BGL_LOG, encoding="utf-8")
    return agrupar_bgl(log, tamano_ventana=3)


def test_la_etiqueta_embebida_de_bgl_se_retira_del_contenido(bgl):
    """Es la fuga que el proyecto ya tuvo: dejar `KERNDTLB` como primer
    token le da la respuesta a la arquitectura."""
    for grupo in bgl:
        for linea in grupo.lineas:
            assert not linea.contenido.startswith("KERNDTLB")
            assert not linea.contenido.startswith("- ")


def test_la_ventana_es_positiva_si_alguna_linea_trae_alerta(bgl):
    assert [g.es_positivo for g in bgl] == [False, True]


def test_las_ventanas_son_disjuntas_y_cubren_el_archivo(bgl):
    vistas = [l.linea_original for g in bgl for l in g.lineas]
    assert vistas == sorted(vistas) == list(range(1, 7))


def test_el_nombre_de_la_ventana_la_hace_trazable_al_archivo(bgl):
    assert bgl[0].grupo == "bgl_l00001-00003"


def test_etiqueta_bgl_distingue_ausencia_de_alerta():
    assert etiqueta_bgl("- 1149 2005.06.03 nodo INFO algo") == "-"
    assert etiqueta_bgl("KERNDTLB 1149 2005.06.03 nodo FATAL algo") == "KERNDTLB"
    assert etiqueta_bgl("") == ""


def test_tamano_de_ventana_invalido_se_rechaza(tmp_path):
    log = tmp_path / "x.log"
    log.write_text(_BGL_LOG, encoding="utf-8")
    with pytest.raises(ValueError, match="tamano_ventana"):
        agrupar_bgl(log, tamano_ventana=0)


# --- partición por grupo -------------------------------------------------

def test_ningun_grupo_queda_en_las_dos_particiones(hdfs):
    reparto = particionar_grupos(hdfs, proporcion_desarrollo=0.5)
    verificar_sin_fuga(reparto)
    nombres_dev = {g.grupo for g in reparto["desarrollo"]}
    nombres_eval = {g.grupo for g in reparto["evaluacion"]}
    assert not nombres_dev & nombres_eval


def test_la_particion_es_determinista_dada_la_semilla(hdfs):
    primera = particionar_grupos(hdfs, semilla=7)
    segunda = particionar_grupos(hdfs, semilla=7)
    assert [g.grupo for g in primera["evaluacion"]] == [
        g.grupo for g in segunda["evaluacion"]
    ]


def test_la_particion_detecta_grupos_repetidos(hdfs):
    with pytest.raises(ValueError, match="repetidos"):
        particionar_grupos(hdfs + [hdfs[0]])


def test_proporcion_fuera_de_rango_se_rechaza(hdfs):
    with pytest.raises(ValueError, match="proporcion_desarrollo"):
        particionar_grupos(hdfs, proporcion_desarrollo=1.0)


def test_la_fuga_entre_particiones_se_detecta(hdfs):
    reparto = {"desarrollo": [hdfs[0]], "evaluacion": [hdfs[0]]}
    with pytest.raises(ValueError, match="fuga entre particiones"):
        verificar_sin_fuga(reparto)
