"""Contratos de caso de prueba y de referencia (ground truth).

**Separación obligatoria.** `TestCase` es lo único que puede llegar a una
arquitectura; `GroundTruth` es lo único que puede llegar a un evaluador.
Nunca viajan juntos: son clases distintas, se guardan en archivos distintos
(`experiments/cases/` y `experiments/ground_truth/`) y solo se vinculan por
`case_id`. El plan lo exige para que una referencia no pueda filtrarse al
prompt por descuido, que es exactamente la fuga que el proyecto ya tuvo con
las etiquetas embebidas de BGL.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from src.experimentation.contracts.enums import (
    DATASETS,
    DIMENSIONES,
    ESTADOS_DIMENSION,
    ETIQUETAS_DETECCION,
    NIVELES_MITRE,
    PARTICIONES,
    TIPOS_DETECCION,
)


def _validar_en(valor, admitidos: tuple, campo: str) -> None:
    if valor not in admitidos:
        raise ValueError(
            f"{campo} inválido: {valor!r}. Admitidos: {', '.join(admitidos)}"
        )


@dataclass
class RegistroProcedencia:
    """De dónde salió una línea concreta del caso.

    Sin esto no se puede auditar un resultado: ante un falso positivo hay
    que poder volver al archivo y la línea original (plan, Fase 2 acción 7).
    """

    indice_en_caso: int
    archivo_origen: str
    linea_original: int
    #: Clave de agrupación del dataset: `blk_...` en HDFS, ventana temporal
    #: en BGL, sesión/incidente en UWF. Es la unidad que NO puede quedar
    #: partida entre desarrollo y evaluación.
    grupo: str | None = None
    #: Identificador estable del evento cuando el dataset lo provee (`uid`
    #: de Zeek). Es la clave de matching exacto de la reconstrucción.
    uid: str | None = None

    def __post_init__(self) -> None:
        if self.indice_en_caso < 0:
            raise ValueError(
                f"indice_en_caso no puede ser negativo: {self.indice_en_caso}"
            )
        if self.linea_original < 1:
            raise ValueError(
                f"linea_original es 1-indexada: {self.linea_original}"
            )

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class TestCase:
    """Entrada preparada para una arquitectura. **No contiene etiquetas.**

    `contenido` es el texto que la arquitectura va a analizar, idéntico para
    todas las arquitecturas comparadas. Si el dataset trae la etiqueta
    embebida en la línea (BGL la pone como primer token), esa columna debe
    retirarse al preparar el caso, no al evaluarlo.
    """

    case_id: str
    dataset: str
    #: `operativa` (HDFS/BGL) o `seguridad` (UWF). Determina qué campo del
    #: estado de NODEX responde la pregunta de detección.
    tipo_deteccion: str
    particion: str
    contenido: str
    #: Dimensiones que este caso puede evaluar. Un caso de HDFS no declara
    #: `mitre` porque el dataset no trae referencia ATT&CK: declararla y
    #: después puntuarla con una referencia inventada es justamente lo que
    #: el protocolo prohíbe.
    dimensiones_aplicables: tuple[str, ...] = ()
    procedencia: list[RegistroProcedencia] = field(default_factory=list)
    #: Grupos cubiertos por el caso, para verificar que no se solapen entre
    #: particiones. Derivado de `procedencia`, se guarda explícito para no
    #: tener que recalcularlo al validar la partición.
    grupos: tuple[str, ...] = ()
    #: Metadatos no evaluables: prevalencia solicitada del lote, nº de
    #: líneas, semilla. Nada de esto puede contener la etiqueta.
    notas: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.case_id:
            raise ValueError("case_id no puede estar vacío")
        _validar_en(self.dataset, DATASETS, "dataset")
        _validar_en(self.tipo_deteccion, TIPOS_DETECCION, "tipo_deteccion")
        _validar_en(self.particion, PARTICIONES, "particion")
        for dimension in self.dimensiones_aplicables:
            _validar_en(dimension, DIMENSIONES, "dimensiones_aplicables")

    def to_dict(self) -> dict:
        d = asdict(self)
        d["procedencia"] = [r.to_dict() for r in self.procedencia]
        return d


@dataclass
class ReferenciaMitre:
    """Técnica o táctica esperada, al nivel en que el dataset la declara.

    `nivel` importa: una táctica NO se convierte automáticamente en una
    técnica, y una subtécnica ausente queda `no_aplica` en vez de inferirse
    (plan, Fase 3 acción 2).
    """

    nivel: str
    id: str
    nombre: str | None = None
    #: `uid`s que sustentan esta atribución, cuando el dataset los provee.
    evidence_uids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _validar_en(self.nivel, NIVELES_MITRE, "nivel")
        if not self.id:
            raise ValueError("ReferenciaMitre.id no puede estar vacío")

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class GroundTruth:
    """Referencia reservada de un caso. **Solo la recibe el evaluador.**

    Cada dimensión lleva su propio estado: que exista el objeto no significa
    que las cinco dimensiones sean puntuables. Una dimensión sin referencia
    aprobada queda `referencia_pendiente` y no se puntúa ni se da por
    acertada.
    """

    case_id: str
    #: Estado por dimensión (`evaluable`, `no_aplica`,
    #: `referencia_pendiente`, ...). Es la fuente de verdad de qué se puede
    #: medir en este caso.
    estado_dimension: dict = field(default_factory=dict)

    # --- D1 detección ---
    #: `normal` | `anomalo`, en el vocabulario del evaluador existente.
    etiqueta_deteccion: str | None = None
    #: Etiqueta cruda del dataset antes de normalizar (`Anomaly`, `Alert`,
    #: `-`, ...). Se conserva para poder auditar la normalización.
    etiqueta_original: str | None = None

    # --- D2 reconstrucción ---
    #: `uid`s de los eventos núcleo del incidente (ERR, en UWF). Es la clave
    #: de matching EXACTO contra `reconstructed_events[].uid`.
    core_event_uids: tuple[str, ...] = ()

    # --- D3 MITRE ---
    referencias_mitre: list[ReferenciaMitre] = field(default_factory=list)
    #: Estado por **nivel** de la dimensión MITRE, que el plan exige llevar
    #: separado (Fase 3, acción 2): táctica presente → `evaluable`; técnica
    #: presente → `evaluable`; subtécnica ausente → `no_aplica`.
    #:
    #: Un solo estado para toda la dimensión no alcanza. En UWF las 22
    #: etiquetas de técnica son todas `T####` sin subtécnica, así que el
    #: nivel de subtécnica no es puntuable mientras los otros dos sí lo son.
    #: Sin esta separación, el evaluador tendría que elegir entre declarar
    #: la dimensión completa no evaluable (perdiendo táctica y técnica) o
    #: inferir una subtécnica, que el plan prohíbe expresamente.
    estado_mitre_por_nivel: dict = field(default_factory=dict)

    # --- D4 reporte ---
    #: El plan prohíbe expresamente ampliar el ERR con `gold_claims`,
    #: `expected_facts`, reportes gold o conclusiones esperadas. La calidad
    #: del reporte se evalúa con rúbrica humana, no comparando contra un
    #: texto de referencia. Acá solo se registra si la rúbrica ya fue
    #: aplicada y dónde vive su resultado.
    rubrica_aplicada: bool = False
    rubrica_ref: str | None = None

    #: Procedencia de la anotación: quién/qué la produjo y si está aprobada.
    #: `fuente="dataset"` para etiquetas provistas; `fuente="revision_humana"`
    #: para anotaciones semánticas. Nunca `fuente="nodex"`: construir la
    #: referencia con la salida del sistema evaluado invalida la medición.
    anotacion: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.case_id:
            raise ValueError("case_id no puede estar vacío")
        if self.etiqueta_deteccion is not None:
            _validar_en(
                self.etiqueta_deteccion, ETIQUETAS_DETECCION, "etiqueta_deteccion"
            )
        for dimension, estado in self.estado_dimension.items():
            _validar_en(dimension, DIMENSIONES, "estado_dimension (clave)")
            _validar_en(estado, ESTADOS_DIMENSION, f"estado_dimension[{dimension}]")
        for nivel, estado in self.estado_mitre_por_nivel.items():
            _validar_en(nivel, NIVELES_MITRE, "estado_mitre_por_nivel (clave)")
            _validar_en(
                estado, ESTADOS_DIMENSION, f"estado_mitre_por_nivel[{nivel}]"
            )
        niveles_con_referencia = {r.nivel for r in self.referencias_mitre}
        for nivel in niveles_con_referencia:
            if self.estado_mitre_por_nivel.get(nivel) == "no_aplica":
                raise ValueError(
                    f"el nivel {nivel!r} está marcado no_aplica pero hay "
                    f"{sum(1 for r in self.referencias_mitre if r.nivel == nivel)} "
                    "referencia(s) de ese nivel: una de las dos cosas está mal"
                )
        if self.anotacion.get("fuente") == "nodex":
            raise ValueError(
                "La referencia no puede provenir de NODEX: usar la salida del "
                "sistema evaluado como ground truth invalida la medición."
            )

    def to_dict(self) -> dict:
        d = asdict(self)
        d["referencias_mitre"] = [r.to_dict() for r in self.referencias_mitre]
        return d
