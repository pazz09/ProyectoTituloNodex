"""Identidad de cada corrida. Fase C del plan de continuación, §15.

Una corrida tiene que poder rastrearse de forma inequívoca hasta:

    case_id, dataset, architecture, run_number, config_version

El `run_id` lleva los cinco, más un sufijo derivado por hash. El sufijo no
es decorativo: sin él, dos corridas del mismo caso, arquitectura y
repetición colisionarían y una sobreescribiría a la otra. Con él, el nombre
depende también de la configuración, así que repetir la misma corrida bajo
otra configuración congelada produce otro artefacto en vez de pisar el
anterior.

El `run_id` es **determinístico**: las mismas cinco coordenadas dan siempre
el mismo identificador. Eso permite saber si una corrida ya existe sin
consultar un índice, y es lo que hace que la persistencia pueda negarse a
sobrescribir.
"""

from __future__ import annotations

import re
import zlib
from dataclasses import asdict, dataclass

from src.experimentation.contracts.enums import ARQUITECTURAS, DATASETS

#: Abreviatura de cada arquitectura dentro del `run_id`. Se usan nombres
#: cortos para que el identificador quepa en un nombre de archivo.
ABREVIATURA_ARQUITECTURA = {
    "nodex_multiagente": "nodex",
    "gemini_externo": "gemext",
    "agente_unico": "unico",
    "baseline_reglas": "reglas",
}

_RUN_ID = re.compile(
    r"^(?P<case_id>[a-z0-9_]+)__(?P<arquitectura>nodex|gemext|unico|reglas)"
    r"__r(?P<repeticion>\d+)__(?P<sufijo>[0-9a-f]{8})$"
)


@dataclass(frozen=True)
class IdentidadCorrida:
    """Las cinco coordenadas que identifican una corrida, más su `run_id`."""

    case_id: str
    dataset: str
    arquitectura: str
    repeticion: int
    config_version: str

    def __post_init__(self) -> None:
        if not self.case_id:
            raise ValueError("case_id no puede estar vacío")
        if self.dataset not in DATASETS:
            raise ValueError(
                f"dataset inválido: {self.dataset!r}. Admitidos: "
                f"{', '.join(DATASETS)}"
            )
        if self.arquitectura not in ARQUITECTURAS:
            raise ValueError(
                f"arquitectura inválida: {self.arquitectura!r}. Admitidas: "
                f"{', '.join(ARQUITECTURAS)}"
            )
        if self.repeticion < 1:
            raise ValueError(
                f"repeticion es 1-indexada; es {self.repeticion}"
            )
        if not self.config_version:
            raise ValueError(
                "config_version no puede estar vacía: un resultado sin "
                "configuración declarada no es reproducible"
            )

    @property
    def sufijo(self) -> str:
        """Ocho hexadecimales derivados de las cinco coordenadas.

        Se usa `crc32` y no `hash()`: el hash de un str varía entre procesos
        por PYTHONHASHSEED y el `run_id` dejaría de ser estable.
        """
        semilla = "|".join([
            self.case_id, self.dataset, self.arquitectura,
            str(self.repeticion), self.config_version,
        ])
        return f"{zlib.crc32(semilla.encode()):08x}"

    @property
    def run_id(self) -> str:
        return (
            f"{self.case_id}"
            f"__{ABREVIATURA_ARQUITECTURA[self.arquitectura]}"
            f"__r{self.repeticion}"
            f"__{self.sufijo}"
        )

    def to_dict(self) -> dict:
        d = asdict(self)
        d["run_id"] = self.run_id
        return d


def partes_del_run_id(run_id: str) -> dict:
    """Descompone un `run_id`. No recupera `dataset` ni `config_version`.

    Los dos están dentro del sufijo por hash y no son reversibles: para
    recuperarlos hay que leer el artefacto, que los lleva explícitos. La
    función existe para poder filtrar archivos por caso o repetición sin
    abrirlos, no como sustituto del artefacto.
    """
    coincidencia = _RUN_ID.match(run_id)
    if not coincidencia:
        raise ValueError(f"run_id con formato inesperado: {run_id!r}")
    partes = coincidencia.groupdict()
    partes["repeticion"] = int(partes["repeticion"])
    return partes


def verificar(identidad: IdentidadCorrida, run_id: str) -> bool:
    """`True` si `run_id` corresponde a esa identidad.

    Sirve para detectar un artefacto renombrado a mano o movido de
    configuración: el sufijo no cuadraría.
    """
    return identidad.run_id == run_id
