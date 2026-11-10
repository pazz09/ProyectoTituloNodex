"""Formulario CIEGO de la rúbrica humana (D4). Decisión D-4: 0 a 3 por criterio, 2 evaluadores.

Lo que garantiza, y cómo:

- **Ciego a la arquitectura.** Los reportes se normalizan a una misma plantilla, se limpian de
  nombres de arquitecturas y modelos, y se AUDITAN: si queda alguno, el paquete no se arma. Cada
  evaluador recibe un archivo con sus reportes identificados solo por su posición (R01, R02...);
  la correspondencia con caso y arquitectura vive en una clave aparte.
- **Orden aleatorio con semilla registrada.** Cada evaluador tiene su propio orden, sacado de
  `Random(f"{semilla}:{evaluador}")`. La semilla va en la clave y solo un COMPROMISO (hash) va en
  el paquete: conocer la semilla permitiría reconstruir qué reporte es cuál.
- **Evaluadores independientes.** Cada uno recibe un HTML autocontenido con SUS reportes y nada
  del otro; exporta un JSON propio. La importación exige archivos de evaluadores distintos y del
  mismo paquete, y rechaza cualquier puntaje incompleto o fuera de la escala.
- **Concordancia sin kappa:** acuerdo exacto, acuerdo hasta un nivel y diferencia absoluta media
  (los de `evaluators/reporte.py`). Elegir un kappa es una decisión metodológica pendiente.

El desciegue (asociar puntajes con arquitectura) ocurre SOLO en `importar_puntajes`, con la clave.

Este módulo no lee salidas de ninguna campaña ni `ground_truth/`: recibe los reportes ya
armados. Quien los prepare decide qué contexto del caso se muestra a los evaluadores.
"""

from __future__ import annotations

import csv
import hashlib
import html
import json
import random
import re
from dataclasses import dataclass
from pathlib import Path

from src.experimentation.evaluators.reporte import (
    CRITERIOS,
    PUNTAJE_MAXIMO,
    PUNTAJE_MINIMO,
    PuntuacionRubrica,
    agregar,
)

EVALUADORES = ("E1", "E2")

#: Términos que delatan la arquitectura o el modelo. Se limpian y luego se audita que no quede
#: ninguno. La lista es deliberadamente amplia: un falso positivo cuesta una palabra redactada. («reglas»
#: no está: el baseline no produce reportes, y esa palabra es común en un reporte legítimo.)
TERMINOS_REVELADORES = (
    "nodex", "gemini", "baseline", "multiagente", "multi-agente", "langgraph", "flash",
    "planificador", "auditor", "agente", "ingeniero de mitigación", "pseudo-ablación",
    "single_agent", "gemext",
)
REDACCION = "[redactado]"

#: Descriptores de cada nivel (docs/experimentacion/anotacion_ground_truth.md §5).
ETIQUETAS = {
    "completitud": "Completitud",
    "correccion_factual": "Corrección factual",
    "coherencia_con_evidencia": "Coherencia con la evidencia",
    "claridad": "Claridad",
    "informacion_no_sustentada": "Información no sustentada (3 = ninguna)",
}
DESCRIPTORES = {
    "completitud": [
        "No menciona el incidente ni los eventos núcleo",
        "Menciona el incidente pero omite la mayoría de los eventos núcleo",
        "Cubre el incidente y la mayoría de los eventos núcleo",
        "Cubre el incidente y todos los eventos núcleo relevantes"],
    "correccion_factual": [
        "Afirmaciones centrales falsas respecto del log",
        "Alguna afirmación central falsa",
        "Afirmaciones correctas con imprecisiones menores",
        "Todas las afirmaciones verificables contra el log son correctas"],
    "coherencia_con_evidencia": [
        "Las conclusiones no se siguen de lo citado",
        "Cita evidencia pero las conclusiones la exceden",
        "Conclusiones sostenidas, con algún salto",
        "Cada conclusión se apoya en evidencia citada"],
    "claridad": [
        "Ininteligible para un analista",
        "Requiere releer para entender qué pasó",
        "Comprensible en una lectura",
        "Comprensible y ordenado, útil tal como está"],
    "informacion_no_sustentada": [
        "Abundante contenido inventado",
        "Varias afirmaciones sin respaldo en el log",
        "Alguna afirmación sin respaldo",
        "Nada que no esté respaldado por el log"],
}


# --- reportes: plantilla común, limpieza y auditoría de ceguera --------------------------------

def texto_del_reporte(salida: dict) -> str:
    """Plantilla ÚNICA para todas las arquitecturas, a partir de la salida del contrato.

    Solo usa campos que el contrato comparte (resumen del reporte). Lo que falta se muestra
    igual para todas («No entregado»), para que ni siquiera la forma delate la arquitectura.
    """
    resumen = ((salida.get("report") or {}).get("summary") or "").strip()
    return resumen or "No entregado"


def sanear(texto: str) -> tuple[str, int]:
    """Redacta los términos reveladores. Devuelve el texto limpio y cuántos reemplazó."""
    total = 0
    for termino in sorted(TERMINOS_REVELADORES, key=len, reverse=True):
        texto, n = re.subn(re.escape(termino), REDACCION, texto, flags=re.IGNORECASE)
        total += n
    return texto, total


def auditar_ceguera(texto: str, extra: tuple[str, ...] = ()) -> list[str]:
    """Términos que delatan la arquitectura y siguen en `texto`. Vacío = a ciegas."""
    bajo = texto.lower()
    return sorted({t for t in (*TERMINOS_REVELADORES, *(e.lower() for e in extra if e)) if t in bajo})


# --- paquete ---------------------------------------------------------------------------------------

@dataclass(frozen=True)
class ReporteEntrada:
    case_id: str
    arquitectura: str
    run_id: str
    texto: str
    #: Contexto del caso que verá el evaluador (log, etc.). Lo arma quien llama.
    contexto: str = ""
    repeticion: int = 1


def _hash(texto: str) -> str:
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def preparar_paquete(reportes: list[ReporteEntrada], semilla: int, config_version: str,
                     evaluadores: tuple[str, ...] = EVALUADORES,
                     arquitecturas: tuple[str, ...] | None = None) -> dict:
    """Arma la clave y los paquetes por evaluador. No escribe nada.

    Devuelve `{"clave": ..., "paquetes": {evaluador: {...}}}`. `clave` es SECRETA: nunca se le
    da a un evaluador.
    """
    if len(evaluadores) != 2 or len(set(evaluadores)) != 2:
        raise ValueError("la rúbrica D-4 tiene dos evaluadores distintos")
    archs = tuple(arquitecturas or sorted({r.arquitectura for r in reportes}))
    por_caso: dict[str, dict] = {}
    for r in reportes:
        if r.arquitectura not in archs:
            raise ValueError(f"arquitectura inesperada: {r.arquitectura}")
        if r.arquitectura in por_caso.setdefault(r.case_id, {}):
            raise ValueError(f"reporte repetido: {r.case_id}/{r.arquitectura}")
        por_caso[r.case_id][r.arquitectura] = r
    for case_id, pares in sorted(por_caso.items()):
        faltan = set(archs) - set(pares)
        if faltan:
            raise ValueError(f"{case_id}: falta el reporte de {sorted(faltan)}")

    limpios: dict[tuple, dict] = {}
    for r in reportes:
        texto, redactados = sanear(r.texto)
        contexto, _ = sanear(r.contexto)
        limpios[(r.case_id, r.arquitectura)] = {
            "texto": texto, "contexto": contexto, "redactados": redactados, "entrada": r}
        # Auditoría sobre lo que verá el evaluador, incluidos los nombres de arquitectura reales
        # y el identificador de la corrida.
        filtracion = auditar_ceguera(texto + "\n" + contexto, extra=(r.arquitectura, r.run_id))
        if filtracion:
            raise ValueError(f"{r.case_id}: el paquete no sería ciego, quedan {filtracion}")

    claves = sorted(limpios)                       # orden determinista de partida
    paquete_id = _hash(json.dumps([claves, semilla, config_version]))[:16]
    clave_items = []
    paquetes = {}
    for evaluador in evaluadores:
        orden = list(claves)
        random.Random(f"{semilla}:{evaluador}").shuffle(orden)
        items = []
        for i, k in enumerate(orden, start=1):
            item_id = f"R{i:02d}"
            d = limpios[k]
            items.append({"id": item_id, "caso": k[0], "texto": d["texto"],
                          "contexto": d["contexto"]})
            clave_items.append({"evaluador": evaluador, "id": item_id, "case_id": k[0],
                                "arquitectura": k[1], "run_id": d["entrada"].run_id,
                                "repeticion": d["entrada"].repeticion})
        paquetes[evaluador] = {"paquete_id": paquete_id, "evaluador": evaluador,
                               "config_version": config_version, "items": items}
    clave = {
        "ADVERTENCIA": "SECRETA: no se entrega a los evaluadores. Desciega los puntajes.",
        "paquete_id": paquete_id, "config_version": config_version, "semilla": semilla,
        "compromiso_semilla": _hash(f"{semilla}:{paquete_id}"),
        "evaluadores": list(evaluadores), "arquitecturas": list(archs),
        "n_reportes": len(claves), "items": clave_items,
        "hash_de_la_clave": _hash(json.dumps(clave_items, sort_keys=True)),
    }
    return {"clave": clave, "paquetes": paquetes}


# --- el formulario (HTML autocontenido) ---------------------------------------------------------

_PLANTILLA = """<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Rúbrica de reportes — evaluador __EVALUADOR__</title>
<style>
body{font:15px/1.5 system-ui,sans-serif;margin:0;background:#f6f6f4;color:#1c1c1a}
header{position:sticky;top:0;background:#1c1c1a;color:#fff;padding:10px 20px;z-index:5}
header b{font-size:16px} header span{opacity:.75;margin-left:14px}
main{max-width:980px;margin:0 auto;padding:18px}
.item{background:#fff;border:1px solid #d6d6d0;border-radius:8px;margin:0 0 22px;padding:16px 18px}
.item.hecho{border-color:#3a7d44}.item h2{margin:0 0 8px;font-size:17px}
pre{white-space:pre-wrap;background:#fafaf7;border:1px solid #e4e4de;padding:12px;border-radius:6px}
table{border-collapse:collapse;width:100%;table-layout:fixed;margin-top:10px;font-size:13.5px}
th,td{border-top:1px solid #e4e4de;padding:6px 8px;text-align:left;vertical-align:top;overflow-wrap:break-word}
th{width:19%}td.n{width:20%}.desc{color:#55554f;font-size:12.5px}
@media (max-width:760px){main{padding:10px}th{width:22%}.desc{font-size:11.5px}}
button{font:inherit;padding:8px 14px;border-radius:6px;border:1px solid #1c1c1a;background:#1c1c1a;color:#fff;cursor:pointer}
button.sec{background:#fff;color:#1c1c1a}.aviso{background:#fff7e0;border:1px solid #e6c660;padding:10px 12px;border-radius:6px}
#estado{margin-left:14px}
</style></head><body>
<header><b>Rúbrica de reportes</b><span>Evaluador: __EVALUADOR__</span><span>Paquete __PAQUETE__</span>
<span id="progreso"></span></header>
<main>
<p class="aviso">Puntúa cada reporte de <b>0 a 3</b> en los cinco criterios. Los reportes aparecen en un orden
aleatorio y <b>no se indica qué sistema los produjo</b>. Trabaja por tu cuenta: no consultes tus puntajes
con el otro evaluador. El último criterio se puntúa al revés de la intuición: <b>3 = no hay información
sin respaldo</b>. Tus respuestas se guardan en este navegador; al terminar, exporta el archivo y envíalo.</p>
__ITEMS__
<p><button id="exportar">Exportar mis puntajes (JSON)</button>
<button class="sec" id="borrar">Borrar mis respuestas</button><span id="estado"></span></p>
</main>
<script>
const DATOS = __DATOS__;
const CLAVE = 'rubrica:' + DATOS.paquete_id + ':' + DATOS.evaluador;
let resp = {};
try { resp = JSON.parse(localStorage.getItem(CLAVE) || '{}'); } catch (e) { resp = {}; }
function guardar() { try { localStorage.setItem(CLAVE, JSON.stringify(resp)); } catch (e) {} }
function refrescar() {
  let hechos = 0;
  DATOS.items.forEach(it => {
    const r = resp[it.id] || {};
    const completo = DATOS.criterios.every(c => Number.isInteger(r[c]));
    if (completo) hechos++;
    document.getElementById('item-' + it.id).classList.toggle('hecho', completo);
  });
  document.getElementById('progreso').textContent = hechos + ' de ' + DATOS.items.length + ' reportes puntuados';
}
document.querySelectorAll('input[type=radio]').forEach(inp => {
  const [id, crit] = inp.name.split('|');
  if ((resp[id] || {})[crit] === Number(inp.value)) inp.checked = true;
  inp.addEventListener('change', () => {
    resp[id] = resp[id] || {}; resp[id][crit] = Number(inp.value); guardar(); refrescar();
  });
});
document.getElementById('exportar').addEventListener('click', () => {
  const faltan = DATOS.items.filter(it => !DATOS.criterios.every(c => Number.isInteger((resp[it.id] || {})[c])));
  if (faltan.length) {
    document.getElementById('estado').textContent = 'Faltan puntajes en: ' + faltan.map(i => i.id).join(', ');
    return;
  }
  const salida = {paquete_id: DATOS.paquete_id, evaluador: DATOS.evaluador, escala: DATOS.escala,
    items: DATOS.items.map(it => ({id: it.id, puntajes: resp[it.id]}))};
  window.__EXPORTADO__ = salida;
  const blob = new Blob([JSON.stringify(salida, null, 2)], {type: 'application/json'});
  const a = document.createElement('a'); a.href = URL.createObjectURL(blob);
  a.download = 'puntajes_' + DATOS.evaluador + '.json'; a.click();
  document.getElementById('estado').textContent = 'Exportado.';
});
document.getElementById('borrar').addEventListener('click', () => {
  if (confirm('¿Borrar todas tus respuestas?')) { resp = {}; guardar(); location.reload(); }
});
refrescar();
</script></body></html>
"""


def _tabla_de_criterios(item_id: str) -> str:
    filas = []
    for criterio in CRITERIOS:
        celdas = "".join(
            f'<td class="n"><label><input type="radio" name="{item_id}|{criterio}" value="{n}"> {n}</label>'
            f'<div class="desc">{html.escape(DESCRIPTORES[criterio][n])}</div></td>'
            for n in range(PUNTAJE_MINIMO, PUNTAJE_MAXIMO + 1))
        filas.append(f"<tr><th>{html.escape(ETIQUETAS[criterio])}</th>{celdas}</tr>")
    return "<table>" + "".join(filas) + "</table>"


def html_del_evaluador(paquete: dict) -> str:
    """Formulario autocontenido de UN evaluador. Solo contiene sus reportes."""
    items_html = []
    for it in paquete["items"]:
        contexto = (f"<details><summary>Ver el caso</summary><pre>{html.escape(it['contexto'])}</pre>"
                    f"</details>") if it["contexto"] else ""
        items_html.append(
            f'<section class="item" id="item-{it["id"]}"><h2>Reporte {it["id"]}'
            f' <small>({html.escape(it["caso"])})</small></h2>{contexto}'
            f'<pre>{html.escape(it["texto"])}</pre>{_tabla_de_criterios(it["id"])}</section>')
    datos = {"paquete_id": paquete["paquete_id"], "evaluador": paquete["evaluador"],
             "criterios": list(CRITERIOS), "escala": f"{PUNTAJE_MINIMO}-{PUNTAJE_MAXIMO}",
             "items": [{"id": it["id"]} for it in paquete["items"]]}
    return (_PLANTILLA.replace("__EVALUADOR__", html.escape(paquete["evaluador"]))
            .replace("__PAQUETE__", paquete["paquete_id"])
            .replace("__ITEMS__", "\n".join(items_html))
            .replace("__DATOS__", json.dumps(datos).replace("</", "<\\/")))


def escribir_paquete(reportes: list[ReporteEntrada], semilla: int, config_version: str,
                     destino: Path, evaluadores: tuple[str, ...] = EVALUADORES) -> dict:
    """Escribe `formulario_<E>.html` (uno por evaluador) y `clave_secreta.json`. No sobrescribe."""
    if destino.exists() and any(destino.iterdir()):
        raise FileExistsError(f"{destino} ya tiene contenido: la rúbrica no se sobrescribe")
    r = preparar_paquete(reportes, semilla, config_version, evaluadores)
    destino.mkdir(parents=True, exist_ok=True)
    for evaluador, paquete in r["paquetes"].items():
        (destino / f"formulario_{evaluador}.html").write_text(
            html_del_evaluador(paquete), encoding="utf-8")
    (destino / "clave_secreta.json").write_text(
        json.dumps(r["clave"], indent=2, ensure_ascii=False), encoding="utf-8")
    return {"paquete_id": r["clave"]["paquete_id"], "n_reportes": r["clave"]["n_reportes"],
            "compromiso_semilla": r["clave"]["compromiso_semilla"]}


# --- importación y desciegue --------------------------------------------------------------------------

def _puntaje_valido(valor) -> bool:
    return (isinstance(valor, int) and not isinstance(valor, bool)
            and PUNTAJE_MINIMO <= valor <= PUNTAJE_MAXIMO)


def leer_respuestas(clave: dict, respuestas: dict) -> list[PuntuacionRubrica]:
    """Valida UN archivo de un evaluador y lo desciega con la clave."""
    if respuestas.get("paquete_id") != clave["paquete_id"]:
        raise ValueError("el archivo es de otro paquete: no se mezclan evaluaciones de paquetes distintos")
    evaluador = respuestas.get("evaluador")
    if evaluador not in clave["evaluadores"]:
        raise ValueError(f"evaluador desconocido: {evaluador!r}")
    esperados = {i["id"]: i for i in clave["items"] if i["evaluador"] == evaluador}
    vistos: set[str] = set()
    salida = []
    for item in respuestas.get("items") or []:
        item_id = item.get("id")
        if item_id not in esperados:
            raise ValueError(f"{evaluador}: reporte desconocido {item_id!r}")
        if item_id in vistos:
            raise ValueError(f"{evaluador}: el reporte {item_id} está repetido")
        vistos.add(item_id)
        puntajes = item.get("puntajes") or {}
        if set(puntajes) != set(CRITERIOS):
            raise ValueError(f"{evaluador}/{item_id}: criterios incompletos o sobrantes")
        for criterio, valor in puntajes.items():
            if not _puntaje_valido(valor):
                raise ValueError(f"{evaluador}/{item_id}/{criterio}: {valor!r} no es un entero "
                                 f"de {PUNTAJE_MINIMO} a {PUNTAJE_MAXIMO}")
        meta = esperados[item_id]
        salida.append(PuntuacionRubrica(meta["case_id"], meta["arquitectura"], evaluador, puntajes))
    faltan = sorted(set(esperados) - vistos)
    if faltan:
        raise ValueError(f"{evaluador}: faltan {len(faltan)} reportes sin puntuar: {faltan[:5]}")
    return salida


def importar_puntajes(clave: dict, archivos: list[dict]) -> dict:
    """Une los archivos de los dos evaluadores, desciega y calcula la concordancia.

    Exige exactamente un archivo por evaluador: dos del mismo no son dos opiniones.
    """
    evaluadores = [a.get("evaluador") for a in archivos]
    if sorted(evaluadores) != sorted(clave["evaluadores"]):
        raise ValueError(f"se necesita un archivo de cada evaluador {clave['evaluadores']}; "
                         f"llegaron {evaluadores}")
    puntuaciones = [p for a in archivos for p in leer_respuestas(clave, a)]
    resultado = agregar(puntuaciones)
    meta = {(i["case_id"], i["arquitectura"]): i for i in clave["items"]}
    return {"puntuaciones": puntuaciones, "resultado": resultado.to_dict(),
            "repeticion_por_reporte": {k: v["repeticion"] for k, v in meta.items()}}


def escribir_resultados(importado: dict, config_version: str, raiz_repo: Path,
                        etiqueta: str | None = None) -> dict:
    """Escribe `puntajes.csv` (el formato que lee el consolidador) y la concordancia.

    Va a `experiments/rubrica/<config_version>/`. No sobrescribe: si ya hay puntajes de esa
    configuración, falla.
    """
    carpeta = raiz_repo / "experiments" / "rubrica" / config_version
    csv_ruta, conc_ruta = carpeta / "puntajes.csv", carpeta / "concordancia.json"
    for ruta in (csv_ruta, conc_ruta):
        if ruta.exists():
            raise FileExistsError(f"{ruta} ya existe: los puntajes humanos no se sobrescriben")
    carpeta.mkdir(parents=True, exist_ok=True)
    with csv_ruta.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["case_id", "arquitectura", "repeticion", "evaluador", *CRITERIOS])
        for p in sorted(importado["puntuaciones"],
                        key=lambda x: (x.case_id, x.arquitectura, x.evaluador)):
            w.writerow([p.case_id, p.arquitectura,
                        importado["repeticion_por_reporte"][(p.case_id, p.arquitectura)],
                        p.evaluador, *(p.puntajes[c] for c in CRITERIOS)])
    conc_ruta.write_text(json.dumps({"config_version": config_version, "etiqueta": etiqueta,
                                     **importado["resultado"]}, indent=2, ensure_ascii=False),
                         encoding="utf-8")
    return {"puntajes": str(csv_ruta), "concordancia": str(conc_ruta)}


def main(argv: list[str] | None = None) -> int:
    import argparse
    p = argparse.ArgumentParser(prog="rubrica_ciega", description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="orden", required=True)
    a = sub.add_parser("preparar", help="arma los formularios ciegos y la clave secreta")
    a.add_argument("--reportes", required=True,
                   help="JSON: lista de {case_id, arquitectura, run_id, texto, contexto?, repeticion?}")
    a.add_argument("--config-version", required=True)
    a.add_argument("--semilla", type=int, required=True)
    a.add_argument("--destino", required=True)
    b = sub.add_parser("importar", help="une los puntajes de los dos evaluadores y desciega")
    b.add_argument("--clave", required=True)
    b.add_argument("--puntajes", nargs=2, required=True, metavar=("E1.json", "E2.json"))
    b.add_argument("--raiz-repo", default=".")
    args = p.parse_args(argv)
    if args.orden == "preparar":
        datos = json.loads(Path(args.reportes).read_text(encoding="utf-8"))
        reportes = [ReporteEntrada(d["case_id"], d["arquitectura"], d["run_id"], d["texto"],
                                   d.get("contexto", ""), d.get("repeticion", 1)) for d in datos]
        print(json.dumps(escribir_paquete(reportes, args.semilla, args.config_version,
                                          Path(args.destino)), indent=2, ensure_ascii=False))
        return 0
    clave = json.loads(Path(args.clave).read_text(encoding="utf-8"))
    archivos = [json.loads(Path(f).read_text(encoding="utf-8")) for f in args.puntajes]
    importado = importar_puntajes(clave, archivos)
    print(json.dumps(escribir_resultados(importado, clave["config_version"], Path(args.raiz_repo)),
                     indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
