"""NODEX final, Fase A: M1 (contexto), M2 (perfil), M6 (grupos), M7 (mitigación), M8 (veredicto), M9.

Sin API: el modelo se simula. Los lotes son sintéticos y se construyen en cada prueba; ninguna
prueba abre casos de la partición de evaluación ni su ground truth.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

import src.config as config
from src.output_contract import (PROMPT_D11, PROMPT_D11_ORIGINAL, campos_d11, clasificacion_detallada,
                                 contexto_d11, normalizar_d11)
from src.preprocessing.perfil_lote import analizar_lote, linea_sin_etiqueta
from src.preprocessing.pipeline import preprocesar
from src.preprocessing.prompt_context import contexto_contenido_lote
from src.tools.validation import validate_solution

# --- lotes sintéticos ----------------------------------------------------------

_BGL = ("{ep} 2005.06.03 R02-M1-N0-C:J12-U11 2005-06-03-15.42.{s:02d}.{us:06d} R02-M1-N0-C:J12-U11 "
        "RAS {comp} {sev} {msg}")


def lote_bgl(con_flag=False, n=6):
    lineas = []
    for i in range(n):
        sev, comp = ("FATAL", "KERNEL") if i == 2 else ("INFO", "KERNEL" if i % 2 else "APP")
        linea = _BGL.format(ep=1117838570 + i, s=i, us=i * 1000, comp=comp, sev=sev,
                            msg=f"instruction cache parity error corrected {i}")
        if con_flag:
            linea = ("KERNDTLB " if i == 2 else "- ") + linea
        lineas.append(linea)
    return "\n".join(lineas) + "\n"


_COLUMNAS = ("uid,ts,datetime,src_ip_zeek,src_port_zeek,dest_ip_zeek,dest_port_zeek,proto,service,duration,"
             "orig_bytes,resp_bytes,conn_state,local_orig,local_resp,missed_bytes,history,orig_pkts,"
             "orig_ip_bytes,resp_pkts,resp_ip_bytes,community_id")


def fila(uid, t, src, dst, dport, proto="tcp", service="-", state="SF", ob="10", rb="10", history="ShADad"):
    dt = str(datetime.fromtimestamp(t, tz=timezone.utc).replace(tzinfo=None))
    return f"{uid},{t},{dt},{src},40000,{dst},{dport},{proto},{service},0.5,{ob},{rb},{state},F,F,0,{history},2,100,2,100,1:x{uid}="


def lote_red():
    """30 consultas DNS UDP sin respuesta (S0), un barrido TCP de 20 puertos, una transferencia
    grande, un par raro y una IP que casi siempre es origen y aparece como destino de SSH."""
    filas, t = [], 1639746000.0
    for i in range(30):
        filas.append(fila(f"Cdns{i:03d}", t + i, "10.0.0.5", "10.0.0.1", 53, "udp", "dns", "S0", "40", "0", "D"))
    for p in range(20):
        filas.append(fila(f"Cscan{p:03d}", t + 40 + p * 0.01, "10.0.0.9", "10.0.0.20", 1000 + p, "tcp", "-", "REJ",
                          "0", "0", "S"))
    filas.append(fila("Cbig000", t + 70, "10.0.0.5", "10.0.0.30", 443, "tcp", "ssl", "SF", "900000", "5000000"))
    filas.append(fila("Cssh000", t + 80, "10.0.0.3", "10.0.0.5", 22, "tcp", "ssh", "SF"))
    return _COLUMNAS + "\n" + "\n".join(filas) + "\n"


def estado_de(raw):
    from src.pipeline import _preparar_estado_inicial
    estado, _, _ = _preparar_estado_inicial(raw, "prueba_fase_a")
    return estado


# --- M2: BGL y UDP -------------------------------------------------------------

def test_bgl_sin_campo_de_alerta_se_enriquece_y_no_emite_etiqueta():
    resultado = preprocesar(lote_bgl(con_flag=False))
    assert resultado.cobertura == 1.0
    assert resultado.ground_truth == []
    assert [e.severity for e in resultado.events][:3] == ["INFO", "INFO", "FATAL"]
    assert resultado.events[2].service_name == "bgl.kernel"
    assert resultado.events[2].message.startswith("instruction cache parity error")


def test_bgl_con_campo_de_alerta_lo_desvia_y_no_llega_al_prompt():
    raw = lote_bgl(con_flag=True)
    resultado = preprocesar(raw)
    assert [g.label for g in resultado.ground_truth].count("Alert") == 1
    estado = estado_de(raw)
    texto = contexto_contenido_lote(estado["contenido_lote"]) + json.dumps(estado["evidencia_logs"])
    assert "KERNDTLB" not in texto
    assert all(not linea.split("] ", 1)[1].startswith("- ") for linea in estado["contenido_lote"]["lineas"])


def test_s0_en_udp_no_es_intento_fallido_pero_en_tcp_si(monkeypatch):
    estado = estado_de(lote_red())
    assert estado["resumen_logs"]["eventos"] == {"evento_critico": 20, "evento_normal": 32}
    assert estado["resumen_logs"]["por_ip"]["10.0.0.5"]["intentos_fallidos"] == 0
    monkeypatch.setattr(config, "UDP_S0_NO_ES_FALLO", False)
    assert estado_de(lote_red())["resumen_logs"]["eventos"]["evento_critico"] == 50


# --- M2/M6: perfil y grupos ------------------------------------------------------

def test_perfil_de_red_detecta_las_senales_genericas():
    analisis = analizar_lote(preprocesar(lote_red()))
    perfil, senales = analisis["perfil_lote"], analisis["perfil_lote"]["senales"]
    assert perfil["tipo"] == "red" and perfil["filas"] == 52
    assert senales["barrido_de_puertos"] == [{"origen": "10.0.0.9", "destino": "10.0.0.20", "protocolo": "tcp",
                                              "puertos_distintos": 20, "conexiones": 20}]
    valores = {(m["tipo"], m["valor"]) for m in senales["servicio_o_protocolo_minoritario"]}
    assert ("servicio", "ssl") in valores and ("servicio", "ssh") in valores
    assert not any(v.startswith("puerto:10") for _, v in valores)          # el barrido no es "minoritario"
    assert senales["transferencias_atipicas"]["filas"][0]["uid"] == "Cbig000"
    assert senales["inversion_de_rol"][0]["ip"] == "10.0.0.5"
    assert perfil["por_origen"]["10.0.0.9"]["puertos_destino_distintos"] == 20


def test_un_barrido_es_un_solo_grupo_y_los_grupos_son_estables():
    analisis = analizar_lote(preprocesar(lote_red()))
    grupos = analisis["grupos_evidencia"]
    barrido = [g for g in grupos if g["clave"]["servicio_o_puerto"] == "barrido_de_puertos"]
    assert len(barrido) == 1 and barrido[0]["conteo"] == 20
    assert [g["group_id"] for g in grupos] == [f"G{i:02d}" for i in range(1, len(grupos) + 1)]
    assert analizar_lote(preprocesar(lote_red()))["grupos_evidencia"] == grupos
    assert sum(g["conteo"] for g in grupos) == 52


def test_flujos_minoritarios_reparten_el_tope_por_turnos(monkeypatch):
    monkeypatch.setattr(config, "PERFIL_MAX_FILAS_MINORITARIAS", 5)
    analisis = analizar_lote(preprocesar(lote_red()))
    flujos = analisis["contenido_lote"]["flujos_minoritarios"]
    assert flujos[0]["motivos"] == ["barrido_de_puertos"]
    assert sum(len(f["filas"]) for f in flujos) == 5
    assert all(len(f["filas"]) >= 1 for f in flujos[:3])                  # el barrido no acapara el tope
    assert analisis["contenido_lote"]["filas_omitidas"] == sum(f["conteo"] for f in flujos) - 5
    fila_barrido = flujos[0]["filas"][0]
    assert {"uid", "source_ip", "destination_port", "conn_state", "history", "orig_bytes"} <= set(fila_barrido)


def test_perfil_de_texto_y_grupos_por_plantilla():
    analisis = analizar_lote(preprocesar(lote_bgl()))
    perfil = analisis["perfil_lote"]
    assert perfil["tipo"] == "texto"
    assert perfil["severidades"] == {"INFO": 5, "FATAL": 1}
    assert perfil["lineas_severidad_alta"]["total"] == 1
    # Las líneas INFO de un mismo componente difieren solo en números: misma plantilla.
    claves = [g["clave"] for g in analisis["grupos_evidencia"]]
    assert all("<n>" in c["plantilla"] for c in claves)
    assert len(analisis["grupos_evidencia"]) == 3


# --- M1: contexto ------------------------------------------------------------------

def test_contenido_de_texto_entrega_todas_las_lineas_y_avisa_el_recorte(monkeypatch):
    estado = estado_de(lote_bgl())
    bloque = contexto_contenido_lote(estado["contenido_lote"])
    assert bloque.count("[log_record_") == 6 and "ATENCIÓN" not in bloque
    monkeypatch.setattr(config, "TRIAGE_MAX_LINEAS", 2)
    recortado = contexto_contenido_lote(estado_de(lote_bgl())["contenido_lote"])
    assert recortado.count("[log_record_") == 2 and "se entregan 2 de 6 líneas" in recortado
    monkeypatch.setattr(config, "CONTEXTO_LOTE_COMPLETO", False)
    assert contexto_contenido_lote(estado["contenido_lote"]) == ""


def test_catalogo_lleva_mensaje_en_texto_y_campos_de_red():
    bgl = estado_de(lote_bgl())["evidencia_logs"]
    assert bgl[2]["message"].startswith("instruction cache parity error") and bgl[2]["severity"] == "FATAL"
    assert bgl[0]["group_id"].startswith("G")
    red = {e["uid"]: e for e in estado_de(lote_red())["evidencia_logs"]}
    assert red["Cbig000"]["orig_bytes"] == "900000" and red["Cbig000"]["duration"] == "0.5"
    assert red["Cdns000"]["history"] == "D"


def test_linea_sin_etiqueta_no_toca_lineas_sin_campo():
    evento = preprocesar(lote_bgl()).events[0]
    assert linea_sin_etiqueta(evento).startswith("1117838570 ")


def test_triage_y_agente_unico_reciben_el_mismo_contenido(monkeypatch):
    import src.agents.agente_analista_triage as triage
    import src.single_agent as single
    estado = estado_de(lote_bgl())
    bloque = contexto_contenido_lote(estado["contenido_lote"])
    vistos = {}

    def falso_triage(prompt, system=None, **_):
        vistos["triage"], vistos["system"] = prompt, system
        return {"necesita_rag": False, "diagnostico": "Error de paridad corregido",
                "veredicto_preliminar": "anomalia_operativa", "justificacion_veredicto": "línea FATAL"}

    monkeypatch.setattr(triage, "llm_json", falso_triage)
    salida = triage.agente_analista_triage(estado)
    assert bloque in vistos["triage"] and "veredicto_preliminar" in vistos["system"]
    assert salida["veredicto_preliminar"] == "anomalia_operativa"

    def falso_unico(prompt, system=None, **_):
        vistos["unico"] = prompt
        return {"diagnostico": "x", "hay_anomalia": True, "hay_incidente": False, "confianza": 0.8,
                "evaluacion": "x", "comandos_mitigacion": [], "eventos_reconstruidos": [],
                "secuencia_temporal": [], "tecnicas_atribuidas": []}

    monkeypatch.setattr(single, "llm_json", falso_unico)
    resultado = single.analizar_lote_agente_unico(lote_bgl())
    assert bloque in vistos["unico"]
    assert resultado["classification_detallada"] == "anomalia_operativa"


# --- M8 ---------------------------------------------------------------------------

def test_veredicto_fuera_del_vocabulario_queda_en_none(monkeypatch):
    import src.agents.agente_analista_triage as triage
    monkeypatch.setattr(triage, "llm_json", lambda *a, **k: {
        "necesita_rag": False, "diagnostico": "d", "veredicto_preliminar": "ataque!"})
    assert triage.agente_analista_triage(estado_de(lote_bgl()))["veredicto_preliminar"] is None


@pytest.mark.parametrize("estado, esperado", [
    ({"hay_incidente": True, "hay_anomalia": True}, "incidente_seguridad"),
    ({"hay_incidente": False, "hay_anomalia": True}, "anomalia_operativa"),
    ({"hay_incidente": False, "hay_anomalia": False}, "normal"),
    ({"hay_incidente": None, "hay_anomalia": True}, None),
])
def test_clasificacion_detallada(estado, esperado):
    assert clasificacion_detallada(estado) == esperado
    assert campos_d11(estado)["classification_detallada"] == esperado


def test_el_adaptador_agrega_la_clasificacion_detallada_sin_cambiar_classification():
    from src.experimentation.adapters.nodex import adaptar
    estado = {"hay_incidente": False, "hay_anomalia": True, "diagnostico": "falla de disco",
              "evaluacion_auditor": "x"}
    salida = adaptar(estado, "c", "r", "operativa", ("deteccion",)).salida.to_dict()
    assert salida["classification"] == "MALICIOUS"
    assert salida["_meta"]["classification_detallada"] == "anomalia_operativa"


# --- M6: contrato -------------------------------------------------------------------

def test_prompt_d11_pide_toda_la_evidencia_por_grupos():
    assert PROMPT_D11 != PROMPT_D11_ORIGINAL
    assert "evidence_groups" in PROMPT_D11 and "TODA la evidencia" in PROMPT_D11
    assert "SOLO eventos relevantes" not in PROMPT_D11 and "no inventes UIDs" in PROMPT_D11


def test_normalizar_expande_grupos_y_cuenta_los_inexistentes():
    evidencia = [{"uid": u, "timestamp": None} for u in ("A", "B", "C", "D")]
    grupos = [{"group_id": "G01", "uids": ["A", "B"]}, {"group_id": "G02", "uids": ["C", "X"]}]
    respuesta = {"eventos_reconstruidos": [
        {"event_id": "event_001", "evidence_groups": ["G01", "G09"], "evidence_uids": ["B", "D", "Z"],
         "timestamp": None, "event_type": "x", "description": "d"},
        {"event_id": "event_002", "evidence_groups": ["G02"], "timestamp": None, "event_type": "y",
         "description": "d"}],
        "secuencia_temporal": [], "tecnicas_atribuidas": [
        {"technique_id": "T1046", "evidence_groups": ["G01"], "justification": "j"}]}
    copia = json.loads(json.dumps(respuesta))
    r = normalizar_d11(respuesta, evidencia, grupos)
    assert respuesta == copia                                             # no muta la respuesta
    assert r["eventos_reconstruidos"][0]["evidence_uids"] == ["A", "B", "D"]
    assert r["eventos_reconstruidos"][0]["evidence_groups"] == ["G01"]
    assert r["eventos_reconstruidos"][1]["evidence_uids"] == ["C"]     # X no está en el catálogo
    assert r["tecnicas_atribuidas"][0]["evidence_uids"] == ["A", "B"]
    assert r["invalid_evidence_uid_count"] == 2 and r["invalid_evidence_group_count"] == 1


def test_contexto_d11_incluye_la_tabla_de_grupos_sin_repetir_uids():
    estado = estado_de(lote_red())
    texto = contexto_d11(estado)
    tabla = json.loads(texto.split("todos sus uids):\n", 1)[1].split("\nCANDIDATOS", 1)[0])
    assert [g["group_id"] for g in tabla] == [g["group_id"] for g in estado["grupos_evidencia"]]
    assert all(set(g) == {"group_id", "clave", "conteo"} for g in tabla)


# --- M7 -----------------------------------------------------------------------------

@pytest.mark.parametrize("comando, motivo", [
    ("iptables -A INPUT -s 10.0.0.9 -j ACCEPT", "ABRE_FIREWALL"),
    ("ufw allow 22/tcp", "ABRE_FIREWALL"),
    ("fail2ban-client set sshd unbanip 10.0.0.9", "ABRE_FIREWALL"),
    ("iptables -F", "ABRE_FIREWALL"),
    ("echo alerta >> /var/log/syslog", "ESCRITURA_FUERA_DE_DIRECTORIO"),
    ("journalctl -u sshd | tee /etc/reporte.txt", "ESCRITURA_FUERA_DE_DIRECTORIO"),
    ("sed -i 's/a/b/' /etc/ssh/sshd_config", "ESCRITURA_FUERA_DE_DIRECTORIO"),
    ("rm -rf /tmp/datos", "DESTRUCTIVO"),
    ("reboot", "DESTRUCTIVO"),
])
def test_validador_estricto_rechaza(comando, motivo):
    resultado = validate_solution([comando])
    assert resultado["valido"] is False and resultado["n_rechazados"] == 1
    assert any(m.startswith(motivo) for m in resultado["rechazados"][0]["motivos"])


@pytest.mark.parametrize("comando", [
    "iptables -A INPUT -s 10.0.0.9 -j DROP",
    "journalctl -u sshd --since today",
    "dmesg | grep -i error",
    "echo revisado > /var/tmp/nodex/estado.txt",
    "smartctl -a /dev/sda 2>/dev/null",
    "sudo ss -tunap",
])
def test_validador_estricto_acepta(comando):
    assert validate_solution([comando])["valido"] is True


def test_tool_validar_registra_los_rechazos_con_el_intento():
    from src.tools.tool_validar_comandos import tool_validar_comandos
    salida = tool_validar_comandos({"comandos_mitigacion": ["ufw allow 22", "dmesg"], "intentos_correccion": 2})
    assert salida["comandos_validos"] is False
    assert salida["comandos_rechazados"] == [{"comando": "ufw allow 22", "motivos": [
        "ABRE_FIREWALL: abre o desactiva ufw"], "intento": 2}]


def test_mitigacion_recibe_veredicto_y_evidencia(monkeypatch):
    import src.agents.agente_ingeniero_mitigacion as mitigacion
    estado = estado_de(lote_red())
    estado.update(diagnostico="barrido de puertos", veredicto_preliminar="incidente_seguridad",
                  justificacion_veredicto_preliminar="20 puertos")
    visto = {}

    def falso(prompt, system=None, **_):
        visto["prompt"], visto["system"] = prompt, system
        return {"comandos": []}

    monkeypatch.setattr(mitigacion, "llm_json", falso)
    mitigacion.agente_ingeniero_mitigacion(estado)
    assert "VEREDICTO PRELIMINAR: incidente_seguridad" in visto["prompt"]
    evidencia = json.loads(visto["prompt"].split("EVIDENCIA: ", 1)[1])
    assert evidencia["barridos_de_puertos"][0]["origen"] == "10.0.0.9"
    assert "solo comandos de diagnóstico de SOLO LECTURA" in visto["system"]
    assert "iptables, fail2ban, ufw, etc." not in visto["system"]


# --- M9 ------------------------------------------------------------------------------

@pytest.mark.parametrize("ts", [1639746045.251239, 1639746045.0, 1639746045.5, 1639746045.12])
def test_formato_rebasado_sigue_la_regla_del_fondo(ts):
    from src.experimentation.datasets.uwf_casos import _formato_del_fondo
    texto_ts, texto_dt = _formato_del_fondo(ts)
    assert texto_ts == repr(ts)
    assert texto_dt == str(datetime.fromtimestamp(ts, tz=timezone.utc).replace(tzinfo=None))
    assert ("." in texto_dt) == (ts != int(ts))


def test_la_regeneracion_no_escribe_en_experiments(tmp_path):
    from src.experimentation.datasets.regenerar import regenerar
    raiz = Path(__file__).resolve().parents[1]
    for destino in (raiz / "experiments", raiz):
        with pytest.raises(ValueError):
            regenerar(raiz, destino, ("desarrollo",))


def test_comparar_detecta_cambios_que_no_son_de_formato(tmp_path):
    from src.experimentation.datasets.regenerar import comparar_con_original
    raiz, destino = tmp_path / "repo", tmp_path / "nuevo"
    original = fila("Cx", 1639746045.251, "10.0.0.1", "10.0.0.2", 80)
    for base, linea in ((raiz / "experiments", original),
                        (destino, original.replace("10.0.0.2", "10.0.0.3"))):
        (base / "cases/uwf/desarrollo").mkdir(parents=True)
        (base / "ground_truth/uwf/desarrollo").mkdir(parents=True)
        (base / "cases/uwf/desarrollo/c.csv").write_text(_COLUMNAS + "\n" + linea + "\n", encoding="utf-8")
    r = comparar_con_original(raiz, destino, "uwf", "desarrollo")
    assert not r["solo_cambia_el_formato"] and "dest_ip_zeek" in r["problemas"][0]
