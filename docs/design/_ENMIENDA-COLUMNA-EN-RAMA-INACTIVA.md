# Enmienda SDD — el preflight acusa una columna que el motor nunca abre

> **Estado:** aprobada e implementada (2026-08-03).
> **Enmienda a:** [`_ENMIENDA-PREFLIGHT-DATASET.md`](_ENMIENDA-PREFLIGHT-DATASET.md) (D-PRE-3, el
> vocabulario `column_role`) y [`_ENMIENDA-INVARIANTES-PREVIAS.md`](_ENMIENDA-INVARIANTES-PREVIAS.md)
> (D-INV-1, la invariante la declara el dominio que la impone).
> **Decisiones:** D-RAM-1 … D-RAM-7.

## 0. El defecto que la origina

Lo reprodujo la revisión adversarial cruzada de Codex el 2026-08-03, sobre trabajo con **todos los
gates verdes**, horas después de declarar 32 `column_role` en `provisioning/`:

```
provisioning_ifrs9.ead.method   = "provided"
provisioning_ifrs9.ead.ccf_col  = "columna_fantasma"

check_dataset → mismatches = ("El dataset no tiene la columna «columna_fantasma»…")
motor         → NUNCA la lee: `_estimate_ccf` es la rama `else` de ead.py:131-135,
                y con method='provided' no se llama
```

El aviso es **falso**, y el usuario no tiene forma de saberlo: para él, el preflight acaba de
señalarle un problema que no existe. La regla que este repo ya escribió con el perfil de columnas
—*«un aviso que se dispara de más se aprende a ignorar»*— vale igual aquí, y con más peso, porque el
preflight es exactamente la superficie cuya autoridad se está construyendo.

## 1. La causa, y por qué no era un olvido

**`column_role` no puede expresar condiciones, por construcción.** `_declaraciones`
(`core/dataset_check.py`) lee el rol del `Field` y emite `(ruta, rol, columna)` **sin mirar el valor
de ningún campo hermano**. Eso es correcto mientras el campo se consuma siempre, y deja de serlo en
cuanto una rama lo apaga.

El criterio con que se eligieron los 23 campos `input` de provisiones fue *«default vacío ⇒ seguro»*,
y **era insuficiente**: lo que decide no es el default del campo condicionado, sino **si la rama que
lo consume está activa**. Un campo que nace vacío y que el usuario llena en una rama que no corre
produce exactamente el falso positivo que D-INV-8 documentó al dejar `stratify_by` fuera.

### 1.1 Los cinco campos afectados, medidos uno a uno

| campo | lo lee | condición | default |
|---|---|---|---|
| `ifrs9.ead.ccf_col` | `ead.py:157-159` | `method == "ccf"` | `ccf` ⇒ activa **de fábrica** |
| `ifrs9.lgd.covariate_cols` | `lgd.py:183-185` | `method ∈ {beta_regression, fractional_response}` | `provided` ⇒ inactiva |
| `ifrs9.staging.rating_col` | `staging.py:189` | `notch_downgrade_threshold is not None` | `None` ⇒ inactiva |
| `ifrs9.staging.origination_rating_col` | `staging.py:190` | idem | `None` ⇒ inactiva |
| `ifrs9.staging.low_credit_risk_col` | `staging.py:221-228` | `low_credit_risk_exemption` | `False` ⇒ inactiva |

El patrón común es que **la validación del config sólo cierra una dirección**: `config.py:508-513`
exige los ratings cuando hay umbral, pero no prohíbe los ratings sin umbral; `config.py:348-349`
sólo veta `ccf_col` **y** `ccf_value` juntos, y únicamente bajo `method='ccf'`. Los cinco estados
son alcanzables y construyen sin un solo error.

## 2. Las tres salidas, y por qué se eligió la tercera

1. **Quitar el rol a los cinco**, sumándolos a los 14 que ya quedaron fuera. Cero riesgo y cero
   mecanismo nuevo, pero devuelve cinco falsos **negativos**: con la rama activa —que es el caso de
   fábrica de `ccf_col`— el preflight volvería a decir «compatible» sobre una columna que falta de
   verdad.
2. **Seguir el precedente de `provisioning/internal`** (`internal/config.py:255-283`), que prohíbe
   declarar una columna cuya rama está apagada: *«una columna declarada que el motor nunca abre es
   una mentira del config»*. Es el arreglo más limpio conceptualmente y no toca el núcleo, pero es
   **cambio de comportamiento**: un config que hoy construye dejaría de construir.
3. **Un método hermano en el protocolo del preflight**, que es lo elegido por Cami.

**D-RAM-1.** Una config declara, por convención de nombre, cuáles de **sus** campos de columna no se
leen con la configuración actual:

```python
def columnas_inactivas(self) -> frozenset[str]: ...
```

Duck-typing y no clase base, igual que `requisitos_incumplidos` (D-INV-1) y por la misma razón: las
configs de dominio no heredan del núcleo. `_declaraciones` la consulta en cada modelo y salta esos
campos.

**D-RAM-2.** Es **aditivo**: quien no lo declare se comporta exactamente como antes. No mueve ningún
`config_hash` —no es un campo de config, es un método—, no cambia ninguna firma pública y no
rechaza ningún config que hoy se acepte.

**D-RAM-3.** Los nombres son los del **propio modelo**, no rutas anidadas: la condición y el campo
condicionado viven juntos, porque quien decide si `ccf_col` se lee es el `method` que tiene al lado.
Si algún día hiciera falta una ruta relativa, se amplía; hoy sería complejidad sin caso.

**D-RAM-4.** 🔴 **Es la primera pieza de este protocolo que puede CALLAR un desajuste**, y por eso su
gate se mide en los **dos** sentidos. Un `column_role` mal declarado produce un aviso de más
—molesto y visible—; una `columnas_inactivas` mal declarada produce un aviso de **menos**, que es el
falso negativo silencioso contra el que existe el preflight entero (D-PRE-9). El error caro aquí es
el simétrico del que arregla. `tests/unit/test_columna_en_rama_inactiva.py` escribe su oráculo **a
mano**, con la condición leída del motor, y por cada campo comprueba que con la rama apagada **no**
se acusa y con la rama encendida **sí**.

**D-RAM-5.** El método hermano **no** absuelve al vocabulario de roles. Un campo sin `column_role`
sigue siendo invisible para el preflight, y eximir en `columnas_inactivas` un campo que nunca
declaró rol no suprime nada: sólo hace creer que se cerró algo. El gate lo rechaza.

## 3. D-RAM-6 — la segunda causa, que apareció al ampliar el preflight a `survival`

Al medir la ampliación a `survival` salió un falso positivo de **otra clase**, y la distinción
importa porque el remedio de arriba no le sirve:

```
survival.input.event_col = "target"     →  la corrida llega a done (medido, preset F4 real)
                                           el preflight lo acusaría de columna faltante
```

No es una rama apagada: la rama corre y la columna **se lee**. Lo que pasa es que `survival` no
consume el archivo del usuario, sino la **salida de `data`**, que trae el target y la partición ya
construidos. Y el caso no es rebuscado: el indicador de evento *es* el flag de malo.

🔴 **Y el defecto no lo traía survival: ya estaba vivo en `main`.** `stability.temporal_column`
declara `input` desde hace semanas y se consume sobre el mismo frame; medido sobre el preset F1,
tres de sus valores alcanzables —`target`, `label_status`, `ttd`— corren a `done` y el preflight los
acusa. **Ningún test cruzaba ese campo con `check_dataset`.** La única guarda que existía
(`partition`) es un efecto colateral del anticolisión de `StabilityConfig`, no del preflight.

**D-RAM-6.** Una sección declara, por convención de nombre, las columnas que **añade** al frame:

```python
def columnas_que_produce(self) -> frozenset[str]: ...
```

`check_dataset` las cuenta como presentes. Hoy sólo la implementa `DataConfig`, y devuelve las
cuatro que `DataStep` escribe **sin condición** (`data/step.py:77-80`): el `target_col` **del
config** —no una constante: renombrarlo mueve la derivada, y hay test— más `label_status`,
`partition` y `ttd`, importadas de sus módulos y no redeclaradas.

Es la cara simétrica de `ROL_DERIVADA`: aquel dice *«este CAMPO nombra algo que produce el pipeline,
no lo exijas»*; éste dice *«esta COLUMNA la produce el pipeline, cuéntala como presente»*. El
primero mira el campo, el segundo el nombre, y hacen falta los dos.

⚠️ **Sólo entra en la comprobación de columna ausente, no en la del índice.** Que el pipeline vaya a
escribir una columna «partition» no dice nada sobre cómo se llama el índice del archivo, y mezclarlo
cambiaría el veredicto de una rama que no tiene este problema.

⚠️ **Riesgo declarado:** silenciar un error de tipeo que coincida por casualidad con un nombre
derivado. Se acota porque lo declara sólo la sección que de verdad las escribe —con `data` apagada
no se suma nada, con test— y porque el ancla del gate exige que una columna inventada se siga
acusando.

## 4. D-RAM-7 — una sección no se acredita a sí misma

La primera versión de D-RAM-6 usaba un conjunto **global** de columnas producidas, y la revisión
adversarial cruzada lo reprodujo:

```
data.schema.columns[0].name = "partition"   →  check_dataset: compatible=True
                                               corrida: muere en `data.schema`
```

`DataStep` valida el esquema en el **primer chequeo del primer paso**, mucho antes de que
`Partitioner` escriba nada. Al medirlo apareció además el caso hermano y más claro: la regla que
**construye** el target podía apuntar al target, y también salía compatible.

**D-RAM-7.** Las columnas que produce una sección **no acreditan declaraciones de esa misma
sección**. Las de `data` sirven a `survival`, `stability` y a cualquiera que corra después —que es
todo el valor de D-RAM-6—, y no a los campos de entrada de la propia `data`. Con su ancla: un test
comprueba que arreglar esto **no** reintroduce el falso positivo que D-RAM-6 cerró.

## 5. Los 14 campos condicionales, medidos (2026-08-03)

Esta sección los dejó como «trabajo siguiente, exige medir la condición de cada uno contra el
motor». Medidos uno a uno: 🔴 **no son un caso con el mecanismo listo, son CINCO patrones distintos,
y `columnas_inactivas` sólo resuelve uno de ellos.** Verificado ejecutando los motores, no leyendo.

| patrón | nº | campos | qué se hizo |
|---|---:|---|---|
| **A** · condición limpia sobre un campo **hermano** | **4** | `ifrs9.ead.ead_col`, `.drawn_col`, `.limit_col`, `ifrs9.lgd.lgd_col` | ✅ **cerrados**: rol declarado + su condición, con gate en los dos sentidos |
| **B** · la condición vive en el **padre** | 1 | `internal.lgd.lgd_col` (lo decide `InternalProvisioningConfig.method`) | ⛔ D-RAM-3 fija que los nombres son del propio modelo. Ampliarlo a rutas relativas es cambio de contrato por un solo caso |
| **C** · condición sobre el **DATO**, no sobre el config | 3 | `cmf.days_past_due_col`, `.debtor_id_col`, `.product_type_col` | ⛔ dependen de qué carteras trae el archivo. `columnas_inactivas` no ve el frame — es más cerca de `requisitos_incumplidos_por_perfil` |
| **D** · el motor **tolera la ausencia** | 4 | `cmf.category_col`, `.contingent_amount_col`, `.contingent_type_col`, `exposure.is_default_col` | ⛔ ni condición que apagar ni exigencia que declarar: columna legítimamente opcional. Pide vocabulario nuevo |
| **E** · estado no-`None` **inalcanzable** | 2 | `ifrs9.pd.rho_col`, `ifrs9.ead.exposure_profile_col` | ⛔ ver §6 |

**Lo que cerró el patrón A**, con su condición exacta:

- `ead_col` — inactiva salvo `method == "provided"`. **Era el peor de los catorce**: default `"ead"`
  contra un `method` que arranca en `ccf`, así que declararle el rol sin este mecanismo habría
  exigido **con el config de fábrica** una columna que el motor nunca abre.
- `drawn_col` / `limit_col` — inactivas salvo `method == "ccf"`. El simétrico exacto del anterior.
- `lgd_col` — 🔴 **su condición NO es el `method`**, y ahí estaba la trampa: dos de las tres ramas lo
  leen **sólo si `recovery_col is None`** (`lgd.py:128-132`, `:193-197`) y la tercera no lo toca
  nunca —su validador ya exige `recovery_col`—, de modo que la condición se cierra en un solo
  predicado sobre un hermano.

⚠️ **Los tres del patrón C tienen una salida conocida y su precio medido**: declararlos `input` sin
condición cierra un falso negativo real en cartera consumo y produce **tres falsos positivos** en una
cartera sólo comercial —que el motor soporta y ningún preset cubre—. Descartado por Cami el
2026-08-03: el gate de presets no distinguiría «es incondicional» de «este dataset casualmente los
trae», que es exactamente el falso verde que el repo persigue.

## 6. Los dos reservados, y por qué no llevan rol

`ifrs9.pd.rho_col` y `ifrs9.ead.exposure_profile_col` tienen **un único estado alcanzable: `None`**.
Cualquier valor informado levanta `IfrsConfigError` en un validador **incondicional**
(`ifrs9/config.py:164-169` y `:352-358`), y ninguna combinación de otros campos lo permite —medido
ejecutando ocho construcciones—. Cero lectores en el motor: sus únicos consumidores copian el valor
al `log_decision` de auditoría.

Declararles `column_role` no puede producir ni falso positivo ni falso negativo —`_columnas_de`
descarta los no-`str`, y `None` nunca emite declaración— **pero tampoco cierra nada**. Se dejan sin
rol con esta razón escrita (decisión de Cami, 2026-08-03): el campo sigue reservado para el consumo
diferido que su docstring documenta, que es para lo que existe.

## 7. Lo que esta enmienda NO resuelve

**Tampoco resuelve la mentira del config.** Con este mecanismo, declarar `ccf_col` bajo
`method='provided'` deja de avisarse, pero sigue siendo un config que nombra una columna que nadie
va a leer. Prohibirlo es la salida 2 de arriba y sigue disponible el día que se decida pagar su
coste de compatibilidad; las dos son compatibles entre sí.
