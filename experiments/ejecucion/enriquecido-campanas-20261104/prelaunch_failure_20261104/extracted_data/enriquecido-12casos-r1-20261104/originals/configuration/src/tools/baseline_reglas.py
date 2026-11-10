"""Baseline determinístico de reglas (Fase 13 del plan; §9 del informe).

El informe compromete una comparación del sistema multiagente **contra un
baseline de reglas**. Sin ese punto de referencia, un F1 de 0,80 no dice
nada: puede ser excelente o puede ser peor que contar líneas con `grep`.

Este módulo implementa ese baseline. Clasifica un lote como anómalo o
normal usando solo el resumen determinístico del preprocesamiento, sin
LLM, sin memoria y sin consultas externas. Es deliberadamente simple: la
pregunta que responde es "¿cuánto aporta el razonamiento del multiagente
por encima de unas reglas evidentes?".

Reglas, en orden de evaluación:

1. Si algún evento declara severidad grave (FATAL/ERROR/CRITICAL), el lote
   es anómalo.
2. Si la proporción de eventos con resultado fallido supera un umbral, el
   lote es anómalo.
3. Si una sola IP concentra más de N intentos fallidos, el lote es anómalo
   (la firma clásica de fuerza bruta).
4. En cualquier otro caso, normal.

**Ninguna regla mira el ground truth.** Se alimentan del mismo resumen que
recibe el detector, que es lo que hace la comparación honesta.
"""

import argparse
import json
import time
from pathlib import Path

from src.tools.provenance import commit_git, procedencia_archivos, procedencia_ejecucion

# Severidades que el propio log declara como graves.
SEVERIDADES_GRAVES = {"fatal", "error", "critical", "crit", "severe", "emerg",
                      "alert", "panic"}

# Proporción de eventos fallidos a partir de la cual el lote se declara
# anómalo. 0.10 es deliberadamente laxo: un baseline debe ser fácil de
# superar, no un rival optimizado.
UMBRAL_PROPORCION_FALLIDOS = 0.10

# Intentos fallidos concentrados en una sola IP.
UMBRAL_FALLIDOS_POR_IP = 5


def clasificar(resumen_v1: dict, metadatos_v2: dict | None = None) -> dict:
    """Clasifica un lote. Devuelve el veredicto y la regla que lo disparó.

    `resumen_v1` es el resumen que consume el grafo; `metadatos_v2` los del
    preprocesamiento nuevo, opcionales. Devolver la regla que decidió
    permite explicar cada predicción en el informe, igual que se hace con
    la justificación del auditor.
    """
    metadatos_v2 = metadatos_v2 or {}

    severidades = metadatos_v2.get("severity_distribution") or {}
    graves = sum(n for s, n in severidades.items()
                 if str(s).strip().lower() in SEVERIDADES_GRAVES)
    if graves:
        return {"prediccion": "anomalo", "regla": "severidad_grave",
                "detalle": f"{graves} evento(s) con severidad grave declarada"}

    eventos = resumen_v1.get("eventos") or {}
    total = sum(eventos.values()) or resumen_v1.get("total_lineas") or 0
    criticos = eventos.get("evento_critico", 0) + eventos.get("acceso_fallido", 0)
    if total and criticos / total > UMBRAL_PROPORCION_FALLIDOS:
        return {"prediccion": "anomalo", "regla": "proporcion_fallidos",
                "detalle": f"{criticos}/{total} eventos fallidos "
                           f"({criticos / total:.0%} > "
                           f"{UMBRAL_PROPORCION_FALLIDOS:.0%})"}

    por_ip = resumen_v1.get("por_ip") or {}
    for ip, datos in por_ip.items():
        fallidos = datos.get("intentos_fallidos", 0)
        if fallidos > UMBRAL_FALLIDOS_POR_IP:
            return {"prediccion": "anomalo", "regla": "concentracion_por_ip",
                    "detalle": f"{ip} acumula {fallidos} intentos fallidos"}

    return {"prediccion": "normal", "regla": "ninguna",
            "detalle": "ninguna regla se disparó"}


def clasificar_texto(raw_logs: str) -> dict:
    """Clasifica un lote a partir de su texto crudo.

    `preprocesar()` corre UNA sola vez (`preprocesar_lote()`): antes este
    módulo agregaba el lote con `aggregate_logs()` y volvía a preprocesarlo
    aparte para los metadatos v2, dos parseos completos del mismo raw
    (hallazgo A1 de la auditoría del 23-sep-2026). Ya no hay un try/except
    alrededor del cálculo de metadatos: antes protegía contra un fallo en
    ese segundo parseo independiente, pero con una sola pasada un fallo del
    preprocesamiento le impide al baseline clasificar de cualquier forma, no
    solo perder los metadatos -- degradarlo en silencio ocultaría el error.
    """
    from src.tools.aggregation import preprocesar_lote

    _resultado, metadatos, resumen = preprocesar_lote(raw_logs)
    return clasificar(resumen, metadatos)


def _commit_git() -> str | None:
    """Hash del commit sobre el que corrió el baseline, o `None` si no se
    pudo obtener (p. ej. corriendo fuera de un checkout de git). `None` en
    vez de lanzar: la corrida ya generó resultados reales y no debe
    perderlos por no poder identificar el commit."""
    return commit_git(Path(__file__).resolve().parents[2])


def _procedencia() -> dict:
    """Motor, versión de esquema, configuración y commit (M5, Fase 4 del
    cierre de auditoría, 23-sep-2026): sin esto, dos archivos de
    `results/` con umbrales o código distintos parecían comparables sin
    serlo -- `eval_deteccion.py` ya registraba motor/configuración desde
    la Fase 11 del plan original; al baseline le faltaba, y a los dos les
    faltaba el commit."""
    return procedencia_ejecucion(Path(__file__).resolve().parents[2])


def _main() -> None:
    parser = argparse.ArgumentParser(
        description="Baseline determinístico de reglas para comparar contra "
                    "el sistema multiagente (§9 del informe). No usa LLM.")
    parser.add_argument("--dataset", choices=("bgl", "hdfs"), required=True)
    parser.add_argument("--n-lotes", type=int, default=20)
    parser.add_argument("--lineas-por-lote", type=int, default=120)
    parser.add_argument("--labels", default=None,
                        help="CSV de etiquetas (obligatorio para hdfs)")
    parser.add_argument("--prop-positivos", type=float, default=0.5)
    parser.add_argument("--no-guardar", action="store_true")
    args = parser.parse_args()

    from src.tools.eval_deteccion import (
        _construir_lotes_bgl,
        _construir_lotes_hdfs,
        _metricas,
    )

    raiz = Path(__file__).resolve().parents[2]
    if args.dataset == "bgl":
        dataset_paths = [raiz / "data" / "logs" / "BGL_2k.log"]
        lotes = _construir_lotes_bgl(dataset_paths[0],
                                     args.n_lotes, args.lineas_por_lote)
    else:
        if not args.labels:
            parser.error("hdfs requiere --labels")
        dataset_paths = [
            raiz / "data" / "logs" / "HDFS_2k.log",
            Path(args.labels),
        ]
        lotes = _construir_lotes_hdfs(
            dataset_paths[0], dataset_paths[1],
            args.n_lotes, args.lineas_por_lote, args.prop_positivos)

    print(f"Baseline de reglas sobre {len(lotes)} lotes de "
          f"{args.dataset.upper()} "
          f"({sum(1 for l in lotes if l['ground_truth'] == 'anomalo')} positivos)...")

    resultados = []
    t0 = time.perf_counter()
    for i, lote in enumerate(lotes, 1):
        veredicto = clasificar_texto(lote["texto"])
        acierto = veredicto["prediccion"] == lote["ground_truth"]
        print(f"[{i}/{len(lotes)}] {lote['id'][:34]:34} gt={lote['ground_truth']:8} "
              f"pred={veredicto['prediccion']:8} regla={veredicto['regla']:22} "
              f"{'acierto' if acierto else 'ERROR'}")
        resultados.append({
            "id": lote["id"],
            "ground_truth": lote["ground_truth"],
            "prediccion": veredicto["prediccion"],
            "regla": veredicto["regla"],
            "detalle": veredicto["detalle"],
        })
    duracion = time.perf_counter() - t0

    m = _metricas(resultados)
    print("=" * 60)
    print(f"Precisión={m['precision']}  Recall={m['recall']}  F1={m['f1']}")
    print(f"TP={m['tp']}  FP={m['fp']}  FN={m['fn']}  TN={m['tn']}")
    print(f"Tiempo total: {duracion:.2f}s ({duracion / len(lotes):.3f}s por lote), "
          f"0 llamadas al LLM, costo USD 0.")

    if not args.no_guardar:
        destino = raiz / "results" / f"baseline_reglas_{args.dataset}_{int(time.time())}.json"
        destino.parent.mkdir(exist_ok=True)
        with open(destino, "w", encoding="utf-8") as f:
            json.dump({
                "baseline": "reglas_deterministicas",
                "dataset": args.dataset,
                "n_lotes": len(lotes),
                "lineas_por_lote": args.lineas_por_lote,
                "prop_positivos": args.prop_positivos if args.dataset == "hdfs" else None,
                "umbrales": {
                    "proporcion_fallidos": UMBRAL_PROPORCION_FALLIDOS,
                    "fallidos_por_ip": UMBRAL_FALLIDOS_POR_IP,
                },
                **_procedencia(),
                "dataset_provenance": procedencia_archivos(dataset_paths, raiz),
                "evaluation_status": "complete",
                "duracion_seg": round(duracion, 3),
                "llamadas_llm": 0,
                "metricas": m,
                "resultados": resultados,
            }, f, ensure_ascii=False, indent=2)
        print(f"Guardado en {destino}")


if __name__ == "__main__":
    _main()
