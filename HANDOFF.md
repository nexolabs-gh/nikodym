# HANDOFF

_Última actualización: 2026-06-24 · repo privado `nexolabs-gh/nikodym` · sobre commit `3ea9523`_

## 🤖 Modo autónomo (rutina)
**Estado:** `IDLE`  _(IDLE = libre · `RUNNING [ts]` = corrida en curso. El lock de OS del wrapper garantiza exclusión; un `RUNNING` visto al arrancar = corrida muerta → rescatar, no abortar.)_
Última corrida: 2026-06-24 22:42 · ítem **B2c.1** · `3ea9523` · ✓ HECHO _(corrida headless DanIA; 332 tests, 100%, gates verdes. Monitor por polling corto en primer plano (ciclos acotados ~75-90s que retornan) → esquivó el auto-background del harness; worker idle en ~9 min. `TargetConfig` y los modelos del mini-DSL ya existían en `config.py` (B2a) → esta corrida solo creó `target.py` + tests.)_
Ciclo en la skill **auto-desarrollo** §2 (rescate §4); playbook en `docs/AUTONOMY.md`; bitácora en `AUTONOMY-LOG.md`. Worker Codex en tmux `nikodym`; maestro fresco por cron horario (:17).

## Backlog priorizado (cola autónoma)
> La rutina consume esto en orden, de arriba a abajo. Marca `[x]` al terminar; **NO** borres ni renumeres.
> Cada ítem es autocontenido = un módulo + sus tests, dejando los 4 gates verdes (cobertura 100%). El worker
> deja el árbol verde **sin commitear**; el maestro revisa, commitea y pushea (R7).
1. [x] **B2b.1** — `data/loading.py` (`DataLoader`): CSV/Parquet + passthrough de DataFrame con copia defensiva, `engine="pyarrow"` explícito, `backend="polars"` perezoso, `from_config`. SDD-02 §4. + `tests/unit/test_data_loading.py`. ✓ `6d699e2` (266 tests, 100%).
2. [x] **B2b.2** — `data/schema.py` (`SchemaValidator`): `SchemaConfig`→`pa.DataFrameSchema` (`import pandera.pandas as pa`), `validate(df, lazy=True)`→`DataValidationError` (reporte español). SDD-02 §7. ✓ `bdbea17` (282 tests, 100%). _Nota ratificada: `index_col`=nombre del índice existente (no `set_index`); `SchemaValidator` no exportado en `data.__init__`._
3. [x] **B2b.3** — `data/hashing.py` (`data_hash`): sha256 por bloques (`hash_pandas_object`), **endianness `<u8` explícito**, `-0.0→0.0`, `index=True`, defaults `hash_key`/`encoding`, golden cross-versión. SDD-02. ✓ `c7edaca` (293 tests, 100%). _Ratificado: ordena por índice (`sort_index` estable) → invariante a permutación de filas; eleva O(n) §7 a O(n log n), aceptado. Header de esquema versionado `nikodym.data_hash.v1`. No exportado en `data.__init__`._
4. [x] **B2b.4** — `data/special.py` (`SpecialValuePolicy`): centinelas→NaN + `special_mask` + `special_catalog`. SDD-02. ✓ `cf2487a` (302 tests, 100%). _Detección type-safe por dtype (evita FutureWarning con `filterwarnings=error`); `label` de `SpecialValueSpec` NO se propaga al `MaskedFrame` (catálogo = columna→centinelas, fiel a §4) → binning/SDD-06 releerá la config. No exportado en `data.__init__`._
5. [x] **B2c.1** — `data/target.py` (`TargetDefinition`): mini-DSL declarativo (allowlist cerrada de operadores, sin `eval`) → `target` `Int8` 1/0/NA + `label_status` categórico; precedencia exclusión>indeterminado>malo>bueno; ventana de desempeño no madurada→`excluido(ventana_incompleta)`. SDD-02 §4/§7. ✓ `3ea9523` (332 tests, 100%). _Consume `TargetConfig`/`Predicate`/`Rule`/`ExclusionRule`/`PerformanceWindow` ya existentes (B2a); valida compatibilidad dtype↔valor ANTES de comparar (lección B2b.4); `LabeledFrame`/`TargetDefinition` NO exportados en `data.__init__` (se cablea en B2d)._
6. [ ] **B2c.2** — `data/partition.py` (`PartitionStrategy`: temporal/random/cohort) con **Hypothesis** para determinismo y anti-leakage. SDD-02.
7. [ ] **B2d** — `data/step.py` (`DataStep @register(domain="data")`) + `Study.run(steps=["data"])` end-to-end de datos. SDD-02 + CT-1.
8. [ ] **B3.1** — integración `audit`/`governance`/`tracking`/`api` (cableado + `assemble_run`/`ModelInventory`, CT-4). SDD-03.
9. [ ] **B4** — `testing` + CI (`.github/workflows`, matriz) + 3 criterios de cierre del Hito 0.

## Estado actual
**Nikodym RiskLib — F0 (Fundación): B1 `core` ✅ + B2a `data` (config) ✅ COMPLETOS.** F0 troceado en 4 bloques: B1 `core` ✅ · **B2 `data` EN CURSO (B2a ✅, B2b ✅, B2c en curso)** · B3 `audit`+`governance`+`tracking`+`api` · B4 `testing`+CI+3 criterios Hito 0.

**B2 por dentro:** B2a ✅ (config) · B2b ✅ COMPLETO (B2b.1 `loading` `6d699e2` · B2b.2 `schema` `bdbea17` · B2b.3 `hashing` `c7edaca` · B2b.4 `special` `cf2487a`) · **B2c EN CURSO** (B2c.1 `target` ✅ `3ea9523` · sigue B2c.2 `partition`) · B2d (`card`·`step`, `Study` end-to-end de datos).

Regla de oro vigente: **mixto-troncal-más-incremental** — cada módulo: programa → `ruff`+`mypy --strict`+`pytest`+cobertura verde → ajusta → sigue. Nunca avanzar en rojo. Reabrir un SDD por feedback del código es esperado y barato.

## Hecho en la última corrida (B2c.1 · `data/target.py`)
- **`src/nikodym/data/target.py`** (NUEVO): `TargetDefinition` (+ `LabeledFrame`/`TargetSummary` Pydantic, `arbitrary_types_allowed=True`). `apply(df, *, audit=None) -> LabeledFrame` etiqueta sobre **copia defensiva** (`df.copy(deep=True)`) agregando `target` (`Int8` nullable: 1=malo, 0=bueno, `pd.NA` fuera de modelado) y `label_status` (categórico `bueno`/`malo`/`indeterminado`/`excluido`). **Mini-DSL propio** (`_eval_rule`/`_eval_predicate`) evalúa `Rule = (AND all_of) AND (OR any_of)` con **allowlist cerrada** `_ALLOWED_OPS` (`==,!=,<,<=,>,>=,in,notin,isna,notna`), **sin `eval`**. **Precedencia** exclusión>indeterminado>malo>bueno; las máscaras se computan sobre el `df` **original** (no el ya etiquetado) → reproducible. Ventana de desempeño: `observation_date + months > data_cutoff` ⇒ `excluido(ventana_incompleta)` (exige columnas datetime, si no → `DataValidationError`). `TargetSummary` (conteos por clase, `bad_rate`, `exclusions_by_reason`, `ambiguous_rows`); emite `audit.emit(AuditEvent(kind="decision", …))` por exclusión y por resolución de ambigüedad.
- **Validación type-safe (lección B2b.4):** `_validate_value_compatible` rechaza comparar valor vs dtype incompatible (numérico vs datetime/string/bool, etc.) con `ConfigError` **antes** de `.eq/.lt/…`, evitando el `FutureWarning` que rompería con `filterwarnings=error`; resultados con NA absorbidos vía `.fillna(False).astype("bool")`. Errores: regla vacía / columna inexistente / operador fuera de allowlist / value incompatible → `ConfigError`; clase vacía (cero buenos o cero malos) y colisión de columnas de salida → `DataValidationError`. Ambigüedad (fila matchea varias reglas) NO es error: se resuelve por precedencia y se cuenta en `summary`.
- **`tests/unit/test_data_target.py`** (NUEVO, 30 tests): golden de clases/summary/auditoría + no-mutación (`assert_frame_equal`), invariante target-no-nulo⇔bueno/malo, ventana incompleta, fecha no-datetime/inexistente, clase vacía, columna inexistente, operador fuera de allowlist, regla vacía, value incompatible, **11 parametrizaciones de dtypes incompatibles sin warning**, object/categórico/string compatibles, object vacío, colisión de columnas.
- **Verde total** (corrido y verificado por el maestro, R7): `ruff` + `ruff format` (54) + `mypy --strict` (30 archivos) + **332 tests** + **cobertura global 100%** (target.py 269 stmts 100%) + gate regulatorio 100% + `uv build` + núcleo liviano.
- El worker Codex dejó el árbol verde **sin commitear**; el maestro revisó el diff, commiteó (`3ea9523`) y pusheó a `main`.

## En curso / a medias
Nada a medias. B2c.1 cerrado, commiteado (`3ea9523`) y pusheado; árbol limpio y verde. **B2c EN CURSO** (target ✅; sigue partition).

## Próximos pasos
**Siguiente ítem del backlog: B2c.2 `data/partition.py`** (`PartitionStrategy`: temporal/random/cohort). SDD-02. Leer primero la sección de particiones/partición del SDD-02 (`docs/design/02-data.md`). Método validado: leer el SDD de la sección → worker Codex fresco módulo-a-módulo → revisión + 4 gates + push por el maestro (R7).
- **`partition.py`**: estrategias de partición train/test (y/o folds) **temporal**, **random** y **cohort**, deterministas por semilla. Usar **Hypothesis** para propiedades de determinismo (misma semilla → misma partición) y **anti-leakage** (sin solapamiento entre splits; en temporal, el train precede al test). Copia defensiva, sin mutar el df del caller; tests canónicos + golden, cobertura 100%. Revisar si consume una `PartitionConfig` ya presente en `data/config.py` (como pasó con `TargetConfig` en B2c.1) antes de definir config nueva.

Tras B2c.2: B2d (`data/step.py`: `DataStep @register(domain="data")`, `Study.run(steps=["data"])` end-to-end de datos). Luego B3 → B4 → T2 scoring → F1 → release v0.1.0.

## Decisiones / contexto a recordar
- **B2c.1 `TargetDefinition` — decisiones SDD-02 §4/§6/§7:** (a) **alcance reducido**: `TargetConfig`/`PerformanceWindow`/`Predicate`/`Rule`/`ExclusionRule` YA existían en `data/config.py` (B2a) y `DataConfig.target` también → la corrida solo creó `target.py` + tests, sin tocar config. (b) **mini-DSL sin `eval`**: evaluador propio con allowlist cerrada de 10 operadores; `Rule = (AND all_of) AND (OR any_of)`; un `else` defensivo cubre el caso imposible post-validación (`# pragma: no cover`). (c) **precedencia** exclusión>indeterminado>malo>bueno aplicada en orden; la primera exclusión que matchea gana el motivo en `exclusions_by_reason`. (d) **filas no clasificadas** (con `good_rule` explícita y sin match de ninguna clase) → `indeterminado` (target NA), conservador. (e) `target` `Int8` nullable + `label_status` `pd.Categorical` con categorías fijas. (f) `_validate_output_columns` impide sobrescribir columnas del cliente (`DataValidationError`). (g) `LabeledFrame`/`TargetDefinition`/`TargetSummary` con `__all__` propio pero NO reexportados en `data/__init__.py` (se cablea en B2d, coherente con schema/hashing/special).
- **B2b.4 `SpecialValuePolicy` — decisiones SDD-02 §4/§7:** (a) **detección type-safe por dtype** (`_is_comparable`): NO se compara un centinela contra columna de dtype incompatible (sentinel numérico vs `datetime`/`string`, o cualquier sentinel vs `bool`) — necesario porque `filterwarnings=error` convierte el `FutureWarning` de comparación cross-dtype en fallo. (b) El **`label`** de `SpecialValueSpec` **NO se propaga** al `MaskedFrame`: `special_catalog` es `columna→[centinelas]` (fiel a la firma §4); el mapeo centinela→`label` lo hará binning (SDD-06) releyendo la config — anotado para que SDD-06 no lo asuma resuelto aquí. (c) Centinelas detectados sobre el `df` **original**, no sobre el frame ya parcialmente reemplazado. (d) `MaskedFrame` Pydantic con `arbitrary_types_allowed=True`. (e) NO exportado en `data/__init__.py`.
- **B2b.3 `data_hash` — ratificaciones SDD-02 §4/§7/§9:** (a) `data_hash` **ordena por índice** internamente (`sort_index(mergesort)`) → hash invariante a permutación de filas con el mismo índice (el índice ES el id de observación, §9); esto eleva la complejidad O(n) de §7 a **O(n log n)** por el sort — aceptado. (b) **Endianness `<u8` explícito** sustituye el `.values.tobytes()` (endian-nativo) del pseudocódigo §4. (c) Normalización `-0.0→0.0` + pin de `hash_key`/`encoding`/`categorize`. (d) Header de esquema **versionado** `nikodym.data_hash.v1`. (e) `data_hash` NO se exporta en `data/__init__.py`.
- **Desviaciones de SDD-02 a ratificar (B2a; integrador):**
  - **`model_rebuild()` del SDD §5 NO funciona**: Pydantic 2.13 no re-narra un campo ya resuelto. Reemplazo: **hook `_DATA_CONFIG_CLS` (módulo `schema`) + `field_validator`**; `nikodym.data` lo puebla al importarse.
  - **`Predicate.value` SIN `strict=True`**: `Field(strict=True)` revienta sobre una unión en Pydantic 2.13 y rompería list→tuple del round-trip. El **modo unión smart** (default) + orden `bool|int|float` ya evita la coerción.
  - **Defaults de `Field` en keyword `default=`** (no posicional): mypy sin plugin pydantic no reconoce un default posicional.
  - **`pandera>=0.24` con `import pandera.pandas as pa`** (NO `import pandera`): el top-level emite `FutureWarning` desde 0.24. **`pyarrow>=14`**.
  - Acumuladas previas (B1): `pandas-stubs`/`joblib.*` overrides; `StepAdapter` `*, requires/provides`; resolución de pasos diferida a T2; `mypy` en 3.12 no 3.11.
- **Hook `_DATA_CONFIG_CLS` (cómo razonar sobre tests):** es global de proceso. Al colectar, cualquier test que importe `nikodym.data` lo deja seteado para toda la sesión. Los tests core-only (`test_config_schema`, `test_config_loader`) lo neutralizan con `monkeypatch.setattr(schema, "_DATA_CONFIG_CLS", None)`; `test_data_config` lo fija a `DataConfig`. Con hook None → `data` es blob JSON-canónico opaco; con hook seteado → se coacciona a `DataConfig` (extra=forbid).

## Callejones sin salida / no reintentar
- **NO comparar valor vs columna de dtype incompatible sin guardia** (B2b.4 + B2c.1) — `series.eq(x)` / `.lt(x)` cross-dtype (numérico vs `datetime`/`string`/`bool`, value escalar vs `category` ordenada, etc.) emite `FutureWarning` → rompe con `filterwarnings=error`. Filtrar por dtype ANTES de comparar (`_is_comparable` en special, `_validate_value_compatible` en target) y `comparison.fillna(False).astype(bool)` para absorber el NA del resultado.
- **NO usar `model_rebuild()` para narrar `NikodymConfig.data`** — no funciona en Pydantic 2.13. El hook+validador es la vía.
- **NO `Field(strict=True)` sobre uniones** en Pydantic 2.13 — usar el modo smart (default).
- **NO defaults posicionales en `Field(...)`** si el modelo es target de `default_factory` — keyword `default=`.
- **`ruff` respeta `.gitignore`**: si un paquete fuente cae bajo un patrón ignorado, ruff lo SALTA silenciosamente (verde falso). Verificar el wheel/`git status` cuando se añade un subpaquete nuevo. El patrón de datos es `/data/` (raíz), no `data/`.
- **NO `import pandera as pa`** (top-level) — `FutureWarning` rompe con `filterwarnings=error`. Usar `import pandera.pandas as pa`.
- **NO `.values.tobytes()` para hashes reproducibles** (B2b.3) — es endian-NATIVO. Forzar little-endian: `hash_pandas_object(...).to_numpy(dtype="<u8", copy=True).tobytes()`. Normalizar `-0.0→0.0` y pinear `hash_key`/`encoding`/`categorize`.
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
- **Plugin mypy de pandera** (`plugins=["pandera.mypy"]`): NO se añadió; B2b/B2c cerraron sin necesitarlo (`schema.py` usa `DataFrameSchema` imperativo; `special.py`/`target.py` no usan pandera). Reevaluar solo si aparece `DataFrameModel` (clases tipadas).
- Momento privado→público del repo (al terminar). Alias de email y Trusted Publishing OIDC en el release público (F1).

## Repo
Privado en GitHub: **`nexolabs-gh/nikodym`** (https://github.com/nexolabs-gh/nikodym), branch `main`. Push directo a `main` autorizado en el cierre. Commits con co-autoría de Claude.
