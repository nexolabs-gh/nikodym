# Provisiones sin normativa local

Nikodym trae un motor de provisiones que **no conoce ninguna tabla de supervisor**. Calcula la
pérdida esperada sobre los grupos que tú defines, con tu probabilidad de incumplimiento y tu
severidad, y publica el resultado con trazabilidad completa.

Esta guía lo demuestra corriendo, de punta a punta, sin una sola línea de norma de ningún país.

!!! note "Estabilidad (SemVer 1.x)"
    La sección `provisioning_internal` es **experimental**, igual que el resto de provisiones del
    paquete: está implementada, testeada y con preset e informe propios, pero queda **fuera de la
    garantía SemVer 1.x** —el contrato puede crecer o cambiar antes de un 2.0—. La parte estable
    del camino es el pipeline de scorecard F1 que produce la PD.

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

# `run_dir` es donde queda la evidencia de la corrida: el audit-trail, el entorno y —si
# declaras la sección `governance`— el model card. Sin él la corrida no escribe nada.
study = nikodym.run(
    NikodymConfig.model_validate(config),
    run_dir=Path("nikodym-runs") / "provision-interna",
)

card = study.artifacts.get("provisioning_internal", "card")
print(card.total_internal_provision, card.n_groups)
```
<!-- provision-neutra-example:end -->

Con el conjunto de ejemplo eso imprime la provisión total y `30`, que son los grupos: tres carteras
por diez bandas de puntaje.

Desde la interfaz es el mismo camino: eliges el trabajo **PD + LGD en una corrida**, cargas tus
datos, dices qué columna es cada cosa y ejecutas. Es el trabajo que corre la cadena completa
—scorecard y provisión en una sola corrida—, igual que el ejemplo de arriba. Si tu PD ya está
calculada y sólo quieres la provisión, el trabajo es **Provisión interna / LGD**, que en vez de
estimarla te pide subir la PD calibrada como una tabla aparte.

## Qué obtienes

Un informe con su capítulo de provisiones: la provisión constituida, el desglose por grupo y la
configuración efectiva en el anexo. Sobre el conjunto de ejemplo son 30 grupos: tres carteras por
diez bandas de puntaje.

El preset genera el informe en `html`, `pdf`, `md` y `docx`. Las tablas **por operación** no caben
en el documento, así que si las quieres completas hay que pedirlas: añade `csv` o `xlsx` a
`report.formats` y quedarán como archivos en el directorio de salida —no entre los botones de
descarga de la interfaz—.

El informe **no nombra ninguna jurisdicción**, y tampoco afirma una moneda que no le hayas
declarado. Si quieres que la publique, decláralo en el config antes de `nikodym.run(...)`:

<!-- provision-neutra-moneda:start -->
```python
config["report"] = {**config["report"], "currency": "S/"}
```
<!-- provision-neutra-moneda:end -->

## Cómo aterrizar tu norma encima

El patrón es siempre el mismo: **lo que tu supervisor define, se resuelve antes y entra como
columna**.

- **Clasificación de deudores.** Calcula tu categoría con tus reglas y pásala como la columna de
  cartera, o como el grupo homogéneo si quieres controlar la agrupación tú mismo.
- **Tramos de mora.** Igual: son un insumo de tu clasificación, no algo que el motor derive.
- **Garantías y aforos.** Ajusta la exposición o la severidad antes de entregarlas.
- **Mínimos.** El piso y el techo de la severidad se declaran en la configuración. Un mínimo sobre
  la provisión o sobre la PD se aplica fuera.

!!! warning "La comparación contra tu método estándar no se puede declarar"
    Si tu supervisor exige constituir el **máximo** entre su método estándar y el método interno,
    esa comparación **hoy no es expresable en la configuración**. El comparador de provisiones sólo
    admite como fuentes los tres motores que trae el paquete
    (`ProvisioningSource`, `src/nikodym/provisioning/config.py:64`) y además exige que las dos sean
    **distintas**, así que no hay forma de apuntar una de ellas a un cálculo tuyo. La salida es
    correr el método interno con Nikodym, calcular tu método estándar por fuera y quedarte con el
    máximo en tu propio proceso —con la salvedad del recuadro de arriba: ese último paso no queda
    en el rastro de auditoría del informe—.

Si prefieres no hacer ese trabajo, lo hace **Nikodym Advisory** como integración. La librería
seguirá siendo gratuita y completa: lo que se paga es el aterrizaje, no el motor.

!!! note "¿Y si mi país necesita un motor propio?"
    No lo vamos a publicar. Mantener al día las circulares de cada supervisor es insostenible para
    una librería, y prometerlo sería peor que no ofrecerlo. Hay **un** caso de referencia
    implementado y congelado —Chile, CMF Capítulo B-1—, que existe como evidencia de que el
    aterrizaje se puede hacer bien: puedes verlo en
    [Aterrizar una norma local](../norma-local.md).
