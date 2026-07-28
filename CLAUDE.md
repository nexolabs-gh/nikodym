# CLAUDE.md — Nikodym RiskLib

@AGENTS.md

> `AGENTS.md` es la fuente de verdad del contexto de trabajo (común a Claude Code y Codex). Mantener ambos coherentes.
> Para arrancar una sesión, leer primero [`HANDOFF.md`](HANDOFF.md).
>
> ## Lo último (2026-07-28, `f3d9f68`, CI verde 16/16, **sin release nuevo**)
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
> ⚠️ **La SPA todavía NO lo llama.** Funciona por código y por HTTP, no por interfaz — y según la
> regla del propio repo eso es feature a medias. Es el objetivo de la próxima sesión, y exige
> decisiones de UX que Cami no ha tomado (ver `HANDOFF.md`).
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
> ⚠️ **`docs/ROADMAP.md:87` quedó stale sobre B2.3**: declara B2.3 sin cerrar, pero medido contra el
> código el extra `[ui]` existe y compone lo que B2.3 pide, `/api/upload` funciona y los tres presets
> corren desde PyPI. Lo que de verdad falta de B2 es **B2.4** (no hay clean-room automatizado ni
> Playwright), **B2.5** (ni el README ni `docs_site` mencionan `nikodym-ui`) y el **tercero sin
> checkout** del criterio de cierre.
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
> Nikodym `1.5.0` fue el cierre del bloque **B1** (tag `v1.5.0`, 2026-07-22); el proyecto ya no está en construcción por capas sino en mejora continua. El **track pre-Interbank está completo** (IBK-01…05 cerradas); no hay bloque IBK siguiente, y el freeze de artefactos terminó con la reunión del 2026-07-22. El plan vigente son los bloques **B1…B8** del `ROADMAP`: el bloque en curso es **B2** (UI instalable) — ojo, `1.6.0` salió **sin** cerrar B2, porque la corrección de la ECL no podía esperar al bloque; el criterio de cierre de B2 sigue siendo el suyo (ver ROADMAP §B2) y **no** se cumplió con este release. **B2.0, B2.1 y B2.2 están cerrados** (B2.2 —launcher, runtime y seguridad— el 2026-07-24, con los 16 jobs del CI verdes); sus decisiones quedaron **consolidadas en SDD-23 y SDD-25**, así que `docs/design/_ENMIENDA-B2.2.md` es ya registro histórico y no contrato vigente. El siguiente nodo es **B2.3** (`[ui]`, uploads y presets), que exige su propia enmienda antes de programar.
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
