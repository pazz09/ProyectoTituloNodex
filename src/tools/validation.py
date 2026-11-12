"""Validación determinística de comandos de mitigación propuestos por el LLM.

Migrado desde la celda 13 del notebook de Colab.

**NODEX final, Fase A (M7).** Con `VALIDACION_COMANDOS_ESTRICTA` (por omisión):

- se rechazan las reglas que ABREN el firewall o levantan bloqueos
  (`-j ACCEPT`, `ufw allow`, `fail2ban-client ... unban`, `firewall-cmd
  --add-port/--add-service`, `nft ... accept`, desactivar o vaciar el
  firewall);
- se rechaza escribir o redirigir a un archivo fuera de
  `MITIGACION_DIR_SALIDA` (`>`, `>>`, `tee`, `sed -i`, `dd of=`, `truncate`),
  salvo `/dev/null`;
- se amplía la lista de comandos destructivos;
- un binario no reconocido INVALIDA el comando (antes solo se anotaba). La
  lista de permitidos incluye herramientas de diagnóstico de solo lectura,
  que son las que la mitigación debe usar ante una anomalía operativa.

Cada comando rechazado queda en `rechazados` con sus motivos.
"""

import posixpath
import re
import shlex

_PELIGROSO = [r"rm\s+-rf\s+/", r":\(\)\s*\{", r"mkfs", r"dd\s+if=", r">\s*/dev/sd",
              r"chmod\s+-R\s+777\s+/", r"curl.+\|\s*sh", r"wget.+\|\s*sh"]
_PERMITIDOS = ("iptables", "ufw", "fail2ban-client", "systemctl", "sshd", "sed",
               "passwd", "usermod", "nft", "firewall-cmd", "echo", "sysctl")

# --- reglas estrictas (M7) ---------------------------------------------------
_ABRE_FIREWALL = [
    (r"-j\s+ACCEPT\b", "abre el firewall (-j ACCEPT)"),
    (r"\b(iptables|ip6tables)\b.*\s-P\s+\S+\s+ACCEPT\b", "política por omisión ACCEPT"),
    (r"\bufw\s+(allow|disable)\b", "abre o desactiva ufw"),
    (r"\bfail2ban-client\b.*\bunban(ip)?\b", "levanta un bloqueo de fail2ban"),
    (r"\bfirewall-cmd\b.*--add-(port|service|source)\b", "abre un puerto o servicio en firewalld"),
    (r"\bnft\b.*\baccept\b", "regla nft accept"),
    (r"\b(iptables|ip6tables)\s+(-F|--flush)\b", "vacía las reglas del firewall"),
    (r"\bnft\s+flush\b", "vacía las reglas de nftables"),
    (r"\bsystemctl\s+(stop|disable|mask)\s+(firewalld|ufw|iptables|nftables|fail2ban)\b",
     "detiene el firewall o fail2ban"),
]
_DESTRUCTIVO = [
    (r"\brm\s+(-[a-zA-Z]*[rRf][a-zA-Z]*\s+)", "borrado recursivo o forzado"),
    (r"\b(shred|wipefs)\b", "destruye datos"),
    (r"\b(shutdown|reboot|halt|poweroff)\b", "apaga o reinicia el equipo"),
    (r"\buserdel\b", "elimina usuarios"),
    (r"\bkill(all)?\s+-9\s+1\b", "mata init"),
    (r"\bchmod\s+(-R\s+)?777\b", "permisos 777"),
]
_PERMITIDOS_SOLO_LECTURA = (
    "journalctl", "dmesg", "cat", "less", "more", "tail", "head", "grep", "egrep", "zgrep",
    "zcat", "awk", "wc", "sort", "uniq", "ls", "stat", "find", "df", "du", "free", "uptime",
    "top", "ps", "pgrep", "ss", "netstat", "lsof", "ip", "ifconfig", "ping", "traceroute",
    "tracepath", "dig", "nslookup", "host", "lsblk", "blkid", "smartctl", "mdadm", "sensors",
    "ipmitool", "lscpu", "lspci", "lsusb", "dmidecode", "uname", "who", "w", "last", "lastb",
    "id", "getent", "date", "hostname", "mount", "findmnt", "vmstat", "iostat", "mpstat",
    "sar", "tcpdump", "nmcli", "conntrack", "aureport", "ausearch", "tee", "dd", "truncate",
)
_ESCRITURA = [
    re.compile(r"(?:^|[^0-9&<>])>>?\s*(?P<ruta>[^\s;&|]+)"),
    re.compile(r"\btee\s+(?:-a\s+)?(?P<ruta>[^\s;&|]+)"),
    re.compile(r"\bdd\b.*\bof=(?P<ruta>[^\s;&|]+)"),
    re.compile(r"\btruncate\b.*\s(?P<ruta>/[^\s;&|]+)"),
]


def _destinos_sed(cmd: str) -> list[str]:
    """Archivos que `sed -i` modificaría (los argumentos que parecen rutas)."""
    if not re.search(r"\bsed\b.*\s-i", cmd):
        return []
    try:
        partes = shlex.split(cmd)
    except ValueError:
        partes = cmd.split()
    return [p for p in partes[1:] if p.startswith("/") or p.startswith("./") or p.startswith("~")]


def _fuera_de(ruta: str, directorio: str) -> bool:
    ruta = ruta.strip("'\"")
    if ruta in ("/dev/null", "&1", "&2"):
        return False
    base = posixpath.normpath(directorio)
    normal = posixpath.normpath(ruta if ruta.startswith("/") else posixpath.join(base, ruta))
    return not (normal == base or normal.startswith(base + "/"))


def motivos_estrictos(cmd: str, dir_salida: str) -> list[str]:
    """Motivos de rechazo de las reglas estrictas (vacío si el comando pasa)."""
    motivos = []
    for patron, motivo in _ABRE_FIREWALL:
        if re.search(patron, cmd):
            motivos.append(f"ABRE_FIREWALL: {motivo}")
    for patron, motivo in _DESTRUCTIVO:
        if re.search(patron, cmd):
            motivos.append(f"DESTRUCTIVO: {motivo}")
    destinos = [m.group("ruta") for r in _ESCRITURA for m in r.finditer(cmd)] + _destinos_sed(cmd)
    for destino in destinos:
        if _fuera_de(destino, dir_salida):
            motivos.append(f"ESCRITURA_FUERA_DE_DIRECTORIO: '{destino}' (solo se permite {dir_salida})")
    return motivos


def validate_solution(commands) -> dict:
    """Valida comandos de mitigación: bloquea patrones destructivos y exige binarios permitidos."""
    from src.config import MITIGACION_DIR_SALIDA, VALIDACION_COMANDOS_ESTRICTA

    if isinstance(commands, str):
        commands = [commands]
    commands = commands or []
    motivos, valido, rechazados = [], True, []
    permitidos = set(_PERMITIDOS) | (set(_PERMITIDOS_SOLO_LECTURA) if VALIDACION_COMANDOS_ESTRICTA else set())
    for cmd in commands:
        propios = []
        for pat in _PELIGROSO:
            if re.search(pat, cmd):
                propios.append(f"PELIGROSO: '{cmd}'")
        primer = cmd.strip().split()[0] if cmd.strip() else ""
        base = primer.split("/")[-1]
        if base == "sudo" and len(cmd.split()) > 1:
            base = cmd.split()[1].split("/")[-1]
        desconocido = bool(base) and base not in permitidos and base not in ("sudo",)
        if VALIDACION_COMANDOS_ESTRICTA:
            propios += motivos_estrictos(cmd, MITIGACION_DIR_SALIDA)
            if desconocido:
                propios.append(f"BINARIO_NO_RECONOCIDO: '{base}'")
        if propios:
            valido = False
            rechazados.append({"comando": cmd, "motivos": propios})
            motivos.extend(f"{m} en '{cmd}'" if not m.startswith("PELIGROSO") else m for m in propios)
        if desconocido and not VALIDACION_COMANDOS_ESTRICTA:
            # Comportamiento anterior (modo no estricto): se anota y no invalida.
            motivos.append(f"binario no reconocido: '{base}' en '{cmd}'")
    return {"valido": valido, "n_comandos": len(commands), "motivos": motivos or ["OK"],
            "rechazados": rechazados, "n_rechazados": len(rechazados)}
