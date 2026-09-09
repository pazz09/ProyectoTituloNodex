"""Descarga y parsea el catálogo oficial de MITRE ATT&CK (Enterprise, STIX
2.1) para poblar la colección `attack_techniques` de ChromaDB -- ver
`src/memory.py` y README, "Integración MITRE ATT&CK", y Tabla 7.4 (Brecha 2:
"Falta de integración con CTI estructurada") del informe.

Fuente oficial: repositorio `mitre-attack/attack-stix-data` (el mismo que
publica MITRE ATT&CK Navigator). Se apunta a la ruta "flotante"
`enterprise-attack.json` en `master` -- siempre sirve la ÚLTIMA versión
publicada, no la v15 que cita el informe (decisión explícita de Antonia,
3-sep-2026: usar la versión actual, no la del texto -- hay que actualizar
esa cita al redactar la sección correspondiente).

La corrida real del 4-sep-2026 cargó la **v19.2**: 697 técnicas, 222
principales y 475 sub-técnicas, con la procedencia en
`data/mitre_attack/provenance.json`. Por eso este script
imprime y registra la versión real (`x_mitre_version` del objeto
`x-mitre-collection` del bundle) que encontró al correr, para que la
corrida quede documentada y sea reproducible aunque el archivo cambie
más adelante.

Solo se cargan técnicas ENTERPRISE (no ICS ni Mobile -- el informe no
menciona esas matrices) y se excluyen los objetos `revoked` o
`x_mitre_deprecated` (siguen en el bundle por historial, pero MITRE los
marca explícitamente como "no usar").

Atribución: los datos de ATT&CK NO son Creative Commons -- MITRE exige una
nota de atribución textual (ver `MITRE_ATTACK_ATTRIBUTION` en
src/config.py, y https://attack.mitre.org/resources/terms-of-use/,
verificado 3-sep-2026). Se guarda un archivo de procedencia junto a los
datos para poder citarla en el informe/README.

Requiere red real -- no funciona desde un sandbox sin acceso a internet
(este repo se edita también desde un puente de dispositivo sin red; correr
este script directamente en tu máquina, igual que
`preparar_labels_hdfs.py`). Se corre para poblar (o repoblar, tras
actualizar de versión) `attack_techniques`; `cargar_tecnicas_attack` usa
`upsert`, así que correrlo de nuevo no duplica documentos.

Uso:
    python -m src.tools.preparar_mitre_attack
"""

import json
import time
from pathlib import Path

import requests

from src.config import MITRE_ATTACK_ATTRIBUTION, MITRE_ATTACK_URL
from src.memory import LongTermMemory

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_DEST_DIR = _REPO_ROOT / "data" / "mitre_attack"
_PROVENANCE_PATH = _DEST_DIR / "provenance.json"


def _extraer_tecnicas(bundle: dict) -> list[dict]:
    """Filtra un bundle STIX 2.1 de ATT&CK Enterprise a una lista plana de
    técnicas usables. Función pura -- sin red, sin ChromaDB -- para poder
    testearla con un bundle de ejemplo pequeño (ver
    tests/test_preparar_mitre_attack.py).

    Cada dict de salida trae: technique_id, name, description, tactics
    (lista de phase_name), is_subtechnique, url.

    Se descartan:
    - objetos que no son `attack-pattern` (tácticas, colecciones,
      relaciones, identidades, marcas de referencia, etc. -- el bundle
      trae todo eso mezclado en "objects").
    - objetos `revoked` o `x_mitre_deprecated` (MITRE los mantiene por
      historial pero indica no usarlos).
    - attack-patterns sin un external_reference con
      source_name == "mitre-attack" (no debería pasar en un bundle
      Enterprise real, pero un objeto así no tendría ID de técnica citable).
    """
    tecnicas = []
    for obj in bundle.get("objects", []):
        if obj.get("type") != "attack-pattern":
            continue
        if obj.get("revoked") or obj.get("x_mitre_deprecated"):
            continue

        technique_id = None
        url = None
        for ref in obj.get("external_references", []):
            if ref.get("source_name") == "mitre-attack":
                technique_id = ref.get("external_id")
                url = ref.get("url")
                break
        if not technique_id:
            continue

        tactics = [
            fase.get("phase_name")
            for fase in obj.get("kill_chain_phases", [])
            if fase.get("kill_chain_name") == "mitre-attack" and fase.get("phase_name")
        ]

        tecnicas.append({
            "technique_id": technique_id,
            "name": obj.get("name", ""),
            "description": obj.get("description", ""),
            "tactics": tactics,
            "is_subtechnique": bool(obj.get("x_mitre_is_subtechnique", False)),
            "url": url,
        })
    return tecnicas


def _version_del_bundle(bundle: dict) -> str | None:
    """Busca el objeto `x-mitre-collection` del bundle, que trae
    `x_mitre_version` -- la versión real de ATT&CK que sirvió el archivo
    "flotante" en el momento de esta corrida (puede no ser v15, ver
    docstring del módulo)."""
    for obj in bundle.get("objects", []):
        if obj.get("type") == "x-mitre-collection":
            return obj.get("x_mitre_version")
    return None


def main() -> None:
    print(f"Descargando catálogo MITRE ATT&CK (Enterprise, STIX 2.1) desde {MITRE_ATTACK_URL} ...")
    resp = requests.get(MITRE_ATTACK_URL, timeout=120)
    resp.raise_for_status()
    bundle = resp.json()

    version = _version_del_bundle(bundle)
    print(f"  Versión encontrada: {version or 'desconocida (no se halló x-mitre-collection en el bundle)'}")

    tecnicas = _extraer_tecnicas(bundle)
    n_subtecnicas = sum(1 for t in tecnicas if t["is_subtechnique"])
    print(f"  {len(tecnicas)} técnicas utilizables ({len(tecnicas) - n_subtecnicas} técnicas "
          f"principales + {n_subtecnicas} sub-técnicas; excluidas revoked/deprecated).")

    if not tecnicas:
        raise SystemExit(
            "0 técnicas extraídas del bundle -- algo está mal (¿cambió la estructura del "
            "STIX oficial, o MITRE_ATTACK_URL apunta a un archivo vacío/corrupto?). No se "
            "modificó ChromaDB."
        )

    print("Cargando en ChromaDB (colección attack_techniques, upsert por technique_id)...")
    ltm = LongTermMemory()
    n_cargadas = ltm.cargar_tecnicas_attack(tecnicas)
    print(f"  {n_cargadas} documentos escritos.")

    _DEST_DIR.mkdir(parents=True, exist_ok=True)
    procedencia = {
        "fuente_url": MITRE_ATTACK_URL,
        "version_attack": version,
        "n_tecnicas": len(tecnicas),
        "n_subtecnicas": n_subtecnicas,
        "fecha_corrida_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "atribucion": MITRE_ATTACK_ATTRIBUTION,
    }
    with open(_PROVENANCE_PATH, "w", encoding="utf-8") as f:
        json.dump(procedencia, f, ensure_ascii=False, indent=2)
    print(f"Procedencia guardada en {_PROVENANCE_PATH} (versión, fecha, atribución -- citar en el informe).")


if __name__ == "__main__":
    main()
