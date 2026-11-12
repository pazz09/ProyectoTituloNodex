/**
 * Test mínimo para el CI (Fase 7 del cierre de auditoría, 23-sep-2026):
 * no busca cobertura, busca que el pipeline de test exista y corra algo
 * real, no un placeholder. Los dos casos abajo son utilidades puras que sí
 * importa que no se rompan en silencio.
 */
import { describe, expect, it } from 'vitest'

import { cn } from '@/lib/utils'
import { NODOS } from '@/lib/nodos'

describe('cn', () => {
  it('combina clases y resuelve conflictos de Tailwind', () => {
    expect(cn('px-2', 'px-4')).toBe('px-4')
    expect(cn('text-sm', undefined, 'font-bold')).toBe('text-sm font-bold')
  })
})

describe('NODOS', () => {
  it('tiene exactamente los 10 nodos del grafo del backend', () => {
    // Si esto falla, el catálogo del frontend quedó desincronizado del
    // grafo real (src/graph/build_graph.py). NODEX final, Fase B: 6 agentes
    // LLM (se suma el cazador) + 4 tools (se suma la corrección del diagnóstico).
    expect(NODOS).toHaveLength(10)
    expect(NODOS.map((n) => n.nombre)).toEqual([
      'agente_planificador',
      'agente_analista_triage',
      'agente_cazador',
      'agente_selector_herramientas',
      'tool_consultar_rag',
      'tool_consultar_cve',
      'agente_ingeniero_mitigacion',
      'tool_validar_comandos',
      'agente_auditor_final',
      'tool_corregir_diagnostico',
    ])
  })

  it('cada nodo tiene título y descripción no vacíos', () => {
    for (const nodo of NODOS) {
      expect(nodo.titulo.length).toBeGreaterThan(0)
      expect(nodo.descripcion.length).toBeGreaterThan(0)
    }
  })
})
