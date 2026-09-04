# Línea base del preprocesamiento

Fecha de levantamiento: 3 de septiembre de 2026.

Este documento congela el comportamiento observable que debe conservar la
capa de compatibilidad durante la migración al preprocesamiento heterogéneo.
No define el diseño nuevo; registra el punto de partida.

## Estado del repositorio

- Rama: `main`.
- Commit de referencia: `c090aef07a9fbc51d19f3554d76b59bfe940b404`.
- Estado al comenzar el levantamiento: limpio y sincronizado con
  `origin/main`.
- Pruebas definidas: 85 funciones `test_*`.

## Limitación del entorno de verificación

La suite no pudo ejecutarse durante este levantamiento porque el entorno no
expone una instalación de Python. Tampoco están disponibles `pytest`, `pip`,
`uv`, Conda ni un entorno virtual local. Por lo tanto, la presencia de las 85
pruebas no debe interpretarse como una corrida exitosa actual.

Antes de modificar el comportamiento productivo se debe disponer de Python,
instalar `requirements.txt` y ejecutar `python -m pytest -q`. El resultado de
esa corrida deberá agregarse a este documento.

## Entradas de referencia disponibles

| Entrada | Tamaño | Propósito |
|---|---:|---|
| `data/logs/HDFS_2k.log` | 287.848 bytes | Regresión del adaptador HDFS |
| `data/logs/BGL_2k.log` | 317.150 bytes | Regresión del adaptador BGL |
| `data/labels/hdfs_anomaly_label_2k.csv` | 71.307 bytes | Ground truth HDFS para evaluación |

Las pruebas también contienen muestras sintéticas de auth-log, CSV/TSV,
Zeek y variantes BGL/HDFS.

## Comportamiento actual

`src.tools.aggregation.aggregate_logs` realiza estas operaciones:

1. Divide el lote mediante `splitlines()` y elimina líneas vacías.
2. Usa las primeras 50 líneas como muestra.
3. Selecciona un único adaptador para todo el lote si alcanza confianza 0,5.
4. Prueba HDFS, BGL y CSV; usa auth-log como fallback.
5. Parsea cada línea con el mismo adaptador.
6. Agrega servicios, eventos, timestamps e información por IP.

El contrato por línea heredado contiene, como mínimo:

```python
{
    "ip": str | None,
    "usuario": str | None,
    "servicio": str,
    "evento": str,
    "intentos_fallidos": int,
    "timestamp": str | None,
}
```

CSV puede agregar `ip_destino` y `etiqueta`.

## Contrato de compatibilidad de `resumen_logs`

Mientras existan consumidores v1, el nuevo preprocesamiento debe seguir
entregando los siguientes campos derivados:

```python
{
    "formato_detectado": str,
    "total_lineas": int,
    "servicios": dict[str, int],
    "eventos": dict[str, int],
    "ventana_temporal": {
        "inicio": str | None,
        "fin": str | None,
    },
    "n_ips_distintas": int,
    "ips_distintas": list[str],
    "por_ip": dict[str, dict],
}
```

`por_ip` conserva actualmente:

```python
{
    "intentos_fallidos": int,
    "usuarios_objetivo": list[str],
    "servicios": list[str],
    "n_eventos": int,
    "n_como_origen": int,
    "n_como_destino": int,
}
```

Cuando un CSV trae una columna de etiqueta, el resumen puede incluir además
`etiquetas`.

## Consumidores que dependen del contrato v1

- `src/pipeline.py`: reputación de `ips_distintas`, evento SSE inicial y
  construcción del estado.
- `src/tools/resumen_prompt.py`: orden y acotamiento de `ips_distintas`,
  `por_ip` y `reputacion_ips`.
- `src/agents/agente_selector_herramientas.py`: selección basada en
  `servicios`.
- `src/tools/tool_consultar_cve.py`: usa el primer servicio como keyword.
- `src/tools/aggregation.py:firma_lote`: firma basada en líneas, IP,
  servicios y eventos.
- `src/tools/log_runner.py`: persiste los campos agregados v1.
- `src/api/static/index.html`: muestra un único formato, líneas, IP y ventana
  temporal.
- Pruebas de agregación, CSV, formatos, prompt y evaluación.

## Resultados persistidos actuales

Los archivos producidos por `log_runner.py` contienen:

- `archivo_origen`
- `formato_detectado`
- `total_lineas`
- `n_ips_distintas`
- `ventana_temporal`
- `servicios`
- `eventos`
- diagnóstico y campos posteriores del grafo

No contienen todavía versión del esquema, cobertura del parsing, distribución
de decodificadores, advertencias ni configuración efectiva de preprocesamiento.

## Riesgos confirmados para la migración

1. Cambiar directamente `aggregate_logs()` rompería varios consumidores.
2. `total_lineas` mezcla actualmente líneas físicas y eventos lógicos.
3. `usuario` representa conceptos incompatibles: usuario, bloque HDFS, nodo
   BGL o identificador de flujo.
4. La detección única por lote no soporta entradas heterogéneas.
5. El fallback auth-log atribuye semántica a texto desconocido.
6. Etiquetas BGL/CSV pueden influir en `evento_critico`, lo que debe separarse
   del canal de features para evitar fuga de ground truth.
7. La firma y los embeddings históricos cambiarán de significado con el
   esquema v2 y deberán versionarse.

## Puerta para comenzar la Fase 1

La Fase 1 puede definir modelos nuevos sin sustituir todavía el contrato v1.
Antes de integrar esos modelos al pipeline debe resolverse la ejecución de la
suite actual o dejar la excepción explícitamente aceptada.
