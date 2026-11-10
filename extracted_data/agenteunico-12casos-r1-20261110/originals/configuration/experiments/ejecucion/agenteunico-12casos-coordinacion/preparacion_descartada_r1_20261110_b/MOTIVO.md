# Preparación R1 y preflight descartados (b), 10-nov-2026, sin inferencia

Se conservan movidos aquí, sin modificar: la segunda preparación de R1 y su preflight
(`preflight_r1_20261110.json`, cero llamadas al modelo, sin credencial en el hijo).

El preflight recuperó bien los candidatos del agente único, pero la columna de NODEX R1 quedó vacía:
`mitre/retrieved_candidates.jsonl` de R1 trae dos filas por caso (`/estado_crudo/tecnicas_mitre`, con
similitud, y `/salida/_meta/mitre_candidates`, sin similitud) y el lector se quedaba con la última.
Se corrigió `candidatos_nodex_r1()` para usar solo el estado crudo y se agregó la prueba
`test_los_candidatos_de_nodex_r1_se_leen_del_estado_crudo_con_similitud`. Como la configuración congela
el hash del lanzador, la preparación y el preflight se rehicieron con el lanzador corregido.
