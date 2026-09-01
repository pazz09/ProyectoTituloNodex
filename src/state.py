"""Definición del estado compartido del grafo (LogGuardState).

Migrado desde la celda 22 del notebook de Colab (sección "1. EL ESTADO DINÁMICO").
Usa typing_extensions.TypedDict (no typing.TypedDict) porque así lo hace el
notebook y porque el Informe (Tabla 8.9) lista typing-extensions>=4.0 como
dependencia explícita del prototipo.
"""

from typing import Annotated, List

from typing_extensions import TypedDict


def limpiar_o_acumular(actuales: list, nuevos: list):
    """Reducer para recordar el historial de fallos.

    Si el nodo emisor envía una lista vacía, se interpreta como "reiniciar"
    (p. ej. tras una corrección exitosa); si no, se acumula.
    """
    if nuevos == []:
        return []
    return actuales + nuevos


class LogGuardState(TypedDict):
    resumen_logs: dict
    firma: str
    diagnostico: str
    necesita_rag: bool               # Router 1: ¿va a ChromaDB?
    usar_cve: bool                   # Router 2: ¿va a NVD?
    contexto_rag: list
    cves_encontrados: list
    comandos_mitigacion: List[str]
    comandos_validos: bool           # Router 3: ¿ciclo de corrección?
    motivos_rechazo: Annotated[List[str], limpiar_o_acumular]
    confianza: float
    intentos_correccion: int         # evita loops infinitos en router_validacion
