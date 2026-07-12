# Changelog

Formato basado en [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/);
el proyecto sigue [SemVer](https://semver.org/lang/es/): desde 1.0, el pipeline de scorecard (F1)
es API estable; las superficies que aún crecen (modelado ML, provisiones, forward-looking,
contratos transversales) quedan marcadas como experimentales, fuera de la garantía SemVer 1.x.

## [1.0.0] — 2026-07-12

Primer release estable. Congela la superficie pública del **pipeline de validación de scorecard
(F1)** bajo garantía SemVer 1.x (no rompe hasta un 2.0): `nikodym.run`, el config raíz
(`run` → `Study` → `NikodymConfig`) y los dominios `data`, `eda`, `binning`, `selection`,
`scorecard`, `calibration`, `performance` (AUC/KS/Gini), `stability` (PSI/CSI) y el reporte HTML.

### Estable (SemVer 1.x)
- Pipeline scorecard F1 de punta a punta y su config declarativo; audit-trail y reproducibilidad
  (`config_hash`).

### Sigue experimental (fuera de la garantía SemVer 1.x)
- Modelado ML/tuning/explicabilidad, forward-looking, Markov, survival y stress testing.
- Provisiones **CMF** e **IFRS 9/ECL** (motores implementados y deterministas, pero su superficie
  regulatoria aún crece y no está *battle-tested* en producción).
- Validación avanzada (backtesting/discriminación), gobernanza/tracking, formatos de reporte
  PDF/DOCX y narrativa por IA, y los contratos transversales de resultados/métricas/orquestación.

### Changed
- Marcadores de estabilidad por módulo: `Experimental (SemVer 0.x)` → `Estable (SemVer 1.x)` en el
  core F1, y → `Experimental (fuera de la garantía SemVer 1.x)` en la superficie que crece.

## [0.9.0] — 2026-07-10

Primer release público en PyPI. Motor V1 completo (F0–F7) y verde en CI; API pública
versionada como 0.x honesto (puede cambiar hasta la 1.0).

### Incluye
- **Núcleo reproducible** (F0): config declarativo Pydantic v2, `Study`/lineage, audit-trail,
  artifacts *namespaced*, gobernanza SR 11-7.
- **Scorecard (F1)**: binning/WoE monotónico (optbinning), selección, regresión logística,
  scorecard escalado, calibración, desempeño (AUC/KS/Gini) y estabilidad (PSI/CSI).
- **Backends ML (F2)**: XGBoost, LightGBM, CatBoost, tuning (Optuna) y explicabilidad (SHAP)
  como *extras* selectivos.
- **Provisiones**: motores **CMF (Chile)** e **IFRS 9/ECL** separados (provisión = máximo).
- **Forward-looking y stress testing**.
- **UI (F7)**: flujo Scorecard F1 (Datos · Ejecutar · Resultados · Reporte) — React + backend
  FastAPI, con modo claro/oscuro y reporte HTML del modelo.
- **Empaquetado**: publicación en PyPI vía Trusted Publishing (OIDC, sin tokens).

### Detalle de la Fundación (F0)
- Esqueleto del paquete: `pyproject.toml` (uv + hatchling, layout `src/`, 7 deps base,
  extras de usuario y grupos de desarrollo PEP 735), `LICENSE` Apache-2.0, `README`, `CHANGELOG`.
- `nikodym.core.exceptions`: jerarquía de excepciones con raíz `NikodymError` (código
  regulatorio, cobertura objetivo 100 %).
- `nikodym.core.seeding`: `SeedManager` — derivación determinista por nombre vía
  `SeedSequence(entropy=[root_seed, hashlib])` (código regulatorio, cobertura objetivo 100 %).
- `nikodym.core.config`: configuración declarativa (Pydantic v2). `NikodymConfig` *frozen*
  construible sin argumentos, secciones `ReproConfig`/`RunConfig`; `config_hash` (SHA-256 del
  JSON canónico que excluye `INFRA_SECTIONS`, estable e idéntico entre procesos); `load_config`/
  `dump_config` (round-trip YAML con `safe_load`); version-gate `migrate` + decorador `@migration`
  (registro vacío en 1.0.0, cadena lineal validada en import-time). Experimental (SemVer 0.x).
- `nikodym.utils.optional`: `require_extra` / `has_extra` / `EXTRA_TO_DISTRIBUTIONS`
  (import perezoso de extras con mensaje accionable).
- Paths regulatorios declarados (`nikodym.provisioning.cmf`, `nikodym.provisioning.ifrs9`)
  para el gate de cobertura regulatoria; su implementación llega en F3/F4.
- `nikodym.core` (resto de la Fundación, 9 módulos): primer `Study` end-to-end con lineage
  reproducible. `audit` (`AuditEvent`/`AuditKind`/`AuditSink`, `NullAuditSink`/`InMemoryAuditSink`/
  `FanOutSink`); `results` (Protocols económicos `ProvisionResultLike`/`ECLResultLike` con
  `term_structure()`, CT-2); `base` (`BaseNikodymEstimator` raíz propia + 6 familias, semántica
  `get_params`/`set_params`/`from_config` estilo scikit-learn sin heredarlo); `mixins`
  (`AuditableMixin`, `SerializationMixin` con puerta `trust`); `registry`/`artifacts` (registro y
  almacén *namespaced* `(domain, key)`); `steps` (`Step`/`StepAdapter`, `requires`/`provides`, CT-1);
  `lineage` (`LineageBundle`/`RunContext`); `study` (`Study`: orquestador motor v1 con validación de
  prerequisitos CT-1, persistencia en directorio atómico, recarga con verificación de `config_hash`
  y reproducibilidad). Experimental (SemVer 0.x): orquestación y Protocols de resultados crecerán.
- `nikodym.data` (B2a — capa `data`, configuración + endurecimiento, SDD-02 §5): sub-config
  declarativo `DataConfig` (`nikodym/data/config.py`): árbol Pydantic completo (Loading/Schema/Target/
  Missing/Partition), mini-DSL declarativo `Predicate`/`Rule` (allowlist cerrada de operadores, sin
  `eval`), unión discriminada **anidada** de la estrategia de partición (temporal/random/cohort) por
  factory local, `model_validator` de fracciones (suman 1) y de regla no vacía, alias `schema` con
  `populate_by_name`. Endurecido `NikodymConfig.data` de `Any` a `DataConfig | None` (tipado estricto
  para mypy; coerción en runtime vía hook `_DATA_CONFIG_CLS` que `nikodym.data` puebla al importarse —
  el núcleo sigue liviano, no importa `data`). Golden `config_hash` por defecto **invariante**. Deps
  base activadas: `pandera>=0.24` (uso `import pandera.pandas`) y `pyarrow>=14`. Experimental (SemVer 0.x).
