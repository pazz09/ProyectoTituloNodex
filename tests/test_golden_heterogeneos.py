"""Golden tests heterogéneos y contrato de esquema v2 (Fase 4 del cierre
de auditoría, 23-sep-2026, último punto: "golden tests heterogéneos --
lote mixto, HDFS_2k y BGL_2k -- con la salida esperada versionada, y
contratos de esquema v2").

Un golden test compara la salida REAL de hoy contra una salida de
referencia capturada y versionada en git (`tests/golden/*.json`), no
contra un valor fijado a mano línea por línea: si el preprocesamiento
cambia de comportamiento -- a propósito o por accidente -- el test lo
marca, y corresponde revisar el diff y, si el cambio es intencional,
regenerar el archivo de referencia (ver `_regenerar()` al final de este
archivo, no se corre en la suite).

Por qué un subconjunto curado y no el dict completo de `agregar_v2()`:
los eventos crudos y las muestras no son deterministas de forma útil de
versionar (dependen de qué evento cae primero en cada decoder, no de
nada que uno quiera fijar como contrato), y HDFS_2k/BGL_2k tienen 2000
eventos cada uno -- versionar la lista completa haría un archivo enorme
y un diff ilegible ante cualquier cambio real. El subconjunto son las
distribuciones y agregados que SÍ son el contrato: lo que consumen
`_metadatos_desde_v2()`, el prompt del Triage y el reporte.
"""

import json
from pathlib import Path

import pytest

from src.preprocessing.aggregation import agregar_v2
from src.preprocessing.pipeline import preprocesar

_RAIZ = Path(__file__).resolve().parent
_GOLDEN_DIR = _RAIZ / "golden"
_DATA_DIR = _RAIZ.parent / "data" / "logs"

SYSLOG = "<38>Jan 10 13:55:36 srv sshd[1]: Failed password for root from 203.0.113.10 port 22 ssh2"
JSON_L = '{"@timestamp": "2024-01-02T10:00:00Z", "src_ip": "10.0.0.1", "msg": "conexion"}'
HDFS_L = ("081109 203615 148 INFO dfs.DataNode$PacketResponder: PacketResponder 1 "
         "for block blk_38865049064139660 terminating")
TEXTO = "esto no se parece a ningun formato conocido"
CEF = "CEF:0|Fortinet|FortiGate|7.0|100|Trafico denegado|8|src=10.0.0.7 dst=10.0.0.8"
KV = "date=2024-01-02 srcip=192.168.1.5 dstip=192.168.1.9 action=deny"

MIXTO = "\n".join([TEXTO, HDFS_L, JSON_L, SYSLOG, CEF, KV]) + "\n"


def _resumen_golden(v2: dict) -> dict:
    """El subconjunto curado que se versiona -- ver el docstring del
    módulo para por qué no es el dict completo."""
    return {
        "schema_version": v2["schema_version"],
        "total_lineas_fisicas": v2["total_lineas_fisicas"],
        "total_eventos": v2["total_eventos"],
        "decoder_distribution": v2["decoder_distribution"],
        "product_distribution": v2["product_distribution"],
        "vendor_distribution": v2["vendor_distribution"],
        "version_distribution": v2["version_distribution"],
        "protocol_distribution": v2["protocol_distribution"],
        "profile_distribution": v2["profile_distribution"],
        "severity_distribution": v2["severity_distribution"],
        "event_categories": v2["event_categories"],
        "event_outcomes": v2["event_outcomes"],
        "entities_conteo": {k: len(vv) for k, vv in v2["entities"].items()},
        "time_window": v2["time_window"],
        "coverage": v2["parsing"]["coverage"],
        "parsed_events": v2["parsing"]["parsed_events"],
        "fallback_events": v2["parsing"]["fallback_events"],
        "n_segments": len(v2["segments"]),
        "segment_decoders": sorted({s["decoder"] for s in v2["segments"]}),
    }


def _cargar_golden(nombre: str) -> dict:
    return json.loads((_GOLDEN_DIR / f"{nombre}_esperado.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("nombre,modo,chunk_size,raw", [
    ("mixto", "hybrid", 10, MIXTO),
], ids=["mixto"])
def test_golden_lote_mixto(nombre, modo, chunk_size, raw):
    v2 = agregar_v2(preprocesar(raw, modo=modo, chunk_size=chunk_size))
    assert _resumen_golden(v2) == _cargar_golden(nombre)


@pytest.mark.parametrize("nombre,archivo", [
    ("hdfs_2k", "HDFS_2k.log"),
    ("bgl_2k", "BGL_2k.log"),
])
def test_golden_dataset_real(nombre, archivo):
    raw = (_DATA_DIR / archivo).read_text(encoding="utf-8", errors="replace")
    v2 = agregar_v2(preprocesar(raw, modo="hybrid"))
    assert _resumen_golden(v2) == _cargar_golden(nombre)


# --- contrato de esquema v2 -------------------------------------------------
#
# A diferencia del golden test (que fija VALORES), esto fija la FORMA:
# qué claves tiene que tener `agregar_v2()` y de qué tipo, para cualquier
# entrada -- lo que evita que una clave se borre o cambie de tipo sin que
# ningún test lo note (los golden test de arriba solo cubren tres lotes
# puntuales).

_CONTRATO_V2 = {
    "schema_version": str,
    "total_lineas_fisicas": int,
    "total_eventos": int,
    "decoder_distribution": dict,
    "product_distribution": dict,
    "vendor_distribution": dict,
    "version_distribution": dict,
    "protocol_distribution": dict,
    "profile_distribution": dict,
    "severity_distribution": dict,
    "event_categories": dict,
    "event_outcomes": dict,
    "entities": dict,
    "time_window": dict,
    "parsing": dict,
    "segments": list,
    "warnings": list,
    "samples": dict,
}


@pytest.mark.parametrize("raw,modo", [
    (MIXTO, "hybrid"),
    (SYSLOG + "\n", "line"),
    ("", "line"),
], ids=["mixto", "un_solo_evento", "vacio"])
def test_contrato_de_esquema_v2(raw, modo):
    v2 = agregar_v2(preprocesar(raw, modo=modo))
    assert set(v2) == set(_CONTRATO_V2)
    for clave, tipo in _CONTRATO_V2.items():
        assert isinstance(v2[clave], tipo), f"{clave} debería ser {tipo}, es {type(v2[clave])}"


def test_contrato_de_segmento_incluye_decoder_inicial_y_confidence_inicial():
    """M3 agregó tres campos al contrato de `RecordSegment` -- confirma
    que todo segmento los trae (decoder_distribution al menos con el
    propio `decoder` como única clave, si no hubo empate ni reproceso)."""
    v2 = agregar_v2(preprocesar(MIXTO, modo="hybrid", chunk_size=10))
    for segmento in v2["segments"]:
        assert "decoder_inicial" in segmento
        assert "confidence_inicial" in segmento
        assert "decoder_distribution" in segmento
        assert segmento["decoder"] in segmento["decoder_distribution"]


def _regenerar() -> None:  # pragma: no cover -- utilidad manual, no se corre en la suite
    """Regenera los tres archivos de `tests/golden/`. Correr a mano
    (`python -c "from tests.test_golden_heterogeneos import _regenerar; _regenerar()"`)
    solo cuando un cambio de comportamiento intencional invalida los
    valores actuales -- y revisar el diff de git antes de comitear."""
    casos = {
        "mixto": _resumen_golden(agregar_v2(preprocesar(MIXTO, modo="hybrid", chunk_size=10))),
        "hdfs_2k": _resumen_golden(agregar_v2(preprocesar(
            (_DATA_DIR / "HDFS_2k.log").read_text(encoding="utf-8", errors="replace"),
            modo="hybrid"))),
        "bgl_2k": _resumen_golden(agregar_v2(preprocesar(
            (_DATA_DIR / "BGL_2k.log").read_text(encoding="utf-8", errors="replace"),
            modo="hybrid"))),
    }
    for nombre, datos in casos.items():
        (_GOLDEN_DIR / f"{nombre}_esperado.json").write_text(
            json.dumps(datos, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
