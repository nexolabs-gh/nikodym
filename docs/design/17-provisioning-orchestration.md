# SDD-17 — `provisioning` (orquestación CMF↔IFRS 9 / piso prudencial · máximo regulatorio)

| Campo | Valor |
|---|---|
| **SDD** | 17 |
| **Módulo** | `nikodym.provisioning` |
| **Dominio** | Provisiones |
| **Fase** | F4 |
| **Tanda de producción** | T4 (Provisiones) |
| **Estado** | 🟡 Borrador |
| **Depende de** | SDD-01 (`core`), SDD-05 (convenciones + config), SDD-15 (`provisioning/cmf`), SDD-16 (`provisioning/ifrs9`) |
| **Lo consumen** | SDD-22 (`validation`), SDD-23 (`ui`), SDD-26 (`report`) |
| **Autor / Fecha** | DanIA (redacción SDD-17 para T4/F4, cierre del track de Provisiones) / 2026-07-03 |

---

## 1. Propósito y responsabilidad

**Qué resuelve (una frase).** `provisioning` es la **capa fina de orquestación** que consume el resultado del motor regulatorio CMF (SDD-15) y del motor contable IFRS 9/ECL (SDD-16), aplica la **provisión reportada = máximo(ECL IFRS 9, piso prudencial CMF)** al nivel de agregación configurado, y publica el **comparativo auditable** (CMF vs IFRS 9 vs reportado, con el motor que "muerde" el piso) como result/summary/card + tidy para report, validation y ui.

**Responsabilidad única (qué SÍ hace).**
- Lee los artefactos `("provisioning_cmf", "result")` y `("provisioning_ifrs9", "result")` por el contrato CT-1 (sus `provides` estables), nunca recalcula PI/PDI/PE, ECL, staging ni term-structure.
- Alinea ambos resultados al **nivel de comparación** declarado (`total` / `portfolio` / `segment` / `operation`, D-PROV-2 R0), reconciliando la taxonomía de cartera CMF (`cmf_portfolio`) con la de IFRS 9 (`portfolio`) por la clave o crosswalk configurado.
- Reconcilia la representación numérica **`Decimal` (CMF)** con **`float` (IFRS 9)** en un dominio común y con tolerancia documentada, preservando el monto original de cada motor en el detalle auditado (nunca pierde precisión regulatoria silenciosamente).
- Computa por cada celda de comparación `provision_reported = max(cmf_provision, ifrs9_ecl_reported)` (regla dura ESPEC §5.4; **no** es decisión abierta), e identifica el **motor vinculante** (`binding = "cmf" | "ifrs9" | "tie"`).
- Publica artefactos namespaced bajo `"provisioning"`: comparativo por celda, resumen agregado, resultado contenedor y card de gobierno; expone `term_structure()` (CT-2) delegando en la curva ECL de IFRS 9 cuando existe.
- Aporta el sub-config **`ProvisioningConfig`** (sección `provisioning` de `NikodymConfig`), computacional y por tanto incluido en el `config_hash`.
- Maneja la **cobertura parcial** (una cartera/operación presente en un motor y no en el otro, o solo un motor configurado en la corrida) según la política declarada, con trazabilidad de cada brecha.
- Registra con `log_decision` el nivel de comparación, la clave/crosswalk de cartera, la política de reconciliación numérica, el conteo de celdas donde muerde CMF vs IFRS 9, las brechas de cobertura y cualquier `FALTA-DATO`.

**Frontera dura de responsabilidad (qué NO hace, y quién lo hace).**
- **No calcula provisión CMF.** SDD-15 produce `CmfProvisionResult`; SDD-17 solo lo consume. No toca matrices B-1/B-3, garantías ni la regla C1-C6.
- **No calcula ECL, staging, PD/LGD/EAD ni term-structure.** SDD-16 produce `IfrsProvisionResult`; SDD-17 solo lo consume.
- **No decide la política de la entidad** (umbrales SICR, `rho`, pesos de escenario, matrices activas): esos parámetros viven en SDD-15/16 y en la config de la institución.
- **No define la definición regulatoria de default ni el panel longitudinal:** se hereda de las capas de datos y de los motores (CT-3).
- **No inventa el mapeo entre carteras CMF y grupos IFRS 9.** Si las taxonomías no comparten clave y no hay crosswalk configurado, marca `FALTA-DATO` o falla según config; no adivina equivalencias por similitud semántica.
- **No modifica** los resultados de entrada: lee copias defensivas y publica resultados propios.
- **No arrastra `provisioning` al núcleo.** `import nikodym.core` no importa `nikodym.provisioning`; pandas pesado se usa perezosamente dentro de `execute`/`compare`.

## 2. Contexto y ubicación en la arquitectura

- **Capa:** cierre del track de Provisiones (F4/T4). Corre **después** de `provisioning_cmf` (SDD-15) y `provisioning_ifrs9` (SDD-16); es la capa fina de ensamblado (owner del comparativo, análoga en espíritu a `assemble_run` de CT-4 pero para el piso prudencial). Su salida alimenta `validation` (SDD-22), `report` (SDD-26) y `ui` (SDD-23).
- **Quién lo invoca:** `Study.run()` como sección `provisioning` de `NikodymConfig`, o API programática para comparar dos resultados ya calculados.
- **A quién invoca:** `core` (`Step`, `ArtifactKey`, `ArtifactStore`, `AuditableMixin`, excepciones, lineage, patrón CT-2 `term_structure()`), y los artefactos `result`/`summary`/`card` de `provisioning_cmf` y `provisioning_ifrs9`. **No importa** los paquetes `cmf`/`ifrs9` como código: el acoplamiento es solo por los DTOs publicados (nombres de clase se referencian, no se re-implementan).

```text
data ─► ... ─► (calibration / survival / forward) ─┐
                                                    │
       provisioning_cmf (SDD-15) ── result ─────────┤
                                                    ├─► provisioning (SDD-17) ─► report / validation / ui
       provisioning_ifrs9 (SDD-16) ─ result ────────┘        máximo(ECL, piso CMF) + comparativo
```

**Interacción con `Study` y config declarativo.** `ProvisioningStep` es un `Step` nativo registrado con `@register("standard", domain="provisioning")`. Como qué motores están presentes depende de la corrida, sus `requires` (CT-1) se construyen en `from_config`: condicionalmente `("provisioning_cmf", "result")` y/o `("provisioning_ifrs9", "result")` según qué secciones estén configuradas y la política `require_both`. Luego resuelve la config, alinea ambos resultados al nivel de comparación, aplica el máximo y escribe sus artefactos bajo `"provisioning"`. El `rng` se recibe por contrato homogéneo de `Step`; el orquestador v1 es determinista y debe hacer `del rng`.

**Cableado futuro en `core.study`.** Al implementar SDD-17 (bloque B17.1):
- `_DOMAIN_MODULES["provisioning"] = "nikodym.provisioning"`;
- `_DOMAIN_CONFIG_CLASSES["provisioning"] = ("nikodym.provisioning.config", "ProvisioningConfig")`;
- `_DEFAULT_DOMAIN_ORDER` ubica `"provisioning"` **después** de `"provisioning_ifrs9"` y `"provisioning_cmf"` (hoy los dos últimos del orden). El orden lineal no reemplaza CT-1: los prerequisitos reales se expresan por `requires`/`provides`; el scheduler topológico sigue diferido a F5.

**Paquete físico troceable.** El paquete padre `src/nikodym/provisioning/` (hoy solo `__init__.py` + sub-paquetes `cmf/`, `ifrs9/`) recibe los módulos de orquestación:

```text
src/nikodym/provisioning/
  __init__.py            # ya existe; se amplía para poblar el hook y registrar el Step de orquestación
  config.py              # ProvisioningConfig (sección `provisioning`)
  exceptions.py          # ProvisioningError + subclases
  results.py             # DTOs: ProvisionComparisonRecord, ProvisionComparisonSummary, card, result
  orchestrator.py        # ProvisioningOrchestrator: alineación + máximo + comparativo (determinista)
  step.py                # ProvisioningStep + @register + cableado core.study
  cmf/                   # SDD-15 (no se toca)
  ifrs9/                 # SDD-16 (no se toca)
```

**Troceo implementable un módulo/commit.**
- **B17.1 — config/exceptions + hook:** `config.py`, `exceptions.py`, hook diferido `_PROVISIONING_CONFIG_CLS` en `core.config.schema`, campo `provisioning` en `NikodymConfig`, round-trip YAML. **Mueve `GOLDEN_DEFAULT_CONFIG_HASH`** (§5/§11).
- **B17.2 — results:** DTOs Pydantic frozen (`ProvisionComparisonRecord`, `ProvisionComparisonSummary`, `ProvisionOrchestrationCard`, `ProvisionOrchestrationResult`), `term_structure()` CT-2, copias defensivas, reconciliación `Decimal`/`float`.
- **B17.3 — orchestrator:** `ProvisioningOrchestrator` determinista con goldens del máximo (gana CMF / gana IFRS 9 / empate) y reconciliación de niveles/claves.
- **B17.4 — step:** `ProvisioningStep`, `@register`, `requires` dinámicos / `provides` estables, cableado `core.study` e integración end-to-end sobre resultados de ambos motores.

Cada bloque cierra con ruff (regla `D` docstrings en español), mypy `--strict`, tests 100% del módulo tocado y **cobertura regulatoria 100%** para `nikodym.provisioning` (piso prudencial → declarado regulatorio, mismo criterio que `cmf`/`ifrs9` en `_CONTRATOS-TRANSVERSALES.md` §4).

## 3. Conceptos y fundamentos

**Fuente normativa (regla del máximo — decidida, no abierta).** ESPECIFICACIONES §5.4 (línea 131) fija la **decisión de diseño dura**:

> «🔴 **CMF ≠ IFRS 9.** Son **dos motores separados**. La provisión final aplica el **máximo** entre el ECL contable (IFRS 9) y el **piso prudencial CMF**. El módulo `provisioning/` orquesta ambos y expone el comparativo.»

ESPEC §6.3 (árbol, línea ~195) lo confirma: `provisioning/ # orquesta CMF vs IFRS 9 → máximo (piso regulatorio)`. `ROADMAP.md` F4 fija el DoD «ECL + piso CMF» y la tarea explícita «Orquestación: `provisioning` compara CMF vs IFRS 9 y aplica el máximo». La regla del máximo es **norma citada**, no una decisión de producto de este SDD; lo que SÍ queda abierto es el **nivel de agregación** al que se aplica (§12, D-PROV-2).

**Definición del piso prudencial.** Para cada celda de comparación `c` (definida por el nivel de agregación):

```text
cmf_provision(c)     = provisión regulatoria CMF B-1/B-3 agregada a la celda c   (SDD-15)
ifrs9_ecl(c)         = ECL contable reportado agregado a la celda c              (SDD-16, ya Σ_k w_k)
provision_reported(c) = max( cmf_provision(c), ifrs9_ecl(c) )
binding(c)           = "cmf"  si cmf_provision(c) > ifrs9_ecl(c)
                       "ifrs9" si ifrs9_ecl(c) > cmf_provision(c)
                       "tie"   si |cmf_provision(c) − ifrs9_ecl(c)| ≤ tol
```

El CMF actúa como **piso** (floor): cuando el ECL contable cae por debajo de la provisión regulatoria, se reporta la provisión CMF. Ambos insumos son no negativos (garantizado por los DTOs de SDD-15/16), luego `provision_reported ≥ 0` y `provision_reported ≥ max(0, ·)` trivialmente.

**Reconciliación numérica `Decimal` vs `float`.** SDD-15 publica montos en `Decimal` (cálculo regulatorio exacto); SDD-16 en `float` (ECL económico). El máximo exige un dominio común. Convención (D-PROV-4): se comparan y se reporta en `Decimal` cuantizando el `float` de IFRS 9 a una escala documentada (o, alternativa, ambos a `float` con `math.isclose`); el detalle conserva `cmf_provision` (Decimal original) e `ifrs9_ecl` (float original) sin recuantizar, y `provision_reported` en el tipo del motor vinculante. La tolerancia `tol` de empate se declara en config. **No se redondea la provisión reportada por default** (`rounding="none"`): el redondeo contable es decisión explícita, heredando el criterio D-CMF-5 / D-IFRS (rounding).

**Nivel de agregación (grano de la comparación).** Los dos motores agregan a granos distintos (§6): CMF `summary` por `portfolio · method · cmf_category`; IFRS 9 `summary` por `portfolio · stage · scenario`. El máximo debe aplicarse a un grano común. Opciones (D-PROV-2, R0):
- **`total`**: un solo máximo entidad-total; robusto, mínimo acoplamiento de claves, pero pierde el detalle de dónde muerde cada norma.
- **`portfolio`**: máximo por cartera; requiere que ambas taxonomías compartan clave `portfolio` o un crosswalk.
- **`segment`**: máximo por una clave de segmento provista por el usuario presente en ambos detalles.
- **`operation`**: máximo por operación (`row_id`); el más granular y prudente, pero exige identidad de fila alineable entre ambos motores (ver §6, caveat de índice).

**Sutileza de doble conteo en el `summary` IFRS 9.** El `summary` de SDD-16 desglosa por `scenario`, pero `ecl_reported` **por fila** ya es `Σ_k w_k · ECL_k` (colapsado por escenario). Sumar `total_ecl_reported` a través de la columna `scenario` del `summary` **duplicaría** la masa. Por eso SDD-17 agrega el ECL IFRS 9 a la celda de comparación desde el **`detail`/`ecl_records`** (por operación, ya colapsado por escenario), no desde el `summary` desglosado por escenario. Para el nivel `total` puede usar `card.total_ecl_reported` (que es el total colapsado). Este es un requisito de correctitud, no una opción.

## 4. API pública (contrato)

> Firmas ilustrativas, no implementación. Identificadores en inglés técnico; docstrings y mensajes en español.

```python
# nikodym/provisioning/config.py
class ProvisioningConfig(NikodymBaseConfig): ...

# nikodym/provisioning/exceptions.py
class ProvisioningError(NikodymError): ...
class ProvisioningConfigError(ProvisioningError): ...
class ProvisioningInputError(ProvisioningError): ...        # resultado de entrada malformado
class ProvisioningAlignmentError(ProvisioningInputError): ...  # claves/niveles no reconciliables
class ProvisioningCoverageError(ProvisioningError): ...     # brecha de cobertura bajo política estricta
```

```python
# nikodym/provisioning/results.py
class ProvisionComparisonRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    cell_id: str                                  # identificador de la celda (total/portfolio/segment/row_id)
    level: Literal["total", "portfolio", "segment", "operation"]
    cmf_provision: Decimal | None                 # None si la celda no está cubierta por CMF
    ifrs9_ecl: float | None                       # None si la celda no está cubierta por IFRS 9
    reported_provision: Decimal                    # máximo (o el disponible según política)
    binding: Literal["cmf", "ifrs9", "tie", "cmf_only", "ifrs9_only"]
    coverage: Literal["both", "cmf_only", "ifrs9_only"]
    warnings: tuple[str, ...] = ()

class ProvisionComparisonSummary(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    level: Literal["total", "portfolio", "segment", "operation"]
    n_cells: int
    n_binding_cmf: int
    n_binding_ifrs9: int
    n_binding_tie: int
    total_cmf_provision: Decimal
    total_ifrs9_ecl: Decimal                       # ECL total reconciliado a Decimal para el agregado
    total_reported_provision: Decimal
    warnings: tuple[str, ...] = ()

class ProvisionOrchestrationCard(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    as_of_date: str
    comparison_level: str
    engines_present: tuple[str, ...]               # p.ej. ("cmf", "ifrs9")
    n_cells: int
    n_binding_cmf: int
    n_binding_ifrs9: int
    n_binding_tie: int
    total_cmf_provision: Decimal
    total_ifrs9_ecl: Decimal
    total_reported_provision: Decimal
    cmf_matrix_version: str | None                 # trazabilidad heredada de la card CMF
    ifrs9_term_structure_source: str | None        # trazabilidad heredada de la card IFRS 9
    regulatory_sources: tuple[str, ...]
    falta_dato: tuple[str, ...] = ()
    metric_sections: dict[str, Any] = Field(default_factory=dict)   # CT-2

class ProvisionOrchestrationResult(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True, extra="forbid")
    comparison: "pandas.DataFrame"                 # una fila por celda de comparación
    summary: "pandas.DataFrame"                     # agregado por nivel
    records: tuple[ProvisionComparisonRecord, ...]
    card: ProvisionOrchestrationCard
    def term_structure(self) -> "pandas.DataFrame | None": ...
```

`term_structure()` cumple CT-2: **delega** en la curva ECL de IFRS 9 (`IfrsProvisionResult.term_structure()`, no nula) cuando IFRS 9 está presente, para que report/ui muestren el desglose por escenario/período del componente contable; retorna `None` cuando solo hay CMF (que no publica term-structure, D-CORE-7). La orquestación **no** fabrica una term-structure del máximo (el máximo es escalar por celda; no tiene curva propia).

```python
# nikodym/provisioning/orchestrator.py
class ProvisioningOrchestrator:
    config_cls: ClassVar[type[ProvisioningConfig]] = ProvisioningConfig
    def __init__(self, config: ProvisioningConfig) -> None: ...
    @classmethod
    def from_config(cls, cfg: ProvisioningConfig) -> "ProvisioningOrchestrator": ...
    def compare(
        self,
        *,
        cmf: "CmfProvisionResult | None",
        ifrs9: "IfrsProvisionResult | None",
        as_of_date: str,
        audit: "AuditSink | None" = None,
    ) -> ProvisionOrchestrationResult: ...
```

```python
# nikodym/provisioning/step.py
@register("standard", domain="provisioning")
class ProvisioningStep(AuditableMixin):
    name: str = "provisioning"
    requires: tuple[ArtifactKey, ...] = ()   # las claves se agregan en from_config según motores presentes
    provides: tuple[ArtifactKey, ...] = (
        ("provisioning", "comparison"),
        ("provisioning", "summary"),
        ("provisioning", "result"),
        ("provisioning", "card"),
    )
    @classmethod
    def from_config(cls, cfg: ProvisioningConfig) -> "ProvisioningStep": ...
    def execute(self, study: "Study", rng: "numpy.random.Generator") -> "ProvisionOrchestrationResult": ...
```

**`requires` dinámicos (CT-1, patrón SDD-16 §4 / SDD-20 §81).** `from_config` construye `requires` según config:
- `("provisioning_cmf", "result")` si `cfg.consume_cmf` (default: presente si la sección `provisioning_cmf` está en el config);
- `("provisioning_ifrs9", "result")` si `cfg.consume_ifrs9` (default: presente si la sección `provisioning_ifrs9` está en el config);
- con `require_both=True`, exige ambos; con `require_both=False`, exige al menos uno y degrada a passthrough del disponible.

La validación pre-run del motor v1 exige que cada `requires` esté en el `ArtifactStore`; su ausencia es `ArtifactNotFoundError` antes de correr.

**Artefactos que `ProvisioningStep.execute` escribe en `study.artifacts`.**

| clave | tipo | contenido |
|---|---|---|
| `"comparison"` | `pandas.DataFrame` | una fila por celda: `cmf_provision`, `ifrs9_ecl`, `reported_provision`, `binding`, `coverage` |
| `"summary"` | `pandas.DataFrame` | agregado por nivel: totales CMF/IFRS 9/reportado y conteo de celdas por motor vinculante |
| `"result"` | `ProvisionOrchestrationResult` | contenedor agregado |
| `"card"` | `ProvisionOrchestrationCard` | resumen para governance/report/validation/ui |

**Ejemplo de uso (pseudocódigo).**

```python
study.run(steps=[..., "provisioning_cmf", "provisioning_ifrs9", "provisioning"])
piso = study.artifacts.get("provisioning", "result")
comparativo = study.artifacts.get("provisioning", "comparison")   # CMF vs IFRS 9 vs reportado
curva_ecl = piso.term_structure()                                 # desglose ECL IFRS 9 (o None si solo CMF)
```

## 5. Configuración (schema Pydantic)

`ProvisioningConfig` es el sub-config de la sección `provisioning` de `NikodymConfig`. Sigue SDD-05: `NikodymBaseConfig`, `extra="forbid"`, `frozen=True`, campos con `title`/`description`, rangos `ge/le`, `Literal` en categóricos y metadatos `ui_*`. **No es infraestructura** (`provisioning ∉ INFRA_SECTIONS`; verificado contra `core/config/hashing.py`: `INFRA_SECTIONS = {"name","governance","audit","tracking","report"}`): cambiar el nivel de comparación, la clave de cartera/crosswalk, la política de cobertura o la reconciliación numérica **cambia el `config_hash`**. Al cablear B17.1 se **moverá `GOLDEN_DEFAULT_CONFIG_HASH`** (mismo precedente que `provisioning_cmf`, `provisioning_ifrs9`, `survival` y `markov`); el implementador debe barrer el literal en tests y repros, **no** tratarlo como regresión inesperada.

```python
class ProvisioningConfig(NikodymBaseConfig):
    schema_version: str = "1.0.0"
    type: Literal["standard"] = "standard"
    as_of_date_col: str = Field("as_of_date", title="Fecha de cálculo (heredada de los motores)")

    comparison_level: Literal["total", "portfolio", "segment", "operation"] = Field(
        "total", title="Nivel de agregación del máximo CMF vs IFRS 9")          # D-PROV-2 (R0)
    cmf_portfolio_col: str = Field("portfolio", title="Columna de cartera en el detail/summary CMF")
    ifrs9_portfolio_col: str = Field("portfolio", title="Columna de cartera en el detail/summary IFRS 9")
    portfolio_crosswalk: dict[str, str] = Field(
        default_factory=dict, title="Mapeo cartera CMF → cartera IFRS 9 (si difieren)")   # D-PROV-3 (R0)
    segment_col: str | None = Field(default=None, title="Columna de segmento (comparison_level='segment')")
    row_id_col: str = Field("row_id", title="Identificador de operación (comparison_level='operation')")

    consume_cmf: bool = Field(default=True, title="Consumir el resultado CMF si está presente")
    consume_ifrs9: bool = Field(default=True, title="Consumir el resultado IFRS 9 si está presente")
    require_both: bool = Field(default=True, title="Exigir ambos motores (si no, passthrough del disponible)")
    coverage_policy: Literal["use_available", "fail", "treat_missing_as_zero"] = Field(
        "use_available", title="Política ante celda cubierta por un solo motor")     # D-PROV-5

    numeric_reconciliation: Literal["decimal_quantize", "float_isclose"] = Field(
        "decimal_quantize", title="Cómo reconciliar Decimal (CMF) y float (IFRS 9)")
    tie_tolerance: float = Field(default=1e-9, ge=0.0, title="Tolerancia absoluta de empate")
    rounding: Literal["none", "currency_2dp", "integer_currency"] = Field(
        "none", title="Redondeo de la provisión reportada")

    fail_on_falta_dato: bool = Field(default=True, title="Fallar ante brechas críticas de dato")
```

**Validaciones de config.**
- `comparison_level="segment"` exige `segment_col` no nulo y presente en el detalle de ambos motores; su ausencia es `ProvisioningConfigError`.
- `comparison_level="operation"` exige que el `row_id` (o el índice) sea alineable entre ambos detalles; si no lo es, `ProvisioningAlignmentError` (ver §6, caveat).
- `comparison_level ∈ {"portfolio","segment"}` con taxonomías distintas exige `portfolio_crosswalk` o falla/`FALTA-DATO` según `fail_on_falta_dato`.
- `require_both=True` con solo un motor configurado en la corrida es `ProvisioningConfigError` (contradicción declarativa) — o `ArtifactNotFoundError` en runtime por CT-1.
- `consume_cmf=False` y `consume_ifrs9=False` simultáneos es `ProvisioningConfigError` (no hay nada que orquestar).
- `tie_tolerance` debe ser `≥ 0`.

**Defaults defendibles (con fuente).**
- `comparison_level="total"`: default **conservador y sin supuestos de taxonomía** — un máximo entidad-total no exige reconciliar claves de cartera ni identidad de fila; es el mínimo común denominador correcto. El grano fino (`portfolio`/`operation`) es más informativo pero exige decisiones de la entidad (D-PROV-2, R0).
- `require_both=True`: el piso prudencial ESPEC §5.4 presupone **ambos** motores; correr solo uno es un caso de diagnóstico/parcial, no la operación normal. Configurable a `False` para pipelines que aún no tienen los dos.
- `coverage_policy="use_available"`: ante una celda cubierta por un solo motor, reportar el monto disponible marcado (`cmf_only`/`ifrs9_only`) es más seguro que asumir `0` en el faltante (que subestimaría la provisión). `treat_missing_as_zero` está disponible por si la entidad define explícitamente que la ausencia equivale a exposición nula.
- `numeric_reconciliation="decimal_quantize"`: preserva la exactitud regulatoria del CMF como dominio de reporte; `float_isclose` como alternativa cuando se prefiere el dominio económico.
- `rounding="none"`: publica el piso económico exacto; el redondeo contable queda como decisión explícita (heredado de D-CMF-5).

**Hook diferido en `core.config.schema`.** Al implementar (B17.1):
- declarar `_PROVISIONING_CONFIG_CLS: type[BaseModel] | None = None`;
- añadir campo `provisioning` como `Any` en runtime y `ProvisioningConfig | None` bajo `TYPE_CHECKING` (espejo de `provisioning_cmf`/`provisioning_ifrs9` ya presentes);
- añadir `@field_validator("provisioning", mode="before")` (`_valida_provisioning`) que valida con `ProvisioningConfig` si el hook está poblado, o exige JSON canónico determinista si no;
- `nikodym.provisioning.__init__` puebla el hook y registra `ProvisioningStep`;
- `provisioning` **no** entra a `INFRA_SECTIONS`.

## 6. Contratos de datos (I/O)

**Inputs de `ProvisioningStep` vía `Study`.**

| dominio | clave | obligatoriedad | uso |
|---|---|---|---|
| `provisioning_cmf` | `"result"` | dura dinámica (`consume_cmf` / `require_both`) | `CmfProvisionResult`: `detail`, `summary`, `records`, `card` (montos `Decimal`) |
| `provisioning_ifrs9` | `"result"` | dura dinámica (`consume_ifrs9` / `require_both`) | `IfrsProvisionResult`: `detail`, `ecl_records`, `summary`, `card` (montos `float`) |

**Contrato consumido del resultado CMF (SDD-15 §4/§6, verificado en `results.py`).** `CmfProvisionResult.detail` con columnas `portfolio, method, cmf_category, matrix_id, matrix_row_id, direct_exposure_amount, contingent_exposure_amount, exposure_amount, pd_source_value, pi_percent, pdi_percent, pe_percent, provision_amount, guarantee_treatment, ccf_percent, warning_codes, source_reference, matrix_version`. La provisión por operación es `provision_amount` (`Decimal`); `CmfProvisionRecord.row_id` identifica la operación (el `detail` preserva el índice de `data.frame`, **sin** columna `row_id`, por lo que la comparación `operation` se apoya en `records`/índice, no en una columna `row_id` del `detail`). El agregado total sale de `card.total_provision_amount`; por cartera, de `summary` sumando `total_provision_amount` sobre `method`/`cmf_category`.

**Contrato consumido del resultado IFRS 9 (SDD-16 §4/§6, verificado en `results.py`).** `IfrsProvisionResult.detail` con `row_id, portfolio, stage, ead, lgd, eir, pd_12m, pd_life, ecl_12m, ecl_lifetime, ecl_reported, scenario_weights, pd_basis, warning_codes`. La provisión contable por operación es `ecl_reported` (`float`, ya `Σ_k w_k`). El agregado total sale de `card.total_ecl_reported`; **por cartera/operación se agrega desde `detail`/`ecl_records`** (colapsado por escenario), no desde `summary` (que desglosa por `scenario` y duplicaría la masa — §3).

**Reconciliación de clave de comparación.**
- `total`: una única celda `cell_id="TOTAL"`; usa `card.total_provision_amount` (CMF) y `card.total_ecl_reported` (IFRS 9). Mínimo acoplamiento.
- `portfolio`: agrupa cada `detail` por su columna de cartera (`cmf_portfolio_col` / `ifrs9_portfolio_col`), aplica `portfolio_crosswalk` para unificar la clave, y compara por cartera. Carteras sin contraparte → celda `cmf_only`/`ifrs9_only` según política.
- `segment`: análogo, por `segment_col` presente en ambos detalles.
- `operation`: alinea por `row_id` (IFRS 9 columna, CMF `records.row_id`/índice); exige identidad de operación entre ambos motores. **Caveat:** CMF y IFRS 9 pueden calcularse sobre perímetros/particiones distintas (CMF por exposición regulatoria, IFRS 9 por instrumento); si los `row_id` no son un conjunto reconciliable, `ProvisioningAlignmentError`. Este es el nivel más prudente pero el de mayor supuesto de datos (D-PROV-2).

**Output `comparison`.** `pandas.DataFrame`, una fila por celda: `cell_id, level, cmf_provision, ifrs9_ecl, reported_provision, binding, coverage, warning_codes`. Orden estable por `cell_id` (orden canónico de cartera/segmento/operación, no orden accidental de dict).

**Output `summary`.** `pandas.DataFrame` agregado por `level`: `level, n_cells, n_binding_cmf, n_binding_ifrs9, n_binding_tie, total_cmf_provision, total_ifrs9_ecl, total_reported_provision, warning_codes`.

**Invariantes.**
- *No mutación:* no modifica `CmfProvisionResult` ni `IfrsProvisionResult` de entrada; usa copias defensivas (los propios DTOs ya entregan copias al acceder a sus DataFrames — se respeta y no se muta en sitio).
- *Máximo correcto:* para toda celda con `coverage="both"`, `reported_provision = max(cmf_provision, ifrs9_ecl)` en el dominio reconciliado; `reported_provision ≥ cmf_provision` y `reported_provision ≥ ifrs9_ecl`.
- *Cobertura:* `coverage="cmf_only"` ⇒ `reported = cmf_provision` (o `max(cmf, 0)` según política); `coverage="ifrs9_only"` ⇒ `reported = ifrs9_ecl`; `binding` refleja la cobertura (`cmf_only`/`ifrs9_only`).
- *Conservación:* `total_reported_provision = Σ_c reported_provision(c)` y `total_reported ≥ max(total_cmf, total_ifrs9)` **solo** para `level="total"` (una celda); a grano fino el total reportado es `≥` ambos totales pero **no** necesariamente igual a `max(Σcmf, Σifrs9)` (el máximo por celda ≥ máximo de las sumas). Esta no-linealidad se documenta y es exactamente la razón por la que el nivel de agregación importa (D-PROV-2).
- *No negatividad y finitud:* `reported_provision ≥ 0`, finito; `-0.0 → 0.0`; nunca `NaN`/`inf`.
- *Trazabilidad:* cada celda referencia el motor vinculante y su cobertura; la card hereda `matrix_version` (CMF) y `term_structure_source` (IFRS 9).
- *Orden estable:* `comparison` y `summary` ordenados por clave canónica; ningún set/dict sin orden determina el output.

## 7. Algoritmos y flujo

**`ProvisioningStep.execute(study, rng)` — secuencia canónica.**
1. **Descartar azar.** `del rng`; el orquestador v1 es determinista.
2. **Leer config.** Resolver `study.config.provisioning` o `ProvisioningConfig()` en invocación programática.
3. **Validar prerequisitos CT-1.** Exigir los `result` de los motores según `requires` dinámicos; ausencia → `ArtifactNotFoundError`.
4. **Cargar resultados.** Obtener `CmfProvisionResult` y/o `IfrsProvisionResult` del `ArtifactStore` (sus accessors ya entregan copias defensivas).
5. **Determinar motores presentes.** `engines_present` a partir de qué resultados existen y de `consume_cmf`/`consume_ifrs9`; validar `require_both`.
6. **Resolver celdas de comparación.** Según `comparison_level`, construir el conjunto de `cell_id` desde cada resultado (total / cartera con crosswalk / segmento / operación), agregando el ECL IFRS 9 desde `detail`/`ecl_records` (no desde `summary`, §3).
7. **Reconciliar numéricamente.** Llevar `cmf_provision` (Decimal) e `ifrs9_ecl` (float) al dominio común (`decimal_quantize`/`float_isclose`), preservando los originales en el registro.
8. **Aplicar el máximo.** Por celda: `reported = max(cmf, ifrs9)`; determinar `binding` (`cmf`/`ifrs9`/`tie` con `tie_tolerance`) y `coverage`.
9. **Resolver cobertura parcial.** Celdas con un solo motor → `use_available` / `fail` / `treat_missing_as_zero` según `coverage_policy`.
10. **Construir DTOs.** `ProvisionComparisonRecord` por celda, `ProvisionComparisonSummary`, `ProvisionOrchestrationCard` (hereda `matrix_version` y `term_structure_source`), `ProvisionOrchestrationResult`; poblar `metric_sections` CT-2.
11. **Auditar decisiones.** Nivel de comparación, crosswalk aplicado, reconciliación numérica, conteo de celdas por motor vinculante, brechas de cobertura, redondeo, `FALTA-DATO`.
12. **Publicar artefactos.** Escribir las cuatro claves `provides` bajo `"provisioning"`.

**`ProvisioningOrchestrator.compare(...)` — detalle del máximo.**
1. Si `cmf is None` y `ifrs9 is None`: `ProvisioningInputError` (nada que orquestar).
2. Para cada celda `c`:
   - `cmf_c = cmf_provision(c)` (Decimal) o `None`; `ifrs9_c = ifrs9_ecl(c)` (float) o `None`.
   - Si ambos: `reported = max(reconcile(cmf_c), reconcile(ifrs9_c))`; `binding` por comparación con `tie_tolerance`.
   - Si solo uno: según `coverage_policy`.
3. Normalizar `-0.0 → 0.0`; nunca publicar `NaN`/`inf`.
4. Agregar el `summary` por nivel y construir la card.

**Alternativas descartadas.**
- *Recalcular ECL o provisión CMF dentro de la orquestación:* descartado; viola la frontera (SDD-15/16 son los motores).
- *Sumar el `summary` IFRS 9 desglosado por escenario para el total por cartera:* descartado; duplica la masa (el `ecl_reported` ya es Σ_k w_k). Se agrega desde `detail`/`ecl_records`.
- *Fabricar una term-structure del máximo:* descartado; el máximo es escalar por celda. `term_structure()` delega en IFRS 9 (referencia auditable), no inventa una curva del piso.
- *Adivinar el crosswalk de carteras por similitud de nombres:* descartado; se exige clave compartida o crosswalk explícito (riesgo regulatorio).
- *Convertir todo a `float` silenciosamente y perder la precisión Decimal del CMF:* descartado; se preservan los originales y la conversión es una decisión declarada (D-PROV-4).
- *Asumir `0` en el motor faltante por default:* descartado como default; subestimaría la provisión. `treat_missing_as_zero` es opt-in explícito.

**Complejidad / rendimiento.** `O(n_cells)` con lookups `O(1)` sobre agregados ya materializados por los motores; el costo dominante es pandas y la cuantización Decimal. Para volumen alto a nivel `operation`, la unión por `row_id` es `O(n)`; se valida el tamaño antes de materializar `comparison`.

## 8. Casos borde y manejo de errores

- **Falta el `result` de un motor exigido (`require_both=True`):** `ArtifactNotFoundError` por CT-1 antes de `execute`.
- **`consume_cmf=False` y `consume_ifrs9=False`:** `ProvisioningConfigError` (no hay nada que orquestar).
- **Solo un motor presente con `require_both=False`:** passthrough del disponible; toda celda `coverage="*_only"`, `binding="*_only"`; se registra `FALTA-DATO` de piso incompleto.
- **`comparison_level="portfolio"` con taxonomías distintas y sin `portfolio_crosswalk`:** `ProvisioningAlignmentError` o `FALTA-DATO` según `fail_on_falta_dato`.
- **`comparison_level="segment"` sin `segment_col` en algún detalle:** `ProvisioningConfigError`.
- **`comparison_level="operation"` con `row_id` no reconciliables (perímetros distintos):** `ProvisioningAlignmentError` listando el desajuste (filas solo-CMF / solo-IFRS 9).
- **Celda cubierta por un solo motor con `coverage_policy="fail"`:** `ProvisioningCoverageError` citando la celda.
- **Monto de entrada negativo o no finito:** no debería ocurrir (los DTOs de SDD-15/16 lo garantizan ≥0 y finito); si se detecta, `ProvisioningInputError` (defensa en profundidad).
- **`Decimal`/`float` que no cuantizan a la misma escala con diferencia material:** se registra `log_decision` con la diferencia; el empate usa `tie_tolerance`.
- **`reported_provision` que redondeado difiere materialmente del exacto:** se audita; los tests comparan pre y post redondeo.
- **Índice duplicado o unión ambigua entre detalles:** `ProvisioningInputError`.

Toda excepción propia desciende de `NikodymError`; mensajes en español e incluyen el nivel de comparación, la celda, el motor y el valor observado cuando aplique.

## 9. Reproducibilidad y auditoría

- **Componentes estocásticos.** Ninguno. `ProvisioningStep.execute(study, rng)` recibe `rng` por contrato y debe hacer `del rng`.
- **Determinismo esperado.** `(result CMF + result IFRS 9 + config_provisioning + uv.lock) → comparison, summary, card idénticos; term_structure() delega en IFRS 9 (no nula) o None si solo CMF`.
- **Normalización numérica.** `-0.0 → 0.0`; no usar `hash()` builtin; la reconciliación Decimal/float es explícita y determinista; nunca depende del orden de iteración de un dict.
- **Audit trail (`log_decision`).** Registrar como mínimo:
  - `provisioning_level`: nivel de comparación y clave/crosswalk de cartera;
  - `provisioning_engines`: motores presentes, `require_both`, cobertura;
  - `provisioning_reconciliation`: dominio numérico, `tie_tolerance`, redondeo;
  - `provisioning_binding`: conteo de celdas donde muerde CMF vs IFRS 9 vs empate;
  - `provisioning_coverage`: celdas solo-CMF / solo-IFRS 9 y política aplicada;
  - `provisioning_falta_dato`: brechas críticas.
- **Model card / report.** `ProvisionOrchestrationCard` expone totales CMF/IFRS 9/reportado, conteo por motor vinculante, `cmf_matrix_version`, `ifrs9_term_structure_source`, fuentes regulatorias y `falta_dato`. `metric_sections` (CT-2) puede incluir `"binding_by_portfolio"`, `"floor_bite_ratio"` sin romper consumidores escalares.
- **Lineage.** `provisioning` no completa `data_hash` ni `config_hash`; los consume. Su aporte al lineage es config computacional, versiones de dependencias, la versión de matrices CMF y la fuente de term-structure IFRS 9 heredadas, y las decisiones auditadas.
- **Vigilancia regulatoria.** Antes de release productivo F4, revalidar que la **regla del máximo y el nivel de agregación** aplicados coinciden con la interpretación normativa vigente de la institución (CMF como piso prudencial del ECL contable); el nivel es parámetro de la entidad, no constante Nikodym.

## 10. Dependencias

**Internas.**
- SDD-01 (`core`): `Step`, `ArtifactKey`, `ArtifactStore`, `AuditableMixin`, `NikodymError`, lineage, `config_hash`, patrón CT-2 `term_structure()`.
- SDD-05: `NikodymBaseConfig`, hooks diferidos, `INFRA_SECTIONS`, round-trip YAML.
- SDD-15 (`provisioning/cmf`): `CmfProvisionResult`/`summary`/`card` (montos `Decimal`); `term_structure()` retorna `None` (CT-2/D-CORE-7).
- SDD-16 (`provisioning/ifrs9`): `IfrsProvisionResult`/`summary`/`card` (montos `float`), `total_ecl_reported`, `term_structure()` no nula.
- Aguas abajo: SDD-22 (validación/backtesting del piso), SDD-23 (ui), SDD-26 (report).

**Externas.**

| Dependencia | Versión / fuente | Licencia | Uso | Distribución |
|---|---|---|---|---|
| pandas | `>=2.0` | BSD-3 ✅ | frames de comparación, agregaciones | base |
| pydantic | `>=2` | MIT ✅ | DTOs/config frozen | base |
| decimal (stdlib) | Python | PSF ✅ | reconciliación exacta de montos CMF | stdlib |

**Núcleo liviano.** `nikodym.core` no importa `nikodym.provisioning`. `import nikodym.provisioning` registra config/step de orquestación (y expone los sub-paquetes `cmf`/`ifrs9`) sin cargar pandas pesado en top-level; pandas se usa dentro de `compare`/`execute`. No hay dependencia copyleft (GPL). Ninguna dependencia externa nueva respecto a SDD-15/16.

## 11. Estrategia de tests

Marco transversal en SDD-24. Casos específicos con goldens verificables a mano:

- **Golden máximo — gana CMF.** `cmf_provision=100.0`, `ifrs9_ecl=60.165289` (ECL golden de SDD-16 §11) → `reported=100.0`, `binding="cmf"`.
- **Golden máximo — gana IFRS 9.** `cmf_provision=50.0`, `ifrs9_ecl=73.0` (ECL multiescenario golden de SDD-16 §11) → `reported=73.0`, `binding="ifrs9"`.
- **Golden máximo — empate.** `cmf_provision=73.0`, `ifrs9_ecl=73.0` → `reported=73.0`, `binding="tie"` (dentro de `tie_tolerance`).
- **Golden nivel `total` con carteras reales.** CMF B4 `provision=438750` (golden SDD-15 §11) vs ECL total `60.165289` → `reported=438750`, `binding="cmf"` (el piso prudencial muerde).
- **No-linealidad por nivel.** Dos carteras: CMF `(100, 10)`, IFRS 9 `(10, 100)`. A nivel `portfolio`: `reported=(100,100)`, total `200`. A nivel `total`: `max(110,110)=110`. El test verifica que el total reportado a grano fino (`200`) `≥` el total a grano grueso (`110`) y documenta que el nivel de agregación cambia la plata (D-PROV-2).
- **Cobertura parcial.** Cartera solo-CMF con `use_available` → `reported=cmf`, `coverage="cmf_only"`; con `fail` → `ProvisioningCoverageError`; con `treat_missing_as_zero` → `reported=max(cmf,0)=cmf`.
- **Reconciliación Decimal/float.** `cmf=Decimal("100.00")` vs `ifrs9=100.0000000004` con `tie_tolerance=1e-6` → `binding="tie"`; sin tolerancia → gana IFRS 9 por el epsilon. Verifica que el monto CMF original no se recuantiza en el registro.
- **No mutación.** Snapshots profundos de `CmfProvisionResult` e `IfrsProvisionResult` permanecen iguales tras `execute`.
- **`term_structure()` delegada.** Con IFRS 9 presente, retorna la curva larga de `IfrsProvisionResult.term_structure()`; solo CMF → `None`.
- **CT-1.** `requires` dinámicos según motores presentes; falta de un `requires` exigido → `ArtifactNotFoundError`; `require_both=False` con un solo motor → passthrough sin error.
- **Config.** Round-trip YAML; cambiar `comparison_level`, `portfolio_crosswalk`, `coverage_policy`, `numeric_reconciliation` o `rounding` cambia `config_hash`; **B17.1 mueve `GOLDEN_DEFAULT_CONFIG_HASH`** (test explícito, no regresión).
- **Import liviano.** `import nikodym.core` no importa `nikodym.provisioning`; `import nikodym.provisioning` no carga pandas pesado hasta pedirlo (test de `sys.modules` en subproceso).
- **Warnings como error.** `filterwarnings=["error"]`; cualquier casting o pérdida de precisión no controlada se convierte en error.
- **Determinismo / tidy.** Dos corridas con mismos resultados de entrada y config producen `comparison`, `summary`, `card` byte-equivalentes y orden estable.
- **Cobertura regulatoria 100%.** `src/nikodym/provisioning/*.py` (orquestación) en el grupo de cobertura 100% (piso prudencial → regulatorio, CT §4). `mypy --strict`; ruff `E,F,I,N,UP,B,SIM,RUF,D` con docstrings en español.

Fixtures: `CmfProvisionResult` sintético (por cartera y total), `IfrsProvisionResult` sintético (con `detail`/`ecl_records` colapsado por escenario), `ProvisioningConfig` mínimo por nivel, `InMemoryAuditSink`, y casos degenerados (taxonomías sin crosswalk, `row_id` no reconciliables, cobertura parcial, empate en el borde de tolerancia).

## 12. Decisiones abiertas y riesgos

**Riesgos.**
- **Nivel de agregación mal elegido cambia la provisión reportada.** El máximo por celda es no-lineal: `Σ max(cmf_c, ifrs9_c) ≥ max(Σ cmf, Σ ifrs9)`. Mitigación: `comparison_level` explícito, default conservador `total`, y documentación de la no-linealidad; **decisión de la entidad** (D-PROV-2, R0).
- **Taxonomías de cartera no reconciliables.** CMF (`cmf_portfolio`: comercial/consumo/vivienda…) e IFRS 9 (`portfolio` propio) pueden no compartir clave. Mitigación: `portfolio_crosswalk` explícito o `FALTA-DATO`; nunca adivinar (D-PROV-3, R0).
- **Pérdida de precisión Decimal→float.** Mitigación: reconciliación declarada, originales preservados, tolerancia de empate configurable (D-PROV-4).
- **Cobertura parcial reportada como piso completo.** Mitigación: `coverage`/`binding` marcan `*_only`; card expone `falta_dato`; report/ui deben mostrarlo visible (D-PROV-5).
- **Doble conteo del ECL por escenario.** Mitigación: se agrega desde `detail`/`ecl_records`, no desde `summary` desglosado por escenario (§3, requisito de correctitud).
- **Perímetros distintos entre motores a nivel operación.** Mitigación: `ProvisioningAlignmentError` explícito; `operation` es opt-in.

**FALTA-DATO explícitos.**
- **FALTA-DATO-PROV-1 — Crosswalk de carteras CMF↔IFRS 9.** Sin clave compartida ni mapeo configurado, la comparación por cartera/segmento no es posible.
- **FALTA-DATO-PROV-2 — Identidad de operación entre motores.** El nivel `operation` exige `row_id` reconciliables; si los perímetros difieren, no hay alineación fila-a-fila.
- **FALTA-DATO-PROV-3 — Piso incompleto.** Correr con un solo motor (`require_both=False`) produce un piso parcial, no la provisión regulatoria final.

**Fuentes verificadas / citas.**
- **ESPECIFICACIONES.md** §5.4 (línea 131): regla dura CMF ≠ IFRS 9, provisión final = **máximo** entre ECL contable y piso prudencial CMF; `provisioning/` orquesta y expone el comparativo. §6.3 (árbol, ~línea 195): `provisioning/ # orquesta CMF vs IFRS 9 → máximo (piso regulatorio)`.
- **ROADMAP.md** F4: objetivo «ECL + piso CMF»; tarea «Orquestación: `provisioning` compara CMF vs IFRS 9 y aplica el máximo»; DoD «ECL reproducible… tests de fórmula contra valores canónicos».
- **SDD-15 (`provisioning/cmf`)** §4/§6 y `results.py`: `CmfProvisionResult` (`detail`/`summary`/`records`/`card`/`matrix_bundle`), montos `Decimal`, `term_structure()` → `None`; interfaz hacia SDD-17 (usar `summary`/`card` y term-structure solo si no es None).
- **SDD-16 (`provisioning/ifrs9`)** §6 (l.531) y §12 D-IFRS-6 (l.711) y `results.py`: `IfrsProvisionResult` publica `total_ecl_reported` + `term_structure()` no nula; el shape del comparativo y la regla del máximo son responsabilidad de SDD-17; `ecl_reported` ya es `Σ_k w_k`.
- **_CONTRATOS-TRANSVERSALES.md** CT-1 (`requires`/`provides` dinámicos), CT-2 (`term_structure()`, `metric_sections`), CT-4 (owner del ensamblado en capa fina), §4 (piso prudencial regulatorio a 100% de cobertura).
- **core/config/hashing.py:24**: `INFRA_SECTIONS = {"name","governance","audit","tracking","report"}` — `provisioning` no pertenece → mueve `GOLDEN_DEFAULT_CONFIG_HASH` al cablearse (B17.1).
- **core/study.py** (l.54-110): `_DOMAIN_MODULES`/`_DOMAIN_CONFIG_CLASSES`/`_DEFAULT_DOMAIN_ORDER` con `provisioning_ifrs9`/`provisioning_cmf` como últimos; `provisioning` va después de ambos.

## Decisiones para revisión de Cami

- **D-PROV-1 — Dominio y clave de config `provisioning`.** Recomendación: dominio plano `"provisioning"` en el paquete padre `nikodym.provisioning` (espeja `provisioning_cmf`/`provisioning_ifrs9`), sección `NikodymConfig.provisioning`. Confirmar (no hay colisión con los dos sub-configs existentes).
- **D-PROV-2 — Nivel de agregación del máximo. [⚠ DECISIÓN CAMI = R0]** Recomendación: default `total` (conservador, sin supuestos de taxonomía), con `portfolio`/`segment`/`operation` opt-in. **El nivel cambia la provisión reportada (plata/regulatorio):** `Σ max(cmf_c, ifrs9_c) ≥ max(Σ cmf, Σ ifrs9)`. Ligado a D-IFRS-6 de SDD-16. ¿A qué grano debe morder el piso CMF según la interpretación normativa de la entidad — total, por cartera, o por operación?
- **D-PROV-3 — Crosswalk de carteras CMF↔IFRS 9. [⚠ DECISIÓN CAMI = R0]** Recomendación: exigir clave compartida o `portfolio_crosswalk` explícito; nunca adivinar por similitud. **Las taxonomías CMF (comercial/consumo/vivienda) e IFRS 9 pueden no coincidir**, y un mapeo errado cambia qué números se comparan (plata). ¿Se define un crosswalk estándar o se deja 100% a config de la entidad?
- **D-PROV-4 — Reconciliación Decimal (CMF) vs float (IFRS 9).** Recomendación: `decimal_quantize` (reportar en Decimal, preservar originales, empate por `tie_tolerance`). Alternativa `float_isclose`. Decisión técnica/contable defendible; confirmar dominio de reporte preferido.
- **D-PROV-5 — Política de cobertura parcial.** Recomendación: `use_available` (reportar el motor disponible, marcado `*_only`) por default; `fail` y `treat_missing_as_zero` opt-in. Confirmar; `treat_missing_as_zero` es sensible porque asumir 0 en el faltante subestima la provisión.
- **D-PROV-6 — Shape mínimo del comparativo para report/validation/ui.** Recomendación: `comparison` (por celda: `cmf_provision`, `ifrs9_ecl`, `reported_provision`, `binding`, `coverage`) + `summary` (por nivel) + `card`. Es el contrato que consumirán SDD-22/23/26 (aún no construidos). Confirmar que este shape cubre lo que report/validation necesitarán, o ampliar aditivamente (CT-2) sin romper.
- **D-PROV-7 — `require_both` por default.** Recomendación: `True` (el piso prudencial presupone ambos motores; correr uno solo es diagnóstico/parcial). Confirmar; `False` habilita pipelines transitorios con passthrough marcado.
- **D-PROV-8 — `term_structure()` de la orquestación.** Recomendación: delegar en la curva ECL de IFRS 9 (no fabricar una curva del máximo, que es escalar por celda); `None` si solo CMF. Confirmar.

> **R0 (decisiones de producto/plata/normativa no disponible localmente):** D-PROV-2 (nivel de agregación del máximo) y D-PROV-3 (crosswalk de carteras). El resto son defaults técnicos/contables defendibles con fuente citada, configurables. La **regla del máximo en sí NO es R0** (es norma, ESPEC §5.4, citada como decidida). Ninguna decisión de este SDD dispara release público, PyPI, datos externos ni cambio de licencia.
