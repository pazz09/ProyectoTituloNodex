"""Nodo Tool: tool_validar_comandos.

Migrado desde la celda 22 del notebook de Colab.

Valida los comandos de mitigación contra la lista blanca de binarios y
patrones peligrosos de `src/tools/validation.py`.
"""

from src.state import LogGuardState
from src.tools.validation import validate_solution


def tool_validar_comandos(state: LogGuardState) -> dict:
    print("\n   🛡️ [Tool Validador] Verificando seguridad de los comandos...")
    validacion = validate_solution(state["comandos_mitigacion"])
    motivos_nuevos = [validacion["motivos"]] if not validacion["valido"] else []

    if validacion["valido"]:
        print("   ✅ Comandos aprobados.")
    else:
        print(f"   ❌ Comandos rechazados: {validacion['motivos']}")

    return {
        "comandos_validos": validacion["valido"],
        "motivos_rechazo": motivos_nuevos,
    }
