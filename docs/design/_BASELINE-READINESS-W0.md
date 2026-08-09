# Baseline W0 — readiness integral

| Campo | Valor |
|---|---|
| **Estado** | EN REVISIÓN — segunda medición pendiente; no es un gate de W1 |
| **Fecha** | 2026-08-09 |
| **Contrato** | [`SDD-30`](30-readiness-integral.md) aprobado; H9=B (`S2-equipo`) |
| **Commit medido** | `fbe1bddbfca01ffdabdaccef1f638374373f615e` |
| **Arnés** | [`scripts/measure_readiness_w0.py`](../../scripts/measure_readiness_w0.py), SHA-256 `5718c8514a0934cd9209c4b9d62688aca5452163d744e8d385eef50f52af7b15` |
| **Evidencia cruda** | Pendiente de regeneración desde el arnés corregido y un commit limpio. |
| **`uv.lock`** | SHA-256 `13534883b272fdd9a0c502a91cbe7ab63f0de43a73b6233b6a5f4dcab694b10a` |

## Veredicto W0

La primera revisión independiente devolvió `NO APROBABLE`; este documento conserva el candidato
mientras se corrige y repite el arnés. W0 **no** está cerrada todavía. El resultado no demuestra
readiness integral ni autoriza optimizaciones o capacidades W1.

- La superficie actual completó F1/UI en la geometría exacta `S0-smoke` de entrenamiento:
  10.000 filas, 25 variables y cardinalidad categórica 100, con resultados y HTML. Consumió 5,25 s
  de pared en el proceso aislado y 413,2 MiB de peak RSS; el tramo `/api/run` tardó 4,68 s.
- `data_hash` se midió como **proxy de componente**, no de flujo, en las geometrías tabulares
  S0/S1/S2. Los tres digests se repitieron idénticos. El proxy S2 1.000.000×100 consumió 1.735,1
  MiB de peak RSS y 3,78 s de pared. Esto no prueba train, batch ni temporal S2.
- Diez de doce celdas perfil×canal quedaron `no_medible`: batch/apply y temporal en S0–S2; train
  en S1/S2; UI en S1/S2. Sólo train S0 y la ruta UI S0 actual tienen medición de superficie.
- H9=B permanece intacta. El host disponible tiene 8 GiB y no representa S1 (16 GiB) ni S2
  (32 GiB); W0 no extrapola S0, no fuerza OOM y no rebaja el target.
- Los cuatro lineages de corridas reales identifican el commit medido, declaran
  `git_dirty=false` y traen `data_hash`/`config_hash`; los cuatro conservan
  `uv_lock_hash=null`. Por tanto G-LINEAGE sigue rojo aunque el arnés ancle el lock externamente.
- Los presets produjeron HTML, QMD y DOCX. No produjeron PDF en este host porque faltan las
  bibliotecas nativas de WeasyPrint. Esto es un límite del entorno medido y no verifica paridad
  visual de F-REPORT.
- H10=A permanece decidido, pero su umbral numérico sigue `no_medible`/no fijado. SDD-30 manda
  fijarlo después de W0; el upload cap actual de 100 MiB no se reutiliza como umbral de jobs.

No se modificó código de producto, schema, fixtures, demo, D-VIS-6, gains ni prosa pública. El
único código añadido es el arnés de medición W0 bajo `scripts/`.

## Entorno de referencia observado

| Dimensión | Valor medido |
|---|---|
| Hardware | Apple Silicon `arm64`, 8 cores lógicos, 8 GiB RAM |
| SO | macOS 26.5.2 |
| Python | 3.12.13 |
| Nikodym | 1.11.0 desde el checkout medido |
| Dependencias principales | NumPy 2.4.6 · pandas 2.3.3 · PyArrow 24.0.0 · scikit-learn 1.7.2 · Pydantic 2.13.4 |
| Guardas | Un proceso por probe · `PYTHONHASHSEED=0` · timeout 60–300 s · sin ejecución S1/S2 cuando el hardware no cumple |

El hardware observado no es el hardware contractual de S1/S2. Sus cifras sólo describen este
baseline local y no son copy público ni compromiso de rendimiento.

## Mediciones y proxies actuales

| Probe | Naturaleza | Dimensión | Wall | Peak RSS | Resultado |
|---|---|---:|---:|---:|---|
| `contract-census` | censo dinámico | 207 pares | 0,36 s | 105,5 MiB | 197 `disponible`, 5 `sin_efecto`, 2 `no_implementada`, 3 condicionados; sin `nikodym.apply`; UI síncrona y sin parámetros de paginación |
| `frame-hash-s0` | proxy de componente | 10.000×25; card. 100 | 0,38 s | 115,5 MiB | digest repetido `b734e325…106c7be` |
| `frame-hash-s1` | proxy de componente | 100.000×50; card. 10.000 | 0,46 s | 207,8 MiB | digest repetido `e29ba01b…cbfe9` |
| `frame-hash-s2` | proxy de componente | 1.000.000×100; card. 100.000 | 3,78 s | 1.735,1 MiB | digest repetido `4f93b222…6a8d8` |
| `preset-f1` | superficie real bajo S0 | 6.000×8 | 18,98 s | 372,2 MiB | `done`; resultados 120.190 B; HTML 250.225 B |
| `preset-f3` | superficie real bajo S0 | 6.000×17 | 5,37 s | 412,8 MiB | `done`; resultados 132.343 B; HTML 258.502 B |
| `preset-f4` | superficie real bajo S0 | 6.000×17; 5 períodos; 1 escenario | 3,48 s | 341,0 MiB | `done`; resultados 18.781 B; HTML 63.270 B |
| `score-train-s0` | superficie real exacta | 10.000 filas; 25 variables; card. 100 | 5,25 s | 413,2 MiB | `done`; resultados 187.043 B; HTML 311.092 B |

`preset-f1` incluye el coste de caché fría de fuentes en el proceso; los probes posteriores
reutilizan el cache dir temporal de esa misma ejecución W0. No se presentan sus diferencias como
comparación de algoritmos. Los tiempos de tabla son wall del proceso completo; el JSON conserva
además CPU, tramo de corrida, bytes, hashes de stdout/stderr y conteos de artefactos.

## Matriz perfil × canal

| Canal | `S0-smoke` | `S1-local` | `S2-equipo` |
|---|---|---|---|
| Train scorecard | **medido** por `score-train-s0` | `no_medible`: host 8 GiB < 16 GiB objetivo | `no_medible`: host 8 GiB < 32 GiB objetivo |
| Apply/batch | `no_medible`: no existe bundle/API targetless | igual | igual |
| Temporal forward→IFRS 9→stress | `no_medible`: no existe integración real; F4 es proxy bajo S0 | igual | igual |
| UI | **superficie S0 medida**, síncrona y sin paginación | `no_medible`: parse/spool previo, resultado completo y sin paginación | igual |

La ruta UI S0 medida no está `gateado`: acepta y ejecuta la geometría, pero no cumple todavía las
propiedades W1/W7 de paginación, rechazo temprano ni lifecycle. Medir sólo un body de 50/100 MiB
habría dado una falsa señal: el handler ve el tamaño después de que FastAPI recibió y parseó el
multipart, y el resultado se materializa completo.

## Censo flujo/gate congelado

| ID | Evidencia W0 y estado que permanece |
|---|---|
| `F-SCORE-TRAIN` | Alcanzable y medido en S0; no hay bundle completo/versionado, por lo que no está `gateado`. |
| `F-SCORE-APPLY`, `F-SCORE-BATCH` | `no_alcanzable` y `no_medible` en S0–S2: no existe API/bundle targetless ni chunking contractual. |
| `G-INFERENCE-TREATMENT` | Sin apply no puede medirse a escala; permanecen los defectos de special/missing anclados por SDD-30. |
| `G-OPTION-EFFECT` | Medido: 207 pares = 197/5/2/3. Los 5 `sin_efecto` contradicen ya el contrato aprobado y se corrigen sólo en W1. |
| `G-LINEAGE` | Medido rojo: `data_hash`/`config_hash` presentes y checkout limpio, pero `uv_lock_hash=null` en cuatro corridas. |
| `G-SCALE` | Baseline W0 parcial disponible; S1/S2 de flujo y `S3-limite` siguen sin evidencia. |
| `F-UI` | Superficie S0 medida; sync, upload 100 MiB y resultados completos; S1/S2 `no_medible`. |
| `F-LGD-BASE`, `F-EAD-BASE`, `F-CMF-REFERENCE` | Proxy F3 real de 6.000 filas bajo S0; no son clean-room ni envelope. |
| `F-LGD-OOS`, `F-EAD-T` | `no_alcanzable`/`no_medible`: no existen apply OOS persistible ni perfil EAD(t) auditable. |
| `F-PD-SURVIVAL`, `F-IFRS9` | Proxy F4 real de 6.000 operaciones, 5 períodos y 1 escenario; bajo S0 y sin forward multi-escenario. |
| `F-PD-MARKOV` | Motor experimental existente, pero el flujo segmentado requerido no tiene superficie/perfil medible. |
| `F-ROLL-VINTAGE` | Sigue condicional y `no_alcanzable`; H7=A exige addendum metodológico antes de código. No se vuelve M por inferencia. |
| `F-FORWARD-IFRS9`, `F-STRESS-ECON` | `no_alcanzable`/`no_medible`: no existe forward real→IFRS 9 real→stress sin stubs. |
| `F-PORTFOLIO-STRESS` | Excluido por H8=A; no se mide ni se presenta como entregado. |
| `F-REPORT` | HTML/QMD/DOCX observados; PDF ausente por runtime local; sin registro semántico ni gate visual/paridad. |
| `G-PUBLIC-NAV` | Baseline estático de SDD-30 permanece: módulos pares; W0 no reorganiza copy ni navegación. |
| `G-DIST-CANDIDATE`, `G-THIRD-PARTY-CANDIDATE` | Sin clean-room enumerado, promoción exacta ni acta sin checkout; no medibles como gate actual. |
| `P-PYPI-VERIFY` | PyPI sigue en 1.11.0; es evidencia post-publicación y quedó expresamente fuera de W0. |

## Reproducción y lectura correcta

Desde el commit medido, con el árbol sin tracked/untracked que alteren lineage:

```bash
.venv/bin/python scripts/measure_readiness_w0.py \
  --output docs/design/evidencia/readiness-w0-repeticion-AAAA-MM-DDTHHMMSS.json
shasum -a 256 docs/design/evidencia/readiness-w0-repeticion-AAAA-MM-DDTHHMMSS.json
```

El arnés abre la salida en modo exclusivo y falla si la ruta ya existe: una repetición usa un
nombre nuevo y se conserva como evidencia distinta. Wall/CPU/RSS y el
SHA del JSON completo pueden variar por entorno; los shapes, digests lógicos, estados, guardas y
razones `no_medible` son los oráculos reproducibles. Para comparar rendimiento se usa el JSON
nuevo y se conserva éste como baseline, nunca se edita un tiempo a mano.

## Condición de detención

W0 se detiene aquí hasta una segunda revisión independiente aprobable. No se implementó ni se
inició W1.
