"""Instrumentación de telemetría del cliente LLM (Fase 6).

**ESCRITAS, NO EJECUTADAS** como parte de la suite. El comportamiento que
afirman se verificó aparte, con un cliente **simulado** (`generate_content`
reemplazado por un objeto falso, sin credenciales y sin red): 7 de 8
escenarios pasaron y el octavo reveló un defecto de producción, no de la
instrumentación (ver `test_el_aviso_del_fallback_no_es_codificable_en_cp1252`).

Lo que estas pruebas protegen, en orden de importancia:

1. Que la instrumentación **no cambie nada** de NODEX: sin grabador activo
   es un no-op y el valor de retorno de `llm_json` es idéntico.
2. Que los dos contadores de llamadas no se confundan. Una invocación de
   `llm_json()` puede producir varias llamadas HTTP, y **los reintentos
   también consumen tokens**.
3. Que un contador que el proveedor no informa quede `None` y no 0.
"""

import types

import pytest

from src import telemetria_llm


class _Uso:
    """`usage_metadata` falso. Omite los atributos que no se le pasan."""

    def __init__(self, entrada=None, salida=None, razonamiento=None, total=None):
        if entrada is not None:
            self.prompt_token_count = entrada
        if salida is not None:
            self.candidates_token_count = salida
        if razonamiento is not None:
            self.thoughts_token_count = razonamiento
        if total is not None:
            self.total_token_count = total


class _Respuesta:
    def __init__(self, texto="{}", uso=None):
        self.text = texto
        self.usage_metadata = uso


@pytest.fixture
def grabador():
    g = telemetria_llm.activar("run-prueba")
    yield g
    telemetria_llm.desactivar()


def _registrar(uso=None, modelo="gemini-3.1-pro-preview",
               solicitado="gemini-3.1-pro-preview", error=None):
    import time

    with telemetria_llm.invocacion_logica(0):
        telemetria_llm.registrar_llamada(
            modelo_efectivo=modelo,
            modelo_solicitado=solicitado,
            comenzado=time.monotonic(),
            respuesta=_Respuesta(uso=uso) if uso is not None else None,
            error=error,
        )


# --- no-op sin grabador --------------------------------------------------

def test_sin_grabador_activo_todo_es_un_no_op():
    """Es lo que garantiza que la web, la API y el CLI no cambien."""
    telemetria_llm.desactivar()
    assert telemetria_llm.grabador_activo() is None
    # No debe lanzar ni registrar nada.
    _registrar(_Uso(10, 1, None, 11))
    assert telemetria_llm.grabador_activo() is None


def test_el_context_manager_no_suprime_excepciones():
    """La telemetría no puede cambiar el flujo de control."""
    with pytest.raises(ValueError):
        with telemetria_llm.invocacion_logica(0):
            raise ValueError("debe propagarse")


# --- los dos contadores --------------------------------------------------

def test_una_invocacion_logica_con_una_llamada_fisica(grabador):
    _registrar(_Uso(1200, 300, 50, 1550))
    d = grabador.to_dict()
    assert d["llm_call_count"] == 1
    assert d["api_call_count"] == 1
    assert d["reintentos_api"] == 0


def test_el_reintento_por_json_invalido_es_el_mismo_paso_de_agente(grabador):
    """`llm_json` vuelve a pedir si el JSON no sirve. Es la misma decisión
    del mismo agente: una invocación lógica, dos llamadas físicas."""
    import time

    with telemetria_llm.invocacion_logica(0):
        telemetria_llm.registrar_llamada(
            "m", "m", time.monotonic(), _Respuesta(uso=_Uso(1000, 10, None, 1010))
        )
    with telemetria_llm.invocacion_logica(1):
        telemetria_llm.registrar_llamada(
            "m", "m", time.monotonic(), _Respuesta(uso=_Uso(1100, 20, None, 1120))
        )
    d = grabador.to_dict()
    assert d["llm_call_count"] == 1
    assert d["api_call_count"] == 2
    assert d["reintentos_api"] == 1
    # Los tokens del reintento CUENTAN: si solo se registrara la respuesta
    # final, el consumo quedaría subestimado justo en las corridas
    # problemáticas, que son las que más interesa medir.
    assert d["input_tokens"] == 2100
    assert d["total_tokens"] == 2130


def test_el_reintento_del_backoff_tambien_se_registra(grabador):
    """Un 503 reintentado consume una llamada aunque no devuelva tokens."""
    _registrar(error="ConnectionError: 503")
    _registrar(_Uso(500, 50, None, 550))
    d = grabador.to_dict()
    assert d["api_call_count"] == 2
    assert len(d["errores"]) == 1
    assert d["input_tokens"] == 500
    # La parcialidad se declara en vez de presentarse como total.
    assert d["campos_parciales"]["input_tokens"] == {
        "informadas": 1, "totales": 2
    }


# --- `None` nunca es cero ------------------------------------------------

def test_un_contador_ausente_queda_none_y_no_cero(grabador):
    """El `print` de `llm_json` usa `getattr(um, 'thoughts_token_count', 0)`.
    Para un mensaje en pantalla da igual; para una métrica no: un 0 se
    promedia y baja el consumo medio sin que nadie lo note."""
    _registrar(_Uso(100, 10))
    d = grabador.to_dict()
    assert d["reasoning_tokens"] is None
    assert d["input_tokens"] == 100


def test_sin_usage_metadata_no_se_estima_nada(grabador):
    _registrar(uso=None)
    d = grabador.to_dict()
    assert d["input_tokens"] is None
    assert d["output_tokens"] is None
    assert d["total_tokens"] is None
    assert d["origen_total_tokens"] == "no_informado"


def test_el_total_declara_de_donde_salio(grabador):
    """Se prefiere el total del proveedor; si no lo informa, se suma de las
    partes y se declara, porque la suma puede no incluir tokens que el
    proveedor contabilice aparte."""
    _registrar(_Uso(100, 10, None, 115))
    assert grabador.to_dict()["origen_total_tokens"] == "proveedor"
    assert grabador.to_dict()["total_tokens"] == 115


def test_sin_total_del_proveedor_se_suma_y_se_declara(grabador):
    _registrar(_Uso(100, 10, 5))
    d = grabador.to_dict()
    assert d["total_tokens"] == 115
    assert d["origen_total_tokens"] == "suma_de_partes"


def test_un_booleano_no_pasa_como_conteo(grabador):
    """`bool` es subclase de `int`: sin descartarlo, un `True` entraría como
    el conteo 1."""
    _registrar(_Uso(True, 10, None, 11))
    assert grabador.to_dict()["input_tokens"] == 10


# --- modelo efectivo y fallback -----------------------------------------

def test_el_fallback_de_modelo_queda_marcado(grabador):
    """Una corrida que cayó al fallback usó otro modelo y no es comparable
    con el resto de la campaña."""
    _registrar(_Uso(300, 30, None, 330),
               modelo="gemini-3.6-flash",
               solicitado="gemini-3.1-pro-preview")
    d = grabador.to_dict()
    assert d["uso_fallback"] is True
    assert d["modelos_efectivos"] == ["gemini-3.6-flash"]
    assert d["llamadas"][0]["uso_fallback"] is True


def test_sin_fallback_no_se_marca(grabador):
    _registrar(_Uso(300, 30, None, 330))
    assert grabador.to_dict()["uso_fallback"] is False


def test_se_registran_todos_los_modelos_efectivos_de_la_corrida(grabador):
    _registrar(_Uso(1, 1, None, 2), modelo="gemini-3.1-pro-preview")
    _registrar(_Uso(1, 1, None, 2), modelo="gemini-3.6-flash",
               solicitado="gemini-3.1-pro-preview")
    assert grabador.to_dict()["modelos_efectivos"] == [
        "gemini-3.1-pro-preview", "gemini-3.6-flash"
    ]


# --- atribución al agente ------------------------------------------------

def test_el_agente_se_deduce_de_la_pila_sin_tocar_los_agentes():
    """Pasarles un parámetro nuevo a los cinco agentes obligaría a editar
    archivos que la implementación externa de D-11 también está tocando."""
    import sys

    modulo = types.ModuleType("src.agents.agente_de_prueba")
    exec("def paso(fn):\n    return fn()\n", modulo.__dict__)
    sys.modules["src.agents.agente_de_prueba"] = modulo
    try:
        deducido = modulo.paso(telemetria_llm.agente_desde_la_pila)
    finally:
        del sys.modules["src.agents.agente_de_prueba"]
    assert deducido == "agente_de_prueba.paso"


def test_fuera_de_un_agente_la_atribucion_es_none():
    assert telemetria_llm.agente_desde_la_pila() is None


def test_el_consumo_se_agrupa_por_agente(grabador):
    import sys

    modulo = types.ModuleType("src.agents.agente_x")
    exec(
        "def paso(registrar, uso):\n"
        "    import time\n"
        "    from src import telemetria_llm as t\n"
        "    with t.invocacion_logica(0):\n"
        "        registrar(uso)\n",
        modulo.__dict__,
    )
    sys.modules["src.agents.agente_x"] = modulo

    def registrar(uso):
        import time
        telemetria_llm.registrar_llamada(
            "m", "m", time.monotonic(), _Respuesta(uso=uso)
        )

    try:
        modulo.paso(registrar, _Uso(10, 1, None, 11))
        modulo.paso(registrar, _Uso(20, 2, None, 22))
    finally:
        del sys.modules["src.agents.agente_x"]

    d = grabador.to_dict()
    assert d["llm_call_count"] == 2
    assert d["por_agente"]["agente_x.paso"]["llamadas_api"] == 2
    assert d["por_agente"]["agente_x.paso"]["input_tokens"] == 30


# --- los contadores del grafo no vienen del grabador --------------------

def test_replan_y_correccion_no_los_aporta_el_grabador(grabador):
    """Son contadores de la **corrida**, no de una llamada: salen del estado
    del grafo y el orquestador los agrega. Si el grabador los inventara,
    estaría midiendo algo que no observa."""
    d = grabador.to_dict()
    assert "replan_count" not in d
    assert "intentos_correccion" not in d


def test_el_orquestador_si_los_agrega():
    import inspect

    from src.experimentation import orquestador

    codigo = inspect.getsource(orquestador._correr_una)
    assert "replan_count=diagnostico.get" in codigo
    assert "intentos_correccion=diagnostico.get" in codigo


def test_el_grabador_se_apaga_en_un_finally():
    """Si quedara activo, la corrida siguiente sumaría sus llamadas a las de
    esta y el consumo por corrida sería acumulativo."""
    import inspect

    from src.experimentation import orquestador

    codigo = inspect.getsource(orquestador._correr_una)
    assert "finally:" in codigo
    assert "telemetria_llm.desactivar()" in codigo


# --- el defecto de producción que destapó la simulación -----------------

def test_el_aviso_del_fallback_no_es_codificable_en_cp1252():
    """Defecto **preexistente de producción**, no de la instrumentación.

    `src/llm.py` imprime el aviso del fallback con `⚠️`, y 56 líneas de
    `src/` tienen caracteres que cp1252 no puede codificar. En Windows,
    cuando la salida se redirige a un archivo, `sys.stdout.encoding` es
    cp1252: una corrida redirigida muere con `UnicodeEncodeError` al
    imprimir, no por un problema del modelo. Y el camino que crashea es
    justo el del fallback, que es el que más interesa observar.

    Se mitiga en la capa experimental con
    `orquestador.asegurar_salida_utf8()`, sin tocar NODEX.
    """
    aviso = "\n⚠️  Modelo principal no disponible"
    with pytest.raises(UnicodeEncodeError):
        aviso.encode("cp1252")


def test_el_orquestador_fuerza_utf8_antes_de_ejecutar():
    import inspect

    from src.experimentation import orquestador

    codigo = inspect.getsource(orquestador.ejecutar_campana)
    assert "asegurar_salida_utf8()" in codigo
    informe = orquestador.asegurar_salida_utf8()
    assert informe["encoding_despues"]["stdout"] in ("utf-8", "UTF-8")
