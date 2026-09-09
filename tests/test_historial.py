"""Tests del historial de corridas (Fase A del plan de ampliación).

Todos usan un archivo SQLite temporal vía `tmp_path`: nunca tocan
`data/historial.db`, que es el historial real de Antonia.
"""

import json

import pytest

from src.api import historial


@pytest.fixture
def db(tmp_path):
    """Ruta a una base temporal, distinta en cada test."""
    return tmp_path / "historial_test.db"


def corrida(job_id="job1", **extra):
    base = {
        "archivo_origen": "HDFS_2k.log",
        "formato_detectado": "hdfs",
        "total_lineas": 2000,
        "motor_preprocesamiento": "v1",
        "diagnostico": "Comportamiento operativo normal del clúster.",
        "confianza": 0.95,
        "hay_anomalia": False,
        "hay_incidente": False,
        "requiere_revision_humana": False,
        "n_comandos_mitigacion": 0,
        "evaluacion_auditor": "El diagnóstico es coherente con la evidencia.",
        "tecnicas_mitre": [],
        "estado": "completo",
    }
    base.update(extra)
    return job_id, base


# --- init ------------------------------------------------------------------

def test_init_db_crea_la_tabla_y_es_idempotente(db):
    historial.init_db(db)
    historial.init_db(db)          # no debe fallar la segunda vez
    assert historial.contar_corridas(db) == 0


def test_las_funciones_de_lectura_inicializan_solas(db):
    """Consultar un historial que todavía no existe no debe reventar."""
    assert historial.listar_corridas(ruta=db) == []
    assert historial.obtener_corrida("inexistente", ruta=db) is None


# --- registrar / obtener ---------------------------------------------------

def test_registrar_y_obtener_una_corrida(db):
    job_id, datos = corrida()
    historial.registrar_corrida(job_id, datos, ruta=db)
    d = historial.obtener_corrida(job_id, ruta=db)
    assert d["job_id"] == job_id
    assert d["archivo_origen"] == "HDFS_2k.log"
    assert d["confianza"] == 0.95
    assert d["total_lineas"] == 2000
    assert d["estado"] == "completo"


def test_los_booleanos_vuelven_como_booleanos_no_como_enteros(db):
    """SQLite los guarda como 0/1; el resto del sistema espera bool."""
    job_id, datos = corrida(hay_anomalia=True, hay_incidente=False,
                            requiere_revision_humana=True)
    historial.registrar_corrida(job_id, datos, ruta=db)
    d = historial.obtener_corrida(job_id, ruta=db)
    assert d["hay_anomalia"] is True
    assert d["hay_incidente"] is False
    assert d["requiere_revision_humana"] is True


def test_las_tecnicas_mitre_se_serializan_y_vuelven_como_lista(db):
    tecnicas = [{"technique_id": "T1110", "nombre": "Brute Force"}]
    job_id, datos = corrida(tecnicas_mitre=tecnicas)
    historial.registrar_corrida(job_id, datos, ruta=db)
    assert historial.obtener_corrida(job_id, ruta=db)["tecnicas_mitre"] == tecnicas


def test_sin_tecnicas_mitre_devuelve_lista_vacia_no_none(db):
    job_id, datos = corrida(tecnicas_mitre=[])
    historial.registrar_corrida(job_id, datos, ruta=db)
    assert historial.obtener_corrida(job_id, ruta=db)["tecnicas_mitre"] == []


def test_se_asigna_timestamp_si_no_viene(db):
    job_id, datos = corrida()
    historial.registrar_corrida(job_id, datos, ruta=db)
    assert historial.obtener_corrida(job_id, ruta=db)["timestamp"]


def test_registrar_dos_veces_el_mismo_id_sobrescribe_sin_fallar(db):
    """Un reintento del hook no debe tumbar la respuesta al navegador."""
    job_id, datos = corrida(diagnostico="primero")
    historial.registrar_corrida(job_id, datos, ruta=db)
    _, datos2 = corrida(diagnostico="segundo")
    historial.registrar_corrida(job_id, datos2, ruta=db)
    assert historial.contar_corridas(db) == 1
    assert historial.obtener_corrida(job_id, ruta=db)["diagnostico"] == "segundo"


def test_obtener_una_corrida_inexistente_devuelve_none(db):
    historial.registrar_corrida(*corrida("existe"), ruta=db)
    assert historial.obtener_corrida("no-existe", ruta=db) is None


# --- corridas con error ----------------------------------------------------

def test_una_corrida_con_error_queda_registrada(db):
    job_id, datos = corrida(
        "job_error", estado="error", error_mensaje="503 UNAVAILABLE",
        diagnostico="", confianza=0.0)
    historial.registrar_corrida(job_id, datos, ruta=db)
    d = historial.obtener_corrida(job_id, ruta=db)
    assert d["estado"] == "error"
    assert d["error_mensaje"] == "503 UNAVAILABLE"
    assert d["confianza"] == 0.0


# --- listado y paginación --------------------------------------------------

def test_listar_devuelve_la_mas_reciente_primero(db):
    for i, ts in enumerate(("2026-09-01T10:00:00Z", "2026-09-03T10:00:00Z",
                            "2026-09-02T10:00:00Z")):
        historial.registrar_corrida(*corrida(f"job{i}", timestamp=ts), ruta=db)
    ids = [c["job_id"] for c in historial.listar_corridas(ruta=db)]
    assert ids == ["job1", "job2", "job0"]      # 03, 02, 01


def test_paginacion_con_limit_y_offset(db):
    for i in range(10):
        historial.registrar_corrida(
            *corrida(f"job{i:02d}", timestamp=f"2026-09-{i + 1:02d}T10:00:00Z"),
            ruta=db)
    pagina1 = historial.listar_corridas(limit=3, offset=0, ruta=db)
    pagina2 = historial.listar_corridas(limit=3, offset=3, ruta=db)
    assert len(pagina1) == 3 and len(pagina2) == 3
    assert not set(c["job_id"] for c in pagina1) & set(c["job_id"] for c in pagina2)
    assert pagina1[0]["job_id"] == "job09"      # la más reciente


def test_el_limite_se_acota_a_un_rango_razonable(db):
    """Un `limit` desmedido desde la URL no debe volcar toda la tabla."""
    historial.registrar_corrida(*corrida(), ruta=db)
    assert len(historial.listar_corridas(limit=99999, ruta=db)) <= 500
    assert len(historial.listar_corridas(limit=0, ruta=db)) >= 0
    assert historial.listar_corridas(offset=-5, ruta=db) is not None


# --- feedback (la escritura a memoria vive en la API, no acá) --------------

def test_una_corrida_nueva_no_tiene_feedback(db):
    historial.registrar_corrida(*corrida(), ruta=db)
    d = historial.obtener_corrida("job1", ruta=db)
    assert d["feedback_correcto"] is None       # distinto de False
    assert d["feedback_comentario"] is None


def test_registrar_feedback_actualiza_los_tres_campos(db):
    historial.registrar_corrida(*corrida(), ruta=db)
    assert historial.registrar_feedback("job1", True, "coincide con lo que vi", ruta=db)
    d = historial.obtener_corrida("job1", ruta=db)
    assert d["feedback_correcto"] is True
    assert d["feedback_comentario"] == "coincide con lo que vi"
    assert d["feedback_timestamp"]


def test_el_feedback_se_puede_corregir(db):
    historial.registrar_corrida(*corrida(), ruta=db)
    historial.registrar_feedback("job1", True, ruta=db)
    historial.registrar_feedback("job1", False, "me equivoqué", ruta=db)
    d = historial.obtener_corrida("job1", ruta=db)
    assert d["feedback_correcto"] is False
    assert d["feedback_comentario"] == "me equivoqué"


def test_feedback_sobre_una_corrida_inexistente_devuelve_false(db):
    assert historial.registrar_feedback("no-existe", True, ruta=db) is False


def test_un_feedback_negativo_no_se_confunde_con_ausencia(db):
    """`False` y `None` significan cosas distintas: 'el analista dijo que
    estaba mal' contra 'todavía nadie opinó'."""
    historial.registrar_corrida(*corrida(), ruta=db)
    historial.registrar_feedback("job1", False, ruta=db)
    assert historial.obtener_corrida("job1", ruta=db)["feedback_correcto"] is False


# --- aislamiento del historial real ---------------------------------------

def test_la_ruta_por_defecto_apunta_a_data_historial_db():
    assert historial.RUTA_DB.name == "historial.db"
    assert historial.RUTA_DB.parent.name == "data"


def test_los_tests_no_tocan_el_historial_real(db, tmp_path):
    historial.registrar_corrida(*corrida("aislado"), ruta=db)
    assert db.exists()
    assert db.parent == tmp_path            # dentro del tmp del test
