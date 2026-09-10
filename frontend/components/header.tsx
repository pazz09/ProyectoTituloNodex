'use client'

import { CircleHelp, Clock3, LockKeyhole, Network } from 'lucide-react'

export type Vista = 'upload' | 'analysis' | 'report' | 'historial'

function Brand() {
  return (
    <div className="brand">
      <div className="brand-mark">
        <Network size={19} strokeWidth={2.5} />
      </div>
      <span>NODEX</span>
      <small>INTELIGENCIA DE SEGURIDAD</small>
    </div>
  )
}

/**
 * Barra superior. Gana un acceso al historial respecto del skeleton
 * original: es la única forma de llegar a la vista nueva, y va acá para no
 * agregar una barra de navegación aparte que rompería el encuadre.
 */
export function Header({
  vista,
  onNavegar,
  onHelp,
}: {
  vista?: Vista
  onNavegar?: (vista: Vista) => void
  onHelp?: () => void
}) {
  return (
    <header className="topbar">
      <Brand />
      <div className="topbar-right">
        {onNavegar && (
          <nav className="nav-tabs">
            <button
              className={vista !== 'historial' ? 'is-active' : ''}
              onClick={() => onNavegar('upload')}
            >
              Analizar
            </button>
            <button
              className={vista === 'historial' ? 'is-active' : ''}
              onClick={() => onNavegar('historial')}
            >
              <Clock3 size={13} /> Historial
            </button>
          </nav>
        )}
        <span className="secure-pill">
          <LockKeyhole size={13} /> Entorno seguro
        </span>
        <button className="icon-button" aria-label="Ayuda" onClick={onHelp}>
          <CircleHelp size={19} />
        </button>
      </div>
    </header>
  )
}
