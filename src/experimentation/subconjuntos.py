"""Subconjuntos preseleccionados: piloto y submuestra de rúbrica.

Son dos cosas distintas y conviene no confundirlas:

- **Piloto** (Fase 3, acción 4): un conjunto chico para verificar que el
  pipeline funciona de punta a punta. Sale **solo de `desarrollo`**: un
  piloto que toque los casos de evaluación los quema, porque después de
  depurar contra ellos ya no son datos reservados.
- **Submuestra de rúbrica** (decisión D-6): los 12 casos por dataset
  principal cuyos reportes leerán dos evaluadores humanos. Sale de
  `evaluacion`, porque la calidad del reporte es un resultado que se
  informa.

Las dos selecciones se fijan **antes** de que exista cualquier resultado, y
con una semilla registrada. Es a propósito: elegir después qué reportes se
revisan, viendo ya cómo le fue al sistema, es cherry-picking aunque no haya
intención de hacerlo.

El criterio de estratificación es el veredicto esperado y la condición. No
hay fuga: la selección decide qué reportes lee un humano, y ninguna
arquitectura la ve.
"""

from __future__ import annotations

import json
import zlib
from dataclasses import asdict, dataclass
from pathlib import Path

from src.experimentation.contracts import PROTOCOLO_VERSION

SEMILLA_SUBCONJUNTOS = 20261004

#: Datasets principales de evaluación (decisión D-7). HDFS queda auxiliar y
#: por lo tanto fuera de la submuestra de rúbrica.
DATASETS_PRINCIPALES = ("bgl", "uwf")

#: Decisión D-6: 12 casos por dataset principal reciben la rúbrica humana.
CASOS_RUBRICA_POR_DATASET = 12

#: Casos de piloto por dataset y condición. 4 × 2 condiciones × 3 datasets
#: = 24 casos; con dos arquitecturas LLM son 48 corridas, que es un piloto
#: que se puede revisar a mano.
CASOS_PILOTO_POR_CONDICION = 4


@dataclass(frozen=True)
class CasoSeleccionado:
    case_id: str
    dataset: str
    particion: str
    condicion: str
    #: Veredicto de referencia. Se registra para poder auditar que la
    #: estratificación quedó como se declaró, no para dárselo a nadie.
    etiqueta_deteccion: str

    def to_dict(self) -> dict:
        return asdict(self)


def _cargar(raiz_experimentos: Path, dataset: str, particion: str) -> list[CasoSeleccionado]:
    """Lee los casos de una partición junto con su veredicto de referencia."""
    directorio = raiz_experimentos / "cases" / dataset / particion
    referencias = raiz_experimentos / "ground_truth" / dataset / particion
    casos = []
    for meta in sorted(directorio.glob("*.json")):
        datos = json.loads(meta.read_text(encoding="utf-8"))
        referencia = json.loads(
            (referencias / meta.name).read_text(encoding="utf-8")
        )
        # La condición está en el `case_id` (`uwf_eva_sigiloso_0003`) y
        # también en las notas de UWF; se lee del id para que valga para los
        # tres datasets.
        partes = datos["case_id"].split("_")
        casos.append(CasoSeleccionado(
            case_id=datos["case_id"],
            dataset=dataset,
            particion=particion,
            condicion=partes[2],
            etiqueta_deteccion=referencia["etiqueta_deteccion"],
        ))
    return casos


def _estratificar(
    casos: list[CasoSeleccionado], cuantos: int, semilla: int
) -> tuple[list[CasoSeleccionado], dict]:
    """Toma `cuantos` casos, mitad positivos y mitad negativos si alcanza.

    Si no hay suficientes de una clase, toma los que haya y **lo registra**
    en vez de completar con la otra en silencio. Pasa en HDFS natural de
    desarrollo, que tiene 1 positivo entre 30 casos.
    """
    import random

    positivos = sorted((c for c in casos if c.etiqueta_deteccion == "anomalo"),
                       key=lambda c: c.case_id)
    negativos = sorted((c for c in casos if c.etiqueta_deteccion == "normal"),
                       key=lambda c: c.case_id)
    azar = random.Random(semilla)
    azar.shuffle(positivos)
    azar.shuffle(negativos)

    objetivo_pos = cuantos // 2
    tomados_pos = positivos[:min(objetivo_pos, len(positivos))]
    # Lo que falte de positivos se completa con negativos, para no entregar
    # menos casos de los pedidos; la diferencia queda anotada.
    tomados_neg = negativos[:cuantos - len(tomados_pos)]
    seleccion = sorted(tomados_pos + tomados_neg, key=lambda c: c.case_id)

    detalle = {
        "solicitados": cuantos,
        "entregados": len(seleccion),
        "positivos": len(tomados_pos),
        "negativos": len(tomados_neg),
        "positivos_objetivo": objetivo_pos,
        "positivos_disponibles": len(positivos),
        "negativos_disponibles": len(negativos),
    }
    if len(tomados_pos) < objetivo_pos:
        detalle["advertencia"] = (
            f"se pedían {objetivo_pos} positivos y solo había "
            f"{len(positivos)}: la submuestra queda desbalanceada y su "
            "recall no es interpretable por separado"
        )
    return seleccion, detalle


def seleccionar_piloto(raiz_experimentos: Path) -> dict:
    """Piloto de verificación del pipeline, solo de `desarrollo`."""
    resultado: dict = {
        "proposito": (
            "verificar que el pipeline experimental funciona de punta a "
            "punta. NO produce métricas reportables"
        ),
        "particion": "desarrollo",
        "por_que_solo_desarrollo": (
            "depurar contra los casos de evaluación los deja de ser datos "
            "reservados"
        ),
        "semilla": SEMILLA_SUBCONJUNTOS,
        "protocolo_version": PROTOCOLO_VERSION,
        "datasets": {},
    }
    total = 0
    for dataset in ("hdfs", "bgl", "uwf"):
        casos = _cargar(raiz_experimentos, dataset, "desarrollo")
        por_condicion: dict = {}
        for condicion in sorted({c.condicion for c in casos}):
            del_grupo = [c for c in casos if c.condicion == condicion]
            semilla = SEMILLA_SUBCONJUNTOS + zlib.crc32(
                f"piloto|{dataset}|{condicion}".encode()
            ) % 10_000
            seleccion, detalle = _estratificar(
                del_grupo, CASOS_PILOTO_POR_CONDICION, semilla
            )
            total += len(seleccion)
            por_condicion[condicion] = {
                "composicion": detalle,
                "case_ids": [c.case_id for c in seleccion],
            }
        resultado["datasets"][dataset] = por_condicion
    resultado["n_casos"] = total
    resultado["costo_estimado"] = {
        "casos": total,
        "arquitecturas_llm": 2,
        "corridas_sin_repeticiones": total * 2,
        "nota": (
            "el baseline de reglas no consume LLM. El número de llamadas por "
            "corrida depende del grafo y se estima en la Fase 6, no acá"
        ),
    }
    return resultado


def seleccionar_rubrica(raiz_experimentos: Path) -> dict:
    """Submuestra de la rúbrica humana (D-6), de `evaluacion`."""
    resultado: dict = {
        "proposito": "evaluación humana de calidad del reporte (dimensión D4)",
        "decision": "D-6: 12 casos por dataset principal",
        "escala": "D-4: 0-3 por criterio, 2 evaluadores, concordancia reportada",
        "criterios": [
            "completitud",
            "correccion_factual",
            "coherencia_con_evidencia",
            "claridad",
            "informacion_no_sustentada",
        ],
        "particion": "evaluacion",
        "preseleccionada_antes_de_resultados": True,
        "por_que": (
            "elegir después qué reportes se revisan, viendo ya cómo le fue "
            "al sistema, sería cherry-picking"
        ),
        "semilla": SEMILLA_SUBCONJUNTOS,
        "protocolo_version": PROTOCOLO_VERSION,
        "datasets": {},
    }
    for dataset in DATASETS_PRINCIPALES:
        casos = _cargar(raiz_experimentos, dataset, "evaluacion")
        condiciones = sorted({c.condicion for c in casos})
        por_condicion = CASOS_RUBRICA_POR_DATASET // len(condiciones)
        detalle_dataset: dict = {}
        for condicion in condiciones:
            del_grupo = [c for c in casos if c.condicion == condicion]
            semilla = SEMILLA_SUBCONJUNTOS + zlib.crc32(
                f"rubrica|{dataset}|{condicion}".encode()
            ) % 10_000
            seleccion, detalle = _estratificar(del_grupo, por_condicion, semilla)
            detalle_dataset[condicion] = {
                "composicion": detalle,
                "case_ids": [c.case_id for c in seleccion],
            }
        resultado["datasets"][dataset] = detalle_dataset
    resultado["n_casos"] = sum(
        len(c["case_ids"])
        for d in resultado["datasets"].values()
        for c in d.values()
    )
    resultado["n_reportes_a_puntuar"] = (
        resultado["n_casos"] * 2  # dos arquitecturas LLM
    )
    resultado["nota_hdfs"] = (
        "HDFS queda fuera por la decisión D-7: es dataset auxiliar, no "
        "principal de evaluación"
    )
    return resultado


def main(raiz_repo: Path) -> None:
    raiz_experimentos = raiz_repo / "experiments"
    destino = raiz_experimentos / "subconjuntos"
    destino.mkdir(parents=True, exist_ok=True)

    piloto = seleccionar_piloto(raiz_experimentos)
    rubrica = seleccionar_rubrica(raiz_experimentos)
    (destino / "piloto.json").write_text(
        json.dumps(piloto, indent=2, ensure_ascii=False), encoding="utf-8")
    (destino / "rubrica.json").write_text(
        json.dumps(rubrica, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"piloto: {piloto['n_casos']} casos "
          f"({piloto['costo_estimado']['corridas_sin_repeticiones']} corridas "
          "con 2 arquitecturas LLM)")
    for dataset, condiciones in piloto["datasets"].items():
        for condicion, detalle in condiciones.items():
            c = detalle["composicion"]
            aviso = "  <-- " + c["advertencia"][:48] if "advertencia" in c else ""
            print(f"  {dataset:<5} {condicion:<11} {c['entregados']} casos "
                  f"({c['positivos']}+/{c['negativos']}-){aviso}")
    print(f"\nrúbrica: {rubrica['n_casos']} casos, "
          f"{rubrica['n_reportes_a_puntuar']} reportes a puntuar")
    for dataset, condiciones in rubrica["datasets"].items():
        for condicion, detalle in condiciones.items():
            c = detalle["composicion"]
            print(f"  {dataset:<5} {condicion:<11} {c['entregados']} casos "
                  f"({c['positivos']}+/{c['negativos']}-)")


if __name__ == "__main__":
    main(Path(__file__).resolve().parents[2])
