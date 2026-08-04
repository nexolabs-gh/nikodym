# Censo — los diez defectos que destapó medir el abanico

> **Estado: CENSO, no diseño.** Ninguna decisión de aquí está tomada. Lo que hay son diez defectos
> **medidos contra el código**, con su `archivo:línea` y su reproducción, y los caminos posibles
> para cerrarlos. Tres exigen contrato y por eso se detienen aquí (regla del repo: un cambio
> contractual se diseña antes de programarse).
>
> **Base:** `main` = `969a2cd`. **Fecha:** 2026-08-04. **Método:** seis barridos independientes y en
> paralelo, uno por grupo de secciones, cada uno midiendo qué hace el motor con **cada valor** de
> cada punto de elección — 69 puntos, 172 opciones.
>
> **Por qué existe.** Escribir el catálogo del abanico obligó a contestar, opción por opción, *qué
> hace exactamente* y *qué exige*. Ninguno de estos diez defectos es del abanico: estaban ahí, y lo
> que los sacó fue tener que decir la verdad sobre cada opción en la pantalla.

## 0. El resultado en una frase

**Cuatro opciones no hacían nada y ahora lo declaran; una la cerró el gate el primer día; y quedan
diez defectos vivos, de los que tres son graves — uno publica un modelo con la discriminación
invertida y ninguna superficie avisa.**

## 1. 🔴 GRAVE-1 — `score_direction` está triplicado y nadie comprueba coherencia

**Qué es.** El mismo dato —«¿un puntaje más alto es mejor o peor cliente?»— se pregunta en tres
secciones (`scorecard`, `performance`, `stability`), con los mismos dos valores, y **se lee por
separado en cada una**.

**Reproducción, medida sobre el preset F1 completo:** con `scorecard.score_direction` en
`higher_is_lower_risk` y las otras dos en `higher_is_higher_risk`:

| superficie | veredicto |
|---|---|
| `NikodymConfig.model_validate` | OK |
| `check_pipeline` | `executable=True` |
| `check_dataset` | `compatible=True`, 0 desajustes, 0 requisitos |
| la corrida | `done`, **cero avisos declarados** |
| el informe | **AUC 0,288 · Gini −0,424** (desarrollo), −0,390 (holdout), −0,315 (OOT) |

El documento publica un modelo que **discrimina al revés**, con las cuatro superficies en verde.

**Por qué importa más que los otros nueve.** Los demás fallan ruidosamente o degradan; éste
produce un número plausible y **está invertido**. Es la clase de defecto más cara que puede tener un
motor de riesgo: nadie mira dos veces un Gini negativo si el sistema no lo señala.

**Dónde vive:** `NikodymConfig._check_cross_section` (`core/config/schema.py:1175`) sólo valida
`run.steps`; `report/prose.py:925` narra la dirección de la tarjeta y `report/prose.py:1350` la
fuente de desempeño, sin cruzarlas.

**Tres caminos, en orden de coste:**

1. **Un `requisitos_incumplidos` cruzado.** ❌ No cabe: el protocolo es **por sección** y esto es una
   invariante *entre* secciones — exactamente el límite que D-INV-8 dejó escrito para
   `required_sections`.
2. **Un chequeo en `_check_cross_section`**, que ya existe y es el sitio natural. ⚠️ Rompe configs
   hoy válidos ⇒ cambio de comportamiento ⇒ SDD.
3. **Que `performance` y `stability` HEREDEN la dirección de `scorecard`** cuando esa sección esté
   activa, dejando el campo propio sólo para uso standalone. Es la única que **elimina la clase** en
   vez de avisarla, y el mecanismo existe: `from_config_with_context` (D-FX-2). ⚠️ Cambia
   comportamiento y hay que medir si mueve `config_hash`.

**Recomendación: (3), por SDD.** Y con una advertencia medida: cerrar así **también cierra
MENOR-6**, porque el campo de `performance` desaparece.

## 2. 🔴 GRAVE-2 — dos trabajos del catálogo nacen inejecutables

Es la misma clase que D-OBL-11 cerró para los capítulos del informe: **el esqueleto que siembra un
trabajo no corre con los defaults del motor**. Hay patrón a seguir.

### 2.1 «PD lifetime (curvas de supervivencia)»

Declara `("data", "survival", "report")` y `external_artifacts=()` (`ui/jobs.py:111,118`). Pero el
default de `survival.input.pd_source` es `model_raw`, que exige `('model','raw_pd_frame')` — y ese
trabajo **no ofrece la sección `model` ni admite subir esa tabla**. Medido: `check_pipeline` da
`executable=False` con el default y `True` sólo con `pd_source='none'`.

El preset F4 lo esquiva escribiendo `"pd_source": "none"` a mano (`ui/presets.py:732`). ⚠️ Y el
comentario de `ui/jobs.py:114-117` —«survival no REQUIERE la PD»— es cierto **sólo** para
`pd_source='none'`, que no es el default.

### 2.2 «Comparar provisiones (CMF vs. interna)»

Declara `data, provisioning_cmf, provisioning_internal, provisioning, report` y está `available`.
Falla por **dos causas independientes**:

1. `provisioning.source_b` viene en `provisioning_ifrs9`, sección que ese trabajo no activa ⇒
   `ConfigError` del DAG. El trabajo que se llama como la regla del B-1 arranca comparando contra
   IFRS 9.
2. `provisioning_internal` exige `('calibration','calibrated_pd_frame')` con su fuente de PD de
   fábrica, y el trabajo declara `external_artifacts: ()` — sin puerta para inyectarla. Su hermano
   «Provisión interna / LGD» sí la declara (`ui/jobs.py:168-193`).

**Camino:** el esqueleto de cada trabajo debe producir un config **ejecutable**, que es lo que
D-OBL-11 fijó. Se cierra sembrando el valor que corre —o declarando el insumo externo— y **con un
gate que lo exija para los diez trabajos**, porque el defecto reaparece con cualquier trabajo nuevo.

## 3. 🔴 GRAVE-3 — el default de `provisioning` no es la regla del B-1

`ProvisioningConfig()` trae `source_a='provisioning_cmf'`, `source_b='provisioning_ifrs9'`,
`rule='max'`. **La regla del Capítulo B-1 (Circular 2.346) es `max(método estándar, método interno
del banco)` por institución**, y el Cap. A-2 num. 5 excluye el deterioro de NIIF 9 sobre
colocaciones (ESPECIFICACIONES §5.4).

⚠️ **El motor no miente sobre la procedencia**: `_rule_source` (`provisioning/orchestrator.py:765-775`)
devuelve `_CROSS_FRAMEWORK_RULE_SOURCE` —«comparativo entre marcos contables SIN norma chilena que
lo exija»— y sólo con `source_b='provisioning_internal'` cita el B-1. **Pero publica la cifra
igual**, bajo un campo cuyo título es «Regla de constitución de la provisión reportada».

La razón escrita del default es «retrocompatibilidad» (`provisioning/config.py:31-33`).
⚠️ **Cambiarlo mueve `config_hash`**: `provisioning` es sección computacional.

## 4. Los siete restantes, medidos

| # | defecto | evidencia | coste de cerrar |
|---|---|---|---|
| **M-1** | `model.optimizer='bfgs'`/`'lbfgs'` pasan `tol=` a una ruta que no lo acepta; statsmodels emite `FutureWarning`, y bajo `filterwarnings=["error"]` —el gate del repo— **la corrida muere**. Alcanzable desde el formulario y **ningún test lo ejercita**: `test_model_config.py:83` lo construye pero nunca ajusta | `model/estimator.py:1184-1189` | bajo; el campo es letra muerta en 2 de sus 3 rutas |
| **M-2** | `check_pipeline` deriva el `requires` de `tuning`/`explain` de la sección `ml` **de fábrica**, no la del usuario: con `ml.feature_source='selection_woe'` exige `binning` (falso rojo) y no exige `selection` (falso verde). Los steps revalidan en `execute`, así que no corrompe resultados — pero la comprobación previa miente | `tuning/step.py:110`, `explain/step.py:110`; `TuningConfig` no tiene ningún campo que lo declare | contractual: el hook `from_config_with_context` entrega dominios activos, no el config de `ml` |
| **M-3** | `CmfProvisioningStep.requires` es **estático** y miente bajo `pd_mapping.method='pd_breaks'`: devuelve sólo el frame de datos mientras el paso exige el artefacto de PD. Sus tres hermanas de provisiones lo construyen dinámico | `cmf/step.py:62` vs `cmf/step.py:291-294` | bajo; **mitigado** ya por `requisitos_incumplidos_por_contexto` (`969a2cd`), pero el DAG sigue sin ordenar los pasos |
| **M-4** | `performance.partitions=()` valida sin quejarse y muere mucho después, con un mensaje interno. **Desmarcar las tres casillas es alcanzable desde la pantalla** | `performance/config.py:167` (sin `min_length`); muere en `performance/evaluator.py:263` | trivial: `min_length=1`, que además lo impide en el formulario |
| **M-5** | `report.formats='xlsx'` sin el extra **mata el informe entero**, no sólo la planilla. `pdf` y `docx` degradan con aviso y tienen interruptor propio; `xlsx` no tiene ninguno de los dos | `report/exports.py:192-197`, sin captura en `report/step.py:345-360` | bajo; asimetría con sus dos hermanos |
| **M-6** | La ficha del modelo publica **dos optimizadores contradictorios**: los umbrales dicen el elegido y las estadísticas el ejecutado. Con `engine='glm_binomial', optimizer='bfgs'` el mismo documento dice `bfgs` e `irls` | `model/step.py:537` vs `model/estimator.py:1439` | bajo; un validador lee dos respuestas a la misma pregunta |
| **M-7** | `calibration.anchor_source='development_observed'` —**el default**— **descarta en silencio** el ancla que el usuario escribió. Las otras tres fuentes fallan si falta el número; ésta acepta y descarta el que sobra. El informe publica la tasa observada sin decir que se pidió otra | `calibration/calibrator.py:621-634`; el validador no lo impide (`config.py:388`) | bajo. ⚠️ Es el mismo mecanismo que hizo que `docs_site/` publicara doce días un ancla que el preset ya no tomaba, visto desde el otro lado |

## 5. Lo que el abanico SÍ cerró, para no re-medirlo

- **`binning.solver='cp'`**: el config lo aceptaba y las tres superficies previas daban verde sobre
  una elección que muere en el paso 2. Cerrado en el validador (`969a2cd`), con el literal intacto.
- **El config de fábrica de IFRS 9**: pedía una curva «a condiciones actuales» y pesos de escenario
  que sólo `forward` publica. Ahora se avisa antes de correr.
- **`survival.input.pd_source='calibration'`** y **`provisioning_cmf.pd_mapping`**: avisan por
  contexto lo que el DAG no ve.
- **Cuatro opciones muertas, declaradas con su cita**: el redondeo de la pérdida IFRS 9 (dos
  valores), `model.engine='glm_binomial'`, `selection.priority_order='gini'` y
  `report.formats='html'`.

## 6. Límites del catálogo que quedaron declarados, no escondidos

1. **El abanico no puede expresar «esta opción no hace nada BAJO otra opción».** Los tres estados de
   D-ABA-4 son propiedades de la **opción**; hay al menos cinco casos que son propiedades del **par**
   —`optimizer × engine`, `criterion × direction='none'`, `anchor_kind × anchor_source`,
   `performance.score_direction × evaluation_source`, `report.ai.provider × ai.enabled`—. Se
   cerraron declarando la condición en el `help` del punto, con el precedente de
   `stability.temporal_freq`. Si el cuarto estado computado de D-ABA-4 crece, éste es su caso de uso
   natural: se evalúa sin mirar los datos, sólo el config.
2. **`markov` y `forward` son la «tercera categoría» real**: el motor las implementa y las prueba,
   pero ninguna sección del formulario las configura. Van `_DISPONIBLE` con el límite en el `help`.
3. **`scorecard.rounding_method='nearest_integer'` es redondeo bancario** (12,5 → 12; 13,5 → 14).
   Quien reproduzca la tarjeta en Excel con `REDONDEAR` obtiene un punto de diferencia en todo tramo
   que caiga en la mitad. Declarado en el `help`; cerrarlo movería puntajes ⇒ SDD.
