"""Driver de la Fase 3: inventario de conocimiento y configuración aislada.

**Solo lee.** Crea los directorios del experimento y escribe el inventario;
no pobla ChromaDB, no carga el modelo de embeddings, no consulta ningún
recurso externo y no ejecuta NODEX.
"""

from __future__ import annotations

import json
from pathlib import Path

from src.experimentation.contracts import PROTOCOLO_VERSION
from src.experimentation.knowledge.aislamiento import (
    HISTORIAL_NO_CONFIGURABLE_POR_ENTORNO,
    POLITICA_RECURSOS_EXTERNOS,
    VARIABLES_AISLAMIENTO,
    configuracion_experimental,
    plan_poblado_chroma,
)
from src.experimentation.knowledge.inventario import inventariar_conocimiento


def main(raiz_repo: Path, chroma_origen: Path) -> None:
    configuracion = configuracion_experimental(raiz_repo)
    configuracion.raiz.mkdir(parents=True, exist_ok=True)
    # El directorio de la base experimental se crea vacío: existir no es lo
    # mismo que estar poblado, y el inventario deja constancia de cuál es
    # cada caso.
    configuracion.chroma.mkdir(parents=True, exist_ok=True)

    inventario = {
        "protocolo_version": PROTOCOLO_VERSION,
        "configuracion_aislada": configuracion.to_dict(),
        "variables_que_config_lee_del_entorno": VARIABLES_AISLAMIENTO,
        "historial": HISTORIAL_NO_CONFIGURABLE_POR_ENTORNO,
        "politica_recursos_externos": POLITICA_RECURSOS_EXTERNOS,
        "conocimiento": inventariar_conocimiento(raiz_repo, chroma_origen),
        "poblado_chroma": plan_poblado_chroma(chroma_origen, configuracion),
        "chroma_experimental": inventariar_conocimiento(
            raiz_repo, configuracion.chroma
        )["chroma_origen"],
    }
    configuracion.inventario.write_text(
        json.dumps(inventario, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    chroma = inventario["conocimiento"]["chroma_origen"]
    print(f"ChromaDB de origen: {chroma['ruta']}")
    if chroma["existe"]:
        for coleccion in chroma["colecciones"]:
            print(f"  {coleccion['nombre']:<20} {coleccion['rol']:<13} "
                  f"embeddings={coleccion['n_embeddings']:>5}")
        print(f"  catálogo: {chroma['catalogo_mitre']}")
    modelo = inventario["conocimiento"]["modelo_embeddings"]
    print(f"modelo: {modelo['modelo']} en_cache={modelo['en_cache']} "
          f"bytes={modelo.get('bytes_totales', 0):,}")
    mitre = inventario["conocimiento"]["catalogo_mitre"]
    print(f"catálogo STIX versionado: {mitre['stix_presente']}")
    print(f"base experimental poblada: "
          f"{inventario['chroma_experimental']['existe']}")
    print(f"inventario escrito en {configuracion.inventario}")


if __name__ == "__main__":
    raiz = Path(__file__).resolve().parents[3]
    # La base de origen vive en el checkout de producción, que no se
    # modifica: solo se lee su SQLite en modo `ro`.
    origen = Path(__file__).resolve().parents[3].parent / "NODEX" / "data" / "chroma"
    main(raiz, origen)
