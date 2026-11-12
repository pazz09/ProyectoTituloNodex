"""Memoria por grupo de eventos de la Fase B.1 (B.1-2). Construcción offline, sin LLM.

    python -m src.experimentation.knowledge.memoria_grupos

Construye `experiments/knowledge/memoria_grupos_v1/` a partir de la partición de
DESARROLLO de UWF (nunca lee la de evaluación):

- malicioso: en cada caso malicioso, los grupos de evidencia que contienen eventos
  del incidente (`core_event_uids` de su ground truth de desarrollo), representados
  solo con las filas del incidente y etiquetados con sus tácticas y técnicas;
- benigno: en cada caso benigno, los grupos con señal del perfil del lote (los
  mismos que examinaría el cazador).

Cada grupo se representa por su comportamiento, sin IP
(`src.tools.memoria_grupos.representacion_grupo_red`), con las huellas de sus
registros fuente (exclusión por solapamiento) y su embedding normalizado
(`EMBEDDING_MODEL`, el mismo de la memoria de lotes). Las memorias no se
sobrescriben.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[3]
NOMBRE = "memoria_grupos_v1"


def _entradas_de_caso(case_id: str):
    from src.preprocessing.perfil_lote import analizar_lote
    from src.preprocessing.pipeline import preprocesar
    from src.tools.memoria_grupos import representacion_grupo_red
    from src.tools.memoria_historica import huella_evento
    carpeta = RAIZ / "experiments/cases/uwf/desarrollo"
    meta = json.loads((carpeta / f"{case_id}.json").read_text(encoding="utf-8"))
    assert meta["particion"] == "desarrollo"
    gt = json.loads((RAIZ / "experiments/ground_truth/uwf/desarrollo" / f"{case_id}.json").read_text(encoding="utf-8"))
    eventos = list(preprocesar((carpeta / meta["archivo_contenido"]).read_text(encoding="utf-8")).events)
    analisis = analizar_lote(_Resultado(eventos))
    flujos = {f["group_id"]: f for f in analisis["contenido_lote"].get("flujos_minoritarios") or []}
    por_grupo: dict[str, list] = {}
    for e, gid in zip(eventos, analisis["group_id_por_registro"]):
        por_grupo.setdefault(gid, []).append(e)
    nucleo = set(gt.get("core_event_uids") or [])
    refs = gt.get("referencias_mitre") or []
    tacticas = [t for r in refs if r.get("nivel") == "tactica" for t in str(r["id"]).split("|")]
    tecnicas = [r["id"] for r in refs if r.get("nivel") in ("tecnica", "subtecnica")]
    if nucleo:
        for gid, propios in por_grupo.items():
            incidente = [e for e in propios if str(e.attributes.get("uid") or "") in nucleo]
            if not incidente:
                continue
            f = flujos.get(gid) or {}
            yield {"id": f"{case_id}:{gid}", "case_id": case_id, "group_id": gid, "etiqueta": "malicioso",
                   "tacticas": tacticas, "tecnicas": tecnicas, "filas": len(incidente),
                   "representacion": representacion_grupo_red(incidente, f.get("motivos"), f.get("motivos_factuales")),
                   "huellas": sorted({huella_evento(e) for e in incidente})}
    else:
        for gid, f in flujos.items():
            propios = por_grupo.get(gid, [])
            yield {"id": f"{case_id}:{gid}", "case_id": case_id, "group_id": gid, "etiqueta": "benigno",
                   "tacticas": [], "tecnicas": [], "filas": len(propios),
                   "representacion": representacion_grupo_red(propios, f.get("motivos"), f.get("motivos_factuales")),
                   "huellas": sorted({huella_evento(e) for e in propios})}


class _Resultado:
    """Envoltorio mínimo con `events`, la interfaz que usa `analizar_lote`."""

    def __init__(self, eventos):
        self.events = eventos


def construir() -> dict:
    from chromadb.utils import embedding_functions
    from src.config import EMBEDDING_MODEL
    from src.tools.memoria_grupos import _normalizar
    destino = RAIZ / "experiments/knowledge" / NOMBRE
    if destino.exists() and any(destino.iterdir()):
        raise FileExistsError(f"{destino} ya existe: las memorias no se sobrescriben")
    casos = sorted(f.stem for f in (RAIZ / "experiments/cases/uwf/desarrollo").glob("*.json"))
    entradas = [e for c in casos for e in _entradas_de_caso(c)]
    ef = embedding_functions.SentenceTransformerEmbeddingFunction(model_name=EMBEDDING_MODEL)
    for entrada, vector in zip(entradas, ef([e["representacion"] for e in entradas])):
        entrada["embedding"] = [round(float(x), 7) for x in _normalizar(vector)]
    destino.mkdir(parents=True, exist_ok=True)
    memoria = {"nombre": NOMBRE, "creado_utc": datetime.now(timezone.utc).isoformat(),
               "modelo_embeddings": EMBEDDING_MODEL, "casos_fuente": casos, "entradas": entradas}
    texto = json.dumps(memoria, ensure_ascii=False)
    (destino / "memoria_grupos.json").write_text(texto, encoding="utf-8")
    manifiesto = {"nombre": NOMBRE, "creado_utc": memoria["creado_utc"], "modelo_embeddings": EMBEDDING_MODEL,
                  "descripcion": "Grupos etiquetados de la partición de desarrollo de UWF: grupos con eventos del "
                                 "incidente (malicioso) y grupos con señal de los casos benignos (benigno).",
                  "memoria_sha256": hashlib.sha256(texto.encode("utf-8")).hexdigest(),
                  "entradas": len(entradas), "por_etiqueta": dict(Counter(e["etiqueta"] for e in entradas)),
                  "por_tactica": dict(Counter(t for e in entradas for t in e["tacticas"])),
                  "grupos": [{k: v for k, v in e.items() if k not in ("embedding", "huellas")}
                             | {"n_huellas": len(e["huellas"])} for e in entradas]}
    (destino / "manifiesto.json").write_text(json.dumps(manifiesto, ensure_ascii=False, indent=2), encoding="utf-8")
    return {k: manifiesto[k] for k in ("nombre", "entradas", "por_etiqueta", "por_tactica", "memoria_sha256")}


if __name__ == "__main__":
    print(json.dumps(construir(), ensure_ascii=False))
