# Enmienda — una SUBSECCIÓN entera puede ser inerte, y hoy el preflight no puede saberlo

> Estado: **BORRADOR — pendiente de decisión de Cami**. Escrita el 2026-08-07 tras una revisión
> adversarial de `9bfccf6`. Decisiones `D-SUB-1…D-SUB-4`.
>
> Enmienda a **D-RAM-1** (`_ENMIENDA-COLUMNA-EN-RAMA-INACTIVA.md`).

## 1. Problema

`provisioning_internal` tiene dos métodos. Con `method='pd_lgd'` descompone la pérdida y lee la
subsección `lgd`; con `method='direct_loss_rate'` toma la tasa de pérdida de una columna y **la
subsección `lgd` entera queda inerte** — `_lgd_modelada` sale con `None` (`internal/engine.py:279-281`)
y `_parse_rows` conmuta a `loss_rate_col` (`:322`).

El preflight no puede saberlo, y desde `9bfccf6` eso tiene consecuencia visible. **Medido:**

| config | desajustes que el preflight declara bajo `lgd` |
|---|---|
| `direct_loss_rate` + `lgd.provided` (el default) | 1 — `lgd.lgd_col` |
| `direct_loss_rate` + `lgd.fractional_response` | 2 — `lgd.lgd_col`, `lgd.covariate_cols` |
| `direct_loss_rate` + `lgd.workout` | **5** — `recovery_col` y las cuatro de recuperos |

Y el control positivo: **esa misma corrida termina**. Con un archivo que sólo trae
`portfolio, exposure_amount, tasa_perdida, segmento` —ninguna de las cinco— el motor produce su
provisión y la card publica `lgd_method: None`.

🔴 **Es regresión parcial de `9bfccf6`.** Antes, `lgd.lgd_col` no declaraba `column_role`, así que el
preflight no lo miraba: el caso costaba **cero** desajustes. El commit le dio el rol —necesario para
que `columnas_inactivas()` pudiera suprimirlo en las ramas que no lo abren (D-LGD-13)— y de paso
abrió esta puerta. `POST /api/preflight` es `check_dataset` (`ui/routes.py:448`), así que esto es
rojo en pantalla para un usuario cuyo config funciona.

## 2. Por qué el mecanismo existente NO lo alcanza

`columnas_inactivas()` es exactamente el mecanismo para «este campo nombra una columna que esta
configuración no va a leer» (D-RAM-1). No sirve aquí por una razón estructural, no por un olvido:

1. **`_columnas_inactivas` sólo pregunta al PROPIO modelo** (`core/dataset_check.py:552-561`), y su
   docstring lo declara: *«Sólo se pregunta por los campos del propio modelo, que es donde vive la
   condición»* (`:574-575`). Aquí la condición vive un nivel **arriba**, en
   `InternalProvisioningConfig.method`; las ramas de LGD no ven a su padre y no deben.
2. **La recursión al submodelo no está guardada.** `_declaraciones` hace
   `yield from _declaraciones(valor, …)` (`:588`) **fuera** del `if … nombre not in inactivas` de
   `:583`. Así que aunque el padre declarase `"lgd"` inactivo, el barrido bajaría igual por sus hijos.

⚠️ El precedente sano está al lado y muestra la salida alternativa: `loss_rate_col` también declara
`column_role: "input"` (`internal/config.py:649`) pero su validador lo **prohíbe** cuando no se lee
(`:702-705`), así que viaja `None` y no declara nada. `lgd` no puede hacer eso: es un submodelo con
`default_factory`, y volverlo anulable cambia el schema y mueve la identidad.

## 3. Decisiones

### D-SUB-1 — «inactivo» pasa a significar el campo Y su subárbol

`_declaraciones` guarda la recursión: un campo que el modelo declare inactivo no emite su columna
**ni la de sus descendientes**.

```python
if nombre in inactivas:
    continue
if rol in ROLES:
    for columna in _columnas_de(valor):
        yield ruta, rol, columna
yield from _declaraciones(valor, f"{ruta}.")
```

🔴 **Medido: es no-op para los seis implementadores actuales.** `IfrsLgdConfig`, `IfrsEadConfig`,
`IfrsStagingConfig` y las tres ramas nuevas nombran **sólo campos de columna**, nunca submodelos, así
que hoy ninguno tiene subárbol que podar. El cambio no altera una sola declaración existente; sólo
hace expresable un caso que antes no lo era.

⚠️ Es la parte que **enmienda contrato**: hasta hoy «inactivo» significaba «no mires esta columna» y
pasa a significar «no mires esta rama». La lectura nueva es la que el nombre siempre sugirió.

### D-SUB-2 — el padre declara inerte la subsección que su método no abre

```python
def columnas_inactivas(self) -> frozenset[str]:
    """Con la tasa de pérdida directa, la subsección de LGD entera queda inerte."""
    return frozenset() if self.method == "pd_lgd" else frozenset({"lgd"})
```

Vive en `InternalProvisioningConfig`, que es **donde está la condición**. Cierra los tres casos de
la tabla del §1 a cero desajustes.

### D-SUB-3 — el gate aprende que un nombre inactivo puede ser un submodelo

`test_todo_campo_declarado_inactivo_existe_y_tiene_rol` exige hoy
`_rol(modelo, nombre) == ROL_ENTRADA` para **todo** nombre devuelto. Un submodelo no tiene
`column_role` y nunca lo tendrá. El gate pasa a exigir **una de dos** cosas, sin aflojar ninguna:

* si el campo declara un rol de columna → el rol tiene que ser `input` (como hoy), o
* si el campo es un **submodelo** → tiene que contener al menos una columna declarada aguas abajo.

La segunda mitad es lo que impide el uso vacuo: declarar inerte un submodelo que no aporta ninguna
columna no suprimiría nada y la línea mentiría, que es exactamente el modo de fallo que el gate
existe para cerrar.

### D-SUB-4 — se mide en los DOS sentidos, como toda pieza que puede callar

D-RAM-4 ya lo exige y aquí pesa más: este supresor puede silenciar **cinco** columnas de una vez. El
oráculo escrito a mano gana su primera fila de `provisioning_internal`, con el config que APAGA la
subsección y el que la ENCIENDE — hoy sus nueve filas son todas de `provisioning_ifrs9`, y por eso
este caso no lo veía nadie.

## 4. Lo que NO se propone

* **No** se quita el `column_role` de `lgd_col` ni de las cinco columnas nuevas. Revertirlo cerraría
  el falso positivo perdiendo la cobertura de preflight que D-LGD-13 pedía, y dejaría a las ramas
  modeladas sin poder declarar nada inerte.
* **No** se hace `lgd` anulable. Mueve schema e identidad para arreglar un caso de preflight.
* **No** se toca `requisitos_incumplidos`: contesta otra pregunta.

## 5. Coste medido

| | |
|---|---|
| Archivos de `src/` | 2 (`core/dataset_check.py`, `provisioning/internal/config.py`) |
| Líneas de cambio en el núcleo | 4 |
| Implementadores afectados | **0** de 6 (medido) |
| `config_hash` | **sin mover** — no nace ningún campo |
| Gates a tocar | 1 (`test_columna_en_rama_inactiva.py`), más su fila de oráculo |

## 6. Riesgo declarado

El cambio es en `core/dataset_check.py`, que es el núcleo del preflight y lo consumen
`check_dataset` por código y `/api/preflight` por la red. Su modo de fallo es **callar de más**: un
`columnas_inactivas()` mal escrito en el futuro podría podar un subárbol entero sin que se note. Es
la razón de D-SUB-3 (no se puede declarar inerte un submodelo sin columnas) y de D-SUB-4 (el oráculo
mide encendido y apagado). El modo contrario —el falso positivo— es el que hay hoy y se ve en
pantalla.
