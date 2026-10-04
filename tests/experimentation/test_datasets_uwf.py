"""Conversión y composición de UWF (Fase 2).

**ESCRITAS, NO EJECUTADAS** (ver `tests/experimentation/__init__.py`).

Las pruebas de la conversión no leen Parquet: `convertir_shard` necesita
`pyarrow`, que vive solo en el entorno de preparación. Lo que sí se prueba
sin pyarrow es la parte que decide qué información puede salir del dataset
—la allowlist de columnas y la separación de etiquetas— y toda la
composición de casos, que opera sobre los registros ya convertidos.
"""

import csv
import io
import random

import pytest

from src.experimentation.datasets.uwf import (
    COLUMNAS_ETIQUETA,
    COLUMNAS_EVENTO,
    VALOR_BENIGNO,
    VALOR_EXCLUIDO,
    VALOR_MALICIOSO,
    verificar_separacion,
)
from src.experimentation.datasets.uwf_casos import (
    GAP_INCIDENTE,
    MAX_CONEXIONES_INCIDENTE,
    MAX_DURACION_INCIDENTE,
    MIN_CONEXIONES_INCIDENTE,
    TAMANO_CASO,
    AsignadorBenigno,
    Incidente,
    Registro,
    componer_caso,
    construir_incidentes,
    particionar_incidentes,
)


def _registro(uid, ts, binario, tactica="none", tecnica="none",
              src="10.0.0.9", shard="s1", fila=2) -> Registro:
    valores = []
    for columna in COLUMNAS_EVENTO:
        if columna == "uid":
            valores.append(uid)
        elif columna == "ts":
            valores.append(f"{ts:.6f}")
        elif columna == "datetime":
            valores.append("2021-12-13 10:00:00.000")
        elif columna == "src_ip_zeek":
            valores.append(src)
        else:
            valores.append("-")
    return Registro(uid=uid, ts=ts, valores=tuple(valores), binario=binario,
                    tacticas=(tactica,), tecnicas=(tecnica,), shard=shard,
                    fila_original=fila)


def _fondo(n, inicio=1_000_000.0, paso=10.0) -> list[Registro]:
    return [_registro(f"B{i:05d}", inicio + i * paso, VALOR_BENIGNO)
            for i in range(n)]


# --- separación de columnas ----------------------------------------------

def test_las_columnas_de_etiqueta_no_estan_en_la_allowlist_de_eventos():
    """Es una allowlist y no una denylist: si el dataset ganara una columna
    de etiqueta nueva, no entraría al CSV de eventos por omisión."""
    assert not set(COLUMNAS_EVENTO) & set(COLUMNAS_ETIQUETA)
    assert not [c for c in COLUMNAS_EVENTO if c.startswith("label")]


def test_uid_esta_en_eventos_y_en_etiquetas():
    """`uid` es la única clave que vincula las dos mitades, y tiene que
    estar en las dos para poder puntuar la reconstrucción."""
    assert "uid" in COLUMNAS_EVENTO


def test_verificar_separacion_detecta_una_columna_de_etiqueta_infiltrada(tmp_path):
    eventos = tmp_path / "eventos"
    eventos.mkdir()
    (eventos / "x.csv").write_text(
        ",".join(COLUMNAS_EVENTO + ("label_binary",)) + "\nA,1\n", encoding="utf-8"
    )
    informe = verificar_separacion(tmp_path)
    assert informe["hallazgos"]
    assert "label_binary" in informe["hallazgos"][0]["columnas"]


def test_verificar_separacion_acepta_la_cabecera_exacta(tmp_path):
    eventos = tmp_path / "eventos"
    eventos.mkdir()
    (eventos / "x.csv").write_text(
        ",".join(COLUMNAS_EVENTO) + "\n", encoding="utf-8"
    )
    assert verificar_separacion(tmp_path)["hallazgos"] == []


def test_el_valor_excluido_es_el_tercer_valor_del_dataset():
    """`label_binary` trae `Duplicate` además de True/False: no es
    clasificable y la decisión del 3-oct-2026 fue excluirlo."""
    assert VALOR_EXCLUIDO not in (VALOR_BENIGNO, VALOR_MALICIOSO)


# --- construcción de incidentes ------------------------------------------

def test_una_pausa_mayor_al_gap_separa_dos_incidentes():
    registros = (
        [_registro(f"M{i}", 100.0 + i, VALOR_MALICIOSO, "Discovery", "T1046")
         for i in range(4)]
        + [_registro(f"N{i}", 100.0 + GAP_INCIDENTE + 50 + i, VALOR_MALICIOSO,
                     "Discovery", "T1046") for i in range(4)]
    )
    incidentes = construir_incidentes(registros)
    assert len(incidentes) == 2


def test_una_rafaga_demasiado_corta_no_es_un_incidente():
    """Con menos de 3 conexiones no hay secuencia que reconstruir."""
    registros = [_registro(f"M{i}", 100.0 + i, VALOR_MALICIOSO, "Discovery")
                 for i in range(MIN_CONEXIONES_INCIDENTE - 1)]
    assert construir_incidentes(registros) == []


def test_una_rafaga_enorme_da_un_solo_incidente_truncado():
    """De un escaneo de 131 152 conexiones sale UN incidente, no miles
    correlacionados."""
    registros = [_registro(f"M{i:06d}", 100.0 + i * 0.001, VALOR_MALICIOSO,
                           "Reconnaissance", "T1595") for i in range(500)]
    incidentes = construir_incidentes(registros)
    assert len(incidentes) == 1
    assert len(incidentes[0].registros) == MAX_CONEXIONES_INCIDENTE


def test_un_incidente_demasiado_largo_se_descarta():
    """No cabría en la ventana de fondo y se desbordaría por el final,
    quedando como los últimos registros del caso."""
    paso = GAP_INCIDENTE - 1
    registros = [_registro(f"M{i}", 100.0 + i * paso, VALOR_MALICIOSO,
                           "Discovery", "T1046")
                 for i in range(int(MAX_DURACION_INCIDENTE / paso) + 5)]
    assert construir_incidentes(registros) == []


def test_distintos_origenes_no_se_mezclan_en_un_incidente():
    registros = (
        [_registro(f"A{i}", 100.0 + i, VALOR_MALICIOSO, "Discovery",
                   src="10.0.0.1") for i in range(4)]
        + [_registro(f"B{i}", 100.0 + i, VALOR_MALICIOSO, "Discovery",
                     src="10.0.0.2") for i in range(4)]
    )
    assert len(construir_incidentes(registros)) == 2


# --- partición de incidentes ---------------------------------------------

def _incidente(nombre, tactica, n=4) -> Incidente:
    return Incidente(
        incidente_id=nombre,
        registros=[_registro(f"{nombre}_{i}", 100.0 + i, VALOR_MALICIOSO,
                             tactica) for i in range(n)],
        tactica=tactica, src_ip="10.0.0.1", shard="s1",
    )


def test_la_particion_de_incidentes_estratifica_por_tactica():
    """`Resource Development` tiene 262 388 conexiones y `Collection` una:
    sin estratificar, una táctica entera podría no llegar nunca a
    evaluación."""
    incidentes = ([_incidente(f"r{i}", "Reconnaissance") for i in range(20)]
                  + [_incidente(f"d{i}", "Discovery") for i in range(10)])
    reparto = particionar_incidentes(incidentes)
    for particion in ("desarrollo", "evaluacion"):
        tacticas = {i.tactica for i in reparto[particion]}
        assert tacticas == {"Reconnaissance", "Discovery"}


def test_ningun_incidente_queda_en_las_dos_particiones():
    incidentes = [_incidente(f"r{i}", "Reconnaissance") for i in range(20)]
    reparto = particionar_incidentes(incidentes)
    ids_dev = {i.incidente_id for i in reparto["desarrollo"]}
    ids_eval = {i.incidente_id for i in reparto["evaluacion"]}
    assert not ids_dev & ids_eval


def test_la_particion_de_incidentes_es_determinista():
    incidentes = [_incidente(f"r{i}", "Reconnaissance") for i in range(20)]
    primera = particionar_incidentes(incidentes, semilla=5)
    segunda = particionar_incidentes(incidentes, semilla=5)
    assert ([i.incidente_id for i in primera["evaluacion"]]
            == [i.incidente_id for i in segunda["evaluacion"]])


# --- asignador de fondo benigno ------------------------------------------

def test_el_fondo_nunca_se_reutiliza():
    asignador = AsignadorBenigno({"s1": _fondo(100)})
    primera = asignador.tomar(40)
    segunda = asignador.tomar(40)
    assert not {r.uid for r in primera} & {r.uid for r in segunda}


def test_una_ventana_sin_extension_suficiente_se_descarta():
    """Si la ventana es más corta que el incidente, el incidente se
    desbordaría por el final del caso."""
    # 60 registros a 1 s de paso: la ventana abarca 59 s.
    asignador = AsignadorBenigno({"s1": _fondo(600, paso=1.0)})
    ventana = asignador.tomar(60, span_minimo=30.0)
    assert ventana[-1].ts - ventana[0].ts >= 30.0
    assert asignador.descartadas == 0


def test_fondo_insuficiente_falla_en_vez_de_reutilizar():
    asignador = AsignadorBenigno({"s1": _fondo(50)})
    with pytest.raises(ValueError, match="no reutilizar registros"):
        asignador.tomar(40)
        asignador.tomar(40)


# --- composición del caso ------------------------------------------------

def _componer(con_incidente=True, n_incidente=10):
    incidente = None
    if con_incidente:
        incidente = Incidente(
            incidente_id="inc_01",
            registros=[_registro(f"M{i}", 500.0 + i * 2, VALOR_MALICIOSO,
                                 "Discovery", "T1046", shard="s2")
                       for i in range(n_incidente)],
            tactica="Discovery", src_ip="10.0.0.1", shard="s2",
        )
    fondo = _fondo(TAMANO_CASO - (n_incidente if con_incidente else 0))
    return componer_caso("uwf_eva_visible_0000", "evaluacion", "visible",
                         fondo, incidente, random.Random(1))


def test_el_caso_compuesto_no_contiene_ninguna_etiqueta():
    caso, _ = _componer()
    assert "label" not in caso.contenido
    assert "Discovery" not in caso.contenido
    assert "T1046" not in caso.contenido
    assert VALOR_MALICIOSO not in caso.contenido.split("\n")[0]


def test_el_caso_declara_que_es_un_escenario_sintetico():
    """El plan exige declararlo: es tráfico compuesto, no capturado así."""
    caso, _ = _componer()
    assert caso.notas["escenario"] == "sintetico_controlado"


def test_el_caso_registra_proporcion_fuentes_y_semilla():
    caso, _ = _componer(n_incidente=15)
    notas = caso.notas
    assert notas["n_registros_maliciosos"] == 15
    assert notas["n_registros_benignos"] == TAMANO_CASO - 15
    assert notas["proporcion_maliciosa"] == round(15 / TAMANO_CASO, 6)
    assert notas["shard_incidente"] == "s2"
    assert notas["shards_fondo"] == ["s1"]
    assert notas["semilla"]


def test_el_offset_permite_recuperar_el_ts_original():
    caso, referencia = _componer()
    offset = caso.notas["offset_rebase_segundos"]
    assert offset != 0
    filas = list(csv.DictReader(io.StringIO(caso.contenido)))
    nucleo = set(referencia.core_event_uids)
    for fila in filas:
        if fila["uid"] in nucleo:
            # El ts del caso menos el offset tiene que caer en la ventana
            # original del incidente (500.0 en adelante).
            assert float(fila["ts"]) - offset >= 500.0
            break


def test_el_incidente_no_queda_en_los_extremos_del_caso():
    """Si empezara en el primer registro o terminara en el último, su
    posición lo delataría sin necesidad de analizar nada."""
    caso, referencia = _componer()
    filas = list(csv.DictReader(io.StringIO(caso.contenido)))
    nucleo = set(referencia.core_event_uids)
    posiciones = [i for i, f in enumerate(filas) if f["uid"] in nucleo]
    assert min(posiciones) > 0
    assert max(posiciones) < len(filas) - 1


def test_las_filas_del_caso_quedan_ordenadas_por_tiempo():
    caso, _ = _componer()
    filas = list(csv.DictReader(io.StringIO(caso.contenido)))
    ts = [float(f["ts"]) for f in filas]
    assert ts == sorted(ts)


def test_datetime_se_recalcula_para_que_no_contradiga_al_ts():
    caso, referencia = _componer()
    filas = list(csv.DictReader(io.StringIO(caso.contenido)))
    nucleo = set(referencia.core_event_uids)
    rebasada = next(f for f in filas if f["uid"] in nucleo)
    # El datetime original del fixture es de 2021-12-13; tras el rebase el
    # ts queda en 1970 (1 000 000 s), así que el datetime no puede seguir
    # siendo el original.
    assert not rebasada["datetime"].startswith("2021-12-13")


def test_core_event_uids_son_exactamente_los_del_incidente():
    caso, referencia = _componer(n_incidente=7)
    assert len(referencia.core_event_uids) == 7
    filas = list(csv.DictReader(io.StringIO(caso.contenido)))
    assert set(referencia.core_event_uids) <= {f["uid"] for f in filas}


def test_un_caso_sin_incidente_deja_reconstruccion_y_mitre_no_aplica():
    """No hay nada que reconstruir ni atribuir: no es un acierto por
    defecto, es una dimensión que no corresponde."""
    _, referencia = _componer(con_incidente=False)
    assert referencia.estado_dimension["reconstruccion"] == "no_aplica"
    assert referencia.estado_dimension["mitre"] == "no_aplica"
    assert referencia.core_event_uids == ()
    assert referencia.etiqueta_deteccion == "normal"


def test_las_referencias_mitre_citan_la_evidencia():
    _, referencia = _componer()
    assert referencia.referencias_mitre
    for mitre in referencia.referencias_mitre:
        assert mitre.evidence_uids == referencia.core_event_uids
    niveles = {m.nivel for m in referencia.referencias_mitre}
    assert niveles == {"tactica", "tecnica"}


def test_la_referencia_de_uwf_viene_del_dataset_y_no_de_nodex():
    _, referencia = _componer()
    assert referencia.anotacion["fuente"] == "dataset"


def test_el_caso_de_uwf_es_de_tipo_seguridad():
    """UWF etiqueta tráfico malicioso, así que el veredicto que corresponde
    leer es `hay_incidente`, no `hay_anomalia`."""
    caso, _ = _componer()
    assert caso.tipo_deteccion == "seguridad"
    assert set(caso.dimensiones_aplicables) == {
        "deteccion", "reconstruccion", "mitre", "reporte", "consumo"}


def test_la_procedencia_distingue_el_fondo_del_incidente():
    caso, referencia = _componer()
    grupos = {r.grupo for r in caso.procedencia}
    assert "inc_01" in grupos
    assert any(g.startswith("fondo:") for g in grupos)
    for registro in caso.procedencia:
        assert registro.uid
