# Glosario regulatorio

Definiciones cortas y precisas de los términos de riesgo de crédito que aparecen en Nikodym y en
su marco normativo. Los términos están agrupados por función: **parámetros de riesgo**,
**construcción del scorecard**, **métricas de desempeño y estabilidad** y **marco normativo y
gobernanza**. Dentro de cada grupo el orden es alfabético.

!!! note "Convención de nombres CMF ↔ internacional"
    La CMF (ex SBIF) nombra los parámetros en español; la literatura y la API usan las siglas
    inglesas. Nikodym trata **CMF regulatorio** e **IFRS 9 / ECL** como dos motores separados
    (la provisión contable es el máximo entre ambos, piso prudencial). Equivalencias:

    | Internacional | CMF (Capítulo B-1 del CNC) | Rol |
    |---|---|---|
    | PD | PI — Probabilidad de Incumplimiento | probabilidad de que el deudor caiga en default |
    | LGD | PDI — Pérdida dado el Incumplimiento | fracción de la exposición que se pierde si hay default |
    | EAD | E — Exposición | monto expuesto al momento del incumplimiento |
    | EL | PE — Pérdida Esperada | `PE = PI × PDI / 100` (base mínima prudencial) |
    | CCF | Factor de conversión (Capítulo B-3) | convierte el monto contingente en exposición |

---

## Parámetros de riesgo de crédito

Son los tres factores de la pérdida esperada: `EL = PD × LGD × EAD`. Cada uno es a la vez un
insumo del modelo y una salida regulatoria.

### EAD — *Exposure at Default* (Exposición al incumplimiento)

Monto que el banco tiene efectivamente expuesto en el instante del default. En CMF es la
**Exposición `E`**. Para un crédito **contingente** (líneas no giradas, avales, boletas de
garantía) la exposición se obtiene aplicando un **factor de conversión (CCF)** del Capítulo B-3 al
monto contingente. Regla dura de la norma: para un deudor **en incumplimiento**, el CCF se fuerza
a **100 %** cualquiera sea el tipo de contingente.

### LGD — *Loss Given Default* (Pérdida dado el incumplimiento)

Fracción de la exposición que no se recupera tras el default, neta de garantías y recuperaciones
(`LGD = 1 − tasa de recuperación`). En CMF es la **PDI**, tabulada por segmento y colateral: por
ejemplo, la matriz comercial individual va de **PDI 82,5 %** (categoría A2) a **97,5 %** (B3–B4).
Garantías reales, financieras y avales la reducen vía las relaciones PVG/PVB/PTVG o por sustitución
de la calidad crediticia del avalista.

### PD — *Probability of Default* (Probabilidad de incumplimiento)

Probabilidad de que el deudor caiga en default en un horizonte dado (típicamente 12 meses). En
CMF es la **PI**. Es la variable objetivo del scorecard de comportamiento (F1): el modelo estima
una PD por deudor que luego se **calibra** a un ancla de negocio. Las tablas CMF fijan PI por
categoría y mora, p. ej. comercial individual A1 = **PI 0,04 %**, y **PI = 100 %** para cartera en
incumplimiento.

### TTC vs PIT — *Through-the-Cycle* vs *Point-in-Time*

Dos regímenes para expresar la PD:

- **PIT (point-in-time):** refleja las condiciones **actuales** del ciclo; sube en recesión y baja
  en expansión. Es el régimen natural de IFRS 9 (ECL sensible al ciclo).
- **TTC (through-the-cycle):** promedia el ciclo económico y es **estable** en el tiempo; es el
  régimen típico de un scorecard regulatorio y del ancla de provisiones.

En Nikodym el paso de **calibración** ajusta la PD cruda a un ancla; en la *corrida de ejemplo* el
ancla es **through-the-cycle** con `target_pd = 0,20`, distinto de la tasa de default observada en
desarrollo (**0,233**), justamente para no arrastrar el punto del ciclo de la muestra.

---

## Construcción del scorecard

### IV — *Information Value*

Medida global del poder predictivo de una variable, agregando el WoE de todos sus bins ponderado
por la diferencia de distribuciones de buenos y malos. Convención de industria para leer la
magnitud:

| IV | Poder predictivo |
|---|---|
| < 0,02 | sin poder (candidata a descartar) |
| 0,02 – 0,10 | débil |
| 0,10 – 0,30 | medio |
| 0,30 – 0,50 | fuerte |
| > 0,50 | sospechoso (posible *leakage*, revisar) |

Nikodym calcula el IV por variable en el paso de **binning** y lo usa como filtro en la
**selección**. En la *corrida de ejemplo*, `ingreso_mensual` es la más informativa (**IV 0,305**),
`deuda_ingreso` queda en rango medio (**IV 0,164**) y `segmento` prácticamente no discrimina
(**IV 0,003**).

### PDO — *Points to Double the Odds*

Parámetro de la escala del scorecard: número de puntos que hay que sumar para **duplicar los
odds** de ser buen pagador. Junto con un puntaje ancla (`target_score`) y sus odds
(`target_odds`) define la transformación lineal `score = offset + factor × ln(odds)`. Es una
convención de presentación, no altera el ranking ni la PD. En la *corrida de ejemplo* la escala es
**PDO 20**, `target_score = 600` y `target_odds = 50`.

### Scorecard

Tabla que traduce los coeficientes de la regresión logística en **puntajes enteros** por bin de
cada variable. El puntaje total del deudor es la suma de los puntos de sus bins más un offset. Es
la forma auditable y desplegable del modelo: cada punto tiene trazabilidad hacia un WoE y un
coeficiente. Es el artefacto central del pipeline F1, accesible como
`study.artifacts.get("scorecard", "scorecard")`.

### WoE — *Weight of Evidence*

Transformación de cada bin de una variable en `ln(%buenos / %malos)`. Linealiza la relación con el
log-odds (lo que la regresión logística espera), maneja no-linealidades y valores faltantes como un
bin más, y hace comparables variables de distinta naturaleza. Nikodym lo calcula con **OptBinning**
imponiendo **monotonía** controlada, de modo que el WoE crezca o decrezca de forma coherente con el
riesgo a lo largo de los bins.

---

## Métricas de desempeño y estabilidad

Se calculan por partición (desarrollo / *holdout* / *out-of-time*). En la *corrida de ejemplo* la
discriminación cae de desarrollo a OOT, como es esperable fuera de muestra y en el tiempo.

### AUC — *Area Under the ROC Curve*

Área bajo la curva ROC: probabilidad de que el modelo asigne más riesgo a un malo que a un bueno
tomados al azar. **0,5** = azar, **1,0** = perfecto. Se relaciona con el Gini por
`Gini = 2 × AUC − 1`. En la *corrida de ejemplo*: **0,712** en desarrollo, **0,695** en holdout y
**0,656** en OOT.

### CSI — *Characteristic Stability Index*

El mismo cálculo del PSI pero aplicado a la **distribución de cada variable** (no del score final),
para localizar **qué** característica está migrando entre poblaciones. Diagnostica el origen de un
PSI alto: si una variable concentra el desplazamiento, el CSI lo señala. Nikodym lo reporta en el
dominio `stability` junto con la peor variable y su valor.

### Gini — *Coeficiente de Gini*

Reescalado del AUC al rango 0–1 (`Gini = 2 × AUC − 1`): **0** = azar, **1** = perfecto. Es la
medida de discriminación más citada en scorecards de crédito. En la *corrida de ejemplo*: **0,425**
en desarrollo, bajando a **0,312** en OOT (consistente con los AUC anteriores).

### KS — *Kolmogorov–Smirnov*

Máxima separación entre las distribuciones acumuladas de score de buenos y malos; captura el punto
de corte donde el modelo mejor separa las poblaciones. Rango 0–1 (a veces expresado en %). En la
*corrida de ejemplo*: **0,320** en desarrollo y **0,252** en OOT.

### PSI — *Population Stability Index*

Mide cuánto se ha desplazado la distribución del **score** entre dos poblaciones (p. ej. desarrollo
vs. una ventana posterior). Convención de industria para leer la magnitud:

| PSI | Interpretación |
|---|---|
| < 0,10 | estable |
| 0,10 – 0,25 | desplazamiento moderado (vigilar) |
| > 0,25 | desplazamiento significativo (revisar / recalibrar) |

En la *corrida de ejemplo* el score es estable: **PSI 0,013** (desarrollo vs. holdout) y **0,007**
(desarrollo vs. OOT), ambos muy por debajo de 0,10.

---

## Marco normativo y gobernanza

### Backtesting

Contraste sistemático de lo **predicho** contra lo **observado** una vez que el resultado se
conoce: PD calibrada vs. tasa de default realizada, ranking (discriminación) y estabilidad
(PSI/CSI) en ventanas nuevas. Es el mecanismo de monitoreo continuo que exige la gobernanza de
modelos; distingue el deterioro real del ruido y dispara recalibración o rediseño.

### ECL / IFRS 9 — *Expected Credit Loss*

Pérdida crediticia esperada bajo la norma contable internacional **IFRS 9**: provisión
**prospectiva** y **sensible al ciclo** (PD en régimen PIT, escenarios forward-looking), con un
enfoque de **tres etapas** (12 meses vs. *lifetime* según deterioro de la calidad crediticia). Es
un cómputo **distinto** del modelo estándar CMF: el banco lo calcula con metodología interna.
Nikodym lo modela como un motor separado del CMF.

### Lineage (linaje / trazabilidad)

Registro que hace **reproducible** cada corrida: git SHA + hash lógico de los datos + `config_hash`
+ semilla + `uv.lock`. Junto con el *audit-trail*, garantiza la propiedad central
`(datos + config + semilla) → resultado idéntico`: reejecutar el mismo config con la misma semilla
sobre los mismos datos reproduce el resultado bit a bit. Es la base auditable que exige un
supervisor.

### Model card (tarjeta de modelo)

Ficha estandarizada que documenta un modelo: propósito, datos, metodología, parámetros, métricas
de desempeño y limitaciones. En Nikodym se **emite al habilitar el paso de gobernanza** (que exige
declarar un `purpose`), como parte del pipeline y alineado con SR 11-7, de modo que la documentación
del modelo no sea un entregable manual posterior sino un subproducto de la ejecución. Lo que sí es
automático en **toda** corrida es el *lineage* y el *audit-trail*.

### Provisiones CMF (modelo estándar)

Pérdida esperada **estandarizada regulatoria** de la CMF chilena (Compendio de Normas Contables,
Capítulos **B-1** provisiones y **B-3** contingentes), una **base mínima prudencial**. Para cada
deudor/operación: `Provisión = Exposición × (PI/100) × (PDI/100)` (con `PI`/`PDI` en %, como en el
resto del glosario; equivale a `Exposición × PE / 100`), con `PI`/`PDI` tomados de tablas por cartera
(comercial individual/grupal, hipotecaria vivienda, consumo) y por mora/colateral. La exposición de
un contingente se obtiene con el **CCF** del B-3 (p. ej. avales **100 %**, boletas de garantía
**50 %**, líneas de libre disposición **35 %**). No confundir con IFRS 9: son motores separados y la
provisión contable es el **máximo** de ambos.

!!! warning "CMF ≠ IFRS 9"
    El modelo estándar CMF es un **piso prudencial** con PD/LGD tabuladas por la norma; IFRS 9/ECL
    es prospectivo y con metodología interna del banco. Nikodym los mantiene como dos motores
    distintos y **no** los mezcla.

### SR 11-7 — *Supervisory Guidance on Model Risk Management*

Guía supervisora (Reserva Federal / OCC, EE. UU.) sobre **gestión del riesgo de modelo**: exige
validación independiente, documentación completa (model card), control de versiones y monitoreo
continuo (backtesting). Es el estándar de referencia de gobernanza de modelos; Nikodym lo adopta
"por construcción": audit-trail y lineage en cada corrida, y model card al habilitar el paso de gobernanza.

---

!!! info "Dónde se calcula cada cosa"
    Los términos de este glosario se materializan como artefactos *namespaced* por dominio en el
    `Study` que devuelve `nikodym.run(config)`: el **IV** y el **WoE** en el dominio `binning`, el
    **scorecard** y el **PDO** en `scorecard`, la **PD calibrada** y el ancla TTC en `calibration`,
    el **AUC/KS/Gini** en `performance` y el **PSI/CSI** en `stability`. Ver
    [Conceptos](concepts.md) para el modelo mental y la [Referencia de la API](api.md) para el
    detalle de acceso.
