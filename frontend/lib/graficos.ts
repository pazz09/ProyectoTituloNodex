/**
 * Gráfico de barras agrupadas, sin librería.
 *
 * El proyecto ya dibuja sus gráficos a mano en SVG (`components/area-chart.tsx`)
 * y el prototipo no suma dependencias de gráficos, así que este sigue el
 * mismo criterio. Hay una ventaja práctica: como la geometría es una función
 * pura, **la pantalla y la exportación salen del mismo cálculo**. Lo que se
 * descarga como SVG o PNG es lo que se ve, no una segunda maqueta que pueda
 * divergir.
 *
 * Reglas de honestidad que condicionan el dibujo:
 *
 *  - `null` NO es cero. Un valor ausente no dibuja barra: deja una marca
 *    `n/d` sobre la base. Dibujar una barra de altura cero diría "el sistema
 *    obtuvo 0", que es una afirmación distinta de "no hay dato".
 *  - El eje de las proporciones va siempre de 0 a 1. Un eje que se ajusta al
 *    máximo exagera diferencias pequeñas entre arquitecturas.
 *  - Los colores de la exportación son para papel (fondo blanco): un SVG
 *    suelto no resuelve las variables CSS del tema oscuro de la interfaz.
 */

import { formatoNumero } from '@/lib/resultados'

export type TemaGrafico = 'pantalla' | 'impresion'

export type SerieBarras = { nombre: string }

export type GrupoBarras = {
  /** Las líneas se separan con ` · `: "bgl · NODEX" se dibuja en dos líneas. */
  etiqueta: string
  /** Un valor por serie, en el mismo orden. `null` = sin dato. */
  valores: (number | null)[]
}

export type ModeloBarras = {
  titulo: string
  descripcion?: string
  series: SerieBarras[]
  grupos: GrupoBarras[]
  /** `proporcion`: eje fijo 0–1. `numero`: eje hasta un techo redondeado. */
  formato?: 'proporcion' | 'numero'
  /** Unidad que se agrega al título del eje, por ejemplo `s` o `tokens`. */
  unidad?: string
  /** Techo fijo del eje (por ejemplo 3 para la rúbrica de 0 a 3). */
  techoFijo?: number
}

export const PALETAS: Record<
  TemaGrafico,
  { fondo: string | null; texto: string; textoFuerte: string; guia: string; series: string[] }
> = {
  pantalla: {
    fondo: null, // transparente: se apoya sobre el panel oscuro
    texto: '#8e8e95',
    textoFuerte: '#f2f2f4',
    guia: '#2a2a30',
    series: ['#4f7cf7', '#4fb87a', '#e08a3c', '#a78bfa', '#e0574f'],
  },
  impresion: {
    fondo: '#ffffff',
    texto: '#444444',
    textoFuerte: '#111111',
    guia: '#d9d9d9',
    series: ['#2f5fd6', '#2e8f5b', '#c06a1b', '#7c5cd6', '#c0392b'],
  },
}

const ANCHO = 760
const MARGEN = { arriba: 58, derecha: 16, izquierda: 52 }
const ALTO_AREA = 190
const LINEA = 13

export type Barra = {
  x: number
  y: number
  ancho: number
  alto: number
  color: string
  valor: number
  serie: number
  grupo: number
  texto: string
}

export type MarcaSinDato = { x: number; y: number; serie: number; grupo: number }

export type GeometriaBarras = {
  ancho: number
  alto: number
  area: { x0: number; x1: number; y0: number; y1: number }
  techo: number
  guias: { y: number; texto: string }[]
  barras: Barra[]
  sinDato: MarcaSinDato[]
  etiquetasGrupo: { x: number; y: number; lineas: string[] }[]
  leyenda: { x: number; y: number; nombre: string; color: string }[]
}

/** Techo "redondo" para un eje numérico: 1, 2, 2.5, 5 o 10 por una potencia de 10. */
export function techoRedondo(maximo: number): number {
  if (!Number.isFinite(maximo) || maximo <= 0) return 1
  const objetivo = maximo * 1.05
  const potencia = Math.pow(10, Math.floor(Math.log10(objetivo)))
  for (const paso of [1, 2, 2.5, 5, 10]) {
    if (paso * potencia >= objetivo) return paso * potencia
  }
  return 10 * potencia
}

function lineasDe(etiqueta: string): string[] {
  const partes = etiqueta.split(' · ').map((p) => p.trim()).filter(Boolean)
  return partes.length ? partes.slice(0, 3) : [etiqueta]
}

export function geometriaBarras(modelo: ModeloBarras, tema: TemaGrafico = 'pantalla'): GeometriaBarras {
  const paleta = PALETAS[tema]
  const formato = modelo.formato ?? 'proporcion'
  const nSeries = Math.max(modelo.series.length, 1)
  const nGrupos = Math.max(modelo.grupos.length, 1)

  const definidos = modelo.grupos.flatMap((g) => g.valores).filter((v): v is number => v !== null)
  const techo =
    modelo.techoFijo ?? (formato === 'proporcion' ? 1 : techoRedondo(Math.max(0, ...definidos)))

  const lineasMax = Math.max(1, ...modelo.grupos.map((g) => lineasDe(g.etiqueta).length))
  const alto = MARGEN.arriba + ALTO_AREA + 14 + lineasMax * LINEA + 10
  const x0 = MARGEN.izquierda
  const x1 = ANCHO - MARGEN.derecha
  const y0 = MARGEN.arriba
  const y1 = MARGEN.arriba + ALTO_AREA
  const anchoGrupo = (x1 - x0) / nGrupos

  // Dentro de cada grupo: las barras ocupan el 70% del ancho y el resto es aire.
  const anchoBarra = Math.min(34, (anchoGrupo * 0.7) / nSeries)
  const anchoBloque = anchoBarra * nSeries

  const escala = (v: number) => y1 - (Math.min(Math.max(v, 0), techo) / techo) * ALTO_AREA

  const guias = [0, 0.25, 0.5, 0.75, 1].map((f) => ({
    y: escala(techo * f),
    texto: formato === 'proporcion' ? formatoNumero(techo * f, 2) : formatoNumero(techo * f, techo >= 10 ? 0 : 1),
  }))

  const barras: Barra[] = []
  const sinDato: MarcaSinDato[] = []
  modelo.grupos.forEach((grupo, g) => {
    const inicio = x0 + g * anchoGrupo + (anchoGrupo - anchoBloque) / 2
    grupo.valores.forEach((valor, s) => {
      const x = inicio + s * anchoBarra
      if (valor === null || valor === undefined || !Number.isFinite(valor)) {
        sinDato.push({ x: x + anchoBarra / 2, y: y1, serie: s, grupo: g })
        return
      }
      const y = escala(valor)
      barras.push({
        x,
        y,
        ancho: Math.max(anchoBarra - 3, 2),
        alto: y1 - y,
        color: paleta.series[s % paleta.series.length],
        valor,
        serie: s,
        grupo: g,
        texto: formato === 'proporcion' ? formatoNumero(valor, 2) : formatoNumero(valor, valor >= 100 ? 0 : 1),
      })
    })
  })

  const etiquetasGrupo = modelo.grupos.map((grupo, g) => ({
    x: x0 + g * anchoGrupo + anchoGrupo / 2,
    y: y1 + 18,
    lineas: lineasDe(grupo.etiqueta),
  }))

  // Leyenda en una fila bajo el título.
  let cursor = x0
  const leyenda = modelo.series.map((serie, s) => {
    const item = { x: cursor, y: 40, nombre: serie.nombre, color: paleta.series[s % paleta.series.length] }
    cursor += 22 + serie.nombre.length * 6.6
    return item
  })

  return { ancho: ANCHO, alto, area: { x0, x1, y0, y1 }, techo, guias, barras, sinDato, etiquetasGrupo, leyenda }
}

function xml(texto: string): string {
  return texto
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

/** SVG autónomo (sin CSS externo ni variables), apto para descargar. */
export function svgDeBarras(modelo: ModeloBarras, tema: TemaGrafico = 'impresion'): string {
  const g = geometriaBarras(modelo, tema)
  const paleta = PALETAS[tema]
  const partes: string[] = []

  partes.push(
    `<svg xmlns="http://www.w3.org/2000/svg" width="${g.ancho}" height="${g.alto}" ` +
      `viewBox="0 0 ${g.ancho} ${g.alto}" role="img" aria-label="${xml(modelo.titulo)}" ` +
      `font-family="Inter, 'Segoe UI', system-ui, sans-serif">`,
  )
  partes.push(`<title>${xml(modelo.titulo)}</title>`)
  if (modelo.descripcion) partes.push(`<desc>${xml(modelo.descripcion)}</desc>`)
  if (paleta.fondo) partes.push(`<rect width="${g.ancho}" height="${g.alto}" fill="${paleta.fondo}"/>`)

  partes.push(
    `<text x="${g.area.x0}" y="22" font-size="14" font-weight="500" fill="${paleta.textoFuerte}">${xml(
      modelo.titulo + (modelo.unidad ? ` (${modelo.unidad})` : ''),
    )}</text>`,
  )

  for (const item of g.leyenda) {
    partes.push(
      `<rect x="${item.x}" y="${item.y - 9}" width="11" height="11" rx="2" fill="${item.color}"/>` +
        `<text x="${item.x + 16}" y="${item.y}" font-size="11" fill="${paleta.texto}">${xml(item.nombre)}</text>`,
    )
  }

  for (const guia of g.guias) {
    partes.push(
      `<line x1="${g.area.x0}" x2="${g.area.x1}" y1="${guia.y}" y2="${guia.y}" stroke="${paleta.guia}" stroke-width="1"/>` +
        `<text x="${g.area.x0 - 8}" y="${guia.y + 4}" font-size="10" text-anchor="end" fill="${paleta.texto}">${xml(guia.texto)}</text>`,
    )
  }

  for (const b of g.barras) {
    partes.push(
      `<rect x="${b.x.toFixed(2)}" y="${b.y.toFixed(2)}" width="${b.ancho.toFixed(2)}" height="${b.alto.toFixed(2)}" rx="2" fill="${b.color}"/>` +
        `<text x="${(b.x + b.ancho / 2).toFixed(2)}" y="${(b.y - 4).toFixed(2)}" font-size="9.5" text-anchor="middle" fill="${paleta.textoFuerte}">${xml(b.texto)}</text>`,
    )
  }

  // `null` no dibuja barra: deja una marca sobre la base.
  for (const m of g.sinDato) {
    partes.push(
      `<text x="${m.x.toFixed(2)}" y="${(m.y - 4).toFixed(2)}" font-size="9" text-anchor="middle" fill="${paleta.texto}">n/d</text>`,
    )
  }

  for (const e of g.etiquetasGrupo) {
    e.lineas.forEach((linea, i) => {
      partes.push(
        `<text x="${e.x.toFixed(2)}" y="${e.y + i * LINEA}" font-size="10.5" text-anchor="middle" fill="${paleta.texto}">${xml(linea)}</text>`,
      )
    })
  }

  partes.push('</svg>')
  return partes.join('')
}
