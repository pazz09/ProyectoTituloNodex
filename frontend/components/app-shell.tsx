'use client'

import type { ReactNode } from 'react'
import { ChevronRight, Clock3, LockKeyhole, Network, ScanSearch, ShieldCheck } from 'lucide-react'

export type Vista = 'upload' | 'analysis' | 'report' | 'historial'

const SECCIONES = [
  { id: 'upload' as Vista, etiqueta: 'Análisis', icono: ScanSearch },
  { id: 'historial' as Vista, etiqueta: 'Historial', icono: Clock3 },
]

/**
 * Armazón de la consola: barra lateral persistente + área de trabajo.
 *
 * Reemplaza el flujo de tres pantallas sueltas del skeleton. La navegación
 * está siempre visible, y el contexto de lo que se está viendo va en la
 * barra superior como ruta, no como titular: una herramienta de análisis no
 * necesita presentarse en cada pantalla.
 */
export function AppShell({
  vista,
  ruta,
  acciones,
  onNavegar,
  children,
}: {
  vista: Vista
  ruta: ReactNode
  acciones?: ReactNode
  onNavegar: (vista: Vista) => void
  children: ReactNode
}) {
  // El análisis y el informe pertenecen a la sección "Análisis".
  const seccionActiva: Vista = vista === 'historial' ? 'historial' : 'upload'

  return (
    <div className="app">
      <aside className="rail">
        <div className="rail-inner">
          <div className="rail-brand">
            <div className="rail-mark">
              <Network size={16} strokeWidth={2.5} />
            </div>
            <div>
              <span>NODEX</span>
              <small>INTELIGENCIA DE SEGURIDAD</small>
            </div>
          </div>

          <nav className="rail-group">
            <span className="label">Operación</span>
            {SECCIONES.map(({ id, etiqueta, icono: Icono }) => (
              <button
                key={id}
                className={`rail-item ${seccionActiva === id ? 'is-active' : ''}`}
                onClick={() => onNavegar(id)}
                aria-current={seccionActiva === id ? 'page' : undefined}
              >
                <Icono size={15} /> {etiqueta}
              </button>
            ))}
          </nav>

          <div className="rail-foot">
            <span>
              <LockKeyhole size={12} /> Entorno local, sin salida a internet
            </span>
            <span>
              <ShieldCheck size={12} /> NODEX v1.0 · 7 agentes
            </span>
          </div>
        </div>
      </aside>

      <div className="workspace">
        <header className="topbar">
          <div className="crumbs">{ruta}</div>
          {acciones && <div className="topbar-actions">{acciones}</div>}
        </header>
        <main className="view">{children}</main>
      </div>
    </div>
  )
}

/** Separador de ruta, para no repetir el icono en cada vista. */
export function Sep() {
  return <ChevronRight size={13} />
}
