# Propuesta pre-START — calibración H9R por flujo y oleada

> **Estado: APROBADA el 2026-08-13 COMO PROTOCOLO PRE-START PARA IMPLEMENTAR Y REVISAR EL
> ARNÉS; SIN START.** Cami aprobó D-RDY-H9R-1…8 el 2026-08-12 y el texto entonces vigente de
> este protocolo el 2026-08-13. El segundo OK autoriza únicamente implementar, probar y revisar el
> arnés; **no** autoriza ninguna unidad START, S0, S1 o S2. La evidencia histórica S0/S1/S2 se
> preserva; la
> autorización S2 `0/1` está cancelada y no puede revivir.
> El mapeo legible por máquina de §10.1 se incorporó después como anotación de implementación no
> normativa: sus `adapter_id` y su serialización JSON no formaron parte del OK byte-exacto.
>
> Este documento sólo preespecifica hipótesis y oráculos. Los caps, geometrías, budgets, disco y
> perfiles candidatos no son contrato ni copy público. Ningún valor se vuelve gate hasta ser medido,
> revisado independientemente y aprobado de forma exacta por Cami.

## TL;DR y recomendación ejecutiva

Calibrar cada flujo alcanzable dentro de un árbol fresco limitado a **4 CPU lógicas** y una escalera
hipotética de **4, 5 y 6 GiB de memoria comprometida job-wide**. Buscar la mayor geometría
bracketed por un rojo controlado, primero con tres intentos de screening y luego con diez intentos
totales de confirmación. Los deadlines sólo protegen el host; los budgets se propondrán después con
una regla robusta que no descarta outliers.

El consumidor se mide desde la primera apertura de sus inputs hasta el flush, hash y publicación
atómica de sus outputs. Fixture, instalación y supervisor externo quedan fuera, pero sus bytes,
hashes y overhead se registran por separado. Memoria y disco se observan como series y como peaks
del sistema operativo; un resultado incompleto, un huérfano o un manifiesto final tras fallo ponen
rojo el intento.

La recomendación es aprobar este protocolo sólo como autorización para **implementar y probar el
arnés**, no para ejecutar workloads. Cada futuro START seguirá requiriendo una autorización propia
para la unidad `candidato × flujo × intento`.

## 1. Autoridad, alcance y no-decisiones

Gobiernan [`30-readiness-integral.md`](30-readiness-integral.md),
[`DECISIONES-VIGENTES.md`](DECISIONES-VIGENTES.md) y
[`_ENMIENDA-H9-ENTORNO-REPRESENTATIVO.md`](_ENMIENDA-H9-ENTORNO-REPRESENTATIVO.md).

Queda fijo por D-RDY-H9R:

- target declarado de hasta 4 CPU lógicas y una máquina de 8 GB nominales;
- calibración inicial en Windows, con confinamiento efectivo si el host físico es mayor;
- aplicación por flujo y por oleada W1–W5, no una corrida transversal anticipada;
- START unitario, árbol fresco, preflight y atestación anteriores al trabajo;
- hashes, lineage, identidad, orden, completitud bidireccional y publicación atómica;
- W0 histórica e inmutable, W1 NO PASS y ausencia de copy público antes del PASS.

Son únicamente hipótesis de este documento:

- caps C4/C5/C6, geometrías G−/G0/G+ y deadlines externos;
- cantidad de repeticiones y regla estadística;
- pisos externos de memoria/disco para proteger el host;
- schema de evidencia v1 y catálogo cerrado de resultados.

Quedan fuera: optimización y código de producto, workflows, hardware/cloud, metodología de riesgo,
API, H10, PyPI, demo y cualquier perfil final. Sólo el código interno del arnés y sus pruebas queda
autorizado por el OK del 2026-08-13. W6–W8 consumen después los perfiles aprobados; no se calibran
por adelantado aquí. `PortfolioStress` sigue excluido por H8=A y roll-rate/vintage no entra hasta
que exista el addendum metodológico exigido por H7=A.

## 2. Unidad START y orden obligatorio

La identidad mínima es:

```text
candidate_manifest_sha256 × flow_id × flow_step × fixture_manifest_sha256 × config_hash
× geometry_id × cap_id × attempt_ordinal
```

`flow_step` separa árboles consumidores distintos dentro de un mismo flujo —por ejemplo fit y apply—
sin cambiar la unidad mínima `candidato × flujo × intento` de D-RDY-H9R-5. Su valor canónico es
`run` cuando el flujo tiene una sola frontera; en los demás casos usa el step explícito de la tabla
de §4. Cada combinación produce un `attempt_id` y un árbol nuevo. Un START sólo sería autorizable si
antes existen y reconcilian:

`candidate_manifest_sha256` es SHA-256 del JSON UTF-8 del manifiesto de distribución, serializado
con claves ordenadas, separadores canónicos y sin campos volátiles. No es el hash del wheel ni del
source por separado; ambos deben aparecer y reconciliar dentro del manifiesto.

1. texto/digest de autorización que nombra exactamente la unidad;
2. manifiesto candidato canónico y su SHA-256, que enumeran source SHA, wheel, sdist y lock con
   bytes y SHA-256 propios; por separado, driver, supervisor, config, propuesta y fixture también
   quedan congelados con sus digests;
3. workdir vacío y exclusivo fuera del checkout, sin caches mutables compartidas;
4. atestación de CPU, memoria, disco, power scheme, versión de Windows y pools nativos;
5. límites efectivos consultados al sistema operativo y token READY anterior a START;
6. destino de evidencia exclusivo que falla si ya existe.

Train, batch, UI y temporal no comparten proceso, cache, bundle mutable ni intento. Un bundle que
consume otro flujo es un input firmado, no estado retenido. El orden de trabajo futuro es:

```text
aprobar protocolo → implementar arnés → probar oráculos → revisar arnés → autorizar cada START
→ medir baseline sin optimizar → proponer perfil final → revisar → aprobar → recién optimizar si rojo
```

## 3. Hipótesis de CPU y memoria

### 3.1 CPU

El límite es exactamente un conjunto de hasta cuatro CPU lógicas. En un host mayor, la raíz, sus
descendientes y pools nativos deben heredar el mismo conjunto; el Job Object de memoria no demuestra
esta condición. Antes de START se registran máscara/CPU Set solicitado y efectivo por PID/TID, y las
variables de pools BLAS/OpenMP conocidas. Una CPU fuera del conjunto clasifica el intento como
`limits_not_applied`.

En una máquina física de cuatro CPU no se infiere cumplimiento: el arnés igualmente atestigua el
censo y prueba que no aparece un quinto recurso lógico. Los tiempos sólo describen el modelo de CPU,
power scheme, SO y runtime firmados; no se extrapolan a otro host.

### 3.2 Escalera de caps job-wide

| Cap ID | Límite hipotético | Uso en calibración |
|---|---:|---|
| `C4` | 4 GiB = 4.294.967.296 B | primer cap evaluado |
| `C5` | 5 GiB = 5.368.709.120 B | sólo si la misma geometría choca C4 |
| `C6` | 6 GiB = 6.442.450.944 B | último cap de esta propuesta |

El límite se aplica a **memoria comprometida del Job completo** y se verifica con
`PeakJobMemoryUsed`; working set/RSS se informa aparte y nunca sustituye el cap. Supervisor y cliente
externos no consumen el cap, pero su memoria se mide para demostrar que no ocultan el riesgo del
host.

El target aprobado es una máquina de **8 GB nominales**, no 8 GiB ni una cantidad visible
byte-exacta. Por eso no se resta el cap del nominal para declarar una reserva fija. Cada intento
registra RAM física/visible/disponible y sólo puede usar C4/C5/C6 si cumple las guardas dinámicas de
§6; C6 puede quedar descartado por esas guardas aun siendo parte de la escalera hipotética.

Para cada geometría se prueba primero el menor cap. Un cap sólo es elegible si la geometría
confirmada termina 10/10 veces y el máximo observado no supera 85 % del límite. No se propone cap
mayor a C6 sin una nueva propuesta y OK. Si C6 no basta, el resultado es rojo medido; no se rebaja la
geometría ni se cambia implementación dentro del mismo intento.

## 4. Geometrías candidatas por oleada y flujo

G−/G0/G+ son puntos de búsqueda, no N−1/N/N+1 contractuales. Los campos no mencionados permanecen
idénticos al fixture funcional aprobado de la oleada; variar filas no autoriza cambiar metodología,
distribución, escenarios, estados o covariables. `filas expandidas` se calcula y reconcilia, no se
presupone desde operaciones.

| Oleada · Flow ID · step | G− | G0 | G+ | Outputs incluidos en la frontera |
|---|---:|---:|---:|---|
| W1 · `F-SCORE-TRAIN` · `train` | 100.000×50; card. máx. 10.000 | 250.000×75; card. máx. 25.000 | 500.000×100; card. máx. 50.000 | bundle, reglas, hashes, lineage y manifiesto |
| W1 · `F-SCORE-APPLY` · `apply` | 100.000 filas | 250.000 filas | 500.000 filas | `application`, `woe`, `trace`, summary y manifiesto; mismo bundle firmado |
| W1 · `F-SCORE-BATCH` · `batch` | 250.000 filas | 500.000 filas | 1.000.000 filas | las mismas tres vistas particionadas, summary y manifiesto; mismo bundle firmado |
| W1 · `F-UI` · `run` (baseline separado) | payload 16 MiB | payload 32 MiB | payload 64 MiB | recepción, ejecución y primera página verificable; no fija H10 |
| W2 · `F-LGD-BASE` · `run` | 250.000 operaciones | 500.000 operaciones | 1.000.000 operaciones | LGD por operación, procedencia y manifiesto; sin fingir fit |
| W2 · `F-LGD-OOS` · `fit` | 100.000 operaciones | 250.000 operaciones | 500.000 operaciones | bundle modelado, covariables crudas, hashes, lineage y manifiesto |
| W2 · `F-LGD-OOS` · `apply` | 250.000 operaciones | 500.000 operaciones | 1.000.000 operaciones | LGD OOS por operación, procedencia, hashes y manifiesto |
| W2 · `F-EAD-BASE` · `run` | 250.000 operaciones | 500.000 operaciones | 1.000.000 operaciones | EAD por operación, reconciliación y manifiesto |
| W2 · `F-EAD-T` · `run` | 25.000×60 = 1,5 M | 50.000×60 = 3 M | 100.000×60 = 6 M | detalle operación×período, movimientos, reconciliación y manifiesto |
| W2 · `F-CMF-REFERENCE` · `run` | 100.000 operaciones | 250.000 operaciones | 500.000 operaciones | salidas congeladas del caso de referencia e informe; motor intacto |
| W3 · `F-PD-SURVIVAL` · `run` | 250.000 observaciones | 500.000 observaciones | 1.000.000 observaciones | bundle/term structure, basis, unidad, lineage y manifiesto |
| W3 · `F-PD-MARKOV` · `run` | 250.000 transiciones | 500.000 transiciones | 1.000.000 transiciones | matrices/curvas segmentadas, reconciliación y manifiesto |
| W4 · `F-IFRS9` · `run` | 25.000×60×3 = 4,5 M | 50.000×60×3 = 9 M | 100.000×60×3 = 18 M | staging, detalle, summary, escenarios y manifiesto |
| W4 · `F-FORWARD-IFRS9` · `run` | 10.000×60×3 = 1,8 M | 25.000×60×3 = 4,5 M | 50.000×60×3 = 9 M | macro/basis, staging, detalle, reconciliación y manifiesto |
| W5 · `F-STRESS-ECON` · `run` | 5.000×60×3 | 10.000×60×3 | 25.000×60×3 | baseline + tres shocks funcionales, reconciliación y manifiesto |

Para batch, LGD, EAD, temporal e IFRS/stress, columnas/covariables, segmentos, estados, horizonte y
escenarios se congelan desde el fixture funcional antes de generar la escalera. Las cifras de la
tabla son hipótesis de volumen, no afirmaciones de que el flujo ya sea alcanzable.

La búsqueda gruesa es ascendente por geometría G y cap. Para declarar una frontera medible debe
existir un punto G confirmado y el siguiente punto de la escalera con un rojo de recurso
**controlado y atribuible al cap** (`job_memory_limit`), nunca OOM del host, deadline externo, guarda
de seguridad, error genérico o evidencia incompleta. Un `watchdog_deadline` sólo protege el host: no
selecciona G ni se convierte en budget. Si G+ termina verde bajo C6, la escalera no acota la frontera:
se detiene y se somete una extensión a otro OK. Si G− falla bajo C6, el flujo queda rojo sin inventar
un punto menor.

El punto G confirmado se convierte después de la medición en **geometría N candidata**, todavía no
en gate. La matriz exacta N−1/N/N+1 pertenece al futuro `S3-limite`, una vez que Cami apruebe N y se
implemente su preflight: N−1 y N deben aceptarse; N+1 debe rechazarse **antes de trabajo pesado**. Se
varía una sola dimensión por vez y se congelan las demás. En scoring train son filas, variables y
cardinalidad; en batch/UI son filas o bytes; en flujos longitudinales son operaciones/observaciones
y, cuando ya forme parte del contrato funcional, horizonte o escenarios. La adyacencia es una unidad
exacta en la dimensión (`N-1`, `N`, `N+1`), no el salto entre G−/G0/G+. Un cambio metodológico nunca
se disfraza de dimensión de escala.

## 5. Fixtures y artefactos congelados

La generación sintética ocurre fuera de START. Se reutiliza `root_seed=20240706` y cada fixture
deriva su sub-seed de SHA-256 sobre `h9r-cal-v1\0flow_id\0geometry_id`; el entero exacto queda en el
manifiesto. Esta regla sólo busca repetibilidad y no cambia la metodología del flujo.

Antes de pedir un START, cada fixture debe publicar:

- `fixture_schema_version`, nombres/dtypes/roles y SHA-256 del schema canónico;
- config canónico con bytes, SHA-256/`config_hash` y reglas de normalización;
- path lógico, formato, filas de entrada, filas expandidas esperadas y dimensiones completas;
- bytes lógicos y bytes asignados en disco, además del SHA-256 de cada archivo;
- seed raíz/sub-seed, generador y commit con SHA-256;
- catálogo de especiales/missing/categorías, escenarios, segmentos y supuestos aplicables;
- identidades esperadas, conteos y hash del golden pequeño que valida la semántica;
- evidencia de que no contiene datos de cliente ni es un fixture de demo recapturado.

Los hashes no existen todavía y no se rellenan con placeholders. El OK del 2026-08-13 autoriza
implementar y probar el arnés con fixtures efímeros de control; no autoriza generar los fixtures
definitivos de calibración ni recapturar o regenerar la demo.

## 6. Deadlines externos y guardas de seguridad

Los fusibles se miden por fase con reloj monotónico: preflight desde su inicio hasta READY;
handshake desde READY hasta el token START; y workload desde START hasta que el árbol queda vacío.
Sólo el workload pertenece a la unidad START y a la frontera del consumidor. Todos son deadlines
externos de seguridad, no budgets, SLA ni copy. Un timeout conserva telemetría cruda, mata el Job
completo y prohíbe manifiesto final.

| Flujo | Deadline externo hipotético |
|---|---:|
| preflight, sin trabajo pesado | 300 s |
| handshake READY→START | 60 s |
| W1 scoring train | 7.200 s |
| W1 apply/batch | 7.200 s |
| W1 UI baseline | 1.800 s |
| W2 LGD fit/apply | 7.200 s |
| W2 EAD/CMF | 3.600 s |
| W3 survival/Markov | 7.200 s |
| W4 IFRS 9 + forward | 10.800 s |
| W5 stress económico | 10.800 s |

Guardas externas adicionales, también no contractuales:

- preflight exige memoria física disponible ≥2 GiB y headroom de commit del sistema ≥2 GiB;
- durante START, disponibilidad física <1 GiB o headroom de commit <1 GiB durante dos muestras
  consecutivas clasifica `safety_abort_system_memory`;
- preflight exige disco libre `max(4 GiB, 3 × bytes_asignados(inputs + bundle))`;
- disco libre <1 GiB durante START clasifica `safety_abort_disk`;
- una falla del sensor, un salto de reloj monotónico o una muestra ausente >2 s clasifica
  `evidence_incomplete`, no success.

Estas guardas no derivan el cap ni la fórmula final de disco. Sólo impiden que una hipótesis agote el
host antes de tener medición confiable.

## 7. Repeticiones y regla estadística

### 7.1 Protocolo adaptativo

1. **Screening:** tres intentos frescos por celda evaluada. Cualquier resultado no normal impide
   promoverla; no se reemplaza el intento ni se descarta como outlier.
2. **Confirmación:** la celda N/cap candidata acumula diez intentos frescos totales. Exige 10/10
   `success`, hashes/reconciliaciones exactos y ausencia de guardas activadas.
3. **Bracket grueso:** el G anterior debe dar 3/3 success; G conserva sus 10/10; el G siguiente debe
   dar 3/3 `job_memory_limit` bajo el mismo cap. Un deadline, una guarda o resultados heterogéneos
   dejan la frontera indeterminada y no producen perfil. N−1/N/N+1 se reserva al `S3-limite` exacto
   descrito en §4; no se confunde con esta escalera.
4. **Orden:** no se ejecuta una celda mayor si la anterior terminó con OOM del host, error no
   clasificado, huérfano o evidencia incompleta. Primero se corrige el arnés y se vuelve a revisión.

Todos los intentos usan proceso, workdir, fixture materializado y caches frescos. El orden de las
diez confirmaciones se permuta de forma determinista entre celdas autorizadas para no confundir
deriva térmica con geometría; el ordinal y la permutación quedan firmados antes del primer START.

### 7.2 Estadísticos y derivación posterior

Para una métrica positiva `x` sobre los diez intentos se calculan:

```text
m = mediana(x)
MAD* = 1,4826 × mediana(|x - m|)
U(x) = max(máximo(x), m + 3 × MAD*)
```

No se elimina ninguna observación. Si `MAD* / m > 0,20` —o `m=0` sin explicación física— la celda
es inestable y no deriva valores finales.

Después de medir, y sólo como propuesta para otra aprobación:

- `budget_candidato = ceil_30s(1,20 × U(wall_seconds))`;
- `memoria_necesaria = ceil_256MiB(U(peak_job_commit_bytes) / 0,85)` y se elige el menor cap
  preaprobado que la cubra;
- `disco_libre_candidato = ceil_256MiB(U(peak_incremental_allocated_bytes) +
  max(0,20 × U(peak_incremental_allocated_bytes), 3 × MAD*_disk) + 1 GiB)`.

La regla es conservadora y reproducible, pero no afirma una garantía probabilística de cola con sólo
diez repeticiones. La propuesta final publicará mediana, mínimo, máximo, MAD*, U y los diez valores;
si se requiere un percentil/SLA con confianza formal, hará falta otro diseño muestral y otro OK.

## 8. Fronteras del consumidor

La generación y firma del fixture, descarga/instalación del candidato y creación del workdir ocurren
fuera. Dentro del Job quedan todas las operaciones que realizaría el consumidor desde un archivo ya
existente:

| Flujo | Inicio incluido | Fin incluido |
|---|---|---|
| scoring train | primera apertura de input/config | bundle, hashes, lineage y manifiesto publicados atómicamente |
| scoring apply/batch | load y verificación del bundle + primera apertura de cartera | tres vistas, summary, hashes y manifiesto publicados atómicamente |
| UI | primer byte HTTP recibido por el servicio fresco | primera página verificable y artefactos finales del flujo; cliente externo excluido |
| LGD | apertura de frame crudo/config/bundle | artefacto o LGD por operación, procedencia, hashes y manifiesto |
| EAD/CMF | apertura de inputs/config | detalle/reconciliación, outputs propios, hashes y manifiesto |
| survival/Markov | apertura del ledger/config | term structure/matrices/curvas, basis, hashes y manifiesto |
| IFRS 9 + forward | apertura de todos los paths, pesos y componentes | staging, detalle, summaries, reconciliación, hashes y manifiesto |
| stress económico | apertura del baseline, shocks e inputs reales | baseline/stressed/reverse aplicable, reconciliación, hashes y manifiesto |

Parseo, validación, cálculo, hashes, lineage, serialización, temporales, `fsync`/flush y rename final
quedan dentro. La lectura no puede moverse antes de START y la generación no puede moverse dentro.
Todo descendiente, pool nativo o worker pertenece al mismo envelope. El supervisor externo sólo
aplica/consulta límites, toma muestras, clasifica y escribe sidecars; no transforma datos ni produce
outputs de negocio.

UI no fija por rebote H10: se mide separada del engine, con servicio fresco, y reporta tiempo hasta
acuse/primera página y tiempo total. Elegir sync/job, payload o threshold requiere la decisión H10
posterior basada en el primer baseline alcanzable.

## 9. Instrumentación de CPU, memoria y disco

### 9.1 CPU y árbol

- atestación previa y posterior de máscara/CPU Set por raíz y descendientes;
- censo de PIDs/TIDs con creation time para evitar reutilización de PID;
- CPU user/kernel acumulada del Job y por proceso;
- variables y tamaño efectivo de pools BLAS/OpenMP, más threads máximos observados;
- muestreo cada 250 ms desde READY hasta árbol vacío; `PeakJobMemoryUsed` y accounting del Job son
  peaks autoritativos aunque caigan entre muestras.

### 9.2 Memoria

Se registran por muestra y al cierre:

- job commit actual/peak, private usage/pagefile y working set actual/peak por proceso;
- suma del árbol y peak del Job consultado al kernel;
- memoria física total/visible/disponible y commit total/límite/disponible del sistema;
- page faults, procesos activos/terminados y causa de terminación;
- memoria del supervisor/cliente externos como serie separada.

Un peak RSS individual no acredita el cap job-wide. `MemoryError`, exit code o kill sin accounting y
clasificación inequívoca es `evidence_incomplete`.

### 9.3 Disco

Se distinguen bytes lógicos de bytes asignados. Antes de READY se censa el baseline por raíz
(`inputs`, `bundle`, `scratch`, `outputs`, `telemetry`). Cada 250 ms se registra:

- espacio libre del volumen y mínimo observado;
- bytes lógicos/asignados y conteo de archivos por raíz;
- high-water incremental de scratch, outputs parciales/finales y telemetría;
- bytes leídos/escritos por proceso cuando Windows los exponga;
- eventos create/rename/delete y presencia del manifiesto final.

Al cierre se vuelve a recorrer el árbol, se hashea cada artefacto y se reconcilia:

```text
footprint_total = bytes_asignados(inputs + bundle) + peak_incremental_allocated
peak_incremental_allocated = max_t(asignados(scratch + outputs + telemetry) - baseline)
```

Si el filesystem no entrega allocation size confiable, la medición no deriva fórmula de disco. Una
caída de espacio libre causada por otro proceso se informa como contaminación del host y deja la
celda no elegible; no se atribuye silenciosamente a Nikodym.

## 10. Schema de evidencia

Cada intento escribe JSON canónico con `schema_version = nikodym.readiness.h9r.calibration.v1` y
sidecars JSONL. El JSON final referencia SHA-256 y cantidad de registros de cada sidecar.

| Objeto requerido | Contenido mínimo |
|---|---|
| `identity` | `attempt_id`, unidad START completa, timestamps monotónicos/wall, flow/step/geometry/cap/ordinal |
| `authority` | hash del texto de autorización, propuesta, SDD-30 y enmienda; `start_authorized=true` sólo con match exacto |
| `candidate` | manifiesto/digest candidato, source SHA, wheel/sdist/lock/runtime hashes y árbol instalado |
| `tooling` | driver/supervisor/propuesta con bytes, SHA-256 y versión de protocolo |
| `fixture` | schema/hash/seed, config canónico/`config_hash`, dimensiones, bytes lógicos/asignados, inputs y goldens |
| `environment` | Windows/build, CPU/model/topología, power scheme, RAM nominal/física/visible, volumen/filesystem |
| `limits` | CPU Set/máscara, cap job commit, deadline y guardas solicitadas/efectivas con orden READY→START |
| `boundary` | eventos first-open, first-byte, fases, flush/hash/rename y exclusiones declaradas |
| `resources` | accounting Job, peaks, series CPU/memoria/disco y hashes de sidecars |
| `outputs` | inventario completo con identidad, orden, filas, bytes, SHA-256, reconciliaciones y atomicidad |
| `termination` | return codes unsigned/signed, causa, cleanup, árbol vacío y ausencia/presencia válida de manifiesto |
| `gates` | condiciones positivas, controles negativos aplicables y oráculos de completitud en ambos sentidos |
| `result` | clasificación cerrada, elegibilidad estadística y razones; nunca un booleano sin evidencia |

Catálogo cerrado de `result.classification`:

```text
success
preflight_rejected
limits_not_applied
job_memory_limit
watchdog_deadline
safety_abort_system_memory
safety_abort_disk
host_contamination
host_oom
cancelled
consumer_error
supervisor_error
invariant_failure
orphan_detected
evidence_incomplete
```

No existe `unknown` aprobable. Un caso nuevo exige revisar schema y gate antes de medir. Sólo
`success` entra al cálculo estadístico; los demás se conservan y cuentan como intentos, nunca se
sobrescriben. Ante cualquier no-success, `outputs.final_manifest_present` debe ser `false`.

### 10.1 Mapeo estático de implementación posterior (no normativo)

Este bloque se añadió después del OK del 2026-08-13 para reconciliar el texto aprobado con la
implementación. No forma parte byte-exacta de aquel OK: las identidades `adapter_id` y el layout
JSON son un mapeo operativo, no una decisión nueva ni una autorización START. Las hipótesis de
oleada, frontera, deadline, geometrías y outputs continúan gobernadas por los apartados aprobados
anteriores. El gate parsea por AST el archivo fuente del catálogo y este bloque JSON; no importa ni
ejecuta el módulo runtime `contracts.py`.

```json h9r-flow-catalog-v1
[{"adapter_id":"nikodym.h9r.score_train.train.v1","deadline_seconds":7200.0,"flow_id":"F-SCORE-TRAIN","flow_step":"train","geometries":{"G+":{"max_cardinality":50000,"rows":500000,"variables":100},"G-":{"max_cardinality":10000,"rows":100000,"variables":50},"G0":{"max_cardinality":25000,"rows":250000,"variables":75}},"outputs":["bundle","rules","hashes","lineage"],"wave":"W1"},{"adapter_id":"nikodym.h9r.score_apply.apply.v1","deadline_seconds":7200.0,"flow_id":"F-SCORE-APPLY","flow_step":"apply","geometries":{"G+":{"rows":500000},"G-":{"rows":100000},"G0":{"rows":250000}},"outputs":["application","woe","trace","summary"],"wave":"W1"},{"adapter_id":"nikodym.h9r.score_batch.batch.v1","deadline_seconds":7200.0,"flow_id":"F-SCORE-BATCH","flow_step":"batch","geometries":{"G+":{"rows":1000000},"G-":{"rows":250000},"G0":{"rows":500000}},"outputs":["application","woe","trace","summary"],"wave":"W1"},{"adapter_id":"nikodym.h9r.ui.run.v1","deadline_seconds":1800.0,"flow_id":"F-UI","flow_step":"run","geometries":{"G+":{"payload_bytes":67108864},"G-":{"payload_bytes":16777216},"G0":{"payload_bytes":33554432}},"outputs":["receipt","execution","first_verifiable_page","flow_artifacts"],"wave":"W1"},{"adapter_id":"nikodym.h9r.lgd_base.run.v1","deadline_seconds":3600.0,"flow_id":"F-LGD-BASE","flow_step":"run","geometries":{"G+":{"operations":1000000},"G-":{"operations":250000},"G0":{"operations":500000}},"outputs":["lgd_by_operation","provenance"],"wave":"W2"},{"adapter_id":"nikodym.h9r.lgd_oos.fit.v1","deadline_seconds":7200.0,"flow_id":"F-LGD-OOS","flow_step":"fit","geometries":{"G+":{"operations":500000},"G-":{"operations":100000},"G0":{"operations":250000}},"outputs":["modeled_bundle","raw_covariates","hashes","lineage"],"wave":"W2"},{"adapter_id":"nikodym.h9r.lgd_oos.apply.v1","deadline_seconds":7200.0,"flow_id":"F-LGD-OOS","flow_step":"apply","geometries":{"G+":{"operations":1000000},"G-":{"operations":250000},"G0":{"operations":500000}},"outputs":["lgd_oos_by_operation","provenance","hashes"],"wave":"W2"},{"adapter_id":"nikodym.h9r.ead_base.run.v1","deadline_seconds":3600.0,"flow_id":"F-EAD-BASE","flow_step":"run","geometries":{"G+":{"operations":1000000},"G-":{"operations":250000},"G0":{"operations":500000}},"outputs":["ead_by_operation","reconciliation"],"wave":"W2"},{"adapter_id":"nikodym.h9r.ead_t.run.v1","deadline_seconds":3600.0,"flow_id":"F-EAD-T","flow_step":"run","geometries":{"G+":{"expanded_rows":6000000,"operations":100000,"periods":60},"G-":{"expanded_rows":1500000,"operations":25000,"periods":60},"G0":{"expanded_rows":3000000,"operations":50000,"periods":60}},"outputs":["operation_period_detail","movements","reconciliation"],"wave":"W2"},{"adapter_id":"nikodym.h9r.cmf_reference.run.v1","deadline_seconds":3600.0,"flow_id":"F-CMF-REFERENCE","flow_step":"run","geometries":{"G+":{"operations":500000},"G-":{"operations":100000},"G0":{"operations":250000}},"outputs":["frozen_reference_outputs","report"],"wave":"W2"},{"adapter_id":"nikodym.h9r.pd_survival.run.v1","deadline_seconds":7200.0,"flow_id":"F-PD-SURVIVAL","flow_step":"run","geometries":{"G+":{"observations":1000000},"G-":{"observations":250000},"G0":{"observations":500000}},"outputs":["bundle","term_structure","basis","unit","lineage"],"wave":"W3"},{"adapter_id":"nikodym.h9r.pd_markov.run.v1","deadline_seconds":7200.0,"flow_id":"F-PD-MARKOV","flow_step":"run","geometries":{"G+":{"transitions":1000000},"G-":{"transitions":250000},"G0":{"transitions":500000}},"outputs":["segmented_matrices","curves","reconciliation"],"wave":"W3"},{"adapter_id":"nikodym.h9r.ifrs9.run.v1","deadline_seconds":10800.0,"flow_id":"F-IFRS9","flow_step":"run","geometries":{"G+":{"expanded_rows":18000000,"operations":100000,"periods":60,"scenarios":3},"G-":{"expanded_rows":4500000,"operations":25000,"periods":60,"scenarios":3},"G0":{"expanded_rows":9000000,"operations":50000,"periods":60,"scenarios":3}},"outputs":["staging","detail","summary","scenarios"],"wave":"W4"},{"adapter_id":"nikodym.h9r.forward_ifrs9.run.v1","deadline_seconds":10800.0,"flow_id":"F-FORWARD-IFRS9","flow_step":"run","geometries":{"G+":{"expanded_rows":9000000,"operations":50000,"periods":60,"scenarios":3},"G-":{"expanded_rows":1800000,"operations":10000,"periods":60,"scenarios":3},"G0":{"expanded_rows":4500000,"operations":25000,"periods":60,"scenarios":3}},"outputs":["macro","basis","staging","detail","reconciliation"],"wave":"W4"},{"adapter_id":"nikodym.h9r.stress_econ.run.v1","deadline_seconds":10800.0,"flow_id":"F-STRESS-ECON","flow_step":"run","geometries":{"G+":{"operations":25000,"periods":60,"scenarios":3},"G-":{"operations":5000,"periods":60,"scenarios":3},"G0":{"operations":10000,"periods":60,"scenarios":3}},"outputs":["baseline","three_functional_shocks","reconciliation"],"wave":"W5"}]
```

El agregado por celda usa `nikodym.readiness.h9r.calibration.aggregate.v1`, enumera exactamente los
attempt IDs esperados y recibidos, conserva todos los valores y calcula la regla de §7. Un intento
faltante o extra pone rojo la completitud.

## 11. Reglas de PASS, rojo y detención

Una celda sólo es elegible si:

- autorización, candidato, fixture y límites coinciden byte a byte;
- CPU efectiva ≤4 y cap job-wide efectivo coincide con C4/C5/C6;
- todos los outputs propios del flujo reconcilian en ambos sentidos;
- no hay timeout, guardas, proceso huérfano, cache compartida ni contaminación;
- el manifiesto aparece sólo tras finalizar y hashear todo;
- repetición y headroom satisfacen §7.

`host_contamination` cubre deriva externa demostrada de CPU/memoria/disco; `host_oom` cubre OOM del
sistema fuera de la terminación inequívoca del Job; `cancelled` cubre cancelación humana o externa
autorizada. Las tres detienen la campaña y nunca son elegibles.

Una celda roja no autoriza optimizar. Primero se publica su causa medida; Cami decide en otra sesión
si corresponde proponer implementación, menor geometría o revisar el target. Se detiene toda la
campaña si aparece OOM del host, disco crítico, límites no aplicados, clasificación nueva, evidencia
incompleta, outputs parciales publicables o discrepancia de hashes.

El cierre de una oleada requiere perfil exacto por cada flujo obligatorio que esa oleada vuelva
alcanzable. Un scoring verde no compensa LGD/temporal rojo y W1 no anticipa W2–W5.

## 12. Controles negativos preespecificados

| Oráculo | Defecto mínimo futuro | Rojo esperado |
|---|---|---|
| autorización/preflight | emitir START sin autorización o antes de READY | `preflight_rejected`/`limits_not_applied`; cero trabajo pesado |
| CPU | hijo intenta ampliar afinidad/CPU Set o pool a una quinta CPU | `limits_not_applied`; árbol terminado |
| memoria | hijo controlado compromete C+1 byte dentro del Job | `job_memory_limit`, host sobre guardas y cero manifiesto |
| deadline | hijo duerme más que el fusible | `watchdog_deadline`, cleanup completo y cero manifiesto |
| guardas | sensor inyectado cruza memoria/disco sin presionar el host real | clasificación safety exacta y cero trabajo/manifest |
| frontera | abrir input antes de START o generar fixture después | `invariant_failure` por orden de eventos |
| completitud | quitar una identidad y, en otra prueba, añadir una no catalogada | gate bidireccional rojo en ambos casos |
| orden | permutar o duplicar filas/chunks | hash/reconciliación rojo |
| atomicidad | terminar entre escritura parcial y rename | parciales censados; manifiesto final ausente |
| evidencia | alterar/eliminar una muestra o sidecar | `evidence_incomplete`; agregado rojo |
| disco | falsificar allocation size o excluir temporales del censo | reconciliación de footprint roja |
| estadística | omitir un intento o descartar el máximo | agregado de cardinalidad/regla rojo |
| copy | insertar “4 CPU/8 GB” como capacidad en superficie pública | gate de copy rojo antes de PASS |
| aislamiento OS del candidato | quitar la etiqueta de una raíz escribible; ponérsela a una protegida; dejar un **archivo** etiquetado bajo un padre protegido; interponer una junction en el contenedor | censo bidireccional rojo en los cuatro casos, con la denegación real del SO comprobada contra un doble sintético |

Cada control sigue verde → defecto mínimo → rojo por la causa prevista → restauración byte-exacta →
verde. Los controles de completitud se prueban en ambos sentidos. Ningún defecto temporal permanece
en el árbol ni se restaura desde el índice Git.

## 12.1 Fronteras de implementación y su estado medido

El arnés no abre su puerta central mientras falte cualquiera de estas fronteras. Ninguna de ellas
autoriza START: cerrarlas sólo deja de bloquear por *implementación*, y la autorización humana por
unidad sigue siendo obligatoria.

| Frontera | Estado | Evidencia |
|---|---|---|
| `qualifying_boundary_adapters_unavailable` | abierta | broker consumer-open y proxy UI existen como prototipo; no califican sin lease continuo |
| `candidate_execution_material_lease_unimplemented` | abierta | falta lease no-follow del ejecutable, árbol candidato e inputs hasta la quiescencia |
| `candidate_output_os_isolation_unimplemented` | **cerrada el 2026-08-20** | token de integridad Low para candidato y probe, etiqueta obligatoria Low sólo en las tres raíces escribibles y censo bidireccional remedido tras la quiescencia |

La revisión adversarial independiente de ese cierre exigió tres correcciones antes de aceptarlo, y
las tres están incorporadas:

- el censo del contenedor recorre **archivos y directorios**, no sólo directorios: la integridad
  obligatoria protege cada objeto y no se hereda del padre ya creado, así que un archivo etiquetado
  bajo un padre protegido seguiría siendo escribible por el candidato. Reparse points y hardlinks
  son condiciones rojas; la detección usa el bit `FILE_ATTRIBUTE_REPARSE_POINT` porque una junction
  —creable sin privilegios— declara `is_symlink() == False` y sí es un directorio para el
  recorrido;
- el probe de denegación ejerce cinco verbos y no tres: añade crear un archivo y sobrescribir uno
  existente, que son los accesos con los que se falsificaría un manifiesto publicado en vez de
  reemplazarlo;
- el censo tiene **cardinalidad cerrada** —tres raíces escribibles y seis protegidas— y la
  revalidación exige igualdad exacta contra el layout derivado, no mera pertenencia: sin eso, una
  evidencia que omitiera una raíz acreditaba el aislamiento con cobertura parcial.
| `multiprocess_native_pool_observer_unimplemented` | abierta | sólo el proceso raíz se auto-reporta; falta atestar cada PID/creation-time del Job |

El mecanismo aprobado para la tercera es `windows_mandatory_integrity_low_v1`. Se eligió tras medir
y descartar dos alternativas en la misma torre: un token `WRITE_RESTRICTED` con SID `RESTRICTED`
deja al hijo en `STATUS_DLL_INIT_FAILED` incluso concediendo el logon SID o reescribiendo el DACL de
`WinSta0\Default`, y crear una window station propia devuelve `ACCESS_DENIED` sin privilegios de
administrador. La integridad obligatoria no exige administrador, no toca ningún objeto compartido
del sistema y se hereda a todo descendiente del candidato.

## 13. Puertas humanas restantes

1. **Cumplida:** revisión independiente read-only de este texto.
2. **Cumplida el 2026-08-13:** OK específico de Cami sobre el texto entonces vigente.
3. **Autorizada:** implementación del arnés y sus tests/controles; todavía sin START.
4. **Autorizada:** revisión independiente del arnés y evidencia de controles negativos.
5. **Pendiente:** autorización propia para cada unidad START enumerada.
6. **Pendiente:** medición y propuesta separada de caps/geometrías/budgets/disco finales por flujo.
7. **Pendiente:** revisión independiente y OK exacto antes de convertirlos en gate o copy.

Texto comunicado y aprobado para la puerta 2:

> Apruebo `_PROPUESTA-CALIBRACION-H9R-PRE-START.md` como protocolo para implementar y revisar el
> arnés de calibración. Apruebo sus caps, geometrías, deadlines, repeticiones, reglas estadísticas,
> fronteras, schema y controles sólo como hipótesis de medición. No apruebo ningún valor final ni
> autorizo START, S0, S1 o S2; cada unidad `candidato × flujo × intento` deberá volver a mi
> autorización explícita. Tampoco autorizo hardware/cloud, metodología, API, PyPI ni demo.

### Acta de aprobación del protocolo

Cami comunicó expresamente el 2026-08-13 el texto anterior y añadió el alcance operativo de esta
sesión: integrar la aprobación en los contratos canónicos, implementar y probar únicamente el
arnés, someterlo a revisión independiente read-only y detenerse antes de cualquier START. No aprobó
ningún valor final, fixture definitivo, perfil, cap, geometría, budget o disco como contrato; tampoco
autorizó S0, S1, S2, hardware/cloud, metodología, API, workflows, PyPI, demo ni fixtures de
demostración.
