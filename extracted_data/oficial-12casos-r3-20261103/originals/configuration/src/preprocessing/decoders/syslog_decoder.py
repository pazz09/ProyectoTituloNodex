"""Decoder syslog RFC 3164 (BSD) y RFC 5424 (Fase 4 del plan).

Es el formato de sistema más extendido en Linux y equipos de red, y el
segmento PyME al que apunta el proyecto lo va a traer casi siempre. El
adaptador auth-log del esquema v1 entendía **solo** la variante BSD sin
prioridad y le pegaba una clasificación de servicio por palabras clave;
acá se parsea la estructura del estándar y la semántica queda para los
agentes.

RFC 3164:  `<134>Jan 10 13:55:36 srv sshd[1234]: mensaje`
RFC 5424:  `<134>1 2024-01-02T10:00:00Z srv sshd 1234 ID [sd] mensaje`

El PRI (`<134>`) es opcional en la práctica: muchos archivos ya vienen sin
él porque el recolector lo consumió.
"""

import re

from src.preprocessing.decoders.base import Decoder
from src.preprocessing.models import NormalizedEvent
from src.preprocessing.normalization import ips_del_texto
from src.preprocessing.segmentation import RawRecord

# <PRI>VERSION TIMESTAMP HOST APP PROCID MSGID [SD] MSG
_RFC5424_RE = re.compile(
    r"^<(?P<pri>\d{1,3})>(?P<version>\d)\s+"
    r"(?P<ts>\S+)\s+(?P<host>\S+)\s+(?P<app>\S+)\s+"
    r"(?P<procid>\S+)\s+(?P<msgid>\S+)\s+"
    r"(?P<resto>.*)$"
)

# [<PRI>]Mmm dd hh:mm:ss HOST TAG[PID]: MSG
_RFC3164_RE = re.compile(
    r"^(?:<(?P<pri>\d{1,3})>)?"
    r"(?P<ts>[A-Z][a-z]{2}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})\s+"
    r"(?P<host>\S+)\s+"
    r"(?P<tag>[^\s:\[]+)(?:\[(?P<pid>\d+)\])?:\s*"
    r"(?P<resto>.*)$"
)

_SEVERIDADES = ("emerg", "alert", "crit", "err", "warning", "notice", "info", "debug")


def _severidad_de_pri(pri: str | None) -> str | None:
    """El PRI codifica facility*8 + severity. Se traduce la severidad."""
    if pri is None:
        return None
    try:
        return _SEVERIDADES[int(pri) % 8]
    except (ValueError, IndexError):
        return None


class SyslogDecoder(Decoder):
    nombre = "syslog"

    def detectar(self, texto: str, contexto: dict | None = None) -> float:
        linea = texto.split("\n", 1)[0]
        if _RFC5424_RE.match(linea):
            return 1.0
        m = _RFC3164_RE.match(linea)
        if m:
            # Con PRI explícito no hay ambigüedad posible.
            return 0.95 if m.group("pri") else 0.85
        return 0.0

    def decodificar(self, registro: RawRecord,
                    contexto: dict | None = None) -> NormalizedEvent:
        linea = registro.raw.split("\n", 1)[0]

        m = _RFC5424_RE.match(linea)
        if m:
            ev = self._evento_base(registro, m.group("resto").strip(), 1.0)
            ev.timestamp = m.group("ts")
            ev.source_host = m.group("host")
            ev.process_name = m.group("app")
            ev.service_name = m.group("app")
            if m.group("procid") != "-":
                ev.process_id = m.group("procid")
            if m.group("msgid") != "-":
                ev.event_code = m.group("msgid")
            ev.severity = _severidad_de_pri(m.group("pri"))
            ev.attributes["syslog_rfc"] = "5424"
            self._ips(ev)
            return ev

        m = _RFC3164_RE.match(linea)
        if m:
            confianza = 0.95 if m.group("pri") else 0.85
            ev = self._evento_base(registro, m.group("resto").strip(), confianza)
            ev.timestamp = m.group("ts")
            ev.source_host = m.group("host")
            ev.process_name = m.group("tag")
            ev.service_name = m.group("tag")
            if m.group("pid"):
                ev.process_id = m.group("pid")
            ev.severity = _severidad_de_pri(m.group("pri"))
            ev.attributes["syslog_rfc"] = "3164"
            self._ips(ev)
            return ev

        # No debería llegar acá si la detección hizo su trabajo.
        return self._evento_base(registro, linea, 0.0)

    @staticmethod
    def _ips(ev: NormalizedEvent) -> None:
        """La IP del cliente suele venir en el texto del mensaje, no en un
        campo propio. Se extrae, pero sin inventar dirección al flujo."""
        ips = ips_del_texto(ev.message)
        if ips:
            ev.source_ip = ips[0]
            if len(ips) > 1:
                ev.attributes["ips_detectadas"] = ips
