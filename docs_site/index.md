# Nikodym RiskLib

Librería Python **open-source (Apache-2.0)** de riesgo de crédito **integral**:
scoring/scorecards, ML, provisiones **CMF (Chile)** e **IFRS 9/ECL**, forward-looking y
stress testing. Paquete: `nikodym`.

!!! note "Estado: 1.1.0 — release estable"
    Disponible en PyPI: `pip install nikodym`. El pipeline de scorecard (F1) es **API estable
    (SemVer 1.x)**; las superficies que aún crecen (modelado ML, provisiones, forward-looking,
    resultados/métricas/orquestación) siguen experimentales, fuera de la garantía SemVer 1.x.

## Principios

- **Reproducibilidad total**: `(datos + config + semilla) → resultado idéntico`. Cada corrida
  emite un *lineage bundle* (git SHA + hash de datos + config + semilla + `uv.lock`).
- **Gobernanza por construcción** (SR 11-7): *model card* y *audit-trail* automáticos.
- **Config declarativo** (Pydantic v2): *el config ES el experimento*.
- **Núcleo liviano**: `import nikodym` no arrastra el stack ML; los backends pesados van tras
  *extras* opcionales con import perezoso.
- **CMF ≠ IFRS 9**: dos motores separados; la provisión es el **máximo** (piso prudencial).

## Instalación

```bash
pip install nikodym                 # núcleo base (config, Study, lineage)
pip install 'nikodym[scoring]'      # MVP scorecard (optbinning + statsmodels + sklearn>=1.6)
pip install 'nikodym[all]'          # todo lo redistribuible (sin copyleft)
```

## Quickstart

El experimento es un `NikodymConfig` declarativo; `nikodym.run(config)` lo ejecuta de extremo a
extremo (binning → selección → modelo → scorecard → calibración → desempeño → estabilidad) y
devuelve un [`Study`](api.md#study) reproducible. El siguiente ejemplo usa el **preset estándar F1**
sobre un dataset sintético de consumo, así corre sin que rellenes ningún campo:

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
scorecard = study.artifacts.get("scorecard", "scorecard")        # tabla del scorecard
metrics = study.artifacts.get("performance", "discriminant_metrics")  # AUC/KS/Gini por partición
print(metrics)
```

`nikodym.run` es *fail-loud pero no explosivo*: ante un fallo devuelve el `Study` **parcial** con
`study.run_context.status == "failed"` (el error vive en el audit-trail y el lineage, no se
silencia). Por eso el consumidor por código **debe** chequear `study.run_context.status` antes de
usar los resultados.

Con un config propio se sustituye el preset: se define el `NikodymConfig` (esquema de datos,
binning, modelo, scorecard, calibración) y se apunta `data.load.source` al dataset real. Ver
[Conceptos](concepts.md) para el modelo mental y [Referencia de la API](api.md) para el detalle de
`run`, `Study` y `NikodymConfig`.

## Licencia

[Apache-2.0](https://github.com/nexolabs-gh/nikodym/blob/main/LICENSE). Sin dependencias copyleft
(GPL/LGPL/AGPL) en el wheel.
