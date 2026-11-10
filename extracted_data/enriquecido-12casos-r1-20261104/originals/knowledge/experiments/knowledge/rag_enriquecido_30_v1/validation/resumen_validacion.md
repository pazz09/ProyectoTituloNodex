# Validaci?n de rag_enriquecido_30_v1

Estado: corpus independiente y snapshot funcional congelado, con limitaciones de representaci?n y desempate documentadas. No se ejecutaron agentes LLM, la campa?a de evaluaci?n ni m?tricas D1?D4.

| Elemento | Resultado real |
|---|---|
| Casos BGL | 15: 8 normales, 7 an?malos |
| Casos UWF | 15: 7 normales, 8 an?malos |
| Casos hist?ricos totales | 30 ?nicos |
| Casos compartidos con evaluaci?n | 0 |
| Registros superpuestos con evaluaci?n | 0 |
| Base MITRE preservada | S?: 697 documentos y embeddings |
| Poblado ChromaDB | Exitoso e idempotente |
| Recuperaci?n funcional | Verificada mediante herramienta real, con l?mites indicados abajo |
| Snapshot generado | S?; restauraci?n de bytes y contenido l?gico verificada |
| Compatibilidad con NODEX | Contrato de memoria/herramienta/JSON verificado; no se ejecut? el LLM |

## Colecciones y embeddings

| Colecci?n | Documentos antes | Documentos despu?s | Embeddings despu?s |
|---|---:|---:|---:|
| `attack_patterns` | 0 | 30 | 30 |
| `attack_techniques` | 697 | 697 | 697 |
| `error_memory` | 0 | 0 | 0 |
| `host_history` | 0 | 0 | 0 |
| Total | 697 | 727 | 727 |

Los 727 embeddings tienen dimensi?n 384. Los 30 documentos hist?ricos contienen firmas de producci?n; las descripciones, observaciones originales y referencias de procedencia se conservan en metadatos. Hay 15 firmas ?nicas; esto no implica duplicaci?n de casos: todos los fragmentos y registros tienen identidades y hashes distintos.

Modelo `all-MiniLM-L6-v2`, revisi?n `1110a243fdf4706b3f48f1d95db1a4f5529b4d41`. Se verificaron los archivos registrados para R1 y el cache completo actual. ChromaDB 1.5.9, sentence-transformers 6.0.1, torch 2.14.0, transformers 5.16.1. Las versiones de embeddings coinciden con R1. M?xima diferencia absoluta entre vectores recalculados y almacenados: `1.4901161193847656e-08`. MITRE se copi? sin recalcular sus embeddings y conserv? su hash l?gico, metadatos y configuraci?n.

## Independencia y fuentes

Se verificaron 2435 registros distintos, 2135 UIDs UWF, las 12 entradas oficiales de R1?R3 y toda la partici?n de evaluaci?n (142 casos). Coincidencias de hashes de fragmentos, registros fuente, UIDs, eventos originales, episodios y ventanas temporales: cero. Se comprueban tambi?n los timestamps originales de los incidentes UWF rebasados en evaluaci?n, no solo su ventana compuesta.

Los CSV UWF regenerados reproducen exactamente los hashes originales de conversi?n de los 13 Parquet. BGL reproduce su original etiquetado y su partici?n de 30 grupos de desarrollo. UWF reproduce los 349 episodios y los 103 de desarrollo. Las etiquetas se contrastaron con las fuentes, sin deducirlas de nombres de archivo ni de un LLM. Los manifiestos de datasets coinciden con sus hashes congelados en las configuraciones R1, R2 y R3.

Para evitar separar artificialmente episodios pr?ximos de UWF, se excluyeron todas las semanas fuente de incidentes oficiales. Los 8 an?malos elegidos son episodios completos de desarrollo de 3?6 conexiones, en dos semanas diferentes de las oficiales. No hay candidatos visibles de al menos 20 conexiones que cumplan esa exclusi?n adicional; no se inventaron ni extendieron incidentes. Solo se conservan las t?cnicas originales T1589, T1590, T1592, a nivel de t?cnica; no se atribuyen subt?cnicas. UWF no tiene identificadores anotados de campa?a: la independencia entre campa?as reales no puede certificarse.

## Recuperaci?n mediante NODEX

Se ejecutaron 60 consultas a `tool_consultar_rag`, contrastadas con `LongTermMemory.retrieve_examples`: 30 firmas originales y 30 variantes obtenidas reservando un registro real. Todas devolvieron documentos hist?ricos y JSON serializable, con IDs originales en metadatos y procedencia resoluble. Todos los documentos se recuperan adem?s por su ID vectorial. Las consultas cubren los cuatro estratos BGL/UWF ? normal/an?malo.

Se conservaron top-k 3, umbral de patrones 0.55 y umbral ATT&CK 0.42. Hubo 26 consultas cuya firma no estaba almacenada; 25 de ellas recuperaron al menos un caso del mismo dataset y clase. En 59/60 consultas hubo un resultado del mismo dataset y clase; la excepci?n fue la variante de `uwf_hist_008`. El propio caso apareci? en el top 3 de 21/30 consultas originales. Estos son controles de recuperaci?n, no m?tricas de clasificaci?n ni resultados de una campa?a LLM.

**Limitaci?n BGL:** los 15 casos tienen cobertura declarada cero con el preprocesamiento actual. Once casos comparten una firma gen?rica entre clases. Las observaciones de mensajes originales se conservan en metadatos, pero la firma no permite garantizar separaci?n de clases ni correspondencia sem?ntica espec?fica. Corregir el decoder o cambiar las firmas funcionales alterar?a el sistema de referencia; no se hizo.

**Empates al restaurar:** 39/60 consultas cambiaron IDs recuperados entre el proceso de poblado y el de restauraci?n. Los 39 cambios correspondieron exclusivamente a documentos con firma y similitud id?nticas. El contenido l?gico y los vectores permanecieron iguales. El RAG existente no garantiza desempate estable; no se modific?. V?ase `comparacion_recuperacion_restaurada.json` para cada diferencia.

Las t?cnicas recuperadas desde la colecci?n est?tica por afinidad sem?ntica no se utilizan como atribuciones de referencia de los casos hist?ricos. Los normales tienen referencias MITRE vac?as.

## Congelamiento, idempotencia y preservaci?n

La incorporaci?n se ejecut? dos veces sobre la misma colecci?n: se mantuvieron exactamente IDs, textos, metadatos y hashes de vectores, sin documentos nuevos en la segunda ejecuci?n. Tambi?n se repiti? el comando completo `poblar` sobre el snapshot congelado: verific? sus hashes y termin? con cero documentos nuevos.

Se cerr? el proceso Chroma antes de copiar el snapshot, se restaur? en otra carpeta y proceso, y se repitieron las consultas con las herramientas reales. El comando p?blico `restaurar` produjo adem?s una copia id?ntica de todos los archivos. Tama?o del snapshot: 7,790,920 bytes. SHA-256 del inventario can?nico:

`f8f1ce20d47021aef6e4fa0f621e7a2aff1337c46f7e6e225f6e1ec072b9a63c`

El corpus y sus manifiestos se reconstruyeron independientemente y resultaron id?nticos byte a byte. Las fuentes protegidas, la semilla R1?R3, producci?n, resultados oficiales, prompts, agentes, routers, configuraci?n y c?digo original conservaron sus hashes. La base de producci?n no se abri? con Chroma. Los ?nicos cambios de c?digo son scripts y pruebas de preparaci?n/validaci?n; se a?adieron exclusiones de temporales a `.gitignore`.

Pruebas: suite de preparaci?n/aislamiento, 131 aprobadas; regresi?n final del nuevo m?dulo, 20 aprobadas. No se ejecutaron m?tricas D1?D4 ni agentes LLM.

Para restaurar y preparar las futuras repeticiones, seguir `../README.md`. El lanzador de campa?as actual conserva su origen est?tico; todav?a no selecciona autom?ticamente este snapshot.
