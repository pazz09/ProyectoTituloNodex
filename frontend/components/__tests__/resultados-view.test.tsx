/**
 * Vista "Resultados".
 *
 * **Todos los datos de estas pruebas son ficticios.** La fixture
 * `lib/__tests__/fixtures_ficticias/resultados_ficticio.json` se generó con
 * corridas simuladas, lleva `datos_ficticios: true` y la vista lo muestra con
 * un aviso. Vive fuera de `experiments/outputs` y `experiments/metrics`, que
 * quedan vacías.
 *
 * Lo que se verifica no son los números sino las reglas de honestidad:
 *  - sin datos no hay cifras;
 *  - `null` se muestra como — y un cero como 0,000;
 *  - las advertencias de integridad acompañan a CADA sección;
 *  - ninguna cifra se presenta como aprobada o reprobada (decisión D-3).
 */
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import fixture from '@/lib/__tests__/fixtures_ficticias/resultados_ficticio.json'
import { AppShell } from '@/components/app-shell'
import {
  ResultadosContenido,
  modeloComparacion,
  modeloDetalle,
  type PropsContenido,
} from '@/components/resultados-view'
import { descargarTexto, type ResumenResultados } from '@/lib/resultados'

vi.mock('@/lib/resultados', async (importar) => {
  const real = await importar<typeof import('@/lib/resultados')>()
  return { ...real, descargarTexto: vi.fn(), descargarBlob: vi.fn() }
})

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const resumen = fixture as unknown as ResumenResultados

const base: PropsContenido = {
  lista: {
    configuraciones: [
      { config_version: 'FICTICIO-no-usar', consolidaciones: ['20000101T000000Z'], ultima: '20000101T000000Z' },
    ],
  },
  configSeleccionada: 'FICTICIO-no-usar',
  consolidacionSeleccionada: '20000101T000000Z',
  resumen,
  cargando: false,
  error: null,
  reporte: null,
  cargandoReporte: false,
  errorReporte: null,
  onSeleccionarConfig: vi.fn(),
  onSeleccionarConsolidacion: vi.fn(),
  onActualizar: vi.fn(),
  onVerReporte: vi.fn(),
  onCerrarReporte: vi.fn(),
}

let desmontar: (() => void) | null = null

function montar(props: Partial<PropsContenido> = {}): HTMLElement {
  const contenedor = document.createElement('div')
  document.body.appendChild(contenedor)
  const raiz = createRoot(contenedor)
  act(() => {
    raiz.render(<ResultadosContenido {...base} {...props} />)
  })
  desmontar = () => {
    act(() => raiz.unmount())
    contenedor.remove()
  }
  return contenedor
}

beforeEach(() => {
  vi.clearAllMocks()
})

afterEach(() => {
  desmontar?.()
  desmontar = null
})

describe('sin datos', () => {
  it('no muestra ninguna cifra: ni tabla ni gráfico', () => {
    const c = montar({ lista: { configuraciones: [] }, resumen: null, configSeleccionada: null })
    expect(c.querySelector('#sin-resultados')).not.toBeNull()
    expect(c.textContent).toContain('Todavía no hay resultados experimentales')
    expect(c.querySelector('table')).toBeNull()
    expect(c.querySelector('svg:not([class*="lucide"])')).toBeNull()
  })

  it('lo dice con palabras: ni de ejemplo ni estimada', () => {
    const c = montar({ lista: { configuraciones: [] }, resumen: null, configSeleccionada: null })
    expect(c.textContent).toMatch(/ni de ejemplo ni estimada/)
  })

  it('mientras carga muestra un indicador y no cifras', () => {
    const c = montar({ cargando: true, resumen: null })
    expect(c.textContent).toContain('Cargando')
    expect(c.querySelector('table')).toBeNull()
  })

  it('un error se muestra como alerta con la causa y un botón para reintentar', () => {
    const c = montar({ error: 'No se pudo contactar al servidor', resumen: null })
    const alerta = c.querySelector('[role="alert"]')
    expect(alerta?.textContent).toContain('No se pudo contactar al servidor')
    const reintentar = [...c.querySelectorAll('button')].find((b) => b.textContent === 'Reintentar')
    act(() => reintentar!.click())
    expect(base.onActualizar).toHaveBeenCalled()
  })
})

describe('con la fixture ficticia', () => {
  it('avisa con claridad que los datos son ficticios', () => {
    const c = montar()
    expect(c.querySelector('#aviso-ficticio')?.textContent).toContain('DATOS FICTICIOS')
    expect(c.textContent).toMatch(/no deben citarse/)
  })

  it('muestra las siete secciones del informe, de la 11.1 a la 11.7', () => {
    const c = montar()
    for (const n of ['1', '2', '3', '4', '5', '6', '7']) {
      expect(c.querySelector(`#seccion-11-${n}`), `sección 11.${n}`).not.toBeNull()
    }
  })

  it('el panel de integridad y CADA sección llevan las advertencias', () => {
    // 1 panel de integridad + 7 secciones = 8 bloques de advertencias.
    const c = montar()
    expect(c.querySelectorAll('.avisos-integridad')).toHaveLength(8)
    for (const seccion of c.querySelectorAll('section[id^="seccion-11-"]')) {
      expect(seccion.querySelector('.avisos-integridad'), seccion.id).not.toBeNull()
    }
  })

  it('muestra fallback, telemetría previa a D-11 y corridas fallidas', () => {
    const texto = montar().querySelector('#integridad')!.textContent!
    expect(texto).toMatch(/modelo de respaldo/)
    expect(texto).toMatch(/antes de integrar D-11/)
    expect(texto).toMatch(/corridas fallidas/)
  })

  it('lista las corridas fallidas con su causa, no solo la cuenta', () => {
    const fallida = resumen.integridad.corridas_fallidas[0]
    const texto = montar().querySelector('#integridad')!.textContent!
    expect(texto).toContain(fallida.run_id)
  })

  it('muestra un null como — y un cero como 0,000', () => {
    const c = montar()
    // Fila del baseline en UWF: precisión indefinida (null), exhaustividad 0.
    const fila = [...c.querySelectorAll('#seccion-11-1 tbody tr')].find(
      (tr) => tr.textContent!.includes('uwf') && tr.textContent!.includes('Baseline de reglas'),
    )!
    const celdas = [...fila.querySelectorAll('td')].map((td) => td.textContent)
    const cab = [...c.querySelectorAll('#seccion-11-1 thead th')].map((th) => th.textContent)
    expect(celdas[cab.indexOf('Precisión')]).toBe('—')
    expect(celdas[cab.indexOf('Exhaustividad')]).toBe('0,000')
  })

  it('muestra la arquitectura con su nombre legible', () => {
    const texto = montar().querySelector('#seccion-11-1')!.textContent!
    expect(texto).toContain('NODEX')
    expect(texto).toContain('Baseline de reglas')
    expect(texto).toContain('Gemini directo')
    expect(texto).not.toContain('nodex_multiagente')
  })

  it('cada tabla tiene su botón CSV, y hay uno por tabla mostrada', () => {
    const c = montar()
    const botones = [...c.querySelectorAll('button')].filter((b) => b.textContent!.trim() === 'CSV')
    // d1 (2 tablas), d2, d3, d4, consumo, consultas externas, comparación y errores.
    expect(botones).toHaveLength(9)
  })

  it('el CSV descargado trae las mismas filas y columnas que la tabla en pantalla', () => {
    const c = montar()
    const boton = [...c.querySelectorAll('#seccion-11-1 button')].find(
      (b) => b.textContent!.trim() === 'CSV',
    )!
    act(() => (boton as HTMLButtonElement).click())
    expect(descargarTexto).toHaveBeenCalledTimes(1)
    const [nombre, contenido, tipo] = vi.mocked(descargarTexto).mock.calls[0]
    expect(nombre).toMatch(/d1_deteccion\.csv$/)
    expect(tipo).toContain('text/csv')
    const lineas = (contenido as string).replace(/^\uFEFF/, '').trim().split('\r\n')
    expect(lineas[0].split(',')).toEqual(
      resumen.tablas.d1_deteccion.columnas.map((col) => col.clave),
    )
    expect(lineas).toHaveLength(1 + resumen.tablas.d1_deteccion.filas.length)
  })

  it('cada gráfico se puede descargar en SVG y en PNG', () => {
    const c = montar()
    const textos = [...c.querySelectorAll('.figura-pie button')].map((b) => b.textContent!.trim())
    expect(textos.filter((t) => t === 'SVG').length).toBeGreaterThanOrEqual(5)
    expect(textos.filter((t) => t === 'PNG').length).toBeGreaterThanOrEqual(5)
    expect(c.querySelectorAll('.grafico-barras svg').length).toBeGreaterThanOrEqual(5)
  })

  it('el aviso del baseline en UWF explica que responde otra pregunta', () => {
    const aviso = montar().querySelector('#aviso-baseline')!.textContent!
    expect(aviso).toContain('En UWF el baseline responde otra pregunta')
    expect(aviso).toMatch(/contextual, no pareada/)
    expect(aviso).toMatch(/Gemini directo no usa RAG ni herramientas/)
  })

  it('no presenta ninguna cifra como aprobada o reprobada', () => {
    // Decisión D-3: sin umbrales absolutos; se comparan arquitecturas. La
    // frase «Sin umbrales de aprobado» es justamente el aviso correcto, así que
    // se quita antes de buscar cualquier otro veredicto.
    const texto = montar().textContent!.replace('Sin umbrales de aprobado', '')
    expect(texto).not.toMatch(/aprobad|reprobad|supera el umbral|cumple/i)
  })

  it('los selectores ofrecen la configuración y la consolidación', () => {
    const c = montar()
    const selects = c.querySelectorAll('select')
    expect(selects).toHaveLength(2)
    expect(selects[0].textContent).toContain('FICTICIO-no-usar')
    expect(selects[1].textContent).toContain('20000101T000000Z')
  })
})

describe('secciones sin datos', () => {
  const sinRubrica: ResumenResultados = {
    ...resumen,
    tablas: { ...resumen.tablas, d4_rubrica: { ...resumen.tablas.d4_rubrica, filas: [] } },
  }

  it('una sección sin filas dice por qué y no dibuja nada', () => {
    const c = montar({ resumen: sinRubrica })
    const seccion = c.querySelector('#seccion-11-4')!
    expect(seccion.textContent).toContain('Sin datos para esta sección')
    expect(seccion.textContent).toMatch(/puntúan dos personas/)
    expect(seccion.querySelector('table')).toBeNull()
    expect(seccion.querySelector('svg')).toBeNull()
  })

  it('aun sin datos la sección conserva sus advertencias de integridad', () => {
    expect(montar({ resumen: sinRubrica }).querySelector('#seccion-11-4 .avisos-integridad')).not.toBeNull()
  })

  it('D2 y D3 explican que solo aplican a UWF', () => {
    const vacio: ResumenResultados = {
      ...resumen,
      tablas: {
        ...resumen.tablas,
        d2_reconstruccion: { ...resumen.tablas.d2_reconstruccion, filas: [] },
        d3_mitre: { ...resumen.tablas.d3_mitre, filas: [] },
      },
    }
    const c = montar({ resumen: vacio })
    expect(c.querySelector('#seccion-11-2')!.textContent).toMatch(/solo se mide en UWF/)
    expect(c.querySelector('#seccion-11-3')!.textContent).toMatch(/solo se mide en UWF/)
  })
})

describe('falsos positivos y negativos (11.7)', () => {
  it('cada error tiene un botón para ver el reporte de esa corrida', () => {
    const c = montar()
    const filas = resumen.tablas.errores_d1.filas
    const botones = [...c.querySelectorAll('#seccion-11-7 tbody button')]
    expect(botones).toHaveLength(filas.length)
    act(() => botones[0].dispatchEvent(new MouseEvent('click', { bubbles: true })))
    expect(base.onVerReporte).toHaveBeenCalledWith(String(filas[0].run_id))
  })

  it('muestra el reporte tal cual lo produjo el sistema', () => {
    const c = montar({
      reporte: {
        run_id: 'r1', case_id: 'c1', dataset: 'uwf', arquitectura: 'nodex_multiagente',
        repeticion: 1, estado_ejecucion: 'completa', clasificacion: 'MALICIOUS',
        motivo_no_evaluable: null, reporte: 'Texto del reporte ficticio',
      },
    })
    expect(c.querySelector('.reporte-texto')?.textContent).toBe('Texto del reporte ficticio')
  })

  it('una corrida sin reporte lo dice en vez de inventar texto', () => {
    const c = montar({
      reporte: {
        run_id: 'r1', case_id: 'c1', dataset: 'uwf', arquitectura: 'gemini_externo',
        repeticion: 1, estado_ejecucion: 'error_contrato', clasificacion: null,
        motivo_no_evaluable: 'sin veredicto', reporte: null,
      },
    })
    expect(c.querySelector('.reporte-texto')).toBeNull()
    expect(c.querySelector('#reporte-corrida')!.textContent).toContain('no produjo un reporte')
    expect(c.querySelector('#reporte-corrida')!.textContent).toContain('sin veredicto')
  })
})

describe('modelos de gráfico', () => {
  it('un null de la tabla llega al gráfico como null y no como cero', () => {
    const m = modeloDetalle(resumen.tablas.d1_deteccion, 't', [
      { clave: 'precision', nombre: 'P' },
    ])
    const fila = resumen.tablas.d1_deteccion.filas.findIndex((f) => f.precision === null)
    expect(fila).toBeGreaterThanOrEqual(0)
    expect(m.grupos[fila].valores[0]).toBeNull()
  })

  it('una tabla ausente da un gráfico sin grupos', () => {
    expect(modeloDetalle(undefined, 't', [{ clave: 'x', nombre: 'x' }]).grupos).toEqual([])
  })

  it('la comparación grafica solo F1 y coincidencia exacta', () => {
    const m = modeloComparacion(resumen.tablas.comparacion)
    expect(m.series.map((s) => s.nombre)).toEqual(['NODEX', 'Baseline de reglas', 'Gemini directo'])
    expect(m.grupos.length).toBeGreaterThan(0)
    for (const g of m.grupos) expect(g.etiqueta).toMatch(/f1|exact/i)
  })

  it('la comparación deja null donde una arquitectura no aplica', () => {
    const m = modeloComparacion(resumen.tablas.comparacion)
    const d2 = m.grupos.find((g) => /D2 f1/.test(g.etiqueta))!
    expect(d2.valores[1]).toBeNull() // el baseline no reconstruye
  })
})

describe('barra lateral', () => {
  it('incluye «Resultados» y lo marca como activo cuando corresponde', () => {
    const contenedor = document.createElement('div')
    document.body.appendChild(contenedor)
    const raiz = createRoot(contenedor)
    const navegar = vi.fn()
    act(() => {
      raiz.render(
        <AppShell grupo="resultados" onNavegar={navegar}>
          <p>x</p>
        </AppShell>,
      )
    })
    const boton = [...contenedor.querySelectorAll('button.rail-item')].find((b) =>
      b.textContent!.includes('Resultados'),
    )!
    expect(boton.getAttribute('aria-current')).toBe('page')
    act(() => (boton as HTMLButtonElement).click())
    expect(navegar).toHaveBeenCalledWith('resultados')
    const otros = [...contenedor.querySelectorAll('button.rail-item')].filter((b) => b !== boton)
    expect(otros.some((b) => b.getAttribute('aria-current') === 'page')).toBe(false)
    act(() => raiz.unmount())
    contenedor.remove()
  })
})

describe('Resultados: versión devuelta por la API y tokens de razonamiento', () => {
  const montarVista = () => {
    const contenedor = document.createElement('div')
    document.body.appendChild(contenedor)
    const raiz = createRoot(contenedor)
    act(() => raiz.render(<ResultadosContenido {...base} />))
    desmontar = () => {
      act(() => raiz.unmount())
      contenedor.remove()
    }
    return contenedor
  }

  const celdaDe = (c: HTMLElement, dataset: string, arq: string, columna: string) => {
    const cab = [...c.querySelectorAll('#seccion-11-5 thead th')].map((th) => th.textContent)
    const fila = [...c.querySelectorAll('#seccion-11-5 tbody tr')].find(
      (tr) => tr.textContent!.includes(dataset) && tr.textContent!.includes(arq),
    )!
    return [...fila.querySelectorAll('td')].map((td) => td.textContent)[cab.indexOf(columna)]
  }

  afterEach(() => desmontar?.())

  it('la tabla de consumo trae las dos columnas nuevas', () => {
    const c = montarVista()
    const cab = [...c.querySelectorAll('#seccion-11-5 thead th')].map((th) => th.textContent)
    expect(cab).toContain('Tokens de razonamiento')
    expect(cab).toContain('Versión devuelta por la API')
  })

  it('muestra el valor informado y — donde el proveedor no lo informó (no 0)', () => {
    const c = montarVista()
    expect(celdaDe(c, 'uwf', 'NODEX', 'Tokens de razonamiento')).toBe('40,00')
    expect(celdaDe(c, 'bgl', 'NODEX', 'Tokens de razonamiento')).toBe('—')
    expect(celdaDe(c, 'uwf', 'Baseline de reglas', 'Tokens de razonamiento')).toBe('—')
    expect(celdaDe(c, 'uwf', 'Baseline de reglas', 'Versión devuelta por la API')).toBe('—')
  })

  it('muestra la versión tal como la devolvió la API, también cuando hubo dos', () => {
    const c = montarVista()
    expect(celdaDe(c, 'uwf', 'NODEX', 'Versión devuelta por la API')).toContain(';')
    expect(celdaDe(c, 'uwf', 'Gemini directo', 'Versión devuelta por la API')).toMatch(/-001$/)
  })

  it('el gráfico de tokens incluye la serie de razonamiento', () => {
    const c = montarVista()
    const leyendas = [...c.querySelectorAll('#seccion-11-5 .grafico-barras svg')]
      .map((s) => s.textContent)
      .join(' ')
    expect(leyendas).toContain('Razonamiento')
  })

  it('el aviso de razonamiento no informado acompaña a las cifras de consumo', () => {
    const c = montarVista()
    expect(c.querySelector('#seccion-11-5 .avisos-integridad')!.textContent).toMatch(
      /sin tokens de razonamiento/,
    )
  })

  it('el CSV de consumo conserva las celdas vacías como vacías', () => {
    const c = montarVista()
    const boton = [...c.querySelectorAll('#seccion-11-5 button')].find(
      (b) => b.textContent!.trim() === 'CSV',
    )!
    vi.mocked(descargarTexto).mockClear()
    act(() => (boton as HTMLButtonElement).click())
    const contenido = vi.mocked(descargarTexto).mock.calls[0][1] as string
    const lineas = (contenido as string).replace(/^\uFEFF/, '').trim().split('\r\n')
    const cab = lineas[0].split(',')
    const iRaz = cab.indexOf('tokens_razonamiento_medios')
    expect(iRaz).toBeGreaterThan(-1)
    const bgl = lineas.find((l) => l.startsWith('bgl,nodex_multiagente'))!.split(',')
    expect(bgl[iRaz]).toBe('')
  })
})

describe('Resultados: depuración, tokens parciales y consultas externas', () => {
  const montarVista = (r: ResumenResultados = resumen) => {
    const contenedor = document.createElement('div')
    document.body.appendChild(contenedor)
    const raiz = createRoot(contenedor)
    act(() => raiz.render(<ResultadosContenido {...base} resumen={r} />))
    desmontar = () => {
      act(() => raiz.unmount())
      contenedor.remove()
    }
    return contenedor
  }

  afterEach(() => desmontar?.())

  it('los resultados de depuración llevan un aviso visible de que no son reportables', () => {
    const c = montarVista()
    const aviso = c.querySelector('#aviso-depuracion')!
    expect(aviso).not.toBeNull()
    expect(aviso.textContent).toMatch(/DEPURACIÓN/)
    expect(aviso.textContent).toMatch(/NO REPORTABLES/)
  })

  it('sin depuración no se muestra el aviso', () => {
    const c = montarVista({ ...resumen, depuracion: false, reportable: true })
    expect(c.querySelector('#aviso-depuracion')).toBeNull()
  })

  it('una consolidación anterior (sin el campo depuracion) no rompe la vista', () => {
    const { depuracion: _d, reportable: _r, ...anterior } = resumen
    const c = montarVista(anterior as ResumenResultados)
    expect(c.querySelector('#aviso-depuracion')).toBeNull()
    expect(c.querySelector('#integridad')).not.toBeNull()
  })

  it('lista las corridas con tokens parciales, con ≥ y cuántas llamadas la sustentan', () => {
    const c = montarVista()
    const bloque = c.querySelector('#tokens-parciales')!
    expect(bloque).not.toBeNull()
    expect(bloque.textContent).toMatch(/≥ 30 entrada/)
    expect(bloque.textContent).toMatch(/2 de 3 llamadas/)
    expect(bloque.textContent).toMatch(/1 fallida/)
    expect(bloque.textContent).toMatch(/nunca un total/)
  })

  it('sin corridas con tokens parciales no aparece ese bloque', () => {
    const limpio = JSON.parse(JSON.stringify(resumen)) as ResumenResultados
    limpio.integridad.corridas_con_tokens_parciales = []
    expect(montarVista(limpio).querySelector('#tokens-parciales')).toBeNull()
  })

  it('el aviso tokens_parciales aparece junto a las cifras de consumo', () => {
    const texto = montarVista().querySelector('#seccion-11-5 .avisos-integridad')!.textContent!
    expect(texto).toMatch(/total de tokens en None/)
  })

  it('la tabla de consumo muestra la suma parcial rotulada y las llamadas fallidas', () => {
    const c = montarVista()
    const cab = [...c.querySelectorAll('#seccion-11-5 thead th')].map((th) => th.textContent)
    expect(cab).toContain('Llamadas fallidas')
    expect(cab.some((h) => h!.startsWith('Tokens parciales'))).toBe(true)
    const iParcial = cab.findIndex((h) => h!.startsWith('Tokens parciales'))
    const fila = [...c.querySelectorAll('#seccion-11-5 tbody tr')].find(
      (tr) => tr.textContent!.includes('uwf') && tr.textContent!.includes('NODEX')
        && tr.textContent!.includes('≥'),
    )!
    const celda = [...fila.querySelectorAll('td')][iParcial].textContent!
    expect(celda).toBe('≥ 30 entrada · ≥ 12 salida · ≥ 7 razonamiento (2 de 3 llamadas)')
  })

  it('muestra la tabla de intentos de consulta externa por arquitectura y dataset', () => {
    const c = montarVista()
    const tablas = [...c.querySelectorAll('#seccion-11-5 table')]
    const ext = tablas.find((t) => t.textContent!.includes('Intentos de salida a la red'))!
    expect(ext).toBeDefined()
    const cab = [...ext.querySelectorAll('thead th')].map((th) => th.textContent)
    const fila = (ds: string, arq: string, herr: string) =>
      [...ext.querySelectorAll('tbody tr')].find((tr) => {
        const td = [...tr.querySelectorAll('td')].map((x) => x.textContent)
        return td[0] === ds && td[1] === arq && td[2] === herr
      })
    const nodex = [...fila('uwf', 'NODEX', 'abuseipdb')!.querySelectorAll('td')].map((x) => x.textContent)
    expect(nodex[cab.indexOf('Consultas a la herramienta')]).toBe('2')
    expect(nodex[cab.indexOf('Bloqueados')]).toBe('2')
    // Gemini directo y el baseline no usan herramientas: no aplica (—), no 0.
    const gem = [...fila('uwf', 'Gemini directo', 'nvd')!.querySelectorAll('td')].map((x) => x.textContent)
    expect(gem[cab.indexOf('Consultas a la herramienta')]).toBe('—')
    // BGL de NODEX no tiene registro: tampoco es 0.
    const bgl = [...fila('bgl', 'NODEX', 'nvd')!.querySelectorAll('td')].map((x) => x.textContent)
    expect(bgl[cab.indexOf('Consultas a la herramienta')]).toBe('—')
  })

  it('una consolidación anterior sin la tabla de consultas externas no la muestra ni falla', () => {
    const anterior = JSON.parse(JSON.stringify(resumen)) as ResumenResultados
    delete (anterior.tablas as Record<string, unknown>).consultas_externas
    const c = montarVista(anterior)
    expect(c.textContent).not.toContain('Intentos de salida a la red')
  })

  it('la tabla de consultas externas se puede descargar en CSV con las celdas vacías como vacías', () => {
    const c = montarVista()
    const botones = [...c.querySelectorAll('#seccion-11-5 button')].filter(
      (b) => b.textContent!.trim() === 'CSV',
    )
    vi.mocked(descargarTexto).mockClear()
    act(() => (botones[botones.length - 1] as HTMLButtonElement).click())
    const [nombre, contenido] = vi.mocked(descargarTexto).mock.calls[0]
    expect(nombre).toMatch(/consultas_externas\.csv$/)
    const lineas = (contenido as string).replace(/^\uFEFF/, '').trim().split('\r\n')
    const gem = lineas.find((l) => l.startsWith('uwf,gemini_externo,nvd'))!.split(',')
    expect(gem[lineas[0].split(',').indexOf('n_consultas')]).toBe('')
  })
})

describe('Resultados: tablas que caben o se desplazan con sentido', () => {
  const montarVista = () => {
    const contenedor = document.createElement('div')
    document.body.appendChild(contenedor)
    const raiz = createRoot(contenedor)
    act(() => raiz.render(<ResultadosContenido {...base} />))
    desmontar = () => {
      act(() => raiz.unmount())
      contenedor.remove()
    }
    return contenedor
  }

  afterEach(() => desmontar?.())

  it('las tablas que empiezan con dataset y arquitectura fijan esas dos columnas', () => {
    const c = montarVista()
    const tablas = [...c.querySelectorAll('table')]
    const consumo = tablas.find((t) => t.textContent!.includes('Corridas con total None'))!
    const consultas = tablas.find((t) => t.textContent!.includes('Intentos de salida a la red'))!
    expect(consumo.classList.contains('tabla-ancla')).toBe(true)
    expect(consultas.classList.contains('tabla-ancla')).toBe(true)
  })

  it('una tabla con otras columnas iniciales no se ancla', () => {
    const c = montarVista()
    const sinAncla = [...c.querySelectorAll('table')].filter(
      (t) => !t.classList.contains('tabla-ancla'),
    )
    for (const t of sinAncla) {
      const [a, b] = [...t.querySelectorAll('thead th')].map((th) => th.textContent)
      expect(a === 'Dataset' && b === 'Arquitectura').toBe(false)
    }
  })

  it('la tabla de consultas externas no tiene la columna «Nota» y sí un estado corto', () => {
    const c = montarVista()
    const t = [...c.querySelectorAll('table')].find((x) =>
      x.textContent!.includes('Intentos de salida a la red'),
    )!
    const cab = [...t.querySelectorAll('thead th')].map((th) => th.textContent)
    expect(cab).not.toContain('Nota')
    expect(cab).toContain('Estado')
    const iEstado = cab.indexOf('Estado')
    for (const tr of t.querySelectorAll('tbody tr')) {
      const estado = [...tr.querySelectorAll('td')][iEstado].textContent!
      expect(estado.length).toBeLessThanOrEqual(12)
    }
  })

  it('la tabla de consumo tiene encabezados cortos', () => {
    const c = montarVista()
    const t = [...c.querySelectorAll('table')].find((x) =>
      x.textContent!.includes('Corridas con total None'),
    )!
    for (const th of t.querySelectorAll('thead th')) {
      expect(th.textContent!.length, th.textContent!).toBeLessThanOrEqual(34)
    }
  })

  it('las seis tarjetas de integridad están en el mismo contenedor', () => {
    const c = montarVista()
    expect(c.querySelectorAll('#integridad .kpis .kpi')).toHaveLength(6)
  })
})
