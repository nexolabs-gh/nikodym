# Parámetros normativos CMF — Modelo estándar de provisiones por riesgo de crédito

| | |
|---|---|
| **Documento** | Extracción de tablas y parámetros numéricos del modelo estándar CMF de provisiones |
| **Fecha de extracción** | 2026-06-23 |
| **Norma base** | Compendio de Normas Contables (CNC) para Bancos — **Capítulo B-1** ("Provisiones por riesgo de crédito") y **Capítulo B-3** ("Créditos contingentes") |
| **Versión vigente del CNC** | Versión **2022** (aprobada por **Circular N° 2.243 / 20.12.2019**, vigente desde 01-01-2022), modificada para consumo por **Circular N° 2.346 / 06.03.2024** (vigente desde el cierre contable de **enero 2025**) |
| **Emisor** | Comisión para el Mercado Financiero (CMF), ex SBIF |
| **Propósito** | Parametrizar el módulo de provisiones regulatorias (modelo estándar) de Nikodym RiskLib |

---

## ⚠️ Advertencias de uso (LEER ANTES DE PARAMETRIZAR)

1. **Esto NO es IFRS 9 / ECL.** Es la **pérdida esperada estandarizada regulatoria** de la CMF (`PE = PI · PDI · Exposición`), una **base mínima prudencial**. Es un cómputo distinto del ECL de IFRS 9 (que el banco calcula con metodologías internas). El módulo debe tratarlos como dos motores separados.

2. **Estructura del cálculo.** Para cada deudor/operación: `Provisión = Exposición × PI × PDI`. La **Exposición** de un crédito contingente se obtiene aplicando el factor de conversión del **Capítulo B-3** al monto contingente (ver §6). En la cartera en incumplimiento individual comercial el cómputo es por rango de pérdida esperada (`Provisión = E × PP/100`, ver §1.3).

3. **Procedencia de los valores.** Las tablas marcadas **VERIFICADO** fueron extraídas del **texto oficial CMF/SBIF** con `pdftotext -layout`. Además, el **2026-06-23 se verificaron VISUALMENTE** (render del PDF oficial) las tablas más críticas: comercial individual A1–B4 (hoja 3), hipotecaria vivienda PVG (hoja 12), PDI de consumo (Circular 2.346) y avales (hoja 18). Resultado: comercial individual, vivienda y consumo **coinciden 100 %**; en avales se **detectó y corrigió** un error de la columna *Escala Internacional* (ver §5.2). Las circulares fuente se citan bajo cada tabla.

4. **Versión del PDF fuente de las matrices.** El PDF consolidado usado (`norma_6545_1.pdf`) se rotula "vigente hasta 31-12-2021". Sin embargo, las **tablas comercial individual, comercial grupal, hipotecaria, incumplimiento y B-3 NO fueron modificadas** por la reforma 2022 ni por la Circular 2.346/2024 (que **solo** introdujo el numeral 3.1.3 de consumo). Por lo tanto **siguen vigentes a 2026**. La matriz de **consumo** sí proviene del texto vigente 2025 (Circular 2.346). Antes de pasar a producción conviene revalidar contra el PDF del CNC versión 2022 publicado en cmfchile.cl (ver §7).

5. **No inventar.** Donde no se pudo confirmar un valor con texto oficial, está marcado **PENDIENTE / NOTA**, nunca rellenado a ojo.

---

## 1. Cartera comercial — Evaluación individual

### 1.1 Cartera Normal (A1–A6) y Subestándar (B1–B4)

| Tipo de Cartera | Categoría | PI — Probabilidad de Incumplimiento (%) | PDI — Pérdida dado el Incumplimiento (%) | PE — Pérdida Esperada (%) | Estado |
|---|---|---|---|---|---|
| **Normal** | A1 | 0,04 | 90,0 | 0,03600 | VERIFICADO |
| **Normal** | A2 | 0,10 | 82,5 | 0,08250 | VERIFICADO |
| **Normal** | A3 | 0,25 | 87,5 | 0,21875 | VERIFICADO |
| **Normal** | A4 | 2,00 | 87,5 | 1,75000 | VERIFICADO |
| **Normal** | A5 | 4,75 | 90,0 | 4,27500 | VERIFICADO |
| **Normal** | A6 | 10,00 | 90,0 | 9,00000 | VERIFICADO |
| **Subestándar** | B1 | 15,00 | 92,5 | 13,87500 | VERIFICADO |
| **Subestándar** | B2 | 22,00 | 92,5 | 20,35000 | VERIFICADO |
| **Subestándar** | B3 | 33,00 | 97,5 | 32,17500 | VERIFICADO |
| **Subestándar** | B4 | 45,00 | 97,5 | 43,87500 | VERIFICADO |

> **Fuente:** CNC, Capítulo B-1, numeral 2.1, **hoja 3**. Circular N° **3.573 / 30.12.2014**. PDF consolidado: `http://www.sbif.cl/sbifweb3/internet/archivos/norma_6545_1.pdf`.
> **Nota:** `PE(%) = PI(%) × PDI(%) / 100`. Estos parámetros son la base mínima para deudores comerciales evaluados individualmente en cartera en cumplimiento (Normal/Subestándar).

### 1.2 Definición de categorías (resumen)

- **A1–A6 (Normal):** deudores con capacidad de pago que les permite cumplir sus obligaciones; A1 = más alta calidad crediticia; el riesgo aumenta de A1 a A6.
- **B1–B4 (Subestándar):** deudores con dificultades financieras o empeoramiento de su capacidad de pago, o con morosidades en el último período; el riesgo aumenta de B1 a B4.
- **C1–C6 (Incumplimiento):** ver §1.3.

> **Fuente:** CNC, Capítulo B-1, numeral 2.1.1, hojas 4–8. Circular N° 3.573/2014. (Definiciones cualitativas; no contienen parámetros adicionales.)

### 1.3 Cartera en Incumplimiento individual (C1–C6)

| Tipo de Cartera | Escala de Riesgo | Rango de Pérdida Esperada | Provisión PP (%) | Estado |
|---|---|---|---|---|
| **Incumplimiento** | C1 | Hasta 3 % | 2 | VERIFICADO |
| **Incumplimiento** | C2 | Más de 3 % hasta 20 % | 10 | VERIFICADO |
| **Incumplimiento** | C3 | Más de 20 % hasta 30 % | 25 | VERIFICADO |
| **Incumplimiento** | C4 | Más de 30 % hasta 50 % | 40 | VERIFICADO |
| **Incumplimiento** | C5 | Más de 50 % hasta 80 % | 65 | VERIFICADO |
| **Incumplimiento** | C6 | Más de 80 % | 90 | VERIFICADO |

> **Fuente:** CNC, Capítulo B-1, numeral 2.2, **hoja 9**. Circular N° **3.573 / 30.12.2014**. PDF: `norma_6545_1.pdf`.
> **Fórmulas (texto oficial):** `Tasa de Pérdida Esperada = (E − R) / E` ; `Provisión = E × (PP/100)`, donde `E` = monto de la exposición (colocaciones + contingentes) y `R` = monto recuperable (ejecución de garantías financieras/reales, bienes en leasing y, con antecedentes, valor presente de recuperaciones por cobranza neto de gastos). La tasa de pérdida esperada se encasilla en C1–C6 y se aplica el `PP` correspondiente.

---

## 2. Cartera comercial — Evaluación grupal (método estándar)

El método estándar comercial grupal usa **tres sub-métodos** (no existe una cuarta matriz "genérica" separada: lo genérico va en el método c). Parámetros actualizados por **Circular N° 2.257 / 22.05.2020 (Resolución N° 2.923)** sobre la base creada por **Circular N° 3.638 / 06.07.2018**.

> **Fuente común:** CNC, Capítulo B-1, numeral **3.1.2**, hojas 13–16. PDF: `norma_6545_1.pdf`. **Estado: VERIFICADO** (todas las tablas de esta sección).

### 2.a Leasing comercial

**PI (%) según morosidad y tipo de bien** (hoja 13):

| Días de mora de la operación al cierre del mes | Inmobiliario | No Inmobiliario |
|---|---|---|
| 0 | 0,79 | 1,61 |
| 1–29 | 7,94 | 12,02 |
| 30–59 | 28,76 | 40,88 |
| 60–89 | 58,76 | 69,38 |
| Cartera en incumplimiento | 100,00 | 100,00 |

**PDI (%) según tramo PVB y tipo de bien** (hoja 14). `PVB = Valor actual de la operación / Valor del bien en leasing`:

| Tramo PVB | Inmobiliario | No Inmobiliario |
|---|---|---|
| PVB ≤ 40 % | 0,05 | 18,2 |
| 40 % < PVB ≤ 50 % | 0,05 | 57,00 |
| 50 % < PVB ≤ 80 % | 5,10 | 68,40 |
| 80 % < PVB ≤ 90 % | 23,20 | 75,10 |
| PVB > 90 % | 36,20 | 78,90 |

> Fuente tabla PI: Circular 3.638/2018. Tabla PDI: misma norma. `PVB` se determina con valor de tasación al otorgamiento (UF para inmobiliarios, pesos para no inmobiliarios).

### 2.b Préstamos estudiantiles

**PI (%) según exigibilidad del pago, morosidad y tipo** (hoja 14). CAE = Ley N° 20.027:

| Exigibilidad del pago | Días de mora al cierre del mes | CAE | CORFO u otros |
|---|---|---|---|
| Sí | 0 | 5,2 | 2,9 |
| Sí | 1–29 | 37,2 | 15,0 |
| Sí | 30–59 | 59,0 | 43,4 |
| Sí | 60–89 | 72,8 | 71,9 |
| Sí | Cartera en incumplimiento | 100,0 | 100,0 |
| No | n/a | 41,6 | 16,5 |

**PDI (%) según exigibilidad del pago y tipo** (hoja 15):

| Exigibilidad del pago | CAE | CORFO u otros |
|---|---|---|
| Sí | 70,9 | 70,9 |
| No | 50,3 | 45,8 |

> **Nota de extracción:** en la fila "Sí" de la tabla PDI, el PDF oficial muestra **un único valor 70,9 centrado abarcando ambas columnas** (CAE y CORFO/otros). Es decir, cuando el pago es exigible, PDI = 70,9 % para ambos tipos. Verificado en texto oficial.

### 2.c Colocaciones comerciales genéricas y factoraje

**PI (%) según morosidad y tramo PTVG** (hoja 15). `PTVG = obligaciones del deudor con el banco / valor de las garantías reales`:

| Días de mora al cierre del mes | Con garantía PTVG ≤ 100 % | Con garantía PTVG > 100 % | Sin garantía |
|---|---|---|---|
| 0 | 1,86 | 2,68 | 4,91 |
| 1–29 | 11,60 | 13,45 | 22,93 |
| 30–59 | 25,33 | 26,92 | 45,30 |
| 60–89 | 41,31 | 41,31 | 61,63 |
| Cartera en incumplimiento | 100,00 | 100,00 | 100,00 |

**PDI (%) según tramo PTVG** (hoja 15):

| Garantía | Tramo PTVG | Comerciales genéricas o factoraje **sin** responsabilidad del cedente | Factoraje **con** responsabilidad del cedente |
|---|---|---|---|
| Con garantía | PTVG ≤ 60 % | 5,0 | 3,2 |
| Con garantía | 60 % < PTVG ≤ 75 % | 20,3 | 12,8 |
| Con garantía | 75 % < PTVG ≤ 90 % | 32,2 | 20,3 |
| Con garantía | 90 % < PTVG | 43,0 | 27,1 |
| Sin garantía | — | 56,9 | 35,9 |

> Fuente PI/PDI: Circular N° **2.257 / 22.05.2020 (Res. 2.923)**. Reglas PTVG (garantías específicas vs generales, exclusión de facturas cedidas, primer grado de preferencia) en hoja 16.

### 2.d Sustitución por avales en cartera grupal (fórmulas)

Cuando hay aval, los montos avalados pueden separarse del segmento grupal:

- **Método 1 (PE directa):** `Provisión = EG·(1 − EA/100)·(PE_grupo/100) + EG·(EA/100)·(PE_aval/100)`
- **Método 2 (PI·PDI):** `Provisión = EG·(1 − EA/100)·(PI_grupo/100)·(PDI_grupo/100) + EG·(EA/100)·(PE_aval/100)`

Donde `EG` = exposición grupal, `EA` = % de exposición avalada, y los parámetros del aval (`PE_aval` / `PI_aval` / `PDI_aval`) se toman de la **tabla del numeral 2.1** (la de §1.1, según la categoría asignada al aval). El `PE_grupo`/`PDI_grupo` se calculan **excluyendo** recuperaciones provenientes de avales.

> **Fuente:** CNC, Capítulo B-1, numeral 4.1 letra a), hojas 18–19. Circular N° 3.638/2018. **Estado: VERIFICADO** (fórmulas; los parámetros del aval remiten a §1.1).

---

## 3. Cartera consumo — Modelo estandarizado vigente (2025)

Numeral **3.1.3** del Capítulo B-1, introducido por **Circular N° 2.346 / 06.03.2024**, vigente desde el **cierre contable de enero 2025**. `PE(%) = PI(%) × PDI(%) / 100`, aplicado uniformemente a todas las colocaciones y contingentes de consumo del deudor con el banco y filiales en Chile (incluye leasing de consumo; excluye filiales/sucursales en el exterior).

### 3.1 Matriz de PI (%) — 3 factores

Factores: (1) nivel de mora máximo de consumo en el banco al cierre del mes; (2) mora ≥ 30 días en el sistema en alguno de los 3 meses previos; (3) tenencia de crédito hipotecario para vivienda vigente en el sistema.

| Nivel de mora máximo en el mes y banco (días, incluye extremos) | Con hipotecario · **Sin** mora >30d sistema | Con hipotecario · **Con** mora >30d sistema | Sin hipotecario · **Sin** mora >30d sistema | Sin hipotecario · **Con** mora >30d sistema |
|---|---|---|---|---|
| 0 a 7 | 3,3 % | 14,6 % | 6,6 % | 19,8 % |
| 8 a 30 | 20,4 % | 41,6 % | 30,6 % | 48,5 % |
| 31 a 60 | 50,2 % | 63,0 % | 65,1 % | 66,3 % |
| 61 a 89 | 62,6 % | 81,7 % | 72,3 % | 86,9 % |

> Si el deudor está **en incumplimiento** (numeral 3.2), **PI = 100 %**.
> **Estado: ✅ VERIFICADO CONTRA EL COMPENDIO CONSOLIDADO — 2026-07-14.** Las **16 celdas de PI, las 6 de PDI (§3.2) y el PI = 100 % de incumplimiento** se contrastaron una a una contra el texto oficial y **coinciden exactamente**. **Fuente:** *Compendio de Normas Contables para Bancos*, Capítulo B-1, numeral **3.1.3**, **hojas 16-18** (pie de página: *"Circular N° 2.346 / 06.03.2024 por Resolución N°2306"*), extraído con `pdftotext -layout` desde el PDF consolidado del portal CMF: `https://www.cmfchile.cl/portal/normativa/624/articles-29177_doc_pdf.pdf`.
> _Sigue sin ser una validación **de** la CMF —la Comisión no certifica implementaciones de terceros—, pero ya no es una transcripción sin contrastar: es un cotejo literal contra el texto vigente._

### 3.2 Matriz de PDI (%) — por tenencia hipotecaria y tipo de producto

| Tenencia de hipotecario en el sistema | Operaciones de leasing y créditos automotrices | Créditos en cuotas | Tarjetas y líneas de crédito, y otros de consumo |
|---|---|---|---|
| **Con** crédito hipotecario para vivienda | 33,2 % | 47,7 % | 49,5 % |
| **Sin** crédito hipotecario para vivienda | 33,2 % | 56,6 % | 60,3 % |

> **Estado: VERIFICADO.** **Fuente:** Circular N° **2.346 / 06.03.2024**, numeral 3.1.3, Capítulo B-1.
> **Clasificación de producto (directrices oficiales):**
> - **Leasing y automotrices:** financiamiento de vehículos de uso particular con prenda a favor del banco + leasing financiero de consumo (ítem 14800 04 00).
> - **Créditos en cuotas:** ítem 14800 01 00 (consumo en cuotas) otorgados con pagaré (monto, plazo, tasa, n° de cuotas), libre disposición, que no caigan en la categoría anterior.
> - **Tarjetas/líneas y otros:** todo lo clasificado en 14800 00 00 (consumo) que no pertenezca a las dos definiciones anteriores.
> **Cambio clave 2024:** se eliminó la regla previa "para créditos de consumo no se considerarán las garantías"; ahora la tenencia de hipotecario sí modula la PDI.

### 3.3 Cartera en incumplimiento — las tres causales (numeral 3.2)

El incumplimiento del Capítulo B-1 **no se deriva solo de la mora**. Son tres causales, y basta una:

| # | Causal | ¿Derivable de los datos de mora? |
|---|---|---|
| i | Atraso **≥ 90 días** en intereses o capital de algún crédito | **Sí** — el motor la deriva del máximo de mora del deudor |
| ii | Se le otorga un crédito **para dejar vigente** una operación con **> 60 días** de atraso | **No** — la declara el banco |
| iii | **Reestructuración forzosa** o **condonación parcial** de una deuda | **No** — la declara el banco |

Las causales **ii** y **iii** son independientes de la mora vigente: un deudor refinanciado o reestructurado puede estar **al día** y aun así la norma le exige **PI = 100 %**. El motor las recoge por la columna **`exposure.is_default_col`** (`is_default` por defecto), **opcional**; sus nulos se leen como "no marcado", de modo que el flag solo puede **sumar** incumplimiento, nunca quitar el que impone la mora.

El incumplimiento se consolida **a nivel deudor**: la norma manda que *"todos los créditos del deudor deberán mantenerse en la Cartera en Incumplimiento"*, así que una sola operación marcada arrastra **todas** las del deudor.

> ⚠️ **Sin esa columna, la cartera queda subprovisionada.** Un deudor reestructurado y al día cae en el tramo 0-7 (PI **6,6 %**) cuando la norma exige **100 %**: un factor **15×** de sub-provisión, y en la dirección que un regulador no perdona. El motor **no puede inferir** las causales ii y iii — si el banco no las declara, no existen para el cálculo.
>
> **Fuente:** CNC, Capítulo B-1, numeral **3.2**, hoja 18 (Circular N° 2.346 / 06.03.2024).

---

## 4. Cartera hipotecaria vivienda (método estándar)

Numeral **3.1.1** del Capítulo B-1 (método estándar vigente desde 2016). `PE(%) = PI(%) × PDI(%) / 100`. `PVG = Capital insoluto del préstamo / Valor de la garantía hipotecaria` (valor de tasación en UF al otorgamiento).

| Tramo PVG | Parámetro | Mora 0 | Mora 1–29 | Mora 30–59 | Mora 60–89 | Cartera en incumplimiento |
|---|---|---|---|---|---|---|
| **PVG ≤ 40 %** | PI (%) | 1,0916 | 21,3407 | 46,0536 | 75,1614 | 100 |
| | PDI (%) | 0,0225 | 0,0441 | 0,0482 | 0,0482 | 0,0537 |
| | PE (%) | 0,0002 | 0,0094 | 0,0222 | 0,0362 | 0,0537 |
| **40 % < PVG ≤ 80 %** | PI (%) | 1,9158 | 27,4332 | 52,0824 | 78,9511 | 100 |
| | PDI (%) | 2,1955 | 2,8233 | 2,9192 | 2,9192 | 3,0413 |
| | PE (%) | 0,0421 | 0,7745 | 1,5204 | 2,3047 | 3,0413 |
| **80 % < PVG ≤ 90 %** | PI (%) | 2,5150 | 27,9300 | 52,5800 | 79,6952 | 100 |
| | PDI (%) | 21,5527 | 21,6600 | 21,9200 | 22,1331 | 22,2310 |
| | PE (%) | 0,5421 | 6,0496 | 11,5255 | 17,6390 | 22,2310 |
| **PVG > 90 %** | PI (%) | 2,7400 | 28,4300 | 53,0800 | 80,3677 | 100 |
| | PDI (%) | 27,2000 | 29,0300 | 29,5900 | 30,1558 | 30,2436 |
| | PE (%) | 0,7453 | 8,2532 | 15,7064 | 24,2355 | 30,2436 |

> **Estado: VERIFICADO** (extraído del PDF semilla B-1 *y* del consolidado `norma_6545_1.pdf`; ambos coinciden). **Fuente:** CNC, Capítulo B-1, numeral 3.1.1, hoja 12. Circular N° **3.638 / 06.07.2018** (circular que rotula la hoja vigente del consolidado; parámetros introducidos por Circular **3.573 / 30.12.2014**). **Verificado visualmente 2026-06-23** (render hoja 12, pie "Circular N° 3.638 / 06.07.2018").
> **Regla:** si un deudor tiene más de un préstamo hipotecario y uno presenta atraso ≥ 90 días, todos pasan a cartera en incumplimiento (cada uno provisionado por su propio PVG).

### 4.1 Factor de mitigación MP (créditos con seguro estatal de remate)

Para créditos hipotecarios de programas habitacionales/subsidio del Estado con seguro de remate. El `PP` se pondera por `MP` según `PVG` y `V` (precio de la vivienda en la escrituración, UF):

| Tramo PVG | V ≤ 1.000 UF | 1.000 < V ≤ 2.000 UF |
|---|---|---|
| PVG ≤ 40 % | 100 % | 100 % |
| 40 % < PVG ≤ 80 % | 100 % | 100 % |
| 80 % < PVG ≤ 90 % | 95 % | 96 % |
| PVG > 90 % | 84 % | 89 % |

> **Estado: VERIFICADO.** **Fuente:** CNC, Capítulo B-1, numeral 3.1.1, hoja 13. Circular N° **3.638 / 06.07.2018** (circular que rotula la hoja vigente del consolidado). **Verificado visualmente 2026-06-23** (render hoja 13). (En el PDF el "100 %" aparece como una celda fusionada que cubre los tramos PVG ≤ 40 % y 40 % < PVG ≤ 80 % para ambas columnas de V.)

---

## 5. Garantías (Capítulo B-1 numeral 4 / RAN)

### 5.1 Tipos de garantía admisibles y tratamiento

| Tipo | Tratamiento en el cálculo de provisiones | Estado |
|---|---|---|
| **a) Avales y fianzas** | Sustitución de la calidad crediticia del deudor por la del avalista/fiador, en la proporción de la exposición avalada (ver tabla §5.2). Aplicable si el aval está calificado en grado de inversión, o si es Fisco/CORFO/FOGAPE (→ categoría A1), o IGR (se usa la clasificación de la propia IGR). | VERIFICADO |
| **b) Garantías reales (hipotecas/prendas)** | Método de deducción / tasa de recuperación: se valora por el flujo neto esperado de la venta del bien (valor de liquidación menos gastos de mantención y enajenación, a valor presente). Requiere estudios y tasaciones por profesionales independientes, con historia ≥ 3 años incl. un episodio de caída económica. | VERIFICADO |
| **c) Garantías financieras** | Se descuenta el **valor razonable ajustado** de la exposición. Admisibles: (i) depósitos en efectivo en moneda nacional o de país de máxima categoría; (ii) títulos de deuda del Estado chileno o Banco Central; (iii) depósitos a plazo en otros bancos en Chile; (iv) títulos de deuda de gobiernos extranjeros de máxima categoría. El valor razonable se ajusta por factores de descuento (volatilidad de tasas y monedas) que fija la CMF, menos costos de liquidación. | VERIFICADO |
| **Bienes en leasing** | Se considera el valor de enajenación del bien arrendado, neto de deterioro y gastos de rescate/liquidación/recolocación. | VERIFICADO |
| **Factoring** | Contraparte = cedente (cesión con responsabilidad) o deudor de la factura (sin responsabilidad). Sustitución excepcional al deudor de la factura si está en categoría A3 o superior y se notifica la cesión. | VERIFICADO |

> **Fuente:** CNC, Capítulo B-1, numeral 4 (4.1, 4.2, 4.3), hojas 18–22. Circulares 3.584/2015 y 3.638/2018. PDF: `norma_6545_1.pdf`.

### 5.2 Equivalencia de calidad crediticia del aval (sustitución)

| Categoría hasta | PI Escala Internacional (%) | PDI Escala Internacional (%) | PI Escala Nacional (%) | PDI Escala Nacional (%) |
|---|---|---|---|---|
| AA / Aa2 | 0,04 | 90,0 | 0,04 | 90,0 |
| A / A2 | 0,04 | 90,0 | 0,10 | 82,5 |
| BBB- / Baa3 | 0,10 | 82,5 | 0,25 | 87,5 |

> **Estado: ✅ VERIFICADO VISUALMENTE (corregido) — 2026-06-23, render del PDF oficial, hoja 18.** **Fuente:** CNC, Capítulo B-1, numeral 4.1 letra a), **hoja 18** (Circular N° **3.638 / 06.07.2018**). _(Re-verificado visualmente 2026-06-23: el render de la hoja 18 muestra el pie "Circular N° 3.638 / 06.07.2018"; la cita previa "hoja 14 / Circular 3.584/2015" era incorrecta. En el CNC v2022 `cir_2249.pdf` la misma tabla figura como "hoja 17" por distinta paginación del PDF.)_ **CORRECCIÓN respecto a la extracción inicial por `pdftotext`:** la columna *Escala Internacional* está **corrida una categoría** respecto a la Nacional, por celdas fusionadas que `pdftotext` no respeta. En la **escala Internacional**, las categorías **AA/Aa2 y A/A2 comparten 0,04 / 90,0** (celda fusionada) y **BBB-/Baa3 = 0,10 / 82,5**. En la **escala Nacional** hay un valor por fila: `0,04/90,0` · `0,10/82,5` · `0,25/87,5` (coinciden con A1/A2/A3 de §1.1). La extracción inicial replicó erróneamente los valores nacionales en la columna internacional; **corregido tras verificación visual**.
> **Aforos/haircuts financieros:** los factores de descuento por volatilidad de tasas/monedas aplicables a garantías financieras (letra c) **NO** están tabulados en el Capítulo B-1: la norma dice que "los fija esta Superintendencia". → **PENDIENTE**: requieren la circular específica de factores de descuento (probablemente vinculada al Capítulo 7-12 de la RAN). No localizada en esta pasada.

### 5.3 RAN 21-10 — Garantías como mitigadores (requisitos)

> **Estado: PENDIENTE.** La normativa de requisitos y condiciones mínimas de garantías como mitigadores de riesgo de crédito (RAN, asociada a la noticia CMF art-89303) regula admisibilidad y condiciones, **no** publica aforos/haircuts numéricos nuevos para el modelo estándar de provisiones (esos viven en B-1). No se extrajo tabla numérica porque el modelo estándar de provisiones del Capítulo B-1 ya incorpora el efecto de garantías vía las relaciones PVG/PVB/PTVG y la sustitución por avales (§§2, 4, 5.2). Referencia: `https://www.cmfchile.cl/portal/prensa/615/w3-article-89303.html`.

---

## 6. Créditos contingentes — Factores de conversión (Capítulo B-3)

Para calcular provisiones (Capítulo B-1), la **Exposición** de un crédito contingente = `monto contingente × factor` de la tabla siguiente.

| Tipo de crédito contingente | Factor de exposición (CCF) | Estado |
|---|---|---|
| a) Avales y fianzas | **100 %** | VERIFICADO |
| b) Cartas de crédito del exterior confirmadas | **20 %** | VERIFICADO |
| c) Cartas de crédito documentarias emitidas | **20 %** | VERIFICADO |
| d) Boletas de garantía | **50 %** | VERIFICADO |
| e) Líneas de crédito de libre disposición (tarjetas, sobregiros pactados) | **35 %** | VERIFICADO |
| f) Otros compromisos de crédito — Créditos para estudios superiores Ley N° 20.027 | **15 %** | VERIFICADO |
| f) Otros compromisos de crédito — Otros | **100 %** | VERIFICADO |
| g) Otros créditos contingentes | **100 %** | VERIFICADO |

> **Estado: VERIFICADO.** **Fuente:** CNC, Capítulo **B-3**, numeral 3, hojas 1–2. Circular N° **3.604 / 29.03.2016** (tabla de exposición); tipos definidos por Circular N° 3.588/25.09.2015. PDF consolidado: `norma_6545_1.pdf`; versión 2022 dentro de `cir_2249_2020.pdf`.
> **Override por incumplimiento (texto oficial):** "cuando se trate de operaciones efectuadas con clientes que tengan créditos **en incumplimiento** según el Capítulo B-1, dicha exposición será **siempre equivalente al 100 %**". → El módulo debe forzar CCF = 100 % para cualquier contingente de un deudor en incumplimiento.
> **Implementación:** el rubro f) requiere **lógica condicional** (15 % vs 100 % según sea o no CAE Ley 20.027), no un único factor por letra.
> **⚠️ No confundir con APR/Basilea:** estos CCF del B-3 son **contables (para provisiones)**. Los CCF para **activos ponderados por riesgo de crédito** (capital regulatorio, RAN Cap. 21-6) son **otra tabla con valores distintos**. No mezclar en el módulo. (Fuera del alcance de este documento; extraer aparte si se necesita el motor de capital.)

---

## 7. Fuentes y verificación

| Fuente | URL | Rol | Estado |
|---|---|---|---|
| **CNC consolidado (183 pp.)** — contiene B-1 completo (hojas 1–25) y B-3 | `http://www.sbif.cl/sbifweb3/internet/archivos/norma_6545_1.pdf` | **Fuente primaria** de §§1, 2, 4, 5, 6 (y confirma §4 hipotecaria) | VERIFICADO (rotulado "vigente hasta 31-12-2021"; tablas no modificadas desde) |
| **Circular N° 2.346 / 2024** — Modelo estándar consumo (B-1 num. 3.1.3 + Cap. E) | `https://www.cmfchile.cl/normativa/cir_2346_2024.pdf` | **Fuente primaria** de §3 (consumo, vigente 2025) | VERIFICADO |
| PDF semilla B-1 (hojas 10–22, Circular 3.584/2015) | `https://sbif.cl/sbifweb/internet/archivos/norma_10821_3.pdf` | Confirmación cruzada de §4 (hipotecaria) y §5 (garantías) | VERIFICADO |
| CNC versión 2022 (Circular 2.243) | `https://www.cmfchile.cl/institucional/mercados/ver_archivo.php?archivo=/web/compendio/cir/cir_2249_2020.pdf` | Versión vigente base; revalidar tablas aquí antes de producción | Referenciado (descarga OK, ~2,3 MB) |
| Índice del Compendio (CNC) | `https://www.cmfchile.cl/portal/principal/613/w3-propertyvalue-29911.html` → redirect `w4-propertyvalue-29911.html` | Navegación / verificación de vigencia | Referenciado |
| Comunicado ME consumo | `https://www.cmfchile.cl/portal/prensa/615/w3-article-79155.html` | Confirma vigencia 2025 y alcance de Circular 2.346 | VERIFICADO |
| Informe Normativo ME consumo (45 pp.) | (CMF, serie de estudios normativos) | Contexto metodológico de §3 | Referenciado |
| Garantías como mitigadores (RAN) | `https://www.cmfchile.cl/portal/prensa/615/w3-article-89303.html` | Contexto §5.3 | Referenciado (sin tabla numérica nueva) |

### Resumen de estado por punto

| # | Punto solicitado | Estado |
|---|---|---|
| 1 | Comercial individual — A1–A6, B1–B4, C1–C6 (PI/PDI/PP) | ✅ **VERIFICADO** |
| 2 | Comercial grupal — leasing, estudiantiles, factoring/genérica (PI/PDI) | ✅ **VERIFICADO** |
| 3 | Consumo — matriz PI (3 factores) + PDI (producto × hipotecario) | ✅ **VERIFICADO** (vigente 2025) |
| 4 | Hipotecaria vivienda — PI/PDI/PE por mora y PVG + factor MP | ✅ **VERIFICADO** |
| 5 | Garantías — tipos, sustitución avales, reglas | ✅ **VERIFICADO** (tabla de avales §5.2 **corregida** tras verificación visual 2026-06-23); ⚠️ aforos/haircuts financieros y RAN 21-10 numéricos: **PENDIENTE** (la norma los delega a circular específica de factores de descuento, no tabulados en B-1) |
| 6 | Créditos contingentes — CCF (Capítulo B-3) | ✅ **VERIFICADO** |

**Pendientes reales (no rellenados a ojo):**
- Factores de descuento por volatilidad (tasas/monedas) para **garantías financieras** del B-1 letra c) — la norma los remite a una circular específica de la CMF (no localizada esta pasada).
- ~~Asignación de columna *Internacional* para la fila BBB-/Baa3 (§5.2)~~ → **RESUELTO** (verificación visual 2026-06-23): la escala Internacional está corrida (AA/Aa2 y A/A2 comparten 0,04/90,0; BBB-/Baa3 = 0,10/82,5). Tabla §5.2 corregida.
- Tabla de CCF para **capital/APR (RAN 21-6)** — fuera del alcance pedido (es para Basilea, no para provisiones); se deja anotada para evitar que se confunda con el B-3.

**Vigilancia regulatoria (verificado 2026-06-23):** ninguna circular **enactada** posterior a 2024 modifica los valores del modelo estándar de provisiones del Capítulo B-1. Existe una **consulta pública en curso** (Res. Exenta N° 273 de 06-01-2025 y su segunda versión Res. Exenta N° 10.976 de 21-10-2025), enmarcada en garantías como mitigadores (nuevo Cap. 21-10 de la RAN); su origen proponía tocar el B-1, pero en la segunda consulta (oct-2025) el alcance contable quedó acotado a los Capítulos **B-6/B-7** (ajustes de referencias cruzadas, **sin** modificar las matrices PI/PDI/PE estándar). **Acción:** vigilar la enacción de esta circular y del Cap. 21-10 antes de uso productivo; no asumir aún cambios a las tablas vigentes.

---

*Documento generado por extracción asistida sobre textos oficiales CMF/SBIF. Todo valor marcado VERIFICADO proviene del texto normativo citado, extraído con `pdftotext -layout` y verificado contra el PDF fuente. Antes de uso productivo en provisiones regulatorias, revalidar contra la versión publicada del CNC en cmfchile.cl a la fecha de cálculo.*
