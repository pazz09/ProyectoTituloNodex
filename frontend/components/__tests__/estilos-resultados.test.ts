/**
 * Contrato de estilos de la vista «Resultados».
 *
 * jsdom no carga el CSS, así que el diseño no se puede probar renderizando. Estas pruebas leen
 * `app/globals.css` y fijan las reglas que corrigen tres defectos vistos en el navegador real
 * (15-oct-2026): la sexta tarjeta de integridad caía a una segunda fila, las tablas eran más
 * anchas que la pantalla sin pistas de desplazamiento, y una columna de texto largo estiraba
 * las filas. La verificación visual (Chrome real) está en `docs/experimentacion/`.
 */
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

const css = readFileSync(join(process.cwd(), 'app', 'globals.css'), 'utf-8')

function regla(selector: string): string {
  const i = css.lastIndexOf('\n' + selector + ' {')
  expect(i, `no se encontró la regla ${selector}`).toBeGreaterThan(-1)
  return css.slice(i, css.indexOf('}', i))
}

describe('tarjetas de integridad', () => {
  it('se reparten en una sola fila de hasta seis, no de cinco', () => {
    const r = regla('#integridad .kpis')
    expect(r).toContain('auto-fit')
    expect(r).toContain('100% / 6')
  })

  it('con un mínimo por tarjeta para que no se aplasten en pantallas angostas', () => {
    expect(regla('#integridad .kpis')).toMatch(/max\(120px/)
  })

  it('el cambio no afecta a las tarjetas de las otras vistas', () => {
    // la regla base `.kpis` conserva su ancho mínimo original
    expect(regla('.kpis')).toContain('minmax(170px, 1fr)')
  })
})

describe('tablas anchas', () => {
  it('los encabezados bajan de línea en los espacios, sin cortar palabras', () => {
    const r = regla('.bloque-tabla .table th')
    expect(r).toContain('white-space: normal')
    expect(r).toContain('overflow-wrap: normal')
    expect(r).toContain('word-break: normal')
  })

  it('ninguna regla de tablas permite cortar en cualquier letra (dejaba columnas de un carácter)', () => {
    // Defecto real visto en Chrome el 15-oct-2026: con `overflow-wrap: anywhere` las columnas se
    // encogían al mínimo y los encabezados y «gemini-3.8-flash» salían en vertical.
    const sinComentarios = css.replace(/\/\*[\s\S]*?\*\//g, '')
    const reglasDeTablas = sinComentarios
      .split('}')
      .filter((b) => /\.bloque-tabla|\.table/.test(b.split('{')[0] ?? ''))
      .join('}')
    expect(reglasDeTablas).not.toMatch(/overflow-wrap:\s*anywhere/)
    expect(reglasDeTablas).not.toMatch(/word-break:\s*break-all/)
  })

  it('los valores de texto de las tablas no se parten, salvo la arquitectura', () => {
    expect(regla('.bloque-tabla .table td.mono')).toContain('white-space: nowrap')
    expect(regla('.bloque-tabla .table.tabla-ancla td:nth-child(2)')).toContain('white-space: normal')
  })

  it('el desplazamiento horizontal tiene sombras laterales como pista', () => {
    const r = regla('.bloque-tabla .table-scroll')
    expect(r).toContain('radial-gradient')
    expect(r).toContain('background-attachment: local, local, scroll, scroll')
  })

  it('dataset y arquitectura quedan fijas a la izquierda al desplazarse', () => {
    expect(css).toContain('.table.tabla-ancla th:nth-child(-n + 2)')
    expect(css).toMatch(/\.table\.tabla-ancla th:nth-child\(-n \+ 2\)[^{]*\{[^}]*position: sticky/)
    // la segunda columna se ancla a la derecha de la primera, sin solaparse
    expect(regla('.table.tabla-ancla th:first-child, .table.tabla-ancla td:first-child')).toContain('left: 0')
    expect(css).toMatch(/nth-child\(2\)[^{]*\{[^}]*left: 64px/)
    expect(css).toMatch(/first-child[^{]*\{[^}]*min-width: 64px/)
  })
})
