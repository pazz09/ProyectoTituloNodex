"""Comparación mínima entre dos modelos: ¿el sistema funciona con cada uno?

**Esto NO mide acierto.** No calcula precisión, F1 ni calidad del reporte, y no
lee `ground_truth/`. Responde una sola pregunta: con este modelo, ¿la corrida
produce una salida válida y sin accidentes? Es la condición mínima para poder
usarlo como modelo de la campaña.

## Qué se corre

Un caso de BGL y uno de UWF (el primero, por orden alfabético de `case_id`,
del subconjunto de desarrollo `piloto`; el criterio se fijó antes de ejecutar)
× dos modelos × dos arquitecturas con LLM (NODEX y Gemini directo):

    2 casos × 2 modelos × (6 + 1 llamadas mínimas) = 28 llamadas mínimas

## Criterios de validez (fijados antes de ejecutar; sin criterios de acierto)

1. `json_objeto_valido`   la respuesta del modelo es JSON válido y es un objeto.
2. `veredicto_presente`   hay un veredicto booleano.
3. `evidencia_valida`     `invalid_evidence_uid_count` es 0 y todo uid citado
                          existe en el caso.
4. `tokens_registrados`   hay tokens de entrada y de salida registrados.
5. `sin_timeout_ni_error` no hubo timeout ni error de API.
6. `solo_el_modelo_pedido` ninguna llamada usó otro modelo.

## Regla de decisión (fijada antes de ejecutar)

Si `gemini-3.8-flash` cumple los seis criterios en todas sus corridas, será el
modelo principal de la campaña. Si falla alguno, se mantiene
`gemini-3.1-pro-preview` y se documenta el motivo. Esta herramienta solo
aplica la regla y la muestra; **no cambia ninguna configuración.**

## Regla de repetición (fijada antes de la primera llamada)

- Las **fallas de contenido** (JSON inválido, veredicto ausente, uids de
  evidencia inválidos, tokens no registrados, otro modelo) cuentan como fallo y
  **NO se repiten**.
- Las **fallas de infraestructura** (timeout, 503 o 429 que persisten tras los
  reintentos con espera de `src/llm.py`) se repiten **UNA vez**. Se conservan los
  dos intentos. Si el repetido también falla, cuenta como fallo.
- Un error que no es ninguno de los dos (p. ej. un 400) cuenta como fallo y no
  se repite: repetirlo no lo arregla.

## Orden de ejecución

Etapa 1: BGL con el candidato, Gemini directo y luego NODEX. Tras ella se revisa
lo que devolvió la API real (versión devuelta no nula y correspondiente al modelo
pedido; razonamiento informado o `None`, sin inventar). Si algo es inesperado la
herramienta termina con código 3 y NO se sigue. Etapa 2: las seis restantes.

## Garantías de la ejecución

- El respaldo de modelo va **apagado** (`LLM_SIN_RESPALDO=true`) y el modelo
  de respaldo se iguala al principal.
- Cada corrida es un proceso propio, con su modelo en el entorno, para que la
  configuración que ve el sistema sea la real y no un parche en memoria.
- Se bloquean las llamadas HTTP de `requests`: es el cliente que usan AbuseIPDB
  y NVD. La política del proyecto los deja congelados fuera de la campaña.
  Gemini usa otro cliente y no se ve afectado. Los intentos bloqueados se
  cuentan y se informan.
- ChromaDB y la caché de IP son **copias** temporales; las originales no se
  tocan.
- El resultado se escribe en un directorio que debe estar **fuera** de
  `experiments/`: esta comparación no es un resultado reportable.
- Sin `--etapa` solo muestra el plan.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from src.experimentation.knowledge.aislamiento import configuracion_experimental

MODELOS = ("gemini-3.1-pro-preview", "gemini-3.8-flash")
MODELO_CANDIDATO = "gemini-3.8-flash"
MODELO_ACTUAL = "gemini-3.1-pro-preview"
ARQUITECTURAS = ("nodex_multiagente", "gemini_externo")
DATASETS = ("bgl", "uwf")
PARTICION = "desarrollo"
SUBCONJUNTO = "piloto"
TEMPERATURA = "0"

#: Llamadas mínimas por corrida (las mismas del orquestador).
LLAMADAS_MINIMAS = {"nodex_multiagente": 6, "gemini_externo": 1}

CRITERIOS = (
    "json_objeto_valido",
    "veredicto_presente",
    "evidencia_valida",
    "tokens_registrados",
    "sin_timeout_ni_error",
    "solo_el_modelo_pedido",
)

#: Corridas de la etapa 1 (BGL con el candidato: Gemini directo y luego NODEX).
ETAPA_1 = 2

#: Tope de las corridas del Pro sobre UWF (las de comparación), en segundos.
#: Se fijó el 15-oct-2026 DESPUÉS de observar la corrida 4 (NODEX con el Pro en BGL
#: tardó 97 min frente a 34 s de la corrida 2 con el candidato). NO es un criterio
#: de decisión del modelo: esas corridas no entran en la regla. Las corridas del
#: candidato no tienen tope. Antes había un tope de 2400 s para todas, pero NO se
#: cumplía: matar al lanzador del venv deja vivo al proceso hijo y `communicate()`
#: esperaba a que cerrara las tuberías; la corrida 4 superó ese tope sin cortarse.
TOPE_PRO_UWF_S = 7200
FALLO_TOPE = "no_completo_en_el_tiempo_previsto"


def tope_de(corrida: "Corrida") -> int | None:
    """Tope en segundos, o `None` si la corrida no tiene tope."""
    return (TOPE_PRO_UWF_S
            if corrida.modelo == MODELO_ACTUAL and corrida.dataset == "uwf" else None)


@dataclass(frozen=True)
class Corrida:
    modelo: str
    arquitectura: str
    dataset: str
    case_id: str

    @property
    def etiqueta(self) -> str:
        return f"{self.modelo}__{self.arquitectura}__{self.case_id}"


# --- plan -------------------------------------------------------------------------

def elegir_casos(raiz_repo: Path) -> dict[str, str]:
    """Primer `case_id`, por orden alfabético, de cada dataset del subconjunto."""
    ruta = raiz_repo / "experiments" / "subconjuntos" / f"{SUBCONJUNTO}.json"
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    elegidos = {}
    for dataset in DATASETS:
        ids = sorted(
            case_id
            for condicion in datos["datasets"][dataset].values()
            for case_id in condicion["case_ids"]
        )
        if not ids:
            raise ValueError(f"el subconjunto {SUBCONJUNTO!r} no tiene casos de {dataset}")
        elegidos[dataset] = ids[0]
    return elegidos


def planificar(raiz_repo: Path) -> list[Corrida]:
    casos = elegir_casos(raiz_repo)
    # Orden fijado antes de ejecutar: BGL primero, y dentro de cada caso el
    # candidato antes que el Pro, Gemini directo antes que NODEX. Las dos
    # primeras corridas son la etapa 1: tras ellas se revisa lo que devolvió la
    # API real antes de seguir.
    return [
        Corrida(modelo, arquitectura, dataset, casos[dataset])
        for dataset in DATASETS
        for modelo in (MODELO_CANDIDATO, MODELO_ACTUAL)
        for arquitectura in ("gemini_externo", "nodex_multiagente")
    ]


def llamadas_minimas(plan: list[Corrida]) -> int:
    return sum(LLAMADAS_MINIMAS[c.arquitectura] for c in plan)


def entorno_de_la_corrida(base: dict, modelo: str, chroma: Path, cache_ip: Path) -> dict:
    """Entorno del proceso hijo. Fuerza el modelo y apaga el respaldo."""
    entorno = dict(base)
    entorno.update({
        "LLM_MODEL_PRIMARY": modelo,
        "LLM_MODEL_FALLBACK": modelo,      # irrelevante con el respaldo apagado
        "LLM_SIN_RESPALDO": "true",
        "TEMPERATURE": TEMPERATURA,
        "CHROMA_PATH": str(chroma),
        "IP_CACHE_PATH": str(cache_ip),
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "PYTHONIOENCODING": "utf-8",
    })
    return entorno


# --- criterios --------------------------------------------------------------------

def uids_del_caso(raiz_repo: Path, dataset: str, case_id: str) -> frozenset[str] | None:
    """`uid` presentes en el caso (entrada), o `None` si el caso no los tiene."""
    archivo = (raiz_repo / "experiments" / "cases" / dataset / PARTICION
               / f"{case_id}.csv")
    if not archivo.is_file():
        return None
    with archivo.open(encoding="utf-8", newline="") as f:
        lector = csv.DictReader(f)
        if not lector.fieldnames or "uid" not in lector.fieldnames:
            return None
        return frozenset(fila["uid"] for fila in lector if fila.get("uid"))


def evaluar_criterios(resultado: dict, modelo: str,
                      uids_caso: frozenset[str] | None,
                      enmendado: bool = False) -> dict[str, bool]:
    """Aplica los seis criterios a lo que dejó el trabajador. Todos son bool.

    `enmendado=True` aplica la ENMIENDA del criterio 3, hecha el 15-oct-2026
    DESPUÉS del primer resultado (ver docs, sección 20.8): en un dataset sin
    columna `uid` no se juzga la evidencia citada por Gemini directo, y en NODEX
    solo cuenta `invalid_evidence_uid_count`. En un dataset con `uid` (UWF) el
    criterio es el mismo. El veredicto con el criterio ORIGINAL (`enmendado=False`)
    se conserva siempre.
    """
    diag = resultado.get("diagnostico") or {}
    tel = resultado.get("telemetria") or {}
    estado = resultado.get("estado") or {}
    llamadas = tel.get("llm_calls") or []
    sin_error = not diag.get("error") and not resultado.get("excepcion")

    if resultado["arquitectura"] == "nodex_multiagente":
        cuenta = resultado.get("llm_json") or {}
        json_ok = cuenta.get("llamadas", 0) > 0 and cuenta.get("invalidas", 1) == 0
    else:
        json_ok = not diag.get("error")

    citados = set(estado.get("uids_citados") or [])
    invalidos = len(citados - uids_caso) if uids_caso is not None else len(citados)
    reportado = estado.get("invalid_evidence_uid_count")
    # NODEX informa su propio contador; Gemini directo no tiene uno (None).
    contador_ok = reportado == 0 if resultado["arquitectura"] == "nodex_multiagente" \
        else reportado in (None, 0)

    if enmendado and uids_caso is None:
        # Dataset sin columna `uid`: citar uids no tiene referencia contra la cual
        # juzgarse. NODEX: solo su propio contador. Gemini directo: no se juzga.
        evidencia_ok = bool(estado) and (
            contador_ok if resultado["arquitectura"] == "nodex_multiagente" else True)
    else:
        evidencia_ok = bool(estado) and invalidos == 0 and contador_ok

    return {
        "json_objeto_valido": bool(json_ok),
        "veredicto_presente": bool(estado.get("veredicto_presente")),
        "evidencia_valida": evidencia_ok,
        "tokens_registrados": all(
            isinstance(tel.get(c), int) and not isinstance(tel.get(c), bool)
            for c in ("input_tokens", "output_tokens")),
        "sin_timeout_ni_error": bool(sin_error),
        "solo_el_modelo_pedido": bool(llamadas) and all(
            c.get("model") == modelo for c in llamadas),
    }


def _regla_con(filas: list[dict], clave: str) -> dict:
    del_candidato = [f for f in filas if f["modelo"] == MODELO_CANDIDATO]
    fallas = [
        {"corrida": f["etiqueta"], "criterio": c}
        for f in del_candidato for c in CRITERIOS if not f[clave][c]
    ]
    cumple = bool(del_candidato) and not fallas
    return {
        "corridas_evaluadas": len(del_candidato),
        "cumple_todos": cumple,
        "resultado_de_la_regla": MODELO_CANDIDATO if cumple else MODELO_ACTUAL,
        "criterios_fallidos": fallas,
    }


def aplicar_regla(filas: list[dict]) -> dict:
    """Regla de decisión fijada de antemano. No cambia ninguna configuración.

    Se evalúa con el criterio ORIGINAL y con el ENMENDADO (criterio 3). La
    decisión usa el enmendado SOLO si el Pro también incumple el criterio
    original en BGL con Gemini directo (eso demuestra que el criterio original
    no discrimina entre modelos). Si el Pro lo cumple y el candidato no, o si
    esa corrida del Pro todavía no existe, vale la regla original.
    """
    original = _regla_con(filas, "criterios")
    enmendada = _regla_con(filas, "criterios_enmendados")
    pro = next((f for f in filas if f["modelo"] == MODELO_ACTUAL
                and f["arquitectura"] == "gemini_externo" and f["dataset"] == "bgl"), None)
    if pro is None:
        usa_enmendado, motivo = False, "la corrida del Pro en BGL con Gemini directo no se hizo"
    elif not pro.get("tiene_estado"):
        usa_enmendado, motivo = False, ("la corrida del Pro en BGL con Gemini directo no "
                                        "devolvió una respuesta que juzgar")
    elif not pro["criterios"]["evidencia_valida"]:
        usa_enmendado, motivo = True, ("el Pro también incumple el criterio 3 original en "
                                       "BGL con Gemini directo: no discrimina")
    else:
        usa_enmendado, motivo = False, ("el Pro cumple el criterio 3 original en BGL con "
                                        "Gemini directo: el criterio sí discrimina")
    elegida = enmendada if usa_enmendado else original
    return {
        "regla": (f"{MODELO_CANDIDATO} cumple los 6 criterios en todas sus corridas "
                  f"-> modelo principal; si no, se mantiene {MODELO_ACTUAL}"),
        "criterio_usado": "enmendado" if usa_enmendado else "original",
        "motivo_del_criterio_usado": motivo,
        "con_criterio_original": original,
        "con_criterio_enmendado": enmendada,
        **elegida,
    }


# --- trabajador (un proceso por corrida) ------------------------------------------

def _instrumentar_llm_json(modulo_llm) -> dict:
    """Envuelve `llm_json` para contar cuántas veces devolvió JSON inválido.

    Hay que llamarla ANTES de importar los agentes: ellos hacen
    `from src.llm import llm_json` y se quedan con la función que haya en ese
    momento.
    """
    cuenta = {"llamadas": 0, "invalidas": 0}
    original = modulo_llm.llm_json

    def envuelta(*args, **kwargs):
        cuenta["llamadas"] += 1
        respuesta = original(*args, **kwargs)
        if not isinstance(respuesta, dict) or respuesta.get("error") == "json_invalido":
            cuenta["invalidas"] += 1
        return respuesta

    modulo_llm.llm_json = envuelta
    return cuenta


def _bloquear_red(clase_sesion) -> list[str]:
    """Hace fallar toda petición de `requests` y anota a dónde iba."""
    intentos: list[str] = []

    def bloqueada(self, metodo, url, *args, **kwargs):
        intentos.append(str(url).split("?")[0])
        raise ConnectionError("llamada externa bloqueada: no autorizada en esta comparación")

    clase_sesion.request = bloqueada
    return intentos


def _resumen_del_estado(estado: dict) -> dict:
    """Solo lo que necesitan los criterios y los avisos. Sin el texto del reporte."""
    citados: list[str] = []
    for clave in ("eventos_reconstruidos", "tecnicas_atribuidas"):
        for item in estado.get(clave) or []:
            if isinstance(item, dict):
                citados += [str(u) for u in item.get("evidence_uids") or []]
    return {
        "veredicto_presente": any(
            isinstance(estado.get(k), bool) for k in ("hay_anomalia", "hay_incidente")),
        "uids_citados": sorted(set(citados)),
        "invalid_evidence_uid_count": estado.get("invalid_evidence_uid_count"),
        "n_eventos_reconstruidos": len(estado.get("eventos_reconstruidos") or []),
        "n_tecnicas_atribuidas": len(estado.get("tecnicas_atribuidas") or []),
        "largo_diagnostico": len(str(estado.get("diagnostico") or "")),
    }


def trabajar(corrida: Corrida, raiz_repo: Path, destino: Path, runner=None) -> dict:
    """Ejecuta UNA corrida en este proceso y escribe su resumen en `destino`.

    **Hace llamadas al modelo.** Solo se invoca desde un proceso hijo lanzado
    por `ejecutar()` tras `--etapa`.
    """
    from src.experimentation.runners import gemini_externo, nodex

    resultado: dict = {
        "etiqueta": corrida.etiqueta, "modelo": corrida.modelo,
        "arquitectura": corrida.arquitectura, "dataset": corrida.dataset,
        "case_id": corrida.case_id, "excepcion": None, "llm_json": None,
    }
    cuenta = None
    intentos_red: list[str] = []
    if runner is None:
        import requests
        import src.llm as modulo_llm

        intentos_red = _bloquear_red(requests.sessions.Session)
        if corrida.arquitectura == "nodex_multiagente":
            cuenta = _instrumentar_llm_json(modulo_llm)
        runner = (nodex if corrida.arquitectura == "nodex_multiagente"
                  else gemini_externo)

    import src.config as config
    resultado["configuracion_efectiva"] = {
        "LLM_MODEL_PRIMARY": config.LLM_MODEL_PRIMARY,
        "LLM_MODEL_FALLBACK": config.LLM_MODEL_FALLBACK,
        "LLM_SIN_RESPALDO": config.LLM_SIN_RESPALDO,
        "TEMPERATURE": config.TEMPERATURE,
    }
    contenido = runner.cargar_caso(raiz_repo, corrida.dataset, PARTICION, corrida.case_id)
    try:
        estado, diagnostico = runner.ejecutar(contenido, f"comparacion__{corrida.etiqueta}")
    except Exception as e:  # noqa: BLE001 - se registra, no se oculta
        estado, diagnostico = {}, {"error": f"{type(e).__name__}: {e}"}
        resultado["excepcion"] = diagnostico["error"]

    telemetria = dict(estado.get("telemetry") or diagnostico.get("telemetry") or {})
    resultado.update({
        "diagnostico": {k: diagnostico.get(k) for k in
                        ("error", "execution_time", "arquitectura", "modelo")},
        "telemetria": telemetria,
        # Vacío si la corrida no devolvió estado: así un fallo no aparenta
        # tener evidencia "válida" por no citar nada.
        "estado": _resumen_del_estado(estado) if estado else {},
        "llm_json": dict(cuenta) if cuenta is not None else None,
        "intentos_de_red_bloqueados": list(intentos_red),
    })
    destino.write_text(json.dumps(resultado, indent=2, ensure_ascii=False), encoding="utf-8")
    return resultado


# --- clasificación de fallos y regla de repetición ---------------------------------

#: Tipos de fallo de una corrida.
#:   contenido       el modelo respondió pero algún criterio falló (JSON inválido,
#:                   veredicto ausente, uids inválidos, tokens no registrados,
#:                   otro modelo). NO se repite.
#:   infraestructura timeout, 503 o 429 que persisten tras los reintentos con
#:                   espera de src/llm.py. Se repite UNA vez.
#:   otro            un error que no es ninguno de los dos (p. ej. un 400 o un
#:                   fallo del propio código). Cuenta como fallo y NO se repite:
#:                   repetirlo no lo arregla.
FALLO_CONTENIDO = "contenido"
FALLO_INFRAESTRUCTURA = "infraestructura"
FALLO_OTRO = "otro"
MAX_INTENTOS = 2


def clasificar_fallo(resultado: dict, criterios: dict[str, bool]) -> str | None:
    """`None` si la corrida cumple todo; si no, el tipo de fallo.

    Si hay un error, manda el error: un timeout deja sin tokens y sin veredicto,
    y eso no es una falla de contenido sino de infraestructura.
    """
    from src.experimentation.runners.nodex import clasificar_error

    if resultado.get("no_completo_en_el_tiempo_previsto"):
        return FALLO_TOPE
    error = (resultado.get("diagnostico") or {}).get("error") or resultado.get("excepcion")
    if error:
        return (FALLO_INFRAESTRUCTURA
                if clasificar_error(str(error)) in ("error_api", "timeout")
                else FALLO_OTRO)
    return None if all(criterios.values()) else FALLO_CONTENIDO


def correr_corrida(corrida: Corrida, lanzar, uids_caso: frozenset[str] | None) -> dict:
    """Corre una corrida aplicando la regla de repetición. Conserva TODOS los intentos.

    `lanzar(corrida, n)` devuelve el resultado crudo del intento `n`. Solo una
    falla de infraestructura se repite, una vez; si el repetido también falla,
    cuenta como fallo. El resultado final es el del último intento.
    """
    intentos = []
    for n in range(1, MAX_INTENTOS + 1):
        resultado = lanzar(corrida, n)
        resultado["intento"] = n
        resultado["criterios"] = evaluar_criterios(resultado, corrida.modelo, uids_caso)
        resultado["criterios_enmendados"] = evaluar_criterios(
            resultado, corrida.modelo, uids_caso, enmendado=True)
        resultado["tipo_fallo"] = clasificar_fallo(resultado, resultado["criterios"])
        intentos.append(resultado)
        if resultado["tipo_fallo"] != FALLO_INFRAESTRUCTURA:
            break
    final = dict(intentos[-1])
    final["repetida_por_infraestructura"] = len(intentos) > 1
    final["intentos"] = intentos
    return final


# --- revisión inmediata de lo que devolvió la API real ----------------------------------

def revision_inmediata(resultado: dict, modelo: str) -> list[str]:
    """Observaciones INESPERADAS sobre lo que devolvió la API. Vacía = todo limpio.

    No juzga el contenido. Mira solo que la instrumentación recibió lo que debía:
    la versión devuelta no es None y corresponde al modelo pedido, y los tokens
    de razonamiento son un entero o `None` (si el proveedor no los informa, se
    deja así; no se inventan).
    """
    avisos: list[str] = []
    llamadas = (resultado.get("telemetria") or {}).get("llm_calls") or []
    if not llamadas:
        return ["no hay ninguna llamada registrada en la telemetría"]
    for i, c in enumerate(llamadas):
        version = c.get("model_version")
        if version is None:
            avisos.append(f"llamada {i}: model_version es None")
        elif not isinstance(version, str) or not (
                version == modelo or version.startswith(modelo + "-")):
            avisos.append(f"llamada {i}: la versión devuelta {version!r} no corresponde "
                          f"al modelo pedido {modelo!r}")
        if c.get("model") != modelo:
            avisos.append(f"llamada {i}: se pidió {c.get('model')!r} y no {modelo!r}")
        razon = c.get("reasoning_tokens")
        if razon is not None and (isinstance(razon, bool) or not isinstance(razon, int)
                                  or razon < 0):
            avisos.append(f"llamada {i}: reasoning_tokens inválido ({razon!r})")
    if resultado.get("excepcion") or (resultado.get("diagnostico") or {}).get("error"):
        avisos.append("la corrida terminó con error: "
                      f"{resultado.get('excepcion') or resultado['diagnostico']['error']}")
    return avisos


def resumen_de_corrida(final: dict, uids_caso: frozenset[str] | None = None) -> dict:
    """Una fila legible de una corrida final, con los dos veredictos.

    El veredicto ORIGINAL es el que quedó guardado al correr y no se recalcula. El
    enmendado se calcula aquí si la corrida es anterior a la enmienda.
    """
    tel = final.get("telemetria") or {}
    llamadas_tel = tel.get("llm_calls") or []

    def _suma(campo):
        """`(total, parcial)`. Total solo si TODAS las llamadas lo informaron; si
        falta alguna, `total` es None y `parcial` es la suma de las que sí lo
        informaron (un piso: el consumo real es mayor). Ninguna informó: ambos None."""
        valores = [c[campo] for c in llamadas_tel if isinstance(c.get(campo), int)]
        if not llamadas_tel:
            return tel.get(campo), None
        if len(valores) == len(llamadas_tel):
            return sum(valores), None
        return None, (sum(valores) if valores else None)

    entrada, entrada_parcial = _suma("input_tokens")
    salida, salida_parcial = _suma("output_tokens")
    razon, razon_parcial = _suma("reasoning_tokens")
    sin_tokens = sum(1 for c in llamadas_tel
                     if all(c.get(k) is None for k in ("input_tokens", "output_tokens",
                                                       "total_tokens")))
    enmendados = final.get("criterios_enmendados") or evaluar_criterios(
        final, final["modelo"], uids_caso, enmendado=True)
    llamadas = tel.get("llm_calls") or []
    return {
        "etiqueta": final["etiqueta"], "modelo": final["modelo"],
        "arquitectura": final["arquitectura"], "dataset": final["dataset"],
        "case_id": final["case_id"], "criterios": final["criterios"],
        "criterios_enmendados": enmendados,
        "cumple_original": all(final["criterios"].values()),
        "cumple_enmendado": all(enmendados.values()),
        "tiene_estado": bool(final.get("estado")),
        "tipo_fallo": final["tipo_fallo"],
        "repetida_por_infraestructura": final["repetida_por_infraestructura"],
        "n_intentos": len(final["intentos"]),
        "tokens_entrada": entrada, "tokens_salida": salida, "tokens_razonamiento": razon,
        # Sumas PARCIALES (solo las llamadas que informaron tokens). Son un piso.
        "tokens_entrada_parcial": entrada_parcial,
        "tokens_salida_parcial": salida_parcial,
        "tokens_razonamiento_parcial": razon_parcial,
        "n_llamadas_sin_tokens": sin_tokens,
        "suma_parcial": any(x is not None for x in (
            entrada_parcial, salida_parcial, razon_parcial)),
        "no_completo_en_el_tiempo_previsto": bool(
            final.get("no_completo_en_el_tiempo_previsto")),
        "tiempo_s": (final.get("diagnostico") or {}).get("execution_time"),
        "llamadas": tel.get("llm_call_count"),
        "versiones_devueltas": sorted({c["model_version"] for c in llamadas
                                       if c.get("model_version")}),
        "max_tokens_salida_por_llamada": max(
            (c["output_tokens"] for c in llamadas
             if isinstance(c.get("output_tokens"), int)), default=None),
        "intentos_de_red_bloqueados": final.get("intentos_de_red_bloqueados"),
        "configuracion_efectiva": final.get("configuracion_efectiva"),
    }


# --- orquestación del padre ---------------------------------------------------------

def _leer_entorno(ruta: Path) -> dict:
    from dotenv import dotenv_values
    return {k: v for k, v in dotenv_values(ruta).items() if v is not None}


_SCRIPT_CONFIG = (
    "import json, src.config as c; print(json.dumps({"
    "'LLM_MODEL_PRIMARY': c.LLM_MODEL_PRIMARY,"
    "'LLM_MODEL_FALLBACK': c.LLM_MODEL_FALLBACK,"
    "'LLM_SIN_RESPALDO': c.LLM_SIN_RESPALDO,"
    "'TEMPERATURE': c.TEMPERATURE,"
    "'CRONOLOGIA_MAX_EVENTOS': c.CRONOLOGIA_MAX_EVENTOS}))"
)


def verificar_configuracion(raiz_repo: Path, ruta_env: Path) -> list[dict]:
    """Qué configuración verá el sistema con cada modelo. No usa la red."""
    base = {**os.environ, **_leer_entorno(ruta_env)}
    filas = []
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        for modelo in MODELOS:
            entorno = entorno_de_la_corrida(
                base, modelo, Path(tmp) / "chroma", Path(tmp) / "ip.json")
            salida = subprocess.run(
                [sys.executable, "-c", _SCRIPT_CONFIG], cwd=raiz_repo, env=entorno,
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300)
            filas.append(json.loads(salida.stdout.strip().splitlines()[-1]))
    return filas


def _matar_arbol(proceso: subprocess.Popen) -> None:
    """Mata al proceso y a TODOS sus descendientes.

    El `python.exe` del venv es un lanzador que arranca al intérprete real: matar
    solo al lanzador deja vivo al hijo, que sigue gastando llamadas y manteniendo
    abiertas las tuberías.
    """
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(proceso.pid), "/T", "/F"],
                       capture_output=True)
    else:  # pragma: no cover - el proyecto corre en Windows
        import signal
        os.killpg(os.getpgid(proceso.pid), signal.SIGKILL)
    proceso.kill()


def ejecutar_hijo(comando: list[str], cwd: Path, entorno: dict,
                  tope_s: int | None) -> tuple[int | None, str, str, bool]:
    """Corre un proceso hijo. Devuelve `(codigo, stdout, stderr, vencio)`.

    Con `tope_s`, al cumplirse el plazo mata el ÁRBOL de procesos y devuelve
    `vencio=True`. Sin tope espera sin límite.
    """
    proceso = subprocess.Popen(
        comando, cwd=cwd, env=entorno, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace")
    try:
        salida, error = proceso.communicate(timeout=tope_s)
        return proceso.returncode, salida or "", error or "", False
    except subprocess.TimeoutExpired:
        _matar_arbol(proceso)
        salida, error = proceso.communicate()
        return None, salida or "", error or "", True


def _lanzador_real(raiz_repo: Path, base: dict, salida: Path, tmp: Path):
    """Devuelve `lanzar(corrida, n)`: un proceso hijo por intento."""
    def lanzar(corrida: Corrida, n: int) -> dict:
        destino = salida / f"{corrida.etiqueta}.intento{n}.json"
        if destino.exists():
            raise FileExistsError(f"{destino} ya existe: no se sobrescribe")
        copia = tmp / f"chroma_{corrida.etiqueta}_{n}"
        shutil.copytree(configuracion_experimental(raiz_repo).chroma, copia)
        entorno = entorno_de_la_corrida(
            base, corrida.modelo, copia, tmp / f"ip_{corrida.etiqueta}_{n}.json")
        tope = tope_de(corrida)
        codigo, stdout, stderr, vencio = ejecutar_hijo(
            [sys.executable, "-m", "src.experimentation.comparacion_modelos",
             "--trabajar", corrida.modelo, corrida.arquitectura,
             corrida.dataset, corrida.case_id, str(destino)],
            raiz_repo, entorno, tope)
        (salida / f"{corrida.etiqueta}.intento{n}.stderr.txt").write_text(
            stderr, encoding="utf-8")
        # La salida estándar tiene el detalle de cada llamada ([tokens] ...) y los
        # avisos; antes se descartaba.
        (salida / f"{corrida.etiqueta}.intento{n}.stdout.txt").write_text(
            stdout, encoding="utf-8")
        base_resultado = {
            "etiqueta": corrida.etiqueta, "modelo": corrida.modelo,
            "arquitectura": corrida.arquitectura, "dataset": corrida.dataset,
            "case_id": corrida.case_id,
        }
        if vencio:
            return {**base_resultado,
                    "no_completo_en_el_tiempo_previsto": True, "tope_s": tope,
                    "excepcion": f"NoCompletoEnElTiempoPrevisto: superó el tope de {tope} s",
                    "diagnostico": {}, "telemetria": {}, "estado": {}}
        if destino.is_file():
            return json.loads(destino.read_text(encoding="utf-8"))
        return {**base_resultado,
                "excepcion": f"el proceso terminó con código {codigo} sin dejar resultado",
                "diagnostico": {}, "telemetria": {}, "estado": {}}
    return lanzar


def ejecutar(raiz_repo: Path, ruta_env: Path, salida: Path, indices: list[int],
             lanzar=None) -> list[dict]:
    """Corre las corridas `indices` del plan. Escribe `<etiqueta>.final.json`."""
    plan = planificar(raiz_repo)
    salida.mkdir(parents=True, exist_ok=True)
    finales = []
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        if lanzar is None:
            base = {**os.environ, **_leer_entorno(ruta_env)}
            lanzar = _lanzador_real(raiz_repo, base, salida, Path(tmp))
        for i in indices:
            corrida = plan[i]
            archivo = salida / f"{corrida.etiqueta}.final.json"
            if archivo.exists():
                raise FileExistsError(f"{archivo} ya existe: la corrida ya se hizo")
            final = correr_corrida(
                corrida, lanzar, uids_del_caso(raiz_repo, corrida.dataset, corrida.case_id))
            archivo.write_text(json.dumps(final, indent=2, ensure_ascii=False),
                               encoding="utf-8")
            finales.append(final)
    return finales


def resumir(raiz_repo: Path, salida: Path) -> dict:
    """Lee todas las corridas finales de `salida` y aplica la regla de decisión."""
    plan = planificar(raiz_repo)
    filas, faltan = [], []
    for corrida in plan:
        archivo = salida / f"{corrida.etiqueta}.final.json"
        if archivo.is_file():
            final = json.loads(archivo.read_text(encoding="utf-8"))
            constancia = salida / f"{corrida.etiqueta}.tope.json"
            if constancia.is_file():
                # Constancia de un vigilante externo que cortó la corrida al
                # cumplirse el tope; el `final.json` no se edita.
                final["no_completo_en_el_tiempo_previsto"] = True
                final["tipo_fallo"] = FALLO_TOPE
            filas.append(resumen_de_corrida(
                final, uids_del_caso(raiz_repo, corrida.dataset, corrida.case_id)))
        else:
            faltan.append(corrida.etiqueta)
    anuladas = sorted(p.name for p in salida.glob("*.anulada"))
    return {"filas": filas, "corridas_que_faltan": faltan,
            "archivos_anulados_conservados": anuladas, "decision": aplicar_regla(filas)}


def describir_plan(plan: list[Corrida]) -> str:
    lineas = [f"Comparacion minima: {len(plan)} corridas, "
              f"{llamadas_minimas(plan)} llamadas minimas (es un piso, no una estimacion)"]
    for i, c in enumerate(plan, start=1):
        etapa = 1 if i <= ETAPA_1 else 2
        lineas.append(f"  {i}. [etapa {etapa}] {c.modelo:<24} {c.arquitectura:<18} "
                      f"{c.dataset}  {c.case_id}  >= {LLAMADAS_MINIMAS[c.arquitectura]} llamadas")
    return "\n".join(lineas)


def _parsear_corridas(texto: str, total: int) -> list[int]:
    """`"2"`, `"3-8"` o `"2,5-6"` (numeración desde 1) -> índices desde 0, ordenados."""
    indices: set[int] = set()
    for parte in texto.split(","):
        extremos = parte.strip().split("-")
        desde, hasta = int(extremos[0]), int(extremos[-1])
        if not (1 <= desde <= hasta <= total):
            raise ValueError(f"corridas fuera del plan (1-{total}): {parte!r}")
        indices.update(range(desde - 1, hasta))
    return sorted(indices)


def _dentro_de(hijo: Path, padre: Path) -> bool:
    try:
        hijo.resolve().relative_to(padre.resolve())
        return True
    except ValueError:
        return False


def main(argv: list[str] | None = None, raiz_repo: Path | None = None) -> int:
    raiz_repo = raiz_repo or Path(__file__).resolve().parents[2]
    p = argparse.ArgumentParser(prog="comparacion_modelos", description=__doc__.split("\n")[0])
    p.add_argument("--etapa", type=int, choices=(1, 2),
                   help="HACE LLAMADAS AL MODELO. 1 = las dos primeras corridas (BGL con el "
                        "candidato); se detiene para revisar. 2 = las seis restantes.")
    p.add_argument("--corridas", metavar="N[,N-M]",
                   help="HACE LLAMADAS AL MODELO. Corre estas corridas del plan "
                        "(numeración de la lista impresa), p. ej. 2 o 3-8.")
    p.add_argument("--verificar-config", action="store_true",
                   help="muestra la configuracion efectiva por modelo; no usa la red.")
    p.add_argument("--resumir", action="store_true",
                   help="lee las corridas ya hechas en --salida y aplica la regla. Sin red.")
    p.add_argument("--env", help="ruta al .env con las credenciales (no se copia).")
    p.add_argument("--salida", help="directorio FUERA de experiments/.")
    p.add_argument("--trabajar", nargs=5, metavar=("MODELO", "ARQ", "DATASET", "CASO", "DESTINO"),
                   help="uso interno: corre una corrida en este proceso.")
    args = p.parse_args(argv)

    if args.trabajar:
        modelo, arquitectura, dataset, case_id, destino = args.trabajar
        trabajar(Corrida(modelo, arquitectura, dataset, case_id), raiz_repo, Path(destino))
        return 0

    plan = planificar(raiz_repo)
    print(describir_plan(plan))

    if args.verificar_config:
        if not args.env:
            p.error("--verificar-config necesita --env")
        for modelo, fila in zip(MODELOS, verificar_configuracion(raiz_repo, Path(args.env))):
            print(f"  config efectiva con {modelo}: {json.dumps(fila)}")
        return 0

    if args.resumir:
        if not args.salida:
            p.error("--resumir necesita --salida")
        print(json.dumps(resumir(raiz_repo, Path(args.salida)), indent=2, ensure_ascii=False))
        return 0

    if not args.etapa and not args.corridas:
        print("\n(sin --etapa ni --corridas: no se hizo ninguna llamada)")
        return 0

    if not args.env or not args.salida:
        p.error("--etapa y --corridas necesitan --env y --salida")
    salida = Path(args.salida)
    if _dentro_de(salida, raiz_repo / "experiments"):
        p.error("--salida debe estar FUERA de experiments/: esto no es un resultado reportable")
    if args.corridas:
        indices = _parsear_corridas(args.corridas, len(plan))
    else:
        indices = list(range(ETAPA_1)) if args.etapa == 1 else list(range(ETAPA_1, len(plan)))
    if args.etapa == 1 and salida.exists() and any(salida.iterdir()):
        p.error("--salida ya tiene contenido: la etapa 1 no sobrescribe nada")
    finales = ejecutar(raiz_repo, Path(args.env), salida, indices)
    inesperado = False
    for final in finales:
        avisos = revision_inmediata(final, final["modelo"])
        print(f"\n{final['etiqueta']}: intentos={len(final['intentos'])} "
              f"tipo_fallo={final['tipo_fallo']}")
        print(f"  criterios: {final['criterios']}")
        for a in avisos:
            print(f"  INESPERADO: {a}")
        inesperado = inesperado or bool(avisos)
    return 3 if inesperado else 0


if __name__ == "__main__":
    raise SystemExit(main())
