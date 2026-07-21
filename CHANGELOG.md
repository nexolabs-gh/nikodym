# Changelog

Formato basado en [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/);
el proyecto sigue [SemVer](https://semver.org/lang/es/): desde 1.0, el pipeline de scorecard (F1)
es API estable; las superficies que aún crecen (modelado ML, provisiones, forward-looking,
contratos transversales) quedan marcadas como experimentales, fuera de la garantía SemVer 1.x.

## [1.4.0] — 2026-07-20

Informe con formato editorial, capítulo de validación formal y contexto poblacional; cierre de seis
brechas del contrato forward→IFRS 9; y pulido del informe y la demo previo a la reunión Interbank.

### Añadido

- **Informe: capítulo condicional «Validación formal».** Cuando la corrida publica el
  `ValidationResult` atómico (`validation.result`), el informe emite un capítulo nuevo —tras
  «Resultados», antes de provisiones— con una subsección por familia declarada en `families_run`
  (discriminación, calibración, estabilidad, backtesting). Las tablas se **copian** del DTO: `report`
  no recalcula métricas ni decisiones. El resumen ejecutivo suma la métrica «Estado técnico de
  validación formal», y el veredicto sigue siendo un bloque humano **POR COMPLETAR**: el estado del
  motor no lo sustituye. Si la corrida trae además una card suelta `validation.card` que no coincide
  con `result.card`, el builder falla en vez de mezclar lecturas de momentos distintos. La prosa de
  alcance deja de prometer futuro: sin validación, el informe dice que **esta corrida no ejecutó** la
  capa formal. El contrato es **aditivo** (`validation` no entra en `ReportStep.requires` ni en
  `required_sections`): ninguna cadena existente se rompe.
- **Informe: subsección «Población, particiones y exclusiones» en el capítulo de Contexto.** Si el
  dominio `data` publicó su card, el informe proyecta tres tablas —estados, particiones (tamaño y tasa
  de incumplimiento) y exclusiones por motivo— copiadas literalmente del `DataCardSection`: no infiere
  conteos ni recalcula estadísticas. Es opcional: su ausencia no es error.
- **Anexo C: cada dominio configurado publica su `effective_config`.** Antes sólo lo anexaban
  `survival` y `provisioning_ifrs9`. Ahora lo hace todo dominio presente en el config de la corrida
  —`data`, el pipeline scorecard, `survival`, `markov`, `forward`, `provisioning_ifrs9`, `validation`
  y las tres secciones de provisiones F3 (`provisioning_cmf`, `provisioning_internal` y el
  orquestador `provisioning` con su regla del máximo)—, incluso si no emitió card por ser config puro.
  No se agrega un dump top-level de `NikodymConfig`, y `effective_config` queda **excluido** del
  payload que se envía a la narrativa IA opcional.

### Corregido

- **Identidad del config (`config_hash`): la ruta del dataset ya no altera la identidad.** El campo
  `data.load.source` (ubicación del archivo en disco) entraba al `config_hash`, de modo que el mismo
  dataset en otra ruta —o el preset con `source: null` frente a la corrida con la ruta real— producía
  un hash distinto, desalineando el `config_hash` que muestra la app y el que aparece en el informe.
  El `data_hash` ya captura el **contenido** del dataset; la ruta es incidental. Ahora `data.load.source`
  se excluye del `config_hash` (además de las secciones de infraestructura). **Nota de contrato
  (SemVer):** esto recalcula el `config_hash` de todo config que fijaba una ruta de dataset; el hash
  del config por defecto (sin `data`) no cambia. Es una corrección de defecto, no una nueva convención.
- **`POST /api/config/to-yaml` era no-determinista frente al estado de imports.** La sección `report`
  (`report: Any` en el schema) se coacciona a `ReportConfig` sólo si `nikodym.report` ya fue importado,
  y esa coacción materializa `report.document` (default_factory) que el config del cliente no traía. El
  YAML salía con o sin ese bloque según qué se hubiera importado antes (así se colaba `report.document`
  al capturar los fixtures de la demo tras generar un informe). Ahora el endpoint vuelca con
  `exclude_unset=True`: idéntico byte a byte en ambos casos, sin tocar el `config_hash` ni el lineage
  de corrida de `study`.
- **Informe: coma decimal (es-CL) en la prosa y en las cifras destacadas.** Los porcentajes y números
  (`_pct`/`_num`) emitían punto decimal (`2.99 %`, `IV 0.03`) mientras las cifras en pesos ya usaban
  el punto como separador de miles. Ahora el decimal es coma (`2,99 %`), coherente con la convención
  chilena. Sólo presentación: no cambia valores ni `data_hash`. Las tablas de detalle y los ejes de
  los gráficos conservan el punto a propósito: son volcado técnico de `results`, pensado para
  copiarse a una herramienta de análisis.
- **Informe: marcador único «—» para celdas sin valor en las tablas de detalle.** `NaN` se volcaba como
  `nan` y el sentinel de dominio `"none"` (de los enums `iv_band`/`expected_sign`/`action` = «sin banda/
  signo/acción») como `none`; ambos parecían celdas rotas. Se unifican a un em-dash (convención de
  estados financieros para nil/ninguno/no-aplica), sin tocar los enums de la API de results ni el
  `data_hash`. Los `inf`/`-inf` se conservan crudos a propósito (anomalía real que debe verse).
- **Informe: las celdas de tabla ya no vuelcan `Decimal` crudo ni colecciones vacías.** Los motores de
  provisiones publican sus cifras en `Decimal` para no perder exactitud contable, pero el renderer no
  tenía rama para ese tipo y caía en `str(value)`: la tabla «Provisión interna por grupo homogéneo»
  mostraba `pd_group = 0.0052290061597687685198855454245661540747073248842022` (52 dígitos), y lo
  mismo `lgd_group` y `expected_loss_rate`. Ahora se formatean con la misma regla que un float (el
  anexo JSON ya lo hacía así). En la misma línea, una colección vacía (`warning_codes: []`) muestra el
  em-dash de «ninguno» en vez de `[]`/`{}` crudos. Sólo presentación: las cifras no cambian.
- **IFRS 9 (experimental): seis brechas del contrato forward→IFRS 9, cerradas con guards fail-fast.**
  Cuatro configuraciones que el motor aceptaba y luego **degradaba en silencio** ahora fallan con un
  mensaje que dice qué usar en su lugar: (1) `pd.rho_col` se rechaza al construir `IfrsPdConfig` —el
  motor v1 sólo consume `pd.rho` escalar, y honrar la columna con el escalar sería una etiqueta
  falsa—; (2) `pit_mode='apply_vasicek'` exige **siempre** `systemic_factor_col`: se elimina la
  exención de `scenarios.source='forward'`, que suponía un factor sistémico Z que forward **no
  publica** (sus curvas ya son PIT ⇒ `pit_mode='consume_pit'`); (3) aplicar Vasicek sobre una
  term-structure ya etiquetada `pd_basis='pit'` queda bloqueado, evitando el doble ajuste macro
  (espejo del guard que `consume_pit` ya tenía); (4) `forbid_mean_scenario=True` pasa de auditado a
  **bloqueante**, en el config y en el motor, sobre las tres fuentes de escenarios y sin distinguir
  mayúsculas (`mean`/`average`/`weighted_mean_input`) —se ponderan outputs por escenario, nunca
  inputs macro promediados—; el escape hatch `flag=False` sigue disponible y queda auditado. Queda
  además **caracterizada** con tests y golden (sin tocar el motor) la frontera de pesos cero:
  `forward` admite peso 0 y IFRS 9 exige peso > 0; su resolución de fondo es una decisión de política
  pendiente. **Nota de contrato:** ninguna ruta válida cambia de resultado numérico (`config_hash` y
  demo F4 invariantes), pero un config que antes corría degradado ahora aborta. La capa IFRS 9 es
  experimental, fuera de la garantía SemVer 1.x.
- **IFRS 9: la LGD de la capa forward ya no se descarta en silencio.** Si la term-structure trae una
  columna `lgd` con algún valor no nulo, el motor —que en v1 estima la LGD desde el `frame` según
  `IfrsLgdConfig`— declara el descarte con el código **`FALTA-DATO-IFRS-6`**: aparece en los
  `warning_codes` de cada fila, en `card.falta_dato`, en la traza de auditoría `ifrs9_lgd` y como
  frase explícita en el informe. Sólo declaración: las cifras no cambian.
- **IFRS 9: descriptions honestas de `rho_col` y `fail_on_falta_dato`.** Ambas prometían conducta que
  el motor no implementa: `rho_col` decía «sobrescribe rho por fila» pero el motor la rechaza
  fail-fast (guard introducido en este mismo release, ver arriba; correlación heterogénea diferida en
  v1); `fail_on_falta_dato` sugería un modo «marcar FALTA-DATO y continuar» ante Vasicek sin rho/Z
  que no existe (el motor falla en cálculo siempre). Se reescriben las descriptions (y títulos) para
  reflejar la conducta real.
- **Captura y config de la UI: la ruta del dataset deja de ser específica del host.** Con `workdir`
  relativo (el default), la ruta que `run_pipeline` cablea a `data.load.source` se conserva relativa y
  en separadores POSIX, de modo que el mismo config sale idéntico en distintos checkouts y en
  Windows/macOS/Linux; una ruta con ancla (raíz, unidad o UNC) conserva su semántica nativa porque es
  una elección explícita del usuario. Además, la validación de contención del directorio de datasets
  ahora resuelve enlaces simbólicos **también en el directorio**, no sólo en el archivo: un
  `workdir/datasets` symlinkeado fuera del workdir pasaba el control anterior.

### Cambiado

- **Informe HTML con formato editorial (tema `nikodym`, el de fábrica).** El HTML pasa a un layout de
  tres columnas en pantalla —sidebar de secciones con la marca Nikodym, contenido e índice lateral
  «En esta página» con los entregables— sobre las clases ya existentes (portada, lineage, firmas
  SR 11-7, veredicto/callouts, chips de estado, tablas). Los rieles son **de pantalla**: en
  `@media print` el documento colapsa a una columna A4, así que el **PDF (WeasyPrint) queda intacto**.
  El tema `plain` no cambia. El markup del documento —`data-section-id`, orden canónico de secciones,
  `id`/`thead`/`tbody` de las tablas y los literales `config_hash=`/`data_hash=`/`git_sha=`/
  `root_seed=`— se conserva: quien parsea el HTML no se ve afectado.
- **Preset F1 de la UI: la corrida estándar ejecuta validación formal.** `standard_preset()` deja de
  traer `validation: null` y activa discriminación, calibración (Hosmer-Lemeshow + Brier sobre la PD
  calibrada) y estabilidad, reusando lo que ya calculan `performance`/`stability`. El contraste por
  grado y el backtesting quedan apagados (el dataset no trae `grade` ni realizados). Los presets F3
  (CMF) y F4 (IFRS 9) declaran `validation: null` explícitamente: conservan su alcance previo.
- **Demo: badge «Experimental» en la card de provisiones CMF (F3)**, igual que la de IFRS 9 (F4), pues
  ambos motores de provisiones son experimentales por madurez.
- Bump de versión 1.3.0 → 1.4.0.

## [1.3.0] — 2026-07-17

### Añadido

- Extra opcional `markov` (`pip install nikodym[markov]`, que provee `scipy`) para el módulo de
  cadenas de Markov (`nikodym.markov`). Los mensajes de dependencia ausente en `markov/*.py` ya
  apuntaban a `nikodym[markov]`; ahora ese extra **existe** de verdad.
- Smoke clean-room del wheel para el preset `f4-ifrs9-retail`. `scripts/smoke_instalacion_pip.py`
  queda **parametrizado por preset** (argumento CLI o variable de entorno), conservando el modo
  scorecard F1 como comportamiento por defecto (el que usa el CI). Sobre una instalación real por
  pip, verifica que la corrida IFRS 9 termina en `done` y produce `provisioning_ifrs9` con staging
  (Stage 1/2/3) y ECL/cobertura.

### Cambiado

- Bump de versión 1.2.0 → 1.3.0.
- Documentación (`docs_site/index.md`, `docs_site/api.md`) y estado del repo (`AGENTS.md`,
  `CLAUDE.md`) reflejan 1.3.0.
- Recaptura de los informes demo (F1 · F3 · F4): el lineage `library_versions.nikodym` de los
  fixtures reporta 1.3.0. Sin cambio de cifras insignia ni del `config_hash` de los presets.

## [1.2.0] — 2026-07-15

### 🔴 Corregido — una regla normativa que afirmábamos y que NO EXISTE

Nikodym declaraba, en el código y en toda su documentación, que la provisión reportada es el
**máximo entre el ECL de IFRS 9 y un "piso prudencial CMF"**, y lo presentaba como **norma citada**.
La fuente era un documento interno de este proyecto que **no citaba ninguna circular**.

Verificado contra el texto oficial del **Compendio de Normas Contables para Bancos** (CMF):

- **Cap. A-2, num. 5** — *"Lo establecido en el Capítulo 5.5 (deterioro de valor) de la NIIF9 (…)
  **no será aplicado respecto de las colocaciones** (…) ni sobre los "Créditos contingentes", ya que
  los criterios para estos temas se definen en los Capítulos B-1 a B-3 de este Compendio."*
  → En Chile, un banco **no calcula ECL de NIIF 9 sobre su cartera de colocaciones**: el B-1 lo
  **sustituye**. No hay nada contra lo que comparar.
- **Cap. B-1, hoja 10-11 (Circular N° 2.346 / 06.03.2024)** — *"La constitución de provisiones se
  efectuará considerando **el mayor valor obtenido entre el respectivo método estándar y el método
  interno**. (…) Esta regla se deberá aplicar **para cada institución en Chile que consolida con el
  banco**."*
  → La regla del máximo es **estándar vs. interno**, a nivel de **entidad**.

**`max(CMF, IFRS 9)` no es "el piso prudencial de la CMF"** y deja de presentarse como tal en todas
las superficies. El comparativo entre ambos marcos **se mantiene** —es útil, por ejemplo, para una
filial que reporta ECL a su matriz extranjera— pero declarado como lo que es: un comparativo entre
marcos contables, **sin norma chilena que lo exija**.

### 🔴 Corregido — el motor subprovisionaba al deudor refinanciado

El incumplimiento del **Cap. B-1 numeral 3.2** tiene **tres** causales: mora ≥ 90 días, un crédito
otorgado **para dejar vigente** una operación con más de 60 días de atraso, y **reestructuración
forzosa o condonación** parcial. El motor de consumo derivaba **solo la primera**, de la mora.

Consecuencia: un deudor reestructurado o refinanciado **al día** recibía la PI de su tramo de mora
(**6,6 %**) en vez del **100 %** que la norma exige. Sub-provisión de **15×**, y en la dirección que
un regulador no perdona. La columna `is_default` existía en la config y el motor **ya la leía para
los contingentes B-3**, pero en consumo **nunca la consultaba**.

Ahora el motor la lee también en consumo: la columna es **opcional** (sin ella, el comportamiento no
cambia) y sus **nulos se leen como "no marcado"**, de modo que el flag solo puede **sumar**
incumplimiento, nunca quitar el que impone la mora. El incumplimiento se consolida **a nivel
deudor** —la norma arrastra *todos* los créditos del deudor— y la traza de auditoría reporta la
categoría `incumplimiento`, no el tramo de mora, para que el PI de 100 % sea visible.

### Verificado — la matriz de consumo, contra el compendio oficial

Las **23 celdas** de `consumer_standard_v2025` (16 de PI, 6 de PDI y el PI = 100 % de
incumplimiento) se **cotejaron una a una** contra el texto del *Compendio de Normas Contables*,
Cap. B-1 numeral **3.1.3**, hojas 16-18 (Circular N° 2.346 / 06.03.2024). **Coinciden exactamente.**
Sigue **sin ser una validación *de* la CMF** —la Comisión no certifica implementaciones de
terceros—, pero deja de ser una transcripción sin contrastar.

También queda **anclado el benchmark** del dataset `provisiones_consumo`: el índice de riesgo de la
**cartera de consumo del sistema bancario es 8,30 %** (CMF, *Informe del Desempeño del Sistema
Bancario y Cooperativas*, noviembre 2025, sección 2.2). La cartera sintética produce **8,63 %** —
33 pb sobre el sistema. Antes se comparaba contra el **2,59 %** del sistema **completo**, que es el
agregado de todas las carteras y **no es comparable** con una cartera de consumo (consumo va 3,2×
sobre ese agregado).

### Añadido

- **`nikodym.provisioning.internal`** — el motor del **método interno** del Cap. B-1, que faltaba:
  `provisión(g) = Exposición(g) · PD(g) · LGD(g)` por **grupo homogéneo**, tal como la norma lo
  describe textualmente. La PD sale del scorecard calibrado, de modo que **el modelo del banco entra
  por fin en la provisión reportada**. Métodos `pd_lgd` y `direct_loss_rate` (los dos que el B-1
  admite), agrupación por banda de score / segmento / provista, aritmética en `Decimal`, y golden
  verificado a mano al centavo.
- **`provisioning.source_a` / `source_b` / `rule`** — el orquestador compara **fuentes
  configurables** en vez de estar cableado a CMF↔IFRS 9. `rule="use_internal"` implementa la otra
  mitad de la norma: con método interno **evaluado y no objetado** por la Comisión, la provisión se
  constituye según el interno **aunque el estándar sea mayor**.
- **Dataset sintético `provisiones_consumo`** — cartera de consumo con las columnas
  económico-regulatorias que exigen los motores (exposición, mora, deudor con varias operaciones,
  producto, flags de sistema, LGD), coherente por construcción y con tasa de default de un dígito.
- **Capítulo de provisiones en el informe** — un capítulo condicional (`ChapterSpec.requires_domain`)
  que solo aparece cuando la corrida calculó provisiones. Su titular es el número que vende: la
  provisión a constituir y el **sobrecosto del método estándar en CLP** (para la cartera de la demo,
  $388.732.916 por encima de lo que el método interno pediría). Trae las tres tablas agregadas
  (comparación estándar-vs-interno, provisión estándar por categoría, provisión interna por grupo),
  declara la asimetría de consolidación que la norma impone (estándar por deudor, interno por banda
  de score) e imprime los warnings del orquestador. Con el capítulo ya presente, el informe **deja
  de decir** que las provisiones "corresponden a fases posteriores". Como consecuencia, `report`
  ahora corre al final del pipeline (antes su builder nunca veía las cards de provisiones).
- **Las cards de provisiones en `results.json`** — el serializer de la UI expone las tres cards
  (estándar CMF, método interno, orquestador con la regla del máximo) y sus frames **agregados**
  graficables: el desglose del estándar por categoría, el del interno por grupo homogéneo y la
  comparación estándar-vs-interno. Los frames `detail` **por operación** (6.000 filas) jamás entran
  al payload — reventarían `/api/results`. Los `Decimal` contables salen como número, no string.
- **Preset `f3-provisiones-consumo`** + rutas REST — un config listo para correr sin tocar nada que,
  encima del scorecard F1, calcula el método estándar de la CMF, el método interno y la regla del
  máximo estándar-vs-interno a nivel de entidad. El selector del front lo descubre por
  `GET /api/config/presets`; el detalle se pide por `GET /api/config/preset/{id}`. **La calibración
  usa `development_observed`, NO se hereda del F1**: con el `target_pd=0.20` del F1 la PD se inflaría
  3x, el método interno superaría al estándar y la regla del máximo no mordería — un test end-to-end
  corre la cadena entera y falla si el estándar deja de ser el que manda. El delta de provisiones se
  deriva —y se verifica corriendo— con `scripts/derive_provisiones_preset.py`.
- **Capítulos condicionales del informe** (`ChapterSpec.requires_domain`): un informe de scorecard ya
  no puede traer un capítulo de provisiones vacío, ni uno con provisiones declarar que no las cubre.
- **`scripts/gen_schema_fixture.py`** — regenera el fixture del schema de la demo, que hasta ahora se
  actualizaba a mano y se desincronizaba en silencio.

### Corregido

- **Los `Decimal` de provisiones tumbaban `/api/results` entero.** El serializador de la UI no
  conocía `Decimal` (los motores de provisiones trabajan en `Decimal` porque es una cifra contable) y
  su guard de serialización es global: no fallaba la sección de provisiones, fallaba **todo el
  payload**. Igual en el informe, que imprimía `{"unsupported_type": "Decimal"}` donde va la cifra.
- **Coherencia del material público (auditoría adversarial pre-1.2.0).** El informe insignia
  renderizaba el markdown `**mayor valor**` como asteriscos crudos (la prosa va autoescapada), y su
  frase de alcance seguía declarando "solo validación de scorecard" pese a incluir el capítulo de
  provisiones — ahora la salvedad reconoce el capítulo regulatorio (experimental, fuera de SemVer
  1.x). En la landing, el dominio de provisiones se rotulaba "CMF + IFRS 9" con superficie UI cuando
  la pantalla compara **CMF vs. método interno** (IFRS 9 corre en el motor, no en la UI). Y el pie de
  la demo declara ahora que la corrida real usa un **dataset sintético de ejemplo**, no la cartera de
  un banco.

### Nota para quien audite

Los parámetros normativos de las matrices CMF **siguen siendo una transcripción del compendio
asistida por IA, con verificación visual**: no son parámetros oficiales de la CMF ni están validados
por ella, y **requieren validación humana contra la norma vigente antes de cualquier uso productivo**.

## [1.1.3] — 2026-07-13

Release de documentación y metadata. **Sin cambios de código**: el motor es idéntico al 1.1.2.

### Añadido

- Sección **"Quién lo construye"** en el README y en la home de la documentación: el motor lo
  construye Nexo Labs, y hasta ahora ninguna superficie decía cómo llegar a quien lo mantiene.
- `[project.urls]`: `Demo` (demo.nikodym.cl) y el enlace a la consultora en la barra lateral de
  PyPI.

### Corregido

- **`Documentation` apuntaba al propio README** (`#readme`), no a docs.nikodym.cl. Lo mismo en la
  sección "Documentación" del README, que enlazaba a sí misma.
- El enlace a la licencia era **relativo**, y los enlaces relativos se rompen en la página de PyPI
  (el README es la `long_description`).

## [1.1.2] — 2026-07-13

### Corregido

- **`pip install nikodym` no corría: la primera corrida de todo usuario nuevo moría.** Las
  dependencias publicadas declaraban rangos abiertos (`pandas>=2.0`, `scikit-learn>=1.6`), y la
  resolución libre de pip —la que hace cualquiera que instale desde PyPI— traía hoy `scikit-learn`
  1.9, que **eliminó** el `force_all_finite` que `optbinning` invoca (el binning muere con un
  `TypeError`), y `pandas` 3.0, que rompe la serialización de resultados con un 500. El motor no
  arrancaba en 1.0.0, 1.1.0 ni 1.1.1.

  El CI no podía verlo: corre con `uv sync --locked`, que fija `pandas` 2.3.3 y `scikit-learn`
  1.7.2. El techo `scikit-learn<1.8` incluso **ya existía**, pero en `[tool.uv]
  constraint-dependencies` —donde protege al desarrollador y al CI, y no viaja en el wheel—. Ahora
  los techos (`pandas<3`, `scikit-learn<1.8`) están donde el usuario los recibe.

  Se añade el gate que faltaba: el CI instala el wheel **con pip resolviendo libre** y corre el
  preset estándar de punta a punta (`scripts/smoke_instalacion_pip.py`). El smoke anterior solo
  hacía `import nikodym`, y importar siempre funcionaba.

## [1.1.1] — 2026-07-13

### Corregido

- **La base editable se descargaba con todas las imágenes rotas.** `GET /api/report/{run_id}/md`
  entregaba un ZIP con el `.qmd` y **ninguna** figura: el documento citaba sus cinco SVG por ruta
  relativa (`scorecard_report_figuras/…`) y ninguna viajaba en el paquete, así que `quarto render`
  no compilaba y el informe se abría sin gráficos. La causa está en la costura entre dos funciones
  que por separado eran correctas: `runs.save` normaliza el documento a `report.qmd` pero copia la
  carpeta de figuras con el `basename` que el propio `.qmd` referencia, mientras que el empaquetador
  derivaba el nombre de esa carpeta del *stem* del archivo persistido (`report_figuras`), que nunca
  existe. Ahora el ZIP empaqueta las carpetas `*_figuras` que realmente están en la corrida. El test
  del endpoint fabricaba a mano un estado que `save` nunca produce, y por eso pasaba en verde: ahora
  monta el estado real y exige la invariante que importa —toda figura citada por el documento viaja
  en el paquete, con la misma ruta relativa—.
- **La UI ofrecía marcar `json` en los formatos del informe, y marcarlo garantizaba un error.** El
  `Literal` de `BasicReportFormat` seguía declarando `json` pese a que ningún motor lo genera, así
  que `GET /api/schema` lo publicaba en el enum, el multiselect pintaba su checkbox y quien lo
  marcaba se llevaba un `ValidationError` que no tenía forma de prever desde la interfaz. El formato
  sale del enum: lo que la UI ofrece es ahora exactamente lo que la corrida puede cumplir. El
  validador que ya rechazaba los formatos sin motor se conserva como red de seguridad para quien
  amplíe el enum sin cablear la generación. Por coherencia, `json` también sale de
  `ReportOutputFormat`: un formato que no se puede pedir tampoco se puede producir.

## [1.1.0] — 2026-07-13

### Añadido

- **Metodología y Resultados llevan prosa generada y determinista**, redactada con los parámetros
  efectivos de la corrida (método de binning y sus umbrales, criterios de selección, estimación,
  escalado, calibración). Sin red y sin IA: un informe regulatorio no puede variar entre dos
  corridas del mismo modelo.
- **Base editable descargable**: el informe se exporta como `.qmd` (Quarto/Markdown, con front-matter
  y el lineage, para editarlo y compilarlo) y como `.docx` (Word, con estilos de encabezado reales,
  tablas nativas y figuras embebidas). Introducción, Contexto y Conclusiones vienen como
  *placeholders* con guía de qué escribir, ocultables con `report.document.placeholders="hide"`.
- Los formatos `csv` y `xlsx` ahora existen de verdad: exportan las tablas por observación
  (puntaje, PD, datasets WoE) **completas**, y se publican en `ReportResult.data_exports`.
- Extra nuevo `nikodym[docx]` (python-docx, MIT) para el export Word. Entra en el meta-extra `all` y
  en `ui`, así que quien instala `nikodym[all]` o `nikodym[ui]` ya lo tiene. El extra `pdf` sigue
  aparte a propósito: WeasyPrint arrastra Pyphen (tri-licencia con GPL) y el gate de licencias del CI
  lo mantiene fuera del cierre redistribuible.

### Cambiado

- **El reporte pasa de ser un volcado a ser un documento.** Antes emitía una sección por paso del
  pipeline, cada una con su `Payload` y tablas tituladas con el nombre de la variable interna. Ahora
  es un informe de validación: portada con campos de proyecto, resumen ejecutivo (veredicto y
  métricas clave), índice, Introducción, Contexto, Metodología, Resultados, Conclusiones,
  Limitaciones y anexos técnicos. Todo el detalle de antes se conserva: baja a los anexos. Quien
  parsee el HTML o los `section.id` del `ReportManifest` verá otra estructura (el esquema de
  `ReportManifest` no cambió: los campos nuevos de `ReportSection` son aditivos y traen default).
- `report.formats` ya no acepta en silencio lo que no implementa: pedir un formato sin ruta real
  falla con un error explícito en vez de validar y no producir nada. **Cambio incompatible acotado**:
  un config con `json` en `report.formats` —que en 1.0.0 validaba pero no producía archivo alguno—
  ahora falla al cargar.
- Las tablas por observación salen del cuerpo del documento (iban truncadas a 200 filas, sin servir
  ni como dato ni como informe) y pasan a los exports de datos. El informe de referencia de la demo
  baja de 58 a 39 páginas.
- El preset estándar pide los cuatro entregables (HTML, PDF, `.qmd`, `.docx`). Antes pedía solo HTML
  y, como la interfaz no expone dónde cambiarlo, las descargas de PDF y base editable respondían 404
  siempre. `report` es infraestructura, así que el `config_hash` del preset no cambia.
- Las funciones de `nikodym.report.charts` aceptan `fmt="svg" | "png"` y su retorno pasa de `str` a
  `str | bytes`. El default no cambia (`svg`), así que el comportamiento en runtime es el mismo.

### Corregido

- **`ranking_preserved` reportaba rankings rotos que no lo estaban.** Comparaba los rangos con
  igualdad exacta, así que una calibración monótona (`intercept_offset`) que colapsara dos PD
  separadas por ~1e-17 al mismo `float64` se reportaba como ranking degradado, sin que ningún par se
  hubiera invertido. Ahora distingue la inversión de orden y el colapso de deudores que el modelo sí
  distinguía (ambos, `False`) del empate por precisión de coma flotante (`True`). El colapso se sigue
  contando en `ties_created`.
- **Sin las librerías nativas de WeasyPrint, la corrida entera moría.** `pdf.fail_if_unavailable=False`
  promete degradar y entregar el HTML igual, pero solo cubría "WeasyPrint no instalado": las nativas
  ausentes (Pango/HarfBuzz/libffi) escapaban como `OSError` crudo. Es el caso normal de
  `pip install nikodym[pdf]` en macOS o Windows sin Pango.

## [1.0.0] — 2026-07-12

Primer release estable. Congela la superficie pública del **pipeline de validación de scorecard
(F1)** bajo garantía SemVer 1.x (no rompe hasta un 2.0): `nikodym.run`, el config raíz
(`run` → `Study` → `NikodymConfig`) y los dominios `data`, `eda`, `binning`, `selection`,
`scorecard`, `calibration`, `performance` (AUC/KS/Gini), `stability` (PSI/CSI) y el reporte HTML.

### Estable (SemVer 1.x)
- Pipeline scorecard F1 de punta a punta y su config declarativo; audit-trail y reproducibilidad
  (`config_hash`).

### Sigue experimental (fuera de la garantía SemVer 1.x)
- Modelado ML/tuning/explicabilidad, forward-looking, Markov, survival y stress testing.
- Provisiones **CMF** e **IFRS 9/ECL** (motores implementados y deterministas, pero su superficie
  regulatoria aún crece y no está *battle-tested* en producción).
- Validación avanzada (backtesting/discriminación), gobernanza/tracking, formatos de reporte
  PDF/DOCX y narrativa por IA, y los contratos transversales de resultados/métricas/orquestación.

### Changed
- Marcadores de estabilidad por módulo: `Experimental (SemVer 0.x)` → `Estable (SemVer 1.x)` en el
  core F1, y → `Experimental (fuera de la garantía SemVer 1.x)` en la superficie que crece.

## [0.9.0] — 2026-07-10

Primer release público en PyPI. Motor V1 completo (F0–F7) y verde en CI; API pública
versionada como 0.x honesto (puede cambiar hasta la 1.0).

### Incluye
- **Núcleo reproducible** (F0): config declarativo Pydantic v2, `Study`/lineage, audit-trail,
  artifacts *namespaced*, gobernanza SR 11-7.
- **Scorecard (F1)**: binning/WoE monotónico (optbinning), selección, regresión logística,
  scorecard escalado, calibración, desempeño (AUC/KS/Gini) y estabilidad (PSI/CSI).
- **Backends ML (F2)**: XGBoost, LightGBM, CatBoost, tuning (Optuna) y explicabilidad (SHAP)
  como *extras* selectivos.
- **Provisiones**: motores **CMF (Chile)** e **IFRS 9/ECL** separados (provisión = máximo).
- **Forward-looking y stress testing**.
- **UI (F7)**: flujo Scorecard F1 (Datos · Ejecutar · Resultados · Reporte) — React + backend
  FastAPI, con modo claro/oscuro y reporte HTML del modelo.
- **Empaquetado**: publicación en PyPI vía Trusted Publishing (OIDC, sin tokens).

### Detalle de la Fundación (F0)
- Esqueleto del paquete: `pyproject.toml` (uv + hatchling, layout `src/`, 7 deps base,
  extras de usuario y grupos de desarrollo PEP 735), `LICENSE` Apache-2.0, `README`, `CHANGELOG`.
- `nikodym.core.exceptions`: jerarquía de excepciones con raíz `NikodymError` (código
  regulatorio, cobertura objetivo 100 %).
- `nikodym.core.seeding`: `SeedManager` — derivación determinista por nombre vía
  `SeedSequence(entropy=[root_seed, hashlib])` (código regulatorio, cobertura objetivo 100 %).
- `nikodym.core.config`: configuración declarativa (Pydantic v2). `NikodymConfig` *frozen*
  construible sin argumentos, secciones `ReproConfig`/`RunConfig`; `config_hash` (SHA-256 del
  JSON canónico que excluye `INFRA_SECTIONS`, estable e idéntico entre procesos); `load_config`/
  `dump_config` (round-trip YAML con `safe_load`); version-gate `migrate` + decorador `@migration`
  (registro vacío en 1.0.0, cadena lineal validada en import-time). Experimental (SemVer 0.x).
- `nikodym.utils.optional`: `require_extra` / `has_extra` / `EXTRA_TO_DISTRIBUTIONS`
  (import perezoso de extras con mensaje accionable).
- Paths regulatorios declarados (`nikodym.provisioning.cmf`, `nikodym.provisioning.ifrs9`)
  para el gate de cobertura regulatoria; su implementación llega en F3/F4.
- `nikodym.core` (resto de la Fundación, 9 módulos): primer `Study` end-to-end con lineage
  reproducible. `audit` (`AuditEvent`/`AuditKind`/`AuditSink`, `NullAuditSink`/`InMemoryAuditSink`/
  `FanOutSink`); `results` (Protocols económicos `ProvisionResultLike`/`ECLResultLike` con
  `term_structure()`, CT-2); `base` (`BaseNikodymEstimator` raíz propia + 6 familias, semántica
  `get_params`/`set_params`/`from_config` estilo scikit-learn sin heredarlo); `mixins`
  (`AuditableMixin`, `SerializationMixin` con puerta `trust`); `registry`/`artifacts` (registro y
  almacén *namespaced* `(domain, key)`); `steps` (`Step`/`StepAdapter`, `requires`/`provides`, CT-1);
  `lineage` (`LineageBundle`/`RunContext`); `study` (`Study`: orquestador motor v1 con validación de
  prerequisitos CT-1, persistencia en directorio atómico, recarga con verificación de `config_hash`
  y reproducibilidad). Experimental (SemVer 0.x): orquestación y Protocols de resultados crecerán.
- `nikodym.data` (B2a — capa `data`, configuración + endurecimiento, SDD-02 §5): sub-config
  declarativo `DataConfig` (`nikodym/data/config.py`): árbol Pydantic completo (Loading/Schema/Target/
  Missing/Partition), mini-DSL declarativo `Predicate`/`Rule` (allowlist cerrada de operadores, sin
  `eval`), unión discriminada **anidada** de la estrategia de partición (temporal/random/cohort) por
  factory local, `model_validator` de fracciones (suman 1) y de regla no vacía, alias `schema` con
  `populate_by_name`. Endurecido `NikodymConfig.data` de `Any` a `DataConfig | None` (tipado estricto
  para mypy; coerción en runtime vía hook `_DATA_CONFIG_CLS` que `nikodym.data` puebla al importarse —
  el núcleo sigue liviano, no importa `data`). Golden `config_hash` por defecto **invariante**. Deps
  base activadas: `pandera>=0.24` (uso `import pandera.pandas`) y `pyarrow>=14`. Experimental (SemVer 0.x).
