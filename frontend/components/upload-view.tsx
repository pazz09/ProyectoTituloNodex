'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import {
  AlertTriangle,
  ArrowRight,
  FileText,
  Loader2,
  Play,
  UploadCloud,
  X,
} from 'lucide-react'

import { AppShell, type Vista } from '@/components/app-shell'
import { MAX_BYTES, listarHistorial, subirArchivo, type Corrida } from '@/lib/api'
import { NODOS } from '@/lib/nodos'

const EXTENSIONES = /\.(log|txt|csv)$/i

function pesoLegible(bytes: number) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

const LIMITE_LEGIBLE = `${Math.round(MAX_BYTES / 1024 / 1024)} MB`

function horaCorta(iso: string) {
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString('es', { dateStyle: 'short', timeStyle: 'short' })
}

export function UploadView({
  onAnalizar,
  onAbrirCorrida,
  onNavegar,
}: {
  onAnalizar: (jobId: string, nombreArchivo: string) => void
  onAbrirCorrida: (corrida: Corrida) => void
  onNavegar: (vista: Vista) => void
}) {
  // Arranca vacío: el botón queda deshabilitado hasta que se elija un
  // archivo real.
  const [archivo, setArchivo] = useState<File | null>(null)
  const [dragging, setDragging] = useState(false)
  const [subiendo, setSubiendo] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  // Las últimas corridas dan contexto operativo: la pantalla de inicio de una
  // consola muestra estado, no una presentación del producto.
  const [recientes, setRecientes] = useState<Corrida[]>([])

  useEffect(() => {
    listarHistorial(5, 0)
      .then((d) => setRecientes(d.corridas))
      .catch(() => setRecientes([]))
  }, [])

  const elegir = useCallback((file?: File) => {
    setError(null)
    if (!file) return
    if (!EXTENSIONES.test(file.name)) {
      setError(`"${file.name}" no es un formato compatible. Se esperan .log, .txt o .csv.`)
      return
    }
    // Se valida acá además del backend para no gastar la subida de un
    // archivo que igual sería rechazado con 413.
    if (file.size > MAX_BYTES) {
      setError(`El archivo pesa ${pesoLegible(file.size)} y el máximo es ${LIMITE_LEGIBLE}.`)
      return
    }
    if (file.size === 0) {
      setError('El archivo está vacío.')
      return
    }
    setArchivo(file)
  }, [])

  const analizar = async () => {
    if (!archivo) return
    setSubiendo(true)
    setError(null)
    try {
      const { job_id } = await subirArchivo(archivo)
      onAnalizar(job_id, archivo.name)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      setSubiendo(false)
    }
  }

  return (
    <AppShell
      vista="upload"
      onNavegar={onNavegar}
      ruta={
        <>
          <span>Análisis</span>
          <strong>Nueva ejecución</strong>
        </>
      }
    >
      <div className="view-head">
        <div>
          <h1>Nuevo análisis de registros</h1>
          <p>
            El lote se preprocesa de forma determinística y luego lo evalúa el grafo de 7
            agentes. Nada se envía a servicios externos salvo las consultas de reputación y
            vulnerabilidades.
          </p>
        </div>
      </div>

      <div className="grid-2">
        <section className="panel">
          <div className="panel-head">
            <div>
              <span className="label">Entrada</span>
              <h2>Archivo de log</h2>
            </div>
            <span className="panel-note">
              <UploadCloud size={13} /> .log · .txt · .csv
            </span>
          </div>
          <div className="panel-body">
            <div
              className={`drop ${dragging ? 'dragging' : ''}`}
              onDragOver={(e) => {
                e.preventDefault()
                setDragging(true)
              }}
              onDragLeave={() => setDragging(false)}
              onDrop={(e) => {
                e.preventDefault()
                setDragging(false)
                elegir(e.dataTransfer.files[0])
              }}
              onClick={() => inputRef.current?.click()}
              role="button"
              tabIndex={0}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault()
                  inputRef.current?.click()
                }
              }}
            >
              <input
                ref={inputRef}
                type="file"
                accept=".log,.txt,.csv"
                hidden
                onChange={(e) => elegir(e.target.files?.[0])}
              />
              <div className="drop-icon">
                <FileText size={18} />
              </div>
              <strong>Arrastrá el archivo o hacé clic para seleccionarlo</strong>
              <span>Un lote por ejecución</span>
              <small>máx. {LIMITE_LEGIBLE}</small>
            </div>

            {error && (
              <div className="notice" role="alert" style={{ marginTop: 13 }}>
                <AlertTriangle size={15} />
                <span>{error}</span>
              </div>
            )}

            {archivo && (
              <div className="file-row">
                <div className="file-icon">
                  <FileText size={15} />
                </div>
                <div>
                  <strong>{archivo.name}</strong>
                  <span>{pesoLegible(archivo.size)} · listo para analizar</span>
                </div>
                <button
                  className="btn btn-icon"
                  aria-label="Quitar archivo"
                  disabled={subiendo}
                  onClick={(e) => {
                    e.stopPropagation()
                    setArchivo(null)
                    setError(null)
                  }}
                >
                  <X size={14} />
                </button>
              </div>
            )}

            <div style={{ marginTop: 15, display: 'flex', justifyContent: 'flex-end' }}>
              <button
                className="btn btn-primary btn-lg"
                disabled={!archivo || subiendo}
                onClick={analizar}
              >
                {subiendo ? (
                  <>
                    <Loader2 size={15} className="spin" /> Subiendo…
                  </>
                ) : (
                  <>
                    <Play size={14} /> Ejecutar análisis
                  </>
                )}
              </button>
            </div>
          </div>
        </section>

        <section className="panel">
          <div className="panel-head">
            <div>
              <span className="label">Actividad</span>
              <h2>Últimas ejecuciones</h2>
            </div>
            {recientes.length > 0 && (
              <button className="btn btn-icon" onClick={() => onNavegar('historial')} aria-label="Ver historial completo">
                <ArrowRight size={15} />
              </button>
            )}
          </div>
          <div className="panel-body tight">
            {recientes.length === 0 ? (
              <p className="prose empty" style={{ padding: 17 }}>
                Sin ejecuciones registradas todavía.
              </p>
            ) : (
              <table className="table">
                <tbody>
                  {recientes.map((c) => (
                    <tr
                      key={c.job_id}
                      className="clickable"
                      tabIndex={0}
                      onClick={() => onAbrirCorrida(c)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') onAbrirCorrida(c)
                      }}
                    >
                      <td className="mono" style={{ whiteSpace: 'nowrap' }}>
                        {horaCorta(c.timestamp)}
                      </td>
                      <td className="mono">{c.archivo_origen ?? '—'}</td>
                      <td style={{ textAlign: 'right' }}>
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
            )}
          </div>
        </section>
      </div>

      {/* El recorrido del grafo, como referencia. Ocupa el espacio que antes
          llenaba el texto de presentación del skeleton, con información
          verificable en lugar de argumentos de venta. */}
      <section className="panel">
        <div className="panel-head">
          <div>
            <span className="label">Arquitectura</span>
            <h2>Qué hace el sistema con el lote</h2>
          </div>
          <span className="panel-note">4 agentes LLM · 3 herramientas · 3 enrutadores condicionales</span>
        </div>
        <div className="panel-body">
          <div className="pipeline">
            {NODOS.map((nodo, i) => (
              <div className="pipeline-step" key={nodo.nombre}>
                <div className="pipeline-num">{String(i + 1).padStart(2, '0')}</div>
                <div>
                  <strong>{nodo.titulo}</strong>
                  {nodo.opcional && <span className="chip">condicional</span>}
                  <p>{nodo.descripcion.replace(/\.\.\.$/, '')}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>
    </AppShell>
  )
}
