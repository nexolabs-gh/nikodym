# HANDOFF

_Última actualización: 2026-06-23 · repo privado `nexolabs-gh/nikodym` · sobre commit `a37cad3`_

## Estado actual
**Nikodym RiskLib** en **fase de diseño**. **Tanda 0 (Verificación) cerrada**: la spec maestra, el roadmap, el índice de SDD, la plantilla y los parámetros normativos CMF fueron re-verificados a fondo y corregidos. **Los valores normativos CMF están triple-verificados** (texto oficial + render visual del PDF + CNC v2022) — **cero errores en cifras**. **Cero código aún** — y así sigue hasta terminar toda la especificación (los 25 SDD). El esqueleto documental está sólido y consistente; el siguiente paso es producir los SDD.

## Hecho en esta sesión (Tanda 0)
- **Verificación adversarial multi-frente** (workflow de 29 agentes: aritmética, coherencia cross-documento, licencias del stack, fórmulas cuantitativas, normativa CMF contra texto oficial, vigencia vs CNC v2022) + **verificación VISUAL** propia de las 6 tablas CMF críticas contra el render del PDF oficial.
- **Resultado normativo:** comercial individual, vivienda (60/60 celdas), factor MP, avales y consumo 2025 **coinciden 100%** con la fuente oficial y con el CNC v2022. Vigencia 2026 confirmada (ninguna circular enactada cambió las tablas).
- **12 correcciones aplicadas** (trazabilidad/coherencia/notación, ningún valor regulatorio):
  - `PE = PI × PDI` → `PE(%) = PI(%)×PDI(%)/100` (la prosa omitía el /100; las tablas siempre bien). normativa §1.1/§3/§4.
  - Cita de circular de hipotecaria y factor MP: `3.584/2015` → **`3.638/2018`** (verificado visualmente en el pie de hojas 12-13). normativa §4/§4.1.
  - Avales: cita `hoja 14` → **`hoja 18`** (verificado visualmente). normativa §5.2 + advertencia.
  - INDICE: `6 tandas` → `7 tandas (T0–T6)`.
  - ESPEC §5.4: `2 pendientes CMF` → `1` (BBB-/Baa3 ya estaba resuelto).
  - Terminología motor CMF: `EAD` → `Exposición` (EAD es término IFRS 9). ESPEC/AGENTS/ROADMAP.
  - Garantías: "reducen PDI" → 3 canales reales (sustitución/recuperación/descuento); RAN 21-10 = admisibilidad, no aforos. ESPEC §5.4.
  - hypothesis reetiquetada MPL-2.0 (copyleft débil, solo dev/test, sin riesgo). ESPEC §7.
  - Vasicek: documentada la convención de signo de Z (Z>0=expansión→menor PD). ESPEC §5.5.
  - Nota de vigilancia regulatoria (consulta pública CMF Res. Exenta 273/2025 → alcance final B-6/B-7, no toca el modelo estándar). normativa §7.
  - **COH-02 (decisión de Cami):** stress movido a **F5** (depende de los escenarios macro de F5); F6 renombrada "Validación avanzada". ESPEC §5.7/§11 + ROADMAP.

## En curso / a medias
- Nada a medias. Tanda 0 cerrada y consistente.

## Próximos pasos
1. **Sesión nueva = Tanda 1 (Fundación):** producir SDD **01 `core`, 02 `data`, 03 `audit+governance`, 04 `tracking+report`, 05 `convenciones+config`, 24 `testing`, 25 `packaging/CI`** — con **fan-out** (1 agente por SDD, plantilla común `docs/design/_PLANTILLA-SDD.md`), integrados y revisados por DanIA.
2. Luego Tandas 2–6 (Scoring → ML → Provisiones → Forward → Validación/UI).
3. **Solo al terminar TODA la spec se empieza a programar** (Fase 0).

## Decisiones / contexto a recordar
- **Licencia Apache-2.0**; la ganancia es reputación para la consultora Nikodym → calidad ejemplar es requisito.
- **CMF ≠ IFRS 9**: dos motores separados, provisión = **máximo** (piso prudencial CMF).
- **Fase 1 = scorecard de comportamiento** (sin reject inference).
- **No reinventar**: OptBinning (binning), statsmodels (inferencia), lifelines (survival). **Evitar GPL** en el core (`scikit-survival` fuera — confirmado GPL-3.0).
- **Núcleo config-driven con Pydantic v2** → "UI = editor del config". `core/` sin deps pesadas; ML/UI tras extras.
- **stress está en F5**, no F6 (decisión Tanda 0). F6 = validación avanzada.
- Principio crítico: **doble verificación trazada de toda info externa** (instituciones financieras → un número errado es riesgo regulatorio).

## Callejones sin salida / no reintentar
- **Screenshot de PDF en el visor de Chrome (PDFium) no funciona** (sale en negro). Para verificación visual de PDFs: descargar el PDF (`curl`) y leerlo con la herramienta **Read renderizada por páginas** (sí funciona). Localizar páginas con `pdftotext -f N -l N` antes de leer la imagen.
- **`pdftotext` NO respeta celdas fusionadas** → en tablas con celdas combinadas (avales, factor MP, estudiantiles PDI) los valores salen corridos. Para esas tablas SIEMPRE verificar por render visual, no solo texto extraído. (Así se detectó el error histórico de avales.)
- PDFs oficiales descargables a /tmp y verificados esta sesión: `norma_6545_1.pdf` (consolidado, tablas en pág PDF: comercial=12, incumplimiento=18, vivienda=21, factor MP=22, avales=27), `cir_2346_2024.pdf` (consumo, matrices pág 3-4), `cir_2249_2020.pdf` (CNC v2022).

## Dudas abiertas / bloqueos
- **Pendiente normativo real** (no rellenado a ojo): haircuts/factores de descuento de garantías financieras del B-1 letra c) — la norma los delega a circular específica de la CMF (no localizada). Documentado en normativa §5.2/§7.
- **Vigilancia:** consulta pública CMF (Res. Exenta 273/2025 y 10.976/2025) — vigilar su enacción antes de uso productivo; en oct-2025 su alcance contable quedó en B-6/B-7, sin tocar las matrices estándar.
- Branding y momento de pasar el repo de **privado → público** (al terminar la librería).
- pandas vs polars interno (según volúmenes reales).

## Repo
Privado en GitHub: **`nexolabs-gh/nikodym`** (https://github.com/nexolabs-gh/nikodym), branch `main`. Push directo a `main` autorizado en el cierre. Commits con co-autoría de Claude.
