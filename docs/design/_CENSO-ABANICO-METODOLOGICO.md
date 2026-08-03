# Censo del abanico metodológico — insumo medido para el SDD de D-JOB-4/5

> **Estado: CENSO, no diseño.** Es el material sobre el que se escribe el SDD de D-JOB-4/5, no el
> SDD. Ninguna decisión de aquí está tomada: lo que hay son hechos medidos contra el código y las
> preguntas que el diseño tendrá que contestar.
>
> **Base:** `main` = `54fea3c`. **Fecha:** 2026-08-02 (noche). **Método:** tres barridos
> independientes y en paralelo —cadena del scorecard, provisiones, y lo temporal/validación— cada
> uno midiendo contra el código, no contra la documentación.
>
> **Por qué existe.** D-JOB-4/5 quiere exponer los puntos de elección metodológica **en idioma de
> negocio**, y D-JOB-5 es explícito: *una opción que no se puede usar se declara con su motivo, no
> se oculta*. Escribir eso sin saber qué exige cada opción de los datos habría sido especulación.
> Ahora se sabe.

## 0. El resultado en una frase

**El mecanismo que D-JOB-5 necesita ya existe, se llama `requisitos_incumplidos`, está probado en
producción y llega hasta la pantalla — pero cubre cuatro secciones de catorce, y las exigencias del
abanico se reparten en CINCO clases de las que ese mecanismo hoy expresa sólo una.**

El SDD no tiene que inventar una superficie: tiene que decidir **hasta dónde ampliar la que hay**, y
en qué orden.

## 1. Las cinco clases de exigencia, que son el eje del diseño

Toda opción del abanico exige algo. Lo que decide el diseño no es *qué* exige, sino **con qué se
puede comprobar** — porque `check_dataset` **no lee los datos** (D-PRE-1), y esa restricción es
contrato.

| # | Clase | Se comprueba con | ¿Hay mecanismo hoy? |
|---|---|---|---|
| **A** | **Coherencia interna del config** | el propio `model_validator` de la sección | ✅ Sí, y en su mayoría **ya implementado**: revienta al construir el config |
| **B** | **Existencia de una columna** | los nombres de columna del dataset | ⚠️ El mecanismo existe (`column_role` + `check_dataset`), pero **casi ningún campo del abanico lo declara** |
| **C** | **Propiedad medible de una columna** | `PerfilColumna` (`n_unicos`, `es_numerica`, `valores_frecuentes`) | ⚠️ Existe (`requisitos_incumplidos_por_perfil`), con **una sola** implementación |
| **D** | **Contexto: otra sección activa, o un extra instalado** | el config raíz y `importlib.util.find_spec` | 🔴 **NO EXISTE.** Es la clase que D-INV-8 dejó fuera como «C2», y es donde cae medio abanico |
| **E** | **Valores o contenido de los datos** | leyendo los datos | 🔴 **Fuera de contrato** por D-PRE-1, y así debe quedarse |

🔴 **El hallazgo que más condiciona el SDD: la clase D no tiene mecanismo, y es enorme.**
`forward.input.term_structure_sources` exige que `survival` o `markov` estén activas;
`validation.discrimination.consume_performance` exige `performance`;
`survival.input.pd_source='calibration'` exige la sección de calibración;
`stress.output.metrics` con `ecl` exige un motor económico conectado;
`provisioning_ifrs9.pd.term_structure_source` exige la sección que produce la curva. Ninguna es una
columna, ninguna es un valor: son **el config mirándose a sí mismo**.

`requisitos_incumplidos(columnas)` recibe columnas y nada más, a propósito — D-INV-1 evita darle el
config raíz a cada dominio para no acoplarlos. **El SDD tiene que resolver esa tensión**, y el
precedente de cómo hacerlo sin romper D-INV-1 ya está en el repo: cuando hizo falta una segunda
clase de exigencia, no se amplió la firma, **se añadió un método hermano**
(`requisitos_incumplidos_por_perfil`, `core/dataset_check.py:63-69`). La forma análoga sería un
tercer hermano que reciba *el contexto* —secciones activas y extras instalados— y nunca los datos.

## 2. El precedente que hay que imitar, con su cobertura real

`requisitos_incumplidos` (enmienda INVARIANTES-PREVIAS, D-INV-1…9) hace **exactamente** lo que
D-JOB-5 pide: una sección declara qué exige, y se comprueba antes de correr. Ya viaja hasta la
interfaz —aviso por sección, salto al campo exacto, botón que cambia de aspecto **sin bloquear**— y
el front **no discrimina por tipo**: consume `path` y `message`. Ampliarlo es aditivo de verdad.

**Quién lo implementa hoy — cuatro de catorce secciones:**

| sección | qué declara |
|---|---|
| `StabilityConfig` | eje temporal sin columna candidata, o con varias (ambigüedad); comparaciones duplicadas |
| `PerformanceConfig` | particiones duplicadas |
| `ValidationConfig` | familias vacías |
| `TemporalSplitConfig` | `oot_from` vacío o no parseable |

Más `BinningConfig.requisitos_incumplidos_por_perfil`, única implementación del hermano por perfil.

⚠️ **`survival`, `markov`, `forward` y `stress` están EXENTAS con una razón escrita**: *«fuera del
alcance F1 del preflight (D-PRE-4)»* (`tests/unit/test_invariantes_previas.py:200-207`). Levantar
esa exención es **decisión de producto, no un olvido técnico**, y el SDD tiene que tomarla
explícitamente. Técnicamente es barato: el recorrido ya camina las secciones anidadas, y el gate de
cobertura se pone rojo solo cuando se saca la fila.

## 3. 🔴 El bloqueador de fondo: los `column_role` que faltan

`grep -c column_role` por sección: `data`=10, `stability`=5, `performance`=4, y **`survival`=0,
`markov`=0, `forward`=0, `stress`=0, `validation`=0, y CERO en todo `provisioning/`**.

Sin `column_role`, ni `check_dataset` ni un requisito nuevo pueden decir «tu archivo no trae la
columna de duración que exige Kaplan-Meier» — que es **literalmente el ejemplo de D-JOB-5**.

Consecuencia medida y grave por sí sola, al margen del abanico: **un config de provisiones que
apunta a columnas inexistentes sale hoy `compatible=True`.** Ninguna de las ~35 columnas que las
cuatro secciones de provisiones nombran —exposición, LGD, EAD, límite, EIR, mora, categoría CMF—
produce un solo aviso. Es el cambio de **mayor palanca y más barato** del censo: aditivo, campo por
campo, sin tocar ningún motor.

⚠️ Y con una trampa ya pagada: declarar el rol equivocado da **falsos positivos** sobre el caso
correcto. Es lo que dejó fuera a `stratify_by` (D-INV-8 A3), que apunta a una columna **derivada**.

## 4. Lo que el abanico ofrecería y no se puede usar — los casos D-JOB-5 de manual

Son opciones que hoy el formulario pinta como elegibles y que el motor rechaza. Un abanico que lea
sus opciones del schema las ofrecería igual.

| opción | qué pasa | cuándo se descubre | clase |
|---|---|---|---|
| `binning.solver = "cp"` | el motor aborta en la primera línea del ajuste | al correr | **A** — declarable con certeza total, sin mirar un dato |
| `stability.csi_source = "woe_bins"` | no implementada; la rechaza el validador | al construir el config | **A**, ya cubierto |
| `validation.calibration.hl_grouping = "fixed_bands"` | ídem | al construir el config | **A**, ya cubierto |
| 🔴 `markov.dynamics.projection_mode = "period_matrices"` | **el config la ACEPTA** y revienta al proyectar | al correr | **A** — la más fácil del censo, y hoy ninguna superficie la para |
| `stress.output.include_baseline_rows = False` | «hoy sólo se admite `True`» está en la *descripción del campo*, no en un validador | al correr | **A** |
| `provisioning_cmf.guarantees.require_recoverable_for_default` | ⛔ **no se lee nunca**: cero usos en el motor | jamás | promete una elección que no existe |
| `provisioning_cmf.matrices.fail_on_unmapped_contingent_type` | **ambas ramas levantan**; sólo cambia la clase de excepción | al correr | el copy promete una elección que no cambia el desenlace |

**Y tres elecciones sin consecuencia desde el formulario**, que merecen decirse en vez de dejarse
elegir: `model.engine='glm_binomial'` (su única ventaja es `sample_weight`, que el pipeline nunca
pasa), `model.optimizer` cuando el motor es GLM (se ignora en silencio), y
`calibration.require_both_classes_for_supervised` (obligado a `True` cuando importa, nunca leído
cuando no).

## 5. Coacciones silenciosas: lo que el motor cambia sin decirlo

Es la otra mitad de D-JOB-5. No es que la opción no se pueda usar: es que **se usa distinto de lo
que el usuario cree**.

1. **OptBinning reduce cualquier monotonía a `"ascending"` en una variable categórica.** Declarable
   antes con el perfil (`es_numerica`).
2. **`calibration.anchor_source='development_observed'` DESCARTA el `target_pd` que el usuario
   escribió.** Declarable con sólo el config. *(Es exactamente el caso que la documentación describió
   mal durante doce días.)*
3. **`stability.temporal_freq` se ignora** si la columna temporal no es datetime.
4. **`ead.method='ccf'` no valida en el config que exista alguna fuente de CCF**; sólo prohíbe
   declarar las dos.
5. 🔴 **El default de fábrica de IFRS 9 es internamente incoherente y nadie lo detecta**:
   `term_structure_source='survival'` + `pit_mode='consume_pit'` + `scenarios.source='forward'`
   **construye sin error** y falla en la primera corrida por dos motivos distintos. Es la
   combinación que un abanico debería poder declarar imposible antes de correr.

## 6. La clase que ninguna herramienta cubre, y que el SDD debe nombrar

Además de las cinco clases de §1, el censo de provisiones aisló una **sexta situación** que no es
ninguna de ellas: *una propiedad del contenido de un artefacto que produce otra sección*. No es una
columna del dataset (la vería `check_dataset`), no es una sección activa (la vería `check_pipeline`
por el DAG), y no es un valor del archivo del usuario.

Es donde vive `pit_mode`: `consume_pit` exige que la curva traiga `pd_basis='pit'` en todas sus
filas, y **`survival` y `markov` no emiten esa columna** — sólo `forward` la produce. Por eso el
default de fábrica es incoherente sin que nadie lo vea.

⚠️ **La información para cerrarlo ya existe y no está conectada**: `survival/results.py:42`,
`markov/step.py:62-72` y `forward/satellite.py:77-86` declaran en **tuplas constantes** qué columnas
publica cada uno. Falta que el consumidor declare qué columnas exige, para poder cruzarlas.

## 7. Lo que el abanico no puede pedir aunque quiera

**~19 columnas de nombre fijo que el config no parametriza**, así que la interfaz no puede pedirlas
ni el preflight comprobarlas: `recovery_cost`, `recovery_time_years`, `contractual_rate`, `ead`,
`pd_pit_origination`, `pd_calibrated`, `aval_coverage_pct`, `aval_rating_scale`,
`aval_rating_category`, `contingent_subtype`, y las nueve de garantía financiera.

Son **constantes de módulo**, así que «qué exige esta opción de tus datos» se puede *computar* en
pre-run. Lo que falta es dónde publicarlo.

## 8. La cuarta clase, trivial y hoy invisible: los extras de pip

`survival.method` ramifica en **dos** extras distintos (`statsmodels` para `discrete_hazard`,
`lifelines` para los otros tres); `forward.macro.kind='auto_arima'` exige `pmdarima`;
`data.load.backend='polars'` y `file_format='excel'` exigen los suyos. Todo se descubre **corriendo**,
con `MissingDependencyError`.

Es **trivialmente verificable antes** con `importlib.util.find_spec`, y **no viola D-PRE-1**: no lee
un solo dato. El precedente de que esto importa ya está en el repo — `[ui]` incluye `lifelines`
*justamente* porque el método es editable desde el formulario, y hay un gate que lo hace cumplir.
Lo que falta es decírselo al usuario **en el selector**, no en el traceback.

🔴 **Y un defecto concreto que el abanico publicaría mal:** el gate de dependencias exige `lifelines`
para todo lo que no sea `discrete_hazard` — **incluido `kaplan_meier`, cuyo estimador declara en su
propio docstring que no usa lifelines en la ruta core**. El gate es más estricto que el motor.

## 9. La plantilla a imitar, ya completa

**`data.partition.strategy` es el modelo formal del abanico, y está terminado.** Cuatro ramas de
unión discriminada, tres con `column_role` declarado, una con `requisitos_incumplidos` propio, y la
cuarta (`columna`) aprovechando `valores_frecuentes` para **ofrecer** valores en vez de preguntar a
ciegas — con la advertencia explícita de que ofrecerlos *no autoriza a contestar por el usuario*.

Es la única rama del censo donde las cuatro exigencias —columna, valores, formato y coherencia
interna— están declaradas y comprobadas antes de correr. Y su hueco conocido (`stratify_by` sin
rol) es el recordatorio de que **la comprobación equivocada da falsos positivos sobre el caso
correcto**.

## 10. Las preguntas que el SDD tiene que contestar

1. **¿Se amplía el alcance del preflight más allá de F1?** `survival`, `markov`, `forward` y `stress`
   están exentas con su razón escrita (D-PRE-4). El abanico no puede declarar sus exigencias sin
   levantar esa exención. **Es decisión de producto.**
2. **¿Cómo se expresa la clase D sin romper D-INV-1?** El precedente dice: método hermano, no firma
   ampliada. Hay que fijarlo antes de programar.
3. **¿El abanico deriva sus opciones del schema, o las declara a mano?** Del schema sale gratis y
   completo, pero entonces ofrecerá `binning.solver='cp'` y `projection_mode='period_matrices'`; a
   mano no puede desincronizarse en silencio pero exige un gate bidireccional. *(El precedente de
   D-COL-6 eligió declararlas a mano con gate bidireccional contra las ramas del motor.)*
4. **¿Qué se hace con las opciones que no cambian nada?** Ocultarlas contradice D-JOB-5; ofrecerlas
   es prometer una elección falsa. Probablemente hay una tercera categoría —«declarada, sin efecto
   hoy»— que el catálogo debe poder expresar.
5. **¿Se arreglan los cuatro defectos que el censo destapó, y en qué orden?** Son independientes del
   abanico y valen por sí solos: los `column_role` de provisiones, `period_matrices` que el config
   acepta, el `require_recoverable_for_default` muerto, y el gate de `lifelines` sobre `kaplan_meier`.

## 11. Deuda menor, medida y anotada

- **Cuatro `rounding` idénticos con defaults distintos**: tres arrancan en `none` y
  `provisioning_internal` en `currency_2dp`. Misma semántica, un default divergente.
- **`requires` estático en CMF** rompe la simetría con las otras tres secciones de provisiones, que
  lo construyen dinámico desde el config: su dependencia condicional sólo aparece como error en
  ejecución.
- **`fail_on_falta_dato` significa tres cosas distintas** en las tres secciones que lo declaran.
- **`provisioning_cmf` no tiene `card.falta_dato`**: todo su «faltante» es excepción dura. Es la
  sección que peor encaja en «declarar con su motivo».
- **`survival.time_grid.time_unit` y `markov.dynamics.time_unit` traen `"period"` de fábrica**, que
  **no es una unidad**. IFRS 9 presume años, y la ECL se mueve 40-50 % en silencio. Es comparable
  contra `known_time_units()` sin tocar los datos: cabe tal cual en el protocolo actual.
