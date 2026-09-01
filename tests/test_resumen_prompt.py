"""Tests de `acotar_resumen_para_prompt` (src/tools/resumen_prompt.py).

Motivación (hallazgo real, 25-ago-2026): el prompt de `agente_analista_triage`
serializaba `resumen_logs` completo, incluyendo el desglose por_ip/
ips_distintas/reputacion_ips -- uno por cada IP distinta del lote. HDFS_2k.log
(202 IPs) disparó 58 289 tokens de entrada en triage vs. 1 096 de BGL_2k.log
(2 IPs), para lotes del mismo tamaño (2000 líneas): el costo escalaba con
cardinalidad de IPs, no con líneas de log. Estos tests son deterministas y no
llaman al LLM ni a `src.llm` -- construyen `resumen_logs` sintéticos con la
misma forma que produce `aggregate_logs()`.
"""

from src.tools.resumen_prompt import acotar_resumen_para_prompt


def _resumen_con_n_ips(n: int, ip_maliciosa_baja_actividad: str | None = None) -> dict:
    """Arma un `resumen_logs` sintético con `n` IPs limpias (n_eventos
    decreciente, la primera es la más activa) y, opcionalmente, una IP extra
    con reputación maliciosa pero la actividad más baja de todas -- el caso
    que el acotamiento no puede permitirse esconder."""
    ips = [f"10.0.0.{i}" for i in range(n)]
    por_ip = {
        ip: {"intentos_fallidos": (n - i), "usuarios_objetivo": [], "servicios": ["sshd"],
             "n_eventos": (n - i)}
        for i, ip in enumerate(ips)
    }
    reputacion = {ip: {"categoria": "limpio"} for ip in ips}
    if ip_maliciosa_baja_actividad:
        ips.append(ip_maliciosa_baja_actividad)
        por_ip[ip_maliciosa_baja_actividad] = {
            "intentos_fallidos": 1, "usuarios_objetivo": [], "servicios": ["sshd"], "n_eventos": 1,
        }
        reputacion[ip_maliciosa_baja_actividad] = {"categoria": "malicioso"}
    ips_ordenadas = sorted(ips, key=lambda ip: por_ip[ip]["n_eventos"], reverse=True)
    return {
        "formato_detectado": "auth_log",
        "total_lineas": n * 3,
        "servicios": {"sshd": n},
        "eventos": {"acceso_fallido": n},
        "ventana_temporal": {"inicio": "t0", "fin": "t1"},
        "n_ips_distintas": len(ips_ordenadas),
        "ips_distintas": ips_ordenadas,
        "por_ip": por_ip,
        "reputacion_ips": reputacion,
    }


def test_lote_pequeno_no_se_toca():
    resumen = _resumen_con_n_ips(5)
    acotado = acotar_resumen_para_prompt(resumen, top_n=20)
    assert acotado is resumen  # nada que acotar -- ni siquiera se copia
    assert "ips_resumidas" not in acotado


def test_lote_grande_se_acota_a_top_n():
    resumen = _resumen_con_n_ips(50)
    acotado = acotar_resumen_para_prompt(resumen, top_n=20)
    assert len(acotado["ips_distintas"]) == 20
    assert len(acotado["por_ip"]) == 20
    assert len(acotado["reputacion_ips"]) == 20
    # las incluidas son justo las 20 más activas, en el mismo orden
    assert acotado["ips_distintas"] == resumen["ips_distintas"][:20]


def test_n_ips_distintas_no_se_trunca():
    resumen = _resumen_con_n_ips(50)
    acotado = acotar_resumen_para_prompt(resumen, top_n=20)
    assert acotado["n_ips_distintas"] == 50  # conteo real del lote, no el acotado


def test_resto_se_agrega_correctamente():
    resumen = _resumen_con_n_ips(25)
    acotado = acotar_resumen_para_prompt(resumen, top_n=20)
    resto_esperado = resumen["ips_distintas"][20:]
    resto = acotado["ips_resumidas"]
    assert resto["cantidad"] == len(resto_esperado) == 5
    assert resto["total_eventos"] == sum(
        resumen["por_ip"][ip]["n_eventos"] for ip in resto_esperado
    )
    assert resto["total_intentos_fallidos"] == sum(
        resumen["por_ip"][ip]["intentos_fallidos"] for ip in resto_esperado
    )


def test_ip_maliciosa_de_baja_actividad_no_se_pierde():
    resumen = _resumen_con_n_ips(30, ip_maliciosa_baja_actividad="203.0.113.99")
    acotado = acotar_resumen_para_prompt(resumen, top_n=20)

    assert "203.0.113.99" in acotado["ips_distintas"]
    assert "203.0.113.99" in acotado["por_ip"]
    assert acotado["reputacion_ips"]["203.0.113.99"]["categoria"] == "malicioso"
    # y no debe contarse dentro del resumen agregado del resto
    assert acotado["ips_resumidas"]["cantidad"] == 30 - 20  # 10 IPs limpias de baja actividad
    assert len(acotado["por_ip"]) == 21  # 20 top + la maliciosa


def test_resumen_sin_reputacion_ips_no_falla():
    """Si `reputacion_ips` no está en el resumen (p. ej. AbuseIPDB no
    configurado), el acotamiento igual funciona -- solo no puede rescatar
    IPs por reputación, se limita al top_n por actividad."""
    resumen = _resumen_con_n_ips(30)
    del resumen["reputacion_ips"]
    acotado = acotar_resumen_para_prompt(resumen, top_n=20)
    assert len(acotado["ips_distintas"]) == 20
    assert "reputacion_ips" not in acotado
    assert acotado["ips_resumidas"]["cantidad"] == 10
