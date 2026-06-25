# HANDOFF

_Última actualización: 2026-06-24 · repo privado `nexolabs-gh/nikodym` · sobre commit `c7edaca`_

## 🤖 Modo autónomo (rutina)
**Estado:** `IDLE`  _(IDLE = libre · `RUNNING [ts]` = corrida en curso. El lock de OS del wrapper garantiza exclusión; un `RUNNING` visto al arrancar = corrida muerta → rescatar, no abortar.)_
Última corrida: 2026-06-24 21:33 · ítem **B2b.3** · `c7edaca` · ✓ HECHO _(corrida headless DanIA; 293 tests, 100%, gates verdes). ⚠ El monitor `esperar-trabajador.sh` NO marcó OCIOSO con el worker Codex ya terminado → verifiqué por `tmux capture-pane` + `git status` (ver Decisiones)._
Ciclo en la skill **auto-desarrollo** §2 (rescate §4); playbook en `docs/AUTONOMY.md`; bitácora en `AUTONOMY-LOG.md`. Worker Codex en tmux `nikodym`; maestro fresco por cron horario (:17).

## Backlog priorizado (cola autónoma)
> La rutina consume esto en orden, de arriba a abajo. Marca `[x]` al terminar; **NO** borres ni renumeres.
> Cada ítem es autocontenido = un módulo + sus tests, dejando los 4 gates verdes (cobertura 100%). El worker
> deja el árbol verde **sin commitear**; el maestro revisa, commitea y pushea (R7).
1. [x] **B2b.1** — `data/loading.py` (`DataLoader`): CSV/Parquet + passthrough de DataFrame con copia defensiva, `engine="pyarrow"` explícito, `backend="polars"` perezoso, `from_config`. SDD-02 §4. + `tests/unit/test_data_loading.py`. ✓ `6d699e2` (266 tests, 100%).
2. [x] **B2b.2** — `data/schema.py` (`SchemaValidator`): `SchemaConfig`→`pa.DataFrameSchema` (`import pandera.pandas as pa`), `validate(df, lazy=True)`→`DataValidationError` (reporte español). SDD-02 §7. ✓ `bdbea17` (282 tests, 100%). _Nota ratificada: `index_col`=nombre del índice existente (no `set_index`); `SchemaValidator` no exportado en `data.__init__`._
3. [x] **B2b.3** — `data/hashing.py` (`data_hash`): sha256 por bloques (`hash_pandas_object`), **endianness `<u8` explícito**, `-0.0→0.0`, `index=True`, defaults `hash_key`/`encoding`, golden cross-versión. SDD-02. ✓ `c7edaca` (293 tests, 100%). _Ratificado: ordena por índice (`sort_index` estable) → invariante a permutación de filas; eleva O(n) §7 a O(n log n), aceptado. Header de esquema versionado `nikodym.data_hash.v1`. No exportado en `data.__init__`._
4. [ ] **B2b.4** — `data/special.py` (`SpecialValuePolicy`): centinelas→NaN + `special_mask` + `special_catalog`. SDD-02.
5. [ ] **B2c.1** — `data/target.py` (definición de target/etiqueta). SDD-02.
6. [ ] **B2c.2** — `data/partition.py` (`PartitionStrategy`: temporal/random/cohort) con **Hypothesis** para determinismo y anti-leakage. SDD-02.
7. [ ] **B2d** — `data/step.py` (`DataStep @register(domain="data")`) + `Study.run(steps=["data"])` end-to-end de datos. SDD-02 + CT-1.
8. [ ] **B3.1** — integración `audit`/`governance`/`tracking`/`api` (cableado + `assemble_run`/`ModelInventory`, CT-4). SDD-03.
9. [ ] **B4** — `testing` + CI (`.github/workflows`, matriz) + 3 criterios de cierre del Hito 0.

## Estado actual
**Nikodym RiskLib — F0 (Fundación): B1 `core` ✅ + B2a `data` (config) ✅ COMPLETOS.** F0 troceado en 4 bloques: B1 `core` ✅ · **B2 `data` EN CURSO (B2a ✅, B2b.1 ✅, B2b.2 ✅, B2b.3 ✅, sigue B2b.4)** · B3 `audit`+`governance`+`tracking`+`api` · B4 `testing`+CI+3 criterios Hito 0.

**B2 por dentro:** B2a ✅ (config) · **B2b EN CURSO** (B2b.1 `loading` ✅ `6d699e2` · B2b.2 `schema` ✅ `bdbea17` · B2b.3 `hashing` ✅ `c7edaca` · sigue B2b.4 `special`) · B2c (target·partition) · B2d (card·step, `Study` end-to-end de datos).

Regla de oro vigente: **mixto-troncal-más-incremental** — cada módulo: programa → `ruff`+`mypy --strict`+`pytest`+cobertura verde → ajusta → sigue. Nunca avanzar en rojo. Reabrir un SDD por feedback del código es esperado y barato (este bloque reabrió 2 mecanismos del SDD-02 §5, ver abajo).

## Hecho en la última corrida (B2b.3 · `data/hashing.py`)
- **`src/nikodym/data/hashing.py`** (NUEVO): `data_hash(df, *, block_size=1_000_000) -> str` — sha256 del **contenido lógico** (D-DATA-2, NO bytes de Parquet). Encabezado de esquema canónico versionado (`nikodym.data_hash.v1`, `col\tdtype` ordenado) + `hash_pandas_object(index=True)` por bloques alimentando el mismo sha256. **3 correcciones de reproducibilidad sobre el pseudocódigo §4**: (A) bytes forzados a `<u8` little-endian (`.to_numpy(dtype="<u8", copy=True)`, NO `.values.tobytes()` endian-nativo); (B) normaliza `-0.0→0.0` en floats (`col + 0.0`, preserva NaN/inf); (C) `hash_key`/`encoding`/`categorize` pineados como constantes de módulo. Copia defensiva (`copy(deep=True)`) + `sort_index(kind="mergesort")` + columnas `sorted()`. `ValueError` si `block_size<1`.
- **`tests/unit/test_data_hashing.py`** (NUEVO, 11 tests): golden cross-versión (`9c5118ad…`, pandas 2.3.3 de `uv.lock`), determinismo, invariancia (orden columnas / permutación filas / block_size), sensibilidad (valor·índice·dtype), `-0.0==0.0`, no-mutación, df vacío, `block_size` inválido, NaN.
- **Verde total** (corrido y verificado por el maestro, R7): `ruff` + `ruff format` (50) + `mypy --strict` (28 archivos) + **293 tests** + **cobertura global 100%** + gate regulatorio 100% + `uv build` + núcleo liviano (`import nikodym.core` NO arrastra `data`/pandera/pyarrow/pandas).
- El worker Codex dejó el árbol verde **sin commitear**; el maestro revisó el diff, commiteó (`c7edaca`) y pusheó a `main`.

## En curso / a medias
Nada a medias. B2b.3 cerrado, commiteado (`c7edaca`) y pusheado; árbol limpio y verde.

## Próximos pasos
**Siguiente ítem del backlog: B2b.4 `data/special.py`** (`SpecialValuePolicy`). Leer primero la sección de valores especiales/missing de `docs/design/02-data.md`. Método validado: leer el SDD de la sección → worker Codex fresco módulo-a-módulo → revisión + 4 gates + push por el maestro (R7).
- **`special.py`** (`SpecialValuePolicy`): centinelas declarados (p.ej. 9999, -1) → NaN + `special_mask` (qué celdas eran centinela) + `special_catalog` (catálogo por columna de los centinelas aplicados). Copia defensiva, sin mutar el df del caller. Tests canónicos + golden, cobertura 100%.

Tras B2b (queda **solo B2b.4**): B2c (target·partition, con Hypothesis para determinismo/anti-leakage) → B2d (card·step, `DataStep @register(domain="data")`, `Study.run(steps=["data"])` end-to-end). Luego B3 → B4 → T2 scoring → F1 → release v0.1.0.

Tras B2b: B2c (target·partition, con Hypothesis para determinismo/anti-leakage) → B2d (card·step, `DataStep @register(domain="data")`, `Study.run(steps=["data"])` end-to-end). Luego B3 → B4 → T2 scoring → F1 → release v0.1.0.

## Decisiones / contexto a recordar
- **B2b.3 `data_hash` — ratificaciones SDD-02 §4/§7/§9:** (a) `data_hash` **ordena por índice** internamente (`sort_index(mergesort)`) → hash invariante a permutación de filas con el mismo índice (el índice ES el id de observación, §9); esto eleva la complejidad O(n) de §7 a **O(n log n)** por el sort — aceptado (sub-segundo a millones de filas; la invariancia regulatoria pesa más). (b) **Endianness `<u8` explícito** sustituye el `.values.tobytes()` (endian-nativo) del pseudocódigo §4. (c) Normalización `-0.0→0.0` + pin de `hash_key`/`encoding`/`categorize`, que el §4 no traía. (d) Header de esquema **versionado** `nikodym.data_hash.v1` (permite migrar el algoritmo a futuro sin colisión). (e) `data_hash` NO se exporta en `data/__init__.py` (se cableará desde el pipeline en B2d).
- **⚠ Deuda de maquinaria (monitor del maestro):** esta corrida `scripts/esperar-trabajador.sh nikodym 250` **no devolvió `OCIOSO`** pese a que el worker Codex terminó (~5 min de trabajo) — bloqueé ~14 min sin salida. Señal fiable usada: `tmux capture-pane` (banner `Worked for Xm` + prompt idle `› Use /skills…`) + `git status` (archivos nuevos presentes). **Para el próximo maestro headless:** tras lanzar, si el monitor no retorna en un tiempo razonable, NO bloquees indefinido — verifica el panel + `git status` directo y procede a gates. (Probable causa: la regex de idle no reconoce el estado ocioso de Codex; conviene refinarla en la maquinaria de AutoDesarrollo.) ✅ **RESUELTO 24-jun** (DanIA en vivo): `hay_spinner` usa solo `esc to interrupt`; `hay_prompt_ocioso` reconoce `Worked for`. Validado: `OCIOSO` en ~31s. Las próximas corridas ya no se bloquean.
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
- **NO `.values.tobytes()` para hashes reproducibles** (B2b.3) — es endian-NATIVO (no reproducible cross-arquitectura). Forzar little-endian: `hash_pandas_object(...).to_numpy(dtype="<u8", copy=True).tobytes()`. Además normalizar `-0.0→0.0` (bits IEEE distintos) y pinear `hash_key`/`encoding`/`categorize` de `hash_pandas_object` (sus defaults pueden cambiar entre versiones de pandas).
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
