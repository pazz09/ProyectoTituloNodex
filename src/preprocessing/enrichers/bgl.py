"""Enriquecedor de BlueGene/L (Fase 6 del plan).

Extrae del log de BGL: nodo del clúster, subsistema RAS y severidad
declarada.

**El punto más importante de este enriquecedor.** El primer campo de la
línea —el flag de alerta que los curadores del dataset agregaron: `-` para
no-alerta, un código como `KERNDTLB` para alerta— NO se traduce en
`evento_critico`, la feature que el detector observa. Traducirlo así sería
fuga de ground truth: el sistema "detectaría" anomalías leyendo la
respuesta que el dataset trae escrita, en vez de razonar sobre el log.

Y no era una sutileza teórica. Explicaba el F1 = 1.00 medido sobre BGL,
que parecía una detección perfecta y en realidad medía si el LLM repetía
fielmente una señal que el parser ya le había entregado.

Acá el flag sale por `extraer_ground_truth()` hacia el canal separado, y
**no** queda en el evento. Los campos que sí quedan son los que el log
declara por sí mismo: nodo, subsistema y severidad.
"""

import re

from src.preprocessing.enrichers.base import Enricher
from src.preprocessing.models import GroundTruthRecord, NormalizedEvent

# flag epoch fecha nodo timestamp nodo_repetido RAS subsistema severidad mensaje
_BGL_RE = re.compile(
    r"^(?P<flag>\S+)\s+(?P<epoch>\d+)\s+(?P<fecha>\d{4}\.\d{2}\.\d{2})\s+"
    r"(?P<nodo>\S+)\s+(?P<ts>\d{4}-\d{2}-\d{2}-\d{2}\.\d{2}\.\d{2}\.\d+)\s+"
    r"(?P<nodo2>\S+)\s+(?P<tipo>\S+)\s+(?P<subsistema>\S+)\s+"
    r"(?P<severidad>\S+)\s+(?P<msg>.*)$"
)

# Misma línea con el campo de alerta OPCIONAL (`BGL_ALERTA_OPCIONAL`, NODEX
# final Fase A). El generador de casos retira ese campo para no filtrar la
# etiqueta, así que la línea empieza por el epoch y `_BGL_RE` no calzaba
# nunca: el enriquecedor no se aplicaba y la cobertura de BGL era 0 %. El
# campo, cuando está, solo puede ser `-` o un código en mayúsculas (así lo
# escribe el dataset); nunca un número, para no confundirlo con el epoch.
_BGL_RE_OPCIONAL = re.compile(
    r"^(?:(?P<flag>-|[A-Z][A-Z0-9_]*)\s+)?(?P<epoch>\d+)\s+(?P<fecha>\d{4}\.\d{2}\.\d{2})\s+"
    r"(?P<nodo>\S+)\s+(?P<ts>\d{4}-\d{2}-\d{2}-\d{2}\.\d{2}\.\d{2}\.\d+)\s+"
    r"(?P<nodo2>\S+)\s+(?P<tipo>\S+)\s+(?P<subsistema>\S+)\s+"
    r"(?P<severidad>\S+)\s+(?P<msg>.*)$"
)
_FLAG_BGL = re.compile(r"-|[A-Z][A-Z0-9_]*")


def _patron():
    from src.config import BGL_ALERTA_OPCIONAL
    return _BGL_RE_OPCIONAL if BGL_ALERTA_OPCIONAL else _BGL_RE


_SUBSISTEMA_A_SERVICIO = {
    "KERNEL": "bgl.kernel",
    "APP": "bgl.app",
    "MMCS": "bgl.mmcs",
    "DISCOVERY": "bgl.discovery",
    "HARDWARE": "bgl.hardware",
    "LINKCARD": "bgl.linkcard",
    "MONITOR": "bgl.monitor",
}

# Valor del primer campo que significa "esta línea no es una alerta".
SIN_ALERTA = "-"


class BglEnricher(Enricher):
    nombre = "bgl"
    producto = "BlueGene/L"

    def aplica(self, evento: NormalizedEvent) -> bool:
        return bool(_patron().match(evento.raw.split("\n", 1)[0]))

    def enriquecer(self, evento: NormalizedEvent) -> NormalizedEvent:
        m = _patron().match(evento.raw.split("\n", 1)[0])
        if not m:
            return evento

        evento.timestamp = m.group("ts")
        evento.product = self.producto
        evento.vendor = "IBM"
        evento.source_host = m.group("nodo")
        subsistema = m.group("subsistema")
        evento.service_name = _SUBSISTEMA_A_SERVICIO.get(
            subsistema, f"bgl.{subsistema.lower()}")
        evento.severity = m.group("severidad")
        evento.message = m.group("msg") or evento.message
        evento.attributes["bgl_subsistema"] = subsistema
        evento.attributes["bgl_tipo"] = m.group("tipo")
        evento.attributes["bgl_nodo"] = m.group("nodo")
        # El flag NO se copia al evento: es la etiqueta del dataset y viaja
        # por `extraer_ground_truth()`.
        return evento

    def extraer_ground_truth(self, evento: NormalizedEvent) -> GroundTruthRecord | None:
        """El flag de alerta del dataset, hacia el canal separado.

        Se lee del primer token del texto crudo, no del match completo:
        algunas variantes de línea (`NULL DISCOVERY ...` en vez de
        `RAS KERNEL INFO ...`) no matchean el patrón entero, y leer el flag
        solo del match perdería esas alertas. Es el mismo hallazgo que se
        corrigió en el adaptador v1 el 24-ago-2026.
        """
        partes = evento.raw.split(None, 1)
        if not partes:
            return None
        flag = partes[0]
        from src.config import BGL_ALERTA_OPCIONAL
        if BGL_ALERTA_OPCIONAL and not _FLAG_BGL.fullmatch(flag):
            # La línea no trae el campo de alerta (el generador lo retiró):
            # no hay etiqueta que desviar. Leer el epoch como flag marcaría
            # todas las líneas como alerta y, además, activaría la regla que
            # oculta las muestras por "ground truth embebido".
            return None
        # La clave se arma SOLO con lo disponible antes del enriquecimiento:
        # `bgl_nodo` lo escribe `enriquecer()`, que corre después, así que
        # usarlo acá daría siempre el fallback. BGL etiqueta por evento, y
        # el número de registro es su identificador natural.
        return GroundTruthRecord(
            key=str(evento.record_number),
            label="Alert" if flag != SIN_ALERTA else "Normal",
            scope="evento",
            source="bgl",
        )
