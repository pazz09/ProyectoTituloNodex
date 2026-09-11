'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  AlertTriangle,
  ArrowUpRight,
  Check,
  Loader2,
  Sparkles,
  TrendingUp,
} from 'lucide-react'

import { AppShell, type Vista } from '@/components/app-shell'
import { AreaChart, type Punto } from '@/components/area-chart'
import { listarHistorial, type Corrida } from '@/lib/api'

/** Cuántas ejecuciones se traen para calcular los agregados. */
const MUESTRA = 200

type Rango = '7d' | '30d' | 'todo'

const RANGOS: { id: Rango; etiqueta: string; dias: number | null }[] = [
  { id: '7d', etiqueta: '7D', dias: 7 },
  { id: '30d', etiqueta: '30D', dias: 30 },
  { id: 'todo', etiqueta: 'TODO', dias: null },
]

/**
 * Clave de día en hora LOCAL.
 *
 * Con `toISOString()` la clave sale en UTC, y una corrida de las 23:31 local
 * caía en el día siguiente mientras el límite "hoy" se calculaba en local:
 * el gráfico mostraba un día que todavía no existía.
 */
function claveDia(d: Date) {
  const mes = String(d.getMonth() + 1).padStart(2, '0')
  const dia = String(d.getDate()).padStart(2, '0')
  return `${d.getFullYear()}-${mes}-${dia}`
}

function diaDe(iso: string) {
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? null : claveDia(d)
}

function etiquetaDia(clave: string) {
  const [, m, d] = clave.split('-')
  return `${d}/${m}`
}

export function OverviewView({
  onAbrir,
  onNavegar,
}: {
  onAbrir: (corrida: Corrida) => void
  onNavegar: (vista: Vista) => void
}) {
  const [corridas, setCorridas] = useState<Corrida[]>([])
  const [cargando, setCargando] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [rango, setRango] = useState<Rango>('30d')

  const cargar = useCallback(async () => {
    setCargando(true)
    setError(null)
    try {
      const datos = await listarHistorial(MUESTRA, 0)
      setCorridas(datos.corridas)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setCargando(false)
    }
  }, [])

  useEffect(() => {
    cargar()
  }, [cargar])

  const kpis = useMemo(() => {
    const completas = corridas.filter((c) => c.estado !== 'error')
    const confianzas = completas.map((c) => c.confianza).filter((v): v is number => v !== null)
    return {
      total: corridas.length,
      incidentes: corridas.filter((c) => c.hay_incidente).length,
      escalados: corridas.filter((c) => c.requiere_revision_humana).length,
      revisadas: corridas.filter((c) => c.feedback_correcto !== null).length,
      confianza: confianzas.length
        ? confianzas.reduce((a, b) => a + b, 0) / confianzas.length
        : null,
      errores: corridas.filter((c) => c.estado === 'error').length,
    }
  }, [corridas])

  // Serie de actividad: ejecuciones por día. Se rellenan los días sin
  // ejecuciones con cero -- si no, el gráfico comprimiría el tiempo y haría
  // parecer continua una actividad que no lo fue.
  const serie = useMemo<Punto[]>(() => {
    const dias = RANGOS.find((r) => r.id === rango)?.dias ?? null
    const claves = corridas.map((c) => diaDe(c.timestamp)).filter((d): d is string => d !== null)
    if (claves.length === 0) return []

    const conteo = new Map<string, number>()
    for (const k of claves) conteo.set(k, (conteo.get(k) ?? 0) + 1)

    const hoy = new Date()
    const primera = new Date(`${claves.reduce((a, b) => (a < b ? a : b))}T12:00:00`)
    const desde = dias
      ? new Date(hoy.getTime() - (dias - 1) * 86400000)
      : primera
    const inicio = desde > primera && dias ? desde : primera

    const puntos: Punto[] = []
    // Se recorre por mediodía local para que el paso de 24 h no se desfase
    // con los cambios de horario de verano.
    const cursor = new Date(inicio)
    cursor.setHours(12, 0, 0, 0)
    const limite = new Date(hoy)
    limite.setHours(12, 0, 0, 0)
    while (cursor <= limite) {
      const clave = claveDia(cursor)
      puntos.push({ etiqueta: etiquetaDia(clave), valor: conteo.get(clave) ?? 0 })
      cursor.setDate(cursor.getDate() + 1)
    }
    return puntos
  }, [corridas, rango])

  const recientes = corridas.slice(0, 6)

  return (
    <AppShell grupo="overview" onNavegar={onNavegar}>
      <div className="view-head">
        <h1>Resumen del sistema</h1>
        <p>Actividad de análisis, veredictos y revisión humana en una sola vista.</p>
      </div>

      {error && (
        <div className="notice-block" role="alert">
          <div className="icono-aviso">
            <AlertTriangle size={16} />
          </div>
          <div>
            <strong>No se pudo leer el historial</strong>
            <p>{error}</p>
          </div>
          <button className="btn" onClick={cargar}>
            Reintentar
          </button>
        </div>
      )}

      {cargando ? (
        <div className="panel">
          <div className="panel-body">
            <p className="prose empty">
              <Loader2 size={15} className="spin" /> Cargando agregados…
            </p>
          </div>
        </div>
      ) : corridas.length === 0 ? (
        <div className="panel">
          <div className="panel-body" style={{ textAlign: 'center', padding: '54px 24px' }}>
            <p className="prose" style={{ marginBottom: 18 }}>
              Todavía no hay ejecuciones registradas. Analizá un lote y el resumen se va a poblar
              con datos reales.
            </p>
            <button className="btn btn-primary" onClick={() => onNavegar('analisis')}>
              <Sparkles size={14} /> Abrir el asistente
            </button>
          </div>
        </div>
      ) : (
        <>
          <div className="kpis">
            <div className="kpi">
              <div className="kpi-top">
                <b>{kpis.total}</b>
                <span className="marca ok">
                  <Check size={13} />
                </span>
              </div>
              <span>Ejecuciones registradas</span>
            </div>
            <div className="kpi">
              <div className="kpi-top">
                <b>{kpis.incidentes}</b>
                {kpis.incidentes > 0 && (
                  <span className="marca crit">
                    <TrendingUp size={13} />
                  </span>
                )}
              </div>
              <span>Con incidente de seguridad</span>
            </div>
            <div className="kpi">
              <div className="kpi-top">
                <b>{kpis.confianza === null ? '—' : kpis.confianza.toFixed(2)}</b>
                {kpis.confianza !== null && (
                  <span className={`marca ${kpis.confianza >= 0.7 ? 'ok' : 'warn'}`}>
                    <ArrowUpRight size={13} />
                  </span>
                )}
              </div>
              <span>Confianza promedio</span>
            </div>
            <div className="kpi">
              <div className="kpi-top">
                <b>{kpis.escalados}</b>
                {kpis.escalados > 0 && (
                  <span className="marca warn">
                    <AlertTriangle size={13} />
                  </span>
                )}
              </div>
              <span>Escalados a un analista</span>
            </div>
            <div className="kpi">
              <div className="kpi-top">
                <b style={{ whiteSpace: 'nowrap' }}>
                  {kpis.revisadas}
                  <span className="faint" style={{ fontSize: 14, fontWeight: 400 }}>
                    {` / ${kpis.total}`}
                  </span>
                </b>
              </div>
              <span>Revisadas por un humano</span>
            </div>
          </div>

          <section className="panel" style={{ marginTop: 18 }}>
            <div className="panel-head con-accion">
              <div>
                <h2>Actividad de análisis</h2>
                <p>Ejecuciones por día, sobre las últimas {corridas.length} registradas.</p>
              </div>
              <div className="segmented">
                {RANGOS.map((r) => (
                  <button
                    key={r.id}
                    className={rango === r.id ? 'is-active' : ''}
                    onClick={() => setRango(r.id)}
                  >
                    {r.etiqueta}
                  </button>
                ))}
              </div>
            </div>
            <div className="panel-body">
              <AreaChart
                puntos={serie}
                vacio="Hace falta actividad en al menos dos días distintos para trazar la serie."
              />
            </div>
          </section>

          <section className="panel">
            <div className="panel-head con-accion">
              <div>
                <h2>Últimas ejecuciones</h2>
                <p>Clic en una fila para abrir su informe.</p>
              </div>
              <button className="btn btn-quiet" onClick={() => onNavegar('historial')}>
                Ver todas
              </button>
            </div>
            <div className="panel-body tight" style={{ marginTop: 18 }}>
              <div className="table-scroll">
                <table className="table">
                  <thead>
                    <tr>
                      <th>Archivo</th>
                      <th>Formato</th>
                      <th style={{ textAlign: 'right' }}>Confianza</th>
                      <th>Veredicto</th>
                    </tr>
                  </thead>
                  <tbody>
                    {recientes.map((c) => (
                      <tr
                        key={c.job_id}
                        className="clickable"
                        tabIndex={0}
                        onClick={() => onAbrir(c)}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter' || e.key === ' ') {
                            e.preventDefault()
                            onAbrir(c)
                          }
                        }}
                      >
                        <td className="mono">{c.archivo_origen ?? '—'}</td>
                        <td className="mono nowrap" style={{ color: 'var(--text-muted)' }}>
                          {(c.formato_detectado ?? '—').toUpperCase().replace(/_/g, '-')}
                        </td>
                        <td className="num">{c.confianza === null ? '—' : c.confianza.toFixed(2)}</td>
                        <td>
                          {c.estado === 'error' ? (
                            <span className="chip crit">error</span>
                          ) : c.hay_incidente ? (
                            <span className="chip crit">incidente</span>
                          ) : c.hay_anomalia ? (
                            <span className="chip warn">anomalía</span>
                          ) : (
                            <span className="chip ok">limpio</span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </section>
        </>
      )}
    </AppShell>
  )
}
