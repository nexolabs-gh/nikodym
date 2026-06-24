# HANDOFF

_Última actualización: 2026-06-24 · repo privado `nexolabs-gh/nikodym` · sobre commit `ef4854c`_

## Estado actual
**Nikodym RiskLib** — fin de la fase de diseño de Fundación, **a punto de empezar a codificar F0**. **Tanda 0 ✅ · Tanda 1 (Fundación) ✅ · Tanda 1 Rev ✅ · Hito 0 (Contratos transversales) ✅.** 27 SDD; los 7 de Fundación (01 `core`, 02 `data`, 03 `audit`+`governance`, 04 `tracking`, 05 convenciones+config, 24 testing, 25 packaging/CI) **Aprobados + revisados**; 01/02/03 además llevan "rev. Hito 0". SDD-27 `eda` en Borrador (se verifica en T2). **Ninguna línea de código aún.**

**Estrategia de construcción confirmada (Cami): MIXTO-TRONCAL-MÁS-INCREMENTAL.** Refina el giro a incremental por capa. Regla: *diseña de extremo a extremo lo caro de cambiar (contratos transversales); difiere just-in-time lo barato (lógica intra-capa).*

## Hecho en esta sesión
- **Análisis de estrategia de construcción** (workflow multi-agente: 4 lectores de madurez de los SDD de Fundación + panel de 4 lentes —arquitecto, regulatorio, open-source, riesgo— que **refutaron** la opción antes de decidir). Convergencia unánime: el molde está maduro (4/5) pero 4 contratos transversales estaban dimensionados solo para scoring lineal/escalar y se romperían en F4/F5.
- **Hito 0 ejecutado.** Nuevo doc [`docs/design/_CONTRATOS-TRANSVERSALES.md`](docs/design/_CONTRATOS-TRANSVERSALES.md) (CT-1…CT-4) + propagación a SDD-01/02/03 + nota en `00-INDICE.md`. Todo **aditivo** (no rompe Tanda 1 Rev). Cami revisó el doc maestro y lo aprobó.
  - **CT-1** (orquestación): `Step`/`StepAdapter` declaran `requires`/`provides` (`ArtifactKey = tuple[str,str]`) → la **firma expresa el DAG** desde v1; el motor v1 solo **valida** prerequisitos (orden = declaración); el **scheduler topológico** (fan-in/fan-out de forward/stress) se difiere a F5 sin tocar la firma. Resuelve de paso el "prerequisite registry" cross-sección.
  - **CT-2** (resultados/gobernanza): puerta de extensión tipada y opcional, el escalar de scoring intacto — `ProvisionResultLike.term_structure() -> DataFrame|None`, `ModelCard.metric_sections: dict[str,Any]={}`, `OverlayRecord.payload: dict|None`. El *shape* interno lo fijan SDD-16/17/20.
  - **CT-3** (datos): frontera escrita en SDD-02 §12 (D-DATA-7): `data` = panel **transversal** de scorecard; IFRS9/forward traen su **capa longitudinal** propia (mismo mecanismo de `data_hash`).
  - **CT-4** (owner): `ModelInventory` con `@runtime_checkable`; el ensamblado de corrida (componer sinks en `FanOutSink`, resolver `NullInventory`/`MLflowInventory`/`MissingDependencyError`) vive en `assemble_run` en **capa fina api/runner fuera de `core`**.

## En curso / a medias
Nada a medias. Hito 0 cerrado, contexto y HANDOFF al día.

## Próximos pasos
1. **PRÓXIMA SESIÓN = PROGRAMAR F0 (Fundación).** El plan y el troncal ya están. **Leer primero** `docs/design/_CONTRATOS-TRANSVERSALES.md` (especialmente §4 criterios de aceptación) + los SDD 01/05 (core/config), luego 02/03/04, y 24/25 para test/packaging. Montar: `src/nikodym/` (layout `src/`), `pyproject.toml` (uv + hatchling ≥1.27, deps base + extras), `core` (Study, config Pydantic, Registry, SeedManager, LineageBundle, exceptions, Step/StepAdapter), y llegar a un **primer `Study` end-to-end con lineage reproducible** (DoD F0, ROADMAP).
2. **Criterios de aceptación añadidos por el Hito 0** (no olvidar — son lo que valida el troncal con código): (a) un `Step` **dummy con fan-in** (dos `requires` de dos dominios) que estrese el bus de I/O y la validación pre-run; (b) un test que pase un `metric_sections`/`payload` estructurado dummy (ECL-like) por `ModelCard`/`OverlayRecord` para verificar la puerta de extensión CT-2; (c) el job `coverage-regulatory` **verifica existencia** de los módulos declarados regulatorios (hoy `provisioning/*` no existe → pasaría 0/0=100% por vacuidad).
3. **Validar el molde con código real**: si un contrato no compila/funciona (StepAdapter, seeding por nombre, config_hash, requires/provides), **reabrir el SDD** correspondiente — esperado y barato.
4. Tras F0 validado: **T2 diseño** (scoring: 27 eda, 06-11, 26) → **F1 código** → **release público v0.1.0** (SemVer 0.x honesto). Y así por capa.
- **Forma de trabajo**: yo-solo + fan-out de lectura. Sin equipo persistente hasta que haya tracks paralelos separables.

## Decisiones / contexto a recordar (el molde rige toda la librería)
- **`core` NO depende de sklearn**; compat sklearn por multiherencia en el módulo del estimador. **`config_cls: ClassVar`** = gancho instancia→sub-config.
- **Identidad = `config_hash`** = sha256 JSON canónico, `exclude=INFRA_SECTIONS` (`{name, governance, audit, tracking, report}`). `data.load.source` normalizado a basename.
- **`data_hash` = contenido lógico por bloques** (`hash_pandas_object(index=True)` + esquema canónico), NO bytes de Parquet. Golden-test cross-versión obligatorio.
- **Orquestación**: orquestador resuelve `(sección → (domain, type) → clase)`; `Step` nativo se usa tal cual, estimador se envuelve en `StepAdapter`; `Step` y los Result/Inventory Protocols son `@runtime_checkable`. Métricas escalares → `results["metrics"]: dict[str,float]`. **(Hito 0)** `Step` ya lleva `requires`/`provides`.
- **Inventario (03↔04)**: governance DEFINE `Protocol ModelInventory` + vocabulario (Literal); tracking IMPLEMENTA (`MLflowInventory`). Ancla `(model_name, nikodym.config_hash)`; aliases+tags (NO stages). `register` sin backend DB → `RegistryUnavailableError`; `publish_to_inventory=True` sin extra → `MissingDependencyError`. **(Hito 0)** el ensamblado lo hace `assemble_run` en capa api/runner, no `core`.
- **Excepciones**: raíz `NikodymError`; subclases por módulo. **Naming D-CONV-1**: inglés stats/IFRS9, español CMF (`pi/pdi/pe`); prosa siempre español.
- **CMF ≠ IFRS 9** (dos motores, provisión = máximo). **MVP F1 = scorecard de comportamiento.**
- **Packaging**: deps base = pydantic/numpy/pandas/**pandera/pyarrow**/joblib/PyYAML. `hatchling>=1.27`. Anti-copyleft: `uv export` + parser SPDX + lista vetada GPL/LGPL/AGPL + FALLAR ante licencia ausente.
- **(Hito 0) Contratos transversales crecen por extensión ADITIVA, nunca ruptura. SemVer 0.x honesto**: marcar experimental las APIs que crecerán (results/overlay/metrics/orquestación).

## Callejones sin salida / no reintentar
- **NO reintroducir 4 claims que la verificación tumbó (context7):** (1) `SeedSequence.spawn()` es posicional → seeding por nombre usa `SeedSequence(entropy=[root_seed, hash_estable(nombre)])` con **`hashlib`**, NO `hash()` builtin. (2) En sklearn ≥1.6, sin heredar `BaseEstimator` no se pasa `check_estimator`. (3) `DataFrame.eval`/`query` NO son sandbox (inyección) → mini-DSL declarativo. (4) Model Stages de MLflow deprecados desde 2.9 → aliases+tags.
- **NO hashear bytes de Parquet para `data_hash`** (no canónico cross-versión; D2 lo revirtió a contenido lógico).
- **`isinstance` sobre un Protocol exige `@runtime_checkable`** — ya aplicado a `Step`, Result Protocols y (Hito 0) `ModelInventory`.
- **NO inflar el "troncal" con diseño especulativo de F4/F5.** El Hito 0 fijó SOLO firmas/puertas de extensión, NO las matemáticas de ECL ni el shape final de term-structure (eso es de SDD-16/17/20). Diferir lo barato de cambiar es la regla.
- **Gotcha de workflows**: en los scripts JS de `Workflow`, las prompts son template literals con backticks; **no** usar backticks internos (rompe el parseo) — comillas simples; `${...}` sí es válido. Pasar `run_in_background` al Workflow **falla** (ya corre en background por defecto).
- Verificación visual de PDFs: descargar y leer con Read por páginas; `pdftotext` no respeta celdas fusionadas (tablas CMF).

## Dudas abiertas / bloqueos (preexistentes, no urgentes)
- **Pendiente normativo CMF:** haircuts/factores de descuento de garantías financieras del B-1 letra c) (norma remite a circular no localizada). En `normativa_cmf_parametros.md` §5.2/§7.
- **Vigilancia:** consulta pública CMF (Res. Exenta 273/2025, 10.976/2025) — en oct-2025 su alcance quedó en B-6/B-7, sin tocar matrices estándar.
- **Deudas diferidas con owner (Hito 0 §5):** pickle/joblib del `ArtifactStore` (frágil/RCE) → owner F3; motor topológico DAG → F5; capa de datos longitudinal → F4/F5; presupuesto de CI (matriz 3×3 + Hypothesis) → F1; `mypy strict` sobre wrappers sin stubs (statsmodels/lifelines) → cast/ignore localizados F1/F5.
- Momento privado→público del repo (al terminar). pandas vs polars interno (según volúmenes reales).

## Repo
Privado en GitHub: **`nexolabs-gh/nikodym`** (https://github.com/nexolabs-gh/nikodym), branch `main`. Push directo a `main` autorizado en el cierre. Commits con co-autoría de Claude.
