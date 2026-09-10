'use client'

import { useCallback, useState } from 'react'

import { AnalysisView } from '@/components/analysis-view'
import { HistorialView } from '@/components/historial-view'
import { ReportView } from '@/components/report-view'
import { UploadView } from '@/components/upload-view'
import type { Vista } from '@/components/app-shell'
import type { Corrida } from '@/lib/api'

/**
 * Orquestador de las 4 vistas.
 *
 * `jobId` se conserva acá porque el evento `final` del SSE no lo trae, y sin
 * él no se puede pedir el PDF ni registrar el feedback de la corrida.
 */
export default function Page() {
  const [vista, setVista] = useState<Vista>('upload')
  const [jobId, setJobId] = useState<string | null>(null)
  const [nombreArchivo, setNombreArchivo] = useState('')
  const [corrida, setCorrida] = useState<Corrida | null>(null)

  const navegar = useCallback((destino: Vista) => {
    if (destino === 'upload') {
      setJobId(null)
      setCorrida(null)
      setNombreArchivo('')
    }
    setVista(destino)
  }, [])

  const mostrarInforme = useCallback((datos: Corrida) => {
    setCorrida(datos)
    setJobId(datos.job_id)
    setNombreArchivo(datos.archivo_origen ?? '')
    setVista('report')
  }, [])

  if (vista === 'historial') {
    return <HistorialView onAbrir={mostrarInforme} onNavegar={navegar} />
  }

  if (vista === 'analysis' && jobId) {
    return (
      <AnalysisView
        jobId={jobId}
        nombreArchivo={nombreArchivo}
        onCompletar={mostrarInforme}
        onReintentar={() => navegar('upload')}
        onNavegar={navegar}
      />
    )
  }

  if (vista === 'report' && corrida) {
    return (
      <ReportView
        corrida={corrida}
        onNuevo={() => navegar('upload')}
        onNavegar={navegar}
        onFeedback={setCorrida}
      />
    )
  }

  return (
    <UploadView
      onAnalizar={(id, nombre) => {
        setJobId(id)
        setNombreArchivo(nombre)
        setVista('analysis')
      }}
      onAbrirCorrida={mostrarInforme}
      onNavegar={navegar}
    />
  )
}
