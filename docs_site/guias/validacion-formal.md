# Validación formal

La **validación formal** es el acta de las pruebas que documentan un scorecard: qué se probó, con
qué muestra, qué salió y qué quedó sin evaluar. Corre penúltima en el pipeline —justo antes del
informe— y no vuelve a calcular nada que las etapas anteriores ya hayan calculado: consume la
discriminación de desempeño y el PSI de estabilidad, y **añade** lo que ninguna otra etapa hace,
que es contrastar la probabilidad estimada contra el incumplimiento observado.

!!! warning "El estado técnico no es el veredicto"
    Nikodym publica evidencia: cuántas pruebas corrieron, cuáles fallaron y sobre qué población.
    Aprobar el modelo, aprobarlo con observaciones o rechazarlo es una decisión de quien valida, y
    el informe lo dice explícitamente en su capítulo. Un «Falla» aquí es una prueba que rechazó,
    no una sentencia sobre el modelo.

!!! note "Los números de esta guía"
    Salen de una **corrida real** del trabajo «Scorecard de comportamiento (PD)» sobre el dataset
    sintético de consumo (6.000 operaciones, partición por cohorte). No son benchmarks: ilustran la
    forma y las magnitudes que produce el pipeline.

---

## 1. Las cuatro familias

La sección **Validación formal** del formulario agrupa sus pruebas en cuatro familias, y eliges
cuáles corren. Al menos una: una validación vacía no valida nada, y el motor lo dice antes de
empezar en vez de terminar con las manos vacías.

| Familia | Qué responde | De dónde sale |
|---|---|---|
| **Discriminación** | ¿El modelo separa a quien incumple de quien no? | Reúsa el AUC, el Gini y el KS de la etapa de desempeño |
| **Calibración** | ¿La probabilidad que da es la que ocurre? | Lo calcula esta etapa |
| **Estabilidad** | ¿La población se movió? | Reúsa el PSI de la etapa de estabilidad |
| **Backtesting** | ¿Lo estimado coincidió con lo que pasó? | Contrasta contra IFRS 9; viene apagado |

Las tres primeras vienen encendidas. El **backtesting** no: necesita que la corrida calcule IFRS 9
y que tu archivo traiga las columnas con el resultado realizado, y no todos los modelos del
inventario las tienen. Elegir la familia sin activar el backtesting detiene la corrida con un
mensaje que apunta al interruptor exacto; si prefieres que quede registrado como aviso y la corrida
siga, apaga «Fallar ante brechas críticas de dato».

## 2. Discriminación

Una fila por muestra, con la población, las tres métricas y de dónde salieron. Por defecto se
reúsan las que ya calculó la etapa de desempeño: son los mismos números, no un segundo cálculo que
podría diferir en el cuarto decimal y abrir una discusión inútil.

| Muestra | Operaciones | Incumplidas | AUC | Gini | KS |
|---|---:|---:|---:|---:|---:|
| Desarrollo | 4.019 | 920 | 0,7128 | 0,4255 | 0,3151 |
| Holdout | 973 | 248 | 0,6768 | 0,3535 | 0,2558 |
| Fuera de tiempo | 1.008 | 239 | 0,6505 | 0,3009 | 0,2210 |

Qué mide cada una está en [Desempeño y estabilidad](desempeno-estabilidad.md). Una muestra que tu
partición no produzca —o que tenga una sola clase— sale marcada como **No evaluable**, sin métricas
inventadas.

## 3. Calibración

Es la familia que esta etapa aporta de nuevo, y responde una pregunta que la discriminación no
toca: un modelo puede ordenar el riesgo perfectamente y aun así equivocarse en el **nivel** de la
probabilidad.

### Por muestra: Hosmer-Lemeshow y el puntaje de Brier

**Hosmer-Lemeshow** parte la cartera en grupos de PD —diez, por convención— y compara, grupo a
grupo, los incumplimientos esperados con los observados. Un p-valor bajo significa que la PD
predicha y la observada no cuadran.

**El puntaje de Brier** es el error cuadrático medio entre la PD predicha y lo que ocurrió. Más bajo
es mejor. No es una prueba de pasa o falla: es un puntaje, y por eso su fila sale **Sin veredicto**.

| Muestra | Prueba | Operaciones | Estadístico | p-valor | Veredicto |
|---|---|---:|---:|---:|---|
| Desarrollo | Hosmer-Lemeshow | 4.019 | 13,6787 | 0,0905 | Pasa |
| Desarrollo | Puntaje de Brier | 4.019 | 0,1581 | — | Sin veredicto |
| Holdout | Hosmer-Lemeshow | 973 | 9,4696 | 0,3042 | Pasa |
| Holdout | Puntaje de Brier | 973 | 0,1759 | — | Sin veredicto |
| Fuera de tiempo | Hosmer-Lemeshow | 1.008 | 18,2021 | 0,0198 | **Falla** |
| Fuera de tiempo | Puntaje de Brier | 1.008 | 0,1725 | — | Sin veredicto |

Esa corrida termina con **Estado técnico: Falla** y «1 de 3 pruebas fallidas». No es un defecto de
la configuración: el rechazo está en la muestra fuera de tiempo y es deriva temporal de la cartera
—lo que la validación existe para detectar—. La pantalla y el informe lo publican tal cual; no se
maquilla ni se esconde.

### Por grado de rating

Si tu archivo trae una columna con el grado de rating de cada operación, puedes encender el
contraste **por grado**: grado a grado, comprueba si los incumplimientos observados caben en la PD
estimada, y le pone un semáforo a cada uno.

Viene **apagado** en los trabajos del scorecard, y con razón medida: un panel de comportamiento no
trae grados de rating, así que encenderlo sin la columna detiene la corrida. Cuando lo enciendes,
el formulario te pide la columna y la comprueba contra tu archivo **antes** de calcular nada.

!!! danger "Un grado sin población no recibe semáforo"
    Un grado con menos operaciones que el mínimo técnico —30 de fábrica— no produce veredicto: sin
    esa población, cualquier resultado sería ruido. Esos grados **no** entran en la tabla ni cuentan
    en las pruebas fallidas, así que el panel publica siempre la cobertura —«3 de 5 evaluados»— y
    enumera aparte los que quedaron fuera, con sus conteos y el mínimo que los excluyó. Sin esa
    línea, un «Pasa · 0 de 1 pruebas fallidas» podría convivir con media cartera sin evaluar.

Dos ajustes finos, los dos institucionales y no fijados por norma: los **cortes del semáforo** sobre
el p-valor (verde/ámbar y ámbar/rojo) y **qué prueba** se usa —la de Jeffreys, que se comporta bien
cuando un grado no registró ningún incumplimiento, o la binomial clásica—. Los dos salen del
resultado con un aviso declarado: son una brecha del motor que Nikodym prefiere decir en voz alta
antes que resolver por su cuenta.

## 4. Estabilidad

La misma tabla de PSI que ya viste en «Estabilidad del score», aquí dentro del acta: una fila por
magnitud y comparación, con su valor, su banda y su veredicto. No se recalcula; se documenta.

| Magnitud | Comparación | PSI | Banda |
|---|---|---:|---|
| score | Dev vs Holdout | 0,0189 | Estable |
| score | Dev vs OOT | 0,0082 | Estable |
| PD calibrada | Dev vs Holdout | 0,0209 | Estable |
| PD calibrada | Dev vs OOT | 0,0095 | Estable |

Las cuatro palabras de las bandas y su acción están en la
[referencia de la API](../api.md#bandas-de-estabilidad).

## 5. Backtesting

Contrasta lo que IFRS 9 estimó contra lo que de verdad ocurrió, parámetro por parámetro y segmento
por segmento. Eliges qué parámetros contrastar —la probabilidad de incumplimiento, la severidad, la
exposición— y cada uno exige su columna con el resultado realizado.

Dos detalles que el copy del formulario declara y conviene tener presentes:

- **El contraste unilateral** sólo gobierna la severidad y la exposición: prueba si el parámetro se
  subestimó, que es lo que le importa al supervisor. La prueba de la probabilidad de incumplimiento
  es siempre unilateral y ese ajuste no la cambia.
- **Una columna realizada ausente no siempre detiene la corrida.** Con «Fallar ante brechas críticas
  de dato» apagado, el aviso queda registrado, esa prueba se omite y la corrida termina. Encendido,
  se detiene. La única columna que detiene **siempre** es la de grado de rating, porque sin ella el
  contraste por grado no puede ni empezar.

## 6. Qué hace un validador con esto

- **Lee el estado técnico y el conteo, no sólo el estado.** «Falla · 1 de 3» y «Falla · 3 de 3» son
  situaciones distintas.
- **Mira la cobertura antes que el veredicto.** Un estado verde sobre media cartera sin evaluar no
  es un estado verde.
- **Separa la deriva del defecto.** Un rechazo que aparece sólo fuera de tiempo suele ser la
  cartera moviéndose, no el modelo mal construido; un rechazo en desarrollo casi nunca lo es.
- **Trata los avisos declarados como preguntas abiertas.** Cada uno señala algo que le corresponde
  decidir a tu institución o una brecha que el motor prefiere declarar antes que resolver sola. Qué
  significa cada uno está en [Avisos declarados](../avisos-declarados.md).

## 7. Por código

La sección se configura igual desde YAML o desde Python; la interfaz es un editor del mismo config.

```python
from nikodym.validation.config import ValidationConfig
from nikodym.validation.evaluator import ValidationEvaluator

config = ValidationConfig(
    families=("discrimination", "calibration", "stability"),
)
resultado = ValidationEvaluator.from_config(config).validate(
    calibrated_pd=frame_pd_calibrada,
    performance_metrics=metricas_de_desempeno,
    stability_metrics=metricas_de_estabilidad,
    model_ref="scorecard-consumo",
)
print(resultado.card.overall_status, resultado.card.n_failed, "de", resultado.card.n_tests)
```

!!! note "Validar un modelo que no ajustaste aquí"
    El trabajo «Validar un modelo existente» mide y documenta tu scorecard con desempeño y
    estabilidad, pero **no** incluye todavía la validación formal: sus pruebas de calibración leen
    la PD desde un artefacto interno cuyas columnas la interfaz no expone, así que un archivo con
    otros nombres de columna no tendría dónde declararlos. Por código no hay tal límite: construye
    el `ValidationEvaluator` con tu propio frame, como en el ejemplo de arriba.

Los campos, sus rangos y sus defaults están en la
[referencia de la API](../api.md#validacion).
