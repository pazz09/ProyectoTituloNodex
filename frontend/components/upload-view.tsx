'use client'

import { useRef, useState } from 'react'
import {
  AlertTriangle,
  ArrowRight,
  FileText,
  Loader2,
  ShieldCheck,
  UploadCloud,
  X,
  Zap,
} from 'lucide-react'

import { Header, type Vista } from '@/components/header'
import { MAX_BYTES, subirArchivo } from '@/lib/api'

const EXTENSIONES = /\.(log|txt|csv)$/i

function pesoLegible(bytes: number) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

const LIMITE_LEGIBLE = `${Math.round(MAX_BYTES / 1024 / 1024)} MB`

export function UploadView({
  onAnalizar,
  onNavegar,
}: {
  onAnalizar: (jobId: string, nombreArchivo: string) => void
  onNavegar: (vista: Vista) => void
}) {
  // Arranca vacío: el botón queda deshabilitado hasta que se elija un archivo
  // real. El skeleton simulaba uno ya seleccionado.
  const [archivo, setArchivo] = useState<File | null>(null)
  const [dragging, setDragging] = useState(false)
  const [subiendo, setSubiendo] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  const elegir = (file?: File) => {
    setError(null)
    if (!file) return
    if (!EXTENSIONES.test(file.name)) {
      setError(`"${file.name}" no es un formato compatible. Se esperan .log, .txt o .csv.`)
      return
    }
    // Se valida acá además del backend para no gastar la subida de un archivo
    // que igual va a ser rechazado con 413.
    if (file.size > MAX_BYTES) {
      setError(
        `El archivo pesa ${pesoLegible(file.size)} y el máximo es ${LIMITE_LEGIBLE}. ` +
          'Subí un lote más chico.',
      )
      return
    }
    if (file.size === 0) {
      setError('El archivo está vacío.')
      return
    }
    setArchivo(file)
  }

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
    <main className="shell upload-shell">
      <Header vista="upload" onNavegar={onNavegar} />
      <section className="upload-content">
        <div className="eyebrow">
          <span className="status-dot" /> MOTOR DE ANÁLISIS MULTIAGENTE
        </div>
        <h1>
          Comprenda lo que ocurre
          <br />
          <span>en sus registros de seguridad.</span>
        </h1>
        <p className="intro">
          NODEX analiza grandes volúmenes de registros y transforma señales dispersas en
          incidentes claros y accionables.
        </p>
        <div className="upload-card">
          <div className="card-label">
            <UploadCloud size={18} /> CARGAR ARCHIVO DE LOG
          </div>
          <div
            className={`dropzone ${dragging ? 'is-dragging' : ''}`}
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
              if (e.key === 'Enter') inputRef.current?.click()
            }}
          >
            <input
              ref={inputRef}
              type="file"
              accept=".log,.txt,.csv"
              hidden
              onChange={(e) => elegir(e.target.files?.[0])}
            />
            <div className="upload-icon">
              <FileText size={25} />
            </div>
            <strong>Arrastre su archivo aquí</strong>
            <span>
              o <u>seleccione un archivo</u> desde su computadora
            </span>
            <small>Formatos compatibles: .LOG · .TXT · .CSV · Máximo {LIMITE_LEGIBLE}</small>
          </div>

          {error && (
            <div className="inline-error" role="alert">
              <AlertTriangle size={16} />
              <span>{error}</span>
            </div>
          )}

          {archivo && (
            <div className="selected-file">
              <div className="file-icon">
                <FileText size={18} />
              </div>
              <div>
                <strong>{archivo.name}</strong>
                <span>Listo para analizar · {pesoLegible(archivo.size)}</span>
              </div>
              <button
                aria-label="Quitar archivo"
                disabled={subiendo}
                onClick={(e) => {
                  e.stopPropagation()
                  setArchivo(null)
                  setError(null)
                }}
              >
                <X size={16} />
              </button>
            </div>
          )}

          <button
            className="primary-button analyze-button"
            disabled={!archivo || subiendo}
            onClick={analizar}
          >
            {subiendo ? (
              <>
                <Loader2 size={18} className="spin" /> Subiendo archivo...
              </>
            ) : (
              <>
                Analizar archivo <ArrowRight size={18} />
              </>
            )}
          </button>
        </div>
        <div className="trust-row">
          <span>
            <ShieldCheck size={16} /> Sus archivos se procesan de forma segura
          </span>
          <span>
            <Zap size={16} /> Resultado en minutos, no horas
          </span>
        </div>
      </section>
      <footer className="page-footer">
        <span>NODEX v1.0 · Sistema de análisis de seguridad</span>
        <span>Los datos no se almacenan después del análisis</span>
      </footer>
    </main>
  )
}
