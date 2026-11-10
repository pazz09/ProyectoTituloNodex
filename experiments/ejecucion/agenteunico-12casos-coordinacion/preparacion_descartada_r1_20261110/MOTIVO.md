# Preparación R1 descartada (10-nov-2026), sin inferencia

Estos cuatro archivos los generó `tools/run_single_agent_campaign.py --repetition 1` y se conservan
movidos aquí, sin modificar.

El primer `--preflight` se detuvo antes de procesar el primer caso porque el proceso hijo, lanzado
sin credencial, la volvió a cargar desde `.env`: `src/config.py` llama a `load_dotenv()` al importarse.
La salvaguarda del propio preflight lo detectó y abortó. Cero llamadas al modelo: la salvaguarda está
antes del preprocesamiento y el modelo estaba reemplazado por un sustituto.

Corrección: el lanzador pasa `GEMINI_API_KEY` y `GOOGLE_API_KEY` vacías al hijo del preflight
(`load_dotenv` no sobrescribe una variable ya definida) y el hijo comprueba la credencial antes y
después de importar `src.config`. Se agregó la prueba
`test_el_hijo_del_preflight_no_recupera_la_credencial_desde_env`.

Como la configuración y `environment.json` congelan el hash del lanzador, la preparación se rehízo con
el lanzador corregido. Ninguna corrida se había iniciado con esta preparación.
