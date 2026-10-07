"""Registro de telemetría de las llamadas al modelo (Fase 6).

**No cambia ninguna decisión de NODEX.** Observa y anota: no reintenta, no
elige modelo, no altera el flujo ni los valores de retorno. Si no hay un
grabador activo, cada función de acá es un no-op, así que la web, la API y
el CLI se comportan exactamente igual que antes.

## Por qué hay dos contadores de llamadas

Una invocación de `llm_json()` puede producir **varias** llamadas HTTP:

1. el bucle de `retries` por JSON inválido vuelve a pedirle al modelo;
2. `_generate_con_backoff` reintenta ante 503 y 429-por-minuto;
3. `_generate_con_fallback` repite la secuencia completa con el modelo de
   respaldo si el principal agota sus reintentos.

Por eso se cuentan dos cosas distintas y se informan por separado:

- **`llamadas_logicas`**: invocaciones de `llm_json()`, es decir pasos de
  agente. Son 6 por corrida de NODEX en el camino sin bucles.
- **`llamadas_api`**: llamadas reales a `generate_content`, reintentos
  incluidos.

Confundirlas sería contar de menos o de más. Y los **tokens se suman sobre
las llamadas físicas**, porque un reintento también consume: si solo se
registrara la respuesta final, el consumo quedaría subestimado justo en las
corridas problemáticas, que son las que más interesa medir.

## `None` nunca es cero

Cuando el proveedor no informa un contador, el campo queda `None`. No se
estima ni se rellena con 0: un 0 se promedia y baja el consumo medio sin que
nadie lo note. Es el mismo criterio que ya aplica
`src/experimentation/evaluators/consumo.py`.

Nótese que el `print` de tokens que ya tenía `llm_json` usa
`getattr(um, "thoughts_token_count", 0)`, con 0 por omisión. Eso está bien
para un mensaje en pantalla, pero no para una métrica: acá se lee el mismo
atributo conservando el `None`.

## Atribución al agente

Se deduce recorriendo la pila hasta el primer marco de `src/agents/`. Se
eligió así para **no tocar los agentes**: pasarles un parámetro nuevo a los
cinco obligaría a modificar archivos que la implementación externa de D-11
también está editando, con riesgo de conflicto y sin ganar precisión.
"""

from __future__ import annotations

import sys
import time
from contextvars import ContextVar
from dataclasses import asdict, dataclass, field

#: Grabador activo. `None` significa "no se está midiendo": todas las
#: funciones de este módulo se vuelven no-ops.
_grabador: ContextVar["GrabadorLlm | None"] = ContextVar(
    "grabador_llm", default=None
)

#: Contexto de la invocación lógica en curso (qué agente, qué reintento de
#: JSON). Vive en un ContextVar para no cambiar ninguna firma de `src/llm.py`.
_contexto: ContextVar[dict] = ContextVar("contexto_llm", default={})

#: Prefijos de módulo que se consideran "el agente que llamó".
_PREFIJOS_AGENTE = ("src.agents.", "src.experimentation.runners.")


@dataclass
class LlamadaApi:
    """Una llamada real a `generate_content`, reintentos incluidos."""

    indice: int
    #: Agente que originó la invocación lógica, deducido de la pila.
    agente: str | None = None
    #: Invocación lógica (`llm_json`) a la que pertenece, 1-indexada.
    llamada_logica: int | None = None
    #: Reintento por JSON inválido dentro de esa invocación, 0 el primero.
    intento_json: int | None = None
    modelo_solicitado: str | None = None
    #: El modelo que realmente se llamó. Difiere del solicitado cuando el
    #: principal agotó sus reintentos y entró el de respaldo.
    modelo_efectivo: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    reasoning_tokens: int | None = None
    total_tokens: int | None = None
    latencia_s: float | None = None
    error: str | None = None

    @property
    def uso_fallback(self) -> bool:
        return bool(
            self.modelo_solicitado
            and self.modelo_efectivo
            and self.modelo_solicitado != self.modelo_efectivo
        )

    def to_dict(self) -> dict:
        d = asdict(self)
        d["uso_fallback"] = self.uso_fallback
        return d


def _entero_o_none(valor) -> int | None:
    """Conserva `None`; rechaza booleanos y cualquier cosa no entera."""
    if isinstance(valor, bool) or not isinstance(valor, int):
        return None
    return valor


@dataclass
class GrabadorLlm:
    """Acumula la telemetría de una corrida."""

    run_id: str | None = None
    llamadas_api: list[LlamadaApi] = field(default_factory=list)
    #: Invocaciones de `llm_json()`, o sea pasos de agente.
    llamadas_logicas: int = 0

    # --- lo que llama `src/llm.py` ---------------------------------------

    def abrir_logica(self, agente: str | None) -> int:
        self.llamadas_logicas += 1
        return self.llamadas_logicas

    def registrar(
        self,
        modelo_efectivo: str,
        modelo_solicitado: str | None,
        latencia_s: float,
        respuesta=None,
        error: str | None = None,
    ) -> None:
        contexto = _contexto.get()
        llamada = LlamadaApi(
            indice=len(self.llamadas_api) + 1,
            agente=contexto.get("agente"),
            llamada_logica=contexto.get("llamada_logica"),
            intento_json=contexto.get("intento_json"),
            modelo_solicitado=modelo_solicitado,
            modelo_efectivo=modelo_efectivo,
            latencia_s=latencia_s,
            error=error,
        )
        uso = getattr(respuesta, "usage_metadata", None) if respuesta else None
        if uso is not None:
            llamada.input_tokens = _entero_o_none(
                getattr(uso, "prompt_token_count", None)
            )
            llamada.output_tokens = _entero_o_none(
                getattr(uso, "candidates_token_count", None)
            )
            # El `print` de `llm_json` usa `getattr(..., 0)`; acá se conserva
            # el `None`, porque un 0 inventado se promediaría.
            llamada.reasoning_tokens = _entero_o_none(
                getattr(uso, "thoughts_token_count", None)
            )
            llamada.total_tokens = _entero_o_none(
                getattr(uso, "total_token_count", None)
            )
        self.llamadas_api.append(llamada)

    # --- lo que lee el orquestador ---------------------------------------

    def _sumar(self, campo: str) -> int | None:
        valores = [
            getattr(llamada, campo)
            for llamada in self.llamadas_api
            if getattr(llamada, campo) is not None
        ]
        return sum(valores) if valores else None

    def _parciales(self) -> dict:
        """Campos que solo algunas llamadas informaron.

        Una suma parcial presentada como total subestimaría el consumo, así
        que la parcialidad se declara en vez de disimularse.
        """
        parciales = {}
        for campo in ("input_tokens", "output_tokens", "reasoning_tokens",
                      "total_tokens"):
            informadas = sum(
                1 for llamada in self.llamadas_api
                if getattr(llamada, campo) is not None
            )
            if informadas and informadas < len(self.llamadas_api):
                parciales[campo] = {
                    "informadas": informadas,
                    "totales": len(self.llamadas_api),
                }
        return parciales

    @property
    def uso_fallback(self) -> bool:
        return any(llamada.uso_fallback for llamada in self.llamadas_api)

    def to_dict(self) -> dict:
        entrada = self._sumar("input_tokens")
        salida = self._sumar("output_tokens")
        razonamiento = self._sumar("reasoning_tokens")
        informado = self._sumar("total_tokens")
        # Se prefiere el total que informa el proveedor. Si no lo informa, se
        # suma de las partes, y queda declarado de dónde salió: la suma de
        # partes puede no incluir tokens que el proveedor contabilice aparte.
        total = informado
        origen_total = "proveedor"
        if total is None and (entrada is not None or salida is not None):
            total = (entrada or 0) + (salida or 0) + (razonamiento or 0)
            origen_total = "suma_de_partes"
        elif total is None:
            origen_total = "no_informado"

        errores = [
            {"llamada": llamada.indice, "error": llamada.error}
            for llamada in self.llamadas_api if llamada.error
        ]
        por_agente: dict = {}
        for llamada in self.llamadas_api:
            clave = llamada.agente or "desconocido"
            registro = por_agente.setdefault(
                clave, {"llamadas_api": 0, "input_tokens": None,
                        "output_tokens": None, "latencia_s": 0.0}
            )
            registro["llamadas_api"] += 1
            for campo in ("input_tokens", "output_tokens"):
                valor = getattr(llamada, campo)
                if valor is not None:
                    registro[campo] = (registro[campo] or 0) + valor
            if llamada.latencia_s is not None:
                registro["latencia_s"] += llamada.latencia_s

        return {
            "run_id": self.run_id,
            # Los dos contadores, nunca uno solo: ver el docstring del módulo.
            "llm_call_count": self.llamadas_logicas,
            "api_call_count": len(self.llamadas_api),
            "reintentos_api": max(
                0, len(self.llamadas_api) - self.llamadas_logicas
            ),
            "input_tokens": entrada,
            "output_tokens": salida,
            "reasoning_tokens": razonamiento,
            "total_tokens": total,
            "origen_total_tokens": origen_total,
            "campos_parciales": self._parciales(),
            "uso_fallback": self.uso_fallback,
            "modelos_efectivos": sorted({
                llamada.modelo_efectivo for llamada in self.llamadas_api
                if llamada.modelo_efectivo
            }),
            "latencia_api_total_s": self._sumar_flotante("latencia_s"),
            "errores": errores,
            "por_agente": por_agente,
            "llamadas": [llamada.to_dict() for llamada in self.llamadas_api],
        }

    def _sumar_flotante(self, campo: str) -> float | None:
        valores = [
            getattr(llamada, campo)
            for llamada in self.llamadas_api
            if getattr(llamada, campo) is not None
        ]
        return sum(valores) if valores else None


# --- API que usa `src/llm.py` --------------------------------------------

def grabador_activo() -> GrabadorLlm | None:
    return _grabador.get()


def activar(run_id: str | None = None) -> GrabadorLlm:
    """Activa un grabador para el contexto actual y lo devuelve."""
    grabador = GrabadorLlm(run_id=run_id)
    _grabador.set(grabador)
    return grabador


def desactivar() -> None:
    _grabador.set(None)


def agente_desde_la_pila() -> str | None:
    """Primer marco de `src/agents/` en la pila, o `None`.

    Recorre los marcos con `sys._getframe` en vez de `inspect.stack()`:
    `inspect.stack()` lee el código fuente de cada marco para armar el
    contexto, lo que cuesta milisegundos. Acá solo hacen falta el nombre del
    módulo y de la función.
    """
    try:
        marco = sys._getframe(1)
    except ValueError:  # pragma: no cover - sin pila disponible
        return None
    profundidad = 0
    while marco is not None and profundidad < 30:
        nombre_modulo = marco.f_globals.get("__name__", "")
        if nombre_modulo.startswith(_PREFIJOS_AGENTE):
            return f"{nombre_modulo.rsplit('.', 1)[-1]}.{marco.f_code.co_name}"
        marco = marco.f_back
        profundidad += 1
    return None


class invocacion_logica:  # noqa: N801 - se usa como context manager
    """Marca una invocación de `llm_json()` y su reintento de JSON.

    Es un no-op si no hay grabador activo, de modo que `src/llm.py` puede
    usarlo siempre sin preguntar.
    """

    def __init__(self, intento_json: int):
        self._intento = intento_json
        self._testigo = None

    def __enter__(self):
        grabador = _grabador.get()
        if grabador is None:
            return None
        agente = agente_desde_la_pila()
        indice = (
            grabador.abrir_logica(agente) if self._intento == 0
            else grabador.llamadas_logicas
        )
        self._testigo = _contexto.set({
            "agente": agente,
            "llamada_logica": indice,
            "intento_json": self._intento,
        })
        return grabador

    def __exit__(self, *_excepcion) -> bool:
        if self._testigo is not None:
            _contexto.reset(self._testigo)
            self._testigo = None
        # Nunca suprime una excepción: la telemetría no cambia el flujo.
        return False


def registrar_llamada(
    modelo_efectivo: str,
    modelo_solicitado: str | None,
    comenzado: float,
    respuesta=None,
    error: str | None = None,
) -> None:
    """Anota una llamada física. No-op sin grabador activo."""
    grabador = _grabador.get()
    if grabador is None:
        return
    grabador.registrar(
        modelo_efectivo=modelo_efectivo,
        modelo_solicitado=modelo_solicitado,
        latencia_s=time.monotonic() - comenzado,
        respuesta=respuesta,
        error=error,
    )
