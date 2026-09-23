# Enmienda — el análisis exploratorio nunca detiene la corrida

| Campo | Valor |
|---|---|
| **Tipo** | Enmienda corta a [`_ENMIENDA-EDA-SIN-EJE-TEMPORAL.md`](_ENMIENDA-EDA-SIN-EJE-TEMPORAL.md) (la **generaliza** y deroga su §2 «los cinco errores quedan intactos» y su §8.2), a [`27-eda.md`](27-eda.md) §8 y a [`31-simplicidad-y-flujo-guiado.md`](31-simplicidad-y-flujo-guiado.md) §8 |
| **Decisiones** | **D-SC-19** (la regla: `eda` nunca detiene la corrida) y **D-SC-20** (qué dicen las superficies de un sub-análisis que falló) |
| **Módulos** | `nikodym.eda` (`step`, `default_rate`, `stability`, `card`), `nikodym.guided.summaries`, `nikodym.report` (`builder`, `prose`), `web/` (`results-types`, `results-format`, `ResultsTab`), `docs_site/guias/analisis-exploratorio.md` |
| **Fase** | F1 |
| **Estado** | **APROBADA por Cami el 2026-09-23** (interactivo), con la recomendación de sus dos decisiones de §5; tres pasadas de Codex absorbidas. **Implementada el 2026-09-23** en la misma sesión; lo que el código midió distinto de lo escrito, en §7 |
| **Depende de** | D-SC-17/18 (el mecanismo de «no evaluable con causa» que esta enmienda reutiliza), D-SIM-1/2, D-FLU |
| **Release** | Aditiva para todo lo que hoy termina: la regla **sólo** entra donde `eda` hoy levanta. Ningún `config_hash` se mueve ⇒ **minor** |
| **Autor / Fecha** | Claude Code (writer) / 2026-09-23 |

---

## 0. Por qué existe: la corrección de ayer fue demasiado estrecha

D-SC-17 degradó **una** condición —sin fecha y sin cohorte— y dejó expresamente como errores otras
cinco. Cami lo cuestionó al día siguiente («no puede morir por un error tan chico») y la medición le
da la razón. Sobre `bda7f20`, una cartera de 4.000 filas con **dos columnas de fecha**
(`fecha_origen`, `fecha_corte`) —lo más normal en un archivo de banco— y la entrada mínima de la
puerta guiada con `partition="random"`:

```text
Ejecución: fallida en «Análisis exploratorio»: La tasa de default por período encontró más de una
columna datetime plausible; declare eda.default_rate.date_col explícitamente. Columnas detectadas:
'fecha_origen', 'fecha_corte'.
```

La corrida murió en 3,5 s, en la **segunda** etapa, y con ella se perdieron binning, selección,
modelo, scorecard, calibración, desempeño, estabilidad, validación e informe.

### 0.1 La causa de fondo, medida

- **El orquestador trata toda etapa como bloqueante**: `Study.run` recorre los pasos y cualquier
  excepción de cualquiera termina la corrida (`core/study.py:445-452`).
- **`eda` es puramente descriptivo y ninguna etapa del modelo lo necesita.** Censado en
  `_ENMIENDA-EDA-SIN-EJE-TEMPORAL.md` §4.0: de las nueve etapas posteriores sólo `report` lee
  `("eda", …)`.
- **Y aun así `eda` tiene 20 puntos donde levanta** (`grep -c "raise "` sobre `src/nikodym/eda/`):
  11 en la tasa por período, 5 en el paso, 2 en los perfiles, 1 en la estabilidad y 1 en el paquete.

La enmienda de ayer defendió que las «contradicciones del config» debían seguir siendo fatales. Para
una etapa de la que depende el modelo eso es correcto; para una **descriptiva** es desproporcionado:
un error ahí debería costar un gráfico, no el modelo. Si el problema es un dato roto de verdad, lo
detiene la primera etapa que **sí** lo necesita —binning—, con el error que le corresponde.

## 1. D-SC-19 — la regla

**`EdaStep.execute` nunca levanta.** Siempre publica sus seis artefactos (`default_rate`,
`stability`, `univariate`, `quality`, `figures`, `eda_card`), y cada **sub-análisis** falla por
separado:

| Sub-análisis | Si falla, publica | Y declara |
|---|---|---|
| Preparación (frame, etiquetas, partición de análisis, muestreo, columnas a perfilar) | **los cuatro siguientes degradados** con la misma causa: sin población no hay nada que describir | una causa por cada sub-análisis |
| Tasa por período | la tasa degradada de D-SC-17 —tabla vacía con sus seis columnas— con la causa **nueva** `no_calculable`; la estabilidad, entonces, no evaluable con la causa **nueva** `tasa_no_calculable` (no hay tasa que mirar) | la causa en palabras |
| Estabilidad, sola | **la tasa se conserva entera** —tabla, figura y cifras—; la estabilidad sale no evaluable con la causa **nueva** `no_calculable` | la causa. Es una unidad de fallo **propia**: atribuir su falla a la tasa haría perder evidencia válida (revisión adversarial, pasada 2) |
| Perfiles por variable | `UnivariateResult` sin perfiles (estado legal: `columns=()` ya lo produce) | la causa |
| Calidad por columna | `QualityResult` con la tabla vacía y sus siete columnas | la causa |
| Figuras | las que se puedan armar con lo que sí se calculó | — (no es una superficie que se lea) |

**La tasa global se conserva siempre que se pueda calcular**: si falló la agrupación en el tiempo
pero la población es buena —el caso de las dos fechas—, `overall_rate` es la de siempre. Si
tampoco se puede (sin población), sale `NaN` y las superficies dicen «no disponible», **no** «sin
operaciones elegibles», que sería falso.

### 1.1 🔴 Un constructor que NO valida la población

El constructor degradado de D-SC-17, `tasa_no_evaluable()`, **valida la población antes de
construir** —frame no vacío, índice único, target presente— y levanta justo en los tres casos que
esta enmienda tiene que rescatar (revisión adversarial, verificado: `_validar_poblacion` es su
primera línea). Usarlo como red volvería a detener la corrida. Por eso hay **dos** constructores,
con contratos distintos y a propósito:

| Constructor | Cuándo | Valida la población | `overall_rate` |
|---|---|---|---|
| `tasa_no_evaluable(frame, …, reason="sin_eje_temporal")` —el de D-SC-17, **sin cambios**— | La población es buena y lo que falta es el eje | **Sí**: si no lo es, levanta, y ese error lo atrapa el paso | la tasa global, con la regla de siempre |
| `tasa_no_calculable(frame \| None, target_col=…, axis=…)` —**nuevo**— | Cualquier otra falla de la tasa, incluida una población rota | **No**: construye siempre | la tasa global **si** el frame existe, trae la columna del target y tiene elegibles; si no, `NaN`. Nunca levanta |

Los dos devuelven la tabla vacía con sus seis columnas, así que la invariante del DTO de D-SC-17
(«con causa ⇒ tabla vacía y sus columnas») se cumple sin tocarla.

### 1.2 🔴 El preflight no puede predecir un corte que ya no ocurre

`check_dataset()` —la verificación previa que usan la pantalla, el YAML y la puerta de
artefactos— existe para decir **antes** de correr qué hará fallar la corrida, y cualquier desajuste
la declara `compatible=False` (`core/dataset_check.py:817`). Dos cosas de `eda` lo alimentan hoy, y
las dos predirían un corte que D-SC-19 elimina (revisión adversarial, pasada 2, verificado):

- **`DefaultRateConfig.requisitos_incumplidos()`** declara, para `axis="cohort"` sin `cohort_col`,
  que «la corrida se detendrá al llegar al análisis exploratorio». Pasa a **no declarar nada**: su
  docstring dice por qué, y el aviso vive donde sí es verdad —el `help` de la opción y la alerta del
  resumen—.
- **Las columnas que nombra `eda`** (`date_col`, `cohort_col`, `univariate.columns`) llevan
  `column_role="input"`, y una ausente produce `missing_column`. El `column_role` **se conserva**
  —es lo que hace que la pantalla ofrezca la lista de columnas del archivo en vez de un campo de
  texto—, pero el recorrido del preflight **deja de contarlas como desajuste**: una columna que falta
  en `eda` cuesta un sub-análisis, no la corrida, y decir «incompatible» sería falso. Se implementa
  como una exención explícita de la sección `eda` en el recorrido, con su razón en el código.

Queda declarado lo que se pierde: por YAML, una columna de `eda` mal escrita ya no se avisa
**antes** de correr; se dice **durante** la corrida, como alerta con su causa, sin detener nada. Un
preflight con avisos no bloqueantes sería una capacidad nueva del contrato transversal D-INV, y no
entra aquí.

### 1.3 🔴 Un sub-análisis caído no se publica como resultado negativo

Rellenar lo que falló con «vacío» no es neutro: con el código de hoy, una tabla de calidad vacía se
convierte en `quality_flag_counts` con **ceros** —que se lee «el archivo no tiene problemas de
calidad»— y una estabilidad no evaluable publica `stability_flagged = 0.0` en el canal de métricas
—que se lee «estable»— (revisión adversarial, pasada 3, verificado: `_build_eda_card` y
`EdaStep.metrics`). Un cálculo que no se hizo no puede publicarse como un resultado negativo. Por
eso:

| Si falló… | La card publica | El canal de métricas (D-GOB-2) |
|---|---|---|
| la calidad | `quality_flag_counts = {}` —**vacío**, no ceros— | sin cambios: la calidad no publica métricas |
| la estabilidad (`no_calculable`) o la tasa de la que depende (`tasa_no_calculable`) | `stability_flagged = False` (el campo es obligatorio), con la causa en `stability_not_evaluable_reason` y en `failed_analyses` | **omite** `stability_flagged` |
| la tasa (`no_calculable`) | `n_periods = 0` y la causa | **omite** `n_periods`; `overall_default_rate` se omite si es `NaN`, como hoy |

Las causas de no evaluabilidad que **ya existían** (`eje_cohorte`, `pocos_periodos_evaluables`,
`tasa_media_cero`, `sin_eje_temporal`) conservan el comportamiento de hoy en el canal de métricas:
cambiarlo movería el `results.metrics` de corridas que hoy terminan —el preset F1 publica
`stability_flagged = 0.0` con `eje_cohorte`— y rompería el bit a bit. Queda declarado como límite:
una señal **no evaluada** por una causa esperada sigue viajando como `0.0`; una **caída** por una
falla, no.

**Qué excepciones se atrapan: todas.** `EdaError` es el caso esperado y su mensaje ya está redactado
para una persona. Cualquier otra excepción —un defecto del motor— **también** degrada, porque la
regla es «nunca la mata», pero **no se esconde**: su causa se publica como «error inesperado del
motor (`<Tipo>`): …» y va al trail con el tipo de la excepción. Un defecto de código queda así a la
vista en el resumen, en el panel y en el informe, en vez de llevarse la corrida.

**Lo que NO cambia:**

- `DefaultRateAnalyzer.compute`, `UnivariateProfiler.profile` y `DataQualityProfiler.profile`, como
  API estable usable sin `Study`, **siguen levantando** su `EdaError` de siempre. La regla es del
  **paso** del pipeline, no de las piezas.
- La degradación por falta de eje de D-SC-17 (`sin_eje_temporal`) se conserva tal cual: es una
  propiedad **esperada** del archivo y se dice como una línea, no como una alerta (§2).
- Ninguna corrida que hoy termina cambia un número: la regla sólo entra donde hoy `eda` levanta.
- `binning` y el resto del pipeline siguen siendo bloqueantes. D-RAR (la categoría rara) es otra
  enmienda, aprobada, y no se toca aquí.

## 2. D-SC-20 — qué dicen las superficies

**Un solo dato nuevo en la card**, que leen todas las superficies:

```python
class EdaCardSection(BaseModel):
    ...
    failed_analyses: dict[str, str] = {}   # aditivo: sub-análisis → causa, en palabras
```

Con claves `default_rate`, `stability`, `univariate` y `quality`. Vacío en toda corrida que hoy
termina.

| Superficie | Qué dice |
|---|---|
| **Trail** | Una decisión por sub-análisis caído: `regla="analisis_exploratorio_parcial"`, `valor=<sub-análisis>`, `umbral=<causa>`, `accion="no_evaluable"`, y el tipo de la excepción cuando no fue un `EdaError` |
| **Resumen de la etapa** | Una **alerta** por sub-análisis caído —«La tasa de malos en el tiempo no se pudo calcular: <causa>»—, que el resumen final recoge en «Qué revisar». La falta de eje de D-SC-17 sigue siendo una **línea**: no es una falla, es el archivo |
| **Panel de Resultados** | Un aviso bajo las cifras con cada sub-análisis caído y su causa, en el molde del que D-SC-18 ya pinta para la falta de eje |
| **Informe** | `_eda_context` y `_results_eda` dicen qué no se pudo calcular y por qué, sin anunciar tablas ni figuras que no están; el builder omite la tabla de calidad vacía como ya omite la de la tasa |
| **Página ejecutiva del informe y resumen final** | 🔴 `_estado_de_ejecucion` escribe hoy «corrieron **sin fallos** <etapas>» mientras el informe se renderiza, y con un `eda` parcial eso sería falso (pasada 3). Pasa a decir «corrieron <etapas>; el análisis exploratorio, de forma **parcial**: <n> de sus análisis no se pudieron calcular (ver “Qué revisar”)». Al terminar, `summary()` dice «completada — con el análisis exploratorio parcial». En una corrida sana los dos textos son **byte a byte** los de hoy |
| **Guía** | La sección de la tasa en el tiempo deja de listar «lo que sigue siendo un error»: pasa a decir que el análisis exploratorio nunca detiene la corrida, y qué se ve cuando algo no se pudo calcular |
| **Catálogo de la pantalla** (`ui/jobs.py`) | 🔴 La opción `eda.default_rate.axis = "cohort"` sigue marcada **«exige otro campo»** con el motivo «Sin ella, la corrida se detiene aquí». Con D-SC-19 eso deja de ser verdad, y el estado está definido como «hasta que lo declares el config no se construye» (D-EXI-2): es exactamente lo que D-SC-18 ya corrigió para la opción `"period"`. Pasa a **«disponible»**, retira `motivo`/`prueba`/`exige`, y el aviso —«sin la columna de cohorte, la tasa en el tiempo no se puede calcular; la corrida sigue»— se muda a su `help`. Se regeneran el fixture `jobs.json` y el ledger `option_surface_ledger.json` |

## 3. Estrategia de tests

Todos nacen rojos. Los tests de D-SC-17 que exigían `EdaError` desde el **paso** se **invierten** y
se declara en su docstring; los que lo exigen desde las **piezas** (el analizador, el constructor
degradado) se quedan como están, porque su contrato no cambia.

| # | Test | Nace rojo porque |
|---|---|---|
| 1 | **Gate de aceptación**: la cartera con dos columnas de fecha y `partition="random"` termina `done` con la puerta guiada, y el resumen de `eda` trae la alerta con la causa | Hoy muere en `eda` |
| 2 | Cada uno de los cinco errores que D-SC-17 dejó intactos, ahora desde el **paso**: la corrida sigue, la tasa sale `no_calculable` con la causa del motor en `failed_analyses` | Hoy levantan |
| 3 | Población rota (partición de análisis vacía, índice duplicado, target ausente): los tres sub-análisis salen degradados con la misma causa, y el paso **publica sus seis artefactos** | Hoy levanta |
| 4 | Perfiles que fallan solos (una columna pedida que no existe): tasa y calidad salen bien, los perfiles vacíos con su causa | Hoy levanta |
| 5 | Una excepción **no** `EdaError` inyectada en un sub-análisis: la corrida sigue, la causa dice «error inesperado del motor (`<Tipo>`)» y el trail registra el tipo | Hoy levanta |
| 6 | La tasa global se conserva cuando falla sólo la agrupación (dos fechas), y sale `NaN` —con las superficies diciendo «no disponible», no «sin operaciones elegibles»— cuando no hay población | La rama no existe |
| 7 | Una decisión `analisis_exploratorio_parcial` por sub-análisis caído, y ninguna en una corrida sana | No se emite |
| 8 | El informe completo de la corrida del test 1: la causa aparece, no aparecen «0 períodos», «un solo período» ni tablas vacías, y ningún identificador del motor en la prosa | La rama no existe |
| 9 | Espejo bidireccional de los rótulos nuevos (`no_calculable`, `tasa_no_calculable`) y del campo `failed_analyses` en `results-types.ts` | Los rótulos no existen |
| 10 | `ResultsTab` pinta el aviso con cada sub-análisis caído (vitest, render estático) | La rama no existe |
| 10b | **El constructor nuevo nunca levanta**: con frame vacío, índice duplicado, sin la columna del target y con `None` devuelve la tabla vacía con sus seis columnas, y `overall_rate` es finito sólo cuando hay elegibles | El constructor no existe |
| 10c | La opción `axis="cohort"` del catálogo es **«disponible»** sin `motivo`, `prueba` ni `exige`, con el aviso en su `help`; y un config con `axis="cohort"` sin `cohort_col` **corre** y degrada la tasa | Hoy está marcada «exige otro campo» |
| 10d | **Preflight**: `check_dataset` declara **compatible** un config cuyos únicos desajustes son de `eda` —`axis="cohort"` sin `cohort_col`, `date_col`/`cohort_col` ausentes, una columna de perfil ausente—, y **sigue** declarando incompatible uno con la misma columna ausente en `binning` (control de que la exención no se derramó) | Hoy los cinco salen `compatible=False` |
| 10e | **La estabilidad falla sola**: con una excepción inyectada en `assess()`, la tasa se publica entera y la estabilidad sale `no_calculable` con su causa en `failed_analyses["stability"]` | Hoy la corrida muere |
| 10f | **Nada caído se publica como negativo**: con la calidad caída, `quality_flag_counts == {}`; con la estabilidad o la tasa caídas, el canal de métricas **no** trae `eda.stability_flagged` ni `eda.n_periods` | Hoy serían ceros |
| 10g | **La página ejecutiva no dice «sin fallos»**: el informe de una corrida con `eda` parcial dice «de forma parcial» y no contiene «corrieron sin fallos»; `summary()` dice «completada — con el análisis exploratorio parcial»; y en una corrida sana los dos textos no cambian | Hoy dice «sin fallos» |
| 11 | **Bit a bit**: la proyección canónica de una corrida F1 del preset antes y después; las únicas diferencias admitidas son las claves nuevas con su valor vacío (`failed_analyses: {}`), `config_hash` `1063d6cf…` intacto | — (guardrail) |

**Controles negativos (RUNBOOK §6):** (a) volver a dejar que el paso propague la excepción de la
tasa y ver rojo el 1; (b) atrapar sólo `EdaError` y ver rojo el 5; (c) no publicar los seis
artefactos cuando falla la preparación y ver rojo el 3; (d) rellenar la tasa global con `NaN` en el
caso de las dos fechas y ver rojo el 6; (e) emitir la decisión también en una corrida sana y ver
rojo el 7; (f) borrar un rótulo nuevo del espejo del front y ver rojo el 9; (g) usar
`tasa_no_evaluable` como red —que valida— y ver rojo el 3 por la población rota; (h) extender la
exención del preflight a todas las secciones y ver rojo el 10d por `binning`; (i) atribuir la falla
de la estabilidad a la tasa y ver rojo el 10e; (j) publicar ceros en `quality_flag_counts` con la
calidad caída y ver rojo el 10f; (k) dejar «corrieron sin fallos» con un `eda` parcial y ver rojo el
10g.

## 4. Riesgos

1. **Que un defecto del motor quede escondido.** Por eso se atrapa todo pero se publica todo: la
   causa de una excepción inesperada lleva su tipo, va a «Qué revisar» y al trail, y el test 5 con
   su control negativo lo vigila.
2. **Que se lea como que la corrida «salió bien» con el EDA roto.** No: cada sub-análisis caído es
   una **alerta** en el resumen final, no una línea; el modelador lo ve en «Qué revisar».
3. **Que un dato roto de verdad avance más allá del EDA.** Avanza hasta la primera etapa que lo
   necesita, que lo rechaza con su propio error. Es donde tiene que fallar.

## 5. Lo que Cami decide

| # | Decisión | Opciones | Recomendación |
|---|---|---|---|
| 5.1 | Qué excepciones degrada el paso | (a) **todas**, publicando el tipo de las inesperadas; (b) sólo `EdaError` | **(a)**: es lo que «nunca la mata» significa; un defecto del motor sigue a la vista en el resumen, el panel, el informe y el trail |
| 5.2 | Cómo se dice un sub-análisis caído | (a) **como alerta**, que el resumen final recoge en «Qué revisar»; (b) como una línea más | **(a)**: una falla es algo que revisar; la falta de eje de D-SC-17 sigue siendo línea porque es el archivo, no una falla |

## 6. La revisión adversarial de este documento

Tope declarado: **tres pasadas**, con el criterio de parada de las enmiendas anteriores (se detiene
cuando una pasada deja de tumbar premisas y sólo refina detalles).

| Pasada | Hallazgo | Qué cambió |
|---|---|---|
| 1 | (a) La opción «Por cohorte o añada» de la pantalla seguía marcada «exige otro campo» y decía que la corrida se detiene; (b) el constructor degradado de D-SC-17 **valida la población** y levanta en los tres casos que había que rescatar | (a) la opción pasa a «disponible» con el aviso en su `help` (§2, test 10c); (b) §1.1: un constructor nuevo, `tasa_no_calculable`, que nunca levanta (test 10b, control negativo g) |
| 2 | (a) El **preflight** seguiría declarando incompatible un config que ahora corre —el requisito de cohorte y las columnas de `eda` ausentes—; (b) tasa y estabilidad como una sola unidad de fallo harían perder una tasa válida cuando falla sólo la estabilidad | (a) §1.2: el requisito deja de declararse y el preflight exime a `eda` conservando el `column_role` del selector de columnas (test 10d, control h); (b) la estabilidad es una unidad propia con su causa (test 10e, control i) |
| 3 | (a) Un sub-análisis caído se publicaría como resultado **negativo válido** —calidad con ceros, `stability_flagged = 0.0` en el canal de métricas—; (b) la página ejecutiva del informe diría «corrieron **sin fallos**» con un `eda` parcial | (a) §1.3: vacío en vez de ceros y métricas omitidas para lo caído (test 10f, control j); (b) el estado de ejecución dice «parcial» (test 10g, control k) |

**Tope alcanzado.** Las dos primeras pasadas trajeron consumidores que el diseño no había mirado
—el constructor que valida, la opción de la pantalla, el preflight— y la tercera, dos formas de
**leer mal** lo que el diseño ya publicaba. Ninguna tumbó la regla; las tres afinaron sus bordes.
Es el criterio de parada declarado: estas correcciones no llevan pasada propia, y la
implementación abre con una pasada sobre su rango de código.

## 7. Implementación (2026-09-23) — lo que el código midió distinto de lo escrito

Implementada en la misma sesión de la aprobación. Cinco cosas se resolvieron al programar y quedan
declaradas aquí, porque el lector de §1–§3 las encontraría distintas en el código:

1. **La población se valida una vez, en la preparación.** §1 la ponía implícita en la red de la
   tasa; medido, con el target ausente la calidad —que describe el archivo y no lee el target—
   salía **bien** mientras la tasa y los perfiles caían, y el test 3 («los tres sub-análisis con la
   misma causa») quedaba rojo por la razón correcta. `EdaStep` llama a `_validar_poblacion` —el
   mismo guard de D-SC-17— justo después de elegir la partición: una población rota (vacía, con
   índice duplicado o sin el target) cae en la preparación y los tres sub-análisis salen con **su**
   causa, una sola. Consecuencia para los controles negativos: el defecto (g) —usar
   `tasa_no_evaluable` como red— ya no lo delata el 3, porque la población rota nunca llega a esa
   red; lo delata el 2, porque la causa sale «sin eje» en vez de `no_calculable`. Y se añade el
   control (g2): quitar el guard de la preparación pone rojo el 3.
2. **La frase de un análisis caído tiene una sola fuente** en `nikodym.eda.card`:
   `FAILED_ANALYSIS_LABELS` (sujeto y predicado de cada clave, concordados, en el orden del paso)
   y `failed_analysis_sentence(key, cause)` → «<sujeto> no se pudo calcular: «<causa>»». La causa va
   **citada** porque es el mensaje del motor tal cual, y como cita conserva su mayúscula tras los
   dos puntos; se le quita el punto final. La leen el resumen de la etapa y el informe; el panel
   la replica en `edaFailedAnalyses` y el espejo de vocabulario ata los dos mapas.
3. **El tipo de una excepción inesperada viaja en la causa**, no en un campo nuevo del trail:
   `DecisionRecord` no cambia (RUNBOOK §12.2-11), y la causa —que va al `umbral` de la decisión
   `analisis_exploratorio_parcial`— ya dice «error inesperado del motor (`KeyError`): …».
4. **Las causas del motor conservan sus nombres de campo.** Algunos mensajes de `EdaError` dicen
   el campo que hay que tocar —«declare `eda.default_rate.date_col` explícitamente»—. Esta enmienda
   los publica tal cual (§1.3 los da por redactados para una persona) y el gate de identificadores
   del resumen y del informe vigila los **slugs** de los mapas de rótulos (`no_calculable`,
   `tasa_no_calculable`, `failed_analyses`), no las rutas de config. Reescribir los mensajes para
   una lectura sin YAML es trabajo aparte y no entra aquí.
5. **Los tests de D-SC-17 que exigían `EdaError` desde el paso se invirtieron**, con la inversión
   dicha en su docstring: los cinco errores se miden ahora sobre la **pieza**
   (`DefaultRateAnalyzer.compute` sigue levantando) y desde el paso publican su causa; y los
   cinco de `test_eda_step.py` (seis casos) que exigían el error por artefactos mal tipados,
   partición sin filas o sin columna de partición pasan a exigir la causa en los tres
   sub-análisis. El requisito de cohorte de `test_invariantes_previas.py` se invirtió igual: ya no
   se declara.

Controles negativos: los once de §3 más (g2) y cinco de superficie —métricas, párrafo del informe,
tabla vacía del builder, alertas del resumen y aviso del panel (vitest)—, cada uno rojo en su test
y restaurado byte a byte.

**Revisión adversarial del código.** Tope declarado: tres pasadas sobre el rango `5fe52f0..HEAD`,
que incluye el commit del notebook.

| Pasada | Hallazgo | Qué cambió |
|---|---|---|
| 1 | (a) **alto**: con la preparación caída, `_publicar` derivaba la estabilidad llamando a `assess()` sin protección —la red de las redes todavía podía levantar—; (b) sin eje temporal y con otra parte caída, el panel y el informe seguían diciendo que «el resto del análisis se hizo completo»; (c) el gate del notebook ejecutaba las celdas pero no comparaba las salidas guardadas, y su docstring prometía que sí | (a) la construcción final se protege y, si falla, la estabilidad se anota como caída con su causa; (b) la frase se dice sólo si nada más cayó; (c) cada celda se ejecuta como un kernel y lo impreso y lo devuelto se comparan con lo guardado, eximiendo sólo las líneas que dependen de los extras. De paso se midió que el gate del notebook habría fallado en los nueve jobs de la matriz, que no instalan `openpyxl`: ahora exige `openpyxl` y corre en el job con todos los extras. Cinco controles negativos más, todos rojos |
| 2 | (a) **alto**: el gate del notebook comparaba el texto de cada resultado pero no su `text/html`, que es lo que se ve al abrir el cuaderno; (b) una falla al armar las recetas de figura se publicaba como `n_figures = 0`, sin causa ni alerta: un negativo publicado y un defecto escondido, contra la propia regla de §1.3 —la tabla de §1 decía que las figuras «no se leen», y es verdad para las superficies, no para la card— | (a) se compara también el HTML, y las menciones del informe PDF/Word —que dependen de los extras— se neutralizan en todas sus formas (línea, par del `repr`, ítem HTML); (b) clave nueva `figures` en `failed_analyses`, con su causa, su decisión en el trail y su alerta; los rótulos pasan a ser sujeto **y predicado** para que las figuras concuerden en plural, y la frase de Resultados deja de enumerar sujetos. Límite declarado: si una receta falla se pierden todas las recetas —la falla se declara—; los gráficos del informe no se pierden porque salen de las tablas. Tres controles negativos más |
| 3 | **medio**: el gate del notebook eximía también las menciones del informe Word, que ya no dependen del entorno —el gate exige `python-docx`—: una regresión que dejara de escribir el `.docx` habría pasado verde con la salida publicada vieja | sólo se exime el PDF; Word se compara y se exige que el `.docx` exista. Un control negativo más: suprimir la escritura del Word pone rojo el gate |

**Tope alcanzado.** La primera pasada tumbó una premisa —la red final todavía podía levantar—, la segunda encontró un negativo publicado que la propia tabla de §1 había dejado pasar —las figuras— y la tercera ya sólo afinó el gate del notebook. Es el criterio de parada declarado.

## 13. Simplicidad (SDD-31) — obligatoria

- **Entrada mínima:** no cambia.
- **Qué NO se configura:** la regla. No hay un flag «dejar que el EDA detenga la corrida»: nadie lo
  querría encendido, y sería una perilla más que documentar y gatear.
- **Campos esenciales:** sin cambios.
- **Presupuesto de perillas: CERO.** El único campo nuevo es de **resultado** (`failed_analyses` en
  la card), no de config; las perillas de las doce secciones del scorecard siguen en **413**.
- **Resumen por etapa:** el de `eda` gana alertas condicionales; en una corrida sana no cambia.
- **Notebook mínimo:** sin cambios en sus líneas.
- **Las cinco cifras:** idénticas. Lo que cambia es que un archivo de banco con dos fechas llega al
  final.
