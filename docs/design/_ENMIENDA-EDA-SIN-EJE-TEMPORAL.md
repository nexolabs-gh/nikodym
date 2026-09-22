# Enmienda — `eda` sin eje temporal: la tasa por período se declara «No evaluable», no mata la corrida

| Campo | Valor |
|---|---|
| **Tipo** | Enmienda corta a [`_ENMIENDA-SCORECARD-COMPLETO.md`](_ENMIENDA-SCORECARD-COMPLETO.md) (familia **D-SC**) y a [`31-simplicidad-y-flujo-guiado.md`](31-simplicidad-y-flujo-guiado.md) §8 |
| **Decisiones** | **D-SC-17** (el motor degrada) y **D-SC-18** (qué dicen las superficies) |
| **Módulos** | `nikodym.eda` (`default_rate`, `stability`, `card`, `figures`, `step`), `nikodym.report` (`builder`, `prose`), `nikodym.guided.summaries`, `nikodym.ui` (`serializers`, `jobs`), `web/` (`results-types`, `results-format`, `ResultsTab`), `docs_site/guias/analisis-exploratorio.md` |
| **Fase** | F1 (`eda` es estable) + F7 (UI) |
| **Estado** | **APROBADA por Cami el 2026-09-22** (interactivo), con la recomendación de los tres puntos de su §8 |
| **Depende de** | D-SC-2 (causa de no evaluabilidad en `stability`), D-SC-3 (inferencia del eje), D-SC-5 (la card publica eje y causa), D-SIM-1/2, D-FLU-1, D-VIS, D-EXI |
| **Lo consumen** | la puerta guiada (`nikodym.Scorecard`), Resultados, el informe, la guía de análisis exploratorio |
| **Release** | Aditiva: convierte un error en un resultado declarado y no mueve ningún número con el mismo config ⇒ **minor**. Ningún `config_hash` de preset se mueve; presupuesto de perillas **cero** |
| **Autor / Fecha** | Claude Code (writer) / 2026-09-22 |

---

## 0. Por qué existe: el defecto medido

El criterio de completado que Cami fijó el 2026-09-22 exige que el writer corra la librería con tres
datasets distintos. El tercero —**UCI German Credit**, externo, 1.000 filas, sin ninguna columna de
fecha— **falla**. Y no es un caso raro del dataset externo: falla **cualquier** archivo sin columna
datetime que se particione al azar, que es exactamente lo que SDD-31 §8 declara soportado.

Medido hoy sobre `015c1bd` con la 1.19.0 del checkout, con un dataset **del propio paquete**
(`hipotecario_comportamiento`, 4.000 filas, 0 columnas datetime) y la entrada mínima de la puerta
guiada (`target=…`, `partition="random"`):

```text
Ejecución: fallida en «Análisis exploratorio»: La tasa de default por período requiere una columna
de fecha, y el archivo no trae ninguna; declárela en eda.default_rate.date_col, o particiona por
cohorte para que el eje la tome de ahí, o usa axis='cohort'.
Validación técnica: no corrió: la corrida falló antes
```

El error nace en `EdaStep._resolve_axis` (`src/nikodym/eda/step.py:180`), con su gemelo en
`DefaultRateAnalyzer` (`src/nikodym/eda/default_rate.py:222`). Tres hechos que fijan el alcance:

1. **El contrato ya prometía lo contrario.** SDD-31 §8, primer caso borde: «**Sin eje temporal en
   los datos:** el usuario declara `partition="random"` (D-OBL-5: no se siembra) y la estabilidad
   temporal queda “No evaluable” con causa (regla que ya existe en `eda`/`stability`)». La promesa
   presupone que la corrida **sigue**; hoy muere antes de llegar a `stability`.
2. **La puerta guiada lo dio por hecho.** El comentario de `guided/scorecard.py:487-489` dice, al
   construir `eda.default_rate` con `axis="period"` y sin `date_col`: «con partición aleatoria no
   hay ninguna y el motor lo declara “no evaluable” (SDD-31 §8)». El motor **no** lo declara. Es un
   defecto de la capa A (1.17.0), no de la capa C.
3. **El mecanismo ya existe y no hay que inventarlo.** `StabilityResult.not_evaluable_reason`
   (D-SC-2) publica tres causas con sus palabras en una fuente única
   (`NOT_EVALUABLE_REASON_LABELS`), espejada con gate en el front, leída por el panel, por la prosa
   del informe y por el resumen de la etapa. Esta enmienda **extiende ese mecanismo a la tasa**, no
   crea uno segundo. La misma corrección que la capa 3 de SCORECARD-COMPLETO ya hizo una vez: «hasta
   la capa 3 este caso levantaba `EdaError` y con él moría la corrida entera de `eda`»
   (`eda/stability.py:132-133`).

**Cami ya eligió la vía**, de forma interactiva el 2026-09-22, frente a (b) que la puerta apagara el
análisis con una hoja de config nueva y (c) que la puerta se detuviera antes de correr:
**(a) el motor degrada**, con su enmienda corta y en una sesión propia. Esta es esa enmienda.

## 1. Qué corrige de lo ya escrito

1. **SDD-31 §8 habla sólo de «la estabilidad temporal»** y por eso se leía como ya cumplido. El
   punto de fallo real está una capa antes: sin eje no hay **tasa por período**, y sin tasa no hay
   nada que la estabilidad pueda mirar. §8 gana la frase completa (§6 de esta enmienda).
2. **El mensaje del error enumera tres salidas y ninguna es la del usuario de referencia.**
   «Declárela en `eda.default_rate.date_col`, o particiona por cohorte, o usa `axis='cohort'`» le
   pide al modelador que conozca el árbol del config para ejecutar un archivo que no tiene fechas.
   Ninguna de las tres existe: el archivo no trae fecha ni cohorte. Es un callejón, no una guía.
3. **`eda` es la 2.ª etapa del pipeline** (tras `data`): el fallo no degrada un análisis, borra
   **nueve** etapas posteriores. El modelador no obtiene scorecard, ni PD, ni informe, ni ficha.
4. **El copy de la opción `eda.default_rate.axis` = «Por la fecha de observación» promete el
   comportamiento viejo** (`ui/jobs.py:1012-1016`): «Sin fecha ni cohorte, la corrida se detiene
   aquí», con `prueba: "eda/step.py:170"`. Deja de ser cierto y se reescribe (§4.6).
5. **La guía pública dice lo mismo** (`docs_site/guias/analisis-exploratorio.md:36`): «Sin fecha y
   sin cohorte, la corrida se detiene en…». Se reescribe, con su gate
   (`tests/unit/test_docs_analisis_exploratorio.py`).

## 2. Alcance: la regla nueva, y sólo ella

Esta enmienda **NO** cambia ningún otro error de `eda`. La regla nueva entra **si y sólo si** se
cumplen las cuatro condiciones a la vez:

| # | Condición | Por qué |
|---|---|---|
| 1 | `eda.default_rate.axis == "period"` | El eje **efectivo** del config. No se afirma nada sobre la intención: da igual que el valor venga del default o esté escrito a mano (la puerta guiada, de hecho, lo escribe) |
| 2 | `eda.default_rate.date_col is None` | `None` es el default **y significa «infiere»**. No es un hueco: es la regla de inferencia que el config declara |
| 3 | El frame de análisis no tiene **ninguna** columna datetime | La inferencia que el config pidió no tiene material (D-SC-3 ya probó esto mismo) |
| 4 | El usuario **no** particionó por cohorte | D-SC-3 ya cubre ese caso: el eje pasa a esa cohorte |

**Por qué `axis="period"` sin fecha se degrada y `axis="cohort"` sin `cohort_col` no**, sin apelar
a la intención de nadie y con una diferencia que el código puede leer: `date_col = None` es el
default **y activa una regla de inferencia** —«la única columna datetime», D-SC-3—, así que el
config está **completo** y lo que falta es el dato. `cohort_col = None` no activa ninguna
inferencia: el config nombra un eje y deja sin resolver la columna que ese eje exige, así que está
**incompleto**. Degradar el segundo escondería un config mal escrito; degradar el primero declara
que el archivo no da para el análisis.

⚠️ **La degradación no es silenciosa**, y esto importa cuando el `axis="period"` sí fue deliberado
(por código o desde el formulario): queda una decisión en el trail (§3.3), la card la declara, y el
resumen de la etapa, el informe y el panel la dicen en palabras (§4). En el formulario, el aviso de
que hace falta una columna de fecha se lee **antes de correr**, en el `help` de la opción
(§4.6/§8.3).

Todo lo demás **sigue siendo un error**, con su mensaje de hoy, y esta enmienda lo declara para que
la implementación no lo ablande de paso:

- `date_col` declarada y ausente del archivo → error (el usuario afirmó algo falso).
- `date_col` declarada y no datetime → error.
- Más de una columna datetime sin `date_col` → error (**ambigüedad**, no ausencia).
- `axis="cohort"` sin `cohort_col`, o con una `cohort_col` inexistente → error (eligió el eje a
  mano y no dijo cuál es la columna).
- Partición vacía, índice duplicado, target ausente → error.

**Criterio, en una frase:** se degrada la **ausencia** de eje cuando nadie eligió ninguno; nunca una
**contradicción** de lo que el usuario declaró.

## 3. D-SC-17 — el motor degrada: la tasa se publica «No evaluable» con su causa

### 3.1 El resultado

`DefaultRateResult` gana **un campo aditivo con default**, exactamente el molde de
`StabilityResult.not_evaluable_reason` (D-SC-2):

```python
DefaultRateNotEvaluableReason = Literal["sin_eje_temporal"]

DEFAULT_RATE_NOT_EVALUABLE_REASON_LABELS: Final[dict[str, str]] = {
    "sin_eje_temporal": "el archivo no trae columna de fecha ni cohorte declarada",
}

class DefaultRateResult(BaseModel):
    by_period: pd.DataFrame
    axis: EdaAxis
    overall_rate: float
    not_evaluable_reason: DefaultRateNotEvaluableReason | None = None   # aditivo
```

Cuando la regla entra, el resultado es:

| Campo | Valor | Por qué |
|---|---|---|
| `by_period` | **tabla vacía** con las seis columnas de `_RESULT_COLUMNS` y sus dtypes | No hay grupos. Una fila única con `period = <NA>` sería **inventar un eje** de un período: el informe y el panel la pintarían como una serie de un punto, que es otra cosa |
| `axis` | `"period"` | El eje **efectivo** es el configurado; no se agrupó por nada, así que no hay un eje distinto que declarar |
| `overall_rate` | la tasa global sobre la población elegible: `n_bad / n_eligible` sobre todo el frame, **con la misma regla que hoy** — `NaN` si no hay ninguna operación elegible | No necesita eje. Es la cifra que el modelador sí quiere y que hoy pierde entera |
| `not_evaluable_reason` | `"sin_eje_temporal"` | La causa, en el molde de D-SC-2 |

**El cruce «sin eje temporal **y** cero elegibles» no es un caso nuevo ni una excepción.** El
contrato vigente ya dice que sin operaciones elegibles la tasa global es `NaN` sin excepción
(`test_n_eligible_cero_produce_nan_sin_excepcion`), y la ruta degradada lo **conserva**: no inventa
una tasa ni convierte la ausencia en error. Las dos ausencias son independientes y se publican
juntas sin contradecirse:

| Superficie | Sin eje, con elegibles | Sin eje **y** sin elegibles |
|---|---|---|
| `EdaCardSection.overall_default_rate` | la tasa global | `NaN` |
| Serializer (`_EDA_AUSENCIAS_DECLARADAS`) | el número | `null` — es una de las **dos** ausencias que el guard ya permite hoy, sin tocarlo |
| `EdaStep.metrics` | la tasa | **omite** la clave; el canal D-GOB-2 no admite no finitos y la regla de hoy es omitir, no rellenar |
| Panel | `6,33 %` | «Sin operaciones elegibles» (copy que **ya existe**) |
| Resumen de la etapa | «Tasa de malos: 6,33 %» | «Tasa de malos: sin operaciones elegibles» |

**Regla de invariante, probada en los dos sentidos (igual que D-SC-2):** hay causa **si y sólo si**
`by_period` está vacía. Una tabla con filas y una causa, o una tabla vacía sin causa, son contrato
roto. La invariante se ancla en la tabla, **no** en `overall_rate`, precisamente porque `NaN` ahí
tiene su propio significado desde antes de esta enmienda.

**Bit a bit:** en la ruta normal `overall_rate` se sigue calculando con `_overall_rate(by_period)`,
byte por byte como hoy. El cálculo global vive **sólo** en la ruta degradada, que hoy no existe
porque levanta. Ninguna corrida que hoy termina cambia un solo número.

### 3.2 Quién decide

La decisión es de **`EdaStep._resolve_axis`**, no del analizador puro: es el único que ve el config
de `data` y por tanto la cohorte de partición, y es donde D-SC-3 ya decide lo mismo para el caso
hermano. `_resolve_axis` devuelve hoy `(config, axis_inferred)` y pasa a devolver un tercer dato:
si el eje quedó **ausente**. Con eje ausente el paso **no llama** a `DefaultRateAnalyzer.compute` y
construye el resultado degradado con un constructor público del módulo dueño del DTO
(`nikodym.eda.default_rate`), para que la invariante de §3.1 tenga una sola fuente.

🔴 **Las validaciones de entrada corren igual en las dos ramas.** Hoy `compute` es el **único**
punto que valida la población antes de calcular —frame no vacío, índice único, columna de target
presente (`_validate_non_empty_frame`, `_validate_unique_index`, `_validate_target_column`)—, así
que una rama que lo saltara aceptaría un índice duplicado o moriría con un `KeyError` incidental en
vez del `EdaError` del contrato. Los tres validadores se extraen a **un helper compartido**
(`_validar_poblacion(frame, target_col=)`) que **`compute` y el constructor degradado llaman antes
de bifurcar**. Las tres excepciones, sus mensajes y sus `loc` quedan **idénticos** en las dos
rutas, y §5 las prueba una por una **sobre la ruta degradada**, no sólo sobre la normal. No es un
detalle de implementación: es la razón por la que una corrida sin eje sigue siendo auditable.

`DefaultRateAnalyzer.compute` —API estable 1.x, usable sin `Study`— **conserva su contrato de hoy**:
llamado directamente con `axis="period"` sobre un frame sin fecha sigue levantando `EdaError`. No
sabe si hubo cohorte de partición, así que no puede aplicar la condición 4 de §2; ablandarlo ahí
degradaría también los casos que §2 declara errores.

### 3.3 Qué registra el trail

Una decisión auditable por corrida degradada, con el molde de `estabilidad_temporal`:

```json
{"regla": "tasa_por_periodo", "umbral": "una columna de fecha o una cohorte declarada",
 "valor": "sin eje temporal", "accion": "no_evaluable"}
```

Sale del mismo `AuditableMixin` del paso; no se inventa un canal nuevo.

### 3.4 La estabilidad, aguas abajo

`TemporalStabilityAnalyzer.assess` mira **primero** la causa de la tasa: con
`default_rate.not_evaluable_reason is not None` devuelve su propio resultado no evaluable con una
causa **nueva y propia**, `"sin_eje_temporal"`, añadida a `NotEvaluableReason` y a
`NOT_EVALUABLE_REASON_LABELS`:

```python
"sin_eje_temporal": "el archivo no trae un eje temporal que ordenar"
```

Sin esta rama el resultado caería por el camino de `pocos_periodos_evaluables` («menos de dos
períodos con observaciones suficientes»), que es **verdadero pero engañoso**: sugiere que faltan
datos cuando lo que falta es la columna. La invariante de D-SC-2 —«hay causa si y sólo si el
indicador configurado no es finito»— se mantiene: los tres indicadores salen `NaN`.

### 3.5 Las figuras

`_build_figure_specs` **no** emite la figura de la tasa cuando hay causa: hoy la emitiría con un
frame vacío y `n_figures` contaría una figura que nadie puede dibujar. Los perfiles univariados,
que no dependen del eje, se emiten como siempre.

### 3.6 Lo que NO cambia

`univariate`, `quality` y sus artefactos corren exactamente igual: no miran el eje. La corrida
continúa a `binning` con la población completa. **La degradación no oculta nada**: el modelador
pierde el diagnóstico temporal —que su archivo no permite— y conserva todo lo demás.

## 4. D-SC-18 — qué dice cada superficie

Copy en español, de las fuentes de rótulos que ya existen, sin identificadores del motor
(gate `test_report_codigos_internos`).

### 4.0 Censo completo de consumidores — la lista, no los ejemplos

Las tres pasadas de revisión de este documento encontraron, cada una, **un consumidor que el
diseño no había mirado**. La respuesta no es parchear el tercero: es censar los dieciocho y decir
de cada uno qué pasa. Medido sobre el árbol, no recordado.

| # | Consumidor | Qué le pasa con el resultado degradado |
|---|---|---|
| 1 | `eda/stability.py::assess` | **Cambia** (§3.4): causa propia `sin_eje_temporal` en vez de `pocos_periodos_evaluables` |
| 2 | `eda/figures.py::_build_figure_specs` | **Cambia** (§3.5): no emite la figura de la tasa |
| 3 | `eda/step.py::_build_eda_card` | **Cambia** (§4.1): publica el campo nuevo |
| 4 | `eda/step.py::metrics` | Sin cambio: las tres métricas se siguen publicando; `NaN` se omite por la regla de hoy (§3.1) |
| 5 | `guided/summaries.py::_resumen_eda` | **Cambia** (§4.2): dos líneas nuevas, sin tabla |
| 6 | `report/builder.py::_collect_tables` | **Cambia** (§4.3): omite la tabla vacía |
| 7 | `report/prose.py::_eda_context` (vía `context_body`) | 🔴 **Cambia** (§4.3): hoy diría «en 0 períodos» y «un solo período» |
| 8 | `report/prose.py::_results_eda` | **Cambia** (§4.3): rama nueva con la causa |
| 9 | `report/renderer.py::_chart_eda_default_rate` | **Cambia** (§4.3): lookup tolerante; ya devolvía `None` con menos de dos filas |
| 10 | `report/renderer.py::_chart_eda_profiles` | Sin cambio: lee las tablas de perfiles, no el eje |
| 11 | `report/document.py` (`KEY_TABLES`, `max_visible_rows`) | Sin cambio: ya filtra por presencia de la clave |
| 12 | `ui/serializers.py::_dump_card` | Sin cambio (§4.5): el guard sigue cumpliéndose |
| 13 | `ui/serializers.py::_eda_default_rate` | Sin cambio: `rows = []`, ventana con `total_periods = 0` |
| 14 | `ui/runs.py::_save_eda_default_rate` | Sin cambio: sólo escribe el CSV si hubo recorte |
| 15 | `ui/jobs.py` (opción del eje) | **Cambia** (§4.6): estado y `help` |
| 16 | `web/src/lib/results-types.ts::EdaResult` | **Cambia** (§4.1): campo nuevo, golden bidireccional |
| 17 | `web/src/lib/results-format.ts` (`edaChartKind`, `edaRatePoints`, `edaRateWindow`, `edaStabilitySummary`, rótulos) | **Cambia** sólo en rótulos (§4.4); las tres primeras ya devuelven vacío con cero filas |
| 18 | `web/src/components/ResultsTab.tsx` | **Cambia** (§4.4): una cifra, una nota |

Fuera de la lista, `nikodym.testing.metrics` exige del dominio `eda` tres nombres de métrica y los
tres siguen existiendo. **Ningún paso del pipeline posterior a `eda` consume `("eda", …)`** salvo
`report` (§7-3).

### 4.1 La card

`EdaCardSection` gana **un campo aditivo con default**, hermano del que D-SC-5 ya le dio a la
estabilidad:

```python
default_rate_not_evaluable_reason: Literal["sin_eje_temporal"] | None = None
```

Con la regla activa: `n_periods = 0`, `overall_default_rate` = la tasa global (`NaN` sólo si no
hay elegibles), `stability_not_evaluable_reason = "sin_eje_temporal"`, `axis = "period"`,
`axis_inferred = False`.

⚠️ El campo nuevo **mueve dos goldens que ya existen** y los dos son bidireccionales, así que no
hay forma de olvidarlos: `test_vocabulario_en_pantalla::test_el_tipo_eda_result_espeja_la_card_y_sus_tres_tablas`
exige que `EdaResult` de `results-types.ts` declare los campos de `EdaCardSection` **en su orden**,
y el fixture `schema.json`/`eda.fixture.ts` del front se regenera.

### 4.2 El resumen de la etapa (puerta guiada)

`_resumen_eda` hoy abre con «Tasa de malos por fecha de observación: 0 períodos, media 6,33 %», que
es absurdo. Con la causa presente dice, en dos líneas:

```text
Tasa de malos: 6,33 %
Tasa de malos en el tiempo: no evaluable (el archivo no trae columna de fecha ni cohorte declarada)
```

y **no** publica la tabla de la etapa (el `by_period` vacío ya la apaga). Las demás líneas del
resumen —columnas descritas, marcas de calidad— no cambian. Sin operaciones elegibles la primera
línea dice «Tasa de malos: sin operaciones elegibles», en vez de un porcentaje.

🔴 **La línea NO lleva denominador, y es deliberado.** El único denominador que `eda` publica hoy
—`n_eligible`— vive en las filas de `by_period`, y la ruta degradada no las tiene. Escribirlo
exigiría una de dos cosas, y las dos están vetadas: recalcularlo en el resumen rompería D-FLU-2
(«el resumen no calcula nada») y duplicaría la regla de elegibilidad y la selección de
`analysis_partition`; y añadir `n_total`/`n_eligible`/`n_bad` a `DefaultRateResult` pondría una
**segunda fuente** del número que `by_period` ya suma en la ruta normal, que es justo lo que
RUNBOOK §12.2-3 prohíbe. Además el denominador no sería el que el lector supone: `eda` describe de
fábrica **sólo la partición de desarrollo** (`analysis_partition="desarrollo"`), no el archivo, de
modo que la cifra no coincidiría con las «1.000 filas» del resumen de datos. Quien quiera el
tamaño lo tiene una etapa antes, dicho con su población correcta.

### 4.3 El informe

🔴 **Son DOS las funciones de prosa que leen la card de `eda`, no una.** Además de `_results_eda`,
`_eda_context` alimenta el `context_body()` del capítulo «Contexto del modelo y de la cartera», y
con el resultado degradado publicaría hoy dos frases falsas dentro del **mismo documento** que ya
trae la explicación correcta:

| Hoy diría (con `n_periods = 0`, `axis = "period"`) | Por qué es falso |
|---|---|
| «…la tasa se agrupó **por fecha de observación en 0 períodos**…» (`prose.py:1439`) | No se agrupó por nada |
| «Con **un solo período** con observaciones no hay serie temporal que graficar: la tasa **se reproduce en la tabla** y no como figura» (`prose.py:1456`, rama `periods < 2 and axis != "cohort"`) | No hay un período, hay cero; y no hay tabla en la que reproducirla |

Con la causa presente, `_eda_context`: **omite** la frase de agrupación y **omite** la rama de «un
solo período», y en su lugar publica la causa en palabras, una sola vez. La frase de la tasa
observada y la de las columnas descritas se conservan tal cual.

`_results_eda` gana su tercera rama. Hoy tiene dos —serie, y «un solo período: no hay serie»— y con
`n_periods = 0` caería en la segunda, que mentiría. La frase pasa a nombrar la causa:

> A continuación se reproducen el perfil por tramo de 7 variables descritas y la calidad de datos
> por columna. La tasa de incumplimiento no se pudo agrupar en el tiempo: el archivo no trae
> columna de fecha ni cohorte declarada.

El `ReportBuilder` **omite la tabla** `eda.default_rate.by_period` cuando el resultado declara su
causa: una tabla de sólo encabezados no es evidencia, y la prosa ya dice por qué no está. Medido
sobre el renderer, la omisión es segura en tres de los cuatro consumidores y exige una línea en el
cuarto:

| Consumidor | Con la tabla omitida |
|---|---|
| Cuerpo del capítulo (`KEY_TABLES`) | Ya filtra por `key in bundle.tables`: no la pide |
| Anexo de tablas | Itera `bundle.tables`: no la ve |
| `max_visible_rows` / tope de 1.000 | No se invoca sin tabla |
| `_chart_eda_default_rate` | 🔴 Hoy hace `bundle.tables["eda.default_rate.by_period"]` **por índice**: pasa a `.get(...)` y devuelve `None` si falta, que es el mismo `None` que ya devuelve con menos de dos filas sobre eje temporal —omisión prescrita por D-SC-5 (b), no degradación— |

### 4.4 El panel de Resultados

Tres cambios acotados, ninguno estructural:

1. La cifra `Agrupada por fecha de observación · 0 períodos` pasa a rótulo **«Agrupada en el
   tiempo»** y valor **«No evaluable»**.
2. Una nota bajo las cifras, hermana de la que ya existe para el eje inferido (D-SC-3): «La tasa
   no se pudo agrupar en el tiempo: el archivo no trae columna de fecha ni cohorte declarada. El
   resto del análisis exploratorio corrió completo y la decisión queda registrada en el trail de
   la corrida.»
3. El bloque «Estabilidad temporal de la tasa» **no cambia de forma**: ya tiene su rama
   `not_evaluable` («No evaluable: {causa}. El indicador configurado es {indicador}.») y sólo
   necesita el rótulo de la causa nueva en `EDA_NOT_EVALUABLE_REASON_LABELS`.

Las secciones que dependen de la tabla —gráfico, «Ver la tasa …», ventana de recorte— ya están
guardadas por `edaPoints.length > 0` y `edaKind !== "none"`, y con cero filas no se pintan. Los
rótulos de la causa nueva de la tasa viven en `EDA_DEFAULT_RATE_NOT_EVALUABLE_REASON_LABELS`,
espejo gateado del diccionario de Python en los dos sentidos, como los tres que ya existen.

### 4.5 El serializer

`_EDA_AUSENCIAS_DECLARADAS` **no cambia**: `overall_default_rate` sale finito y `stability_value`
sale `null` con su causa, que es justo lo que el guard de `_dump_card` exige hoy. El payload gana la
clave nueva de la card, `null` en toda corrida que hoy existe.

### 4.6 El copy de la opción y la guía

🔴 **El estado de la opción deja de ser verdad y hay que moverlo.** `_EXIGE_OTRO_CAMPO` está
definido en el catálogo como «el motor la tiene, pero **elegirla sola no basta**: exige que
declares otro campo del config, y **hasta que lo declares el config no se construye** (D-EXI-2)».
Después de D-SC-17 el config se construye **y la corrida termina**, así que dejar la marca sería
publicar una falsedad con el gate en verde —exactamente lo que D-ABA-5 persigue—, y además D-ABA-3
sólo prohíbe ofrecer como elegible «algo que el motor rechaza», cosa que el motor deja de hacer.

Por eso la opción `eda.default_rate.axis = "period"` pasa a **`_DISPONIBLE`** y, por el gate
`test_una_opcion_disponible_no_lleva_motivo_ni_prueba`, **retira `motivo`, `prueba` y `exige`**. El
aviso no se pierde: se mueve al `help`, que toda opción lleva y el formulario pinta:

> Agrupa por la fecha en que se observó cada operación, por mes, trimestre o año, y permite evaluar
> si la tasa se deteriora en el tiempo. Es la opción de fábrica. Si no indicas la columna, el motor
> usa la única columna de fecha que haya; si tu archivo no trae ninguna y particionas por cohorte,
> agrupa por esa cohorte y lo deja registrado. **Sin fecha ni cohorte, la tasa en el tiempo queda
> sin evaluar —la corrida sigue y el resto del análisis se hace igual—.**

La opción **`"cohort"` no se toca**: sigue en `_EXIGE_OTRO_CAMPO` con su `exige`, porque §2 deja ese
caso como error y la marca sigue siendo cierta.

`docs_site/guias/analisis-exploratorio.md` cambia la frase equivalente («Sin fecha y sin cohorte, la
corrida se detiene en…») y gana el caso en su tabla, con su gate
(`tests/unit/test_docs_analisis_exploratorio.py`).

## 5. Estrategia de tests

Todos nacen rojos. Los dos primeros son **inversiones de tests existentes**, y se declaran aquí para
que el revisor no los lea como un oráculo debilitado: son el contrato que esta enmienda cambia.

| # | Test | Nace rojo porque |
|---|---|---|
| 1 | `test_eda_step.py::test_sin_fecha_ni_cohorte_declarada…` **invierte**: ya no espera `EdaError`, espera la corrida con causa | Hoy levanta |
| 2 | `test_eda_step.py::test_sin_config_de_data_tampoco_se_infiere` **invierte** igual | Hoy levanta |
| 3 | La tabla vacía y la causa van **juntas** (invariante, los dos sentidos) | El campo no existe |
| 4 | `overall_rate` degradado == la tasa global calculada a mano sobre el frame | La ruta no existe |
| 4b | **Cruce**: sin eje **y** sin operaciones elegibles → `overall_rate` `NaN`, causa presente, serializer `null`, `EdaStep.metrics` **sin** la clave, y el resumen dice «sin operaciones elegibles» | La ruta no existe |
| 5 | La decisión `tasa_por_periodo`/`no_evaluable` está en el trail, **una sola vez** | No se emite |
| 6 | `stability` publica `sin_eje_temporal`, **no** `pocos_periodos_evaluables` | La causa no existe |
| 7 | `n_figures` no cuenta la figura de la tasa; sí cuenta los perfiles | Hoy la contaría vacía |
| 8 | Los errores de §2 **siguen levantando** `EdaError`, **uno por fila y sin agrupar**: `date_col` ausente del archivo · `date_col` no datetime · dos columnas datetime sin `date_col` · `axis="cohort"` sin `cohort_col` · `axis="cohort"` con `cohort_col` inexistente | — (nacen verdes: son el guardrail de que la regla no se derramó, y llevan su control negativo (d)) |
| 8b | **Sobre la ruta degradada**, tres tests independientes: frame vacío, índice duplicado y target ausente levantan el **mismo** `EdaError` que por la ruta normal, con el mismo mensaje | Hoy esos casos nunca llegan a la rama, que no existe |
| 9 | El informe **completo** de una corrida degradada, medido sobre el HTML: aparece la causa **una sola vez**, no aparece la tabla de la tasa, y **no aparece ninguna** de las cadenas «0 períodos», «se agrupó» ni «un solo período»; sin códigos internos. Se repite sobre el cruce sin operaciones elegibles | Las dos ramas no existen, y hoy el documento diría dos frases falsas |
| 10 | El resumen de la etapa dice las dos líneas de §4.2 | La rama no existe |
| 11 | Espejo bidireccional del diccionario de rótulos nuevo (Python ↔ TS) | El diccionario no existe |
| 12 | `ResultsTab` pinta «No evaluable» y su causa (vitest, render estático) | La rama no existe |
| 12b | La opción `axis="period"` del catálogo es `_DISPONIBLE` **sin** `motivo`, `prueba` ni `exige`, y la opción `"cohort"` **conserva** `_EXIGE_OTRO_CAMPO` con su `exige` | Hoy las dos llevan la marca |
| 13 | **Gate de aceptación end-to-end**: el pipeline F1 completo sobre un frame sin fecha con `partition="random"` termina `done` | Hoy termina `failed` en `eda` |
| 14 | **Bit a bit**: la proyección canónica (`_proyeccion_canonica.py`) de una corrida F1 del preset, antes y después. Las **únicas** diferencias admitidas son las **dos claves nuevas, y sólo con valor `None`** (ver abajo); todo lo demás, idéntico, y `config_hash` `1063d6cf…` intacto | — (guardrail de aditividad) |

**Censo de goldens que la capa mueve** (medido, no supuesto; es el punto donde una capa se pasa de
hora): `EdaResult` en `results-types.ts` (espejo por orden de los campos de la card), el fixture
`schema.json` y el bundle del front, `eda.fixture.ts`, y el `help`/estado de la opción en
`tests/unit/test_jobs_abanico.py`. **`tests/fixtures/option_effect_oracles.txt` NO se mueve**: su
fila `eda.default_rate.axis` cita tres tests por nombre y **ninguno de los dos que esta capa
invierte** está entre ellos (medido sobre la fila 76). Si al implementar hiciera falta renombrar
uno de los citados, la fila se actualiza en el mismo commit.

**Qué significa exactamente «bit a bit» con dos campos aditivos (test 14).** `proyeccion_canonica`
vuelca cada `BaseModel` con `model_dump()`, **campos con default incluidos**, así que dos campos
nuevos aparecen en la proyección de **toda** corrida, también las normales: exigir «cero
diferencias» contra `015c1bd` sería un gate imposible que sólo se podría cumplir debilitando el
oráculo. El criterio —el mismo que S17 aplicó y dejó escrito («cero diferencias… sólo aparecen las
dos claves nuevas»)— es:

1. La lista de diferencias entre la proyección de `015c1bd` y la del árbol nuevo **es exactamente**
   `eda.default_rate.not_evaluable_reason` y `eda.eda_card.default_rate_not_evaluable_reason`.
2. Las dos aparecen **ausentes antes y `None` después**. Una clave nueva con valor no nulo en una
   corrida normal es un rojo, no una diferencia de esquema.
3. Cualquier otra diferencia —un `float` que cambie un bit, un hash de tabla, una clave más— es un
   rojo y detiene la capa.
4. El `config_hash` del preset no se mueve (`1063d6cf…`), y la comparación **estricta** (cero
   diferencias, sin excepciones) se sigue exigiendo entre dos corridas **del mismo árbol**: las
   paridades `run()` vs `run(until=)+resume()` y las dos puertas no admiten ninguna.

La proyección de referencia de `015c1bd` se mide y se guarda **antes** de tocar código, y la
evidencia del cierre publica la lista literal de diferencias, no un «sin cambios».

**Controles negativos (§6 del runbook), preespecificados:** (a) anular la rama de `_resolve_axis` y
ver rojo el test 13; (b) devolver una tabla con una fila `<NA>` en vez de vacía y ver rojo el test 3;
(c) quitar la rama de `stability` y ver rojo el test 6; (d) devolver la causa en un caso de §2
—`date_col` declarada y ausente— y ver rojo el test 8; (e) borrar una entrada del diccionario de
rótulos y ver rojo el test 11; (f) **saltar `_validar_poblacion` en la rama degradada** y ver rojo
el test 8b; (g) rellenar `overall_rate` con `0.0` en vez de `NaN` sin elegibles y ver rojo el 4b;
(h) **dejar `_eda_context` sin su rama** —es decir, el código de hoy— y ver rojo el test 9 por las
cadenas «0 períodos» y «un solo período».

## 6. Qué cambia en los documentos vigentes

- **SDD-31 §8**, primer caso borde, pasa a: «**Sin eje temporal en los datos:** el usuario declara
  `partition="random"` (D-OBL-5: no se siembra); la tasa de incumplimiento **por período** y la
  estabilidad temporal quedan “No evaluable” con causa y **la corrida sigue** (D-SC-17/18); el resto
  del análisis exploratorio —perfiles y calidad— corre completo».
- **`_ENMIENDA-SCORECARD-COMPLETO.md`** gana D-SC-17 y D-SC-18 en su registro de decisiones, con la
  nota de que D-SC-2 y D-SC-3 no se reabren: se extienden.
- **`DECISIONES-VIGENTES.md`** gana la fila de esta enmienda.
- **`_ENMIENDA-FLUJO-GUIADO-SCORECARD.md`** gana una anotación: el comentario de
  `guided/scorecard.py` que daba por hecho esta regla queda cumplido, sin cambiar la puerta.

## 7. Riesgos

1. **Que la degradación tape un error real del usuario.** Mitigado por §2: cuatro condiciones a la
   vez, cinco controles positivos y un control negativo (d) que inyecta la causa en un caso de
   error. El caso incómodo —alguien elige «por la fecha de observación» **a conciencia** y su
   archivo no trae fecha— se degrada igual, y por diseño: no hay dato con que hacer otra cosa. Lo
   que lo hace aceptable es que nada queda callado (trail, card, resumen, informe y panel lo dicen)
   y que el formulario lo advierte **antes** de correr, en el `help` de la opción (§4.6).
1b. **Que la rama nueva se salte una validación de población.** Es el riesgo más caro y está
   cerrado en §3.2: un solo helper, llamado por las dos ramas antes de bifurcar, con tres tests
   sobre la rama degradada (8b) y su control negativo (f).
2. **Que la tabla vacía se cuele a una superficie que no la espera.** Censado consumidor a
   consumidor: el serializer publica `rows = []` y `default_rate_window = {total_periods: 0,
   truncated: false}`; el CSV de la interfaz sólo se escribe **si hubo recorte**, y con cero filas
   no lo hay; en el front `edaChartKind` da `"none"`, `edaRatePoints` da `[]` y las dos secciones
   del panel que dependen de ellos ya están guardadas por `length > 0`. En el informe, la tabla
   **se omite** y el único acceso por índice se hace tolerante (§4.3). Lo que sí hay que escribir
   es la rama de la prosa, la del resumen de la etapa y la del panel.
3. **Que la corrida siga y falle más adelante por la misma carencia.** Censado: de las nueve etapas
   que siguen a `eda` en el pipeline F1, la única que lee `("eda", "default_rate")` es `report`
   (`ReportBuilder._collect_tables`), y §4.3 la cubre. Fuera del pipeline lo leen el resumen de la
   etapa (`guided/summaries.py:576`) y el volcado CSV de la interfaz
   (`ui/runs.py::_save_eda_default_rate`, que sólo escribe si la respuesta **se recortó**: con cero
   filas no se recorta nada). `nikodym.testing.metrics` exige del dominio `eda` las tres métricas
   `overall_default_rate`, `n_periods` y `stability_flagged`, y las tres se siguen publicando
   —finita, `0` y `0.0`—. Lo verifica además el test 13 de punta a punta.

## 8. Lo que Cami decide

| # | Decisión | Opciones | Recomendación |
|---|---|---|---|
| 8.1 | La forma del resultado degradado | (a) **tabla vacía + causa**, y `overall_rate` finito sobre toda la población; (b) una fila única `<NA>` con toda la población; (c) tabla vacía y `overall_rate` también `NaN` | **(a)**: (b) inventa un período que no existe y lo pinta como serie de un punto; (c) le quita al modelador la única cifra de la etapa que su archivo sí permite calcular |
| 8.2 | Alcance de la degradación | (a) **sólo las cuatro condiciones de §2**, sin mirar si el `axis="period"` fue deliberado; (b) además, `axis="cohort"` sin `cohort_col` degrada en vez de fallar; (c) degradar sólo si el config **no** escribió `axis` a mano | **(a)**: con `date_col=None` el config está completo y pide inferir, así que lo que falta es el dato; con `cohort_col=None` el config está incompleto y degradarlo escondería un error de escritura. (c) no es implementable sin inventar procedencia —la puerta guiada **escribe** `axis: period`— y dejaría fuera justo el caso que hay que arreglar |
| 8.3 | Qué hace la opción «Por la fecha de observación» en el formulario | (a) **pasa a «disponible»** y el aviso se mueve al `help` (§4.6); (b) conserva la marca «exige otro campo», enmendando la definición del estado en el catálogo; (c) un estado nuevo, «degrada sin el otro campo» | **(a)**: la definición vigente del estado dice «hasta que lo declares **el config no se construye**», y eso deja de ser verdad; mantenerla sería publicar una falsedad con los gates en verde. El aviso no se pierde —`help` lo lleva y el formulario lo pinta—, y la opción `"cohort"` conserva su marca porque ahí sí sigue siendo cierta. (c) añade vocabulario a D-ABA/D-EXI por un solo caso |

## 8bis. La revisión adversarial de este documento: tope, criterio y qué encontró

**Tope declarado antes de lanzar: tres pasadas** de Codex sobre el HEAD commiteado, con base
`015c1bd`. **Criterio de parada:** se detiene al alcanzar el tope o cuando una pasada deje de
traer un consumidor o un contrato nuevo. Las tres trajeron algo real y distinto, todo verificado
contra el árbol antes de absorberlo:

| Pasada | Hallazgos | Qué cambió |
|---|---|---|
| 1 | `overall_rate` prometido finito contra un contrato que devuelve `NaN`; la rama degradada se saltaba los guards de población; `axis="period"` no demuestra intención | §3.1 (cruce sin elegibles), §3.2 (helper compartido), §2 (criterio medible) |
| 2 | El resumen prometía un denominador que ningún artefacto conserva; el gate «cero diferencias» era imposible con campos aditivos | §4.2 (copy sin denominador, con su razón), §5 (criterio real del bit a bit) |
| 3 | `_eda_context` publicaría «0 períodos» y «un solo período» en el mismo informe que trae la causa | §4.3 (dos funciones de prosa, no una), test 9 endurecido |

**Las tres son el mismo defecto de método**: el diseño miraba consumidores de a uno. Por eso, en
vez de parchear el tercero, se censaron **los dieciocho** (§4.0) y se dice de cada uno qué le pasa.
Ese censo, y dos cambios que salieron de él —el estado de la opción del catálogo (§4.6) y el censo
de goldens (§5)— entran **después** de la tercera pasada y **no llevan pasada propia**: el tope
está alcanzado y se declara aquí, como en S12 y S18. La implementación abre con una pasada sobre
su propio rango de código, que es donde el revisor rinde más.

## 9. Lo que NO entra en esta enmienda

- Inferir un eje de una columna de texto con pinta de fecha. El motor no adivina tipos.
- Ofrecer `date` o `cohort` en la puerta guiada cuando el archivo no los tiene: no hay nada que
  ofrecer.
- Tocar `DefaultRateAnalyzer.compute` como API pública (§3.2).
- Cambiar la figura, la tabla o el copy de ninguna corrida **con** eje temporal.

## 13. Simplicidad (SDD-31) — obligatoria

- **Entrada mínima:** no cambia. La puerta guiada sigue pidiendo `target` y la estrategia de
  muestras; con `partition="random"` deja de hacer falta **nada más** para que la corrida termine,
  que es justamente el punto.
- **Qué NO se configura:** la degradación **no es opcional**. No hay un flag «permitir que la tasa
  no sea evaluable»: sin eje no hay eje, y un flag pondría al modelador a decidir sobre un hecho
  del archivo, no sobre una política. Tampoco se configura la causa, ni su texto: viven en el
  diccionario de rótulos, que es una constante con espejo gateado.
- **Campos esenciales:** sin cambios. `eda` declara **cero** esenciales y lo dice en pantalla
  (D-FLU, capa B); esta enmienda no le añade ninguno.
- **Presupuesto de perillas: CERO.** No entra ninguna hoja de config nueva. Las perillas de las doce
  secciones del scorecard siguen en **413**; el golden de `test_simplicidad_scorecard.py` no se
  mueve. Los dos campos nuevos son **de resultado** (`DefaultRateResult`, `EdaCardSection`), no de
  config, y no aparecen en el formulario.
- **Resumen por etapa:** el de `eda` gana **una** línea y pierde otra (§4.2); sigue en su rango de
  3–8 líneas. Su tabla de decisión no cambia. No admite decisiones humanas nuevas.
- **Notebook mínimo:** sin cambios: **15 líneas de usuario**, 5 conceptos. Lo que cambia es que
  ahora el mismo notebook corre sobre un archivo sin fechas.
- **Las cinco cifras (D-SIM-11):** medidas el 2026-09-22 sobre `015c1bd` y **objetivo: idénticas**.
  Líneas de usuario **15** → 15 · esenciales visibles **35**, máx. 6 → 35, máx. 6 · perillas
  **413** → 413 · conceptos **5** → 5 · segundos al primer resumen ≈ **1 s** → ≈ 1 s. Esta enmienda
  no gana simplicidad **midiendo**: la gana **existiendo**, porque hoy la cifra real de un archivo
  sin fechas es que la corrida no termina.
