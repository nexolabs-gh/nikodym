# HANDOFF

_Última actualización: 2026-06-24 · repo privado `nexolabs-gh/nikodym` · sobre commit `1067afa`_

## 🤖 Modo autónomo (rutina)
**Estado:** `IDLE`  _(IDLE = libre · `RUNNING [ts]` = corrida en curso. El lock de OS del wrapper garantiza exclusión; un `RUNNING` visto al arrancar = corrida muerta → rescatar, no abortar.)_
Última corrida: 2026-06-24 20:53 · ítem **B2b.2** · `bdbea17` · ✓ HECHO _(rescate del maestro DanIA en vivo; la 1ª corrida headless se cortó por monitor en background — prompt corregido)_
Ciclo en la skill **auto-desarrollo** §2 (rescate §4); playbook en `docs/AUTONOMY.md`; bitácora en `AUTONOMY-LOG.md`. Worker Codex en tmux `nikodym`; maestro fresco por cron horario (:17).

## Backlog priorizado (cola autónoma)
> La rutina consume esto en orden, de arriba a abajo. Marca `[x]` al terminar; **NO** borres ni renumeres.
> Cada ítem es autocontenido = un módulo + sus tests, dejando los 4 gates verdes (cobertura 100%). El worker
> deja el árbol verde **sin commitear**; el maestro revisa, commitea y pushea (R7).
1. [x] **B2b.1** — `data/loading.py` (`DataLoader`): CSV/Parquet + passthrough de DataFrame con copia defensiva, `engine="pyarrow"` explícito, `backend="polars"` perezoso, `from_config`. SDD-02 §4. + `tests/unit/test_data_loading.py`. ✓ `6d699e2` (266 tests, 100%).
2. [x] **B2b.2** — `data/schema.py` (`SchemaValidator`): `SchemaConfig`→`pa.DataFrameSchema` (`import pandera.pandas as pa`), `validate(df, lazy=True)`→`DataValidationError` (reporte español). SDD-02 §7. ✓ `bdbea17` (282 tests, 100%). _Nota ratificada: `index_col`=nombre del índice existente (no `set_index`); `SchemaValidator` no exportado en `data.__init__`._
3. [ ] **B2b.3** — `data/hashing.py` (`data_hash`): sha256 por bloques (`hash_pandas_object`), **endianness `<u8` explícito**, `-0.0→0.0`, `index=True`, defaults `hash_key`/`encoding`, golden cross-versión. SDD-02.
4. [ ] **B2b.4** — `data/special.py` (`SpecialValuePolicy`): centinelas→NaN + `special_mask` + `special_catalog`. SDD-02.
5. [ ] **B2c.1** — `data/target.py` (definición de target/etiqueta). SDD-02.
6. [ ] **B2c.2** — `data/partition.py` (`PartitionStrategy`: temporal/random/cohort) con **Hypothesis** para determinismo y anti-leakage. SDD-02.
7. [ ] **B2d** — `data/step.py` (`DataStep @register(domain="data")`) + `Study.run(steps=["data"])` end-to-end de datos. SDD-02 + CT-1.
8. [ ] **B3.1** — integración `audit`/`governance`/`tracking`/`api` (cableado + `assemble_run`/`ModelInventory`, CT-4). SDD-03.
9. [ ] **B4** — `testing` + CI (`.github/workflows`, matriz) + 3 criterios de cierre del Hito 0.

## Estado actual
**Nikodym RiskLib — F0 (Fundación): B1 `core` ✅ + B2a `data` (config) ✅ COMPLETOS.** F0 troceado en 4 bloques: B1 `core` ✅ · **B2 `data` EN CURSO (B2a ✅, B2b.1 ✅, B2b.2 ✅, sigue B2b.3)** · B3 `audit`+`governance`+`tracking`+`api` · B4 `testing`+CI+3 criterios Hito 0.

**B2 por dentro:** B2a ✅ (config) · **B2b EN CURSO** (B2b.1 `loading` ✅ `6d699e2` · B2b.2 `schema` ✅ `bdbea17` · sigue B2b.3 `hashing` · B2b.4 `special`) · B2c (target·partition) · B2d (card·step, `Study` end-to-end de datos).

Regla de oro vigente: **mixto-troncal-más-incremental** — cada módulo: programa → `ruff`+`mypy --strict`+`pytest`+cobertura verde → ajusta → sigue. Nunca avanzar en rojo. Reabrir un SDD por feedback del código es esperado y barato (este bloque reabrió 2 mecanismos del SDD-02 §5, ver abajo).

## Hecho en esta sesión (B2a · config + endurecimiento de `data`)
- **`src/nikodym/data/config.py`** (NUEVO): árbol Pydantic completo de `DataConfig` (SDD-02 §5) — `CsvOptions`/`LoadingConfig` · `ColumnSpec`/`SchemaConfig` · `PerformanceWindow` · mini-DSL `Predicate`/`Rule`/`ExclusionRule` (allowlist cerrada de operadores, **sin `eval`/`df.eval`**, D-DATA-6) · `TargetConfig` · `SpecialValueSpec`/`MissingConfig` · `TemporalSplitConfig`/`RandomSplitConfig`/`CohortSplitConfig` + `PartitionStrategy` (unión discriminada **anidada** por factory local) + `PartitionConfig` · `DataConfig` (alias `schema` + `populate_by_name`). `model_validator`: fracciones random suman 1.0, `Rule` no vacía.
- **`src/nikodym/data/__init__.py`** (NUEVO): registra `DataConfig` en el hook `_DATA_CONFIG_CLS` de `core/config/schema` al importarse.
- **`src/nikodym/core/config/schema.py`** (endurecido): `data: Any` → `DataConfig | None`. Patrón verificado: `if TYPE_CHECKING: data: DataConfig | None` (vista mypy estricta) / `else: data: Any` (runtime) + `field_validator("data", mode="before")` que coacciona vía el hook. Quitado el viejo `_data_json_canonica` (su protección JSON-canónica se conserva como fallback cuando el hook es None = core en solitario).
- **`pyproject.toml`**: pisos `pandera>=0.24` (obliga `import pandera.pandas`) y `pyarrow>=14`. `uv.lock` actualizado (instalados pandera 0.32, pyarrow 24).
- **`.gitignore`**: `data/` → `/data/` (anclado a raíz). **Bug cazado**: `data/` ignoraba el paquete fuente `src/nikodym/data/` → git no lo trackeaba (se habría perdido al commitear), el wheel lo excluía, y **ruff lo saltaba** (respeta .gitignore) → "verde" falso. Lo descubrí inspeccionando el wheel.
- **Tests**: `tests/unit/test_data_config.py` (NUEVO, 19 tests: estructura, alias, unión discriminada, model_validators, integración con `NikodymConfig` vía hook, golden `config_hash`, round-trip YAML). Fixtures autouse `_vista_core_solo` (monkeypatch hook=None) añadidas a `test_config_schema.py` y `test_config_loader.py` para aislar la vista core-only (el hook es process-wide).
- **Verde total**: `ruff` + `ruff format` + `mypy --strict` (25 archivos) + **249 tests** + **cobertura 100%** global + gate regulatorio 100% + `uv build` (wheel incluye `nikodym/data/`) + núcleo liviano (`import nikodym.core` NO arrastra `data`/pandera/pyarrow/pandas, verificado). Golden `config_hash` por defecto **invariante** (`02b667fc…`).

## En curso / a medias
Nada a medias. B2a cerrado y verde.

## Próximos pasos
**Arrancar B2b = primitivas de `data` (sin orquestación)** — leer primero `docs/design/02-data.md` §4/§7/§10 (ya leído íntegro esta sesión) y el bloque de hallazgos de comprensión (workflow guardado, ver abajo). Método sugerido (validado): fan-out de comprensión con context7 → código por DanIA módulo-a-módulo → revisión adversarial.
- **`loading.py`** (`DataLoader`): carga CSV/Parquet, passthrough de DataFrame en memoria con copia defensiva; `engine="pyarrow"` explícito (no 'auto'); `backend="polars"` opcional con import perezoso. `from_config`.
- **`schema.py`** (`SchemaValidator`): builder `DataConfig.schema_` → `pa.DataFrameSchema` (`import pandera.pandas as pa`); `validate(df, lazy=True)` → captura `pa.errors.SchemaErrors` → re-empaqueta en **`DataValidationError`** (de `core.exceptions`) con reporte en español. no-nulos = `nullable=False` (NO un Check); unicidad = `unique=`/`unique=[...]`.
- **`hashing.py`** (`data_hash`): sha256 del contenido lógico por bloques (`hash_pandas_object`, D2). **Fix de endianness obligatorio**: usar `.astype('<u8').tobytes()` (little-endian explícito), NO `.values.tobytes()` (endian-nativo, no reproducible cross-arquitectura). Normalizar `-0.0→0.0`. Defaults explícitos `hash_key`/`encoding`. Golden-test cross-versión. `index=True` (en Nikodym el índice ES el identificador de observación).
- **`special.py`** (`SpecialValuePolicy`): centinelas → NaN + `special_mask` + `special_catalog`.
- Cada módulo con sus tests canónicos + golden values. Apuntar a cobertura 100% (gate formal de `data` es global ≥90, pero mantener el estándar del proyecto).

Tras B2b: B2c (target·partition, con Hypothesis para determinismo/anti-leakage) → B2d (card·step, `DataStep @register(domain="data")`, `Study.run(steps=["data"])` end-to-end). Luego B3 → B4 → T2 scoring → F1 → release v0.1.0.

## Decisiones / contexto a recordar
- **Desviaciones de SDD-02 a ratificar (B2a; integrador):**
  - **`model_rebuild()` del SDD §5 NO funciona**: Pydantic 2.13 no re-narra un campo ya resuelto (probado: placeholder `Any` o modelo dummy → `model_rebuild(force=True)` con namespace explícito NO intercambia el tipo). Reemplazo: **hook `_DATA_CONFIG_CLS` (módulo `schema`) + `field_validator`**; `nikodym.data` lo puebla al importarse. Más robusto (valida en construcción) y mantiene el núcleo liviano.
  - **`Predicate.value` SIN `strict=True`**: `Field(strict=True)` revienta sobre una unión en Pydantic 2.13 (`Unable to apply constraint 'strict' to schema of type 'union'`) y rompería list→tuple del round-trip. El **modo unión smart** (default) + orden `bool|int|float` ya evita la coerción que el SDD buscaba (verificado: `True`→bool, `1`→int, `[1,2,3]`→tuple).
  - **Defaults de `Field` en keyword `default=`** (no posicional): mypy sin plugin pydantic no reconoce un default posicional → cree que el modelo requiere args → rompe `default_factory=Clase`. Coherente con el core.
  - **`pandera>=0.24` con `import pandera.pandas as pa`** (NO `import pandera`): el top-level emite `FutureWarning` desde 0.24 → con `filterwarnings=["error"]` rompe los tests. **`pyarrow>=14`**.
  - Acumuladas previas (B1): `pandas-stubs`/`joblib.*` overrides; `StepAdapter` `*, requires/provides`; resolución de pasos diferida a T2; `mypy` en 3.12 no 3.11.
- **Hook `_DATA_CONFIG_CLS` (cómo razonar sobre tests):** es global de proceso. Al colectar, cualquier test que importe `nikodym.data` lo deja seteado para toda la sesión. Los tests core-only (`test_config_schema`, `test_config_loader`) lo neutralizan con `monkeypatch.setattr(schema, "_DATA_CONFIG_CLS", None)`; `test_data_config` lo fija a `DataConfig`. Con hook None → `data` es blob JSON-canónico opaco; con hook seteado → se coacciona a `DataConfig` (extra=forbid).

## Callejones sin salida / no reintentar
- **NO usar `model_rebuild()` para narrar `NikodymConfig.data`** — no funciona en Pydantic 2.13 (ver arriba). El hook+validador es la vía.
- **NO `Field(strict=True)` sobre uniones** en Pydantic 2.13 — usar el modo smart (default).
- **NO defaults posicionales en `Field(...)`** si el modelo es target de `default_factory` — keyword `default=`.
- **`ruff` respeta `.gitignore`**: si un paquete fuente cae bajo un patrón ignorado, ruff lo SALTA silenciosamente (verde falso). Verificar el wheel/`git status` cuando se añade un subpaquete nuevo. El patrón de datos es `/data/` (raíz), no `data/`.
- **NO `import pandera as pa`** (top-level) — `FutureWarning` rompe con `filterwarnings=error`. Usar `import pandera.pandas as pa`.
- Heredados de B1 (siguen vigentes): NO cobertura por submódulo (`--cov=nikodym.core.audit` → doble-load numpy); `ArtifactStore.keys()` → `# noqa: SIM118`; colisión módulo/función `migration` (usar `from ... import X`); workflow JS: `parallel()` ya devuelve array, prompts sin backticks internos, `Date.now()`/`Math.random()` prohibidos.

## Comandos verde
- Sync: `uv sync --no-default-groups --group test --group lint --python 3.12`
- Verificar: `uv run --no-sync ruff check . && uv run --no-sync ruff format --check . && uv run --no-sync mypy && uv run --no-sync pytest -q --cov=nikodym --cov-report=term-missing`
- Gate regulatorio (100%): `uv run --no-sync coverage run -m pytest && uv run --no-sync coverage report --include="*/nikodym/core/exceptions.py,*/nikodym/core/seeding.py,*/nikodym/provisioning/cmf/__init__.py,*/nikodym/provisioning/ifrs9/__init__.py" --fail-under=100`
- Liviano: `uv run --no-sync python -c "import nikodym.core, sys; assert not [m for m in ('nikodym.data','pandera','pyarrow','pandas') if m in sys.modules]"`

## Dudas abiertas / bloqueos (preexistentes, no urgentes)
- **Pendiente normativo CMF:** haircuts/factores de descuento de garantías financieras del B-1 letra c) → F3.
- **Deudas con owner (Hito 0 §5):** pickle/joblib del `ArtifactStore` → F3; motor topológico DAG → F5; capa datos longitudinal → F4/F5; matriz CI 3×3 + Hypothesis → F1; `assemble_run`/`ModelInventory` (CT-4) → B3.
- **T2 (al materializar `StepAdapter.execute`):** propagar `_audit` al estimador envuelto; fijar derivación de `requires`/`provides` por dominio (SDD-06+).
- **Plugin mypy de pandera** (`plugins=["pandera.mypy"]`): NO se añadió en B2a (config.py es Pydantic puro). Decidir en B2b si hace falta al importar pandera (probablemente no, usamos `DataFrameSchema` imperativo, no `DataFrameModel`).
- Momento privado→público del repo (al terminar). Alias de email y Trusted Publishing OIDC en el release público (F1).

## Repo
Privado en GitHub: **`nexolabs-gh/nikodym`** (https://github.com/nexolabs-gh/nikodym), branch `main`. Push directo a `main` autorizado en el cierre. Commits con co-autoría de Claude.
