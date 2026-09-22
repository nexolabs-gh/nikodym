# Enmienda — una categoría rara con una clase en cero no puede matar la corrida

| Campo | Valor |
|---|---|
| **Tipo** | Enmienda corta a [`31-simplicidad-y-flujo-guiado.md`](31-simplicidad-y-flujo-guiado.md) (§8, casos borde) y a [`_ENMIENDA-FLUJO-GUIADO-SCORECARD.md`](_ENMIENDA-FLUJO-GUIADO-SCORECARD.md) (lo que la puerta infiere y declara); **no** toca SDD-06 ni el contrato de `binning` |
| **Decisiones** | **D-RAR-1** (la puerta agrupa, y sólo si hace falta) y **D-RAR-2** (qué dice, dónde y con qué palabras) |
| **Módulos** | `nikodym.guided.scorecard` (construcción del config e inferencias), `nikodym.guided.summaries` (resumen de la etapa de tramos) |
| **Fase** | F1 |
| **Estado** | **Propuesta** — pendiente del OK de Cami |
| **Depende de** | D-SC-3 (el precedente: el motor infiere y lo declara), D-SIM-1/2, D-FLU-1/2, D-SC-17/18 |
| **Lo consumen** | la puerta guiada; nadie más |
| **Release** | Aditiva para todo lo que hoy corre: la regla **sólo** entra cuando la corrida iba a fallar. Ningún `config_hash` de preset se mueve ⇒ **minor** |
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
(`binning/transformer.py:1155`). El problema es **cómo se llegó a ese bin**, y la medición lo
señala con precisión.

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

## 1. Alcance: qué NO se toca

- **El contrato de `binning` no cambia.** Un bin con una clase en cero sigue siendo un error del
  motor, con su mensaje: el WoE no existe y publicar uno sería inventarlo. Lo que cambia es que la
  puerta guiada **no construya** un config que lo provoque pudiendo evitarlo.
- **El default `cat_cutoff = 0.01` no se toca.** Cambiarlo movería el `config_hash` de los presets
  F1 y F5, cambiaría resultados de corridas que hoy terminan con el mismo config —ruptura de la
  garantía 1.x— y obligaría a recapturar la demo. §8.2 lo eleva igualmente, porque es una decisión
  defendible para un 2.0, pero no es esta enmienda.
- **No se añade ninguna perilla.** `cat_cutoff` ya existe, y además **por variable**
  (`BinningConfig.variable_overrides[col].cat_cutoff`, `binning/config.py:126`). La puerta la
  escribe; no la pregunta.
- **No se descarta ninguna variable ni ninguna fila.** Agrupar dos niveles raros conserva toda la
  información; descartar la variable la perdería.

## 2. D-RAR-1 — la puerta agrupa, y sólo si hace falta

Al construir el config, y **después** de resolver las muestras —porque el problema vive en
Desarrollo, no en el archivo—, la puerta guiada hace por cada columna categórica:

1. Cuenta, **sobre la muestra de desarrollo**, buenos y malos de cada nivel. Es aritmética sobre el
   frame, no un segundo binning: no se ajusta nada, no se optimiza nada (RUNBOOK §12.2-5).
2. Marca los niveles **degenerados**: los que tienen cero malos o cero buenos.
3. Si un nivel degenerado quedaría **solo** bajo el `cat_cutoff` vigente —es decir, es el único por
   debajo del corte—, escribe para **esa columna** un `cat_cutoff` override: el menor valor que
   deja al menos **dos** niveles bajo el corte, de modo que el grupo de raras no sea unitario.
4. Si no hay nivel degenerado, **no escribe nada**. Una corrida que hoy funciona no cambia ni un
   número.

**Lo que la regla NO promete.** No garantiza que el bin resultante tenga las dos clases: el
optimizador decide, y puede que ni juntando los dos niveles más raros aparezca un malo. Cuando eso
ocurra, el motor se detendrá con su error de siempre —que es lo correcto—, pero ahora el resumen de
la etapa dirá **qué** categoría es y **qué** se intentó (§3), en vez de dejar al modelador con el
nombre de un bin y ninguna salida. Esa honestidad es parte del contrato: la puerta hace lo que
puede y dice dónde llegó.

**Por qué por variable y no global:** un corte global movería el binning de las otras doce
categóricas de German Credit —y de cualquier archivo— para arreglar una. El override por columna
toca exactamente lo que hay que tocar, y el resto del config sigue siendo el de fábrica.

**Por qué en la puerta y no en el motor:** el motor no sabe qué es «la muestra de desarrollo» hasta
que `data` corrió, y para entonces `binning` ya recibió su config. La puerta sí: resuelve las
muestras antes de construir el config, que es justo donde D-SC-3 ya decide algo parecido con el eje
de la tasa.

## 3. D-RAR-2 — qué se dice y dónde

- **Trail.** Una decisión por columna tocada, con el molde de las inferencias de la puerta
  (`step="scorecard_guided"`, `autor="puerta_guiada"`): regla `categoria_rara_agrupada`, el nivel
  degenerado, sus conteos en desarrollo y el corte escrito. Es una decisión del motor, no humana.
- **Resumen de la etapa de datos y muestras** (donde ya se lee «Se infirió: …»): una línea más
  cuando la regla entra, en el idioma del modelador:

  > Categorías con muy pocas operaciones agrupadas para poder calcular su WoE: «proposito» (nivel
  > A48: 5 operaciones en desarrollo, ninguna incumplida).

- **Resumen de «Tramos y WoE»**, cuando el motor **sí** se detiene pese a la regla: la alerta
  nombra la variable y el nivel, dice que se intentó agruparlo y qué se puede hacer —excluir la
  variable con `exclude(...)`, o reagrupar el nivel desde el config completo—. Hoy el mensaje es el
  del motor y no ofrece salida.
- **Ficha e informe: nada nuevo.** El config final lleva el override y el Anexo de parámetros lo
  reproduce, como cualquier otra hoja. No se inventa una sección.

## 4. Estrategia de tests

Todos nacen rojos salvo los marcados como guardrail.

| # | Test | Nace rojo porque |
|---|---|---|
| 1 | **Gate de aceptación**: `Scorecard(german_credit, target=…, partition="random").run()` termina `done` | Hoy muere en `binning` |
| 2 | La regla escribe el override **sólo** en la columna afectada; las otras doce no ganan ninguna hoja | La regla no existe |
| 3 | Con un archivo sin niveles degenerados, el config es **byte a byte** el de hoy y no hay decisión en el trail | — (guardrail de «sólo si hace falta») |
| 4 | El corte elegido deja **≥ 2** niveles bajo él (los dos sentidos: uno menos y el grupo vuelve a ser unitario) | La regla no existe |
| 5 | Los conteos se miden sobre **desarrollo** y no sobre el archivo: un nivel sano en el archivo y degenerado en desarrollo dispara la regla | La regla no existe |
| 6 | La decisión `categoria_rara_agrupada` está en el trail con sus conteos, una vez por columna | No se emite |
| 7 | El resumen de datos publica su línea, en español y sin identificadores del motor | La rama no existe |
| 8 | Cuando el motor se detiene **igual**, la alerta nombra variable, nivel y salidas | La rama no existe |
| 9 | **Bit a bit**: la proyección canónica de una corrida F1 del preset antes y después, **cero diferencias**, `config_hash` `1063d6cf…` intacto. Esta capa no añade campos, así que aquí la comparación es estricta | — (guardrail) |

**Controles negativos (§6):** (a) desactivar la detección y ver rojo el test 1; (b) medir los
conteos sobre el archivo en vez de desarrollo y ver rojo el 5; (c) escribir el override en todas
las categóricas y ver rojo el 2; (d) elegir un corte que deje un solo nivel debajo y ver rojo el 4;
(e) emitir la decisión también cuando no hace falta y ver rojo el 3.

## 5. Riesgos

1. **Que la regla cambie resultados de corridas que hoy funcionan.** Cerrado por construcción: sólo
   entra ante un nivel degenerado en desarrollo, y el test 3 lo vigila con su control negativo (e).
2. **Que el corte elegido empeore el binning de esa variable.** Junta los dos niveles más raros; el
   resto del binning lo sigue decidiendo el optimizador con las hojas de fábrica. El IV de la
   variable queda en la tabla de la etapa, como siempre, y el modelador puede excluirla.
3. **Que se lea como que el motor ya no falla nunca.** No: §2 declara explícitamente lo que la
   regla NO promete, y §3 da el copy del caso en que se detiene igual.

## 6. Lo que Cami decide

| # | Decisión | Opciones | Recomendación |
|---|---|---|---|
| 6.1 | Dónde vive el arreglo | (a) **la puerta guiada infiere y declara** (esta enmienda); (b) subir el default `cat_cutoff` del motor; (c) exponer `cat_cutoff` como campo esencial; (d) que el motor degrade el bin | **(a)**: no mueve ningún `config_hash`, no añade perillas, no cambia una corrida que hoy funciona, y es el mismo patrón que D-SC-3. (b) rompe la garantía 1.x y obliga a recapturar; (c) pone al modelador a decidir sobre un umbral que no debería tener que conocer; (d) exigiría inventar un WoE |
| 6.2 | Qué hace la regla cuando aun agrupando queda una clase en cero | (a) **el motor se detiene con su error, y el resumen explica y ofrece salidas**; (b) la puerta excluye la variable sola | **(a)**: excluir una variable sin preguntar es una decisión de modelación, y el contrato dice que esas las toma la persona (D-FLU) |
| 6.3 | Si el default `cat_cutoff = 0.01` se revisa para 2.0 | (a) **sí, se anota como candidato con esta medición**; (b) se deja como está | **(a)**: la medición de §0.1 muestra que un corte fijo puede aislar un nivel en cualquier archivo; es material para la poda de D-SIM-12, no para 1.x |

## 13. Simplicidad (SDD-31) — obligatoria

- **Entrada mínima:** no cambia. Nada nuevo que declarar.
- **Qué NO se configura:** el umbral. La puerta lo calcula del archivo y lo declara; preguntarlo
  sería pedirle al modelador una decisión que sólo se puede tomar después de mirar los datos, que
  es justo lo que la puerta ya hace por él con el esquema, las predictoras y las muestras.
- **Campos esenciales:** sin cambios; `eda` y `binning` no ganan ninguno.
- **Presupuesto de perillas: CERO.** `cat_cutoff` global y por variable ya existen y siguen
  contando igual; las perillas de las doce secciones del scorecard siguen en **413**.
- **Resumen por etapa:** el de datos gana **una** línea condicional; el de tramos gana **una**
  alerta condicional. Ninguno cambia cuando la regla no entra.
- **Notebook mínimo:** sin cambios (15 líneas, 5 conceptos).
- **Las cinco cifras:** idénticas. Lo que cambia no es una cifra: es que un archivo externo real
  llega hasta el final.
