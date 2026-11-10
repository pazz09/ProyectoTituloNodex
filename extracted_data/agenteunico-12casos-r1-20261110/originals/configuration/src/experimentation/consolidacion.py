"""Consolidación de resultados: de las corridas guardadas a tablas del informe.

Toma lo que la campaña dejó en `experiments/` y lo convierte en las tablas
que alimentan las secciones 11.1 a 11.7 del informe, escritas en
`experiments/metrics/<config_version>/<marca>/`.

## No reimplementa ninguna métrica

Todo el cálculo viene de `src/experimentation/evaluators/` (detección, conjuntos,
rúbrica, consumo) y de `runtime/exportacion.py`. Este módulo solo **agrupa**
—por dataset, arquitectura, condición y repetición—, **declara** y **escribe**.
Si un número de una tabla no coincide con un evaluador, el error está acá.

## Reglas de honestidad

- **`null` es "no aplica o sin dato", nunca cero.** Una celda inaplicable va
  `null` en JSON y vacía en CSV.
- **Nada se oculta.** Las corridas ausentes, las fallidas, las que usaron otro
  modelo (fallback) y las de telemetría previa a D-11 se cuentan y se
  declaran junto a los números, en `integridad`.
- **No se sobrescribe.** Cada consolidación va a un directorio nuevo; si ya
  existe, falla.
- **No abre el ground truth.** Lo hace `evaluacion.py`, que es quien corrige.
  Este módulo recibe sus registros ya corregidos.

## Definiciones, para que el número se pueda leer

- **D1 micro**: una sola matriz de confusión con todas las corridas
  evaluables del grupo (dataset × arquitectura), repeticiones incluidas.
- **D1 macro por condición**: el promedio de las métricas calculadas dentro de
  cada condición (natural, balanceado, visible, sigiloso). Cada condición pesa
  igual aunque tenga distinto número de casos o distinta prevalencia.
- **Media y desviación entre repeticiones**: la métrica se calcula por
  repetición y se promedia. Con una sola repetición la desviación es `null`,
  no cero: una sola observación no tiene dispersión.
- **D2 / D3 micro y macro**: ver `evaluators/conjuntos.py`.
- **Fallback de modelo**: una corrida lo usó si alguna de sus llamadas la
  respondió un modelo distinto del principal de la configuración congelada.
  Sin configuración congelada no se puede saber, y se declara en vez de
  suponer que no hubo.
"""

from __future__ import annotations

import csv
import json
import statistics
from datetime import datetime, timezone
from pathlib import Path

from src.experimentation import estadistica
from src.experimentation.contracts import PROTOCOLO_VERSION
from src.experimentation.evaluacion import (
    REGLA_D2_D3,
    RegistroEvaluado,
    ResultadoEvaluacion,
    evaluar_corridas,
)
from src.experimentation.evaluators import deteccion as eval_deteccion
from src.experimentation.evaluators.agregacion import (
    construir_conjuntos,
    construir_consumo,
    construir_deteccion,
    construir_reporte,
    escribir_resultado,
)
from src.experimentation.evaluators.conjuntos import evaluar_conjuntos
from src.experimentation.evaluators.consumo import agregar as agregar_consumo
from src.experimentation.evaluators.reporte import (
    CRITERIOS,
    PuntuacionRubrica,
    agregar as agregar_rubrica,
)
from src.experimentation.orquestador import ARQUITECTURAS_CAMPANA
from src.experimentation.runtime import exportacion, persistencia
from src.experimentation.runtime.identidad import IdentidadCorrida
from src.experimentation.runtime.telemetria import campos_de_modelo

ESQUEMA_RESULTADOS = "resultados-v1"

#: Estados de ejecución que cuentan como corrida completa.
ESTADO_COMPLETA = "completa"


# --- utilidades numéricas ----------------------------------------------------

def _definidos(valores) -> list[float]:
    return [v for v in valores if v is not None]


def media(valores) -> float | None:
    """Promedio ignorando `None`. Con todo `None` es `None`, no cero."""
    d = _definidos(valores)
    return statistics.fmean(d) if d else None


def desviacion(valores) -> float | None:
    """Desviación muestral. Con menos de dos observaciones es `None`."""
    d = _definidos(valores)
    return statistics.stdev(d) if len(d) >= 2 else None


# --- entradas auxiliares -----------------------------------------------------

def modelo_principal_congelado(raiz_repo: Path, config_version: str) -> str | None:
    """`LLM_MODEL_PRIMARY` de la configuración congelada, o `None` si no hay."""
    ruta = raiz_repo / "experiments" / "config" / f"config_{config_version}.json"
    if not ruta.is_file():
        return None
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    return (datos.get("parametros") or {}).get("LLM_MODEL_PRIMARY")


def modelos_de_la_corrida(telemetria: dict | None) -> list[str]:
    """Modelos que respondieron en una corrida, según su telemetría."""
    if not telemetria:
        return []
    llamadas = telemetria.get("llm_calls")
    if isinstance(llamadas, list) and llamadas:
        return sorted({str(c.get("model")) for c in llamadas if c.get("model")})
    efectivo = telemetria.get("modelo_efectivo")
    return [str(efectivo)] if efectivo else []


def uso_fallback(telemetria: dict | None, principal: str | None) -> bool | None:
    """`True`/`False`, o `None` si no se puede determinar."""
    modelos = modelos_de_la_corrida(telemetria)
    if principal is None or not modelos:
        return None
    return any(m != principal for m in modelos)


def _con_tokens(llamada: dict) -> bool:
    """La llamada informó tokens de entrada y de salida."""
    return all(isinstance(llamada.get(c), int) and not isinstance(llamada.get(c), bool)
               for c in ("input_tokens", "output_tokens"))


def tokens_de_la_corrida(telemetria: dict | None) -> dict:
    """Qué tokens se pueden afirmar de una corrida, llamada por llamada.

    `src/telemetry.py` calcula los totales de forma todo-o-nada: una sola
    llamada fallida deja los totales de la corrida en `None`. Esto recupera lo que
    SÍ se sabe: la suma de las llamadas que informaron tokens. Esa suma es un
    PISO (el consumo real es mayor), nunca un total.

    `completa` es `True` solo si TODAS las llamadas informaron tokens. Una llamada
    cuenta como fallida si trae `error` o si no informó ningún token.
    """
    llamadas = [c for c in ((telemetria or {}).get("llm_calls") or []) if isinstance(c, dict)]
    con_tokens = [c for c in llamadas if _con_tokens(c)]

    def suma(campo):
        valores = [c[campo] for c in con_tokens
                   if isinstance(c.get(campo), int) and not isinstance(c.get(campo), bool)]
        return sum(valores) if valores else None

    fallidas = sum(
        1 for c in llamadas
        if c.get("error") is not None
        or all(c.get(k) is None for k in ("input_tokens", "output_tokens", "total_tokens")))
    return {
        "n_llamadas": len(llamadas), "n_con_tokens": len(con_tokens),
        "n_fallidas": fallidas, "entrada": suma("input_tokens"),
        "salida": suma("output_tokens"), "razonamiento": suma("reasoning_tokens"),
        "completa": bool(llamadas) and len(con_tokens) == len(llamadas),
    }


def es_parcial(telemetria: dict | None) -> bool:
    """Total `None`, pero algunas llamadas sí informaron tokens (y otras no)."""
    d = tokens_de_la_corrida(telemetria)
    return (telemetria or {}).get("total_tokens") is None and 0 < d["n_con_tokens"] < d["n_llamadas"]


def _miles(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def texto_tokens_parciales(corridas: list[dict]) -> str | None:
    """Suma parcial rotulada de un grupo de corridas con total `None`.

    Siempre con «≥» (es un piso) y con «(k de n llamadas)», para que nadie la lea
    como un total. `None` si no hay nada que mostrar.
    """
    partes = [tokens_de_la_corrida(t) for t in corridas]
    k = sum(d["n_con_tokens"] for d in partes)
    n = sum(d["n_llamadas"] for d in partes)
    if not partes or k == 0:
        return None
    etiquetas = []
    for campo, nombre in (("entrada", "entrada"), ("salida", "salida"),
                          ("razonamiento", "razonamiento")):
        valores = [d[campo] for d in partes if d[campo] is not None]
        if valores:
            etiquetas.append(f"≥ {_miles(sum(valores))} {nombre}")
    return f"{' · '.join(etiquetas)} ({k} de {n} llamadas)"


def leer_rubrica(
    raiz_repo: Path, config_version: str
) -> tuple[list[PuntuacionRubrica], list[dict]]:
    """Puntajes humanos de `experiments/rubrica/<config_version>/puntajes.csv`.

    Columnas: `case_id, arquitectura, repeticion, evaluador` y los cinco
    criterios (escala 0 a 3, decisión D-4). Una fila inválida no se descarta
    en silencio ni tumba la consolidación: se devuelve aparte, para
    declararla. Si el archivo no existe, la dimensión queda sin datos.
    """
    ruta = raiz_repo / "experiments" / "rubrica" / config_version / "puntajes.csv"
    if not ruta.is_file():
        return [], []
    validas: list[PuntuacionRubrica] = []
    invalidas: list[dict] = []
    with ruta.open(encoding="utf-8", newline="") as f:
        for numero, fila in enumerate(csv.DictReader(f), start=2):
            try:
                validas.append(PuntuacionRubrica(
                    case_id=fila["case_id"],
                    arquitectura=fila["arquitectura"],
                    evaluador=fila["evaluador"],
                    puntajes={c: int(fila[c]) for c in CRITERIOS},
                ))
            except (KeyError, ValueError, TypeError) as error:
                invalidas.append({"linea": numero, "error": str(error)})
    return validas, invalidas


def ultimo_fallo_por_corrida(fallos: list[dict]) -> list[dict]:
    """Un registro por corrida: el del último intento.

    Los intentos se acumulan en disco (`__f1`, `__f2`...) para no perder el
    historial, pero una corrida que falló tres veces es UNA corrida fallida,
    no tres; contarla tres veces inflaría la cifra de fallos.
    """
    ultimo: dict = {}
    for f in fallos:
        previo = ultimo.get(f["run_id"])
        if previo is None or f.get("intento", 0) >= previo.get("intento", 0):
            ultimo[f["run_id"]] = f
    return [ultimo[k] for k in sorted(ultimo)]


def _dataset_de(case_id: str) -> str:
    return case_id.split("_")[0]


# --- tablas ------------------------------------------------------------------

def _tabla(titulo, seccion, columnas, filas, descripcion=None, aviso=None) -> dict:
    return {
        "titulo": titulo,
        "seccion": seccion,
        "descripcion": descripcion,
        # Advertencia que la vista muestra DESTACADA (no una nota al pie).
        "aviso": aviso,
        "columnas": [
            {"clave": c[0], "etiqueta": c[1], "tipo": c[2] if len(c) > 2 else "texto"}
            for c in columnas
        ],
        "filas": filas,
    }


def _grupos(registros: list[RegistroEvaluado]) -> dict:
    """Agrupa por (dataset, arquitectura), conservando un orden estable."""
    grupos: dict = {}
    for r in sorted(registros, key=lambda r: (r.dataset, r.arquitectura, r.run_id)):
        grupos.setdefault((r.dataset, r.arquitectura), []).append(r)
    return grupos


def _pares(registros) -> list:
    return [
        eval_deteccion.ParDeteccion(r.case_id, r.prediccion, r.referencia)
        for r in registros if r.resultado_d1 != "NA"
    ]


def _estados_d1(registros) -> list[str]:
    """Estado de D1 por corrida, coherente con la matriz de confusión."""
    estados = []
    for r in registros:
        if r.resultado_d1 != "NA":
            estados.append("evaluable")
        else:
            previo = r.estados.get("deteccion", "no_evaluable")
            estados.append("no_evaluable" if previo == "evaluable" else previo)
    return estados


_METRICAS_CON_INTERVALO = (
    ("accuracy", lambda c: (c.tp + c.tn, c.total)),
    ("precision", lambda c: (c.tp, c.tp + c.fp)),
    ("recall", lambda c: (c.tp, c.tp + c.fn)),
)


def _intervalos_d1(conteos) -> dict:
    """Intervalo de Wilson al 95 % de exactitud, precisión y exhaustividad, con su texto."""
    campos = {}
    for nombre, numerador_y_denominador in _METRICAS_CON_INTERVALO:
        aciertos, total = numerador_y_denominador(conteos)
        ic = estadistica.wilson(aciertos, total)
        campos[f"{nombre}_ic"] = estadistica.texto_intervalo(ic)
        campos[f"{nombre}_ic_inf"] = None if ic is None else round(ic[0], 6)
        campos[f"{nombre}_ic_sup"] = None if ic is None else round(ic[1], 6)
        campos[f"{nombre}_ic_n"] = total
    return campos


def _aviso_muestras_chicas(filas: list[dict]) -> str | None:
    """Aviso destacado: con pocos casos por celda los intervalos son anchos y las repeticiones no
    son independientes. Lleva los tamaños reales."""
    ns = [f["n_evaluables"] for f in filas if f.get("n_evaluables")]
    if not ns:
        return None
    rango = str(min(ns)) if min(ns) == max(ns) else f"{min(ns)} a {max(ns)}"
    return (f"Muestras chicas: {rango} corridas evaluables por celda. Los intervalos de confianza son "
            f"anchos: una diferencia entre arquitecturas que cabe dentro de ellos no permite decir "
            f"que una sea mejor que otra. Las repeticiones de un mismo caso no son independientes, así "
            f"que los intervalos de Wilson (que las tratan como independientes) son además optimistas.")


def tabla_d1(registros) -> tuple[dict, dict, list]:
    """D1 por dataset y arquitectura, y por condición. Devuelve también los
    `MetricsRecord` del contrato, que validan el invariante contable."""
    filas, filas_cond, contratos = [], [], []
    for (dataset, arquitectura), grupo in _grupos(registros).items():
        pares = _pares(grupo)
        conteos = eval_deteccion.contar(pares)
        m = eval_deteccion.metricas(conteos)
        estados = _estados_d1(grupo)

        por_cond = {}
        for condicion in sorted({r.condicion for r in grupo}):
            sub = _pares([r for r in grupo if r.condicion == condicion])
            c = eval_deteccion.contar(sub)
            mc = eval_deteccion.metricas(c)
            por_cond[condicion] = mc
            filas_cond.append({
                "dataset": dataset, "arquitectura": arquitectura,
                "condicion": condicion, "n_evaluables": c.total,
                "tp": c.tp, "fp": c.fp, "fn": c.fn, "tn": c.tn,
                "precision": mc["precision"], "recall": mc["recall"], "f1": mc["f1"],
            })

        por_rep = {}
        for rep in sorted({r.repeticion for r in grupo}):
            sub = _pares([r for r in grupo if r.repeticion == rep])
            por_rep[rep] = eval_deteccion.metricas(eval_deteccion.contar(sub))

        filas.append({
            "dataset": dataset, "arquitectura": arquitectura,
            "n_corridas": len(grupo), "n_evaluables": conteos.total,
            "no_evaluables": len(grupo) - conteos.total,
            "tp": conteos.tp, "fp": conteos.fp, "fn": conteos.fn, "tn": conteos.tn,
            "accuracy": m["accuracy"], "precision": m["precision"],
            "recall": m["recall"], "f1": m["f1"], "fpr": m["fpr"], "fnr": m["fnr"],
            "f1_macro_condiciones": media([v["f1"] for v in por_cond.values()]),
            "f1_media_repeticiones": media([v["f1"] for v in por_rep.values()]),
            "f1_desv_repeticiones": desviacion([v["f1"] for v in por_rep.values()]),
            **_intervalos_d1(conteos),
        })
        contratos.append(construir_deteccion(arquitectura, dataset, estados, conteos, m))

    t1 = _tabla(
        "Detección por dataset y arquitectura", "11.1",
        [("dataset", "Dataset"), ("arquitectura", "Arquitectura"),
         ("n_corridas", "Corridas", "entero"), ("n_evaluables", "Evaluables", "entero"),
         ("no_evaluables", "No evaluables", "entero"),
         ("tp", "TP", "entero"), ("fp", "FP", "entero"),
         ("fn", "FN", "entero"), ("tn", "TN", "entero"),
         ("accuracy", "Exactitud", "proporcion"), ("precision", "Precisión", "proporcion"),
         ("recall", "Exhaustividad", "proporcion"), ("f1", "F1", "proporcion"),
         ("fpr", "FPR", "proporcion"), ("fnr", "FNR", "proporcion"),
         ("f1_macro_condiciones", "F1 macro (condiciones)", "proporcion"),
         ("f1_media_repeticiones", "F1 media (repeticiones)", "proporcion"),
         ("f1_desv_repeticiones", "F1 desv. (repeticiones)", "proporcion"),
         ("accuracy_ic", "IC 95 % Exactitud (Wilson)"),
         ("precision_ic", "IC 95 % Precisión (Wilson)"),
         ("recall_ic", "IC 95 % Exhaustividad (Wilson)")],
        filas,
        "Micro: una matriz con todas las corridas evaluables. Una celda vacía es "
        "«sin dato», no cero. IC 95 %: intervalo de Wilson de la exactitud (TP+TN sobre evaluables), "
        "la precisión (TP sobre TP+FP) y la exhaustividad (TP sobre TP+FN).",
        _aviso_muestras_chicas(filas),
    )
    t2 = _tabla(
        "Detección por condición", "11.1",
        [("dataset", "Dataset"), ("arquitectura", "Arquitectura"),
         ("condicion", "Condición"), ("n_evaluables", "Evaluables", "entero"),
         ("tp", "TP", "entero"), ("fp", "FP", "entero"),
         ("fn", "FN", "entero"), ("tn", "TN", "entero"),
         ("precision", "Precisión", "proporcion"),
         ("recall", "Exhaustividad", "proporcion"), ("f1", "F1", "proporcion")],
        filas_cond,
    )
    return t1, t2, contratos


def _tabla_conjuntos(registros, dimension: str, seccion: str, titulo: str):
    """D2 (reconstrucción) o D3 (MITRE, nivel técnica)."""
    filas, contratos = [], []
    for (dataset, arquitectura), grupo in _grupos(registros).items():
        estados = [r.estados.get(dimension, "no_aplica") for r in grupo]
        if all(e == "no_aplica" for e in estados):
            continue  # la dimensión no corresponde a este dataset/arquitectura
        # Cobertura: k de n evaluables, donde n son las corridas a las que la dimensión APLICA
        # (con referencia). Las omisiones cuentan como evaluables: son un fallo, no un hueco.
        n_aplicables = sum(1 for e in estados if e != "no_aplica")
        n_omisiones = sum(
            1 for r in grupo
            if getattr(r, "omision_d2" if dimension == "reconstruccion" else "omision_d3"))
        attr = "comparacion_d2" if dimension == "reconstruccion" else "comparacion_d3"
        comps = [getattr(r, attr) for r in grupo if getattr(r, attr) is not None]
        resultado = evaluar_conjuntos(comps)
        por_rep = [
            evaluar_conjuntos([getattr(r, attr) for r in grupo
                               if r.repeticion == rep and getattr(r, attr) is not None])
            for rep in sorted({r.repeticion for r in grupo})
        ]
        fila = {
            "dataset": dataset, "arquitectura": arquitectura,
            "n_corridas": len(grupo), "n_evaluables": len(comps),
            "cobertura": f"{len(comps)} de {n_aplicables}",
            "n_omisiones": n_omisiones,
            "no_evaluables": sum(1 for e in estados if e == "no_evaluable"),
            "micro_precision": resultado.micro.get("precision"),
            "micro_recall": resultado.micro.get("recall"),
            "micro_f1": resultado.micro.get("f1"),
            "macro_precision": resultado.macro.get("precision"),
            "macro_recall": resultado.macro.get("recall"),
            "macro_f1": resultado.macro.get("f1"),
            "exact_match": resultado.exact_match,
            "f1_media_repeticiones": media([p.micro.get("f1") for p in por_rep if p.n_casos]),
            "f1_desv_repeticiones": desviacion([p.micro.get("f1") for p in por_rep if p.n_casos]),
        }
        if dimension == "reconstruccion":
            fila["uids_inventados"] = sum(r.uids_inventados_d2 for r in grupo)
        else:
            fila["atribuciones_sin_evidencia"] = sum(len(r.sin_evidencia_d3) for r in grupo)
        filas.append(fila)
        contratos.append(construir_conjuntos(
            dimension, arquitectura, dataset, estados, resultado,
            nivel="tecnica" if dimension == "mitre" else None,
        ))

    extra = ("uids_inventados", "uids inventados") if dimension == "reconstruccion" \
        else ("atribuciones_sin_evidencia", "atribuciones sin evidencia")
    columnas = [
        ("dataset", "Dataset"), ("arquitectura", "Arquitectura"),
        ("n_corridas", "Corridas", "entero"), ("cobertura", "Cobertura (evaluables)"),
        ("n_evaluables", "Evaluables", "entero"), ("n_omisiones", "Omisiones", "entero"),
        ("no_evaluables", "No evaluables", "entero"),
        ("micro_precision", "Precisión (micro)", "proporcion"),
        ("micro_recall", "Exhaustividad (micro)", "proporcion"),
        ("micro_f1", "F1 (micro)", "proporcion"),
        ("macro_precision", "Precisión (macro)", "proporcion"),
        ("macro_recall", "Exhaustividad (macro)", "proporcion"),
        ("macro_f1", "F1 (macro)", "proporcion"),
        ("exact_match", "Coincidencia exacta", "proporcion"),
        ("f1_media_repeticiones", "F1 media (repeticiones)", "proporcion"),
        ("f1_desv_repeticiones", "F1 desv. (repeticiones)", "proporcion"),
        (extra[0], extra[1].capitalize(), "entero"),
    ]
    return _tabla(
        titulo, seccion, columnas, filas,
        "Cobertura = evaluables de las corridas a las que la dimensión aplica (con referencia). "
        "Omisión: corrida válida y completa en que el sistema no entregó nada y la referencia "
        "existe; CUENTA (exhaustividad 0, precisión indefinida) y no sale de la métrica "
        "(enmienda del 15-oct-2026, fijada antes de la campaña). No evaluables: la corrida "
        "falló o su formato es inválido; se informan aparte."), contratos


def tabla_d4(puntuaciones: list[PuntuacionRubrica], registros) -> tuple[dict, list]:
    por_grupo: dict = {}
    for p in puntuaciones:
        por_grupo.setdefault((_dataset_de(p.case_id), p.arquitectura), []).append(p)
    filas, contratos = [], []
    for (dataset, arquitectura), grupo in sorted(por_grupo.items()):
        r = agregar_rubrica(grupo)
        d = r.to_dict()
        filas.append({
            "dataset": dataset, "arquitectura": arquitectura,
            "n_reportes": r.n_reportes, "n_evaluadores": r.n_evaluadores,
            **{c: d["por_criterio"].get(c) for c in CRITERIOS},
            "promedio_global": d["promedio_global"],
            "acuerdo_exacto": d["concordancia"].get("acuerdo_exacto"),
            "acuerdo_hasta_un_nivel": d["concordancia"].get("acuerdo_hasta_un_nivel"),
            "diferencia_absoluta_media": d["concordancia"].get("diferencia_absoluta_media"),
            "desacuerdos_relevantes": d["concordancia"].get("n_desacuerdos_relevantes"),
        })
        contratos.append(construir_reporte(
            arquitectura, dataset, ["evaluable"] * r.n_reportes, r))
    columnas = [
        ("dataset", "Dataset"), ("arquitectura", "Arquitectura"),
        ("n_reportes", "Reportes", "entero"), ("n_evaluadores", "Evaluadores", "entero"),
        ("completitud", "Completitud", "numero"),
        ("correccion_factual", "Corrección factual", "numero"),
        ("coherencia_con_evidencia", "Coherencia con evidencia", "numero"),
        ("claridad", "Claridad", "numero"),
        ("informacion_no_sustentada", "Sin información inventada", "numero"),
        ("promedio_global", "Promedio global", "numero"),
        ("acuerdo_exacto", "Acuerdo exacto", "proporcion"),
        ("acuerdo_hasta_un_nivel", "Acuerdo ±1 nivel", "proporcion"),
        ("diferencia_absoluta_media", "Diferencia absoluta media", "numero"),
        ("desacuerdos_relevantes", "Desacuerdos de 2+ niveles", "entero"),
    ]
    return _tabla(
        "Rúbrica del reporte (escala 0 a 3)", "11.4", columnas, filas,
        "Dos evaluadores humanos. Concordancia por acuerdo exacto, hasta un nivel "
        "y diferencia absoluta media; no se calcula kappa. En el último criterio, "
        "3 significa ausencia de información no sustentada.",
    ), contratos


def tabla_consumo(registros, telemetrias, fallos_sin_salida, principal) -> tuple[dict, list]:
    filas, contratos = [], []
    por_grupo = _grupos(registros)
    # Una arquitectura/dataset con solo corridas fallidas también debe figurar.
    for f in fallos_sin_salida:
        por_grupo.setdefault((f["dataset"], f["arquitectura"]), [])
    for (dataset, arquitectura), grupo in sorted(por_grupo.items()):
        corridas = [
            {"estado": r.estado_ejecucion or "desconocido",
             "telemetria": telemetrias.get(r.run_id) or {}}
            for r in grupo
        ]
        corridas += [
            {"estado": f.get("estado") or "fallida", "telemetria": {}}
            for f in fallos_sin_salida
            if f["dataset"] == dataset and f["arquitectura"] == arquitectura
        ]
        agg = agregar_consumo(corridas)
        c = agg.por_campo
        completas = [r for r in grupo if r.estado_ejecucion == ESTADO_COMPLETA]
        es_baseline = arquitectura == "baseline_reglas"
        filas.append({
            "dataset": dataset, "arquitectura": arquitectura,
            "n_completas": agg.n_corridas_completas,
            "n_no_completas": len(corridas) - agg.n_corridas_completas,
            "tiempo_medio_s": c["execution_time"]["media"],
            "tiempo_mediana_s": c["execution_time"]["mediana"],
            "llamadas_medias": c["llm_call_count"]["media"],
            "tokens_entrada_medios": c["input_tokens"]["media"],
            "tokens_salida_medios": c["output_tokens"]["media"],
            # `None` cuando ninguna corrida informó razonamiento: no es 0.
            "tokens_razonamiento_medios": c["reasoning_tokens"]["media"],
            "tokens_totales_medios": c["total_tokens"]["media"],
            # Versión(es) que devolvió la API, tal cual. `None` para el
            # baseline (no usa el modelo) o si ninguna respuesta la informó.
            "versiones_devueltas": "; ".join(sorted({
                v for r in grupo
                for v in (telemetrias.get(r.run_id) or {}).get("modelos_efectivos") or []
            })) or None,
            "replan_medio": c["replan_count"]["media"],
            "correcciones_medias": c["intentos_correccion"]["media"],
            # El baseline no usa el modelo: no tiene tokens que informar ni un
            # modelo al que caer. Para él estas dos celdas NO APLICAN (null);
            # un 0 diría «usó el modelo principal y no faltó ningún dato».
            # Corridas completas con total `None` (por una llamada fallida o porque el
            # proveedor no informó): quedan FUERA de las medias de tokens de arriba.
            "n_llamadas_fallidas": None if es_baseline else sum(
                tokens_de_la_corrida(telemetrias.get(r.run_id))["n_fallidas"]
                for r in grupo),
            # Suma parcial de esas corridas, rotulada como piso. Nunca se mezcla con
            # las medias ni con los totales.
            "tokens_parciales": None if es_baseline else texto_tokens_parciales([
                telemetrias.get(r.run_id) for r in completas
                if es_parcial(telemetrias.get(r.run_id))]),
            "n_con_fallback": None if es_baseline else sum(
                1 for r in grupo
                if uso_fallback(telemetrias.get(r.run_id), principal) is True),
            "n_sin_tokens": None if es_baseline else sum(
                1 for r in completas
                if (telemetrias.get(r.run_id) or {}).get("total_tokens") is None),
        })
        estados = ["evaluable" if k["estado"] == ESTADO_COMPLETA else "fallido"
                   for k in corridas]
        contratos.append(construir_consumo(arquitectura, dataset, estados, agg))
    columnas = [
        ("dataset", "Dataset"), ("arquitectura", "Arquitectura"),
        ("n_completas", "Completas", "entero"), ("n_no_completas", "No completas", "entero"),
        ("tiempo_medio_s", "Tiempo medio (s)", "numero"),
        ("tiempo_mediana_s", "Tiempo mediana (s)", "numero"),
        ("llamadas_medias", "Llamadas al modelo", "numero"),
        ("tokens_entrada_medios", "Tokens de entrada", "numero"),
        ("tokens_salida_medios", "Tokens de salida", "numero"),
        ("tokens_razonamiento_medios", "Tokens de razonamiento", "numero"),
        ("tokens_totales_medios", "Tokens totales", "numero"),
        ("versiones_devueltas", "Versión devuelta por la API"),
        ("replan_medio", "Replanificaciones", "numero"),
        ("correcciones_medias", "Correcciones", "numero"),
        ("n_con_fallback", "Con fallback", "entero"),
        ("n_sin_tokens", "Corridas con total None", "entero"),
        ("n_llamadas_fallidas", "Llamadas fallidas", "entero"),
        ("tokens_parciales", "Tokens parciales (≥, piso)"),
    ]
    return _tabla(
        "Consumo y comportamiento operacional", "11.5", columnas, filas,
        "Solo promedian las corridas completas: una corrida cortada consumió menos y "
        "haría parecer más eficiente a la arquitectura que más falla. Si el proveedor "
        "no informó los tokens, la celda queda vacía; no se estiman. Una llamada "
        "fallida deja el total de su corrida en None y la deja fuera de las medias "
        "de tokens («Corridas con total None»); lo que sí se sabe de esas corridas se "
        "muestra aparte como suma parcial («Tokens parciales», ≥, un piso), nunca como total.",
    ), contratos


def _variacion_pct(valores: list[float]) -> float | None:
    """(máximo − mínimo) / media × 100 de las repeticiones de un caso. `None` si no se puede."""
    if len(valores) < 2:
        return None
    m = sum(valores) / len(valores)
    return None if m == 0 else 100 * (max(valores) - min(valores)) / m


def tabla_consistencia(registros, telemetrias) -> dict:
    """¿El sistema repite lo que dice? Concordancia de veredicto y variación de tokens y tiempo
    entre las repeticiones de un mismo caso. Solo hay filas donde hay repeticiones (no el baseline).

    - Concordancia: de los casos con veredicto en al menos 2 repeticiones, en cuántos todas
      coinciden. Una repetición sin veredicto (falló) no se compara; se cuenta aparte.
    - Variación: por caso, (máximo − mínimo) / media de la repetición; se informa la media y el
      máximo sobre los casos. Tokens: total de la corrida; tiempo: segundos de ejecución.
    """
    filas = []
    for (dataset, arquitectura), grupo in _grupos(registros).items():
        por_caso: dict[str, list] = {}
        for r in grupo:
            por_caso.setdefault(r.case_id, []).append(r)
        if max(len(v) for v in por_caso.values()) < 2:
            continue
        comparables = concordantes = sin_comparar = 0
        var_tokens, var_tiempo = [], []
        for reps in por_caso.values():
            veredictos = [r.prediccion for r in reps if r.prediccion is not None]
            if len(veredictos) >= 2:
                comparables += 1
                concordantes += len(set(veredictos)) == 1
            else:
                sin_comparar += 1
            tokens = [t["total_tokens"] for r in reps
                      if (t := telemetrias.get(r.run_id) or {}).get("total_tokens") is not None]
            tiempos = [t["execution_time"] for r in reps
                       if (t := telemetrias.get(r.run_id) or {}).get("execution_time") is not None]
            if (v := _variacion_pct(tokens)) is not None:
                var_tokens.append(v)
            if (v := _variacion_pct(tiempos)) is not None:
                var_tiempo.append(v)
        ic = estadistica.wilson(concordantes, comparables)
        filas.append({
            "dataset": dataset, "arquitectura": arquitectura,
            "n_casos": len(por_caso), "n_comparables": comparables,
            "n_sin_comparar": sin_comparar, "n_mismo_veredicto": concordantes,
            "concordancia": None if not comparables else concordantes / comparables,
            "concordancia_ic": estadistica.texto_intervalo(ic),
            "n_casos_tokens": len(var_tokens),
            "tokens_variacion_media_pct": media(var_tokens),
            "tokens_variacion_max_pct": max(var_tokens) if var_tokens else None,
            "n_casos_tiempo": len(var_tiempo),
            "tiempo_variacion_media_pct": media(var_tiempo),
            "tiempo_variacion_max_pct": max(var_tiempo) if var_tiempo else None,
        })
    return _tabla(
        "Consistencia entre repeticiones", "11.1",
        [("dataset", "Dataset"), ("arquitectura", "Arquitectura"),
         ("n_casos", "Casos", "entero"), ("n_comparables", "Con veredicto en ≥ 2 repeticiones", "entero"),
         ("n_sin_comparar", "Sin comparar", "entero"),
         ("n_mismo_veredicto", "Mismo veredicto", "entero"),
         ("concordancia", "Concordancia de veredicto", "proporcion"),
         ("concordancia_ic", "IC 95 % (Wilson)"),
         ("tokens_variacion_media_pct", "Variación de tokens, media (%)", "numero"),
         ("tokens_variacion_max_pct", "Variación de tokens, máx. (%)", "numero"),
         ("tiempo_variacion_media_pct", "Variación de tiempo, media (%)", "numero"),
         ("tiempo_variacion_max_pct", "Variación de tiempo, máx. (%)", "numero")],
        filas,
        "Por caso: (máximo − mínimo) / media entre sus repeticiones. «Sin comparar»: casos con menos "
        "de 2 repeticiones con veredicto (una repetición fallida no se compara ni se cuenta como "
        "discrepancia). Temperatura 0 no garantiza respuestas idénticas.",
        _aviso_muestras_chicas([{"n_evaluables": f["n_comparables"]} for f in filas]),
    )


HERRAMIENTAS_EXTERNAS = ("abuseipdb", "nvd")


def tabla_consultas_externas(registros, consultas_por_run: dict) -> dict:
    """Intentos de consulta externa (AbuseIPDB, NVD) por arquitectura y dataset.

    Insumo para decidir, con datos, si la campaña final corre con consultas reales o con
    respaldo local (decisión PENDIENTE). En el piloto las llamadas HTTP se bloquean y
    responde el respaldo local; esto cuenta cuántas veces NODEX lo intentó.

    Solo NODEX usa herramientas: para Gemini directo y el baseline las celdas NO APLICAN
    (`None`), no valen 0. Si ninguna corrida del grupo tiene registro (corridas
    anteriores a este registro), también son `None`: «no se midió» no es «cero intentos».
    """
    filas = []
    for (dataset, arquitectura), grupo in sorted(_grupos(registros).items()):
        for herramienta in HERRAMIENTAS_EXTERNAS:
            # `estado` es una palabra corta («no aplica», «sin registro», «medido»): el
            # texto largo va en la descripción de la tabla, no en cada fila.
            base = {"dataset": dataset, "arquitectura": arquitectura, "herramienta": herramienta,
                    "n_corridas": len(grupo), "n_con_registro": None, "n_corridas_con_intentos": None,
                    "n_consultas": None, "n_intentos_externos": None, "n_bloqueados": None,
                    "n_respaldo_respondio": None, "n_sin_reputacion": None,
                    "estado": "no aplica"}
            if arquitectura != "nodex_multiagente":
                filas.append(base)
                continue
            listas = [consultas_por_run.get(r.run_id) for r in grupo]
            con_registro = [l for l in listas if l is not None]
            if not con_registro:
                filas.append({**base, "estado": "sin registro"})
                continue
            propias = [[c for c in l if c.get("herramienta") == herramienta] for l in con_registro]
            todas = [c for l in propias for c in l]
            filas.append({
                **base, "n_con_registro": len(con_registro),
                "n_corridas_con_intentos": sum(
                    1 for l in propias if any(c.get("intento_externo") for c in l)),
                "n_consultas": len(todas),
                "n_intentos_externos": sum(1 for c in todas if c.get("intento_externo")),
                "n_bloqueados": sum(1 for c in todas if c.get("bloqueado")),
                "n_respaldo_respondio": sum(1 for c in todas if c.get("respaldo_respondio")),
                # Consultas que el modo «sin reputación externa» contestó sin consultar nada.
                "n_sin_reputacion": sum(1 for c in todas if c.get("sin_reputacion")),
                "estado": "medido",
            })
    columnas = [
        ("dataset", "Dataset"), ("arquitectura", "Arquitectura"), ("herramienta", "Herramienta"),
        ("n_corridas", "Corridas", "entero"), ("n_con_registro", "Con registro", "entero"),
        ("n_corridas_con_intentos", "Corridas con intentos", "entero"),
        ("n_consultas", "Consultas a la herramienta", "entero"),
        ("n_intentos_externos", "Intentos de salida a la red", "entero"),
        ("n_bloqueados", "Bloqueados", "entero"),
        ("n_respaldo_respondio", "Respondió el respaldo local", "entero"),
        ("n_sin_reputacion", "Sin reputación (modo)", "entero"),
        ("estado", "Estado"),
    ]
    return _tabla(
        "Intentos de consulta externa (NVD, AbuseIPDB)", "11.5", columnas, filas,
        "Para decidir con datos la política de consultas externas de la campaña final "
        "(decisión pendiente; cualquiera que se elija debe declararse en el informe). En el "
        "piloto las llamadas HTTP se bloquean y responde el respaldo local. Estado «no aplica»: "
        "la arquitectura no usa herramientas externas (Gemini directo, baseline). «Sin "
        "registro»: corridas anteriores a este registro. Ninguno de los dos es lo mismo que 0 "
        "intentos.")


def tabla_comparacion(t_d1, t_d2, t_d3, t_consumo) -> dict:
    """NODEX frente al baseline y a Gemini directo (sección 11.6)."""
    arqs = ("nodex_multiagente", "baseline_reglas", "gemini_externo")

    def valor(tabla, dataset, arq, clave):
        for f in tabla["filas"]:
            if f["dataset"] == dataset and f["arquitectura"] == arq:
                return f.get(clave)
        return None

    metricas = [
        ("D1_precision", t_d1, "precision"), ("D1_recall", t_d1, "recall"),
        ("D1_f1", t_d1, "f1"), ("D2_f1", t_d2, "micro_f1"),
        ("D2_exact_match", t_d2, "exact_match"), ("D3_f1", t_d3, "micro_f1"),
        ("D3_exact_match", t_d3, "exact_match"),
        ("tiempo_medio_s", t_consumo, "tiempo_medio_s"),
    ]
    datasets = sorted({f["dataset"] for t in (t_d1, t_d2, t_d3, t_consumo) for f in t["filas"]})
    filas = []
    for dataset in datasets:
        for nombre, tabla, clave in metricas:
            valores = {a: valor(tabla, dataset, a, clave) for a in arqs}
            if all(v is None for v in valores.values()):
                continue
            if nombre.startswith("D1") and dataset == "uwf":
                tipo = "contextual"
                nota = ("El baseline responde la pregunta operativa y UWF pregunta por "
                        "actividad maliciosa: la comparación con el baseline no es pareada.")
            elif nombre.startswith("D1"):
                tipo = "pareada"
                nota = "NODEX y el baseline responden la misma pregunta."
            elif nombre.startswith(("D2", "D3")):
                tipo = "sin baseline"
                nota = "El baseline no produce esta salida: no aplica."
            else:
                tipo = "sistema completo vs modelo"
                nota = ("Gemini directo no usa RAG ni herramientas, por diseño: compara el "
                        "sistema completo con el modelo, no una sola variable.")
            filas.append({"dataset": dataset, "metrica": nombre, **valores,
                          "comparable": tipo, "nota": nota})
    return _tabla(
        "NODEX frente al baseline y a Gemini directo", "11.6",
        [("dataset", "Dataset"), ("metrica", "Métrica"),
         ("nodex_multiagente", "NODEX", "proporcion"),
         ("baseline_reglas", "Baseline", "proporcion"),
         ("gemini_externo", "Gemini directo", "proporcion"),
         ("comparable", "Tipo de comparación"), ("nota", "Nota")],
        filas,
        "Sin umbrales de aprobado: se comparan las arquitecturas entre sí y se "
        "describe cada resultado. Una celda vacía es «no aplica o sin dato».",
    )


def tabla_errores(registros) -> dict:
    filas = [
        {"run_id": r.run_id, "case_id": r.case_id, "dataset": r.dataset,
         "condicion": r.condicion, "arquitectura": r.arquitectura,
         "repeticion": r.repeticion, "resultado": r.resultado_d1,
         "prediccion": r.prediccion, "referencia": r.referencia}
        for r in sorted(registros, key=lambda r: r.run_id)
        if r.resultado_d1 in ("FP", "FN")
    ]
    return _tabla(
        "Falsos positivos y falsos negativos", "11.7",
        [("run_id", "Corrida"), ("dataset", "Dataset"), ("condicion", "Condición"),
         ("arquitectura", "Arquitectura"), ("repeticion", "Rep.", "entero"),
         ("resultado", "Tipo"), ("prediccion", "Predicción"), ("referencia", "Referencia")],
        filas,
        "FP: el sistema afirmó actividad que la referencia no tiene. FN: la referencia "
        "la tiene y el sistema no la detectó.",
    )


# --- integridad --------------------------------------------------------------

def construir_integridad(
    resultado: ResultadoEvaluacion,
    telemetrias: dict,
    fallos: list[dict],
    principal: str | None,
    filas_rubrica_invalidas: list[dict],
    datos_ficticios: bool,
    depuracion: bool = False,
    consultas_externas: dict | None = None,
) -> dict:
    ids_con_fallo = {f["run_id"] for f in fallos}
    ausentes_puras = [r for r in resultado.ausentes if r not in ids_con_fallo]
    fallidas = [
        {"run_id": f["run_id"], "estado": f.get("estado"), "error": f.get("error")}
        for f in fallos if f["run_id"] in resultado.ausentes
    ] + [
        {"run_id": r.run_id, "estado": r.estado_ejecucion, "error": None}
        for r in resultado.registros
        if r.estado_ejecucion not in (ESTADO_COMPLETA, None)
    ]
    llm = [r for r in resultado.registros if r.arquitectura != "baseline_reglas"]
    con_llamadas = [r for r in llm if modelos_de_la_corrida(telemetrias.get(r.run_id))]
    con_fallback = [r.run_id for r in llm
                    if uso_fallback(telemetrias.get(r.run_id), principal) is True]
    previas = sum(1 for r in llm
                  if (telemetrias.get(r.run_id) or {}).get("previa_a_d11") is True)
    sin_tokens = sum(
        1 for r in llm if r.estado_ejecucion == ESTADO_COMPLETA
        and (telemetrias.get(r.run_id) or {}).get("total_tokens") is None)
    # De esas, las que tienen una suma parcial que mostrar (alguna llamada informó).
    parciales = [
        {"run_id": r.run_id,
         "n_llamadas": (d := tokens_de_la_corrida(telemetrias.get(r.run_id)))["n_llamadas"],
         "n_con_tokens": d["n_con_tokens"], "n_llamadas_fallidas": d["n_fallidas"],
         "tokens_entrada_parcial": d["entrada"], "tokens_salida_parcial": d["salida"],
         "tokens_razonamiento_parcial": d["razonamiento"]}
        for r in llm if r.estado_ejecucion == ESTADO_COMPLETA
        and es_parcial(telemetrias.get(r.run_id))]
    completas_llm = [r for r in llm if r.estado_ejecucion == ESTADO_COMPLETA]
    sin_razonamiento = sum(
        1 for r in completas_llm
        if (telemetrias.get(r.run_id) or {}).get("reasoning_tokens") is None)
    sin_version = sum(
        1 for r in completas_llm
        if not (telemetrias.get(r.run_id) or {}).get("modelos_efectivos"))
    sin_meta = sum(1 for r in resultado.registros if r.sin_metadatos_de_ejecucion)
    determinable = principal is not None or not con_llamadas

    def aviso(codigo, severidad, mensaje, n):
        return {"codigo": codigo, "severidad": severidad, "mensaje": mensaje, "n": n}

    avisos = []
    if datos_ficticios:
        avisos.append(aviso("datos_ficticios", "alta", "datos ficticios de prueba", 0))
    omisiones = sum(1 for r in resultado.registros if r.omision_d2 or r.omision_d3)
    if omisiones:
        avisos.append(aviso(
            "omisiones_d2_d3", "info",
            "corridas válidas en que el sistema no entregó eventos o técnicas habiendo referencia: "
            "cuentan como omisión (exhaustividad 0), no salen de la métrica (regla v2, 15-oct-2026)",
            omisiones))
    if depuracion:
        avisos.append(aviso(
            "resultados_de_depuracion", "alta",
            "resultados de DEPURACIÓN (desarrollo/piloto): no son reportables ni se citan "
            "en el informe", 0))
    bloqueados = sum(
        1 for l in (consultas_externas or {}).values() for c in (l or []) if c.get("bloqueado"))
    if bloqueados:
        avisos.append(aviso(
            "consultas_externas_bloqueadas", "info",
            "intentos de consulta a NVD/AbuseIPDB bloqueados, con respaldo local "
            "(política de la campaña final pendiente)", bloqueados))
    if ausentes_puras:
        avisos.append(aviso("corridas_ausentes", "alta",
                            "corridas esperadas que no están guardadas", len(ausentes_puras)))
    if fallidas:
        avisos.append(aviso("corridas_fallidas", "alta",
                            "corridas fallidas", len(fallidas)))
    if con_fallback:
        avisos.append(aviso("fallback_de_modelo", "alta",
                            "corridas que respondió el modelo de respaldo; no son comparables",
                            len(con_fallback)))
    if not determinable:
        avisos.append(aviso("fallback_no_determinable", "media",
                            "sin configuración congelada: no se puede saber si hubo fallback",
                            len(con_llamadas)))
    if previas:
        avisos.append(aviso("telemetria_previa_a_d11", "media",
                            "telemetría tomada antes de integrar D-11; no mezclar con la posterior",
                            previas))
    if sin_tokens - len(parciales):
        avisos.append(aviso("tokens_no_informados", "media",
                            "corridas completas sin tokens informados",
                            sin_tokens - len(parciales)))
    if parciales:
        avisos.append(aviso(
            "tokens_parciales", "media",
            "corridas completas con el total de tokens en None porque una llamada falló "
            "(o no informó): solo se conoce una suma parcial, que es un piso; quedan "
            "fuera de las medias de tokens", len(parciales)))
    if sin_razonamiento:
        avisos.append(aviso("razonamiento_no_informado", "info",
                            "corridas completas sin tokens de razonamiento informados "
                            "(no son 0: el proveedor no los entregó)", sin_razonamiento))
    if sin_version:
        avisos.append(aviso("version_de_modelo_no_informada", "info",
                            "corridas completas sin la versión que devolvió la API: "
                            "no se puede probar qué versión respondió", sin_version))
    if sin_meta:
        avisos.append(aviso("sin_metadatos_de_ejecucion", "alta",
                            "corridas guardadas sin metadatos de ejecución: sus dimensiones "
                            "figuran como no evaluables", sin_meta))
    if filas_rubrica_invalidas:
        avisos.append(aviso("rubrica_filas_invalidas", "media",
                            "filas de la rúbrica inválidas, descartadas y declaradas",
                            len(filas_rubrica_invalidas)))

    return {
        "corridas_esperadas": resultado.esperadas,
        "corridas_presentes": len(resultado.registros),
        "corridas_completas": sum(
            1 for r in resultado.registros if r.estado_ejecucion == ESTADO_COMPLETA),
        "corridas_ausentes": ausentes_puras,
        "corridas_fallidas": fallidas,
        "corridas_con_fallback": con_fallback,
        "fallback_determinable": determinable,
        "modelo_principal": principal,
        "corridas_con_telemetria_previa_a_d11": previas,
        "corridas_sin_tokens": sin_tokens,
        "corridas_con_tokens_parciales": parciales,
        "corridas_sin_razonamiento": sin_razonamiento,
        "corridas_sin_version_de_modelo": sin_version,
        "advertencias": avisos,
    }


# --- escritura ---------------------------------------------------------------

def _csv_tabla(ruta: Path, tabla: dict) -> None:
    claves = [c["clave"] for c in tabla["columnas"]]
    with ruta.open("w", encoding="utf-8-sig", newline="") as f:
        escritor = csv.writer(f, lineterminator="\r\n")
        escritor.writerow(claves)
        for fila in tabla["filas"]:
            escritor.writerow([
                "" if fila.get(k) is None else fila.get(k) for k in claves
            ])


def consolidar(
    raiz_repo: Path,
    subconjunto: str,
    config_version: str,
    arquitecturas: tuple[str, ...] = ARQUITECTURAS_CAMPANA,
    raiz_destino: Path | None = None,
    marca: str | None = None,
    datos_ficticios: bool = False,
    depuracion: bool | None = None,
    repeticiones: int | None = None,
) -> Path:
    """Consolida una campaña y devuelve el directorio escrito.

    `repeticiones`: ver `evaluar_corridas` (la evaluación manual lo usa).

    `depuracion`: marca los resultados como de DEPURACIÓN (no reportables). Por omisión es
    `True` para cualquier partición que no sea `evaluacion`: el desarrollo y el piloto
    existen para depurar, y sus cifras no se citan en el informe.

    No ejecuta nada ni llama a ningún modelo: lee lo guardado. Falla si el
    directorio de esa consolidación ya existe.
    """
    marca = marca or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destino = (raiz_destino or raiz_repo) / "experiments" / "metrics" / config_version / marca
    if destino.exists():
        raise FileExistsError(
            f"{destino} ya existe. Las consolidaciones no se sobrescriben")

    resultado = evaluar_corridas(raiz_repo, subconjunto, config_version, arquitecturas,
                                 repeticiones=repeticiones)
    registros = resultado.registros

    if depuracion is None:
        depuracion = resultado.particion != "evaluacion"
    telemetrias: dict[str, dict | None] = {}
    consultas_externas: dict[str, list | None] = {}
    for r in registros:
        identidad = IdentidadCorrida(r.case_id, r.dataset, r.arquitectura,
                                     r.repeticion, config_version)
        consultas_externas[r.run_id] = persistencia.leer_consultas_externas(identidad, raiz_repo)
        tel = persistencia.leer_telemetria(identidad, raiz_repo)
        if tel is not None:
            # Las corridas guardadas antes de esta instrumentación no traen
            # estos campos: se derivan de `llm_calls` si existe, y si no, quedan
            # en `None` (no se inventan).
            tel = dict(tel)
            for clave, valor in campos_de_modelo(tel).items():
                tel.setdefault(clave, valor)
        telemetrias[r.run_id] = tel

    fallos = ultimo_fallo_por_corrida(persistencia.leer_fallos(raiz_repo, config_version))
    # Solo los fallos de corridas que no llegaron a guardar una salida: si una
    # corrida falló y luego se reintentó con éxito, el fallo es historia.
    fallos_sin_salida = [f for f in fallos if f["run_id"] in set(resultado.ausentes)]
    principal = modelo_principal_congelado(raiz_repo, config_version)
    puntuaciones, rubrica_invalida = leer_rubrica(raiz_repo, config_version)

    t_d1, t_d1c, c_d1 = tabla_d1(registros)
    t_d2, c_d2 = _tabla_conjuntos(registros, "reconstruccion", "11.2",
                                  "Reconstrucción del incidente")
    t_d3, c_d3 = _tabla_conjuntos(registros, "mitre", "11.3",
                                  "Identificación MITRE ATT&CK (nivel técnica)")
    t_d4, c_d4 = tabla_d4(puntuaciones, registros)
    t_con, c_con = tabla_consumo(registros, telemetrias, fallos_sin_salida, principal)
    t_ext = tabla_consultas_externas(registros, consultas_externas)
    t_cons = tabla_consistencia(registros, telemetrias)
    t_cmp = tabla_comparacion(t_d1, t_d2, t_d3, t_con)
    t_err = tabla_errores(registros)
    tablas = {
        "d1_deteccion": t_d1, "d1_condiciones": t_d1c,
        "d2_reconstruccion": t_d2, "d3_mitre": t_d3, "d4_rubrica": t_d4,
        "consumo": t_con, "consultas_externas": t_ext, "consistencia_repeticiones": t_cons,
        "comparacion": t_cmp,
        "errores_d1": t_err,
    }

    integridad = construir_integridad(
        resultado, telemetrias, fallos, principal, rubrica_invalida, datos_ficticios,
        depuracion=depuracion, consultas_externas=consultas_externas)

    resumen = {
        "esquema": ESQUEMA_RESULTADOS,
        "datos_ficticios": datos_ficticios,
        # De DEPURACIÓN: no reportable. Se muestra con una advertencia en la vista.
        "depuracion": depuracion,
        "reportable": not depuracion and not datos_ficticios,
        "config_version": config_version,
        "consolidacion": marca,
        "generado_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "protocolo_version": PROTOCOLO_VERSION,
        # Reglas de evaluación que cambian lo que significa una cifra, con su versión y fecha.
        "reglas_de_evaluacion": {"d2_d3": REGLA_D2_D3},
        "subconjunto": subconjunto,
        "particion": resultado.particion,
        "arquitecturas": list(arquitecturas),
        "integridad": integridad,
        "tablas": tablas,
    }

    destino.mkdir(parents=True, exist_ok=False)
    (destino / "resumen.json").write_text(
        json.dumps(resumen, indent=2, ensure_ascii=False), encoding="utf-8")
    for nombre, tabla in tablas.items():
        _csv_tabla(destino / f"{nombre}.csv", tabla)
    (destino / "registros.json").write_text(
        json.dumps([r.to_dict() for r in registros], indent=2, ensure_ascii=False),
        encoding="utf-8")

    # Tabla plana del §14, una fila por corrida, con el esquema exacto del plan.
    puntajes_por_reporte: dict = {}
    for p in puntuaciones:
        puntajes_por_reporte.setdefault((p.case_id, p.arquitectura), {})[p.evaluador] = p.puntajes
    filas14 = []
    for r in registros:
        tel = dict(telemetrias.get(r.run_id) or {})
        tel["uso_fallback"] = uso_fallback(tel, principal) is True
        tel["previa_a_d11"] = bool(tel.get("previa_a_d11", True))
        comp2 = evaluar_conjuntos([r.comparacion_d2]).micro if r.comparacion_d2 else None
        comp3 = evaluar_conjuntos([r.comparacion_d3]).micro if r.comparacion_d3 else None
        filas14.append(exportacion.fila(
            identidad={"case_id": r.case_id, "dataset": r.dataset,
                       "arquitectura": r.arquitectura, "repeticion": r.repeticion,
                       "config_version": config_version},
            estados={**r.estados, "reporte": "referencia_pendiente",
                     "consumo": "evaluable" if tel else "no_evaluable"},
            deteccion={"prediccion": r.prediccion, "outcome": r.resultado_d1},
            reconstruccion=({**comp2, "coincide_exacto": r.comparacion_d2.coincide_exacto}
                            if comp2 else None),
            mitre=({**comp3, "coincide_exacto": r.comparacion_d3.coincide_exacto,
                    "nivel": "tecnica"} if comp3 else None),
            reporte=puntajes_por_reporte.get((r.case_id, r.arquitectura)),
            telemetria=tel,
            status=r.estado_ejecucion or "desconocido",
        ))
    exportacion.escribir_csv(filas14, destino / "tabla_14.csv")

    escribir_resultado(c_d1 + c_d2 + c_d3 + c_d4 + c_con, destino,
                       detalle={"integridad": integridad}, etiqueta="contrato", marca=marca)
    return destino


# --- línea de comandos -------------------------------------------------------------

def main(argv: list[str] | None = None, raiz_repo: Path | None = None) -> int:
    """`python -m src.experimentation.consolidacion --subconjunto X --config Y`.

    Solo LEE lo guardado: no ejecuta arquitecturas ni llama a ningún modelo.
    Se niega a crear una consolidación cuando no hay ninguna corrida guardada
    ni ningún fallo registrado, para no dejar carpetas vacías en
    `experiments/metrics/` por una invocación accidental.
    """
    import argparse

    analizador = argparse.ArgumentParser(
        prog="python -m src.experimentation.consolidacion",
        description="Consolida las corridas guardadas en tablas para el informe.",
    )
    analizador.add_argument("--subconjunto", required=True,
                            help="nombre del subconjunto: piloto, rubrica, evaluacion")
    analizador.add_argument("--config", required=True,
                            help="config_version de las corridas a consolidar")
    analizador.add_argument("--arquitecturas", nargs="+", default=list(ARQUITECTURAS_CAMPANA),
                            help="por omisión: NODEX y el baseline")
    analizador.add_argument("--marca", default=None,
                            help="marca de la consolidación (por omisión, la hora UTC)")
    args = analizador.parse_args(argv)

    raiz = raiz_repo or Path(__file__).resolve().parents[2]
    arquitecturas = tuple(args.arquitecturas)

    previa = evaluar_corridas(raiz, args.subconjunto, args.config, arquitecturas)
    hay_fallos = bool(persistencia.leer_fallos(raiz, args.config))
    if not previa.registros and not hay_fallos:
        print(f"No hay corridas guardadas de {args.config!r} para el subconjunto "
              f"{args.subconjunto!r} ({previa.esperadas} esperadas, todas ausentes). "
              "No se crea ninguna consolidación.")
        return 2

    destino = consolidar(raiz, args.subconjunto, args.config, arquitecturas, marca=args.marca)
    resumen = json.loads((destino / "resumen.json").read_text(encoding="utf-8"))
    i = resumen["integridad"]
    print(f"Consolidación escrita en {destino}")
    print(f"  corridas: {i['corridas_presentes']} presentes de {i['corridas_esperadas']} "
          f"esperadas | completas {i['corridas_completas']} | ausentes "
          f"{len(i['corridas_ausentes'])} | fallidas {len(i['corridas_fallidas'])}")
    for aviso in i["advertencias"]:
        print(f"  [{aviso['severidad']}] {aviso['mensaje']} ({aviso['n']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
