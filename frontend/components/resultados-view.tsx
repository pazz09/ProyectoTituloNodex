'use client'

import { useCallback, useEffect, useState } from 'react'
import { AlertTriangle, Download, Loader2, RotateCcw } from 'lucide-react'

import { AppShell, type Vista } from '@/components/app-shell'
import { GraficoBarras } from '@/components/grafico-barras'
import type { ModeloBarras } from '@/lib/graficos'
import {
  descargarTexto,
  formatoCelda,
  listarResultados,
  nombreArchivo,
  nombreArquitectura,
  obtenerReporteCorrida,
  obtenerResultados,
  tablaACsv,
  type Advertencia,
  type FilaTabla,
  type ListaResultados,
  type ReporteCorrida,
  type ResumenResultados,
  type TablaResultados,
} from '@/lib/resultados'

/* ==========================================================================
   Vista "Resultados"

   Muestra lo que el consolidador calculó (`src/experimentation/consolidacion.py`)
   con los evaluadores del proyecto. NO calcula métricas, NO abre el ground
   truth y NO invoca modelos: es de solo lectura.

   Reglas de honestidad que condicionan el diseño:

   - Sin datos no hay cifras. Nada de números de ejemplo: el estado vacío lo
     dice con palabras.
   - `null` es "sin dato", no cero: se muestra como — y los gráficos lo marcan
     n/d en vez de dibujar una barra.
   - Las advertencias de integridad (fallback de modelo, telemetría previa a
     D-11, corridas ausentes o fallidas) van SIEMPRE junto a los números, no
     en una pantalla aparte: un resultado sin su salvedad se lee mal.
   ========================================================================== */

const MOTIVOS_VACIO: Record<string, string> = {
  d1_deteccion: 'No hay corridas evaluables de detección en esta consolidación.',
  d2_reconstruccion:
    'La reconstrucción solo se mide en UWF, el único dataset con identificador estable de evento. HDFS y BGL no aplican.',
  d3_mitre:
    'La atribución MITRE solo se mide en UWF, que trae técnicas en su referencia. HDFS y BGL no aplican.',
  d4_rubrica:
    'La rúbrica la puntúan dos personas. Todavía no hay puntajes cargados para esta configuración.',
  consumo: 'No hay telemetría de corridas completas en esta consolidación.',
  comparacion: 'Se necesitan resultados de más de una arquitectura para comparar.',
  errores_d1: 'No hay falsos positivos ni falsos negativos en esta consolidación.',
}

function tablaDe(resumen: ResumenResultados | null, id: string): TablaResultados | undefined {
  return resumen?.tablas?.[id]
}

function etiquetaFila(f: FilaTabla): string {
  return `${String(f.dataset ?? '')} · ${nombreArquitectura(String(f.arquitectura ?? ''))}`
}

function numeroONull(valor: unknown): number | null {
  return typeof valor === 'number' && Number.isFinite(valor) ? valor : null
}

// --- modelos de gráfico --------------------------------------------------------

export function modeloDetalle(
  tabla: TablaResultados | undefined,
  titulo: string,
  columnas: { clave: string; nombre: string }[],
  extra: Partial<ModeloBarras> = {},
): ModeloBarras {
  return {
    titulo,
    series: columnas.map((c) => ({ nombre: c.nombre })),
    grupos: (tabla?.filas ?? []).map((f) => ({
      etiqueta: etiquetaFila(f),
      valores: columnas.map((c) => numeroONull(f[c.clave])),
    })),
    ...extra,
  }
}

export function modeloComparacion(tabla: TablaResultados | undefined): ModeloBarras {
  const arquitecturas = ['nodex_multiagente', 'baseline_reglas', 'gemini_externo']
  return {
    titulo: 'NODEX frente al baseline y a Gemini directo',
    series: arquitecturas.map((a) => ({ nombre: nombreArquitectura(a) })),
    grupos: (tabla?.filas ?? [])
      .filter((f) => typeof f.metrica === 'string' && /f1|exact/i.test(String(f.metrica)))
      .map((f) => ({
        etiqueta: `${String(f.dataset)} · ${String(f.metrica).replace(/_/g, ' ')}`,
        valores: arquitecturas.map((a) => numeroONull(f[a])),
      })),
  }
}

// --- piezas ------------------------------------------------------------------

const CLASE_SEVERIDAD: Record<Advertencia['severidad'], string> = {
  alta: 'crit',
  media: 'warn',
  info: 'info',
}

/** Salvedades de integridad. Se repite en cada sección para que viajen con los números. */
export function AvisosIntegridad({ resumen }: { resumen: ResumenResultados }) {
  const avisos = resumen.integridad.advertencias
  if (avisos.length === 0) {
    return (
      <div className="avisos-integridad">
        <span className="chip ok">sin advertencias de integridad</span>
      </div>
    )
  }
  return (
    <div className="avisos-integridad" role="note" aria-label="Advertencias de integridad">
      {avisos.map((a) => (
        <span key={a.codigo} className={`chip ${CLASE_SEVERIDAD[a.severidad]}`} title={a.mensaje}>
          {a.n > 0 ? `${a.n} · ` : ''}
          {a.mensaje}
        </span>
      ))}
    </div>
  )
}

function BotonCsv({ tabla, nombre }: { tabla: TablaResultados; nombre: string }) {
  return (
    <button
      className="btn"
      onClick={() =>
        descargarTexto(`${nombre}.csv`, tablaACsv(tabla), 'text/csv;charset=utf-8')
      }
      title="Descargar esta tabla en CSV"
    >
      <Download size={14} /> CSV
    </button>
  )
}

function TablaDatos({
  tabla,
  nombre,
  acciones,
}: {
  tabla: TablaResultados
  nombre: string
  acciones?: (fila: FilaTabla) => React.ReactNode
}) {
  return (
    <div className="bloque-tabla">
      <div className="bloque-tabla-cabecera">
        <h3>{tabla.titulo}</h3>
        <BotonCsv tabla={tabla} nombre={nombre} />
      </div>
      {tabla.descripcion && <p className="nota-tabla">{tabla.descripcion}</p>}
      <div className="table-scroll">
        <table className="table">
          <thead>
            <tr>
              {tabla.columnas.map((c) => (
                <th key={c.clave}>{c.etiqueta}</th>
              ))}
              {acciones && <th />}
            </tr>
          </thead>
          <tbody>
            {tabla.filas.map((fila, i) => (
              <tr key={i}>
                {tabla.columnas.map((c) => {
                  const numerica = c.tipo && c.tipo !== 'texto'
                  // En pantalla la arquitectura va con su nombre legible; el
                  // CSV conserva la clave tal cual, porque es un dato.
                  const texto =
                    c.clave === 'arquitectura' && typeof fila[c.clave] === 'string'
                      ? nombreArquitectura(String(fila[c.clave]))
                      : formatoCelda(fila[c.clave], c.tipo)
                  return (
                    <td key={c.clave} className={numerica ? 'num' : 'mono'}>
                      {texto}
                    </td>
                  )
                })}
                {acciones && <td className="nowrap">{acciones(fila)}</td>}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function Seccion({
  numero,
  titulo,
  descripcion,
  resumen,
  children,
}: {
  numero: string
  titulo: string
  descripcion: string
  resumen: ResumenResultados
  children: React.ReactNode
}) {
  return (
    <section className="panel" id={`seccion-${numero.replace('.', '-')}`}>
      <div className="panel-head">
        <h2>
          <span className="num-seccion">{numero}</span> {titulo}
        </h2>
        <p>{descripcion}</p>
      </div>
      <div className="panel-body">
        <AvisosIntegridad resumen={resumen} />
        {children}
      </div>
    </section>
  )
}

function Vacio({ id }: { id: string }) {
  return (
    <p className="prose empty">
      Sin datos para esta sección. {MOTIVOS_VACIO[id] ?? ''}
    </p>
  )
}

function Integridad({ resumen }: { resumen: ResumenResultados }) {
  const i = resumen.integridad
  const celdas: [string, number][] = [
    ['Corridas esperadas', i.corridas_esperadas],
    ['Presentes', i.corridas_presentes],
    ['Completas', i.corridas_completas],
    ['Ausentes', i.corridas_ausentes.length],
    ['Fallidas', i.corridas_fallidas.length],
    ['Con fallback de modelo', i.corridas_con_fallback.length],
  ]
  return (
    <section className="panel" id="integridad">
      <div className="panel-head">
        <h2>Integridad de los datos</h2>
        <p>
          Qué tan completo y comparable es lo que se muestra abajo. Las corridas fallidas y las que
          usaron otro modelo se muestran, no se ocultan.
        </p>
      </div>
      <div className="panel-body">
        <div className="kpis" style={{ marginBottom: 18 }}>
          {celdas.map(([etiqueta, valor]) => (
            <div className="kpi" key={etiqueta}>
              <div className="kpi-top">
                <b>{valor}</b>
              </div>
              <span>{etiqueta}</span>
            </div>
          ))}
        </div>
        <AvisosIntegridad resumen={resumen} />
        {!i.fallback_determinable && (
          <p className="nota-tabla">
            No hay configuración congelada para esta campaña, así que no se puede determinar si
            alguna corrida usó el modelo de respaldo.
          </p>
        )}
        {i.corridas_fallidas.length > 0 && (
          <ul className="lista-fallidas">
            {i.corridas_fallidas.map((f) => (
              <li key={f.run_id}>
                <code>{f.run_id}</code> — {f.estado ?? 'sin estado'}
                {f.error ? `: ${f.error}` : ''}
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  )
}

// --- contenido (presentacional, sin red) ---------------------------------------

export type PropsContenido = {
  lista: ListaResultados | null
  configSeleccionada: string | null
  consolidacionSeleccionada: string | null
  resumen: ResumenResultados | null
  cargando: boolean
  error: string | null
  reporte: ReporteCorrida | null
  cargandoReporte: boolean
  errorReporte: string | null
  onSeleccionarConfig: (config: string) => void
  onSeleccionarConsolidacion: (marca: string) => void
  onActualizar: () => void
  onVerReporte: (runId: string) => void
  onCerrarReporte: () => void
}

export function ResultadosContenido(p: PropsContenido) {
  const { lista, resumen } = p
  const configuraciones = lista?.configuraciones ?? []
  const base = resumen ? nombreArchivo(resumen.config_version, resumen.consolidacion) : 'resultados'

  return (
    <>
      <div className="view-head">
        <h1>Resultados</h1>
        <p>
          Resultados de la evaluación experimental, organizados como las secciones 11.1 a 11.7 del
          informe. Esta pantalla solo lee: no ejecuta el sistema, no consulta modelos y no abre las
          respuestas correctas.
        </p>
        <div className="acciones">
          {configuraciones.length > 0 && (
            <>
              <label className="selector">
                <span>Configuración</span>
                <select
                  value={p.configSeleccionada ?? ''}
                  onChange={(e) => p.onSeleccionarConfig(e.target.value)}
                >
                  {configuraciones.map((c) => (
                    <option key={c.config_version} value={c.config_version}>
                      {c.config_version}
                    </option>
                  ))}
                </select>
              </label>
              <label className="selector">
                <span>Consolidación</span>
                <select
                  value={p.consolidacionSeleccionada ?? ''}
                  onChange={(e) => p.onSeleccionarConsolidacion(e.target.value)}
                >
                  {(configuraciones.find((c) => c.config_version === p.configSeleccionada)
                    ?.consolidaciones ?? []
                  ).map((m) => (
                    <option key={m} value={m}>
                      {m}
                    </option>
                  ))}
                </select>
              </label>
            </>
          )}
          <button className="btn" onClick={p.onActualizar} disabled={p.cargando}>
            <RotateCcw size={14} /> Actualizar
          </button>
        </div>
      </div>

      {p.error && (
        <div className="notice-block" role="alert">
          <div className="icono-aviso">
            <AlertTriangle size={16} />
          </div>
          <div>
            <strong>No se pudieron cargar los resultados</strong>
            <p>{p.error}</p>
          </div>
          <button className="btn" onClick={p.onActualizar}>
            Reintentar
          </button>
        </div>
      )}

      {p.cargando && (
        <section className="panel">
          <div className="panel-body">
            <p className="prose empty">
              <Loader2 size={14} className="spin" /> Cargando…
            </p>
          </div>
        </section>
      )}

      {!p.cargando && !p.error && !resumen && (
        <section className="panel" id="sin-resultados">
          <div className="panel-head">
            <h2>Todavía no hay resultados experimentales</h2>
          </div>
          <div className="panel-body">
            <p className="prose empty">
              Esta pantalla se llena cuando se consolidan las corridas de una campaña. Mientras
              tanto no se muestra ninguna cifra: ni de ejemplo ni estimada.
            </p>
          </div>
        </section>
      )}

      {resumen && (
        <>
          {resumen.datos_ficticios && (
            <div className="notice-block" role="alert" id="aviso-ficticio">
              <div className="icono-aviso">
                <AlertTriangle size={16} />
              </div>
              <div>
                <strong>DATOS FICTICIOS</strong>
                <p>
                  Estas cifras son de una prueba de la interfaz. No son resultados experimentales
                  y no deben citarse.
                </p>
              </div>
            </div>
          )}

          <Integridad resumen={resumen} />

          <Seccion
            numero="11.1"
            titulo="Detección"
            descripcion="Matriz de confusión y precisión, exhaustividad y F1 por dataset y arquitectura."
            resumen={resumen}
          >
            {tablaDe(resumen, 'd1_deteccion')?.filas.length ? (
              <>
                <GraficoBarras
                  nombreBase={`${base}_d1`}
                  modelo={modeloDetalle(
                    tablaDe(resumen, 'd1_deteccion'),
                    'Detección: precisión, exhaustividad y F1',
                    [
                      { clave: 'precision', nombre: 'Precisión' },
                      { clave: 'recall', nombre: 'Exhaustividad' },
                      { clave: 'f1', nombre: 'F1' },
                    ],
                  )}
                />
                <TablaDatos tabla={tablaDe(resumen, 'd1_deteccion')!} nombre={`${base}_d1_deteccion`} />
                {tablaDe(resumen, 'd1_condiciones')?.filas.length ? (
                  <TablaDatos
                    tabla={tablaDe(resumen, 'd1_condiciones')!}
                    nombre={`${base}_d1_condiciones`}
                  />
                ) : null}
              </>
            ) : (
              <Vacio id="d1_deteccion" />
            )}
          </Seccion>

          <Seccion
            numero="11.2"
            titulo="Reconstrucción del incidente"
            descripcion="Coincidencia exacta, por uid, entre los eventos que cita el sistema y los del incidente."
            resumen={resumen}
          >
            {tablaDe(resumen, 'd2_reconstruccion')?.filas.length ? (
              <>
                <GraficoBarras
                  nombreBase={`${base}_d2`}
                  modelo={modeloDetalle(
                    tablaDe(resumen, 'd2_reconstruccion'),
                    'Reconstrucción: métricas de conjunto (micro)',
                    [
                      { clave: 'micro_precision', nombre: 'Precisión' },
                      { clave: 'micro_recall', nombre: 'Exhaustividad' },
                      { clave: 'micro_f1', nombre: 'F1' },
                      { clave: 'exact_match', nombre: 'Coincidencia exacta' },
                    ],
                  )}
                />
                <TablaDatos
                  tabla={tablaDe(resumen, 'd2_reconstruccion')!}
                  nombre={`${base}_d2_reconstruccion`}
                />
              </>
            ) : (
              <Vacio id="d2_reconstruccion" />
            )}
          </Seccion>

          <Seccion
            numero="11.3"
            titulo="Identificación MITRE ATT&CK"
            descripcion="Técnicas atribuidas frente a label_technique, solo a nivel de técnica. Una atribución sin evidencia citada no cuenta."
            resumen={resumen}
          >
            {tablaDe(resumen, 'd3_mitre')?.filas.length ? (
              <>
                <GraficoBarras
                  nombreBase={`${base}_d3`}
                  modelo={modeloDetalle(
                    tablaDe(resumen, 'd3_mitre'),
                    'MITRE: métricas de conjunto (micro)',
                    [
                      { clave: 'micro_precision', nombre: 'Precisión' },
                      { clave: 'micro_recall', nombre: 'Exhaustividad' },
                      { clave: 'micro_f1', nombre: 'F1' },
                      { clave: 'exact_match', nombre: 'Coincidencia exacta' },
                    ],
                  )}
                />
                <TablaDatos tabla={tablaDe(resumen, 'd3_mitre')!} nombre={`${base}_d3_mitre`} />
              </>
            ) : (
              <Vacio id="d3_mitre" />
            )}
          </Seccion>

          <Seccion
            numero="11.4"
            titulo="Calidad del reporte"
            descripcion="Puntajes de la rúbrica (0 a 3) y concordancia entre los dos evaluadores. No se calcula kappa."
            resumen={resumen}
          >
            {tablaDe(resumen, 'd4_rubrica')?.filas.length ? (
              <>
                <GraficoBarras
                  nombreBase={`${base}_d4`}
                  modelo={modeloDetalle(
                    tablaDe(resumen, 'd4_rubrica'),
                    'Rúbrica: promedio por criterio',
                    [
                      { clave: 'completitud', nombre: 'Completitud' },
                      { clave: 'correccion_factual', nombre: 'Corrección factual' },
                      { clave: 'coherencia_con_evidencia', nombre: 'Coherencia' },
                      { clave: 'claridad', nombre: 'Claridad' },
                      { clave: 'informacion_no_sustentada', nombre: 'Sin info. inventada' },
                    ],
                    { formato: 'numero', techoFijo: 3 },
                  )}
                />
                <TablaDatos tabla={tablaDe(resumen, 'd4_rubrica')!} nombre={`${base}_d4_rubrica`} />
              </>
            ) : (
              <Vacio id="d4_rubrica" />
            )}
          </Seccion>

          <Seccion
            numero="11.5"
            titulo="Consumo y comportamiento operacional"
            descripcion="Tiempo, llamadas al modelo, tokens, replanificaciones y correcciones. Solo promedian las corridas completas."
            resumen={resumen}
          >
            {tablaDe(resumen, 'consumo')?.filas.length ? (
              <>
                <div className="grid-2">
                  <GraficoBarras
                    nombreBase={`${base}_consumo_tiempo`}
                    modelo={modeloDetalle(
                      tablaDe(resumen, 'consumo'),
                      'Tiempo por corrida',
                      [
                        { clave: 'tiempo_medio_s', nombre: 'Media' },
                        { clave: 'tiempo_mediana_s', nombre: 'Mediana' },
                      ],
                      { formato: 'numero', unidad: 's' },
                    )}
                  />
                  <GraficoBarras
                    nombreBase={`${base}_consumo_tokens`}
                    modelo={modeloDetalle(
                      tablaDe(resumen, 'consumo'),
                      'Tokens por corrida',
                      [
                        { clave: 'tokens_entrada_medios', nombre: 'Entrada' },
                        { clave: 'tokens_salida_medios', nombre: 'Salida' },
                      ],
                      { formato: 'numero', unidad: 'tokens' },
                    )}
                    vacio="Sin tokens: el proveedor no informó el consumo de ninguna corrida."
                  />
                </div>
                <GraficoBarras
                  nombreBase={`${base}_consumo_llamadas`}
                  modelo={modeloDetalle(
                    tablaDe(resumen, 'consumo'),
                    'Llamadas al modelo, replanificaciones y correcciones por corrida',
                    [
                      { clave: 'llamadas_medias', nombre: 'Llamadas' },
                      { clave: 'replan_medio', nombre: 'Replanificaciones' },
                      { clave: 'correcciones_medias', nombre: 'Correcciones' },
                    ],
                    { formato: 'numero' },
                  )}
                />
                <TablaDatos tabla={tablaDe(resumen, 'consumo')!} nombre={`${base}_consumo`} />
              </>
            ) : (
              <Vacio id="consumo" />
            )}
          </Seccion>

          <Seccion
            numero="11.6"
            titulo="NODEX frente al baseline y a Gemini directo"
            descripcion="Las tres arquitecturas sobre los mismos casos, cuando hay datos de más de una."
            resumen={resumen}
          >
            <div className="notice-block aviso" id="aviso-baseline">
              <div className="icono-aviso">
                <AlertTriangle size={16} />
              </div>
              <div>
                <strong>En UWF el baseline responde otra pregunta</strong>
                <p>
                  Sus reglas son operativas (severidad, proporción de fallos, concentración por
                  IP). UWF pregunta por actividad maliciosa, y un escaneo exitoso no produce
                  fallos. Allí la comparación con el baseline es contextual, no pareada. En BGL
                  sí es pareada. Gemini directo no usa RAG ni herramientas, por diseño: es una
                  comparación entre el sistema completo y el modelo, no entre dos variantes que
                  difieren en una sola cosa.
                </p>
              </div>
            </div>
            {tablaDe(resumen, 'comparacion')?.filas.length ? (
              <>
                <GraficoBarras
                  nombreBase={`${base}_comparacion`}
                  modelo={modeloComparacion(tablaDe(resumen, 'comparacion'))}
                  vacio="Sin métricas comparables todavía."
                />
                <TablaDatos
                  tabla={tablaDe(resumen, 'comparacion')!}
                  nombre={`${base}_comparacion`}
                />
              </>
            ) : (
              <Vacio id="comparacion" />
            )}
          </Seccion>

          <Seccion
            numero="11.7"
            titulo="Falsos positivos y falsos negativos"
            descripcion="Cada error de detección, con enlace al reporte que produjo el sistema en esa corrida."
            resumen={resumen}
          >
            {tablaDe(resumen, 'errores_d1')?.filas.length ? (
              <TablaDatos
                tabla={tablaDe(resumen, 'errores_d1')!}
                nombre={`${base}_errores`}
                acciones={(fila) => (
                  <button
                    className="btn"
                    onClick={() => p.onVerReporte(String(fila.run_id))}
                    disabled={p.cargandoReporte}
                  >
                    Ver reporte
                  </button>
                )}
              />
            ) : (
              <Vacio id="errores_d1" />
            )}

            {(p.reporte || p.cargandoReporte || p.errorReporte) && (
              <div className="reporte-corrida" id="reporte-corrida">
                <div className="bloque-tabla-cabecera">
                  <h3>Reporte de la corrida {p.reporte ? p.reporte.run_id : ''}</h3>
                  <button className="btn" onClick={p.onCerrarReporte}>
                    Cerrar
                  </button>
                </div>
                {p.cargandoReporte && (
                  <p className="prose empty">
                    <Loader2 size={14} className="spin" /> Cargando…
                  </p>
                )}
                {p.errorReporte && <p className="figura-error">{p.errorReporte}</p>}
                {p.reporte && (
                  <>
                    <p className="nota-tabla">
                      {p.reporte.dataset} · {nombreArquitectura(p.reporte.arquitectura)} · repetición{' '}
                      {p.reporte.repeticion} · estado {p.reporte.estado_ejecucion ?? '—'} ·
                      clasificación {p.reporte.clasificacion ?? '—'}
                    </p>
                    {p.reporte.reporte ? (
                      <pre className="reporte-texto">{p.reporte.reporte}</pre>
                    ) : (
                      <p className="prose empty">
                        Esta corrida no produjo un reporte.
                        {p.reporte.motivo_no_evaluable ? ` ${p.reporte.motivo_no_evaluable}` : ''}
                      </p>
                    )}
                  </>
                )}
              </div>
            )}
          </Seccion>
        </>
      )}
    </>
  )
}

// --- contenedor con red -----------------------------------------------------------

type Carga = {
  lista: ListaResultados
  config: string | null
  consolidacion: string | null
  resumen: ResumenResultados | null
}

/**
 * Trae la lista y el resumen de una configuración. No toca el estado de React:
 * solo devuelve datos. Así la carga inicial puede correr dentro de un efecto
 * sin llamar a `setState` de forma síncrona, y las recargas manuales usan la
 * misma función.
 */
async function traer(cfg: string | null, marca: string | null): Promise<Carga> {
  const lista = await listarResultados()
  const elegida =
    lista.configuraciones.find((c) => c.config_version === cfg) ?? lista.configuraciones[0]
  if (!elegida) return { lista, config: null, consolidacion: null, resumen: null }
  const marcaElegida = marca && elegida.consolidaciones.includes(marca) ? marca : elegida.ultima
  const resumen = await obtenerResultados(elegida.config_version, marcaElegida ?? undefined)
  return { lista, config: elegida.config_version, consolidacion: marcaElegida, resumen }
}

export function ResultadosView({ onNavegar }: { onNavegar: (vista: Vista) => void }) {
  const [lista, setLista] = useState<ListaResultados | null>(null)
  const [config, setConfig] = useState<string | null>(null)
  const [consolidacion, setConsolidacion] = useState<string | null>(null)
  const [resumen, setResumen] = useState<ResumenResultados | null>(null)
  const [cargando, setCargando] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [reporte, setReporte] = useState<ReporteCorrida | null>(null)
  const [cargandoReporte, setCargandoReporte] = useState(false)
  const [errorReporte, setErrorReporte] = useState<string | null>(null)

  const aplicar = useCallback((carga: Carga) => {
    setLista(carga.lista)
    setConfig(carga.config)
    setConsolidacion(carga.consolidacion)
    setResumen(carga.resumen)
    setReporte(null)
  }, [])

  // Recarga manual (botón y selectores).
  const recargar = useCallback(
    async (cfg: string | null, marca: string | null) => {
      setCargando(true)
      setError(null)
      try {
        aplicar(await traer(cfg, marca))
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e))
        setResumen(null)
      } finally {
        setCargando(false)
      }
    },
    [aplicar],
  )

  // Carga inicial. `cargando` ya arranca en true, así que no hace falta
  // activarlo acá; y `activo` evita actualizar una vista ya desmontada.
  useEffect(() => {
    let activo = true
    traer(null, null)
      .then((carga) => {
        if (activo) aplicar(carga)
      })
      .catch((e) => {
        if (activo) setError(e instanceof Error ? e.message : String(e))
      })
      .finally(() => {
        if (activo) setCargando(false)
      })
    return () => {
      activo = false
    }
  }, [aplicar])

  const verReporte = useCallback(
    async (runId: string) => {
      if (!config) return
      setCargandoReporte(true)
      setErrorReporte(null)
      setReporte(null)
      try {
        setReporte(await obtenerReporteCorrida(config, runId))
      } catch (e) {
        setErrorReporte(e instanceof Error ? e.message : String(e))
      } finally {
        setCargandoReporte(false)
      }
    },
    [config],
  )

  return (
    <AppShell grupo="resultados" onNavegar={onNavegar}>
      <ResultadosContenido
        lista={lista}
        configSeleccionada={config}
        consolidacionSeleccionada={consolidacion}
        resumen={resumen}
        cargando={cargando}
        error={error}
        reporte={reporte}
        cargandoReporte={cargandoReporte}
        errorReporte={errorReporte}
        onSeleccionarConfig={(c) => recargar(c, null)}
        onSeleccionarConsolidacion={(m) => recargar(config, m)}
        onActualizar={() => recargar(config, consolidacion)}
        onVerReporte={verReporte}
        onCerrarReporte={() => {
          setReporte(null)
          setErrorReporte(null)
        }}
      />
    </AppShell>
  )
}
