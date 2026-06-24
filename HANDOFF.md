# HANDOFF

_Última actualización: 2026-06-24 · repo privado `nexolabs-gh/nikodym` · sobre commit `59aaad3`_

## Estado actual
**Nikodym RiskLib — F0 (Fundación): B1 `core` COMPLETO ✅.** Diseño de Fundación cerrado (Tanda 0/1/1Rev + Hito 0). F0 troceado en 4 bloques: **B1 `core` ✅ (este commit)** · B2 `data` (siguiente) · B3 `audit`+`governance`+`tracking`+`api` · B4 `testing`+CI+3 criterios Hito 0.

**B1 `core` por dentro:** B1a ✅ (esqueleto + `exceptions` + `seeding`) · B1b ✅ (`core/config`) · **B1c ✅ (resto de `core`: audit · results · base/mixins · registry/artifacts · steps · lineage · study)** ← este commit. **Primer `Study` end-to-end con lineage reproducible (DoD F0).**

Regla de oro vigente: **mixto-troncal-más-incremental** — cada módulo: programa → `ruff`+`mypy --strict`+`pytest`+cobertura verde → ajusta → sigue. Nunca avanzar en rojo. Reabrir un SDD por feedback del código es esperado y barato.

## Hecho en esta sesión (B1c · resto de `core`, 9 módulos)
- **`src/nikodym/core/`** 9 módulos nuevos en orden topológico: `audit.py` (`AuditEvent` BaseModel frozen+forbid, `AuditKind` Literal, `AuditSink` Protocol, `NullAuditSink`/`InMemoryAuditSink`/`FanOutSink` CT-4) · `results.py` (Protocols `ProvisionResultLike`/`ECLResultLike` @runtime_checkable, `term_structure()` CT-2, pandas bajo TYPE_CHECKING) · `base.py` (`BaseNikodymEstimator` raíz propia + 6 familias; `get_params`/`set_params`/`from_config`/`_validate_config`/`_check_fitted` semántica sklearn) · `mixins.py` (`AuditableMixin` `_audit` nunca None, `SerializationMixin` save/load joblib + trust) · `registry.py` (`Registry`/`REGISTRY`/`register` namespaced) · `artifacts.py` (`ArtifactStore` (domain,key), emite `AuditEvent("artifact")` en cada escritura) · `steps.py` (`ArtifactKey`, `Step` Protocol CT-1, `StepAdapter`) · `lineage.py` (`LineageBundle`/`RunContext` BaseModel forbid, DoD F0) · `study.py` (`Study` orquestador: motor v1 CT-1, save/load directorio atómico, trust gate, reproducibilidad).
- **Método ultracode:** workflow de comprensión (10 agentes: 7 blueprints + contratos + convenciones + APIs context7) → código por DanIA módulo-a-módulo → **revisión adversarial (workflow 27 agentes, 6 dimensiones → 19 hallazgos confirmados)** → integración por DanIA → **2ª pasada de fidelidad-contrato (workflow → 3 hallazgos)** → integración.
- **Tests:** `tests/unit/test_{audit,results,base_mixins,registry,artifacts,steps,lineage,study}.py` + fixture `PYTHONHASHSEED` autouse movido a `tests/conftest.py`. **230 passed.**
- **Verde total:** `ruff` + `mypy --strict` (23 archivos) + cobertura **100% global** + gate regulatorio **100%** + `uv build` wheel + smoke import aislado + núcleo liviano (core no arrastra pandas/sklearn/mlflow/joblib en runtime).
- **pyproject:** añadidos `pandas-stubs>=2.0` y `joblib.*` (overrides mypy), ambos dev-only. `uv.lock` actualizado.

## En curso / a medias
Nada a medias. B1c cerrado y verde. Working tree = los 9 módulos + 8 tests + conftest + pyproject/uv.lock + __init__ (este commit).

## Próximos pasos
**Arrancar B2 = capa `data` (SDD-02).** Es un sub-bloque independiente → **buen momento para sesión fresca** (este HANDOFF es el puente; warm start). Leer primero `docs/design/02-data.md` y `_CONTRATOS-TRANSVERSALES.md` (CT-3: frontera transversal scorecard vs longitudinal IFRS9/forward).
- B2 endurece el placeholder `NikodymConfig.data` (hoy `Any`=None) a `DataConfig | None` vía `model_rebuild()` al importar `nikodym.data` (con `data=None` el golden `config_hash` NO cambia).
- `data_hash` = hash del contenido lógico por bloques (`hash_pandas_object`), NO bytes Parquet (D2). El campo ya existe en `LineageBundle`; el cálculo vive en `data/`.
- Deps base de `data`: pandas (ya), **pandera + pyarrow** (declaradas en overrides mypy, faltan instalar/usar).
- Método sugerido (validado): fan-out de comprensión (APIs con context7) → código por DanIA → revisión adversarial → integración.

Tras B2: B3 (audit/governance/tracking/api, incl. `assemble_run` CT-4 y `ModelInventory`) → B4 (testing+CI+3 criterios Hito 0). Luego T2 diseño scoring → F1 código → release público v0.1.0.

## Decisiones / contexto a recordar
- **Decisiones de integrador B1c (técnicas; ratificar al revisar SDD):**
  - **steps/study**: la resolución config→pasos y `StepAdapter.execute` se **difieren a T2** (F0 no tiene secciones de dominio orquestables) — diferido RUIDOSO (`ConfigError`/`NotImplementedError`, nunca no-op silencioso). El motor CT-1 (`_validate_pipeline` pre-run global + `_check_prerequisites` por paso) SÍ está implementado y probado con pipelines dummy vía monkeypatch del seam `_resolve_steps`.
  - **`register_on_success` NO implementado**: el campo no existe en `RunConfig` (solo `steps`/`fail_fast`); el warning ruidoso se difiere hasta que el campo exista (deuda). `fail_fast=False` SÍ → warning ruidoso.
  - **study**: `name` override vía `config.model_copy`; `run(steps=)` > `config.run.steps`; `lineage_bundle()` en `created` → `NikodymError`; `load(trust=False)` con artefactos joblib → `UntrustedStudyError`; `config_hash` mismatch al recargar → `ReproducibilityError` (detecta divergencia ACCIDENTAL, no manipulación maliciosa — documentado); `uv_lock_hash`/`data_hash` = None en F0.
  - **lineage**: `LineageBundle`/`RunContext` sin `frozen` (RunContext muta en run()), con `extra="forbid"`. `AuditEvent` frozen+forbid.
  - **seeding (reabierto)**: `apply_global` ahora propaga `PYTHONHASHSEED` a subprocesos vía `os.environ` (SDD-01 §9, antes faltaba).
- **Hallazgos de las 2 revisiones adversariales CERRADOS en B1c (mantener):**
  - Corrida fallida ahora **conserva el lineage** (se inicia tras `run_start`, orden SDD §7.3: run_start → iniciar bundle) → evidencia SR 11-7 no se pierde en fallo.
  - `save` **atómico real**: aparta el destino previo a un respaldo lateral antes del swap y lo restaura si falla (antes hacía rmtree(destino) antes de os.replace → ventana de pérdida).
  - `set_params` anidado sobre no-estimador → `ConfigError` (antes `AttributeError` crudo, violaba "todo desciende de NikodymError").
  - `git_dirty`/git-ausente → caveat en `determinism_caveats` (working tree sucio = no reproducible-garantizado).
  - `_emit` tipado con `AuditKind` → eliminado el único `# type: ignore` del core.
  - `StepAdapter.domain` eliminado (superficie extra no contractual; `name` es la única fuente).
- **Desviaciones de SDD a ratificar (acumuladas):** las 4 de B1a + 3 de B1b + B1c: `pandas-stubs`/`joblib.*` overrides; `StepAdapter.__init__` añade `*, requires/provides` (mecanismo de derivación I/O diferido a SDD-06+); resolución de pasos diferida a T2.
- **Comandos verde:** `uv sync --no-default-groups --group test --group lint --python 3.12`. Verificar: `uv run --no-sync ruff check . && uv run --no-sync ruff format --check . && uv run --no-sync mypy && uv run --no-sync pytest -q --cov=nikodym --cov-report=term-missing`. Gate regulatorio: `coverage run -m pytest` + `coverage report --include="*/nikodym/core/exceptions.py,*/nikodym/core/seeding.py,*/nikodym/provisioning/cmf/__init__.py,*/nikodym/provisioning/ifrs9/__init__.py" --fail-under=100`.

## Callejones sin salida / no reintentar
- **NO** correr cobertura por submódulo (`--cov=nikodym.core.audit` etc.) → doble-load numpy 2.x ("cannot load module more than once"). Usar `--cov=nikodym` (paquete entero) y mirar el reporte por archivo, o el gate regulatorio con `--include=<rutas>`.
- **`apply_global` advierte sobre `PYTHONHASHSEED`** si no está fijo → con `filterwarnings=error` rompe cualquier test que construya un `Study`. Cubierto por el fixture autouse `_pythonhashseed_fijo` en `tests/conftest.py` (setea "0"); los tests del seeding que prueban el aviso hacen `monkeypatch.delenv` en su cuerpo.
- **`ArtifactStore.keys()` dispara `SIM118`** (ruff cree que es `dict.keys()`); es método propio → `# noqa: SIM118` puntual.
- **mypy 3.12** (no 3.11) por stubs numpy 2.x. **NO** fijar 3.11.
- **Colisión módulo/función `migration`** (B1b): `import nikodym.core.config.migration` agarra el decorador; usar `from ... import X` para los privados.
- **Workflow JS gotchas:** `parallel()` ya devuelve `Promise<array>` (NO envolver en `Promise.all`); prompts son template literals (sin backticks internos); `Date.now()`/`Math.random()` prohibidos.

## Dudas abiertas / bloqueos (preexistentes, no urgentes)
- **Pendiente normativo CMF:** haircuts/factores de descuento de garantías financieras del B-1 letra c) (`normativa_cmf_parametros.md` §5.2/§7) → F3.
- **Deudas con owner (Hito 0 §5):** pickle/joblib del `ArtifactStore` → F3; motor topológico DAG (scheduler) → F5; capa datos longitudinal → F4/F5; matriz CI 3×3 + Hypothesis → F1; `assemble_run`/`ModelInventory` (CT-4) → B3 (api/runner, fuera de core).
- **T2 (al materializar StepAdapter.execute):** propagar `_audit` al estimador envuelto (`paso.estimator`), o sus `log_decision` caen al NullAuditSink (TODO anclado en `study.py:_run_one`); fijar el mecanismo de derivación de `requires`/`provides` por dominio (SDD-06+).
- Momento privado→público del repo (al terminar). Alias de email del paquete y Trusted Publishing OIDC al armar el release público (F1).

## Repo
Privado en GitHub: **`nexolabs-gh/nikodym`** (https://github.com/nexolabs-gh/nikodym), branch `main`. Push directo a `main` autorizado en el cierre. Commits con co-autoría de Claude.
