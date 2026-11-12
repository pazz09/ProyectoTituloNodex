"""Corpus de memoria histórica de la Fase B (B3 y B4). Construcción offline, sin LLM.

    python -m src.experimentation.knowledge.memoria_historica_v2 --todos

Construye dos memorias nuevas; la v1 (`rag_enriquecido_30_v1`), evidencia del
piloto, no se toca:

- `rag_enriquecido_30_v2` (B3): los MISMOS 30 casos históricos de la v1,
  re-indexados con la representación nueva (grupos con señal y composición).
- `rag_enriquecido_v2` (B4): TODOS los casos de la partición de desarrollo (BGL y
  UWF) más los históricos de la v1 que no comparten registros con ningún caso de
  desarrollo (duplicados eliminados por registros fuente).

Cada patrón lleva su etiqueta (normal / anomalo / malicioso), una descripción
breve y verificable de por qué tiene esa etiqueta, tomada de su ground truth de
DESARROLLO (las líneas con alerta en BGL; las conexiones del incidente y sus
tácticas en UWF), y las huellas de sus registros fuente para la exclusión por
solapamiento. Nunca se lee la partición de evaluación.

Cada memoria es una copia de `experiments/knowledge/chroma_v2` (las 697 técnicas
MITRE) con la colección `attack_patterns` agregada, y un manifiesto con cada
patrón, su representación y el hash de sus huellas.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[3]
V1 = RAIZ / "experiments/knowledge/rag_enriquecido_30_v1"
SEMILLA = RAIZ / "experiments/knowledge/chroma_v2"
BGL_FUENTE = RAIZ / "data/logs/BGL_2k.log"
SEVERIDADES_ALTAS = {"fatal", "error", "warning", "warn", "critical", "crit", "severe", "alert", "emerg", "failure"}


def _analizar(raw: str):
    from src.preprocessing.perfil_lote import analizar_lote
    from src.preprocessing.pipeline import preprocesar
    from src.tools.memoria_historica import huellas_registros, representacion_lote
    resultado = preprocesar(raw)
    analisis = analizar_lote(resultado)
    return (resultado.events, representacion_lote(analisis["perfil_lote"], analisis["grupos_evidencia"],
                                                  analisis["contenido_lote"]), huellas_registros(resultado.events))


def _top(conteo: Counter, n=4) -> str:
    return ", ".join(f"{k} {v}" for k, v in conteo.most_common(n))


def _evento_texto(e) -> str:
    from src.preprocessing.perfil_lote import plantilla_mensaje
    componente = e.service_name or e.attributes.get("bgl_subsistema") or "-"
    return f"[{e.severity or '-'} {componente}] {plantilla_mensaje(e.message)[:90]}"


def descripcion_texto(eventos, alerta_por_indice: list[bool]) -> tuple[str, str]:
    """(etiqueta, descripción) de un lote de texto con la marca de alerta de cada línea."""
    severidades = Counter(e.severity or "-" for e in eventos)
    alertas = Counter(_evento_texto(e) for e, a in zip(eventos, alerta_por_indice) if a)
    if alertas:
        return "anomalo", ("Anómalo según la organización (requiere intervención). Eventos que determinan la "
                           "alerta: " + "; ".join(f"{n} × {t}" for t, n in alertas.most_common(4))
                           + f". Composición: {len(eventos)} eventos, severidades {_top(severidades)}.")
    altas = Counter(_evento_texto(e) for e in eventos if (e.severity or "").lower() in SEVERIDADES_ALTAS)
    return "normal", ("Normal según la organización (no requiere intervención). "
                      + (f"Contiene eventos de severidad alta que no se consideraron alerta: "
                         + "; ".join(f"{n} × {t}" for t, n in altas.most_common(4)) + ". " if altas else "")
                      + f"Composición: {len(eventos)} eventos, severidades {_top(severidades)}.")


def descripcion_red(eventos, uids_incidente: set, tacticas: list[str], tecnicas: list[str]) -> tuple[str, str]:
    """(etiqueta, descripción) de un lote de red con las conexiones del incidente."""
    def clave(e):
        servicio = e.service_name if e.service_name and e.service_name != "-" else f"puerto {e.destination_port}"
        return f"{(e.protocol or '-').lower()} {servicio}"
    protocolos = Counter((e.protocol or "-").lower() for e in eventos)
    estados = Counter(e.event_outcome or "-" for e in eventos)
    incidente = [e for e in eventos if (e.attributes.get("uid") or "") in uids_incidente]
    fondo = [e for e in eventos if (e.attributes.get("uid") or "") not in uids_incidente]
    protocolos = Counter((e.protocol or "-").lower() for e in fondo)
    if incidente:
        destinos = Counter(clave(e) for e in incidente)
        estados_inc = Counter(e.event_outcome or "-" for e in incidente)
        puertos = len({e.destination_port for e in incidente})
        etiqueta = "malicioso"
        return etiqueta, (f"Malicioso ({', '.join(tacticas) or 'táctica no anotada'}"
                          + (f"; {', '.join(tecnicas)}" if tecnicas else "") + "). "
                          f"Actividad del incidente: {len(incidente)} conexiones ({_top(destinos)}), "
                          f"{puertos} puertos de destino distintos, estados {_top(estados_inc)}. "
                          f"Resto del lote: {len(eventos) - len(incidente)} conexiones de fondo "
                          f"(protocolos {_top(protocolos)}).")
    return "normal", (f"Benigno: sin actividad maliciosa. Tráfico de fondo de {len(eventos)} conexiones "
                      f"(protocolos {_top(protocolos)}, estados {_top(estados)}).")


# --- fuentes ----------------------------------------------------------------------

def _casos_desarrollo():
    """Todos los casos de DESARROLLO de BGL y UWF, con su etiqueta del ground truth de desarrollo."""
    lineas_bgl = BGL_FUENTE.read_text(encoding="utf-8", errors="replace").splitlines()
    for dataset in ("bgl", "uwf"):
        carpeta = RAIZ / "experiments/cases" / dataset / "desarrollo"
        for meta_path in sorted(carpeta.glob("*.json")):
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            assert meta["particion"] == "desarrollo"
            gt = json.loads((RAIZ / "experiments/ground_truth" / dataset / "desarrollo" / meta_path.name)
                            .read_text(encoding="utf-8"))
            raw = (carpeta / meta["archivo_contenido"]).read_text(encoding="utf-8")
            eventos, representacion, huellas = _analizar(raw)
            if dataset == "bgl":
                alertas = [lineas_bgl[p["linea_original"] - 1].split(None, 1)[0] != "-" for p in meta["procedencia"]]
                etiqueta, descripcion = descripcion_texto(eventos, alertas)
            else:
                refs = gt.get("referencias_mitre") or []
                etiqueta, descripcion = descripcion_red(
                    eventos, set(gt.get("core_event_uids") or []),
                    [r["id"] for r in refs if r.get("nivel") == "tactica"],
                    [r["id"] for r in refs if r.get("nivel") in ("tecnica", "subtecnica")])
            yield {"historical_case_id": meta["case_id"], "dataset": dataset, "origen": "caso_desarrollo",
                   "etiqueta": etiqueta, "descripcion": descripcion, "representacion": representacion,
                   "huellas": huellas, "etiqueta_referencia": gt["etiqueta_deteccion"]}


def _historicos_v1():
    """Los 30 históricos de `rag_enriquecido_30_v1` (todos de desarrollo), re-descritos."""
    for fila in csv.DictReader((V1 / "manifests/casos_seleccionados.csv").open(encoding="utf-8")):
        raw = (V1 / fila["corpus_path"]).read_text(encoding="utf-8")
        meta = json.loads((V1 / fila["corpus_path"]).with_suffix(".json").read_text(encoding="utf-8"))
        assert meta["partition"] == "desarrollo"
        eventos, representacion, huellas = _analizar(raw)
        if fila["dataset"] == "bgl":
            alertas = [r["original_label"] != "-" for r in meta["records"]]
            etiqueta, descripcion = descripcion_texto(eventos, alertas)
        else:
            maliciosos = {r["uid"] for r in meta["records"] if str(r.get("original_label")).lower() in ("true", "malicious")}
            if fila["classification"] == "anomalo" and not maliciosos:
                maliciosos = {r["uid"] for r in meta["records"]}
            refs = meta.get("mitre_references") or []
            etiqueta, descripcion = descripcion_red(
                eventos, maliciosos if fila["classification"] == "anomalo" else set(),
                [r.get("id") for r in refs if r.get("nivel") == "tactica"],
                [r.get("id") for r in refs if r.get("nivel") in ("tecnica", "subtecnica")])
        yield {"historical_case_id": fila["historical_case_id"], "dataset": fila["dataset"],
               "origen": f"rag_enriquecido_30_v1:{fila['original_id']}", "etiqueta": etiqueta,
               "descripcion": descripcion, "representacion": representacion, "huellas": huellas,
               "etiqueta_referencia": fila["classification"]}


# --- construcción ---------------------------------------------------------------------

def _escribir_memoria(nombre: str, patrones: list[dict], notas: dict) -> dict:
    import chromadb
    from chromadb.utils import embedding_functions
    from src.config import COL_PATTERNS, EMBEDDING_MODEL
    destino = RAIZ / "experiments/knowledge" / nombre
    if destino.exists():
        raise FileExistsError(f"{destino} ya existe: las memorias no se sobrescriben")
    snapshot = destino / "chroma_snapshot"
    shutil.copytree(SEMILLA, snapshot)
    cliente = chromadb.PersistentClient(path=str(snapshot))
    ef = embedding_functions.SentenceTransformerEmbeddingFunction(model_name=EMBEDDING_MODEL)
    coleccion = cliente.get_or_create_collection(COL_PATTERNS, embedding_function=ef, metadata={"hnsw:space": "cosine"})
    coleccion.add(ids=[f"{nombre}:{p['historical_case_id']}" for p in patrones],
                  documents=[p["representacion"] for p in patrones],
                  metadatas=[{"historical_case_id": p["historical_case_id"], "dataset": p["dataset"],
                              "etiqueta": p["etiqueta"], "descripcion": p["descripcion"], "origen": p["origen"],
                              "huellas": json.dumps(p["huellas"])} for p in patrones])
    total, tecnicas = coleccion.count(), cliente.get_collection("attack_techniques").count()
    del cliente
    manifiesto = {"nombre": nombre, "creado_utc": datetime.now(timezone.utc).isoformat(), **notas,
                  "patrones": len(patrones), "patrones_en_coleccion": total, "tecnicas_mitre": tecnicas,
                  "por_dataset_y_etiqueta": dict(Counter(f"{p['dataset']}/{p['etiqueta']}" for p in patrones)),
                  "casos": [{k: v for k, v in p.items() if k != "huellas"}
                            | {"n_huellas": len(p["huellas"]),
                               "huellas_sha256": hashlib.sha256(json.dumps(p["huellas"]).encode()).hexdigest()}
                            for p in patrones]}
    (destino / "manifiesto.json").write_text(json.dumps(manifiesto, ensure_ascii=False, indent=2), encoding="utf-8")
    return {k: manifiesto[k] for k in ("nombre", "patrones", "patrones_en_coleccion", "tecnicas_mitre",
                                       "por_dataset_y_etiqueta")}


def construir_30_v2() -> dict:
    patrones = list(_historicos_v1())
    return _escribir_memoria("rag_enriquecido_30_v2", patrones, {
        "descripcion": "Los mismos 30 históricos de rag_enriquecido_30_v1, re-indexados con la representación "
                       "de la Fase B (grupos con señal y composición) y descripciones del ground truth de desarrollo."})


def construir_v2() -> dict:
    desarrollo = list(_casos_desarrollo())
    huellas_desarrollo = set().union(*(set(p["huellas"]) for p in desarrollo))
    extra, duplicados = [], []
    for p in _historicos_v1():
        (duplicados if set(p["huellas"]) & huellas_desarrollo else extra).append(p)
    return _escribir_memoria("rag_enriquecido_v2", desarrollo + extra, {
        "descripcion": "Todos los casos de desarrollo (BGL y UWF) más los históricos de la v1 sin registros en "
                       "común con ellos.",
        "historicos_v1_descartados_por_duplicado": [p["historical_case_id"] for p in duplicados],
        "historicos_v1_agregados": [p["historical_case_id"] for p in extra]})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--todos", action="store_true")
    parser.add_argument("--solo", choices=("rag_enriquecido_30_v2", "rag_enriquecido_v2"))
    args = parser.parse_args()
    if args.todos or args.solo == "rag_enriquecido_30_v2":
        print(json.dumps(construir_30_v2(), ensure_ascii=False))
    if args.todos or args.solo == "rag_enriquecido_v2":
        print(json.dumps(construir_v2(), ensure_ascii=False))
