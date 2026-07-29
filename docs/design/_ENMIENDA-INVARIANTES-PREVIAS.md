# Enmienda SDD — el config se contradice a sí mismo y nadie lo dice hasta el paso 8

> **Estado:** aprobada e implementada (2026-07-29).
> **Enmienda a:** [`_ENMIENDA-PREFLIGHT-DATASET.md`](_ENMIENDA-PREFLIGHT-DATASET.md) (D-PRE-1…D-PRE-9),
> SDD-23 §4 (comprobación sin correr).
> **Decisiones:** D-INV-1 … D-INV-8.

## 0. El defecto que la origina

Medido con HMEQ el 2026-07-29, durante el ensayo D1 del webinar:

```
partición aleatoria + stability.temporal_axis = "period" (su default)

check_dataset  → compatible=True, mismatches=0, uninspected=()      ← "todo bien"
check_pipeline → executable=True, 10 pasos                          ← "todo bien"
run            → status=failed, paso 8 de 10, a los 4,4 s
                 StabilityDataError (stability/evaluator.py:665)
```

Las dos superficies que existen para responder *«¿puedo correr esto?»* dicen que sí, con la señal
más fuerte que saben emitir —cero desajustes, cero secciones sin mirar—, sobre un config que muere
con todo el cómputo ya pagado. Es la familia que persigue `test_seccion_opaca_invariante.py` y que
D-PRE-9 declara la peor respuesta posible: **afirmar «todo bien» sobre lo que no se miró.** Pero por
una vía nueva: aquí no hay ninguna sección opaca, y ningún campo nombra una columna que falte. Lo
que falla es una **invariante interna del config** —`temporal_axis ≠ "none"` exige una columna de
período, declarada o inferible— que ninguna de las dos superficies comprueba porque ninguna de las
dos existe para eso.

## 1. Lo que la medición dice, antes de diseñar nada

El HANDOFF de la sesión anterior avisaba: *«decidir si va en `check_pipeline` o en el preflight, y
sobre todo CUÁNTAS invariantes más de este tipo hay. No dar por hecho que es sólo `stability`.»*
Se midió, y **no es sólo `stability`**.

### 1.1 El censo

Un barrido de `src/` buscó puntos que levantan **durante la ejecución de un paso** por una
combinación de campos del propio config que se podía haber detectado antes. Devolvió 13 candidatas.
Ocho se llevaron al banco de pruebas —mutar el config de HMEQ, preguntar a las dos superficies,
correr de verdad— y el resultado es éste:

| caso | invariante | preflight | pipeline | corrida |
|---|---|---|---|---|
| A1 | `stability.temporal_axis` ≠ `none` sin columna de período | OK | OK | **falla** en `stability` |
| A3 | `data.partition.strategy.stratify_by` inexistente | OK | OK | **falla** en `data` |
| A7 | `data.partition.strategy.oot_from` no parseable como fecha | OK | OK | **falla** en `data` |
| A9 | `validation.families` vacío | OK | OK | **falla** en `validation` |
| A10 | `stability.comparisons` con duplicados | OK | OK | **falla** en `stability` |
| A11 | `performance.partitions` con duplicados | OK | OK | **falla** en `performance` |
| C2 | `report.sections.required_sections` nombra un dominio apagado | OK | OK | **falla** en `report` |

**Siete de siete confirmadas en vivo**, cada una con las dos superficies en verde. (La octava —
special values sobre una columna inexistente— quedó **sin veredicto**: la mutación de prueba fue
rechazada por `model_validate`, así que no se pudo aislar la invariante de la validación de forma.
No se cuenta ni como confirmada ni como refutada.)

### 1.2 El dato que decide el diseño

**Ninguna de las siete la caza `check_pipeline`**, y no por un olvido: `check_pipeline` resuelve el
**DAG de pasos** —qué correría y en qué orden— y esa pregunta no tiene nada que ver con éstas. La
hipótesis natural («va en `check_pipeline`, que ya resuelve el pipeline») describe el sitio correcto
para una pregunta distinta de la que hay que hacer.

Y el reparto por **insumos** no es uniforme:

- **A7, A9, A10, A11, C2** son invariantes de **config puro**: se deciden sin mirar el dataset.
- **A1 y A3** necesitan además los **nombres de columna** del dataset.

### 1.3 Lo que la medición desmintió

- **A1 no es una incompatibilidad entre partición aleatoria y eje temporal.** Se midió la dirección
  positiva: HMEQ + una columna `period` + partición **aleatoria** corre hasta `done` en 4,9 s. La
  invariante es sobre la existencia de la columna, no sobre la estrategia de partición. Una
  comprobación escrita contra la estrategia habría dado falsos positivos.
- **La columna del CSV sobrevive el pipeline hasta el frame de `stability`** (con
  `keep_structural_columns: true`), así que la ausencia en el dataset crudo implica la ausencia en el
  frame. La implicación vale en **una sola dirección**, y de ahí D-INV-4.

### 1.4 El agujero estructural que el censo destapa, y que esta enmienda NO cierra

Tres causas distintas producen las trece, y se arreglan distinto:

1. **Campos de columna sin `column_role` declarado** (`special_values[].columns`, `stratify_by`, las
   siete de `validation/config.py`). Arreglo mecánico: declarar el rol. Es **ampliar el preflight**,
   no esta enmienda, y toca alcance F1 (D-PRE-4).
2. **`ROL_DERIVADA` significa «no mirar», mientras su docstring promete «NO debe existir en el
   dataset crudo»** (`dataset_check.py:41` vs `:235`). Saltar ≠ verificar ausencia. Comprobar la
   ausencia cazaría dos invariantes más (colisión de `target_col`/`partition`), pero **no todas las
   derivadas se comportan igual** —el motor sólo se niega a sobrescribir algunas— y convertirlas en
   requisito produciría falsos positivos. Exige medir cuáles, una por una: **queda fuera, con su
   razón escrita.**
3. **Una invariante que ningún vocabulario por campo puede expresar**: la obligatoriedad es
   *condicional* (`temporal_column` hace falta si y sólo si `temporal_axis ≠ "none"`), o no habla de
   columnas en absoluto (A9, A10, A11, C2). **Ésta es la que cierra esta enmienda.**

## 2. Decisiones

**D-INV-1 · La invariante la declara el dominio que la impone, no un registro central.** Cada config
de sección puede implementar `requisitos_incumplidos(columnas)` y devolver lo que su propio motor va
a exigir. Mismo criterio que `column_role`, y por la misma razón (`dataset_check.py`): es una
propiedad de la sección, no un criterio transversal. Un `if` por motor dentro del comprobador sería
el criterio disperso que D-PRE-3 evita, y además obligaría al núcleo a conocer los dominios.

**D-INV-2 · Se consume por la superficie que ya existe: `check_dataset`.** No se crea una tercera
función ni se cambia la forma de `check_pipeline`. Tres razones medidas:

- `check_dataset` ya es *«te aviso antes de correr, sin bloquear»*, que es exactamente la semántica
  que hace falta (D-PRE-5).
- Ya viaja hasta la interfaz: aviso en «Cargar datos», aviso por sección, **salto al campo exacto**
  (18/18 medido el 2026-07-29) y el botón que cambia de aspecto sin bloquear. Un canal nuevo habría
  que cablearlo entero.
- El front **no discrimina por `kind`**: consume `path` y `message`. Ampliar el vocabulario es
  aditivo de verdad.

**D-INV-3 · Un requisito incumplido NO hace `executable=False`.** `check_pipeline` conserva su
significado —¿resuelve el DAG?— y **sigue siendo lo único que gobierna el botón**. Un requisito es un
aviso: la corrida sigue siendo la autoridad sobre sí misma (D-PRE-5). Bloquear con esto convertiría
cada falso positivo futuro en un usuario que no puede correr algo que sí funciona.

**D-INV-4 · `columnas=None` significa «no se sabe», no «no hay».** Idéntico al precedente de
`index_columns` (`1.9.0`), y por la misma razón: un requisito que dependa de las columnas **no se
emite** si no se conocen. Afirmar sin el dato reintroduce el falso positivo más caro. Corolario que
sale de la medición §1.3: la ausencia en el dataset crudo implica la ausencia en el frame del paso,
pero **la presencia no implica la presencia** —un paso intermedio puede descartar la columna—. Por
eso un requisito se emite sólo cuando la carencia es **segura**, nunca cuando es probable.

**D-INV-5 · Un requisito nombra el campo que lo arregla, en rutas relativas.** El dominio devuelve
`temporal_axis`; el recorrido le antepone su prefijo (`stability.`). Así la sección no sabe dónde
está montada —y el salto al campo, que es lo que hace útil al aviso, funciona sin que el dominio
sepa nada de la interfaz.

**D-INV-6 · Lo que devuelve es copy público.** Mismo contrato que D-PRE-8: español, sin códigos
internos, y diciendo **qué hacer**, no sólo qué está mal. El mensaje del motor —bueno, pero escrito
para después— se reescribe para antes.

**D-INV-7 · La cobertura se declara, no se calla.** Un gate recorre las secciones del formulario y
exige que cada una **implemente** el protocolo o esté **exenta con su razón escrita**, igual que
`EXENTOS_MULTISELECT` y que el gate de la sección opaca. Sin esto, «cerramos la clase» sería una
frase: una lista corta y sin explicación se lee como cobertura total (D-PRE-4).

**D-INV-8 · Lo que queda FUERA, con su razón medida.** *(Nació al programar.)* Cinco invariantes
entran (A1 ×2, A7, A9, A10, A11); dos de las confirmadas **no**, y ninguna por olvido:

- **A3 (`stratify_by` inexistente) queda fuera porque comprobarla daría FALSOS POSITIVOS.** El uso
  canónico la apunta a una columna **derivada**: `Partitioner.suggest` genera
  `RandomSplitConfig(stratify_by=lf.target_col)` (`data/partition.py:195`), y `target` no existe en
  el dataset crudo — la crea el propio paso `data`. Una comprobación «¿está entre las columnas?»
  acusaría al caso correcto. `stratify_by` no declara `column_role` (a diferencia de sus pares
  `date_col` y `cohort_col`), y ése —no éste— es su arreglo: pertenece al agujero 1 de §1.4.
- **C2 (`required_sections` nombra un dominio apagado) queda fuera porque NO es una invariante de
  una sección**, sino **entre** secciones: para decidirla, `report` tendría que saber qué otras
  secciones del config están activas. Dárselo obligaría a pasar el config raíz a cada dominio, que
  es justo el acoplamiento que D-INV-1 evita. Necesita otra superficie, y no se improvisa aquí.
- Y siguen fuera los dos agujeros estructurales de §1.4: declarar `column_role` donde falta amplía
  el **alcance del preflight** fuera de F1 —decisión de producto (D-PRE-4)—, y comprobar la ausencia
  de las derivadas exige medir motor por motor cuáles rechazan de verdad una colisión.

**D-INV-9 · Una constante que el aviso y el motor comparten vive en UN sitio.** *(Nació al
programar.)* Los nombres candidatos a columna de período estaban **triplicados**: `evaluator.py`,
`step.py` y ahora los necesitaba el aviso. Tres copias de la lista que define la invariante es la
garantía de que algún día el aviso diga una cosa y el motor haga otra. Quedan en
`stability/config.py::TEMPORAL_CANDIDATE_NAMES`, que los otros dos importan. Misma lección que
`e688280`: medir el footprint real, no una lista escrita al lado.

## 3. Contrato

```python
# En cualquier config de sección (protocolo opcional, por convención de nombre):
def requisitos_incumplidos(self, columnas: frozenset[str] | None) -> tuple[Requisito, ...]: ...

@dataclass(frozen=True, slots=True)
class Requisito:
    path: str       # ruta RELATIVA del campo que lo arregla ("temporal_axis")
    declared: str   # el valor que crea la exigencia ("period")
    message: str    # copy público, en español, con la salida
```

`check_dataset` los recolecta caminando el config —el mismo recorrido que ya usa para las columnas—
y los publica como `Mismatch(kind="unmet_requirement")`, con la ruta ya absoluta. `DatasetCheck.compatible`
pasa a `False`, igual que con cualquier otro desajuste.

## 4. Qué NO resuelve esta enmienda

- **No amplía el alcance del preflight** (D-PRE-4 sigue vigente: camino F1).
- **No cierra las trece invariantes del censo**, sólo las medidas y seguras. Las demás quedan en
  §1.4 con su causa y su costo.
- **No cambia el veredicto de `/api/run`** ni el del botón Ejecutar (D-INV-3).
- **No toca `check_pipeline`.** Sigue respondiendo lo que siempre respondió.

## 5. Estrategia de tests

- **El caso de origen, en los dos sentidos**: `temporal_axis="period"` sin columna candidata →
  requisito; con la columna presente → sin requisito. Y con `columnas=None` → **sin requisito**
  (D-INV-4), que es la regresión que importa.
- **Cada invariante implementada**, con su config mínimo y su ruta esperada.
- **Cobertura declarada** (D-INV-7): recorrer las secciones del formulario y exigir protocolo o
  exención con razón.
- **Verificación por inyección**: el gate y los tests deben ponerse **rojos** al quitar el protocolo
  de una sección que lo tenga, no sólo verdes al tenerlo (regla del repo: un test que no puede
  producir el estado no puede cazar su defecto).
