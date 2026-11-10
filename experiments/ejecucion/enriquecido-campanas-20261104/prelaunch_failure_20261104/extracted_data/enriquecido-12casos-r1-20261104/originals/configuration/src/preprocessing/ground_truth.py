"""Canal separado de ground truth (Fase 7 del plan).

Las etiquetas de evaluación no pueden ser visibles para el detector. Suena
obvio dicho así, pero el esquema v1 lo violaba de una forma difícil de ver:
el flag de alerta que los curadores de BGL agregaron al principio de cada
línea terminaba, tras pasar por el adaptador, convertido en
`evento_critico` — la misma feature que el LLM observa para decidir si hay
una anomalía. El sistema no detectaba: leía la respuesta.

El efecto medido fue un F1 = 1.00 sobre BGL, que parecía detección
perfecta y era circularidad. El plan lo anticipa: "el F1 puede disminuir al
eliminar información filtrada desde las etiquetas. Las nuevas métricas
tendrán mayor validez metodológica".

Este módulo concentra las dos formas de obtener etiquetas:

1. **Embebidas en el log**, que los enriquecedores retiran del evento y
   entregan acá (el flag de BGL, el `label_tactic` de UWF-ZeekDataFall22).
2. **En un archivo aparte**, como el ground truth oficial de HDFS, que
   etiqueta por bloque (`blk_...`) y no por línea.

En ambos casos la etiqueta queda fuera de `PreprocessingResult.to_dict()`,
que la omite salvo pedido explícito.
"""

import csv
from pathlib import Path

from src.preprocessing.models import GroundTruthRecord, NormalizedEvent

# Nombres habituales de la columna clave y de la columna etiqueta en los
# archivos de ground truth de los datasets de la Tabla 8.11.
_COLUMNAS_CLAVE = ("blockid", "block_id", "key", "id", "uid", "event_id")
_COLUMNAS_ETIQUETA = ("label", "etiqueta", "class", "anomaly", "label_tactic")


def cargar_labels_csv(ruta: str | Path, scope: str = "bloque",
                      source: str | None = None) -> list[GroundTruthRecord]:
    """Lee un CSV de etiquetas externo (p. ej. `hdfs_anomaly_label_2k.csv`).

    Detecta las columnas de clave y etiqueta por nombre, así que sirve
    tanto para el formato `BlockId,Label` de loglizer como para variantes.
    """
    ruta = Path(ruta)
    registros: list[GroundTruthRecord] = []
    with open(ruta, encoding="utf-8", newline="") as f:
        lector = csv.DictReader(f)
        if not lector.fieldnames:
            return registros
        normalizados = {c.strip().lower(): c for c in lector.fieldnames}
        col_clave = next((normalizados[c] for c in _COLUMNAS_CLAVE
                          if c in normalizados), lector.fieldnames[0])
        col_etiqueta = next((normalizados[c] for c in _COLUMNAS_ETIQUETA
                             if c in normalizados), lector.fieldnames[-1])
        for fila in lector:
            clave = (fila.get(col_clave) or "").strip()
            etiqueta = (fila.get(col_etiqueta) or "").strip()
            if not clave or not etiqueta:
                continue
            registros.append(GroundTruthRecord(
                key=clave, label=etiqueta, scope=scope,
                source=source or ruta.name,
            ))
    return registros


def claves_de_evento(evento: NormalizedEvent) -> list[str]:
    """Claves por las que un evento puede emparejarse con una etiqueta.

    HDFS etiqueta por bloque, Zeek por identificador de flujo, y algunos
    datasets por número de registro. Se devuelven todas las disponibles
    para que el emparejamiento no dependa del dataset.
    """
    claves: list[str] = []
    for atributo in ("block_id", "flow_id"):
        valor = evento.attributes.get(atributo)
        if valor:
            claves.append(str(valor))
    if evento.record_number is not None:
        claves.append(str(evento.record_number))
    return claves


def etiquetar_eventos(eventos: list[NormalizedEvent],
                      etiquetas: list[GroundTruthRecord]) -> dict[str, str]:
    """Empareja eventos con etiquetas y devuelve el mapa clave -> etiqueta.

    **No escribe nada en los eventos**: devolver el mapa aparte es lo que
    mantiene la separación. Quien calcula métricas lo usa después del
    análisis; el detector nunca lo ve.
    """
    por_clave = {g.key: g.label for g in etiquetas}
    resultado: dict[str, str] = {}
    for evento in eventos:
        for clave in claves_de_evento(evento):
            if clave in por_clave:
                resultado[clave] = por_clave[clave]
                break
    return resultado


def verificar_aislamiento(eventos: list[NormalizedEvent],
                          etiquetas: list[GroundTruthRecord],
                          revisar_raw: bool = False) -> list[str]:
    """Busca etiquetas que se hayan filtrado a las features de un evento.

    Devuelve la lista de problemas encontrados; vacía significa que quitar
    el ground truth no cambiaría nada de lo que el detector observa, que es
    el criterio de aceptación de la fase.

    Es una comprobación barata y vale la pena mantenerla: la fuga original
    de BGL no se veía leyendo el código del adaptador, se veía comparando
    la etiqueta contra la feature.

    **`revisar_raw` merece una explicación.** En datasets como BGL la
    etiqueta está escrita en la propia línea (el primer token), así que
    `raw` la contiene por definición: preservar el registro original y
    ocultar la etiqueta son objetivos que ahí se contradicen. Se resuelve
    conservando `raw` —hace falta para auditar y para el reporte— y
    prohibiendo que llegue al detector: las muestras de texto crudo que se
    envían al LLM deben excluirse cuando el lote trae ground truth
    embebido. Con `revisar_raw=True` esta función reporta esa vía, que es
    la forma de comprobar que la agregación (Fase 8) no la abrió.
    """
    problemas: list[str] = []
    valores_etiqueta = {g.label.strip().lower() for g in etiquetas
                        if g.label and g.label.strip().lower() not in ("normal",)}
    if not valores_etiqueta:
        return problemas

    for evento in eventos:
        # Ningún campo semántico ni atributo debe contener el valor de la
        # etiqueta, ni una columna llamarse como ella.
        for clave, valor in evento.attributes.items():
            if clave.strip().lower() in ("label", "label_tactic",
                                         "label_binary", "label_technique"):
                problemas.append(
                    f"registro {evento.record_number}: el atributo {clave!r} "
                    "es una columna de ground truth y quedó en el evento"
                )
            if isinstance(valor, str) and valor.strip().lower() in valores_etiqueta:
                problemas.append(
                    f"registro {evento.record_number}: el atributo {clave!r} "
                    f"contiene el valor de una etiqueta ({valor!r})"
                )
        for campo in ("event_category", "event_outcome", "severity",
                      "event_action"):
            valor = getattr(evento, campo, None)
            if isinstance(valor, str) and valor.strip().lower() in valores_etiqueta:
                problemas.append(
                    f"registro {evento.record_number}: el campo {campo} "
                    f"contiene el valor de una etiqueta ({valor!r})"
                )
    if revisar_raw:
        # La vía del texto crudo no se detecta buscando el VALOR de la
        # etiqueta: el enriquecedor la normaliza ("Alert"/"Normal") mientras
        # que el crudo conserva el código original del dataset ("APPREAD",
        # "KERNDTLB"). La regla correcta es de lote: si las etiquetas venían
        # embebidas en la línea, entonces `raw` las contiene por
        # construcción y no puede muestrearse hacia el detector.
        embebidas = sorted({g.source for g in etiquetas
                            if g.source in ("bgl", "zeek")})
        if embebidas:
            problemas.append(
                "el lote trae ground truth embebido en la propia línea "
                f"(origen: {', '.join(embebidas)}); el texto crudo lo "
                "contiene y no debe enviarse como muestra al detector"
            )
    return problemas
