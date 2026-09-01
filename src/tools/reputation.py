"""Corroboración de reputación de IPs (AbuseIPDB + caché persistente).

Migrado desde las celdas 13 y 16 del notebook de Colab.
"""

import json
import os

import requests

from src.config import ABUSEIPDB_API_KEY, IP_CACHE_PATH, SCORE_MALICIOSO, SCORE_SOSPECHOSO


def categorizar_reputacion(score) -> str:
    if score is None:
        return "desconocido"
    if score >= SCORE_MALICIOSO:
        return "malicioso"
    if score >= SCORE_SOSPECHOSO:
        return "sospechoso"
    return "limpio"


def check_ip_reputation(ip: str) -> dict:
    """Reputación de una IP. Primario: AbuseIPDB. Fallback: heurística local."""
    if ABUSEIPDB_API_KEY:
        try:
            r = requests.get(
                "https://api.abuseipdb.com/api/v2/check",
                headers={"Key": ABUSEIPDB_API_KEY, "Accept": "application/json"},
                params={"ipAddress": ip, "maxAgeInDays": 90}, timeout=8)
            r.raise_for_status()
            d = r.json()["data"]
            return {"fuente": "abuseipdb", "ip": ip,
                    "score": d.get("abuseConfidenceScore"),
                    "total_reportes": d.get("totalReports"),
                    "pais": d.get("countryCode")}
        except Exception:
            pass  # cae al fallback
    # --- Fallback local ---
    if ip is None:
        return {"fuente": "fallback", "ip": ip, "score": None, "nota": "sin IP"}
    privada = ip.startswith(("10.", "192.168.", "172.16.", "127."))
    score = 0 if privada else 50
    return {"fuente": "fallback", "ip": ip, "score": score,
            "nota": "IP privada/local" if privada else "IP pública (sin datos externos)"}


def corroborar_ips(ips: list, cache: "ReputationCache | None" = None) -> dict:
    """Corrobora la reputación de una lista de IPs (paso "CORROBORACIÓN DE IPs" del
    diagrama de arquitectura del informe, entre la agregación y el planificador).

    Usa `cache` para no repetir consultas a AbuseIPDB por la misma IP entre lotes
    (cada IP se consulta una sola vez mientras esté en caché). Si no se pasa un
    `cache`, crea uno nuevo respaldado por `IP_CACHE_PATH` (ver config).
    """
    cache = cache if cache is not None else ReputationCache()
    resultado = {}
    for ip in ips:
        info = cache.get(ip)
        if info is None:
            info = check_ip_reputation(ip)
            info["categoria"] = categorizar_reputacion(info.get("score"))
            cache.set(ip, info)
        resultado[ip] = info
    return resultado


class ReputationCache:
    """Caché persistente IP -> reputación+categoría, para no repetir llamadas a la API."""

    def __init__(self, path=IP_CACHE_PATH):
        self.path = path
        self.data = {}
        if os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as f:
                    self.data = json.load(f)
            except Exception:
                self.data = {}

    def get(self, ip):
        return self.data.get(ip)

    def set(self, ip, info):
        self.data[ip] = info
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)

    def __len__(self):
        return len(self.data)
