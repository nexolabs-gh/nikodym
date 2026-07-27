# Enmienda SDD — el fallo de RESOLUCIÓN del pipeline también deja rastro

> **Estado: APROBADA (Cami, 2026-07-27).**
>
> **Base:** `main` = `3231c98` (CI verde 16/16).
> **Autor / Fecha:** DanIA / 2026-07-27.

| Campo | Valor |
|---|---|
| **Problema** | Un config inejecutable no deja rastro alguno: el motor produce un diagnóstico exacto y la cadena entera lo tira, hasta acabar en un HTTP 500 opaco |
| **Enmienda a** | [`_ENMIENDA-RUN-ERROR.md`](_ENMIENDA-RUN-ERROR.md) (D-ERR-1…D-ERR-7), SDD-01 §7.3 (secuencia de `run`) |
| **No toca** | `Study.run()` como primitivo *fail-loud* que re-levanta, ni **D-UI-2** (`nikodym.run` captura y devuelve el `Study` parcial). El `RunError` de D-ERR-2 se reutiliza tal cual |
| **Release** | Sin publicar. **Cambia comportamiento observable**: ver §4 |

---

## 1. El problema, medido

Reproducción por el camino del usuario de la UI instalable, el 2026-07-27: dataset
`ifrs9_retail_latam`, sección `provisioning_ifrs9` encendida desde el formulario (que es lo primero
que hace quien quiere provisiones), y **Ejecutar**. Lo que el usuario ve:

> **No se pudo ejecutar la corrida** · HTTP 500 en run · *Ajusta el config o el dataset y reintenta.*

Lo que el motor **sí sabía decir**, capturado llamando a `Study.run()` directo:

```
ConfigError: El paso 'provisioning_ifrs9' requiere ('survival', 'term_structure'),
que ningún paso aguas arriba produce: config inejecutable.
```

Ese mensaje es exactamente lo que el usuario necesita —le falta encender `survival`— y no lo ve
nadie. La cadena que lo pierde, medida capa por capa:

| capa | qué pasa | estado resultante |
|---|---|---|
| `Study.run()` ([`study.py`](../../src/nikodym/core/study.py)) | `_resolve_steps`/`_validate_pipeline` levantan **antes** de asignar `run_id`, y quedan **fuera** del `try` que registra el fallo | re-levanta, `run_context` intacto |
| `api.run()` ([`api.py`](../../src/nikodym/api.py)) | captura el `NikodymError` (D-UI-2) y devuelve el `Study` | `status="created"`, `run_id=None`, **`error=None`** |
| `run_pipeline` ([`ui/routes.py`](../../src/nikodym/ui/routes.py)) | `runs.save()` sobre un `Study` sin `run_id` | `UiError` → **HTTP 500** |

Tres consecuencias, todas verificadas en el árbol:

1. **Dos docstrings afirman algo falso.** El de `api.run` dice que el diagnóstico «queda en
   `study.run_context.error` … sin que haya que configurar nada»: vale `None`. El de `run_pipeline`
   dice que una corrida fallida «devuelve `status="failed"` (nunca un 500 opaco)»: dio uno.
2. **El camino por código está peor que el de la UI.** `nikodym.run()` devuelve `status="created"`
   —ni `"done"` ni `"failed"`—, o sea un valor que el propio docstring no contempla al mandar
   chequear el status. El fallo no se degrada: **se silencia entero**, que es justo lo que D-ERR-1
   existía para impedir.
3. **La enmienda RUN-ERROR resolvió sólo la mitad del problema que describía.** Su manejo de fallo
   vive dentro del `try` que envuelve el bucle de pasos, así que cubre los fallos de **ejecución** y
   no los de **resolución**. No fue un descuido: su §1 se midió con un dataset al que le faltaba una
   columna, y ese fallo ocurre dentro de un paso.

**Es paridad UI↔código (requisito 1) en su forma más literal:** la capacidad de configurar
provisiones por formulario se entregó en `3231c98`, y el primer usuario que la ejercita recibe un
500. Una feature que el usuario no puede completar cuenta como no entregada.

## 2. Las decisiones

**D-ERR-8 — La garantía de D-ERR-1 cubre la corrida ENTERA, no sólo el bucle de pasos.** Un fallo de
resolución o de validación del pipeline registra `status="failed"`, `finished_at` y
`run_context.error` igual que uno de ejecución. El criterio que separa las dos fases es interno al
motor; para quien llama, «la corrida falló» es una sola cosa.

**D-ERR-9 — `run_id` se asigna ANTES de resolver los pasos.** Es lo que hace posible D-ERR-8 y lo que
permite persistir la corrida fallida: sin `run_id` no hay nada que guardar, y ése era el 500. Una
corrida inejecutable es una corrida que se intentó, y el audit-trail SR 11-7 la registra como tal.

**D-ERR-10 — El registro del fallo vive en UN helper.** `_registrar_fallo(exc, paso, run_id)`, usado
por las dos fases. Duplicar el bloque es lo que permitiría que vuelvan a divergir — que es
literalmente el defecto que esta enmienda corrige.

**D-ERR-11 — `step=None` en un fallo de resolución, y es información, no un hueco.** No hay paso en
curso: el config es inejecutable *antes* del primero. `RunError.step` ya admite `None` (D-ERR-2), y
distinguirlo de un fallo dentro de un paso le dice al lector dónde mirar — el config, no los datos.

## 3. Lo que NO se hace

- **No se valida el pipeline en `/api/validate`.** Es tentador —avisaría al usuario mientras edita,
  antes de Ejecutar— pero cambia el significado de «config válido»: hoy es «reconstruye el modelo
  Pydantic», y pasaría a ser «además es ejecutable». Merece su propia decisión, con su copy.
  Anotado como candidato, no incluido.
- **No se resiembra `survival` automáticamente al encender `provisioning_ifrs9`.** Adivinar qué
  secciones quiere el usuario es exactamente el tipo de magia que este repo evita: el motor dice qué
  falta y el usuario decide.

## 4. Cambio de comportamiento (medido, no estimado)

Para un config **inejecutable**, `nikodym.run()` devolvía y devolverá:

| | antes | después |
|---|---|---|
| `run_context.status` | `"created"` | `"failed"` |
| `run_context.run_id` | `None` | asignado |
| `run_context.error` | `None` | `RunError(type="ConfigError", message=…, step=None)` |
| `run_context.finished_at` | `None` | sellado |

`Study.run()` sigue re-levantando en ambos casos: el primitivo *fail-loud* no cambia.

**Un test del Hito 0 fija hoy el estado viejo** — `test_hito0_contracts.py::…_ct1_fan_in…` afirma
`status == "created"` tras exactamente este `ConfigError`. Ese assert es **incidental** al propósito
del test, que es garantizar que un config inejecutable no ejecuta nada (`executed is False`,
`artifacts` vacío): eso no cambia. Se actualiza el assert con su razón escrita al lado, porque un
contrato que se toca en silencio es peor que uno que se rompe.

Es una mejora estricta —antes no había nada que inspeccionar— y la extensión de `RunContext` sigue
siendo la aditiva de D-ERR-7, así que no rompe la garantía SemVer 1.x del pipeline F1.
