# Roadmap de construcción — Nikodym RiskLib

| | |
|---|---|
| **Documento** | Roadmap completo de construcción |
| **Versión** | 1.0 |
| **Fecha** | 2026-06-23 |
| **Base** | [`ESPECIFICACIONES.md`](ESPECIFICACIONES.md) v1.0 · [`design/00-INDICE.md`](design/00-INDICE.md) |

## Principios de secuencia
1. **Cada fase entrega valor por sí sola.** No se avanza sin DoD + tests + docs de la anterior.
2. **Fundación primero, auditabilidad desde el día 0.** Sin `core`/`audit`/`governance` nada es reproducible ni defendible.
3. **Lo que produce PD va antes de lo que la consume.** Scoring (F1) es cimiento de CMF, IFRS 9 y lifetime.
4. **Open-source como escaparate** → calidad ejemplar es requisito de cada fase, no un extra.
5. **Dos disciplinas de proceso:** un SDD aprobado antes de codear cada módulo; `HANDOFF.md` como puente entre sesiones.
6. **Doble verificación de toda información externa.** Cada dato/tabla/parámetro de internet o normativa se valida contra la fuente oficial por una segunda vía (ideal: render visual del original). Usado por instituciones financieras → un número errado es riesgo regulatorio. Nada avanza sin doble check trazado.
7. **Verificación antes de ampliar (Tanda 0).** Antes de producir nuevos documentos, se re-verifica que lo ya hecho esté correcto. Ver la Tanda 0 en [`design/00-INDICE.md`](design/00-INDICE.md).

## Mapa de fases

| Fase | Nombre | Entrega clave | Esfuerzo | "¿Qué se puede mostrar?" |
|---|---|---|---|---|
| **F0** | Fundaciones & gobierno | Esqueleto auditable | M | Repo serio, CI verde, lineage |
| **F1** | Scorecard comportamiento | **MVP open-source** | L | Scorecard end-to-end + reporte |
| **F2** | Machine Learning | Benchmark + SHAP | M | CatBoost vs logística, explicado |
| **F3** | Provisiones CMF | Motor B-1 | M | Provisión regulatoria chilena |
| **F4** | IFRS 9 / ECL | ECL + piso CMF | XL | Pérdida esperada multi-norma |
| **F5** | Forward-looking | Lifetime + escenarios | XL | Term-structure, macro, Markov |
| **F6** | Validación avanzada | Backtesting | L | Validación formal + backtesting |
| **F7** | UI visual | Producto no-code | L | Drag-and-drop sobre la API |
| **F+** | Originación | Reject inference | M | Scorecard de admisión |

Esfuerzo relativo: S < M < L < XL.

---

## F0 — Fundaciones & gobierno
**Objetivo.** El núcleo del que todo cuelga, auditable desde el primer commit.
**SDDs.** 01 core · 02 data · 03 audit+governance · 04 tracking+report · 05 convenciones+config · 24 testing · 25 packaging/CI.
**Entregables.**
- Repo Apache-2.0, `src/` layout, `pyproject.toml` (uv + hatchling, extras declarados).
- `core`: objeto `Study`, config Pydantic v2 (round-trip YAML), registry, orquestación.
- `data`: validación de esquema, definición de target, particiones (Dev/HO/OOT/TTD), missing/special.
- `audit` + `governance`: semilla global, lineage bundle, model card, inventario.
- `tracking` (MLflow local) + `report` (esqueleto Quarto + capa IA opcional).
- CI (ruff, mypy, pytest), pre-commit, plantillas de issues/PR.
**DoD.** CI verde; un `Study` vacío se crea, serializa y recarga; una corrida trivial emite lineage + model card reproducibles; cobertura base.
**Dependencias.** Ninguna.

## F1 — Scorecard de comportamiento (MVP open-source)
**Objetivo.** Pipeline de scorecard completo, sin reject inference. **Es el activo de marketing.**
**SDDs.** 06 binning · 07 selection · 08 model · 09 scorecard · 10 calibration · 11 performance+stability.
**Entregables.**
- Binning OptBinning monótono (WoE), ajuste en Dev → transform al resto.
- Selección: PSI/CSI, IV, ROC/KS/Gini por muestra y período; correlación; descarte por negocio.
- Stepwise (Wald/LR, statsmodels), regla de signos, IV-contribution ≤ 90%.
- Scorecard (offset/PDO, puntos por atributo); calibración de PD.
- Tabla de rendimiento (deciles) + estabilidad del score.
- **Reporte Quarto HTML+PDF** de la scorecard.
**DoD.** Dataset de ejemplo → scorecard reproducible + reporte; tests numéricos de WoE/IV/PSI/escalado contra valores a mano; **release público v0.1.0** en PyPI + GitHub con README, tutorial y ejemplo ejecutable.
**Dependencias.** F0.

## F2 — Machine Learning
**Objetivo.** Modelos ML como benchmark de poder predictivo, con explicabilidad.
**SDDs.** 12 ml-models · 13 tuning · 14 explain.
**Entregables.**
- Wrappers SVM, RandomForest, XGBoost, LightGBM, **CatBoost** (extras opcionales), con monotonic constraints donde aplique.
- Optuna (samplers seedeados, search spaces editables).
- SHAP + reason codes; comparativa scorecard vs ML en el reporte.
**DoD.** Mismo pipeline de datos que F1; tuning reproducible (seed); SHAP integrado al reporte; tests de determinismo.
**Dependencias.** F1 (pipeline, binning, model).

## F3 — Provisiones CMF (norma local)
**Objetivo.** Motor de pérdida esperada estandarizada `PE = PI·PDI·Exposición` del Capítulo B-1.
**SDDs.** 15 provisioning-cmf.
**Entregables.**
- Matrices por cartera (comercial individual A1–C6, grupal, consumo 2025, vivienda PVG) como **datos versionados** ([`normativa_cmf_parametros.md`](normativa_cmf_parametros.md)).
- Contingentes B-3 (CCF + override 100% en incumplimiento); sustitución por avales; garantías → PDI.
**DoD.** Cálculo de provisión por cartera reproducible contra casos de ejemplo; **validación humana de las matrices** registrada en governance; tests por cada matriz.
**Dependencias.** F1 (segmentación/PD de entrada). **Riesgo:** los parámetros cambian con la norma → versionar.

## F4 — IFRS 9 / ECL
**Objetivo.** ECL de 3 etapas + capa que toma el **máximo** vs piso CMF.
**SDDs.** 16 provisioning-ifrs9 · 17 provisioning-orchestration.
**Entregables.**
- PD (12m/lifetime, PIT/TTC Vasicek), LGD (beta/fractional/workout), EAD/CCF.
- Staging (SICR, Stage 1/2/3, backstops 30/90 dpd, umbrales parametrizables).
- Motor ECL con descuento a EIR, multi-escenario ponderado.
- Orquestación: `provisioning` compara CMF vs IFRS 9 y aplica el máximo.
**DoD.** ECL reproducible sobre dataset de ejemplo; term-structure conectada (interfaz a F5); tests de fórmula (Vasicek, ECL marginal) contra valores canónicos.
**Dependencias.** F4↔F5 (lifetime usa survival/markov; se especifica con interfaz abstracta y se conecta al cerrar F5).

## F5 — Forward-looking & dinámica
**Objetivo.** Lifetime PD, proyección macro y escenarios.
**SDDs.** 18 survival · 19 markov · 20 forward-macro · 21 stress.
**Entregables.**
- Survival (KM, Cox, AFT, discrete-time hazard) → lifetime PD; reusa stack de regresión.
- Markov (cohort/duration/generador, embedding) → term structure.
- Macro ARIMA/VAR + satellite models (Wilson logit) + escenarios ponderados (≥3).
- Stress testing (escenarios severos, sensibilidad).
**DoD.** Curvas lifetime PD reproducibles por ambas rutas (survival y matriz); consistencia PIT en la cadena; tests numéricos.
**Dependencias.** F1 (regresión). Cierra el lifetime de F4.

## F6 — Validación avanzada
**Objetivo.** Validación formal y backtesting integrados. (El módulo `stress/` se construye en F5; aquí se valida y se hace backtesting.)
**SDDs.** 22 validation.
**Entregables.** Discriminación (ROC/AUC, Gini, KS), calibración (Hosmer-Lemeshow, binomial, traffic-light, Brier), estabilidad (PSI), backtesting realizado-vs-estimado (t-test ECB).
**DoD.** Suite de validación ejecutable sobre cualquier modelo del repo; reportes Quarto de validación.
**Dependencias.** F1–F5.

## F7 — UI visual
**Objetivo.** Interfaz drag-and-drop sobre la API (editor del config Pydantic).
**SDDs.** 23 ui.
**Entregables.** App Streamlit que construye el `Study` editando el config; visor de resultados y reportes; **cero lógica propia** (todo invoca la API).
**DoD.** Un modelo F1 completo construible 100% desde la UI, idéntico al hecho por código.
**Dependencias.** Todo el core.

## F+ — Originación & reject inference (insertable)
**Objetivo.** Scorecard de admisión cuando haya caso de uso.
**Entregables.** Muestra TTD (through-the-door), reject inference (parcelling/fuzzy/reweighting) validado por outcomes.
**Cuándo.** Insertable tras F1, cuando un cliente lo requiera.

---

## Estrategia de release (open-source)
- **v0.1.0** al cerrar F1 (scorecard) — primer escaparate público.
- Releases incrementales por fase (semver), changelog, docs Quarto/mkdocs.
- Cada release: tutorial + dataset de ejemplo + notebook reproducible (es marketing de la consultora).

## Puentes de sesión
- Entre tandas/fases: `cierre-trabajo` → `HANDOFF.md` → `inicio-trabajo` en sesión fresca.
- El HANDOFF resume estado, decisiones y siguiente paso. Warm start desde el HANDOFF, no re-explorar todo.
