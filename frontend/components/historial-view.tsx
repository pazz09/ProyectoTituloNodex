'use client'

import { useCallback, useEffect, useState } from 'react'
import {
  AlertTriangle,
  ChevronLeft,
  ChevronRight,
  Clock3,
  Loader2,
  ThumbsDown,
  ThumbsUp,
} from 'lucide-react'

import { Header, type Vista } from '@/components/header'
import { listarHistorial, type Corrida } from '@/lib/api'

const POR_PAGINA = 15

function fechaCorta(iso: string) {
  const d = new Date(iso)
  return Number.isNaN(d.getTime())
    ? iso
    : d.toLocaleString('es', { dateStyle: 'short', timeStyle: 'short' })
}

function recortar(texto: string | null, largo = 90) {
  if (!texto) return '—'
  return texto.length > largo ? `${texto.slice(0, largo).trim()}…` : texto
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
    <main className="shell report-shell">
      <Header vista="historial" onNavegar={onNavegar} />
      <section className="report-content">
        <div className="report-top">
          <div>
            <div className="eyebrow">
              <Clock3 size={15} /> CORRIDAS ANTERIORES
            </div>
            <h1>Historial de análisis</h1>
            <p className="file-context">
              {total === 0
                ? 'Todavía no hay corridas registradas.'
                : `${total} corrida(s) · mostrando ${desde}–${hasta}`}
            </p>
          </div>
        </div>

        {error && (
          <div className="error-banner" role="alert">
            <div className="error-icon">
              <AlertTriangle size={19} />
            </div>
            <div>
              <strong>No se pudo cargar el historial</strong>
              <p>{error}</p>
            </div>
            <button className="secondary-button" onClick={() => cargar(offset)}>
              Reintentar
            </button>
          </div>
        )}

        <div className="events-card">
          <div className="section-heading">
            <div>
              <span className="eyebrow">REGISTRO</span>
              <h2>Análisis ejecutados</h2>
            </div>
            <span className="plain-help">Hacé clic en una fila para ver el informe completo</span>
          </div>

          {cargando ? (
            <p className="prosa vacio">
              <Loader2 size={15} className="spin" /> Cargando historial...
            </p>
          ) : corridas.length === 0 && !error ? (
            <p className="prosa vacio">
              Todavía no hay corridas. Analizá un archivo y va a aparecer acá.
            </p>
          ) : (
            <div className="events-table historial-table">
              <div className="event-row event-head">
                <span>FECHA</span>
                <span>ARCHIVO</span>
                <span>FORMATO</span>
                <span>DIAGNÓSTICO</span>
                <span>CONFIANZA</span>
                <span>VEREDICTOS</span>
              </div>
              {corridas.map((c) => (
                <div
                  className="event-row fila-clickable"
                  key={c.job_id}
                  role="button"
                  tabIndex={0}
                  onClick={() => onAbrir(c)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault()
                      onAbrir(c)
                    }
                  }}
                >
                  <span>{fechaCorta(c.timestamp)}</span>
                  <span className="mono">{c.archivo_origen ?? '—'}</span>
                  <span>{(c.formato_detectado ?? '—').toUpperCase()}</span>
                  <span className="celda-diagnostico">
                    {c.estado === 'error' ? (
                      <em>Análisis interrumpido</em>
                    ) : (
                      recortar(c.diagnostico)
                    )}
                  </span>
                  <span>
                    {c.confianza === null ? '—' : `${Math.round(c.confianza * 100)}%`}
                  </span>
                  <span className="celda-veredictos">
                    {c.hay_incidente && <span className="badge on">incidente</span>}
                    {c.hay_anomalia && !c.hay_incidente && (
                      <span className="badge on">anomalía</span>
                    )}
                    {c.requiere_revision_humana && <span className="badge warn">escalada</span>}
                    {c.feedback_correcto === true && (
                      <span className="badge fb-ok" title="Revisada: diagnóstico correcto">
                        <ThumbsUp size={11} />
                      </span>
                    )}
                    {c.feedback_correcto === false && (
                      <span className="badge fb-no" title="Revisada: diagnóstico incorrecto">
                        <ThumbsDown size={11} />
                      </span>
                    )}
                  </span>
                </div>
              ))}
            </div>
          )}

          {total > POR_PAGINA && (
            <div className="paginacion">
              <button
                className="secondary-button"
                disabled={offset === 0 || cargando}
                onClick={() => setOffset(Math.max(0, offset - POR_PAGINA))}
              >
                <ChevronLeft size={15} /> Anteriores
              </button>
              <span>
                {desde}–{hasta} de {total}
              </span>
              <button
                className="secondary-button"
                disabled={hasta >= total || cargando}
                onClick={() => setOffset(offset + POR_PAGINA)}
              >
                Siguientes <ChevronRight size={15} />
              </button>
            </div>
          )}
        </div>
      </section>
    </main>
  )
}
