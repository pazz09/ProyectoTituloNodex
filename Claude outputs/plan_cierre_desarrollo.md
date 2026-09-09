# Plan de cierre de desarrollo — NODEX (Proyecto de Título)

**Para**: Claude Code local de Antonia, repo `Desktop\NODEX`.
**Objetivo de este plan**: dejar el desarrollo cerrado y documentado antes del Informe de Avance — no abrir trabajo nuevo de alcance salvo que se indique explícitamente. Cada tarea tiene un criterio de aceptación: no se marca hecha hasta que se cumple con evidencia real, no supuesta.

**Reglas de trabajo para esta ronda** (ya establecidas y confirmadas con Antonia a lo largo del proyecto — mantenerlas):
- Verificar con tests deterministas / datos reales antes de aplicar un cambio, no solo antes de reportarlo.
- Si aparece una brecha entre lo que dice el informe/README y lo que el código realmente hace, reportarla con evidencia concreta y preguntar antes de decidir el fix — no corregirla en silencio ni asumir la opción por defecto.
- No gastar cuota de LLM real salvo que la tarea lo pida explícitamente (las tareas que sí lo piden están marcadas con 💰).
- Al terminar cada bloque, reportar de vuelta con números/resultados exactos (conteos de tests, rutas de archivos JSON generados, mensajes de error textuales si algo falla) — no con resúmenes cualitativos tipo "quedó bien".

---

## Bloque 0 — Verificación inmediata (bloquea todo lo demás)

### 0.1 Resultado de la evaluación multiagente con motor v2 💰
Si ya se lanzó y terminó: recuperar el/los JSON de `results/` y reportar precisión/recall/F1 exactos (BGL y ambos escenarios de HDFS — balanceado y prevalencia real 3.1%), con los mismos parámetros usados en las corridas de comparación anteriores (BGL n=16, HDFS n=20) para que sean comparables con el baseline de reglas ya medido.
Si no se ha lanzado: lanzarla ahora con el motor v2 activado por variable de entorno, mismos parámetros.
**Criterio de aceptación**: JSON en `results/` con `campo_veredicto`, métricas y motor usado (`v1`/`v2`) explícitos en el resultado — igual que las corridas anteriores.

### 0.2 Confirmar la Fase 0 del plan de preprocesamiento heterogéneo (pytest real)
Correr `python -m pytest -q` completo contra el repo real, en el entorno con las dependencias instaladas (no hace falta `GEMINI_API_KEY` real para los tests que no llaman a la API).
**Criterio de aceptación**: conteo exacto pass/fail reportado, y si hay algo roto, el traceback completo — no arreglarlo en silencio, reportarlo primero. Agregar el resultado a `docs/preprocessing_baseline.md`, reemplazando la nota de "la suite no se pudo ejecutar durante este levantamiento".

---

## Bloque 1 — Sincronizar documentación con el estado real del código

### 1.1 Actualizar `README.md`
Está desactualizado en al menos estos puntos (confirmado en la sesión del 4-sep):
- Dice "falta correr `preparar_mitre_attack.py` con red real" — ya se hizo (697 técnicas, ATT&CK v19.2, `data/mitre_attack/provenance.json` real).
- No documenta el bug/fix de `SIMILARITY_FLOOR_ATTACK` (ronda 2, umbral 0.35 para la colección `attack_techniques`).
- No refleja el preprocesamiento heterogéneo v2 (14 fases, `src/preprocessing/`, activable por variable de entorno, v1 sigue siendo el default).
- Conteo de tests desactualizado (debería decir 317, no 85).
**Criterio de aceptación**: README relee correctamente contra `git log`/estructura real del repo — cualquier afirmación de "pendiente" que ya esté resuelta se corrige o se elimina.

### 1.2 Actualizar la cita "MITRE ATT&CK v15" a v19.2
Dondequiera que aparezca en el repo (README, docstrings, comentarios) — no en el informe LaTeX, eso lo maneja Antonia aparte.

---

## Bloque 2 — Confirmaciones funcionales pendientes

### 2.1 Reconfirmar la interfaz web end-to-end contra la API real 💰
Sigue sin confirmarse desde el fix del 1-sep-2026 (bug de "análisis instantáneo" tras error). Subir un lote real (`data/logs/HDFS_2k.log` o `BGL_2k.log`), confirmar que el streaming SSE muestra los 7 nodos en vivo y que el reporte final llega completo. Probar también con `v1` (default) — no hace falta forzar `v2` acá salvo que sea rápido.
**Criterio de aceptación**: confirmación explícita de que el flujo básico funciona de punta a punta, o un reporte de bug con evidencia concreta si no.

### 2.2 (Opcional, no bloqueante) Ciclo de corrección de comandos con LLM real
Si en alguna corrida real del punto 2.1 se dispara naturalmente, tomar nota del resultado. No vale la pena gastar cuota solo para forzarlo — ya está verificado estructuralmente con mocks.

---

## Bloque 3 — Higiene de repo antes del Informe de Avance

### 3.1 Confirmar `.gitignore` y qué se versiona
Doble-chequear que `data/labels/*.csv` sigue versionado (ground truth de HDFS) y que no se coló nada sensible en el commit de 59 archivos del 9-sep (`.env`, credenciales, caché de reputación de IPs).

### 3.2 Confirmar que `data/mitre_attack/provenance.json` está commiteado
Para que quede trazabilidad de versión/fecha de los datos de MITRE frente al jurado.

---

## Fuera de alcance de esta ronda — siguiente fase, NO ejecutar sin confirmar con Antonia primero

Estas son las 3 brechas que quedan de las 6 originales contra el §8.7 del informe. Son la fase de **pruebas formales**, no cierre de desarrollo — necesitan decisión explícita de alcance (con Antonia y/o su profesora guía) antes de invertir tiempo:

- **Escenario B / UWF-ZeekDataFall22**: único dataset con ground truth de seguridad real (no solo anomalías operativas como HDFS/BGL). Antes de implementar, revisar si el enricher Zeek que ya existe en `src/preprocessing/enrichers/` (parte de las 14 fases) ya cubre parte de esto — puede que el trabajo de adaptación sea menor de lo que parece.
- **Evaluación cualitativa por rúbrica de expertos** (§8.6.3 del informe) — falta diseñar el instrumento y aplicarlo, aunque sea con evaluadores informales (Antonia/Felipe).
- **LogHub** — evaluar si entra en el alcance del Proyecto de Título o queda como trabajo futuro declarado; no iniciar sin esa decisión.

---

## Al terminar

Reportar de vuelta, para actualizar el documento de contexto del proyecto:
1. Números exactos de la evaluación v2 (Bloque 0.1).
2. Resultado exacto de pytest (Bloque 0.2) — pass/fail, cualquier falla.
3. Confirmación de que README y citas quedaron sincronizados (Bloque 1).
4. Resultado de la prueba end-to-end de la interfaz (Bloque 2.1).
5. Cualquier bug real encontrado en el camino, con evidencia — no corregido en silencio si involucra una decisión de alcance o diseño.
