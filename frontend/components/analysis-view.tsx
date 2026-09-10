'use client'

import { useEffect, useRef, useState } from 'react'
import { AlertTriangle, Check, FileText, Info, RotateCcw } from 'lucide-react'

import { AppShell, Sep, type Vista } from '@/components/app-shell'
import {
  obtenerCorrida,
  urlDelStream,
  type Corrida,
  type EventoSse,
  type ResumenLote,
} from '@/lib/api'
import {
  NODOS,
  aplicarNodo,
  avanceInicial,
  completarTodo,
  nodosEjecutados,
  progreso,
  type Avance,
} from '@/lib/nodos'

function reloj(segundos: number) {
  return `${String(Math.floor(segundos / 60)).padStart(2, '0')}:${String(segundos % 60).padStart(2, '0')}`
}

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
      } else if (evento.tipo === 'nodo') {
        setAvance((previo) => aplicarNodo(previo, evento.nombre))
      } else if (evento.tipo === 'error') {
        cerrado = true
        setError(evento.mensaje)
        fuente.close()
      } else if (evento.tipo === 'final') {
        cerrado = true
        setAvance(completarTodo)
        fuente.close()
        // El evento `final` no trae el job_id ni los datos del archivo: se
        // pide la fila del historial, el mismo shape que consume el detalle.
        // Así la vista de informe tiene una sola forma de entrada.
        obtenerCorrida(jobId)
          .then(onCompletar)
          .catch((e) => setError(e instanceof Error ? e.message : String(e)))
      }
    }

    fuente.onerror = () => {
      if (!cerrado) {
        setError(
          'Se perdió la conexión con el servidor durante la ejecución. El análisis puede ' +
            'haber continuado: revisá el historial antes de reintentar.',
        )
      }
      fuente.close()
    }

    return () => fuente.close()
  }, [jobId, onCompletar])

  const pct = progreso(avance)
  const ejecutados = nodosEjecutados(avance)

  return (
    <AppShell
      vista="analysis"
      onNavegar={onNavegar}
      ruta={
        <>
          <span>Análisis</span>
          <Sep />
          <span className="mono">{nombreArchivo}</span>
        </>
      }
      acciones={
        <>
          <span className="chip mono">{reloj(elapsed)}</span>
          {error ? (
            <span className="chip crit">interrumpido</span>
          ) : (
            <span className="chip info">en ejecución</span>
          )}
        </>
      }
    >
      <div className="view-head">
        <div>
          <h1>{error ? 'Ejecución interrumpida' : 'Ejecución en curso'}</h1>
          <p>
            {ejecutados} de {NODOS.length} agentes ejecutados · {pct}% del recorrido
          </p>
        </div>
      </div>

      {error && (
        <div className="notice-block" role="alert">
          <div className="modal-icon" style={{ margin: 0, color: 'var(--crit)', background: 'var(--crit-bg)', borderColor: 'var(--crit-line)' }}>
            <AlertTriangle size={16} />
          </div>
          <div>
            <strong>No se pudo completar el análisis</strong>
            <p>{error}</p>
          </div>
          <button className="btn" onClick={onReintentar}>
            <RotateCcw size={14} /> Reintentar
          </button>
        </div>
      )}

      <div className="grid-2">
        <section className="panel">
          <div className="panel-head">
            <div>
              <span className="label">Grafo multiagente</span>
              <h2>Recorrido de la ejecución</h2>
            </div>
            <div className="meter">
              <div className={`meter-track ${error ? 'crit' : ''}`}>
                <div style={{ width: `${pct}%` }} />
              </div>
              <b>{pct}%</b>
            </div>
          </div>
          <div className="panel-body">
            <div className="flow">
              {NODOS.map((nodo, index) => {
                const paso = avance[nodo.nombre]
                const activo = paso.estado === 'activo'
                const hecho = paso.estado === 'completado'
                // Una revisita se anuncia distinto: "ejecutando" daría a
                // entender que es la primera pasada.
                const revisita = activo && paso.visitas > 1
                return (
                  <div
                    className={`step ${hecho ? 'done' : ''} ${activo ? 'active' : ''}`}
                    key={nodo.nombre}
                  >
                    <div className="step-node">
                      {hecho ? (
                        <Check size={13} />
                      ) : activo ? (
                        <span className="step-pulse" />
                      ) : (
                        String(index + 1).padStart(2, '0')
                      )}
                    </div>
                    <div className="step-copy">
                      <div className="step-title">
                        <strong>{nodo.titulo}</strong>
                        {hecho && <span className="chip ok">completado</span>}
                        {activo && !revisita && <span className="chip info">ejecutando</span>}
                        {revisita && <span className="chip warn">revisando de nuevo</span>}
                        {paso.visitas > 1 && <span className="step-visits">×{paso.visitas}</span>}
                        {nodo.opcional && paso.visitas === 0 && !error && (
                          <span className="chip">condicional</span>
                        )}
                      </div>
                      {activo && <p>{nodo.descripcion}</p>}
                    </div>
                    {index < NODOS.length - 1 && <div className="step-line" />}
                  </div>
                )
              })}
            </div>
          </div>
        </section>

        <div>
          <section className="panel">
            <div className="panel-head">
              <div>
                <span className="label">Lote</span>
                <h2>Preprocesamiento</h2>
              </div>
            </div>
            <div className="panel-body">
              <div className="facts">
                <div>
                  <dt>Archivo</dt>
                  <dd className="mono">{nombreArchivo}</dd>
                </div>
                <div>
                  <dt>Formato detectado</dt>
                  <dd className="mono">
                    {resumen?.formato_detectado
                      ? resumen.formato_detectado.toUpperCase().replace(/_/g, '-')
                      : 'detectando…'}
                  </dd>
                </div>
                <div>
                  <dt>Registros</dt>
                  <dd className="mono">{resumen?.total_lineas?.toLocaleString('es') ?? '—'}</dd>
                </div>
                <div>
                  <dt>IPs distintas</dt>
                  <dd className="mono">{resumen?.n_ips_distintas ?? '—'}</dd>
                </div>
                <div>
                  <dt>Ventana temporal</dt>
                  <dd className="mono">
                    {resumen?.ventana_temporal?.inicio && resumen?.ventana_temporal?.fin
                      ? `${resumen.ventana_temporal.inicio} — ${resumen.ventana_temporal.fin}`
                      : '—'}
                  </dd>
                </div>
              </div>
            </div>
          </section>

          <section className="panel">
            <div className="panel-body">
              <div className="notice info">
                <Info size={15} />
                <span>
                  Los pasos condicionales se ejecutan solo si el análisis los requiere, y
                  algunos pueden repetirse para revisar un resultado. El recorrido no es lineal.
                </span>
              </div>
            </div>
          </section>
        </div>
      </div>
    </AppShell>
  )
}
