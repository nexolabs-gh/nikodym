# Enmienda — una categoría rara con una clase en cero no puede matar la corrida

| Campo | Valor |
|---|---|
| **Tipo** | Enmienda corta a [`06-binning.md`](06-binning.md) (§8, manejo de errores) y a [`31-simplicidad-y-flujo-guiado.md`](31-simplicidad-y-flujo-guiado.md) (§8, casos borde) |
| **Decisiones** | **D-RAR-1** (el motor reagrupa el nivel degenerado y lo declara) y **D-RAR-2** (qué dice, dónde y con qué palabras) |
| **Módulos** | `nikodym.binning` (`transformer`, `step`), `nikodym.guided.summaries` (el resumen de la etapa) |
| **Fase** | F1 |
| **Estado** | **Propuesta** — pendiente del OK de Cami |
| **Depende de** | D-SC-2 y D-SC-17 (el precedente: un error fatal pasa a ser una degradación declarada), D-SIM-1/2, D-FLU-1/2 |
| **Lo consumen** | la puerta guiada, el config completo y la pantalla: las tres, porque la regla vive en el motor |
| **Release** | Aditiva para todo lo que hoy corre: la regla **sólo** entra donde la corrida iba a fallar. Ningún `config_hash` se mueve ⇒ **minor** |
| **Autor / Fecha** | Claude Code (writer) / 2026-09-22 |

---

## 0. Por qué existe: el defecto medido

Tras la corrección de D-SC-17, **UCI German Credit** —el tercer dataset del criterio de completado
del scorecard, externo y sin columna de fecha— pasa el análisis exploratorio y muere una etapa
después:

```text
Ejecución: fallida en «Tramos y WoE»: WoE no defendible por bin con una clase en cero:
variable='proposito', valor observado={'Bin': array(['A48'], dtype=object), 'Non-event': 5, 'Event': 0}.
```

El motor tiene razón en detenerse: un bin con cero malos no tiene WoE defendible
(`binning/transformer.py:1152-1157`). El problema es **cómo se llegó a ese bin**.

### 0.1 El mecanismo exacto, medido con OptBinning real

`proposito` tiene diez niveles. Sobre el archivo entero:

| Nivel | Filas | Frecuencia | Malos |
|---|---:|---:|---:|
| **A48** | **9** | **0,9 %** | **1** |
| A44 | 12 | 1,2 % | 4 |
| A410 | 12 | 1,2 % | 5 |
| A45 | 22 | 2,2 % | 8 |
| … | … | … | … |

El default del motor es `binning.cat_cutoff = 0.01`: los niveles por **debajo** del 1 % se agrupan
antes de optimizar. Y aquí está la trampa, medida barriendo el valor sobre los mismos datos:

| `cat_cutoff` | Dónde cae A48 | Bins con una clase en cero |
|---|---|---|
| `None` | junto a A41 | ninguno |
| 0,005 | junto a A41 | ninguno |
| **0,01 (el default)** | **A48 solo** | ninguno *sobre el archivo* |
| 0,02 | con A44 y A410 | ninguno |
| 0,05 | con A45, A44 y A410 | ninguno |

**A48 es el único nivel bajo el 1 %**, así que el grupo de «categorías raras» que arma el corte
tiene **un solo miembro**: el agrupamiento que debía protegerlo lo deja igual de solo. Sobre el
archivo entero eso todavía no rompe nada (A48 tiene 1 malo de 9). Rompe al partir: el único malo
cae en Holdout y en **Desarrollo** —802 filas, la población con la que se ajusta— A48 queda con
**5 buenos y 0 malos**.

La regla general, que no es de este dataset: **un corte de rareza que aísla exactamente un nivel
crea un bin unitario, y un bin unitario es el candidato natural a tener una clase en cero.** El
default no es «demasiado bajo»: es que **cualquier** valor fijo puede caer justo encima de un solo
nivel, y no hay constante que lo evite en todos los archivos.

### 0.2 Por qué el modelador de referencia no puede salir de esto

Medido: `Scorecard(...)` expone `max_bins` y `min_bin_size`, y **no** expone `cat_cutoff`
(`guided/scorecard.py:179-180`, `:494-495`). El usuario de la puerta guiada —el modelador del banco
chico que no necesariamente sabe Python— **no tiene ninguna palanca**: tendría que bajar al
`NikodymConfig` completo, encontrar una perilla llamada «umbral de categorías raras» y adivinar un
valor. Es exactamente el muro que SDD-31 vino a quitar.

Y es un caso ordinario, no un borde raro: cualquier cartera real tiene un producto, una sucursal o
una campaña con pocas operaciones, y basta con que sus incumplimientos caigan del otro lado de la
partición.

### 0.3 🔴 Por qué la regla NO puede vivir en la puerta guiada

La primera redacción de esta enmienda ponía la corrección en `nikodym.Scorecard`: contar las clases
por nivel en desarrollo al construir el config y escribir un `cat_cutoff` override por variable.
**La revisión adversarial la tumbó, y con razón** (verificado contra el árbol):

`_resolver_muestras` (`guided/scorecard.py:731`) resuelve **la estrategia**, no la pertenencia. Qué
fila cae en desarrollo lo decide `DataStep` mucho después, con `Partitioner.split` y la semilla del
`Study`, y **después** de aplicar el esquema, los valores especiales, las reglas del target y la
exclusión de indeterminados. Contar «en desarrollo» desde la puerta exigiría **duplicar ese
pipeline** —lo que RUNBOOK §12.2-5 prohíbe— o contar sobre otra población: con partición aleatoria,
un target por regla o filas indeterminadas, el override se basaría en filas distintas de las que
luego ajustan el binning, y podría conservar el bin degenerado, alterar una corrida que hoy termina
o registrar conteos falsos en el trail.

**Quien sí tiene la población correcta es el motor.** `BinningStep.requires` incluye
`("data", "splits")` además de `("data", "frame")` y `("data", "labels")`
(`binning/step.py:84-89`): recibe exactamente las filas que va a ajustar. La regla vive ahí. Y de
paso deja de ser un arreglo de una sola puerta: sirve igual a quien llega por YAML o por pantalla,
que es la mitad de los usuarios de referencia.

## 1. Alcance: qué cambia y qué no

- **Cambia el manejo de errores de `binning`, y se declara.** Hoy un bin con una clase en cero
  detiene la corrida siempre. Pasa a detenerla **sólo si el motor no pudo evitarlo**, con un
  reintento acotado (§2) declarado en el trail. Es el mismo patrón que Cami ya aprobó dos veces
  —D-SC-2 y D-SC-17—: un error fatal que se convierte en una degradación **declarada**, nunca en
  un silencio.
- **No se inventa ningún WoE.** La regla **reagrupa** para que el WoE exista; si aun así no
  existe, el motor se detiene con su mensaje de siempre. Publicar un WoE para un bin sin una de
  las dos clases sería fabricar evidencia, y eso no entra.
- **El default `cat_cutoff = 0.01` no se toca.** Cambiarlo movería el `config_hash` de los presets
  F1 y F5, cambiaría resultados de corridas que hoy terminan con el mismo config —ruptura de la
  garantía 1.x— y obligaría a recapturar la demo. §6.3 lo eleva para un 2.0.
- **No se añade ninguna perilla.** `cat_cutoff` ya existe, global y por variable; la regla es un
  reintento interno, no un campo.
- **No se descarta ninguna variable ni ninguna fila.** Agrupar dos niveles raros conserva toda la
  información; descartar la variable la perdería, y eso es decisión de la persona (D-FLU).
- **Ninguna corrida que hoy termina cambia un número.** La regla se activa **después** de que el
  ajuste produjo un bin degenerado, que es exactamente el estado en el que hoy no hay resultado.

## 2. D-RAR-1 — el motor reagrupa, una vez, y lo declara

En `WoEBinner`, por cada columna **categórica** cuyo ajuste produce un bin con una clase en cero:

1. Se identifica el o los niveles del bin degenerado y sus conteos, **sobre las filas que el paso
   está ajustando** —las de desarrollo, que es lo que `binning` recibe—. Nada se recalcula ni se
   reparticiona: son los conteos de la propia tabla de binning.
2. Se calcula el menor `cat_cutoff` que deja **al menos dos** niveles por debajo del corte, de modo
   que el grupo de raras deje de ser unitario, y **se reajusta esa columna una sola vez** con ese
   valor. Un solo reintento: si el segundo ajuste vuelve a dar un bin degenerado, el motor se
   detiene con el error de hoy.
3. La decisión va al trail, y la columna queda ajustada con el corte efectivo, que el config final
   y el Anexo de parámetros reproducen como cualquier otra hoja.
4. Si ninguna columna produce un bin degenerado, **no pasa nada**: ni reintento, ni decisión, ni
   una línea de más.

**Por qué un solo reintento y no una búsqueda.** Subir el corte hasta que «funcione» podría acabar
metiendo en un mismo bin media variable, que es un cambio de modelación tomado por la máquina. Un
intento acotado resuelve el caso medido —un nivel aislado por el corte— y deja el resto donde
corresponde: en la persona, que ve en el resumen qué pasó y puede excluir la variable o fijar sus
tramos.

**Qué NO promete.** No garantiza que el segundo ajuste tenga las dos clases: puede que ni juntando
los dos niveles más raros aparezca un malo. Cuando eso ocurra el motor se detendrá —que es lo
correcto—, pero el resumen dirá qué categoría es, qué se intentó y qué salidas hay (§3), en vez de
dejar al modelador con el nombre de un bin y ningún camino.

## 3. D-RAR-2 — qué se dice y dónde

- **Trail.** Una decisión por columna reagrupada: regla `categoria_rara_reagrupada`, el nivel
  degenerado con sus conteos, el corte de partida y el corte efectivo, acción `reagrupar`.
- **Resumen de «Tramos y WoE»** (`guided/summaries.py`), una línea cuando la regla entra:

  > Categorías con muy pocas operaciones agrupadas para poder calcular su WoE: «proposito» (nivel
  > A48: 5 operaciones, ninguna incumplida).

- **Resumen de «Tramos y WoE» cuando el motor se detiene igual**: la alerta nombra la variable y el
  nivel, dice que se intentó agruparlo y ofrece las dos salidas —excluir la variable con
  `exclude(...)` o fijar sus tramos—. Hoy el mensaje es el del motor y no ofrece ninguna.
- **Ficha e informe: nada nuevo.** El corte efectivo viaja en el config y en el Anexo de
  parámetros, como cualquier hoja. No se inventa una sección.

## 4. Estrategia de tests

Todos nacen rojos salvo los marcados como guardrail.

| # | Test | Nace rojo porque |
|---|---|---|
| 1 | **Gate de aceptación**: `Scorecard(german_credit, target=…, partition="random").run()` termina `done`, **con sus 13 categóricas intactas** | Hoy muere en `binning` |
| 2 | Un fixture mínimo con un nivel degenerado reproduce el bin unitario, y tras la regla la tabla de esa variable no tiene ninguna clase en cero | La regla no existe |
| 3 | Con un archivo sin niveles degenerados, la corrida es **byte a byte** la de hoy y no hay decisión en el trail | — (guardrail de «sólo si hace falta») |
| 4 | El corte efectivo deja **≥ 2** niveles bajo él (los dos sentidos: uno menos y el grupo vuelve a ser unitario) | La regla no existe |
| 5 | Los conteos de la decisión son los de la tabla de binning del paso, **no** los del archivo: un nivel sano en el archivo y degenerado en la muestra ajustada dispara la regla | La regla no existe |
| 6 | **Un solo reintento**: con un fixture donde ni el segundo ajuste resuelve, el motor levanta el `BinningFitError` de siempre y el trail registra el intento | La regla no existe |
| 7 | La decisión `categoria_rara_reagrupada` está en el trail con sus conteos, una vez por columna | No se emite |
| 8 | El resumen publica su línea —y su alerta en el caso 6—, en español y sin identificadores del motor | La rama no existe |
| 9 | **Bit a bit**: la proyección canónica de una corrida F1 del preset antes y después, **cero diferencias**, `config_hash` `1063d6cf…` intacto | — (guardrail) |

**Controles negativos (§6):** (a) desactivar la regla y ver rojo el test 1; (b) tomar los conteos
del archivo en vez de la tabla del paso y ver rojo el 5; (c) reintentar en bucle en vez de una vez
y ver rojo el 6; (d) elegir un corte que deje un solo nivel debajo y ver rojo el 4; (e) emitir la
decisión también cuando no hace falta y ver rojo el 3.

## 5. Riesgos

1. **Que la regla cambie resultados de corridas que hoy funcionan.** Cerrado por construcción: se
   activa después de un ajuste que produjo un bin degenerado, que es el estado en el que hoy no hay
   resultado. El test 3 y su control negativo (e) lo vigilan.
2. **Que el reintento empeore el binning de esa variable.** Junta los dos niveles más raros y
   reajusta esa columna sola; el resto del binning no se toca. El IV queda en la tabla de la etapa
   y el modelador puede excluir la variable.
3. **Que se lea como que el motor ya no falla nunca.** No: §2 declara lo que la regla no promete y
   §3 da el copy del caso en que se detiene igual.
4. **Que el reintento esconda un problema de datos real.** Por eso se declara en el trail y se dice
   en el resumen: un nivel sin un solo incumplimiento es información sobre la cartera, no ruido.

## 6. Lo que Cami decide

| # | Decisión | Opciones | Recomendación |
|---|---|---|---|
| 6.1 | Dónde vive el arreglo | (a) **el motor reagrupa y lo declara** (esta enmienda); (b) la puerta guiada escribe un override al construir el config; (c) exponer `cat_cutoff` como campo esencial; (d) subir el default del motor | **(a)**: es el único sitio que tiene la población real —§0.3 mide que la puerta **no** la conoce hasta que `DataStep` corre—, y además sirve a las tres puertas. (b) exigiría duplicar el pipeline de `data`; (c) pone al modelador a decidir sobre un umbral que no debería tener que conocer; (d) rompe la garantía 1.x y obliga a recapturar |
| 6.2 | Cuántos reintentos | (a) **uno**; (b) subir el corte hasta que funcione | **(a)**: una búsqueda podría acabar metiendo media variable en un bin, que es una decisión de modelación tomada por la máquina |
| 6.3 | Si el default `cat_cutoff = 0.01` se revisa para 2.0 | (a) **sí, se anota como candidato con esta medición**; (b) se deja como está | **(a)**: §0.1 muestra que un corte fijo puede aislar un nivel en cualquier archivo; es material para la poda de D-SIM-12, no para 1.x |

## 7. La revisión adversarial de este documento

**Tope declarado: tres pasadas.** La primera tumbó la premisa central de la primera redacción —que
la puerta guiada puede contar sobre desarrollo antes de que `DataStep` particione— y con ella el
sitio donde vivía la regla; §0.3 recoge la medición y §6.1 la convierte en la decisión de Cami. Las
pasadas restantes van sobre esta redacción.

## 13. Simplicidad (SDD-31) — obligatoria

- **Entrada mínima:** no cambia. Nada nuevo que declarar.
- **Qué NO se configura:** el reintento. No hay un flag «permitir reagrupar»: sin reagrupar no hay
  WoE, y la alternativa es que la corrida muera. Preguntarlo sería pedirle al modelador una
  decisión que sólo tiene una respuesta razonable.
- **Campos esenciales:** sin cambios; `binning` no gana ninguno.
- **Presupuesto de perillas: CERO.** `cat_cutoff` global y por variable ya existen y siguen
  contando igual; las perillas de las doce secciones del scorecard siguen en **413**.
- **Resumen por etapa:** el de tramos gana **una** línea condicional y **una** alerta condicional.
  Ninguna aparece cuando la regla no entra.
- **Notebook mínimo:** sin cambios (15 líneas, 5 conceptos).
- **Las cinco cifras:** idénticas. Lo que cambia no es una cifra: es que un archivo externo real
  llega hasta el final.
