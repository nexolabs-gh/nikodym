# CLAUDE.md — Nikodym RiskLib

@AGENTS.md

> `AGENTS.md` es la fuente de verdad del contexto de trabajo (común a Claude Code y Codex). Mantener ambos coherentes.
> Para arrancar una sesión, leer primero [`HANDOFF.md`](HANDOFF.md).
>
> ## Lo último (2026-08-01 tarde, público `4958b9c`, **CI en curso al cerrar — verificar con `gh`**)
>
> 🔴 **EL HISTORIAL PÚBLICO SE REESCRIBIÓ.** Con OK explícito de Cami se purgaron con `filter-branch`
> + force push dos `.playwright-mcp/console-*.log` commiteados por error el 2026-07-31 —traían
> navegación de Google y de `cmfchile.cl`, o sea por dónde anduvo quien los generó—. **Los SHA
> anteriores al 2026-08-01 17:00 que aparezcan en documentos viejos ya no existen**: `2868490` es hoy
> `a1d40d6` y `f7d4877` es `4af4ecc`. Ningún tag se movió (el último, `v1.10.0`, es del 2026-07-29) y
> PyPI no se tocó. ⚠️ **GitHub sigue sirviendo los blobs por su SHA** tras el force push —su
> recolector no corre al instante, y hay 1 fork—: purga dura es un ticket a Support.
>
> ✅ **P1 CERRADO: el gate de aceptación se verificó de punta a punta con un dataset propio.** Entrar
> por «Scorecard de comportamiento (PD)», contestar sus dos decisiones, subir un CSV de 6.000 filas y
> llegar a **«Corrida completada»** con `report.html` en disco. **D-JOB-7 no se empezó**: se cambió
> por la enmienda del perfil de columnas, decisión de Cami tras medir lo que el gate destapó.
>
> 🔴 **TRES premisas heredadas salieron FALSAS al medirlas, y ninguna se veía leyendo el código.**
> Es la lección de la sesión, y la primera estaba escrita **en este mismo archivo**:
>
> 1. **«`Rule` y `TargetConfig` no son construibles, y por eso el catálogo las publica como mapa».**
>    Falso. `_mapa_de_modelo` (`effective_defaults.py:245`) decide mapa-vs-descriptor mirando **sólo
>    la anotación** y **jamás** consulta `is_required()`. `DataConfig.load` **sí** es construible y
>    también salía como mapa. Aunque `Rule` lo fuera, `bad_rule` seguiría roto.
> 2. **«Es la sección `data`».** Falso: `survival` tiene el defecto idéntico, el mismo mecanismo
>    rompe **cuatro** gestos de estructura —incluido *añadir fila*, que nacía con su regla vacía— y
>    **los diez trabajos nacían con config inválido**, no sólo quien activaba `data` a mano.
> 3. **«Arreglar el catálogo deja el config válido».** Falso, **y a propósito**: `bad_rule` (qué es
>    un moroso en esta cartera) y `partition.strategy` son `DATO-INSTITUCIONAL`. El arreglo cambia un
>    valor inventado que el motor rechaza con jerga por un hueco honesto. De ahí salió la Parte B.
>
> ✅ **Lo que se implementó, en dos enmiendas aprobadas.**
> [`_ENMIENDA-DECISIONES-OBLIGATORIAS.md`](docs/design/_ENMIENDA-DECISIONES-OBLIGATORIAS.md)
> (D-OBL-1…D-OBL-11): el catálogo publica un submodelo obligatorio como **descriptor que conserva sus
> hijos** —`{has_default: false, children: {…}}`—, forma elegida porque **no obliga a tocar
> `canonicalProjection` ni `isDescriptor`**: el nodo nuevo cae por la rama que ya sabía omitir. Y el
> trabajo **pregunta en idioma de negocio** lo que sólo el usuario decide: medido, son **cuatro**
> decisiones en las 14 secciones, derivadas del schema con gate bidireccional.
> [`_ENMIENDA-PERFIL-DE-COLUMNAS.md`](docs/design/_ENMIENDA-PERFIL-DE-COLUMNAS.md) (D-PERF-1…8): una
> columna identificador se avisa **antes** de correr.
>
> 🔴 **El gate de aceptación destapó que NINGÚN trabajo llegaba a `done`, y la suite no lo veía.** El
> esqueleto sembraba `report.sections.required_sections` con el default del motor —ocho capítulos,
> entre ellos `eda`—, pero ningún trabajo declara `eda` y **el formulario ni la ofrece**. El preset F1
> no lo sufría porque declara sus siete a mano. Lo cierra D-OBL-11 recortando a la intersección con
> las secciones del trabajo: el criterio de D-FX-3 aplicado al sitio que faltaba, la siembra.
>
> ⚠️ **Y un golden estuvo a punto de enterrar 28 campos sin comparar.** Al implementar D-OBL-2 el
> conteo de descriptores bajó de 1024 a **996**. No había menos descriptores: el emparejador cortaba
> al ver uno y dejaba de bajar por los hijos de los obligatorios. Moverlo a 996 habría absorbido la
> pérdida en silencio. Va a **1034**, y los 10 submodelos obligatorios quedan **enumerados uno a uno**
> en un test, para que el número no pueda tragarse un onceavo.
>
> ⚠️ **La forma que se pensó para el aviso del identificador NO era posible.** «Que el preflight mire
> la cardinalidad» choca con D-PRE-1 —no lee los datos— y el parquet tampoco la trae:
> **`distinct_count` viene `None`** en todas las columnas, medido; pandas no lo escribe. El perfil
> pasó a ser **un dato que aporta la ingesta** (que ya carga el DataFrame, o sea gratis), persistido
> junto al parquet. `None` sigue siendo «no se sabe», igual que `index_columns`.
>
> ⚠️ **El criterio del aviso no es «cardinalidad alta» sino «TEXTO con casi un valor por fila»**: una
> numérica continua tiene tantos valores distintos como filas y se discretiza sin problema —medido:
> `carga_financiera`, 3.423 valores, corrió bien—. Los dos falsos positivos plausibles tienen control
> negativo, porque un aviso que se dispara de más se aprende a ignorar.
>
> ⚠️ **Ajustar el binning real sobre un frame con columna identificador TUMBA el solver dentro de
> pytest** —crash duro del runner, no un fallo—, así que su test ancla la traducción del mensaje
> contra el literal de OptBinning y no el ajuste. No se investigó.
>
> **Deuda anotada con su medición:** `UiConfig.upload_max_mb` es un campo **muerto** (declara 200 MB,
> nadie lo lee, el tope real son 100 MiB *hardcoded*); `data.schema.unique_keys` se edita como
> **textarea JSON crudo** y no como multiselect de columnas; `injected_artifacts` **no llega al
> informe** pese a la §6.3 de su enmienda; y el perfil de columnas **sólo lo tienen los datasets
> subidos**, no los del catálogo.
>
> **Siguiente: D-JOB-7, con su terreno YA MEDIDO en esta sesión** —no re-medirlo—. Los dos trabajos
> bloqueados sólo necesitan **DataFrames planos** (`calibration.calibrated_pd_frame`, y para validar
> un modelo además `scorecard.score`); el hueco son **4 piezas** y no un parámetro, y ⚠️ **`ui/runs.py`
> NO participa** (es sólo persistencia). 🔴 `_pipeline_payload` llama `check_pipeline` **sin
> artefactos**, así que `/api/validate` mentiría justo en el caso que D-JOB-7 habilita; y **no existe
> gate estructural** que obligue a un endpoint nuevo a entrar en `MUTATING_PATHS`/`CREDENTIALED_PATHS`
> — el defecto del preflight se puede repetir con la suite verde. Detalle en `HANDOFF.md`.
>
> ---
>
> ## Lo de la sesión anterior (2026-08-01 mañana, público `a1d40d6` — era `2868490` antes de la reescritura)
>
> ✅ **P1 arrancó: el SDD de la UI por trabajos quedó APROBADO como contrato** y sus dos primeras
> decisiones se implementaron. `docs/design/_SDD-UI-POR-TRABAJOS.md`, D-JOB-1…D-JOB-19.
> **D-JOB-2**: la sesión arranca vacía y pidiendo tus datos; los presets pasan a «ver un ejemplo con
> datos de muestra». **D-JOB-1**: el trabajo elegido decide qué secciones existen — el sidebar de
> «Scorecard» pinta 9 y **ninguna** de IFRS 9, survival o CMF.
>
> 🔴 **Revisar el SDD ANTES de programar encontró cinco huecos, y cerrarlos cambió el trabajo.** Los
> tres que más pesaron: el catálogo de trabajos vive en el **backend** (`ui/jobs.py` + `GET
> /api/jobs`) porque D-JOB-3 exige que lo consuma también el preflight, **que es Python**; elegir un
> trabajo siembra **su esqueleto** y no un config vacío; y **la demo estática sigue sembrada**
> (D-JOB-19), porque no tiene backend ni acepta datos propios.
>
> ⚠️ **`CONFIG_SECTIONS` NO se tocó, y ése es el diseño**: sigue siendo «qué sabe pintar el
> formulario» —con sus cuatro gates de paridad intactos— y el catálogo de trabajos es «qué te muestro
> según a qué viniste». El sidebar filtra el primero por el segundo.
>
> 🔴 **Cinco copys que MENTÍAN con el arranque vacío, y ninguno lo veía un test** —nadie asevera el
> texto de una tarjeta—. El del stepper se corrigió **dos veces**: con un trabajo elegido las
> secciones existen pero falta lo que sólo decide el usuario, así que sólo es opcional con un ejemplo
> cargado.
>
> ⚠️ **`test_ui_no_reimplementa_formulas_de_dominio` es MÁS AMPLIO que su nombre**: veta cierto
> término de dominio en **todo** el fuente de `nikodym/ui/`, comentarios incluidos. Costó renombrar un
> trabajo del catálogo. Saberlo antes de escribir copy nuevo en esa capa.
>
> ⚠️ **`HANDOFF.md` de la raíz es un SYMLINK a `privado/HANDOFF.md` y está gitignored en el público.**
> Escribirlo con una herramienta que reemplaza el archivo **rompe el symlink** y deja el HANDOFF
> versionado sin actualizar, en silencio. Editar `privado/HANDOFF.md`, o reponer el symlink después.
>
> ---
>
> ## Lo de la sesión anterior (2026-07-31 noche, público `f501147` · privado `76f4dd9`, **CI 16/16 sobre `45bfe7b`**)
>
> ✅ **Paquete D cerrado: la interfaz ya muestra el config que se va a ejecutar.** D1 filtra
> `ReportStep.requires` por los dominios ACTIVOS de la invocación —vía un hook genérico del resolver,
> `from_config_with_context`, sin un solo `if name == "report"` en el núcleo— y D2 publica
> `effective_defaults` en `GET /api/schema` para que el formulario pinte el valor efectivo **sin
> materializarlo**. Verificado en vivo con Playwright, no sólo con tests. Gates: 4.670 passed,
> vitest 408/408, mypy 243, cobertura regulatoria 100 %, bundle reproducible.
>
> 🔴 **La lección técnica que hay que llevarse: el valor efectivo de un campo NO siempre sale de su
> `FieldInfo`.** `MLConfig.hyperparameters` declara `None` y un `model_validator(mode="before")` lo
> rellena con siete hiperparámetros, así que el catálogo publicaba `null` donde el motor corre con el
> dict. Para toda clase construible la fuente es `Cls().model_dump(mode="json", by_alias=True)`. Lo
> encontró la **revisión adversarial**, no la suite — cuarto paquete seguido en que ocurre.
>
> ⚠️ **Y el gate que debía cazarlo no podía: las 22 clases raíz de sección NO están en `$defs`** (el
> schema compuesto las empotra inline), así que un barrido sobre `$defs` dejaba fuera 224
> descriptores. Todo gate que recorra el schema compuesto tiene que mirar las **dos** coordenadas.
>
> 🔴 **EL EJE DEL PROYECTO CAMBIÓ: de corrección a producto.** Cami señaló cinco cosas de la interfaz
> que son **un solo problema** —la aplicación asume que vienes a ver una demostración— y añadió el
> requisito de LATAM. El orden vigente ya NO es el del plan anterior: vive en
> **`privado/ROADMAP-CONSOLIDADO-2026-07-31.md`**.
>
> 1. **P1 · UI por trabajos y datos propios primero.** El sidebar mapea las 14 secciones sin filtro
>    (`web/src/App.tsx:138`) y la sesión arranca sembrando el preset **con su dataset sintético**
>    (`web/src/lib/bootstrap.ts:116-120`). Diseñado en `docs/design/_SDD-UI-POR-TRABAJOS.md`,
>    D-JOB-1…D-JOB-14, **borrador con sus cuatro decisiones ya tomadas**.
> 2. **P2 · Validar un modelo existente**, decidido por delante de E/G/H1: la puerta de entrada más
>    barata para un banco. Hoy la ruta no existe.
> 3. **P3 · Un estándar, y cada país se adapta encima.** Reuniones en Bolivia, Chile, Perú, Colombia
>    y Ecuador. Perseguir cada circular y cada RAN es insostenible: el núcleo expone el motor
>    estándar y **la jurisdicción es DATO**, no código. CMF pasa a ser el primer ejemplo del
>    mecanismo, no el mecanismo.
> 4. **P4 · LGD modelada: medido, es conectar y no construir.** `LgdEngine`
>    (`provisioning/ifrs9/lgd.py`) ya ofrece `beta_regression`, `fractional_response` y `workout`, y
>    admite `covariate_cols` arbitrarias —o sea columnas WoE— sin tocarlo. Falta que
>    `provisioning_internal` pueda delegar en él. ⚠️ El árbol de regresión sigue sin existir y hay
>    razón escrita para no añadirlo a la ligera: la LGD es **bimodal**, «nunca OLS plano».
>
> ⚠️ **No falta capacidad: falta exponerla.** El motor YA corre trabajos aislados (`data →
> provisioning_internal` es ejecutable con la PD inyectada por la puerta del paquete B) y YA ofrece
> **50+ puntos de elección metodológica implementados**. La puerta HTTP/UI quedó fuera del paquete B
> a propósito, y es lo que desbloquea los trabajos por área.
>
> ⚠️ **`git checkout -- <archivo>` restaura desde el ÍNDICE**: con un cambio ya `git add`-eado
> descarta en silencio las ediciones posteriores. Costó reaplicar el arreglo de un bloqueante.
>
> ---
>
> ## Lo de la sesión anterior (2026-07-30 mediodía, `423e1a6`, **sin un solo cambio de código en la sesión**)
>
> 🔴 **El material de cámara del webinar está TERMINADO y verificado ejecutándolo**: dos notebooks,
> el guion minuto a minuto, una presentación de 12 láminas en HTML y dos YAML de respaldo. Vive en
> `~/Downloads/webinar-nikodym-hmeq/` y versionado en `privado/webinar-material/` **con sus tres
> generadores**, que son la fuente: los `.ipynb` y los YAML se regeneran, no se editan a mano.
>
> 🔴 **La validación formal de HMEQ cierra en `fail`, y el informe lo publica en su resumen
> ejecutivo** («2 de 3 tests fallidos · Falla técnica»). Hosmer-Lemeshow rechaza en desarrollo
> (p = 0,0017) y holdout (p = 0,0029) y pasa en OOT (p = 0,168). **No es un defecto**: HL castiga el
> tamaño de muestra, la calibración en nivel es exacta (19,7142 % contra 19,7142 %, Brier 0,081) y la
> discriminación no está en duda. Hay que **decirlo antes de abrir el informe en cámara**; bien
> contado es el mejor argumento de credibilidad que tiene la demo.
>
> ✅ **El config mínimo funciona: se declara el target y el resto se infiere.**
> `binning.feature_columns = "*"` (el **default** del motor) + `exclude_columns=["BAD"]` +
> `categorical_columns=[]` dan **exactamente el mismo resultado** que enumerar las doce variables
> —mismas 9 finales, mismos AUC— y `REASON`/`JOB` se reconocen categóricas por su tipo. En la
> interfaz es el interruptor «Todas las variables disponibles», que baja **Optimal Binning de 21
> clicks a 3** y el recorrido completo de ~50 interacciones a ~20. `config_hash` pasó a
> **`e5868bd6…`** (el `data_hash b6c9f33a…` no se movió).
>
> 🔴 **Y ahí un defecto REAL del motor, medido y sin corregir: con `feature_columns="*"`, las
> columnas que alimentan el `bad_rule` NO se excluyen.** `BAD` entró al binning como variable; aquí
> quedó neutralizada por casualidad (IV 0,0000, un bin), pero con una regla «más de 90 días de mora»
> la columna de mora entraría como predictor: **fuga con AUC inflado**. Causa localizada:
> `_structural_columns` (`binning/step.py`) excluye `target_col`, que es la columna **derivada**
> (`target`), no los insumos de la regla — que son inferibles del propio config. Va por SDD: cambia
> comportamiento y mueve hashes.
>
> ⚠️ **Hay DOS kernels de Jupyter llamados «nikodym» y hasta hoy sólo uno generaba PDF.** JupyterLab
> autodetecta el del venv y lo bautiza con el nombre del entorno (`display_name` «nikodym
> (3.12.13.final.0)», `name: python3`), así que el menú ofrecía dos entradas indistinguibles y una no
> llevaba `DYLD_FALLBACK_LIBRARY_PATH`: con ésa **la corrida termina `done` y sólo falta el PDF**. Se
> le añadió el bloque `env` a `.venv/share/jupyter/kernels/python3/kernel.json`; **si se recrea el
> venv hay que reponerlo**. Y ojo: Jupyter se instaló con `uv pip install jupyterlab` fuera de
> `pyproject.toml`, así que **un `uv sync` lo borra**.
>
> ⚠️ **Dos lecciones de método que costaron una ejecución fallida:** (a) **quitar una defensa por
> limpiar el copy** convirtió un fallo menor en desastre — la celda del informe hacía
> `Path(rep.pdf_path)` sin comprobar `None`, y sin el `assert` del estado de la corrida un fallo en
> `run` encadenaba quince errores que escondían la causa; (b) **`Mismatch` expone `path`/`message`,
> no `field`/`reason`**, y los `.py` del plan B traían esa línea mal desde siempre sin que se notara,
> porque **sólo se ejecuta cuando hay desajustes**, o sea justo cuando importa.
>
> ⚠️ **`check_dataset` da 18 desajustes por código y 19 por interfaz, y ambas son correctas:** el
> 19.º es `index_col`, que sólo se emite pasando `index_columns=[]`. Omitirlo significa «no lo sé».
>
> ⚠️ **Nikodym tiene identidad de marca canónica en `web/src/styles/tokens.css`** (navy `#051528`,
> acento `#2e6ff2`, cyan `#4fc3e8` de detalle, Avenir Next + Inter, sombra de la casa), portada 1:1
> desde la web en producción. Cualquier material visual nuevo sale de ahí: la primera versión de la
> presentación se inventó una paleta y no se parecía ni al producto ni a la landing.
>
> ---
>
> ## Lo de la sesión anterior (2026-07-30 madrugada, `3f646ae`, **CI 16/16 confirmado con `gh`**)
>
> 🔴 **EL WEBINAR ES HOY, 2026-07-30, POR LA TARDE. El ensayo está HECHO y lo único que queda es el
> GUION y la PPT** — Cami los puso explícitamente al final, «con los tiempos ya medidos». Están
> medidos: la secuencia de cámara, los tres comandos y las cuatro trampas viven en
> [`HANDOFF.md`](HANDOFF.md).
>
> ✅ **El ensayo D3 salió limpio por los dos caminos, con la máquina descargada** (load 1,31):
> 19 → **0 desajustes** sólo con el formulario, `done` en **10,5 s** por UI y **14,8 s** por código,
> los cuatro formatos, **0 avisos declarados** y **cero defectos nuevos de la aplicación**. AUC
> **0,9175 / 0,8872 / 0,9133**, PSI ≤ 0,0113, los 9 coeficientes con signo correcto.
>
> 🔴 **El hallazgo que CORRIGE al D2: la paridad UI ↔ código es EXACTA.** El D2 dejó escrito que los
> `config_hash` «no calzan y está bien, es el orden de `binning.feature_columns`». Medido: con el
> **mismo esquema declarado**, los dos caminos dan `config_hash e3d75b27…` y `data_hash b6c9f33a…`
> **carácter por carácter**, aunque la UI lea un parquet y el script un CSV. Lo que difería era
> **esquema mínimo contra esquema completo**: el `data_hash` depende del esquema porque declarar un
> `dtype` coerciona la columna, y el hash es del contenido lógico ya cargado. De ahí el script nuevo
> `privado/webinar-hmeq-codigo-minimo.py`, espejo exacto de la versión corta por UI, que **verifica
> la paridad él solo y la imprime**. ⚠️ **Si en cámara se enseñan los dos caminos, va ése**: con el
> de 13 columnas los hashes no calzan (y es correcto que no calcen).
>
> ✅ **Los diez menores del ensayo: resueltos y verificados EN LA PANTALLA**, no sólo con tests
> (§D3-bis del informe). **M1** los mensajes de validación dejan de salir en inglés —se traducen por
> `type`, que es contrato estable de Pydantic, nunca por `msg`— · **M2** cero `id` de DOM duplicados:
> el switch de un campo opcional pasa a `<path>__activar` y declara `data-field-path`, que es por
> donde el salto del preflight alcanza un campo **apagado** · **M3/P6** fuera «Editor JSON (tipo no
> mapeado)», «allowlist cerrada», «BinningProcess», «Estrictez de columnas» · **M4** los cinco
> «Añadir» dicen a qué lista añaden · **M5** el selector de Preset marca «con tus cambios» y **pide
> confirmación antes de resembrar** (antes borraba el trabajo de un click) · **M7** la interfaz
> escribe un `.gitignore` con `*` **dentro de su propio workdir**, que es la clase entera: el nombre
> lo elige quien lanza con `--workdir` · **M10** se acabaron los «Documento / Documento».
>
> 🔴 **Y el barrido de copy destapó 43 ofensores donde el D2 había anotado 4:** 26 descripciones con
> `None`/`True`/`False` en las secciones del formulario, 15 más en las de provisiones, 3 títulos con
> jerga interna y **9 en inglés** («Catálogo de special values», «WoE para missing», «Umbral de rare
> levels»…). ⚠️ **`fieldPlaceholder` cae en la `description`, así que un `None` ahí ES el placeholder
> del input** y se lee sin hover. **No** se tocaron `score`, `target`, `WoE`, `PSI` ni `holdout`: son
> terminología del dominio, y cambiarlas sería reescribir el vocabulario de la interfaz y del informe.
> Lo cierra el gate nuevo `tests/unit/test_copy_del_formulario.py`.
>
> ⚠️ **Tres lecciones que ese gate aprendió DE SÍ MISMO, y valen para cualquier gate del repo:**
> (a) 🔴 su primera versión **daba verde recorriendo CERO campos** —asumí mal la forma de
> `schema_payload()`, que devuelve `{json_schema, defaults, section_order}`—, y «0 ofensores» se lee
> igual que «todo limpio»: por eso ahora exige **>300 campos y tres anclas concretas**; (b) heredar
> sólo `title`/`description` al bajar por un `anyOf` dio **dos falsos positivos**, porque
> `ui_widget: "hidden"` vive en el padre de un `bool | None`; (c) el **título de una lista** se perdía
> al bajar a sus `items`, y ahí vivía «Catálogo de special values» — que sólo se vio leyendo un
> `aria-label` en la pantalla.
>
> ⚠️ **PyPI publica `1.10.0` y los arreglos de esta sesión NO están publicados.** La demo corre del
> árbol local, así que no bloquea nada; pero un tercero que instale hoy se lleva el copy viejo, el
> `id` duplicado y el selector que resiembra sin avisar. **Publicar `1.11.0` es decisión de Cami**
> (cambia comportamiento de UI ⇒ minor, no patch) y exige su OK explícito más la auditoría
> adversarial previa.
>
> ⚠️ **Trampa de CI nueva: un rojo que no es del cambio.** El primer run dio 15 + 1, y el fallo fue
> «Verify vendored license evidence against PyPI» por red del runner (`greenlet==3.5.2: fuente
> inaccesible — SSL: UNEXPECTED_EOF_WHILE_READING`). Ese gate consulta PyPI por HTTP. `rerun --failed`
> → 16/16. **Si falla ese paso y el mensaje habla de red, es reintento, no diagnóstico.**
>
> ✅ **Carpeta de exploración entregada** (pedido de Cami): `~/Downloads/webinar-nikodym-hmeq/` con el
> dataset, los **dos** recorridos comentados paso a paso, un explorador con pandas (WoE e IV a mano) y
> su README. No toca el repo; verificada corriéndola.
>
> ---
>
> ### Lo de la sesión anterior (`9a85a53` + tag **`v1.10.0`**, 2026-07-29): el D2 y el release
>
> 🔴 **EL WEBINAR EN VIVO ES MAÑANA POR LA MAÑANA, 2026-07-30. Y lo que queda NO es programar.**
> Cami lo dijo al cerrar esta sesión: «parto una fresca haciendo **una corrida limpia con el
> dataset**… **no puedo fallar en vivo**». El objetivo de la próxima sesión es **ensayar la secuencia
> exacta de la cámara**, con la máquina descargada, y cronometrarla. La secuencia paso a paso, los
> comandos y las cuatro trampas están en [`HANDOFF.md`](HANDOFF.md).
>
> ✅ **`1.10.0` PUBLICADO en PyPI** (tag `v1.10.0` sobre `9a85a53`, OK explícito de Cami), y **era
> necesario, no cosmético: la demo era irreproducible con lo publicado.** `1.9.0` (= `cd75aa9`) es
> anterior a los seis commits que hacen posible el recorrido por UI, así que **en PyPI los multiselect
> de binning seguían pintando «Sin opciones.»** — el bloqueo que el D1 documentó. Verificado desde
> PyPI en venv limpio con `--no-cache-dir`: 0 desajustes, `done` en 14,5 s, los cuatro formatos con
> `[ui,pdf]` y la portada con sus cinco campos.
>
> ✅ **El P0 del D2 está cumplido: el camino 100 % por UI llega al informe.** 19 desajustes → **0**
> corrigiendo sólo desde el formulario, sin cargar ningún YAML, `done` y los cuatro formatos. AUC
> **0,9175 / 0,8872 / 0,9133**, PSI ≤ 0,0113, los 9 coeficientes con signo correcto, **0 avisos
> declarados**. El recorrido por código quedó escrito en `privado/webinar-hmeq-codigo.py` (11 pasos).
> Informe con tiempos y fricción medida: `privado/WEBINAR-D2-ENSAYO-2026-07-29.md`.
>
> ✅ **El formulario ofrece 14 secciones: entra «Informe», y con ella la portada del entregable**
> (decisión de Cami entre tres opciones con su costo medido). Antes esos cinco campos sólo se
> escribían por YAML o por código, así que el informe del camino UI salía con la primera página en
> blanco. ⚠️ **Llenar la portada NO mueve el `config_hash`**: `report` está en `INFRA_SECTIONS` a
> propósito, porque el informe es presentación y no cálculo.
>
> 🔴 **La auditoría adversarial FRENÓ el release: dos de tres revisores dijeron parar, y tenían razón.
> Tercer release consecutivo en que ocurre.** Lo que encontró estaba **en la pantalla que se abre en
> la demo**, y nada de eso lo veían 4.550 tests verdes:
>
> 1. **Cinco etiquetas visibles SIN hover** en la sección nueva: «Embeder assets», «Timeout IA»,
>    «Máximo tokens entrada», «Variable de API key» y «payload» **en un placeholder** —⚠️
>    `fieldPlaceholder` cae en la `description`, así que **una `description` puede leerse sin
>    hover**—. Más ocho descripciones que empezaban por «True …» sobre interruptores que dicen
>    Activado/Desactivado.
> 2. **Reincidencia EXACTA del defecto corregido horas antes:** el tooltip de `missing_policy` mandaba
>    a elegir «warning» y el selector muestra `error`, `warn`, `skip`. Las opciones se pintan crudas
>    (`String(option)`), así que **todo copy que nombre una opción tiene que usar su literal**.
> 3. **Un mensaje compartido entre botones acusa al que no fue:** pulsar «Word (.docx)» decía «Esta
>    corrida no generó un PDF». El arreglo hace **obligatorio** el parámetro del entregable, sin
>    default, para que no se pueda reintroducir en silencio.
> 4. **`pd.Timestamp("")` y `pd.Timestamp("nan")` devuelven `NaT` SIN levantar**, así que atrapar
>    `ValueError` no bastaba y un `oot_from` en blanco se iba en silencio. Confirmado **corriendo el
>    motor**: muere en `data` con las dos superficies en verde.
> 5. **`[ui]` no declaraba matplotlib** y su formulario ofrece `render_charts` en `True`: funcionaba
>    sólo porque `optbinning` y `lifelines` lo arrastran — **verde por accidente**.
>
> **Y lo que la auditoría REFUTÓ vale igual:** `config_hash` idéntico byte a byte en los tres presets
> y en el YAML del webinar, medido **en caliente y en frío** contra un `git archive v1.9.0`; ningún
> config de fábrica gana avisos; ninguna firma pública cambió; `manifest.path` no se movió.
>
> ✅ **Un defecto real del núcleo, que encontró el recorrido POR CÓDIGO:** `ReportResult.html_path`
> devolvía `reports/reports/scorecard_report.html` —inexistente— cuando `report.output_dir` es
> **relativo**, que es el default del preset F1 y el caso de quien usa la librería por código. La
> interfaz pasa ruta absoluta, así que por ahí no se veía, y **ningún test cubría el caso relativo**.
>
> **Cuatro trampas operativas nuevas que conviene no re-aprender:**
>
> 1. **🔴 La máquina cargada multiplica la corrida por 10.** La misma corrida tarda **14,9 s libre y
>    157,5 s con load average 20**; por UI, 20 s → **206 s**. No es regresión: el camino por código,
>    que no cambió, se degrada igual. Antes de una demo en vivo, cerrar Chrome y las otras sesiones.
> 2. **🔴 `nohup` también se come el `DYLD`.** macOS (SIP) lo borra al exec-utar `/usr/bin/nohup`,
>    igual que con el `/bin/sh` del shebang. La regla buena es más general que «usa `python -m`»: **el
>    primer proceso exec-utado tiene que ser el intérprete**, sin `sh` ni `nohup` en medio.
> 3. **🔴 Tocar `pyproject.toml` sin correr `uv lock` pone 15 de 16 jobs en rojo** (`uv sync
>    --locked`). No es un fallo de tests: ningún job llega a correr uno.
> 4. **⚠️ El minificador emite template literals:** `grep 'key:"report"'` da **cero hits** sobre un
>    bundle correcto. Hay que grepear con backticks — casi costó un P0 falso.
>
> ⚠️ **`[ui]` a secas NO produce PDF, y es diseño:** `[pdf]` (WeasyPrint) nunca entra por la
> transitiva copyleft. A un tercero se le dice **`pip install "nikodym[ui,pdf]"`**.
>
> ---
>
> ### Lo de la sesión anterior (`0ea4cba`, 2026-07-29): las invariantes previas y la jerga de pandera
>
> 🔴 **Y lo que falta NO es código: es el ensayo de punta a punta.** Cami lo dijo así: «me interesa
> sacar una scorecard del dataset y mostrar todos los pasos tanto como en código como en UI», «no nos
> apuremos, hagamos las cosas bien», y **el guion/PPT va al final**. Nadie ha llevado el preset F1
> hasta HMEQ corriendo **entero por el formulario** hasta el informe: el D1 declaró ese camino
> bloqueado (N2), la sesión siguiente arregló la causa pero midió sólo un tramo («18 → 11 desajustes»,
> una corrida `done` tras corregir **una** columna), y encima hay dos commits nuevos —uno de ellos
> añade un aviso en esa misma pantalla—. El primer paso concreto está en `HANDOFF.md`.
>
> **Congelados hasta después del webinar**: B2.4, la recaptura de la demo, vitest→jsdom, la pata de
> release de B2.5, el menor 8 del D1 y las 6 invariantes del censo que no entraron.
>
> ✅ **Playwright de verdad SÍ funciona sobre esta UI** (MCP `mcp__playwright__*`, verificado en esta
> sesión: abrió el `Select` del eje temporal y eligió `none`). La nota anterior sigue siendo cierta
> —`dispatchEvent` sintético no sirve para Base UI— pero **ya no hay que esperar a B2.4 para verificar
> un recorrido en vivo**.
>
> ✅ **El P1 cerrado, y el aviso del HANDOFF anterior era correcto: NO era sólo `stability`.** El
> censo halló **13 candidatas** de la misma clase y **7 se confirmaron en vivo**, todas con
> `check_dataset` **y** `check_pipeline` en verde y la corrida muriendo igual: `oot_from` no
> parseable, `validation.families` vacío, `comparisons`/`partitions` duplicadas,
> `required_sections` sobre un dominio apagado. Entran cinco.
> [`_ENMIENDA-INVARIANTES-PREVIAS.md`](docs/design/_ENMIENDA-INVARIANTES-PREVIAS.md), D-INV-1…D-INV-9.
>
> **Tres decisiones de diseño que conviene no re-litigar:**
>
> 1. **La invariante la declara el dominio que la impone** (`requisitos_incumplidos(columnas)`), no un
>    registro central: mismo criterio que `column_role`, y por la misma razón escrita en
>    `dataset_check.py` —es propiedad de la sección, no un criterio transversal—.
> 2. **Se consume por `check_dataset`, y `check_pipeline` NO se tocó.** La hipótesis «`check_pipeline`
>    es el sitio natural» describe el sitio correcto **para otra pregunta**: esa función resuelve el
>    DAG de pasos. Efecto lateral decisivo a un día del webinar: **cero cambios en el gate del botón
>    Ejecutar** y cero cableado nuevo en el front.
> 3. **Un requisito incumplido avisa, no bloquea** (D-INV-3, sigue D-PRE-5).
>
> ⚠️ **A3 y C2 quedaron fuera CON SU RAZÓN MEDIDA, no por falta de tiempo** (D-INV-8): comprobar
> `stratify_by` daría **falsos positivos** —`Partitioner.suggest` la apunta a `target_col`, columna
> derivada que por definición no está en el CSV—, y `required_sections` es una invariante **entre**
> secciones, que un protocolo por sección no expresa sin el acoplamiento que D-INV-1 evita.
>
> 🔴 **`study.results` resultó un canal MUERTO que sí tiene consumidores.** `ModelCardBuilder`
> (`governance/model_card.py:189`) y `TrackingSink` (`tracking/sink.py:47`) leen de él, así que un
> model card publicado sale **sin métricas** y MLflow recibe vacío; no se ve en la demo porque los
> tres presets traen `governance: null` y `tracking: null` (medido). Se corrigió **el docstring** de
> `nikodym.run`, que mandaba usarlo —ahora apunta a `study.artifacts.get(dominio, clave)`, con
> ejemplo—, y el defecto quedó escrito en `core/study.py`. Llenarlo es contrato, o sea SDD.
>
> **Cuatro cosas más de esta sesión que conviene no re-aprender:**
>
> 1. **🔴 Mirar la pantalla destapó dos defectos de copy que ningún test habría visto, y los dos eran
>    escritos en esa misma sesión:** el aviso por sección decía «nombra una columna que el dataset no
>    tiene» —falso para dos de los cuatro tipos de desajuste— y el mensaje nuevo mandaba a elegir un
>    «ninguno» que **en el selector se llama `none`**, porque las opciones se pintan crudas.
> 2. **🔴 Un hallazgo de censo se verifica MUTANDO el config y corriendo**, no leyendo el código: de 8
>    candidatas probadas, 7 confirmadas y **1 sin veredicto** (la mutación murió en `model_validate`).
> 3. **⚠️ La constante que comparten el aviso y el motor estaba TRIPLICADA** (`evaluator.py`,
>    `step.py` y la que pedía el aviso). Vive ahora en
>    `stability/config.py::TEMPORAL_CANDIDATE_NAMES`, y el test exige que sean el **mismo objeto**.
> 4. **⚠️ Doce tests aseveraban justo lo que había que quitar:** `test_data_schema.py` verificaba los
>    literales de `pandera` en un mensaje que es **copy público**, o sea que los tests defendían la
>    jerga. El error del esquema ya se lee como una frase en español.
>
> ---
>
> ### Lo de la sesión anterior (`987f678`, 2026-07-29): el D1 corrido y el formulario de raíz
>
> ✅ **El D1 se corrió entero (código + UI) y la demo se sostiene:** HMEQ da **AUC 0,918 dev /
> 0,887 HO / 0,913 OOT**, PSI ≤ 0,011, los 9 coeficientes con signo correcto y el informe **sin un
> solo aviso declarado**. Los 9 hallazgos con su `archivo:línea` y los tiempos medidos están en
> [`privado/WEBINAR-D1-ENSAYO-2026-07-28.md`](privado/WEBINAR-D1-ENSAYO-2026-07-28.md).
>
> 🔴 **El PDF no era el `DYLD` que decía la memoria.** `nikodym-ui` tiene shebang `#!/bin/sh`, y
> **macOS (SIP) borra `DYLD_*` al pasar por `/bin/sh`**, así que exportarla no sirve por esa vía —
> verificado con `/bin/sh -c 'echo $DYLD_FALLBACK_LIBRARY_PATH'` → vacío. **El comando bueno es
> `python -m nikodym.ui`** (`pyproject.toml:68` declara los dos entrypoints): con él salen los
> cuatro formatos y cero warnings. `PYTHONHASHSEED=0` mata además el warning de `study.py:245`.
>
> ✅ **Y lo que más vale: el formulario quedó arreglado DE RAÍZ**, por decisión explícita de Cami
> («hay que dejar todo bien, no parches») que descartó el plan B de cargar un YAML. Tres commits
> que cierran una clase entera — **ninguna lista del config queda sin control**:
>
> | commit | qué cierra |
> |---|---|
> | `5969dc0` | el multiselect toma sus opciones del **dataset**, vía `column_role` |
> | `dd8161f` | las **11 listas de objetos** se editan fila a fila, no como JSON crudo |
> | `e688280` | el gate mide el **footprint real** del motor, no una lista escrita al lado |
>
> Medido en vivo con HMEQ sobre el bundle reconstruido: los avisos del preflight que enfocan el
> **campo exacto** pasan de **0 a 18/18**; corregir binning desde el formulario baja los desajustes
> de **18 → 11**; y editar una lista con sus botones deja el config válido y la corrida termina en
> **12,8 s** con «Ejecutar corrida», no «de todos modos».
>
> **Cinco cosas de esta sesión que conviene no re-aprender:**
>
> 1. **🔴 El salto del preflight se arregló SOLO al expandir las listas**, sin tocar una línea de
>    `preflight.ts`: `candidateFieldIds` ya probaba del id más específico al más general «por si
>    algún día las listas se expanden». Escribir la degradación explícita ahorró el trabajo hoy.
> 2. **🔴 `[]` significaba dos cosas y por eso el defecto era invisible:** «no hay nada que elegir»
>    y «no hay lista cerrada». Con opciones que salen del dataset, el segundo es el caso normal.
>    Ahora `[]` = lista abierta ⇒ entrada libre, y «Sin opciones.» sólo aparece si el enum está vacío.
> 3. **🔴 `toggleMultiselect` descartaba los valores fuera de `options`.** Con opciones del schema
>    no se notaba; con opciones del dataset borra el trabajo del usuario en silencio al cambiar de
>    archivo. Ahora se conservan en rojo con «no está en el dataset»: que un valor no calce es lo
>    que el preflight existe para señalar, y el formulario no debe taparlo borrándolo.
> 4. **⚠️ `pnpm typecheck` pasó donde `pnpm build:package` falló** (caché incremental de `tsc -b`):
>    **el gate real del front es el build**, no el typecheck.
> 5. **⚠️ Automatizar la UI con `dispatchEvent` sintético no sirve para Base UI y corrompe el
>    estado** (los `Select` no cambian, y un popup queda abierto bloqueando a Playwright). Dos veces
>    confundí un artefacto de mi robot con un defecto de la app. Un recorrido real exige Playwright
>    de verdad — ⚠️ **y eso ya está disponible**: el MCP `mcp__playwright__*` maneja los `Select` sin
>    problema (verificado el 2026-07-29 por la tarde), así que no hay que esperar a B2.4.
>
> ⚠️ **Un matiz de `column_role` que evita tocar comportamiento sin querer:** `dataset_check.py`
> hace `continue` sobre `derived`/`not_a_column`, así que **clasificar con esos dos roles NO amplía
> el preflight**. Por eso los cuatro `force_*` pudieron declararse gratis; en cambio
> `survival.input.covariate_cols` y `LgdConfig.covariate_cols` **sí** son columnas y declararles
> `input` ampliaría el preflight fuera de F1 (D-PRE-4): quedan **exentos con su razón escrita** en
> `EXENTOS_MULTISELECT`, que es alcance a decidir por Cami, no un olvido.
>
> **La idea del plan —ENSAYAR PRIMERO, ARREGLAR DESPUÉS— se pagó sola.** El D1 se corrió sin
> preparar nada y destapó lo que ningún plan escrito traía: que el PDF no depende del `DYLD` sino
> del entrypoint, que el editor de listas es JSON crudo, y que preflight y `check_pipeline` dan
> verde sobre un config que muere en el paso 8. **El arco narrativo se confirmó y creció**: no son
> «~16» desajustes sino **18**, y ahora los 18 saltan al campo exacto.
>
> ⚠️ **Lo de «HMEQ no trae columna de tiempo» tenía una segunda mitad que nadie había medido.**
> Cambiar a partición aleatoria son **2 clicks** en la UI y mantiene las tres particiones (así que
> no hay que tocar `performance.partitions` ni `stability.comparisons`), **pero**
> `stability.temporal_axis` se queda en su default `"period"` y **aborta la corrida en el paso 8 de
> 10**, con las dos comprobaciones previas en verde. ✅ **Cerrado el 2026-07-29 por la tarde** — y al
> medirlo resultó que no era una invariante sino **siete**: ver el bloque «Lo último» arriba.
>
> ---
>
> ### Lo de la sesión anterior (`cd75aa9`, 2026-07-28 noche): `1.9.0` LIVE en PyPI
>
> ✅ **`1.9.0` PUBLICADO** (tag `v1.9.0` sobre `cd75aa9`, OK explícito de Cami), verificado **desde
> PyPI** en venv limpio con **sólo `[ui]`**: 705 MB, F1/F3/F4 a `done` con informe (3/3), y los dos
> arreglos comprobados contra el artefacto publicado.
>
> ⚠️ **LO QUE MÁS VALE NO ES EL RELEASE: es que la auditoría adversarial lo FRENÓ** y encontró dos
> defectos que 4.522 tests y CI 16/16 no veían. **Segundo release consecutivo en que ocurre.** Lo que
> se publicó no es lo que se iba a publicar por la mañana. Y **las tres sospechas más caras salieron
> REFUTADAS con medición**, que también vale: licencias copyleft por `lifelines` (`[ui] ⊆ [all]`, y
> el lock **no añade un solo paquete**), drift del bundle (rebuild → `git status` vacío) y
> `config_hash` movido por el extra (hash byte-idéntico con las deps pesadas bloqueadas).
>
> 1. **🔴 El preflight decía `compatible=True` sobre un `data.schema.index_col` inexistente**, con
>    `mismatches` y `uninspected` **vacíos** —la señal más fuerte posible— y la corrida muriendo en su
>    primer paso. `index_col` tenía **tres** estados y sólo dos ramas. **La causa era de FIRMA, no un
>    `if` olvidado:** `check_dataset` recibía sólo las columnas, y el índice por definición no está
>    entre ellas, así que un `index_col` correcto era indistinguible de uno inexistente. De ahí
>    `index_columns=`. ⚠️ **`None` significa «no se sabe», no «no hay»**: omitirlo conserva el
>    comportamiento anterior **a propósito**, porque afirmar sin ese dato reintroduce el falso
>    positivo más caro (el dataset del catálogo contra su propio preset). Test en los dos sentidos.
> 2. **🔴 `POST /api/preflight` no exigía token**: 200 y materializaba el parquet a cualquier proceso
>    local, mientras `/api/run` daba 403 en las mismas condiciones. Va en **`CREDENTIALED_PATHS`, no
>    en `MUTATING_PATHS`**: mismas credenciales, pero **sigue vivo con `allow_live_execution=false`**
>    porque comprobar no es correr. ⚠️ Se reportó como **filtración de datos del usuario y NO lo es**:
>    el id de un upload es el **sha256 de su contenido** y `/api/datasets` no los lista.
>
> **Cuatro cosas de esta sesión que conviene no re-aprender:**
>
> 1. **🔴 PyPI recién publicado puede darte el release ANTERIOR y parecer verde.** La primera
>    instalación limpia trajo `1.8.0` con `1.9.0` ya en el índice. **Siempre `--no-cache-dir`.**
> 2. **🔴 Un hallazgo de subagente se verifica en la RUTA REAL antes de reportarlo, y se calibra su
>    gravedad.** El P1 más serio llegó ubicado en `data.load.index_col`, donde **no se reproduce**
>    (422 `extra_forbidden`): vive en `data.schema.index_col`. El defecto era real; la referencia, no.
> 3. **🔴 El gate de ruff son DOS comandos.** Otra vez: `check` pasó y `format --check` marcó 2
>    archivos.
> 4. **⚠️ Un cambio sólo de TIPO en TypeScript no mueve el bundle** —tocar un union en `api.ts` no
>    cambió un byte del `.js`—, así que «toqué `web/`» no implica drift.
>
> ⚠️ **Tres gates eran más débiles de lo que su nombre promete. `test_column_roles.py` quedó
> ARREGLADO el 2026-07-29** (`e688280`): mide el footprint real y se verificó inyectando otra vez
> el rol en `markov`. **Siguen abiertos los otros dos:** el gate del extra `[ui]` sólo itera **5 de
> 12** extras; y `schema.test.ts` deriva sus casos de lo que vigila, así que **`model` se puede
> borrar del formulario con todo el CI verde**.
>
> ---
>
> ### Lo de la sesión anterior (`d842ccd`, 2026-07-28): el preflight se vuelve interfaz
>
> ✅ **El preflight ya es interfaz, no sólo capacidad.** El aviso vive en «Cargar datos» y en cada
> sección de «Configuración»; **un click salta al campo** que hay que corregir; el botón Ejecutar
> cambia de aspecto y **nunca bloquea** (D-PRE-5). Tres decisiones de UX de Cami. El estado vive en
> `appStore` y va **encadenado detrás de la validación** —dispara sólo con `config_hash` en mano—,
> así hereda su debounce y no gasta una llamada por tecleo.
>
> ✅ **Y lo que más vale es la CLASE que cierran los tres arreglos: algo que existe y el usuario no
> puede alcanzar.** La sesión anterior cerró esa clase en el núcleo (la sección opaca); ésta la
> cerró en el producto, en tres capas, y dos dejaron gate:
>
> | capa | existía | el usuario veía | gate |
> |---|---|---|---|
> | capacidad | `check_dataset` + `/api/preflight` | la SPA no los llamaba | la feature *es* el arreglo |
> | formulario | `stability`, sección del camino F1 | el preflight la señalaba **sin pestaña** a la que saltar | `test_column_roles.py` |
> | paquete | el motor completo, tras extras | `pip install nikodym[ui]` levantaba una interfaz que **no corría ninguno de sus 3 presets** | `test_extra_ui_cubre_el_formulario.py` |
>
> **Los dos gates miden deriva contra `CONFIG_SECTIONS`, no listas escritas al lado.** Cuando el
> formulario crezca —hoy el backend expande **24** secciones y el formulario ofrece **13**—, el CI
> exige la pestaña y el extra, o que la sección salga. Verificados inyectando el defecto anterior.
>
> ⚠️ **`[ui]` ya no es «el servidor»: trae lo que su formulario puede ejecutar** (decisión de Cami,
> «no quiero promesas falsas»). Compone `scoring` y `survival`; **310 → 703 MB**. `survival` entra
> porque su sección está en el formulario y `method` es editable —el preset F4 usa `discrete_hazard`,
> pero `kaplan_meier`/`cox_aft` exigen lifelines—; `ml`/`tuning`/`explain`/`markov`/`forward` **no**
> entran porque el formulario no los ofrece; **`[pdf]` nunca entra** (copyleft). Verificado
> instalando el wheel en venv limpio con **sólo `[ui]`**: 0/3 → 3/3 presets a `done` con informe.
>
> ✅ **B2.5 documentación HECHA** (el nodo queda **PARCIAL**: falta su pata de release). Al comando
> `nikodym-ui` sólo se llegaba leyendo el `pyproject.toml`.
>
> **Cinco cosas de esta sesión que conviene no re-aprender:**
>
> 1. **🔴 Un salto por `path` se verifica en el DOM, no comparando strings.** Dos defectos que ningún
>    test de strings habría cazado: el formulario **no expande las listas de objetos** —de
>    `data.schema.columns[0].name` no hay control, hay uno para la lista entera— y el foco caía al
>    `body` en **8 de 15** desajustes; y un campo **opcional apagado** se pinta como switch, con el
>    `id` en un checkbox `aria-hidden` en `position: fixed`. Lo resuelven `candidateFieldIds` y
>    `controlVisible` (`web/src/lib/preflight.ts`, `App.tsx`).
> 2. **🔴 `ConfigError` no hereda de `ValueError`**, así que Pydantic no lo envuelve y escapa entero:
>    `/api/validate` —contrato «siempre 200»— devolvía **500**, y el front lo mostraba como «Backend
>    no disponible», que es falso. **Seis `config.py` lo levantan al validar**, así que se traduce en
>    el endpoint, no por sección: `validate` → `valid=false`; `preflight`/`run`/`to-yaml` → 422.
>    `from-yaml` ya lo hacía y es el precedente.
> 3. **🔴 El gate de ruff son DOS comandos:** `ruff check .` **y** `ruff format --check .`. Correr
>    sólo el primero costó un CI rojo en `Quality`.
> 4. **⚠️ Un efecto que depende del `config` dispara con el hash del render anterior.** El preflight
>    salía con el config nuevo y el `config_hash` viejo → 422 en cada tecleo. La dependencia correcta
>    es **sólo el hash**, con el config vía `ref`.
> 5. **⚠️ `ConfigTab` no puede tener `useEffect`** —gate de `bootstrap.test.ts`, que protege la
>    regresión UX1—, por eso el foco del salto vive en `App.tsx`.
>
> ---
>
> ### Lo de la sesión anterior (`f3d9f68`, 2026-07-28)
>
> ✅ **El config y tu dataset se comparan ANTES de correr.** `nikodym.check_dataset(config, columnas)`
> y `POST /api/preflight` devuelven **todos** los desajustes de una vez, sin ejecutar nada y sin leer
> los datos. Medido desde PyPI en venv limpio: un CSV con nombres de columna propios exigía **seis
> ediciones del preset F1 en seis lugares distintos**, y el motor las revelaba **de a una** —cada
> corrida fallida destapaba la siguiente—.
> [`_ENMIENDA-PREFLIGHT-DATASET.md`](docs/design/_ENMIENDA-PREFLIGHT-DATASET.md), D-PRE-1…D-PRE-9.
> Es **aditivo**: no toca el `config_hash`, ni el veredicto de `/api/run`, ni comportamiento
> existente. Informa, **no bloquea** (D-PRE-5).
>
> ✅ **La SPA ya lo llama** (cerrado en `473af0a`, ver arriba). Cuando se escribió esta línea
> funcionaba sólo por código y por HTTP, que según la regla del repo es feature a medias.
>
> ✅ **Y lo que más vale de la sesión no es la feature: es el gate de CLASE** (`b968fb3`,
> `tests/unit/test_seccion_opaca_invariante.py`). **Los tres defectos serios de los últimos tres
> releases son UN SOLO defecto con tres disfraces** — `1.7.0` (el `save`→`load` que se rechazaba a
> sí mismo), `1.8.0` (dos `config_hash` según los imports) y el del preflight de esta sesión (decía
> `compatible=True` sobre un config con 17 desajustes). Causa única: **una sección de config existe
> en dos estados —tipada u opaca— y casi ningún consumidor lo contempla.** Los tres se habían
> parcheado donde dolía; ahora el gate exige que cada superficie pública responda **lo mismo** en
> los dos estados, y que todo consumidor nuevo de `NikodymConfig` declare su política (`comprobado`
> con test, o `exento: <razón>`). Verificado reintroduciendo los defectos: se pone rojo.
>
> **Seis cosas de esta sesión que conviene no re-aprender:**
>
> 1. **⚠️ El estado OPACO es el DEFAULT, no un caso raro de procesos mínimos.** `model_validate` no
>    coacciona las secciones salvo que alguien haya llamado `cargar_configs_de_dominio()`; tener
>    `nikodym.binning` importado **no basta**. Eso explica que la misma familia de defectos
>    reapareciera tres veces conviviendo con 4.500 tests verdes.
> 2. **Clasificar un campo por su nombre falla en 5 de 26.** `keep_structural_columns` es un `bool`;
>    `selection.feature_columns`/`exclude_columns` refieren las variables WoE que publica *binning*,
>    no columnas del dataset; y en `stability` conviven `temporal_column` (entrada) y
>    `partition_column` (derivada) con idéntico aspecto. De ahí el vocabulario de cuatro valores
>    (`input`/`derived`/`index`/`not_a_column`) declarado en el propio `Field`, como `ui_help`.
> 3. **🔴 El falso positivo más caro sólo apareció probando EN VIVO.** El esquema Arrow lista el
>    índice como una columna más, así que el dataset del catálogo salía incompatible **con su propio
>    preset**. Un test que pasa los nombres a mano ya los trae separados y **nunca reproduce el
>    estado**; hay que ir contra el parquet real.
> 4. **🔴 Estuve a punto de reportar un cuarto defecto que NO existe.** El gate acusó a
>    `dump_config`; medido, `config_to_yaml` usa `exclude_unset=True` **a propósito y documentado**
>    para ser determinista frente a los imports, y `Study.save()` vuelca el config ya resuelto. Está
>    escrito en el test para que nadie «arregle» esa decisión.
> 5. **⚠️ `cancelled` ≠ `failed` en el CI.** El run cerró en `failure` dos intentos seguidos con
>    **15/16 verdes y ningún job `failed`**: el único no-verde era macOS 3.12 en `cancelled` con
>    `steps: []` —nunca ejecutó una línea— mientras macOS 3.11 y 3.13 pasaban sobre el mismo commit.
>    Al tercer intento consiguió runner: 16/16. **Antes de buscar el defecto, mirar si hay algún job
>    `failed`**; si no lo hay y `steps` viene vacío, es la cola de runners macOS.
> 6. **El preset F1 está acoplado a la forma física de su dataset**, y arreglar sólo `index_col` da
>    **falsa sensación de cierre**: con un CSV fabricado con los nombres exactos del preset basta una
>    edición y corre; con nombres propios faltan cinco más. El tercero real no trae los nombres del
>    catálogo.
>
> ⚠️ **Alcance del preflight: camino F1, a propósito** (D-PRE-4). `provisioning*`, `survival`,
> `markov`, `forward` y `stress` quedan fuera y el gate de cobertura **lo declara** en vez de
> callarlo — una lista corta sin explicación se lee como cobertura total. Ampliarlo es registrar sus
> campos con `column_role`; el mecanismo no cambia.
>
> ✅ **El ROADMAP ya no está stale sobre B2** (corregido en `5662172`/`d842ccd`): B2.3 quedó
> declarado cerrado y su discrepancia del extra `[ui]` —decía componer `scoring` y no lo hacía— está
> resuelta. Lo que sigue abierto de B2 es **B2.4** (no hay clean-room automatizado ni Playwright), la
> **pata de release de B2.5** y el **tercero sin checkout** del criterio de cierre.
>
> ---
>
> ### Lo de la sesión anterior (`1.8.0`, 2026-07-27)
>
> ✅ **`1.8.0` LIVE** (tag `v1.8.0` sobre `2c9ed79`, OK explícito de Cami). **La identidad del config
> dejó de depender de qué módulos hubiera importado el proceso.** El mismo config producía **dos
> `config_hash` distintos** según si la capa de dominio estaba importada: sin ella la sección viaja
> como blob opaco y se canonicaliza **sin normalizar**, así que los defaults que el YAML no traía no
> se materializan. De ese digest cuelgan el lineage, el model card, el informe y el ancla de
> idempotencia de MLflow. Ahora `config_hash` coacciona antes de canonicalizar: la identidad es la
> del config **que se ejecutaría**, la misma semántica que el lineage adoptó en `1.7.0`.
> [`_ENMIENDA-CONFIG-HASH-IMPORTS.md`](docs/design/_ENMIENDA-CONFIG-HASH-IMPORTS.md), D-HASH-1…D-HASH-8.
> Verificado **desde PyPI** en venv limpio, en dos procesos: hashes idénticos con y sin la capa, y el
> round-trip `save`→`load` del P0 anterior sigue cerrado.
>
> **Cuatro cosas de esta sesión que conviene no re-aprender:**
>
> 1. **La premisa con que se priorizó el ítem era FALSA, y medirlo cambió el trabajo.** El pendiente
>    decía «el defecto de `valid`, el único que afecta al usuario mientras trabaja». Medido: por la
>    UI **no se alcanza** —el front no valida hasta recibir el schema (`appStore.tsx:107`,
>    `if (schema === null) return`) y `GET /api/schema` importa los dominios—. A quien afecta es al
>    cliente HTTP directo y al uso por código con `dict`. Y el defecto grave no era `valid` sino la
>    identidad. Van **nueve veces** que el plan escrito no sobrevive a la primera medición.
> 2. **Un cambio de `config_hash` va en MINOR, nunca en patch.** Se propuso `1.7.1` y estaba mal: el
>    precedente del repo es `1.4.0`, que recalculó identidad al excluir `data.load.source` y salió
>    como minor con nota de contrato SemVer (`1.4.1`, en cambio, fue docs y presentación). Un patch
>    se lo lleva quien tenga pin `~=1.7.0` sin decidirlo, y aquí lo que cambia es su clave de
>    idempotencia en MLflow.
> 3. **`config_hash` tiene que seguir siendo TOTAL** (D-HASH-8, salió al programar). Una sección
>    opaca puede llevar un campo que el schema del dominio prohíbe —el blob lo acepta por no conocer
>    su schema—, así que coaccionar puede levantar `ValidationError` donde antes había digest.
>    Propagarlo convertiría en 500 el 200 incondicional de `/api/validate`. Si la coacción falla se
>    devuelve el config sin coaccionar: el error lo reporta el validador, no el hash.
> 4. **Un test puede fallar con el código viejo y aun así ser falso verde.** Uno de los dos tests de
>    regresión pasaba con el código defectuoso porque su valor **esperado** se calculaba en el
>    proceso de pytest, expuesto al mismo estado de imports que el defecto: los dos lados salían
>    malos y coincidían. Lleva ahora un `import` explícito con su razón escrita. Corolario del repo:
>    **los defectos de import se prueban en `subprocess`**, porque dentro de la suite todo está
>    siempre importado.
>
> ⚠️ **El blob opaco del núcleo liviano NO se tocó y es contrato** (SDD-23 §4.1/§9): la coacción vive
> en el hash, no en `model_validate`. `import nikodym.core.config` sigue sin arrastrar dominios y los
> **18** tests `test_core_valida_<X>_como_blob_opaco_sin_importar_<X>` —más los 43 `core_only`— siguen
> siendo la prueba de que no se invadió. Un extra ausente deja su sección opaca **a propósito**: la
> garantía es «el hash no depende del ORDEN de los imports dentro de una instalación dada», no
> igualdad entre instalaciones con distintos extras.
>
> ---
>
> ### Lo de dos sesiones atrás (`1.7.0`, 2026-07-27)
>
> ⚠️ **LO MÁS IMPORTANTE DE ESTA SESIÓN NO ES EL RELEASE: es el P0 que la auditoría previa frenó.**
> `Study.save()` guardaba una corrida **exitosa** que `Study.load()` después rechazaba con
> `ReproducibilityError`, y ni 4.476 tests ni CI 16/16 lo veían. Regresión de `cf217a2`: mover el
> `run_id` antes de resolver (D-ERR-9) se llevó consigo `_build_lineage()`, y **resolver COACCIONA el
> config** (`_coerce_domain_config` materializa los defaults que el YAML no traía), así que el
> lineage congelaba un `config_hash` que el propio `config.yaml` contradecía. Alcance más allá del
> round-trip: el hash del model card, del informe y del ancla de MLflow era el del config *como se
> escribió*, no el que *se ejecutó*. **El lineage se congela ahora DESPUÉS de resolver, en un
> `finally`** que mantiene D-ERR-8 (se cuelga igual si la resolución falla). No tocar ese orden.
>
> **Por qué ningún test lo cazaba, y vale para cualquier defecto de esta familia:** los round-trips
> construyen el config en Python **ya tipado** y los presets escriben **todos** los campos
> explícitos — dos formas de no tener nunca una sección opaca. El caso exige sección opaca (YAML +
> capa no importada) **y** un campo con default omitido. Para montarlo hay que forzar el dict con
> `model_copy` (no el constructor: dentro de la suite la capa ya está importada y se coacciona en la
> raíz, tapando el defecto).
>
> **Comprobar un config tampoco puede sembrar el proceso.** `Study.__init__` llama `apply_global()`,
> que resetea el `random` global y fija el hint `PYTHONHASHSEED` **una sola vez por proceso**. Con
> `/api/validate` llamándolo en cada tecleo, ese hint quedaba anclado a la semilla del config que se
> **editaba**. De ahí `Study(config, apply_global_seed=False)`, que usa `nikodym.check_pipeline`.
>
> **El formulario del UI instalable pasó de 7 secciones a 12**: entran `survival` y las cuatro de
> `provisioning*`. Es el núcleo técnico de la paridad UI↔código (requisito 1), y **no cierra ningún
> nodo de B2** —ver ROADMAP §B2, que lo dice con su criterio—. Cuatro reglas que hay que respetar al
> tocar esto:
>
> 1. **Una sección de dominio viaja como `anyOf: [<objeto>, {"type":"null"}]`**, porque es apagable.
>    `rama_objeto()` (`core/config/schema.py`) es el ÚNICO sitio que conoce esa forma; su espejo en
>    el front es `configSectionSchema()` (`web/src/lib/schema.ts`). Preguntarle `"properties"` al
>    nodo raíz da falso negativo y declara opaco lo que sí se expandió.
> 2. **⚠️ Tocar un `description` o un `ui_widget` de cualquier config obliga a regenerar
>    `web/src/fixtures/schema.json` (`scripts/gen_schema_fixture.py`) Y a rebuildear el bundle**
>    (`pnpm build:package` desde `web/`), porque el fixture viaja dentro del `.js` instalable. Lo
>    exigen el gate G7 (`tests/unit/test_ui_schema_fixture.py`) y el gate de drift del CI.
> 3. **`ui_widget: "hidden"` no se renderiza**, y el vocabulario motor↔front lo vigila
>    `tests/unit/test_ui_widget_vocabulary.py`. Conocía 4 de los 20 literales que emite `src/`.
>    ⚠️ Ese gate **inspecciona 14 de los 20**: recorre bien `properties` de la raíz, pero para
>    `$defs` itera `nodo.values()` y les pide `properties`, que en un schema de def nunca acierta.
>    Hoy da verde legítimo (0 huérfanos), pero **no cazaría un literal nuevo declarado en un campo
>    anidado**; decir que vigila «el vocabulario completo» es hoy una sobrepromesa.
> 4. **El catálogo de secciones navegables vive UNA vez**, en `CONFIG_SECTIONS` de
>    `web/src/lib/schema.ts`; los iconos se quedan en `App.tsx` para que `lib/` no importe React.
>    `F1_SECTIONS` **no** es la lista de lo editable: es sólo la sonda de degradación del schema.
>
> **Y una lección de método que ya se pagó:** el primer usuario del formulario nuevo destapó un
> defecto **del núcleo** que 4.451 tests y CI 16/16 no veían — un config inejecutable no dejaba
> rastro (`status="created"`, `run_id=None`, `error=None`) y la UI devolvía un HTTP 500 opaco, aunque
> el motor produce ahí un diagnóstico exacto. Vivía en el hueco que dejó la enmienda RUN-ERROR: su
> manejo de fallo cubría la EJECUCIÓN de los pasos y no la RESOLUCIÓN del pipeline. Lo cierra
> [`_ENMIENDA-RUN-ERROR-RESOLUCION.md`](docs/design/_ENMIENDA-RUN-ERROR-RESOLUCION.md)
> (D-ERR-8…D-ERR-11). **Abrir una superficie de UI permite armar estados que ningún preset produce**,
> y un test que sólo hace `pytest.raises` no verifica el estado que la excepción deja atrás.
>
> ---
>
> ✅ **`1.6.0` PUBLICADO en PyPI el 2026-07-26** (tag `v1.6.0` sobre `86e121b`, con OK explícito de
> Cami). Cierra la enmienda del horizonte: **la term-structure transporta su unidad temporal** y
> `ifrs9` convierte a años antes de descontar. Verificado instalando **desde PyPI**, no desde el
> árbol: la misma cartera declarada en años y en meses da la misma ECL —desvío 0,00 %, era 40,45 %—.
>
> ⚠️ **Trae dos cambios de comportamiento cuyo default es DETENER, y ambos afectan a configuraciones
> de fábrica.** Quien actualice desde `1.5.0` se topa con esto: (a) una curva sin `time_unit`
> convertible emite `DATO-INSTITUCIONAL-IFRS-7` —y el default de `survival`/`markov` es `"period"`,
> que no es una unidad—; (b) un `horizon_12m_periods` que no dure un año emite `FALTA-DATO-IFRS-8`
> —y su default es `12`, correcto sólo para curvas mensuales—. La salida en ambos casos es declarar
> el dato (una línea) o apagar `fail_on_falta_dato`. Está en el CHANGELOG con ejemplos.
>
> Nikodym `1.5.0` fue el cierre del bloque **B1** (tag `v1.5.0`, 2026-07-22); el proyecto ya no está en construcción por capas sino en mejora continua. El **track pre-Interbank está completo** (IBK-01…05 cerradas); no hay bloque IBK siguiente, y el freeze de artefactos terminó con la reunión del 2026-07-22. El plan vigente son los bloques **B1…B8** del `ROADMAP`: el bloque en curso es **B2** (UI instalable) — ojo, `1.6.0` salió **sin** cerrar B2, porque la corrección de la ECL no podía esperar al bloque; el criterio de cierre de B2 sigue siendo el suyo (ver ROADMAP §B2) y **no** se cumplió con este release. **B2.0, B2.1 y B2.2 están cerrados** (B2.2 —launcher, runtime y seguridad— el 2026-07-24, con los 16 jobs del CI verdes); sus decisiones quedaron **consolidadas en SDD-23 y SDD-25**, así que `docs/design/_ENMIENDA-B2.2.md` es ya registro histórico y no contrato vigente. ⚠️ **Lo que sigue de este párrafo es histórico: decía «el siguiente nodo es B2.3, que exige su propia enmienda antes de programar», y B2.3 quedó CERRADO el 2026-07-28** —el extra `[ui]`, los uploads y los presets funcionan, sin enmienda propia—. Ver el bloque «Lo último» arriba y `docs/ROADMAP.md` §B2.
>
> **Taxonomía de marcas (2026-07-25, ejecutada y publicada):** un aviso declarado se marca
> `FALTA-DATO` si la carencia es **del motor** o `DATO-INSTITUCIONAL` si el dato **lo aporta la
> institución**. El contrato vive en `src/nikodym/core/markers.py` y **ningún filtro debe comparar
> el literal**: se consume `is_declared_warning()`. Un código interno **nunca** va al copy público:
> ahí se explica la limitación en el idioma del lector.
>
> ⚠️ **Cuidado con las cifras de esta taxonomía: circulan dos unidades distintas** (medido el
> 2026-07-25, cierra un pendiente que venía de dos sesiones). El «9 + 2 `pending_items`» y el «34»
> de la enmienda cuentan **fichas de SDD**, y varias de esas fichas son *requisitos de entrada
> documentados que el motor nunca emite en runtime* —de la familia IFRS, por ejemplo, sólo IFRS-4 e
> IFRS-6 se emitían; desde `1.6.0` también IFRS-7 e IFRS-8—. Lo que el motor **nombra** en `src/` son
> **27 códigos: 10 `FALTA-DATO` y 17 `DATO-INSTITUCIONAL`** (medido el 2026-07-26 con el criterio
> del propio gate, `_codigos_del_motor()`; no con un `grep` propio, que da menos). Ése es el
> universo que miden el gate `tests/unit/test_public_copy.py` y
> la página [`docs_site/avisos-declarados.md`](docs_site/avisos-declarados.md). Las dos cifras son
> correctas en su propia unidad; compararlas entre sí no significa nada.
>
> **Copy público NO es sólo la landing y el README** (2026-07-25: creerlo dejó vivos dos defectos).
> Cuenta toda superficie que lea un humano: el **tooltip del formulario del UI instalable** —una
> `description` de Pydantic viaja a `schema.json` y de ahí al `FieldRenderer`—, el panel de
> resultados, la **prosa del informe** HTML/PDF/Word, `docs_site/` y la descripción de un dataset o
> preset que el backend devuelva. **No** cuentan: `warning_codes` y `card.falta_dato` (son el dato),
> las claves de los dicts de labels, los comentarios, los tests, `docs/design/` y el volcado de
> auditoría del anexo del informe —ahí el código es la evidencia y borrarlo falsearía el audit
> trail—. Dos gates lo vigilan: `web/src/lib/public-copy.test.ts` (todo `web/src`) y
> `tests/unit/test_public_copy.py` (`docs_site/` + el `README.md` + el espejo
> `web/src/lib/markers.ts`). **El `README.md` entró al gate el 2026-07-25** (decisión de Cami): los
> códigos salieron de la portada y su documentación vive en
> [`docs_site/avisos-declarados.md`](docs_site/avisos-declarados.md), la página de referencia del
> *output* del motor. Esa página es la **única** exención nueva, por la misma razón que el anexo del
> informe: ahí el código es el dato. Dos tests atan la página al motor en los dos sentidos —un código
> emitido sin documentar, y uno documentado que ya no existe—.
>
> **Contrato de resolución de parámetros (2026-07-25, APROBADO).** El requisito 3 de la visión
> —el dato se provee, se modela o sale del histórico— se diseñó como **contrato transversal**, no
> motor por motor: [`docs/design/_CONTRATO-RESOLUCION-PARAMETROS.md`](docs/design/_CONTRATO-RESOLUCION-PARAMETROS.md).
> El censo del código mostró que el problema no es que falten vías, sino que **cada parámetro ya tiene
> su política de resolución y se contradicen entre motores**. Siete decisiones (CRP-1…CRP-7); EAD entra
> al contrato distinguiendo **resolutor** de **consumidor**.
>
> **B3.a-1 CERRADO el 2026-07-25** (`main` = `1bbf737`, CI verde). Ojo: su premisa original era
> **falsa** y el censo lo demostró — el `Literal` de `governance/config.py:27` no era la llave de
> segmentación de ningún cálculo, y la llave real (`portfolio_col`) ya era `str` libre en los tres
> motores. El bloqueo verdadero era que **nadie declaraba el dominio de valores del segmento**.
> Se reformuló y se implementó como
> [`docs/design/_ENMIENDA-SEGMENTACION.md`](docs/design/_ENMIENDA-SEGMENTACION.md) (D-SEG-1…D-SEG-11,
> de las que **el código cita diez**: D-SEG-11 quedó *sin objeto* por ser consecuencia de D-SEG-1 —si
> el régimen es atributo del motor, no queda config donde omitirlo— y se conserva escrita para el día
> que exista un segundo motor. No la busques en `src/`: no es un olvido):
> esquema de segmentación declarado (normativo / institucional / derivado del dato), que **viaja en
> el resultado** de los tres motores, y régimen garantizado por un **registro régimen→motor con test
> de cobertura** —no por el sistema de tipos, que no puede: ampliar un `Literal` compila igual sin
> motor detrás—. El contrato de resolución de parámetros es el nodo en curso: su §2 quedó enmendado
> y sus dos primeros pasos (CRP-5 y CRP-6 bloque A) están implementados — ver `ROADMAP.md` §B3.
>
> **CRP-6 — CUMPLIDO en las siete capas el 2026-07-26** (bloque A en `368bcf5`, bloque B a
> continuación).
> [`docs/design/_ENMIENDA-CRP6-FLAG.md`](docs/design/_ENMIENDA-CRP6-FLAG.md), D-CRP6-1…D-CRP6-8.
> `fail_on_falta_dato` significa **una sola cosa**: *¿una marca declarada **gobernable** emitida en
> la corrida la detiene?* Dos cosas que hay que saber antes de tocar esto:
>
> - **No toda marca declarada es gobernable.** Una marca es **estructural** si el motor la emite en
>   toda corrida por una capacidad diferida propia —`FALTA-DATO-IFRS-4` aparece **incluso con la EAD
>   entregada por la institución**, medido—. Las estructurales se registran siempre y **nunca**
>   detienen: abortar por ellas dejaría el motor inservible con su propio default. El criterio vive
>   en `core/markers.py::governable_warnings()` y **no se reimplementa con un `if` por motor**. Que
>   no detengan no las absuelve: su arreglo es ampliar la capacidad, y CRP-7 tiene asignada IFRS-4.
> - **El chequeo PIT de `ifrs9` es incondicional** y no lo apaga ningún flag. El contrato mandaba
>   *renombrar* ese flag; medido, su `False` no abría ruta degradada alguna —`_apply_vasicek` levanta
>   igual— y sólo movía la validación al medio del cálculo, que es lo que CRP-5 prohíbe.
>
> El bloque B cerró la capa que faltaba, y otra vez **el plan escrito no sobrevivió a la medición**
> —van seis veces en este repo—:
>
> - **`SUR-1` tiene cuatro emisores**, no sólo `kaplan_meier`: también `cox_aft`, `discrete_hazard`
>   y el propio `step`. Por eso el gate vive en `survival/step.py::_card_from_model` y **no dentro
>   de un motor**: es el único punto donde la capa conoce todas sus marcas.
> - **`survival` no declara ninguna marca estructural.** La analogía con `ifrs9` invita a copiar una
>   lista de estructurales; aquí sería falsa. `SUR-1` y `SUR-3` se midieron **en los dos sentidos**,
>   así que la llamada va con `structural=()` a propósito, dicho en el código para que no se lea
>   como olvido.
> - **El «preset que se contradice a sí mismo» no existía.** Se dio por hecho dos sesiones seguidas
>   que el preset F4 mezcla `fail_on_falta_dato=True` con la carencia `SUR-3`. Corrido sobre su
>   dataset real emite `falta_dato=()`: usa `method="discrete_hazard"` y `SUR-3` sólo la emite
>   `kaplan_meier`. La decisión de declarar los intervalos **se mantuvo con otra razón** —`method`
>   es editable desde el formulario y el preset dejaría de correr al cambiarlo—, y esa razón quedó
>   escrita en el SDD y en el propio preset.
>
> ⚠️ **El P2 quedó fuera y no por orden de trabajo: hoy es inalcanzable.** Sacar al preset F4 de
> `pit_mode="ttc_only"` sólo tiene dos salidas, y ninguna está disponible — `consume_pit` exige una
> term-structure `pd_basis='pit'` que `survival` no produce (habría que encadenar `forward`), y
> `apply_vasicek` exige `rho` **y** `systemic_factor_col`, columna que el dataset
> `ifrs9_retail_latam` no tiene. Es alcance de otra magnitud y espera decisión de Cami.
>
> Lección de método que vale para todo ítem de roadmap: tres de los cuatro puntos que el plan daba
> por bloqueantes eran nomenclatura, y el cuarto describía una contradicción que no ocurría.
> **Medir contra el código antes de planificar.**
>
> **La unidad temporal: CERRADA y publicada en `1.6.0`** (2026-07-26).
> [`docs/design/_ENMIENDA-IFRS9-HORIZONTE.md`](docs/design/_ENMIENDA-IFRS9-HORIZONTE.md) está
> **IMPLEMENTADA**. La curva declara su unidad en una columna `time_unit`, `ifrs9` convierte con
> `core/time_units.py` y publica `time_value` crudo **y** `time_value_years` para que la conversión
> sea auditable. Cuatro cosas que conviene no re-aprender:
>
> - **El catálogo de códigos de SDD-16 §6 es la fuente de verdad de la NUMERACIÓN, no `src/`.** El
>   espacio `IFRS-N` lo comparten las dos marcas, así que un `git grep` da por libres los números de
>   los requisitos documentados. Se estuvo a punto de reutilizar `IFRS-1` —el factor sistémico `Z`—
>   y los dos tests bidireccionales de `test_public_copy.py` habrían quedado **verdes**, porque
>   comparan strings y no semántica. Los códigos nuevos son `DATO-INSTITUCIONAL-IFRS-7` (unidad) y
>   `FALTA-DATO-IFRS-8` (horizonte).
> - **El «modo A» de la §1 de la enmienda es un criterio EQUIVOCADO, y está implementado el modo B.**
>   `H >= T_max` dispara sobre la curva lifetime de doce meses —la config de fábrica, correcta— y
>   como la marca es gobernable, abortaba. Lo que hay ahora verifica contra `time_value_years` que
>   el período del horizonte dure ~1 año. La §1 se conserva sin editar porque describe el
>   diagnóstico previo, pero **no es el contrato**; el contrato está en SDD-16 §8.
> - **Un gate al 100 % puede no probar nada.** `core/time_units.py` entró a la cobertura regulatoria
>   con una justificación que era falsa: sus 78 alias son **un solo statement**, y mutar `monthly`
>   de 1/12 a 1.0 pasaba la suite entera. Lo arregla una tabla alias→canónico **escrita a mano** en
>   el test, nunca derivada del propio dict.
> - **`fail_on_falta_dato` viene en `True`**, así que toda marca gobernable nueva es un cambio de
>   comportamiento para usuarios existentes. La enmienda afirmaba «no rompe a ningún usuario actual»
>   y era falso: 27 tests lo demostraron. Cami decidió mantener el corte tras medirlo.

> **Catálogo de datos externos (2026-07-25, noche).** 42 datasets públicos documentados en
> [`docs/datasets/`](docs/datasets/); los datos viven en `data/externos/raw/` (vetado, **nunca** se
> commitea) y son **efímeros** —`./descargar.sh get` los repone—. ⚠️ **Leer el §0-bis del README
> antes de planificar sobre una fila del catálogo:** once de sus justificaciones prometen casos de
> prueba que ningún motor puede correr hoy, cada uno documentado con `archivo:línea`. Misma lección
> que B3.a-1, ahora aplicada a una fuente externa: **un relevamiento es hipótesis de alcance hasta
> que se mide contra el código.**
>
> **La landing tiene un rediseño evaluado y EN COLA** (`privado/diseno-landing-2026-07-25/`): cuatro
> piezas valen la pena, pero su banda de cifras publica «0 supuestos de país en el núcleo», que es
> **falso** —el censo del contrato encontró 15 puntos y B3.a-2 está diferido a propósito— junto con
> una cifra que se contradice con la propia página y una figura sin fixture detrás. No portarlo sin
> las correcciones de §2 de esa evaluación.
>
> **Auto-desarrollo: SOLO cuando Cami lo pida explícitamente** (skill `/auto-desarrollo-claude`). En trabajo normal, usar workflows y subagentes con normalidad, sin pedir permiso cada vez — ver `AGENTS.md` §Auto-desarrollo. La maquinaria tmux/Codex multi-motor está FROZEN (histórica).
