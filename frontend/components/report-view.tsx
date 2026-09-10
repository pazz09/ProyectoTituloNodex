'use client'

import { useState } from 'react'
import {
  AlertTriangle,
  CheckCircle2,
  Clock3,
  Download,
  FileText,
  Info,
  Loader2,
  RotateCcw,
  ShieldCheck,
  ThumbsDown,
  ThumbsUp,
  Zap,
} from 'lucide-react'

import { ConfirmDialog } from '@/components/confirm-dialog'
import { Header, type Vista } from '@/components/header'
import {
  descargarInforme,
  enviarFeedback,
  type Corrida,
  type RespuestaFeedback,
} from '@/lib/api'

const ATRIBUCION_MITRE =
  'MITRE ATT&CK® data reproduced and distributed with the permission of The MITRE Corporation. © The MITRE Corporation.'

function fechaLegible(iso: string | null) {
  if (!iso) return 'sin fecha'
  const d = new Date(iso)
  return Number.isNaN(d.getTime())
    ? iso
    : d.toLocaleString('es', { dateStyle: 'medium', timeStyle: 'medium' })
}

/**
 * Veredicto para el banner, derivado de los dos booleanos que da el
 * backend. No se inventa un puntaje de riesgo que el sistema no calcula:
 * `hay_incidente` y `hay_anomalia` son lo que hay.
 */
function veredicto(c: Corrida) {
  if (c.hay_incidente) {
    return {
      clase: 'is-incidente',
      titulo: 'INCIDENTE DE SEGURIDAD',
      nota: 'El análisis concluyó que hay actividad maliciosa.',
    }
  }
  if (c.hay_anomalia) {
    return {
      clase: 'is-anomalia',
      titulo: 'ANOMALÍA OPERATIVA',
      nota: 'Hay comportamiento fuera de lo normal, sin evidencia de ataque.',
    }
  }
  return {
    clase: 'is-limpio',
    titulo: 'SIN HALLAZGOS',
    nota: 'No se detectaron anomalías en el lote analizado.',
  }
}

/**
 * Limpia la descripción de una técnica para mostrarla.
 *
 * El `texto` que devuelve la API es el documento tal como se indexó desde el
 * bundle STIX: arranca repitiendo el nombre de la técnica y trae los enlaces
 * y citas en el marcado propio de ATT&CK
 * (`[Valid Accounts](https://…)`, `(Citation: …)`), que en pantalla se leen
 * como ruido.
 */
function descripcionCorta(texto: string, nombre: string, largo = 260) {
  let limpio = texto
    .replace(/\[([^\]]+)\]\([^)]*\)/g, '$1') // enlaces de ATT&CK
    .replace(/\(Citation:[^)]*\)/g, '') // citas bibliográficas
    .replace(/<\/?code>/g, '')
    .replace(/\s+/g, ' ')
    .trim()
  // El documento indexado empieza con "Nombre. descripción".
  if (limpio.startsWith(`${nombre}.`)) limpio = limpio.slice(nombre.length + 1).trim()
  return limpio.length > largo ? `${limpio.slice(0, largo).trim()}…` : limpio
}

/** `auth_log` -> `AUTH-LOG`, igual que en la vista de análisis. */
function formatoLegible(formato: string | null) {
  return (formato ?? 'sin determinar').toUpperCase().replace(/_/g, '-')
}

function principales(dist: Record<string, number> | undefined, tope = 6) {
  return Object.entries(dist ?? {})
    .sort((a, b) => b[1] - a[1])
    .slice(0, tope)
}

export function ReportView({
  corrida,
  onReset,
  onNavegar,
  onFeedback,
}: {
  corrida: Corrida
  onReset: () => void
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
  const v = veredicto(corrida)
  const confianza = corrida.confianza ?? 0

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
    <main className="shell report-shell">
      <Header vista="report" onNavegar={onNavegar} />
      <section className="report-content">
        <div className="report-top">
          <div>
            <div className="eyebrow">
              {corrida.estado === 'error' ? (
                <>
                  <AlertTriangle size={15} /> ANÁLISIS INCOMPLETO
                </>
              ) : (
                <>
                  <CheckCircle2 size={15} /> ANÁLISIS COMPLETADO
                </>
              )}
            </div>
            <h1>Informe de seguridad</h1>
            <p className="file-context">
              <FileText size={15} /> {corrida.archivo_origen ?? 'sin nombre'} ·{' '}
              {fechaLegible(corrida.timestamp)}
            </p>
            <p className="file-context">
              <Info size={15} /> Formato detectado:{' '}
              <strong>{formatoLegible(corrida.formato_detectado)}</strong> ·
              Motor de preprocesamiento:{' '}
              <strong>{corrida.motor_preprocesamiento ?? 'sin registrar'}</strong>
            </p>
          </div>
          <div className="report-actions">
            <button className="secondary-button" onClick={onReset}>
              <RotateCcw size={16} /> Nuevo análisis
            </button>
            <button className="primary-button" onClick={descargar} disabled={descargando}>
              {descargando ? (
                <>
                  <Loader2 size={16} className="spin" /> Generando...
                </>
              ) : (
                <>
                  <Download size={16} /> Descargar informe
                </>
              )}
            </button>
          </div>
        </div>

        {errorDescarga && (
          <div className="inline-error" role="alert">
            <AlertTriangle size={16} />
            <span>{errorDescarga}</span>
          </div>
        )}

        {corrida.estado === 'error' && (
          <div className="error-banner" role="alert">
            <div className="error-icon">
              <AlertTriangle size={19} />
            </div>
            <div>
              <strong>El análisis no pudo completarse</strong>
              <p>{corrida.error_mensaje ?? 'Error no especificado.'}</p>
            </div>
          </div>
        )}

        <div className={`risk-banner ${v.clase}`}>
          <div className="risk-score">
            <span>VEREDICTO</span>
            <strong>{v.titulo}</strong>
            <small>{v.nota}</small>
          </div>
          <div className="risk-summary">
            {corrida.requiere_revision_humana
              ? 'La confianza quedó bajo el umbral: este informe requiere la revisión de un analista humano antes de actuar.'
              : 'La confianza del análisis es suficiente para resolver sin escalamiento.'}
            <div className="badge-row">
              <span className={corrida.hay_anomalia ? 'badge on' : 'badge'}>
                Anomalía: {corrida.hay_anomalia ? 'sí' : 'no'}
              </span>
              <span className={corrida.hay_incidente ? 'badge on' : 'badge'}>
                Incidente: {corrida.hay_incidente ? 'sí' : 'no'}
              </span>
              <span className={corrida.requiere_revision_humana ? 'badge warn' : 'badge'}>
                Revisión humana: {corrida.requiere_revision_humana ? 'requerida' : 'no requerida'}
              </span>
            </div>
          </div>
        </div>

        <div className="metrics-grid">
          <div>
            <span>Líneas analizadas</span>
            <strong>{(corrida.total_lineas ?? 0).toLocaleString('es')}</strong>
            <small>Del archivo cargado</small>
          </div>
          <div>
            <span>IPs distintas</span>
            <strong>{resumen.n_ips_distintas ?? 0}</strong>
            <small>Origen y destino</small>
          </div>
          <div>
            <span>Comandos propuestos</span>
            <strong>{corrida.n_comandos_mitigacion ?? 0}</strong>
            <small>{reporte.comandos_validos ? 'Validados' : 'Sin validar'}</small>
          </div>
          <div>
            <span>Confianza del análisis</span>
            <strong>{Math.round(confianza * 100)}%</strong>
            <div className="confianza-track">
              <div style={{ width: `${Math.round(confianza * 100)}%` }} />
            </div>
          </div>
        </div>

        <div className="report-grid">
          <section className="findings-card">
            <div className="section-heading">
              <div>
                <span className="eyebrow">DIAGNÓSTICO</span>
                <h2>Qué encontramos</h2>
              </div>
              <span className="plain-help">
                <Info size={14} /> Redactado por el agente de triage
              </span>
            </div>
            <p className="prosa">{corrida.diagnostico || 'El sistema no registró un diagnóstico para esta corrida.'}</p>
          </section>
          <aside className="recommendation-card">
            <div className="aside-card-title">
              <ShieldCheck size={17} /> Evaluación del auditor
            </div>
            <p className="prosa">
              {corrida.evaluacion_auditor ||
                'El auditor no dejó una evaluación registrada para esta corrida.'}
            </p>
            <div className="report-footnote">
              <ShieldCheck size={15} /> Informe generado por 7 agentes especializados
              {reporte.intentos_correccion ? ` · ${reporte.intentos_correccion} ciclo(s) de corrección` : ''}
            </div>
          </aside>
        </div>

        <div className="events-card">
          <div className="section-heading">
            <div>
              <span className="eyebrow">EVIDENCIA OBSERVADA</span>
              <h2>Qué trae el archivo</h2>
            </div>
            <span className="plain-help">
              <Clock3 size={14} />{' '}
              {resumen.ventana_temporal?.inicio && resumen.ventana_temporal?.fin
                ? `${resumen.ventana_temporal.inicio} → ${resumen.ventana_temporal.fin}`
                : 'sin ventana temporal'}
            </span>
          </div>
          <div className="events-table">
            <div className="event-row event-head">
              <span>CATEGORÍA</span>
              <span>DETALLE</span>
              <span>VALOR</span>
              <span>ESTADO</span>
            </div>
            {principales(resumen.servicios).map(([nombre, n]) => (
              <div className="event-row" key={`svc-${nombre}`}>
                <span>Servicio</span>
                <span>{nombre}</span>
                <span>{n.toLocaleString('es')} evento(s)</span>
                <span />
              </div>
            ))}
            {principales(resumen.eventos).map(([nombre, n]) => (
              <div className="event-row" key={`ev-${nombre}`}>
                <span>Evento</span>
                <span>{nombre.replace(/_/g, ' ')}</span>
                <span>{n.toLocaleString('es')} línea(s)</span>
                <span />
              </div>
            ))}
            {Object.entries(resumen.reputacion_ips ?? {}).map(([ip, datos]) => {
              const cat = datos?.categoria ?? 'desconocido'
              return (
                <div className="event-row" key={`ip-${ip}`}>
                  <span>IP</span>
                  <span className="mono">{ip}</span>
                  <span>
                    {datos?.score !== null && datos?.score !== undefined
                      ? `score ${datos.score} · AbuseIPDB`
                      : 'sin score'}
                  </span>
                  <span className={`event-status rep-${cat}`}>{cat}</span>
                </div>
              )
            })}
          </div>
        </div>

        {tecnicas.length > 0 && (
          <div className="findings-card mitre-card">
            <div className="section-heading">
              <div>
                <span className="eyebrow">CONTEXTO DE AMENAZAS</span>
                <h2>Técnicas MITRE ATT&amp;CK relacionadas</h2>
              </div>
              <span className="plain-help">
                <Info size={14} /> Recuperadas por similitud, {tecnicas.length} de la base
              </span>
            </div>
            <div className="mitre-list">
              {tecnicas.map((t) => (
                <article className="mitre-item" key={t.meta.technique_id}>
                  <div className="mitre-id">{t.meta.technique_id}</div>
                  <div>
                    <div className="finding-meta">
                      <strong>{t.meta.name}</strong>
                      {t.meta.tactics && <span>· {t.meta.tactics.replace(/,/g, ', ')}</span>}
                    </div>
                    <p>{descripcionCorta(t.texto, t.meta.name)}</p>
                    <a href={t.meta.url} target="_blank" rel="noreferrer noopener">
                      Ver en attack.mitre.org
                    </a>
                  </div>
                </article>
              ))}
            </div>
            {/* Requisito de atribución de MITRE: solo corresponde si
                efectivamente se muestran datos de ATT&CK. */}
            <p className="mitre-attribution">{ATRIBUCION_MITRE}</p>
          </div>
        )}

        <div className="events-card">
          <div className="section-heading">
            <div>
              <span className="eyebrow">MITIGACIÓN PROPUESTA</span>
              <h2>Acciones recomendadas</h2>
            </div>
            <span className="plain-help">
              <Zap size={14} /> NODEX no los ejecuta
            </span>
          </div>
          {comandos.length === 0 ? (
            <p className="prosa vacio">
              No se requieren acciones de mitigación. El análisis no identificó acciones
              necesarias sobre la evidencia observada.
            </p>
          ) : (
            <ul className="comandos-lista">
              {comandos.map((c, i) => (
                <li key={`${i}-${c}`}>
                  <code>{c}</code>
                  <span className={reporte.comandos_validos ? 'cmd-ok' : 'cmd-warn'}>
                    {reporte.comandos_validos ? 'validado' : 'sin validar'}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="events-card feedback-card">
          <div className="section-heading">
            <div>
              <span className="eyebrow">REVISIÓN DEL ANALISTA</span>
              <h2>¿El diagnóstico es correcto?</h2>
            </div>
            <span className="plain-help">
              <Info size={14} /> Alimenta la memoria del sistema
            </span>
          </div>
          <p className="prosa">
            Tu veredicto se guarda en la memoria de largo plazo y afecta las recomendaciones de
            análisis futuros.
          </p>
          <div className="feedback-actions">
            <button
              className={`feedback-button ok ${yaRevisada && corrida.feedback_correcto ? 'elegido' : ''}`}
              disabled={enviando}
              onClick={() => setPendiente(true)}
            >
              <ThumbsUp size={15} /> Diagnóstico correcto
            </button>
            <button
              className={`feedback-button no ${yaRevisada && corrida.feedback_correcto === false ? 'elegido' : ''}`}
              disabled={enviando}
              onClick={() => setPendiente(false)}
            >
              <ThumbsDown size={15} /> Diagnóstico incorrecto
            </button>
            {enviando && (
              <span className="feedback-estado">
                <Loader2 size={14} className="spin" /> Guardando...
              </span>
            )}
          </div>
          <textarea
            className="feedback-comentario"
            placeholder="Comentario (opcional): qué falta, qué sobra, o qué era en realidad."
            value={comentario}
            onChange={(e) => setComentario(e.target.value)}
          />
          {yaRevisada && !resultado && (
            <p className="feedback-estado ok">
              <CheckCircle2 size={14} /> Ya revisada
              {corrida.feedback_timestamp ? ` el ${fechaLegible(corrida.feedback_timestamp)}` : ''}. Se
              puede corregir volviendo a elegir.
            </p>
          )}
          {resultado && (
            <p className="feedback-estado ok">
              <CheckCircle2 size={14} /> Veredicto registrado.
              {resultado.memoria
                ? ` Guardado en ${resultado.memoria.guardado_en}` +
                  (resultado.memoria.promovido_a_attack_patterns
                    ? ', promovido a attack_patterns'
                    : '') +
                  (resultado.memoria.error_registrado ? ', registrado en error_memory' : '') +
                  '.'
                : ` ${resultado.detalle ?? ''}`}
            </p>
          )}
          {errorFeedback && (
            <p className="feedback-estado error">
              <AlertTriangle size={14} /> {errorFeedback}
            </p>
          )}
        </div>
      </section>

      <ConfirmDialog
        abierto={pendiente !== null}
        titulo={
          pendiente
            ? 'Marcar el diagnóstico como correcto'
            : 'Marcar el diagnóstico como incorrecto'
        }
        descripcion="Esto va a afectar las recomendaciones futuras del sistema: el veredicto se guarda en la memoria de largo plazo y se usa como referencia en análisis posteriores."
        textoConfirmar={pendiente ? 'Confirmar como correcto' : 'Confirmar como incorrecto'}
        variante={pendiente ? 'primary' : 'danger'}
        onConfirmar={confirmar}
        onCancelar={() => setPendiente(null)}
      />
    </main>
  )
}
