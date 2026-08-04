# Aterrizar una norma local

Nikodym implementa **estándares comunes**: PD, LGD y EAD, validación de modelos, IFRS 9/ECL,
forward-looking y stress testing. Ninguna de esas piezas asume un país.

Lo que ningún motor estándar puede darte es **tu** norma: cada supervisor tabula sus propios
parámetros, define sus propias carteras y cambia sus circulares en su propio calendario. Perseguir
ese calendario para cada jurisdicción no es sostenible para una librería, y prometerlo sería
prometer lo que no se puede cumplir.

Así que la librería hace lo contrario: **el motor estándar queda abajo, y la norma local se monta
encima**. Esta página documenta cómo, con el único caso que está implementado —Chile, CMF— como
ejemplo trabajado de punta a punta.

!!! info "Qué es esta página, y qué no"
    Es una **demostración de método**, no un catálogo de jurisdicciones soportadas. El caso chileno
    está congelado en la versión que se cotejó (ver [El caso está congelado](#el-caso-esta-congelado));
    no se mantiene al día con cada circular. Si necesitas otra jurisdicción —o ésta, actualizada—,
    el camino es escribirla sobre las mismas piezas, y el ajuste final lo hace el modelador.

## Qué es neutro y qué no

Medido sobre el código, no supuesto:

| Componente | Cálculo | Qué hace |
|---|---|---|
| `provisioning.internal` | **neutro** | Provisión por PD · LGD · exposición sobre grupos homogéneos —los formas tú, o los deriva el motor por banda de puntaje—. No conoce ninguna cartera normativa ni ninguna tabla de supervisor. ⚠️ Pero **su vocabulario de fábrica sí es chileno**: la columna de cartera se llama `cmf_portfolio` por defecto y varias ayudas del formulario citan el Cap. B-1, porque este método existe *porque* esa norma lo exige. Se cambia sin tocar el motor. |
| `provisioning.ifrs9` | **neutro** | ECL bajo IFRS 9: PD marginal × LGD × EAD descontada a la EIR, con staging por SICR. Es una norma contable internacional, no local. |
| `provisioning` (orquestación) | **neutro, con default chileno** | El *mecanismo* no sabe de países: compara dos fuentes y aplica la regla que declaras. ⚠️ Lo que sí es chileno es el **estado de fábrica**: la fuente A apunta por defecto al motor CMF, y el único régimen de segmentación registrado hoy es el suyo. Cambiar la fuente es un campo del config. |
| `provisioning.cmf` | **Chile** | El caso de referencia: matrices del Capítulo B-1/B-3 de la CMF, con su mapeo de categorías, su tratamiento de garantías y sus reglas de exposición. |

La consecuencia práctica, y ésta sí es exacta: **el pipeline completo corre hoy fuera de Chile sin
tocar una línea del motor chileno**. Scorecard, IFRS 9 y método interno no lo importan siquiera
—medido: cargarlos no mete `provisioning.cmf` en memoria—. Lo que hay que ajustar fuera de Chile no
es el cálculo, son los defaults y los nombres.

## Las cinco piezas de una norma local

Esto es lo que hubo que escribir para el caso chileno, y es lo que hay que escribir para cualquier
otro. Ninguna exige modificar el núcleo.

1. **Las tablas de parámetros, versionadas y selladas.** No van en código: viven en un archivo de
   datos con su hash SHA-256 y un manifiesto que declara de qué circular salió cada tabla, con qué
   fecha de vigencia y en qué estado de verificación está. El motor **rehúsa arrancar por defecto**
   si el hash no coincide con lo declarado —es un interruptor, y apagarlo deja pasar el desajuste:
   está a la vista para que la decisión sea explícita, no para que se tome sin querer—. En el caso
   chileno son 10 matrices, en aritmética `Decimal` —nunca
   coma flotante— porque una provisión que se reporta no admite error de redondeo.
2. **El vocabulario de segmentos, declarado.** Qué carteras existe la norma y cómo se llaman. Viaja
   **dentro del resultado** de la corrida, no sólo en el config: un esquema que se declara sólo en la
   entrada es una afirmación que nadie puede contrastar después.
3. **El mapeo desde el modelo hacia la norma.** Tu PD estimada no es la categoría del supervisor: hay
   que traducir, y esa traducción es una decisión que el motor te pide explícitamente en vez de
   adivinarla.
4. **Exposición y garantías según la norma.** Qué entra en la exposición, cómo se descuenta un aval,
   qué redondeo aplica la moneda local.
5. **La regla de comparación, si la norma la impone.** En Chile el Capítulo B-1 obliga a reportar,
   por institución, el mayor entre el método estándar del supervisor y el método interno del banco.
   Eso lo expresa la orquestación con dos fuentes y una regla —hoy, el máximo o reportar el método
   interno—, y no hay nada chileno en el mecanismo. ⚠️ Que la segunda alternativa sea *el interno* y
   no cualquiera de las dos tampoco es casual: también sale del B-1, que la admite sólo cuando el
   supervisor evaluó ese método y no lo objetó.

!!! warning "Un error que la norma chilena hace fácil cometer"
    La regla del máximo es entre el **método estándar y el método interno**, y **no** entre el
    estándar e IFRS 9. El Compendio (Cap. A-2, num. 5) **excluye** el modelo de deterioro de NIIF 9
    sobre las colocaciones y los créditos contingentes. Comparar los dos marcos contables puede ser
    útil —por ejemplo, para reportar a una matriz extranjera— pero no es una exigencia del
    supervisor, y el motor no la rotula como tal.

## El caso está congelado

El motor chileno **no se mantiene al día con cada circular**, y decirlo es parte del entregable: un
motor normativo que se publica y no se actualiza no envejece hacia «incompleto», envejece hacia
**incorrecto**, y su salida es un número que alguien puede reportar.

Por eso el estado de verificación viaja con los datos y se publica aquí:

| | |
|---|---|
| Versión del bundle | `cmf_b1_b3_2025_01` |
| **Extracción desde el texto oficial** | **2026-06-23** (y verificación visual de las tablas más críticas ese mismo día) |
| **Cotejo celda por celda de la matriz de consumo** | **2026-07-14**, contra el compendio consolidado |
| Última modificación normativa incorporada | 2025-01-31 (Circular 2.346/2024, consumo) |
| Archivo de parámetros | sellado por SHA-256, verificado en cada corrida |

⚠️ **Las dos fechas no son la misma cosa, y la diferencia importa.** La primera es la que declara el
manifiesto que viaja en el paquete: cuándo se extrajeron las tablas. La segunda es un cotejo
posterior y más fuerte —una a una contra el texto— y **sólo cubre la matriz de consumo**. El resto
de las tablas está verificado, pero no con ese nivel de detalle; el registro dice exactamente cuál
tiene cuál.

⚠️ **La fecha de vigencia no es una sola.** Cada matriz trae la suya, y la más antigua en uso es de
**2014**. El identificador del bundle dice `2025_01` porque ésa es la última circular incorporada,
no porque todas las tablas sean de esa fecha:

| Matriz | Vigente desde | Circular |
|---|---|---|
| Comercial individual (normal y en incumplimiento) | 2014-12-30 | 3.573/2014 |
| Comercial grupal — leasing | 2018-07-06 | 3.638/2018 |
| Comercial grupal — estudiantil | 2018-07-06 | 3.638/2018 |
| Comercial grupal — genérico y factoring | 2020-05-22 | 2.257/2020 |
| Comercial grupal — sustitución por aval | 2018-07-06 | 3.638/2018 |
| Vivienda (PVG) | 2018-07-06 | 3.638/2018 |
| Calidad del aval | 2018-07-06 | 3.638/2018 |
| Contingentes (B-3) | 2016-03-29 | 3.604/2016 |
| **Consumo** | **2025-01-31** | **2.346/2024** |

### Estado real de las fuentes

Cinco fuentes, y **no todas están en el mismo estado**:

| Fuente | Estado |
|---|---|
| Compendio consolidado B-1/B-3 (3.573/2014; 3.638/2018; 3.604/2016) | verificada |
| Circular de consumo 2.346/2024 | verificada |
| PDF semilla B-1 (3.584/2015), confirmación cruzada | verificada |
| Versión 2022 del Compendio (2.243/2019) | **referenciada** — revalidación pendiente antes de uso productivo |
| RAN 21-10 (garantías) | **pendiente** — sin tabla numérica nueva verificada |

### Dos brechas que el motor declara en vez de rellenar

1. **Aforos y *haircuts* de garantías financieras.** No están tabulados en el B-1; exigen una
   circular específica de factores de descuento. El motor no inventa un factor: te pregunta qué
   hacer con una garantía financiera cuyo aforo no está verificado.
2. **Las tablas numéricas del RAN 21-10.** El RAN regula requisitos de garantías, pero de él no se
   extrajo ninguna tabla nueva para el modelo estándar del B-1.

## Antes de usarlo en producción

**Los parámetros no son oficiales.** Se transcribieron del compendio con asistencia de IA y
verificación visual; **no provienen de la CMF ni están validados por ella** —la Comisión no
certifica implementaciones de terceros— y **requieren validación humana contra la norma vigente
antes de cualquier uso productivo**.

Lo que sí está hecho y es auditable: la matriz de consumo (numeral B-1 3.1.3, Circular 2.346/2024)
se cotejó **celda por celda** contra el texto del compendio el **2026-07-14** —sus 16 valores de PI,
sus 6 de PDI y el PI de incumplimiento coinciden exactamente—, y la verificación visual del
2026-06-23 sobre las tablas más críticas **detectó y corrigió** un error en la columna de escala
internacional de avales. El registro completo, tabla por tabla y con su estado, está en
[`docs/normativa_cmf_parametros.md`](https://github.com/nexolabs-gh/nikodym/blob/main/docs/normativa_cmf_parametros.md).

Y una vez más, porque es el punto de la página: **una jurisdicción implementada es evidencia de que
el método funciona, no una promesa de mantenerla al día.** Si tu norma es otra, las cinco piezas de
arriba son el camino; el motor estándar que hay debajo ya no hay que escribirlo.
