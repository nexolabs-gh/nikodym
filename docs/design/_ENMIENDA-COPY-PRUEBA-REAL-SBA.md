# Enmienda corta de copy — lo que la prueba real con el SBA mostró mal escrito

| Campo | Valor |
|---|---|
| **Tipo** | Enmienda de **copy y presentación** sobre la puerta guiada, la pantalla, el informe y el sitio. No toca el motor, el config ni ningún artefacto publicado |
| **Decisiones** | **D-CPY-1…6** (qué se corrige y cómo) y tres **elevaciones** que no son copy (§8) |
| **Módulos** | `nikodym.guided` (`summaries`, `scorecard`), `nikodym.report` (`prose`, `renderer`), `web/src/lib/results-format.ts`, `docs_site/` |
| **Fase** | F1 |
| **Estado** | **Propuesta** el 2026-09-24 (S22). Sin código |
| **Depende de** | D-FLU (resúmenes por etapa, `TablaDeEtapa`), D-VAL-13…18 (líneas de validación) |
| **Release** | Sólo presentación: ningún número, `config_hash` ni artefacto cambia ⇒ **patch** (entra con la minor que corresponda) |
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
particiones. Además, «0 malos» es falso: esas filas no tienen desenlace, así que sus malos son
desconocidos, no cero.

**Dirá:** «Fuera del ajuste», con Malos «—». Se usa «Fuera del ajuste» y no «Sin desenlace»
porque la partición también reúne a los **excluidos** por una regla, que pueden tener desenlace. Es
el mismo rótulo que ya usa la línea del resumen («Fuera del ajuste: N indeterminadas y M
excluidas»).

- **Una sola fuente:** la entrada nueva en `_PARTITION_LABELS`, que leen el resumen, la página
  ejecutiva y la tabla `data.partitions` del informe. Hoy esa tabla pinta las cuatro claves crudas;
  se ve en `web/src/fixtures/demo/report-ifrs9.html`.
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

## 3. D-CPY-3 — los tramos categóricos se leen como texto (hallazgo 4)

**Hoy** la tabla de la tarjeta dice:

```text
anio_fiscal               ['2001' '2000']
antiguedad_de_la_empresa  ['5 años o más' '2 a 3 años' '4 a 5 años']
```

Es la representación de un arreglo de numpy: `scorecard/scaler.py` hace `str(row["Bin"])` sobre
el arreglo de categorías de OptBinning. Llega igual a `sc.results`, a la pantalla y al informe.

**Dirá:** «2001, 2000» y «5 años o más, 2 a 3 años, 4 a 5 años»: las categorías unidas con «, »,
en el orden de OptBinning. Es la regla que la pantalla ya aplica con `normalizeBinLabel`, así que
ambas lecturas quedan iguales.

- **Sólo en la presentación.** `bin_label` es también la clave con que se casan los puntos
  fijados a mano (`scorecard.point_overrides`), así que el artefacto `scorecard.scorecard` y su
  `bin_label` **no cambian**. Se formatea al pintar: `TablaDeEtapa`, el informe y `sc.bins()`.
- **Gate:** una función `rotulo_de_tramo` con su test, usada por las tres superficies. Un test
  confirma que `bin_label` en el artefacto sigue igual, así que el ajuste manual de puntos no se
  entera. `test_diagnosticos_por_muestra.py` sigue verde: fija la forma del `bin_frame` de
  entrada, no la de una superficie.

## 4. D-CPY-4 — los rangos y los p-valores se escriben en es-CL (hallazgo 8)

**Hoy:**

```text
Tramo                 Rango  Filas Malos Tasa de malos    WoE
    1      (-inf, 50450.00) 15.001 4.109       27,39 % -0,189
    2 [50450.00, 102230.50)  4.707 1.111       23,60 %  0,011
```

y la tabla del modelo dice «p-valor 0,0000» en las ocho filas. El rango es la etiqueta de
OptBinning (`.2f`, punto decimal), que pasa tal cual. El p-valor usa el tipo de celda `"num"`, con
cuatro decimales.

**Dirá:**
- **Rangos:** con la forma que Cami elija en §7.1. La recomendada es «< 50.450», «≥ 50.450 y
  < 102.230,5» y «≥ 102.230,5»: punto de miles, coma decimal, sin ceros de relleno y con los
  bordes exactos de OptBinning (cerrado a la izquierda, abierto a la derecha).
- **p-valores:** un tipo de celda `"pvalor"` en `TablaDeEtapa` con la regla que las frases ya
  usan (`_pvalor`): «< 0,001» por debajo de ese umbral y tres decimales por encima. Se aplica al
  modelo y a la validación.

Como en §3, el cambio es sólo al pintar: `binning.tables` conserva la etiqueta de OptBinning, que
es la que leen el bundle y los cortes fijados.

**Gate:** tests del formateador con bordes infinitos, decimales, miles y enteros. La pantalla
tiene sus anclas con punto en `results-format.test.ts`: se alinea con la misma regla y se mueven.

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

**Gate:** `test_docs_site_cifras.py` no exige un separador; sus anclas citan el punto en
`tutorial.md` y `modelo-calibracion.md` y se mueven a la coma. Se añade un test que cuenta las
cifras con punto decimal fuera del código y exige cero, con su control negativo.

## 6. D-CPY-6 — Hosmer-Lemeshow dice la brecha que midió (hallazgo 7, la parte de copy)

**Hoy** el estado técnico dice «Hosmer-Lemeshow en Desarrollo (p-valor < 0,001)» en las tres
muestras. Con decenas de miles de filas, el test detecta brechas muy chicas, y el modelador no ve
cuán grande es la que hay. Medido:

| Muestra | Filas | PD calibrada media | Tasa observada | p-valor |
|---|---|---|---|---|
| Desarrollo | 30.316 | 23,80 % | 23,80 % | < 0,001 |
| Holdout | 7.733 | 23,82 % | 24,14 % | < 0,001 |
| Fuera de tiempo (OOT) | 5.725 | 27,15 % | 21,76 % | < 0,001 |

En Desarrollo y Holdout la media casi no se mueve, y el rechazo es la potencia del test sobre la
forma por grupo. En OOT la brecha es real: el modelo espera 5,4 puntos más de lo que ocurrió.

**Dirá:** la línea de cada Hosmer-Lemeshow que falla suma la brecha que el motor ya publica
(`expected_pd` y `observed_dr` de `validation.calibration`): «Hosmer-Lemeshow en Fuera de tiempo
(OOT) (p-valor < 0,001; PD media 27,2 % frente a 21,8 % observada)». **El veredicto no cambia**:
decidir que un rechazo con muestra grande no cuenta es metodología y va en §8.1.

## 7. Lo que Cami decide

| # | Decisión | Opciones | Recomendación |
|---|---|---|---|
| 7.1 | Cómo se escribe un rango de tramo | (a) **con comparadores**: «< 50.450», «≥ 50.450 y < 102.230,5», «≥ 102.230,5»; (b) notación de intervalo con coma decimal: «(−∞; 50.450)», «[50.450; 102.230,5)»; (c) en palabras: «menos de 50.450», «de 50.450 a menos de 102.230,5» | **(a)**: exacta en los bordes, corta y legible sin conocer la notación de intervalos. (b) exige el punto y coma, que confunde a quien viene de Excel; (c) es la más clara, pero alarga la columna |

## 8. Lo que se eleva (no es copy)

| # | Hallazgo | Por qué no cabe aquí | Propuesta |
|---|---|---|---|
| 8.1 | **Hosmer-Lemeshow «Falla» con muestras grandes** (7) | Decidir que el rechazo no cuenta, o sumar un criterio de brecha absoluta, cambia el veredicto de validación: es metodología (D-VAL-13…18) | Enmienda propia de validación: un criterio de materialidad (brecha absoluta o relativa) junto al p-valor, con cotejo contra fuentes |
| 8.2 | **Las decisiones humanas con motivo no viajan en el YAML** (5) | `to_yaml()` vuelca sólo el config. El motivo vive en el preámbulo del trail. La pantalla corre `nikodym.run` sin preámbulo y muestra «Sin decisiones». Que viajen exige un campo nuevo, en `governance` (INFRA, fuera del `config_hash`) o en otro lado: es un cambio de schema | Enmienda propia: las decisiones con motivo viajan en el YAML y la pantalla las muestra y las registra |
| 8.3 | **`anio_fiscal` entra como predictora sin aviso con partición por fecha** (6) | Detectar una columna derivada de la fecha es una regla nueva. Además comparte causa con el defecto previo de la enmienda TTD §7: la categoría 2009 no existe en Desarrollo, el motor le da WoE neutro en silencio y el bundle la rechaza | Enmienda propia que junte las dos cosas: una regla declarada para categorías no vistas en Desarrollo (motor y bundle iguales) y un aviso cuando una predictora cambia de dominio entre Desarrollo y OOT |

## 9. Estrategia de tests y controles negativos

Un test nacido rojo por cada D-CPY (los de §1–§6) y un control negativo por gate nuevo:

- quitar `fuera_de_modelo` del mapa (D-CPY-1);
- volver a `_COMPARISON_LABELS` solo (D-CPY-2);
- pintar con `str()` (D-CPY-3);
- devolver la etiqueta de OptBinning (D-CPY-4);
- inyectar una cifra con punto en una guía (D-CPY-5);
- omitir la brecha (D-CPY-6).

Guardrails: el bit a bit del preset F1 **sin ninguna diferencia**, porque ningún artefacto cambia,
y el `config_hash` `1063d6cf…` intacto. Los goldens del informe y de la pantalla que pinten estas
tablas se mueven y se revisan uno por uno.

## 13. Simplicidad (SDD-31) — obligatoria

- **Entrada mínima:** no cambia.
- **Qué NO se configura:** el formato de los números (es-CL, fijo), la forma de los rangos (la que
  elija Cami, fija) y los rótulos.
- **Presupuesto de perillas: CERO.**
- **Resumen por etapa:** mismas líneas, mejor escritas; la de Hosmer-Lemeshow suma la brecha.
- **Las cinco cifras:** idénticas.
