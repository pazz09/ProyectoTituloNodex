"""Memoria histórica de la organización (NODEX final, B3 y B4).

La memoria histórica son casos pasados, etiquetados por la organización, con
una descripción breve y verificable de por qué tienen su etiqueta. Sirve como
referencia de CRITERIO (qué cuenta como alerta aquí), no como prueba.

- `representacion_lote`: texto con que un lote se indexa y se consulta. Se arma
  con la composición del lote y sus grupos con señal (o, en texto, sus grupos de
  severidad alta o plantilla minoritaria), no con conteos globales de la firma.
  No incluye direcciones IP: el criterio se refiere a comportamientos, no a
  equipos concretos.
- `huellas_registros`: identificadores de los registros fuente del lote (el
  `uid` original o el SHA-256 de la línea sin el campo de alerta). Un patrón que
  comparta cualquier registro con el lote analizado se excluye: un caso no puede
  recuperarse a sí mismo (validación cruzada dejando uno fuera en desarrollo).
- `consultar_historicos`: los k patrones más parecidos sin solapamiento.

Lo usan `pipeline._preparar_estado_inicial` (NODEX y agente único, la misma
consulta) y el constructor de los corpus (`src/experimentation/knowledge/
memoria_historica_v2.py`).
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter

from src.preprocessing.perfil_lote import _SEVERIDADES_ALTAS, linea_sin_etiqueta

#: Definiciones generales del veredicto (B4). Las comparten el triage, el auditor
#: y el agente único: son la especificación de la tarea, no parte de la
#: arquitectura. No contienen ejemplos tomados de casos de desarrollo.
CRITERIO_ORGANIZACION = (
    "Definiciones: incidente_seguridad = actividad maliciosa o amenaza de seguridad respaldada por la "
    "evidencia. anomalia_operativa = evidencia de una falla que, según los criterios de la organización "
    "reflejados en sus casos históricos, requiere intervención o investigación; la severidad declarada por "
    "el log no basta por sí sola. normal = nada que requiera intervención según esos criterios. Usa los "
    "casos históricos como referencia de criterio, no como prueba: si el lote se parece a un caso histórico "
    "normal pero contiene eventos que en los casos históricos anómalos determinaron la alerta, prevalece la "
    "evidencia. La similitud con casos históricos normales no descarta un incidente: los eventos "
    "minoritarios se evalúan por sí mismos. "
)

#: Máximo de caracteres de la representación. El modelo de embeddings trunca a
#: 256 piezas de palabra (~1 000-1 500 caracteres), así que lo más informativo
#: (grupos con señal) va primero.
MAX_CHARS_REPRESENTACION = 2000


def _top(conteo: dict | None, n: int = 6) -> str:
    return ", ".join(f"{k} {v}" for k, v in list((conteo or {}).items())[:n])


def _grupos_destacados(perfil: dict, grupos: list[dict], contenido: dict) -> list[str]:
    """Descripción sin IP de los grupos con señal (red) o de severidad alta/minoritarios (texto)."""
    if perfil.get("tipo") == "red":
        lineas = []
        for flujo in (contenido or {}).get("flujos_minoritarios") or []:
            c = flujo.get("clave") or {}
            lineas.append(f"[{'/'.join(flujo.get('motivos') or [])}] {c.get('protocolo')} "
                          f"{c.get('servicio_o_puerto')} x{flujo.get('conteo')}")
        return lineas
    total = max(1, sum(g.get("conteo", 0) for g in grupos))
    lineas = []
    for g in grupos:
        c = g.get("clave") or {}
        alta = str(c.get("severidad", "")).strip().lower() in _SEVERIDADES_ALTAS
        if alta or g.get("conteo", 0) / total < 0.05:
            lineas.append(f"[{c.get('severidad')} {c.get('componente')}] {c.get('plantilla')} "
                          f"x{g.get('conteo')} en {g.get('n_nodos', 0)} nodos")
    return lineas


def representacion_lote(perfil: dict | None, grupos: list[dict] | None, contenido: dict | None) -> str:
    """Texto determinístico del lote para indexar y consultar la memoria histórica."""
    perfil = perfil or {}
    grupos = grupos or []
    destacados = _grupos_destacados(perfil, grupos, contenido or {})
    if perfil.get("tipo") == "red":
        dominantes = sorted(grupos, key=lambda g: -g.get("conteo", 0))[:3]
        partes = [
            "Grupos con señal: " + ("; ".join(destacados) if destacados else "ninguno"),
            f"Lote de red, {perfil.get('filas')} conexiones. Protocolos: {_top(perfil.get('protocolos'))}. "
            f"Servicios: {_top(perfil.get('servicios'))}. Estados: {_top(perfil.get('estados'))}.",
            "Dominante: " + "; ".join(f"{(g['clave'] or {}).get('protocolo')} "
                                      f"{(g['clave'] or {}).get('servicio_o_puerto')} x{g['conteo']}"
                                      for g in dominantes),
        ]
    else:
        partes = [
            "Eventos destacados: " + ("; ".join(destacados) if destacados else "ninguno"),
            f"Log de texto, {perfil.get('filas')} eventos. Severidades: {_top(perfil.get('severidades'))}. "
            f"Componentes: {_top(perfil.get('componentes'))}. Nodos distintos: {perfil.get('nodos_distintos')}.",
        ]
    return "\n".join(partes)[:MAX_CHARS_REPRESENTACION]


def huella_evento(evento) -> str:
    """`uid` original si existe; si no, SHA-256 (16 hex) de la línea sin campo de alerta."""
    uid = evento.attributes.get("uid") or evento.attributes.get("flow_id")
    if uid:
        return f"uid:{str(uid).strip()}"
    linea = linea_sin_etiqueta(evento).strip()
    return "sha:" + hashlib.sha256(linea.encode("utf-8")).hexdigest()[:16]


def huellas_registros(eventos) -> list[str]:
    return sorted({huella_evento(e) for e in eventos})


#: Etiquetas de la clase positiva (B.1-1). El resto de las etiquetas conocidas es "normal".
ETIQUETAS_ANOMALAS = {"anomalo", "malicioso", "anomalous", "malicious", "incidente", "anomalia"}


def clase_de_etiqueta(etiqueta) -> str | None:
    """'anomala' (anómalo o malicioso), 'normal', o None si la etiqueta no se reconoce."""
    valor = str(etiqueta or "").strip().lower()
    if valor in ETIQUETAS_ANOMALAS:
        return "anomala"
    if valor in ("normal", "benigno", "benign"):
        return "normal"
    return None


def tipo_de_representacion(texto) -> str | None:
    """Tipo de lote (red/texto) de una representación de `representacion_lote`, o None."""
    if not isinstance(texto, str):
        return None
    if texto.startswith("Grupos con señal:"):
        return "red"
    if texto.startswith("Eventos destacados:"):
        return "texto"
    return None


def consultar_historicos(coleccion, representacion: str, huellas: list[str], k: int,
                         k_por_clase: int | None = None, tipo: str | None = None) -> dict:
    """Los patrones más parecidos que no comparten registros con el lote.

    - Sin `k_por_clase` (Fase B): los k más parecidos, de cualquier clase.
    - Con `k_por_clase` (B.1-1, memoria contrastiva): los `k_por_clase` más parecidos de CADA
      clase (normal y anómala), solo del mismo `tipo` de lote (red o texto) si se indica. Un
      patrón cuyo tipo no se puede leer (sin documento) se considera compatible.

    Devuelve `{"casos": [...], "excluidos_por_solapamiento": [...], "consultados": n}`.
    Cada caso: id, dataset, etiqueta, clase, descripción y similitud (coseno).
    """
    if coleccion is None or k <= 0:
        return {"casos": [], "excluidos_por_solapamiento": [], "consultados": 0}
    total = coleccion.count()
    if total == 0:
        return {"casos": [], "excluidos_por_solapamiento": [], "consultados": 0}
    res = coleccion.query(query_texts=[representacion[:MAX_CHARS_REPRESENTACION]], n_results=total)
    documentos = (res.get("documents") or [[None] * len(res["ids"][0])])[0] if isinstance(res, dict) else None
    documentos = documentos or [None] * len(res["ids"][0])
    propias = set(huellas)
    casos, excluidos, por_clase, otro_tipo = [], [], {"anomala": 0, "normal": 0}, 0
    for vid, meta, dist, doc in zip(res["ids"][0], res["metadatas"][0], res["distances"][0], documentos):
        meta = meta or {}
        try:
            ajenas = set(json.loads(meta.get("huellas") or "[]"))
        except ValueError:
            ajenas = set()
        if propias & ajenas:
            excluidos.append(vid)
            continue
        # Los patrones antiguos (feedback de la interfaz) no traen el esquema de la
        # Fase B: se usa su `clasificacion` y se declara que no hay descripción.
        etiqueta = meta.get("etiqueta") or meta.get("clasificacion")
        caso = {"id": meta.get("historical_case_id") or vid, "dataset": meta.get("dataset"),
                "etiqueta": etiqueta, "clase": clase_de_etiqueta(etiqueta),
                "descripcion": meta.get("descripcion") or "patrón validado sin descripción",
                "similitud": round(1 - dist, 3)}
        if k_por_clase is None:
            if len(casos) < k:
                casos.append(caso)
            continue
        tipo_patron = tipo_de_representacion(doc)
        if tipo and tipo_patron and tipo_patron != tipo:
            otro_tipo += 1
            continue
        if caso["clase"] in por_clase and por_clase[caso["clase"]] < k_por_clase:
            por_clase[caso["clase"]] += 1
            casos.append(caso)
    salida = {"casos": casos, "excluidos_por_solapamiento": excluidos, "consultados": total}
    if k_por_clase is not None:
        salida.update(contrastiva=True, k_por_clase=k_por_clase, tipo=tipo, omitidos_otro_tipo=otro_tipo)
    return salida


_INSTRUCCION_CONTRASTIVA = (
    "Esto es una COMPARACIÓN, no una votación: que el lote se parezca más a unos que a otros no decide "
    "el veredicto. Identifica qué evidencia concreta diferencia a los casos anómalos de los normales (los "
    "eventos que determinaron la alerta) y verifica si esa evidencia está presente en este lote. Decide por "
    "esa evidencia.")


def contexto_historico(casos: list[dict] | None) -> str:
    """Bloque del prompt con los casos históricos (compartido por triage, auditor y agente único).

    Con `HISTORICO_CONTRASTIVO` (B.1-1) se presentan separados por clase y sin la similitud
    numérica, como comparación; sin él, en una lista con su similitud (Fase B).
    """
    from src.config import HISTORICO_ACTIVO, HISTORICO_CONTRASTIVO
    if not HISTORICO_ACTIVO or not casos:
        return ""
    if HISTORICO_CONTRASTIVO:
        normales = [c for c in casos if (c.get("clase") or clase_de_etiqueta(c.get("etiqueta"))) == "normal"]
        anomalos = [c for c in casos if (c.get("clase") or clase_de_etiqueta(c.get("etiqueta"))) == "anomala"]
        lineas = ["CASOS HISTÓRICOS DE LA ORGANIZACIÓN PARA COMPARAR (referencia de criterio, no prueba). "
                  "El lote se parece a estos casos NORMALES:"]
        lineas += [f"- [{c.get('etiqueta')}] {c.get('descripcion')}" for c in normales] or ["- (ninguno disponible)"]
        lineas.append("y a estos casos ANÓMALOS o MALICIOSOS:")
        lineas += [f"- [{c.get('etiqueta')}] {c.get('descripcion')}" for c in anomalos] or ["- (ninguno disponible)"]
        lineas.append(_INSTRUCCION_CONTRASTIVA)
        return "\n".join(lineas)
    lineas = ["CASOS HISTÓRICOS DE LA ORGANIZACIÓN MÁS PARECIDOS (referencia de criterio, no prueba):"]
    for c in casos:
        lineas.append(f"- [{c.get('etiqueta')}] (similitud {c.get('similitud')}): {c.get('descripcion')}")
    return "\n".join(lineas)


def resumen_composicion(conteo: Counter, n: int = 5) -> str:
    return ", ".join(f"{k} {v}" for k, v in conteo.most_common(n))
