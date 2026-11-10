"""Extrae y verifica una repetición del agente único con el esquema de `oficial-12casos-r1-20261028`.

    python tools/export_single_agent_campaign.py --config-version agenteunico-12casos-r1-20261110

Reutiliza SIN MODIFICAR `tools/export_experimental_data.py` (proyecciones, ausentes, null, orden,
duplicados y sufijos `_items` idénticos a R1) y `tools/verify_official_repetition.py`. Ambos tienen
fijados en el código la carpeta `experiments/nodex` y el patrón de nombre de las carpetas oficiales;
aquí se adaptan en tiempo de ejecución con `unittest.mock.patch`:

- las copias de `experiments/nodex/...` se leen de `experiments/single_agent/...` (misma estructura);
- el verificador acepta `agenteunico-12casos-rN-AAAAMMDD` y valida el número de repetición real.

No ejecuta NODEX ni el agente único y no calcula métricas. Las referencias se copian solo aquí,
después de la inferencia. Nunca escribe en las extracciones existentes.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import sys
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from tools import export_experimental_data as extractor  # noqa: E402
from tools import verify_official_repetition as verificador  # noqa: E402
from tools import run_single_agent_campaign as campana  # noqa: E402

PATRON = r"agenteunico-12casos-r([123])-\d{8}"
DOC_PATRON = "agente_unico_12casos_*.md"


def _mapear(fuente, root):
    """`experiments/nodex/<ds>/...` -> `experiments/single_agent/<ds>/...` (solo predicciones)."""
    ruta = Path(fuente)
    relativa = ruta.relative_to(root) if ruta.is_absolute() else ruta
    if relativa.parts[:2] == ("experiments", "nodex"):
        return Path("experiments", "single_agent", *relativa.parts[2:])
    return fuente


def _rechazar_constante(valor):
    raise ValueError(f"constante JSON no válida: {valor}")


def jsonl_estrictos(carpeta):
    """Todas las filas JSONL se leen sin NaN/Infinity. Devuelve (archivos, filas)."""
    archivos = filas = 0
    for ruta in sorted(Path(carpeta).rglob("*.jsonl")):
        archivos += 1
        for linea in ruta.read_text(encoding="utf-8").splitlines():
            json.loads(linea, parse_constant=_rechazar_constante)
            filas += 1
    return archivos, filas


def comprobar_zip(carpeta, archivo):
    with zipfile.ZipFile(archivo) as z:
        if z.testzip() is not None:
            raise ValueError("ZIP inválido")
        nombres = sorted(n for n in z.namelist() if not n.endswith("/"))
        locales = sorted(p.relative_to(carpeta).as_posix() for p in Path(carpeta).rglob("*") if p.is_file())
        if nombres != locales:
            raise ValueError("El ZIP no contiene exactamente los archivos de la carpeta")
        for nombre in nombres:
            if z.read(nombre) != (Path(carpeta) / nombre).read_bytes():
                raise ValueError(f"Archivo distinto dentro del ZIP: {nombre}")
    return len(nombres)


def export(version, root=ROOT, salida=None):
    coincide = re.fullmatch(PATRON, version)
    if not coincide:
        raise ValueError("Solo se admiten identificadores agenteunico-12casos-rN-AAAAMMDD")
    repeticion = int(coincide.group(1))
    root = Path(root).resolve()
    carpeta = Path(salida or root / "extracted_data" / version).resolve()
    if carpeta.exists() or carpeta.with_suffix(".zip").exists():
        raise FileExistsError(f"La extracción no se sobrescribe: {carpeta}")
    logs = root / "experiments/ejecucion" / version
    seleccion = extractor.read(logs / "selection.json")
    terminados = len(list(logs.glob("*.result.json")))
    if terminados != 12:
        raise ValueError(f"La repetición no terminó: {terminados} de 12 resultados")

    copiar_original = extractor.Export.copy

    def copiar(self, source, identity, category, required=True):
        return copiar_original(self, _mapear(source, self.root), identity, category, required)

    with patch.object(extractor.Export, "copy", copiar):
        extractor.export(root, version, carpeta)

        # Evidencia propia de la campaña, sin tocar las proyecciones de R1.
        ex = extractor.Export(root, carpeta)
        ex.manifest = extractor.read(carpeta / "manifest.json")
        identidad = dict(config_version=version, repeticion=repeticion)
        for nombre in ("rag_initial.json", "compatibility.json"):
            ex.copy(logs / nombre, identidad, "configuration")
        coord = campana.COORD
        for ruta in sorted(coord.rglob("*")):
            if ruta.is_file():
                ex.copy(ruta, identidad, "configuration")
        for ruta in sorted(campana.SEED.rglob("*")):
            if ruta.is_file():
                ex.copy(ruta, identidad, "knowledge")
        for nombre in ("poblado_chroma_v2.json", "inventario_conocimiento_v2.json", "verificacion_chroma_v2.json"):
            ex.copy(root / "experiments/knowledge" / nombre, identidad, "knowledge")
        ex.copy(root / "experiments/config/precios_modelo.json", identidad, "configuration")
        estados_salida = {}
        for caso in seleccion["casos"]:
            ident = {k: caso[k] for k in ("case_id", "dataset", "particion", "run_id", "arquitectura",
                                          "repeticion", "config_version", "orden")}
            run = caso["run_id"]
            for final in ("isolation.json", "worker.json", "llm_input.json"):
                ex.copy(logs / f"{run}.{final}", ident, "execution")
            obs, fuente = ex.copy(logs / f"{run}.mitre_retrieval.json", ident, "execution")
            ex.project("mitre/retrieval_observation.jsonl", obs, fuente, ident,
                       ["/consulta", "/consulta_sha256", "/consulta_interna_igual", "/n_candidatos",
                        "/llegada_al_prompt", "/segundos_recuperacion_mitre", "/segundos_carga_memoria"])
            ex.project("mitre/retrieval_observation.jsonl", obs, fuente, ident, ["/candidatos"], items=True)
            ex.project("performance/single_agent_observation.jsonl", obs, fuente, ident,
                       ["/llm_json", "/solicitudes_llm_json", "/prompt_chars", "/prompt_sha256"])
            prediccion = extractor.read(root / "experiments/single_agent" / caso["dataset"] / f"{run}.json")
            estados_salida[run] = prediccion.get("ejecucion") or {}
        ex.finish()

    # run_status: misma fila de R1 + resultado incompleto declarado (regla de NODEX aplicada).
    filas = [json.loads(l) for l in (carpeta / "run_status.jsonl").read_text(encoding="utf-8").splitlines()]
    with (carpeta / "run_status.jsonl").open("w", encoding="utf-8", newline="\n") as f:
        for fila in filas:
            ejec = estados_salida.get(fila["run_id"], {})
            fila.update(estado_ejecucion_salida=ejec.get("estado"),
                        resultado_incompleto=ejec.get("resultado_incompleto"),
                        regla_completa="NODEX: completa si trae un veredicto booleano y no hubo excepción")
            f.write(json.dumps(fila, ensure_ascii=False) + "\n")
    incompletos = [dict(case_id=f["case_id"], run_id=f["run_id"], motivo=f["resultado_incompleto"])
                   for f in filas if f["resultado_incompleto"]]

    extraccion = extractor.read(carpeta / "extraction.json")
    extraccion.update(
        repeticion=repeticion, arquitectura="agente_unico", referencia_r1=campana.R1,
        required_missing=[r["source_path"] for r in ex.manifest if r["required"] and not r["available"]],
        resultados_incompletos=incompletos,
        exporter_wrapper_sha256=extractor.sha(Path(__file__)),
        adaptaciones=["Predicciones leídas de experiments/single_agent/ (export_experimental_data.py fija experiments/nodex).",
                      "mitre/retrieval_observation.jsonl: candidatos recuperados SIEMPRE por el agente único, separados de las atribuciones.",
                      "run_status.jsonl agrega estado_ejecucion_salida y resultado_incompleto."])
    extractor.write_json(carpeta / "extraction.json", extraccion)

    cuaderno = carpeta / "revision_datos_crudos.ipynb"
    nb = extractor.read(cuaderno)
    for celda in nb["cells"]:
        texto = "".join(celda["source"]).replace(campana.R1, version)
        texto = texto.replace("# Revisión de datos crudos de NODEX", "# Revisión de datos crudos — NODEX agente único")
        texto = texto.replace("una corrida por caso", f"agente único, R{repeticion}: una corrida por caso")
        celda["source"] = texto.splitlines(keepends=True)
    extractor.write_json(cuaderno, nb)

    integridad = identidad_y_referencias(carpeta, repeticion, seleccion)
    procedimiento = carpeta / "procedure"
    procedimiento.mkdir()
    for nombre in ("export_experimental_data.py", "export_single_agent_campaign.py", "verify_official_repetition.py",
                   "run_single_agent_campaign.py", "single_agent_runner.py", "run_official_experiment.py",
                   "run_official_repetitions.py"):
        shutil.copyfile(root / "tools" / nombre, procedimiento / nombre)
    for doc in sorted((root / "docs/experimentacion").glob(DOC_PATRON)):
        shutil.copyfile(doc, procedimiento / doc.name)
    (carpeta / "README.md").write_text(readme(version, repeticion), encoding="utf-8")

    with patch.object(verificador, "re", SimpleNamespace(fullmatch=lambda _p, s: re.fullmatch(PATRON, s))):
        verificacion = verificador.verify(carpeta, execute_notebook=True)
    archivos_jsonl, filas_jsonl = jsonl_estrictos(carpeta)
    semilla_intacta = campana.oficial.tree_hashes(campana.SEED) == extractor.read(logs / "rag_initial.json")["files"]
    if not semilla_intacta:
        raise ValueError("La semilla chroma_v2 cambió respecto del inicio de la repetición")
    integridad.update(jsonl_estrictos=archivos_jsonl, filas_jsonl_estrictas=filas_jsonl,
                      semilla_igual_a_rag_initial=semilla_intacta)
    extractor.write_json(carpeta / "repetition_integrity.json", integridad)

    archivo = carpeta.with_suffix(".zip")
    shutil.make_archive(str(carpeta), "zip", root_dir=carpeta)
    en_zip = comprobar_zip(carpeta, archivo)
    archivo.with_suffix(".zip.sha256").write_text(extractor.sha(archivo) + "  " + archivo.name + "\n", encoding="ascii")
    return dict(verificacion, config_version=version, extraction=str(carpeta), archive=str(archivo),
                archive_sha256=extractor.sha(archivo), archive_bytes=archivo.stat().st_size,
                archivos_en_zip_verificados=en_zip, jsonl=archivos_jsonl, filas_jsonl=filas_jsonl,
                resultados_incompletos=incompletos)


def identidad_y_referencias(carpeta, repeticion, seleccion):
    """Doce casos en el orden de R1; entradas y referencias idénticas a la copia de R1."""
    filas = [json.loads(l) for l in (carpeta / "run_status.jsonl").read_text(encoding="utf-8").splitlines()]
    r1 = campana.oficial.r1_selection()["casos"]
    if len(filas) != 12 or [f["case_id"] for f in filas] != [c["case_id"] for c in r1]:
        raise ValueError("La extracción debe conservar los doce casos en el orden de R1")
    if any(f["repeticion"] != repeticion or "__unico__" not in f["run_id"] for f in filas):
        raise ValueError("Repetición o arquitectura incorrecta")
    previo = extractor.read(campana.R1_EXPORT / "manifest.json")
    actual = extractor.read(carpeta / "manifest.json")
    for categoria in ("inputs", "ground_truth"):
        antes = {r["source_path"]: r["sha256_copy"] for r in previo
                 if r["available"] and r["export_path"].startswith(f"originals/{categoria}/")}
        despues = {r["source_path"]: r["sha256_copy"] for r in actual
                   if r["available"] and r["export_path"].startswith(f"originals/{categoria}/")}
        if antes != despues:
            raise ValueError(f"Las {categoria} difieren de R1")
    return dict(cases=12, repetition=repeticion, arquitectura="agente_unico", orden_igual_a_r1=True,
                input_copies_equal_r1=True, ground_truth_copies_equal_r1=True,
                run_ids=[f["run_id"] for f in filas],
                schema="Mismas proyecciones que R1 y sufijos _items; más mitre/retrieval_observation.jsonl y "
                       "performance/single_agent_observation.jsonl")


def readme(version, repeticion):
    return (
        f"# NODEX agente único — R{repeticion}: {version}\n\n"
        "Doce casos en el orden de `oficial-12casos-r1-20261028`, una ejecución por caso, arquitectura "
        "`agente_unico` (`src/single_agent.py`, una llamada al modelo). Mismo modelo, temperatura y política "
        "externa que las campañas oficiales de NODEX multiagente. Abrir `revision_datos_crudos.ipynb`.\n\n"
        "Las proyecciones conservan el esquema de R1: `detection/`, `reconstruction/`, `mitre/`, `reports/`, "
        "`performance/`. Los archivos `_items` mantienen orden y duplicados; `present` distingue ausencia de null. "
        "Las referencias (ground truth) se copiaron solo al extraer, después de la inferencia, y están separadas "
        "de las predicciones.\n\n"
        "Propio del agente único: `mitre/retrieval_observation.jsonl` (candidatos MITRE recuperados SIEMPRE, con "
        "similitud, texto de la consulta y comprobación de que llegaron al prompt; no son atribuciones) y "
        "`performance/single_agent_observation.jsonl` (JSON válido y tamaño del prompt). El texto exacto enviado al "
        "modelo está en `originals/execution/.../<run_id>.llm_input.json`.\n\n"
        "`run_status.jsonl` conserva los 12 casos e indica `resultado_incompleto` cuando el agente no entregó el "
        "contrato completo (la corrida se cuenta como completa con la regla de NODEX si trae un veredicto booleano).\n\n"
        "Consulte `manifest.json`, `extraction.json`, `verification.json` y `repetition_integrity.json`. La carpeta "
        "`procedure/` conserva los scripts y la bitácora. No se ejecuta el sistema desde el notebook ni se calculan "
        "métricas.\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config-version", required=True)
    args = parser.parse_args()
    print(json.dumps(export(args.config_version), ensure_ascii=False, indent=2, default=str))
