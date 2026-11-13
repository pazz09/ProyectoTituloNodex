"""Extracción de la evaluación final (sin API, sin métricas de calidad).

    python tools/exportar_evaluacion_final.py --todo                    # 9 repeticiones x sistema + piloto
    python tools/exportar_evaluacion_final.py --etapa r1 --sistema nodex
    python tools/exportar_evaluacion_final.py --verificar extracted_data/final-60casos-nodex-r1-AAAAMMDD

Mismo formato que `extracted_data/enriquecido-12casos-r1-20261104/` (clase `Export` de
`tools/export_experimental_data.py`): `originals/` (copias byte a byte verificadas con SHA-256: configuración,
entradas, referencias, predicciones y ejecución), proyecciones JSONL literales con puntero al original por
escenario (`detection/`, `reconstruction/`, `mitre/`, `reports/`, `performance/`, `rag_usage/`), con tablas
`_items` por elemento, `manifest.json`/`manifest.csv`, `run_status.jsonl`, `extraction.json`, `verification.json`,
`README.md` y el notebook de revisión. Los eventos van con su `categoria` y cada veredicto con
`classification_detallada`. Para Gemini directo se exportan la respuesta cruda, el JSON extraído y la salida
normalizada.

Las referencias (ground truth) se abren solo aquí, después de la inferencia. Nombres de los ZIP:
`final-60casos-{nodex|agenteunico|geminidirecto}-rN-AAAAMMDD.zip` y `final-piloto12-nodex-AAAAMMDD.zip`, cada
uno con su `.sha256`.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.export_experimental_data import Export, make_notebook, pointer, read, sha, write_json  # noqa: E402

EVALUACION = ROOT / "experiments" / "evaluacion_final"
CASOS_FINAL = ROOT / "experiments" / "cases_final"
CONFIGURACION = [ROOT / "experiments/config/config_oficial-12casos-r1-20261028.json",
                 ROOT / "docs/experimentacion/preregistro_evaluacion_final.md",
                 CASOS_FINAL / "seleccion.json", CASOS_FINAL / "composicion.csv",
                 CASOS_FINAL / "verificacion_regeneracion.json", CASOS_FINAL / "preflight.json"]
PROMPT_GEMINI = ROOT / "experiments/config/prompt_gemini_directo_v2_1.txt"
NOMBRE_SISTEMA = {"nodex": "nodex", "agente_unico": "agenteunico", "gemini_directo": "geminidirecto"}
SECCIONES = ("diagnostico", "diagnostico_inicial", "evaluacion_auditor", "comandos_mitigacion", "comandos_validos",
             "comandos_rechazados", "motivos_rechazo", "cves_encontrados", "correcciones_auditor",
             "historial_correcciones", "veredicto_preliminar", "justificacion_veredicto_preliminar")


class ExportFinal(Export):
    """`Export` que admite resultados fuera del repositorio (p. ej. la prueba con el modelo simulado)."""

    def __init__(self, root, output, evaluacion: Path):
        super().__init__(root, output)
        self.evaluacion = Path(evaluacion).resolve()

    def copy(self, source, identity, category, required=True):
        source = Path(source)
        if not source.is_absolute():
            source = self.root / source
        source = source.resolve()
        try:
            relative = source.relative_to(self.root)
        except ValueError:
            relative = Path("evaluacion_externa") / source.relative_to(self.evaluacion.parent)
        target = self.output / "originals" / category / relative
        entry = dict(identity, source_path=relative.as_posix(), source_filename=source.name,
                     export_path=target.relative_to(self.output).as_posix(), available=source.is_file(),
                     required=required)
        self.manifest.append(entry)
        if not entry["available"]:
            return None, entry
        target.parent.mkdir(parents=True, exist_ok=True)
        before = sha(source)
        target.write_bytes(source.read_bytes())
        after, copied = sha(source), sha(target)
        if before != after or before != copied:
            raise ValueError(f"El original cambió o la copia difiere: {source}")
        entry.update(sha256_source=before, sha256_copy=copied, size_bytes=source.stat().st_size)
        return (read(target) if source.suffix == ".json" else None), entry


def nombre_extraccion(etapa: str, sistema: str, fecha: str) -> str:
    if etapa == "piloto_no_confirmatorio":
        return f"final-piloto12-nodex-{fecha}"
    return f"final-60casos-{NOMBRE_SISTEMA[sistema]}-{etapa}-{fecha}"


def _proyecciones_nodex(ex, doc, src, ident):
    e = "/estado/"
    ex.project("detection/verdicts.jsonl", doc, src, ident, [e + k for k in (
        "hay_anomalia", "hay_incidente", "confianza", "classification_detallada", "veredicto_preliminar",
        "veredicto_consolidado", "requiere_revision_humana", "_error_api")])
    ex.project("reconstruction/predictions.jsonl", doc, src, ident,
               [e + "eventos_reconstruidos", e + "secuencia_temporal"], items=True)
    ex.project("reconstruction/evidence.jsonl", doc, src, ident,
               [e + "evidencia_logs", e + "grupos_evidencia", e + "evaluacion_grupos"], items=True)
    ex.project("reconstruction/filter.jsonl", doc, src, ident,
               [e + "invalid_evidence_uid_count", e + "invalid_evidence_group_count", e + "d11_warnings"])
    ex.project("mitre/attributions.jsonl", doc, src, ident, [e + "tecnicas_atribuidas"], items=True)
    ex.project("mitre/retrieved_candidates.jsonl", doc, src, ident, [e + "tecnicas_mitre"], items=True)
    ex.project("mitre/query.jsonl", doc, src, ident, [e + "consulta_mitre", e + "rag_omitido"])
    ex.project("reports/sections.jsonl", doc, src, ident, [e + k for k in SECCIONES])
    ex.project("rag_usage/memory.jsonl", doc, src, ident,
               [e + "casos_historicos", e + "historico_consulta", e + "memoria_grupos", e + "memoria_grupos_consulta"])
    ex.project("performance/runs.jsonl", doc, src, ident, [e + "telemetry"])
    ex.project("performance/llm_calls.jsonl", doc, src, ident, [e + "telemetry/llm_calls"], items=True)
    ex.project("performance/plan.jsonl", doc, src, ident,
               [e + "plan", e + "historial_ejecucion", e + "replan_count", e + "intentos_correccion"])


def _proyecciones_gemini(ex, doc, src, ident, output):
    n = "/resultado/normalizado/"
    ex.project("detection/verdicts.jsonl", doc, src, ident, [n + k for k in (
        "hay_anomalia", "hay_incidente", "confianza", "classification_detallada")])
    ex.project("reconstruction/predictions.jsonl", doc, src, ident,
               [n + "eventos_reconstruidos", n + "secuencia_temporal"], items=True)
    ex.project("reconstruction/filter.jsonl", doc, src, ident, [n + "invalid_evidence_uid_count", n + "d11_warnings"])
    ex.project("mitre/attributions.jsonl", doc, src, ident, [n + "tecnicas_atribuidas"], items=True)
    ex.project("reports/sections.jsonl", doc, src, ident, [n + k for k in ("diagnostico", "evaluacion",
                                                                          "comandos_mitigacion")])
    ex.project("reports/raw_response.jsonl", doc, src, ident, ["/resultado/" + k for k in (
        "respuesta_cruda", "forma_respuesta", "json_extraido", "falla", "detalle_falla", "prompt_sha256",
        "solicitud_sha256", "solicitud_caracteres")])
    ex.project("performance/runs.jsonl", doc, src, ident, ["/resultado/telemetria"])
    ex.project("performance/llm_calls.jsonl", doc, src, ident, ["/resultado/telemetria/llm_calls"], items=True)
    presente, cruda = pointer(doc, "/resultado/respuesta_cruda") if doc else (False, None)
    if presente and isinstance(cruda, str):
        destino = output / "reports" / "raw" / f"{ident['run_id']}.txt"
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(cruda.encode("utf-8"))


def exportar(etapa: str, sistema: str, fecha: str, evaluacion: Path = EVALUACION,
             destino_raiz: Path = ROOT / "extracted_data", zip_: bool = True, referencias: bool = True) -> dict:
    """`referencias=False` solo para probar la extracción antes de la inferencia (no copia ground truth)."""
    evaluacion = Path(evaluacion).resolve()
    nombre = nombre_extraccion(etapa, sistema, fecha)
    output = Path(destino_raiz) / nombre
    if output.exists():
        raise FileExistsError(f"La exportación no se sobrescribe: {output}")
    output.mkdir(parents=True)
    ex = ExportFinal(ROOT, output, evaluacion)
    base = dict(config_version=nombre)
    for archivo in CONFIGURACION + ([PROMPT_GEMINI] if sistema == "gemini_directo" else []):
        ex.copy(archivo, base, "configuration")
    for archivo in sorted(evaluacion.glob("registro_*.json")) + sorted(evaluacion.glob(f"informe_operativo_{etapa}.json")):
        ex.copy(archivo, base, "execution")
    carpeta = evaluacion / etapa / sistema
    estados = []
    archivos = sorted(p for p in carpeta.glob("*.json"))
    for orden, archivo in enumerate(archivos, 1):
        doc_previo = read(archivo)
        case_id, ds = doc_previo["case_id"], doc_previo["dataset"]
        ident = dict(case_id=case_id, dataset=ds, particion="evaluacion", run_id=f"{case_id}__{sistema}__{etapa}",
                     arquitectura=sistema, repeticion=(doc_previo.get("ejecucion") or {}).get("repeticion"),
                     config_version=nombre, orden=orden)
        entrada = ROOT / doc_previo["entrada"]
        # La entrada no cambió desde la inferencia (mismo texto que leyó el proceso del caso).
        if hashlib.sha256(entrada.read_text(encoding="utf-8").encode("utf-8")).hexdigest() != doc_previo.get("entrada_sha256"):
            raise ValueError(f"La entrada de {case_id} cambió desde la inferencia")
        ex.copy(entrada, ident, "inputs")
        meta, meta_src = ex.copy(entrada.with_suffix(".json"), ident, "inputs")
        ex.project("cases.jsonl", meta, meta_src, ident, [""])
        ex.project("provenance.jsonl", meta, meta_src, ident, ["/procedencia"], items=True)
        # Referencias: se abren únicamente al extraer, después de la inferencia.
        if referencias:
            raiz_gt = (CASOS_FINAL / "ground_truth") if "cases_final" in doc_previo["entrada"] else (ROOT / "experiments/ground_truth")
            gt, gt_src = ex.copy(raiz_gt / ds / "evaluacion" / f"{case_id}.json", ident, "ground_truth")
            ex.project("detection/ground_truth.jsonl", gt, gt_src, ident, [""])
            ex.project("reconstruction/reference.jsonl", gt, gt_src, ident, ["/core_event_uids", "/estado_dimension", "/anotacion"])
            ex.project("mitre/ground_truth.jsonl", gt, gt_src, ident,
                       ["/referencias_mitre", "/estado_mitre_por_nivel", "/estado_dimension"], items=True)
        doc, src = ex.copy(archivo, ident, "predictions")
        ex.copy(archivo.with_suffix(".stderr.txt"), ident, "execution", required=False)
        ex.project("detection/predictions.jsonl", doc, src, ident, ["/ejecucion"])
        if sistema == "gemini_directo":
            _proyecciones_gemini(ex, doc, src, ident, output)
        else:
            _proyecciones_nodex(ex, doc, src, ident)
        ex.project("performance/prompts.jsonl", doc, src, ident, ["/prompts"], items=True)
        ex.project("performance/node_tokens.jsonl", doc, src, ident, ["/observaciones"], items=True)
        ex.project("performance/processes.jsonl", doc, src, ident,
                   ["/ejecucion", "/segundos_pared_hijo", "/usd", "/llamadas_llm", "/inicio_utc", "/fin_utc"])
        ex.project("performance/configuration.jsonl", doc, src, ident, ["/configuracion_efectiva"])
        ex.project("performance/consultas_externas.jsonl", doc, src, ident, ["/consultas_externas"], items=True)
        for apartada in sorted((evaluacion / "apartadas" / etapa / sistema).glob(f"{case_id}__intento*")):
            ex.copy(apartada, ident, "execution", required=False)
        ejecucion = (doc or {}).get("ejecucion") or {}
        estados.append(dict(ident, result_available=src["available"], estado=ejecucion.get("estado"),
                            motivo=ejecucion.get("motivo"), intento=ejecucion.get("intento")))
    ex.tables["run_status.jsonl"] = estados
    ex.finish()
    faltan = [r["source_path"] for r in ex.manifest if r["required"] and not r["available"]]
    esperados = 12 if etapa == "piloto_no_confirmatorio" else 60
    extraccion = dict(
        config_version=nombre, etapa=etapa, sistema=sistema, created_utc=datetime.now(timezone.utc).isoformat(),
        extractor_sha256=sha(Path(__file__)), arguments=sys.argv, cases=len(estados), cases_expected=esperados,
        completed=sum(r["estado"] == "completa" for r in estados),
        system_failures=sorted(r["case_id"] for r in estados if r["estado"] == "falla_sistema"),
        required_missing=faltan, no_confirmatorio=etapa == "piloto_no_confirmatorio", referencias_incluidas=referencias,
        rules=["Copias byte a byte verificadas con SHA-256.",
               "JSONL UTF-8: present=false significa campo ausente; value=null es null original.",
               "Listas vacías, cadenas vacías, orden y duplicados se conservan.",
               "source_json_pointer y array_index vinculan las proyecciones al archivo original.",
               "Sin matching, métricas, evaluadores ni conclusiones de desempeño."],
        limitations=["Las referencias se copian solo en la extracción, después de la inferencia.",
                      "Las corridas apartadas por infraestructura se conservan en originals/execution y no se proyectan.",
                      "El costo se calcula con la tarifa vigente (USD 0,75 / 3,75 por millón; razonamiento como salida)."])
    write_json(output / "extraction.json", extraccion)
    verificacion = verificar(output)
    (output / "README.md").write_text(
        f"# NODEX — {nombre}\n\n"
        + ("**No confirmatorio.** NODEX final sobre los 12 casos del piloto (1 repetición).\n\n"
           if etapa == "piloto_no_confirmatorio" else
           f"Evaluación final, {etapa.upper()}, sistema `{sistema}`, 60 casos de `experiments/cases_final/`.\n\n")
        + "Formato de `extracted_data/enriquecido-12casos-r1-20261104/`: `originals/` (copias verificadas con SHA-256), "
          "proyecciones JSONL literales por escenario con puntero al original (`detection/`, `reconstruction/`, "
          "`mitre/`, `reports/`, `performance/`, `rag_usage/`), tablas `_items` por elemento, `manifest.json`, "
          "`run_status.jsonl`, `extraction.json` y `verification.json`. Los eventos llevan `categoria` y cada veredicto "
          "`classification_detallada`."
        + (" Gemini directo: `reports/raw/` y `reports/raw_response.jsonl` conservan la respuesta cruda y el JSON "
           "extraído; las demás tablas, la salida normalizada (mismo filtro de evidencia que NODEX)."
           if sistema == "gemini_directo" else "")
        + "\n\nNo se calcularon métricas de calidad. Verificación: "
          f"`python tools/exportar_evaluacion_final.py --verificar <carpeta>`.\n", encoding="utf-8")
    make_notebook(output)
    cuaderno = output / "revision_datos_crudos.ipynb"
    cuaderno.write_text(cuaderno.read_text(encoding="utf-8").replace("oficial-12casos-r1-20261028", nombre)
                        .replace("12 casos solicitados", f"{esperados} casos").replace("uwf_eva_visible_0004",
                                                                                     estados[0]["case_id"] if estados else ""),
                        encoding="utf-8")
    resultado = dict(extraccion, verificacion=verificacion, carpeta=str(output))
    if zip_:
        resultado.update(empaquetar(output))
    return resultado


def verificar(output: Path) -> dict:
    """Vuelve a calcular el SHA-256 de cada copia contra el manifiesto."""
    manifiesto = read(output / "manifest.json")
    malas = [m["export_path"] for m in manifiesto if m["available"]
             and sha(output / m["export_path"]) != m["sha256_copy"]]
    estados = [json.loads(l) for l in (output / "run_status.jsonl").read_text(encoding="utf-8").splitlines() if l]
    resultado = {"copias_verificadas": sum(1 for m in manifiesto if m["available"]), "copias_con_hash_distinto": malas,
                 "casos": len(estados), "con_resultado": sum(1 for e in estados if e["result_available"]),
                 "ok": not malas}
    write_json(output / "verification.json", resultado)
    return resultado


def empaquetar(output: Path) -> dict:
    archivo = output.with_suffix(".zip")
    if archivo.exists():
        raise FileExistsError(f"El ZIP no se sobrescribe: {archivo}")
    with zipfile.ZipFile(archivo, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(output.rglob("*")):
            if p.is_file():
                z.write(p, Path(output.name) / p.relative_to(output))
    huella = sha(archivo)
    archivo.with_suffix(".zip.sha256").write_text(f"{huella}  {archivo.name}\n", encoding="utf-8")
    return {"zip": str(archivo), "zip_sha256": huella}


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--todo", action="store_true")
    p.add_argument("--etapa")
    p.add_argument("--sistema", choices=tuple(NOMBRE_SISTEMA))
    p.add_argument("--fecha", default=datetime.now().strftime("%Y%m%d"))
    p.add_argument("--evaluacion", type=Path, default=EVALUACION)
    p.add_argument("--destino", type=Path, default=ROOT / "extracted_data")
    p.add_argument("--verificar", type=Path)
    a = p.parse_args()
    if a.verificar:
        print(json.dumps(verificar(a.verificar), ensure_ascii=False, indent=1))
    elif a.todo:
        trabajos = [(f"r{r}", s) for r in (1, 2, 3) for s in NOMBRE_SISTEMA] + [("piloto_no_confirmatorio", "nodex")]
        for etapa, sistema in trabajos:
            if (a.evaluacion / etapa / sistema).is_dir():
                r = exportar(etapa, sistema, a.fecha, a.evaluacion, a.destino)
                print(json.dumps({k: r[k] for k in ("config_version", "cases", "completed", "system_failures",
                                                    "required_missing", "zip", "zip_sha256")}, ensure_ascii=False))
    elif a.etapa and a.sistema:
        r = exportar(a.etapa, a.sistema, a.fecha, a.evaluacion, a.destino)
        print(json.dumps({k: v for k, v in r.items() if k not in ("rules", "limitations")}, ensure_ascii=False, indent=1))
    else:
        p.print_help()
