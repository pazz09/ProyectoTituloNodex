"""SUPERADO — NO CONECTAR. Ver el aviso al final de este docstring.

Extensión propuesta del contrato de salida de los agentes.

================================================================
AVISO (7 de octubre de 2026)
================================================================

**D-11 quedó resuelto externamente y su implementación NO es de este
módulo.** La decisión consolidada dice, textual: no implementar D-11, no
modificar los agentes para resolverlo, no cambiar sus prompts, no agregar
los campos por cuenta propia y no duplicar una implementación que ya está
siendo desarrollada por otro proceso.

Este archivo se escribió **antes** de esa decisión, como propuesta para que
la autora eligiera. Queda en el repositorio por dos razones:

1. documenta el diagnóstico que llevó a D-11, con la medición que lo
   sustenta (la tabla de más abajo);
2. deja constancia de que el adaptador ya sabe consumir esos tres campos,
   así que cuando la implementación externa aparezca no hay que tocar la
   capa experimental.

Lo que **no** debe hacerse con él: conectar `ADDENDUM_TRIAGE` a ningún
agente, ni tomar `ESQUEMA_TRIAGE_PROPUESTO` como el contrato real. El
contrato real es el que defina la implementación externa; cuando esté,
`src/experimentation/runtime/configuracion.py::detectar_d11()` lo confirma y
la Fase D valida la integración.

El texto que sigue es el diagnóstico original, conservado sin cambios.

## El problema que resuelve

De las cinco dimensiones del protocolo, dos **no se pueden medir hoy**
porque NODEX no produce la salida correspondiente:

| Dimensión | Qué produce NODEX hoy |
|---|---|
| D1 detección | `hay_anomalia` / `hay_incidente`, booleanos. **Medible.** |
| D2 reconstrucción | Nada. Lo único parecido es la cronología del preprocesamiento, que es determinística y no es una afirmación del sistema. |
| D3 MITRE | Solo candidatas del RAG (`tecnicas_mitre`). El agente de triage recibe la instrucción de *citar* IDs dentro del texto libre de `diagnostico` (`agente_analista_triage.py:71`), sin campo propio y sin evidencia. |
| D4 reporte | `diagnostico` + `evaluacion_auditor` + comandos. **Medible.** |
| D5 consumo | Telemetría (Fase 6). **Medible.** |

Sin un cambio en los agentes, D2 y D3 quedan `no_evaluable` en todos los
casos, de forma permanente. No es un problema de desempeño: es que no hay
salida que puntuar.

## Lo que no hay que confundir

Agregar estos campos **no es instrumentación neutral**. Pedirle al agente
que enumere los eventos que constituyen el incidente y que atribuya
técnicas con evidencia cambia su tarea: puede mejorar el análisis, o
empeorarlo al gastar atención en estructurar la respuesta. Por eso:

1. La campaña evalúa el sistema **con** esta extensión activa, y la tesis
   tiene que describir esa versión, no la anterior.
2. El prompt queda versionado (`VERSION_CONTRATO_AGENTES`) y su hash entra
   en la procedencia de cada corrida (Fase 6, acción 3).
3. Si se quisiera medir el efecto del cambio en sí, haría falta correr las
   dos versiones, que es una campaña aparte y no está en este plan.

## Alternativa sin tocar los agentes

Extraer los IDs citados en prosa con una expresión regular. Se descartó
como fuente de atribuciones puntuables porque esos IDs no traen
`evidence_uids`, y el protocolo no puntúa una atribución sin evidencia: una
técnica adivinada y una fundamentada no son el mismo resultado. Los IDs en
prosa sí se registran en `_meta`, como señal de que la capacidad existe en
alguna forma.
"""

from __future__ import annotations

#: Versión del contrato de agentes. Cambiarla obliga a registrar el cambio
#: en la procedencia y a no comparar corridas de versiones distintas como
#: si fueran lo mismo.
VERSION_CONTRATO_AGENTES = "1.0.0-propuesta-SUPERADA"

#: Campos nuevos que el estado tendría que llevar. Son los que
#: `src/experimentation/adapters/extraccion.py` ya sabe leer: si se activan,
#: el adaptador los toma sin más cambios.
CAMPOS_NUEVOS_DE_ESTADO = {
    "tecnicas_atribuidas": (
        "list[dict] con {id, nivel, name, evidence_uids}. Las técnicas y "
        "tácticas que el sistema AFIRMA que aplican al caso, cada una con "
        "los identificadores de los eventos que la sustentan. Distinto de "
        "`tecnicas_mitre`, que son las candidatas que recuperó el RAG"
    ),
    "eventos_reconstruidos": (
        "list[dict] con {uid, timestamp, event_type, entities, "
        "evidence_uids}. Los eventos que el sistema considera el núcleo del "
        "incidente. En UWF el `uid` es el de Zeek y viene en el propio caso"
    ),
    "secuencia_temporal": (
        "list[str] con los `uid` de `eventos_reconstruidos` en el orden en "
        "que el sistema cree que ocurrieron"
    ),
}

#: Añadido al prompt del agente de triage. Se agrega al final de la
#: instrucción existente, sin reemplazarla: el objetivo es ampliar el
#: contrato de salida, no cambiar la tarea de diagnóstico.
#:
#: Tres cuidados en la redacción, cada uno por una razón concreta:
#:
#: - "solo si el log lo sustenta": sin esa condición el agente completa los
#:   campos para satisfacer el formato, que es exactamente la información no
#:   sustentada que la rúbrica penaliza.
#: - "usa los identificadores que aparecen en el log": el `uid` tiene que
#:   venir del caso. Uno inventado no coincide con `core_event_uids` y
#:   además es una afirmación falsa.
#: - listas vacías explícitas: un campo ausente y una lista vacía dicen
#:   cosas distintas. La lista vacía es "no encontré nada"; la ausencia es
#:   un fallo de formato, y el adaptador los distingue.
ADDENDUM_TRIAGE = """
Además del diagnóstico, devuelve estos tres campos, completándolos SOLO si
el contenido del log lo sustenta:

- "eventos_reconstruidos": los eventos que constituyen el incidente. Para
  cada uno: {"uid": "<identificador tal como aparece en el log>",
  "timestamp": "<marca de tiempo del log>", "event_type": "<qué ocurrió>",
  "entities": ["<IP, host o usuario involucrado>"]}. Usa los
  identificadores que aparecen en el log; no inventes ninguno. Si el log no
  tiene identificadores de evento, devuelve la lista vacía.
- "secuencia_temporal": los "uid" de esos eventos en el orden en que crees
  que ocurrieron.
- "tecnicas_atribuidas": las técnicas o tácticas MITRE ATT&CK que afirmas
  que aplican a ESTE caso. Para cada una: {"id": "T####", "nivel":
  "tecnica" o "tactica", "evidence_uids": ["<uid de los eventos que la
  sustentan>"]}. Una técnica sin evidencia no se cuenta: si no puedes citar
  los eventos que la respaldan, no la incluyas. No incluyas una técnica
  solo porque aparezca en la lista de TÉCNICAS MITRE ATT&CK recuperadas:
  esa lista son candidatas por similitud, no conclusiones.

Si no encuentras nada para alguno de los tres campos, devuélvelo como lista
vacía. No omitas el campo.
""".strip()

#: Esquema JSON resultante del agente de triage, para la revisión.
ESQUEMA_TRIAGE_PROPUESTO = {
    "diagnostico": "str",
    "necesita_rag": "bool",
    "eventos_reconstruidos": "list[{uid, timestamp, event_type, entities}]",
    "secuencia_temporal": "list[str]",
    "tecnicas_atribuidas": "list[{id, nivel, evidence_uids}]",
}

#: Riesgos del cambio, para que la decisión se tome con ellos a la vista.
RIESGOS = {
    "cambia_el_sistema_evaluado": (
        "la campaña mediría la versión con estos campos, no la actual. Hay "
        "que decirlo en la tesis"
    ),
    "puede_degradar_el_diagnostico": (
        "pedir estructura consume atención del modelo; el diagnóstico en "
        "prosa podría empeorar"
    ),
    "aumenta_los_tokens_de_salida": (
        "más campos es más salida por llamada, lo que afecta la dimensión "
        "de consumo (D5). La comparación con el agente único sigue siendo "
        "válida si el agente único recibe el mismo contrato de salida"
    ),
    "riesgo_de_uid_inventados": (
        "mitigable verificando contra el caso: un uid que no está en el "
        "caso no se cuenta como acierto y se registra como afirmación no "
        "sustentada"
    ),
    "el_agente_unico_debe_recibir_el_mismo_contrato": (
        "si no, la comparación entre arquitecturas mediría el contrato de "
        "salida y no la arquitectura"
    ),
}

#: Qué pasa si NO se activa.
SI_NO_SE_ACTIVA = {
    "D2_reconstruccion": "no_evaluable en los 336 casos, de forma permanente",
    "D3_mitre": "no_evaluable en los 336 casos, de forma permanente",
    "consecuencia": (
        "la campaña mediría detección, calidad de reporte y consumo. "
        "Reconstrucción y atribución MITRE quedarían declaradas como "
        "capacidades no medidas, no como capacidades ausentes: el sistema "
        "cita técnicas en prosa, pero sin evidencia asociada no hay forma "
        "de puntuarlas"
    ),
}
