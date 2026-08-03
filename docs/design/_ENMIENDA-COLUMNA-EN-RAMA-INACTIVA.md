# Enmienda SDD — el preflight acusa una columna que el motor nunca abre

> **Estado:** aprobada e implementada (2026-08-03).
> **Enmienda a:** [`_ENMIENDA-PREFLIGHT-DATASET.md`](_ENMIENDA-PREFLIGHT-DATASET.md) (D-PRE-3, el
> vocabulario `column_role`) y [`_ENMIENDA-INVARIANTES-PREVIAS.md`](_ENMIENDA-INVARIANTES-PREVIAS.md)
> (D-INV-1, la invariante la declara el dominio que la impone).
> **Decisiones:** D-RAM-1 … D-RAM-5.

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

## 3. Lo que esta enmienda NO resuelve

**Los 14 campos condicionales de provisiones siguen sin rol.** El mecanismo que necesitan acaba de
nacer, pero declararlos exige medir la condición de cada uno contra el motor —que es el trabajo que
esta enmienda hizo para cinco— y no se hace a ojo. Queda como trabajo siguiente, con su lista en el
HANDOFF. El peor sigue siendo `ifrs9.ead.ead_col`: trae default `"ead"` y sólo se lee con
`method='provided'`, cuyo default es `ccf`, así que declararlo hoy exigiría con el config de fábrica
una columna que el motor nunca abre.

**Tampoco resuelve la mentira del config.** Con este mecanismo, declarar `ccf_col` bajo
`method='provided'` deja de avisarse, pero sigue siendo un config que nombra una columna que nadie
va a leer. Prohibirlo es la salida 2 de arriba y sigue disponible el día que se decida pagar su
coste de compatibilidad; las dos son compatibles entre sí.
