'use client'

import { useCallback, useState } from 'react'

import { ConversacionView } from '@/components/conversacion-view'
import { HistorialView } from '@/components/historial-view'
import { OverviewView } from '@/components/overview-view'
import { ReportView } from '@/components/report-view'
import type { Grupo, Vista } from '@/components/app-shell'
import type { Corrida } from '@/lib/api'

/**
 * Orquestador de las vistas.
 *
 * `grupoOrigen` recuerda por dónde se entró al informe: se llega desde el
 * asistente (recién analizado) o desde una ejecución anterior, y corresponde
 * dejar resaltado en la barra lateral el camino por el que se entró.
 */
export default function Page() {
  const [vista, setVista] = useState<Vista>('analisis')
  const [corrida, setCorrida] = useState<Corrida | null>(null)
  const [grupoOrigen, setGrupoOrigen] = useState<Grupo>('analisis')

  const navegar = useCallback((destino: Vista) => {
    if (destino !== 'informe') {
      setGrupoOrigen(destino === 'historial' ? 'historial' : destino === 'overview' ? 'overview' : 'analisis')
    }
    setVista(destino)
  }, [])

  const abrirInforme = useCallback((datos: Corrida, desde: Grupo) => {
    setCorrida(datos)
    setGrupoOrigen(desde)
    setVista('informe')
  }, [])

  if (vista === 'informe' && corrida) {
    return (
      <ReportView
        corrida={corrida}
        grupo={grupoOrigen}
        onNavegar={navegar}
        onFeedback={setCorrida}
      />
    )
  }

  if (vista === 'overview') {
    return (
      <OverviewView onAbrir={(c) => abrirInforme(c, 'overview')} onNavegar={navegar} />
    )
  }

  if (vista === 'historial') {
    return (
      <HistorialView onAbrir={(c) => abrirInforme(c, 'historial')} onNavegar={navegar} />
    )
  }

  return (
    <ConversacionView onAbrirInforme={(c) => abrirInforme(c, 'analisis')} onNavegar={navegar} />
  )
}
