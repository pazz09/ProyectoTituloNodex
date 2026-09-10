'use client'

import { useState } from 'react'
import {
  AlertTriangle,
  CheckCircle2,
  Download,
  Info,
  Loader2,
  Plus,
  ThumbsDown,
  ThumbsUp,
} from 'lucide-react'

import { AppShell, Sep, type Vista } from '@/components/app-shell'
import { ConfirmDialog } from '@/components/confirm-dialog'
import {
  descargarInforme,
  enviarFeedback,
  type Corrida,
  type RespuestaFeedback,
} from '@/lib/api'

const ATRIBUCION_MITRE =
  'MITRE ATT&CK® data reproduced and distributed with the permission of The MITRE Corporation. © The MITRE Corporation.'

function fechaLegible(iso: string | null) {
  if (!iso) return '—'
  const d = new Date(iso)
  return Number.isNaN(d.getTime())
    ? iso
    : d.toLocaleString('es', { dateStyle: 'medium', timeStyle: 'medium' })
}

/**
 * Veredicto derivado de los dos booleanos del backend. No se inventa un
 * puntaje de riesgo que el sistema no calcula.
 */
function veredicto(c: Corrida) {
  if (c.estado === 'error') {
    return { clase: 'crit', titulo: 'EJECUCIÓN INCOMPLETA', nota: 'El análisis no llegó a terminar.' }
  }
  if (c.hay_incidente) {
    return { clase: 'crit', titulo: 'INCIDENTE DE SEGURIDAD', nota: 'Se concluyó actividad maliciosa.' }
  }
  if (c.hay_anomalia) {
    return { clase: 'warn', titulo: 'ANOMALÍA OPERATIVA', nota: 'Comportamiento fuera de lo normal, sin evidencia de ataque.' }
  }
  return { clase: 'ok', titulo: 'SIN HALLAZGOS', nota: 'No se detectaron anomalías en el lote.' }
}

/**
 * Limpia la descripción de una técnica para mostrarla.
 *
 * El `texto` de la API es el documento tal como se indexó desde el bundle
 * STIX: repite el nombre al principio y trae los enlaces y citas en el
 * marcado propio de ATT&CK, que en pantalla se leen como ruido.
 */
function descripcionCorta(texto: string, nombre: string, largo = 240) {
  let limpio = texto
    .replace(/\[([^\]]+)\]\([^)]*\)/g, '$1')
    .replace(/\(Citation:[^)]*\)/g, '')
    .replace(/<\/?code>/g, '')
    .replace(/\s+/g, ' ')
    .trim()
  if (limpio.startsWith(`${nombre}.`)) limpio = limpio.slice(nombre.length + 1).trim()
  return limpio.length > largo ? `${limpio.slice(0, largo).trim()}…` : limpio
}

function formatoLegible(formato: string | null) {
  return (formato ?? '—').toUpperCase().replace(/_/g, '-')
}

function ordenar(dist: Record<string, number> | undefined) {
  return Object.entries(dist ?? {}).sort((a, b) => b[1] - a[1])
}

/** Distribución con barra proporcional al máximo de la serie. */
function Distribucion({ datos, tope = 6 }: { datos: Record<string, number> | undefined; tope?: number }) {
  const filas = ordenar(datos).slice(0, tope)
  if (filas.length === 0) return <p className="prose empty">Sin datos.</p>
  const max = filas[0][1] || 1
  return (
    <div className="dist">
      {filas.map(([nombre, n]) => (
        <div className="dist-row" key={nombre}>
          <div>
            <span>{nombre.replace(/_/g, ' ')}</span>
            <div className="dist-bar">
              <div style={{ width: `${Math.max(2, (n / max) * 100)}%` }} />
            </div>
          </div>
          <b>{n.toLocaleString('es')}</b>
        </div>
      ))}
    </div>
  )
}

export function ReportView({
  corrida,
  onNuevo,
  onNavegar,
  onFeedback,
}: {
  corrida: Corrida
  onNuevo: () => void
  onNavegar: (vista: Vista) => void
  onFeedback?: (actualizada: Corrida) => void
}) {
  const [descargando, setDescargando] = useState(false)
  const [errorDescarga, setErrorDescarga] = useState<string | null>(null)

  const [comentario, setComentario] = useState(corrida.feedback_comentario ?? '')
  const [pendiente, setPendiente] = useState<boolean | null>(null)
  const [enviando, setEnviando] = useState(false)
  const [resultado, setResultado] = useState<RespuestaFeedback | null>(null)
  const [errorFeedback, setErrorFeedback] = useState<string | null>(null)

  const reporte = corrida.reporte_json ?? {}
  const resumen = corrida.resumen_json ?? {}
  const tecnicas = corrida.tecnicas_mitre ?? []
  const comandos = reporte.comandos_mitigacion ?? []
  const ips = Object.entries(resumen.reputacion_ips ?? {})
  const v = veredicto(corrida)
  const confianza = corrida.confianza ?? 0
  const pctConfianza = Math.round(confianza * 100)

  const descargar = async () => {
    setDescargando(true)
    setErrorDescarga(null)
    try {
      await descargarInforme(corrida.job_id)
    } catch (e) {
      setErrorDescarga(e instanceof Error ? e.message : String(e))
    } finally {
      setDescargando(false)
    }
  }

  const confirmar = async () => {
    if (pendiente === null) return
    const correcto = pendiente
    setPendiente(null)
    setEnviando(true)
    setErrorFeedback(null)
    try {
      const r = await enviarFeedback(corrida.job_id, correcto, comentario.trim() || null)
      setResultado(r)
      onFeedback?.({
        ...corrida,
        feedback_correcto: correcto,
        feedback_comentario: comentario.trim() || null,
      })
    } catch (e) {
      setErrorFeedback(e instanceof Error ? e.message : String(e))
    } finally {
      setEnviando(false)
    }
  }

  const yaRevisada = corrida.feedback_correcto !== null && corrida.feedback_correcto !== undefined

  return (
    <AppShell
      vista="report"
      onNavegar={onNavegar}
      ruta={
        <>
          <span>Análisis</span>
          <Sep />
          <span className="mono">{corrida.archivo_origen ?? 'sin nombre'}</span>
          <Sep />
          <strong>Informe</strong>
        </>
      }
      acciones={
        <>
          <button className="btn" onClick={onNuevo}>
            <Plus size={14} /> Nuevo
          </button>
          <button className="btn btn-primary" onClick={descargar} disabled={descargando}>
            {descargando ? (
              <>
                <Loader2 size={14} className="spin" /> Generando…
              </>
            ) : (
              <>
                <Download size={14} /> Informe PDF
              </>
            )}
          </button>
        </>
      }
    >
      <div className="view-head">
        <div>
          <h1>Informe de análisis</h1>
          <p>
            <span className="mono">{corrida.job_id.slice(0, 12)}</span> · {fechaLegible(corrida.timestamp)}
          </p>
        </div>
      </div>

      {errorDescarga && (
        <div className="notice" role="alert" style={{ marginBottom: 14 }}>
          <AlertTriangle size={15} />
          <span>{errorDescarga}</span>
        </div>
      )}

      <div className={`verdict ${v.clase}`}>
        <div className="verdict-main">
          <span className="label">Veredicto</span>
          <strong>{v.titulo}</strong>
          <p>{v.nota}</p>
        </div>
        <div className="verdict-meta">
          <div>
            <span className="label">Confianza</span>
            <div className="meter">
              <div className={`meter-track ${pctConfianza < 70 ? 'warn' : ''}`}>
                <div style={{ width: `${pctConfianza}%` }} />
              </div>
              <b>{confianza.toFixed(2)}</b>
            </div>
          </div>
          <div>
            <span className="label">Formato</span>
            <b className="mono">{formatoLegible(corrida.formato_detectado)}</b>
          </div>
          <div>
            <span className="label">Motor</span>
            <b className="mono">{corrida.motor_preprocesamiento ?? '—'}</b>
          </div>
          <div className="verdict-chips">
            <span className={corrida.hay_anomalia ? 'chip warn' : 'chip'}>
              anomalía {corrida.hay_anomalia ? 'sí' : 'no'}
            </span>
            <span className={corrida.hay_incidente ? 'chip crit' : 'chip'}>
              incidente {corrida.hay_incidente ? 'sí' : 'no'}
            </span>
            <span className={corrida.requiere_revision_humana ? 'chip warn' : 'chip ok'}>
              {corrida.requiere_revision_humana ? 'escalado a analista' : 'auto-resuelto'}
            </span>
          </div>
        </div>
      </div>

      {corrida.estado === 'error' && (
        <div className="notice-block" role="alert">
          <div className="modal-icon" style={{ margin: 0, color: 'var(--crit)', background: 'var(--crit-bg)', borderColor: 'var(--crit-line)' }}>
            <AlertTriangle size={16} />
          </div>
          <div>
            <strong>La ejecución no se completó</strong>
            <p className="mono">{corrida.error_mensaje ?? 'Error no especificado.'}</p>
          </div>
        </div>
      )}

      <section className="panel">
        <div className="panel-body tight">
          <div className="stats">
            <div>
              <span className="label">Registros analizados</span>
              <b>{(corrida.total_lineas ?? 0).toLocaleString('es')}</b>
            </div>
            <div>
              <span className="label">IPs distintas</span>
              <b>{resumen.n_ips_distintas ?? 0}</b>
              <small>
                {(() => {
                  const n = ips.filter(([, d]) => d?.categoria === 'malicioso').length
                  return n === 1 ? '1 maliciosa' : `${n} maliciosas`
                })()}
              </small>
            </div>
            <div>
              <span className="label">Comandos propuestos</span>
              <b>{corrida.n_comandos_mitigacion ?? 0}</b>
              <small>{reporte.comandos_validos ? 'validados' : 'sin validar'}</small>
            </div>
            <div>
              <span className="label">Técnicas ATT&amp;CK</span>
              <b>{tecnicas.length}</b>
            </div>
            <div>
              <span className="label">Ciclos de corrección</span>
              <b>{reporte.intentos_correccion ?? 0}</b>
            </div>
          </div>
        </div>
      </section>

      <div className="grid-2">
        <section className="panel">
          <div className="panel-head">
            <div>
              <span className="label">Sección 1</span>
              <h2>Diagnóstico</h2>
            </div>
            <span className="panel-note">agente de triage</span>
          </div>
          <div className="panel-body">
            <p className="prose">
              {corrida.diagnostico || 'El sistema no registró un diagnóstico para esta ejecución.'}
            </p>
          </div>
        </section>

        <section className="panel">
          <div className="panel-head">
            <div>
              <span className="label">Sección 2</span>
              <h2>Evaluación del auditor</h2>
            </div>
          </div>
          <div className="panel-body">
            <p className="prose">
              {corrida.evaluacion_auditor || 'El auditor no dejó una evaluación registrada.'}
            </p>
          </div>
        </section>
      </div>

      <section className="panel">
        <div className="panel-head">
          <div>
            <span className="label">Sección 3</span>
            <h2>Evidencia observada</h2>
          </div>
          <span className="panel-note">preprocesamiento determinístico, sin LLM</span>
        </div>
        <div className="panel-body">
          <div className="grid-2">
            <div className="facts">
              <div>
                <dt>Archivo de origen</dt>
                <dd className="mono">{corrida.archivo_origen ?? '—'}</dd>
              </div>
              <div>
                <dt>Ventana temporal</dt>
                <dd className="mono">
                  {resumen.ventana_temporal?.inicio && resumen.ventana_temporal?.fin
                    ? `${resumen.ventana_temporal.inicio} — ${resumen.ventana_temporal.fin}`
                    : '—'}
                </dd>
              </div>
              <div>
                <dt>Formato / motor</dt>
                <dd className="mono">
                  {formatoLegible(corrida.formato_detectado)} · {corrida.motor_preprocesamiento ?? '—'}
                </dd>
              </div>
              <div>
                <dt>Firma del lote</dt>
                <dd className="mono" style={{ wordBreak: 'break-all', fontSize: 11 }}>
                  {reporte.firma ?? '—'}
                </dd>
              </div>
            </div>
            <div>
              <span className="label">Servicios</span>
              <div style={{ marginTop: 9, marginBottom: 17 }}>
                <Distribucion datos={resumen.servicios} />
              </div>
              <span className="label">Tipos de evento</span>
              <div style={{ marginTop: 9 }}>
                <Distribucion datos={resumen.eventos} />
              </div>
            </div>
          </div>
        </div>
        {ips.length > 0 && (
          <>
            <div className="subhead">
              <span className="label">Reputación de las direcciones observadas</span>
            </div>
          <div className="table-scroll">
            <table className="table">
              <thead>
                <tr>
                  <th>Dirección IP</th>
                  <th>Reputación</th>
                  <th>Score</th>
                  <th>Fuente</th>
                </tr>
              </thead>
              <tbody>
                {ips.map(([ip, datos]) => {
                  const cat = datos?.categoria ?? 'desconocido'
                  const clase = cat === 'malicioso' ? 'crit' : cat === 'sospechoso' ? 'warn' : cat === 'limpio' ? 'ok' : ''
                  return (
                    <tr key={ip}>
                      <td className="mono">{ip}</td>
                      <td>
                        <span className={`chip ${clase}`}>{cat}</span>
                      </td>
                      <td className="num">{datos?.score ?? '—'}</td>
                      <td className="mono" style={{ color: 'var(--text-muted)' }}>
                        {datos?.fuente ?? '—'}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
          </>
        )}
      </section>

      {tecnicas.length > 0 && (
        <section className="panel">
          <div className="panel-head">
            <div>
              <span className="label">Sección 4</span>
              <h2>Técnicas MITRE ATT&amp;CK relacionadas</h2>
            </div>
            <span className="panel-note">
              <Info size={13} /> recuperadas por similitud semántica
            </span>
          </div>
          <div className="panel-body">
            {tecnicas.map((t) => (
              <article className="tech" key={t.meta.technique_id}>
                <div className="tech-id">{t.meta.technique_id}</div>
                <div>
                  <div className="tech-head">
                    <strong>{t.meta.name}</strong>
                    {t.meta.tactics
                      .split(',')
                      .filter(Boolean)
                      .map((tactica) => (
                        <span className="chip" key={tactica}>
                          {tactica.trim().replace(/-/g, ' ')}
                        </span>
                      ))}
                    <span className="step-visits">sim {t.similitud.toFixed(3)}</span>
                  </div>
                  <p>{descripcionCorta(t.texto, t.meta.name)}</p>
                  <a href={t.meta.url} target="_blank" rel="noreferrer noopener">
                    attack.mitre.org/techniques/{t.meta.technique_id.replace('.', '/')}
                  </a>
                </div>
              </article>
            ))}
            {/* Requisito de atribución de MITRE: solo corresponde si
                efectivamente se muestran datos de ATT&CK. */}
            <p className="attribution">{ATRIBUCION_MITRE}</p>
          </div>
        </section>
      )}

      <section className="panel">
        <div className="panel-head">
          <div>
            <span className="label">Sección {tecnicas.length > 0 ? 5 : 4}</span>
            <h2>Mitigación propuesta</h2>
          </div>
          <span className="panel-note">NODEX no ejecuta estos comandos</span>
        </div>
        {comandos.length === 0 ? (
          <div className="panel-body">
            <p className="prose empty">
              No se requieren acciones de mitigación sobre la evidencia observada.
            </p>
          </div>
        ) : (
          <div className="panel-body tight">
            <div className="cmds">
              {comandos.map((c, i) => (
                <div key={`${i}-${c}`}>
                  <span className="idx">{String(i + 1).padStart(2, '0')}</span>
                  <code style={{ flex: 1 }}>{c}</code>
                  <span className={reporte.comandos_validos ? 'chip ok' : 'chip warn'}>
                    {reporte.comandos_validos ? 'validado' : 'sin validar'}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}
      </section>

      <section className="panel">
        <div className="panel-head">
          <div>
            <span className="label">Sección {tecnicas.length > 0 ? 6 : 5}</span>
            <h2>Revisión del analista</h2>
          </div>
          <span className="panel-note">escribe en la memoria de largo plazo</span>
        </div>
        <div className="panel-body">
          <p className="prose" style={{ marginBottom: 13 }}>
            El veredicto se guarda en la memoria del sistema y se usa como referencia en
            ejecuciones posteriores.
          </p>
          <div className="review">
            <button
              className={`btn ${yaRevisada && corrida.feedback_correcto ? 'chosen-ok' : ''}`}
              disabled={enviando}
              onClick={() => setPendiente(true)}
            >
              <ThumbsUp size={14} /> Diagnóstico correcto
            </button>
            <button
              className={`btn ${yaRevisada && corrida.feedback_correcto === false ? 'chosen-no' : ''}`}
              disabled={enviando}
              onClick={() => setPendiente(false)}
            >
              <ThumbsDown size={14} /> Diagnóstico incorrecto
            </button>
            {enviando && (
              <span className="review-note">
                <Loader2 size={13} className="spin" /> guardando…
              </span>
            )}
          </div>
          <textarea
            className="field"
            placeholder="Comentario (opcional): qué falta, qué sobra, o qué era en realidad."
            value={comentario}
            onChange={(e) => setComentario(e.target.value)}
          />
          {yaRevisada && !resultado && (
            <p className="review-note ok" style={{ marginTop: 11 }}>
              <CheckCircle2 size={13} /> Revisada
              {corrida.feedback_timestamp ? ` el ${fechaLegible(corrida.feedback_timestamp)}` : ''} ·
              se puede corregir volviendo a elegir
            </p>
          )}
          {resultado && (
            <p className="review-note ok" style={{ marginTop: 11 }}>
              <CheckCircle2 size={13} />
              {resultado.memoria
                ? `Registrado en ${resultado.memoria.guardado_en}` +
                  (resultado.memoria.promovido_a_attack_patterns ? ' · promovido a attack_patterns' : '') +
                  (resultado.memoria.error_registrado ? ' · registrado en error_memory' : '')
                : ` Registrado. ${resultado.detalle ?? ''}`}
            </p>
          )}
          {errorFeedback && (
            <p className="review-note err" style={{ marginTop: 11 }}>
              <AlertTriangle size={13} /> {errorFeedback}
            </p>
          )}
        </div>
      </section>

      <ConfirmDialog
        abierto={pendiente !== null}
        titulo={pendiente ? 'Confirmar diagnóstico como correcto' : 'Confirmar diagnóstico como incorrecto'}
        descripcion="Esto va a afectar las recomendaciones futuras del sistema: el veredicto se guarda en la memoria de largo plazo y se usa como referencia en análisis posteriores."
        textoConfirmar={pendiente ? 'Marcar como correcto' : 'Marcar como incorrecto'}
        variante={pendiente ? 'primary' : 'danger'}
        onConfirmar={confirmar}
        onCancelar={() => setPendiente(null)}
      />
    </AppShell>
  )
}
