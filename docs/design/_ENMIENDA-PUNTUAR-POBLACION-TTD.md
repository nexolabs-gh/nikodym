# Enmienda — la corrida puntúa a la población through-the-door que no entra al ajuste

| Campo | Valor |
|---|---|
| **Tipo** | Enmienda a [`09-scorecard.md`](09-scorecard.md) §6 («Poblaciones»: `fuera_de_modelo` «no recibe `score`»), a [`06-binning.md`](06-binning.md) §6 (el `transform_out_of_model` que anunciaba «en una versión futura»), a [`08-model.md`](08-model.md) y [`10-calibration.md`](10-calibration.md) (sus poblaciones) y, si Cami aprueba §5.1, a [`11-performance-stability.md`](11-performance-stability.md). Cumple lo que [`31-simplicidad-y-flujo-guiado.md`](31-simplicidad-y-flujo-guiado.md) §8 y [`_ENMIENDA-FLUJO-GUIADO-SCORECARD.md`](_ENMIENDA-FLUJO-GUIADO-SCORECARD.md) ya aprobaron («target con nulos: se puntúan, no se ajustan») y el motor nunca implementó |
| **Decisiones** | **D-TTD-1** (qué filas se puntúan y cómo), **D-TTD-2** (los artefactos), **D-TTD-3** (qué dicen las superficies) y **D-TTD-4** (representatividad, sujeta a §5.1) |
| **Módulos** | `nikodym.binning`, `nikodym.model`, `nikodym.scorecard`, `nikodym.calibration` (`step`), `nikodym.guided` (`summaries`, `scorecard`), `nikodym.report` (exports); con §5.1 (a), `nikodym.stability` |
| **Fase** | F1 |
| **Estado** | **Propuesta** el 2026-09-24 (S22). Sin código |
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
| **Sin desenlace (TTD)** | 6.225 (5.855 con el bundle, ver §7) | **554,9** | **561** | **15,0 %** |

Los préstamos que quedaron sin desenlace **no se parecen** a la muestra de ajuste: el modelo los
ve menos riesgosos. PSI del puntaje, con los deciles de Desarrollo: **0,175** entre Desarrollo y
los sin desenlace, frente a **0,004** entre Desarrollo y la TTD completa. La TTD completa contiene
al propio Desarrollo, que es el 61 % de ella, y eso diluye la diferencia (§4). Es justo el dato
para el que D-DATA-5 creó el rol `ttd`, porque sirve para medir representatividad.

## 1. D-TTD-1 — qué filas se puntúan y cómo

1. **Filas:** las que tienen `partition == "fuera_de_modelo"` **y** `ttd == True`. Se respeta la TTD
   ya declarada: con `data.partition.ttd_includes_excluded=True` (el default y lo que usa la
   puerta guiada) entran los indeterminados y los excluidos; con `False`, sólo los que la TTD
   declara. No se inventa una población nueva.
2. **Cómo:** con **la misma transformación que ya reciben Holdout y OOT**, paso por paso y con los
   objetos ya ajustados. `binning` aplica su `WoEBinner` ajustado, con los WoE asignados de D-FAL-1
   y los reagrupamientos de D-RAR-1. `model` aplica su estimador sobre las columnas WoE finales.
   `scorecard` aplica su escalador y `calibration` su calibrador. Ningún paso reajusta nada.
3. **Qué no hacen estas filas:** no entran a ningún ajuste —binning, selección, modelo, escala ni
   calibración— y no tocan ninguna métrica existente: AUC, KS, PSI, calibración, validación y
   desempeño se calculan exactamente sobre las mismas filas que hoy. No tienen desenlace, así que
   no hay métrica de discriminación que calcular sobre ellas.
4. **No es inferencia de rechazados.** No se les imputa un desenlace ni se reajusta el modelo con
   ellas; eso sigue siendo de la sub-fase de originación (SDD-02, «Decisiones abiertas»).
5. **Puntuarlas nunca detiene la corrida** (el patrón de D-SC-19). Si la transformación de estas
   filas falla en cualquier paso, el paso publica su artefacto vacío con la causa y la corrida
   sigue. El trail registra `ttd_no_puntuada` con la causa, el resumen de la etapa lo dice como
   **alerta** y los pasos siguientes publican vacío sin volver a fallar. Una corrida que hoy
   termina `done` sigue terminando `done`.

## 2. D-TTD-2 — los artefactos: cuatro claves aditivas, espejo de las modelables

| Clave nueva | Espejo de | Contenido |
|---|---|---|
| `("binning", "out_of_model_woe_frame")` | `("binning", "woe_frame")` | Mismas columnas: estructurales y `<feature>__woe` |
| `("model", "out_of_model_pd_frame")` | `("model", "raw_pd_frame")` | `partition`, `target`, `linear_predictor`, `pd_raw` |
| `("scorecard", "out_of_model_score")` | `("scorecard", "score")` | `<feature>__points` y `score`, con las columnas estructurales |
| `("calibration", "out_of_model_calibrated_pd_frame")` | `("calibration", "calibrated_pd_frame")` | Las seis columnas del frame calibrado |

- El índice es el de las filas en `("data", "frame")`, igual en las cuatro claves y **disjunto**
  del de las modelables. Se publican **siempre**, vacías y con su esquema cuando no hay filas.
  Consumir la clave no exige preguntar si existe.
- **Los artefactos existentes no cambian**: `woe_frame`, `raw_pd_frame`, `score` y
  `calibrated_pd_frame` conservan sus filas, su índice y sus invariantes. El chequeo de índice
  idéntico entre `score` y `raw_pd_frame` sigue intacto, y el par nuevo tiene el suyo.
- `selection` no cambia: `model` toma las columnas WoE finales del frame de `binning`.
- **Nombre:** `out_of_model_*` porque son las filas de la partición `fuera_de_modelo`, filtradas
  por la TTD declarada. No se llama `ttd_*`: la TTD completa también incluye Desarrollo, Holdout y
  OOT, que siguen en sus artefactos de siempre.
- **Exports:** `scorecard.out_of_model_score` y `calibration.out_of_model_calibrated_pd_frame` se
  registran como tablas **por observación**, junto a `scorecard.score` y
  `calibration.calibrated_pd_frame`. Así salen completas como exports de datos, no dentro del
  documento. Títulos: «Puntaje de la población sin desenlace (TTD)» y «PD calibrada de la
  población sin desenlace (TTD)». Los dos frames intermedios no se exportan.
- **Trail:** una decisión en `scorecard`, `regla="puntuar_ttd_fuera_de_modelo"`,
  `valor={filas, indeterminadas, excluidas}`, `accion="puntuar_sin_ajustar"`. Las decisiones que
  hoy dicen `no_puntuar`/`no_calibrar` sobre `fuera_de_modelo` (`model`, `scorecard`,
  `calibration`) nunca se disparan, porque `binning` ya filtra antes; no cambian.

## 3. D-TTD-3 — qué dicen las superficies

| Superficie | Qué dice |
|---|---|
| **Resumen de datos** | La línea de `d2839d8` pasa de «no entran al ajuste ni reciben puntaje» a «no entran al ajuste; la tarjeta los puntúa aparte, como parte de la población total (TTD)». Lo dice en futuro porque la etapa de datos no sabe si la corrida llegará a la tarjeta (`run(until=…)`) |
| **Inferencia de la puerta** | El motivo «se puntúa y no entra al ajuste» pasa a ser verdad; no cambia. Sí se precisa su docstring |
| **Resumen de la tarjeta** | Una línea condicional, p. ej. «Población sin desenlace (TTD): 6.225 operaciones puntuadas, puntaje medio 555 (Desarrollo 539)» (cifras ilustrativas: las del §0 salen del bundle, sobre 5.855 filas) |
| **Resumen de calibración** | La tabla «PD por muestra» gana la fila «Sin desenlace (TTD)», con PD media cruda y calibrada y la tasa observada vacía (—). Suma una línea, p. ej. «PD calibrada media de toda la población que pidió crédito (TTD, 49.999 operaciones): 23,1 %» (ilustrativa: medida sobre 49.629 filas, §7) |
| **Pantalla, informe (página ejecutiva) y `sc.results`** | Leen la misma fuente que `summary()`: las líneas y la fila llegan solas |
| **Informe y Excel** | Los dos exports por observación de §2. El Excel por etapa los incluye si el informe los publica para el dominio; se mide al implementar |
| **SDD-09 §6, SDD-06 §6, SDD-08, SDD-10, SDD-31 §8** | Se anotan con un puntero a esta enmienda cuando se implemente |

Todo lo que se lee sale de los mapas de rótulos existentes. El rótulo de la partición
`fuera_de_modelo` —«Sin desenlace (TTD)»— es el mismo que pide el hallazgo 2 de la enmienda de
copy de esta sesión, y los dos cambios comparten la entrada en `report/prose.py`.

## 4. D-TTD-4 — representatividad: los sin desenlace frente a Desarrollo (sujeta a §5.1)

Si Cami la aprueba, `stability` publica un PSI del puntaje entre Desarrollo y los sin desenlace:

- **Clave aditiva** `("stability", "out_of_model_psi")`, con el mismo esquema por tramo que
  `psi_table` y los mismos tramos del puntaje que usa la comparación Desarrollo vs. OOT. El motor
  PSI es el de siempre (`_psi_from_counts`); no se escribe otro.
- **No es una comparación configurable**: no se añade `dev_vs_ttd` a `stability.comparisons`, y por
  eso el `config_hash` de ningún preset se mueve. Se calcula cuando hay filas sin desenlace
  puntuadas y, si no las hay, la clave queda vacía.
- **Se compara contra los sin desenlace, no contra la TTD completa.** La TTD contiene al propio
  Desarrollo (61 % en el SBA) y el PSI contra ella sale casi cero aunque los sin desenlace difieran
  mucho: 0,004 frente a 0,175, medido.
- **Rótulo propio.** Los umbrales son los de estabilidad ya configurados, pero la lectura es de
  representatividad, no de deriva: «se parecen» (< 0,10), «difieren moderadamente» (0,10–0,25) y
  «difieren» (≥ 0,25). No se dice «Redesarrollar», porque no hay nada que redesarrollar.
- **Fuera del veredicto.** No entra a `validation` ni al estado técnico. Una línea en el resumen de
  estabilidad: «Sin desenlace frente a Desarrollo: PSI 0,175 — difieren moderadamente: el modelo
  los ve con menor riesgo (PD calibrada media 15,0 % frente a 23,8 %)». Sólo «difieren» sube como
  alerta a «Qué revisar».

## 5. Lo que Cami decide

| # | Decisión | Opciones | Recomendación |
|---|---|---|---|
| 5.1 | ¿Entra la representatividad (§4) en esta enmienda? | (a) **sí**: puntuar y además medir si los sin desenlace se parecen a la muestra de ajuste; (b) no: sólo puntuar, y la representatividad va en otra enmienda | **(a)**: puntuar sin comparar deja una columna sin lectura. D-DATA-5 creó el rol `ttd` para medir representatividad, y el SBA muestra que la diferencia existe (PSI 0,175). Cuesta una clave aditiva y una línea |

Lo demás no se pregunta porque tiene una respuesta de principio: las filas son las de la TTD ya
declarada, el tratamiento es el de Holdout/OOT y nada es configurable (§13).

## 6. Estrategia de tests

| # | Test | Nace rojo porque |
|---|---|---|
| 1 | **Gate de aceptación**: el SBA termina `done` con las cuatro claves de §2, 6.225 filas cada una, y el índice de esas filas es disjunto del de las modelables | Las claves no existen |
| 2 | **Paridad con la transformación de Holdout**: en un fixture, las filas puntuadas como sin desenlace reciben el mismo WoE, predictor lineal, puntaje y PD calibrada que recibirían con los mismos valores en Holdout. Se compara contra `binner.transform`, el estimador, el escalador y el calibrador ajustados, aplicados a mano | La regla no existe |
| 3 | **Paridad con el bundle**: `FittedScorecardBundle.apply` sobre esas filas da el mismo `score` y la misma `pd_calibrated` que los artefactos nuevos, **en las filas que el bundle puede puntuar** (§7) | La regla no existe |
| 4 | Con `ttd_includes_excluded=False` no se puntúan los excluidos, y sí los indeterminados | La regla no existe |
| 5 | Sin filas sin desenlace: las cuatro claves se publican vacías con su esquema y no hay decisión ni línea de resumen | Las claves no existen |
| 6 | **Nunca detiene**: una falla inyectada en la transformación de esas filas deja la corrida `done`, las claves vacías, `ttd_no_puntuada` en el trail y la alerta en el resumen | La regla no existe |
| 7 | Una decisión `puntuar_ttd_fuera_de_modelo` con sus conteos | No se emite |
| 8 | El resumen de datos, el de la tarjeta y la tabla de calibración dicen lo de §3, sin identificadores del motor; la línea de datos ya no dice «ni reciben puntaje» | No lo dicen |
| 9 | Los dos exports por observación salen con su título | No están registrados |
| 10 | Con §5.1 (a): el PSI de representatividad del SBA, su rótulo y su línea; la clave vacía sin filas; `validation` no la lee | No existe |
| 11 | **Bit a bit** sobre el preset F1, que no tiene filas fuera de modelo: las únicas diferencias son las claves nuevas vacías; el `config_hash` `1063d6cf…` y las cinco cifras quedan intactos | — (guardrail) |

**Controles negativos:** no filtrar por `ttd` (4); puntuar también las modelables en la clave nueva
(1); reajustar el calibrador con las filas nuevas (2); dejar que la falla de §1.5 levante (6); no
registrar el export (9); comparar contra la TTD completa en vez de los sin desenlace (10).

## 7. Defecto previo medido: una categoría que no se vio en Desarrollo (registrado aparte, no se toca aquí)

Al medir el §0 apareció un defecto anterior a esta enmienda, que también afecta a Holdout y OOT:

- En el SBA, `anio_fiscal` entra como predictora (es el hallazgo 6 de la enmienda de copy). El año
  fiscal 2009 **no existe en Desarrollo** por construcción: la frontera OOT es 2008-01-01 y el
  año fiscal 2009 empieza el 1-oct-2008.
- **El motor** transforma esa categoría no vista con WoE ≈ 0 (`2,2e-16`), es decir, con el riesgo
  promedio. Le da 74 puntos a las **2.620** operaciones OOT de 2009, **sin declararlo en ningún
  lado**. Es el mismo cero que D-FAL-1 rechazó como «no es una estimación».
- **El bundle** no las puntúa: `categoria_no_observada_en_fit` en 2.620 filas OOT (más una por
  `estado_del_proyecto`) y en 370 de las 6.225 sin desenlace. **La corrida y el bundle discrepan
  hoy** en esas filas. El test que ancla la paridad corre sobre datos sin categorías nuevas.

Esta enmienda no lo corrige, porque corregirlo cambiaría números de corridas que hoy terminan.
Las filas sin desenlace reciben lo mismo que OOT, que es la promesa de §1.2, y el test 3 compara
sólo las filas que el bundle puntúa. Queda **elevado a Cami** como enmienda propia: una regla
declarada para categorías no vistas, que el motor y el bundle apliquen igual.

## 8. La revisión adversarial de este documento

Tope declarado: **tres pasadas**. Criterio de parada: la pasada 3 no tumba una premisa. Un hallazgo
contractual no se programa: se eleva.

| Pasada | Hallazgo | Qué cambió |
|---|---|---|
| 1 | — | — |

## 13. Simplicidad (SDD-31) — obligatoria

- **Entrada mínima:** no cambia. Quien declara un target con vacíos obtiene sus puntajes sin
  escribir nada.
- **Qué NO se configura:**
  - si se puntúa la TTD (siempre);
  - qué filas (las de la TTD ya declarada con `ttd_includes_excluded`);
  - con qué transformación (la de Holdout/OOT);
  - con §5.1 (a), la comparación de representatividad (siempre, con los umbrales de estabilidad
    ya configurados).

  El `transform_out_of_model=True` que SDD-06 §6 anunciaba «en una versión futura» **no se
  crea**.
- **Presupuesto de perillas: CERO.** Todo lo nuevo es resultado.
- **Resumen por etapa:** la tarjeta gana una línea condicional; la calibración, una fila y una
  línea; con §5.1 (a), la estabilidad gana una línea.
- **Las cinco cifras:** idénticas en toda corrida, porque las métricas se calculan sobre las
  mismas filas que hoy.
