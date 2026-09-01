"""Consulta de CVEs en la NVD, con fallback a catálogo local.

Migrado desde la celda 13 del notebook de Colab.

Pendiente del Proyecto de Título (no implementado aún): enlace formal
CVE <-> técnica MITRE ATT&CK vía STIX (github.com/mitre-attack/attack-stix-data).
"""

import requests

from src.config import NVD_API_KEY

_CVE_LOCAL = {
    "openssh": ["CVE-2024-6387 (regreSSHion, RCE en sshd)"],
    "apache": ["CVE-2021-41773 (path traversal en Apache HTTP)"],
    "sql": ["CWE-89 (SQL Injection)"],
}


def query_cve(keyword: str) -> dict:
    """Busca CVEs por palabra clave. Primario: NVD (público). Fallback: catálogo local."""
    try:
        headers = {"apiKey": NVD_API_KEY} if NVD_API_KEY else {}
        r = requests.get(
            "https://services.nvd.nist.gov/rest/json/cves/2.0",
            params={"keywordSearch": keyword, "resultsPerPage": 3},
            headers=headers, timeout=10)
        r.raise_for_status()
        vulns = r.json().get("vulnerabilities", [])
        cves = []
        for v in vulns[:3]:
            c = v["cve"]
            desc = next((d["value"] for d in c.get("descriptions", []) if d["lang"] == "en"), "")
            cves.append({"id": c["id"], "resumen": desc[:160]})
        if cves:
            return {"fuente": "nvd", "keyword": keyword, "cves": cves}
    except Exception:
        pass
    for k, v in _CVE_LOCAL.items():
        if k in keyword.lower():
            return {"fuente": "fallback", "keyword": keyword, "cves": v}
    return {"fuente": "fallback", "keyword": keyword, "cves": []}
