# Enmienda SDD — horizonte 12m de IFRS 9: la verificación que el motor no hace

> **Estado: PROPUESTA — requiere OK de Cami antes de programar.** No se ha escrito una línea de
> motor. Lo único ejecutado es la corrección del texto de SDD-16, que afirmaba un aviso inexistente.
>
> **Revisión adversarial (2026-07-25):** la primera versión de esta enmienda tenía **un argumento
> falso, un gatillo que no funcionaba y un blast radius subestimado**. Un revisor fresco lo demostró
> instrumentando el motor, no leyendo la prosa. Esta versión incorpora sus correcciones y deja
> anotado, abajo, qué decía la versión anterior — porque el error es informativo: casi todo venía de
> razonar sobre lo que el código *debería* hacer.
>
> **Base:** `main` = `c6580a0`.
> **Autor / Fecha:** DanIA / 2026-07-25.

| Campo | Valor |
|---|---|
| **Problema** | `horizon_12m_periods` asume periodicidad mensual por default y nadie lo contrasta con la curva recibida: una configuración plausible produce una ECL de Stage 1 incorrecta **en silencio** |
| **Enmienda a** | SDD-16 (§8 casos borde, §9 audit trail, ficha IFRS-2) |
| **No toca** | La clasificación de IFRS-1…IFRS-6, ni el contrato de `core/markers.py`, ni la firma de `marginal_to_horizon` |
| **Release** | `1.6.0` — `provisioning/ifrs9` es experimental; el pipeline F1 estable no participa |
| **Decisión previa que la bloquea** | **En qué unidad está `time_value`, quién la declara y quién la verifica** (§5). Sin eso, cualquier gatillo se apoya en un supuesto no escrito |

---

## 1. El problema, medido

`IfrsPdConfig.horizon_12m_periods: int = Field(default=12, …)`
(`provisioning/ifrs9/config.py:125`) declara cuántos períodos de la term-structure cubren 12 meses.
Su única validación es `ge=1`. El `@model_validator` `_check_pd` no lo mira, y `marginal_to_horizon`
(`provisioning/ifrs9/pd_pit.py`) valida columnas, rango de `pd_marginal` y `period >= 1` — nada
sobre la curva contra la que ese horizonte se aplica.

El corte del horizonte aparece **dos veces, por separado**:

```python
within_12m = working["period"] <= horizon_periods   # pd_pit.py — PD 12m vs lifetime
within_12m = cols["period"] <= horizon_12m          # ecl.py:253 — componentes de la ECL
```

Esto importa para no contar mal la historia: **la ECL no consume `pd_12m`**. Aquella viaja a
`detail`, `staging` e `IfrsEclRecord`; la ECL se trunca sola, con su propia máscara. Lo que une a
las dos es que **leen el mismo campo de config** (`engine.py:262` y `:795`), así que un
`horizon_12m_periods` mal puesto las descuadra a ambas — pero por un origen común, no porque una
cause la otra. *(La versión anterior decía «`pd_12m == pd_life` **y por tanto** la ECL…». Es un non
sequitur: con `base_pd_source="calibration"` se midió `pd_12m ≠ pd_life` y la ECL igual idéntica.)*

De ahí salen dos modos de fallo. Sólo el primero está confirmado ejecutando el motor:

- **A · El horizonte alcanza el soporte de la curva preparada.** El umbral **no es `T_max`**: es
  `min(T_max, max_lifetime_periods)`, porque `_prepare_term_structure` (`engine.py:690-697`) trunca
  la curva **antes** de todo. Cuando `horizon_12m_periods` alcanza ese mínimo, la máscara queda toda
  verdadera y la ECL a 12 meses iguala a la lifetime: **un Stage 1 provisiona exactamente lo mismo
  que un Stage 2**. La corrida termina `done`, la card no dice nada y los totales se ven razonables.
  Con `stage3_direct=True` (no es el default) el Stage 3 se recalcula aparte y **no** iguala — medido
  en 5,14×. Por eso el caso borde de SDD-16 habla de Stage 1 y Stage 2, no de «Stage 2/3».
- **B · El default no corresponde a la periodicidad real.** Una institución con curva trimestral que
  no toca el campo acumularía 12 trimestres —tres años— y los reportaría como 12 meses. **Nada en el
  motor lo impide** (verificado). Pero, a diferencia de A, hoy **no hay forma de detectarlo**: ver §2.

Ambos son sobreestimaciones —contablemente conservadoras— pero **incorrectas**, y en un motor de
provisiones un número conservador equivocado sigue siendo un número del que hay que responder.

**Lo que sí existía era la promesa.** SDD-16 §8 decía «warning; … y se registra
`DATO-INSTITUCIONAL-IFRS-2`». `git grep IFRS-2 src/ tests/ web/src/` devuelve cero y `git log -S`
confirma que nunca estuvo: no es un código que se borró, es uno que jamás se escribió. Ese texto ya
fue corregido; esta enmienda diseña el arreglo.

## 2. Por qué esto todavía no se puede programar (D-HOR-0)

La primera versión proponía dos gatillos. **El segundo no funciona, y el primero no basta.**

**El gatillo por unidad (`time_value` cerca de 1.0 en el período del horizonte) es indefendible
hoy.** La unidad de `time_value` **no está fijada en ninguna parte del sistema**: `time_unit` es un
string declarativo con default `"period"` (`survival/config.py:137-142`, `markov/config.py:236-241`)
y **IFRS 9 nunca lo lee** — cero ocurrencias. Markov publica `time_value = horizon` en la unidad
declarada (`markov/term_structure.py:442,501`). Con lectura unidad-nativa, una curva **mensual
correcta** con `H=12` da `time_value = 12.0` en ese período, exactamente igual que la **trimestral
equivocada**. El gatillo no separa el caso bueno del malo: **dispararía sobre el correcto**, que es
el modo de fallo que mata un aviso —enseña a ignorarlo— y viola el criterio de aceptación #3 de esta
misma enmienda.

**Y hay algo mayor detrás, que esta enmienda no puede resolver sola.** Si `time_value` viene en
meses o trimestres, **el descuento también está mal**: `ecl.py:204` lo usa como exponente crudo bajo
`discount_convention="annual_eir_year_fraction"` (el default), así que `(1+EIR)^-12` para un
horizonte de doce meses son doce años de descuento. SDD-16:167 dice que τ es «el tiempo en años
**derivado de** `time_value`/unidad temporal», pero **esa derivación no existe en el código**. El
horizonte es un síntoma; la ambigüedad de unidad es la enfermedad, y toca la cifra de ECL de
cualquier corrida cuya curva no esté en años.

**El gatillo por soporte (modo A) sí es implementable**, con dos correcciones sobre la primera
versión:

- El umbral es `min(T_max, max_lifetime_periods)`, no `T_max`.
- **No todo disparo es un defecto.** Quien fija `max_lifetime_periods=1` está truncando **a
  propósito** —hay test que lo cubre, `test_ifrs9_engine.py:719`— y avisarle de lo que pidió es
  ruido. El predicado tiene que distinguir el truncado deliberado del horizonte que se comió la
  curva sin que nadie lo mirara.
- El caso «el período del horizonte no existe en la curva» **no está cubierto por A**, contra lo que
  decía la versión anterior: con `periods={3}` y `H=1` el gatillo A no dispara y una mediana sobre
  selección vacía es `NaN`, que en toda comparación da `False` — el predicado queda **mudo, sin
  error**. Hay 4 casos así en el corpus.

## 3. Blast radius, medido (no estimado)

Instrumentando `EclEngine.compute` sobre 914 tests: **78 corridas ECL observadas, 28 dispararían el
gatillo A (35,9 %)**. La primera versión hablaba de «4 aserciones de tupla exacta»: se quedó corta
por un orden de magnitud.

**Pero el número hay que leerlo bien, en las dos direcciones.** De esas 28, **25 son el combo
`H=1, T_max=1`**: fixtures mínimos de una sola fila, no corridas realistas. Y el preset F4 de la
demo —la única corrida real publicada— **no dispara**: `T_max = 5`, `horizon_12m_periods = 1`
(`presets.py:764`), verificado contra `results-ifrs9.json` y ejecutando el preset. **La demo, el
número insignia y el deploy están a salvo**, y el criterio de aceptación #5 ya está satisfecho sin
escribir código.

O sea: el aviso **no** sería ruidoso en producción, pero **sí** obliga a tocar ~28 corridas de test.
Ese es el costo real, y es de trabajo, no de señal.

## 4. Alcance, si se aprueba

Cada eslabón sale del patrón de `FALTA-DATO-IFRS-6`, que es el aviso condicional que ya funciona de
punta a punta:

| Archivo | Cambio |
|---|---|
| `provisioning/ifrs9/engine.py` | Constante `_WARNING_HORIZON_MISMATCH` + predicado + append condicional junto al de IFRS-6 |
| `provisioning/ifrs9/step.py` | `ifrs9_pd_horizon` registra el `T_max` **observado** y el umbral efectivo, no sólo los dos campos de config |
| `report/prose.py` | Entrada en `_IFRS9_WARNING_LABELS`. **No es opcional**: `renderer.py` retira `warning_codes` de las tablas, así que un código sin label es invisible en el entregable. El texto explica la limitación **sin nombrar el código** |
| `methodology.py` | Frase metodológica, replicando el patrón de IFRS-4 |
| Tests | Espejo del bloque de IFRS-6, más las ~28 corridas cuyo `card.falta_dato` cambia |

**Marca: `FALTA-DATO` (D-HOR-2).** *Declarar* la periodicidad es de la institución: sólo ella sabe
si su curva es mensual. *Verificar que lo declarado sea coherente con lo recibido* es del motor, y
hoy no lo hace. Por la regla de que una capacidad diferida es del motor aunque el parámetro lo
escriba el usuario (precedente `FWD-8`), el aviso nace `FALTA-DATO`. IFRS-2 se queda como requisito
documentado, sin código emitido.

**Aviso, no excepción (D-HOR-3).** ⚠️ La primera versión justificaba esto diciendo que «quien quiera
el fail-fast ya tiene `fail_on_falta_dato=True`». **Es falso.** En `provisioning_ifrs9` ese flag es
un gate de **validación de config** (`config.py:637-660`): sólo exige `rho` y `systemic_factor_col`
cuando `pit_mode="apply_vasicek"`, y **nunca inspecciona `card.falta_dato` ni `warning_codes`**. La
prueba está publicada: el preset F4 lleva `fail_on_falta_dato: True` y su fixture trae
`falta_dato: ["FALTA-DATO-IFRS-4"]` con la corrida completa. **Hoy nadie tiene fail-fast por aviso
declarado en IFRS 9**, y eso es un hueco aparte que conviene mirar. La decisión de que sea aviso y
no excepción se sostiene por otra razón: el motor **infiere** el desajuste a partir de un dato cuya
unidad no controla, y un fail-fast sobre una inferencia rompe corridas legítimas con convenciones
que no anticipamos.

## 5. La decisión que va primero

**¿En qué unidad está `time_value`, quién la declara y quién la verifica?** De eso dependen tres
cosas, y sólo una es esta enmienda:

1. El gatillo por unidad (§2), que sin esto no se puede escribir.
2. **El descuento de la ECL**, que hoy asume años sin verificarlo — de mayor impacto que el horizonte.
3. La frontera con survival/markov, que publican `time_value` en la unidad que declaran y no
   convierten.

Mi recomendación es resolver (1)+(2) juntos en una enmienda de **unidad temporal**, y que el aviso
de horizonte sea una consecuencia suya, no un parche previo. Programar sólo el gatillo A ahora
arregla el caso visible y deja intacto el que mueve la cifra.

## 6. Lo que queda fuera a propósito

- **Inferir la periodicidad y corregir `horizon_12m_periods` solo.** El motor declararía haber
  entendido un dato que la institución no confirmó. Se declara el desajuste; el número lo arregla
  quien tiene autoridad para hacerlo.
- **Tocar `DATO-INSTITUCIONAL-SUR-1`** o la frontera con survival, más allá de nombrarla en §5.
- **Reclasificar IFRS-1, 3 y 5.** Son requisitos documentados y se quedan como están.
