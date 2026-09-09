# Enmienda SDD — el scorecard completo en la interfaz: EDA, validación formal, selección, bandas del PSI y la ficha del modelo en el informe

> **Estado: PROPUESTA, pendiente de revisión adversarial y del OK de Cami.** Diseño sin código
> (S6). Nace de la decisión 4 de Cami del 2026-09-09: «scorecard completo» = EDA con trabajo,
> panel y guía; `validation` en el formulario y en Resultados; panel de `selection` y copy de las
> bandas del PSI; y la ficha del modelo en el informe (abierto 3 de D-GOB, ya no diferido).
>
> **Base medida:** `main` = `40cb5a3da0d5483be0fcf328beb14796d6025a99` (1.12.0). **Autor /
> Fecha:** Claude Code / 2026-09-09.
>
> **Enmienda a:** SDD-27 §5/§8 (`eda`: eje de cohorte y decisión de eje), SDD-22 §5 (`validation`:
> superficie del formulario), SDD-23 §3 (secciones del formulario), SDD-26 §3/§5/§6 (contrato de
> capítulos: «Ficha del modelo» y el `ReportInputBundle`), SDD-11 y
> [`_ENMIENDA-RESUMEN-PSI.md`](_ENMIENDA-RESUMEN-PSI.md) (copy de las bandas),
> [`_SDD-UI-POR-TRABAJOS.md`](_SDD-UI-POR-TRABAJOS.md) §4 y D-JOB-18 (`validation` entra al
> catálogo con su pendiente cerrado), D-GOB abierto 3.
>
> **No toca:** el `config_hash` de ningún preset **hasta la capa de release** (§6, capa 5), la
> metodología de ningún cálculo (HL, Brier, PSI, IV, VIF), D-GOB-1…16, D-JUR, la puerta H9R ni el
> arnés. **No autoriza** bump, tag, PyPI ni recaptura de la demo: la recaptura única de la release
> (D-GOB-9) absorbe lo que esta enmienda mueve en los fixtures.

| Campo | Valor |
|---|---|
| **Enmienda** | SCORECARD-COMPLETO (D-SC-1…D-SC-16) |
| **Módulos** | `nikodym.eda` (una regla de §8), `nikodym.ui` (jobs, presets, serializers), `nikodym.report` (document, builder, results, prose), `nikodym.stability` (rótulos de banda), front `web/` (schema, ResultsTab, tipos, charts), `docs_site/` |
| **Fase** | F1 (EDA, selección, PSI son estables) + F6 (`validation`, experimental) + F7 (UI) + gobernanza |
| **Depende de** | D-JOB-1…19, D-EJE-1…7, D-OBL, D-EXI, D-ABA, D-GOB-10…16, D-EST, D-FX-8 (esqueleto), CT-1/CT-2 |
| **Lo consumen** | «Scorecard de comportamiento (PD)», «PD + LGD en una corrida», Resultados, el informe, la demo (tras la recaptura), «Empezar» y las guías |
| **Release** | Cambio observable de producto ⇒ **minor** (1.13.0). Mueve el `config_hash` de los presets F1 y F5 **sólo** en la capa 5 (§6), con nota SemVer en el CHANGELOG. Ninguna API estable rompe: la regla nueva de `eda` convierte un error en un resultado declarado (aditiva) |

## 0. Qué corrige de lo ya escrito

1. **«EDA está listo; sólo le falta superficie» es demasiado fuerte.** Medido corriendo el preset
   F1 con `eda` en sus defaults (`axis="period"`): `EdaError: La tasa de default por período
   requiere una columna de fecha`. El dataset `consumo_comportamiento` **no tiene ninguna columna
   de fecha** (medido: 0 columnas datetime; `data.window` no está en el config) y ninguno de los
   seis datasets sintéticos la tiene como datetime (`as_of_date` existe en tres, pero como texto).
   Con `axis="cohort"` y `cohort_col="cohorte"` tampoco corre: `EdaError: La estabilidad temporal
   descriptiva solo aplica al eje temporal… Las cohortes no tienen orden cronológico inferible`
   (`eda/stability.py:163-171`). Sólo corre declarando `as_of_date` como `datetime` con
   `coerce: true` en `data.schema.columns` (medido sobre F5: `done` en 8,6 s, **1 período**,
   estabilidad `not_evaluable`, 11 perfiles, 12 figuras). **Conclusión**: sin una regla nueva en
   el motor o un dataset nuevo, EDA no puede encenderse en el preset F1. Esta enmienda propone la
   regla (D-SC-2) y la decisión de eje en la interfaz (D-SC-3).
2. **`validation` con los defaults del motor tampoco corre sobre F1**: `ValidationDataError:
   binomial_by_grade requiere la columna 'grade'` (medido). El preset lo sabe y apaga
   `binomial_by_grade` (`ui/presets.py:375-392`); un trabajo que la siembre tiene que declarar
   ese override (D-EJE-2) y la opción tiene que decir qué exige (D-EXI): §3 D-SC-6.
3. **El HANDOFF dice «EDA … tiene capítulo listo».** Preciso: no es capítulo, es la **subsección**
   `context.eda` «Población y calidad de datos» del capítulo «Contexto del modelo y de la
   cartera» (`report/document.py:81,141`), y **se emite** cuando la card existe (medido en F5:
   tres tablas, figuras SVG y la prosa de `context_body`). No hace falta un capítulo nuevo de EDA.
4. **El registro dice del PSI que el rótulo «Peor PSI entre score y PD» se mantiene.** Medido:
   ese rótulo **sólo existe en el informe** (`report/prose.py:259`); la pestaña Resultados pinta
   las series y nunca el resumen (`ResultsTab.tsx:529-596`; `max_psi_by_comparison` viaja en el
   payload y no se lee). Mantenerlo incluye ponerlo donde falta (D-SC-11).
5. **Los rótulos de banda ya son copy público con DOS vocabularios**: la interfaz dice
   «Estable / Revisar / Redesarrollar / No evaluable» (`web/src/components/charts/chart-theme.ts:122-125`)
   y el informe «Estable / Requiere revisión / Requiere redesarrollo / No evaluable»
   (`report/prose.py:67-72`); la guía publica los slugs en inglés
   (`docs_site/guias/desempeno-estabilidad.md:126-128,139-148`). La decisión pendiente no es «si
   traducir», es **unificar en una fuente** (D-SC-10).
6. **El abierto 3 de D-GOB describía el síntoma («el informe no lleva la ficha») y no la causa.**
   Medida: el `ModelCard` se construye **después** de que corrió `report` (`api.py:262` →
   `:282-289`; `report` es el último paso de `_DEFAULT_DOMAIN_ORDER`) y el `ReportInputBundle` no
   tiene dónde recibirlo (`report/results.py:112-148`, `extra="forbid"`). No es un cableado que
   falte: en el orden actual el informe **no puede** recibir la ficha. D-SC-14 diseña el capítulo
   desde lo que sí existe en ese momento —las declaraciones de la institución— sin fabricar una
   segunda ficha.
7. **Conteos de campos hoja**: el HANDOFF cuenta `validation` = 32 (campos `Field(` menos
   contenedores); el barrido del gate de copy del formulario, sobre el schema completo, cuenta
   **33 rutas** (30 visibles + 3 filas de lista) y para `eda` **17**. Aquí se usan los dos: la
   tabla de copy va por campo (32 / 17) y los goldens del formulario por ruta.

## 1. El estado, medido sobre `40cb5a3`

| Pieza | Config | Preset | Trabajo | `CONFIG_SECTIONS` | `serialize_study` | Panel Resultados | Informe | Guía | Métricas D-GOB-4 | SemVer |
|---|---|---|---|---|---|---|---|---|---|---|
| `eda` | 17 hojas, 17 con `ui_*` (`eda/config.py`) | **apagada en los 4** (`presets.py:186`) | ninguno | no (15) | no (`serializers.py:48-68`) | no | subsección `context.eda` cuando hay card; `eda` en `required_sections` por defecto del motor (`report/config.py:293`) pero **no** en la lista del preset F1 (`presets.py:477-485`); el informe demo F1 no la trae | no (autodoc `api.md:140-166`) | declara no publicar (`testing/metrics.py:65-68`) | **estable** |
| `validation` | 32 hojas, 32 con `ui_*`, 1 `ui_help` (`validation/config.py`) | **F1 y F5 encendida** (familias discriminación, calibración, estabilidad; `binomial_by_grade: False`; backtesting apagado) | ninguno (D-JOB-18; comentario en `jobs.py:404-409`) | no | no | no | capítulo «Validación formal» condicional (`document.py:356-370`) con 4 familias; métrica ejecutiva «Estado técnico de validación formal» con bandas «Pass técnico / Requiere revisión / Falla técnica» (`prose.py:81-84`); el informe demo F1 la trae y su estado es **`fail` (1 de 3 tests)**, medido | no (autodoc `api.md:315-333`) | declara no publicar (`:80`) | experimental |
| `selection` | 33 rutas en el formulario | F1/F3/F5 | sí (scorecard, PD+LGD) | sí | **sí**: `selection_card` + `decisions` (`serializers.py:49,188-189,328-336`); `results-f1.json` trae la clave | **no** (0 hits en `ResultsTab.tsx`) | subsección `results.selection` + metodología; motivos traducidos por `_reason_label` (`prose.py:2655-2671`) | sí (`guias/binning-seleccion.md`) | 3 (`n_candidates`, `n_selected`, `max_abs_correlation_after_selection`) | estable |
| PSI (bandas) | `stability/results.py:39` `StabilityBand = stable/review/redevelop/not_evaluable`; `_psi_band` `:583-589`; A1+B1 implementadas | F1/F3/F5 | sí | sí | sí (`max_psi_by_comparison`, `psi_metric_by_comparison`, `bands_by_comparison`, `psi_table`, `stability_metrics`) | «Estabilidad del score»: series, leyenda por banda, **sin el resumen** | «Peor PSI entre score y PD · score/PD calibrada» (`prose.py:259-261`); bandas en prosa | sí, con slugs en inglés | 2 (`worst_psi`, `worst_csi_value`) | estable |
| ficha del modelo | `GovernanceConfig` (13 campos, D-GOB-13) | apagada en los 4 | los 10, latente | sí (15.ª) | `model_card` (post-run) | «Ficha del modelo» (S4) | **no**: card construida tras `report`; bundle sin campo; «Limitaciones y supuestos» no lee `governance` (`prose.py:2381-2460`) | sí (`guias/gobernanza.md`, dice como hecho que el informe no la incluye) | consume las de otros | experimental |

Medido además en corridas reales (scripts en el scratchpad de la sesión):

- F1 con `eda` default: **`failed`** (`EdaError`, sin fecha). F1 con `eda` por cohorte: **`failed`**
  (`EdaError`, cohorte sin cronología). `config_hash` de F1 con `eda` default:
  `ec10eb43…` → `9a69f547…` (se mueve).
- F5 con `as_of_date` declarada `datetime`+`coerce` y `eda.date_col="as_of_date"`: **`done`**;
  `eda_card = {overall_default_rate 0,072; n_periods 1; stability_flagged False; stability_value
  NaN; n_columns_profiled 11; quality_flag_counts {near_constant 3, near_unique 2}; n_figures
  12}`; el perfil univariado incluye `bad_flag` (la columna que define el target), `cohorte`,
  `portfolio`, `exposure_amount` y `lgd`; el informe emite `context.eda` con `eda.default_rate`,
  `eda.quality`, 33 menciones de `eda.univariate` y 10 `<svg>`; `serialize_study` no emite `eda`.
- F1 con `validation` en defaults del motor: **`failed`** (`ValidationDataError`, columna `grade`).
- F1 tal cual: `validation.card = {overall_status "fail", n_tests 3, n_failed 1, falta_dato []}`;
  `selection.card = {n_candidates 6, n_selected 5, excluded_by_reason {low_iv 1}}` y tabla con
  `reason ∈ {included, low_iv}`, `iv_band ∈ {none, weak, medium, strong}`, `detail = "iv=0.0029 <
  min_iv=0.02"`; `stability.card = {max_psi_by_comparison {dev_vs_holdout 0,0132, dev_vs_oot
  0,0068}, psi_metric_by_comparison {pd_psi, score_psi}, bands_by_comparison {stable, stable}}`.

Los gates que fijan el hash del preset F1 y que esta enmienda toca **sólo en la capa 5**:
`test_ui_presets.py:52` (`_EXPECTED_CONFIG_HASH`), `test_columna_cartera_ambigua.py:132`,
`test_jobs_abanico.py:748` (`_HASHES_ANTES_DEL_ABANICO`, «el oráculo es el pasado»),
`test_presets_gobernanza.py:85-115` (hash del preset == `lineage.config_hash` de
`results-f1.json`), `test_ui_presets.py:352-356` (digests del payload). El informe tiene un golden
de HTML por SHA-256 (`test_report_step.py:83`) que **no** se mueve mientras `governance` sea
`None`.

## 2. Lo que ya está construido y no hay que inventar

- **D-OBL/D-EXI/D-ABA**: decisiones obligatorias con formas de respuesta y precargas
  (`_DECISIONES_POR_SECCION`), opciones que declaran lo que exigen, estados `no_implementada` /
  `exige extra`. EDA y validación entran por ese mecanismo, no por uno nuevo.
- **D-EJE-2/4**: overrides por trabajo en el catálogo (`overrides`), con gate de ejecutabilidad
  sobre los diez (`test_jobs_ejecutables`). Es donde va `binomial_by_grade = False`.
- **D-OBL-11 `recortarCapitulosDelInforme`**: `report.sections.required_sections` del esqueleto se
  recorta a las secciones del trabajo. Añadir `eda` a un trabajo la añade a las requeridas del
  informe sin tocar el front.
- **Serializer por card** (`_CARD_KEY_BY_DOMAIN`) + `_augment_with_rich_artifacts` para tablas
  agregadas; el patrón de `stability` (card + `psi_table` + `stability_metrics`) es el molde.
- **`ResultsPanel` por props + render estático en vitest** (S4), guard por presencia, tipos
  espejo con gate Python ↔ TS en los dos sentidos (`test_gobernanza_en_pantalla.py:353-431`).
- **Gate de dos fuentes con un oráculo** (`MODEL_CARD_NO_PINTADO`, `LINEAGE_NO_PINTADO`): el
  molde para los rótulos de banda en Python y en TS.
- **Prosa ya traducida**: `_reason_label` (14 motivos de selección), `_VALIDATION_FAMILY_LABELS`,
  `_VALIDATION_STATUS_BANDS`, `_STABILITY_BANDS`, `_PSI_METRIC_LABELS`. El panel reusa esos
  vocabularios; la enmienda sólo decide cuál gana cuando hay dos.
- **`AvisoDeclaradoChip` y `esAvisoDeclarado`** (S4): la marca de aviso declarado que el panel de
  validación reutiliza para `falta_dato`.
- **Capítulos condicionales** del informe (`requires_domain`, `requires_result`): «Ficha del
  modelo» entra con `requires_governance`, un predicado más sobre el bundle.

## 3. Las decisiones que se proponen

### 3.1 EDA (D-SC-1…D-SC-5)

**D-SC-1 · `eda` entra al formulario como la 16.ª sección, «Análisis exploratorio», entre «Esquema
y target» y «Optimal Binning»**, que es su posición en `_DEFAULT_DOMAIN_ORDER`. Sus 17 descripciones
pasan a copy público; la tabla §3.6 es lo que Cami aprueba. `type` sigue `hidden`.

**D-SC-2 · Regla nueva en el motor (SDD-27 §8): con `axis="cohort"` la estabilidad temporal es
`no_evaluable`, no un error.** El analizador registra la decisión `regla="estabilidad_temporal",
accion="no_evaluable", valor="eje de cohorte sin cronología"` —el mismo tratamiento que «< 2
períodos»— y devuelve `cv/max_relative_drift/trend_slope = NaN`, `flagged=False`. SDD-27 §3 ya
declara los dos ejes como soportados y §8 ya declara el caso no evaluable; el `raise` de
`_validate_temporal_axis` contradice el primero. Es **aditivo** para un dominio estable: ningún
config válido hoy cambia de resultado; un config que hoy revienta pasa a producir tasa por cohorte,
perfiles y calidad con la señal temporal declarada no evaluable. La tasa por cohorte **sí** es
útil: es la vista de añada que ESPECIFICACIONES §5.2 pide.

**D-SC-3 · El eje de la tasa de incumplimiento es una decisión obligatoria del usuario
(D-OBL), no un default.** `_DECISIONES_POR_SECCION["eda"]` gana `eda.default_rate.axis` con dos
formas: «Por la fecha de observación» (pide `date_col`; precarga: las columnas `datetime` del
schema declarado) y «Por cohorte o añada» (pide `cohort_col`; precarga: `data.partition.strategy.cohort_col`
cuando la partición es por cohorte). Pregunta y ayuda en §3.6. Sin esta decisión, un trabajo que
siembre `eda` nacería inejecutable sobre cualquier dataset sin fecha —el defecto de clase que
D-EJE cerró—. `date_col` y `cohort_col` llevan `column_role` para que el preflight (D-INV/D-PRE)
diga «esa columna no está en tu archivo» antes de correr.

**D-SC-4 · `eda` entra a «Scorecard de comportamiento (PD)» y a «PD + LGD en una corrida»**, en
segunda posición de `sections`, **sembrada encendida** (no latente: no tiene ningún dato
institucional sin default; la decisión de eje se contesta con la precarga). No entra a «Validar un
modelo existente» —no modela; describir la población es útil pero es alcance aparte— ni a los
trabajos de provisiones. Consecuencia automática: `required_sections` del esqueleto gana `eda`
(D-OBL-11) y el informe del trabajo emite «Población y calidad de datos» con sus tablas y figuras.

**D-SC-5 · Panel «Análisis exploratorio» en Resultados y clave `eda` del serializer.**
`serialize_study` emite `eda`: la card (`overall_default_rate`, `n_periods`, `stability_flagged`,
`stability_metric_used`, `stability_threshold`, `stability_value` con `NaN → null`,
`n_columns_profiled`, `quality_flag_counts`, `n_figures`) más tres tablas agregadas:
`default_rate.by_period` (una fila por período/cohorte), `quality.by_column` (una fila por
columna) y `univariate` reducido a **una fila por tramo de las columnas perfiladas** (tramo, n,
cobertura, tasa), nunca el frame. El panel va **primero** entre los analíticos (es la población
sobre la que todo lo demás se lee): tasa global y por período/cohorte (línea o barras según el
eje), la señal de estabilidad con su indicador, umbral y valor —«No evaluable: un solo período» /
«eje de cohorte»— y la tabla de calidad con sus tres marcas en español («casi constante», «casi
única», «alta cardinalidad»); los perfiles univariados como desplegable por variable. Guard por
presencia: sin card no hay bloque. Tipos `EdaResult`, `EdaPeriodRow`, `EdaQualityRow`,
`EdaProfileRow` en `results-types.ts`, espejo con gate Python ↔ TS.

**Dos hechos medidos que la implementación tiene que resolver y esta enmienda deja fijados:**
(a) el perfil univariado con `columns=None` incluye la columna que define el target (`bad_flag`,
tasa 0 %/100 %) y las columnas de negocio que no son candidatas; el preset F1 fija
`eda.univariate.columns = binning.feature_columns` (curado, capa 5) y el esqueleto lo deja vacío
—«todas»— con la guía diciéndolo; excluir del alcance por defecto las columnas que las reglas del
target usan es una mejora del motor que se **propone** en §8 (no se cuela aquí). (b) Un dataset
con un solo período produce una figura de línea de un punto: el panel y el informe la omiten
cuando `n_periods < 2` y lo dicen.

### 3.2 Validación formal (D-SC-6…D-SC-9)

**D-SC-6 · `validation` entra al formulario como «Validación formal», después de «Estabilidad» y
antes de «Survival», y a los dos trabajos del pipeline F1, con un override en el catálogo:
`("validation.calibration.binomial_by_grade", False)`**, la misma razón escrita que el preset
(`presets.py:375-379`): el test por grado exige una columna de grado de rating que un scorecard de
comportamiento no trae. La opción se ofrece con D-EXI: encenderla exige `grade_col`, que lleva
`column_role` y entra al preflight. D-JOB-18 queda cerrado con su pendiente cumplido: la sección
existe en el formulario. «Validar un modelo existente» **no** la recibe en esta enmienda: exige
medir en la capa 2 si `check_pipeline` resuelve la familia `calibration` sobre la PD que ese
trabajo trae por la puerta de artefactos (§8-4).

**D-SC-7 · Copy público de los 32 campos y superficie de cada uno (tabla §3.7).** Seis campos no
se exponen: `schema_version` y `type` (ya `hidden`); **`hl_grouping`** (D-SUB: su segundo valor
`fixed_bands` lo rechaza el validador `_check_calibration`, «no soportado»: una opción de dos con
una sola usable es una subsección inerte); **`target_column`, `pd_column`, `partition_column`**
(D-SUB: nombran columnas del artefacto interno `calibrated_pd_frame` que el propio motor produce
—`target`, `pd_calibrated`, `partition`—; ningún otro valor corre desde el formulario). Quedan
**26 visibles**. `grade_col`, `segment_col` y las tres `realised_*_col` nombran columnas del
archivo del usuario: llevan `column_role` y D-EXI (`grade_col` exige `binomial_by_grade`; las
cuatro de backtesting exigen `backtesting.enabled`). Los códigos `FALTA-DATO-VAL-*`,
`DATO-INSTITUCIONAL-VAL-4`, «ECB», «BCBS», «chi2», «G−2 gl», «NaN» salen del copy.

**D-SC-8 · Los tres `FALTA-DATO` se muestran, no se resuelven aquí.** Medido: `VAL-2` y `VAL-3`
se gatillan con `binomial_by_grade=True` (`evaluator.py:382-389`) y `VAL-1`/`VAL-3` con el
backtesting de LGD/EAD y PD (`:431-434`); los presets no los gatillan (`falta_dato: []`). La
interfaz los pinta como **avisos declarados** —la marca de S4, con la remisión a «Avisos
declarados»— en el panel de validación y el copy de `binomial_by_grade` y de `backtesting.enabled`
lo advierte: «el corte del semáforo / la convención del test están declarados como brecha del
motor; el resultado sale marcado». Cerrarlos exige la verificación por render de las
instrucciones de la ECB y de BCBS WP14 (SDD-22 §12): trabajo normativo de doble verificación, que
se ofrece en §8-5 como tarea aparte.

**D-SC-9 · Panel «Validación formal» en Resultados, después de «Estabilidad del score», y clave
`validation` del serializer.** El serializer emite la card (`model_ref`, `families_run`,
`overall_status`, `n_tests`, `n_failed`, `falta_dato`, `dependency_versions`, `metric_sections`)
y las cuatro tablas tidy tal como las publica el motor (`discrimination`, `calibration`,
`stability`, `backtesting`), que son agregadas por partición/test/grado/segmento. El panel:
cabecera «Estado técnico» con el estado y «N de M tests fallidos», la frase de la prosa —es
evidencia técnica; el veredicto es del validador—, una sección por familia corrida (tabla), los
avisos declarados con la marca, y nada de códigos. Un solo vocabulario para el estado en informe
y pantalla (§8-3): recomendación **«Pasa» · «Revisar» · «Falla»** bajo el rótulo «Estado
técnico», sustituyendo «Pass técnico / Requiere revisión / Falla técnica» de `prose.py:81-84`.
Tipos `ValidationResult`, `ValidationCard`, `ValidationDiscriminationRow`, `ValidationCalibrationRow`,
`ValidationStabilityRow`, `ValidationBacktestRow`, con gate espejo.

### 3.3 Selección (D-SC-10)

**D-SC-10 · Panel «Selección de variables» en Resultados, entre «Análisis por variable (WoE)» y
«Escala y calibración»**, sobre la clave `selection` que el serializer ya emite. Contenido:
candidatas / seleccionadas / excluidas, los umbrales activos con su rótulo del formulario, la tabla
de decisiones (variable, incluida, motivo en español por el mapa de `_reason_label` replicado en TS
con gate, IV y banda en español —«sin poder», «débil», «medio», «fuerte», «sospechoso»—, AUC/KS,
peor correlación y con quién, VIF, CSI, forzada) y los avisos de IV alto e inestabilidad. `detail`
(texto libre del motor, p. ej. `iv=0.0029 < min_iv=0.02`) se muestra como dato de auditoría en la
fila, sin reescribirlo. Guard por presencia.

### 3.4 Bandas del PSI (D-SC-11…D-SC-12)

**D-SC-11 · Un solo vocabulario público para las cuatro bandas, con una fuente y un espejo
gateado.** `nikodym.stability.results.BAND_LABELS` (Python) es la fuente; `chart-theme.ts` la
replica y un gate compara las dos en los dos sentidos (molde `MODEL_CARD_NO_PINTADO`);
`report/prose.py` consume la fuente y retira `_STABILITY_BANDS`; la guía publica las palabras y
deja los slugs sólo en la referencia de la API. Los slugs `stable/review/redevelop/not_evaluable`
**siguen en el motor y en el JSON** (B1 no se toca): son el dato; las palabras son el copy.
**Propuesta de palabras (§8-2): «Estable» · «Revisar» · «Redesarrollar» · «No evaluable».** Son
las que la interfaz ya pinta, las de ESPECIFICACIONES §5.2 y las acciones que el motor mismo
declara (`_BAND_TO_ACTION`: none / vigilar / redesarrollar), caben en una leyenda y describen lo
que hay que hacer, que es lo que un gerente lee en un semáforo. Alternativa: las del informe
(«Estable / Requiere revisión / Requiere redesarrollo / No evaluable»), más largas y sin verbo.

**D-SC-12 · El resumen A1 se pinta en la pestaña Resultados con su rótulo.** «Estabilidad del
score» gana, arriba de las series, una fila por comparación: «Peor PSI entre score y PD ·
PD calibrada — 0,0132 · Estable», leída de `max_psi_by_comparison`, `psi_metric_by_comparison` y
`bands_by_comparison`, que ya viajan. El rótulo es el que Cami mantuvo; la identidad se pinta con
las palabras del informe («score» / «PD calibrada», `_PSI_METRIC_LABELS`).

### 3.5 La ficha del modelo en el informe (D-SC-13…D-SC-16)

**D-SC-13 · Capítulo nuevo «Ficha del modelo», condicional a que `governance` esté declarada,
entre «Introducción» y «Contexto del modelo y de la cartera».** Contrato SDD-26 §5: entra como
2-bis del modelo documental, `ChapterSpec(id="model_card", title="Ficha del modelo",
kind="prose", requires_governance=True)`, un predicado nuevo del mismo tipo que
`requires_domain`/`requires_result`. Sin `governance` **no hay capítulo** —ni vacío ni fabricado,
igual que el panel de S4— y «Limitaciones y supuestos» gana una frase factual: «La institución no
declaró propósito, supuestos ni limitaciones en esta corrida». Con `governance`, ese capítulo
remite a la ficha en vez de repetirla.

**D-SC-14 · El capítulo se construye desde lo que existe cuando corre `report`: las
declaraciones de la institución.** `ReportInputBundle` gana el campo aditivo `governance:
GovernanceDeclaration | None = None` (DTO frozen con `model_name`, `purpose`, `assumptions`,
`limitations`, `review_period_months`, `cartera`, `motor`, `fase`, `estado_validacion`, `author`),
que el builder llena desde `study.config.governance`. El capítulo publica: propósito; supuestos y
limitaciones declarados, como listas verbatim; la identidad de inventario (nombre, cartera, motor,
fase, estado de la revisión independiente, responsable) con los rótulos del copy aprobado de
D-GOB-13; la periodicidad de revisión en meses; y una remisión explícita: «las métricas, las
decisiones registradas y las fechas de emisión y de próxima revisión se fijan en la ficha
emitida al cierre de la corrida (`model_card.json` y `.md` en el directorio de la corrida)». **No
duplica métricas ni decisiones** —ya están en los capítulos de resultados y en la ficha— y **no
fija fechas**: la fecha de emisión la fija `ModelCardBuilder` después de `report`, y publicar otra
en el informe crearía dos verdades (la lección de S2a: un solo card por corrida).

**D-SC-15 · Cero códigos internos en la prosa del capítulo.** Los tags `nikodym.*`, «SR 11-7»,
«effective challenge» y los `Literal` de `motor`/`fase`/`estado_validacion` no se imprimen crudos:
se traducen con el vocabulario de D-GOB-13 y de la ficha en Resultados (S4). El gate
`test_report_codigos_internos` ya vigila `FALTA-DATO`/`DATO-INSTITUCIONAL` en el cuerpo; se
extiende a los tags y a los slugs del capítulo nuevo.

**D-SC-16 · Determinismo y goldens.** Con `governance=None` el HTML es **byte a byte** el de hoy
(`GOLDEN_STEP_HTML_SHA256` no se mueve; es el control positivo de la capa). Con `governance` el
capítulo entra al manifiesto de secciones y a los goldens nuevos; la guía de gobernanza deja de
decir «el informe no incluye la ficha» y dice qué incluye y qué remite.

### 3.6 Copy público de EDA (17 campos; lo que Cami aprueba)

| Campo | Hoy | Propuesto |
|---|---|---|
| `type` | — (`hidden`) | **No se expone.** |
| `analysis_partition` | «Población base del análisis (default: Desarrollo, donde se ajusta el modelo). Los 'fuera_de_modelo' nunca entran al denominador de default_rate.» | Sobre qué parte de tu archivo se describe la cartera. De fábrica, la partición de desarrollo, que es donde se ajusta el modelo. Las operaciones fuera del modelo se cuentan, pero no entran en la tasa de incumplimiento. |
| `default_rate.axis` | «'period' discretiza una fecha; 'cohort' usa una columna de añada/vintage.» | Cómo se agrupa la tasa de incumplimiento en el tiempo: por la fecha de observación, en períodos, o por cohorte o añada. **Decisión obligatoria** (D-SC-3): pregunta «¿Cómo quieres ver la tasa de incumplimiento en el tiempo?», ayuda «Por fecha, si tu archivo trae una fecha de observación; por cohorte, si trae la añada de cada operación. Con cohortes la señal de deterioro en el tiempo no se evalúa: no tienen un orden cronológico que el motor pueda inferir.» |
| `default_rate.date_col` | «Fecha de observación que se agrupa en períodos; la columna debe ser de tipo fecha y la corrida se detiene si no lo es.» | La columna con la fecha de observación de cada operación. Tiene que ser de tipo fecha en tu esquema; si no lo es, la corrida se detiene antes de calcular. |
| `default_rate.period_freq` | «Mensual/Trimestral/Anual para discretizar date_col.» | Cada cuánto se agrupa la fecha: por mes, por trimestre o por año. |
| `default_rate.cohort_col` | «Categórica de añada/vintage; misma noción que data.partition.cohort_col.» | La columna con la cohorte o añada de cada operación. Suele ser la misma con la que particionas tus datos. |
| `default_rate.min_obs_per_period` | «Períodos con menos elegibles se marcan como poco fiables en la tabla (no se eliminan).» | Un período con menos operaciones elegibles que esto se marca como poco fiable en la tabla. No se elimina: se ve, marcado. |
| `stability.metric` | «Indicador comparado contra el umbral para señalar redesarrollo.» | Con qué indicador se mide cuánto se mueve la tasa de incumplimiento entre períodos: variación relativa, peor desvío o tendencia. Se compara con el umbral para avisar un posible redesarrollo. |
| `stability.threshold` | «Por encima del umbral se registra una decisión señalando posible redesarrollo; la corrida continúa.» | Por encima de este valor se registra un aviso de posible redesarrollo. Es un umbral de exploración, no una regla: la corrida sigue. |
| `univariate.n_quantile_bins` | «Troceo descriptivo del perfil; no es el binning que alimenta el modelo.» | En cuántos tramos se parte cada variable numérica para ver su tasa de incumplimiento. Es sólo para describir; no es el binning que entra al modelo. |
| `univariate.rare_level_threshold` | «Niveles con frecuencia menor se agrupan en '_otros_' solo para la tabla descriptiva.» | Los valores de una variable categórica con menos frecuencia que esto se agrupan bajo «otros», sólo para la tabla. |
| `univariate.compute_descriptive_iv` | «Diagnóstico rápido etiquetado 'pre-binning'; no es el IV final del binning.» | Calcula un poder predictivo orientativo por variable sobre estos tramos. No es el IV que decide el modelo: ése lo calcula el binning. |
| `univariate.columns` | «Vacío = todas las columnas no estructurales (excluye target, estado, partición, fecha y cohorte). Define el alcance del perfil, no qué variables entran al modelo.» | Qué columnas describir frente al incumplimiento. En blanco, todas las de tu archivo salvo las estructurales (target, estado, partición, fecha y cohorte). Define qué se describe, no qué entra al modelo. |
| `quality.near_constant_threshold` | «Si un valor concentra >= este % de filas no nulas, se marca near_constant.» | Si un solo valor concentra al menos esta proporción de las filas con dato, la columna se marca como casi constante. Sólo se reporta. |
| `quality.high_cardinality_threshold` | «Categóricas con más niveles se marcan high_cardinality (solo reporte).» | Una variable categórica con más valores distintos que esto se marca como de alta cardinalidad. Sólo se reporta. |
| `sampling.enabled` | «Calcula los perfiles y figuras sobre una muestra. La tasa de default por período se calcula siempre sobre el total, nunca sobre la muestra.» | Calcula los perfiles por variable y sus figuras sobre una muestra, para archivos grandes. La tasa de incumplimiento por período se calcula siempre sobre el total. |
| `sampling.max_rows` | «Límite de filas para perfiles univariados cuando el muestreo está activo.» | Cuántas filas entran a la muestra cuando el muestreo está activo. |

Grupos del formulario: «General», «Tasa de incumplimiento», «Estabilidad temporal», «Perfiles por
variable», «Calidad de datos», «Muestreo» (los `ui_group` actuales dicen «Tasa de default» y
«Perfiles univariados»; el copy público dice «incumplimiento» y «por variable», como el resto del
sitio).

### 3.7 Copy público de `validation` (32 campos; lo que Cami aprueba)

| Campo | Superficie | Hoy | Propuesto |
|---|---|---|---|
| `schema_version` | oculto | — | — |
| `type` | oculto | — | — |
| `families` | visible | «Familias de validación que se ejecutan. El backtesting queda fuera por defecto: exige los resultados IFRS 9 y las columnas de resultado realizado.» | Qué familias de pruebas corren: discriminación, calibración, estabilidad y backtesting. El backtesting viene apagado: necesita el cálculo IFRS 9 y las columnas con lo que de verdad ocurrió. |
| `fail_on_falta_dato` | visible | «Si es True, una brecha crítica (p. ej. backtesting activo sin insumos) hace fallar la corrida en vez de quedar registrada como aviso declarado en el resultado.» | Si una prueba no puede correr por falta de un insumo, la corrida se detiene. Apagado, la brecha queda registrada como aviso declarado y la corrida sigue. |
| `discrimination.consume_performance` | visible | «Con True se toman el AUC, el Gini y el KS ya calculados en la etapa de desempeño; con False se calculan aquí con ese mismo motor, nunca con otra fórmula.» | Reutiliza el AUC, el Gini y el KS que ya calculó la etapa de desempeño. Apagado, los vuelve a calcular con el mismo motor, nunca con otra fórmula. |
| `discrimination.partitions` | visible | «Particiones sobre las que se reporta la discriminación del modelo.» | Sobre qué particiones se reporta la discriminación: desarrollo, holdout y fuera de tiempo. |
| `calibration.hosmer_lemeshow` | visible | «Activa el estadístico Hosmer-Lemeshow por grupos de PD (chi2 con G-2 gl).» | Comprueba con la prueba de Hosmer-Lemeshow que la PD predicha coincide con la observada, por grupos de PD. |
| `calibration.hl_n_groups` | visible | «Nº de grupos G del Hosmer-Lemeshow; convención estándar G=10 -> G-2=8 gl.» | En cuántos grupos de PD se parte la cartera para la prueba de Hosmer-Lemeshow. La convención estándar es diez. |
| `calibration.hl_grouping` | **oculto (D-SUB)** | «deciles (default estándar); fixed_bands reservado (exige bandas declaradas).» | — (su segundo valor lo rechaza el motor) |
| `calibration.brier` | visible | «Activa el Brier score (1/N)*suma((p-y)^2) por partición.» | Calcula el puntaje de Brier por partición: el error cuadrático medio entre la PD predicha y lo que ocurrió. Más bajo es mejor. |
| `calibration.binomial_by_grade` | visible (D-EXI: exige `grade_col`) | «Activa el contraste binomial/Jeffreys de PD por grado de rating.» | Contrasta, grado por grado, si los incumplimientos observados caben en la PD estimada. Exige una columna de grado de rating en tu archivo. Los cortes del semáforo y la convención exacta de la prueba están declarados como brecha del motor: el resultado sale con ese aviso. |
| `calibration.grade_col` | visible (columna; exige `binomial_by_grade`) | «Columna que identifica el grado de rating para el test binomial por grado.» | La columna de tu archivo con el grado de rating de cada operación. |
| `calibration.pd_test` | visible | «jeffreys (ECB feb 2019, robusto con D=0) o binomial (BCBS WP14).» | Qué prueba se usa por grado: la de Jeffreys, que se comporta bien cuando un grado no tiene incumplimientos, o la binomial clásica. |
| `calibration.alpha` | visible | «Nivel de significancia estándar de los tests de calibración; configurable.» | Nivel de significancia de las pruebas de calibración. Cinco por ciento es el estándar. |
| `calibration.traffic_light_green_alpha` | visible | «Corte del semáforo verde/ámbar sobre el p-valor del test por grado.» | Por encima de este p-valor el grado queda en verde; por debajo, en ámbar. |
| `calibration.traffic_light_red_alpha` | visible | «Corte del semáforo ámbar/rojo sobre el p-valor del test por grado; debe ser más estricto que el corte verde (rojo < verde).» | Por debajo de este p-valor el grado queda en rojo. Tiene que ser menor que el corte del verde. |
| `calibration.target_column` | **oculto (D-SUB)** | «Columna con el resultado binario (0/1) para la calibración.» | — (columna del artefacto interno) |
| `calibration.pd_column` | **oculto (D-SUB)** | «Columna con la PD calibrada que alimenta Hosmer-Lemeshow, Brier y el test por grado.» | — |
| `calibration.partition_column` | **oculto (D-SUB)** | «Columna que identifica Desarrollo, Holdout y OOT.» | — |
| `calibration.min_rows_per_group` | visible | «Grupos HL/grados bajo este mínimo se auditan como not_evaluable, no NaN.» | Un grupo o un grado con menos operaciones que esto no se evalúa: queda marcado como no evaluable en vez de dar un número engañoso. |
| `stability.consume_stability` | visible | «Con True se toma el PSI ya calculado en la etapa de estabilidad; con False se calcula aquí con ese mismo motor, nunca con otra fórmula.» | Reutiliza el PSI que ya calculó la etapa de estabilidad. Apagado, lo vuelve a calcular con el mismo motor. |
| `stability.psi_stable_threshold` | visible | «Por debajo de este valor el PSI se considera estable; al alcanzarlo o superarlo inicia la banda de revisión.» | Por debajo de este PSI la población se considera estable; desde este valor entra en la banda de revisión. |
| `stability.psi_review_threshold` | visible | «Al alcanzar o superar este valor, el PSI gatilla redesarrollo.» | Desde este PSI la banda es la de redesarrollo. Tiene que ser mayor que el umbral de revisión. |
| `backtesting.enabled` | visible (D-EXI: exige IFRS 9 activa y las columnas realizadas) | «Activa el backtesting. Exige los resultados de `provisioning_ifrs9` y las columnas de resultado realizado, que no todos los modelos del inventario tienen.» | Compara lo estimado por IFRS 9 con lo que de verdad ocurrió. Exige que la corrida calcule IFRS 9 y que tu archivo traiga las columnas con el resultado realizado. La forma exacta de la prueba de severidad y exposición está declarada como brecha del motor: el resultado sale con ese aviso. |
| `backtesting.parameters` | visible | «Parámetros IFRS 9 a contrastar realizado-vs-estimado.» | Qué parámetros se contrastan: la PD, la severidad o la exposición. |
| `backtesting.segment_col` | visible (columna) | «Columna de segmento/cartera para agregar el backtesting.» | La columna de tu archivo por la que se agrupa el contraste, por ejemplo la cartera. |
| `backtesting.alpha` | visible | «Nivel de significancia de los contrastes de backtesting; configurable.» | Nivel de significancia de las pruebas de backtesting. |
| `backtesting.one_sided` | visible | «El interés supervisor es la subestimación del parámetro (ECB); configurable.» | Prueba sólo si el parámetro se subestimó, que es lo que le importa al supervisor. Apagado, prueba desvíos en los dos sentidos. |
| `backtesting.realised_pd_col` | visible (columna) | «Columna con el default efectivo realizado del período de desempeño.» | La columna de tu archivo que dice si la operación incumplió de verdad en el período de desempeño. |
| `backtesting.realised_lgd_col` | visible (columna) | «Columna con la LGD realizada del período de desempeño.» | La columna con la severidad que de verdad se observó. |
| `backtesting.realised_ead_col` | visible (columna) | «Columna con la EAD realizada a default del período de desempeño.» | La columna con la exposición que de verdad había al incumplir. |
| `backtesting.pd_test` | visible | «jeffreys (ECB feb 2019) o binomial (BCBS WP14) para el backtesting de PD.» | Qué prueba se usa para la PD: la de Jeffreys o la binomial clásica. |

Grupos: «General», «Discriminación», «Calibración», «Semáforo», «Estabilidad», «Backtesting»,
«Columnas» (los actuales), sin cambios de nombre.

## 4. Contratos de datos (I/O)

- **Motor** (`eda`): `TemporalStabilityAnalyzer.assess` con `axis="cohort"` devuelve
  `StabilityResult(NaN…, flagged=False)` y registra `no_evaluable`. `EdaCardSection` no cambia.
- **Catálogo**: `sections` de `scorecard_pd` y `pd_y_lgd` ganan `eda` (2.ª) y `validation` (tras
  `stability`); `overrides` de ambos ganan `("validation.calibration.binomial_by_grade", False)`;
  `_DECISIONES_POR_SECCION["eda"]` con `eda.default_rate.axis` y sus dos formas.
- **Formulario**: `CONFIG_SECTIONS` 15 → **17** (`eda` en 2.ª, `validation` tras `stability`).
  Goldens medidos por el barrido del gate sobre el schema completo: formulario **527 → 527 + 17
  (eda: 16 campos visibles + la fila de la lista `columns[]`) + 29 (validation: 33 rutas − las 4
  que D-SC-7 oculta) = 573 rutas**, a confirmar al implementar; `$defs` sin cambio; el catálogo
  de defaults efectivos crece por las dos secciones.
- **`serialize_study`**: claves nuevas `eda` y `validation` (`null` cuando el dominio no corrió;
  ausentes nunca). El gate «emite exactamente estas claves» se actualiza.
- **Front**: tipos nuevos en `results-types.ts`, `ResultsResponse` gana `eda?` y `validation?`;
  paneles «Análisis exploratorio», «Validación formal», «Selección de variables»; fila de resumen
  PSI; `BAND_LABELS` espejo.
- **Informe**: `ReportInputBundle.governance` (aditivo, default `None`); `ChapterSpec` con
  `requires_governance`; `CANONICAL_SECTION_ORDER` gana `model_card` tras `introduction`;
  `_VALIDATION_STATUS_BANDS` y `_STABILITY_BANDS` pasan a consumir las fuentes únicas.
- **Presets (capa 5)**: F1 y F5 encienden `eda` con `axis="cohort"`, `cohort_col="cohorte"`,
  `univariate.columns = binning.feature_columns`; `required_sections` de F1 gana `eda`;
  `config_hash` de F1 `ec10eb43…` → el que mida la capa; F5 `b36318b5…` → ídem; goldens
  re-anclados con la decisión escrita; `results-f1.json`/`results-f5.json` recapturados.

## 5. Casos borde y errores

- `eda` por fecha sobre una columna que no es `datetime` → el preflight lo dice (`column_role`);
  si llega al motor, `EdaError` como hoy, con `loc` (D-VIS).
- `eda` por cohorte → tasa por cohorte, perfiles y calidad; estabilidad `no_evaluable` declarada;
  el panel y el informe dicen «no evaluable: eje de cohorte».
- Un solo período → `no_evaluable` como hoy; sin figura de línea de un punto.
- `validation` con `binomial_by_grade` encendido y sin `grade_col` en el archivo → preflight en
  rojo antes de correr; nunca `ValidationDataError` en pantalla.
- `validation` con backtesting encendido en un trabajo sin IFRS 9 → D-EXI lo declara en la opción
  y `check_pipeline` lo deja inejecutable con el motivo (`DATO-INSTITUCIONAL-VAL-4` sólo en el
  anexo).
- `overall_status = fail` en el preset F1 (medido: HL falla en una partición) → el panel lo
  pinta tal cual; no se maquilla ni se esconde. La guía de validación explica qué significa y qué
  hace un validador con ello.
- `governance` declarada con `assumptions=[]`/`limitations=[]` → el capítulo publica «no se
  declararon» en esa lista; el propósito no puede estar vacío (D-GOB-12).
- Corrida `failed` con `governance` declarada → sin informe, como hoy; el capítulo no aplica.

## 6. Orden de capas, gates y controles negativos preespecificados

Cada capa cierra con sus gates verdes, sus CN, revisión adversarial y commit propio (una capa por
sesión de implementación, como D-GOB).

**Capa 1 — Selección, PSI y resumen (sin schema, sin hash, sin motor).** D-SC-10, D-SC-11,
D-SC-12. Gates: `ResultsTab.test.ts` renderiza el panel de selección con el fixture F1 real
(contiene `low_iv`) y sin `selection`; el resumen PSI con `pd_psi` ganador y con `score_psi`;
gate Python ↔ TS de `BAND_LABELS` y del mapa de motivos; `test_prosa_factual` con las palabras
nuevas; docs (`desempeno-estabilidad.md`, `binning-seleccion.md`) sin slugs, `mkdocs --strict`.
**CN**: cambiar «Revisar» sólo en TS → rojo el gate espejo; pintar el resumen con la banda del
score cuando gana la PD → rojo (el caso divergente de A1, reinyectado).

**Capa 2 — `validation` en el formulario y en Resultados.** D-SC-6…D-SC-9. Gates:
`test_jobs_catalogo` (17 secciones, todas con trabajo), `test_jobs_ejecutables` (los diez, con el
override), `test_copy_del_formulario` (26 visibles, 160 caracteres, sin literales Python, sin
códigos), `test_jobs_abanico` (sus `Literal` declarados o exentos con razón), `gen_schema_fixture`
+ `gen_jobs_fixture` + bundle, `test_extra_ui_cubre_el_formulario` (`validation` → extra `scoring`,
ya dentro de `[ui]`), gate espejo de tipos, `ResultsTab.test.ts` con una corrida real con
`validation` (estado `fail` real) y con `null`, preflight de `grade_col`, guía nueva
`docs_site/guias/validacion-formal.md`, «Empezar». **CN**: quitar el override del catálogo →
`test_jobs_ejecutables` en rojo por `grade`; exponer `hl_grouping` → rojo el gate D-SUB; dejar un
`FALTA-DATO-VAL` literal en un tooltip → rojo el copy gate; quitar el guard del panel → rojo el
render con `null`.

**Capa 3 — EDA: regla del motor, decisión de eje, formulario, panel, informe.** D-SC-1…D-SC-5.
Gates: test del analizador con `axis="cohort"` (decisión `no_evaluable`, sin excepción) **nacido
rojo** sobre el árbol actual; `test_jobs_ejecutables` con la decisión contestada por la precarga
(cohorte) sobre el esqueleto de los dos trabajos; corrida real por `/api/run` del trabajo
scorecard sobre `consumo_comportamiento` con eje de cohorte → `done`, `eda` en el payload,
`context.eda` en el informe con tablas y figuras y sin figura de un punto; copy gate de los 17;
guía nueva `docs_site/guias/analisis-exploratorio.md`; ejemplo por código ejecutado por gate
(marcadores). **CN**: revertir la regla del motor → el test nacido rojo vuelve a rojo y la
corrida del trabajo falla con `EdaError`; quitar la decisión de eje → esqueleto inejecutable en
`test_jobs_ejecutables`; perfilar la columna del target en el preset → el gate del preset (capa 5)
lo acusa.

**Capa 4 — «Ficha del modelo» en el informe.** D-SC-13…D-SC-16. Gates: golden HTML intacto con
`governance=None` (control positivo); capítulo presente con `governance` real de una corrida por
formulario (`b9633af1…`-like), en HTML, PDF (job CI), DOCX y QMD; `test_report_codigos_internos`
ampliado a tags y slugs; el manifiesto lista `model_card`; «Limitaciones y supuestos» con la frase
factual sin gobernanza y con la remisión con ella; guía de gobernanza actualizada. **CN**: pintar
el capítulo con `governance=None` → rojo el golden; imprimir `nikodym.cartera` crudo → rojo el gate
de códigos; poner una fecha de emisión en el capítulo → rojo el test que exige la remisión sin
fechas.

**Capa 5 — Release (sesión propia, con el OK de release y de D-GOB-9).** Presets F1/F5 encienden
`eda`; re-anclaje de los cinco goldens de hash con la decisión escrita en el registro; CHANGELOG
con el antes/después del hash; recaptura única (F1, F4, F5, con la ficha); retiro de las ocho
notas «Si instalaste desde PyPI»; bump a 1.13.0. **CN**: el gate del fixture de la demo en rojo
entre el flip y la recaptura es la razón de que las dos cosas vayan en la misma capa.

## 7. Lo que esta enmienda NO hace

- No cambia ninguna fórmula ni umbral: HL, Brier, Jeffreys, PSI, IV, VIF y las fronteras B1
  quedan como están.
- No cierra los `FALTA-DATO-VAL-1/2/3`: los muestra (§8-5 ofrece cerrarlos aparte).
- No mete `validation` en «Validar un modelo existente» sin medirlo (§8-4).
- No añade métricas D-GOB-4 de `eda` ni de `validation` a la ficha (§8-6).
- No fabrica una segunda ficha del modelo dentro de `report`, ni mueve el `ModelCard` a un `Step`
  (D-GOB-10: `governance` no tiene `Step`).
- No recaptura la demo, no mueve hashes antes de la capa 5, no publica.
- No toca el copy aprobado de D-GOB-13 ni el de la ficha en Resultados: los reutiliza.

## 8. Lo que Cami decide

1. **¿Se aprueban D-SC-1…D-SC-16 y el orden de capas 1 → 2 → 3 → 4 → 5?** Recomendación: sí,
   con la capa 5 pegada a la release por el gate del fixture de la demo.
2. **Las cuatro palabras de las bandas del PSI.** Recomendación: **«Estable» · «Revisar» ·
   «Redesarrollar» · «No evaluable»** (las de la interfaz y de ESPECIFICACIONES §5.2).
   Alternativa: «Estable · Requiere revisión · Requiere redesarrollo · No evaluable» (las del
   informe).
3. **Las tres palabras del estado técnico de la validación formal.** Recomendación: **«Pasa» ·
   «Revisar» · «Falla»** bajo el rótulo «Estado técnico» (con la frase de que el veredicto es del
   validador). Alternativa: conservar «Pass técnico / Requiere revisión / Falla técnica».
4. **¿`validation` entra también a «Validar un modelo existente»?** Recomendación: **medirlo en la
   capa 2** (`check_pipeline` con la PD por la puerta de artefactos) y entrar sólo si el esqueleto
   resulta ejecutable; si no, declararlo en la guía como «por código».
5. **¿Se abre una tarea aparte para cerrar `FALTA-DATO-VAL-1/2/3`** (verificación por render de
   las instrucciones ECB 2019 y BCBS WP14, doble verificación trazada)? Recomendación: sí, después
   del scorecard completo; no bloquea esta enmienda porque los presets no los gatillan.
6. **¿`eda` declara métricas D-GOB-4** (`overall_default_rate`, `n_periods`,
   `stability_flagged`) para que la ficha del modelo las lleve? Recomendación: sí, en la capa 3,
   son tres escalares con productor; alternativa: mantener «declara no publicar».
7. **Copy público**: ¿se aprueban las tablas §3.6 (17) y §3.7 (32, con 6 ocultos) y la decisión
   de eje de §3.6?
8. **Mejora del motor propuesta, no incluida**: excluir del perfil por defecto de EDA las columnas
   que usan las reglas del target (`bad_flag` sale como «tasa por tramo» 0 %/100 %). Cambia el
   resultado de `columns=None` en un dominio estable ⇒ minor con nota; recomendación: hacerlo en
   la capa 3 si Cami lo aprueba, si no, el preset lo evita por `columns` explícitas y la guía lo
   advierte.
