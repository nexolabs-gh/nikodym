# HANDOFF

_Última actualización: 2026-06-24 · repo privado `nexolabs-gh/nikodym` · sobre commit `9f4f4c2`_

## Estado actual
**Nikodym RiskLib** en fase de diseño avanzada. **Tanda 0 ✅ · Tanda 1 (Fundación) ✅ · Tanda 1 Rev ✅ cerrada.** Los **7 SDD de Fundación** (01 `core`, 02 `data`, 03 `audit`+`governance`, 04 `tracking`, 05 convenciones+config, 24 testing, 25 packaging/CI) están **Aprobados + revisados** (cabecera "rev. Tanda 1 Rev 2026-06-24"). **Total ahora: 27 SDD** (antes 26) — se creó SDD-27 `eda`.

**🔁 CAMBIO DE PROCESO (decisión de Cami): de waterfall a INCREMENTAL POR CAPA.** Ya NO se difiere todo el código hasta tener los 27 SDD. A partir de aquí: **diseñar una capa → programarla → validar el molde con código → ajustar → seguir.** El próximo paso NO es Tanda 2 de diseño, sino **empezar a programar F0 (Fundación)**.

## Hecho en esta sesión (Tanda 1 Rev)
- **Revisión adversarial multi-agente** (2 workflows, ~50 agentes, context7) de los 7 SDD de Fundación: 94 hallazgos → 19 clusters → verificación → integración por DanIA.
- **Integradas todas las correcciones**: 1 crítico (C01: `pandera`/`pyarrow` faltaban en deps base → `import nikodym.data` rompía) + 7 altos (C02 markers 24↔25; C08 `config_cls` ClassVar; C12 gates de cobertura; C13 `root_seed` en `Partitioner.split`; C14 `RunContext` opcional + `StepAdapter` + claves I/O; C16 anti-copyleft con mecánica; C17 `DataCardSection` declarado) + ~7 medios + roll-up.
- **5 decisiones abiertas ratificadas**: **D1** crear SDD-27 `eda` (26→27); **D2 revertir D-DATA-2** → `data_hash` = hash de contenido lógico por bloques (`hash_pandas_object`), no bytes de Parquet; **D3** migración version-gate + `@migration` dict→dict (vacíos en v1); **D4** Result Protocols se quedan como `Protocol`; **D5** inventario MLflow esquema de 3 capas (aliases champion/challenger/production + tags identidad + descriptivos vocab cerrado, prefijo `nikodym.`).
- **SDD-27 `eda`** redactado (Borrador) — paso 1 del pipeline scorecard (tasa de default por período + estabilidad temporal).
- **Índice** a v1.1 / 27 SDD (T2 incluye 27); **ROADMAP** F0 sin report, F1 con eda+report.
- **2ª pasada de verificación** (14 agentes): cazó 6 medios + bajos de prosa stale → **todos corregidos** (grep final limpio).
- Archivos: `docs/design/01-05,24,25,00-INDICE.md` + `docs/ROADMAP.md` (modificados) + `docs/design/27-eda.md` (nuevo) + `AGENTS.md` + `HANDOFF.md`.

## En curso / a medias
Nada a medias: Tanda 1 Rev quedó cerrada y verificada.

## Próximos pasos
1. **PRÓXIMA SESIÓN = ARMAR EL PLAN para programar F0 (Fundación).** No seguir con diseño de Tanda 2 todavía. Concretamente: planificar cómo se codifica `core`/`data`/`audit`/`governance`/`tracking` + el `pyproject.toml` (uv+hatchling) + la suite de testing (SDD-24/25), montar `src/nikodym/`, y llegar a un primer `Study` end-to-end con lineage reproducible (DoD F0, ROADMAP). Decidir forma de trabajo (yo-solo vs equipo) antes de lanzar.
2. **Validar el molde de Fundación con código real** — si algo del contrato no funciona al compilar (p.ej. el `StepAdapter`, el seeding por nombre, el `config_hash`), **reabrir el SDD correspondiente** (es esperado y barato ahora).
3. Recién tras F0 validado: **Tanda 2 diseño** (scoring: SDD-27 eda, 06-11, 26) → **F1 código** (MVP scorecard, release público v0.1.0). Y así por capa.

## Decisiones / contexto a recordar (el molde de T1 rige toda la librería)
- **Incremental por capa** (NUEVO): SDD aprobado → código → tests → ajuste, capa por capa. Nunca código sin SDD; nunca diferir todo el código al final.
- **`core` NO depende de sklearn**; estimadores que quieran compat sklearn multiheredan `BaseEstimator` en su módulo. **`config_cls: ClassVar`** en `BaseNikodymEstimator` es el gancho instancia→sub-config (lo usan `from_config`/`_validate_config`/el check de SDD-24).
- **Identidad = `config_hash`** = sha256 del JSON canónico, `exclude=INFRA_SECTIONS` (`{name, governance, audit, tracking, report}`). `data.load.source` se normaliza (basename) para estabilidad cross-máquina.
- **`data_hash` = contenido lógico por bloques** (`hash_pandas_object(index=True)` + esquema canónico), NO bytes de Parquet. Sin fallback muestreado en ruta regulatoria. Golden-test cross-versión obligatorio.
- **Orquestación**: el orquestador resuelve `(sección → (domain, type) → clase)`; un `Step` nativo (DataStep) se usa tal cual; un estimador se envuelve en **`StepAdapter`** (lee X/y del ArtifactStore por claves de I/O, llama fit+transform/predict/compute, escribe namespaced). `Step` es `@runtime_checkable`. Métricas escalares → `results["metrics"]: dict[str,float]`.
- **Inventario (03↔04)**: governance DEFINE el `Protocol ModelInventory` + el vocabulario (Literal); tracking lo IMPLEMENTA (`MLflowInventory`). Tag ancla `nikodym.config_hash`; `register` levanta `RegistryUnavailableError` (definido en governance, importado por tracking) sin backend DB; `publish_to_inventory=True` sin extra → `MissingDependencyError`. Aliases+tags, NO stages.
- **Excepciones**: raíz `NikodymError`; cada módulo sus subclases. **Naming D-CONV-1**: inglés stats/sklearn/IFRS9, español CMF (`pi/pdi/pe`); prosa siempre español.
- **CMF ≠ IFRS 9** (dos motores, provisión = máximo). **MVP F1 = scorecard de comportamiento.**
- **Packaging**: deps base = pydantic/numpy/pandas/**pandera/pyarrow**/joblib/PyYAML. `hatchling>=1.27` (PEP 639). Extras incl. `polars`, `ml` (SVM/RF sklearn). SDD-24 dueño del contenido pytest/coverage; SDD-25 lo transcribe + cabla. Anti-copyleft: `uv export` + parser SPDX + lista vetada GPL/LGPL/AGPL + FALLAR ante licencia ausente.

## Callejones sin salida / no reintentar
- **NO reintroducir 4 claims que la verificación tumbó (context7):** (1) `SeedSequence.spawn()` es posicional → seeding por nombre usa `SeedSequence(entropy=[root_seed, hash_estable(nombre)])`. (2) En sklearn ≥1.6, sin heredar `BaseEstimator` no se pasa `check_estimator`. (3) `DataFrame.eval`/`query` NO son sandbox (inyección; `@`-prefix alcanza locales) → mini-DSL declarativo. (4) Model Stages de MLflow deprecados desde 2.9 → aliases+tags.
- **NO volver a hashear bytes de Parquet para `data_hash`** (no canónico cross-versión de pyarrow; D2 lo revirtió a contenido lógico).
- **`isinstance` sobre un Protocol exige `@runtime_checkable`** — si se usa el patrón en código, decorar el Protocol (ya aplicado a `Step` y a los Result Protocols).
- **Gotcha de workflows**: en los scripts JS de `Workflow`, las prompts son template literals con backticks; **no** usar backticks internos para código (rompe el parseo) — usar comillas simples. (Interpolación `${...}` sí es válida.)
- Verificación visual de PDFs: descargar y leer con Read por páginas; `pdftotext` no respeta celdas fusionadas (tablas CMF).

## Dudas abiertas / bloqueos (preexistentes, no urgentes)
- **Pendiente normativo CMF:** haircuts/factores de descuento de garantías financieras del B-1 letra c) (norma remite a circular no localizada). En `normativa_cmf_parametros.md` §5.2/§7.
- **Vigilancia:** consulta pública CMF (Res. Exenta 273/2025, 10.976/2025) — vigilar enacción; en oct-2025 su alcance quedó en B-6/B-7, sin tocar matrices estándar.
- Momento privado→público del repo (al terminar). pandas vs polars interno (según volúmenes reales).
- 2 ítems cosméticos *intencionales* en los SDD (no son defectos): campo `author` ↔ tag `nikodym.autor` (idioma distinto, documentado); orden de claves del bloque pytest/coverage en 25 vs 24 (irrelevante en TOML).

## Repo
Privado en GitHub: **`nexolabs-gh/nikodym`** (https://github.com/nexolabs-gh/nikodym), branch `main`. Push directo a `main` autorizado en el cierre. Commits con co-autoría de Claude.
