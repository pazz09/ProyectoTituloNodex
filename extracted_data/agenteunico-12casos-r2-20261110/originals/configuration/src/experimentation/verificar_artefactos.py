"""Verificacion por ejecucion de los artefactos preparados.

Se corre con `python -m src.experimentation.verificar_artefactos` y conviene
repetirlo ANTES de congelar la configuracion de la campana final.

Solo lee y hashea. No usa el modelo, no ejecuta NODEX y NO abre el contenido
de `experiments/ground_truth/` (solo comprueba que cada referencia exista).
"""
import hashlib
import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
EXP = RAIZ / "experiments"
fallos: list[str] = []
verificados = 0


def sha(ruta: Path) -> str:
    h = hashlib.sha256()
    with ruta.open("rb") as f:
        for bloque in iter(lambda: f.read(1 << 20), b""):
            h.update(bloque)
    return h.hexdigest()


def comparar(etiqueta: str, esperado: str, ruta: Path) -> None:
    global verificados
    verificados += 1
    if not ruta.is_file():
        fallos.append(f"{etiqueta}: no existe {ruta}")
        return
    real = sha(ruta)
    if real != esperado:
        fallos.append(f"{etiqueta}: hash distinto (registrado {esperado[:12]}, real {real[:12]})")


print("=== 1) fuentes (inventario_fuentes.json) ===")
inv = json.loads((EXP / "manifests" / "inventario_fuentes.json").read_text(encoding="utf-8"))
n = 0
for clave, archivos in inv.items():
    for a in archivos:
        comparar(f"fuente {clave}", a["sha256"], RAIZ / a["ruta_relativa"])
        n += 1
print(f"  {n} archivos fuente comparados")

print("=== 2) conversion de UWF (uwf_conversion.json) ===")
conv = json.loads((EXP / "manifests" / "uwf_conversion.json").read_text(encoding="utf-8"))
n = 0
for s in conv["shards"]:
    comparar("parquet " + s["semana"], s["sha256_parquet"], RAIZ / s["archivo_parquet"])
    comparar("csv eventos " + s["semana"], s["sha256_eventos"],
             RAIZ / "data/experimentacion/uwf_csv/eventos" / f"{s['semana']}.csv")
    comparar("csv etiquetas " + s["semana"], s["sha256_etiquetas"],
             RAIZ / "data/experimentacion/uwf_csv/etiquetas" / f"{s['semana']}.csv")
    n += 3
print(f"  {n} archivos comparados ({len(conv['shards'])} shards)")

print("=== 3) base vectorial del experimento (poblado_chroma.json) ===")
pob = json.loads((EXP / "knowledge" / "poblado_chroma.json").read_text(encoding="utf-8"))
n = 0
for rel, meta in pob["snapshot"]["archivos"].items():
    comparar("chroma " + rel, meta["sha256"], EXP / "knowledge" / "chroma" / rel)
    n += 1
print(f"  {n} archivos de la base comparados")

print("=== 4) casos listados en los manifiestos vs archivos en disco ===")
n = 0
for ds in ("hdfs", "bgl", "uwf"):
    man = json.loads((EXP / "manifests" / f"{ds}.json").read_text(encoding="utf-8"))
    for particion, conds in man["condiciones"].items():
        for cond, det in conds.items():
            for cid in det["case_ids"]:
                n += 1
                base = EXP / "cases" / ds / particion
                gt = EXP / "ground_truth" / ds / particion / f"{cid}.json"
                contenido = list(base.glob(f"{cid}.log")) + list(base.glob(f"{cid}.csv"))
                if not (base / f"{cid}.json").is_file():
                    fallos.append(f"caso {cid}: falta su JSON")
                if not contenido:
                    fallos.append(f"caso {cid}: falta su archivo de contenido")
                if not gt.is_file():
                    fallos.append(f"caso {cid}: falta su referencia")
print(f"  {n} casos de los manifiestos comprobados")

print("=== 5) subconjuntos referencian casos existentes ===")
n = 0
for nombre in sorted(p.stem for p in (EXP / "subconjuntos").glob("*.json")):
    sub = json.loads((EXP / "subconjuntos" / f"{nombre}.json").read_text(encoding="utf-8"))
    part = sub["particion"]
    for ds, conds in sub["datasets"].items():
        for cond, det in conds.items():
            for cid in det["case_ids"]:
                n += 1
                if not (EXP / "cases" / ds / part / f"{cid}.json").is_file():
                    fallos.append(f"subconjunto {nombre}: caso inexistente {cid}")
                if not (EXP / "ground_truth" / ds / part / f"{cid}.json").is_file():
                    fallos.append(f"subconjunto {nombre}: referencia inexistente {cid}")
    print(f"  {nombre}: {sum(len(d['case_ids']) for c in sub['datasets'].values() for d in c.values())} casos")

print("=== 6) base vectorial del experimento: solo lectura, 697 documentos ===")
import shutil
import sqlite3
import tempfile

_sqlite = EXP / "knowledge" / "chroma" / "chroma.sqlite3"
_con = sqlite3.connect(f"file:{_sqlite}?mode=ro", uri=True)
try:
    _con.execute("CREATE TABLE x (a)")
    fallos.append("la base se pudo escribir en modo solo lectura")
except sqlite3.OperationalError:
    print("  escritura rechazada en modo solo lectura: correcto")
_colecciones = {
    nombre: _con.execute(
        "SELECT COUNT(*) FROM embeddings WHERE segment_id IN "
        "(SELECT id FROM segments WHERE collection=?)", (cid,)).fetchone()[0]
    for cid, nombre in _con.execute("SELECT id, name FROM collections").fetchall()
}
_con.close()
print(f"  colecciones: {_colecciones}")
if _colecciones != {"attack_techniques": 697}:
    fallos.append(f"la base experimental deberia tener solo attack_techniques=697: {_colecciones}")

try:
    import chromadb
except ImportError:
    print("  chromadb no instalado: se omite la apertura con la API")
else:
    # La API de Chroma puede ejecutar migraciones al abrir una base, asi que
    # se abre una COPIA y el original no se toca. `ignore_cleanup_errors`
    # porque en Windows el cliente mantiene abierto el archivo temporal.
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as _tmp:
        _copia = Path(_tmp) / "chroma"
        shutil.copytree(EXP / "knowledge" / "chroma", _copia)
        _col = chromadb.PersistentClient(path=str(_copia)).get_collection("attack_techniques")
        _n = _col.count()
        _tecnicas = [m.get("technique_id") for m in _col.get(include=["metadatas"])["metadatas"]]
        _padres = sum(1 for t in _tecnicas if "." not in str(t))
        print(f"  API de chromadb sobre una copia: {_n} documentos "
              f"({_padres} tecnicas padre + {_n - _padres} subtecnicas)")
        if (_n, _padres) != (697, 222):
            fallos.append(f"catalogo inesperado: total={_n} padres={_padres}")
    comparar("chroma tras abrir la copia", pob["snapshot"]["archivos"]["chroma.sqlite3"]["sha256"], _sqlite)

print("=== 7) base vectorial ACTIVA (v2): hashes y apertura con el codigo de NODEX ===")
# La seccion 6 solo comprobaba que los datos estuvieran (697 documentos) abriendo la
# base SIN funcion de embeddings. Eso no probaba que NODEX pudiera abrirla: la v1 se
# creo sin funcion y `src/memory.py` la rechaza. Esta seccion abre la v2 con
# `LongTermMemory`, el mismo codigo que usa NODEX, y hace consultas reales.
pob2 = json.loads((EXP / "knowledge" / "poblado_chroma_v2.json").read_text(encoding="utf-8"))
n = 0
for rel, meta in pob2["snapshot"]["archivos"].items():
    comparar("chroma_v2 " + rel, meta["sha256"], EXP / "knowledge" / "chroma_v2" / rel)
    n += 1
print(f"  {n} archivos de la base v2 comparados")
try:
    from src.experimentation.knowledge.verificar_base import abrir_con_memoria

    _abierta = abrir_con_memoria(RAIZ, EXP / "knowledge" / "chroma_v2")
    print(f"  abierta con LongTermMemory: {_abierta['n_attack_techniques']} documentos, "
          f"{len(_abierta['consultas'])} consultas respondidas")
    if _abierta["n_attack_techniques"] != 697:
        fallos.append(f"la base v2 deberia tener 697 documentos: {_abierta['n_attack_techniques']}")
    if not all(c["ids"] for c in _abierta["consultas"]):
        fallos.append("la base v2 no respondio alguna consulta de verificacion")
except Exception as _e:  # noqa: BLE001 - se informa como fallo, no se oculta
    fallos.append(f"NODEX no puede abrir la base v2: {type(_e).__name__}: {str(_e)[:300]}")
comparar("chroma_v2 tras abrir la copia",
         pob2["snapshot"]["archivos"]["chroma.sqlite3"]["sha256"],
         EXP / "knowledge" / "chroma_v2" / "chroma.sqlite3")

print(f"\nhashes verificados: {verificados} | FALLOS: {len(fallos)}")
for f in fallos[:20]:
    print("  -", f)
sys.exit(1 if fallos else 0)
