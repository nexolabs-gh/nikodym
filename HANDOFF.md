# HANDOFF

_Última actualización: 2026-06-24 · repo privado `nexolabs-gh/nikodym` · sobre commit `4a3faf2`_

## Estado actual
**Nikodym RiskLib — F0 (Fundación) EN CURSO, construyendo `core`.** Diseño de Fundación cerrado (Tanda 0/1/1Rev + Hito 0). F0 troceado en 4 bloques: **B1 `core`** (en curso) · B2 `data` · B3 `audit`+`governance`+`tracking`+`api` · B4 `testing`+CI+3 criterios Hito 0.

**B1 `core` por dentro:** B1a ✅ (esqueleto + `exceptions` + `seeding`) · **B1b ✅ (`core/config`)** ← este commit · B1c… pendiente (audit → results → base/mixins → registry/artifacts → steps → lineage → study).

Regla de oro vigente: **mixto-troncal-más-incremental** — cada módulo: programa → `ruff`+`mypy --strict`+`pytest`+cobertura verde → ajusta → sigue. Nunca avanzar en rojo. Reabrir un SDD por feedback del código es esperado y barato.

## Hecho en esta sesión (B1b · `core/config`)
- **`src/nikodym/core/config/`** (4 módulos): `schema.py` (`NikodymBaseConfig` frozen+`extra=forbid`, `ReproConfig` seed=42 ge=0, `RunConfig` fail_fast=True, `NikodymConfig` raíz construible sin args), `hashing.py` (`config_hash` = SHA-256 del JSON canónico `model_dump(mode="json", by_alias=True, exclude=set(INFRA_SECTIONS))` + `json.dumps(sort_keys=True, separators, ensure_ascii=False)`; `INFRA_SECTIONS={name,governance,audit,tracking,report}`), `loader.py` (`load_config`/`loads_config`/`dump_config`, round-trip YAML con `safe_load`), `migration.py` (`migrate` version-gate + `@migration` decorador + `_parse` SemVer; `_MIGRATORS` **vacío** en 1.0.0). `core/__init__.py` re-exporta toda la superficie de config.
- **Construido por método ultracode:** workflow de comprensión (5 lectores + síntesis, **Pydantic v2 verificado con context7**) → código por DanIA → **workflow de revisión adversarial (20 agentes, 4 dimensiones, 14 hallazgos reales)** → integración por DanIA.
- **9 hallazgos de la revisión cerrados de raíz** (ver "Decisiones"). 
- **Tests:** `tests/unit/test_config_{schema,hashing,loader,migration,public_api}.py` + `tests/repro/test_config_hash_golden.py`. **109 passed.**
- **Verde total:** `ruff check`+`format`, `mypy --strict` (14 archivos), cobertura **100% global** + gate regulatorio **100%**, `uv build` wheel + smoke import aislado (py3.12), núcleo liviano confirmado (config no arrastra sklearn/mlflow).
- **Golden `config_hash` de `NikodymConfig()` congelado:** `02b667fc7421ceb14fa7c72f9897d8e16a66fb7e8cba116d1336677b32582175` (test repro lo verifica, incl. cross-proceso con PYTHONHASHSEED variado).
- **pyproject:** añadido `types-PyYAML>=6.0` al grupo `lint` (dev-only, stubs mypy). `uv.lock` actualizado.

## En curso / a medias
Nada a medias. B1b cerrado y verde. Working tree limpio salvo los archivos de B1b (este commit).

## Próximos pasos
**Arrancar B1c = resto de `core`**, en este **orden topológico** (cada módulo: programar + test + verde antes de seguir). Leer primero `docs/design/01-core.md`, `03-audit-governance.md`, `04-tracking.md` y `_CONTRATOS-TRANSVERSALES.md`. Método sugerido (igual que B1b): fan-out de comprensión (verificar APIs con context7) → código por DanIA → revisión adversarial → integración.
1. **`core/audit.py`**: `AuditEvent`, `AuditSink` (Protocol), `NullAuditSink`, `InMemoryAuditSink`, `FanOutSink` (compositor CT-4).
2. **`core/results.py`**: SOLO Protocols `ProvisionResultLike`/`ECLResultLike` con `term_structure()->DataFrame|None` (CT-2), `@runtime_checkable`. Sin clases concretas (F3/F4).
3. **`core/base.py` + `core/mixins.py`**: `BaseNikodymEstimator` (raíz propia NO sklearn, `config_cls: ClassVar`, `from_config` excl. `type`, `get_params/set_params`, `_check_fitted`) + 6 familias; `AuditableMixin` (`_audit=NullAuditSink()` nunca None), `SerializationMixin`.
4. **`core/registry.py` + `core/artifacts.py`**: `Registry`/`REGISTRY`/`register` namespaced; `ArtifactStore` (domain,key) con `ArtifactNotFoundError`/`ArtifactExistsError`.
5. **`core/steps.py`**: `ArtifactKey=tuple[str,str]`, `Step` Protocol `@runtime_checkable` con `requires`/`provides` (CT-1), `StepAdapter`.
6. **`core/lineage.py`**: `LineageBundle` + `RunContext` (status="created" serializa sin valores ficticios, DoD F0).
7. **`core/study.py`**: `Study` (validación pre-run CT-1 → `ArtifactNotFoundError` antes de execute; orden de declaración, scheduler topológico diferido F5; `save`/`load` directorio atómico; `set_audit_sink` recibe el sink ya compuesto; `lineage_bundle` congelado). Validar que `fail_fast=False`/`register_on_success` NO sean no-op silenciosos (warning ruidoso). **Owner de `fail_fast` (forzado True en v1): el campo vive en `RunConfig` (B1b); el warning ruidoso si llega False lo pone aquí, no en config.**

Cierre de B1 = primer `Study` end-to-end con lineage reproducible. Luego B2 (`data`), B3, B4 (incl. los 3 criterios Hito 0). **B1c es un sub-bloque casi independiente → buen momento para sesión fresca** (este HANDOFF es el puente).

## Decisiones / contexto a recordar
- **Decisiones de integrador tomadas en B1b (técnicas; ratificar al revisar SDD si toca):**
  - `data: Any | None = None` (placeholder F0; con `data=None` serializa a `null` igual que un futuro `DataConfig`, golden hash no cambia al endurecer en B2 vía `model_rebuild()`). TODO anclado en `schema.py`.
  - Módulo se llama **`hashing.py`** (el plan B1b lo fija); SDD-01 lo menciona en prosa como `core.config.io`. Divergencia a ratificar.
  - Parser **SemVer local** `_parse` (regex `^\d+\.\d+\.\d+$`), sin `packaging` (núcleo liviano).
  - **Sin Hypothesis** en F0 (diferida a F1); round-trip determinista cubre el DoD.
- **Hallazgos de la revisión adversarial CERRADOS en B1b (mantener):**
  - `config_hash` no-determinista si entra un `set`/objeto-no-serializable/NaN-inf en `data` → **`field_validator("data")` exige `data` JSON-canónico** (`json.dumps(v, allow_nan=False)`). Cierra 3 hallazgos.
  - Versión malformada o `schema_version` no-`str` lanzaba `ValueError` crudo que escapaba `NikodymError` → **`_parse` con regex + guarda de tipo** → todo cae en `ConfigError`. Cierra 3 hallazgos (viola la regla dura "todo desciende de NikodymError").
  - Bucle de migración podía colgar (ciclo / migrador no-avanzante) y selección golosa entraba a ramas muertas → **`@migration` valida `to>from` y origen único en import-time** (cadena lineal). Cierra 2.
  - YAML malformado escapaba como `YAMLError` crudo → **envuelto en `ConfigError`** (`test_load_usa_safe_load` ahora espera `ConfigError`).
- **Deudas DIFERIDAS a B2 (dependen del `DataConfig` real; NO son gap de F0):** normalización de `data.load.source` a basename para hash cross-máquina (SDD-01 §5/§12); `allow_inf_nan=False` general en `NikodymBaseConfig` para campos float futuros (provisioning/calibration); sombreado de nombre `migration` (el atributo `nikodym.core.config.migration` resuelve al **decorador**, no al submódulo — para acceder al módulo usar `from nikodym.core.config.migration import X`; revisar convención cuando se escriba el 1er migrador real, p.ej. renombrar a `register_migration`).
- **Desviaciones de SDD a ratificar (acumuladas):** las 4 de B1a (mypy 3.12 por numpy 2.x; nombres de import en `EXTRA_TO_DISTRIBUTIONS`; gate `coverage-regulatory` por `--include`; `per-file-ignores` tests) + 3 de B1b (`types-PyYAML` dev-only; `hashing.py` vs `io.py`; rechazo de `schema_version` con aridad≠3/pre-release, endurece SDD-05 §5.4).
- **Comandos verde:** `uv sync --no-default-groups --group test --group lint --python 3.12`. Verificar: `uv run --no-sync ruff check . && uv run --no-sync ruff format --check . && uv run --no-sync mypy && uv run --no-sync pytest --cov=nikodym --cov-report=term-missing`. Gate regulatorio: `coverage run -m pytest` + `coverage report --include="*/nikodym/core/exceptions.py,*/nikodym/core/seeding.py,*/nikodym/provisioning/cmf/__init__.py,*/nikodym/provisioning/ifrs9/__init__.py" --fail-under=100`.

## Callejones sin salida / no reintentar
- **Colisión módulo/función `migration`:** `import nikodym.core.config.migration as m` agarra el **decorador** (CPython usa atributo vía `IMPORT_FROM`), no el submódulo. Para los privados (`_MIGRATORS`, `_parse`) en tests usar `from nikodym.core.config.migration import _MIGRATORS, _parse`.
- **`__all__` orden ruff RUF022:** SCREAMING_CASE → CamelCase → lowercase. Dejar que `ruff check --fix` lo ordene.
- **NO** fijar mypy `python_version="3.11"` con numpy 2.x (rompe stubs PEP 695). Usar 3.12.
- **NO** correr el gate regulatorio con `--cov=nikodym.core.seeding` por nombre de módulo (doble-load numpy 2.x); usar `coverage report --include=<rutas>`.
- **NO** reintroducir los claims tumbados en Tanda 1 Rev: `spawn()` posicional (usar entropía compuesta hashlib); herencia sklearn obligatoria; `DataFrame.eval/query` como sandbox; Model Stages MLflow (usar aliases+tags). **NO** hashear bytes de Parquet para `data_hash` (contenido lógico por bloques).
- **Workflow JS gotchas:** prompts son template literals (sin backticks internos; `${...}` sí); `Date.now()`/`Math.random()` prohibidos; no pasar `run_in_background`.

## Dudas abiertas / bloqueos (preexistentes, no urgentes)
- **Pendiente normativo CMF:** haircuts/factores de descuento de garantías financieras del B-1 letra c) (`normativa_cmf_parametros.md` §5.2/§7).
- **Deudas con owner (Hito 0 §5):** pickle/joblib del `ArtifactStore` → F3; motor topológico DAG → F5; capa datos longitudinal → F4/F5; matriz CI 3×3 + Hypothesis → F1; `mypy strict` sobre wrappers sin stubs (statsmodels/lifelines) → cast/ignore localizados F1/F5.
- Momento privado→público del repo (al terminar). Alias de email del paquete y Trusted Publishing OIDC al armar el release público (F1).

## Repo
Privado en GitHub: **`nexolabs-gh/nikodym`** (https://github.com/nexolabs-gh/nikodym), branch `main`. Push directo a `main` autorizado en el cierre. Commits con co-autoría de Claude.
