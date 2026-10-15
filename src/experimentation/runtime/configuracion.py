"""Configuración congelada de la campaña. §12 del plan de continuación.

La campaña no empieza hasta que esta configuración esté estable, y cada
resultado queda atado a su `config_version`. Sin eso, un número no se puede
reproducir: basta que alguien cambie una temperatura o un prompt para que la
métrica cambie sin dejar rastro.

## Qué congela

Todo lo que puede cambiar un resultado sin cambiar el código del
experimento: versión del código, commit, modelo, temperatura, prompts,
configuración RAG, modelo de embeddings, ChromaDB, datasets, hashes,
semillas, generadores de casos, adaptador, evaluador y fecha.

## El fallback de modelo

`src/config.py` define `LLM_MODEL_PRIMARY` y `LLM_MODEL_FALLBACK`: si el
primario agota reintentos, el sistema reintenta con el otro. Para una
campaña eso es un problema serio, no un detalle: una corrida que cayó al
fallback **usó otro modelo** y no es comparable con las demás.

Por eso la configuración congela los dos nombres, y la telemetría exige el
**modelo efectivo por llamada**. La exportación marca cualquier corrida con
`uso_fallback = True`, y esas corridas no se mezclan en el agregado sin
decirlo.
"""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

#: Versión del esquema de esta configuración. No es la `config_version` de
#: una campaña: es la versión del formato en que se la registra.
ESQUEMA_CONFIGURACION = "1.0"

#: Parámetros de `src/config.py` que entran en la configuración congelada.
#: La lista es explícita a propósito: capturar el módulo completo metería
#: credenciales.
PARAMETROS_CONGELADOS = (
    "LLM_MODEL_PRIMARY",
    "LLM_MODEL_FALLBACK",
    "LLM_SIN_RESPALDO",
    "TEMPERATURE",
    "EMBEDDING_MODEL",
    "TOP_K_FEWSHOT",
    "TOP_K_ERRORS",
    "TOP_K_ATTACK",
    "ATTACK_MAX_CHARS_EMBED",
    "MAX_RAW_CHARS_EMBED",
    "CONTEXTO_PREPROCESAMIENTO_MAX_CHARS",
    "LOG_MAX_FILE_BYTES",
    "LOG_MAX_EVENTS",
    "LOG_MAX_RAW_SAMPLES",
    "LOG_PRESERVE_RAW",
)

#: Nombres que NUNCA se registran, ni siquiera truncados. De las
#: credenciales solo se registra su presencia, como booleano.
CREDENCIALES = (
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "ABUSEIPDB_API_KEY",
    "NVD_API_KEY",
)


def _git(raiz: Path, *argumentos: str) -> str | None:
    try:
        salida = subprocess.run(
            ["git", "-C", str(raiz), *argumentos],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        return salida.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def _sha256_texto(texto: str) -> str:
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def _sha256_archivo(ruta: Path) -> str:
    h = hashlib.sha256()
    with ruta.open("rb") as f:
        for bloque in iter(lambda: f.read(1 << 20), b""):
            h.update(bloque)
    return h.hexdigest()


def hashes_de_prompts(raiz_repo: Path) -> dict:
    """Hash del archivo de cada agente.

    Se hashea el archivo entero y no solo la cadena del prompt: el
    comportamiento del agente también depende del código que arma el
    contexto, no únicamente del texto de la instrucción.
    """
    directorio = raiz_repo / "src" / "agents"
    if not directorio.is_dir():
        return {}
    return {
        archivo.name: _sha256_archivo(archivo)
        for archivo in sorted(directorio.glob("*.py"))
        if archivo.name != "__init__.py"
    }


def hashes_de_capa_experimental(raiz_repo: Path) -> dict:
    """Hash de los módulos del adaptador, el evaluador y el runtime.

    §12 pide la versión del adaptador y del evaluador. Un número de versión
    escrito a mano se olvida de actualizar; el hash del código no.
    """
    resultado: dict = {}
    for subpaquete in ("adapters", "evaluators", "runtime"):
        directorio = raiz_repo / "src" / "experimentation" / subpaquete
        if not directorio.is_dir():
            continue
        resultado[subpaquete] = {
            archivo.name: _sha256_archivo(archivo)
            for archivo in sorted(directorio.glob("*.py"))
        }
    return resultado


@dataclass
class ConfiguracionCongelada:
    """Instantánea de todo lo que puede mover un resultado."""

    #: Identificador de la campaña. Entra en cada `run_id`.
    config_version: str
    esquema: str = ESQUEMA_CONFIGURACION
    congelada_utc: str = ""
    #: Código: commit, rama y si el árbol estaba limpio.
    git: dict = field(default_factory=dict)
    #: Parámetros de `src/config.py` de `PARAMETROS_CONGELADOS`.
    parametros: dict = field(default_factory=dict)
    #: Parámetros que `src/config.py` no tenía. Se listan aparte y no solo
    #: como `None` dentro de `parametros`: un nombre mal escrito en
    #: `PARAMETROS_CONGELADOS` dejaría el parámetro real SIN congelar, y un
    #: `None` entre otros catorce valores no se nota. Acá sí.
    parametros_ausentes: list = field(default_factory=list)
    #: Solo presencia (booleano) de cada credencial. Nunca el valor.
    credenciales_presentes: dict = field(default_factory=dict)
    prompts_sha256: dict = field(default_factory=dict)
    capa_experimental_sha256: dict = field(default_factory=dict)
    #: Manifiestos de datasets y sus hashes, ya generados en la Fase 2.
    datasets: dict = field(default_factory=dict)
    #: Inventario de conocimiento de la Fase 3.
    conocimiento: dict = field(default_factory=dict)
    #: Semillas de todos los generadores.
    semillas: dict = field(default_factory=dict)
    entorno: dict = field(default_factory=dict)
    #: `True` cuando D-11 está integrado en el repositorio. Mientras sea
    #: `False`, D2 y D3 no son medibles y la telemetría **no** es la
    #: definitiva (§11: no mezclar mediciones previas a D-11 con
    #: posteriores).
    d11_integrado: bool = False

    def __post_init__(self) -> None:
        if not self.config_version:
            raise ValueError("config_version no puede estar vacía")
        if self.parametros_ausentes:
            # No se lanza: puede ser legítimo que un parámetro no exista en
            # una versión del código. Pero queda en el artefacto, visible.
            pass
        for clave, valor in self.credenciales_presentes.items():
            if not isinstance(valor, bool):
                raise ValueError(
                    f"credenciales_presentes[{clave}] debe ser booleano: solo "
                    "se registra la PRESENCIA, nunca el valor"
                )

    @property
    def huella(self) -> str:
        """Hash de la configuración completa, sin la marca temporal.

        Dos campañas con la misma huella corrieron sobre lo mismo. Se
        excluye `congelada_utc` porque congelar dos veces la misma
        configuración tiene que dar la misma huella.
        """
        datos = self.to_dict()
        datos.pop("congelada_utc", None)
        return _sha256_texto(json.dumps(datos, sort_keys=True, default=str))

    def to_dict(self) -> dict:
        return asdict(self)


def detectar_d11(raiz_repo: Path) -> dict:
    """Busca los campos de D-11 en el estado y los agentes de producción.

    D-11 es una implementación **externa** (decisión del 7-oct-2026): este
    módulo solo comprueba si ya está, nunca la agrega.
    """
    campos = (
        "eventos_reconstruidos",
        "secuencia_temporal",
        "tecnicas_atribuidas",
        "evidence_uids",
    )
    objetivo = [raiz_repo / "src" / "state.py"]
    directorio_agentes = raiz_repo / "src" / "agents"
    if directorio_agentes.is_dir():
        objetivo += sorted(directorio_agentes.glob("*.py"))

    presencia: dict[str, list[str]] = {campo: [] for campo in campos}
    for archivo in objetivo:
        if not archivo.is_file():
            continue
        texto = archivo.read_text(encoding="utf-8", errors="replace")
        for campo in campos:
            if campo in texto:
                presencia[campo].append(archivo.name)

    integrado = all(
        presencia[campo]
        for campo in ("eventos_reconstruidos", "tecnicas_atribuidas")
    )
    return {
        "integrado": integrado,
        "campos": {campo: sorted(v) for campo, v in presencia.items()},
        "nota": (
            "D-11 es implementación externa. Si no está integrado, D2 y D3 "
            "no son medibles y la telemetría no es la definitiva"
        ),
    }


def congelar(
    config_version: str,
    raiz_repo: Path,
    modulo_config=None,
) -> ConfiguracionCongelada:
    """Arma la instantánea. Lee configuración y archivos; no ejecuta NODEX.

    `modulo_config` se inyecta para poder congelar sin importar
    `src.config`, que valida credenciales al importarse.
    """
    if modulo_config is None:
        import src.config as modulo_config  # import diferido

    parametros = {}
    ausentes = []
    for nombre in PARAMETROS_CONGELADOS:
        # Se declara la ausencia en vez de omitir la clave: así se nota si un
        # parámetro se renombró y la congelación quedó incompleta.
        if hasattr(modulo_config, nombre):
            parametros[nombre] = getattr(modulo_config, nombre)
        else:
            parametros[nombre] = None
            ausentes.append(nombre)

    credenciales = {
        nombre: bool(getattr(modulo_config, nombre, None))
        for nombre in CREDENCIALES
    }

    manifiestos = {}
    directorio_manifiestos = raiz_repo / "experiments" / "manifests"
    if directorio_manifiestos.is_dir():
        for archivo in sorted(directorio_manifiestos.glob("*.json")):
            manifiestos[archivo.stem] = _sha256_archivo(archivo)

    inventario = {}
    directorio_conocimiento = raiz_repo / "experiments" / "knowledge"
    for nombre, clave in (
        ("inventario_conocimiento.json", "inventario_sha256"),
        ("poblado_chroma.json", "poblado_sha256"),
    ):
        ruta = directorio_conocimiento / nombre
        if ruta.is_file():
            inventario[clave] = _sha256_archivo(ruta)

    try:
        from src.experimentation.datasets.particion import SEMILLA_PARTICION
        from src.experimentation.datasets.uwf_casos import SEMILLA_UWF
        from src.experimentation.subconjuntos import SEMILLA_SUBCONJUNTOS

        semillas = {
            "particion": SEMILLA_PARTICION,
            "uwf_casos": SEMILLA_UWF,
            "subconjuntos": SEMILLA_SUBCONJUNTOS,
        }
    except ImportError:
        semillas = {}

    return ConfiguracionCongelada(
        config_version=config_version,
        congelada_utc=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        git={
            "commit": _git(raiz_repo, "rev-parse", "HEAD"),
            "rama": _git(raiz_repo, "rev-parse", "--abbrev-ref", "HEAD"),
            # Un árbol sucio invalida la reproducibilidad: el commit no
            # describe lo que realmente corrió.
            "arbol_limpio": _git(raiz_repo, "status", "--porcelain") == "",
        },
        parametros=parametros,
        parametros_ausentes=ausentes,
        credenciales_presentes=credenciales,
        prompts_sha256=hashes_de_prompts(raiz_repo),
        capa_experimental_sha256=hashes_de_capa_experimental(raiz_repo),
        datasets={"manifiestos_sha256": manifiestos},
        conocimiento=inventario,
        semillas=semillas,
        entorno={
            "python": platform.python_version(),
            "plataforma": platform.platform(),
        },
        d11_integrado=detectar_d11(raiz_repo)["integrado"],
    )


def escribir(configuracion: ConfiguracionCongelada, raiz_repo: Path) -> Path:
    """Escribe la configuración en `experiments/config/`, sin sobrescribir."""
    destino = raiz_repo / "experiments" / "config"
    destino.mkdir(parents=True, exist_ok=True)
    archivo = destino / f"config_{configuracion.config_version}.json"
    if archivo.exists():
        raise FileExistsError(
            f"{archivo} ya existe. Una configuración congelada no se "
            "modifica: usar otra config_version"
        )
    datos = configuracion.to_dict()
    datos["huella"] = configuracion.huella
    archivo.write_text(
        json.dumps(datos, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    return archivo
