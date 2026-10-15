"""Salud ESTRUCTURAL de una campaña: ¿las salidas tienen la forma que el contrato espera?

No mide acierto. Cuenta, por arquitectura y dataset, cuántas salidas son estructuralmente
usables: JSON válido, veredicto presente, D2 y D3 con contenido, evidencia inválida, y la
matriz de confusión de D1 **solo como diagnóstico** (no como resultado).

Solo LEE lo guardado:

- las salidas, el estado crudo y la telemetría de cada corrida (`persistencia`);
- `registros.json` de una consolidación ya hecha (de ahí salen D1 y los uids inventados).

**No abre `ground_truth/`**: la referencia solo la lee `evaluacion.py` (que produjo ese
`registros.json`). No ejecuta ninguna arquitectura ni llama a ningún modelo.

## Qué se puede y qué no se puede afirmar de «JSON válido»

- **Gemini directo:** su runner parsea la respuesta del modelo; si no era un objeto JSON queda
  un error en su diagnóstico. Se informa el porcentaje real.
- **NODEX:** el JSON lo valida `llm_json()` en cada nodo, y el lanzador del piloto NO contaba las
  respuestas inválidas. No hay medición directa: se informa `None` y, aparte, un *proxy*
  (la corrida terminó completa y con veredicto), que NO es lo mismo.
- **Baseline:** no usa el modelo; no aplica.
"""

from __future__ import annotations

import json
from pathlib import Path

from src.experimentation import orquestador
from src.experimentation.runtime import persistencia
from src.experimentation.runtime.identidad import IdentidadCorrida

RESULTADOS_D1 = ("TP", "FP", "FN", "TN", "NA")


def _ultima_consolidacion(raiz_repo: Path, config_version: str, marca: str | None) -> Path:
    base = raiz_repo / "experiments" / "metrics" / config_version
    carpetas = sorted(p for p in base.iterdir() if p.is_dir()) if base.is_dir() else []
    if marca:
        carpetas = [p for p in carpetas if p.name == marca]
    if not carpetas:
        raise FileNotFoundError(f"no hay consolidación de {config_version} en {base}")
    return carpetas[-1]


def _leer_json(ruta: Path) -> dict | None:
    return json.loads(ruta.read_text(encoding="utf-8")) if ruta.is_file() else None


def _filas(raiz_repo: Path, subconjunto: str, config_version: str,
           arquitecturas: tuple[str, ...], marca: str | None) -> tuple[list[dict], str]:
    consolidacion = _ultima_consolidacion(raiz_repo, config_version, marca)
    registros = {r["run_id"]: r for r in json.loads(
        (consolidacion / "registros.json").read_text(encoding="utf-8"))}
    sub = orquestador.cargar_subconjunto(raiz_repo, subconjunto)
    if sub["particion"] == "evaluacion":
        raise ValueError(
            "la salud estructural del piloto es SOLO de casos de desarrollo: este subconjunto "
            "es de la partición de evaluación")
    plan = orquestador.planificar(raiz_repo, sub, config_version, arquitecturas)
    filas = []
    for entrada in plan.corridas + plan.ya_hechas:
        ident = IdentidadCorrida(entrada["case_id"], entrada["dataset"], entrada["arquitectura"],
                                 entrada["repeticion"], config_version)
        rutas = persistencia.rutas(ident, raiz_repo)
        guardado = _leer_json(rutas.salida)
        crudo = (_leer_json(rutas.crudo) or {}).get("estado_crudo") or {}
        tel = persistencia.leer_telemetria(ident, raiz_repo) or {}
        reg = registros.get(ident.run_id) or {}
        if guardado is None:
            filas.append({**entrada, "run_id": ident.run_id, "guardada": False})
            continue
        salida, ejec = guardado.get("salida") or {}, guardado.get("ejecucion") or {}
        estados = ejec.get("estados_por_dimension") or {}
        diag = tel.get("diagnostico_runner") or {}
        mitre = salida.get("mitre") or {}
        arq = ident.arquitectura
        if arq == "gemini_externo":
            json_valido = not diag.get("error")
        else:
            json_valido = None          # NODEX: no medido; baseline: no aplica
        filas.append({
            "run_id": ident.run_id, "case_id": ident.case_id, "dataset": ident.dataset,
            "arquitectura": arq, "guardada": True,
            "estado_ejecucion": ejec.get("estado"),
            "json_valido": json_valido,
            "proxy_json_valido": ejec.get("estado") == "completa" and bool(
                (salida.get("_meta") or {}).get("veredicto_booleano_presente")),
            "veredicto_presente": bool((salida.get("_meta") or {}).get("veredicto_booleano_presente")),
            # Estado FINAL (el de las métricas: la salida cruzada con la referencia). El del
            # lado de la salida va aparte: dice si el sistema produjo algo que puntuar.
            "estado_d2": (reg.get("estados") or {}).get("reconstruccion", estados.get("reconstruccion")),
            "estado_d3": (reg.get("estados") or {}).get("mitre", estados.get("mitre")),
            "estado_d2_salida": estados.get("reconstruccion"),
            "estado_d3_salida": estados.get("mitre"),
            "d2_con_contenido": bool(salida.get("reconstructed_events")),
            "d3_con_contenido": bool(mitre.get("techniques") or mitre.get("tactics")),
            "n_eventos": len(salida.get("reconstructed_events") or []),
            "n_tecnicas": len(mitre.get("techniques") or []),
            "invalid_evidence_uid_count": (
                tel.get("invalid_evidence_uid_count") if arq == "nodex_multiagente" else None),
            "uids_inventados_d2": reg.get("uids_inventados_d2"),
            "resultado_d1": reg.get("resultado_d1"),
            "prediccion_d1": reg.get("prediccion"),
            "d11_warnings": len(crudo.get("d11_warnings") or []),
        })
    return filas, consolidacion.name


def _pct(n: int, total: int) -> float | None:
    return None if total == 0 else round(100 * n / total, 1)


def resumir(filas: list[dict]) -> list[dict]:
    """Agrega por (arquitectura, dataset). Cada porcentaje lleva su denominador."""
    grupos: dict[tuple, list[dict]] = {}
    for f in filas:
        grupos.setdefault((f["arquitectura"], f["dataset"]), []).append(f)
    salida = []
    for (arq, ds), g in sorted(grupos.items()):
        guardadas = [f for f in g if f.get("guardada")]
        n = len(guardadas)
        usa_modelo = arq != "baseline_reglas"
        d1 = {k: sum(1 for f in guardadas if f["resultado_d1"] == k) for k in RESULTADOS_D1}
        validos = [f["json_valido"] for f in guardadas if f["json_valido"] is not None]
        salida.append({
            "arquitectura": arq, "dataset": ds, "corridas": len(g), "guardadas": n,
            "completas": sum(1 for f in guardadas if f["estado_ejecucion"] == "completa"),
            "json_valido_pct": _pct(sum(validos), len(validos)) if validos else None,
            "json_valido_n": f"{sum(validos)}/{len(validos)}" if validos else None,
            "proxy_json_valido_pct": _pct(sum(f["proxy_json_valido"] for f in guardadas), n)
            if usa_modelo else None,
            "veredicto_presente_pct": _pct(sum(f["veredicto_presente"] for f in guardadas), n),
            "veredicto_presente_n": f"{sum(f['veredicto_presente'] for f in guardadas)}/{n}",
            "d2_evaluable": sum(1 for f in guardadas if f["estado_d2"] == "evaluable"),
            "d2_no_evaluable": sum(1 for f in guardadas if f["estado_d2"] not in ("evaluable", "no_aplica")),
            "d2_no_aplica": sum(1 for f in guardadas if f["estado_d2"] == "no_aplica"),
            "d2_con_contenido": sum(1 for f in guardadas if f["d2_con_contenido"]),
            "d3_evaluable": sum(1 for f in guardadas if f["estado_d3"] == "evaluable"),
            "d3_no_evaluable": sum(1 for f in guardadas if f["estado_d3"] not in ("evaluable", "no_aplica")),
            "d3_no_aplica": sum(1 for f in guardadas if f["estado_d3"] == "no_aplica"),
            "d3_con_contenido": sum(1 for f in guardadas if f["d3_con_contenido"]),
            "invalid_uid_contador_mayor_que_0": (
                sum(1 for f in guardadas if (f["invalid_evidence_uid_count"] or 0) > 0)
                if arq == "nodex_multiagente" else None),
            "uids_inventados_d2_mayor_que_0": (
                sum(1 for f in guardadas if (f["uids_inventados_d2"] or 0) > 0)
                if usa_modelo else None),
            "d1": d1,
            "d1_prediccion_maligna": sum(1 for f in guardadas if f["prediccion_d1"] == "MALICIOUS"),
        })
    return salida


def analizar(raiz_repo: Path, subconjunto: str, config_version: str,
             arquitecturas: tuple[str, ...], marca: str | None = None) -> dict:
    """Salud estructural de las corridas guardadas. Devuelve filas y resumen."""
    filas, consolidacion = _filas(raiz_repo, subconjunto, config_version, arquitecturas, marca)
    return {
        "config_version": config_version, "subconjunto": subconjunto,
        "consolidacion": consolidacion,
        "aviso": ("diagnóstico estructural de corridas de DESARROLLO; no es un resultado "
                  "reportable ni mide acierto"),
        "resumen": resumir(filas), "filas": filas,
    }
