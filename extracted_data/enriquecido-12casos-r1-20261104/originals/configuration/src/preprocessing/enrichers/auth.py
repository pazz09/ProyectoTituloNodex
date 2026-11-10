"""Enriquecedor de autenticación: sshd, sudo, PAM (Fase 6 del plan).

No estaba en la lista original del plan, que nombra HDFS, BGL y Zeek. Se
agrega porque sin él el preprocesamiento **no cubre el caso de uso
principal del sistema**: hace falta reconocer "Failed password" y contar
el evento como `acceso_fallido`; el decoder de syslog no hace eso, porque
clasificar el resultado de una operación a partir del texto del mensaje es
conocimiento del producto, no de la estructura del formato.

Sin este perfil, un lote de auth-log —el escenario de fuerza bruta SSH que
usa el informe— reportaría cero eventos críticos.

Extrae únicamente lo que el mensaje declara: si la autenticación falló o
tuvo éxito, y sobre qué usuario. **No decide que hay un ataque**: que haya
diez fallos seguidos sea fuerza bruta o un dedo pesado es justamente lo que
los agentes tienen que interpretar.
"""

import re

from src.preprocessing.enrichers.base import Enricher
from src.preprocessing.models import NormalizedEvent

# Servicios de autenticación conocidos, tal como aparecen en el tag syslog.
_SERVICIOS_AUTH = {"sshd", "sudo", "su", "login", "su-l", "polkitd",
                   "gdm-password", "vsftpd", "proftpd"}

_FALLO_RE = re.compile(
    r"(failed password|authentication failure|invalid user|failed publickey"
    r"|failed none|auth(entication)? failed|permission denied"
    r"|incorrect password|maximum authentication attempts exceeded)",
    re.IGNORECASE,
)
_EXITO_RE = re.compile(
    r"(accepted password|accepted publickey|session opened|authentication succeeded)",
    re.IGNORECASE,
)

# Usuario objetivo. Se prueban los patrones del más específico al más
# general, así que "for invalid user admin" devuelve "admin" (no "invalid",
# que sería el resultado de capturar la primera alternativa que aparece en
# el texto en vez de la más específica).
_USUARIO_RES = (
    re.compile(r"invalid user\s+([A-Za-z0-9._\-]+)", re.IGNORECASE),
    re.compile(r"user\s+([A-Za-z0-9._\-]+)", re.IGNORECASE),
    re.compile(r"\bfor\s+([A-Za-z0-9._\-]+)\s+from\b", re.IGNORECASE),
)


class AuthEnricher(Enricher):
    # El nombre coincide con el del adaptador v1 ("auth_log") para que
    # `formato_detectado` sea idéntico entre motores.
    nombre = "auth_log"
    producto = "auth"

    def aplica(self, evento: NormalizedEvent) -> bool:
        servicio = (evento.service_name or evento.process_name or "").lower()
        if servicio in _SERVICIOS_AUTH:
            return True
        # Un auth-log sin tag reconocible igual se enriquece si el mensaje
        # habla claramente de autenticación.
        return bool(_FALLO_RE.search(evento.message) or _EXITO_RE.search(evento.message))

    def enriquecer(self, evento: NormalizedEvent) -> NormalizedEvent:
        mensaje = evento.message or evento.raw
        evento.event_category = "authentication"

        if _FALLO_RE.search(mensaje):
            evento.event_outcome = "failure"
            evento.event_action = "login"
        elif _EXITO_RE.search(mensaje):
            evento.event_outcome = "success"
            evento.event_action = "login"

        if not evento.source_user:
            for patron in _USUARIO_RES:
                m = patron.search(mensaje)
                if m:
                    evento.source_user = m.group(1)
                    break

        m = re.search(r"\bport\s+(\d+)", mensaje, re.IGNORECASE)
        if m and not evento.source_port:
            evento.source_port = int(m.group(1))
        return evento
