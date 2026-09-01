"""Nodo Tool: tool_consultar_cve.

Migrado desde la celda 22 del notebook de Colab.

Consulta la NVD por CVEs relacionados al primer servicio afectado detectado
en la agregación.

Pendiente del Proyecto de Título (no implementado aún):
enlace formal CVE <-> técnica MITRE ATT&CK vía STIX
(github.com/mitre-attack/attack-stix-data).
"""

from src.state import LogGuardState
from src.tools.cve import query_cve


def tool_consultar_cve(state: LogGuardState) -> dict:
    print("   📋 [Tool CVE] Consultando NVD...")

    servicios = list(state["resumen_logs"].get("servicios", {}).keys())
    keyword = servicios[0] if servicios else "ssh"

    resultado = query_cve(keyword)
    cves = resultado.get("cves", [])
    print(f"   → {len(cves)} CVE(s) encontrados para '{keyword}'.")
    return {"cves_encontrados": cves}
