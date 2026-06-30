# AGENTS.md — Nikodym RiskLib

> Contexto de trabajo del proyecto (fuente común para Claude Code y Codex). `CLAUDE.md` importa este archivo.
> Detalle completo en [`docs/ESPECIFICACIONES.md`](docs/ESPECIFICACIONES.md), [`docs/ROADMAP.md`](docs/ROADMAP.md) y [`docs/design/00-INDICE.md`](docs/design/00-INDICE.md).

## Qué es
Librería Python **open-source (Apache-2.0)** de riesgo de crédito **integral**: scoring/scorecards, ML, provisiones **CMF (Chile)** e **IFRS 9/ECL**, forward-looking y stress testing. Paquete: `nikodym`. Marca compartida con la **consultora Nikodym** (la librería es su escaparate de reputación → calidad ejemplar es requisito, no extra).

## Idioma
Todo en **español** (docs, comentarios, comunicación). Términos técnicos en su forma original.

## Estado operativo AutoDesarrollo (2026-06-30)
Latido **PAUSADO** por reset operativo. No hay `autodev-cron`, `autodev-watchdog`, maestro headless, revisor ni gates corriendo. La maquinaria es **multi-motor por rol**: perfil actual recomendado `AUTODESARROLLO_PERFIL=codex-only`, pero se puede correr `claude-only` o mixto con `MAESTRO_MOTOR`, `WORKER_MOTOR`/`MOTOR`, `REVISOR_MOTOR`, `PLANIFICADOR_MOTOR`. No hay fallback oculto entre motores: el cambio debe ser explícito.

Rol del maestro: supervisor/orquestador, no programador de código de Nikodym. B21.3 `stress/engine.py` quedó WIP local sin commit/push; leer `HANDOFF.md` antes de tocarlo.

## Estado actual (2026-06-24)
**27 SDD en total** (antes 26): en Tanda 1 Rev se creó **SDD-27 `eda`** (huérfano del árbol que ningún SDD cubría).
**Tanda 0 ✅ · Tanda 1 (Fundación) ✅ · Tanda 1 Rev ✅ cerrada.** Los 7 SDD de Fundación (01 `core`, 02 `data`, 03 `audit`+`governance`, 04 `tracking`, 05 convenciones+config, 24 testing, 25 packaging/CI) están **Aprobados + revisados** (cabecera "rev. Tanda 1 Rev"). Tanda 1 Rev: revisión adversarial multi-agente (context7) → integró 1 crítico + 7 altos + ~medios, ratificó las 5 decisiones abiertas, y re-verificó (2ª pasada, residuos corregidos). Molde fijado (core sin sklearn; identidad por `config_hash` JSON canónico que excluye INFRA_SECTIONS; excepciones `NikodymError` + subclases por módulo; `FanOutSink`; uniones anidadas con factory local; naming inglés stats/IFRS9 + español CMF; `StepAdapter` + claves de I/O; `config_cls` ClassVar). SDD-27 `eda` queda en **Borrador** (verificación formal en Tanda 2).

**🔁 ESTRATEGIA DE CONSTRUCCIÓN confirmada (Cami, 2026-06-24): MIXTO-TRONCAL-MÁS-INCREMENTAL.** Refina (no reemplaza) el giro de waterfall a incremental por capa. Regla: **diseña de extremo a extremo lo que es caro cambiar (contratos transversales); difiere just-in-time lo barato (lógica intra-capa).** Análisis multi-agente (4 lectores de madurez + panel de 4 lentes que refutaron) convergió unánime: el molde de Fundación está maduro (4/5), pero 4 contratos que cruzan todas las capas estaban dimensionados solo para scoring lineal/escalar y se romperían en F4/F5 (cuando ya haya código y release encima). Por eso se hizo el **Hito 0** antes de codificar.

**✅ Hito 0 — Contratos transversales (2026-06-24, cerrado).** Estabilizó la *extensibilidad* (aditiva, sin romper Tanda 1 Rev) de los 4 contratos, en [`docs/design/_CONTRATOS-TRANSVERSALES.md`](docs/design/_CONTRATOS-TRANSVERSALES.md) (CT-1…CT-4), propagado a SDD-01/02/03 (cabecera "rev. Hito 0"): **CT-1** `Step`/`StepAdapter` con `requires`/`provides` (firma DAG desde v1; scheduler topológico diferido a F5); **CT-2** puerta de extensión estructurada (`ProvisionResultLike.term_structure()`, `ModelCard.metric_sections`, `OverlayRecord.payload`); **CT-3** frontera datos transversal (scorecard) vs longitudinal (IFRS9/forward) escrita en SDD-02; **CT-4** `ModelInventory` `@runtime_checkable` + owner del ensamblado `assemble_run` en capa fina api/runner.

**🟢 F0 (Fundación) EN CURSO. B1 `core` COMPLETO ✅. B2a `data` (config) COMPLETO ✅.** F0 se troceó en 4 bloques (B1 core · B2 data · B3 audit/governance/tracking/api · B4 testing+CI+3 criterios Hito 0). **B1a ✅** (esqueleto + `core/exceptions` + `core/seeding`, regulatorios 100%) · **B1b ✅** (`core/config`: schema·hashing·loader·migration) · **B1c ✅** (resto de `core`, 9 módulos). **B2 se trocea en B2a (config+endurecimiento ✅) · B2b (primitivas: loading·schema/validator·hashing·special) · B2c (target·partition) · B2d (card·step, Study end-to-end de datos).**
**B1c ✅ verde — resto de `core`** (audit · results · base/mixins · registry/artifacts · steps · lineage · study). **Primer `Study` end-to-end con lineage reproducible (DoD F0).** `audit` (`AuditEvent`/`AuditKind`/`AuditSink`/`FanOutSink`) · `results` (Protocols económicos CT-2, `term_structure`) · `base` (`BaseNikodymEstimator` raíz propia + 6 familias, `get_params`/`set_params`/`from_config` sklearn-like) · `mixins` (`AuditableMixin`, `SerializationMixin` trust gate) · `registry`/`artifacts` (namespaced) · `steps` (`Step` Protocol CT-1, `StepAdapter`) · `lineage` (`LineageBundle`/`RunContext`, DoD F0) · `study` (orquestador motor v1 CT-1, save/load directorio atómico, reproducibilidad). Método ultracode: workflow de comprensión (10 agentes, APIs context7) → código por DanIA módulo-a-módulo → **revisión adversarial (27 agentes, 19 hallazgos integrados)** → **2ª pasada fidelidad-contrato (3 hallazgos integrados)**. **230 tests, cobertura 100%** global + regulatoria, `mypy --strict` (23 archivos), wheel OK, núcleo liviano. Decisiones de integrador y hallazgos cerrados en `HANDOFF.md` (resolución de pasos y `StepAdapter.execute` diferidos a T2 con error ruidoso; lineage conservado en corridas fallidas; save atómico con respaldo lateral; `apply_global` propaga `PYTHONHASHSEED`; `extra="forbid"` en modelos audit/lineage).

**B2a ✅ verde — capa `data` (config + endurecimiento).** `DataConfig` (árbol Pydantic + mini-DSL `Predicate`/`Rule` sin `eval` + unión discriminada anidada por factory local). `NikodymConfig.data` endurecido a `DataConfig | None`: **el `model_rebuild()` que preveía SDD-02 §5 NO narra un campo ya resuelto en Pydantic 2.13** (verificado) → reemplazado por hook `_DATA_CONFIG_CLS` + `field_validator` que `nikodym.data` puebla al importarse (núcleo sigue liviano; golden `config_hash` invariante). Deps `pandera>=0.24` (`import pandera.pandas`) / `pyarrow>=14` activadas. **249 tests, cobertura 100%**, `mypy --strict` (25 archivos), wheel incluye `data`. Detalle y desviaciones a ratificar en `HANDOFF.md`.

**Siguiente: B2b** (primitivas de `data`, SDD-02): `loading.py` (DataLoader CSV/Parquet), `schema.py` (SchemaValidator + builder `DataConfig→pandera.DataFrameSchema`, `validate(lazy=True)→DataValidationError`), `hashing.py` (`data_hash` por contenido lógico D2, con **fix de endianness** `.astype('<u8')`), `special.py`. Forma de trabajo: **yo-solo + fan-out**, sin equipo persistente. Tras F0 validado: T2 diseño (scoring) → F1 código → release público v0.1.0.

## Reglas de trabajo durables
- **Incremental por capa (NUEVO, reemplaza "cero código ahora")**: cada capa se **diseña (SDD) → programa → valida con código y tests → ajusta → sigue**. Nunca se programa sin el SDD aprobado de esa capa, pero ya no se difiere todo el código hasta el final. El código de una capa es la prueba de fuego de su diseño; reabrir un SDD por feedback de código es esperado y barato.
- **Doble verificación trazada de toda info externa** (internet/normativa) contra fuente oficial, ideal por render visual del original. Proyecto delicado: lo usarán instituciones financieras; un número errado es riesgo regulatorio. (Principio no negociable #11.)
- **Verificación antes de ampliar**: re-verificar lo hecho antes de producir más. **Tras cada tanda/capa hay una sesión de revisión** (p.ej. "Tanda 1 Rev") antes de avanzar. Patrón de revisión validado: lectura adversarial multi-agente → triage/dedup → verificación adversarial (context7 para APIs) → integración por DanIA → 2ª pasada de verificación de las correcciones.
- **Proceso de producción de SDD**: 27 SDD en tandas (ver índice), **fan-out de agentes** (1 por SDD, plantilla común `docs/design/_PLANTILLA-SDD.md`), **integración y revisión por DanIA**. Sesiones frescas con `HANDOFF.md` como puente.
- **Calidad del código (cuando se programe)**: `mypy --strict`, ruff, tests canónicos numéricos con golden values, 100% de cobertura en código regulatorio (`core/exceptions`, `core/seeding`, `provisioning/cmf`, `provisioning/ifrs9`), `filterwarnings=["error"]`. SDD-24/25 los especifican.
- Decisiones de fondo: una recomendación, no menú. Conciso y ejecutivo.

## Decisiones de diseño fijadas
- **Licencia** Apache-2.0 (open-source). Evitar dependencias copyleft (GPL) — p.ej. `scikit-survival` queda fuera del core.
- **CMF ≠ IFRS 9**: dos motores separados (`provisioning/cmf` con PE=PI·PDI·Exposición, B-1; `provisioning/ifrs9` con ECL), provisión = **máximo** (piso prudencial CMF).
- **MVP Fase 1**: scorecard de **comportamiento** (sin reject inference; originación es sub-fase posterior).
- **Stack**: pandas (+ **pandera/pyarrow** deps base de `data`), **OptBinning** (binning), **statsmodels** (inferencia), **lifelines** (survival), Optuna, SHAP, MLflow, **Quarto** (reporte HTML+PDF), capa IA opcional inyectable (documenta/narra, nunca calcula). Empaquetado **uv + hatchling** (≥1.27), `src/` layout. Config **Pydantic v2** (núcleo config-driven → la UI es editor del mismo config). Gobernanza **SR 11-7** en el núcleo.
- **`data_hash`** (Tanda 1 Rev, D2): hash del **contenido lógico por bloques** (`hash_pandas_object`), NO los bytes del Parquet (no canónico cross-versión). Inventario MLflow por **aliases+tags** con prefijo `nikodym.` (no stages, deprecados), ancla idempotencia `(model_name, nikodym.config_hash)`.
- **Contratos transversales (Hito 0, CT-1…CT-4)**: orquestación expresa el DAG en la firma (`Step.requires`/`provides`, `ArtifactKey`), motor v1 solo valida prerequisitos; contratos de lectura (resultados/metrics/overlay) crecen por **extensión aditiva**, nunca ruptura; `data` = panel transversal de scorecard, IFRS9/forward traen capa longitudinal propia; el ensamblado de corrida (sink+inventory) vive en capa fina api/runner (`assemble_run`), no en `core`. **SemVer 0.x honesto**: APIs que crecerán (results/overlay/metrics/orquestación) marcadas experimental hasta 1.0.

## Mapa de documentos (`docs/`)
- `ESPECIFICACIONES.md` — spec maestra v1.0.
- `ROADMAP.md` — fases F0–F7 (+ originación), DoD por fase.
- `normativa_cmf_parametros.md` — parámetros CMF verificados (tablas PI/PDI por cartera).
- `design/00-INDICE.md` — los **27 SDD** y las tandas (T0 verificación → T1 fundación ✅ → T1 Rev ✅ → T2 scoring → …); v1.1.
- `design/01-core.md` … `05`, `24`, `25` — los 7 SDD de Tanda 1 (Fundación), **Aprobados + revisados (T1 Rev + Hito 0 en 01/02/03)**.
- `design/27-eda.md` — SDD-27 `eda` (paso 1 del pipeline scorecard), **Borrador** (creado en T1 Rev; se verifica en T2).
- `design/_CONTRATOS-TRANSVERSALES.md` — **decisiones troncales Hito 0** (CT-1…CT-4): qué se fija ahora vs qué se difiere, SemVer 0.x, criterios de aceptación de F0. **Leer antes de codificar F0.**
- `design/_PLANTILLA-SDD.md` — plantilla de cada documento de diseño.

## Git
Repo **privado** en GitHub: **`nexolabs-gh/nikodym`** (cuenta `nexolabs-gh`), branch `main`. Se trabaja aquí mientras se construye la librería; **se moverá a un repo público al terminar**. Push directo a `main` autorizado en el cierre de sesión. No inventar coautoría: trailer solo si la herramienta que participó lo exige. `.gitignore` veta datos y secretos por defecto (proyecto regulatorio).
