'use client'

import type { ReactNode } from 'react'
import { Activity, ChartColumn, LayoutGrid, Settings, Sparkles } from 'lucide-react'

export type Vista = 'overview' | 'analisis' | 'informe' | 'historial' | 'resultados'

/** Grupo de la barra lateral que queda resaltado. */
export type Grupo = 'overview' | 'historial' | 'analisis' | 'resultados'

/**
 * Armazón de la aplicación.
 *
 * La barra lateral sigue la referencia: logotipo espaciado, ítems callados con
 * el activo en una caja rellena, un divisor antes del grupo del asistente y
 * otro antes de Ajustes, que queda más apagado que el resto.
 *
 * El grupo resaltado se pasa desde afuera y no se deriva de la vista: al
 * informe se llega por dos caminos —recién analizado desde el asistente, o
 * abierto desde una ejecución anterior— y corresponde resaltar el camino por
 * el que se entró.
 */
export function AppShell({
  grupo,
  onNavegar,
  children,
  sinPadding = false,
}: {
  grupo: Grupo
  onNavegar: (vista: Vista) => void
  children: ReactNode
  /** La conversación maneja su propio espaciado y el compositor pegado abajo. */
  sinPadding?: boolean
}) {
  const item = (id: Vista, etiqueta: string, Icono: typeof LayoutGrid, activo: boolean) => (
    <button
      className={`rail-item ${activo ? 'is-active' : ''}`}
      onClick={() => onNavegar(id)}
      aria-current={activo ? 'page' : undefined}
    >
      <Icono size={16} strokeWidth={1.6} /> {etiqueta}
    </button>
  )

  return (
    <div className="marco-app">
      <div className="app">
        <aside className="rail">
          <div className="rail-inner">
            <div className="wordmark">NODEX</div>

            <nav className="rail-nav">
              {item('overview', 'Resumen', LayoutGrid, grupo === 'overview')}
              {item('historial', 'Ejecuciones', Activity, grupo === 'historial')}
              {item('resultados', 'Resultados', ChartColumn, grupo === 'resultados')}
            </nav>

            <div className="rail-sep" />

            <nav className="rail-nav">
              {item('analisis', 'Multiagente', Sparkles, grupo === 'analisis')}
            </nav>

            <div className="rail-foot">
              <div className="rail-sep" />
              {/* Presente porque la referencia lo tiene, e inerte porque el
                  prototipo no expone configuración desde la interfaz: se
                  configura por variables de entorno. */}
              <button className="rail-item inerte" disabled title="El prototipo se configura por variables de entorno">
                <Settings size={16} strokeWidth={1.6} /> Ajustes
              </button>
            </div>
          </div>
        </aside>

        <div className="workspace">
          {sinPadding ? children : <main className="view">{children}</main>}
        </div>
      </div>
    </div>
  )
}
