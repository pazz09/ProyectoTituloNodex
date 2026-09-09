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
- Pruebas definidas al levantar la línea base: 85 funciones `test_*`.
- Pruebas al cierre del desarrollo (9-sep-2026): **317**, todas en verde.
- Commit de la verificación de cierre: `dd73cd21eec47324e06166c285fa8771f1ad99a1`.

## Ejecución de la suite (resuelto el 4-sep-2026)

La limitación registrada en el levantamiento inicial —«el entorno no expone una
instalación de Python»— era en parte de entorno y en parte un **defecto real
del código**, que quedó identificado y corregido como parte de la Fase 0.

### Defecto encontrado

`src/llm.py` invocaba `validate_config()` en **tiempo de importación**. Como
consecuencia, en cualquier clon sin `.env` la COLECCIÓN de pytest abortaba con
`OSError: Falta GEMINI_API_KEY` en cuatro archivos —`test_llm.py`,
`test_eval_deteccion.py`, `test_ciclo_correccion.py` y
`test_agente_auditor_final.py`—, dejando **44 de las 85 pruebas sin ejecutar**.
Esas cuatro solo importan el módulo para simular el LLM; ninguna llama a la API.

Esto además contradecía la afirmación del README de que la suite es
determinística y no requiere API keys: solo lo era para 41 de las 85 pruebas.

### Corrección aplicada

La validación de credenciales se difirió al primer uso real, en `llm_json()`,
mediante el helper `_asegurar_credenciales()`. El cliente `genai.Client` se
sigue construyendo al importar —no valida la credencial ni toca la red al
crearse— para que continúe siendo monkeypatcheable desde las pruebas. Los
helpers internos (`_generate_con_backoff`) no exigen credencial, de modo que
los tests puedan ejercitar el backoff y el modelo de respaldo con el cliente
simulado.

### Resultado verificado

| Escenario | Resultado |
|---|---|
| Entorno con `.env` configurado | **85 passed** |
| Clon limpio, sin `.env` ni variables de entorno | **85 passed** |
| `llm_json()` sin credencial | Lanza `OSError` con el mensaje original |

No se detectaron fallos preexistentes más allá del descrito. La suite es ahora
reproducible sin credenciales, que era la condición de la puerta de la Fase 1.

Comando de verificación:

```bash
python -m pytest tests/ -q
```

## Verificación de cierre (9-sep-2026)

La nota original de este documento —«la suite no pudo ejecutarse durante este
levantamiento porque el entorno no expone una instalación de Python»— queda
resuelta. La suite se ejecutó contra el repositorio real, con las dependencias
instaladas:

```
$ python -m pytest -q
317 passed, 1 warning in 19.23s
```

**317 pruebas, 0 fallos.** El único aviso es un `StarletteDeprecationWarning`
de `fastapi.testclient` sobre `httpx`, ajeno al código del proyecto.

No hacen falta credenciales: la suite corre completa en un clon sin `.env`
(ver «Ejecución de la suite» arriba). Tampoco cambia el resultado según el
motor de preprocesamiento: **317 pasan tanto con `LOG_PREPROCESSING_ENGINE=v1`
como con `=v2`**.

Distribución por archivo:

| Archivo | Pruebas |
|---|---:|
| `test_preprocessing_decoders.py` | 36 |
| `test_preprocessing_heterogeneous.py` | 22 |
| `test_preprocessing_validacion.py` | 21 |
| `test_preprocessing_models.py` | 20 |
| `test_preprocessing_config.py` | 20 |
| `test_preprocessing_aggregation.py` | 20 |
| `test_preprocessing_segmentation.py` | 17 |
| `test_preprocessing_ground_truth.py` | 17 |
| `test_preprocessing_consumidores.py` | 17 |
| `test_llm.py` | 17 |
| `test_eval_deteccion.py` | 17 |
| `test_preprocessing_enrichers.py` | 15 |
| `test_preprocessing_normalization.py` | 14 |
| `test_preprocessing_integracion.py` | 13 |
| `test_preparar_mitre_attack.py` | 11 |
| `test_aggregation_csv.py` | 9 |
| `test_agente_auditor_final.py` | 8 |
| `test_resumen_prompt.py` | 6 |
| `test_aggregation_multi_formato.py` | 5 |
| `test_reputation.py` | 4 |
| `test_validation.py` | 3 |
| `test_aggregation.py` | 3 |
| `test_ciclo_correccion.py` | 2 |

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

Condición original: «debe resolverse la ejecución de la suite actual o dejar la
excepción explícitamente aceptada».

**Resuelta el 4-sep-2026.** La suite corre completa (85/85) tanto con `.env`
configurado como en un clon limpio sin credenciales —ver «Ejecución de la
suite» arriba—, de modo que no queda ninguna excepción que aceptar. Los
criterios de aceptación de la Fase 0 quedan cubiertos:

- Suite ejecutada y resultado documentado: **85 passed**, reproducible.
- Fallos preexistentes identificados: uno, el de validación en importación, ya
  corregido.
- Contrato v1 explícito e inventario de consumidores: documentados arriba.

La Fase 1 puede definir modelos nuevos sin sustituir todavía el contrato v1.
