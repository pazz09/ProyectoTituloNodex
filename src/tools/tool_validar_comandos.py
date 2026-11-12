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

    # M7 (NODEX final): cada comando rechazado queda registrado con su motivo y
    # el intento de corrección en que se propuso (se acumula en el estado).
    intento = state.get("intentos_correccion", 0)
    rechazados = [dict(r, intento=intento) for r in validacion.get("rechazados", [])]
    if rechazados:
        print(f"   → {len(rechazados)} comando(s) rechazado(s) en el intento {intento}.")
    return {
        "comandos_validos": validacion["valido"],
        "motivos_rechazo": motivos_nuevos,
        "comandos_rechazados": rechazados,
    }
