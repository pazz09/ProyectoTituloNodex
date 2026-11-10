"""Runner del baseline determinístico de reglas. §10 del plan de continuación.

Reutiliza `src/tools/baseline_reglas.py` sin modificarlo. No consume LLM, así
que no necesita repeticiones: `N=1` basta porque el resultado es el mismo
siempre.

## La desalineación de pregunta con UWF, que hay que declarar

El baseline tiene **un solo veredicto**, y sus reglas son operativas:
severidad declarada del evento, proporción de eventos fallidos y
concentración de intentos fallidos por IP. Eso responde *"¿el sistema se
comporta de forma anómala?"*, que es la pregunta de HDFS y BGL.

UWF pregunta otra cosa: *"¿hay actividad maliciosa?"*. Un escaneo de puertos
exitoso no produce severidades graves ni conexiones fallidas, así que el
baseline puede no detectarlo **por diseño de sus reglas**, no por debilidad.

No se resuelve inventándole al baseline una noción de malicia. Se resuelve
declarándolo: cada salida lleva `pregunta_respondida` y, cuando el caso es
de seguridad, `desalineacion_de_pregunta = True`. El informe tiene que leer
esa comparación como **contextual**, no como una comparación pareada entre
pares. Para BGL, donde la pregunta sí coincide, la comparación es pareada y
válida.

## Dimensiones que puede evaluar

| Dimensión | Baseline |
|---|---|
| D1 detección | Sí (con la salvedad de arriba en UWF) |
| D2 reconstrucción | No: no produce eventos |
| D3 MITRE | No: no conoce ATT&CK |
| D4 reporte | No: `detalle` es una línea, no un informe |
| D5 consumo | Parcial: tiempo de ejecución, sin tokens ni llamadas |
"""

from __future__ import annotations

import time
from pathlib import Path

from src.experimentation.contracts import CONTRATO_VERSION
from src.experimentation.contracts.salida import ExperimentalOutput
from src.experimentation.runtime.identidad import IdentidadCorrida
from src.experimentation.runtime.telemetria import Telemetria

#: Dimensiones que el baseline puede responder. Las demás quedan
#: `no_aplica`: no es que falle, es que no produce esa salida.
DIMENSIONES_DEL_BASELINE = ("deteccion", "consumo")

#: El baseline responde la pregunta operativa, cualquiera sea el dataset.
PREGUNTA_RESPONDIDA = "operativa"

#: Mapa del vocabulario del baseline al del contrato común.
_CLASIFICACION = {"anomalo": "MALICIOUS", "normal": "BENIGN"}


def ejecutar(
    contenido: str,
    identidad: IdentidadCorrida,
    tipo_deteccion: str,
) -> tuple[ExperimentalOutput, Telemetria, dict]:
    """Clasifica un caso con el baseline de reglas.

    **Ejecuta el preprocesamiento de NODEX** (`clasificar_texto` llama a
    `preprocesar_lote`), así que esta función solo debe invocarse durante una
    corrida autorizada, nunca en preparación.

    Devuelve `(salida, telemetria, diagnostico)`.
    """
    # Import diferido: importar el baseline arrastra el preprocesamiento, y
    # este módulo tiene que poder importarse para revisión sin eso.
    from src.tools.baseline_reglas import clasificar_texto

    comenzado = time.monotonic()
    error: str | None = None
    resultado: dict = {}
    try:
        resultado = clasificar_texto(contenido)
    except Exception as excepcion:  # noqa: BLE001 - se registra, no se oculta
        # El plan prohíbe ocultar ejecuciones fallidas. Un fallo del
        # preprocesamiento impide clasificar, así que no se degrada a
        # "normal": se registra como no evaluable.
        error = f"{type(excepcion).__name__}: {excepcion}"
    transcurrido = time.monotonic() - comenzado

    prediccion = resultado.get("prediccion")
    clasificacion = _CLASIFICACION.get(prediccion)

    salida = ExperimentalOutput(
        case_id=identidad.case_id,
        run_id=identidad.run_id,
        arquitectura="baseline_reglas",
        contrato_version=CONTRATO_VERSION,
        classification=clasificacion,
        veredicto_booleano_presente=clasificacion is not None,
        motivo_no_evaluable=(
            error
            or (
                f"el baseline devolvió una predicción inesperada: "
                f"{prediccion!r}"
                if clasificacion is None
                else None
            )
        ),
        # El baseline no produce reporte: `detalle` es una línea que explica
        # qué regla se disparó, no un informe que una rúbrica pueda puntuar.
        report_summary=None,
    )

    telemetria = Telemetria(
        run_id=identidad.run_id,
        execution_time=transcurrido,
        # Sin LLM: estos campos quedan en `None` y no en 0, porque 0
        # llamadas y "no aplica" no son lo mismo al promediar.
        errores=[error] if error else [],
        # El baseline no usa el modelo, así que D-11 no lo afecta y su
        # telemetría no queda invalidada por §11.
        previa_a_d11=False,
    )

    diagnostico = {
        "regla_disparada": resultado.get("regla"),
        "detalle": resultado.get("detalle"),
        "pregunta_respondida": PREGUNTA_RESPONDIDA,
        "desalineacion_de_pregunta": tipo_deteccion != PREGUNTA_RESPONDIDA,
        "nota_desalineacion": (
            "el baseline responde la pregunta operativa; este caso es de "
            "seguridad. La comparación es contextual, no pareada"
            if tipo_deteccion != PREGUNTA_RESPONDIDA
            else None
        ),
        "determinista": True,
        "error": error,
    }
    return salida, telemetria, diagnostico


def estados_por_dimension(
    salida: ExperimentalOutput, dimensiones_aplicables: tuple[str, ...]
) -> dict:
    """Estado de cada dimensión para una corrida del baseline.

    Las dimensiones que el baseline no produce quedan `no_aplica` **aunque el
    caso las declare aplicables**: el caso dice qué se puede medir con una
    referencia, y esto dice qué puede responder esta arquitectura. Son dos
    cosas distintas y el evaluador se queda con la más restrictiva.
    """
    estados = {}
    for dimension in ("deteccion", "reconstruccion", "mitre", "reporte",
                      "consumo"):
        if dimension not in DIMENSIONES_DEL_BASELINE:
            estados[dimension] = "no_aplica"
        elif dimension not in dimensiones_aplicables:
            estados[dimension] = "no_aplica"
        elif dimension == "deteccion":
            estados[dimension] = (
                "evaluable" if salida.classification else "no_evaluable"
            )
        else:
            estados[dimension] = "evaluable"
    return estados


def cargar_caso(raiz_repo: Path, dataset: str, particion: str, case_id: str) -> str:
    """Lee el contenido de un caso. **No lee su ground truth.**

    El baseline recibe exactamente el mismo archivo que las otras dos
    arquitecturas: si recibiera algo distinto, la comparación mediría la
    entrada y no la arquitectura.
    """
    directorio = raiz_repo / "experiments" / "cases" / dataset / particion
    for extension in ("log", "csv"):
        archivo = directorio / f"{case_id}.{extension}"
        if archivo.is_file():
            return archivo.read_text(encoding="utf-8")
    raise FileNotFoundError(
        f"no se encontró el contenido del caso {case_id} en {directorio}"
    )
