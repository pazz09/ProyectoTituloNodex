/**
 * Los 7 nodos reales del grafo y el estado del avance.
 *
 * El progreso NO es lineal, y el modelo de estado tiene que soportarlo:
 *
 *  - `agente_analista_triage` se ejecuta de nuevo después del RAG (confirmado
 *    en corridas reales), así que un paso ya completado puede volver a estar
 *    activo.
 *  - `tool_consultar_rag` y `tool_consultar_cve` pueden no ejecutarse nunca:
 *    lo decide `agente_selector_herramientas`.
 *  - `agente_ingeniero_mitigacion` y `tool_validar_comandos` pueden repetirse
 *    si el validador rechaza los comandos (ciclo de corrección).
 *
 * Por eso el estado es un mapa por nodo con visitas contadas, en vez de un
 * índice que solo avanza.
 */

export type NombreNodo =
  | 'agente_analista_triage'
  | 'agente_selector_herramientas'
  | 'tool_consultar_rag'
  | 'tool_consultar_cve'
  | 'agente_ingeniero_mitigacion'
  | 'tool_validar_comandos'
  | 'agente_auditor_final'

export type Nodo = {
  nombre: NombreNodo
  titulo: string
  /** Qué está haciendo, en lenguaje llano, para mostrar mientras corre. */
  descripcion: string
  /** `true` si el selector puede decidir no ejecutarlo. */
  opcional?: boolean
}

export const NODOS: Nodo[] = [
  {
    nombre: 'agente_analista_triage',
    titulo: 'Análisis inicial',
    descripcion:
      'Leyendo el archivo y buscando señales de comportamiento anómalo...',
  },
  {
    nombre: 'agente_selector_herramientas',
    titulo: 'Selección de herramientas',
    descripcion:
      'Decidiendo qué información adicional necesita para confirmar el diagnóstico...',
  },
  {
    nombre: 'tool_consultar_rag',
    titulo: 'Memoria y técnicas conocidas',
    descripcion:
      'Buscando en la memoria de casos anteriores y en la base de técnicas de ataque conocidas (MITRE ATT&CK) patrones similares...',
    opcional: true,
  },
  {
    nombre: 'tool_consultar_cve',
    titulo: 'Vulnerabilidades conocidas',
    descripcion:
      'Consultando bases públicas de vulnerabilidades conocidas relacionadas con los servicios detectados...',
    opcional: true,
  },
  {
    nombre: 'agente_ingeniero_mitigacion',
    titulo: 'Diseño de la mitigación',
    descripcion:
      'Diseñando los comandos recomendados para contener la amenaza...',
  },
  {
    nombre: 'tool_validar_comandos',
    titulo: 'Validación de comandos',
    descripcion:
      'Verificando que los comandos propuestos sean seguros antes de mostrarlos...',
  },
  {
    nombre: 'agente_auditor_final',
    titulo: 'Auditoría final',
    descripcion:
      'Revisando todo el análisis para emitir el veredicto final...',
  },
]

export type EstadoNodo = 'pendiente' | 'activo' | 'completado'

export type AvanceNodo = {
  estado: EstadoNodo
  /** Cuántas veces emitió evento este nodo. */
  visitas: number
}

export type Avance = Record<string, AvanceNodo>

export function avanceInicial(): Avance {
  return Object.fromEntries(
    NODOS.map((n) => [n.nombre, { estado: 'pendiente' as EstadoNodo, visitas: 0 }]),
  )
}

/**
 * Aplica un evento `nodo` al avance.
 *
 * El nodo que emitió pasa a `activo` y suma una visita; cualquier OTRO nodo
 * que estuviera activo pasa a `completado`. Un nodo ya completado que vuelve
 * a emitir vuelve a `activo` **sin** resetear a los demás: los pasos
 * intermedios que ya corrieron conservan su estado.
 */
export function aplicarNodo(avance: Avance, nombre: string): Avance {
  const siguiente: Avance = { ...avance }
  for (const clave of Object.keys(siguiente)) {
    if (clave !== nombre && siguiente[clave].estado === 'activo') {
      siguiente[clave] = { ...siguiente[clave], estado: 'completado' }
    }
  }
  const previo = siguiente[nombre] ?? { estado: 'pendiente' as EstadoNodo, visitas: 0 }
  siguiente[nombre] = { estado: 'activo', visitas: previo.visitas + 1 }
  return siguiente
}

/** Al terminar el análisis, todo lo que se ejecutó queda completado. */
export function completarTodo(avance: Avance): Avance {
  return Object.fromEntries(
    Object.entries(avance).map(([clave, valor]) => [
      clave,
      valor.visitas > 0 ? { ...valor, estado: 'completado' as EstadoNodo } : valor,
    ]),
  )
}

/**
 * Progreso en porcentaje.
 *
 * Se calcula sobre los nodos que YA se ejecutaron, no sobre un índice: con
 * pasos que se saltan y otros que se repiten, un porcentaje lineal mentiría.
 * Los dos nodos opcionales no cuentan en el denominador hasta que aparecen,
 * porque una corrida que no los usa igual está completa.
 */
export function progreso(avance: Avance): number {
  const obligatorios = NODOS.filter((n) => !n.opcional)
  const opcionalesVistos = NODOS.filter((n) => n.opcional && avance[n.nombre]?.visitas > 0)
  const total = obligatorios.length + opcionalesVistos.length
  const hechos = [...obligatorios, ...opcionalesVistos].filter(
    (n) => avance[n.nombre]?.estado === 'completado',
  ).length
  const enCurso = [...obligatorios, ...opcionalesVistos].some(
    (n) => avance[n.nombre]?.estado === 'activo',
  )
  return Math.min(100, Math.round(((hechos + (enCurso ? 0.35 : 0)) / total) * 100))
}

export function nodosEjecutados(avance: Avance): number {
  return Object.values(avance).filter((v) => v.visitas > 0).length
}
