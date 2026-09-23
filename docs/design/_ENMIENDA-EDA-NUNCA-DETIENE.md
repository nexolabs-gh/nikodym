# Enmienda — el análisis exploratorio nunca detiene la corrida

| Campo | Valor |
|---|---|
| **Tipo** | Enmienda corta a [`_ENMIENDA-EDA-SIN-EJE-TEMPORAL.md`](_ENMIENDA-EDA-SIN-EJE-TEMPORAL.md) (la **generaliza** y deroga su §2 «los cinco errores quedan intactos» y su §8.2), a [`27-eda.md`](27-eda.md) §8 y a [`31-simplicidad-y-flujo-guiado.md`](31-simplicidad-y-flujo-guiado.md) §8 |
| **Decisiones** | **D-SC-19** (la regla: `eda` nunca detiene la corrida) y **D-SC-20** (qué dicen las superficies de un sub-análisis que falló) |
| **Módulos** | `nikodym.eda` (`step`, `default_rate`, `stability`, `card`), `nikodym.guided.summaries`, `nikodym.report` (`builder`, `prose`), `web/` (`results-types`, `results-format`, `ResultsTab`), `docs_site/guias/analisis-exploratorio.md` |
| **Fase** | F1 |
| **Estado** | **Propuesta** — la dirección la eligió Cami el 2026-09-23 (interactivo: «nunca la mata», y todo en la misma sesión); falta su OK al documento |
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
| Tasa por período + estabilidad | la tasa degradada de D-SC-17 —tabla vacía con sus seis columnas— con la causa **nueva** `no_calculable`; la estabilidad, no evaluable con la causa **nueva** `tasa_no_calculable` | la causa en palabras |
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

Con claves `default_rate`, `univariate` y `quality`. Vacío en toda corrida que hoy termina.

| Superficie | Qué dice |
|---|---|
| **Trail** | Una decisión por sub-análisis caído: `regla="analisis_exploratorio_parcial"`, `valor=<sub-análisis>`, `umbral=<causa>`, `accion="no_evaluable"`, y el tipo de la excepción cuando no fue un `EdaError` |
| **Resumen de la etapa** | Una **alerta** por sub-análisis caído —«La tasa de malos en el tiempo no se pudo calcular: <causa>»—, que el resumen final recoge en «Qué revisar». La falta de eje de D-SC-17 sigue siendo una **línea**: no es una falla, es el archivo |
| **Panel de Resultados** | Un aviso bajo las cifras con cada sub-análisis caído y su causa, en el molde del que D-SC-18 ya pinta para la falta de eje |
| **Informe** | `_eda_context` y `_results_eda` dicen qué no se pudo calcular y por qué, sin anunciar tablas ni figuras que no están; el builder omite la tabla de calidad vacía como ya omite la de la tasa |
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
| 11 | **Bit a bit**: la proyección canónica de una corrida F1 del preset antes y después; las únicas diferencias admitidas son las claves nuevas con su valor vacío (`failed_analyses: {}`), `config_hash` `1063d6cf…` intacto | — (guardrail) |

**Controles negativos (RUNBOOK §6):** (a) volver a dejar que el paso propague la excepción de la
tasa y ver rojo el 1; (b) atrapar sólo `EdaError` y ver rojo el 5; (c) no publicar los seis
artefactos cuando falla la preparación y ver rojo el 3; (d) rellenar la tasa global con `NaN` en el
caso de las dos fechas y ver rojo el 6; (e) emitir la decisión también en una corrida sana y ver
rojo el 7; (f) borrar un rótulo nuevo del espejo del front y ver rojo el 9; (g) usar
`tasa_no_evaluable` como red —que valida— y ver rojo el 3 por la población rota.

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
