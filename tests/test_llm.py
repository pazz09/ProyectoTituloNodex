"""Tests de `_generate_con_backoff`/`_generate_con_fallback` (src/llm.py):
distingue 429 diario, 429 por minuto y 503 transitorio, reintenta solo
cuando corresponde, respeta el techo de backoff y el jitter, y cambia al
modelo de respaldo cuando el principal agota sus reintentos.

Motivación (hallazgo real, 25-ago-2026): la primera corrida real end-to-end
sobre HDFS_2k.log murió en un 429 con quotaId
`GenerateRequestsPerMinutePerProjectPerModel-FreeTier` (límite 5/min), que
el código anterior trataba igual que la cuota DIARIA -- relanzaba de
inmediato, sin reintentar, aunque el propio error de Google traía
`retryDelay: '1s'` indicando que era recuperable en segundos. Estos tests
mockean `client.models.generate_content` y `time.sleep` para verificar los
distintos caminos de forma determinista, sin llamar a la API real ni gastar
cuota ni tiempo real de espera.
"""

import ssl
from types import SimpleNamespace

import src.llm as llm_mod


def _respuesta_llm(texto: str):
    return SimpleNamespace(text=texto, usage_metadata=None)


def test_llm_json_reintenta_si_gemini_devuelve_una_lista(monkeypatch):
    """Los agentes esperan objetos y usan ``.get``; una lista no es válida.

    Regresión del cierre de Fase 6: un lote HDFS colapsó porque Gemini
    devolvió JSON de nivel superior con forma de lista. El wrapper debe pedir
    una corrección y entregar a los agentes únicamente un diccionario.
    """
    respuestas = iter([
        _respuesta_llm('[{"diagnostico": "forma incorrecta"}]'),
        _respuesta_llm('{"diagnostico": "forma correcta"}'),
    ])
    monkeypatch.setattr(llm_mod, "_asegurar_credenciales", lambda: None)
    monkeypatch.setattr(llm_mod, "_generate_con_fallback", lambda *a, **k: next(respuestas))

    resultado = llm_mod.llm_json("analiza", retries=1)

    assert resultado == {"diagnostico": "forma correcta"}


def test_llm_json_no_expone_lista_si_agota_reintentos(monkeypatch):
    respuestas = iter([
        _respuesta_llm('[{"diagnostico": "incorrecto 1"}]'),
        _respuesta_llm('[{"diagnostico": "incorrecto 2"}]'),
    ])
    monkeypatch.setattr(llm_mod, "_asegurar_credenciales", lambda: None)
    monkeypatch.setattr(llm_mod, "_generate_con_fallback", lambda *a, **k: next(respuestas))

    resultado = llm_mod.llm_json("analiza", retries=1)

    assert isinstance(resultado, dict)
    assert resultado["error"] == "json_invalido"


class _ErrorFalso(Exception):
    """Simula una excepción real del SDK (`google.genai.errors.APIError` y
    subclases): expone `.code` y un mensaje de texto con la forma real que
    devuelve Google (incluyendo el `quotaId` y, para el 429 por minuto, el
    `retryDelay` real que trajo la corrida del 25-ago-2026)."""

    def __init__(self, code: int, texto: str):
        super().__init__(texto)
        self.code = code


ERR_CUOTA_DIARIA = _ErrorFalso(
    429,
    "429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'message': "
    "\"...GenerateRequestsPerDayPerProjectPerModel-FreeTier, limit: 20\", "
    "'status': 'RESOURCE_EXHAUSTED'}}",
)

ERR_CUOTA_MINUTO = _ErrorFalso(
    429,
    "429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'message': "
    "\"...GenerateRequestsPerMinutePerProjectPerModel-FreeTier, limit: 5\", "
    "'status': 'RESOURCE_EXHAUSTED', 'details': [{'@type': "
    "'type.googleapis.com/google.rpc.RetryInfo', 'retryDelay': '1s'}]}}",
)

ERR_503 = _ErrorFalso(503, "503 UNAVAILABLE. The model is overloaded. Please try again later.")

ERR_NO_RECONOCIDO = _ErrorFalso(400, "400 INVALID_ARGUMENT. Bad request.")

# Error real del 26-ago-2026: un corte de conexión TLS a mitad de la
# respuesta, sin código HTTP (.code queda None) -- el caso que motivó
# ampliar _es_error_transitorio() más allá de códigos HTTP.
ERR_SSL_TRANSPORTE = _ErrorFalso(
    None, "[SSL: UNEXPECTED_EOF_WHILE_READING] EOF occurred in violation of protocol (_ssl.c:2427)"
)


def test_tipo_error_cuota_distingue_dia_de_minuto():
    assert llm_mod._tipo_error_cuota(ERR_CUOTA_DIARIA) == "dia"
    assert llm_mod._tipo_error_cuota(ERR_CUOTA_MINUTO) == "minuto"
    assert llm_mod._tipo_error_cuota(ERR_503) is None
    assert llm_mod._tipo_error_cuota(ERR_NO_RECONOCIDO) is None


def test_retry_delay_sugerido_lee_el_de_google_o_usa_default():
    assert llm_mod._retry_delay_sugerido(ERR_CUOTA_MINUTO) == 1.0
    assert llm_mod._retry_delay_sugerido(ERR_CUOTA_DIARIA) == 15.0  # sin retryDelay -> default


def test_cuota_diaria_no_reintenta(monkeypatch):
    llamadas = {"n": 0}

    def fake_generate(model=None, contents=None, config=None):
        llamadas["n"] += 1
        raise ERR_CUOTA_DIARIA

    monkeypatch.setattr(llm_mod.client.models, "generate_content", fake_generate)
    monkeypatch.setattr(llm_mod.time, "sleep", lambda s: (_ for _ in ()).throw(
        AssertionError("no debería dormir ante una cuota diaria")))

    try:
        llm_mod._generate_con_backoff("x", None)
        assert False, "debía relanzar la excepción"
    except _ErrorFalso:
        pass
    assert llamadas["n"] == 1


def test_cuota_por_minuto_reintenta_con_el_retry_delay_de_google(monkeypatch):
    respuestas = iter([ERR_CUOTA_MINUTO, ERR_CUOTA_MINUTO, "respuesta_ok"])
    llamadas = {"n": 0}
    esperas = []

    def fake_generate(model=None, contents=None, config=None):
        llamadas["n"] += 1
        r = next(respuestas)
        if isinstance(r, Exception):
            raise r
        return r

    monkeypatch.setattr(llm_mod.client.models, "generate_content", fake_generate)
    monkeypatch.setattr(llm_mod.time, "sleep", lambda s: esperas.append(s))

    resultado = llm_mod._generate_con_backoff("x", None)
    assert resultado == "respuesta_ok"
    assert llamadas["n"] == 3
    # backoff FIJO (no exponencial) al retryDelay real de Google -- la cuota
    # por minuto se repone en un tiempo fijo, no cada vez más lento.
    assert esperas == [1.0, 1.0]


def test_cuota_por_minuto_agota_reintentos_y_relanza(monkeypatch):
    llamadas = {"n": 0}

    def fake_generate(model=None, contents=None, config=None):
        llamadas["n"] += 1
        raise ERR_CUOTA_MINUTO

    monkeypatch.setattr(llm_mod.client.models, "generate_content", fake_generate)
    monkeypatch.setattr(llm_mod.time, "sleep", lambda s: None)

    try:
        llm_mod._generate_con_backoff("x", None, max_reintentos_cuota_minuto=3)
        assert False, "debía relanzar tras agotar los reintentos"
    except _ErrorFalso:
        pass
    assert llamadas["n"] == 4  # 1 intento inicial + 3 reintentos


def test_503_sigue_con_backoff_exponencial(monkeypatch):
    """Regresión: el camino de 503 (agregado 23-ago-2026) no debe cambiar
    con esta modificación. `jitter=0.0` para que las esperas sean
    deterministas -- el jitter en sí se prueba aparte."""
    respuestas = iter([ERR_503, ERR_503, "ok_503"])
    esperas = []

    def fake_generate(model=None, contents=None, config=None):
        r = next(respuestas)
        if isinstance(r, Exception):
            raise r
        return r

    monkeypatch.setattr(llm_mod.client.models, "generate_content", fake_generate)
    monkeypatch.setattr(llm_mod.time, "sleep", lambda s: esperas.append(s))

    resultado = llm_mod._generate_con_backoff("x", None, max_reintentos=2, espera_inicial=2.0, jitter=0.0)
    assert resultado == "ok_503"
    assert esperas == [2.0, 4.0]  # exponencial: 2s, luego 4s


def test_error_no_reconocido_no_reintenta(monkeypatch):
    llamadas = {"n": 0}

    def fake_generate(model=None, contents=None, config=None):
        llamadas["n"] += 1
        raise ERR_NO_RECONOCIDO

    monkeypatch.setattr(llm_mod.client.models, "generate_content", fake_generate)
    monkeypatch.setattr(llm_mod.time, "sleep", lambda s: (_ for _ in ()).throw(
        AssertionError("no debería dormir ante un error no reconocido")))

    try:
        llm_mod._generate_con_backoff("x", None)
        assert False, "debía relanzar de inmediato"
    except _ErrorFalso:
        pass
    assert llamadas["n"] == 1


def test_error_ssl_transporte_se_reconoce_como_transitorio_por_mensaje():
    """El error real del 26-ago-2026: sin código HTTP, solo el texto lo
    delata. Antes de este fix, `_es_error_transitorio` devolvía False."""
    assert llm_mod._es_error_transitorio(ERR_SSL_TRANSPORTE) is True


def test_error_ssl_transporte_se_reconoce_por_tipo():
    """Cuando la excepción SÍ preserva el tipo original (`ssl.SSLError`),
    se reconoce por isinstance, no solo por texto."""
    err_tipado = ssl.SSLError("EOF occurred in violation of protocol")
    assert llm_mod._es_error_transitorio(err_tipado) is True


def test_error_ssl_transporte_reintenta_con_el_mismo_backoff_que_503(monkeypatch):
    """Un corte de conexión TLS debe reintentar por el mismo camino que un
    503 -- backoff exponencial corto, mismo contador `intentos_503`."""
    respuestas = iter([ERR_SSL_TRANSPORTE, "ok_transporte"])
    esperas = []

    def fake_generate(model=None, contents=None, config=None):
        r = next(respuestas)
        if isinstance(r, Exception):
            raise r
        return r

    monkeypatch.setattr(llm_mod.client.models, "generate_content", fake_generate)
    monkeypatch.setattr(llm_mod.time, "sleep", lambda s: esperas.append(s))

    resultado = llm_mod._generate_con_backoff("x", None, max_reintentos=2, espera_inicial=2.0, jitter=0.0)
    assert resultado == "ok_transporte"
    assert esperas == [2.0]


def test_backoff_respeta_el_techo_y_no_crece_indefinidamente(monkeypatch):
    """Ante una racha larga de 503, el backoff exponencial no debe superar
    `backoff_max` -- sin techo, una racha suficientemente larga produciría
    esperas de minutos u horas."""
    respuestas = iter([ERR_503, ERR_503, ERR_503, "ok_503"])
    esperas = []

    def fake_generate(model=None, contents=None, config=None):
        r = next(respuestas)
        if isinstance(r, Exception):
            raise r
        return r

    monkeypatch.setattr(llm_mod.client.models, "generate_content", fake_generate)
    monkeypatch.setattr(llm_mod.time, "sleep", lambda s: esperas.append(s))

    resultado = llm_mod._generate_con_backoff(
        "x", None, max_reintentos=3, espera_inicial=2.0, backoff_max=8.0, jitter=0.0,
    )
    assert resultado == "ok_503"
    # 2.0 -> 4.0 -> 8.0 (techo) -- sin el techo, el cuarto valor sería 16.0.
    assert esperas == [2.0, 4.0, 8.0]


def test_jitter_mantiene_la_espera_dentro_del_rango_esperado():
    """`_espera_con_jitter` no debe alejarse más de `jitter` (proporcional)
    del valor base, y `jitter=0` debe devolver el valor exacto (usado en el
    resto de los tests para mantenerlos deterministas)."""
    for _ in range(50):
        resultado = llm_mod._espera_con_jitter(10.0, 0.25)
        assert 7.5 <= resultado <= 12.5
    assert llm_mod._espera_con_jitter(10.0, 0.0) == 10.0


# --- Modelo principal + respaldo (_generate_con_fallback, 1-sep-2026) ---

def test_generate_con_backoff_usa_el_modelo_principal_por_defecto(monkeypatch):
    modelos_usados = []

    def fake_generate(model=None, contents=None, config=None):
        modelos_usados.append(model)
        return "ok"

    monkeypatch.setattr(llm_mod.client.models, "generate_content", fake_generate)

    resultado = llm_mod._generate_con_backoff("x", None)
    assert resultado == "ok"
    assert modelos_usados == [llm_mod.LLM_MODEL_PRIMARY]


def test_fallback_activa_tras_agotar_reintentos_transitorio(monkeypatch):
    """Si el modelo principal agota sus reintentos por una racha de 503,
    `_generate_con_fallback` debe reintentar completo con el de respaldo
    -- no relanzar el error del principal."""
    modelos_usados = []

    def fake_generate(model=None, contents=None, config=None):
        modelos_usados.append(model)
        if model == llm_mod.LLM_MODEL_PRIMARY:
            raise ERR_503  # el principal siempre falla, agota sus reintentos
        return "ok_respaldo"

    monkeypatch.setattr(llm_mod.client.models, "generate_content", fake_generate)
    monkeypatch.setattr(llm_mod.time, "sleep", lambda s: None)

    resultado = llm_mod._generate_con_fallback("x", None, max_reintentos=1, jitter=0.0)
    assert resultado == "ok_respaldo"
    # 2 intentos contra el principal (1 inicial + 1 reintento) y luego 1 contra el respaldo.
    assert modelos_usados == [llm_mod.LLM_MODEL_PRIMARY, llm_mod.LLM_MODEL_PRIMARY, llm_mod.LLM_MODEL_FALLBACK]


def test_fallback_activa_ante_cuota_diaria_del_principal(monkeypatch):
    """Una cuota diaria agotada del principal (que NO reintenta -- ver
    `test_cuota_diaria_no_reintenta`) también debe disparar el respaldo:
    es exactamente el escenario "el principal tiene mucha demanda o no
    funciona" que motivó este mecanismo."""
    modelos_usados = []

    def fake_generate(model=None, contents=None, config=None):
        modelos_usados.append(model)
        if model == llm_mod.LLM_MODEL_PRIMARY:
            raise ERR_CUOTA_DIARIA
        return "ok_respaldo"

    monkeypatch.setattr(llm_mod.client.models, "generate_content", fake_generate)
    monkeypatch.setattr(llm_mod.time, "sleep", lambda s: None)

    resultado = llm_mod._generate_con_fallback("x", None)
    assert resultado == "ok_respaldo"
    assert modelos_usados == [llm_mod.LLM_MODEL_PRIMARY, llm_mod.LLM_MODEL_FALLBACK]


def test_sin_fallback_ante_error_no_reconocido(monkeypatch):
    """Un error no reconocido (p. ej. 400 por un prompt mal formado) es un
    bug de código, no de disponibilidad del modelo -- no debe activar el
    respaldo (cambiar de modelo no lo arregla, solo lo repite dos veces)."""
    modelos_usados = []

    def fake_generate(model=None, contents=None, config=None):
        modelos_usados.append(model)
        raise ERR_NO_RECONOCIDO

    monkeypatch.setattr(llm_mod.client.models, "generate_content", fake_generate)
    monkeypatch.setattr(llm_mod.time, "sleep", lambda s: (_ for _ in ()).throw(
        AssertionError("no debería dormir ante un error no reconocido")))

    try:
        llm_mod._generate_con_fallback("x", None)
        assert False, "debía relanzar de inmediato, sin probar el respaldo"
    except _ErrorFalso:
        pass
    assert modelos_usados == [llm_mod.LLM_MODEL_PRIMARY]


def test_fallback_tambien_falla_propaga_su_propio_error(monkeypatch):
    """Si el modelo de respaldo también falla, se propaga SU error (no el
    del principal) -- es la información más relevante en ese momento: ni
    el principal ni el respaldo están disponibles."""

    def fake_generate(model=None, contents=None, config=None):
        if model == llm_mod.LLM_MODEL_PRIMARY:
            raise ERR_CUOTA_DIARIA
        raise ERR_503

    monkeypatch.setattr(llm_mod.client.models, "generate_content", fake_generate)
    monkeypatch.setattr(llm_mod.time, "sleep", lambda s: None)

    try:
        llm_mod._generate_con_fallback("x", None, max_reintentos=0, jitter=0.0)
        assert False, "debía relanzar el error del respaldo"
    except _ErrorFalso as e:
        assert e is ERR_503
