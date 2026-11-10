# NODEX ? Entrega R2 y R3 del 3 de noviembre de 2026

R2 se ejecut? y valid? antes de preparar e iniciar R3. Las 24 ejecuciones adicionales terminaron con estado `completa`. No se repitieron casos ni se calcularon m?tricas de calidad.

| Elemento | R2 | R3 |
|---|---|---|
| Identificador | oficial-12casos-r2-20261103 | oficial-12casos-r3-20261103 |
| RAG limpio y verificado | S?: 697 t?cnicas; memorias vac?as | S?: 697 t?cnicas; memorias vac?as |
| Casos procesados | 12 | 12 |
| Casos completados | 12 | 12 |
| Casos fallidos | 0 | 0 |
| Archivos exportados | 359 | 360 |
| Originales copiados | 304 | 305 |
| Validaci?n de integridad | Aprobada; sin archivos requeridos faltantes | Aprobada; sin archivos requeridos faltantes |
| Ruta de extracci?n | [R2](oficial-12casos-r2-20261103/README.md) | [R3](oficial-12casos-r3-20261103/README.md) |
| ZIP generado | [ZIP R2](oficial-12casos-r2-20261103.zip) | [ZIP R3](oficial-12casos-r3-20261103.zip) |

Se comprobaron 4618 proyecciones en R2 y 4624 en R3, 12 reportes literales por repetici?n y las 10 celdas de cada notebook individual. Estos conteos son controles de extracci?n, no evaluaciones de calidad. Cada ZIP tiene una huella SHA-256 contigua; las huellas coinciden con los archivos entregados.

R1 permanece intacta: la comprobaci?n final coincide con los hashes iniciales de sus 608 archivos y fuentes registrados, incluido el ZIP original. No se ejecut? ni regener? R1.

Las tres repeticiones pueden cargarse conjuntamente bajo la configuraci?n experimental y conocimiento inicial verificados: coinciden entradas, orden, referencias reservadas, c?digo de inferencia, par?metros, Python, plataforma, dependencias, modelo efectivo gemini-3.8-flash y semilla MITRE. No se detectaron diferencias funcionales o de conocimiento inicial. Cada caso tuvo una copia temporal limpia del mismo RAG; las copias se descartaron al finalizar y la semilla qued? intacta.

R3 contiene un archivo de fuente adicional en su instant?nea de herramientas: el verificador conjunto se a?adi? despu?s de preparar R2 y no participa de la inferencia. Esto explica la diferencia de un original y un archivo total entre los paquetes. El tiempo de pared del envoltorio incluye las comprobaciones adicionales de aislamiento; las medidas originales de ejecuci?n y llamadas se conservan separadas.

El [notebook conjunto](revision_conjunta_r1_r2_r3_20261103.ipynb) carg? correctamente las 36 identidades distintas mediante case_id, repeticion y run_id y ejecut? sus 5 celdas de c?digo. Para Colab, subir ese notebook y los tres ZIP al panel Archivos; la celda de carga puede descomprimirlos en carpetas independientes. Los notebooks no llaman a NODEX ni calculan m?tricas.

La evidencia est? en [validacion_conjunta_r1_r2_r3_20261103.json](validacion_conjunta_r1_r2_r3_20261103.json), los manifiestos de cada paquete, repetition_integrity.json, rag_initial.json y los archivos isolation.json copiados en sus originales.
