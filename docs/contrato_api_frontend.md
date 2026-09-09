# Contrato de la API para el frontend

Campos **medidos contra respuestas reales** de la API el 9-sep-2026 (corrida
`666e9e69`, `auth_muestra.log`), no inferidos del código. Sirve para conectar
el frontend de Next.js sin asumir nombres.

Base de desarrollo: `http://127.0.0.1:8000`. CORS habilitado para
`http://localhost:3000` y `http://127.0.0.1:3000`, con `Content-Disposition`
en `expose_headers` (hace falta para nombrar el PDF descargado).

## `POST /api/analizar`

`multipart/form-data`, campo **`archivo`**.

```json
{ "job_id": "666e9e69be694ba48e528cac214968fc", "nombre_archivo": "auth_muestra.log" }
```

Errores que devuelve, todos con `{"detail": "..."}`:

| Código | Cuándo |
|---|---|
| 413 | El archivo supera `LOG_MAX_FILE_BYTES` |
| 415 | Hay bytes nulos en los primeros 8 KB (parece binario) |
| 400 | El archivo está vacío o solo espacios |
| 422 | Falta el campo `archivo` |

**Límite real de tamaño: 52 428 800 bytes = 50 MiB** (`LOG_MAX_FILE_BYTES` en
`src/config.py`, configurable por entorno). No 500 MB.

## `GET /api/stream/{job_id}` (Server-Sent Events)

Cada mensaje es `data: <json>`. Cuatro tipos:

### `inicio` — una vez, antes de tocar el LLM

```jsonc
{
  "tipo": "inicio",
  "resumen": {
    "formato_detectado": "auth_log",
    "total_lineas": 23,
    "n_ips_distintas": 3,
    "servicios": { "sshd": 18, "desconocido": 2, "apache": 2, "kernel": 1 },
    "eventos": { "acceso_fallido": 13, "evento_generico": 10 },
    "ventana_temporal": { "inicio": "Sep  9 03:12:01", "fin": "Sep  9 03:22:14" },
    "reputacion_ips": { "45.155.205.233": { "fuente": "abuseipdb", "ip": "...", "score": 100, "categoria": "malicioso" } }
  },
  "preprocesamiento": {},   // vacío con el motor v1 (el predeterminado)
  "advertencias": []
}
```

`formato_detectado` de acá es el valor real para el panel lateral.

### `nodo` — una vez por nodo ejecutado

```json
{ "tipo": "nodo", "nombre": "agente_analista_triage", "detalle": { ... } }
```

`nombre` es uno de los 7 nodos. **Un nodo revisitado emite un evento cada vez**
— no hay campo de "número de visita": el contador lo lleva el frontend.

Orden observado en una corrida real (`auth_muestra.log`):

```
agente_analista_triage → tool_consultar_rag → agente_analista_triage
  → agente_selector_herramientas → tool_consultar_cve
  → agente_ingeniero_mitigacion → tool_validar_comandos → agente_auditor_final
```

`tool_consultar_cve` **puede no aparecer**: lo decide
`agente_selector_herramientas`. Lo mismo `tool_consultar_rag`.
`agente_ingeniero_mitigacion` y `tool_validar_comandos` pueden repetirse si los
comandos se rechazan (ciclo de corrección, `intentos_correccion` en el reporte).

### `error` — termina el stream

```json
{ "tipo": "error", "mensaje": "ResourceExhausted: 429 ..." }
```

**Después de un `error` NO llega un `final`.** El stream termina ahí.

### `final` — una vez, solo si no hubo error

```jsonc
{
  "tipo": "final",
  "reporte": {
    "diagnostico": "…",
    "confianza": 1.0,
    "hay_incidente": true,
    "hay_anomalia": true,
    "evaluacion_auditor": "…",
    "tecnicas_mitre": [ /* ver abajo */ ],
    "comandos_mitigacion": ["iptables -I INPUT …", "…"],
    "comandos_validos": true,
    "cves_encontrados": [],
    "intentos_correccion": 1,
    "requiere_revision_humana": false,
    "firma": "v1|lineas=23 ips=3 servicios=[…]"
  }
}
```

**El `final` no trae `job_id`, ni `archivo_origen`, ni `formato_detectado`, ni
`total_lineas`, ni `motor_preprocesamiento`, ni `timestamp`.** El `job_id` hay
que conservarlo de la respuesta de `POST /api/analizar`; los demás campos están
repartidos entre el evento `inicio` y la fila del historial.

## `GET /api/historial/{job_id}`

Devuelve la fila **plana**, que es un shape **distinto** al del evento `final`:

| Campo | Tipo | Ejemplo |
|---|---|---|
| `job_id` | str | `"666e9e69…"` |
| `timestamp` | str | `"2026-09-09T16:33:51Z"` |
| `archivo_origen` | str | `"auth_muestra.log"` |
| `formato_detectado` | str | `"auth_log"` |
| `total_lineas` | int | `23` |
| `motor_preprocesamiento` | str | `"v1"` |
| `diagnostico` | str | … |
| `confianza` | float | `1.0` |
| `hay_anomalia` / `hay_incidente` / `requiere_revision_humana` | bool | |
| `n_comandos_mitigacion` | int | `9` |
| `evaluacion_auditor` | str | … |
| `tecnicas_mitre` | list | ver abajo |
| `estado` | str | `"completo"` \| `"error"` |
| `error_mensaje` | str \| null | |
| `feedback_correcto` | bool \| **null** | `null` = todavía sin revisar |
| `feedback_comentario` | str \| null | |
| `feedback_timestamp` | str \| null | |
| `resumen_json` | dict | copia del `resumen` del evento `inicio` |
| `reporte_json` | dict | copia del `reporte` del evento `final` |

> **Recomendación para no duplicar lógica de render:** al recibir el evento
> `final`, pedir `GET /api/historial/{job_id}` y alimentar la vista de informe
> con **este** shape, el mismo que usa el detalle del historial. Si no, la vista
> tiene que aceptar dos formas distintas.
>
> Hay una carrera acotada: la fila se escribe en el `finally` del generador SSE,
> es decir inmediatamente **después** de emitir el `final`. Si la petición llega
> antes, responde 404 — conviene un reintento corto.

## `GET /api/historial?limit=&offset=`

`limit` se acota a [1, 500] (default 50); `offset` a ≥ 0. Orden: más reciente
primero.

```json
{ "total": 5, "limit": 50, "offset": 0, "corridas": [ /* filas planas */ ] }
```

## `GET /api/historial/{job_id}/pdf`

`application/pdf` con `Content-Disposition: attachment; filename=informe_<job_id>.pdf`.
404 si no existe. No vuelve a correr el grafo (no cuesta cuota de LLM).

## `POST /api/feedback/{job_id}`

```json
{ "correcto": true, "comentario": "texto o null" }
```

Respuesta:

```json
{ "guardado": true, "memoria": { "guardado_en": "host_history",
  "promovido_a_attack_patterns": true, "error_registrado": false } }
```

`memoria` viene en `null` (con un campo `detalle` explicando por qué) si la
corrida no conserva la firma del lote o si falla la escritura a ChromaDB — en
los dos casos el veredicto **sí** quedó guardado. 404 si el `job_id` no existe;
422 si el cuerpo no valida.

## `tecnicas_mitre` — forma real de cada elemento

No es `{technique_id, nombre}`:

```jsonc
{
  "texto": "Remote Services. Adversaries may use [Valid Accounts](https://…) to log into a service that accepts remote connections, such as telnet, SSH, and VNC…",
  "meta": {
    "technique_id": "T1021",
    "name": "Remote Services",
    "tactics": "lateral-movement",       // string separado por comas, no lista
    "url": "https://attack.mitre.org/techniques/T1021",
    "is_subtechnique": false
  },
  "similitud": 0.484
}
```

Para las tarjetas: **ID** = `meta.technique_id`, **nombre** = `meta.name`,
**descripción corta** = `texto` recortado (el texto viene truncado a 800
caracteres desde la indexación, y empieza repitiendo el nombre).

### Atribución de MITRE (obligatoria si se muestran técnicas)

`MITRE_ATTACK_ATTRIBUTION` en `src/config.py`, textual:

> MITRE ATT&CK® data reproduced and distributed with the permission of The MITRE Corporation. © The MITRE Corporation.

Va **solo** si la lista no viene vacía: si no se muestran datos de ATT&CK, la
nota no corresponde.
