"""Orquestador de la campaña. §13 Fases C y E del plan de continuación.

Recorre un subconjunto de casos, corre cada arquitectura, persiste cada
corrida y exporta la tabla del §14. Es la última pieza antes del piloto.

## La ejecución viene deshabilitada

`ejecutar_campana()` **no corre nada** salvo que se le pase
`ejecucion_habilitada=True` de forma explícita. Con el valor por omisión
hace un **plan en seco**: enumera exactamente qué corridas haría, cuántas
llamadas al modelo implican y qué ya está hecho, sin tocar el modelo ni el
preprocesamiento. Así se puede revisar el alcance y el costo antes de gastar
cuota.

## Separación del ground truth

El orquestador tiene dos mitades que **no se tocan**:

    ejecutar_campana()   -> corre arquitecturas. NO abre ground_truth/.
    evaluar_campana()    -> lee las salidas guardadas + ground_truth/.

Están separadas en funciones distintas a propósito. Mientras una corrida
está en curso, la referencia no está cargada en ninguna variable del
proceso, así que no puede filtrarse a un prompt por descuido.

## Reanudación

El `run_id` es determinístico, así que una campaña interrumpida se reanuda
sola: las corridas ya guardadas se detectan por la existencia del archivo y
se omiten. No se sobrescribe ninguna.

## Repeticiones (D-2)

`N=1` en desarrollo y piloto; `N=3` en la campaña final, y solo para las
arquitecturas LLM. El baseline es determinístico: repetirlo tres veces daría
tres archivos idénticos y triplicaría el conteo de casos sin aportar nada.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from src.experimentation.contracts import PROTOCOLO_VERSION
from src.experimentation.runtime.identidad import IdentidadCorrida
from src.experimentation.runtime import exportacion, persistencia

#: Repeticiones por partición (decisión D-2, cerrada el 7-oct-2026).
REPETICIONES = {"desarrollo": 1, "evaluacion": 3}

#: El baseline es determinístico: una sola corrida.
REPETICIONES_BASELINE = 1

#: Arquitecturas que consumen LLM.
ARQUITECTURAS_LLM = ("nodex_multiagente", "agente_unico")

#: Llamadas al modelo por corrida, para estimar el costo del plan en seco.
#:
#: NODEX tiene 5 nodos LLM (planificador, triage, selector de herramientas,
#: ingeniero de mitigación, auditor final) y el nodo de triage tiene dos
#: puntos de llamada, así que el piso son 6. Sube con los bucles de
#: replanificación y de corrección de comandos, que no se pueden acotar sin
#: medir. Es un **piso**, no una estimación.
LLAMADAS_POR_CORRIDA = {
    "nodex_multiagente": 6,
    "agente_unico": 1,
    "baseline_reglas": 0,
}


@dataclass
class PlanCampana:
    """Qué correría la campaña. Es lo que devuelve el plan en seco."""

    config_version: str
    particion: str
    arquitecturas: tuple[str, ...]
    corridas: list = field(default_factory=list)
    ya_hechas: list = field(default_factory=list)

    @property
    def pendientes(self) -> list:
        return self.corridas

    def resumen(self) -> dict:
        por_arquitectura: dict = {}
        llamadas_piso = 0
        for corrida in self.corridas:
            arquitectura = corrida["arquitectura"]
            por_arquitectura[arquitectura] = por_arquitectura.get(arquitectura, 0) + 1
            llamadas_piso += LLAMADAS_POR_CORRIDA.get(arquitectura, 0)
        return {
            "config_version": self.config_version,
            "particion": self.particion,
            "arquitecturas": list(self.arquitecturas),
            "corridas_pendientes": len(self.corridas),
            "corridas_ya_hechas": len(self.ya_hechas),
            "por_arquitectura": por_arquitectura,
            "llamadas_llm_piso": llamadas_piso,
            "nota_llamadas": (
                "piso, no estimación: NODEX tiene 6 puntos de llamada y sube "
                "con los bucles de replanificación y corrección, que no se "
                "pueden acotar sin medir"
            ),
            "repeticiones": REPETICIONES.get(self.particion),
        }


def cargar_subconjunto(raiz_repo: Path, nombre: str) -> dict:
    """Lee `experiments/subconjuntos/<nombre>.json`."""
    archivo = raiz_repo / "experiments" / "subconjuntos" / f"{nombre}.json"
    if not archivo.is_file():
        raise FileNotFoundError(f"no existe el subconjunto {archivo}")
    return json.loads(archivo.read_text(encoding="utf-8"))


def _casos_del_subconjunto(subconjunto: dict) -> list[tuple[str, str]]:
    """`[(dataset, case_id), ...]`, ordenado y sin repetidos."""
    vistos: list[tuple[str, str]] = []
    for dataset, condiciones in sorted(subconjunto["datasets"].items()):
        for _condicion, detalle in sorted(condiciones.items()):
            for case_id in detalle["case_ids"]:
                par = (dataset, case_id)
                if par not in vistos:
                    vistos.append(par)
    return vistos


def _metadatos_del_caso(raiz_repo: Path, dataset: str, particion: str,
                        case_id: str) -> dict:
    """Lee el JSON del caso. **No abre `ground_truth/`.**"""
    archivo = (
        raiz_repo / "experiments" / "cases" / dataset / particion
        / f"{case_id}.json"
    )
    return json.loads(archivo.read_text(encoding="utf-8"))


def planificar(
    raiz_repo: Path,
    subconjunto: dict,
    config_version: str,
    arquitecturas: tuple[str, ...] = ARQUITECTURAS_LLM + ("baseline_reglas",),
) -> PlanCampana:
    """Enumera las corridas. No ejecuta ninguna."""
    particion = subconjunto["particion"]
    plan = PlanCampana(
        config_version=config_version,
        particion=particion,
        arquitecturas=tuple(arquitecturas),
    )
    for dataset, case_id in _casos_del_subconjunto(subconjunto):
        for arquitectura in arquitecturas:
            repeticiones = (
                REPETICIONES_BASELINE
                if arquitectura == "baseline_reglas"
                else REPETICIONES.get(particion, 1)
            )
            for repeticion in range(1, repeticiones + 1):
                identidad = IdentidadCorrida(
                    case_id=case_id,
                    dataset=dataset,
                    arquitectura=arquitectura,
                    repeticion=repeticion,
                    config_version=config_version,
                )
                entrada = {
                    "case_id": case_id,
                    "dataset": dataset,
                    "arquitectura": arquitectura,
                    "repeticion": repeticion,
                    "run_id": identidad.run_id,
                }
                if persistencia.ya_existe(identidad, raiz_repo):
                    plan.ya_hechas.append(entrada)
                else:
                    plan.corridas.append(entrada)
    return plan


def _correr_una(
    raiz_repo: Path, identidad: IdentidadCorrida, particion: str,
    metadatos_caso: dict,
) -> dict:
    """Corre una arquitectura sobre un caso y persiste el resultado.

    **Ejecuta el sistema.** Solo se llama desde `ejecutar_campana()` con la
    ejecución habilitada.
    """
    from src.experimentation.adapters.nodex import adaptar
    from src.experimentation.runners import agente_unico, baseline, nodex

    tipo_deteccion = metadatos_caso["tipo_deteccion"]
    dimensiones = tuple(metadatos_caso.get("dimensiones_aplicables") or ())
    modulo = {
        "nodex_multiagente": nodex,
        "agente_unico": agente_unico,
        "baseline_reglas": baseline,
    }[identidad.arquitectura]

    contenido = modulo.cargar_caso(
        raiz_repo, identidad.dataset, particion, identidad.case_id
    )
    iniciado = datetime.now(timezone.utc).isoformat(timespec="seconds")

    if identidad.arquitectura == "baseline_reglas":
        salida, telemetria, diagnostico = baseline.ejecutar(
            contenido, identidad, tipo_deteccion
        )
        estados = baseline.estados_por_dimension(salida, dimensiones)
        salida_dict = salida.to_dict()
        estado_ejecucion = (
            "completa" if salida.classification else "error_contrato"
        )
        crudo = {"diagnostico_baseline": diagnostico}
        telemetria_dict = telemetria.to_dict()
    else:
        if identidad.arquitectura == "nodex_multiagente":
            estado, diagnostico = nodex.ejecutar(contenido, identidad.run_id)
            estado_ejecucion = nodex.estado_de_ejecucion(diagnostico, estado)
        else:
            estado, diagnostico = agente_unico.ejecutar(
                contenido, identidad.run_id
            )
            estado_ejecucion = (
                "error_api" if diagnostico.get("error_llm") else "completa"
            )
        resultado = adaptar(
            estado,
            case_id=identidad.case_id,
            run_id=identidad.run_id,
            tipo_deteccion=tipo_deteccion,
            dimensiones_aplicables=dimensiones,
            arquitectura=identidad.arquitectura,
            raw_output_ref=persistencia.rutas(identidad, raiz_repo).crudo.name,
        )
        salida_dict = resultado.salida.to_dict()
        estados = resultado.estado_por_dimension
        crudo = estado
        # La telemetría fina (tokens, modelo efectivo) la instrumenta la
        # Fase 6 sobre `src/llm.py`. Hasta entonces se registra lo que el
        # runner puede medir, y queda marcada como previa a D-11.
        telemetria_dict = {
            "run_id": identidad.run_id,
            "execution_time": diagnostico.get("execution_time"),
            "replan_count": diagnostico.get("replan_count"),
            "intentos_correccion": diagnostico.get("intentos_correccion"),
            "llm_call_count": diagnostico.get("llamadas_llm"),
            "input_tokens": None,
            "output_tokens": None,
            "total_tokens": None,
            "uso_fallback": False,
            "previa_a_d11": True,
            "nota": (
                "tokens y modelo efectivo pendientes de la instrumentación "
                "de la Fase 6; no se inventan"
            ),
            "diagnostico_runner": diagnostico,
        }

    persistencia.guardar(
        identidad, raiz_repo,
        salida=salida_dict,
        crudo=crudo,
        telemetria=telemetria_dict,
    )
    return {
        "run_id": identidad.run_id,
        # La identidad viaja con el resultado. Antes se la buscaba después
        # recorriendo el plan por `run_id`, que es O(n^2) y se rompe si el
        # plan cambia entre la corrida y la exportación.
        "identidad": identidad.to_dict(),
        "iniciado_utc": iniciado,
        "estado": estado_ejecucion,
        "estados_por_dimension": estados,
        "salida": salida_dict,
        "telemetria": telemetria_dict,
        "diagnostico": diagnostico,
    }


def ejecutar_campana(
    raiz_repo: Path,
    subconjunto_nombre: str,
    config_version: str,
    arquitecturas: tuple[str, ...] = ARQUITECTURAS_LLM + ("baseline_reglas",),
    ejecucion_habilitada: bool = False,
) -> dict:
    """Plan en seco por omisión; corre la campaña solo si se habilita.

    **No abre `ground_truth/` en ningún momento.** La evaluación es otra
    función, para que la referencia no esté cargada en el proceso mientras
    una corrida está en curso.
    """
    subconjunto = cargar_subconjunto(raiz_repo, subconjunto_nombre)
    plan = planificar(raiz_repo, subconjunto, config_version, arquitecturas)

    if not ejecucion_habilitada:
        return {
            "modo": "plan_en_seco",
            "ejecutado": False,
            "aviso": (
                "no se ejecutó nada. Para correr hace falta pasar "
                "ejecucion_habilitada=True de forma explícita"
            ),
            "plan": plan.resumen(),
            "corridas": plan.pendientes,
            "ya_hechas": plan.ya_hechas,
        }

    particion = subconjunto["particion"]
    resultados, fallos = [], []
    for entrada in plan.pendientes:
        identidad = IdentidadCorrida(
            case_id=entrada["case_id"],
            dataset=entrada["dataset"],
            arquitectura=entrada["arquitectura"],
            repeticion=entrada["repeticion"],
            config_version=config_version,
        )
        metadatos = _metadatos_del_caso(
            raiz_repo, identidad.dataset, particion, identidad.case_id
        )
        try:
            resultados.append(
                _correr_una(raiz_repo, identidad, particion, metadatos)
            )
        except Exception as excepcion:  # noqa: BLE001
            # El plan prohíbe ocultar ejecuciones fallidas: el fallo se
            # registra y la campaña sigue con el caso siguiente.
            fallos.append({
                "run_id": identidad.run_id,
                "error": f"{type(excepcion).__name__}: {excepcion}",
            })

    filas = [
        exportacion.fila(
            identidad=r["identidad"],
            estados=r["estados_por_dimension"],
            telemetria=r["telemetria"],
            status=r["estado"],
        )
        for r in resultados
    ]
    return {
        "modo": "ejecutado",
        "ejecutado": True,
        "protocolo_version": PROTOCOLO_VERSION,
        "plan": plan.resumen(),
        "n_resultados": len(resultados),
        "fallos": fallos,
        "integridad": exportacion.resumen_de_integridad(filas),
        "filas": filas,
    }


def imprimir_plan(plan: dict) -> None:
    """Resumen legible del plan en seco."""
    resumen = plan["plan"]
    print(f"config_version : {resumen['config_version']}")
    print(f"particion      : {resumen['particion']}")
    print(f"repeticiones   : {resumen['repeticiones']}")
    print(f"pendientes     : {resumen['corridas_pendientes']}")
    print(f"ya hechas      : {resumen['corridas_ya_hechas']}")
    for arquitectura, cuantas in sorted(resumen["por_arquitectura"].items()):
        llamadas = cuantas * LLAMADAS_POR_CORRIDA.get(arquitectura, 0)
        print(f"  {arquitectura:<20} {cuantas:>4} corridas  "
              f"{llamadas:>5} llamadas (piso)")
    print(f"llamadas LLM piso: {resumen['llamadas_llm_piso']}")
    print(f"  {resumen['nota_llamadas']}")


# --- la mitad que SÍ ve el ground truth ----------------------------------

def _cargar_referencia(raiz_repo: Path, dataset: str, particion: str,
                       case_id: str) -> dict:
    archivo = (
        raiz_repo / "experiments" / "ground_truth" / dataset / particion
        / f"{case_id}.json"
    )
    return json.loads(archivo.read_text(encoding="utf-8"))


def evaluar_campana(
    raiz_repo: Path,
    subconjunto_nombre: str,
    config_version: str,
    arquitecturas: tuple[str, ...] = ARQUITECTURAS_LLM + ("baseline_reglas",),
) -> dict:
    """Evalúa las corridas **ya guardadas** contra el ground truth.

    Es la otra mitad del orquestador, y la única que abre `ground_truth/`.
    No corre ninguna arquitectura: si una corrida no está guardada, se
    cuenta como ausente en vez de ejecutarse. Así la evaluación es
    reproducible y no depende de cuándo se la invoque.

    Para cada caso combina **dos** estados por dimensión y se queda con el
    más restrictivo: el de la salida (¿el sistema produjo algo que puntuar?)
    y el de la referencia (¿hay una referencia aprobada?). Una dimensión se
    puntúa solo si las dos dicen `evaluable`.
    """
    from src.experimentation.adapters.nodex import dimension_final
    from src.experimentation.evaluators import deteccion as eval_deteccion
    from src.experimentation.evaluators.mitre import comparar_caso as comparar_mitre
    from src.experimentation.evaluators.reconstruccion import (
        comparar_caso as comparar_reconstruccion,
    )

    subconjunto = cargar_subconjunto(raiz_repo, subconjunto_nombre)
    particion = subconjunto["particion"]

    por_arquitectura: dict = {}
    ausentes: list = []

    for arquitectura in arquitecturas:
        pares: list = []
        estados_d1: list[str] = []
        comparaciones_d2: list = []
        estados_d2: list[str] = []
        comparaciones_d3: dict[str, list] = {"tactica": [], "tecnica": []}
        estados_d3: list[str] = []
        detalle: list = []

        for dataset, case_id in _casos_del_subconjunto(subconjunto):
            repeticiones = (
                REPETICIONES_BASELINE
                if arquitectura == "baseline_reglas"
                else REPETICIONES.get(particion, 1)
            )
            for repeticion in range(1, repeticiones + 1):
                identidad = IdentidadCorrida(
                    case_id=case_id, dataset=dataset,
                    arquitectura=arquitectura, repeticion=repeticion,
                    config_version=config_version,
                )
                ruta = persistencia.rutas(identidad, raiz_repo).salida
                if not ruta.is_file():
                    ausentes.append(identidad.run_id)
                    continue
                guardado = persistencia.leer_salida(ruta)
                salida = guardado["salida"]
                referencia = _cargar_referencia(
                    raiz_repo, dataset, particion, case_id
                )
                estados_salida = guardado.get("estados_por_dimension") or {}

                # --- D1 deteccion ---
                estado = dimension_final(
                    estados_salida.get("deteccion", "no_evaluable"),
                    referencia["estado_dimension"].get("deteccion", "no_aplica"),
                )
                estados_d1.append(estado)
                if estado == "evaluable" and salida.get("classification"):
                    pares.append(eval_deteccion.ParDeteccion(
                        case_id=case_id,
                        prediccion=salida["classification"],
                        referencia=referencia["etiqueta_deteccion"],
                    ))

                # --- D2 reconstruccion ---
                estado_d2 = dimension_final(
                    estados_salida.get("reconstruccion", "no_evaluable"),
                    referencia["estado_dimension"].get("reconstruccion",
                                                       "no_aplica"),
                )
                estados_d2.append(estado_d2)
                if estado_d2 == "evaluable":
                    comparacion, _ = comparar_reconstruccion(
                        case_id,
                        [e.get("uid")
                         for e in salida.get("reconstructed_events") or []],
                        tuple(referencia.get("core_event_uids") or ()),
                    )
                    comparaciones_d2.append(comparacion)

                # --- D3 MITRE, un nivel a la vez ---
                estado_d3 = dimension_final(
                    estados_salida.get("mitre", "no_evaluable"),
                    referencia["estado_dimension"].get("mitre", "no_aplica"),
                )
                estados_d3.append(estado_d3)
                if estado_d3 == "evaluable":
                    mitre = salida.get("mitre") or {}
                    atribuciones = [
                        dict(item, nivel="tactica")
                        for item in (mitre.get("tactics") or [])
                    ] + [
                        dict(item, nivel="tecnica")
                        for item in (mitre.get("techniques") or [])
                    ]
                    for nivel in ("tactica", "tecnica"):
                        por_nivel = referencia.get("estado_mitre_por_nivel") or {}
                        if por_nivel.get(nivel) != "evaluable":
                            continue
                        comparacion, _ = comparar_mitre(
                            case_id, atribuciones,
                            referencia.get("referencias_mitre") or [], nivel,
                        )
                        comparaciones_d3[nivel].append(comparacion)

                detalle.append({
                    "run_id": identidad.run_id,
                    "dataset": dataset,
                    "estados": {
                        "deteccion": estado,
                        "reconstruccion": estado_d2,
                        "mitre": estado_d3,
                    },
                })

        conteos, metricas = eval_deteccion.evaluar(pares)
        por_arquitectura[arquitectura] = {
            "deteccion": {
                "conteos": conteos.to_dict(),
                "metricas": metricas,
                "estados": estados_d1,
            },
            "reconstruccion": {
                "n_comparaciones": len(comparaciones_d2),
                "estados": estados_d2,
            },
            "mitre": {
                "comparaciones_por_nivel": {
                    nivel: len(v) for nivel, v in comparaciones_d3.items()
                },
                "estados": estados_d3,
            },
            "detalle": detalle,
        }

    return {
        "protocolo_version": PROTOCOLO_VERSION,
        "config_version": config_version,
        "subconjunto": subconjunto_nombre,
        "particion": particion,
        "corridas_ausentes": ausentes,
        "nota_ausentes": (
            "una corrida ausente se cuenta, no se ejecuta: la evaluación no "
            "debe depender de cuándo se la invoque"
        ),
        "por_arquitectura": por_arquitectura,
    }
