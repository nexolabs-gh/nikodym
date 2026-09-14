# Enmienda SDD — las deudas declaradas de `validation`: cotejo doble contra las fuentes oficiales y cierre

> **Estado: PROPUESTA, pendiente de Cami** (§8). Diseño sin código: esta enmienda mide y decide;
> **no programa nada** hasta la aprobación. Nace de las respuestas 5, 11 y 12 de Cami del
> 2026-09-09 a [`_ENMIENDA-SCORECARD-COMPLETO.md`](_ENMIENDA-SCORECARD-COMPLETO.md) §8 —«tarea
> aparte para `FALTA-DATO-VAL-1/2/3`», «el recálculo del PSI queda oculto, con tarea aparte para el
> cableado», «el mínimo por grupo de Hosmer-Lemeshow exige su propia enmienda con goldens»— y del
> abierto que S11 dejó medido en el `HANDOFF`.
>
> **Base medida:** `main` = `00791102eb424eddb61de61ff70a9c45dcc8ee6e` (bump 1.15.1 sobre
> `9ffb7bc`). **Autor / Fecha:** Claude Code / 2026-09-13 (S12). **Revisión adversarial:**
> pendiente (Codex, sobre este documento, antes de elevar).
>
> **Enmienda a:** SDD-22 §3.2/§3.4 (fórmulas y su cotejo), §5 (`consume_stability`,
> `min_rows_per_group`), §7 (fallback de estabilidad), §8 (grupos HL bajo mínimo), §12 (los tres
> `FALTA-DATO-VAL` y sus fuentes) y D-VAL-2/5/7; SDD-11 §4 (un ensamblador de frame reutilizable);
> `docs_site/avisos-declarados.md` (catálogo) y el copy de dos campos de `validation` (§8-7 del
> scorecard completo: cambiar un texto es copy, no reabre el diseño).
>
> **No toca:** ninguna fórmula (HL, Brier, Jeffreys, binomial, t-test, PSI), ningún `config_hash`
> de preset (medido en §1.4), el `GOLDEN_STEP_HTML_SHA256` ni los fixtures de la demo (medido en
> §1.4), CMF, el arnés H9R, D-SC-1…16 ni PARIDAD-1-1. **No autoriza** bump, tag, PyPI ni recaptura.

| Campo | Valor |
|---|---|
| **Enmienda** | VALIDACION-COTEJADA (D-VAL-13…D-VAL-18; continúa la numeración D-VAL-1…12 de SDD-22) |
| **Módulos** | `nikodym.validation` (evaluator, calibration_tests, backtesting, config, step), `nikodym.stability.step` (un ensamblador público), `nikodym.report.prose` (frases de avisos y metodología), `docs_site/` (catálogo y guía), front `web/` (schema, un fixture de test) |
| **Fase** | F6 (`validation`, **experimental**, fuera de la garantía SemVer 1.x) |
| **Depende de** | SDD-22, SDD-11, D-VIS (ningún error sin superficie), D-SUB (subsección inerte), D-FTE/D-VER (fuente y verificador de un cotejo), D-CRP6 (`fail_on_falta_dato`), CT-1/CT-2 |
| **Lo consumen** | «Scorecard de comportamiento (PD)», «PD + LGD en una corrida», Resultados («Validación formal»), el capítulo «Validación formal» del informe, la guía `validacion-formal.md`, la referencia `avisos-declarados.md` |
| **Release** | Cambio observable en un dominio experimental (dos códigos de aviso desaparecen, uno cambia de naturaleza, una prueba deja de dar veredicto con grupos sin potencia, un campo oculto se expone) ⇒ **minor** (1.16.0) con nota. Ninguna API estable rompe. **Sin recaptura** de la demo (§1.4) |

---

## 0. Qué corrige de lo ya escrito

1. **«Los cortes del semáforo siguen la convención de Basilea (1996)» es falso.** Lo dice la
   frase pública del aviso (`report/prose.py:1068-1071`) y el catálogo
   (`docs_site/avisos-declarados.md:54`: «los cortes del semáforo de VaR (Basilea-1996) no están
   verificados contra el render oficial»). Medido contra el render del documento oficial (§2,
   fuente F3, Tabla 2): Basilea 1996 define las zonas por la **probabilidad acumulada del número
   de excepciones** de un VaR al 99 % sobre 250 días —amarilla desde el 95 %, roja desde el
   99,99 %—; en términos de p-valor unilateral serían cortes en **0,05 y 0,0001**. El motor corta
   en **0,05 y 0,01** (`validation/config.py:217-245`, D-VAL-5) y nunca implementó otra cosa. No
   hay «convención de Basilea» que verificar: los cortes son el default institucional que D-VAL-5
   propuso, y así lo dice ya el `ui_help` del campo. La verificación no puede confirmar un anclaje
   que no existe; lo que corresponde es dejar de atribuirlo (§3, D-VAL-15).
2. **«La forma exacta del t-test del BCE —simple o ponderada por exposición, y su orientación—
   no está verificada» ya no es cierto.** Verificada por doble vía (§2): el estadístico del BCE
   es `T = √N · ē / s` sobre el error por facilidad `e_i = realizado_i − estimado_i`, con `s²`
   muestral (`N − 1`), **sin ponderar por exposición** («number-weighted averages» en la plantilla
   oficial), unilateral con `H0: estimado ≥ realizado` y p-valor `1 − S_{N−1}(T)` (Student con
   `N − 1` gl). Es exactamente `backtesting.py::ttest_realised_vs_predicted` con
   `one_sided=True`. La deuda `FALTA-DATO-VAL-1` está cerrada por medición.
3. **«La orientación exacta del p-valor de Jeffreys no está verificada» tampoco.** Verificada por
   doble vía (§2): `p = β_{D+½, N−D+½}(PD)`, la función de distribución de la beta posterior
   evaluada en la PD del grado, con `H0: PD aplicada ≥ PD verdadera`; la plantilla oficial lo
   calcula literalmente como `BETA.DIST(PD, D+0.5, N−D+0.5, TRUE)` sobre la PD **media** del grado.
   Es exactamente `calibration_tests.py::binomial_by_grade` con `test="jeffreys"`. La deuda
   `FALTA-DATO-VAL-3` está cerrada por medición.
4. **La fórmula del t-test de CCF impresa en el PDF (§2.9.3.1, p. 53) omite el `1/R` del
   numerador**: `T = √R · Σ(CCF_R − CCF_E) / √s²`. Es una errata del documento: las fórmulas de
   LGD (§2.6.2.1, p. 31), ELBE (§2.7.2.1), LGD in-default (§2.8.2.1) y EAD (§2.9.3.2, p. 55)
   llevan la media, y la plantilla oficial de CCF calcula el p-valor con la **diferencia de
   medias** (`SQRT(R)*(mean_R − mean_E)/SQRT(s²)`). El motor sigue la forma con media, que es la
   única consistente con «Student-t con `R − 1` gl». Queda escrito para que nadie «corrija» el
   motor hacia la errata.
5. **«La versión vigente del documento del BCE» es la de febrero de 2019.** Medido el
   2026-09-13: la página oficial *Ongoing model monitoring* del BCE enlaza el mismo PDF
   (`creationDate 2019-02-28`, `modDate 2019-03-05`, sha256 en §2) y las plantillas de reporte
   (ZIP con seis libros, fechados 2020-11 a 2021-03). No existe una versión posterior de las
   instrucciones; la actualización de 2025 es del *ECB guide to internal models*, que remite al
   *Supervisory handbook* de la EBA (EBA/REP/2023/29) y no redefine estos estadísticos.
6. **La deuda que el catálogo llama «brecha del motor» era, en dos de tres casos, una brecha de
   verificación —ya cerrada— y en el tercero un rótulo equivocado.** Ninguna de las tres exigía
   cambiar una fórmula. La consecuencia de contrato es de superficie: qué códigos deja de emitir
   la card, qué frases desaparecen de la prosa, el copy y el catálogo, y cómo se registra el
   cotejo (D-FTE/D-VER exigen fuente y verificador para todo cotejo nuevo).
7. **§0-9 y §0-21 del scorecard completo siguen vigentes sobre `0079110`**, medidos de nuevo:
   `ValidationStep.execute` (`validation/step.py:110-122`) nunca pasa `stability_frame`, así que
   `consume_stability=False` cae a un fallback que exige ese frame (`evaluator.py:394-411` →
   `stability.py::evaluate_stability`) y aborta con `ValidationDataError`; y
   `_hosmer_lemeshow_record` compara `min_rows_per_group` con la **partición entera**
   (`evaluator.py:329`) y llama al kernel sin mínimo (`:340`), de modo que una partición de 100
   operaciones con 10 grupos y mínimo 30 recibe veredicto con grupos de 10, mientras que el test
   por grado sí aplica el mínimo grado a grado (`:376`).

## 1. El estado, medido sobre `0079110`

### 1.1 Dónde vive cada código (motor, prosa, interfaz, docs, tests)

Censo por `git grep` sobre el árbol; los consumidores filtran por
`nikodym.core.markers.is_declared_warning()` y ninguno decide por el literal (regla de
`AGENTS.md`). Las líneas son las del árbol base.

| Superficie | `FALTA-DATO-VAL-1` (t-test) | `FALTA-DATO-VAL-2` (semáforo) | `FALTA-DATO-VAL-3` (Jeffreys) |
|---|---|---|---|
| **Motor: constantes y emisión** | `validation/evaluator.py:110`; se emite en `_resolve_backtesting` (`:432`) cuando `lgd` o `ead` están en `backtesting.parameters` y el backtesting corrió | `evaluator.py:108`; `_calibration_falta_dato` (`:387`) cuando `binomial_by_grade=True` | `evaluator.py:109`; `:389` con `binomial_by_grade=True` y `pd_test="jeffreys"`; `:434` con `pd` en los parámetros del backtesting y `backtesting.pd_test="jeffreys"` |
| **Motor: docstrings y comentarios** | `backtesting.py:30-33, 91` | `calibration_tests.py:20-22, 56-58, 129-132, 204`; `config.py:606` (nota de numeración) | `calibration_tests.py:20-22, 129-132`; `backtesting.py:33` |
| **Card y trail** | `ValidationCardSection.falta_dato` (`results.py:468`); `ValidationStep._emit_decisions` registra `validation_falta_dato` por cada código (`step.py:234-241`) | ídem | ídem |
| **Prosa del informe** | `report/prose.py:1063-1067` («sigue la convención del BCE, cuya forma exacta … todavía no se cotejó») | `:1068-1071` («siguen la convención de Basilea (1996)…») | `:1072-1075`; nota de deduplicación `:1125` |
| **Interfaz (Resultados)** | `web/src/components/ResultsTab.tsx:988-1008`: cuenta las salvedades de `falta_dato` y remite al catálogo; no pinta el código (D-SC-9) | ídem | ídem; fixture de test `ResultsTab.test.ts:577` |
| **Copy del formulario** | `config.py:394-404` (`backtesting.enabled`: «La forma exacta de la prueba de severidad y exposición está declarada como brecha del motor: el resultado sale con ese aviso») | `config.py:173-181` (`binomial_by_grade`: «Los cortes del semáforo y la convención exacta de la prueba están declarados como brecha del motor…»); `ui_help` de `traffic_light_green_alpha` (`:217-232`: «default institucional, no un umbral fijado por norma») | `config.py:173-181` (la misma frase) |
| **Docs públicas** | `docs_site/avisos-declarados.md:53`; guía `validacion-formal.md:103-106` («son una brecha del motor que Nikodym prefiere decir en voz alta») | `avisos-declarados.md:54`; guía `:103-106` | `avisos-declarados.md:55`; guía `:103-106` |
| **SDD-22** | `22-validation.md:143, 592, 599, 613` (D-VAL-7) | `:118, 392, 490, 506, 585, 593, 600, 611` (D-VAL-5) | `:116, 592, 601` |
| **Tests que afirman el código** | `test_validation_evaluator.py:468, 598, 814`; `test_core_markers.py:33`; `test_report_codigos_internos.py:48` | `test_validation_evaluator.py:151, 317`; `test_validation_results.py:277, 577`; `test_copy_del_formulario.py:222-252`; `test_report_codigos_internos.py:48` | `test_validation_evaluator.py:152, 469, 599, 815`; `test_report_codigos_internos.py:48` |
| **Gates del catálogo** | `test_public_copy.py:116-135`: la página documenta **cada** código que nombra un `.py` de `src/nikodym` **y no inventa ninguno** — el censo lee docstrings y comentarios, así que retirar un código exige retirarlo también de todo texto del paquete | ídem | ídem |

`DATO-INSTITUCIONAL-VAL-4` (backtesting pedido y apagado) no está en alcance y no cambia.

### 1.2 Qué hace el motor hoy con cada convención (y qué dice la fuente)

| Convención | Motor (`0079110`) | Fuente oficial (§2) | Veredicto |
|---|---|---|---|
| Jeffreys por grado | `beta.cdf(p̂, D+½, N−D+½)` con `p̂` = PD media del grado (`calibration_tests.py:157`); unilateral hacia la subestimación | BCE §2.5.3.1: `β_{D+½, N−D+½}(PD)`, `H0: PD aplicada > verdadera`; plantilla PD 3.0 col. N: `BETA.DIST(PD_i, D_i+0.5, N_i−D_i+0.5, TRUE)` con `PD_i` = «(Average) estimated PD» | **Coincide.** Reproducido: N=200, D=7, PD=0,025 → motor 0,177852704399066 = fórmula BCE = integral numérica de la densidad (2·10⁶ nodos) a 2·10⁻¹⁴ |
| Binomial por grado | `binomtest(D, N, p̂, alternative="greater")` = `P(X ≥ D)`; `z` asintótico | BCBS WP14 p. 47: `H0` PD correcta, `H1` subestimada; rechazo si `k ≥ k*` con `Σ_{i≥k} C(n,i)PDⁱ(1−PD)ⁿ⁻ⁱ ≤ 1−q`; aproximación normal `k* = Φ⁻¹(q)√(nPD(1−PD)) + nPD` | **Coincide.** Reproducido: 0,235945960229294 en ambos |
| t-test LGD/EAD | `T = √N·ē/s`, `s` con `ddof=1`, `p = t.sf(T, N−1)` (`one_sided=True`); `2·t.sf(|T|, N−1)` con `one_sided=False`; sin pesos | BCE §2.6.2.1 (LGD) y §2.9.3.2 (EAD): `T = √N · (1/N)Σ(R_i − E_i) / √s²`, `s² = Σ(e_i − ē)²/(N−1)`, `p = 1 − S_{N−1}(T)`; plantillas LGD 2.0 y CCF 3.1/3.2: `1 − T.DIST(SQRT(N)*(mean_R − mean_E)/SQRT(s²), N−1, TRUE)` sobre promedios **number-weighted** | **Coincide** en forma, ponderación, orientación y distribución. Reproducido con N=50: `T` 2,70272856597448 y `p` 0,00471202123926 en ambos. El bilateral es la convención de ELBE (§2.7.2.1: `2·(1 − S_{N−1}(|T|))`) |
| Semáforo por grado | `p ≥ 0,05` verde · `0,01 ≤ p < 0,05` ámbar · `p < 0,01` rojo, cortes de config (`traffic_light`, `_reseal_traffic_light`) | BCE 2019: **no fija** cortes ni colores sobre el p-valor (la plantilla sólo compara el p-valor reportado con su cálculo, «>0.001% deviation»). BCBS 1996 Tabla 2: zonas por probabilidad acumulada del número de excepciones de VaR, amarilla ≥ 95 %, roja ≥ 99,99 %. WP14 §III: el «traffic lights approach» de Blochwitz-Hohl-Wehn es multi-período con cuatro colores sobre cuantiles normales, otra herramienta | **No hay anclaje regulatorio que verificar.** Los cortes son política institucional (D-VAL-5). La frase «siguen la convención de Basilea (1996)» es falsa (§0-1) |
| Alcance del Jeffreys | Sólo por grado (no hay fila de portafolio) | BCE: «at portfolio level and at the level of all individual rating grades» | Diferencia de **alcance**, no de fórmula; fuera de esta enmienda (§7) |

### 1.3 Lo que no está cableado ni protegido

- **Recálculo del PSI (`consume_stability=False`).** `stability.py::stability_recomputed` existe,
  reutiliza `StabilityEvaluator` y tiene sus tests (`test_validation_stability.py`), pero ningún
  camino del `Study` llega a él: `_requires_for` exige siempre `stability.stability_metrics` y
  `psi_table` cuando la familia está activa (`step.py:316-318`) y `execute` no construye el frame
  (`:110-122`). D-VAL-2 prometió «consumir el artefacto; fallback por reúso»; hoy el fallback es
  inalcanzable y el toggle sólo tiene un valor que corre (por eso D-SC-7 lo ocultó, D-SUB). El
  frame que el recálculo exige es el que arma `stability/step.py::_assemble_stability_frame`
  (`:273`): `scorecard.score` + `calibration.calibrated_pd_frame` alineados por índice, más la
  columna temporal (`data.frame` sólo si el score no la trae, `:240`), los `__points` para el CSI
  (`binning.bin_frame` opcional, `:259`) y la coherencia de dirección del score (`:200`). Todo
  eso lo gobierna `NikodymConfig.stability` (SDD-11), que es **opcional** en el config
  (`core/config/schema.py:455-465`); el paso de estabilidad usa su propio default como respaldo
  (`_stability_config_from_study`, `:226`).
- **Mínimo por grupo de Hosmer-Lemeshow.** `min_rows_per_group=30` (default) protege la partición
  (`evaluator.py:329`) y el grado (`:376`); el kernel sólo marca `not_evaluable` un grupo vacío o
  con denominador cero (`calibration_tests.py:85-91`). Con `hl_n_groups=10`, una partición de 100
  operaciones recibe veredicto con grupos de 10 (§0-21 del scorecard completo). El título del campo
  («Mínimo de operaciones para evaluar») y su `ui_help` ya dicen que **no** se aplica por grupo.

### 1.4 Goldens y fixtures: qué se mueve y qué no

| Golden | Contenido medido | ¿Se mueve? |
|---|---|---|
| `test_ui_presets.py:56` `_EXPECTED_CONFIG_HASH` (F1 `1063d6cf…`), F5, y los hashes de `test_jobs_abanico.py`, `test_columna_cartera_ambigua.py`, `test_presets_gobernanza.py` | hash de **valores** del config; ninguna decisión cambia un valor de preset (`consume_stability: true` sigue; los cortes siguen) | **No** |
| `web/src/fixtures/demo/results-f1.json` (firma) | `validation.falta_dato == []` (F1 no gatilla ningún `VAL`: `binomial_by_grade: false`, backtesting apagado); `metric_sections.validation.not_evaluable_grades == []` | **No** mientras no se añada una clave nueva a `metric_sections` (§3, D-VAL-17 lo evita) |
| `report-f1.html/.pdf/.docx` de la demo | 0 apariciones de «Basilea», «Jeffreys», «BCE», «salvedad», «brecha del motor»; la prosa de calibración es genérica (`prose.py:1184-1185`) | **No**, si la frase nueva de los cortes (D-VAL-15) se emite **sólo cuando corrió** el contraste por grado |
| `GOLDEN_STEP_HTML_SHA256` (`test_report_step.py:88`) | el bundle golden no lleva `validation` (`:112-113`: `report` no la exige) | **No** |
| `GOLDEN_HTML_SHA256` del renderer | sin `validation` | **No** |
| HL de la demo F1 | particiones 4.019 / 973 / 1.008 con 10 grupos → grupos de ≥ 97 > 30 | **No** con D-VAL-17 |
| `web/src/fixtures/schema.json` y el bundle `src/nikodym/ui/static` | descripciones de `binomial_by_grade` y `backtesting.enabled`; `ui_widget` de `consume_stability` | **Sí**, regenerados por `gen_schema_fixture.py` + `build:package` (no es recaptura) |
| Ledger `option_surface` (`test_option_surface_ledger.py`), `test_effective_defaults.py:87-89`, `test_jobs_abanico.py:207` | listan `consume_stability` como oculto por D-SUB | **Sí** con D-VAL-16 (un campo deja de ser oculto) |
| Fixtures de `test_validation_evaluator.py` (`_analytic_frame`: 60/30/30 filas, `hl_n_groups=5`, `min_rows_per_group=10`) | grupos de 12 / 6 / 6 | **Sí** con D-VAL-17: holdout y oot pasan a `not_evaluable` salvo que el fixture baje el mínimo o los grupos (§6) |

## 2. El cotejo doble, trazado (D-FTE/D-VER: fuente, verificador y método)

Todo se descargó de la URL oficial el 2026-09-13 (hora local) y se verificó por **dos vías
independientes**: (i) extracción de texto (`pypdf`) del PDF oficial y (ii) **render** de la página
a PNG (`pymupdf 1.28.2`, zoom 2×) leído visualmente; y, para el BCE, una **tercera** fuente oficial
distinta del PDF: las plantillas de reporte, cuyas fórmulas de Excel calculan el p-valor que el
BCE espera («The institution's reported value should match the ECB's calculation»). Verificador:
Claude Code, sesión S12; la revisión adversarial de Codex sobre este documento se anota en el
`HANDOFF`. Las copias y los renders quedan en el scratchpad de la sesión; el sha256 basta para
reproducir la descarga.

| # | Fuente | URL oficial | sha256 del archivo descargado | Qué se leyó (página del PDF · sección) | Resultado |
|---|---|---|---|---|---|
| F1 | BCE, *Instructions for reporting the validation results of internal models — IRB Pillar I models for credit risk*, febrero 2019 (70 pp.; metadata `creationDate 2019-02-28`, `modDate 2019-03-05`) | `https://www.bankingsupervision.europa.eu/activities/internal_models/shared/pdf/instructions_validation_reporting_credit_risk.en.pdf` (enlazado desde `…/activities/internal_models/omm/html/index.en.html`) | `f0bef87b1c636b8dc493e0d8e8b0690a5660a0663086ea6f676ccae2a7685d01` | p. 20-21 (impresas; 21-22 del PDF) · §2.5.3.1 «PD back-testing using a Jeffreys test»; p. 31 (impresa; 32 del PDF) · §2.6.2.1 «LGD back-testing using a t-test»; p. 53 (impresa; 54 del PDF) · §2.9.3.1 (CCF); p. 55 (impresa; 56 del PDF) · §2.9.3.2 (EAD); p. 40-41 · §2.7.2.1 (ELBE, bilateral) | Jeffreys y t-test **coinciden** con el motor (§1.2); errata del `1/R` en CCF (§0-4); ningún corte de semáforo |
| F2 | BCE, plantillas oficiales de reporte (ZIP, 6 libros `.xlsx`, 2020-11-24 … 2021-03-16) | `https://www.bankingsupervision.europa.eu/banking/tasks/internal_models/shared/pdf/templates_validation_reporting_credit_risk.zip` | `68a86250453166c6dde3f0e45d8d2c7cd44bde0b73f575808f3786a77119e5fa` | `LEICode_PD_…xlsx` hoja `3.0`, col. N (`BETA.DIST(E,G+0.5,F−G+0.5,TRUE)` con E = PD media, F = N, G = D) y col. O (tolerancia 10⁻⁵); `LEICode_LGD_…xlsx` hoja `2.0` col. AI (`1−T.DIST(SQRT(E)*(H−G)/SQRT(U),E−1,TRUE)` con H/G promedios *number-weighted*); `LEICode_CCF_…xlsx` hojas `3.1` col. AI y `3.2` fila 12 | **Coinciden** con el motor; confirma la errata de F1 §2.9.3.1 |
| F3 | BCBS, *Supervisory framework for the use of "backtesting" in conjunction with the internal models approach to market risk capital requirements*, enero 1996 (15 pp.) | `https://www.bis.org/publications/199601-standards-supervisory-framework-use-backtesting-conjunction-internal-models-approach-market-risk-capital.pdf` (landing `https://www.bis.org/publ/bcbs22.htm`) | `e3dd0e08100ad19dd88f0305cf25c0af5384b5272f2e72aa9c10daa79fd73f28` | p. 7-8 (impresas) · (c)-(f) definición de zonas; p. 15 del PDF · Tabla 2 | Zonas por probabilidad acumulada de excepciones de VaR (95 % / 99,99 %); **no aplica** a la calibración de PD y no coincide con 0,05/0,01 |
| F4 | BCBS, Working Paper No. 14, *Studies on the Validation of Internal Rating Systems* (revised), mayo 2005 (120 pp.) | `https://www.bis.org/publications/studies-validation-internal-rating-systems-revised.pdf` (landing `https://www.bis.org/publ/bcbs_wp14.htm`) | `49cfd1cea68f7e7491f34d97b9660dfb4d4a0b23041868012c835728d9358188` | p. 47 (impresa; 55 del PDF) · «Binomial test»; p. 34-35 (impresas; 42-43 del PDF) · «traffic lights approach» (Blochwitz, Hohl y Wehn 2003) | Binomial **coincide** con el motor; el traffic lights de WP14 es multi-período, cuatro colores, otra herramienta: no ancla el semáforo por p-valor |

Lo que **no** se pudo verificar y se declara: el texto de Hosmer & Lemeshow (*Applied Logistic
Regression*) no está en línea; el estadístico y los `G − 2` gl ya estaban confirmados en SDD-22 §12
(2026-07-03) y esta enmienda no toca la fórmula. La regla de «mínimo por grupo» de D-VAL-17 es una
elección metodológica del motor, no una prescripción de fuente.

## 3. Las decisiones que se proponen

### 3.1 Cierre de las tres deudas (D-VAL-13…D-VAL-15)

**D-VAL-13 · `FALTA-DATO-VAL-3` se cierra: el Jeffreys del motor es el del BCE.** El código deja
de existir: se retira de `evaluator.py` (constante y las dos emisiones), de los docstrings de
`calibration_tests.py` y `backtesting.py`, de `_DECLARED_WARNING_PROSE`, del catálogo
`avisos-declarados.md` y de los tests que lo afirman (§1.1). Ningún `ValidationCardSection`
volverá a llevarlo. SDD-22 §3.2 y §12 pasan de «pendiente de verificación por render» a la fila de
cotejo de §2 (F1 + F2), con fecha y verificador. El número **3 no se reutiliza** (la nota de
`config.py:606` ya fija esa regla para la familia `VAL`).

**D-VAL-14 · `FALTA-DATO-VAL-1` se cierra: el t-test del motor es el del BCE.** Misma retirada que
D-VAL-13 (`evaluator.py:110, 432`; `backtesting.py:30-33, 91`; prosa; catálogo; tests). D-VAL-7
queda **confirmada** tal como se propuso: pareado simple sobre `e_i = realizado − estimado`,
unilateral hacia la subestimación, Student con `N − 1` gl. `one_sided=False` se documenta como la
convención bilateral del ELBE (F1 §2.7.2.1), no como una desviación. El copy de
`backtesting.enabled` pierde la frase «La forma exacta de la prueba … está declarada como brecha
del motor: el resultado sale con ese aviso» (copy: Cami lo revisa contra la pantalla, precedente
§8-7 del scorecard completo). Sin ponderación por exposición: la fuente no la usa y ofrecerla
sería inventar una variante.

**D-VAL-15 · `FALTA-DATO-VAL-2` se retira sin sucesor; los cortes del semáforo son política
institucional publicada, como `alpha`.** No hay anclaje regulatorio que cotejar (§1.2), así que un
`FALTA-DATO` que promete una verificación imposible es un aviso que nunca podrá cerrarse: el motor
no tiene deuda ahí. Tampoco se propone un `DATO-INSTITUCIONAL` permanente: los cortes ya son dato
del config, viajan en la tabla tidy `calibration` (`alpha`, `traffic_light` por grado) y el
`ui_help` los declara institucionales; emitir un aviso cada vez que corre el contraste, incluso
cuando la institución fijó sus cortes, sería ruido sin acción posible (mismo trato que
`alpha=0,05` del HL y los umbrales PSI 0,10/0,25, que nunca llevaron marca). Lo que sí cambia, para
que nada quede sin superficie (D-VIS):

- la prosa del capítulo «Validación formal» dice, **sólo cuando corrió el contraste por grado**,
  con qué cortes se pintó el semáforo: «Un grado queda en verde con un p-valor de al menos X, en
  ámbar entre Y y X, y en rojo por debajo de Y; los cortes los fija la política de validación de la
  institución, no una norma.» (números formateados como el resto del capítulo; F1 no lo emite:
  contraste apagado, §1.4);
- la frase «siguen la convención de Basilea (1996)» desaparece de la prosa y del catálogo;
- el copy de `binomial_by_grade` pierde «Los cortes del semáforo y la convención exacta de la
  prueba están declarados como brecha del motor: el resultado sale con ese aviso» y gana una
  remisión a los dos cortes («los cortes del semáforo son los dos campos de abajo, fijados por tu
  política de validación»); el `ui_help` de `traffic_light_green_alpha` se conserva;
- la guía `validacion-formal.md` §3 reescribe el párrafo «Dos ajustes finos…»: los dos siguen
  siendo institucionales, pero ya no «salen del resultado con un aviso declarado»;
- SDD-22 D-VAL-5 pasa a «default institucional, sin marca; verificado que no existe corte
  regulatorio (F1, F3, F4)».

Alternativa medida y descartada: reclasificar a `DATO-INSTITUCIONAL-VAL-5` (§8-3, opción B).

**D-VAL-18 · Registro del cotejo y regla para los siguientes.** La tabla §2 se copia a SDD-22 §12
(sustituye el bloque «`FALTA-DATO` a resolver por verificación de render») y el registro canónico
gana una fila «D-VAL-13…18» con el estado. Todo cotejo futuro de una convención del motor que **no**
sea normativa local (las de CMF ya tienen manifiesto propio, D-COT/D-FTE) se registra con el mismo
formato mínimo —fuente, URL oficial, sha256, página/sección, método, verificador, fecha— en el SDD
del módulo; sin ese registro, la convención sigue marcada. No se crea un manifiesto en el paquete:
la card ya publica `dependency_versions` y el trail el `log_decision`; un manifiesto sería una
tercera superficie sin consumidor.

### 3.2 Recálculo del PSI (D-VAL-16)

**D-VAL-16 · El fallback de D-VAL-2 se cablea de verdad, reutilizando el ensamblador del paso de
estabilidad; `consume_stability` deja de estar oculto.**

1. `nikodym.stability.step` expone `assemble_stability_frame(study, config) ->
   (frame, feature_point_columns)`: envuelve, sin cambiar una línea de cálculo, lo que hoy hace
   `execute` antes de llamar al evaluador (`_csi_frame`, `_require_direccion_coherente`,
   `_data_frame_for_temporal_if_needed`, `_assemble_stability_frame`). `StabilityStep.execute` pasa
   a llamarla (un solo camino, sin duplicar la alineación).
2. `ValidationStep._requires_for` cambia para la familia `stability`: con `consume_stability=True`
   exige, como hoy, `stability.stability_metrics` y `psi_table`; con `False` exige
   `scorecard.score` y `calibration.calibrated_pd_frame` (los `requires` del paso de estabilidad;
   `data.frame` y `binning.bin_frame` siguen siendo opcionales y se leen si están). Es CT-1 tal
   como ya lo hace la discriminación (`consume_performance=False` exige el frame analítico).
3. `execute` construye el frame con el ensamblador cuando la familia está activa y
   `consume_stability=False`, con la `StabilityConfig` de `NikodymConfig.stability` o, si el config
   no la trae, `StabilityConfig()` (el mismo respaldo que usa el paso). Pasa el frame como
   `stability_frame` y los `evaluator_kwargs` que el evaluador de SDD-11 necesita (`psi_bins`,
   `comparisons`, `temporal_axis`, …) leídos de esa misma config, de modo que **el recálculo es el
   mismo cálculo**: la fila `source="recomputed"` tiene el mismo `value` que la fila
   `source="stability_artifact"` de una corrida con el paso (gate byte a byte en §6).
4. La semántica del toggle queda como D-VAL-2 la enunció: `True` = consumir el artefacto; `False`
   = recalcular por reúso. **No** se introduce «consumir si existe, si no recalcular» (un tercer
   estado implícito): quien apaga el consumo lo hace a propósito y el DAG lo declara.
5. `consume_stability` pasa a `ui_widget="checkbox"` con copy nuevo (borrador: «Reusar el PSI que
   ya calculó la etapa de estabilidad. Apagado, la validación lo recalcula con el mismo motor sobre
   el score y la PD calibrada; el resultado dice de dónde salió cada fila.»). Es la única superficie
   nueva del formulario: mueve el ledger de `option_surface`, `test_effective_defaults.py:87-89`,
   `test_jobs_abanico.py:207`, el fixture `schema.json` y el bundle; **no** mueve el `config_hash`
   de ningún preset (el valor sigue `true`).
6. El panel y la prosa ya distinguen `source`; la guía §4 deja de decir «No se recalcula; se
   documenta» y explica los dos caminos.

### 3.3 Mínimo por grupo de Hosmer-Lemeshow (D-VAL-17)

**D-VAL-17 · `min_rows_per_group` protege también cada grupo de Hosmer-Lemeshow: un grupo con
menos operaciones que el mínimo deja la prueba `not_evaluable` en esa partición.** Es la lectura
literal del título del campo y el mismo trato que el test por grado (`:376`): sin potencia no hay
veredicto. Detalle:

- `hosmer_lemeshow(y_true, pd_pred, *, n_groups, min_rows_per_group=1)` gana el parámetro con
  default inerte (1 = comportamiento actual); tras `np.array_split` (grupos de tamaño `⌊N/G⌋` o
  `⌈N/G⌉`), si `min(counts) < min_rows_per_group` devuelve `_hl_not_evaluable` (kernel puro, sin
  auditoría, como hoy).
- `_hosmer_lemeshow_record` pasa `self.min_rows` al kernel; conserva la puerta por partición
  (`N < min` sigue evitando el kernel).
- La razón se audita con `log_decision(regla="calibration_hl_group_not_evaluable", …)` con
  `partition`, `n`, `n_groups`, `min_group_size` y `min_rows`; el record tidy conserva su forma
  (`decision="not_evaluable"`, `p_value=None`). **No** se añade columna a `_CALIBRATION_COLUMNS`
  ni clave nueva a `metric_sections` (evita mover `results-f1.json`, §1.4). El panel sigue
  pintando «No evaluable» y la guía explica las dos causas (partición bajo mínimo; algún grupo bajo
  mínimo) y cómo destrabarlas (menos grupos o menos mínimo, los dos visibles en el formulario).
- Con los defaults (10 grupos, mínimo 30) una partición necesita ≥ 300 operaciones para recibir
  HL. Medido sobre la demo F1: 973 y 1.008 ya cumplen; las guías y el informe de la demo no cambian.
- Copy: el `ui_help` de `min_rows_per_group` pierde «No se aplica a cada grupo de PD dentro de la
  prueba de Hosmer-Lemeshow» y dice lo contrario; §0-21 del scorecard completo queda superado por
  esta decisión (se anota allí).

Alternativa medida y descartada: reducir `G` al mayor valor con grupos ≥ mínimo (§8-5, opción C).

## 4. Contratos de datos (I/O)

- `ValidationCardSection.falta_dato`: nunca contiene `FALTA-DATO-VAL-1/2/3`. Sigue pudiendo
  contener `DATO-INSTITUCIONAL-VAL-4: …` y `FALTA-DATO: provisioning_ifrs9.detail no contiene
  columnas estimadas …` (marca desnuda, `_backtesting_blocker`). Los consumidores no cambian:
  filtran por `is_declared_warning()`.
- Tablas tidy `discrimination` / `calibration` / `stability` / `backtesting`: **mismas columnas**.
  `stability.source` puede valer `"recomputed"` desde un `Study` (hoy sólo desde el kernel).
- `CalibrationTestRecord` de HL: `decision="not_evaluable"` también por grupo bajo mínimo
  (`statistic=0.0`, `p_value=None`, `alpha=None`), forma idéntica a la de la partición bajo mínimo.
- `ValidationStep.requires` (CT-1) para `stability` con `consume_stability=False`:
  `("scorecard","score")`, `("calibration","calibrated_pd_frame")`; `optional_requires` gana
  `("data","frame")` y `("binning","bin_frame")` sólo en esa rama.
- Trail: `calibration_hl_group_not_evaluable` (nueva regla) y `stability_psi` con
  `source="recomputed"` (regla existente). `validation_falta_dato` deja de emitirse por los tres
  códigos retirados.

## 5. Casos borde y errores

- **Backtesting con `lgd`/`ead` y sin las columnas realizadas**: sin cambio (`_backtesting_blocker`
  y `fail_on_falta_dato`, §0-17/§0-22 del scorecard completo).
- **`consume_stability=False` sin `scorecard.score` en el `Study`** (por ejemplo, PD por la puerta
  de artefactos): `_require_present` levanta el error de `requires` ausente con la clave exacta,
  como cualquier paso (CT-1); antes abortaba en el evaluador con un mensaje que hablaba de un frame
  que nadie podía dar.
- **`consume_stability=False` y `NikodymConfig.stability` ausente**: se recalcula con
  `StabilityConfig()`; el trail lo dice (`stability_psi`, `source="recomputed"`). Si `temporal_axis`
  del default exige una columna que el score no trae, el ensamblador lee `data.frame`; si tampoco
  está, el error es el del paso de estabilidad (mismo texto).
- **HL con `N ≥ min` pero `⌊N/G⌋ < min`**: `not_evaluable` por grupo (nuevo); con `min=1` (por
  código) el comportamiento es el actual.
- **HL con grupos desiguales** (`np.array_split`): la puerta mira el **menor** grupo.
- **Un preset con `binomial_by_grade=True` y cortes explícitos**: prosa con los cortes; sin marca.
- **Un YAML viejo con `consume_stability: false`**: hoy aborta; con D-VAL-16 corre y recalcula.
  No es ruptura: convierte un error en un resultado declarado.

## 6. Orden de capas, gates y controles negativos preespecificados

Una capa por cierre, en este orden; cada una cierra entera (suite completa sola sobre el árbol
congelado, revisión adversarial hasta `approve`, commit y push propios) antes de la siguiente.

**Capa A — cierre de VAL-1/2/3 (D-VAL-13/14/15/18).** Motor (constantes, emisiones, docstrings),
`prose.py` (tres frases fuera; frase de los cortes dentro, condicionada), catálogo, copy de dos
campos, guía, SDD-22 §3/§12, CHANGELOG. Tests: invertir las afirmaciones de
`test_validation_evaluator.py` (`falta_dato == ()` en los cuatro escenarios; el binomial sigue sin
marca), `test_report_codigos_internos.py:48` sin la tupla `validation`, `test_core_markers.py:33`,
`test_validation_results.py:277/577` (fixture), `test_copy_del_formulario.py:222-252` (el ejemplo
usa otro código real), `ResultsTab.test.ts:577` (fixture con `DATO-INSTITUCIONAL-VAL-4`), gates del
catálogo (`test_public_copy.py`) y `test_report_prose` para la frase de los cortes (**test nacido
rojo**: con el contraste corrido, el capítulo nombra los dos cortes; sin contraste, no). Regenerar
`schema.json` y el bundle. **Controles negativos:** (1) reponer `marks.append("FALTA-DATO-VAL-3")`
en `_calibration_falta_dato` → rojo en el test de la card y en `test_public_copy` («la página no
documenta…»); (2) dejar la fila `VAL-2` en el catálogo → rojo «la página inventa códigos»; (3)
emitir la frase de los cortes sin contraste → rojo en el test de prosa. Los tres se revierten por
copia exacta (RUNBOOK §6).

**Capa B — HL por grupo (D-VAL-17).** Kernel + evaluador + trail + copy + guía. **Tests nacidos
rojos:** `hosmer_lemeshow(…, n_groups=10, min_rows_per_group=30)` sobre 100 filas →
`not_evaluable`; sobre 300 → mismo record que sin mínimo; evaluador con partición de 100 y
`min_rows_per_group=30` → HL `not_evaluable`, `n_tests` lo excluye, `log_decision` con la regla
nueva; el F1 de `tests/unit/_ui_f1.py` a `done` con los mismos tres HL que hoy. Ajustar los
fixtures de `test_validation_evaluator.py` (mínimo 6 o `hl_n_groups=3` en `_config()`, con la razón
escrita). **Control negativo:** quitar la comparación con `min(counts)` → rojos los dos primeros.
**Gate de goldens:** `results-f1.json`, `report-f1.html` y `GOLDEN_STEP_HTML_SHA256` intactos
(medido en §1.4; se vuelve a medir con `diff`).

**Capa C — recálculo del PSI (D-VAL-16).** `stability/step.py` (ensamblador público, `execute` lo
usa), `validation/step.py` (`requires` dinámicos, frame), `config.py` (`checkbox` + copy),
`schema.json` + bundle + ledger de `option_surface` + los censos de `test_effective_defaults` y
`test_jobs_abanico`, guía §4. **Tests nacidos rojos:** (1) `Study` con `scorecard` +
`calibration` + `validation(families=("stability",), consume_stability=False)` y **sin** paso
`stability` → `done`, filas con `source="recomputed"`; (2) la misma corrida **con** el paso →
`value` idéntico fila a fila entre `recomputed` y `stability_artifact` (`np.array_equal`, no
`approx`: es el mismo motor sobre el mismo frame); (3) `requires` de `ValidationStep` con el toggle
apagado nombra `scorecard.score` y no `stability.stability_metrics`; (4) sin `scorecard.score` →
error de `requires` ausente con la clave exacta. **Controles negativos:** dejar `stability_frame`
sin pasar → (1) rojo con el `ValidationDataError` de hoy; devolver los `requires` viejos → (3)
rojo. Verificar el artefacto final: corrida por la interfaz con el toggle apagado, panel
«Validación formal» con la sección de estabilidad y el informe con su tabla.

**Release.** Las tres capas caben en una release **minor** (1.16.0) con OK propio de Cami; sin
recaptura (§1.4). Si una capa se aprueba y otra no, cada una es publicable sola.

## 7. Lo que esta enmienda NO hace

- No cambia ninguna fórmula: Jeffreys, binomial, t-test, HL, Brier y PSI quedan como están (lo
  que cambia es qué se **dice** de ellas y cuándo HL se abstiene).
- No añade la fila de portafolio del Jeffreys ni los doce segmentos LGD/CCF del BCE (§1.2, última
  fila): serían capacidades nuevas con tablas nuevas; si Cami las quiere, exigen su enmienda.
- No ofrece un t-test ponderado por exposición ni un semáforo «Basilea 1996» sobre PD: la fuente
  no usa lo primero y lo segundo es un error de categoría (SDD-22 §12).
- No toca `alpha`, los umbrales PSI, `hl_n_groups`, `hl_grouping` (sigue oculto, D-SUB) ni
  `DATO-INSTITUCIONAL-VAL-4`.
- No mete `validation` en «Validar un modelo existente» (D-SC-7 mide por qué no).
- No recaptura la demo, no mueve hashes, no publica.

## 8. Lo que Cami decide

1. **`FALTA-DATO-VAL-3` (Jeffreys).** (A) **Cerrarla y retirar el código** —motor, prosa,
   catálogo, copy, tests—, con el cotejo registrado en SDD-22 §12 (D-VAL-13). (B) Conservar el
   aviso «por si el BCE cambia la convención»: no es una brecha y ningún cotejo futuro la cerraría.
   **Recomendación: A.**
2. **`FALTA-DATO-VAL-1` (t-test).** (A) **Cerrarla y retirar el código**; `one_sided` se documenta
   como ELBE (D-VAL-14). (B) Cerrarla y además añadir una variante ponderada por exposición: la
   fuente no la usa. **Recomendación: A.**
3. **`FALTA-DATO-VAL-2` (semáforo).** (A) **Retirarla sin sucesor**: los cortes son política
   institucional publicada en config, tabla y prosa, como `alpha` (D-VAL-15). (B) Reclasificarla a
   `DATO-INSTITUCIONAL-VAL-5`, emitida cada vez que corre el contraste por grado: honesta con la
   doctrina «el motor no inventa datos institucionales», pero es un aviso sin acción posible cuando
   la institución ya fijó sus cortes, y trata distinto a `alpha` y a los umbrales PSI sin razón
   medida. (C) Dejarla: contradice el cotejo (no hay nada que verificar) y mantiene una frase
   falsa. **Recomendación: A.**
4. **El copy que cambia** —`binomial_by_grade`, `backtesting.enabled`, `consume_stability`,
   `min_rows_per_group` (`ui_help`), la frase nueva de los cortes en el informe y dos párrafos de
   la guía— ¿lo revisa Cami contra la pantalla al implementar cada capa, como en el scorecard
   completo (§8-7)? **Recomendación: sí**, borradores en §3; cambiar un texto es copy.
5. **Mínimo por grupo de Hosmer-Lemeshow.** (A) **Puerta por grupo** → `not_evaluable` con la
   razón en el trail y en la guía (D-VAL-17). (B) Dejarlo como está y que el copy siga diciendo que
   no protege el grupo (§0-21): coherente pero desigual con el test por grado. (C) Reducir `G` al
   mayor valor con grupos ≥ mínimo (mínimo 3) y publicar el `n_groups` efectivo: da veredicto a
   más particiones, pero decide por el usuario un parámetro que él fijó y cambia el estadístico
   frente a lo pedido. **Recomendación: A.**
6. **Recálculo del PSI.** (A) **Cablearlo de verdad** con el ensamblador reutilizado, `requires`
   dinámicos y el toggle expuesto (D-VAL-16); ~una sesión, cinco censos y una sección del
   formulario sin campos nuevos. (B) No cablearlo: `consume_stability=False` pasa a error de
   validación del config («el recálculo no está cableado»), fail-fast en vez de abortar a mitad
   de corrida, y el campo sigue oculto como `hl_grouping`. Barato y honesto, pero D-VAL-2 sigue sin
   cumplirse y `stability_recomputed` sigue siendo código sin camino. (C) Retirar el campo:
   ruptura de una superficie experimental sin ganar nada. **Recomendación: A**; si Cami prefiere
   no gastar la sesión, **B** deja la deuda declarada y no escondida.
7. **Orden y release.** (A) **A → B → C, cada capa entera, y una sola release minor 1.16.0 con
   su OK**. (B) Sólo A ahora (cierre documental y de superficie), B y C después. **Recomendación:
   A**; B es aceptable si el tiempo manda.
8. **Registro del cotejo.** (A) **Tabla §2 en SDD-22 §12 y fila en `DECISIONES-VIGENTES.md`**
   (D-VAL-18), sin manifiesto en el paquete. (B) Un manifiesto versionado en `nikodym.validation`
   al estilo del de CMF: una tercera superficie sin consumidor hoy. **Recomendación: A.**
