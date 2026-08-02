# Enmienda SDD — lo que ya traes en tu archivo se declara, no se vuelve a inventar

> **Estado: APROBADA por Cami (2026-08-02) — D-COL-2/D-COL-3/D-COL-4 IMPLEMENTADAS.** El camino lo
> fijó él tras leer la medición: **el motor aprende a leer**. La opción que el plan traía escrita
> —«acotar las decisiones por trabajo»— se midió y **no es implementable**; el porqué está en §1.3 y
> es la mitad valiosa de este documento.
>
> **Base:** `main` = `3349245`. **Autor / Fecha:** DanIA / 2026-08-02.
>
> ## Lo que la implementación de D-COL-2/3/4 corrigió de este documento
>
> 1. ✅ **Hash-neutralidad re-verificada con la rama de verdad**: `ec10eb43…`, `857b06ee…`,
>    `013e69dc…`, byte a byte. Control negativo **ejecutado**: un campo nuevo en `PartitionConfig`
>    pone rojos los tres, y borrar la rama pone rojo el ancla estructural del propio gate.
> 2. ⚠️ **Los gates que se mueven son TRES, no los cinco que anunciaba §1.5.** `test_column_roles`
>    sale **verde** porque la implementación sí declara `column_role: "input"` en `partition_col`
>    —la sonda de la sesión anterior no lo declaraba, y de ahí sus 2 rojos—. Los que se mueven son
>    `test_ui_schema_fixture` (2) y `test_effective_defaults` (1, `1034 → 1039`).
> 3. 🔴 **La rama destapa un defecto que ella misma habría creado, y que ningún test pedía:**
>    `binning/step.py` excluía de las variables candidatas `date_col` y `cohort_col`, pero no
>    `partition_col`. Con `feature_columns="*"` la columna que marca la muestra se habría ofrecido
>    como **predictor**. Corregido y con control negativo ejecutado; de paso la función pasó a
>    llamarse `_data_declared_structural_columns`, porque el nombre anterior nombraba dos de sus
>    cuatro fuentes.
> 4. **Dos decisiones de implementación que el documento no fijaba**, ambas escritas en el código:
>    un valor **declarado** que no aparece entre las filas utilizables es error nombrado que
>    publica los observados (es lo que caza el error de tipeo, y no puede decir «no existe en la
>    columna» porque sería falso para un valor presente sólo en filas excluidas); y `partition_col`
>    no puede llamarse `partition` ni `ttd`, con mensaje propio — con esta estrategia, que la
>    columna del usuario se llame así deja de ser un caso raro.

| Campo | Valor |
|---|---|
| **Problema** | «Validar un modelo existente» exige definir qué es un cliente malo y cómo se separa la muestra, aunque el usuario traiga su etiqueta y su partición **dentro** del archivo del modelo. Contesta dos veces lo mismo, y la segunda inventando criterio |
| **Enmienda a** | `_ENMIENDA-DECISIONES-OBLIGATORIAS.md` D-OBL-6 (qué decisiones ve un trabajo) y D-OBL-7 (cómo se derivan); SDD-02 `data` gana una rama pública de partición |
| **No toca** | El `config_hash` de ningún config existente (medido, §1.5), el catálogo de secciones, la puerta de artefactos, ni el criterio de qué secciones muestra un trabajo (D-JOB-1) |
| **Release** | Capacidad pública nueva en `data` ⇒ **minor**, aditiva. Esta enmienda no autoriza bump, tag ni publicación |

## 1. Evidencia medida

Todo lo de esta sección se ejecutó contra `29b46d2`/`3349245`. Lo que se dedujo leyendo se dice.

### 1.1 El reparto de hoy, y su alcance real

`_DECISIONES_POR_SECCION` (`ui/jobs.py:396`) declara **cuatro** decisiones en dos secciones, y
`decisiones_de` (`:438-451`) las reparte **por pertenencia de sección**, sin ninguna condición. Los
10 trabajos declaran `data`, así que los 10 heredan `data.target.bad_rule` y
`data.partition.strategy`; los dos con `survival` heredan además `duration_col` y `event_col`.

Quién consume el **producto** de esas decisiones —`data.labels` y `data.splits`—: sólo `binning`
(`binning/step.py:79-84`), `selection` (`selection/step.py:91-99`), `model` (`model/step.py:90-97`)
y, fuera del formulario, `eda`. `performance` y `stability` **no los requieren**
(`performance/step.py:62-65`, `stability/step.py:68-72`), y las provisiones requieren sólo
`("data","frame")`.

De **22 pares (trabajo, decisión)** publicados hoy, ~12 no tienen lector aguas abajo. No 2, que es
lo que el plan heredado suponía.

### 1.2 🔴 Pero «sin lector» NO es «inerte», y ahí se cae el plan

Tres mediciones que lo impiden:

1. **El frame no es neutral.** `DataStep` publica como `("data","frame")` el frame **post-partición**
   (`data/step.py:159`), que lleva `partition`, `ttd`, el target derivado y `label_status`
   (`data/partition.py:139-143`, `data/target.py:155-156`). Los 10 trabajos reciben esas columnas.
2. **`survival` filtra por ellas.** Sólo elimina `partition` del frame de ajuste si
   `input.pd_source == "none"` (`survival/step.py:158-163`); en el resto, `_fit_mask`
   (`survival/discrete_hazard.py:471-480`, `cox_aft.py:542-549`) **ajusta sólo sobre `desarrollo`**.
   La condición de relevancia no es «la sección survival está», sino
   `pd_source != "none"` **y** `method != "kaplan_meier"`.
3. **Poder de veto en los 7.** `_validate_min_bads` (`data/partition.py:526-537`) detiene la corrida
   si una partición evaluable no alcanza el piso de malos (`min_bads_per_partition`, default **30**)
   o se queda sin buenos (`:513-524`); los conteos salen de `lf.target_col` (`:146-147`), o sea que
   **la definición de malo alimenta el umbral**. Y `_validate_non_empty_partitions` (`:469-499`)
   exige un conjunto de particiones **que depende de la estrategia**.

⇒ **Ninguna de las cuatro decisiones se puede omitir sin consecuencia**, ni siquiera donde nadie lee
su producto.

### 1.3 🔴 Y omitirla es, además, imposible o deshonesto

- **3 de las 4 no admiten ningún relleno.** `bad_rule` con `{"all_of":[],"any_of":[]}` ⇒
  `ValidationError: una Rule debe declarar al menos un predicado` (`data/config.py:387-389`);
  `duration_col`/`event_col` vacíos ⇒ `SurvivalConfigError` (`survival/config.py:359`). Si un
  trabajo las exime, el config **no reconstruye** y la corrida ni arranca: medido,
  `NikodymConfig.model_validate` da `data.target → Field required`.
- **La única que admite relleno es la peligrosa.** `{"type":"random"}` materializa en silencio
  `0.70/0.15/0.15` sin estratificar, y el propio config lo declara **pseudo-OOT**
  (`data/config.py:650, 687-689`). Sortear el fuera-de-tiempo en vez de cortarlo por fecha **infla
  la métrica OOT** en el trabajo cuyo entregable *es* la métrica OOT.
- 🔴 **Y publicaría una frase falsa en el informe.** `report/prose.py:415-419` emite **sin ninguna
  condición** «La población se particionó de forma aleatoria: Desarrollo 70%, Holdout 15%, OOT 15%»,
  mientras la frase del target de `:398-411` **sí** está gateada por que exista cadena de
  construcción. Rellenar no es sólo esconder: es afirmar en un documento que lee un regulador algo
  que el usuario nunca eligió.
- **Y `data_hash` se contamina.** Se calcula sobre el frame post-partición (`data/step.py:86`), así
  que con `random` depende de `repro.seed`: dos usuarios con la misma cartera y distinto relleno
  quedan con identidades distintas. `config_hash` excluye `data.load.source` **a propósito** porque
  «la identidad depende del CONTENIDO del dato, vía `data_hash`» (`core/config/hashing.py:107`); el
  relleno convertiría esa identidad de contenido en identidad de (contenido, semilla).

### 1.4 La variante «una sección `data` que carga pero no etiqueta» también se midió, y no sirve

Era la salida natural y **entrega menos que hoy**:

- La card queda vacía: `DataCardSection` (`data/card.py:23-33`) tiene 11 campos **todos requeridos**
  y 7 dependen del etiquetado o la partición. Las tres tablas de población del informe
  (`report/builder.py:626-654`) salen **100 %** de esos mapas.
- El `data_hash` **cambia**: medido, el del frame crudo difiere del actual, y
  `data_hash(post − {partition,ttd,target,label_status}) == data_hash(crudo)` exacto. Dos corridas
  del mismo archivo por variantes distintas quedarían con identidades incomparables **en silencio**.
- Cuesta cinco capas (`schema.py:534-537` coacciona a **una** clase por sección) y **no hay un solo
  precedente**: los 24 `@register` del repo son `"standard"`.

⚠️ Y rompería `survival` **sin ruido**: `_fit_mask` devuelve `np.ones(...)` cuando falta la columna,
o sea que ajustaría sobre la población entera en vez de sobre desarrollo. Cambia el número y no
enrojece nada. *(Ese fallback es un defecto propio y se corrige aparte en esta misma sesión.)*

### 1.5 🔴 Lo que sí es barato, medido: una rama nueva NO mueve ningún hash

**Medido añadiendo la rama de verdad a `PartitionStrategy`**, no simulando sobre el payload: se
registró una cuarta rama `columna` en `data/config.py`, se recalcularon los tres `config_hash` y se
revirtió.

| preset | antes | con la rama registrada |
|---|---|---|
| `f1-estandar-consumo` | `ec10eb43…` | **`ec10eb43…`** |
| `f3-provisiones-consumo` | `857b06ee…` | **`857b06ee…`** |
| `f4-ifrs9-retail` | `013e69dc…` | **`013e69dc…`** |

Idénticos byte a byte. `type: "standard"` ya viaja dentro del payload hasheado, así que una rama
hermana no mueve nada; añadir un **campo** a una clase existente, en cambio, los mueve los tres.

`type: "standard"` ya viaja dentro del payload hasheado, así que una rama hermana no mueve nada. Y
`PartitionStrategy` **ya es** una unión de tres ramas (`data/config.py:758-761`) que el formulario
**ya sabe renderizar** (`form-engine.ts:457,508-525`; `FieldRenderer.tsx:244,541-561`), y que
`check_dataset` **ya recorre** (`core/dataset_check.py:197-231`). Ese es el filo que decide todo el
diseño: el camino trillado de este repo es *otra rama*, no *otra sección*.

⚠️ **Lo que sí se mueve, medido con la misma sonda: cinco gates, ninguno de identidad.** La rama
nueva pone rojos `test_ui_schema_fixture.py` (2), `test_column_roles.py` (2) y
`test_effective_defaults.py` (1). Es el coste real y va en el mismo commit: fixture de schema
regenerado, bundle reconstruido y golden de descriptores recalculado —**investigado antes de
moverlo**, nunca ajustado para que pase—.

✅ Y un hallazgo que vale la pena: `test_column_roles` se puso rojo **porque la sonda no declaró
`column_role` en `partition_col`**. O sea que el gate vigente ya **obliga** a lo que D-COL-2 exige;
no hay que añadir nada para que esa parte no se pueda olvidar.

### 1.6 El diagnóstico, en una frase

**El motor sólo sabe CONSTRUIR la etiqueta y la partición; no sabe LEERLAS aunque la institución ya
las traiga en su archivo.** La fricción de «Validar un modelo existente» es un síntoma de eso, no un
problema de cuántas preguntas hace la interfaz.

Y hay media capacidad ya presente: **`bad_rule` ya sabe leer una etiqueta existente**. Es
literalmente lo que trae el preset F1 —`{"all_of":[{"col":"bad_flag","op":"==","value":1}]}`—. Lo
que falta ahí no es motor: es que la interfaz lo **ofrezca** en vez de exigir construir la regla a
mano.

## 2. Decisiones

**D-COL-1 — Ninguna decisión obligatoria se esconde, en ningún trabajo.** Las cuatro se siguen
preguntando siempre. §1.2 y §1.3 lo miden: **mientras el trabajo declare la sección `data`**,
omitirlas es imposible en tres casos y deshonesto en el cuarto. Lo que cambia no es *cuántas*
preguntas hay, sino *en qué idioma* se pueden contestar.

⚠️ **Precisión que corrige a una versión anterior de este documento, y que la revisión adversarial
tuvo razón en exigir.** Aquí decía «todos los trabajos **requieren** `("data","frame")`», y es
**falso**: `performance` y `stability` no lo requieren (`performance/step.py:62-65`,
`stability/step.py:68-72`), y medido, un config con `data: None` + `performance` + `stability`
(`temporal_axis: "none"`) + `report` da `check_pipeline → executable=True`. Lo cierto es lo otro:
los 10 trabajos **declaran la sección `data`** en su catálogo, y mientras la declaren `DataStep`
corre y exige las dos decisiones. La imposibilidad es de la exención **declarativa** —dejar la
sección puesta y no preguntar—, no de la ejecución sin `data`.

**Que se pueda correr sin `data` no reabre nada**: es la opción «quitar `data` del trabajo», medida
en la sesión anterior y **descartada por Cami** con su coste a la vista —se pierden el `data_hash`
y las tres tablas de población—. Esta enmienda existe *porque* esa opción se descartó. Se deja
escrito para que la próxima revisión no vuelva a proponerlo como si fuera un hallazgo nuevo.

**D-COL-2 — `PartitionStrategy` gana una CUARTA rama: la partición viene en una columna.**
`{"type": "columna", "partition_col": …, "desarrollo": …, "holdout": …, "oot": …}`, con mapeo
**explícito** de los valores del usuario a las tres particiones del motor. Es hash-neutral (§1.5),
el formulario la renderiza sin código nuevo y el preflight la verifica gratis declarando
`column_role: "input"` en `partition_col`.

**D-COL-3 — Prohibido adivinar el mapeo.** Ni por parecido de nombre (`dev`≈`desarrollo`), ni por
orden, ni por frecuencia. Un valor sin mapear es un error **nombrado**, no una asignación
inventada; lo no mapeado explícitamente cae a `fuera_de_modelo`. Es D-OBL-5 aplicado al sitio nuevo:
el motor no inventa criterio institucional.

**D-COL-4 — Con `columna`, las particiones exigidas son EXACTAMENTE las que el usuario mapeó.**
`_required_model_partitions` (`data/partition.py:469-499`) no puede exigir `oot` como hace
`temporal`, ni mirar fracciones como hace `random`: aquí el conjunto lo declara el usuario. El veto
de `_validate_min_bads` **se conserva intacto**, y con esta rama pasa a medir *las particiones del
propio usuario*, que es información legítima sobre su muestra.

**D-COL-5 — `TargetConfig` NO se toca.** `bad_rule` ya expresa «la etiqueta viene marcada en una
columna». Añadirle un campo movería el `config_hash` de **todo** config existente (§1.5) para
comprar una capacidad que ya está. Lo que falta es de interfaz, y lo cubre D-COL-6.

**D-COL-6 — Una decisión declara sus FORMAS DE RESPUESTA, cada una con su pregunta de negocio y una
plantilla literal del fragmento de config que produce.** Para `bad_rule`: *«la construyo con
condiciones»* (la de hoy) y *«ya viene marcada en una columna de mi archivo»* → produce el `Rule`
exacto. Para `partition.strategy`: las tres de hoy más *«ya viene marcada en una columna»* (D-COL-2).
La plantilla es un literal en `ui/` —mismo precedente que `presets.py`—, de modo que el front elige
forma sin reimplementar dominio (SDD-23 §11).

**D-COL-7 — Se pregunta qué valor marca el incumplimiento; nunca se asume `1`.** Exige extender el
perfil de columnas (`ui/datasets.py`) con los valores más frecuentes, para **ofrecerlos** en vez de
pedirlos a ciegas. Aditivo, y se apoya en el perfil que desde esta sesión tienen también los
datasets del catálogo.

**D-COL-8 — Pre-rellenar, jamás auto-contestar.** Una forma de respuesta puede llegar **pre-cargada**
desde una columna que el trabajo ya preguntó, mostrada como respuesta editable y **con su
procedencia a la vista**; sin un gesto del usuario, el config sigue **incompleto y honesto**
(D-OBL-5 intacto). Un clic escribe exactamente lo que el usuario habría escrito a mano, así que el
`config_hash` es el mismo por los dos caminos (D-OBL-10 / D-JOB-9 intactos).

⚠️ **El pre-relleno cruzado sólo procede si el insumo externo declara el MISMO `dataset_id` que la
cartera.** Los `config_paths` de `external_artifacts` se validan contra el archivo externo
(`ui/routes.py:357-380`) y el motor lee la cartera: pegar una columna de uno en el otro sería un
error de categoría **silencioso**. Cuando no procede, se dice por qué (D-JOB-5) en vez de callarlo.

**D-COL-9 — La prosa del informe sólo narra la partición que de verdad se aplicó.** Hoy
`report/prose.py:415-419` afirma el reparto sin condición. Se le aplica el criterio que la frase del
target ya usa doce líneas más arriba. *(Se implementa en el paquete de las tablas de población, que
va aparte por tocar goldens del informe.)*

**D-COL-10 — Esto no mueve ningún hash de ningún config existente**, y lo verifica un gate sobre los
tres presets. Es la propiedad que hace la enmienda aditiva de verdad y no de palabra.

## 3. Alternativas rechazadas

1. **Acotar las decisiones por trabajo (el plan heredado).** Medido inviable: §1.3. Se conserva
   escrito porque descubrir *por qué* no se puede vale más que la enmienda misma.
2. **Rellenar la decisión con el default del motor.** Publica una frase falsa en el informe y
   contamina el `data_hash` con la semilla (§1.3).
3. **Una variante de sección `data` que cargue pero no etiquete.** Entrega **menos** que hoy: card
   vacía, `data_hash` distinto, cinco capas tocadas, cero precedente (§1.4).
4. **Graduar cada par (trabajo, decisión) por su «efecto» y reagrupar la tarjeta.** Es la propuesta
   más barata y baja la fricción a dos clics sin tocar el motor, pero su grado depende de un oráculo
   por grep sobre el fuente: un paso que nombre su columna por una constante importada escapa, y el
   grado equivocado es exactamente lo que D-COL-1 existe para impedir. Se rechaza el **grado**; su
   idea de proponer respuestas derivadas de lo ya contestado se conserva en D-COL-8.
5. **Añadir un campo a `TargetConfig` para «leer la etiqueta».** Mueve el `config_hash` de todos los
   configs existentes para comprar algo que `bad_rule` ya hace (§1.6).
6. **Adivinar el mapeo de valores de la columna de partición.** Es criterio institucional inventado,
   y en silencio: la clase que este repo ya pagó tres releases seguidos.

## 4. Gates de aceptación

- **Hash-neutralidad**: los tres presets conservan su `config_hash` byte a byte con la rama nueva
  registrada. Control negativo: convertir la rama en un campo de `PartitionStrategy` pone rojo.
- **La rama funciona de punta a punta**: una cartera con su columna de partición corre hasta `done`
  con las particiones del usuario, y `check_dataset` verifica la existencia de `partition_col` sin
  código nuevo.
- **Nada se adivina**: un valor de la columna sin mapear produce un error nombrado. Control
  negativo: implementar el parecido por nombre pone rojo.
- **Cobertura de formas de respuesta (bidireccional)**: `{formas declaradas para un path}` iguala
  `{ramas que el schema declara para ese path}`. Añadir una quinta estrategia sin su forma ⇒ rojo;
  declarar una forma sin rama ⇒ rojo.
- **Prohibido contestar por el usuario, por CI**: ningún path de `_DECISIONES_POR_SECCION` puede
  aparecer en ningún `config_paths` de `external_artifacts` ni ser materializado por
  `effective_defaults`.
- **Paridad de identidad**: el `config_hash` de un config completado por una forma de respuesta es
  idéntico al del mismo config escrito campo a campo desde las secciones.
- **El gate bidireccional vigente de D-OBL-7 sigue verde sin tocarse**: ningún `path` cambia, así
  que `test_jobs_decisiones.py:105-131` no se modifica. Que no haya que tocarlo es parte de la
  prueba de que esto no esconde nada.
- **Si alguna vez se introdujera una exención**, el catálogo debe declararla con su motivo y el test
  **re-derivar** independientemente el predicado desde `requires`/`provides`, con **ancla nominal
  positiva** (`scorecard_pd` debe salir «consume»): un oráculo roto que dijera «nadie consume nada»
  —y por tanto eximiera todo— no puede pasar.
- Copy sin jerga en toda pregunta y toda nota (gate vigente, extendido a las formas nuevas).
- Fixture de trabajos y de schema regenerados y bundle reconstruido **en el mismo commit**; suite,
  mypy, ruff, vitest, typecheck, `mkdocs --strict`.
- Verificación **en vivo con Playwright**: vitest corre sin DOM y no puede probar lo que se ve.

## 5. Lo que esta enmienda NO resuelve, dicho y no escondido

1. **No elimina ninguna pregunta.** «Validar un modelo existente» sigue pidiendo dos cosas; lo que
   desaparece es tener que **inventar criterio** para contestarlas. Si el objetivo era «cero
   preguntas», la medición dice que nada lo consigue sin esconder algo.
2. **No desactiva el veto** de `min_bads_per_partition`. Se conserva, y con D-COL-4 pasa a medir las
   particiones del usuario. ⚠️ Su mensaje de error nombra hoy la estrategia y campos que el usuario
   quizá no eligió: revisarlo es trabajo aparte.
3. **No arregla el desajuste de `loc`**: con el hueco, Pydantic devuelve `data.target` y el front no
   puede casarlo con `required_decisions` —y un solo error `survival.input` cubre **dos** decisiones—.
   Es un paquete propio.
4. **No neutraliza el frame**: `partition`/`ttd`/`target`/`label_status` siguen viajando a survival y
   a las provisiones.
5. **No cubre el caso de dos archivos distintos** cuando la columna no está en la cartera. Ahí queda
   la experiencia de hoy **más su motivo** (D-COL-8).

## 6. Orden de implementación

1. `data/config.py` — `PartitionFromColumnConfig` + cuarta rama en `PartitionStrategy` (+
   `column_role`). **Con su gate de hash-neutralidad en el mismo commit.**
2. `data/partition.py` — `_split_from_column`, entrada en `_SPLITTERS`, caso en
   `_required_model_partitions`.
3. Enmienda de SDD-02 indexada en `00-INDICE.md`, **mismo commit**.
4. `ui/datasets.py` — valores frecuentes en el perfil de columnas (D-COL-7).
5. `ui/jobs.py` — formas de respuesta con sus plantillas y el pre-relleno condicionado; fixture de
   trabajos en el mismo commit.
6. `web/` — selector de forma de respuesta; el renderizado de la rama nueva **no requiere código**.
7. Verificación en vivo del trabajo «Validar un modelo existente», de punta a punta.

Ningún paso autoriza bump, tag ni publicación.
