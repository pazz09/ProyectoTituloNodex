"""Selección, regeneración y preflight del conjunto final de evaluación de NODEX (60 casos). Sin API.

    python tools/seleccionar_conjunto_final.py seleccionar    # solo metadatos -> experiments/cases_final/seleccion.json
    python tools/seleccionar_conjunto_final.py regenerar      # generador corregido -> experiments/cases_final/{cases,ground_truth}
    python tools/seleccionar_conjunto_final.py composicion    # experiments/cases_final/composicion.csv (+ tabla para el preregistro)
    python tools/seleccionar_conjunto_final.py preflight      # sin LLM: preprocesamiento, prompts, memoria

Preregistro: docs/experimentacion/preregistro_evaluacion_final.md (semilla 20261113).

**Selección (solo metadatos).** No abre el contenido de ningún caso de evaluación ni su ground truth:
- UWF: manifiesto del generador (`experiments/manifests/uwf.json`). Regla del generador
  (`generar_casos_uwf`): en cada condición, los índices `< round(n_casos * prevalencia)` son positivos y
  llevan el incidente `incidentes_usados[indice]` (id `ventana__táctica__IP__n[#rN]`); el resto son
  benignos (solo fondo).
- BGL: el generador se reproduce en memoria con sus semillas (`agrupar_bgl` sobre el log fuente,
  `particionar_grupos`, `generar_campana`), y de cada caso se toma su grupo (ventana de 20 líneas del
  log fuente). Regla del generador: índice `< n_positivos` = con alerta. Categoría de alerta: la del grupo
  en el log fuente (`etiqueta_original`, primera alerta), y número de líneas con alerta del grupo.
- Se excluyen los 12 casos del piloto (`experiments/ejecucion/enriquecido-12casos-r1-20261104/selection.json`).

Reglas (preregistro, sección 3). Si una no se puede cumplir, se informa en `decisiones` y se aplica la
alternativa documentada; nada se relaja en silencio.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import math
import random
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SEMILLA = 20261113
DESTINO = ROOT / "experiments" / "cases_final"
PILOTO = ROOT / "experiments/ejecucion/enriquecido-12casos-r1-20261104/selection.json"
MEMORIA = ROOT / "experiments/knowledge/rag_enriquecido_v2"
CONFIG_CONGELADA = ROOT / "experiments/config/config_oficial-12casos-r1-20261028.json"
OBJETIVO = {"bgl_con_alerta": 15, "bgl_sin_alerta": 15, "uwf_malicioso": 15, "uwf_benigno": 15}
OBJETIVO_UWF_MALICIOSO = {"visible": 7, "sigiloso": 8}
OBJETIVO_UWF_BENIGNO = {"visible": 7, "sigiloso": 8}
TOPE_POR_TACTICA = 2
TACTICA_SIN_TOPE = "Reconnaissance"


def _leer(ruta: Path):
    return json.loads(Path(ruta).read_text(encoding="utf-8"))


def _escribir(ruta: Path, datos) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps(datos, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


# --- metadatos ------------------------------------------------------------------------------

def casos_piloto() -> set[str]:
    return {c["case_id"] for c in _leer(PILOTO)["casos"]}


def _incidente(incidente_id: str) -> dict:
    base, _, recorte = incidente_id.partition("#r")
    ventana, tactica, ip, n = base.split("__")
    return {"incidente_id": incidente_id, "incidente_base": base, "ventana_incidente": ventana,
            "tactica": tactica, "tacticas": sorted(tactica.split("|")), "ip_atacante": ip,
            "recorte_filas": int(recorte) if recorte else None}


def metadatos_uwf() -> list[dict]:
    """Casos UWF de evaluación con su clase y su incidente, según la regla del generador."""
    manifiesto = _leer(ROOT / "experiments/manifests/uwf.json")
    salida = []
    for condicion, c in manifiesto["condiciones"]["evaluacion"].items():
        n_pos = round(c["n_casos"] * c["prevalencia_solicitada"])
        if n_pos != len(c["incidentes_usados"]):
            raise SystemExit(f"uwf/{condicion}: la regla del generador no coincide con el manifiesto")
        for indice, case_id in enumerate(c["case_ids"]):
            if not case_id.endswith(f"_{indice:04d}"):
                raise SystemExit(f"{case_id}: el índice no coincide con la posición en el manifiesto")
            fila = {"case_id": case_id, "dataset": "uwf", "condicion": condicion, "indice": indice,
                    "positivo": indice < n_pos}
            if fila["positivo"]:
                fila.update(_incidente(c["incidentes_usados"][indice]))
            salida.append(fila)
    return salida


def metadatos_bgl() -> list[dict]:
    """Casos BGL de evaluación con su grupo, clase y categoría de alerta (generador reproducido en memoria)."""
    from src.experimentation.datasets.agrupacion import agrupar_bgl, etiqueta_bgl
    from src.experimentation.datasets.generador import generar_campana
    from src.experimentation.datasets.particion import particionar_grupos
    from src.experimentation.datasets.preparar import _especificaciones
    fuente = ROOT / "data/logs/BGL_2k.log"
    grupos = agrupar_bgl(fuente)
    etiquetas = [etiqueta_bgl(linea) for linea in fuente.read_text(encoding="utf-8", errors="replace").splitlines()]
    reparto = particionar_grupos(grupos)
    resultados = generar_campana(reparto["evaluacion"], _especificaciones("bgl", "evaluacion"))
    manifiesto = _leer(ROOT / "experiments/manifests/bgl.json")["condiciones"]["evaluacion"]
    por_nombre = {g.grupo: g for g in grupos}
    salida = []
    for condicion, resultado in resultados.items():
        ids = [c.case_id for c in resultado.casos]
        if ids != manifiesto[condicion]["case_ids"]:
            raise SystemExit(f"bgl/{condicion}: la reproducción del generador no coincide con el manifiesto")
        n_pos = round(resultado.especificacion.n_casos * resultado.especificacion.prevalencia_solicitada)
        for indice, caso in enumerate(resultado.casos):
            (nombre,) = caso.grupos
            grupo = por_nombre[nombre]
            lineas = [l.linea_original for l in grupo.lineas]
            alertas = [etiquetas[n - 1] for n in lineas if etiquetas[n - 1] not in ("-", "")]
            positivo = indice < n_pos
            if positivo != grupo.es_positivo:
                raise SystemExit(f"{caso.case_id}: la regla del índice no coincide con el grupo")
            salida.append({"case_id": caso.case_id, "dataset": "bgl", "condicion": condicion, "indice": indice,
                           "positivo": positivo, "grupo": nombre,
                           "categoria": grupo.etiqueta_original if positivo else None,
                           "categorias_del_grupo": sorted(set(alertas)),
                           "lineas_con_alerta": len(alertas)})
    return salida


def memoria_uwf() -> dict:
    """IP atacantes e incidentes presentes en la memoria `rag_enriquecido_v2` (solo desarrollo y v1)."""
    manifiesto = _leer(MEMORIA / "manifiesto.json")
    uwf = _leer(ROOT / "experiments/manifests/uwf.json")["condiciones"]["desarrollo"]
    incidente_de_dev = {}
    for c in uwf.values():
        for indice, case_id in enumerate(c["case_ids"]):
            if indice < len(c["incidentes_usados"]):
                incidente_de_dev[case_id] = _incidente(c["incidentes_usados"][indice])
    ips, bases = set(), set()
    for p in manifiesto["casos"]:
        if p["dataset"] != "uwf" or p["etiqueta"] != "malicioso":
            continue
        inc = (incidente_de_dev[p["historical_case_id"]] if p["origen"] == "caso_desarrollo"
               else _incidente(p["origen"].split(":", 1)[1]))
        ips.add(inc["ip_atacante"])
        bases.add(inc["incidente_base"])
    return {"ips": sorted(ips), "incidentes": sorted(bases)}


# --- selección ----------------------------------------------------------------------------------

def _tope_categoria(conteos: Counter, objetivo: int) -> int:
    """El menor tope por categoría que permite llegar al objetivo."""
    for tope in range(1, max(conteos.values()) + 1):
        if sum(min(n, tope) for n in conteos.values()) >= objetivo:
            return tope
    return max(conteos.values())


def seleccionar_bgl(casos: list[dict], azar: random.Random, decisiones: list) -> list[dict]:
    positivos = [c for c in casos if c["positivo"]]
    negativos = [c for c in casos if not c["positivo"]]
    elegidos = []
    # Con alerta: estratificado por categoría, con tope por categoría.
    por_categoria: dict[str, list] = {}
    for c in sorted(positivos, key=lambda c: c["case_id"]):
        por_categoria.setdefault(c["categoria"], []).append(c)
    conteos = Counter({k: len(v) for k, v in por_categoria.items()})
    objetivo = OBJETIVO["bgl_con_alerta"]
    if sum(conteos.values()) < objetivo:
        decisiones.append({"regla": "BGL: 15 con alerta", "cumplida": False,
                           "alternativa": f"se toman los {sum(conteos.values())} disponibles"})
        objetivo = sum(conteos.values())
    tope = _tope_categoria(conteos, objetivo)
    tomados = {}
    for categoria in sorted(por_categoria):
        lista = list(por_categoria[categoria])
        azar.shuffle(lista)
        tomados[categoria] = lista[:min(len(lista), tope)]
    exceso = sum(len(v) for v in tomados.values()) - objetivo
    while exceso > 0:
        # Se recorta de las categorías más grandes (en el tope), al azar entre ellas.
        mayor = max(len(v) for v in tomados.values())
        candidatas = sorted(k for k, v in tomados.items() if len(v) == mayor)
        tomados[azar.choice(candidatas)].pop()
        exceso -= 1
    for categoria in sorted(tomados):
        elegidos.extend(tomados[categoria])
    decisiones.append({"regla": "BGL con alerta: estratificado por categoría con tope por categoría",
                       "cumplida": True, "tope_por_categoria": tope,
                       "disponibles_por_categoria": dict(sorted(conteos.items())),
                       "elegidos_por_categoria": {k: len(v) for k, v in sorted(tomados.items())},
                       "criterio_del_tope": "el menor tope que permite llegar a 15; el exceso se recorta al azar "
                                            "de las categorías más grandes"})
    # Sin alerta: al azar (las ventanas de 20 líneas son disjuntas por construcción).
    lista = sorted(negativos, key=lambda c: c["case_id"])
    azar.shuffle(lista)
    sin_alerta = lista[:OBJETIVO["bgl_sin_alerta"]]
    elegidos.extend(sin_alerta)
    grupos = [c["grupo"] for c in elegidos]
    decisiones.append({"regla": "BGL: 15 sin alerta, ventanas distintas",
                       "cumplida": len(sin_alerta) == OBJETIVO["bgl_sin_alerta"] and len(set(grupos)) == len(grupos),
                       "nota": "cada caso es una ventana contigua y disjunta de 20 líneas del log fuente; ningún "
                               "grupo se repite entre los 30 casos BGL"})
    return elegidos


def _admite(caso: dict, conteo_tacticas: Counter) -> bool:
    return all(t == TACTICA_SIN_TOPE or conteo_tacticas[t] < TOPE_POR_TACTICA for t in caso["tacticas"])


INTENTOS_UWF = 3000


def _intento_uwf(candidatos: list[dict], azar: random.Random) -> tuple[list[dict], list]:
    """Un intento greedy: cobertura de tácticas (las más raras primero) y relleno por condición."""
    candidatos = list(candidatos)
    azar.shuffle(candidatos)
    orden = {c["case_id"]: i for i, c in enumerate(candidatos)}
    tacticas = sorted({t for c in candidatos for t in c["tacticas"]},
                      key=lambda t: (sum(t in c["tacticas"] for c in candidatos), azar.random()))
    elegidos, conteo_tacticas, conteo_ips, bases, avisos = [], Counter(), Counter(), set(), []
    cuota = dict(OBJETIVO_UWF_MALICIOSO)

    def usar(c):
        elegidos.append(c)
        conteo_tacticas.update(c["tacticas"])
        conteo_ips[c["ip_atacante"]] += 1
        bases.add(c["incidente_base"])
        cuota[c["condicion"]] -= 1

    def puntaje(c):
        # IP menos repetida y, a igualdad, el orden al azar del intento.
        return (conteo_ips[c["ip_atacante"]], orden[c["case_id"]])

    def aptos(filtro):
        return [c for c in candidatos if filtro(c) and c not in elegidos
                and c["incidente_base"] not in bases and _admite(c, conteo_tacticas)]

    # 1) Cobertura: cada táctica disponible al menos una vez.
    for tactica in tacticas:
        if tactica in {t for c in elegidos for t in c["tacticas"]}:
            continue
        lista = aptos(lambda c: tactica in c["tacticas"])
        con_cuota = [c for c in lista if cuota[c["condicion"]] > 0]
        if con_cuota:
            usar(min(con_cuota, key=puntaje))
        elif lista:
            c = min(lista, key=puntaje)
            avisos.append({"regla": "UWF maliciosos: ~7 visibles y 8 sigilosos", "cumplida": False,
                           "alternativa": f"para cubrir {tactica} se excede la cuota de {c['condicion']}"})
            usar(c)
        else:
            avisos.append({"regla": f"UWF: cubrir la táctica {tactica}", "cumplida": False,
                           "alternativa": "no hay candidato que respete el tope y un caso por incidente"})
    # 2) Relleno hasta la cuota de cada condición, eligiendo en ambas a la vez (la IP menos usada).
    while any(n > 0 for n in cuota.values()):
        lista = aptos(lambda c: cuota[c["condicion"]] > 0)
        if not lista:
            break
        usar(min(lista, key=puntaje))
    # 3) Alternativa documentada: completar desde la otra condición, con topes e incidentes.
    while len(elegidos) < OBJETIVO["uwf_malicioso"]:
        lista = aptos(lambda c: True)
        if not lista:
            break
        c = min(lista, key=puntaje)
        avisos.append({"regla": "UWF maliciosos: ~7 visibles y 8 sigilosos", "cumplida": False,
                       "alternativa": f"{c['case_id']} completa desde la otra condición"})
        usar(c)
    return elegidos, avisos


def _evaluar_intento(elegidos: list[dict], todas: list[str]) -> tuple:
    """Clave a minimizar: reglas incumplidas, luego repetición de IP (suma de cuadrados y máximo)."""
    tacticas = Counter(t for c in elegidos for t in c["tacticas"])
    ips = Counter(c["ip_atacante"] for c in elegidos)
    incumplidas = (abs(OBJETIVO["uwf_malicioso"] - len(elegidos))
                   + sum(1 for t in todas if t not in tacticas)
                   + sum(1 for t, n in tacticas.items() if t != TACTICA_SIN_TOPE and n > TOPE_POR_TACTICA)
                   + sum(abs(OBJETIVO_UWF_MALICIOSO[k] - sum(c["condicion"] == k for c in elegidos))
                         for k in OBJETIVO_UWF_MALICIOSO))
    return (incumplidas, sum(n * n for n in ips.values()), max(ips.values(), default=0))


def seleccionar_uwf_maliciosos(casos: list[dict], azar: random.Random, decisiones: list) -> list[dict]:
    candidatos = sorted((c for c in casos if c["positivo"]), key=lambda c: c["case_id"])
    todas = sorted({t for c in candidatos for t in c["tacticas"]})
    mejor = None
    for intento in range(INTENTOS_UWF):
        elegidos, avisos = _intento_uwf(candidatos, random.Random(azar.random()))
        clave = _evaluar_intento(elegidos, todas)
        if mejor is None or clave < mejor[0]:
            mejor = (clave, intento, elegidos, avisos)
    clave, intento, elegidos, avisos = mejor
    decisiones.extend(avisos)
    conteo_tacticas = Counter(t for c in elegidos for t in c["tacticas"])
    conteo_ips = Counter(c["ip_atacante"] for c in elegidos)
    bases = {c["incidente_base"] for c in elegidos}
    decisiones.append({"regla": "UWF maliciosos: método", "nota":
                       f"{INTENTOS_UWF} intentos greedy con orden al azar (semilla {SEMILLA}); se conserva el que "
                       "cumple todas las reglas y reparte mejor las IP atacantes (menor suma de cuadrados de casos "
                       f"por IP, luego menor máximo). Elegido: intento {intento}, clave {list(clave)}."})
    disponibles = sorted({t for c in candidatos for t in c["tacticas"]})
    cubiertas = sorted({t for c in elegidos for t in c["tacticas"]})
    decisiones.append({"regla": "UWF maliciosos: cubrir todas las tácticas disponibles",
                       "cumplida": cubiertas == disponibles, "tacticas_disponibles": disponibles,
                       "tacticas_cubiertas": cubiertas,
                       "nota": "las etiquetas compuestas del dataset (p. ej. Discovery|Reconnaissance) cuentan para "
                               "cada táctica que nombran, en la cobertura y en el tope"})
    decisiones.append({"regla": f"UWF maliciosos: a lo más {TOPE_POR_TACTICA} por táctica salvo {TACTICA_SIN_TOPE}",
                       "cumplida": all(n <= TOPE_POR_TACTICA for t, n in conteo_tacticas.items()
                                       if t != TACTICA_SIN_TOPE),
                       "casos_por_tactica": dict(sorted(conteo_tacticas.items()))})
    decisiones.append({"regla": "UWF maliciosos: un caso por incidente", "cumplida": len(bases) == len(elegidos)})
    n_ips = len(conteo_ips)
    decisiones.append({"regla": "UWF maliciosos: IP atacantes distintas cuando sea posible",
                       "cumplida": n_ips == len(elegidos),
                       "ips_distintas": n_ips, "ips_disponibles": len({c['ip_atacante'] for c in candidatos}),
                       "casos_por_ip": dict(sorted(conteo_ips.items())),
                       "alternativa": None if n_ips == len(elegidos) else
                       "con 15 casos y las IP disponibles no es posible que todas sean distintas: se usan todas las "
                       "IP disponibles y se minimiza la repetición"})
    decisiones.append({"regla": "UWF maliciosos: ~7 visibles y 8 sigilosos",
                       "resultado": dict(Counter(c["condicion"] for c in elegidos))})
    return elegidos


def seleccionar_uwf_benignos(casos: list[dict], azar: random.Random, decisiones: list) -> list[dict]:
    elegidos = []
    for condicion, n in OBJETIVO_UWF_BENIGNO.items():
        lista = sorted((c for c in casos if not c["positivo"] and c["condicion"] == condicion),
                       key=lambda c: c["indice"])
        # Muestreo sistemático con inicio al azar: el fondo se asigna con un cursor que avanza en el
        # orden de los índices, así que índices espaciados son ventanas separadas en el tiempo.
        paso = len(lista) / n
        inicio = azar.random() * paso
        elegidos.extend(lista[min(len(lista) - 1, int(inicio + k * paso))] for k in range(n))
    decisiones.append({"regla": "UWF: 15 benignos de ventanas distintas",
                       "cumplida": len({c["case_id"] for c in elegidos}) == OBJETIVO["uwf_benigno"],
                       "nota": "el fondo de cada caso es un tramo contiguo propio (ningún uid se repite entre casos, "
                               "lo verifica el generador); además se eligen índices espaciados (muestreo sistemático "
                               "con inicio al azar), que el cursor del generador asigna a tramos separados en el "
                               "tiempo. La ventana efectiva de cada caso se informa en la composición."})
    return elegidos


def seleccionar() -> dict:
    azar = random.Random(SEMILLA)
    excluidos = casos_piloto()
    bgl = [c for c in metadatos_bgl() if c["case_id"] not in excluidos]
    uwf = [c for c in metadatos_uwf() if c["case_id"] not in excluidos]
    memoria = memoria_uwf()
    decisiones: list = []
    elegidos = (seleccionar_bgl(bgl, azar, decisiones) + seleccionar_uwf_maliciosos(uwf, azar, decisiones)
                + seleccionar_uwf_benignos(uwf, azar, decisiones))
    for c in elegidos:
        if c["dataset"] == "uwf" and c["positivo"]:
            c["ip_en_memoria"] = c["ip_atacante"] in memoria["ips"]
            c["incidente_en_memoria"] = c["incidente_base"] in memoria["incidentes"]
    ids = [c["case_id"] for c in elegidos]
    if len(ids) != len(set(ids)) or set(ids) & excluidos:
        raise SystemExit("selección inválida: casos repetidos o del piloto")
    resultado = {
        "semilla": SEMILLA, "particion": "evaluacion", "n_casos": len(elegidos),
        "fuentes": {"uwf": "experiments/manifests/uwf.json (incidentes_usados, case_ids)",
                    "bgl": "data/logs/BGL_2k.log + generador reproducido en memoria (agrupar_bgl, "
                           "particionar_grupos, generar_campana, semillas registradas)",
                    "piloto_excluido": str(PILOTO.relative_to(ROOT)).replace("\\", "/"),
                    "memoria": "experiments/knowledge/rag_enriquecido_v2/manifiesto.json"},
        "excluidos_piloto": sorted(excluidos),
        "candidatos": {"bgl_con_alerta": sum(c["positivo"] for c in bgl),
                       "bgl_sin_alerta": sum(not c["positivo"] for c in bgl),
                       "uwf_malicioso": sum(c["positivo"] for c in uwf),
                       "uwf_benigno": sum(not c["positivo"] for c in uwf)},
        "memoria_uwf": memoria, "decisiones": decisiones,
        "casos": sorted(elegidos, key=lambda c: c["case_id"]),
    }
    _escribir(DESTINO / "seleccion.json", resultado)
    return resultado


# --- regeneración y verificación ---------------------------------------------------------------

def _verificar_csv(original: Path, nuevo: Path, meta_original: dict) -> dict:
    from src.experimentation.datasets.regenerar import _dt
    from src.experimentation.datasets.uwf_casos import _formato_del_fondo
    insertadas = {p["uid"] for p in meta_original["procedencia"] if not str(p["grupo"]).startswith("fondo:")}
    fa = list(csv.DictReader(io.StringIO(original.read_text(encoding="utf-8"))))
    fb = list(csv.DictReader(io.StringIO(nuevo.read_text(encoding="utf-8"))))
    problemas, cambiadas, fuera = [], 0, 0
    if len(fa) != len(fb):
        return {"problemas": ["distinto número de filas"], "filas_cambiadas": 0}
    for x, y in zip(fa, fb):
        distintas = [k for k in x if x[k] != y.get(k)]
        if not distintas:
            continue
        cambiadas += 1
        if set(distintas) - {"ts", "datetime"}:
            problemas.append(f"cambian columnas {sorted(set(distintas) - {'ts', 'datetime'})}")
        if x["uid"] not in insertadas:
            fuera += 1
        if abs(float(x["ts"]) - float(y["ts"])) > 1e-6:
            problemas.append(f"ts cambia de instante en una fila")
        if _dt(y["datetime"]).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3] != x["datetime"]:
            problemas.append("datetime cambia de instante en una fila")
        if _formato_del_fondo(float(y["ts"])) != (y["ts"], y["datetime"]):
            problemas.append("el formato nuevo no sigue la regla del fondo")
    if fuera:
        problemas.append(f"{fuera} filas del fondo cambian (solo deben cambiar las insertadas)")
    return {"problemas": sorted(set(problemas)), "filas_cambiadas": cambiadas, "filas_insertadas": len(insertadas)}


def regenerar() -> dict:
    from src.experimentation.datasets.regenerar import regenerar as regenerar_particion
    seleccion = _leer(DESTINO / "seleccion.json")
    for sub in ("cases", "ground_truth"):
        if (DESTINO / sub).exists() and any((DESTINO / sub).rglob("*")):
            raise SystemExit(f"{DESTINO / sub} ya tiene archivos: no se sobrescribe")
    verificacion = []
    with tempfile.TemporaryDirectory(prefix="cases_final_", ignore_cleanup_errors=True) as tmp:
        tmp = Path(tmp)
        # El generador recorre siempre todas las particiones (mismas semillas y registros); se escribe
        # la de evaluación en un directorio temporal y se copian SOLO los 60 casos elegidos.
        regenerar_particion(ROOT, tmp, ("evaluacion",))
        registro = _leer(tmp / "regeneracion.json")
        for c in seleccion["casos"]:
            ds, cid = c["dataset"], c["case_id"]
            ext = "log" if ds == "bgl" else "csv"
            orig_dir = ROOT / "experiments/cases" / ds / "evaluacion"
            gt_orig = ROOT / "experiments/ground_truth" / ds / "evaluacion" / f"{cid}.json"
            nuevo_dir, gt_nuevo = tmp / "cases" / ds / "evaluacion", tmp / "ground_truth" / ds / "evaluacion" / f"{cid}.json"
            fila = {"case_id": cid, "metadatos_identicos": (orig_dir / f"{cid}.json").read_bytes()
                    == (nuevo_dir / f"{cid}.json").read_bytes(),
                    "referencia_identica": gt_orig.read_bytes() == gt_nuevo.read_bytes()}
            if ext == "log":
                fila.update(contenido_identico=(orig_dir / f"{cid}.log").read_bytes()
                            == (nuevo_dir / f"{cid}.log").read_bytes(), problemas=[], filas_cambiadas=0)
            else:
                fila.update(_verificar_csv(orig_dir / f"{cid}.csv", nuevo_dir / f"{cid}.csv",
                                           _leer(orig_dir / f"{cid}.json")))
            fila["solo_cambia_el_formato"] = (fila["metadatos_identicos"] and fila["referencia_identica"]
                                              and not fila["problemas"] and fila.get("contenido_identico", True))
            verificacion.append(fila)
            for origen, destino in (((nuevo_dir / f"{cid}.{ext}"), DESTINO / "cases" / ds / "evaluacion" / f"{cid}.{ext}"),
                                    ((nuevo_dir / f"{cid}.json"), DESTINO / "cases" / ds / "evaluacion" / f"{cid}.json"),
                                    (gt_nuevo, DESTINO / "ground_truth" / ds / "evaluacion" / f"{cid}.json")):
                destino.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(origen, destino)
    import hashlib
    resumen = {"regeneracion": registro, "casos": len(verificacion),
               "todos_solo_cambia_el_formato": all(v["solo_cambia_el_formato"] for v in verificacion),
               "filas_reformateadas": sum(v["filas_cambiadas"] for v in verificacion),
               "sha256": {f"{p.relative_to(DESTINO).as_posix()}": hashlib.sha256(p.read_bytes()).hexdigest()
                          for p in sorted((DESTINO / "cases").rglob("*")) if p.is_file()},
               "verificacion": verificacion}
    _escribir(DESTINO / "verificacion_regeneracion.json", resumen)
    return resumen


# --- composición -----------------------------------------------------------------------------------

COLUMNAS = ("case_id", "dataset", "condicion", "clase", "tactica_o_categoria", "filas_incidente",
            "ip_atacante", "ip_atacante_en_memoria", "incidente_en_memoria", "ventana")


def composicion() -> list[dict]:
    seleccion = _leer(DESTINO / "seleccion.json")
    filas = []
    for c in seleccion["casos"]:
        meta = _leer(DESTINO / "cases" / c["dataset"] / "evaluacion" / f"{c['case_id']}.json")
        notas = meta.get("notas") or {}
        if c["dataset"] == "bgl":
            fila = {"tactica_o_categoria": c["categoria"] or "-",
                    "filas_incidente": c["lineas_con_alerta"], "ip_atacante": "-",
                    "ip_atacante_en_memoria": "-", "incidente_en_memoria": "-", "ventana": c["grupo"]}
        else:
            n_mal = notas.get("n_registros_maliciosos", 0)
            if c["positivo"] and c.get("recorte_filas") not in (None, n_mal):
                raise SystemExit(f"{c['case_id']}: el recorte del incidente no coincide con los metadatos")
            fila = {"tactica_o_categoria": c.get("tactica") or "-", "filas_incidente": n_mal if c["positivo"] else 0,
                    "ip_atacante": c.get("ip_atacante") or "-",
                    "ip_atacante_en_memoria": ("sí" if c.get("ip_en_memoria") else "no") if c["positivo"] else "-",
                    "incidente_en_memoria": ("sí" if c.get("incidente_en_memoria") else "no") if c["positivo"] else "-",
                    "ventana": "fondo " + ",".join(notas.get("shards_fondo") or [])}
        filas.append({"case_id": c["case_id"], "dataset": c["dataset"], "condicion": c["condicion"],
                      "clase": "positivo" if c["positivo"] else "negativo", **fila})
    with (DESTINO / "composicion.csv").open("w", encoding="utf-8", newline="") as f:
        escritor = csv.DictWriter(f, fieldnames=COLUMNAS, lineterminator="\n")
        escritor.writeheader()
        escritor.writerows(filas)
    return filas


def tabla_markdown(filas: list[dict]) -> str:
    cab = ("| Caso | Dataset | Condición | Clase | Táctica o categoría | Filas del incidente | IP atacante | "
           "IP en memoria | Incidente en memoria | Ventana |")
    sep = "|---|---|---|---|---|---:|---|---|---|---|"
    return "\n".join([cab, sep] + [
        f"| {f['case_id']} | {f['dataset']} | {f['condicion']} | {f['clase']} | {f['tactica_o_categoria']} | "
        f"{f['filas_incidente']} | {f['ip_atacante']} | {f['ip_atacante_en_memoria']} | "
        f"{f['incidente_en_memoria']} | {f['ventana']} |" for f in filas])


# --- preflight (sin LLM) -----------------------------------------------------------------------------

#: Marcas que no pueden aparecer en ningún prompt: columnas de etiqueta de UWF y campos del ground truth.
MARCAS_PROHIBIDAS = ("label_binary", "label_tactic", "label_technique", "etiqueta_deteccion", "core_event_uids",
                     "referencias_mitre", "etiqueta_original", "tactica_del_incidente", "mitre_attack")


def _respuestas_simuladas():
    """Respuestas del modelo simulado: estructuralmente válidas, sin contenido sobre el caso."""
    return {
        "planificador": {"objetivo": "o", "pasos": [{"id": 1, "accion": "triage", "objetivo": "d", "estado": "pendiente"},
                                                    {"id": 2, "accion": "mitigacion", "objetivo": "m", "estado": "pendiente"}],
                         "criterios_finalizacion": ["x"]},
        "triage": {"diagnostico": "preflight", "veredicto_preliminar": "normal", "justificacion_veredicto": "preflight"},
        "selector": {"usar_cve": False, "razon": "preflight"},
        "mitigacion": {"comandos": ["true"]},
        "auditor": {"confianza": 0.9, "hay_anomalia": False, "hay_incidente": False, "evaluacion": "preflight",
                    "cobertura_auditor": True, "eventos_reconstruidos": [], "secuencia_temporal": [],
                    "tecnicas_atribuidas": [], "evaluacion_grupos": []},
        "agente_unico": {"diagnostico": "preflight", "veredicto_preliminar": "normal", "confianza": 0.9,
                         "hay_anomalia": False, "hay_incidente": False, "evaluacion": "preflight",
                         "comandos": ["true"], "eventos_reconstruidos": [], "secuencia_temporal": [],
                         "tecnicas_atribuidas": []},
    }


def preflight_hijo(salida: Path) -> None:
    """Corre en un proceso con la configuración congelada y una copia desechable de la memoria."""
    import importlib
    from src.experimentation.runtime.consultas_externas import RegistroConsultas, instalar
    registro = RegistroConsultas()
    instalar(registro)
    import src.config as config
    from src.preprocessing.pipeline import preprocesar
    respuestas = _respuestas_simuladas()
    capturas: list = []

    def simulado(nodo):
        def llm_json(prompt, system=None, *a, **k):
            capturas.append({"nodo": nodo, "prompt": prompt or "", "system": system or ""})
            return json.loads(json.dumps(respuestas[nodo]))
        return llm_json

    modulos = {"agente_planificador": "planificador", "agente_analista_triage": "triage",
               "agente_selector_herramientas": "selector", "agente_ingeniero_mitigacion": "mitigacion",
               "agente_auditor_final": "auditor"}
    for nombre, nodo in modulos.items():
        importlib.import_module(f"src.agents.{nombre}").llm_json = simulado(nodo)
    import src.single_agent as single
    single.llm_json = simulado("agente_unico")
    from src import pipeline
    from tools.single_agent_runner import recuperar_candidatos
    seleccion = _leer(DESTINO / "seleccion.json")
    resultados = []
    for c in seleccion["casos"]:
        ds, cid = c["dataset"], c["case_id"]
        contenido = (DESTINO / "cases" / ds / "evaluacion" / f"{cid}.{'log' if ds == 'bgl' else 'csv'}").read_text(encoding="utf-8")
        pre = preprocesar(contenido)
        capturas.clear()
        estado = pipeline.analizar_lote(contenido, thread_id=f"preflight__{cid}")
        nodex = list(capturas)
        capturas.clear()
        candidatos = recuperar_candidatos(contenido)["candidatos"]
        single.analizar_lote_agente_unico(contenido, thread_id=f"preflight_unico__{cid}", tecnicas_mitre=candidatos)
        unico = list(capturas)
        textos = [x["prompt"] + "\n" + x["system"] for x in nodex + unico]
        prohibidas = sorted({m for m in MARCAS_PROHIBIDAS for t in textos if m in t})
        if ds == "bgl":
            # El código de alerta del grupo solo existe como etiqueta (se retira del contenido).
            prohibidas += sorted({f"codigo_de_alerta:{k}" for k in c["categorias_del_grupo"]
                                  for t in textos if k in t})
        else:
            prohibidas += sorted({f"incidente:{c['incidente_base']}" for t in textos
                                  if c.get("incidente_base") and c["incidente_base"] in t})
        auditores = [x for x in nodex if x["nodo"] == "auditor"]
        consulta = estado.get("historico_consulta") or {}
        historicos = estado.get("casos_historicos") or []
        resultados.append({
            "case_id": cid, "dataset": ds, "error_api": estado.get("_error_api"),
            "cobertura_parsing": round(pre.cobertura, 4), "eventos": len(pre.events),
            "advertencias_parsing": len(pre.warnings or []), "eventos_fallback": pre.eventos_fallback,
            "llamadas_nodex": [x["nodo"] for x in nodex], "llamadas_agente_unico": len(unico),
            "marcas_de_etiqueta_en_prompts": prohibidas,
            "auditor_chars": max((len(x["prompt"]) + len(x["system"]) for x in auditores), default=0),
            "auditor_grupos_con_senal": "GRUPOS CON SEÑAL" in (auditores[0]["prompt"] if auditores else ""),
            "agente_unico_chars": max((len(x["prompt"]) + len(x["system"]) for x in unico), default=0),
            "triage_chars": max((len(x["prompt"]) + len(x["system"]) for x in nodex if x["nodo"] == "triage"), default=0),
            "historicos": len(historicos),
            "historicos_por_clase": dict(Counter(h.get("clase") or h.get("etiqueta") for h in historicos)),
            "excluidos_por_solapamiento": consulta.get("excluidos_por_solapamiento") or [],
            "memoria_grupos_grupos": len(estado.get("memoria_grupos") or {}),
            "memoria_grupos_excluidos": (estado.get("memoria_grupos_consulta") or {}).get("excluidos_por_solapamiento") or [],
        })
    _escribir(salida, {"interruptores": {k: getattr(config, k) for k in (
        "LLM_MODEL_PRIMARY", "LLM_SIN_RESPALDO", "REPUTACION_SIN_ENRIQUECIMIENTO", "AUDITOR_REFORZADO",
        "HISTORICO_CONTRASTIVO", "MEMORIA_GRUPOS_ACTIVA")},
        "consultas_externas": registro.a_lista(), "casos": resultados})


def preflight() -> dict:
    from src.experimentation import campana
    congelada = _leer(CONFIG_CONGELADA)
    salida = DESTINO / "preflight.json"
    with tempfile.TemporaryDirectory(prefix="preflight_", ignore_cleanup_errors=True) as tmp:
        tmp = Path(tmp)
        shutil.copytree(MEMORIA / "chroma_snapshot", tmp / "chroma")
        # Sin credencial real: el modelo está simulado y ninguna llamada puede salir.
        base = {k: v for k, v in __import__("os").environ.items() if "KEY" not in k.upper()}
        base["GEMINI_API_KEY"] = "preflight-sin-api"
        entorno = campana.entorno_de_la_corrida(base, congelada, tmp / "chroma", tmp / "ip.json")
        r = subprocess.run([sys.executable, str(Path(__file__).resolve()), "preflight-hijo", str(salida)],
                           cwd=ROOT, env=entorno, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if r.returncode != 0:
            print(r.stderr[-4000:])
            raise SystemExit(f"preflight falló (código {r.returncode})")
    return _leer(salida)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("accion", choices=("seleccionar", "regenerar", "composicion", "preflight", "preflight-hijo"))
    p.add_argument("salida", nargs="?")
    a = p.parse_args()
    if a.accion == "seleccionar":
        r = seleccionar()
        print(json.dumps({"n_casos": r["n_casos"], "candidatos": r["candidatos"], "decisiones": r["decisiones"]},
                         ensure_ascii=False, indent=1))
    elif a.accion == "regenerar":
        r = regenerar()
        print(json.dumps({k: v for k, v in r.items() if k not in ("verificacion", "sha256")}, ensure_ascii=False, indent=1))
        print("problemas:", [v for v in r["verificacion"] if not v["solo_cambia_el_formato"]])
    elif a.accion == "composicion":
        print(tabla_markdown(composicion()))
    elif a.accion == "preflight":
        r = preflight()
        print(json.dumps({"interruptores": r["interruptores"], "consultas_externas": len(r["consultas_externas"])},
                         ensure_ascii=False))
    else:
        preflight_hijo(Path(a.salida))
