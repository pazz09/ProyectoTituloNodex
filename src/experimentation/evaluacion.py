"""Evaluación de corridas YA guardadas contra el ground truth.

Es el **único módulo del proyecto que abre `experiments/ground_truth/`**.
Está separado de `orquestador.py` a propósito: el orquestador corre
arquitecturas y este módulo las corrige, y mientras una corrida está en
curso la referencia no está cargada en ninguna variable del proceso, así que
no puede filtrarse a un prompt por descuido. Antes las dos mitades convivían
en un mismo archivo; ahora `orquestador.py` no contiene ninguna ruta al
ground truth, y eso se verifica por AST en las pruebas.

No ejecuta ninguna arquitectura. Si una corrida no está guardada se cuenta
como **ausente**, no se ejecuta: la evaluación es reproducible y no depende
de cuándo se la invoque.

## Qué devuelve

Un `RegistroEvaluado` por corrida, no métricas agregadas. La agregación
(por dataset, arquitectura, condición y repetición) es de
`consolidacion.py`, que reutiliza los evaluadores de
`src/experimentation/evaluators/`. Antes `evaluar_campana` mezclaba todos
los datasets en una sola matriz de confusión por arquitectura, de modo que
BGL y UWF —preguntas distintas— se promediaban juntos.

## Cómo se combinan los estados

Para cada dimensión se toman **dos** estados y gana el más restrictivo: el de
la salida (¿el sistema produjo algo que puntuar?) y el de la referencia
(¿hay una referencia aprobada?). Una dimensión se puntúa solo si las dos
dicen `evaluable`.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path

from src.experimentation.adapters.nodex import dimension_final
from src.experimentation.evaluators import deteccion as eval_deteccion
from src.experimentation.evaluators.conjuntos import ComparacionConjuntos
from src.experimentation.evaluators.mitre import comparar_caso as comparar_mitre
from src.experimentation.evaluators.reconstruccion import (
    comparar_caso as comparar_reconstruccion,
)
from src.experimentation.orquestador import (
    ARQUITECTURAS_CAMPANA,
    REPETICIONES,
    REPETICIONES_BASELINE,
    _casos_del_subconjunto,
    cargar_subconjunto,
)
from src.experimentation.runtime import persistencia
from src.experimentation.runtime.identidad import IdentidadCorrida


#: ENMIENDA D2/D3 (15-oct-2026, fijada ANTES de la campaña). Motivo: en el piloto de desarrollo, los
#: casos con incidente en que el sistema no atribuyó ninguna técnica (ni dio eventos) salían de la
#: métrica como «no evaluables», y la exhaustividad quedaba calculada solo sobre los casos en que el
#: sistema sí dijo algo: inflada, y favorable al que se calla.
#:
#: Regla: si la corrida es VÁLIDA y COMPLETA, la referencia existe y el sistema no entregó ningún evento
#: (D2) ni técnica (D3), eso es una OMISIÓN: el caso cuenta con exhaustividad 0 y precisión indefinida
#: (no hubo predicciones), y NO sale de la métrica. Si la corrida falló o su formato es inválido, sigue
#: «no evaluable» y se informa aparte. La cobertura («k de n evaluables») va junto a cada cifra.
REGLA_D2_D3 = {
    "version": "v2-omision-cuenta",
    "enmienda": "2026-10-15",
    "motivo": ("observación del piloto de desarrollo: los casos sin atribución salían de la métrica "
               "e inflaban la exhaustividad"),
    "texto": ("corrida válida y completa + referencia existente + sin eventos/técnicas = omisión "
              "(exhaustividad 0, precisión indefinida, cuenta); corrida fallida o de formato "
              "inválido = no evaluable, aparte"),
}


def corrida_valida_y_completa(ejecucion: dict | None, salida: dict) -> bool:
    """`True` si la corrida terminó `completa` y su salida trae un veredicto booleano.

    Sin metadatos de ejecución (formato anterior) no se puede afirmar: es `False`.
    """
    return bool(
        ejecucion
        and ejecucion.get("estado") == "completa"
        and (salida.get("_meta") or {}).get("veredicto_booleano_presente")
    )


@dataclass
class RegistroEvaluado:
    """Una corrida guardada, ya comparada con su referencia."""

    run_id: str
    case_id: str
    dataset: str
    condicion: str
    arquitectura: str
    repeticion: int
    #: Cómo terminó la corrida, tal como quedó guardado. `None` si el archivo
    #: no trae metadatos de ejecución (formato anterior).
    estado_ejecucion: str | None
    #: Estado final de cada dimensión: el más restrictivo entre el de la
    #: salida y el de la referencia.
    estados: dict = field(default_factory=dict)
    prediccion: str | None = None
    referencia: str | None = None
    #: `TP`, `FP`, `FN`, `TN` o `NA` si la detección no fue puntuable.
    resultado_d1: str = "NA"
    comparacion_d2: ComparacionConjuntos | None = None
    uids_inventados_d2: int = 0
    comparacion_d3: ComparacionConjuntos | None = None
    sin_evidencia_d3: list = field(default_factory=list)
    #: `True` si el archivo guardado no trae `ejecucion`: sus estados por
    #: dimensión son desconocidos y todo figura como no evaluable. Se marca
    #: para que ese vacío no se confunda con un sistema que falla.
    sin_metadatos_de_ejecucion: bool = False
    #: `True` si en esa dimensión el sistema no entregó nada en una corrida válida y completa y la
    #: referencia existe: cuenta como omisión (ver `REGLA_D2_D3`), no sale de la métrica.
    omision_d2: bool = False
    omision_d3: bool = False

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "case_id": self.case_id,
            "dataset": self.dataset,
            "condicion": self.condicion,
            "arquitectura": self.arquitectura,
            "repeticion": self.repeticion,
            "estado_ejecucion": self.estado_ejecucion,
            "estados": self.estados,
            "prediccion": self.prediccion,
            "referencia": self.referencia,
            "resultado_d1": self.resultado_d1,
            "d2": self.comparacion_d2.to_dict() if self.comparacion_d2 else None,
            "uids_inventados_d2": self.uids_inventados_d2,
            "d3": self.comparacion_d3.to_dict() if self.comparacion_d3 else None,
            "sin_evidencia_d3": list(self.sin_evidencia_d3),
            "sin_metadatos_de_ejecucion": self.sin_metadatos_de_ejecucion,
            "omision_d2": self.omision_d2,
            "omision_d3": self.omision_d3,
        }


@dataclass
class ResultadoEvaluacion:
    subconjunto: str
    particion: str
    config_version: str
    arquitecturas: tuple[str, ...]
    registros: list[RegistroEvaluado] = field(default_factory=list)
    #: `run_id` esperados que no están guardados.
    ausentes: list[str] = field(default_factory=list)
    #: Total de corridas que el plan esperaba.
    esperadas: int = 0


def _cargar_referencia(raiz_repo: Path, dataset: str, particion: str,
                       case_id: str) -> dict:
    """Lee la referencia de un caso. **La única función que lo hace.**"""
    archivo = (
        raiz_repo / "experiments" / "ground_truth" / dataset / particion
        / f"{case_id}.json"
    )
    return json.loads(archivo.read_text(encoding="utf-8"))


def _uids_del_caso(raiz_repo: Path, dataset: str, particion: str,
                   case_id: str) -> frozenset[str] | None:
    """Los `uid` que realmente están en el caso, o `None` si no tiene.

    Sirve para distinguir un evento mal elegido de uno INVENTADO. Lee el
    contenido del caso (la entrada), no la referencia. Solo UWF trae una
    columna `uid`; HDFS y BGL no tienen identificador estable.
    """
    archivo = raiz_repo / "experiments" / "cases" / dataset / particion / f"{case_id}.csv"
    if not archivo.is_file():
        return None
    with archivo.open(encoding="utf-8", newline="") as f:
        lector = csv.DictReader(f)
        if not lector.fieldnames or "uid" not in lector.fieldnames:
            return None
        return frozenset(fila["uid"] for fila in lector if fila.get("uid"))


def evaluar_corridas(
    raiz_repo: Path,
    subconjunto_nombre: str,
    config_version: str,
    arquitecturas: tuple[str, ...] = ARQUITECTURAS_CAMPANA,
) -> ResultadoEvaluacion:
    """Evalúa las corridas guardadas de un subconjunto. No ejecuta nada."""
    subconjunto = cargar_subconjunto(raiz_repo, subconjunto_nombre)
    particion = subconjunto["particion"]
    resultado = ResultadoEvaluacion(
        subconjunto=subconjunto_nombre,
        particion=particion,
        config_version=config_version,
        arquitecturas=tuple(arquitecturas),
    )

    for dataset, case_id in _casos_del_subconjunto(subconjunto):
        referencia = _cargar_referencia(raiz_repo, dataset, particion, case_id)
        uids_caso = _uids_del_caso(raiz_repo, dataset, particion, case_id)
        condicion = case_id.split("_")[2]

        for arquitectura in arquitecturas:
            repeticiones = (
                REPETICIONES_BASELINE if arquitectura == "baseline_reglas"
                else REPETICIONES.get(particion, 1)
            )
            for repeticion in range(1, repeticiones + 1):
                identidad = IdentidadCorrida(
                    case_id=case_id, dataset=dataset, arquitectura=arquitectura,
                    repeticion=repeticion, config_version=config_version,
                )
                resultado.esperadas += 1
                ruta = persistencia.rutas(identidad, raiz_repo).salida
                if not ruta.is_file():
                    resultado.ausentes.append(identidad.run_id)
                    continue
                resultado.registros.append(_evaluar_una(
                    raiz_repo, identidad, ruta, condicion, referencia, uids_caso,
                ))
    return resultado


def _evaluar_una(
    raiz_repo: Path,
    identidad: IdentidadCorrida,
    ruta: Path,
    condicion: str,
    referencia: dict,
    uids_caso: frozenset[str] | None,
) -> RegistroEvaluado:
    guardado = persistencia.leer_salida(ruta)
    salida = guardado["salida"]
    ejecucion = guardado.get("ejecucion")
    estados_salida = (ejecucion or {}).get("estados_por_dimension") or {}

    registro = RegistroEvaluado(
        run_id=identidad.run_id,
        case_id=identidad.case_id,
        dataset=identidad.dataset,
        condicion=condicion,
        arquitectura=identidad.arquitectura,
        repeticion=identidad.repeticion,
        estado_ejecucion=(ejecucion or {}).get("estado"),
        sin_metadatos_de_ejecucion=ejecucion is None,
    )
    estado_ref = referencia["estado_dimension"]
    valida = corrida_valida_y_completa(ejecucion, salida)

    # --- D1 detección ---
    d1 = dimension_final(estados_salida.get("deteccion", "no_evaluable"),
                         estado_ref.get("deteccion", "no_aplica"))
    registro.estados["deteccion"] = d1
    if d1 == "evaluable" and salida.get("classification"):
        par = eval_deteccion.ParDeteccion(
            case_id=identidad.case_id,
            prediccion=salida["classification"],
            referencia=referencia["etiqueta_deteccion"],
        )
        registro.prediccion, registro.referencia = par.prediccion, par.referencia
        conteo = eval_deteccion.contar([par])
        registro.resultado_d1 = next(
            nombre.upper() for nombre in ("tp", "fp", "fn", "tn")
            if getattr(conteo, nombre) == 1
        )

    # --- D2 reconstrucción ---
    estado_d2 = estados_salida.get("reconstruccion", "no_evaluable")
    omitio_d2 = estado_d2 == "no_evaluable" and valida
    if omitio_d2:
        estado_d2 = "evaluable"     # REGLA_D2_D3: la omisión se puntúa, no se descarta
    d2 = dimension_final(estado_d2, estado_ref.get("reconstruccion", "no_aplica"))
    registro.estados["reconstruccion"] = d2
    registro.omision_d2 = omitio_d2 and d2 == "evaluable"
    if d2 == "evaluable":
        # El matching va por `evidence_uids`, NO por el id del evento. En el
        # contrato d11-v1, `event_id` es la etiqueta que el sistema le pone
        # al evento y `normalizar_d11` la reemplaza por una sintética si
        # colisiona con un uid; los `evidence_uids` se validan contra el
        # catálogo de evidencia, indexado por el uid real del registro.
        citados: list[str] = []
        for evento in salida.get("reconstructed_events") or []:
            for uid in evento.get("evidence_uids") or []:
                if str(uid) not in citados:
                    citados.append(str(uid))
        comparacion, diag = comparar_reconstruccion(
            identidad.case_id, citados,
            tuple(referencia.get("core_event_uids") or ()),
            uids_del_caso=uids_caso,
        )
        registro.comparacion_d2 = comparacion
        registro.uids_inventados_d2 = diag["n_uids_inventados"]

    # --- D3 MITRE, solo nivel técnica ---
    estado_d3 = estados_salida.get("mitre", "no_evaluable")
    omitio_d3 = estado_d3 == "no_evaluable" and valida
    if omitio_d3:
        estado_d3 = "evaluable"     # REGLA_D2_D3
    d3 = dimension_final(estado_d3, estado_ref.get("mitre", "no_aplica"))
    registro.estados["mitre"] = d3
    registro.omision_d3 = omitio_d3 and d3 == "evaluable"
    por_nivel = referencia.get("estado_mitre_por_nivel") or {}
    if d3 == "evaluable" and por_nivel.get("tecnica") == "evaluable":
        # Decisión del 7-oct-2026: el scoring de D3 se fija en
        # `label_technique`. El contrato no lleva nivel y `label_tactic` queda
        # como información complementaria del dataset.
        atribuciones = [
            dict(item, nivel="tecnica")
            for item in ((salida.get("mitre") or {}).get("techniques") or [])
        ]
        comparacion, diag = comparar_mitre(
            identidad.case_id, atribuciones,
            referencia.get("referencias_mitre") or [], "tecnica",
        )
        registro.comparacion_d3 = comparacion
        registro.sin_evidencia_d3 = diag["atribuciones_sin_evidencia_descartadas"]

    return registro
