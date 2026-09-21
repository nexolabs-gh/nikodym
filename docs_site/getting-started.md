# Instalación y primeros pasos

Cómo instalar Nikodym, elegir los *extras* que necesitas y correr tu primera corrida en menos de
cinco minutos. Si aún no tienes el modelo mental de `run` → `Study`, lee primero
[Conceptos](concepts.md).

## Requisitos

- **Python ≥ 3.11** (probado en 3.11, 3.12 y 3.13).
- Un gestor de paquetes: `pip` sirve; para desarrollo el proyecto usa
  [uv](https://docs.astral.sh/uv/).
- Sin dependencias del sistema para el núcleo base. Algunos *extras* pesados (p. ej. los backends
  GBDT) traen *wheels* compiladas; en plataformas sin *wheel* precompilada necesitarás un
  toolchain de C/C++, pero eso es responsabilidad de cada paquete upstream, no de Nikodym.

!!! note "Núcleo liviano por diseño"
    `import nikodym` **no** arrastra el stack de ML: las dependencias base son solo librerías
    permisivas y livianas (Pydantic, NumPy, pandas, pandera, PyArrow, joblib, Jinja2, PyYAML). La
    superficie de ejecución (`run`, `assemble_run`) se re-exporta de forma **perezosa** (PEP 562) y
    los backends pesados viven tras *extras* opcionales con import diferido. Consecuencia práctica:
    instalar y arrancar el núcleo es barato, y solo pagas el peso de un backend cuando realmente lo
    usas.

## Instalación desde PyPI

### Núcleo base

```bash
pip install nikodym
```

Con esto tienes el config declarativo (`NikodymConfig`), el contenedor `Study`, el *lineage
bundle*, el *audit-trail* y la gobernanza. Es suficiente para leer/serializar configs y para la
infraestructura de corridas, pero **no** incluye los motores de scoring/ML: para correr el pipeline
F1 necesitas el extra `scoring` (ver abajo).

### Matriz de extras

Los *extras* son selectivos: instala solo lo que tu corrida necesita. Los nombres son exactamente
los declarados en `[project.optional-dependencies]` del `pyproject.toml`.

| Extra | `pip install 'nikodym[…]'` | Qué habilita | Trae (principal) |
|---|---|---|---|
| `scoring` | `nikodym[scoring]` | **MVP scorecard (F1)**: binning/WoE con monotonía, selección, logística e inferencia, scorecard escalado, calibración y métricas. | `optbinning`, `statsmodels`, `scikit-learn>=1.6`, `scipy` |
| `ml` | `nikodym[ml]` | Modelos nativos de scikit-learn (SVM / RandomForest). | `scikit-learn>=1.6` |
| `xgboost` | `nikodym[xgboost]` | Backend GBDT XGBoost (F2). | `xgboost>=2.0`, `scikit-learn` |
| `lightgbm` | `nikodym[lightgbm]` | Backend GBDT LightGBM (F2). | `lightgbm>=4.0`, `scikit-learn` |
| `catboost` | `nikodym[catboost]` | Backend GBDT CatBoost (F2). | `catboost>=1.2`, `scikit-learn` |
| `tuning` | `nikodym[tuning]` | Optimización de hiperparámetros. | `optuna` |
| `explain` | `nikodym[explain]` | Explicabilidad (SHAP) y figuras asociadas. | `shap`, `matplotlib`, `numba`, `llvmlite` |
| `forecasting` | `nikodym[forecasting]` | Forward-looking / proyección macro (F5). | `statsmodels`, `pmdarima` |
| `survival` | `nikodym[survival]` | Modelos de supervivencia (Cox / AFT). | `lifelines` |
| `markov` | `nikodym[markov]` | Cadenas de Markov: term-structure de PD por matrices de transición. | `scipy` |
| `tracking` | `nikodym[tracking]` | Registro de corridas / *registry*. | `mlflow` |
| `ui` | `nikodym[ui]` | **Interfaz gráfica local**, lista para correr: instala el comando `nikodym-ui` y **todo lo que su formulario puede ejecutar**. | `fastapi`, `uvicorn`, `python-multipart` + los extras `scoring`, `survival`, `excel`, `docx` y `report` |
| `polars` | `nikodym[polars]` | Backend de carga de datos con Polars. | `polars` |
| `excel` | `nikodym[excel]` | Lectura de `.xlsx` en el `DataLoader`. | `openpyxl` |
| `report` | `nikodym[report]` | Figuras opcionales del reporte. | `matplotlib` |
| `docx` | `nikodym[docx]` | Export del informe a Word (`.docx`). | `python-docx` |
| `pdf` | `nikodym[pdf]` | Export del informe a PDF. **No entra en `all`** (ver aviso abajo). | `weasyprint` |
| `ai` | `nikodym[ai]` | Narrativa asistida por IA (opcional). | `anthropic` |
| `all` | `nikodym[all]` | **Meta-extra**: todo lo redistribuible de la tabla anterior. | todos los de arriba **menos `pdf`** |

Puedes combinar extras en una sola instalación:

```bash
pip install 'nikodym[scoring,xgboost,explain]'
```

!!! note "Comillas obligatorias en zsh"
    En zsh (el shell por defecto de macOS) los corchetes son *globbing*: escribe siempre el nombre
    entre comillas — `pip install 'nikodym[scoring]'` — o el shell fallará antes de llegar a pip.

!!! warning "`all` excluye copyleft a propósito, y por eso deja fuera `pdf`"
    `nikodym[all]` reúne todo lo **redistribuible**, no literalmente todo. Deja fuera dependencias
    copyleft (p. ej. `scikit-survival`, GPL-3.0); por eso el motor de supervivencia usa `lifelines`
    (MIT). El *wheel* de Nikodym no arrastra GPL/LGPL/AGPL.

    **`pdf` es el único extra de la tabla que `all` no incluye**, por la misma razón: WeasyPrint
    arrastra Pyphen, que es tri-licencia con GPL. Si quieres el informe en PDF, pídelo explícitamente
    — `pip install 'nikodym[ui,pdf]'` — y ten en cuenta que además necesita las librerías nativas de
    Pango/HarfBuzz en tu sistema.

!!! note "Grupos de desarrollo (no son extras)"
    Los grupos `test` / `lint` / `docs` / `dev` del `pyproject.toml` son **grupos de dependencias de
    desarrollo** (PEP 735): no se redistribuyen en el *wheel* y no se instalan con `pip install
    nikodym[…]`. Si vas a contribuir, clona el repo y usa `uv sync` (sincroniza el grupo `dev`, que
    incluye test/lint/docs).

## Verificación de la instalación

Comprueba que el núcleo importa y reporta versión:

```bash
python -c "import nikodym; print(nikodym.__version__)"
```

Debe imprimir la versión instalada; la última publicada es la que anuncia la portada de esta
documentación. Que este comando funcione confirma que el **núcleo base** está sano; no dice nada sobre los extras, porque
sus imports son perezosos. Para verificar que el extra `scoring` quedó disponible, la prueba real es
correr una corrida F1 (siguiente sección): si falta el extra, el motor fallará al importar
`optbinning` de forma explícita, no en silencio.

## Tu primer scorecard en 15 líneas

La **puerta guiada** construye un scorecard de comportamiento de punta a punta con lo que sólo tu
institución sabe: los datos, qué es «malo», el identificador, el eje temporal y la muestra fuera
de tiempo. Todo lo demás lo infiere, lo declara en el registro de auditoría y lo corre con
valores de fábrica que funcionan. Cada etapa cuenta lo que hizo en español, con su tabla de
decisión (`sc.results["selection"]`, `sc.summary("binning")`), y el resumen final separa si la
corrida **terminó** de si el modelo **pasa** la validación técnica.

!!! note "Tres puertas, un motor"
    La puerta guiada por código, el config completo y la pantalla producen el mismo config, la
    misma identidad (`config_hash`) y los mismos resultados; la pantalla muestra abiertos los
    mismos campos esenciales que esta firma y pliega el resto en «Avanzado». La puerta guiada es
    API estable bajo SemVer 1.x: su firma y sus resúmenes sólo crecen de forma aditiva. Necesita
    el extra `scoring`.

<!-- primer-scorecard:start -->
```python
from pathlib import Path

from nikodym import Scorecard
from nikodym.ui.datasets import materialize

# La cartera sintética de consumo del paquete (6.000 operaciones, determinista).
datos = materialize("consumo_comportamiento", workdir=Path("nikodym-runs"))

sc = Scorecard(
    data=datos,
    target="bad_flag",          # 1 = malo
    id="loan_id",
    cohort="cohorte",           # la añada de cada operación
    oot_cohorts=["2024Q2"],     # la muestra fuera de tiempo la decide la institución
    name="consumo_v01",
)
sc.run()                            # corre todo y cuenta cada etapa
sc.exclude("mora_max_12m", reason="no estará disponible al originar")
sc.resume()                         # corrida nueva y completa con la decisión; muestra el resumen final
```
<!-- primer-scorecard:end -->

`run()` imprime el resumen de cada etapa mientras corre y, en un notebook, la última línea pinta
el resumen final (también con `sc.summary()`; el de una etapa, con `sc.summary("binning")`, y su
tabla de decisión en `sc.results["binning"]`). `sc.run(until="selection")` se detiene tras esa
etapa para mirar antes de seguir. Las **decisiones humanas** —`sc.exclude(...)`, `sc.keep(...)`,
`sc.merge_bins(...)` y `sc.set_bins(...)`, siempre con `reason=`— escriben el config y quedan en
el registro de auditoría con autor y motivo en la corrida siguiente; `sc.resume()` es una corrida
nueva y completa sobre el config vigente (la anterior queda como respaldo lateral con su informe),
y `sc.compare(otra)` pone dos corridas lado a lado. Sobre los tramos de una variable numérica,
`sc.bins("antiguedad_meses")` los numera con su rango, filas, malos y WoE;
`sc.merge_bins("antiguedad_meses", [2, 3], reason=...)` junta dos tramos **adyacentes** y
`sc.set_bins("antiguedad_meses", [24, 60], reason=...)` fija los cortes que decide la
institución: las dos escriben `binning.variable_overrides` (`user_splits`, todos fijados) y en la
corrida siguiente el motor tramifica exactamente así y calcula el WoE de los tramos que resultan. La evidencia queda en `nikodym-runs/consumo_v01/`: una copia de los datos en `input/` (la que la corrida lee, con su huella en el nombre), el config completo en `config.yaml`, el
registro de auditoría y el estudio en `run/`, y el informe en `reports/`. Ese `config.yaml` es un
`NikodymConfig` entero: la puerta completa de abajo lo corre tal cual y produce los mismos
resultados.

Dos cosas que un validador pregunta primero salen ahora como artefactos aparte, sin tocar las
tablas de siempre: el **IV por muestra** (`("selection", "iv_by_partition")`, en la tabla de
decisión de la selección) y la **tasa de malos por tramo y muestra** con la marca de inversión
(`("binning", "event_rate_by_partition")`; el resumen de binning avisa «invierte la tendencia en
Holdout / Fuera de tiempo»). Sólo alertan; el descarte sigue siendo decisión tuya.

Dos entregables opcionales, a pedido y nunca la vía para ver un resultado: `sc.export_excel()`
escribe en `nikodym-runs/consumo_v01/excel/` un libro por etapa —`01 Datos y muestras.xlsx` …
`10 Validación formal.xlsx`, más `11 Decisiones.xlsx` con las decisiones del registro de
auditoría—, cada uno con el resumen de la etapa, su tabla de decisión y las tablas completas que
el informe publica para ese dominio (exige el extra `excel`); y `sc.export("corrida.zip")`
empaqueta la carpeta del proyecto entera —config, datos, evidencia, informe y Excel— para
compartirla o archivarla. En la interfaz, la pestaña Resultados muestra este mismo resumen por
etapa y el resumen final de cada corrida; y el informe (HTML, PDF, Word y fuente editable) abre,
tras la portada, con la página «Resumen de la corrida»: el mismo resumen final —qué corrió, el
estado técnico de la validación, las cifras clave, qué revisar, las decisiones humanas con su
motivo y dónde queda cada archivo—, desde la misma fuente, para el comité que lo lee.

## La puerta completa: correr el preset F1

El experimento en Nikodym *es* un `NikodymConfig` declarativo; `nikodym.run(config, run_dir=...)`
lo ejecuta de extremo a extremo, deja la evidencia de la corrida en `run_dir` y devuelve un `Study`
reproducible. El camino más corto para ver el motor funcionando es el **preset estándar F1**, que
trae un config curado y un dataset sintético de consumo, así corre sin que rellenes ningún campo.

!!! note "Requiere el extra `scoring`"
    El preset F1 ejerce el pipeline de scorecard completo. Instala `pip install 'nikodym[scoring]'`
    antes de ejecutar el ejemplo.

<!-- quickstart:start -->
```python
from pathlib import Path
from tempfile import mkdtemp

import nikodym
from nikodym.core.config import NikodymConfig
from nikodym.ui.datasets import materialize
from nikodym.ui.presets import standard_preset

# 1. Materializa el dataset sintético de consumo (determinista) en un workdir temporal.
workdir = Path(mkdtemp(prefix="nikodym-quickstart-"))
preset = standard_preset()
data_path = materialize(preset["dataset_id"], workdir=workdir)

# 2. Toma el config F1 curado y apúntalo al archivo de datos recién materializado.
cfg_dict = preset["config"]
cfg_dict["data"]["load"]["source"] = str(data_path)
config = NikodymConfig.model_validate(cfg_dict)

# 3. Ejecuta la corrida completa y verifica el estado ANTES de leer resultados. `run_dir` es
#    donde queda su evidencia: el audit-trail que el preset trae encendido y, si declaras la
#    sección `governance`, la ficha del modelo.
study = nikodym.run(config, run_dir=workdir / "corrida")
assert study.run_context.status == "done"

# 4. Accede a los resultados namespaced por dominio/clave.
scorecard = study.artifacts.get("scorecard", "scorecard")             # tabla del scorecard
metrics = study.artifacts.get("performance", "discriminant_metrics")  # AUC/KS/Gini por partición
print(metrics)
```
<!-- quickstart:end -->

El dataset del preset (`consumo_comportamiento`) es una cartera de consumo sintética de 6.000 filas,
cohortada por trimestre para partición Dev/Held-out/OOT — determinista, sin datos reales.

!!! warning "Chequea el estado antes de usar resultados"
    `nikodym.run` es *fail-loud pero no explosivo*: ante un fallo devuelve el `Study` **parcial** con
    `study.run_context.status == "failed"`. El consumidor por código **debe** verificar
    `study.run_context.status` antes de leer artefactos.

    Cuando falla, el diagnóstico está en `study.run_context.error` y no hay que configurar nada para
    verlo:

    ```python
    if study.run_context.status == "failed":
        error = study.run_context.error
        print(error.step)     # el paso del pipeline que falló, p. ej. "data"
        print(error.message)  # el mensaje del motor, con la columna o el parámetro concreto
    ```

## El mismo pipeline, sin escribir código

Todo lo anterior se puede hacer desde una **interfaz gráfica local**, que se instala y se levanta en
dos comandos:

```bash
pip install 'nikodym[ui]'
nikodym-ui
```

`nikodym-ui` sirve la interfaz en `http://127.0.0.1:8000` y abre el navegador. Lo primero que
pregunta es **a qué viniste**: eliges un trabajo del catálogo —o directamente uno de los ejemplos
ya configurados— y la interfaz te muestra sólo las secciones que ese trabajo usa. A partir de ahí
el recorrido son cinco pasos: datos → configuración (opcional) → ejecutar → resultados → informe.
Si prefieres armarlo tú, el catálogo ofrece esa salida y te deja en el formulario completo,
sección por sección.

Los trabajos del catálogo, en el orden en que aparecen:

<!-- catalogo-trabajos:start -->
| Trabajo | Qué corre |
|---|---|
| **Scorecard de comportamiento (PD)** | El pipeline F1 completo: análisis exploratorio, binning, selección, modelo, scorecard, calibración, desempeño, estabilidad, validación formal e informe. |
| **PD lifetime (curvas de supervivencia)** | Curvas de supervivencia sobre datos censurados y su estructura temporal de PD. |
| **Provisiones IFRS 9 / ECL** | Pérdida esperada de tres etapas: PD lifetime, LGD, EAD, staging por SICR y descuento a la tasa efectiva. |
| **Provisión interna / LGD** | Provisión por el método interno sobre grupos homogéneos, a partir de la PD calibrada que traes como tabla. |
| **PD + LGD en una corrida** | El scorecard completo —análisis exploratorio y validación formal incluidos— y la provisión interna en una sola corrida y un solo informe. |
| **Validar un modelo existente** | Tu scorecard y tu PD, medidos y documentados: discriminación, calibración y estabilidad, sin volver a modelar. |
| **Severidad modelada o calculada** | La LGD modelada con las variables de tu archivo, o calculada descontando lo que ya recuperaste. |
| **Stress testing** | Escenarios adversos y shocks macro sobre la cartera. Hoy sólo por código: el motor corre desde Python y todavía no tiene pantalla. |
<!-- catalogo-trabajos:end -->

Los dos trabajos del scorecard abren con la sección **Análisis exploratorio**, que describe la
cartera antes de modelarla —la tasa de incumplimiento en el tiempo, un perfil por variable y las
marcas de calidad del archivo— y la pinta primero en Resultados; viene encendida con sus valores de
fábrica y, si tu archivo no trae fecha, agrupa la tasa por la cohorte con la que particionas. Qué
muestra y qué hace el motor con la señal temporal está en
[Análisis exploratorio](guias/analisis-exploratorio.md).

Incluyen además la sección **Validación formal**, que documenta el modelo con pruebas de
discriminación, calibración y estabilidad y publica su estado técnico en Resultados y en el informe;
qué prueba cada familia y qué hace un validador con el resultado está en
[Validación formal](guias/validacion-formal.md).

Todos comparten la sección **Gobernanza**, que llega apagada: encenderla pide el propósito del
modelo y hace que Resultados muestre la ficha del modelo. Cómo se enciende y qué muestra está en
[Gobernanza y ficha del modelo](guias/gobernanza.md).

!!! note "`[ui]` trae lo que el formulario puede ejecutar"
    No es sólo el servidor: compone `scoring`, `survival`, `excel`, `docx` y `report`, así que los
    tres presets de fábrica —F1 scorecard, F4 IFRS 9 y F5 provisión interna sobre cartera
    genérica— corren hasta el informe con esa única instalación. Son unos
    700 MB en disco. Un extra llamado `ui` que instalara la interfaz pero no el motor que ésta
    dispara prometería algo que no cumple. Quedan fuera el **PDF** (`nikodym[pdf]`), por la licencia
    de WeasyPrint, y el backend de lectura **`polars`** (`nikodym[polars]`), que sólo acelera la
    carga sin cambiar el resultado; si lo eliges sin instalarlo, la corrida te da el comando exacto.

### Opciones del comando

| Opción | Qué hace |
|---|---|
| `--port PORT` | Puerto local (1024–65535). Por defecto `8000`. |
| `--workdir DIR` | Dónde se guardan corridas y datasets. Por defecto `.nikodym_ui` en el directorio actual. |
| `--no-open` | No abrir el navegador automáticamente. |
| `--casos-de-referencia` | Ofrecer también los casos de referencia atados a una jurisdicción. Por defecto el catálogo no los ofrece; ver [Aterrizar una norma local](norma-local.md). |

!!! note "Sólo escucha en loopback, y no es configurable"
    El bind es siempre `127.0.0.1`: **no existe `--host`**. La interfaz no es alcanzable desde la
    red y tus datos no salen de tu máquina. Cada lanzamiento genera además un token propio que no se
    escribe en el log ni en la URL, y las operaciones de escritura exigen origen local.

### Es la misma corrida, no una versión reducida

La interfaz **edita el mismo `NikodymConfig`** que usarías por código, y el motor es el mismo:

- Lo que armas en el formulario se exporta a YAML y se ejecuta con `nikodym.run`, produciendo el
  mismo `config_hash`.
- Un YAML existente se puede cargar en el formulario y seguir editándolo ahí.

Antes de ejecutar, la interfaz compara la configuración con las columnas de tu archivo y lista
**todos** los desajustes de una vez, cada uno con un enlace al campo que hay que corregir. Informa,
no bloquea: puedes ejecutar igual y dejar que la corrida sea la autoridad.

## Siguientes pasos

- **[Tutorial](tutorial.md)** — el mismo pipeline paso a paso: qué produce cada etapa (binning →
  selección → modelo → scorecard → calibración → desempeño/estabilidad) y cómo leer los artefactos.
- **[Conceptos](concepts.md)** — el modelo mental (`config` declarativo, `run` → `Study`,
  reproducibilidad y gobernanza).
- **[Referencia de la API](api.md)** — detalle de `run`, `Study` y `NikodymConfig`.
- **[Proponer un caso](https://www.nikodym.cl/?ref=docs-getting-started#contact)** — Nexo Labs, la
  consultora que construye el motor. Si el problema no es correr el pipeline sino defender el
  modelo ante Validación, ahí se evalúa.
