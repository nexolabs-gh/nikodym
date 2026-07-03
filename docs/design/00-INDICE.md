# Índice maestro de diseño — Nikodym RiskLib

| | |
|---|---|
| **Documento** | Índice de Documentos de Diseño (SDD) |
| **Versión** | 1.1 (Tanda 1 Rev) |
| **Fecha** | 2026-06-24 |
| **Base** | [`docs/ESPECIFICACIONES.md`](../ESPECIFICACIONES.md) v1.0 · [`docs/ROADMAP.md`](../ROADMAP.md) |

> **Tanda 1 Rev (2026-06-24):** los 7 SDD de Fundación (01-05, 24, 25) se revisaron de forma adversarial e integraron sus correcciones (cabecera "rev. Tanda 1 Rev" en cada uno). Cambios de alcance: **+SDD-27 `eda`** (de 26 a **27 SDD**); **D2** revierte el `data_hash` a hash de contenido lógico (SDD-02). Detalle de hallazgos y decisiones en el cierre de la sesión.
>
> **Hito 0 — Contratos transversales (2026-06-24):** antes de codificar F0 se estabilizó la *extensibilidad* de los 4 contratos que cruzan todas las capas (orquestación DAG vía `requires`/`provides`; resultados/metrics/overlay con puerta de extensión estructurada; frontera datos transversal-vs-longitudinal; owner del ensamblado de corrida). Decisiones en [`_CONTRATOS-TRANSVERSALES.md`](_CONTRATOS-TRANSVERSALES.md) (CT-1…CT-4), propagadas a SDD-01/02/03 (cabecera "rev. Hito 0"). Estrategia de construcción confirmada: **mixto-troncal-más-incremental** (spike troncal acotado → código F0 → incremental por capa con diseño *just-in-time*).

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
| **06** | `binning` | Scoring | F1 | T2 | 02, 05 | 🟡 Borrador |
| **07** | `selection` | Scoring | F1 | T2 | 06 | 🟡 Borrador |
| **08** | `model` (logística + stepwise) | Scoring | F1 | T2 | 07 | 🟡 Borrador |
| **09** | `scorecard` | Scoring | F1 | T2 | 08 | 🟡 Borrador |
| **10** | `calibration` | Scoring | F1 | T2 | 08 | 🟡 Borrador |
| **11** | `performance` + `stability` | Scoring | F1 | T2 | 09, 10 | 🟡 Borrador |
| **12** | `ml` (SVM/RF/XGB/LGBM/CatBoost) | ML | F2 | T3 | 06, 08 | ⬜ Pendiente |
| **13** | `tuning` (Optuna) | ML | F2 | T3 | 12 | ⬜ Pendiente |
| **14** | `explain` (SHAP + reason codes) | ML | F2 | T3 | 12 | ⬜ Pendiente |
| **15** | `provisioning/cmf` (B-1, matrices, B-3, garantías) | Provisiones | F3 | T4 | 08, 02 | 🟡 Borrador |
| **16** | `provisioning/ifrs9` (PD/LGD/EAD, staging, ECL) | Provisiones | F4 | T4 | 10, 18 | 🟡 Borrador |
| **17** | `provisioning` (orquestación / piso regulatorio) | Provisiones | F4 | T4 | 15, 16 | 🟡 Borrador |
| **18** | `survival` (KM/Cox/AFT/discrete-time) | Forward | F5 | T5 | 08 | 🟡 Borrador |
| **19** | `markov` (transición, term structure) | Forward | F5 | T5 | 02 | 🟡 Borrador |
| **20** | `forward` (macro ARIMA/VAR, satellite, escenarios) | Forward | F5 | T5 | 18, 19 | 🟡 Borrador |
| **21** | `stress` (stress testing, sensibilidad) | Forward | F5 | T5 | 20 | 🟡 Borrador |
| **22** | `validation` | Validación | F6 | T6 | 11, 16 | 🟡 Borrador |
| **23** | `ui` (Streamlit, editor de config) | Producto | F7 | T6 | 05, todos | ⬜ Pendiente |
| **26** | `report` (Quarto HTML+PDF, capa IA, export) | Reporte | F1 | T2 | 01 | 🟡 Borrador |
| **27** | `eda` (tasa de default por período, estabilidad temporal) | Scoring | F1 | T2 | 02 | ✅ Aprobado |

**27 SDD · 7 tandas (T0–T6; T0 = verificación, sin SDD nuevo).** Leyenda estado: ⬜ Pendiente · 🟡 Borrador · 🔵 En revisión · ✅ Aprobado.

> **SDD-27 `eda`** se creó en **Tanda 1 Rev** (decisión D1): el paquete `eda/` figuraba en el árbol de paquetes (ESPEC §6.3) y en el config (SDD-05 §5.1) pero ningún SDD lo cubría — quedaba huérfano. Es el **paso 1 del pipeline de scorecard** (pre-binning, F1/T2), depende de 02 (`data`). **Aguas abajo** 06 (binning), 11 (performance+stability, deslindado) y 26 (report) **consumen sus diagnósticos** (tasa de default por período, figuras), pero NO es una dependencia dura de build de esos SDD — por eso no aparece en su columna "Depende de" (corren sobre el frame de `data`); el orden T2 garantiza que `eda` se diseñe primero.

## Tandas de producción

| Tanda | SDDs | Foco | Pre-requisito |
|---|---|---|---|
| **T0 — Verificación** | (ninguno nuevo) | Doble-check de TODO lo ya hecho (spec, normativa CMF, índice, roadmap, plantilla) contra fuente oficial; corregir antes de avanzar. | — |
| **T1 — Fundación** | 01, 02, 03, 04, 05, 24, 25 | El núcleo del que todo cuelga; sin esto nada es auditable. | T0 |
| **T2 — Scoring (F1)** | 27, 06, 07, 08, 09, 10, 11, 26 | EDA + el MVP open-source + reporte Quarto (release público). | T1 |
| **T3 — ML (F2)** | 12, 13, 14 | Benchmark predictivo + explicabilidad. | T2 |
| **T4 — Provisiones (F3-F4)** | 15, 16, 17 | CMF + IFRS 9 + piso regulatorio. | T2 (PD); T5 parcial (lifetime) |
| **T5 — Forward-looking (F5)** | 18, 19, 20, 21 | Lifetime PD, escenarios, stress. | T2 |
| **T6 — Validación + UI (F6-F7)** | 22, 23 | Backtesting y producto no-code. | T2–T5 |

> **Nota de dependencia cruzada:** IFRS 9 lifetime (SDD-16) usa la term-structure de `survival`/`markov` (T5). Se especifica en T4 con interfaz abstracta y se conecta cuando T5 esté lista (ver roadmap, dependencia F4↔F5).

## Convenciones de los SDD
- Numeración estable (el número no se reutiliza aunque se reordene).
- Cada SDD es autocontenido pero enlaza sus dependencias.
- Las **fórmulas y parámetros normativos** se citan desde [`ESPECIFICACIONES.md`](../ESPECIFICACIONES.md) y [`normativa_cmf_parametros.md`](../normativa_cmf_parametros.md), no se reescriben.
