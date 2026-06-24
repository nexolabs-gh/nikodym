# AGENTS.md — Nikodym RiskLib

> Contexto de trabajo del proyecto (fuente común para Claude Code y Codex). `CLAUDE.md` importa este archivo.
> Detalle completo en [`docs/ESPECIFICACIONES.md`](docs/ESPECIFICACIONES.md), [`docs/ROADMAP.md`](docs/ROADMAP.md) y [`docs/design/00-INDICE.md`](docs/design/00-INDICE.md).

## Qué es
Librería Python **open-source (Apache-2.0)** de riesgo de crédito **integral**: scoring/scorecards, ML, provisiones **CMF (Chile)** e **IFRS 9/ECL**, forward-looking y stress testing. Paquete: `nikodym`. Marca compartida con la **consultora Nikodym** (la librería es su escaparate de reputación → calidad ejemplar es requisito, no extra).

## Idioma
Todo en **español** (docs, comentarios, comunicación). Términos técnicos en su forma original.

## Estado actual (2026-06-24)
**27 SDD en total** (antes 26): en Tanda 1 Rev se creó **SDD-27 `eda`** (huérfano del árbol que ningún SDD cubría).
**Tanda 0 ✅ · Tanda 1 (Fundación) ✅ · Tanda 1 Rev ✅ cerrada.** Los 7 SDD de Fundación (01 `core`, 02 `data`, 03 `audit`+`governance`, 04 `tracking`, 05 convenciones+config, 24 testing, 25 packaging/CI) están **Aprobados + revisados** (cabecera "rev. Tanda 1 Rev"). Tanda 1 Rev: revisión adversarial multi-agente (context7) → integró 1 crítico + 7 altos + ~medios, ratificó las 5 decisiones abiertas, y re-verificó (2ª pasada, residuos corregidos). Molde fijado (core sin sklearn; identidad por `config_hash` JSON canónico que excluye INFRA_SECTIONS; excepciones `NikodymError` + subclases por módulo; `FanOutSink`; uniones anidadas con factory local; naming inglés stats/IFRS9 + español CMF; `StepAdapter` + claves de I/O; `config_cls` ClassVar). SDD-27 `eda` queda en **Borrador** (verificación formal en Tanda 2).

**🔁 CAMBIO DE PROCESO (decisión de Cami, 2026-06-24): de waterfall a INCREMENTAL POR CAPA.** Ya NO se difiere todo el código hasta tener los 27 SDD. A partir de ahora: **diseñar una capa → programarla → validar el molde con código → ajustar → seguir.** Razón: la Tanda 1 Rev encontró 8 defectos de contrato en docs ya "aprobados" y la verificación halló errores que solo el código caza (p.ej. `isinstance` sobre Protocol sin `@runtime_checkable`); validar el molde de Fundación con código real **antes** de apilar 20 SDD encima reduce retrabajo y adelanta el activo que da reputación (la librería corriendo, no los markdown).

**Próximo paso: ARMAR EL PLAN para programar F0 (Fundación)** — `core`/`data`/`audit`/`governance`/`tracking`/`packaging`/`testing`, ahora que sus 7 SDD están revisados. **NO** seguir con Tanda 2 de diseño todavía: primero se codifica y valida F0. La próxima sesión arranca planificando F0 (montar `src/nikodym/`, `pyproject.toml` uv+hatchling, primer `Study` end-to-end con lineage). Tras F0 validado: T2 diseño (scoring: 27 eda, 06-11, 26) → F1 código, y así por capa.

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
- **Stack**: pandas (+ **pandera/pyarrow** deps base de `data`), **OptBinning** (binning), **statsmodels** (inferencia), **lifelines** (survival), Optuna, SHAP, MLflow, **Quarto** (reporte HTML+PDF), Claude (capa IA opcional, documenta nunca calcula). Empaquetado **uv + hatchling** (≥1.27), `src/` layout. Config **Pydantic v2** (núcleo config-driven → la UI es editor del mismo config). Gobernanza **SR 11-7** en el núcleo.
- **`data_hash`** (Tanda 1 Rev, D2): hash del **contenido lógico por bloques** (`hash_pandas_object`), NO los bytes del Parquet (no canónico cross-versión). Inventario MLflow por **aliases+tags** con prefijo `nikodym.` (no stages, deprecados), ancla idempotencia `(model_name, nikodym.config_hash)`.

## Mapa de documentos (`docs/`)
- `ESPECIFICACIONES.md` — spec maestra v1.0.
- `ROADMAP.md` — fases F0–F7 (+ originación), DoD por fase.
- `normativa_cmf_parametros.md` — parámetros CMF verificados (tablas PI/PDI por cartera).
- `design/00-INDICE.md` — los **27 SDD** y las tandas (T0 verificación → T1 fundación ✅ → T1 Rev ✅ → T2 scoring → …); v1.1.
- `design/01-core.md` … `05`, `24`, `25` — los 7 SDD de Tanda 1 (Fundación), **Aprobados + revisados (T1 Rev)**.
- `design/27-eda.md` — SDD-27 `eda` (paso 1 del pipeline scorecard), **Borrador** (creado en T1 Rev; se verifica en T2).
- `design/_PLANTILLA-SDD.md` — plantilla de cada documento de diseño.

## Git
Repo **privado** en GitHub: **`nexolabs-gh/nikodym`** (cuenta `nexolabs-gh`), branch `main`. Se trabaja aquí mientras se construye la librería; **se moverá a un repo público al terminar**. Push directo a `main` autorizado en el cierre de sesión. Commits con `Co-Authored-By: Claude Opus 4.8`. `.gitignore` veta datos y secretos por defecto (proyecto regulatorio).
