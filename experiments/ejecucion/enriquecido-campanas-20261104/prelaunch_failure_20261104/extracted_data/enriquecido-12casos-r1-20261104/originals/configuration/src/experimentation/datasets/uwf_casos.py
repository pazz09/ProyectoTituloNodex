"""Composición de casos de UWF: incidentes maliciosos sobre fondo benigno.

Decisiones del 3-oct-2026 implementadas acá, todas registradas por caso:

- **D-8, composición.** No se construyen casos por shard/semana, porque lo
  benigno (350 339 registros de dic-2021) y lo malicioso (310 034 de
  ago-oct 2022) están en semanas distintas: un caso por shard sería 100%
  benigno o 100% malicioso y se podría acertar leyendo la fecha. Los casos
  son **escenarios sintéticos controlados** y cada uno lo declara en sus
  metadatos.
- **D-8, timestamps.** El incidente se **rebasa** a la ventana temporal del
  fondo benigno conservando los deltas relativos internos. El offset
  aplicado se guarda en el caso, así que el `ts` original es siempre
  recuperable. `datetime` se recalcula desde el `ts` rebasado para que las
  dos columnas no se contradigan.
- **uid** es la clave de referencia de reconstrucción: `core_event_uids`
  son los `uid` del incidente inyectado.

Unidad de agrupación (lo que no puede cruzar particiones): el **incidente**,
definido como una ráfaga temporal de conexiones maliciosas del mismo origen
y la misma táctica, con huecos de a lo más `GAP_INCIDENTE` segundos.

Límite honesto de este dataset: UWF tiene solo 10 IP de origen maliciosas
en total, así que un mismo host atacante aparece en desarrollo y en
evaluación. Los incidentes son episodios disjuntos y ningún registro se
reutiliza, pero el patrón de comportamiento del atacante **sí** se repite
entre particiones. No se puede eliminar con este dataset y queda declarado
como riesgo residual, no disimulado.
"""

from __future__ import annotations

import csv
import json
import random
import zlib
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from src.experimentation.contracts import PROTOCOLO_VERSION
from src.experimentation.contracts.casos import (
    GroundTruth,
    ReferenciaMitre,
    RegistroProcedencia,
    TestCase,
)
from src.experimentation.datasets.uwf import (
    COLUMNAS_EVENTO,
    SEPARADOR_ETIQUETAS,
    SIN_ATAQUE,
    VALOR_BENIGNO,
    VALOR_MALICIOSO,
)

#: Hueco máximo entre dos conexiones del mismo incidente, en segundos.
#: Con 60 s el dataset da 490 episodios (mediana 4 conexiones); con 300 s
#: baja a 323 y con 900 s a 241. Se eligió 60 s por ser el que más
#: incidentes independientes produce sin partir una ráfaga obvia.
GAP_INCIDENTE = 60.0

#: Un incidente no puede ser un solo evento: con una conexión no hay
#: secuencia que reconstruir y la dimensión D2 quedaría vacía.
MIN_CONEXIONES_INCIDENTE = 3

#: Tope de conexiones por incidente. Hay episodios de hasta 131 152
#: conexiones (escaneos sostenidos); de esos se toma un prefijo contiguo y
#: el resto del episodio se descarta, para no generar muchos incidentes
#: correlacionados a partir de una sola ráfaga.
MAX_CONEXIONES_INCIDENTE = 60

#: Duración máxima de un incidente, en segundos.
#:
#: Un incidente se inserta en el 70% central de la ventana de fondo, así que
#: necesita que esa ventana abarque al menos `duración / 0,70`. Medido:
#:
#:   duración de los incidentes   p50 = 0,4 s   p75 = 5 s   p90 = 46 s
#:                                p100 = 2 233 s (un solo caso)
#:   extensión de una ventana benigna de 240 registros   p10 = 994 s
#:
#: Con 600 s se descarta **1 incidente de 350** y el fondo necesario
#: (857 s) queda por debajo del p10 de las ventanas benignas, así que
#: prácticamente ninguna ventana se descarta por corta. Sin este tope, ese
#: único incidente de 37 minutos no cabía y se desbordaba por el final del
#: caso, quedando como los últimos registros: una pista posicional.
MAX_DURACION_INCIDENTE = 600.0

#: Tamaño del caso, en registros. Un caso es un extracto de tráfico, no un
#: dataset: ~300 conexiones es lo que un analista revisa de una vez y
#: mantiene el archivo en decenas de KB.
TAMANO_CASO = 300

#: Condiciones experimentales. En UWF **no** existe una prevalencia
#: "natural" a nivel de caso, porque los casos son compuestos: inventarla
#: sería arbitrario. La variable que sí tiene sentido es qué tan enterrado
#: está el incidente, con la prevalencia de casos fija en 0,5 para que D1
#: sea comparable entre condiciones.
#: Las dos condiciones tienen la MISMA prevalencia de casos (0,5), así que
#: no se llaman "balanceada" y "natural": lo balanceado es común a las dos.
#: Lo que varía, y lo que se quiere medir, es el tamaño del incidente
#: respecto del caso.
#:
#: Tamaños disponibles (350 incidentes): 125 de 3-4 conexiones, 139 de 5-9,
#: 14 de 10-19, 10 de 20-59 y 62 de 60 (prefijos de ráfagas enormes).
CONDICIONES = {
    # >= 20 conexiones en 300: el incidente ocupa al menos el 6,7% del caso.
    "visible": {
        "prevalencia": 0.50,
        "min_conexiones": 20,
        "recorte_incidente": None,
    },
    # 3 a 5 conexiones en 300: 1% a 1,67% del caso. Es la condición que
    # mide lo que la tesis afirma que aporta el enfoque multiagente:
    # encontrar algo pequeño dentro del ruido.
    "sigiloso": {
        "prevalencia": 0.50,
        "min_conexiones": MIN_CONEXIONES_INCIDENTE,
        "recorte_incidente": (3, 5),
    },
}

#: Presupuesto de casos por partición y condición. Acotado por los
#: incidentes de >= 20 conexiones, que son 21 en desarrollo y 51 en
#: evaluación tras la partición 30/70.
PRESUPUESTO = {
    "desarrollo": {"visible": 12, "sigiloso": 12},
    "evaluacion": {"visible": 40, "sigiloso": 40},
}

SEMILLA_UWF = 20261003


@dataclass
class Registro:
    """Una conexión ya convertida, con su etiqueta al lado (uso interno).

    Las etiquetas viven acá solo durante la generación. No se escriben
    nunca en el archivo del caso: van al `GroundTruth`.
    """

    uid: str
    ts: float
    valores: tuple
    binario: str
    tacticas: tuple[str, ...]
    tecnicas: tuple[str, ...]
    shard: str
    fila_original: int


@dataclass
class Incidente:
    """Ráfaga de conexiones maliciosas del mismo origen y la misma táctica."""

    incidente_id: str
    registros: list[Registro]
    tactica: str
    src_ip: str
    shard: str

    @property
    def tacticas(self) -> tuple[str, ...]:
        return tuple(sorted({t for r in self.registros for t in r.tacticas}
                            - {SIN_ATAQUE}))

    @property
    def tecnicas(self) -> tuple[str, ...]:
        return tuple(sorted({t for r in self.registros for t in r.tecnicas}
                            - {SIN_ATAQUE}))


def _leer(destino_csv: Path) -> tuple[list[Registro], dict[str, list[Registro]]]:
    """Lee los CSV convertidos. Devuelve (maliciosos, benignos por shard)."""
    etiquetas: dict[str, tuple[str, tuple, tuple]] = {}
    for archivo in sorted((destino_csv / "etiquetas").glob("*.csv")):
        with archivo.open(encoding="utf-8", newline="") as f:
            for fila in csv.DictReader(f):
                etiquetas[fila["uid"]] = (
                    fila["label_binary"],
                    tuple(fila["label_tactic"].split(SEPARADOR_ETIQUETAS)),
                    tuple(fila["label_technique"].split(SEPARADOR_ETIQUETAS)),
                )

    maliciosos: list[Registro] = []
    benignos: dict[str, list[Registro]] = defaultdict(list)
    for archivo in sorted((destino_csv / "eventos").glob("*.csv")):
        with archivo.open(encoding="utf-8", newline="") as f:
            for numero, fila in enumerate(csv.DictReader(f), start=2):
                binario, tacticas, tecnicas = etiquetas[fila["uid"]]
                registro = Registro(
                    uid=fila["uid"],
                    ts=float(fila["ts"]),
                    valores=tuple(fila[c] for c in COLUMNAS_EVENTO),
                    binario=binario,
                    tacticas=tacticas,
                    tecnicas=tecnicas,
                    shard=archivo.stem,
                    fila_original=numero,
                )
                if binario == VALOR_MALICIOSO:
                    maliciosos.append(registro)
                elif binario == VALOR_BENIGNO:
                    benignos[archivo.stem].append(registro)
    for registros in benignos.values():
        registros.sort(key=lambda r: r.ts)
    return maliciosos, dict(benignos)


def construir_incidentes(maliciosos: list[Registro]) -> list[Incidente]:
    """Agrupa los maliciosos en ráfagas por (shard, táctica, IP origen)."""
    por_clave: dict[tuple, list[Registro]] = defaultdict(list)
    for registro in maliciosos:
        # La táctica unida (`A|B`) se usa tal cual como clave: separar una
        # conexión con dos tácticas en dos incidentes la duplicaría.
        clave = (
            registro.shard,
            SEPARADOR_ETIQUETAS.join(registro.tacticas),
            registro.valores[COLUMNAS_EVENTO.index("src_ip_zeek")],
        )
        por_clave[clave].append(registro)

    incidentes: list[Incidente] = []
    for clave in sorted(por_clave):
        shard, tactica, src_ip = clave
        registros = sorted(por_clave[clave], key=lambda r: (r.ts, r.uid))
        rafaga: list[Registro] = [registros[0]]
        rafagas: list[list[Registro]] = []
        for anterior, actual in zip(registros, registros[1:]):
            if actual.ts - anterior.ts <= GAP_INCIDENTE:
                rafaga.append(actual)
            else:
                rafagas.append(rafaga)
                rafaga = [actual]
        rafagas.append(rafaga)

        for indice, rafaga in enumerate(rafagas):
            if len(rafaga) < MIN_CONEXIONES_INCIDENTE:
                continue
            # Prefijo contiguo: de una ráfaga enorme sale UN incidente.
            recortada = rafaga[:MAX_CONEXIONES_INCIDENTE]
            duracion = recortada[-1].ts - recortada[0].ts
            if duracion > MAX_DURACION_INCIDENTE:
                continue
            incidentes.append(
                Incidente(
                    incidente_id=f"{shard}__{tactica}__{src_ip}__{indice:04d}",
                    registros=recortada,
                    tactica=tactica,
                    src_ip=src_ip,
                    shard=shard,
                )
            )
    return incidentes


def particionar_incidentes(
    incidentes: list[Incidente],
    proporcion_desarrollo: float = 0.30,
    semilla: int = SEMILLA_UWF,
) -> dict[str, list[Incidente]]:
    """Reparte los incidentes 30/70, estratificando por táctica.

    Estratificar por táctica importa porque la distribución es muy
    desigual: `Resource Development` tiene 262 388 conexiones y `Collection`
    una sola. Sin estratificar, una táctica entera podría caer solo en
    desarrollo y la evaluación de D3 no la vería nunca.
    """
    reparto: dict[str, list[Incidente]] = {"desarrollo": [], "evaluacion": []}
    por_tactica: dict[str, list[Incidente]] = defaultdict(list)
    for incidente in incidentes:
        por_tactica[incidente.tactica].append(incidente)
    for tactica in sorted(por_tactica):
        estrato = sorted(por_tactica[tactica], key=lambda i: i.incidente_id)
        # `crc32` y no `hash()`: el hash de un str varía entre procesos por
        # PYTHONHASHSEED y la partición no sería reproducible.
        semilla_estrato = semilla + zlib.crc32(tactica.encode()) % 100_000
        random.Random(semilla_estrato).shuffle(estrato)
        corte = round(len(estrato) * proporcion_desarrollo)
        reparto["desarrollo"].extend(estrato[:corte])
        reparto["evaluacion"].extend(estrato[corte:])
    for particion in reparto:
        reparto[particion].sort(key=lambda i: i.incidente_id)
    return reparto


class AsignadorBenigno:
    """Entrega ventanas contiguas de tráfico benigno, sin reutilizar nada.

    Cada ventana es un tramo contiguo de un shard benigno, así que el fondo
    del caso es un pedazo real de tráfico y no una muestra barajada.
    """

    def __init__(self, benignos: dict[str, list[Registro]]):
        self._shards = sorted(benignos)
        self._datos = benignos
        self._cursor = {s: 0 for s in self._shards}
        self._siguiente = 0

    #: Ventanas descartadas por ser temporalmente demasiado cortas. Se
    #: informa en el manifiesto: son registros benignos consumidos que no
    #: llegaron a ningún caso.
    descartadas = 0

    def tomar(self, cuantos: int, span_minimo: float = 0.0) -> list[Registro]:
        """Entrega una ventana contigua que abarque al menos `span_minimo`.

        La densidad del tráfico benigno varía: hay tramos de 300 conexiones
        que cubren horas y otros que cubren segundos. Si la ventana es más
        corta que el incidente, el incidente se desbordaría por el final y
        quedaría siendo los últimos registros del caso, lo que es una pista
        posicional. Por eso una ventana demasiado corta se descarta en vez
        de usarse.
        """
        intentos_por_shard = 64
        for _ in range(len(self._shards) * intentos_por_shard):
            shard = self._shards[self._siguiente % len(self._shards)]
            self._siguiente += 1
            inicio = self._cursor[shard]
            if inicio + cuantos > len(self._datos[shard]):
                continue
            ventana = self._datos[shard][inicio:inicio + cuantos]
            self._cursor[shard] = inicio + cuantos
            if ventana[-1].ts - ventana[0].ts >= span_minimo:
                return ventana
            self.descartadas += 1
        raise ValueError(
            "no quedan ventanas benignas contiguas con suficiente extensión "
            f"temporal (se pedían {cuantos} registros abarcando "
            f"{span_minimo:.1f} s): reducir el número de casos, no reutilizar "
            "registros"
        )

    def restante(self) -> int:
        return sum(len(self._datos[s]) - self._cursor[s] for s in self._shards)


def _rebasar(incidente_ts: list[float], destino: float) -> float:
    """Offset que lleva el inicio del incidente a `destino`."""
    return destino - min(incidente_ts)


def _recomputar_datetime(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%S.%f"
    )[:-3]


def _fila_rebasada(registro: Registro, offset: float) -> tuple:
    """Copia la fila con `ts` y `datetime` desplazados."""
    valores = list(registro.valores)
    indice_ts = COLUMNAS_EVENTO.index("ts")
    indice_dt = COLUMNAS_EVENTO.index("datetime")
    nuevo_ts = registro.ts + offset
    valores[indice_ts] = f"{nuevo_ts:.6f}"
    valores[indice_dt] = _recomputar_datetime(nuevo_ts)
    return tuple(valores)


def componer_caso(
    case_id: str,
    particion: str,
    condicion: str,
    fondo: list[Registro],
    incidente: Incidente | None,
    azar: random.Random,
) -> tuple[TestCase, GroundTruth]:
    """Arma un caso compuesto y su referencia."""
    filas: list[tuple[float, tuple, Registro]] = [
        (r.ts, r.valores, r) for r in fondo
    ]
    offset = 0.0
    uids_nucleo: tuple[str, ...] = ()

    if incidente is not None:
        ts_fondo = [r.ts for r in fondo]
        # El incidente se inserta en un punto interior de la ventana del
        # fondo, nunca en los extremos: si empezara en el primer segundo o
        # terminara en el último, su posición lo delataría.
        inferior, superior = min(ts_fondo), max(ts_fondo)
        margen = (superior - inferior) * 0.15
        duracion = max(r.ts for r in incidente.registros) - min(
            r.ts for r in incidente.registros
        )
        tope = superior - margen - duracion
        piso = inferior + margen
        if tope <= piso:
            # El asignador ya garantiza la extensión necesaria; si igual no
            # alcanza, se falla en vez de dejar el incidente desbordando el
            # final de la ventana, que sería una pista posicional.
            raise ValueError(
                f"{case_id}: el incidente dura {duracion:.1f} s y no cabe en "
                f"una ventana de {superior - inferior:.1f} s con margen"
            )
        destino = azar.uniform(piso, tope)
        offset = _rebasar([r.ts for r in incidente.registros], destino)
        for registro in incidente.registros:
            filas.append((registro.ts + offset,
                          _fila_rebasada(registro, offset), registro))
        uids_nucleo = tuple(r.uid for r in incidente.registros)

    filas.sort(key=lambda f: (f[0], f[2].uid))

    contenido = ",".join(COLUMNAS_EVENTO) + "\n" + "\n".join(
        ",".join(str(v) for v in valores) for _, valores, _ in filas
    )
    procedencia = [
        RegistroProcedencia(
            indice_en_caso=posicion,
            archivo_origen=f"data/experimentacion/uwf_csv/eventos/{r.shard}.csv",
            linea_original=r.fila_original,
            grupo=(incidente.incidente_id if incidente and r.uid in uids_nucleo
                   else f"fondo:{r.shard}"),
            uid=r.uid,
        )
        for posicion, (_, _, r) in enumerate(filas)
    ]

    n_maliciosos = len(uids_nucleo)
    caso = TestCase(
        case_id=case_id,
        dataset="uwf",
        tipo_deteccion="seguridad",
        particion=particion,
        contenido=contenido,
        dimensiones_aplicables=("deteccion", "reconstruccion", "mitre",
                                "reporte", "consumo"),
        procedencia=procedencia,
        grupos=tuple(sorted({r.grupo for r in procedencia})),
        notas={
            # Declaración obligatoria: el caso es sintético.
            "escenario": "sintetico_controlado",
            "composicion": (
                "fondo benigno contiguo de UWF (dic-2021) con un incidente "
                "malicioso de UWF (ago-oct 2022) rebasado a la ventana del "
                "fondo; ningún registro se reutiliza entre casos"
            ),
            "n_registros": len(filas),
            "n_registros_benignos": len(fondo),
            "n_registros_maliciosos": n_maliciosos,
            "proporcion_maliciosa": round(n_maliciosos / len(filas), 6),
            "shards_fondo": sorted({r.shard for r in fondo}),
            "shard_incidente": incidente.shard if incidente else None,
            "offset_rebase_segundos": round(offset, 6),
            "ts_original_recuperable": (
                "ts_original = ts_del_caso - offset_rebase_segundos, solo "
                "para las filas del incidente"
            ),
            "datetime_recomputado": bool(incidente),
            "condicion": condicion,
            "semilla": SEMILLA_UWF,
            "protocolo_version": PROTOCOLO_VERSION,
        },
    )

    referencias_mitre = []
    if incidente is not None:
        for tactica in incidente.tacticas:
            referencias_mitre.append(ReferenciaMitre(
                nivel="tactica", id=tactica, evidence_uids=uids_nucleo))
        for tecnica in incidente.tecnicas:
            referencias_mitre.append(ReferenciaMitre(
                nivel="tecnica", id=tecnica, evidence_uids=uids_nucleo))

    referencia = GroundTruth(
        case_id=case_id,
        estado_dimension={
            "deteccion": "evaluable",
            # Sin incidente no hay nada que reconstruir ni que atribuir: no
            # es un acierto por defecto, es una dimensión que no aplica.
            "reconstruccion": "evaluable" if incidente else "no_aplica",
            "mitre": "evaluable" if incidente else "no_aplica",
            "reporte": "referencia_pendiente",
            "consumo": "evaluable",
        },
        etiqueta_deteccion="anomalo" if incidente else "normal",
        etiqueta_original=VALOR_MALICIOSO if incidente else VALOR_BENIGNO,
        core_event_uids=uids_nucleo,
        referencias_mitre=referencias_mitre,
        # UWF etiqueta táctica y técnica, nunca subtécnica: las 22 etiquetas
        # de `label_technique` del dataset son todas `T####` sin punto. La
        # subtécnica queda `no_aplica` y **no se infiere** desde la técnica.
        estado_mitre_por_nivel=(
            {"tactica": "evaluable", "tecnica": "evaluable",
             "subtecnica": "no_aplica"}
            if incidente else
            {"tactica": "no_aplica", "tecnica": "no_aplica",
             "subtecnica": "no_aplica"}
        ),
        anotacion={
            "fuente": "dataset",
            "regla": (
                "label_binary del dataset UWF, por uid; el caso es malicioso "
                "si contiene el incidente inyectado"
            ),
            "incidente": incidente.incidente_id if incidente else None,
            "tactica_del_incidente": incidente.tactica if incidente else None,
            "aprobada": True,
        },
    )
    return caso, referencia


# --- generación completa ---------------------------------------------------

def _recortar(incidente: Incidente, parametros: dict,
              azar: random.Random) -> Incidente | None:
    """Adapta un incidente a la condición, o lo descarta si no califica.

    El recorte toma un prefijo contiguo, así que el incidente recortado
    sigue siendo una ráfaga real y `core_event_uids` sigue describiendo
    exactamente lo que está en el caso.
    """
    if len(incidente.registros) < parametros["min_conexiones"]:
        return None
    recorte = parametros["recorte_incidente"]
    if recorte is None:
        return incidente
    minimo, maximo = recorte
    cuantos = azar.randint(minimo, min(maximo, len(incidente.registros)))
    return Incidente(
        incidente_id=f"{incidente.incidente_id}#r{cuantos}",
        registros=incidente.registros[:cuantos],
        tactica=incidente.tactica,
        src_ip=incidente.src_ip,
        shard=incidente.shard,
    )


def _seleccionar_por_tactica(
    disponibles: list[Incidente], cuantos: int, parametros: dict,
    azar: random.Random,
) -> tuple[list[Incidente], list[Incidente]]:
    """Elige incidentes por rondas, empezando por las tácticas más escasas.

    Sin esto la selección queda dominada por `Reconnaissance`, que son 227
    de los 246 incidentes de evaluación: en una primera versión 51 de los 52
    casos positivos eran de esa única táctica y D3 habría medido una sola.
    Recorriendo las tácticas de menor disponibilidad hacia la mayor se
    garantiza que las escasas entren antes de que la abundante llene el
    resto.

    La diversidad sigue acotada por el dataset: evaluación tiene 8
    etiquetas de táctica distintas y cuatro de ellas con un solo incidente.
    """
    por_tactica: dict[str, list[Incidente]] = defaultdict(list)
    for incidente in disponibles:
        por_tactica[incidente.tactica].append(incidente)
    orden = sorted(por_tactica, key=lambda t: (len(por_tactica[t]), t))

    elegidos: list[Incidente] = []
    consumidos: list[Incidente] = []
    while len(elegidos) < cuantos:
        avanzo = False
        for tactica in orden:
            if len(elegidos) == cuantos:
                break
            while por_tactica[tactica]:
                candidato = por_tactica[tactica].pop(0)
                recortado = _recortar(candidato, parametros, azar)
                if recortado is None:
                    # No califica para esta condición; queda disponible para
                    # la otra, así que no se marca como consumido.
                    continue
                elegidos.append(recortado)
                consumidos.append(candidato)
                avanzo = True
                break
        if not avanzo:
            break
    return elegidos, consumidos


def generar_casos_uwf(raiz_repo: Path, raiz_experimentos: Path) -> dict:
    """Genera todos los casos de UWF y devuelve el manifiesto."""
    destino_csv = raiz_repo / "data/experimentacion/uwf_csv"
    maliciosos, benignos = _leer(destino_csv)
    incidentes = construir_incidentes(maliciosos)
    reparto = particionar_incidentes(incidentes)

    manifiesto = {
        "dataset": "uwf",
        "protocolo_version": PROTOCOLO_VERSION,
        "tipo_deteccion": "seguridad",
        "escenario": "sintetico_controlado",
        "decisiones_aplicadas": {
            "D-8_composicion": (
                "casos compuestos: fondo benigno contiguo de dic-2021 con un "
                "incidente malicioso de ago-oct 2022; no se construyen casos "
                "por shard por la separación temporal del dataset"
            ),
            "D-8_timestamps": (
                "el incidente se rebasa a la ventana del fondo conservando "
                "sus deltas internos; el offset queda en cada caso y datetime "
                "se recalcula desde el ts rebasado"
            ),
            "D-9_duplicate": (
                "los registros label_binary='Duplicate' ya fueron excluidos "
                "en la conversión (ver uwf_conversion.json)"
            ),
            "uid_referencia": "core_event_uids son los uid del incidente",
        },
        "agrupacion": {
            "unidad": "incidente (ráfaga por shard+táctica+IP origen)",
            "gap_segundos": GAP_INCIDENTE,
            "min_conexiones": MIN_CONEXIONES_INCIDENTE,
            "max_conexiones": MAX_CONEXIONES_INCIDENTE,
                "max_duracion_segundos": MAX_DURACION_INCIDENTE,
            "n_incidentes": len(incidentes),
            "n_incidentes_por_particion": {
                p: len(v) for p, v in reparto.items()
            },
            "tacticas": dict(sorted(
                ((t, sum(1 for i in incidentes if i.tactica == t))
                 for t in {i.tactica for i in incidentes}),
                key=lambda par: -par[1],
            )),
        },
        "riesgo_residual": (
            "UWF tiene solo 10 IP de origen maliciosas, así que un mismo host "
            "atacante aparece en desarrollo y en evaluación. Los incidentes "
            "son episodios disjuntos y ningún registro se reutiliza, pero el "
            "patrón del atacante se repite entre particiones. No es "
            "eliminable con este dataset."
        ),
        "benigno": {
            "registros_disponibles": sum(len(v) for v in benignos.values()),
            "shards": sorted(benignos),
        },
        "condiciones": {},
    }

    asignador = AsignadorBenigno(benignos)
    usados_global: set[str] = set()

    for particion in ("desarrollo", "evaluacion"):
        disponibles = list(reparto[particion])
        manifiesto["condiciones"][particion] = {}
        for condicion, parametros in CONDICIONES.items():
            n_casos = PRESUPUESTO[particion][condicion]
            prevalencia = parametros["prevalencia"]
            n_positivos = round(n_casos * prevalencia)
            azar = random.Random(
                SEMILLA_UWF + zlib.crc32(f"{particion}|{condicion}".encode()) % 10_000
            )

            elegidos, consumidos = _seleccionar_por_tactica(
                disponibles, n_positivos, parametros, azar
            )
            for candidato in consumidos:
                disponibles.remove(candidato)
            if len(elegidos) < n_positivos:
                raise ValueError(
                    f"{particion}/{condicion}: se necesitan {n_positivos} "
                    f"incidentes y hay {len(elegidos)} utilizables; reducir el "
                    "presupuesto, no reutilizar incidentes"
                )

            casos, referencias = [], []
            for indice in range(n_casos):
                incidente = elegidos[indice] if indice < n_positivos else None
                n_fondo = TAMANO_CASO - (len(incidente.registros) if incidente else 0)
                # El incidente se inserta dejando un 15% de margen a cada
                # lado, así que tiene que caber en el 70% central: la
                # ventana debe abarcar al menos duración / 0,70.
                span_minimo = 0.0
                if incidente:
                    ts_incidente = [r.ts for r in incidente.registros]
                    span_minimo = (max(ts_incidente) - min(ts_incidente)) / 0.70
                fondo = asignador.tomar(n_fondo, span_minimo)
                case_id = f"uwf_{particion[:3]}_{condicion}_{indice:04d}"
                caso, referencia = componer_caso(
                    case_id, particion, condicion, fondo, incidente, azar
                )
                # Ningún uid puede repetirse dentro del caso ni entre casos:
                # es la condición para que uid sirva de clave de matching.
                uids = [r.uid for r in caso.procedencia]
                if len(uids) != len(set(uids)):
                    raise ValueError(f"{case_id}: uid repetido dentro del caso")
                choque = usados_global & set(uids)
                if choque:
                    raise ValueError(
                        f"{case_id}: {len(choque)} uid ya usados en otro caso"
                    )
                usados_global |= set(uids)
                casos.append(caso)
                referencias.append(referencia)

            _escribir(casos, referencias, raiz_experimentos)
            proporciones = [c.notas["proporcion_maliciosa"] for c in casos
                            if c.notas["n_registros_maliciosos"]]
            manifiesto["condiciones"][particion][condicion] = {
                "n_casos": len(casos),
                "prevalencia_solicitada": prevalencia,
                "prevalencia_efectiva": round(n_positivos / n_casos, 6),
                "delta_por_redondeo": round(n_positivos / n_casos - prevalencia, 6),
                "min_conexiones_incidente": parametros["min_conexiones"],
                "recorte_incidente": parametros["recorte_incidente"],
                "tamano_caso": TAMANO_CASO,
                "proporcion_maliciosa_en_casos_positivos": {
                    "min": min(proporciones) if proporciones else None,
                    "max": max(proporciones) if proporciones else None,
                    "media": (round(sum(proporciones) / len(proporciones), 6)
                              if proporciones else None),
                },
                # Distribución de tácticas de los casos positivos: es lo que
                # acota qué puede medir D3 en esta condición.
                "tacticas_de_los_positivos": dict(sorted(
                    ((t, sum(1 for i in elegidos if i.tactica == t))
                     for t in {i.tactica for i in elegidos}),
                    key=lambda par: -par[1],
                )),
                "incidentes_usados": [i.incidente_id for i in elegidos],
                "case_ids": [c.case_id for c in casos],
            }

    manifiesto["benigno"]["registros_consumidos"] = (
        manifiesto["benigno"]["registros_disponibles"] - asignador.restante()
    )
    manifiesto["benigno"]["ventanas_descartadas_por_extension"] = (
        asignador.descartadas
    )
    manifiesto["uids_usados"] = len(usados_global)
    return manifiesto


def _escribir(casos: list[TestCase], referencias: list[GroundTruth],
              raiz_experimentos: Path) -> None:
    for caso in casos:
        directorio = raiz_experimentos / "cases" / "uwf" / caso.particion
        directorio.mkdir(parents=True, exist_ok=True)
        (directorio / f"{caso.case_id}.csv").write_text(
            caso.contenido + "\n", encoding="utf-8"
        )
        meta = caso.to_dict()
        meta.pop("contenido")
        meta["archivo_contenido"] = f"{caso.case_id}.csv"
        (directorio / f"{caso.case_id}.json").write_text(
            json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    for referencia in referencias:
        case_id = referencia.case_id
        particion = "desarrollo" if "_des_" in case_id else "evaluacion"
        directorio = raiz_experimentos / "ground_truth" / "uwf" / particion
        directorio.mkdir(parents=True, exist_ok=True)
        (directorio / f"{case_id}.json").write_text(
            json.dumps(referencia.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )


def main(raiz_repo: Path) -> None:
    raiz_experimentos = raiz_repo / "experiments"
    manifiesto = generar_casos_uwf(raiz_repo, raiz_experimentos)
    ruta = raiz_experimentos / "manifests" / "uwf.json"
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(
        json.dumps(manifiesto, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    agrupacion = manifiesto["agrupacion"]
    print(f"incidentes: {agrupacion['n_incidentes']} "
          f"({agrupacion['n_incidentes_por_particion']})")
    for particion, condiciones in manifiesto["condiciones"].items():
        for condicion, detalle in condiciones.items():
            proporcion = detalle["proporcion_maliciosa_en_casos_positivos"]
            print(f"  {particion:<11} {condicion:<11} n={detalle['n_casos']:<3} "
                  f"prev={detalle['prevalencia_efectiva']:.3f} "
                  f"malicioso_en_positivos={proporcion['min']:.4f}"
                  f"-{proporcion['max']:.4f} (media {proporcion['media']:.4f})")
    print(f"uid usados: {manifiesto['uids_usados']:,} | "
          f"benignos consumidos: {manifiesto['benigno']['registros_consumidos']:,}")


if __name__ == "__main__":
    main(Path(__file__).resolve().parents[3])
