"""Calibra caracteres/token con el prompt del auditor de NODEX R1 (reconstruido del estado crudo) y
estima tokens y costo del agente único a partir del preflight. Solo lectura; sin modelo."""
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(sys.argv[1])
sys.path.insert(0, str(ROOT))
from src.output_contract import PROMPT_D11, contexto_d11  # noqa: E402
from src.preprocessing.prompt_context import contexto_preprocesamiento  # noqa: E402
import src.agents.agente_auditor_final as auditor  # noqa: E402
import inspect  # noqa: E402

R1 = ROOT / "extracted_data/oficial-12casos-r1-20261028"
fuente = inspect.getsource(auditor.agente_auditor_final)
system_aud = eval(fuente.split("sys_instruction = (", 1)[1].split("\n    )\n", 1)[0].join("()"))  # literal
system_aud += PROMPT_D11

llamadas = defaultdict(list)
for l in open(R1 / "performance/llm_calls_items.jsonl", encoding="utf-8"):
    r = json.loads(l)
    llamadas[r["case_id"]].append(r["value"])

ratios = {}
for raw in sorted((R1 / "originals/predictions/experiments/nodex").glob("*/raw/*.raw.json")):
    d = json.loads(raw.read_text(encoding="utf-8"))
    s = d["estado_crudo"]
    pre = contexto_preprocesamiento(s.get("preprocessing_metadata"), s.get("parsing_warnings"))
    user = (f"DIAGNÓSTICO: {s.get('diagnostico')}\n"
            f"COMANDOS VALIDADOS: {s.get('comandos_mitigacion')}\n"
            f"CVEs ENCONTRADOS: {len(s.get('cves_encontrados', []))} CVEs\n"
            f"CONTEXTO RAG: {'Sí' if s.get('contexto_rag') else 'No'}" + (f"\n\n{pre}" if pre else ""))
    user += contexto_d11(s)
    chars = len(system_aud) + len(user)
    ultima = llamadas[d["case_id"]][-1]
    ratios[d["case_id"]] = dict(chars=chars, tokens=ultima["input_tokens"], ratio=chars / ultima["input_tokens"],
                                salida=ultima["output_tokens"], razon=ultima.get("reasoning_tokens") or 0)

for k, v in ratios.items():
    print(f"{k:28} chars={v['chars']:7} tokens={v['tokens']:6} chars/token={v['ratio']:.3f}")
print(json.dumps({"ratios": ratios}, ensure_ascii=False), file=open(sys.argv[2], "w", encoding="utf-8"))
