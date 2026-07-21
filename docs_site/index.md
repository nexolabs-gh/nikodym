# Nikodym RiskLib

Librería Python **open-source (Apache-2.0)** de riesgo de crédito **integral**:
scoring/scorecards, ML, provisiones **CMF (Chile)** e **IFRS 9/ECL**, forward-looking y
stress testing. Paquete: `nikodym`.

!!! note "Estado: 1.4.0 — release estable"
    Disponible en PyPI: `pip install nikodym`. El pipeline de scorecard (F1) es **API estable
    (SemVer 1.x)**; las superficies que aún crecen (modelado ML, provisiones, forward-looking,
    resultados/métricas/orquestación) siguen experimentales, fuera de la garantía SemVer 1.x.

    **Los seis dominios calculan hoy** —son motores deterministas, con más de 600 tests sobre los
    cuatro que no tienen interfaz—, pero **solo el scorecard y las provisiones tienen UI, preset y
    capítulo en el informe** (el scorecard bajo garantía SemVer 1.x; las provisiones, la más nueva,
    aún experimentales). Stress, Markov, forward-looking y survival se usan escribiendo el config
    en Python: no hay CLI. Lo que les falta es superficie, no aritmética.

!!! warning "Antes de usarlo en producción"
    **Los parámetros normativos CMF no son oficiales**: se transcribieron del compendio con
    asistencia de IA y verificación visual, no provienen de la CMF ni están validados por ella, y
    **requieren validación humana contra la norma vigente antes de cualquier uso productivo** (quedan
    dos brechas `FALTA-DATO` declaradas: aforos/*haircuts* de garantías financieras y las tablas del
    RAN 21-10). Además, **la EAD de IFRS 9 se despliega constante en el tiempo** —el panel
    longitudinal está diferido— y el motor lo publica en cada fila con el código `FALTA-DATO-IFRS-4`.

## Principios

- **Reproducibilidad total**: `(datos + config + semilla) → resultado idéntico`. Cada corrida
  emite un *lineage bundle* (git SHA, estado del working tree, hash del contenido de los datos,
  `config_hash`, semilla raíz y versiones de las librerías). El hash del `uv.lock` está pendiente:
  el campo viaja vacío y el *model card* lo declara como limitación.
- **Gobernanza por construcción** (SR 11-7): *model card* y *audit-trail* automáticos.
- **Config declarativo** (Pydantic v2): *el config ES el experimento*.
- **Núcleo liviano**: `import nikodym` no arrastra el stack ML; los backends pesados van tras
  *extras* opcionales con import perezoso.
- **CMF ≠ IFRS 9**: dos motores separados, nunca uno solo. La **regla del máximo** del Capítulo B-1
  (Circular N° 2.346) se aplica entre el **método estándar y el método interno** del banco — *no*
  entre CMF e IFRS 9: el Compendio (Cap. A-2, num. 5) **excluye** el modelo de deterioro de NIIF 9
  sobre las colocaciones y los créditos contingentes.

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

## Quién lo construye

Nikodym RiskLib lo construye **Nexo Labs**, una consultora chilena de riesgo y analítica de datos.
El motor es Apache-2.0 y no tiene edición comercial ni funciones reservadas: está publicado para
que puedas leer el código antes de hablar con nosotros.

Una librería calcula; no decide. El binning, la calibración y las métricas los corre el motor —pero
a qué tasa central anclas (TTC o PIT), dónde pones el corte y qué supuestos sostienes ante
Validación o ante la CMF sigue siendo juicio de modelo. Si ese es el problema, puedes
[proponer un caso](https://www.nikodym.cl/?ref=docs-home#contact). Cada caso se evalúa antes de
aceptarse; si no hay caso, también te lo decimos, en menos de 48 horas hábiles.

## Licencia

[Apache-2.0](https://github.com/nexolabs-gh/nikodym/blob/main/LICENSE). Sin dependencias copyleft
(GPL/LGPL/AGPL) en el wheel.
