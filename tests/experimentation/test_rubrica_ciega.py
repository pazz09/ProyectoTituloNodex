"""Formulario ciego de la rúbrica humana (src/experimentation/rubrica_ciega.py).

**Todos los reportes de estas pruebas son ficticios** y viven en `tmp_path`: no se usa ninguna
salida de una campaña ni de un piloto.
"""

import ast
import csv
import inspect
import json
import re
from pathlib import Path

import pytest

from src.experimentation import consolidacion, rubrica_ciega as rc
from src.experimentation.evaluators.reporte import CRITERIOS

CASOS = [f"bgl_eva_x_{i:04d}" for i in range(6)] + [f"uwf_eva_x_{i:04d}" for i in range(6)]
ARQS = ("nodex_multiagente", "gemini_externo")
CONFIG = "ficticia-001"


def _reportes(textos=None):
    salida = []
    for i, caso in enumerate(CASOS):
        for arq in ARQS:
            texto = (textos or {}).get((caso, arq)) or (
                f"Se observa actividad anómala en el caso {i}: varios intentos fallidos y luego "
                f"un acceso exitoso. Recomendación: revisar la cuenta afectada ({arq[:3]}).")
            salida.append(rc.ReporteEntrada(caso, arq, f"run-{caso}-{arq}", texto,
                                            contexto=f"línea 1 del caso {caso}\nlínea 2"))
    return salida


def _paquete(semilla=20261015, reportes=None):
    return rc.preparar_paquete(reportes or _reportes(), semilla, CONFIG)


# --- 24 reportes y 48 evaluaciones -------------------------------------------------------------

def test_son_24_reportes_por_evaluador_y_48_evaluaciones_en_total():
    p = _paquete()
    assert p["clave"]["n_reportes"] == 24
    assert {e: len(x["items"]) for e, x in p["paquetes"].items()} == {"E1": 24, "E2": 24}
    assert len(p["clave"]["items"]) == 48


def test_cada_reporte_aparece_una_sola_vez_por_evaluador_con_su_caso_y_su_arquitectura():
    clave = _paquete()["clave"]
    for ev in ("E1", "E2"):
        pares = [(i["case_id"], i["arquitectura"]) for i in clave["items"] if i["evaluador"] == ev]
        assert len(pares) == len(set(pares)) == 24
        assert {a for _, a in pares} == set(ARQS)


def test_falta_el_reporte_de_una_arquitectura_y_el_paquete_no_se_arma():
    reportes = [r for r in _reportes() if not (r.case_id == CASOS[0] and r.arquitectura == ARQS[1])]
    with pytest.raises(ValueError, match="falta el reporte"):
        rc.preparar_paquete(reportes, 1, CONFIG)


def test_un_reporte_repetido_o_de_otra_arquitectura_se_rechaza():
    with pytest.raises(ValueError, match="repetido"):
        rc.preparar_paquete(_reportes() + [_reportes()[0]], 1, CONFIG)
    with pytest.raises(ValueError, match="inesperada"):
        rc.preparar_paquete(_reportes(), 1, CONFIG, arquitecturas=("nodex_multiagente",))


def test_son_exactamente_dos_evaluadores_distintos():
    with pytest.raises(ValueError):
        rc.preparar_paquete(_reportes(), 1, CONFIG, evaluadores=("E1", "E1"))
    with pytest.raises(ValueError):
        rc.preparar_paquete(_reportes(), 1, CONFIG, evaluadores=("E1", "E2", "E3"))


# --- orden aleatorio con semilla registrada --------------------------------------------------------

def _orden(p, ev):
    return [i["caso"] for i in p["paquetes"][ev]["items"]]


def test_el_orden_se_reproduce_con_la_misma_semilla_y_cambia_con_otra():
    assert _orden(_paquete(7), "E1") == _orden(_paquete(7), "E1")
    assert _orden(_paquete(7), "E1") != _orden(_paquete(8), "E1")


def test_cada_evaluador_tiene_su_propio_orden():
    p = _paquete()
    assert _orden(p, "E1") != _orden(p, "E2")
    assert sorted(_orden(p, "E1")) == sorted(_orden(p, "E2"))            # los mismos 24 reportes


def test_el_orden_no_depende_de_cual_es_cual_en_la_lista_de_entrada():
    """Si el orden dependiera del orden de entrada, la arquitectura se podría deducir."""
    a = _paquete(5, _reportes())
    b = _paquete(5, list(reversed(_reportes())))
    assert a["clave"]["items"] == b["clave"]["items"]


def test_la_semilla_queda_en_la_clave_y_en_el_paquete_solo_su_compromiso():
    p = _paquete(20261015)
    assert p["clave"]["semilla"] == 20261015
    for paquete in p["paquetes"].values():
        assert "20261015" not in json.dumps(paquete)
        assert "semilla" not in paquete
    assert re.fullmatch(r"[0-9a-f]{64}", p["clave"]["compromiso_semilla"])


def test_el_orden_se_mezcla_de_verdad_y_no_agrupa_las_arquitecturas():
    p = _paquete()
    clave = {(i["evaluador"], i["id"]): i["arquitectura"] for i in p["clave"]["items"]}
    secuencia = [clave[("E1", it["id"])] for it in p["paquetes"]["E1"]["items"]]
    assert len(set(secuencia[:6])) == 2 or len(set(secuencia[6:12])) == 2   # no son 12 y 12 seguidos


# --- ceguera ----------------------------------------------------------------------------------------------

def test_los_ids_son_la_posicion_y_no_delatan_caso_ni_arquitectura():
    for paquete in _paquete()["paquetes"].values():
        assert [i["id"] for i in paquete["items"]] == [f"R{n:02d}" for n in range(1, 25)]


def test_los_nombres_de_arquitectura_y_modelo_se_redactan():
    texto, n = rc.sanear("El sistema NODEX, con Gemini Flash y su agente auditor, concluye…")
    assert n >= 4 and rc.auditar_ceguera(texto) == []
    assert "NODEX" not in texto and "Gemini" not in texto and rc.REDACCION in texto


def test_la_auditoria_detecta_lo_que_la_limpieza_no_alcanzo():
    assert rc.auditar_ceguera("generado por nodex") == ["nodex"]
    assert rc.auditar_ceguera("texto limpio", extra=("run-123",)) == []
    assert rc.auditar_ceguera("viene de run-123", extra=("run-123",)) == ["run-123"]


def test_un_reporte_que_menciona_su_arquitectura_se_redacta_y_el_paquete_sale_limpio():
    reportes = _reportes({(CASOS[0], ARQS[0]): "Informe del sistema NODEX multiagente: hay anomalía."})
    p = rc.preparar_paquete(reportes, 3, CONFIG)
    textos = " ".join(i["texto"] for x in p["paquetes"].values() for i in x["items"])
    assert rc.auditar_ceguera(textos) == []


def test_un_identificador_de_corrida_dentro_del_texto_impide_armar_el_paquete():
    """Si el texto cita el id de la corrida (que sí identifica la arquitectura en la clave), el
    paquete no se arma. Aquí el id no contiene nombres de arquitectura que la limpieza redactaría."""
    reportes = _reportes()
    reportes[0] = rc.ReporteEntrada(reportes[0].case_id, reportes[0].arquitectura, "id-ZZ9",
                                    "Véase la corrida id-ZZ9 para más detalle.")
    with pytest.raises(ValueError, match="no sería ciego"):
        rc.preparar_paquete(reportes, 3, CONFIG)


def test_el_reporte_se_arma_con_la_misma_plantilla_para_cualquier_arquitectura():
    a = rc.texto_del_reporte({"report": {"summary": "Resumen A"}})
    b = rc.texto_del_reporte({"report": {"summary": "Resumen A"}, "mitre": {}, "otro": 1})
    assert a == b == "Resumen A"
    assert rc.texto_del_reporte({}) == rc.texto_del_reporte({"report": {"summary": "  "}}) == "No entregado"


# --- el formulario HTML ------------------------------------------------------------------------------------

@pytest.fixture
def escrito(tmp_path):
    destino = tmp_path / "rubrica"
    rc.escribir_paquete(_reportes(), 20261015, CONFIG, destino)
    return destino


def test_se_escriben_un_formulario_por_evaluador_y_la_clave(escrito):
    assert {p.name for p in escrito.iterdir()} == {
        "formulario_E1.html", "formulario_E2.html", "clave_secreta.json"}


def test_el_formulario_no_contiene_arquitectura_modelo_corrida_clave_ni_semilla(escrito):
    clave = json.loads((escrito / "clave_secreta.json").read_text(encoding="utf-8"))
    for ev in ("E1", "E2"):
        pagina = (escrito / f"formulario_{ev}.html").read_text(encoding="utf-8")
        assert rc.auditar_ceguera(pagina, extra=(*ARQS, "run-", clave["hash_de_la_clave"],
                                                 str(clave["semilla"]))) == []


def test_el_formulario_de_un_evaluador_no_trae_nada_del_otro(escrito):
    p1 = (escrito / "formulario_E1.html").read_text(encoding="utf-8")
    p2 = (escrito / "formulario_E2.html").read_text(encoding="utf-8")
    assert "Evaluador: E1" in p1 and "Evaluador: E2" not in p1
    assert "Evaluador: E2" in p2 and "Evaluador: E1" not in p2
    orden1 = re.findall(r'<small>\((\w+)\)</small>', p1)
    orden2 = re.findall(r'<small>\((\w+)\)</small>', p2)
    assert orden1 != orden2 and sorted(orden1) == sorted(orden2)


def test_el_formulario_tiene_5_criterios_por_reporte_con_la_escala_0_a_3_y_sus_descriptores(escrito):
    pagina = (escrito / "formulario_E1.html").read_text(encoding="utf-8")
    assert pagina.count('type="radio"') == 24 * 5 * 4
    for criterio in CRITERIOS:
        for nivel in range(4):
            assert f'name="R01|{criterio}" value="{nivel}"' in pagina
    for criterio in CRITERIOS:
        for descriptor in rc.DESCRIPTORES[criterio]:
            assert descriptor in pagina
    assert "3 = no hay información" in pagina          # el criterio que se puntúa al revés
    assert "no se indica qué sistema los produjo" in pagina


def test_los_descriptores_cubren_los_cinco_criterios_con_cuatro_niveles():
    assert set(rc.DESCRIPTORES) == set(CRITERIOS) == set(rc.ETIQUETAS)
    assert all(len(v) == 4 for v in rc.DESCRIPTORES.values())


def test_el_texto_del_reporte_se_escapa_en_el_html(tmp_path):
    reportes = _reportes({(CASOS[0], ARQS[0]): '<script>alert("x")</script> & más'})
    rc.escribir_paquete(reportes, 1, CONFIG, tmp_path / "r")
    pagina = (tmp_path / "r" / "formulario_E1.html").read_text(encoding="utf-8")
    assert "<script>alert" not in pagina and "&lt;script&gt;" in pagina


def test_no_se_sobrescribe_un_paquete_existente(escrito):
    with pytest.raises(FileExistsError):
        rc.escribir_paquete(_reportes(), 1, CONFIG, escrito)


# --- importación, desciegue y concordancia ----------------------------------------------------------------------

def _respuestas(clave, evaluador, f):
    """`f(case_id, arquitectura) -> {criterio: puntaje}` -> archivo exportado por un evaluador."""
    items = [{"id": i["id"], "puntajes": f(i["case_id"], i["arquitectura"])}
             for i in clave["items"] if i["evaluador"] == evaluador]
    return {"paquete_id": clave["paquete_id"], "evaluador": evaluador, "items": items}


def _todos(n):
    return {c: n for c in CRITERIOS}


def test_dos_evaluadores_identicos_dan_acuerdo_exacto_total():
    clave = _paquete()["clave"]
    r = rc.importar_puntajes(clave, [_respuestas(clave, "E1", lambda c, a: _todos(2)),
                                     _respuestas(clave, "E2", lambda c, a: _todos(2))])
    conc = r["resultado"]["concordancia"]
    assert conc["acuerdo_exacto"] == 1.0 and conc["acuerdo_hasta_un_nivel"] == 1.0
    assert conc["diferencia_absoluta_media"] == 0.0
    assert conc["reportes_con_dos_evaluadores"] == 24 and conc["n_comparaciones"] == 24 * 5


def test_la_concordancia_se_calcula_a_mano():
    """E2 puntúa 1 más que E1 en 2 criterios de cada reporte, y 2 más en 1 criterio."""
    clave = _paquete()["clave"]

    def e1(c, a):
        return _todos(1)

    def e2(c, a):
        return {CRITERIOS[0]: 2, CRITERIOS[1]: 2, CRITERIOS[2]: 3, CRITERIOS[3]: 1, CRITERIOS[4]: 1}

    conc = rc.importar_puntajes(clave, [_respuestas(clave, "E1", e1),
                                        _respuestas(clave, "E2", e2)])["resultado"]["concordancia"]
    assert conc["acuerdo_exacto"] == pytest.approx(2 / 5)           # 2 de 5 criterios iguales
    assert conc["acuerdo_hasta_un_nivel"] == pytest.approx(4 / 5)   # solo el criterio con diferencia 2 no
    assert conc["diferencia_absoluta_media"] == pytest.approx((1 + 1 + 2 + 0 + 0) / 5)
    assert conc["n_desacuerdos_relevantes"] == 24                   # la diferencia de 2, una por reporte


def test_no_se_calcula_ningun_kappa():
    clave = _paquete()["clave"]
    r = rc.importar_puntajes(clave, [_respuestas(clave, e, lambda c, a: _todos(3)) for e in ("E1", "E2")])
    assert r["resultado"]["kappa"] is None and "pendiente" in r["resultado"]["nota_kappa"]
    assert "kappa" not in {k for k in r["resultado"]["concordancia"]}


def test_el_desciegue_asocia_cada_puntaje_con_la_arquitectura_correcta():
    clave = _paquete()["clave"]
    alto = lambda c, a: _todos(3 if a == "nodex_multiagente" else 1)
    r = rc.importar_puntajes(clave, [_respuestas(clave, e, alto) for e in ("E1", "E2")])
    por = {}
    for p in r["puntuaciones"]:
        por.setdefault(p.arquitectura, set()).update(p.puntajes.values())
    assert por == {"nodex_multiagente": {3}, "gemini_externo": {1}}


@pytest.mark.parametrize("estropear, mensaje", [
    (lambda r: r["items"].pop(), "faltan"),
    (lambda r: r["items"].append(dict(r["items"][0])), "repetido"),
    (lambda r: r["items"][0]["puntajes"].update({CRITERIOS[0]: 4}), "no es un entero"),
    (lambda r: r["items"][0]["puntajes"].update({CRITERIOS[0]: -1}), "no es un entero"),
    (lambda r: r["items"][0]["puntajes"].update({CRITERIOS[0]: True}), "no es un entero"),
    (lambda r: r["items"][0]["puntajes"].update({CRITERIOS[0]: 2.0}), "no es un entero"),
    (lambda r: r["items"][0]["puntajes"].pop(CRITERIOS[0]), "criterios incompletos"),
    (lambda r: r["items"][0].update({"id": "R99"}), "desconocido"),
    (lambda r: r.update({"paquete_id": "otro"}), "otro paquete"),
    (lambda r: r.update({"evaluador": "E9"}), "evaluador desconocido"),
])
def test_un_archivo_defectuoso_se_rechaza(estropear, mensaje):
    clave = _paquete()["clave"]
    r = _respuestas(clave, "E1", lambda c, a: _todos(2))
    estropear(r)
    with pytest.raises(ValueError, match=mensaje):
        rc.leer_respuestas(clave, r)


def test_dos_archivos_del_mismo_evaluador_no_son_dos_opiniones():
    clave = _paquete()["clave"]
    e1 = _respuestas(clave, "E1", lambda c, a: _todos(2))
    with pytest.raises(ValueError, match="un archivo de cada evaluador"):
        rc.importar_puntajes(clave, [e1, dict(e1)])
    with pytest.raises(ValueError, match="un archivo de cada evaluador"):
        rc.importar_puntajes(clave, [e1])


def test_un_evaluador_no_puede_importar_los_ids_del_otro():
    """Los ids son posiciones distintas para cada evaluador: mezclarlos desciega mal."""
    clave = _paquete()["clave"]
    r = _respuestas(clave, "E1", lambda c, a: _todos(2))
    ajeno = _respuestas(clave, "E2", lambda c, a: _todos(2))
    mezclado = {**r, "items": ajeno["items"]}              # los puntajes de E2 firmados como E1
    leidos = rc.leer_respuestas(clave, mezclado)           # ids válidos (R01..R24): pasan...
    esperados = {(i["case_id"], i["arquitectura"]) for i in clave["items"] if i["evaluador"] == "E1"}
    assert {(p.case_id, p.arquitectura) for p in leidos} == esperados   # ...pero se desciegan con la clave de E1


# --- salida compatible con el consolidador ------------------------------------------------------------------------

def test_los_puntajes_escritos_los_lee_el_consolidador_tal_cual(tmp_path):
    clave = _paquete()["clave"]
    importado = rc.importar_puntajes(clave, [
        _respuestas(clave, "E1", lambda c, a: _todos(2)),
        _respuestas(clave, "E2", lambda c, a: _todos(3))])
    rc.escribir_resultados(importado, CONFIG, tmp_path)
    puntuaciones, invalidas = consolidacion.leer_rubrica(tmp_path, CONFIG)
    assert invalidas == [] and len(puntuaciones) == 48
    assert {p.evaluador for p in puntuaciones} == {"E1", "E2"}
    assert {p.arquitectura for p in puntuaciones} == set(ARQS)


def test_se_escribe_la_concordancia_y_no_se_sobrescriben_los_puntajes(tmp_path):
    clave = _paquete()["clave"]
    importado = rc.importar_puntajes(clave, [_respuestas(clave, e, lambda c, a: _todos(2))
                                             for e in ("E1", "E2")])
    rutas = rc.escribir_resultados(importado, CONFIG, tmp_path, etiqueta="ficticio")
    datos = json.loads(Path(rutas["concordancia"]).read_text(encoding="utf-8"))
    assert datos["concordancia"]["acuerdo_exacto"] == 1.0 and datos["etiqueta"] == "ficticio"
    with Path(rutas["puntajes"]).open(encoding="utf-8", newline="") as f:
        assert next(csv.reader(f))[:4] == ["case_id", "arquitectura", "repeticion", "evaluador"]
    with pytest.raises(FileExistsError):
        rc.escribir_resultados(importado, CONFIG, tmp_path)


def test_el_modulo_no_lee_ground_truth_ni_salidas_de_ninguna_campana():
    arbol = ast.parse(inspect.getsource(rc))
    documentos = set()
    for nodo in ast.walk(arbol):
        if isinstance(nodo, (ast.Module, ast.FunctionDef, ast.ClassDef)):
            primero = nodo.body[0] if nodo.body else None
            if isinstance(primero, ast.Expr) and isinstance(primero.value, ast.Constant):
                documentos.add(id(primero.value))
    cadenas = [n.value for n in ast.walk(arbol) if isinstance(n, ast.Constant)
               and isinstance(n.value, str) and id(n) not in documentos]
    assert not any("ground_truth" in c for c in cadenas)
    assert not any(c in ("experiments/nodex", "experiments/outputs", "experiments/gemini_externo")
                   for c in cadenas)
    importados = {n.module for n in ast.walk(arbol) if isinstance(n, ast.ImportFrom)}
    assert not any(m and m.startswith("src.experimentation.runners") for m in importados)


# --- diseño: los cuatro niveles tienen que verse sin desplazarse ----------------------------------

def test_la_tabla_de_criterios_reparte_el_ancho_en_columnas_fijas(escrito):
    """Defecto visto en Chrome real: con `white-space: nowrap` los descriptores ensanchaban la
    tabla y la columna del nivel 3 quedaba fuera de pantalla: el evaluador no veía su opción."""
    pagina = (escrito / "formulario_E1.html").read_text(encoding="utf-8")
    estilo = pagina[pagina.index("<style>"):pagina.index("</style>")]
    assert "table-layout:fixed" in estilo
    assert "nowrap" not in estilo
    assert re.search(r"td\.n\{width:20%\}", estilo) and re.search(r"th\{width:19%\}", estilo)
    assert "@media (max-width:760px)" in estilo          # también en pantallas angostas
    # 19 % + 4 × 20 % = 99 %: las cinco columnas caben en el 100 % del contenedor
    assert 19 + 4 * 20 <= 100
