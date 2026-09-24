'use client'

import { useCallback, useEffect, useRef, useState } from 'react'

import {
  obtenerCorrida,
  subirArchivo,
  urlDelStream,
  type Corrida,
  type EventoSse,
  type ResumenLote,
} from '@/lib/api'
import type { NombreNodo } from '@/lib/nodos'

/** Un mensaje del hilo. El contenido lo arma la vista. */
export type Mensaje =
  | { rol: 'usuario'; id: string; nombre: string; peso: number }
  | { rol: 'inicio'; id: string; hora: string; resumen: ResumenLote }
  | {
      rol: 'nodo'
      id: string
      hora: string
      nodo: NombreNodo
      visita: number
      detalle: Record<string, unknown>
    }
  | { rol: 'cierre'; id: string; hora: string; corrida: Corrida }
  | { rol: 'error'; id: string; hora: string; mensaje: string }

function hora() {
  return new Date().toLocaleTimeString('es', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

/**
 * Estado del análisis en curso, por encima del cambio de vista.
 *
 * Vive en el componente que enruta las vistas y no dentro de la
 * conversación: si viviera ahí, ir a Resumen o a Ejecuciones desmontaría la
 * vista y el hilo se perdería. Con el estado arriba, el hilo sobrevive a la
 * navegación **y** el `EventSource` sigue recibiendo mensajes mientras se
 * mira otra pantalla, así que al volver la conversación está completa.
 */
export function useAnalisis() {
  const [mensajes, setMensajes] = useState<Mensaje[]>([])
  const [jobId, setJobId] = useState<string | null>(null)
  const [nombreArchivo, setNombreArchivo] = useState<string | null>(null)
  const [corriendo, setCorriendo] = useState(false)
  const [errorCarga, setErrorCarga] = useState<string | null>(null)
  const [corrida, setCorrida] = useState<Corrida | null>(null)

  const visitas = useRef<Record<string, number>>({})
  const fuente = useRef<EventSource | null>(null)

  // Cierra el stream si el árbol se desmonta (recarga, navegación real).
  useEffect(() => () => fuente.current?.close(), [])

  const analizar = useCallback(async (archivo: File) => {
    if (fuente.current) {
      fuente.current.close()
      fuente.current = null
    }
    setCorriendo(true)
    setErrorCarga(null)
    setCorrida(null)
    visitas.current = {}
    setNombreArchivo(archivo.name)
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

    const es = new EventSource(urlDelStream(id))
    fuente.current = es
    // El backend no emite `final` después de un `error`, así que este flag
    // distingue "terminó" de "se cortó la conexión".
    let cerrado = false

    es.onmessage = (m) => {
      const ev: EventoSse = JSON.parse(m.data)

      if (ev.tipo === 'inicio') {
        setMensajes((prev) => [
          ...prev,
          { rol: 'inicio', id: 'inicio', hora: hora(), resumen: ev.resumen },
        ])
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
        setMensajes((prev) => [
          ...prev,
          { rol: 'error', id: 'err', hora: hora(), mensaje: ev.mensaje },
        ])
        setCorriendo(false)
        es.close()
      } else if (ev.tipo === 'final') {
        cerrado = true
        es.close()
        // El evento `final` no trae el job_id ni los datos del archivo: se
        // pide la fila del historial, el mismo shape que consume el informe.
        obtenerCorrida(id)
          .then((c) => {
            setCorrida(c)
            setMensajes((prev) => [
              ...prev,
              { rol: 'cierre', id: 'cierre', hora: hora(), corrida: c },
            ])
          })
          .catch((e) =>
            setMensajes((prev) => [
              ...prev,
              {
                rol: 'error',
                id: 'err',
                hora: hora(),
                mensaje: e instanceof Error ? e.message : String(e),
              },
            ]),
          )
          .finally(() => setCorriendo(false))
      }
    }

    es.onerror = () => {
      if (!cerrado) {
        setMensajes((prev) => [
          ...prev,
          {
            rol: 'error',
            id: 'err',
            hora: hora(),
            mensaje:
              'Se perdió la conexión con el servidor durante la ejecución. El análisis puede ' +
              'haber continuado: revisá las ejecuciones antes de reintentar.',
          },
        ])
        setCorriendo(false)
      }
      es.close()
    }
  }, [])

  // El mensaje `cierre` guarda una foto fija de la corrida tomada al
  // terminar el stream. Si después se da feedback desde el informe, esa foto
  // queda desactualizada: al volver al hilo y reabrir "Ver el informe" se
  // vuelve a ver la corrida sin revisar. Esto la mantiene al día.
  const actualizarCorrida = useCallback((actualizada: Corrida) => {
    setCorrida((prev) => (prev && prev.job_id === actualizada.job_id ? actualizada : prev))
    setMensajes((prev) =>
      prev.map((m) =>
        m.rol === 'cierre' && m.corrida.job_id === actualizada.job_id
          ? { ...m, corrida: actualizada }
          : m,
      ),
    )
  }, [])

  const reiniciar = useCallback(() => {
    fuente.current?.close()
    fuente.current = null
    setMensajes([])
    setJobId(null)
    setNombreArchivo(null)
    setCorrida(null)
    setErrorCarga(null)
    setCorriendo(false)
    visitas.current = {}
  }, [])

  return {
    mensajes,
    jobId,
    nombreArchivo,
    corriendo,
    errorCarga,
    /** Corrida terminada de ESTE hilo, si ya llegó el cierre. */
    corrida,
    analizar,
    reiniciar,
    actualizarCorrida,
    setErrorCarga,
    /** Hay un hilo al que se puede volver. */
    hayHilo: mensajes.length > 0,
  }
}

export type EstadoAnalisis = ReturnType<typeof useAnalisis>
