# HANDOFF

_Última actualización: 2026-06-24 · repo privado `nexolabs-gh/nikodym` · sobre commit `f309821`_

## Estado actual
**Nikodym RiskLib — F0 (Fundación) EN CURSO, programando.** Diseño de Fundación cerrado (Tanda 0/1/1Rev + Hito 0). **Ya hay código**: arrancó F0 y el **Bloque 1a quedó verde**. El plan completo de F0 está cerrado (17 módulos en orden topológico, 61 archivos) y F0 se troceó en **4 bloques**:
- **B1 · `core`** ← en curso. (B1a ✅ hecho; B1b… = resto de core, pendiente.)
- **B2 · `data`** (panel transversal, `data_hash` lógico).
- **B3 · `audit` + `governance` + `tracking` + `api`** (gobernanza y ensamblado `assemble_run`).
- **B4 · `testing` + tests del DoD + CI + los 3 criterios del Hito 0.**

Regla de oro vigente (Cami): **mixto-troncal-más-incremental** — diseña de extremo a extremo lo caro de cambiar (contratos transversales, ya hechos en Hito 0); difiere just-in-time lo barato. Cada bloque: **programa → `ruff`+`mypy --strict`+`pytest`+cobertura verde → ajusta → sigue**.

## Hecho en esta sesión
- **Workflow de comprensión** (fan-out de 9 lectores + síntesis) sobre los 9 docs de Fundación → **plan de construcción de F0**: orden topológico de 17 módulos, 61 archivos, alcance F0 (incluye/difiere), 9 conflictos y 8 riesgos. (Resultado efímero en `/tmp`; lo esencial está abajo.)
- **B1a construido y 100% verde** (este commit):
  - Esqueleto: `pyproject.toml` (uv+hatchling≥1.27, `src/` layout, 7 deps base, extras, grupos PEP 735), `uv.lock` (Python 3.12, numpy 2.5, pydantic 2.13), `LICENSE` Apache-2.0, `README.md`, `CHANGELOG.md`.
  - `src/nikodym/`: `__init__.py` (`__version__="0.1.0"`), `py.typed`, `core/exceptions.py` (jerarquía completa `NikodymError`+subclases, **cobertura 100%**), `core/seeding.py` (`SeedManager`, derivación por nombre con `hashlib`+`SeedSequence`, **cobertura 100%**, golden values congelados), `utils/optional.py` (`require_extra`/`has_extra`/`EXTRA_TO_DISTRIBUTIONS`), `core/__init__.py`, `utils/__init__.py`, `provisioning/{cmf,ifrs9}/__init__.py` (paths regulatorios declarados para el gate).
  - Tests: `tests/unit/test_exceptions.py`, `tests/unit/test_optional.py`, `tests/repro/test_seeding_golden.py`, `tests/conftest.py`. **44 passed.**
  - Verificado: `ruff check`+`format`, `mypy --strict` (9 archivos), cobertura **100% global**, gate regulatorio **100%** (forma robusta, ver abajo), `uv build` wheel+sdist + smoke import aislado, núcleo liviano (sin sklearn/mlflow al `import nikodym`).

## En curso / a medias
Nada a medias. B1a está cerrado y verde. Working tree limpio salvo los archivos nuevos de B1a (este commit).

## Próximos pasos
**Arrancar B1b = resto de `core`**, en este **orden topológico** (cada módulo: programar + test + verde antes de seguir). Leer primero `docs/design/01-core.md` y `05-convenciones-config.md` (ya rigen todo core) + `_CONTRATOS-TRANSVERSALES.md`:

1. **`core/config/`** (4 módulos, decisión tomada): `schema.py` (`NikodymBaseConfig`/`NikodymConfig` + secciones `|None`, `ReproConfig` seed=42 ge=0, `RunConfig` fail_fast forzado True) · `hashing.py` (`config_hash` = sha256 JSON canónico, `exclude=INFRA_SECTIONS={name,governance,audit,tracking,report}`, `by_alias=True`, `sort_keys=True`) · `loader.py` (round-trip YAML) · `migration.py` (`@migration` dict→dict, registro **vacío** en 1.0.0, version-gate 5 ramas). **`NikodymConfig()` sin args construible (DoD F0).** ⚠️ Verificar Pydantic v2 `model_rebuild`/`by_alias`/`frozen` con **context7** (no de memoria); el forward-ref `DataConfig` se resuelve con `model_rebuild()` al importar `nikodym.data` (B2).
2. **`core/audit.py`**: `AuditEvent`, `AuditSink` (Protocol), `NullAuditSink`, `InMemoryAuditSink`, `FanOutSink` (compositor CT-4).
3. **`core/results.py`**: SOLO Protocols `ProvisionResultLike`/`ECLResultLike` con `term_structure()->DataFrame|None` (CT-2). `@runtime_checkable`. Sin clases concretas (esas son F3/F4).
4. **`core/base.py` + `core/mixins.py`**: `BaseNikodymEstimator` (raíz propia NO sklearn, `config_cls: ClassVar`, `from_config` excl. `type`, `get_params/set_params`, `_check_fitted`) + 6 familias; `AuditableMixin` (`_audit=NullAuditSink()` nunca None), `SerializationMixin`.
5. **`core/registry.py` + `core/artifacts.py`**: `Registry`/`REGISTRY`/`register` namespaced; `ArtifactStore` (domain,key) con `ArtifactNotFoundError`/`ArtifactExistsError`.
6. **`core/steps.py`**: `ArtifactKey=tuple[str,str]`, `Step` Protocol `@runtime_checkable` con `requires`/`provides` (CT-1), `StepAdapter`.
7. **`core/lineage.py`**: `LineageBundle` + `RunContext` (status="created" serializa sin valores ficticios, DoD F0).
8. **`core/study.py` + `core/__init__.py`**: `Study` (validación pre-run CT-1 → `ArtifactNotFoundError` antes de execute; orden de declaración, scheduler topológico diferido F5; `save`/`load` directorio atómico; `set_audit_sink` recibe el sink ya compuesto; `lineage_bundle` congelado). Validar que `fail_fast=False`/`register_on_success` NO sean no-op silenciosos (warning ruidoso).

Cierre de B1 = primer `Study` end-to-end con lineage reproducible. Luego B2 (`data`), B3, B4 (incl. los **3 criterios del Hito 0**: Step dummy con fan-in CT-1; payload estructurado dummy CT-2; gate `coverage-regulatory` que verifica existencia de paths). Forma de trabajo: **yo-solo + fan-out de lectura**, sin equipo persistente.

## Decisiones / contexto a recordar
- **Decisiones de conflicto ya tomadas (integrador, técnicas):** `MissingDependencyError` vive SOLO en `core/exceptions.py` (otros la importan); `core/config/` = 4 módulos; `assemble_run` → `nikodym/api.py`; `results.py` en F0 = solo Protocols; forward-ref `DataConfig` → `model_rebuild()`; config muerto v1 → warning ruidoso.
- **Gotchas ya implementados en B1a (mantener):** seeding usa `_stable_hash` con `hashlib.sha256` (NUNCA `hash()` builtin ni `spawn()`); entropía compuesta `SeedSequence(entropy=[root_seed, _stable_hash(name)])`; `int_seed_for` deriva un uint32 de la misma SeedSequence; `apply_global` advierte si `PYTHONHASHSEED` no está fijo y NO llama `np.random.seed` legacy.
- **🔧 4 DESVIACIONES de los SDD que el código destapó — RATIFICAR al revisar el SDD (reabrir SDD es esperado y barato):**
  1. **mypy `python_version = "3.12"`** (no 3.11): los stubs de **numpy 2.x** usan PEP 695 (`type X = …`), que mypy solo parsea con target ≥3.12. El runtime 3.11 lo cubren los tests. → SDD-25 §5.
  2. **`EXTRA_TO_DISTRIBUTIONS`**: usar nombres de **import**, no de distribución — `scikit-learn`→`sklearn`, `hydra-core`→`hydra`. Como estaba en el SDD, `require_extra` fallaría siempre. → SDD-25 §4.1.
  3. **Gate `coverage-regulatory`**: el comando exacto del SDD (`--cov=nikodym.core.seeding` por nombre de módulo) **rompe** con numpy 2.x ("cannot load module more than once per process"). Forma robusta usada: `coverage run -m pytest` + `coverage report --include="…exceptions.py,…seeding.py,…cmf/__init__.py,…ifrs9/__init__.py" --fail-under=100`. → SDD-25 §7 (cablear así el job de CI en B4).
  4. **`[tool.ruff.lint.per-file-ignores]`**: `"tests/**" = ["D"]` (los tests no exigen docstring por función). → SDD-24/25.
- **Comandos verde (entorno):** `uv sync --no-default-groups --group test --group lint --python 3.12` (rápido) o `uv sync` (dev completo). Verificar: `uv run --no-sync ruff check . && uv run --no-sync ruff format --check . && uv run --no-sync mypy && uv run --no-sync pytest --cov=nikodym --cov-report=term-missing`.

## Callejones sin salida / no reintentar
- **NO** fijar mypy `python_version="3.11"` con numpy 2.x instalado: rompe al parsear los stubs (PEP 695). Usar 3.12 (ver desviación 1).
- **NO** correr el gate regulatorio con `--cov=nikodym.core.seeding` por **nombre de módulo**: dispara el doble-load de numpy 2.x. Usar `coverage report --include=<rutas>` (desviación 3).
- **NO** reintroducir los 4 claims que la verificación (context7) tumbó en Tanda 1 Rev: `spawn()` posicional (usar entropía compuesta con `hashlib`); sin heredar `BaseEstimator` no pasa `check_estimator` (≥1.6); `DataFrame.eval`/`query` NO son sandbox (mini-DSL declarativo); Model Stages de MLflow deprecados (aliases+tags).
- **NO** hashear bytes de Parquet para `data_hash` (contenido lógico por bloques, `hash_pandas_object`).
- **Workflow JS gotchas**: prompts son template literals — sin backticks internos (usar comillas simples); `${...}` sí; no pasar `run_in_background` (ya corre en background).

## Dudas abiertas / bloqueos (preexistentes, no urgentes)
- **Pendiente normativo CMF:** haircuts/factores de descuento de garantías financieras del B-1 letra c) (en `normativa_cmf_parametros.md` §5.2/§7).
- **Deudas diferidas con owner (Hito 0 §5):** pickle/joblib del `ArtifactStore` → F3; motor topológico DAG → F5; capa de datos longitudinal → F4/F5; matriz CI 3×3 + Hypothesis → F1; `mypy strict` sobre wrappers sin stubs (statsmodels/lifelines) → cast/ignore localizados F1/F5.
- Momento privado→público del repo (al terminar). Alias de email del paquete (`admin@nxlabs.cl` → alias de proyecto) y Trusted Publishing OIDC al armar el release público (F1).

## Repo
Privado en GitHub: **`nexolabs-gh/nikodym`** (https://github.com/nexolabs-gh/nikodym), branch `main`. Push directo a `main` autorizado en el cierre. Commits con co-autoría de Claude.
