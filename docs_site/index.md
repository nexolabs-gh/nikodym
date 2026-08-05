# Nikodym RiskLib

Librería Python **open-source (Apache-2.0)** de riesgo de crédito **integral**: **PD** (scorecards,
ML, survival), **LGD y EAD**, **validación de modelos**, provisiones **IFRS 9/ECL**, forward-looking
y stress testing, con **informe reproducible** y su lineage. Paquete: `nikodym`.

Los estándares comunes —Basilea, IFRS 9— van en el motor. La **normativa local de cada
jurisdicción se aterriza encima**, y hay un caso de referencia implementado que muestra cómo:
[Aterrizar una norma local](norma-local.md).

!!! note "Estado: 1.11.0 — release estable"
    Disponible en PyPI: `pip install nikodym`. El pipeline de scorecard (F1) es **API estable
    (SemVer 1.x)**; las superficies que aún crecen (modelado ML, provisiones, forward-looking,
    resultados/métricas/orquestación) siguen experimentales, fuera de la garantía SemVer 1.x.

    **Los seis dominios calculan hoy** —son motores deterministas, con más de 500 tests sobre los
    tres que no tienen interfaz—, pero **solo el scorecard, las provisiones y survival tienen UI,
    preset y capítulo en el informe** (el scorecard bajo garantía SemVer 1.x; los otros dos, más
    nuevos, aún experimentales). Stress, Markov y forward-looking se usan escribiendo el config
    en Python: el comando `nikodym-ui` levanta la interfaz y no los corre. Lo que les falta es
    superficie, no aritmética.

!!! warning "Antes de usarlo en producción"
    **Los parámetros del caso de referencia no son oficiales, y el caso está congelado**: el motor
    que aterriza la norma chilena (CMF, Cap. B-1) existe como ejemplo de método, no como compromiso
    de mantenimiento. Sus tablas se extrajeron del compendio con asistencia de IA y verificación
    visual el **2026-06-23** —la de consumo, cotejada celda por celda el **2026-07-14**—, no
    provienen de la CMF ni están validadas por ella, y
    **requieren validación humana contra la norma vigente antes de cualquier uso productivo**.
    Faltan además dos tablas: los aforos y *haircuts* de garantías financieras, y las del RAN 21-10
    — el manifiesto de parámetros las declara faltantes en vez de rellenarlas con un valor
    inventado. El alcance completo está en [Aterrizar una norma local](norma-local.md).
    Y **la curva lifetime de IFRS 9 asume exposición constante por período**: no modela
    la amortización del crédito en el tiempo. El resultado lo deja anotado en cada fila, para que
    nadie lo descubra tarde.

## Principios

- **Reproducibilidad total**: `(datos + config + semilla) → resultado idéntico`. Cada corrida
  emite un *lineage bundle* (git SHA, estado del working tree, hash del contenido de los datos,
  `config_hash`, semilla raíz y versiones de las librerías). El hash del `uv.lock` está pendiente:
  el campo viaja vacío y el *model card* lo declara como limitación.
- **Gobernanza por construcción** (SR 11-7): *model card* y *audit-trail* automáticos.
- **Config declarativo** (Pydantic v2): *el config ES el experimento*.
- **Núcleo liviano**: `import nikodym` no arrastra el stack ML; los backends pesados van tras
  *extras* opcionales con import perezoso.
- **Una norma local nunca se funde con un estándar contable**: son motores separados, nunca uno
  solo, y la regla que los compara la declara quien la usa. El caso de referencia lo ilustra: la
  **regla del máximo** del Capítulo B-1 (Circular N° 2.346) se aplica entre el **método estándar y
  el método interno** del banco — *no* entre ese estándar e IFRS 9, porque el Compendio (Cap. A-2,
  num. 5) **excluye** el modelo de deterioro de NIIF 9 sobre las colocaciones y los créditos
  contingentes.

## Instalación

```bash
pip install nikodym                 # núcleo base (config, Study, lineage)
pip install 'nikodym[scoring]'      # MVP scorecard (optbinning + statsmodels + sklearn>=1.6)
pip install 'nikodym[ui]'           # interfaz gráfica local, lista para correr (`nikodym-ui`)
pip install 'nikodym[all]'          # todo lo redistribuible (sin copyleft)
```

## Dos caminos: código o interfaz

El mismo motor y el mismo config, por donde prefieras trabajar. Por código, el quickstart de abajo.
Por interfaz, dos comandos:

```bash
pip install 'nikodym[ui]'
nikodym-ui
```

Levanta la interfaz en `http://127.0.0.1:8000` —sólo loopback, tus datos no salen de tu máquina— y
abre el navegador. Detalle y opciones en
[Instalación y primeros pasos](getting-started.md#el-mismo-pipeline-sin-escribir-codigo).

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
`study.run_context.status == "failed"`, y el diagnóstico —tipo del error, mensaje del motor y paso
que falló— queda en `study.run_context.error`, sin configurar nada. Por eso el consumidor por código
**debe** chequear `study.run_context.status` antes de usar los resultados.

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
Validación o ante tu regulador sigue siendo juicio de modelo. Si ese es el problema, puedes
[proponer un caso](https://www.nikodym.cl/?ref=docs-home#contact). Cada caso se evalúa antes de
aceptarse; si no hay caso, también te lo decimos, en menos de 48 horas hábiles.

## Licencia

[Apache-2.0](https://github.com/nexolabs-gh/nikodym/blob/main/LICENSE). Sin dependencias copyleft
(GPL/LGPL/AGPL) en el wheel.
