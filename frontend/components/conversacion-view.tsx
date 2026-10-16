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
  ListChecks,
  Loader2,
  RotateCcw,
  ScanSearch,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  Terminal,
  Upload,
  X,
} from 'lucide-react'

import { AppShell, type Vista } from '@/components/app-shell'
import type { EstadoAnalisis } from '@/components/use-analisis'
import { MAX_BYTES, type Corrida } from '@/lib/api'
import { NODOS, type NombreNodo } from '@/lib/nodos'

const EXTENSIONES = /\.(log|txt|csv)$/i
const LIMITE_LEGIBLE = `${Math.round(MAX_BYTES / 1024 / 1024)} MB`

function pesoLegible(bytes: number) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

const ICONOS: Record<NombreNodo, typeof Sparkles> = {
  agente_planificador: ListChecks,
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

  if (nodo === 'agente_planificador') {
    const plan = (detalle.plan ?? {}) as { objetivo?: string; pasos?: { accion: string; objetivo?: string }[] }
    const pasos = lista(plan.pasos) as { accion: string; objetivo?: string }[]
    return (
      <>
        {visita > 1 && (
          <p className="faint">La cobertura del plan anterior no alcanzó: este es el plan revisado.</p>
        )}
        <p>{plan.objetivo || 'Sin objetivo registrado.'}</p>
        {pasos.length > 0 && (
          <ul style={{ margin: '6px 0 0', paddingLeft: 18 }}>
            {pasos.map((p) => (
              <li key={p.accion}>
                <strong>{p.accion}</strong>
                {p.objetivo ? ` — ${p.objetivo}` : ''}
              </li>
            ))}
          </ul>
        )}
      </>
    )
  }

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
  const hayIncidente = Boolean(detalle.hay_incidente)
  const hayAnomalia = Boolean(detalle.hay_anomalia)
  const nivel = hayIncidente ? 'crit' : hayAnomalia ? 'warn' : 'ok'
  const titulo = hayIncidente
    ? 'Incidente de seguridad'
    : hayAnomalia
      ? 'Anomalía operativa (sin evidencia de seguridad)'
      : 'Sin anomalías'
  const IconoVeredicto = hayIncidente ? ShieldAlert : hayAnomalia ? AlertTriangle : ShieldCheck
  return (
    <>
      <div className={`verdict ${nivel}`} style={{ margin: '0 -20px 0', borderRadius: 0, borderTop: 0, borderRight: 0, borderBottom: 0 }}>
        <div className="verdict-main">
          <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <IconoVeredicto size={16} />
            <strong>{titulo}</strong>
          </span>
          <p>{detalle.requiere_revision_humana ? 'Confianza bajo el umbral: requiere revisión humana.' : 'Confianza sobre el umbral de escalamiento.'}</p>
        </div>
        <div className="verdict-meta">
          <div>
            <span className="faint" style={{ fontSize: 11.5 }}>Confianza</span>
            <div className="meter">
              <div className="bar-track">
                <div style={{ width: `${Math.round(confianza * 100)}%` }} />
              </div>
              <b>{confianza.toFixed(2)}</b>
            </div>
          </div>
          <div className="verdict-chips">
            <span className={hayAnomalia ? 'chip warn' : 'chip'}>anomalía {hayAnomalia ? 'sí' : 'no'}</span>
            <span className={hayIncidente ? 'chip crit' : 'chip'}>incidente {hayIncidente ? 'sí' : 'no'}</span>
          </div>
        </div>
      </div>
      <p>{String(detalle.evaluacion_auditor ?? 'Sin evaluación registrada.')}</p>
    </>
  )
}

/**
 * Rastreador de avance + hallazgos en vivo.
 *
 * Complementa el hilo (que hay que leer mensaje a mensaje) con una franja
 * fija arriba: en qué nodo del grafo está ahora mismo, cuáles ya pasaron, y
 * un conteo de lo que el análisis ya encontró (técnicas MITRE, CVEs, IPs
 * con mala reputación, comandos propuestos) -- para que de un vistazo, sin
 * leer nada, se note que el multiagente está avanzando y encontrando
 * evidencia real, no solo "pensando".
 */
function RastreadorGrafo({ mensajes, corriendo }: { mensajes: EstadoAnalisis['mensajes']; corriendo: boolean }) {
  const nodosVistos = new Set<NombreNodo>()
  let nodoActual: NombreNodo | null = null
  let replans = 0
  let nTecnicas = 0
  let nCves = 0
  let nComandos = 0
  let nIpsMalas = 0

  for (const m of mensajes) {
    if (m.rol === 'inicio') {
      const reputacion = (m.resumen.reputacion_ips ?? {}) as Record<string, { categoria?: string }>
      nIpsMalas = Object.values(reputacion).filter(
        (d) => d?.categoria === 'malicioso' || d?.categoria === 'sospechoso',
      ).length
    }
    if (m.rol !== 'nodo') continue
    if (m.nodo === 'agente_planificador' && nodosVistos.has('agente_planificador')) replans += 1
    nodosVistos.add(m.nodo)
    nodoActual = m.nodo
    if (m.nodo === 'tool_consultar_rag') {
      nTecnicas = (m.detalle.tecnicas_mitre as unknown[] | undefined)?.length ?? nTecnicas
    }
    if (m.nodo === 'tool_consultar_cve') {
      nCves = (m.detalle.cves_encontrados as unknown[] | undefined)?.length ?? nCves
    }
    if (m.nodo === 'agente_ingeniero_mitigacion') {
      nComandos = (m.detalle.comandos_mitigacion as unknown[] | undefined)?.length ?? nComandos
    }
  }

  if (nodosVistos.size === 0) return null

  const hallazgos: { texto: string; clase: string }[] = []
  if (nIpsMalas > 0) hallazgos.push({ texto: `${nIpsMalas} IP con reputación mala`, clase: 'crit' })
  if (nTecnicas > 0) hallazgos.push({ texto: `${nTecnicas} técnica(s) MITRE`, clase: 'warn' })
  if (nCves > 0) hallazgos.push({ texto: `${nCves} CVE(s)`, clase: 'warn' })
  if (nComandos > 0) hallazgos.push({ texto: `${nComandos} comando(s) propuestos`, clase: 'info' })
  if (replans > 0) hallazgos.push({ texto: `replanificado ${replans}×`, clase: 'info' })

  return (
    <div className="rastreador">
      <div className="rastreador-nodos">
        {NODOS.map((n) => {
          const Icono = ICONOS[n.nombre] ?? Sparkles
          const activo = n.nombre === nodoActual && corriendo
          const hecho = nodosVistos.has(n.nombre)
          return (
            <span
              key={n.nombre}
              className={`rastreador-nodo ${activo ? 'activo' : ''} ${hecho ? 'hecho' : ''}`}
              title={n.titulo}
            >
              <Icono size={14} />
            </span>
          )
        })}
      </div>
      {hallazgos.length > 0 && (
        <div className="rastreador-hallazgos">
          {hallazgos.map((h) => (
            <span className={`chip ${h.clase}`} key={h.texto}>
              {h.texto}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}

export function ConversacionView({
  analisis,
  onAbrirInforme,
  onNavegar,
}: {
  analisis: EstadoAnalisis
  onAbrirInforme: (corrida: Corrida) => void
  onNavegar: (vista: Vista) => void
}) {
  // El estado del análisis vive por encima del cambio de vista (ver
  // ): así el hilo sobrevive a ir a Resumen o Ejecuciones,
  // y el stream sigue recibiendo mientras se mira otra pantalla.
  const { mensajes, jobId, corriendo, errorCarga, analizar, reiniciar, setErrorCarga } = analisis

  const [archivo, setArchivo] = useState<File | null>(null)
  const [dragging, setDragging] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)
  const finRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    finRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [mensajes])

  const elegir = useCallback(
    (file?: File) => {
      setErrorCarga(null)
      if (!file) return
      if (!EXTENSIONES.test(file.name)) {
        setErrorCarga(`"${file.name}" no es un formato compatible. Se esperan .log, .txt o .csv.`)
        return
      }
      // Se valida acá además del backend para no gastar la subida de un
      // archivo que igual sería rechazado con 413.
      if (file.size > MAX_BYTES) {
        setErrorCarga(`El archivo pesa ${pesoLegible(file.size)} y el máximo es ${LIMITE_LEGIBLE}.`)
        return
      }
      if (file.size === 0) {
        setErrorCarga('El archivo está vacío.')
        return
      }
      setArchivo(file)
    },
    [setErrorCarga],
  )

  const enviar = async () => {
    if (!archivo || corriendo) return
    const elegido = archivo
    setArchivo(null)
    await analizar(elegido)
  }

  const esperando = corriendo && mensajes.length > 0

  return (
    <AppShell grupo="analisis" onNavegar={onNavegar} sinPadding>
      <div className="chat">
        <div className="chat-cabecera">
          <div className="view-head" style={{ marginBottom: 0 }}>
            <h1>Multiagente NODEX</h1>
            <p>
              {mensajes.length === 0
                ? 'Adjunta un lote de registros: primero se arma un plan de investigación y después el grafo de agentes lo ejecuta paso a paso.'
                : 'Cada mensaje es lo que ese nodo devolvió al estado del grafo.'}
            </p>
          </div>
        </div>
        <RastreadorGrafo mensajes={mensajes} corriendo={corriendo} />
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
                      Reconocí el lote como{' '}
                      <strong
                        className="mono"
                        title="Producto o perfil reconocido, no la sintaxis de la línea: HDFS y BGL, por ejemplo, se decodifican como texto plano pero igual se identifican por su propio formato de columnas."
                      >
                        {(r.formato_detectado ?? '—').toUpperCase().replace(/_/g, '-')}
                      </strong>:{' '}
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

            if (m.rol === 'registro') {
              return (
                <div className="msg msg-agente" key={m.id} id="registro-manual">
                  <div className="msg-cabecera">
                    <span className="icono">
                      <FileText size={15} />
                    </span>
                    <strong>
                      {m.registrado ? 'Registrado para las métricas' : 'No entra a las métricas'}
                    </strong>
                    <time>{m.hora}</time>
                  </div>
                  <div className="msg-cuerpo">
                    <p>
                      {m.registrado && m.caso ? (
                        <>
                          Caso <strong className="mono">{m.caso}</strong>, análisis nº {m.repeticion}. Las
                          métricas (precisión, exhaustividad, F1…) aparecen en el módulo Resultados.
                        </>
                      ) : (
                        m.motivo
                      )}
                    </p>
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
                  {/* Reiniciar el hilo no pierde nada: la ejecución quedó
                      persistida y su informe se puede volver a abrir. */}
                  <p className="faint" style={{ fontSize: 12.5 }}>
                    Este informe queda guardado en Ejecuciones: analizar otro lote no lo borra.
                  </p>
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

            <div className="compositor-contenido">
              {archivo ? (
                /* El archivo elegido es una ficha DENTRO del contenedor, con
                   su propia superficie y su botón de quitar adentro. */
                <div className="compositor-ficha">
                  <span className="icono">
                    <FileText size={15} />
                  </span>
                  <div>
                    <strong>{archivo.name}</strong>
                    <span>{pesoLegible(archivo.size)} · listo para analizar</span>
                  </div>
                  <button
                    className="btn btn-quiet quitar"
                    aria-label="Quitar archivo"
                    disabled={corriendo}
                    onClick={(e) => {
                      e.stopPropagation()
                      setArchivo(null)
                    }}
                  >
                    <X size={14} />
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
            </div>

            <button
              className="btn btn-primary enviar"
              aria-label="Analizar el lote"
              disabled={!archivo || corriendo}
              onClick={(e) => {
                e.stopPropagation()
                enviar()
              }}
            >
              {corriendo ? <Loader2 size={15} className="spin" /> : <ArrowUp size={15} />}
            </button>
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
