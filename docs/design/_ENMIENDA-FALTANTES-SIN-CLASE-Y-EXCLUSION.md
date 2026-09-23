# Enmienda — un bin de faltantes sin una clase no mata la corrida, y excluir excluye de verdad

| Campo | Valor |
|---|---|
| **Tipo** | Enmienda corta a [`06-binning.md`](06-binning.md) (§8, manejo de errores), a [`_ENMIENDA-CATEGORIA-RARA-SIN-CLASE.md`](_ENMIENDA-CATEGORIA-RARA-SIN-CLASE.md) (la extiende a los bins de faltantes y especiales) y a [`_ENMIENDA-FLUJO-GUIADO-SCORECARD.md`](_ENMIENDA-FLUJO-GUIADO-SCORECARD.md) (el contrato de `exclude`) |
| **Decisiones** | **D-FAL-1** (el WoE de un bin de faltantes o especiales sin una clase se **asigna** con una regla declarada), **D-FAL-2** (qué dicen las superficies) y **D-EXC-1** (`exclude()` descarta en toda la corrida, binning incluido) |
| **Módulos** | `nikodym.binning` (`transformer`, `results`, `step`), `nikodym.guided` (`scorecard`, `summaries`) |
| **Fase** | F1 |
| **Estado** | **PROPUESTA** — Cami pidió enmienda y código hoy (2026-09-23), con la regla que el writer recomiende pensando en auditorías |
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

Por cada variable cuyo bin **`Missing`** o **`Special`** tiene observaciones y **una clase en cero**
en las filas ajustadas, y sólo cuando su WoE es el empírico (`metric_missing` / `metric_special` =
`"empirical"`, el default):

1. **No se estima su WoE: se le asigna** con la regla de §5.1. La regla recomendada es la
   **conservadora**: el WoE del tramo regular de **mayor riesgo** de esa misma variable. Un grupo
   sin evidencia de incumplimiento no recibe el mejor puntaje por falta de datos.
2. La tabla de binning publica ese WoE en la fila del bin, y el **IV de esa fila queda en 0**: el
   bin no aporta evidencia, así que no suma poder predictivo. El IV de la variable no cambia.
3. La transformación usa el mismo WoE para las filas de ese bin, en todas las muestras (tabla y
   puntaje nunca discrepan).
4. Si el usuario **declaró** un valor numérico en `metric_missing` / `metric_special`, rige ese
   valor y la regla no entra: el bin ya no depende de lo observado.

**Qué no cambia:** un bin **regular** sin una clase sigue siendo asunto de D-RAR (categóricas) o de
la validación de siempre. Un bin de faltantes con las dos clases, por chico que sea, sigue con su
WoE empírico. Ninguna corrida que hoy termina cambia un número: la regla sólo entra donde hoy la
corrida muere.

## 2. D-FAL-2 — qué dicen las superficies

| Superficie | Qué dice |
|---|---|
| **Trail** | Una decisión por bin asignado: `regla="bin_sin_clase_asignado"`, `valor={variable, bin, operaciones, incumplidas}`, `umbral={regla, woe_asignado, tramo_de_referencia}`, `accion="asignar_woe"` |
| **Card de `binning`** | Campo aditivo `assigned_bins`: por variable, el bin, sus operaciones y malos, el WoE asignado y el tramo del que se tomó |
| **Resumen de «Tramos y WoE»** | Una línea: «Faltantes sin incumplimientos a los que se asignó el riesgo del peor tramo: «antiguedad_de_la_empresa» (4 operaciones, ninguna incumplida)» |
| **Informe** | Lo publica el Anexo de parámetros con la card; el cuerpo no gana sección |

Los conteos son **operaciones** de las filas ajustadas, sin pesos (misma regla que D-RAR tras su
pasada 2 de Codex).

## 3. D-EXC-1 — `exclude()` descarta en toda la corrida

`Scorecard.exclude(columns, reason=...)` escribe, además de `selection.force_exclude`,
**`binning.exclude_columns`**: la variable no se tramifica, no aparece en las tablas de binning y
no puede detener la corrida allí. `binning.feature_columns` —la lista inferida— no se toca, para que
`exclude()`/`keep()` sigan reconociendo la variable. `keep()` sobre una variable excluida la retira
de las dos listas (la última decisión gana, como hoy).

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
| 4 | Con `metric_missing` numérico declarado, rige ese valor y no hay decisión | Hoy muere igual |
| 5 | Una decisión `bin_sin_clase_asignado` por bin asignado, y ninguna sin bins degenerados | No se emite |
| 6 | La card publica `assigned_bins` y el resumen su línea, sin identificadores del motor | No existe |
| 7 | `exclude()` escribe `binning.exclude_columns`: una variable que hoy tumba el binning, excluida, deja terminar la corrida y no aparece en las tablas | Hoy muere igual |
| 8 | `keep()` después de `exclude()` la devuelve al binning | — |
| 9 | Bit a bit sobre el preset F1: la única diferencia es la clave aditiva vacía de la card | — (guardrail) |

**Controles negativos:** desactivar la regla (1, 2); asignar el WoE del mejor tramo en vez del peor
(2); no corregir la transformación (2); emitir la decisión sin bin degenerado (5); ignorar el valor
declarado (4); no escribir `binning.exclude_columns` (7).

## 5. Lo que Cami decide

| # | Decisión | Opciones | Recomendación |
|---|---|---|---|
| 5.1 | Qué WoE se asigna a un bin de faltantes/especiales sin una clase | (a) **conservador**: el del tramo de mayor riesgo de la variable; (b) **neutral**: 0, el riesgo promedio de la cartera —lo que OptBinning ya calcula—; (c) detener la corrida con salidas (hoy, pero mejor explicado) | **(a)**: ante una deficiencia de datos, las guías de estimación de PD piden margen de conservadurismo; un grupo sin evidencia de incumplimiento no debe llevarse el mejor puntaje. (b) es defendible y más simple, pero premia la falta de datos en grupos sin malos. (c) deja al modelador sin salida en la pantalla |
| 5.2 | Qué hace `exclude()` | (a) **descartar en toda la corrida**, binning incluido; (b) sólo selección, como hoy | **(a)**: es lo que su contrato promete y lo que el modelador entiende por excluir; con (b) la salida de los mensajes de error no se puede ejecutar |

## 6. La revisión adversarial de este documento

Tope declarado: tres pasadas.

## 13. Simplicidad (SDD-31) — obligatoria

- **Entrada mínima:** no cambia.
- **Qué NO se configura:** la regla de asignación. Quien quiera otro valor ya tiene
  `metric_missing` / `metric_special` numéricos, que la regla respeta.
- **Presupuesto de perillas: CERO.** Los campos nuevos son de resultado (`assigned_bins`).
- **Resumen por etapa:** el de tramos gana una línea condicional.
- **Las cinco cifras:** idénticas en toda corrida que hoy termina.
