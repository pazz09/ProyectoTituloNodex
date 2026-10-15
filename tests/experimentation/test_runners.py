"""Runners de las tres arquitecturas (Fase C).

**ESCRITAS, NO EJECUTADAS.** Ejecutar un runner es ejecutar NODEX, el agente
único o el preprocesamiento sobre un caso de prueba, que requiere
autorización. Lo que estas pruebas verifican es **estructura**: firmas,
ausencia de ground truth, mapeo de vocabularios y clasificación de errores.
Ninguna invoca `ejecutar()`.

La prueba `test_todos_los_imports_de_la_capa_experimental_existen` es la que
más veces habría evitado un error: durante la Fase C fallaron dos imports
(`CONTRATO_VERSION` desde el módulo equivocado y `firma_lote` desde
`resumen_prompt` en vez de `aggregation`), y los dos solo se habrían notado
al correr la campaña.
"""

import ast
import inspect
from pathlib import Path

import pytest

from src.experimentation.runners import baseline, gemini_externo, nodex

RAIZ = Path(__file__).resolve().parents[2]
#: El checkout de producción, donde viven `src/pipeline.py` y los agentes.
RAIZ_PRODUCCION = RAIZ.parent / "NODEX"


# --- ninguna arquitectura ve el ground truth ----------------------------

@pytest.mark.parametrize("modulo", [nodex, gemini_externo, baseline])
def test_ninguna_funcion_del_runner_recibe_ground_truth(modulo):
    prohibidos = {"ground_truth", "referencia", "etiqueta",
                  "etiqueta_deteccion", "core_event_uids", "referencias_mitre"}
    for nombre, funcion in inspect.getmembers(modulo, inspect.isfunction):
        if funcion.__module__ != modulo.__name__:
            continue
        parametros = set(inspect.signature(funcion).parameters)
        assert not prohibidos & parametros, f"{nombre}: {prohibidos & parametros}"


@pytest.mark.parametrize("modulo", [nodex, gemini_externo, baseline])
def test_los_tres_runners_leen_el_caso_con_la_misma_firma(modulo):
    """Si recibieran entradas distintas, la comparación entre arquitecturas
    mediría la entrada y no la arquitectura."""
    parametros = list(inspect.signature(modulo.cargar_caso).parameters)
    assert parametros == ["raiz_repo", "dataset", "particion", "case_id"]


@pytest.mark.parametrize("modulo", [nodex, gemini_externo, baseline])
def test_cargar_caso_no_construye_ninguna_ruta_al_ground_truth(modulo):
    """Verifica el invariante, no el docstring.

    La primera versión de esta prueba comprobaba que el docstring
    *mencionara* "ground_truth", lo que ni verificaba nada ni era cierto: el
    texto dice "ground truth" con espacio. Lo que importa es que el código
    arme la ruta bajo `cases/` y no exista ningún segmento de ruta
    `"ground_truth"` que pudiera leer la referencia.
    """
    codigo = inspect.getsource(modulo.cargar_caso)
    assert '"cases"' in codigo
    assert '"ground_truth"' not in codigo


# --- baseline ------------------------------------------------------------

def test_el_baseline_declara_que_solo_responde_deteccion_y_consumo():
    assert set(baseline.DIMENSIONES_DEL_BASELINE) == {"deteccion", "consumo"}


def test_el_baseline_marca_la_desalineacion_de_pregunta_en_uwf():
    """Sus reglas son operativas (severidad, fallos, concentración por IP).
    UWF pregunta por actividad maliciosa: un escaneo exitoso no produce
    fallos, así que el baseline puede no verlo por diseño de sus reglas."""
    assert baseline.PREGUNTA_RESPONDIDA == "operativa"


def test_el_baseline_nunca_declara_mitre_ni_reconstruccion_evaluables():
    class _Salida:
        classification = "MALICIOUS"

    estados = baseline.estados_por_dimension(
        _Salida(), ("deteccion", "reconstruccion", "mitre", "reporte", "consumo")
    )
    assert estados["reconstruccion"] == "no_aplica"
    assert estados["mitre"] == "no_aplica"
    assert estados["reporte"] == "no_aplica"
    assert estados["deteccion"] == "evaluable"


def test_una_prediccion_ausente_del_baseline_deja_la_deteccion_no_evaluable():
    class _Salida:
        classification = None

    estados = baseline.estados_por_dimension(_Salida(), ("deteccion",))
    assert estados["deteccion"] == "no_evaluable"


# --- Gemini externo (pseudo-ablación) ----------------------------------

def test_el_gemini_externo_no_usa_rag_ni_herramientas_y_lo_declara():
    """No es un defecto: es el diseño. La comparación del proyecto es una
    pseudo-ablación declarada —sistema completo contra modelo desnudo—, no
    una ablación de una sola variable."""
    codigo = inspect.getsource(gemini_externo)
    assert "tool_consultar_rag" not in codigo
    assert "tool_consultar_cve" not in codigo
    assert "sin_rag" in codigo


def test_el_gemini_externo_no_usa_el_cliente_llm_de_nodex():
    """`src/llm.py` arrastra la instrumentación, el fallback de modelo y los
    reintentos de NODEX. La pseudo-ablación quiere el modelo desnudo."""
    arbol = ast.parse(inspect.getsource(gemini_externo))
    modulos = {
        nodo.module for nodo in ast.walk(arbol)
        if isinstance(nodo, ast.ImportFrom) and nodo.module
    }
    assert "src.llm" not in modulos
    assert not any(m.startswith("src.tools") for m in modulos)


def test_el_gemini_externo_usa_el_mismo_modelo_y_temperatura():
    """Lo que se compara es el sistema, no el proveedor."""
    codigo = inspect.getsource(gemini_externo.ejecutar)
    assert "LLM_MODEL_PRIMARY" in codigo
    assert "TEMPERATURE" in codigo


def test_el_gemini_externo_pide_los_campos_del_contrato_d11():
    """Con los nombres de `d11-v1` y no con otros: dos vocabularios
    obligarían a traducir un lado, con riesgo de traducir mal."""
    instruccion = gemini_externo.INSTRUCCION_SISTEMA
    for clave in ("event_id", "evidence_uids", "technique_id",
                  "eventos_reconstruidos", "tecnicas_atribuidas",
                  "secuencia_temporal"):
        assert clave in instruccion, clave


def test_un_caso_demasiado_grande_falla_en_vez_de_recortarse():
    """Recortar en silencio haría que Gemini viera menos caso que NODEX."""
    codigo = inspect.getsource(gemini_externo.ejecutar)
    assert "no se recorta" in codigo
    assert gemini_externo.MAX_CARACTERES_PROMPT > 100_000


def test_el_gemini_externo_no_informa_replan_ni_correccion():
    """No hay grafo que replanifique ni comandos que corregir. Van `None` y
    no 0, porque 0 afirmaría que hubo cero replanificaciones en un sistema
    que no replanifica."""
    codigo = inspect.getsource(gemini_externo.ejecutar)
    assert '"replan_count": None' in codigo
    assert '"intentos_correccion": None' in codigo


# --- NODEX ---------------------------------------------------------------

def test_cada_corrida_usa_su_propio_hilo_de_checkpointer():
    """Si dos corridas compartieran hilo, el checkpoint de la primera
    contaminaría a la segunda y la repetición 2 no sería independiente de la
    1, que es justo lo que N=3 quiere medir."""
    a = nodex.thread_id_de("caso__nodex__r1__aaaaaaaa")
    b = nodex.thread_id_de("caso__nodex__r2__bbbbbbbb")
    assert a != b


@pytest.mark.parametrize("error,esperado", [
    ("GoogleAPIError: 429 RESOURCE_EXHAUSTED", "error_api"),
    ("ServiceUnavailable: 503", "error_api"),
    ("TimeoutError: timeout tras 600s", "timeout"),
    ("PreprocesamientoError: fallo el preprocesamiento", "error_preprocesamiento"),
    ("ValueError: json mal formado", "error_contrato"),
])
def test_el_estado_de_ejecucion_distingue_la_causa(error, esperado):
    """Una cuota agotada se reintenta; un JSON mal formado se corrige. Si
    los dos se registraran igual, no se sabría qué hacer."""
    assert nodex.estado_de_ejecucion({"error": error}, {}) == esperado


def test_un_estado_sin_ningun_veredicto_es_error_de_contrato():
    diagnostico = {"error": None}
    estado = {"diagnostico": "algo", "confianza": 0.9}
    assert nodex.estado_de_ejecucion(diagnostico, estado) == "error_contrato"


def test_un_estado_con_veredicto_es_completa():
    assert nodex.estado_de_ejecucion(
        {"error": None}, {"hay_anomalia": False, "hay_incidente": False}
    ) == "completa"


def test_el_runner_de_nodex_no_rellena_los_campos_de_d11():
    codigo = inspect.getsource(nodex)
    # Los menciona solo para informar su presencia, nunca para asignarlos.
    assert "d11_presente_en_el_estado" in codigo
    assert "eventos_reconstruidos\"] =" not in codigo
    assert "tecnicas_atribuidas\"] =" not in codigo


# --- control de imports --------------------------------------------------

def _nombres_definidos(modulo: str) -> set[str] | None:
    """Nombres de módulo superior definidos en `modulo`, por AST.

    Soporta asignaciones en tupla (`A, B = 1, 2`): sin eso, el control daba
    un falso positivo con `VALOR_BENIGNO, VALOR_MALICIOSO = "False", "True"`
    de `datasets/uwf.py`.
    """
    relativo = Path(*modulo.split(".")).with_suffix(".py")
    for base in (RAIZ, RAIZ_PRODUCCION):
        candidatos = (
            base / relativo,
            base / Path(*modulo.split(".")) / "__init__.py",
        )
        for candidato in candidatos:
            if not candidato.is_file():
                continue
            arbol = ast.parse(
                candidato.read_text(encoding="utf-8"), filename=str(candidato)
            )
            nombres: set[str] = set()

            def agregar(destino) -> None:
                if isinstance(destino, ast.Name):
                    nombres.add(destino.id)
                elif isinstance(destino, (ast.Tuple, ast.List)):
                    for elemento in destino.elts:
                        agregar(elemento)

            for nodo in arbol.body:
                if isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef,
                                     ast.ClassDef)):
                    nombres.add(nodo.name)
                elif isinstance(nodo, ast.Assign):
                    for destino in nodo.targets:
                        agregar(destino)
                elif isinstance(nodo, ast.AnnAssign):
                    agregar(nodo.target)
                elif isinstance(nodo, ast.ImportFrom):
                    nombres.update(a.asname or a.name for a in nodo.names)
                elif isinstance(nodo, ast.Import):
                    nombres.update(
                        a.asname or a.name.split(".")[0] for a in nodo.names
                    )
            return nombres
    return None


def _es_submodulo(paquete: str, nombre: str) -> bool:
    """`True` si `paquete/nombre.py` existe en alguno de los dos checkouts."""
    relativo = Path(*paquete.split(".")) / f"{nombre}.py"
    return any((base / relativo).is_file() for base in (RAIZ, RAIZ_PRODUCCION))


def test_todos_los_imports_de_la_capa_experimental_existen():
    """Un `from src.X import Y` con Y inexistente solo falla al ejecutar.

    En la Fase C pasó dos veces: `CONTRATO_VERSION` se importaba de
    `contracts.salida`, donde no está, y `firma_lote` de
    `tools.resumen_prompt` en vez de `tools.aggregation`. Los dos habrían
    reventado en plena campaña.
    """
    fallos = []
    for archivo in sorted((RAIZ / "src" / "experimentation").rglob("*.py")):
        if "__pycache__" in str(archivo):
            continue
        arbol = ast.parse(archivo.read_text(encoding="utf-8"),
                          filename=str(archivo))
        for nodo in ast.walk(arbol):
            if not isinstance(nodo, ast.ImportFrom):
                continue
            if not nodo.module or not nodo.module.startswith("src."):
                continue
            disponibles = _nombres_definidos(nodo.module)
            if disponibles is None:
                fallos.append(f"{archivo.name}: módulo inexistente {nodo.module}")
                continue
            for alias in nodo.names:
                if alias.name in disponibles:
                    continue
                # `from paquete import submodulo` es valido aunque el
                # `__init__.py` no reexporte el nombre: Python resuelve el
                # submodulo del disco. Sin esta rama el control daba tres
                # falsos positivos: runtime.exportacion, runtime.persistencia
                # y evaluators.deteccion.
                if _es_submodulo(nodo.module, alias.name):
                    continue
                fallos.append(
                    f"{archivo.name}: {nodo.module} no define {alias.name!r}"
                )
    assert not fallos, "\n".join(fallos)


# --- gemini_externo con un cliente simulado ---------------------------------------
#
# Hasta ahora las pruebas de este runner inspeccionaban su código fuente; estas lo
# EJECUTAN con un cliente falso (sin red y sin gastar cuota) y fijan qué telemetría
# deja: la versión que devolvió la API, los tokens de razonamiento y la cuenta de
# llamadas.

from types import SimpleNamespace


class _ClienteFalso:
    """Imita `client.models.generate_content` de google-genai."""

    def __init__(self, respuesta=None, error=None):
        self._respuesta, self._error = respuesta, error
        self.llamadas = []
        self.models = SimpleNamespace(generate_content=self._generar)

    def _generar(self, **kwargs):
        self.llamadas.append(kwargs)
        if self._error is not None:
            raise self._error
        return self._respuesta


def _respuesta_gemini(texto, version="modelo-x-001", razonamiento=9):
    uso = SimpleNamespace(prompt_token_count=100, candidates_token_count=20,
                          total_token_count=129, thoughts_token_count=razonamiento)
    return SimpleNamespace(text=texto, usage_metadata=uso, model_version=version)


def _ejecutar_con(monkeypatch, cliente):
    import google.genai.types as tipos
    import src.config as config

    monkeypatch.setattr(config, "GEMINI_API_KEY", "clave-ficticia")
    monkeypatch.setattr(gemini_externo, "_cliente", lambda *a, **k: (cliente, tipos))
    return gemini_externo.ejecutar("log de prueba", "caso__gemext__r1__00000000")


def test_gemini_externo_registra_version_devuelta_y_razonamiento(monkeypatch):
    cliente = _ClienteFalso(_respuesta_gemini('{"hay_incidente": true}'))
    estado, diagnostico = _ejecutar_con(monkeypatch, cliente)
    tel = diagnostico["telemetry"]
    assert len(cliente.llamadas) == 1
    assert tel["llm_call_count"] == 1
    assert tel["reasoning_tokens"] == 9
    assert tel["modelo_efectivo"] == "modelo-x-001"       # lo que devolvió la API
    assert tel["modelo_solicitado"] == diagnostico["modelo"]
    assert tel["llm_calls"] == [{
        "model": diagnostico["modelo"], "model_version": "modelo-x-001",
        "input_tokens": 100, "output_tokens": 20, "total_tokens": 129,
        "reasoning_tokens": 9,
    }]


def test_gemini_externo_sin_version_ni_razonamiento_los_deja_en_none(monkeypatch):
    """Antes `modelo_efectivo` repetía el nombre pedido aunque la API no
    hubiera informado nada: aparentaba una prueba que no existía."""
    cliente = _ClienteFalso(_respuesta_gemini(
        '{"hay_incidente": true}', version=None, razonamiento=None))
    _, diagnostico = _ejecutar_con(monkeypatch, cliente)
    tel = diagnostico["telemetry"]
    assert tel["modelo_efectivo"] is None
    assert tel["reasoning_tokens"] is None
    assert tel["llm_calls"][0]["model_version"] is None
    assert tel["llm_calls"][0]["reasoning_tokens"] is None


def test_regresion_una_respuesta_que_no_es_json_igual_cuenta_como_una_llamada(monkeypatch):
    """Defecto previo: una respuesta no-JSON figuraba con 0 llamadas aunque la
    llamada se hizo y gastó tokens, así que el consumo quedaba subestimado."""
    cliente = _ClienteFalso(_respuesta_gemini("esto no es json"))
    _, diagnostico = _ejecutar_con(monkeypatch, cliente)
    assert diagnostico["error"] == "la respuesta no es un objeto JSON"
    assert diagnostico["llamadas_llm"] == 1
    assert diagnostico["telemetry"]["llm_call_count"] == 1
    assert diagnostico["telemetry"]["input_tokens"] == 100       # los tokens SÍ se gastaron
    assert len(diagnostico["telemetry"]["llm_calls"]) == 1


def test_un_error_de_la_api_cuenta_como_llamada_y_deja_tokens_en_none(monkeypatch):
    cliente = _ClienteFalso(error=TimeoutError("timeout"))
    _, diagnostico = _ejecutar_con(monkeypatch, cliente)
    assert "TimeoutError" in diagnostico["error"]
    tel = diagnostico["telemetry"]
    assert tel["llm_call_count"] == 1
    assert tel["input_tokens"] is None and tel["reasoning_tokens"] is None
    assert tel["llm_calls"][0]["model_version"] is None
    assert len(cliente.llamadas) == 1          # sin reintentos ni respaldo
