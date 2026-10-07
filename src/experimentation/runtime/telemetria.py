"""Telemetría de una corrida. §11 del plan de continuación.

Define **qué se registra y con qué garantías**, no cómo se instrumenta el
cliente LLM: eso es trabajo de la Fase 6 sobre `src/llm.py`.

Tres reglas que vienen del plan:

1. **No inventar tokens ni costos cuando el proveedor no los entrega.** Un
   `0` inventado se promedia y baja el consumo medio sin que nadie lo note.
   Un campo que el proveedor no devolvió queda `None` y se cuenta como
   ausente.
2. **Las credenciales quedan fuera del registro**, siempre.
3. **Modelo efectivo por llamada.** `src/config.py` tiene
   `LLM_MODEL_PRIMARY` y `LLM_MODEL_FALLBACK`: si el primario agota
   reintentos, el sistema reintenta con el otro. Una corrida que cayó al
   fallback usó otro modelo y **no es comparable**. Por eso cada llamada
   registra qué modelo respondió, y la corrida expone `uso_fallback`.

`invalid_evidence_uid_count` existe en el esquema pero solo se puebla
cuando D-11 esté integrado: hoy no hay `evidence_uids` que validar.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

#: Campos numéricos agregables que el evaluador de consumo resume.
CAMPOS_NUMERICOS = (
    "llm_call_count",
    "input_tokens",
    "output_tokens",
    "total_tokens",
    "execution_time",
    "replan_count",
    "intentos_correccion",
    "consultas_rag",
    "visitas_nodos",
    "invalid_evidence_uid_count",
)


@dataclass
class LlamadaLlm:
    """Una llamada al modelo.

    `modelo_efectivo` es el que respondió, no el que se pidió. Es la
    diferencia que importa cuando hay fallback.
    """

    indice: int
    agente: str
    modelo_solicitado: str | None = None
    modelo_efectivo: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    #: Tokens de razonamiento, cuando el proveedor los informa aparte.
    reasoning_tokens: int | None = None
    reintentos: int = 0
    error: str | None = None
    latencia_s: float | None = None

    @property
    def uso_fallback(self) -> bool:
        """`True` si respondió un modelo distinto del solicitado."""
        return bool(
            self.modelo_solicitado
            and self.modelo_efectivo
            and self.modelo_solicitado != self.modelo_efectivo
        )

    def to_dict(self) -> dict:
        d = asdict(self)
        d["uso_fallback"] = self.uso_fallback
        return d


@dataclass
class Telemetria:
    """Telemetría de una corrida completa."""

    run_id: str
    llamadas: list[LlamadaLlm] = field(default_factory=list)
    execution_time: float | None = None
    replan_count: int | None = None
    intentos_correccion: int | None = None
    consultas_rag: int | None = None
    visitas_nodos: int | None = None
    #: Solo se puebla cuando D-11 esté integrado.
    invalid_evidence_uid_count: int | None = None
    errores: list = field(default_factory=list)
    #: `True` cuando la telemetría se tomó sobre una versión del sistema sin
    #: D-11. §11 prohíbe mezclar esas mediciones con las posteriores.
    previa_a_d11: bool = True

    @property
    def llm_call_count(self) -> int:
        return len(self.llamadas)

    @property
    def uso_fallback(self) -> bool:
        """`True` si alguna llamada la respondió un modelo distinto."""
        return any(llamada.uso_fallback for llamada in self.llamadas)

    @property
    def modelos_efectivos(self) -> list[str]:
        return sorted({
            llamada.modelo_efectivo
            for llamada in self.llamadas
            if llamada.modelo_efectivo
        })

    def _sumar(self, campo: str) -> int | None:
        """Suma un campo de tokens. `None` si **ninguna** llamada lo trae.

        Si algunas llamadas lo traen y otras no, devuelve la suma de las que
        sí **y** lo declara en `campos_parciales`: una suma parcial
        presentada como total subestimaría el consumo.
        """
        valores = [
            getattr(llamada, campo)
            for llamada in self.llamadas
            if isinstance(getattr(llamada, campo), int)
            and not isinstance(getattr(llamada, campo), bool)
        ]
        return sum(valores) if valores else None

    @property
    def campos_parciales(self) -> dict:
        """Campos de token que solo algunas llamadas informaron."""
        parciales = {}
        for campo in ("input_tokens", "output_tokens", "reasoning_tokens"):
            informadas = sum(
                1
                for llamada in self.llamadas
                if isinstance(getattr(llamada, campo), int)
                and not isinstance(getattr(llamada, campo), bool)
            )
            if informadas and informadas < len(self.llamadas):
                parciales[campo] = {
                    "informadas": informadas,
                    "totales": len(self.llamadas),
                }
        return parciales

    def to_dict(self) -> dict:
        entrada = self._sumar("input_tokens")
        salida = self._sumar("output_tokens")
        razonamiento = self._sumar("reasoning_tokens")
        total = None
        if entrada is not None or salida is not None:
            total = (entrada or 0) + (salida or 0) + (razonamiento or 0)
        return {
            "run_id": self.run_id,
            "llm_call_count": self.llm_call_count,
            "input_tokens": entrada,
            "output_tokens": salida,
            "reasoning_tokens": razonamiento,
            # `None` y no 0 cuando el proveedor no entregó ningún conteo.
            "total_tokens": total,
            "execution_time": self.execution_time,
            "replan_count": self.replan_count,
            "intentos_correccion": self.intentos_correccion,
            "consultas_rag": self.consultas_rag,
            "visitas_nodos": self.visitas_nodos,
            "invalid_evidence_uid_count": self.invalid_evidence_uid_count,
            "reintentos": sum(llamada.reintentos for llamada in self.llamadas),
            "uso_fallback": self.uso_fallback,
            "modelos_efectivos": self.modelos_efectivos,
            "campos_parciales": self.campos_parciales,
            "errores": list(self.errores),
            "previa_a_d11": self.previa_a_d11,
            "llamadas": [llamada.to_dict() for llamada in self.llamadas],
        }
