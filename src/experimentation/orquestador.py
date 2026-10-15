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

Este módulo corre arquitecturas y **no contiene ninguna ruta al ground
truth**. La corrección de las corridas guardadas vive en
`src/experimentation/evaluacion.py`, el único módulo que abre
`experiments/ground_truth/`:

    orquestador.py   -> corre arquitecturas y guarda lo que produjeron.
    evaluacion.py    -> lee lo guardado + la referencia y corrige.

Mientras una corrida está en curso, la referencia no está cargada en
ninguna variable del proceso, así que no puede filtrarse a un prompt por
descuido. Antes las dos mitades convivían acá, en funciones distintas; ahora
están en archivos distintos y la ausencia de la ruta se verifica por AST.

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
from src.experimentation.runtime.telemetria import campos_de_modelo

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
#: REFERENCIA de partida, **NO un piso**. NODEX tiene 5 nodos LLM (planificador,
#: triage, selector de herramientas, ingeniero de mitigación, auditor final) y el
#: nodo de triage tiene dos puntos de llamada, de ahí el 6. Pero lo MEDIDO en la
#: comparación de modelos del 15-oct-2026 fue 5, 6, 12 y 13 llamadas: puede ser
#: menos (5) y sube con los bucles de replanificación y de corrección de comandos,
#: que no se pueden acotar sin medir. Ver `LLAMADAS_MEDIDAS`.
LLAMADAS_POR_CORRIDA = {
    "nodex_multiagente": 6,
    # Pseudo-ablacion: un solo prompt, sin reintentos ni fallback.
    "gemini_externo": 1,
    "baseline_reglas": 0,
}


#: Lo medido (llamadas por corrida) en la comparación de modelos del 15-oct-2026,
#: con ambos modelos y dos casos por modelo. Son 4 corridas de NODEX: es un rango
#: observado, no un intervalo.
LLAMADAS_MEDIDAS = {
    "nodex_multiagente": (5, 6, 12, 13),
    "gemini_externo": (1, 1, 1, 1),
    "baseline_reglas": (0,),
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
        referencia = 0
        for corrida in self.corridas:
            arquitectura = corrida["arquitectura"]
            por_arquitectura[arquitectura] = por_arquitectura.get(arquitectura, 0) + 1
            referencia += LLAMADAS_POR_CORRIDA.get(arquitectura, 0)
        return {
            "config_version": self.config_version,
            "particion": self.particion,
            "arquitecturas": list(self.arquitecturas),
            "corridas_pendientes": len(self.corridas),
            "corridas_ya_hechas": len(self.ya_hechas),
            "por_arquitectura": por_arquitectura,
            "llamadas_llm_referencia": referencia,
            "rango_medido_de_llamadas_por_corrida": {
                a: [min(v), max(v)] for a, v in LLAMADAS_MEDIDAS.items()
                if a in por_arquitectura},
            "nota_llamadas": (
                "referencia de partida, NO un piso: se midieron 5, 6, 12 y 13 "
                "llamadas por corrida de NODEX (puede ser menos de 6 y sube con los "
                "bucles de replanificación y corrección)"
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
            # Misma clasificación que NODEX: la misma causa no puede contarse
            # en categorías distintas según la arquitectura.
            estado_ejecucion = (
                nodex.clasificar_error(diagnostico["error"])
                if diagnostico.get("error") else "completa"
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
        # Una corrida que "terminó" sin ningún veredicto booleano no es
        # completa: no hay nada que puntuar en D1.
        if estado_ejecucion == "completa" and resultado.salida.classification is None:
            estado_ejecucion = "error_contrato"
        crudo = estado
        # `resumen_telemetria` ya trae llm_call_count, tokens,
        # execution_time, replan_count, intentos_correccion (acumulado a
        # través de `historial_planes`, no solo el del estado final),
        # invalid_evidence_uid_count y d11_warning_count. No se recalcula
        # ninguno: el orquestador solo agrega lo que mide él mismo.
        telemetria_dict = dict(
            medido,
            # Versión devuelta por la API y tokens de razonamiento, a partir
            # de `llm_calls` (instrumentación de src/llm.py).
            **campos_de_modelo(medido),
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
        # Cómo terminó y qué dimensiones se pueden puntuar. Sin esto el
        # evaluador no tiene de dónde leerlo y da todo por no evaluable.
        ejecucion={
            "estado": estado_ejecucion,
            "estados_por_dimension": estados,
            "iniciado_utc": iniciado,
        },
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

    return ejecutar_plan(raiz_repo, subconjunto, plan, config_version)


def ejecutar_plan(
    raiz_repo: Path,
    subconjunto: dict,
    plan: PlanCampana,
    config_version: str,
) -> dict:
    """Corre las corridas pendientes de un plan. **Ejecuta el sistema.**

    Existe aparte de `ejecutar_campana` para poder probar el bucle completo
    —persistencia, registro de fallos, exportación— con corredores simulados,
    sin pasar por el interruptor `ejecucion_habilitada`. Quien quiera correr
    de verdad una campaña sigue entrando por `ejecutar_campana`, que es la
    que exige habilitarlo de forma explícita.
    """
    # Antes de la primera corrida: sin esto, una salida redirigida aborta
    # con UnicodeEncodeError al imprimir el progreso de NODEX.
    salida_utf8 = asegurar_salida_utf8()

    from src.experimentation.runners import nodex

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
            descripcion = f"{type(excepcion).__name__}: {excepcion}"
            fallos.append({"run_id": identidad.run_id, "error": descripcion})
            # Además del valor de retorno (que se pierde al terminar el
            # proceso), el fallo queda en disco: si no, el consolidador no
            # tendría forma de mostrarlo.
            try:
                persistencia.guardar_fallo(
                    identidad, raiz_repo,
                    estado=nodex.clasificar_error(descripcion),
                    error=descripcion,
                )
            except Exception as error_al_registrar:  # noqa: BLE001
                fallos[-1]["no_se_pudo_registrar"] = str(error_al_registrar)

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
        rango = resumen["rango_medido_de_llamadas_por_corrida"].get(arquitectura)
        medido = f"  (medido {rango[0]}-{rango[1]} por corrida)" if rango else ""
        print(f"  {arquitectura:<20} {cuantas:>4} corridas  "
              f"{llamadas:>5} llamadas de referencia{medido}")
    print(f"llamadas LLM de referencia (NO un piso): {resumen['llamadas_llm_referencia']}")
    print(f"  {resumen['nota_llamadas']}")
