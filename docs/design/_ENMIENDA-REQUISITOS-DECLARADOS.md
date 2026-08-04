# Enmienda — un paso declara los requisitos que va a usar, no los de fábrica (M-2)

> ✅ **Estado: APROBADA por Cami el 2026-08-05, con la salida (a) y el gate de clase.** Enmienda al
> contrato CT-1 (`_CONTRATOS-TRANSVERSALES.md`) en su punto de `Step.requires`, y a
> [`26-report.md`](26-report.md) en el hook.
>
> Decisiones: **D-REQ-1 … D-REQ-8**. Hermana de
> [`_ENMIENDA-REQUISITOS-CMF.md`](_ENMIENDA-REQUISITOS-CMF.md) (M-3), y §1.3 explica por qué.
>
> 🔴 **M-3 NO se implementa** —decisión de producto: la normativa local de cada país sale del
> alcance de la librería—, así que `provisioning_cmf` entra al gate de D-REQ-8 como **excepción
> declarada con su razón**, no como caso a cerrar. Que la excepción esté escrita es justo lo que
> impide que se lea como un olvido.

---

## 1. El problema

### 1.1 Lo que el censo decía, y se reprodujo ejecutando

`TuningStep` y `ExplainStep` fijan su `requires` en `__init__` a partir del **default de fábrica** de
`ml.feature_source`, no del que el usuario escribió. Con `ml.feature_source='selection_woe'`:

**Falso rojo** —`check_pipeline` rechaza un pipeline que corre—, con los artefactos reales presentes:

```
executable = False
El paso 'tuning' necesita 'woe_frame', que produce 'binning', y ningún paso anterior
lo genera: active 'binning' antes de 'tuning' o quite este paso.
```

**Falso verde** —`check_pipeline` acepta un pipeline que muere—, sin inyectar nada, sólo con
`run.steps=['data','binning','tuning']`:

```
executable = True | steps = ('data','binning','tuning') | message = None
… y `tuning.execute` muere con ArtifactNotFoundError('selection','selected_woe_frame')
```

### 1.2 🔴 Tres cosas que el censo NO traía, y las tres salieron al ejecutar

1. **Hay una TERCERA mentira, y es un aviso público que se lee al revés.** En el falso rojo,
   `PipelineCheck.inert_artifacts` declara **inertes los dos artefactos que el paso sí consume**:
   `(('selection','selected_woe_columns'), ('selection','selected_woe_frame'))`. El usuario recibe a
   la vez «te falta binning» (falso) y «lo de selection no lo usa nadie» (falso). El copy de esa
   clave promete lo contrario (`api.py:105-107`).
2. **`tuning` miente también por `monotonic.mode`**, no sólo por `feature_source`: con `mode='off'`
   declara `binning.tables` y `binning.result`, que no consume. Son **dos** campos de `ml`, no uno.
3. **NO hay ninguna `MLConfig` de fábrica de por medio.** Lo que hay son **dos constantes `str`
   escritas a mano** (`tuning/step.py:85-86`, `explain/step.py:87`) que replican los `default=` de
   `ml/config.py:449` y `:299`. Si `ml` cambia su default, estos dos no se enteran y **ningún test lo
   caza**: es una duplicación muda, sin ligadura.

### 1.3 🔴 Y M-2 y M-3 son el MISMO defecto con dos disfraces

`CmfProvisioningStep` (M-3) declara de menos y `tuning`/`explain` (M-2) declaran de más y de menos a
la vez; pero los tres fallan en lo mismo —**`Step.requires` afirma una cosa y el paso lee otra**— y
los tres producen **la misma tercera mentira en `inert_artifacts`**, que se midió por separado en
cada uno sin buscarla. Es el patrón que este repo ya conoce: tres defectos, un mecanismo.

De ahí D-REQ-8, que es la parte que sobrevive a los dos casos.

### 1.4 ⚠️ Duele menos de lo que el censo sugiere, y conviene decirlo antes de presupuestar

- **No es alcanzable desde la pantalla.** `ml`, `tuning` y `explain` **no están** en
  `CONFIG_SECTIONS` (`web/src/lib/schema.ts:86`, 14 claves, medidas) ni tienen una sola mención en
  el catálogo de trabajos (`ui/jobs.py`, 0 menciones de ambas). Ninguno de los diez trabajos las
  enciende. El defecto vive **sólo en la API por código**.
- **No corrompe resultados**: los tres `_require_present` de `execute` son la red y funcionan.
- **En un pipeline completo casi siempre queda tapado**: `MLStep` **sí** declara honesto
  (`ml/step.py:135`), así que el rojo llega igual, atribuido a otro paso.

**El argumento para enmendar no es el dolor del usuario: es que el contrato CT-1 está roto y hay dos
tests que consagran la mentira** (`test_tuning_step.py:376-382`, `test_explain_step.py:343-347`; el
comentario de `test_explain_step.py:783` la describe literalmente). Una enmienda que no los derogue
no ha cerrado nada.

### 1.5 El límite, confirmado por tercera vez

`from_config_with_context` entrega `active_domains: frozenset[str]` —**nombres de paso**, no config—
(`core/steps.py:64-70`, único llamador `core/study.py:520-534`, único implementador en `src/`
`report/step.py:117`). Un `TuningStep` que lo implementara sabría que `selection` corre, pero **no
podría leer `ml.feature_source`**. El límite es real y no se rodea sin tocar el hook.

## 2. Las tres salidas, con su coste medido

### (a) El contexto del hook deja de ser un `frozenset` y pasa a ser un DTO

`active_domains: frozenset[str]` → un DTO congelado que además transporta lo que una sección declare
de sí misma. **No** el config crudo: eso es el acoplamiento que D-INV-1 rechazó.

⚠️ **Hay precedente exacto y ya probado**: `ContextoConfig` (`core/dataset_check.py:237-296`) es ese
DTO para el **otro** canal de contexto, su propio docstring escribe este diagnóstico —«con un
`frozenset` a secas habría que cambiar la firma de todos los implementadores»— y **ya se amplió una
vez sin tocar ningún implementador** (D-DIR-5). El dato lo produciría un **método-protocolo en la
propia `MLConfig`**, al estilo de `METODO_CONVENCION_SCORE`, para que el núcleo **transporte sin
interpretar**.

| coste | medido |
|---|---|
| llamadores | 1 (`core/study.py:520-534`, más el mensaje que nombra la firma) |
| implementadores en `src/` | 1 (`report/step.py:117` + su `__init__` y docstring) |
| citas en tests | 7 (`test_report_dominios_activos.py`), 4 de ellas llamadas directas |
| citas en docs | 6, más `CLAUDE.md` y `AGENTS.md` |
| `config_hash` | **cero** |
| riesgo | rompe a un implementador de tercero; mitigable con kwarg aditivo, pero conviven dos firmas |

⚠️ **Punto sin medir que decide la implementación**: con `ml` en estado **opaco** —que es el default
del núcleo— el método-protocolo no existe hasta coaccionar la sección, y la coacción puede fallar
(D-ANC-10). Hay que decidir qué se declara entonces: conservar el default de fábrica es exactamente
el comportamiento de hoy, y habría que **decirlo**, no heredarlo en silencio.

### (b) `tuning` y `explain` declaran el dato en su propio config

Precedente exacto y más barato: `ProvisioningStep` (`provisioning/step.py:137-152`) deriva su
`requires` **de su propia sección** —de qué dominio ajeno depende lo dice él, y el núcleo no cruza
nada—. Su docstring lo llama «`requires` dinámicos (CT-1, patrón SDD-16 §4)».

| coste | medido |
|---|---|
| `config_hash` | **cero**: `ml`/`tuning`/`explain` son `None` en el config de fábrica y en los tres presets |
| fixture del schema | **sí** se mueve → regenerar + bundle en el mismo commit |
| tests a derogar | los dos que consagran el defecto; 12 líneas tocan `_requires_for`/`step.requires` |

🔴 **Su contra, y es de fondo:** `execute` **ya lee `ml` obligatoriamente** (`tuning/step.py:556`),
así que un campo propio **duplica una fuente de verdad** y abre la pregunta «¿y si se contradicen?».
La respuesta correcta sería detener con error nombrado —el criterio de D-DIR-1— pero eso es fabricar
una contradicción posible donde hoy no la hay, para no tocar un hook con un solo implementador.

### (c) Sólo ligar las constantes al default de Pydantic

`_DEFAULT_FEATURE_SOURCE = MLConfig.model_fields['feature_source'].default`. Coste casi nulo.

**No cierra M-2**: sigue siendo el default de fábrica, no el del usuario. Cierra otra cosa —la
deriva muda de §1.2.3— y es **complemento** de (a) o (b), no alternativa.

## 3. La recomendación

**(a), con (c) incluida de paso.** Tres razones, en orden de peso:

1. **(b) fabrica una contradicción para no tocar una firma con un solo implementador.** El dato es
   de `ml` y lo lee `ml`; copiarlo a otras dos secciones crea dos campos que pueden decir cosas
   distintas sobre el mismo hecho, y este repo acaba de pagar (D-DIR-1) por exactamente eso.
2. **El hook nació para esto.** `core/steps.py:64` lo presenta como «la vía genérica —sin casos
   especiales por dominio en el núcleo—», y hoy tiene **un** implementador: ampliarlo es más barato
   ahora que nunca.
3. **El precedente ya existe y ya se amplió sin romper a nadie** (`ContextoConfig`, D-DIR-5).

## 4. Las decisiones

- **D-REQ-1.** `Step.requires` declara **lo que el paso leerá con la config dada**. Lo que hoy es
  contrato de facto en cuatro pasos pasa a ser contrato escrito, y `tuning`/`explain` se alinean.
- **D-REQ-2.** El contexto del hook deja de ser `frozenset[str]` y pasa a ser un DTO congelado que
  conserva `active_domains` como campo. **Extensión aditiva**: el implementador que hoy sólo usa
  pertenencia de nombres sigue funcionando sin cambiar de forma.
- **D-REQ-3.** Lo que el DTO transporta de `ml` lo **produce `MLConfig`** por método-protocolo, no lo
  interpreta el núcleo (D-INV-1). Los **dos** campos, no uno: `feature_source` y `monotonic.mode`.
- **D-REQ-4.** Si `ml` está ausente o no se puede coaccionar, el paso conserva el default de fábrica
  —el comportamiento de hoy— y **lo declara**; no se hereda en silencio.
- **D-REQ-5.** Los dos tests que consagran el defecto se **derogan con su razón escrita**, no se
  borran: quedan invertidos, midiendo lo contrario.
- **D-REQ-6.** Las constantes duplicadas se ligan al default de Pydantic (la salida (c)), para que la
  deriva muda entre módulos no sobreviva a esta enmienda.
- **D-REQ-7.** `inert_artifacts` se mide en el gate: con `selection_woe`, los dos artefactos de
  `selection` dejan de salir como inertes. Es la §1.2.1 y es lo que prueba que se cerró de verdad.
- **D-REQ-8.** 🔴 **Nace un gate de CLASE, y es lo que sobrevive a M-2 y M-3.** Recorre **todos** los
  steps registrados y, para cada uno, contrasta el `requires` declarado contra el que su propio
  `execute` re-deriva con la misma config. Sin él, el cuarto caso de esta familia vuelve a nacer con
  la suite verde — que es exactamente lo que pasó con las tres reincidencias de la sección opaca.
  ⚠️ Su ancla anti-vacuidad es obligatoria: un barrido que recorra cero steps da verde.

## 5. Lo que salió AL IMPLEMENTAR, y cambió tres decisiones

### 5.1 🔴 El primer arreglo pasaba sus tests y dejaba el defecto VIVO por la puerta pública

`_contexto_de_resolucion` recorría las secciones **activas**. Con `run.steps=['tuning']` —que es
justo el caso B con que se reprodujo el falso verde— la sección `ml` **existe y no corre**, así que
su contrato no se leía y el paso volvía al default de fábrica. Los tests por-paso pasaban, porque
construyen el contexto a mano.

Medido con `nikodym.check_pipeline` **después** de dar por bueno el arreglo:

```
FALSO ROJO  -> executable=True … ✗ seguía en False
inertes     -> (('selection','selected_woe_columns'), ('selection','selected_woe_frame'))  ✗
```

**El contrato se lee de las secciones DECLARADAS**, no de las activas, porque es lo que `execute`
hace: `_ml_config_from_study` lee `study.config.ml` sin mirar si `ml` está entre los pasos.
`dominios_activos` sigue siendo el conjunto activo — son dos preguntas distintas, y por eso son dos
campos.

⚠️ **Lección transferible**: un test que **construye** el contexto a mano no puede detectar que el
contexto se construye mal. El oráculo tenía que ser la superficie pública, y por eso los tres tests
de §D-REQ-7 van por `check_pipeline` y no por el constructor del paso.

### 5.2 🔴 El gate de clase acusó a TRES inocentes, y su criterio era el equivocado

Con la condición «re-deriva sus requisitos en `execute`», el gate marcó `ml`, `provisioning` y
`validation`. Medido: los tres re-derivan desde **su propia** sección, releída de `study.config` por
si difiere de la del constructor. Eso no es el defecto — un paso siempre puede saber lo suyo.

La condición correcta es **«los compone con datos de otra sección»**, y se detecta siguiendo qué
variables de `execute` salen de un `_<ajeno>_config_from_study(...)`, con cierre transitivo (en
`explain` el valor llega al compositor a través de `_resolve_feature_source`). Su control negativo
—un paso que relee lo suyo **no** debe marcarse— quedó escrito en el propio gate, porque es el error
que cometió su primera versión.

### 5.3 D-REQ-5 describía un problema que no existía tal como se escribió

Los dos tests «que consagraban la mentira» miden `from_config` **sin contexto**, y eso sigue siendo
correcto: es el caso «no se sabe» de D-REQ-4. No había que invertirlos, sino **encuadrarlos** —dejar
dicho que son el caso suelto y no la regla— y corregir un comentario de `test_explain_step.py` que
sí describía el defecto como aceptado («el static check pasa y execute re-deriva»).

### 5.4 D-REQ-6 no se pudo implementar como estaba escrita

Leer el default de `MLConfig` en import time arrastraría el dominio `ml` —que `tuning` importa
**perezosamente**, por su extra— al importar `tuning`. La copia a mano se conserva y lo que cierra
la deriva muda es **un gate bidireccional**, que consigue lo mismo sin romper el núcleo liviano.

### 5.5 🔴 Declarar los requisitos correctos EMPEORÓ un mensaje, y lo cazó un test existente

Con `ml.feature_source='data_raw'` —una fuente **diferida**, que el motor rechaza siempre con
`FALTA-DATO-ML-1`— el contrato hacía que `tuning` declarase `('data','frame')` como prerequisito
duro. Resultado: el DAG cortaba **antes** con «necesita 'frame', que produce 'data'», cierto y mucho
peor que el diagnóstico que nombra la carencia y sus dos salidas.

**`data_raw` no se publica en el contrato** (`MLConfig.contrato_de_variables_declarado`). No es
declarar de menos: un paso con esa fuente **no llega a correr nunca**, así que sus requisitos son
irrelevantes y lo único que se decide es cuál de los dos errores lee el usuario.

⚠️ Es la clase que D-CMF-4 anticipó para CMF —«el mensaje del camino normal pierde su cita»— y que
aquí ocurrió de verdad. **Un arreglo de `requires` puede degradar un diagnóstico sin tocar una sola
línea de copy**, y sólo se ve corriendo la suite entera: lo cazó `test_data_raw_esta_diferido`, un
test que existía y que no habla de `requires`.

## 6. Lo que esta enmienda NO hace

1. **No toca `optional_requires`**: declara claves que el paso adopta si existen y **no** entran a
   `_validate_pipeline`, así que convertiría el falso rojo en silencio, no en verdad.
2. **No pasa el dato por un artefacto**: `requires` se resuelve **antes** de que exista ninguno.
3. **No amplía el formulario**: `ml`/`tuning`/`explain` siguen fuera de `CONFIG_SECTIONS`, y esta
   enmienda no es razón para meterlas.
