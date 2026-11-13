# Preregistro de la evaluación final de NODEX

> Se versiona en git (`docs/experimentacion/preregistro_evaluacion_final.md`) con un commit **anterior** a la ejecución del primer caso de evaluación. El commit fecha el documento. Los campos [PENDIENTE] se completan al congelar.

## 1. Sistema evaluado
- **Versión:** NODEX final, rama `nodex-final`, tag `nodex-final-evaluada`, commit `e7db484` (código del sistema). El tag `nodex-final-evaluada` se crea sobre el commit que agrega este preregistro y el conjunto final (`experiments/cases_final/`); ese commit no modifica `src/` respecto de `e7db484`.
- **Arquitectura:**
  - **Nodos:** preprocesamiento determinístico (perfil del lote, grupos de evidencia, contenido del lote) → planificador → triage → RAG MITRE por hipótesis → selector de herramientas → mitigación ⇄ validación → auditor reforzado → router de coherencia (corrección y re-ejecución de mitigación y auditoría, máximo 1) → router de finalización (replanificación, máximo 1).
  - **Agentes LLM:** 5.
  - **Memoria:** contrastiva por lote (2 normales y 2 anómalos o maliciosos) y por grupo de eventos.
- **Selección de la configuración (desarrollo, 48 casos, 1 repetición):**
  - **Regla fijada antes de ver los resultados:** mayor F1 promedio BGL/UWF de NODEX; si hay empate, la configuración más simple.
  - **Resultado:**

    | Configuración | F1 promedio |
    |---|---|
    | A.1 | 0,641 |
    | Configuración elegida | 0,639 |
    | Otras configuraciones | 0,625 |

  - **Desviación documentada (12-11-2026):** se eligió la configuración con auditor reforzado en lugar de A.1, por tres motivos:
    1. Con una repetición, la diferencia (0,002) es menor que la variación propia del modelo: con entradas idénticas, el triage cambió de veredicto en 2 de 48 casos.
    2. A.1 conserva un defecto funcional confirmado: la corrección del auditor no se propaga a la mitigación.
    3. La configuración elegida tiene mayor F1 en BGL (0,778 frente a 0,615).

    Registrado en `bitacora_desarrollo_nodex_final.md`.
- **Configuración de evaluación:**
  - modelo gemini-3.8-flash, temperatura 0, sin modelo de respaldo;
  - sin reputación externa de IP;
  - red bloqueada salvo la API del modelo;
  - memoria `rag_enriquecido_v2` (solo partición de desarrollo), con exclusión por solapamiento de registros.

## 2. Sistemas de comparación
**2.1 Gemini 3.8 Flash directo (comparación con el modelo base).**
- Mismo modelo que NODEX (gemini-3.8-flash), temperatura 0, una sola llamada.
- Recibe el archivo de log crudo y completo, con el prompt estructurado v2.1, el mismo usado en la comparación con asistentes de propósito general (hash registrado).
- No usa preprocesamiento, memoria, RAG, herramientas ni arquitectura.
- Responde: ¿aporta el sistema NODEX respecto de usar el modelo directamente?

**2.2 Agente único (estudio de ablación de arquitectura).**
- Mismo modelo y mismo contexto de entrada que NODEX: contenido del lote, perfil, grupos con señal con filas, motivo factual y lista de patrones MITRE, memoria contrastiva por lote y por grupo, candidatos MITRE, criterio de la organización y reglas de mitigación por veredicto.
- Recibe la misma instrucción de evaluar cada grupo con señal, en una sola llamada.
- La única diferencia con NODEX es la arquitectura: planificación, separación entre diagnóstico y auditoría independiente, ciclo de corrección y replanificación.
- Responde: ¿aporta la arquitectura multiagente por sí misma?

## 3. Conjunto de evaluación
- **Fuente:** partición de evaluación (`*_eva_*`, semilla de partición 20261003). Ningún caso se usó durante el desarrollo. Se excluyen los 12 casos de la evaluación piloto.
- **Composición: 60 casos.**
  - BGL: 15 con alerta y 15 sin alerta.
  - UWF: 15 maliciosos (aprox. 7 visibles y 8 sigilosos) y 15 benignos.
- **Reglas de diversidad:**
  1. Los UWF maliciosos cubren todas las tácticas disponibles, con a lo más 2 casos por táctica, salvo Reconnaissance.
  2. Un caso por incidente y, en lo posible, IP atacantes distintas.
  3. Los BGL con alerta se estratifican por categoría de alerta, con tope por categoría.
  4. Los normales y benignos provienen de ventanas distintas.
- **Selección:** semilla **20261113**, mediante un script que usa solo metadatos (índice, condición, táctica y categoría de alerta), sin abrir el contenido de los logs.
- **Generación:** se regeneran con el generador corregido (formato de hora idéntico al fondo) y se verifica que la única diferencia con el original sea ese formato.
- **Tabla de composición:** anexo A, registrada antes de ejecutar.

## 4. Procedimiento
- **Repeticiones:** 3 por sistema y caso, 540 ejecuciones en total (60 casos × 3 repeticiones × 3 sistemas). Orden: R1 completa (NODEX, agente único y Gemini directo, 60 casos cada uno), luego R2 y luego R3, para que cada repetición quede completa aunque haya interrupciones.
- **Un proceso nuevo por caso,** con copia desechable de la memoria.
- **Referencia:** el ground truth no se lee durante la inferencia.
- **Fallas:**
  - *Del sistema* (excepción, salida inválida, tope de tiempo): se registran como fallas y **no se repiten**.
  - *De infraestructura ajenas al sistema* (corte de energía, suspensión del equipo, crédito agotado, caída de red): la corrida se aparta sin borrarla, se repite desde cero y se registra en la bitácora.
- **Registro por ejecución:** commit, configuración, interruptores, hashes de prompts, tokens, tiempo y costo. En Gemini directo, además, la respuesta cruda completa, el JSON extraído y su normalización; un JSON inválido es falla del sistema y no se repite.
- **Adicional, no confirmatorio:** NODEX final sobre los 12 casos del piloto (1 repetición), para mostrar la evolución piloto → final. Esos casos se usaron en el diagnóstico.

## 5. Hipótesis confirmatorias
Cada hipótesis se evalúa por separado frente a Gemini directo (a) y frente al agente único (b).
- **H1. Detección.** El F1 de NODEX es mayor o igual que el del sistema de comparación.
  - Prueba: McNemar pareado sobre el veredicto mayoritario de las 3 repeticiones (α = 0,05), más IC 95 % bootstrap por caso de la diferencia de F1.
  - Como hay dos comparaciones, se informa también el resultado con corrección de Holm.
- **H2. Reconstrucción.** En los UWF maliciosos detectados por ambos sistemas, la cobertura de evidencia del incidente de NODEX es mayor o igual (Wilcoxon pareado por caso).
  - En NODEX y en el agente único se usan los eventos de categoría `incidente`; en Gemini directo, la unión de los `evidence_uids` de sus eventos reconstruidos (su contrato solo admite eventos de incidente).
- **H3. Atribución MITRE.** La proporción de atribuciones incorrectas de NODEX es menor o igual.
- **H4. Reporte (D4).** El puntaje medio de NODEX en la rúbrica es mayor.
  - Wilcoxon pareado sobre 15 casos estratificados (semilla 20261114, reportes R1), evaluación ciega de dos evaluadores.
  - Cantidad: 15 × 3 sistemas = 45 reportes. Si el tiempo de los evaluadores no alcanza, se evalúan solo NODEX y Gemini directo (30 reportes), y se declara.

## 6. Métricas
- **D1 Detección.**
  - Criterio: en BGL, `hay_anomalia`; en UWF, `hay_incidente`.
  - Métricas: precisión, recall, F1, especificidad y exactitud por dataset y en total.
  - Veredicto por caso: el mayoritario de las 3 repeticiones.
  - Estabilidad: kappa de Fleiss.
- **D2 Reconstrucción.** Cobertura y precisión de uids sobre los eventos de categoría `incidente`, en UWF maliciosos; agregadas y por caso.
- **D3 MITRE.** Técnicas correctas, omitidas e incorrectas, a nivel de técnica.
- **D4 Reporte.** Rúbrica de 5 criterios (0 a 3) y afirmaciones no sustentadas. Acuerdo entre evaluadores: exacto, ±1 y kappa ponderado.
- **D5 Rendimiento.** Llamadas, tokens (entrada, salida y razonamiento), tiempo de flujo y de pared, y costo según la tarifa vigente.
- **Además:** número de correcciones del auditor y su acierto.

## 7. Análisis exploratorios (se informan como tales)
- **Por táctica UWF y categoría BGL:** descriptivo, caso a caso.
- **Atacante presente o no en la memoria.**
- **Visibles frente a sigilosos.**
- **Piloto → final** en los 12 casos del piloto.

## 8. Reglas de reporte
1. Se informan todos los resultados de las hipótesis, favorables o no.
2. No se cambian las métricas, el conjunto ni la configuración después de ejecutar.
3. Toda desviación se registra con fecha y motivo.
4. Los resultados de desarrollo se presentan como proceso de desarrollo, nunca como evaluación.

## 9. Riesgos declarados de antemano
- **Etiquetas de BGL:** ventanas muy similares tienen etiquetas distintas.
- **Construcción artificial de UWF:** fondo de 2021 con incidentes de 2022 insertados. Algunas señales pueden deberse en parte a la construcción.
- **Pocas IP atacantes en UWF (10):** posible solapamiento de atacante con la memoria.
- **Un solo modelo y dos tipos de log.**
- **Evaluación D4 parcialmente ciega,** con evaluadores que son los desarrolladores del sistema.

## Anexo A. Composición del conjunto final (13-nov-2026, antes de ejecutar)

Generado con `python tools/seleccionar_conjunto_final.py seleccionar | regenerar | composicion | preflight`
(semilla 20261113). Archivos: `experiments/cases_final/seleccion.json` (metadatos y decisiones de cada regla),
`composicion.csv`, `verificacion_regeneracion.json` (comparación caso por caso y sha256 de cada archivo) y
`preflight.json`.

**Candidatos tras excluir los 12 del piloto:** BGL 17 con alerta y 39 sin alerta; UWF 37 maliciosos y 37 benignos.

**Cumplimiento de las reglas:**
1. *Tácticas UWF:* las 6 tácticas disponibles quedan cubiertas (Defense Evasion 1, Discovery 2, Execution 1,
   Initial Access 1, Resource Development 2, Reconnaissance 9). Las etiquetas compuestas del dataset
   (Discovery|Reconnaissance) cuentan para cada táctica que nombran. 7 visibles y 8 sigilosos.
2. *Un caso por incidente:* sí. *IP atacantes distintas:* no es posible con 15 casos; se usan las 7 IP
   disponibles y se minimiza la repetición (143.88.10.11: 5 casos; 143.88.7.11: 3; 143.88.18.12 y
   143.88.5.11: 2; 143.88.3.12, 143.88.6.11 y 143.88.9.12: 1). Los sigilosos de Reconnaissance disponibles
   provienen todos de 143.88.10.11. La IP atacante está en la memoria en 12 de los 15 casos; ningún
   incidente de evaluación está en la memoria.
3. *Categorías BGL:* 9 categorías, tope 3 por categoría (el menor que permite llegar a 15; el exceso se
   recortó al azar de las categorías más grandes): KERNDTLB 3, APPSEV 2, KERNMNTF 2, KERNREC 2, KERNSTOR 2,
   APPCHILD 1, APPOUT 1, APPREAD 1, KERNTERM 1.
4. *Ventanas distintas:* cada caso BGL es una ventana disjunta de 20 líneas (ningún grupo se repite). En UWF,
   el fondo de cada caso es un tramo contiguo propio (ningún registro se repite entre casos); la columna
   "Ventana" indica la semana del fondo, que comparten varios casos sin compartir registros.

**Regeneración:** los 60 casos se regeneraron con el generador corregido. En los 60, metadatos y referencias
son idénticos byte a byte al original; en BGL el log es idéntico; en UWF cambian solo `ts`/`datetime`, solo en
las filas insertadas (451 filas en los 15 maliciosos; ninguna en los benignos), con el mismo instante.

**Preflight sin modelo** (configuración congelada, memoria `rag_enriquecido_v2`, red bloqueada, modelo
simulado): cobertura de parsing 100 % en los 60 casos (sin eventos de respaldo; una advertencia informativa
de cabecera CSV por caso UWF); ningún prompt contiene columnas de etiqueta, campos del ground truth, códigos de
alerta BGL ni identificadores de incidente; tamaño del prompt del auditor: BGL mediana 19 720 caracteres
(12 467–29 212), UWF mediana 149 482 (140 519–171 024); los 60 casos reciben 4 casos históricos (2 normales y
2 anómalos o maliciosos), ninguno excluido por solapamiento; los 30 UWF reciben memoria de grupos para todos sus
grupos con señal; ningún intento de conexión externa. Con el agente único como estudio de ablación (mismo bloque
de grupos con señal que el auditor), su prompt tiene una mediana de 23 907 caracteres en BGL (16 025–35 789) y
167 827 en UWF (152 377–207 200), también sin marcas de etiqueta.

**Preflight de Gemini directo** (`preflight_gemini_directo.json`, sin modelo): prompt v2.1 de 3 612 caracteres
(SHA-256 `2dd880789645f682d411094f2bfa224168bf416c68fa8f66c348e16e93dde660`); en los 60 casos la solicitud lleva
el archivo completo a continuación del prompt (BGL: mediana 6 347 caracteres, 6 143–8 043; UWF: mediana 59 190,
57 813–59 702); ningún archivo tiene columnas de etiqueta (UWF: las 22 columnas Zeek, con 300 `uid` citables;
BGL: 20 líneas, `log_record_000001` a `log_record_000020`, sin líneas vacías intermedias).

**Piloto no confirmatorio:** NODEX final corre sobre los mismos 12 archivos que usó el piloto
(`experiments/cases/`, verificados por SHA-256 contra su `selection.json`), para que la comparación piloto → final
tenga la misma entrada.

| Caso | Dataset | Condición | Clase | Táctica o categoría | Filas del incidente | IP atacante | IP en memoria | Incidente en memoria | Ventana |
|---|---|---|---|---|---:|---|---|---|---|
| bgl_eva_balanceado_0000 | bgl | balanceado | positivo | APPOUT | 3 | - | - | - | bgl_l01961-01980 |
| bgl_eva_balanceado_0002 | bgl | balanceado | positivo | KERNMNTF | 7 | - | - | - | bgl_l01381-01400 |
| bgl_eva_balanceado_0003 | bgl | balanceado | positivo | KERNTERM | 1 | - | - | - | bgl_l01021-01040 |
| bgl_eva_balanceado_0004 | bgl | balanceado | positivo | KERNSTOR | 9 | - | - | - | bgl_l00201-00220 |
| bgl_eva_balanceado_0009 | bgl | balanceado | negativo | - | 0 | - | - | - | bgl_l00941-00960 |
| bgl_eva_balanceado_0011 | bgl | balanceado | negativo | - | 0 | - | - | - | bgl_l00981-01000 |
| bgl_eva_natural_0000 | bgl | natural | positivo | KERNDTLB | 11 | - | - | - | bgl_l00161-00180 |
| bgl_eva_natural_0003 | bgl | natural | positivo | APPSEV | 3 | - | - | - | bgl_l01241-01260 |
| bgl_eva_natural_0004 | bgl | natural | positivo | KERNREC | 1 | - | - | - | bgl_l01521-01540 |
| bgl_eva_natural_0005 | bgl | natural | positivo | KERNMNTF | 2 | - | - | - | bgl_l01361-01380 |
| bgl_eva_natural_0007 | bgl | natural | positivo | KERNREC | 1 | - | - | - | bgl_l01701-01720 |
| bgl_eva_natural_0008 | bgl | natural | positivo | KERNDTLB | 20 | - | - | - | bgl_l00121-00140 |
| bgl_eva_natural_0009 | bgl | natural | positivo | APPREAD | 1 | - | - | - | bgl_l00341-00360 |
| bgl_eva_natural_0010 | bgl | natural | positivo | KERNDTLB | 17 | - | - | - | bgl_l00101-00120 |
| bgl_eva_natural_0011 | bgl | natural | positivo | KERNSTOR | 8 | - | - | - | bgl_l00181-00200 |
| bgl_eva_natural_0012 | bgl | natural | positivo | APPCHILD | 1 | - | - | - | bgl_l00361-00380 |
| bgl_eva_natural_0013 | bgl | natural | positivo | APPSEV | 1 | - | - | - | bgl_l01481-01500 |
| bgl_eva_natural_0014 | bgl | natural | negativo | - | 0 | - | - | - | bgl_l01121-01140 |
| bgl_eva_natural_0015 | bgl | natural | negativo | - | 0 | - | - | - | bgl_l01141-01160 |
| bgl_eva_natural_0021 | bgl | natural | negativo | - | 0 | - | - | - | bgl_l01041-01060 |
| bgl_eva_natural_0024 | bgl | natural | negativo | - | 0 | - | - | - | bgl_l00681-00700 |
| bgl_eva_natural_0027 | bgl | natural | negativo | - | 0 | - | - | - | bgl_l00081-00100 |
| bgl_eva_natural_0028 | bgl | natural | negativo | - | 0 | - | - | - | bgl_l00041-00060 |
| bgl_eva_natural_0033 | bgl | natural | negativo | - | 0 | - | - | - | bgl_l00481-00500 |
| bgl_eva_natural_0035 | bgl | natural | negativo | - | 0 | - | - | - | bgl_l00421-00440 |
| bgl_eva_natural_0038 | bgl | natural | negativo | - | 0 | - | - | - | bgl_l00641-00660 |
| bgl_eva_natural_0041 | bgl | natural | negativo | - | 0 | - | - | - | bgl_l00921-00940 |
| bgl_eva_natural_0042 | bgl | natural | negativo | - | 0 | - | - | - | bgl_l00381-00400 |
| bgl_eva_natural_0045 | bgl | natural | negativo | - | 0 | - | - | - | bgl_l00521-00540 |
| bgl_eva_natural_0047 | bgl | natural | negativo | - | 0 | - | - | - | bgl_l00801-00820 |
| uwf_eva_sigiloso_0001 | uwf | sigiloso | positivo | Discovery\|Reconnaissance | 4 | 143.88.6.11 | no | no | fondo 2021-12-19_2021-12-26 |
| uwf_eva_sigiloso_0002 | uwf | sigiloso | positivo | Execution | 3 | 143.88.10.11 | sí | no | fondo 2021-12-26_2022-01-02 |
| uwf_eva_sigiloso_0004 | uwf | sigiloso | positivo | Initial Access | 4 | 143.88.9.12 | no | no | fondo 2021-12-12_2021-12-19 |
| uwf_eva_sigiloso_0007 | uwf | sigiloso | positivo | Resource Development | 4 | 143.88.5.11 | sí | no | fondo 2022-01-02_2022-01-09 |
| uwf_eva_sigiloso_0010 | uwf | sigiloso | positivo | Reconnaissance | 4 | 143.88.10.11 | sí | no | fondo 2021-12-26_2022-01-02 |
| uwf_eva_sigiloso_0012 | uwf | sigiloso | positivo | Reconnaissance | 5 | 143.88.10.11 | sí | no | fondo 2021-12-12_2021-12-19 |
| uwf_eva_sigiloso_0016 | uwf | sigiloso | positivo | Reconnaissance | 3 | 143.88.10.11 | sí | no | fondo 2021-12-12_2021-12-19 |
| uwf_eva_sigiloso_0017 | uwf | sigiloso | positivo | Reconnaissance | 4 | 143.88.10.11 | sí | no | fondo 2021-12-19_2021-12-26 |
| uwf_eva_sigiloso_0021 | uwf | sigiloso | negativo | - | 0 | - | - | - | fondo 2021-12-19_2021-12-26 |
| uwf_eva_sigiloso_0023 | uwf | sigiloso | negativo | - | 0 | - | - | - | fondo 2022-01-02_2022-01-09 |
| uwf_eva_sigiloso_0027 | uwf | sigiloso | negativo | - | 0 | - | - | - | fondo 2022-01-02_2022-01-09 |
| uwf_eva_sigiloso_0029 | uwf | sigiloso | negativo | - | 0 | - | - | - | fondo 2021-12-19_2021-12-26 |
| uwf_eva_sigiloso_0031 | uwf | sigiloso | negativo | - | 0 | - | - | - | fondo 2022-01-02_2022-01-09 |
| uwf_eva_sigiloso_0034 | uwf | sigiloso | negativo | - | 0 | - | - | - | fondo 2021-12-26_2022-01-02 |
| uwf_eva_sigiloso_0036 | uwf | sigiloso | negativo | - | 0 | - | - | - | fondo 2021-12-12_2021-12-19 |
| uwf_eva_sigiloso_0038 | uwf | sigiloso | negativo | - | 0 | - | - | - | fondo 2021-12-26_2022-01-02 |
| uwf_eva_visible_0000 | uwf | visible | positivo | Defense Evasion | 60 | 143.88.18.12 | sí | no | fondo 2021-12-12_2021-12-19 |
| uwf_eva_visible_0001 | uwf | visible | positivo | Discovery | 60 | 143.88.18.12 | sí | no | fondo 2021-12-19_2021-12-26 |
| uwf_eva_visible_0002 | uwf | visible | positivo | Resource Development | 60 | 143.88.5.11 | sí | no | fondo 2021-12-26_2022-01-02 |
| uwf_eva_visible_0016 | uwf | visible | positivo | Reconnaissance | 60 | 143.88.3.12 | no | no | fondo 2021-12-12_2021-12-19 |
| uwf_eva_visible_0017 | uwf | visible | positivo | Reconnaissance | 60 | 143.88.7.11 | sí | no | fondo 2021-12-19_2021-12-26 |
| uwf_eva_visible_0018 | uwf | visible | positivo | Reconnaissance | 60 | 143.88.7.11 | sí | no | fondo 2021-12-26_2022-01-02 |
| uwf_eva_visible_0019 | uwf | visible | positivo | Reconnaissance | 60 | 143.88.7.11 | sí | no | fondo 2022-01-02_2022-01-09 |
| uwf_eva_visible_0021 | uwf | visible | negativo | - | 0 | - | - | - | fondo 2021-12-19_2021-12-26 |
| uwf_eva_visible_0023 | uwf | visible | negativo | - | 0 | - | - | - | fondo 2022-01-02_2022-01-09 |
| uwf_eva_visible_0026 | uwf | visible | negativo | - | 0 | - | - | - | fondo 2021-12-26_2022-01-02 |
| uwf_eva_visible_0030 | uwf | visible | negativo | - | 0 | - | - | - | fondo 2021-12-26_2022-01-02 |
| uwf_eva_visible_0033 | uwf | visible | negativo | - | 0 | - | - | - | fondo 2021-12-19_2021-12-26 |
| uwf_eva_visible_0036 | uwf | visible | negativo | - | 0 | - | - | - | fondo 2021-12-12_2021-12-19 |
| uwf_eva_visible_0038 | uwf | visible | negativo | - | 0 | - | - | - | fondo 2021-12-26_2022-01-02 |
