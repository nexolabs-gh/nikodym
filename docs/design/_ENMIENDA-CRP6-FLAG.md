# Enmienda SDD — CRP-6: la semántica única del flag, y la marca que no se puede gobernar

- **Estado:** APROBADA por Cami (2026-07-25), con adopción **partida en dos bloques** (§7)
- **Fecha:** 2026-07-25
- **Enmienda a:** [`_CONTRATO-RESOLUCION-PARAMETROS.md`](_CONTRATO-RESOLUCION-PARAMETROS.md) §CRP-6 y
  [`_ENMIENDA-CRP-IFRS9.md`](_ENMIENDA-CRP-IFRS9.md) §2.3 y §3.6
- **Afecta a:** SDD-16 (`provisioning/ifrs9`), SDD-19 (`survival`), SDD-20 (`forward`),
  SDD-22 (`validation`)
- **Decisiones:** D-CRP6-1 … D-CRP6-7

## 1. Por qué existe esta enmienda

CRP-6 se escribió en dos frases: el flag pasa a significar *«¿una marca declarada emitida durante la
corrida la detiene?»* en todas las capas, y lo que hoy significa otra cosa —el chequeo PIT de
IFRS 9— «se renombra a lo que hace». Al medir el código antes de programar, las dos frases se
rompen por motivos distintos, y una de ellas destapa un bloqueo que ningún censo previo vio.

Esta enmienda no reabre el objetivo de CRP-6. Reabre **su alcance**, que estaba sobredimensionado en
un eje y subdimensionado en otro.

## 2. El censo, re-medido contra la pregunta que CRP-6 define

El censo de `_ENMIENDA-CRP-IFRS9.md` §2.3 clasificó las siete capas por **mecanismo** (gate de
config, gate de runtime, mixto, no-op, gate compuesto) y contó cinco semánticas. Esa cuenta es
correcta en su unidad. Pero la unidad que decide el trabajo es otra: **¿el flag gobierna una marca
declarada, sí o no?** Medido así, el cuadro es bastante menos malo.

| Capa | Marca que gobierna | Dónde comprueba | ¿Conforme? |
|---|---|---|---|
| `provisioning/config.py:298` | `DATO-INSTITUCIONAL-PROV-4` | runtime (`orchestrator.py:262`) | **sí** — patrón D-SEG-7 |
| `provisioning/internal/config.py:209` | `DATO-INSTITUCIONAL` (nulo en insumo) | runtime (`engine.py:389`) | **sí** |
| `stress/config.py:656` | `DATO-INSTITUCIONAL-STR-2` | config (`config.py:938`) | **sí** |
| `stress` (3 sitios) | `_INSTITUTIONAL_OFFICIAL` / `_DOMINANCE` / `_LGD` | runtime (`engine.py:1835`, `2003`, `2483`) | **sí** |
| `validation/evaluator.py:422` | marcador de backtesting | runtime | **sí** |
| `validation/config.py:415` | *(no la nombra)* | config | **parcial** |
| `forward/config.py:650` | `DATO-INSTITUCIONAL-FWD-1` | config | **parcial** — AND con un 2.º flag |
| `provisioning/ifrs9/config.py:666` | **ninguna** | config | **no** |
| `survival/config.py:301` | ninguna (no-op) | — | **no** |

**Cinco de las siete capas ya cumplen CRP-6.** Lo que varía entre ellas es *dónde* comprueban, y eso
no es otra semántica del flag: comprobar en la entrada cuando el config ya permite demostrar la
carencia es exactamente lo que CRP-5 manda. Confundir «dónde comprueba» con «qué significa» es lo que
infló la cuenta a cinco semánticas.

Los no conformes reales son **dos** (`ifrs9`, `survival`) más dos matices (`forward`, `validation`).

### 2.1 El flag de `ifrs9` no gobierna ninguna marca — y su `False` viola CRP-5

`fail_on_falta_dato` en IFRS 9 decide si un config PIT inconsistente (`pit_mode='apply_vasicek'` sin
`pd.rho` o sin el factor sistémico Z) falla al validar el config o más tarde. Con `False` **no hay
ruta degradada**: `_apply_vasicek` (`engine.py:763-778`) levanta igual. La suite ya lo cementa en
`tests/unit/test_ifrs9_engine.py:384`, cuyo propio docstring dice que no existe ruta FALTA-DATO para
`rho`.

O sea: el único efecto de `False` es **mover una validación al medio del cálculo**, que es
literalmente lo que CRP-5 acaba de prohibir y lo que se corrigió en `afa3403`. Renombrar el campo,
como manda el contrato, **conservaría esa opción** y además costaría el primer migrador del proyecto
(`NikodymBaseConfig` es `extra="forbid"`, `_MIGRATORS` está vacío), `schema.json`, cuatro fixtures del
front y una recaptura de demo.

### 2.2 El bloqueo que ningún censo vio: `FALTA-DATO-IFRS-4` se emite en toda corrida

`ead.py:137-142` añade `FALTA-DATO-IFRS-4` a **todas** las filas, por los dos métodos (`provided` y
CCF), sin rama que lo evite: declara que el perfil EAD(t) longitudinal está diferido a CT-3, que es
una propiedad del motor y no del dato entregado.

Medido sobre el motor, con la institución entregando la EAD real (`method="provided"`):

```
card.falta_dato      = ('FALTA-DATO-IFRS-4',)
warning_codes fila 0 = ('FALTA-DATO-IFRS-4',)
fail_on_falta_dato   = True (default)
```

**Consecuencia:** conectar el flag de `ifrs9` a la semántica única tal como está escrita haría
**abortar toda corrida de IFRS 9**, con el flag en su valor por defecto, en los tres presets
(`ui/presets.py:420`, `608`, `633`, `751`, `811`) y en la demo pública. CRP-6 no es implementable en
esa capa sin decidir antes qué marcas puede gobernar un flag.

Esto es una **dependencia que el orden de adopción no vio**: la enmienda asignó la taxonomía de los
warnings a CRP-4, que va *después* de CRP-6. No hace falta reordenar —CRP-4 sigue después—, pero sí
que CRP-6 fije el criterio que CRP-4 aplicará al inventario de nueve.

### 2.3 El preset de IFRS 9 se miente a sí mismo, y sólo se descubre al implementar el flag

La sección `survival` del preset que se entrega al usuario (`ui/presets.py:743`, `751`) declara
`fail_on_falta_dato: True` —«detente ante una carencia declarada»— y al mismo tiempo entrega
`kaplan_meier.confidence_level: None`, que **es** una carencia declarada: `_global_warnings`
(`kaplan_meier.py:608-611`) emite `DATO-INSTITUCIONAL-SUR-3` exactamente por eso. Medido sobre el
preset real:

```
preset survival · fail_on_falta_dato = True
preset survival · confidence_level   = None
marcas globales que emite            = ('DATO-INSTITUCIONAL-SUR-3',)
```

Hoy la contradicción no se nota porque el flag es no-op en esa capa (§2). El día que se implemente,
**el preset se aborta a sí mismo**. No es un efecto colateral de CRP-6: es la incoherencia que CRP-6
existe para destapar, y estaba publicada.

A diferencia de `FALTA-DATO-IFRS-4`, `SUR-3` **sí es gobernable** por D-CRP6-2 —basta declarar
`confidence_level` y `confidence_transform`—, así que el criterio no la absuelve: hay que arreglar el
preset.

## 3. Las decisiones

### 3.1 · D-CRP6-1 — La semántica única, enunciada de forma decidible

`fail_on_falta_dato` significa, en las siete capas: **«una marca declarada *gobernable* emitida por
esta capa detiene la corrida (`True`) o queda registrada en el resultado y la corrida sigue
(`False`)»**.

Se admite comprobarla **en el config** cuando la carencia ya es demostrable desde el config, y **en
runtime** cuando sólo se conoce al calcular. No son dos semánticas: es CRP-5 aplicado —validar lo
antes posible—. Lo que queda prohibido es que el momento de la comprobación dependa del propio flag
(§2.1).

### 3.2 · D-CRP6-2 — Marca **gobernable** vs marca **estructural**

Una marca declarada es **gobernable** si existe alguna entrada válida con la que la capa **no** la
emita. Es **estructural** si el motor la emite en toda corrida por una capacidad diferida propia.

El flag gobierna las gobernables. Las estructurales **siempre** se registran en el resultado y
**nunca** detienen la corrida, porque el usuario no tiene ninguna acción que las evite: detenerlas no
es fail-fast, es deshabilitar el motor.

El criterio es decidible y comprobable con un test: *¿existe una entrada válida sin esa marca?* Con
él, `FALTA-DATO-IFRS-4` es estructural (§2.2) y `FALTA-DATO-IFRS-6` es gobernable (sólo aparece si la
term-structure de forward trae LGD, `engine.py:250`).

**Que una marca sea estructural no la absuelve**: dice que su arreglo es aumentar la capacidad del
motor —CT-3 para IFRS-4—, no rotularla ni abortar por ella. La lista de estructurales es deuda
declarada, y CRP-7 ya tiene asignado el caso de IFRS-4.

### 3.3 · D-CRP6-3 — En `ifrs9` el chequeo PIT pasa a ser **incondicional** (decidido por Cami)

**Corrige al contrato, que mandaba renombrar.** El chequeo PIT deja de mirar el flag y se ejecuta
siempre, siguiendo el patrón de la capa de referencia de CRP-5 (`cmf/engine.py:443`, `446-462`), que
valida el dominio de cartera incondicionalmente en la entrada.

Nadie que hoy corriera bien pasa a fallar: hoy ese config falla igual, sólo que más tarde. El único
comportamiento que cambia es el de quien construye el config y **nunca** ejecuta el motor. Sin
rename, sin migrador, sin recaptura de demo.

Liberado el nombre, `fail_on_falta_dato` toma en `ifrs9` la semántica de D-CRP6-1 sobre las marcas
**gobernables** de la capa: hoy `FALTA-DATO-IFRS-6`. La comprobación va donde las marcas se
consolidan (`engine.py:519`, `_build_card`), que es el único punto donde la capa las conoce todas.

### 3.4 · D-CRP6-4 — `survival` implementa el flag sobre sus tres marcas

Deja de ser campo reservado. Gobierna `DATO-INSTITUCIONAL-SUR-1/2/3`, las tres gobernables: cada
una depende de la entrada.

**No se elimina**, confirmando E-CRP-6: sería ruptura pública sin ruta de migración.

**Corregido al programarlo — el censo de emisores estaba incompleto.** La v1.0 localizaba las tres
marcas en `kaplan_meier.py:55-57`. Medido, `SUR-1` tiene **cuatro** emisores: `kaplan_meier.py:585`,
`cox_aft.py:889`, `discrete_hazard.py:968` y el propio `step.py:528`, que la emite cuando ninguna
grilla fue declarada y hay que caer a los tiempos observados. El alcance no crece, pero **el lugar
del gate sí importaba**: va en `step.py::_card_from_model`, el único punto donde la capa conoce
todas sus marcas vengan del motor o del step —análogo exacto del `_build_card` de IFRS 9—. Puesto
dentro de un motor, la carencia del step se habría escapado.

**`survival` no declara ninguna marca estructural, y se midió en los dos sentidos.** La analogía
con IFRS 9 invita a copiar una lista de estructurales; aquí sería falsa. `SUR-1` desaparece
declarando `horizon_periods` o `evaluation_times`; `SUR-3`, declarando `confidence_level`. La
llamada va con `structural=()` **a propósito**, y el comentario en el código lo dice para que nadie
lo lea como un olvido.

### 3.5 · D-CRP6-5 — `forward` pierde el AND

`config.py:650` exige hoy `fail_on_falta_dato AND validation.fail_on_missing_scenario_paths`. Un
segundo flag que apaga al primero es apagado silencioso: el usuario deja `fail_on_falta_dato=True` y
la carencia no lo detiene. `DATO-INSTITUCIONAL-FWD-1` pasa a colgar sólo de `fail_on_falta_dato`.

**Corregido al programarlo.** La v1.0 de esta decisión decía que `fail_on_missing_scenario_paths`
«se conserva con su significado propio». Es falso, y lo mostró el código: ese `if` era su **único**
lector en todo `src/`. Quitar el AND y dejar el campo lo habría convertido en un no-op nuevo —el
mismo pecado que esta enmienda le reprocha a `survival`—, y en forward ambos flags gobiernan
exactamente el mismo aviso, así que uno sobra por construcción.

Se retira el específico y se conserva el del contrato transversal, con el precedente propio del
repo: `DeprecationWarning`, no borrado (`provisioning/config.py:422-428`). El aviso se emite **sólo**
cuando el campo llega en `False`, que es el único valor cuyo efecto cambia; en `True` el
comportamiento es idéntico y no hay nada que avisar.

### 3.6 · D-CRP6-6 — `validation` nombra la marca que gobierna

`config.py:415` levanta sin nombrar código, a diferencia de sus seis pares. El mensaje pasa a
declarar su marca, de modo que el volcado de auditoría la registre igual que las demás.

### 3.7 · D-CRP6-7 — Lo que esta enmienda **no** toca, dicho a propósito

La imputación a **cero** de `provisioning/internal` cuando el flag está en `False` (`engine.py:389`)
cumple CRP-6 —marca y sigue—, pero imputar cero a una PD o una LGD ausente **subestima la
provisión**. Es un defecto de resolución de parámetros, no de semántica del flag: entra por CRP-1
(qué vías son admisibles) y se registra aquí para que no se pierda.

## 4. Superficies afectadas

- **Copy público** (las siete `description` viajan a `schema.json` → tooltip del `FieldRenderer`):
  las de `ifrs9` y `survival` describen hoy fielmente un comportamiento que deja de ser cierto, así
  que **deben** cambiar en el mismo commit que el código.
- `schema.json` y los fixtures del front que lo embeben.
- **No** cambia ningún nombre de campo → sin migrador, sin ruptura de YAML, sin recaptura de demo.

## 5. Criterios de aceptación

1. Test parametrizado sobre las **siete** capas: con `True`, una marca gobernable emitida detiene la
   corrida; con `False`, queda en el resultado y la corrida termina. (Criterio 3 del contrato.)
2. Test del criterio de D-CRP6-2: una corrida de IFRS 9 con EAD entregada y `fail_on_falta_dato=True`
   **termina** y su `card.falta_dato` conserva `FALTA-DATO-IFRS-4`.
3. Los tests nuevos **fallan** contra el código anterior; se verifica ejecutándolos, no razonándolo.
4. `ruff`, `mypy` y la suite completa verdes; gates de copy público verdes.

### 3.8 · D-CRP6-8 — El preset declara sus intervalos de confianza

⚠️ **La premisa de esta decisión era falsa, y la medición lo mostró antes de programarla.** §2.3
afirmaba que el preset F4 «se contradice a sí mismo»: `fail_on_falta_dato=True` junto a la carencia
`SUR-3`. Corrido el preset real sobre su dataset real (`ifrs9_retail_latam`, 6.000 filas), emite
`falta_dato=()`. No hay contradicción: el preset declara `method="discrete_hazard"`, y `SUR-3` sólo
la emite `kaplan_meier.py:611`, de modo que `confidence_level=None` **nunca se lee**. Con el flag ya
implementado el preset sigue corriendo igual.

**La decisión no cambia; cambia su razón, que es lo que había que reescribir.** `method` es editable
desde el formulario del UI instalable. Antes del bloque A eso daba lo mismo. Ahora, quien parta del
preset F4 y elija `kaplan_meier` en el selector vería **abortar una corrida que hoy termina bien** —
y el aborto sería correcto según el contrato, lo que lo vuelve peor: no es un bug que se arregle
después, es un preset publicado que deja de correr al tocar un control legítimo. Declarar los
intervalos lo previene.

Es el tercer caso de la misma clase en esta enmienda (el flag de `ifrs9` que no gobernaba nada,
`FALTA-DATO-IFRS-4` emitida en toda corrida, y ahora esto). **Un censo describe el mecanismo; sólo
correr el motor dice qué pasa.**

De las tres salidas a §2.3 —declarar los intervalos, poner el flag en `False`, o reclasificar
`SUR-3`— se toma la primera:

- **Declarar `confidence_level` y `confidence_transform`** deja el preset coherente, conserva el
  default `True` y de paso el preset gana bandas de confianza, que es mejor producto.
- Poner el flag en `False` haría al preset honesto pero **desprotegido**: dejaría de detenerse también
  ante `SUR-2` (curva sin un solo evento), que sí es grave.
- Reclasificar `SUR-3` —defendible, porque una opción no ejercida no es un dato que falte— es
  **taxonomía, o sea CRP-4**, y se registra ahí en vez de resolverse de paso aquí.

**Coste y secuencia.** Cambiar el preset mueve `config_hash` y obliga a recaptura de demo patrón C-D
con bump de versión previo. Esa recaptura **ya estaba comprometida** por el P2 del handoff (el preset
F4 sale de `pit_mode="ttc_only"`), que se difirió justamente para no recapturar dos veces. Los dos
cambios deben entrar en la **misma** recaptura.

## 6. Riesgos

- **`survival` pasa de no-op a gobernar tres marcas con el flag en `True` por defecto.** Riesgo
  medido y cerrado: el preset de IFRS 9 no emitía ninguna marca ni antes ni después (ver D-CRP6-8),
  y de los 4.349 tests el único que hubo que tocar fue el **golden del `config_hash` del F4**, que
  falló exactamente como debía al cambiar el preset y forzó la recaptura al mismo lote en vez de
  dejarla pendiente en silencio. El riesgo real que sí queda vivo es
  el del **usuario existente** cuyo config no declara grilla: hasta ahora recibía `SUR-1` como aviso
  y desde el bloque B su corrida se detiene. Es exactamente lo que el flag promete y su default
  siempre dijo, pero es un cambio de comportamiento observable → va en las notas del release.
- El criterio gobernable/estructural se fija aquí y lo hereda CRP-4 para los nueve warnings. Si el
  inventario de CRP-4 encuentra un caso que no clasifica, se reabre esta decisión, no se parchea.
- La recaptura de demo tiene dos reincidencias registradas por árbol sucio (patrón C-D exige árbol
  limpio y commit entre capturas). Es el paso con más historial de error de este plan.

## 7. Adopción en dos bloques (decidido por Cami, 2026-07-25)

La enmienda se implementa partida por una frontera técnica, no por comodidad: **si el cambio mueve
`config_hash`**. Lo que lo mueve arrastra recaptura de demo, y la recaptura conviene hacerla una sola
vez.

**Bloque A — sin `config_hash`, se implementa ya.** D-CRP6-1, D-CRP6-2, D-CRP6-3, D-CRP6-5, D-CRP6-6
y el gate parametrizado de §5.1. Toca `schema.json` sólo por el copy público de las `description`,
que no entra en el hash.

**Bloque B — mueve `config_hash`, va con el P2 del handoff.** D-CRP6-4 (survival implementa el flag)
y D-CRP6-8 (el preset declara sus intervalos), junto con la salida del preset F4 de
`pit_mode="ttc_only"`, el bump de versión y **una** recaptura patrón C-D.

**Consecuencia asumida y declarada:** entre A y B, `survival` sigue siendo el campo no-op que esta
misma enmienda condena. Se acepta porque cerrarlo antes obligaría a la segunda recaptura que el P2 se
difirió justamente para evitar. El bloque B no es opcional ni «cuando se pueda»: sin él, CRP-6 no
está cumplido y el criterio 1 de §5 no pasa para las siete capas.
