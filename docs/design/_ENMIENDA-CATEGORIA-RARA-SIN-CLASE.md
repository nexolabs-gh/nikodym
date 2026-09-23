# Enmienda — una categoría rara con una clase en cero no puede matar la corrida

| Campo | Valor |
|---|---|
| **Tipo** | Enmienda corta a [`06-binning.md`](06-binning.md) (§8, manejo de errores) y a [`31-simplicidad-y-flujo-guiado.md`](31-simplicidad-y-flujo-guiado.md) (§8, casos borde) |
| **Decisiones** | **D-RAR-1** (el motor reagrupa el nivel degenerado y lo declara) y **D-RAR-2** (qué dice, dónde y con qué palabras) |
| **Módulos** | `nikodym.binning` (`transformer`, `step`), `nikodym.guided.summaries` (el resumen de la etapa) |
| **Fase** | F1 |
| **Estado** | **APROBADA por Cami el 2026-09-22** (interactivo), con la recomendación de las cinco decisiones de su §6. **Implementada el 2026-09-23**; lo que el código midió distinto de lo escrito, en §8 |
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
3. La decisión va al trail **antes** de que el paso publique nada, y el **corte efectivo se
   publica como resultado**, no como config (§2.1).
4. Si ninguna columna produce un bin degenerado, **no pasa nada**: ni reintento, ni decisión, ni
   una línea de más.

### 2.1 🔴 El corte efectivo es un RESULTADO, no una hoja del config

La primera redacción decía que «el config final reproduce el corte efectivo como cualquier otra
hoja». **No puede ser**, y la revisión adversarial lo midió: el `config_hash` se calcula sobre el
config —`binning` incluido—, el `Study` congela el lineage **antes** de ejecutar el paso y `save()`
escribe `study.config`. Escribir el corte ahí después del ajuste rompería la correspondencia con el
hash; no escribirlo dejaría un config guardado que no reproduce lo que se hizo. La salida no es
elegir entre las dos:

- **El corte efectivo viaja en la card de `binning`**, por variable, junto al declarado, como
  cualquier otra cifra que el motor calcula. El Anexo de parámetros lo publica **distinguiéndolo**
  del declarado: «umbral de categorías raras declarado 0,01 · efectivo 0,02 (reagrupado por el
  motor)».
- **La reproducibilidad no depende de guardar el valor, sino de que la regla sea determinista**:
  el mismo config sobre los mismos datos vuelve a producir el mismo bin degenerado, el mismo corte
  y el mismo ajuste. El `config_hash` sigue identificando **lo que el usuario declaró**, que es lo
  que identifica por contrato; el corte efectivo es evidencia de la corrida, como el IV o los
  coeficientes.
- **Gate:** guardar la corrida, recargarla y reejecutar el mismo config tiene que dar el mismo
  corte efectivo y el mismo binning, con el `config_hash` intacto.

### 2.2 🔴 Cuando el segundo ajuste falla, quien habla es el ERROR, no el resumen

La primera redacción prometía una alerta en el resumen de «Tramos y WoE». **Tampoco puede ser**, y
también está medido: `BinningStep.execute` llama a `binner.fit` **antes** de publicar artefactos, el
`Study` invoca `on_step` sólo cuando `execute` **termina**, y ahí es donde la puerta guiada arma el
resumen de la etapa. Si el segundo ajuste levanta `BinningFitError`, ese resumen no llega a
existir nunca.

Por eso, en la ruta de fallo:

- **El intento y el éxito son DOS eventos distintos**, y esto importa más de lo que parece: la
  ficha del modelo materializa las decisiones del trail tal cual, así que un único evento
  `categoria_rara_reagrupada` emitido **antes** del segundo ajuste dejaría, en una corrida
  fallida, una ficha que afirma una reagrupación que nunca se completó. Por eso el paso emite
  `categoria_rara_intento_reagrupar` **antes** de reintentar —acción `intentar`, con el nivel, sus
  conteos y el corte que va a probar— y `categoria_rara_reagrupada` **sólo después de un ajuste
  exitoso**. El sumidero está disponible dentro del paso, así que el intento queda registrado
  aunque `execute` no termine.
- **El diagnóstico que lee la persona es el mensaje del propio error**, que es la superficie que sí
  existe en esa ruta: la puerta guiada ya lo publica tal cual («Ejecución: fallida en “Tramos y
  WoE”: …»), y lo mismo hacen la pantalla y el YAML. El mensaje pasa a nombrar la variable, el
  nivel y sus conteos, decir que se intentó reagruparlo y con qué corte, y ofrecer las dos salidas.
- El resumen de la etapa sólo habla en el camino **exitoso** (§3).

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

- **Cuando el motor se detiene igual**, el que habla es el **mensaje del error** (§2.2), porque el
  resumen de la etapa no llega a construirse:

  > WoE no defendible por bin con una clase en cero: variable «proposito», nivel «A48» con 5
  > operaciones y ninguna incumplida. Se reagrupó con las categorías más raras (umbral 0,01 →
  > 0,02) y el bin sigue sin incumplimientos. Puedes excluir la variable, o subir el umbral de
  > categorías raras de esa variable en el config completo (`binning.variable_overrides`).

  Hoy nombra el bin y no ofrece ninguna salida.

  ⚠️ **Las dos salidas tienen que ser ejecutables para una categórica, y eso hubo que medirlo**:
  `set_bins` escribe `user_splits`, y `WoEBinner` **rechaza expresamente `user_splits` en columnas
  categóricas** (`transformer.py:799-808`: «los cortes fijados sólo aplican a variables
  numéricas»), así que ofrecer «fija sus tramos» —como decía la redacción anterior— habría mandado
  al modelador contra otro `BinningFitError`. Una vía de agrupación **manual** de categorías no
  existe hoy y no se inventa aquí: si hace falta, es su propia enmienda (§6.5).
- **Ficha e informe: nada nuevo.** El corte efectivo viaja en la **card de `binning`** y el Anexo
  de parámetros lo publica junto al declarado (§2.1). No se inventa una sección.

## 4. Estrategia de tests

Todos nacen rojos salvo los marcados como guardrail.

| # | Test | Nace rojo porque |
|---|---|---|
| 1 | **Gate de aceptación**: `Scorecard(german_credit, target=…, partition="random").run()` termina `done`, **con sus 13 categóricas intactas** | Hoy muere en `binning` |
| 2 | Un fixture mínimo con un nivel degenerado reproduce el bin unitario, y tras la regla la tabla de esa variable no tiene ninguna clase en cero | La regla no existe |
| 3 | Con un archivo sin niveles degenerados, la corrida es **byte a byte** la de hoy y no hay decisión en el trail | — (guardrail de «sólo si hace falta») |
| 4 | El corte efectivo deja **≥ 2** niveles bajo él (los dos sentidos: uno menos y el grupo vuelve a ser unitario) | La regla no existe |
| 5 | Los conteos de la decisión son los de la tabla de binning del paso, **no** los del archivo: un nivel sano en el archivo y degenerado en la muestra ajustada dispara la regla | La regla no existe |
| 6 | **Un solo reintento**: con un fixture donde ni el segundo ajuste resuelve, el motor levanta `BinningFitError`, **el trail ya registró el intento** —se emite antes de propagar— y el mensaje nombra variable, nivel, conteos, cortes y las dos salidas | La regla no existe, y hoy el trail no vería nada |
| 6b | **El corte efectivo es resultado, no config**: la card de `binning` lo publica por variable, el `config_hash` no se mueve, y guardar → recargar → reejecutar el mismo config da el mismo corte y el mismo binning | La card no lo publica |
| 7 | **Intento y éxito son dos eventos**: tras un reintento exitoso el trail lleva `categoria_rara_intento_reagrupar` **y** `categoria_rara_reagrupada`; tras uno fallido lleva **sólo el intento**, y la ficha de esa corrida no afirma ninguna reagrupación | No se emiten |
| 8 | El resumen publica su línea **en el camino exitoso**, en español y sin identificadores del motor. El camino fallido NO se mide aquí: su diagnóstico lo dan el mensaje del error y el trail, y eso lo miden el 6 y el 7 | La rama no existe |
| 9 | **Bit a bit**: la proyección canónica de una corrida F1 del preset antes y después, **cero diferencias**, `config_hash` `1063d6cf…` intacto | — (guardrail) |

**Controles negativos (§6):** (a) desactivar la regla y ver rojo el test 1; (b) tomar los conteos
del archivo en vez de la tabla del paso y ver rojo el 5; (c) reintentar en bucle en vez de una vez
y ver rojo el 6; (d) elegir un corte que deje un solo nivel debajo y ver rojo el 4; (e) emitir la
decisión también cuando no hace falta y ver rojo el 3; (f) emitir la decisión del intento
**después** de propagar el error y ver rojo el 6; (g) escribir el corte efectivo en el config en
vez de en la card y ver rojo el 6b por el `config_hash`.

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
| 6.5 | Qué salidas ofrece el error para una categórica | (a) **excluir la variable, o subir su umbral de categorías raras en el config completo**; (b) además, diseñar una vía de agrupación manual de categorías | **(a)**: es lo ejecutable hoy —`set_bins` escribe `user_splits`, que el motor rechaza en categóricas—. (b) es una capacidad nueva con su propia enmienda, y ofrecerla en un mensaje antes de tenerla manda al modelador contra otro error |
| 6.4 | Dónde vive el corte efectivo | (a) **en la card de `binning`**, publicado junto al declarado, con el `config_hash` intacto; (b) reescribir `binning.cat_cutoff` en el config guardado | **(a)**: (b) rompe la correspondencia con el `config_hash`, que se congela antes de ejecutar el paso. El corte es evidencia de la corrida, como el IV; la reproducibilidad la da que la regla sea determinista, no guardar el número |
| 6.3 | Si el default `cat_cutoff = 0.01` se revisa para 2.0 | (a) **sí, se anota como candidato con esta medición**; (b) se deja como está | **(a)**: §0.1 muestra que un corte fijo puede aislar un nivel en cualquier archivo; es material para la poda de D-SIM-12, no para 1.x |

## 7. La revisión adversarial de este documento

**Tope declarado: tres pasadas**, con el criterio de parada de siempre.

| Pasada | Hallazgo | Qué cambió |
|---|---|---|
| 1 | La puerta guiada **no conoce** la muestra de desarrollo al construir el config: la resuelve `DataStep` con `Partitioner.split` y la semilla, tras el esquema, los especiales y el target | La regla se muda al **motor**, que sí recibe esas filas (§0.3, §6.1) |
| 2 | (a) El corte efectivo no puede ir al config sin contradecir el `config_hash`, que se congela antes de ejecutar; (b) la alerta del reintento fallido **no puede existir**: `on_step` sólo corre si `execute` termina, y ahí el paso ya levantó | (a) §2.1: el corte es **resultado** —card y anexo—, y la reproducibilidad viene de que la regla es determinista; (b) §2.2: el trail se emite **antes** de propagar y quien habla es el **mensaje del error** |

| 3 | (a) Emitir `categoria_rara_reagrupada` **antes** del reintento dejaría, en una corrida fallida, una ficha que afirma una reagrupación que no ocurrió; (b) el mensaje ofrecía «fijar sus tramos» y `set_bins` escribe `user_splits`, que el motor **rechaza en categóricas**; (c) el test 8 seguía exigiendo un resumen que §2.2 declara imposible | (a) dos eventos, `…_intento_reagrupar` y `…_reagrupada`, con su test; (b) el mensaje ofrece sólo salidas ejecutables y §6.5 lo eleva; (c) el test 8 se limita al camino exitoso |

Las dos primeras pasadas tumbaron una premisa de arquitectura cada una; la tercera ya no tumbó
ninguna —corrigió una contradicción interna y dos promesas que el motor no puede cumplir—, que es
el criterio de parada declarado. **Tope alcanzado**: estas correcciones no llevan pasada propia, y
la implementación abrirá con una sobre su propio rango de código.

## 8. Implementación (2026-09-23) — lo que el código midió distinto de lo escrito

Implementada el 2026-09-23. Seis precisiones que el lector de §2–§4 encontraría distintas en el
código:

1. **El alcance de la regla es exactamente el caso medido.** Entra sólo si la columna es
   **categórica** con corte declarado, un bin **regular** tiene observaciones y una clase en cero,
   y ese bin está formado por niveles que el corte ya había mandado **solos** bajo el umbral —un
   único nivel debajo—. Fuera de ese caso (un bin especial o de faltantes degenerado, un grupo de
   raras que ya tiene dos niveles, un bin que armó el optimizador con niveles sobre el corte) no
   hace nada y habla la validación de siempre: reagrupar ahí sería una decisión de modelación que
   la enmienda no aprobó.
2. **El corte efectivo es `(n₂ + ½) / n`**, con `n₂` las filas del segundo nivel más raro y `n`
   las filas limpias (sin faltantes ni especiales) sobre las que OptBinning aplica el corte: es
   el punto medio del intervalo de cortes que agrupan exactamente los dos niveles más raros, así
   que no depende de redondeos. Sobre German Credit: 0,01 → 0,0118 (9,5 / 802).
3. **El reajuste toca sólo esa columna**, por la API pública de OptBinning
   (`BinningProcess.update_binned_variable`): se repite la conversión `check_array` del ajuste
   completo y se ajusta un proceso de una sola variable con los mismos parámetros salvo el corte.
   El resto de las columnas no se reajusta, y `summary()` recalcula sus estadísticas.
4. **El sumidero llega al binner por `WoEBinner.fit(..., audit=...)`**, un keyword nuevo y
   aditivo, con el mismo patrón que `PDCalibrator.fit`. `BinningStep` le pasa el suyo: así el
   intento queda en el trail aunque el reajuste falle y `execute` no termine.
5. **El bit a bit del test 9 da una diferencia, no cero.** La §2.1 aprobada (6.4) publica el
   corte efectivo en la card de `binning`, y un campo nuevo de la card es una clave nueva en la
   proyección: `binning_card.rare_category_regroupings = {}` en el preset F1. Es la única
   diferencia; el `config_hash` `1063d6cf…` no se mueve y ningún número cambia. El «cero
   diferencias» de la tabla del §4 no era alcanzable con la decisión aprobada.
6. **El Anexo publica el corte como el resto de la card**, con los dos campos
   (`declared_cat_cutoff`, `effective_cat_cutoff`) uno junto al otro, no con la frase de §2.1:
   el Anexo de parámetros reproduce el payload de cada card sin redactarlo, y es un anexo de
   auditoría. La frase para una persona vive en el resumen de «Tramos y WoE».

**Gate de aceptación, medido fuera de la suite con el archivo de la UCI** (sha256 del crudo
`b21f3d81…`, `partition="random"`): German Credit termina **`done` en 12,7 s**, con **20 de 20
variables tramificadas** —sus 13 categóricas intactas—, la línea «Categorías con muy pocas
operaciones agrupadas para poder calcular su WoE: «proposito» (nivel A48: 5 operaciones, ninguna
incumplida)», las dos decisiones en el trail en su orden, el bin final `['A410', 'A48']` con 14
operaciones y 4 malos, AUC Holdout 0,837 y validación técnica «Pasa». En la suite, el test 1 corre
sobre una cartera sintética que reproduce el mecanismo (el archivo de la UCI no se descarga en
CI).

**Controles negativos:** los siete de §4 más uno del resumen (h), cada uno rojo en su test y
restaurado byte a byte.

**Revisión adversarial del código.** Tope declarado: tres pasadas sobre `9a4312a..HEAD`.

| Pasada | Hallazgo | Qué cambió |
|---|---|---|
| 1 | (a) **alto**: la regla miraba las categóricas **antes** del descarte por estado del solver (`require_optimal`): una variable no óptima, que antes se descartaba y dejaba terminar la corrida, podía reajustarse —cambiando números— o detenerla; (b) con dos categorías, o con empates por encima del nivel raro, juntar los dos más raros manda **todas** al grupo de raras y el reajuste es imposible, y el mensaje igual ofrecía subir el umbral, que no puede resolverlo (y cuyo máximo es 0,5) | (a) la regla salta la variable si su estado no es óptimo y la exige el config, como hace la recolección; (b) si el corte dejaría todas bajo el umbral no se intenta —el trail no registra un intento imposible— y el mensaje sólo ofrece excluir la variable; tras un reintento fallido, «sube el umbral» se ofrece sólo si existe un umbral ≤ 0,5 que agrupe el nivel siguiente y deje alguno fuera (el máximo se lee del campo del config). Tres controles negativos más y un test del reintento fallido sin umbral posible |
| 2 | (a) **alto**, según Codex: con pesos fraccionarios la regla truncaba `Event`/`Non-event` a entero y podía tratar como degenerado un nivel que la validación aceptaba. **Medido, la premisa no se sostiene**: OptBinning 0.20 ya trunca las masas en su propia tabla —ocho filas con un malo a peso 0,5 salen `Count 3, Event 0`— y la validación de siempre, que lee esa tabla, moría igual; lo que sí era real es que la regla **publicaba masas como operaciones** (3 y ninguna incumplida en vez de 8 y 1). (b) **medio**: el sumidero quedaba guardado en el binner, así que un segundo `fit` sin `audit` escribía en el trail anterior o fallaba si estaba cerrado | (a) la detección compara la tabla sin truncar —igual que la validación— y los conteos que se publican y se dicen salen de las **filas ajustadas**, sin pesos; la frase dice cuántas incumplidas cuando no es ninguna ni todas; (b) el sumidero se pone y se retira alrededor de la única parte que emite decisiones. Dos controles negativos más |

## 13. Simplicidad (SDD-31) — obligatoria

- **Entrada mínima:** no cambia. Nada nuevo que declarar.
- **Qué NO se configura:** el reintento. No hay un flag «permitir reagrupar»: sin reagrupar no hay
  WoE, y la alternativa es que la corrida muera. Preguntarlo sería pedirle al modelador una
  decisión que sólo tiene una respuesta razonable.
- **Campos esenciales:** sin cambios; `binning` no gana ninguno.
- **Presupuesto de perillas: CERO.** `cat_cutoff` global y por variable ya existen y siguen
  contando igual; las perillas de las doce secciones del scorecard siguen en **413**.
- **Resumen por etapa:** el de tramos gana **una** línea condicional, sólo en el camino exitoso.
  En el camino fallido el resumen no llega a construirse y quien habla es el mensaje del error
  (§2.2). Ninguna de las dos aparece cuando la regla no entra.
- **Notebook mínimo:** sin cambios (15 líneas, 5 conceptos).
- **Las cinco cifras:** idénticas. Lo que cambia no es una cifra: es que un archivo externo real
  llega hasta el final.
