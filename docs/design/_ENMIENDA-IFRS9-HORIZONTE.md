# Enmienda SDD — horizonte 12m de IFRS 9: la verificación que el motor no hace

> **Estado: PROPUESTA — requiere OK de Cami antes de programar.** No se ha escrito una línea de
> motor. Lo único ejecutado es la corrección del texto de SDD-16, que afirmaba un aviso inexistente
> (§1).
>
> **Base:** `main` = `655f7d2`.
> **Autor / Fecha:** DanIA / 2026-07-25.

| Campo | Valor |
|---|---|
| **Problema** | `horizon_12m_periods` asume periodicidad mensual por default y nadie lo contrasta: dos configuraciones plausibles producen una ECL de Stage 1 incorrecta **en silencio** |
| **Enmienda a** | SDD-16 (§8 casos borde, §9 audit trail, ficha IFRS-2) |
| **No toca** | La clasificación de IFRS-1…IFRS-6, ni el contrato de `core/markers.py`, ni la firma de `marginal_to_horizon` |
| **Release** | `1.6.0` — `provisioning/ifrs9` es experimental; el pipeline F1 estable no participa |

---

## 1. El problema, medido

`IfrsPdConfig.horizon_12m_periods: int = Field(default=12, …)` (`provisioning/ifrs9/config.py:125`)
declara cuántos períodos de la term-structure cubren 12 meses. Su única validación es `ge=1`. El
`@model_validator` `_check_pd` no lo mira, y `marginal_to_horizon`
(`provisioning/ifrs9/pd_pit.py`) valida columnas, rango de `pd_marginal` y `period >= 1` — nada
sobre la curva contra la que ese horizonte se aplica.

El corte del horizonte es una sola línea:

```python
within_12m = working["period"] <= horizon_periods
```

De ahí salen dos modos de fallo, ninguno de los cuales avisa:

- **A · El horizonte alcanza o pasa el soporte de la curva (`H_12m ≥ T_max`).** La máscara queda
  toda verdadera, así que `pd_12m == pd_life`. **La ECL de Stage 1 se vuelve numéricamente idéntica
  a la de Stage 2/3**, que es exactamente la distinción que IFRS 9 existe para hacer. La corrida
  termina `done`, la card no dice nada y los totales se ven razonables.
- **B · El default no corresponde a la periodicidad real.** Una institución con curva trimestral que
  no toca el campo acumula **12 trimestres —tres años— de PD marginal** y los reporta como PD a 12
  meses. Aquí no hay degradación visible: hay un número inflado con etiqueta correcta, que es peor,
  porque sobrevive a una revisión que mire la coherencia interna del informe.

Ambos son sobreestimaciones —contablemente conservadoras— pero **incorrectas**, y en un motor de
provisiones un número conservador equivocado sigue siendo un número equivocado del que hay que
responder ante el regulador.

**Lo que sí existía era la promesa.** SDD-16 §8 decía «warning; … y se registra
`DATO-INSTITUCIONAL-IFRS-2`», y §9 lo listaba en el audit trail junto a `T_max` y a la unidad
temporal. `git grep IFRS-2 src/ tests/ web/src/` devuelve **cero**, y `git log -S` confirma que
nunca estuvo: no es un código que se borró, es uno que jamás se escribió. Ese texto ya fue
corregido para que describa el comportamiento real; esta enmienda diseña el arreglo.

**El motor tiene con qué verificar y no lo usa.** `_TS_REQUIRED_COLUMNS` incluye `time_value` como
columna **obligatoria**, y `ecl.py` ya la consume como fracción de año en el descuento
(`discount_convention="annual_eir_year_fraction"`). El supuesto «`time_value` está en años» ya lo
hace el motor para descontar; no verificarlo para el horizonte es una inconsistencia interna, no una
falta de información.

## 2. Decisión: un aviso, dos gatillos (D-HOR-1)

Se añade **un** aviso declarado nuevo, `FALTA-DATO-IFRS-7`, que dispara si se cumple **cualquiera**
de las dos condiciones. La causa raíz es una sola —el motor no contrasta el horizonte declarado
contra la curva recibida— y partirla en dos códigos obligaría al lector a saber cuál de los dos
mirar antes de saber que hay un problema.

- **Gatillo A — `horizon_12m_periods >= T_max` observado**, con `T_max = max(period)` de la
  term-structure preparada. La igualdad entra: con `H_12m == T_max` la máscara ya es toda verdadera.
- **Gatillo B — la unidad no cuadra.** Sea `tv` la mediana de `time_value` en
  `period == horizon_12m_periods`; dispara si `tv` cae fuera de `[0.5, 2.0]`. La tolerancia es
  deliberadamente ancha: absorbe convenciones de calendario (365/360, 12×30) y sólo caza el
  desalineamiento de **orden de magnitud**, que es el que hace daño. Si el período del horizonte no
  existe en la curva, el gatillo A ya disparó.

**Marca: `FALTA-DATO`, no `DATO-INSTITUCIONAL` (D-HOR-2).** Aquí hay dos cosas que la ficha de
IFRS-2 tenía empaquetadas y esta enmienda separa. *Declarar* la periodicidad es de la institución:
sólo ella sabe si su curva es mensual. Pero *verificar que lo declarado sea coherente con lo
recibido* es del motor, y hoy no lo hace. Por la regla de que **una capacidad diferida es del motor
aunque el parámetro lo escriba el usuario** (precedente `FWD-8`), el aviso que cubre la verificación
omitida nace `FALTA-DATO`. IFRS-2 se queda como requisito documentado, sin código emitido.

**Aviso, no excepción (D-HOR-3).** El precedente de `rho_col` —detener la corrida en vez de aplicar
un escalar en silencio— es tentador, y el gatillo B parece un error de configuración. Pero la unidad
de `time_value` la fija la institución aguas arriba (`DATO-INSTITUCIONAL-SUR-1` cubre justamente
«horizonte lifetime y unidad temporal»): el motor **infiere** el desajuste, no lo constata. Un
fail-fast sobre una inferencia rompe corridas legítimas con convenciones que no anticipamos, y quien
paga es el usuario que sí tenía razón. Se declara y se deja decidir. Quien quiera el fail-fast ya
tiene `fail_on_falta_dato=True`, que es precisamente para lo que existe: **el aviso lo convierte en
bloqueante sin código nuevo**.

## 3. Alcance

Cada eslabón sale del patrón de `FALTA-DATO-IFRS-6`, que es el aviso condicional que ya funciona de
punta a punta:

| Archivo | Cambio |
|---|---|
| `provisioning/ifrs9/engine.py` | Constante `_WARNING_HORIZON_MISMATCH` + predicado del gatillo + append condicional junto al de IFRS-6 |
| `provisioning/ifrs9/step.py` | `ifrs9_pd_horizon` registra el `T_max` **observado** y la evidencia de unidad, no sólo los dos campos de config |
| `report/prose.py` | Entrada en `_IFRS9_WARNING_LABELS`. **No es opcional**: `renderer.py` retira `warning_codes` de las tablas, así que un código sin label es invisible en el entregable |
| `methodology.py` | Frase metodológica, replicando el patrón de IFRS-4 |
| `tests/unit/test_ifrs9_engine.py`, `test_ifrs9_step.py` | Espejo del bloque de IFRS-6: positivo por gatillo, negativos, `card.falta_dato`, `warning_codes` por fila, prosa |

**Blast radius a resolver antes de dar por verde.** Hay aserciones de **tupla exacta** que cambian
si alguna fixture cae en la condición: `test_ifrs9_engine.py:178` (`== ("FALTA-DATO-IFRS-4",)`),
`:193` (ídem sobre `card.falta_dato`), más fixtures en `test_report_builder.py:878` y
`test_methodology.py:157`. Y `ui/presets.py:764` fija `horizon_12m_periods: 1` con
`term_structure_source: "survival"`: **hay que comprobar si el preset F4 empieza a emitir el aviso**
—no debería, con `H_12m = 1 < T_max` y `time_value ≈ 1` por período anual, pero eso se verifica
corriendo el preset, no razonando—. Si emite, cambia la demo publicada y el número insignia, y eso
es decisión aparte.

`_CONTRATOS-TRANSVERSALES.md` §4 declara `provisioning/ifrs9` código regulatorio a **100 % de
cobertura**: cada rama nueva necesita test, sin excepción.

**Nota de lectura:** `D-IFRS-7` ya existe en SDD-16 como identificador de una *decisión* (la de `rho`
sin default). `FALTA-DATO-IFRS-7` vive en el espacio de nombres de los *avisos*, donde 7 es el
siguiente libre. Coinciden en el número y no en la cosa; por eso las decisiones de esta enmienda se
numeran `D-HOR-*` y no `D-IFRS-*`.

## 4. Criterio de aceptación

1. Una term-structure con `H_12m ≥ T_max` emite `FALTA-DATO-IFRS-7` en `warning_codes` de cada fila
   afectada y en `card.falta_dato`, y la prosa del informe lo explica **sin nombrar el código**.
2. Una curva trimestral con `horizon_12m_periods` en su default de 12 emite el aviso por el gatillo B.
3. Una curva mensual con `horizon_12m_periods = 12` y `T_max > 12` **no** emite: el falso positivo es
   el modo de fallo que mata a un aviso, porque enseña a ignorarlo.
4. Los tres tests nuevos se verifican **fallando contra el código actual** antes de integrarse.
5. El preset F4 de la demo corre y se declara explícitamente si emite o no, con la corrida a la vista.
6. Cobertura 100 % de las ramas nuevas; `mypy --strict` y `ruff` verdes; CI 16/16.

## 5. Lo que esta enmienda deja fuera a propósito

- **Inferir la periodicidad y corregir `horizon_12m_periods` sola.** El motor declararía haber
  entendido un dato que la institución no confirmó. Se declara el desajuste; el número lo arregla
  quien tiene la autoridad para hacerlo.
- **Tocar `DATO-INSTITUCIONAL-SUR-1`** o la frontera con survival. El aviso vive en IFRS 9, que es
  donde se conoce la causa — el mismo criterio con el que `_backtesting_blocker` decide su marca.
- **Reclasificar IFRS-1, 3 y 5.** Son requisitos documentados y se quedan como están; lo único que
  cambia es que SDD-16 ahora lo dice explícitamente en vez de dejarlo inferir.
