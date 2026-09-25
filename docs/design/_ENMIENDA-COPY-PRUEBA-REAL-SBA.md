# Enmienda corta de copy — lo que la prueba real con el SBA mostró mal escrito

| Campo | Valor |
|---|---|
| **Tipo** | Enmienda de **copy y presentación** sobre la puerta guiada, la pantalla, el informe y el sitio, **más dos requisitos aditivos del motor** que exigen los rótulos de tramo (§3): el casamiento de `point_overrides` y una clave con los bordes efectivos. No toca el config ni cambia ningún artefacto existente |
| **Decisiones** | **D-CPY-1…6** (qué se corrige y cómo) y tres **elevaciones** que no son copy (§8) |
| **Módulos** | `nikodym.guided` (`summaries`, `scorecard`), `nikodym.report` (`prose`, `renderer`), `web/src/lib/results-format.ts`, `docs_site/` |
| **Fase** | F1 |
| **Estado** | **APROBADA por Cami el 2026-09-24/25** (S22, interactivo): rangos **con comparadores** (§7.1 a). La reestructuración de §3 tras la pasada 2 abre la implementación con una pasada de Codex sobre su código |
| **Depende de** | D-FLU (resúmenes por etapa, `TablaDeEtapa`), D-VAL-13…18 (líneas de validación) |
| **Release** | Ningún número, `config_hash` ni artefacto existente cambia; §3 añade una clave y una alerta ⇒ **minor** (entra con la que corresponda) |
| **Autor / Fecha** | Claude Code (writer) / 2026-09-24 |

---

## 0. De dónde sale

Cami corrió la puerta guiada y la pantalla con la muestra pública de préstamos 7(a) de la SBA.
En S21 anotó nueve hallazgos: el primero, puntuar la población TTD, tiene su propia enmienda
([`_ENMIENDA-PUNTUAR-POBLACION-TTD.md`](_ENMIENDA-PUNTUAR-POBLACION-TTD.md)). Esta enmienda cubre
los otros ocho. Cada «hoy» está medido el 2026-09-24 sobre `d2839d8`, con el SBA crudo por la puerta
guiada (`date="fecha_aprobacion"`, `oot_from="2008-01-01"`, `config_hash` `a27e678f…`).

Seis son copy o presentación y se corrigen aquí (§1–§6). Tres piden algo más que un texto: una
regla de validación, un campo que viaje en el YAML o una detección nueva. Esos se **elevan** en §8
en vez de disfrazarse de copy.

## 1. D-CPY-1 — la partición `fuera_de_modelo` tiene rótulo (hallazgo 2)

**Hoy** la tabla de muestras del resumen de datos dice:

```text
              Muestra  Filas Malos Tasa de malos
           Desarrollo 30.316 7.214       23,80 %
              Holdout  7.733 1.867       24,14 %
Fuera de tiempo (OOT)  5.725 1.246       21,76 %
      fuera_de_modelo  6.225     0             —
```

El código interno llega crudo porque `report/prose.py` `_PARTITION_LABELS` sólo conoce tres
particiones. Además, en el SBA «0 malos» es falso: esas filas no tienen desenlace, así que sus malos
son desconocidos, no cero.

**Dirá:** «Fuera del ajuste». Se usa este rótulo y no «Sin desenlace» porque la partición también
reúne a los **excluidos** por una regla y a las filas **con desenlace** que la división por columna
no asignó a ninguna muestra (`_split_from_column`).

- **Malos y tasa.** Si ninguna fila fuera del ajuste tiene target 0/1, Malos y Tasa de malos dicen
  «—». Si algunas lo tienen, se conserva el conteo de malos y la tasa se calcula sobre ellas, con
  el denominador declarado en la línea, p. ej. «tasa sobre 412 con desenlace». Nunca se borra un
  incumplimiento conocido (revisión adversarial, pasada 1).
- **La línea del resumen** hoy dice «N indeterminadas y M excluidas». Nombra también el tercer
  grupo cuando existe: «y K con desenlace fuera de las muestras declaradas».
- **Resumen y página ejecutiva:** leen la entrada nueva de `_PARTITION_LABELS`.
- **Informe.** La tabla `data.partitions` **no** pasa por ese mapa. `ReportBuilder` copia
  `str(partition)` en la columna **`Partición`**, y el renderer sólo aplica rótulos a las tablas
  `validation.*`. Se añade `"data.partitions": {"Partición": _PARTITION_LABELS}` al mapa por tabla
  del renderer —la clave es el nombre exacto de la columna, que es como la busca `_table_view`
  (revisión adversarial, pasada 2)—. Un test ancla en HTML y Word que ninguna fila de
  `data.partitions` muestre un identificador crudo. El export crudo conserva el identificador, como el de las demás tablas. Hoy la
  tabla pinta las cuatro claves crudas; se ve en `web/src/fixtures/demo/report-ifrs9.html`.
- **La pantalla** tiene su propio `partitionLabel` (`web/src/lib/results-format.ts`), que tampoco
  conoce `fuera_de_modelo` y dice «OOT» donde Python dice «Fuera de tiempo (OOT)». Se alinea con
  el mapa de Python.
- **Gate:** el filtro de identificadores internos de `test_guided_summaries.py` hoy sólo arma su
  lista con claves que aparecen en algún mapa de rótulos, y `fuera_de_modelo` no estaba en
  ninguno. Se añade explícitamente, y la corrida de prueba gana filas fuera de modelo.

## 2. D-CPY-2 — la línea de validación nombra lo que falló (hallazgo 3)

**Hoy** el estado técnico del resumen final, el de la etapa, la pantalla y la página ejecutiva
dicen:

```text
… PSI del score Desarrollo vs. OOT (Revisar), PSI de la PD Desarrollo vs. OOT (Revisar),
CSI Desarrollo vs. OOT (Redesarrollar), CSI Desarrollo vs. OOT (Redesarrollar),
CSI Desarrollo vs. OOT (Redesarrollar) y PSI temporal period (Redesarrollar)
```

`_pruebas_decisivas` (`guided/summaries.py`) traduce la comparación sólo con `_COMPARISON_LABELS`,
así que `period` sale crudo, y no usa la columna `feature`, así que los tres CSI son
indistinguibles.

**Dirá:** «CSI de anio_fiscal Desarrollo vs. OOT (Redesarrollar), CSI de
antiguedad_de_la_empresa …, CSI de con_garantia_real … y PSI temporal por período
(Redesarrollar)». Se usan los mismos mapas que la **tabla** de esa misma etapa, que ya lo resuelve
bien (`{**_COMPARISON_LABELS, **TEMPORAL_AXIS_LABELS}` y `_sin_sufijo(feature)`): una sola fuente
para la línea y la tabla.

**Gate:** una prueba ancla la frase con un CSI de dos variables y el eje temporal, y el filtro de
identificadores internos se extiende a los valores sin guion bajo (`period`, `cohort`).

## 3. D-CPY-3 — los tramos se leen como texto (hallazgos 4 y 8): presentación con dos requisitos del motor

**Hoy** la tabla de la tarjeta y la de tramos dicen:

```text
anio_fiscal               ['2001' '2000']
antiguedad_de_la_empresa  ['5 años o más' '2 a 3 años' '4 a 5 años']

Tramo                 Rango  Filas Malos Tasa de malos    WoE
    1      (-inf, 50450.00) 15.001 4.109       27,39 % -0,189
    2 [50450.00, 102230.50)  4.707 1.111       23,60 %  0,011
```

- **Los tramos categóricos** muestran la representación de un arreglo de numpy:
  `scorecard/scaler.py` hace `str(row["Bin"])` sobre el arreglo de categorías de OptBinning.
- **Los rangos** son la etiqueta de OptBinning, **redondeada a dos decimales** (`show_digits=2`) y
  con punto decimal.

Los dos llegan igual a `sc.results`, a la pantalla y al informe.

**Dirá:**

- **Categóricos:** «2001, 2000» y «5 años o más, 2 a 3 años, 4 a 5 años», es decir, las
  categorías unidas con «, » en el orden de OptBinning. Es la regla que la pantalla ya aplica con
  `normalizeBinLabel`.
- **Rangos:** con la forma que Cami elija en §7.1. La recomendada es «< 50.450», «≥ 50.450 y
  < 102.230,5» y «≥ 102.230,5»: punto de miles, coma decimal y sin ceros de relleno, cerrado a la
  izquierda y abierto a la derecha como OptBinning.

Una sola función, `rotulo_de_tramo`, escribe el rótulo para `TablaDeEtapa`, `sc.bins()`, el
informe y el payload de la pantalla.

**Por qué no basta con cambiar el texto (revisión adversarial, pasada 2).** Dos cosas del motor
dependen de la etiqueta que hoy se ve, y la enmienda las resuelve de forma **aditiva**:

1. **El casamiento de los puntos fijados a mano.**
   - Hoy: `scorecard.point_overrides[].bin_label` se casa con `str(row["Bin"])`, y su ayuda dice
     «etiqueta exacta del bin, tal como aparece en la tabla de binning; si no calza exactamente,
     el override no se aplica». El override que no casa **se ignora en silencio**: es un defecto
     previo.
   - Problema: si la tabla muestra «2001, 2000» y el modelador copia eso, el ajuste no se
     aplicaría y nadie lo sabría.
   - **Regla:**
     - el escalador casa `bin_label` con la etiqueta del motor **o** con el rótulo legible de
       `rotulo_de_tramo`; los dos se calculan del mismo `Bin` y son únicos dentro de una variable;
     - un override que no casa con ninguno de los dos queda **declarado**: una decisión
       `point_override_sin_casar` en el trail y una **alerta** en el resumen de la tarjeta, con la
       variable y la etiqueta escrita;
     - no es un error, para no detener corridas que hoy terminan.
   - Las etiquetas del motor que hoy casan siguen casando igual, así que ningún número de una
     corrida que hoy aplica sus overrides cambia.
   - Único cambio de número posible: un override escrito ya con el rótulo legible, que hoy se
     ignoraba en silencio y pasa a aplicarse. Se declara.
   - La ayuda del campo pasa a decir «la etiqueta del motor o el rótulo de la tabla».
2. **Los bordes efectivos de los rangos.**
   - La etiqueta `Bin` está redondeada, y un corte puede tener más decimales:
     - `merge_bins` toma los cortes de `process_.splits`;
     - `set_bins` admite decimales largos.
   - El informe (`ReportBuilder` recolecta `binning.tables`, no `binning.process`) y la pantalla
     (el serializer envía sólo las tablas) no tienen el corte. Escribir un comparador desde la
     etiqueta redondeada podría afirmar que una operación junto al borde cae en el tramo
     equivocado.
   - **Regla:**
     - `binning` publica una **clave aditiva** `("binning", "bin_edges")`: un frame con
       `variable`, `bin_index`, `lower` y `upper` a precisión completa, para los tramos regulares
       de las variables numéricas;
     - el resumen, el informe (que la recolecta sin registrarla como tabla) y el payload de la
       pantalla leen los bordes de ahí;
     - sin esa clave (artefactos inyectados de una corrida anterior) el rango se muestra con la
       etiqueta del motor tal cual, sin inventar un borde.

`binning.tables` y `scorecard.scorecard` no cambian: `Bin` y `bin_label` conservan la etiqueta del
motor, que es la que leen el bundle y los cortes fijados.

**Gate:**

- `rotulo_de_tramo`, con tests de bordes infinitos, decimales, miles y enteros;
- un override escrito con el rótulo legible se aplica;
- uno con la etiqueta del motor se aplica igual que hoy;
- uno que no casa deja la decisión y la alerta;
- un corte con **más de dos decimales** y valores a ambos lados del borde: el rango de HTML, Word
  y pantalla dice el borde exacto;
- sin `bin_edges`, se muestra la etiqueta del motor.

La pantalla tiene sus anclas con punto en `results-format.test.ts`: se alinea con la misma regla y
esas anclas se mueven. `test_diagnosticos_por_muestra.py` sigue verde: fija la forma del
`bin_frame` de entrada, no la de una superficie.

## 4. D-CPY-4 — los p-valores se escriben en es-CL (hallazgo 8)

**Hoy** la tabla del modelo dice «p-valor 0,0000» en las ocho filas: usa el tipo de celda `"num"`,
con cuatro decimales.

**Dirá:** un tipo de celda `"pvalor"` en `TablaDeEtapa`, con la regla que las frases ya usan
(`_pvalor`): «< 0,001» por debajo de ese umbral y tres decimales por encima. Se aplica al modelo y a
la validación.

**Gate:** tests del tipo de celda en los dos umbrales, y las tablas del modelo y de la validación
sin «0,0000».

## 5. D-CPY-5 — el sitio escribe los decimales con coma (hallazgo 9)

**Hoy**, contado fuera de los bloques de código:

| Página | Con punto | Con coma |
|---|---|---|
| `tutorial.md` | 73 | 0 |
| `guias/binning-seleccion.md` | 46 | 0 |
| `guias/modelo-calibracion.md` | 17 | 0 |
| `glosario.md` | 0 | 31 |
| `guias/desempeno-estabilidad.md` | 0 | 32 |
| `guias/validacion-formal.md` | 0 | 24 |
| `guias/analisis-exploratorio.md` | 0 | 14 |

**Dirá:** coma decimal en toda la prosa, tablas incluidas. El código, sus salidas y los nombres de
parámetros (`target_pd = 0.20`) conservan el punto, porque así los escribe Python.

**Gate:**

- `test_docs_site_cifras.py` no exige un separador. Sus anclas citan el punto en `tutorial.md` y
  `modelo-calibracion.md`, y se mueven a la coma.
- Se añade un test que cuenta las cifras con punto decimal en el **texto visible** y exige cero,
  con su control negativo.
- El test usa un extractor probado aparte, que excluye tres cosas:
  - los bloques de código;
  - el **código en línea** (`min_iv = 0.02` va entre comillas invertidas en una tabla de
    `tutorial.md`);
  - las **versiones** (`0.20.0`, `3.11`).

  Sin ese extractor, el gate nacería rojo por literales que esta misma enmienda ordena conservar
  (revisión adversarial, pasada 1).

## 6. D-CPY-6 — Hosmer-Lemeshow dice la brecha que midió (hallazgo 7, la parte de copy)

**Hoy** el estado técnico dice «Hosmer-Lemeshow en Desarrollo (p-valor < 0,001)» en las tres
muestras. Con decenas de miles de filas, el test detecta brechas muy chicas, y el modelador no ve
cuán grande es la que hay. Medido:

| Muestra | Filas | PD calibrada media | Tasa observada | p-valor |
|---|---|---|---|---|
| Desarrollo | 30.316 | 23,80 % | 23,80 % | < 0,001 |
| Holdout | 7.733 | 23,82 % | 24,14 % | < 0,001 |
| Fuera de tiempo (OOT) | 5.725 | 27,15 % | 21,76 % | < 0,001 |

**Lo que esa tabla no dice.** Hosmer-Lemeshow suma las desviaciones entre observado y esperado
**por grupo de PD**. `expected_pd` y `observed_dr` son **medias de toda la muestra**, y pueden
coincidir aunque varios grupos estén descalibrados en sentidos opuestos. Que la media de Desarrollo
calce exactamente (el calibrador la ancla ahí) **no** prueba que el rechazo sea sólo potencia del
test (revisión adversarial, pasada 1). En OOT la brecha media ya es material: el modelo espera 5,4
puntos más de lo que ocurrió.

**Dirá:** la línea de cada Hosmer-Lemeshow que falla suma la **brecha media agregada** que el motor
ya publica, sin atribuirle una causa: «Hosmer-Lemeshow en Fuera de tiempo (OOT) (p-valor < 0,001;
PD media agregada 27,2 % frente a 21,8 % observada)».

- **El veredicto no cambia.** Decidir que un rechazo con muestra grande no cuenta es metodología y
  va en §8.1.
- **Mostrar la desviación por grupo** exige publicar la tabla por grupo del test, y también va en
  §8.1.

## 7. Lo que Cami decide

| # | Decisión | Opciones | Recomendación |
|---|---|---|---|
| 7.1 | Cómo se escribe un rango de tramo | (a) **con comparadores**: «< 50.450», «≥ 50.450 y < 102.230,5», «≥ 102.230,5»; (b) notación de intervalo con coma decimal: «(−∞; 50.450)», «[50.450; 102.230,5)»; (c) en palabras: «menos de 50.450», «de 50.450 a menos de 102.230,5» | **(a)**: exacta en los bordes, corta y legible sin conocer la notación de intervalos. (b) exige el punto y coma, que confunde a quien viene de Excel; (c) es la más clara, pero alarga la columna |

## 8. Lo que se eleva (no es copy)

| # | Hallazgo | Por qué no cabe aquí | Propuesta |
|---|---|---|---|
| 8.1 | **Hosmer-Lemeshow «Falla» con muestras grandes** (7) | Decidir que el rechazo no cuenta, o sumar un criterio de brecha absoluta, cambia el veredicto de validación: es metodología (D-VAL-13…18). Mostrar la desviación por grupo exige publicar la tabla por grupo del test | Enmienda propia de validación: la tabla por grupo del test y un criterio de materialidad junto al p-valor, con cotejo contra fuentes |
| 8.2 | **Las decisiones humanas con motivo no viajan en el YAML** (5) | `to_yaml()` vuelca sólo el config. El motivo vive en el preámbulo del trail. La pantalla corre `nikodym.run` sin preámbulo y muestra «Sin decisiones». Que viajen exige un campo nuevo, en `governance` (INFRA, fuera del `config_hash`) o en otro lado: es un cambio de schema | Enmienda propia: las decisiones con motivo viajan en el YAML y la pantalla las muestra y las registra |
| 8.3 | **`anio_fiscal` entra como predictora sin aviso con partición por fecha** (6) | Detectar una columna derivada de la fecha es una regla nueva. Además comparte causa con el defecto previo de la enmienda TTD §7: la categoría 2009 no existe en Desarrollo, el motor le da WoE neutro en silencio y el bundle la rechaza | Enmienda propia que junte las dos cosas: una regla declarada para categorías no vistas en Desarrollo (motor y bundle iguales) y un aviso cuando una predictora cambia de dominio entre Desarrollo y OOT |

## 9. Estrategia de tests y controles negativos

Un test nacido rojo por cada D-CPY (los de §1–§6) y un control negativo por gate nuevo:

- quitar `fuera_de_modelo` del mapa (D-CPY-1);
- volver a `_COMPARISON_LABELS` solo (D-CPY-2);
- pintar con `str()` (D-CPY-3);
- casar el override sólo con la etiqueta del motor (D-CPY-3);
- no declarar el override sin casar (D-CPY-3);
- escribir el rango desde la etiqueta redondeada en vez de `bin_edges` (D-CPY-3);
- pintar el p-valor con `"num"` (D-CPY-4);
- inyectar una cifra con punto en una guía (D-CPY-5);
- omitir la brecha (D-CPY-6).

Guardrails:

- **Bit a bit sin ninguna diferencia**, sobre el preset F1, en los **artefactos computacionales**
  (la proyección canónica), el config, el `config_hash` `1063d6cf…` y los **exports crudos** del
  informe (CSV/Parquet). Ninguno de ellos cambia, salvo la clave aditiva
  `("binning", "bin_edges")`.
- **Lo que sí cambia, declarado:** el HTML, PDF y Word renderizados, los resúmenes y la pantalla.
  El informe de F1 pinta `binning.tables`, `scorecard.scorecard` y `data.partitions`, así que sus
  goldens se mueven. Se revisa cada diferencia, una por una, contra lo que esta enmienda promete, y
  cualquier otra diferencia es un defecto (revisión adversarial, pasada 1).

## 10. La revisión adversarial de este documento

Tope declarado: **dos pasadas**, porque es una enmienda de presentación.

| Pasada | Hallazgo | Qué cambió |
|---|---|---|
| 1 | (a) **alto**: «Malos —» borraba los incumplimientos conocidos de las filas con desenlace que la división por columna aparta. (b) **alto**: la etiqueta de OptBinning está redondeada a dos decimales, y un comparador escrito desde ella podía afirmar un borde falso. (c) **alto**: la brecha media no es lo que mide Hosmer-Lemeshow, y atribuir el rechazo a la potencia del test podía minimizar una falla real. (d) **medio**: `data.partitions` del informe no pasa por `_PARTITION_LABELS`. (e) **medio**: un gate de «cero puntos decimales fuera de los bloques» nacería rojo por el código en línea y las versiones. (f) **medio**: «F1 sin ninguna diferencia» chocaba con los goldens del informe que sí se mueven | (a) §1: «—» sólo sin target, y denominador declarado. (b) §3: comparadores desde los cortes efectivos, con un test junto al borde. (c) §6: «brecha media agregada», sin causa atribuida, y la tabla por grupo en §8.1. (d) §1: mapa por tabla en el renderer, probado en HTML y Word. (e) §5: extractor de texto visible, probado aparte. (f) §9: el bit a bit se limita a los artefactos computacionales, el config y los exports crudos; el render se revisa diferencia por diferencia |
| 2 | (a) **alto**: el rótulo legible dejaba de servir para `point_overrides.bin_label`, que casa con la etiqueta cruda y se ignora en silencio si no calza: el modelador que copiara la tabla perdería su ajuste sin saberlo. (b) **alto**: los cortes efectivos no llegan al informe ni a la pantalla, que sólo reciben `binning.tables`, con etiquetas redondeadas. (c) **medio**: la tabla `data.partitions` usa la columna `Partición`, no `partition` | (a) y (b) §3 se reescribió: ya **no es sólo presentación**. Casa las dos etiquetas y declara el override sin casar (defecto previo). Publica los bordes en una clave aditiva `("binning", "bin_edges")`. (c) §1: la clave del mapa es `Partición`, con un test en HTML y Word |

**Tope.** La pasada 2 tumbó la premisa de «sólo presentación» de §3, así que el criterio de parada
no se cumplió dentro del tope de dos. La reestructuración de §3 queda **sin revisar por Codex**. Se
eleva así a Cami y la implementación abre con una pasada sobre el código de §3 antes que nada.

## 13. Simplicidad (SDD-31) — obligatoria

- **Entrada mínima:** no cambia.
- **Qué NO se configura:** el formato de los números (es-CL, fijo), la forma de los rangos (la que
  elija Cami, fija) y los rótulos.
- **Presupuesto de perillas: CERO.**
- **Resumen por etapa:** mismas líneas, mejor escritas; la de Hosmer-Lemeshow suma la brecha
  media agregada, y la tarjeta gana una alerta condicional por override sin casar.
- **Las cinco cifras:** idénticas.
