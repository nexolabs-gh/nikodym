# Nikodym RiskLib

[![PyPI](https://img.shields.io/pypi/v/nikodym.svg)](https://pypi.org/project/nikodym/)
[![Python](https://img.shields.io/pypi/pyversions/nikodym.svg)](https://pypi.org/project/nikodym/)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](https://github.com/nexolabs-gh/nikodym/blob/main/LICENSE)
[![CI](https://github.com/nexolabs-gh/nikodym/actions/workflows/ci.yml/badge.svg)](https://github.com/nexolabs-gh/nikodym/actions/workflows/ci.yml)

Librería Python **open-source (Apache-2.0)** de riesgo de crédito **integral**:
scoring/scorecards, backends ML, provisiones **CMF (Chile)** e **IFRS 9/ECL**, forward-looking
y stress testing. Todo en un motor **reproducible por construcción** y con gobernanza
(model card + audit-trail) automática. Paquete: `nikodym`.

> **Estado: 1.x (estable).** El pipeline de validación de scorecard (F1) es **API estable
> (SemVer 1.x)**: no rompe hasta un 2.0. Las superficies que aún crecen —modelado ML, provisiones
> CMF/IFRS 9, forward-looking, y los contratos transversales de resultados/métricas/orquestación—
> siguen marcadas como **experimentales** (fuera de la garantía SemVer 1.x).

## Qué hace

Los seis dominios **calculan** hoy: son motores deterministas, sin *stubs*, con más de 600 tests
sobre los cuatro que no tienen interfaz (más de 3.700 en la suite completa). Lo que los separa no es
"hecho / no hecho", sino **superficie** (¿tiene UI, preset y capítulo en el informe, o hay que
escribir el config en Python?) y **garantía de API** (¿congelada bajo SemVer 1.x, o experimental?).
No existe CLI.

| Dominio | Superficie | Garantía |
|---|---|---|
| **Scorecard (F1)** — binning/WoE monotónico (optbinning), selección (IV/VIF), regresión logística, scorecard escalado (PDO/offset), calibración, desempeño (AUC/KS/Gini) y estabilidad (PSI/CSI) | UI, preset e informe | **estable** (SemVer 1.x) |
| **Provisiones** — motores **CMF (Chile)** e **IFRS 9/ECL** separados; la orquestación B-1 compara método estándar CMF e interno y aplica la regla declarada | UI, preset e informe | experimental |
| **Stress testing** — escenarios adversos, shocks macro en escala logit, sensibilidad y *reverse stress* por bisección | Python | experimental |
| **Markov** — matrices de transición (cohorte/duración), Chapman-Kolmogorov, Aalen-Johansen, *term-structure* de PD | Python | experimental |
| **Forward-looking** — ARIMA/auto-ARIMA, VAR/VECM, Ljung-Box y modelos satélite macro → PD/LGD | Python | experimental |
| **Survival** — Kaplan-Meier, Cox/AFT y *hazard* discreto sobre datos censurados | Python | experimental |

- **Backends ML (F2)**: XGBoost, LightGBM, CatBoost y tuning (Optuna) como *extras* selectivos,
  con explicabilidad (SHAP) opcional.
- **No hace** (por si lo estás buscando): *roll rates*, curvas de cosecha/*vintage*, ni CLI.
- **Informe de validación, no un log**: cada corrida produce un documento con portada, resumen
  ejecutivo, metodología (redactada con los parámetros que realmente se usaron), resultados,
  conclusiones y anexos técnicos. Sale en HTML y PDF, y también como **base editable** (`.qmd` de
  Quarto o `.docx` de Word) para que escribas tu documentación encima: los capítulos que solo puede
  escribir un humano (contexto de la cartera, conclusión que se firma) vienen como *placeholders*
  con guía, nunca inventados.
- **Reproducibilidad total**: `(datos + config + semilla) → resultado idéntico`, con *lineage
  bundle* (git SHA, estado del working tree, hash del contenido de los datos, `config_hash`, semilla
  raíz y versiones de las librerías) en cada corrida. El hash del `uv.lock` está **pendiente**: el
  campo existe y hoy viaja vacío, y el propio *model card* declara la limitación en vez de callarla.

## Tus datos no salen de tu infraestructura

Nikodym es una librería, no un servicio: se instala con `pip` y corre donde tú la ejecutes —tu
notebook, tu servidor, tu clúster, dentro de tu red—. Para una institución financiera esto suele
importar más que cualquier métrica:

- **Sin telemetría.** El paquete no reporta uso, ni versiones, ni nada. No hay código de analítica.
- **Sin llamadas de red en el cálculo.** El pipeline no abre conexiones por sí solo: las cifras se
  computan en tu proceso, con tus datos, y los artefactos se escriben en el `workdir` que declaras.
- **Sin dependencias de un servicio nuestro.** No hay una API que tenga que estar arriba para que
  el motor funcione, ni licencia que validar contra un servidor. Si Nexo Labs desaparece mañana, tu
  corrida de pasado mañana sigue dando el mismo resultado.
- **Las dos salidas posibles son tuyas y opcionales**: la narración por IA (apagada por defecto, con
  tu clave y tu proveedor; la prosa del informe es determinista y no la escribe la IA) y el registro
  de experimentos MLflow, que por defecto escribe en un directorio local. Detalle en
  [SECURITY.md](SECURITY.md).

Y como es Apache-2.0, puedes auditar el código, forkearlo y adaptarlo sin pedirnos permiso.

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

## Limitaciones que debes conocer antes de usarlo en serio

El motor las publica de sí mismo —cada fila afectada emite su código `FALTA-DATO`—, así que aquí se
dicen igual de claro:

- **Los parámetros normativos CMF no son oficiales.** Se transcribieron del compendio y **no
  provienen de la CMF ni están validados por ella** —la Comisión no certifica implementaciones de
  terceros—, así que **requieren validación humana contra la norma vigente antes de cualquier uso
  productivo**. Lo que sí está hecho: la **matriz de consumo** (numeral B-1 3.1.3, Circular
  2.346/2024) se **cotejó celda por celda contra el texto del compendio** —sus 16 valores de PI,
  sus 6 de PDI y el PI de incumplimiento coinciden exactamente— y el cotejo queda registrado en
  [`docs/normativa_cmf_parametros.md`](docs/normativa_cmf_parametros.md) §3. Quedan dos brechas
  abiertas y declaradas (`FALTA-DATO`): aforos y *haircuts* de garantías financieras, y las tablas
  del RAN 21-10.
- **Las causales de incumplimiento que el motor no puede inferir, las declara el banco.** De las
  tres del numeral B-1 3.2, solo la mora ≥ 90 días sale de los datos; el refinanciamiento para
  dejar vigente una operación morosa y la reestructuración forzosa hay que **entregarlas en la
  columna `is_default`**. Sin ella, un deudor reestructurado y al día se provisiona al 6,6 % en vez
  del 100 % que exige la norma.
- **La EAD de IFRS 9 se despliega constante en el tiempo.** El panel longitudinal está diferido; el
  motor no lo aplana en silencio: cada fila lo declara con el código `FALTA-DATO-IFRS-4`, y el
  config **rechaza** `exposure_profile_col` en vez de fingir que lo usa.
- **Experimental no es "beta marketinera"**: todo lo que no sea el pipeline de scorecard puede
  cambiar de firma dentro de la 1.x, y no está *battle-tested* en producción.

## Principios de diseño

- **Reproducibilidad total**: misma entrada → resultado byte-idéntico, con lineage completo.
- **Gobernanza por construcción** (SR 11-7): *model card* y *audit-trail* automáticos.
- **Config declarativo** (Pydantic v2): *el config ES el experimento*.
- **Núcleo liviano**: los backends pesados van tras *extras* con import perezoso.
- **CMF ≠ IFRS 9**: dos motores separados, nunca uno solo. La **regla del máximo** del Capítulo B-1
  (Circular N° 2.346) es entre el **método estándar y el método interno** del banco — *no* entre CMF
  e IFRS 9: el Compendio (Cap. A-2, num. 5) **excluye** el deterioro de NIIF 9 sobre colocaciones.
- **Lo que falta se declara, no se disimula**: un dato ausente sale como `FALTA-DATO` en el
  resultado; una opción sin motor detrás se rechaza al validar el config, no al final de la corrida.

## Documentación

Guía completa (conceptos, referencia de `run`/`Study`/`NikodymConfig`) en
[docs.nikodym.cl](https://docs.nikodym.cl). La demo del scorecard —una corrida real, paso a paso—
en [demo.nikodym.cl](https://demo.nikodym.cl). El `CHANGELOG.md` registra los cambios por versión.

## Desarrollo

El proyecto usa [uv](https://docs.astral.sh/uv/) + hatchling, con layout `src/`.

```bash
uv sync                              # entorno completo (grupo dev: test/lint/docs)
uv run ruff check . && uv run ruff format --check .
uv run mypy                          # type-check estricto de todo el paquete
uv run pytest                        # suite de tests
```

## Quién lo construye

Nikodym RiskLib lo construye **Nexo Labs**, una consultora chilena de riesgo y analítica de datos.
El motor es Apache-2.0 y no tiene edición comercial, *tier* de pago ni funciones reservadas: lo que
hay en `src/` es todo lo que hay. Está publicado para que puedas leer el código antes de hablar con
nosotros.

Una librería calcula; no decide. El binning, la calibración y las métricas los corre el motor —pero
a qué tasa central anclas (TTC o PIT), dónde pones el corte y qué supuestos sostienes ante
Validación o ante la CMF sigue siendo juicio de modelo, y eso no lo entrega ningún paquete de pip.
Si ese es el problema, puedes [proponer un caso](https://www.nikodym.cl/?ref=readme#contact). Cada
caso se evalúa antes de aceptarse; si no hay caso, también te lo decimos, en menos de 48 horas
hábiles.

## Licencia

[Apache-2.0](https://github.com/nexolabs-gh/nikodym/blob/main/LICENSE). Sin dependencias copyleft
(GPL/LGPL/AGPL) en el wheel.
