# Estado y roadmap de evolución — Nikodym RiskLib

| | |
|---|---|
| **Documento** | Estado por capacidad y plan de evolución |
| **Versión** | 1.3 |
| **Fecha** | 2026-07-21 |
| **Base** | [`ESPECIFICACIONES.md`](ESPECIFICACIONES.md) v1.1 · [`design/00-INDICE.md`](design/00-INDICE.md) |

El código, el tag `v1.4.1` y PyPI están en `1.4.1`. `main` se encuentra en mejora continua; el próximo
release será un bump `1.5.0` con OK específico de Cami.
Las fases F0–F8 que siguen conservan el diseño y los DoD históricos; **no son una cola automática**.
El estado y el plan de esta sección son la fuente vigente.

## Estado actual

| Capacidad | Estado | Límite vigente |
|---|---|---|
| F0/F1 · núcleo y scorecard de comportamiento | **Estable** | Garantía SemVer 1.x para el pipeline F1 |
| F2 · ML/tuning/explain | Implementado, **experimental** | No sustituye la scorecard ni amplía SemVer F1 |
| F3/F8 · CMF, método interno y orquestación | Implementado, **experimental** | Validación humana de matrices/haircuts pendiente |
| F4 · IFRS 9/ECL | Implementado, **experimental** | Independiente del máximo B-1 chileno |
| F5/F6 · forward, survival, Markov, stress y validación | Implementado, **experimental** | Uso por config Python; sin preset/UI propios |
| F7 · UI React/FastAPI e informe | **Incompleta como producto** | El backend viaja en `[ui]`, pero el front no se distribuye ni hay comando de arranque → **B2** |
| Originación/reject inference | Futuro | Requiere caso de uso, priorización y SDD |

## Plan operativo vigente (desde 2026-07-21)

El track pre-reunión quedó cerrado con el release `1.4.1`. Lo que sigue es el plan de mejora continua
fijado el 2026-07-21, ordenado por prioridad de ejecución. **Ningún bloque se inicia por estar en esta
lista**: cada uno arranca cuando el anterior cierra o cuando su condición explícita se cumple.

### Marco de producto (decidido 2026-07-21)

- **La librería es y seguirá siendo 100 % gratuita bajo Apache-2.0.** No hay edición cerrada, tier
  comercial ni funcionalidad reservada. El código que se publica es el código completo.
- **La monetización vive fuera del paquete**: integración en la institución, adaptación o *fork*
  personalizado, funcionalidades a medida y servicios adyacentes de automatización. La librería abre
  la conversación técnica; el trabajo pagado puede terminar siendo otra cosa. Esto **no** condiciona
  qué se publica: nada se retiene del open-source para venderlo aparte.
- **«Instalable y usable» es requisito, no adorno.** Quien ejecute `pip install nikodym` debe poder
  levantar y usar el producto sin conocimiento interno del repo. Una capacidad que existe pero que el
  usuario no puede alcanzar cuenta como no entregada.
- **Los módulos experimentales se mantienen ofrecidos.** F5/F6 amplían lo que la librería puede
  conversar con una institución; no se podan. Lo que les falta es ruta de uso, no justificación.

### B1 · Higiene y deuda corta → habilita `1.5.0`

Cierra los defectos conocidos que hoy sólo viven en el HANDOFF. Todos son acotados y verificables.

1. ~~**Rótulo de los dos ECL del anexo IFRS 9.**~~ **HECHO (2026-07-21, `ee9b0cb`).** Se añadió la
   clave hermana `ecl_by_scenario_basis` (extensión aditiva, CT-3). El rótulo declara **dos**
   motivos de la brecha, no uno: la cifra por escenario no aplica `scenario_weights` **y** cubre el
   horizonte completo, mientras la reportada pondera y trunca Stage 1 a 12 meses. No apunta a
   `staging_distribution` —esa clave vive en la capa UI y no existe en el anexo—.
2. **Deuda cosmética del informe y del editor de config.** Pendiente sólo el primer ítem:
   descriptions del schema con jerga interna (`== @register('standard', …) (SDD-16 §4)`), visibles
   en la UI — su cambio obliga a regenerar `web/src/fixtures/schema.json` en **commit atómico**, así
   que espera a que pase el freeze de la demo. ~~Diagnósticos del motor de selección con decimales
   sin formatear~~ y ~~`total_expected_loss_rate` como string de 51 dígitos~~ **HECHOS (2026-07-21,
   `f34d13c`)**: los `detail` de IV/VIF/correlación/contribución/p-valores pasan a 6 cifras
   significativas y la tasa pasa de texto a `float` (**cambio de tipo** declarado en el CHANGELOG;
   superficie experimental, fuera de la garantía SemVer 1.x).
3. ~~**Respaldo remoto del workspace interno.**~~ **HECHO (2026-07-21).** El workspace interno ya
   tiene repo privado propio fuera del disco local; el respaldo se verificó restaurándolo (clon
   completo, idéntico al original) y se mantiene al día pusheando en cada cierre de sesión.

### B2 · La UI instalable y usable  ← *requisito de producto*

F7 ya **promete** que `pip install nikodym[ui]` trae el front buildeado (ver F7 más abajo). Hoy no lo
cumple, y el hueco es de **distribución, no de ingeniería**: el backend FastAPI sí viaja en el wheel y
`ui/server.py` ya monta los estáticos cuando encuentra el directorio.

1. **Entry point.** `pyproject.toml` no declara `[project.scripts]`: no existe ningún comando. Definir
   el comando de arranque y su contrato (host, puerto, directorio de trabajo, apertura del navegador).
2. **Assets en el wheel.** El build del front (`pnpm build`, no `build:demo`) tiene que producirse en
   el flujo de release y quedar dentro del paquete, con el gate de licencias intacto.
3. **Documentación y gate.** Instalar y levantar en dos comandos, documentado en README y `docs_site`;
   el smoke clean-room debe verificar que la UI **carga**, no sólo que el import no explota.

> **Criterio de aceptación:** un tercero sin acceso al repo instala desde PyPI, levanta la UI, carga
> un dataset propio y obtiene el informe. Mientras eso no ocurra, F7 no está entregado.

### B3 · Abstracción de jurisdicción (CMF ≠ SBS ≠ …)

Hoy el motor de provisiones regulatorias está casado con Chile: `provisioning/cmf/engine.py` concentra
2.044 líneas con ids, carteras y buckets chilenos. En cambio `provisioning/internal/` ya es casi
neutro — su única atadura real es el `default="cmf_portfolio"` de su config.

Se ejecuta en dos etapas con condiciones distintas:

1. **B3.a — SDD + refactor de abstracción (sin implementar ninguna jurisdicción nueva).** Fijar el
   contrato que separa «motor de provisión estandarizada» de «parámetros y reglas de una
   jurisdicción», y dejar `internal/` genuinamente neutro. **Tiene valor por sí solo**: es deuda
   arquitectónica que hoy impide describir con honestidad el costo de un port.
2. **B3.b — Implementación de una jurisdicción concreta.** No se inicia de forma especulativa;
   requiere un compromiso comercial firmado. Sin él, el trabajo es una apuesta sobre normativa
   extranjera que además puede cambiar antes de tener usuario.

> **Regla de honestidad**: mientras B3.b no exista, la librería **no** tiene motor SBS ni de ninguna
> otra jurisdicción, y no se insinúa lo contrario. El módulo `internal/` sí es utilizable hoy fuera de
> Chile, y ése es el alcance real que se comunica.

### B4 · Rutas de uso para F5/F6

F5 (forward, survival, Markov, stress) y F6 (validación avanzada) están implementados y cubiertos por
tests, pero sólo se usan escribiendo el config en Python. Se mantienen en la oferta, así que necesitan
al menos **un preset documentado y un ejemplo ejecutable por capacidad** — no una UI completa. Sin
eso, ofrecerlos es ofrecer algo que el usuario no puede ejecutar.

### B5 · Validación humana de las matrices CMF (gate G0)

Sigue siendo el DoD incumplido de F3 y **no lo puede hacer un agente**. Se ejecuta sí o sí, pero no
encabeza la cola: CMF es Chile y el alcance del proyecto es LATAM. Hasta que ocurra, F3 se comunica
como experimental sin excepción. Detonante natural: el primer compromiso concreto en Chile.

### B6 · Workspace de evidencia de corridas v1

Bloque planificado con anterioridad, mantenido pero **repriorizado según feedback comercial**. Produce
y aprueba un único SDD; la primera rebanada vertical extiende la corrida local existente sin duplicar
un motor MLOps:

1. `SourceSnapshot`: identidad inmutable de fuente/as-of, esquema, conteos y hash lógico; inicialmente
   sólo archivos, datasets sintéticos y uploads ya soportados.
2. `ExecutionLedger`: transiciones y eventos append-only por `Step` en la capa fina runner/API, no en
   `core`.
3. Workspace: listar, reabrir, clonar y comparar corridas compatibles usando manifiestos y resultados
   existentes.

El SDD debe fijar migración de corridas actuales, escrituras atómicas, idempotencia, concurrencia,
crash recovery, codecs JSON/Parquet, exclusión de secretos y reglas de compatibilidad. Estados
asíncronos, cancelación cooperativa y reanudación se implementan sólo cuando el runner pueda cumplirlos
de forma durable; nunca se simulan sobre HTTP.

### B7 · Mapa regulatorio LATAM

Investigación de reguladores de la región, hoy incompleta y con errores detectados por el verificador.
**Queda en plan, sin prioridad.** Material de conversación, nunca de publicación ni de cotización, sin
otra pasada completa de verificación contra fuente oficial.

### B8 · Cola candidata, no autorizada

`SplitPolicy`, `ScenarioContract`, `ValidationLedger`, `SatelliteModel v2`, `PortfolioStress` y
`PortfolioForecast`. Ninguno se inicia por mera presencia en esta lista.

## Historial: P0 — Cierre pre-Interbank *(cerrado con `1.4.1`)*

1. Recuperar **al menos 12 GiB libres** y completar el preflight reproducible de la campaña. El
   corte de esta consolidación quedó bajo ese umbral; no iniciar una ejecución larga con el disco
   en presión.
2. ✅ **Cerrado (2026-07-20).** Las seis brechas de contrato `forward`→IFRS 9 quedaron resueltas
   o caracterizadas con tests, actualizando SDD-16/SDD-20 en el mismo bloque: `rho_col` rechazada
   fail-fast en config (consumo real diferido); exención del `Z` implícito eliminada (Z siempre
   explícito; con fuente forward la vía es `consume_pit`); guard anti doble ajuste PIT/TTC en el
   motor; `forbid_mean_scenario` bloqueante en config y motor (antes sólo auditado); pesos cero
   caracterizados como frontera con tests (resolución de fondo = decisión de política pendiente);
   LGD forward ignorada ahora con aviso auditado `FALTA-DATO-IFRS-6` y golden invariante
   (precedencia pendiente de SDD propio).
3. ✅ **Cerrado (2026-07-20).** Campaña adversarial de la demo F1/F3/F4: caza por 7 ejes → 4 fixes P0/P1
   integrados en `main` (P0 estado obsoleto al cambiar de preset en los 4 caminos; P1 selector de dataset;
   P1 fuga de ruta host en informes F1/F4; P1 `toyaml` stale), con revisor fresco por candidato.
4. ✅ **Cerrado (2026-07-20).** Reproducido el riesgo de resultados obsoletos al cambiar de preset (era
   real) y corregido. Sólo se tocaron P0/P1 verificables.
5. ✅ **Cerrado (2026-07-20).** Gates completos verdes (12/12), revisión independiente y `demo.nikodym.cl`
   re-deployada y verificada por hash contra el SHA aprobado (`1aba6cf`).
6. ✅ **Cerrado (2026-07-20) con el release `1.4.0`.** Al bloque de pulido P2/P3 (locale es-CL,
   marcador «—», descriptions honestas de `rho_col`/`fail_on_falta_dato`, badge «Experimental» en la
   card CMF F3, `to-yaml` determinista y `config_hash` sin `data.load.source`) se sumaron cuatro
   defectos que encontró la verificación adversarial del propio release, todos de cara al lector del
   informe: `Decimal` crudo en las celdas (52 dígitos en la tabla de provisiones internas), tablas de
   10+ columnas ilegibles en el PDF (ahora en hoja apaisada), la tabla insignia de IFRS 9 rotulada
   con su clave interna y la jerga de ingeniería en la prosa (DTO, `ValidationResult`, SDD-16,
   SemVer). Demo recapturada y re-deployada, tag `v1.4.0` y PyPI publicados con OK de Cami. Falta
   sólo congelar antes de la reunión del **2026-07-22**.

El gate humano de las matrices CMF **no** se cerró con este track: sigue abierto como **B5**.

## Qué no hacer

- No retener funcionalidad del open-source para venderla aparte: la librería es gratuita y completa.
- No anunciar ni insinuar un motor de una jurisdicción que no esté implementado (ver B3).
- No implementar una jurisdicción nueva de forma especulativa, sin compromiso comercial (B3.b).
- No copiar DataHub, SQL, defaults ni metodología institucional; sólo reimplementar patrones genéricos.
- No construir conectores remotos antes de fijar `SourceSnapshot`.
- No mezclar `ExecutionLedger` operacional con `ValidationLedger` humano.
- No presentar CMF/IFRS 9/forward/stress como certificados por estar implementados.

## Principios de secuencia
1. **Cada fase entrega valor por sí sola.** No se avanza sin DoD + tests + docs de la anterior.
2. **Fundación primero, auditabilidad desde el día 0.** Sin `core`/`audit`/`governance` nada es reproducible ni defendible.
3. **Lo que produce PD va antes de lo que la consume.** Scoring (F1) es cimiento de CMF, IFRS 9 y lifetime.
4. **Open-source como escaparate** → calidad ejemplar es requisito de cada fase, no un extra.
5. **Dos disciplinas de proceso:** un SDD aprobado antes de codear cada módulo; `HANDOFF.md` como puente entre sesiones.
6. **Doble verificación de toda información externa.** Cada dato/tabla/parámetro de internet o normativa se valida contra la fuente oficial por una segunda vía (ideal: render visual del original). Usado por instituciones financieras → un número errado es riesgo regulatorio. Nada avanza sin doble check trazado.
7. **Verificación antes de ampliar (Tanda 0).** Antes de producir nuevos documentos, se re-verifica que lo ya hecho esté correcto. Ver la Tanda 0 en [`design/00-INDICE.md`](design/00-INDICE.md).

## Mapa de fases

| Fase | Nombre | Entrega clave | Esfuerzo | "¿Qué se puede mostrar?" |
|---|---|---|---|---|
| **F0** | Fundaciones & gobierno | Esqueleto auditable | M | Repo serio, CI verde, lineage |
| **F1** | Scorecard comportamiento | **MVP open-source** | L | Scorecard end-to-end + reporte |
| **F2** | Machine Learning | Benchmark + SHAP | M | CatBoost vs logística, explicado |
| **F3** | Provisiones CMF | Motor B-1 | M | Provisión regulatoria chilena |
| **F4** | IFRS 9 / ECL | ECL independiente | XL | Pérdida esperada bajo IFRS 9 |
| **F5** | Forward-looking | Lifetime + escenarios | XL | Term-structure, macro, Markov |
| **F6** | Validación avanzada | Backtesting | L | Validación formal + backtesting |
| **F7** | UI visual | **App React premium** | L | Web premium sobre la API (local + demo) |
| **F+** | Originación | Reject inference | M | Scorecard de admisión |

Esfuerzo relativo: S < M < L < XL.

---

## F0 — Fundaciones & gobierno
**Objetivo.** El núcleo del que todo cuelga, auditable desde el primer commit.
**SDDs.** 01 core · 02 data · 03 audit+governance · 04 tracking · 05 convenciones+config · 24 testing · 25 packaging/CI. *(El reporte se separó a **SDD-26 `report`** en T2/F1; ver índice.)*
**Entregables.**
- Repo Apache-2.0, `src/` layout, `pyproject.toml` (uv + hatchling, extras declarados).
- `core`: objeto `Study`, config Pydantic v2 (round-trip YAML), registry, orquestación.
- `data`: validación de esquema, definición de target, particiones (Dev/HO/OOT/TTD), missing/special.
- `audit` + `governance`: semilla global, lineage bundle, model card, inventario.
- `tracking` (MLflow local). *(El informe determinístico + capa IA opcional es **SDD-26**, producido en T2/F1, no en F0.)*
- CI (ruff, mypy, pytest), pre-commit, plantillas de issues/PR.
**DoD.** CI verde; un `Study` vacío se crea, serializa y recarga; una corrida trivial emite lineage + model card reproducibles; cobertura base.
**Dependencias.** Ninguna.

## F1 — Scorecard de comportamiento (MVP open-source)
**Objetivo.** Pipeline de scorecard completo, sin reject inference. **Es el activo de marketing.**
**SDDs.** 27 eda · 06 binning · 07 selection · 08 model · 09 scorecard · 10 calibration · 11 performance+stability · 26 report.
**Entregables.**
- EDA de riesgo (SDD-27): tasa de default por período/cohorte, estabilidad temporal (señal de redesarrollo), perfiles univariados.
- Binning OptBinning monótono (WoE), ajuste en Dev → transform al resto.
- Selección: PSI/CSI, IV, ROC/KS/Gini por muestra y período; correlación; descarte por negocio.
- Stepwise (Wald/LR, statsmodels), regla de signos, IV-contribution ≤ 90%.
- Scorecard (offset/PDO, puntos por atributo); calibración de PD.
- Tabla de rendimiento (deciles) + estabilidad del score.
- **Informe HTML/PDF/Word** de la scorecard, con fuente Markdown/Quarto opcional.
**DoD.** Dataset de ejemplo → scorecard reproducible + reporte; tests numéricos de WoE/IV/PSI/escalado contra valores a mano; **release público inicial** en PyPI + GitHub con README, tutorial y ejemplo ejecutable. **Cumplido.**
**Dependencias.** F0.

## F2 — Machine Learning
**Objetivo.** Modelos ML como benchmark de poder predictivo, con explicabilidad.
**SDDs.** 12 ml-models · 13 tuning · 14 explain.
**Entregables.**
- Wrappers SVM, RandomForest, XGBoost, LightGBM, **CatBoost** (extras opcionales), con monotonic constraints donde aplique.
- Optuna (samplers seedeados, search spaces editables).
- SHAP + reason codes; comparativa scorecard vs ML en el reporte.
**DoD.** Mismo pipeline de datos que F1; tuning reproducible (seed); SHAP integrado al reporte; tests de determinismo.
**Dependencias.** F1 (pipeline, binning, model).

## F3 — Provisiones CMF (norma local)
**Objetivo.** Motor de pérdida esperada estandarizada `PE = PI·PDI·Exposición` del Capítulo B-1.
**SDDs.** 15 provisioning-cmf.
**Entregables.**
- Matrices por cartera (comercial individual A1–C6, grupal, consumo 2025, vivienda PVG) como **datos versionados** ([`normativa_cmf_parametros.md`](normativa_cmf_parametros.md)).
- Contingentes B-3 (CCF + override 100% en incumplimiento); sustitución por avales; garantías → PDI.
**DoD.** Cálculo de provisión por cartera reproducible contra casos de ejemplo; **validación humana de las matrices** registrada en governance; tests por cada matriz.
**Dependencias.** F1 (segmentación/PD de entrada). **Riesgo:** los parámetros cambian con la norma → versionar.

> 🔴 **DoD INCUMPLIDO: la validación humana de las matrices SIGUE PENDIENTE.** Los parámetros se transcribieron del compendio **con asistencia de IA y verificación visual**; no son oficiales de la CMF ni están validados por ella (así está confesado en el README y en la landing). **Un gerente de riesgo pregunta por su procedencia en los primeros cinco minutos.** Para cartera de consumo se usa **una sola** matriz (`consumer_standard_v2025`): validarla a mano, celda por celda, **no lo puede hacer un agente**.
>
> **Prioridad fijada el 2026-07-21 (bloque B5):** se hace sí o sí, pero no encabeza la cola — CMF es Chile y el alcance del proyecto es LATAM. Detonante natural: el primer compromiso concreto en el mercado chileno. Mientras tanto F3 se comunica como experimental **sin excepción**.

## F4 — IFRS 9 / ECL
**Objetivo.** ECL de 3 etapas como motor independiente; la orquestación configurable vive en una
capa separada y sólo representa la regla B-1 al comparar estándar CMF con método interno.
**SDDs.** 16 provisioning-ifrs9 · 17 provisioning-orchestration.
**Entregables.**
- PD (12m/lifetime, PIT/TTC Vasicek), LGD (beta/fractional/workout), EAD/CCF.
- Staging (SICR, Stage 1/2/3, backstops 30/90 dpd, umbrales parametrizables).
- Motor ECL con descuento a EIR, multi-escenario ponderado.
- Orquestación: `provisioning` compara **dos fuentes configurables** y aplica la regla declarada.
**DoD.** ECL reproducible sobre dataset de ejemplo; term-structure conectada (interfaz a F5); tests de fórmula (Vasicek, ECL marginal) contra valores canónicos.
**Dependencias.** F4↔F5 (lifetime usa survival/markov; se especifica con interfaz abstracta y se conecta al cerrar F5).

> ⚠️ **CORRECCIÓN NORMATIVA (2026-07-14).** Este roadmap decía *"capa que toma el máximo vs piso CMF"* y *"`provisioning` compara CMF vs IFRS 9 y aplica el máximo"*. **Ese encuadre era falso.** El Cap. A-2 del Compendio **excluye** el deterioro de NIIF 9 sobre las colocaciones, y la regla del máximo del Cap. B-1 (Circular N° 2.346) es entre el **método estándar y el método interno del banco**, por institución. Ver `ESPECIFICACIONES.md` §5.4 y el SDD-17 §3.
>
> **Para el mercado chileno, el ECL de IFRS 9 no es el operando del máximo.** F4 sigue siendo válido para quien sí aplica NIIF 9 completa (filiales que reportan a matriz extranjera, entidades no bancarias, instrumentos distintos de colocaciones).

## F8 — El método interno y la ruta hasta el usuario (post-1.0)
**Objetivo.** Que un gerente de riesgo pueda **ver** la provisión que la norma le obliga a constituir.
**SDD.** 28 provisiones-end-to-end.
**Entregables.**
- ✅ `provisioning/internal`: el **método interno** del B-1 (`Exposición · PD · LGD` por grupo homogéneo). La PD sale del scorecard → **el modelo del banco entra en la provisión reportada**.
- ✅ Orquestador con fuentes configurables + `rule="use_internal"`.
- ✅ Dataset `provisiones_consumo` y capítulos condicionales del informe.
- ✅ **La ruta hasta el usuario**: preset, serializer, pantalla y capítulo del informe F3, integrada y
  recapturada en la demo multi-dominio.
**DoD.** La cadena corre de punta a punta desde la UI y el informe trae la cifra; validación **humana** de la matriz de consumo contra el compendio (gate G0).

## F5 — Forward-looking & dinámica
**Objetivo.** Lifetime PD, proyección macro y escenarios.
**SDDs.** 18 survival · 19 markov · 20 forward-macro · 21 stress.
**Entregables.**
- Survival (KM, Cox, AFT, discrete-time hazard) → lifetime PD; reusa stack de regresión.
- Markov (cohort/duration/generador, embedding) → term structure.
- Macro ARIMA/VAR + satellite models (Wilson logit) + escenarios ponderados (≥3).
- Stress testing (escenarios severos, sensibilidad).
**DoD.** Curvas lifetime PD reproducibles por ambas rutas (survival y matriz); consistencia PIT en la cadena; tests numéricos.
**Dependencias.** F1 (regresión). Cierra el lifetime de F4.

## F6 — Validación avanzada
**Objetivo.** Validación formal y backtesting integrados. (El módulo `stress/` se construye en F5; aquí se valida y se hace backtesting.)
**SDDs.** 22 validation.
**Entregables.** Discriminación (ROC/AUC, Gini, KS), calibración (Hosmer-Lemeshow, binomial, traffic-light, Brier), estabilidad (PSI), backtesting realizado-vs-estimado (t-test ECB).
**DoD.** Suite de validación ejecutable sobre cualquier modelo del repo; informes HTML/PDF/Word de validación.
**Dependencias.** F1–F5.

## F7 — UI visual
> **Rumbo actualizado (2026-07-04): UI = app React/Vite premium, NO Streamlit.** El contrato de
> `design/23-ui.md` se implementó sobre React/FastAPI; sus referencias históricas a Streamlit no
> describen el producto actual.

**Objetivo.** Web premium sobre la API que construye y visualiza el `Study` (editor del config Pydantic), para dos públicos: analistas técnicos (MVP/benchmark rápido) y gerentes de riesgo no-técnicos (demo de venta).
**SDDs.** 23 ui *(contrato evolucionado e implementado sobre React/FastAPI)*.
**Stack.** React + Vite + Tailwind + shadcn/ui + charts premium; backend **FastAPI**; **cero lógica propia** (todo invoca la API de la lib).
**Dos modos de despliegue.**
- **Local (analista):** `pip install nikodym[ui]` trae el React ya buildeado + levanta FastAPI local; los datos no salen de su máquina. 🔴 **PROMESA INCUMPLIDA** — el extra `[ui]` instala el backend FastAPI y `ui/server.py` monta los estáticos si los encuentra, pero **el front buildeado no viaja en el wheel y no existe `[project.scripts]`**: no hay comando de arranque ni documentación. Es el bloque **B2** del plan operativo; hasta cerrarlo, F7 no está entregado.
- **Hosteada (comercial):** `nikodym.cl/demo`, dataset **sintético** precargado, flujo guiado "arma tu modelito en pocos pasos" + CTA de lead comercial.
**DoD.** Un modelo F1 completo construible 100% desde la UI, idéntico al hecho por código; look&feel premium aprobado por revisión visual.
**Dependencias.** Todo el core (motor V1 ✅ completo 2026-07-04).

## F+ — Originación & reject inference (insertable)
**Objetivo.** Scorecard de admisión cuando haya caso de uso.
**Entregables.** Muestra TTD (through-the-door), reject inference (parcelling/fuzzy/reweighting) validado por outcomes.
**Cuándo.** Insertable tras F1, cuando un cliente lo requiera.

---

## Estrategia de release (open-source)
- `1.4.1` es la versión del código/tag y la publicada en PyPI; el próximo release será `1.5.0` (bump
  con OK específico de Cami). El pipeline F1 conserva la garantía SemVer 1.x.
- **`1.5.0` = cierre de B1** (rótulo ECL + deuda cosmética). **`1.6.0` = cierre de B2** (UI instalable).
  Se publican por separado: atar el release de higiene a la distribución de la UI retrasa correcciones
  ya listas sin beneficio para nadie.
- La librería se publica **completa y gratuita** bajo Apache-2.0. Ninguna capacidad se retiene del
  paquete público por motivos comerciales.
- Releases incrementales con changelog, docs MkDocs, dataset/tutorial reproducible y smoke clean-room.
- Cada tag y publicación PyPI requiere OK específico de Cami; push/deploy ordinarios no sustituyen ese gate.

## Puentes de sesión
- Entre tandas/fases: `cierre-trabajo` → `HANDOFF.md` → `inicio-trabajo` en sesión fresca.
- El HANDOFF resume estado, decisiones y siguiente paso. Warm start desde el HANDOFF, no re-explorar todo.
