# Enmienda SDD — paridad 1:1 Python ↔ interfaz, secuenciada (objetivo de roadmap)

> **Estado: PROPUESTA, pendiente de revisión adversarial y del OK de Cami.** Diseño sin código
> (S6). Nace de la decisión 2 de Cami del 2026-09-09: «paridad 1:1 Python ↔ interfaz,
> secuenciada: primero lo que completa el scorecard, luego ML/tuning/explain, al final forward,
> Markov y stress». Fija el **objetivo**, el **criterio de entregado**, el **orden** y las
> **condiciones de entrada** de cada bloque; **no** es el SDD de ningún bloque: cada uno exige su
> propia enmienda medida antes de programar (AGENTS.md).
>
> **Base medida:** `main` = `40cb5a3da0d5483be0fcf328beb14796d6025a99` (1.12.0). **Autor /
> Fecha:** Claude Code / 2026-09-09.
>
> **Enmienda a:** [`../ROADMAP.md`](../ROADMAP.md) (§Estado, §B4 «Rutas de uso para F5/F6», §F2,
> §F5, §F6, §F7 DoD), [`_SDD-UI-POR-TRABAJOS.md`](_SDD-UI-POR-TRABAJOS.md) §4 (D-JOB-13 `stress`
> «a medir»), SDD-23 §3 (secciones), SDD-26 §5 (capítulos que faltan), SDD-25 (composición del
> extra `[ui]`).
>
> **No toca:** ningún motor, el `config_hash`, D-JUR, D-GOB, D-EST (ninguna marca de estabilidad
> se mueve), el arnés H9R. **No autoriza** programar ningún bloque, ni bump, tag, PyPI o recaptura.

| Campo | Valor |
|---|---|
| **Enmienda** | PARIDAD-1-1 (D-PAR-1…D-PAR-9) |
| **Módulos** | roadmap y contrato de entrega; toca `nikodym.ui`, `web/`, `report`, `docs_site/` **por bloques**, cada uno con su enmienda |
| **Fase** | F7 (UI) sobre F1, F2, F5, F6 |
| **Depende de** | [`_ENMIENDA-SCORECARD-COMPLETO.md`](_ENMIENDA-SCORECARD-COMPLETO.md) (bloque A), D-JOB-1…19, D-EJE, D-OBL, D-EXI, D-ABA-5/7/8, D-PUE (puerta de artefactos por HTTP), D-FX-8 (esqueleto) |
| **Lo consumen** | «Empezar» (catálogo), README y portada (tabla «Superficie»), el extra `[ui]`, la demo |
| **Release** | Cada bloque entregado es un **minor** con su CHANGELOG. Este documento no cambia ninguna versión |

## 0. Qué corrige de lo ya escrito

1. **Los conteos del HANDOFF («257 campos hoja») dependen del contador.** Medido con dos
   convenciones (§1.1): por `Field(` menos contenedores, los ocho suman **255** (o **233** si la
   unión de hiperparámetros de `ml` cuenta como un control; **257** era «`ml` = 28» por la primera
   rama de la unión); por el barrido del gate de copy del formulario sobre el schema completo
   —que es lo que `test_copy_del_formulario` medirá cuando entren—, suman **293 rutas** (listas y
   filas incluidas). Aquí se usan las dos y se dice cuál es cuál.
2. **«Lo que les falta es superficie, no aritmética» (portada) es cierto para cinco de los ocho y
   sólo a medias para tres.** `forward`, `markov` y `stress` no tienen **datos con los que
   correr** en el paquete: ningún dataset sintético trae serie macro ni panel longitudinal
   (`ui/datasets.py:80-93,163-292`: una fila por operación, sin columna de estado ni repetición
   temporal; `as_of_date` es un único corte). Sin insumo no hay preset, y sin preset no hay
   ejemplo ejecutable (ROADMAP §B4). El bloque C empieza por los datos, no por el formulario.
3. **`ml`, `tuning` y `explain` no tienen ni una línea en `nikodym.report`** (0 menciones fuera de
   un comentario). SDD-26 §5 no los contempla; el DoD de F2 («SHAP integrado al reporte») nunca se
   ejecutó. Entregarlos exige una enmienda a SDD-26, no sólo un panel.
4. **El extra `[ui]` promete «todo lo que su formulario puede ejecutar»** (`getting-started.md:229`,
   `pyproject.toml:121-123`) y un gate lo hace cumplir (`test_extra_ui_cubre_el_formulario.py`):
   prohíbe que `[ui]` arrastre `ml`, `tuning`, `explain`, `markov` y `forecasting` **mientras no
   estén en el formulario**, y exige declarar el extra de toda sección nueva. Meter `ml` en el
   formulario mueve, por contrato, la composición de `[ui]` (o cambia el contrato): es una
   decisión de producto (§8-2), no un detalle.

## 1. El estado, medido sobre `40cb5a3`

### 1.1 Los ocho dominios fuera del formulario

| Dominio | Hojas (`Field` − contenedores) | Rutas (barrido del gate) | `ui_*` | Requeridos sin default | Extra(s) | SemVer | Orden DAG | `requires` | Serializer | Panel | Informe | Trabajo | Preset | Dataset que sirve | Guía |
|---|---:|---:|---|---:|---|---|---:|---|---|---|---|---|---|---|---|
| `eda` | 17 | 17 | 100 % | 0 | — | **estable** | 3 | estático (`data.frame`, `data.labels`) | no | no | subsección `context.eda` cuando hay card | no | apagado | los 6 (con la regla D-SC-2) | no |
| `validation` | 32 | 33 | 100 % | 0 | `scoring` (en `[ui]`) | experimental | 21 | dinámico por familias | no | no | capítulo «Validación formal» | no (D-JOB-18) | **F1, F5** | los F1 | no |
| `ml` | 25 + 25 (5 backends) | 52 | 100 % | 0 | `ml` + `xgboost`/`lightgbm`/`catboost` por backend | experimental | 10 | dinámico (`feature_source`, `monotonic`) | no | no | **nada** | no | apagado | los F1 | no |
| `tuning` | 16 | 13 | 100 % | 0 | `tuning` (optuna) | experimental | 9 | dinámico, contextual (`from_config_with_context`); hereda `backend`/`feature_source` de `ml` | no | no | **nada** | no | apagado | los F1 | no |
| `explain` | 29 | 27 | 100 % | 0 | `ml` + `explain` (shap, numba, llvmlite, matplotlib) | experimental | 11 | dinámico (`targets`, `feature_source`) | no | no | **nada** | no | apagado | los F1 | no |
| `forward` | 48 | 53 | 100 % | **7** (`input`, `satellite`, `macro_source`, `variable_cols`, `factor_cols`, `scenarios[].name/.weight`); `ForwardConfig()` no construye | base + `forecasting` (statsmodels, pmdarima) | experimental | 13 | dinámico (`term_structure_sources` + macro `artifact`) | no | no | título en `DOMAIN_TITLES` y Anexo C; sin capítulo | no | apagado | **ninguno** (sin serie macro) | no |
| `markov` | 27 | 29 | 100 % | **4** (`id_col`, `time_col`, `state_col`, `states`; con placeholders) | base + `markov` (scipy, sólo embedding) | experimental | 2 | estático (`data.frame`) | no | no | título y Anexo C; sin capítulo | no | apagado | **ninguno** (sin panel id × tiempo × estado) | no |
| `stress` | 60 | 69 | 100 % | **13** (`StressConfig()` construye y el validador la rechaza vacía) | ninguno | experimental | 14 | dinámico: 5 claves de `forward` + motor ECL si hay métricas económicas | no | no | **ausente** de `report/` | «Stress testing», `unavailable`, `missing_sections=[stress]` | apagado | ninguno (depende de `forward`) | no |

Las 15 secciones del formulario (`web/src/lib/schema.ts:88-181`) tienen las seis superficies; las
ocho de arriba tienen la primera a medias (metadatos `ui_*` al 100 %, formulario no) y ninguna
de las otras cinco, salvo `validation` (capítulo y preset) y `eda` (subsección).

### 1.2 Lo que hoy dice el copy público, literal

| Superficie | Frase | Archivo:línea |
|---|---|---|
| README | fila «**Stress testing** … \| Python \| experimental» | `README.md:37` |
| README | fila «**Markov** … \| Python \| experimental» | `README.md:38` |
| README | fila «**Forward-looking** … \| Python \| experimental» | `README.md:39` |
| README | «**Backends ML (F2)**: XGBoost, LightGBM, CatBoost y tuning (Optuna) como *extras* selectivos, con explicabilidad (SHAP) opcional.» (sin columna de superficie) | `README.md:42-43` |
| README | «Lo que los separa no es "hecho / no hecho", sino **superficie** (¿tiene UI, preset y capítulo en el informe, o hay que escribir el config en Python?)» | `README.md:25-27` |
| Portada | «**solo el scorecard y las provisiones tienen UI, preset y capítulo propio en el informe** … **Stress, Markov y forward-looking se usan escribiendo el config en Python: el comando `nikodym-ui` levanta la interfaz y no los corre.** Lo que les falta es superficie, no aritmética.» | `docs_site/index.md:18-24` |
| «Empezar» | fila «**Stress testing** \| … Hoy sólo por código: el motor corre desde Python y todavía no tiene pantalla.» (gateada por `list_jobs()`) | `docs_site/getting-started.md:203` |
| «Empezar» | «`[ui]` trae lo que el formulario puede ejecutar» | `getting-started.md:229-230` |
| ROADMAP | «F5/F6 · forward, survival, Markov, stress y validación \| Implementado, experimental \| … forward, Markov y stress se usan por config Python» | `ROADMAP.md:31` |
| ROADMAP | B4: «necesitan al menos **un preset documentado y un ejemplo ejecutable por capacidad** —no necesariamente una UI completa—» | `ROADMAP.md:502-508` |
| ROADMAP | F7 DoD: «Un modelo **F1** completo construible 100 % desde la UI» | `ROADMAP.md:756-780` |
| `pyproject` | «Lo que **NO** entra [a `[ui]`] es lo que el formulario no ofrece (`ml`, `tuning`, `explain`, `markov`, `forward`)» | `pyproject.toml:121-123` |

Ninguna de esas frases es falsa hoy. Todas dejan de serlo **el día que un bloque se entrega**, y
ninguna está atada a un gate que lo note (salvo la fila de «Empezar»).

### 1.3 Gates que gobiernan una sección nueva del formulario

`test_jobs_catalogo` (sección ⇔ trabajo, bidireccional; `missing_sections` reales),
`test_jobs_ejecutables` (esqueleto de cada trabajo `available` ejecutable por `check_pipeline`),
`test_jobs_abanico` (todo `Literal` de una sección del catálogo declarado o exento con razón),
`test_copy_del_formulario` (placeholder ≤ 160, sin literales Python, sin códigos),
`test_extra_ui_cubre_el_formulario` (extra declarado por sección; `[ui]` no arrastra lo que el
formulario no ofrece), `test_gobernanza_en_pantalla` (15 secciones, gate espejo de tipos),
`test_invariantes_previas`/`test_column_roles` (preflight de columnas), `test_docs_gobernanza`
(catálogo de «Empezar» == `list_jobs()`), `test_public_copy` (códigos internos en docs/README),
`test_marca_estabilidad` (ninguna marca se mueve sin decisión). Son los peajes de cada bloque; la
enmienda de cada bloque los enumera con sus CN.

## 2. Lo que ya está construido y no hay que inventar

- La **UI por trabajos** (D-JOB), el **esqueleto ejecutable** (D-EJE), las **decisiones
  obligatorias** (D-OBL), el **abanico con estados** —incluido «exige el extra X» (D-ABA-7) y
  «exige otra sección activa» (D-ABA-8)— y la **puerta de artefactos por HTTP** (D-PUE: tablas
  como insumo externo con nombre de negocio).
- El **precedente exacto**: la paridad de provisiones («el formulario pasa de 7 secciones a 12»,
  `ROADMAP.md:153-160`, `cf217a2`) y la de gobernanza (D-GOB-10…16): ambas entraron por sección,
  con copy público, esqueleto, panel y capítulo, cada una con su enmienda.
- `ui_widget`/`ui_group`/`ui_order` al **100 %** en los ocho dominios: el trabajo de paridad es
  de superficie, no de metadatos.
- `DOMAIN_TITLES` ya registra `forward` («Escenarios forward-looking») y `markov` («Matrices de
  transición»), y el Anexo C ya vuelca sus parámetros.

## 3. Las decisiones que se proponen

**D-PAR-1 · Objetivo de roadmap: toda sección orquestable del motor es alcanzable desde la
interfaz.** Entra en `ROADMAP.md` como objetivo de producto con su criterio (D-PAR-2), sus bloques
(D-PAR-3) y sin fecha. No amplía ninguna garantía SemVer (D-EST): un dominio experimental sigue
experimental cuando gana pantalla.

**D-PAR-2 · «Alcanzable» tiene seis superficies, y una sección está ENTREGADA sólo con las
seis:** (1) sección del formulario con sus descripciones como copy público; (2) al menos un
trabajo `available` que la ofrezca, con esqueleto ejecutable y sus decisiones obligatorias; (3)
clave en `serialize_study` y panel en Resultados con guard por presencia; (4) capítulo o
subsección en el informe según SDD-26; (5) insumo con el que correr —dataset del registro o
insumo externo por la puerta— y un preset de ejemplo; (6) guía en `docs_site/`. Con menos, la
sección es «por código» y así se dice. Es el criterio que `AGENTS.md` ya fija («una capacidad
que un usuario de `pip install` no puede alcanzar no está entregada») aplicado sección por sección.

**D-PAR-3 · Tres bloques, en este orden, cada uno con su enmienda y su release:**

| Bloque | Dominios | Rutas | Qué lo hace primero | Enmienda |
|---|---|---:|---|---|
| **A · Scorecard completo** | `eda`, `validation` (+ panel de `selection`, bandas del PSI, ficha en el informe) | 50 | son F1 —`eda` estable— y ya corren sobre los datasets del paquete; cierran la promesa del titular | [`_ENMIENDA-SCORECARD-COMPLETO.md`](_ENMIENDA-SCORECARD-COMPLETO.md) (esta sesión) |
| **B · Modelo retador y explicabilidad** | `ml`, `tuning`, `explain` | 92 | corren sobre los datasets F1 y sobre los artefactos del scorecard; el valor es el *benchmark* del scorecard contra GBDT y las razones por operación | por escribir: entrada cuando A esté entregado |
| **C · Forward-looking y dinámica** | `markov`, `forward`, `stress` | 151 | exigen datos que el paquete no tiene (§0-2), 24 campos requeridos, tablas editables anidadas y un DAG de tres dominios; «Stress testing» ya está declarado `unavailable` con su razón | por escribir: entrada cuando B esté entregado y exista el insumo (D-PAR-6) |

**D-PAR-4 · Bloque B: lo que su enmienda tiene que resolver, medido.** (a) **Cómo se ofrece**:
un trabajo nuevo «Scorecard con modelo retador» (secciones del scorecard + `ml` + `explain`,
`tuning` latente como `governance`) frente a `ml`/`explain`/`tuning` **latentes** dentro de
«Scorecard de comportamiento (PD)»; recomendación: **trabajo nuevo** (D-JOB-14: es un entregable
con nombre en un banco, y sembrar GBDT encendido en el scorecard de todos los usuarios no lo es).
(b) **Extras**: los cinco backends de `ml` se instalan aparte; el abanico los declara con «exige
instalar `nikodym[xgboost]`» (D-ABA-7) y `[ui]` compone lo que corre de fábrica (§8-2). (c)
**`tuning.search_space.params`** es un `dict[str, ParamSpec]` con `ui_widget: table` que hoy cae
al editor JSON (`tuning/config.py:294-296`): o gana un widget de espacio de búsqueda o se
declara subsección por código (D-SUB) en la primera entrega. (d) **Informe**: SDD-26 gana los
capítulos «Modelo retador» (comparación de métricas por partición, importancias) y
«Explicabilidad» (SHAP global, códigos de razón sobre una muestra), con figuras; es el DoD de F2.
(e) **Serializer y paneles**: `ml.comparison`, importancias top-k, `explain.shap_global`,
`reason_codes` (muestra), nunca `shap_local` entero. (f) Ningún dataset nuevo.

**D-PAR-5 · Bloque C: condiciones de entrada, medidas.** (a) **Datos**: un dataset sintético de
**panel longitudinal** (id × período × estado) para `markov` y una **serie macro** para `forward`
—como insumo externo por la puerta de artefactos (es una tabla) o como dataset del registro—,
ambos con su generador determinista, catálogo de columnas y firmas; sin ellos no hay preset ni
ejemplo (ROADMAP §B4). (b) **Trabajos**: «Term structure por matrices de transición» (`data`,
`markov`, `report`), «Forward-looking: escenarios macro» (`data`, `survival`|`markov`, `forward`,
`report`) y «Stress testing» pasando de `unavailable` a `available` con `data`, `forward`,
`stress` (+ IFRS 9 cuando se pidan métricas económicas), cada uno con `check_pipeline` verde en
`test_jobs_ejecutables`. (c) **Requeridos**: 24 campos sin default entre los tres; `ForwardConfig()`
no construye, así que el esqueleto (D-FX-8) no puede sembrarlo sin decisiones obligatorias
(`variable_cols`, `factor_cols`, `macro_source`, los escenarios con su peso); es la clase de
`data.target.bad_rule`. (d) **Tablas editables anidadas** (`stress.scenarios[].shocks[]`,
`forward.scenarios[]`): el formulario las edita fila a fila desde `dd8161f`; hay que medir que
dos niveles funcionan. (e) **Informe**: `stress` no existe en `report/`; `forward`/`markov` sólo
en el Anexo C: SDD-26 gana tres capítulos. (f) Los avisos ya declarados (`DATO-INSTITUCIONAL-FWD-1`,
`DATO-INSTITUCIONAL-STR-2`, `FALTA-DATO-ML-1`) se muestran como avisos declarados. (g) D-JOB-13
sigue vigente hasta esa entrega: «Stress testing» se declara, no se promete.

**D-PAR-6 · Nada del copy público cambia antes de entregar cada bloque, y lo que cambia se ata a
un gate.** Las frases de §1.2 siguen siendo verdad hasta que un bloque pase D-PAR-2; entonces
cambian **en el mismo commit** que el gate de entrega. Para que no dependa de la memoria, el
bloque A trae un gate nuevo: la columna «Superficie» de la tabla del README y la frase de portada
se atan al catálogo —un dominio sólo dice «UI, preset e informe» si está en `CONFIG_SECTIONS` **y**
en un trabajo `available` **y** en un preset— y la frase «Stress, Markov y forward-looking se usan
escribiendo el config en Python» se deriva de los dominios de `_DEFAULT_DOMAIN_ORDER` que no
cumplan lo anterior (el mismo mecanismo que hoy ata el catálogo de «Empezar»). **CN**: marcar
`markov` como «UI» en el README con el catálogo actual → rojo.

**D-PAR-7 · Cada bloque respeta los peajes de §1.3 y añade los suyos**: copy público de todas
sus descripciones (tabla «Hoy / Propuesto», como D-GOB-13), abanico declarado o exento con razón,
preflight de columnas (`column_role`), extra declarado por sección, gate espejo de tipos, render
del panel con y sin la clave, capítulo verificado en HTML/PDF/DOCX, guía con ejemplo ejecutado por
gate, «Empezar» regenerado por el gate del catálogo, y recorrido en navegador.

**D-PAR-8 · Lo que la paridad NO promete todavía**: fechas; que un dominio experimental pase a
estable por tener pantalla; una CLI que corra pipelines; *roll rates* ni curvas de cosecha
(README lo niega y sigue negándolo); datasets reales; que la demo pública muestre los bloques B y
C (cada recaptura tiene su OK); que `[ui]` instale los backends GBDT (§8-2); ni que
`validation` entre a «Validar un modelo existente» antes de medirlo (bloque A, §8-4 de su
enmienda).

**D-PAR-9 · Convención de conteo para el roadmap**: los tamaños se citan en **rutas del barrido
del gate de copy del formulario** (lo que la persona verá) y, entre paréntesis, los campos por
`Field` menos contenedores; nunca se suman conteos de convenciones distintas.

## 4. Contratos de datos (I/O)

Ninguno cambia con este documento. Por bloque, las enmiendas fijan: secciones nuevas de
`CONFIG_SECTIONS` (A: 15 → 17; B: → 20; C: → 23), claves nuevas de `serialize_study`, tipos del
front, `ChapterSpec` nuevos de SDD-26, datasets nuevos del registro (C), y la composición del
extra `[ui]` (B, §8-2).

## 5. Casos borde

- Un dominio que gane formulario sin trabajo → `test_toda_seccion_del_formulario_pertenece_a_algun_trabajo`
  en rojo (ya existe): la secuencia no admite «sección huérfana».
- Un trabajo `available` sin preset ni insumo → viola D-PAR-2 (5); se declara `unavailable` con
  razón (D-JOB-6) hasta tenerlo.
- Un dominio con extra opcional no instalado → el abanico lo declara y la corrida no arranca con
  el motivo (D-ABA-7); nunca `MissingDependencyError` en pantalla.
- Un bloque que necesite mover una marca de estabilidad → decisión registrada en el registro
  (D-EST-4), nunca como efecto lateral de la paridad.

## 6. Gates y controles negativos de ESTA enmienda

Este documento sólo añade un gate, el de D-PAR-6, que entra con el bloque A (capa 2 de su
enmienda o una capa propia, a elección del implementador): README y portada atados al catálogo,
con su control positivo (un dominio marcado «UI» que sí lo está) y su negativo (marcar `markov`).
Todo lo demás son gates de cada bloque. El `ROADMAP.md` gana el objetivo y la tabla de bloques con
enlace a este documento; `docs/design/00-INDICE.md` lo indexa (`test_indice_diseno`).

## 7. Lo que esta enmienda NO hace

- No diseña los bloques B ni C: fija sus condiciones de entrada y sus peajes.
- No cambia el copy público ni el catálogo: eso lo hace cada bloque cuando se entrega.
- No mueve marcas de estabilidad, hashes, extras ni versión.
- No decide la composición de `[ui]`: la eleva (§8-2).
- No reabre D-JOB-13 (`stress` `unavailable`) ni D-JOB-18 (`validation`, que cierra el bloque A).

## 8. Lo que Cami decide

1. **¿Se aprueban el objetivo (D-PAR-1), el criterio de seis superficies (D-PAR-2) y el orden
   A → B → C (D-PAR-3)?** Recomendación: sí.
2. **Composición del extra `[ui]` para el bloque B.** Opciones: (a) `[ui]` compone también `ml`,
   `tuning` y `explain` (shap, numba, llvmlite, optuna) y mantiene los backends GBDT como extras
   aparte que el abanico declara; (b) `[ui]` compone todo, incluidos los tres GBDT; (c) `[ui]` no
   cambia y la promesa de «Empezar» pasa a «lo que el formulario ofrece de fábrica». Recomendación:
   **(a)**: conserva la promesa para lo que el formulario corre sin elegir un backend externo, y
   D-ABA-7 ya sabe decir «exige instalar `nikodym[xgboost]`».
3. **Bloque B: ¿trabajo nuevo «Scorecard con modelo retador» o secciones latentes en el
   scorecard?** Recomendación: **trabajo nuevo**.
4. **Bloque C: ¿se compromete en el roadmap ahora, o queda «con demanda que lo justifique»** como
   dice el plan operativo del 2026-07-30 (`ROADMAP.md:38`)? Recomendación: **se compromete como
   objetivo con condiciones de entrada (D-PAR-5) y sin fecha**; la demanda decide cuándo, no si.
5. **¿El gate de D-PAR-6 (README/portada atados al catálogo) entra con el bloque A?**
   Recomendación: sí, es barato y es lo que impide que el copy se pudra al entregar B y C.
