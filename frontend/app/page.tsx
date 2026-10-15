'use client'

import { useCallback, useState } from 'react'

import { ConversacionView } from '@/components/conversacion-view'
import { HistorialView } from '@/components/historial-view'
import { OverviewView } from '@/components/overview-view'
import { ReportView } from '@/components/report-view'
import { ResultadosView } from '@/components/resultados-view'
import { useAnalisis } from '@/components/use-analisis'
import type { Grupo, Vista } from '@/components/app-shell'
import type { Corrida } from '@/lib/api'

/**
 * Orquestador de las vistas.
 *
 * El estado del análisis vive **acá** y no dentro de la conversación: si
 * viviera ahí, ir a Resumen o a Ejecuciones desmontaría la vista y el hilo
 * se perdería. Desde acá sobrevive a la navegación, y el stream sigue
 * recibiendo mensajes mientras se mira otra pantalla.
 *
 * `grupoOrigen` recuerda por dónde se entró al informe: se llega desde el
 * multiagente (recién analizado) o desde una ejecución anterior, y
 * corresponde dejar resaltado en la barra lateral el camino por el que se
 * entró.
 */
export default function Page() {
  const [vista, setVista] = useState<Vista>('analisis')
  const [corrida, setCorrida] = useState<Corrida | null>(null)
  const [grupoOrigen, setGrupoOrigen] = useState<Grupo>('analisis')
  const analisis = useAnalisis()

  const navegar = useCallback((destino: Vista) => {
    if (destino !== 'informe') {
      setGrupoOrigen(
        destino === 'historial'
          ? 'historial'
          : destino === 'overview'
            ? 'overview'
            : destino === 'resultados'
              ? 'resultados'
              : 'analisis',
      )
    }
    setVista(destino)
  }, [])

  const abrirInforme = useCallback((datos: Corrida, desde: Grupo) => {
    setCorrida(datos)
    setGrupoOrigen(desde)
    setVista('informe')
  }, [])

  // El feedback actualiza el informe que se está viendo Y la foto que el
  // hilo guardó al terminar el análisis -- si no, volver a "Ver el informe"
  // desde la conversación muestra otra vez la corrida como si no se hubiera
  // revisado.
  const registrarFeedback = useCallback(
    (datos: Corrida) => {
      setCorrida(datos)
      analisis.actualizarCorrida(datos)
    },
    [analisis],
  )

  if (vista === 'informe' && corrida) {
    return (
      <ReportView
        corrida={corrida}
        grupo={grupoOrigen}
        // Solo se ofrece volver al hilo si el informe que se está viendo es
        // el de ESA conversación: volver desde una ejecución vieja llevaría
        // a un hilo que no tiene nada que ver.
        onVolverAlHilo={
          analisis.hayHilo && analisis.jobId === corrida.job_id
            ? () => navegar('analisis')
            : undefined
        }
        onNavegar={navegar}
        onFeedback={registrarFeedback}
      />
    )
  }

  if (vista === 'overview') {
    return <OverviewView onAbrir={(c) => abrirInforme(c, 'overview')} onNavegar={navegar} />
  }

  if (vista === 'historial') {
    return <HistorialView onAbrir={(c) => abrirInforme(c, 'historial')} onNavegar={navegar} />
  }

  if (vista === 'resultados') {
    return <ResultadosView onNavegar={navegar} />
  }

  return (
    <ConversacionView
      analisis={analisis}
      onAbrirInforme={(c) => abrirInforme(c, 'analisis')}
      onNavegar={navegar}
    />
  )
}
