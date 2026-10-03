"""Driver de preparación de casos (Fase 2).

Transforma datos: lee los logs, agrupa, particiona y escribe los casos y
sus referencias. **No ejecuta ninguna arquitectura, ni NODEX, ni el agente
único, ni el baseline, ni llama a ningún modelo.** Tampoco importa
`src.pipeline`: validar los casos a través del preprocesamiento de NODEX
es una acción que requiere autorización aparte.

Los presupuestos de casos no son arbitrarios: están acotados por cuántos
grupos disjuntos existen, porque ningún grupo se reutiliza. El cálculo que
los justifica está en `PRESUPUESTOS`.
"""

from __future__ import annotations

import json
import zlib
from pathlib import Path

from src.experimentation.contracts import PROTOCOLO_VERSION
from src.experimentation.datasets.agrupacion import (
    TAMANO_VENTANA_BGL,
    agrupar_bgl,
    agrupar_hdfs,
)
from src.experimentation.datasets.generador import (
    EspecificacionCasos,
    escribir_generacion,
    generar_campana,
)
from src.experimentation.datasets.inventario import inventariar_fuentes
from src.experimentation.datasets.particion import (
    SEMILLA_PARTICION,
    particionar_grupos,
    resumen_particion,
)

#: Prevalencias naturales, medidas sobre la unidad de agrupación de cada
#: dataset. **Dependen de la unidad**: la de BGL (0,28) es la fracción de
#: ventanas de 20 líneas que contienen al menos una alerta, no la fracción
#: de líneas de alerta (0,0715). Cambiar `TAMANO_VENTANA_BGL` la cambia.
PREVALENCIA_NATURAL = {
    "hdfs": 0.0346,   # 69 de 1994 componentes
    "bgl": 0.2800,    # 28 de 100 ventanas de 20 líneas
}

#: Presupuesto de casos por dataset, partición y condición.
#:
#: Está limitado por los grupos disjuntos disponibles tras la partición
#: 30/70, porque un grupo entra en un caso como máximo y las dos
#: condiciones tampoco comparten grupos:
#:
#:   HDFS  1994 grupos (69+) -> desarrollo 21+/578-  evaluación 48+/1347-
#:   BGL    100 grupos (28+) -> desarrollo  8+/ 22-  evaluación 20+/  50-
#:
#: La condición natural va primero porque es la que más grupos negativos
#: consume y la que no se puede recortar sin volverse no informativa.
PRESUPUESTOS: dict[str, dict[str, list[dict]]] = {
    "hdfs": {
        "desarrollo": [
            {"condicion": "natural", "n_casos": 30, "grupos_por_caso": 10},
            {"condicion": "balanceado", "n_casos": 16, "grupos_por_caso": 10},
        ],
        "evaluacion": [
            {"condicion": "natural", "n_casos": 60, "grupos_por_caso": 10},
            {"condicion": "balanceado", "n_casos": 40, "grupos_por_caso": 10},
        ],
    },
    "bgl": {
        "desarrollo": [
            {"condicion": "natural", "n_casos": 20, "grupos_por_caso": 1},
            {"condicion": "balanceado", "n_casos": 4, "grupos_por_caso": 1},
        ],
        "evaluacion": [
            {"condicion": "natural", "n_casos": 50, "grupos_por_caso": 1},
            {"condicion": "balanceado", "n_casos": 12, "grupos_por_caso": 1},
        ],
    },
}

#: Prevalencia solicitada de la condición balanceada.
PREVALENCIA_BALANCEADA = 0.50

#: HDFS y BGL etiquetan anomalías DE SISTEMA, no ataques: la pregunta es
#: operativa y el veredicto que corresponde leer es `hay_anomalia`.
TIPO_DETECCION = {"hdfs": "operativa", "bgl": "operativa"}


def _especificaciones(dataset: str, particion: str) -> list[EspecificacionCasos]:
    especificaciones = []
    for entrada in PRESUPUESTOS[dataset][particion]:
        prevalencia = (
            PREVALENCIA_BALANCEADA
            if entrada["condicion"] == "balanceado"
            else PREVALENCIA_NATURAL[dataset]
        )
        especificaciones.append(
            EspecificacionCasos(
                dataset=dataset,
                tipo_deteccion=TIPO_DETECCION[dataset],
                particion=particion,
                condicion=entrada["condicion"],
                n_casos=entrada["n_casos"],
                grupos_por_caso=entrada["grupos_por_caso"],
                prevalencia_solicitada=prevalencia,
                # La semilla se deriva de la partición y la condición para
                # que cada una sea reproducible por separado y agregar una
                # condición no reordene las demás.
                #
                # Se usa `crc32` y NO `hash()`: el hash de un str en Python
                # cambia entre procesos por `PYTHONHASHSEED`, así que una
                # semilla derivada de `hash()` daría casos distintos en cada
                # corrida y la generación no sería reproducible.
                semilla=SEMILLA_PARTICION
                + zlib.crc32(f"{particion}|{entrada['condicion']}".encode()) % 1000,
            )
        )
    return especificaciones


def preparar_dataset(dataset: str, raiz_repo: Path, raiz_experimentos: Path) -> dict:
    """Prepara un dataset completo y devuelve su manifiesto."""
    if dataset == "hdfs":
        grupos = agrupar_hdfs(
            raiz_repo / "data/logs/HDFS_2k.log",
            raiz_repo / "data/labels/hdfs_anomaly_label_2k.csv",
        )
        parametros_agrupacion = {"unidad": "componente_conexo_bloque_linea"}
    elif dataset == "bgl":
        grupos = agrupar_bgl(raiz_repo / "data/logs/BGL_2k.log")
        parametros_agrupacion = {
            "unidad": "ventana_contigua_disjunta",
            "tamano_ventana": TAMANO_VENTANA_BGL,
        }
    else:
        raise ValueError(
            f"dataset {dataset!r} no preparable acá: UWF requiere un motor "
            "Parquet y vive en uwf.py"
        )

    reparto = particionar_grupos(grupos)
    manifiesto = {
        "dataset": dataset,
        "protocolo_version": PROTOCOLO_VERSION,
        "tipo_deteccion": TIPO_DETECCION[dataset],
        "agrupacion": parametros_agrupacion
        | {
            "n_grupos": len(grupos),
            "n_grupos_positivos": sum(1 for g in grupos if g.es_positivo),
            "prevalencia_natural_de_grupos": round(
                sum(1 for g in grupos if g.es_positivo) / len(grupos), 6
            ),
            "grupos_con_varios_miembros": sum(
                1 for g in grupos if len(g.miembros) > 1
            ),
        },
        "particion": {
            "proporcion_desarrollo": 0.30,
            "semilla": SEMILLA_PARTICION,
            "estratificada_por": "es_positivo",
            "resumen": resumen_particion(reparto),
        },
        "condiciones": {},
    }

    for particion, grupos_particion in reparto.items():
        resultados = generar_campana(
            grupos_particion, _especificaciones(dataset, particion)
        )
        manifiesto["condiciones"][particion] = {
            condicion: escribir_generacion(resultado, raiz_experimentos)
            for condicion, resultado in resultados.items()
        }
    return manifiesto


def main(raiz_repo: Path, raiz_experimentos: Path) -> None:
    raiz_experimentos.mkdir(parents=True, exist_ok=True)
    dir_manifiestos = raiz_experimentos / "manifests"
    dir_manifiestos.mkdir(parents=True, exist_ok=True)

    inventario = inventariar_fuentes(raiz_repo)
    (dir_manifiestos / "inventario_fuentes.json").write_text(
        json.dumps(inventario, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    for dataset in ("hdfs", "bgl"):
        manifiesto = preparar_dataset(dataset, raiz_repo, raiz_experimentos)
        manifiesto["inventario_fuentes"] = {
            clave: valor
            for clave, valor in inventario.items()
            if clave.startswith(dataset)
        }
        (dir_manifiestos / f"{dataset}.json").write_text(
            json.dumps(manifiesto, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"{dataset}: manifiesto escrito")
        for particion, condiciones in manifiesto["condiciones"].items():
            for condicion, detalle in condiciones.items():
                prevalencia = detalle["prevalencia_efectiva"]
                print(
                    f"  {particion:<11} {condicion:<11} "
                    f"n={detalle['n_casos']:<4} "
                    f"solicitada={prevalencia['solicitada']:.4f} "
                    f"efectiva={prevalencia['efectiva']:.4f} "
                    f"delta={prevalencia['delta_por_redondeo']:+.4f}"
                )


if __name__ == "__main__":
    raiz = Path(__file__).resolve().parents[3]
    main(raiz, raiz / "experiments")
