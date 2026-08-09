# Enmienda — la severidad del método interno se puede MODELAR, no sólo leer

> Estado canónico: **APROBADA E IMPLEMENTADA** (2026-08-07). El texto conserva la propuesta v2 y
> sus costes históricos; para estado y correcciones posteriores manda
> [`DECISIONES-VIGENTES.md`](DECISIONES-VIGENTES.md), §D-LGD.
>
> 🔴 Corrección posterior: el abanico **conservó `options`**. La prescripción histórica de migrarlo
> a `answer_forms` quedó descartada al medir porque convertía una elección metodológica en respuesta
> obligatoria; se corrigieron los oráculos de uniones.
>
> v2 incorpora la revisión adversarial: **cuatro roturas de gate que v1 no vio**, una afirmación
> falsa sobre `src/`, un mecanismo inventado y una alarma de CI mal calibrada. Todas verificadas a
> mano contra el código antes de aceptarlas.
> Detonante: P4 del roadmap («LGD modelada»), único nodo abierto tras el release `1.11.0`.
> Decisiones: **D-LGD-1 … D-LGD-15**.
> Enmienda a: **D-JOB-11** (`_SDD-UI-POR-TRABAJOS.md` §3 y su tabla), **SDD-28 §5.1**
> (`InternalLgdConfig`) y **SDD-16 §3/§7** (`LgdEngine` y sus columnas convencionales de `workout`).
> Alcance decidido por Cami al abrir: **las dos regresiones + `workout`**, **sin covariables WoE**,
> y el motor de LGD **se eleva** a nivel compartido.

---

## 1. Problema

`provisioning_internal` calcula `provisión = Exposición · PD · LGD` por grupo homogéneo. La PD puede
venir de un modelo —entra como artefacto de otro paso— pero **la severidad sólo puede leerse de una
columna del archivo**: `InternalLgdMethod = Literal["provided", "group_historical"]`
(`internal/config.py:31`), y las dos ramas leen el mismo `lgd_col`; lo único que las separa es cómo
se agrega el grupo, como el catálogo ya explica bien (`ui/jobs.py:1938-1974`).

O sea: el motor sabe **modelar** un factor de la pérdida esperada y **no sabe modelar** el otro,
aunque el modelo exista, esté probado y corra en producción dentro del otro motor de provisiones.

El catálogo lo declara con todas las letras. El trabajo `lgd_modelada` existe, está en
`unavailable`, y su `unavailable_reason` (`ui/jobs.py:448-451`) dice: *«El motor de LGD ya modela
por regresión, pero el método interno todavía no puede delegar en él: sólo admite la LGD dada o el
promedio por grupo.»*

---

## 2. Lo que la medición corrigió

### 2.1 🔴 «Es cambio de DAG» — falso para la capacidad base

El `HANDOFF` afirma: *«el step no pide el artefacto de binning, así que las columnas WoE no llegan —
es cambio de DAG, no un parámetro»*. El dato es cierto; la conclusión no se sigue.

`LgdEngine` no consume ningún artefacto de binning **hoy tampoco**. En IFRS 9 se le llama con el
`frame` crudo: `LgdEngine.from_config(...).estimate(frame, eir=...)` (`ifrs9/engine.py:409`), donde
`frame` es la copia defensiva de `("data","frame")` (`ifrs9/engine.py:259` ← `ifrs9/step.py:101-105`).
Y `provisioning_internal` **ya exige exactamente ese artefacto** (`internal/step.py:199-201`).

⇒ **La capacidad base entra con CERO cambio de DAG.**

### 2.2 🔴 «`Decimal` contra `float64`» — el puente ya existe y está en producción

El motor interno es todo `Decimal` con `prec=50` (`internal/engine.py:90`) y `LgdEngine` devuelve
`float64` (`lgd.py:216`, coaccionado en `:207`). Pero **la PD ya cruza esa frontera**: `_pd_by_row`
(`internal/engine.py:213-249`) sólo hace `.to_dict()`, sin convertir nada, y la conversión ocurre en
`_parse_rows` al aplicar `_decimal_or_none` sobre `pd_by_row[label]` (`:288`).

Sonda ejecutada: `np.float64(0.3) → Decimal('0.3')`, `np.float64(1/3) → Decimal('0.3333333333333333')`.
⇒ **No hay problema que resolver: hay un precedente que seguir.**

### 2.3 🔴 Lo caro es la IDENTIDAD — y el riesgo NO es «el CI se queda verde»

Añadir campos a `InternalLgdConfig` mueve el `config_hash` de dos presets. Medido inyectando un
campo de verdad y revirtiendo:

| preset | antes | con un campo nuevo | ancla viva en tests |
|---|---|---|---|
| `f1-estandar-consumo` | `ec10eb43` | `ec10eb43` (sección `None`) | `test_ui_presets.py:52` |
| `f3-provisiones-consumo` | `857b06ee` | **`31980950`** 🔴 | `test_ui_presets.py:246` |
| `f4-ifrs9-retail` | `013e69dc` | `013e69dc` (sección `None`) | `test_ui_presets.py:308` |
| `f5-provision-interna-generica` | `b36318b5` | **`43b4e95c`** 🔴 | **ninguna** |

⚠️ **Corrección a v1, que exageraba.** v1 decía «el CI seguiría verde». Es falso: `test_ui_presets.py:262`
se pone **rojo de inmediato** al mover F3. El riesgo real es de **segundo orden y por eso es peor**:
re-anclar ese test es el gesto normal y correcto cuando un default cambia legítimamente, y hecho eso
**nada vuelve a mirar la demo**. `857b06ee` está impreso dentro de `web/src/fixtures/demo/results.json`,
`preset.json` y `report.html`, y **ningún gate cruza el fixture de la demo con el preset vivo** —
verificado—. La demo quedaría publicando un `config_hash` que el preset ya no produce, que es la
clase del lineage que decía `nikodym 1.8.0`. Y recapturar está vetado en esta sesión.

⚠️ Segunda corrección: **F5 no tiene ancla ni aparece en la demo**, así que la única fila que sí se
movería en silencio es la que v1 usaba como daño colateral, no como argumento.

**Salida medida**: la unión discriminada es **hash-neutral**. Sonda con la tercera rama añadida de
verdad —no simulada—: los cuatro presets **byte a byte iguales** (`ec10eb43`, `857b06ee`, `013e69dc`,
`b36318b5`). Es el mismo hecho que D-COL midió para `PartitionStrategy`, ahora medido en esta clase.

### 2.4 ⚠️ «`LgdEngine` admite covariables WoE sin modificarlo» (D-JOB-11) — cierto en la firma, falso en el frame

`covariate_cols` acepta cualquier nombre, pero los nombres deben existir en el frame que recibe, y
ese frame no tiene columnas WoE. Además `("binning","woe_frame")` cubre sólo las tres particiones
modelables (`binning/step.py:56`, `:133`), no la cartera entera que se provisiona.

⚠️ Y un matiz que v1 sobrevendió: la nota «son columnas **CRUDAS**, no WoE» vive en un **comentario
`#`** (`ifrs9/config.py:232-236`), **no** en el `description` del campo (`:229`) ni en ningún
`ui_help`. Quien usa el formulario **no la lee**. Eso es copy a cerrar, no evidencia a citar
(D-LGD-7).

---

## 3. Lo que NO se propone

- **No se toca el cálculo de IFRS 9.** Ni un número suyo cambia; se comprueba con sus goldens.
- **No se duplica matemática.** El repo ya pagó esa clase con `TEMPORAL_CANDIDATE_NAMES` triplicada.
- **No se abre la regla del máximo**, ni se toca el motor CMF, ni se re-litiga el veredicto D-JUR.
- **No se mueve ningún `config_hash`** — exigencia, no consecuencia (§2.3).
- **No se recaptura la demo.**
- **No se ofrecen covariables WoE** (D-LGD-7).

---

## 4. Decisiones

### D-LGD-1 — la LGD del método interno se contesta ELIGIENDO UNA FORMA

`InternalLgdConfig` deja de ser una clase plana con un `method` dentro y pasa a ser una **unión
discriminada por `method`**, en el molde de `PartitionStrategy` (`data/config.py:852-855`) y por la
razón de D-COL-6: *una decisión metodológica se contesta eligiendo una forma, y cada forma trae sus
propios huecos*.

Las dos ramas existentes conservan **exactamente** sus cuatro campos actuales, byte a byte, que es
lo que preserva la identidad (§2.3). Las ramas nuevas traen lo suyo y **sólo lo paga quien las
elige**.

⚠️ Efecto lateral que vale por sí solo: **cierra estructuralmente la clase «campo declarado en rama
inactiva»** para el eje del método. Con una clase plana, `covariate_cols`, `recovery_col`,
`workout_discount` y los cuatro nombres de columna de `workout` serían **siete campos visibles e
inertes** para quien eligió `provided`. Con la unión no existen en ese config.

⚠️ **Corrección a v1, que afirmaba «cero en `src/`» y era falso.** `InternalLgdConfig` se usa como
constructor en **8 sitios de tests** (`test_internal_provisioning_config.py:39,104,106,108,110,112`
y `test_internal_provisioning_engine.py:409,422`) **y en uno de `src/`**:
`internal/config.py:227`, `default_factory=InternalLgdConfig`. Un `Annotated[...]` no es invocable,
así que ese sitio **rompe al importar el módulo** si no se cambia a la rama concreta. Y el nombre
está en `__all__` en dos sitios (`internal/config.py:38`, `internal/__init__.py:29,79`): la
conversión a alias **cambia API pública** y va con su nota en el CHANGELOG.

### D-LGD-1-bis — la unión NO es un cambio local: arrastra cuatro superficies, todas con precedente vivo

Ésta es la corrección más importante de v2. Convertir `lgd` en unión lo saca de «un grupo de cuatro
campos del formulario» y lo mete en la maquinaria de formas de respuesta. Las cuatro, medidas:

1. 🔴 **El punto del abanico migra de `options` a `answer_forms`.** `_campo_del_path`
   (`test_jobs_abanico.py:71-83`) se queda con **la primera rama** de una unión, así que
   `provisioning_internal.lgd.method` resolvería a `Literal["provided"]` —un solo valor— contra un
   catálogo con varios ⇒ el gate de igualdad (`:159`) **rojo**; y `_puntos_del_motor` (`:98-109`)
   exige `len(valores) > 1`, así que el path **desaparece** del oráculo independiente. El precedente
   lo demuestra: `data.partition.strategy` **no** declara `.type` en `options`, declara la unión
   entera con `answer_forms` (`ui/jobs.py:623-631`).
2. 🔴 **Hay que quitar `ui_widget: "section"` del campo `lgd`** (`internal/config.py:230`). En
   `form-engine.ts` el `if (override) return override` de `:507` **precede** al bloque de unión
   discriminada de `:515-517`, y `section → group` sobre una unión no encuentra `properties`: pinta
   el fieldset «Sin campos.», que es el defecto que el propio archivo documenta en `:485-490` para
   `binning.variable_overrides`. `PartitionConfig.strategy` funciona porque **declara `ui_help` y
   ningún `ui_widget`** (`data/config.py:862-870`) — verificado. Quitar un `json_schema_extra` **no
   mueve el `config_hash`** (es metadato de schema, no valor), pero sí obliga a regenerar el fixture
   y el bundle.
3. ⚠️ **`effective_defaults` colapsa las cuatro hojas.** `_submodelo_directo`
   (`effective_defaults.py:114-129`) devuelve `None` ante una unión multi-rama —su docstring lo dice
   literalmente— y `_mapa_de_modelo` la publica entonces como **descriptor**. `HOJAS_DEL_FORMULARIO`
   (396) y `DESCRIPTORES_TOTALES` (1042, `test_effective_defaults.py:54`, `:87`) se mueven **por el
   colapso**, no sólo por los campos nuevos. Es exactamente el caso en que un golden puede tragarse
   una pérdida en silencio (la lección de los 28 campos de D-OBL-2): el número nuevo se justifica
   enumerando, no ajustando.
4. ⚠️ **`test_jobs_formas_de_respuesta.py:302` ancla `con_ramas == 1`** con el mensaje *«sólo
   `data.partition.strategy` es hoy una unión discriminada»*. Deja de ser cierto en cuanto `lgd` sea
   decisión con formas, y el gate se actualiza **enumerando las dos**, nunca subiendo el número.

**Nada de esto es territorio desconocido**: las cuatro superficies tienen precedente vivo en
`data.partition.strategy`. Es más trabajo del que v1 estimó, no trabajo de riesgo desconocido.

### D-LGD-2 — `LgdEngine` se eleva a `provisioning/lgd.py`

Hoy vive en `provisioning/ifrs9/lgd.py` y se exporta en `ifrs9.__all__` (`ifrs9/__init__.py:40,86`).
Que el motor neutro dependa del paquete de una norma contable concreta es el acoplamiento
equivocado. Se mueve al nivel compartido con **re-export desde `ifrs9`** para no romper API pública.

⚠️ **Corrección a v1, que llamó «mecánico» al movimiento contando instanciaciones.** Se instancia en
un sitio (`ifrs9/engine.py:409`), pero `tests/unit/test_ifrs9_lgd.py:20` importa **el módulo**
(`import nikodym.provisioning.ifrs9.lgd as lgd_module`) y parchea `lgd_module._import_beta_model` /
`_import_statsmodels` / `lgd_module.importlib` en **seis sitios** (`:329,358,380,386,392,400`). Un
re-export de la *clase* no preserva la ruta del *módulo*: esos seis monkeypatches se reapuntan.

### D-LGD-3 — las columnas de `workout` dejan de ser constantes de módulo y las declara el config

`workout` está **en alcance** por decisión de Cami. Hoy el motor lee cuatro columnas por **nombre
fijo**: `ead`, `recovery_cost`, `recovery_time_years`, `contractual_rate` (`lgd.py:63-66`). Eso
colisiona con el método interno, cuya exposición es configurable (`exposure_col`, default
`exposure_amount`): exigir además una columna literalmente llamada `ead` obliga a duplicar el mismo
dato bajo dos nombres, que es una mentira del config esperando a ocurrir.

El motor pasa a **pedirle los nombres a su config**, y así se preserva la identidad:

- **`IfrsLgdConfig` los expone como `@property`, no como campos.** Sonda: una `@property` sobre
  `NikodymBaseConfig` **no entra al `model_dump`** ⇒ `013e69dc` no se mueve y IFRS 9 se comporta
  igual. Verificado además que **ningún gate exige que todo atributo de un config sea un campo**
  (`test_config_schema.py:112` sólo exige `title` sobre `model_fields`).
- **La rama `workout` del método interno los declara como campos suyos**, configurables, con su
  `column_role`. Hash-neutral por D-LGD-1.

⚠️ **Límite declarado, corrigiendo el «Riesgo 4» de v1, que lo daba por general**: `_declaraciones`
(`core/dataset_check.py:576-587`) recorre `model_fields`, y una `@property` no es un campo ⇒ **las
cuatro columnas de `workout` en IFRS 9 siguen con cero cobertura de preflight, igual que hoy**. La
mejora del preflight vale **sólo** para la rama del método interno. Cerrarlo también en IFRS 9
exigiría convertirlas en campos, y eso **sí** movería `013e69dc`: queda fuera de alcance, escrito.

La tasa de descuento sigue el mismo criterio: `workout_discount='eir'` recibe la serie por parámetro
(`lgd.py:169-177`), y como el método interno **no tiene ningún concepto de EIR**, su rama `workout`
declara el nombre de la columna de la que sale.

### D-LGD-4 — la severidad modelada entra por la puerta de la PD, no mutando el frame

`_calculate` resuelve `pd_by_row` (`internal/engine.py:185`) y acto seguido `_parse_rows` (`:186`).
La severidad modelada entra como **`severity_by_row`, hermano exacto de `pd_by_row`**: `None` en las
ramas observadas y un mapa por etiqueta de índice en las modeladas. El frame **no se muta**
(contrato de `LgdEngine`, `lgd.py:19-20`).

⚠️ **Corrección a v1, que se contradecía a sí misma.** v1 decía «`_parse_rows` sin tocar» en §5
mientras D-LGD-4 le añadía un parámetro. `_parse_rows` **sí cambia**, y por dos razones medidas:

1. Accede **incondicionalmente** a `.lgd_col`, `.lgd_floor` y `.lgd_cap` (`internal/engine.py:261`,
   `:266-267`). Con `strict = true` en todo el paquete (`pyproject.toml:235`), mypy sólo lo acepta
   si **todas** las ramas declaran los tres. ⇒ los tres viven en la base común de la unión, no en
   las ramas: toda rama tiene objetivo, piso y techo. Es coherente, no un parche.
2. `required = [..., severity_col]` con `_require_columns` (`:262-264`) exigiría `lgd_col` en el
   archivo **incluso con la severidad modelada** — y en la rama `workout` el objetivo no es `lgd_col`
   sino los flujos de recupero. La exigencia de columnas pasa a derivarse de la rama.

### D-LGD-5 — la conversión a `Decimal` es la que ya usa la PD, sin canal nuevo

`_decimal_or_none`, misma función y misma semántica (§2.2). Un test lo ancla en los dos sentidos:
mismo valor por columna y por modelo ⇒ misma provisión al último decimal.

### D-LGD-6 — el piso y el techo se aplican una vez, y su re-aplicación es idempotente

`LgdEngine._finalize` (`lgd.py:205-216`) valida rango y aplica `lgd_floor`/`lgd_cap`; `_parse_rows`
(`:312-313`) los re-aplica con los **mismos** valores, de la misma rama. `min(max(x,f),c)` sobre un
`x` ya acotado es la identidad. La idempotencia queda con test explícito, no con un comentario.

### D-LGD-7 — sin covariables WoE, y la razón se declara donde el usuario la lee

**Decisión de Cami.** Dos razones medidas, y la primera es metodológica:

1. **El WoE es una codificación supervisada contra el target de INCUMPLIMIENTO.** Usarla como
   covariable de la severidad —otro target, condicional a haber incumplido— importa la supervisión
   del target de PD dentro del modelo de LGD. Es un defecto de método, y este motor existe para que
   un regulador lo lea.
2. **La cobertura de filas no cuadra**: `woe_frame` sólo trae desarrollo/holdout/OOT.

🔴 **Y esto obliga a corregir copy ya publicado.** La descripción del trabajo `lgd_modelada`
(`ui/jobs.py:417-418`) dice *«Modelar la severidad con **las mismas variables discretizadas del
scorecard**…»* y declara `binning` en sus secciones (`:420`). Es exactamente la promesa que el
alcance elegido **no** cumple. Se corrige la descripción y **sale `binning`**: el trabajo no lo
necesita —la PD entra como artefacto externo— y dejarlo es prometer la covariable WoE por la puerta
de atrás.

⚠️ Y el límite se escribe en el **`description` del campo**, no en un comentario `#`: hoy la única
nota que dice «columnas crudas, no WoE» vive donde el usuario no la ve (§2.4).

### D-LGD-8 — `fail_on_falta_dato` NO gobierna el ajuste, y se dice

Con la severidad leída, un hueco se rige por el flag (`internal/engine.py:394-401`). Con la
severidad **modelada**, un hueco en el objetivo o en una covariable **detiene siempre**. No es
omisión: imputar cero en una covariable **sesga el ajuste en silencio** y contamina a todas las
filas, no sólo a la que tenía el hueco. Es la regla que CRP-5 ya fijó en este mismo motor
(`lgd.py:143-150`). Se declara en la ayuda del campo y en la prosa del informe.

### D-LGD-9 — el ajuste es in-sample y el documento lo dice

`LgdEngine` ajusta y predice sobre las mismas filas (`lgd.py:179-188`). Es propiedad
**preexistente** —IFRS 9 la tiene hoy— pero vivía donde nadie la leía. Al ofrecerla en el motor que
produce el número de provisión, se publica en la prosa y en la traza de auditoría.

### D-LGD-10 — el informe dice qué método de LGD se usó (cierra un defecto preexistente)

`report/prose.py:1817-1861` publica la fuente de la PD y la agrupación con sus dos diccionarios de
etiquetas, y **no dice nada del método de LGD** —`grep -n "lgd" report/prose.py` da **cero
coincidencias**— aunque la card lo publique desde siempre (`internal/engine.py:831`, `:892`). Hoy el
daño es menor porque las dos ramas leen la misma columna. **Con severidad modelada, el documento que
lee un regulador no diría que la LGD salió de una regresión ajustada sobre esa misma cartera.**

### D-LGD-11 — el abanico declara su estado a mano, y el extra se resuelve por composición

⚠️ **Corrección a v1, que inventó un mecanismo.** v1 decía que el estado se computa con `find_spec`
«sin mecanismo nuevo». Falso: `find_spec` aparece **una sola vez en todo `src/nikodym`**
(`report/exports.py:219`) y **cero veces** en `ui/jobs.py`; `_ESTADOS_DE_OPCION` (`ui/jobs.py:788`)
son tres literales declarados a mano, y su comentario de cabecera (`:764-769`) advierte que afirmar
disponibilidad desde el catálogo sería «el error de categoría que D-PRE-1 existe para impedir».

Lo que resuelve el caso sin mecanismo nuevo **es la composición de extras**: `ui` compone
`nikodym[scoring]` (`pyproject.toml:124`) y `scoring` trae `statsmodels>=0.14` (`:73-75`). ⇒ **quien
tiene el formulario tiene statsmodels por construcción**, así que las dos regresiones se declaran
`_DISPONIBLE` sin afirmar nada que el catálogo no pueda saber. Por la ruta de código sin el extra,
`LgdEngine` ya levanta `MissingDependencyError` con mensaje accionable (`lgd.py:70-73`). El gate lo
ancla en los dos sentidos.

### D-LGD-12 — el gate de aceptación es una CORRIDA con la rama modelada, no la resolución del pipeline

⚠️ **Corrección a v1**, que proponía como gate que `lgd_modelada` pasara a `available`. Insuficiente:
`test_jobs_ejecutables.py:12-15` declara en su propio docstring que mide *«que el pipeline resuelva,
no que la corrida termine bien»*, y arma el esqueleto desde `build_effective_defaults()`, o sea con
`method="provided"`. El trabajo se pondría verde **sin ejercitar una sola vez una rama modelada**.

El gate de aceptación es: **una corrida end-to-end que llega a `done` con `method` modelado**,
produciendo su informe, con la provisión comparada contra el mismo dato por la rama observada. Que
`lgd_modelada` pase a `available` es consecuencia, no criterio.

### D-LGD-13 — los campos de columna nuevos declaran `column_role`, y su rama declara `columnas_inactivas()`

⚠️ **Corrección a v1, que decía «no lo cubriría ningún gate» y era falso.** `provisioning_internal`
sí está cubierto por dos gates derivados de `test_column_roles.py` (`:204` navegabilidad, `:246-278`
footprint, que lo lista a mano) y por el de multiselect de texto libre. Lo que **sí** queda fuera es
el criterio por sufijo `*_col*`, porque las cuatro secciones de provisiones están deliberadamente
fuera de `SECCIONES_EN_ALCANCE` (`test_column_roles.py:57-72`, razón escrita en `:57-62` — v1 citó
`:20-45`, que es la cola del docstring).

Los campos de columna de las ramas nuevas declaran `column_role: "input"`, y cada rama implementa
`columnas_inactivas()` en el molde de `IfrsLgdConfig` (`ifrs9/config.py:271-289`) para el único
condicional que sobrevive dentro de una rama: `lgd_col` es inerte cuando `recovery_col` está
informada. ✅ Verificado que el mecanismo es transparente a la unión: `dataset_check.py:576-591` y
`:610-645` recorren **instancias**, no anotaciones.

### D-LGD-14 — `provisioning/lgd.py` entra al gate de cobertura regulatoria

Medido: `ifrs9/lgd.py` **no está hoy** en `REGULATORY_COVERAGE_PATHS` (`testing/regulatory.py:21-40`,
que incluye `ifrs9/__init__.py` y **todo** `provisioning/internal/`). Así que moverlo no pierde
cobertura — **pero crea una obligación nueva**: el módulo pasa a producir la severidad de una cifra
contable cuyo paquete está al 100 % precisamente porque *«una rama sin cubrir es una provisión sin
verificar»* (`regulatory.py:33-35`). Entra al gate. ⚠️ La lista está **duplicada** en
`tests/unit/test_hito0_contracts.py:329` (`_EXPECTED_REGULATORY_PATHS`): son dos sitios.

### D-LGD-15 — `fractional_response` es el que corresponde al dato, y el copy lo dice

`beta_regression` exige el objetivo **estrictamente** en `(0, 1)` (`lgd.py:198-200`) y la LGD es
bimodal, con masa real en 0 (recupero total) y en 1 (pérdida total) — la propiedad que el docstring
del motor declara desde siempre (`lgd.py:3-4`). El motor rechaza con error nombrado en vez de clipar,
que es correcto, pero significa que en la mayoría de las carteras **beta muere en la entrada**. El
`help` de la opción lo dice; no se deja al azar de quién elija primero.

---

## 5. Coste medido (v2 — v1 lo subestimaba)

| superficie | qué cambia | nota |
|---|---|---|
| `provisioning/lgd.py` | motor movido + nombres de workout desde config | +6 monkeypatches reapuntados |
| `ifrs9/config.py` | 4 `@property`, cero campos | `013e69dc` no se mueve (sonda) |
| `internal/config.py` | unión discriminada + ramas + quitar `ui_widget:"section"` | hashes no se mueven (sonda) |
| `internal/engine.py` | `severity_by_row`; `_parse_rows` **sí cambia** | mypy strict + columnas por rama |
| `ui/jobs.py` | `options` → `answer_forms`; copy de `lgd_modelada`; opciones nuevas | 🔴 el grueso del trabajo |
| `web/src/lib/` + form-engine | render de la unión (precedente vivo) | fixture + bundle |
| `report/prose.py` | etiquetas del método de LGD | defecto preexistente |
| `testing/regulatory.py` + `test_hito0_contracts.py` | ruta nueva al 100 % | dos sitios |
| goldens | `HOJAS_DEL_FORMULARIO` 396, `DESCRIPTORES_TOTALES` 1042 | se mueven **por el colapso**, se enumeran |
| tests | 8 sitios de construcción + `default_factory` + suites nuevas | API pública en el CHANGELOG |

**No se mueve**: ningún `config_hash`, ningún resultado de IFRS 9, ninguna demo, ningún preset.

---

## 6. Riesgos declarados

1. **El ajuste es in-sample** (D-LGD-9). Se declara, no se resuelve.
2. **`beta_regression` muere ante masas en 0/1** (D-LGD-15).
3. **Un ajuste que no converge detiene la corrida** (`lgd.py:260-265`). Correcto; se declara.
4. **La rama `workout` exige cuatro columnas más**; se señala en el preflight **sólo en el método
   interno**, no en IFRS 9 (D-LGD-3).
5. **El grueso del coste está en el catálogo y el formulario, no en el motor.** Si Cami prefiere
   pagar identidad en vez de maquinaria, la alternativa es la clase plana: 3 anclas re-ancladas, la
   demo stale, siete campos inertes y el `config_hash` de todo usuario de `provisioning_internal`
   movido. **No se recomienda**, y la razón es la regla del camino largo.

---

## 7. Plan de ejecución

1. D-LGD-2 + D-LGD-14 (mover el motor, re-export, monkeypatches, gate regulatorio) — goldens de
   IFRS 9 verdes antes y después.
2. D-LGD-3 (nombres de workout desde config, `@property`) — sonda de `013e69dc` como control negativo.
3. D-LGD-1 + D-LGD-1-bis **sin ramas nuevas todavía**: unión de dos ramas idénticas a hoy, quitar
   `ui_widget`, migrar el abanico a `answer_forms`, actualizar los cuatro goldens **enumerando**.
   Los cuatro `config_hash` son el control negativo **antes** de añadir nada.
4. Ramas nuevas + D-LGD-4/5/6/8/13/15.
5. D-LGD-10 (informe) y D-LGD-7/11/12 (copy, abanico y la corrida de aceptación).
6. Fixtures, bundle y gates.

Cada paso con su control negativo **ejecutado**, no descrito.
