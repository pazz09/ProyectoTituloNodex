'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import {
  AlertTriangle,
  ArrowUp,
  BookMarked,
  CheckCircle2,
  FileText,
  Gauge,
  Layers,
  Loader2,
  Paperclip,
  RotateCcw,
  ScanSearch,
  ShieldCheck,
  Sparkles,
  Terminal,
  Upload,
  X,
} from 'lucide-react'

import { AppShell, type Vista } from '@/components/app-shell'
import {
  MAX_BYTES,
  obtenerCorrida,
  subirArchivo,
  urlDelStream,
  type Corrida,
  type EventoSse,
  type ResumenLote,
} from '@/lib/api'
import { NODOS, type NombreNodo } from '@/lib/nodos'

const EXTENSIONES = /\.(log|txt|csv)$/i
const LIMITE_LEGIBLE = `${Math.round(MAX_BYTES / 1024 / 1024)} MB`

function pesoLegible(bytes: number) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

function hora() {
  return new Date().toLocaleTimeString('es', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

/** Un mensaje del hilo. El contenido lo arma el componente. */
type Mensaje =
  | { rol: 'usuario'; id: string; nombre: string; peso: number }
  | { rol: 'inicio'; id: string; hora: string; resumen: ResumenLote }
  | { rol: 'nodo'; id: string; hora: string; nodo: NombreNodo; visita: number; detalle: Record<string, unknown> }
  | { rol: 'cierre'; id: string; hora: string; corrida: Corrida }
  | { rol: 'error'; id: string; hora: string; mensaje: string }

const ICONOS: Record<NombreNodo, typeof Sparkles> = {
  agente_analista_triage: ScanSearch,
  agente_selector_herramientas: Layers,
  tool_consultar_rag: BookMarked,
  tool_consultar_cve: ShieldCheck,
  agente_ingeniero_mitigacion: Terminal,
  tool_validar_comandos: CheckCircle2,
  agente_auditor_final: Gauge,
}

/** Barras proporcionales al máximo de la serie, como en la referencia. */
function Barras({ datos, tope = 4 }: { datos?: Record<string, number>; tope?: number }) {
  const filas = Object.entries(datos ?? {}).sort((a, b) => b[1] - a[1]).slice(0, tope)
  if (filas.length === 0) return null
  const max = filas[0][1] || 1
  return (
    <div className="bars">
      {filas.map(([nombre, n]) => (
        <div className="bar-row" key={nombre}>
          <div>
            <strong>{nombre.replace(/_/g, ' ')}</strong>
            <b>{n.toLocaleString('es')}</b>
          </div>
          <div className="bar-track">
            <div style={{ width: `${Math.max(2, (n / max) * 100)}%` }} />
          </div>
        </div>
      ))}
    </div>
  )
}

/**
 * Cuerpo del mensaje de cada nodo, armado con lo que ese nodo devolvió de
 * verdad al estado (el `detalle` del evento SSE). Nada de este texto lo
 * inventa la interfaz: la narración es el encuadre, el contenido es el dato.
 */
function CuerpoNodo({ nodo, detalle, visita }: { nodo: NombreNodo; detalle: Record<string, unknown>; visita: number }) {
  const lista = (v: unknown) => (Array.isArray(v) ? v : [])

  if (nodo === 'agente_analista_triage') {
    const diagnostico = String(detalle.diagnostico ?? '')
    // En la primera pasada el nodo puede devolver SOLO `necesita_rag: true`:
    // decide que le falta contexto y sale sin diagnosticar. Ahí lo honesto es
    // decir eso, no "no se registró un diagnóstico", que se lee como una
    // falla (ver src/agents/agente_analista_triage.py, el return de la línea
    // final del nodo).
    if (!diagnostico) {
      return (
        <p>
          {detalle.necesita_rag === true
            ? 'Antes de diagnosticar necesito ver si hay casos anteriores parecidos. Voy a consultar la memoria.'
            : 'Esta pasada no produjo un diagnóstico.'}
        </p>
      )
    }
    return (
      <>
        {visita > 1 && (
          <p className="faint">
            Con los precedentes y las técnicas recuperadas, este es el diagnóstico.
          </p>
        )}
        <p>{diagnostico}</p>
      </>
    )
  }

  if (nodo === 'tool_consultar_rag') {
    const precedentes = lista(detalle.contexto_rag)
    const tecnicas = lista(detalle.tecnicas_mitre) as { meta: { technique_id: string; name: string } }[]
    return (
      <>
        <p>
          {precedentes.length === 0
            ? 'No hay casos anteriores parecidos en la memoria.'
            : `Encontré ${precedentes.length} caso(s) anterior(es) con una firma parecida.`}
          {' '}
          {tecnicas.length === 0
            ? 'Ninguna técnica de ATT&CK superó el umbral de similitud.'
            : `Recuperé ${tecnicas.length} técnica(s) de MITRE ATT&CK relacionadas.`}
        </p>
        {tecnicas.length > 0 && (
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            {tecnicas.map((t) => (
              <span className="chip info mono" key={t.meta.technique_id}>
                {t.meta.technique_id} · {t.meta.name}
              </span>
            ))}
          </div>
        )}
      </>
    )
  }

  if (nodo === 'agente_selector_herramientas') {
    const razon = String(detalle.razon_seleccion ?? '')
    return (
      <>
        <p>
          {detalle.usar_cve
            ? 'Conviene consultar vulnerabilidades conocidas.'
            : 'No hace falta consultar vulnerabilidades para este lote.'}
        </p>
        {razon && <p className="faint">{razon}</p>}
      </>
    )
  }

  if (nodo === 'tool_consultar_cve') {
    const cves = lista(detalle.cves_encontrados)
    return (
      <p>
        {cves.length === 0
          ? 'La NVD no devolvió vulnerabilidades para los servicios detectados.'
          : `La NVD devolvió ${cves.length} vulnerabilidad(es) relacionadas con los servicios detectados.`}
      </p>
    )
  }

  if (nodo === 'agente_ingeniero_mitigacion') {
    const comandos = lista(detalle.comandos_mitigacion) as string[]
    const intento = Number(detalle.intentos_correccion ?? 1)
    return (
      <>
        <p>
          {intento > 1
            ? `Rediseñé los comandos (intento ${intento}) después del rechazo del validador.`
            : `Propongo ${comandos.length} comando(s) de contención.`}
        </p>
        {comandos.length > 0 && (
          <div className="cmds" style={{ margin: '0 -20px -18px' }}>
            {comandos.map((c, i) => (
              <div key={`${i}-${c}`}>
                <span className="idx">{String(i + 1).padStart(2, '0')}</span>
                <code>{c}</code>
              </div>
            ))}
          </div>
        )}
      </>
    )
  }

  if (nodo === 'tool_validar_comandos') {
    const motivos = lista(detalle.motivos_rechazo) as string[]
    return (
      <>
        <p>
          {detalle.comandos_validos
            ? 'Los comandos pasaron la validación: ningún patrón destructivo y todos los binarios están en la lista permitida.'
            : 'Rechacé los comandos propuestos.'}
        </p>
        {motivos.length > 0 && (
          <div className="notice warn">
            <AlertTriangle size={15} />
            <span>{motivos.join(' · ')}</span>
          </div>
        )}
      </>
    )
  }

  // agente_auditor_final
  const confianza = Number(detalle.confianza ?? 0)
  return (
    <>
      <p>{String(detalle.evaluacion_auditor ?? 'Sin evaluación registrada.')}</p>
      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center' }}>
        <div className="meter">
          <div className="bar-track">
            <div style={{ width: `${Math.round(confianza * 100)}%` }} />
          </div>
          <b>{confianza.toFixed(2)}</b>
        </div>
        <span className={detalle.hay_anomalia ? 'chip warn' : 'chip'}>
          anomalía {detalle.hay_anomalia ? 'sí' : 'no'}
        </span>
        <span className={detalle.hay_incidente ? 'chip crit' : 'chip'}>
          incidente {detalle.hay_incidente ? 'sí' : 'no'}
        </span>
      </div>
    </>
  )
}

export function ConversacionView({
  onAbrirInforme,
  onNavegar,
}: {
  onAbrirInforme: (corrida: Corrida) => void
  onNavegar: (vista: Vista) => void
}) {
  const [archivo, setArchivo] = useState<File | null>(null)
  const [dragging, setDragging] = useState(false)
  const [mensajes, setMensajes] = useState<Mensaje[]>([])
  const [jobId, setJobId] = useState<string | null>(null)
  const [corriendo, setCorriendo] = useState(false)
  const [errorCarga, setErrorCarga] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const finRef = useRef<HTMLDivElement>(null)
  const visitas = useRef<Record<string, number>>({})

  useEffect(() => {
    finRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [mensajes])

  const elegir = useCallback((file?: File) => {
    setErrorCarga(null)
    if (!file) return
    if (!EXTENSIONES.test(file.name)) {
      setErrorCarga(`"${file.name}" no es un formato compatible. Se esperan .log, .txt o .csv.`)
      return
    }
    // Se valida acá además del backend para no gastar la subida de un archivo
    // que igual sería rechazado con 413.
    if (file.size > MAX_BYTES) {
      setErrorCarga(`El archivo pesa ${pesoLegible(file.size)} y el máximo es ${LIMITE_LEGIBLE}.`)
      return
    }
    if (file.size === 0) {
      setErrorCarga('El archivo está vacío.')
      return
    }
    setArchivo(file)
  }, [])

  const enviar = async () => {
    if (!archivo || corriendo) return
    setCorriendo(true)
    setErrorCarga(null)
    visitas.current = {}
    setMensajes([{ rol: 'usuario', id: 'u0', nombre: archivo.name, peso: archivo.size }])

    let id: string
    try {
      const r = await subirArchivo(archivo)
      id = r.job_id
      setJobId(id)
    } catch (e) {
      setErrorCarga(e instanceof Error ? e.message : String(e))
      setMensajes([])
      setCorriendo(false)
      return
    }

    setArchivo(null)
    const fuente = new EventSource(urlDelStream(id))
    // El backend no emite `final` después de un `error`, así que este flag
    // distingue "terminó" de "se cortó la conexión".
    let cerrado = false

    fuente.onmessage = (m) => {
      const ev: EventoSse = JSON.parse(m.data)

      if (ev.tipo === 'inicio') {
        setMensajes((prev) => [...prev, { rol: 'inicio', id: 'inicio', hora: hora(), resumen: ev.resumen }])
      } else if (ev.tipo === 'nodo') {
        const visita = (visitas.current[ev.nombre] ?? 0) + 1
        visitas.current[ev.nombre] = visita
        setMensajes((prev) => [
          ...prev,
          {
            rol: 'nodo',
            id: `${ev.nombre}-${visita}`,
            hora: hora(),
            nodo: ev.nombre as NombreNodo,
            visita,
            detalle: ev.detalle,
          },
        ])
      } else if (ev.tipo === 'error') {
        cerrado = true
        setMensajes((prev) => [...prev, { rol: 'error', id: 'err', hora: hora(), mensaje: ev.mensaje }])
        setCorriendo(false)
        fuente.close()
      } else if (ev.tipo === 'final') {
        cerrado = true
        fuente.close()
        // El evento `final` no trae el job_id ni los datos del archivo: se
        // pide la fila del historial, el mismo shape que consume el informe.
        obtenerCorrida(id)
          .then((c) =>
            setMensajes((prev) => [...prev, { rol: 'cierre', id: 'cierre', hora: hora(), corrida: c }]),
          )
          .catch((e) =>
            setMensajes((prev) => [
              ...prev,
              { rol: 'error', id: 'err', hora: hora(), mensaje: e instanceof Error ? e.message : String(e) },
            ]),
          )
          .finally(() => setCorriendo(false))
      }
    }

    fuente.onerror = () => {
      if (!cerrado) {
        setMensajes((prev) => [
          ...prev,
          {
            rol: 'error',
            id: 'err',
            hora: hora(),
            mensaje:
              'Se perdió la conexión con el servidor durante la ejecución. El análisis puede haber continuado: revisá las ejecuciones antes de reintentar.',
          },
        ])
        setCorriendo(false)
      }
      fuente.close()
    }
  }

  const reiniciar = () => {
    setMensajes([])
    setJobId(null)
    setArchivo(null)
    setErrorCarga(null)
    visitas.current = {}
  }

  // El nodo que está corriendo es el último que emitió: mientras no llegue el
  // cierre, se muestra el indicador de actividad.
  const esperando = corriendo && mensajes.length > 0

  return (
    <AppShell grupo="analisis" onNavegar={onNavegar} sinPadding>
      <div className="chat">
        <div className="chat-cabecera">
          <div className="view-head" style={{ marginBottom: 0 }}>
            <h1>Multiagente NODEX</h1>
            <p>
              {mensajes.length === 0
                ? 'Adjunta un lote de registros y el grafo de 7 agentes lo va a analizar paso a paso.'
                : 'Cada mensaje es lo que ese agente devolvió al estado del grafo.'}
            </p>
          </div>
        </div>
        <div className="chat-hilo">
          {mensajes.length === 0 && (
            <div className="msg msg-agente">
              <div className="msg-cabecera">
                <span className="icono">
                  <Sparkles size={15} />
                </span>
                <strong>NODEX</strong>
              </div>
              <div className="msg-cuerpo">
                <p>
                  Ingresa tu archivo de registros en el campo de abajo. Formatos compatibles: .log,
                  .txt y .csv, hasta {LIMITE_LEGIBLE}.
                </p>
                <p className="faint">
                  El preprocesamiento es determinístico y corre local. Solo salen a internet las
                  consultas de reputación de IPs y de vulnerabilidades.
                </p>
              </div>
            </div>
          )}

          {mensajes.map((m) => {
            if (m.rol === 'usuario') {
              return (
                <div className="msg msg-usuario" key={m.id}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                    <FileText size={15} />
                    <span className="mono">{m.nombre}</span>
                  </div>
                  <div className="mono" style={{ fontSize: 12, marginTop: 4 }}>
                    {pesoLegible(m.peso)} · analizá este lote
                  </div>
                </div>
              )
            }

            if (m.rol === 'inicio') {
              const r = m.resumen
              const ventana = r.ventana_temporal
              return (
                <div className="msg msg-agente" key={m.id}>
                  <div className="msg-cabecera">
                    <span className="icono">
                      <Layers size={15} />
                    </span>
                    <strong>Preprocesamiento</strong>
                    <time>{m.hora}</time>
                  </div>
                  <div className="msg-cuerpo">
                    <p>
                      Reconocí el lote como <strong className="mono">{(r.formato_detectado ?? '—').toUpperCase().replace(/_/g, '-')}</strong>:{' '}
                      {r.total_lineas?.toLocaleString('es')} registros, {r.n_ips_distintas} IP(s) distinta(s)
                      {r.n_usuarios_distintos ? `, ${r.n_usuarios_distintos} actor(es)` : ''}
                      {ventana?.inicio && ventana?.fin ? `, entre ${ventana.inicio} y ${ventana.fin}` : ''}.
                    </p>
                  </div>
                  <div className="msg-bloque">
                    <div className="msg-bloque-titulo">
                      <Layers size={13} /> Distribución por servicio
                    </div>
                    <Barras datos={r.servicios} />
                  </div>
                  <div className="msg-bloque">
                    <div className="msg-bloque-titulo">
                      <ScanSearch size={13} /> Tipos de evento
                    </div>
                    <Barras datos={r.eventos} />
                  </div>
                </div>
              )
            }

            if (m.rol === 'nodo') {
              const meta = NODOS.find((n) => n.nombre === m.nodo)
              const Icono = ICONOS[m.nodo] ?? Sparkles
              return (
                <div className="msg msg-agente" key={m.id}>
                  <div className="msg-cabecera">
                    <span className="icono">
                      <Icono size={15} />
                    </span>
                    <strong>{meta?.titulo ?? m.nodo}</strong>
                    {m.visita > 1 && <span className="chip warn">revisión {m.visita}</span>}
                    <time>{m.hora}</time>
                  </div>
                  <div className="msg-cuerpo">
                    <CuerpoNodo nodo={m.nodo} detalle={m.detalle} visita={m.visita} />
                  </div>
                </div>
              )
            }

            if (m.rol === 'error') {
              return (
                <div className="msg msg-agente" key={m.id} style={{ borderColor: 'var(--crit-line)' }}>
                  <div className="msg-cabecera">
                    <span className="icono" style={{ color: 'var(--crit)' }}>
                      <AlertTriangle size={15} />
                    </span>
                    <strong>El análisis se interrumpió</strong>
                    <time>{m.hora}</time>
                  </div>
                  <div className="msg-cuerpo">
                    <p>{m.mensaje}</p>
                    <button className="btn" onClick={reiniciar}>
                      <RotateCcw size={14} /> Empezar de nuevo
                    </button>
                  </div>
                </div>
              )
            }

            // cierre
            const c = m.corrida
            return (
              <div className="msg msg-agente" key={m.id}>
                <div className="msg-cabecera">
                  <span className="icono">
                    <FileText size={15} />
                  </span>
                  <strong>Informe listo</strong>
                  <time>{m.hora}</time>
                </div>
                <div className="msg-cuerpo">
                  <p>
                    Terminé el análisis. El informe reúne el diagnóstico, la evidencia, la secuencia
                    temporal, las técnicas de ATT&amp;CK y la mitigación propuesta.
                  </p>
                  <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
                    <button className="btn btn-primary" onClick={() => onAbrirInforme(c)}>
                      <FileText size={14} /> Ver el informe
                    </button>
                    <button className="btn" onClick={reiniciar}>
                      <RotateCcw size={14} /> Analizar otro lote
                    </button>
                  </div>
                </div>
              </div>
            )
          })}

          {esperando && (
            <div className="msg msg-agente pendiente">
              <div className="msg-cabecera">
                <span className="icono">
                  <Sparkles size={15} />
                </span>
                <strong>Analizando</strong>
              </div>
              <div className="msg-cuerpo">
                <div className="escribiendo">
                  <i />
                  <i />
                  <i />
                </div>
              </div>
            </div>
          )}

          <div ref={finRef} />
        </div>

        <div className="compositor-zona">
          <div className="compositor-caja">
          {errorCarga && (
            <div className="notice" role="alert" style={{ marginBottom: 12 }}>
              <AlertTriangle size={15} />
              <span>{errorCarga}</span>
            </div>
          )}
          {/* La zona entera es el selector de archivo: hacer clic en cualquier
              parte abre el diálogo, salvo cuando ya hay uno elegido o el
              análisis está corriendo. */}
          <div
            className={`compositor ${dragging ? 'dragging' : ''} ${archivo ? 'con-archivo' : ''} ${corriendo ? 'inactivo' : ''}`}
            role={archivo || corriendo ? undefined : 'button'}
            tabIndex={archivo || corriendo ? undefined : 0}
            onClick={() => !archivo && !corriendo && inputRef.current?.click()}
            onKeyDown={(e) => {
              if ((e.key === 'Enter' || e.key === ' ') && !archivo && !corriendo) {
                e.preventDefault()
                inputRef.current?.click()
              }
            }}
            onDragOver={(e) => {
              e.preventDefault()
              if (!corriendo) setDragging(true)
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={(e) => {
              e.preventDefault()
              setDragging(false)
              if (!corriendo) elegir(e.dataTransfer.files[0])
            }}
          >
            <input
              ref={inputRef}
              type="file"
              accept=".log,.txt,.csv"
              hidden
              onChange={(e) => elegir(e.target.files?.[0])}
            />

            {archivo ? (
              <div className="compositor-archivo">
                <div className="compositor-accion">
                  <span className="icono">
                    <FileText size={16} />
                  </span>
                </div>
                <div>
                  <strong>{archivo.name}</strong>
                  <span>{pesoLegible(archivo.size)} · listo para analizar</span>
                </div>
                <button
                  className="btn btn-quiet"
                  aria-label="Quitar archivo"
                  disabled={corriendo}
                  onClick={(e) => {
                    e.stopPropagation()
                    setArchivo(null)
                  }}
                >
                  <X size={15} />
                </button>
              </div>
            ) : (
              <div className="compositor-accion">
                <span className="icono">
                  {corriendo ? <Loader2 size={16} className="spin" /> : <Upload size={16} />}
                </span>
                <div>
                  <strong>
                    {corriendo ? (
                      'Analizando el lote…'
                    ) : (
                      <>
                        Arrastrá un archivo de registros o <u>elegilo desde tu equipo</u>
                      </>
                    )}
                  </strong>
                  <small>.log · .txt · .csv — hasta {LIMITE_LEGIBLE}</small>
                </div>
              </div>
            )}

            <div className="compositor-pie">
              <button
                className="btn btn-quiet"
                aria-label="Elegir archivo"
                disabled={corriendo}
                onClick={(e) => {
                  e.stopPropagation()
                  inputRef.current?.click()
                }}
              >
                <Paperclip size={15} />
              </button>
              <button
                className="btn btn-primary enviar"
                disabled={!archivo || corriendo}
                onClick={(e) => {
                  e.stopPropagation()
                  enviar()
                }}
              >
                {corriendo ? <Loader2 size={15} className="spin" /> : <ArrowUp size={15} />}
              </button>
            </div>
          </div>
          <p className="compositor-nota">
            {jobId ? (
              <span className="mono">ejecución {jobId.slice(0, 12)}</span>
            ) : (
              'El lote se procesa de forma local; no se almacena el archivo original'
            )}
          </p>
          </div>
        </div>
      </div>
    </AppShell>
  )
}
