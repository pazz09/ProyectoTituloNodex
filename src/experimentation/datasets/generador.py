"""Armado de casos a partir de grupos, con prevalencia auditable.

Tres reglas que corrigen defectos medidos del generador anterior:

1. **Ningún grupo se reutiliza.** Cada grupo entra en un caso como máximo.
   El generador anterior reutilizaba los bloques normales entre lotes, así
   que el mismo dato pesaba varias veces en la métrica.

2. **No se fuerza un positivo por caso.** `n_positivos = round(n_casos ·
   prevalencia)`, sin `max(1, ...)`. Con 16 lotes y prevalencia 0,031 el
   generador anterior producía 1 positivo, es decir 0,0625 efectivo, y el
   informe citaba 0,031.

3. **La prevalencia efectiva se registra aparte de la solicitada.** Si el
   redondeo las separa, el manifiesto muestra las dos y la diferencia.

Y una regla de separación: `TestCase` y `GroundTruth` se escriben en
directorios distintos y nunca en el mismo archivo.
"""

from __future__ import annotations

import json
import random
from dataclasses import asdict, dataclass, field
from pathlib import Path

from src.experimentation.contracts import PROTOCOLO_VERSION
from src.experimentation.contracts.casos import (
    GroundTruth,
    RegistroProcedencia,
    TestCase,
)
from src.experimentation.contracts.enums import CAMPO_VEREDICTO_POR_TIPO
from src.experimentation.datasets.agrupacion import GrupoDataset

#: Dimensiones aplicables por dataset, y por qué.
#:
#: HDFS y BGL no traen identificador estable de evento ni etiquetas ATT&CK,
#: así que reconstrucción y MITRE quedan `no_aplica` **por diseño**: el plan
#: prohíbe declarar una dimensión y después puntuarla contra una referencia
#: inventada.
DIMENSIONES_POR_DATASET: dict[str, tuple[str, ...]] = {
    "hdfs": ("deteccion", "reporte", "consumo"),
    "bgl": ("deteccion", "reporte", "consumo"),
    "uwf": ("deteccion", "reconstruccion", "mitre", "reporte", "consumo"),
}

#: Estado inicial de cada dimensión al generar el caso. `reporte` nace
#: `referencia_pendiente` porque la rúbrica humana todavía no se aplicó
#: (Fase 3); `consumo` es `evaluable` porque se mide con telemetría y no
#: necesita referencia.
_ESTADO_INICIAL = {
    "deteccion": "evaluable",
    "reconstruccion": "referencia_pendiente",
    "mitre": "referencia_pendiente",
    "reporte": "referencia_pendiente",
    "consumo": "evaluable",
}

#: Extensión del archivo de caso por dataset. Define con qué decoder lo va
#: a leer el preprocesamiento de NODEX.
_EXTENSION = {"hdfs": "log", "bgl": "log", "uwf": "csv"}


@dataclass(frozen=True)
class EspecificacionCasos:
    """Qué casos se piden. Todo lo de acá va al manifiesto."""

    dataset: str
    tipo_deteccion: str
    particion: str
    #: Nombre de la condición experimental (`balanceado`, `natural`). Entra
    #: en el `case_id` para que dos condiciones no colisionen, y permite
    #: reportar las métricas por condición en vez de promediarlas, que
    #: mezclaría prevalencias distintas en un solo número.
    condicion: str
    n_casos: int
    grupos_por_caso: int
    prevalencia_solicitada: float
    semilla: int

    def __post_init__(self) -> None:
        if not self.condicion:
            raise ValueError("condicion no puede estar vacía")
        if self.n_casos < 1:
            raise ValueError(f"n_casos debe ser >= 1; es {self.n_casos}")
        if self.grupos_por_caso < 1:
            raise ValueError(
                f"grupos_por_caso debe ser >= 1; es {self.grupos_por_caso}"
            )
        if not 0.0 <= self.prevalencia_solicitada <= 1.0:
            raise ValueError(
                "prevalencia_solicitada debe estar en [0,1]; es "
                f"{self.prevalencia_solicitada}"
            )

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ResultadoGeneracion:
    especificacion: EspecificacionCasos
    casos: list[TestCase] = field(default_factory=list)
    referencias: list[GroundTruth] = field(default_factory=list)
    #: Prevalencia realmente obtenida y los conteos que la sustentan.
    prevalencia_efectiva: dict = field(default_factory=dict)
    #: Grupos que quedaron sin usar, por si hace falta ampliar los casos.
    grupos_sobrantes: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "especificacion": self.especificacion.to_dict(),
            "protocolo_version": PROTOCOLO_VERSION,
            "campo_veredicto": CAMPO_VEREDICTO_POR_TIPO[
                self.especificacion.tipo_deteccion
            ],
            "n_casos": len(self.casos),
            "prevalencia_efectiva": self.prevalencia_efectiva,
            "grupos_sobrantes": self.grupos_sobrantes,
            "dimensiones_aplicables": list(
                DIMENSIONES_POR_DATASET[self.especificacion.dataset]
            ),
            "case_ids": [c.case_id for c in self.casos],
        }


def generar_casos(
    grupos: list[GrupoDataset], especificacion: EspecificacionCasos
) -> ResultadoGeneracion:
    """Arma los casos de una partición, sin reutilizar ningún grupo.

    Un caso positivo lleva exactamente un grupo positivo; el resto de sus
    grupos son negativos. Mantenerlo en uno hace que la prevalencia de
    casos sea interpretable: un caso positivo es "hay al menos una anomalía
    acá dentro", que es justo lo que el veredicto binario afirma.
    """
    espec = especificacion
    positivos = sorted((g for g in grupos if g.es_positivo), key=lambda g: g.grupo)
    negativos = sorted((g for g in grupos if not g.es_positivo), key=lambda g: g.grupo)

    # Sin `max(1, ...)`: si el redondeo da 0, el lote no lleva positivos y
    # eso queda registrado, en vez de corregirse en silencio.
    n_positivos = round(espec.n_casos * espec.prevalencia_solicitada)
    n_negativos_caso = espec.grupos_por_caso - 1
    requiere_negativos = (
        n_positivos * n_negativos_caso
        + (espec.n_casos - n_positivos) * espec.grupos_por_caso
    )
    if n_positivos > len(positivos):
        raise ValueError(
            f"se necesitan {n_positivos} grupos positivos y hay "
            f"{len(positivos)} en la partición {espec.particion!r}: reducir "
            "n_casos o la prevalencia, no reutilizar grupos"
        )
    if requiere_negativos > len(negativos):
        raise ValueError(
            f"se necesitan {requiere_negativos} grupos negativos y hay "
            f"{len(negativos)} en la partición {espec.particion!r}: reducir "
            "n_casos o grupos_por_caso, no reutilizar grupos"
        )

    azar = random.Random(espec.semilla)
    azar.shuffle(positivos)
    azar.shuffle(negativos)
    cola_positivos = positivos[:n_positivos]
    cola_negativos = list(negativos)

    resultado = ResultadoGeneracion(especificacion=espec)
    for indice in range(espec.n_casos):
        es_positivo = indice < n_positivos
        del_caso: list[GrupoDataset] = []
        if es_positivo:
            del_caso.append(cola_positivos.pop())
        while len(del_caso) < espec.grupos_por_caso:
            del_caso.append(cola_negativos.pop())
        caso, referencia = _materializar(espec, indice, del_caso)
        resultado.casos.append(caso)
        resultado.referencias.append(referencia)

    n_casos_positivos = sum(1 for r in resultado.referencias
                            if r.etiqueta_deteccion == "anomalo")
    resultado.prevalencia_efectiva = {
        "solicitada": espec.prevalencia_solicitada,
        "efectiva": round(n_casos_positivos / len(resultado.casos), 6),
        "n_casos": len(resultado.casos),
        "n_casos_positivos": n_casos_positivos,
        # Diferencia por redondeo. Si no es 0, la prevalencia que hay que
        # citar en el informe es la efectiva.
        "delta_por_redondeo": round(
            n_casos_positivos / len(resultado.casos) - espec.prevalencia_solicitada, 6
        ),
    }
    resultado.grupos_sobrantes = {
        "positivos": len(positivos) - n_positivos,
        "negativos": len(cola_negativos),
    }
    return resultado


def _materializar(
    espec: EspecificacionCasos, indice: int, grupos: list[GrupoDataset]
) -> tuple[TestCase, GroundTruth]:
    """Convierte un conjunto de grupos en un caso y su referencia."""
    case_id = (
        f"{espec.dataset}_{espec.particion[:3]}_{espec.condicion}_{indice:04d}"
    )

    # Las líneas se ordenan por su número original: el caso queda leyéndose
    # como un extracto del log, no como una lista barajada.
    lineas = sorted(
        ((g, l) for g in grupos for l in g.lineas),
        key=lambda par: par[1].linea_original,
    )
    contenido = "\n".join(l.contenido for _, l in lineas)
    procedencia = [
        RegistroProcedencia(
            indice_en_caso=posicion,
            archivo_origen=espec.dataset,
            linea_original=linea.linea_original,
            grupo=grupo.grupo,
            uid=linea.uid,
        )
        for posicion, (grupo, linea) in enumerate(lineas)
    ]

    positivos = [g for g in grupos if g.es_positivo]
    caso = TestCase(
        case_id=case_id,
        dataset=espec.dataset,
        tipo_deteccion=espec.tipo_deteccion,
        particion=espec.particion,
        contenido=contenido,
        dimensiones_aplicables=DIMENSIONES_POR_DATASET[espec.dataset],
        procedencia=procedencia,
        grupos=tuple(sorted(g.grupo for g in grupos)),
        notas={
            # Nada de esto revela la etiqueta: son tamaños y parámetros.
            "n_lineas": len(lineas),
            "n_grupos": len(grupos),
            "prevalencia_solicitada_del_lote": espec.prevalencia_solicitada,
            "semilla": espec.semilla,
            "protocolo_version": PROTOCOLO_VERSION,
        },
    )
    referencia = GroundTruth(
        case_id=case_id,
        estado_dimension={
            dimension: (
                _ESTADO_INICIAL[dimension]
                if dimension in DIMENSIONES_POR_DATASET[espec.dataset]
                else "no_aplica"
            )
            for dimension in _ESTADO_INICIAL
        },
        etiqueta_deteccion="anomalo" if positivos else "normal",
        etiqueta_original=(
            positivos[0].etiqueta_original if positivos else
            grupos[0].etiqueta_original
        ),
        anotacion={
            "fuente": "dataset",
            "regla": (
                "el caso es positivo si alguno de sus grupos lo es; el grupo "
                "es positivo según la regla documentada del dataset"
            ),
            "grupos_positivos": [g.grupo for g in positivos],
            "etiquetas_originales": sorted(
                {g.etiqueta_original for g in positivos}
            ),
            "aprobada": True,
        },
    )
    return caso, referencia


def generar_campana(
    grupos: list[GrupoDataset], especificaciones: list[EspecificacionCasos]
) -> dict[str, ResultadoGeneracion]:
    """Genera varias condiciones consumiendo el pool de grupos **una vez**.

    Las condiciones tampoco comparten grupos entre sí. Si la condición
    balanceada y la natural usaran los mismos datos, no serían dos
    mediciones independientes y una diferencia entre ellas podría venir del
    solapamiento y no de la prevalencia.
    """
    disponibles = list(grupos)
    resultados: dict[str, ResultadoGeneracion] = {}
    for espec in especificaciones:
        if espec.condicion in resultados:
            raise ValueError(f"condición repetida: {espec.condicion!r}")
        resultado = generar_casos(disponibles, espec)
        usados = {nombre for caso in resultado.casos for nombre in caso.grupos}
        disponibles = [g for g in disponibles if g.grupo not in usados]
        resultados[espec.condicion] = resultado
    return resultados


# --- escritura en disco ----------------------------------------------------

def escribir_generacion(
    resultado: ResultadoGeneracion, raiz_experimentos: Path
) -> dict:
    """Escribe casos, referencias y manifiesto en directorios separados.

    Los casos y las referencias NO comparten directorio: la separación
    física es parte del control contra fugas.
    """
    espec = resultado.especificacion
    extension = _EXTENSION[espec.dataset]
    dir_casos = raiz_experimentos / "cases" / espec.dataset / espec.particion
    dir_ref = raiz_experimentos / "ground_truth" / espec.dataset / espec.particion
    dir_casos.mkdir(parents=True, exist_ok=True)
    dir_ref.mkdir(parents=True, exist_ok=True)

    for caso in resultado.casos:
        # El contenido va a un archivo con la extensión del dataset, para
        # que el preprocesamiento lo detecte igual que un log real.
        (dir_casos / f"{caso.case_id}.{extension}").write_text(
            caso.contenido + "\n", encoding="utf-8"
        )
        meta = caso.to_dict()
        # El contenido ya está en el archivo de log: duplicarlo en el JSON
        # haría divergir las dos copias.
        meta.pop("contenido")
        meta["archivo_contenido"] = f"{caso.case_id}.{extension}"
        (dir_casos / f"{caso.case_id}.json").write_text(
            json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    for referencia in resultado.referencias:
        (dir_ref / f"{referencia.case_id}.json").write_text(
            json.dumps(referencia.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    return resultado.to_dict()
