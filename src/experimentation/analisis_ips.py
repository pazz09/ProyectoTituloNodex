"""Qué IPs consultó NODEX a AbuseIPDB durante una campaña, y qué responde el respaldo local.

Insumo para decidir, con datos, la política de consultas externas de la campaña final. Solo LEE
los registros de consultas que guarda el lanzador (`*.consultas_externas.json`); no consulta nada.

## Clases de IP

Se separan para poder decir qué fracción de las consultas NO tenía sentido preguntarle a un servicio
de reputación pública: las direcciones privadas y reservadas no tienen reputación pública.

    rfc1918          10/8, 172.16/12, 192.168/16
    loopback         127/8
    link_local       169.254/16
    cgnat            100.64/10 (espacio compartido)
    multicast        224/4
    reservada        otras reservadas por IANA (0/8, 240/4...)
    ipv6_no_global   IPv6 link-local, ULA, etc.
    ipv6_global      IPv6 global
    publica          IPv4 global

«No pública» = todas menos `publica` y `ipv6_global`.
"""

from __future__ import annotations

import ipaddress
import json
from pathlib import Path

CLASES_PUBLICAS = ("publica", "ipv6_global")

#: Lo que el respaldo local (`check_ip_reputation`, rama sin AbuseIPDB) considera «privada».
#: Se repite acá para poder compararlo con la clasificación correcta; una prueba verifica que
#: coincide con el código real, para que no se desfase en silencio.
PREFIJOS_PRIVADOS_DEL_RESPALDO = ("10.", "192.168.", "172.16.", "127.")

_RFC1918 = tuple(ipaddress.ip_network(n) for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"))
_CGNAT = ipaddress.ip_network("100.64.0.0/10")


def clasificar_ip(texto: str) -> str:
    """Clase de una dirección (ver la tabla del módulo). `no_es_ip` si no se puede interpretar."""
    try:
        a = ipaddress.ip_address(texto)
    except ValueError:
        return "no_es_ip"
    if a.version == 6:
        return "ipv6_global" if a.is_global else "ipv6_no_global"
    if any(a in red for red in _RFC1918):
        return "rfc1918"
    if a.is_loopback:
        return "loopback"
    if a.is_link_local:
        return "link_local"
    if a in _CGNAT:
        return "cgnat"
    if a.is_multicast:
        return "multicast"
    if a.is_reserved or a.is_unspecified:
        return "reservada"
    if not a.is_global:
        return "otra_no_global"
    return "publica"


def respaldo_la_trata_como_privada(ip: str) -> bool:
    return ip.startswith(PREFIJOS_PRIVADOS_DEL_RESPALDO)


def _consultas_de(raiz_repo: Path, config_version: str) -> list[dict]:
    salida = []
    for ruta in sorted((raiz_repo / "experiments" / "telemetry").glob("*/*.consultas_externas.json")):
        datos = json.loads(ruta.read_text(encoding="utf-8"))
        if datos.get("config_version") != config_version:
            continue
        for c in datos.get("consultas") or []:
            salida.append({**c, "dataset": datos["dataset"], "arquitectura": datos["arquitectura"],
                           "run_id": datos["run_id"]})
    return salida


def _porcentaje(n: int, total: int) -> float | None:
    return None if total == 0 else round(100 * n / total, 1)


def analizar(raiz_repo: Path, config_version: str) -> dict:
    """Por dataset: consultas a AbuseIPDB, IPs únicas, clases y desacuerdos con el respaldo."""
    por_dataset: dict[str, dict] = {}
    for c in _consultas_de(raiz_repo, config_version):
        if c.get("herramienta") != "abuseipdb":
            continue
        ip = (c.get("parametros") or {}).get("ip")
        d = por_dataset.setdefault(c["dataset"], {"consultas": [], })
        d["consultas"].append(ip)
    resumen = {}
    total_c = total_np = 0
    for dataset, d in sorted(por_dataset.items()):
        ips = d["consultas"]
        unicas = sorted(set(ips))
        clases = {}
        for ip in ips:
            clases[clasificar_ip(ip)] = clases.get(clasificar_ip(ip), 0) + 1
        clases_u = {}
        for ip in unicas:
            clases_u[clasificar_ip(ip)] = clases_u.get(clasificar_ip(ip), 0) + 1
        no_publicas = sum(n for k, n in clases.items() if k not in CLASES_PUBLICAS)
        no_publicas_u = [ip for ip in unicas if clasificar_ip(ip) not in CLASES_PUBLICAS]
        # IPs no públicas que el respaldo NO reconoce como privadas y por lo tanto puntúa como
        # públicas (score 50, categoría «sospechoso»).
        mal_tratadas = [ip for ip in no_publicas_u if not respaldo_la_trata_como_privada(ip)]
        resumen[dataset] = {
            "consultas": len(ips), "ips_unicas": len(unicas),
            "por_clase_consultas": clases, "por_clase_ips_unicas": clases_u,
            "consultas_no_publicas": no_publicas,
            "pct_consultas_no_publicas": _porcentaje(no_publicas, len(ips)),
            "ips_unicas_no_publicas": len(no_publicas_u),
            "pct_ips_unicas_no_publicas": _porcentaje(len(no_publicas_u), len(unicas)),
            "ips_no_publicas_que_el_respaldo_puntua_como_publicas": len(mal_tratadas),
            "ejemplos_mal_tratadas": mal_tratadas[:10],
        }
        total_c += len(ips)
        total_np += no_publicas
    return {"config_version": config_version, "por_dataset": resumen,
            "total_consultas": total_c, "total_no_publicas": total_np,
            "pct_total_no_publicas": _porcentaje(total_np, total_c)}


def descripcion_del_respaldo() -> dict:
    """Qué contiene EXACTAMENTE el respaldo local de cada herramienta, leído del código."""
    from src.config import SCORE_MALICIOSO, SCORE_SOSPECHOSO
    from src.tools import cve

    return {
        "abuseipdb": {
            "donde": "src/tools/reputation.py::check_ip_reputation (rama sin AbuseIPDB)",
            "fuente": "ninguna: es una heurística escrita en el código, no un conjunto de datos",
            "fecha": "ninguna (no tiene versión ni fecha de datos; viene de la migración del "
                     "prototipo, 1-sep-2026)",
            "cobertura": ("una sola regla: si la dirección empieza con "
                          f"{list(PREFIJOS_PRIVADOS_DEL_RESPALDO)} se considera privada (score 0, "
                          "«limpio»); CUALQUIER otra cadena se considera pública con score 50"),
            "limites_conocidos": [
                "172.16. solo cubre 172.16.x.x; el rango privado real es 172.16.0.0/12 "
                "(172.16 a 172.31)",
                "no reconoce IPv6, link-local 169.254, multicast 224/4 ni 100.64/10: las puntúa "
                "como públicas",
                "no distingue ninguna IP pública de otra: todas valen 50",
            ],
            "categoria_resultante": {
                "score_0": "limpio",
                f"score_50 (SCORE_SOSPECHOSO={SCORE_SOSPECHOSO}, SCORE_MALICIOSO={SCORE_MALICIOSO})":
                    "sospechoso" if SCORE_SOSPECHOSO <= 50 < SCORE_MALICIOSO else "otra",
            },
        },
        "nvd": {
            "donde": "src/tools/cve.py::query_cve (catálogo local `_CVE_LOCAL`)",
            "fuente": "ninguna declarada: tres entradas escritas a mano",
            "fecha": "ninguna",
            "cobertura": {k: list(v) for k, v in cve._CVE_LOCAL.items()},
            "regla": "una palabra clave que CONTENGA una de las claves devuelve su entrada; "
                     "cualquier otra devuelve lista vacía",
        },
    }
