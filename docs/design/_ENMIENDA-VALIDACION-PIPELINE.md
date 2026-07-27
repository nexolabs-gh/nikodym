# Enmienda SDD — la ejecutabilidad del pipeline se sabe mientras se edita, no al ejecutar

> **Estado: APROBADA (Cami, 2026-07-27).** D-PIPE-4 —avisar sin bloquear— se decidió
> explícitamente sobre la alternativa de gatear el botón Ejecutar.
>
> **Base:** `main` = `cb85716` (CI verde 16/16).
> **Autor / Fecha:** DanIA / 2026-07-27.

| Campo | Valor |
|---|---|
| **Problema** | El usuario descubre que su config es inejecutable **al ejecutar**. El motor sabe decirlo sin datos y sin correr nada, pero nadie se lo pregunta hasta que aprieta Ejecutar |
| **Enmienda a** | [`_ENMIENDA-RUN-ERROR-RESOLUCION.md`](_ENMIENDA-RUN-ERROR-RESOLUCION.md) §3 (candidato anotado, sin decidir), SDD-23 §3.3/§4.2 (contrato de `/api/validate`) |
| **No toca** | El significado de `valid` (D-PIPE-1), `canRun` (D-PIPE-4), `Study.run()` como primitivo *fail-loud*, ni el 422 de `/api/run` |
| **Release** | Sin publicar. Cambio de contrato **aditivo** (CT-3): la respuesta de `/api/validate` crece, ningún campo existente cambia |

---

## 1. Lo que la medición dice, antes de diseñar nada

Medido el 2026-07-27 contra el árbol (`scratchpad/medir_resolucion.py`), porque en este repo el plan
escrito no ha sobrevivido a la primera medición **ocho veces seguidas**:

| pregunta que decide el diseño | medición |
|---|---|
| ¿La resolución depende del dataset? | **No.** `_default_step_names` mira las secciones activas del config; `_validate_pipeline` compara `requires`/`provides` contra un `ArtifactStore` vacío |
| ¿Cuánto cuesta? (va con debounce, en cada tecleo) | **≤ 0,1 ms** con los dominios ya importados. La **primera** llamada paga 1.071 ms de imports perezosos (F1); es un pago único del proceso |
| ¿Tiene efectos? | **Ninguno observable.** Cero archivos nuevos en el cwd, el dict de entrada no se muta, y `run_context` queda intacto (`status="created"`, `run_id=None`) |
| ¿Monta sinks, MLflow o inventario? | **No.** Eso vive en `assemble_run`, que sólo llama `api.run` |
| ¿Reproduce el diagnóstico? | Sí, exacto: `ConfigError: El paso 'provisioning_ifrs9' requiere ('survival', 'term_structure'), que ningún paso aguas arriba produce: config inejecutable.` |

Y un hallazgo que **cambia la forma de la solución**, no sólo su tamaño:

> **La lista `errors[]` de `/api/validate` se pinta POR CAMPO.** El front la indexa por `pathKey(loc)`
> y cada `FieldRenderer` recupera su mensaje por `path` (`web/src/lib/validation.ts`). Un fallo de
> pipeline **no tiene `loc` de campo** —es del config entero—, así que meterlo en `errors[]` lo
> volvería **invisible**: ningún campo lo reclamaría y el contador diría «1 error» sin mostrar cuál.
> Ése es el argumento duro para un canal propio, y no la estética del payload.

El prefijo obvio para las decisiones, `D-VAL-`, **ya está tomado** por SDD-22 (`22-validation.md`,
D-VAL-1…D-VAL-12). Se usa `D-PIPE-`. Es la misma trampa que costó una casi-colisión en la enmienda
del horizonte: el catálogo de códigos vive en los SDD, no en `src/`.

## 2. Las decisiones

**D-PIPE-1 — `valid` NO cambia de significado.** Sigue siendo «el config reconstruye
`NikodymConfig`». Es la precondición de `/api/config/to-yaml`, del 422 de `/api/run` y del gate
`canRun`; redefinirla como «además es ejecutable» convierte cualquier config a medio editar en
inválido y bloquea al usuario por algo que no es un error de dato. Es justo la objeción que dejó
este ítem sin decidir en la enmienda anterior, y la respuesta es no tocar la palabra.

**D-PIPE-2 — La ejecutabilidad viaja en un campo ADITIVO.** La respuesta suma
`pipeline: {executable: bool, steps: list[str], message: str | null}`; `valid`, `config_hash` y
`errors` quedan idénticos. Extensión aditiva de contrato de lectura (CT-3), no ruptura. `steps` es
además el primer lugar donde el usuario ve **qué va a correr y en qué orden** antes de correrlo.

**D-PIPE-3 — La capacidad vive en el NÚCLEO, no en la capa UI.** Se expone
`Study.check_pipeline()` (resuelve y valida sin ejecutar; *fail-loud*, re-levanta como `Study.run`)
y `nikodym.check_pipeline(config)` (envoltorio de producto que captura y devuelve el veredicto,
igual que `api.run` con D-UI-2). `/api/validate` la **consume**; no reimplementa nada.
Razón: es literalmente el requisito 1 de la visión. Poner el aviso sólo en la UI dejaría al que
trabaja por código descubriendo el problema al ejecutar — la mitad de la paridad que ya nos costó
un defecto de núcleo la sesión pasada.

**D-PIPE-4 — Avisa, no bloquea.** `canRun` no se toca: con `executable=false` el botón Ejecutar
sigue habilitado. Tres razones, en orden de peso: (a) el motor es la autoridad y desde D-ERR-8 una
corrida inejecutable **se registra** con su diagnóstico y su `run_id`, así que intentar deja
audit-trail —bloquear se lo quita—; (b) la resolución de `/api/validate` puede diferir de la real
(extras instalados, imports); (c) un aviso que se equivoca cuesta una línea de texto, un bloqueo que
se equivoca cuesta la corrida.

**D-PIPE-5 — El aviso transporta el mensaje del motor tal cual, bajo un encabezado propio.** El
front no traduce ni mapea artefacto→sección: eso sería lógica de dominio en la UI, que SDD-23 §3.3
prohíbe. El copy propio es el encabezado —«Este config todavía no se puede ejecutar»— y el cuerpo es
el mensaje del motor, que es el que sabe. Que ese mensaje nombre artefactos en jerga
(`('survival', 'term_structure')`) es una deuda **del motor**: se anota, no se parchea aquí.

**D-PIPE-6 — `/api/validate` sigue respondiendo 200 siempre.** Cualquier excepción de la resolución
—`ConfigError`, `MissingDependencyError` por un extra ausente, o lo que levante un `from_config`—
se traduce a `executable=false` + `message`. Un endpoint de validación que responde 500 porque el
config es malo es el defecto que esta familia de enmiendas viene corrigiendo.

## 3. Lo que NO se hace

- **No se resiembra `survival` automáticamente.** Se mantiene lo decidido en RUN-ERROR-RESOLUCION §3:
  el motor dice qué falta y el usuario decide.
- **No se reescribe el mensaje del motor** para nombrar la sección apagada en vez del artefacto.
  Mejora real y medible, pero es alcance propio: toca `_validate_pipeline`, que es núcleo con
  cobertura regulatoria, y su copy lo consumen la UI y el camino por código.
- **No se valida nada que dependa del dataset** (columnas, tipos, nulos). Eso exige leer los datos y
  ocurre dentro de un paso: es el territorio que ya cubre RUN-ERROR.

## 4. Cambio de comportamiento (medido)

| | antes | después |
|---|---|---|
| `POST /api/validate` sobre un config inejecutable | `{valid: true, config_hash: …, errors: []}` | idem **+** `pipeline: {executable: false, steps: [], message: "El paso 'provisioning_ifrs9' requiere…"}` |
| `POST /api/validate` sobre un config ejecutable | idem | idem **+** `pipeline: {executable: true, steps: [10 pasos], message: null}` |
| Botón Ejecutar | habilitado | **habilitado** (D-PIPE-4) |
| Camino por código | no existía | `nikodym.check_pipeline(config)` |

Ningún consumidor existente se rompe: los tres campos viejos conservan tipo y semántica, y un
cliente que ignore `pipeline` se comporta como hoy.

## 5. Verificación exigida antes de cerrar

- Un test que **falle contra el código viejo**, no sólo que pase (la regla de la casa): el del
  endpoint con el config del preset F4 sin `survival`.
- Los dos sentidos de D-PIPE-1: un config inválido para Pydantic sigue dando `valid=false`, y un
  config inejecutable sigue dando `valid=true`.
- El coste del debounce medido en el servidor real (`python -m nikodym.ui`), no en un banco de
  pruebas: es el que recibe `pip install`.
- Verificación **en vivo en la pantalla**, encendiendo `provisioning_ifrs9` desde el formulario: el
  aviso aparece mientras se edita, sin apretar Ejecutar.
