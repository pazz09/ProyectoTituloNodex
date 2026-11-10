"""Decoder CSV / TSV y otros delimitadores (Fase 4 del plan).

Generaliza el adaptador CSV del esquema v1, con dos diferencias
importantes:

1. **La cabecera vive en el contexto del segmento**, no en el decoder.
   En v1 el adaptador guardaba la cabecera en el objeto, así que hubo que
   instanciarlo por lote para que dos análisis simultáneos de la interfaz
   web no se pisaran. Acá el decoder es sin estado por construcción, y
   además permite que un mismo archivo contenga dos CSV con cabeceras
   distintas: cada segmento lleva la suya.

2. **No decide sobre ataques.** El adaptador v1 leía la columna de
   etiqueta del dataset (`label_tactic`) y la convertía en
   `evento_critico`, o sea que el ground truth alimentaba la feature que
   el detector observa. Acá la etiqueta se conserva como un atributo más;
   separarla al canal de ground truth es trabajo de la Fase 7.
"""

import csv

from src.preprocessing.decoders.base import Decoder
from src.preprocessing.models import NormalizedEvent, ParsingWarning
from src.preprocessing.normalization import mapear_campos, normalizar_nombre
from src.preprocessing.segmentation import RawRecord

DELIMITADORES = (",", ";", "\t", "|")

# Nombres de columna que delatan una cabecera: si aparece alguno, la fila
# es la cabecera del segmento y no un registro de datos.
_SENAL_CABECERA = {
    "ts", "timestamp", "datetime", "time", "date",
    "src_ip", "source_ip", "src_ip_zeek", "id.orig_h", "srcip",
    "dest_ip", "dst_ip", "destination_ip", "dest_ip_zeek", "id.resp_h",
    "proto", "protocol", "service", "conn_state", "uid", "community_id",
    "event_id", "severity", "level", "action", "user", "username",
}


def partir(linea: str, delim: str) -> list[str]:
    try:
        return next(csv.reader([linea], delimiter=delim))
    except (StopIteration, csv.Error):
        return []


def detectar_cabecera(linea: str) -> tuple[str, list[str]] | None:
    """¿Esta línea es una cabecera CSV? Devuelve (delimitador, columnas).

    Se exige una señal explícita —al menos un nombre de columna conocido—
    en vez de aceptar cualquier línea con comas: una frase con comas no es
    una cabecera, y tratarla como tal desalinearía todo el segmento.
    """
    mejor = None
    for delim in DELIMITADORES:
        columnas = partir(linea, delim)
        if len(columnas) < 2:
            continue
        normalizadas = {normalizar_nombre(c) for c in columnas}
        if not (normalizadas & _SENAL_CABECERA):
            continue
        if mejor is None or len(columnas) > len(mejor[1]):
            mejor = (delim, columnas)
    return mejor


class CsvDecoder(Decoder):
    nombre = "csv"

    def detectar(self, texto: str, contexto: dict | None = None) -> float:
        ctx = contexto or {}
        cabecera = ctx.get("csv_cabecera")
        delim = ctx.get("csv_delimitador")
        if not cabecera or not delim:
            # Sin cabecera en el segmento no hay forma de interpretar
            # posicionalmente: que decida otro decoder.
            return 0.0
        campos = partir(texto, delim)
        if not campos:
            return 0.0
        if len(campos) == len(cabecera):
            return 0.95
        # Fila con cantidad de columnas distinta: probablemente corrupta o
        # de otro segmento. Confianza baja para que el híbrido la reprocese.
        return 0.2

    def decodificar(self, registro: RawRecord,
                    contexto: dict | None = None) -> NormalizedEvent:
        ctx = contexto or {}
        cabecera = ctx.get("csv_cabecera") or []
        delim = ctx.get("csv_delimitador") or ","
        campos = partir(registro.raw, delim)

        if not cabecera:
            ev = self._evento_base(registro, registro.raw, 0.2)
            ev.warnings.append(ParsingWarning(
                codigo="csv_sin_cabecera",
                mensaje="Fila CSV sin cabecera conocida en su segmento.",
                line_start=registro.line_start,
            ))
            return ev

        confianza = 0.95
        if len(campos) != len(cabecera):
            confianza = 0.2

        datos = {}
        for i, nombre in enumerate(cabecera):
            datos[nombre] = campos[i] if i < len(campos) else None
        sobrantes = campos[len(cabecera):]

        canonicos, atributos = mapear_campos(
            datos, max_no_mapeados=ctx.get("max_no_mapeados"))
        mensaje = canonicos.pop("message", None) or registro.raw
        ev = self._evento_base(registro, mensaje, confianza)
        for campo, valor in canonicos.items():
            setattr(ev, campo, valor)
        ev.attributes.update(atributos)

        if len(campos) != len(cabecera):
            ev.warnings.append(ParsingWarning(
                codigo="csv_columnas_desalineadas",
                mensaje=(
                    f"La fila trae {len(campos)} columnas y la cabecera "
                    f"{len(cabecera)}."
                ),
                line_start=registro.line_start,
            ))
            if sobrantes:
                ev.attributes["_columnas_sobrantes"] = sobrantes
        return ev
