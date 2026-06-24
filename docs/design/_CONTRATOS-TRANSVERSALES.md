# Contratos transversales v1 — decisiones troncales (Hito 0)

| Campo | Valor |
|---|---|
| **Documento** | Contratos transversales — estabilización troncal previa a F0 código |
| **Tipo** | Decisiones de diseño troncal (cruza todos los SDD) |
| **Versión** | 1.0 |
| **Fecha** | 2026-06-24 |
| **Autor** | DanIA |
| **Base** | [`ESPECIFICACIONES.md`](../ESPECIFICACIONES.md) · [`01-core.md`](01-core.md) · [`02-data.md`](02-data.md) · [`03-audit-governance.md`](03-audit-governance.md) · [`04-tracking.md`](04-tracking.md) |
| **Estado** | Aprobado (Hito 0) — propagado a SDD-01/02/03 |

---

## 1. Por qué existe este documento

El proyecto pasó de waterfall a **incremental por capa** (diseñar una capa → programarla → validar el molde con código → seguir). Es la decisión correcta para el **80%** del sistema: la lógica intra-capa se valida mejor con código que con markdown.

Pero el incremental *puro* tiene un punto ciego: **no obliga a confrontar los contratos que cruzan todas las capas antes de cementarlos**. Una revisión adversarial multi-agente de los 7 SDD de Fundación (madurez 4/5, molde maduro y de calidad ejemplar) convergió —desde cuatro lentes independientes— en que **cuatro contratos transversales están hoy dimensionados solo para el caso fácil (scoring lineal/escalar) y solo se rompen en F4/F5**, cuando ya habrá 4 capas de código y un release público v0.1.0 encima. Codificar F0/F1 con un scorecard **no los ejercita** (un scorecard es una cadena lineal de salidas escalares) → pasaría verde y daría falsa confianza de "molde validado".

Este documento **estabiliza la *extensibilidad*** de esos cuatro contratos antes de codificar F0. **Regla rectora:**

> **Diseña de extremo a extremo lo que es caro cambiar (interfaces transversales). Difiere *just-in-time* lo que es barato cambiar (lógica intra-capa).**

**Qué NO es este documento.** No es el diseño de F4/F5 ni de los 20 SDD pendientes. No fija las matemáticas de ECL, ni el *shape* exacto de la term-structure, ni un segundo *loader* longitudinal. Fija **firmas y puertas de extensión**, no algoritmos. Diseñar de más aquí es el riesgo simétrico (waterfall por la puerta de atrás) y está acotado deliberadamente (§6).

---

## 2. Las cuatro decisiones

Cada contrato distingue **lo que se fija ahora** (barato, estructural, no especulativo) de **lo que se difiere** (requiere el SDD de su dominio).

### CT-1 — Orquestación: el `Step` expresa el DAG desde v1 (motor topológico diferido)

**Problema.** El orquestador de SDD-01 ejecuta los pasos en el **orden de declaración** de las secciones del config, y las claves de I/O entre pasos están "documentadas por cada dominio" (`Step` solo declara `name` + `execute`; SDD-01 §6 admite "o la salida del paso previo"). Es una **cadena lineal implícita**. Pero `forward` (macro→satellite→term-structure→ecl) y `stress` (multi-escenario) son **DAGs con fan-in/fan-out**: un paso consume artefactos de varios dominios. Convertir el bus lineal en DAG cuando llegue F5 es el **refactor más caro del programa** (toca el `Step`, `StepAdapter`, `run_step`, el `LineageBundle` y toda capa ya codificada).

**Decisión — se fija ahora.** El Protocol `Step` (y `StepAdapter`) declara sus dependencias **explícitas** sobre el `ArtifactStore`:

```python
ArtifactKey = tuple[str, str]   # (domain, key) — la misma clave namespaced de ArtifactStore (SDD-01 §6)

@runtime_checkable
class Step(Protocol):
    name: str
    requires: tuple[ArtifactKey, ...]   # claves que LEE del ArtifactStore (vacío = no depende de upstream)
    provides: tuple[ArtifactKey, ...]   # claves que ESCRIBE
    def execute(self, study: "Study", rng: "numpy.random.Generator") -> Any: ...
```

`StepAdapter` deriva `requires`/`provides` de las **claves de I/O documentadas del dominio** (SDD-01 §6) — no es trabajo nuevo del dominio, es hacer explícito en la firma lo que ya estaba en prosa.

**Qué hace el motor v1 con esto (barato).** Antes de ejecutar un paso, **valida que todo `requires` esté presente** en el `ArtifactStore` → si falta, `ArtifactNotFoundError` con el contrato incumplido **antes** de correr (mejor diagnóstico que reventar dentro del `execute`). Tras ejecutar, opcionalmente verifica que `provides` se escribió. **El orden de ejecución v1 sigue siendo el orden de declaración del config.**

**Qué se difiere (a forward/F5).** El **motor topológico** (derivar el orden de ejecución del grafo `requires`/`provides` en vez del orden de declaración, y soportar fan-in/fan-out real). La **firma ya expresa el DAG**; solo el *scheduler* es lineal en v1 y se reemplaza sin tocar la firma ni las capas que la consumen.

**Bonus (resuelve un gap aparte).** `requires`/`provides` **es** el registro de prerequisitos cross-sección que CT-4 necesitaba: "provisioning requiere calibration" se expresa como un `requires=(("calibration","pd_calibrada"),)` cuyo proveedor debe existir aguas arriba. La validación pre-run (un `requires` que ningún paso `provides`) sustituye un "prerequisite registry" ad-hoc.

---

### CT-2 — Resultados y gobernanza: puerta de extensión tipada para payloads estructurados

**Problema.** Los contratos de **lectura** que `report`/`governance`/`ui` consumen nacieron escalares, pensados para scoring (KS/AUC/PSI son `float`):
- `ProvisionResultLike.por_escenario: Mapping[str, float]` — escalar por escenario, **sin eje temporal `t`**. Pero `ECL = Σ_k w_k·Σ_t PD_marg_k(t)·LGD_k(t)·EAD_k(t)/(1+EIR)^t` (ESPEC §5.5) es una **curva lifetime** por escenario.
- `ModelCard.metrics: dict[str, float]` y `log_metrics` filtrando a numéricos finitos — no representan ECL por stage × escenario, term-structure ni matrices de transición Markov.
- `OverlayRecord.value_before/after: float` — un overlay IFRS 9 real opera sobre **vectores/curvas** (control anti *earnings-management* que se rompe justo donde más lo mira el regulador).

Si se publican escalares en v0.1.0 y se rompen en v0.4 al llegar provisiones, es el peor costo reputacional para una librería que vende auditabilidad y estabilidad.

**Decisión — se fija ahora.** Cada contrato de lectura económico o de gobernanza nace con una **puerta de extensión tipada y opcional** para el caso estructurado, **además** del caso escalar. El escalar sigue siendo el camino de scoring; la puerta la usan solo las capas pesadas:

- **Resultados económicos** (`ProvisionResultLike`/`ECLResultLike`, SDD-01 §4 `results.py`): se añade un método opcional para la estructura temporal/multi-dimensional, que devuelve `None` cuando no aplica (CMF agregado) y un `DataFrame` tidy cuando sí (ECL lifetime):
  ```python
  def term_structure(self) -> "pandas.DataFrame | None": ...
      # None si el motor no es multi-período (CMF agregado);
      # DataFrame tidy [escenario, t, componente, valor] si lo es (ECL lifetime, F4).
  ```
- **Model card** (SDD-03): junto a `metrics: dict[str, float]` (escalares, intacto), un campo reservado y aditivo:
  ```python
  metric_sections: dict[str, Any] = {}   # secciones estructuradas (curvas, matrices) que el card renderiza aparte; vacío en scoring
  ```
- **Overlays / escenarios** (SDD-03 `OverlayRecord`/`ScenarioLog`): junto a `value_before/after: float` (intacto), un campo reservado:
  ```python
  payload: dict[str, Any] | None = None   # overlay vectorial/curva (IFRS 9); None en el caso escalar
  ```

**Qué se difiere (a SDD-16/17/20).** El **esquema interno exacto** de la term-structure, del `metric_sections` de ECL y del `payload` de overlays. **No se especifica el shape final** (sería adivinar sin el SDD del dominio). Solo se garantiza que el contrato **crece por extensión (aditivo), nunca por ruptura**: añadir un campo opcional con default no rompe a ningún consumidor existente.

---

### CT-3 — Datos: frontera explícita transversal (scorecard) vs longitudinal (IFRS 9/forward)

**Problema.** El modelo de datos de SDD-02 es un **panel transversal**: una fila = una observación, índice = identificador de observación, **una** ventana de desempeño, partición fija {Dev/HO/OOT}, target **binario**. Pero IFRS 9/ECL es **panel longitudinal por construcción** (PD_marg(t)/LGD(t)/EAD(t) por cuenta a lo largo de `t`, multi-escenario `k`), y forward necesita series macro→satellite→term-structure por `t`. Hoy SDD-02 **no declara** que es "datos de scorecard"; si nadie escribe la frontera, alguien asumirá que `data` sirve para todo y forzará un refactor caro de SDD-02 (o un `data_hash` inconsistente entre paneles) en F4/F5.

**Decisión — se fija ahora (una frase de alcance, no un diseño).** Se declara explícitamente en SDD-02 §12:

> **`data` (SDD-02) modela el panel transversal de scorecard** (unidad = observación, ventana de desempeño única, target binario bueno/malo). **IFRS 9 y forward (F4/F5) requieren un panel longitudinal** (unidad = cuenta × período, exposición/EAD por `t`, múltiples escenarios) y traerán su **propia capa de datos** (un módulo/contrato dedicado, p.ej. `data` longitudinal), **no se fuerza SDD-02 a servir ambos**. Ambas capas derivan su `data_hash` del **mismo mecanismo** (hash de contenido lógico por bloques, D-DATA-2) para que sean comparables en mecánica aunque distintos en forma; el `LineageBundle` admite múltiples fuentes identificadas por nombre de dataset.

**Qué se difiere (a F4/F5).** El **diseño** de la capa de datos longitudinal (su contrato, particiones por añada-de-reporting, staging Stage 1/2/3, definición de default regulatorio). Solo se reserva el **gancho conceptual** y se evita la suposición tóxica.

---

### CT-4 — Owner de orquestación: quién ensambla la corrida (hoy en tierra de nadie)

**Problema.** El primer `Study` end-to-end de F0 choca un gap sin dueño entre los SDD de Fundación: **quién construye y resuelve** el `AuditSink` y el `ModelInventory` reales. `core` toma **un** `AuditSink` ya resuelto (no importa MLflow ni governance); pero alguien tiene que: instanciar `JsonlAuditSink` (SDD-03) + el sink de tracking (SDD-04), componerlos en `FanOutSink`, y resolver `NullInventory` vs `MLflowInventory` según extra instalado + config. Además, el Protocol `ModelInventory` no declara si lleva `@runtime_checkable` (el bug exacto que cazó la Tanda 1 Rev en `Step`).

**Decisión — se fija ahora.**
1. **`ModelInventory` lleva `@runtime_checkable`** (consistente con `Step`, `ProvisionResultLike`, `ECLResultLike`; SDD-03).
2. **Capa de ensamblado de corrida.** El ensamblado vive en una **capa fina de orquestación de alto nivel** (un *runner*/API delgada, p.ej. `nikodym.api`), **fuera de `core`** para no contaminar el núcleo liviano (D-CORE-1). Su contrato:
   ```python
   def assemble_run(config: NikodymConfig) -> tuple[AuditSink, ModelInventory]: ...
       # 1) construye JsonlAuditSink (governance) + sink de tracking (si tracking habilitado);
       #    los compone en FanOutSink([...]);
       # 2) resuelve el inventario: NullInventory por defecto;
       #    MLflowInventory si el extra está instalado Y governance.publish_to_inventory;
       #    si publish_to_inventory=True y falta el extra -> MissingDependencyError (falla ruidoso, contrato regulatorio).
   ```
   `core` sigue recibiendo el `AuditSink` ya compuesto vía `Study.set_audit_sink(...)`. La API de usuario (`nikodym.run(config)`) llama a `assemble_run` y al `Study`; la UI (F7) hace lo mismo. Owner: **SDD-03/04 especifican las piezas; la capa `api`/runner las ensambla** (se documenta en SDD-03 §contratos y se materializa al codificar F0).

**Qué se difiere.** La ubicación final del módulo (`nikodym/api.py` vs `nikodym/runner.py`) se decide al codificar F0 — es un detalle de empaquetado, no de contrato.

---

## 3. Política de versionado (protege el escaparate sin retrasar el release)

El release **v0.1.0 NO se retrasa**: F1 corriendo es el activo que da reputación, y CT-1…CT-4 reducen la superficie de cambios futuros. La tensión "breaking changes en una librería que vende estabilidad" se resuelve con **honestidad de SemVer**, no esperando a F4:

- **`0.x.y` es explícitamente pre-estable.** SemVer permite cambios incompatibles en `0.x`. La estabilidad fuerte se promete desde `1.0.0` (post-suite completa).
- **Marcar como experimental** —en docstrings, `README` y changelog— las APIs que CT-1…CT-2 saben que **crecerán**: los Protocols de resultados, `metric_sections`/`payload`, y el motor de orquestación (DAG diferido). Crecer una API marcada inestable en `v0.4` **no es** un breaking change deshonesto: es lo que `0.x` significa. Gestión de expectativas = protección reputacional.

---

## 4. Criterios de aceptación añadidos a F0 (validar el troncal con código, no en F4)

Codificar F0/F1 con un scorecard no ejercita el troncal. Se añaden al DoD de F0 **pruebas de fuego** que estresan los contratos mientras cambiarlos es gratis:

- **Step dummy con fan-in.** Un `Step` de juguete con **`requires` de dos artefactos de dos dominios distintos** (fan-in real), que ejercite el contrato `requires`/`provides` y la validación pre-run del motor **antes** de que `forward` dependa de él. Criterio de aceptación, no "nice to have".
- **Payload estructurado dummy.** Un test que pase por `log_metrics`/`ModelCard` un `metric_sections` dummy (ECL-like por stage × escenario) y por `OverlayRecord` un `payload` no escalar, para verificar que la puerta de extensión de CT-2 aguanta. Convierte el riesgo de F4/F5 en un test que falla hoy si la firma no sirve.
- **Gate de cobertura regulatoria sin falsos verdes.** El job `coverage-regulatory` **verifica la existencia** de cada módulo declarado regulatorio; hoy `provisioning/cmf|ifrs9` no existen y `0/0=100%` pasaría por vacuidad. La lista de módulos-a-100% falla si un path declarado no se encuentra.

---

## 5. Lo que se difiere (con owner de fase) — anti over-engineering

Estas son deudas **reconocidas y diferidas a propósito**; NO entran al Hito 0 para no inflarlo:

| Deuda | Por qué se difiere | Owner (fase) |
|---|---|---|
| Motor de orquestación **topológico** (DAG real) | La firma ya lo expresa (CT-1); el scheduler lineal basta hasta forward | F5 |
| *Shape* interno de term-structure / `metric_sections` / `payload` | Requiere el SDD del dominio; fijarlo ahora es especulativo | SDD-16/17/20 |
| Capa de datos **longitudinal** | Requiere el SDD de IFRS 9/forward | F4/F5 |
| **Pickle/joblib** del `ArtifactStore** (frágil cross-version, vector RCE, no diffeable) | No bloquea F0/F1; duele con DataFrames grandes y tablas regulatorias | F3 (pre-CMF) |
| `mypy strict` sobre wrappers sin stubs (statsmodels/lifelines) → `cast()`/`ignore` localizados | Operativo, no estructural | F1/F5 |
| Presupuesto de CI (matriz 3×3 + Hypothesis `max_examples`) | Decisión operativa; vigilar que no estrangule el loop incremental | F1 |
| `register_on_success` reservado / `fail_fast=False` reservado | Config muerto v1; validar que no sea no-op silencioso | F0 (validación) / v2 |

---

## 6. Propagación a los SDD aprobados

El Hito 0 reabre tres SDD de Fundación (esperado y barato bajo el proceso incremental). Cabecera de cada uno: *"rev. Hito 0 (Contratos transversales) 2026-06-24"*.

| SDD | Edición |
|---|---|
| **01-core** | CT-1: `requires`/`provides` + `ArtifactKey` en `Step`/`StepAdapter` (§4) y validación pre-run en el motor (§7); CT-2: método `term_structure()` en `ProvisionResultLike` (§4 `results.py`); CT-4: `assemble_run` referenciado + nota de que `core` recibe el sink ya compuesto (§4/§2); nueva decisión **D-CORE-7** (§12). |
| **02-data** | CT-3: frontera transversal vs longitudinal explícita (§12) + nota de que el `LineageBundle` admite múltiples fuentes por nombre. |
| **03-audit-governance** | CT-2: `metric_sections` en `ModelCard`, `payload` en `OverlayRecord`/`ScenarioLog`; CT-4: `@runtime_checkable` en `ModelInventory` + owner del ensamblado (`assemble_run`). |

> SDD-24 (testing) y el ROADMAP recogen los **criterios de aceptación de F0** (§4) cuando se planifique el código de F0 — no se editan en este Hito (son de la sesión de plan de F0).

---

## 7. Citas

- **Evidencia:** revisión adversarial multi-agente del Hito 0 (4 lectores de madurez sobre SDD-01/02/03/24/25 + panel de 4 lentes: arquitecto, regulatorio, open-source/GTM, riesgo-de-proyecto). Convergencia unánime en `mixto-troncal-mas-incremental` tras refutación independiente.
- **SDD-01** §4 (Protocol `Step`, `StepAdapter`, `results.py`), §6 (claves de I/O `(domain,key)`), §7 (orquestación por orden de declaración), §12 (D-CORE-1 núcleo liviano, D-CORE-6 Protocols económicos).
- **SDD-02** modelo transversal (target binario, ventana única, particiones), D-DATA-2 (`data_hash` por contenido lógico).
- **SDD-03/04** `ModelCard`, `OverlayRecord`/`ScenarioLog`, `ModelInventory` (Protocol), `FanOutSink`, `MLflowInventory`/`NullInventory`, `MissingDependencyError`/`RegistryUnavailableError`.
- **ESPECIFICACIONES.md** §5.5 (ECL multi-período/lifetime), §5.6 (cadena forward macro→satellite→term-structure→ecl), §12 (R1 boil-the-ocean, R2 sobre-acoplamiento).
