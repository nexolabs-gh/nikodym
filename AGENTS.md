# AGENTS.md — Nikodym RiskLib

> Contexto de trabajo del proyecto (fuente común para Claude Code y Codex). `CLAUDE.md` importa este archivo.
> Detalle completo en [`docs/ESPECIFICACIONES.md`](docs/ESPECIFICACIONES.md), [`docs/ROADMAP.md`](docs/ROADMAP.md) y [`docs/design/00-INDICE.md`](docs/design/00-INDICE.md).

## Qué es
Librería Python **open-source (Apache-2.0)** de riesgo de crédito **integral**: scoring/scorecards, ML, provisiones **CMF (Chile)** e **IFRS 9/ECL**, forward-looking y stress testing. Paquete: `nikodym`. Marca compartida con la **consultora Nikodym** (la librería es su escaparate de reputación → calidad ejemplar es requisito, no extra).

## Idioma
Todo en **español** (docs, comentarios, comunicación). Términos técnicos en su forma original.

## Estado del proyecto (2026-07-21)
PyPI publica **`1.4.1`**; el tag `v1.4.1` apunta a `e5816c7` (el SHA vigente de `main` queda en
`HANDOFF.md`). El paquete se anuncia como **`Development Status :: 4 - Beta`**: el pipeline F1 es
estable bajo SemVer 1.x, pero las provisiones siguen experimentales, así que «Production/Stable»
sería sobrepromesa. El próximo release será un bump a `1.5.0` con OK específico de Cami. La librería
ya **no** está en fase de construcción por capas — está publicada y en mejora continua:
- **Pipeline scorecard F1 (comportamiento)**: API **estable** bajo garantía **SemVer 1.x** (binning WoE
  monotónico, selección IV/VIF, logística sobre WoE, calibración, informe HTML/PDF/Word).
- **Provisiones CMF (Chile, B-1) e IFRS 9/ECL**: implementadas, testeadas y con preset/UI/informe, pero
  marcadas **experimentales** (madurez, no certificación).
- **Stress, markov, forward, survival**: implementados y cubiertos por tests, pero hoy se usan
  escribiendo el config en Python (sin preset/UI propios) → **experimentales**.
- **UI React** en `web/` + **demo multi-dominio** (F1 scorecard · F3 CMF · F4 IFRS 9) deployada en
  **demo.nikodym.cl** (fixtures de corridas reales, sin cálculo en el navegador).
- **Informe** HTML/PDF/Word con estilo editorial, contexto poblacional, validación formal y config
  efectiva por dominio; F3 fue recapturado desde una corrida real durante esta consolidación.
- Suite: **>3.900 tests**, `mypy --strict`, cobertura 100 % en código regulatorio, CI matriz verde
  (macOS/Windows/Linux × Python 3.11–3.13).

**Track pre-Interbank COMPLETO:** la cola [`privado/COLA-CODEX-INTERBANK.md`](privado/COLA-CODEX-INTERBANK.md)
(IBK-01…IBK-05) está **toda cerrada** al 2026-07-17. **No hay bloque IBK siguiente.** El release
**1.4.1** (2026-07-21) dejó la demo y PyPI con lineage 1.4.1, tras corregir los defectos que
destapó la verificación adversarial previa a la reunión. Reunión **Interbank miércoles
2026-07-22**; el guion y el PPT los tiene Cami. El
**tag `vX.Y.Z` y PyPI exigen OK específico de Cami por release** (el OK permanente cubre push/deploy,
no tag/PyPI). **Arrancar toda sesión leyendo [`HANDOFF.md`](HANDOFF.md).**

## Auto-desarrollo (motor de trabajo)
Para una ejecución autónoma usar la skill explícitamente pedida por Cami y una tarea standalone o
efímera: coordinador, un único writer, gates, revisor adversarial fresco e integración final. No usar
un heartbeat que acumule contexto. La **maquinaria tmux multi-motor está FROZEN** (histórica):
`autodev-cron`, watchdog, maestro headless y los perfiles por motor ya no corren. La construcción por
Tandas/SDD y el Hito 0 de contratos transversales (CT-1…CT-4)
ya se completaron; sus decisiones siguen vigentes en `docs/design/`.

## Reglas de trabajo durables
- **Memoria histórica `Ideas Nikodym` (privada, disponible sólo en el workspace interno):** antes de
  planificar o implementar mejoras de forward-looking, stress, validación, PDI, forecast de cartera,
  conectores o Risk Leap, leer
  `privado/REVISION-HISTORICA-IDEAS-NIKODYM-2026-07-18.md` cuando esa ruta esté disponible.
  El corpus histórico es inspiración y fuente de tests adversariales, **no** metodología aprobada ni
  fuente normativa. Toda propuesta debe respetar sus decisiones `IHN-001…IHN-011`, evitar duplicar
  capacidades actuales y mantener detalles institucionales en `privado/`.
- **Incremental por capa (NUEVO, reemplaza "cero código ahora")**: cada capa se **diseña (SDD) → programa → valida con código y tests → ajusta → sigue**. Nunca se programa sin el SDD aprobado de esa capa, pero ya no se difiere todo el código hasta el final. El código de una capa es la prueba de fuego de su diseño; reabrir un SDD por feedback de código es esperado y barato.
- **Doble verificación trazada de toda info externa** (internet/normativa) contra fuente oficial, ideal por render visual del original. Proyecto delicado: lo usarán instituciones financieras; un número errado es riesgo regulatorio. (Principio no negociable #11.)
- **Verificación antes de ampliar**: re-verificar lo hecho antes de producir más. **Tras cada tanda/capa hay una sesión de revisión** (p.ej. "Tanda 1 Rev") antes de avanzar. Patrón de revisión validado: lectura adversarial multi-agente → triage/dedup → verificación adversarial (context7 para APIs) → integración por DanIA → 2ª pasada de verificación de las correcciones.
- **Evolución por SDD:** toda capacidad nueva o cambio contractual se diseña antes de programarse,
  usando `docs/design/_PLANTILLA-SDD.md`, revisión independiente e integración coordinada. Los SDD
  históricos conservan las decisiones ya implementadas; no constituyen por sí solos una cola activa.
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
- `ROADMAP.md` — estado por capacidad y plan de evolución vigente; conserva las fases históricas.
- `normativa_cmf_parametros.md` — parámetros CMF verificados (tablas PI/PDI por cartera).
- `design/00-INDICE.md` — índice histórico de los SDD y sus decisiones.
- `design/01-core.md` … `28-provisioning-end-to-end.md` — contratos de diseño implementados o
  experimentales según el estado declarado en `ROADMAP.md`.
- `design/_CONTRATOS-TRANSVERSALES.md` — **decisiones troncales Hito 0** (CT-1…CT-4): qué se fija ahora vs qué se difiere, SemVer 0.x, criterios de aceptación de F0. **Leer antes de codificar F0.**
- `design/_PLANTILLA-SDD.md` — plantilla de cada documento de diseño.

## Git
Repo **PÚBLICO** en GitHub: **`nexolabs-gh/nikodym`** (cuenta `nexolabs-gh`), branch `main`, con issues habilitados. ⚠️ Ya no es privado —lo era durante la construcción— así que **todo lo que se commitea es visible para cualquiera**: nada de datos de clientes, credenciales ni detalle institucional fuera de `privado/` (que sí es un repo local aparte, sin remote). Push directo a `main` autorizado en el cierre de sesión. No inventar coautoría: trailer solo si la herramienta que participó lo exige. `.gitignore` veta datos y secretos por defecto (proyecto regulatorio).
