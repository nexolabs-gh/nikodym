# Enmienda SDD — el fallo de una corrida deja rastro legible en `run_context`

> **Estado: APROBADA (Cami, 2026-07-25).** Ejecuta el P0 del handoff del 2026-07-25.
>
> **Base:** `main` = `d1347ee` (CI verde).
> **Autor / Fecha:** DanIA / 2026-07-25.

| Campo | Valor |
|---|---|
| **Problema** | Por el camino que la documentación recomienda, una corrida que falla no deja ni el mensaje ni el paso: el error se emite a un sink nulo y se pierde |
| **Enmienda a** | SDD-01 (§4 `RunContext`, §7.3 secuencia de `run`), SDD-23 §8 (serialización del fallo en la UI) |
| **No toca** | La semántica **D-UI-2** (`nikodym.run` captura el `NikodymError` y devuelve el `Study` parcial), ni `Study.run()` como primitivo *fail-loud* que re-levanta |
| **Release** | `1.6.0`. Extensión **aditiva** de `RunContext`: no rompe la garantía SemVer 1.x del pipeline F1 |

---

## 1. El problema, medido

Reproducción por el camino literal de [`docs_site/getting-started.md`](../../docs_site/getting-started.md)
—preset F1, dataset del propio preset con una columna de menos, que es lo primero que pasa cuando
alguien apunta el motor a su cartera—:

```
status      : failed
run_id      : 5304ae10bb1f44308747cd274dd0903f
started_at  : 2026-07-25 19:49:47.216538+00:00
finished_at : None
results     : {}
artefactos  : 0
lineage     : 413 bytes de hashes
campos de run_context: ['finished_at', 'lineage', 'run_id', 'started_at', 'status']
```

El motor **sí** produce un diagnóstico excelente —«El DataFrame no cumple el esquema declarado…
columna: `mora_max_12m`»—: `Study.run` lo emite en el evento `run_end`
([`study.py:293`](../../src/nikodym/core/study.py)). Pero el preset F1 trae `audit: null`, así que
`assemble_run` devuelve un `NullAuditSink` ([`api.py:136`](../../src/nikodym/api.py)) y el mensaje
se emite al vacío. El usuario se queda con la palabra `failed` y 413 bytes de hashes.

Tres consecuencias, todas verificadas en el árbol:

1. **La documentación afirma algo falso, en cinco superficies.** El docstring de `run`
   ([`api.py:37`](../../src/nikodym/api.py)), el `README.md:148`, `docs_site/index.md:88`,
   `docs_site/tutorial.md:111` y `docs_site/getting-started.md:140` dicen que el fallo «vive en
   `study.run_context.status`, en el audit-trail y en el lineage». De los tres lugares **sólo el
   primero es cierto**: el lineage no guarda el error nunca, y el audit-trail sólo si el usuario
   configuró un sink — cosa que el preset recomendado no hace.
2. **La UI arrastra el mismo defecto, y está documentado como desviación.**
   [`ui/serializers.py:67`](../../src/nikodym/ui/serializers.py) tiene un `_FAILURE_MESSAGE`
   genérico con el comentario «`run_context` NO persiste el mensaje del `NikodymError` de dominio
   (…) de modo que la serialización no puede recuperarlo desde el `Study`». El front ya está listo
   para mostrar el mensaje real (`RunTab.tsx:192`, `ResultsTab.tsx:254`): recibe el genérico porque
   el backend no tiene otro que darle.
3. **`finished_at` queda `None` en el camino de fallo.** La corrida terminó y el contexto no dice
   cuándo. Es el mismo `except` el que lo omite.

Esto no es cosmético: es **paridad UI↔código** (requisito 1 de la visión de producto) y es el
requisito previo para el barrido con datasets externos (requisito 2) — depurar un dataset sucio
contra un motor que sólo dice `failed` es a ciegas.

## 2. Las decisiones

**D-ERR-1 — El rastro del fallo vive en `RunContext`, no en un canal opcional.** Se añade
`RunContext.error: RunError | None = None`. Es la única de las tres salidas evaluadas que no cambia
comportamiento para quien no falla: un sink en memoria por defecto le impondría acumulación de
eventos a **todas** las corridas, y devolver el trail desde `run` rompería su firma.

**D-ERR-2 — Modelo `RunError`** (`frozen`, `extra="forbid"`, junto a `RunContext` en
`core/lineage.py`):

| Campo | Tipo | Qué guarda |
|---|---|---|
| `type` | `str` | Nombre de la clase de la excepción (`DataValidationError`, `KeyError`…) |
| `message` | `str` | `str(exc)` **íntegro**, con el código de marca si el mensaje lo trae |
| `step` | `str \| None` | Paso del pipeline que falló; `None` si el fallo fue fuera del bucle de pasos |
| `is_domain_error` | `bool` | Si la excepción es un `NikodymError` (mensaje redactado para humanos) o algo inesperado |
| `ts` | `datetime` | Instante del fallo, en UTC |

Los nombres van en inglés como el resto de los modelos del `core` (`AuditEvent.step`,
`AuditEvent.ts`, `LineageBundle.git_sha`).

**D-ERR-3 — `finished_at` se sella también en fallo.** Una corrida terminada declara cuándo
terminó, haya salido bien o mal.

**D-ERR-4 — El mensaje íntegro es para el código; la UI publica el mensaje saneado.** Once `raise`
del motor llevan el código de marca al frente del mensaje (`DATO-INSTITUCIONAL-FWD-1: adverse/severe
deben declarar…`). En `run_context.error.message` ese código **se conserva**: es la superficie de
código, donde el código es el dato — la misma razón por la que se conserva en `warning_codes` y en
el anexo de auditoría del informe. En la UI **no**: el panel de resultados es copy público, así que
el mensaje se publica sin el código, vía `strip_declared_codes()` en `core/markers.py`.

**D-ERR-5 — La UI sólo publica el mensaje de un error de dominio.** Con `is_domain_error=False`
—un `KeyError` de pandas, un bug— se mantiene el mensaje genérico más el tipo de la excepción: un
traceback interno no es información útil para quien usa el formulario, y puede arrastrar rutas del
sistema de archivos del servidor.

**D-ERR-6 — El evento `run_end` crece de forma aditiva.** Suma `error_type` y `step` al payload
conservando la clave `error`: un lector del trail existente no se entera (CT-3, crecimiento
aditivo).

**D-ERR-7 — Compatibilidad de `run_metadata.json`.** El campo lleva default `None`, así que un
bundle guardado antes de esta enmienda recarga sin tocarlo. Un bundle **nuevo de una corrida
fallida** leído por una versión anterior sería rechazado por `extra="forbid"`; es el precio
conocido de una extensión aditiva y no afecta a las corridas en éxito, donde el campo serializa
como `null`.

## 3. Superficies afectadas

| Archivo | Cambio |
|---|---|
| `src/nikodym/core/lineage.py` | Modelo `RunError` + campo `RunContext.error` |
| `src/nikodym/core/study.py` | Poblar el campo y `finished_at` en el `except`; `run_end` aditivo |
| `src/nikodym/core/markers.py` | `strip_declared_codes()` |
| `src/nikodym/ui/serializers.py` | Mensaje real saneado; el genérico queda como *fallback* |
| `src/nikodym/api.py`, `README.md`, `docs_site/{index,tutorial,getting-started}.md` | Corregir la afirmación falsa |
| `web/` | **Ninguno.** El front ya muestra `results.error` |

## 4. Criterios de aceptación

1. La reproducción del §1 imprime el mensaje del motor y el paso que falló, sin configurar ningún
   sink.
2. `finished_at` no es `None` tras un fallo.
3. Un `Study` fallido sobrevive el round-trip `save`/`load` con su `error` intacto, y un
   `run_metadata.json` sin el campo sigue recargando.
4. La UI devuelve el mensaje de dominio **sin** código de marca ante un `NikodymError`, y el
   genérico ante una excepción inesperada.
5. Ninguna de las cinco superficies sigue afirmando que el error vive en el lineage.
6. Todo test nuevo se verifica **fallando** contra el árbol anterior.
