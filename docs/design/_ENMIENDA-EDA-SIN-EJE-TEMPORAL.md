# Enmienda — `eda` sin eje temporal: la tasa por período se declara «No evaluable», no mata la corrida

| Campo | Valor |
|---|---|
| **Tipo** | Enmienda corta a [`_ENMIENDA-SCORECARD-COMPLETO.md`](_ENMIENDA-SCORECARD-COMPLETO.md) (familia **D-SC**) y a [`31-simplicidad-y-flujo-guiado.md`](31-simplicidad-y-flujo-guiado.md) §8 |
| **Decisiones** | **D-SC-17** (el motor degrada) y **D-SC-18** (qué dicen las superficies) |
| **Módulos** | `nikodym.eda` (`default_rate`, `stability`, `card`, `figures`, `step`), `nikodym.report` (`builder`, `prose`), `nikodym.guided.summaries`, `nikodym.ui` (`serializers`, `jobs`), `web/` (`results-types`, `results-format`, `ResultsTab`), `docs_site/guias/analisis-exploratorio.md` |
| **Fase** | F1 (`eda` es estable) + F7 (UI) |
| **Estado** | **Propuesta** — pendiente del OK de Cami |
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
| 1 | `eda.default_rate.axis == "period"` | Es el valor de fábrica: el usuario no eligió un eje, lo heredó |
| 2 | `eda.default_rate.date_col is None` | Nadie declaró una fecha |
| 3 | El frame de análisis no tiene **ninguna** columna datetime | No hay nada que inferir (D-SC-3 ya probó esto mismo) |
| 4 | El usuario **no** particionó por cohorte | D-SC-3 ya cubre ese caso: el eje pasa a esa cohorte |

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
| `overall_rate` | la tasa global sobre la población elegible, **finita** | No necesita eje: `n_bad / n_eligible` sobre todo el frame. Es la cifra que el modelador sí quiere y que hoy pierde entera |
| `not_evaluable_reason` | `"sin_eje_temporal"` | La causa, en el molde de D-SC-2 |

**Regla de invariante, probada en los dos sentidos (igual que D-SC-2):** hay causa **si y sólo si**
`by_period` está vacía. Una tabla con filas y una causa, o una tabla vacía sin causa, son contrato
roto.

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

### 4.1 La card

`EdaCardSection` gana **un campo aditivo con default**, hermano del que D-SC-5 ya le dio a la
estabilidad:

```python
default_rate_not_evaluable_reason: Literal["sin_eje_temporal"] | None = None
```

Con la regla activa: `n_periods = 0`, `overall_default_rate` **finito** (la tasa global),
`stability_not_evaluable_reason = "sin_eje_temporal"`, `axis = "period"`, `axis_inferred = False`.

### 4.2 El resumen de la etapa (puerta guiada)

`_resumen_eda` hoy abre con «Tasa de malos por fecha de observación: 0 períodos, media 6,33 %», que
es absurdo. Con la causa presente dice, en dos líneas:

```text
Tasa de malos: 6,33 % sobre 4.000 operaciones elegibles
Tasa de malos en el tiempo: no evaluable (el archivo no trae columna de fecha ni cohorte declarada)
```

y **no** publica la tabla de la etapa (el `by_period` vacío ya la apaga). Las demás líneas del
resumen —columnas descritas, marcas de calidad— no cambian.

### 4.3 El informe

`_results_eda` gana su tercera rama. Hoy tiene dos —serie, y «un solo período: no hay serie»— y con
`n_periods = 0` caería en la segunda, que mentiría. La frase pasa a nombrar la causa:

> A continuación se reproducen el perfil por tramo de 7 variables descritas y la calidad de datos
> por columna. La tasa de incumplimiento no se pudo agrupar en el tiempo: el archivo no trae
> columna de fecha ni cohorte declarada.

El `ReportBuilder` **omite la tabla** `eda.default_rate.by_period` cuando el resultado declara su
causa: una tabla de sólo encabezados no es evidencia, y la prosa ya dice por qué no está. El gráfico
de la tasa ya se omite solo (`_chart_eda_default_rate` devuelve `None` con menos de dos filas sobre
eje temporal, y lo declara como omisión prescrita, no como degradación).

### 4.4 El panel de Resultados

La cifra «Agrupada por fecha de observación · 0 períodos» pasa a **«No evaluable»**, con su causa
bajo el bloque, en el mismo molde con que el panel ya pinta la causa de la estabilidad. El resto
del bloque —tasa global, columnas descritas, calidad, perfiles— se pinta igual. Los rótulos viven
en `EDA_DEFAULT_RATE_NOT_EVALUABLE_REASON_LABELS`, espejo gateado del diccionario de Python en los
dos sentidos, como los tres que ya existen.

### 4.5 El serializer

`_EDA_AUSENCIAS_DECLARADAS` **no cambia**: `overall_default_rate` sale finito y `stability_value`
sale `null` con su causa, que es justo lo que el guard de `_dump_card` exige hoy. El payload gana la
clave nueva de la card, `null` en toda corrida que hoy existe.

### 4.6 El copy de la opción y la guía

`ui/jobs.py`, opción `eda.default_rate.axis = "period"`, cierre del `motivo`:

> Necesita una columna de fecha en tu archivo. Si no la indicas, el motor usa la única columna de
> fecha que haya; si no hay ninguna y particionas por cohorte, agrupa por esa cohorte y lo deja
> registrado. Sin fecha ni cohorte, la tasa en el tiempo queda **sin evaluar** y la corrida sigue.

La opción **conserva** su estado `_EXIGE_OTRO_CAMPO` y su `exige: ("eda.default_rate.date_col",)`:
sigue siendo verdad que el análisis temporal necesita esa columna. Lo que deja de ser verdad es que
su ausencia detenga la corrida. `prueba` apunta al test nuevo, no a la línea vieja.

`docs_site/guias/analisis-exploratorio.md` cambia la frase equivalente y gana el caso en su tabla.

## 5. Estrategia de tests

Todos nacen rojos. Los dos primeros son **inversiones de tests existentes**, y se declaran aquí para
que el revisor no los lea como un oráculo debilitado: son el contrato que esta enmienda cambia.

| # | Test | Nace rojo porque |
|---|---|---|
| 1 | `test_eda_step.py::test_sin_fecha_ni_cohorte_declarada…` **invierte**: ya no espera `EdaError`, espera la corrida con causa | Hoy levanta |
| 2 | `test_eda_step.py::test_sin_config_de_data_tampoco_se_infiere` **invierte** igual | Hoy levanta |
| 3 | La tabla vacía y la causa van **juntas** (invariante, los dos sentidos) | El campo no existe |
| 4 | `overall_rate` degradado == la tasa global calculada a mano sobre el frame | La ruta no existe |
| 5 | La decisión `tasa_por_periodo`/`no_evaluable` está en el trail, **una sola vez** | No se emite |
| 6 | `stability` publica `sin_eje_temporal`, **no** `pocos_periodos_evaluables` | La causa no existe |
| 7 | `n_figures` no cuenta la figura de la tasa; sí cuenta los perfiles | Hoy la contaría vacía |
| 8 | Los cinco errores de §2 **siguen levantando** `EdaError` (control positivo, uno por fila) | — (nace verde: es el guardrail de que la regla no se derramó; se acompaña de su control negativo) |
| 9 | El informe de una corrida degradada: sin tabla de la tasa, con la frase de la causa, sin códigos internos | La rama no existe |
| 10 | El resumen de la etapa dice las dos líneas de §4.2 | La rama no existe |
| 11 | Espejo bidireccional del diccionario de rótulos nuevo (Python ↔ TS) | El diccionario no existe |
| 12 | `ResultsTab` pinta «No evaluable» y su causa (vitest, render estático) | La rama no existe |
| 13 | **Gate de aceptación end-to-end**: el pipeline F1 completo sobre un frame sin fecha con `partition="random"` termina `done` | Hoy termina `failed` en `eda` |
| 14 | **Bit a bit**: la proyección canónica (`_proyeccion_canonica.py`) de una corrida F1 del preset, antes y después, con 0 diferencias y `config_hash` `1063d6cf…` intacto | — (guardrail de aditividad) |

**Controles negativos (§6 del runbook), preespecificados:** (a) anular la rama de `_resolve_axis` y
ver rojo el test 13; (b) devolver una tabla con una fila `<NA>` en vez de vacía y ver rojo el test 3;
(c) quitar la rama de `stability` y ver rojo el test 6; (d) devolver la causa en un caso de §2
—`date_col` declarada y ausente— y ver rojo el test 8; (e) borrar una entrada del diccionario de
rótulos y ver rojo el test 11.

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
   vez, cinco controles positivos y un control negativo que inyecta la causa en un caso de error.
2. **Que la tabla vacía se cuele a una superficie que no la espera.** Medido: el serializer publica
   `[]` y `edaChartKind` devuelve `"none"` con cero filas; el gráfico del informe ya devuelve `None`
   con menos de dos filas. Lo único que hay que añadir es la omisión de la tabla en el builder
   (§4.3) y la rama de la prosa.
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
| 8.2 | Alcance de la degradación | (a) **sólo las cuatro condiciones de §2**; (b) además, `axis="cohort"` sin `cohort_col` degrada en vez de fallar | **(a)**: elegir «por cohorte» y no decir cuál es la columna es una contradicción del usuario, no una ausencia; degradarla escondería un config mal escrito |
| 8.3 | Qué hace la opción «Por la fecha de observación» en el formulario | (a) **sigue marcada «exige otro campo»**, con el motivo reescrito (§4.6); (b) deja de exigir nada, porque ya no detiene la corrida | **(a)**: la columna sigue haciendo falta **para el análisis**; retirar la marca le quitaría al modelador el aviso de que perderá el diagnóstico temporal |

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
