# Enmienda SDD — el censo del contrato, re-medido: qué cae, qué crece y por dónde se adopta

| Campo | Valor |
|---|---|
| **Documento** | Enmienda al contrato transversal de resolución de parámetros: corrección de su §2 y plan de adopción en IFRS 9 |
| **Tipo** | Enmienda a decisiones troncales |
| **Versión** | 2.0 — reescrita tras revisión adversarial (§7) |
| **Fecha** | 2026-07-25 |
| **Autor** | DanIA |
| **Base** | Re-censo sobre `main` = `f4fa383` con cinco lectores frescos independientes y sondas en runtime; auditoría de citas y revisión adversarial por dos lectores más. El censo original del contrato es de `c02a4f7` y lo escribió el mismo autor del contrato |
| **Enmienda a** | [`_CONTRATO-RESOLUCION-PARAMETROS.md`](_CONTRATO-RESOLUCION-PARAMETROS.md) §2 (P2 y P3), CRP-1, CRP-3, CRP-6 y §7 (estrategia de adopción) |
| **No toca** | CRP-2 y CRP-7, que el re-censo confirmó sin correcciones. Tampoco reabre B3.a-2 ni la lectura del panorama LATAM (§5 del contrato), que sigue sin verificar |
| **Estado** | **APROBADO (Cami, 2026-07-25)**, incluidas las dos decisiones que eran suyas: el orden de adopción arranca en CRP-5 (§3.7) y el preset F4 **se cambia**, no se declara (§3.8) |
| **Release** | `1.6.0`, junto con el resto del contrato |

---

## 1. Por qué existe esta enmienda

El contrato §2 dice «el problema, medido». Se midió, pero **una de sus afirmaciones se escribió leyendo un
archivo en vez de barrer el repo**, y es precisamente la que sostiene la decisión más cara del contrato
(CRP-3). Re-medido contra `f4fa383`: de las siete afirmaciones estructurales del §2, **cuatro se
confirman, una se amplía, una queda parcial y una es falsa** — y era falsa ya en `c02a4f7`, así que no
la invalidó la enmienda de segmentación: nació mal.

Es la tercera vez que este proyecto paga el mismo error de método: B3.a-1 (premisa falsa), el catálogo
de datasets (once justificaciones sin motor detrás) y ahora el §2 del propio contrato.

**Y la cuarta fue esta enmienda.** Su versión 1.0 propuso eliminar `fail_on_falta_dato` de `survival`
argumentando que la capa «no tiene ninguna carencia declarada que gobernar». La capa emite tres
(`survival/kaplan_meier.py:55-57`). La revisión adversarial lo cazó antes de que llegara a código. El
§7 lista los seis puntos que cambiaron; se deja escrito porque el patrón —afirmar un negativo sin
buscarlo— es el mismo que esta enmienda denuncia, y ocultarlo haría del documento un mal ejemplo de sí
mismo.

**Corrección al primer barrido: B3.a-1 sí movió números de línea.** `ifrs9/config.py` ganó 10 líneas
(el `portfolio_scheme` de la línea 601) y `ui/presets.py` cuatro. Dos citas del contrato quedaron
corridas: `fail_on_falta_dato` pasó de `config.py:637` a **`:647`**, y el bloque del preset de
`presets.py:751` a **`:754`**. Las citas de esta enmienda usan los números de hoy.

## 2. El re-censo, afirmación por afirmación

| # | Afirmación del contrato §2 | Veredicto |
|---|---|---|
| P1 | La misma carencia falla de formas opuestas (6 casos) | **CONFIRMADA** 6/6; dos medidas en runtime |
| P2.a | `rho` no tiene default y detiene la corrida | **PARCIAL** — es condicional, no exigido |
| P2.b | Los umbrales SICR y los backstops son constantes cableadas | **REFUTADA** — son campos con validación, UI y preset |
| P2.c | El gatillo SICR cuantitativo viene apagado y no se declara | **CONFIRMADA**; el negativo se buscó en seis superficies |
| P3 | Un solo lugar del repo registra procedencia | **REFUTADA** — pero el conteo correcto está abierto (§2.1) |
| P4 | Tres momentos de validación para el mismo parámetro | **CONFIRMADA**, y peor de lo descrito |
| P5 | `fail_on_falta_dato` es tres cosas | **CONFIRMADA y ampliada** — siete definiciones, cinco semánticas |

### 2.1 P3 es falsa, y su reemplazo todavía no es un número cerrado

El contrato afirma que `source="default_a_confirmar"` (`forward/scenarios.py:91-106`) es **el único**
lugar del repo que marca procedencia, y de ahí concluye que CRP-3 introduce una capacidad inexistente.
El barrido la refuta, pero **dos barridos independientes dieron dos inventarios distintos**, así que lo
honesto es publicar la estructura, no un total:

**(a) Registran procedencia de un valor** — el objeto directo de CRP-3:

| Mecanismo | Ubicación | ¿Anterior al censo? |
|---|---|---|
| `source` de los pesos de escenario | `forward/scenarios.py:102` | sí |
| `shock.source` en frame y auditoría | `stress/engine.py:1795`, `3597`, `3640` | sí |
| `source` de los puntos de la scorecard | `scorecard/scaler.py:492`, `497`, `521` | **sí** |
| `source` del generador Markov | `markov/transition.py:695`; `markov/step.py:438` | **sí** |
| `MLComparisonRecord.source`, validado contra la métrica | `ml/results.py:81`, `92`, `112-116` | **sí** |
| `source` de estabilidad | `validation/stability.py:100`, `148`, `225` | **sí** |
| `source` de discriminación | `validation/discrimination.py:120`, `223` | **sí** |
| `AnchorSource` de la tasa central de calibración | `calibration/config.py:26-32`, `124`, `370-387` | **sí** |
| `EvaluationSource` de performance | `performance/config.py:26`; `performance/results.py:142-143` | **sí** |
| Procedencia normativa de las matrices CMF | `cmf/matrices.py:34-36`, `71-102` | **sí** |
| `IfrsScenarioConfig.source` | `ifrs9/config.py:458`, cruzado en `484-516` | **sí** |
| `ProvisioningSource` | `provisioning/config.py:60` | **sí** |

**(b) Registran procedencia de un *esquema*, no de un valor** — eje distinto, ver §3.1.4:
`provisioning/segmentation.py:40-108` (`SchemeOwner`) y su viaje a las tres cards
(`ifrs9/engine.py:534`, `internal/engine.py:781`, `cmf/engine.py:2016`). Introducidos por B3.a-1.

**(c) Letra muerta o duplicación, que no migran nada:** `ScorecardBinPoint` (`scorecard/results.py:35`)
**nunca se instancia**; `stress/results.py:865-867` es copia manual a mano del dominio de
`stress/config.py:168`; `validation/results.py:73` y `:100` son declaraciones de nombre de columna del
mismo artefacto ya contado.

**Lo que sobrevive y lo que no.** Sobrevive el veredicto: **P3 es falsa**, no hay «un solo lugar», y
varios de estos mecanismos ya **cross-validan** procedencia contra otra cosa (`calibration:370-387`,
`performance/results.py:142-143`, `ml/results.py:112-116`, `ifrs9/config.py:484-516`, y las matrices CMF
vía `fail_on_source_mismatch`). No sobrevive ningún total: la v1.0 dijo «trece» y no es defendible.
**Cerrar el inventario es la primera tarea de CRP-3, no un dato que ya tengamos** — y esa es
precisamente la lección que esta enmienda existe para aplicar.

### 2.2 P2 estaba mal en sus dos polos, y la conclusión se sostiene igual

**El polo «exige decisión» no existe.** `rho` no detiene la corrida: la guarda
(`ifrs9/config.py:666-671`) exige **dos** condiciones simultáneas — `pit_mode="apply_vasicek"` **y**
`fail_on_falta_dato=True` —, y el default de `pit_mode` es `"consume_pit"`. Medido en runtime:
`IfrsProvisioningConfig()` construye con `rho=None`, sin emitir nada.

Verificado sobre los **55 campos de los siete modelos** de `ifrs9/config.py` (`is_required()` es `False`
en los 55; los siete construyen vacíos): **no hay un solo parámetro exigido de forma incondicional**. Los
que parecen exigidos son condicionales, activados por otra elección del usuario. La dicotomía real no es
«a veces exige, a veces inventa» sino **«siempre inventa, salvo cuando el usuario ya activó una vía que
obliga a completarla»**.

**El polo «constantes cableadas» es falso.** Los umbrales SICR (2.0, 3.0), los backstops (30, 90) y el
horizonte (12) son campos Pydantic con validación de rango, `json_schema_extra` de UI y presencia en el
preset F4 (`ifrs9/config.py:329-365`, `125-133`; `ui/presets.py:790-793`). Son configurables. Lo que
falta no es configurabilidad: **es el aviso**.

Con una excepción que el censo original no vio: los backstops 30/90 **sí se publican** en la prosa del
informe vía la ficha metodológica (`methodology.py:184-193`), y `sicr_pd_ratio_threshold` en el decision
log (`ifrs9/step.py:186`). Los que no constan en **ninguna** superficie son cuatro:
`sicr_pd_pit_backstop_multiple` (3.0), `ecl.rounding`, `lgd.workout_discount` y
`staging.low_credit_risk_exemption`.

### 2.3 El problema es mayor de lo medido, en tres ejes

**Seis gatillos apagados por defecto, no uno.** El contrato cita `origination_pd_life_col`. Son seis, y
ninguno lo declara:

| Gatillo | Ubicación | Default | Efecto al quedar inerte |
|---|---|---|---|
| SICR cuantitativo (PD lifetime en origen) | `config.py:378` | `None` | vector de `False` |
| Downgrade por notches | `config.py:396` | `None` | vector de `False` |
| Override cualitativo de stage | `config.py:403` | `None` | `numpy.ones` — vector de stages, no booleano (`staging.py:193-198`) |
| Exención de bajo riesgo (5.5.10) | `config.py:411` | `False` | opt-in puro (`staging.py:207-210`); publica columna todo-`False` en `staging.py:257` |
| Stage 3 por `is_default` | `config.py:372` (`"is_default"`) | columna ausente | `staging.py:200-205` colapsa opt-out y carencia en la misma condición |
| **Backstop PIT** | `staging.py:170-181` | columna `pd_pit_origination` **cableada** (`staging.py:75`) | `numpy.zeros`; ni siquiera es parámetro de config |

**Nueve warnings de carencia sin marca, no cuatro.** Los nueve verificados: existen con el literal exacto
y `is_declared_warning()` los rechaza (ejecutado).

| Código | Ubicación | Gravedad |
|---|---|---|
| `hazard_derivado_desde_pd_marginal` | `forward/satellite.py:62` | ya listado |
| `lgd_base_ausente` | `forward/satellite.py:63` | ya listado |
| `pd_basis_asumida_desde_config` | `forward/satellite.py:64` + literal duplicado en `forward/step.py:834` | ya listado |
| `pd_basis_no_resuelta` | `forward/satellite.py:65` + literal duplicado en `forward/step.py:836` | ya listado |
| `D-SUR-7` | `survival/cox_aft.py:61` | **nuevo.** Su vecino de la línea 60 sí está marcado; viaja como código SDD crudo a la term-structure (`cox_aft.py:412`→`:673`) |
| `hazard_undefined_zero_survival` | `markov/term_structure.py:71` | **nuevo, el peor**: no llega al filtro (cae en la columna `warning_codes` del frame, `term_structure.py:509`, y `markov/step.py:542` filtra `diagnostics.warnings`) |
| `normalized_stochastic_row:{state}` | `markov/transition.py:590` | **nuevo.** Declara que el motor **alteró el dato** |
| `unknown_states_dropped:{...}` | `markov/transition.py:760` | **nuevo.** Declara que el motor **eliminó filas** |
| `ead_floored_limit_below_drawn` | `ifrs9/ead.py:71` | **nuevo** |

La evidencia más dura de que es descuido y no criterio: `forward/step.py:831-839` tiene **tres `append`
consecutivos en la misma función**, uno marcado (`:838`) y dos no.

**Siete definiciones de `fail_on_falta_dato` y cinco semánticas, no tres.** Y una capa **ya fue
corregida** por D-SEG-7 (`provisioning/orchestrator.py:259-266`), lo que la convierte en el patrón a
replicar, no en un pendiente:

| Capa | Lector | Semántica real |
|---|---|---|
| `provisioning/ifrs9/config.py:647` | sólo `config.py:666` | gate de config del chequeo PIT; con `False` el fallo reaparece en `engine.py:760-770` |
| `survival/config.py:301` | **nadie** | no-op puro; sólo se escribe en tres constructores |
| `forward/config.py:578` | `config.py:650` | gate de config compuesto por AND con un segundo flag; alcance: un aviso |
| `stress/config.py:656` (bajo `validation`) | `config.py:940` + `engine.py:1835`, `2003`, `2483` | mixto config+runtime |
| `provisioning/internal/config.py:209` | `engine.py:389` | gate de runtime con imputación a cero + marca |
| `provisioning/config.py:298` | `config.py:397` + `orchestrator.py:262` | **ya corregida (D-SEG-7)** |
| `validation/config.py:399` | `config.py:415` + `evaluator.py:422` | mixto config+runtime |

Ni `ifrs9` ni `survival` lo llevan a su audit trail; las otras cinco sí. `provisioning/cmf` **no tiene el
flag** y su gate de dominio de cartera es incondicional en la entrada del motor (`cmf/engine.py:443`,
`446-462`): es la capa más alineada con CRP-5 y sirve de referencia.

### 2.4 Lo que ya se cobra una corrida: cinco defectos vivos, tres medidos en runtime

1. **LGD subestimada 20 pp, en silencio.** Con enfoque `workout`, si falta `recovery_cost` el motor asume
   cero (`ifrs9/lgd.py:142-145`). Medido: EAD 100, recovery 50 → `lgd=0.5`; con `recovery_cost=20` →
   `lgd=0.7`. `warnings: []`. Su insumo hermano, `recovery_time_years`, sí levanta `IfrsLgdError`.
2. **Un default genuino sale Stage 1.** Sin la columna `is_default` en el frame, `staging.py:200-205`
   devuelve `False` para toda la cartera. Medido: `stages: [1, 1]`, `warnings: []`; con la columna,
   `stages: [3, 1]`.
3. **El preset F4 que se entrega al usuario corre en modo diagnóstico sin decirlo.**
   `ui/presets.py:764` fija `pit_mode: "ttc_only"`, modo que el propio config describe como «solo
   diagnóstico» (`ifrs9/config.py:92`). `report/prose.py:1625` lo traduce a «through-the-cycle (TTC)» sin
   señalarlo, y los fixtures de la demo pública lo llevan (`preset-ifrs9.json:220`,
   `results-ifrs9.json:115`, `report-ifrs9.html:1923`).
4. **Los pesos inválidos ya ponderaron la PD antes de fallar.** `_forward_weights`
   (`ifrs9/engine.py:775-790`) no valida suma, positividad ni cobertura; los chequeos llegan en
   `ecl.py:360-379`, después de que `engine.py:240` ponderara la PD 12m/lifetime. P4 subestimaba: no es
   «después de staging», es después de haber calculado con el número malo.
5. **`FALTA-DATO-IFRS-4` se emite en todas las filas** incluso con EAD provista por la institución
   (`ifrs9/ead.py:137-142`, incondicional). Confirmado en corrida completa de
   `IfrsProvisioningEngine.calculate`: `ead=[1000.0]` desde la columna y `card.falta_dato =
   ('FALTA-DATO-IFRS-4',)`.

### 2.5 Correcciones de nomenclatura del contrato

- La clase es **`IfrsProvisioningConfig`** (`ifrs9/config.py:565`), no `IfrsConfig`.
- El punto de entrada del motor es **`calculate`**, no `compute`.
- El tercer default en conflicto de §2 no es `term_structure_source` sino **`pd.pit_mode`**:
  `term_structure_source="survival"` es la contraparte que hace imposibles a los otros dos (survival no
  publica `pd_basis` ni `scenario_weight`; sólo `forward` las emite). Son **cuatro** campos en conflicto
  —`ead.method="ccf"` llega con `ccf_col=None` **y** `ccf_value=None`—, y el default puro falla en cadena
  en tres puntos: `engine.py:777-780` → `engine.py:725-729` → `ead.py:162-164`.
- El preset está en `ui/presets.py:754-812` y sobrescribe **cuatro** campos, no tres (añade
  `pd.horizon_12m_periods: 1`).
- La clase de comparación de ml es **`MLComparisonRecord`** (`ml/results.py:81`).
- La ficha metodológica vive en `src/nikodym/methodology.py`, no bajo `report/`.

## 3. Las decisiones

### 3.1 · E-CRP-1 — CRP-3 se redefine: `Resolved[T]` unifica, no crea

El objetivo de CRP-3 no cambia; cambian su naturaleza y su plan.

1. **La adopción es por extensión aditiva.** Los mecanismos existentes siguen funcionando mientras
   migran; no hay corte. Es la regla de CT-2 para contratos de lectura.
2. **Cerrar el inventario de §2.1 es la primera tarea de CRP-3**, con el criterio explícito de qué
   cuenta: registra procedencia **de un valor de riesgo**, está **instanciado** (no letra muerta) y no es
   copia de otro. El inventario entra al SDD antes de migrar la primera capa.
3. **Se fija un vocabulario único antes de migrar nada, y el mapeo es una descomposición, no una
   traducción.** Los vocabularios actuales mezclan tres ejes: la **vía** (`ParameterSource`), el bit
   `is_default` (`default_a_confirmar` en `forward` y `stress` es esto, no una vía) y el **reuso de
   artefacto** (`stability_artifact` vs `recomputed` en `validation`; `binning_table` vs `override` en
   `scorecard`). Cada valor existente se descompone en esos tres ejes, con test de cobertura.
4. **`SchemeOwner` no se absorbe**, y la relación entre ejes se declara con sus dos huecos resueltos:
   `scheme_by_id` (`segmentation.py:197-221`) hoy **fabrica en silencio** un esquema `INSTITUTION` cuando
   el id es desconocido —procedencia inventada por el motor, justo lo que CRP-4 prohíbe— y
   `_coherencia_por_dueno` (`segmentation.py:76-108`) no impone ninguna regla a `INSTITUTION`. Ambos
   entran al alcance de CRP-3.
5. **La firma usa `Generic[T]`, no PEP 695.** `class Resolved[T]` exige Python ≥3.12 y el proyecto
   declara `requires-python = ">=3.11"` con CI en 3.11 (`pyproject.toml:12`, `ci.yml:54`). El bloque de
   código del contrato se corrige.
6. **`is_default` exige decidir el canal de carga antes de existir** — ver §3.3.

### 3.2 · E-CRP-2 — CRP-1 fija además *qué se exige*, con un test decidible

El re-censo mostró que ninguna política exige nada de forma incondicional. Declarar las vías no arregla
eso. Se añade a CRP-1 la regla de exigibilidad, y se opera con un test que no dependa del criterio del
implementador:

> **Exigible** un parámetro institucional para el que **no existe cita normativa o de estándar que fije
> el valor**. **Con default y aviso** cuando sí existe esa cita (el motor puede defender el número ante
> un supervisor sin conocer a la institución). La exigencia es **condicional a que la vía que consume el
> parámetro esté activa**: se valida cuando el config la activó, no en toda corrida.

Aplicada, da resultado determinista y **corrige dos clasificaciones de la v1.0**: `dpd_default_backstop`
(90) y `dpd_sicr_backstop` (30) tienen cita —presunciones de IFRS 9 B5.5.37 y 5.5.11— → default + aviso;
`low_credit_risk_exemption=False` es **opt-in puro** (`staging.py:207-210`), su `False` significa «no
apliqué un alivio opcional» y eso sí es defendible → default + aviso, no exigible; `sicr_pd_ratio_threshold`
(2.0) y `sicr_pd_pit_backstop_multiple` (3.0) **no tienen valor normado** → exigibles cuando el gatillo
está activo; `ecl.rounding` es política contable sin cita → exigible.

**Los nombres de columna quedan fuera de esta regla.** Cuatro de los seis gatillos de §2.3 son
`*_col`, no parámetros: no se «exigen», se resuelven por la vía `PROVIDED` y su ausencia es materia de
CRP-4 y CRP-5.

### 3.3 · E-CRP-3 — `is_default` no es computable hoy; se decide aquí o CRP-3 no es implementable

CRP-3 define `is_default: bool  # ¿lo eligió el motor porque el usuario no dijo nada?`, y E-CRP-2 ancla
su regla en él. **Ese bit no existe y no puede derivarse del canal actual:**

- `model_fields_set` / `__pydantic_fields_set__` no se usan en ninguna parte de `src/`.
- El preset escribe **todas** las claves explícitas, incluidos los apagados (`ui/presets.py:789-803`) y
  se genera así por diseño (`scripts/derive_ifrs9_preset.py:100`, `125`, sin `exclude_unset`).
- El volcado de config tiene **dos semánticas**: `dump_config` usa `exclude_unset=False` por defecto para
  conservar lineage auditable (`core/config/loader.py:83`, `103`), y el round-trip del UI usa
  `exclude_unset=True` (`ui/routes.py:132`).

Consecuencia: la misma config efectiva daría `is_default` distinto según el canal. **Un audit-trail que
miente es peor que uno ausente** — el mismo argumento con que esta enmienda juzga el resto del censo.

**Decisión: `is_default` se deriva de un centinela propio en los campos resolubles**, no de
`model_fields_set` ni de `exclude_unset`. Razón: es el único mecanismo indiferente al canal, y no obliga
a tocar `dump_config` (cuyo volcado completo es deliberado y sostiene el lineage). El diseño del
centinela entra al SDD de CRP-3 antes de escribir la primera emisión.

### 3.4 · E-CRP-4 — Los umbrales configurables salen de CRP-1 y entran a CRP-4

Reducción de alcance con evidencia: ya son campos con UI y preset. El trabajo es declarar su procedencia
y avisar cuando el valor es default, no volverlos configurables. Sin choque con §3.2: aquí se decide
*dónde* se declaran, allá *si se exigen*.

### 3.5 · E-CRP-5 — CRP-4 se dimensiona con el inventario real, y la taxonomía de los nueve se decide antes de programar

Los criterios del contrato §6.2 se miden contra **nueve** warnings y **seis** gatillos. Cuatro
precisiones de método, todas de diseño y no de implementación:

1. **`markov/term_structure.py:71` no se arregla poniéndole prefijo**: su colección no llega al filtro.
   Un prefijo ahí daría un falso verde. Hay que replicar el `_warning_codes_from_frame` de
   `forward/step.py:665`, que `markov/step.py` no tiene.
2. **Los dos literales duplicados de `pd_basis_*`** (`forward/satellite.py:64-65` y
   `forward/step.py:834-836`) se unifican **antes** de marcarlos, o el arreglo deja uno vivo.
3. **Dos de los nueve no caben en la taxonomía de dos marcas.** `normalized_stochastic_row` y
   `unknown_states_dropped` declaran que el motor **alteró o eliminó el dato del usuario**: no es una
   carencia que deba Nikodym ni la institución. `ead_floored_limit_below_drawn` es del mismo género.
   **Decisión: son `FALTA-DATO`** —el motor tomó una decisión sobre el dato que el usuario no autorizó, y
   la deuda es del motor: debería haberlo consultado o rechazado— y **no se crea una tercera marca**,
   porque una taxonomía de tres exige revisar los 45 códigos vivos y eso es un trabajo aparte.
4. **Cada uno de los nueve recibe familia y número en el SDD, no al programar.** El gate real es el
   regex `MARCA-[A-Z]+-\d+` de `tests/unit/test_public_copy.py:93-95`; hoy no existe familia para
   `markov` y el espacio de numeración es compartido entre las dos marcas dentro de una familia (conviven
   `DATO-INSTITUCIONAL-FWD-1,4,5` con `FALTA-DATO-FWD-6,8`), regla que no está escrita en ninguna parte y
   que esta enmienda deja escrita. **Los dos códigos con sufijo dinámico** (`:{state}`, `:{...}`) se
   emiten con el código estable y el detalle fuera del código, o el test que barre el fuente
   (`test_public_copy.py:116`) quedaría verde mientras el usuario ve un código que la página no documenta.

### 3.6 · E-CRP-6 — CRP-6: `survival` **implementa** el flag; no se elimina

**Corrige a la v1.0, cuya premisa era falsa.** `survival` emite tres marcas declaradas
(`kaplan_meier.py:55-57`: `DATO-INSTITUCIONAL-SUR-1/2/3`, documentadas en
`docs_site/avisos-declarados.md:82-84`), que es exactamente el objeto que CRP-6 gobierna. Es además el
caso más simple de las siete capas: no hay semántica heredada que desandar.

Eliminarlo, además, habría sido ruptura pública sin ruta de migración: el campo viaja al `schema.json`
del UI instalable (`core/study.py:96` lo incluye en `_DOMAIN_CONFIG_CLASSES`), está en el preset y en el
fixture publicado, `NikodymBaseConfig` es `extra="forbid"` (`core/config/schema.py:114`) —así que todo
YAML `1.5.x` con ese campo pasaría a levantar `ConfigError`— y `_MIGRATORS` está **vacío**
(`core/config/migration.py:30`): sería el primer migrador del proyecto. El precedente propio es retirar
con `DeprecationWarning` (`provisioning/config.py:422-428`), no borrar.

El patrón de implementación es D-SEG-7 (`provisioning/orchestrator.py:259-266`), que ya lo resolvió en su
capa con la razón escrita. Con esto el criterio 3 del contrato («las **siete** capas, con test
parametrizado») queda aplicable tal como está.

### 3.7 · E-CRP-7 — Orden de adopción: **CRP-5 → CRP-6 → CRP-4 → CRP-1/CRP-3 → CRP-7**

**Corrige a la v1.0, que ponía CRP-4 primero con una justificación falsa.** La v1.0 argumentó que CRP-4
ataca «los únicos defectos que producen cifras erradas». No es cierto: **CRP-4 sólo rotula**. Marcar
`lgd.py:142-145` deja la LGD subestimada 20 pp, ahora con etiqueta; el `is_default` ausente seguiría
dando Stage 1. Lo que corrige ambos es el **gate único de entrada (CRP-5)**, que es además consistente
con P1 del contrato —el gemelo `days_past_due` sí levanta `IfrsStagingError`— y tiene patrón de
referencia en `cmf/engine.py:443`, `446-462`.

Vender rotulado como corrección es exactamente el parche que `AGENTS.md` §Visión manda señalar. El orden
corregido:

| # | Paso | Por qué aquí |
|---|---|---|
| 1 | **CRP-5** — gate único de entrada en IFRS 9 | Corrige de verdad §2.4-1 y §2.4-2, las dos cifras erradas. Local, sin API nueva |
| 2 | **CRP-6** — semántica única del flag | Antes de CRP-4: con cinco semánticas vivas y el flag en `True` en los tres presets, marcar nueve warnings haría abortar corridas en unas capas y no en otras |
| 3 | **CRP-4** — nada se apaga en silencio | Ya con semántica estable debajo. Aditivo, no rompe API |
| 4 | **CRP-1 + CRP-3** — vías y `Resolved[T]` | Requiere el inventario cerrado (§3.1.2) y el centinela de `is_default` (§3.3) |
| 5 | **CRP-7** — resolutor vs consumidor de EAD | Consume el `Resolved[T]` del paso 4 |

**Tensión declarada, no escondida:** este orden difiere lo caro de cambiar (la interfaz `Resolved[T]`)
detrás de tres pasos baratos, lo que invierte la regla rectora del contrato §1. Se acepta a conciencia
porque `Resolved[T]` **no es diseñable hoy** —le falta la decisión de §3.3 y el inventario de §3.1.2—, y
porque los pasos 1 y 2 corrigen cifras y comportamiento observable que hoy están mal. Coste asumido: las
emisiones del paso 3 se revisitan al llegar el paso 4.

**Relación con [`_ENMIENDA-IFRS9-HORIZONTE.md`](_ENMIENDA-IFRS9-HORIZONTE.md), que sigue PROPUESTA.**
No se duplica ni se absorbe: la degradación silenciosa del horizonte 12m es **un caso del paso 1** —una
carencia que hoy no se valida en la entrada y produce una ECL de Stage 1 incorrecta—, así que entra por
CRP-5 con el resto. Su bloqueo declarado (`D-HOR-0`: en qué unidad está `time_value`, quién la declara y
quién la verifica) **es exactamente un parámetro de los que CRP-1 obliga a declarar**, lo que lo
convierte en el primer caso de prueba de §3.2: si la regla de exigibilidad no lo resuelve, la regla está
mal. Ambas enmiendas se integran en el paso 1; la del horizonte conserva su propio SDD y su OK
pendiente.

### 3.8 · E-CRP-8 — El preset F4 **se cambia**: sale del modo diagnóstico (decidido por Cami)

`pit_mode="ttc_only"` en el preset que se entrega al usuario (§2.4-3) admitía dos salidas: declararlo
como capacidad no ejercida —barato, la maquinaria existe en `methodology.py:249-285`— o cambiarlo a un
modo PIT real. **Decisión de Cami (2026-07-25): se cambia.** Razón: declararlo sería rotular con
honestidad un resultado que igual no es el que un banco usaría, y el preset es la puerta de entrada del
requisito 1 de la visión.

Consecuencias que el cambio arrastra y que van con él, no después:

- El preset PIT real exige que la term-structure entrante traiga `pd_basis='pit'`
  (`ifrs9/engine.py:725-729`), lo que toca la cadena de la que sale — hay que verificar contra qué motor
  se genera hoy el fixture F4 antes de elegir el modo destino.
- Mueve el `config_hash` del preset → **recaptura de la demo con el patrón C-D** (árbol limpio, commit
  entre capturas) y **bump de versión antes** de recapturar, no después.
- Toca `ui/presets.py:764`, `scripts/derive_ifrs9_preset.py`, los tres fixtures publicados
  (`preset-ifrs9.json`, `results-ifrs9.json`, `report-ifrs9.html`) y la prosa que hoy traduce el slug
  (`report/prose.py:1625`).

Va **después** del paso 1 del orden (§3.7): el gate de entrada de CRP-5 puede cambiar qué configs son
válidas, y recapturar dos veces la demo es el desperdicio que el patrón C-D existe para evitar.

Nota aparte, que sigue abierta: `MethodologyFact` **no es** una marca declarada —se deriva del config, no
de lo que el motor hizo, y no llega a `card.falta_dato`—. CRP-4 debe fijar cuál de los dos canales manda
cuando ambos aplican.

## 4. Superficies afectadas

- **Motor**: `provisioning/ifrs9/{config,staging,lgd,ead,ecl,engine,step}.py` (pasos 1-3);
  `forward/{satellite,step}.py`, `survival/{cox_aft,config}.py`,
  `markov/{transition,term_structure,step}.py` (warnings nuevos y CRP-6).
- **Config y canal**: `core/config/{loader,schema,migration}.py` y `scripts/derive_ifrs9_preset.py` si
  §3.3 obliga a tocarlos; `ui/presets.py`; `core/config/hashing.py` (`survival` **no** es INFRA → mover su
  flag mueve el `config_hash`).
- **UI**: `web/src/fixtures/schema.json` (regenerar), `web/src/lib/schema.ts`. ⚠️ Las secciones
  `provisioning*` **no son editables por formulario** hoy (P1 del `HANDOFF`), así que todo lo que estos
  pasos añadan a IFRS 9 será alcanzable por preset o YAML, no por formulario. No lo resuelve esta
  enmienda; se deja escrito para que no se confunda con paridad lograda.
- **Copy público**: prosa del informe (`report/prose.py`), ficha metodológica (`methodology.py`), panel de
  resultados. Gates `tests/unit/test_public_copy.py` y `web/src/lib/public-copy.test.ts`.
- **Documentación del output**: `docs_site/avisos-declarados.md` gana los códigos nuevos (y corrige
  `:127-129`, que documenta el flag de `survival` como reservado); sus dos tests de coherencia
  bidireccional con el motor son el gate.
- **Fixtures de la demo**: cualquier código nuevo cambia `card.falta_dato` en F4 → recaptura con el
  patrón C-D (árbol limpio, commit entre capturas), con el bump de versión **antes** de recapturar.
- **SDD**: `_CONTRATO-RESOLUCION-PARAMETROS.md` §2, CRP-1, CRP-3, CRP-6, §7; `16-provisioning-ifrs9.md`;
  `18-survival.md:433`. Nota de CHANGELOG por el cambio de comportamiento del flag.

## 5. Criterios de aceptación

1. Los dos defectos de cifras (§2.4-1 y §2.4-2) tienen test con el valor numérico esperado, y ese test
   **falla** contra el código actual. Es el criterio del paso 1.
2. `fail_on_falta_dato` tiene el mismo comportamiento observable en las **siete** capas, con el test
   parametrizado que ya pide el contrato §6.3 —no siete tests escritos a mano—.
3. Los nueve warnings de §2.3 pasan `is_declared_warning()` **y** llegan efectivamente al filtro de su
   capa; para `markov/term_structure.py:71` el test debe fallar con el código actual, no sólo con el
   literal viejo. Cada código nuevo está documentado en `docs_site/avisos-declarados.md` y los dos tests
   bidireccionales lo atan al motor.
4. Los seis gatillos de §2.3 emiten marca declarada cuando quedan inertes; test por gatillo que verifique
   el caso apagado **y** el ejercido.
5. `IfrsProvisioningConfig()` sin argumentos es **ejecutable** —los cuatro campos en conflicto de §2.5
   dejan de contradecirse—, que es el CA-5 del contrato y ninguna decisión previa se hacía cargo.
6. Ningún test nuevo cementa un literal sin marca. Los dos existentes que lo hacen
   (`tests/unit/test_forward_satellite.py:354`, `:358`) se actualizan en el mismo commit que el motor.
7. **Al menos un caso de aceptación corre sobre un dataset externo real**, no sintético: las carencias
   que ataca esta enmienda (columna ausente, coste de recuperación ausente) son exactamente las que un
   dataset sucio destapa, y el requisito 2 de la visión se prueba de paso en vez de quedar para después.

## 6. Riesgos

- **Ruptura de fixtures y golden values.** Marcar nueve warnings cambia `card.falta_dato` en varias
  corridas capturadas. Mitigación: patrón C-D y bump de versión **antes** de recapturar.
- **Falso verde por prefijo.** El caso de markov es el ejemplo: poner el prefijo sin arreglar la ruta del
  filtro deja el gate en verde con el defecto vivo. Por eso el criterio 3 exige probar la llegada al
  filtro, no la forma del código.
- **Marcas nuevas en un mundo de cinco semánticas.** Una marca que en `internal` aborta
  (`internal/engine.py:388-395`) y en `ifrs9` no se mira. Es la razón de que CRP-6 vaya antes que CRP-4;
  si por lo que sea se invierte, hay que demostrar por capa —con test— que ninguna marca nueva entra en
  una ruta que aborte.
- **Alcance de CRP-3 sin cerrar.** El inventario no tiene total defendible (§2.1) y varios mecanismos
  cross-validan procedencia contra otra cosa, lo que encarece la migración. Mitigación: cerrarlo es la
  primera tarea del paso 4, con extensión aditiva y sin corte.
- **El re-censo también es falible.** Lo hicieron cinco lectores frescos, una auditoría de citas y una
  revisión adversarial; cuatro hallazgos caros se verificaron a mano contra `c02a4f7`. Aun así, toda
  decisión que cambie código exige su propio test que falle antes del arreglo.

## 7. Qué cambió tras la revisión adversarial

Seis puntos de la v1.0 no sobrevivieron a dos lectores frescos. Se dejan escritos con su razón:

| # | v1.0 decía | Por qué cayó |
|---|---|---|
| 1 | Eliminar `fail_on_falta_dato` de `survival` porque «no tiene carencia declarada que gobernar» | **Premisa falsa**: emite `DATO-INSTITUCIONAL-SUR-1/2/3` (`kaplan_meier.py:55-57`). Además habría sido ruptura pública sin migrador. Invertido en §3.6 |
| 2 | CRP-4 primero «porque ahí están los defectos que producen cifras erradas» | **Falso**: CRP-4 rotula, no corrige. Lo que corrige es CRP-5. Orden rehecho en §3.7 |
| 3 | «Trece mecanismos de procedencia» | No defendible: dos barridos dieron inventarios distintos; 5 eran de *esquema*, 1 referencia documental, 1 doble conteo, y faltaban ≥5 con cross-validación. §2.1 publica la estructura y difiere el total |
| 4 | «Ningún número de línea del censo original estaba corrido» | **Falso**: B3.a-1 movió `ifrs9/config.py` +10 y `presets.py` +4; dos citas del contrato quedaron corridas. Corregido en §1 |
| 5 | «Cinco gatillos apagados» y «el inventario completo (35 parámetros)» | Son **seis** gatillos (falta el backstop PIT, `staging.py:170-181`) y **55 campos** en siete modelos; los 35 eran cuatro submodelos |
| 6 | «Default defendible» como criterio | No operacionalizable: dos implementadores discrepaban en `low_credit_risk_exemption` y `ecl.rounding`, y chocaba con la propia E-CRP-3. Reemplazado por el test de cita normativa + condicionalidad (§3.2) |

Se añadieron tres decisiones que la v1.0 no tenía y sin las cuales la primera capa no era implementable:
la firma `Generic[T]` en vez de PEP 695 (§3.1.5), el centinela de `is_default` (§3.3) y la taxonomía con
familia y número de los nueve warnings (§3.5).
