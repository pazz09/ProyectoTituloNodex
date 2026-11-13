"""Ejecutor y exportador de la evaluación final. Sin API: el modelo se simula."""

import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from tools import ejecutar_evaluacion_final as ef

RAIZ = Path(__file__).resolve().parents[1]


def test_el_plan_sigue_el_orden_del_preregistro():
    corridas = ef.plan()
    assert len(corridas) == 60 * 3 * 3 + 12
    bloques = []
    for c in corridas:
        clave = (c["etapa"], c["sistema"])
        if not bloques or bloques[-1][0] != clave:
            bloques.append([clave, 0])
        bloques[-1][1] += 1
    assert bloques == [[(f"r{r}", s), 60] for r in (1, 2, 3) for s in ("nodex", "agente_unico", "gemini_directo")] \
        + [[("piloto_no_confirmatorio", "nodex"), 12]]
    assert all(c["entrada"].startswith("experiments/cases_final/") for c in corridas if c["confirmatorio"])
    assert all(not c["confirmatorio"] and c["entrada"].startswith("experiments/cases/")
               for c in corridas if c["etapa"] == "piloto_no_confirmatorio")


@pytest.mark.parametrize("documento, energia, esperado", [
    ({"sistema": "nodex", "estado": {"_error_api": None}}, [], "completa"),
    ({"sistema": "nodex", "estado": {"_error_api": "ServerError: 503 UNAVAILABLE"}}, [], "falla_infraestructura"),
    ({"sistema": "nodex", "estado": {"_error_api": "402 RESOURCE_EXHAUSTED: prepayment credits are depleted"}}, [],
     "credito_agotado"),
    ({"sistema": "agente_unico", "estado": {"_error_api": "El agente único no produjo un resultado D1/D4 completo."}},
     [], "falla_sistema"),
    ({"sistema": "gemini_directo", "resultado": {"falla": "sistema", "detalle_falla": "json_invalido"}}, [],
     "falla_sistema"),
    ({"sistema": "gemini_directo", "resultado": {"falla": "infraestructura", "detalle_falla": "503"}}, [],
     "falla_infraestructura"),
    ({"sistema": "nodex", "estado": {"_error_api": None}}, [{"id": "42"}], "falla_infraestructura"),
    (None, [], "falla_sistema"),
])
def test_clasificacion_de_fallas(documento, energia, esperado):
    assert ef.clasificar(documento, 1, False, energia)[0] == esperado


def test_ejecucion_simulada_registra_hashes_y_se_exporta(tmp_path):
    from tools.exportar_evaluacion_final import exportar
    salida = tmp_path / "ev"
    r = subprocess.run([sys.executable, str(RAIZ / "tools/ejecutar_evaluacion_final.py"), "--simulado", "--salida",
                        str(salida), "--casos", "bgl_eva_natural_0008", "--repeticiones", "1", "--sin-piloto"],
                       cwd=RAIZ, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900)
    assert r.returncode == 0, r.stderr[-2000:]
    for sistema in ef.SISTEMAS:
        doc = json.loads((salida / "r1" / sistema / "bgl_eva_natural_0008.json").read_text(encoding="utf-8"))
        assert doc["ejecucion"]["estado"] == "completa" and doc["simulado"] is True
        assert doc["prompts"] and all(len(p["prompt_sha256"]) == 64 for p in doc["prompts"])
        assert doc["configuracion_efectiva"]["LLM_SIN_RESPALDO"] is True
        assert not [k for k in doc["configuracion_efectiva"] if "KEY" in k]
    gemini = json.loads((salida / "r1" / "gemini_directo" / "bgl_eva_natural_0008.json").read_text(encoding="utf-8"))
    assert gemini["prompts"][0]["prompt_v2_1_sha256"] == "2dd880789645f682d411094f2bfa224168bf416c68fa8f66c348e16e93dde660"
    nodex = json.loads((salida / "r1" / "nodex" / "bgl_eva_natural_0008.json").read_text(encoding="utf-8"))
    assert [p["nodo"] for p in nodex["prompts"]][-1] == "auditor"
    extraccion = exportar("r1", "gemini_directo", "20990101", salida, tmp_path / "x", referencias=False)
    assert extraccion["cases"] == 1 and extraccion["verificacion"]["ok"]
    with zipfile.ZipFile(extraccion["zip"]) as z:
        assert any(n.endswith("reports/raw_response.jsonl") for n in z.namelist())
    assert Path(extraccion["zip"]).with_suffix(".zip.sha256").read_text().split()[0] == extraccion["zip_sha256"]


def test_al_relanzar_omite_lo_terminado_y_repite_lo_interrumpido(tmp_path):
    salida = tmp_path / "ev"
    comando = [sys.executable, str(RAIZ / "tools/ejecutar_evaluacion_final.py"), "--simulado", "--salida", str(salida),
               "--casos", "bgl_eva_natural_0008", "--repeticiones", "1", "--sin-piloto"]
    assert subprocess.run(comando, cwd=RAIZ, capture_output=True, timeout=900).returncode == 0
    # Interrupción simulada: el resultado de Gemini directo quedó sin cierre del lanzador y el estado en curso.
    archivo = salida / "r1" / "gemini_directo" / "bgl_eva_natural_0008.json"
    doc = json.loads(archivo.read_text(encoding="utf-8"))
    doc.pop("ejecucion")
    archivo.write_text(json.dumps(doc), encoding="utf-8")
    estado = json.loads((salida / "estado.json").read_text(encoding="utf-8"))
    (salida / "estado.json").write_text(json.dumps(dict(estado, en_curso="r1/gemini_directo/bgl_eva_natural_0008")),
                                        encoding="utf-8")
    r = subprocess.run(comando, cwd=RAIZ, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900)
    assert r.returncode == 0, r.stderr[-2000:]
    bitacora = (salida / "bitacora_ejecucion.md").read_text(encoding="utf-8")
    assert "corrida interrumpida" in bitacora and "resultado sin cierre" in bitacora
    assert list((salida / "apartadas" / "r1" / "gemini_directo").glob("bgl_eva_natural_0008__intentointerrumpida_*.json"))
    assert json.loads(archivo.read_text(encoding="utf-8"))["ejecucion"]["estado"] == "completa"
    log = (salida / "ejecucion.log").read_text(encoding="utf-8")
    assert log.count("r1/nodex/bgl_eva_natural_0008: completa") == 1          # la terminada no se repitió
    final = json.loads((salida / "estado.json").read_text(encoding="utf-8"))
    assert final["en_curso"] is None and final["terminado"] is True and final["terminadas"] == 3
