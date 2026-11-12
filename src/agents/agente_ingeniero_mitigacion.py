"""Nodo LLM: agente_ingeniero_mitigacion.

Migrado desde la celda 22 del notebook de Colab.

Genera comandos de mitigación. Si `tool_validar_comandos` rechazó el
intento anterior, se autocorrige usando `motivos_rechazo`.
"""

import json

from src.llm import llm_json
from src.state import LogGuardState

#: M7 (NODEX final): reglas por veredicto preliminar. Antes el agente recibía
#: solo el texto del diagnóstico y un system que sugería iptables/fail2ban/ufw;
#: ante fallas operativas propuso abrir el firewall (`-j ACCEPT`), desbanear
#: IPs y escribir en /var/log.
_SISTEMA_CON_CONTEXTO = (
    "Eres un ingeniero de sistemas Linux con experiencia en respuesta a incidentes. "
    "Propón comandos según el VEREDICTO PRELIMINAR y la EVIDENCIA, con estas reglas: "
    "(1) normal: no propongas comandos (lista vacía). "
    "(2) anomalia_operativa: solo comandos de diagnóstico de SOLO LECTURA (revisar logs, "
    "estado de servicios y hardware, conectividad); ninguna regla de firewall ni cambio de "
    "configuración. "
    "(3) incidente_seguridad: contención proporcional y verificable, aplicada solo a las "
    "entidades (IP, puertos, servicios, usuarios) que aparecen en la evidencia. "
    "Nunca abras el firewall (-j ACCEPT, ufw allow), nunca desbanees (fail2ban-client unban), "
    "no uses comandos destructivos y no escribas ni redirijas salida fuera de {dir_salida}. "
    "Si no hay veredicto preliminar, actúa como en anomalia_operativa. "
    'Responde SOLO en JSON: {{"comandos": ["cmd1", "cmd2", ...]}}'
)


def _resumen_evidencia(state: LogGuardState) -> dict:
    """Lo que la mitigación necesita de la evidencia, sin las filas completas."""
    contenido = state.get("contenido_lote") or {}
    perfil = (state.get("resumen_logs") or {}).get("perfil_lote") or {}
    if contenido.get("tipo") == "red" or perfil.get("tipo") == "red":
        senales = perfil.get("senales") or {}
        return {"tipo": "red",
                "flujos_senalados": [{k: f.get(k) for k in ("group_id", "clave", "conteo", "motivos")}
                                     for f in (contenido.get("flujos_minoritarios") or [])],
                "barridos_de_puertos": senales.get("barrido_de_puertos") or [],
                "inversion_de_rol": senales.get("inversion_de_rol") or []}
    altas = (perfil.get("lineas_severidad_alta") or {}).get("lineas") or []
    # El texto de cada línea está en el contenido del lote (`[uid] línea`).
    texto_por_uid = {}
    for linea in contenido.get("lineas") or []:
        if linea.startswith("[") and "] " in linea:
            uid, texto = linea[1:].split("] ", 1)
            texto_por_uid[uid] = texto[:300]
    return {"tipo": "texto", "severidades": perfil.get("severidades"),
            "componentes": perfil.get("componentes"),
            "lineas_severidad_alta": [{"uid": l.get("uid"), "severidad": l.get("severidad"),
                                       "group_id": l.get("group_id"), "linea": texto_por_uid.get(l.get("uid"))}
                                      for l in altas[:15]]}


def agente_ingeniero_mitigacion(state: LogGuardState) -> dict:
    from src.config import MITIGACION_CON_CONTEXTO, MITIGACION_DIR_SALIDA

    intentos = state.get("intentos_correccion", 0)
    print(f"\n👷 [Agente Mitigación] Generando comandos (intento {intentos + 1})...")

    if MITIGACION_CON_CONTEXTO:
        sys_instruction = _SISTEMA_CON_CONTEXTO.format(dir_salida=MITIGACION_DIR_SALIDA)
    else:
        sys_instruction = (
            "Eres un ingeniero de sistemas Linux experto en ciberseguridad. "
            "Genera comandos de mitigación seguros (iptables, fail2ban, ufw, etc.). "
            'Responde SOLO en JSON: {"comandos": ["cmd1", "cmd2", ...]}'
        )

    user_content = f"DIAGNÓSTICO: {state.get('diagnostico', '')}\n"
    if MITIGACION_CON_CONTEXTO:
        # Fase B: el veredicto consolidado (triage + hallazgos alto del cazador)
        # manda sobre el preliminar cuando existe.
        consolidado = state.get("veredicto_consolidado")
        veredicto = consolidado or state.get("veredicto_preliminar") or "sin veredicto preliminar"
        etiqueta = "VEREDICTO CONSOLIDADO" if consolidado else "VEREDICTO PRELIMINAR"
        user_content += (f"\n{etiqueta}: {veredicto}"
                         + (f" ({state['justificacion_veredicto_preliminar']})"
                            if state.get("justificacion_veredicto_preliminar") else "")
                         + "\nEVIDENCIA: " + json.dumps(_resumen_evidencia(state), ensure_ascii=False) + "\n")
        hallazgos = [h for h in state.get("hallazgos_cazador") or [] if h.get("nivel_sospecha") in ("alto", "medio")]
        if hallazgos:
            user_content += "HALLAZGOS DEL CAZADOR (alto/medio): " + json.dumps(hallazgos, ensure_ascii=False) + "\n"

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
