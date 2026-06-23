# AGENTS.md — Nikodym RiskLib

> Contexto de trabajo del proyecto (fuente común para Claude Code y Codex). `CLAUDE.md` importa este archivo.
> Detalle completo en [`docs/ESPECIFICACIONES.md`](docs/ESPECIFICACIONES.md), [`docs/ROADMAP.md`](docs/ROADMAP.md) y [`docs/design/00-INDICE.md`](docs/design/00-INDICE.md).

## Qué es
Librería Python **open-source (Apache-2.0)** de riesgo de crédito **integral**: scoring/scorecards, ML, provisiones **CMF (Chile)** e **IFRS 9/ECL**, forward-looking y stress testing. Paquete: `nikodym`. Marca compartida con la **consultora Nikodym** (la librería es su escaparate de reputación → calidad ejemplar es requisito, no extra).

## Idioma
Todo en **español** (docs, comentarios, comunicación). Términos técnicos en su forma original.

## Estado actual (2026-06-23)
**Fase de diseño. CERO código** hasta tener TODA la arquitectura + roadmap + los **26 SDD** especificados. Recién entonces se programa (Fase 0).
**Tanda 0 (verificación) ✅ cerrada.** **Tanda 1 (Fundación) ✅ producida:** los 7 SDD (01 `core`, 02 `data`, 03 `audit`+`governance`, 04 `tracking`, 05 convenciones+config, 24 testing, 25 packaging/CI) escritos, verificados (3 ciclos adversariales + context7) e integrados por DanIA → marcados **Aprobado** por integración. Se fijó el molde (core sin sklearn; identidad por `config_hash` JSON canónico que excluye infraestructura; excepciones raíz `NikodymError` + subclases por módulo; `FanOutSink`; uniones anidadas con factory local; naming inglés stats/IFRS9 + español CMF). **Cambio de alcance:** `report` separado de SDD-04 → nuevo **SDD-26** (`report` Quarto) en T2/F1 (por eso 26 SDD).
**Próximo: Tanda 1 Rev** (sesión de revisión de los 7 SDD; tras cada tanda hay una sesión de revisión). Luego Tanda 2 (Scoring, MVP): SDD 06-11 + 26.

## Reglas de trabajo durables
- **Cero código ahora**: solo documentos de arquitectura/diseño (markdown).
- **Doble verificación trazada de toda info externa** (internet/normativa) contra fuente oficial, ideal por render visual del original. Proyecto delicado: lo usarán instituciones financieras; un número errado es riesgo regulatorio. (Principio no negociable #11.)
- **Verificación antes de ampliar**: re-verificar lo hecho antes de producir más. **Tras cada tanda hay una sesión de revisión** (p.ej. "Tanda 1 Rev") antes de pasar a la siguiente.
- **Proceso de producción**: 26 SDD en tandas (ver índice), **fan-out de agentes** (1 por SDD, plantilla común `docs/design/_PLANTILLA-SDD.md`), **integración y revisión por DanIA**. Patrón validado en T1: diseño paralelo → redacción → verificación adversarial multi-lente → corrección → cierre. Sesiones frescas con `HANDOFF.md` como puente.
- Decisiones de fondo: una recomendación, no menú. Conciso y ejecutivo.

## Decisiones de diseño fijadas
- **Licencia** Apache-2.0 (open-source). Evitar dependencias copyleft (GPL) — p.ej. `scikit-survival` queda fuera del core.
- **CMF ≠ IFRS 9**: dos motores separados (`provisioning/cmf` con PE=PI·PDI·Exposición, B-1; `provisioning/ifrs9` con ECL), provisión = **máximo** (piso prudencial CMF).
- **MVP Fase 1**: scorecard de **comportamiento** (sin reject inference; originación es sub-fase posterior).
- **Stack**: pandas, **OptBinning** (binning), **statsmodels** (inferencia), **lifelines** (survival), Optuna, SHAP, MLflow, **Quarto** (reporte HTML+PDF), Claude (capa IA opcional, documenta nunca calcula). Empaquetado **uv + hatchling**, `src/` layout. Config **Pydantic v2** (núcleo config-driven → la UI es editor del mismo config). Gobernanza **SR 11-7** en el núcleo.

## Mapa de documentos (`docs/`)
- `ESPECIFICACIONES.md` — spec maestra v1.0.
- `ROADMAP.md` — fases F0–F7 (+ originación), DoD por fase.
- `normativa_cmf_parametros.md` — parámetros CMF verificados (tablas PI/PDI por cartera).
- `design/00-INDICE.md` — los 26 SDD y las tandas (T0 verificación → T1 fundación ✅ → T2 scoring → …).
- `design/01-core.md` … `05`, `24`, `25` — los 7 SDD de Tanda 1 (Fundación), **Aprobados**.
- `design/_PLANTILLA-SDD.md` — plantilla de cada documento de diseño.

## Git
Repo **privado** en GitHub: **`nexolabs-gh/nikodym`** (cuenta `nexolabs-gh`), branch `main`. Se trabaja aquí mientras se construye la librería; **se moverá a un repo público al terminar**. Push directo a `main` autorizado en el cierre de sesión. Commits con `Co-Authored-By: Claude Opus 4.8`. `.gitignore` veta datos y secretos por defecto (proyecto regulatorio).
