# AGENTS.md — Nikodym RiskLib

> Contexto de trabajo del proyecto (fuente común para Claude Code y Codex). `CLAUDE.md` importa este archivo.
> Detalle completo en [`docs/ESPECIFICACIONES.md`](docs/ESPECIFICACIONES.md), [`docs/ROADMAP.md`](docs/ROADMAP.md) y [`docs/design/00-INDICE.md`](docs/design/00-INDICE.md).

## Qué es
Librería Python **open-source (Apache-2.0)** de riesgo de crédito **integral**: scoring/scorecards, ML, provisiones **CMF (Chile)** e **IFRS 9/ECL**, forward-looking y stress testing. Paquete: `nikodym`. Marca compartida con la **consultora Nikodym** (la librería es su escaparate de reputación → calidad ejemplar es requisito, no extra).

## Idioma
Todo en **español** (docs, comentarios, comunicación). Términos técnicos en su forma original.

## Estado vigente (2026-08-01 tarde, P1 CERRADO)

**`main` = `bc2a914`, con CI 16/16 confirmado por `gh` sobre `4958b9c`** —el commit que trae todo el
código; `bc2a914` es sólo documentación—. **PyPI sigue en `1.10.0` y no hay release autorizado.** Gates: **4713 passed / 6 skipped**, mypy 244, ruff check + format, vitest
**443/443**, bundle reconstruido, fixtures de schema y de trabajos regenerados, mkdocs `--strict`.

🔴 **EL HISTORIAL PÚBLICO SE REESCRIBIÓ** (OK explícito de Cami): se purgaron dos volcados de consola
de Playwright commiteados por error el 2026-07-31, que traían la navegación de quien los generó. **Los
SHA anteriores al 2026-08-01 17:00 que aparezcan en documentos viejos ya no existen** — `2868490` es
hoy `a1d40d6`, `f7d4877` es `4af4ecc`. Ningún tag se movió y PyPI no se tocó. ⚠️ GitHub sigue
sirviendo los blobs por su SHA tras un force push, y hay 1 fork: purga dura es un ticket a Support.

✅ **P1 CERRADO.** El gate de aceptación se verificó de punta a punta **en vivo**: entrar por
«Scorecard de comportamiento (PD)», contestar sus dos decisiones, subir un CSV propio de 6.000 filas
y llegar a «Corrida completada» con su informe en disco. **D-JOB-7 no se empezó**: se cambió por la
enmienda del perfil de columnas, decisión de Cami tras medir lo que el gate destapó.

🔴 **Tres premisas heredadas salieron FALSAS al medirlas, y la primera estaba escrita en `CLAUDE.md`.**
Es la lección transferible: (1) la causa del `bad_rule` inválido **no era la construibilidad** —
`_mapa_de_modelo` decide mirando **sólo la anotación** y nunca consulta `is_required()`; (2) **no era
`data`**: `survival` tiene el defecto idéntico, rompe **cuatro** gestos de estructura y **los diez
trabajos nacían inválidos**; (3) **arreglarlo no deja el config válido, y a propósito** — `bad_rule` y
`partition.strategy` son `DATO-INSTITUCIONAL`, así que el arreglo cambia un valor inventado por un
hueco honesto. De ahí salió la segunda mitad del trabajo.

✅ **Dos enmiendas aprobadas e implementadas.**
[`_ENMIENDA-DECISIONES-OBLIGATORIAS.md`](docs/design/_ENMIENDA-DECISIONES-OBLIGATORIAS.md)
(D-OBL-1…D-OBL-11): el catálogo publica un submodelo obligatorio como **descriptor que conserva sus
hijos**, forma elegida porque **no obliga a tocar `canonicalProjection` ni `isDescriptor`**; y el
trabajo **pregunta en idioma de negocio** lo que sólo el usuario decide —medido, **cuatro**
decisiones en las 14 secciones, con gate bidireccional contra `model_fields`—.
[`_ENMIENDA-PERFIL-DE-COLUMNAS.md`](docs/design/_ENMIENDA-PERFIL-DE-COLUMNAS.md) (D-PERF-1…D-PERF-8):
una columna identificador se avisa **antes** de correr.

🔴 **El gate destapó que NINGÚN trabajo llegaba a `done`**, y la suite no lo veía: el esqueleto
sembraba los ocho capítulos obligatorios del informe —entre ellos `eda`—, que ningún trabajo declara
y el formulario no ofrece. Lo cierra D-OBL-11 recortando a la intersección, que es el criterio de
D-FX-3 aplicado a la siembra.

⚠️ **Un golden estuvo a punto de enterrar 28 campos sin comparar**: el conteo de descriptores bajó a
996 porque el emparejador cortaba al ver un descriptor y dejaba de bajar por sus hijos. Va a **1034**,
con los 10 submodelos obligatorios enumerados uno a uno para que el número no trague un onceavo.

⚠️ **La forma pensada para el aviso del identificador NO era posible**: el preflight no lee los datos
(D-PRE-1) y el parquet no trae `distinct_count` —medido, pandas no lo escribe—. El perfil pasó a ser
**un dato que aporta la ingesta**. Y el criterio no es «cardinalidad alta» sino **texto con casi un
valor por fila**: una numérica continua se discretiza sin problema, y por eso lleva control negativo.

**Siguiente: D-JOB-7, con su terreno ya medido** (no re-medirlo): los dos trabajos bloqueados sólo
necesitan DataFrames planos, el hueco son **4 piezas** y `ui/runs.py` **no participa**. 🔴
`_pipeline_payload` llama `check_pipeline` sin artefactos, y **no hay gate estructural** que obligue a
un endpoint nuevo a entrar en las listas de seguridad. Detalle en [`HANDOFF.md`](HANDOFF.md).

---

## Lo de la sesión anterior (2026-08-01 mañana, `a1d40d6` — era `2868490` antes de la reescritura)

✅ **El SDD de la UI por trabajos quedó APROBADO como contrato** (D-JOB-1…D-JOB-19) y sus dos primeras
decisiones se implementaron y verificaron **en vivo**: la sesión arranca vacía y pidiendo tus datos
(D-JOB-2), y el trabajo elegido decide qué secciones existen (D-JOB-1). El sidebar de «Scorecard»
pinta 9 secciones y ninguna de IFRS 9, survival o CMF.

🔴 **Revisar el SDD antes de programar cambió el trabajo**, y ésa es la lección transferible: el
catálogo de trabajos tiene que vivir en el **backend** porque el preflight que debe consumirlo es
Python; elegir un trabajo siembra **su esqueleto** y no un config vacío; la **demo estática** no puede
arrancar vacía porque no tiene backend ni acepta datos propios; `validation` no podía declararse
porque el formulario no la ofrece; y el caso «un YAML con secciones ajenas» se cierra **seleccionando
el trabajo que le corresponde**, no añadiendo un aviso.

⚠️ **`CONFIG_SECTIONS` no se tocó**: es «qué sabe pintar el formulario», con sus cuatro gates de
paridad intactos, y el catálogo de trabajos es «qué te muestro según a qué viniste».

⚠️ **Dos trampas del árbol.** (a) `test_ui_no_reimplementa_formulas_de_dominio` veta cierto término de
dominio en **todo** el fuente de `nikodym/ui/`, comentarios incluidos: es más amplio que su nombre.
(b) **`HANDOFF.md` de la raíz es un symlink a `privado/HANDOFF.md`** y está gitignored en el público:
escribirlo con una herramienta que reemplaza el archivo rompe el enlace y deja el HANDOFF versionado
sin actualizar, en silencio.

---

## Lo de la sesión anterior (2026-07-31, cierre del paquete D)

**PyPI publica `1.10.0`; no hay release autorizado ni en curso.** Los paquetes B (puerta pública de
artefactos), C (fuga del target en binning + `unique_keys`) y **D (la UI fabrica un config distinto
del que muestra)** están implementados, revisados y cerrados en `main`; C vive en `905b26f`,
`008b217` y `56f53a3`. El plan ejecutable de la próxima oleada vive en
`privado/PLAN-IMPLEMENTACION-2026-07-31.md`; no reabrir sus censos ni los SDD cerrados salvo
evidencia nueva.

🔴 **D cerró con una lección que vale para cualquier catálogo derivado de Pydantic: el valor efectivo
de un campo NO siempre sale de su `FieldInfo`.** `MLConfig.hyperparameters` declara `None` y un
`model_validator(mode="before")` lo rellena con siete hiperparámetros, así que
`FieldInfo.get_default(call_default_factory=True)` —que era la única fuente— publicaba `null` donde
el motor corre con el dict. Ahora, para toda clase construible, la fuente es
`Cls().model_dump(mode="json", by_alias=True)`, que es donde ya corrieron los validadores. Lo
encontró la revisión adversarial, no la suite.

⚠️ **Y el gate que debía cazarlo no podía: las 22 clases raíz de sección NO están en `$defs`** —el
schema compuesto las empotra *inline*—, así que un barrido sobre `$defs` dejaba fuera 224
descriptores, el 32 % del catálogo. Todo gate que recorra el schema compuesto tiene que mirar las
**dos** coordenadas.

⚠️ **Un render recursivo que no propaga su contexto es una clase de defecto, no un olvido.**
`NullableField` llamaba a `FieldRenderer` sin pasarle el catálogo, y los ~60 campos `X | None`
perdían su default: `binning.max_n_bins` pintaba el slider en **2** (su cota inferior) mientras el
motor usaba **8**, con la insignia «Predeterminado» al lado afirmando un valor falso. Es la única
rama del árbol que no pasa por `GroupFieldList`. Lo vigila ahora un guardrail estático sobre el
fuente del componente, porque **vitest corre sin DOM y no puede cazarlo renderizando**.

⚠️ **`git checkout -- <archivo>` restaura desde el ÍNDICE.** Con un cambio ya `git add`-eado, ese
comando descarta en silencio las ediciones posteriores del working tree. Pasó al revertir un control
negativo: se perdió el arreglo del bloqueante y hubo que reaplicarlo.

El benchmark de escala heredado se detuvo porque su `rss_pico_gb` medía sólo antes/después y el
corte de 5 GB no actuaba durante el cálculo. El arnés privado ya supervisa cada escalón en un worker,
muestrea RSS real y termina/limpia al alcanzar el techo. Un smoke de `50.000 x 25` midió 56,78 s,
RSS pico 0,438 GB y `tracemalloc` 0,286 GB. **F0.1 sigue abierto**: la corrida completa debe hacerse
en una tarea standalone y con la máquina descargada.

Los censos del 2026-07-31 dejan cuatro correcciones de premisa: hay 58 candidatos históricos a campo
inerte y sólo 2 confirmados; `Study.results` está vacío y tiene dos consumidores, pero no debe
llenarse como segunda fuente; CMF no puede separarse con un extra vacío; y la moneda es un contrato
transversal de presentación. Orden vigente: evidencia segura → puerta de artefactos → fuga del
target/unique keys → defaults efectivos de UI → defectos runtime → publicación canónica de
resultados → gates débiles → posicionamiento/documentación. Cada cambio contractual nuevo se detiene
en su SDD.

Los gates del cierre D son **4.670 passed / 6 skipped**, mypy 243, ruff check/format, vitest
**408/408**, cobertura regulatoria 682 statements / 166 branches al 100 %, bundle reconstruido dos
veces con hash idéntico, fixture sin drift y supply-chain 29/29. El recorrido real por la interfaz
—preset F1, YAML parcial y el caso causal de `eda`— quedó verificado en vivo. La evidencia completa,
riesgos y siguiente acción se actualizan siempre en `HANDOFF.md`.

---

## Historial reciente (2026-07-30 mediodía, cierre)

**`main` = `423e1a6`, sin un solo cambio de código en la sesión del material de cámara.** No se tocó
`src/`, `web/` ni `pyproject.toml`, así que los gates del repo siguen siendo los del cierre anterior.
**PyPI publica `1.10.0`.**

🔴 **El material del webinar está terminado y verificado ejecutándolo**: dos notebooks, el guion, una
presentación de 12 láminas en HTML y dos YAML de respaldo, en `~/Downloads/webinar-nikodym-hmeq/` y
versionados en `privado/webinar-material/` **con sus generadores** (los `.ipynb` y los YAML se
regeneran, no se editan a mano). Números: `done` en 10–15 s, AUC **0,9175 / 0,8872 / 0,9133**,
PSI ≤ 0,0113, 9 finales con signo correcto, 0 avisos, PDF 310 KB, `config_hash e5868bd6…` ·
`data_hash b6c9f33a…` por los tres caminos.

🔴 **La validación formal de HMEQ cierra en `fail`** (Hosmer-Lemeshow rechaza en dos de tres
particiones) y el informe lo publica en su resumen ejecutivo. No es un defecto: HL castiga el tamaño
de muestra, la calibración en nivel es exacta y la discriminación no está en duda. Es material de
guion, no de código.

🔴 **Defecto real del motor, medido y sin corregir: `feature_columns="*"` no excluye las columnas del
`bad_rule`.** `_structural_columns` (`binning/step.py`) excluye `target_col`, que es la columna
**derivada**, no los insumos de la regla. Con una regla «más de 90 días de mora», la columna de mora
entra como predictor: fuga con AUC inflado. Va por SDD (cambia comportamiento y mueve hashes).

⚠️ **Dos kernels de Jupyter se llaman «nikodym»** y hasta hoy sólo uno declaraba
`DYLD_FALLBACK_LIBRARY_PATH`: con el otro la corrida termina `done` **sin PDF**. Ya corregido en
`.venv/share/jupyter/kernels/python3/kernel.json`; se pierde si se recrea el venv. Y Jupyter vive
fuera de `pyproject.toml` (`uv pip install jupyterlab`), así que **un `uv sync` lo borra**.

⚠️ **La identidad de marca es canónica y vive en `web/src/styles/tokens.css`** (navy `#051528`,
acento `#2e6ff2`, cyan `#4fc3e8`, Avenir Next + Inter). Todo material visual nuevo sale de ahí.

---

### Lo de la sesión anterior (2026-07-30 madrugada, `3f646ae`)

**`main` = `3f646ae`, CI 16/16 confirmado con `gh`, todo pusheado.** **PyPI publica `1.10.0`** (tag
`v1.10.0` sobre `9a85a53`) — ⚠️ **los arreglos del 2026-07-30 no están publicados**; publicar
`1.11.0` es decisión de Cami y exige su OK. Suite **4560 passed / 6 skipped**; vitest **369/369**;
`mypy` 242; `ruff check` **y** `ruff format --check`; fixture del schema regenerado; bundle
reconstruido.

🔴 **El ensayo del webinar está HECHO y la demo se sostiene; lo que queda es el guion y la PPT.**
19 → 0 desajustes sólo por formulario, `done` en 10,5 s por UI y 14,8 s por código, AUC
**0,9175 / 0,8872 / 0,9133**, PSI ≤ 0,0113, 0 avisos, los cuatro formatos. Secuencia de cámara,
comandos y trampas: [`HANDOFF.md`](../HANDOFF.md).

🔴 **La paridad UI ↔ código es EXACTA, y esto corrige lo que decía el D2.** Con el mismo esquema
declarado, los dos caminos dan `config_hash e3d75b27…` y `data_hash b6c9f33a…` **carácter por
carácter**, aunque la UI lea un parquet y el script un CSV. La diferencia que el D2 atribuyó al orden
de `binning.feature_columns` era **esquema mínimo contra esquema completo**: el `data_hash` depende
del esquema, porque declarar un `dtype` coerciona la columna y el hash es del contenido lógico ya
cargado. El script `privado/webinar-hmeq-codigo-minimo.py` es el espejo exacto de la UI y verifica la
paridad él solo.

✅ **Los diez menores del ensayo, resueltos y verificados en la pantalla** (no sólo con tests):
mensajes de validación en español —traducidos por `type` de Pydantic, que es contrato estable—; cero
`id` de DOM duplicados (el switch de un campo opcional usa `<path>__activar` + `data-field-path`);
fuera la jerga «Editor JSON (tipo no mapeado)», «allowlist cerrada», «BinningProcess»; los cinco
botones «Añadir» distinguibles; el selector de Preset marca «con tus cambios» y **pide confirmación
antes de resembrar**; el workdir de la interfaz **se auto-veta escribiendo su propio `.gitignore`**;
y se acabaron los títulos repetidos «Documento / Documento».

⚠️ **El barrido de copy encontró 43 ofensores donde había 4 anotados** (26 descripciones con
`None`/`True`/`False`, 15 en provisiones, 3 títulos con jerga y 9 en inglés). Importa porque
**`fieldPlaceholder` cae en la `description`**: un `None` ahí es el placeholder del input y se lee sin
hover. Lo cierra `tests/unit/test_copy_del_formulario.py`. ⚠️ **Su primera versión daba verde
recorriendo cero campos**, así que ahora exige >300 campos y tres anclas: un gate que no recorre nada
no prueba nada.

⚠️ **Trampa de CI nueva:** el paso «Verify vendored license evidence against PyPI» consulta el índice
por HTTP y puede caerse por red del runner (`SSL: UNEXPECTED_EOF_WHILE_READING`) sin que nada del repo
haya cambiado. `gh run rerun --failed` → 16/16. Antes de diagnosticar, mirar si el rojo es ése.

---

### Lo de la sesión anterior (`9a85a53` + tag `v1.10.0`, 2026-07-29)

**`main` = `9a85a53`, con tag `v1.10.0`, CI 16/16 confirmado con `gh`, todo pusheado.**
**PyPI publica `1.10.0`.** Suite **4550 passed / 6 skipped**; vitest **359/359**; `mypy` 242;
`ruff check` **y** `ruff format --check`; bundle sin drift; fixture del schema regenerado.

🔴 **PRIORIDAD ABSOLUTA: el webinar EN VIVO es MAÑANA POR LA MAÑANA, 2026-07-30 — y lo que queda NO
es programar.** Es sobre regresión logística y scorecard, con **demo real no precargada**, dataset
**HMEQ**, en código **y** en UI, ante audiencia mixta con decisores. Cami lo dijo al cerrar: «parto
una fresca haciendo **una corrida limpia con el dataset**… **no puedo fallar en vivo**». El objetivo
de la próxima sesión es **ensayar la secuencia exacta de la cámara**, con la máquina descargada, y
cronometrarla. Secuencia paso a paso, comandos y trampas: [`HANDOFF.md`](../HANDOFF.md).

✅ **El P0 del D2 está CUMPLIDO: el camino 100 % por UI llega al informe.** 19 desajustes → **0**
corrigiendo sólo desde el formulario, sin cargar ningún YAML; `done` y los cuatro formatos. AUC
**0,9175 / 0,8872 / 0,9133**, PSI ≤ 0,0113, los 9 coeficientes con signo correcto, **0 avisos
declarados**. Lo que el D1 declaró bloqueado quedó verificado de punta a punta, no por tramos. El
recorrido por código está escrito en `privado/webinar-hmeq-codigo.py` (11 pasos, ~15 s).

✅ **`1.10.0` PUBLICADO, y era necesario, no cosmético: la demo era irreproducible con lo publicado.**
`1.9.0` (= `cd75aa9`) es anterior a los seis commits que hacen posible el recorrido por UI, así que
**en PyPI los multiselect de binning seguían pintando «Sin opciones.»**. Verificado desde PyPI en venv
limpio con `--no-cache-dir`, con `[ui]` y con `[ui,pdf]`. ⚠️ **`[ui]` a secas no produce PDF y es
diseño** (`[pdf]` nunca entra, por la transitiva copyleft): a un tercero se le dice
**`pip install "nikodym[ui,pdf]"`**.

✅ **El formulario ofrece 14 secciones: entra «Informe», con la portada del entregable** (modelo,
entidad, cartera, responsable, versión). Antes esos cinco campos sólo se escribían por YAML o por
código, así que el informe del camino UI salía con la primera página en blanco. ⚠️ **Llenar la portada
NO mueve el `config_hash`**: `report` está en `INFRA_SECTIONS` a propósito — el informe es
presentación, no cálculo.

🔴 **La auditoría adversarial FRENÓ el release: dos de tres revisores dijeron parar, y tenían razón.
Tercer release consecutivo en que ocurre**, y esta vez lo que encontró estaba **en la pantalla de la
demo**: cinco etiquetas en inglés o calcadas visibles sin hover («Embeder assets», «Timeout IA»,
«Máximo tokens entrada», «Variable de API key», «payload» en un placeholder); ocho descripciones que
empezaban por «True …» sobre interruptores que dicen Activado/Desactivado; **la reincidencia exacta**
del defecto corregido horas antes (un tooltip mandando a elegir «warning» cuando el selector muestra
`error`/`warn`/`skip`); y el botón «Word (.docx)» diciendo «Esta corrida no generó un PDF».

- ⚠️ **Una `description` de Pydantic puede leerse SIN hover**: `fieldPlaceholder` cae en ella, así que
  también es el `placeholder` del input. No es sólo el tooltip.
- ⚠️ **Las opciones de un selector se pintan crudas** (`String(option)`): todo copy que nombre una
  opción tiene que usar su literal exacto.
- ⚠️ **`pd.Timestamp("")` y `pd.Timestamp("nan")` devuelven `NaT` SIN levantar**: atrapar `ValueError`
  no basta. Un `oot_from` en blanco se iba en silencio y la corrida muere en `data`.
- ⚠️ **`[ui]` no declaraba matplotlib** aunque su formulario ofrece `render_charts` en `True`:
  funcionaba sólo porque `optbinning` y `lifelines` lo arrastran — verde por accidente.
- ⚠️ **Lo que la auditoría REFUTÓ vale igual:** `config_hash` idéntico byte a byte en los tres presets
  y en el YAML del webinar, medido **en caliente y en frío** contra un `git archive v1.9.0`; ningún
  config de fábrica gana avisos; ninguna firma pública cambió; `manifest.path` no se movió.

🔴 **Y el recorrido por código destapó un defecto real del núcleo:** `ReportResult.html_path` devolvía
`reports/reports/scorecard_report.html` —inexistente— cuando `report.output_dir` es **relativo**, o sea
el default del preset F1 y el caso de cualquiera que use la librería por código. La interfaz pasa ruta
absoluta, así que por ahí no se veía, y **ningún test cubría el caso relativo**.

**Cuatro trampas operativas nuevas:**

1. **🔴 La máquina cargada multiplica la corrida por 10**: 14,9 s libre vs **157,5 s con load average
   20** (por UI, 20 s → 206 s). No es regresión — el camino por código, que no cambió, se degrada
   igual. Antes de una demo en vivo, cerrar Chrome y las otras sesiones.
2. **🔴 `nohup` también se come el `DYLD`** (SIP), igual que el `/bin/sh` del shebang. La regla buena:
   **el primer proceso exec-utado tiene que ser el intérprete**, sin `sh` ni `nohup` en medio. Sin la
   variable no hay PDF y la corrida termina `done` igual: el fallo es silencioso.
3. **🔴 Tocar `pyproject.toml` sin correr `uv lock` pone 15 de 16 jobs en rojo** (`uv sync --locked`).
   Ningún job llega a correr un test.
4. **⚠️ El minificador emite template literals**: `grep 'key:"report"'` da cero hits sobre un bundle
   correcto. Grepear con backticks.

**Congelados hasta después del webinar**: B2.4, la recaptura de la demo, vitest→jsdom, la pata de
release de B2.5 y las 6 invariantes del censo que no entraron.

---

### Lo de la sesión del 2026-07-29 (mañana/tarde): las invariantes previas

**`main` = `0ea4cba`, CI 16/16 confirmado con `gh`, todo pusheado.** PyPI sigue en `1.9.0` (tag
`v1.9.0` sobre `cd75aa9`). Suite **4545 passed / 6 skipped**; vitest **357/357**; `mypy` 242;
`ruff check` **y** `ruff format --check`; bundle sin drift.

🔴 **PRIORIDAD ABSOLUTA: el webinar EN VIVO de Cami es MAÑANA, el 2026-07-30.** La fecha estaba mal
en toda la documentación anterior (decía 2026-08-02) y Cami la corrigió el 2026-07-29: queda lo que
reste de ese día y **la mañana del 2026-07-30**. Es sobre regresión logística y scorecard, con **demo
real no precargada**, dataset **HMEQ**, en código **y** en UI, ante audiencia mixta con decisores.
**Congelados hasta después del webinar**: B2.4, la recaptura de la demo, vitest→jsdom, la pata de
release de B2.5, el menor 8 del D1 y las 6 invariantes del censo que no entraron.

🔴 **Y lo que falta NO es código: es el ensayo de punta a punta.** Cami lo pidió así —«sacar una
scorecard del dataset y mostrar todos los pasos tanto como en código como en UI», «no nos apuremos,
hagamos las cosas bien», y el guion/PPT **al final**—. **Nadie ha llevado el preset F1 hasta HMEQ
corriendo entero por el formulario hasta el informe**: el D1 declaró ese camino bloqueado (N2), la
sesión siguiente arregló la causa pero midió sólo un tramo («18 → 11 desajustes», una corrida `done`
tras corregir **una** columna), y encima hay dos commits nuevos, uno de los cuales añade un aviso en
esa misma pantalla. Primer paso concreto: `HANDOFF.md`.

**El P1 quedó cerrado, y no era una invariante sino siete.** `check_dataset` **y** `check_pipeline`
declaraban verde un config que muere en el paso 8 de 10 (`stability.temporal_axis` en su default
`"period"` sobre un dataset sin columna de período). El censo halló **13 candidatas** de la misma
clase y **7 se confirmaron en vivo**, todas con las dos superficies en verde. Entran cinco.
[`_ENMIENDA-INVARIANTES-PREVIAS.md`](design/_ENMIENDA-INVARIANTES-PREVIAS.md), D-INV-1…D-INV-9.

- **La invariante la declara el dominio que la impone** (`requisitos_incumplidos(columnas)`), no un
  registro central: mismo criterio que `column_role`.
- **Se consume por `check_dataset`; `check_pipeline` NO se tocó** y sigue siendo lo único que gobierna
  el botón Ejecutar. «`check_pipeline` es el sitio natural» describe el sitio correcto para **otra**
  pregunta: esa función resuelve el DAG de pasos, y ninguna de las siete tiene que ver con eso.
- ⚠️ **A3 y C2 quedaron fuera con su razón MEDIDA** (D-INV-8): comprobar `stratify_by` daría **falsos
  positivos** —`Partitioner.suggest` la apunta a `target_col`, columna derivada que por definición no
  está en el CSV—, y `required_sections` es una invariante **entre** secciones, que un protocolo por
  sección no expresa sin el acoplamiento que D-INV-1 evita.

🔴 **`study.results` es un canal muerto CON consumidores.** `ModelCardBuilder` y `TrackingSink` leen
de él y siempre está vacío, así que un model card publicado sale sin métricas y MLflow recibe vacío;
no se ve en la demo porque los tres presets traen `governance: null` y `tracking: null` (medido). Se
corrigió el docstring de `nikodym.run`, que mandaba usarlo —ahora apunta a
`study.artifacts.get(dominio, clave)`—. Llenarlo es contrato, o sea SDD.

✅ **Playwright de verdad SÍ funciona sobre esta UI** (MCP `mcp__playwright__*`): maneja los `Select`
de Base UI sin problema. La nota anterior sigue valiendo —`dispatchEvent` sintético no sirve— pero ya
no hay que esperar a B2.4 para verificar un recorrido en vivo.

⚠️ **Y mirar la pantalla destapó dos defectos de copy que ningún test habría visto**, ambos escritos
en esa misma sesión: el aviso por sección decía «nombra una columna que el dataset no tiene» —falso
para dos de los cuatro tipos— y un mensaje nuevo mandaba a elegir un «ninguno» que en el selector se
llama `none`. El error de esquema, además, era un volcado de `pandera` en copy público; **doce tests
aseveraban justo esa jerga**, o sea que la defendían.

---

### Lo de la sesión anterior (`987f678`, 2026-07-29)

**El ensayo D1 se corrió entero y la demo se sostiene:** HMEQ da **AUC 0,918 dev /
0,887 HO / 0,913 OOT**, PSI ≤ 0,011, los 9 coeficientes con signo correcto y el informe **sin un solo
aviso declarado**. Los 9 hallazgos con su `archivo:línea` y los tiempos cronometrados están en
`privado/WEBINAR-D1-ENSAYO-2026-07-28.md`.

🔴 **El PDF de la UI no dependía del `DYLD` sino del entrypoint.** `nikodym-ui` tiene shebang
`#!/bin/sh` y **macOS (SIP) borra `DYLD_*` al pasar por `/bin/sh`**: exportar la variable no sirve
por esa vía. **El comando bueno es `python -m nikodym.ui`** (`pyproject.toml:68` declara los dos),
y con él salen los cuatro formatos y cero warnings.

**Y el formulario quedó arreglado DE RAÍZ** —decisión explícita de Cami, «hay que dejar todo bien,
no parches», que descartó el plan B de cargar un YAML—. Tres commits cierran una clase entera:
**ninguna lista del config queda sin control**.

- `5969dc0` — **el multiselect toma sus opciones del dataset**, vía `column_role`. Una lista de
  nombres de columna no puede traer `enum` (dependen del archivo del usuario), y era lo único que
  `multiselectOptions` miraba. ⚠️ `toggleMultiselect` además **descartaba** los valores fuera de las
  opciones: inofensivo con opciones del schema, destructivo con opciones del dataset.
- `dd8161f` — **las 11 listas de objetos se editan fila a fila**. `data.schema.columns` eran 1.552
  caracteres de JSON en un `<textarea rows=5>`. El salto del preflight se arregló **solo**: los
  avisos que enfocan el campo exacto pasan de **0 a 18/18**.
- `e688280` — **el gate de `column_role` mide el footprint real**, no una tupla escrita al lado.
  ⚠️ Matiz útil: `dataset_check.py` hace `continue` sobre `derived`/`not_a_column`, así que
  clasificar con esos roles **no amplía el preflight**; declarar `input` en `survival`/
  `provisioning_ifrs9` **sí** lo haría, y por eso quedan exentos con su razón escrita.

**La auditoría adversarial previa al release de `1.9.0` lo FRENÓ y encontró dos defectos que 4.522
tests y CI 16/16 no veían** — segundo release consecutivo en que ocurre. Ambos corregidos antes de
publicar:

- **El preflight declaraba compatible un `data.schema.index_col` inexistente.** `index_col` tenía
  **tres** estados y sólo dos ramas; el tercero se iba en silencio con `compatible=True` y
  `mismatches`/`uninspected` **vacíos**, sobre un config que la corrida rechaza en su primer paso.
  La causa era **de firma**: `check_dataset` recibía sólo las columnas, y el índice por definición no
  está entre ellas, así que un `index_col` correcto era indistinguible de uno inexistente. De ahí
  `index_columns=`; ⚠️ **`None` significa «no se sabe», no «no hay»**, y omitirlo conserva el
  comportamiento anterior a propósito —afirmar sin ese dato reintroduce el falso positivo más caro—.
- **`POST /api/preflight` no exigía token**: 200 y materializaba el parquet a cualquier proceso
  local, con `/api/run` dando 403 en las mismas condiciones. Va en `CREDENTIALED_PATHS`, **no** en
  `MUTATING_PATHS`: exige las mismas credenciales pero **sigue vivo con
  `allow_live_execution=false`**, porque comprobar no es correr.

⚠️ **`[ui]` ya no es «el servidor»** (decisión de Cami, «no quiero promesas falsas»): compone
`scoring`, `survival`, `excel` y `docx`. 310 → **703 MB**, 0 → **3 presets ejecutables**. Hereda con
ello el techo **`scikit-learn<1.8`** que `scoring` ya imponía. `ml`/`tuning`/`explain`/`markov`/
`forward` **no** entran porque el formulario no los ofrece; **`[pdf]` nunca**, por copyleft; y
**`polars` tampoco** —es alcanzable desde el formulario (`data.backend`) pero degrada con el comando
exacto y no cambia el resultado, así que se corrigió la frase del README en vez de sumar el extra—.

⚠️ **`ConfigError` no hereda de `ValueError`.** Pydantic no lo envuelve, así que escapaba entero y
`/api/validate` —contrato «siempre 200»— devolvía **500**, que el front mostraba como «Backend no
disponible». Seis `config.py` lo levantan al validar: se traduce en el endpoint, no por sección.

**Estado de B2:** cerrados B2.0–B2.3 y la documentación de B2.5; abiertos **B2.4** (no hay clean-room
automatizado ni Playwright), la **pata de release de B2.5** (el job publica con rebuild, sin pasar
por ningún gate) y el **tercero sin checkout**, que no lo sustituye ningún agente: el recorrido
automatizable elimina la dependencia del árbol, **no** el sesgo de conocimiento interno.
**Todo ello congelado hasta después del webinar (2026-07-30) por el webinar.**

⚠️ **De los tres gates más débiles que su nombre (auditoría del 2026-07-28), `test_column_roles.py`
quedó ARREGLADO el 2026-07-29** (`e688280`, verificado inyectando otra vez el rol en `markov`).
**Siguen abiertos los otros dos**: el gate del extra `[ui]` sólo itera 5 de 12 extras; y
`schema.test.ts` deriva sus casos de lo que vigila, así que **`model` se puede borrar del formulario
con todo el CI verde**. Detalle en `HANDOFF.md`.

---

### Lo de la sesión del 2026-07-28 (mañana)

**El config y el dataset se comparan ANTES de correr.** `nikodym.check_dataset(config, columnas)` y
`POST /api/preflight` devuelven **todos** los desajustes de una vez, sin ejecutar nada. Medido desde
PyPI en venv limpio: un CSV con nombres de columna propios exigía **seis ediciones del preset F1 en
seis lugares distintos**, reveladas **de a una** —cada corrida fallida destapaba la siguiente—.
[`_ENMIENDA-PREFLIGHT-DATASET.md`](design/_ENMIENDA-PREFLIGHT-DATASET.md), D-PRE-1…D-PRE-9.

**Y lo que más vale de esa sesión no es la feature: es haber atacado una CLASE de defecto.** Los tres
defectos serios de los últimos tres releases —el `save`→`load` que se rechazaba a sí mismo (`1.7.0`),
los dos `config_hash` según los imports (`1.8.0`) y el preflight que decía `compatible=True` sobre un
config con 17 desajustes— **son el mismo defecto con tres disfraces**: una sección de config existe
en **dos estados**, tipada u opaca, y casi ningún consumidor lo contempla. Los tres se habían
parcheado donde dolía. `tests/unit/test_seccion_opaca_invariante.py` exige ahora que cada superficie
pública responda **lo mismo** en los dos estados, y que todo consumidor nuevo de `NikodymConfig`
declare su política (`comprobado` con test, o `exento: <razón>`).

⚠️ **El estado opaco es el DEFAULT, no un caso raro:** `model_validate` no coacciona salvo que
alguien haya llamado `cargar_configs_de_dominio()`, y tener la capa importada **no basta**. Ésa es la
razón de que la familia reapareciera tres veces conviviendo con 4.500 tests verdes.

Ese recorrido midió además que el extra `[ui]`, `/api/upload` y los tres presets **funcionan desde
PyPI** (F1/F3/F4 hasta `done` + informe, con los negativos de seguridad verdes), lo que destapó que
`docs/ROADMAP.md` declaraba B2.3 abierto contra lo que decía el código. Ya está corregido.

---

### Lo de la sesión anterior (2026-07-27)

**`1.8.0` PUBLICADO en PyPI** (tag `v1.8.0` sobre `2c9ed79`, con OK explícito de Cami).

**`1.8.0` corrige que la identidad criptográfica del config dependía del orden de los `import`.** El
mismo config producía dos `config_hash` distintos según si la capa de dominio estaba importada:
sin ella la sección viaja como blob opaco y se canonicaliza **sin normalizar**. De ese digest cuelgan
el lineage, el model card, el informe y el ancla de idempotencia de MLflow. `config_hash` coacciona
ahora antes de canonicalizar —la identidad es la del config **que se ejecutaría**—, sin tocar el blob
opaco del núcleo liviano.
[`_ENMIENDA-CONFIG-HASH-IMPORTS.md`](design/_ENMIENDA-CONFIG-HASH-IMPORTS.md), D-HASH-1…D-HASH-8.

⚠️ **Sale como minor a propósito: recalcula identidad.** Un config con secciones opacas y campos
omitidos cambia de `config_hash`, y con él la clave de idempotencia de su inventario MLflow. Los
`Study` guardados con `save()` **no** se mueven (escriben el config ya coaccionado y completo,
verificado con un round-trip entre procesos). Precedente idéntico: `1.4.0`.

**Y la premisa con que se había priorizado ese trabajo era falsa.** El pendiente decía que el defecto
afectaba «al usuario mientras trabaja» en la UI; medido, por la interfaz **no se alcanza** —el
formulario no valida hasta recibir el schema, y `/api/schema` importa los dominios—. Afecta al cliente
HTTP directo y al uso por código con `dict`, y el defecto grave no era el que daba título al ítem.
Van nueve veces que el plan escrito no sobrevive a la primera medición contra el código.

La sesión previa del 2026-07-27 había entregado el **núcleo técnico de la paridad UI↔código en
provisiones** —el formulario del UI instalable pasó de 7 secciones a **12**, entran `survival` y las
cuatro de `provisioning*`— más el aviso en vivo de config inejecutable y `nikodym.check_pipeline`.

⚠️ **La auditoría previa a publicar encontró un P0 que 4.476 tests y CI 16/16 no veían, y frenó el
release.** Vale más que la feature: `Study.save()` guardaba una corrida exitosa que `Study.load()`
después rechazaba con `ReproducibilityError`. Era regresión de `cf217a2`: mover el `run_id` antes de
resolver el pipeline (D-ERR-9) se llevó consigo el `_build_lineage()`, y **resolver COACCIONA el
config** (`_coerce_domain_config` materializa los defaults que el YAML no traía), así que el lineage
congelaba un `config_hash` que el propio `config.yaml` contradecía. Alcance real más allá del
round-trip: el hash publicado en el model card, el informe y el ancla de MLflow era el del config
*como se escribió*, no el que *se ejecutó*.

**Por qué ningún test lo cazaba, y es la lección transferible:** los round-trips construyen el config
en Python **ya tipado** y los presets escriben **todos** los campos explícitos — dos formas de no
tener nunca una sección opaca. El defecto exige sección opaca (YAML + capa no importada) **y** un
campo con default omitido. Un test que no pueda producir el estado no puede cazar su defecto.

Probar el formulario ya había destapado antes otro defecto del núcleo (config inejecutable sin
rastro → HTTP 500), cerrado con
[`_ENMIENDA-RUN-ERROR-RESOLUCION.md`](design/_ENMIENDA-RUN-ERROR-RESOLUCION.md) (D-ERR-8…D-ERR-11).
Detalle operativo y las cuatro reglas para tocar el formulario: `CLAUDE.md` §«Lo último».

## Estado publicado (2026-07-29)
PyPI publica **`1.10.0`** (tag `v1.10.0` sobre `9a85a53`, 2026-07-29, con OK explícito de Cami); el
tag `v1.5.0` apunta al cierre del bloque B1 (el SHA vigente de `main` queda en `HANDOFF.md`). El
paquete se anuncia como **`Development Status :: 4 - Beta`**: el pipeline F1 es estable bajo SemVer
1.x, pero las provisiones siguen experimentales, así que «Production/Stable» sería sobrepromesa.

⚠️ **Al verificar un release recién subido, `pip install` SIN `--no-cache-dir` puede traerte el
release ANTERIOR** con el nuevo ya en el índice, y parecer verde. Pasó con `1.9.0`: la primera
instalación limpia trajo `1.8.0` mientras `pip index versions` decía `LATEST: 1.9.0`.

**Regla de release que `1.10.0` dejó explícita: el tag va sobre un commit con CI VERDE, nunca sobre
el commit del bump recién pusheado.** `release.yml` **no corre ningún gate** —sólo verifica que el tag
coincida con `__version__`, hace `uv build` y publica—, así que tagear a ciegas publica sin red. La
secuencia buena es: commit del bump → push → esperar el conteo `gh` de los 16 jobs → tag. Y ojo con la
trampa que costó 15 jobs rojos en este mismo release: **tocar `pyproject.toml` obliga a `uv lock`**,
porque casi todos los jobs hacen `uv sync --locked`.

**Regla de release que `1.8.0` dejó explícita: un cambio de `config_hash` va en MINOR, nunca en
patch.** Se propuso publicarlo como `1.7.1` y estaba mal fundamentado: el precedente del repo es
`1.4.0` —recalculó identidad al excluir `data.load.source` y salió como minor con nota de contrato
SemVer—, mientras que `1.4.1` fue documentación y defectos de presentación. Un patch se lo lleva
quien tenga pin `~=1.7.0` sin haberlo decidido.

**`1.7.0` abre la interfaz a provisiones y survival** —el formulario pasa de 7 a 12 secciones— y
suma el aviso en vivo de config inejecutable más `nikodym.check_pipeline`. **No rompe a nadie**: los
tres cambios de contrato son aditivos. **Survival dejó de ser un dominio «sólo Python»** y eso ya
está corregido en la landing, el README y `docs_site`; ojo con la cifra de tests de los dominios sin
interfaz, que bajó a «más de 500» porque los 89 de survival se fueron con él. Verificado instalando
**desde PyPI**, no desde el árbol: el round-trip `save`→`load` que el P0 rompía funciona, y la SPA
del paquete sirve el aviso nuevo.

**`1.6.0` corrigió una cifra y rompió dos configuraciones de fábrica**, y eso hay que tenerlo presente
al hablar con cualquiera que venga de `1.5.0`: el descuento de la ECL asumía que `time_value` estaba
en años sin verificarlo (−40 a −50 % de provisión con una curva en meses), y ahora la
term-structure transporta su unidad. Como contrapartida, una curva sin unidad declarada o un
`horizon_12m_periods` que no dure un año **detienen la corrida** con el default. Cada release sigue
exigiendo **OK específico de Cami**. La librería ya **no** está en fase de construcción por capas
— está publicada y en mejora continua:
- **Pipeline scorecard F1 (comportamiento)**: API **estable** bajo garantía **SemVer 1.x** (binning WoE
  monotónico, selección IV/VIF, logística sobre WoE, calibración, informe HTML/PDF/Word).
- **Provisiones CMF (Chile, B-1) e IFRS 9/ECL**: implementadas, testeadas y con preset/UI/informe, pero
  marcadas **experimentales** (madurez, no certificación).
- **Stress, markov y forward**: implementados y cubiertos por tests, pero hoy se usan escribiendo el
  config en Python (sin preset/UI propios) → **experimentales**. Survival ya tiene UI, preset e
  informe y sigue experimental.
- **UI React** en `web/` + **demo multi-dominio** (F1 scorecard · F3 CMF · F4 IFRS 9) deployada en
  **demo.nikodym.cl** (fixtures de corridas reales, sin cálculo en el navegador).
- **Informe** HTML/PDF/Word con estilo editorial, contexto poblacional, validación formal y config
  efectiva por dominio; F3 fue recapturado desde una corrida real durante esta consolidación.
- Suite: **>4.500 tests** (4.515 al 2026-07-28), `mypy --strict` y un gate al 100 % sobre las 11 rutas
  explícitas de `REGULATORY_COVERAGE_PATHS`; ese gate no cubre todo el código regulatorio ni los
  engines CMF/IFRS 9 completos. CI matriz verde (macOS/Windows/Linux × Python 3.11–3.13).

**Track pre-Interbank COMPLETO:** la cola [`privado/COLA-CODEX-INTERBANK.md`](privado/COLA-CODEX-INTERBANK.md)
(IBK-01…IBK-05) está **toda cerrada** al 2026-07-17. **No hay bloque IBK siguiente.** El release
**1.5.0** (2026-07-22) cerró el bloque **B1** y dejó la demo y PyPI con lineage 1.5.0. La reunión
con **Interbank** (2026-07-22) salió bien: van a revisar la librería y luego agendar una segunda
sesión, así que el freeze de artefactos previo a esa reunión ya no aplica. El
**tag `vX.Y.Z` y PyPI exigen OK específico de Cami por release** (el OK permanente cubre push/deploy,
no tag/PyPI). **Arrancar toda sesión leyendo [`HANDOFF.md`](HANDOFF.md).**

**Plan vigente desde 2026-07-21:** el track pre-reunión se reemplazó por los bloques **B1…B8** de
[`docs/ROADMAP.md`](docs/ROADMAP.md) §«Plan operativo vigente». Orden: B1 higiene → B2 UI instalable →
B3.a abstracción de jurisdicción → B4 rutas de uso F5/F6; B3.b (motor de una jurisdicción nueva) exige
compromiso comercial firmado. El track comercial (precios, cláusulas, accesos) vive en
`privado/PLAN-TRABAJO-2026-07-21.md` y **no se publica**.

## Visión de producto — qué significa «lista» (fijada por Cami el 2026-07-25)

El criterio de éxito no es una lista de features cerradas: es que **cualquier equipo de riesgo de
LATAM diga «no puedo vivir sin esta librería»**. De ahí bajan cuatro requisitos, y ninguno es
opcional:

1. **Paridad UI ↔ código.** Se instala y se trabaja 100 % por código o 100 % por interfaz gráfica,
   sin perder ni ganar nada en ninguno de los dos caminos. Es la lectura fuerte de «instalable y
   usable»: no basta con que la UI exista, tiene que *alcanzar todo*.
2. **Validación contra datos reales y sucios.** Hasta el 2026-07-25 **todo el catálogo era sintético
   determinista** (`src/nikodym/ui/datasets.py:1`). Una librería de riesgo validada sólo contra datos
   que ella misma genera no está validada. Se prueba con datasets externos de varias plataformas
   —uno solo no demuestra generalidad— y Cami autorizó registrarse o pagar por ellos si hace falta.
3. **Flexibilidad total de inputs: se provee, se modela, o sale del histórico.** Para PD, LGD, EAD,
   PIT/TTC, calibración y escenarios macro, y en los tres motores (IFRS 9, stress, forward). Si el
   dato viene en el dataset se usa; si no viene, se modela; si hay historia, se puede estimar de
   ella. **Todas las alternativas, no una.** ⚠️ Esto es un problema de *arquitectura*, no una suma de
   features: exige un contrato transversal de resolución de parámetros **diseñado por SDD antes de
   programar nada**. Atacarlo motor por motor produce N implementaciones ad-hoc intestables.
4. **Multi-jurisdicción al final, por prioridad y por tamaño de banca: Chile → Perú (SBS) →
   Colombia.** **Brasil queda fuera** por ahora (mundo aparte). Ojo con el orden: implementar una
   jurisdicción nueva va al final, pero *dejar de asumir Chile* (B3.a) va antes de construir la
   matriz de flexibilidad encima de una taxonomía chilena hardcodeada.

**Criterio de método, dicho por Cami:** camino largo pero seguro, no «puras zancadillas». Un arreglo
puntual que no acerca a estos cuatro puntos compite contra ellos por el tiempo, y hay que decirlo
cuando ocurra.

**Estado del camino largo (2026-07-26).** El requisito 3 tiene contrato aprobado
—[`docs/design/_CONTRATO-RESOLUCION-PARAMETROS.md`](design/_CONTRATO-RESOLUCION-PARAMETROS.md),
CRP-1…CRP-7—, **B3.a-1 está cerrado** y el contrato **está en ejecución**: CRP-5 implementado
(`afa3403`) y **CRP-6 cumplido en las siete capas** (bloque A en `368bcf5`, bloque B a
continuación) — ver `CLAUDE.md` y `ROADMAP.md` §B3. Queda fuera el P2 (`pit_mode` del preset F4),
que **no es orden de trabajo sino imposibilidad medida**: sus dos salidas exigen encadenar `forward`
o ampliar el dataset sintético.

Los dos pasos ejecutados dejaron la misma lección, ya cuatro veces pagada en este repo: **el plan
escrito no sobrevive a la primera medición contra el código.** CRP-6 no era implementable como
estaba redactado —el flag de `ifrs9` no gobernaba ninguna marca, y `FALTA-DATO-IFRS-4` se emite en
toda corrida, de modo que conectarlo tal cual habría abortado el motor entero con su default—. Y hay
un matiz nuevo que conviene tener presente al leer cualquier censo heredado: **un censo clasifica por
el mecanismo que eligió, no por la pregunta que decide el trabajo.** El de CRP-6 contaba cinco
semánticas; contra la pregunta real, cinco de las siete capas ya cumplían.

B3.a-1 no se ejecutó como estaba escrito: **su premisa era falsa y el censo lo demostró.** El enum
chileno de `governance` no era la llave de segmentación de ningún cálculo y la llave real ya era
neutra; lo que faltaba era que **alguien declarara el dominio de valores del segmento**, sin el cual
CRP-1 y CRP-3 no se pueden montar. Se reformuló y se implementó en
[`docs/design/_ENMIENDA-SEGMENTACION.md`](design/_ENMIENDA-SEGMENTACION.md). Tres de sus decisiones
**cambiaron al programarlas** y quedaron escritas con su razón en el propio SDD, que es la conducta
esperada: reabrir un diseño por feedback del código es barato, dejar que documento y código se
separen en silencio no. El requisito 2 dejó de ser teoría: el pipeline F1 corre sobre **Lending Club, 1.348.099
préstamos reales**, y esa primera tarde de datos sucios destapó dos defectos que 4.300 tests verdes no
veían —la deriva de tasa base entre particiones no tiene guarda, y el gate de bin puro ignora un WoE
que el usuario declaró—. Un dataset sintético determinista no puede encontrarlos: produce tasa base
estable y nulos limpios por construcción.

**El catálogo de datos externos (2026-07-25, noche).** Ya no es un dataset suelto: hay un catálogo
curado de 42 datasets públicos documentado en [`docs/datasets/`](datasets/) —README, `catalogo.csv`
y el gestor `descargar.sh`—, con los datos en `data/externos/raw/` (vetado por `.gitignore`,
**nunca** se commitea). Son **efímeros**: el ciclo es `get` → probar → `rm`, y lo permanente es la
documentación. El gestor se ejecuta desde `data/externos/`, donde los cuatro documentos son
symlinks a su copia versionada.

⚠️ **Leer el §0-bis del README antes de planificar sobre una fila del catálogo.** El catálogo se
escribió mirando los datasets, no el código, y **once de sus justificaciones describen casos de
prueba que ningún motor puede correr hoy** —`stress` no lee archivos y además rechaza
`source="official"`; no hay riesgo competitivo, ni fairness, ni RWA, ni reject inference (excluido
por diseño en ESPECIFICACIONES §5.2, y sin embargo es la entrada de *prioridad 1* del catálogo)—.
Cada discrepancia está con `archivo:línea`. Es el mismo error de método que ya se pagó en B3.a-1:
**un relevamiento externo es hipótesis de alcance hasta que se mide contra el código.**

## Auto-desarrollo (motor de trabajo)
**Regla fijada por Cami el 2026-07-24: el auto-desarrollo se invoca SOLO cuando él lo pide de forma
explícita.** Nunca se entra en modo autónomo por iniciativa propia ni porque la tarea parezca de
campaña. En el **trabajo normal**, en cambio, se usa todo el potencial disponible —workflows,
subagentes en paralelo, fan-out de búsqueda, revisores adversariales frescos— **sin pedir permiso
cada vez**: basta con decir qué se lanzó y por qué. Son dos cosas distintas: el auto-desarrollo es un
*modo de operación* (corridas largas sin nadie delante) y esa decisión es suya; los subagentes son
*una herramienta más* dentro de una sesión normal. La pregunta explícita se reserva para montar un
equipo persistente sobre el mismo árbol.

Para una ejecución autónoma usar la skill explícitamente pedida por Cami y una tarea standalone o
efímera: coordinador, un único writer, gates, revisor adversarial fresco e integración final. No usar
un heartbeat que acumule contexto. La **maquinaria tmux multi-motor está FROZEN** (histórica):
`autodev-cron`, watchdog, maestro headless y los perfiles por motor ya no corren. La construcción por
Tandas/SDD y el Hito 0 de contratos transversales (CT-1…CT-4)
ya se completaron; sus decisiones siguen vigentes en `docs/design/`.

## Reglas de trabajo durables
- **Memoria histórica `Ideas Nikodym` (privada, disponible sólo en el workspace interno):** antes de
  planificar o implementar mejoras de forward-looking, stress, validación, PDI, forecast de cartera,
  conectores o Risk Leap, leer
  `privado/REVISION-HISTORICA-IDEAS-NIKODYM-2026-07-18.md` cuando esa ruta esté disponible.
  El corpus histórico es inspiración y fuente de tests adversariales, **no** metodología aprobada ni
  fuente normativa. Toda propuesta debe respetar sus decisiones `IHN-001…IHN-011`, evitar duplicar
  capacidades actuales y mantener detalles institucionales en `privado/`.
- **Incremental por capa (NUEVO, reemplaza "cero código ahora")**: cada capa se **diseña (SDD) → programa → valida con código y tests → ajusta → sigue**. Nunca se programa sin el SDD aprobado de esa capa, pero ya no se difiere todo el código hasta el final. El código de una capa es la prueba de fuego de su diseño; reabrir un SDD por feedback de código es esperado y barato.
- **Doble verificación trazada de toda info externa** (internet/normativa) contra fuente oficial, ideal por render visual del original. Proyecto delicado: lo usarán instituciones financieras; un número errado es riesgo regulatorio. (Principio no negociable #11.)
- **Verificación antes de ampliar**: re-verificar lo hecho antes de producir más. **Tras cada tanda/capa hay una sesión de revisión** (p.ej. "Tanda 1 Rev") antes de avanzar. Patrón de revisión validado: lectura adversarial multi-agente → triage/dedup → verificación adversarial (context7 para APIs) → integración por DanIA → 2ª pasada de verificación de las correcciones.
- **Evolución por SDD:** toda capacidad nueva o cambio contractual se diseña antes de programarse,
  usando `docs/design/_PLANTILLA-SDD.md`, revisión independiente e integración coordinada. Los SDD
  históricos conservan las decisiones ya implementadas; no constituyen por sí solos una cola activa.
- **Calidad del código (cuando se programe)**: `mypy --strict`, ruff, tests canónicos numéricos con
  golden values y 100 % de cobertura sobre la lista literal
  `nikodym.testing.regulatory.REGULATORY_COVERAGE_PATHS` (11 rutas; no equivale a todo el código
  regulatorio), `filterwarnings=["error"]`. SDD-24/25 los especifican.
- Decisiones de fondo: una recomendación, no menú. Conciso y ejecutivo.

## Decisiones de diseño fijadas
- **Licencia** Apache-2.0 (open-source). Evitar dependencias copyleft (GPL) — p.ej. `scikit-survival` queda fuera del core.
- **Modelo de negocio (Cami, 2026-07-21): la librería es 100 % gratuita y se publica completa.** No
  existe tier comercial, edición cerrada ni funcionalidad reservada; **nunca retener una capacidad del
  open-source para venderla aparte**. La monetización vive fuera del paquete: integración, fork
  personalizado para una institución, features a medida y servicios adyacentes (p. ej. automatizar en
  Python lo que el cliente hace en Excel). La librería abre la conversación; el trabajo pagado puede
  ser otra cosa.
- **Dos marcas de aviso declarado (2026-07-25).** `FALTA-DATO` = *lo debe Nikodym* (brecha del motor:
  algo que no trae, difirió o no verificó contra la fuente oficial). `DATO-INSTITUCIONAL` = *lo debe la
  institución* (parámetro, definición o dato de entrada que sólo ella puede fijar; el motor **se negó a
  inventarlo**). Ambas viven en `src/nikodym/core/markers.py`; los filtros consumen
  `is_declared_warning()`, **nunca** el literal —un filtro que sólo conozca una marca descarta la otra
  en silencio—. Regla de clasificación de todo código nuevo: una capacidad **diferida** es del motor
  aunque el parámetro lo escriba el usuario. Y los códigos internos **no van al copy público**: la
  limitación se explica en el idioma del lector, sin nombrar el código.
- **Qué cuenta como copy público (precisado el 2026-07-25, tras dos defectos vivos).** No es sólo la
  landing y el README: cuenta el **tooltip del formulario del UI instalable** —una `description` de
  Pydantic viaja a `schema.json` y de ahí al `FieldRenderer`—, el panel de resultados, la **prosa
  del informe** HTML/PDF/Word, `docs_site/`, y la descripción de un dataset o preset que devuelva el
  backend (un fallback puede copiarla tal cual a una card). **No** cuentan: `warning_codes` y
  `card.falta_dato`, las claves de los dicts de labels, comentarios, tests, `docs/design/` y el
  volcado de auditoría del anexo del informe —ahí el código es la evidencia—. Lo vigilan
  `web/src/lib/public-copy.test.ts` y `tests/unit/test_public_copy.py`. **El `README.md` SÍ está en
  el gate** desde el 2026-07-25 (decisión de Cami): lo consume `test_public_copy.py:44`, y la
  documentación de los códigos vive en `docs_site/avisos-declarados.md`, su única exención nueva.
- **«Instalable y usable» es requisito de entrega.** Una capacidad que el usuario de `pip install` no
  puede alcanzar cuenta como no entregada, por más tests que tenga. Ver
  [[feature-gateada-por-config-es-feature-inexistente]] y el bloque B2 del ROADMAP.
- **No se anuncia un motor de una jurisdicción que no exista.** Hoy sólo hay CMF (Chile);
  `provisioning/internal/` es el único componente jurisdiccionalmente reutilizable. Implementar una
  jurisdicción nueva exige compromiso comercial firmado (B3.b).
- **CMF ≠ IFRS 9**: dos motores separados (`provisioning/cmf` con PE=PI·PDI·Exposición, B-1; `provisioning/ifrs9` con ECL). ⚠️ **La regla del máximo del B-1 (Circular 2.346) es `max(método estándar, método interno del banco)`, por institución — NO `max(CMF, IFRS 9)`**: el Cap. A-2 num. 5 del Compendio excluye el deterioro de NIIF 9 sobre colocaciones. Ver ESPECIFICACIONES §5.4 (corregido 2026-07-13).
- **MVP Fase 1**: scorecard de **comportamiento** (sin reject inference; originación es sub-fase posterior).
- **Stack**: pandas (+ **pandera/pyarrow** deps base de `data`), **OptBinning** (binning), **statsmodels** (inferencia), **lifelines** (survival), Optuna, SHAP, MLflow, **Jinja2 + WeasyPrint** (informe HTML y PDF; Quarto se retiró en 1.0) y **python-docx** (export Word), capa IA opcional inyectable (documenta/narra, nunca calcula; la prosa del informe es determinista y NO la escribe la IA). Empaquetado **uv + hatchling** (≥1.27), `src/` layout. Config **Pydantic v2** (núcleo config-driven → la UI es editor del mismo config). Gobernanza **SR 11-7** en el núcleo.
- **`data_hash`** (Tanda 1 Rev, D2): hash del **contenido lógico por bloques** (`hash_pandas_object`), NO los bytes del Parquet (no canónico cross-versión). Inventario MLflow por **aliases+tags** con prefijo `nikodym.` (no stages, deprecados), ancla idempotencia `(model_name, nikodym.config_hash)`.
- **Contratos transversales (Hito 0, CT-1…CT-4)**: orquestación expresa el DAG en la firma (`Step.requires`/`provides`, `ArtifactKey`), motor v1 solo valida prerequisitos; contratos de lectura (resultados/metrics/overlay) crecen por **extensión aditiva**, nunca ruptura; `data` = panel transversal de scorecard, IFRS9/forward traen capa longitudinal propia; el ensamblado de corrida (sink+inventory) vive en capa fina api/runner (`assemble_run`), no en `core`. **SemVer 1.x**: el pipeline scorecard F1 es API estable; las APIs que crecen (results/overlay/metrics/orquestación) quedan marcadas experimental, fuera de la garantía SemVer 1.x.

## Mapa de documentos (`docs/`)
- `ESPECIFICACIONES.md` — spec maestra v1.0.
- `ROADMAP.md` — estado por capacidad y plan de evolución vigente; conserva las fases históricas.
- `normativa_cmf_parametros.md` — parámetros CMF verificados (tablas PI/PDI por cartera).
- `design/00-INDICE.md` — índice histórico de los SDD y sus decisiones.
- `design/01-core.md` … `28-provisioning-end-to-end.md` — contratos de diseño implementados o
  experimentales según el estado declarado en `ROADMAP.md`.
- `design/_CONTRATOS-TRANSVERSALES.md` — **decisiones troncales Hito 0** (CT-1…CT-4): qué se fija ahora vs qué se difiere, SemVer 0.x, criterios de aceptación de F0. **Leer antes de codificar F0.**
- `design/_PLANTILLA-SDD.md` — plantilla de cada documento de diseño.

## Git
Repo **PÚBLICO** en GitHub: **`nexolabs-gh/nikodym`** (cuenta `nexolabs-gh`), branch `main`, con issues habilitados. ⚠️ Ya no es privado —lo era durante la construcción— así que **todo lo que se commitea es visible para cualquiera**: nada de datos de clientes, credenciales ni detalle institucional fuera de `privado/`, que es un repo git **aparte y privado**, con respaldo remoto propio desde 2026-07-21 (antes era sólo local). Push directo a `main` autorizado en el cierre de sesión; **`privado/` se pushea en cada cierre igual que el público** — un respaldo que no se mantiene al día no es respaldo. No inventar coautoría: trailer solo si la herramienta que participó lo exige. `.gitignore` veta datos y secretos por defecto (proyecto regulatorio) — y desde el 2026-07-25 eso es
cierto de verdad: el patrón de `data/` llevaba el comentario **en la misma línea**, y como en
`.gitignore` el `#` sólo abre comentario al principio de la línea, el veto estaba inerte desde que se
escribió. **El comentario va siempre en su propia línea**, y `tests/unit/test_gitignore.py` lo hace
cumplir preguntándole a git en vez de leer el archivo. Los datasets externos viven en `data/`
(ignorado); los comprimidos se vetan **sólo** ahí, porque `web/src/fixtures/demo/*.zip` sí se
versionan. Dos excepciones más, ambas con test (2026-07-25): `docs/datasets/catalogo.csv` se
reincluye a mano —cae bajo el veto global de `*.csv` y sin eso la documentación de con qué datos se
valida la librería se perdería en silencio en el próximo clon—, y `docs/datasets/raw/` se veta
porque basta invocar `descargar.sh` desde su ubicación versionada para bajar gigabytes a un
directorio que sí se commitea. La regla general: **cada excepción al veto se prueba en los dos
sentidos** —que lo permitido pase y que lo prohibido siga vetado—.
