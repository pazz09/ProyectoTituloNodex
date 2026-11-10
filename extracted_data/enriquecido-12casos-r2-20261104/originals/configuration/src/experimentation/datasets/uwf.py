"""Conversión offline de UWF-ZeekDataFall22: Parquet → CSV.

**Es el único módulo del proyecto que importa `pyarrow`**, y corre una sola
vez, fuera de cualquier experimento. Autorización del 3-oct-2026: pyarrow
vive en `requirements-experimentacion.txt` y en `.venv-preparacion`, nunca
en las dependencias de producción. Después de esta conversión los
experimentos consumen **solo** los CSV generados y sus SHA-256.

La conversión separa físicamente dos cosas que en el Parquet viajan juntas:

- `eventos/` — las 22 columnas de `conn.log` de Zeek. Es lo único que puede
  llegar a una arquitectura o al RAG.
- `etiquetas/` — `uid`, `label_binary`, `label_tactic`, `label_technique`.
  Es lo único que puede llegar a un evaluador.

Tres decisiones del 3-oct-2026 quedan implementadas acá:

1. Los registros con `label_binary == "Duplicate"` se **excluyen** y se
   cuenta cuántos (decisión D-9).
2. Las tres columnas de etiqueta nunca entran al CSV de eventos.
3. `uid` es la clave de referencia para el matching de reconstrucción.

Sobre `uid`: se repite 37 423 veces en el dataset, pero **no hay ninguna
colisión real**. Se verificó comparando los 9 campos que identifican el
flujo (`ts`, IPs, puertos, proto, duración, bytes): las filas que comparten
`uid` comparten también la firma completa del flujo, es decir son la misma
conexión etiquetada más de una vez. Por eso deduplicar por `uid` es
correcto y no pierde eventos, siempre que las etiquetas se **unan** en vez
de quedarse con una sola.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

#: Las 22 columnas de Zeek. Es una allowlist, no una denylist: si el
#: dataset ganara una columna de etiqueta nueva, no entraría al CSV de
#: eventos por omisión.
COLUMNAS_EVENTO = (
    "uid", "ts", "datetime", "src_ip_zeek", "src_port_zeek", "dest_ip_zeek",
    "dest_port_zeek", "proto", "service", "duration", "orig_bytes",
    "resp_bytes", "conn_state", "local_orig", "local_resp", "missed_bytes",
    "history", "orig_pkts", "orig_ip_bytes", "resp_pkts", "resp_ip_bytes",
    "community_id",
)

#: Columnas de referencia. Van al CSV de etiquetas y a ningún otro lado.
COLUMNAS_ETIQUETA = ("label_binary", "label_tactic", "label_technique")

#: Valor de `label_binary` que no es clasificable. Decisión del 3-oct-2026:
#: se excluye del conjunto experimental.
VALOR_EXCLUIDO = "Duplicate"

#: Valores de `label_binary` que sí son clasificables.
VALOR_BENIGNO, VALOR_MALICIOSO = "False", "True"

#: Valor de `label_tactic` / `label_technique` que significa "sin ataque".
SIN_ATAQUE = "none"

#: Separador de etiquetas unidas. Una conexión puede tener más de una
#: táctica: 2 930 `uid` tienen dos y uno tiene tres.
SEPARADOR_ETIQUETAS = "|"


@dataclass
class ResumenConversion:
    """Contabilidad de un shard. Todo esto va al manifiesto."""

    semana: str
    archivo_parquet: str
    sha256_parquet: str
    filas_parquet: int = 0
    #: Excluidas por `label_binary == "Duplicate"` (decisión D-9).
    filas_excluidas_duplicate: int = 0
    #: Filas colapsadas al deduplicar por `uid`. No son pérdida de eventos:
    #: son filas redundantes de la misma conexión.
    filas_colapsadas_por_uid: int = 0
    eventos_emitidos: int = 0
    eventos_benignos: int = 0
    eventos_maliciosos: int = 0
    #: `uid` que perdieron una táctica al excluir su fila `Duplicate`. Es el
    #: costo medido de la decisión D-9 sobre la referencia de D3.
    uids_con_tactica_perdida: int = 0
    #: `uid` que quedaron sin ninguna fila tras la exclusión. Debe ser 0: se
    #: verificó que ninguna fila `Duplicate` existe sin su gemela.
    uids_desaparecidos: int = 0
    sha256_eventos: str = ""
    sha256_etiquetas: str = ""
    tacticas: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "semana": self.semana,
            "archivo_parquet": self.archivo_parquet,
            "sha256_parquet": self.sha256_parquet,
            "filas_parquet": self.filas_parquet,
            "filas_excluidas_duplicate": self.filas_excluidas_duplicate,
            "filas_colapsadas_por_uid": self.filas_colapsadas_por_uid,
            "eventos_emitidos": self.eventos_emitidos,
            "eventos_benignos": self.eventos_benignos,
            "eventos_maliciosos": self.eventos_maliciosos,
            "uids_con_tactica_perdida": self.uids_con_tactica_perdida,
            "uids_desaparecidos": self.uids_desaparecidos,
            "sha256_eventos": self.sha256_eventos,
            "sha256_etiquetas": self.sha256_etiquetas,
            "tacticas": self.tacticas,
        }


def _sha256(ruta: Path) -> str:
    h = hashlib.sha256()
    with ruta.open("rb") as f:
        for bloque in iter(lambda: f.read(1 << 20), b""):
            h.update(bloque)
    return h.hexdigest()


def _csv_valor(valor) -> str:
    """Serializa un valor al CSV, citando solo cuando hace falta."""
    if valor is None:
        # Zeek escribe `-` para un campo ausente; mantenerlo hace que el
        # CSV se lea como un log de Zeek y no como una tabla con huecos.
        return "-"
    if isinstance(valor, bool):
        return "T" if valor else "F"
    texto = str(valor)
    if any(c in texto for c in (",", '"', "\n", "\r")):
        return '"' + texto.replace('"', '""') + '"'
    return texto


def _escribir_csv(ruta: Path, columnas: tuple[str, ...], filas) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with ruta.open("w", encoding="utf-8", newline="\n") as f:
        f.write(",".join(columnas) + "\n")
        for fila in filas:
            f.write(",".join(_csv_valor(v) for v in fila) + "\n")


def convertir_shard(
    archivo: Path, semana: str, destino: Path, raiz_repo: Path
) -> ResumenConversion:
    """Convierte un Parquet a un CSV de eventos y un CSV de etiquetas."""
    import pyarrow.parquet as pq  # import diferido: solo este módulo lo usa

    tabla = pq.read_table(archivo)
    faltantes = (set(COLUMNAS_EVENTO) | set(COLUMNAS_ETIQUETA)) - set(
        tabla.column_names
    )
    if faltantes:
        raise ValueError(
            f"{archivo.name}: faltan columnas esperadas {sorted(faltantes)}"
        )
    columnas = tabla.to_pydict()
    n_filas = tabla.num_rows

    resumen = ResumenConversion(
        semana=semana,
        archivo_parquet=archivo.relative_to(raiz_repo).as_posix(),
        sha256_parquet=_sha256(archivo),
        filas_parquet=n_filas,
    )

    # Primera pasada: agrupar por uid, separando lo excluido de lo que entra.
    # Se recorre en orden de fila para que el resultado sea determinístico.
    eventos: dict[str, tuple] = {}
    binarios: dict[str, set[str]] = defaultdict(set)
    tacticas: dict[str, set[str]] = defaultdict(set)
    tecnicas: dict[str, set[str]] = defaultdict(set)
    orden: list[str] = []
    tacticas_excluidas: dict[str, set[str]] = defaultdict(set)

    for i in range(n_filas):
        uid = columnas["uid"][i]
        etiqueta = columnas["label_binary"][i]
        if etiqueta == VALOR_EXCLUIDO:
            resumen.filas_excluidas_duplicate += 1
            # Se guarda qué táctica aportaba, para poder medir cuántos uid
            # pierden una atribución por la exclusión.
            tacticas_excluidas[uid].add(columnas["label_tactic"][i])
            continue
        if uid in eventos:
            resumen.filas_colapsadas_por_uid += 1
        else:
            eventos[uid] = tuple(columnas[c][i] for c in COLUMNAS_EVENTO)
            orden.append(uid)
        binarios[uid].add(etiqueta)
        tacticas[uid].add(columnas["label_tactic"][i])
        tecnicas[uid].add(columnas["label_technique"][i])

    # Un uid cuyas únicas filas eran `Duplicate` desaparecería del conjunto.
    # Se verificó que no ocurre; el conteo lo deja demostrado por corrida.
    resumen.uids_desaparecidos = len(set(tacticas_excluidas) - set(eventos))
    resumen.uids_con_tactica_perdida = sum(
        1
        for uid, perdidas in tacticas_excluidas.items()
        if uid in eventos and perdidas - tacticas[uid]
    )

    filas_etiquetas = []
    for uid in orden:
        valores = binarios[uid]
        if len(valores) > 1:
            # Una conexión etiquetada a la vez benigna y maliciosa no es
            # clasificable: no se inventa un criterio, se falla.
            raise ValueError(
                f"{archivo.name}: el uid {uid!r} tiene label_binary "
                f"contradictorio {sorted(valores)}"
            )
        binario = next(iter(valores))
        if binario == VALOR_MALICIOSO:
            resumen.eventos_maliciosos += 1
        elif binario == VALOR_BENIGNO:
            resumen.eventos_benignos += 1
        else:
            raise ValueError(
                f"{archivo.name}: label_binary inesperado {binario!r} en {uid!r}"
            )
        filas_etiquetas.append((
            uid,
            binario,
            SEPARADOR_ETIQUETAS.join(sorted(tacticas[uid])),
            SEPARADOR_ETIQUETAS.join(sorted(tecnicas[uid])),
        ))
    resumen.eventos_emitidos = len(orden)

    conteo_tacticas: dict[str, int] = defaultdict(int)
    for uid in orden:
        for tactica in tacticas[uid]:
            conteo_tacticas[tactica] += 1
    resumen.tacticas = dict(sorted(conteo_tacticas.items(),
                                   key=lambda par: -par[1]))

    ruta_eventos = destino / "eventos" / f"{semana}.csv"
    ruta_etiquetas = destino / "etiquetas" / f"{semana}.csv"
    _escribir_csv(ruta_eventos, COLUMNAS_EVENTO, (eventos[u] for u in orden))
    _escribir_csv(
        ruta_etiquetas, ("uid",) + COLUMNAS_ETIQUETA, filas_etiquetas
    )
    resumen.sha256_eventos = _sha256(ruta_eventos)
    resumen.sha256_etiquetas = _sha256(ruta_etiquetas)
    return resumen


def verificar_separacion(destino: Path) -> dict:
    """Comprueba que ningún CSV de eventos mencione una columna de etiqueta.

    Es una verificación sobre el artefacto, no sobre el código: lo que
    importa es que el archivo que puede llegar al prompt no contenga la
    referencia, independientemente de cómo se generó.
    """
    hallazgos = []
    for csv in sorted((destino / "eventos").glob("*.csv")):
        with csv.open(encoding="utf-8") as f:
            cabecera = f.readline().strip().split(",")
        intrusas = [c for c in cabecera if c.startswith("label")]
        if intrusas:
            hallazgos.append({"archivo": csv.name, "columnas": intrusas})
        if tuple(cabecera) != COLUMNAS_EVENTO:
            hallazgos.append({"archivo": csv.name, "cabecera_inesperada": cabecera})
    return {"archivos_revisados": len(list((destino / "eventos").glob("*.csv"))),
            "hallazgos": hallazgos}


def convertir_dataset(raiz_repo: Path, destino: Path) -> dict:
    """Convierte los 13 shards y devuelve el manifiesto de conversión."""
    origen = raiz_repo / "data/logs/UWF-ZeekDataFall22-parquet"
    if not origen.is_dir():
        raise FileNotFoundError(f"no está el dataset UWF en {origen}")

    resumenes = []
    for directorio in sorted(origen.iterdir()):
        if not directorio.is_dir():
            continue
        archivos = sorted(directorio.glob("*.parquet"))
        if not archivos:
            continue
        # El nombre del directorio viene con `%20` por la descarga: se
        # normaliza a un nombre de archivo sin espacios ni codificación.
        semana = directorio.name.replace("%20", " ").replace(" - ", "_").replace(" ", "")
        for archivo in archivos:
            resumenes.append(
                convertir_shard(archivo, semana, destino, raiz_repo)
            )

    totales = {
        "filas_parquet": sum(r.filas_parquet for r in resumenes),
        "filas_excluidas_duplicate": sum(
            r.filas_excluidas_duplicate for r in resumenes
        ),
        "filas_colapsadas_por_uid": sum(
            r.filas_colapsadas_por_uid for r in resumenes
        ),
        "eventos_emitidos": sum(r.eventos_emitidos for r in resumenes),
        "eventos_benignos": sum(r.eventos_benignos for r in resumenes),
        "eventos_maliciosos": sum(r.eventos_maliciosos for r in resumenes),
        "uids_con_tactica_perdida": sum(
            r.uids_con_tactica_perdida for r in resumenes
        ),
        "uids_desaparecidos": sum(r.uids_desaparecidos for r in resumenes),
    }
    return {
        "dataset": "uwf",
        "origen": origen.relative_to(raiz_repo).as_posix(),
        "destino": destino.relative_to(raiz_repo).as_posix(),
        "motor": "pyarrow==25.0.1 (requirements-experimentacion.txt)",
        "decisiones_aplicadas": {
            "D-9_excluir_duplicate": (
                "los registros con label_binary='Duplicate' se excluyen del "
                "conjunto experimental; su conexión permanece a través de la "
                "fila gemela, de modo que no desaparece ningún uid"
            ),
            "etiquetas_separadas": (
                "label_binary, label_tactic y label_technique se escriben "
                "SOLO en etiquetas/; eventos/ lleva una allowlist de 22 "
                "columnas de Zeek"
            ),
            "uid_clave_de_referencia": (
                "uid es la clave de matching de reconstrucción; se dedupica "
                "por uid porque las filas que lo comparten son la misma "
                "conexión (firma de flujo idéntica en 9 campos, 0 colisiones)"
            ),
        },
        "totales": totales,
        "separacion_verificada": verificar_separacion(destino),
        "shards": [r.to_dict() for r in resumenes],
    }


def main(raiz_repo: Path) -> None:
    destino = raiz_repo / "data/experimentacion/uwf_csv"
    manifiesto = convertir_dataset(raiz_repo, destino)
    ruta = raiz_repo / "experiments/manifests/uwf_conversion.json"
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(
        json.dumps(manifiesto, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    t = manifiesto["totales"]
    print(f"shards convertidos: {len(manifiesto['shards'])}")
    print(f"  filas en Parquet:            {t['filas_parquet']:>9,}")
    print(f"  excluidas (Duplicate):       {t['filas_excluidas_duplicate']:>9,}")
    print(f"  colapsadas por uid:          {t['filas_colapsadas_por_uid']:>9,}")
    print(f"  eventos emitidos:            {t['eventos_emitidos']:>9,}")
    print(f"    benignos:                  {t['eventos_benignos']:>9,}")
    print(f"    maliciosos:                {t['eventos_maliciosos']:>9,}")
    print(f"  uid con tactica perdida:     {t['uids_con_tactica_perdida']:>9,}")
    print(f"  uid desaparecidos:           {t['uids_desaparecidos']:>9,}")
    print(f"separacion verificada: {manifiesto['separacion_verificada']}")


if __name__ == "__main__":
    main(Path(__file__).resolve().parents[3])
