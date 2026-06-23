# HANDOFF

_Última actualización: 2026-06-23 · sin repo git aún (pendiente `git init`)_

## Estado actual
**Nikodym RiskLib** en **fase de diseño**. El esqueleto de la arquitectura está completo: spec maestra v1.0, roadmap por fases y andamiaje de los 25 documentos de diseño (SDD). Parámetros normativos CMF extraídos y verificados visualmente. **Cero código aún** — y así sigue hasta terminar toda la especificación.

## Hecho en esta sesión
- **Naming** cerrado: marca "Nikodym RiskLib", paquete `nikodym`.
- **Alcance** ampliado a suite integral (scoring + ML + CMF + IFRS 9 + forward-looking + stress).
- **Investigación** de 5 frentes (CMF, IFRS 9, scorecards/libs, arquitectura, forward/stress) — síntesis incorporadas a la spec.
- **`docs/ESPECIFICACIONES.md` v1.0** (implementable): visión, modelo de negocio (open-source = escaparate de consultora), 11 principios, dominios, arquitectura, stack con licencias, gobernanza SR 11-7.
- **`docs/normativa_cmf_parametros.md`**: tablas CMF (B-1) extraídas del texto oficial y **verificadas VISUALMENTE** (render de PDF). Comercial individual, vivienda y consumo 100% exactas; **avales §5.2 corregida** (escala Internacional estaba corrida por celdas fusionadas).
- **Andamiaje de diseño**: `docs/design/_PLANTILLA-SDD.md`, `docs/design/00-INDICE.md` (25 SDD, 7 tandas con T0), `docs/ROADMAP.md` (F0–F7 + originación).
- **AGENTS.md / CLAUDE.md** de proyecto creados.

## En curso / a medias
- Los **25 SDD están sin escribir** (solo el andamiaje). Es el grueso pendiente.
- **Pendientes CMF**: (1) haircuts de garantías financieras del B-1 letra c) — la norma los delega a otra circular (no localizada); (2) revalidar todas las matrices contra el **CNC versión 2022** antes de uso productivo.

## Próximos pasos (orden fijado por Cami)
1. **Sesión nueva = Tanda 0 (VERIFICACIÓN):** re-verificar que TODO lo ya hecho (ESPECIFICACIONES, normativa CMF, índice, roadmap, plantilla) esté correcto, con **doble-check de cada dato/tabla/decisión** contra fuente oficial. Corregir lo que falle. → Recomendado: hacerlo con **fan-out + verificación rigurosa** (la sesión tiene ultracode disponible).
2. **Cerrar esa sesión** (cierre-trabajo → actualizar este HANDOFF).
3. **Tanda 1 (Fundación):** producir SDD 01 `core`, 02 `data`, 03 `audit+governance`, 04 `tracking+report`, 05 `convenciones+config`, 24 `testing`, 25 `packaging/CI` — con fan-out (1 agente por SDD, plantilla común), integrados por DanIA.
4. Luego Tandas 2–6 (Scoring → ML → Provisiones → Forward → Validación/UI).
5. **Solo al terminar TODA la spec se empieza a programar** (Fase 0).

## Decisiones / contexto a recordar
- **Licencia Apache-2.0** (open-source); la ganancia es reputación para la consultora Nikodym. → calidad ejemplar es requisito.
- **CMF ≠ IFRS 9**: dos motores separados, provisión = máximo (piso prudencial CMF).
- **Fase 1 = scorecard de comportamiento** (sin reject inference).
- **No reinventar**: OptBinning (binning), statsmodels (inferencia), lifelines (survival). **Evitar GPL** en el core (`scikit-survival` fuera).
- **Núcleo config-driven con Pydantic v2** → habilita "UI = editor del config". `core/` sin deps pesadas; ML/UI tras extras.
- **Reporte Quarto** (HTML+PDF); **MLflow** tracking; gobernanza **SR 11-7** (model card + lineage por corrida).
- Principio nuevo y crítico: **doble verificación trazada de toda info externa** (proyecto usado por instituciones financieras).

## Callejones sin salida / no reintentar
- **Screenshot de PDF en el visor de Chrome (PDFium) no funciona** (sale en negro). Para verificación visual de PDFs: descargar el PDF (`curl`) y leerlo con la herramienta Read renderizada por páginas — eso sí funciona. Localizar páginas con `pdftotext -f N -l N` antes de leer la imagen.

## Dudas abiertas / bloqueos
- Licencia exacta: Apache-2.0 (recomendada) vs MIT — confirmar.
- `git init` + branding del repo público (parte de Fase 0).
- pandas vs polars interno (según volúmenes reales).
