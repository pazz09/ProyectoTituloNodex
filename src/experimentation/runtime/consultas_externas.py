"""Registro de cada intento de consulta externa (NVD, AbuseIPDB) por corrida.

## Para qué

En el piloto las llamadas HTTP de `requests` (el cliente que usan AbuseIPDB y NVD)
se **bloquean** y las herramientas contestan con su respaldo local. Para decidir
con datos —y no a ojo— si la campaña final corre con consultas reales o con respaldo
local, hay que saber **cuántas veces NODEX las intenta**, con qué parámetros y si el
respaldo respondió. Eso es lo que se registra, por corrida.

La decisión sigue PENDIENTE. Este módulo solo mide; no cambia el comportamiento del
sistema más allá de impedir la salida a la red.

## Qué se registra, por cada llamada a una herramienta

- `herramienta`: `abuseipdb` o `nvd`.
- `parametros`: lo que se consultó (`ip` o `keyword`).
- `intento_externo`: si la herramienta intentó salir a la red (en AbuseIPDB solo lo
  intenta si hay llave configurada; NVD siempre lo intenta).
- `bloqueado`: si ese intento fue bloqueado por este módulo.
- `respaldo_respondio`: si la respuesta vino del respaldo local (`fuente` distinta
  de la externa).
- `fuente_respuesta`: el campo `fuente` que devolvió la herramienta.

## Cómo se instala

Hay que llamar a `instalar()` ANTES de importar el pipeline: los agentes hacen
`from ... import herramienta` y se quedan con la función que haya en ese momento.
"""

from __future__ import annotations

import functools
import importlib
from urllib.parse import urlsplit

#: herramienta -> (módulo, función, `fuente` de una respuesta REAL del servicio,
#:                 nombre del parámetro)
HERRAMIENTAS = {
    "abuseipdb": ("src.tools.reputation", "check_ip_reputation", "abuseipdb", "ip"),
    "nvd": ("src.tools.cve", "query_cve", "nvd", "keyword"),
}


class RegistroConsultas:
    """Acumula las consultas y los intentos de salida a la red de una corrida."""

    def __init__(self) -> None:
        self.consultas: list[dict] = []
        #: Destinos (solo host) de las peticiones bloqueadas, en orden.
        self.bloqueados: list[str] = []

    def a_lista(self) -> list[dict]:
        return [dict(c) for c in self.consultas]


def bloquear_red(registro: RegistroConsultas, clase_sesion) -> None:
    """Hace fallar toda petición de `requests` y anota a dónde iba (solo el host)."""

    def bloqueada(self, *args, **kwargs):
        # `requests.get(...)` llama a `Session.request(method=..., url=...)` con
        # ARGUMENTOS POR NOMBRE; si la firma exigiera la URL posicional, el bloqueo
        # fallaría con TypeError ANTES de anotar el intento (y las herramientas, que
        # tragan toda excepción, caerían igual al respaldo): el contador marcaría 0
        # siempre. Defecto real de la comparación de modelos del 15-oct-2026.
        url = kwargs.get("url", args[1] if len(args) > 1 else "")
        registro.bloqueados.append(urlsplit(str(url)).netloc or str(url))
        raise ConnectionError("llamada externa bloqueada: no autorizada en el piloto")

    clase_sesion.request = bloqueada


def envolver(registro: RegistroConsultas, herramienta: str, modulo=None) -> None:
    """Reemplaza la función de la herramienta por una que registra cada consulta."""
    nombre_modulo, nombre_funcion, fuente_externa, parametro = HERRAMIENTAS[herramienta]
    modulo = modulo or importlib.import_module(nombre_modulo)
    original = getattr(modulo, nombre_funcion)

    @functools.wraps(original)
    def registrada(*args, **kwargs):
        antes = len(registro.bloqueados)
        resultado = original(*args, **kwargs)
        nuevos = registro.bloqueados[antes:]
        valor = args[0] if args else kwargs.get(parametro)
        fuente = resultado.get("fuente") if isinstance(resultado, dict) else None
        registro.consultas.append({
            "orden": len(registro.consultas) + 1,
            "herramienta": herramienta,
            "parametros": {parametro: valor},
            "intento_externo": bool(nuevos),
            "bloqueado": bool(nuevos),
            "n_intentos_bloqueados": len(nuevos),
            "hosts": sorted(set(nuevos)),
            "respaldo_respondio": fuente is not None and fuente != fuente_externa,
            "fuente_respuesta": fuente,
        })
        return resultado

    setattr(modulo, nombre_funcion, registrada)


def instalar(registro: RegistroConsultas, clase_sesion=None) -> None:
    """Bloquea la red y registra las dos herramientas. Llamar ANTES de importar el pipeline."""
    if clase_sesion is None:
        import requests
        clase_sesion = requests.sessions.Session
    bloquear_red(registro, clase_sesion)
    for herramienta in HERRAMIENTAS:
        envolver(registro, herramienta)
