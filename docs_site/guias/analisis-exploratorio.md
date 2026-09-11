# Análisis exploratorio

El **análisis exploratorio** describe la cartera antes de modelarla: cuánto incumplimiento hay,
cómo se mueve en el tiempo, qué muestra cada variable frente al incumplimiento y qué marcas de
calidad levanta el archivo. Corre segundo en el pipeline —justo después de preparar los datos— y
no transforma nada: describe, no decide. El binning, la selección y el modelo trabajan sobre los
datos originales, no sobre lo que esta sección calcula.

!!! note "Los números de esta guía"
    Salen de una **corrida real** del trabajo «Scorecard de comportamiento (PD)» sobre el dataset
    sintético de consumo (6.000 operaciones, partición por cohorte), con la sección en sus
    valores de fábrica. No son benchmarks: ilustran la forma y las magnitudes que produce el
    pipeline.

---

## 1. Sobre qué población se describe

La descripción se calcula sobre **una** muestra, y de fábrica es la de **desarrollo**, que es donde
se ajusta el modelo: conocer esa población antes de modelar es lo que da sentido a la sección.
Puedes pedir la de validación, la fuera de tiempo o el archivo entero. Las operaciones fuera del
modelo se cuentan, pero no entran en la tasa de incumplimiento.

## 2. La tasa de incumplimiento en el tiempo

La tasa se agrupa de dos maneras, y eliges cuál:

| Eje | Qué hace | Qué necesita |
|---|---|---|
| **Por la fecha de observación** | Agrupa por mes, trimestre o año y evalúa si la tasa se deteriora en el tiempo | Una columna de fecha en tu archivo |
| **Por cohorte o añada** | Agrupa por la cohorte de cada operación: la vista por camada | La columna de cohorte, que suele ser la misma con la que particionas |

Viene de fábrica **por la fecha de observación**, y no hace falta indicar cuál: si tu archivo trae
una sola columna de fecha, el motor la usa. Y si no trae ninguna pero particionas por cohorte, el
motor **toma esa cohorte como eje** y lo deja registrado en el trail de la corrida —no inventa un
eje: usa el que ya declaraste para particionar—. Sin fecha y sin cohorte, la corrida se detiene en
ese campo antes de calcular nada.

Es lo que ocurre en la corrida de esta guía: el archivo no tiene fecha y se particiona por la
columna `cohorte`, así que la tasa sale por cohorte, y Resultados lo dice con todas sus letras
(«Eje tomado de la partición por cohorte»).

| Cohorte | Operaciones elegibles | Incumplidas | Tasa |
|---|---:|---:|---:|
| 2023Q1 | 815 | 187 | 22,94 % |
| 2023Q2 | 822 | 181 | 22,02 % |
| 2023Q3 | 819 | 180 | 21,98 % |
| 2023Q4 | 801 | 188 | 23,47 % |
| 2024Q1 | 762 | 184 | 24,15 % |

La cohorte 2024Q2 no aparece: es la reservada como fuera de tiempo, y la descripción es sobre
desarrollo. La tasa global de esa población es **22,89 %**. Un período con menos operaciones
elegibles que el mínimo configurado —50 de fábrica— no se elimina: se marca como **poco fiable** y
se ve, marcado, en la tabla y en el gráfico.

### La señal de estabilidad temporal

Sobre un eje con orden cronológico, la sección mide cuánto se mueve la tasa de un período a otro
con uno de tres indicadores —la **variación relativa**, el **peor desvío** respecto de la media o
la **tendencia**— y lo compara con un umbral. Por encima del umbral registra un **aviso de posible
redesarrollo**. Es un umbral de exploración, no una regla: la corrida sigue igual.

Hay tres situaciones en las que la señal **no se evalúa**, y las tres se declaran con su causa en
vez de callarse o de fallar:

| Causa | Cuándo |
|---|---|
| Eje de cohorte, sin orden cronológico | La tasa se agrupó por cohorte —elegida o tomada de la partición—: las cohortes no tienen un orden que el motor pueda inferir |
| Menos de dos períodos con observaciones suficientes | Un solo período, o varios de los que menos de dos superan el mínimo |
| Sin incumplimientos en los períodos evaluables | La tasa media es cero y el indicador es relativo (variación relativa o peor desvío); con la tendencia sí se evalúa, y vale cero |

En la corrida de esta guía la causa es la primera: la tasa por cohorte se ve y se lee, pero no hay
serie temporal que evaluar.

## 3. Perfiles por variable

Cada variable se describe frente al incumplimiento: las numéricas en tramos por cuantiles —diez de
fábrica— y las categóricas por valor, con los valores raros agrupados bajo «otros». Es sólo para
describir; **no es el binning** que entra al modelo, ni el IV que decide qué variable queda.

Con «Todas las columnas» marcado se describen todas las de tu archivo **salvo** las estructurales
—el target, el estado, la partición, la fecha y la cohorte— y las que definen el incumplimiento:
describir la columna con la que se construyó el target daría una tasa de 0 % o 100 % por tramo que
no dice nada. Si eliges columnas, se describen sólo ésas; y una selección vacía no describe ninguna.

En la corrida de esta guía se describen seis variables. Dos de sus perfiles, resumidos:

| `ingreso_mensual` (tramo) | Operaciones | Tasa |
|---|---:|---:|
| hasta 286.536 | 402 | 37,56 % |
| 286.536 – 353.899 | 402 | 36,57 % |
| … | … | … |
| 814.788 – 1.017.596 | 402 | 13,18 % |
| más de 1.017.596 | 402 | 10,95 % |

| `mora_max_12m` (tramo) | Operaciones | Tasa |
|---|---:|---:|
| 0 – 3 | 619 | 19,06 % |
| 3 – 4 | 541 | 21,07 % |
| … | … | … |
| 8 – 9 | 288 | 24,65 % |
| 9 – 17 | 345 | 26,38 % |

La tasa cae con el ingreso y sube con la mora máxima: es la forma que un analista espera antes de
binificar, y verla aquí evita sorpresas después. Si activas el **poder predictivo orientativo**,
cada perfil trae además un IV descriptivo sobre estos tramos —orientativo: el que decide es el del
binning—.

## 4. Calidad de datos

Una fila por columna del archivo, con su tipo, la proporción de faltantes, cuántos valores
distintos tiene y hasta tres marcas:

| Marca | Qué significa |
|---|---|
| **casi constante** | Un solo valor concentra al menos la proporción configurada de las filas con dato (99 % de fábrica) |
| **casi única** | Tiene casi tantos valores distintos como filas: suele ser un identificador |
| **alta cardinalidad** | Una categórica con más valores distintos que el umbral (50 de fábrica) |

Sólo se reportan: ninguna marca elimina una columna ni cambia el modelo. En la corrida de esta
guía, `ingreso_mensual` sale **casi única** —4.019 valores distintos en 4.019 operaciones— y no es
un identificador sino un monto con decimales; la marca invita a mirar, no sentencia.

## 5. En Resultados y en el informe

En Resultados, el panel **Análisis exploratorio** va primero entre los analíticos: es la población
sobre la que todo lo demás se lee. Muestra la tasa global, la tasa en el tiempo —una línea si se
agrupó por fecha, barras si por cohorte, y ninguna figura cuando hay un solo período—, la señal de
estabilidad o su causa, la tabla de calidad con sus marcas y un desplegable por variable descrita.

En el informe, la subsección **Población y calidad de datos** del capítulo de contexto reproduce la
tasa por período o cohorte —graficada con el mismo criterio que la pantalla, y en su tabla— y la
calidad por columna, más una figura con la tasa por tramo de cada variable descrita (hasta doce
paneles; si hay más variables, el título dice cuántas quedaron fuera). La prosa dice el eje
efectivo, si el motor lo tomó de la partición y por qué la señal temporal no se evaluó cuando no se
evaluó. Los perfiles por variable van al anexo de tablas, uno por columna descrita.

## 6. Por código

La sección se configura igual desde YAML o desde Python; la interfaz es un editor del mismo config.
Los analizadores también se usan sueltos, sobre cualquier tabla con un target binario:

<!-- eda-example:start -->
```python
import pandas as pd

from nikodym.eda import DefaultRateAnalyzer, DefaultRateConfig, TemporalStabilityAnalyzer
from nikodym.eda import TemporalStabilityConfig

cartera = pd.DataFrame(
    {
        "cohorte": ["2024Q1", "2024Q1", "2024Q2", "2024Q2", "2024Q3", "2024Q3"],
        "incumplio": [1, 0, 0, 0, 1, 1],
    },
    index=pd.Index([f"op-{i}" for i in range(6)], name="id"),
)

tasa = DefaultRateAnalyzer(
    DefaultRateConfig(axis="cohort", cohort_col="cohorte", min_obs_per_period=1)
).compute(cartera, target_col="incumplio")
print(tasa.by_period[["period", "n_eligible", "n_bad", "default_rate"]])

estabilidad = TemporalStabilityAnalyzer(TemporalStabilityConfig()).assess(tasa)
print(estabilidad.not_evaluable_reason)  # 'eje_cohorte': sobre cohortes la señal no se evalúa
```
<!-- eda-example:end -->

Las palabras con que la pantalla y el informe nombran el eje, el indicador, las causas y las marcas
—y sus identificadores en el JSON— están en la [referencia de la API](../api.md#eje-indicador-causas-y-marcas).
