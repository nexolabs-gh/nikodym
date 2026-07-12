# Nikodym RiskLib

[![PyPI](https://img.shields.io/pypi/v/nikodym.svg)](https://pypi.org/project/nikodym/)
[![Python](https://img.shields.io/pypi/pyversions/nikodym.svg)](https://pypi.org/project/nikodym/)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
[![CI](https://github.com/nexolabs-gh/nikodym/actions/workflows/ci.yml/badge.svg)](https://github.com/nexolabs-gh/nikodym/actions/workflows/ci.yml)

Librería Python **open-source (Apache-2.0)** de riesgo de crédito **integral**:
scoring/scorecards, backends ML, provisiones **CMF (Chile)** e **IFRS 9/ECL**, forward-looking
y stress testing. Todo en un motor **reproducible por construcción** y con gobernanza
(model card + audit-trail) automática. Paquete: `nikodym`.

> **Estado: 1.0 (estable).** El pipeline de validación de scorecard (F1) es **API estable
> (SemVer 1.x)**: no rompe hasta un 2.0. Las superficies que aún crecen —modelado ML, provisiones
> CMF/IFRS 9, forward-looking, y los contratos transversales de resultados/métricas/orquestación—
> siguen marcadas como **experimentales** (fuera de la garantía SemVer 1.x).

## Qué hace

- **Scorecard (F1)**: binning/WoE con monotonía (optbinning), selección, regresión logística,
  scorecard escalado, calibración y métricas de desempeño (AUC/KS/Gini) y estabilidad (PSI/CSI).
- **Backends ML (F2)**: XGBoost, LightGBM, CatBoost y tuning (Optuna) como *extras* selectivos,
  con explicabilidad (SHAP) opcional.
- **Provisiones**: motores **CMF (Chile)** e **IFRS 9/ECL** separados; la provisión es el
  **máximo** de ambos (piso prudencial).
- **Forward-looking & stress testing**: proyección macroeconómica y escenarios.
- **Reproducibilidad total**: `(datos + config + semilla) → resultado idéntico`, con *lineage
  bundle* (git SHA + hash de datos + config + semilla + `uv.lock`) en cada corrida.

## Instalación

```bash
pip install nikodym                 # núcleo base (config, Study, lineage)
pip install 'nikodym[scoring]'      # MVP scorecard (optbinning + statsmodels + sklearn>=1.6)
pip install 'nikodym[all]'          # todo lo redistribuible (sin copyleft)
```

Requiere Python ≥ 3.11. El núcleo base es liviano: `import nikodym` **no** arrastra el stack ML;
los backends pesados viven tras *extras* opcionales con import perezoso.

## Quickstart

El experimento es un `NikodymConfig` declarativo; `nikodym.run(config)` lo ejecuta de extremo a
extremo (binning → selección → modelo → scorecard → calibración → desempeño → estabilidad) y
devuelve un `Study` reproducible. Este ejemplo usa el **preset estándar F1** sobre un dataset
sintético de consumo, así corre sin rellenar ningún campo:

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

# 3. Ejecuta la corrida completa y verifica el estado.
study = nikodym.run(config)
assert study.run_context.status == "done"

# 4. Accede a los resultados namespaced por dominio/clave.
scorecard = study.artifacts.get("scorecard", "scorecard")             # tabla del scorecard
metrics = study.artifacts.get("performance", "discriminant_metrics")  # AUC/KS/Gini por partición
print(metrics)
```

`nikodym.run` es *fail-loud pero no explosivo*: ante un fallo devuelve el `Study` **parcial** con
`study.run_context.status == "failed"` (el error vive en el audit-trail y el lineage, no se
silencia). El consumidor por código **debe** chequear `study.run_context.status` antes de usar los
resultados.

## Principios de diseño

- **Reproducibilidad total**: misma entrada → resultado byte-idéntico, con lineage completo.
- **Gobernanza por construcción** (SR 11-7): *model card* y *audit-trail* automáticos.
- **Config declarativo** (Pydantic v2): *el config ES el experimento*.
- **Núcleo liviano**: los backends pesados van tras *extras* con import perezoso.
- **CMF ≠ IFRS 9**: dos motores separados; la provisión es el máximo (piso prudencial).

## Documentación

Guía completa (conceptos, referencia de `run`/`Study`/`NikodymConfig`) en el
[sitio de documentación](https://github.com/nexolabs-gh/nikodym#readme). El `CHANGELOG.md`
registra los cambios por versión.

## Desarrollo

El proyecto usa [uv](https://docs.astral.sh/uv/) + hatchling, con layout `src/`.

```bash
uv sync                              # entorno completo (grupo dev: test/lint/docs)
uv run ruff check . && uv run ruff format --check .
uv run mypy                          # type-check estricto de todo el paquete
uv run pytest                        # suite de tests
```

## Licencia

[Apache-2.0](LICENSE). Sin dependencias copyleft (GPL/LGPL/AGPL) en el wheel.
