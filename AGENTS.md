# AGENTS.md — Nikodym RiskLib

> Contexto de trabajo del proyecto (fuente común para Claude Code y Codex). `CLAUDE.md` importa este archivo.
> Detalle completo en [`docs/ESPECIFICACIONES.md`](docs/ESPECIFICACIONES.md), [`docs/ROADMAP.md`](docs/ROADMAP.md) y [`docs/design/00-INDICE.md`](docs/design/00-INDICE.md).

## Qué es
Librería Python **open-source (Apache-2.0)** de riesgo de crédito **integral**: scoring/scorecards, ML, provisiones **CMF (Chile)** e **IFRS 9/ECL**, forward-looking y stress testing. Paquete: `nikodym`. Marca compartida con la **consultora Nikodym** (la librería es su escaparate de reputación → calidad ejemplar es requisito, no extra).

## Idioma
Todo en **español** (docs, comentarios, comunicación). Términos técnicos en su forma original.

## Estado actual (2026-06-23)
**Fase de diseño. CERO código** hasta tener TODA la arquitectura + roadmap + los 25 SDD especificados. Recién entonces se programa (Fase 0).
**Tanda 0 (verificación) ✅ cerrada:** spec + normativa CMF re-verificadas (verificación adversarial multi-agente + render visual de las 6 tablas CMF críticas). Valores normativos **triple-verificados** (texto oficial + render visual + CNC v2022), cero errores en cifras; 12 correcciones de trazabilidad/coherencia/notación aplicadas. **Próximo: Tanda 1 (Fundación)** — SDD 01-05, 24, 25.

## Reglas de trabajo durables
- **Cero código ahora**: solo documentos de arquitectura/diseño (markdown).
- **Doble verificación trazada de toda info externa** (internet/normativa) contra fuente oficial, ideal por render visual del original. Proyecto delicado: lo usarán instituciones financieras; un número errado es riesgo regulatorio. (Principio no negociable #11.)
- **Verificación antes de ampliar**: re-verificar lo hecho (Tanda 0) antes de producir más.
- **Proceso de producción**: 25 SDD en tandas (ver índice), **fan-out de agentes** (1 por SDD, plantilla común `docs/design/_PLANTILLA-SDD.md`), **integración y revisión por DanIA**. Sesiones frescas con `HANDOFF.md` como puente.
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
- `design/00-INDICE.md` — los 25 SDD y las tandas (T0 verificación → T1 fundación → …).
- `design/_PLANTILLA-SDD.md` — plantilla de cada documento de diseño.

## Git
Repo **privado** en GitHub: **`nexolabs-gh/nikodym`** (cuenta `nexolabs-gh`), branch `main`. Se trabaja aquí mientras se construye la librería; **se moverá a un repo público al terminar**. Push directo a `main` autorizado en el cierre de sesión. Commits con `Co-Authored-By: Claude Opus 4.8`. `.gitignore` veta datos y secretos por defecto (proyecto regulatorio).
