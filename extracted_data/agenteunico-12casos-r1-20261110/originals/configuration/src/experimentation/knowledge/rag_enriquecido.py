"""Corpus histórico y snapshot aislado; nunca ejecuta agentes ni evaluadores.

python -m src.experimentation.knowledge.rag_enriquecido construir
python -m src.experimentation.knowledge.rag_enriquecido poblar
python -m src.experimentation.knowledge.rag_enriquecido restaurar --destino ...

Los imports de Chroma/embeddings/herramienta se limitan a un proceso hijo
con CHROMA_PATH explícito. Las bases de origen se leen como archivos o SQLite
ro, nunca con la API de Chroma. El snapshot se copia después de terminar el hijo.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
VERSION = "rag_enriquecido_30_v1"
DEFAULT_OUTPUT = ROOT / "experiments/knowledge" / VERSION
SEED = ROOT / "experiments/knowledge/chroma_v2"
QUOTAS = {("bgl", "normal"): 8, ("bgl", "anomalo"): 7,
          ("uwf", "normal"): 7, ("uwf", "anomalo"): 8}
REPETITIONS = ("oficial-12casos-r1-20261028", "oficial-12casos-r2-20261103",
               "oficial-12casos-r3-20261103")


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def tree(path):
    path = Path(path)
    return {p.relative_to(path).as_posix(): {"sha256": sha(p), "bytes": p.stat().st_size}
            for p in sorted(path.rglob("*")) if p.is_file()}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def inside(path, parent):
    return Path(path).resolve().is_relative_to(Path(parent).resolve())


def protected():
    """Inventario de archivos que esta preparación nunca debe modificar."""
    paths = [ROOT / x for x in ("experiments/cases", "experiments/ground_truth",
             "experiments/manifests", "experiments/knowledge/chroma_v2", "data/chroma",
             "src/agents", "src/graph", "src/preprocessing")]
    paths += [ROOT / base / r for r in REPETITIONS
              for base in ("experiments/ejecucion", "extracted_data")]
    result = {}
    for path in paths:
        if path.exists():
            result[path.relative_to(ROOT).as_posix()] = {
                k: v for k, v in tree(path).items() if '__pycache__/' not in k and not k.endswith('.pyc')}
    for name in ("src/memory.py", "src/config.py", "src/pipeline.py",
                 "src/tools/tool_consultar_rag.py", "src/tools/aggregation.py",
                 "src/experimentation/campana.py"):
        result[name] = sha(ROOT / name)
    return result


def official_exclusions():
    """Lee exclusivamente selecciones, entradas y procedencia, nunca resultados/GT."""
    repetitions, reference = {}, None
    cases = []
    for version in REPETITIONS:
        path = ROOT / "experiments/ejecucion" / version / "selection.json"
        data = read(path)
        rows = [{k: r[k] for k in ("case_id", "dataset", "input_path", "sha256")}
                for r in data["casos"]]
        require(len(rows) == 12 and len({r["case_id"] for r in rows}) == 12,
                f"Selección oficial inválida: {version}")
        if reference is None:
            reference = rows
        require(rows == reference, "Las selecciones de R1–R3 no son iguales")
        repetitions[version] = {"path": path.relative_to(ROOT).as_posix(), "sha256": sha(path)}
    for row in reference:
        path = ROOT / row["input_path"]
        require(sha(path) == row["sha256"], f"Entrada oficial modificada: {path}")
        meta = read(path.with_suffix(".json"))
        require(meta["case_id"] == row["case_id"] and meta["particion"] == "evaluacion",
                "Procedencia de evaluación inconsistente")
        cases.append({**row, "metadata_sha256": sha(path.with_suffix(".json")),
                      "metadata": meta, "raw": path.read_text(encoding="utf-8")})
    return repetitions, cases


def source_csv(work):
    """Reconstruye exactamente los CSV originales de preparación, en tmp/."""
    from src.experimentation.datasets.uwf import convertir_shard
    conversion = read(ROOT / "experiments/manifests/uwf_conversion.json")
    sources = []
    for shard in conversion["shards"]:
        parquet = ROOT / shard["archivo_parquet"]
        require(sha(parquet) == shard["sha256_parquet"], f"Parquet distinto: {parquet}")
        events = work / "eventos" / (shard["semana"] + ".csv")
        labels = work / "etiquetas" / events.name
        if not events.exists() or not labels.exists():
            convertir_shard(parquet, shard["semana"], work, ROOT)
        require(sha(events) == shard["sha256_eventos"] and sha(labels) == shard["sha256_etiquetas"],
                f"Conversión no reproduce el manifiesto original: {shard['semana']}")
        sources.append({k: shard[k] for k in ("semana", "archivo_parquet", "sha256_parquet",
                                             "sha256_eventos", "sha256_etiquetas")})
    return sources


def csv_rows(raw):
    return list(csv.DictReader(io.StringIO(raw)))


def window(ds, raw):
    values = ([float(line.split()[0]) for line in raw.splitlines()]
              if ds == "bgl" else [float(r["ts"]) for r in csv_rows(raw)])
    return [min(values), max(values)]


def overlaps(a, b):
    return a[0] <= b[1] and b[0] <= a[1]


def incident_base(group):
    return group.split("#", 1)[0]


def incident_groups(meta):
    return {incident_base(g) for g in meta["grupos"] if not g.startswith("fondo:")}


def record_key(record):
    return (record["source_file_sha256"], record["source_line"])


def validate_disjoint(cases, forbidden):
    """Controles reutilizables; falla también ante alias y modificaciones de UID."""
    seen_ids, seen_hashes, seen_records, seen_uids, seen_events = set(), set(), set(), set(), set()
    for case in cases:
        require(case["historical_case_id"] not in seen_ids, "ID histórico duplicado")
        require(case["original_id"] not in forbidden["case_ids"], "Caso de evaluación reutilizado")
        require(case["fragment_sha256"] not in forbidden["hashes"], "Archivo de evaluación idéntico")
        require(case["fragment_sha256"] not in seen_hashes, "Fragmento histórico duplicado")
        require(case["partition"] == "desarrollo", "Fuente ajena a desarrollo")
        local_records, local_uids, local_events = set(), set(), set()
        for record in case["records"]:
            key, uid, event = record_key(record), record.get("uid"), record["original_event_sha256"]
            require(key not in forbidden["records"] and key not in seen_records and key not in local_records,
                    "Registro original compartido o duplicado")
            require(event not in forbidden["events"] and event not in seen_events and event not in local_events,
                    "Evento original compartido, derivado o duplicado")
            if uid:
                require(uid not in forbidden["uids"] and uid not in seen_uids and uid not in local_uids,
                        "UID compartido o duplicado")
                local_uids.add(uid)
            local_records.add(key)
            local_events.add(event)
        for other in forbidden["windows"]:
            if other["dataset"] == case["dataset"]:
                require(not overlaps(case["time_window"], other["window"]),
                        "Ventana temporal de evaluación superpuesta")
        for other in cases:
            if other is case:
                break
            if other["dataset"] == case["dataset"]:
                require(not overlaps(case["time_window"], other["time_window"]),
                        "Ventanas históricas superpuestas")
        if case.get("incident_id"):
            require(incident_base(case["incident_id"]) not in forbidden["incidents"],
                    "Episodio de evaluación reutilizado o recortado")
            require(case["incident_shard"] not in forbidden["incident_shards"],
                    "Semana de incidente oficial reutilizada")
        seen_ids.add(case["historical_case_id"])
        seen_hashes.add(case["fragment_sha256"])
        seen_records.update(local_records)
        seen_uids.update(local_uids)
        seen_events.update(local_events)
    return {"cases": len(seen_ids), "records": len(seen_records), "uids": len(seen_uids),
            "shared_cases": 0, "shared_records": 0, "shared_uids": 0, "shared_events": 0,
            "overlapping_time_windows": 0, "duplicate_fragments": 0}


def choose_diverse(candidates, count):
    """Cobertura de atributos primero, desempate lexicográfico; sin azar."""
    remaining = sorted(candidates, key=lambda c: c["original_id"])
    chosen, covered = [], set()
    while remaining and len(chosen) < count:
        def score(c):
            return sum(100 if f.startswith(('label:', 'technique:')) else
                       20 if f.startswith(('shard:', 'ip:', 'service:', 'proto:', 'state:')) else 1
                       for f in set(c['selection_features']) - covered)
        best = max(remaining, key=score)
        chosen.append(best)
        covered.update(best["selection_features"])
        remaining.remove(best)
    require(len(chosen) == count, f"Candidatos insuficientes: {len(chosen)}/{count}")
    return chosen


def prepare(output, csv_work):
    require(not output.exists(), f"El destino ya existe; no se sobrescribe: {output}")
    before = protected()
    repetitions, official = official_exclusions()
    sources = source_csv(csv_work)
    from src.experimentation.datasets.agrupacion import agrupar_bgl, _sin_etiqueta_bgl
    from src.experimentation.datasets.particion import particionar_grupos
    from src.experimentation.datasets.uwf import COLUMNAS_EVENTO
    from src.experimentation.datasets.uwf_casos import _leer, construir_incidentes, particionar_incidentes
    malicious, benign = _leer(csv_work)
    incidents = construir_incidentes(malicious)
    split = particionar_incidentes(incidents)
    require(len(incidents) == 349 and len(split["desarrollo"]) == 103,
            "No se reproduce la partición original de UWF")
    bgl_split = particionar_grupos(agrupar_bgl(ROOT / "data/logs/BGL_2k.log"))
    bgl_dev = {g.grupo for g in bgl_split["desarrollo"]}
    by_uid = {r.uid: r for r in malicious}
    by_uid.update((r.uid, r) for records in benign.values() for r in records)
    shard_sources = {s["semana"]: s for s in sources}
    bgl_path = ROOT / "data/logs/BGL_2k.log"
    bgl_hash, bgl_lines = sha(bgl_path), bgl_path.read_text(encoding="utf-8").splitlines()
    expected = read(ROOT / "experiments/manifests/inventario_fuentes.json")["bgl_log"][0]["sha256"]
    require(bgl_hash == expected, "BGL original modificado")

    def bgl_record(line):
        text = _sin_etiqueta_bgl(bgl_lines[line - 1])
        return {"source_path": "data/logs/BGL_2k.log", "source_file_sha256": bgl_hash,
                "source_line": line, "uid": None, "original_event_sha256": digest(text),
                "original_label": bgl_lines[line - 1].split()[0], "original_ts": float(text.split()[0])}

    def uwf_record(r):
        s = shard_sources[r.shard]
        return {"source_path": s["archivo_parquet"], "source_file_sha256": s["sha256_parquet"],
                "source_line": r.fila_original,
                "source_line_unit": "fila CSV deduplicado (cabecera=1), regenerable por hash",
                "converted_events_sha256": s["sha256_eventos"], "uid": r.uid,
                "original_event_sha256": digest(dict(zip(COLUMNAS_EVENTO, r.valores))),
                "original_ts": r.ts, "original_label": r.binario,
                "original_tactics": list(r.tacticas), "original_techniques": list(r.tecnicas)}

    forbidden = {"case_ids": set(), "hashes": set(), "records": set(), "events": set(),
                 "uids": set(), "incidents": set(), "incident_shards": set(), "windows": []}
    # Se excluye además toda la partición de evaluación a nivel de registros,
    # UID, episodio y ventana. Solo las 12 entradas aportan semanas prohibidas.
    exclusion_evidence = []
    official_ids = {c["case_id"] for c in official}
    for ds in ("bgl", "uwf"):
        for f in sorted((ROOT / "experiments/cases" / ds / "evaluacion").glob("*.json")):
            meta = read(f)
            raw_path = f.parent / meta["archivo_contenido"]
            raw = raw_path.read_text(encoding="utf-8")
            forbidden["case_ids"].add(meta["case_id"])
            forbidden["hashes"].add(sha(raw_path))
            forbidden["hashes"].add(hashlib.sha256(raw.encode('utf-8')).hexdigest())
            groups = incident_groups(meta) if ds == "uwf" else set()
            forbidden["incidents"].update(groups)
            if meta["case_id"] in official_ids:
                forbidden["incident_shards"].update(g.split("__")[0] for g in groups)
            events = []
            for p in meta["procedencia"]:
                r = bgl_record(p["linea_original"]) if ds == "bgl" else uwf_record(by_uid[p["uid"]])
                forbidden["records"].add(record_key(r))
                forbidden["events"].add(r["original_event_sha256"])
                if r["uid"]:
                    forbidden["uids"].add(r["uid"])
                events.append(r)
            # Los casos UWF rebajan timestamps. Se comprueban tanto la ventana
            # compuesta como los intervalos originales por archivo/episodio.
            windows = [window(ds, raw)]
            if ds == "uwf":
                per_source = defaultdict(list)
                for p, r in zip(meta["procedencia"], events):
                    per_source[(r["source_file_sha256"], p["grupo"])].append(r["original_ts"])
                windows += [[min(v), max(v)] for v in per_source.values()]
            forbidden["windows"].extend({"dataset": ds, "window": w, "case_id": meta["case_id"]}
                                         for w in windows)
            if meta["case_id"] in official_ids:
                exclusion_evidence.append({"case_id": meta["case_id"], "dataset": ds,
                    "input_path": raw_path.relative_to(ROOT).as_posix(), "sha256": sha(raw_path),
                    "metadata_sha256": sha(f), "source_record_keys": [list(record_key(r)) for r in events],
                    "uids": [r["uid"] for r in events if r["uid"]], "incidents": sorted(groups),
                    "time_windows": windows})

    candidates, rejected = [], []

    def candidate(ds, original_id, label, raw, records, **extra):
        return {"dataset": ds, "original_id": original_id, "classification": label,
                "partition": "desarrollo", "raw": raw,
                "fragment_sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
                "records": records, "time_window": window(ds, raw), **extra}

    for ds in ("bgl", "uwf"):
        for f in sorted((ROOT / "experiments/cases" / ds / "desarrollo").glob("*.json")):
            meta = read(f)
            gtpath = ROOT / "experiments/ground_truth" / ds / "desarrollo" / f.name
            gt = read(gtpath)
            require(meta["particion"] == "desarrollo" and meta["case_id"] == gt["case_id"],
                    "Metadatos/etiqueta de desarrollo inconsistentes")
            if ds == "uwf" and gt["etiqueta_deteccion"] != "normal":
                continue  # reconstruimos otros episodios de desarrollo, con semana separada
            raw_path = f.parent / meta["archivo_contenido"]
            raw = raw_path.read_text(encoding="utf-8")
            if ds == "bgl":
                require(set(meta["grupos"]) <= bgl_dev, "Grupo BGL fuera de desarrollo")
                records = [bgl_record(p["linea_original"]) for p in meta["procedencia"]]
                expected_raw = "\n".join(_sin_etiqueta_bgl(bgl_lines[r["source_line"] - 1]) for r in records) + "\n"
                require(raw == expected_raw, "Fragmento BGL no corresponde al original")
                label = "anomalo" if any(r["original_label"] != "-" for r in records) else "normal"
                require(gt["etiqueta_deteccion"] == label, "Etiqueta BGL contradice las líneas originales")
                features = sorted({"label:" + r["original_label"] for r in records})
                # Severidad y mensaje del original ayudan a cubrir patrones normales diversos.
                features += sorted({"message:" + " ".join(l.split()[7:]) for l in raw.splitlines()})
                condition = "ventana_original_20"
            else:
                rows = csv_rows(raw)
                records = [uwf_record(by_uid[p["uid"]]) for p in meta["procedencia"]]
                require(len(rows) == len(records), "Procedencia UWF incompleta")
                for row, p, r in zip(rows, meta["procedencia"], records):
                    source = by_uid[p["uid"]]
                    require(row == dict(zip(COLUMNAS_EVENTO, source.valores)), "Normal UWF derivado o alterado")
                    require(p["linea_original"] == source.fila_original and r["original_label"] == "False",
                            "Normal UWF contradice las etiquetas originales")
                label, condition = "normal", "fondo_normal_original"
                features = sorted({"service:" + r["service"] for r in rows}
                                  | {"proto:" + r["proto"] for r in rows}
                                  | {"state:" + r["conn_state"] for r in rows})
            candidates.append(candidate(ds, meta["case_id"], label, raw, records,
                source_case_path=f.relative_to(ROOT).as_posix(), source_case_sha256=sha(f),
                source_input_path=raw_path.relative_to(ROOT).as_posix(), source_input_sha256=sha(raw_path),
                source_ground_truth_path=gtpath.relative_to(ROOT).as_posix(), source_ground_truth_sha256=sha(gtpath),
                original_label=gt["etiqueta_original"], condition=condition,
                selection_features=features, mitre_references=[]))

    # Usa únicamente incidentes asignados a desarrollo por el algoritmo original.
    # Ningún timestamp se desplaza y no se inyectan ni se fabrican registros.
    for incident in split["desarrollo"]:
        records = [uwf_record(r) for r in incident.registros]
        raw = ",".join(COLUMNAS_EVENTO) + "\n" + "\n".join(
            ",".join(r.valores) for r in incident.registros)
        refs = [{"nivel": "tactica", "id": t} for t in incident.tacticas]
        refs += [{"nivel": "tecnica", "id": t} for t in incident.tecnicas]
        candidates.append(candidate("uwf", incident.incidente_id, "anomalo", raw, records,
            incident_id=incident.incidente_id, incident_shard=incident.shard,
            original_label="True", condition=("visible" if len(records) >= 20 else "sigiloso"),
            source_case_path="particionar_incidentes(construir_incidentes(_leer(CSV_originales)))",
            source_case_sha256=sha(ROOT / "src/experimentation/datasets/uwf_casos.py"),
            selection_features=["shard:" + incident.shard, "ip:" + incident.src_ip,
                                "size:" + str(len(records)), *["technique:" + t for t in incident.tecnicas]],
            mitre_references=refs))

    valid = []
    for c in candidates:
        c["historical_case_id"] = "candidate:" + c["original_id"]
        try:
            validate_disjoint([c], forbidden)
            valid.append(c)
        except ValueError as e:
            rejected.append({"original_id": c["original_id"], "reason": str(e)})
    chosen = []
    availability = {}
    for (ds, label), n in QUOTAS.items():
        pool = [c for c in valid if (c["dataset"], c["classification"]) == (ds, label)]
        availability[f"{ds}/{label}"] = len(pool)
        chosen += choose_diverse(pool, n)
    chosen.sort(key=lambda c: (c["dataset"], c["classification"], c["original_id"]))
    counters = Counter()
    for c in chosen:
        counters[c["dataset"]] += 1
        c["historical_case_id"] = f"{c['dataset']}_hist_{counters[c['dataset']]:03d}"
    audit = validate_disjoint(chosen, forbidden)
    require(Counter((c["dataset"], c["classification"]) for c in chosen) == Counter(QUOTAS), "Cuotas incorrectas")

    # La misma función y la misma vista v2 que pipeline._preparar_estado_inicial;
    # no se importa pipeline (importaría el grafo/LLM). firma_lote solo lee estos campos de v2.
    from src.tools.aggregation import preprocesar_lote, firma_lote
    for c in chosen:
        _, v2, summary = preprocesar_lote(c["raw"])
        c["signature"] = firma_lote(summary, v2)
        require(len(c["signature"]) <= 2000, "Firma supera el truncamiento real de NODEX")
        c["features"] = {k: v2[k] for k in ("total_eventos", "decoder_distribution", "product_distribution",
                                           "severity_distribution", "event_categories", "parsing")}
        if c['dataset'] == 'bgl':
            # Observaciones literales de las columnas BGL, sin depender de que
            # el decoder productivo reconozca el lote y sin inferir ataques.
            messages = Counter(line.split(None, 8)[-1] for line in c['raw'].splitlines())
            c['observed_patterns'] = {
                'original_label_counts': dict(Counter(r['original_label'] for r in c['records'])),
                'message_samples': [{'message': m[:180], 'count': n}
                                    for m, n in messages.most_common(3)],
                'raw_severity_counts': dict(Counter(line.split()[7] for line in c['raw'].splitlines()))}
            observed = '; '.join(f"{x['count']} × {x['message']}" for x in c['observed_patterns']['message_samples'])
        else:
            rows = csv_rows(c['raw'])
            c['observed_patterns'] = {
                'protocol_counts': dict(Counter(r['proto'] for r in rows)),
                'service_counts': dict(Counter(r['service'] for r in rows)),
                'connection_state_counts': dict(Counter(r['conn_state'] for r in rows)),
                'destination_ports_top5': Counter(r['dest_port_zeek'] for r in rows).most_common(5),
                'distinct_source_ips': len({r['src_ip_zeek'] for r in rows}),
                'distinct_destination_ips': len({r['dest_ip_zeek'] for r in rows})}
            observed = canonical(c['observed_patterns'])
        c["description"] = (f"{c['dataset'].upper()}: {len(c['records'])} registros originales; "
            f"referencia {c['classification']} ({c['original_label']}). Observado: {observed}")
        c["vector_id"] = f"{VERSION}:{c['historical_case_id']}"
        extension = ".log" if c["dataset"] == "bgl" else ".csv"
        c["corpus_path"] = f"corpus/{c['dataset']}/{c['historical_case_id']}{extension}"
        out = output / c["corpus_path"]
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(c.pop("raw"), encoding="utf-8", newline="\n")
        require(sha(out) == c["fragment_sha256"], "Exportación altera el fragmento")
        write(out.with_suffix(".json"), c)

    write(output / "manifests/configuracion_corpus.json", {
        "version": VERSION, "created_utc": datetime.now(timezone.utc).isoformat(),
        "selection": "cobertura greedy ponderada: etiqueta/técnica=100, fuente/IP/protocolo/servicio/estado=20, mensaje/tamaño=1; desempate original_id",
        "randomness": False, "partition_seed": 20261003, "quotas": {f"{d}/{c}": n for (d,c),n in QUOTAS.items()},
        "uwf_anomalies": "episodios originales de desarrollo; timestamps originales; sin mezcla ni rebase",
        "uwf_campaign_control": "excluir todas las semanas fuente de incidentes de los 12 oficiales",
        "campaign_limitation": "UWF no proporciona campaign_id: semanas e IP son controles conservadores, no prueba de campañas reales distintas",
        "original_split": {"bgl_development_groups": sorted(bgl_dev),
            "uwf_development_incidents": [i.incidente_id for i in split['desarrollo']],
            "uwf_total_incidents": len(incidents)},
        "available_after_exclusions": availability, "rejected_candidates": rejected,
        "uwf_valid_anomaly_sizes": dict(sorted(Counter(len(c['records']) for c in valid if c['dataset']=='uwf' and c['classification']=='anomalo').items())),
        "uwf_visible_limit": "No existen episodios de >=20 registros de desarrollo fuera de las semanas de incidentes oficiales; se prioriza independencia y se conservan episodios sigilosos completos de 3–6 registros.",
        "functional_changes": [], "llm_calls": 0, "evaluation_runs": 0, "metrics_D1_D4": False})
    manifest = output / "manifests/casos_seleccionados.csv"
    with manifest.open("w", encoding="utf-8", newline="") as f:
        keys = ["historical_case_id", "dataset", "classification", "original_label", "original_id", "partition",
                "condition", "fragment_sha256", "vector_id", "corpus_path", "source_case_path"]
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        writer.writerows({k: c.get(k, "") for k in keys} for c in chosen)
    with (output / "corpus/corpus_historico.jsonl").open("w", encoding="utf-8", newline="\n") as f:
        for c in chosen:
            f.write(canonical(c) + "\n")
    write(output / "manifests/fuentes_y_hashes.json", {
        "bgl": {"source_path": "data/logs/BGL_2k.log", "sha256": bgl_hash}, "uwf": sources,
        "partition_manifests": {f"{ds}.json": sha(ROOT / f"experiments/manifests/{ds}.json") for ds in ('bgl','uwf')},
        "conversion_manifest_sha256": sha(ROOT / "experiments/manifests/uwf_conversion.json"),
        "official_selections": repetitions, "official_exclusions": exclusion_evidence})
    require(before == protected(), "Archivos protegidos modificados durante preparación")
    write(output / "manifests/validacion_independencia.json", {
        "status": "passed", **audit, "official_cases": 12, "excluded_entire_evaluation_partition": len(forbidden['case_ids']),
        "original_labels_verified": True, "original_sources_verified": True,
        "source_csv_hashes_match_original_conversion": True,
        "forbidden_incident_shards": sorted(forbidden['incident_shards']),
        "shared_incident_shards_with_official_attacks": 0, "evaluation_ground_truth_parsed": False,
        "evaluation_predictions_used": False, "original_event_hashes_ignore_synthetic_rebase": True,
        "campaign_identity": "no anotada; no se afirma independencia por campaña real",
        "protected_files_unchanged": True, "protected_inventory_sha256": digest(before)})
    write(output / "manifests/artefactos_corpus.json", tree(output / "corpus"))
    by_signature = defaultdict(list)
    for c in chosen:
        by_signature[c['signature']].append(c)
    write(output / 'validation/validacion_firmas.json', {
        'status': 'passed_with_limitations', 'production_signature_function': 'src.tools.aggregation.firma_lote',
        'signature_matches_production_v2_contract': True, 'cases': len(chosen), 'unique_signatures': len(by_signature),
        'cases_with_zero_parsing_coverage': [c['historical_case_id'] for c in chosen if c['features']['parsing']['coverage'] == 0],
        'cross_class_signature_collisions': [{'signature': signature,
            'cases': [{'historical_case_id': c['historical_case_id'], 'classification': c['classification']} for c in group]}
            for signature, group in by_signature.items() if len({c['classification'] for c in group}) > 1],
        'limitation': 'La firma productiva puede ser genérica para BGL saneado. No se garantiza separación de clases ni recuperación del propio ID dentro de top_k=3; la clasificación original y los mensajes observados permanecen en los metadatos. No se cambia el decoder ni el RAG.'})
    print(canonical({"status": "corpus_validated", "counts": dict(counters), "availability": availability, **audit}))


def load_corpus(output):
    require(read(output / "manifests/validacion_independencia.json")["status"] == "passed",
            "Independencia no superada; poblado prohibido")
    expected = read(output / "manifests/artefactos_corpus.json")
    require(tree(output / "corpus") == expected, "Corpus cambiado después de su validación")
    cases = [json.loads(line) for line in (output / "corpus/corpus_historico.jsonl").read_text(encoding="utf-8").splitlines()]
    require(len(cases) == 30 and len({c['historical_case_id'] for c in cases}) == 30, "No hay 30 casos únicos")
    require(Counter((c['dataset'], c['classification']) for c in cases) == Counter(QUOTAS), "Cuotas incorrectas")
    for c in cases:
        require(sha(output / c["corpus_path"]) == c["fragment_sha256"], "Hash del corpus incorrecto")
    return cases


def metadata(case):
    """Mismo contrato de seed_pattern, con procedencia escalar adicional."""
    return {
        "clasificacion": case["classification"],
        "mitigacion": ("No aplica: comportamiento normal según etiquetas originales." if case["classification"] == "normal"
                       else "El dataset no proporciona una mitigación de referencia."),
        "historical_case_id": case["historical_case_id"], "vector_id": case["vector_id"],
        "knowledge_origin": "historical_development", "corpus_version": VERSION,
        "dataset": case["dataset"], "original_id": case["original_id"], "partition": "desarrollo",
        "fragment_sha256": case["fragment_sha256"], "records_count": len(case["records"]),
        "original_label": case["original_label"], "condition": case["condition"],
        "provenance_ref": str(Path(case["corpus_path"]).with_suffix(".json")).replace("\\", "/"),
        "source_paths": canonical(sorted({r["source_path"] for r in case["records"]})),
        "source_hashes": canonical(sorted({r["source_file_sha256"] for r in case["records"]})),
        "record_identifiers_sha256": digest([record_key(r) for r in case["records"]]),
        "descripcion": case["description"], "features": canonical(case["features"]),
        "observed_patterns": canonical(case["observed_patterns"]),
        "mitre_references": canonical(case["mitre_references"]),
    }


def seed_historical(memory, cases):
    """Equivalente experimental de seed_pattern; IDs estables y upsert idempotente.

    seed_pattern no acepta IDs ni procedencia y duplica al repetir. Se utiliza
    la colección y función de embeddings creadas por LongTermMemory, sin
    modificar seed_pattern ni el código/contrato de recuperación productivo.
    """
    existing = memory.patterns.get(ids=[c['vector_id'] for c in cases], include=['documents', 'metadatas'])
    stored = {vid: (existing['documents'][i], existing['metadatas'][i])
              for i, vid in enumerate(existing['ids'])}
    pending = []
    for c in cases:
        if c['vector_id'] in stored:
            require(stored[c['vector_id']] == (c['signature'], metadata(c)),
                    'ID histórico ya existente con otro contenido; crear nueva versión')
        else:
            pending.append(c)
    if pending:
        memory.patterns.upsert(ids=[c["vector_id"] for c in pending],
            documents=[c["signature"] for c in pending], metadatas=[metadata(c) for c in pending])


def collection_state(col):
    import numpy as np
    data = col.get(include=["documents", "metadatas", "embeddings"])
    rows = []
    for i in sorted(range(len(data["ids"])), key=lambda i: data["ids"][i]):
        v = np.asarray(data["embeddings"][i], dtype="<f4")
        require(v.shape == (384,) and np.isfinite(v).all() and np.linalg.norm(v) > 0, "Embedding inválido")
        rows.append({"id": data["ids"][i], "document": data["documents"][i], "metadata": data["metadatas"][i],
                     "embedding_sha256_float32": hashlib.sha256(v.tobytes()).hexdigest()})
    return {"count": len(rows), "content_sha256": digest(rows), "metadata": col.metadata,
            "configuration": col.configuration_json}


def retrieval_checks(memory, cases, output, tool):
    from src.config import SIMILARITY_FLOOR, SIMILARITY_FLOOR_ATTACK, TOP_K_FEWSHOT
    from src.tools.aggregation import preprocesar_lote, firma_lote
    queries, coverage = [], set()
    signatures = {c["signature"] for c in cases}
    for c in cases:
        raw = (output / c["corpus_path"]).read_text(encoding="utf-8")
        # Variante formada por registros reales del mismo caso; no se edita
        # una firma a mano y se calcula con las funciones productivas.
        lines = raw.splitlines()
        variant = "\n".join(lines[:-1])
        for kind, text in (("original", raw), ("one_record_held_out", variant)):
            _, v2, summary = preprocesar_lote(text)
            signature = firma_lote(summary, v2)
            direct = memory.retrieve_examples(signature)
            returned = tool({"firma": signature, "resumen_logs": summary})
            require(returned["contexto_rag"] == direct, "Contrato herramienta/memoria divergente")
            json.dumps(returned, ensure_ascii=False, allow_nan=False)  # serialización real para el agente
            require(bool(direct), f"La herramienta no recupera ejemplos para {c['historical_case_id']}/{kind}")
            related = []
            for r in direct:
                m = r["meta"]
                require(m["vector_id"] in {x["vector_id"] for x in cases}, "ID recuperado sin trazabilidad")
                require(m["clasificacion"] in ("normal", "anomalo"), "Clase ininterpretable")
                require(r["similitud"] >= SIMILARITY_FLOOR - .0005, "Umbral de recuperación incorrecto")
                require((output / m["provenance_ref"]).is_file(), "Procedencia no resoluble")
                if m["dataset"] == c["dataset"] and m["clasificacion"] == c["classification"]:
                    related.append(m["historical_case_id"])
                    coverage.add((c["dataset"], c["classification"]))
            queries.append({"historical_case_id": c["historical_case_id"], "dataset": c["dataset"],
                "classification": c["classification"], "kind": kind, "signature": signature,
                "query_is_stored_signature": signature in signatures,
                "related_same_dataset_class": related,
                "self_id_in_top_k": any(r['meta']['historical_case_id']==c['historical_case_id'] for r in direct),
                "historical_results": [{"vector_id": r['meta']['vector_id'],
                    "historical_case_id": r['meta']['historical_case_id'], "dataset": r['meta']['dataset'],
                    "classification": r['meta']['clasificacion'], "similarity": r['similitud'],
                    "signature": r['texto']} for r in direct],
                "mitre_result_ids": [r['meta'].get('technique_id') for r in returned['tecnicas_mitre']]})
    require(coverage == set(QUOTAS), "No se recuperan los cuatro estratos históricos")
    novel = [q for q in queries if not q['query_is_stored_signature'] and q['related_same_dataset_class']]
    require(novel, "No hay recuperación de consultas no idénticas")
    return {"status": "passed", "tool": "src.tools.tool_consultar_rag.tool_consultar_rag",
        "memory_function": "LongTermMemory.retrieve_examples", "llm_calls": 0,
        "threshold": SIMILARITY_FLOOR, "attack_threshold": SIMILARITY_FLOOR_ATTACK,
        "top_k": TOP_K_FEWSHOT, "query_count": len(queries),
        "nonidentical_related_queries": len(novel), "strata_retrieved": sorted('/'.join(k) for k in coverage),
        "note": "La firma agregada puede coincidir entre casos: no garantiza recuperar el propio ID ni distinguir clases con la misma firma. No se mide desempeño del LLM.",
        "queries": queries}


def worker(output, report, populate):
    """Solo se invoca en hijo con una copia de trabajo y parámetros congelados."""
    require('CHROMA_PATH' in os.environ, "Falta aislamiento de Chroma")
    path = Path(os.environ['CHROMA_PATH']).resolve()
    require(path != SEED.resolve() and path != (ROOT / 'data/chroma').resolve(), "Base protegida")
    require(inside(path, ROOT / 'tmp'), "El hijo solo puede abrir copias en tmp/")
    import importlib
    import importlib.metadata
    import numpy as np
    from src.config import EMBEDDING_MODEL, SIMILARITY_FLOOR, SIMILARITY_FLOOR_ATTACK, TOP_K_FEWSHOT, MAX_RAW_CHARS_EMBED
    rag = importlib.import_module('src.tools.tool_consultar_rag')
    memory = rag.ltm
    cases = load_corpus(output)
    require(EMBEDDING_MODEL == 'all-MiniLM-L6-v2' and SIMILARITY_FLOOR == .55
            and SIMILARITY_FLOOR_ATTACK == .42 and TOP_K_FEWSHOT == 3 and MAX_RAW_CHARS_EMBED == 2000,
            "Parámetros de recuperación distintos de R1–R3")
    static_before = collection_state(memory.attack_techniques)
    before = {c.name: c.count() for c in memory._db.list_collections()}
    require(static_before['count'] == 697 and memory.errors.count() == 0 and memory.history.count() == 0,
            "La semilla contiene memoria dinámica o un catálogo inesperado")
    if populate:
        require(memory.patterns.count() == 0, "La copia inicial contiene patrones dinámicos")
        seed_historical(memory, cases)
    after_first = collection_state(memory.patterns)
    require(after_first['count'] == 30, "Poblado no representa los 30 casos")
    seed_historical(memory, cases)
    require(collection_state(memory.patterns) == after_first, "Poblado no idempotente")
    stored = memory.patterns.get(ids=[c['vector_id'] for c in cases], include=['documents','metadatas','embeddings'])
    require(set(stored['ids']) == {c['vector_id'] for c in cases}, "Faltan documentos por ID")
    by_id = {c['vector_id']: c for c in cases}
    for i, vid in enumerate(stored['ids']):
        c = by_id[vid]
        require(stored['documents'][i] == c['signature'] and stored['metadatas'][i] == metadata(c), "Documento alterado")
    recomputed = np.asarray(memory._ef([by_id[vid]['signature'] for vid in stored['ids']]), dtype=np.float32)
    require(np.allclose(recomputed, stored['embeddings'], atol=2e-6, rtol=0), "Embeddings no corresponden al modelo original")
    retrieval = retrieval_checks(memory, cases, output, rag.tool_consultar_rag)
    require(collection_state(memory.attack_techniques) == static_before, "MITRE modificado")
    after = {c.name: c.count() for c in memory._db.list_collections()}
    packages = {k: importlib.metadata.version(k) for k in ('chromadb','sentence-transformers','torch','transformers')}
    reference_packages = dict(read(ROOT / 'experiments/ejecucion' / REPETITIONS[0] / 'environment.json')['packages'])
    require(all(reference_packages[k] == v for k, v in packages.items()), 'Dependencias de embeddings distintas de R1')
    write(report, {'status': 'passed', 'documents_before': before, 'documents_after': after,
        'embeddings_after': after, 'embedding_dimension': 384, 'embedding_model': EMBEDDING_MODEL,
        'packages': packages, 'embedding_dependency_versions_match_R1': True,
        'mitre_before': static_before, 'mitre_after': collection_state(memory.attack_techniques),
        'patterns': after_first, 'idempotent': True, 'all_ids_retrievable': True,
        'embeddings_recomputed_and_verified': 30, 'max_embedding_absolute_difference': float(np.max(np.abs(recomputed - stored['embeddings']))),
        'retrieval': retrieval})


def model_inventory():
    info = read(ROOT / 'experiments/knowledge/inventario_conocimiento_v2.json')['conocimiento']['modelo_embeddings']
    hub = Path(os.environ.get('HF_HOME', Path.home() / '.cache/huggingface'))
    if hub.name != 'hub':
        hub = hub / 'hub'
    snapshot = hub / ('models--sentence-transformers--' + info['modelo']) / 'snapshots' / info['revision']
    require((snapshot.parents[1] / 'refs/main').read_text(encoding='utf-8').strip() == info['revision'],
            'La revisión seleccionada offline no es la utilizada en R1')
    for f in info['archivos']:
        require(sha(snapshot / f['nombre']) == f['sha256'], f"Modelo distinto de R1: {f['nombre']}")
    return {**info, 'complete_current_cached_model_files': tree(snapshot)}


def run_worker(output, database, report, populate):
    env = dict(os.environ, CHROMA_PATH=str(database), HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1',
               ANONYMIZED_TELEMETRY='False', TOKENIZERS_PARALLELISM='false', PYTHONUTF8='1')
    # No copia credenciales a registros. src.config puede leer .env, pero este
    # proceso no importa agentes, LLM, reputación, pipeline ni ejecuta un grafo.
    cmd = [sys.executable, '-m', 'src.experimentation.knowledge.rag_enriquecido',
           '_worker', '--output', str(output), '--report', str(report)]
    if populate:
        cmd.append('--populate')
    with report.with_suffix('.stdout.txt').open('w', encoding='utf-8') as stdout, \
         report.with_suffix('.stderr.txt').open('w', encoding='utf-8') as stderr:
        result = subprocess.run(cmd, cwd=ROOT, env=env, stdout=stdout, stderr=stderr, timeout=1200)
    require(result.returncode == 0, f"Validación hija falló; consultar {report.with_suffix('.stderr.txt')}")
    return read(report)


def populate(output):
    load_corpus(output)
    if (output / 'chroma_snapshot').exists():
        frozen = read(output / 'manifests/snapshot_congelado.json')
        require(frozen['status'] == 'frozen' and read(output / 'validation/validacion_poblado.json')['status'] == 'passed',
                'Snapshot existente sin validación completa')
        require(tree(output / 'chroma_snapshot') == frozen['files'], 'Snapshot existente modificado')
        require(sha(output / 'corpus/corpus_historico.jsonl') == frozen['corpus_sha256'], 'Corpus congelado modificado')
        print(canonical({'status': 'already_frozen_verified', 'version': VERSION,
                         'collections': frozen['collections'], 'new_documents': 0}))
        return
    before = protected()
    expected_seed = read(ROOT / 'experiments/knowledge/poblado_chroma_v2.json')['snapshot']['archivos']
    require(tree(SEED) == expected_seed, "La semilla estática no coincide byte a byte con R1–R3")
    r1_sources = read(ROOT / 'experiments/ejecucion' / REPETITIONS[0] / 'environment.json')['source_sha256']
    require(all(sha(ROOT / p) == h for p, h in r1_sources.items()), 'Código original distinto del registrado en R1')
    model = model_inventory()
    validation = output / 'validation'
    validation.mkdir(exist_ok=True)
    # No abrimos el origen con Chroma: una copia de archivos preserva todos
    # los vectores y parámetros de indexación exactamente, sin recalcular MITRE.
    with tempfile.TemporaryDirectory(prefix='rag_enriquecido_', dir=ROOT / 'tmp', ignore_cleanup_errors=True) as td:
        working = Path(td) / 'chroma'
        shutil.copytree(SEED, working)
        first = run_worker(output, working, validation / 'worker_poblado.json', True)
        require(first['retrieval']['status'] == 'passed', "Recuperación fallida: no congelar")
        # El hijo ya terminó: SQLite y los índices HNSW están cerrados.
        shutil.copytree(working, output / 'chroma_snapshot')
        snapshot_tree = tree(output / 'chroma_snapshot')
        restored = Path(td) / 'restored'
        shutil.copytree(output / 'chroma_snapshot', restored)
        require(tree(restored) == snapshot_tree, "Restauración no reproduce los bytes")
        second = run_worker(output, restored, validation / 'worker_restauracion.json', False)
        require(second['patterns'] == first['patterns'] and second['mitre_after'] == first['mitre_before'],
                "Snapshot restaurado no preserva el contenido")
    require(protected() == before, "Fuentes o archivos protegidos modificados")
    require(tree(output / 'chroma_snapshot') == snapshot_tree, "Snapshot modificado por validación")
    write(validation / 'pruebas_recuperacion.json', first.pop('retrieval'))
    write(validation / 'validacion_poblado.json', {**first,
        'snapshot_restored_and_tool_verified': True, 'protected_files_unchanged': True,
        'all_original_source_hashes_match_R1': True,
        'seed_files_match_R1_R3': True, 'seed_tree_sha256': digest(expected_seed),
        'embedding_inventory': model, 'production_db_opened': False, 'llm_calls': 0,
        'runtime_code_changes': [], 'snapshot_files': snapshot_tree, 'snapshot_tree_sha256': digest(snapshot_tree)})
    write(output / 'manifests/snapshot_congelado.json', {
        'version': VERSION, 'status': 'frozen', 'created_utc': datetime.now(timezone.utc).isoformat(),
        'files': snapshot_tree, 'tree_sha256': digest(snapshot_tree),
        'collections': first['documents_after'], 'embedding_dimension': 384,
        'embedding_revision': model['revision'], 'restore_requires_new_copy_per_case': True,
        'corpus_sha256': sha(output / 'corpus/corpus_historico.jsonl'),
        'script_sha256': sha(Path(__file__)), 'protected_inventory_sha256': digest(before)})
    print(canonical({'status': 'frozen', 'version': VERSION, 'collections': first['documents_after'],
                     'snapshot_tree_sha256': digest(snapshot_tree)}))


def restore(output, destination):
    frozen = read(output / 'manifests/snapshot_congelado.json')
    require(frozen['status'] == 'frozen', "Snapshot no congelado")
    require(tree(output / 'chroma_snapshot') == frozen['files'], "Hash del snapshot incorrecto")
    require(inside(destination, ROOT / 'experiments') or inside(destination, ROOT / 'tmp'),
            "La restauración debe quedar en experiments/ o tmp/ del repositorio")
    require(not inside(destination, output), "No restaurar dentro del corpus congelado")
    require(not destination.exists(), "El destino ya existe: restauración no destructiva rechazada")
    require(not inside(destination, SEED), "No escribir dentro de la semilla estática")
    shutil.copytree(output / 'chroma_snapshot', destination)
    require(tree(destination) == frozen['files'], "La copia restaurada difiere del snapshot")
    print(canonical({'status': 'restored', 'destination': str(destination),
                     'CHROMA_PATH': str(destination.resolve()), 'snapshot_tree_sha256': frozen['tree_sha256']}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=('construir', 'poblar', 'restaurar', '_worker'))
    parser.add_argument('--output', type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument('--csv-work', type=Path, default=ROOT / 'tmp/rag-source-csv')
    parser.add_argument('--destino', type=Path)
    parser.add_argument('--report', type=Path)
    parser.add_argument('--populate', action='store_true')
    args = parser.parse_args()
    output = args.output.resolve()
    require(inside(output, ROOT / 'experiments/knowledge') and output != SEED.resolve(), "Destino del corpus fuera de experiments/knowledge")
    if args.stage == 'construir':
        require(inside(args.csv_work, ROOT / 'tmp'), "CSV temporales fuera de tmp/")
        prepare(output, args.csv_work.resolve())
    elif args.stage == 'poblar':
        populate(output)
    elif args.stage == 'restaurar':
        require(args.destino is not None, 'Falta --destino')
        restore(output, args.destino.resolve())
    else:
        require(args.report is not None and inside(args.report, output / 'validation'), 'Informe hijo fuera de validation/')
        worker(output, args.report, args.populate)


if __name__ == '__main__':
    main()
