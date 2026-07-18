# SDD-17 — `provisioning` (orquestación configurable de provisiones)

| Campo | Valor |
|---|---|
| **SDD** | 17 |
| **Módulo** | `nikodym.provisioning` |
| **Dominio** | Provisiones — comparación y regla de constitución |
| **Fase** | F3/F4 |
| **Tanda de producción** | T4 (Provisiones), corregido y ampliado con SDD-28 |
| **Estado** | ✅ Implementado; API experimental |
| **Depende de** | SDD-01 (`core`), SDD-05 (config) y dos fuentes entre SDD-15 CMF, SDD-28 interno y SDD-16 IFRS 9 |
| **Lo consumen** | SDD-22 (`validation`), SDD-23 (`ui`), SDD-26 (`report`) |
| **Actualización** | 2026-07-18 — consolidado contra el código vigente |

---

## 1. Regla normativa y alcance

La regla chilena está fijada por el **Capítulo B-1, hojas 10–11**, actualizado por la Circular
N.º 2.346 del 6 de marzo de 2024:

- la provisión se constituye considerando el mayor valor entre el **método estándar** y el
  **método interno**;
- la regla se aplica para cada institución en Chile que consolida con el banco;
- si el método interno fue evaluado y no objetado por la Comisión, se constituye según ese método.

Por tanto:

```text
caso general B-1       = max(método estándar CMF, método interno), por institución
interno no objetado    = método interno, aun si el estándar es mayor
```

El Capítulo A-2, número 5, excluye el deterioro NIIF 9 sobre colocaciones y créditos contingentes,
porque sus criterios se regulan en B-1 a B-3. En consecuencia, `max(CMF, IFRS 9)` **no** es el piso
prudencial chileno. Nikodym permite ese par por compatibilidad y para comparativos entre marcos,
pero lo etiqueta como no normativo.

## 2. Propósito y fronteras

`provisioning` es una capa fina que consume dos resultados ya calculados, aplica una regla
declarada y publica el comparativo auditable.

Responsabilidades:

- seleccionar `source_a` y `source_b` entre CMF estándar, método interno e IFRS 9;
- declarar prerequisitos CT-1 dinámicos según las fuentes y flags de consumo;
- exigir una única fecha de cierre;
- agregar o alinear montos al nivel configurado;
- aplicar crosswalks explícitos de cartera;
- reconciliar `Decimal` y `float` sin perder los valores originales;
- aplicar `rule="max"` o `rule="use_internal"`;
- identificar la fuente vinculante, empates y cobertura parcial;
- publicar comparación, resumen, resultado y card con copias defensivas;
- registrar regla, fuentes, nivel, reconciliación, binding y brechas.

Fronteras:

- no calcula PI/PDI/PE estándar, PD/LGD interna ni ECL;
- no decide matrices CMF, agrupación interna, LGD, staging, escenarios ni EIR;
- no inventa crosswalks ni identidad de operación;
- no mezcla fechas de cierre;
- no convierte una comparación informativa con IFRS 9 en exigencia regulatoria;
- no importa los motores dentro de `core` ni muta resultados de entrada.

## 3. Arquitectura

```text
provisioning_cmf ─────────┐
                         │
provisioning_internal ───┼──► provisioning ──► validation / report / ui
                         │      regla + evidencia
provisioning_ifrs9 ──────┘
```

La config elige exactamente dos fuentes distintas. Para el binding B-1:

```yaml
provisioning:
  source_a: provisioning_cmf
  source_b: provisioning_internal
  rule: max
  comparison_level: total
  require_both: true
```

`ProvisioningStep` está registrado como `@register("standard", domain="provisioning")`. Sus
`requires` apuntan a `(source, "result")` y sus `provides` son:

```python
(
    ("provisioning", "comparison"),
    ("provisioning", "summary"),
    ("provisioning", "result"),
    ("provisioning", "card"),
)
```

El step y los DTOs no cargan pandas al importar el paquete; el orquestador lo carga dentro de
`compare`. `execute` descarta `rng` porque toda la operación es determinística.

## 4. API pública

`nikodym.provisioning` exporta:

- config y tipos: `ProvisioningConfig`, `ProvisioningSource`, `ProvisioningRule`,
  `ProvisioningComparisonLevel`, `ProvisioningCoveragePolicy`,
  `ProvisioningNumericReconciliation`, `ProvisioningRoundingPolicy`;
- ejecución: `ProvisioningStep`, `ProvisioningOrchestrator`, `PROVISIONING_ARTIFACTS`;
- DTOs: `ProvisionComparisonRecord`, `ProvisionComparisonSummary`,
  `ProvisionOrchestrationCard`, `ProvisionOrchestrationResult`;
- errores: `ProvisioningError`, `ProvisioningConfigError`, `ProvisioningInputError`,
  `ProvisioningAlignmentError`, `ProvisioningCoverageError`.

Fuentes admitidas:

| Config | Nombre corto en resultados | Dominio numérico |
|---|---|---|
| `provisioning_cmf` | `cmf` | `Decimal` |
| `provisioning_internal` | `internal` | `Decimal` |
| `provisioning_ifrs9` | `ifrs9` | `float` |

## 5. Configuración

`ProvisioningConfig` es frozen, rechaza campos extra, usa schema local `1.0.0` y es
**computacional**: cualquier cambio relevante mueve el `config_hash`.

Campos principales:

```python
class ProvisioningConfig(NikodymBaseConfig):
    source_a: Literal[
        "provisioning_cmf", "provisioning_internal", "provisioning_ifrs9"
    ] = "provisioning_cmf"
    source_b: Literal[
        "provisioning_cmf", "provisioning_internal", "provisioning_ifrs9"
    ] = "provisioning_ifrs9"  # compatibilidad; no binding B-1
    rule: Literal["max", "use_internal"] = "max"
    comparison_level: Literal["total", "portfolio", "segment", "operation"] = "total"
    portfolio_crosswalk: dict[str, str] = {}
    consume_a: bool = True
    consume_b: bool = True
    require_both: bool = True
    coverage_policy: Literal["use_available", "fail", "treat_missing_as_zero"] = "use_available"
    numeric_reconciliation: Literal["decimal_quantize", "float_isclose"] = "decimal_quantize"
    tie_tolerance: float = 1e-9
    rounding: Literal["none", "currency_2dp", "integer_currency"] = "none"
    fail_on_falta_dato: bool = True
```

Además declara la fecha, columnas de cartera por fuente, columna de segmento e identificador de
operación. `consume_cmf` y `consume_ifrs9` se conservan sólo como aliases deprecados; código nuevo
usa `consume_a`/`consume_b`.

Validaciones de config:

- `source_a != source_b`;
- `use_internal` exige que una fuente sea `provisioning_internal`;
- `require_both=True` exige ambas fuentes habilitadas;
- `segment` exige `segment_col`;
- niveles por cartera/segmento con taxonomías distintas exigen crosswalk;
- nombres de columnas y claves de crosswalk no pueden estar vacíos;
- tolerancia y políticas usan vocabularios cerrados.

El default CMF↔IFRS 9 existe por retrocompatibilidad. Los presets regulatorios y todo ejemplo B-1
deben sobrescribirlo con CMF↔interno. Cambiar ese default es una decisión de compatibilidad futura,
no una reinterpretación normativa.

## 6. Nivel de comparación

`comparison_level="total"` agrega toda la corrida. Sólo representa el nivel “por institución” del
B-1 bajo el precontrato de **una institución por corrida**; Nikodym no valida hoy esa frontera. Los
demás niveles son diagnósticos:

- `portfolio`: agrega por cartera después de aplicar un crosswalk explícito, si corresponde;
- `segment`: usa una columna común declarada;
- `operation`: exige los mismos identificadores en ambas fuentes;
- `total`: suma cada fuente y aplica la regla una sola vez.

La diferencia es material:

```text
Σ max(A_c, B_c) >= max(Σ A_c, Σ B_c)
```

Por eso un máximo por cartera, segmento u operación no debe presentarse como la provisión B-1 de
la institución. Sirve para explicar dónde una fuente supera a la otra.

## 7. Reconciliación y cobertura

### Reconciliación numérica

- `decimal_quantize`: convierte la comparación al dominio `Decimal` y preserva exactitud de los
  motores regulatorios;
- `float_isclose`: compara en dominio económico `float` y vuelve a `Decimal` para el monto
  publicado;
- `tie_tolerance` define empates sobre la diferencia económica;
- `rounding` se aplica sólo después de elegir el monto reportado;
- `provision_a` y `provision_b` conservan el tipo original de la fuente.

### Cobertura parcial

- `require_both=True`: falta una fuente y la ejecución falla;
- `use_available`: publica el monto disponible marcado `<source>_only`;
- `fail`: una celda no cubierta por ambas fuentes falla;
- `treat_missing_as_zero`: imputa cero de forma explícita y deja warning;
- `fail_on_falta_dato=True`: convierte brechas críticas de alineación en error.

Un passthrough de una sola fuente es una **comparación incompleta**, no una provisión obtenida por
una regla entre dos métodos.

## 8. Algoritmo

```text
1. Resolver config efectivo y requires dinámicos.
2. Cargar los dos result opacos habilitados.
3. Exigir al menos una fuente y una única as_of_date.
4. Extraer montos por total/cartera/segmento/operación.
5. Aplicar crosswalk y validar alineación.
6. Construir la unión ordenada de celdas.
7. Resolver cobertura por celda.
8. Aplicar use_internal o max con tolerancia y redondeo.
9. Agregar conteos y totales.
10. Construir card, DataFrames y term-structure delegada si participa IFRS 9.
11. Auditar y publicar cuatro artefactos con copias defensivas.
```

`rule="use_internal"` selecciona el monto interno aunque el otro sea mayor. Sólo representa B-1 si
el par es CMF/interno, el nivel es `total`, la corrida contiene una institución y ésta acredita que
el método fue evaluado y no objetado; Nikodym no verifica esa condición. `rule="max"` sólo se cita
como binding B-1 bajo el mismo par/nivel/perímetro.

## 9. Contratos de resultados

### `ProvisionComparisonRecord`

Una fila lógica por celda:

- `cell_id`, `level`, `source_a`, `source_b`;
- `provision_a`, `provision_b`, `reported_provision`;
- `binding`: `cmf`, `internal`, `ifrs9`, `tie` o `<source>_only`;
- `coverage`: `both` o `<source>_only`;
- `warnings`.

### `ProvisionComparisonSummary`

Publica número de celdas, conteos por binding, totales por fuente, total reportado y warnings.

### `ProvisionOrchestrationCard`

Publica fecha, nivel, regla, fuentes, motores presentes, binding agregado cuando hay una celda,
versiones/metodologías heredadas, fuentes regulatorias, `falta_dato` y `metric_sections` CT-2.
La métrica neutral vigente es `source_a_binding_ratio`; `floor_bite_ratio` se conserva como alias
legacy con el mismo valor para respetar la evolución aditiva. Del mismo modo,
`comparacion_incompleta` se publica junto a `piso_incompleto` en resultados legacy hasta una
migración versionada. Los consumidores nuevos deben usar los nombres neutrales.

### `ProvisionOrchestrationResult`

Contiene:

- `comparison`: DataFrame canónico con una fila por celda;
- `summary`: DataFrame agregado;
- `records`: DTO paralelo a `comparison`;
- `card`;
- `ifrs9_term_structure`, sólo si IFRS 9 participa.

`term_structure()` devuelve una copia de la curva IFRS 9 delegada o `None`. No fabrica una curva
para CMF, método interno ni para el máximo reportado.

Todos los DTOs son frozen y rechazan campos extra. Los DataFrames y payloads mutables se copian al
validar y al acceder.

## 10. Errores, auditoría y seguridad

Errores:

- `ProvisioningConfigError`: combinación declarativa inválida;
- `ProvisioningInputError`: fuente ausente, fecha incompatible o resultado malformado;
- `ProvisioningAlignmentError`: claves o perímetros no reconciliables;
- `ProvisioningCoverageError`: brecha prohibida por política.

Decisiones auditadas:

- fuentes y regla;
- nivel y claves de comparación;
- reconciliación, tolerancia y redondeo;
- conteos por binding;
- cobertura e imputación;
- brechas `FALTA-DATO`;
- fuentes regulatorias heredadas.

El token histórico de acción `aplicar_regla_de_constitucion` se conserva por compatibilidad del
trail; su payload declara fuentes, nivel y regla y no convierte un comparativo diagnóstico en norma.

El orquestador no acepta expresiones ejecutables ni SQL, no lee secretos, no escribe fuera del
ArtifactStore y no altera los resultados fuente.

## 11. Verificación y Definition of Done

La batería dedicada cubre config, DTOs, orquestador, step y el método interno integrado.

Criterios permanentes:

- goldens a mano para gana A, gana B, empate y `use_internal`;
- CMF↔interno a nivel total con cita B-1 correcta;
- CMF↔IFRS 9 etiquetado como comparativo entre marcos;
- `Σ max >= max Σ` verificado para niveles diagnósticos;
- crosswalk, desalineación de operación y columnas faltantes;
- las tres políticas de cobertura;
- exactitud Decimal, floats no finitos, tolerancia y redondeo;
- fechas de cierre iguales;
- `requires` dinámicos y publicación de cuatro artefactos;
- copias defensivas y no mutación;
- determinismo entre ejecuciones e import liviano;
- ruff, mypy `--strict` y cobertura regulatoria 100 %.

## 12. Decisiones fijadas

- **D-PROV-1:** fuentes configurables, nunca operandos cableados.
- **D-PROV-2:** `total` representa B-1 sólo con una institución por corrida; niveles finos son
  diagnósticos.
- **D-PROV-3:** crosswalk explícito; no hay inferencia semántica.
- **D-PROV-4:** originales preservados; reconciliación numérica declarada.
- **D-PROV-5:** cobertura parcial siempre visible y gobernada por política.
- **D-PROV-6:** CMF↔IFRS 9 es comparativo entre marcos, no piso CMF.
- **D-PROV-7:** `use_internal` modela esa política, pero Nikodym no acredita evaluación/no objeción.
- **D-PROV-8:** la orquestación permanece experimental y fuera de la garantía SemVer F1.

## 13. Fuentes vigentes

- Compendio de Normas Contables para Bancos, capítulos A-2 y B-1; parámetros trazados en la
  documentación normativa del proyecto.
- `src/nikodym/provisioning/`: contrato ejecutable.
- `tests/unit/test_provisioning_*.py` y tests del método interno: comportamiento verificable.
- SDD-15, SDD-16 y SDD-28: contratos de las tres fuentes.
- `docs/ESPECIFICACIONES.md` §5.4: separación de motores y corrección normativa.

No quedan decisiones abiertas en este SDD. La validación humana de matrices CMF y haircuts sigue
siendo un gate separado del SDD-15 y no se resuelve por tener este orquestador implementado.
