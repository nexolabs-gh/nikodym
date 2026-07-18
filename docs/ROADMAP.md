# Estado y roadmap de evolución — Nikodym RiskLib

| | |
|---|---|
| **Documento** | Estado por capacidad y plan de evolución |
| **Versión** | 1.1 |
| **Fecha** | 2026-07-18 |
| **Base** | [`ESPECIFICACIONES.md`](ESPECIFICACIONES.md) v1.1 · [`design/00-INDICE.md`](design/00-INDICE.md) |

Nikodym `1.3.0` está publicado y el repositorio se encuentra en mejora continua. Las fases F0–F8
que siguen conservan el diseño y los DoD históricos; **no son una cola automática**. El estado y el
plan de esta sección son la fuente vigente.

## Estado actual

| Capacidad | Estado | Límite vigente |
|---|---|---|
| F0/F1 · núcleo y scorecard de comportamiento | **Estable** | Garantía SemVer 1.x para el pipeline F1 |
| F2 · ML/tuning/explain | Implementado, **experimental** | No sustituye la scorecard ni amplía SemVer F1 |
| F3/F8 · CMF, método interno y orquestación | Implementado, **experimental** | Validación humana de matrices/haircuts pendiente |
| F4 · IFRS 9/ECL | Implementado, **experimental** | Independiente del máximo B-1 chileno |
| F5/F6 · forward, survival, Markov, stress y validación | Implementado, **experimental** | Uso por config Python; sin preset/UI propios |
| F7 · UI React/FastAPI e informe | Disponible | Demo estática F1/F3/F4; ejecución local para datos propios |
| Originación/reject inference | Futuro | Requiere caso de uso, priorización y SDD |

## Plan operativo vigente

### P0 — Cierre pre-Interbank

1. Recuperar **al menos 12 GiB libres** y completar el preflight reproducible de la campaña. El
   corte de esta consolidación quedó bajo ese umbral; no iniciar una ejecución larga con el disco
   en presión.
2. Resolver o caracterizar con tests seis brechas de contrato `forward`→IFRS 9 detectadas en la
   revisión: `rho_col` no consumida; `Z` implícito inexistente; falta de guard PIT/TTC antes de
   Vasicek; `forbid_mean_scenario` sólo auditado; pesos cero incompatibles; LGD forward ignorada.
   Cada corrección requiere actualizar SDD, tests y contrato público experimental en el mismo bloque.
3. Ejecutar una campaña adversarial autónoma y finita de **14 horas** sobre la demo F1/F3/F4: tarjeta, preset,
   dataset, resultados, lineage e informes HTML/PDF/Word/ZIP.
4. Reproducir específicamente el riesgo de resultados obsoletos al cambiar de preset. Corregir sólo
   defectos **P0/P1 verificables**; no recapturar ni redesplegar por cosmética P2.
5. Ejecutar gates completos, revisión independiente y verificar el activo desplegado contra el SHA
   aprobado.
6. Congelar código, fixtures, informes y deploy a más tardar el **2026-07-21** para la reunión
   Interbank del **2026-07-22**. No crear tag ni publicar PyPI en esta campaña.

En paralelo permanece un gate humano separado: validar las matrices CMF celda a celda y resolver los
haircuts remitidos a normativa complementaria. Hasta entonces no existe certificación normativa.

### P1 — Primer bloque posterior a Interbank

Producir y aprobar un único SDD: **Workspace de evidencia de corridas v1**. La primera rebanada
vertical debe extender la corrida local existente, sin duplicar un motor MLOps:

1. `SourceSnapshot`: identidad inmutable de fuente/as-of, esquema, conteos y hash lógico; inicialmente
   sólo archivos, datasets sintéticos y uploads ya soportados.
2. `ExecutionLedger`: transiciones y eventos append-only por `Step` en la capa fina runner/API, no en
   `core`.
3. Workspace: listar, reabrir, clonar y comparar corridas compatibles usando manifiestos y resultados
   existentes.

El SDD debe fijar migración de corridas actuales, escrituras atómicas, idempotencia, concurrencia,
crash recovery, codecs JSON/Parquet, exclusión de secretos y reglas de compatibilidad. Estados
asíncronos, cancelación cooperativa y reanudación se implementan sólo cuando el runner pueda cumplirlos
de forma durable; nunca se simulan sobre HTTP.

### P2 — Cola candidata, no autorizada

Después del SDD anterior, volver a priorizar con feedback comercial y evidencia: `SplitPolicy`,
`ScenarioContract`, `ValidationLedger`, `SatelliteModel v2`, `PortfolioStress` y
`PortfolioForecast`. Ninguno se inicia por mera presencia en esta lista.

## Qué no hacer

- No inventar un bloque IBK-06 ni ampliar funcionalidades antes de la reunión.
- No copiar DataHub, SQL, defaults ni metodología institucional; sólo reimplementar patrones genéricos.
- No construir conectores remotos antes de fijar `SourceSnapshot`.
- No mezclar `ExecutionLedger` operacional con `ValidationLedger` humano.
- No presentar CMF/IFRS 9/forward/stress como certificados por estar implementados.

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
| **F4** | IFRS 9 / ECL | ECL independiente | XL | Pérdida esperada bajo IFRS 9 |
| **F5** | Forward-looking | Lifetime + escenarios | XL | Term-structure, macro, Markov |
| **F6** | Validación avanzada | Backtesting | L | Validación formal + backtesting |
| **F7** | UI visual | **App React premium** | L | Web premium sobre la API (local + demo) |
| **F+** | Originación | Reject inference | M | Scorecard de admisión |

Esfuerzo relativo: S < M < L < XL.

---

## F0 — Fundaciones & gobierno
**Objetivo.** El núcleo del que todo cuelga, auditable desde el primer commit.
**SDDs.** 01 core · 02 data · 03 audit+governance · 04 tracking · 05 convenciones+config · 24 testing · 25 packaging/CI. *(El reporte se separó a **SDD-26 `report`** en T2/F1; ver índice.)*
**Entregables.**
- Repo Apache-2.0, `src/` layout, `pyproject.toml` (uv + hatchling, extras declarados).
- `core`: objeto `Study`, config Pydantic v2 (round-trip YAML), registry, orquestación.
- `data`: validación de esquema, definición de target, particiones (Dev/HO/OOT/TTD), missing/special.
- `audit` + `governance`: semilla global, lineage bundle, model card, inventario.
- `tracking` (MLflow local). *(El informe determinístico + capa IA opcional es **SDD-26**, producido en T2/F1, no en F0.)*
- CI (ruff, mypy, pytest), pre-commit, plantillas de issues/PR.
**DoD.** CI verde; un `Study` vacío se crea, serializa y recarga; una corrida trivial emite lineage + model card reproducibles; cobertura base.
**Dependencias.** Ninguna.

## F1 — Scorecard de comportamiento (MVP open-source)
**Objetivo.** Pipeline de scorecard completo, sin reject inference. **Es el activo de marketing.**
**SDDs.** 27 eda · 06 binning · 07 selection · 08 model · 09 scorecard · 10 calibration · 11 performance+stability · 26 report.
**Entregables.**
- EDA de riesgo (SDD-27): tasa de default por período/cohorte, estabilidad temporal (señal de redesarrollo), perfiles univariados.
- Binning OptBinning monótono (WoE), ajuste en Dev → transform al resto.
- Selección: PSI/CSI, IV, ROC/KS/Gini por muestra y período; correlación; descarte por negocio.
- Stepwise (Wald/LR, statsmodels), regla de signos, IV-contribution ≤ 90%.
- Scorecard (offset/PDO, puntos por atributo); calibración de PD.
- Tabla de rendimiento (deciles) + estabilidad del score.
- **Informe HTML/PDF/Word** de la scorecard, con fuente Markdown/Quarto opcional.
**DoD.** Dataset de ejemplo → scorecard reproducible + reporte; tests numéricos de WoE/IV/PSI/escalado contra valores a mano; **release público inicial** en PyPI + GitHub con README, tutorial y ejemplo ejecutable. **Cumplido.**
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

> 🔴 **DoD INCUMPLIDO: la validación humana de las matrices SIGUE PENDIENTE.** Los parámetros se transcribieron del compendio **con asistencia de IA y verificación visual**; no son oficiales de la CMF ni están validados por ella (así está confesado en el README y en la landing). **Un gerente de riesgo pregunta por su procedencia en los primeros cinco minutos.** Para cartera de consumo se usa **una sola** matriz (`consumer_standard_v2025`): validarla a mano, celda por celda, es el trabajo de mayor retorno del track — y **no lo puede hacer un agente**.

## F4 — IFRS 9 / ECL
**Objetivo.** ECL de 3 etapas como motor independiente; la orquestación configurable vive en una
capa separada y sólo representa la regla B-1 al comparar estándar CMF con método interno.
**SDDs.** 16 provisioning-ifrs9 · 17 provisioning-orchestration.
**Entregables.**
- PD (12m/lifetime, PIT/TTC Vasicek), LGD (beta/fractional/workout), EAD/CCF.
- Staging (SICR, Stage 1/2/3, backstops 30/90 dpd, umbrales parametrizables).
- Motor ECL con descuento a EIR, multi-escenario ponderado.
- Orquestación: `provisioning` compara **dos fuentes configurables** y aplica la regla declarada.
**DoD.** ECL reproducible sobre dataset de ejemplo; term-structure conectada (interfaz a F5); tests de fórmula (Vasicek, ECL marginal) contra valores canónicos.
**Dependencias.** F4↔F5 (lifetime usa survival/markov; se especifica con interfaz abstracta y se conecta al cerrar F5).

> ⚠️ **CORRECCIÓN NORMATIVA (2026-07-14).** Este roadmap decía *"capa que toma el máximo vs piso CMF"* y *"`provisioning` compara CMF vs IFRS 9 y aplica el máximo"*. **Ese encuadre era falso.** El Cap. A-2 del Compendio **excluye** el deterioro de NIIF 9 sobre las colocaciones, y la regla del máximo del Cap. B-1 (Circular N° 2.346) es entre el **método estándar y el método interno del banco**, por institución. Ver `ESPECIFICACIONES.md` §5.4 y el SDD-17 §3.
>
> **Para el mercado chileno, el ECL de IFRS 9 no es el operando del máximo.** F4 sigue siendo válido para quien sí aplica NIIF 9 completa (filiales que reportan a matriz extranjera, entidades no bancarias, instrumentos distintos de colocaciones).

## F8 — El método interno y la ruta hasta el usuario (post-1.0)
**Objetivo.** Que un gerente de riesgo pueda **ver** la provisión que la norma le obliga a constituir.
**SDD.** 28 provisiones-end-to-end.
**Entregables.**
- ✅ `provisioning/internal`: el **método interno** del B-1 (`Exposición · PD · LGD` por grupo homogéneo). La PD sale del scorecard → **el modelo del banco entra en la provisión reportada**.
- ✅ Orquestador con fuentes configurables + `rule="use_internal"`.
- ✅ Dataset `provisiones_consumo` y capítulos condicionales del informe.
- ✅ **La ruta hasta el usuario**: preset, serializer, pantalla y capítulo del informe F3, integrada y
  recapturada en la demo multi-dominio.
**DoD.** La cadena corre de punta a punta desde la UI y el informe trae la cifra; validación **humana** de la matriz de consumo contra el compendio (gate G0).

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
**DoD.** Suite de validación ejecutable sobre cualquier modelo del repo; informes HTML/PDF/Word de validación.
**Dependencias.** F1–F5.

## F7 — UI visual
> **Rumbo actualizado (2026-07-04): UI = app React/Vite premium, NO Streamlit.** El contrato de
> `design/23-ui.md` se implementó sobre React/FastAPI; sus referencias históricas a Streamlit no
> describen el producto actual.

**Objetivo.** Web premium sobre la API que construye y visualiza el `Study` (editor del config Pydantic), para dos públicos: analistas técnicos (MVP/benchmark rápido) y gerentes de riesgo no-técnicos (demo de venta).
**SDDs.** 23 ui *(contrato evolucionado e implementado sobre React/FastAPI)*.
**Stack.** React + Vite + Tailwind + shadcn/ui + charts premium; backend **FastAPI**; **cero lógica propia** (todo invoca la API de la lib).
**Dos modos de despliegue.**
- **Local (analista):** `pip install nikodym[ui]` trae el React ya buildeado + levanta FastAPI local; los datos no salen de su máquina.
- **Hosteada (comercial):** `nikodym.cl/demo`, dataset **sintético** precargado, flujo guiado "arma tu modelito en pocos pasos" + CTA de lead comercial.
**DoD.** Un modelo F1 completo construible 100% desde la UI, idéntico al hecho por código; look&feel premium aprobado por revisión visual.
**Dependencias.** Todo el core (motor V1 ✅ completo 2026-07-04).

## F+ — Originación & reject inference (insertable)
**Objetivo.** Scorecard de admisión cuando haya caso de uso.
**Entregables.** Muestra TTD (through-the-door), reject inference (parcelling/fuzzy/reweighting) validado por outcomes.
**Cuándo.** Insertable tras F1, cuando un cliente lo requiera.

---

## Estrategia de release (open-source)
- `1.3.0` es el release vigente; el pipeline F1 conserva la garantía SemVer 1.x.
- Releases incrementales con changelog, docs MkDocs, dataset/tutorial reproducible y smoke clean-room.
- Cada tag y publicación PyPI requiere OK específico de Cami; push/deploy ordinarios no sustituyen ese gate.

## Puentes de sesión
- Entre tandas/fases: `cierre-trabajo` → `HANDOFF.md` → `inicio-trabajo` en sesión fresca.
- El HANDOFF resume estado, decisiones y siguiente paso. Warm start desde el HANDOFF, no re-explorar todo.
