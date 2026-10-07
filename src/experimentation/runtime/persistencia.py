"""Persistencia de corridas. §15 del plan de continuación.

Estructura, una carpeta por arquitectura:

    experiments/
    |-- cases/          casos (entrada; sin etiquetas)
    |-- ground_truth/   referencias (solo para el evaluador)
    |-- manifests/      manifiestos de datasets y conversiones
    |-- nodex/          salidas de NODEX multiagente
    |-- single_agent/   salidas del agente único
    |-- baseline/       salidas del baseline de reglas
    |-- metrics/        métricas calculadas
    |-- telemetry/      telemetría por corrida
    `-- config/         configuraciones congeladas

**Nada se sobrescribe.** Escribir una corrida que ya existe falla. Es la
garantía que hace que un informe pueda citar un resultado y que ese
resultado siga existiendo tal como se citó.

Cada corrida se guarda en tres piezas separadas:

- `salida`: el contrato común, lo que consume el evaluador.
- `crudo`: el estado final sin interpretar, para poder auditar una métrica.
- `telemetria`: el consumo, que se agrega aparte de la calidad.

Están separadas porque se consumen por separado: el evaluador no necesita el
crudo, y el consumo no debe mezclarse con la calidad del resultado.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from src.experimentation.runtime.identidad import IdentidadCorrida

#: Carpeta de salidas por arquitectura.
CARPETA_POR_ARQUITECTURA = {
    "nodex_multiagente": "nodex",
    "agente_unico": "single_agent",
    "baseline_reglas": "baseline",
}

#: Subdirectorios que la campaña necesita.
SUBDIRECTORIOS = (
    "cases",
    "ground_truth",
    "manifests",
    "nodex",
    "single_agent",
    "baseline",
    "metrics",
    "telemetry",
    "config",
)


def preparar_estructura(raiz_repo: Path) -> dict:
    """Crea los subdirectorios y devuelve qué existía y qué se creó."""
    raiz = raiz_repo / "experiments"
    informe = {}
    for nombre in SUBDIRECTORIOS:
        ruta = raiz / nombre
        existia = ruta.is_dir()
        ruta.mkdir(parents=True, exist_ok=True)
        informe[nombre] = "existia" if existia else "creado"
    return informe


@dataclass
class RutasCorrida:
    salida: Path
    crudo: Path
    telemetria: Path

    def existentes(self) -> list[Path]:
        return [p for p in (self.salida, self.crudo, self.telemetria) if p.exists()]


def rutas(identidad: IdentidadCorrida, raiz_repo: Path) -> RutasCorrida:
    """Dónde van las tres piezas de una corrida."""
    raiz = raiz_repo / "experiments"
    carpeta = CARPETA_POR_ARQUITECTURA[identidad.arquitectura]
    base = raiz / carpeta / identidad.dataset
    return RutasCorrida(
        salida=base / f"{identidad.run_id}.json",
        crudo=base / "raw" / f"{identidad.run_id}.raw.json",
        telemetria=(
            raiz / "telemetry" / identidad.dataset / f"{identidad.run_id}.json"
        ),
    )


def ya_existe(identidad: IdentidadCorrida, raiz_repo: Path) -> bool:
    """`True` si la corrida ya tiene su salida guardada.

    Permite reanudar una campaña interrumpida sin repetir ni sobrescribir:
    el `run_id` es determinístico, así que la existencia del archivo es
    respuesta suficiente.
    """
    return rutas(identidad, raiz_repo).salida.exists()


def _escribir(ruta: Path, datos: dict) -> Path:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    if ruta.exists():
        raise FileExistsError(
            f"{ruta} ya existe. Las corridas no se sobrescriben: si hay que "
            "corregir algo, se genera otra config_version"
        )
    ruta.write_text(
        json.dumps(datos, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    return ruta


def guardar(
    identidad: IdentidadCorrida,
    raiz_repo: Path,
    salida: dict,
    crudo: dict | None = None,
    telemetria: dict | None = None,
) -> dict:
    """Guarda las tres piezas de una corrida. Falla si alguna ya existe.

    La comprobación se hace **antes** de escribir cualquiera, para no dejar
    una corrida a medio guardar: o se escriben todas o ninguna.
    """
    destino = rutas(identidad, raiz_repo)
    previas = destino.existentes()
    if previas:
        raise FileExistsError(
            f"la corrida {identidad.run_id} ya tiene "
            f"{len(previas)} archivo(s) guardados: {[p.name for p in previas]}"
        )

    # Cada pieza lleva la identidad completa: un archivo movido de carpeta
    # sigue sabiendo de qué caso, dataset, arquitectura, repetición y
    # configuración salió.
    cabecera = identidad.to_dict()
    escritos = {"salida": str(_escribir(destino.salida,
                                       {**cabecera, "salida": salida}))}
    if crudo is not None:
        escritos["crudo"] = str(
            _escribir(destino.crudo, {**cabecera, "estado_crudo": crudo})
        )
    if telemetria is not None:
        escritos["telemetria"] = str(
            _escribir(destino.telemetria,
                      {**cabecera, "telemetria": telemetria})
        )
    return escritos


def leer_salida(ruta: Path) -> dict:
    """Lee una corrida guardada, verificando que trae su identidad."""
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    faltantes = {
        "case_id", "dataset", "arquitectura", "repeticion", "config_version",
        "run_id",
    } - set(datos)
    if faltantes:
        raise ValueError(
            f"{ruta.name} no trae su identidad completa; faltan "
            f"{sorted(faltantes)}. Un resultado sin identidad no es rastreable"
        )
    return datos


def listar(raiz_repo: Path, arquitectura: str, dataset: str | None = None) -> list[Path]:
    """Las salidas guardadas de una arquitectura, opcionalmente por dataset."""
    carpeta = raiz_repo / "experiments" / CARPETA_POR_ARQUITECTURA[arquitectura]
    patron = f"{dataset}/*.json" if dataset else "*/*.json"
    # Se excluye `raw/`: ahí vive el estado crudo, no el contrato común.
    return sorted(
        p for p in carpeta.glob(patron) if p.parent.name != "raw"
    )
