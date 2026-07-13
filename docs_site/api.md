# Referencia de la API

Superficie pública de Nikodym RiskLib, organizada por dominio. Cada símbolo se genera
automáticamente desde sus *docstrings* con [mkdocstrings]; las firmas y campos son los del código
publicado (`1.1.3`).

!!! note "Estabilidad (SemVer 1.x)"
    El pipeline de validación de scorecard (F1) —el trío `run` → `Study` → `NikodymConfig` y los
    dominios `data`, `eda`, `binning`, `selection`, `scorecard`, `calibration`, `performance`,
    `stability` y el reporte HTML— es **API estable**: no rompe hasta un 2.0. Las superficies que
    aún crecen (modelado ML, provisiones, forward-looking, resultados/métricas/orquestación) están
    marcadas como **experimentales** en su *docstring*, fuera de la garantía SemVer 1.x.

!!! note "Núcleo liviano e import perezoso"
    `import nikodym` no arrastra el stack ML. `nikodym.run` se re-exporta de forma perezosa (PEP
    562) desde `nikodym.api`, y los backends pesados de cada dominio (pandas, sklearn, statsmodels,
    optbinning, XGBoost, …) se cargan solo al ejecutar el paso correspondiente, tras sus *extras*
    opcionales.

## Ejecución y estado de la corrida

Punto de entrada único (`run`) y las estructuras *stateful* que produce: el `Study` contenedor, su
`ArtifactStore` *namespaced*, el `RunContext` (estado + lineage) y el `LineageBundle` reproducible.

::: nikodym.run
    options:
      heading_level: 3

::: nikodym.api.assemble_run
    options:
      heading_level: 3

<a id="study"></a>

::: nikodym.core.study.Study
    options:
      heading_level: 3

::: nikodym.core.artifacts.ArtifactStore
    options:
      heading_level: 3

::: nikodym.core.lineage.RunContext
    options:
      heading_level: 3

::: nikodym.core.lineage.LineageBundle
    options:
      heading_level: 3

::: nikodym.core.steps.Step
    options:
      heading_level: 3

## Configuración declarativa

`NikodymConfig` es la raíz del experimento (Pydantic v2): agrupa las secciones de reproducibilidad,
orquestación y todos los dominios. Se acompaña de utilidades de identidad (`config_hash`),
carga/volcado YAML y migración de esquema.

::: nikodym.core.config.schema.NikodymConfig
    options:
      heading_level: 3

::: nikodym.core.config.schema.RunConfig
    options:
      heading_level: 3

::: nikodym.core.config.schema.ReproConfig
    options:
      heading_level: 3

::: nikodym.core.config.hashing.config_hash
    options:
      heading_level: 3

::: nikodym.core.config.loader.load_config
    options:
      heading_level: 3

::: nikodym.core.config.loader.loads_config
    options:
      heading_level: 3

::: nikodym.core.config.loader.dump_config
    options:
      heading_level: 3

::: nikodym.core.config.migration.migrate
    options:
      heading_level: 3

::: nikodym.core.config.migration.migration
    options:
      heading_level: 3

## Datos

Carga, validación de esquema, definición del *target*, particionado y hashing lógico del dataset
(`data_hash`) que alimenta el lineage.

::: nikodym.data.config.DataConfig
    options:
      heading_level: 3

::: nikodym.data.loading.DataLoader
    options:
      heading_level: 3

::: nikodym.data.schema.SchemaValidator
    options:
      heading_level: 3

::: nikodym.data.target.TargetDefinition
    options:
      heading_level: 3

::: nikodym.data.partition.Partitioner
    options:
      heading_level: 3

::: nikodym.data.step.DataStep
    options:
      heading_level: 3

## Análisis exploratorio (EDA)

Perfilado univariado, calidad de datos, tasa de *default* y estabilidad temporal previa al modelado.

::: nikodym.eda.config.EdaConfig
    options:
      heading_level: 3

::: nikodym.eda.univariate.UnivariateProfiler
    options:
      heading_level: 3

::: nikodym.eda.quality.DataQualityProfiler
    options:
      heading_level: 3

::: nikodym.eda.default_rate.DefaultRateAnalyzer
    options:
      heading_level: 3

::: nikodym.eda.stability.TemporalStabilityAnalyzer
    options:
      heading_level: 3

::: nikodym.eda.step.EdaStep
    options:
      heading_level: 3

## Binning y WoE

Discretización supervisada con *Weight of Evidence* (WoE), monotonía controlada e IV (motor
OptBinning tras el *extra* `scoring`).

::: nikodym.binning.config.BinningConfig
    options:
      heading_level: 3

::: nikodym.binning.transformer.WoEBinner
    options:
      heading_level: 3

::: nikodym.binning.results.BinningResult
    options:
      heading_level: 3

::: nikodym.binning.step.BinningStep
    options:
      heading_level: 3

## Selección de variables

Filtrado pre-modelo por IV, correlación, VIF y estabilidad.

::: nikodym.selection.config.SelectionConfig
    options:
      heading_level: 3

::: nikodym.selection.selector.FeatureSelector
    options:
      heading_level: 3

::: nikodym.selection.results.SelectionResult
    options:
      heading_level: 3

::: nikodym.selection.step.SelectionStep
    options:
      heading_level: 3

## Modelo (regresión logística PD)

Regresión logística sobre variables WoE con *stepwise*, política de signos e inferencia
(statsmodels).

::: nikodym.model.config.ModelConfig
    options:
      heading_level: 3

::: nikodym.model.estimator.LogisticPDModel
    options:
      heading_level: 3

::: nikodym.model.results.ModelResult
    options:
      heading_level: 3

::: nikodym.model.step.ModelStep
    options:
      heading_level: 3

## Scorecard

Traducción de coeficientes a puntajes enteros (escala PDO / *target odds*), con *overrides* y
redondeo controlado.

::: nikodym.scorecard.config.ScorecardConfig
    options:
      heading_level: 3

::: nikodym.scorecard.scaler.PointsScaler
    options:
      heading_level: 3

::: nikodym.scorecard.transformer.Scorecard
    options:
      heading_level: 3

::: nikodym.scorecard.results.ScorecardResult
    options:
      heading_level: 3

::: nikodym.scorecard.step.ScorecardStep
    options:
      heading_level: 3

## Calibración

Ajuste de la PD cruda a un ancla de negocio (*through-the-cycle*), con tope de *offset* auditable.

::: nikodym.calibration.config.CalibrationConfig
    options:
      heading_level: 3

::: nikodym.calibration.calibrator.PDCalibrator
    options:
      heading_level: 3

::: nikodym.calibration.results.CalibrationResult
    options:
      heading_level: 3

::: nikodym.calibration.step.CalibrationStep
    options:
      heading_level: 3

## Desempeño

Métricas de discriminación (AUC/KS/Gini) y desempeño por decil, por partición.

::: nikodym.performance.config.PerformanceConfig
    options:
      heading_level: 3

::: nikodym.performance.evaluator.PerformanceEvaluator
    options:
      heading_level: 3

::: nikodym.performance.results.PerformanceResult
    options:
      heading_level: 3

::: nikodym.performance.step.PerformanceStep
    options:
      heading_level: 3

## Estabilidad

PSI/CSI y estabilidad temporal del puntaje y de las características.

::: nikodym.stability.config.StabilityConfig
    options:
      heading_level: 3

::: nikodym.stability.evaluator.StabilityEvaluator
    options:
      heading_level: 3

::: nikodym.stability.results.StabilityResult
    options:
      heading_level: 3

::: nikodym.stability.step.StabilityStep
    options:
      heading_level: 3

## Validación

Backtesting y pruebas regulatorias de discriminación, calibración y estabilidad (familias de tests).

::: nikodym.validation.config.ValidationConfig
    options:
      heading_level: 3

::: nikodym.validation.evaluator.ValidationEvaluator
    options:
      heading_level: 3

::: nikodym.validation.results.ValidationResult
    options:
      heading_level: 3

::: nikodym.validation.step.ValidationStep
    options:
      heading_level: 3

## Backends ML

Modelos GBDT (XGBoost, LightGBM, CatBoost), *random forest* y SVM como *extras* selectivos, con
monotonía y comparación *challenger* frente al scorecard.

::: nikodym.ml.config.MLConfig
    options:
      heading_level: 3

::: nikodym.ml.results.MLResult
    options:
      heading_level: 3

::: nikodym.ml.step.MLStep
    options:
      heading_level: 3

## Tuning de hiperparámetros

Optimización del espacio de búsqueda (Optuna) con muestreadores/*pruners* deterministas.

::: nikodym.tuning.config.TuningConfig
    options:
      heading_level: 3

::: nikodym.tuning.results.TuningResult
    options:
      heading_level: 3

::: nikodym.tuning.step.TuningStep
    options:
      heading_level: 3

## Explicabilidad

Explicaciones globales/locales (SHAP opcional) y *reason codes* para scorecard y modelos ML.

::: nikodym.explain.config.ExplainConfig
    options:
      heading_level: 3

::: nikodym.explain.results.ExplainResult
    options:
      heading_level: 3

::: nikodym.explain.step.ExplainStep
    options:
      heading_level: 3

## Survival

Modelos de tiempo-a-evento: Kaplan-Meier, hazard discreto y Cox/AFT (algunos tras *extra*).

::: nikodym.survival.config.SurvivalConfig
    options:
      heading_level: 3

::: nikodym.survival.step.SurvivalStep
    options:
      heading_level: 3

## Cadenas de Markov

Estimación de matrices de transición y estructura temporal de PD por estados.

::: nikodym.markov.config.MarkovConfig
    options:
      heading_level: 3

::: nikodym.markov.step.MarkovStep
    options:
      heading_level: 3

## Forward-looking

Proyección macroeconómica, modelos satélite y escenarios ponderados para PD *point-in-time*.

::: nikodym.forward.config.ForwardConfig
    options:
      heading_level: 3

::: nikodym.forward.results.ForwardResult
    options:
      heading_level: 3

::: nikodym.forward.step.ForwardStep
    options:
      heading_level: 3

## Stress testing

Escenarios de *shock*, barridos de sensibilidad y *reverse stress* sobre las métricas de provisión.

::: nikodym.stress.config.StressConfig
    options:
      heading_level: 3

::: nikodym.stress.results.StressResult
    options:
      heading_level: 3

::: nikodym.stress.step.StressStep
    options:
      heading_level: 3

## Provisiones

Dos motores separados —**CMF (Chile)** e **IFRS 9/ECL**— orquestados por una capa fina que reporta
el **máximo** de ambos (piso prudencial).

::: nikodym.provisioning.config.ProvisioningConfig
    options:
      heading_level: 3

::: nikodym.provisioning.orchestrator.ProvisioningOrchestrator
    options:
      heading_level: 3

::: nikodym.provisioning.results.ProvisionOrchestrationResult
    options:
      heading_level: 3

::: nikodym.provisioning.step.ProvisioningStep
    options:
      heading_level: 3

### Motor CMF

::: nikodym.provisioning.cmf.config.CmfProvisioningConfig
    options:
      heading_level: 4

::: nikodym.provisioning.cmf.engine.CmfProvisioningEngine
    options:
      heading_level: 4

::: nikodym.provisioning.cmf.results.CmfProvisionResult
    options:
      heading_level: 4

### Motor IFRS 9 / ECL

::: nikodym.provisioning.ifrs9.config.IfrsProvisioningConfig
    options:
      heading_level: 4

::: nikodym.provisioning.ifrs9.engine.IfrsProvisioningEngine
    options:
      heading_level: 4

::: nikodym.provisioning.ifrs9.results.IfrsProvisionResult
    options:
      heading_level: 4

## Gobernanza

*Model card* (SR 11-7), inventario de modelos y registro de escenarios/overlays. Es la superficie de
trazabilidad que `run` ensambla y (opcionalmente) publica al inventario.

::: nikodym.governance.config.GovernanceConfig
    options:
      heading_level: 3

::: nikodym.governance.model_card.ModelCard
    options:
      heading_level: 3

::: nikodym.governance.model_card.ModelCardBuilder
    options:
      heading_level: 3

::: nikodym.governance.inventory.ModelInventory
    options:
      heading_level: 3

::: nikodym.governance.inventory.NullInventory
    options:
      heading_level: 3

::: nikodym.governance.inventory.InventoryEntry
    options:
      heading_level: 3

::: nikodym.governance.inventory.publish_inventory
    options:
      heading_level: 3

::: nikodym.governance.scenarios.ScenarioLog
    options:
      heading_level: 3

## Auditoría, lineage y reproducibilidad

*Audit sink* JSONL, captura del entorno y hashing determinista de datos/archivos, más la relectura
del *trail* para reconstruir la corrida.

::: nikodym.audit.config.AuditConfig
    options:
      heading_level: 3

::: nikodym.audit.sink.JsonlAuditSink
    options:
      heading_level: 3

::: nikodym.audit.environment.EnvironmentSnapshot
    options:
      heading_level: 3

::: nikodym.audit.environment.capture_environment
    options:
      heading_level: 3

::: nikodym.audit.hashing.hash_dataframe
    options:
      heading_level: 3

::: nikodym.audit.hashing.hash_file
    options:
      heading_level: 3

::: nikodym.audit.replay.read_trail
    options:
      heading_level: 3

::: nikodym.audit.replay.iter_trail
    options:
      heading_level: 3

## Tracking (MLflow)

Registro opcional de corridas y modelos en un backend externo (MLflow), tras el *extra*
correspondiente.

::: nikodym.tracking.config.TrackingConfig
    options:
      heading_level: 3

::: nikodym.tracking.recorder.TrackingRecorder
    options:
      heading_level: 3

::: nikodym.tracking.sink.TrackingSink
    options:
      heading_level: 3

::: nikodym.tracking.inventory.MLflowInventory
    options:
      heading_level: 3

## Reportería

Reporte auditable del scorecard: ensamblado del bundle, render HTML/PDF y narración opcional
(regla o IA).

::: nikodym.report.config.ReportConfig
    options:
      heading_level: 3

::: nikodym.report.builder.ReportBuilder
    options:
      heading_level: 3

::: nikodym.report.renderer.HtmlReportRenderer
    options:
      heading_level: 3

::: nikodym.report.renderer.PdfReportRenderer
    options:
      heading_level: 3

::: nikodym.report.results.ReportResult
    options:
      heading_level: 3

::: nikodym.report.step.ReportStep
    options:
      heading_level: 3

## Datasets y presets (helpers)

Utilidades para el quickstart y la UI: materialización determinista de datasets sintéticos,
ingesta de *uploads* y el config F1 curado (`standard_preset`).

::: nikodym.ui.datasets.materialize
    options:
      heading_level: 3

::: nikodym.ui.datasets.list_datasets
    options:
      heading_level: 3

::: nikodym.ui.datasets.ingest_upload
    options:
      heading_level: 3

::: nikodym.ui.presets.standard_preset
    options:
      heading_level: 3

## Extras opcionales

Introspección de *extras* instalados e imports perezosos con error accionable cuando falta una
dependencia opcional.

::: nikodym.utils.optional.has_extra
    options:
      heading_level: 3

::: nikodym.utils.optional.require_extra
    options:
      heading_level: 3

[mkdocstrings]: https://mkdocstrings.github.io/
