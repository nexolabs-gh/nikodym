# Índice maestro de diseño — Nikodym RiskLib

| | |
|---|---|
| **Documento** | Índice de Documentos de Diseño (SDD) |
| **Versión** | 1.2 (índice histórico consolidado) |
| **Fecha** | 2026-07-18 |
| **Base** | [`docs/ESPECIFICACIONES.md`](../ESPECIFICACIONES.md) v1.1 · [`docs/ROADMAP.md`](../ROADMAP.md) |

> **Lectura actual:** este índice confirma qué SDD están implementados, pero no es un backlog. Para
> `estable`/`experimental`, gates pendientes y prioridad vigente manda
> [`ROADMAP.md`](../ROADMAP.md).

> **Tanda 1 Rev (2026-06-24):** los 7 SDD de Fundación (01-05, 24, 25) se revisaron de forma adversarial e integraron sus correcciones (cabecera "rev. Tanda 1 Rev" en cada uno). Cambios de alcance: **+SDD-27 `eda`** (de 26 a **27 SDD**); **D2** revierte el `data_hash` a hash de contenido lógico (SDD-02). Detalle de hallazgos y decisiones en el cierre de la sesión.
>
> **Hito 0 — Contratos transversales (2026-06-24):** antes de codificar F0 se estabilizó la *extensibilidad* de los 4 contratos que cruzan todas las capas (orquestación DAG vía `requires`/`provides`; resultados/metrics/overlay con puerta de extensión estructurada; frontera datos transversal-vs-longitudinal; owner del ensamblado de corrida). Decisiones en [`_CONTRATOS-TRANSVERSALES.md`](_CONTRATOS-TRANSVERSALES.md) (CT-1…CT-4), propagadas a SDD-01/02/03 (cabecera "rev. Hito 0"). Estrategia de construcción confirmada: **mixto-troncal-más-incremental** (spike troncal acotado → código F0 → incremental por capa con diseño *just-in-time*).

Este índice lista los **28 Documentos de Diseño (SDD)** que guiaron la construcción de Nikodym
RiskLib. Cada SDD sigue [`_PLANTILLA-SDD.md`](_PLANTILLA-SDD.md) y cubre un módulo del árbol
`src/nikodym/`; un cambio contractual nuevo requiere un SDD nuevo o una revisión explícita.

## Cómo se produce (proceso)
1. **Andamiaje** (hecho): esta plantilla + este índice + el roadmap.
2. **Tanda 0 — Verificación**: antes de producir nada nuevo, se re-verifica que **todo lo ya hecho** (ESPECIFICACIONES, normativa CMF, índice, roadmap, plantilla) esté correcto, con **doble check** de cada dato/tabla/decisión contra su fuente oficial. Se corrige lo que falle. Recién entonces se avanza.
3. **Producción por tandas**: cada tanda agrupa SDDs de una capa/fase y se produce con **fan-out de agentes** (un agente especificador por SDD, siguiendo la plantilla), **integrados y revisados por DanIA**.
4. **Sesiones frescas con HANDOFF** entre tandas (evita degradación de contexto). El `HANDOFF.md` es el puente.
5. Un SDD pasa de *Borrador* → *En revisión* → **Aprobado** solo tras revisión de integración.

> **Regla dura (proyecto delicado):** ningún dato externo se da por válido sin **doble verificación trazada** contra la fuente oficial. Será usado por instituciones financieras.

## Estado global

| SDD | Módulo | Dominio | Fase | Tanda | Depende de | Estado |
|---|---|---|---|---|---|---|
| **01** | `core` | Fundación | F0 | T1 | — | ✅ Implementado |
| **02** | `data` | Fundación | F0 | T1 | 01 | ✅ Implementado |
| **03** | `audit` + `governance` | Fundación | F0 | T1 | 01 | ✅ Implementado |
| **04** | `tracking` (MLflow) | Fundación | F0 | T1 | 01, 03 | ✅ Implementado |
| **05** | Convenciones API + schema de config global | Fundación | F0 | T1 | 01 | ✅ Implementado |
| **24** | Estrategia de testing | Ingeniería | F0 | T1 | 01, 05 | ✅ Implementado |
| **25** | Packaging + CI (uv, hatchling, extras) | Ingeniería | F0 | T1 | — | ✅ Contrato B2.0 aprobado · fundación implementada; gates de distribución pendientes |
| **06** | `binning` | Scoring | F1 | T2 | 02, 05 | ✅ Implementado · estable F1 |
| **07** | `selection` | Scoring | F1 | T2 | 06 | ✅ Implementado · estable F1 |
| **08** | `model` (logística + stepwise) | Scoring | F1 | T2 | 07 | ✅ Implementado · estable F1 |
| **09** | `scorecard` | Scoring | F1 | T2 | 08 | ✅ Implementado · estable F1 |
| **10** | `calibration` | Scoring | F1 | T2 | 08 | ✅ Implementado · estable F1 |
| **11** | `performance` + `stability` | Scoring | F1 | T2 | 09, 10 | ✅ Implementado · estable F1 |
| **12** | `ml` (SVM/RF/XGB/LGBM/CatBoost) | ML | F2 | T3 | 06, 08 | ✅ Implementado · experimental |
| **13** | `tuning` (Optuna) | ML | F2 | T3 | 12 | ✅ Implementado · experimental |
| **14** | `explain` (SHAP + reason codes) | ML | F2 | T3 | 12 | ✅ Implementado · experimental |
| **15** | `provisioning/cmf` (B-1, matrices, B-3, garantías) | Provisiones | F3 | T4 | 08, 02 | ✅ Implementado · experimental |
| **16** | `provisioning/ifrs9` (PD/LGD/EAD, staging, ECL) | Provisiones | F4 | T4 | 10, 18 | ✅ Implementado · experimental |
| **17** | `provisioning` (orquestación / regla del máximo) | Provisiones | F4 | T4 | 15, 16, 28 | ✅ Implementado · experimental |
| **18** | `survival` (KM/Cox/AFT/discrete-time) | Forward | F5 | T5 | 08 | ✅ Implementado · experimental |
| **19** | `markov` (transición, term structure) | Forward | F5 | T5 | 02 | ✅ Implementado · experimental |
| **20** | `forward` (macro ARIMA/VAR, satellite, escenarios) | Forward | F5 | T5 | 18, 19 | ✅ Implementado · experimental |
| **21** | `stress` (stress testing, sensibilidad) | Forward | F5 | T5 | 20 | ✅ Implementado · experimental |
| **22** | `validation` | Validación | F6 | T6 | 11, 16 | ✅ Implementado · experimental |
| **23** | `ui` (React/Vite + FastAPI, editor de config) | Producto | F7 | T6 | 05, 01, 03, 26, todos | ✅ Backend/front implementados · distribución en curso: B2.1 y B2.2 cerrados (assets, launcher, runtime y seguridad); falta B2.3–B2.5 |
| **26** | `report` (HTML/PDF/Word, fuente editable, capa IA opcional) | Reporte | F1 | T2 | 01 | ✅ Implementado |
| **27** | `eda` (tasa de default por período, estabilidad temporal) | Scoring | F1 | T2 | 02 | ✅ Implementado · estable F1 |
| **28** | `provisioning/internal` + regla del máximo (dataset → preset → UI → informe) | Producto | F8 | T7 | 08, 10, 15, 17, 23, 26 | ✅ Implementado · experimental |

**28 SDD · 8 tandas (T0–T7; T0 = verificación, sin SDD nuevo).** La madurez pública y la garantía
SemVer se declaran únicamente en `ROADMAP.md`.

> **SDD-28** (post-1.0) hace dos cosas. **(1)** Construye el motor que faltaba: el **método interno** (`PD × LGD × EAD` por grupo homogéneo), que es el que el Capítulo B-1 §3 describe textualmente y que el pipeline de scorecard ya alimenta. **(2)** Le abre la ruta hasta el usuario —dataset, preset, pantalla, capítulo— porque *una feature sin preset, sin pantalla y sin capítulo no existe*, y este proyecto ya lo pagó dos veces.
>
> Su **v1 fue descartada**: diseñaba la demo alrededor de `max(CMF, IFRS 9)` presentado como "el piso prudencial de la CMF", una regla que **no existe** (ver la corrección en SDD-17 §3 y ESPEC §5.4). La regla real del B-1 es `max(estándar, interno)`, a nivel de entidad — y es mejor noticia, porque es citable **y** porque hace que el scorecard entre en el número final.

> **SDD-27 `eda`** se creó en **Tanda 1 Rev** (decisión D1): el paquete `eda/` figuraba en el árbol de paquetes (ESPEC §6.3) y en el config (SDD-05 §5.1) pero ningún SDD lo cubría — quedaba huérfano. Es el **paso 1 del pipeline de scorecard** (pre-binning, F1/T2), depende de 02 (`data`). **Aguas abajo** 06 (binning), 11 (performance+stability, deslindado) y 26 (report) **consumen sus diagnósticos** (tasa de default por período, figuras), pero NO es una dependencia dura de build de esos SDD — por eso no aparece en su columna "Depende de" (corren sobre el frame de `data`); el orden T2 garantiza que `eda` se diseñe primero.
>
> **Diseño ≠ implementación ≠ distribución (B2.0 aprobado, 2026-07-23).** SDD-23 y SDD-25
> aprobaron contractualmente la distribución sobre la base
> `dd89f7d35cefb0aebb4ec2055c4ca81c171dd59e`, tras revisión adversarial sin P0/P1/P2 y auditoría
> API aprobada. El checkout contiene backend FastAPI y frontend React/Vite; los
> artefactos oficiales `1.5.0` instalan el backend pero no incluyen launcher, `__main__`,
> `static/index.html` ni assets JS/CSS. El contrato aprobado B2 separa assets/supply-chain,
> launcher/seguridad local, extra/uploads/presets, clean-room y release; exige procedencia Vite
> autoritativa por output/hash con textos de licencia/atribución íntegros y trazados (pnpm full/prod
> solo reconcilia), cierre Python permisivo base + `[all]` con `[pdf]` separado, veto trazado de
> fixtures demo, upload raw agnóstico y preflight/indexación en la extensión pública de
> `nikodym.run`, token efímero no cacheable y gates F1/F3/F4. F7 permanece no entregado hasta
> publicar y repetir el recorrido desde PyPI.
>
> **Avance de la distribución (2026-07-24).** **B2.1 CERRADO** (assets versionados, supply-chain y
> licencias) y **B2.2 CERRADO** (launcher `nikodym-ui`, runtime y seguridad local), este último bajo
> la enmienda [`_ENMIENDA-B2.2.md`](_ENMIENDA-B2.2.md), aprobada por Cami, con dos rondas de revisión
> adversarial y los 16 jobs del CI verdes. Sigue **B2.3** (`[ui]`, uploads y presets), que exige su
> propia enmienda antes de programarse. Aprobación de diseño no equivale a distribución, y
> distribución en `main` no equivale a producto publicado: `1.5.0` sigue sin launcher ni assets.
>
> **Taxonomía de marcas separada (2026-07-24).** `FALTA-DATO` cubría tres cosas distintas —una
> brecha del motor, un input que aporta la institución y un TODO de ingeniería—. La enmienda
> [`_ENMIENDA-TAXONOMIA-MARCAS.md`](_ENMIENDA-TAXONOMIA-MARCAS.md), aprobada por Cami y ejecutada el
> mismo día, deja `FALTA-DATO` sólo para las brechas del motor (9 códigos + 2 `pending_items` CMF),
> crea **`DATO-INSTITUCIONAL`** para los 34 que declara la institución, saca del contrato 7 TODO de
> ingeniería y cierra 4 ítems que ya estaban resueltos. Afecta a los SDD 12, 13, 14, 16, 17, 18,
> 19, 20, 21, 22 y 23; el contrato compartido vive en `nikodym/core/markers.py`.
>
> **Corrección del 2026-07-25 (revisión adversarial posterior a la ejecución).** `FWD-8` había
> quedado clasificado como institucional siendo una brecha del motor —su propio mensaje decía «en
> esta versión»—, así que vuelve a `FALTA-DATO` y el reparto pasa a 9/34. El blocker de backtesting
> de SDD-22 marcaba institucionales cinco motivos distintos, uno de los cuales es la ausencia de
> columnas que produce el propio motor IFRS 9: ese caso pasa a `FALTA-DATO`. Y `STR-8`, que el motor
> emitía sin ficha en ningún SDD, quedó declarado en SDD-21.
>
> **Horizonte 12m de IFRS 9 — enmienda PROPUESTA, sin OK todavía (2026-07-25).** Verificar que un
> código citado en un SDD exista en `src/` destapó algo mayor que una cita huérfana:
> `DATO-INSTITUCIONAL-IFRS-2` nunca se emitió —`git log -S` confirma que jamás estuvo en el motor—,
> y detrás de la promesa hay una **degradación silenciosa** real. Cuando `horizon_12m_periods`
> alcanza `min(T_max, max_lifetime_periods)` la máscara del horizonte queda toda verdadera: la ECL a
> 12 meses iguala a la lifetime y un Stage 1 provisiona lo mismo que un Stage 2 —la distinción que
> IFRS 9 existe para hacer— sin warning ni excepción. El
> texto de SDD-16 ya se corrigió para que describa el comportamiento real (§8, §9 y la ficha), y el
> diseño del arreglo vive en [`_ENMIENDA-IFRS9-HORIZONTE.md`](_ENMIENDA-IFRS9-HORIZONTE.md):
> **APROBADA el 2026-07-26; ninguna línea de motor escrita todavía.** Deja fijada además una
> distinción que faltaba: de los seis códigos IFRS sólo IFRS-4 e IFRS-6 se emiten en runtime; los
> otros cuatro son requisitos de entrada documentados.
>
> ⚠️ **Su título apunta al síntoma menor.** Medido el 2026-07-26 sobre el motor: el horizonte mal
> declarado **no cambia la ECL total** —sólo el corte de stage 1—, mientras que la unidad de
> `time_value` la mueve un **−50,8 %** (misma curva declarada en meses en vez de años). `ifrs9`
> usa `time_value` como exponente de `(1+EIR)^(-τ)` asumiendo años, y la term-structure no
> transportaba su unidad. **D-HOR-0 resuelto por Cami: la term-structure la transporta**; si no la
> declara, se asume años **con marca declarada** `DATO-INSTITUCIONAL` —aditivo, no rompe a nadie— y
> `fail_on_falta_dato` la gobierna. Descuento y horizonte entran juntos.
>
> **El fallo de una corrida deja rastro legible (2026-07-25, APROBADA y ejecutada).**
> [`_ENMIENDA-RUN-ERROR.md`](_ENMIENDA-RUN-ERROR.md), sobre SDD-01 (§4 `RunContext`, §7.3) y SDD-23
> §8. Por el camino que la propia documentación recomienda, una corrida que fallaba no dejaba ni el
> mensaje ni el paso: el error se emitía a un sink nulo y se perdía. Extensión **aditiva** de
> `RunContext`, así que no toca la garantía SemVer 1.x de F1, y **no** altera D-UI-2 (`nikodym.run`
> devuelve el `Study` parcial; `Study.run()` sigue siendo *fail-loud*).
>
> **…y el fallo de RESOLUCIÓN también (2026-07-27, APROBADA e implementada).**
> [`_ENMIENDA-RUN-ERROR-RESOLUCION.md`](_ENMIENDA-RUN-ERROR-RESOLUCION.md), D-ERR-8…D-ERR-11,
> continúa la numeración de la anterior. **La enmienda de arriba resolvió la mitad del problema que
> describía:** su manejo de fallo vive dentro del `try` que envuelve el bucle de pasos, así que
> cubría los fallos de *ejecución* y dejaba fuera los de *resolución* del pipeline. Medido por el
> camino del usuario de la UI el 2026-07-27 —encender `provisioning_ifrs9` sin `survival`—: el motor
> emitía un `ConfigError` exacto que se perdía entero, `nikodym.run` devolvía un `Study` en
> `"created"` con `run_id` y `error` en `None` —ni `"done"` ni `"failed"`— y la UI, incapaz de
> persistir una corrida sin `run_id`, respondía un **HTTP 500 opaco**. `run_id` pasa a asignarse
> antes de resolver, y el registro del fallo vive en un helper único para que las dos fases no
> puedan volver a divergir. Cambia comportamiento observable: ver su §4.
>
> **…y la ejecutabilidad se sabe MIENTRAS se edita (2026-07-27, APROBADA e implementada).**
> [`_ENMIENDA-VALIDACION-PIPELINE.md`](_ENMIENDA-VALIDACION-PIPELINE.md), D-PIPE-1…D-PIPE-6, cierra
> el candidato que la anterior dejó anotado sin decidir en su §3. `Study.check_pipeline()` resuelve
> y valida **sin ejecutar nada** —medido: función del config, sin dataset, sin disco y ≤0,1 ms con
> los dominios importados—, `nikodym.check_pipeline(config)` lo envuelve capturando (misma relación
> que `run` con `Study.run`, D-UI-2) y `/api/validate` lo consume en un campo **aditivo**
> `pipeline`. La capacidad vive en el núcleo y no en la UI a propósito: ponerla sólo en el
> formulario dejaba al camino por código descubriendo el problema al ejecutar, que es media paridad.
> **`valid` NO cambia de significado** (D-PIPE-1) y el aviso **no bloquea** Ejecutar (D-PIPE-4,
> decisión de Cami): desde D-ERR-8 el intento se registra con su diagnóstico, y bloquear se lo
> quitaría al usuario. El prefijo `D-VAL-` estaba tomado por SDD-22, de ahí `D-PIPE-`.
>
> **…y la identidad del config deja de depender de qué importó el proceso (2026-07-27, APROBADA e
> implementada).** [`_ENMIENDA-CONFIG-HASH-IMPORTS.md`](_ENMIENDA-CONFIG-HASH-IMPORTS.md),
> D-HASH-1…D-HASH-8, enmienda a SDD-01 §5. El **mismo** config producía **dos `config_hash`
> distintos** según si la capa de dominio estaba importada: una sección opaca se canonicalizaba sin
> normalizar, y coaccionar materializa los defaults que el dict no traía. `config_hash` coacciona
> ahora antes de canonicalizar (D-HASH-1) — la identidad es la del config **que se ejecutaría**, la
> misma semántica que el lineage adoptó al arreglar su P0. El *blob* opaco del núcleo liviano queda
> intacto (D-HASH-2): la coacción vive en el hash, no en `model_validate`.
>
> Tres cosas que conviene no re-aprender. **La premisa con que se priorizó era falsa** —«afecta al
> usuario mientras trabaja»—: medido, por la UI **no se alcanza**, porque el formulario no valida
> hasta recibir el schema y `/api/schema` importa los dominios; a quien afecta es al cliente HTTP
> directo y al uso por código con `dict`. **El test de regresión exige subproceso**: dentro de la
> suite las capas siempre están importadas, así que un montaje natural nunca vive en el lado opaco
> de la brecha (se verificó que falla sin el arreglo). Y **D-HASH-8 nació al programar**: la primera
> implementación volvía `config_hash` fallable, lo que habría convertido en 500 el 200 incondicional
> de `/api/validate`.
>
> **…y el config y el dataset propio se comparan ANTES de correr (2026-07-28, APROBADA e
> implementada).** [`_ENMIENDA-PREFLIGHT-DATASET.md`](_ENMIENDA-PREFLIGHT-DATASET.md),
> D-PRE-1…D-PRE-8, enmienda a SDD-23 §7 y al alcance de `check_pipeline`, que responde «¿es
> ejecutable?» **sin leer el dataset** y por eso no ve esta familia de desajustes. Medido desde PyPI
> en un venv limpio: un CSV con nombres de columna propios exige **6 ediciones del preset F1 en 6
> lugares distintos**, y el motor las revela **de a una** —cada corrida fallida destapa la
> siguiente—. Los mensajes del motor son buenos; lo que falta es verlos todos juntos. La decisión
> que sostiene el diseño es D-PRE-3: un campo que nombra columna puede referirse a una columna **de
> entrada** o a una **derivada** que produce el propio pipeline (`score_column`, `pd_column`,
> `partition_column`), y sólo las primeras se exigen — de los 26 campos del camino F1 que nombran
> columnas, sólo 6 son de entrada. Alcance explícito: F1; los demás dominios quedan fuera **a
> propósito** y el test de cobertura lo declara (D-PRE-4).
>
> **…y el config que se contradice a sí mismo se avisa ANTES, no en el paso 8 (2026-07-29, APROBADA
> e implementada).** [`_ENMIENDA-INVARIANTES-PREVIAS.md`](_ENMIENDA-INVARIANTES-PREVIAS.md),
> D-INV-1…D-INV-9, enmienda a `_ENMIENDA-PREFLIGHT-DATASET.md` y a SDD-23 §4. Medido con HMEQ
> durante el ensayo del webinar: partición aleatoria + `stability.temporal_axis` en su default
> `"period"` deja a `check_dataset` en `compatible=True, mismatches=0` **y** a `check_pipeline` en
> `executable=True`, y la corrida muere a los 4,4 s en el paso **8 de 10**. Es la familia de D-PRE-9
> —«todo bien» sobre lo que no se miró— por una vía nueva: no hay sección opaca ni columna que
> falte, sino una **invariante interna** que ninguna superficie comprueba. **Y no era sólo
> `stability`:** el censo halló 13 candidatas y **7 se confirmaron en vivo**, todas con las dos
> superficies en verde. La decisión que sostiene el diseño es D-INV-1: la invariante la declara el
> dominio que la impone (`requisitos_incumplidos`), no un registro central — mismo criterio que
> `column_role`. Se consume por `check_dataset`, que ya informa sin bloquear y ya llega hasta el
> salto al campo (D-INV-2); **`check_pipeline` no se toca** y sigue siendo lo único que gobierna el
> botón (D-INV-3). Entran 5 invariantes; **A3 y C2 quedan fuera con su razón medida** (D-INV-8):
> `stratify_by` apunta a una columna **derivada** en el uso canónico y comprobarla daría falsos
> positivos, y `required_sections` es una invariante **entre** secciones, que el protocolo por
> sección no puede expresar sin el acoplamiento que D-INV-1 evita.
>
> **…y se puede entrar por la mitad: la puerta de artefactos (2026-07-30, APROBADA; implementada y
> cerrada el 2026-07-31 en `1a7eb43`).**
> [`_ENMIENDA-PUERTA-ARTEFACTOS.md`](_ENMIENDA-PUERTA-ARTEFACTOS.md), D-ART-1…D-ART-12, enmienda a
> SDD-01 §4/§6/§7 y SDD-05, y amplía el alcance de `_ENMIENDA-VALIDACION-PIPELINE.md`. Es el nodo
> **F1.1** del roadmap y el de mayor apalancamiento: desbloquea T7 (validar un modelo que ya
> existe), T3 (LGD) y T4 (EAD). **La capacidad quedó entregada y medida**: sembrar el
> `ArtifactStore` con los cuatro artefactos de `data` deja el pipeline F1 ejecutable en 9 pasos sin
> la sección `data`, porque `_validate_pipeline` siembra `disponibles` con el store
> (`core/study.py:510`) y `ArtifactStore.set` es público. La implementación añadió la **superficie**
> `artifacts=` a `nikodym.run`/`check_pipeline`, el lineage y la guía pública, sin abrir
> deserialización por UI/HTTP. Tres decisiones
> sostienen el diseño: la inyección va **después** de `set_audit_sink` para que el evento
> `"artifact"` que el store ya emite sirva de registro de procedencia (D-ART-3); el `LineageBundle`
> gana `injected_artifacts` **aditivo** más un caveat de determinismo, y el `config_hash` **no se
> toca** —el contenido de un artefacto arbitrario no es hasheable y recalcular identidad castigaría
> a quien no usa la puerta— (D-ART-7); y el tipo **no** se valida en la puerta, sino en el
> consumidor, que es el único que conoce el contrato sin obligar a `core` a importar los DTO de
> todos los dominios (D-ART-6). ⚠️ **Corrige una afirmación del documento rector**: de los cuatro
> artefactos que `validation` exige, `('data','labels')` **no** es un DataFrame plano sino un
> `LabeledFrame`, así que T7 necesita además un adaptador (D-ART-11).
>
> **…y la columna que define el target deja de entrar como predictor (2026-07-30, APROBADA;
> implementada y cerrada el 2026-07-31).**
> [`_ENMIENDA-FUGA-TARGET-BINNING.md`](_ENMIENDA-FUGA-TARGET-BINNING.md), D-FUGA-1…D-FUGA-10,
> enmienda a SDD-06 §4/§7 y SDD-02 §4. Con `binning.feature_columns="*"` —**el default del
> campo**— el motor excluye `target_col`, que es la columna **derivada**, no los insumos de la regla
> que la calcula; con un `bad_rule` «más de 90 días de mora», la columna de mora entra al binning:
> fuga de target con AUC inflado. La medición añadió tres cosas al enunciado: **no es sólo
> `bad_rule`** (`good_rule` es su complemento exacto entre las filas modelables y también es fuga);
> la **rama de lista explícita comparte el mismo conjunto de exclusiones**, así que hay que decidir
> las dos ramas por separado; y **el mecanismo de inferencia ya existe en la línea de al lado**
> —`_data_temporal_columns` ya deriva del `DataConfig` las columnas de fecha y cohorte—, de modo que
> la enmienda extiende algo probado en vez de inventarlo. ⚠️ **Y corrige el encuadre del propio
> defecto: los hashes NO se mueven.** `config_hash` y `data_hash` quedan idénticos (el config no
> cambia; cambia lo que el motor deriva de él); lo que cambia son los resultados. Va en minor por
> eso, y la nota debe decir que **un AUC que baja tras actualizar es la corrección, no una
> regresión**. Medido además que **ningún preset de fábrica usa el wildcard en binning** y que el
> config del webinar ya excluye la columna a mano: cero goldens movidos. D-FUGA-2 deja fuera
> `indeterminate_rule` y `exclusion_rules` **con su contraejemplo**, no por falta de tiempo —
> deciden quién sale de la muestra, no la etiqueta de quien queda, y excluirlas produciría falsos
> positivos sobre columnas con variación legítima (mismo criterio que D-INV-8). **D-FUGA-10 suma
> `unique_keys` al alcance, acotado a llave de UNA columna** por la misma razón: `unique_keys` es la
> llave **compuesta** que identifica la fila («cliente + fecha», dice su propio `ui_help`), así que
> con dos o más columnas ninguna es identificador por sí sola y excluirlas repetiría el falso
> positivo. Va en commit y CHANGELOG aparte: es **ruido de identificador**, no fuga de target.
>
> **La UI debe mostrar el mismo config efectivo que ejecuta (2026-07-31, APROBADA; sin
> implementar).**
> [`_ENMIENDA-DEFAULTS-EFECTIVOS-UI.md`](_ENMIENDA-DEFAULTS-EFECTIVOS-UI.md), D-FX-1…D-FX-10,
> enmienda conjunta a SDD-01/05/23/26. Cierra el diseño de D1 y D2: el report exige como
> prerequisitos duros sólo las cards de los pasos activos de la invocación y deja que
> `missing_policy` resuelva en runtime una sección requerida pero apagada, sin retirar `eda` del
> default ni ocultar incumplimientos CT-1 de productores activos. La UI obtiene los defaults
> efectivos desde las clases Pydantic registradas mediante un catálogo versionado y probado contra
> la coacción real; JSON Schema conserva forma y validación, pero no se usa como segunda fuente de
> defaults anidados. Ausencia y `null|false|0|""|[]` explícitos son estados distintos: renderizar,
> abrir o guardar no escribe ni mueve `config_hash`, y el primer gesto materializa el valor. La
> implementación futura es atómica con copy, fixture, Vitest y bundle.
>
> **La interfaz se organiza por TRABAJO, con tus datos y tu metodología (2026-08-01, APROBADA).**
> [`_SDD-UI-POR-TRABAJOS.md`](_SDD-UI-POR-TRABAJOS.md), D-JOB-1…D-JOB-19, enmienda a
> SDD-23 §3/§4.2. Adelanta y amplía el nodo F3 del plan. Cinco síntomas con una causa medida: la
> aplicación asume que vienes a ver una demostración —el sidebar mapea las 14 secciones sin filtro,
> la sesión arranca sembrando el preset con su dataset sintético, y el abanico de metodologías viaja
> como campos sueltos—. El trabajo pasa a ser concepto de primer nivel y decide qué secciones
> existen; la sesión arranca vacía pidiendo datos propios; la puerta de artefactos se abre por
> HTTP/UI acotada a lo que cada trabajo declara; y un trabajo u opción que no corre se **declara**,
> no se oculta ni se promete. **Lo medido que más importa: no falta capacidad, falta exponerla** — el
> motor ya corre trabajos aislados y ya ofrece más de 50 puntos de elección metodológica
> implementados. Incluye las cuatro decisiones de alcance de Cami (D-JOB-11…D-JOB-14), entre ellas
> que la LGD modelada es **conectar `LgdEngine`, no construir un motor**. La aprobación del
> 2026-08-01 cerró cinco huecos que la revisión previa a programar encontró (D-JOB-15…D-JOB-19): el
> catálogo vive en el **backend** con fixture de respaldo, porque el preflight que debe consumirlo es
> Python; elegir un trabajo siembra **su esqueleto** y ningún dataset, que es lo que conserva «entrar
> basta para ejecutar» sin sembrar la demo; el trabajo **manda sobre la navegación sin parches** —y el
> config que trae secciones ajenas se resuelve seleccionando el trabajo que le corresponde, no
> añadiendo un aviso—; `validation` sale del catálogo porque el formulario no la ofrece; y **la demo
> estática sigue arrancando sembrada**, porque no tiene backend ni acepta datos propios.
>
> **Lo que sólo la institución puede decidir se pregunta, no se inventa (2026-08-01, APROBADA).**
> [`_ENMIENDA-DECISIONES-OBLIGATORIAS.md`](_ENMIENDA-DECISIONES-OBLIGATORIAS.md), D-OBL-1…D-OBL-11,
> enmienda a `_ENMIENDA-DEFAULTS-EFECTIVOS-UI.md` (D-FX-5 y D-FX-8) y a
> `_SDD-UI-POR-TRABAJOS.md` (D-JOB-3 y D-JOB-4). Activar una sección escribía un submodelo
> obligatorio con valores inventados que el motor rechaza —`target.bad_rule = {all_of: [], any_of:
> []}`—, y los **diez** trabajos nacían con config inválido. ⚠️ **La causa que la nota heredada
> atribuía era falsa**: no es que `Rule` y `TargetConfig` no sean construibles, es que
> `_mapa_de_modelo` decide mapa-vs-descriptor **mirando sólo la anotación** y nunca consulta
> `is_required()` —`DataConfig.load` sí es construible y también sale como mapa—. El criterio pasa a
> ser la obligatoriedad, y el nodo obligatorio se publica como descriptor **que conserva sus hijos**
> (`{has_default: false, children: {…}}`), forma elegida porque no obliga a tocar `isDescriptor` ni
> `canonicalProjection`. Alcance medido: no es `data`, es una clase — `survival` tiene el defecto
> idéntico y el mismo mecanismo rompe **cuatro** gestos de estructura, incluido *añadir una fila* de
> exclusión. 🔴 **Y el arreglo NO deja el config válido, a propósito**: `bad_rule` y
> `partition.strategy` son `DATO-INSTITUCIONAL`, así que el hueco pasa de un valor inventado a un
> hueco honesto. De ahí la segunda parte: un trabajo **declara sus decisiones obligatorias en idioma
> de negocio** —medido, son sólo **cuatro** en las 14 secciones del formulario—, derivadas del schema
> con gate bidireccional y mostradas al principio de Configuración. `markov` y `stress` quedan fuera
> **con su razón medida**, no por falta de tiempo.
>
> **La llave de segmentación gana dominio y régimen declarados (2026-07-25, APROBADA e
> implementada — es B3.a-1).** [`_ENMIENDA-SEGMENTACION.md`](_ENMIENDA-SEGMENTACION.md),
> D-SEG-1…D-SEG-11, enmienda a SDD-15, SDD-16, SDD-17 y SDD-03. **Reformuló B3.a-1 porque su
> premisa era falsa:** el `Literal` chileno de `governance/config.py` no era la llave de
> segmentación de ningún cálculo y la llave real (`portfolio_col`) ya era `str` libre en los tres
> motores; lo que faltaba era que **alguien declarara el dominio de valores del segmento**. Deja un
> esquema declarado —normativo / institucional / derivado del dato— que **viaja en el resultado** de
> los tres motores, y garantiza el régimen con un **registro régimen→motor con test de cobertura**,
> no con el sistema de tipos (ampliar un `Literal` compila igual sin motor detrás). Adelanta dos
> piezas del contrato de parámetros para que éste las herede en vez de contradecirlas: **CRP-3
> parcial** (la procedencia del segmento en el resultado) y **CRP-6 parcial** (D-SEG-7,
> `orchestrator.py`, hoy el **patrón de referencia** de la semántica única del flag). Tres de sus
> decisiones cambiaron al programarlas y quedaron escritas con su razón en el propio SDD.
>
> **Contrato de resolución de parámetros — su censo, re-medido y enmendado (2026-07-25, APROBADO).**
> [`_ENMIENDA-CRP-IFRS9.md`](_ENMIENDA-CRP-IFRS9.md) corrige el §2 del
> [`_CONTRATO-RESOLUCION-PARAMETROS.md`](_CONTRATO-RESOLUCION-PARAMETROS.md) y fija por dónde se
> adopta. **No leer ese §2 sin esta enmienda:** cinco lectores frescos sobre `f4fa383` confirmaron P1,
> P4 y P5 —ampliada a **siete** definiciones y **cinco** semánticas de `fail_on_falta_dato`—, pero
> **refutaron P3** (la procedencia no la registra «un solo lugar»; hay más de una docena de
> mecanismos, varios anteriores al propio censo) y corrigieron los dos polos de P2. El problema es
> mayor de lo medido: **seis** gatillos apagados por defecto y **nueve** warnings de carencia sin
> marca, no cuatro. Orden de adopción fijado: **CRP-5 → CRP-6 → CRP-4 → CRP-1/CRP-3 → CRP-7**, que
> corrige el §7 del contrato — CRP-4 sólo rotula, y lo que corrige las dos cifras erradas es el gate
> de entrada. Añade las tres decisiones sin las cuales `Resolved[T]` no era implementable: firma
> `Generic[T]` (PEP 695 exige 3.12 y el proyecto soporta 3.11), el centinela de `is_default` —hoy no
> es computable en ningún canal— y la taxonomía con familia y número de los nueve warnings.
> **Su §7 registra los seis puntos que la propia enmienda tuvo que corregir tras revisión
> adversarial**, incluido uno con la misma premisa falsa que ella denuncia.
>
> **CRP-6 — la semántica única del flag, y la marca que no se puede gobernar (2026-07-25,
> APROBADA).** [`_ENMIENDA-CRP6-FLAG.md`](_ENMIENDA-CRP6-FLAG.md), D-CRP6-1…D-CRP6-8, enmienda a
> SDD-16, SDD-19, SDD-20 y SDD-22. Re-mide el censo de las siete capas contra *la pregunta que CRP-6
> define* en vez de contra el mecanismo: **cinco de las siete ya cumplían**, porque comprobar en el
> config cuando la carencia ya es demostrable no es otra semántica, es CRP-5. Destapa dos cosas que
> ningún censo previo vio: el flag de `ifrs9` **no gobierna ninguna marca** —su `False` sólo mueve
> una validación al medio del cálculo, justo lo que CRP-5 prohíbe, así que el chequeo PIT pasa a ser
> **incondicional** en vez de renombrarse (sin migrador ni recaptura)—, y `FALTA-DATO-IFRS-4` **se
> emite en toda corrida**, de modo que conectar el flag tal cual habría abortado todo IFRS 9 con su
> default. De ahí la decisión que CRP-4 hereda: marca **gobernable** (existe una entrada válida sin
> ella) vs **estructural** (capacidad diferida del motor; se registra, nunca detiene). Mide además
> que el **preset publicado se miente a sí mismo** —`fail_on_falta_dato=True` junto a la carencia
> `SUR-3`—, invisible hasta hoy porque el flag es no-op en `survival`. Se adopta en **dos bloques**
> por la frontera de `config_hash` (§7): el B va con el P2 y una única recaptura.
>
> **SDD-23 `ui` reescrito (2026-07-06):** el borrador Streamlit quedó **descartado** (ROADMAP §F7)
> y el SDD pasó al stack React/Vite sobre FastAPI. La implementación histórica del backend/front no
> equivale a la implementación de la distribución aprobada en B2.0.

## Tandas de producción

| Tanda | SDDs | Foco | Pre-requisito |
|---|---|---|---|
| **T0 — Verificación** | (ninguno nuevo) | Doble-check de TODO lo ya hecho (spec, normativa CMF, índice, roadmap, plantilla) contra fuente oficial; corregir antes de avanzar. | — |
| **T1 — Fundación** | 01, 02, 03, 04, 05, 24, 25 | El núcleo del que todo cuelga; sin esto nada es auditable. | T0 |
| **T2 — Scoring (F1)** | 27, 06, 07, 08, 09, 10, 11, 26 | EDA + MVP open-source + informe determinístico (release público). | T1 |
| **T3 — ML (F2)** | 12, 13, 14 | Benchmark predictivo + explicabilidad. | T2 |
| **T4 — Provisiones (F3-F4)** | 15, 16, 17 | CMF e IFRS 9 como motores separados + orquestación configurable. | T2 (PD); T5 parcial (lifetime) |
| **T5 — Forward-looking (F5)** | 18, 19, 20, 21 | Lifetime PD, escenarios, stress. | T2 |
| **T6 — Validación + UI (F6-F7)** | 22, 23 | Backtesting y producto no-code (UI = web premium React/Vite + FastAPI sobre la API pública). | T2–T5 |
| **T7 — Provisiones end-to-end (F8)** | 28 | Método interno B-1 + máximo estándar/interno + ruta hasta UI/informe. | T2, T4, T6 |

> **Nota de dependencia cruzada:** IFRS 9 lifetime (SDD-16) usa la term-structure de `survival`/`markov` (T5). Se especifica en T4 con interfaz abstracta y se conecta cuando T5 esté lista (ver roadmap, dependencia F4↔F5).

## Convenciones de los SDD
- Numeración estable (el número no se reutiliza aunque se reordene).
- Cada SDD es autocontenido pero enlaza sus dependencias.
- Las **fórmulas y parámetros normativos** se citan desde [`ESPECIFICACIONES.md`](../ESPECIFICACIONES.md) y [`normativa_cmf_parametros.md`](../normativa_cmf_parametros.md), no se reescriben.
