# Datasets para Nikodym — qué existe, dónde está, y por qué testear con cada uno

Relevado y descargado el **2026-07-25**. Cubre: scorecard, behavioral, IFRS 9, LGD, stress
testing, Basilea, fairness, macro y Chile.

El criterio de este documento no es "acá hay datos de crédito". Es: **qué caso de prueba cubre
este dataset que ningún otro cubre**. Un dataset que no rompe nada nuevo no vale el disco.

> **Dónde vive esto ahora (2026-07-25, noche).** Este catálogo se incorporó al repo:
> la documentación se versiona en `docs/datasets/` y los datos viven en `data/externos/raw/`,
> que está vetado por `.gitignore` y **nunca** se commitea. `descargar.sh` resuelve su `raw/`
> relativo al directorio del script, así que se ejecuta desde `data/externos/`.
> El `raw/` original de 10 GB se podó a **944 MB**: se conservó lo que algún motor puede consumir
> hoy y se borró el resto, todo reponible con `./descargar.sh get`. Ver §0-bis.

| Archivo | Qué es |
|---|---|
| `README.md` | Este documento: qué existe, dónde está y por qué testear con cada dataset. |
| `catalogo.csv` | Los 42 datasets en formato máquina (módulo, url, ruta, estado, justificación). |
| `descargar.sh` | Gestor: `ls` / `get` / `rm` / `nucleo` / `espacio` / `manual` / `inventario`. |
| `INVENTARIO.md` | Qué hay en disco *ahora*. Se regenera con `./descargar.sh inventario`. |
| `HANDOFF.md` | Estado al cierre de sesión: decisiones, callejones sin salida y próximos pasos. |
| `raw/` | Los datos — **efímeros**, ver §0. |

### Mapa de `raw/`

Una carpeta por módulo de la librería, no por fuente. Lo que pesa poco va como archivo suelto;
lo que pesa va en su propia subcarpeta.

```
raw/
├── scorecard/     PD retail: hmeq, german, taiwan, lending_club*, sba, vehicle, gmsc, home_credit
├── behavioral/    berka/ (transacciones crudas), home_credit_stability/ (drift temporal)
├── ifrs9/         mortgage.csv (panel 622k) + freddiemac/ (27 vintages 1999–2025)
├── lgd/           lgd.csv (bimodal) + bondora (curvas de recuperación)
├── stress/        fed/ (escenarios 2026 + resultados DFAST) · eba/ (ST25 con IFRS9_Stages)
├── basilea/       eba_tr_*.csv — transparency exercise, 119 bancos
├── fairness/      hmda_2025_CA (1,16M con atributos protegidos), hmda_RI, adult
├── corporativo/   polish, taiwanese, ratings
├── macro/         fred_*.csv — 8 series, incluidas 3 de mora real
├── chile/         cmf_morosidad90_*.xlsx — 12 meses por institución
└── fraude/        creditcard_ulb/ — desbalance extremo
```

---

# 0-bis. Lo que este catálogo promete y el motor todavía no puede consumir

**Leer antes de planificar trabajo apoyándose en una fila de `catalogo.csv`.** El catálogo se
escribió mirando los datasets, no el código, y por eso varias justificaciones describen un caso de
prueba que hoy **ningún motor de Nikodym puede correr**. No están mal como relevamiento —el dataset
es el correcto para ese caso— pero sí como plan: el caso exige antes una capacidad que no existe.

Verificado contra el árbol el 2026-07-25, cada fila con `archivo:línea`:

| Lo que promete el catálogo | Qué dice el código |
|---|---|
| Stress end-to-end con el escenario oficial del Fed (prioridad 1) | `stress/` no lee archivos: los shocks son escalares de config (`stress/config.py:135-175`). Peor: `source="official"` —que es lo que *es* un escenario del Fed— **detiene la corrida** (`stress/config.py:948-952` y `stress/engine.py:1818-1834`). Los CSV del Fed sólo entran por `forward` como trayectoria macro. |
| EBA macro scenario como segunda jurisdicción | Es `.xlsx` y `forward` sólo acepta `.parquet`/`.csv` (`forward/step.py:871-885`). Hay que convertirlo antes. |
| `payoff_time` como riesgo competitivo (el argumento estrella de `mortgage.csv`) | No existe riesgo competitivo en la librería: `survival/config.py:61-66` define un único evento binario. El dataset sirve; el error que dice demostrar es hoy indistinguible para el motor. |
| Panel longitudinal para IFRS 9 | El motor IFRS 9 es de corte: exige unicidad de fila (`ifrs9/engine.py:600-610`) y veta el perfil longitudinal en construcción (`ifrs9/config.py:285-318`). Hay que colapsar el panel antes. |
| SBA prueba que el EL respeta mitigantes | No hay campo de garantía en el cálculo: `IfrsEadConfig` (`ifrs9/config.py:244-322`) no lo tiene, y `guarantee_treatment` es sólo un descriptor de salida (`cmf/results.py:90`). |
| HMDA para fairness / disparate impact | No hay módulo de fairness en `src/nikodym/`. |
| EBA Transparency como benchmark de densidad de RWA | No hay módulo de Basilea/RWA. |
| Lending Club rechazados, **prioridad 1**, para reject inference | No hay reject inference, y está excluido por diseño: `docs/design/02-data.md:581` cita ESPECIFICACIONES §5.2 («sin reject inference en F1»). Es la discrepancia de prioridad más grande del catálogo. |
| Berka obliga a Firth o calibración bayesiana | Ninguna de las dos existe: `model/config.py:22` y `calibration/config.py:24`. |
| Bondora: curvas de recuperación descontadas a la EIR | La LGD del motor es escalar por fila (`ifrs9/config.py:237-240`), sin flujos indexados en el tiempo. |
| «Bajar el dataset y correrlo» | `data/loading.py:97-107` sólo infiere `.csv`, `.parquet` y `.xlsx`. Los `.gz`, `.zip` y los `.txt` de Freddie Mac (delimitados por `|`) exigen declarar `file_format` y `csv_options` a mano. |

`catalogo.csv` se deja **tal cual**: es un inventario correcto de lo que existe allá afuera, y
reescribir sus prioridades con el criterio de hoy borraría información útil para cuando esas
capacidades sí existan. Esta tabla es el filtro que hay que aplicarle.

---

# 0. Cómo se usa esto: datasets efímeros

El disco es escaso; los datasets son reproducibles. **Lo permanente son estos tres archivos
(~50 KB), no los datos.** El ciclo es: bajar lo que se va a usar ahora → probar → borrar.
Si en tres meses hay que volver a validar algo, se baja de nuevo con una línea.

```bash
./descargar.sh ls                        # qué hay en disco y cuánto pesa
./descargar.sh get lending_club_reject   # baja uno (3,8 GB)
#   ... se trabaja el módulo de reject inference ...
./descargar.sh rm lending_club_reject    # se recupera el disco
./descargar.sh espacio                   # ranking de lo que ocupa
./descargar.sh manual                    # fuentes que exigen navegador o registro
```

**Núcleo permanente** (`./descargar.sh nucleo`, ~90 MB): `hmeq`, `german`, `south_german`,
`taiwan`, `credit_approval`, `australian`, `polish`, `taiwan_bank`, `ratings`, `adult`, `lgd`,
`mortgage`, `fed`, `fred`, `cmf`. Son los que van en CI y los que cubren IFRS 9, LGD y stress
end-to-end. Estos no conviene borrarlos nunca.

**Los pesados, bajo demanda.** Ordenados por lo que cuestan:

| Clave | Peso | Se baja cuando toca trabajar en… |
|---|---|---|
| `amex` | 50 GB | Behavioral con series mensuales. Hoy no cabe |
| `lending_club_reject` | 3,8 GB | Reject inference y sesgo de selección |
| `stability` | 3,1 GB | Monitoreo: PSI, CSI, drift temporal |
| `home_credit` | 2,5 GB | Feature engineering relacional con bureau |
| `lending_club` | 1,7 GB | Scorecard a escala con out-of-time |
| `freddie` | ~40 MB/vintage | IFRS 9 y LGD con volumen de venta |
| `hmda_ca` | 419 MB | Fairness y proxy discrimination |
| `eba_te` | 246 MB | Benchmark de RWA contra 119 bancos |
| `bondora` | 149 MB | Curvas de recuperación en el tiempo |
| `fraude` | 144 MB | Métricas bajo desbalance extremo |

Redundancias que conviene saber: `lending_club_reject` ya contiene los aceptados, así que tener
`lending_club` en paralelo es opcional. `hmda_ri` (15 MB) sustituye a `hmda_ca` (419 MB) para
tests rápidos de fairness.

---

# 1. Scorecard / PD retail

### `raw/scorecard/hmeq.csv` — HMEQ, 5.960 × 13
**Fuente:** [creditriskanalytics.net](http://www.creditriskanalytics.net/datasets-private2.html) (Baesens, Roesch & Scheule)
**Por qué testear con éste:** tiene ~20% de valores faltantes **por diseño**, concentrados en las
variables más predictivas (`DEBTINC`, `DEROG`, `DELINQ`). Es el caso que rompe cualquier binning
ingenuo: si tu WOE trata el missing como una categoría más sin verificar monotonía, acá se nota.
Además el missing **es informativo** (no falta al azar) — probar que tu pipeline no lo imputa a la
media y destruye señal. Chico, corre en un segundo, va en CI.

### `raw/scorecard/lending_club/` — 1,7 GB, 2007–2020Q3
**Fuente:** [Kaggle · ethon0426](https://www.kaggle.com/datasets/ethon0426/lending-club-20072020q1)
**Por qué testear con éste:** es el único de este tamaño con **fecha de originación real por
préstamo**, así que es el que permite un out-of-time honesto (entrenar ≤2016, validar 2017–2020)
en vez del split aleatorio que infla todas las métricas. Cruza la crisis de 2008 y el COVID:
si tu monitoreo de PSI/CSI no dispara alertas en 2020Q2, está mal calibrado. También trae
`grade`/`sub_grade` de Lending Club → benchmark contra un scorecard comercial real.

### `raw/scorecard/lending_club_reject/` — 3,8 GB, accepted + rejected
**Fuente:** [Kaggle · wordsforthewise](https://www.kaggle.com/datasets/wordsforthewise/lending-club)
**Por qué testear con éste:** **es el único público con las solicitudes rechazadas.** Sin
rechazados no puedes probar reject inference (parcelling, augmentation, Heckman) ni medir el
sesgo de selección — que es el error conceptual más caro de un scorecard real, porque el modelo
solo ve a quien ya fue aprobado. Si Nikodym vende un módulo de reject inference, este dataset
es la única evidencia pública que lo respalda.

### `raw/scorecard/sba_national/SBAnational.csv` — 899.164 × 27, 1987–2014
**Fuente:** [Kaggle](https://www.kaggle.com/datasets/mirbektoktogaraev/should-this-loan-be-approved-or-denied) · paper en el mismo directorio
**Por qué testear con éste:** **PD de PyME con garantía estatal parcial**, que es una estructura
que ningún dataset retail tiene: la pérdida no es el saldo, es el saldo menos la porción
garantizada. Sirve para probar que tu cálculo de EL respeta mitigantes de crédito. Cubre 27 años
y tres recesiones (1990, 2001, 2008) → es el mejor para probar estabilidad de parámetros a través
de ciclos completos. Trae industria (código NAICS) → prueba de segmentación por sector.

### `raw/scorecard/taiwan_credit_cards.zip` — 30.000 × 24
**Fuente:** [UCI 350](https://archive.ics.uci.edu/dataset/350/default+of+credit+card+clients)
**Por qué testear con éste:** trae `LIMIT_BAL` más 6 meses de saldo y de pago. Es el **test
unitario de utilización de línea y de CCF** más simple que existe: cabe en memoria, se calcula a
mano, y sirve para verificar que tu fórmula de EAD revolvente da el número correcto antes de
soltarla sobre datos grandes.

### `raw/scorecard/german_credit.zip` y `south_german_credit.zip` — 1.000 c/u
**Fuente:** [UCI 144](https://archive.ics.uci.edu/dataset/144/statlog+german+credit+data) · [UCI 522](https://archive.ics.uci.edu/dataset/522/south+german+credit)
**Por qué testear con éste:** trae una **matriz de costos asimétrica oficial (5:1 FN/FP)**. Es el
caso para probar que tu selección de punto de corte optimiza costo esperado y no accuracy.
Bajé las dos versiones a propósito: el German original tiene errores de codificación documentados
y South German los corrige — úsalos juntos para probar que tu pipeline es reproducible frente a
un cambio de diccionario de datos. Por su tamaño, son los ejemplos de la documentación.

### `raw/scorecard/vehicle_loan/` — 233k
**Fuente:** [Kaggle · L&T](https://www.kaggle.com/datasets/mamtadhaker/lt-vehicle-loan-default-prediction)
**Por qué testear con éste:** trae **bureau score externo** (CIBIL) junto a las variables propias.
Es el caso de "tengo un score comprado, ¿aporta sobre mi scorecard interno?" — prueba de
incrementalidad y de calibración de dos scores en distinta escala. Además es mercado emergente:
distribuciones más sucias que las de US.

### `raw/scorecard/credit_approval.zip` y `australian_credit.zip` — 690 c/u
**Fuente:** [UCI 27](https://archive.ics.uci.edu/dataset/27/credit+approval) · [UCI 143](https://archive.ics.uci.edu/dataset/143/statlog+australian+credit+approval)
**Por qué testear con éste:** variables completamente anonimizadas, mezcla de continuas y
categóricas sin nombres. Único uso real: **prueba de inferencia automática de tipos**. Que tu
librería decida sola qué binnear como continua y qué como categórica sin metadatos.

### Pendientes de Kaggle (ver §8)
`Give Me Some Credit` (150k, el benchmark de CI con AUC ~0,86 conocido) y
`Home Credit Default Risk` (7 tablas relacionales — el test de feature engineering con bureau
externo y agregaciones a múltiples niveles).

---

# 2. Behavioral scoring y estabilidad temporal

### `raw/behavioral/berka/` — 8 tablas, 1,05M transacciones, 682 créditos
**Fuente:** [Kaggle · Berka / PKDD'99](https://www.kaggle.com/datasets/marceloventura/the-berka-dataset)
**Por qué testear con éste:** es el único que te da **transacciones crudas de cuenta corriente**
(`trans.csv`, 1M movimientos) en vez de features ya cocinadas. Prueba el paso que casi ningún
dataset permite: construir el feature store desde el movimiento bancario — saldos promedio,
volatilidad de ingreso, días en descubierto, estacionalidad. Segundo uso, igual de importante:
**682 créditos con muy pocos defaults = low-default portfolio**. Es el caso donde la regresión
logística estándar colapsa y hay que probar corrección de Firth, priors o calibración bayesiana.

### Pendientes de Kaggle (ver §8)
`Home Credit - Model Stability` es el **único dataset del mundo diseñado para medir degradación
temporal**: su métrica oficial penaliza la caída de Gini en el tiempo, no el Gini promedio. Es el
banco de pruebas natural del módulo de monitoreo (PSI, CSI, alertas de drift).
`AMEX` (~50 GB) da 13 meses de perfil mensual por cliente — behavioral con series reales.
**No cabe en el disco actual** (quedan 20 GB).

---

# 3. IFRS 9 — el bloque más importante

### `raw/ifrs9/mortgage.csv` — 622.489 filas de panel ← **empieza por acá**
**Fuente:** [creditriskanalytics.net](http://www.creditriskanalytics.net/datasets-private2.html) — venía en un `.rar` no listado en la página; ya extraído.
**Estructura:** 50.000 hipotecas × 60 trimestres.

```
id, time, orig_time, first_time, mat_time, balance_time, LTV_time, interest_rate_time,
hpi_time, gdp_time, uer_time, REtype_CO/PU/SF_orig_time, investor_orig_time,
balance_orig_time, FICO_orig_time, LTV_orig_time, Interest_Rate_orig_time,
hpi_orig_time, default_time, payoff_time, status_time
```

**Por qué testear con éste — cuatro cosas que ningún dataset transversal permite:**

1. **PD marginal por edad del crédito.** Al estar en panel, se estima la curva de hazard
   condicional a sobrevivir hasta *t*. Sin esto no hay lifetime ECL, solo un PD a 12 meses
   extrapolado a mano.
2. **`payoff_time` — prepago como riesgo competitivo.** Un crédito que se paga anticipadamente
   no es ni bueno ni malo: sale de la cartera. Tratarlo como censura no informativa **sobrestima
   sistemáticamente el ECL lifetime**, y es donde falla la mayoría de las implementaciones que
   he visto. Este archivo permite modelarlo bien y demostrar la diferencia con un número.
3. **Macro por período incorporado** (`hpi_time`, `gdp_time`, `uer_time`): el forward-looking de
   IFRS 9 se prueba de punta a punta sin tener que enlazar fuentes externas.
4. **LTV dinámico** (`LTV_time` vs `LTV_orig_time`): permite un criterio de SICR basado en
   deterioro real de garantía, no solo en días de mora. Es el test del módulo de staging.

Con 622k filas corre en memoria en cualquier laptop. Da el ciclo IFRS 9 completo sin bajar
los ~200 GB de Freddie Mac.

### `raw/ifrs9/freddiemac/sample_YYYY.zip` — **27 vintages, 1999–2025, 1,0 GB (completo)**
**Fuente:** [Freddie Mac Clarity](https://claritydownload.fmapps.freddiemac.com/CRT/#/sflld) (cuenta creada)
**Estructura por año:** `sample_orig_YYYY.txt` (50.000 originaciones, 32 campos) +
`sample_svcg_YYYY.txt` (performance mensual; p. ej. 2020 trae 2.340.586 filas).
El muestreo de 50.000 préstamos por vintage **lo hace Freddie Mac**, no nosotros — eso lo vuelve
defendible ante un cliente sin tener que justificar un diseño muestral propio.

**Por qué testear con éste (más allá de `mortgage.csv`):**
- **Es el dato de venta.** Un banco acepta "validado sobre el universo Freddie Mac"; no acepta
  "validado sobre 50.000 observaciones de un libro de texto".
- **LGD derivable de verdad**: el archivo de servicing trae `net sales proceeds`, gastos de
  liquidación y UPB al default → LGD real, no una proxy.
- **Matriz de transición de estados de mora** (0→30→60→90→default→liquidación) construida
  loan-level, que es la que se usa en IFRS 9 — no la de ratings corporativos.
- 27 vintages permiten **vintage analysis**: comparar cosechas y detectar deterioro de
  originación, algo que un corte transversal no muestra. Las cosechas 2005–2007 son el
  caso de estudio clásico: originación relajada seguida de default masivo.
- **Cubre la crisis completa.** Sin los vintages 1999–2008 el modelo solo vería un ciclo
  benigno más COVID — demasiado suave para calibrar un escenario adverso creíble.

Con 1,0 GB para 27 años, este es el mejor ratio valor/disco de todo el catálogo. No borrar.

---

# 4. LGD y recuperaciones

### `raw/lgd/lgd.csv` — 2.545 obs, banco europeo anonimizado
**Fuente:** [creditriskanalytics.net](http://www.creditriskanalytics.net/datasets-private2.html)
**Por qué testear con éste:** es **la única LGD pública citable en un informe**. Y su valor de
prueba está en la forma de la distribución: la LGD real es **bimodal** (masa en 0 = recupero
todo, masa en 1 = no recupero nada). Eso rompe la regresión lineal — el modelo predice valores
fuera de [0,1] y el error no es normal. Es el caso que obliga a implementar bien regresión beta,
transformación logit o modelos de dos etapas. Con 2.545 obs cabe en un test.

### `raw/lgd/bondora_loan_dataset.xlsx` — 160 MB, P2P europeo 2009–hoy
**Fuente:** [Bondora public statistics](https://www.bondora.com/en/public-statistics/) (descarga directa, sin registro)
**Por qué testear con éste:** trae `PrincipalRecovery` y `RecoveryStage` **con fechas**, o sea
permite construir **curvas de recuperación en el tiempo** en vez de una LGD puntual. Es lo que
necesitas para probar el descuento de flujos de recuperación a la tasa efectiva original — el
requisito de IFRS 9 que casi nadie implementa bien. Ojo: es cobranza P2P, plazos y tasas de
recupero no son extrapolables a banca; sirve para probar la mecánica, no para calibrar.

### El hoyo, dicho sin rodeos
No existe LGD pública con muestra grande ni EAD/CCF corporativo abierto. Los papers del área
usan datos propietarios. Para vender módulo LGD hay dos caminos: derivarla de Freddie Mac
(`net sales proceeds` − gastos vs UPB al default) o construirla con el primer cliente.

---

# 5. Stress testing

### `raw/stress/fed/` — escenarios oficiales del Fed
**Fuente:** [Federal Reserve](https://www.federalreserve.gov/publications/files/2026-final-supervisory-stress-test-scenarios-20260204.pdf) · CSV en `supervisionreg/files`
**Contenido:** 18 variables domésticas (PIB real y nominal, desempleo, CPI, tasas 3M/5A/10A,
BBB corporate yield, mortgage rate, prime, Dow Jones, **House Price Index**, CRE Price Index,
VIX) + internacionales, 13 trimestres, en tres escenarios: baseline, adverse y severely adverse.
**Por qué testear con éste:** son los escenarios **regulatorios reales de 2026**, no inventados.
El House Price Index y el desempleo enlazan directo con `mortgage.csv` (§3), así que se puede
correr el stress de punta a punta: escenario → PD condicionada → ECL proyectado. Que el resultado
sea defendible ante un regulador depende de usar el escenario oficial, no uno propio.

### `raw/stress/fed/fed_public_results_DFAST_2026.csv` — 188 KB
**Por qué testear con éste:** son los **resultados publicados banco por banco** del ejercicio
2026. Es el ground truth: corres tu modelo sobre el escenario severely adverse y comparas tu
pérdida proyectada contra lo que reportó la industria. Sin esto tu stress test no tiene contra
qué validarse.

### `raw/stress/eba/TRA_CRE_IRB` y `TRA_CRE_STA` — 60 + 80 MB
**Fuente:** [EBA EU-wide stress test 2025](https://www.eba.europa.eu/eu-wide-stress-test-2025), base completa
**Columnas:** `Country_code, LEI_Code, Bank_name, Period, Item, Scenario, Portfolio,`
**`IFRS9_Stages`**`, Exposure, Country, Country_rank, Perf_status, Amount`
**Por qué testear con éste:** trae exposiciones **por banco, por escenario, por cartera y por
stage IFRS 9**, separadas en método IRB y estándar. Es el único lugar donde puedes verificar si
tu migración de stages bajo escenario adverso se parece a lo que reportaron 64 bancos europeos
reales. Si tu modelo manda el 40% de la cartera a stage 2 y la industria reportó 12%, tu
criterio de SICR está mal — y esto te lo dice antes que el cliente.

### `raw/stress/eba/eba_st25_macro_scenario.xlsx`
Escenario macro EBA por país. Segunda jurisdicción → prueba de que tu motor no está hardcodeado
a variables del Fed.

---

# 6. Basilea / RWA

### `raw/basilea/eba_tr_cre.csv` — 128 MB (+ `tr_sov`, `tr_oth`, `tr_mrk`)
**Fuente:** [EBA Transparency Exercise 2025](https://www.eba.europa.eu/eu-wide-transparency-exercise-0) — 119 bancos, 25 países, 4 fechas (sep-24 a jun-25)
**Por qué testear con éste — y qué NO es:** esto **no es un dataset de entrenamiento**. Para
Basilea no existe tal cosa: el RWA IRB se calcula aplicando las fórmulas del BCBS sobre tus
propios PD/LGD/EAD. Lo que este archivo te da es el **benchmark de razonabilidad**: densidad de
RWA, PD y LGD promedio por cartera y por banco, sobre datos COREP/FINREP reales.

Es lo que responde la pregunta que un cliente sí va a hacer: *"tu modelo me da una densidad de
RWA de 45% en cartera comercial, ¿eso está bien?"*. Con esto contestas "el rango de los 119
bancos europeos es X–Y, estás en el percentil Z". Sin esto, tu número no tiene contra qué
compararse. `eba_SDD.xlsx` y `eba_TR_Metadata.xlsx` son los diccionarios para interpretarlo.

---

# 7. Validación, fairness y macro

### `raw/fairness/hmda_2025_CA.csv` — 1.161.293 solicitudes, 433 MB
**Fuente:** [FFIEC / CFPB data browser](https://ffiec.cfpb.gov/data-publication/modified-lar) (sin registro; California 2025)
**Por qué testear con éste:** es **el único dataset del mundo con atributos protegidos y decisión
de crédito real** — `derived_race`, `derived_ethnicity`, `derived_sex`, edad, junto a
`action_taken` y `denial_reason`. Todo lo demás que se usa para fairness (Adult, COMPAS) no es
crediticio.

Con esto se prueban de verdad: disparate impact ratio, equal opportunity difference, y sobre todo
**proxy discrimination** — que tu scorecard no discrimine indirectamente vía código postal o
tipo de propiedad aunque no use raza como variable. Si Nikodym va a vender validación de modelos
a un banco chileno, esto es el diferenciador: nadie más lo tiene testeado.
`raw/fairness/hmda_2024_RI_muestra.csv` (42k) es la versión chica para tests rápidos.

### `raw/macro/fred_*.csv` — 8 series
**Fuente:** [FRED](https://fred.stlouisfed.org) (CSV directo, sin API key)
`UNRATE` (desempleo), `CSUSHPINSA` (precios vivienda), `GDPC1` (PIB real), `FEDFUNDS`, `CPIAUCSL`,
y las tres claves de crédito: `DRSFRMACBS` (mora hipotecaria), `DRCCLACBS` (mora tarjetas),
`DRALACBS` (mora total del sistema).
**Por qué testear con éste:** las tres series de mora son el **backtesting del forward-looking**.
Tu modelo proyecta una tasa de default agregada bajo un escenario macro; estas series te dicen
qué pasó de verdad. Es la única forma de validar que el enlace macro→PD no es decorativo.

### `raw/fairness/adult_census.zip` — 48.842
Test unitario de las métricas de equidad (los valores esperados están publicados en la
literatura). No es crediticio: sirve para verificar la implementación, no para concluir.

### `raw/fraude/creditcard_ulb/creditcard.csv` — 284.807, 0,17% de positivos
**Por qué testear con éste:** desbalance extremo (1 en 578). Es el caso límite del módulo de
métricas: AUC-ROC se ve excelente y es engañoso; hay que usar AUC-PR. Prueba que tus métricas
no mienten cuando la clase positiva es rarísima — situación real en carteras de bajo default.

---

# 8. Chile

### `raw/chile/cmf_morosidad90_*.xlsx` — 12 meses, jun-2025 a may-2026
**Fuente:** [CMF](https://www.cmfchile.cl/portal/estadisticas/626/w4-propertyvalue-28914.html) — "Indicadores de riesgo de crédito, cartera con morosidad de 90 días o más (individual)"
**Por qué testear con éste:** es **la única referencia local**. Trae mora 90+ **por institución**
y por cartera (comercial, consumo, vivienda), mensual, con los códigos de cuenta del Manual del
Sistema de Información. Dos usos concretos de venta:
1. **Calibrar la matriz estándar de la Circular 3.573** — el modelo estándar chileno de
   provisiones se ancla en estos niveles.
2. **Benchmark contra el cliente**: cuando un banco chileno te contrate, lo primero que va a
   preguntar es cómo se compara con el sistema. Esto lo contesta.

Es agregado, no loan-level — no sirve para entrenar, sirve para calibrar y comparar.

**Nota sobre el portal:** la página "Datos Abiertos" de la CMF está vacía (solo navegación, sin
archivos). Los datos reales están dispersos en las páginas de estadísticas, con URLs del tipo
`articles-NNNNNN_recurso_1.xlsx` que no se descubren desde el HTML. El `descargar.sh` ya trae
las 12 URLs resueltas.

### Falta: Encuesta Financiera de Hogares (§9)
[EFH 2024](https://www.bcentral.cl/areas/encuestas-economicas/encuesta-financiera-de-hogares) del
Banco Central, 4.649 hogares. **Es lo más cercano a microdatos crediticios chilenos que existe**
— deuda por tipo, carga financiera, ingreso. Requiere registro en efhweb.cl.

---

# 9. Lo que falta y por qué

### Resuelto: Kaggle
Las tres competencias quedaron aceptadas y descargadas el 2026-07-25, después de que Cami
verificara la cuenta por SMS. `~/.kaggle/access_token` (CLI 2.2.4, OAuth) autentica bien; el
`kaggle.json` viejo ya no se usa.

### Pendiente: vintages 1999–2008 de Freddie Mac
Chrome bloquea las descargas múltiples del sitio después de cierto número — los clics se disparan
pero el archivo no baja. Se necesita autorizar descargas múltiples para
`claritydownload.fmapps.freddiemac.com` (ícono de bloqueo en la barra de direcciones) y volver a
disparar los 10 años faltantes. Son los vintages de la crisis: **la cola de default está ahí**,
sin ellos el modelo solo ve un ciclo benigno más COVID.

### Requieren que crees cuenta (no puedo crear cuentas)

| Plataforma | Qué desbloquea | Urgencia |
|---|---|---|
| [efhweb.cl](https://www.efhweb.cl) | Único microdato de deuda de hogares chilenos | Media |
| [Fannie Mae](https://loanperformancedata.fanniemae.com/lppub/index.html) | Validación out-of-sample cruzada contra Freddie | Baja |
| [S&P Global](https://www.spglobal.com/ratings) | Matrices de transición 1981–2025 (vienen en PDF) | Solo si haces rating corporativo |

### Omitido por espacio
`AMEX Default Prediction` pesa ~50 GB y quedan **20 GB libres** (disco al 90%). Si liberas
espacio: `AMEX=1 bash descargar.sh kaggle`. Alternativa: hay versiones parquet de la comunidad
de 3–10 GB con el mismo esquema.

### No existe públicamente
- **EAD/CCF corporativo** — ningún dataset abierto de líneas comprometidas.
- **LGD con muestra grande** — solo los 2.545 registros de Baesens.
- **Loan-level chileno** — no existe. La EFH es encuesta, no registro administrativo.
- **Matrices de transición en formato máquina** — S&P y Moody's publican en PDF. Tipearlas una
  vez y versionarlas en el repo.

---

# Orden de ataque sugerido

| # | Archivo | Qué desbloquea |
|---|---|---|
| 1 | `ifrs9/mortgage.csv` | El ciclo IFRS 9 completo, hoy, sin dependencias |
| 2 | `scorecard/hmeq.csv` + `german_credit` | Los tests de CI: binning, missings, punto de corte |
| 3 | `stress/fed_2026_*.csv` + `mortgage.csv` | Stress testing end-to-end con escenario oficial |
| 4 | `basilea/eba_tr_cre.csv` | Que tus RWA tengan contra qué compararse |
| 5 | `scorecard/lending_club*` | Scorecard a escala + reject inference |
| 6 | `fairness/hmda_2025_CA.csv` | El diferenciador comercial |
| 7 | `chile/cmf_*` | Aterrizar a la Circular 3.573 |
