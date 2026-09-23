# Enmienda — un bin de faltantes sin una clase no mata la corrida, y excluir excluye de verdad

| Campo | Valor |
|---|---|
| **Tipo** | Enmienda corta a [`06-binning.md`](06-binning.md) (§8, manejo de errores), a [`_ENMIENDA-CATEGORIA-RARA-SIN-CLASE.md`](_ENMIENDA-CATEGORIA-RARA-SIN-CLASE.md) (la extiende a los bins de faltantes y especiales) y a [`_ENMIENDA-FLUJO-GUIADO-SCORECARD.md`](_ENMIENDA-FLUJO-GUIADO-SCORECARD.md) (el contrato de `exclude`) |
| **Decisiones** | **D-FAL-1** (el WoE de un bin de faltantes o especiales sin una clase se **asigna** con una regla declarada), **D-FAL-2** (qué dicen las superficies) y **D-EXC-1** (`exclude()` descarta en toda la corrida, binning incluido) |
| **Módulos** | `nikodym.binning` (`transformer`, `results`, `step`), `nikodym.guided` (`scorecard`, `summaries`) |
| **Fase** | F1 |
| **Estado** | **APROBADA por Cami el 2026-09-23** (interactivo): regla **conservadora** (§5.1 a) y `exclude()` en toda la corrida (§5.2 a); **implementada el mismo día** (lo que el código precisó, en §7) |
| **Depende de** | D-RAR-1/2, D-SC-19/20 (el patrón: un error fatal pasa a ser una degradación **declarada**), D-FLU (decisiones humanas) |
| **Release** | Aditiva para todo lo que hoy corre: D-FAL-1 sólo entra donde la corrida iba a morir. D-EXC-1 cambia qué hace `exclude()`, pero sólo para acercarlo a lo que su propio contrato ya promete ⇒ **minor** |
| **Autor / Fecha** | Claude Code (writer) / 2026-09-23 |

---

## 0. Por qué existe: medido con un dataset real

Cami pidió probar la librería con datos **reales con fecha** —para ejercitar Desarrollo, Holdout,
fuera de tiempo y la población through-the-door—. Se armó una muestra de 49.999 préstamos de la
base pública 7(a) de la SBA de EE. UU. (FY2000–FY2009, U.S. Government Works). La primera corrida
por la puerta guiada, con `date="fecha_aprobacion"` y `oot_from="2008-01-01"`, **muere** en «Tramos y
WoE»:

```text
WoE no defendible por bin con una clase en cero: variable='antiguedad_de_la_empresa',
valor observado={'Bin': 'Missing', 'Non-event': 4, 'Event': 0}.
```

Ocho préstamos de 49.999 no declaran la antigüedad de la empresa; cuatro caen en desarrollo y
ninguno es malo. El bin de **faltantes** queda sin una de las dos clases.

- **D-RAR no lo cubre**: reagrupa **categorías** raras, y un faltante no es una categoría que se
  pueda juntar con otra por el corte de raras.
- **Medido con OptBinning**: a ese bin le calcula **WoE 0 e IV 0** —el riesgo promedio de la
  cartera— y así lo transforma (`metric_missing="empirical"` y `0` dan lo mismo). El motor se
  detiene porque ese cero **no es una estimación**: es un artefacto de dividir por cero clases, y
  nadie lo declara. Detenerse es correcto hoy; lo que falta es una regla declarada.
- **Y la salida que el mensaje sugeriría no funciona por la puerta guiada**: `sc.exclude(...)`
  sobre esa variable **no evita la caída** —medido—, porque `exclude()` escribe sólo
  `selection.force_exclude` y la variable igual pasa por el binning. Su docstring promete otra
  cosa: «Descarta variables en toda la corrida siguiente». El mensaje de D-RAR, recién entregado,
  ofrece «Puedes excluir la variable», que por la puerta guiada tampoco se cumple.

Con los ocho vacíos escritos como la categoría que el propio dato ya trae («sin respuesta»), la
misma corrida termina en 16 s (AUC fuera de tiempo 0,795). El defecto es del motor, no del dato:
un banco real tiene faltantes así en cualquier variable.

## 1. D-FAL-1 — el WoE de un bin de faltantes o especiales sin una clase se asigna, no se estima

La unidad es el **par (variable, bin)**: por cada bin **`Missing`** o **`Special`** con
observaciones y **una clase en cero** en las filas ajustadas —una misma variable puede tener los
dos—, y sólo cuando su WoE es el empírico (`metric_missing` / `metric_special` = `"empirical"`, el
default):

1. **No se estima su WoE: se le asigna** con la regla de §5.1. La regla recomendada es la
   **conservadora**: el WoE del tramo regular con la **mayor tasa de malos observada** de esa misma
   variable —el de menor WoE; ante un empate, la **primera fila regular** con ese WoE, que es la
   que usa la búsqueda de puntos del escalador—. Un grupo sin evidencia de incumplimiento no recibe
   el WoE de menor riesgo por falta de datos. La promesa es sobre el **WoE**: el puntaje sigue la dirección que el
   modelo le dé a la variable, así que con el signo esperado el faltante recibe el puntaje más bajo
   de la variable, y si el modelo invierte el signo —que `sign_policy` ya marca— se invierte con
   toda la variable (revisión adversarial, pasada 1).
2. La tabla de binning publica ese WoE en la fila del bin, y el **IV de esa fila queda en 0** —que
   es lo que OptBinning ya le calcula—: el bin no aporta evidencia, así que no suma poder
   predictivo. El IV de la variable no cambia.
3. La transformación usa el mismo WoE para las filas de ese bin, en todas las muestras: tabla,
   transformación, puntos y bundle leen el mismo número.
4. **Alcance: sólo con el WoE empírico** (`metric_missing` / `metric_special` = `"empirical"`, el
   default). Con un valor numérico declarado el comportamiento **no cambia**. Medido en la pasada 1:
   hoy, con un valor declarado, la transformación usa ese valor pero la tabla —de la que salen los
   puntos— conserva el WoE empírico, así que ya existe una divergencia previa entre ambos; se
   registra como defecto aparte y no se toca aquí, porque corregirla cambiaría corridas que hoy
   terminan con un valor declarado.

### 1.1 Los puntos de un bin asignado

El escalador indexa los puntos por `(variable, WoE)` y, ante WoE repetidos, gana el primer bin y el
duplicado queda registrado —ya pasa hoy entre los bins vacíos `Special` y `Missing`, que tienen WoE
0—. Un bin asignado comparte a propósito el WoE de su tramo de referencia y, por tanto, **sus
puntos**: mismo riesgo, mismo puntaje. Una sola política, en las dos direcciones del ajuste
manual de puntos (`scorecard.point_overrides`):

- **Un override sobre el tramo de referencia se hereda**: la fila del bin asignado en la tabla de
  puntos lleva los mismos puntos ajustados, con su fuente declarada, y el bundle congela esa fila.
  Sin esto, las filas faltantes recibirían en la corrida los puntos ajustados —la búsqueda es por
  WoE y gana el tramo de referencia— mientras la tabla y el bundle conservaban los sin ajustar
  (revisión adversarial, pasada 2).
- **Un override sobre el bin asignado se rechaza**, con un mensaje que dice que ese bin comparte los
  puntos de su tramo de referencia y que el ajuste se hace sobre ese tramo.

Gate: corrida, tabla de puntos y bundle dan los mismos puntos a las filas del bin asignado, con y
sin override en el tramo de referencia.

**Qué no cambia:** un bin **regular** sin una clase sigue siendo asunto de D-RAR (categóricas) o de
la validación de siempre. Un bin de faltantes con las dos clases, por chico que sea, sigue con su
WoE empírico. Ninguna corrida que hoy termina cambia un número: la regla sólo entra donde hoy la
corrida muere.

## 2. D-FAL-2 — qué dicen las superficies

| Superficie | Qué dice |
|---|---|
| **Trail** | Una decisión por bin asignado: `regla="bin_sin_clase_asignado"`, `valor={variable, bin, operaciones, incumplidas}`, `umbral={regla, woe_asignado, tramo_de_referencia}`, `accion="asignar_woe"` |
| **Card de `binning`** | Campo aditivo `assigned_bins`: una entrada por par (variable, bin) —una variable puede tener dos—, con sus operaciones y malos, el WoE asignado y el tramo del que se tomó |
| **Resumen de «Tramos y WoE»** | Una línea por bin asignado, con el tipo de bin y la clase que falta —«Faltantes» o «Valores especiales»; «ninguna incumplida» o «todas incumplidas»—: «Faltantes de «antiguedad_de_la_empresa» (4 operaciones, ninguna incumplida): se les asignó el riesgo de su peor tramo» (revisión adversarial, pasada 2: un bin especial puede estar hecho sólo de malos) |
| **Informe** | Lo publica el Anexo de parámetros con la card; el cuerpo no gana sección |

Los conteos son **operaciones** de las filas ajustadas, sin pesos (misma regla que D-RAR tras su
pasada 2 de Codex).

## 3. D-EXC-1 — `exclude()` descarta en toda la corrida

`Scorecard.exclude(columns, reason=...)` escribe **`binning.exclude_columns`** y retira la
variable de `selection.force_exclude`/`force_include` y de `model.force_include`: la variable no se
tramifica, no aparece en las tablas de binning y no puede detener la corrida allí. **No** escribe
`selection.force_exclude`: la selección rechaza forzar una variable que el binning ya no publica, y
la corrida moriría en selección (revisión adversarial, pasada 1, verificado en
`selection/selector.py`). `binning.feature_columns` —la lista inferida— no se toca, para que
`exclude()`/`keep()` sigan reconociendo la variable. `keep()` sobre una variable excluida la retira
de `binning.exclude_columns` y la fuerza en selección y modelo, como hoy (la última decisión gana).

**Los tramos fijados de una variable excluida quedan en suspenso.** `set_bins()` y `merge_bins()`
escriben `binning.variable_overrides`, y el binning rechaza un override de una variable que no va a
tramificar: excluir después de fijar tramos volvería a detener la corrida (revisión adversarial,
pasada 2). El paso de binning ignora —y declara en el trail— los overrides de las variables que
están en `binning.exclude_columns`, en vez de rechazarlos; un override de una variable que **no**
existe sigue siendo un error. El override queda en el config, así que `keep()` lo reactiva sin
volver a escribirlo.

Consecuencia deliberada: una variable excluida deja de mostrar su IV en «Tramos y WoE». Es lo que
significa descartarla, y la decisión con su motivo sigue en el trail.

Con esto, la salida «Puedes excluir la variable» de los mensajes de D-RAR es ejecutable por la
puerta guiada; el mensaje nombra cómo: `exclude()` en la puerta guiada o `binning.exclude_columns`
en el config completo.

## 4. Estrategia de tests

| # | Test | Nace rojo porque |
|---|---|---|
| 1 | **Gate de aceptación**: el dataset SBA real —con sus faltantes— termina `done` por la puerta guiada con `date` y `oot_from` | Hoy muere en `binning` |
| 2 | Un fixture con un bin de faltantes sin malos: la tabla publica el WoE del peor tramo en esa fila, IV 0, y la transformación da ese mismo WoE a las filas faltantes | La regla no existe |
| 3 | Lo mismo para un bin `Special` sin malos | La regla no existe |
| 4 | Con `metric_missing` numérico declarado el comportamiento no cambia y no hay decisión | — (guardrail del alcance) |
| 5 | Una decisión `bin_sin_clase_asignado` por bin asignado, y ninguna sin bins degenerados | No se emite |
| 6 | La card publica `assigned_bins` y el resumen su línea, sin identificadores del motor | No existe |
| 7 | `exclude()` escribe `binning.exclude_columns` y no `selection.force_exclude`: una variable que hoy tumba el binning, excluida, deja terminar la corrida **en `done`** y no aparece en las tablas | Hoy muere igual |
| 8 | `keep()` después de `exclude()` la devuelve al binning y la corrida termina | — |
| 8a | `set_bins()` → `exclude()` termina `done`, con el override en suspenso declarado; y `keep()` después vuelve a tramificarla con esos mismos cortes | Hoy muere en binning |
| 8b | **Paridad de puntos**: las filas faltantes reciben los puntos de su tramo de referencia en la corrida, en la tabla de puntos y en el bundle, **también con un override en el tramo de referencia** | La regla no existe |
| 8d | El resumen dice el tipo de bin y la clase que falta: «Faltantes» / «Valores especiales», «ninguna incumplida» / «todas incumplidas» | La rama no existe |
| 8e | **Dos bins asignados en una variable** (`Missing` y `Special` a la vez): la corrida termina `done` y tabla, trail y card llevan las dos asignaciones | La regla no existe |
| 8f | **Empate de WoE mínimo** entre dos tramos regulares, con override en la referencia: la referencia es la primera fila, y corrida, tabla y bundle dan los mismos puntos | La regla no existe |
| 8c | Un `point_override` sobre un bin asignado se rechaza con su mensaje | No se valida |
| 9 | Bit a bit sobre el preset F1: la única diferencia es la clave aditiva vacía de la card | — (guardrail) |

**Controles negativos:** desactivar la regla (1, 2); asignar el WoE del mejor tramo en vez del peor
(2); no corregir la transformación (2, 8b); emitir la decisión sin bin degenerado (5); aplicar la
regla con un valor declarado (4); no escribir `binning.exclude_columns` (7); volver a escribir
`selection.force_exclude` (7); aceptar el override sobre un bin asignado (8c); no heredar el
override del tramo de referencia (8b); rechazar el override en suspenso (8a).

## 5. Lo que Cami decide

| # | Decisión | Opciones | Recomendación |
|---|---|---|---|
| 5.1 | Qué WoE se asigna a un bin de faltantes/especiales sin una clase | (a) **conservador**: el del tramo de mayor riesgo de la variable; (b) **neutral**: 0, el riesgo promedio de la cartera —lo que OptBinning ya calcula—; (c) detener la corrida con salidas (hoy, pero mejor explicado) | **(a)**: ante una deficiencia de datos, las guías de estimación de PD piden margen de conservadurismo; un grupo sin evidencia de incumplimiento no debe llevarse el mejor puntaje. (b) es defendible y más simple, pero premia la falta de datos en grupos sin malos. (c) deja al modelador sin salida en la pantalla |
| 5.2 | Qué hace `exclude()` | (a) **descartar en toda la corrida**, binning incluido; (b) sólo selección, como hoy | **(a)**: es lo que su contrato promete y lo que el modelador entiende por excluir; con (b) la salida de los mensajes de error no se puede ejecutar |

## 6. La revisión adversarial de este documento

Tope declarado: tres pasadas.

| Pasada | Hallazgo | Qué cambió |
|---|---|---|
| 1 | (a) **alto**: escribir `binning.exclude_columns` **y** `selection.force_exclude` hace morir la corrida en selección, que rechaza forzar una variable no binificada; (b) **alto**: con un WoE declarado, la transformación y la tabla —de donde salen los puntos— ya divergen hoy, y «rige ese valor» no lo resolvía; (c) **alto**: los puntos se indexan por `(variable, WoE)` y un bin asignado comparte clave con su tramo de referencia, así que un override por bin sería ambiguo; (d) **medio**: «peor tramo» no garantiza el peor puntaje si el modelo invierte el signo | (a) §3: `exclude()` escribe sólo `binning.exclude_columns` y retira la variable de las listas de selección y modelo; (b) §1, punto 4: la regla entra sólo con WoE empírico, el comportamiento con valor declarado no cambia y la divergencia previa se registra aparte; (c) §1.1: el bin asignado comparte a propósito los puntos de su tramo, y un override sobre él se rechaza; (d) §1, punto 1: la promesa se acota al WoE y a la dirección que el modelo dé a la variable |
| 2 | (a) **alto**: un override sobre el **tramo de referencia** llegaba a las filas faltantes por la búsqueda por WoE, pero no a la fila `Missing` de la tabla, que es la que congela el bundle: corrida y bundle puntuaban distinto; (b) **alto**: `exclude()` tras `set_bins()` o `merge_bins()` dejaba un override de una variable no tramificada, que el binning rechaza; (c) **medio**: la frase del resumen suponía «sin incumplimientos», y un bin especial puede estar hecho sólo de malos | (a) §1.1: el bin asignado **hereda** los puntos ajustados de su tramo de referencia, con fuente declarada, y el gate de paridad cubre ese caso; (b) §3: los overrides de una variable excluida quedan en suspenso, declarados, y `keep()` los reactiva; (c) §2: el texto dice el tipo de bin y la clase que falta |
| 3 | (a) **alto**: la regla se decía «por variable» mientras el trail va por bin; con `Missing` y `Special` degenerados a la vez, uno quedaría sin tratar y la corrida moriría, o la card perdería una asignación; (b) **alto**: «peor tramo» no desempataba dos tramos con el mismo WoE mínimo; si la referencia fuera el segundo y se ajustaran sus puntos, la corrida usaría los del primero y el bundle los heredados | (a) §1 y §2: la unidad es el par (variable, bin) y la card admite dos entradas por variable, con su gate; (b) §1: ante un empate, la referencia es la primera fila regular, que es la que usa el escalador, con su gate |

**Tope alcanzado.** Las dos primeras pasadas tumbaron premisas —la exclusión moría en selección; los puntos del bin asignado podían divergir entre corrida y bundle— y la tercera ya sólo afinó bordes. Es el criterio de parada declarado; la implementación abre con su propia pasada.

## 7. Implementación (2026-09-23): lo que el código precisó

Implementada el mismo día de su aprobación. Diecisiete tests nuevos con OptBinning real
(`tests/unit/test_binning_faltantes_sin_clase.py`): contra el código anterior, dieciséis rojos y
uno verde —el test 4, que es el guardrail del alcance y debe serlo—. Once controles negativos, uno
por cada defecto que §4 promete detectar más el desempate, rojos con el defecto y verdes tras
restaurar byte a byte.

1. **La referencia, en el escalador, se ubica por WoE, no por etiqueta.** La card dice qué bins se
   asignaron (`assigned_bins`: variable y bin); el escalador toma como referencia la **primera
   fila de la variable con el mismo WoE**, que es exactamente la que gana la búsqueda de puntos.
   Así no depende de cómo se escribe la etiqueta de un tramo categórico, que en la card queda como
   el texto del arreglo de niveles. La herencia de un override se declara en el trail
   (`point_override_heredado`).
2. **La regla no entra si un tramo regular también quedó sin una clase**: ese caso lo resuelve
   D-RAR o lo dice la validación de siempre, y asignar primero dejaría en el trail una decisión
   de una corrida que igual se detiene.
3. **La transformación usa la misma llamada que `BinningProcess` hace por variable**, con el WoE
   asignado como valor numérico de ese bin: es la vía pública de OptBinning, no un parche sobre
   su salida.
4. **`exclude()` retira la variable de las cuatro listas forzadas** —también de
   `model.force_exclude`, que un config completo puede traer—: el modelo rechaza un override sobre
   una variable que no le llega.
5. **El cuaderno publicado `primer-scorecard.ipynb` se regeneró.** Excluye `mora_max_12m`; con
   D-EXC-1 esa variable ya no aparece en «Tramos y WoE» ni en la selección —6 → 5 variables
   tramificadas, y desaparece su aviso de tendencia invertida—. Las cifras del modelo no cambian
   (AUC fuera de tiempo 0,648, la misma validación). Su gate lo exigía: compara cada salida
   guardada con la de hoy.
6. **Los mensajes de D-RAR nombran cómo excluir**: «`exclude()` en la puerta guiada o
   `binning.exclude_columns` en el config completo».

**Medido.** El dataset SBA crudo, con sus faltantes, termina `done` por la puerta guiada con
`date="fecha_aprobacion"` y `oot_from="2008-01-01"` en 20,7 s, con el mismo `config_hash`
(`a27e678f…`) y AUC fuera de tiempo 0,795; el resumen dice «Faltantes de
«antiguedad_de_la_empresa» (4 operaciones, ninguna incumplida): se les asignó el riesgo de su peor
tramo». Bit a bit sobre el preset F1: una diferencia, la clave aditiva
`binning_card.assigned_bins = ()`; `config_hash` `1063d6cf…` intacto. Paridad de puntos entre
corrida y bundle en las filas faltantes: diferencia máxima 0,0, con y sin override en la
referencia.

## 13. Simplicidad (SDD-31) — obligatoria

- **Entrada mínima:** no cambia.
- **Qué NO se configura:** la regla de asignación. Quien quiera otro valor ya tiene
  `metric_missing` / `metric_special` numéricos, que la regla respeta.
- **Presupuesto de perillas: CERO.** Los campos nuevos son de resultado (`assigned_bins`).
- **Resumen por etapa:** el de tramos gana una línea condicional.
- **Las cinco cifras:** idénticas en toda corrida que hoy termina.
