"""Enriquecedor de Zeek / UWF-ZeekDataFall22 (Fase 6 del plan).

Se aplica sobre eventos que ya decodificó el decoder CSV (o JSON, si el
Zeek viene en ese formato): agrega la semántica de un log de FLUJOS, que
es distinta a la de un log de eventos.

`conn_state` merece una aclaración. Es contenido real del log, no una
etiqueta del dataset: Zeek lo calcula observando la conexión. Por eso sí
se conserva, como `event_outcome`. Lo que **no** se conserva en el evento
son las columnas `label_tactic`, `label_technique` y `label_binary`, que
los curadores de UWF agregaron para evaluar: esas viajan al canal de
ground truth. Un detector que las viera estaría leyendo la respuesta.
"""

from src.preprocessing.enrichers.base import Enricher
from src.preprocessing.models import GroundTruthRecord, NormalizedEvent

# Columnas que delatan un log de conexiones de Zeek.
_SENAL_ZEEK = ("conn_state", "uid", "community_id", "orig_bytes", "resp_bytes",
               "history", "orig_pkts", "resp_pkts")

# Estados de conexión que Zeek asigna a intentos rechazados o no
# establecidos. Es la observación del sensor, no una etiqueta de ataque.
_ESTADOS_FALLIDOS = {"REJ", "S0", "RSTO", "RSTR", "RSTOS0", "RSTRH", "SH", "SHR"}

# Columnas de etiqueta del dataset. NO deben quedar en el evento.
_COLUMNAS_ETIQUETA = ("label_tactic", "label_technique", "label_binary", "label")

# Valores de etiqueta que significan tráfico benigno.
_ETIQUETAS_BENIGNAS = {"", "-", "0", "false", "none", "benign", "normal", "background"}


class ZeekEnricher(Enricher):
    nombre = "zeek"
    producto = "Zeek"

    def aplica(self, evento: NormalizedEvent) -> bool:
        claves = {k.lower() for k in evento.attributes}
        return any(s in claves for s in _SENAL_ZEEK)

    def enriquecer(self, evento: NormalizedEvent) -> NormalizedEvent:
        evento.product = self.producto
        evento.vendor = "Zeek"
        evento.event_category = "network"

        attrs = {k.lower(): v for k, v in evento.attributes.items()}
        # `conn_state` es sinónimo de `event_outcome`, así que la
        # normalización ya lo movió al campo canónico y no está en
        # `attributes`. Se busca en los dos lugares para no depender de
        # por dónde llegó.
        estado = attrs.get("conn_state") or evento.event_outcome
        if estado:
            evento.event_outcome = str(estado).strip()
            # `failure`/`success` describe el resultado de la CONEXIÓN, que
            # es lo que Zeek observó. No afirma que haya un ataque.
            evento.attributes["zeek_conexion_establecida"] = (
                str(estado).strip().upper() not in _ESTADOS_FALLIDOS)

        uid = attrs.get("uid") or attrs.get("community_id")
        if uid:
            evento.attributes["flow_id"] = uid

        # Las etiquetas del dataset se retiran del evento: su lugar es el
        # canal de ground truth.
        for columna in list(evento.attributes):
            if columna.lower() in _COLUMNAS_ETIQUETA:
                evento.attributes.pop(columna, None)
        return evento

    def extraer_ground_truth(self, evento: NormalizedEvent) -> GroundTruthRecord | None:
        attrs = {k.lower(): v for k, v in evento.attributes.items()}
        # Se prefiere la táctica MITRE por ser la etiqueta más específica y
        # la de vocabulario inequívoco: `label_binary` trae valores como
        # "Duplicate" en algunos shards del dataset.
        for columna in ("label_tactic", "label", "label_binary"):
            valor = attrs.get(columna)
            if valor is None:
                continue
            texto = str(valor).strip()
            benigno = texto.lower() in _ETIQUETAS_BENIGNAS
            # `flow_id` lo escribe `enriquecer()`, que corre DESPUÉS de esta
            # extracción, así que acá se lee el identificador original tal
            # como vino del CSV. Usar `flow_id` daría siempre el fallback.
            clave = (attrs.get("uid") or attrs.get("community_id")
                     or str(evento.record_number))
            return GroundTruthRecord(
                key=str(clave),
                label="Normal" if benigno else texto,
                scope="evento",
                source="zeek",
            )
        return None
