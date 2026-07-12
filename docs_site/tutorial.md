# Tutorial: tu primera scorecard (F1)

Este tutorial recorre el pipeline **F1** (scorecard de comportamiento) de extremo a extremo:
elegir datos → configurar → correr con el preset estándar → leer los artefactos → interpretar cada
métrica. Al final tendrás una scorecard entrenada, calibrada y auditada, y sabrás qué mirar en cada
paso para decidir si el modelo es apto.

Los números que aparecen a lo largo del tutorial provienen de una **corrida de ejemplo** real sobre
el dataset sintético `consumo_comportamiento` (la misma que alimenta la demo). No están inventados:
son la salida determinista del pipeline con la semilla del preset. Los tuyos coincidirán bit a bit si
usas el mismo config, la misma semilla, los mismos datos y el mismo entorno (versiones de librerías / SO).

!!! note "Antes de empezar"
    Lee [Conceptos](concepts.md) para el modelo mental (`run` → `Study`, artefactos *namespaced* por
    dominio, el config *es* el experimento). Aquí asumimos ese marco.

## Requisitos

El pipeline F1 vive tras el extra `scoring` (optbinning + statsmodels + sklearn):

```bash
pip install 'nikodym[scoring]'
```

## Los seis pasos del pipeline F1

Una corrida F1 encadena estos pasos, cada uno gobernado por su sección del `NikodymConfig` y cada uno
publicando artefactos bajo su dominio:

1. **binning** — discretiza cada variable en *bins* con *Weight of Evidence* (WoE) y monotonía.
2. **selección** — filtra variables por IV, correlación y VIF.
3. **modelo** — regresión logística con *stepwise* (statsmodels).
4. **scorecard** — traduce los coeficientes a puntajes enteros (escala PDO / *target odds*).
5. **calibración** — ancla la PD a un nivel de negocio (*through-the-cycle*).
6. **desempeño / estabilidad** — discriminación (AUC/KS/Gini) y PSI/CSI por partición.

---

## Paso 1 — Elegir los datos

La librería trae datasets sintéticos deterministas para probar el pipeline sin datos propios.
`list_datasets()` los enumera; `materialize()` escribe el parquet en un *workdir*:

```python
from pathlib import Path
from tempfile import mkdtemp

from nikodym.ui.datasets import list_datasets, materialize

for ds in list_datasets():
    print(ds["id"], "—", ds["name"])

workdir = Path(mkdtemp(prefix="nikodym-tutorial-"))
data_path = materialize("consumo_comportamiento", workdir=workdir)
```

Usaremos `consumo_comportamiento`: una **cartera de consumo de 6.000 filas** con cinco features de
comportamiento (`ingreso_mensual`, `deuda_ingreso`, `utilizacion_linea`, `mora_max_12m`,
`antiguedad_meses`), un `segmento` categórico, una `cohorte` trimestral para partición temporal y el
`bad_flag` como target binario.

!!! tip "Otros datasets del catálogo"
    `hipotecario_comportamiento` (4.000 filas, cartera de menor riesgo) sirve para contrastar; y
    `consumo_drift` (6.000 filas) introduce **deterioro temporal** entre cohortes para demostrar
    PSI/CSI. Todos comparten el mismo esquema, así que corren con el mismo config.

Cifras — fixture `web/src/fixtures/demo/datasets.json`.

## Paso 2 — Configurar con el preset estándar

En vez de escribir el `NikodymConfig` a mano, el preset F1 curado trae un config completo y
consistente (esquema, partición por cohorte, binning, selección, modelo, scorecard, calibración,
desempeño, estabilidad y reporte). Solo hay que apuntarlo al archivo de datos:

```python
from nikodym.core.config import NikodymConfig
from nikodym.ui.presets import standard_preset

preset = standard_preset()
cfg_dict = preset["config"]
cfg_dict["data"]["load"]["source"] = str(data_path)   # apunta al parquet materializado
config = NikodymConfig.model_validate(cfg_dict)
```

Vale la pena saber qué decide este preset, porque son las palancas que editarías en un config propio:

| Sección | Decisión del preset | Por qué importa |
|---|---|---|
| `partition` | Cohorte; **OOT = `2024Q2`**, holdout 20 % | Separa Dev / Holdout / OOT para medir degradación temporal |
| `binning` | máx. 6 bins, monotonía `auto_asc_desc`, solver MIP | WoE monótono e interpretable |
| `selection` | `min_iv = 0.02`, corr `> 0.75`, VIF `> 5` | Descarta variables débiles o redundantes |
| `model` | logit + stepwise, signo esperado **negativo** | Coeficientes con dirección de riesgo coherente |
| `scorecard` | **PDO 20**, *target score* **600** a *odds* **50:1** | Escala de puntaje del negocio |
| `calibration` | ancla `target_pd = 0.20`, *through-the-cycle* | PD promedio anclada a un nivel de política |

Cifras — fixture `web/src/fixtures/demo/preset.json`.

## Paso 3 — Correr y verificar el estado

`nikodym.run(config)` ejecuta el pipeline completo y devuelve un `Study` reproducible:

```python
import nikodym

study = nikodym.run(config)
assert study.run_context.status == "done"
```

!!! warning "Chequea el estado siempre"
    `run` es *fail-loud pero no explosivo*: ante un fallo devuelve el `Study` **parcial** con
    `status == "failed"` (el error queda en el audit-trail y el lineage, no se silencia). El consumidor
    por código **debe** verificar `study.run_context.status == "done"` antes de usar los resultados.

Los resultados no viven en un `dict` plano sino en el `ArtifactStore`, accesible con
`study.artifacts.get(<dominio>, <clave>)`. Las secciones siguientes recorren cada dominio.

---

## Paso 4 — Leer e interpretar los artefactos

### Binning y WoE

```python
tables = study.artifacts.get("binning", "tables")     # WoE/IV por variable
summary = study.artifacts.get("binning", "summary")   # IV agregado por variable
```

El binning discretiza cada variable y le asigna un **WoE** por bin (log-odds de *good* vs *bad*
relativo a la población) y un **IV** (*Information Value*) que resume su poder predictivo. En la
corrida de ejemplo las seis variables se binnearon sin descartes, con estos IV:

| Variable | IV | Monotonía |
|---|---|---|
| `ingreso_mensual` | 0.305 | descendente |
| `deuda_ingreso` | 0.164 | ascendente |
| `utilizacion_linea` | 0.061 | ascendente |
| `antiguedad_meses` | 0.041 | descendente |
| `mora_max_12m` | 0.022 | ascendente |
| `segmento` | 0.003 | — (categórica) |

!!! note "Cómo leer el IV"
    Regla de dedo estándar (Siddiqi): **< 0.02** no predictivo · **0.02–0.1** débil · **0.1–0.3**
    medio · **0.3–0.5** fuerte · **> 0.5** sospechosamente alto (posible *leakage* o target contaminado,
    revisar). Aquí `ingreso_mensual` (0.305) es la variable más fuerte y `segmento` (0.003) es ruido.

La monotonía es clave para que la scorecard sea defendible ante un revisor: el riesgo debe moverse en
una sola dirección a lo largo de los bins. En `ingreso_mensual` la tasa de default cae de forma
monótona al subir el ingreso, y el WoE sube en consecuencia:

| Bin de `ingreso_mensual` | Tasa de default | WoE |
|---|---|---|
| `(-inf, 242796)` | 42.9 % | -0.902 |
| `[242796, 354257)` | 35.3 % | -0.582 |
| `[354257, 464805)` | 28.2 % | -0.254 |
| `[464805, 631639)` | 22.7 % | +0.036 |
| `[631639, 913197)` | 16.6 % | +0.428 |
| `[913197, inf)` | 8.3 % | +1.210 |

WoE negativo = bin **peor** que la media (más riesgo); positivo = **mejor** que la media. La monotonía
limpia (sin zig-zag) es señal de un binning sano.

Cifras — fixture `web/src/fixtures/demo/results.json` (`binning`).

### Selección de variables

```python
selected = study.artifacts.get("selection", "selected_features")
sel_table = study.artifacts.get("selection", "selection_table")
```

La selección aplica los umbrales del config. De **6 candidatas** quedaron **5**: se descartó
`segmento` por **IV bajo** (0.003 < 0.02). Tras seleccionar, la **correlación máxima** entre features
fue 0.030 y el **VIF máximo** 1.002 — es decir, ninguna multicolinealidad (VIF cercano a 1 es el ideal;
el umbral del preset era 5).

!!! tip "Qué mirar"
    Un VIF alto (> 5) o una correlación alta (> 0.75) indican features redundantes que inflan los
    errores estándar y vuelven inestables los coeficientes. Aquí el conjunto quedó limpio.

Cifras — fixture `results.json` (`selection`).

### Modelo (regresión logística)

```python
coefs = study.artifacts.get("model", "coefficients")
fit = study.artifacts.get("model", "fit_statistics")
```

El modelo es una logística sobre las columnas WoE, con *stepwise* y significancia. En la corrida de
ejemplo convergió (Newton, 6 iteraciones) con las 5 features, todas con **p-value ≪ 0.05** y **signo
correcto** (β negativo sobre WoE: más WoE → menos riesgo):

| Feature | β | p-value | Contribución al IV |
|---|---|---|---|
| `intercept` | -1.192 | ~3e-190 | — |
| `ingreso_mensual` | -1.052 | ~3e-42 | 51.4 % |
| `deuda_ingreso` | -1.078 | ~1e-28 | 27.6 % |
| `utilizacion_linea` | -1.115 | ~8e-12 | 10.3 % |
| `antiguedad_meses` | -1.081 | ~3e-07 | 7.0 % |
| `mora_max_12m` | -0.968 | ~4e-04 | 3.7 % |

Estadísticos de ajuste (partición de desarrollo, n = 3.961, 924 *bads*): **pseudo-R² de McFadden
0.097**, **AIC 3898.7**, y el test de razón de verosimilitud (LLR) con p ≈ 8e-88 (el modelo es
globalmente significativo).

!!! note "Cómo leer estos números"
    El **signo** es la primera revisión de sanidad: un signo invertido significa que la variable predice
    al revés de lo esperado (el preset lo marca con `sign_policy`). El **p-value** confirma que cada
    coeficiente aporta. El **pseudo-R² de McFadden** no se lee como el R² de una regresión lineal:
    valores de 0.2–0.4 ya indican muy buen ajuste; 0.097 es modesto pero típico de un *behavior
    scorecard*, donde la métrica operativa es la **discriminación** (AUC/KS), no el pseudo-R².

Cifras — fixture `results.json` (`model`).

### Scorecard

```python
scorecard = study.artifacts.get("scorecard", "scorecard")   # puntos por bin
score = study.artifacts.get("scorecard", "score")           # score por fila
```

La scorecard traduce los coeficientes a **puntos enteros** con la transformación clásica PDO. El preset
fija **PDO = 20** (cada 20 puntos las *odds* se duplican), *target score* **600** a *odds* **50:1**, con
`score_direction = higher_is_lower_risk` (más puntaje = menos riesgo). De ahí salen los parámetros de
escala **factor ≈ 28.85** y **offset ≈ 487.12**. En la corrida de ejemplo los scores de la población
caen en el rango **446–622**.

!!! tip "Interpretación de negocio"
    A los 600 puntos, por construcción, las *odds good:bad* son 50:1. Cada 20 puntos por encima duplican
    esas odds (100:1 a 620), cada 20 por debajo las parten a la mitad (25:1 a 580). Es la escala que el
    área comercial usa para fijar puntos de corte.

Cifras — fixture `results.json` (`scorecard`).

### Calibración

```python
cal = study.artifacts.get("calibration", "result")
```

La scorecard ordena bien el riesgo, pero su PD promedio no tiene por qué coincidir con el nivel de
política del banco. La calibración por `intercept_offset` corre el intercepto para anclar la PD media a
un *target*. El preset ancla a **`target_pd = 0.20`** *through-the-cycle*. En desarrollo la PD media
**cruda era 0.233** (igual a la tasa observada de default) y tras el offset de **-0.218** quedó en
**0.200** exacto. Puntos clave de la corrida de ejemplo:

- `ranking_preserved = True` y `ties_created = 0`: el ajuste **desplaza** las PD sin alterar el orden
  ni crear empates. La discriminación (AUC/KS) no cambia con la calibración; solo cambia el nivel.
- Fiabilidad (Brier / ECE) por partición — cuánto se pega la PD predicha a la observada:

| Partición | Brier | ECE |
|---|---|---|
| desarrollo | 0.161 | 0.034 |
| holdout | 0.165 | 0.039 |
| oot | 0.172 | 0.055 |

!!! note "Cómo leer Brier y ECE"
    Ambos son *menor es mejor*. El **ECE** (*Expected Calibration Error*) mide la brecha media entre PD
    predicha y default observado por decil: 0.034 en desarrollo indica una calibración muy ajustada. Que
    suba a 0.055 en OOT es esperable (los datos futuros se apartan del entrenamiento) y es justo la señal
    que la partición OOT existe para vigilar.

Cifras — fixture `results.json` (`calibration`).

### Desempeño (discriminación)

```python
disc = study.artifacts.get("performance", "discriminant_metrics")
```

La discriminación mide cuán bien el modelo separa *goods* de *bads*, evaluada en las tres particiones:

| Partición | n (bads) | AUC | Gini | KS |
|---|---|---|---|---|
| desarrollo | 3.961 (924) | 0.712 | 0.425 | 0.320 |
| holdout | 1.031 (244) | 0.695 | 0.389 | 0.312 |
| oot | 1.008 (239) | 0.656 | 0.312 | 0.252 |

!!! note "Cómo leer AUC / Gini / KS"
    - **AUC**: probabilidad de rankear un *bad* peor que un *good*. 0.5 = azar; **≥ 0.70** se considera
      aceptable para un *behavior scorecard*. Aquí 0.712 en desarrollo es razonable.
    - **Gini** = 2·AUC − 1. Es la misma información reescalada a [0, 1]; muchos equipos de riesgo lo
      reportan en vez de AUC.
    - **KS**: máxima separación entre las acumuladas de *goods* y *bads*. Valores en torno a **0.30** son
      típicos y sanos para consumo.

!!! warning "La caída Dev → OOT es la métrica que de verdad importa"
    El AUC baja de 0.712 (desarrollo) a 0.656 (OOT): ~0.056 de degradación temporal. Algo de caída es
    normal; una caída grande delataría *overfitting* o cambio de población. **Nunca reportes el modelo
    por su número de desarrollo**: el OOT es el que estima el desempeño en producción.

Cifras — fixture `results.json` (`performance`).

### Estabilidad (PSI / CSI)

```python
psi = study.artifacts.get("stability", "psi_table")
stab = study.artifacts.get("stability", "stability_metrics")
```

El PSI (*Population Stability Index*) mide cuánto se desplazó la distribución del score entre
particiones; el CSI hace lo mismo por variable. En la corrida de ejemplo todo salió **estable**:

| Comparación | PSI del score | Banda |
|---|---|---|
| dev_vs_holdout | 0.013 | estable |
| dev_vs_oot | 0.007 | estable |

El peor CSI por variable fue `mora_max_12m` con 0.010, también en zona estable.

!!! note "Umbrales de PSI/CSI"
    Convención (la misma del preset): **< 0.1** estable · **0.1–0.25** revisar · **> 0.25** inestable
    (reentrenar / investigar). PSI bajo entre Dev y OOT dice que la población no se movió; combinado con
    la caída de AUC, aquí la degradación viene de la relación variable–target, no de un cambio de mezcla.

!!! tip "Ver el efecto contrario"
    Repite la corrida con el dataset `consumo_drift` en el Paso 1: introduce deterioro temporal y verás
    el PSI dispararse a zona de revisión — el caso de uso para el que existe la métrica.

Cifras — fixture `results.json` (`stability`).

---

## Paso 5 — Exportar el reporte

El preset F1 ya incluye una sección `report`, así que la misma corrida **genera un reporte HTML
auditable** como último paso del pipeline (plantilla `scorecard_basic_v1`, con binning, selección,
modelo, scorecard, calibración, desempeño y estabilidad). No hay que llamar nada extra: al terminar
`run`, el HTML está escrito en disco y su ubicación queda publicada como artefacto del dominio
`report`:

```python
manifest = study.artifacts.get("report", "manifest")
print(manifest.path)     # p. ej. reports/scorecard_report.html
print(manifest.sha256)   # hash del HTML, para el audit-trail

result = study.artifacts.get("report", "result")
print(result.html_path)  # ruta en disco del reporte (output_dir/basename; relativa por defecto)
```

El manifiesto trae la **ruta** y el **`sha256`** del HTML — el mismo hash queda registrado en el
audit-trail (`report_export_html`), de modo que el reporte es trazable a la corrida que lo produjo.

!!! note "Ajustar el reporte"
    La sección `report` del config controla `output_dir`, `basename`, `language` (`es`) y `formats`.
    El preset emite HTML con los *assets* embebidos (un único archivo autocontenido). El export a **PDF**
    (WeasyPrint) y la narrativa por IA existen como opciones del mismo config, marcadas experimentales
    (fuera de la garantía SemVer 1.x).

!!! info "Gobernanza"
    Cada paso publica además su *card* (`study.artifacts.get("model", "model_card")`,
    `("performance", "card")`, etc.) y toda la corrida emite su *lineage bundle* (git SHA + hash de datos
    + `config_hash` + semilla + `uv.lock`). Reejecutar el mismo config con la misma semilla sobre los
    mismos datos y en el mismo entorno (versiones de librerías / SO) reproduce el resultado —y el
    reporte— bit a bit.

---

## Recapitulación

En una corrida cubriste el pipeline F1 completo:

1. Materializaste un dataset y lo apuntaste desde el preset.
2. Ejecutaste `run` y verificaste `status == "done"`.
3. Leíste, dominio por dominio, binning/WoE, selección, coeficientes, scorecard, calibración,
   desempeño y estabilidad — sabiendo **qué es bueno y qué mirar** en cada métrica.
4. Recogiste el reporte HTML auditable que la propia corrida generó.

Para el detalle de `run`, `Study` y `NikodymConfig`, ver [Referencia de la API](api.md). Para sustituir
el preset por datos y política propios, edita el `NikodymConfig` (esquema, binning, modelo, scorecard,
calibración) y apunta `data.load.source` a tu dataset real.
