# Enmienda SDD — Flujo guiado del scorecard (primera aplicación de SDD-31)

> **Estado: APROBADA por Cami el 2026-09-18** (sesión S16), de forma interactiva y con la
> recomendación de cada uno de los siete puntos de §8, sobre sus decisiones del mismo día (SDD-31
> §0.2). Diseño sin código: **la capa A se implementa en la sesión siguiente**, con tests nacidos
> rojos, controles negativos y revisión adversarial; B y C después, cada una con el OK de su
> release (1.17.0 la A, **declarada experimental hasta que cierre B**; 1.18.0 B + C).
> **Corregida el mismo día tras la pasada 1 de Codex** (seis hallazgos high, todos absorbidos; los
> cuatro contractuales decididos por Cami: D-OBL-5 se respeta —la frontera OOT se exige—, adelanto
> declarado en D-SIM-1, paridad de resultados con procedencia declarada, `resume()` como corrida
> nueva completa; los otros dos, artefactos aditivos separados y ficha sólo con `purpose`, son
> correcciones de diseño). **Pasada 2 de Codex (siete high, todos absorbidos, ninguno
> contractual):** residuos de la reanudación incremental retirados; el IV por muestra es un
> artefacto aparte también en la tabla de §1.2; el umbral de los diagnósticos es una constante de
> filas por tramo, independiente de `min_bads_per_partition`; autor y motivo viajan en el trail
> con el `DecisionRecord` actual intacto (la ficha muestra la decisión, no el motivo, hasta la
> capa C); el gate de paridad compara una proyección computacional, no los archivos; la firma de
> `Scorecard` tiene un mapeo exhaustivo con los esenciales (§3.8); `run_dir` y `name` tienen
> default (§3.1, §8-8). **Pasada 3 (cinco high, todos absorbidos, ninguno contractual):** `keep`
> escribe `selection.force_include` y `model.force_include`; `id` es opcional y mapea a
> `unique_keys` (columna) o `index_col` (índice); un `DataFrame` se persiste como snapshot y el
> config lo referencia; `partition="random"` fija las tres fracciones y ajusta las listas de
> particiones; cada resumen usa sólo lo que publica su etapa o una anterior (sin AUC en `model`,
> sin Brier ni ECE en `calibration`). **Con esto se cierra la revisión de diseño en el tope
> declarado de tres pasadas**: las siguientes van sobre el código de la capa A.
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
| **Depende de** | SDD-31; D-OBL (decisiones institucionales); D-SUB/`hidden` (mecánica de ocultar); D-SC (bandas y estados en palabras); D-FUGA (exclusión de las columnas del target); D-GOB-8 (la ficha sólo con `purpose`). **No** depende de D-ART: `resume()` no reutiliza artefactos (§3.3) |
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
| `ejecutar_bivariado`: IV, IEP y ROC **por muestra** (DEV/HO/OOT/TTD), Excel `02` | `selection` publica IV/AUC/KS/Gini univariados **sólo en desarrollo**; CSI por partición en `selection.stability` | ⚠️ | **Capa A**: IV por partición como artefacto aparte `("selection", "iv_by_partition")`; `selection_table` conserva su esquema (D-FLU-6, §3.6) |
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
- La puerta de artefactos (`nikodym.run(..., artifacts=…)`, `docs_site/guias/puerta-artefactos.md`)
  existe y **no la usa esta enmienda**: `resume()` es una corrida completa (D-FLU-3); la
  reutilización de artefactos queda como candidata con evidencia de costo (§3.7).
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
    date="fecha_solicitud",             # o cohort="cohorte"; sin ninguno, partition="random" explícito
    oot_from="2024-01",                 # frontera OOT: obligatoria con date (oot_cohorts= con cohort); D-OBL-5
    name="consumo_v01",                 # versión del proyecto; default "scorecard"
    run_dir="modelos",                  # la evidencia queda en modelos/consumo_v01; default "nikodym-runs"
)
sc.run()                                # corre todo e imprime el resumen de cada etapa
sc.summary()                            # el resumen final: ejecución y veredicto técnico, por separado
```

- **Lo que se pide** es sólo lo institucional (D-SIM-2, D-OBL-5): datos, target, eje temporal
  **y la frontera OOT** (`oot_from=` con `date`, `oot_cohorts=` con `cohort`) o, sin eje,
  `partition="random"`. El identificador (`id=`) es opcional y recomendado: si nombra una columna
  va a `data.schema.unique_keys`; si nombra el índice del archivo, a `index_col` (que el motor
  reserva a un índice pandas nombrado, `data/schema.py:36`); sin él se usa el índice del archivo
  y se declara. Si con `date`/`cohort` falta la frontera, `Scorecard` se detiene
  **antes de correr** con el rango del archivo y el valor que usaría («los últimos 12 meses serían
  desde 2024-01»). Nada institucional se siembra. Todo lo demás tiene default.
- **Lo que se infiere y se declara** (una decisión `inferencia_*` en el trail por cada una): el
  esquema (`data.schema.columns` desde los dtypes), las categóricas (dtype `object`/`category`/
  `bool`), las predictoras (todas menos id, target, fecha/cohorte y las columnas de la regla del
  target, por D-FUGA) y los rótulos de las muestras. La estrategia de partición **sigue a lo
  declarado** (`date` → temporal, `cohort` → cohorte), no se infiere.
- **Argumentos opcionales ⊆ campos esenciales** (D-SIM-4, D-FLU-7): la firma de `Scorecard`
  expone **exactamente** los argumentos de la tabla de §3.8 (nombre, tipo y default por cada path
  esencial), ninguno más; `purpose=` enciende `governance` y con ella la ficha (sin él no hay ficha,
  D-GOB-8); `track=` enciende `tracking`. Ninguno es una hoja nueva: cada uno escribe una hoja
  existente del config. Lo que no está en esa tabla se alcanza por `sc.config` (la puerta completa).
- **`data` como `DataFrame`:** la puerta lo persiste como snapshot parquet determinista en
  `<run_dir>/<name>/input/data.parquet` y apunta `data.load.source` a esa ruta, de modo que
  `sc.config` y `sc.to_yaml()` reproducen la corrida por sí solos (la entrada `("data",
  "input_frame")` no se usa: no forma parte del config).
- **`partition="random"`:** `holdout_fraction = holdout`, `oot_fraction = 0.0` y `dev_fraction =
  1 − holdout` (`RandomSplitConfig` exige que sumen 1); no hay muestra OOT, y la puerta ajusta las
  listas de particiones de `performance.partitions`, `validation.discrimination.partitions` y
  `stability.comparisons` a las que existen, declarándolo como inferencia.
- **Dónde queda la evidencia (§8-8):** `run_dir` tiene default `"nikodym-runs"` (relativo al
  directorio de trabajo) y `name` default `"scorecard"`; la corrida escribe en `<run_dir>/<name>/`
  el layout de SDD-03 §6 (trail incluido: el preset F1 trae `audit` encendido y el trail relativo
  exige un `run_dir`, D-GOB-7). `run_dir=None` no se acepta en la puerta guiada. Una corrida
  repetida sobre el mismo `<run_dir>/<name>/` aparta la anterior a `.<name>.old.*`, que es lo que
  `nikodym.run` ya hace. La primera línea del resumen de datos dice la ruta absoluta.
  **Precisión al implementar la capa A (S17, 2026-09-19):** `nikodym.run` sustituye **entero** su
  destino al consolidar y aparta lo que había —incluido lo que la propia corrida escribió allí
  mientras corría—, así que el layout de SDD-03 §6 vive en `<run_dir>/<name>/run/` y a su lado,
  donde ninguna consolidación se los lleva, quedan `config.yaml` (el config vigente que la puerta
  reescribe en cada corrida), `input/data.parquet` (el snapshot, sólo con `DataFrame`) y
  `reports/` (el informe, con `report.output_dir` absoluto). Cada informe se asocia a la
  evidencia de SU corrida por identidad de intento, no por heurísticas sobre qué hay en `run/`:
  al arrancar, la puerta aparta el `reports/` anterior a `.reports.prev.<token>` y censa los
  hermanos `.run.old.*`/`.run.failed.*` existentes; si `nikodym.run` consolida —éxito o fallo de
  dominio—, el informe apartado va dentro del `.run.old.*` que ESA consolidación creó (cada
  corrida archivada queda completa); si el intento revienta sin consolidar, el `reports/` que
  ESTE intento escribió va dentro del `.run.failed.*` que ESTE intento dejó y el apartado vuelve
  a `reports/`, porque `run/` sigue siendo la corrida a la que pertenece. Sin hermano nuevo al
  que ir —no había corrida previa consolidada, o el fallo no dejó evidencia—, el informe se
  conserva como hermano `.reports.old.*`. Nunca se borra un informe ni se asocia al trail de
  otra corrida (pasadas de Codex sobre A2, A2-bis y A2-ter). La carpeta admite **una corrida a
  la vez**: un candado `.lock` en `<run_dir>/<name>/` —que el sistema operativo suelta si el
  proceso muere— rechaza la segunda con un error legible antes de mover nada (pasada de cierre
  de Codex sobre la capa A).
- **Precisión (pasada de cierre de Codex, S17):** la puerta arma las **tres** reglas del target
  —«malo», «bueno» e «indeterminado»—, no sólo la de «malo»: con `good_rule` vacía el motor toma
  por bueno todo lo que no es malo, incluidos los resultados vacíos (operaciones sin desempeño
  maduro), que entrarían al ajuste como no-default sin error alguno. Un resultado vacío en la
  columna del target —o en la columna de la regla— es desconocido: queda indeterminado, se
  puntúa, no entra al ajuste, y la puerta lo declara al trail (`inferencia_resultado_vacio`,
  con la cifra) y en el resumen de datos.
- `sc.config` es el `NikodymConfig` completo que corre; `sc.study` el `Study`; `sc.config_hash`
  la identidad. `sc.to_yaml()` exporta el config para la puerta completa o la pantalla.

### 3.2 D-FLU-2 — Etapas y lo que dice cada resumen

Nombres estables en inglés, rótulos en español. Cada resumen: 3–8 líneas, una tabla de decisión y
las alertas en palabras.

| Etapa | Rótulo | Lo que dice | Tabla de decisión |
|---|---|---|---|
| `data` | Datos y muestras | filas, malos y tasa; por muestra (DEV/HO/OOT/TTD) con fechas o cohortes; qué se infirió; dónde queda la evidencia | filas y malos por muestra |
| `eda` | Análisis exploratorio | la tasa de malos en el tiempo y su banda; las marcas de calidad del archivo | tasa de malos por período o cohorte con la banda de estabilidad |
| `binning` | Tramos y WoE | variables tramificadas, descartadas por no tramificables, alertas de monotonía en HO/OOT (§3.6) | IV por variable con tendencia y número de tramos |
| `selection` | Selección de variables | cuántas entran, cuáles salen y por qué (IV, correlación, VIF, estabilidad, decisión humana) | IV por muestra, correlación máxima, VIF (§3.6) |
| `model` | Modelo | variables finales, iteraciones del stepwise y qué salió en cada una, ajuste (pseudo-R², AIC, LLR) | coeficientes con signo, p-valor y contribución al IV |
| `scorecard` | Tarjeta de puntuación | escala (PDO, puntaje y odds objetivo), rango de puntajes | puntos por tramo |
| `calibration` | Calibración | ancla y fuente, desplazamiento aplicado, ranking preservado y empates | PD media por muestra antes y después del ajuste |
| `performance` | Desempeño | AUC, Gini y KS por muestra y la caída DEV→OOT en palabras | deciles por muestra (la tabla de rendimiento) |
| `stability` | Estabilidad | peor PSI con su banda, CSI peor por variable | PSI/CSI por comparación con banda |
| `validation` | Validación formal | estado técnico en palabras y qué prueba lo decidió | pruebas por familia con veredicto |
| `report` | Informe y ficha | dónde quedó cada archivo | — |

Cada resumen usa **sólo lo que publica su etapa o una anterior**: `run(until=)` habla al terminar
el prefijo sin recalcular nada (la discriminación es de `performance`, Brier y las pruebas son de
`validation`, y ninguna cifra que el árbol no publique —no existe un ECE— entra a un resumen). Las
tablas y las palabras son las que ya publican las cards y los mapas de rótulos del informe: **una
sola fuente** (D-SIM-5). En notebook el resumen se pinta por `_repr_html_`; en consola, texto;
en pantalla, el panel de Resultados que ya existe, alineado a esta misma fuente.

### 3.3 D-FLU-3 — Parar, decidir y seguir

```python
sc.run(until="selection")
sc.exclude(["saldo_promedio_6m", "n_productos"], reason="inversión de negocio")
sc.merge_bins("antiguedad_meses", [2, 3], reason="tramos con la misma tasa")
sc.resume()                             # corrida nueva y completa sobre el config vigente
```

- `run(until=<etapa>)` ejecuta el **prefijo** del pipeline hasta esa etapa inclusive (es
  `run.steps` recortado: una corrida parcial con su propio `config_hash`, `run_id` y lineage).
  **`resume()` es una corrida nueva y completa** sobre el config vigente (D-SIM-6): `nikodym.run`
  con `run.steps` completo, `run_id`, lineage y `run_dir` propios; la corrida anterior queda como
  respaldo lateral (`.<nombre>.old.*`, comportamiento que `nikodym.run` ya tiene). No se reutilizan
  artefactos entre corridas y la puerta D-ART no interviene: nada queda obsoleto bajo un lineage
  nuevo. El costo de recomputar se mide en la capa A (cifra 4 de SDD-31 §5); la reutilización queda
  como candidata con evidencia (§3.7).
- Decisiones humanas de la capa A: `exclude(cols, reason=)`, `keep(cols, reason=)`,
  `merge_bins(col, bins, reason=)`, `set_bins(col, cuts, reason=)`. Cada una escribe las hojas de
  config que la hacen efectiva en **todo** el pipeline: `exclude` → `selection.force_exclude`;
  `keep` → `selection.force_include` **y** `model.force_include` (sólo con
  la primera, `model` no vería una variable que `selection` descartó por IV, correlación o VIF);
  `merge_bins`/`set_bins` → `binning.variable_overrides`. La última decisión sobre una variable
  gana y la retira de la lista contraria, porque `selection` rechaza una variable en las dos
  listas a la vez (`selection/config.py:562`).
  **Dos correcciones medidas al implementar (S17, 2026-09-19):** (1) `exclude` **no** escribe
  `model.force_exclude`: el motor rechaza un override de `model` sobre una variable que la
  selección ya descartó (`model/step.py::_validate_force_overrides`, «los overrides de model deben
  referirse a features seleccionadas»), y con `selection.force_exclude` la variable no llega al
  modelo; sí se retira de `model.force_include`. (2) `merge_bins`/`set_bins` **no se pueden
  implementar con cero hojas nuevas**: `binning.variable_overrides` (`VariableBinningConfig`)
  lleva tipo, monotonía, máximo de tramos, tamaño mínimo y umbral de categorías raras, **no
  cortes ni categorías** —la frase de §2 «cortes y categorías por variable» era falsa—, y
  `user_splits` no existe en `src/nikodym`. Fijar cortes exige una hoja nueva (`user_splits` /
  `user_splits_fixed` de OptBinning en `VariableBinningConfig`); es una decisión de Cami (§8-9)
  y la capa A las deja fuera. En la corrida siguiente, `Scorecard` emite **un** evento
  `decision` al trail con los seis campos que `DecisionRecord` ya materializa
  (`governance/model_card.py:31`: `step="scorecard_guided"`, `regla="decision_del_usuario"`,
  `umbral=None`, `valor={hoja: valor}`, `accion=<exclude|keep|merge_bins|set_bins>`, `ts`) **más**
  dos claves aditivas del payload, `autor="usuario"` y `motivo`, que el trail conserva y la ficha
  ignora (misma regla que D-ERR-6: un lector existente no se entera de las claves nuevas).
  **Propietarios distintos, sin duplicado:** ese evento registra la *intención*; los eventos que
  ya emiten los motores por los mismos overrides (`model/step.py:192-199`: `force_include`/
  `force_exclude`) registran la *ejecución*; el resumen final los une por hoja. La ficha (con
  `purpose=`) muestra la decisión con sus seis campos; **el motivo no llega a la ficha en la capa
  A**: extender `DecisionRecord` es una enmienda a D-GOB que va con la ficha renderizada de la
  capa C. El resumen final lista siempre decisión y motivo desde el trail.
- `run()` sobre `sc.config` sin la puerta guiada reproduce los mismos **resultados**: las decisiones
  viven en el config, no en el objeto. La **procedencia** (inferencias y motivos en el trail) es de
  la puerta guiada y se declara (D-SIM-1).

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

### 3.6 D-FLU-6 — Lo que se adopta del banco en la capa A (dos artefactos aditivos, separados)

Las tablas estables de F1 (`selection_table`, las tablas de binning) **no cambian de esquema**: los
diagnósticos nuevos son artefactos aparte, con clave propia, que los consumidores 1.x pueden
ignorar y cuyos goldens nacen con ellos.

1. **`("selection", "iv_by_partition")`** — una fila por variable y partición (`desarrollo`,
   `holdout`, `oot`), columnas `feature`, `partition`, `n`, `n_bad`, `iv`, `not_evaluable_reason`.
   Metodología: los tramos y el WoE son los fijados en desarrollo (`binning` ya transforma todas las
   particiones con ellos); el IV se calcula con la fórmula de SDD-07 sobre las filas de esa partición
   con target no nulo; Missing y Special cuentan como tramos si existen. Casos borde: partición
   ausente → sin fila; partición con una sola clase → `iv` nulo con causa `single_class` (no hay
   umbral de filas propio: `data.partition.min_bads_per_partition` ya garantiza los malos mínimos
   de cada partición con target, y ese es el único criterio de tamaño). Ningún umbral nuevo: el
   descarte sigue siendo por `min_iv` en desarrollo. Evidencia: es la primera pregunta de un
   validador y el flujo del banco descartaba por «IV HO/OOT». **Precisión al implementar (S17):**
   los tramos son los de desarrollo y las distribuciones (y por tanto el WoE de cada tramo) son
   **las de cada muestra**; así el IV de desarrollo coincide con el que publica el binning
   (medido: diferencia 5,6e-17 sobre el dataset del paquete). Un tramo sin malos o sin buenos en
   la muestra no aporta al IV, como OptBinning con un tramo vacío.
2. **`("binning", "event_rate_by_partition")`** — una fila por variable, tramo y partición, con
   `feature`, `bin_id`, `bin_label`, `partition`, `n`, `n_bad`, `event_rate`, `inverts`. Metodología:
   la tendencia de referencia es la de desarrollo (`monotonic_trend` efectivo); un tramo `inverts`
   cuando el signo de la diferencia de tasa con el tramo anterior contradice esa tendencia; Missing y
   Special quedan fuera de la comparación; empates (diferencia cero) no invierten; un tramo con
   menos de **30 filas** en la partición no se evalúa (`inverts` nulo). Ese 30 es una **constante
   del diagnóstico** —filas por tramo, no malos por partición: no tiene relación con
   `min_bads_per_partition` ni con ningún campo del config, y se elige por ser la cifra que un
   validador ya reconoce como grupo mínimo (el default de Hosmer-Lemeshow)—. El resumen de binning
   marca «invierte en <muestra>» por variable. Sólo alerta; no descarta.

Además, sin tocar motores: la traza legible del stepwise, `merge_bins`, `exclude` con motivo,
`name=` y `compare(other)` (dos corridas lado a lado: cifras, variables y decisiones).

### 3.7 Candidatos anotados, no adoptados (cada uno espera su evidencia)

Muestreo con control de PD por período; escala maestra y puntos de corte (módulo propio); test de
representatividad de tramos; bootstrap de coeficientes; export SQL de la tarjeta. Entran por su
enmienda cuando un caso real muestre que el default falla o que el módulo falta (SDD-31 D-SIM-3).

### 3.8 D-FLU-7 — Esenciales por sección (propuesta para §8-4)

| Sección | Esenciales | Hoy visibles |
|---|---|---|
| `data` | archivo, regla del target, identificador, fecha o cohorte, frontera OOT (o partición aleatoria), proporción de holdout | 158 |
| `eda` | ninguno: todo default; el resumen lo muestra | 17 |
| `binning` | `feature_columns`, `categorical_columns`, `max_n_bins`, `min_bin_size`, `monotonic_trend` | 42 |
| `selection` | `min_iv`, `correlation.threshold`, `vif.threshold` | 33 |
| `model` | `stepwise.enabled`, `stepwise.entry_p_value`, `stepwise.exit_p_value`, `sign_policy.action` | 23 |
| `scorecard` | `pdo`, `target_score`, `target_odds` | 17 |
| `calibration` | `anchor_source`, `target_pd` | 16 |
| `performance` | `n_deciles` | 12 |
| `stability` | `psi_stable_threshold`, `psi_review_threshold` | 16 |
| `validation` | `families` | 28 |
| `report` | `document.model_name`, `document.entity`, `document.portfolio`, `document.author`, `formats` | 33 |
| `governance` | `purpose`, responsable, periodicidad de revisión | 14 |

De 409 campos visibles a **≈ 37 esenciales**; el resto se pliega en «Avanzado» (D-FLU-8). La marca
es un metadato del schema (`json_schema_extra={"ui_essential": True}`), con golden bidireccional.

**Mapeo exhaustivo path esencial → argumento de `Scorecard`** (D-SIM-4: la firma expone estos y
ninguno más; el default es el del preset F1 salvo que se indique):

| Path esencial | Argumento | Tipo · default |
|---|---|---|
| `data.load.source` | `data` | ruta (csv/parquet/xlsx) o `DataFrame` · obligatorio |
| `data.target.bad_rule` | `target` | nombre de columna 0/1, o regla `{"col","op","value"}` · obligatorio |
| `data.schema.unique_keys` (columna) o `data.schema.index_col` (índice nombrado del archivo) | `id` | `str` · opcional: una columna va a `unique_keys`, el nombre del índice a `index_col`; sin él, el índice del archivo, declarado |
| `data.partition.strategy` (con `date_col` / `cohort_col`; con `random`, `holdout_fraction=holdout`, `oot_fraction=0.0`, `dev_fraction=1−holdout`) | `date=` / `cohort=` / `partition="random"` | `str` · obligatorio uno de los tres |
| `data.partition.strategy.oot_from` / `.oot_cohorts` | `oot_from=` / `oot_cohorts=` | `str` / `list[str]` · obligatorio con `date`/`cohort` |
| `data.partition.strategy.holdout_fraction` | `holdout=` | `float` · 0.2 |
| `binning.feature_columns` / `.categorical_columns` | `features=` / `categorical=` | `list[str]` · inferidas (§3.1) |
| `binning.max_n_bins` / `.min_bin_size` / `.monotonic_trend` | `max_bins=` / `min_bin_size=` / `monotonic=` | `int` 6 / `float` 0.05 / literal `"auto_asc_desc"` |
| `selection.min_iv` / `.correlation.threshold` / `.vif.threshold` | `min_iv=` / `max_correlation=` / `max_vif=` | 0.02 / 0.75 / 5.0 |
| `model.stepwise.enabled` / `.entry_p_value` / `.exit_p_value` | `stepwise=` / `p_enter=` / `p_exit=` | `True` / 0.05 / 0.05 |
| `model.sign_policy.action` | `sign_policy=` | literal de `SignPolicyConfig.action` · `"flag"` |
| `scorecard.pdo` / `.target_score` / `.target_odds` | `pdo=` / `target_score=` / `target_odds=` | 20 / 600 / 50 |
| `calibration.anchor_source` / `.target_pd` | `anchor=` / `target_pd=` | `"development_observed"` / `None` |
| `performance.n_deciles` | `deciles=` | 10 |
| `stability.psi_stable_threshold` / `.psi_review_threshold` | `psi_thresholds=` | `(0.10, 0.25)` |
| `validation.families` | `validation=` | `("discrimination", "calibration", "stability")` |
| `report.document.model_name` / `.entity` / `.portfolio` / `.author` | `document=` | `dict` · vacío (la portada declara «sin dato», como hoy) |
| `report.formats` | `formats=` | los del preset (`html` siempre; `pdf`/`md`/`docx` sin detener la corrida si falta el extra) |
| `governance.purpose` / responsable / periodicidad de revisión | `purpose=` / `owner=` / `review_every=` | `str` · `None` (sin ficha) |
| `tracking` (sección entera con sus defaults) | `track=` | URI o ruta · `None` |

Los nombres de los argumentos de gobernanza y de informe se fijan al implementar sobre los campos
reales de `GovernanceConfig` y `DocumentConfig`; el mapeo (un argumento por path esencial) es el
contrato, y el golden de esenciales lo ata en los dos sentidos.

### 3.9 D-FLU-8 — Pantalla

Cada sección pinta sus esenciales abiertos y un único bloque «Avanzado» **cerrado** con la cifra de
cuántos campos avanzados difieren del default; el resto de la mecánica (grupos, ayuda, validación
en vivo, decisiones institucionales) no cambia. El panel de Resultados, que ya pinta por etapa,
consume la misma fuente que `summary()`.

**Implementado en la capa B (S18, 2026-09-21), con tres precisiones medidas:** (1) la división la
enciende una **marca de sección** en el schema (`ui_essentials_declared`, `declara_esenciales` en el
core) y no el conteo de campos marcados, porque `eda` declara cero esenciales y también se divide,
mientras que una sección de un módulo que aún no pasó por su enmienda (supervivencia, IFRS 9,
provisiones) se pinta entera; (2) una marca puede vivir dentro de un sub-modelo, así que la división
lo **poda** —la vista de esenciales recibe sólo sus hojas marcadas y «Avanzado» el resto, con el
mismo `path`—, y una **unión discriminada o una lista son atómicas** (la estrategia de partición va
entera a esenciales: el selector de variante no se pinta dos veces), de modo que en `data` la
pantalla abre cuatro campos —la fuente, la llave de unicidad, la regla de «malo» y la estrategia de
partición con su frontera y su holdout dentro—; (3) la cifra cuenta las **hojas** plegadas cuya clave está
presente en el config con un valor distinto del catálogo de defaults efectivos (una obligatoria sin
default cuenta cuando el usuario la escribió; sin catálogo no se afirma nada), y el bloque se abre
solo ante un error del motor en un campo plegado —no se puede cerrar mientras dure— o ante un foco
pedido hacia uno de ellos.

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
| **A** | Puerta guiada por código: entrada mínima e inferencias, `run`/`until`/`resume`, decisiones humanas, resúmenes por etapa, resumen final, `compare`, `track=`, `purpose=`, los dos artefactos de §3.6, `raise_on_error`, notebook mínimo. Sale en 1.17.0 **declarada experimental** en copy público y CHANGELOG hasta que cierre B (D-SIM-1) | las cinco cifras ancladas; notebook en CI; `config_hash` de `sc.config` == el del YAML exportado; `run()` y `resume()` tras `run(until)` dejan artefactos idénticos sin decisiones; los goldens de `selection_table` y de las tablas de binning **no se mueven** |
| **B** | Pantalla esenciales/«Avanzado» con su golden; Excel opcional y `export()`; Resultados sobre la fuente de `summary()` | golden de esenciales; copy gate; Excel byte a byte con las tablas del informe |
| **C** | Informe: página ejecutiva = resumen final; tipografía y marca del sitio; ficha renderizada (lo que ENTREGABLES-LEGIBLES pedía y no depende de la API) | goldens del informe declarados antes de moverlos |

### 3.13 D-FLU-12 — Presupuesto de perillas: cero. Qué NO se configura

Cero hojas nuevas de config: cada argumento de la puerta guiada escribe una hoja existente y
`ui_essential` es metadato. No se configura: el formato ni el idioma de los resúmenes, la
numeración y los nombres del Excel, la regla de inferencia del esquema y de las predictoras, el
orden de las etapas, los rótulos, ni qué tabla es «de decisión» en cada etapa. Son constantes con
su razón: cada una de ellas es exactamente lo que hoy obliga al usuario a saber antes de empezar.

## 4. Contratos de datos (I/O)

- **Entrada:** ruta a csv/parquet/xlsx, o `pandas.DataFrame` que la puerta persiste como snapshot
  parquet bajo `<run_dir>/<name>/input/` y referencia desde `data.load.source` (§3.1); target como
  columna o regla en la forma de `data.target.bad_rule`; `date` o `cohort` nombran columnas
  existentes; `id` una columna (`unique_keys`) o el índice nombrado (`index_col`).
- **Salida:** `sc.study` (el `Study`), `sc.config` (`NikodymConfig`), `sc.results[<etapa>]` (los
  DataFrames de decisión), `sc.summary(<etapa>|None)`, y en disco el layout de SDD-03 §6 bajo
  `<run_dir>/<name>/` más `excel/` si se pidió.
- **Invariantes:** `config_hash(sc.config)` es el de la corrida completa y coincide con el del YAML
  exportado; una corrida parcial (`run(until=)`) tiene su propio hash porque `run.steps` entra al
  hash; `resume()` produce los mismos artefactos que `run()` sobre el mismo config; toda decisión
  humana aparece una vez en el config y una vez en el trail de la corrida que la ejecuta.

## 5. Casos borde

Sin `date` ni `cohort` (hay que declarar `partition="random"`; estabilidad temporal «No evaluable»
con causa); `date`/`cohort` sin frontera OOT (se detiene antes de correr con el rango y el valor
sugerido); sin `purpose=` (no hay ficha; el resumen final lista igual las decisiones); `id` ausente
(índice del archivo, declarado); `id` con duplicados (falla la unicidad de `unique_keys` con el
mensaje del motor); target con nulos (TTD: se puntúa, no se ajusta);
categórica con cardinalidad alta (`cat_cutoff` de fábrica agrupa el resto y el resumen lo dice);
todas las variables descartadas (el modelo falla con el mensaje del motor; los resúmenes anteriores
quedan); `merge_bins` sobre tramos no adyacentes (error legible: el motor exige adyacencia);
`resume()` sin `run(until)` previo (corre todo); `track=` sin el extra instalado (mensaje con el
comando exacto, como `polars`).

## 6. Gates y controles negativos de ESTA enmienda

1. Golden de las cinco cifras del scorecard (SDD-31 §5) y del tope de esenciales por sección.
2. El notebook mínimo ejecutado en CI; control negativo: una línea de más lo pone rojo.
3. `config_hash(sc.config) == config_hash(load_config(sc.to_yaml()))`.
4. **Paridad computacional:** `run()` y `run(until="model") + resume()` sin decisiones humanas
   producen la misma **proyección canónica** —`study.results` (métricas planas) y los DataFrames y
   DTOs de los dominios de cálculo (`eda`, `binning`, `selection`, `model`, `scorecard`,
   `calibration`, `performance`, `stability`, `validation`), serializados sin los campos de
   procedencia (`run_id`, sellos de tiempo, rutas, `created_from_lineage_at`, lineage)—; `report`
   y `audit` quedan fuera de la comparación. Un segundo aserto comprueba que `run_id` y lineage
   **sí** son distintos. El helper de esa proyección vive en `tests/` y nace con la capa A.
5. Una decisión humana aparece en el trail con motivo y, con `purpose=`, en la ficha; control
   negativo: retirar la emisión → gate rojo.
6. Los resúmenes no contienen identificadores del motor (gate de códigos internos extendido).
7. Los dos artefactos de §3.6 son aparte: los goldens actuales de `selection_table` y de las tablas
   de binning **no se mueven**; los nuevos nacen con golden propio y sus casos borde (partición con
   una clase, tramo con pocas filas, Missing/Special) con test nacido rojo.
8. Con `date`/`cohort` y sin frontera OOT la puerta se detiene antes de correr (test con el mensaje
   y el valor sugerido); sin eje y sin `partition="random"`, también.
9. El Excel opcional reproduce byte a byte las tablas de los exports del informe.

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
| 8-8 | Dónde escribe la puerta guiada sin `run_dir` (decidido por el writer tras la pasada 2 de Codex; veto de Cami) | (a) **default `"nikodym-runs"` relativo al directorio de trabajo, con `name="scorecard"`**, y la ruta absoluta en la primera línea del resumen; (b) exigir `run_dir` siempre | **(a)**: quien llama a `Scorecard(...).run()` pide un modelo con su evidencia, y el notebook mínimo no gasta una línea en ello; `nikodym.run(run_dir=None)` sigue sin escribir nada (D-GOB-6) |

**Respuestas de Cami (2026-09-18, interactivas): (a) en los siete.** Vigente: la puerta guiada se
llama `nikodym.Scorecard`; la escala maestra es el hito H5 del roadmap; la capa A sale en 1.17.0 y
B + C en 1.18.0; la tabla de §3.8 es borrador aprobado y sus rótulos se revisan contra la pantalla
al implementar; el notebook mínimo es el único ejemplo canónico; los nombres del Excel son los de
§3.5.

**8-2, superada el mismo día tras la pasada 1 de Codex** (ver más abajo). Tras la tabla y sus
respuestas, la §13 obligatoria de la plantilla cierra el documento.

| # | Decisión | Opciones | Recomendación |
|---|---|---|---|
| 8-9 | **Cortes por variable para `merge_bins`/`set_bins`** (abierto por el writer en S17, 2026-09-19, al medir que `binning.variable_overrides` no lleva cortes y que `user_splits` no existe en el motor) | (a) **una hoja nueva `user_splits: tuple[float, ...] \| None` (y `user_splits_fixed`) en `VariableBinningConfig`, cableada a `binning_fit_params[col]["user_splits"]` de OptBinning**, como excepción justificada al presupuesto cero: es una decisión humana del flujo del banco (`categorizacion_manual`), no un default que falle; (b) `merge_bins` sólo, implementado bajando `max_n_bins` de la variable (OptBinning reoptimiza y puede juntar otros tramos: no hace lo que el usuario pidió); (c) dejar las dos fuera de la puerta guiada hasta la escala maestra (H5) | **(a)**: sin cortes fijos la decisión humana «junta estos dos tramos» no existe en ninguna puerta, y (b) mentiría. Entra en la capa B con su golden de `HOJAS_DEL_FORMULARIO` (+2) y su test de paridad |

**8-2, superada el mismo día tras la pasada 1 de Codex:** inferir el corte OOT contradecía D-OBL-5
(«no se siembra una `partition.strategy` por defecto»). Cami eligió **respetar D-OBL**: la
estrategia sigue a lo declarado (`date` → temporal, `cohort` → cohorte, sin eje `partition="random"`
explícito) y la **frontera OOT se exige**; si falta, la puerta se detiene antes de correr con el
rango del archivo y el valor que usaría. Las otras tres decisiones contractuales de esa pasada
(adelanto declarado, paridad de resultados con procedencia declarada, `resume()` como corrida
nueva) están en SDD-31 §12.

## 13. Simplicidad (SDD-31)

Sección obligatoria de la plantilla desde el 2026-09-18; aquí remite a donde cada punto está
especificado, para que el agente que implemente la capa A no tenga que reconstruirlo.

- **Entrada mínima (§3.1):** datos (ruta o `DataFrame`, persistido como snapshot), regla o columna
  del target, eje temporal (`date` o `cohort`) **con su frontera OOT** o `partition="random"`
  explícito (D-OBL-5); `id` opcional. Se infieren y se declaran en el trail: el esquema, las
  categóricas, las predictoras (D-FUGA) y los rótulos de las muestras.
- **Qué NO se configura (§3.13):** el formato y el idioma de los resúmenes, la numeración y los
  nombres del Excel, la regla de inferencia del esquema y de las predictoras, el orden de las
  etapas, los rótulos, qué tabla es «de decisión» en cada etapa, el umbral de 30 filas por tramo
  del diagnóstico de monotonía (§3.6). Cada uno es una constante con su razón.
- **Campos esenciales (§3.8):** ≈ 37 en doce secciones, ninguna sección por encima del tope de 6;
  mapeo exhaustivo path → argumento de `Scorecard`; el resto se pliega en «Avanzado» (capa B).
- **Presupuesto de perillas:** **cero** hojas nuevas de config. `ui_essential` es metadato del
  schema; cada argumento de la puerta guiada escribe una hoja existente; los dos diagnósticos del
  banco son artefactos aparte sin umbral configurable (§3.6).
- **Resumen por etapa (§3.2):** diez etapas con rótulo en español, 3–8 líneas, una tabla de decisión
  y alertas; una sola fuente para texto, `_repr_html_` y pantalla; cada uno usa sólo lo que publica
  su etapa o una anterior. Decisiones humanas admitidas: `exclude`, `keep`, `merge_bins`,
  `set_bins` (§3.3).
- **Notebook mínimo (§3.11):** «Tu primer scorecard en ≤ 25 líneas» (SDD-31 §12.2): construir,
  correr, leer el resumen, una decisión humana, `resume()`, exportar; ejecutado en CI.
- **Las cinco cifras (SDD-31 §5), línea base y objetivo:** líneas de usuario 83 + ~60 → ≤ 25;
  esenciales por sección: todos (409 en 12) → ≤ 6 por sección (≈ 37); perillas de las doce
  secciones: 409 → sin crecer; segundos al primer resumen: sin resumen hoy → ≤ 30 s con el dataset
  del paquete; conceptos antes del primer resultado: ≥ 8 (`standard_preset`, `materialize`,
  `NikodymConfig`, `run`, `Study`, `run_context`, `artifacts.get`, dominio/clave) → ≤ 5. La capa A
  mide la línea base exacta sobre `fcd058d` antes de escribir código y ancla el después en su
  golden.
