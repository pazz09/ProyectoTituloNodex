'use client'

import { useCallback, useEffect, useState } from 'react'
import {
  AlertTriangle,
  ChevronLeft,
  ChevronRight,
  Loader2,
  RotateCcw,
  ThumbsDown,
  ThumbsUp,
} from 'lucide-react'

import { AppShell, type Vista } from '@/components/app-shell'
import { listarHistorial, type Corrida } from '@/lib/api'

const POR_PAGINA = 20

function fechaCorta(iso: string) {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleString('es', {
    day: '2-digit',
    month: '2-digit',
    year: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function recortar(texto: string | null, largo = 110) {
  if (!texto) return '—'
  return texto.length > largo ? `${texto.slice(0, largo).trim()}…` : texto
}

function estadoDe(c: Corrida) {
  if (c.estado === 'error') return { clase: 'crit', texto: 'error' }
  if (c.hay_incidente) return { clase: 'crit', texto: 'incidente' }
  if (c.hay_anomalia) return { clase: 'warn', texto: 'anomalía' }
  return { clase: 'ok', texto: 'limpio' }
}

export function HistorialView({
  onAbrir,
  onNavegar,
}: {
  onAbrir: (corrida: Corrida) => void
  onNavegar: (vista: Vista) => void
}) {
  const [corridas, setCorridas] = useState<Corrida[]>([])
  const [total, setTotal] = useState(0)
  const [offset, setOffset] = useState(0)
  const [cargando, setCargando] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const cargar = useCallback(async (desde: number) => {
    setCargando(true)
    setError(null)
    try {
      const datos = await listarHistorial(POR_PAGINA, desde)
      setCorridas(datos.corridas)
      setTotal(datos.total)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setCargando(false)
    }
  }, [])

  useEffect(() => {
    cargar(offset)
  }, [cargar, offset])

  const desde = total === 0 ? 0 : offset + 1
  const hasta = Math.min(offset + POR_PAGINA, total)

  return (
    <AppShell
      vista="historial"
      onNavegar={onNavegar}
      ruta={
        <>
          <span>Historial</span>
          <strong>Ejecuciones</strong>
        </>
      }
      acciones={
        <button className="btn" onClick={() => cargar(offset)} disabled={cargando}>
          <RotateCcw size={14} /> Actualizar
        </button>
      }
    >
      <div className="view-head">
        <div>
          <h1>Historial de ejecuciones</h1>
          <p>
            Los resultados quedan persistidos localmente: revisar un informe anterior no vuelve
            a ejecutar el grafo ni consume cuota del modelo.
          </p>
        </div>
      </div>

      {error && (
        <div className="notice-block" role="alert">
          <div className="modal-icon" style={{ margin: 0, color: 'var(--crit)', background: 'var(--crit-bg)', borderColor: 'var(--crit-line)' }}>
            <AlertTriangle size={16} />
          </div>
          <div>
            <strong>No se pudo cargar el historial</strong>
            <p>{error}</p>
          </div>
          <button className="btn" onClick={() => cargar(offset)}>
            Reintentar
          </button>
        </div>
      )}

      <section className="panel">
        <div className="panel-head">
          <div>
            <span className="label">Registro</span>
            <h2>
              {total} {total === 1 ? 'ejecución' : 'ejecuciones'}
            </h2>
          </div>
          <span className="panel-note">clic en una fila para abrir el informe</span>
        </div>

        {cargando ? (
          <div className="panel-body">
            <p className="prose empty">
              <Loader2 size={14} className="spin" /> Cargando…
            </p>
          </div>
        ) : corridas.length === 0 && !error ? (
          <div className="panel-body">
            <p className="prose empty">
              Sin ejecuciones registradas. Analizá un archivo y va a aparecer acá.
            </p>
          </div>
        ) : (
          <>
            <div className="table-scroll">
              <table className="table">
                <thead>
                  <tr>
                    <th>Fecha</th>
                    <th>Archivo</th>
                    <th>Formato</th>
                    <th>Diagnóstico</th>
                    <th style={{ textAlign: 'right' }}>Conf.</th>
                    <th>Estado</th>
                    <th>Revisión</th>
                  </tr>
                </thead>
                <tbody>
                  {corridas.map((c) => {
                    const e = estadoDe(c)
                    return (
                      <tr
                        key={c.job_id}
                        className="clickable"
                        tabIndex={0}
                        onClick={() => onAbrir(c)}
                        onKeyDown={(ev) => {
                          if (ev.key === 'Enter' || ev.key === ' ') {
                            ev.preventDefault()
                            onAbrir(c)
                          }
                        }}
                      >
                        <td className="mono" style={{ whiteSpace: 'nowrap' }}>
                          {fechaCorta(c.timestamp)}
                        </td>
                        <td className="mono">{c.archivo_origen ?? '—'}</td>
                        <td className="mono nowrap" style={{ color: 'var(--text-muted)' }}>
                          {(c.formato_detectado ?? '—').toUpperCase().replace(/_/g, '-')}
                        </td>
                        <td style={{ minWidth: 280 }}>
                          {c.estado === 'error' ? (
                            <span style={{ color: 'var(--crit)' }}>Ejecución interrumpida</span>
                          ) : (
                            recortar(c.diagnostico)
                          )}
                        </td>
                        <td className="num">{c.confianza === null ? '—' : c.confianza.toFixed(2)}</td>
                        <td>
                          <span className={`chip ${e.clase}`}>{e.texto}</span>
                          {c.requiere_revision_humana && (
                            <span className="chip warn" style={{ marginLeft: 5 }}>
                              escalado
                            </span>
                          )}
                        </td>
                        <td>
                          {c.feedback_correcto === true && (
                            <span className="chip ok" title="Revisada: diagnóstico correcto">
                              <ThumbsUp size={10} /> correcto
                            </span>
                          )}
                          {c.feedback_correcto === false && (
                            <span className="chip crit" title="Revisada: diagnóstico incorrecto">
                              <ThumbsDown size={10} /> incorrecto
                            </span>
                          )}
                          {c.feedback_correcto === null && (
                            <span style={{ color: 'var(--text-faint)' }}>sin revisar</span>
                          )}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>

            {total > POR_PAGINA && (
              <div className="pager">
                <button
                  className="btn"
                  disabled={offset === 0 || cargando}
                  onClick={() => setOffset(Math.max(0, offset - POR_PAGINA))}
                >
                  <ChevronLeft size={14} /> Anteriores
                </button>
                <span>
                  {desde}–{hasta} de {total}
                </span>
                <button
                  className="btn"
                  disabled={hasta >= total || cargando}
                  onClick={() => setOffset(offset + POR_PAGINA)}
                >
                  Siguientes <ChevronRight size={14} />
                </button>
              </div>
            )}
          </>
        )}
      </section>
    </AppShell>
  )
}
