"""Runner experimental del agente único integrado (`src/single_agent.py`).

Sigue la forma de `src/experimentation/runners/nodex.py` sin modificar ningún
archivo de `src/`:

- `cargar_caso`: la MISMA lectura de archivo que NODEX (`nodex.cargar_caso`).
- `recuperar_candidatos`: candidatos MITRE ATT&CK con la MISMA función y el
  MISMO texto de consulta que la herramienta RAG de NODEX
  (`ltm.retrieve_attack_techniques(describir_lote_en_prosa(resumen_logs))`).
  A diferencia de NODEX, donde el selector decide si consultar, aquí la
  recuperación se hace SIEMPRE, una vez por caso, fuera de la llamada al modelo.
- `ejecutar`: `analizar_lote_agente_unico(contenido, thread_id, tecnicas_mitre)`.
- `estado_de_ejecucion`: la MISMA regla que NODEX (`nodex.estado_de_ejecucion`):
  un error de excepción se clasifica con `nodex.clasificar_error`; sin error,
  la corrida es «completa» si trae al menos un veredicto booleano. Un resultado
  incompleto del contrato (D1/D4 o confianza) se conserva aparte.
- `correr_una_agente_unico`: réplica de la rama LLM de
  `orquestador._correr_una` (misma `adaptar`, `persistencia.guardar` y forma de
  la telemetría) que despacha al agente único. El lanzador la instala con
  `unittest.mock.patch` solo dentro del proceso hijo.

No lee ground truth. No calcula métricas. Las envolturas que instala sobre
`llm_json` y `_preparar_estado_inicial` solo observan: llaman a la función
original con los mismos argumentos y devuelven el mismo objeto.
"""
from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path

ARQUITECTURA = "agente_unico"

#: Mensajes fijos con que `src/single_agent.py` marca un resultado incompleto del
#: contrato (no son excepciones). Cualquier otro `_error_api` viene de una excepción.
CONTRATO_INCOMPLETO = (
    "El agente único no produjo un resultado D1/D4 completo.",
    "El agente único no produjo una confianza válida.",
)

#: Encabezado con que `contexto_d11` introduce los candidatos en el prompt.
ENCABEZADO_CANDIDATOS = "CANDIDATOS MITRE RECUPERADOS POR RAG (no atribuidos):\n"

CLAVES_ESPERADAS = ("hay_anomalia", "hay_incidente", "confianza", "diagnostico",
                    "evaluacion_auditor", "comandos_mitigacion")


def _sha_texto(texto: str) -> str:
    return hashlib.sha256((texto or "").encode("utf-8")).hexdigest()


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def thread_id_de(run_id: str) -> str:
    return f"exp__{run_id}"


def cargar_caso(raiz_repo: Path, dataset: str, particion: str, case_id: str) -> str:
    """Misma lectura que NODEX. No lee el ground truth."""
    from src.experimentation.runners import nodex
    return nodex.cargar_caso(raiz_repo, dataset, particion, case_id)


def _memoria(ltm=None):
    """La instancia compartida de la herramienta RAG de NODEX (sobre `CHROMA_PATH`)."""
    if ltm is not None:
        return ltm, 0.0
    comienzo = time.perf_counter()
    from src.tools.tool_consultar_rag import ltm as compartida
    return compartida, time.perf_counter() - comienzo


def recuperar_candidatos(contenido: str, ltm=None) -> dict:
    """Candidatos MITRE con la misma función y el mismo texto de consulta que NODEX."""
    from src.tools.aggregation import describir_lote_en_prosa, preprocesar_lote

    memoria, carga = _memoria(ltm)
    t0 = time.perf_counter()
    _resultado, _v2, resumen = preprocesar_lote(contenido)
    consulta = describir_lote_en_prosa(resumen or {})
    t1 = time.perf_counter()
    candidatos = memoria.retrieve_attack_techniques(consulta)
    t2 = time.perf_counter()
    return {
        "candidatos": list(candidatos or []),
        "consulta": consulta,
        "consulta_sha256": _sha_texto(consulta),
        "segundos_carga_memoria": round(carga, 6),
        "segundos_preprocesamiento_consulta": round(t1 - t0, 6),
        "segundos_recuperacion_mitre": round(t2 - t1, 6),
    }


def resumen_candidatos(candidatos: list) -> list[dict]:
    return [{"technique_id": (c.get("meta") or {}).get("technique_id"),
             "name": (c.get("meta") or {}).get("name"),
             "similitud": c.get("similitud")} for c in candidatos or []]


def ejecutar(contenido: str, run_id: str, candidatos: list) -> tuple[dict, dict]:
    """Corre el agente único. **Hace una llamada al modelo** (más el reintento por JSON inválido)."""
    from src.single_agent import analizar_lote_agente_unico

    comenzado = time.monotonic()
    error = None
    estado: dict = {}
    try:
        estado = analizar_lote_agente_unico(contenido, thread_id=thread_id_de(run_id),
                                            tecnicas_mitre=candidatos)
    except Exception as excepcion:  # noqa: BLE001 - se registra, no se oculta
        error = f"{type(excepcion).__name__}: {excepcion}"
    transcurrido = time.monotonic() - comenzado
    error_agente = estado.get("_error_api")
    incompleto = error_agente if error_agente in CONTRATO_INCOMPLETO else None
    if error is None and error_agente and not incompleto:
        # El agente único captura las excepciones (API, contrato) en `_error_api`;
        # NODEX las deja subir. Se tratan como el error de excepción de NODEX.
        error = error_agente
    diagnostico = {
        "arquitectura": ARQUITECTURA,
        "thread_id": thread_id_de(run_id),
        "execution_time": transcurrido,
        "error": error,
        "error_api_del_agente": error_agente,
        "resultado_incompleto": incompleto,
        "claves_ausentes_en_el_estado": sorted(c for c in CLAVES_ESPERADAS if c not in estado),
        "replan_count": None,
        "intentos_correccion": None,
        "d11_presente_en_el_estado": all(c in estado for c in ("eventos_reconstruidos",
                                                               "tecnicas_atribuidas")),
        "n_candidatos_mitre": len(candidatos or []),
    }
    return estado, diagnostico


def estado_de_ejecucion(diagnostico: dict, estado: dict) -> str:
    """Misma regla que NODEX: «completa» si trae un veredicto booleano y no hubo excepción."""
    from src.experimentation.runners import nodex
    return nodex.estado_de_ejecucion(diagnostico, estado)


class Observacion:
    """Envolturas de solo observación sobre el módulo `src.single_agent`.

    - `llm_json`: la misma cuenta de JSON válido que NODEX (`_instrumentar_llm_json`)
      y una copia del prompt y del system enviados.
    - `_preparar_estado_inicial`: el texto de consulta que se obtiene del resumen
      interno del agente, para comprobar que es el mismo que se usó al recuperar.
    """

    def __init__(self):
        self.prompts: list[dict] = []
        self.consultas_internas: list[str] = []
        self.cuenta = None
        self._restaurar = []

    def instalar(self):
        import src.single_agent as single
        from src.experimentation.comparacion_modelos import _instrumentar_llm_json
        from src.tools.aggregation import describir_lote_en_prosa

        original_llm, original_preparar = single.llm_json, single._preparar_estado_inicial
        self._restaurar = [(single, "llm_json", original_llm),
                           (single, "_preparar_estado_inicial", original_preparar)]
        self.cuenta = _instrumentar_llm_json(single)      # reemplaza single.llm_json
        contado = single.llm_json

        def llm_observado(prompt, system=None, *args, **kwargs):
            self.prompts.append({"prompt": prompt, "system": system})
            return contado(prompt, system, *args, **kwargs)

        def preparar_observado(*args, **kwargs):
            resultado = original_preparar(*args, **kwargs)
            self.consultas_internas.append(
                describir_lote_en_prosa(resultado[0].get("resumen_logs") or {}))
            return resultado

        single.llm_json = llm_observado
        single._preparar_estado_inicial = preparar_observado
        return self

    def desinstalar(self):
        for modulo, nombre, original in reversed(self._restaurar):
            setattr(modulo, nombre, original)
        self._restaurar = []


def candidatos_en_prompt(prompt: str, candidatos: list) -> dict:
    """¿Llegaron los candidatos, completos, al bloque de candidatos del prompt?"""
    bloque = prompt.split(ENCABEZADO_CANDIDATOS, 1)[1] if ENCABEZADO_CANDIDATOS in (prompt or "") else ""
    completo = json.dumps(list(candidatos or []), ensure_ascii=False)
    return {
        "bloque_presente": bool(bloque),
        "lista_completa_en_bloque": bool(bloque) and bloque.startswith(completo),
        "ids_en_bloque": {r["technique_id"]: (r["technique_id"] or "") in bloque
                          for r in resumen_candidatos(candidatos)},
    }


def _escribir_nuevo(ruta: Path, valor) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with ruta.open("x", encoding="utf-8", newline="\n") as f:
        json.dump(valor, f, indent=2, ensure_ascii=False, default=str)
        f.write("\n")


def correr_una_agente_unico(raiz_repo: Path, identidad, particion: str, metadatos_caso: dict,
                            carpeta_observacion: Path | None = None, ltm=None) -> dict:
    """Réplica de la rama LLM de `orquestador._correr_una`, despachando al agente único."""
    from src.experimentation.adapters.nodex import adaptar
    from src.experimentation.runtime import persistencia
    from src.experimentation.runtime.configuracion import detectar_d11
    from src.experimentation.runtime.telemetria import campos_de_modelo

    if identidad.arquitectura != ARQUITECTURA:
        raise ValueError(f"este runner solo corre {ARQUITECTURA}, no {identidad.arquitectura}")
    tipo_deteccion = metadatos_caso["tipo_deteccion"]
    dimensiones = tuple(metadatos_caso.get("dimensiones_aplicables") or ())
    contenido = cargar_caso(raiz_repo, identidad.dataset, particion, identidad.case_id)
    iniciado = datetime.now(timezone.utc).isoformat(timespec="seconds")

    recuperacion = recuperar_candidatos(contenido, ltm)
    candidatos = recuperacion["candidatos"]
    observacion = Observacion().instalar()
    try:
        estado, diagnostico = ejecutar(contenido, identidad.run_id, candidatos)
    finally:
        observacion.desinstalar()
        try:
            persistencia.guardar_llm_json(identidad, raiz_repo, observacion.cuenta["llamadas"],
                                          observacion.cuenta["invalidas"])
        except FileExistsError:
            pass
    estado_ejecucion = estado_de_ejecucion(diagnostico, estado)

    medido = dict(estado.get("telemetry") or {})
    resultado = adaptar(
        estado, case_id=identidad.case_id, run_id=identidad.run_id,
        tipo_deteccion=tipo_deteccion, dimensiones_aplicables=dimensiones,
        arquitectura=ARQUITECTURA,
        raw_output_ref=persistencia.rutas(identidad, raiz_repo).crudo.name)
    salida_dict = resultado.salida.to_dict()
    estados = resultado.estado_por_dimension
    if estado_ejecucion == "completa" and resultado.salida.classification is None:
        estado_ejecucion = "error_contrato"
    telemetria_dict = dict(
        medido,
        **campos_de_modelo(medido),
        tiempo_total_runner_s=diagnostico.get("execution_time"),
        previa_a_d11=not detectar_d11(raiz_repo).get("integrado", False),
        output_contract_version=estado.get("output_contract_version"),
        diagnostico_runner=diagnostico,
        # Fuera de la llamada al modelo y fuera de `execution_time`.
        segundos_recuperacion_mitre=recuperacion["segundos_recuperacion_mitre"],
        segundos_preprocesamiento_consulta_mitre=recuperacion["segundos_preprocesamiento_consulta"],
        segundos_carga_memoria_rag=recuperacion["segundos_carga_memoria"],
        n_candidatos_mitre=len(candidatos),
    )
    persistencia.guardar(
        identidad, raiz_repo, salida=salida_dict, crudo=estado, telemetria=telemetria_dict,
        ejecucion={"estado": estado_ejecucion, "estados_por_dimension": estados,
                   "iniciado_utc": iniciado,
                   # Regla de NODEX aplicada; el resultado incompleto queda declarado.
                   "resultado_incompleto": diagnostico.get("resultado_incompleto")})

    if carpeta_observacion is not None:
        prompt = observacion.prompts[0]["prompt"] if observacion.prompts else ""
        _escribir_nuevo(Path(carpeta_observacion) / f"{identidad.run_id}.mitre_retrieval.json", {
            **identidad.to_dict(), "registrado_utc": _utc(),
            "consulta": recuperacion["consulta"], "consulta_sha256": recuperacion["consulta_sha256"],
            "consulta_interna_igual": [c == recuperacion["consulta"] for c in observacion.consultas_internas],
            "candidatos": resumen_candidatos(candidatos), "n_candidatos": len(candidatos),
            "candidatos_completos": candidatos,
            "llegada_al_prompt": [candidatos_en_prompt(p["prompt"], candidatos) for p in observacion.prompts],
            "segundos_recuperacion_mitre": recuperacion["segundos_recuperacion_mitre"],
            "segundos_preprocesamiento_consulta": recuperacion["segundos_preprocesamiento_consulta"],
            "segundos_carga_memoria": recuperacion["segundos_carga_memoria"],
            "llm_json": observacion.cuenta, "solicitudes_llm_json": len(observacion.prompts),
            "prompt_chars": len(prompt), "prompt_sha256": _sha_texto(prompt),
        })
        _escribir_nuevo(Path(carpeta_observacion) / f"{identidad.run_id}.llm_input.json", {
            **identidad.to_dict(),
            "nota": "Texto exacto entregado a llm_json (system y prompt). El primer elemento es la "
                    "solicitud original; llm_json agrega el aviso de corrección solo si reintenta.",
            "solicitudes": observacion.prompts})

    return {"run_id": identidad.run_id, "identidad": identidad.to_dict(), "iniciado_utc": iniciado,
            "estado": estado_ejecucion, "estados_por_dimension": estados, "salida": salida_dict,
            "telemetria": telemetria_dict, "diagnostico": diagnostico}
