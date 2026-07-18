# Nikodym RiskLib — Especificaciones del Proyecto

| | |
|---|---|
| **Documento** | Especificación maestra |
| **Versión** | 1.1 (producto publicado) |
| **Fecha** | 2026-07-18 |
| **Marca / nombre completo** | Nikodym RiskLib |
| **Paquete Python** | `nikodym` (`pip install nikodym`, `import nikodym`) |
| **Licencia** | **Apache-2.0** (open-source) |
| **Estado** | Nikodym `1.3.0` publicado; pipeline F1 estable y dominios CMF/IFRS 9/forward/stress experimentales. Parámetros CMF con validación humana pendiente pre-producción. |

> El nombre **Nikodym** viene de la derivada de **Radon–Nikodym** (cambio de medida), el corazón matemático del riesgo cuantitativo. Es marca compartida con la consultora **Nikodym**.

---

## 1. Visión, propósito y modelo de negocio

Construir una librería Python **integral, auditable y reproducible** para el modelamiento de **riesgo de crédito** en todas sus facetas, utilizable por cualquier área de banca, financiera, fintech o cooperativa que necesite:
- desarrollar modelos de **scoring / scorecards**,
- calcular **provisiones bajo norma local CMF** (Chile),
- calcular **pérdida esperada bajo IFRS 9**,
- y ejecutar **forward-looking y stress testing**.

La meta: que **sea tonto no usar Nikodym RiskLib porque lo tiene todo, bien hecho y auditable**.

**Modelo de negocio (define prioridades de calidad):** la librería es **open-source (Apache-2.0)**. La ganancia no es licenciamiento, sino **reputación y visibilidad para la consultora Nikodym**: una librería de referencia en riesgo de crédito posiciona a sus creadores como autoridad técnica → los bancos y financieras que la adoptan contratan a Nikodym para consultoría, implementación y validación.
- **Consecuencia de diseño:** el código, los tests, la documentación y los ejemplos son **la carta de presentación comercial**, no un detalle interno. Calidad impecable = argumento de venta. Esto eleva el estándar de ingeniería de "bueno" a "ejemplar".

**Principio rector:** todo lo que la librería calcula debe poder **justificarse y replicarse bit a bit**. La IA documenta; **nunca calcula**.

---

## 2. Usuarios objetivo

- **Modeladores / científicos de riesgo** de bancos, financieras, fintech, cooperativas, retail financiero.
- **Equipos de riesgo / provisiones** que reportan a la **CMF** (Chile) y/o bajo **IFRS 9**.
- **Validadores y auditores** (consumidores de la trazabilidad y documentación automática).
- **Analistas no-programadores** vía la interfaz visual React/FastAPI.
- **La propia consultora Nikodym** como usuaria intensiva en sus engagements.

---

## 3. Alcance

### 3.1 En alcance
- **Scoring / scorecards** clásicos (regresión logística + WoE) — Fase 1 validada en **comportamiento**.
- **Modelos ML** de clasificación: SVM, Random Forest, XGBoost, LightGBM, **CatBoost**, con SHAP y monotonía.
- **Provisiones CMF (norma local)**: motor de **pérdida esperada estandarizada** `PE = PI · PDI · Exposición` (Cap. B-1 CNC), por cartera.
- **IFRS 9 / ECL**: PD (12m y lifetime), LGD, EAD/CCF, staging (SICR, Stage 1/2/3), motor ECL.
- **Forward-looking**: proyección macro (ARIMA/VAR), escenarios ponderados, satellite models.
- **Dinámica multi-período**: matrices de transición de Markov, survival (lifetime PD).
- **Stress testing**: escenarios severos, sensibilidad, impacto en provisiones/ECL.
- **Validación, estabilidad y monitoreo**: PSI/CSI, IV, ROC/KS/Gini, calibración, backtesting.
- **Auditabilidad/reproducibilidad** y **gobernanza (SR 11-7)** como capa transversal.
- **Documentación automática** HTML/PDF/Word, fuente editable Markdown/Quarto opcional, narrativa IA
  opcional y **tracking** (MLflow).

### 3.2 Fuera de alcance (por ahora)
- Riesgo de mercado, liquidez u operacional.
- Capital regulatorio Basilea (RWA) como producto formal (derivable después; ver RAN 21-6).
- Serving online de alta concurrencia (se entregan modelos serializados; el despliegue es del cliente).
- ETL de origen (consume datasets ya consolidados).
- **Originación + reject inference**: diferido a sub-fase posterior (ver §11).

### 3.3 Decisiones tomadas (antes "asunciones")
- **D-LIC.** Licencia **Apache-2.0** (open-source). *Evitar dependencias copyleft (GPL) en el core distribuido* (afecta a `scikit-survival`, ver §7).
- **D-MVP.** Fase 1 = **scorecard de comportamiento** (cartera vigente, **sin reject inference**).
- **D-PKG.** Entorno/empaquetado: **`uv` + `hatchling`**, `pyproject.toml`, `src/` layout.
- **D-CFG.** Configuración: **Pydantic v2** como única fuente de verdad (núcleo config-driven).
- **D-DATA.** Interfaz de datos: **pandas** (polars interno opcional si el volumen lo exige).
- **D-IA.** La capa narrativa es opcional y actualmente usa **Anthropic** vía API key del usuario;
  nunca calcula ni altera contenido cuantitativo.

---

## 4. Principios de diseño (no negociables)

1. **Reproducibilidad total.** `(datos + config + semilla) → resultado idéntico`. Semilla global propagada a todo componente estocástico (`numpy.random.Generator`, `random_state` en sklearn/XGBoost/LightGBM/CatBoost, `PYTHONHASHSEED`). Caveat documentado: GBDTs multihilo no son 100% deterministas.
2. **Auditabilidad por construcción.** Cada decisión (descarte, corte de binning, exclusión, selección) se registra con su razón y el umbral gatillante.
3. **Gobernanza en el núcleo (SR 11-7), no como reporte.** Cada corrida emite un **model card** + bundle de lineage (git SHA + hash de datos + config + seed + `uv.lock`).
4. **Monotonía con el riesgo.** Default en binning y modelos (incluido ML vía *monotonic constraints*). Efectos/β contrarios al riesgo se eliminan.
5. **Configuración declarativa.** El config Pydantic ES el experimento; la UI es su editor visual.
6. **Un solo núcleo, dos interfaces.** La UI React/FastAPI genera su formulario desde el mismo schema
   Pydantic y no duplica lógica de dominio.
7. **La IA documenta, no calcula.** Contenido cuantitativo 100% determinístico, existe sin API key.
8. **No reinventar lo resuelto.** Binning → OptBinning; inferencia → statsmodels. El valor propio está en **orquestación, gobernanza y monitoreo**.
9. **Núcleo liviano.** `core/` sin dependencias pesadas; backends ML/UI/forecasting detrás de *extras* opcionales con import perezoso.
10. **Calidad ejemplar (es marketing).** Cobertura de tests, tipado, docs y ejemplos al nivel de un proyecto de referencia.
11. **Doble verificación de datos externos.** Todo dato, tabla o parámetro extraído de internet o de normativa se confirma contra la **fuente oficial por una segunda vía** (ideal: render visual del documento original, no solo extracción de texto). El producto será usado por instituciones financieras: un número errado es **riesgo regulatorio**, no un detalle cosmético. Nada se da por bueno sin doble check trazado.

---

## 5. Dominios funcionales

### 5.1 Fundaciones (transversal)
- **Objeto `Study`/`Project`**: estado end-to-end serializable y recargable.
- **Config Pydantic v2** versionado (YAML ↔ modelo, round-trip).
- **Datos**: carga, validación de esquema (pandera/pydantic), definición de target (qué es "malo", ventana de desempeño, exclusiones, bueno/malo/indeterminado), política de *missing* y *special values*.
- **Particiones**: Desarrollo / Holdout / Out-of-Time / Through-the-Door; sugerencia automática editable.

### 5.2 Scoring / Scorecard (Fase 1 — comportamiento)
Pipeline:
1. **Tasa de incumplimiento** por período (PD promedio histórica + evolución).
2. **Binning** con **OptBinning** (Apache-2.0): WoE, **monotonía** (auto/valle/pico; no forzar U-shaped genuinas). *Ajuste solo en Desarrollo → transform al resto* (evita leakage).
3. **Univariado** sobre bins fijados, por muestra y período: **PSI/CSI, IV, ROC/AUC, KS, Gini**.
   - `WoE = ln(%Goods/%Bads)`; `IV = Σ(%Goods−%Bads)·WoE` (umbrales 0.02/0.1/0.3/0.5).
   - `PSI = Σ(%a−%e)·ln(%a/%e)` (<0.1 estable, 0.1–0.25 revisar, >0.25 redesarrollar).
4. **Descarte manual por negocio**.
5. **Correlación**: ranking por IV/ROC → eliminar correlacionadas (**Pearson/Spearman/Kendall**, |ρ|>0.7–0.8; VIF>5–10), conservando la de mayor poder.
6. **Stepwise** (**Wald** o **LR**) con **statsmodels** (p-values): signos de β coherentes con el riesgo (regla dura), discriminación mínima (IV/ROC configurable), **IV-contribution ≤ 90%** (parametrizable).
7. **Scorecard**: `Score = Offset + Factor·ln(odds)`, `Factor = PDO/ln(2)`; puntos por atributo `(β_i·WoE_i + α/n)·Factor + Offset/n`.
8. **Calibración de PD**: anclaje a tendencia central.
9. **Estabilidad del score** (PSI entre muestras/períodos).
10. **Tabla de rendimiento**: deciles → PD, tasa buenos/malos, totales, KS, lift.

> **Reject inference** (parcelling, fuzzy, reweighting) se incorpora con la sub-fase de **originación**, no en Fase 1.

### 5.3 Machine Learning (Fase 2)
- **SVM, Random Forest, XGBoost, LightGBM, CatBoost** (énfasis en CatBoost, infrautilizado).
- **Optuna** (samplers seedeados) para tuning; **monotonic constraints** donde el modelo lo soporte.
- **SHAP** + **reason codes** (sustituyen a la scorecard en modelos no lineales).
- Reusa el pipeline de datos/binning/selección/validación.
- *Nota:* scorecard (interpretable, regulatoria) y SHAP (post-hoc) **no son intercambiables 1:1**; ML aporta benchmark de poder predictivo.

### 5.4 Provisiones CMF — norma local (Fase 3)
- Motor **`cmf_standard`**: pérdida esperada estandarizada **`PE = PI · PDI · Exposición`** (Cap. **B-1** CNC).
- **Matrices regulatorias por cartera**: comercial individual (categorías A1–A6/B1–B4/C1–C6), comercial grupal (mora + garantías), consumo (modelo 2025: PI por mora banco/sistema + tenencia hipotecaria; PDI por producto), vivienda (mora × LTV).
- **Créditos contingentes** (Cap. B-3): factores de conversión (CCF).
- **Garantías** (Cap. B-1 num. 4; RAN 21-10 regula admisibilidad y condiciones): mitigan la pérdida esperada por **tres canales** según el tipo — avales/fianzas por **sustitución** de la calidad crediticia (PI·PDI del aval sobre la porción avalada), garantías reales por **tasa de recuperación**, garantías financieras por **descuento del valor razonable ajustado** de la exposición. Los aforos numéricos del modelo estándar viven en el B-1 (PVG/PVB/PTVG); los haircuts de garantías financieras los fija la CMF en circular específica.
- **Provisiones adicionales** por riesgos no capturados.
- **Parámetros numéricos**: extraídos y verificados contra texto oficial CMF/SBIF en [`docs/normativa_cmf_parametros.md`](normativa_cmf_parametros.md) (comercial individual A1–C6, grupal, consumo 2025, vivienda PVG, contingentes B-3, garantías). **Requieren validación humana contra el CNC v2022 vigente antes de uso productivo**; 1 pendiente menor documentado (haircuts/factores de descuento de garantías financieras del B-1 letra c, que la norma remite a circular específica de la CMF; el mapeo BBB-/Baa3 quedó resuelto por verificación visual 2026-06-23). Las matrices se tratan como **datos versionados**, no constantes hardcodeadas.

> **🔴 Decisión de diseño dura: CMF ≠ IFRS 9.** Son **dos motores separados**; montarlos como un solo "motor ECL" **incumple CMF**. El módulo `provisioning/` orquesta y expone el comparativo.
>
> **⚠️ CORRECCIÓN (2026-07-13) — la regla del máximo NO es entre CMF e IFRS 9.** Hasta hoy este documento afirmaba que «la provisión final aplica el máximo entre el ECL contable (IFRS 9) y el piso prudencial CMF», sin citar norma. Se verificó contra el texto oficial del Compendio de Normas Contables para Bancos y **era incorrecto**. Lo que la norma dice:
>
> - **Cap. A-2, numeral 5** — *"Lo establecido en el Capítulo 5.5 (deterioro de valor) de la NIIF9 (…) **no será aplicado respecto de las colocaciones** ("Adeudado por bancos" y "Créditos y cuentas por cobrar a clientes") (…) **ni sobre los "Créditos contingentes"**, ya que los criterios para estos temas se definen en los Capítulos B-1 a B-3 de este Compendio."*
>   → En los EEFF locales de un banco chileno **no existe un ECL NIIF 9 de colocaciones** que pueda compararse con la provisión B-1. El B-1 **sustituye** al ECL; no compite con él.
>
> - **Cap. B-1, hoja 10-11 (Circular N° 2.346 / 06.03.2024)** — *"La constitución de provisiones se efectuará considerando **el mayor valor obtenido entre el respectivo método estándar y el método interno**. (…) Esta regla se deberá aplicar **para cada institución en Chile que consolida con el banco**, separando así la matriz de sus filiales."*
>   → **La regla del máximo es `max(método estándar CMF, método interno del banco)`**, y se aplica **a nivel de entidad**, no por operación ni por celda de cartera.
>
> - El modelo estándar es la **base mínima prudencial**, y la norma **obliga a disponer de ambos métodos**: *"en ningún caso exime a las instituciones financieras de su responsabilidad de contar con metodologías propias (…) debiendo por tanto disponer de ambos métodos."*
>
> **Consecuencias de diseño:**
> - `provisioning/cmf` = el **método estándar**. Correcto tal cual.
> - El **método interno** es `PD × LGD × EAD` por grupo homogéneo — el propio B-1 lo describe así (*"asociando a cada grupo una determinada probabilidad de incumplimiento y un porcentaje de recuperación (…) multiplicando el monto total de colocaciones del grupo respectivo por los porcentajes de incumplimiento estimado y de pérdida dado el incumplimiento"*). Nikodym lo implementa en `provisioning/internal` y lo compara con el estándar mediante el orquestador, conforme al SDD-28.
> - `provisioning/ifrs9` (ECL) **sigue siendo válido**, pero cambia de destinatario: entidades que sí aplican NIIF 9 completa (reporting a una matriz extranjera, entidades no bancarias, instrumentos distintos de colocaciones). **No es el piso prudencial chileno.**
> - `provisioning` (orquestación) aplica una regla del máximo entre dos fuentes. **El encuadre normativo citable es estándar-vs-interno**; el comparativo CMF-vs-IFRS 9 se mantiene como comparativo entre marcos, **sin presentarlo como exigencia de la CMF**.

### 5.5 IFRS 9 / ECL (Fase 4)
- **PD**: 12m y **lifetime**, **term structure**, **PIT vs TTC**. Transformación PIT con **Vasicek monofactorial**: `PD_PIT(Z)=Φ[(Φ⁻¹(PD_TTC)−√ρ·Z)/√(1−ρ)]` (convención: Z ~ N(0,1), índice de ciclo con **Z>0 = expansión → menor PD** y **Z<0 = recesión → mayor PD**; el signo −√ρ·Z implementa esa orientación. Al portar fórmulas ASRF/Basilea —factor sistémico con signo + y peor caso evaluado en el cuantil superior— invertir el signo).
- **LGD**: distribución bimodal → **beta regression / fractional response / Tobit / workout LGD** (no OLS plano). `LGD = 1 − recovery`.
- **EAD/CCF**: `EAD = drawn + CCF·(límite − drawn)`.
- **Staging / SICR**: Stage 1/2/3; triggers (ratio PD lifetime vs origen ≥2×, backstop ≥3× PIT, downgrade por notches, cualitativos); backstops 30 dpd (SICR) / 90 dpd (default); *low credit risk exemption*. Umbrales **parametrizables por cartera**.
- **Motor ECL** (descuento a la **EIR** del instrumento):
  `ECL = Σ_k w_k · Σ_t [ PD_marg_k(t) · LGD_k(t) · EAD_k(t) / (1+EIR)^t ]`, `w_k` = peso de escenario.
- Stage 1 = suma truncada a 12m; Stage 2/3 = lifetime.

### 5.6 Forward-looking & dinámica (Fase 5)
- **Macro**: ARIMA/SARIMA/ARIMAX, **VAR/VECM** (`statsmodels`, `pmdarima`); diagnóstico Ljung-Box.
- **Escenarios** base/adverso/severo **ponderados por probabilidad** (≥3; nunca usar el escenario medio — la PD es no-lineal en macro). Más allá del horizonte *reasonable & supportable* → reversión a la media (TTC).
- **Satellite models** (forma Wilson/CreditPortfolioView): `logit(PD)` ~ factores macro. Interfaz central macro↔PD/LGD.
- **Markov**: estimación **cohort** y **duration/generador** (`scipy.linalg.expm`); multi-período (Chapman-Kolmogorov); no-homogéneo (Aalen-Johansen); manejo del *embedding problem* (Israel-Rosenthal-Wei) con flag de diagnóstico.
- **Survival (lifetime PD)**: Kaplan-Meier, Cox PH (Schoenfeld), AFT, y **discrete-time hazard** (logística/cloglog person-period) — **estándar IFRS 9 lifetime, reusa el stack de scoring**. `S(t)=∏(1−h_j)`, `PD_marg(t)=S(t−1)·h(t)`.
- **Cadena de integración**: `macro_projection → satellite_model → pd_lgd_term_structure → ecl_engine → scenario_weighting`. **Consistencia PIT** en toda la cadena.

### 5.7 Stress testing (Fase 5) y validación avanzada (Fase 6)

> **Nota de fase:** el módulo `stress/` (SDD-21) se produce en **T5/F5** porque consume los escenarios macro/satellite de §5.6; la **validación formal y el backtesting** (SDD-22) son **F6**. (Alineado con `ROADMAP.md` e `00-INDICE.md`.)
- Frameworks de referencia (conceptual): **EBA EU-wide**, **Fed CCAR/DFAST**, **ICAAP**; reverse stress testing.
- Sensibilidad de provisiones/ECL a shocks macro vía satellite models.
- **Validación**: discriminación (ROC/AUC, Gini, KS), calibración (Hosmer-Lemeshow, binomial, traffic-light, Brier), estabilidad (PSI), backtesting realizado-vs-estimado (t-test ECB para LGD/EAD).

### 5.8 Reporte y documentación (transversal)
- **Jinja2** como fuente primaria determinística → HTML autocontenido; **WeasyPrint** deriva PDF y
  **python-docx** produce Word. Se entrega además una fuente Markdown/Quarto editable opcional.
- **Capa IA opcional** (Anthropic): resumen ejecutivo e interpretación, marcada como generada por IA,
  sin tocar números. Sin API key → reporte base determinístico completo.
- Adjuntos tabulares **CSV/XLSX**; manifest y DTOs serializables a JSON para integración.

### 5.9 Interfaces de uso
- **API programática** (todas las fases), estilo scikit-learn.
- **UI visual React/Vite + FastAPI**: editor del config Pydantic, ejecución local y demo estática
  multi-dominio en `demo.nikodym.cl`.

---

## 6. Arquitectura de software

### 6.1 Principios estructurales
- **`src/` layout, monopaquete con sub-paquetes por dominio** (no multi-paquete: el núcleo compartido es fuerte).
- **`core/` agnóstico** (base classes, config, registry, seeding, lineage) sin backends pesados ni
  frontend. La UI importa el núcleo, nunca al revés.
- **Registry interno con decoradores** (`@register("logit")`) para modelos propios; `entry_points` solo si terceros aportan modelos (no necesario v1).
- **API estilo scikit-learn** (`fit/transform/predict`, `get_params/set_params`, sin lógica en `__init__`, validación en `fit`, `check_estimator`) en scoring, transformers (WoE/binning) y wrappers ML.
- **Clases base propias** (mismo "sabor") donde el contrato sklearn no calza: **forecasting** (patrón sktime `fit/predict` con horizonte), **survival** (y estructurado evento+tiempo), **ECL/CMF** (`BaseECLModel`/`BaseProvisionModel`, salida económica multi-componente, no un `predict` único).

### 6.2 `Study` + config declarativo
- El **`Study`** mantiene el estado y los artefactos; la API opera sobre él.
- El **config Pydantic v2** describe el pipeline completo. La **UI React genera el formulario desde el
  mismo schema** y serializa de vuelta (round-trip YAML↔modelo). Hydra/OmegaConf queda como capa fina
  opcional para barridos por CLI.

### 6.3 Árbol de paquetes
```
src/nikodym/
├── core/         # Study/Project, config Pydantic, registry, seeding, lineage, orquestación
├── data/         # carga, validación, target, particiones, missing/special
├── eda/          # tasa de default por período, estabilidad temporal
├── binning/      # wrapper OptBinning, WoE, monotonía
├── selection/    # PSI/CSI, IV, ROC/KS/Gini, correlación, filtros, negocio
├── model/        # abstracción Estimator; logística + stepwise (Wald/LR, signos) [statsmodels]
├── ml/           # SVM, RF, XGBoost, LightGBM, CatBoost (+ monotonic constraints)
├── tuning/       # Optuna (samplers seedeados)
├── explain/      # scorecard (WoE+β) y SHAP + reason codes
├── scorecard/    # escalado, offset/PDO, puntos por atributo
├── calibration/  # anclaje PD, PIT/TTC (Vasicek)
├── provisioning/ # orquesta y aplica la regla del máximo (ver §5.4: la regla del B-1 es
│              # max(estándar, interno), NO max(CMF, IFRS 9))
│   ├── cmf/      # motor estándar B-1 (PE=PI·PDI·Exposición, matrices, B-3, garantías)
│   ├── internal/ # método interno B-1 (PD·LGD·EAD por grupo homogéneo)
│   └── ifrs9/    # PD/LGD/EAD, staging (SICR), motor ECL (12m/lifetime)
├── forward/      # macro ARIMA/VAR, escenarios, satellite models (Wilson logit)
├── survival/     # KM, Cox, AFT, discrete-time hazard → lifetime PD [lifelines+statsmodels]
├── markov/       # transición cohort/duration, embedding, term structure
├── stress/       # stress testing, sensibilidad, escenarios severos
├── performance/  # tabla deciles/gains, KS, Gini, lift, swap-set
├── stability/    # PSI score, backtesting
├── validation/   # Hosmer-Lemeshow, binomial, traffic-light, Brier, t-test ECB
├── governance/   # model card, inventario, lineage (SR 11-7)
├── audit/        # semillas, registro de entorno, hash de datos, audit-trail
├── tracking/     # MLflow (runs, registry, artefactos)
├── report/       # Jinja2/WeasyPrint/python-docx, fuente Markdown, gráficos y capa IA opcional
├── ui/           # backend FastAPI y persistencia local de corridas; frontend React vive en web/
└── utils/
```

---

## 7. Stack tecnológico (con licencias)

| Dominio | Librería | Licencia |
|---|---|---|
| Datos / validación | pandas, numpy, pandera o pydantic | BSD/MIT ✅ |
| Binning / WoE | **OptBinning** | **Apache-2.0 ✅** |
| Estadística / logística | **statsmodels**, scikit-learn, scipy | BSD ✅ |
| ML | scikit-learn (SVM/RF), **xgboost, lightgbm, catboost** | permisivas ✅ |
| Tuning | optuna | MIT ✅ |
| Explicabilidad | shap | MIT ✅ |
| Supervivencia | **lifelines** | **MIT ✅** |
| Supervivencia (research only) | ⚠️ scikit-survival | **GPL-3.0 — NO en el core distribuido** |
| Series de tiempo | statsmodels, pmdarima | BSD/MIT ✅ |
| Tracking | mlflow | Apache-2.0 ✅ |
| Reporte | jinja2, WeasyPrint, python-docx; fuente Quarto opcional | permisivas ✅ |
| UI | React, Vite, FastAPI | permisivas ✅ |
| IA (opcional) | anthropic | — (API) |
| Build / entorno | **uv + hatchling**, pyproject.toml | permisivas ✅ |
| Calidad (test/dev) | pytest, ruff, mypy, pre-commit | permisivas ✅ |
| Property-based testing | hypothesis | MPL-2.0 (copyleft débil, scope por archivo) — solo dev/test, **no se redistribuye** en el wheel ✅ |

**Gestión de dependencias:** `[project.optional-dependencies]` para extras de usuario (`[xgboost]`, `[catboost]`, `[forecasting]`, `[ui]`, `[all]`); `[dependency-groups]` (PEP 735) para dev/test/docs. Backends pesados tras import perezoso con mensaje claro.

---

## 8. Outputs / artefactos

- `Study` serializado + modelo(s) (joblib/MLflow) + **config YAML** reproducible.
- **Scorecard** → Excel/CSV/JSON.
- Tablas: binning/WoE; IV·PSI·ROC·KS por variable × muestra × período; rendimiento (deciles); calibración; matrices de transición; términos de ECL; provisiones CMF.
- Gráficos: WoE, PSI, ROC/KS, distribución de score, calibración, term structure, escenarios.
- Reason codes / SHAP según modelo.
- **Model card** + **audit log** + **run MLflow**.
- **Informe HTML/PDF/Word** + fuente Markdown/Quarto editable y exports CSV/XLSX.

---

## 9. Auditabilidad, reproducibilidad y gobernanza (SR 11-7)

Tres pilares: desarrollo sólido · **effective challenge** (validación independiente) · governance con documentación e **inventario de modelos**.
- **Semilla global** propagada; determinismo garantizado (con caveat GBDT).
- **Lineage bundle** por modelo: git SHA + hash de datos + config + seed + `uv.lock`.
- **Model card** automático por corrida (propósito, supuestos, limitaciones, datos, métricas, fecha, próxima revisión).
- **Inventario versionado** = MLflow Registry.
- **Registro auditable de escenarios y overlays** (foco supervisor: evitar *earnings management*).
- Pensado para validadores y reguladores (**CMF** / IFRS 9 / SR 11-7).

---

## 10. Calidad de ingeniería (es marketing — §1)

- **Testing**: pytest + hypothesis; tests de reproducibilidad (mismo seed → mismo output); tests numéricos contra casos canónicos (fórmulas Vasicek, ECL, escalado).
- **CI**: ruff, mypy (strict en API pública), tests, build; pre-commit.
- **Docs**: mkdocs-material; ejemplos ejecutables y tutoriales por dominio.
- Semver, changelog, type hints y docstrings completos.

---

## 11. Estado y roadmap

El único plan vivo es [`ROADMAP.md`](ROADMAP.md). Este documento define el contrato del producto y
no mantiene una segunda cola de implementación.

Estado resumido a `1.3.0`:

| Capacidad | Estado de producto |
|---|---|
| Pipeline scorecard F1 | **Estable** bajo SemVer 1.x |
| ML, CMF, método interno, IFRS 9, forward, survival, Markov, stress y validación | **Implementados; experimentales** |
| UI React/FastAPI e informes HTML/PDF/Word | **Disponibles**; demo F1/F3/F4 publicada |
| Parámetros CMF | Implementados con tests; **validación humana pre-producción pendiente** |
| Originación/reject inference y plataforma institucional multiusuario | Futuro; requieren priorización y SDD |

Toda capacidad nueva o cambio contractual sigue la secuencia **priorizar → SDD → implementar → gates
→ revisión independiente**. Que un módulo exista no lo convierte en certificado ni amplía la garantía
SemVer del pipeline F1.

---

## 12. Riesgos y decisiones abiertas

**Riesgos**
- **R1 — Sobre-ampliación.** Mitigación: una sola prioridad por ola, SDD y entregable verificable.
- **R2 — Sobre-acoplamiento.** Mitigación: contratos vía `Study`/config; dominios independientes;
  `core/` liviano y ensamblado en la capa fina de runner/API.
- **R3 — Determinismo frágil.** Mitigación: tests de reproducibilidad, pin de dependencias (`uv.lock`).
- **R4 — Madurez desigual.** CMF, IFRS 9 y los dominios dinámicos son experimentales; no presentarlos
  como certificación ni ocultar datos faltantes, supuestos u overlays.
- **R5 — Parámetros CMF cambian** (la norma se actualiza). Mitigación: matrices como **datos versionados**, no constantes hardcodeadas.
- **R6 — Gate humano CMF.** La transcripción verificada y los tests no sustituyen la revisión humana
  celda a celda ni la resolución de haircuts remitidos a normativa complementaria.

**Decisiones abiertas (menores)**
- **D1.** ¿Polars interno desde cuándo? Depende de volúmenes reales de clientes.
- **D2.** Contratos del futuro workspace de corridas y ejecución durable; requieren SDD antes de código.
- **D3.** Autenticación, tenancy y despliegue institucional permanecen fuera del producto local hasta
  que exista un caso de uso priorizado.

---

## 13. Glosario

- **PD/LGD/EAD/CCF** — Probability of Default / Loss Given Default / Exposure at Default / Credit Conversion Factor.
- **PI/PDI** — Probabilidad de Incumplimiento / Pérdida Dado el Incumplimiento (nomenclatura CMF).
- **PE** — Pérdida Esperada (CMF). **ECL** — Expected Credit Loss (IFRS 9). **SICR** — Significant Increase in Credit Risk.
- **PIT/TTC** — Point-in-Time / Through-the-Cycle. **WoE/IV** — Weight of Evidence / Information Value.
- **PSI/CSI** — Population / Characteristic Stability Index. **KS** — Kolmogorov-Smirnov.
- **TTD/OOT/HO** — Through-the-Door / Out-of-Time / Holdout. **PDO** — Points to Double the Odds. **EIR** — Effective Interest Rate.
- **CNC / RAN** — Compendio de Normas Contables / Recopilación Actualizada de Normas (CMF). **SR 11-7** — guía de Model Risk Management (Fed).
