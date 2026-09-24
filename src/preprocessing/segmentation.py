"""Segmentación de líneas físicas en registros lógicos (Fase 3 del plan).

Separa dos cosas que el esquema v1 confundía: una **línea física** del
archivo y un **registro lógico** que el sistema debe analizar. Un stack
trace de treinta líneas es un solo evento; en v1 inflaba el conteo por
treinta y podía inclinar cualquier estadística del lote.

Una línea continúa el registro anterior cuando ocurre alguna de estas cosas:

1. **JSON abierto**: el registro empezó con `{` o `[` y las llaves no
   cierran todavía. El conteo ignora llaves dentro de cadenas y escapes,
   porque un mensaje que contenga `"{"` no debería abrir un objeto.
2. **Indentación**: la línea empieza con espacio o tabulador, que es la
   convención de casi todos los stack traces.
3. **Marcadores conocidos**: `at `, `Caused by:`, `... N more`, `Traceback`.
4. **Regla de inicio de registro**: el registro abierto empezó con un
   patrón reconocible (timestamp, PRI de syslog, JSON, CEF/LEEF) y esta
   línea no lo tiene. Es la regla que usan los recolectores de logs
   reales, y la única que salva el caso más común: la línea con la clase
   de la excepción (`java.lang.NullPointerException: ...`) va pegada al
   margen, sin indentar y sin marcador.

Nada se descarta en silencio: las líneas en blanco se cuentan pero no
generan registros, y una línea de continuación que aparece sin un registro
previo al cual adherirse se emite como registro propio con una advertencia.
"""

import re
from dataclasses import dataclass, field

from src.preprocessing.models import ParsingWarning

# Marcadores de continuación que suelen venir SIN indentación.
_CONTINUACION_RE = re.compile(
    r"^(at\s+\S|caused\s+by:|\.{3}\s*\d+\s+more|traceback\s+\(most\s+recent)",
    re.IGNORECASE,
)

# Patrones que delatan el COMIENZO de un registro nuevo. La lista es
# deliberadamente conservadora: si un formato no aparece acá, cada una de
# sus líneas se trata como un registro propio, que es el comportamiento
# seguro. Reconocer de menos degrada al comportamiento v1; reconocer de más
# pegotearía registros distintos, que sí sería una pérdida de información.
_INICIO_REGISTRO_RE = re.compile(
    r"^("
    r"<\d{1,3}>"                                     # syslog RFC 5424 (PRI)
    r"|\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}"       # ISO-8601
    r"|\d{4}/\d{2}/\d{2}\s+\d{2}:\d{2}:\d{2}"        # 2024/01/02 10:00:00
    r"|[A-Z][a-z]{2}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}"  # syslog BSD
    r"|\d{6}\s+\d{6}\s"                              # HDFS: 081109 203615
    r"|\d{10}(\.\d+)?\s"                             # epoch
    r"|\[\d{4}-\d{2}-\d{2}"                          # [2024-01-02 ...]
    r"|[{\[]"                                        # JSON
    r"|CEF:|LEEF:"                                   # CEF / LEEF
    r"|[A-Za-z_][\w.\-]*=\S"                          # clave=valor (firewalls, logfmt)
    r"|\S+\s+\d{9,11}\s+\d{4}\.\d{2}\.\d{2}\s"        # BGL: flag epoch fecha
    r")"
)

# Subconjunto del anterior: formatos cuyo registro PUEDE extenderse a
# varias líneas sin indentación. Syslog y los logs de aplicación con
# timestamp al inicio sí; CEF, LEEF, JSON y las filas CSV NO, porque son
# formatos autodelimitados -- un registro CEF es exactamente una línea,
# así que la línea siguiente nunca puede ser su continuación. Sin esta
# distinción, un CEF seguido de un registro de otro formato se lo tragaba.
_PERMITE_CONTINUACION_RE = re.compile(
    r"^("
    r"<\d{1,3}>"                                     # syslog RFC 5424 (PRI)
    r"|\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}"      # ISO-8601
    r"|\d{4}/\d{2}/\d{2}\s+\d{2}:\d{2}:\d{2}"       # 2024/01/02 10:00:00
    r"|[A-Z][a-z]{2}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}"  # syslog BSD
    r"|\d{6}\s+\d{6}\s"                            # HDFS
    r"|\[\d{4}-\d{2}-\d{2}"                         # [2024-01-02 ...]
    r")"
)


@dataclass
class RawRecord:
    """Un registro lógico todavía sin decodificar.

    Conserva el texto tal cual apareció y las líneas físicas que ocupó, para
    que cualquier advertencia posterior pueda señalar el lugar exacto del
    archivo.
    """

    raw: str
    line_start: int
    line_end: int
    is_multiline: bool = False
    record_number: int = 0
    warnings: list[ParsingWarning] = field(default_factory=list)

    @property
    def n_lineas(self) -> int:
        return self.line_end - self.line_start + 1


@dataclass
class SegmentationResult:
    records: list[RawRecord] = field(default_factory=list)
    total_lineas_fisicas: int = 0
    lineas_en_blanco: int = 0
    warnings: list[ParsingWarning] = field(default_factory=list)
    truncado: bool = False

    @property
    def lineas_contabilizadas(self) -> int:
        """Toda línea física debe terminar en un registro o contarse como
        vacía. Si esto no coincide con `total_lineas_fisicas`, se perdió
        contenido, que es justamente lo que el criterio de aceptación
        prohíbe. (No aplica si el lote se truncó por límite de eventos.)"""
        return sum(r.n_lineas for r in self.records) + self.lineas_en_blanco


def _abre_json(texto: str) -> bool:
    t = texto.lstrip()
    return t.startswith("{") or t.startswith("[")


def _balance_json(texto: str, balance_previo: int = 0) -> int:
    """Cuenta llaves y corchetes ignorando lo que esté dentro de cadenas.

    Un mensaje como `{"msg": "se recibio { sin cerrar"}` no debe quedar
    abierto y tragarse el resto del archivo.
    """
    balance = balance_previo
    en_cadena = False
    escapado = False
    for ch in texto:
        if escapado:
            escapado = False
            continue
        if ch == "\\":
            escapado = True
            continue
        if ch == '"':
            en_cadena = not en_cadena
            continue
        if en_cadena:
            continue
        if ch in "{[":
            balance += 1
        elif ch in "}]":
            balance -= 1
    return balance


def _parece_inicio_de_registro(linea: str) -> bool:
    return bool(_INICIO_REGISTRO_RE.match(linea))


def _permite_continuacion(linea: str) -> bool:
    """¿Un registro que empieza así puede seguir en las líneas siguientes?

    Solo los formatos con timestamp al inicio. CEF, LEEF, JSON y CSV son
    autodelimitados: su registro termina donde termina la línea (o donde
    cierran las llaves), así que aplicarles la regla 4 haría que se
    tragaran el registro siguiente.
    """
    return bool(_PERMITE_CONTINUACION_RE.match(linea))


def _es_continuacion(linea: str, inicio_reconocido: bool = False) -> bool:
    """¿Esta línea continúa el registro anterior?

    `inicio_reconocido` indica si el registro abierto empezó con un patrón
    de inicio conocido. Solo en ese caso se aplica la regla 4 del módulo:
    sin ella, un stack trace se parte en la primera línea sin indentar.
    """
    if linea[:1] in (" ", "\t"):
        return True
    if _CONTINUACION_RE.match(linea):
        return True
    if inicio_reconocido and not _parece_inicio_de_registro(linea):
        return True
    return False


def segmentar(
    texto: str,
    enable_multiline: bool = True,
    max_eventos: int | None = None,
) -> SegmentationResult:
    """Divide `texto` en registros lógicos.

    Con `enable_multiline=False` cada línea no vacía es un registro, que es
    el comportamiento del esquema v1 y sirve de control para comparar.

    `max_eventos` RECHAZA el lote (lanza `ValueError`) en vez de procesar
    un archivo desmedido en silencio (§14 del plan) -- misma política que
    el límite de bytes en `preprocesar()` (M6, Fase 4 del cierre de
    auditoría, 23-sep-2026: antes truncaba con una advertencia, la API
    ya rechazaba el mismo caso por bytes; ahora los dos caminos coinciden).
    """
    lineas = texto.splitlines()
    res = SegmentationResult(total_lineas_fisicas=len(lineas))

    actual: RawRecord | None = None
    balance = 0
    inicio_reconocido = False

    def cerrar() -> None:
        nonlocal actual, balance
        if actual is not None:
            actual.is_multiline = actual.n_lineas > 1
            actual.record_number = len(res.records) + 1
            res.records.append(actual)
        actual = None
        balance = 0

    for i, linea in enumerate(lineas, start=1):
        if not linea.strip():
            res.lineas_en_blanco += 1
            # Una línea en blanco cierra un JSON multilínea sin terminar:
            # seguir acumulando arrastraría el resto del archivo.
            if actual is not None and balance > 0:
                actual.warnings.append(ParsingWarning(
                    codigo="json_sin_cerrar",
                    mensaje="El objeto JSON no cerró antes de una línea en blanco.",
                    severidad="warning",
                    line_start=actual.line_start,
                ))
                cerrar()
            continue

        if max_eventos is not None and len(res.records) >= max_eventos:
            # M6 (Fase 4 del cierre de auditoría, 23-sep-2026): rechaza, no
            # trunca -- misma política que el límite de bytes en
            # preprocesar(). `ValueError` porque este módulo no depende de
            # `pipeline.py` (evitaría un import circular); el llamador
            # (_preprocesar_y_agregar, src/tools/aggregation.py) ya envuelve
            # cualquier excepción del preprocesamiento en
            # `PreprocesamientoError` con un mensaje claro.
            raise ValueError(
                f"El lote tiene más de {max_eventos} eventos "
                f"(LOG_MAX_EVENTS); se alcanzó el límite en la línea {i} "
                f"de {len(lineas)}. Subí un lote más chico o ajustá esa "
                "variable."
            )

        if not enable_multiline:
            actual = RawRecord(raw=linea, line_start=i, line_end=i)
            cerrar()
            continue

        # Un JSON que quedó abierto no debe tragarse el registro siguiente.
        # Pasa con una línea truncada a mitad de archivo: la comilla sin
        # cerrar deja el balance en positivo y, sin este corte, todo lo que
        # venga después se acumula en el registro roto. Una línea SIN
        # indentar que empieza un registro nuevo cierra el anterior; las
        # continuaciones legítimas de un JSON multilínea vienen indentadas,
        # así que no se ven afectadas.
        if (actual is not None and balance > 0
                and linea[:1] not in (" ", "\t")
                and _parece_inicio_de_registro(linea)):
            actual.warnings.append(ParsingWarning(
                codigo="json_sin_cerrar",
                mensaje=("El registro quedó sin cerrar y la línea siguiente "
                         "empieza uno nuevo; se cierra acá para no absorberlo."),
                severidad="warning",
                line_start=actual.line_start,
            ))
            cerrar()

        continua = (
            actual is not None
            and (balance > 0 or _es_continuacion(linea, inicio_reconocido))
        )

        if continua:
            actual.raw += "\n" + linea
            actual.line_end = i
            if balance > 0:
                balance = _balance_json(linea, balance)
                if balance <= 0:
                    cerrar()
            continue

        # Empieza un registro nuevo.
        cerrar()
        if _es_continuacion(linea):
            # Continuación sin nada a lo que adherirse: no se descarta, se
            # emite sola y se deja constancia.
            huerfana = RawRecord(raw=linea, line_start=i, line_end=i)
            huerfana.warnings.append(ParsingWarning(
                codigo="continuacion_huerfana",
                mensaje="Línea de continuación sin un registro previo al cual unirse.",
                severidad="info",
                line_start=i,
            ))
            actual = huerfana
            inicio_reconocido = False
            cerrar()
            continue

        # El registro queda ABIERTO a propósito: la línea siguiente puede ser
        # una continuación. Se cierra al ver que no lo es, o al terminar.
        actual = RawRecord(raw=linea, line_start=i, line_end=i)
        inicio_reconocido = _permite_continuacion(linea)
        if _abre_json(linea):
            balance = _balance_json(linea)
            if balance <= 0:
                cerrar()

    if res.truncado:
        # El registro que quedó abierto al alcanzar el límite se descarta:
        # ya hay constancia del corte y de la línea exacta donde ocurrió.
        actual = None

    if actual is not None:
        if balance > 0:
            actual.warnings.append(ParsingWarning(
                codigo="json_sin_cerrar",
                mensaje="El objeto JSON no cerró antes del fin del lote.",
                severidad="warning",
                line_start=actual.line_start,
            ))
        cerrar()

    return res
