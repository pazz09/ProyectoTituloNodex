/**
 * Gráfico de barras: geometría y SVG.
 *
 * La geometría es una función pura, y la pantalla y la exportación salen del
 * mismo cálculo. Estas pruebas fijan las dos reglas de honestidad del dibujo:
 *
 *  - un valor `null` NO dibuja barra (dibujar una de altura cero diría «el
 *    sistema obtuvo 0», que es distinto de «no hay dato»);
 *  - el eje de las proporciones va siempre de 0 a 1.
 */
import { describe, expect, it } from 'vitest'

import {
  PALETAS,
  geometriaBarras,
  svgDeBarras,
  techoRedondo,
  type ModeloBarras,
} from '@/lib/graficos'

const modelo: ModeloBarras = {
  titulo: 'Detección',
  series: [{ nombre: 'Precisión' }, { nombre: 'Exhaustividad' }],
  grupos: [
    { etiqueta: 'uwf · NODEX', valores: [0.5, 0] },
    { etiqueta: 'uwf · Baseline', valores: [null, 0.25] },
  ],
}

describe('techoRedondo', () => {
  it('redondea hacia arriba a un valor legible', () => {
    expect(techoRedondo(8)).toBe(10)
    expect(techoRedondo(17)).toBe(20)
    expect(techoRedondo(0.7)).toBeCloseTo(1)
    expect(techoRedondo(120)).toBe(200)
  })

  it('cubre siempre el máximo y nunca da cero', () => {
    for (const v of [0.01, 1, 3.3, 99, 1234]) expect(techoRedondo(v)).toBeGreaterThanOrEqual(v)
    expect(techoRedondo(0)).toBe(1)
    expect(techoRedondo(-5)).toBe(1)
    expect(techoRedondo(Number.NaN)).toBe(1)
  })
})

describe('geometriaBarras', () => {
  const g = geometriaBarras(modelo, 'impresion')

  it('un null no dibuja barra: deja una marca de sin dato', () => {
    expect(g.sinDato).toHaveLength(1)
    expect(g.sinDato[0]).toMatchObject({ grupo: 1, serie: 0 })
    expect(g.barras.find((b) => b.grupo === 1 && b.serie === 0)).toBeUndefined()
  })

  it('un cero SÍ dibuja barra, de altura cero, distinta de un null', () => {
    const cero = g.barras.find((b) => b.grupo === 0 && b.serie === 1)
    expect(cero).toBeDefined()
    expect(cero!.alto).toBe(0)
    expect(cero!.texto).toBe('0,00')
  })

  it('el eje de proporciones es fijo, de 0 a 1', () => {
    expect(g.techo).toBe(1)
    expect(g.guias[0].texto).toBe('0,00')
    expect(g.guias[g.guias.length - 1].texto).toBe('1,00')
  })

  it('la altura de las barras es proporcional al valor', () => {
    const media = g.barras.find((b) => b.valor === 0.5)!
    const cuarto = g.barras.find((b) => b.valor === 0.25)!
    expect(media.alto).toBeCloseTo(cuarto.alto * 2, 5)
  })

  it('todas las barras caen dentro del área de dibujo', () => {
    for (const b of g.barras) {
      expect(b.x).toBeGreaterThanOrEqual(g.area.x0)
      expect(b.x + b.ancho).toBeLessThanOrEqual(g.area.x1)
      expect(b.y).toBeGreaterThanOrEqual(g.area.y0 - 0.001)
      expect(b.y + b.alto).toBeCloseTo(g.area.y1, 5)
    }
  })

  it('un valor fuera de rango no se sale del gráfico', () => {
    const fuera = geometriaBarras(
      { ...modelo, grupos: [{ etiqueta: 'x', valores: [7, -3] }] },
      'impresion',
    )
    for (const b of fuera.barras) {
      expect(b.y).toBeGreaterThanOrEqual(fuera.area.y0 - 0.001)
      expect(b.alto).toBeGreaterThanOrEqual(0)
    }
  })

  it('el eje numérico se ajusta al máximo pero respeta un techo fijo', () => {
    const num = geometriaBarras(
      { titulo: 't', series: [{ nombre: 's' }], formato: 'numero',
        grupos: [{ etiqueta: 'a', valores: [8] }] },
      'impresion',
    )
    expect(num.techo).toBe(10)
    const fijo = geometriaBarras(
      { titulo: 't', series: [{ nombre: 's' }], formato: 'numero', techoFijo: 3,
        grupos: [{ etiqueta: 'a', valores: [2] }] },
      'impresion',
    )
    expect(fijo.techo).toBe(3)
  })

  it('las etiquetas de grupo se parten en líneas por « · »', () => {
    expect(g.etiquetasGrupo[0].lineas).toEqual(['uwf', 'NODEX'])
  })

  it('la leyenda tiene una entrada por serie, con colores distintos', () => {
    expect(g.leyenda.map((l) => l.nombre)).toEqual(['Precisión', 'Exhaustividad'])
    expect(new Set(g.leyenda.map((l) => l.color)).size).toBe(2)
  })

  it('sin grupos no falla', () => {
    expect(() => geometriaBarras({ titulo: 't', series: [], grupos: [] })).not.toThrow()
  })
})

describe('svgDeBarras', () => {
  const impresion = svgDeBarras(modelo, 'impresion')
  const pantalla = svgDeBarras(modelo, 'pantalla')

  it('es un SVG autónomo y bien formado', () => {
    for (const svg of [impresion, pantalla]) {
      expect(svg.startsWith('<svg xmlns="http://www.w3.org/2000/svg"')).toBe(true)
      expect(svg.endsWith('</svg>')).toBe(true)
      expect(new DOMParser().parseFromString(svg, 'image/svg+xml')
        .querySelector('parsererror')).toBeNull()
    }
  })

  it('no depende de variables CSS: un SVG suelto no las resuelve', () => {
    expect(impresion).not.toContain('var(--')
    expect(pantalla).not.toContain('var(--')
  })

  it('para papel lleva fondo blanco; en pantalla es transparente', () => {
    expect(impresion).toContain(`fill="${PALETAS.impresion.fondo}"`)
    expect(PALETAS.pantalla.fondo).toBeNull()
  })

  it('marca n/d donde hay null y no lo marca donde hay un cero', () => {
    expect(impresion.match(/>n\/d</g)).toHaveLength(1)
  })

  it('escapa el texto: un título con símbolos no rompe el documento', () => {
    const peligroso = svgDeBarras({ ...modelo, titulo: 'A<B & "C"' }, 'impresion')
    expect(peligroso).toContain('A&lt;B &amp; &quot;C&quot;')
    expect(new DOMParser().parseFromString(peligroso, 'image/svg+xml')
      .querySelector('parsererror')).toBeNull()
  })

  it('lleva título y descripción accesibles', () => {
    const conDesc = svgDeBarras({ ...modelo, descripcion: 'Texto largo' }, 'impresion')
    expect(conDesc).toContain('<title>Detección</title>')
    expect(conDesc).toContain('<desc>Texto largo</desc>')
    expect(conDesc).toContain('role="img"')
  })

  it('incluye la unidad en el título cuando se indica', () => {
    const conUnidad = svgDeBarras({ ...modelo, titulo: 'Tiempo', unidad: 's' }, 'impresion')
    expect(conUnidad).toContain('Tiempo (s)')
  })
})
