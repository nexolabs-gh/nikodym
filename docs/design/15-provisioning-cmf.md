# SDD-15 — `provisioning/cmf` (provisiones CMF, modelo estándar B-1)

| Campo | Valor |
|---|---|
| **SDD** | 15 |
| **Módulo** | `nikodym.provisioning.cmf` |
| **Dominio** | Provisiones |
| **Fase** | F3 |
| **Tanda de producción** | T4 (Provisiones) |
| **Estado** | 🟡 Borrador |
| **Depende de** | SDD-01 (`core`), SDD-02 (`data`), SDD-05 (convenciones + config), SDD-08 (`model`) |
| **Lo consumen** | SDD-16 (`provisioning/ifrs9`, comparación futura), SDD-17 (`provisioning`, orquestación/piso), SDD-22 (`validation`), SDD-23 (`ui`), SDD-26 (`report`) |
| **Autor / Fecha** | DanIA (redacción SDD-15 para T4) / 2026-06-29 |

---

## 1. Propósito y responsabilidad

**Qué resuelve (una frase).** `provisioning.cmf` calcula la provisión regulatoria chilena bajo el modelo estándar del Compendio de Normas Contables CMF, Capítulo B-1, aplicando `PE = PI * PDI * Exposición` por operación/cartera y publicando resultados auditables por fila y agregados por cartera.

**Responsabilidad unica (que SI hace).**
- Carga matrices regulatorias CMF B-1/B-3 desde **datos versionados**, con manifest de fuente, vigencia, hash y estado de verificacion; el motor nunca dispersa numeros normativos en ramas de codigo.
- Calcula exposicion: saldo directo mas contingentes convertidos por factor B-3, con override `100%` para clientes/operaciones en incumplimiento cuando aplique.
- Resuelve la matriz aplicable por cartera: comercial individual A1-C6, comercial grupal, consumo, vivienda PVG, avales/fianzas y garantias admisibles segun B-1.
- Calcula PI, PDI, PE y monto de provision por fila, preservando trazabilidad de matriz/fila normativa usada.
- Trata la cartera individual en incumplimiento C1-C6 con su regla propia: `Tasa de Perdida Esperada = (E - R) / E` y `Provision = E * (PP/100)`, no como una multiplicacion PI/PDI ordinaria.
- Consume la PD que publica F1 (SDD-08 `model.raw_pd_frame`) como insumo trazable para asignacion o contraste de PI, sin permitir que una PD libre reemplace parametros regulatorios sin una politica explicita y auditada.
- Publica artefactos namespaced bajo `"provisioning_cmf"`: detalle por fila, resumen por cartera, bundle de matrices usadas, resultado agregado y card de provision.
- Aporta el sub-config **`CmfProvisioningConfig`** (seccion `provisioning_cmf` de `NikodymConfig`), computacional y por tanto incluido en el `config_hash`.
- Registra con `log_decision` la version normativa activa, politicas de mapeo PD->PI, garantias aplicadas/omitidas, contingentes B-3, redondeo y cualquier fila excluida.

**Frontera dura de responsabilidad (que NO hace, y quien lo hace).**
- **No entrena ni calibra modelos de PD.** SDD-08 produce PD cruda; SDD-10 puede producir PD calibrada para scoring. `provisioning.cmf` solo las consume como inputs declarados.
- **No implementa IFRS 9/ECL.** SDD-16 calcula ECL; SDD-17 compara CMF vs IFRS 9 y aplica el maximo cuando corresponda.
- **No construye term-structures lifetime.** SDD-18/19/20/21 cubren survival, Markov, forward-looking y stress.
- **No decide si un banco puede usar metodologia interna en vez del modelo estandar.** Este SDD cubre el modelo estandar B-1; una metodologia interna de PI/PDI requeriria SDD separado o extension explicita.
- **No inventa haircuts de garantias financieras.** Si el dato no esta verificado en `docs/normativa_cmf_parametros.md`, el motor falla o marca `FALTA-DATO` segun config no-default.
- **No muta `data.frame`, `model.raw_pd_frame` ni artefactos aguas arriba.** Lee copias defensivas y publica resultados propios.
- **No arrastra `provisioning` al nucleo.** `import nikodym.core` no importa `nikodym.provisioning`, matrices regulatorias ni pandas extra fuera de lo ya base.

## 2. Contexto y ubicación en la arquitectura

- **Capa:** Provisiones regulatorias locales (F3/T4). Corre despues de `data` y `model`; puede correr sin scorecard/puntos si existe `model.raw_pd_frame` y las columnas regulatorias requeridas en `data.frame`.
- **Quien lo invoca:** `Study.run()` como seccion `provisioning_cmf` de `NikodymConfig`, o API programatica para calcular provisiones CMF sobre un frame ya validado.
- **A quien invoca:** `core` (`Step`, `ArtifactKey`, `ArtifactStore`, `AuditableMixin`, excepciones), `data` (`frame`, `labels`, `splits`), `model` (`raw_pd_frame`) y los datos versionados del paquete `nikodym.provisioning.cmf`.

```text
data -> ... -> model
  |             |
  |             v
  +-------> provisioning_cmf (SDD-15) -> provisioning (SDD-17) -> report/validation
             B-1/B-3 matrices
             PI/PDI/E/provision
```

**Interaccion con `Study` y config declarativo.** `CmfProvisioningStep` es un `Step` nativo registrado con `@register("standard", domain="provisioning_cmf")`. Declara `requires`/`provides` (CT-1), lee `data.frame` y `model.raw_pd_frame`, carga el bundle normativo activo, calcula resultados y escribe sus artefactos bajo `"provisioning_cmf"`. El `rng` se recibe por contrato homogeneo; v1 no usa azar y debe hacer `del rng`.

**Orden canonico propuesto.** Al implementar SDD-15:
- `_DOMAIN_MODULES["provisioning_cmf"] = "nikodym.provisioning.cmf"`;
- `_DOMAIN_CONFIG_CLASSES["provisioning_cmf"] = ("nikodym.provisioning.cmf.config", "CmfProvisioningConfig")`;
- `_DEFAULT_DOMAIN_ORDER` agrega `"provisioning_cmf"` despues de `"model"` para F3 minimo. Si Cami decide consumir PD calibrada de SDD-10 como fuente default, el orden pasa a ser despues de `"calibration"` (ver D-CMF-2).

**Paquete fisico troceable.**

```text
src/nikodym/provisioning/
  __init__.py
  cmf/
    __init__.py
    config.py
    exceptions.py
    results.py
    matrices.py
    engine.py
    step.py
    data/
      cmf_b1_b3_2025_01.yaml
      cmf_b1_b3_2025_01.sha256
      manifest.json
```

**Troceo implementable un modulo/commit.**
- **B15.1 - matrices versionadas:** `cmf/data/*` + `matrices.py` loader/manifest/hash, sin motor de calculo.
- **B15.2 - config/exceptions:** `config.py`, `exceptions.py`, hook diferido en `NikodymConfig`, sin mover `core` a imports pesados.
- **B15.3 - results:** DTOs Pydantic puros, `term_structure()` CT-2, copias defensivas y serializacion.
- **B15.4 - engine:** `CmfProvisioningEngine` determinista con goldens por matriz.
- **B15.5 - step:** `CmfProvisioningStep`, `@register`, `requires/provides`, cableado `core.study` e integracion end-to-end.

Cada bloque debe cerrar con ruff, mypy `--strict`, tests 100% del modulo tocado y cobertura regulatoria 100% para `nikodym.provisioning.cmf`.

## 3. Conceptos y fundamentos

**Formula general B-1.** Para carteras en cumplimiento bajo modelo estandar:

```text
PE_i = PI_i * PDI_i
Provision_i = Exposicion_i * PE_i
```

Las matrices de `docs/normativa_cmf_parametros.md` expresan PI, PDI y PE en porcentaje. El motor normaliza a fraccion decimal solo para calcular, y conserva el porcentaje original en el detalle auditado. Fuente: `docs/normativa_cmf_parametros.md` Advertencias §2; CNC CMF, Capitulo B-1.

**Exposicion.** Para colocaciones directas, la exposicion base es el saldo configurado. Para creditos contingentes, la exposicion se calcula como `monto_contingente * CCF_B3`. Si el cliente/operacion esta en incumplimiento segun B-1, el factor B-3 se fuerza a `100%` (fuente: `docs/normativa_cmf_parametros.md` §6; CNC Capitulo B-3). Si hay saldo directo y contingente, la exposicion total es la suma de ambos componentes, salvo regla especifica de cartera.

**PI desde PD F1.** La PD de F1 llega desde `("model", "raw_pd_frame")`, columna `pd_raw` (SDD-08). En el modelo estandar B-1, esa PD **no reemplaza automaticamente** los parametros PI de las matrices regulatorias. La ruta segura v1 es:
- si la matriz B-1 pide categoria/tramo (A1-B4, C1-C6, mora, PVG, PVB/PTVG, producto), la PI se toma de la fila normativa resultante;
- la PD F1 se usa para asignar una categoria CMF solo si `pd_mapping.method="pd_breaks"` trae umbrales explicitos del usuario, versionados en config y auditados;
- si no hay categoria/tramo ni mapping explicito, se levanta `CmfMappingError`.

**Cartera individual en incumplimiento C1-C6.** Para C1-C6 no se aplica `PI * PDI`. La norma define `Tasa de Perdida Esperada = (E - R) / E`; esa tasa se encasilla en C1-C6 y se aplica `PP` segun tabla: C1 `2%`, C2 `10%`, C3 `25%`, C4 `40%`, C5 `65%`, C6 `90%` (fuente: `docs/normativa_cmf_parametros.md` §1.3; CNC B-1 numeral 2.2, hoja 9, Circular 3.573/2014).

**Garantias.**
- Avales/fianzas pueden sustituir la calidad crediticia del deudor por la del avalista en la proporcion avalada. La tabla verificada contiene tres filas: `AA/Aa2`, `A/A2`, `BBB-/Baa3`, con PI/PDI por escala internacional/nacional (fuente: `docs/normativa_cmf_parametros.md` §5.2; CNC B-1 numeral 4.1 letra a, hoja 18, Circular 3.638/2018).
- Garantias reales, bienes en leasing, PVG/PVB/PTVG y factoring operan por la matriz de cartera correspondiente (fuente: `docs/normativa_cmf_parametros.md` §§2, 4, 5.1).
- Garantias financieras requieren aforos/haircuts que `docs/normativa_cmf_parametros.md` marca como **PENDIENTE** (§5.2). En v1, si una fila requiere ese descuento y no trae `recoverable_amount` ya calculado por el usuario, el default es fallar con `CmfMissingRegulatoryDataError`.

**Matrices regulatorias como datos versionados.** La implementacion debe cargar un bundle con al menos:

| matriz_id | cobertura | fuente en `docs/normativa_cmf_parametros.md` | fuente normativa |
|---|---|---|---|
| `commercial_individual_performing_v2014` | Comercial individual Normal/Subestandar A1-A6, B1-B4: PI, PDI, PE | §1.1 | CNC B-1 num. 2.1, hoja 3, Circular 3.573/2014 |
| `commercial_individual_default_v2014` | Comercial individual incumplimiento C1-C6: rango perdida esperada y PP | §1.3 | CNC B-1 num. 2.2, hoja 9, Circular 3.573/2014 |
| `commercial_group_leasing_v2018` | Leasing comercial: PI por mora/bien y PDI por PVB/bien | §2.a | CNC B-1 num. 3.1.2, hojas 13-14, Circular 3.638/2018 |
| `commercial_group_student_v2018` | Prestamos estudiantiles: PI/PDI por exigibilidad, mora y tipo CAE/CORFO | §2.b | CNC B-1 num. 3.1.2, hojas 14-15, Circular 3.638/2018 |
| `commercial_group_generic_factoring_v2020` | Comerciales genericas/factoraje: PI por mora/PTVG y PDI por PTVG/responsabilidad cedente | §2.c | CNC B-1 num. 3.1.2, hojas 15-16, Circular 2.257/2020 |
| `commercial_group_guarantee_substitution_v2018` | Sustitucion por avales, formulas PE directa y PI/PDI | §2.d | CNC B-1 num. 4.1 letra a, hojas 18-19, Circular 3.638/2018 |
| `consumer_standard_v2025` | Consumo: PI por mora/hipotecario/mora sistema y PDI por producto/hipotecario | §3 | Circular 2.346/2024, B-1 num. 3.1.3, vigente cierre enero 2025 |
| `housing_pvg_v2018` | Vivienda PVG: PI/PDI/PE por PVG y mora, mas MP seguro estatal | §4 y §4.1 | CNC B-1 num. 3.1.1, hojas 12-13, Circular 3.638/2018 |
| `guarantee_aval_quality_v2018` | Avales/fianzas: equivalencia de calidad crediticia por escala | §5.2 | CNC B-1 num. 4.1 letra a, hoja 18, Circular 3.638/2018 |
| `contingent_b3_v2016` | CCF contables B-3 para creditos contingentes | §6 | CNC B-3 num. 3, hojas 1-2, Circular 3.604/2016 |

**Extracto de control: comercial individual A1-B4.** Estos numeros no deben copiarse a ramas de codigo; viven en el archivo de datos versionado y se testean contra esta fuente.

| Categoria | PI (%) | PDI (%) | PE (%) |
|---|---:|---:|---:|
| A1 | 0,04 | 90,0 | 0,03600 |
| A2 | 0,10 | 82,5 | 0,08250 |
| A3 | 0,25 | 87,5 | 0,21875 |
| A4 | 2,00 | 87,5 | 1,75000 |
| A5 | 4,75 | 90,0 | 4,27500 |
| A6 | 10,00 | 90,0 | 9,00000 |
| B1 | 15,00 | 92,5 | 13,87500 |
| B2 | 22,00 | 92,5 | 20,35000 |
| B3 | 33,00 | 97,5 | 32,17500 |
| B4 | 45,00 | 97,5 | 43,87500 |

Fuente de todos los valores de la tabla: `docs/normativa_cmf_parametros.md` §1.1; CNC B-1 numeral 2.1, hoja 3, Circular 3.573/2014.

**Extracto de control: consumo vigente 2025.** Matriz PI por cuatro tramos de mora (`0 a 7`, `8 a 30`, `31 a 60`, `61 a 89` dias), tenencia de hipotecario y mora sistema >30 dias: valores `3,3%`, `14,6%`, `6,6%`, `19,8%`; `20,4%`, `41,6%`, `30,6%`, `48,5%`; `50,2%`, `63,0%`, `65,1%`, `66,3%`; `62,6%`, `81,7%`, `72,3%`, `86,9%`. Si el deudor esta en incumplimiento, `PI = 100%`. La PDI por producto/hipotecario es `33,2%`, `47,7%`, `49,5%`, `56,6%`, `60,3%` segun la tabla §3.2. Fuente: `docs/normativa_cmf_parametros.md` §3; Circular 2.346/2024, B-1 numeral 3.1.3, vigente desde cierre contable enero 2025.

**Extracto de control: vivienda PVG.** La matriz cubre cuatro tramos PVG (`PVG <= 40%`, `40% < PVG <= 80%`, `80% < PVG <= 90%`, `PVG > 90%`) y cinco estados de mora (`0`, `1-29`, `30-59`, `60-89`, incumplimiento). Incluye PI, PDI y PE para cada cruce, mas MP para creditos con seguro estatal de remate: `100%`, `95%`, `96%`, `84%`, `89%` segun PVG y valor vivienda. Fuente: `docs/normativa_cmf_parametros.md` §4 y §4.1; CNC B-1 numeral 3.1.1, hojas 12-13, Circular 3.638/2018. Los valores completos deben residir en `housing_pvg_v2018`, no en el motor.

**Extracto de control: creditos contingentes B-3.** La tabla contable B-3 esta marcada **VERIFICADO** en `docs/normativa_cmf_parametros.md` §6 y debe implementarse como matriz activa por default:

| fila B-3 | tipo de credito contingente | CCF |
|---|---|---:|
| a) | Avales y fianzas | 100% |
| b) | Cartas de credito del exterior confirmadas | 20% |
| c) | Cartas de credito documentarias emitidas | 20% |
| d) | Boletas de garantia | 50% |
| e) | Lineas de credito de libre disposicion (tarjetas, sobregiros pactados) | 35% |
| f) CAE | Otros compromisos de credito - creditos para estudios superiores Ley N° 20.027 | 15% |
| f) otros | Otros compromisos de credito - otros | 100% |
| g) | Otros creditos contingentes | 100% |

Fuente de todos los valores: `docs/normativa_cmf_parametros.md` §6; CNC Capitulo B-3, numeral 3, hojas 1-2, Circular 3.604/2016. El rubro f) requiere logica condicional (`CAE Ley 20.027` vs otros), y si el cliente/operacion esta en incumplimiento segun B-1, el CCF se fuerza a `100%`. No mezclar estos CCF contables de provisiones con tablas de capital/APR/Basilea.

## 4. API pública (contrato)

> Firmas ilustrativas, no implementacion. Identificadores en ingles tecnico; docstrings y mensajes en español.

```python
# nikodym/provisioning/cmf/config.py
class CmfMatrixConfig(NikodymBaseConfig): ...
class CmfPdMappingConfig(NikodymBaseConfig): ...
class CmfExposureConfig(NikodymBaseConfig): ...
class CmfGuaranteeConfig(NikodymBaseConfig): ...
class CmfProvisioningConfig(NikodymBaseConfig): ...

# nikodym/provisioning/cmf/exceptions.py
class CmfProvisioningError(NikodymError): ...
class CmfConfigError(CmfProvisioningError): ...
class CmfInputError(CmfProvisioningError): ...
class CmfMappingError(CmfProvisioningError): ...
class CmfMatrixError(CmfProvisioningError): ...
class CmfMissingRegulatoryDataError(CmfMatrixError): ...
class CmfCalculationError(CmfProvisioningError): ...
```

```python
# nikodym/provisioning/cmf/matrices.py
class CmfMatrixManifest(BaseModel): ...
class CmfMatrixRow(BaseModel): ...
class CmfMatrixBundle(BaseModel): ...

def load_cmf_matrices(config: CmfMatrixConfig) -> CmfMatrixBundle: ...
def validate_cmf_matrix_bundle(bundle: CmfMatrixBundle) -> None: ...
```

```python
# nikodym/provisioning/cmf/results.py
class CmfProvisionRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    row_id: str
    portfolio: str
    method: str
    exposure_amount: Decimal
    direct_exposure_amount: Decimal
    contingent_exposure_amount: Decimal
    pi_percent: Decimal | None
    pdi_percent: Decimal | None
    pe_percent: Decimal
    provision_amount: Decimal
    matrix_id: str
    matrix_row_id: str
    cmf_category: str | None = None
    pd_source_value: Decimal | None = None
    guarantee_treatment: str | None = None
    warnings: tuple[str, ...] = ()

class CmfPortfolioSummary(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    portfolio: str
    n_rows: int
    total_exposure_amount: Decimal
    total_provision_amount: Decimal
    weighted_pe_percent: Decimal
    warnings: tuple[str, ...] = ()

class CmfProvisionCard(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    matrix_version: str
    as_of_date: str
    n_rows: int
    total_exposure_amount: Decimal
    total_provision_amount: Decimal
    portfolios: tuple[CmfPortfolioSummary, ...]
    regulatory_sources: tuple[str, ...]
    metric_sections: dict[str, Any] = Field(default_factory=dict)  # CT-2.

class CmfProvisionResult(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True, extra="forbid")
    detail: "pandas.DataFrame"
    summary: "pandas.DataFrame"
    records: tuple[CmfProvisionRecord, ...]
    card: CmfProvisionCard
    matrix_bundle: CmfMatrixBundle
    def term_structure(self) -> "pandas.DataFrame": ...
```

`term_structure()` cumple CT-2: para CMF v1 retorna una estructura monoperiodo con `as_of_date`, `portfolio`, `exposure_amount`, `provision_amount` y `pe_percent`. SDD-16/17 podran comparar contra IFRS 9 sin romper el contrato.

```python
# nikodym/provisioning/cmf/engine.py
class CmfProvisioningEngine:
    config_cls: ClassVar[type[CmfProvisioningConfig]] = CmfProvisioningConfig
    def __init__(self, config: CmfProvisioningConfig, *, matrices: CmfMatrixBundle) -> None: ...
    @classmethod
    def from_config(cls, cfg: CmfProvisioningConfig) -> "CmfProvisioningEngine": ...
    def calculate(
        self,
        frame: "pandas.DataFrame",
        *,
        pd_frame: "pandas.DataFrame",
        as_of_date: str,
        audit: "AuditSink | None" = None,
    ) -> CmfProvisionResult: ...
```

```python
# nikodym/provisioning/cmf/step.py
@register("standard", domain="provisioning_cmf")
class CmfProvisioningStep(AuditableMixin):
    name: str = "provisioning_cmf"
    requires: tuple[ArtifactKey, ...] = (
        ("data", "frame"),
        ("data", "labels"),
        ("data", "splits"),
        ("model", "raw_pd_frame"),
    )
    provides: tuple[ArtifactKey, ...] = (
        ("provisioning_cmf", "detail"),
        ("provisioning_cmf", "summary"),
        ("provisioning_cmf", "matrix_bundle"),
        ("provisioning_cmf", "result"),
        ("provisioning_cmf", "card"),
    )
    @classmethod
    def from_config(cls, cfg: CmfProvisioningConfig) -> "CmfProvisioningStep": ...
    def execute(self, study: "Study", rng: "numpy.random.Generator") -> "CmfProvisionResult": ...
```

**Artefactos que `CmfProvisioningStep.execute` escribe en `study.artifacts`.**

| clave | tipo | contenido |
|---|---|---|
| `"detail"` | `pandas.DataFrame` | una fila por exposicion, con PI/PDI/PE, exposicion, provision, matriz/fila normativa y warnings |
| `"summary"` | `pandas.DataFrame` | agregados por cartera/metodo/categoria |
| `"matrix_bundle"` | `CmfMatrixBundle` | snapshot de matrices usadas, manifest, hash y fuentes |
| `"result"` | `CmfProvisionResult` | contenedor agregado |
| `"card"` | `CmfProvisionCard` | resumen para governance/report/orquestacion |

**Ejemplo de uso (pseudocodigo).**

```python
study.run(steps=["data", "binning", "selection", "model", "provisioning_cmf"])
cmf = study.artifacts.get("provisioning_cmf", "result")
detalle = study.artifacts.get("provisioning_cmf", "detail")
```

## 5. Configuración (schema Pydantic)

`CmfProvisioningConfig` es el sub-config de la seccion `provisioning_cmf` de `NikodymConfig`. Sigue SDD-05: `NikodymBaseConfig`, `extra="forbid"`, `frozen=True`, campos con `title`/`description`, rangos `ge/le`, `Literal` en categoricos y metadatos `ui_*`. **No es infraestructura** (`provisioning_cmf ∉ INFRA_SECTIONS`): cambiar version de matrices, mapping PD, columnas regulatorias, politica de garantias o redondeo cambia el `config_hash`.

```python
class CmfMatrixConfig(NikodymBaseConfig):
    active_version: str = Field("cmf_b1_b3_2025_01", title="Version normativa activa")
    require_verified_rows: bool = Field(True, title="Exigir filas verificadas")
    fail_on_unmapped_contingent_type: bool = Field(True, title="Fallar ante tipo contingente no mapeado")
    fail_on_source_mismatch: bool = Field(True, title="Fallar ante hash/fuente inconsistente")

class CmfPdMappingConfig(NikodymBaseConfig):
    pd_source_domain: Literal["model", "calibration"] = Field("model", title="Dominio fuente PD")
    pd_source_key: str = Field("raw_pd_frame", title="Artefacto fuente PD")
    pd_column: str = Field("pd_raw", title="Columna PD")
    method: Literal["provided_cmf_category", "pd_breaks"] = Field(
        "provided_cmf_category", title="Metodo PD a categoria/PI")
    pd_breaks: tuple[float, ...] = Field(default_factory=tuple, title="Cortes PD para categorias")
    categories: tuple[str, ...] = Field(default_factory=tuple, title="Categorias CMF resultantes")

class CmfExposureConfig(NikodymBaseConfig):
    direct_exposure_col: str = Field("exposure_amount", title="Exposicion directa")
    contingent_amount_col: str = Field("contingent_amount", title="Monto contingente")
    contingent_type_col: str = Field("contingent_type", title="Tipo contingente B-3")
    is_default_col: str = Field("is_default", title="Indicador incumplimiento")
    allow_negative_exposure: bool = Field(False, title="Permitir exposicion negativa")
    rounding: Literal["none", "currency_2dp", "integer_currency"] = Field(
        "none", title="Redondeo de provision")

class CmfGuaranteeConfig(NikodymBaseConfig):
    enable_aval_substitution: bool = Field(True, title="Aplicar sustitucion por aval")
    financial_guarantee_policy: Literal["fail", "ignore_if_missing", "use_recoverable_amount"] = Field(
        "fail", title="Politica ante aforos financieros faltantes")
    require_recoverable_for_default: bool = Field(True, title="Exigir R para C1-C6")

class CmfProvisioningConfig(NikodymBaseConfig):
    schema_version: str = "1.0.0"
    type: Literal["standard"] = "standard"
    as_of_date_col: str = Field("as_of_date", title="Fecha de calculo")
    portfolio_col: str = Field("cmf_portfolio", title="Cartera CMF")
    category_col: str = Field("cmf_category", title="Categoria CMF")
    days_past_due_col: str = Field("days_past_due", title="Dias de mora")
    product_type_col: str = Field("cmf_product_type", title="Tipo producto CMF")
    matrices: CmfMatrixConfig = Field(default_factory=CmfMatrixConfig, title="Matrices")
    pd_mapping: CmfPdMappingConfig = Field(default_factory=CmfPdMappingConfig, title="PD a PI")
    exposure: CmfExposureConfig = Field(default_factory=CmfExposureConfig, title="Exposicion")
    guarantees: CmfGuaranteeConfig = Field(default_factory=CmfGuaranteeConfig, title="Garantias")
```

**Validaciones de config.**
- `pd_mapping.method="pd_breaks"` exige `pd_breaks` estrictamente crecientes y `len(categories) == len(pd_breaks) + 1`; categorias permitidas dependen de la cartera declarada.
- `pd_mapping.method="provided_cmf_category"` exige que `category_col` exista en el frame para carteras que lo necesiten.
- `matrices.fail_on_unmapped_contingent_type=True` levanta `CmfMappingError` si una fila contingente no calza con ninguna de las ocho filas B-3 verificadas.
- `exposure.allow_negative_exposure=False` rechaza exposiciones directas o contingentes negativas.
- `guarantees.financial_guarantee_policy="use_recoverable_amount"` exige columna `recoverable_amount` validada por usuario; no calcula haircuts no verificados.

**Defaults defendibles.**
- `active_version="cmf_b1_b3_2025_01"` apunta al conjunto compatible con consumo vigente 2025 de `docs/normativa_cmf_parametros.md` §3.
- La matriz B-3 contable esta activa y verificada por default segun `docs/normativa_cmf_parametros.md` §6; los contingentes no-default no se bloquean por diseño, solo fallan si el tipo no puede mapearse.
- `method="provided_cmf_category"` evita mapear PD F1 a categorias regulatorias con cortes inventados.
- `financial_guarantee_policy="fail"` evita aceptar mitigacion con aforos pendientes.
- `rounding="none"` publica el calculo economico exacto; el redondeo contable queda como decision explicita (D-CMF-5).

**Hook diferido en `core.config.schema`.** Al implementar:
- declarar `_PROVISIONING_CMF_CONFIG_CLS`;
- añadir campo `provisioning_cmf` como `Any` en runtime y `CmfProvisioningConfig | None` bajo `TYPE_CHECKING`;
- añadir validator `_valida_provisioning_cmf` que valida con `CmfProvisioningConfig` si el hook esta poblado, o exige JSON canonico determinista si no;
- `nikodym.provisioning.cmf.__init__` puebla el hook y registra `CmfProvisioningStep`;
- `provisioning_cmf` **no** entra a `INFRA_SECTIONS`.

## 6. Contratos de datos (I/O)

**Inputs de `CmfProvisioningStep` via `Study`.**

| dominio | clave | uso |
|---|---|---|
| `data` | `"frame"` | frame validado, etiquetado, particionado; contiene columnas regulatorias y exposicion |
| `data` | `"labels"` | contrato target/status; permite distinguir filas modelables/excluidas si aplica |
| `data` | `"splits"` | particiones y roles; auditoria de poblacion usada |
| `model` | `"raw_pd_frame"` | indice original + `partition`, `target`, `linear_predictor`, `pd_raw` de SDD-08 |

**Columnas minimas por cartera.**

| cartera | columnas requeridas principales |
|---|---|
| `commercial_individual` | `cmf_category` A1-C6; `exposure_amount`; si C1-C6 y no viene categoria final, `recoverable_amount` para calcular `(E-R)/E` |
| `commercial_group_leasing` | `days_past_due`, `leasing_asset_type`, `pvb`, `exposure_amount` |
| `commercial_group_student` | `student_payment_due`, `days_past_due`, `student_loan_type`, `exposure_amount` |
| `commercial_group_generic_factoring` | `days_past_due`, `ptvg_bucket` o `guarantee_value`, `factoring_recourse_type`, `exposure_amount` |
| `consumer` | `days_past_due`, `has_housing_loan_system`, `system_dpd30_last_3m`, `consumer_product_type`, `exposure_amount` |
| `housing` | `days_past_due`, `pvg` o `loan_balance` + `mortgage_guarantee_value`, `exposure_amount`, flags de seguro estatal si aplica |
| contingentes B-3 | `contingent_amount`, `contingent_type`, `is_default`; tipo mapeable a las ocho filas verificadas de `docs/normativa_cmf_parametros.md` §6 |
| avales/fianzas | `aval_coverage_pct`, `aval_rating_scale`, `aval_rating_category` cuando `enable_aval_substitution=True` |

**Output `detail`.** `pandas.DataFrame`, mismo indice que las filas calculadas:
- `portfolio`, `method`, `cmf_category`, `matrix_id`, `matrix_row_id`;
- `direct_exposure_amount`, `contingent_exposure_amount`, `exposure_amount`;
- `pd_source_value`, `pi_percent`, `pdi_percent`, `pe_percent`;
- `provision_amount`;
- `guarantee_treatment`, `ccf_percent`, `warning_codes`;
- `source_reference` y `matrix_version`.

**Output `summary`.** `pandas.DataFrame` agregado por `portfolio`, `method`, `cmf_category`:
- `n_rows`;
- `total_exposure_amount`;
- `total_provision_amount`;
- `weighted_pe_percent = total_provision_amount / total_exposure_amount * 100`;
- `matrix_version`;
- `warning_codes`.

**Invariantes.**
- *No mutacion:* no modifica `data.frame` ni `model.raw_pd_frame`.
- *Alineacion:* `pd_frame.index` debe contener las filas que se calculan o la config debe permitir `pd_mapping.method="provided_cmf_category"` sin PD por fila para matrices puramente regulatorias; default exige trazabilidad PD si el frame fue modelado.
- *Finitud:* exposicion, PI, PDI, PE y provision publicables son finitos y no negativos.
- *Trazabilidad normativa:* cada fila calculada referencia `matrix_id`, `matrix_row_id`, `matrix_version` y fuente.
- *B-3:* si una exposicion contingente no puede mapear a CCF verificado, falla por default; no usa factores por similitud semantica.
- *Categorias:* A1-A6/B1-B4 usan PI/PDI/PE; C1-C6 usan PP.
- *Orden estable:* `detail` preserva orden de `data.frame`; `summary` se ordena por orden canonico de carteras/categorias, no por orden accidental de dict.

## 7. Algoritmos y flujo

**`CmfProvisioningStep.execute(study, rng)` - secuencia canonica.**
1. **Descartar azar.** `del rng`; el motor CMF v1 es determinista.
2. **Leer config.** Resolver `study.config.provisioning_cmf` o `CmfProvisioningConfig()` en invocacion programatica.
3. **Validar prerequisitos CT-1.** Exigir `data.frame`, `data.labels`, `data.splits` y `model.raw_pd_frame`.
4. **Cargar matrices.** `load_cmf_matrices(cfg.matrices)`, validar hash, version, fuentes y estado `VERIFICADO` o `FALTA-DATO` segun politica.
5. **Copias defensivas.** Copiar frame y PD frame; validar indice unico.
6. **Alinear PD.** Unir `pd_column` por indice; registrar filas sin PD si config lo permite.
7. **Validar columnas regulatorias.** Resolver cartera por `portfolio_col`; validar columnas minimas por cartera.
8. **Calcular exposicion.** Directa + contingente convertido por B-3 usando la matriz contable verificada; aplicar override `100%` en incumplimiento; si el tipo contingente no calza con ninguna fila B-3, fallar por default.
9. **Resolver matriz/fila.** Para cada fila, seleccionar matriz por cartera y row key por categoria/tramo/mora/producto/garantia.
10. **Aplicar garantias.** Avales por sustitucion proporcional; garantias reales via PVG/PVB/PTVG; financieras solo con datos verificados o recoverable amount configurado.
11. **Calcular provision.**
    - A1-B4, comercial grupal y consumo: `Provision = E * (PI/100) * (PDI/100)`.
    - Vivienda PVG: `Provision = E * (PE_tabulada/100)` usando la PE publicada por la matriz, no recomputada desde PI/PDI. PI y PDI se conservan como campos auditables y se verifica su coherencia con PE solo con tolerancia.
    - C1-C6: `Provision = E * (PP/100)`.
12. **Construir DTOs.** `CmfProvisionRecord`, `CmfPortfolioSummary`, `CmfProvisionCard`, `CmfProvisionResult`.
13. **Auditar decisiones.** Version normativa, mapping PD, garantias, B-3, rows excluidas, redondeo y warnings.
14. **Publicar artefactos.** Escribir las cinco claves `provides` bajo `"provisioning_cmf"`.

**`CmfProvisioningEngine.calculate(...)` - detalle de resolucion.**
1. Normalizar porcentajes como `Decimal` desde strings de matriz (`"0.04"`, `"90.0"`), no desde literales float.
2. Para cada fila, construir una `CmfLookupKey` con cartera, mora, categoria, producto, tramos PVG/PVB/PTVG y flags de garantia.
3. Buscar fila exacta en `CmfMatrixBundle`. Cualquier ambiguedad o ausencia es `CmfMatrixError`.
4. Calcular provision en precision decimal; convertir a `pandas` al final preservando representacion serializable.
5. Aplicar redondeo solo si `cfg.exposure.rounding != "none"` y registrar politica en la card.

**Alternativas descartadas.**
- *Hardcodear matrices en `engine.py`:* descartado por riesgo regulatorio y porque F3 exige versionar parametros.
- *Usar bytes del PDF como fuente runtime:* descartado; el runtime debe usar datos estructurados versionados y hash, no parsear PDFs.
- *Usar `pd_raw` directamente como PI default:* descartado; confundiria scorecard F1 con el modelo estandar B-1.
- *Mezclar B-3 contable con CCF de capital/APR/Basilea:* descartado; `provisioning.cmf` usa exclusivamente la tabla B-3 contable verificada en `docs/normativa_cmf_parametros.md` §6.
- *Imputar haircuts financieros no localizados:* descartado; se marca FALTA-DATO y se falla por default.

**Complejidad / rendimiento.** El calculo es O(n) sobre filas con lookups O(1) en matrices indexadas. El costo dominante es pandas/Decimal; para volumen alto se puede vectorizar por grupos de lookup en B15.4, manteniendo resultados bit-identicos contra el motor fila-a-fila de referencia.

## 8. Casos borde y manejo de errores

- **Falta `data.frame` o `model.raw_pd_frame`:** `ArtifactNotFoundError` por CT-1.
- **Frame sin columnas regulatorias requeridas:** `CmfInputError` listando cartera, columnas faltantes y primera fila afectada.
- **Indice duplicado:** `CmfInputError`; no se permite alinear PD/exposicion de forma ambigua.
- **PD fuera de `[0,1]` o no finita:** `CmfInputError`, aunque el default no use PD como PI.
- **Categoria CMF desconocida:** `CmfMappingError` con categoria y cartera.
- **`pd_breaks` incompletos o no monotonomos:** `CmfConfigError`.
- **Exposicion negativa:** `CmfInputError` salvo config explicita no-default.
- **Exposicion cero:** publica provision cero si PI/PDI existen; si C1-C6 requiere `(E-R)/E`, `E=0` levanta `CmfCalculationError`.
- **C1-C6 sin `recoverable_amount` ni categoria C provista:** `CmfInputError`; no estima recuperacion.
- **Contingente B-3 con tipo no verificado:** `CmfMissingRegulatoryDataError` por default.
- **Garantia financiera sin haircut verificado:** `CmfMissingRegulatoryDataError` por default.
- **Aval con cobertura fuera de `[0,100]`:** `CmfInputError`.
- **PDI/PI/PE de matriz no coherentes:** `CmfMatrixError` si `abs(PE - PI*PDI/100)` excede tolerancia configurada; vivienda PVG usa PE tabulada para calcular y esta regla opera solo como verificacion de consistencia; C1-C6 queda excluido porque usa PP.
- **Rounding produce diferencia material:** registrar `log_decision`; tests comparan pre y post redondeo.

Toda excepcion propia desciende de `NikodymError`; mensajes en español e incluyen cartera, regla normativa, version de matriz y valor observado.

## 9. Reproducibilidad y auditoría

- **Componentes estocasticos.** Ninguno. `CmfProvisioningStep.execute(study, rng)` recibe `rng` por contrato y debe hacer `del rng`.
- **Determinismo esperado.** `(data_hash + config_hash + matrix_bundle.sha256 + model.raw_pd_frame + uv.lock) -> detalle, summary, card y term_structure identicos`.
- **Datos normativos versionados.** `CmfMatrixManifest` registra: version, fecha de vigencia, fecha de extraccion, fuentes oficiales, `docs/normativa_cmf_parametros.md` section refs, hash sha256 del YAML canonico, autor/verificador y estado (`verified`, `pending_reconciliation`, `deprecated`).
- **Audit trail (`log_decision`).** Registrar:
  - version de matrices y hash;
  - politica PD->PI y fuente PD usada;
  - conteo por cartera/categoria;
  - contingentes B-3 convertidos y override `100%` por incumplimiento;
  - garantias aplicadas, omitidas o fallidas;
  - filas excluidas y razon;
  - redondeo aplicado;
  - cualquier `FALTA-DATO` permitido por config no-default.
- **Model card / report.** `CmfProvisionCard` debe exponer total provision, exposicion, PE ponderada, fuentes regulatorias, version normativa y warnings. `metric_sections` queda como puerta CT-2 para futuros desgloses por stage, escenario o term-structure sin romper SDD-17.
- **Lineage.** `provisioning_cmf` no completa `data_hash`; lo consume desde SDD-02. Su aporte al lineage son `matrix_bundle.sha256`, config computacional y decisiones auditadas.
- **Vigilancia regulatoria.** Antes de release productivo F3, se debe revalidar `matrix_bundle` contra el PDF vigente del CNC en cmfchile.cl y contra `docs/normativa_cmf_parametros.md`. Si hay cambio normativo, se crea una nueva version de matrices y se depreca la anterior.

## 10. Dependencias

**Internas.**
- SDD-01 (`core`): `Step`, `ArtifactKey`, `ArtifactStore`, `AuditableMixin`, `NikodymError`, `MissingDependencyError`, lineage y `config_hash`.
- SDD-02 (`data`): `frame`, `labels`, `splits`, `data_hash`, target/particiones y validacion de esquema.
- SDD-05: `NikodymBaseConfig`, hooks diferidos, `INFRA_SECTIONS`, round-trip YAML.
- SDD-08 (`model`): `raw_pd_frame` con `pd_raw`, `linear_predictor`, `partition`, `target`.
- SDD-03/26 (aguas abajo): governance/report consumen `CmfProvisionCard`.

**Aguas abajo.**
- SDD-16 (`provisioning/ifrs9`) podra comparar metodologia IFRS 9 contra `CmfProvisionResult.term_structure()`.
- SDD-17 (`provisioning`) aplica el maximo entre CMF e IFRS 9 y publica provision final.
- SDD-22 (`validation`) usa detalle/summary para backtesting regulatorio.
- SDD-23 (`ui`) edita config y muestra brechas `FALTA-DATO`.
- SDD-26 (`report`) presenta card, detalle y fuentes.

**Externas.**

| Dependencia | Version / fuente | Licencia | Uso | Distribucion |
|---|---|---|---|---|
| pandas | `>=2.0` | BSD-3 ✅ | frames de entrada/salida, agregaciones | base |
| pydantic | `>=2` | MIT ✅ | DTOs/config frozen | base |
| PyYAML / yaml parser actual del core | segun SDD-05 | MIT/permisiva ✅ | cargar datos versionados si no se usa JSON | base existente |
| decimal (stdlib) | Python | PSF ✅ | calculo auditado de porcentajes/montos | stdlib |

**Nucleo liviano.** `nikodym.core` no importa `nikodym.provisioning`. `import nikodym.provisioning.cmf` puede registrar config/step y cargar metadatos livianos, pero no debe leer matrices completas ni importar pandas pesado hasta `load_cmf_matrices()` o `execute()`, salvo que pandas ya sea base en el entorno `data`.

## 11. Estrategia de tests

Marco transversal en SDD-24. Casos especificos:

- **Matrices versionadas.** `manifest.sha256` fijo; parser rechaza YAML modificado; cada `matrix_id` tiene fuente, vigencia y estado. Test de coherencia `PE = PI*PDI/100` para A1-B4, comercial grupal y consumo; vivienda PVG se calcula con PE tabulada y verifica coherencia con PI/PDI solo con tolerancia; C1-C6 se valida contra PP.
- **Goldens comercial individual.** A1 con exposicion `1.000.000` produce provision `360` (`0,04% * 90,0% = 0,036%`), fuente `docs/normativa_cmf_parametros.md` §1.1. B4 con exposicion `1.000.000` produce `438.750` (`43,875%`), misma fuente.
- **Goldens incumplimiento C.** E=`1.000`, R=`750` -> tasa perdida `25%`, categoria C3, PP `25%`, provision `250`; fuente `docs/normativa_cmf_parametros.md` §1.3.
- **Goldens consumo 2025.** Sin hipotecario, sin mora sistema, mora `0 a 7`, producto `creditos_en_cuotas`: PI `6,6%`, PDI `56,6%`; E=`100.000` -> provision `3.735,6`; fuente `docs/normativa_cmf_parametros.md` §3.
- **Goldens vivienda PVG.** PVG `>90%`, mora `60-89`, E=`100.000`: PE `24,2355%`, provision `24.235,5`; fuente `docs/normativa_cmf_parametros.md` §4.
- **Goldens comercial grupal.** Generica sin garantia, mora `0`, E=`100.000`: PI `4,91%`, PDI `56,9%`, provision `2.793,79`; fuente `docs/normativa_cmf_parametros.md` §2.c.
- **B-3 contable verificado.** Tests para las ocho filas reales: a=`100%`, b=`20%`, c=`20%`, d=`50%`, e=`35%`, f-CAE=`15%`, f-otros=`100%`, g=`100%`; override incumplimiento `100%` se prueba como regla verificada. Tipo contingente no mapeado levanta `CmfMappingError`.
- **Avales.** Cobertura `40%` con aval A1 reduce/sustituye solo el tramo avalado y deja el resto con PI/PDI del deudor; prueba contra formulas de `docs/normativa_cmf_parametros.md` §2.d y tabla §5.2.
- **Garantia financiera faltante.** Fila que requiere haircut financiero sin `recoverable_amount` levanta `CmfMissingRegulatoryDataError`.
- **No mutacion.** Snapshots profundos de `data.frame` y `model.raw_pd_frame` permanecen iguales tras `execute`.
- **Contratos CT-1.** Falta `model.raw_pd_frame` -> `ArtifactNotFoundError`; falta columna regulatoria -> `CmfInputError`.
- **Config.** Round-trip YAML; cambiar `active_version`, `pd_mapping.method`, `pd_breaks`, `financial_guarantee_policy` o `rounding` cambia `config_hash`.
- **Reproducibilidad.** Dos corridas con mismo frame, PD frame, config y matrices producen `detail`, `summary`, `card` y `term_structure()` byte-equivalentes.
- **Import liviano.** `import nikodym.core` no importa `nikodym.provisioning`; `import nikodym.provisioning.cmf` no carga matrices completas hasta pedirlas.
- **Cobertura regulatoria 100%.** `src/nikodym/provisioning/cmf/**` debe quedar en el grupo de cobertura 100% junto con los modulos regulatorios ya definidos.

Fixtures: `cmf_small_exposures.parquet` sintetico sin datos reales, `raw_pd_frame` sintetico de SDD-08, matriz YAML canonica minima con todas las filas verificadas, `InMemoryAuditSink` y casos por cartera.

## 12. Decisiones abiertas y riesgos

**Riesgos.**
- **Parametro regulatorio desactualizado.** Mitigacion: matrices como datos versionados con hash/fuente, tests por matriz y vigilancia regulatoria antes de release.
- **Confundir PD de scorecard con PI regulatoria.** Mitigacion: default exige categoria/tramo o mapping explicito; `pd_raw` queda auditado, no sustituye parametros B-1 por defecto.
- **Confundir CCF contables B-3 con CCF de capital/APR/Basilea.** Mitigacion: matriz `contingent_b3_v2016` separada, fuentes explicitas de `docs/normativa_cmf_parametros.md` §6 y tests de las ocho filas verificadas.
- **Garantias financieras sin haircuts.** Mitigacion: fail-fast default; no se imputan descuentos.
- **Sobreajuste del diseno a una entidad.** Mitigacion: columnas configurables y datos normativos separados del motor; defaults conservadores.
- **Rendimiento con Decimal.** Mitigacion: motor de referencia decimal para goldens; vectorizacion por grupos si el volumen lo exige, con tests de equivalencia.
- **Reporte de resultados incompletos como definitivos.** Mitigacion: `CmfProvisionCard` expone warnings y fuentes; SDD-17/report deben mostrar `FALTA-DATO` de forma visible.

**Fuentes verificadas / citas.**
- **docs/normativa_cmf_parametros.md** Advertencias, §§1-7: fuente primaria interna de numeros para B-1/B-3 recopilados, verificados visualmente 2026-06-23, con pendientes explicitos.
- **ROADMAP.md** F3: motor B-1, matrices por cartera como datos versionados, contingentes B-3, avales y garantias.
- **SDD-02 (`data`)**: `frame`, `labels`, `splits`, `data_hash`, frontera datos transversales.
- **SDD-08 (`model`)**: `raw_pd_frame` con `pd_raw`; etiqueta de PD cruda no calibrada.
- **_CONTRATOS-TRANSVERSALES.md** CT-1 (`requires`/`provides`), CT-2 (`ProvisionResultLike.term_structure()`), CT-4 (core liviano).
- **CNC CMF Capitulo B-1**: provisiones por riesgo de credito, categorias A1-C6, matrices comercial/grupal/consumo/vivienda, garantias.
- **CNC CMF Capitulo B-3**: creditos contingentes y factores de conversion contables para provisiones, segun tabla verificada en `docs/normativa_cmf_parametros.md` §6.
- **Circular CMF 2.346/2024**: modelo estandar consumo vigente desde cierre contable enero 2025.

## Decisiones para revision de Cami

- **D-CMF-1 - Dominio y clave de config `provisioning_cmf`.** Recomendacion: usar dominio plano `"provisioning_cmf"` para evitar ambiguedad con SDD-17 (`provisioning`) y con IFRS 9. Confirmar si Cami prefiere config anidado futuro `provisioning.cmf`.
- **D-CMF-2 - Fuente default de PD para mapeo PI.** Recomendacion conservadora: default `model.raw_pd_frame.pd_raw` solo como insumo trazable; PI regulatoria sale de matrices/categorias. Si Cami quiere PD calibrada de SDD-10 como default, cambiar dependencia/orden a `calibration.calibrated_pd_frame`.
- **D-CMF-3 - Cortes PD -> categorias CMF.** No hay cortes regulatorios recopilados para convertir PD continua F1 a A1-B4/C. Recomendacion: no hardcodear; exigir `pd_breaks` configurados por usuario o columna `cmf_category` provista. FALTA-DATO si se pretendia un mapping estandar Nikodym.
- **D-CMF-4 - Revalidar B-3 antes del release F3.** La tabla B-3 contable queda activa por default con los factores verificados de `docs/normativa_cmf_parametros.md` §6. Recomendacion: antes del release F3, revalidar la tabla completa contra el PDF vigente del Compendio y, si la norma cambio, emitir una nueva matriz `contingent_b3_vYYYY_MM` versionada.
- **D-CMF-5 - Redondeo contable.** Recomendacion: calcular y auditar sin redondeo (`rounding="none"`) y dejar redondeo de moneda como opcion explicita. Cami decide si v1 debe redondear a pesos/centavos por defecto.
- **D-CMF-6 - Haircuts de garantias financieras.** `docs/normativa_cmf_parametros.md` marca aforos/haircuts como pendiente. Recomendacion: fail-fast por default y permitir solo `recoverable_amount` provisto/auditado por el usuario hasta localizar la circular especifica.
- **D-CMF-7 - Uso de C1-C6.** Recomendacion: si el usuario entrega `cmf_category=C1..C6`, aplicar PP directamente; si no entrega categoria, exigir `recoverable_amount` para encasillar por `(E-R)/E`. Confirmar si se permitira categoria provista sin recalculo de R.
- **D-CMF-8 - Alcance de matrices en el primer commit funcional.** Recomendacion: implementar todas las matrices B-1 verificadas y la tabla B-3 contable verificada en B15.1. Alternativa no recomendada: liberar F3 sin contingentes; debilita el DoD del roadmap.
