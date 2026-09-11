'use client'

import { useState } from 'react'
import {
  AlertTriangle,
  CheckCircle2,
  Download,
  ExternalLink,
  Loader2,
  Plus,
  ThumbsDown,
  ThumbsUp,
} from 'lucide-react'

import { AppShell, type Grupo, type Vista } from '@/components/app-shell'
import { ConfirmDialog } from '@/components/confirm-dialog'
import {
  API_BASE,
  descargarInforme,
  enviarFeedback,
  type Corrida,
  type RespuestaFeedback,
} from '@/lib/api'

function fechaLegible(iso: string | null) {
  if (!iso) return '—'
  const d = new Date(iso)
  return Number.isNaN(d.getTime())
    ? iso
    : d.toLocaleString('es', { dateStyle: 'medium', timeStyle: 'medium' })
}

/**
 * Vista del informe.
 *
 * Muestra **el PDF mismo**, incrustado: lo que se ve en pantalla es
 * exactamente lo que se descarga, sin una segunda maquetación en HTML que
 * pueda divergir del documento. El precio es que dentro del visor no hay
 * nada interactivo, así que lo que no puede vivir en un PDF --descargarlo,
 * abrirlo aparte y la revisión del analista-- queda afuera, como controles
 * de la aplicación alrededor del documento.
 */
export function ReportView({
  corrida,
  grupo,
  onNavegar,
  onFeedback,
}: {
  corrida: Corrida
  grupo: Grupo
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

  // `inline=1` hace que el backend responda con `Content-Disposition: inline`:
  // con `attachment` el navegador descargaría el archivo en vez de mostrarlo
  // dentro del visor.
  const urlVisor = `${API_BASE}/api/historial/${corrida.job_id}/pdf?inline=1`

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
    <AppShell grupo={grupo} onNavegar={onNavegar}>
      <div className="view-head">
        <h1>Informe de análisis</h1>
        <p>
          <span className="mono">{corrida.archivo_origen ?? 'sin nombre'}</span> ·{' '}
          {fechaLegible(corrida.timestamp)} ·{' '}
          <span className="mono">{corrida.job_id.slice(0, 12)}</span>
        </p>
        <div className="acciones">
          <button className="btn btn-primary" onClick={descargar} disabled={descargando}>
            {descargando ? (
              <>
                <Loader2 size={14} className="spin" /> Generando…
              </>
            ) : (
              <>
                <Download size={14} /> Descargar PDF
              </>
            )}
          </button>
          <a className="btn" href={urlVisor} target="_blank" rel="noreferrer noopener">
            <ExternalLink size={14} /> Abrir en otra pestaña
          </a>
          <button className="btn" onClick={() => onNavegar('analisis')}>
            <Plus size={14} /> Analizar otro lote
          </button>
        </div>
      </div>

      {errorDescarga && (
        <div className="notice" role="alert" style={{ marginBottom: 18 }}>
          <AlertTriangle size={15} />
          <span>{errorDescarga}</span>
        </div>
      )}

      {corrida.estado === 'error' && (
        <div className="notice-block" role="alert">
          <div className="icono-aviso">
            <AlertTriangle size={16} />
          </div>
          <div>
            <strong>La ejecución no se completó</strong>
            <p className="mono">{corrida.error_mensaje ?? 'Error no especificado.'}</p>
          </div>
        </div>
      )}

      {/* El documento tal como se descarga. El visor es el del navegador: el
          texto del <p> solo se ve si no puede mostrar PDF incrustado. */}
      <div className="visor-pdf">
        <p className="visor-alterna">
          Tu navegador no puede mostrar el PDF incrustado.{' '}
          <a href={urlVisor} target="_blank" rel="noreferrer noopener">
            Abrilo en otra pestaña
          </a>
          .
        </p>
        <iframe src={urlVisor} title="Informe de análisis en PDF" />
      </div>

      <section className="panel">
        <div className="panel-head">
          <h2>Revisión del analista</h2>
          <p>
            El veredicto se guarda en la memoria de largo plazo del sistema y se usa como
            referencia en ejecuciones posteriores. Queda registrado en el informe.
          </p>
        </div>
        <div className="panel-body">
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
            <p className="review-note ok" style={{ marginTop: 14 }}>
              <CheckCircle2 size={13} /> Revisada
              {corrida.feedback_timestamp ? ` el ${fechaLegible(corrida.feedback_timestamp)}` : ''} ·
              se puede corregir volviendo a elegir
            </p>
          )}
          {resultado && (
            <p className="review-note ok" style={{ marginTop: 14 }}>
              <CheckCircle2 size={13} />
              {resultado.memoria
                ? `Registrado en ${resultado.memoria.guardado_en}` +
                  (resultado.memoria.promovido_a_attack_patterns
                    ? ' · promovido a attack_patterns'
                    : '') +
                  (resultado.memoria.error_registrado ? ' · registrado en error_memory' : '')
                : ` Registrado. ${resultado.detalle ?? ''}`}
            </p>
          )}
          {errorFeedback && (
            <p className="review-note err" style={{ marginTop: 14 }}>
              <AlertTriangle size={13} /> {errorFeedback}
            </p>
          )}
        </div>
      </section>

      <ConfirmDialog
        abierto={pendiente !== null}
        titulo={
          pendiente
            ? 'Confirmar diagnóstico como correcto'
            : 'Confirmar diagnóstico como incorrecto'
        }
        descripcion="Esto va a afectar las recomendaciones futuras del sistema: el veredicto se guarda en la memoria de largo plazo y se usa como referencia en análisis posteriores."
        textoConfirmar={pendiente ? 'Marcar como correcto' : 'Marcar como incorrecto'}
        variante={pendiente ? 'primary' : 'danger'}
        onConfirmar={confirmar}
        onCancelar={() => setPendiente(null)}
      />
    </AppShell>
  )
}
