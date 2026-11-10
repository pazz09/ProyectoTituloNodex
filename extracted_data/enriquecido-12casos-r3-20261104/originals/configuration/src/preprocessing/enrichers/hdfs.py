"""Enriquecedor de Hadoop HDFS (Fase 6 del plan).

Extrae del log de HDFS: timestamp, clase Java, nivel y block id — como una
capa **opcional** sobre un evento ya decodificado, no como el parser que
define el lote.

Dos decisiones que importan:

- El `blk_...` no ocupa el campo `usuario`. Un block id no es una persona;
  va a `attributes["block_id"]`, que además es la clave con la que el
  ground truth oficial de HDFS etiqueta (por bloque, no por línea).
- El nivel `WARN`/`ERROR`/`FATAL` se guarda como `severity`, que es lo que
  el log declara, y no se convierte en `evento_critico`. Esa traducción de
  "nivel alto" a "evento crítico" sería una decisión de detección tomada en
  el preprocesamiento, y es justamente lo que este enriquecedor evita.
"""

import re

from src.preprocessing.enrichers.base import Enricher
from src.preprocessing.models import NormalizedEvent

_HDFS_RE = re.compile(
    r"^(?P<fecha>\d{6})\s+(?P<hora>\d{6})\s+(?P<hilo>\d+)\s+"
    r"(?P<nivel>INFO|WARN|ERROR|FATAL)\s+(?P<clase>\S+):\s*(?P<msg>.*)$"
)

_CLASE_A_SERVICIO = {
    "dfs.DataNode$PacketResponder": "hdfs.datanode",
    "dfs.DataNode$DataXceiver": "hdfs.datanode",
    "dfs.DataNode$BlockReceiver": "hdfs.datanode",
    "dfs.DataNode": "hdfs.datanode",
    "dfs.FSNamesystem": "hdfs.fsnamesystem",
    "dfs.FSDataset": "hdfs.fsdataset",
    "dfs.DataBlockScanner": "hdfs.datablockscanner",
}

_BLOCK_RE = re.compile(r"(blk_-?\d+)")
_IP_PUERTO_RE = re.compile(r"\b(\d{1,3}(?:\.\d{1,3}){3}):(\d+)\b")


class HdfsEnricher(Enricher):
    nombre = "hdfs"
    producto = "HDFS"

    def aplica(self, evento: NormalizedEvent) -> bool:
        return bool(_HDFS_RE.match(evento.raw.split("\n", 1)[0]))

    def enriquecer(self, evento: NormalizedEvent) -> NormalizedEvent:
        m = _HDFS_RE.match(evento.raw.split("\n", 1)[0])
        if not m:
            return evento

        fecha, hora = m.group("fecha"), m.group("hora")
        evento.timestamp = (
            f"20{fecha[0:2]}-{fecha[2:4]}-{fecha[4:6]} "
            f"{hora[0:2]}:{hora[2:4]}:{hora[4:6]}"
        )
        evento.severity = m.group("nivel")
        evento.product = self.producto
        evento.vendor = "Apache"
        clase = m.group("clase")
        evento.service_name = _CLASE_A_SERVICIO.get(clase, "hdfs.otro")
        evento.process_name = clase
        evento.message = m.group("msg") or evento.message
        evento.attributes["hdfs_clase"] = clase
        evento.attributes["hdfs_hilo"] = m.group("hilo")

        bloque = _BLOCK_RE.search(evento.raw)
        if bloque:
            # Clave del ground truth oficial de HDFS, que etiqueta por
            # bloque y no por línea.
            evento.attributes["block_id"] = bloque.group(1)

        # Las direcciones de HDFS vienen como ip:puerto dentro del mensaje.
        puntos = _IP_PUERTO_RE.findall(evento.message)
        if puntos:
            evento.source_ip, puerto = puntos[0][0], puntos[0][1]
            evento.source_port = int(puerto)
            if len(puntos) > 1:
                evento.destination_ip = puntos[1][0]
                evento.destination_port = int(puntos[1][1])
        return evento
