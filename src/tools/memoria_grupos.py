"""Memoria por grupo de eventos (NODEX final, Fase B.1-2).

Además de la memoria de lotes (B4), una memoria de GRUPOS etiquetados construida
offline a partir de la partición de desarrollo
(`src/experimentation/knowledge/memoria_grupos.py`):

- malicioso: los grupos que contienen eventos de un incidente, con su táctica;
- benigno: los grupos con señal de los casos benignos.

Cada grupo se representa por su COMPORTAMIENTO, sin direcciones IP
(`representacion_grupo_red`): protocolo, servicio o puerto, estados e historia
de las conexiones, número de filas, ventana temporal, bytes y duración, y la
señal que lo marcó con su motivo factual. Solo logs de red: es una
representación de flujos.

Para cada grupo con señal del lote, `consultar_memoria_grupos` recupera el
grupo malicioso y el grupo benigno más parecidos (contrastivo), excluyendo
cualquier grupo que comparta registros fuente con el lote analizado (la misma
exclusión por solapamiento de la memoria de lotes). Lo reciben el cazador y,
para que la comparación sea justa, el agente único.
"""

from __future__ import annotations

import json
import statistics
from collections import Counter
from functools import lru_cache
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
#: El modelo de embeddings trunca a 256 piezas de palabra: lo más informativo va primero.
MAX_CHARS_REPRESENTACION = 1200


def _numero(valor):
    try:
        return float(valor)
    except (TypeError, ValueError):
        return None


def _mediana(valores) -> str:
    valores = [v for v in valores if v is not None]
    if not valores:
        return "sin dato"
    m = statistics.median(valores)
    return f"{m:.3g}"


def _top(conteo: Counter, n: int = 3) -> str:
    return ", ".join(f"{k} {v}" for k, v in conteo.most_common(n)) or "sin dato"


def representacion_grupo_red(eventos, motivos=None, motivos_factuales=None) -> str:
    """Comportamiento de un grupo de flujos, sin IP (texto determinístico para indexar y consultar)."""
    from src.preprocessing.perfil_lote import _servicio_o_puerto, segundos_de_evento
    eventos = list(eventos)
    n = len(eventos)
    protocolos = Counter((e.protocol or "-").lower() for e in eventos)
    servicios = Counter(_servicio_o_puerto(e) for e in eventos)
    puertos = sorted({e.destination_port for e in eventos if e.destination_port is not None})
    estados = Counter(e.event_outcome or "-" for e in eventos)
    historias = Counter(str(e.attributes.get("history") or "-") for e in eventos)
    marcas = [s for e in eventos if (s := segundos_de_evento(e)) is not None]
    ventana = (max(marcas) - min(marcas)) if len(marcas) >= 2 else 0.0
    ritmo = f", {n / ventana:.2g} filas/s" if ventana > 0 else ""
    origenes = len({e.source_ip for e in eventos if e.source_ip})
    destinos = len({e.destination_ip for e in eventos if e.destination_ip})
    lista_puertos = ", ".join(str(p) for p in puertos[:8]) + (" ..." if len(puertos) > 8 else "")
    partes = [
        f"Señal: {'/'.join(sorted(motivos or [])) or 'ninguna'}"
        + (f" ({'; '.join(motivos_factuales)})" if motivos_factuales else "") + ".",
        f"Protocolo {_top(protocolos)}; servicio {_top(servicios)}; {len(puertos)} puertos de destino "
        f"distintos ({lista_puertos or 'sin puerto'}).",
        f"{n} filas, {origenes} origen(es) y {destinos} destino(s); ventana {ventana:.1f} s{ritmo}.",
        f"Estados: {_top(estados)}. Historia: {_top(historias)}.",
        f"Mediana de duración {_mediana(_numero(e.attributes.get('duration')) for e in eventos)} s, "
        f"bytes enviados {_mediana(_numero(e.attributes.get('orig_bytes')) for e in eventos)}, "
        f"bytes recibidos {_mediana(_numero(e.attributes.get('resp_bytes')) for e in eventos)}.",
    ]
    return " ".join(partes)[:MAX_CHARS_REPRESENTACION]


def grupos_con_senal_red(eventos, analisis: dict) -> list[dict]:
    """Los grupos con señal de un lote de red, con sus eventos y su representación."""
    from src.tools.memoria_historica import huella_evento
    flujos = (analisis.get("contenido_lote") or {}).get("flujos_minoritarios") or []
    por_grupo: dict[str, list] = {}
    for e, gid in zip(eventos, analisis.get("group_id_por_registro") or []):
        por_grupo.setdefault(gid, []).append(e)
    salida = []
    for f in flujos:
        propios = por_grupo.get(f["group_id"], [])
        salida.append({"group_id": f["group_id"],
                       "representacion": representacion_grupo_red(propios, f.get("motivos"),
                                                                   f.get("motivos_factuales")),
                       "huellas": sorted({huella_evento(e) for e in propios})})
    return salida


def _resolver(ruta) -> Path:
    ruta = Path(ruta)
    return ruta if ruta.is_absolute() else (RAIZ / ruta).resolve()


@lru_cache(maxsize=4)
def cargar_memoria(ruta: str) -> dict | None:
    """La memoria de grupos (JSON con embeddings normalizados), o None si no existe."""
    archivo = _resolver(ruta)
    if not archivo.exists():
        return None
    return json.loads(archivo.read_text(encoding="utf-8"))


def _normalizar(vector) -> list[float]:
    norma = sum(x * x for x in vector) ** 0.5 or 1.0
    return [float(x) / norma for x in vector]


def _resumen_entrada(entrada: dict, similitud: float) -> dict:
    return {"id": entrada["id"], "etiqueta": entrada["etiqueta"], "tacticas": entrada.get("tacticas") or [],
            "comportamiento": entrada["representacion"], "similitud": round(float(similitud), 3)}


def consultar_memoria_grupos(memoria: dict | None, consultas: list[dict], huellas_lote: list[str], embed) -> dict:
    """Para cada grupo consultado, el grupo malicioso y el benigno más parecidos sin solapamiento.

    `consultas`: [{"group_id", "representacion"}]. `embed`: función lista de textos -> vectores
    (la misma función de embeddings de la memoria). Devuelve
    `{"por_grupo": {gid: {"representacion", "malicioso", "benigno"}}, "excluidos_por_solapamiento",
    "consultados"}`.
    """
    vacio = {"por_grupo": {}, "excluidos_por_solapamiento": [], "consultados": 0}
    if not memoria or not consultas:
        return vacio
    entradas = memoria.get("entradas") or []
    propias = set(huellas_lote)
    excluidos = sorted(e["id"] for e in entradas if propias & set(e.get("huellas") or []))
    disponibles = [e for e in entradas if e["id"] not in set(excluidos)]
    vectores = [_normalizar(v) for v in embed([c["representacion"] for c in consultas])]
    por_grupo = {}
    for consulta, vector in zip(consultas, vectores):
        mejores = {}
        for entrada in disponibles:
            similitud = float(sum(a * b for a, b in zip(vector, entrada["embedding"])))
            actual = mejores.get(entrada["etiqueta"])
            if actual is None or similitud > actual[1]:
                mejores[entrada["etiqueta"]] = (entrada, similitud)
        por_grupo[consulta["group_id"]] = {
            "representacion": consulta["representacion"],
            **{clase: (_resumen_entrada(*mejores[clase]) if clase in mejores else None)
               for clase in ("malicioso", "benigno")}}
    return {"por_grupo": por_grupo, "excluidos_por_solapamiento": excluidos, "consultados": len(entradas)}


def contexto_memoria_grupos(por_grupo: dict | None) -> str:
    """Bloque del prompt (agente único): cada grupo con señal frente a sus dos referentes etiquetados."""
    from src.config import MEMORIA_GRUPOS_ACTIVA
    if not MEMORIA_GRUPOS_ACTIVA or not por_grupo:
        return ""
    lineas = [_ENCABEZADO]
    for gid, item in por_grupo.items():
        lineas.append(f"- {gid}: {item.get('representacion')}")
        lineas.extend(_referentes(item))
    lineas.append(_INSTRUCCION)
    return "\n".join(lineas)


_ENCABEZADO = ("MEMORIA DE GRUPOS ETIQUETADOS DE LA ORGANIZACIÓN (por cada grupo con señal del lote, el grupo "
               "malicioso y el grupo benigno de casos pasados más parecidos en comportamiento):")
_INSTRUCCION = ("Es una comparación, no una votación: decide qué referente comparte los rasgos de comportamiento "
                "que importan (volumen, ritmo, dirección, puertos, estados) y no solo el servicio.")


def _referentes(item: dict) -> list[str]:
    salida = []
    mal, ben = item.get("malicioso"), item.get("benigno")
    salida.append(f"    malicioso más parecido ({', '.join(mal.get('tacticas') or []) or 'táctica no anotada'}): "
                  f"{mal['comportamiento']}" if mal else "    malicioso más parecido: ninguno disponible")
    salida.append(f"    benigno más parecido: {ben['comportamiento']}" if ben
                  else "    benigno más parecido: ninguno disponible")
    return salida


def referentes_de_grupo(item: dict | None) -> dict | None:
    """Los dos referentes de un grupo, en la forma que recibe el cazador (sin similitud numérica)."""
    if not item:
        return None
    def corto(r):
        return None if not r else {k: r[k] for k in ("tacticas", "comportamiento") if k in r and r[k]}
    return {"malicioso_mas_parecido": corto(item.get("malicioso")),
            "benigno_mas_parecido": corto(item.get("benigno"))}
