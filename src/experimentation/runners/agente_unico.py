"""Agente único: la comparación pareada contra NODEX. §10 del plan.

Un solo agente LLM responsable de todo el análisis. Es el baseline que pide
el formulario de la tesis, y **no** es el baseline de reglas.

## Qué se mantiene idéntico, y por qué

La variable experimental tiene que ser **la arquitectura**, no la entrada ni
los recursos. Si el agente único recibiera menos contexto, la comparación
mediría el contexto. Por eso comparte con NODEX, bit a bit:

| Elemento | Cómo se garantiza |
|---|---|
| El caso | El mismo archivo de `experiments/cases/`, leído igual |
| El preprocesamiento | La misma `preprocesar_lote()`, una sola pasada |
| El resumen que ve el modelo | El mismo `acotar_resumen_para_prompt()` |
| El contexto de interpretación | El mismo `contexto_preprocesamiento()` |
| El conocimiento externo | El mismo `tool_consultar_rag()`, con los mismos `TOP_K_*` |
| Modelo y temperatura | El mismo `llm_json()`, que lee `src/config.py` |
| El contrato de salida | Las mismas claves de estado que produce NODEX |

Lo que cambia es **solo** la arquitectura: NODEX orquesta cinco agentes con
routers, planificación, validación de comandos y bucles de corrección; acá
hay una sola llamada que tiene que hacer todo.

## Lo que NO recibe

El ground truth, en ninguna forma. Esta función recibe el contenido del caso
y nada más; no tiene parámetro para la referencia.

## D-11

Cuando la implementación externa de D-11 defina los tres campos
(`eventos_reconstruidos`, `secuencia_temporal`, `tecnicas_atribuidas`), el
agente único **tiene que recibir el mismo contrato de salida**: si NODEX los
produce y el agente único no, D2 y D3 compararían un sistema que responde
contra uno que no puede, y eso no mide arquitectura.

Ese punto está marcado en `INSTRUCCION_SISTEMA` con
`MARCADOR_CONTRATO_D11`. **No se rellena acá**: el texto exacto lo define la
implementación externa, y escribirlo por adelantado sería duplicarla. La
función `contrato_d11_pendiente()` lo detecta y lo reporta.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from src.experimentation.contracts import CONTRATO_VERSION

#: Marcador donde entra el contrato de salida de D-11, cuando exista.
MARCADOR_CONTRATO_D11 = "{{CONTRATO_D11}}"

#: Instrucción del agente único.
#:
#: Pide exactamente lo que NODEX produce hoy en su estado final, con los
#: mismos nombres, para que el **mismo adaptador** sirva para las dos
#: arquitecturas sin ramas especiales. Los campos salen de:
#:
#:   diagnostico          -> agente_analista_triage
#:   hay_anomalia         -> agente_auditor_final
#:   hay_incidente        -> agente_auditor_final
#:   confianza            -> agente_auditor_final
#:   evaluacion_auditor   -> agente_auditor_final (campo `evaluacion`)
#:   comandos_mitigacion  -> agente_ingeniero_mitigacion
#:
#: La distinción entre `hay_anomalia` y `hay_incidente` se conserva porque
#: es la que permite leer la pregunta correcta según el dataset: comparar
#: `hay_incidente` contra etiquetas de anomalía de sistema mide la pregunta
#: equivocada, y en este proyecto ya dio recall 0,0 por esa razón.
INSTRUCCION_SISTEMA = """\
Eres un analista SOC experto. Vas a analizar un lote de logs COMPLETO por tu
cuenta: no hay otros agentes, así que tienes que hacer todo el análisis en
una sola respuesta.

Tu trabajo:
1. Diagnosticar qué ocurrió en el lote.
2. Decidir si hay una ANOMALÍA DE SISTEMA (comportamiento operativo
   anormal: fallos, errores, degradación) y, por separado, si hay un
   INCIDENTE DE SEGURIDAD (actividad maliciosa). Son preguntas distintas:
   un disco que falla es una anomalía sin ser un incidente, y un escaneo
   exitoso es un incidente sin producir fallos.
3. Proponer comandos de mitigación si corresponde.
4. Evaluar críticamente tu propio diagnóstico: qué lo sostiene y qué queda
   sin explicar.

Si alguna técnica de las TÉCNICAS MITRE ATT&CK listadas realmente aplica a
lo que ves, cita su ID dentro del diagnóstico. Si ninguna aplica, o la lista
viene vacía, no inventes IDs. Esa lista son candidatas recuperadas por
similitud, no conclusiones.

Si el lote se interpretó con baja cobertura o trae advertencias de parsing,
tenlo en cuenta: estás diagnosticando sobre un resumen incompleto y la
confianza debe reflejarlo.

Responde SOLO en JSON:
{"diagnostico": "...", "hay_anomalia": true/false,
 "hay_incidente": true/false, "confianza": 0.0-1.0,
 "evaluacion_auditor": "...", "comandos_mitigacion": ["...", "..."]}
""" + MARCADOR_CONTRATO_D11


def contrato_d11_pendiente() -> bool:
    """`True` mientras el marcador de D-11 siga sin rellenar."""
    return MARCADOR_CONTRATO_D11 in INSTRUCCION_SISTEMA


def construir_entrada(contenido: str) -> tuple[dict, dict, str]:
    """Arma la entrada observable, idéntica a la que recibe NODEX.

    Replica `_preparar_estado_inicial()` de `src/pipeline.py` paso por paso.
    Es imprescindible que sea el mismo camino y no uno parecido: cualquier
    diferencia en lo que el modelo ve se confundiría después con una
    diferencia entre arquitecturas.

    El camino real del pipeline es:

        _resultado, v2, resumen = preprocesar_lote(raw)
        metadatos, advertencias, muestras = _metadatos_desde_v2(_resultado, v2)

    y el triage arma su contexto con `contexto_preprocesamiento(metadatos,
    advertencias, muestras, incluir_muestras=True)`. Las **muestras** y ese
    `incluir_muestras=True` importan: sin ellos el agente único vería menos
    que NODEX y la comparación estaría sesgada a favor del multiagente.

    Devuelve `(resumen_acotado, estado_base, contexto_pre)`.

    **Ejecuta el preprocesamiento**, así que solo debe invocarse durante una
    corrida autorizada.
    """
    from src.pipeline import _metadatos_desde_v2
    from src.preprocessing.prompt_context import contexto_preprocesamiento
    from src.tools.aggregation import preprocesar_lote
    from src.tools.resumen_prompt import acotar_resumen_para_prompt

    resultado, v2, resumen = preprocesar_lote(contenido)
    metadatos, advertencias, muestras = _metadatos_desde_v2(resultado, v2)
    resumen_acotado = acotar_resumen_para_prompt(resumen)
    contexto_pre = contexto_preprocesamiento(
        metadatos, advertencias, muestras, incluir_muestras=True
    )
    estado_base = {
        "resumen_logs": resumen,
        "preprocessing_metadata": metadatos,
        "parsing_warnings": advertencias,
        "raw_samples": muestras,
    }
    return resumen_acotado, estado_base, contexto_pre


def _texto_rag(contexto_rag: list, tecnicas_mitre: list) -> tuple[str, str]:
    contexto_txt = (
        json.dumps(contexto_rag, ensure_ascii=False)
        if contexto_rag
        else "Sin patrones históricos previos (memoria aún vacía)."
    )
    if tecnicas_mitre:
        ids = ", ".join(
            t.get("meta", {}).get("technique_id", "?") for t in tecnicas_mitre
        )
        tecnicas_txt = f"{ids}\n{json.dumps(tecnicas_mitre, ensure_ascii=False)}"
    else:
        tecnicas_txt = "Sin técnicas relacionadas recuperadas."
    return contexto_txt, tecnicas_txt


def ejecutar(contenido: str, run_id: str) -> tuple[dict, dict]:
    """Corre el agente único sobre un caso. Devuelve `(estado, diagnostico)`.

    El `estado` usa las mismas claves que el estado final de NODEX, así que
    el adaptador de `src/experimentation/adapters/nodex.py` lo consume sin
    cambios. Eso es deliberado: dos adaptadores distintos podrían diferir en
    cómo interpretan un veredicto ausente, y esa diferencia se confundiría
    con una diferencia entre arquitecturas.

    **Hace una llamada al modelo.** Solo debe invocarse durante una corrida
    autorizada.
    """
    from src.llm import llm_json
    from src.tools.tool_consultar_rag import tool_consultar_rag

    # `firma_lote` vive en `src.tools.aggregation`, igual que la importa
    # `src/pipeline.py`. El RAG exige `state["firma"]` y lanza KeyError si
    # falta, así que no es opcional.
    from src.tools.aggregation import firma_lote

    comenzado = time.monotonic()
    resumen_acotado, estado_base, contexto_pre = construir_entrada(contenido)

    # Mismo acceso al conocimiento que NODEX: si el agente único no pudiera
    # consultar el RAG, la comparación mediría el acceso al conocimiento y
    # no la arquitectura. La firma se calcula igual que en el pipeline,
    # porque el RAG la usa para recuperar precedentes del mismo lote.
    firma = firma_lote(estado_base["resumen_logs"],
                       estado_base["preprocessing_metadata"])
    estado_para_rag = dict(estado_base, firma=firma)
    try:
        recuperado = tool_consultar_rag(estado_para_rag)
        error_rag = None
    except Exception as excepcion:  # noqa: BLE001 - se registra, no se oculta
        recuperado = {"contexto_rag": [], "tecnicas_mitre": []}
        error_rag = f"{type(excepcion).__name__}: {excepcion}"

    contexto_txt, tecnicas_txt = _texto_rag(
        recuperado.get("contexto_rag") or [],
        recuperado.get("tecnicas_mitre") or [],
    )
    user_content = (
        f"RESUMEN DEL LOTE:\n{json.dumps(resumen_acotado, ensure_ascii=False)}\n\n"
        + (f"{contexto_pre}\n\n" if contexto_pre else "")
        + f"CONTEXTO HISTÓRICO (RAG):\n{contexto_txt}\n\n"
        + f"TÉCNICAS MITRE ATT&CK RELACIONADAS:\n{tecnicas_txt}"
    )

    error_llm = None
    respuesta: dict = {}
    try:
        respuesta = llm_json(user_content, system=INSTRUCCION_SISTEMA)
    except Exception as excepcion:  # noqa: BLE001
        error_llm = f"{type(excepcion).__name__}: {excepcion}"

    transcurrido = time.monotonic() - comenzado

    def _booleano(clave: str):
        """Solo acepta un booleano real.

        Si el modelo devuelve "true", 1 o nada, el campo queda `None` y el
        adaptador marca la detección no evaluable. Convertirlo con `bool()`
        inventaría una predicción, que es el defecto que ya falseó conteos
        en este proyecto.
        """
        valor = respuesta.get(clave)
        return valor if isinstance(valor, bool) else None

    comandos = respuesta.get("comandos_mitigacion")
    estado = {
        "diagnostico": respuesta.get("diagnostico") or "",
        "hay_anomalia": _booleano("hay_anomalia"),
        "hay_incidente": _booleano("hay_incidente"),
        "confianza": (
            respuesta.get("confianza")
            if isinstance(respuesta.get("confianza"), (int, float))
            and not isinstance(respuesta.get("confianza"), bool)
            else None
        ),
        "evaluacion_auditor": respuesta.get("evaluacion_auditor") or "",
        "comandos_mitigacion": comandos if isinstance(comandos, list) else [],
        # Candidatas del RAG, igual que en NODEX: el adaptador las manda a
        # `_meta`, nunca a `mitre`.
        "tecnicas_mitre": recuperado.get("tecnicas_mitre") or [],
        "contexto_rag": recuperado.get("contexto_rag") or [],
        # El estado lleva el resumen COMPLETO y los metadatos, igual que el
        # de NODEX: el adaptador y la auditoría tienen que poder ver lo
        # mismo que vio el modelo.
        **estado_base,
        "firma": firma,
    }

    diagnostico = {
        "arquitectura": "agente_unico",
        "contrato_version": CONTRATO_VERSION,
        "llamadas_llm": 0 if error_llm else 1,
        "execution_time": transcurrido,
        "error_llm": error_llm,
        "error_rag": error_rag,
        "contrato_d11_pendiente": contrato_d11_pendiente(),
        "nota_d11": (
            "el marcador del contrato de D-11 sigue sin rellenar: mientras "
            "siga así, el agente único no produce D2 ni D3, igual que NODEX, "
            "y la comparación en esas dimensiones no es posible para ninguna "
            "de las dos arquitecturas"
            if contrato_d11_pendiente() else None
        ),
        "campos_ausentes_en_la_respuesta": sorted(
            clave for clave in ("diagnostico", "hay_anomalia", "hay_incidente",
                                "confianza", "evaluacion_auditor",
                                "comandos_mitigacion")
            if clave not in respuesta
        ),
    }
    return estado, diagnostico


def cargar_caso(raiz_repo: Path, dataset: str, particion: str, case_id: str) -> str:
    """Lee el contenido de un caso. **No lee su ground truth.**"""
    directorio = raiz_repo / "experiments" / "cases" / dataset / particion
    for extension in ("log", "csv"):
        archivo = directorio / f"{case_id}.{extension}"
        if archivo.is_file():
            return archivo.read_text(encoding="utf-8")
    raise FileNotFoundError(
        f"no se encontró el contenido del caso {case_id} en {directorio}"
    )
