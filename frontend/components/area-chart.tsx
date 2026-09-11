'use client'

import { useId } from 'react'

export type Punto = { etiqueta: string; valor: number }

/**
 * Gráfico de área en SVG, sin librería.
 *
 * Se dibuja a mano en vez de sumar una dependencia de gráficos a un
 * prototipo: lo único que hace falta es un área con degradado y una línea
 * encima, que es lo que muestra la referencia de diseño.
 *
 * La curva usa una interpolación monótona (Fritsch–Carlson): una spline
 * cúbica común puede producir sobreimpulsos que dibujan valores negativos
 * donde el dato es cero, y en una serie de conteos eso sería mentir sobre
 * el dato.
 */
export function AreaChart({
  puntos,
  alto = 210,
  formatoValor = (v: number) => String(v),
  vacio = 'Sin datos suficientes para trazar la serie.',
}: {
  puntos: Punto[]
  alto?: number
  formatoValor?: (v: number) => string
  vacio?: string
}) {
  const id = useId()

  // Con menos de dos puntos no hay serie que trazar, y un área de un solo
  // punto se lee como un dato inventado.
  if (puntos.length < 2) {
    return <div className="chart-vacio">{vacio}</div>
  }

  const ancho = 760
  const margen = { arriba: 14, derecha: 8, abajo: 30, izquierda: 46 }
  const w = ancho - margen.izquierda - margen.derecha
  const h = alto - margen.arriba - margen.abajo

  const maximo = Math.max(...puntos.map((p) => p.valor), 1)
  // Techo redondeado hacia arriba, para que la última guía sea un número
  // legible y no el máximo exacto de la serie.
  const techo = Math.ceil(maximo * 1.15)

  const x = (i: number) => margen.izquierda + (i / (puntos.length - 1)) * w
  const y = (v: number) => margen.arriba + h - (v / techo) * h

  // --- interpolación monótona ---------------------------------------------
  const n = puntos.length
  const dx = Array.from({ length: n - 1 }, (_, i) => x(i + 1) - x(i))
  const dy = Array.from({ length: n - 1 }, (_, i) => y(puntos[i + 1].valor) - y(puntos[i].valor))
  const pendientes = dx.map((d, i) => dy[i] / d)

  const m: number[] = new Array(n)
  m[0] = pendientes[0]
  m[n - 1] = pendientes[n - 2]
  for (let i = 1; i < n - 1; i++) {
    if (pendientes[i - 1] * pendientes[i] <= 0) {
      m[i] = 0 // extremo local: tangente plana, sin sobreimpulso
    } else {
      m[i] = (pendientes[i - 1] + pendientes[i]) / 2
    }
  }

  let curva = `M ${x(0)} ${y(puntos[0].valor)}`
  for (let i = 0; i < n - 1; i++) {
    const c1x = x(i) + dx[i] / 3
    const c1y = y(puntos[i].valor) + (m[i] * dx[i]) / 3
    const c2x = x(i + 1) - dx[i] / 3
    const c2y = y(puntos[i + 1].valor) - (m[i + 1] * dx[i]) / 3
    curva += ` C ${c1x} ${c1y}, ${c2x} ${c2y}, ${x(i + 1)} ${y(puntos[i + 1].valor)}`
  }
  const area = `${curva} L ${x(n - 1)} ${margen.arriba + h} L ${x(0)} ${margen.arriba + h} Z`

  const guias = [0, 0.5, 1].map((f) => Math.round(techo * f))
  // En series cortas cabe toda etiqueta; en series largas se saltean para no
  // amontonarlas.
  const paso = Math.ceil(puntos.length / 8)

  return (
    <svg className="chart" viewBox={`0 0 ${ancho} ${alto}`} role="img" preserveAspectRatio="none">
      <defs>
        <linearGradient id={`grad-${id}`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="var(--accent)" stopOpacity="0.42" />
          <stop offset="100%" stopColor="var(--accent)" stopOpacity="0" />
        </linearGradient>
      </defs>

      {guias.map((v) => (
        <g key={v}>
          <line className="guia" x1={margen.izquierda} x2={ancho - margen.derecha} y1={y(v)} y2={y(v)} />
          <text className="eje" x={margen.izquierda - 10} y={y(v) + 4} textAnchor="end">
            {formatoValor(v)}
          </text>
        </g>
      ))}

      <path d={area} fill={`url(#grad-${id})`} />
      <path className="linea" d={curva} />

      {puntos.map((p, i) =>
        i % paso === 0 || i === puntos.length - 1 ? (
          <text className="eje" key={`${p.etiqueta}-${i}`} x={x(i)} y={alto - 8} textAnchor="middle">
            {p.etiqueta}
          </text>
        ) : null,
      )}
    </svg>
  )
}
