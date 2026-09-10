'use client'

import { useEffect, useRef, useState } from 'react'
import {
  Activity,
  AlertTriangle,
  Check,
  Clock3,
  FileText,
  Info,
  RotateCcw,
} from 'lucide-react'

import { Header, type Vista } from '@/components/header'
import { obtenerCorrida, urlDelStream, type Corrida, type EventoSse, type ResumenLote } from '@/lib/api'
import {
  NODOS,
  aplicarNodo,
  avanceInicial,
  completarTodo,
  nodosEjecutados,
  progreso,
  type Avance,
} from '@/lib/nodos'

export function AnalysisView({
  jobId,
  nombreArchivo,
  onCompletar,
  onReintentar,
  onNavegar,
}: {
  jobId: string
  nombreArchivo: string
  onCompletar: (corrida: Corrida) => void
  onReintentar: () => void
  onNavegar: (vista: Vista) => void
}) {
  const [avance, setAvance] = useState<Avance>(avanceInicial)
  const [resumen, setResumen] = useState<ResumenLote | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [elapsed, setElapsed] = useState(0)
  const inicio = useRef(Date.now())

  useEffect(() => {
    const timer = window.setInterval(
      () => setElapsed(Math.floor((Date.now() - inicio.current) / 1000)),
      1000,
    )
    return () => window.clearInterval(timer)
  }, [])

  useEffect(() => {
    const fuente = new EventSource(urlDelStream(jobId))
    // El backend no emite `final` después de un `error`, así que este flag
    // distingue "terminó" de "se cortó la conexión".
    let cerrado = false

    fuente.onmessage = (mensaje) => {
      const evento: EventoSse = JSON.parse(mensaje.data)

      if (evento.tipo === 'inicio') {
        setResumen(evento.resumen)
        return
      }
      if (evento.tipo === 'nodo') {
        setAvance((previo) => aplicarNodo(previo, evento.nombre))
        return
      }
      if (evento.tipo === 'error') {
        cerrado = true
        setError(evento.mensaje)
        fuente.close()
        return
      }
      if (evento.tipo === 'final') {
        cerrado = true
        setAvance(completarTodo)
        fuente.close()
        // El evento `final` no trae el job_id ni los datos del archivo: se
        // pide la fila del historial, que es el mismo shape que consume el
        // detalle del historial. Así la vista de informe tiene una sola
        // forma de entrada.
        obtenerCorrida(jobId)
          .then(onCompletar)
          .catch((e) => setError(e instanceof Error ? e.message : String(e)))
      }
    }

    fuente.onerror = () => {
      if (!cerrado) {
        setError(
          'Se perdió la conexión con el servidor mientras se ejecutaba el análisis. ' +
            'El análisis puede haber seguido corriendo: revisá el historial antes de reintentar.',
        )
      }
      fuente.close()
    }

    return () => fuente.close()
  }, [jobId, onCompletar])

  const pct = progreso(avance)
  const ejecutados = nodosEjecutados(avance)

  return (
    <main className="shell analysis-shell">
      <Header vista="analysis" onNavegar={onNavegar} />
      <section className="analysis-content">
        <div className="analysis-heading">
          <div>
            <div className="eyebrow">
              {error ? (
                <>
                  <AlertTriangle size={14} /> ANÁLISIS INTERRUMPIDO
                </>
              ) : (
                <>
                  <span className="live-dot" /> ANÁLISIS EN VIVO
                </>
              )}
            </div>
            <h1>{error ? 'El análisis se interrumpió' : 'Analizando tu archivo'}</h1>
            <p className="file-context">
              <FileText size={15} /> {nombreArchivo}
            </p>
          </div>
          <div className="elapsed">
            <Clock3 size={17} />
            <span>Tiempo transcurrido</span>
            <strong>
              {String(Math.floor(elapsed / 60)).padStart(2, '0')}:
              {String(elapsed % 60).padStart(2, '0')}
            </strong>
          </div>
        </div>

        {error && (
          <div className="error-banner" role="alert">
            <div className="error-icon">
              <AlertTriangle size={19} />
            </div>
            <div>
              <strong>No se pudo completar el análisis</strong>
              <p>{error}</p>
            </div>
            <button className="secondary-button" onClick={onReintentar}>
              <RotateCcw size={16} /> Reintentar
            </button>
          </div>
        )}

        <div className="progress-strip">
          <div>
            <span>Progreso del análisis</span>
            <strong>{pct}%</strong>
          </div>
          <div className="progress-track">
            <div className={error ? 'is-stopped' : ''} style={{ width: `${pct}%` }} />
          </div>
        </div>

        <div className="analysis-grid">
          <div className="agent-flow">
            <div className="flow-header">
              <span>Flujo de análisis</span>
              <span className="flow-count">
                {ejecutados} de {NODOS.length} agentes ejecutados
              </span>
            </div>
            <div className="agents-list">
              {NODOS.map((nodo, index) => {
                const paso = avance[nodo.nombre]
                const activo = paso.estado === 'activo'
                const hecho = paso.estado === 'completado'
                // Una revisita se anuncia distinto: "Procesando" daría a
                // entender que es la primera pasada.
                const revisita = activo && paso.visitas > 1
                return (
                  <div
                    className={`agent-row ${hecho ? 'done' : ''} ${activo ? 'current' : ''}`}
                    key={nodo.nombre}
                  >
                    <div className="agent-node">
                      {hecho ? (
                        <Check size={16} />
                      ) : activo ? (
                        <span className="node-pulse" />
                      ) : (
                        <span>{String(index + 1).padStart(2, '0')}</span>
                      )}
                    </div>
                    <div className="agent-copy">
                      <div className="agent-title">
                        <strong>{nodo.titulo}</strong>
                        {hecho && <span className="complete-label">Completado</span>}
                        {activo && !revisita && <span className="active-label">Procesando</span>}
                        {revisita && <span className="revisit-label">Revisando de nuevo</span>}
                        {paso.visitas > 1 && (
                          <span className="visit-count">×{paso.visitas}</span>
                        )}
                        {nodo.opcional && paso.visitas === 0 && !error && (
                          <span className="optional-label">Solo si se necesita</span>
                        )}
                      </div>
                      {activo && <p>{nodo.descripcion}</p>}
                    </div>
                    {index < NODOS.length - 1 && <div className="flow-line" />}
                  </div>
                )
              })}
            </div>
          </div>
          <aside className="analysis-aside">
            <div className="aside-card">
              <div className="aside-card-title">
                <Activity size={17} /> Lectura del sistema
              </div>
              <p>
                Mientras NODEX trabaja, puede seguir cada etapa del análisis. No necesita
                interpretar códigos: le explicaremos cada hallazgo en un lenguaje claro.
              </p>
              <div className="aside-note">
                <Info size={15} />
                <span>
                  Algunas etapas se ejecutan solo si el análisis las necesita, y otras pueden
                  repetirse para revisar un resultado.
                </span>
              </div>
            </div>
            <div className="aside-card compact">
              <span className="mini-label">ARCHIVO EN PROCESO</span>
              <strong>{nombreArchivo}</strong>
              <span>
                Formato detectado:{' '}
                {resumen?.formato_detectado
                  ? resumen.formato_detectado.toUpperCase().replace(/_/g, '-')
                  : 'detectando...'}
              </span>
            </div>
            {resumen && (
              <div className="aside-card compact">
                <span className="mini-label">LOTE AGREGADO</span>
                <strong>{resumen.total_lineas?.toLocaleString('es')} líneas</strong>
                <span>{resumen.n_ips_distintas} IP(s) distinta(s)</span>
              </div>
            )}
          </aside>
        </div>
      </section>
    </main>
  )
}
