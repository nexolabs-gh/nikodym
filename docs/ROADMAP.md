# Estado y roadmap de evolución — Nikodym RiskLib

| | |
|---|---|
| **Documento** | Estado por capacidad y plan de evolución |
| **Versión** | 1.5 |
| **Fecha** | 2026-07-23 |
| **Base** | [`ESPECIFICACIONES.md`](ESPECIFICACIONES.md) v1.1 · [`design/00-INDICE.md`](design/00-INDICE.md) |

El código, el tag `v1.5.0` y PyPI están en `1.5.0`. `main` se encuentra en mejora continua; el próximo
release será un bump `1.6.0` con OK específico de Cami.
Las fases F0–F8 que siguen conservan el diseño y los DoD históricos; **no son una cola automática**.
El estado y el plan de esta sección son la fuente vigente.

## Estado actual

| Capacidad | Estado | Límite vigente |
|---|---|---|
| F0/F1 · núcleo y scorecard de comportamiento | **Estable** | Garantía SemVer 1.x para el pipeline F1 |
| F2 · ML/tuning/explain | Implementado, **experimental** | No sustituye la scorecard ni amplía SemVer F1 |
| F3/F8 · CMF, método interno y orquestación | Implementado, **experimental** | Validación humana de matrices/haircuts pendiente |
| F4 · IFRS 9/ECL | Implementado, **experimental** | Independiente del máximo B-1 chileno |
| F5/F6 · forward, survival, Markov, stress y validación | Implementado, **experimental** | Uso por config Python; sin preset/UI propios |
| F7 · UI React/FastAPI e informe | **No entregada como producto** | B2.1 y B2.2 cerrados (assets, supply-chain, licencias; launcher, runtime y seguridad) en `main`. `1.5.0` —lo publicado— sigue sin launcher/assets, y `[ui]` no cierra sus presets hasta B2.3 |
| Originación/reject inference | Futuro | Requiere caso de uso, priorización y SDD |

## Plan operativo vigente (desde 2026-07-21)

El track pre-reunión quedó cerrado con el release `1.4.1`. Lo que sigue es el plan de mejora continua
fijado el 2026-07-21, ordenado por prioridad de ejecución. **Ningún bloque se inicia por estar en esta
lista**: cada uno arranca cuando el anterior cierra o cuando su condición explícita se cumple.

### Marco de producto (decidido 2026-07-21)

- **La librería es y seguirá siendo 100 % gratuita bajo Apache-2.0.** No hay edición cerrada, tier
  comercial ni funcionalidad reservada. El código que se publica es el código completo.
- **La monetización vive fuera del paquete**: integración en la institución, adaptación o *fork*
  personalizado, funcionalidades a medida y servicios adyacentes de automatización. La librería abre
  la conversación técnica; el trabajo pagado puede terminar siendo otra cosa. Esto **no** condiciona
  qué se publica: nada se retiene del open-source para venderlo aparte.
- **«Instalable y usable» es requisito, no adorno.** Quien ejecute `pip install nikodym` debe poder
  levantar y usar el producto sin conocimiento interno del repo. Una capacidad que existe pero que el
  usuario no puede alcanzar cuenta como no entregada.
- **Los módulos experimentales se mantienen ofrecidos.** F5/F6 amplían lo que la librería puede
  conversar con una institución; no se podan. Lo que les falta es ruta de uso, no justificación.

### B1 · Higiene y deuda corta → **CERRADO** (publicado en `1.5.0`, 2026-07-22)

Cerró los defectos conocidos que sólo vivían en el HANDOFF. Todos acotados y verificables.

1. ~~**Rótulo de los dos ECL del anexo IFRS 9.**~~ **HECHO (2026-07-21, `ee9b0cb`).** Se añadió la
   clave hermana `ecl_by_scenario_basis` (extensión aditiva, CT-3). El rótulo declara **dos**
   motivos de la brecha, no uno: la cifra por escenario no aplica `scenario_weights` **y** cubre el
   horizonte completo, mientras la reportada pondera y trunca Stage 1 a 12 meses. No apunta a
   `staging_distribution` —esa clave vive en la capa UI y no existe en el anexo—.
2. ~~**Deuda cosmética del informe y del editor de config.**~~ **HECHO.** ~~Diagnósticos del motor
   de selección con decimales sin formatear~~ y ~~`total_expected_loss_rate` como string de 51
   dígitos~~ **(2026-07-21, `f34d13c`)**: los `detail` de IV/VIF/correlación/contribución/p-valores
   pasan a 6 cifras significativas y la tasa pasa de texto a `float` (**cambio de tipo** declarado
   en el CHANGELOG; superficie experimental, fuera de la garantía SemVer 1.x). ~~Descriptions del
   schema con jerga interna~~ **(2026-07-22, `2484511`)**: 185 textos reescritos —`description`,
   `title` y `ui_group`— más los descriptores de preset y dataset, con el fixture regenerado en el
   mismo commit atómico. El alcance real era una clase, no dos campos: 78 textos citaban documentos
   internos en el editor que ve el usuario. **Se conservan** las referencias normativas, la
   terminología de riesgo y los códigos de aviso que el motor imprime en el informe.
   La limpieza destapó **nueve afirmaciones que el motor no respalda** (cinco anteriores a esta
   pasada), entre ellas dos gatillos SICR descritos con un mínimo que el validador no impone y un
   `is_default_col` que omitía la reclasificación del deudor de consumo a incumplimiento. Quedan
   **cuatro campos inertes** ya declarados como tales en su texto (`repro.strict_determinism`,
   `tuning.validation.fit_partition`, `survival.fail_on_falta_dato`, `report.pdf.enabled`):
   cablearlos o retirarlos es trabajo aparte, fuera de B1.

   > **Medición del 2026-07-22 (tarde): esos cuatro campos son la punta de una clase mayor.** Un
   > barrido sobre los **800 campos** de los **121 modelos** Pydantic del config identificó **58
   > candidatos** a campo inerte, en dos patrones: el *huérfano* (el motor no nombra el campo) y el
   > *leído-nunca* (el motor lo nombra pero le pasa un literal, sin leer el config). **Solo 2 de los
   > 58 completaron verificación adversarial** —la corrida se agotó por cuota—, así que el resto son
   > **hipótesis con evidencia, no defectos confirmados**, y varias tocan superficie regulatoria.
   > Antes de cablear o retirar nada hay que terminar la verificación. Es el mismo sesgo de método
   > que B1.2: el ítem enumeraba los síntomas notados, no el patrón.
3. ~~**Respaldo remoto del workspace interno.**~~ **HECHO (2026-07-21).** El workspace interno ya
   tiene repo privado propio fuera del disco local; el respaldo se verificó restaurándolo (clon
   completo, idéntico al original) y se mantiene al día pusheando en cada cierre de sesión.

### B2 · La UI instalable y usable  ← *requisito de producto*

**Estado: B2 total ABIERTO; B2.0 CERRADO; B2.1 CERRADO (2026-07-24); B2.2 CERRADO (2026-07-24).**
B2.2 se programó tras aprobar su enmienda
([`design/_ENMIENDA-B2.2.md`](design/_ENMIENDA-B2.2.md), fuente de verdad del nodo) y pasó dos rondas
de revisión adversarial fresca —una sobre el diseño y otra sobre el código—. El cierre se declara
sobre `1f9b027` con los **16 jobs del CI verdes** (run `30126576076`), tras verificar además el wheel
instalado en un venv limpio y el console script arrancado.
**Límite medido del cierre (L-B2.2-CI):** `tests/unit/test_ui_launcher.py` se **skipea en los 9 jobs de
matriz** Windows/macOS/Linux, porque `fastapi` sólo entra con `--extra ui` y la matriz instala
`--extra scoring`. Toda la evidencia de ejecución del launcher sale por tanto de un **único job
Linux** (`Tests all extras`) más la verificación local en macOS; el verde de Windows prueba que el
paquete importa y que la suite general pasa, **no** que el launcher arranque ahí. Cerrar esa brecha
es trabajo de B2.4 (clean-room), donde el recorrido se ejecuta desde el wheel. La
medición
clean-room y la reapertura de SDD-23/25 se cerraron el 2026-07-23 sobre
`dd89f7d35cefb0aebb4ec2055c4ca81c171dd59e`, con revisión adversarial final sin P0/P1/P2 y
auditoría API aprobada. Esa transición B2.0 aprobó el contrato sin implementar distribución; el
cierre B2.1 descrito abajo sí incorpora los assets al candidate de `main`, pero no modifica
retroactivamente el producto `1.5.0` publicado.

**Línea base oficial `1.5.0`.**

- Wheel `nikodym-1.5.0-py3-none-any.whl`, SHA-256
  `5bc4ad78d6b134c199a5e392d714f35b1dac9807c59ff2a47eea4589e297f015`.
- Sdist `nikodym-1.5.0.tar.gz`, SHA-256
  `9d7db9efabb6590db492c71ac9f2c11043d5b431d4e0ab49cfb07a92fef9e524`.
- `pip install "nikodym[ui]==1.5.0"` funciona para el backend, pero no instala console script,
  `nikodym/ui/__main__.py`, `static/index.html` ni assets JS/CSS. `/api/*` responde con bootstrap
  manual; `/` no entrega la SPA.
- Un upload externo válido expuso dos brechas adicionales: al ejecutar se deja `loan_id` como
  columna con `RangeIndex` pese al `index_col` del preset F1, y `[ui]` no instala scoring
  que requieren los presets visibles F1/F3/F4. Ninguno completa una corrida ni genera informe con
  solo el extra publicado.

**DAG aprobado — un nodo habilita al siguiente.**

1. **B2.1 · assets, supply-chain y licencias — ✅ CERRADO (2026-07-24).** `web/` es fuente completa en Git y wheel/sdist
   distribuyen solo el build normal versionado en `src/nikodym/ui/static/` y se construyen sin Node.
   `.node-version` fija Node 22.22.2, `packageManager` fija pnpm 11.15.0 e instalación frozen; tooling
   pasa a `devDependencies`. Un plugin versionado del build normal Vite (`transform` +
   `generateBundle` + `writeBundle`) separa fuentes directas de la unión conservadora y liga los
   bytes finales de cada output; los inventarios pnpm
   full/prod solo reconcilian declaraciones y **no** prueban redistribución. Notices nacen de la
   procedencia y concatenan íntegramente todos los textos legales convencionales
   LICENSE/LICENCE/NOTICE/COPYING/COPYRIGHT más atribuciones explícitas, con hashes fuente/final
   ligados al candidate; SPDX solo no basta.
   `lightningcss`/MPL exige allowlist build-only exacta y ausencia de prod/procedencia. El build
   normal veta módulos de `web/src/fixtures/demo/**` y un sentinel + hashes/firmas detecta material
   inline/emitido. La demo se construye en un directorio temporal y no puede alterar el árbol
   distribuible; el build normal se repite y debe ser byte-idéntico. Otra allowlist inspecciona
   wheel/sdist y excluye `web/`, fixtures demo, `.vercel`, datos y binarios. La fase B2.1 del
   manifiesto exige index, notices y recursos locales; B2.2 añadirá `__main__` y entry point a
   `required`. El job frontend sube evidencia autoritativa solo tras completar todos sus gates; un
   job Python con checkout separado la descarga, exige exactamente un wheel universal y un sdist de
   la misma versión y comprueba en ambos igualdad exacta de rutas/tamaños/SHA-256 con esa
   procedencia. También reconstruye el wheel desde el sdist y revalida. Candidate, evidencia y
   reportes quedan juntos bajo un `SHA256SUMS`. En Python, el gate permisivo cubre base +
   `--extra all`; `[pdf]` queda fuera por WeasyPrint→Pyphen y se audita/documenta en un job opt-in
   separado. B2.1 no añade launcher ni completa `[ui]`: ambos siguen en B2.2/B2.3.
   **Cierre (2026-07-24), tras tres ciclos de revisión adversarial fresca.** Cada ciclo encontró el
   siguiente nivel de la misma clase en el analizador del bundle: primero el receptor de la llamada
   (`parent.fetch` pasaba), luego el grafo de bindings (`const {top:T} = window` pasaba, con PoC sobre
   el `index.html` real). Ambos cerrados y cubiertos por tests que se verificó que **fallan con el
   código anterior**, con aislamiento por hallazgo. El ciclo se cerró por contrato, no por
   agotamiento: SDD-25 §6.1 declara ahora el alcance del gate y sus cinco límites medidos (L1…L5), de
   modo que lo no cubierto está escrito en vez de implícito. Se añadieron además `window.open`,
   `location.assign`/`replace`, `document.write`/`writeln`, `serviceWorker.register` e
   `insertAdjacentHTML`, todos con 0 ocurrencias en el bundle real. En el lado Python, el gate de
   licencias dejó de auditar sólo el corte del runner —evaluaba los markers contra un único entorno y
   descartaba 9 pines en silencio— y pasa a una **matriz de 30 entornos soportados**, con las
   declaraciones ancladas a la core metadata upstream vendorizada y hasheada, re-verificable contra
   PyPI en un paso propio del CI. Eso destapó `nvidia-nccl-cu12` (`LicenseRef-NVIDIA-Proprietary`,
   ~303 MB) entrando por `xgboost` en Linux: el extra pasa a resolver **`xgboost-cpu`** bajo
   `sys_platform == 'linux'`, que es el mismo proyecto en Apache-2.0 y sin rutas GPU (98 MB → 5,7 MB
   por wheel). El job `release` **sigue sin pasar por estos gates** y su cableado es B2.5; §7.7 lo
   declara explícitamente en vez de describirlo como vigente.
2. **B2.2 · launcher, runtime y seguridad.** `nikodym-ui = nikodym.ui.__main__:main`, `argparse`,
   bind fijo `127.0.0.1:8000`, `.nikodym_ui`, navegador abierto y
   `--no-open`/`--port`/`--workdir` —sin `--host`. Cada lanzamiento crea un token aleatorio de
   256 bits, no log/URL, inyectado en memoria en el index; la SPA lo envía por header. Toda request
   valida `Host` exacto; upload/run exigen `Origin` same-origin + token y CORS externo está apagado.
   El index inyectado responde `Cache-Control: no-store` y no se persiste.
   SPA `/`, API relativa `/api`, assets `/assets`, same-origin y
   sin subpath en `1.6.0`; API registrada antes del fallback. Falta del index o de **cualquier**
   `src`/`href` local —favicon incluido— falla antes de bind; exposición a red queda diferida como R0.
3. **B2.3 · `[ui]`, uploads y presets.** Como delta, `[ui]` compone
   `nikodym[scoring,excel,docx]` + FastAPI/Uvicorn/multipart y preserva
   `scikit-learn>=1.6,<1.8`. `allow_live_execution=false` devuelve 403
   en upload/run pero conserva lectura/validación. `upload_max_mb` tiene default único de 100 MiB y
   lectura por chunks. Upload guarda los bytes originales en `uploaded_<sha256><suffix>` sin parsear
   ni convertir y devuelve solo metadata física. `/run` copia el config cambiando únicamente
   `source=None` y pasa el raw path a la extensión aditiva de `nikodym.run`; la API pública coacciona
   `DataConfig` perezosamente, carga path/DataFrame con `DataLoader`, resuelve `schema_.index_col`
   sin ambigüedad e inyecta el frame tras conectar audit. Preflight inválido ocurre antes de
   `Study`/sink y el endpoint lo traduce a 422 —incluido `MissingDependencyError` de DataLoader—;
   la misma clase nacida dentro de `Study.run` queda capturada como `Study failed`/200 y siempre
   cierra el sink. No hay Parquet intermedio. HTML es obligatorio; PDF degrada.
4. **B2.4 · candidate wheel clean-room + Playwright.** Fuera del checkout se instala solo
   `<wheel>[ui]`, se lanza `--no-open` y se permite exclusivamente loopback. Se comprueba `/` +
   HTTP 200 de cada `src`/`href` local —favicon incluido— y se ejecutan
   F1/`consumo_comportamiento`, F3/`provisiones_consumo` y
   F4/`ifrs9_retail_latam` hasta `done` + resultados + HTML; además F1 con CSV externo y `loan_id`.
   Negativos Host/Origin/token y cero red externa son obligatorios. El control negativo elimina
   `index.html` y, por separado, un recurso local obligatorio en una instalación descartable y exige
   fallo antes de bind.
5. **B2.5 · documentación y release.** README/docs explican instalación y arranque en dos comandos.
   Release publica exactamente el wheel/sdist gateados, sin rebuild. Tag/PyPI `1.6.0` conservan el
   OK específico de Cami.

**Identidad del DoD.** Antes de correr: igualdad estructural del config +
`config_hash(UI) == config_hash(código)`; la ubicación de datos se excluye del `config_hash`.
Después de correr: igualdad de `data_hash` —contenido lógico— y resultados canónicos.

> **Criterio de cierre de B2:** no basta un candidate local ni CI verde. B2 cierra únicamente cuando
> los artefactos gateados se publican en PyPI y un tercero, sin checkout, repite desde esa publicación
> `instalar → lanzar → F1/F3/F4 done + HTML → F1 con CSV propio`. La aprobación de B2.0 no satisface
> este criterio: B2 total permanece abierto y F7 sigue no entregado.

### B3 · Abstracción de jurisdicción (CMF ≠ SBS ≠ …)

Hoy el motor de provisiones regulatorias está casado con Chile: `provisioning/cmf/engine.py` concentra
2.044 líneas con ids, carteras y buckets chilenos. En cambio `provisioning/internal/` ya es casi
neutro — su única atadura real es el `default="cmf_portfolio"` de su config.

Se ejecuta en dos etapas con condiciones distintas:

1. **B3.a — SDD + refactor de abstracción (sin implementar ninguna jurisdicción nueva).** Fijar el
   contrato que separa «motor de provisión estandarizada» de «parámetros y reglas de una
   jurisdicción», y dejar `internal/` genuinamente neutro. **Tiene valor por sí solo**: es deuda
   arquitectónica que hoy impide describir con honestidad el costo de un port.

   **B3.a se parte en dos (Cami, 2026-07-25), y sólo la primera mitad bloquea aguas abajo.** El censo
   del código encontró 15 puntos de chilenidad, y no pesan igual:

   - **B3.a-1 · la llave de segmentación. REDEFINIDO el 2026-07-25 tras medirlo contra el código**
     ([`_ENMIENDA-SEGMENTACION.md`](design/_ENMIENDA-SEGMENTACION.md)). La premisa original —«el
     segmento es un enum chileno»— resultó **falsa**: el `Literal` de `governance/config.py:27` no es
     la llave de segmentación de ningún cálculo (una sola lectura, un tag de inventario, ni siquiera
     llega al `schema.json`), y la llave real, `portfolio_col`, ya era `str` libre en los tres
     motores. El bloqueo verdadero era otro: **nadie declaraba el dominio de valores del segmento**,
     y sin dominio no hay CRP-1 ni CRP-3. B3.a-1 pasa a ser: la llave gana **esquema declarado**
     (normativo / institucional / derivado del dato), el esquema **viaja en el resultado** —el
     orquestador nunca ve el config de los motores— y el régimen se garantiza con un **registro
     régimen→motor** con test de cobertura, no con el sistema de tipos. **Implementado**
     (D-SEG-1…D-SEG-10); ver §«Pendiente de B3.a-1» abajo.
   - **B3.a-2 · el contenido normativo del motor CMF.** Matrices y su versionado, tramos de mora B-1,
     `is_default = dpd >= 90` (`cmf/engine.py:540`), buckets PVB/PVG, rangos C1-C6, títulos del
     informe. **No bloquea, y que sea chileno es correcto**: ese motor *es* el método estándar
     chileno. Se abstrae cuando exista un segundo motor que exija el molde común — es decir, con
     B3.b.

   Orden resultante: **B3.a-1 → contrato de resolución de parámetros → B3.a-2 con la jurisdicción
   nueva.**

   **Estado del contrato al 2026-07-26.** Su §2 se re-midió con lectores frescos y quedó enmendado
   ([`_ENMIENDA-CRP-IFRS9.md`](design/_ENMIENDA-CRP-IFRS9.md), aprobada): cayó P3 —la procedencia no
   la registra «un solo lugar»—, se corrigieron los dos polos de P2, y el problema resultó mayor de
   lo medido (seis gatillos apagados por defecto, nueve warnings de carencia sin marca, siete
   definiciones de `fail_on_falta_dato` con cinco semánticas). El orden de adopción quedó
   **CRP-5 → CRP-6 → CRP-4 → CRP-1/CRP-3 → CRP-7**, porque CRP-4 sólo rotula y lo que corrige las
   cifras es el gate. **CRP-5 está implementado en IFRS 9** (`afa3403`, CI verde): la LGD *workout*
   ya no asume coste de recuperación cero —subestimaba 20 pp en silencio—, el gatillo Stage 3 ya no
   se apaga cuando falta la columna declarada, y los pesos de escenario se validan antes de ponderar
   la PD y no después.

   **CRP-6 — CUMPLIDO en las siete capas** ([`_ENMIENDA-CRP6-FLAG.md`](design/_ENMIENDA-CRP6-FLAG.md),
   D-CRP6-1…D-CRP6-8, aprobada). El censo de las siete capas se re-midió contra *la pregunta que
   CRP-6 define* en vez de contra el mecanismo, y **cinco ya cumplían**: comprobar en el config
   cuando la carencia ya es demostrable no es otra semántica, es CRP-5. Las «cinco semánticas» son
   ciertas en su unidad —igual que el «34 vs 24» de las marcas—, pero no son la unidad que dimensiona
   el trabajo. Dos hallazgos que ningún censo previo tenía:

   - **El flag de `ifrs9` no gobernaba ninguna marca.** Su `False` sólo movía el chequeo PIT al medio
     del cálculo (`_apply_vasicek` levantaba igual), que es lo que CRP-5 prohíbe. Por eso el chequeo
     pasó a ser **incondicional** en vez de renombrarse como mandaba el contrato: sin migrador, sin
     tocar `schema.json` por el nombre y sin recaptura.
   - **`FALTA-DATO-IFRS-4` se emite en toda corrida** —medido con la EAD entregada por la
     institución—, así que conectar el flag tal cual habría **abortado todo IFRS 9** con su default y
     en los tres presets. De ahí la distinción que CRP-4 hereda: marca **gobernable** (existe una
     entrada válida sin ella) vs **estructural** (capacidad diferida del motor: se registra siempre,
     nunca detiene). Vive en `core/markers.py::governable_warnings`.

   **Bloque B implementado el 2026-07-26: las siete capas cubiertas.** `survival` dejó de ser el
   campo no-op que la propia enmienda condenaba —el gate vive en `step.py::_card_from_model`, el
   único punto donde la capa conoce todas sus marcas— y el preset F4 declara sus intervalos de
   confianza. Dos correcciones al plan escrito, ambas por medición previa:

   - **`SUR-1` tenía cuatro emisores, no uno.** El censo sólo citaba `kaplan_meier`; también la
     emiten `cox_aft`, `discrete_hazard` y el propio `step` cuando no se declaró grilla. No amplió
     el alcance, pero sí decidió **dónde** va el gate: dentro de un motor, la carencia del step se
     habría escapado.
   - **El «preset que se contradice» no existía.** El censo daba por hecho que el preset F4 declara
     `fail_on_falta_dato=True` junto a la carencia `SUR-3`. Corrido sobre su dataset real emite
     `falta_dato=()`: usa `method="discrete_hazard"` y `SUR-3` sólo la emite `kaplan_meier`, así que
     `confidence_level=None` nunca se lee. La decisión se mantuvo con **otra razón** —`method` es
     editable desde el formulario, y con el flag activo el preset dejaría de correr al cambiarlo—.

   **Queda fuera el P2** (el preset F4 sale de `pit_mode="ttc_only"`), y no por orden de trabajo:
   medido, **ninguna de sus dos salidas es alcanzable hoy**. `consume_pit` exige una term-structure
   con `pd_basis='pit'` que `survival` no produce (habría que encadenar `forward`), y
   `apply_vasicek` exige `rho` **y** `systemic_factor_col`, columna que el dataset
   `ifrs9_retail_latam` no tiene (habría que ampliar `_generate_ifrs9_retail`). Es alcance de otra
   magnitud que CRP-6 y espera decisión de Cami.

   **Pendiente de B3.a-1 al 2026-07-25** (lo demás está implementado y con gates):

   - **El selector de régimen en preset y UI: DIFERIDO a propósito (Cami, 2026-07-25)**, no olvidado.
     Se difiere hasta que la UI exponga las secciones de provisiones, y entonces el régimen nace como
     **campo real** junto al resto de su config. Tres razones: (a) un desplegable con **una sola**
     opción no es una elección, y ofrecer más contradiría la regla de honestidad de este mismo
     bloque; (b) el objetivo de fondo —que «provisiones» deje de significar Chile sin decirlo— ya se
     cumple donde el usuario lee: el informe titula «Método estándar de la CMF de Chile (Cap. B-1)»
     (`report/document.py:94-96`) y la landing rotula CMF como chileno; (c) hoy las secciones
     `provisioning*` **no son editables por formulario** (`web/src/lib/schema.ts` sólo declara las 7
     de F1), así que un selector iría encima de un formulario que no existe. Lo que sí quedó listo:
     el régimen viaja en el resultado (`segmentation.regime`) y el registro expone su rótulo público,
     de modo que cablearlo será una línea que lee del registro, no un rediseño.
     ⚠️ **Ese hueco de formulario es el pendiente real de paridad UI↔código** (requisito 1 de la
     visión) y es mayor que el selector: el motor de provisiones sólo se alcanza por preset o
     subiendo un YAML.
   - **La recaptura de la demo**, que va una sola vez y al final (ver §5 de la enmienda).
     **Ejecutada el 2026-07-26** con el bloque B de CRP-6: bump a `1.6.0` y las tres capturas
     (F1, F3, F4) en patrón C-D.

   **Sacar el preset F4 de `pit_mode="ttc_only"` — PENDIENTE, y no es un cambio de una línea**
   (medido el 2026-07-26; venía arrastrándose como «P2» del handoff). El preset publica PD **TTC**
   presentadas dentro de un motor IFRS 9, y salir de ahí tiene exactamente dos vías, **ninguna
   alcanzable con lo que hoy existe**:

   - **`pit_mode="consume_pit"`** exige una term-structure etiquetada `pd_basis='pit'` en todas sus
     filas (`ifrs9/engine.py::_require_pit_basis`). La produce `survival`, que es TTC —el propio
     mensaje de error lo dice—. Habría que **encadenar `forward` en el preset F4** para que las
     curvas lleguen PIT: es la vía metodológicamente más rica y el cambio de cadena más grande.
   - **`pit_mode="apply_vasicek"`** exige `rho` **y** `systemic_factor_col`
     (`ifrs9/config.py:672-684`), y el dataset `ifrs9_retail_latam` **no trae ninguna columna de
     factor sistémico** (17 columnas, verificadas). Habría que ampliar `_generate_ifrs9_retail` en
     `ui/datasets.py`: vía más corta, pero toca el generador de datos y arrastra otra recaptura.

   Cualquiera de las dos mueve `config_hash` y cifras del informe, así que va con su propio bump y
   su propia recaptura. **Decisión de Cami pendiente**; entretanto el preset es honesto —declara
   `ttc_only`— pero no ejercita el forward-looking que IFRS 9 sí contempla.

   **Cerrado desde que se escribió esta lista:** el **gate de entrada del motor CMF** (D-SEG-4) ya no
   descubre la cartera desconocida a mitad del cómputo — `_validate_portfolio_domain`
   (`cmf/engine.py:446-462`) la rechaza al entrar, con el `raise` del despachador conservado como
   defensa en profundidad (`fc651dc`). Es además el **patrón de referencia de CRP-5**: el gate de
   entrada de IFRS 9 lo replica (`afa3403`).
2. **B3.b — Implementación de una jurisdicción concreta.** No se inicia de forma especulativa;
   requiere un compromiso comercial firmado. Sin él, el trabajo es una apuesta sobre normativa
   extranjera que además puede cambiar antes de tener usuario.

> **Regla de honestidad**: mientras B3.b no exista, la librería **no** tiene motor SBS ni de ninguna
> otra jurisdicción, y no se insinúa lo contrario. El módulo `internal/` sí es utilizable hoy fuera de
> Chile, y ése es el alcance real que se comunica.

**Requisito de producto añadido (Cami, 2026-07-24): la jurisdicción debe ser una elección visible,
no un supuesto.** Hoy «provisiones» significa Chile sin decirlo, y el proyecto es LATAM. B3.a debe
entregar la jurisdicción como **selector explícito** en preset y UI —`Provisiones · Chile (CMF)`—
de modo que el usuario vea que está eligiendo un régimen y no «el» régimen. Condición dura, derivada
de la regla de honestidad de arriba: el selector **nace con una sola opción real**; una jurisdicción
sólo aparece en la lista cuando existe su motor (B3.b). Un desplegable que muestre `Perú (SBS)` en
gris o «próximamente» es exactamente la insinuación que esta regla prohíbe.

### B4 · Rutas de uso para F5/F6

F5 (forward, survival, Markov, stress) y F6 (validación avanzada) están implementados y cubiertos por
tests, pero sólo se usan escribiendo el config en Python. Se mantienen en la oferta, así que necesitan
al menos **un preset documentado y un ejemplo ejecutable por capacidad** — no una UI completa. Sin
eso, ofrecerlos es ofrecer algo que el usuario no puede ejecutar.

### B5 · Validación humana de las matrices CMF (gate G0)

Sigue siendo el DoD incumplido de F3 y **no lo puede hacer un agente**. Se ejecuta sí o sí, pero no
encabeza la cola: CMF es Chile y el alcance del proyecto es LATAM. Hasta que ocurra, F3 se comunica
como experimental sin excepción. Detonante natural: el primer compromiso concreto en Chile.

**Precisión (Cami, 2026-07-24): lo que molesta es que la procedencia pública se apoye en «asistencia
de IA».** Es lo primero que lee un gerente de riesgo, y en un producto regulatorio una transcripción
asistida no respalda un número. **La frase no se toca antes de la validación**: borrarla sin hacer el
trabajo convierte una limitación declarada en una afirmación falsa de procedencia, que es un riesgo
mucho mayor que el disclaimer. El orden es: validar → registrar en governance → recién entonces
reescribir el texto, porque cambió el hecho.

- **El trabajo pendiente es más acotado de lo que sugiere el disclaimer.** `normativa_cmf_parametros.md`
  §3 documenta que las cuatro tablas críticas —comercial individual A1–B4, hipotecaria vivienda PVG,
  PDI de consumo (Circular 2.346) y avales— ya se verificaron **visualmente contra el render del PDF
  oficial**, con coincidencia 100 % y un error real detectado y corregido en la columna *Escala
  Internacional* de avales. Lo que falta es la pasada humana celda por celda y su **registro
  firmado**, no una extracción desde cero.
- **Al cerrar, el texto cambia en varias superficies a la vez** (patrón conocido del repo): la doc
  pública `docs_site/index.md`, el `README.md`, y `web/src/components/landing-evidence.ts` —que
  además viaja al bundle distribuido y a la demo, así que exige recaptura y verificación del
  artefacto final, no sólo del fuente.
- **Estado del texto al 2026-07-25.** Las salvedades que rodean a la frase se reescribieron para
  sacarles los códigos internos (`docs_site/index.md` y `landing-evidence.ts`, con el bundle
  versionado rebuildeado). **La frase de «asistencia de IA» sigue intacta y así debe quedarse**
  hasta que la validación humana ocurra. Al cerrar B5 hay que revisar las dos frases juntas: la de
  procedencia y la de las dos tablas faltantes, que hoy dicen que el manifiesto las declara
  faltantes en vez de rellenarlas.

### B6 · Workspace de evidencia de corridas v1

Bloque planificado con anterioridad, mantenido pero **repriorizado según feedback comercial**. Produce
y aprueba un único SDD; la primera rebanada vertical extiende la corrida local existente sin duplicar
un motor MLOps:

1. `SourceSnapshot`: identidad inmutable de fuente/as-of, esquema, conteos y hash lógico; inicialmente
   sólo archivos, datasets sintéticos y uploads ya soportados.
2. `ExecutionLedger`: transiciones y eventos append-only por `Step` en la capa fina runner/API, no en
   `core`.
3. Workspace: listar, reabrir, clonar y comparar corridas compatibles usando manifiestos y resultados
   existentes.

El SDD debe fijar migración de corridas actuales, escrituras atómicas, idempotencia, concurrencia,
crash recovery, codecs JSON/Parquet, exclusión de secretos y reglas de compatibilidad. Estados
asíncronos, cancelación cooperativa y reanudación se implementan sólo cuando el runner pueda cumplirlos
de forma durable; nunca se simulan sobre HTTP.

### B7 · Mapa regulatorio LATAM

Investigación de reguladores de la región, hoy incompleta y con errores detectados por el verificador.
**Queda en plan, sin prioridad.** Material de conversación, nunca de publicación ni de cotización, sin
otra pasada completa de verificación contra fuente oficial.

### B8 · Cola candidata, no autorizada

`SplitPolicy`, `ScenarioContract`, `ValidationLedger`, `SatelliteModel v2`, `PortfolioStress` y
`PortfolioForecast`. Ninguno se inicia por mera presencia en esta lista.

## Historial: P0 — Cierre pre-Interbank *(cerrado con `1.4.1`)*

1. Recuperar **al menos 12 GiB libres** y completar el preflight reproducible de la campaña. El
   corte de esta consolidación quedó bajo ese umbral; no iniciar una ejecución larga con el disco
   en presión.
2. ✅ **Cerrado (2026-07-20).** Las seis brechas de contrato `forward`→IFRS 9 quedaron resueltas
   o caracterizadas con tests, actualizando SDD-16/SDD-20 en el mismo bloque: `rho_col` rechazada
   fail-fast en config (consumo real diferido); exención del `Z` implícito eliminada (Z siempre
   explícito; con fuente forward la vía es `consume_pit`); guard anti doble ajuste PIT/TTC en el
   motor; `forbid_mean_scenario` bloqueante en config y motor (antes sólo auditado); pesos cero
   caracterizados como frontera con tests (resolución de fondo = decisión de política pendiente);
   LGD forward ignorada ahora con aviso auditado `FALTA-DATO-IFRS-6` y golden invariante
   (precedencia pendiente de SDD propio).
3. ✅ **Cerrado (2026-07-20).** Campaña adversarial de la demo F1/F3/F4: caza por 7 ejes → 4 fixes P0/P1
   integrados en `main` (P0 estado obsoleto al cambiar de preset en los 4 caminos; P1 selector de dataset;
   P1 fuga de ruta host en informes F1/F4; P1 `toyaml` stale), con revisor fresco por candidato.
4. ✅ **Cerrado (2026-07-20).** Reproducido el riesgo de resultados obsoletos al cambiar de preset (era
   real) y corregido. Sólo se tocaron P0/P1 verificables.
5. ✅ **Cerrado (2026-07-20).** Gates completos verdes (12/12), revisión independiente y `demo.nikodym.cl`
   re-deployada y verificada por hash contra el SHA aprobado (`1aba6cf`).
6. ✅ **Cerrado (2026-07-20) con el release `1.4.0`.** Al bloque de pulido P2/P3 (locale es-CL,
   marcador «—», descriptions honestas de `rho_col`/`fail_on_falta_dato`, badge «Experimental» en la
   card CMF F3, `to-yaml` determinista y `config_hash` sin `data.load.source`) se sumaron cuatro
   defectos que encontró la verificación adversarial del propio release, todos de cara al lector del
   informe: `Decimal` crudo en las celdas (52 dígitos en la tabla de provisiones internas), tablas de
   10+ columnas ilegibles en el PDF (ahora en hoja apaisada), la tabla insignia de IFRS 9 rotulada
   con su clave interna y la jerga de ingeniería en la prosa (DTO, `ValidationResult`, SDD-16,
   SemVer). Demo recapturada y re-deployada, tag `v1.4.0` y PyPI publicados con OK de Cami. Falta
   sólo congelar antes de la reunión del **2026-07-22**.

El gate humano de las matrices CMF **no** se cerró con este track: sigue abierto como **B5**.

## Qué no hacer

- No retener funcionalidad del open-source para venderla aparte: la librería es gratuita y completa.
- No anunciar ni insinuar un motor de una jurisdicción que no esté implementado (ver B3).
- No implementar una jurisdicción nueva de forma especulativa, sin compromiso comercial (B3.b).
- No copiar DataHub, SQL, defaults ni metodología institucional; sólo reimplementar patrones genéricos.
- No construir conectores remotos antes de fijar `SourceSnapshot`.
- No mezclar `ExecutionLedger` operacional con `ValidationLedger` humano.
- No presentar CMF/IFRS 9/forward/stress como certificados por estar implementados.

## Principios de secuencia
1. **Cada fase entrega valor por sí sola.** No se avanza sin DoD + tests + docs de la anterior.
2. **Fundación primero, auditabilidad desde el día 0.** Sin `core`/`audit`/`governance` nada es reproducible ni defendible.
3. **Lo que produce PD va antes de lo que la consume.** Scoring (F1) es cimiento de CMF, IFRS 9 y lifetime.
4. **Open-source como escaparate** → calidad ejemplar es requisito de cada fase, no un extra.
5. **Dos disciplinas de proceso:** un SDD aprobado antes de codear cada módulo; `HANDOFF.md` como puente entre sesiones.
6. **Doble verificación de toda información externa.** Cada dato/tabla/parámetro de internet o normativa se valida contra la fuente oficial por una segunda vía (ideal: render visual del original). Usado por instituciones financieras → un número errado es riesgo regulatorio. Nada avanza sin doble check trazado.
7. **Verificación antes de ampliar (Tanda 0).** Antes de producir nuevos documentos, se re-verifica que lo ya hecho esté correcto. Ver la Tanda 0 en [`design/00-INDICE.md`](design/00-INDICE.md).

## Mapa de fases

| Fase | Nombre | Entrega clave | Esfuerzo | "¿Qué se puede mostrar?" |
|---|---|---|---|---|
| **F0** | Fundaciones & gobierno | Esqueleto auditable | M | Repo serio, CI verde, lineage |
| **F1** | Scorecard comportamiento | **MVP open-source** | L | Scorecard end-to-end + reporte |
| **F2** | Machine Learning | Benchmark + SHAP | M | CatBoost vs logística, explicado |
| **F3** | Provisiones CMF | Motor B-1 | M | Provisión regulatoria chilena |
| **F4** | IFRS 9 / ECL | ECL independiente | XL | Pérdida esperada bajo IFRS 9 |
| **F5** | Forward-looking | Lifetime + escenarios | XL | Term-structure, macro, Markov |
| **F6** | Validación avanzada | Backtesting | L | Validación formal + backtesting |
| **F7** | UI visual | **App React premium** | L | Web premium sobre la API (local + demo) |
| **F+** | Originación | Reject inference | M | Scorecard de admisión |

Esfuerzo relativo: S < M < L < XL.

---

## F0 — Fundaciones & gobierno
**Objetivo.** El núcleo del que todo cuelga, auditable desde el primer commit.
**SDDs.** 01 core · 02 data · 03 audit+governance · 04 tracking · 05 convenciones+config · 24 testing · 25 packaging/CI. *(El reporte se separó a **SDD-26 `report`** en T2/F1; ver índice.)*
**Entregables.**
- Repo Apache-2.0, `src/` layout, `pyproject.toml` (uv + hatchling, extras declarados).
- `core`: objeto `Study`, config Pydantic v2 (round-trip YAML), registry, orquestación.
- `data`: validación de esquema, definición de target, particiones (Dev/HO/OOT/TTD), missing/special.
- `audit` + `governance`: semilla global, lineage bundle, model card, inventario.
- `tracking` (MLflow local). *(El informe determinístico + capa IA opcional es **SDD-26**, producido en T2/F1, no en F0.)*
- CI (ruff, mypy, pytest), pre-commit, plantillas de issues/PR.
**DoD.** CI verde; un `Study` vacío se crea, serializa y recarga; una corrida trivial emite lineage + model card reproducibles; cobertura base.
**Dependencias.** Ninguna.

## F1 — Scorecard de comportamiento (MVP open-source)
**Objetivo.** Pipeline de scorecard completo, sin reject inference. **Es el activo de marketing.**
**SDDs.** 27 eda · 06 binning · 07 selection · 08 model · 09 scorecard · 10 calibration · 11 performance+stability · 26 report.
**Entregables.**
- EDA de riesgo (SDD-27): tasa de default por período/cohorte, estabilidad temporal (señal de redesarrollo), perfiles univariados.
- Binning OptBinning monótono (WoE), ajuste en Dev → transform al resto.
- Selección: PSI/CSI, IV, ROC/KS/Gini por muestra y período; correlación; descarte por negocio.
- Stepwise (Wald/LR, statsmodels), regla de signos, IV-contribution ≤ 90%.
- Scorecard (offset/PDO, puntos por atributo); calibración de PD.
- Tabla de rendimiento (deciles) + estabilidad del score.
- **Informe HTML/PDF/Word** de la scorecard, con fuente Markdown/Quarto opcional.
**DoD.** Dataset de ejemplo → scorecard reproducible + reporte; tests numéricos de WoE/IV/PSI/escalado contra valores a mano; **release público inicial** en PyPI + GitHub con README, tutorial y ejemplo ejecutable. **Cumplido.**
**Dependencias.** F0.

## F2 — Machine Learning
**Objetivo.** Modelos ML como benchmark de poder predictivo, con explicabilidad.
**SDDs.** 12 ml-models · 13 tuning · 14 explain.
**Entregables.**
- Wrappers SVM, RandomForest, XGBoost, LightGBM, **CatBoost** (extras opcionales), con monotonic constraints donde aplique.
- Optuna (samplers seedeados, search spaces editables).
- SHAP + reason codes; comparativa scorecard vs ML en el reporte.
**DoD.** Mismo pipeline de datos que F1; tuning reproducible (seed); SHAP integrado al reporte; tests de determinismo.
**Dependencias.** F1 (pipeline, binning, model).

## F3 — Provisiones CMF (norma local)
**Objetivo.** Motor de pérdida esperada estandarizada `PE = PI·PDI·Exposición` del Capítulo B-1.
**SDDs.** 15 provisioning-cmf.
**Entregables.**
- Matrices por cartera (comercial individual A1–C6, grupal, consumo 2025, vivienda PVG) como **datos versionados** ([`normativa_cmf_parametros.md`](normativa_cmf_parametros.md)).
- Contingentes B-3 (CCF + override 100% en incumplimiento); sustitución por avales; garantías → PDI.
**DoD.** Cálculo de provisión por cartera reproducible contra casos de ejemplo; **validación humana de las matrices** registrada en governance; tests por cada matriz.
**Dependencias.** F1 (segmentación/PD de entrada). **Riesgo:** los parámetros cambian con la norma → versionar.

> 🔴 **DoD INCUMPLIDO: la validación humana de las matrices SIGUE PENDIENTE.** Los parámetros se transcribieron del compendio **con asistencia de IA y verificación visual**; no son oficiales de la CMF ni están validados por ella (así está confesado en el README y en la landing). **Un gerente de riesgo pregunta por su procedencia en los primeros cinco minutos.** Para cartera de consumo se usa **una sola** matriz (`consumer_standard_v2025`): validarla a mano, celda por celda, **no lo puede hacer un agente**.
>
> **Prioridad fijada el 2026-07-21 (bloque B5):** se hace sí o sí, pero no encabeza la cola — CMF es Chile y el alcance del proyecto es LATAM. Detonante natural: el primer compromiso concreto en el mercado chileno. Mientras tanto F3 se comunica como experimental **sin excepción**.

## F4 — IFRS 9 / ECL
**Objetivo.** ECL de 3 etapas como motor independiente; la orquestación configurable vive en una
capa separada y sólo representa la regla B-1 al comparar estándar CMF con método interno.
**SDDs.** 16 provisioning-ifrs9 · 17 provisioning-orchestration.
**Entregables.**
- PD (12m/lifetime, PIT/TTC Vasicek), LGD (beta/fractional/workout), EAD/CCF.
- Staging (SICR, Stage 1/2/3, backstops 30/90 dpd, umbrales parametrizables).
- Motor ECL con descuento a EIR, multi-escenario ponderado.
- Orquestación: `provisioning` compara **dos fuentes configurables** y aplica la regla declarada.
**DoD.** ECL reproducible sobre dataset de ejemplo; term-structure conectada (interfaz a F5); tests de fórmula (Vasicek, ECL marginal) contra valores canónicos.
**Dependencias.** F4↔F5 (lifetime usa survival/markov; se especifica con interfaz abstracta y se conecta al cerrar F5).

> ⚠️ **CORRECCIÓN NORMATIVA (2026-07-14).** Este roadmap decía *"capa que toma el máximo vs piso CMF"* y *"`provisioning` compara CMF vs IFRS 9 y aplica el máximo"*. **Ese encuadre era falso.** El Cap. A-2 del Compendio **excluye** el deterioro de NIIF 9 sobre las colocaciones, y la regla del máximo del Cap. B-1 (Circular N° 2.346) es entre el **método estándar y el método interno del banco**, por institución. Ver `ESPECIFICACIONES.md` §5.4 y el SDD-17 §3.
>
> **Para el mercado chileno, el ECL de IFRS 9 no es el operando del máximo.** F4 sigue siendo válido para quien sí aplica NIIF 9 completa (filiales que reportan a matriz extranjera, entidades no bancarias, instrumentos distintos de colocaciones).

## F8 — El método interno y la ruta hasta el usuario (post-1.0)
**Objetivo.** Que un gerente de riesgo pueda **ver** la provisión que la norma le obliga a constituir.
**SDD.** 28 provisiones-end-to-end.
**Entregables.**
- ✅ `provisioning/internal`: el **método interno** del B-1 (`Exposición · PD · LGD` por grupo homogéneo). La PD sale del scorecard → **el modelo del banco entra en la provisión reportada**.
- ✅ Orquestador con fuentes configurables + `rule="use_internal"`.
- ✅ Dataset `provisiones_consumo` y capítulos condicionales del informe.
- ✅ **La ruta hasta el usuario**: preset, serializer, pantalla y capítulo del informe F3, integrada y
  recapturada en la demo multi-dominio.
**DoD.** La cadena corre de punta a punta desde la UI y el informe trae la cifra; validación **humana** de la matriz de consumo contra el compendio (gate G0).

## F5 — Forward-looking & dinámica
**Objetivo.** Lifetime PD, proyección macro y escenarios.
**SDDs.** 18 survival · 19 markov · 20 forward-macro · 21 stress.
**Entregables.**
- Survival (KM, Cox, AFT, discrete-time hazard) → lifetime PD; reusa stack de regresión.
- Markov (cohort/duration/generador, embedding) → term structure.
- Macro ARIMA/VAR + satellite models (Wilson logit) + escenarios ponderados (≥3).
- Stress testing (escenarios severos, sensibilidad).
**DoD.** Curvas lifetime PD reproducibles por ambas rutas (survival y matriz); consistencia PIT en la cadena; tests numéricos.
**Dependencias.** F1 (regresión). Cierra el lifetime de F4.

## F6 — Validación avanzada
**Objetivo.** Validación formal y backtesting integrados. (El módulo `stress/` se construye en F5; aquí se valida y se hace backtesting.)
**SDDs.** 22 validation.
**Entregables.** Discriminación (ROC/AUC, Gini, KS), calibración (Hosmer-Lemeshow, binomial, traffic-light, Brier), estabilidad (PSI), backtesting realizado-vs-estimado (t-test ECB).
**DoD.** Suite de validación ejecutable sobre cualquier modelo del repo; informes HTML/PDF/Word de validación.
**Dependencias.** F1–F5.

## F7 — UI visual
> **Rumbo actualizado (2026-07-04): UI = app React/Vite premium, NO Streamlit.** El contrato de
> `design/23-ui.md` se implementó sobre React/FastAPI; sus referencias históricas a Streamlit no
> describen el producto actual.

**Objetivo.** Web premium sobre la API que construye y visualiza el `Study` (editor del config Pydantic), para dos públicos: analistas técnicos (MVP/benchmark rápido) y gerentes de riesgo no-técnicos (demo de venta).
**SDDs.** 23 ui *(contrato evolucionado e implementado sobre React/FastAPI)*.
**Stack.** React + Vite + Tailwind + shadcn/ui + charts premium; backend **FastAPI**. No recalcula
outputs contractuales, regulatorios ni de modelado; `reliability.py` es la única derivación
determinista de presentación (read-only, trazada y fuera de modelo/ModelCard/informe).
**Dos modos de despliegue.**
- **Local (analista):** `pip install nikodym[ui]` debe traer el React buildeado y levantar FastAPI
  en loopback; los datos no salen de su máquina. 🔴 **PROMESA INCUMPLIDA EN `1.5.0`** — lo publicado
  no trae launcher/assets y el extra no cierra los presets visibles. En `main`, B2.1 ya versiona y
  gatea los assets y B2.2 añade el launcher `nikodym-ui` con su runtime y seguridad; falta que B2.3
  complete `[ui]`. Hasta completar B2.3–B2.5, publicar y repetir el recorrido desde PyPI, F7 no
  está entregado.
- **Hosteada (comercial):** `nikodym.cl/demo`, dataset **sintético** precargado, flujo guiado "arma tu modelito en pocos pasos" + CTA de lead comercial.
**DoD.** Un modelo F1 completo construible 100 % desde la UI: igualdad estructural +
`config_hash` antes de ejecutar y, sobre el mismo contenido, `data_hash` + resultados canónicos
después; informe HTML y look&feel premium aprobados. El cierre de producto exige el recorrido desde
el artefacto publicado en PyPI.
**Dependencias.** Todo el core (motor V1 ✅ completo 2026-07-04).

## F+ — Originación & reject inference (insertable)
**Objetivo.** Scorecard de admisión cuando haya caso de uso.
**Entregables.** Muestra TTD (through-the-door), reject inference (parcelling/fuzzy/reweighting) validado por outcomes.
**Cuándo.** Insertable tras F1, cuando un cliente lo requiera.

---

## Estrategia de release (open-source)
- `1.5.0` es la versión del código/tag y la publicada en PyPI; el próximo release será `1.6.0` (bump
  con OK específico de Cami). El pipeline F1 conserva la garantía SemVer 1.x.
- **`1.5.0` = cierre de B1** (rótulo ECL + deuda cosmética) — **publicado el 2026-07-22**.
  **`1.6.0` = cierre de B2** (UI instalable).
  Se publican por separado: atar el release de higiene a la distribución de la UI retrasa correcciones
  ya listas sin beneficio para nadie.
- La librería se publica **completa y gratuita** bajo Apache-2.0. Ninguna capacidad se retiene del
  paquete público por motivos comerciales.
- Releases incrementales con changelog, docs MkDocs, dataset/tutorial reproducible y smoke clean-room.
- Cada tag y publicación PyPI requiere OK específico de Cami; push/deploy ordinarios no sustituyen ese gate.

## Puentes de sesión
- Entre tandas/fases: `cierre-trabajo` → `HANDOFF.md` → `inicio-trabajo` en sesión fresca.
- El HANDOFF resume estado, decisiones y siguiente paso. Warm start desde el HANDOFF, no re-explorar todo.
