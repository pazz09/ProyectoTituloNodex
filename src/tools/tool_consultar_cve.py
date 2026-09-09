"""Nodo Tool: tool_consultar_cve.

Migrado desde la celda 22 del notebook de Colab.

Consulta la NVD por CVEs relacionados al software afectado.

Adaptado en la Fase 10 del plan de preprocesamiento heterogéneo. Dos
cambios respecto de la versión original:

**Se eliminó el fallback a "ssh".** Antes, un lote sin servicios conocidos
consultaba la NVD por `"ssh"` sin ninguna razón, y devolvía CVEs de OpenSSH
para logs que no tenían nada que ver. Un resultado inventado es peor que
ninguno: ahora se informa que no hay término de búsqueda y no se consulta.

**La palabra clave se elige por especificidad, no por posición.** Antes se
tomaba el primer servicio del diccionario, que con el esquema v2 puede ser
`hdfs.datanode` o `bgl.kernel` -- términos que la NVD no conoce y que
devuelven cero resultados. Ahora se prefiere producto y fabricante (que es
como la NVD indexa), después el servicio, y se descartan los nombres
internos que no corresponden a software buscable.
"""

from src.state import LogGuardState
from src.tools.cve import query_cve

# Servicios que no son software buscable en la NVD: son nombres internos de
# un producto (`hdfs.datanode`) o marcadores de ausencia. Consultarlos
# gasta una llamada para devolver cero resultados.
_NO_BUSCABLES = {"desconocido", "otro", "text", "auth_log"}


def _es_buscable(termino: str) -> bool:
    t = (termino or "").strip().lower()
    if not t or t in _NO_BUSCABLES:
        return False
    # `hdfs.datanode`, `bgl.kernel`: componentes internos, no productos.
    if "." in t and t.split(".", 1)[0] in ("hdfs", "bgl", "dfs"):
        return False
    return True


def elegir_keyword(resumen: dict, metadatos: dict | None = None) -> str | None:
    """Término de búsqueda para la NVD, o `None` si no hay uno razonable.

    Orden de preferencia: producto, fabricante y por último servicio. La
    NVD indexa por producto y proveedor, así que un nombre de producto
    ("Apache", "OpenSSH") encuentra mucho más que el nombre interno de un
    componente.
    """
    metadatos = metadatos or {}
    for clave in ("product_distribution", "vendor_distribution"):
        for candidato in (metadatos.get(clave) or {}):
            if _es_buscable(candidato):
                return candidato
    for servicio in (resumen.get("servicios") or {}):
        if _es_buscable(servicio):
            return servicio
    return None


def tool_consultar_cve(state: LogGuardState) -> dict:
    print("   📋 [Tool CVE] Consultando NVD...")

    keyword = elegir_keyword(
        state.get("resumen_logs") or {},
        state.get("preprocessing_metadata") or {},
    )
    if keyword is None:
        print("   → Sin término de búsqueda razonable: no se consulta la NVD. "
              "El lote no identifica un producto ni un servicio buscable.")
        return {"cves_encontrados": []}

    resultado = query_cve(keyword)
    cves = resultado.get("cves", [])
    print(f"   → {len(cves)} CVE(s) encontrados para '{keyword}'.")
    return {"cves_encontrados": cves}
