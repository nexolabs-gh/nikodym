# Enmienda SDD — el formulario no sabe de dónde sale una columna

> **Estado: APROBADA por Cami e IMPLEMENTADA (2026-08-03).** Verificada en vivo con Playwright, los
> seis casos de D-PRO-6 en la pantalla.
>
> ## 🔴 Lo que la implementación corrigió de este documento
>
> 1. **El campo se llama `produced_columns_by_section`, no `available_columns_by_section`**, y
>    publica sólo las columnas **producidas** por sección — no la unión con las del archivo. Razón
>    medida: `/api/validate` **no recibe el `dataset_id`**, así que no puede conocer las columnas del
>    archivo; el front ya las tiene y hace la unión. Lo que importaba de D-PRO-3 se conserva intacto:
>    la regla de D-RAM-7 la aplica el backend, y el front sólo busca su clave.
> 2. **El mapa viaja COMPLETO, con todas las claves del config**, incluidas las que no aportan nada.
>    Filtrar las vacías obligaría al consumidor a distinguir «esta sección no viene» de «no aporta
>    nada», que son la misma cosa y no deberían parecer dos.
> 3. ⚠️ **`columnas_producidas_por_seccion` tiene que COACCIONAR las secciones opacas**, y no estaba
>    en el diseño. Lo cazó `test_seccion_opaca_invariante` al escribirla: una sección que viaja como
>    `dict` —el estado por defecto— no implementa `columnas_que_produce`, así que sin la coacción la
>    misma pregunta tendría dos respuestas según los imports y el formulario acusaría en rojo lo que
>    el motor da por bueno. El gate obligó a declarar su política, y la respuesta es «comprobado».
> 4. 🔴 **Abrir la pantalla destapó copy falso que el diseño no anticipaba**: el desplegable rotulaba
>    «Columnas del archivo (21)» sobre una lista donde 4 no venían del archivo. Se arregló con lo que
>    D-PRO-4 ya pedía —procedencia a la vista—: el rótulo pasa a «Columnas disponibles» cuando hay
>    producidas, «Índice del archivo» en un campo de índice, y cada chip derivado se marca
>    «· calculada» con su tooltip.
> 5. ⚠️ **Límite medido y declarado: las columnas producidas sólo se conocen si el config VALIDA.**
>    Con las decisiones obligatorias en blanco (D-OBL-5) `/api/validate` no devuelve el mapa, así que
>    el formulario vuelve a ofrecer sólo las del archivo. No es un defecto nuevo —es el estado que
>    había siempre— y degrada del lado seguro, pero conviene saberlo: el aviso aparece **después** de
>    contestar las decisiones, no antes.
> 6. **`data.schema.index_col` pasa de caja de texto a widget `column`.** Es cambio de UI observable,
>    consecuencia directa de D-PRO-5: antes no ofrecía nada y se tecleaba a ciegas.
>
> ---
>
> **Estado original:** BORRADOR, pendiente de aprobación de Cami (2026-08-03).
> **Enmienda a:** [`_ENMIENDA-COLUMNA-EN-RAMA-INACTIVA.md`](_ENMIENDA-COLUMNA-EN-RAMA-INACTIVA.md)
> (D-RAM-6/7, que enseñaron esto al backend y dejaron al front atrás) y a SDD-23 §4.2 (contrato REST).
> **Decisiones:** D-PRO-1 … D-PRO-9.

## 0. Los dos defectos, medidos y verificados en pantalla

Son el mismo defecto de fondo —**el front cree que «columna del archivo» es la única clase de columna
que existe**— con dos caras que hoy se ven distintas.

### 0.1 · El front acusa lo que el backend acredita

```
survival.input.event_col = "target"

front     → campo en ROJO, aria-invalid=true, «Esa columna no está en el dataset cargado»
backend   → check_dataset: compatible=True, cero mismatches
corrida   → done
```

El aviso es **falso**, y lo peor es que convive en la misma pantalla con el aviso del preflight, que
para el mismo config guarda silencio. El usuario ve dos superficies del mismo producto
contradiciéndose y no tiene forma de saber cuál miente.

Nació de una mejora: D-RAM-6 enseñó al backend que `data` escribe cuatro columnas al frame
—`target`, `label_status`, `partition`, `ttd`— y que exigirlas del archivo es un falso positivo.
**El front no se enteró.** Antes los dos estaban de acuerdo, y los dos mal.

🔴 **Y no son dos campos: son 32.** Medido sobre el schema real, hay **47 rutas** con
`column_role: "input"`; el backend acredita las columnas producidas a toda sección **menos a la que
las produce** (D-RAM-7), así que las 15 de `data.*` se siguen acusando —correctamente— y **las otras
32 se acusan sin motivo**:

| sección | rutas afectadas |
|---|---:|
| `binning` (`feature_columns`, `exclude_columns`, `categorical_columns`) | 3 |
| `stability` (`temporal_column`) | 1 |
| `survival` (`duration_col`, `event_col`, `id_col`, `segment_col`, `covariate_cols`) | 5 |
| `provisioning_cmf` | 4 |
| `provisioning_internal` | 5 |
| `provisioning_ifrs9` | 14 |

⚠️ **Excepción medida, no deducida:** `stability.temporal_column` tiene **3 valores alcanzables y no
4**. `StabilityConfig` rechaza `"partition"` **antes de construir**, por su anticolisión propia
(`stability/config.py:205-213`). Probar ahí los cuatro mediría el validador, no el preflight.

Dos comprobaciones distintas lo pintan, y las dos llaman a la misma función pura:

- **escalar** — `FieldRenderer.tsx:447-451` (`ausente`), copy en `FieldRenderer.tsx:467`;
- **multiselect** — `FieldRenderer.tsx:1011`, copy en `FieldRenderer.tsx:1040`.

Ambas se apoyan en `optionsFromDataset` (`form-engine.ts:970-974`) y en una única lista:
`ConfigTab.tsx:751-753`, `selectedDataset.columns.map(c => c.name)` — **los nombres crudos del
archivo, sin ninguna otra fuente.**

**Ningún test lo cubre**, ni en vitest ni en pytest. Lo que hay es adyacente y pasa igual con el
defecto puesto.

### 0.2 · El catálogo publica el ÍNDICE como si fuera una columna

```
catálogo declara  →  loan_id, ingreso_mensual, deuda_ingreso, … (9)
parquet real      →  8 columnas + loan_id como ÍNDICE
```

`loan_id` **no es una columna inexistente: es el índice**. Se declara en `ui/datasets.py:72` dentro
de `_COLUMNS`, que los otros dos esquemas heredan por splat (`:104`, `:126`), de modo que alcanza a
**los cinco datasets del catálogo**.

Consecuencia visible: por `ConfigTab.tsx:752-754` la interfaz **ofrece `loan_id` como columna
elegible** en todo campo de columna —features del binning, target, segmento—, y en el parquet no hay
tal columna. Sólo funciona como `data.schema.index_col`, que es lo que el preset hace bien.

🔴 **Y el backend ya sabe la verdad y se contradice consigo mismo**: `_columnas_del_parquet`
(`ui/routes.py:177-206`) separa índice de columnas para el preflight —tiene que hacerlo, es el falso
positivo más caro del repo—, y `_valores_publicables` (`ui/datasets.py:295-297`) itera
`frame.columns`, de modo que `loan_id` sale siempre con `values: []` mientras sus ocho hermanas
traen valores. Un dataset **subido** deriva sus columnas de `frame.columns` (`ui/datasets.py:367-380`)
y por tanto **no** incluye el índice: catálogo y subida ya publican cosas distintas.

⚠️ **Y el gate que debería vigilarlo CODIFICA la conflación.**
`tests/unit/test_ui_datasets.py:243-250` suma el índice a mano para que cuadre:

```python
nombres_frame = [frame.index.name, *frame.columns]
assert nombres_frame == nombres_descriptor
```

Bendice la declaración actual. No es un gate que se olvidó del caso: es un gate que lo afirma.

## 1. La causa común

`GET /api/datasets` publica una sola lista, `columns`, y el front la trata como *«todo lo que el
usuario puede nombrar»*. Pero un nombre de columna en el config puede referirse a **tres** cosas
distintas, y sólo una está en esa lista:

| clase | ejemplo | ¿está en `columns`? | ¿el backend la acepta? |
|---|---|---|---|
| columna del archivo | `ingreso_mensual` | sí | sí |
| **índice** del archivo | `loan_id` | 🔴 sí, y no debería | sí, sólo en un campo `index` |
| columna que **produce el pipeline** | `target`, `partition` | no | sí, salvo en la sección que la escribe |

El front no puede distinguirlas porque **nadie se las publica separadas**. `role` no sirve: es el rol
semántico del catálogo sintético (`id`, `feature`, `segment`, `cohort`, `target`, `economic`,
`survival`), un dataset subido no lo trae, y su valor `target` describe una columna **del archivo**,
no la que el pipeline escribe. Es un falso amigo.

## 2. Decisiones

**D-PRO-1 — El catálogo publica el índice APARTE, y `columns` vuelve a significar columnas.**
`GET /api/datasets` gana `index_columns: string[]`, y `loan_id` sale de `columns`. Aditivo: un
cliente que sólo lea `columns` obtiene una respuesta **más correcta** que hoy, no una distinta.

*Por qué no se resuelve filtrando por `role` en el front*, que era más barato y no tocaba el
contrato: `role` describe la semántica de negocio de la columna, no su ubicación física, y un dataset
subido no lo trae. Usarlo funcionaría por coincidencia —hoy sólo `loan_id` tiene `role: "id"`— y
dejaría el payload afirmando algo falso para todo consumidor que no sea nuestro propio front.

**D-PRO-2 — El backend publica, por sección, qué columnas puede nombrar esa sección.** Un campo nuevo
en la respuesta de `POST /api/validate`:

```json
"available_columns_by_section": {"data": ["…"], "survival": ["…", "target", "partition"], "…": []}
```

Va en `/api/validate` y **no** en `/api/schema` por una razón medida: la lista **depende del config**
—`DataConfig.columnas_que_produce()` devuelve el `target_col` *del config*, no una constante, y hay
test que lo exige (`test_columna_en_rama_inactiva.py:256`)—. El schema es estático y no puede
saberlo. `/api/validate` ya recibe el config, ya se llama en cada tecleo y ya es de donde cuelga el
preflight.

**D-PRO-3 — 🔴 La lista viaja YA RESUELTA por sección, y ésa es la decisión importante.** El backend
aplica él la regla de D-RAM-7 —*una sección no se acredita a sí misma*— y publica, para cada sección,
el conjunto que **esa** sección puede nombrar. El front hace un lookup por el primer segmento del
path y nada más.

*Por qué no una lista plana:* con `["target", "partition", …]` el front pintaría en verde
`data.schema.columns[0].name = "partition"`, que el backend **sí** acusa y cuya corrida muere en el
primer paso. Sería reintroducir en el front el defecto que D-RAM-7 acaba de cerrar en el backend.

*Y por qué el front no aplica la regla él mismo:* sería reimplementar dominio en la interfaz, que
SDD-23 §11 prohíbe. Es el mismo mecanismo que el `when` de `external_artifacts` y que los `slots`
condicionales de las formas de respuesta: **la condición viaja como dato y el front la evalúa sin
saber qué significa.**

**D-PRO-4 — Una columna producida se OFRECE, marcada con su procedencia.** No basta con dejar de
pintarla en rojo: si el motor la acepta, el desplegable debe ofrecerla, y decir de dónde sale («la
calcula el paso anterior»). Ocultarla sería la mentira simétrica —D-JOB-5 aplicado a una columna en
vez de a una opción—.

**D-PRO-5 — El índice se ofrece donde corresponde y sólo ahí.** Un campo con `column_role: "index"`
ofrece `index_columns`; uno con `"input"`, `columns`. Hoy `index_col` es el único campo `index` del
repo, y el preset F1 ya lo apunta a `loan_id`: esto hace verdadero en la interfaz lo que el preset ya
hacía bien.

**D-PRO-6 — 🔴 Al separar los tres conjuntos se prueban LOS TRES, no sólo el que se arregla.** Es la
lección más cara de la sesión del 2026-08-03 —un arreglo de copy rompió su caso simétrico el mismo
día— y aquí hay tres conjuntos y no dos:

| caso | esperado |
|---|---|
| columna del archivo | sin rojo (hoy correcto) |
| columna producida, sección **distinta** de `data` | **sin rojo** ← lo que se arregla |
| columna producida, campo **dentro de `data`** | **con rojo** ← D-RAM-7, no puede perderse |
| índice, en un campo `input` | **con rojo** ← no es una columna |
| índice, en un campo `index` | sin rojo |
| columna inventada | **con rojo** ← el control negativo de siempre |

Los seis, con test. Un gate que sólo mida el segundo daría verde habiendo roto el tercero.

**D-PRO-7 — Paridad front↔backend como invariante, no como coincidencia.** Un gate cruza, para un
config y un dataset dados, el veredicto de `check_dataset` con el conjunto que el front usaría, y
exige que **no haya campo donde uno acuse y el otro calle**. Es el gate que no existía y que habría
cazado esto el día que D-RAM-6 entró.

⚠️ Su oráculo se escribe **a mano**: derivar el conjunto del front llamando a la misma función del
backend mediría que la función es determinista, no que las dos superficies coinciden — el gate
autorreferencial que este repo ya pagó dos veces.

**D-PRO-8 — El gate que codifica la conflación se corrige, no se elimina.**
`test_ui_datasets.py:243-250` pasa a comparar `columns` contra `frame.columns` y `index_columns`
contra el nombre del índice, **por separado**. Un gate que sume el índice a mano para que cuadre no
está midiendo el descriptor: está afirmándolo.

**D-PRO-9 — Nada de esto mueve un `config_hash` ni un `data_hash`.** No nace ningún campo de config:
son un campo de payload REST y una lista que se calcula en tiempo de render. Gate sobre los tres
presets.

## 3. Alcance: qué NO entra

1. **El fixture de la demo estática** (`web/src/fixtures/demo/datasets.json`) trae hoy `loan_id` como
   columna en los cinco datasets. Se regenera en el mismo commit — es dato derivado, no decisión.
2. **`stability.temporal_column = "partition"`** sigue siendo inalcanzable por el anticolisión de
   `StabilityConfig`. No se toca: es una guarda legítima de esa sección.
3. **No se declara la procedencia de columnas que produce una sección distinta de `data`.** Hoy sólo
   `DataConfig` implementa `columnas_que_produce`; si mañana otra sección escribe columnas, entra sola
   por el mismo mecanismo.

## 4. Gates de aceptación

- Los **seis** casos de D-PRO-6, con sus controles negativos ejecutados.
- **Paridad front↔backend** (D-PRO-7) con oráculo escrito a mano y ancla nominal positiva.
- `columns` de los cinco datasets del catálogo **iguala** `frame.columns`, e `index_columns` iguala
  el índice — comparados por separado (D-PRO-8), y **con `_columnas_del_parquet`**, nunca leyendo el
  esquema Arrow por cuenta propia.
- Hash-neutralidad sobre los tres presets.
- Fixture de la demo y bundle regenerados en el mismo commit; suite, mypy, ruff, vitest, typecheck.
- **Verificación en vivo**: `survival.input.event_col = "target"` deja de pintarse en rojo y
  `data.schema.columns[0].name = "partition"` **sigue** pintándose. Vitest corre sin DOM.

## 5. Orden de implementación

1. `ui/datasets.py` — `index_columns` fuera de `columns` (D-PRO-1), con D-PRO-8 en el mismo commit.
2. `ui/routes.py` — `available_columns_by_section` en `/api/validate` (D-PRO-2/3).
3. `web/src/lib/form-engine.ts` + `ConfigTab.tsx` — el conjunto por sección y el índice (D-PRO-4/5).
4. Gates de D-PRO-6/7; fixture y bundle.
5. Verificación en vivo.

Ningún paso autoriza bump, tag ni publicación.
