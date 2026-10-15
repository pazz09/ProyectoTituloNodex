/**
 * Cliente y utilidades de la vista "Resultados".
 *
 * Los tipos reflejan EXACTAMENTE lo que escribe el consolidador
 * (`src/experimentation/consolidacion.py`, esquema `resultados-v1`). La
 * vista no calcula métricas: muestra lo que el consolidador ya calculó con
 * los evaluadores del proyecto, y arma el CSV a partir de las mismas filas
 * que muestra en pantalla, para que lo descargado y lo visto no puedan
 * diferir.
 *
 * Regla que atraviesa todo el archivo: **`null` significa "no aplica o no
 * hay dato", nunca cero**. Un 0 se promedia y se dibuja como barra; un
 * `null` no. Por eso el formato distingue `—` de `0,000`.
 */

import { API_BASE } from '@/lib/api'

export const ESQUEMA_RESULTADOS = 'resultados-v1'

export type ValorCelda = string | number | boolean | null

export type ColumnaTabla = {
  clave: string
  etiqueta: string
  /** `proporcion` se muestra con 3 decimales; `entero` sin decimales. */
  tipo?: 'texto' | 'proporcion' | 'numero' | 'entero'
}

export type FilaTabla = Record<string, ValorCelda>

export type TablaResultados = {
  titulo: string
  /** Sección del informe a la que alimenta (11.1 a 11.7). */
  seccion: string
  descripcion?: string
  columnas: ColumnaTabla[]
  filas: FilaTabla[]
}

export type Advertencia = {
  codigo: string
  severidad: 'alta' | 'media' | 'info'
  mensaje: string
  n: number
}

export type CorridaFallida = {
  run_id: string
  estado: string | null
  error: string | null
}

export type CorridaConTokensParciales = {
  run_id: string
  n_llamadas: number
  n_con_tokens: number
  n_llamadas_fallidas: number
  tokens_entrada_parcial: number | null
  tokens_salida_parcial: number | null
  tokens_razonamiento_parcial: number | null
}

export type Integridad = {
  corridas_esperadas: number
  corridas_presentes: number
  corridas_completas: number
  corridas_ausentes: string[]
  corridas_fallidas: CorridaFallida[]
  corridas_con_fallback: string[]
  /** `false` cuando no hay configuración congelada: no se puede saber. */
  fallback_determinable: boolean
  modelo_principal: string | null
  corridas_con_telemetria_previa_a_d11: number
  corridas_sin_tokens: number
  /** Corridas completas con total de tokens None pero con una suma parcial (un piso). */
  corridas_con_tokens_parciales?: CorridaConTokensParciales[]
  /** Corridas completas que no informaron tokens de razonamiento (no son 0). */
  corridas_sin_razonamiento?: number
  /** Corridas completas sin la versión de modelo que devolvió la API. */
  corridas_sin_version_de_modelo?: number
  advertencias: Advertencia[]
}

export type ResumenResultados = {
  esquema: string
  /** `true` solo en fixtures de prueba. Nunca en resultados reales. */
  datos_ficticios: boolean
  /** Resultados de DEPURACIÓN (desarrollo/piloto): no son reportables. */
  depuracion?: boolean
  /** `false` si son ficticios o de depuración. */
  reportable?: boolean
  config_version: string
  consolidacion: string
  generado_utc: string
  protocolo_version: string
  subconjunto: string
  particion: string
  arquitecturas: string[]
  integridad: Integridad
  tablas: Record<string, TablaResultados>
}

export type ConfigResultados = {
  config_version: string
  consolidaciones: string[]
  ultima: string | null
}

export type ListaResultados = {
  configuraciones: ConfigResultados[]
}

export type ReporteCorrida = {
  run_id: string
  case_id: string
  dataset: string
  arquitectura: string
  repeticion: number
  estado_ejecucion: string | null
  clasificacion: string | null
  motivo_no_evaluable: string | null
  /** Texto del reporte tal como lo produjo el sistema; `null` si no hay. */
  reporte: string | null
}

// --- formato ---------------------------------------------------------------

export const SIN_DATO = '—'

/** `null`/`undefined` → `—`; un cero real se muestra como `0,000`. */
export function formatoNumero(valor: ValorCelda | undefined, decimales = 3): string {
  if (valor === null || valor === undefined) return SIN_DATO
  if (typeof valor === 'boolean') return valor ? 'sí' : 'no'
  if (typeof valor === 'string') return valor === '' ? SIN_DATO : valor
  if (!Number.isFinite(valor)) return SIN_DATO
  return valor.toFixed(decimales).replace('.', ',')
}

export function formatoCelda(valor: ValorCelda | undefined, tipo: ColumnaTabla['tipo']): string {
  if (tipo === 'entero') return formatoNumero(valor, 0)
  if (tipo === 'numero') return formatoNumero(valor, 2)
  return formatoNumero(valor, 3)
}

export const NOMBRE_ARQUITECTURA: Record<string, string> = {
  nodex_multiagente: 'NODEX',
  baseline_reglas: 'Baseline de reglas',
  gemini_externo: 'Gemini directo',
  agente_unico: 'Agente único',
}

export function nombreArquitectura(clave: string): string {
  return NOMBRE_ARQUITECTURA[clave] ?? clave
}

// --- CSV -------------------------------------------------------------------

function escaparCsv(valor: ValorCelda | undefined): string {
  // `null` → celda vacía. Nunca "0": una celda vacía es "no hay dato".
  if (valor === null || valor === undefined) return ''
  const texto = typeof valor === 'boolean' ? (valor ? 'true' : 'false') : String(valor)
  return /[",\r\n]/.test(texto) ? `"${texto.replace(/"/g, '""')}"` : texto
}

/**
 * CSV de una tabla, con las mismas filas y columnas que se ven.
 *
 * Lleva BOM UTF-8 porque Excel, sin él, abre el archivo como Windows-1252 y
 * rompe las tildes. Los números van con punto decimal (formato de datos, no
 * de lectura).
 */
export function tablaACsv(tabla: TablaResultados): string {
  const cabecera = tabla.columnas.map((c) => escaparCsv(c.clave)).join(',')
  const cuerpo = tabla.filas.map((fila) =>
    tabla.columnas.map((c) => escaparCsv(fila[c.clave])).join(','),
  )
  return '\uFEFF' + [cabecera, ...cuerpo].join('\r\n') + '\r\n'
}

// --- descargas (solo navegador) -------------------------------------------

export function descargarBlob(nombre: string, blob: Blob) {
  const url = URL.createObjectURL(blob)
  const enlace = document.createElement('a')
  enlace.href = url
  enlace.download = nombre
  enlace.click()
  URL.revokeObjectURL(url)
}

export function descargarTexto(nombre: string, texto: string, tipo = 'text/plain;charset=utf-8') {
  descargarBlob(nombre, new Blob([texto], { type: tipo }))
}

/** Nombre de archivo seguro: sin espacios ni caracteres de ruta. */
export function nombreArchivo(...partes: string[]): string {
  return partes
    .join('_')
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/[^A-Za-z0-9._-]+/g, '_')
    .replace(/^_+|_+$/g, '')
}

/** Rasteriza un SVG (texto) a PNG, a 2x para que se lea bien en un informe. */
export async function svgAPng(svg: string, ancho: number, alto: number, escala = 2): Promise<Blob> {
  const url = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`
  const imagen = new Image()
  await new Promise<void>((resolver, rechazar) => {
    imagen.onload = () => resolver()
    imagen.onerror = () => rechazar(new Error('No se pudo rasterizar el gráfico.'))
    imagen.src = url
  })
  const lienzo = document.createElement('canvas')
  lienzo.width = ancho * escala
  lienzo.height = alto * escala
  const ctx = lienzo.getContext('2d')
  if (!ctx) throw new Error('El navegador no permite dibujar el gráfico.')
  ctx.scale(escala, escala)
  ctx.drawImage(imagen, 0, 0, ancho, alto)
  return new Promise<Blob>((resolver, rechazar) =>
    lienzo.toBlob(
      (b) => (b ? resolver(b) : rechazar(new Error('No se pudo generar el PNG.'))),
      'image/png',
    ),
  )
}

// --- API ---------------------------------------------------------------------

async function detalle(r: Response, porDefecto: string) {
  try {
    const cuerpo = await r.json()
    if (typeof cuerpo?.detail === 'string') return cuerpo.detail
  } catch {
    // el backend no siempre responde JSON
  }
  return porDefecto
}

export async function listarResultados(): Promise<ListaResultados> {
  const r = await fetch(`${API_BASE}/api/resultados`)
  if (!r.ok) throw new Error(await detalle(r, `No se pudo leer la lista de resultados (HTTP ${r.status}).`))
  return r.json()
}

export async function obtenerResultados(
  configVersion: string,
  consolidacion?: string,
): Promise<ResumenResultados> {
  const qs = consolidacion ? `?consolidacion=${encodeURIComponent(consolidacion)}` : ''
  const r = await fetch(`${API_BASE}/api/resultados/${encodeURIComponent(configVersion)}${qs}`)
  if (!r.ok) throw new Error(await detalle(r, `No se pudieron leer los resultados (HTTP ${r.status}).`))
  return r.json()
}

export async function obtenerReporteCorrida(
  configVersion: string,
  runId: string,
): Promise<ReporteCorrida> {
  const r = await fetch(
    `${API_BASE}/api/resultados/${encodeURIComponent(configVersion)}/reportes/${encodeURIComponent(runId)}`,
  )
  if (!r.ok) throw new Error(await detalle(r, `No se pudo leer el reporte (HTTP ${r.status}).`))
  return r.json()
}
