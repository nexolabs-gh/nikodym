# Enmienda SDD — el config y el dataset propio no se comparan hasta que la corrida falla

> **Estado: APROBADA (Cami, 2026-07-28) e IMPLEMENTADA.** El OK cubre expresamente las dos
> decisiones que se le consultaron: el **alcance acotado al camino F1** (D-PRE-4) y que el preflight
> **informe sin bloquear** la ejecución (D-PRE-5).
>
> **Tres decisiones nacieron al programar** —D-PRE-9 completa, y D-PRE-3 cambió de mecanismo y de
> vocabulario— y quedan escritas con su razón, que es la conducta esperada aquí: reabrir un diseño
> por feedback del código es barato; dejar que documento y código se separen en silencio, no.
>
> **Base:** `main` = `c40013f` (CI verde 16/16, `1.8.0` publicado en PyPI).
> **Autor / Fecha:** DanIA / 2026-07-28.

| Campo | Valor |
|---|---|
| **Problema** | Un usuario que sube su propio CSV y elige un preset descubre los desajustes **de a uno**: cada corrida fallida revela el siguiente. Medido sobre `1.8.0` desde PyPI, un CSV con nombres de columna propios exige **6 ediciones del config en 6 lugares distintos**, y sólo la sexta corrida llega a `done` |
| **Enmienda a** | SDD-23 (`ui`) §7 —el contrato de `/run` y el flujo de upload— y el alcance de `nikodym.check_pipeline` (SDD-23 §7 bis / D-PIPE-1…D-PIPE-6), que responde «¿es ejecutable?» **sin leer el dataset** y por tanto no puede ver esta familia de desajustes |
| **No toca** | El contrato de `SchemaValidator` (`data/schema.py`): `index_col` sigue siendo el nombre del índice pandas **ya existente** y el validador sigue sin hacer `set_index`. Tampoco toca el motor, los presets, ni el `config_hash` |
| **Release** | Aditivo: una capacidad nueva y un endpoint nuevo. No cambia comportamiento existente ni identidad de config |

---

## 1. Lo que la medición dice, antes de diseñar nada

Medido el 2026-07-28 contra `nikodym[ui,scoring]==1.8.0` **instalado desde PyPI** en un venv limpio
fuera del checkout, con `nikodym-ui` levantado y hablando por HTTP. Scripts en el scratchpad de la
sesión (`recorrido.py`, `f1_csv_propio.py`, `cuantas_ediciones.py`).

### 1.1 El recorrido de B2 pasa en todo menos en este paso

| paso del criterio de cierre de B2 | resultado |
|---|---|
| `pip install` → `nikodym-ui` arranca | ✅ SPA 200; favicon, JS y CSS 200 cada uno; sin red externa |
| F1 / F3 / F4 hasta `done` + informe HTML | ✅ 3/3 (250 / 258 / 63 KB) |
| negativos de seguridad | ✅ Host falso → 403; Origin cruzado en `/run` → 403; token inválido → 403 |
| **F1 con CSV propio** | ❌ `failed` con el preset tal cual |

### 1.2 Seis ediciones, descubiertas en serie

Mismo contenido, nombres de columna de una cartera chilena (`rut_operacion`, `renta_liquida`,
`marca_incumplimiento`, …). Cada fila es una corrida completa; el mensaje es el que ve el usuario:

| # | edición acumulada | qué reporta la corrida |
|---|---|---|
| 0 | preset tal cual | `data` — 9 fallos de esquema, texto de pandera: `check: field_name('loan_id')` |
| 1 | `data.schema.index_col → None` | `data` — 8 fallos, `column_in_dataframe` por cada columna |
| 2 | `data.schema.columns[].name` | `data` — «Regla de target referencia una columna inexistente: `bad_flag`» |
| 3 | `data.target.bad_rule.all_of[].col` | `data` — «La estrategia cohort referencia una columna inexistente: `cohorte`» |
| 4 | `data.partition.strategy.cohort_col` | `binning` — «`feature_columns` declara columna(s) inexistente(s): …» |
| 5 | `binning.feature_columns` + `categorical_columns` | `stability` — «no se halló una columna de período/cohorte; fije `stability.temporal_column`» |
| 6 | `stability.temporal_column` | **`done`** |

Dos lecturas importan, y apuntan en direcciones opuestas:

- **Los mensajes del motor son buenos.** De la edición 2 en adelante cada uno nombra la columna
  exacta y el campo de config que la declara, en español. No hay nada que traducir ahí.
- **Pero el descubrimiento es serial.** El motor corta en el primer paso que falla, así que seis
  desajustes que existen desde el segundo cero se revelan en seis corridas. Ése es el defecto de
  producto: no la calidad de cada mensaje, sino que sólo llega uno por vez.

### 1.3 Lo que se midió y resultó FALSO

| hipótesis | medición |
|---|---|
| «`/api/run` no informa el error: devuelve `error: None`» | **Falsa.** `run_pipeline` devuelve por contrato `{run_id, status}`; el diagnóstico completo está en `GET /api/results/{run_id}` y en el `results.json` persistido. El `None` era artefacto del script de medición, no del producto |
| «Basta arreglar `index_col` para que el flujo funcione» | **Falsa.** Con un CSV fabricado con los nombres exactos del preset, sí: una sola edición y corre (AUC 0,737 / 0,726 / 0,718 en desarrollo / holdout / OOT). Con nombres propios —el caso real— faltan cinco ediciones más |
| «El mensaje de pandera es el problema principal» | **Parcialmente falsa.** Es el peor de los seis y es el primero que se ve, pero traducirlo dejaría intactas las otras cinco iteraciones |

### 1.4 El censo que decide el diseño

El camino F1 declara **26 campos** que nombran columnas, en siete secciones:

| sección | campos |
|---|---|
| `data` | `index_col`, `observation_date_col`, `data_cutoff_col`, `target_col`, `date_col`, `cohort_col` |
| `binning` | `feature_columns`, `exclude_columns`, `categorical_columns`, `keep_structural_columns` |
| `selection` | `feature_columns`, `exclude_columns`, `keep_structural_columns` |
| `scorecard` | `score_column` |
| `calibration` | `pd_raw_column`, `linear_predictor_column`, `pd_calibrated_column`, `linear_predictor_calibrated_column`, `partition_column`, `target_column` |
| `performance` | `score_column`, `pd_column`, `target_column`, `partition_column` |
| `stability` | `score_column`, `pd_column`, `partition_column`, `temporal_column` |

Sólo seis tropezaron, y la razón **es** el diseño: los demás nombran columnas que **produce el
pipeline** (`score_column`, `pd_column`, `partition_column`, `data.target.target_col`), no columnas
que el usuario deba traer. Un preflight que exigiera la existencia de las 26 en el CSV emitiría
falsos positivos en la mayoría; uno que no distinga no sirve para nada.

---

## 2. Decisiones

**D-PRE-1 · El preflight cruza el config contra los NOMBRES de columna del dataset, y nada más.**
No lee filas, no valida tipos, no ejecuta pasos, no deja rastro de corrida. Los nombres ya los tiene
la UI: `/api/upload` devuelve `columns[]`. Comprobar no es correr — la misma frontera que D-PIPE-1
fijó para `check_pipeline`, que esta capacidad extiende sin absorber.

**D-PRE-2 · Es TOTAL: reporta todos los desajustes de una vez.** Es la razón de existir de la
capacidad. Un preflight que corte en el primero reproduce el problema que viene a resolver.

**D-PRE-3 · Todo campo que nombra columna declara su rol en su propio `Field`.** Sólo las de
ENTRADA se exigen presentes en el dataset; las DERIVADAS las produce el pipeline y exigirlas sería
un falso positivo.

*El diseño decía «un registro único en un módulo», y al programarlo se movió al `Field`.* El
precedente del repo manda: `ui_help` y `ui_widget` ya viven ahí, y el rol es una **propiedad del
campo**, no un criterio transversal como `governable_warnings()` —que sí es central, y con razón—.
Junto a la declaración no puede divergir de ella, y viaja gratis al `schema.json` de la UI.

**El vocabulario tiene cuatro valores, no dos**, y los dos que faltaban salieron de medir:

- `not_a_column` — `keep_structural_columns` calza con el patrón `*_columns` pero es un **`bool`**
  que decide si se conservan las columnas estructurales. Se marca explícitamente en vez de dejarlo
  sin rol, para que la excepción se lea como decisión y no como olvido.
- `index` — ver D-PRE-6.

**Y dos clasificaciones «obvias» resultaron falsas**, que es justo lo que la decisión previene:
`selection.feature_columns` y `selection.exclude_columns` **no** nombran columnas del dataset sino
las variables WoE que publica *binning*, así que son DERIVADAS. En `stability` conviven
`temporal_column` (entrada) y `partition_column` (derivada) con idéntico aspecto. Clasificar por el
nombre del campo habría fallado en cinco de los 26; van ancladas a mano en el gate.

**D-PRE-4 · El registro tiene test de cobertura, y su alcance es explícito.** Un campo `*_col` /
`*_column` / `*_columns` de una sección **en alcance** que no esté clasificado **rompe el test**. El
alcance de esta enmienda es el camino F1 (las siete secciones de §1.4); `provisioning*`, `survival`,
`markov`, `forward` y `stress` quedan **fuera a propósito** y el test lo declara, para que su
ausencia no se lea como cobertura. Ampliar el alcance es registrar sus campos, no reescribir nada.

**D-PRE-5 · El preflight informa, no bloquea.** No cambia el veredicto de `/run` ni impide correr:
la corrida sigue siendo la autoridad sobre sí misma. Misma semántica que `check_pipeline`, y por el
mismo motivo — una comprobación que tumba a quien la llama es peor que el fallo que reporta.

**D-PRE-6 · `index_col` tiene diagnóstico propio.** Es el único caso donde el desajuste no es un
nombre equivocado sino una imposibilidad de formato: **un CSV no puede transportar un índice
pandas**. Cuando `index_col` está declarado y esa columna existe como columna ordinaria, el
preflight lo dice con esas palabras y nombra las dos salidas que el `ui_help` del campo ya
documenta (declararla en columnas esperadas, o en llaves de unicidad). No se corrige solo: D-PRE-5.

**D-PRE-7 · Paridad UI ↔ código.** Una función pública de Python y un endpoint que la envuelve,
con la misma respuesta por los dos caminos — requisito 1 de la visión, y la regla que D-PIPE-3 ya
fijó para `check_pipeline`.

**D-PRE-8 · Lo que devuelve es copy público.** Cada desajuste viaja con la **ruta del campo en el
config** (`data.partition.strategy.cohort_col`) para que el formulario pueda enfocarlo, y con un
mensaje en español, sin códigos internos. Lo vigilan los gates de copy público ya existentes.

**D-PRE-9 · No se declara compatible lo que no se pudo mirar.** *(Nació al programar.)* El primer
recorrido devolvió `compatible=True` con cero desajustes sobre el caso que sí tenía seis: las
secciones habían llegado **opacas** —`dict`, porque el proceso no había importado la capa— y un
`dict` no tiene `Field` que consultar, así que el recorrido no encontró un solo campo y calló. Es
el mismo defecto que `config_hash` arrastraba hasta `1.8.0`, y se arregla igual (D-HASH-1):
`check_dataset` **coacciona antes de recorrer**, de modo que mira el config *que se ejecutaría*.
Y donde la coacción falla —una sección opaca con un campo que su schema prohíbe, D-HASH-8— el
resultado **no** es `compatible`: esas secciones se publican en `uninspected` y bloquean el
veredicto. La diferencia con `config_hash` es deliberada: allí devolver el config sin coaccionar
es inocuo porque la identidad no ancla ninguna corrida; aquí, decir «compatible» sobre lo que no se
miró es una afirmación falsa a alguien que está por lanzar una corrida.

---

## 3. Contrato

```python
def check_dataset(config: NikodymConfig, columns: Sequence[str]) -> DatasetCheck: ...
```

`DatasetCheck` es aditivo y de lectura (CT-2): `compatible: bool` y `mismatches: tuple[Mismatch, ...]`,
donde cada `Mismatch` lleva `path` (ruta del campo en el config), `declared` (la columna que el
config nombra), `kind` (`missing_column` | `index_not_a_column`) y `message` (el copy en español).

Endpoint espejo: `POST /api/preflight` con `{config, dataset_id}` → el mismo payload. Siempre 200,
igual que `/api/validate`: un config inejecutable es información, no un error de transporte.

---

## 4. Qué NO resuelve esta enmienda

- **No mapea columnas automáticamente.** No adivina que `renta_liquida` es `ingreso_mensual`. Dice
  qué falta y dónde; el usuario decide. Un mapeo asistido es una capacidad mayor y separada.
- **No cambia los presets.** Siguen acoplados a la forma física de su dataset del catálogo, que es
  correcto para lo que son: configs curados listos para correr **sobre ese dataset**.
- **No cierra B2.** El criterio sigue exigiendo que un tercero sin checkout repita el recorrido.
  Esta enmienda quita el obstáculo medido en el camino; no sustituye al testigo.

## 5. Estrategia de tests

- El caso medido en §1.2 como test de extremo a extremo: config del preset F1 + las columnas del
  CSV de nombres propios → **los seis** desajustes en **una** llamada, con sus rutas.
- El control negativo que importa: el config del preset F1 contra las columnas de **su** dataset →
  `compatible=True`, `mismatches=()`. Sin él, un preflight que acusara siempre pasaría el positivo.
- Las columnas DERIVADAS **no** se reportan: test explícito de que `score_column`, `pd_column`,
  `partition_column` y `data.target.target_col` no aparecen como faltantes (D-PRE-3).
- Cobertura del registro (D-PRE-4): recorrer los campos de las siete secciones en alcance y exigir
  que todos estén clasificados. El test se prueba **inyectando** un campo sin clasificar y
  verificando que falla — un gate que declara barrer una clase se prueba inyectando.
- `index_col` (D-PRE-6) en sus dos sentidos: presente como columna ordinaria → se reporta con su
  diagnóstico propio; presente como índice del parquet → no se reporta.
