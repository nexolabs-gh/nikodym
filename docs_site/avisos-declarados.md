# Avisos declarados

Cuando un número no sale de un dato real, Nikodym no lo rellena con un default cómodo: lo marca. La
constancia viaja con el resultado —no en un log que nadie lee— y esta página es el catálogo de esas
marcas, para cuando aparezca una en tu corrida y necesites saber qué significa.

Es referencia técnica del *output* del motor. Si buscas la explicación de qué hace la librería,
empieza por [Conceptos](concepts.md).

## Las dos marcas, y por qué son dos

La diferencia importa, porque una es un pendiente nuestro y la otra una decisión tuya:

**`FALTA-DATO` — lo debe Nikodym.** Una brecha del motor: algo que la librería todavía no trae, que
difirió a una versión posterior, o que no verificó contra la fuente oficial. Son pocas, y están
enumeradas abajo hasta la última.

**`DATO-INSTITUCIONAL` — lo debe tu institución.** Un parámetro, una definición o un dato de entrada
que sólo puede fijar quien usa la librería: los shocks macro de tu ejercicio de stress, tu taxonomía
de estados, tu definición operacional de default. Aquí la marca no confiesa una carencia; deja
constancia de que el motor **se negó a inventar** un supuesto que no le corresponde.

Hasta la versión 1.5.0 ambas cosas compartían la marca `FALTA-DATO`, y el parámetro que le tocaba al
banco se leía como defecto nuestro.

## Dónde los ves

Un aviso declarado llega hasta ti por tres vías, según de qué se trate:

- **`warning_codes`**, una columna del resultado: la fila afectada carga sus códigos. Es la vía de
  los avisos que no impiden calcular.
- **`card.falta_dato`**, en la *model card* de la corrida: el consolidado por paso, para gobernanza.
- **Una excepción al validar el config o al ejecutar**, cuando el motor no puede seguir sin ese dato.
  No hay resultado parcial que marcar: el aviso *es* el mensaje del error.

En el informe HTML/PDF/Word los códigos aparecen sólo en el volcado de auditoría del anexo. La prosa
del informe explica la limitación en palabras, sin nombrar el código.

## Catálogo

Los códigos siguen la forma `MARCA-FAMILIA-N`. La familia dice de qué capacidad viene.

### `FALTA-DATO` — brechas del motor

| Código | Qué falta |
| --- | --- |
| `FALTA-DATO-IFRS-4` | La EAD se despliega **constante por período**: el panel longitudinal está diferido. Cada fila lo declara, y el config **rechaza** `exposure_profile_col` en vez de fingir que lo usa. |
| `FALTA-DATO-IFRS-6` | La LGD condicionada que trae la *term-structure* de forward-looking no se consume en v1: el motor estima la LGD desde el `frame` y declara el descarte en vez de callarlo. |
| `FALTA-DATO-IFRS-8` | El `horizon_12m_periods` que declaraste no es conmensurable con el largo de tu curva: o el horizonte alcanza todo su soporte —y entonces un Stage 1 provisiona lo mismo que un Stage 2— o cae por debajo del primer período —y Stage 1 provisiona cero—. En ambos casos la corrida terminaba `done` y los totales se veían razonables. Declararlo es tuyo; **verificar que sea coherente con la curva recibida es del motor**, y hasta ahora no lo hacía. |
| `FALTA-DATO-ML-1` | `feature_source='data_raw'` está diferido. El modo crudo exige una política de imputación por variable que la librería todavía no ofrece; usa `binning_woe` o `selection_woe`. |
| `FALTA-DATO-FWD-6` | La precedencia entre la LGD de forward y la de IFRS 9 está pendiente de diseño. No se emite en runtime: queda documentado en el código que la fija. |
| `FALTA-DATO-FWD-8` | `kind='vecm'` exige `vecm_rank` explícito, porque el motor todavía **no selecciona el rango de cointegración**. |
| `FALTA-DATO-VAL-1` | La forma exacta del t-test ECB —simple o ponderado por exposición, y su orientación— no está verificada contra el render oficial. |
| `FALTA-DATO-VAL-2` | Los cortes del semáforo de VaR (Basilea-1996) no están verificados contra el render oficial. |
| `FALTA-DATO-VAL-3` | La orientación exacta del p-valor de Jeffreys —la CDF de la posterior en `p_hat`— no está verificada contra el render oficial. |
| `FALTA-DATO-STR-5` | Falta la ECL de referencia que el ejercicio de stress necesita para el cálculo. |

Las tres de `VAL` son la misma clase de brecha: la convención metodológica está implementada, pero
no cotejada contra el documento original. Es la aplicación literal de nuestra regla de verificación
—una fuente externa se coteja contra el render oficial o se declara sin verificar—, no un descuido.

Fuera de esta tabla quedan dos brechas normativas del motor CMF que no viajan como código de fila
sino como parámetro marcado: los aforos y *haircuts* de garantías financieras, y las tablas del
RAN 21-10. Están registradas en el
[cotejo de parámetros normativos](https://github.com/nexolabs-gh/nikodym/blob/main/docs/normativa_cmf_parametros.md).

### `DATO-INSTITUCIONAL` — inputs que aporta la institución

| Código | Qué te toca declarar |
| --- | --- |
| `DATO-INSTITUCIONAL-EXP-1` | El `top_n` y la dirección adversa de los *reason codes*. La referencia es ECOA/FCRA, **no** norma CMF: el corte lo fija tu política. |
| `DATO-INSTITUCIONAL-EXP-2` | El umbral de gobierno sin el cual los *reason codes* son irrelevantes. No se emite en runtime: queda documentado en el módulo. |
| `DATO-INSTITUCIONAL-FWD-1` | Los escenarios `adverse` y `severe` deben declarar su `macro_path_path` o sus `shocks`. Un escenario adverso sin trayectoria no es un escenario. |
| `DATO-INSTITUCIONAL-FWD-4` | `ttc_anchor='input_term_structure'` sin un `pd_basis='ttc'` resuelto: se usa como ancla TTC con base PIT o desconocida, y se advierte explícitamente. |
| `DATO-INSTITUCIONAL-FWD-5` | Historia insuficiente para ajustar el modelo satélite, según el `min_history_periods` que tú fijaste. |
| `DATO-INSTITUCIONAL-IFRS-7` | La unidad temporal de la curva de PD. El descuento eleva el plazo de cada punto como exponente **en años**, así que si tu curva viene en meses o trimestres y no lo dice, la provisión sale mal por un factor grande. Cuando la curva no la declara, el motor asume años y lo deja escrito aquí en vez de callarlo. Se declara en `time_grid.time_unit` (survival) o `dynamics.time_unit` (markov); ojo con el default `"period"`, que **no** es una unidad. |
| `DATO-INSTITUCIONAL-PROV-1` | Una celda de la comparación no tiene contraparte en el otro motor. |
| `DATO-INSTITUCIONAL-PROV-2` | Una celda imputó 0 a un motor por `coverage_policy='treat_missing_as_zero'`. La imputación es tu política, no un supuesto nuestro. |
| `DATO-INSTITUCIONAL-PROV-3` | Comparación incompleta: sólo un motor está presente (`require_both=False`). |
| `DATO-INSTITUCIONAL-PROV-4` | Una cartera de la primera fuente no pertenece a la taxonomía que declaró la segunda, ni siquiera tras aplicar el mapeo. Sólo tu institución sabe qué cartera equivale a cuál, así que el motor no lo adivina: declara la equivalencia en `portfolio_crosswalk`. |
| `DATO-INSTITUCIONAL-STR-1` | No existe un *delta* adverse trazable para ese escenario, factor y períodos, así que la dominancia no se puede verificar. |
| `DATO-INSTITUCIONAL-STR-2` | `source='official'` exige metadata externa de archivo, hash y fuente. Un shock que se declara oficial trae su evidencia o no es oficial. |
| `DATO-INSTITUCIONAL-STR-8` | `output.metrics` incluye `lgd`, pero `lgd`/`lgd_base` no están disponibles para ese escenario y período. |
| `DATO-INSTITUCIONAL-VAL-4` | Pediste la familia `backtesting` pero la dejaste apagada. El backtesting IFRS 9 necesita estar habilitado y con sus columnas realizadas declaradas: cuáles son sólo lo sabe tu institución. |
| `DATO-INSTITUCIONAL-SUR-1` | La grilla temporal de la curva de supervivencia. Sin ella el motor cae a los tiempos de evento observados —y si no hubo eventos, a los máximos observados— y lo advierte. |
| `DATO-INSTITUCIONAL-SUR-2` | No hay eventos observados en la partición, así que la curva no es estimable con esos datos. |
| `DATO-INSTITUCIONAL-SUR-3` | El intervalo de confianza de la curva no está disponible con la configuración entregada. |

## Cómo se clasifica un código nuevo

La regla cabe en una línea: `FALTA-DATO` es *lo debe Nikodym*; `DATO-INSTITUCIONAL` es *lo debe la
institución*. Con una precisión que evita el caso ambiguo: **una capacidad diferida es del motor
aunque el parámetro lo escriba el usuario**. Si la librería no la trae todavía, la deuda es nuestra
por más que el dato tenga que ponerlo alguien más.

Las dos marcas viven en `nikodym.core.markers`, y el código que las consume usa `is_declared_warning()`
en vez de comparar el literal: un filtro que sólo conozca una de las dos descartaría la otra en
silencio.

```python
from nikodym.core.markers import is_declared_warning

# Todos los avisos declarados de la fila, de cualquiera de las dos marcas.
declarados = [c for c in fila.warning_codes if is_declared_warning(c)]

# Sólo los de una familia.
ifrs = [c for c in fila.warning_codes if is_declared_warning(c, family="IFRS")]
```

## Qué hacer si aparece uno

Depende de la marca, y por eso son dos:

- **`FALTA-DATO`**: no hay nada que configurar. El número salió con un supuesto que la librería
  declara; decide si ese supuesto es tolerable para tu uso, y si no lo es, la capacidad todavía no
  está.
- **`DATO-INSTITUCIONAL`**: falta un input tuyo. La tabla de arriba dice cuál. Entrégalo y el aviso
  desaparece.

`fail_on_falta_dato` significa **una sola cosa** en todas las capas que lo exponen: *¿un aviso
declarado **gobernable** emitido durante la corrida la detiene?* Con `True` —el default— la detiene;
con `False` queda registrado en el resultado y el cálculo sigue.

La única sutileza que hay que conocer es qué avisos son **gobernables**:

- Un aviso es **estructural** cuando el motor lo emite en toda corrida por una capacidad diferida
  propia, y por eso **nunca** detiene: abortar por él dejaría el motor inservible con su propio
  valor por defecto. `FALTA-DATO-IFRS-4` es el caso: la EAD constante por período se declara siempre,
  entregues los datos que entregues, así que activar el flag **no** hará que corte.
- Todos los demás son **gobernables**: dependen de lo que entregues, y declarar el dato que piden
  los hace desaparecer. `DATO-INSTITUCIONAL-IFRS-7` —la unidad temporal de la curva— es uno de
  ellos, así que con el flag en su valor por defecto una curva que no declare su unidad **detiene la
  corrida**. Declararla es todo lo que hace falta para que siga.
