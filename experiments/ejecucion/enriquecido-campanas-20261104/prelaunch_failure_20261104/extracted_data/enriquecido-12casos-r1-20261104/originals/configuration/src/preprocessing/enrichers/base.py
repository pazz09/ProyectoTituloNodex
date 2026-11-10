"""Interfaz de los enriquecedores de producto (Fase 6 del plan).

Un enriquecedor agrega el conocimiento específico de un producto sobre un
evento que **ya fue decodificado**. La diferencia con el esquema v1 es de
arquitectura: allí, reconocer HDFS o BGL era lo que elegía el parser del
lote entero; acá el parsing es genérico y el producto solo agrega detalle.
Una fuente sin perfil completa el flujo igual, con menos campos.

Dos reglas que el plan fija como criterio de aceptación y que conviene no
perder de vista al agregar un enriquecedor nuevo:

**Ningún enriquecedor decide que existe un ataque.** Puede leer la
severidad que el propio log declara (`WARN`, `FATAL`), porque eso es
contenido del registro. No puede marcar un evento como crítico por su
cuenta ni traducir una etiqueta del dataset en una señal observable: eso
sería fabricar la respuesta que el detector debe encontrar.

**Las etiquetas de evaluación salen por otra puerta.** `extraer_ground_truth()`
existe justamente para que el flag de alerta de BGL o el `label_tactic` de
UWF-ZeekDataFall22 viajen al canal separado en vez de contaminar las
features. Devolver `None` es lo normal: la mayoría de los logs reales no
vienen etiquetados.
"""

from src.preprocessing.models import GroundTruthRecord, NormalizedEvent


class Enricher:
    """Perfil de producto. Sin estado: recibe el evento y lo devuelve."""

    nombre: str = "base"
    producto: str | None = None

    def aplica(self, evento: NormalizedEvent) -> bool:
        """¿Este evento pertenece al producto que el enriquecedor conoce?"""
        raise NotImplementedError

    def enriquecer(self, evento: NormalizedEvent) -> NormalizedEvent:
        """Agrega campos del producto. Muta y devuelve el mismo evento."""
        raise NotImplementedError

    def extraer_ground_truth(self, evento: NormalizedEvent) -> GroundTruthRecord | None:
        """Etiqueta de evaluación del dataset, si la hubiera.

        Lo que devuelve NO debe quedar en el evento: el pipeline lo desvía
        al canal de ground truth.

        **Orden obligatorio: primero esto, después `enriquecer()`.** Un
        enriquecedor puede retirar del evento las columnas de etiqueta —el
        de Zeek lo hace con `label_tactic` y compañía—, así que invertir el
        orden dejaría el canal de ground truth vacío sin que nada falle. El
        pipeline respeta esta secuencia y hay un test que la fija.
        """
        return None
