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
| `tracking` | `nikodym[tracking]` | Registro de corridas / *registry*. | `mlflow` |
| `ui` | `nikodym[ui]` | Backend REST de la UI (incluye el extra `excel`). | `fastapi`, `uvicorn`, `python-multipart` |
| `sweep` | `nikodym[sweep]` | Barridos de configuración por CLI. | `hydra-core`, `omegaconf` |
| `polars` | `nikodym[polars]` | Backend de carga de datos con Polars. | `polars` |
| `excel` | `nikodym[excel]` | Lectura de `.xlsx` en el `DataLoader`. | `openpyxl` |
| `report` | `nikodym[report]` | Figuras opcionales del reporte. | `matplotlib`, `plotly` |
| `ai` | `nikodym[ai]` | Narrativa asistida por IA (opcional). | `anthropic` |
| `all` | `nikodym[all]` | **Meta-extra**: todo lo redistribuible de la tabla anterior. | (agrega todos los de arriba) |

Puedes combinar extras en una sola instalación:

```bash
pip install 'nikodym[scoring,xgboost,explain]'
```

!!! note "Comillas obligatorias en zsh"
    En zsh (el shell por defecto de macOS) los corchetes son *globbing*: escribe siempre el nombre
    entre comillas — `pip install 'nikodym[scoring]'` — o el shell fallará antes de llegar a pip.

!!! warning "`all` excluye copyleft a propósito"
    `nikodym[all]` reúne todo lo **redistribuible**, no literalmente todo. Deja fuera dependencias
    copyleft (p. ej. `scikit-survival`, GPL-3.0); por eso el motor de supervivencia usa `lifelines`
    (MIT). El *wheel* de Nikodym no arrastra GPL/LGPL/AGPL.

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

Debe imprimir la versión instalada (esta documentación corresponde a la serie **0.9.x**). Que este
comando funcione confirma que el **núcleo base** está sano; no dice nada sobre los extras, porque
sus imports son perezosos. Para verificar que el extra `scoring` quedó disponible, la prueba real es
correr una corrida F1 (siguiente sección): si falta el extra, el motor fallará al importar
`optbinning` de forma explícita, no en silencio.

## Primer contacto: correr el preset F1

El experimento en Nikodym *es* un `NikodymConfig` declarativo; `nikodym.run(config)` lo ejecuta de
extremo a extremo y devuelve un `Study` reproducible. El camino más corto para ver el motor
funcionando es el **preset estándar F1**, que trae un config curado y un dataset sintético de
consumo, así corre sin que rellenes ningún campo.

!!! note "Requiere el extra `scoring`"
    El preset F1 ejerce el pipeline de scorecard completo. Instala `pip install 'nikodym[scoring]'`
    antes de ejecutar el ejemplo.

```python
from pathlib import Path
from tempfile import mkdtemp

import nikodym
from nikodym.core.config import NikodymConfig
from nikodym.ui.datasets import materialize
from nikodym.ui.presets import standard_preset

# 1. Materializa el dataset sintético de consumo (determinista) en un workdir temporal.
workdir = Path(mkdtemp(prefix="nikodym-primer-contacto-"))
preset = standard_preset()
data_path = materialize(preset["dataset_id"], workdir=workdir)

# 2. Toma el config F1 curado y apúntalo al archivo de datos recién materializado.
cfg_dict = preset["config"]
cfg_dict["data"]["load"]["source"] = str(data_path)
config = NikodymConfig.model_validate(cfg_dict)

# 3. Ejecuta la corrida completa y verifica el estado ANTES de leer resultados.
study = nikodym.run(config)
assert study.run_context.status == "done"

# 4. Accede a los resultados namespaced por dominio/clave.
metrics = study.artifacts.get("performance", "discriminant_metrics")  # AUC/KS/Gini por partición
print(metrics)
```

El dataset del preset (`consumo_comportamiento`) es una cartera de consumo sintética de 6.000 filas,
cohortada por trimestre para partición Dev/Held-out/OOT — determinista, sin datos reales.

!!! warning "Chequea el estado antes de usar resultados"
    `nikodym.run` es *fail-loud pero no explosivo*: ante un fallo devuelve el `Study` **parcial** con
    `study.run_context.status == "failed"` (el error queda en el audit-trail y el lineage, no se
    silencia). El consumidor por código **debe** verificar `study.run_context.status` antes de leer
    artefactos.

## Siguientes pasos

- **[Tutorial](tutorial.md)** — el mismo pipeline paso a paso: qué produce cada etapa (binning →
  selección → modelo → scorecard → calibración → desempeño/estabilidad) y cómo leer los artefactos.
- **[Conceptos](concepts.md)** — el modelo mental (`config` declarativo, `run` → `Study`,
  reproducibilidad y gobernanza).
- **[Referencia de la API](api.md)** — detalle de `run`, `Study` y `NikodymConfig`.
