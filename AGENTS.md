# AGENTS.md — Nikodym RiskLib

> Contexto de trabajo del proyecto (fuente común para Claude Code y Codex). `CLAUDE.md` importa este archivo.
> Detalle completo en [`docs/ESPECIFICACIONES.md`](docs/ESPECIFICACIONES.md), [`docs/ROADMAP.md`](docs/ROADMAP.md) y [`docs/design/00-INDICE.md`](docs/design/00-INDICE.md).

## Qué es
Librería Python **open-source (Apache-2.0)** de riesgo de crédito **integral**: scoring/scorecards, ML, provisiones **CMF (Chile)** e **IFRS 9/ECL**, forward-looking y stress testing. Paquete: `nikodym`. Marca compartida con la **consultora Nikodym** (la librería es su escaparate de reputación → calidad ejemplar es requisito, no extra).

## Idioma
Todo en **español** (docs, comentarios, comunicación). Términos técnicos en su forma original.

## Estado del proyecto (2026-07-28, noche)

**`main` = `cd75aa9`, CI verde 16/16 (conteo por `gh`), `1.9.0` PUBLICADO en PyPI** (tag `v1.9.0`,
con OK explícito de Cami). Suite 4522 passed / 6 skipped; vitest 331/331.

🔴 **PRIORIDAD ABSOLUTA hasta el 2026-08-02: el webinar EN VIVO de Cami** sobre regresión logística y
scorecard, con **demo real no precargada**, dataset **HMEQ**, en código **y** en UI, ante audiencia
mixta con decisores. El plan de 5 días, el arco narrativo y los cinco riesgos conocidos están en
`HANDOFF.md`. **B2.4, la recaptura de la demo, vitest→jsdom y la pata de release de B2.5 quedan
CONGELADOS hasta el 2026-08-03**: no acercan el webinar.

**La auditoría adversarial previa al release lo FRENÓ y encontró dos defectos que 4.522 tests y CI
16/16 no veían** — segundo release consecutivo en que ocurre. Ambos corregidos antes de publicar:

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
**Todo ello congelado hasta el 2026-08-03 por el webinar.**

⚠️ **Tres gates son más débiles de lo que su nombre promete** (auditoría del 2026-07-28, sin
arreglar): `test_column_roles.py` mide una lista hardcodeada y no el footprint real de `column_role`
—verificado inyectando un rol en `markov`: queda verde—; el gate del extra `[ui]` sólo itera 5 de 12
extras; y `schema.test.ts` deriva sus casos de lo que vigila, así que **`model` se puede borrar del
formulario con todo el CI verde**. Detalle en `HANDOFF.md` P5.

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

## Estado publicado (2026-07-28)
PyPI publica **`1.9.0`** (tag `v1.9.0` sobre `cd75aa9`, 2026-07-28, con OK explícito de Cami); el
tag `v1.5.0` apunta al cierre del bloque B1 (el SHA vigente de `main` queda en `HANDOFF.md`). El
paquete se anuncia como **`Development Status :: 4 - Beta`**: el pipeline F1 es estable bajo SemVer
1.x, pero las provisiones siguen experimentales, así que «Production/Stable» sería sobrepromesa.

⚠️ **Al verificar un release recién subido, `pip install` SIN `--no-cache-dir` puede traerte el
release ANTERIOR** con el nuevo ya en el índice, y parecer verde. Pasó con `1.9.0`: la primera
instalación limpia trajo `1.8.0` mientras `pip index versions` decía `LATEST: 1.9.0`.

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
- **Stress, markov, forward, survival**: implementados y cubiertos por tests, pero hoy se usan
  escribiendo el config en Python (sin preset/UI propios) → **experimentales**.
- **UI React** en `web/` + **demo multi-dominio** (F1 scorecard · F3 CMF · F4 IFRS 9) deployada en
  **demo.nikodym.cl** (fixtures de corridas reales, sin cálculo en el navegador).
- **Informe** HTML/PDF/Word con estilo editorial, contexto poblacional, validación formal y config
  efectiva por dominio; F3 fue recapturado desde una corrida real durante esta consolidación.
- Suite: **>4.500 tests** (4.515 al 2026-07-28), `mypy --strict`, cobertura 100 % en código regulatorio, CI matriz verde
  (macOS/Windows/Linux × Python 3.11–3.13).

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
- **Calidad del código (cuando se programe)**: `mypy --strict`, ruff, tests canónicos numéricos con golden values, 100% de cobertura en código regulatorio (`core/exceptions`, `core/seeding`, `provisioning/cmf`, `provisioning/ifrs9`), `filterwarnings=["error"]`. SDD-24/25 los especifican.
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
