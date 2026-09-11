/**
 * Catálogo de los 7 nodos reales del grafo: su nombre en el backend, cómo se
 * llaman en pantalla y qué hacen, en lenguaje llano.
 *
 * Acá no hay estado. El avance de una ejecución lo lleva
 * `components/use-analisis.ts` como una lista de mensajes, con el número de
 * visita en cada uno, porque el recorrido NO es lineal:
 *
 *  - `agente_analista_triage` se ejecuta de nuevo después del RAG (confirmado
 *    en corridas reales), así que un paso ya "terminado" vuelve a hablar.
 *  - `tool_consultar_rag` y `tool_consultar_cve` pueden no ejecutarse nunca:
 *    lo decide `agente_selector_herramientas`.
 *  - `agente_ingeniero_mitigacion` y `tool_validar_comandos` pueden repetirse
 *    si el validador rechaza los comandos (ciclo de corrección).
 *
 * Este archivo tenía además una máquina de estados por nodo
 * (`pendiente`/`activo`/`completado` con contador de visitas) para la barra
 * de progreso de la vista anterior. Se eliminó el 11-sep-2026 al reemplazar
 * esa vista por la conversación, donde cada paso es un mensaje y no hay
 * porcentaje que calcular.
 */

export type NombreNodo =
  | 'agente_planificador'
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
    nombre: 'agente_planificador',
    titulo: 'Plan de investigación',
    descripcion:
      'Decidiendo qué hace falta investigar antes de empezar el análisis...',
  },
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
