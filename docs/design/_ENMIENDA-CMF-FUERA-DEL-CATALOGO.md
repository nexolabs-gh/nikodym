# Enmienda SDD — el caso de referencia sale del catálogo por defecto de la interfaz (D-JUR-9)

> **Estado: PROPUESTA, pendiente de revisión adversarial y del OK de Cami.** Diseño sin código
> (S6). Nace de la decisión de Cami del 2026-09-09 —«CMF sale del catálogo por defecto de la
> interfaz; el motor, sus tests, su evidencia y la página se conservan: D-JUR no se reabre, cambia
> la visibilidad»— y la convierte en contrato medido.
>
> **Base medida:** `main` = `40cb5a3da0d5483be0fcf328beb14796d6025a99` (1.12.0 en el árbol y en
> PyPI). **Autor / Fecha:** Claude Code / 2026-09-09.
>
> **Enmienda a:** [`_VEREDICTO-NORMATIVA-LOCAL.md`](_VEREDICTO-NORMATIVA-LOCAL.md) (D-JUR-1…8,
> añade D-JUR-9), [`_SDD-UI-POR-TRABAJOS.md`](_SDD-UI-POR-TRABAJOS.md) §4 (catálogo inicial;
> D-JOB-8 «la jurisdicción es un atributo del trabajo» y D-JOB-19 «la demo sigue arrancando
> sembrada»), SDD-23 §3.2 (presets estándar) y SDD-28 §«ruta hasta el usuario» (la demo F3).
>
> **No toca:** el motor `provisioning/cmf`, sus 39 archivos de test, sus matrices y su manifiesto,
> la cobertura regulatoria de CI, la página «Aterrizar una norma local», el `config_hash` de ningún
> preset, la regla del máximo (D-MAX), D-JUR-1…8, la puerta H9R ni el arnés. **No autoriza**
> bump, tag, PyPI ni recaptura de la demo.

| Campo | Valor |
|---|---|
| **Enmienda** | D-JUR-9 |
| **Módulos** | `nikodym.ui` (catálogo de trabajos y presets, rutas, ajustes, lanzador), front `web/` (demo estática, fixtures), CI/deploy, documentación pública |
| **Fase** | F7 (UI) sobre F3 (caso de referencia) |
| **Depende de** | D-JUR-1…8, D-JOB-1/3/8/15/17/19, D-EJE-5, D-GOB-9 (la recaptura única de la release) |
| **Lo consumen** | «Empezar» (catálogo gateado), `demo.nikodym.cl`, `deploy.yml`, la landing de `nikodym-ui`, el smoke de instalación |
| **Release** | Cambio observable de producto en una superficie experimental (`ui` sin marca; `provisioning` experimental) ⇒ **minor**, entrada «Cambiado» en el CHANGELOG. Ninguna API estable cambia |

## 0. Qué corrige de lo ya escrito

- **D-JOB-8 sigue vigente y esta enmienda la usa, no la sustituye.** «La jurisdicción es un
  atributo del trabajo» ya está implementada: los dos trabajos CMF declaran `jurisdiction_code =
  "CL"` (`ui/jobs.py:195`, `:346`) y el front los **separa** en un bloque «Normativa local · casos
  de referencia» (`web/src/lib/jobs.ts:303-311`, `LandingLauncher.tsx:469-507`). Lo que cambia es
  el **default**: el bloque deja de aparecer salvo que quien lanza la interfaz lo pida.
- **D-JOB-19 («la demo estática sigue arrancando sembrada») se conserva; cambia CON QUÉ.** Hoy
  siembra F3 (`demo.ts:158`, `:171-173`: «SIEMPRE F3»). Pasa a sembrar F1.
- **HANDOFF (2026-09-09) contaba 4 presets de fábrica y «Empezar» los publica como cuatro**
  (`getting-started.md:207-209`: «los cuatro presets de fábrica —F1 scorecard, F3 provisiones CMF,
  F4 IFRS 9 y F5…»). Tras esta enmienda el catálogo ofrece **tres**; F3 pasa a ser el *preset de
  referencia*, alcanzable por id y por código, no ofrecido.
- **ESPECIFICACIONES §11** dice «demo F1/F3/F4 publicada». Pasa a «demo F1/F4 (y F5 tras la
  recaptura de la release)», con nota «Lectura actual» y sin reescribir la historia.
- **La primera redacción de D-JUR-9.2/9.3/9.4 publicaba por `GET /api/jobs` sólo el catálogo por
  defecto, y eso rompía el YAML propio** (séptima revisión adversarial, 2026-09-09, verificada):
  el front resuelve el trabajo de un YAML importado con `jobForConfig(jobs, config)` —el trabajo
  más pequeño **del catálogo recibido** que contenga sus secciones (`web/src/lib/jobs.ts:727`)—
  y los insumos externos con `requiredExternalArtifacts(job, config)`, que devuelve `[]` sin
  trabajo (`external-artifacts.ts:60-68`). Un YAML de comparación (`provisioning_cmf` +
  `provisioning_internal` con `pd_source="calibration"` + `provisioning`) no habría casado con
  ningún trabajo recibido, la pestaña Datos no habría pedido la PD y el método interno habría
  seguido exigiéndola (`InternalProvisioningStep`): la «compatibilidad del YAML propio» que
  D-JUR-9.4 prometía era falsa. Corregido: **el cable lleva el catálogo completo con la oferta
  marcada** (`offered`), y el front ofrece con la marca y resuelve con todo.

## 1. El estado, medido sobre `40cb5a3`

Censo hecho con Python sobre el árbol (no con `grep` de rótulos con tilde), en los dos sentidos:
qué consume los dos trabajos y el preset, y qué gate se pondría rojo al moverlos.

### 1.1 Lo que sale del catálogo por defecto

| Pieza | Dónde vive | Medido |
|---|---|---|
| Trabajo «Provisiones CMF» (`provisiones_cmf`) | `ui/jobs.py:150-200` | `sections = (data, provisioning_cmf, report, governance)`, `jurisdiction_code = "CL"`, `status = available`, con dos insumos externos (PD calibrada / PD sin calibrar) |
| Trabajo «Comparar provisiones (CMF vs. interna)» (`comparar_provisiones`) | `ui/jobs.py:294-350` | `sections = (data, provisioning_cmf, provisioning_internal, provisioning, report, governance)`, `jurisdiction_code = "CL"`, `available`; sus overrides y la puerta de artefactos son los que D-EJE-4 le dio para que corriera |
| Preset `f3-provisiones-consumo` | `ui/presets.py:739` (`provisiones_preset`), registrado en `_PRESETS` (`:955-960`) en segunda posición | `dataset_id = provisiones_consumo`; enciende `provisioning_cmf`, `provisioning_internal` y `provisioning`; `config_hash = 857b06ee…` |
| Los otros ocho trabajos | `ui/jobs.py` | `jurisdiction_code = None` los ocho; «Stress testing» sigue `unavailable` por `missing_sections = [stress]` |

Sólo esos dos trabajos declaran jurisdicción: la partición del front devuelve exactamente
`["provisiones_cmf", "comparar_provisiones"]` y un gate lo fija (`web/src/lib/jobs.test.ts:1082`).

### 1.2 Todo consumidor, y si cambia

| Consumidor | Qué hace hoy | ¿Cambia? |
|---|---|---|
| `ui/routes.py:706` `jobs_payload` → `GET /api/jobs` (`:1179`) | publica `list_jobs()` entero: 10 trabajos | **Sí, aditivo**: publica los 10 con `offered` (8 en `true`; 10 con el opt-in) |
| `ui/routes.py:716` `presets_index_payload` → `GET /api/config/presets` (`:1184`) | publica `list_presets()`: F1, F3, F4, F5 | **Sí**: F1, F4, F5 salvo opt-in |
| `ui/routes.py:686` `preset_payload` → `GET /api/config/preset/{id}` (`:1194`) | resuelve cualquier id registrado con `get_preset` | **No**: un id explícito es una petición explícita (§3, D-JUR-9.3) |
| `ui/routes.py:323` (avisos de columnas de insumos externos) | recorre `list_jobs()` para indexar `external_artifacts` por clave | **Sí, hacia el catálogo completo**: es un índice por artefacto, no una oferta |
| `scripts/gen_jobs_fixture.py` → `web/src/fixtures/jobs.json` | vuelca `jobs_payload()` (10 trabajos, `jurisdiction_code` en `:2159` y `:5924`) | **Sí**: los 10 con `offered` (2 en `false`); es el respaldo offline y lo que empaqueta la demo |
| `web/src/lib/jobs.ts:303` `particionarPorJurisdiccion` + `LandingLauncher.tsx:484-507` | pinta el bloque de referencia sólo si `porJurisdiccion.length > 0` | **Sí, mínimo**: la partición se aplica sobre `jobs.filter(offered)`; con el catálogo por defecto el bloque desaparece solo y con opt-in reaparece tal cual |
| `web/src/lib/jobs.ts:727` `jobForConfig` y `external-artifacts.ts:60-68` `requiredExternalArtifacts` | resuelven el trabajo y los insumos de un YAML sobre **el catálogo recibido** | **No**: reciben los 10 (D-JUR-9.2); es lo que conserva la puerta de insumos para un YAML propio de referencia |
| `web/src/lib/schema.ts:88` `CONFIG_SECTIONS` (15) | incluye `provisioning_cmf` («Provisiones CMF», `:139-143`) y `provisioning` («Comparación de provisiones», `:157-161`) | **No** con la opción recomendada (§3.2); **sí** (15 → 13) con la alternativa B |
| `web/src/lib/demo.ts` | `PRESET_ORDER = [F1, F3, F4]` (`:152`); `activePresetId = F3_ID` (`:158`); `demoGetPreset` siembra F3 (`:171-173`); importa los 8 fixtures F3 sin sufijo (`:39-41`, `:48-57`) | **Sí**: `PRESET_ORDER = [F1, F4]` (F5 al recapturar), siembra F1, sin imports F3 |
| `web/src/lib/presentation.ts:37-75` `CURATED` | copy curado de F1, F3, F4 y F5 | **No**: la entrada F3 sirve cuando el opt-in lista el preset; sin él es inerte y no daña |
| `web/src/fixtures/demo/` | `preset.json`, `results.json` (`lineage.config_hash = 857b06ee…`, `run_id df491df8…`), `toyaml.json`, `report.{html,pdf,docx}`, `report-quarto.zip` son la corrida F3; `-f1` y `-ifrs9` las otras dos; **no existe F5** | **Sí**: los ocho archivos F3 salen del bundle (§8-2 decide si también del árbol); F5 llega con la recaptura |
| `scripts/frontend_demo_fixture_signatures.json` + `generate_frontend_demo_fixture_signatures.mjs` + `check_frontend_bundle.mjs` | firman y verifican cada fixture del bundle, incluidos los F3 | **Sí**: se regeneran sin los F3 (y con los F5 al recapturar) |
| `scripts/capture_demo_fixtures.py` (`PRESET_ID = f3…`, `:73`) y `tests/unit/test_capture_demo_fixtures.py` | capturador **canónico** de F3, escribe los nombres sin sufijo | **Sí, de rol**: sale de la matriz de `recapture-demo.yml` (`:43-47`) y queda como capturador de referencia, ejecutable a mano; sus guardas siguen verdes |
| `scripts/verify_demo_prose_artifacts.py` (`families = f1, f3, ifrs9`) y `scripts/check_demo_report_copy.py` | verifican la prosa de los tres informes de la demo | **Sí**: `f3` sale de `all` (queda invocable por nombre mientras existan sus archivos); entra `f5` con la recaptura |
| `.github/workflows/deploy.yml:144-153` | verifica en vivo que el bundle **no** contenga «provisiones CMF de Chile» y sí «La normativa local se aterriza encima» | **Sí, aditivo**: además exige que el bundle no contenga el `run_id` ni el `config_hash` de la corrida F3 capturada (D-JUR-9.8); **no** puede exigir la ausencia de «Provisiones CMF» ni del id F3, que el front conserva por D-JUR-9.5 y `CURATED` |
| `.github/workflows/ci.yml:363-371` (smoke del wheel) | corre `smoke_instalacion_pip.py` con `f3`, `f4` y `f5` por `GET /api/config/preset/{id}` | **No**: el id explícito sigue resolviendo (evidencia de que el wheel corre el caso de referencia) |
| `.github/workflows/recapture-demo.yml:43-47` | matriz `f1 / f3 / ifrs9` | **Sí**: `f1 / ifrs9 / f5` (F5 exige un `capture_demo_fixtures_f5.py`, hermano de `_f1.py`) |
| `docs_site/getting-started.md:192-203` (catálogo entre marcadores) | 10 filas, atadas a `list_jobs()` por `test_docs_gobernanza.py:237-267` | **Sí**: 8 filas; el gate obliga |
| `docs_site/getting-started.md:207-212` (nota `[ui]`) | «los cuatro presets de fábrica —F1…, F3 provisiones CMF, F4…, F5…—» | **Sí**: tres presets; F3 se cita como caso de referencia por código |
| `docs_site/norma-local.md` | no dice hoy cómo llegar al caso desde la interfaz (0 menciones a «trabajo», «preset» o «interfaz») | **Sí, aditivo**: gana «Cómo verlo» (por código con `get_preset`, y por interfaz con el opt-in) |
| `docs_site/guias/gobernanza.md:25` («La sección **Gobernanza** está en los **diez trabajos** del catálogo») | cifra a mano, sin gate | **Sí**: «en todos los trabajos del catálogo» (sin cifra: el gate de «Empezar» ya ata la lista; una cifra a mano se pudre) |
| `README.md:36`, `docs_site/index.md:10-11` | enlazan el caso de referencia desde la fila «Provisiones»; el titular ya es neutro (D-JUR-8) | **No** |
| `docs_site/glosario.md:196` («Provisiones CMF (modelo estándar)») | glosa el motor | **No**: es evidencia |
| `docs/ESPECIFICACIONES.md:325` («demo F1/F3/F4 publicada») y `docs/ROADMAP.md:687` (F3) | estado histórico | **Sí**: nota «Lectura actual» |
| `CHANGELOG.md` `## [No publicado]` | — | **Sí**: entrada «Cambiado» |

### 1.3 Gates que hoy fijan lo contrario (nacerían rojos al implementar, que es lo que se busca)

| Gate | Qué fija hoy | Qué le pasa |
|---|---|---|
| `tests/unit/test_jobs_catalogo.py:70` `test_toda_seccion_del_formulario_pertenece_a_algun_trabajo` | toda sección de `CONFIG_SECTIONS` la muestra algún trabajo de `list_jobs()` | con el catálogo por defecto, `provisioning_cmf` y `provisioning` quedan huérfanas → **rojo** hasta medir contra el catálogo completo (§6-2) |
| `tests/unit/test_jobs_ejecutables.py:233-237` | «el catálogo tiene 10 trabajos» y ancla `comparar_provisiones` como disponible | pasa a recorrer el catálogo completo (los 10 siguen ejecutables: D-EJE-5 no se relaja) |
| `tests/unit/test_gobernanza_en_pantalla.py:161-170` `test_los_diez_trabajos_ofrecen_governance_y_la_declaran_latente` | `len(list_jobs()) == 10` y `governance` latente en cada uno | catálogo completo |
| `tests/unit/test_jobs_abanico.py:160-162` `_SECCIONES_DEL_CATALOGO` (derivada de `list_jobs()`) y el gate bidireccional sección ↔ abanico | los bloques de `_ABANICO_POR_SECCION` para `provisioning_cmf` y `provisioning` (`jobs.py:885`) tienen sección en el catálogo | catálogo completo; si no, esos dos bloques quedan huérfanos → rojo |
| `tests/unit/test_portada_sin_jurisdiccion.py:634-679` `test_el_catalogo_publica_todo_el_copy_con_jurisdiccion_del_fuente` | todo literal con jurisdicción del **fuente** de `jobs.py` llega a `list_jobs()` (AST) | catálogo completo: con el catálogo por defecto los 2 trabajos «no se publican» y el gate acusa copy huérfano → rojo; es el gate que veta dejar las entradas muertas en el fuente |
| `tests/unit/test_presets_gobernanza.py:26,35,66` («los cuatro presets»: `audit` encendido, hash inmóvil) | recorren `list_presets()` | catálogo completo (F3 sigue teniendo que cumplirlos) |
| `tests/unit/test_portada_sin_jurisdiccion.py:600-642` `_trabajos_con_jurisdiccion` | deriva los exentos de `list_jobs()` y **exige que no esté vacío** («el caso de referencia se borró del catálogo») | ese assert es el control negativo natural de esta enmienda: se mide sobre el catálogo completo y sigue exigiendo los dos |
| `tests/unit/test_portada_sin_jurisdiccion.py:685` `test_un_trabajo_neutro_no_nombra_ninguna_jurisdiccion` | los 8 neutros no nombran jurisdicción | no cambia |
| `tests/unit/test_docs_gobernanza.py:237` (catálogo de «Empezar» == `list_jobs()`) | 10 filas | 8 filas, en orden |
| `tests/unit/test_ui_presets.py:477-489` `test_list_presets_cataloga_ambos_sin_config` | `[F1, F3, F4, F5]` en orden | `[F1, F4, F5]` por defecto; `[F1, F3, F4, F5]` con el catálogo completo |
| `tests/unit/test_docs_provision_neutra.py:119` `test_todo_preset_del_catalogo_esta_curado_en_el_front` | todo `list_presets()` está en `CURATED` | se mide sobre el catálogo completo (F3 sigue curado) |
| `tests/unit/test_presets_gobernanza.py:86-92` (los tres fixtures de la demo conservan su `config_hash`) | parametriza `results.json` ↔ F3 | pierde la fila F3 y gana `results-f5.json` cuando exista |
| `tests/unit/test_ui_presets.py:246` `_EXPECTED_F3_CONFIG_HASH`, `test_jobs_abanico.py:747-751`, `test_columna_cartera_ambigua.py:131-136`, `test_validate_contrato_200.py:53-56,136`, `test_requisitos_por_contexto.py:47-51`, `test_columna_en_rama_inactiva.py:483`, `test_report_builder.py:968`, `test_ui_routes.py:950-1000`, `test_ui_serializers.py:660` | usan `provisiones_preset()`/`get_preset("f3…")` como oráculo de motor, hash o contrato | **no cambian**: `get_preset` por id sigue resolviendo (D-JUR-9.3) |
| `web/src/lib/jobs.test.ts:1082` («hoy son los dos de CMF») y `demo.test.ts:47-61` (F3 default) | fijan el estado actual | se reescriben: la partición se prueba con un fixture propio con jurisdicción; el `jobs.json` empaquetado debe traer **cero**; la demo siembra F1 |
| `web/src/lib/presentation.test.ts:43-74` | copy curado de F3 | no cambia |
| `tests/unit/test_effective_defaults.py:782-798` `ANCLAS_POR_SECCION` (15 anclas) | una ancla por sección del formulario | no cambia con la opción recomendada; con la alternativa B pierde dos |

### 1.4 Lo que NO depende del catálogo y se conserva sin tocar

`src/nikodym/provisioning/cmf/**` y sus tests, el dataset `provisiones_consumo`
(`ui/datasets.py:212`) y sus tests (`test_ui_datasets.py`, `test_ui_server.py`), la cobertura
regulatoria (`nikodym.testing.regulatory`, job «Regulatory coverage»: los tests del motor que la
sostienen no dependen del catálogo), los literales `_PROVISIONES_SECTIONS` y
`_PROVISIONES_CALIBRATION_OVERRIDE` de `ui/presets.py:562-651` (el F5 **reusa** el bloque
`provisioning_internal` y la calibración: no se pueden borrar sin romper el preset neutro), los
iconos de sección del front (`App.tsx:76-77`), el panel de Resultados que pinta
`provisioning_cmf` con guard por presencia (`ResultsTab.tsx:352-367`) y sus gráficos,
`scripts/measure_readiness_w0.py` (declara una probe F3; ningún workflow lo ejecuta), `docs/normativa_cmf_parametros.md`,
`docs_site/norma-local.md`, el glosario, los tipos y fixtures del front con valores F3 reales
(`results-types.ts:376-386`, `results-format.test.ts:1397-1405`: prueban el **shape** del serializer,
no el catálogo), el copy con jurisdicción que `test_portada_sin_jurisdiccion` ya exime por ser del
motor (`_SECCIONES_CON_JURISDICCION`, `_COPY_DEL_FRONT_CON_JURISDICCION`), y la evidencia de
`landing-evidence.ts:271-272, 345-352` (§1 de la landing publica el caso **como evidencia con
fecha**, que es exactamente el encuadre de D-JUR-7).

## 2. Lo que ya está construido y no hay que inventar

- **El discriminador existe**: `jurisdiction_code` (D-JOB-8), declarado por trabajo y verificado
  en pareja con `jurisdiction_label` (`test_jobs_catalogo.py:154`). Un caso de referencia nuevo
  hereda el comportamiento declarando su jurisdicción, que es lo que debe hacer.
- **La landing ya se comporta bien con cero trabajos de referencia**: el bloque está bajo
  `porJurisdiccion.length > 0 ? … : null`. No hay que tocar un componente.
- **La demo ya tiene selector multi-preset con orden estable** (`PRESET_ORDER`) y el arranque
  sembrado es una inyección (`BootstrapDeps.sembrarAlArrancar`, `bootstrap.ts:127-135`), así que
  cambiar el preset sembrado es cambiar una constante y sus tests.
- **`UiConfig` es el sitio para un ajuste de la herramienta** que no entra al `config_hash`
  (D-UI-3, `ui/settings.py`); `nikodym-ui` ya tiene tres opciones (`--port`, `--workdir`,
  `--no-open`, `ui/__main__.py:62-74`) y el precedente de que una opción **no** existe a propósito
  (`--host`).
- **El gate de «Empezar» ya regenera el catálogo publicado desde `list_jobs()`**; el de la portada
  ya deriva los exentos del propio catálogo; el de la demo ya verifica en vivo el bundle.

## 3. Las decisiones que se proponen

### D-JUR-9 — El catálogo por defecto de la interfaz no ofrece ningún trabajo ni preset con jurisdicción; el caso de referencia se conserva entero y alcanzable

**D-JUR-9.1 · La visibilidad se DERIVA de la jurisdicción, no se declara aparte.** Un trabajo con
`jurisdiction_code` es un *caso de referencia*; un preset cuyo config enciende una sección de un
caso de referencia también lo es. No se añade un campo `visibility`: dos atributos que digan lo
mismo divergen (la lección de D-EST-1). La lista de presets de referencia se declara en
`ui/presets.py` con su razón (`_PRESETS_DE_REFERENCIA = {"f3-provisiones-consumo": "enciende
provisioning_cmf, el motor del caso de referencia (D-JUR-7)"}`) y un gate la ata en los dos
sentidos a las secciones con jurisdicción del catálogo de trabajos: un preset que encienda
`provisioning_cmf` y no esté en la lista pone rojo, y uno listado que no la encienda también.

**D-JUR-9.2 · Dos catálogos en Python, un catálogo en el cable con la oferta marcada.**
`list_jobs(*, incluir_referencia: bool = False)` y `list_presets(*, incluir_referencia: bool =
False)` para quien pregunta «¿qué se ofrece?» (el catálogo de «Empezar», los gates de copy); el
**catálogo completo** es el de hoy y lo usan los gates de ejecutabilidad, abanico y jurisdicción.
Ninguna pieza se borra de `_JOBS` ni de `_PRESETS`: D-JOB-15 (una sola fuente para landing,
sidebar y preflight) y D-EJE-5 (el gate de ejecutabilidad recorre **los diez**) siguen exactos.
⚠️ Corregido tras la séptima revisión (§0): `jobs_payload` —`GET /api/jobs` y el fixture
`jobs.json`— publica **los diez** con un campo aditivo por trabajo, `offered: bool`, derivado:
`jurisdiction_code is None or cfg.casos_de_referencia`. El front **ofrece** los `offered`
(landing, selector de trabajos) y **resuelve** con todos: `jobForConfig` y
`requiredExternalArtifacts` reciben el catálogo entero, para que un YAML propio de referencia
case con su trabajo, pida su PD por la puerta de artefactos y corra.

**D-JUR-9.3 · Ofrecer no es lo mismo que resolver.** Ofrecer es la marca `offered` de
`/api/jobs` y la lista de `GET /api/config/presets` (que sigue filtrando: un preset no se resuelve
desde un YAML, se elige). Resolver es por id o por config: `GET /api/config/preset/{id}` y
`get_preset(id)` siguen resolviendo la referencia —quien escribe `f3-provisiones-consumo` está
pidiendo exactamente eso—, y `jobForConfig` resuelve sobre los diez. Es lo que mantiene verde el
smoke del wheel en CI (`ci.yml:368`) sin que la pantalla lo ofrezca, y lo que deja al usuario
llegar por código como documenta «Aterrizar una norma local».

**D-JUR-9.4 · El opt-in es del lanzador, explícito y de la herramienta, no del experimento.**
`UiConfig.casos_de_referencia: bool = False` (D-UI-3: no entra al `config_hash`) y la opción
`nikodym-ui --casos-de-referencia`. Con ella, los dos trabajos de referencia salen `offered` y
`/api/config/presets` lista F3: la landing vuelve a pintar el bloque «Normativa local · casos de
referencia» **sin cambiar el componente** (la partición por jurisdicción se aplica sobre los
ofrecidos). Sin ella, el usuario que trae su propio YAML con `provisioning_cmf:` sigue viéndolo
entero, con su trabajo resuelto, su insumo pedido y su corrida (D-JOB-17: el config es suyo; el
catálogo no lo ofrece, no se lo esconde). La demo estática no tiene backend: para ella no existe
el opt-in y `jobs.json` lleva los dos de referencia con `offered: false`.

**D-JUR-9.5 · `provisioning_cmf` y `provisioning` se quedan en `CONFIG_SECTIONS` y expandidas en
el schema.** Responde la pregunta abierta en el HANDOFF («¿sección expandida sin trabajo, como hoy
`eda`?»): **no como `eda`**. `eda` está expandida en `schema.json` y **fuera** del formulario; las
dos secciones de referencia siguen **dentro** del formulario, porque el opt-in y el YAML propio
necesitan pintarlas. Lo que cambia es la regla del gate bidireccional del catálogo: «toda sección
del formulario pertenece a un trabajo **del catálogo completo**», y «toda sección que sólo
pertenezca a trabajos de referencia es una sección de referencia» —derivada, hoy exactamente
`{provisioning_cmf, provisioning}`—. El schema no cambia: `_DOMAIN_CONFIG_CLASSES` sigue igual y
`$defs`/hojas del formulario quedan en 104 y 527.

**D-JUR-9.6 · «Comparar provisiones (CMF vs. interna)» sale con su jurisdicción, no con su
motor interno.** El trabajo depende de dos motores, pero su regla es la del Capítulo B-1 (fuente A
= `provisioning_cmf` por defecto, D-MAX) y por eso declara `CL`. El método interno es neutro y
sigue ofrecido en «Provisión interna / LGD», «PD + LGD en una corrida» y «Severidad modelada o
calculada». La comparación IFRS 9 ↔ interno existe por código (`provisioning.source_a =
provisioning_ifrs9`) y **ningún trabajo la ofrece hoy**; esta enmienda no crea ese trabajo ni
abre la regla del máximo a dos internos (D-JUR-1 lo deja fuera con su razón).

**D-JUR-9.7 · La demo pasa a F1 por defecto, con F4; F5 entra con la recaptura de la release.**
`PRESET_ORDER = [F1, F4]`, `activePresetId = F1_ID`, `demoGetPreset` siembra F1 y los ocho
fixtures F3 dejan de importarse. No existe hoy captura de F5 (`web/src/fixtures/demo/` sólo tiene
F3, F1 e IFRS 9), y capturar exige Linux y un OK propio (runbook §5; D-GOB-9). Por eso el estado
**intermedio** de la demo es F1/F4, y el final —F1/F4/F5, con la ficha del modelo— llega con la
**única** recaptura que Cami fijó para la 1.13.0. La matriz de `recapture-demo.yml` pasa a
`f1 / ifrs9 / f5`, con un `capture_demo_fixtures_f5.py` hermano del de F1.

**D-JUR-9.8 · Verificación en vivo negativa sobre lo que la demo OFRECE, no sobre las cadenas
del front.** ⚠️ Corregido tras la revisión adversarial del 2026-09-09: el bundle de la demo se
construye del mismo front, y ese front **conserva a propósito** el rótulo «Provisiones CMF»
(`CONFIG_SECTIONS`, D-JUR-9.5), el id `f3-provisiones-consumo` (`CURATED`, `presentation.ts:17`)
y `schema.json` con el título de la sección; exigir su ausencia literal habría bloqueado todo
deploy conforme. Lo que sí sólo existe en los fixtures F3 es la **corrida capturada**: el `run_id`
`df491df8bb1e48c9a40bbbe474a97938` y el `config_hash` `857b06ee…` de `results.json`, y los
fragmentos firmados de `preset.json`/`report.html`. `deploy.yml` exige que el bundle publicado
**no** contenga ese `run_id` ni ese hash (y sigue exigiendo lo de hoy: sin «provisiones CMF de
Chile», con el subtítulo vigente). Que la demo no **ofrezca** F3 —selector con dos ejemplos,
landing sin el bloque de referencia, siembra en F1— se verifica donde se ve: `demo.test.ts` sobre
`demoListPresets`/`demoGetPreset`, el render estático de la landing con el `jobs.json` empaquetado
(0 trabajos con jurisdicción) y el recorrido en navegador sobre `demo.nikodym.cl` tras el deploy.

**D-JUR-9.9 · Nada del motor se mueve.** Cero archivos borrados en `provisioning/cmf`, sus tests,
sus datos, la cobertura regulatoria, `norma-local.md` ni el glosario. El dataset
`provisiones_consumo` sigue en el registro (alimenta tests del motor y el preset de referencia).
`config_hash` de los cuatro presets: intacto (medido: `ec10eb43…`, `857b06ee…`, `013e69dc…`,
`b36318b5…`; nada de esta enmienda toca un campo de config).

### 3.2 Alternativas evaluadas

| Opción | Qué es | Por qué no |
|---|---|---|
| **A (recomendada)** | Dos catálogos desde una fuente; opt-in del lanzador; secciones de referencia siguen en el formulario | — |
| **B — retirada dura** | Los dos trabajos salen de `_JOBS`, F3 de `_PRESETS`, y `provisioning_cmf` + `provisioning` salen de `CONFIG_SECTIONS` (15 → 13) | Borra la ruta de interfaz al caso que D-JUR-7 quiere **visible como evidencia**; deja muerto el bloque de referencia del front y el gate `test_portada…:600-642` que hoy exige que exista un caso de referencia; obliga a mover `ANCLAS_POR_SECCION`, `_SECCIONES_CON_JURISDICCION` y el barrido del copy del formulario; y un YAML propio con `provisioning_cmf:` pasaría a correr **sin pintarse** (la clase de defecto de D-JOB-18). Sería la única sección con `Step` y config que el formulario no puede mostrar |
| **C — sólo el front** | Ocultar el bloque de referencia detrás de un desplegable «Ver casos de referencia» | Deja los trabajos en `/api/jobs`, en `jobs.json`, en «Empezar» (el gate ata la tabla al catálogo) y en la demo: no es «fuera del catálogo», es «doblado». Además pone la decisión en el front, contra D-JOB-15 |
| **D — bandera de entorno** | `NIKODYM_UI_REFERENCE_CASES=1` en vez de una opción del lanzador | La interfaz no lee variables de entorno para nada de producto; el precedente del repo es la opción explícita del comando (`--no-open`) y el ajuste tipado en `UiConfig` |

## 4. Contratos de datos (I/O)

- `list_jobs(*, incluir_referencia=False) -> list[dict]`: mismo shape por trabajo que hoy más el
  campo aditivo `offered: bool`; el filtro por defecto es `job["jurisdiction_code"] is None`.
- `list_presets(*, incluir_referencia=False) -> list[dict]`: mismo shape; el filtro es
  `id not in _PRESETS_DE_REFERENCIA`. `get_preset(id)` no cambia.
- `jobs_payload(cfg: UiConfig)` publica `list_jobs(incluir_referencia=True)` con `offered` derivado
  del ajuste; `presets_index_payload(cfg: UiConfig)` publica `list_presets(incluir_referencia=
  cfg.casos_de_referencia)`. Hoy no reciben nada; las rutas ya tienen acceso a la `UiConfig` con la
  que se creó la app.
- Front: `Job.offered: boolean` en `jobs.ts`; `JobSelector` ofrece `jobs.filter(offered)`;
  `jobForConfig`, `requiredExternalArtifacts` y `sectionsOfJob` reciben la lista entera.
- `UiConfig.casos_de_referencia: bool = False` (título «Ofrecer los casos de referencia con
  jurisdicción»). Es un ajuste de la herramienta: no aparece en el schema del experimento ni en el
  formulario.
- `GET /api/jobs`: **aditivo hacia el cliente**: los mismos 10 con un campo más; un front viejo
  los ofrece todos, como hoy. `GET /api/config/presets`: menos elementos, misma forma.
- `web/src/fixtures/jobs.json`: 10 trabajos con `offered` (8 `true`); `schema.json`: sin cambio
  (`$defs` 104).
- Demo: `PRESET_ORDER`, `activePresetId`, `demoGetPreset` y los imports de fixtures.

## 5. Casos borde y errores

- **`GET /api/config/preset/f3-provisiones-consumo` sin opt-in** → 200 (D-JUR-9.3). Un id
  inexistente sigue en 404, como hoy.
- **YAML con `provisioning_cmf:` cargado sin opt-in** → sesión sin trabajo y formulario completo
  (D-JOB-17), sección visible y ejecutable. No hay aviso especial: el config es del usuario.
- **YAML con `provisioning_cmf:` cargado con opt-in** → «Cargar un YAML selecciona el trabajo que
  le corresponde» (D-JOB-17): se selecciona «Provisiones CMF» o «Comparar…», como hoy.
- **Demo con `?preset=f3` o un id desconocido** → cae al preset por defecto (F1), como hoy cae a
  F3 (`demo.ts:214-216`).
- **Un trabajo nuevo con `jurisdiction_code`** → nace fuera del catálogo por defecto y dentro del
  completo, sin tocar nada más (es el costo visible que ya describe `test_portada…:604-606`).
- **Preflight de insumos externos** (`routes.py:323`) sobre el catálogo completo: la referencia y
  «Provisión interna / LGD» declaran el mismo artefacto con el mismo `when`; acumular no produce
  falsos positivos (el propio comentario del código lo mide).

## 6. Tests y controles negativos preespecificados

1. **El catálogo por defecto no ofrece jurisdicción**: `list_jobs()` trae 8 trabajos, todos con
   `jurisdiction_code None`; `GET /api/jobs` trae los 10 y exactamente esos 8 con `offered: true`
   (los dos de referencia en `false`); `list_presets()` y `GET /api/config/presets` traen F1, F4,
   F5 en ese orden. **CN**: cambiar el default del parámetro a `True` pone rojo; marcar `offered`
   un trabajo con jurisdicción sin el opt-in pone rojo.
2. **El catálogo completo sigue entero**: `list_jobs(incluir_referencia=True)` trae los 10 en el
   orden de hoy y `list_presets(incluir_referencia=True)` los 4. **CN**: borrar `provisiones_cmf`
   de `_JOBS` pone rojo (y además enrojece `test_portada…:604-606`, que exige un caso de
   referencia); es el gate que impide que «fuera del catálogo» degenere en «borrado».
3. **Gate bidireccional del catálogo, reescrito**: toda sección de `CONFIG_SECTIONS` pertenece a
   un trabajo del catálogo completo; el conjunto de secciones que **sólo** usan trabajos de
   referencia es exactamente `{provisioning_cmf, provisioning}`, escrito a mano. **CN**: quitar
   `provisioning` de «Comparar provisiones» pone rojo por la lista a mano; añadir `provisioning_cmf`
   a un trabajo neutro pone rojo por la derivación.
4. **`_PRESETS_DE_REFERENCIA` atado en los dos sentidos** a las secciones de referencia. **CN**:
   vaciar la lista → rojo (F3 enciende `provisioning_cmf`); añadir F5 → rojo (no enciende ninguna).
5. **Ejecutabilidad de los diez** (`test_jobs_ejecutables`) sobre el catálogo completo, sin
   relajar D-EJE-5. **CN**: pasarle el catálogo por defecto deja el barrido en 8 y el ancla
   `comparar_provisiones` lo pone rojo.
6. **El opt-in funciona de punta a punta**: `create_app(UiConfig(casos_de_referencia=True))` →
   `/api/jobs` con 10 y `/api/config/presets` con 4; `nikodym-ui --casos-de-referencia` lo cablea
   (test del parser). **CN**: ignorar el ajuste en `jobs_payload` pone rojo.
7. **Bundle y demo**: `jobs.json` regenerado (10, con 2 `offered: false`) y comparado contra
   `GET /api/jobs` real (el gate `test_el_fixture_del_front_no_se_queda_viejo_en_silencio` ya
   existe); `demo.test.ts`: lista
   `[F1, F4]`, siembra F1, F3 desconocido cae a F1; `check_frontend_bundle.mjs` exige que el
   bundle construido con `build:demo` **no** contenga el `run_id` ni el `config_hash` de la
   corrida F3 (las ventanas firmadas de sus fixtures salen del manifiesto) y que sí contenga los
   de F1 y F4 (gate local, espejo del de `deploy.yml`, D-JUR-9.8). **CN**: dejar el import de
   `results.json` (F3) en `demo.ts` pone rojo el gate local antes de llegar al deploy; dejar F3 en
   `PRESET_ORDER` pone rojo `demo.test.ts`.
8. **La partición del front sigue probada** sobre los ofrecidos, con el `jobs.json` empaquetado
   (los dos de referencia con `offered: false` no entran a ningún bloque de la landing) y con un
   fixture propio con el opt-in (entran al bloque de referencia). **CN**: partir sobre `jobs`
   en vez de `jobs.filter(offered)` → la landing pinta el bloque con el fixture empaquetado →
   rojo.
12. **El YAML propio de referencia sigue corriendo sin opt-in** (§0): cargar por «Cargar un YAML
    existente» un config de comparación (`provisioning_cmf` + `provisioning_internal` con
    `pd_source="calibration"` + `provisioning`) sobre `provisiones_consumo` resuelve
    `comparar_provisiones` (no ofrecido), la pestaña Datos pide «La PD calibrada de tu modelo, por
    operación», y con la tabla adjunta la corrida llega a `done` por `/api/run` con el capítulo de
    provisiones en el informe (el arnés de `test_ui_puerta_artefactos.py` ya tiene la PD de
    ejemplo). **CN**: resolver `jobForConfig` sólo sobre los ofrecidos → la tarjeta de insumo no
    aparece y el gate de vitest sobre `requiredExternalArtifacts` con ese YAML devuelve `[]` →
    rojo; en Python, `check_pipeline` sin el artefacto → inejecutable → rojo.
9. **Docs**: `test_docs_gobernanza` (catálogo de «Empezar» == 8 filas), nota `[ui]` sin «cuatro
   presets», `norma-local.md` con la sección «Cómo verlo» que cita el comando literal
   `nikodym-ui --casos-de-referencia` y el id del preset; `mkdocs build --strict` solo y después
   los focales de docs (runbook §5). **CN**: dejar una fila CMF en la tabla → rojo.
10. **Recorrido en navegador** (runbook §5, «UI/navegación»): `nikodym-ui` sin opción → landing sin
    el bloque de referencia y selector de ejemplos con tres; con `--casos-de-referencia` → bloque y
    cuatro; cargar un YAML con `provisioning_cmf:` sin opción → formulario completo con la sección.
11. **Verificación en vivo** tras el deploy: `deploy.yml` con las dos negativas nuevas (`run_id` y
    hash de la corrida F3 ausentes del bundle), más `curl` desde la sesión sobre `demo.nikodym.cl`
    y `docs.nikodym.cl/getting-started/`, y el recorrido en navegador sobre la demo publicada:
    selector con dos ejemplos y sin bloque de referencia.

Todo cierre regenera `gen_jobs_fixture` (no `gen_schema_fixture`: el schema no cambia), reconstruye
el bundle y las firmas, y corre los gates de la fila «Catálogo de trabajos/abanico» del runbook §5.

## 7. Lo que esta enmienda NO hace

- **No borra ni degrada CMF**: motor, tests, matrices, manifiesto, cobertura regulatoria, página,
  glosario, dataset y evidencia de la landing quedan como están. D-JUR-5 (validación humana) sigue
  debiéndose con el mismo detonante.
- **No reabre D-JUR-1…8, D-MAX ni D-JOB-8/19.** No abre la regla del máximo a dos internos ni crea
  un trabajo «Comparar IFRS 9 con interno».
- **No recaptura la demo ni captura F5**: lo hace la recaptura única de la release (D-GOB-9), con
  su OK. Hasta entonces la demo es F1/F4.
- **No mueve ningún `config_hash`, ningún fixture golden del motor ni el schema del formulario.**
- **No toca el copy aprobado de D-GOB-13** (que nombra «provisiones CMF» en `governance.motor`: es
  inventario, no oferta) ni el de la ficha en Resultados.
- **No cambia la versión, las notas «Si instalaste desde PyPI» ni publica nada.**

## 8. Lo que Cami decide

1. **¿Se aprueba D-JUR-9 con la opción A** —dos catálogos desde una fuente, opt-in
   `nikodym-ui --casos-de-referencia`, secciones de referencia dentro del formulario— **o se
   prefiere la retirada dura (B)?** Recomendación: **A**. Conserva la visibilidad como evidencia
   que D-JUR-7 pide, no toca el front de la landing, mantiene D-JOB-15/D-EJE-5 exactos y no
   introduce una sección que corre sin pintarse.
2. **¿Los ocho fixtures F3 salen también del árbol** (`web/src/fixtures/demo/preset.json`,
   `results.json`, `toyaml.json`, `report.{html,pdf,docx}`, `report-quarto.zip`; ~1,2 MB), **o se
   conservan sin empaquetar?** Recomendación: **salen del árbol** en la capa de implementación
   —el historial de git los conserva, las firmas se regeneran y un bundle no debe arrastrar una
   corrida que el catálogo no ofrece—. Es una supresión de material versionado, así que exige este
   OK explícito (AGENTS.md: «borrar o reemplazar evidencia material»). El capturador F3 queda como
   capturador de referencia, fuera de la matriz de recaptura.
3. **¿La demo intermedia F1/F4 se publica con el deploy automático de esta capa, o se retiene la
   capa de la demo hasta la recaptura con F5?** Recomendación: **se publica**: desplegar
   artefactos ya versionados no es recaptura (runbook §8), y mantener F3 sembrado en la demo
   pública mientras el catálogo instalable ya no lo ofrece sería la contradicción que `deploy.yml`
   existe para vetar.
4. **Nombre de la opción**: `--casos-de-referencia` (recomendado: es el rótulo del bloque de la
   landing y de la página «Aterrizar una norma local») frente a `--norma-local` o
   `--jurisdiccion`.
