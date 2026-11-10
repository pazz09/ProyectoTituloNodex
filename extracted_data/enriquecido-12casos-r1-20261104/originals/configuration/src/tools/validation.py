"""Validación determinística de comandos de mitigación propuestos por el LLM.

Migrado desde la celda 13 del notebook de Colab.
"""

import re

_PELIGROSO = [r"rm\s+-rf\s+/", r":\(\)\s*\{", r"mkfs", r"dd\s+if=", r">\s*/dev/sd",
              r"chmod\s+-R\s+777\s+/", r"curl.+\|\s*sh", r"wget.+\|\s*sh"]
_PERMITIDOS = ("iptables", "ufw", "fail2ban-client", "systemctl", "sshd", "sed",
               "passwd", "usermod", "nft", "firewall-cmd", "echo", "sysctl")


def validate_solution(commands) -> dict:
    """Valida comandos de mitigación: bloquea patrones destructivos y exige binarios permitidos."""
    if isinstance(commands, str):
        commands = [commands]
    commands = commands or []
    motivos, valido = [], True
    for cmd in commands:
        for pat in _PELIGROSO:
            if re.search(pat, cmd):
                valido = False
                motivos.append(f"PELIGROSO: '{cmd}'")
        primer = cmd.strip().split()[0] if cmd.strip() else ""
        base = primer.split("/")[-1]
        if base and base not in _PERMITIDOS and base not in ("sudo",):
            motivos.append(f"binario no reconocido: '{base}' en '{cmd}'")
    return {"valido": valido, "n_comandos": len(commands), "motivos": motivos or ["OK"]}
