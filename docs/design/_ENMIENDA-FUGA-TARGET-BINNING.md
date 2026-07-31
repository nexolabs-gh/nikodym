# Enmienda SDD — la columna que define el target entra como predictor

> **Estado:** **APROBADA en sus decisiones de fondo** (OK explícito de Cami, 2026-07-30). Ninguna
> línea de motor escrita, y **sin commitear hasta después del webinar** (esa misma noche).
> **Enmienda a:** SDD-06 §4/§7 (`binning`, resolución de variables candidatas) y SDD-02 §4
> (`data.target`, las reglas del target como fuente de verdad de qué columna es insumo del target).
> **Decisiones:** D-FUGA-1 … D-FUGA-10.
> **Nodo de roadmap:** Fx (defecto P1) de
> [`privado/FIGURA-Y-ROADMAP-2026-07-30.md`](../../privado/FIGURA-Y-ROADMAP-2026-07-30.md).
> **Autor / Fecha:** DanIA · 2026-07-30 (medido contra `main` = `c6513aa`).

---

## 0. El defecto

`binning.feature_columns = "*"` —**el default del campo** (`binning/config.py:145`)— significa
«todas las columnas no estructurales del dataset». El motor excluye ocho nombres: los cuatro que
recibe del dominio `data` en runtime y sus cuatro literales por defecto
(`binning/step.py:433-449`):

```python
{target_col, status_col, partition_col, ttd_col,
 "target", "label_status", "partition", "ttd"}
```

`target_col` es la columna **derivada** —la que el motor crea con el 0/1—, no las columnas del
dataset de las que esa etiqueta se calcula. Y esas columnas **son inferibles del propio config**:
viven en `data.target.bad_rule`, que es obligatoria (`data/config.py:429`).

**Con una regla «más de 90 días de mora», la columna de mora entra como predictor.** El modelo la
elige (IV altísimo, es el target disfrazado), el AUC sale inflado, y el informe publica una scorecard
que en producción no discrimina nada. Es la fuga de target clásica, y hoy el motor la habilita con su
configuración por defecto.

### 0.1 La medición (2026-07-30, `main` = `c6513aa`)

Frame con seis columnas candidatas y un `data.target` que usa las cuatro clases de regla.
`_resolve_feature_columns` llamada directamente, sin ejecutar el pipeline:

```
estructurales excluidas : ['label_status', 'partition', 'target', 'ttd']

wildcard  '*'   → ('loan_id', 'dpd_12m', 'fraude', 'score_buro', 'cerrado', 'al_dia')
                            ▲          ▲                          ▲         ▲
                       bad_rule   exclusion_rule        indeterminate  good_rule

lista explícita → ('dpd_12m', 'score_buro')
                     ▲ también sobrevive: la rama explícita filtra por el MISMO conjunto
```

**Tres cosas que la medición añade al enunciado del defecto:**

1. **No es sólo `bad_rule`.** Las cuatro reglas del target aportan columnas y las cuatro entran hoy:
   `bad_rule`, `good_rule`, `indeterminate_rule` y `exclusion_rules[].rule` (`data/config.py:429-470`).
   Pero **no todas son fuga** — ver D-FUGA-2, que es la decisión menos obvia de esta enmienda.
2. **La rama de lista explícita comparte el mismo conjunto de exclusiones** (`step.py:423`), así que
   cualquier cambio ahí afecta también a quien enumera sus variables a mano. Eso obliga a decidir las
   dos ramas por separado (D-FUGA-3), no a tocar un `set` y darlo por hecho.
3. **El mecanismo de inferencia ya existe, en la línea de al lado.** `_data_temporal_columns`
   (`step.py:410,452-464`) ya lee del `DataConfig` las columnas de fecha y cohorte —
   `target.window.observation_date_col`, `data_cutoff_col`, `partition.strategy.date_col`,
   `cohort_col`— para excluirlas del wildcard. Esta enmienda **no inventa un mecanismo: extiende uno
   que ya está y funciona.** Y su helper `_get_config_attr` (`:467-473`) ya soporta el config opaco.

---

## 1. Lo que la medición corrigió del enunciado

### 1.1 🔴 «Cambia comportamiento y mueve hashes» — **los hashes NO se mueven**

Medido:

- **`config_hash` no cambia.** Es el SHA-256 del config computacional (`core/config/hashing.py:91`).
  El arreglo **no toca ningún campo del config**: cambia qué columnas *deriva* el motor a partir del
  mismo config. Mismo config → mismo digest, antes y después.
- **`data_hash` no cambia.** Es el hash del frame que publica `data` (`data/step.py:82`), un paso
  **anterior** a binning.

Lo que cambia son los **resultados**: el universo de variables candidatas → las finales → los
coeficientes → las métricas → el informe. Y con ellos, los golden values de los tests que corran con
wildcard. El encuadre SemVer es correcto (**minor**) pero por otra razón: no porque recalcule
identidad, sino porque **cambia el número que sale de una corrida existente**. La nota de contrato
tiene que decir eso, no lo otro.

### 1.2 ✅ Ningún preset de fábrica se mueve, y la demo del webinar tampoco

Medido sobre los tres presets publicados:

| preset | `binning.feature_columns` | `bad_rule` | ¿la columna del target está en la lista? |
|---|---|---|---|
| `f1-estandar-consumo` | lista de 6 explícitas | `bad_flag` | **no** |
| `f3-provisiones-consumo` | lista de 6 explícitas | `bad_flag` | **no** |
| `f4-ifrs9-retail` | sin sección `binning` | `bad_flag` | — |

**Ningún preset usa `"*"` en binning.** Y el config del webinar (HMEQ) usa `"*"` **con
`exclude_columns=["BAD"]`**, o sea que ya excluye a mano la columna que el arreglo excluiría solo:
mismo resultado, mismo `config_hash e5868bd6…`, mismos AUC.

⇒ **El arreglo no mueve ni un golden de preset, ni un `config_hash`, ni un número de la demo.**
Cambia el resultado **sólo** para quien usa el wildcard sobre un dataset cuya columna de target no
excluyó a mano — que es exactamente el caso que hoy produce la fuga. Eso baja el riesgo del cambio de
«mueve todo» a «corrige justo lo que estaba mal».

### 1.3 El alcance es `binning`, y está acotado por medición

- **`selection.feature_columns` también admite `"*"`** (`selection/config.py:265`) pero opera sobre
  las **variables WoE que publica binning**, no sobre columnas del dataset (ya escrito en
  `CLAUDE.md`, verificado en el config). Si binning excluye la columna, selection no la ve: el
  arreglo se propaga solo. **No se toca.**
- **`ml` no declara `feature_columns`** (grep vacío): consume lo que selection publica. **No se
  toca.**
- **`_structural_columns` tiene un único consumidor**, `_resolve_feature_columns` (`step.py:409`).
  El cambio está contenido en una función.

---

## 2. Decisiones

### D-FUGA-1 · Las columnas que determinan la ETIQUETA se excluyen del wildcard: `bad_rule` y `good_rule`

Se derivan del config todas las columnas nombradas en los predicados de `data.target.bad_rule` y
`data.target.good_rule` (`Predicate.col`, en `all_of` y `any_of`), y se suman al conjunto de
exclusiones que ya construye `_resolve_feature_columns`.

**Por qué también `good_rule`,** que el enunciado no mencionaba: entre las filas que llegan al ajuste,
`good_rule` determina el `target = 0` (`data/target.py:135-147`) y es el complemento exacto de
`bad_rule`. Una `good_rule` de tipo «al día» hace de esa columna un predictor perfecto por la misma
mecánica. Con el default (`good_rule = None`, «es bueno todo lo que no sea malo») no hay columnas que
excluir y la decisión es inerte — que es el caso de los tres presets.

### D-FUGA-2 · `indeterminate_rule` y `exclusion_rules` quedan FUERA, y no por falta de tiempo

Es la decisión menos obvia, y va contra la intuición de «excluir todo lo que toque el target». La
razón es un **contraejemplo real**:

`indeterminate_rule` y `exclusion_rules` no determinan la etiqueta de nadie: determinan **quién sale
de la muestra** antes de etiquetar (`data/target.py:126-133`). Entre las filas que quedan, esas
reglas son falsas por construcción. Y su columna puede seguir teniendo variación legítima:

> `exclusion_rules = [{name: "productos_retirados", rule: {col: producto, op: "in", value: ["A","B"]}}]`
>
> En la muestra quedan los productos C, D, E. **`producto` es un predictor legítimo y bueno**, y
> excluirlo le quita al usuario una variable buena sin decírselo.

El caso degenerado (`fraude == 1`, que deja la columna constante) se resuelve solo: un bin, IV 0, y el
gate de variables no bineables ya la reporta. **Excluir por si acaso produciría falsos positivos**, que
es el criterio con el que D-INV-8 dejó fuera `stratify_by` y `required_sections`. Mismo razonamiento,
mismo resultado: se queda fuera **con su razón escrita**, no por omisión.

### D-FUGA-3 · Sólo se excluye en la rama `"*"`; la lista explícita se respeta, pero no en silencio

- **`feature_columns = "*"`** → las columnas de D-FUGA-1 se excluyen. El usuario dijo «elige tú», y el
  motor sabe cuáles no puede elegir.
- **`feature_columns = [...]`** → las columnas se **conservan**, y la contradicción se registra como
  decisión auditable (D-FUGA-5). El usuario las nombró una por una; borrarlas en silencio es
  exactamente el defecto que la UI ya pagó (`toggleMultiselect` descartaba los valores fuera de las
  opciones y borraba el trabajo del usuario sin avisar).

**Corolario que baja el riesgo del cambio:** la lista explícita es la **salida de escape**. Quien de
verdad quiera binear la columna del target puede, enumerándola. El arreglo cambia el *default*, no
quita capacidad.

### D-FUGA-4 · La inferencia debe funcionar con el config de `data` OPACO

`_resolve_feature_columns` recibe `data_config=getattr(study.config, "data", None)`
(`step.py:112`), que puede ser un `dict` sin coaccionar. **El estado opaco es el default**
(`test_seccion_opaca_invariante.py`), y es la familia de defectos que este repo pagó tres releases
seguidos.

El helper existente (`_get_config_attr`, `:467-473`) resuelve un nivel sobre dict o Pydantic. El
recorrido nuevo baja tres niveles y atraviesa **listas** (`target.bad_rule.all_of[i].col`), así que
el helper crece — y el gate de D-FUGA-8 lo prueba en los dos estados. Sin eso, el arreglo funciona en
la suite (donde todo está siempre importado) y **no** en el proceso de quien carga un YAML.

### D-FUGA-5 · Lo excluido se declara: audit-trail y card, no un `warning`

Dos canales, los dos ya existentes:

1. **Audit-trail**, por el mecanismo que binning ya usa para sus decisiones
   (`_log_binning_decisions`, `step.py:147`): una decisión por columna excluida, con la regla que la
   nombró.
2. **`BinningCardSection`** (`binning/results.py:87`), campo **aditivo**
   `excluded_by_target_rule: tuple[str, ...] = ()`, para que llegue al model card y al informe. Es
   extensión aditiva de un contrato de lectura (CT-3), no ruptura.

**No se emite un aviso declarado.** `FALTA-DATO` es una carencia del motor y `DATO-INSTITUCIONAL` un
dato que aporta la institución (`core/markers.py`); esto no es ninguna de las dos, y forzarlo dentro
de la taxonomía la desdibuja. **Tampoco un `warnings.warn`**: el proyecto corre con
`filterwarnings=["error"]`, así que un warning nuevo es un fallo de test disfrazado de aviso.

### D-FUGA-6 · El copy del campo tiene que dejar de mentir

`binning.feature_columns` dice hoy, en el formulario y en el tooltip:

> «'*' = todas las columnas no estructurales del dataset.»

Con el arreglo eso sigue siendo cierto sólo si «estructural» incluye las columnas que definen el
target — que no es lo que un lector entiende. La `description` y el `ui_help` se actualizan en el
mismo commit. ⚠️ Es **copy público** (`AGENTS.md` §copy público: una `description` de Pydantic viaja
a `schema.json` y de ahí al tooltip **y al placeholder**), así que el cambio obliga a regenerar
`web/src/fixtures/schema.json` (`scripts/gen_schema_fixture.py`) **y** a rebuildear el bundle
(`pnpm build:package`), o los gates G7 y el de drift del CI se ponen rojos.

### D-FUGA-7 · Contrato SemVer: MINOR, con nota de cambio de comportamiento

- **No recalcula identidad**: `config_hash` y `data_hash` no se mueven (§1.1).
- **Sí cambia el resultado numérico** de una corrida que use `"*"` con una columna de target no
  excluida a mano: menos variables candidatas, otros coeficientes, otro AUC — **más bajo, y correcto**.
- Precedente de encuadre: `1.6.0`, que también cambió números de corridas existentes y salió como
  minor con su nota en el CHANGELOG y la salida escrita.
- **La nota debe decir explícitamente que un AUC que baja tras actualizar es la corrección, no una
  regresión.** Sin esa frase, el primer usuario que lo vea va a abrir un issue de regresión.

### D-FUGA-8 · Los gates

1. **Gate de la clase, que se prueba inyectando el defecto**: config con `bad_rule` sobre `dpd_12m` y
   `feature_columns="*"` → `dpd_12m` **no** está entre las candidatas. Debe **fallar** con el código
   de hoy (verificarlo, no suponerlo).
2. **`good_rule`** en el mismo test, porque es la mitad que el enunciado no traía.
3. **Los dos falsos positivos de D-FUGA-2**: una `exclusion_rule` y una `indeterminate_rule` sobre una
   columna con variación → la columna **sigue** entre las candidatas. Este test defiende una decisión
   que un lector futuro va a querer «arreglar».
4. **Config opaco** (`data` como `dict`) → mismo resultado que tipado. D-FUGA-4.
5. **Rama explícita**: la columna se conserva **y** queda la decisión en el trail. D-FUGA-3.
6. **Los tres presets no se mueven**: `config_hash` byte a byte, y el conjunto de candidatas idéntico.
   Es el gate que demuestra §1.2 en vez de confiar en él.
7. **Un caso de punta a punta con dataset**: la fuga se ve en el número. Correr con la columna dentro
   y fuera, y aseverar que el AUC de desarrollo **baja**. Un test de conjuntos no demuestra que el
   defecto importaba.

### D-FUGA-9 · Lo que esta enmienda NO cubre

- **La definición de default vive en tres sitios sin contrato común** (`data.target`, el staging de
  IFRS 9, los backstops de CMF) — lo declara F5 del roadmap. Esta enmienda no unifica nada: usa
  `data.target` como fuente porque es la que alimenta a `binning`, y punto.
- **Un identificador no declarado** sigue entrando con `"*"`. ⚠️ Medido: `index_col` **no** protege,
  porque el validador lo interpreta como el nombre del índice pandas ya existente y no hace
  `set_index` (`data/schema.py:36-39`); si el identificador vive como columna, la única declaración
  que el motor tiene es `unique_keys`, y esa sí entra al alcance por D-FUGA-10. Lo que **no** se
  puede es adivinar un `loan_id` que el usuario no declaró en ninguna parte.
- **La fuga por construcción del dataset** —una columna que codifica el futuro sin estar en ninguna
  regla— es indetectable desde el config y no se promete.

### D-FUGA-10 · `unique_keys` entra, pero **sólo con una columna**, y ésa es la corrección medida

Decidido por Cami el 2026-07-30. La recomendación original decía «entra» a secas; medirlo la acotó:

`unique_keys` es `tuple[str, ...] | None` y declara **la combinación de columnas que identifica la
fila**, no una lista de identificadores. Su propio `ui_help` da el ejemplo: *«cliente + fecha»*
(`data/config.py:271-281`).

- **`len(unique_keys) == 1`** → la columna identifica la fila por sí sola: un valor por fila, binning
  degenerado, cero poder predictivo posible. **Se excluye del wildcard.**
- **`len(unique_keys) >= 2`** → **ninguna columna individual es identificador**, y excluirlas sería
  el falso positivo de D-FUGA-2 otra vez: en `("producto", "fecha_obs")`, `producto` es un predictor
  legítimo y `fecha_obs` ya la excluye `_data_temporal_columns`. **No se excluye nada.**

Va en **commit propio, con gate propio**, y separado en el CHANGELOG: esto es **ruido de
identificador**, no fuga de target. Mezclarlos haría que un usuario que ve bajar su AUC no sepa cuál
de los dos cambios se lo movió.

**Gate**: los dos sentidos —llave de una columna se excluye, llave compuesta **no** toca ninguna—,
porque el segundo defiende una decisión que un lector futuro va a querer «completar».

---

## 3. Contrato del cambio (ilustrativo)

```python
# data.target.bad_rule  = {all_of: [{col: "dpd_12m", op: ">=", value: 90}]}
# data.target.good_rule = None
# binning.feature_columns = "*"

# ANTES:  ('dpd_12m', 'score_buro', 'renta', 'antiguedad', ...)   ← dpd_12m es el target disfrazado
# DESPUÉS: ('score_buro', 'renta', 'antiguedad', ...)

# trail: {kind: "decision", step: "binning",
#         payload: {regla: "columna_del_target", valor: "dpd_12m",
#                   accion: "excluir_de_candidatas", umbral: "data.target.bad_rule"}}

# card:  excluded_by_target_rule = ('dpd_12m',)
```

---

## 4. Decisiones cerradas por Cami (2026-07-30)

1. **`unique_keys` entra** → D-FUGA-10, acotado a llave de **una** columna tras medir su semántica
   (es una llave compuesta, no una lista de identificadores). Commit propio y gate propio.
2. **Sale en `1.11.0` junto con la puerta de artefactos.** La nota del CHANGELOG debe decir
   explícitamente **cuál de los dos cambios mueve los números**: ésta sí (menos variables candidatas
   → otros coeficientes → **AUC más bajo, y correcto**), la puerta no (aditiva pura).
   ⚠️ El release en sí **sigue exigiendo OK específico de Cami** y la auditoría adversarial previa:
   los tres últimos la frenaron y encontraron defectos que el CI verde no veía.

**Orden de implementación** (a partir del 2026-07-31, ninguna línea escrita todavía):
D-FUGA-1/2/3 (el arreglo del wildcard) → D-FUGA-5 (trail + card) → D-FUGA-6 (copy + fixture +
bundle) → D-FUGA-10 (`unique_keys`, commit aparte) → D-FUGA-8 (los siete gates).
