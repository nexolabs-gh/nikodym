# Enmienda SDD — Flujo guiado del scorecard (primera aplicación de SDD-31)

> **Estado: PROPUESTA el 2026-09-18** (sesión S16), sobre las decisiones interactivas de Cami de ese
> día (SDD-31 §0.2). Pendiente de su aprobación a §8. Diseño sin código: **no autoriza programar**
> ninguna capa; cada capa se implementa sólo tras el OK, con tests nacidos rojos, controles
> negativos y revisión adversarial.
>
> **Base medida:** `main` = `fcd058d` (1.16.0). **Enmienda a:**
> [`31-simplicidad-y-flujo-guiado.md`](31-simplicidad-y-flujo-guiado.md) (lo aplica), SDD-06…11 y
> SDD-27 (resúmenes por etapa y dos adiciones al motor de §3.6), SDD-26 (la página ejecutiva y el
> Excel opcional), SDD-23 y [`_SDD-UI-POR-TRABAJOS.md`](_SDD-UI-POR-TRABAJOS.md) (esenciales y
> «Avanzado»), SDD-04 (MLflow opt-in), `docs_site/` (el notebook mínimo abre la guía).
> **Absorbe:** la parte de ENTREGABLES-LEGIBLES que depende de la forma de uso (§0.2) y los
> hallazgos #4, #5 y #8 de INTEGRACION-EXTERNA-1-16 (§0.3).
>
> **No toca:** los motores de binning, selección, modelo, scorecard, calibración, desempeño,
> estabilidad ni validación (sus resultados son bit a bit los de hoy con el mismo config), el
> `config_hash`, la garantía SemVer 1.x, D-JUR/D-GOB/D-EST/D-SUB/D-OBL/D-JOB/D-SC/D-VAL, CMF, el
> arnés H9R. **No autoriza** bump, tag, PyPI ni recaptura.

| Campo | Valor |
|---|---|
| **Enmienda** | FLUJO-GUIADO-SCORECARD (D-FLU-1…D-FLU-12) |
| **Módulos** | Puerta guiada nueva (`nikodym.Scorecard`, nombre en §8-1); `selection` y `binning` (dos publicaciones aditivas, §3.6); `report` (resúmenes, página ejecutiva, Excel opcional); `nikodym.ui` + `web/` (esenciales/«Avanzado»); `docs_site/` |
| **Fase** | F1 |
| **Depende de** | SDD-31; puerta de artefactos (D-ART) para reanudar; D-OBL (decisiones institucionales); D-SUB/`hidden` (mecánica de ocultar); D-SC (bandas y estados en palabras); D-FUGA (exclusión de las columnas del target) |
| **Lo consumen** | El notebook mínimo, «Empezar», el tutorial, la UI (trabajos `scorecard_pd` y `pd_y_lgd`), la demo, la enmienda de IFRS 9 (mismo molde) |
| **Release** | Capa A aditiva en un minor (§8-5); B y C en el siguiente o el mismo, según §8-5 |

## 0. Qué corrige de lo ya escrito

### 0.1 «Scorecard 100 % cerrado» (S15) era cierto para el motor y la pantalla, no para la forma

La definición vigente de cerrado (SCORECARD-COMPLETO 16/16 + VALIDACION-COTEJADA) no incluía cómo
se usa. Con SDD-31 el scorecard cierra cuando cumple su §7: entrada mínima, puerta guiada, esenciales
declarados, notebook mínimo en CI y las cinco cifras ancladas. Nada de lo cerrado se reabre: los
motores no cambian y sus goldens tampoco.

### 0.2 ENTREGABLES-LEGIBLES cambia de forma, no de objetivo

El resumen ejecutivo de una página y el helper `study.summary()` que ese plan pedía son el
**resumen final** de la puerta guiada (D-FLU-4), con una sola fuente para notebook, pantalla e
informe. La tipografía y marca del informe, y la ficha renderizada, pasan a la **capa C** de esta
enmienda; el «detalle al anexo o al CSV/XLSX» pasa a ser el Excel opcional por etapa (D-FLU-5).

### 0.3 INTEGRACION-EXTERNA-1-16: tres hallazgos se cubren aquí; cuatro siguen pendientes

- **#4** (`assert_done`/`raise_on_error`) y **#5** («ejecución completada» ≠ «modelo rechazado»):
  el resumen final publica los dos estados por separado y `Scorecard.run()` ofrece
  `raise_on_error=` (D-FLU-4).
- **#8** (`export_bundle`): `Scorecard.export()` empaqueta el `run_dir` (D-FLU-5).
- **#1, #2, #6, #7** son contractuales (estructura congelable del informe, presets versionados,
  preflight de contenido, cadena de hashes del trail) y conservan su propia enmienda.

### 0.4 La Clase 6 de Academia Bayes deja de ser el ejemplo canónico

La sustituye el notebook mínimo público (D-FLU-10). El material del curso se actualiza fuera del
repo cuando la capa A esté publicada.

## 1. El estado, medido sobre `fcd058d`

### 1.1 Cifras

- Formulario: **572 campos** visibles en 17 secciones; las doce secciones que tocan los dos trabajos
  del scorecard suman **409** (`data` 158, `binning` 42, `selection` 33, `report` 33, `validation`
  28, `model` 23, `eda` 17, `scorecard` 17, `calibration` 16, `stability` 16, `governance` 14,
  `performance` 12). Los grupos de cada sección se pintan abiertos
  (`web/src/components/ConfigTab.tsx:748-752`).
- Preset F1: ~380 líneas de literal (`src/nikodym/ui/presets.py`); cambia 14 de 202 hojas
  comparables con el default de fábrica.
- Uso real por código (Clase 6, 15.665 filas, 108 candidatas): celda de configuración de **83
  líneas** (el esquema de las 108 columnas como lista de dicts), `nikodym.run()` sin salida, lectura
  de resultados con `study.artifacts.get(dominio, clave)` y renombres a mano
  (`{"desarrollo": "DEV", …}`); el informe, 8 + 3 secciones, **126 tablas, 614 KiB**.
- `nikodym.run` devuelve `status == "done"` con `validation.overall_status == "fail"`, y sólo
  quien conoce las dos claves lo ve (hallazgo #5).

### 1.2 El flujo del banco, paso a paso, y qué se adopta

Medido sobre el flujo que Cami diseñó y operó (clase `modelacion`, 39 métodos; notebook de 79
celdas con 27 llamadas y 79 parámetros como máximo). Se adopta el **patrón**, nunca el código ni la
metodología institucional (`ROADMAP.md`, «Qué no hacer»).

| Paso del banco | En Nikodym hoy | Estado | Se adopta |
|---|---|---|---|
| `modelacion(12 args)` + Excel con las variables | `data.schema` exige declarar cada columna; `binning.feature_columns` | ✅ motor · ❌ forma | **Capa A**: entrada mínima e inferencia del esquema (D-FLU-1) |
| `muestra_train`: busca una semilla que deje la PD por período dentro de su IC en train y test | `data.partition` aleatoria/temporal/cohorte/columna, sin control de PD por período | ⚠️ | **No ahora**: la partición temporal ya protege lo que ese muestreo buscaba; sin evidencia de que el default falle (D-SIM-3). Candidato anotado en §3.7 |
| `proceso_woeizacion` (OptBinning, códigos especiales) | `binning` (OptBinning, `special_values`, `variable_overrides`) | ✅ | Reúso |
| `categorizacion_manual` (juntar dos tramos) | `binning.variable_overrides` por config, antes de correr | ⚠️ | **Capa A**: `merge_bins()` como decisión humana (D-FLU-3) |
| `ejecutar_bivariado`: IV, IEP y ROC **por muestra** (DEV/HO/OOT/TTD), Excel `02` | `selection` publica IV/AUC/KS/Gini univariados **sólo en desarrollo**; CSI por partición en `selection.stability` | ⚠️ | **Capa A**: IV por partición en la tabla de selección (D-FLU-6, §3.6) |
| `descartar_inversion_br`: monotonía de la tasa de malos por tramo, por muestra | `binning.monotonic_trend` garantiza monotonía en desarrollo; nada la comprueba en holdout/OOT | ⚠️ | **Capa A**: alerta «tramo que invierte en HO/OOT» en el resumen de binning (D-FLU-6, §3.6) |
| `estabilidad_periodos`: IEP por período por variable, Excel `03` | `eda.stability`, `stability` temporal (PSI/CSI por período) | ✅ parcial | Reúso en el resumen de estabilidad |
| Descartes manuales con lista y motivo | `selection.force_exclude` (sin motivo) | ⚠️ | **Capa A**: `exclude(cols, reason=)` al trail (D-FLU-3) |
| `proceso_correlacion` (Pearson, orden por IV), Excel `04` | `selection.correlation` (método, umbral, orden por prioridad) + `vif` | ✅ | Reúso |
| `stepwise` iterativo con cascada beta negativo → ROC → IV-contribution → VIF, hoja por iteración | `model.stepwise` + `sign_policy` + `iv_contribution` + `selection.vif`, con acciones `flag`/`drop` | ✅ | **Capa A**: traza legible de qué salió y por qué en el resumen del modelo (D-FLU-2) |
| `scorecard`, `07` Kendall/Spearman, `08` VIF, `09` DQ de las finales | `scorecard`; `correlation.method`; `vif`; `eda.quality` | ✅ | Reúso en los resúmenes |
| `tdr_paso_1`: deciles por muestra, Excel `10` | `performance` (deciles, KS, lift por partición) | ✅ | Reúso |
| `tdr_paso_2`: **tramos de score** con OptimalBinning monótono y PI por tramo | — | ❌ | **Módulo aparte** «escala maestra y puntos de corte» (ROADMAP H5); §8-3 decide si su primera versión entra en la capa B |
| Calibración por intercepto a la tasa TTC | `calibration.intercept_offset` (ancla observada o de negocio) | ✅ | Reúso |
| Bayes iterado a TTC por bucket | — | ❌ | **No**: metodología institucional; la calibración del motor ya ancla al TTC |
| `test_representatividad` (homogeneidad/heterogeneidad de tramos, HHI) | — | ❌ | **Después**, con la escala maestra o la validación (ROADMAP H4/H5) |
| `bootstrap_test` (IC de los coeficientes) | — | ❌ | **Después**, en validación (ROADMAP H4) |
| `output_calculadora_dat` (betas, WoE, PI por bucket) | `FittedScorecardBundle` (manifest + bins.parquet) | ✅ equivalente | Reúso; export SQL como candidato del roadmap |
| `01 Registro de Parametros.txt` | audit-trail + lineage + `config.yaml` | ✅ más completo, menos legible | **Capa A**: «Registro de decisiones» en el resumen final (D-FLU-4) |
| Versiones V00…VF01 por carpeta | `run_dir` por corrida + `config_hash`, sin nombre de versión | ⚠️ | **Capa A**: `name=` y `compare()` (D-FLU-1/6) |
| Excel numerado por paso | exports csv/xlsx del informe, al final | ❌ | **Capa B**: `export_excel()` opcional (D-FLU-5) |
| Cada paso imprime 1–5 líneas | `run()` mudo | ❌ | **Capa A**: resumen por etapa (D-FLU-2) |

## 2. Lo que ya está construido y no hay que inventar

- `nikodym.run` / `Study` (`core/study.py`): orquestación, `run_step` (`:468`), `save`/`load`.
- La puerta de artefactos (`nikodym.run(..., artifacts=…)`, `docs_site/guias/puerta-artefactos.md`):
  reanudar desde claves ya calculadas es exactamente `resume()` (D-FLU-3).
- `binning.variable_overrides` (`binning/config.py:203`): cortes y categorías por variable.
- `selection.force_exclude` / `model.force_exclude` / `force_include`.
- `report/exports.py`: csv y xlsx por tabla con `spreadsheet_safety`.
- `scorecard/bundle.py`: `FittedScorecardBundle`, `apply`, `apply_file`.
- `tracking/config.py`: `TrackingConfig` completa; apagada en los presets.
- `ui/jobs.py:642` `_DECISIONES_POR_SECCION`: las decisiones institucionales ya formuladas en
  idioma de negocio con sus formas de respuesta; son la entrada mínima de D-FLU-1 en pantalla.
- `binning/config.py:60` `ui_group` y la mecánica `hidden` de D-SUB: el schema ya transporta
  metadatos de presentación; «esencial» es uno más.
- `nikodym.validation.results` y `nikodym.stability.results`: las palabras de los estados y las
  bandas («Pasa · Revisar · Falla · No evaluable», «Estable · Revisar · Redesarrollar · No
  evaluable») con espejo gateado en el front.
- `report/prose.py` y los mapas de rótulos: el vocabulario en español de cada tabla ya existe.

## 3. Las decisiones que se proponen

### 3.1 D-FLU-1 — La puerta guiada y su entrada mínima

```python
from nikodym import Scorecard          # nombre en §8-1

sc = Scorecard(
    data="cartera.parquet",             # ruta (csv/parquet/xlsx) o DataFrame
    target="malo",                      # columna 0/1, o una regla: {"col": "dias_mora", "op": ">", "value": 90}
    id="id_cliente",
    date="fecha_solicitud",             # o cohort="cohorte"; sin ninguno, partición aleatoria declarada
    name="consumo_v01",                 # versión del proyecto; opcional
    run_dir="modelos",                  # la evidencia queda en modelos/consumo_v01
)
sc.run()                                # corre todo e imprime el resumen de cada etapa
sc.summary()                            # el resumen final: ejecución y veredicto técnico, por separado
```

- **Lo que se pide** es sólo lo institucional (D-SIM-2): datos, target, identificador, eje
  temporal y —si no hay eje— nada más. Todo lo demás tiene default.
- **Lo que se infiere y se declara** (una decisión `inferencia_*` en el trail por cada una): el
  esquema (`data.schema.columns` desde los dtypes), las categóricas (dtype `object`/`category`/
  `bool`), las predictoras (todas menos id, target, fecha/cohorte y las columnas de la regla del
  target, por D-FUGA), la partición (temporal si hay `date`, por cohorte si hay `cohort`, aleatoria
  si no; el corte OOT por la regla de §8-2), y los rótulos de las muestras.
- **Argumentos opcionales = campos esenciales** (D-FLU-7): `features=`, `categorical=`,
  `oot_from=`/`oot_cohorts=`, `holdout=`, `max_bins=`, `min_iv=`, `pdo=`/`target_score=`/
  `target_odds=`, `target_pd=`, `track=`. Ninguno es una hoja nueva: cada uno escribe una hoja
  existente del config.
- `sc.config` es el `NikodymConfig` completo que corre; `sc.study` el `Study`; `sc.config_hash`
  la identidad. `sc.to_yaml()` exporta el config para la puerta completa o la pantalla.

### 3.2 D-FLU-2 — Etapas y lo que dice cada resumen

Nombres estables en inglés, rótulos en español. Cada resumen: 3–8 líneas, una tabla de decisión y
las alertas en palabras.

| Etapa | Rótulo | Lo que dice | Tabla de decisión |
|---|---|---|---|
| `data` | Datos y muestras | filas, malos y tasa; por muestra (DEV/HO/OOT/TTD) con fechas o cohortes; qué se infirió | tasa de malos por período con la banda de estabilidad de `eda` |
| `binning` | Tramos y WoE | variables tramificadas, descartadas por no tramificables, alertas de monotonía en HO/OOT (§3.6) | IV por variable con tendencia y número de tramos |
| `selection` | Selección de variables | cuántas entran, cuáles salen y por qué (IV, correlación, VIF, estabilidad, decisión humana) | IV por muestra, correlación máxima, VIF (§3.6) |
| `model` | Modelo | variables finales, iteraciones del stepwise y qué salió en cada una, AUC/KS por muestra | coeficientes con signo, p-valor y contribución al IV |
| `scorecard` | Tarjeta de puntuación | escala (PDO, puntaje y odds objetivo), rango de puntajes | puntos por tramo |
| `calibration` | Calibración | ancla y fuente, PD media antes y después, ranking preservado | Brier/ECE por muestra |
| `performance` | Desempeño | AUC, Gini y KS por muestra y la caída DEV→OOT en palabras | deciles por muestra (la tabla de rendimiento) |
| `stability` | Estabilidad | peor PSI con su banda, CSI peor por variable | PSI/CSI por comparación con banda |
| `validation` | Validación formal | estado técnico en palabras y qué prueba lo decidió | pruebas por familia con veredicto |
| `report` | Informe y ficha | dónde quedó cada archivo | — |

Las tablas y las palabras son las que ya publican las cards y los mapas de rótulos del informe:
**una sola fuente** (D-SIM-5). En notebook el resumen se pinta por `_repr_html_`; en consola, texto;
en pantalla, el panel de Resultados que ya existe, alineado a esta misma fuente.

### 3.3 D-FLU-3 — Parar, decidir y seguir

```python
sc.run(until="selection")
sc.exclude(["saldo_promedio_6m", "n_productos"], reason="inversión de negocio")
sc.merge_bins("antiguedad_meses", [2, 3], reason="tramos con la misma tasa")
sc.resume()                             # continúa desde la primera etapa afectada
```

- `run(until=<etapa>)` ejecuta hasta esa etapa inclusive; `resume()` continúa. Si una decisión
  cambia el config de una etapa ya corrida, `resume()` vuelve a correr desde ella (la puerta de
  artefactos conserva lo anterior).
- Decisiones humanas de la capa A: `exclude(cols, reason=)`, `keep(cols, reason=)` (fuerza
  inclusión), `merge_bins(col, bins, reason=)`, `set_bins(col, cuts, reason=)`. Cada una escribe
  la hoja de config correspondiente (`selection.force_exclude`, `model.force_include`,
  `binning.variable_overrides`) y emite `decision` al trail con `autor="usuario"`, `motivo` y la
  hoja tocada. La ficha las lista en «Decisiones».
- `run()` sobre `sc.config` sin la puerta guiada reproduce el mismo resultado: las decisiones viven
  en el config, no en el objeto.

### 3.4 D-FLU-4 — El resumen final: dos estados, cinco cifras y qué revisar

`sc.summary()` publica, en este orden: **Ejecución** («completada» o «fallida en <etapa>: <mensaje
del motor>»); **Validación técnica** («Pasa · Revisar · Falla · No evaluable», con la prueba que lo
decidió); cinco cifras (AUC/Gini/KS en OOT, caída DEV→OOT, peor PSI con banda); qué revisar (las
alertas de todas las etapas); el registro de decisiones humanas con motivo; y dónde quedó cada
archivo. Es la página ejecutiva que ENTREGABLES-LEGIBLES pedía, con la misma fuente que el informe.
`sc.run(raise_on_error=True)` lanza la excepción del motor en vez de devolver el estado (#4).

### 3.5 D-FLU-5 — Excel opcional y exportación

`sc.export_excel()` escribe en `<run_dir>/<name>/excel/` un libro por etapa, numerado en el orden
de §3.2 (`01 Datos y muestras.xlsx` … `09 Validación.xlsx`, más `10 Decisiones.xlsx`), con las
tablas de decisión y las tablas completas del anexo, por `report/exports.py` (misma protección de
celdas). `sc.export("corrida.zip")` empaqueta el `run_dir` (#8). Ninguno corre solo.

### 3.6 D-FLU-6 — Lo que se adopta del banco en la capa A (dos publicaciones aditivas del motor)

1. **IV por partición** en la tabla de selección: `selection` publica, además del IV en desarrollo,
   el IV de cada variable en holdout y OOT sobre los tramos fijados en desarrollo. Aditivo (una
   columna por partición en `selection_table`); ningún umbral nuevo: el descarte sigue siendo por
   `min_iv` en desarrollo. Evidencia: es la primera pregunta de un validador y el flujo del banco
   descartaba por «IV HO/OOT».
2. **Alerta de monotonía fuera de desarrollo**: `binning` publica la tasa de malos por tramo en
   cada partición y el resumen marca «invierte en <muestra>» cuando la tendencia de desarrollo no
   se sostiene. Sólo alerta; no descarta.

Además, sin tocar motores: la traza legible del stepwise, `merge_bins`, `exclude` con motivo,
`name=` y `compare(other)` (dos corridas lado a lado: cifras, variables y decisiones).

### 3.7 Candidatos anotados, no adoptados (cada uno espera su evidencia)

Muestreo con control de PD por período; escala maestra y puntos de corte (módulo propio); test de
representatividad de tramos; bootstrap de coeficientes; export SQL de la tarjeta. Entran por su
enmienda cuando un caso real muestre que el default falla o que el módulo falta (SDD-31 D-SIM-3).

### 3.8 D-FLU-7 — Esenciales por sección (propuesta para §8-4)

| Sección | Esenciales | Hoy visibles |
|---|---|---|
| `data` | archivo, regla del target, identificador, fecha o cohorte, partición | 158 |
| `eda` | ninguno: todo default; el resumen lo muestra | 17 |
| `binning` | `max_n_bins`, `min_bin_size`, `monotonic_trend` | 42 |
| `selection` | `min_iv`, `correlation.threshold`, `vif.threshold` | 33 |
| `model` | `stepwise.enabled`, `stepwise.entry_p_value`, `stepwise.exit_p_value`, `sign_policy.action` | 23 |
| `scorecard` | `pdo`, `target_score`, `target_odds` | 17 |
| `calibration` | `anchor_source`, `target_pd` | 16 |
| `performance` | `n_deciles` | 12 |
| `stability` | `psi_stable_threshold`, `psi_review_threshold` | 16 |
| `validation` | `families` | 28 |
| `report` | `document.model_name`, `document.entity`, `document.portfolio`, `document.author`, `formats` | 33 |
| `governance` | `purpose`, responsable, periodicidad de revisión | 14 |

De 409 campos visibles a **≈ 35 esenciales**; el resto se pliega en «Avanzado» (D-FLU-8). La marca
es un metadato del schema (`json_schema_extra={"ui_essential": True}`), con golden bidireccional.

### 3.9 D-FLU-8 — Pantalla

Cada sección pinta sus esenciales abiertos y un único bloque «Avanzado» **cerrado** con la cifra de
cuántos campos avanzados difieren del default; el resto de la mecánica (grupos, ayuda, validación
en vivo, decisiones institucionales) no cambia. El panel de Resultados, que ya pinta por etapa,
consume la misma fuente que `summary()`.

### 3.10 D-FLU-9 — MLflow

`Scorecard(..., track="./mlruns")` (o una URI) enciende `tracking` con sus defaults; sin el
argumento no se registra nada. Lo que se registra es lo de SDD-04.

### 3.11 D-FLU-10 — El notebook mínimo

`docs_site/` gana «Tu primer scorecard en N líneas» (N de SDD-31 §12.2): construir, correr, leer el
resumen, una decisión humana, `resume()`, exportar. Se ejecuta en CI como los bloques
`quickstart:start/end`. «Empezar» y el tutorial abren con él; la puerta completa queda como segunda
lectura.

### 3.12 D-FLU-11 — Capas

| Capa | Qué | Gate de cierre |
|---|---|---|
| **A** | Puerta guiada por código: entrada mínima e inferencias, `run`/`until`/`resume`, decisiones humanas, resúmenes por etapa, resumen final, `compare`, `track=`, las dos publicaciones de §3.6, `raise_on_error`, notebook mínimo | las cinco cifras ancladas; notebook en CI; `config_hash` de `sc.config` == el del YAML exportado; `run()` == `run(until)+resume()` sin decisiones |
| **B** | Pantalla esenciales/«Avanzado» con su golden; Excel opcional y `export()`; Resultados sobre la fuente de `summary()` | golden de esenciales; copy gate; Excel byte a byte con las tablas del informe |
| **C** | Informe: página ejecutiva = resumen final; tipografía y marca del sitio; ficha renderizada (lo que ENTREGABLES-LEGIBLES pedía y no depende de la API) | goldens del informe declarados antes de moverlos |

### 3.13 D-FLU-12 — Presupuesto de perillas: cero. Qué NO se configura

Cero hojas nuevas de config: cada argumento de la puerta guiada escribe una hoja existente y
`ui_essential` es metadato. No se configura: el formato ni el idioma de los resúmenes, la
numeración y los nombres del Excel, la regla de inferencia del esquema y de las predictoras, el
orden de las etapas, los rótulos, ni qué tabla es «de decisión» en cada etapa. Son constantes con
su razón: cada una de ellas es exactamente lo que hoy obliga al usuario a saber antes de empezar.

## 4. Contratos de datos (I/O)

- **Entrada:** ruta a csv/parquet/xlsx o `pandas.DataFrame` (por `("data", "input_frame")`);
  target como columna o regla en la forma de `data.target.bad_rule`; `date` o `cohort` nombran
  columnas existentes.
- **Salida:** `sc.study` (el `Study`), `sc.config` (`NikodymConfig`), `sc.results[<etapa>]` (los
  DataFrames de decisión), `sc.summary(<etapa>|None)`, y en disco el layout de SDD-03 §6 bajo
  `<run_dir>/<name>/` más `excel/` si se pidió.
- **Invariantes:** `config_hash(sc.config)` es estable entre `run()`, `run(until)+resume()` y el
  YAML exportado; toda decisión humana aparece una vez en el trail y una vez en el config.

## 5. Casos borde

Sin `date` ni `cohort` (partición aleatoria declarada; estabilidad temporal «No evaluable» con
causa); `id` ausente (índice del archivo, declarado); target con nulos (TTD: se puntúa, no se ajusta);
categórica con cardinalidad alta (`cat_cutoff` de fábrica agrupa el resto y el resumen lo dice);
todas las variables descartadas (el modelo falla con el mensaje del motor; los resúmenes anteriores
quedan); `merge_bins` sobre tramos no adyacentes (error legible: el motor exige adyacencia);
`resume()` sin `run(until)` previo (corre todo); `track=` sin el extra instalado (mensaje con el
comando exacto, como `polars`).

## 6. Gates y controles negativos de ESTA enmienda

1. Golden de las cinco cifras del scorecard (SDD-31 §5) y del tope de esenciales por sección.
2. El notebook mínimo ejecutado en CI; control negativo: una línea de más lo pone rojo.
3. `config_hash(sc.config) == config_hash(load_config(sc.to_yaml()))`.
4. `run()` y `run(until="model") + resume()` dejan artefactos idénticos sin decisiones humanas.
5. Una decisión humana aparece en el trail con motivo y en la ficha; control negativo: retirar la
   emisión → gate rojo.
6. Los resúmenes no contienen identificadores del motor (gate de códigos internos extendido).
7. Las dos publicaciones de §3.6 son aditivas: los goldens actuales de `selection_table` y de las
   tablas de binning no se mueven salvo por las columnas nuevas, declaradas.
8. El Excel opcional reproduce byte a byte las tablas de los exports del informe.

## 7. Lo que esta enmienda NO hace

No cambia ningún resultado numérico con el mismo config; no retira ni renombra hojas del config; no
mueve el `config_hash` de los presets; no toca CMF ni IFRS 9 (su enmienda es la siguiente); no
convierte el Excel en obligatorio; no reabre D-SC (bandas y estados), D-VAL (pruebas), D-GOB
(ficha) ni D-JOB (trabajos); no programa nada.

## 8. Lo que Cami decide

| # | Decisión | Opciones | Recomendación |
|---|---|---|---|
| 8-1 | Nombre de la puerta guiada | (a) **clase `nikodym.Scorecard`**; (b) función `nikodym.scorecard(...)` que devuelve el objeto; (c) `nikodym.Flow("scorecard", ...)` genérico | **(a)**: se lee como lo que es, y IFRS 9 tendrá `nikodym.Ecl` con el mismo molde |
| 8-2 | Corte OOT por defecto cuando hay `date` | (a) **inferir con regla declarada** (los últimos 12 meses si el rango cubre ≥ 24; si no, el último 25 % de los períodos) y mostrarlo en el resumen de datos con cómo cambiarlo; (b) exigir `oot_from` siempre | **(a)**: respeta D-OBL porque la decisión se ve y se cambia con un argumento; exigirlo devuelve el primer resultado a una pregunta previa |
| 8-3 | Escala maestra y puntos de corte (tramos del banco) | (a) **módulo propio después de IFRS 9** (ROADMAP H5); (b) una primera versión (`cutoffs(n=3)`) en la capa B | **(a)**: es metodología con tests propios; meterla en B retrasa la capa que hace usable el scorecard |
| 8-4 | Esenciales por sección | (a) **la tabla de §3.8**; (b) recortar a 3 por sección; (c) ampliar | **(a)**: ≈ 35 campos, cabe en pantalla y en la firma |
| 8-5 | Releases | (a) **capa A en 1.17.0; B y C en 1.18.0**; (b) A+B+C en 1.17.0 | **(a)**: A ya cambia cómo se usa la librería y merece salir sola; B y C mueven front, informe y goldens |
| 8-6 | Notebook mínimo como ejemplo canónico | (a) **sí**, y la Clase 6 se actualiza fuera del repo; (b) los dos conviven | **(a)**: dos ejemplos canónicos son dos maneras de empezar |
| 8-7 | Nombres del Excel opcional | (a) **los de §3.5**; (b) otros | **(a)** |
