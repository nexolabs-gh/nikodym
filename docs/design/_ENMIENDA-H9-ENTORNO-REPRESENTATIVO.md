# Enmienda propuesta — entorno objetivo representativo para recalibrar H9

> **Estado: BORRADOR PARA APROBACIÓN; NO VIGENTE.** Cami autorizó el 2026-08-12 diseñar esta
> enmienda y retiró la autorización operativa pendiente de `S2-equipo`; no autorizó implementar ni
> ejecutar una calibración. Hasta que apruebe el texto final,
> [`DECISIONES-VIGENTES.md`](DECISIONES-VIGENTES.md) sigue describiendo H9=B como el contrato
> histórico aprobado, pero **no queda ningún START S2 autorizado**.
>
> Esta propuesta enmienda únicamente la dirección de H9 y las consecuencias operativas de escala de
> [`SDD-30`](30-readiness-integral.md). No cambia H1–H8, H10, H11, fórmulas, metodología de riesgo,
> API pública, candidato de distribución ni hardware/cloud. Decisiones propuestas:
> **D-RDY-H9R-1…8**.

## TL;DR y recomendación ejecutiva

Retirar H9=B/`S2-equipo` como puerta futura de readiness y dirigir su reemplazo a un entorno objetivo
de **hasta 4 CPU lógicas y una máquina de 8 GB nominales**, declarado por Cami como representativo
del usuario que Nikodym debe servir. La torre disponible puede usarse para calibrar sólo si el árbol
queda efectivamente confinado y el supervisor demuestra el límite antes de cada START.

Esta enmienda **no inventa** todavía un cap de memoria, geometrías, budgets ni reserva de disco. La
evidencia existente no permite fijarlos. Esos valores se medirán por flujo, cuando cada oleada sea
alcanzable, y volverán a Cami como una decisión exacta antes de convertirse en gate o código. Así se
elimina ahora la barrera de infraestructura sin reemplazarla por un verde de papel.

## 1. Premisa de producto y problema observado

Cami fijó una restricción de producto: el entorno objetivo debe representar equipos pequeños o
cloud comparables de la banca que Nikodym busca servir; la referencia de diseño es 4 CPU lógicas y
8 GB nominales. Es una decisión de posicionamiento, no un censo de mercado ni una afirmación de
capacidad ya entregada.

La puerta H9=B exigía 16 CPU lógicas, 32 GiB utilizables y 60 GiB libres. El único host accesible
quedó fuera por cuatro CPU y por apenas **89.092.096 B** de memoria visible, aunque era una máquina
nominal de 32 GB. Repetir preflights no podía producir evidencia nueva: el gate había pasado a medir
acceso a infraestructura, no la capacidad del producto.

La corrección no consiste en declarar que Nikodym ya funciona en 8 GB. Consiste en convertir el
entorno objetivo en una condición falsable, calibrar el gate contra ella y dejar rojo lo que todavía
no quepa o no termine.

## 2. Evidencia existente y límite de la inferencia

| Evidencia identificada | Medición | Lectura válida |
|---|---:|---|
| W0: [`readiness-w0-2026-08-09.json`](evidencia/readiness-w0-2026-08-09.json), SHA-256 `757c55ef3d8274ca44232eb03943f6fd04e26d5a568774bcdbef025933e092ab` | host Apple Silicon 8 GiB; train S0 10.000×25: 431.226.880 B peak RSS y 5,22 s | Smoke funciona; no prueba un flujo productivo nuevo |
| W0, proxy tabular S2 del mismo JSON | 1.000.000×100: 1.843.167.232 B peak RSS y 3,79 s | El hashing por bloques no exige por sí solo 32 GiB; es sólo proxy |
| S2 diagnóstico `readiness-w1-s2-2026-08-11-171025-4fa2ea45a5d1-136db945-diagnostic.json`, SHA-256 `36f9a1222f18b85d78226e256ad166b83bd01ce5bd12d165f297bedded63b3d8` | bundle observado a 521,765 s; batch 4,49 M/5 M antes del timeout | Train completó y batch avanzó; S2 quedó **NO PASS** |
| Telemetría S2 `…-job-telemetry.json`, SHA-256 `cd3e2fe7cc1b4635fe8ac20b6a19819b2a0e5fed3a4163e759e0d76367367d96` | 20.677.672.960 B peak job commit; driver 18.413.268.992 B peak working set | El peak incluye preparación, materialización, train y driver; no es consumo aislado de batch |
| Muestras S2 `…-job-samples.jsonl`, SHA-256 `0d9b59aabb0ffa4534ef989ae92aa6d707dbafe127160707a68f6c639dbf648d` | durante batch: árbol 8.491.941.888 B private y 5.435.867.136 B working set; consumidor individual 3.440.906.240 B peak working set | El proceso individual no justifica un cap job-wide de 5 GiB |
| Benchmark `w1-batch-benchmark-2026-08-11-4fa2ea45.json`, SHA-256 `fb9df49e52670a7224870de28e7ab919f0cd09a14b47369039a3044088607ad2` | chunk 10.000×100: p75 steady 3,125 s; proyección no contractual 1.562,55 s para 500 chunks | El hotspot es repetible; no fija tiempo con 4 CPU ni otra geometría |

Los nombres abreviados `…` comparten el prefijo completo de la primera fila S2; los manifiestos
privados conservan las rutas y hashes íntegros. Nada de esta tabla demuestra un cap, una geometría
o un budget productivo en 4 CPU/8 GB.

## 3. Decisiones propuestas

### D-RDY-H9R-1 — S2 deja de gobernar el trabajo futuro

Al aprobarse esta enmienda:

- H9=B/`S2-equipo` se retira como puerta futura de readiness;
- S0, S1 y S2 se conservan con sus nombres, artefactos y conclusiones históricas;
- la autorización S2 `0/1`, retirada operacionalmente el 2026-08-12, no puede revivirse por relevo;
- no se ejecuta otro S2 por compatibilidad, comparación ni “una última prueba”;
- un stress futuro por encima del entorno objetivo requerirá alcance y autorización propios y no
  bloqueará readiness de ese entorno.

Retirar H9=B no otorga PASS: H9 queda **en recalibración** hasta que un perfil exacto, medido y
aprobado lo sustituya.

### D-RDY-H9R-2 — Se fija el entorno objetivo, no una promesa de rendimiento

El reemplazo de H9 se diseña para:

| Dimensión | Decisión de dirección |
|---|---|
| CPU | como máximo 4 CPU lógicas efectivamente utilizables por raíz, descendientes y pools nativos |
| Memoria del equipo | clase nominal de 8 GB; no comparación byte-exacta de RAM visible |
| Plataforma inicial del gate | Windows, porque el supervisor Job Object existente y la torre disponible permiten evidencia reproducible |
| Host mayor | elegible para calibración sólo si demuestra confinamiento efectivo antes de START |

La CPU se limitará con afinidad o CPU Sets efectivos, heredados y verificados en cada descendiente;
el Job Object de memoria no prueba por sí solo el límite de CPU. La evidencia registrará modelo de
CPU, esquema de energía, RAM física/visible y censo de pools/hilos. Un control negativo intentará
ampliar la máscara desde un hijo y deberá quedar rojo.

Los tiempos obtenidos serán válidos para el host y la configuración atestiguados. Extender el gate
a macOS/Linux exigirá semánticas equivalentes explícitas; no se inferirá portabilidad desde Windows.

### D-RDY-H9R-3 — El cap y los perfiles salen de calibración, no de intuición

Una propuesta de calibración posterior deberá preespecificar, antes de cualquier START:

1. la escalera de caps job-wide que representa la memoria utilizable por Nikodym en una máquina de
   8 GB nominales, con unidades y reserva del sistema explícitas;
2. los fixtures candidatos por flujo, su seed, schema, bytes, filas, dimensionalidad y SHA-256;
3. geometrías N−1/N/N+1 y criterio de selección sin rebajar un rojo en silencio;
4. deadlines externos de seguridad para terminar el árbol sin agotar el host, más el número de
   repeticiones y la política estadística que después derivarán los budgets; esos deadlines no son
   promesas de rendimiento ni budgets candidatos;
5. bytes reales conocidos del fixture, instrumentación para censar temporales/salidas y la regla
   que, después de medirlos, derivará la fórmula y el factor de seguridad de disco;
6. schema de evidencia, clasificación de timeout/cap/error y controles negativos.

Los antiguos 5 GiB, 10 GiB, `25.000×60×3` y budgets 1.800/1.800/2.700 s quedan expresamente
**descartados como contrato**: fueron hipótesis no medidas del primer borrador. Lo mismo vale para
cualquier geometría propuesta hasta que la calibración y el OK humano la conviertan en gate.

### D-RDY-H9R-4 — El envelope se aplica por flujo y por oleada

No existe una corrida monolítica “E8” que anticipe W1–W5. El envelope transversal de recursos se
aplica a cada flujo cuando la oleada lo vuelve alcanzable:

| Oleada | Flujo que puede calibrar/gatear | Salida propia |
|---|---|---|
| W1 | scoring train y score/apply/batch; baseline UI por separado | bundle; `application`, `woe`, `trace`; manifiesto de scoring |
| W2 | LGD/EAD y demás capacidades que W2 haga alcanzables | contratos y salidas propios del flujo |
| W3–W5 | temporal, IFRS 9/ECL, forward-looking y stress según sus dependencias | detalle, resúmenes y reconciliaciones propios; no vistas WoE heredadas |

Cada flujo recibe geometría, budget, disco, outputs y controles propios. Las tres vistas
`application`/`woe`/`trace` pertenecen sólo a scoring. W1 no puede fallar ni pasar por un temporal
todavía inalcanzable.

H10=A no cambia: el baseline UI debe medir el umbral de job y elevar esa cifra en una decisión
separada; ni el tamaño del archivo ni un tiempo propuesto lo fijan de rebote.

### D-RDY-H9R-5 — Un START es una unidad fresca y auditable

La unidad mínima será `candidato × flujo × intento`. Cada START requiere árbol fresco, autorización
propia, fixture y artefactos congelados, preflight verde y atestación anterior al primer byte de
trabajo. No se comparten procesos, caches mutables ni estado retenido entre train, batch y temporal.

Fronteras mínimas:

- **train:** apertura y parseo del input → bundle, hashes, lineage y publicación atómica;
- **batch:** load del bundle + apertura y parseo del input → outputs y manifiesto propios;
- **temporal:** apertura y parseo de todos los inputs → detalle, resúmenes, reconciliaciones y
  manifiesto propios.

El fixture sintético se genera y firma antes del START porque el usuario parte de un archivo
existente. Toda lectura, parseo, validación, cálculo, hash, lineage, flush y publicación del
consumidor queda dentro. Mover la lectura afuera da un verde falso; generar dentro mide el arnés y
no sólo el producto.

### D-RDY-H9R-6 — Invariantes comunes y atomicidad permanecen congelados

Todo perfil final deberá conservar, cuando aplique al flujo:

- identidades y orden estables, completitud bidireccional y reconciliación de conteos;
- hashes de input, candidato, configuración, entorno y outputs;
- lineage de SDD-30 y semántica de warning vigente;
- publicación atómica: ante timeout, cancelación, cap, error o proceso huérfano no existe manifiesto
  final publicable;
- censo de raíz, descendientes, pools nativos, temporales y artefactos al cierre.

La propuesta de calibración debe describir el oráculo rojo→verde de cada invariante antes de
ejecutarlo. Un conteo fijo sin censo en ambos sentidos no prueba completitud.

### D-RDY-H9R-7 — W0 no se reescribe y W1 no obtiene PASS automático

W0 continúa CERRADA/PASS como medición histórica del contrato que regía el 2026-08-09. Sus JSON,
hashes y conclusiones no cambian.

Tras aprobar esta enmienda, W1 deja de estar bloqueada por conseguir un runner H9=B, pero permanece
**NO PASS / bloqueada por recalibración de H9**. Primero se aprueba la propuesta de calibración;
después se mide el candidato sin optimizaciones nuevas; sólo un rojo medido puede justificar una
propuesta de implementación. Un perfil exacto y su PASS requieren sus propias revisiones y OK.

### D-RDY-H9R-8 — El copy público nace después de evidencia gateada

Antes del PASS no se publican “4 CPU”, “8 GB”, geometrías ni tiempos como capacidad entregada. La
documentación de diseño puede declarar el entorno objetivo; README, `docs_site`, landing, metadata,
tooltips, backend, panel e informes sólo publican mediciones verificadas y sus condiciones.

La calibración o un PASS no autorizan PyPI, recaptura de demo, hardware/cloud ni cambios de
metodología, contrato de riesgo o API.

## 4. Gates mínimos de la futura propuesta de calibración

| Gate | PASS futuro | Control negativo requerido |
|---|---|---|
| Preflight | recursos, fixture, candidato y autorización atestiguados antes de START | intentar START antes de aplicar el envelope |
| CPU | raíz, descendientes y pools no usan más de 4 CPU | hijo intenta ampliar afinidad/CPU Set |
| Memoria | árbol completo respeta cada cap de calibración y clasifica su terminación | copia controlada rebasa el cap sin provocar OOM del host |
| Frontera | generación fuera; toda apertura/lectura y salida dentro | mover lectura afuera o generación adentro |
| Flujo | geometría, outputs y reconciliaciones propias completas | pérdida/duplicación o cruce de identidad |
| Atomicidad | manifiesto sólo tras completar y hashear todo | terminar entre chunks y exigir ausencia de manifiesto |
| Disco | fórmula medida falla antes de trabajo pesado | declarar espacio insuficiente y observar cero START |
| Copy | sin promesa pública anterior al PASS | inyectar el target en una superficie pública y detectarlo |

Esta tabla especifica oráculos, no caps, geometrías ni budgets finales. La siguiente propuesta podrá
preespecificar únicamente las escaleras de caps/geometrías, deadlines de seguridad y regla de
selección de la calibración. Los valores que gobernarán readiness sólo podrán aparecer después de
medir, con trazabilidad, revisión independiente y decisión humana exacta.

## 5. Secuencia autorizable después del OK

La aprobación final de este texto autorizará **actualizar la dirección contractual y redactar la
propuesta de calibración**, no programar ni ejecutar:

1. integrar D-RDY-H9R-1…8 en SDD-30 y `DECISIONES-VIGENTES.md`;
2. redactar caps candidatos, fixtures por flujo, fronteras, schema, protocolo de medición de disco
   —incluido un piso de seguridad no contractual— y oráculos;
3. revisión independiente read-only y OK de Cami sobre esa propuesta exacta;
4. recién entonces implementar el arnés de calibración;
5. obtener otra autorización explícita para cada unidad START definida;
6. medir sin reinterpretar los deadlines de seguridad como budgets;
7. proponer caps, geometrías, budgets y disco finales por flujo a partir de esas mediciones;
8. someter cada gate final a revisión independiente y OK de Cami antes de convertirlo en contrato.

No se compra ni provisiona hardware/cloud, no se modifica un workflow, no se publica PyPI y no se
recaptura la demo como consecuencia de esta enmienda.

## 6. Texto exacto de aprobación solicitado

> Apruebo D-RDY-H9R-1…8 como decisión de dirección: retiro H9=B/`S2-equipo` como puerta futura de
> readiness y fijo 4 CPU lógicas/8 GB nominales como entorno objetivo declarado. La autorización S2
> `0/1` queda cancelada y no puede revivirse. No apruebo todavía cap de memoria, geometrías,
> budgets, disco ni perfiles finales: deben medirse por flujo y oleada, someterse a revisión
> independiente y volver a mi aprobación. Este OK autoriza actualizar los contratos canónicos y
> redactar la propuesta de calibración; no autoriza programar, ejecutar START, provisionar
> infraestructura, publicar PyPI ni recapturar la demo.
