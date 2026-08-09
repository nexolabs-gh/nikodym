# SDD-30 — Readiness integral de producto

> **Estado: APROBADO.** Cami aprobó expresamente el 2026-08-09 este SDD,
> **D-RDY-ABA-1…6** y las decisiones H1=A, H2=A, H3=A, H4=A, H5=A, H6=A, H7=A, H8=A, H9=B,
> H10=A y H11=A. La aprobación habilita las oleadas en el orden de §7.5; no autoriza por sí sola
> publicar PyPI ni recapturar la demo, que conservan sus OK específicos.
>
> **Identificación.** El índice conserva numeración estable y SDD-28 reservó el número 29 para el
> CLI. Por eso el siguiente identificador disponible es **SDD-30**; el 29 no se reutiliza.

| Campo | Valor |
|---|---|
| **SDD** | 30 |
| **Módulo** | Contrato transversal de `nikodym` — no crea un paquete `readiness` |
| **Fase** | F0–F8, cierre transversal de producto |
| **Tanda de producción** | T8 aprobada, por oleadas (§7.5) |
| **Estado** | Aprobado por Cami el 2026-08-09 |
| **Depende de** | SDD-01/02/06/08/09/10/11/16/18/19/20/21/23/25/26/28 y contratos vigentes en `DECISIONES-VIGENTES.md` |
| **Lo consumen** | Todos los flujos públicos, CI/release, UI, landing, demo, docs e informes |
| **Autor / Fecha** | Codex, con censos independientes y revisión adversarial / 2026-08-09 |

## Recomendación ejecutiva

Adoptar **readiness por flujo con una puerta global acumulativa**: Nikodym sólo podrá presentarse
como integralmente lista cuando cada flujo obligatorio pueda ejecutarse desde una instalación
limpia, con datos propios, artefactos persistibles, salida reconciliable, lineage completo,
envelope medido y evidencia final renderizada. Los módulos o fórmulas aislados no bastan.

La secuencia recomendada es una sola: primero cerrar el fundamento productivo de
entrenamiento/apply y los gates transversales; después LGD/EAD; luego PD temporal; a continuación
IFRS 9 + forward y stress conectados al engine real; por último informes, arquitectura pública y
distribución exacta. No se optimiza antes de medir un baseline y no se promociona una release
reconstruyendo artefactos.

---

## 1. Propósito y responsabilidad

**Qué resuelve.** Define qué significa que Nikodym esté lista para que un equipo de riesgo de
crédito la instale y la use de punta a punta para desarrollar, validar, persistir, aplicar,
provisionar, estresar, auditar y comunicar resultados.

**Responsabilidad única.** Este SDD:

- convierte la dirección de producto en flujos, estados, Definition of Done (DoD), evidencias y
  controles negativos falsables;
- fija contratos transversales que hoy quedan entre módulos: artefactos aplicables, tratamientos en
  inferencia, lineage de entorno, escala, semántica de tablas y promoción exacta de distribución;
- clasifica cada brecha como defecto, integración pendiente, capacidad deliberadamente no
  soportada o decisión humana;
- enmienda la semántica de opciones de D-ABA para que toda opción seleccionable
  ejecute una rama real con efecto verificable;
- ordena la implementación en oleadas dependientes sin reabrir decisiones ya aprobadas.

**Límites explícitos.** Este SDD:

- no implementa por sí mismo ninguna capacidad; la ejecución respeta el orden de oleadas de §7.5;
- no define covariables WoE para LGD: la LGD modelada consume el frame crudo, conforme a D-LGD;
- no modifica CMF ni sus tests, y no mezcla el motor CMF con IFRS 9;
- no resuelve D-VIS-6 ni el hallazgo metodológico de gains;
- no reabre los seis defectos de prosa cerrados sin una regresión reproducible;
- no convierte la memoria histórica interna en metodología; se usó sólo como checklist
  adversarial de fugas, doble conteo, procedencia y ejecución durable;
- no incluye `PortfolioStress` de saldos/capital sin la elección metodológica de H8;
- no autoriza tag, release PyPI ni recaptura de demo. Cada una conserva su OK específico.

## 2. Contexto y ubicación en la arquitectura

Readiness no es un módulo nuevo ni una etiqueta de marketing. Es una propiedad demostrada de una
cadena completa:

```text
datos propios
   │
   ├─ entrenamiento ─ artefacto versionado ─ apply batch ─ salida fila a fila
   │                                      │
   │                                      └─ validación / gobierno / informe
   │
   └─ PD temporal ─ forward ─ LGD(t) / EAD(t) ─ IFRS 9 ─ stress económico
                                                        │
                                                        └─ HTML / PDF / DOCX

wheel + sdist gateados ─ clean-room por flujo ─ promoción de los mismos bytes ─ tercero sin checkout
```

### 2.1 Estados de readiness

Cada flujo tendrá un estado durable, derivado de evidencia y no de prosa:

| Estado | Significado |
|---|---|
| `no_alcanzable` | Existe código parcial, pero un usuario de `pip install` no puede completar el flujo. |
| `experimental` | El flujo es alcanzable, pero falta al menos un gate de exactitud, apply, escala, artefacto final o clean-room. |
| `gateado` | Cumple su DoD, controles positivos/negativos y clean-room sobre los artefactos candidatos. |
| `publicado` | Los mismos bytes gateados fueron publicados con OK específico y un tercero los verificó sin checkout. |

La librería sólo será **integralmente lista** cuando todos los flujos obligatorios de la matriz §6
estén al menos `gateado`. `publicado` es una fase de distribución posterior y no se infiere de un
`main` verde.

### 2.2 Regla de evidencia

Toda evidencia de readiness debe identificar como mínimo:

- flujo, versión del contrato, commit, wheel y sdist con SHA-256;
- `data_hash`, `config_hash`, hash del artefacto fiteado y `uv_lock_hash`/manifiesto de build;
- entorno runtime normalizado, plataforma y hardware de referencia;
- dimensiones del caso, tiempos, peak RSS y bytes de salida;
- gates positivos, controles negativos, artefacto final y resultado;
- procedencia de datos sintéticos, escenarios, supuestos y cualquier `DATO-INSTITUCIONAL`.

La evidencia es inmutable por candidato. Reejecutar crea una evidencia nueva; no sobrescribe la
anterior.

## 3. Conceptos y fundamentos

### 3.1 Entrenamiento, validación y aplicación

- **`fit`** estima tratamientos, bins, coeficientes, escala o calibración usando sólo Desarrollo.
- **validación** evalúa con parámetros congelados sobre Holdout/OOT. Alterar target o predictores de
  HO/OOT no puede cambiar el artefacto fiteado.
- **`apply`** transforma una cartera nueva sin target ni partición, sin ejecutar ningún `fit` y sin
  modificar el bundle. Un target opcional sólo puede usarse después para monitoreo/backtesting.
- **fila verificable** significa que cada resultado referencia una identidad estable de entrada y
  permite reconstruir las decisiones de tratamiento, WoE, predictor lineal, score y PD sin invertir
  el score ni adivinar defaults.

### 3.2 Tratamientos en cartera nueva

El orden contractual es:

1. validar esquema, tipos, unicidad e identidad de fila;
2. reconocer códigos especiales declarados **antes** de convertir missing;
3. aplicar la política explícita de missing;
4. aplicar la política explícita de outlier aprendida sólo en Desarrollo o provista por la
   institución;
5. resolver categorías conocidas, `other` entrenado y categorías nuevas según una política
   declarada;
6. transformar a WoE con bins congelados;
7. calcular `eta` y `pd_raw` desde el modelo;
8. calcular puntos y score, incluidos rounding/clipping/overrides del artefacto;
9. calcular `pd_calibrated` desde el calibrador, nunca invirtiendo el score.

Un centinela como `-99999` conserva su identidad y su rama durante `apply`, aunque no haya aparecido
en Desarrollo. Eso **no inventa un WoE**: si el estado no tuvo soporte en fit, se aplica H2 —error o
mapping provisto— y la fila no se puntúa silenciosamente. `special` y missing genuino sólo pueden
converger si la política aprobada es explícitamente `as_missing`; con `separate` deben seguir
produciendo tratamientos distintos.

Missing, especiales, categorías nuevas, outliers y particiones son **mecanismos**. Este SDD no
inventa su metodología: la política se declara por variable, queda congelada en el artefacto y
falla cerrada cuando falta. No hay aprendizaje en HO/OOT ni en `apply`.

### 3.3 Pérdida esperada y descuento

La identidad auditable permanece:

\[
ECL_{i,s,t}=PD^{marg}_{i,s,t}\times LGD_{i,s,t}\times EAD_{i,s,t}\times DF_{i,t}
\]

con:

\[
DF_{i,t}=(1+EIR_i)^{-\tau_t}
\]

`EAD(t)` y `DF` son componentes distintos. Amortización, prepagos, drawdowns, castigos y ajustes
institucionales cambian exposición; EIR cambia sólo descuento. Ningún campo o ajuste puede entrar
en ambas rutas.

El perfil auditable mínimo por operación/período contiene `ead_base`, `scheduled_drawdown`,
`contractual_amortization`, `prepayment`, `writeoff`, `other_adjustment`, `ead_final`, procedencia y
regla aplicada. La reconciliación es:

\[
EAD^{final}_{i,t}=
EAD^{base}_{i,t}+drawdown_{i,t}-amortization_{i,t}-prepayment_{i,t}
-writeoff_{i,t}+adjustment_{i,t}
\]

La fórmula es una identidad de movimientos, no una estimación de comportamiento. Un resultado
negativo es error de reconciliación; Nikodym no lo lleva silenciosamente a cero. La fuente de cada
componente —provista, contractual o modelada— sigue siendo una decisión explícita. La vía
`provided` preserva una EAD institucional precalculada y no obliga a descomponerla artificialmente.

### 3.4 PD temporal, forward y stress

- Markov y survival son métodos alternativos de **PD temporal**; no son productos pares ni engines
  de ECL.
- Forward transforma trayectorias macro y componentes de riesgo con basis/procedencia explícitos.
- IFRS 9 es el único owner de staging, horizonte 12m/lifetime, ponderación de escenarios, EIR y ECL.
- El stress económico actual aplica shocks y sensibilidad sobre el flujo forward→IFRS 9 real. Un
  stub que comparte el nombre `calculate` no es evidencia de integración.
- `PortfolioStress` proyectaría saldos, runoff, originación, castigos, recuperaciones, garantías y
  capital. Es otro alcance y requiere metodología propia.

Toda curva declara `pd_basis` (`TTC`, `PIT` o `forward_PIT`), horizonte, unidad temporal, escenario y
procedencia. Una transformación PIT/forward no puede aplicarse dos veces. Un escenario ponderado es
un resultado; no puede entrar de nuevo como escenario `mean` junto a sus componentes.

### 3.5 Opción real

Una opción es real si, sobre un fixture que discrimina sus ramas:

1. el dispatcher ejecuta código distinto;
2. cambia al menos un output contractual, artefacto, regla de validación o trayectoria auditada;
3. el efecto es verificado por un oráculo independiente del mismo dispatcher.

Cambiar sólo un rótulo de metadata no cuenta. Dos alias matemáticamente equivalentes no son dos
opciones de producto: uno se retira del selector y, si SemVer lo exige, se conserva temporalmente
como alias de compatibilidad con deprecación explícita.

## 4. API pública (contrato)

Las firmas son ilustrativas y no autorizan implementación.

### 4.1 Bundle de scoring/PD

```python
class FittedScorecardBundle:
    schema_version: str
    fitted_at: datetime
    input_schema: InputSchemaContract
    row_identity: RowIdentityContract
    treatment_policy: TreatmentPolicy
    special_catalog: SpecialCatalog       # declarados, aunque no observados
    binner: FittedBinningArtifact
    feature_mapping: FeatureMapping
    model: FittedLogisticPdArtifact
    scorecard: FittedPointsArtifact
    calibrator: FittedCalibrationArtifact
    lineage: ArtifactLineage

    @classmethod
    def fit(cls, development_frame, *, config, validation_frames=None): ...
    def save(self, path): ...
    @classmethod
    def load(cls, path, *, verify_hashes=True): ...
    def apply(self, raw_frame, *, trace="full") -> ScorecardApplicationResult: ...
```

El bundle contiene sólo especificación y parámetros necesarios para transformar; no contiene el
dataset de cliente. El formato recomendado en H1 es abierto, versionado y sin ejecución de objetos
arbitrarios: manifiesto JSON + tablas columnares + hashes dentro de un bundle determinista.

`ScorecardApplicationResult` publica:

- `application_frame`: una fila por identidad de entrada, mismo orden, con `input_row_hash`, flags
  de tratamiento, `scoring_status` (`scored` o `not_scorable`), `rejection_reason`, `eta`, `pd_raw`,
  `score_unrounded`, `score`, `pd_calibrated`, `warning_codes` y hash de la traza. Los cinco outputs
  numéricos son nulos en una fila `not_scorable`; la fila nunca desaparece ni recibe un valor
  inventado;
- `woe_frame`: WoE de las variables finales por fila;
- `treatment_trace`: forma larga `row_id × feature` con regla, estado
  (`observed/missing/special/unseen/outlier`), bin/category id, valor transformado y warning;
- `summary`, `lineage` y hash del bundle aplicado.

La implementación puede escribir por lotes/particiones para no materializar todo en RAM, pero la
semántica y el orden total son los mismos.

### 4.2 Bundle de LGD

```python
class FittedLgdBundle:
    method: Literal["beta_regression", "fractional_response"]
    raw_covariates: tuple[str, ...]       # nunca WoE supervisado contra default
    input_schema: InputSchemaContract
    treatment_policy: TreatmentPolicy
    fitted_parameters: LgdParameters
    lineage: ArtifactLineage

    @classmethod
    def fit(cls, development_frame, *, config): ...
    def save(self, path): ...
    @classmethod
    def load(cls, path, *, verify_hashes=True): ...
    def apply(self, raw_frame) -> LgdApplicationResult: ...
```

`provided`, `recovery` y `workout` se preservan como estrategias de `LgdEngine`; no se fuerzan a
fingir un `fit`. Las ramas modeladas sí separan fit/persist/load/apply fuera de muestra.

### 4.3 Perfil EAD y engine IFRS 9

```python
class EadProfileResult:
    detail: DataFrame  # operación × período; componentes y reconciliación de §3.3
    source: Literal["provided", "ccf", "contractual", "modeled"]
    assumptions: tuple[ResolvedAssumption, ...]
    lineage: ArtifactLineage

class Ifrs9ApplicationResult:
    staging: DataFrame
    detail: DataFrame  # operación × escenario × período
    summary: DataFrame
    scenario_reconciliation: DataFrame
    lineage: ArtifactLineage
```

IFRS 9 consume una PD temporal, una LGD y una EAD con basis/procedencia explícitos. Si recibe dos
fuentes incompatibles para el mismo componente sin la política H5 declarada, falla antes de
calcular; la precedencia silenciosa queda prohibida.

### 4.4 Stress conectado

Stress consume una interfaz adaptada al engine IFRS 9 real y devuelve baseline/stressed con el
mismo esquema de detalle y reconciliación. El protocolo debe validar firma, tipos, artefactos y
provenance; `runtime_checkable` por coincidencia nominal no basta.

### 4.5 Evidencia de readiness

```python
class ReadinessEvidence:
    contract_version: str
    flow: str
    candidate_hashes: DistributionHashes
    lineage: ArtifactLineage
    profile: ScaleProfile
    measurements: ResourceMeasurements
    positive_gates: tuple[GateResult, ...]
    negative_controls: tuple[GateResult, ...]
    final_artifacts: tuple[ArtifactEvidence, ...]
```

No hace falta exponer una clase pública con ese nombre si el mismo contrato se representa en JSON;
la forma y los invariantes sí son obligatorios.

## 5. Configuración (schema Pydantic)

### 5.1 Política de inferencia

El artefacto congela, por variable:

| Política | Valores contractuales | Regla |
|---|---|---|
| missing | `error`, `separate_trained`, `provided_mapping` sólo con H2=B | No se imputa ni se crea WoE sin soporte explícito. |
| special | `error`, `separate_trained`, `as_missing_trained`, `provided_mapping` sólo con H2=B | Catálogo completo declarado, observado o no. |
| categoría nueva | `error`, `trained_other`, `provided_mapping` sólo con H2=B | `trained_other` sólo si ese bin existió en fit. |
| outlier | `none`, `error`, `cap_fitted`, `separate_fitted` | Umbrales sólo de Desarrollo o provistos. |
| columna faltante | `error` | No existe fallback silencioso. |
| columna adicional | `allow_audited`, `error` | Nunca entra al modelo sin estar en el artefacto. |

`provided_mapping` identifica el estado de origen, el bin entrenado de destino, fuente, responsable
y justificación; conserva el special/unseen original en la traza. No admite un número WoE libre.
Un estado `separate_trained`/`trained_other` sin observaciones y eventos/no-eventos suficientes en
Desarrollo no tiene WoE estimable y falla. H2 decide la política productiva; no existe WoE neutral o
prior implícito.

### 5.2 Particiones

- `fit_partition="desarrollo"` es fijo para F1 estable.
- HO y OOT son transform-only; no participan en bins, selección, coeficientes, calibración ni
  tratamientos aprendidos.
- `apply` no crea Dev/HO/OOT ni exige target. Declara `population_role="inference"`.
- Un monitoreo posterior puede anexar outcomes y períodos sin mutar el bundle.

### 5.3 Escenarios y componentes IFRS 9

Cada escenario declara nombre, peso, source id, versión, fecha de corte, hash, frecuencia,
granularidad, unidad, transformación, basis y owner. Los pesos son finitos, no negativos y suman uno
dentro de tolerancia. H6 decide si peso cero se normaliza/filtra o se rechaza; nunca se acepta de
forma distinta entre forward e IFRS 9.

En un flujo productivo no se materializa ningún `default_a_confirmar`: fuente, path/artefacto,
versión, fecha de corte, pesos efectivos y transformaciones son explícitos. Defaults ilustrativos
pueden existir sólo en fixtures/tutoriales marcados `illustrative` y no cuentan como clean-room de
readiness.

La alineación frecuencia×granularidad se declara como una de cuatro operaciones cerradas:
`exact`, `aggregate_declared`, `broadcast_declared` o `interpolate_declared`. Las últimas tres
incluyen keys de join, ventana, agregador/interpolador, tratamiento de bordes y unidad. Si dos
datasets no coinciden y no existe mapping, el preflight falla; no hay broadcast, forward-fill ni
interpolación implícitos.

PD, LGD y EAD declaran por separado:

- `basis` y horizonte;
- fuente (`provided`, `fitted`, `forward_adjusted`);
- overlays aplicados, orden, signo y responsable;
- escenario y granularidad;
- si la cifra ya incorpora macro. Un componente marcado `forward_adjusted` no vuelve a pasar por
  otro ajuste macro equivalente.

Todo `FALTA-DATO-FWD-*` o `FALTA-DATO-STR-*` alcanzable por la rama elegida impide que ese flujo
quede `gateado`. En particular bloquean la ausencia de paths/shocks, la precedencia LGD pendiente y
la conexión stress↔IFRS real. Un `DATO-INSTITUCIONAL` no es deuda del motor, pero el fixture
clean-room debe suministrarlo con procedencia; Nikodym nunca lo inventa.

### 5.4 Contrato longitudinal independiente (CT-3)

El frame transversal de scoring no se reutiliza como si contuviera una serie longitudinal. Cada
dataset longitudinal conserva hash, schema, as-of y source propios:

| Dataset | Clave única mínima | Contenido |
|---|---|---|
| `operations_as_of` | `(portfolio_id, operation_id, as_of_date)` | Atributos vigentes de operación, stage inputs y moneda. |
| `risk_component_path` | `(portfolio_id, operation_id, as_of_date, scenario, period)` | `time_value`, `time_unit` y PD/LGD/EAD con basis/source; cada componente es opcional según la rama. |
| `macro_path` | `(source_id, version, scenario, period, factor)` | Valor, unidad, frecuencia, granularidad y fecha de publicación. |
| `transition_ledger` | `(entity_id, observation_time)` | Estado, segmento y cohorte para Markov/roll-rate. |
| `survival_ledger` | `(entity_id, origin_date, observation_time)` | Duración, evento/censura, segmento y covariables crudas. |

Invariantes:

- no hay duplicados en la clave declarada ni joins implícitos por posición;
- `as_of_date` es único por corrida o existe una política de snapshot explícita;
- períodos y `time_value` crecen, su unidad viaja y el horizonte concuerda;
- el conjunto de escenarios coincide con el de pesos efectivos;
- granularidad/frecuencia sólo cambian mediante el mapping declarado en §5.3;
- cada input aporta `data_hash`, fuente, versión, fecha de corte y filas rechazadas;
- cualquier broadcast cuenta→segmento o escenario→cartera es explícito y reconciliable.

### 5.5 Perfiles de escala

Antes de optimizar se mide el siguiente grid fijo. S1/S2 son candidatos de compromiso para H9, no
copy público mientras sus gates sigan rojos:

| Perfil | Filas/operaciones | Variables | Cardinalidad máx. | Horizonte | Escenarios | Hardware/RAM objetivo | Tiempo objetivo |
|---|---:|---:|---:|---:|---:|---|---|
| `S0-smoke` | 10.000 | 25 | 100 | 12 | 1 | CI, peak RSS ≤4 GiB | ≤5 min por flujo |
| `S1-local` | 100.000 | 50 | 10.000 | 60 | 3 | 8 vCPU/16 GiB, peak ≤12 GiB | train ≤15 min; batch/temporal ≤20 min |
| `S2-equipo` | train 1 M; batch 5 M; temporal 100.000 ops | 100 | 100.000 | 120 | 5 | 16 vCPU/32 GiB, peak ≤24 GiB | train ≤45 min; batch ≤20 min; temporal ≤60 min |

Para ECL temporal, `filas` significa operaciones de entrada y se registra además el número real de
filas operación×período×escenario. Para UI se prueban N−1/N/N+1 respecto del límite de bytes y los
resultados paginados.

UI S1 acepta hasta 50 MiB; UI S2, hasta 100 MiB. En ambas el acuse/job id y una página de resultados
tardan ≤2 s en el hardware de referencia; el cálculo total hereda el budget de su flujo. Esos
tiempos se miden con caché fría y caliente por separado.

Cada medición registra wall time, CPU time, peak RSS, bytes de entrada/salida, páginas/chunks,
hardware, SO, Python, dependencias y hashes. Entrenamiento, inferencia batch y UI tienen resultados
separados. Tras elegir H9 nace `S3-limite`: N−1/N/N+1 sobre cada dimensión del envelope aprobado,
con proceso aislado y límite de recursos para que un baseline rojo no agote el host.

## 6. Contratos de datos y matriz flujo × estado × DoD × evidencia

La matriz describe el baseline medido sobre `bb3141b47106cc6e316856bc8c933c02f1568475`.
Los IDs son estables. `M` exige estado `gateado` para readiness global; `T` es gate transversal que
deben cumplir todos los `M`; `C(Hn)` se vuelve `M` sólo si la decisión indicada lo activa; `X` está
excluido; `P` sólo existe después de una publicación autorizada.

| Flow ID · alcance | Estado actual medido | Definition of Done | Evidencia exigida |
|---|---|---|---|
| `F-SCORE-TRAIN · M` | F1 real y estable; fit en Desarrollo y transform Dev/HO/OOT. | Fit no usa HO/OOT; artefacto completo, versionado y reproducible. | Golden manual, anti-leakage y hashes del bundle. |
| `F-SCORE-APPLY · M` | `no_alcanzable`: hay piezas separadas, no bundle/API targetless. | `fit→save→load en proceso limpio→apply`; una fila de salida por entrada, puntuada o `not_scorable`. | Equivalencia contractual, golden puntuable y rechazo estructurado. |
| `G-INFERENCE-TREATMENT · T` | `-99999` puede colapsar con missing y un special no observado no se congela. | Identidad preservada; tratamiento soportado o fail-closed/mapping conforme a H2. | `-99999` sólo en apply; mutación de orden pone rojo. |
| `G-OPTION-EFFECT · T` | 207 pares: 197 disponibles, 5 `sin_efecto`, 2 `no_implementada`, 3 condicionados. | Cero seleccionables sin `effect_oracle`; catálogo↔schema↔dispatcher bidireccional. | Censo exacto y fixture discriminante por opción. |
| `G-LINEAGE · T` | Campo/helper `uv_lock_hash` existe, pero `Study` fija `None`; fixtures quedan null. | Hash de build y runtime no nulos; data/config/artifact hashes completos. | Repetición estable; lock alterado cambia hash; ausencia falla explícitamente. |
| `G-SCALE · T` | Sin benchmark de filas/variables/cardinalidad/RAM/tiempo. | Baseline S0–S2, envelope H9 y `S3-limite`; no OOM silencioso. | Evidencia de recursos por fase/hardware. |
| `F-SCORE-BATCH · M` | Sin superficie productiva ni perfil de escala. | Apply streaming/chunked, orden estable y envelope propio. | S1/S2 elegido, peak RSS y equivalencia con ejecución no chunked. |
| `F-UI · M` | Síncrona; 100 MiB se valida después del parse/spool; resultados sin paginación. | Rechazo temprano N+1, paginación estable; lifecycle según H10. | N−1/N/N+1, cursor negativo y budget de respuesta. |
| `F-LGD-BASE · M` | Provided/recovery/workout implementadas y legítimas. | Se preservan, con salida/procedencia por operación. | Golden recovery/workout y EIR propia de workout. |
| `F-LGD-OOS · M` | Beta/fractional hacen fit y predict in-sample. | Fit/persist/load/apply OOS, frame crudo, cero WoE de default. | Spy anti-refit, target OOS irrelevante y equivalencia tras reload. |
| `F-EAD-BASE · M` | Provided y CCF funcionan; PD×LGD×EAD está implementado. | Mantener ambas vías y reconciliar por operación/período. | Golden manual y EAD institucional precalculada. |
| `F-EAD-T · M` | Perfil constante y marca IFRS-4; longitudinal se rechaza. | Perfil auditable con movimientos según H4. | Reconciliación; EIR no cambia EAD. |
| `F-CMF-REFERENCE · M` | Caso de referencia existente, congelado y probado. | Preservarlo separado de IFRS 9 y sin ampliar promesa local. | Golden/regulatorio y clean-room del flujo publicado. |
| `F-PD-SURVIVAL · M` | Método temporal implementado, experimental, sin capítulo autónomo. | Term structure común consumible por IFRS 9 y reporting dentro de PD temporal. | Golden hazard/survival y clean-room. |
| `F-PD-MARKOV · M` | `segment_col` mezcla segmentos; `period_matrices` se expone y se veta. | Matrices/curvas segmentadas; toda projection seleccionable es real. | Segmentos opuestos, permutación y negativo no-op. |
| `F-ROLL-VINTAGE · C(H7=A)` | Fuera del producto público actual; no es regresión. | Addendum de denominadores/cohortes/censura aprobado antes de código. | Diagnósticos dentro de PD temporal, no producto aislado. |
| `F-IFRS9 · M` | Staging, marginal, 12m/lifetime, PIT/TTC, escenarios, EIR y ECL existen. | Basis/procedencia; LGD resuelta; EAD(t) real. | Golden operación×escenario×período, stages 1/2/3. |
| `F-FORWARD-IFRS9 · M` | Steps aislados; pesos cero discrepan; no hay caso conjunto real. | ≥3 escenarios, inputs explícitos y sin inyección manual de term structure. | Reconciliación, fuentes/horizonte/unidad y no doble conteo. |
| `F-STRESS-ECON · M` | Shocks/sensibilidad/reverse existen; protocolo incompatible y tests con stubs. | Forward real→IFRS real→stress, misma reconciliación ECL. | Zero-shock=baseline; stub/incompatibilidad rechazados. |
| `F-PORTFOLIO-STRESS · X(H8=A)/C(H8=B-C)` | No existe; no modela saldos/runoff/recuperaciones/capital. | Sólo se vuelve `M` tras H8 B/C y SDD metodológico propio aprobado. | No se publicita ni cuenta hoy. |
| `F-REPORT · M` | Sin metadata semántica común; DOCX degrada layout. | Registro cerrado y paridad semántica/visual target-specific. | HTML/PDF/DOCX renderizados; overflow/cortes en rojo. |
| `G-PUBLIC-NAV · T` | Landing/README presentan módulos pares. | Seis familias de navegación mapean los diez trabajos D-JOB. | Censo landing↔README↔demo↔docs↔jobs. |
| `G-DIST-CANDIDATE · T` | CI parcial; smoke usa checkout; release reconstruye. | Clean-room enumerado y promoción exacta de wheel+sdist gateados. | Hashes, instalación externa, assets/red y artefactos finales. |
| `G-THIRD-PARTY-CANDIDATE · T` | No existe acta sin checkout sobre el candidato. | Tercero obtiene candidate-unit por SHA, sin repo, y repite los flujos `M`. | Acta independiente previa a cualquier OK PyPI. |
| `P-PYPI-VERIFY · P` | PyPI 1.11.0; no hay release autorizada. | Tras OK/publicación, descargar los mismos hashes y repetir smoke externo. | Acta post-publicación; no condiciona diseño ni autoriza release. |

La puerta global es computable: todos los `F-* · M` deben estar `gateado`, todos los `G-* · T`
deben pasar sobre ellos y ningún `X` puede presentarse como entregado. Un `C` activado se incorpora
al conjunto `M` sólo tras aprobar su contrato metodológico.

### 6.1 Anclas reproducibles del baseline

Estas rutas fijan la evidencia de “estado actual” sobre el commit citado; no sustituyen los gates
futuros de la cuarta columna:

| Frente | Evidencia medida |
|---|---|
| Scoring/apply | API pública sin `apply`: `src/nikodym/__init__.py:15-27`; piezas separadas en `src/nikodym/data/special.py:50-103`, `src/nikodym/binning/transformer.py:298-362`, `src/nikodym/model/estimator.py:269-305`, `src/nikodym/scorecard/scaler.py:204-252` y `src/nikodym/calibration/calibrator.py:331-365`. |
| Persistencia | `Study.save/load` usa artefactos joblib (`src/nikodym/core/study.py:765-859`); scorecard/calibration publican resultados, no los dos transformadores fiteados (`src/nikodym/scorecard/step.py:222-227`, `src/nikodym/calibration/step.py:264-277`). |
| Special inference | La máscara fiteada no cruza índices nuevos (`src/nikodym/binning/transformer.py:579-604`) y un special declarado pero no observado no entra al catálogo (`tests/unit/test_data_special.py:259-269`). |
| Opciones | Catálogo en `src/nikodym/ui/jobs.py`: 207 pares únicos, 197/5/2/3; gates vigentes en `tests/unit/test_jobs_abanico.py:300-405`. |
| Lineage/escala/UI | Helper lock en `src/nikodym/audit/environment.py:42-94`, pero `Study` fija `uv_lock_hash=None` en `src/nikodym/core/study.py:719-761`; UI síncrona/límite posterior al parse en `src/nikodym/ui/routes.py:867-898,1099-1171`; serializer completo en `src/nikodym/ui/serializers.py:248-339`. |
| LGD/EAD/IFRS | Fit/predict in-sample en `src/nikodym/provisioning/lgd.py:258-267,326-345`; EAD constante en `src/nikodym/provisioning/ifrs9/ead.py:122-193`; ECL y DF separados en `src/nikodym/provisioning/ifrs9/ecl.py:180-263`. |
| Forward/temporal/stress | LGD forward ignorada probada en `tests/unit/test_ifrs9_engine.py:1077-1092`; pooling Markov en `src/nikodym/markov/transition.py:330-390`; protocolos incompatibles en `src/nikodym/stress/engine.py:393-408` y `src/nikodym/provisioning/ifrs9/engine.py:208-216`. |
| Informe/producto | Proyección tabular sin metadata en `src/nikodym/report/renderer.py:732-761`; DOCX genérico en `src/nikodym/report/docx.py:308-316,392-407`; módulos pares en `web/src/components/landing-evidence.ts:229-329`. |
| Distribución | Candidato CI en `.github/workflows/ci.yml:259-377,439-467`; smoke dependiente del checkout en `scripts/smoke_instalacion_pip.py:1-186`; rebuild de release en `.github/workflows/release.yml:40-41`. |

## 7. Algoritmos y flujo

### 7.1 Entrenamiento y aplicación de scoring

1. Validar datos y crear particiones sin fuga.
2. Ajustar en Desarrollo tratamientos, binning, selección, logística, scorecard y calibración.
3. Transformar HO/OOT con objetos congelados y ejecutar validación.
4. Ensamblar el bundle seguro con schema, políticas, parámetros, lineage y hashes.
5. Persistir y recargar en un proceso limpio que no importe desde el checkout.
6. Aplicar a un frame targetless por chunks; validar fila/orden y emitir traza.
7. Reconciliar por fila:
   `raw → treatment_id → bin/category_id → WoE → eta → pd_raw → score → pd_calibrated`.
8. Probar que ningún objeto fiteado cambia y que no se llamó `fit`.

### 7.2 LGD, EAD e IFRS 9

1. Resolver fuente LGD: provided/recovery/workout o bundle modelado OOS.
2. Resolver perfil EAD según H4; validar movimientos y procedencia.
3. Resolver PD temporal y basis; aplicar forward una sola vez.
4. Resolver LGD forward conforme a H5; conflicto ambiguo falla.
5. Validar escenarios/pesos/fuentes y ausencia de doble conteo.
6. Ejecutar staging y ECL real por operación×escenario×período.
7. Aplicar corte 12m/lifetime según stage y descontar sólo con EIR.
8. Reconciliar detalle, escenario, stage, cartera y total sin volver a calcular en UI/report.

### 7.3 PD temporal y stress

1. Seleccionar survival o Markov como método de PD temporal.
2. En Markov, estimar por segmento sin pooling accidental; en survival, conservar el contrato
   común de term structure.
3. Ejecutar forward con macro/procedencia/basis explícitos.
4. Calcular el baseline mediante IFRS 9 real.
5. Aplicar shocks y recalcular con el mismo engine/adaptador.
6. Comparar baseline/stressed sobre detalle reconciliable. Un zero-shock debe ser identidad.
7. No mezclar aquí runoff, crecimiento, capital o recuperaciones de `PortfolioStress`.

### 7.4 Informes y arquitectura pública

Cada tabla tiene una clave estable y un registro cerrado de columnas. Además de `column_key`, cada
descriptor contiene exactamente los ocho atributos semánticos exigidos:

| Atributo | Contrato |
|---|---|
| `label` | Etiqueta pública, sin nombres internos ni códigos de deuda. |
| `type` | `text`, `integer`, `decimal`, `percentage`, `currency`, `date`, `duration`, `code`. |
| `unit` | Unidad física/financiera o `none`; nunca implícita por nombre. |
| `locale` | Locale de representación, separado del valor canónico. |
| `precision` | Decimales/cifras significativas y regla de rounding de presentación. |
| `alignment` | Alineación semántica; numéricos a la derecha salvo excepción declarada. |
| `width` | Mínimo, preferido y política de wrap/landscape por formato. |
| `visibility` | `all` o allowlist HTML/PDF/DOCX con motivo. |

Los tres formatos consumen el mismo valor canónico y descriptor. Pueden tener layout específico;
no se exige pixel-identidad. Sí se exige igualdad de etiquetas, unidades, precisión, orden y
visibilidad, más gates visuales de cortes, overflow, wrap numérico, páginas vacías y legibilidad.

La navegación pública se reorganiza en seis **familias de navegación**. No reemplazan ni enmiendan
el catálogo D-JOB de diez trabajos ejecutables; lo agrupan:

1. scoring y PD;
2. PD temporal;
3. LGD, EAD y pérdida esperada;
4. IFRS 9;
5. forward-looking y stress;
6. validación, gobierno y reporte.

| Trabajo D-JOB vigente | Familia primaria |
|---|---|
| Scorecard de comportamiento (PD) | scoring y PD |
| PD lifetime (curvas de supervivencia) | PD temporal |
| Provisiones CMF | LGD, EAD y pérdida esperada |
| Provisiones IFRS 9 / ECL | IFRS 9 |
| Provisión interna / LGD | LGD, EAD y pérdida esperada |
| PD + LGD en una corrida | LGD, EAD y pérdida esperada |
| Comparar provisiones (CMF vs interna) | LGD, EAD y pérdida esperada |
| Stress testing | forward-looking y stress |
| Validar un modelo existente | validación, gobierno y reporte |
| LGD modelada por regresión | LGD, EAD y pérdida esperada |

Survival y Markov son métodos dentro de PD temporal; satélites son métodos dentro de
forward/stress; CMF permanece visible como caso de referencia dentro de pérdida/provisiones, nunca
como titular ni sustituto de IFRS 9. Un gate exige mapping total y único de los diez trabajos y
permite cross-links secundarios sin duplicar su familia primaria.

### 7.5 Oleadas, orden y dependencias

| Oleada | Alcance | Depende de | Gate de salida |
|---|---|---|---|
| **W0 — contrato y baseline** | Aprobar SDD/H1–H11; medir con guardas sólo superficies/proxies actuales; marcar `no_medible` lo no alcanzable. | Este SDD aprobado y envelope H9 elegido. | Baseline disponible congelado y censo explícito de perfiles `no_medible`. |
| **W1 — fundamento productivo** | Bundle scoring/apply, tratamientos, `-99999`, D-ABA, `uv_lock_hash`, batch/UI básica. | W0. | Cartera nueva targetless, fila a fila, clean-room y cero opciones no-op seleccionables. |
| **W2 — LGD/EAD/pérdida** | LGD OOS persistible; provided/recovery/workout; EAD(t) según H4; reconciliación. | W1 para contratos de artefacto/lineage. | PD×LGD×EAD por operación/período y controles cruzados EIR/EAD. |
| **W3 — PD temporal** | Markov segmentado, projection real, survival común y H7. | W1. | Term structures intercambiables y ambos flujos PD temporal gateados. |
| **W4 — IFRS 9 + forward** | Basis, escenarios, macro, LGD forward, EAD(t), caso ≥3 escenarios. | W2 y W3. | Forward real→IFRS 9 real reconciliado. |
| **W5 — stress económico** | Adaptador/engine IFRS real, shocks, sensibilidad y reverse stress; H8 permanece separado. | W4. | Zero-shock identity y shock reconciliado sin stubs. |
| **W6 — informe y producto** | Metadata semántica, paridad renderizada y seis familias sobre diez trabajos D-JOB. | W1–W5. | HTML/PDF/DOCX renderizados y censo público bidireccional. |
| **W7 — distribución candidata** | Clean-room enumerado, paginación/lifecycle UI, bytes exactos y tercero sobre candidate-unit. | W1–W6. | Un wheel+sdist con hashes únicos; sin rebuild; acta sin checkout. |
| **W8 — release** | Sólo tras OK específico de Cami; promoción y verificación post-PyPI. | W7 verde + CI completo. | Publicar mismos bytes y verificar hashes desde PyPI. |

No se adelanta una oleada si su dependencia sigue sin contrato. W0 mide antes de optimizar; W8 no
queda autorizada por aprobar este SDD.

W1–W5 aplican el mismo ciclo dentro de cada flujo que hoy es `no_alcanzable` o `no_medible`:
**funcional mínimo → baseline sin optimizar → optimización → S1/S2 elegido → `S3-limite`**. Una
oleada no sale verde por haber creado la superficie; debe alcanzar el envelope H9 o dejar el flujo
rojo con evidencia. G-SCALE se evalúa de nuevo, acumulativamente, al cerrar W7.

## 8. Casos borde y manejo de errores

- ID ausente/duplicado, columnas requeridas ausentes, dtype incompatible o orden ambiguo: error
  antes de transformar, con rutas y conteos.
- Special declarado no observado en fit: se reconoce y conserva en la traza; sin soporte/mapping
  H2 falla antes de puntuar, no inventa WoE.
- Missing genuino y special: no se colapsan salvo `as_missing` explícito.
- Categoría nueva: nunca recibe silenciosamente el WoE de otra categoría; se aplica H2.
- Outlier fuera de soporte: se aplica política congelada; nunca recalcula umbral en apply.
- Bundle con hash, schema/version o dependencia incompatible: load/apply falla; no intenta “hacer lo
  mejor posible”.
- EAD negativa, movimientos que no reconcilian o períodos duplicados: error por operación/período.
- EIR ausente cuando se requiere descuento: `DATO-INSTITUCIONAL`/error conforme al contrato
  vigente; jamás se mezcla con un haircut de EAD.
- Peso faltante, no finito, negativo, suma distinta de uno o cero no permitido por H6: error antes
  de ECL.
- LGD forward y LGD del frame presentes sin resolución conforme a H5: error de precedencia.
- Curva sin basis/unidad/horizonte o con doble aplicación PIT: error, no warning cosmético.
- Segmento Markov vacío/desconocido: no se mezcla con otro segmento; política explícita de error o
  salida `not_evaluable`.
- Stress con stub o protocolo incompatible: error de integración temprano.
- Perfil que supera envelope: rechazo controlado que nombra dimensión y límite; nunca OOM/timeout
  opaco.
- Tabla sin descriptor o descriptor huérfano: build/report rojo.
- Render con encabezado o cifra cortada: gate visual rojo aunque el texto extraído coincida.
- Clean-room que resuelve imports desde checkout: fallo de prueba, no PASS.
- Candidato con artefacto adicional/faltante o hash distinto: promoción bloqueada.

## 9. Reproducibilidad y auditoría

### 9.1 Lineage completo

Toda corrida y todo apply registran:

- `git_sha`/estado sucio cuando existe checkout;
- versión Nikodym, schema del bundle y hashes wheel/sdist;
- `data_hash` de fit o apply, `config_hash` y hash del bundle;
- `uv_lock_hash` de la fuente de build embebido en el manifiesto del candidato;
- hash normalizado del entorno runtime instalado;
- root seed y seeds por componente;
- versiones, plataforma, arquitectura, hardware y caveats deterministas;
- políticas de tratamiento, features/orden, source/version de macro, escenarios/pesos, basis y
  overlays;
- cualquier ausencia que impida reproducibilidad como estado explícito, nunca `None` silencioso.

En checkout, `uv_lock_hash` coincide con el archivo canónico. En wheel instalado, el valor proviene
del manifiesto de build gateado; no se inventa un lock local. El entorno runtime se registra aparte
porque el lock de build no demuestra qué instaló el consumidor.

### 9.2 Determinismo

Mismos bytes de entrada, config, bundle, seed y entorno deben producir los mismos artefactos
canónicos. Si una dependencia sólo garantiza tolerancia numérica, esa tolerancia se declara por
campo y el hash se calcula sobre una representación canónica coherente; no se oculta detrás de un
hash binario inestable.

### 9.3 Escala y ejecución durable

Una ejecución larga registra estados `queued/running/succeeded/failed/cancelled`, heartbeat,
progreso, retry/idempotency key y cleanup. Esto se exige en UI sólo si H10 activa jobs; batch por
código puede seguir síncrono y chunked. Reanudar no puede duplicar filas ni mezclar candidatos.

## 10. Dependencias

**Internas.** Este contrato coordina los módulos existentes y no introduce una dependencia de
`core` hacia dominios. CT-1…CT-4, D-LGD, D-JOB, D-ART/D-PUE, D-PKG, D-HOR, D-CRP y la taxonomía de
marcas conservan autoridad salvo la enmienda explícita a D-ABA de §12.1.

**Externas.** No se aprueba una dependencia nueva aquí. El bundle seguro debe construirse con
formatos/librerías ya permisivos o, si necesita una dependencia, ésta requiere licencia, extra,
import perezoso y revisión supply-chain conforme a SDD-25. Pickle/joblib no es el formato público
recomendado para importar un artefacto no confiable.

**Fuentes metodológicas/normativas.** Este SDD no cambia fórmulas normativas. Los detalles de IFRS 9,
PD temporal, forward y stress conservan sus SDD aprobados y fuentes oficiales. Toda nueva elección
metodológica de H3–H8 exige doble verificación oficial antes de implementarse. La revisión histórica
interna sólo aportó canarios adversariales; no se cita como autoridad.

## 11. Estrategia de tests y controles negativos obligatorios

Cada gate nace con un control negativo temporal: inyectar el defecto, observar rojo, revertir
exactamente y observar verde. Los oráculos no pueden llamar a la misma función que se prueba.

| Área | Gate positivo | Control negativo obligatorio |
|---|---|---|
| Scoring persistible | Fit/save/load/apply idéntico en campos exactos y equivalente bajo tolerancia declarada en floats; golden fila manual. | Quitar binner, scaler o calibrador del bundle; cada ausencia pone rojo. |
| Anti-refit | Apply conserva hashes/estado y no llama `fit`. | Spy de `fit` que lanza; alterar target de apply no cambia salida. |
| Special | `-99999` sólo en apply conserva identidad; usa mapping explícito o falla si no tuvo soporte. | Cambiar orden special→missing o inyectar WoE neutral y observar rojo. |
| Categorías/outliers | Política declarada se aplica y se audita por fila. | Categoría nueva o outlier sin política debe fallar, no recibir WoE 0 silencioso. |
| D-ABA | Cada seleccionable tiene fixture discriminante y `effect_oracle`. | Hacer que dos opciones despachen a la misma rama; censo/gate pone rojo. |
| Catálogo bidireccional | Schema, catálogo, validator y dispatcher coinciden en ambos sentidos. | Añadir un literal (`period_matrices`) sin estado o retirar uno sin limpiar catálogo. |
| Lineage | `uv_lock_hash` y runtime hash presentes y correctos. | Alterar un byte del lock; `None`, lock falso o mismatch bloquean readiness. |
| Escala | S0–S2 registran tiempo/RSS; `S3-limite` prueba el envelope elegido. | Añadir copia full-frame o retardo; RAM/tiempo excedido pone rojo. |
| UI límite | N−1/N aceptados, N+1 rechazado antes de parse/spool. | Body chunked sin `Content-Length` supera N y debe cortarse temprano. |
| Paginación | Page size/cursor/orden estables. | Backend devuelve más de `page_size`, repite cursor o materializa score completo. |
| LGD OOS | Bundle modelado aplica sobre OOT/nuevo frame. | Reordenar/quitar covariable; alterar target OOS; intentar WoE de default. |
| EAD/EIR | Movimientos EAD y DF reconcilian por separado. | Cambiar EIR no cambia EAD; cambiar prepago no cambia DF; cruzarlos pone rojo. |
| ECL | Golden PD×LGD×EAD×DF por fila/escenario/período. | Inyectar ajuste EAD dentro del DF o doble ponderación de escenario. |
| Forward/IFRS | ≥3 escenarios reales terminan en IFRS 9. | Pesos inválidos, escenario `mean`, unidad/horizonte incoherente o doble PIT. |
| LGD forward | Fuente resuelta conforme a H5. | Presentar dos fuentes conflictivas y comprobar fail-loud. |
| Markov segmento | Segmentos opuestos producen matrices/curvas separadas. | Pooling accidental reproduce `P_A=[0.5,0.5]` y debe fallar. |
| Survival/Markov | Misma semántica mínima de term structure. | Cambiar unidad/basis o columnas requeridas en una sola ruta. |
| Stress | Zero-shock = IFRS baseline; shock recalcula ECL real. | Stub nominal, firma incompatible o shock macro duplicado deben fallar temprano. |
| Metadata tabla | Toda columna renderizada tiene descriptor y viceversa. | Añadir columna sin descriptor o descriptor huérfano. |
| Paridad | HTML/PDF/DOCX comparten label/unidad/precisión/orden/visibilidad. | Cambiar precision/locale en un renderer o estrechar hasta cortar cifras. |
| Arquitectura pública | Seis familias cubren y mapean los diez trabajos una vez. | Card de módulo sin mapping o ruta docs huérfana pone rojo. |
| Clean-room | Cada flujo corre desde wheel en tmp fuera del checkout. | Forzar `PYTHONPATH`/import desde checkout o quitar extra/asset. |
| Promoción | Release consume exactamente candidate-unit y verifica SHA. | Presencia de `build`, commit/tag distinto, byte corrupto o artefacto extra. |
| Tercero | Descarga, hashes y recorridos sin checkout. | Un archivo local necesario o conocimiento implícito bloquea el acta. |

### 11.1 Clean-room enumerado

Cada caso instala el mismo wheel candidato en un directorio temporal fuera del checkout, bloquea
imports desde la raíz y conserva el artefacto final:

| Caso | Flow IDs cubiertos | Fixture/resultado mínimo |
|---|---|---|
| `CR-01-score-train` | `F-SCORE-TRAIN` | CSV propio sintético → bundle, validación e informe. |
| `CR-02-score-apply` | `F-SCORE-APPLY`, `F-SCORE-BATCH` | Positivo: special con soporte/mapping → score/PD. Negativo: `-99999` sólo en apply bajo H2=A → misma fila `not_scorable`, motivo y outputs nulos. |
| `CR-03-ui` | `F-UI` | Console script loopback, upload, ejecución síncrona/job conforme a H10, paginación, assets 200 y cero red externa. |
| `CR-04-lgd` | `F-LGD-BASE`, `F-LGD-OOS` | Provided/recovery/workout + fit/load/apply beta/fractional en OOT. |
| `CR-05-ead` | `F-EAD-BASE`, `F-EAD-T` | Provided/CCF + perfil operación×período reconciliado. |
| `CR-06-cmf-reference` | `F-CMF-REFERENCE` | Caso de referencia congelado con golden regulatorio e informe. |
| `CR-07-survival` | `F-PD-SURVIVAL` | Ledger longitudinal → term structure con unidad/basis. |
| `CR-08-markov` | `F-PD-MARKOV` | Segmentos opuestos → matrices y curvas separadas. |
| `CR-09-forward-ifrs` | `F-IFRS9`, `F-FORWARD-IFRS9` | ≥3 escenarios → detalle/staging/ECL reconciliado. |
| `CR-10-stress` | `F-STRESS-ECON` | Zero-shock y shock real sobre el engine IFRS 9, sin stub. |
| `CR-11-report` | `F-REPORT` | HTML/PDF/DOCX renderizados desde el mismo registro semántico. |

`G-THIRD-PARTY-CANDIDATE` repite CR-01…CR-11 obteniendo candidate-unit por commit/SHA, sin clone ni
checkout. `P-PYPI-VERIFY` es otra evidencia posterior: sólo tras OK y publicación descarga desde
PyPI los mismos hashes. Ninguna de las dos recaptura la demo.

Además de las suites enfocadas se ejecutan gates proporcionales completos: ruff, format, mypy,
pytest con cobertura, regulatorios, núcleo liviano, frontend, build, MkDocs strict, contenido de
distribución, clean-room y artefactos renderizados. Los controles negativos no permanecen en el
árbol.

## 12. Decisiones abiertas, enmienda D-ABA y riesgos

### 12.1 Enmienda aprobada a D-ABA

Desde la aprobación expresa de Cami del 2026-08-09, **D-RDY-ABA-1…6 enmiendan D-ABA-4/5/6**:

1. **D-RDY-ABA-1 — `sin_efecto` deja de ser seleccionable.** El estado desaparece del contrato de
   opciones. Una opción se implementa, se deshabilita como `no_implementada` o sale del selector.
2. **D-RDY-ABA-2 — `disponible` exige rama y efecto.** Cada par `path/value` declara internamente un
   test de dispatcher y un `effect_oracle` con fixture discriminante. Metadata nominal no basta.
3. **D-RDY-ABA-3 — condicionada hereda el mismo gate sin cambiar D-ABA-8/D-PRE-5.**
   `exige_otro_campo` permanece seleccionable con aviso y preflight informativo/no bloqueante; el
   motor conserva la autoridad de rechazar el config incompleto. Cuando el requisito se satisface,
   la opción debe ejecutar una rama real y pasar su `effect_oracle`.
4. **D-RDY-ABA-4 — `no_implementada` sigue visible y deshabilitada.** La UI no la selecciona y el
   motor la rechaza con diagnóstico. No bloquea readiness porque no pertenece a la superficie
   soportada.
5. **D-RDY-ABA-5 — alias de compatibilidad no es opción.** Todo alias que pertenezca a F1 estable
   sigue aceptado por API/YAML durante SemVer 1.x, se normaliza a una rama explícita, emite
   `DeprecationWarning`, no aparece en el selector y sólo puede retirarse en 2.0.
6. **D-RDY-ABA-6 — censo bidireccional completo.** Todo literal alcanzable aparece en catálogo y
   dispatcher o se declara interno/no seleccionable; esto incluye `markov.period_matrices`.

Disposición contractual de los siete hallazgos medidos:

| Hallazgo | Disposición aprobada |
|---|---|
| `provisioning_ifrs9.ecl.rounding=currency_2dp` | Implementar efecto real según H3 y gate de reconciliación. |
| `provisioning_ifrs9.ecl.rounding=integer_currency` | Implementar efecto real según H3 y gate de reconciliación. |
| `report.formats=html` | HTML pasa a artefacto canónico base. En 1.x el literal sigue aceptado, normaliza a `html_always_on`, emite deprecación y sale del selector; se retira de `formats` en 2.0. |
| `selection.priority_order=gini` | En 1.x sigue aceptado, normaliza a `auc`, emite deprecación y sale del selector; se retira en 2.0 porque Gini es transformación monótona de AUC. |
| `model.engine=glm_binomial` | En 1.x sigue aceptado, normaliza a la rama logística actual y emite deprecación; sale del selector y se retira en 2.0. Un GLM ponderado futuro usa otro literal y otra enmienda. |
| `stability.csi_source=woe_bins` | Implementar como rama real en W1; no pasa a `disponible` hasta que el oracle discrimine ambas fuentes CSI. |
| `binning.solver=cp` | Mantener visible/deshabilitada y fuera de readiness; no se habilita sin término acotado y timeout probado. |

`markov.dynamics.projection_mode=period_matrices` se incorpora al mismo censo: sale de la superficie
seleccionable y conserva un error/deprecación explícitos hasta que una enmienda futura implemente su
rama. El estado actual “Literal aceptado y luego vetado” no es válido.

### 12.2 Decisiones humanas aprobadas

El acta de aprobación fija la alternativa elegida en cada decisión. Se conservan las alternativas
descartadas para trazabilidad del contrato.

#### H1 — Formato persistible de artefactos

- **A. Bundle abierto y seguro (recomendada):** manifiesto JSON, tablas columnares, hashes y schema;
  sin ejecutar pickle/joblib externo.
- B. Joblib como formato público: menor esfuerzo, pero acopla versiones y requiere confiar en el
  archivo.
- C. Ambos como contratos pares: más superficie y migraciones duplicadas.

**Recomendación: A.** Joblib puede seguir como persistencia interna de `Study`, no como intercambio
de un modelo recibido.

#### H2 — Tratamientos sin soporte en Desarrollo

- **A. Fail-closed (recomendada):** special, missing, categoría u outlier sin bin/mapping entrenado
  conserva su identidad y detiene esas filas antes de puntuar.
- B. Mapping provisto a un bin entrenado: la institución declara por variable el destino, fuente y
  justificación; la traza conserva el estado original.
- C. Método de prior/regularización: Nikodym estima un WoE para estados no observados mediante una
  metodología nueva que exigiría fuentes, SDD y aprobación aparte.

**Recomendación: A.** Los estados con soporte observado siguen su política entrenada; templates de
UI reducen fricción sin inventar un WoE neutral. Elegir A deja `provided_mapping` fuera del contrato
inicial; elegir B lo habilita de forma explícita.

#### H3 — Punto de rounding IFRS 9

- **A. ECL final por operación (recomendada):** sumar escenarios/períodos sin redondeo, redondear la
  ECL de cada operación y luego agregar; publicar diferencia de rounding.
- B. Cada operación×escenario×período: maximiza efecto acumulado y cambia reconciliación.
- C. Sólo presentación: no sería una opción del engine y `rounding` saldría del config de cálculo.

**Recomendación: A.** Mantiene detalle de cálculo y permite reconciliar total desde operaciones.

#### H4 — EAD(t), amortización y prepagos

- **A. Perfil provisto + identidad de movimientos (recomendada):** la institución entrega EAD(t) o
  componentes; Nikodym valida/reconcilia. CCF estático continúa disponible.
- B. Schedule contractual genérico: Nikodym genera amortización; prepayment sigue provisto.
- C. Modelo conductual completo: Nikodym estima drawdown/prepayment/runoff.

**Recomendación: A para readiness inicial.** B/C requieren convenciones y datos que no deben
inferirse; pueden añadirse después mediante SDD metodológico.

#### H5 — Precedencia de LGD forward

- **A. Fuentes mutuamente excluyentes (recomendada):** `provided/fitted` produce LGD base;
  `forward_adjusted` la transforma. Dos LGD finales fallan.
- B. Precedencia forward explícita: `lgd_precedence="forward"` es obligatoria cuando ambas fuentes
  llegan; audita la LGD desplazada y emite warning de conflicto resuelto.
- C. Precedencia frame explícita: `lgd_precedence="frame"` es obligatoria; audita el path forward
  descartado y emite el mismo tipo de warning.

**Recomendación: A.** Se conserva una base auditable y una sola transformación con provenance.

#### H6 — Pesos de escenario cero

- **A. Rechazar peso cero (recomendada):** sólo viajan escenarios activos y todos pesan `>0`.
- B. Permitirlos y filtrarlos en una frontera común antes de forward/IFRS 9; ambos engines consumen
  el mismo conjunto/pesos efectivos y lineage conserva los escenarios excluidos.

**Recomendación: A.** Simplifica el contrato y evita que forward e IFRS 9 discrepen.

#### H7 — Roll-rate y vintage

- **A. Incluirlos como diagnósticos de PD temporal (recomendada):** no son estimadores ni productos;
  requieren antes un addendum de denominador, cohortes y censura.
- B. Excluirlos de readiness inicial y mantener el copy actual.
- C. Presentarlos como módulos independientes.

**Recomendación: A**, sin programar hasta aprobar el addendum metodológico. Markov/survival siguen
siendo los métodos de PD temporal.

#### H8 — Alcance de `PortfolioStress`

- **A. Excluirlo de readiness inicial (recomendada):** cerrar primero stress económico sobre IFRS
  real; `PortfolioStress` obtiene SDD propio.
- B. Incluir saldos/runoff/recuperaciones sin capital.
- C. Incluir también capital, garantías, crecimiento y originación.

**Recomendación: A.** B/C requieren elecciones de metodología y datos institucionales todavía no
aprobadas.

#### H9 — Compromiso de escala

- A. **`S1-local`:** 8 vCPU/16 GiB, 100.000×50, cardinalidad 10.000, 60 períodos/3 escenarios,
  UI 50 MiB; peak ≤12 GiB y tiempos de §5.5.
- **B. `S2-equipo` (recomendada):** 16 vCPU/32 GiB; train 1 M, batch 5 M, 100 variables,
  cardinalidad 100.000, 100.000 operaciones×120 períodos×5 escenarios, UI 100 MiB; peak ≤24 GiB y
  tiempos de §5.5.
- C. **Sólo corrección `S0`:** sin compromiso público de escala; cualquier volumen mayor queda
  best-effort y no permite declarar readiness integral.

**Recomendación: B.** W0 mide el baseline del target antes de cualquier optimización; un rojo no
rebaja el target en silencio, sino que cuantifica la brecha. `S3-limite` prueba después N−1/N/N+1.

#### H10 — Ejecución larga en UI

- **A. Engine/batch síncronos; UI usa job al cruzar umbral (recomendada):** paginación siempre;
  lifecycle durable sólo donde el baseline lo exige.
- B. Todo síncrono: menor complejidad, peor control de timeout/cancelación.
- C. Todo asíncrono: más infraestructura incluso para flujos cortos.

**Recomendación: A**, con umbral fijado después de W0.

#### H11 — Paridad Word/PDF

- **A. Paridad semántica + constraints visuales por formato (recomendada).**
- B. Pixel-identidad: frágil y poco realista entre HTML/PDF y OOXML.
- C. Sólo igualdad de texto: no detecta cortes, wrapping ni tablas ilegibles.

**Recomendación: A.** El artefacto renderizado, no el XML o el texto extraído, decide el gate.

### 12.3 Riesgos y mitigaciones

- **SDD demasiado transversal.** Mitigación: cada oleada conserva owner y SDD de dominio; SDD-30
  sólo fija fronteras/evidencias y exige addendum cuando hay metodología nueva.
- **Convertir readiness en marketing.** Mitigación: estados derivados de evidencia y clean-room.
- **Romper F1 estable al retirar aliases.** Mitigación: alias de compatibilidad deprecado fuera del
  selector durante SemVer 1.x; ninguna ruptura silenciosa.
- **Artefactos enormes por traza fila×variable.** Mitigación: salida columnar particionada/streaming,
  hashes y paginación; no se sacrifica verificabilidad.
- **Prometer escala antes de medir.** Mitigación: W0 y H9 son gates previos a optimización/copy.
- **Doble conteo macro o financiero.** Mitigación: basis/provenance/overlay order obligatorios y
  controles negativos de EAD/EIR y PIT/forward.
- **Confundir stress económico con PortfolioStress.** Mitigación: owners, inputs y estados separados;
  copy público no los fusiona.
- **Rebuild de release.** Mitigación: promoción de candidate-unit por hashes y veto estático de
  cualquier paso `build` en release.

### 12.4 Acta de revisión adversarial independiente

Revisión read-only del 2026-08-09 contra AGENTS, HANDOFF, decisiones vigentes y SDD de dominio.
Veredicto de primera ronda: **NO APROBABLE** hasta resolver los hallazgos. Disposición integrada:

| Hallazgo independiente | Disposición en esta revisión |
|---|---|
| W3/W4 tenían dependencia circular | W3 ahora entrega PD temporal; W4 integra IFRS/forward; W5 stress. |
| D-RDY-ABA-3 contradecía D-ABA-8/D-PRE-5 | Mantiene selección+aviso y preflight no bloqueante; el motor conserva autoridad. |
| Special/unseen sin soporte prometía WoE imposible | H2 obliga fail-closed, mapping provisto o futuro método aprobado; no hay WoE neutral. |
| Puerta global no computable | IDs estables y estados `M/T/C/X/P`; clean-room CR-01…CR-11. |
| Tercero y PyPI conflados | Acta candidate pre-release y evidencia PyPI post-release separadas. |
| CT-3 sin input longitudinal | §5.4 define datasets, keys, as-of, hashes, joins y granularidad. |
| Forward/stress conservaban defaults ambiguos | Productivo fail-closed; mappings de frecuencia/granularidad cerrados; `FALTA-DATO` bloquea. |
| H9 no ofrecía envelope elegible | S1 y S2 tienen filas, cardinalidad, horizonte, escenarios, hardware, RAM y tiempo; se recomienda S2. |
| EAD hacía floor y también prometía error | Se elimina floor: EAD negativa falla. |
| Bit-equivalencia contradecía tolerancias | Igualdad exacta sólo en campos canónicos; floats usan tolerancia declarada. |
| Seis trabajos podían reemplazar D-JOB | Son familias de navegación con mapping de los diez trabajos vigentes. |
| S3 usaba N antes de elegir envelope | S3 nace después de H9 y prueba N−1/N/N+1 con límites de proceso. |

La segunda ronda mantuvo **NO APROBABLE** por cuatro contradicciones residuales, también resueltas:
filas no puntuables conservan una salida estructurada; W0 marca `no_medible` y cada oleada mide antes
de optimizar; todas las alternativas H5/H6 son coherentes; y los aliases F1 tienen migración 1.x/2.0
exacta. Los nitpicks de familias, README, CR-03 y doble verificación H3 se integraron.

**Veredicto final de tercera ronda: APROBABLE, sin hallazgos materiales ni contradicciones nuevas.**
La revisión fue independiente y no editó el checkout.

### 12.5 Acta de aprobación

Cami comunicó expresamente el 2026-08-09:

> Apruebo SDD-30, D-RDY-ABA-1…6 y las decisiones H1=A, H2=A, H3=A, H4=A, H5=A, H6=A, H7=A,
> H8=A, H9=B, H10=A y H11=A.

La aprobación habilita **W0** y, sólo después de cerrar sus gates y dependencias, las oleadas
siguientes. No autoriza saltar una dependencia, publicar PyPI ni recapturar la demo.
