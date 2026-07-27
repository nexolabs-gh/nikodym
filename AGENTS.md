# AGENTS.md — Nikodym RiskLib

> Contexto de trabajo del proyecto (fuente común para Claude Code y Codex). `CLAUDE.md` importa este archivo.
> Detalle completo en [`docs/ESPECIFICACIONES.md`](docs/ESPECIFICACIONES.md), [`docs/ROADMAP.md`](docs/ROADMAP.md) y [`docs/design/00-INDICE.md`](docs/design/00-INDICE.md).

## Qué es
Librería Python **open-source (Apache-2.0)** de riesgo de crédito **integral**: scoring/scorecards, ML, provisiones **CMF (Chile)** e **IFRS 9/ECL**, forward-looking y stress testing. Paquete: `nikodym`. Marca compartida con la **consultora Nikodym** (la librería es su escaparate de reputación → calidad ejemplar es requisito, no extra).

## Idioma
Todo en **español** (docs, comentarios, comunicación). Términos técnicos en su forma original.

## Estado del proyecto (2026-07-27)

**`main` = `cf217a2`, CI verde 16/16, sin publicar** (PyPI sigue en `1.6.0`). La sesión del
2026-07-27 entregó el **núcleo técnico de la paridad UI↔código en provisiones**: el formulario del UI
instalable pasó de 7 secciones a **12** —entran `survival` y las cuatro de `provisioning*`—, más tres
gates que antes no existían (staleness del fixture del schema, cobertura del vocabulario de widgets,
y el estado que deja una corrida fallida). **No cierra ningún nodo de B2**, cuyo criterio exige PyPI
más un tercero sin checkout; es trabajo del requisito 1 de la visión, que atraviesa el bloque.

Probar ese formulario recién abierto destapó un defecto **del núcleo** que 4.451 tests verdes no
veían: un config inejecutable no dejaba rastro alguno y la UI respondía un HTTP 500, pese a que el
motor produce ahí un diagnóstico exacto. Cerrado con
[`_ENMIENDA-RUN-ERROR-RESOLUCION.md`](design/_ENMIENDA-RUN-ERROR-RESOLUCION.md) (D-ERR-8…D-ERR-11).
Detalle operativo y las cuatro reglas para tocar el formulario: `CLAUDE.md` §«Lo último».

## Estado publicado (2026-07-26)
PyPI publica **`1.6.0`** (tag `v1.6.0` sobre `86e121b`, 2026-07-26, con OK explícito de Cami); el
tag `v1.5.0` apunta al cierre del bloque B1 (el SHA vigente de `main` queda en `HANDOFF.md`). El
paquete se anuncia como **`Development Status :: 4 - Beta`**: el pipeline F1 es estable bajo SemVer
1.x, pero las provisiones siguen experimentales, así que «Production/Stable» sería sobrepromesa.

**`1.6.0` corrige una cifra y rompe dos configuraciones de fábrica**, y eso hay que tenerlo presente
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
- Suite: **>3.900 tests**, `mypy --strict`, cobertura 100 % en código regulatorio, CI matriz verde
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
  `web/src/lib/public-copy.test.ts` y `tests/unit/test_public_copy.py`; el `README.md` queda fuera
  hasta que Cami decida (`HANDOFF.md` P1).
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
