# Enmienda SDD — el esqueleto que siembra un trabajo tiene que CORRER

> **Estado:** **aprobada e implementada** (Cami, 2026-08-04: overrides en el catálogo + gate de los
> diez).
> **Enmienda a:** [`_ENMIENDA-DECISIONES-OBLIGATORIAS.md`](_ENMIENDA-DECISIONES-OBLIGATORIAS.md)
> (D-OBL-11, el recorte de los capítulos del informe) y [`_SDD-UI-POR-TRABAJOS.md`](_SDD-UI-POR-TRABAJOS.md)
> (D-JOB-1, el trabajo decide qué secciones existen).
> **Origen:** GRAVE-2 de [`_CENSO-DEFECTOS-DEL-ABANICO.md`](_CENSO-DEFECTOS-DEL-ABANICO.md) §2.
> **Decisiones:** D-EJE-1 … D-EJE-7.

## 0. El defecto, y por qué es una clase y no dos casos

Dos de los diez trabajos del catálogo **nacen inejecutables**: quien entra por ellos y contesta todo
lo que la pantalla le pide obtiene un config que el motor rechaza antes de leer una fila.

| trabajo | qué falla | dónde |
|---|---|---|
| «PD lifetime (curvas de supervivencia)» | el default `survival.input.pd_source='model_raw'` exige `('model','raw_pd_frame')`, y el trabajo **no ofrece la sección `model`** ni admite subir esa tabla | `ui/jobs.py:104-123` · `survival/step.py:330-341` |
| «Comparar provisiones (CMF vs. interna)» | **dos causas independientes**: (a) el default `provisioning.source_b='provisioning_ifrs9'` exige una sección que el trabajo no activa; (b) `provisioning_internal` exige `('calibration','calibrated_pd_frame')` y el trabajo declara `external_artifacts=()` | `ui/jobs.py:228-249` · `provisioning/step.py:137-153` · `internal/step.py:199-201` |

**Es exactamente la clase que D-OBL-11 cerró para los capítulos del informe** —el esqueleto sembraba
ocho capítulos obligatorios, entre ellos uno que ningún trabajo declara, y ningún trabajo llegaba a
`done`—. Hay patrón a seguir y, sobre todo, hay una lección ya pagada: **aquello se descubrió
corriendo el gate de aceptación a mano, no en la suite**, y está escrito así en
`web/src/lib/jobs.test.ts:577`.

## 1. Lo que se midió, y que decide el diseño

### 1.1 🔴 La siembra vive ENTERA en el front, y el gate que falta tiene que ser Python

`jobSkeleton` (`web/src/lib/jobs.ts:260-273`) construye el config del trabajo: clona el catálogo de
defaults efectivos y proyecta las secciones que el trabajo declara. El backend **no tiene siembra**:
`grep -rn "skeleton\|esqueleto" src/nikodym/` sólo devuelve un comentario.

Y el único ajuste post-siembra que existe es `recortarCapitulosDelInforme` (`jobs.ts:292-306`), que
es D-OBL-11 **cableado a mano a un único path**. Medido: `grep -rn "job\.id ===\|jobId ===" web/src`
devuelve **cero**. No hay ningún mecanismo de «este trabajo siembra este valor».

**La consecuencia manda sobre el diseño:** un gate que compruebe ejecutabilidad tiene que llamar a
`check_pipeline`, que es Python, y hoy **no puede reproducir el esqueleto** sin reimplementar en
Python lo que el front hace en TypeScript. Reimplementarlo sería un oráculo derivado del mismo dato
que verifica — el error que este repo ya tiene documentado dos veces.

### 1.2 ✅ El patrón correcto ya existe en el propio catálogo

«Validar un modelo existente» (`ui/jobs.py:250-309`) declara `performance` y `stability` **sin**
`scorecard` ni `calibration`, y por eso declara las dos claves que esos pasos exigen como
`external_artifacts`. Su hermano «Provisión interna / LGD» (`jobs.py:158-200`) hace lo mismo con la
PD, y además **con un `when`**: la clave se exige sólo bajo el valor de config que la consume.

O sea: el catálogo ya sabe decir «esta tabla la traes tú». Lo que falta no es mecanismo, es **usarlo
en los dos trabajos donde falta y un gate que lo exija**.

### 1.3 ⚠️ Los dos trabajos NO se arreglan igual, y ésa es la parte que no se puede copiar

- **«PD lifetime»** puede corregirse **sin puerta nueva**: `pd_source='none'` ajusta las curvas sólo
  con lo que trae el archivo, que es exactamente lo que ese trabajo promete. Es lo que el preset F4
  ya escribe a mano (`ui/presets.py:732`). ⚠️ El comentario de `jobs.py:114-117` —«survival no
  REQUIERE la PD»— es cierto **sólo** para ese valor, que no es el default: el comentario describe
  una intención que la siembra no cumple.
- **«Comparar provisiones»** necesita **las dos cosas**: un valor sembrado (`source_b`) y una puerta
  declarada (la PD calibrada). Un mecanismo que sólo resuelva una de las dos deja el trabajo roto
  igual.

### 1.4 🔴 Una de las dos causas de «Comparar provisiones» la cierra GRAVE-3, no esta enmienda

`provisioning.source_b='provisioning_ifrs9'` es el default que
[`_ENMIENDA-REGLA-DEL-MAXIMO.md`](_ENMIENDA-REGLA-DEL-MAXIMO.md) discute por razones **normativas**.
Si ese default pasa a `provisioning_internal`, la causa (a) **desaparece sola** y el trabajo que se
llama «CMF vs. interna» deja de arrancar comparando contra IFRS 9.

Las dos enmiendas son independientes y hay que decidirlas por separado, pero el orden importa: **si
GRAVE-3 se aprueba, esta enmienda tiene menos que hacer**. Se declara aquí para que la decisión no
se tome dos veces con información distinta.

## 2. Las decisiones

**D-EJE-1.** **Un trabajo `available` produce un config EJECUTABLE.** Es la promesa que el estado
`available` hace en la pantalla, y hasta hoy no la comprobaba nadie. Un trabajo que no pueda
cumplirla se declara `unavailable` con su motivo, que es el mecanismo que el catálogo ya tiene para
«esto todavía no».

**D-EJE-2.** **Lo que un trabajo necesita sembrar se declara en el catálogo, no en el front.** Nace
un campo `overrides` en la entrada del trabajo (`ui/jobs.py`): rutas de config con el valor que ese
trabajo siembra por encima del default del motor. `jobSkeleton` lo aplica después de
`canonicalProjection` y antes de `recortarCapitulosDelInforme`.

> **Por qué en el backend y no en el front, que es donde vive la siembra:** porque el gate de D-EJE-5
> es Python. Con los overrides en el catálogo, el gate los aplica **desde la misma fuente** que el
> front consume por `GET /api/jobs`, y no reimplementa nada. Es el mismo argumento con que D-JOB-3
> puso el catálogo de trabajos en el backend: lo consume el preflight, que es Python.

**D-EJE-3.** **`recortarCapitulosDelInforme` se conserva tal cual y NO se reescribe como override.**
Su recorte es una **intersección calculada** con las secciones del trabajo, no un valor fijo: no cabe
en `overrides` sin volverlo un lenguaje. D-OBL-11 sigue siendo una pieza propia, y esta enmienda
añade la de al lado.

**D-EJE-4.** **Los dos trabajos se corrigen con el mecanismo mínimo que cada uno necesita:**

| trabajo | corrección |
|---|---|
| «PD lifetime» | `overrides: {"survival.input.pd_source": "none"}`, y el comentario de `jobs.py:114-117` pasa a decir lo que la siembra hace |
| «Comparar provisiones» | `external_artifacts` para `('calibration','calibrated_pd_frame')` con su `when` sobre `provisioning_internal.pd_source`, **más** `overrides: {"provisioning.source_b": "provisioning_internal"}` si GRAVE-3 no lo cierra desde el default |

**D-EJE-5.** 🔴 **El gate recorre LOS DIEZ trabajos y le pregunta al motor.** Por cada trabajo
`available`: construir su esqueleto desde el catálogo, aplicar sus `overrides`, inyectar sus
`external_artifacts` y exigir `check_pipeline(...).executable is True`. El defecto reaparece con
cualquier trabajo nuevo, así que lo que se cierra es la clase.

⚠️ **Y el gate necesita construir el esqueleto en Python.** Se hace con `effective_defaults`, que es
la misma fuente que consume el front (`GET /api/schema`), y **no** copiando la lógica de
`canonicalProjection`: si el esqueleto del gate y el de la pantalla pudieran divergir, el gate
mediría un config que ningún usuario tiene. Un test de paridad ancla que los dos producen lo mismo.

**D-EJE-6.** **Las decisiones obligatorias se contestan en el gate con un valor cualquiera
admisible.** Un esqueleto real llega con `bad_rule` y la partición sin contestar —eso es D-OBL-6 y es
correcto—, así que `check_pipeline` sobre el esqueleto crudo mediría otra cosa. El gate las rellena
con el mínimo que construye, y **declara** que lo hace: lo que mide es *«contestadas las obligatorias,
¿corre?»*, que es la pregunta del usuario que entra por el trabajo.

**D-EJE-7.** **Lo que este gate NO mide, declarado.** No mide que la corrida **termine bien**: mide
que el pipeline **resuelva**. Una corrida real necesita además un dataset con las columnas correctas,
y eso lo cubre `check_dataset`, que es otra pregunta y tiene su propio mecanismo. Decir que este gate
garantiza «el trabajo funciona» sería la sobrepromesa que D-PRE-4 evita declarando su alcance.

## 3. Orden de implementación

1. D-EJE-2, el campo `overrides` en el catálogo, con su gate de forma (rutas que existen, valores
   admisibles) — el mismo patrón que `test_jobs_insumos_externos.py` usa para `config_paths`.
2. D-EJE-5, el gate de ejecutabilidad, **antes** de las correcciones: tiene que ponerse **rojo sobre
   los dos trabajos medidos** y verde sobre los otros ocho. Ése es su control negativo, y sale gratis
   porque el defecto todavía está puesto.
3. D-EJE-4, las dos correcciones, hasta que el gate quede verde.
4. Fixture de trabajos y bundle en el mismo commit.

## 4. Lo que cambió AL PROGRAMARLA

**4.1 🔴 Los trabajos rotos son TRES, no dos.** «Provisiones IFRS 9» cae por **la misma causa** que
«PD lifetime» —el default de la fuente de PD de `survival` exige un artefacto de la sección `model`,
que tampoco ofrece—, y el censo no lo había visto. Salió al construir el gate, que es exactamente
para lo que sirve un gate que recorre la clase entera en vez de los casos conocidos. La corrección
es idéntica: un override con la fuente que no exige nada.

**4.2 🔴 El gate cazó un defecto en el código que se acababa de escribir, el mismo día.** El primer
`aplicarOverridesDelTrabajo` recorría los tramos de la ruta y hacía `continue` si alguno no existía.
Medido: `survival.input` **no existe en el esqueleto** —la proyección canónica omite los submodelos
obligatorios enteros (D-OBL-2)— así que el único override del catálogo se perdía **en silencio** y
los dos trabajos seguían naciendo rotos con el catálogo ya corregido. Los tramos que falten se crean;
el bloque queda incompleto a propósito, que es el estado en que la decisión obligatoria espera al
usuario, con override o sin él.

**4.3 ⚠️ La réplica de la siembra en Python es deuda declarada, no una solución.** `jobSkeleton` vive
en TypeScript y el gate necesita el mismo esqueleto en Python; no hay forma de ejecutarlas y
compararlas. Lo que las ata es un gate **estático** que lee `web/src/lib/jobs.ts` y exige que la
función siga llamando exactamente a los tres pasos que la réplica reproduce, en ese orden. Si el
front gana un cuarto, se pone rojo y obliga a mirarlo — que es todo lo que un ancla puede prometer,
y más que callarse. Cerrarlo de verdad exige que el backend publique el esqueleto, y eso es contrato
nuevo: se anota, no se hace aquí.

**4.4 ✅ El control negativo salió gratis y midió exacto.** Revertidas las tres correcciones, el gate
se pone rojo sobre **los tres trabajos y ninguno más**; repuestas, verde. Es la prueba de que mide
la clase y no tres casos escritos a mano.

**Gates del cierre:** pytest **5096 passed / 8 skipped**, mypy 245, `ruff check` y `format`, vitest
626/626, typecheck y lint del front, fixture de trabajos y de schema regenerados.
