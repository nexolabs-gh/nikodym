# AGENTS.md — Nikodym RiskLib

> Contexto de trabajo del proyecto (fuente común para Claude Code y Codex). `CLAUDE.md` importa este archivo.
> Detalle completo en [`docs/ESPECIFICACIONES.md`](docs/ESPECIFICACIONES.md), [`docs/ROADMAP.md`](docs/ROADMAP.md) y [`docs/design/00-INDICE.md`](docs/design/00-INDICE.md).

## Qué es
Librería Python **open-source (Apache-2.0)** de riesgo de crédito **integral**: scoring/scorecards, ML, provisiones **CMF (Chile)** e **IFRS 9/ECL**, forward-looking y stress testing. Paquete: `nikodym`. Marca compartida con la **consultora Nikodym** (la librería es su escaparate de reputación → calidad ejemplar es requisito, no extra).

## Idioma
Todo en **español** (docs, comentarios, comunicación). Términos técnicos en su forma original.

## Estado del proyecto (2026-07-17)
**Nikodym `1.3.0` publicado en PyPI** (`pip install nikodym`); repo `main` en `89583dd`. La librería
ya **no** está en fase de construcción por capas — está publicada y en mejora continua:
- **Pipeline scorecard F1 (comportamiento)**: API **estable** bajo garantía **SemVer 1.x** (binning WoE
  monotónico, selección IV/VIF, logística sobre WoE, calibración, informe HTML/PDF/Word).
- **Provisiones CMF (Chile, B-1) e IFRS 9/ECL**: implementadas, testeadas y con preset/UI/informe, pero
  marcadas **experimentales** (madurez, no certificación).
- **Stress, markov, forward, survival**: implementados y cubiertos por tests, pero hoy se usan
  escribiendo el config en Python (sin preset/UI propios) → **experimentales**.
- **UI React** en `web/` + **demo multi-dominio** (F1 scorecard · F3 CMF · F4 IFRS 9) deployada en
  **demo.nikodym.cl** (fixtures de corridas reales, sin cálculo en el navegador).
- Suite: **>3.900 tests**, `mypy --strict`, cobertura 100 % en código regulatorio, CI matriz verde
  (macOS/Windows/Linux × Python 3.11–3.13).

**Track pre-Interbank COMPLETO:** la cola [`privado/COLA-CODEX-INTERBANK.md`](privado/COLA-CODEX-INTERBANK.md)
(IBK-01…IBK-05) está **toda cerrada** al 2026-07-17. **IBK-05 (`89583dd`, tag `v1.3.0`) = RC 1.3.0 LIVE en
PyPI + demo re-deployada** con lineage 1.3.0 (extra `markov` real, smoke clean-room F4, recaptura de
informes). **No hay bloque IBK siguiente.** Reunión **Interbank miércoles 2026-07-22** (congelar demo ≤
martes 21). El **tag `vX.Y.Z` y PyPI exigen OK específico de Cami por release** (el OK permanente cubre
push/deploy, no tag/PyPI). **Arrancar toda sesión leyendo [`HANDOFF.md`](HANDOFF.md).**

## Auto-desarrollo (motor de trabajo)
Método vigente: la skill de Claude **`/auto-desarrollo-claude`** (maestro Opus 4.8 que delega en writers
en worktrees + revisor adversarial independiente + integrador; o maestro-solo si se pide explícitamente).
La **maquinaria tmux/Codex multi-motor está FROZEN** (histórica): `autodev-cron`, watchdog, maestro
headless y los perfiles por motor ya no corren. Detalle histórico en `docs/AUTONOMY.md`. La construcción
por Tandas/SDD y el Hito 0 de contratos transversales (CT-1…CT-4) ya se completaron; su diseño vive en
`docs/design/` y en «Decisiones de diseño fijadas» más abajo.

## Reglas de trabajo durables
- **Incremental por capa (NUEVO, reemplaza "cero código ahora")**: cada capa se **diseña (SDD) → programa → valida con código y tests → ajusta → sigue**. Nunca se programa sin el SDD aprobado de esa capa, pero ya no se difiere todo el código hasta el final. El código de una capa es la prueba de fuego de su diseño; reabrir un SDD por feedback de código es esperado y barato.
- **Doble verificación trazada de toda info externa** (internet/normativa) contra fuente oficial, ideal por render visual del original. Proyecto delicado: lo usarán instituciones financieras; un número errado es riesgo regulatorio. (Principio no negociable #11.)
- **Verificación antes de ampliar**: re-verificar lo hecho antes de producir más. **Tras cada tanda/capa hay una sesión de revisión** (p.ej. "Tanda 1 Rev") antes de avanzar. Patrón de revisión validado: lectura adversarial multi-agente → triage/dedup → verificación adversarial (context7 para APIs) → integración por DanIA → 2ª pasada de verificación de las correcciones.
- **Proceso de producción de SDD**: 27 SDD en tandas (ver índice), **fan-out de agentes** (1 por SDD, plantilla común `docs/design/_PLANTILLA-SDD.md`), **integración y revisión por DanIA**. Sesiones frescas con `HANDOFF.md` como puente.
- **Calidad del código (cuando se programe)**: `mypy --strict`, ruff, tests canónicos numéricos con golden values, 100% de cobertura en código regulatorio (`core/exceptions`, `core/seeding`, `provisioning/cmf`, `provisioning/ifrs9`), `filterwarnings=["error"]`. SDD-24/25 los especifican.
- Decisiones de fondo: una recomendación, no menú. Conciso y ejecutivo.

## Decisiones de diseño fijadas
- **Licencia** Apache-2.0 (open-source). Evitar dependencias copyleft (GPL) — p.ej. `scikit-survival` queda fuera del core.
- **CMF ≠ IFRS 9**: dos motores separados (`provisioning/cmf` con PE=PI·PDI·Exposición, B-1; `provisioning/ifrs9` con ECL). ⚠️ **La regla del máximo del B-1 (Circular 2.346) es `max(método estándar, método interno del banco)`, por institución — NO `max(CMF, IFRS 9)`**: el Cap. A-2 num. 5 del Compendio excluye el deterioro de NIIF 9 sobre colocaciones. Ver ESPECIFICACIONES §5.4 (corregido 2026-07-13).
- **MVP Fase 1**: scorecard de **comportamiento** (sin reject inference; originación es sub-fase posterior).
- **Stack**: pandas (+ **pandera/pyarrow** deps base de `data`), **OptBinning** (binning), **statsmodels** (inferencia), **lifelines** (survival), Optuna, SHAP, MLflow, **Jinja2 + WeasyPrint** (informe HTML y PDF; Quarto se retiró en 1.0) y **python-docx** (export Word), capa IA opcional inyectable (documenta/narra, nunca calcula; la prosa del informe es determinista y NO la escribe la IA). Empaquetado **uv + hatchling** (≥1.27), `src/` layout. Config **Pydantic v2** (núcleo config-driven → la UI es editor del mismo config). Gobernanza **SR 11-7** en el núcleo.
- **`data_hash`** (Tanda 1 Rev, D2): hash del **contenido lógico por bloques** (`hash_pandas_object`), NO los bytes del Parquet (no canónico cross-versión). Inventario MLflow por **aliases+tags** con prefijo `nikodym.` (no stages, deprecados), ancla idempotencia `(model_name, nikodym.config_hash)`.
- **Contratos transversales (Hito 0, CT-1…CT-4)**: orquestación expresa el DAG en la firma (`Step.requires`/`provides`, `ArtifactKey`), motor v1 solo valida prerequisitos; contratos de lectura (resultados/metrics/overlay) crecen por **extensión aditiva**, nunca ruptura; `data` = panel transversal de scorecard, IFRS9/forward traen capa longitudinal propia; el ensamblado de corrida (sink+inventory) vive en capa fina api/runner (`assemble_run`), no en `core`. **SemVer 1.x**: el pipeline scorecard F1 es API estable; las APIs que crecen (results/overlay/metrics/orquestación) quedan marcadas experimental, fuera de la garantía SemVer 1.x.

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
