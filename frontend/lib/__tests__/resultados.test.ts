/**
 * Utilidades de la vista "Resultados".
 *
 * La regla que atraviesa todo: `null` es «sin dato», nunca cero. Un cero se
 * promedia y se dibuja como barra; un `null` no. Por eso cada función que
 * formatea o exporta tiene que distinguir los dos.
 */
import { describe, expect, it } from 'vitest'

import {
  formatoCelda,
  formatoNumero,
  nombreArchivo,
  nombreArquitectura,
  SIN_DATO,
  tablaACsv,
  type TablaResultados,
} from '@/lib/resultados'

describe('formatoNumero', () => {
  it('distingue sin dato de cero', () => {
    expect(formatoNumero(null)).toBe(SIN_DATO)
    expect(formatoNumero(undefined)).toBe(SIN_DATO)
    expect(formatoNumero(0)).toBe('0,000')
    expect(formatoNumero(0)).not.toBe(formatoNumero(null))
  })

  it('usa coma decimal y la cantidad de decimales pedida', () => {
    expect(formatoNumero(0.8235294, 3)).toBe('0,824')
    expect(formatoNumero(12.5, 1)).toBe('12,5')
    expect(formatoNumero(7, 0)).toBe('7')
  })

  it('no muestra NaN ni infinito como si fueran un número', () => {
    expect(formatoNumero(Number.NaN)).toBe(SIN_DATO)
    expect(formatoNumero(Number.POSITIVE_INFINITY)).toBe(SIN_DATO)
  })

  it('muestra los booleanos y el texto vacío con sentido', () => {
    expect(formatoNumero(true)).toBe('sí')
    expect(formatoNumero(false)).toBe('no')
    expect(formatoNumero('')).toBe(SIN_DATO)
    expect(formatoNumero('uwf')).toBe('uwf')
  })
})

describe('formatoCelda', () => {
  it('aplica los decimales de cada tipo de columna', () => {
    expect(formatoCelda(3, 'entero')).toBe('3')
    expect(formatoCelda(2.345, 'numero')).toBe('2,35')
    expect(formatoCelda(0.5, 'proporcion')).toBe('0,500')
  })

  it('un null sigue siendo sin dato sea cual sea el tipo', () => {
    for (const tipo of ['entero', 'numero', 'proporcion', 'texto'] as const) {
      expect(formatoCelda(null, tipo)).toBe(SIN_DATO)
    }
  })
})

const tabla: TablaResultados = {
  titulo: 'T',
  seccion: '11.1',
  columnas: [
    { clave: 'dataset', etiqueta: 'Dataset' },
    { clave: 'precision', etiqueta: 'Precisión', tipo: 'proporcion' },
    { clave: 'recall', etiqueta: 'Exhaustividad', tipo: 'proporcion' },
    { clave: 'nota', etiqueta: 'Nota' },
    { clave: 'ok', etiqueta: 'OK' },
  ],
  filas: [
    { dataset: 'uwf', precision: null, recall: 0, nota: 'dice "hola", y chau', ok: true },
    { dataset: 'bgl', precision: 0.5, recall: 1, nota: 'línea\nnueva', ok: false },
  ],
}

describe('tablaACsv', () => {
  const csv = tablaACsv(tabla)
  const lineas = csv.replace('\uFEFF', '').split('\r\n')

  it('lleva BOM UTF-8 para que Excel no rompa las tildes', () => {
    expect(csv.startsWith('\uFEFF')).toBe(true)
  })

  it('la cabecera son las claves de las columnas', () => {
    expect(lineas[0]).toBe('dataset,precision,recall,nota,ok')
  })

  it('un null va como celda vacía y un cero va como 0', () => {
    // Esta es la prueba que importa: «precisión indefinida» y «exhaustividad
    // cero» son situaciones opuestas y el CSV no puede mostrarlas igual.
    const celdas = lineas[1].split(',')
    expect(celdas[1]).toBe('')
    expect(celdas[2]).toBe('0')
  })

  it('escapa comillas, comas y saltos de línea', () => {
    expect(lineas[1]).toContain('"dice ""hola"", y chau"')
    expect(csv).toContain('"línea\nnueva"')
  })

  it('escribe los booleanos como true/false, no como sí/no', () => {
    expect(lineas[1].endsWith(',true')).toBe(true)
    expect(csv).toContain(',false')
  })

  it('termina cada registro con CRLF: cabecera y dos filas son tres', () => {
    // El salto de linea DENTRO de las comillas de una celda es un LF suelto,
    // no un CRLF, asi que no cuenta como fin de registro.
    expect(csv.match(/\r\n/g)?.length).toBe(3)
  })

  it('una tabla sin filas exporta solo la cabecera', () => {
    const vacia = tablaACsv({ ...tabla, filas: [] })
    expect(vacia.replace('\uFEFF', '')).toBe('dataset,precision,recall,nota,ok\r\n')
  })
})

describe('nombreArchivo', () => {
  it('no deja espacios, tildes ni caracteres de ruta', () => {
    const n = nombreArchivo('piloto 001', '2026/10/14', 'Detección')
    expect(n).toMatch(/^[A-Za-z0-9._-]+$/)
    expect(n).not.toContain('/')
    expect(n).toContain('Deteccion')
  })
})

describe('nombreArquitectura', () => {
  it('traduce las conocidas y deja pasar las desconocidas', () => {
    expect(nombreArquitectura('nodex_multiagente')).toBe('NODEX')
    expect(nombreArquitectura('gemini_externo')).toBe('Gemini directo')
    expect(nombreArquitectura('otra')).toBe('otra')
  })
})
