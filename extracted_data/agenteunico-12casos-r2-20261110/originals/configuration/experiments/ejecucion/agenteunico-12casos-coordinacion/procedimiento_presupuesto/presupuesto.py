"""Estimación de costo del agente único y escritura de presupuesto.json (creación exclusiva). Sin modelo."""
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT, CALIB, ESCRIBIR = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3] == "escribir"
R1 = ROOT / "extracted_data/oficial-12casos-r1-20261028"
COORD = ROOT / "experiments/ejecucion/agenteunico-12casos-coordinacion"
pre = json.loads((COORD / "preflight_r1_20261110.json").read_text(encoding="utf-8"))
cal = json.loads(CALIB.read_text(encoding="utf-8"))["ratios"]
precios = json.loads((ROOT / "experiments/config/precios_modelo.json").read_text(encoding="utf-8"))
v = next(x for x in precios["modelos"]["gemini-3.8-flash"]["vigencias"] if x["hasta"] == "2026-12-31")
PIN, POUT = v["entrada_por_millon"], v["salida_por_millon"]
TOPE = 2.50

llamadas = defaultdict(list)
for l in open(R1 / "performance/llm_calls_items.jsonl", encoding="utf-8"):
    r = json.loads(l)
    llamadas[r["case_id"]].append(r["value"])
ds = lambda c: c[:3]  # noqa: E731
ratio = {d: (min(x["ratio"] for k, x in cal.items() if ds(k) == d), max(x["ratio"] for k, x in cal.items() if ds(k) == d)) for d in ("bgl", "uwf")}
# Salida + razonamiento (se factura como salida): mínimo = la última llamada de NODEX (el auditor);
# máximo = todo lo que generó NODEX en el caso sumando sus 5-11 llamadas.
salida = {}
for d in ("bgl", "uwf"):
    ultimas = [c[-1]["output_tokens"] + (c[-1].get("reasoning_tokens") or 0) for k, c in llamadas.items() if ds(k) == d]
    totales = [sum(x["output_tokens"] + (x.get("reasoning_tokens") or 0) for x in c) for k, c in llamadas.items() if ds(k) == d]
    salida[d] = (min(ultimas), max(totales))
usd = lambda i, o: (i * PIN + o * POUT) / 1e6  # noqa: E731

casos = []
for c in pre["casos"]:
    d = c["dataset"]
    chars = c["prompt_chars"] + c["system_chars"]
    imin, imax = round(chars / ratio[d][1]), round(chars / ratio[d][0])
    cmin, cmax = usd(imin, salida[d][0]), usd(imax, salida[d][1])
    casos.append(dict(orden=c["orden"], case_id=c["case_id"], dataset=d, prompt_chars=c["prompt_chars"],
                      system_chars=c["system_chars"], tokens_entrada_min=imin, tokens_entrada_max=imax,
                      salida_y_razonamiento_min=salida[d][0], salida_y_razonamiento_max=salida[d][1],
                      usd_min=round(cmin, 5), usd_max=round(cmax, 5), usd_max_con_reintento_json=round(2 * cmax, 5)))
rep_min, rep_max = sum(x["usd_min"] for x in casos), sum(x["usd_max"] for x in casos)
rep_peor = sum(x["usd_max_con_reintento_json"] for x in casos)
cota = {d: max(x["usd_max_con_reintento_json"] for x in casos if x["dataset"] == d) for d in ("bgl", "uwf")}
for x in casos:
    print(f"{x['orden']:2} {x['case_id']:26} prompt={x['prompt_chars']:6}+{x['system_chars']} chars  "
          f"entrada≈{x['tokens_entrada_min']:6}-{x['tokens_entrada_max']:6}  USD {x['usd_min']:.4f}-{x['usd_max']:.4f} "
          f"(peor con reintento {x['usd_max_con_reintento_json']:.4f})")
print("ratios chars/token", ratio, "salida+razonamiento", salida)
print(f"por repetición: USD {rep_min:.3f} - {rep_max:.3f} (peor con reintento en todos: {rep_peor:.3f})")
print(f"3 repeticiones: USD {3*rep_min:.3f} - {3*rep_max:.3f} (peor: {3*rep_peor:.3f})   tope {TOPE}")
print("cota previa por dataset:", cota)
registro = dict(
    creado_utc=datetime.now(timezone.utc).isoformat(), tope_gasto_usd=TOPE, alcance="las 3 repeticiones del agente único",
    precios=dict(modelo="gemini-3.8-flash", entrada_por_millon=PIN, salida_por_millon=POUT, vigencia_hasta=v["hasta"],
                 fuente=precios["fuente"], fecha_de_consulta=precios["fecha_de_consulta"],
                 nota="El razonamiento se factura como salida. Desde el 2027-01-01 el precio se duplica."),
    metodo=dict(
        tokens_entrada="caracteres del prompt + system del preflight / caracteres por token calibrados con el prompt del "
                       "auditor de NODEX R1 reconstruido desde su estado crudo y su input_tokens medido",
        caracteres_por_token=ratio,
        salida_y_razonamiento=dict(min="última llamada de NODEX R1 (auditor), mínimo del dataset",
                                   max="suma de todas las llamadas de NODEX R1 en el caso, máximo del dataset", valores=salida),
        reintento_json="llm_json(retries=1): una respuesta inválida repite la solicitud; el peor caso duplica el costo"),
    casos=casos, por_repeticion=dict(usd_min=round(rep_min, 4), usd_max=round(rep_max, 4), usd_peor_con_reintento=round(rep_peor, 4)),
    total_3_repeticiones=dict(usd_min=round(3 * rep_min, 4), usd_max=round(3 * rep_max, 4), usd_peor_con_reintento=round(3 * rep_peor, 4)),
    costo_maximo_previo_por_dataset=cota,
    regla="Antes de cada caso: gasto real de las 3 repeticiones (recalculado desde la telemetría) + costo máximo del "
          "dataset (el mayor entre lo observado en la campaña y esta cota previa) no puede superar el tope; si lo supera, "
          "el lanzador se detiene antes de lanzar el caso.")
if ESCRIBIR:
    with (COORD / "presupuesto.json").open("x", encoding="utf-8", newline="\n") as f:
        json.dump(registro, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print("escrito", COORD / "presupuesto.json")
