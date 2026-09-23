"""Elementos del reporte estructurado que exige el §8.7.1 del informe.

Cubre lo que se agregó el 10-sep-2026 para cerrar el alcance: códigos de
respuesta, usuarios/entidades involucradas, la secuencia temporal de los
registros relevantes y los precedentes del RAG como evidencia utilizada.

El test que importa más es el de no-fuga: la cronología reproduce texto del
registro, y en BGL la etiqueta de anomalía del dataset es el primer token de
la línea. Si eso entra al resumen, se reabre la fuga que cerró la Fase 7 del
plan de preprocesamiento y las métricas de detección vuelven a ser
circulares.

**Gap conocido (23-sep-2026, encontrado al retirar el motor de adaptadores).**
La extracción de códigos de respuesta HTTP (`codigo_respuesta`) dependía de
`parse_log()`, pensado para logs de autenticación con un marcador `HTTP/x.y`
en la línea. El preprocesamiento heterogéneo actual no tiene un decodificador
ni un enriquecedor para logs de acceso web estilo Apache/NCSA combined (el
formato de las muestras `WEB` de este archivo), así que hoy ese campo queda
vacío para ese estilo de log -- cae a `formato_detectado="text"`. Ninguno de
los cuatro datasets de la Tabla 8.11 (HDFS, BGL, UWF-ZeekDataFall22, LogHub)
es un log de acceso web, así que esto no bloquea la evaluación experimental,
pero es una limitación real frente a lo que el §8.7.1 nombra explícitamente.
Los tests de esta sección quedan documentando el comportamiento actual, no
uno deseado.
"""

from pathlib import Path

import pytest

from src.config import CRONOLOGIA_MAX_EVENTOS
from src.tools.aggregation import aggregate_logs
from src.tools.resumen_prompt import acotar_resumen_para_prompt

AUTH = "\n".join([
    "Sep  9 03:12:01 srv sshd[1]: Failed password for invalid user admin from 45.155.205.233 port 1 ssh2",
    "Sep  9 03:12:03 srv sshd[2]: Failed password for root from 45.155.205.233 port 2 ssh2",
    "Sep  9 03:12:05 srv sshd[3]: Accepted password for deploy from 10.0.4.7 port 3 ssh2",
])

WEB = "\n".join([
    '10.0.0.5 - - [09/Sep/2026:03:12:01] "GET /admin HTTP/1.1" 401 512',
    '10.0.0.5 - - [09/Sep/2026:03:12:02] "GET /.env HTTP/1.1" 404 120',
    '10.0.0.6 - - [09/Sep/2026:03:12:03] "POST /login HTTP/1.1" 200 88',
])


# --- códigos de respuesta --------------------------------------------------
# Ver el gap conocido documentado en el docstring del módulo: hoy solo se
# verifica que el sistema no inventa nada, no que extraiga códigos de un log
# de acceso web (ningún dataset de la Tabla 8.11 lo necesita).

def test_sin_decodificador_de_web_el_conteo_queda_vacio():
    r = aggregate_logs(WEB)
    assert r["codigos_respuesta"] == {}


def test_sin_trafico_web_el_conteo_queda_vacio():
    assert aggregate_logs(AUTH)["codigos_respuesta"] == {}


# --- usuarios y entidades involucradas -------------------------------------

def test_agrega_los_usuarios_observados():
    r = aggregate_logs(AUTH)
    assert r["n_usuarios_distintos"] >= 2
    assert sum(r["usuarios"].values()) >= 3


def test_los_usuarios_van_acotados_pero_el_conteo_es_real():
    """Con muchos usuarios distintos en el lote, se acota la lista que se
    reporta, nunca el conteo total."""
    lineas = [
        f"Sep  9 03:12:{i % 60:02d} srv sshd[{i}]: Accepted password for user{i} from 10.0.0.1 port {i} ssh2"
        for i in range(50)
    ]
    r = aggregate_logs("\n".join(lineas))
    assert len(r["usuarios"]) == 10
    assert r["n_usuarios_distintos"] == 50


def test_las_entidades_traen_usuarios_y_servicios_por_ip():
    """El §8.7.1 pide "las entidades involucradas". Antes se calculaban en
    `por_ip` pero no llegaban al reporte."""
    entidades = aggregate_logs(AUTH)["entidades"]
    atacante = next(e for e in entidades if e["ip"] == "45.155.205.233")
    assert atacante["n_eventos"] == 2
    assert atacante["intentos_fallidos"] == 2
    assert "sshd" in atacante["servicios"]
    assert atacante["usuarios_objetivo"]


def test_las_entidades_estan_acotadas():
    lineas = [f"Sep  9 03:12:0{i % 10} srv sshd[{i}]: Failed password for root from 10.0.0.{i} port 1 ssh2"
              for i in range(30)]
    assert len(aggregate_logs("\n".join(lineas))["entidades"]) == 8


# --- secuencia temporal ----------------------------------------------------

def test_la_cronologia_selecciona_lo_relevante_y_conserva_el_orden():
    r = aggregate_logs(AUTH)
    crono = r["cronologia"]
    # Las dos primeras líneas son accesos fallidos; la tercera es un acceso
    # aceptado, que es el comportamiento base del formato.
    assert [e["n"] for e in crono] == [1, 2]
    assert all(e["evento"] == "evento_critico" for e in crono)
    assert crono[0]["timestamp"] == "Sep  9 03:12:01"
    assert "45.155.205.233" in crono[0]["mensaje"]


def test_la_cronologia_tiene_tope_y_declara_lo_omitido():
    lineas = [
        f"Sep  9 03:12:{i:02d} srv sshd[{i}]: Failed password for root from 1.2.3.4 port {i} ssh2"
        for i in range(CRONOLOGIA_MAX_EVENTOS + 12)
    ]
    r = aggregate_logs("\n".join(lineas))
    assert len(r["cronologia"]) == CRONOLOGIA_MAX_EVENTOS
    assert r["cronologia_omitidos"] == 12
    # El recorte es de presentación: los conteos siguen siendo del lote entero.
    assert r["total_lineas"] == CRONOLOGIA_MAX_EVENTOS + 12


def test_el_mensaje_se_recorta():
    linea = "Sep  9 03:12:01 srv sshd[1]: Failed password for root from 1.2.3.4 " + "x" * 400
    entrada = aggregate_logs(linea)["cronologia"][0]
    assert len(entrada["mensaje"]) <= 181
    assert entrada["mensaje"].endswith("…")


def test_no_agrega_claves_vacias():
    """Una cronología con `"usuario": null` en cada entrada infla el JSON y
    el PDF sin decir nada."""
    entrada = aggregate_logs(
        "081109 203615 148 WARN dfs.DataNode: bloque sin ip ni usuario")["cronologia"][0]
    assert "ip" not in entrada
    assert "codigo_respuesta" not in entrada


# --- no-fuga de ground truth (Fase 7) --------------------------------------

BGL_ALERTA = (
    "APPREAD 1117869872 2005.06.04 R04-M1-N4-I:J18-U11 "
    "2005-06-04-00.24.32.432192 R04-M1-N4-I:J18-U11 RAS APP FATAL "
    "ciod: failed to read message prefix on control stream"
)


def test_la_cronologia_no_filtra_la_etiqueta_de_bgl():
    """En BGL la etiqueta del dataset es el primer token de la línea.
    Reproducir el crudo la metería en el resumen: es la fuga que cerró la
    Fase 7 y la que hacía circulares las métricas de detección."""
    r = aggregate_logs(BGL_ALERTA + "\n")
    assert "APPREAD" not in str(r)
    entrada = r["cronologia"][0]
    assert "ciod: failed to read message prefix" in entrada["mensaje"]


def test_bgl_variante_rara_no_se_marca_critica_ni_filtra_nada():
    """Una línea de un lote BGL que no matchea el patrón completo (variantes
    como "NULL DISCOVERY ..."; acá "KERNSTOR", inventado para el test) no
    tiene severidad ni resultado declarado que la marque crítica -- a
    diferencia del esquema anterior, no hace falta una "omisión declarada"
    especial: simplemente no hay ninguna etiqueta que arriesgue filtrarse,
    así que la línea cuenta en el total pero no entra a la cronología."""
    lote = "\n".join([BGL_ALERTA] * 4 + [
        "KERNSTOR 1117869872 2005.06.04 variante rara sin el patron completo",
    ])
    r = aggregate_logs(lote)
    assert r["formato_detectado"] == "bgl"
    assert r["total_lineas"] == 5
    assert "KERNSTOR" not in str(r)
    assert len(r["cronologia"]) == 4
    assert r["eventos"]["evento_normal"] == 1


def test_el_prompt_no_recibe_la_cronologia_ni_las_entidades():
    """Doble defensa: además de sanear el mensaje, estas claves no salen
    hacia el LLM. Es el único camino del resumen al prompt del triage."""
    r = aggregate_logs(AUTH)
    acotado = acotar_resumen_para_prompt(r)
    assert "cronologia" not in acotado
    assert "cronologia_omitidos" not in acotado
    assert "entidades" not in acotado
    # Lo que sí es señal para el LLM se conserva.
    assert "usuarios" in acotado
    assert "codigos_respuesta" in acotado


def test_acotar_no_muta_el_resumen_original():
    r = aggregate_logs(AUTH)
    acotar_resumen_para_prompt(r)
    assert "cronologia" in r


# --- forma del resumen ------------------------------------------------------

def test_el_resumen_expone_las_claves_del_8_7_1():
    """El informe, el PDF y la interfaz consumen estas claves del §8.7.1."""
    r = aggregate_logs(AUTH)
    esperadas = {"usuarios", "n_usuarios_distintos", "codigos_respuesta",
                 "entidades", "cronologia", "cronologia_omitidos"}
    assert esperadas <= set(r)


# --- precedentes como evidencia utilizada ----------------------------------

def test_los_precedentes_del_rag_quedan_en_el_reporte():
    """El §8.7.1 pide "las evidencias utilizadas": los CVEs, la reputación y
    ATT&CK ya quedaban, los precedentes de la memoria no."""
    from src.pipeline import _precedentes

    contexto = [
        {"texto": "v1|lineas=23 ...", "similitud": 0.91,
         "meta": {"clasificacion": "fuerza bruta SSH", "confianza": 0.95, "host": "web"}},
        {"texto": "v1|otra", "similitud": 0.62, "meta": {}},
    ]
    salida = _precedentes(contexto)
    assert salida[0] == {"clasificacion": "fuerza bruta SSH", "confianza": 0.95,
                         "host": "web", "similitud": 0.91}
    # No se copia el documento completo: es la firma del lote precedente y
    # no aporta nada leída.
    assert "texto" not in salida[0]
    assert salida[1]["clasificacion"] is None


@pytest.mark.parametrize("entrada", [None, [], ["basura"], [None]])
def test_los_precedentes_toleran_entrada_invalida(entrada):
    from src.pipeline import _precedentes

    assert isinstance(_precedentes(entrada), list)


# --- el informe en PDF los muestra -----------------------------------------

def test_el_pdf_incluye_la_cronologia_y_las_entidades(monkeypatch):
    from tests.test_informe_pdf import CORRIDA, _texto_escrito

    corrida = dict(CORRIDA)
    corrida["resumen_json"] = {
        **CORRIDA["resumen_json"],
        "usuarios": {"root": 4, "admin": 2},
        "n_usuarios_distintos": 2,
        "codigos_respuesta": {"401": 3},
        "entidades": [{"ip": "45.155.205.233", "n_eventos": 15,
                       "intentos_fallidos": 16, "servicios": ["sshd"],
                       "usuarios_objetivo": ["root", "admin"]}],
        "cronologia": [{"n": 1, "timestamp": "Sep  9 03:12:01", "servicio": "sshd",
                        "evento": "acceso_fallido", "ip": "45.155.205.233",
                        "mensaje": "Failed password for root"}],
        "cronologia_omitidos": 7,
    }
    corrida["reporte_json"] = {
        **CORRIDA["reporte_json"],
        "precedentes": [{"clasificacion": "fuerza bruta previa", "confianza": 0.9,
                         "host": "web", "similitud": 0.88}],
    }
    texto = _texto_escrito(monkeypatch, corrida)
    assert "SECUENCIA TEMPORAL" in texto.upper()
    assert "Failed password for root" in texto
    assert "7 registros" in texto              # el recorte queda declarado
    assert "ENTIDADES INVOLUCRADAS" in texto.upper()
    assert "root, admin" in texto            # usuarios objetivo de la entidad
    assert "401" in texto                    # códigos de respuesta
    assert "fuerza bruta previa" in texto    # precedentes


def test_el_pdf_omite_las_secciones_sin_datos(monkeypatch):
    from tests.test_informe_pdf import CORRIDA, _texto_escrito

    texto = _texto_escrito(monkeypatch, CORRIDA)
    assert "SECUENCIA TEMPORAL" not in texto.upper()
