"""Evaluación cuantitativa de detección (Precisión/Recall/F1) -- §8.6.2 del
Informe de Seminario ("Métricas de desempeño").

Corre el pipeline completo (`analizar_lote`) sobre varios LOTES de control,
cada uno con una etiqueta de verdad-terreno (ground truth) conocida --
"contiene una anomalía real" o "es tráfico normal" -- y compara el
veredicto del agente contra esa etiqueta para calcular Precisión,
Exhaustividad (Recall) y F1-Score, tal como especifica el informe.

**Corrección 1 (3-sep-2026, primera ronda)**: la primera versión de este
script usaba `confianza >= CONFIDENCE_THRESHOLD` como proxy de "el agente
detectó un incidente". Es un proxy incorrecto -- `confianza` mide qué tan
seguro está el auditor de SU PROPIO análisis, no la clasificación en sí.
Un diagnóstico de "todo normal" bien fundamentado da confianza alta, y ese
proxy lo contaba como "anómalo". Resultado real de la primera corrida
(4 lotes de BGL): precisión 0.25 / recall 1.00 -- exactamente lo que da un
clasificador que siempre predice "anómalo", sin importar la evidencia. Se
agregó `hay_incidente` como veredicto explícito del auditor, independiente
de `confianza` (ver `src/agents/agente_auditor_final.py`).

**Corrección 2 (3-sep-2026, segunda ronda, mismo día)**: con `hay_incidente`
ya funcionando, la corrida real sobre BGL dio recall 0.0 -- y el auditor
tenía razón: distinguió correctamente un problema de hardware/kernel real
("no constituye un incidente de seguridad, aunque sí una anomalía operativa
que requiere atención") de un ataque. El problema es de definiciones: BGL
(y HDFS) etiquetan cualquier anomalía de sistema, no solo las de seguridad
-- con la pregunta "¿hay un incidente de seguridad?", ambos datasets iban a
dar recall ≈0 de forma sistemática, sin importar qué tan bien razone el
modelo. Se agregó un segundo campo, `hay_anomalia` (¿el sistema se
comporta de forma anómala u operacionalmente irregular, sea o no un
problema de seguridad?), y este script ahora usa el campo que corresponde
a lo que cada dataset realmente etiqueta -- ver `CAMPO_VEREDICTO_POR_DATASET`
y `_prediccion_desde_estado`. BGL y HDFS son benchmarks de anomalías de
*sistema* (fallos de hardware, errores de replicación), no de seguridad;
el único dataset de la Tabla 8.11 con ground truth de seguridad real es
UWF-ZeekDataFall22 (trae tácticas MITRE), que usaría `hay_incidente`
cuando se implemente su adaptador.

Dos datasets, dos fuentes de ground truth distintas:

- **BGL**: el flag de alerta (primer token de cada línea, "-" = normal,
  cualquier otro valor = alerta real) YA ES el ground truth oficial del
  dataset (convención estándar de LogHub/BGL) -- no requiere ningún archivo
  externo. Los lotes son ventanas contiguas del archivo real; el ground
  truth del lote es "anomalo" si alguna línea de la ventana trae el flag
  de alerta.

  **Advertencia metodológica, no un bug**: `_BglAdapter` (`src/tools/aggregation.py`)
  lee ese mismo flag de alerta para calcular `evento_critico` ANTES de que
  el LLM vea nada -- la agregación determinística ya le entrega al modelo
  una señal derivada directamente del ground truth. Esta evaluación sobre
  BGL mide, en rigor, "¿el LLM transmite correctamente una señal que el
  parser ya calculó?", no "¿el sistema detecta anomalías de forma
  independiente?". Vale la pena citarlo así en el informe -- no invalida
  el resultado (el LLM igual podría ignorar o contradecir esa señal, y no
  lo hace, lo cual es información real), pero es una limitación real de lo
  que esta evaluación específica puede afirmar.

- **HDFS**: el ground truth es por BLOQUE (`block_id` -> Normal/Anomaly),
  no está en el archivo de logs en sí, y el parser (`_HdfsAdapter`) NO lo
  deriva de ahí (usa WARN/ERROR/FATAL como heurística de evento crítico,
  algo distinto e independiente del label real) -- por eso la evaluación
  sobre HDFS sí es independiente de lo que la agregación determinística ya
  sabe, a diferencia de BGL. Requiere `anomaly_label.csv`, el dataset
  canónico de ground truth para HDFS usado en la literatura (el mismo que
  citan varios papers del SLR de la Tabla 7.1, p. ej. el trabajo original
  de Loglizer/He et al.) -- ver `src/tools/preparar_labels_hdfs.py` para
  cómo conseguirlo y filtrarlo a los block_id de `HDFS_2k.log`. Los lotes
  mezclan un bloque real (etiquetado Anomaly o solo Normal) con bloques
  normales de relleno hasta el tamaño de lote pedido, preservando el orden
  original de las líneas en el archivo (las líneas de distintos bloques
  llegan intercaladas en un batch real, no agrupadas).

Uso:
    python -m src.tools.eval_deteccion --dataset bgl --n-lotes 20 --lineas-por-lote 120
    python -m src.tools.eval_deteccion --dataset hdfs --n-lotes 20 --lineas-por-lote 150 \\
        --labels data/labels/hdfs_anomaly_label_2k.csv

    # Segundo reporte con prevalencia REAL de HDFS (69/2200 ≈ 0.031), en vez
    # del balanceado 50/50 por defecto -- ver "prop_positivos" más abajo:
    python -m src.tools.eval_deteccion --dataset hdfs --n-lotes 20 --lineas-por-lote 150 \\
        --labels data/labels/hdfs_anomaly_label_2k.csv --prop-positivos 0.031

Cada corrida hace ~n-lotes llamadas reales y completas al pipeline (7 nodos
LLM por lote) -- gasta cuota/dinero real. Costo real medido (3-sep-2026,
4 lotes de BGL de ~120 líneas, modelo principal `gemini-3.1-pro-preview`):
USD 0.033/lote (16 llamadas LLM en total) -- el razonamiento es ~87% de
los tokens de salida. 20 lotes costarían ≈USD 0.66. Correr primero con
`--n-lotes` bajo (p. ej. 4) para confirmar el costo real de tu corrida
antes de escalar -- ver "Modelo LLM en la práctica" en el README para el
resto del detalle de costos.

**`--prop-positivos` (agregado 3-sep-2026, tercera ronda)**: por defecto,
los lotes de HDFS se arman balanceados 50/50 -- necesario con pocos lotes
para tener suficientes positivos y que precisión/recall no queden
indefinidos. Pero la prevalencia REAL de anomalías en `HDFS_2k.log` es
~3.1% (69/2200 block_id) -- una corrida balanceada sobreestima la
precisión que se vería con la tasa base real (con 3% de prevalencia, la
misma tasa de falsos positivos observada hundiría la precisión). Para el
informe conviene reportar ambas corridas: la balanceada (números estables,
buen recall) y una con `--prop-positivos 0.031` (representativa de
producción). No aplica a BGL, cuyos lotes ya son un muestreo al azar de
ventanas contiguas, sin balancear artificialmente.
"""

import argparse
import csv
import json
import random
import re
import time
from pathlib import Path

from src.config import CONFIDENCE_THRESHOLD
from src.pipeline import analizar_lote

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_DATA_DIR = _REPO_ROOT / "data" / "logs"
_RESULTS_DIR = _REPO_ROOT / "results"

# Qué campo del veredicto del auditor se compara contra el ground truth de
# cada dataset -- ver "Corrección 2" en el docstring del módulo. BGL/HDFS
# etiquetan anomalías de sistema (no necesariamente de seguridad), así que
# usan `hay_anomalia`; un dataset de seguridad real (p. ej. UWF, cuando se
# implemente) debe usar `hay_incidente`. Sin entrada explícita, se usa
# `hay_incidente` por defecto (más estricto -- mejor fallar mostrando 0
# incidentes que sobre-contar anomalías operativas como ataques).
CAMPO_VEREDICTO_POR_DATASET = {
    "bgl": "hay_anomalia",
    "hdfs": "hay_anomalia",
}

_BLOQUE_RE = re.compile(r"blk_-?\d+")


def _agrupar_por_bloque(lineas: list[str]) -> dict[str, list[str]]:
    """block_id -> lista de índices (no líneas) en las que aparece, para
    poder reconstruir después el orden original del archivo."""
    por_bloque: dict[str, list[int]] = {}
    for i, linea in enumerate(lineas):
        m = _BLOQUE_RE.search(linea)
        if not m:
            continue
        por_bloque.setdefault(m.group(0), []).append(i)
    return por_bloque


def _seleccionar_bloques_hasta(
    candidatos: list[str],
    conteo_lineas: dict[str, int],
    rng: random.Random,
    max_lineas: int,
    ya_incluidos: list[str] | None = None,
) -> list[str]:
    """Agrega bloques de `candidatos` (sin repetir) hasta que la suma de
    sus líneas alcance `max_lineas`, partiendo de `ya_incluidos`."""
    incluidos = list(ya_incluidos or [])
    total = sum(conteo_lineas[b] for b in incluidos)
    disponibles = [b for b in candidatos if b not in incluidos]
    rng.shuffle(disponibles)
    for b in disponibles:
        if total >= max_lineas:
            break
        incluidos.append(b)
        total += conteo_lineas[b]
    return incluidos


def _texto_por_bloques(lineas: list[str], por_bloque: dict[str, list[int]], bloques: list[str]) -> str:
    """Líneas de los bloques dados, en el orden ORIGINAL del archivo (no
    agrupadas por bloque) -- así el lote se parece a un batch real, donde
    las líneas de distintos bloques llegan intercaladas."""
    indices = sorted(i for b in bloques for i in por_bloque[b])
    return "\n".join(lineas[i] for i in indices)


def _construir_lotes_bgl(path: Path, n_lotes: int, lineas_por_lote: int) -> list[dict]:
    lineas = path.read_text(encoding="utf-8", errors="replace").splitlines()
    total_ventanas = len(lineas) // lineas_por_lote
    if total_ventanas == 0:
        raise ValueError(f"{path} tiene menos de {lineas_por_lote} líneas -- baja --lineas-por-lote")
    n_lotes = min(n_lotes, total_ventanas)
    indices = list(range(total_ventanas))
    random.Random(42).shuffle(indices)  # muestra aleatoria, pero reproducible (seed fija)
    elegidos = sorted(indices[:n_lotes])

    lotes = []
    for i in elegidos:
        ventana = lineas[i * lineas_por_lote:(i + 1) * lineas_por_lote]
        contiene_alerta = any(l.strip() and l.split(" ", 1)[0] != "-" for l in ventana)
        lotes.append({
            "id": f"bgl_ventana_{i:04d}",
            "texto": "\n".join(ventana),
            "ground_truth": "anomalo" if contiene_alerta else "normal",
        })
    return lotes


def _construir_lotes_hdfs(
    path: Path, labels_csv: Path, n_lotes: int, lineas_por_lote: int, prop_positivos: float = 0.5
) -> list[dict]:
    """`prop_positivos` (agregado 3-sep-2026, tercera ronda): fracción de
    los lotes que se arman con un bloque `Anomaly` real. Por defecto 0.5
    (balanceado 50/50) -- necesario con pocos lotes para tener suficientes
    casos positivos y que precisión/recall no queden indefinidos. Pero la
    prevalencia REAL de anomalías en HDFS_2k.log es ~3.1% (69/2200
    block_id) -- una corrida balanceada no es representativa de la tasa de
    falsos positivos que se vería en producción. Para un segundo reporte
    con prevalencia realista, pasar `prop_positivos=0.031` (o el valor que
    corresponda al dataset real que se esté usando)."""
    labels: dict[str, str] = {}
    with open(labels_csv, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            labels[row["BlockId"]] = row["Label"]  # "Normal" | "Anomaly"

    lineas = path.read_text(encoding="utf-8", errors="replace").splitlines()
    por_bloque = _agrupar_por_bloque(lineas)
    conteo = {b: len(idxs) for b, idxs in por_bloque.items()}

    anomalos = [b for b in por_bloque if labels.get(b) == "Anomaly"]
    normales = [b for b in por_bloque if labels.get(b) == "Normal"]
    if not anomalos:
        raise ValueError(
            f"Ningún block_id de {path.name} tiene label 'Anomaly' en {labels_csv} -- "
            "revisa que sea el archivo de labels correcto y que cubra estos block_id "
            "(ver docs/como_obtener_labels_hdfs.md)."
        )
    if not normales:
        raise ValueError(f"Ningún block_id de {path.name} tiene label 'Normal' en {labels_csv}.")

    rng = random.Random(42)
    rng.shuffle(anomalos)
    # Al menos 1 lote positivo si hay algún bloque Anomaly disponible y se
    # pidió al menos 1 lote -- con n_lotes chico (o prop_positivos baja),
    # redondear a 0 dejaría la evaluación sin ningún caso positivo, lo que
    # rompe recall.
    n_pos = min(max(1, round(n_lotes * prop_positivos)), len(anomalos), n_lotes)
    n_neg = n_lotes - n_pos

    lotes = []
    for i in range(n_pos):
        bloque_anomalo = anomalos[i]
        bloques = _seleccionar_bloques_hasta(
            normales, conteo, rng, lineas_por_lote, ya_incluidos=[bloque_anomalo]
        )
        lotes.append({
            "id": f"hdfs_positivo_{i:03d}_{bloque_anomalo}",
            "texto": _texto_por_bloques(lineas, por_bloque, bloques),
            "ground_truth": "anomalo",
        })
    for i in range(n_neg):
        bloques = _seleccionar_bloques_hasta(normales, conteo, rng, lineas_por_lote)
        lotes.append({
            "id": f"hdfs_negativo_{i:03d}",
            "texto": _texto_por_bloques(lineas, por_bloque, bloques),
            "ground_truth": "normal",
        })
    return lotes


def _metricas(resultados: list[dict]) -> dict:
    """`resultados`: lista de dicts con 'ground_truth' y 'prediccion',
    cada uno 'anomalo' o 'normal'. Positivo = 'anomalo' (§8.6.2: incidente
    confirmado)."""
    tp = sum(1 for r in resultados if r["ground_truth"] == "anomalo" and r["prediccion"] == "anomalo")
    fp = sum(1 for r in resultados if r["ground_truth"] == "normal" and r["prediccion"] == "anomalo")
    fn = sum(1 for r in resultados if r["ground_truth"] == "anomalo" and r["prediccion"] == "normal")
    tn = sum(1 for r in resultados if r["ground_truth"] == "normal" and r["prediccion"] == "normal")
    precision = (tp / (tp + fp)) if (tp + fp) else None
    recall = (tp / (tp + fn)) if (tp + fn) else None
    f1 = (2 * precision * recall / (precision + recall)) if (precision and recall and (precision + recall)) else None
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn, "precision": precision, "recall": recall, "f1": f1}


def _prediccion_desde_estado(estado: dict, confianza: float, campo: str = "hay_incidente") -> str:
    """La predicción del agente para efectos de Precisión/Recall/F1 viene
    del veredicto EXPLÍCITO del auditor en `campo` (ver
    `src/agents/agente_auditor_final.py`) -- no de `confianza`, y no
    siempre del mismo campo: qué campo usar depende de qué etiqueta el
    ground truth del dataset (ver `CAMPO_VEREDICTO_POR_DATASET`).

    Bug real encontrado el 3-sep-2026 (primera ronda): la primera versión
    de este script usaba `confianza >= CONFIDENCE_THRESHOLD` como proxy de
    "es anómalo". `confianza` mide la certeza del auditor sobre SU PROPIO
    análisis, no la clasificación -- un diagnóstico de "todo normal" bien
    fundamentado da confianza alta, y ese proxy lo contaba como "anómalo".
    Resultado en la corrida real: precisión 0.25 / recall 1.00 sobre 4
    lotes de BGL, exactamente lo que da un clasificador que predice
    "anómalo" siempre. `hay_incidente` se agregó al auditor específicamente
    para que esta evaluación mida lo que dice medir.

    Segundo hallazgo real el mismo día (segunda ronda): con `hay_incidente`
    ya en uso, BGL dio recall 0.0 -- el auditor distinguía correctamente
    anomalías operativas (hardware/kernel) de incidentes de seguridad, pero
    BGL/HDFS etiquetan cualquier anomalía de sistema, no solo las de
    seguridad. Se agregó `hay_anomalia` y el parámetro `campo` para que la
    evaluación compare contra la pregunta que el dataset realmente etiqueta.
    """
    valor = estado.get(campo)
    if not isinstance(valor, bool):
        # Estado de una corrida vieja (antes de que existiera el campo) o
        # el auditor no lo devolvió -- mismo respaldo que usa el nodo.
        print(f"   ⚠️ '{campo}' ausente en el estado -- usando confianza como respaldo.")
        valor = confianza >= CONFIDENCE_THRESHOLD
    return "anomalo" if valor else "normal"


def correr_evaluacion(
    dataset: str,
    n_lotes: int,
    lineas_por_lote: int,
    labels_csv: str | None = None,
    prop_positivos: float = 0.5,
) -> dict:
    if dataset == "bgl":
        if prop_positivos != 0.5:
            print("   ⚠️ --prop-positivos no aplica a BGL (los lotes son ventanas contiguas "
                  "muestreadas al azar, no se balancean artificialmente) -- se ignora.")
        lotes = _construir_lotes_bgl(_DATA_DIR / "BGL_2k.log", n_lotes, lineas_por_lote)
    elif dataset == "hdfs":
        if not labels_csv:
            raise ValueError("--labels es obligatorio para --dataset hdfs (ver docs/como_obtener_labels_hdfs.md)")
        lotes = _construir_lotes_hdfs(
            _DATA_DIR / "HDFS_2k.log", Path(labels_csv), n_lotes, lineas_por_lote, prop_positivos
        )
    else:
        raise ValueError(f"dataset desconocido: {dataset!r} (usa 'hdfs' o 'bgl')")

    campo_veredicto = CAMPO_VEREDICTO_POR_DATASET.get(dataset, "hay_incidente")
    print(f"Evaluando {len(lotes)} lotes de {dataset.upper()} "
          f"({sum(1 for l in lotes if l['ground_truth'] == 'anomalo')} positivos, "
          f"{sum(1 for l in lotes if l['ground_truth'] == 'normal')} negativos), "
          f"usando '{campo_veredicto}' como veredicto...")

    resultados = []
    for i, lote in enumerate(lotes):
        print(f"\n[{i + 1}/{len(lotes)}] {lote['id']} (ground truth: {lote['ground_truth']}) ...")
        t0 = time.time()
        estado = analizar_lote(lote["texto"], thread_id=f"eval_{lote['id']}")
        dt = time.time() - t0
        confianza = float(estado.get("confianza", 0) or 0)
        prediccion = _prediccion_desde_estado(estado, confianza, campo=campo_veredicto)
        n_comandos = len(estado.get("comandos_mitigacion") or [])
        acierto = prediccion == lote["ground_truth"]
        print(f"   hay_anomalia={estado.get('hay_anomalia')} hay_incidente={estado.get('hay_incidente')} "
              f"confianza={confianza:.2f} -> predicción={prediccion} "
              f"({'acierto' if acierto else 'ERROR'}, {dt:.1f}s)")
        resultados.append({
            "id": lote["id"],
            "ground_truth": lote["ground_truth"],
            "confianza": confianza,
            "hay_anomalia": estado.get("hay_anomalia"),
            "hay_incidente": estado.get("hay_incidente"),
            "prediccion": prediccion,
            "diagnostico": estado.get("diagnostico"),
            "evaluacion_auditor": estado.get("evaluacion_auditor"),
            "n_comandos_mitigacion": n_comandos,
            "duracion_seg": round(dt, 1),
        })

    metricas = _metricas(resultados)
    salida = {
        "dataset": dataset,
        "n_lotes": len(lotes),
        "lineas_por_lote": lineas_por_lote,
        "umbral_confianza": CONFIDENCE_THRESHOLD,
        "campo_veredicto": campo_veredicto,
        "prop_positivos": prop_positivos if dataset == "hdfs" else None,
        "metricas": metricas,
        "resultados": resultados,
    }
    _RESULTS_DIR.mkdir(exist_ok=True)
    destino = _RESULTS_DIR / f"eval_deteccion_{dataset}_{int(time.time())}.json"
    destino.write_text(json.dumps(salida, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n{'=' * 60}")
    print(f"Precisión={metricas['precision']}  Recall={metricas['recall']}  F1={metricas['f1']}")
    print(f"TP={metricas['tp']}  FP={metricas['fp']}  FN={metricas['fn']}  TN={metricas['tn']}")
    print(f"Guardado en {destino}")
    return salida


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dataset", choices=["hdfs", "bgl"], required=True)
    ap.add_argument("--n-lotes", type=int, default=20, help="Cantidad total de lotes a evaluar (default 20)")
    ap.add_argument("--lineas-por-lote", type=int, default=120, help="Tamaño aproximado de cada lote (default 120)")
    ap.add_argument("--labels", type=str, default=None, help="Ruta al CSV de labels (obligatorio para --dataset hdfs)")
    ap.add_argument(
        "--prop-positivos", type=float, default=0.5,
        help="Solo --dataset hdfs: fracción de lotes armados con un bloque Anomaly real "
             "(default 0.5, balanceado). La prevalencia real en HDFS_2k.log es ~0.031 "
             "(69/2200 block_id) -- pasar ese valor para un reporte con prevalencia realista.",
    )
    args = ap.parse_args()
    correr_evaluacion(args.dataset, args.n_lotes, args.lineas_por_lote, args.labels, args.prop_positivos)
