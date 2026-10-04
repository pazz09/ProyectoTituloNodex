"""Configuración aislada del experimento: ChromaDB, caché y recursos externos.

Acciones 5 y 7 de la Fase 3. La idea es simple: **el experimento no toca
ningún almacén de producción**. Todo lo que NODEX escribe o lee —memoria
vectorial, caché de reputación, historial— se redirige a rutas propias del
experimento mediante variables de entorno que `src/config.py` ya respeta.

Lo que se gana con esto no es orden sino validez. Si el experimento usara
`data/chroma/`, la memoria acumulada por corridas anteriores (`host_history`
tiene un host de una corrida previa) le daría al sistema información sobre
los casos que no vino de los casos. Y si usara
`data/ip_reputation_cache.json`, una IP ya consultada respondería distinto
que una nueva, así que dos casos equivalentes dejarían de serlo.

**Nada de este módulo se ejecuta durante la preparación.** Define rutas y
devuelve variables de entorno; poblar la base y correr el sistema son
acciones de fases posteriores, con su propia autorización.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path

#: Variables que `src/config.py` **sí** lee del entorno, con el valor de
#: producción que hay que sobrescribir. Se documentan juntas porque olvidar
#: una sola rompe el aislamiento completo.
VARIABLES_AISLAMIENTO = {
    "CHROMA_PATH": "./data/chroma",
    "IP_CACHE_PATH": "./data/ip_reputation_cache.json",
}

#: El historial **no** se configura por entorno: `RUTA_DB` en
#: `src/api/historial.py` es una constante derivada de la raíz del
#: repositorio (`parents[2] / "data" / "historial.db"`). No existe ninguna
#: variable `DB_PATH`.
#:
#: Quedan dos consecuencias que conviene no confundir:
#:
#: 1. El aislamiento del historial ya está dado por el **worktree**: al
#:    correr desde el worktree de preparación, la raíz es otra y la base
#:    también. Es aislamiento por ubicación, no por configuración.
#: 2. Las funciones de persistencia aceptan un parámetro `ruta` opcional
#:    (`historial.py:76`), así que el orquestador experimental puede pasar
#:    su propia base explícitamente, sin depender de dónde esté corriendo.
#:
#: Se prefiere (2) para la campaña: depender del directorio de trabajo es
#: frágil, y un `cd` equivocado escribiría en la base de producción.
HISTORIAL_NO_CONFIGURABLE_POR_ENTORNO = {
    "constante": "src/api/historial.py::RUTA_DB",
    "derivada_de": "raíz del repositorio",
    "mecanismo_de_aislamiento": "parámetro `ruta` explícito en cada llamada",
    "riesgo_si_se_omite": (
        "la campaña escribiría en el data/historial.db del checkout donde "
        "se la invoque"
    ),
}


@dataclass
class ConfiguracionAislada:
    """Rutas exclusivas del experimento."""

    raiz: Path
    #: Base vectorial del experimento. Contendrá **solo** el catálogo MITRE.
    chroma: Path = field(init=False)
    #: Caché de reputación de IP, propia y vacía al empezar.
    cache_ip: Path = field(init=False)
    #: Historial de corridas, separado del `historial.db` de producción.
    historial: Path = field(init=False)
    #: Snapshot del inventario de conocimiento.
    inventario: Path = field(init=False)

    def __post_init__(self) -> None:
        self.chroma = self.raiz / "chroma"
        self.cache_ip = self.raiz / "ip_reputation_cache.json"
        self.historial = self.raiz / "historial.db"
        self.inventario = self.raiz / "inventario_conocimiento.json"

    def variables_entorno(self) -> dict[str, str]:
        """Variables a exportar antes de cualquier ejecución autorizada.

        Solo estas dos existen. El historial se aísla pasando `ruta`
        explícitamente, no con una variable: ver
        `HISTORIAL_NO_CONFIGURABLE_POR_ENTORNO`.
        """
        return {
            "CHROMA_PATH": str(self.chroma),
            "IP_CACHE_PATH": str(self.cache_ip),
        }

    def to_dict(self) -> dict:
        d = {k: str(v) for k, v in asdict(self).items()}
        d["variables_entorno"] = self.variables_entorno()
        d["historial"] = {
            "ruta": str(self.historial),
            "mecanismo": "parámetro `ruta` explícito, no variable de entorno",
            "detalle": HISTORIAL_NO_CONFIGURABLE_POR_ENTORNO,
        }
        return d


def configuracion_experimental(raiz_repo: Path) -> ConfiguracionAislada:
    return ConfiguracionAislada(raiz=raiz_repo / "experiments" / "knowledge")


# --- política de recursos externos ----------------------------------------

#: Política de los tres recursos externos, para la futura ejecución.
#:
#: `congelado_antes_de_ejecutar` significa que la caché se llena **una vez**,
#: en un paso autorizado aparte, y después se usa en modo solo lectura
#: durante toda la campaña. Es lo que hace comparables dos arquitecturas: si
#: la caché se fuera llenando durante la corrida, la segunda arquitectura
#: evaluada tendría respuestas que la primera tuvo que ir a buscar, y la
#: diferencia de tiempo y de consumo no mediría la arquitectura.
POLITICA_RECURSOS_EXTERNOS = {
    "abuseipdb": {
        "estado": "congelado_antes_de_ejecutar",
        "cache": "experiments/knowledge/ip_reputation_cache.json",
        "modo_durante_campana": "solo_lectura",
        "si_falta_una_ip": (
            "registrar el fallo en la telemetría del caso y marcar la "
            "dimensión afectada, no inventar una reputación por omisión"
        ),
        "consultas_de_prueba": "prohibidas en la preparación",
    },
    "nvd": {
        "estado": "congelado_antes_de_ejecutar",
        "modo_durante_campana": "solo_lectura",
        "consultas_de_prueba": "prohibidas en la preparación",
    },
    "gemini": {
        "estado": "sin_cache",
        "nota": (
            "no se cachea: el modelo es la variable que se está midiendo. "
            "Las llamadas se registran con modelo efectivo, tokens y "
            "reintentos (Fase 6)"
        ),
        "consultas_de_prueba": "prohibidas en la preparación",
    },
}


def plan_poblado_chroma(
    origen: Path, configuracion: ConfiguracionAislada
) -> dict:
    """Describe cómo se poblará la base experimental. **No la pobla.**

    El poblado copia los vectores **ya calculados** de la colección
    `attack_techniques` de la base de origen a la base del experimento. No
    recalcula embeddings, así que no carga el modelo ni necesita el JSON
    STIX, y los vectores quedan bit a bit idénticos a los de producción, que
    es lo que hace comparable un resultado con otro.

    Las colecciones de memoria (`host_history`, `error_memory`,
    `attack_patterns`) **no** se copian: son residuo de corridas previas.

    Requiere autorización explícita, porque la acción 6 de la Fase 3 gatilla
    el poblado de la base.
    """
    from src.experimentation.knowledge.inventario import (
        COLECCIONES_CONOCIMIENTO,
        COLECCIONES_MEMORIA,
    )

    return {
        "origen": str(origen),
        "destino": str(configuracion.chroma),
        "colecciones_a_copiar": list(COLECCIONES_CONOCIMIENTO),
        "colecciones_a_excluir": list(COLECCIONES_MEMORIA),
        "metodo": (
            "copiar embeddings, documentos y metadata ya almacenados; no "
            "recalcular vectores ni cargar el modelo de embeddings"
        ),
        "requiere_autorizacion": True,
        "estado": "NO_EJECUTADO",
    }
