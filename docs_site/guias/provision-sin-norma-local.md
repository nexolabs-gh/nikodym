# Provisiones sin normativa local

Nikodym trae un motor de provisiones que **no conoce ninguna tabla de supervisor**. Calcula la
pérdida esperada sobre los grupos que tú defines, con tu probabilidad de incumplimiento y tu
severidad, y publica el resultado con trazabilidad completa.

Esta guía lo demuestra corriendo, de punta a punta, sin una sola línea de norma de ningún país.

## Qué hace y qué no

Lo que hace:

> El motor de provisión interna no conoce ninguna tabla de supervisor: tú declaras tus grupos, tu
> PD y tu severidad, y él calcula `PE = PI · PDI · Exposición` con aritmética exacta y trazabilidad
> completa. Lo que no hace es interpretar tu norma por ti: la clasificación, la mora, las garantías
> y los mínimos los aterriza el modelador encima.

Esa frase es el alcance completo, y conviene leerla en los dos sentidos. **El cálculo es neutro de
verdad**: cero matrices, cero tramos de mora, cero categorías de rating, cero porcentajes
normativos. **Y lo que la norma de tu país exige alrededor no está dentro del motor**: la
clasificación de deudores, los tramos de mora, las garantías y sus aforos, los mínimos regulatorios
—salvo el piso y el techo de la severidad— y las provisiones adicionales se calculan fuera y entran
como columnas ya resueltas.

!!! warning "Lo que se calcula fuera no queda en el rastro de auditoría"
    Si precalculas la clasificación o el efecto de las garantías en tu propio proceso, esas
    decisiones **no entran** en el `config_hash` ni en el anexo de configuración del informe. El
    documento será correcto y reproducible respecto de lo que el motor hizo, pero la parte que
    hiciste antes tendrás que documentarla tú. Tenlo presente si el informe va a un validador.

## Qué necesita de tus datos

Cuatro columnas, y ninguna tiene un nombre impuesto:

| Columna | Qué es |
|---|---|
| Fecha de corte | La fecha a la que está referida la cartera. Un solo valor para toda la corrida. |
| Cartera | El grupo al que pertenece cada operación, **en tu taxonomía**. El motor agrupa por ella; no la interpreta. |
| Exposición | El monto expuesto de cada operación. |
| Severidad (LGD) | La pérdida dado el incumplimiento, como columna de tus datos. |

La probabilidad de incumplimiento **no** es una columna: la produce el pipeline —el scorecard
calibrado— o la traes tú como tabla aparte.

## Correrlo

El preset `f5-provision-interna-generica` trae todo configurado sobre un conjunto de datos de
ejemplo cuya cartera se llama `nomina`, `microempresa` y `consumo_senior`: nombres de negocio que
ninguna norma define.

<!-- provision-neutra-example:start -->
```python
from pathlib import Path

import nikodym
from nikodym.core.config import NikodymConfig
from nikodym.ui.datasets import materialize
from nikodym.ui.presets import get_preset

preset = get_preset("f5-provision-interna-generica")
config = dict(preset["config"])

# El preset no trae ruta de datos: apúntala a tu archivo (.csv, .parquet o .xlsx).
# Aquí se materializa el conjunto de ejemplo del propio catálogo.
origen = materialize(preset["dataset_id"], workdir=Path("nikodym-runs"))
config["data"] = {**config["data"], "load": {**config["data"]["load"], "source": str(origen)}}

study = nikodym.run(NikodymConfig.model_validate(config))

card = study.artifacts.get("provisioning_internal", "card")
print(card.total_internal_provision, card.n_groups)
```
<!-- provision-neutra-example:end -->

Con el conjunto de ejemplo eso imprime la provisión total y `30`, que son los grupos: tres carteras
por diez bandas de puntaje.

Desde la interfaz es el mismo camino: eliges el trabajo **Provisión interna**, cargas tus datos,
dices qué columna es cada cosa y ejecutas.

## Qué obtienes

Un informe con su capítulo de provisiones —la provisión constituida, el desglose por grupo y la
configuración efectiva en el anexo—, más las tablas por operación como archivos adjuntos. Sobre el
conjunto de ejemplo son 30 grupos: tres carteras por diez bandas de puntaje.

El informe **no nombra ninguna jurisdicción**, y tampoco afirma una moneda que no le hayas
declarado. Si quieres que la publique, declárala:

```python
config = config.model_copy(update={"report": config.report.model_copy(update={"currency": "S/"})})
```

## Cómo aterrizar tu norma encima

El patrón es siempre el mismo: **lo que tu supervisor define, se resuelve antes y entra como
columna**.

- **Clasificación de deudores.** Calcula tu categoría con tus reglas y pásala como la columna de
  cartera, o como el grupo homogéneo si quieres controlar la agrupación tú mismo.
- **Tramos de mora.** Igual: son un insumo de tu clasificación, no algo que el motor derive.
- **Garantías y aforos.** Ajusta la exposición o la severidad antes de entregarlas.
- **Mínimos.** El piso y el techo de la severidad se declaran en la configuración. Un mínimo sobre
  la provisión o sobre la PD se aplica fuera.

Si prefieres no hacer ese trabajo, lo hace **Nikodym Advisory** como integración. La librería
seguirá siendo gratuita y completa: lo que se paga es el aterrizaje, no el motor.

!!! note "¿Y si mi país necesita un motor propio?"
    No lo vamos a publicar. Mantener al día las circulares de cada supervisor es insostenible para
    una librería, y prometerlo sería peor que no ofrecerlo. Hay **un** caso de referencia
    implementado y congelado —Chile, CMF Capítulo B-1—, que existe como evidencia de que el
    aterrizaje se puede hacer bien: puedes verlo en
    [Aterrizar una norma local](../norma-local.md).
