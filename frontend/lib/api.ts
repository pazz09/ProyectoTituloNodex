/**
 * Cliente de la API de NODEX.
 *
 * Los tipos siguen los campos REALES de la API, medidos contra respuestas
 * reales -- ver `docs/contrato_api_frontend.md`. Dos que sorprenden y
 * conviene no olvidar:
 *
 *  - `tecnicas_mitre` no es `{technique_id, nombre}`: cada elemento trae
 *    `texto`, `meta` y `similitud`.
 *  - el evento `final` del SSE no trae `job_id` ni los datos del archivo, así
 *    que la vista de informe se alimenta con la fila del historial (el mismo
 *    shape que usa el detalle) en vez de con el evento.
 */

export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE ?? 'http://127.0.0.1:8000'

/** Límite real del backend: `LOG_MAX_FILE_BYTES` en `src/config.py`. */
export const MAX_BYTES = 52_428_800

export type TecnicaMitre = {
  texto: string
  similitud: number
  meta: {
    technique_id: string
    name: string
    tactics: string // separado por comas, no es lista
    url: string
    is_subtechnique: boolean
  }
}

export type ReputacionIp = {
  fuente?: string
  ip?: string
  score?: number | null
  categoria?: 'malicioso' | 'sospechoso' | 'limpio' | 'desconocido'
  pais?: string | null
}

export type Entidad = {
  ip: string
  n_eventos: number
  intentos_fallidos: number
  usuarios_objetivo: string[]
  servicios: string[]
  n_como_origen: number
  n_como_destino: number
}

/** Una entrada de la secuencia temporal del incidente. */
export type EntradaCronologia = {
  n: number
  timestamp: string | null
  servicio: string | null
  evento: string | null
  mensaje: string
  ip?: string
  ip_destino?: string
  usuario?: string
  codigo_respuesta?: string
}

export type ResumenLote = {
  formato_detectado?: string
  total_lineas?: number
  n_ips_distintas?: number
  servicios?: Record<string, number>
  eventos?: Record<string, number>
  ventana_temporal?: { inicio: string | null; fin: string | null }
  reputacion_ips?: Record<string, ReputacionIp>
  // Elementos del §8.7.1 del informe, agregados el 10-sep-2026.
  usuarios?: Record<string, number>
  n_usuarios_distintos?: number
  codigos_respuesta?: Record<string, number>
  entidades?: Entidad[]
  cronologia?: EntradaCronologia[]
  cronologia_omitidos?: number
}

export type ReporteFinal = {
  diagnostico?: string
  confianza?: number
  hay_incidente?: boolean
  hay_anomalia?: boolean
  evaluacion_auditor?: string
  tecnicas_mitre?: TecnicaMitre[]
  comandos_mitigacion?: string[]
  comandos_validos?: boolean
  cves_encontrados?: unknown[]
  intentos_correccion?: number
  requiere_revision_humana?: boolean
  firma?: string
  /** Precedentes que el RAG recuperó y que el triage tuvo a la vista. */
  precedentes?: {
    clasificacion: string | null
    confianza: number | null
    host: string | null
    similitud: number | null
  }[]
  n_precedentes?: number
  /** NODEX final, Fase B: diagnóstico anterior a la corrección del auditor (B2). */
  diagnostico_inicial?: string
  correcciones_auditor?: number
  historial_correcciones?: { correccion: number; clase_anterior: string | null; clase_nueva: string | null }[]
  /** Auditor reforzado: evaluación de cada grupo con señal antes del veredicto. */
  evaluacion_grupos?: {
    group_id: string
    explicacion_benigna?: string
    explicacion_maliciosa?: string
    /** Patrón de la lista de verificación MITRE que calza, o `ninguno`. */
    patron_lista?: string
  }[]
  veredicto_consolidado?: string | null
  classification_detallada?: string | null
}

/** Fila del historial: el shape que consume la vista de informe. */
export type Corrida = {
  job_id: string
  timestamp: string
  archivo_origen: string | null
  formato_detectado: string | null
  total_lineas: number | null
  motor_preprocesamiento: string | null
  diagnostico: string | null
  confianza: number | null
  hay_anomalia: boolean | null
  hay_incidente: boolean | null
  requiere_revision_humana: boolean | null
  n_comandos_mitigacion: number | null
  evaluacion_auditor: string | null
  tecnicas_mitre: TecnicaMitre[]
  estado: 'completo' | 'error' | string
  error_mensaje: string | null
  feedback_correcto: boolean | null
  feedback_comentario: string | null
  feedback_timestamp: string | null
  resumen_json: ResumenLote
  reporte_json: ReporteFinal
}

export type EventoSse =
  | { tipo: 'inicio'; resumen: ResumenLote; preprocesamiento: Record<string, unknown>; advertencias: unknown[] }
  | { tipo: 'nodo'; nombre: string; detalle: Record<string, unknown> }
  | { tipo: 'error'; mensaje: string }
  | { tipo: 'final'; reporte: ReporteFinal }
  | {
      tipo: 'registro_manual'
      registrado: boolean
      motivo: string
      case_id?: string
      repeticion?: number
      config_version?: string
    }

async function detalleDelError(r: Response, porDefecto: string) {
  try {
    const cuerpo = await r.json()
    if (typeof cuerpo?.detail === 'string') return cuerpo.detail
  } catch {
    // el backend no siempre responde JSON (p. ej. un 500 de uvicorn)
  }
  return porDefecto
}

/** Sube el archivo y devuelve el `job_id` con el que se abre el stream. */
export async function subirArchivo(archivo: File): Promise<{ job_id: string; nombre_archivo: string }> {
  const cuerpo = new FormData()
  cuerpo.append('archivo', archivo) // el backend espera exactamente este campo

  let r: Response
  try {
    r = await fetch(`${API_BASE}/api/analizar`, { method: 'POST', body: cuerpo })
  } catch {
    throw new Error(
      `No se pudo contactar al servidor de análisis en ${API_BASE}. ` +
        'Verificá que esté corriendo (uvicorn src.api.main:app).',
    )
  }
  if (!r.ok) {
    throw new Error(await detalleDelError(r, `El servidor rechazó el archivo (HTTP ${r.status}).`))
  }
  return r.json()
}

export function urlDelStream(jobId: string) {
  return `${API_BASE}/api/stream/${jobId}`
}

/**
 * Fila del historial de una corrida.
 *
 * `reintentos` existe por una carrera acotada: la fila se escribe en el
 * `finally` del generador SSE, es decir justo DESPUÉS de emitir el evento
 * `final`. Pedirla de inmediato puede dar 404 por unos milisegundos.
 */
export async function obtenerCorrida(jobId: string, reintentos = 4): Promise<Corrida> {
  for (let intento = 0; ; intento++) {
    const r = await fetch(`${API_BASE}/api/historial/${jobId}`)
    if (r.ok) return r.json()
    if (r.status !== 404 || intento >= reintentos) {
      throw new Error(await detalleDelError(r, `No se pudo leer la corrida (HTTP ${r.status}).`))
    }
    await new Promise((listo) => setTimeout(listo, 250))
  }
}

export async function listarHistorial(limit: number, offset: number): Promise<{
  total: number
  limit: number
  offset: number
  corridas: Corrida[]
}> {
  const r = await fetch(`${API_BASE}/api/historial?limit=${limit}&offset=${offset}`)
  if (!r.ok) throw new Error(await detalleDelError(r, `No se pudo leer el historial (HTTP ${r.status}).`))
  return r.json()
}

/** Descarga el informe en PDF que arma el backend. */
export async function descargarInforme(jobId: string) {
  const r = await fetch(`${API_BASE}/api/historial/${jobId}/pdf`)
  if (!r.ok) throw new Error(await detalleDelError(r, `El informe no está disponible (HTTP ${r.status}).`))

  // El nombre viene en Content-Disposition; el backend expone esa cabecera
  // por CORS para poder leerla desde acá.
  const disposicion = r.headers.get('content-disposition') ?? ''
  const nombre = /filename=([^;]+)/i.exec(disposicion)?.[1]?.trim() ?? `informe_${jobId}.pdf`

  const url = URL.createObjectURL(await r.blob())
  const enlace = document.createElement('a')
  enlace.href = url
  enlace.download = nombre
  enlace.click()
  URL.revokeObjectURL(url)
}

export type RespuestaFeedback = {
  guardado: boolean
  memoria: {
    guardado_en: string
    promovido_a_attack_patterns: boolean
    error_registrado: boolean
  } | null
  detalle?: string
}

export async function enviarFeedback(
  jobId: string,
  correcto: boolean,
  comentario: string | null,
): Promise<RespuestaFeedback> {
  const r = await fetch(`${API_BASE}/api/feedback/${jobId}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ correcto, comentario }),
  })
  if (!r.ok) throw new Error(await detalleDelError(r, `No se pudo guardar el veredicto (HTTP ${r.status}).`))
  return r.json()
}
