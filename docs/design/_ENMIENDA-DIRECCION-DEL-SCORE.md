# Enmienda SDD — la dirección del score se pregunta tres veces y nadie la cruza

> **Estado:** **aprobada e implementada** (Cami, 2026-08-04, alcance completo: artefacto + error +
> aviso, y el copy en el mismo commit).
> **Enmienda a:** [`09-scorecard.md`](09-scorecard.md) (§5, `score_direction` de la escala),
> [`11-performance-stability.md`](11-performance-stability.md) (§5, los dos campos gemelos) y
> [`_ENMIENDA-INVARIANTES-PREVIAS.md`](_ENMIENDA-INVARIANTES-PREVIAS.md) (D-INV-1 y D-INV-8, el
> límite «una invariante ENTRE secciones no la expresa un protocolo POR sección»).
> **Origen:** GRAVE-1 de [`_CENSO-DEFECTOS-DEL-ABANICO.md`](_CENSO-DEFECTOS-DEL-ABANICO.md) §1.
> **Decisiones:** D-DIR-1 … D-DIR-9.

## 0. El defecto

El mismo dato —«¿un puntaje más alto es mejor o peor cliente?»— se declara en **tres** secciones
(`scorecard.score_direction`, `performance.score_direction`, `stability.score_direction`), con el
mismo `Literal` y el mismo default, y **cada una se lee por su cuenta**. Ninguna superficie comprueba
que digan lo mismo.

Con las direcciones cruzadas, el informe publica **AUC 0,288 · Gini -0,424** en desarrollo con
`model_validate`, `check_pipeline`, `check_dataset` y la corrida **los cuatro en verde y cero
avisos**. Es la clase de defecto más cara que puede tener un motor de riesgo: los demás fallan
ruidosamente, éste produce un número plausible y está invertido.

El propio catálogo del abanico ya lo dice en la pantalla, y ésa es la medida de cuán consciente era
el motor del problema (`ui/jobs.py:3367-3369`): *«Tiene que decir lo mismo que la escala con que
construiste la tarjeta, **porque nadie lo comprueba por ti**.»*

## 1. Lo que se midió al abrir el terreno, y que corrige al censo

Ocho hechos, todos verificados contra `a71d3e2`. **Cuatro reordenan el diseño y dos refutan una
premisa del censo.**

### 1.1 🔴 La reproducción del censo tiene un tercer factor que no escribió

`performance.score_direction` **sólo se lee cuando `evaluation_source == "score"`**
(`performance/evaluator.py:556-571`, y su segundo uso en `:764-770`). Con el default
`pd_calibrated` —el del preset F1— el campo es **inerte**: el ranking sale de la PD calibrada y el
signo no interviene.

Ejecutado sobre el preset F1 completo, cuatro corridas:

| caso | mutación | `evaluation_source` | Gini desarrollo |
|---|---|---|---|
| **A** | ninguna (baseline) | `pd_calibrated` | **+0,4247** |
| **B** | `performance` y `stability` invertidas | `pd_calibrated` | **+0,4247** ← *no se invierte* |
| **C** | `performance` invertida | **`score`** | **-0,4243** |
| **D** | ninguna | **`score`** | +0,4243 |

El caso **C** reproduce las cifras exactas del censo (-0,424 / -0,390 / -0,315 en las tres
particiones). El caso **B** es la reproducción tal como el censo la describe, y **no reproduce
nada**.

**El defecto es real y sigue siendo el más grave**; lo que cambia es su condición de disparo, y con
ella el alcance de la corrección. `evaluation_source` es un `selectbox` del formulario y un punto del
abanico: la combinación es alcanzable con dos clicks, no es un caso de laboratorio.

### 1.2 🔴 `stability.score_direction` no gobierna ningún cálculo

Barrido exhaustivo de `stability/evaluator.py`: las cuatro apariciones son el parámetro del
constructor (`:97`), su asignación (`:114`), la copia a la card (`:255`) y la revalidación de runtime
(`:608`). **Ninguna rama de cálculo lo lee.** PSI y CSI comparan distribuciones binadas y son
invariantes al signo.

⚠️ **Y su ayuda en la pantalla afirma lo contrario.** `ui/jobs.py:848` dice que se usa *«para
ordenar los tramos del informe y para leer los desplazamientos en el sentido correcto»*. Eso es falso
medido: el valor viaja del config a `StabilityCardSection.score_direction`
(`stability/results.py:267`) y muere ahí. **Es un defecto de copy nuevo, no listado en el censo**, y
se cierra en esta enmienda porque cualquier salida cambia lo que hay que decir ahí.

### 1.3 🔴 `from_config_with_context` **no puede** transportar la dirección

La recomendación del censo —opción (3), «que hereden vía `from_config_with_context`, el mecanismo ya
existe»— descansa sobre una premisa falsa. Ese hook entrega **exactamente dos cosas**: la propia
sección ya coaccionada y `active_domains`, que es un **`frozenset[str]` de nombres de paso**
(`core/study.py:475`, `:520-534`). Un `PerformanceStep` que lo implementara sabría que `"scorecard"`
corre; **no podría leer `scorecard.score_direction`**, porque no está ahí.

Y hay un gate que fija que hoy no lo implementa: `test_report_dominios_activos.py:476` asevera
`not hasattr(StabilityStep, "from_config_with_context")`.

### 1.4 🔴 `_check_cross_section` **no es** el sitio natural

La opción (2) del censo lo llamaba «el sitio que ya existe y es el natural». Medido, hay dos razones
por las que no lo es, y las dos están escritas en el propio código:

1. Su docstring declara el límite (`core/config/schema.py:1176-1180`): *«Valida invariantes
   **estructurales** entre secciones (no reglas de dominio). […] Las reglas de dominio las valida el
   orquestador en runtime, no el schema.»*
2. **El núcleo no conoce `score_direction`.** Una sección de dominio existe en dos estados —tipada u
   opaca— y **el opaco es el default** (SDD-23 §4.1; es la clase de defecto que
   `test_seccion_opaca_invariante.py` vigila). Con `nikodym.performance` sin importar,
   `self.performance` es un `dict` crudo, y leer `self.performance["score_direction"]` desde el
   núcleo es exactamente el acoplamiento que D-INV-1 rechazó.

Además levanta un `ValueError` de Python plano, no `ConfigError`, así que un chequeo nuevo ahí
llegaría a `/api/validate` como `ValidationError` de Pydantic — que es el camino correcto para un
error de schema y el equivocado para una regla de dominio.

### 1.5 El campo propio **no se puede eliminar**: hay un trabajo que lo necesita

«Validar un modelo existente» (`ui/jobs.py:250-309`, el trabajo **P2**) declara
`sections = (data, performance, stability, report)` — **sin `scorecard`** — y trae el score por la
puerta de artefactos externos (`('scorecard','score')`, `jobs.py:288-299`). Ahí no hay ninguna
sección de la que heredar, y la dirección del score externo **sólo la sabe el usuario**.

Medido en el fixture del front: ese trabajo pregunta la dirección **dos veces**
(`web/src/fixtures/jobs.json:6208` y `:6339`) sin sección ancla. Eso descarta cualquier salida que
borre el campo de `performance`/`stability` — y con ella se cae de paso la afirmación del censo de
que cerrar GRAVE-1 «también cierra MENOR-6».

### 1.6 Los tres presets son coherentes; ninguna salida rompe un ejemplo

`ui/presets.py:294`, `:348` y `:362` escriben los tres `higher_is_lower_risk`, y los tres presets
derivan de ahí sin sobrescribirlo. Los fixtures de la demo lo confirman
(`web/src/fixtures/demo/preset.json:275,381,399`). **Una salida que rechace la contradicción no
invalida ningún config de fábrica.**

### 1.7 Tres tests fijan hoy la independencia de los tres campos

| test | qué fija |
|---|---|
| `test_performance_config.py:136` | el hash cambia al variar `performance.score_direction` **con `scorecard=None`** |
| `test_performance_evaluator.py:175` | el evaluador es autónomo: se instancia con la dirección y sin ningún scorecard |
| `test_performance_config.py:73` · `test_stability_config.py:65` | el campo sobrevive al round-trip YAML como campo propio |

Ninguno asevera que las tres direcciones puedan **contradecirse**; los tres aseveran que el campo
**existe y es propio**. Una salida que conserve el campo los deja intactos.

### 1.8 `config_hash`: quién lo mueve y quién no

`INFRA_SECTIONS` es una **lista negra** (`core/config/hashing.py:34-46`): todo lo que no esté ahí
entra al hash. Las tres secciones son computacionales, así que **el campo contribuye al hash desde
las tres**.

Consecuencia directa para las salidas: **conservar el campo y cambiar cómo se interpreta NO mueve
ningún `config_hash`**; eliminarlo de dos secciones lo movería en todo config que las active. La
hash-neutralidad se declara aquí como requisito y se **mide** al implementar, no se supone.

## 2. Las salidas, con su coste medido

Las tres del censo quedan reducidas a una (la 1 y la 2 están refutadas arriba, y la 3 no es
implementable con el mecanismo que citaba). Lo que sigue son las salidas que **sí** están abiertas
sobre el terreno medido.

### (A) Sólo avisar, por el preflight

`ContextoConfig` gana un campo con la orientación que declara la sección que produce el score, y
`performance`/`stability` implementan `requisitos_incumplidos_por_contexto` para avisar cuando
difiere. Es el mecanismo que `bd3ffec` acaba de construir para exactamente esta forma de problema
—«una opción exige algo de otra sección»— y su gate ya existe.

- ✅ No mueve `config_hash`, no rompe ningún config, avisa **antes** de correr, en la pantalla.
- ✅ Sigue D-INV-3: *un requisito incumplido avisa, no bloquea*.
- ❌ **Un aviso no impide publicar el Gini invertido.** Quien lo ignore obtiene el mismo documento de
  hoy. Para «te falta un dato» eso es correcto; para «vas a publicar una cifra invertida», es poco.
- ⚠️ Coste real: **ampliar `ContextoConfig` a dos campos**, lo que su docstring declara previsto pero
  su gate cierra a propósito (`test_requisitos_por_contexto.py:71-76`: *«Un campo nuevo amplía lo que
  cada sección puede saber del resto del config: se decide en el SDD, no al programar»*). Y el campo
  nuevo lleva vocabulario de dominio al núcleo, que `secciones_activas` no llevaba.

### (B) La orientación se lee del ARTEFACTO, no del config *(recomendada)*

`performance` y `stability` ya consumen `('scorecard','score')` (`performance/step.py:62-65`,
`stability/step.py:68-71`). El paso `scorecard` publica además `('scorecard','card')`
(`scorecard/step.py:51`), y esa card **lleva la orientación con la que el score fue construido**
(`scorecard/results.py:81`).

La regla: **cuando el score viene del paso `scorecard`, su orientación viene con él**; el campo
propio de la sección rige **sólo** cuando el score entra por la puerta externa, que es el caso de
«Validar un modelo existente».

- ✅ **Elimina la clase por construcción**, no la avisa: con el paso activo, la dirección deja de ser
  una respuesta que el usuario pueda contradecir, porque no se le pregunta al config.
- ✅ **No mueve `config_hash`**: el campo se conserva tal cual.
- ✅ **No rompe el caso standalone** (§1.5) ni los tres tests de independencia (§1.7).
- ✅ El mecanismo existe y es del núcleo: `optional_requires`, atributo opcional que el motor consulta
  con `getattr` (`core/study.py:616`, precedente `data/step.py:57`). No nace contrato nuevo.
- ❌ **Por sí sola descarta en silencio** lo que el usuario escribió — que es exactamente el
  mecanismo de MENOR-7 (`calibration.anchor_source`), catalogado como defecto en el mismo censo. Por
  eso no se propone sola: ver D-DIR-4.

### (C) Rechazar la contradicción, deteniendo la corrida

Cuando el paso `scorecard` está activo y la sección declara una dirección distinta, la corrida se
detiene con un mensaje nombrado.

- ✅ No inventa ni descarta: dice exactamente qué está mal y dónde.
- ❌ **Llega tarde**: `performance` corre en el paso 8 de 10; el usuario paga binning, selection,
  model, scorecard y calibration antes de enterarse. Es el patrón que `_ENMIENDA-INVARIANTES-PREVIAS`
  existe para evitar.
- ⚠️ Es cambio de comportamiento: un config hoy válido deja de correr. Medido, **ninguno de fábrica**
  (§1.6).

## 3. Lo que se propone: (B) + (A) + (C), en ese orden de autoridad

Las tres salidas atacan momentos distintos y **no compiten**: (B) hace imposible el número
invertido, (C) impide que la contradicción pase en silencio, y (A) la pone en la pantalla antes de
gastar una corrida. Juntas cuestan poco más que (B) sola, porque las tres leen el mismo dato.

---

**D-DIR-1.** La dirección del score es **propiedad del score**, no de quien lo mide. Cuando el paso
`scorecard` corre en la invocación, su card es la **única fuente de verdad** de la orientación, y
`performance` y `stability` la toman de ahí. El campo propio de cada sección conserva su significado
original —la orientación de un score que el motor no construyó— y **rige exactamente cuando el score
llega por la puerta de artefactos externos**.

**D-DIR-2.** El acoplamiento viaja por el **DAG**, no por el config. `performance` y `stability`
declaran `optional_requires = (("scorecard", "card"),)`. Es un atributo opcional que el motor ya
consulta con `getattr` (`core/study.py:616`); no nace ningún contrato nuevo y el caso standalone
—donde nadie publica esa card— sigue resolviendo igual.

> **Por qué no `requires`:** volvería obligatoria la card y rompería «Validar un modelo existente»,
> que inyecta `('scorecard','score')` sin card. `optional_requires` es la diferencia entre *«lo
> consumo si está»* y *«lo exijo»*, y aquí sólo se necesita lo primero.

**D-DIR-3.** El núcleo **no participa**. No se añade ningún chequeo a `_check_cross_section` ni a
ninguna otra pieza de `core/config/`, por las dos razones de §1.4: su docstring excluye las reglas de
dominio, y con sección opaca —el estado por defecto— leer `score_direction` desde el núcleo es el
acoplamiento que D-INV-1 rechazó. La regla la impone el dominio que la sufre, igual que
`column_role` y `requisitos_incumplidos`.

**D-DIR-4.** **Una contradicción no se descarta en silencio.** Si la card publica una orientación y
la sección declara la contraria, el paso **se detiene** con un error nombrado que dice las dos
direcciones, la sección que las declara y qué hacer. Ésta es la mitad que impide repetir MENOR-7:
heredar sin decirlo convertiría este defecto en el otro.

> ⚠️ **Y hay que distinguir «declaró» de «no tocó el default».** Los tres presets y el esqueleto de
> todo trabajo escriben el campo **explícito**, así que `model_fields_set` **no** sirve para saber si
> el usuario lo eligió: es la misma trampa que D-COL-8 midió con el gesto de mapeo. Por eso el
> criterio es el **valor**, no la procedencia: contradecir es declarar un valor distinto del de la
> card, venga de donde venga. Con los tres presets coherentes (§1.6), ninguno se detiene.

**D-DIR-5.** El aviso llega **antes de correr**. `ContextoConfig` gana un segundo campo que
transporta la orientación declarada por la sección que produce el score, y `performance` y
`stability` implementan `requisitos_incumplidos_por_contexto` para avisar. Es el uso que el docstring
del DTO declaró previsto (`core/dataset_check.py:238-243`), y el aviso es de la familia que **añade**,
no de las dos que suprimen, así que no hereda la obligación de D-RAM-4 de medirse en los dos
sentidos.

> ⚠️ **El campo nuevo es la decisión cara de esta enmienda**, no un detalle de implementación: amplía
> lo que toda sección puede saber del resto del config, y su gate lo cierra a propósito
> (`test_requisitos_por_contexto.py:71-76`). Se declara **con nombre de dominio y tipo cerrado**
> —`direccion_del_score: str | None`— y no como un mapa genérico de convenciones: un `Mapping`
> abierto sería la puerta que el DTO existe para no abrir.

**D-DIR-6.** **`stability` deja de preguntar lo que no usa.** Medido (§1.2), su campo no gobierna
ningún cálculo. El campo **se conserva** —está en el golden de defaults, en el round-trip y en la
card que publica el informe—, pero:

- su punto del abanico **dice la verdad**: que describe el score que se está midiendo y que el motor
  de estabilidad no lo consume, en vez de la frase falsa de `ui/jobs.py:848`;
- su valor publicado en `StabilityCardSection` pasa a ser el heredado por D-DIR-1, de modo que el
  informe no pueda publicar dos orientaciones distintas del mismo score.

**D-DIR-7.** El gate se escribe **con oráculo independiente y en los dos sentidos**:

1. **Cara positiva:** con `scorecard` activa y las direcciones cruzadas, la corrida se detiene, y el
   preflight lo había avisado antes. Se mide **ejecutando**, sobre el preset F1, y el control
   negativo (revertir D-DIR-4) se ejecuta.
2. **Cara simétrica —la cara cara—:** sin `scorecard` activa, un `performance` con
   `higher_is_higher_risk` **corre y no avisa**. Es el caso de «Validar un modelo existente», y un
   gate que sólo mida la cara positiva se pone verde con la feature rota para el trabajo P2.
3. **Ancla anti-vacuidad:** el gate afirma cuántas secciones participan y cuáles, para que no pueda
   quedarse verde recorriendo cero.
4. 🔴 **El oráculo del Gini se escribe a mano**: el valor esperado no se deriva de la misma corrida
   que se está comprobando. La reproducción de §1.1 deja los cuatro números medidos y son los que se
   anclan.

**D-DIR-8.** **Hash-neutralidad declarada y medida.** Ninguna de las cuatro decisiones anteriores
toca la forma del config, así que los `config_hash` de los tres presets deben quedar **byte a byte
iguales**. Se mide contra el árbol anterior con los tres presets, no se supone — es el mismo
protocolo que D-COL-2 usó para la rama `columna`.

**D-DIR-9.** **Lo que esta enmienda NO cierra, dicho en vez de callado.** Cerrar GRAVE-1 **no** cierra
MENOR-6 (la ficha del modelo publica dos optimizadores contradictorios): el censo lo afirmaba
suponiendo que el campo de `performance` desaparecería, y §1.5 mide que no puede desaparecer. MENOR-6
es la misma **clase** —dos respuestas a la misma pregunta en un documento— y sigue abierto con su
propio coste.

## 4. Alcance y orden de implementación

1. D-DIR-2 y D-DIR-1 en `performance` y `stability` (motor + card), con su gate en los dos sentidos.
2. D-DIR-4, el error nombrado, con su control negativo ejecutado.
3. D-DIR-5, el campo de `ContextoConfig` y los dos implementadores, tocando su gate con la razón
   escrita.
4. D-DIR-6, el copy del abanico —lo que obliga a regenerar el fixture de trabajos **y** el bundle en
   el mismo commit—.
5. D-DIR-8, la medición de hash-neutralidad, **antes** de dar el bloque por cerrado.

**Fuera de alcance, declarado:** unificar los tres alias `ScoreDirection` en uno solo del núcleo. Son
tres `Literal` idénticos byte a byte en tres módulos (`scorecard/config.py:24`,
`performance/config.py:26`, `stability/config.py:32`); unificarlos es refactor de superficie pública
—los tres están en su `__all__` y en su `__init__`— y no cambia ningún comportamiento. Se anota, no
se hace aquí.

## 5. Lo que cambió AL PROGRAMARLA

Reabrir un diseño por feedback del código es barato y esperado; dejar que documento y código se
separen en silencio, no. Cuatro cosas se movieron, y las cuatro están medidas.

**5.1 🔴 D-DIR-1 y D-DIR-4 colapsan en un solo mecanismo, y el diseño mejora.** La enmienda las
escribió como dos piezas —heredar la orientación, y detener si el config la contradice—; al
programarlas se ve que **la herencia es inobservable**: o coinciden, y heredar es la identidad, o
difieren, y se detiene antes de calcular. Lo que queda es **una comparación**, no una asignación. El
efecto práctico de D-DIR-1 se conserva entero: la ficha que el informe publica no puede contener una
orientación distinta de la del puntaje. Pero el motor **no reescribe** ningún valor del usuario, que
es más fuerte que lo escrito: no hay ni siquiera un sitio donde el silencio de MENOR-7 pudiera
reaparecer.

**5.2 ⚠️ El campo nuevo del contexto NO lo llena el núcleo leyendo `scorecard`.** Esa era la
implementación obvia y habría metido por la puerta trasera justo lo que D-DIR-3 prohíbe: con la
sección opaca, `config.scorecard["score_direction"]`. Nace en su lugar un tercer protocolo por
convención de nombre —`METODO_CONVENCION_SCORE`, hermano de `requisitos_incumplidos`—: la sección que
**construye** el puntaje lo declara, y el núcleo transporta un `str` que no interpreta. Un gate fija
que sólo `scorecard` lo declara, porque con dos declarantes el desempate lo decidiría el orden de los
campos.

**5.3 ⚠️ La corrida de punta a punta NO se puede medir dentro de pytest.** Ajustar el binning real
importa el solver de OptBinning, y eso **tumba el runner con un segfault** —crash duro, no fallo—; es
la misma trampa que el repo ya tenía anotada para el binning con columna identificador. El gate
ejercita **los dos pasos con la ficha inyectada**, que es más falsable y no depende de ese import; la
corrida completa está medida fuera y sus cuatro números viven en §1.1. Consecuencia declarada: el
número **-0,4243** no lo ancla ningún test — lo ancla este documento.

**5.4 ✅ Los dos controles negativos se ejecutaron, y cada uno tumbó exactamente lo suyo.** Quitar la
guarda del motor deja **3 rojos** y ninguno del preflight; quitar el declarante de `scorecard` deja
**4 rojos** —los dos del protocolo y los dos del aviso— y ninguno de la guarda. Que las dos mitades
fallen por separado es la prueba de que son dos mecanismos y no uno con dos nombres.

**Gates del cierre:** pytest **5071 passed / 6 skipped** (base 5056), mypy 245, `ruff check` y
`format`, y **hash-neutralidad confirmada**: `test_ui_presets` y `test_config_hash_golden` pasan sin
tocar un valor esperado.
