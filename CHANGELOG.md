# Changelog

Formato basado en [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/);
el proyecto sigue [SemVer](https://semver.org/lang/es/) (0.x honesto: APIs que crecerán
marcadas como experimentales hasta la 1.0).

## [No publicado]

### Añadido (F0 — Fundación, en curso)
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
