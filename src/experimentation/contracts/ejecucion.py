"""Contratos de configuración y de registro de ejecución.

`ExperimentConfig` es lo que se congela antes de una campaña;
`RunRecord` es la bitácora de una ejecución concreta (un caso, una
arquitectura, una repetición). Juntos permiten responder "¿con qué código,
qué modelo y qué datos se produjo este número?" sin depender de la memoria
de quien lo corrió.

La procedencia no se reimplementa: se reutiliza
`src/tools/provenance.py::procedencia_ejecucion()`, que ya centraliza
commit, rama, árbol limpio, motor, esquema, configuración de
preprocesamiento, versión de Python, plataforma y hashes de
`requirements.txt`/`constraints.txt`.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from src.experimentation.contracts.enums import (
    ARQUITECTURAS,
    DATASETS,
    ESTADOS_EJECUCION,
    PARTICIONES,
)


def _validar_en(valor, admitidos: tuple, campo: str) -> None:
    if valor not in admitidos:
        raise ValueError(
            f"{campo} inválido: {valor!r}. Admitidos: {', '.join(admitidos)}"
        )


@dataclass
class ExperimentConfig:
    """Configuración congelable de una campaña. **Sin secretos.**

    Las credenciales no se guardan ni se registran: solo se anota si estaban
    presentes, para poder distinguir "no corrió porque faltaba la key" de
    "no corrió porque el modelo falló".
    """

    config_id: str
    #: Versión del protocolo experimental bajo el que se interpretan los
    #: resultados. Un cambio de reglas de matching o de métricas obliga a
    #: subirla: dos campañas con protocolos distintos no son comparables.
    protocolo_version: str
    arquitecturas: tuple[str, ...]
    datasets: tuple[str, ...]
    particion: str
    #: Repeticiones por caso y arquitectura. Con temperatura 0 el sistema
    #: sigue mostrando variabilidad menor entre corridas idénticas (está
    #: documentado en el README), así que N>1 mide esa variabilidad en vez
    #: de suponerla nula.
    repeticiones: int
    #: Modelos CONFIGURADOS. Los realmente usados por llamada se registran
    #: en `RunRecord.telemetria`, porque el respaldo puede activarse a mitad
    #: de una corrida (ya pasó: cuota agotada del principal durante BGL).
    modelo_principal: str | None = None
    modelo_respaldo: str | None = None
    temperatura: float | None = None
    #: Semilla de construcción de casos, para que el banco sea reproducible.
    semilla: int | None = None
    #: Rutas aisladas del experimento (ChromaDB propio, caché propia). No
    #: deben apuntar a `data/chroma` ni a la caché de producción.
    rutas_aisladas: dict = field(default_factory=dict)
    #: Procedencia del entorno: salida de `procedencia_ejecucion()`.
    procedencia: dict = field(default_factory=dict)
    #: **Interruptor de ejecución.** La configuración que se entrega al
    #: cerrar la preparación va en `False`. El orquestador debe negarse a
    #: invocar modelos o evaluadores mientras esté en `False`; preparar un
    #: manifiesto no lo activa (plan, Fase 7 acción 3).
    ejecucion_habilitada: bool = False
    credenciales_presentes: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.config_id:
            raise ValueError("config_id no puede estar vacío")
        if not self.protocolo_version:
            raise ValueError("protocolo_version no puede estar vacía")
        if not self.arquitecturas:
            raise ValueError("arquitecturas no puede estar vacía")
        for arquitectura in self.arquitecturas:
            _validar_en(arquitectura, ARQUITECTURAS, "arquitecturas")
        if not self.datasets:
            raise ValueError("datasets no puede estar vacía")
        for dataset in self.datasets:
            _validar_en(dataset, DATASETS, "datasets")
        _validar_en(self.particion, PARTICIONES, "particion")
        if self.repeticiones < 1:
            raise ValueError(f"repeticiones debe ser >= 1; es {self.repeticiones}")
        if self.temperatura is not None and not 0.0 <= self.temperatura <= 2.0:
            raise ValueError(f"temperatura fuera de rango: {self.temperatura}")
        for clave in self.credenciales_presentes:
            valor = self.credenciales_presentes[clave]
            if not isinstance(valor, bool):
                raise ValueError(
                    f"credenciales_presentes[{clave!r}] debe ser booleano: solo se "
                    "registra la PRESENCIA de la credencial, nunca su valor."
                )

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class RunRecord:
    """Bitácora de una ejecución: un caso, una arquitectura, una repetición.

    `run_id` no puede depender solo de un timestamp en segundos: dos
    ejecuciones del mismo segundo colisionarían y una sobreescribiría a la
    otra (plan, Fase 7 acción 1).
    """

    run_id: str
    case_id: str
    arquitectura: str
    dataset: str
    repeticion: int
    config_id: str
    protocolo_version: str
    iniciado_utc: str
    #: `None` mientras la ejecución está en curso o si se interrumpió sin
    #: poder cerrar el registro.
    terminado_utc: str | None = None
    estado: str = "completa"
    #: Mensaje de error tal como lo reportó el sistema. No se resume ni se
    #: normaliza: un `402 RESOURCE_EXHAUSTED` y un JSON mal formado tienen
    #: causas distintas y deben poder distinguirse después.
    error: str | None = None
    #: Archivos fuente usados, con hash (`procedencia_archivos()`).
    fuentes: list = field(default_factory=list)
    #: Procedencia del entorno de ESTA corrida.
    procedencia: dict = field(default_factory=dict)
    #: Ruta relativa del `ExperimentalOutput` producido, si lo hubo.
    output_ref: str | None = None
    #: Consumo operacional. La instrumentación real es de la Fase 6; acá
    #: queda el campo con las claves previstas: `modelo_efectivo_por_llamada`,
    #: `tokens_entrada`, `tokens_salida`, `tokens_razonamiento`, `llamadas`,
    #: `reintentos`, `fallbacks`, `duracion_total_s`, `duracion_por_agente_s`,
    #: `visitas_nodo`, `consultas_rag`.
    telemetria: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.run_id:
            raise ValueError("run_id no puede estar vacío")
        if not self.case_id:
            raise ValueError("case_id no puede estar vacío")
        _validar_en(self.arquitectura, ARQUITECTURAS, "arquitectura")
        _validar_en(self.dataset, DATASETS, "dataset")
        _validar_en(self.estado, ESTADOS_EJECUCION, "estado")
        if self.repeticion < 1:
            raise ValueError(f"repeticion es 1-indexada; es {self.repeticion}")
        if self.estado != "completa" and not self.error:
            raise ValueError(
                f"estado {self.estado!r} exige un mensaje en `error`: una "
                "ejecución fallida sin causa registrada no es auditable."
            )

    @property
    def fue_completa(self) -> bool:
        return self.estado == "completa"

    def to_dict(self) -> dict:
        return asdict(self)
