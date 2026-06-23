# HANDOFF

_Última actualización: 2026-06-23 · repo privado `nexolabs-gh/nikodym` · sobre commit `ed047b4`_

## Estado actual
**Nikodym RiskLib** en **fase de diseño** (cero código). **Tanda 0 (Verificación) ✅** y **Tanda 1 (Fundación) ✅ producida e integrada**. Los **7 SDD de Fundación** están escritos, verificados (3 ciclos adversariales multi-agente + re-verificación de APIs externas con context7) e integrados por DanIA → marcados **Aprobado** en el índice y en sus headers:

| SDD | Módulo | Archivo |
|---|---|---|
| 01 | `core` (Study, Registry, config, seeding, lineage, base classes, excepciones) | `docs/design/01-core.md` |
| 02 | `data` (carga, esquema pandera, target, particiones, mini-DSL de reglas) | `docs/design/02-data.md` |
| 03 | `audit` + `governance` (AuditSink, model card, inventario SR 11-7) | `docs/design/03-audit-governance.md` |
| 04 | `tracking` (MLflow: runs, registry, aliases+tags) | `docs/design/04-tracking.md` |
| 05 | Convenciones API + schema de config global | `docs/design/05-convenciones-config.md` |
| 24 | Estrategia de testing | `docs/design/24-testing.md` |
| 25 | Packaging + CI (uv/hatchling, extras) | `docs/design/25-packaging-ci.md` |

**Total ahora: 26 SDD** (antes 25): el reporte Quarto se separó de SDD-04 → nuevo **SDD-26 `report`** en T2/F1 (decisión de alcance de Cami).

## Próximos pasos
1. **PRÓXIMA SESIÓN = "Tanda 1 Rev"** (sesión de revisión). **Regla de Cami: tras cada tanda hay una sesión de revisión antes de avanzar.** Releer con ojo fresco los 7 SDD aprobados + el molde (01/05), validar coherencia/completitud/implementabilidad de extremo a extremo, y resolver las decisiones abiertas que quedaron delegadas (abajo). Recién al cerrar Tanda 1 Rev se pasa a Tanda 2.
2. **Luego Tanda 2 — Scoring (F1, MVP open-source):** SDD **06 `binning`, 07 `selection`, 08 `model`, 09 `scorecard`, 10 `calibration`, 11 `performance`+`stability`, 26 `report`**. Mismo método que T1: diseño paralelo → redacción → verificación adversarial → corrección → cierre, integrado por DanIA.
3. Solo al terminar TODA la spec (los 26 SDD) se empieza a programar (Fase 0).

## Decisiones / contexto a recordar (el molde de T1 rige toda la librería)
- **`core` NO depende de sklearn** (D-CORE-1, núcleo liviano §4 principio 9). Los estimadores de dominio que quieran compat sklearn (`check_estimator`, Pipeline) **multiheredan `sklearn.base.BaseEstimator`** en su módulo. `check_estimator` (sklearn ≥1.6) exige esa herencia; las bases de `core` no la pretenden.
- **Identidad del config = `config_hash`** = sha256 del **JSON canónico** (`model_dump(mode="json", by_alias=True, exclude=INFRA_SECTIONS)`, `sort_keys=True`). `INFRA_SECTIONS = {name, governance, audit, tracking, report}` se **excluyen** (la identidad es el experimento, no la plomería → idempotencia del inventario). `frozen=True` NO hace el modelo hashable; la identidad es el hash, no `__hash__`.
- **Excepciones:** raíz `NikodymError` + núcleo en `core.exceptions`; cada dominio define sus subclases en su módulo (todas heredan de `NikodymError`).
- **`FanOutSink`** (en `core.audit`) combina varios `AuditSink` (governance + tracking) bajo el único hook `Study.set_audit_sink`.
- **Uniones discriminadas:** de **nivel sección** → `type` == key del `Registry` (orquestador). **Anidadas** (p.ej. `data.partition.strategy`) → **factory local**, no Registry.
- **Naming (D-CONV-1):** identificadores en inglés para stats/sklearn/IFRS9 (`fit`, `pd`, `lgd`); en español para regulatorio CMF (`pi`, `pdi`, `pe`). Docstrings/mensajes siempre en español.
- **Inventario (frontera 03↔04):** `governance` (03) **define** el `Protocol ModelInventory` (escritura `register(InventoryEntry)→str` idempotente por `config_hash`; lectura `get_active`/`list_versions` → `InventoryRecord` liviano). `tracking` (04) lo **implementa** (`MLflowInventory`, aliases+tags, NO stages). Dirección de import: 04→03 (tracking importa governance; governance no importa tracking).
- **CMF ≠ IFRS 9** (dos motores, provisión = máximo). **MVP = scorecard de comportamiento.** **Stack** y licencias sin copyleft (GPL fuera; `scikit-survival` fuera del core; `hypothesis` MPL solo dev/test).

## Decisiones abiertas a resolver en Tanda 1 Rev (delegadas en §12 de cada SDD)
- **`eda/`** está en el árbol de paquetes (ESPEC §6.3) pero **ningún SDD lo cubre**. Decidir: plegarlo en SDD-02 (data) / SDD-11 (performance+stability) o darle SDD propio. (En SDD-05 §5.1 figura como sección `eda` "SDD por confirmar".)
- **Formato del `data_hash`** para datasets grandes (sha256 del parquet canónico vs incremental/muestreado) — coordinación DanIA + SDD-02.
- **Política de migración de `schema_version`** (solo levantar en v1 vs auto-migrar) — SDD-05.
- **Contrato concreto de `ProvisionResultLike`/`ECLResultLike`** (campos, dataclass vs Pydantic) — se fija en SDD-15/16 (T4); `core` solo deja el Protocol mínimo.
- Esquema fino de tags/aliases del inventario y metadatos `ui_*` (coordinación 03↔04 y 05↔23).

## Callejones sin salida / no reintentar
- **NO reintroducir 4 claims técnicos que la verificación tumbó (con context7):** (1) `SeedSequence.spawn()` es **posicional**, no acepta nombre → el seeding por nombre usa `SeedSequence(entropy=[root_seed, hash_estable(nombre)])`. (2) En **sklearn ≥1.6**, sin heredar `BaseEstimator` **no** se pasa `check_estimator` (los tags viven en `BaseEstimator`). (3) `DataFrame.eval`/`query` **no** son sandbox seguro (inyección de código; `@`-prefix alcanza locales) → reglas por mini-DSL declarativo, no `df.eval`. (4) **Model Stages de MLflow deprecados** desde 2.9 → usar aliases+tags.
- **Gotcha de workflows:** en los scripts JS de `Workflow`, las strings de prompt son template literals con backticks; **no** usar backticks internos para código (rompe el parseo) — usar comillas simples.
- Verificación visual de PDFs (Tanda 0): screenshot del visor PDFium de Chrome sale en negro; descargar PDF y leer con Read renderizado por páginas. `pdftotext` no respeta celdas fusionadas (tablas CMF) → verificar por render visual.

## Dudas abiertas / bloqueos (preexistentes, no urgentes)
- **Pendiente normativo CMF:** haircuts/factores de descuento de garantías financieras del B-1 letra c) (la norma los remite a circular específica no localizada). Documentado en `normativa_cmf_parametros.md` §5.2/§7.
- **Vigilancia:** consulta pública CMF (Res. Exenta 273/2025, 10.976/2025) — vigilar enacción antes de uso productivo; en oct-2025 su alcance quedó en B-6/B-7, sin tocar las matrices estándar.
- Momento privado→público del repo (al terminar la librería). pandas vs polars interno (según volúmenes reales).

## Repo
Privado en GitHub: **`nexolabs-gh/nikodym`** (https://github.com/nexolabs-gh/nikodym), branch `main`. Push directo a `main` autorizado en el cierre. Commits con co-autoría de Claude.
