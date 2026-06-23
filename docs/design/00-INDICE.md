# Índice maestro de diseño — Nikodym RiskLib

| | |
|---|---|
| **Documento** | Índice de Documentos de Diseño (SDD) |
| **Versión** | 1.0 |
| **Fecha** | 2026-06-23 |
| **Base** | [`docs/ESPECIFICACIONES.md`](../ESPECIFICACIONES.md) v1.0 · [`docs/ROADMAP.md`](../ROADMAP.md) |

Este índice lista **todos los Documentos de Diseño (SDD)** que especifican Nikodym RiskLib a nivel implementable, **antes de escribir código**. Cada SDD sigue [`_PLANTILLA-SDD.md`](_PLANTILLA-SDD.md) y cubre un módulo del árbol `src/nikodym/`.

## Cómo se produce (proceso)
1. **Andamiaje** (hecho): esta plantilla + este índice + el roadmap.
2. **Tanda 0 — Verificación**: antes de producir nada nuevo, se re-verifica que **todo lo ya hecho** (ESPECIFICACIONES, normativa CMF, índice, roadmap, plantilla) esté correcto, con **doble check** de cada dato/tabla/decisión contra su fuente oficial. Se corrige lo que falle. Recién entonces se avanza.
3. **Producción por tandas**: cada tanda agrupa SDDs de una capa/fase y se produce con **fan-out de agentes** (un agente especificador por SDD, siguiendo la plantilla), **integrados y revisados por DanIA**.
4. **Sesiones frescas con HANDOFF** entre tandas (evita degradación de contexto). El `HANDOFF.md` es el puente.
5. Un SDD pasa de *Borrador* → *En revisión* → **Aprobado** solo tras revisión de integración.

> **Regla dura (proyecto delicado):** ningún dato externo se da por válido sin **doble verificación trazada** contra la fuente oficial. Será usado por instituciones financieras.

## Estado global

| SDD | Módulo | Dominio | Fase | Tanda | Depende de | Estado |
|---|---|---|---|---|---|---|
| **01** | `core` | Fundación | F0 | T1 | — | ✅ Aprobado |
| **02** | `data` | Fundación | F0 | T1 | 01 | ✅ Aprobado |
| **03** | `audit` + `governance` | Fundación | F0 | T1 | 01 | ✅ Aprobado |
| **04** | `tracking` (MLflow) | Fundación | F0 | T1 | 01, 03 | ✅ Aprobado |
| **05** | Convenciones API + schema de config global | Fundación | F0 | T1 | 01 | ✅ Aprobado |
| **24** | Estrategia de testing | Ingeniería | F0 | T1 | 01, 05 | ✅ Aprobado |
| **25** | Packaging + CI (uv, hatchling, extras) | Ingeniería | F0 | T1 | — | ✅ Aprobado |
| **06** | `binning` | Scoring | F1 | T2 | 02, 05 | ⬜ Pendiente |
| **07** | `selection` | Scoring | F1 | T2 | 06 | ⬜ Pendiente |
| **08** | `model` (logística + stepwise) | Scoring | F1 | T2 | 07 | ⬜ Pendiente |
| **09** | `scorecard` | Scoring | F1 | T2 | 08 | ⬜ Pendiente |
| **10** | `calibration` | Scoring | F1 | T2 | 08 | ⬜ Pendiente |
| **11** | `performance` + `stability` | Scoring | F1 | T2 | 09, 10 | ⬜ Pendiente |
| **12** | `ml` (SVM/RF/XGB/LGBM/CatBoost) | ML | F2 | T3 | 06, 08 | ⬜ Pendiente |
| **13** | `tuning` (Optuna) | ML | F2 | T3 | 12 | ⬜ Pendiente |
| **14** | `explain` (SHAP + reason codes) | ML | F2 | T3 | 12 | ⬜ Pendiente |
| **15** | `provisioning/cmf` (B-1, matrices, B-3, garantías) | Provisiones | F3 | T4 | 08, 02 | ⬜ Pendiente |
| **16** | `provisioning/ifrs9` (PD/LGD/EAD, staging, ECL) | Provisiones | F4 | T4 | 10, 18 | ⬜ Pendiente |
| **17** | `provisioning` (orquestación / piso regulatorio) | Provisiones | F4 | T4 | 15, 16 | ⬜ Pendiente |
| **18** | `survival` (KM/Cox/AFT/discrete-time) | Forward | F5 | T5 | 08 | ⬜ Pendiente |
| **19** | `markov` (transición, term structure) | Forward | F5 | T5 | 02 | ⬜ Pendiente |
| **20** | `forward` (macro ARIMA/VAR, satellite, escenarios) | Forward | F5 | T5 | 18, 19 | ⬜ Pendiente |
| **21** | `stress` (stress testing, sensibilidad) | Forward | F5 | T5 | 20 | ⬜ Pendiente |
| **22** | `validation` | Validación | F6 | T6 | 11, 16 | ⬜ Pendiente |
| **23** | `ui` (Streamlit, editor de config) | Producto | F7 | T6 | 05, todos | ⬜ Pendiente |
| **26** | `report` (Quarto HTML+PDF, capa IA, export) | Reporte | F1 | T2 | 01 | ⬜ Pendiente |

**26 SDD · 7 tandas (T0–T6; T0 = verificación, sin SDD nuevo).** Leyenda estado: ⬜ Pendiente · 🟡 Borrador · 🔵 En revisión · ✅ Aprobado.

## Tandas de producción

| Tanda | SDDs | Foco | Pre-requisito |
|---|---|---|---|
| **T0 — Verificación** | (ninguno nuevo) | Doble-check de TODO lo ya hecho (spec, normativa CMF, índice, roadmap, plantilla) contra fuente oficial; corregir antes de avanzar. | — |
| **T1 — Fundación** | 01, 02, 03, 04, 05, 24, 25 | El núcleo del que todo cuelga; sin esto nada es auditable. | T0 |
| **T2 — Scoring (F1)** | 06, 07, 08, 09, 10, 11, 26 | El MVP open-source + reporte Quarto (release público). | T1 |
| **T3 — ML (F2)** | 12, 13, 14 | Benchmark predictivo + explicabilidad. | T2 |
| **T4 — Provisiones (F3-F4)** | 15, 16, 17 | CMF + IFRS 9 + piso regulatorio. | T2 (PD); T5 parcial (lifetime) |
| **T5 — Forward-looking (F5)** | 18, 19, 20, 21 | Lifetime PD, escenarios, stress. | T2 |
| **T6 — Validación + UI (F6-F7)** | 22, 23 | Backtesting y producto no-code. | T2–T5 |

> **Nota de dependencia cruzada:** IFRS 9 lifetime (SDD-16) usa la term-structure de `survival`/`markov` (T5). Se especifica en T4 con interfaz abstracta y se conecta cuando T5 esté lista (ver roadmap, dependencia F4↔F5).

## Convenciones de los SDD
- Numeración estable (el número no se reutiliza aunque se reordene).
- Cada SDD es autocontenido pero enlaza sus dependencias.
- Las **fórmulas y parámetros normativos** se citan desde [`ESPECIFICACIONES.md`](../ESPECIFICACIONES.md) y [`normativa_cmf_parametros.md`](../normativa_cmf_parametros.md), no se reescriben.
