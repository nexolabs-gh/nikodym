# Índice maestro de diseño — Nikodym RiskLib

| | |
|---|---|
| **Documento** | Índice de Documentos de Diseño (SDD) |
| **Versión** | 1.2 (índice histórico consolidado) |
| **Fecha** | 2026-07-18 |
| **Base** | [`docs/ESPECIFICACIONES.md`](../ESPECIFICACIONES.md) v1.1 · [`docs/ROADMAP.md`](../ROADMAP.md) |

> **Lectura actual:** este índice confirma qué SDD están implementados, pero no es un backlog. Para
> `estable`/`experimental`, gates pendientes y prioridad vigente manda
> [`ROADMAP.md`](../ROADMAP.md).

> **Tanda 1 Rev (2026-06-24):** los 7 SDD de Fundación (01-05, 24, 25) se revisaron de forma adversarial e integraron sus correcciones (cabecera "rev. Tanda 1 Rev" en cada uno). Cambios de alcance: **+SDD-27 `eda`** (de 26 a **27 SDD**); **D2** revierte el `data_hash` a hash de contenido lógico (SDD-02). Detalle de hallazgos y decisiones en el cierre de la sesión.
>
> **Hito 0 — Contratos transversales (2026-06-24):** antes de codificar F0 se estabilizó la *extensibilidad* de los 4 contratos que cruzan todas las capas (orquestación DAG vía `requires`/`provides`; resultados/metrics/overlay con puerta de extensión estructurada; frontera datos transversal-vs-longitudinal; owner del ensamblado de corrida). Decisiones en [`_CONTRATOS-TRANSVERSALES.md`](_CONTRATOS-TRANSVERSALES.md) (CT-1…CT-4), propagadas a SDD-01/02/03 (cabecera "rev. Hito 0"). Estrategia de construcción confirmada: **mixto-troncal-más-incremental** (spike troncal acotado → código F0 → incremental por capa con diseño *just-in-time*).

Este índice lista los **28 Documentos de Diseño (SDD)** que guiaron la construcción de Nikodym
RiskLib. Cada SDD sigue [`_PLANTILLA-SDD.md`](_PLANTILLA-SDD.md) y cubre un módulo del árbol
`src/nikodym/`; un cambio contractual nuevo requiere un SDD nuevo o una revisión explícita.

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
| **01** | `core` | Fundación | F0 | T1 | — | ✅ Implementado |
| **02** | `data` | Fundación | F0 | T1 | 01 | ✅ Implementado |
| **03** | `audit` + `governance` | Fundación | F0 | T1 | 01 | ✅ Implementado |
| **04** | `tracking` (MLflow) | Fundación | F0 | T1 | 01, 03 | ✅ Implementado |
| **05** | Convenciones API + schema de config global | Fundación | F0 | T1 | 01 | ✅ Implementado |
| **24** | Estrategia de testing | Ingeniería | F0 | T1 | 01, 05 | ✅ Implementado |
| **25** | Packaging + CI (uv, hatchling, extras) | Ingeniería | F0 | T1 | — | ✅ Contrato B2.0 aprobado · fundación implementada; gates de distribución pendientes |
| **06** | `binning` | Scoring | F1 | T2 | 02, 05 | ✅ Implementado · estable F1 |
| **07** | `selection` | Scoring | F1 | T2 | 06 | ✅ Implementado · estable F1 |
| **08** | `model` (logística + stepwise) | Scoring | F1 | T2 | 07 | ✅ Implementado · estable F1 |
| **09** | `scorecard` | Scoring | F1 | T2 | 08 | ✅ Implementado · estable F1 |
| **10** | `calibration` | Scoring | F1 | T2 | 08 | ✅ Implementado · estable F1 |
| **11** | `performance` + `stability` | Scoring | F1 | T2 | 09, 10 | ✅ Implementado · estable F1 |
| **12** | `ml` (SVM/RF/XGB/LGBM/CatBoost) | ML | F2 | T3 | 06, 08 | ✅ Implementado · experimental |
| **13** | `tuning` (Optuna) | ML | F2 | T3 | 12 | ✅ Implementado · experimental |
| **14** | `explain` (SHAP + reason codes) | ML | F2 | T3 | 12 | ✅ Implementado · experimental |
| **15** | `provisioning/cmf` (B-1, matrices, B-3, garantías) | Provisiones | F3 | T4 | 08, 02 | ✅ Implementado · experimental |
| **16** | `provisioning/ifrs9` (PD/LGD/EAD, staging, ECL) | Provisiones | F4 | T4 | 10, 18 | ✅ Implementado · experimental |
| **17** | `provisioning` (orquestación / regla del máximo) | Provisiones | F4 | T4 | 15, 16, 28 | ✅ Implementado · experimental |
| **18** | `survival` (KM/Cox/AFT/discrete-time) | Forward | F5 | T5 | 08 | ✅ Implementado · experimental |
| **19** | `markov` (transición, term structure) | Forward | F5 | T5 | 02 | ✅ Implementado · experimental |
| **20** | `forward` (macro ARIMA/VAR, satellite, escenarios) | Forward | F5 | T5 | 18, 19 | ✅ Implementado · experimental |
| **21** | `stress` (stress testing, sensibilidad) | Forward | F5 | T5 | 20 | ✅ Implementado · experimental |
| **22** | `validation` | Validación | F6 | T6 | 11, 16 | ✅ Implementado · experimental |
| **23** | `ui` (React/Vite + FastAPI, editor de config) | Producto | F7 | T6 | 05, 01, 03, 26, todos | ✅ Contrato B2.0 aprobado para B2.1 · backend/front implementados; distribución pendiente |
| **26** | `report` (HTML/PDF/Word, fuente editable, capa IA opcional) | Reporte | F1 | T2 | 01 | ✅ Implementado |
| **27** | `eda` (tasa de default por período, estabilidad temporal) | Scoring | F1 | T2 | 02 | ✅ Implementado · estable F1 |
| **28** | `provisioning/internal` + regla del máximo (dataset → preset → UI → informe) | Producto | F8 | T7 | 08, 10, 15, 17, 23, 26 | ✅ Implementado · experimental |

**28 SDD · 8 tandas (T0–T7; T0 = verificación, sin SDD nuevo).** La madurez pública y la garantía
SemVer se declaran únicamente en `ROADMAP.md`.

> **SDD-28** (post-1.0) hace dos cosas. **(1)** Construye el motor que faltaba: el **método interno** (`PD × LGD × EAD` por grupo homogéneo), que es el que el Capítulo B-1 §3 describe textualmente y que el pipeline de scorecard ya alimenta. **(2)** Le abre la ruta hasta el usuario —dataset, preset, pantalla, capítulo— porque *una feature sin preset, sin pantalla y sin capítulo no existe*, y este proyecto ya lo pagó dos veces.
>
> Su **v1 fue descartada**: diseñaba la demo alrededor de `max(CMF, IFRS 9)` presentado como "el piso prudencial de la CMF", una regla que **no existe** (ver la corrección en SDD-17 §3 y ESPEC §5.4). La regla real del B-1 es `max(estándar, interno)`, a nivel de entidad — y es mejor noticia, porque es citable **y** porque hace que el scorecard entre en el número final.

> **SDD-27 `eda`** se creó en **Tanda 1 Rev** (decisión D1): el paquete `eda/` figuraba en el árbol de paquetes (ESPEC §6.3) y en el config (SDD-05 §5.1) pero ningún SDD lo cubría — quedaba huérfano. Es el **paso 1 del pipeline de scorecard** (pre-binning, F1/T2), depende de 02 (`data`). **Aguas abajo** 06 (binning), 11 (performance+stability, deslindado) y 26 (report) **consumen sus diagnósticos** (tasa de default por período, figuras), pero NO es una dependencia dura de build de esos SDD — por eso no aparece en su columna "Depende de" (corren sobre el frame de `data`); el orden T2 garantiza que `eda` se diseñe primero.
>
> **Diseño ≠ implementación ≠ distribución (B2.0 aprobado, 2026-07-23).** SDD-23 y SDD-25
> aprobaron contractualmente la distribución sobre la base
> `dd89f7d35cefb0aebb4ec2055c4ca81c171dd59e`, tras revisión adversarial sin P0/P1/P2 y auditoría
> API aprobada. El checkout contiene backend FastAPI y frontend React/Vite; los
> artefactos oficiales `1.5.0` instalan el backend pero no incluyen launcher, `__main__`,
> `static/index.html` ni assets JS/CSS. El contrato aprobado B2 separa assets/supply-chain,
> launcher/seguridad local, extra/uploads/presets, clean-room y release; exige procedencia Vite
> autoritativa por output/hash con textos de licencia/atribución íntegros y trazados (pnpm full/prod
> solo reconcilia), cierre Python permisivo base + `[all]` con `[pdf]` separado, veto trazado de
> fixtures demo, upload raw agnóstico y preflight/indexación en la extensión pública de
> `nikodym.run`, token efímero no cacheable y gates F1/F3/F4. F7 permanece no entregado hasta
> publicar y repetir el recorrido desde PyPI. B2.1 está habilitado, pero su implementación sigue
> pendiente: aprobación de diseño no equivale a distribución.
>
> **SDD-23 `ui` reescrito (2026-07-06):** el borrador Streamlit quedó **descartado** (ROADMAP §F7)
> y el SDD pasó al stack React/Vite sobre FastAPI. La implementación histórica del backend/front no
> equivale a la implementación de la distribución aprobada en B2.0.

## Tandas de producción

| Tanda | SDDs | Foco | Pre-requisito |
|---|---|---|---|
| **T0 — Verificación** | (ninguno nuevo) | Doble-check de TODO lo ya hecho (spec, normativa CMF, índice, roadmap, plantilla) contra fuente oficial; corregir antes de avanzar. | — |
| **T1 — Fundación** | 01, 02, 03, 04, 05, 24, 25 | El núcleo del que todo cuelga; sin esto nada es auditable. | T0 |
| **T2 — Scoring (F1)** | 27, 06, 07, 08, 09, 10, 11, 26 | EDA + MVP open-source + informe determinístico (release público). | T1 |
| **T3 — ML (F2)** | 12, 13, 14 | Benchmark predictivo + explicabilidad. | T2 |
| **T4 — Provisiones (F3-F4)** | 15, 16, 17 | CMF e IFRS 9 como motores separados + orquestación configurable. | T2 (PD); T5 parcial (lifetime) |
| **T5 — Forward-looking (F5)** | 18, 19, 20, 21 | Lifetime PD, escenarios, stress. | T2 |
| **T6 — Validación + UI (F6-F7)** | 22, 23 | Backtesting y producto no-code (UI = web premium React/Vite + FastAPI sobre la API pública). | T2–T5 |
| **T7 — Provisiones end-to-end (F8)** | 28 | Método interno B-1 + máximo estándar/interno + ruta hasta UI/informe. | T2, T4, T6 |

> **Nota de dependencia cruzada:** IFRS 9 lifetime (SDD-16) usa la term-structure de `survival`/`markov` (T5). Se especifica en T4 con interfaz abstracta y se conecta cuando T5 esté lista (ver roadmap, dependencia F4↔F5).

## Convenciones de los SDD
- Numeración estable (el número no se reutiliza aunque se reordene).
- Cada SDD es autocontenido pero enlaza sus dependencias.
- Las **fórmulas y parámetros normativos** se citan desde [`ESPECIFICACIONES.md`](../ESPECIFICACIONES.md) y [`normativa_cmf_parametros.md`](../normativa_cmf_parametros.md), no se reescriben.
