# Enmienda — la corrida puntúa a la población through-the-door que no entra al ajuste

| Campo | Valor |
|---|---|
| **Tipo** | Enmienda a [`09-scorecard.md`](09-scorecard.md) §6 («Poblaciones»: `fuera_de_modelo` «no recibe `score`»), a [`06-binning.md`](06-binning.md) §6 (el `transform_out_of_model` que anunciaba «en una versión futura»), a [`08-model.md`](08-model.md) y [`10-calibration.md`](10-calibration.md) (sus poblaciones) y, si Cami aprueba §5.1, a [`11-performance-stability.md`](11-performance-stability.md). Cumple lo que [`31-simplicidad-y-flujo-guiado.md`](31-simplicidad-y-flujo-guiado.md) §8 y [`_ENMIENDA-FLUJO-GUIADO-SCORECARD.md`](_ENMIENDA-FLUJO-GUIADO-SCORECARD.md) ya aprobaron («target con nulos: se puntúan, no se ajustan») y el motor nunca implementó |
| **Decisiones** | **D-TTD-1** (qué filas se puntúan y cómo), **D-TTD-2** (los artefactos y sus dependencias), **D-TTD-3** (qué dicen las superficies), **D-TTD-4** (representatividad, sujeta a §5.1) y **D-TTD-5** (las categorías que no existían en Desarrollo se cuentan y se dicen, sujeta a §5.2) |
| **Módulos** | `nikodym.binning`, `nikodym.model`, `nikodym.scorecard`, `nikodym.calibration` (`step`), `nikodym.guided` (`summaries`, `scorecard`), `nikodym.report` (exports); con §5.1 (a), `nikodym.stability` |
| **Fase** | F1 |
| **Estado** | **APROBADA por Cami el 2026-09-24/25** (S22, interactivo): con la representatividad (§5.1 a) y con las categorías no vistas puntuadas como hoy y declaradas en todas las muestras (§5.2 a). La release espera a esta enmienda y a la de copy |
| **Depende de** | D-DATA-5 (TTD es un rol booleano superpuesto a la partición), D-FAL-1 y D-RAR-1 (la transformación que reciben estas filas), D-SC-19 (el patrón: lo accesorio no detiene la corrida) |
| **Release** | Aditiva: artefactos nuevos con clave propia, ningún campo de config, ningún número existente cambia ⇒ **minor** |
| **Autor / Fecha** | Claude Code (writer) / 2026-09-24 |

---

## 0. Por qué existe: medido con un dataset real

La muestra pública de préstamos 7(a) de la SBA que Cami usa para su prueba trae **6.225
préstamos sin desenlace** (cancelados antes de desembolsar o exentos) de 49.999: el 12,5 % de
quienes llegaron a pedir crédito. Hoy la corrida **no les da puntaje ni PD**:

- `binning` sólo transforma `desarrollo`/`holdout`/`oot` (`binning/step.py`, `_modelable_mask`), así
  que esas filas no llegan a `model`, `scorecard` ni `calibration`.
- SDD-09 §6 lo dice: «`fuera_de_modelo`: no recibe `score` por defecto».
- **Pero el contrato aprobado de la puerta guiada promete lo contrario.** SDD-31 §8: «Target con
  nulos: son solicitudes recientes sin desempeño (TTD); se puntúan, no se ajustan». La enmienda
  FLUJO-GUIADO-SCORECARD lo repite, y la inferencia que la puerta muestra al construir el
  `Scorecard` también: «la fila queda indeterminada, se puntúa y no entra al ajuste»
  (`guided/scorecard.py`, `inferencia_resultado_vacio`). En `d2839d8` se corrigió la línea del
  resumen de datos para que dijera la verdad («no entran al ajuste ni reciben puntaje»); la
  inferencia, su docstring y los dos documentos de diseño siguen prometiendo el puntaje.

Un modelador que trae su cartera con indeterminados espera lo que SDD-31 promete: saber qué
puntaje y qué PD le da el modelo a **toda** la población que pasó por la puerta, no sólo a la que
tiene desenlace.

**Medido (2026-09-24, SBA crudo por la puerta guiada, `date="fecha_aprobacion"`,
`oot_from="2008-01-01"`, `config_hash` `a27e678f…`, puntuando esas filas con el bundle sólo para
medir):**

| Muestra | Operaciones | Puntaje medio | Mediana | PD calibrada media |
|---|---|---|---|---|
| Desarrollo | 30.316 | 539,4 | 550 | 23,8 % |
| Holdout | 7.733 | 539,0 | 549 | 23,8 % |
| Fuera de tiempo (OOT) | 5.725 | 527,2 | 536 | 27,2 % |
| **Sin desenlace** | 6.225 (5.855 con el bundle, ver §5.2 y §7) | **554,9** | **561** | **15,0 %** |

Los préstamos que quedaron sin desenlace **no se parecen** a la muestra de ajuste: el modelo los
ve menos riesgosos. PSI del puntaje, con los deciles de Desarrollo: **0,175** entre Desarrollo y
los sin desenlace, frente a **0,004** entre Desarrollo y la TTD completa. La TTD completa contiene
al propio Desarrollo, que es el 61 % de ella, y eso diluye la diferencia (§4). Es justo el dato
para el que D-DATA-5 creó el rol `ttd`, porque sirve para medir representatividad.

## 1. D-TTD-1 — qué filas se puntúan y cómo

1. **Filas:** las que tienen `partition == "fuera_de_modelo"` **y** `ttd == True`. Se respeta la TTD
   ya declarada, sin cambiar D-DATA-5 (`data/partition.py`, `_ttd_mask`):
   - con `data.partition.ttd_includes_excluded=True` —el default y lo que usa la puerta guiada—
     `ttd` vale `True` en todas las filas, así que se puntúan **todas** las fuera de modelo;
   - con `False`, `ttd` vale `False` en **todas** las fuera de modelo: la TTD declarada son sólo
     las modelables, que ya tienen puntaje, y **no se puntúa ninguna fila nueva**.
2. **Qué hay en esa partición.** No son sólo indeterminados. `fuera_de_modelo` reúne tres grupos:
   - las filas **indeterminadas** (`label_status="indeterminado"`: target vacío o sin regla que
     las clasifique);
   - las **excluidas** por una regla de exclusión (`label_status="excluido"`, target vacío);
   - las filas con **desenlace conocido que la partición apartó**, porque su valor no se mapeó a
     ninguna muestra en la división por columna (`data/partition.py`, `_split_from_column`). Esas
     tienen target 0/1.

   Por eso el rótulo es **«Fuera del ajuste»**, no «Sin desenlace», y las superficies dicen la
   composición (§3).
3. **Cómo:** con **la misma transformación que ya reciben Holdout y OOT**, con los objetos ya
   ajustados y sin reajustar nada, paso por paso:
   - `binning`: `WoEBinner.transform` sobre las columnas predictoras, con los WoE asignados de
     D-FAL-1 y los reagrupamientos de D-RAR-1;
   - `model`: las columnas WoE finales (`estimator.final_woe_columns_`), con el mismo chequeo de
     WoE finita que `FeatureSelector.transform` le hace a las modelables, y
     `decision_function`/`predict_pd` del estimador ajustado;
   - `scorecard`: `PointsScaler.transform`;
   - `calibration`: los **parámetros ajustados** del calibrador. `PDCalibrator.transform` filtra
     a Desarrollo, Holdout y OOT (`_validate_raw_contract`), así que con estas filas devolvería
     un frame vacío. El paso aplica el mismo estado con la función interna que `transform` usa
     después de filtrar (`_transform_with_state`). La API pública de `transform` no cambia.
     Vale para los tres métodos (`intercept_offset`, `platt_scaling`, `isotonic`).
4. **Qué no hacen estas filas:** no entran a ningún ajuste —binning, selección, modelo, escala ni
   calibración— y no tocan ninguna métrica existente: AUC, KS, PSI, calibración, validación y
   desempeño se calculan exactamente sobre las mismas filas que hoy. La mayoría no tiene desenlace.
   Las que sí lo tienen fueron apartadas por la partición, y tampoco entran a las métricas de
   discriminación.
5. **No es inferencia de rechazados.** No se les imputa un desenlace ni se reajusta el modelo con
   ellas; eso sigue siendo de la sub-fase de originación (SDD-02, «Decisiones abiertas»).
6. **Puntuarlas nunca detiene la corrida** (el patrón de D-SC-19). Si la transformación de estas
   filas falla en cualquier paso, ese paso publica su clave vacía y la corrida sigue:
   - el trail registra `ttd_no_puntuada` con la causa y el paso;
   - el resumen de la etapa lo dice como **alerta**;
   - los pasos siguientes publican vacío sin volver a fallar.

   Una corrida que hoy termina `done` sigue terminando `done`.

## 2. D-TTD-2 — los artefactos, sus dependencias y los exports

| Clave nueva | Espejo de | Columnas |
|---|---|---|
| `("binning", "out_of_model_woe_frame")` | `("binning", "woe_frame")` | Las mismas: estructurales (`target`, `label_status`, `partition`, `ttd`, según `keep_structural_columns`) y `<feature>__woe` |
| `("model", "out_of_model_pd_frame")` | `("model", "raw_pd_frame")` | `partition`, `target`, `linear_predictor`, `pd_raw` |
| `("scorecard", "out_of_model_score")` | `("scorecard", "score")` | Las del `score`: estructurales, `<feature>__points` y `score` |
| `("calibration", "out_of_model_calibrated_pd_frame")` | `("calibration", "calibrated_pd_frame")` | Las **ocho** de `_OUTPUT_COLUMNS`: `partition`, `target`, `linear_predictor`, `pd_raw`, `linear_predictor_calibrated`, `pd_calibrated`, `calibration_method`, `anchor_kind` |

- **Índice:** el de esas filas en `("data", "frame")`, igual en las cuatro claves y **disjunto**
  del de las modelables.
- **Cuándo se publican:** cada paso que **corre** publica su clave, vacía y con su esquema si no
  hay filas. Con `run(until="binning")` sólo existe la de `binning`; las demás, como cualquier
  artefacto de un paso que no corrió, no existen.
- **Dependencias:** cada clave nueva entra en el `optional_requires` del paso siguiente, nunca en
  `requires`:

  | Paso | `optional_requires` nuevo |
  |---|---|
  | `model` | `("binning", "out_of_model_woe_frame")` |
  | `scorecard` | `("binning", "out_of_model_woe_frame")`, `("model", "out_of_model_pd_frame")` |
  | `calibration` | `("model", "out_of_model_pd_frame")`, `("scorecard", "out_of_model_score")` |
  | `stability`, con §5.1 (a) | `("scorecard", "out_of_model_score")`, `("calibration", "out_of_model_calibrated_pd_frame")` |

  Un trabajo con artefactos inyectados —«Validar un modelo existente» y los demás que no corren
  `binning`— sigue funcionando igual. Si la clave de entrada falta, el paso publica la suya
  **vacía**, sin alerta, porque no había nada que puntuar. Si la entrada existe pero es
  inconsistente —columnas WoE finales ausentes, índice distinto entre el par—, rige §1.6: clave
  vacía, `ttd_no_puntuada` y alerta.
- **Una cadena, no cuatro claves sueltas.** Cada paso publica filas sólo si **todas** sus entradas
  nuevas tienen filas y el mismo índice. Si una etapa anterior quedó vacía por una falla, la
  siguiente publica vacío sin volver a alertar: la alerta ya la dio la etapa que falló.
  - Si el modelo produjo la PD y la tarjeta falló, la calibración no publica PD para filas sin
    puntaje.
  - Si la calibración falló, la estabilidad no mide la representatividad con una PD que no
    existe.

  Así las cuatro claves comparten índice o están vacías desde el punto de la falla.
- **Los artefactos existentes no cambian**: `woe_frame`, `raw_pd_frame`, `score` y
  `calibrated_pd_frame` conservan sus filas, su índice y sus invariantes. El chequeo de índice
  idéntico entre `score` y `raw_pd_frame` sigue intacto, y el par nuevo tiene el suyo.
- **`selection` no cambia.** `FeatureSelector.transform` sólo recorta columnas y verifica que el
  WoE sea finito; `model` hace lo mismo con las columnas finales del estimador.
- **Nombre:** `out_of_model_*` porque son las filas de la partición `fuera_de_modelo` que la TTD
  declarada incluye. No se llama `ttd_*`: la TTD completa también incluye Desarrollo, Holdout y
  OOT, que siguen en sus artefactos de siempre.
- **Exports.** `scorecard.out_of_model_score` y `calibration.out_of_model_calibrated_pd_frame` se
  registran como tablas **por observación**, junto a `scorecard.score` y
  `calibration.calibrated_pd_frame`:
  - salen completas como exports de datos, no dentro del documento, con los títulos «Puntaje de
    las operaciones fuera del ajuste (TTD)» y «PD calibrada de las operaciones fuera del ajuste
    (TTD)»;
  - **una clave nueva vacía no llega al informe**: el `ReportBuilder` no la recolecta, así que no
    hay adjunto de cero filas, ni referencia en el anexo, ni hoja vacía en el Excel. Hoy el
    builder recolecta los `DataFrame` vacíos y `data_export_refs` no los filtra; el filtro es sólo
    para estas claves;
  - los dos frames intermedios no se exportan.
- **Trail.** Una decisión en `scorecard`: `regla="puntuar_ttd_fuera_de_modelo"`,
  `valor={filas, indeterminadas, excluidas, con_desenlace}` y `accion="puntuar_sin_ajustar"`.
  - Las decisiones que hoy dicen `no_puntuar`/`no_calibrar` sobre `fuera_de_modelo` (en `model`,
    `scorecard` y `calibration`) nunca se disparan, porque `binning` ya filtra antes, y no cambian.

## 3. D-TTD-3 — qué dicen las superficies

| Superficie | Qué dice |
|---|---|
| **Resumen de datos** | La línea de `d2839d8` pasa de «no entran al ajuste ni reciben puntaje» a «no entran al ajuste; la tarjeta las puntúa aparte, como parte de la población total (TTD)». Lo dice en futuro porque la etapa de datos no sabe si la corrida llegará a la tarjeta (`run(until=…)`). Con `ttd_includes_excluded=False` dice lo que pasa: «no entran al ajuste ni a la población total (TTD), así que no se puntúan» |
| **Inferencia de la puerta** | El motivo «se puntúa y no entra al ajuste» pasa a ser verdad y no cambia. Se precisa su docstring |
| **Resumen de la tarjeta** | Una línea condicional con la composición, p. ej. «Fuera del ajuste (TTD): 6.225 operaciones puntuadas —6.225 indeterminadas—, puntaje medio 555 (Desarrollo 539)». Nombra sólo los grupos con filas |
| **Resumen de calibración** | La tabla «PD por muestra» gana la fila «Fuera del ajuste (TTD)» con la PD media cruda y la calibrada. La tasa observada se calcula sobre las filas con target 0/1, si las hay, y si no queda vacía (—). Suma una línea, p. ej. «PD calibrada media de toda la población que pidió crédito (TTD, 49.999 operaciones): 23,1 %». Las cifras de los ejemplos son ilustrativas: las del §0 salen del bundle, sobre 5.855 filas |
| **Pantalla, informe (página ejecutiva) y `sc.results`** | Leen la misma fuente que `summary()`: las líneas y la fila llegan solas |
| **Informe y Excel** | Los dos exports por observación de §2, sólo cuando tienen filas. El Excel por etapa los incluye si el informe los publica para el dominio; se mide al implementar |
| **SDD-09 §6, SDD-06 §6, SDD-08, SDD-10, SDD-31 §8** | Se anotan con un puntero a esta enmienda cuando se implemente |

Todo lo que se lee sale de los mapas de rótulos existentes. El rótulo «Fuera del ajuste» de la
partición `fuera_de_modelo` es el mismo que fija D-CPY-1 en
[`_ENMIENDA-COPY-PRUEBA-REAL-SBA.md`](_ENMIENDA-COPY-PRUEBA-REAL-SBA.md), y las dos enmiendas
comparten esa entrada de `report/prose.py`. Aquí se le añade «(TTD)» porque, puntuadas, son la
parte de la población total que no entró al ajuste.

## 4. D-TTD-4 — representatividad: lo que quedó fuera del ajuste frente a Desarrollo (sujeta a §5.1)

Si Cami la aprueba, `stability` publica un PSI del puntaje entre Desarrollo y las filas fuera
del ajuste puntuadas:

- **Clave aditiva** `("stability", "out_of_model_psi")`, con el mismo esquema por tramo que
  `psi_table` y los mismos tramos del puntaje que usa la comparación Desarrollo vs. OOT. El motor
  PSI es el de siempre (`_psi_from_counts`); no se escribe otro.
- **No es una comparación configurable**: no se añade `dev_vs_ttd` a `stability.comparisons`, y por
  eso el `config_hash` de ningún preset se mueve. Se calcula cuando hay filas fuera del ajuste
  puntuadas; si no las hay, la clave queda vacía y, como en §2, no llega al informe.
- **Se compara contra lo que quedó fuera, no contra la TTD completa.** La TTD contiene al propio
  Desarrollo (61 % en el SBA), y el PSI contra ella sale casi cero aunque lo de fuera difiera
  mucho: 0,004 frente a 0,175, medido.
- **Rótulo propio.** Los cortes son los **efectivos** de la corrida,
  `stability.psi_stable_threshold` y `stability.psi_review_threshold` (0,10 y 0,25 por defecto),
  pero la lectura es de representatividad, no de deriva:
  - «se parecen», por debajo del corte estable;
  - «difieren moderadamente», entre los dos cortes;
  - «difieren», desde el corte de revisión.

  No se dice «Redesarrollar», porque no hay nada que redesarrollar. La banda y la alerta se derivan
  de esos dos valores, nunca de cifras escritas en el código.
- **Fuera del veredicto.** No entra a `validation` ni al estado técnico. El resumen de estabilidad
  gana una línea: «Fuera del ajuste frente a Desarrollo: PSI 0,175 — difieren moderadamente: el
  modelo las ve con menor riesgo (PD calibrada media 15,0 % frente a 23,8 %)». Sólo «difieren»
  sube como alerta a «Qué revisar».

## 5. Lo que Cami decide

| # | Decisión | Opciones | Recomendación |
|---|---|---|---|
| 5.1 | ¿Entra la representatividad (§4) en esta enmienda? | (a) **sí**: puntuar y además medir si lo que quedó fuera se parece a la muestra de ajuste; (b) no: sólo puntuar, y la representatividad va en otra enmienda | **(a)**: puntuar sin comparar deja una columna sin lectura. D-DATA-5 creó el rol `ttd` para medir representatividad, y el SBA muestra que la diferencia existe (PSI 0,175). Cuesta una clave aditiva y una línea |
| 5.2 | Las 370 filas fuera del ajuste con una categoría que no existía en Desarrollo (§7) | (a) **puntuar ahora con el tratamiento de hoy** —el mismo que reciben 2.620 filas OOT—, y **contarlo y decirlo en todas las muestras** (D-TTD-5), sin cambiar ningún número; la regla para esas categorías va en su propia enmienda; (b) no puntuar fuera del ajuste hasta que esa regla exista | **(a)**: hoy OOT ya recibe ese tratamiento y sólo el trail lo registra; el modelador no lo ve. Con (a) deja de ser silencioso en todas las muestras a la vez y la regla se corrige una sola vez para todas. Con (b) la TTD espera a una enmienda que puede cambiar números de OOT, y eso en 1.x exige su propia decisión |

Lo demás no se pregunta porque tiene una respuesta de principio: las filas son las de la TTD ya
declarada, el tratamiento es el de Holdout/OOT y nada es configurable (§13).

### 5.2 (a) en detalle: D-TTD-5 — las categorías no vistas se cuentan por muestra y se dicen

**Lo que ya existe.** `WoEBinner.transform` cuenta los niveles categóricos no vistos en el ajuste
(`_count_unknown_categories`, en `unknown_categories_`), y `BinningStep._log_unknown_categories`
emite `categoria_no_vista` con `accion="asignar_woe_neutral"`. En el SBA registra `anio_fiscal`
2.620, `programa` 58 y `estado_del_proyecto` 1. Pero el conteo junta Holdout y OOT y **sólo vive en
el trail**: ningún resumen, pantalla ni informe lo dice, y el modelador no lee el trail.

**Lo que se añade:**

- **Quién cuenta.** `binning` cuenta por variable y por muestra —Holdout, OOT y fuera del ajuste—
  con la **misma función pura** `_count_unknown_categories` sobre las filas de cada muestra.
  Desarrollo no aparece: por construcción, todo lo que tiene lo vio.
- **Sin tocar lo auditado, salvo un registro falso.** El estado publicado del `process` queda
  **exactamente como hoy**, y el evento `categoria_no_vista` también **con el default**
  (`cat_unknown=None`). Con un valor declarado, hoy el evento dice `accion="asignar_woe_neutral"`
  aunque OptBinning aplicó ese valor. Ese registro miente. Pasa a
  `accion="asignar_woe_declarado"`, con el valor en `umbral` (revisión adversarial, pasada 3).
  El orden es fijo:
  1. la transformación de las modelables;
  2. su registro, igual que hoy;
  3. la transformación de las filas fuera del ajuste;
  4. `unknown_categories_` vuelve al valor de las modelables, porque cada `transform` lo reemplaza.

  Sin filas fuera del ajuste no se llama a `transform`.
- **Dónde queda.** En una clave aditiva propia, `("binning", "unseen_categories")`, un frame con
  columnas `variable`, `muestra` y `filas`, vacío si no hay ninguna. **No es un campo de la card**:
  el `ReportBuilder` vuelca toda la card de `binning` al anexo, y un campo nuevo, aunque vacío,
  cambiaría el informe de toda corrida. La clave no se registra como tabla del informe.
- **Qué dice el resumen de «Tramos y WoE».** Una **alerta** por variable, redactada desde el
  tratamiento **efectivo** de `binning.cat_unknown`:
  - con el default (`None`, WoE 0): «anio_fiscal: 2.620 operaciones de Fuera de tiempo (OOT) y 370
    fuera del ajuste traen una categoría que no existía en Desarrollo; en esa variable reciben WoE
    0, el riesgo promedio»;
  - con un valor declarado, dice ese valor: «reciben el WoE declarado para categorías no vistas
    (−0,5)».

  La página ejecutiva y la pantalla la leen de la misma fuente.
- **Qué no cambia.** Ningún WoE, puntaje ni PD y ningún campo de card. Ningún evento del trail
  cambia con el default. Se dice en pantalla lo que hoy sólo registra el trail.

## 6. Estrategia de tests

| # | Test | Nace rojo porque |
|---|---|---|
| 1 | **Gate de aceptación**: el SBA termina `done` con las cuatro claves de §2, 6.225 filas cada una, y el índice de esas filas es disjunto del de las modelables | Las claves no existen |
| 2 | **Paridad con la transformación de Holdout**, en un fixture, **en todas las filas fuera del ajuste** (incluidas las que traen una categoría no vista): cada fila recibe el mismo WoE, predictor lineal, puntaje y PD calibrada que da aplicar a mano `binner.transform`, el estimador, el escalador y el estado del calibrador ajustados | La regla no existe |
| 2b | Lo mismo con cada método de calibración: `intercept_offset`, `platt_scaling` e `isotonic` | La calibración devuelve vacío |
| 3 | **Paridad con el bundle** en las filas que el bundle puntúa: el `FittedScorecardBundle.apply` da el mismo `score` y la misma `pd_calibrated`. En las que no puntúa, el test **fija el desacuerdo conocido**: el motor les da el riesgo promedio y el bundle `categoria_no_observada_en_fit` (§7). Si una enmienda futura lo corrige, este test cambia a propósito | La regla no existe |
| 4 | Con `ttd_includes_excluded=False` las cuatro claves quedan vacías, no hay decisión y la línea de datos dice que no se puntúan | Hoy la línea no lo dice |
| 4b | **División por columna con un valor no mapeado que trae desenlace**: esas filas se puntúan, la composición las nombra «con desenlace» y la tasa observada de la fila «Fuera del ajuste (TTD)» se calcula sobre ellas | La regla no existe |
| 5 | Sin filas fuera del ajuste: las cuatro claves se publican vacías con su esquema, no hay decisión ni línea de resumen, y el informe no gana adjuntos | Las claves no existen |
| 6 | **Nunca detiene**: una falla inyectada en la transformación de esas filas deja la corrida `done`, las claves vacías, `ttd_no_puntuada` en el trail y la alerta en el resumen | La regla no existe |
| 6a | **La falla se propaga por la cadena**: una falla inyectada en `PointsScaler.transform` deja vacías la tarjeta, la calibración y la representatividad aunque el modelo haya producido PD; una sola alerta, la de la tarjeta | La cadena no existe |
| 6b | **Entradas inyectadas**: un trabajo que no corre `binning` (p. ej. «Validar un modelo existente») sigue igual; `model`, `scorecard` y `calibration` publican vacío sin alerta. Con `run(until="binning")` sólo existe la clave de `binning` | Las dependencias no existen |
| 7 | Una decisión `puntuar_ttd_fuera_de_modelo` con sus conteos por grupo | No se emite |
| 8 | El resumen de datos, el de la tarjeta y la tabla de calibración dicen lo de §3, sin identificadores del motor; la línea de datos ya no dice «ni reciben puntaje» | No lo dicen |
| 9 | Los dos exports por observación salen con su título cuando tienen filas | No están registrados |
| 10 | Con §5.1 (a): el PSI de representatividad del SBA, su rótulo y su línea; la clave vacía sin filas; `validation` no la lee | No existe |
| 10a | Con §5.1 (a) y los dos cortes de estabilidad cambiados (p. ej. 0,05 y 0,15): la banda y la alerta siguen a los cortes efectivos | No existe |
| 10b | Con §5.2 (a): `("binning", "unseen_categories")` del SBA da `anio_fiscal` con 2.620 en OOT y 370 fuera del ajuste, y la alerta lo dice; ningún WoE cambia | No existe |
| 10c | Con §5.2 (a): el evento `categoria_no_vista` y `binning.process.unknown_categories_` quedan idénticos a los de hoy **con** filas fuera del ajuste | La transformación nueva los reemplazaría |
| 10d | Con §5.2 (a) y un `cat_unknown` numérico declarado: el WoE aplicado, la alerta y el evento del trail dicen el mismo valor (`asignar_woe_declarado`), no «neutral» ni «el riesgo promedio»; con el default, el evento es el de hoy | Hoy el trail dice «neutral» |
| 11 | **Bit a bit** sobre el preset F1, que no tiene filas fuera de modelo: las únicas diferencias en los artefactos son las claves nuevas (vacías, si F1 no trae categorías no vistas; se mide); ningún campo de card ni evento del trail cambia. **El informe renderizado y sus exports quedan idénticos**, comparados antes y después. El `config_hash` `1063d6cf…` y las cinco cifras quedan intactos | — (guardrail) |

**Controles negativos:**

- no filtrar por `ttd` (4);
- puntuar también las modelables en la clave nueva (1);
- reajustar el calibrador con las filas nuevas (2);
- llamar a `PDCalibrator.transform` en vez del estado (2b);
- dejar que la falla de §1.6 levante (6);
- que la calibración lea sólo la PD del modelo (6a);
- declarar `requires` en vez de `optional_requires` (6b);
- no registrar el export (9);
- dejar pasar una clave vacía al informe (5, 11);
- comparar contra la TTD completa (10);
- escribir los cortes 0,10/0,25 en el código (10a);
- no contar la categoría no vista (10b);
- no restaurar `unknown_categories_` tras la transformación fuera del ajuste (10c);
- redactar la alerta o el evento sin mirar `cat_unknown` (10d);
- poner el conteo en la card (11).

## 7. Defecto previo medido: una categoría que no se vio en Desarrollo (la regla se eleva aparte)

Al medir el §0 apareció un defecto anterior a esta enmienda, que también afecta a Holdout y OOT:

- En el SBA, `anio_fiscal` entra como predictora (es el hallazgo 6 de la enmienda de copy). El año
  fiscal 2009 **no existe en Desarrollo** por construcción: la frontera OOT es 2008-01-01 y el
  año fiscal 2009 empieza el 1-oct-2008.
- **El motor** transforma esa categoría no vista con WoE ≈ 0 (`2,2e-16`), que el escalador
  normaliza al WoE 0 de los tramos `Special`/`Missing` vacíos. Resultado: el riesgo promedio, 74
  puntos, a las **2.620** operaciones OOT de 2009. Es el default de `binning.cat_unknown` (`None`,
  WoE neutral) y **sólo lo declara el trail** (`categoria_no_vista`, con Holdout y OOT juntos).
  Ningún resumen ni pantalla lo dice.
- **El bundle** no las puntúa: `categoria_no_observada_en_fit` en 2.620 filas OOT (más una por
  `estado_del_proyecto`) y en 370 de las 6.225 fuera del ajuste. **La corrida y el bundle
  discrepan hoy** en esas filas, y el test que ancla la paridad corre sobre datos sin categorías
  nuevas.

**Esta enmienda no corrige la regla.** Asignar otro WoE cambiaría números de corridas que hoy
terminan, y en 1.x eso exige su propia enmienda y decisión. Lo que sí hace, con §5.2 (a), es
**decirlo** en todas las muestras (D-TTD-5) y **fijar el desacuerdo** con el bundle en un test
(test 3). Queda **elevado a Cami** como enmienda propia: una regla declarada para categorías no
vistas, que el motor y el bundle apliquen igual, junto con el aviso de una predictora que cambia
de dominio entre Desarrollo y OOT (hallazgo 6).

## 8. La revisión adversarial de este documento

Tope declarado: **tres pasadas**. Criterio de parada: la pasada 3 no tumba una premisa. Un hallazgo
contractual no se programa: se eleva.

| Pasada | Hallazgo | Qué cambió |
|---|---|---|
| 1 | (a) **alto**: con `ttd_includes_excluded=False`, `_ttd_mask` pone `ttd=False` en **todas** las fuera de modelo, también en las indeterminadas; el test 4 pedía lo imposible. (b) **alto**: `fuera_de_modelo` también reúne filas con desenlace conocido que la división por columna no mapeó; «Sin desenlace» las falseaba. (c) **alto**: `PDCalibrator.transform` filtra a las modelables y devolvería vacío; además la calibración publica ocho columnas, no seis. (d) **alto**: faltaba cómo llega el frame nuevo a `model` (que consume `selection`), qué pasa con artefactos inyectados y con `run(until=)`. (e) **alto**: el test de paridad con el bundle excluía justo las 370 filas problemáticas del caso de aceptación. (f) **medio**: publicar claves vacías y registrarlas como exports rompía la promesa bit a bit del informe en F1 | (a) §1.1 y test 4: con `False` no se puntúa ninguna, sin tocar D-DATA-5. (b) §1.2, §3 y test 4b: rótulo «Fuera del ajuste», composición en tres grupos y tasa observada sobre los que tienen target. (c) §1.3, §2 y test 2b: el paso aplica el estado ajustado con `_transform_with_state`, sin cambiar la API pública; las ocho columnas. (d) §2: `optional_requires` por paso, clave vacía sin alerta si falta la entrada, publicación sólo de los pasos que corren, y test 6b. (e) §5.2, D-TTD-5, §7 y tests 2, 3 y 10b: la paridad con la transformación cubre todas las filas, el desacuerdo con el bundle queda fijado y las categorías no vistas se declaran. (f) §2 y tests 5 y 11: una clave vacía no llega al informe, y el guardrail compara también el informe |
| 2 | (a) **alto**: `unseen_categories = {}` en la card de `binning` cambiaba el informe de F1, porque el builder vuelca toda la card al anexo. (b) **alto**: la premisa de §7 era falsa, porque el trail **ya** registra `categoria_no_vista` (`asignar_woe_neutral`). Además, cada `WoEBinner.transform` reemplaza `unknown_categories_`, así que la transformación nueva podía alterar el evento auditado o el estado publicado del `process`. (c) **medio**: la alerta prometía «el riesgo promedio» aunque `binning.cat_unknown` es configurable. (d) **medio**: las bandas de representatividad fijaban 0,10/0,25 aunque los cortes de estabilidad son configurables | (a) D-TTD-5 publica en una clave propia, `("binning", "unseen_categories")`, que no es campo de card ni tabla del informe; el test 11 compara el informe renderizado. (b) §7 y D-TTD-5 corregidos: lo que falta es decirlo fuera del trail, por muestra. El orden queda fijo —modelables, su registro, fuera del ajuste y restauración de `unknown_categories_`—, con el test 10c. (c) La alerta se redacta desde `cat_unknown` efectivo (test 10d). (d) §4 deriva banda y alerta de los cortes efectivos (test 10a) |
| 3 | (a) **alto**: `calibration` leía sólo la PD del modelo, así que con una falla en la tarjeta publicaría PD para filas sin puntaje; lo mismo la estabilidad si fallaba la calibración. (b) **medio**: con `cat_unknown` declarado, el evento `categoria_no_vista` dice `asignar_woe_neutral` aunque se aplicó otro valor. Es un registro falso previo, y la alerta nueva lo contradiría | (a) §2: `calibration` y `stability` dependen también de la etapa anterior, y cada paso publica sólo si todas sus entradas tienen filas con el mismo índice (test 6a). (b) D-TTD-5: el evento dice el tratamiento efectivo cuando `cat_unknown` está declarado y queda igual con el default (test 10d) |

**Tope alcanzado.** La pasada 1 tumbó seis premisas (población, calibración, dependencias, informe)
y la 2 dos más (la card y la auditoría existente). La 3 ya sólo encontró bordes: una propagación y
un registro previo. Es el criterio de parada declarado. La implementación abre con su propia
pasada sobre el código.

## 13. Simplicidad (SDD-31) — obligatoria

- **Entrada mínima:** no cambia. Quien declara un target con vacíos obtiene sus puntajes sin
  escribir nada.
- **Qué NO se configura:**
  - si se puntúa la TTD (siempre);
  - qué filas (las de la TTD ya declarada con `ttd_includes_excluded`);
  - con qué transformación (la de Holdout/OOT);
  - con §5.1 (a), la comparación de representatividad (siempre, con los umbrales de estabilidad
    ya configurados);
  - con §5.2 (a), el conteo de categorías no vistas (siempre).

  El `transform_out_of_model=True` que SDD-06 §6 anunciaba «en una versión futura» **no se
  crea**.
- **Presupuesto de perillas: CERO.** Todo lo nuevo es resultado.
- **Resumen por etapa:**
  - la tarjeta gana una línea condicional;
  - la calibración, una fila y una línea;
  - con §5.1 (a), la estabilidad gana una línea;
  - con §5.2 (a), «Tramos y WoE» gana una alerta por variable con categorías no vistas.
- **Las cinco cifras:** idénticas en toda corrida, porque las métricas se calculan sobre las
  mismas filas que hoy.
