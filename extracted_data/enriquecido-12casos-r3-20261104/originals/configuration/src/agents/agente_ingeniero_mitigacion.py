"""Nodo LLM: agente_ingeniero_mitigacion.

Migrado desde la celda 22 del notebook de Colab.

Genera comandos de mitigación. Si `tool_validar_comandos` rechazó el
intento anterior, se autocorrige usando `motivos_rechazo`.
"""

from src.llm import llm_json
from src.state import LogGuardState


def agente_ingeniero_mitigacion(state: LogGuardState) -> dict:
    intentos = state.get("intentos_correccion", 0)
    print(f"\n👷 [Agente Mitigación] Generando comandos (intento {intentos + 1})...")

    sys_instruction = (
        "Eres un ingeniero de sistemas Linux experto en ciberseguridad. "
        "Genera comandos de mitigación seguros (iptables, fail2ban, ufw, etc.). "
        'Responde SOLO en JSON: {"comandos": ["cmd1", "cmd2", ...]}'
    )

    user_content = f"DIAGNÓSTICO: {state.get('diagnostico', '')}\n"

    if state.get("cves_encontrados"):
        user_content += f"\nCVEs RELACIONADOS: {state['cves_encontrados'][:2]}\n"

    if state.get("contexto_rag"):
        user_content += f"\nSOLUCIONES HISTÓRICAS SIMILARES: {state['contexto_rag']}\n"

    if state.get("comandos_validos") is False and state.get("motivos_rechazo"):
        print("   ⚠️ Autorreflexión: corrigiendo errores anteriores...")
        user_content += (
            f"\nCOMANDOS ANTERIORES RECHAZADOS POR:\n{state['motivos_rechazo']}\n"
            "Corrige los errores y genera comandos válidos."
        )

    respuesta = llm_json(user_content, system=sys_instruction)
    nuevos_comandos = respuesta.get("comandos", [])
    print(f"   → {len(nuevos_comandos)} comandos generados.")

    return {
        "comandos_mitigacion": nuevos_comandos,
        "intentos_correccion": intentos + 1,
    }
