'use client'

import { useState } from 'react'
import { Download } from 'lucide-react'

import { geometriaBarras, svgDeBarras, type ModeloBarras } from '@/lib/graficos'
import { descargarBlob, descargarTexto, nombreArchivo, svgAPng } from '@/lib/resultados'

/**
 * Gráfico de barras agrupadas con descarga en SVG y PNG.
 *
 * La pantalla muestra el MISMO SVG que se descarga (con la paleta oscura de
 * la interfaz), y la exportación usa la paleta para papel. Los dos salen de
 * `svgDeBarras`, así que no hay una segunda maqueta que pueda divergir.
 *
 * Si todos los valores son `null`, no se dibuja nada y se dice por qué: un
 * gráfico de barras vacío se lee como "el sistema obtuvo cero".
 */
export function GraficoBarras({
  modelo,
  nombreBase,
  vacio = 'Sin datos para graficar.',
}: {
  modelo: ModeloBarras
  /** Prefijo del archivo descargado. */
  nombreBase: string
  vacio?: string
}) {
  const [error, setError] = useState<string | null>(null)

  const hayDatos = modelo.grupos.some((g) => g.valores.some((v) => v !== null))
  if (!hayDatos) {
    return <div className="chart-vacio">{vacio}</div>
  }

  const geometria = geometriaBarras(modelo, 'impresion')

  const descargarSvg = () => {
    setError(null)
    descargarTexto(
      nombreArchivo(nombreBase, 'grafico') + '.svg',
      svgDeBarras(modelo, 'impresion'),
      'image/svg+xml;charset=utf-8',
    )
  }

  const descargarPng = async () => {
    setError(null)
    try {
      const png = await svgAPng(svgDeBarras(modelo, 'impresion'), geometria.ancho, geometria.alto)
      descargarBlob(nombreArchivo(nombreBase, 'grafico') + '.png', png)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  return (
    <figure className="figura">
      <div
        className="grafico-barras"
        // El SVG lo arma `svgDeBarras` con todo el texto escapado.
        dangerouslySetInnerHTML={{ __html: svgDeBarras(modelo, 'pantalla') }}
      />
      <figcaption className="figura-pie">
        <button className="btn" onClick={descargarSvg} title="Descargar el gráfico en SVG">
          <Download size={14} /> SVG
        </button>
        <button className="btn" onClick={descargarPng} title="Descargar el gráfico en PNG">
          <Download size={14} /> PNG
        </button>
        {error && <span className="figura-error">{error}</span>}
      </figcaption>
    </figure>
  )
}
