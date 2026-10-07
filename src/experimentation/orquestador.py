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
#:
#: `gemini_externo` es la pseudo-ablacion y se maneja como **procedimiento
#: experimental separado** (decision del 7-oct-2026, §4 y §5): no es
#: obligatorio que la campana automatizada lo corra.
ARQUITECTURAS_LLM = ("nodex_multiagente",)

#: Arquitecturas por omision de la campana automatizada: NODEX y el baseline
#: determinista. Antes incluia el agente unico integrado como requisito de
#: toda corrida, lo que duplicaba el costo sin que la decision lo pidiera.
ARQUITECTURAS_CAMPANA = ("nodex_multiagente", "baseline_reglas")

#: Llamadas al modelo por corrida, para estimar el costo del plan en seco.
#:
#: NODEX tiene 5 nodos LLM (planificador, triage, selector de herramientas,
#: ingeniero de mitigación, auditor final) y el nodo de triage tiene dos
#: puntos de llamada, así que el piso son 6. Sube con los bucles de
#: replanificación y de corrección de comandos, que no se pueden acotar sin
#: medir. Es un **piso**, no una estimación.
LLAMADAS_POR_CORRIDA = {
    "nodex_multiagente": 6,
    # Pseudo-ablacion: un solo prompt, sin reintentos ni fallback.
    "gemini_externo": 1,
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


def asegurar_salida_utf8() -> dict:
    """Fuerza UTF-8 en stdout/stderr antes de correr. **Riesgo real medido.**

    NODEX imprime progreso con caracteres no ASCII (`→`, `⚠️`, `✓`): 56
    líneas de `src/` no se pueden codificar en cp1252. Y en Windows, cuando
    la salida se **redirige** a un archivo o a otro proceso,
    `sys.stdout.encoding` es cp1252, no UTF-8.

    Consecuencia: una corrida con la salida redirigida muere con
    `UnicodeEncodeError` al imprimir, no por un problema del modelo. El caso
    más incómodo es `src/llm.py:248`, el aviso del fallback de modelo: el
    camino que más interesa observar es justo uno de los que crashean.

    Se arregla **acá y no en NODEX**: reconfigurar la salida del proceso que
    orquesta no cambia ninguna lógica del sistema evaluado. El defecto de
    producción queda reportado aparte.
    """
    import sys

    antes = {}
    for nombre in ("stdout", "stderr"):
        flujo = getattr(sys, nombre, None)
        antes[nombre] = getattr(flujo, "encoding", None)
        reconfigurar = getattr(flujo, "reconfigure", None)
        if reconfigurar is not None:
            try:
                # `errors="replace"` como red de seguridad: si algún flujo no
                # admite UTF-8, un carácter se vuelve "?" en vez de abortar
                # una corrida de miles de llamadas.
                reconfigurar(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass
    return {
        "encoding_antes": antes,
        "encoding_despues": {
            nombre: getattr(getattr(sys, nombre, None), "encoding", None)
            for nombre in ("stdout", "stderr")
        },
        "motivo": (
            "56 líneas de src/ no son codificables en cp1252 y en Windows "
            "stdout es cp1252 cuando se redirige la salida"
        ),
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
    arquitecturas: tuple[str, ...] = ARQUITECTURAS_CAMPANA,
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
    from src.experimentation.runners import baseline, gemini_externo, nodex

    tipo_deteccion = metadatos_caso["tipo_deteccion"]
    dimensiones = tuple(metadatos_caso.get("dimensiones_aplicables") or ())
    modulo = {
        "nodex_multiagente": nodex,
        "gemini_externo": gemini_externo,
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
        from src.experimentation.runtime.configuracion import detectar_d11

        if identidad.arquitectura == "nodex_multiagente":
            estado, diagnostico = nodex.ejecutar(contenido, identidad.run_id)
            estado_ejecucion = nodex.estado_de_ejecucion(diagnostico, estado)
        else:
            estado, diagnostico = gemini_externo.ejecutar(
                contenido, identidad.run_id
            )
            estado_ejecucion = (
                "error_api" if diagnostico.get("error") else "completa"
            )
        # La telemetría la produce el propio sistema: `analizar_lote()`
        # envuelve el grafo en `medir_ejecucion()` y deja el resumen en
        # `estado["telemetry"]` (src/telemetry.py). El orquestador no la
        # recalcula: duplicarla daría dos números para lo mismo.
        medido = dict(estado.get("telemetry") or diagnostico.get("telemetry") or {})
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
        # `resumen_telemetria` ya trae llm_call_count, tokens,
        # execution_time, replan_count, intentos_correccion (acumulado a
        # través de `historial_planes`, no solo el del estado final),
        # invalid_evidence_uid_count y d11_warning_count. No se recalcula
        # ninguno: el orquestador solo agrega lo que mide él mismo.
        telemetria_dict = dict(
            medido,
            # Tiempo de pared del runner, que incluye la lectura del caso y
            # la adaptación. Distinto del `execution_time` del grafo, así que
            # lleva otro nombre en vez de sobreescribirlo.
            tiempo_total_runner_s=diagnostico.get("execution_time"),
            # §11 del plan: no mezclar telemetría previa a D-11 con la
            # posterior. El valor se mide, no se asume.
            previa_a_d11=not detectar_d11(raiz_repo).get("integrado", False),
            output_contract_version=estado.get("output_contract_version"),
            diagnostico_runner=diagnostico,
        )

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
    arquitecturas: tuple[str, ...] = ARQUITECTURAS_CAMPANA,
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

    # Antes de la primera corrida: sin esto, una salida redirigida aborta
    # con UnicodeEncodeError al imprimir el progreso de NODEX.
    salida_utf8 = asegurar_salida_utf8()

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
        "salida_utf8": salida_utf8,
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
    arquitecturas: tuple[str, ...] = ARQUITECTURAS_CAMPANA,
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
        # Solo `tecnica`: ver el comentario del bloque D3 mas abajo.
        comparaciones_d3: dict[str, list] = {"tecnica": []}
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
                    # El matching va por `evidence_uids`, NO por el `uid`
                    # del evento. En el contrato d11-v1, `event_id` es la
                    # etiqueta que el sistema le pone al evento y
                    # `normalizar_d11` la reemplaza por una sintetica si
                    # colisiona con un uid; los `evidence_uids` son los que
                    # se validan contra el catalogo de evidencia, indexado
                    # por el uid real del registro. Comparar `event_id`
                    # contra `core_event_uids` no coincidiria con nada.
                    citados: list[str] = []
                    for evento in salida.get("reconstructed_events") or []:
                        for uid in evento.get("evidence_uids") or []:
                            if uid not in citados:
                                citados.append(str(uid))
                    comparacion, _ = comparar_reconstruccion(
                        case_id,
                        citados,
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
                    # Solo nivel TECNICA. El contrato d11-v1 no lleva nivel y
                    # la decision del 7-oct-2026 fija el scoring de D3 en
                    # `label_technique`; `label_tactic` queda como
                    # informacion complementaria del dataset y no entra.
                    mitre = salida.get("mitre") or {}
                    atribuciones = [
                        dict(item, nivel="tecnica")
                        for item in (mitre.get("techniques") or [])
                    ]
                    por_nivel = referencia.get("estado_mitre_por_nivel") or {}
                    if por_nivel.get("tecnica") == "evaluable":
                        comparacion, _ = comparar_mitre(
                            case_id, atribuciones,
                            referencia.get("referencias_mitre") or [],
                            "tecnica",
                        )
                        comparaciones_d3["tecnica"].append(comparacion)

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
