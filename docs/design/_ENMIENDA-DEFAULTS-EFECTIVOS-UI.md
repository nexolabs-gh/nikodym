# Enmienda SDD — la UI muestra el mismo config que ejecuta

> **Estado: APROBADA (Cami, 2026-07-31).** Esta enmienda conjunta cierra el diseño previo de D1 y
> D2. No contiene implementación.
>
> **Base:** `main` = `8089da079f9e51d6a4a2d582b1837c9b497480c0` (CI verde 16/16).
> **Autor / Fecha:** DanIA / 2026-07-31.

| Campo | Valor |
|---|---|
| **Problema** | La firma dura de `ReportStep` puede exigir una card de un dominio que no correrá, y el formulario pinta vacío un campo ausente cuyo modelo Pydantic aplicará un default no vacío |
| **Enmienda a** | SDD-01 §4/§7 (contexto de resolución), SDD-05 §5 (presencia e identidad), SDD-23 §3–§5/§9 (editor), SDD-26 §3/§4/§11 (report y `missing_policy`) |
| **No toca** | El default de ocho `required_sections`, la semántica de CT-1 para un step activo, el algoritmo de `config_hash`, los presets, los censos cerrados ni los paquetes B/C |
| **Release** | Corrección observable y aditiva para el próximo corte autorizado; exige CHANGELOG. Esta tarea no autoriza bump, tag ni publicación |

## 1. Evidencia y alcance

El defecto D1 está en la frontera entre dos dueños. `ReportStep.from_config` recibe sólo
`ReportConfig`, pero el conjunto efectivo de pasos lo conoce `Study._resolve_steps`; por eso filtrar
por dominios activos no puede implementarse honestamente dentro del constructor actual ni con un
caso especial para `eda`. `ReportBuilder`, en cambio, ya aplica `missing_policy`: `error` falla,
`warn` publica una sección ausente y `skip` la omite dejando la limitación trazada.

El defecto D2 tampoco se resuelve leyendo más profundamente JSON Schema. En Pydantic, campos como
`report.sections`, `report.html`, `model.stepwise` y `selection.correlation` nacen de
`default_factory`; la coacción materializa sus objetos completos, pero sus nodos JSON Schema no
traen `default`. La medición cerrada deja 394 hojas visibles, 227 defaults no triviales, dos
mentiras vivas en F1 y 80 al activar secciones. No se recensa nada aquí.

Alcance: contrato de resolución del report, catálogo de defaults efectivos, lectura visual del
formulario, carga/guardado sparse, identidad y gates. No se modifica código en esta enmienda.

## 2. Decisiones

**D-FX-1 — “Activo” significa presente en la lista efectiva de esa invocación.** El conjunto es
`frozenset(nombres)` después de resolver la precedencia `steps=` → `config.run.steps` → pipeline por
secciones no nulas. Una sección configurada pero omitida por `steps=` está apagada para esa corrida;
usar sólo `section is not None` daría un DAG distinto del que se ejecutará.

**D-FX-2 — El contexto llega por una extensión genérica y opcional del resolver.** Un componente
puede exponer `from_config_with_context(sub_cfg, *, active_domains)`; si ese hook no es callable,
`Study` usa el `from_config(sub_cfg)` vigente. No habrá `if name == "report"`, introspección de
firmas ni escritura del contexto dentro de Pydantic. Una construcción directa de
`ReportStep.from_config(ReportConfig())` mantiene la firma histórica para no romper uso standalone.

**D-FX-3 — La firma dura del report es una doble intersección.** Para una corrida resuelta:

```text
ReportStep.requires = tuple(
  (domain, key)
  for domain, key in REPORT_REQUIRED_CARDS
  if domain in set(report.sections.required_sections) and domain in active_domains
)
```

`REPORT_REQUIRED_CARDS`, `required_sections` y su default de ocho —incluido `eda`— no cambian. El
filtro vale para cualquier dominio, no sólo EDA. Las cards que el builder puede adoptar si existen
siguen siendo consumos opcionales y deben participar en el mecanismo genérico ya existente de
`optional_requires`; no se reabre la puerta de artefactos.

**D-FX-4 — `missing_policy` gobierna una sección requerida cuyo dominio está apagado.** Como esa
card deja de ser prerequisito duro, `check_pipeline` resulta ejecutable y el report alcanza
`ReportBuilder`: `error` falla en el paso `report`; `warn` termina y publica la ausencia; `skip`
termina, omite la sección y conserva la limitación. No se muta `required_sections` al resolver:
el builder necesita la lista original para saber qué falta.

Un step **activo** que declaró la card en `provides` y no la publicó sigue incumpliendo CT-1:
`ArtifactNotFoundError` antes de entrar al builder, para las tres políticas. `missing_policy` no es
permiso para ocultar un productor roto. Esta precisión sustituye la frase demasiado amplia del plan
que atribuía la misma degradación a una card ausente de un dominio activo.

**D-FX-5 — La fuente canónica de presentación es un catálogo de defaults efectivos derivado de las
clases Pydantic registradas.** `GET /api/schema` crece aditivamente con
`effective_defaults`; `json_schema`, `defaults` y `section_order` conservan significado. El catálogo
se construye desde `cargar_configs_de_dominio()` y `model_fields`, ejecutando el mismo
default/default_factory que Pydantic, serializado por alias y modo JSON. No se mantiene a mano.

El artefacto es versionado. Su coordenada propia `sections` indexa los subconfigs raíz; `$defs`
refleja la coordenada homónima del schema compuesto para modelos anidados/variantes. Las claves de
`$defs` son exactamente las que referencia `json_schema`, no un identificador paralelo inventado
por el front. Cada hoja usa un descriptor, no el valor desnudo, para diferenciar “sin default” de
“default `null`”: `has_default=false` omite la clave `value`; `has_default=true` la incluye aunque
sea `null`.

```json
{
  "effective_defaults": {
    "version": 1,
    "sections": {
      "report": {
        "sections": {
          "required_sections": {
            "has_default": true,
            "value": ["eda", "binning", "selection", "model", "scorecard",
                      "calibration", "performance", "stability"]
          }
        }
      }
    },
    "$defs": {
      "data__RandomSplitConfig": {
        "holdout_fraction": {"has_default": true, "value": 0.15}
      }
    }
  }
}
```

Los modelos con campos obligatorios también publican los defaults de sus campos no obligatorios:
no se exige inventar una instancia raíz inválida. La paridad se prueba contra
`FieldInfo.get_default(call_default_factory=True)` y, en modelos construibles, contra
`Cls().model_dump(mode="json", by_alias=True)`; las variantes se contrastan después de aportar sólo
sus campos requeridos. Alias como `schema` son los del payload, nunca nombres Python como `schema_`.

**D-FX-6 — JSON Schema sigue siendo la verdad de forma y validación, no de defaults efectivos.** El
schema decide tipo, nulabilidad, restricciones, enum, widgets y discriminador. El catálogo decide
qué valor efectivo pinta una ausencia. JSON Schema por sí solo no basta porque `default` es una
anotación opcional, no aplica defaults, y Pydantic no lo emite necesariamente para submodelos creados
por `default_factory`; inferir `{}`, `false`, `0` o la primera opción duplicaría lógica y ya produjo
las 80 divergencias.

**D-FX-7 — Ausente y falsy explícito son estados contractualmente distintos.** La resolución visual
usa presencia de clave, no `??`, truthiness ni igualdad con el default:

```text
si path existe en config: displayed = valor almacenado, provenance = explicit
si path no existe y descriptor.has_default == true:
  displayed = descriptor.value, provenance = default
si path no existe y no hay descriptor o descriptor.has_default == false:
  displayed = undefined, provenance = missing
```

Por tanto `null`, `false`, `0`, `""` y `[]` explícitos jamás caen al default. El helper de lectura
debe devolver también la procedencia; todos los widgets —boolean, select, number/text y
multiselect— consumen el mismo helper. Un valor virtual se identifica con copy público breve:
“Predeterminado; se usará mientras no elijas otro.” No se muestran `unset`, `default_factory`,
Pydantic ni JSON Schema.

**D-FX-8 — Pintar no escribe; el primer gesto sí.** Montar la app, abrir una pestaña, cambiar de
sección, resolver un valor virtual y descargar/guardar sin editar no invocan `setAtPath` ni añaden
claves. Un YAML parcial de la versión vigente vuelve al store con la misma presencia de claves tras
normalización JSON y alias; una migración declarada puede transformar su versión, pero no
materializa defaults ajenos. `from-yaml` debe devolver la proyección validada con
`exclude_unset=True`; `to-yaml` conserva esa misma frontera.

El primer gesto sobre un control materializa **sólo ese path** con el valor resultante. Excepciones
que son gestos de estructura: activar una sección/objeto escribe recursivamente todas las hojas
`has_default=true` de su proyección canónica y omite las obligatorias sin default; cambiar una
variante escribe el tag y las hojas con default de esa variante. Quitar un chip de un multiselect
virtual escribe la lista completa restante. Tocar el valor que ya coincide con el default puede
cambiar sparse→explícito sin cambiar identidad.

**D-FX-9 — La identidad es una invariante, no un efecto visual.** Renderizar, abrir o guardar sin
interacción conserva el dict sparse y el `config_hash`. No cambia el algoritmo ni ningún golden:
el hash ya identifica el config efectivo coaccionado, por lo que ausente y default explícito tienen
el mismo digest. Tras el primer gesto, el hash cambia sólo si cambió un valor computacional efectivo;
un valor igual al default o un campo de `report` puede materializarse sin moverlo.

**D-FX-10 — Compatibilidad y rollout son aditivos y atómicos por artefacto.** Clientes viejos de
`/api/schema` ignoran `effective_defaults`; el campo raíz `defaults` conserva el config vacío con
secciones nulas. Extras ausentes dejan su dominio opaco y sin defaults fabricados; backend y fixture
declaran exactamente el mismo catálogo disponible. Cualquier cambio del payload viaja en el mismo
commit que el fixture, los tipos TypeScript, Vitest y el bundle normal versionado. El CHANGELOG debe
declarar el cambio observable de `check_pipeline` y que la UI ahora distingue valor predeterminado
de valor explícito. El copy actual “Sección desactivada: no se incluye en el config” se corrige:
`null` explícito sí puede estar incluido; la promesa pública es “no se ejecuta”. No se resembran
presets ni se toca el `config_hash`.

## 3. Matrices contractuales

### 3.1 DAG, dominios y política

La matriz se ejecuta con config tipado y con la misma sección como dict opaco. `X` es primero `eda`
y luego un dominio no específico (`stability`) para impedir un parche.

| `X` requerido | `X` activo en pasos efectivos | card al llegar a report | política | `check_pipeline` | runtime |
|---|---:|---:|---|---|---|
| sí | no | no | `error` | ejecutable | falla en `report` con `ReportInputError` |
| sí | no | no | `warn` | ejecutable | `done`, sección `missing` sin números |
| sí | no | no | `skip` | ejecutable | `done`, omitida y declarada en limitaciones |
| sí | sí | sí | cualquiera | ejecutable | `done` |
| sí | sí | no por incumplimiento del productor | cualquiera | ejecutable si el productor la declaró | `ArtifactNotFoundError` CT-1 antes de report |
| no | no | no | cualquiera | ejecutable | omitida, no figura como faltante |

Un productor activo colocado después de `report` sigue haciendo el pipeline inejecutable. Una
sección no nula omitida de `steps=` cuenta como apagada (D-FX-1).

### 3.2 Presencia, falsy y widgets

| estado almacenado | default efectivo de prueba | widget | pinta | escribe al render |
|---|---|---|---|---:|
| ausente | `true` | boolean | activado + indicador de predeterminado | no |
| `false` explícito | `true` | boolean | desactivado | no |
| ausente | `"show"` | select | `show` + indicador | no |
| `""` explícito | texto no vacío | text/select nullable | vacío | no |
| ausente | `7` | number | `7` + indicador | no |
| `0` explícito | `7` | number | `0` | no |
| ausente | ocho secciones | multiselect | ocho chips + indicador | no |
| `[]` explícito | ocho secciones | multiselect | cero chips | no |
| `null` explícito | cualquier valor | nullable | desactivado/nulo | no |

## 4. Alternativas rechazadas

1. **Sacar `eda` del default.** Arregla un preset y deja viva la clase para cualquier otro dominio.
2. **Filtrar en `Study` sólo cuando `name == "report"`.** Acopla el núcleo a un dominio y es el
   parche específico prohibido.
3. **Considerar activo todo subconfig no nulo.** Miente con `steps=` parciales o reordenados.
4. **Quitar todas las cards de `requires`.** Oculta incumplimientos CT-1 de productores activos.
5. **Sembrar desde el preset.** No cubre “Empezar de cero”, YAML parcial, variantes ni campos nuevos.
6. **Inferir recursivamente desde JSON Schema.** No ve `default_factory` y crea una segunda fuente.
7. **Materializar al montar o al guardar.** Cambia el documento que el usuario no editó y puede
   mover identidad computacional.
8. **Usar `value ?? default`.** Confunde `null` explícito con ausencia; usar truthiness además rompe
   `false`, `0`, `""` y `[]`.

## 5. Orden de implementación futura

1. **D1 — contexto de resolución genérico + `ReportStep`.** Añadir la fábrica opcional, derivar la
   doble intersección, declarar consumos opcionales y cerrar la matriz Python tipada/opaca.
2. **D2 — commit atómico de contrato y UI.** Generar `effective_defaults`, ampliar `/api/schema`,
   preservar sparse en YAML, incorporar resolver puro y procedencia en todos los widgets, regenerar
   fixture, correr Vitest/typecheck y reconstruir bundle en el mismo commit.
3. **Integración.** CHANGELOG/copy, presets y hashes como controles negativos, build reproducible y
   recorrido real de los dos casos F1. Ningún paso autoriza release.

## 6. Gates de aceptación

- La matriz §3.1 completa para config tipado/opaco, EDA y otro dominio; `ReportStep.from_config`
  standalone y pipelines/presets existentes conservan compatibilidad.
- Los dos casos vivos F1: `report.html.render_charts` pinta `true` virtual y
  `report.document.placeholders` pinta `show` virtual, sin mutar config ni hash.
- Caso causal: activar `report` desde config vacío pinta ocho chips; EDA apagada deja preflight
  ejecutable y `error|warn|skip` llega al runtime definido. El usuario puede retirar `eda` y se
  materializan exactamente siete valores.
- Muestra adversarial del censo de 80: `model.stepwise.enabled`,
  `selection.correlation.enabled`, `selection.vif.threshold`,
  `provisioning_cmf.matrices.active_version`, `provisioning_ifrs9.pd.pit_mode` y
  `provisioning_ifrs9.staging.dpd_default_backstop` coinciden con la coacción real, tanto al partir
  de sección tipada como de dict opaco y sin depender del orden de imports.
- Gate no vacuo: recorre las **394** hojas actuales y anclas nombradas de las 14 secciones; todo nodo
  con descriptor coincide con `model_fields`, y todo `default_factory` visible tiene cobertura. Un
  cambio legítimo del total exige actualizar el golden y sus anclas en el mismo cambio. El control
  negativo altera un default del artefacto capturado y obliga al gate de paridad a fallar.
- Matriz §3.2 completa; render/open/save conservan igualdad estructural sparse; el hash de una
  sección computacional omitida conserva su digest; el primer gesto escribe sólo el path y el hash
  cambia únicamente cuando cambia su valor efectivo.
- `/api/schema` conserva los tres campos previos y añade el catálogo versionado; extra ausente
  degrada opaco; repeticiones producen bytes determinísticos.
- Copy público en español, sin jerga interna, y accesibilidad del indicador de predeterminado bajo
  los gates existentes de Python y frontend.
- Fixture `web/src/fixtures/schema.json` sin drift; Vitest del resolver/widgets, lint/typecheck,
  build normal, supply-chain/licencias, bundle versionado y build de distribución reproducibles.
- `git diff --check`, MkDocs strict y ausencia de cambios accidentales en hashes/presets. La futura
  implementación ejecutará además los gates focales Python/React y la suite proporcional al alcance.

No quedan decisiones de diseño abiertas para D1/D2.
