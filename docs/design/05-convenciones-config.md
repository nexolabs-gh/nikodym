# SDD-05 — Convenciones de API + schema de config global

| Campo | Valor |
|---|---|
| **SDD** | 05 |
| **Módulo** | Transversal (contrato). El schema raíz vive en `nikodym.core.config`; las convenciones aplican a todos los paquetes. |
| **Fase** | F0 |
| **Tanda de producción** | T1 (Fundación) |
| **Estado** | Aprobado |
| **Depende de** | SDD-01 (`core`) |
| **Lo consumen** | Todos los SDD de dominio (02, 06–23), SDD-24 (testing), SDD-23 (UI) |
| **Autor / Fecha** | DanIA (síntesis multi-agente + verificación adversarial, context7) / 2026-06-23 |

---

## 1. Propósito y responsabilidad

**Qué resuelve (una frase).** Fija el **estándar único** de cómo se ve, se nombra, se valida y se serializa la API pública y la configuración de **toda** la librería, para que los 25 módulos sean consistentes, auditables e intercambiables por contrato — y para que la UI sea una proyección automática del config, no código duplicado.

**Responsabilidad única (qué SÍ hace).**
- Define las **convenciones de API** estilo scikit-learn que todo estimador/transformer/motor de Nikodym cumple, y **cuándo** se usan las clases base propias (forecasting/survival/ECL/CMF).
- Define el **contrato del config global**: el árbol Pydantic raíz `NikodymConfig` y su **lista canónica de secciones**, la base común, el patrón de **uniones discriminadas**, los **defaults defendibles** y los **metadatos obligatorios** por campo (que habilitan la UI).
- Define la **política de versionado** del schema (`schema_version`) y de migraciones.
- Define el **contrato de identidad/serialización** (`config_hash`, round-trip YAML) y el de **naming** y **mensajes** (idioma).

**Límites explícitos (qué NO hace, y quién lo hace).**
- **No implementa** infraestructura: el loader/dumper, el `config_hash`, el motor de migraciones, el `Registry`, las clases base y la **jerarquía de excepciones** **viven en `core` (SDD-01)**. SDD-05 dice *qué forma tiene y qué garantías da*; SDD-01 dice *qué código lo carga, valida, versiona, hashea y ejecuta*.
- **No define los sub-configs de cada dominio**: cada SDD (02, 06–23) define el suyo **siguiendo** estas convenciones.
- **No produce el lineage bundle ni el model card**: SDD-05/01 producen el `config_hash` y la serialización; **SDD-03** los consume.
- **No es la especificación de la UI**: el mapa de widgets es **SDD-23**; aquí solo se fija el *contrato de metadatos*.

---

## 2. Contexto y ubicación en la arquitectura

Documento transversal de la capa Fundación: el "manual de estilo ejecutable" del que dependen todos los módulos. Cada estimador concreto hereda de las clases base de `core` (SDD-01) **siguiendo** las reglas de SDD-05, y cada sub-config se anida en `NikodymConfig` **siguiendo** el patrón de composición de SDD-05.

**Relación con el `Study` y el config declarativo.** El config ES el experimento (§4 principio 5): SDD-05 garantiza que sea una sola fuente de verdad, validada, versionada, hasheada y renderizable como formulario. El `Study` (SDD-01) se construye desde un `NikodymConfig` que cumple este contrato.

Frontera (mnemónica): **SDD-05** = "qué forma tiene el config y la API, y qué garantías dan"; **SDD-01** = "qué código las materializa"; **SDD-03** = "qué hace el resto del sistema con ese hash/serialización para auditoría".

---

## 3. Conceptos y fundamentos

- **Patrón scikit-learn** — contrato uniforme `fit`/`transform`/`predict`, `get_params`/`set_params`, sin lógica en `__init__`, validación en `fit`, atributos fiteados con sufijo `_`. La compatibilidad **plena** con el ecosistema sklearn (`Pipeline`, `check_estimator`, `GridSearchCV`) **requiere heredar `sklearn.base.BaseEstimator`** (en sklearn ≥1.6 los tags viven ahí); por eso `check_estimator` se aplica solo a los estimadores de dominio que multiheredan sklearn, **no** a las bases de `core` (D-CORE-1, SDD-01 §12). Verificado contra la guía de desarrollo oficial de sklearn (context7).
- **Clase base propia** — donde el contrato sklearn no calza (§6.1): forecasting (horizonte `fh` + `cutoff_`, patrón sktime), survival (entrada estructurada evento+tiempo), ECL/CMF (salida económica multi-componente vía `compute(...)`). Viven en `core.base` (SDD-01).
- **Unión discriminada (tagged union)** — `Annotated[Union[...], Field(discriminator="type")]`, cada variante con `type: Literal["<key>"]`. Validación temprana, errores accionables (`union_tag_invalid` lista los tags válidos — verificado en Pydantic v2) y render UI condicional. Para los componentes de **nivel sección** (los que el orquestador resuelve), el tag **coincide con la key del `Registry`** → `config → registry → clase` es un único identificador (`type` == `domain.name` del paso, SDD-01 §7). Las uniones **anidadas dentro de una sección** (p.ej. `data.partition.strategy`) se resuelven con un **factory local** del módulo, **no** con el `Registry` global; su `type` da el polimorfismo pero **no** necesita ser key del Registry (el test cruzado union↔Registry de §11 aplica solo a uniones de nivel sección).
- **`config_hash`** — identidad criptográfica: `sha256` del **JSON canónico** del config (claves ordenadas), no del texto YAML ni del `__hash__`. Pieza del lineage bundle (§4 principio 3, §9).
- **`schema_version`** — SemVer del *schema* del config (distinto de la versión del paquete); gobierna la migración de configs guardados.

---

## 4. API pública (contrato de convenciones)

> No es código nuevo: es el **contrato** que la API pública de cada módulo debe cumplir. Las clases base concretas viven en `core` (SDD-01).

**4.1 Esqueleto canónico de un estimador.**

```python
@register("logit", domain="model")             # tag == discriminador del sub-config == name en el Registry
class LogitModel(NikodymClassifier):           # hereda la base apropiada de core.base (§4.2)
    def __init__(self, stepwise="wald", p_value_max=0.05, enforce_sign=True):
        # SOLO asigna params (espejo de los campos del sub-config). NADA de lógica/validación aquí.
        self.stepwise = stepwise
        self.p_value_max = p_value_max
        self.enforce_sign = enforce_sign

    def fit(self, X, y, sample_weight=None) -> "Self":
        self._validate_config()                # heredado de BaseNikodymEstimator: reconstruye el sub-config
        # ... validación de datos y ajuste ...  desde get_params() y lo re-valida (params espejo)
        self.coef_ = ...                        # atributos fiteados: sufijo _
        self.log_decision(regla="signo_beta", umbral=0.0, valor=beta_i, accion="descartar")
        return self

    def predict_proba(self, X): self._check_fitted(); ...
    # from_config(cls, cfg) lo provee BaseNikodymEstimator (mapea campos del sub-config a kwargs); ver SDD-01 §4
```

`from_config`, `_validate_config`, `_check_fitted`, `get_params`/`set_params` son **contrato de la base** (`BaseNikodymEstimator`, SDD-01 §4): el estimador concreto no los reimplementa salvo necesidad. `_validate_config` aprovecha el invariante **params == campos del sub-config**: reconstruye el modelo Pydantic desde `get_params()` y lo valida.

**Reglas duras (compatibilidad sklearn verificada):**
1. `__init__` **solo asigna** params; cada param público es **espejo** de un campo del sub-config Pydantic. Habilita `get_params`/`set_params`/`clone` sin efectos.
2. **Toda validación** (datos y config) ocurre en `fit`/`compute`, nunca en `__init__`.
3. Los **atributos fiteados** llevan **sufijo `_`** (`coef_`, `bins_`, `woe_`, `cutoff_`). `_check_fitted()` levanta `NotFittedError` (propio) antes de `predict`/`transform`/`compute`.
4. **`check_estimator`**: cada estimador de dominio que sigue el contrato sklearn **multihereda `sklearn.base.BaseEstimator`** (sklearn primero en el MRO) y **debe pasar `check_estimator`/`parametrize_with_checks`** en su CI (SDD-24). Las familias propias (forecaster/survival/provision) usan la **batería de checks Nikodym** equivalente (SDD-24).
5. **Auditoría por construcción** (§4 principio 2): toda decisión (descarte, corte, exclusión, umbral gatillado) se registra con `log_decision(regla, umbral, valor, accion)`. `_audit` se inyecta por el orquestador, default `NullAuditSink` (nunca `None`), excluido de `get_params`; tras `clone()`/`check_estimator` cae al `NullAuditSink` de clase (no rompe).

**4.2 Qué base usar (árbol de decisión).**

| Si el componente… | Hereda de (core.base) | Método de salida |
|---|---|---|
| transforma features (binning/WoE/particiones) | `NikodymTransformer` | `transform(X) -> DataFrame` |
| clasifica (logística, wrappers ML: SVM/RF/GBDT) | `NikodymClassifier` | `predict`/`predict_proba` |
| proyecta series con horizonte | `BaseForecaster` | `predict(fh, X) -> Series`; fija `cutoff_` |
| modela survival (lifetime PD) | `BaseSurvivalEstimator` | `predict_survival_function`/`predict_hazard` |
| calcula provisión CMF | `BaseProvisionModel` | `compute(exposures) -> ProvisionResultLike` |
| calcula ECL (IFRS 9) | `BaseECLModel` | `compute(exposures) -> ECLResultLike` |
| **NO es estimador** (splitter de particiones, validador de esquema, reporter) | — (ninguna base de estimador) | contrato funcional propio de su SDD |

> ECL hereda de provisión solo por reutilización del contrato `compute()`; **NO** implica que ECL derive de CMF: son dos motores separados (§5.4), el máximo lo toma SDD-17.

**4.3 Jerarquía de excepciones.** La **raíz `NikodymError`** y las excepciones del **núcleo** viven en `core.exceptions` (SDD-01 §4). **Regla única:** toda excepción **desciende de `NikodymError`**; los módulos de dominio **definen sus propias subclases en su módulo** (no se centraliza cada clase en core). SDD-05 fija su **uso y mensajes**. Resumen del árbol del núcleo:

```
NikodymError ── ConfigError(ConfigVersionError, MigrationNotFoundError), DataValidationError,
                NotFittedError, RegistryError(UnknownComponentError, DuplicateRegistrationError),
                ArtifactNotFoundError, ArtifactExistsError, ReproducibilityError,
                UntrustedStudyError, RegulatoryError
```

**Convención de mensajes:** en **español**, e incluyen la **regla**, el **umbral gatillante** y el **valor** observado (auditabilidad). Ej.: `"Variable 'edad' descartada: |ρ Pearson|=0.83 > umbral 0.80."`.

**4.4 Convención de idioma (naming).**
- **Identificadores** (clases, métodos, params, campos de config): forma **convencional/oficial del término**. Estadística/sklearn/IFRS 9 → **inglés** (`fit`, `transform`, `seed`, `score`, `pd`, `lgd`, `ead`). Términos **regulatorios CMF** → su forma oficial en **español** (`pi`, `pdi`, `pe`, `cartera`, `garantia`). Es "términos técnicos en su forma original" (AGENTS/ESPEC §Idioma, glosario §13).
- **Regla dura (verificable por linter/test en SDD-24):** en `provisioning/cmf` se usa **PI/PDI/PE** (nomenclatura CMF), **no** PD/LGD/EAD; en `provisioning/ifrs9` se usa PD/LGD/EAD. No se relajan en T4.
- **Docstrings, comentarios y mensajes al usuario**: **español** siempre.

---

## 5. Configuración (schema Pydantic global)

**5.1 Base, raíz y lista canónica de secciones** (alojadas en `core.config.schema`, SDD-01; contrato aquí):

```python
class NikodymBaseConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)   # cerrado e inmutable (convención universal)

class NikodymConfig(NikodymBaseConfig):
    # — meta —
    schema_version: str = Field("1.0.0", title="Versión del schema", description="SemVer; gobierna migración.")
    name: str = Field("nikodym-study", title="Nombre del estudio")
    repro: ReproConfig = Field(default_factory=ReproConfig)
    run: RunConfig = Field(default_factory=RunConfig)
    # — pipeline (orden de declaración = orden canónico de pasos; SDD-01 §7) —
    data: "DataConfig | None" = None            # SDD-02
    eda: "EdaConfig | None" = None              # (eda/: tasa de default por período; SDD por confirmar)
    binning: "BinningConfig | None" = None      # SDD-06
    selection: "SelectionConfig | None" = None  # SDD-07
    model: "ModelConfig | None" = None          # SDD-08/12 (unión discriminada; incluye logit y ML)
    tuning: "TuningConfig | None" = None        # SDD-13
    explain: "ExplainConfig | None" = None      # SDD-14
    scorecard: "ScorecardConfig | None" = None  # SDD-09
    calibration: "CalibrationConfig | None" = None  # SDD-10
    provisioning: "ProvisioningConfig | None" = None  # SDD-15/16/17
    forward: "ForwardConfig | None" = None      # SDD-20
    survival: "SurvivalConfig | None" = None    # SDD-18
    markov: "MarkovConfig | None" = None        # SDD-19
    stress: "StressConfig | None" = None        # SDD-21
    performance: "PerformanceConfig | None" = None  # SDD-11
    stability: "StabilityConfig | None" = None  # SDD-11
    validation: "ValidationConfig | None" = None    # SDD-22
    # — infraestructura —
    governance: "GovernanceConfig | None" = None    # SDD-03
    audit: "AuditConfig | None" = None              # SDD-03
    tracking: "TrackingConfig | None" = None        # SDD-04
    report: "ReportConfig | None" = None            # SDD-26 (report, Quarto; T2/F1)

    @model_validator(mode="after")
    def _check_cross_section(self) -> "Self":
        # ejemplo de invariante inter-sección sobre campos DECLARADOS; la regla de negocio
        # "provisioning requiere calibration" la fija SDD-17 (orquestación), citada aquí, no hardcodeada.
        if self.provisioning is not None and self.calibration is None:
            raise ValueError("provisioning requiere una sección 'calibration' (regla de SDD-17).")
        return self
```

> **Ninguna sección es obligatoria a nivel de schema** (todas `| None = None`): un `NikodymConfig()` sin argumentos es construible (DoD F0: "Study mínimo" creable/serializable, SDD-01 §11). El **orquestador** valida en runtime los prerequisitos de cada pipeline (p.ej. un paso de scoring exige `data` y `binning`).

**5.2 Composición + uniones discriminadas** (patrón canónico):

```python
class LogitModelConfig(NikodymBaseConfig):
    type: Literal["logit"] = "logit"                    # == @register("logit", domain="model")
    stepwise: Literal["wald", "lr", "none"] = Field("wald", title="Selección stepwise",
        description="Criterio de entrada/salida de variables.")
    p_value_max: float = Field(0.05, ge=0.0, le=1.0, title="p-valor máximo")
    enforce_sign: bool = Field(True, title="Forzar signo coherente con el riesgo")

class XGBoostModelConfig(NikodymBaseConfig):
    type: Literal["xgboost"] = "xgboost"
    max_depth: int = Field(3, ge=1, le=12, title="Profundidad máxima")
    monotonic: bool = Field(True, title="Restricciones de monotonía")

ModelConfig = Annotated[Union[LogitModelConfig, XGBoostModelConfig], Field(discriminator="type")]
```

**5.3 Defaults defendibles (convención).** `extra="forbid"` (un typo es error, no se ignora — riesgo regulatorio); `frozen=True` (inmutable; evita mutación accidental — **no** vuelve el modelo hashable con campos `list`/`dict` ni congela anidados, por eso la identidad es el `config_hash`, D-CORE-3); **todas las secciones opcionales** (`None`), prerequisitos validados en runtime; numéricos con `ge/le`; categóricos como `Literal`/`Enum`. Cada campo lleva `title` y `description` **obligatorios** (contrato UI, §5.5). *Regla:* preferir tuplas/modelos sobre `list`/`dict` crudos en los sub-configs cuando sea posible.

**5.4 Versionado y migración.** `schema_version` SemVer en la raíz. Al cargar, `core.config` compara contra la versión actual y aplica una cadena **lineal** de migraciones registradas `@migration("1.0.0", "1.1.0")` (funciones puras `dict→dict` que corren **antes** de `model_validate`); si falta un salto → `MigrationNotFoundError`; si la versión es mayor que la del paquete → `ConfigVersionError`. **Caso borde:** un dict crudo sin `schema_version` asume la versión base mínima `"1.0.0"` antes de migrar. **Política v1:** levantar; migradores explícitos después. (Aplica R5 §12 al config.)

**5.5 Identidad, round-trip YAML y UI.**
- **Carga:** `NikodymConfig.model_validate(yaml.safe_load(text))` (tras migración).
- **Identidad (`config_hash`):** `sha256(json.dumps(cfg.model_dump(mode="json", by_alias=True, exclude=INFRA_SECTIONS), sort_keys=True, separators=(",", ":"), ensure_ascii=False))`, con `INFRA_SECTIONS = {"name", "governance", "audit", "tracking", "report"}`. Se hashea el **JSON con claves ordenadas** de las secciones **computacionales** (datos + método + semilla), excluyendo la infraestructura: así el URI de MLflow, la plantilla de reporte o el nombre del estudio no cambian la identidad del experimento (idempotencia del inventario, SDD-03/04). Independiente del estilo/versión de PyYAML y del orden de declaración (mismo experimento → mismo hash entre releases). Base del lineage bundle (SDD-03).
- **YAML legible:** `yaml.safe_dump(cfg.model_dump(mode="json", by_alias=True), sort_keys=False)` (orden de declaración, para revisores). Tanto el YAML como el `config_hash` usan `by_alias=True` (serialización canónica única).
- **Alias (excepcional):** por defecto el nombre del campo es el canónico (Python = YAML = hash = UI), **sin alias**. Se permite un `Field(alias=...)` **solo** para evitar colisión con un nombre reservado o un método de Pydantic (p.ej. campo `schema` ↔ `BaseModel.schema()`): en ese caso el **alias es el nombre canónico** (YAML/hash, vía `by_alias=True`) y se habilita `populate_by_name=True` en ese sub-config para construir también por nombre Python.
- **UI:** la UI Streamlit (SDD-23) se genera desde `NikodymConfig.model_json_schema()` + introspección, sin duplicar lógica (§4 principio 6). Mapeo: `Literal`/`Enum`→selectbox, `bool`→checkbox, numérico con `ge/le`→slider, `str`→text_input; el discriminador controla el render condicional. Metadatos de presentación: `json_schema_extra={"ui_widget":…, "ui_group":…, "ui_order":…}` (contrato aquí; widgets en SDD-23). Preservación de comentarios (ruamel) **diferida** a la UI/CLI.

**5.6 Hydra/OmegaConf.** Capa fina **opcional** (extra `[sweep]`, import perezoso) solo para barridos por CLI: Hydra compone overrides → `dict` → `NikodymConfig.model_validate(dict)`. **Pydantic es siempre el árbitro final**; OmegaConf nunca es fuente de verdad ni dependencia de `core` (§6.2). (Licencias: `hydra-core` MIT, `omegaconf` BSD-3 — sin copyleft, D-LIC.)

---

## 6. Contratos de datos (I/O)

Convenciones universales que todo módulo respeta:
- **Input estándar:** `pandas.DataFrame` (índice = identificador de observación). Polars interno opcional si el volumen lo exige (D-DATA), tras la interfaz de SDD-02.
- **Output de transformers:** `DataFrame` con **columnas nombradas** (no `ndarray` pelado) para trazabilidad.
- **Output económico (provisioning):** `ProvisionResultLike`/`ECLResultLike` (Protocols en `core.results`, SDD-01 §4) con todas las columnas regulatorias; invariante `PE = PI·PDI·Exposición` fila a fila (verificable a mano); provisión final = `max(CMF, IFRS 9)` (§5.4, piso prudencial; lo toma SDD-17).
- **Config:** input YAML/dict → `NikodymConfig` frozen; identidad por `config_hash` (JSON canónico).

**Invariantes universales.** `get_params(self) == campos del sub-config`; post-`fit` existe ≥1 atributo con sufijo `_`; el discriminador `type` de toda unión **de nivel sección** ∈ keys del `Registry` (las uniones **anidadas** se resuelven por factory local y quedan fuera de este cruce, §3); round-trip preserva igualdad de valores y `config_hash` estable bajo reordenamiento de claves y versión de PyYAML.

---

## 7. Algoritmos y flujo

> El código vive en `core` (SDD-01); aquí el flujo que las convenciones implican.

**Carga:** `text → yaml.safe_load → migrate(raw, target) → NikodymConfig.model_validate → instancia frozen`. La validación resuelve cada unión por `type`, corre `field_validator` (intra-campo) y `model_validator(mode="after")` (inter-sección).

**Identidad:** `cfg.model_dump(mode="json") → json.dumps(sort_keys=True) → config_hash = sha256(...)`.

**Resolución de componente (runtime, orquestador SDD-01 §7):** `sección activa → (domain=nombre de sección, name=cfg.<sección>.type) → Registry.resolve(domain, name) → clase → from_config(sub_cfg)` (params espejo; sin lógica en `__init__`; validación en `fit`).

**Barrido CLI (extra):** Hydra compone overrides → `dict` → `model_validate` → un `NikodymConfig` por punto → un `Study`.

**Decisiones algorítmicas y alternativas descartadas:** uniones discriminadas en vez de `dict` interpretado en runtime (falla temprano, no a mitad de pipeline); hash sobre **JSON canónico** en vez de texto YAML (estable cross-version); validación cruzada en `model_validator` en vez de runtime (config inválido no pasa el parse).

---

## 8. Casos borde y manejo de errores

- **Campo desconocido en YAML** (typo) → `ValidationError` (`extra_forbidden`) → `ConfigError`. Nunca silencioso.
- **Discriminador `type` no registrado** → `ValidationError` (`union_tag_invalid`) listando los tags válidos.
- **`schema_version` mayor que el del paquete** → `ConfigVersionError`; **menor sin migración** → `MigrationNotFoundError(from, to)`; **dict sin `schema_version`** → asume `"1.0.0"`.
- **Componente estocástico activo:** `seed=42` por defecto garantiza reproducibilidad; un dominio que exija seed explícita lo valida en su `model_validator`.
- **`provisioning` sin `calibration`** → `ValueError` en `model_validator` → `ConfigError` (regla de SDD-17).
- **Float `NaN`/`inf` en el config** → rechazado por `field_validator` (finitud).
- **Mutar un config frozen** → Pydantic levanta → `ConfigError`.
- **`set_params` con clave inexistente** → `ValueError` **propio de `BaseNikodymEstimator`** (introspección propia, NO de sklearn; coherente con D-CORE-1), envuelto como `ConfigError` donde aplique.

---

## 9. Reproducibilidad y auditoría

- El **`config_hash`** (sha256 del JSON canónico) entra al lineage bundle junto a git SHA + hash de datos + seed + `uv.lock` (lo ensambla SDD-01, lo persiste SDD-03).
- `schema_version` queda en el config serializado → un lineage viejo es re-cargable vía migración.
- `seed` (en `repro`) es la fuente de la propagación determinística (`core.seeding`, derivación por nombre).
- **`log_decision`** es el canal de auditoría por construcción: cada descarte/corte/umbral gatillado se registra (regla, umbral, valor, acción) en español. Las clases base lo ofrecen; cada módulo decide **qué** registra.
- **Determinismo del config:** el `config_hash` por JSON canónico es estable (mismo cfg → mismo hash, independiente de PyYAML y del orden de claves). El determinismo del config no cubre el caveat GBDT multihilo (lo documenta el SDD del modelo).

---

## 10. Dependencias

**Internas:** SDD-01 (`core`: schema raíz, loader, `config_hash`, Registry, base classes, excepciones, seeding, lineage) materializa este contrato. Todos los SDD de dominio aportan su sub-config; SDD-03 consume `config_hash`; SDD-23 consume `model_json_schema()`; SDD-24 consume las estrategias de test de contrato.

**Externas:** las mismas que `core` (pydantic ≥2.5, PyYAML ≥6, numpy — MIT/BSD; ver SDD-01 §10). **Opcional:** `hydra-core` (MIT)/`omegaconf` (BSD-3), extra `[sweep]`, import perezoso; `ruamel.yaml` (MIT) diferido. **Ninguna copyleft** (D-LIC). El patrón sklearn es **convención**, no dependencia de `core`; sklearn es dep de los **extras** de scoring/ML donde los estimadores lo multiheredan para `check_estimator`.

---

## 11. Estrategia de tests

Operativizado por **SDD-24**; el contrato que SDD-05 impone:
- **Contrato sklearn:** cada estimador de dominio que multihereda `BaseEstimator` pasa `parametrize_with_checks([Est()])`/`check_estimator`. Las familias propias usan la batería Nikodym equivalente (no `check_estimator` estándar, que exige heredar `BaseEstimator`).
- **Round-trip config:** `load_config(dump_config(cfg)) == cfg` (igualdad estructural, frozen).
- **`config_hash` determinístico:** dos instancias semánticamente iguales (distinto orden de kwargs, distinta versión de PyYAML) → mismo hash; cambiar un campo → hash distinto.
- **Unión discriminada:** `model_validate({"model": {"type": "logit", …}})` → `LogitModelConfig`; `type` inválido → `ValidationError` con tags esperados.
- **Cruce unión↔Registry (propiedad):** todo discriminador `type` de cualquier unión **de nivel sección** ∈ keys del `Registry` (atrapa drift); las uniones anidadas (factory local) se validan localmente en su módulo, no aquí (§3).
- **Migración:** YAML `1.0.0` con migración a `1.1.0` registrada → carga OK; sin migración → `MigrationNotFoundError`; dict sin versión → asume `1.0.0`.
- **Naming CMF (linter/test):** en `provisioning/cmf` no aparecen identificadores `pd`/`lgd`/`ead` (deben ser `pi`/`pdi`/`pe`).
- **Fixtures:** `configs/minimo.yaml`, `configs/scorecard_completo.yaml`, `configs/con_provisioning.yaml`; estrategia Hypothesis de `NikodymConfig` reutilizable; camino Hydra (`overrides → dict → model_validate`) cubierto (o delegado a SDD-25 si requiere el extra).

---

## 12. Decisiones abiertas y riesgos

**Decisiones resueltas (trazabilidad).**
- **D-CONV-1 — Identificadores en la forma oficial del término** (inglés stats/sklearn/IFRS 9; español regulatorio CMF: PI/PDI/PE), prosa siempre en español. *Alternativa descartada:* todo en español (chocaría con `fit`/`predict` y PD/LGD).
- **D-CONV-2 — Uniones discriminadas con `type` == key del Registry == `domain.name` del paso** como mecanismo único de selección. *Porqué:* validación temprana + un solo identificador config↔código↔orquestador.
- **D-CONV-3 — Identidad por `config_hash` (JSON canónico)**, YAML solo para legibilidad. *Porqué:* hash estable cross-version (PyYAML no interviene); `frozen=True` no basta para identidad (no hashable con campos mutables).
- **D-CONV-4 — `check_estimator` solo a estimadores de dominio que multiheredan `BaseEstimator`**; familias propias con batería Nikodym (SDD-24). *Porqué:* en sklearn ≥1.6 los tags exigen heredar `BaseEstimator`; el duck typing no basta.

**Decisiones abiertas (delegadas).**
- **Alcance de SDD-04 — RESUELTO (checkpoint Cami, 2026-06-23):** SDD-04 = `tracking` (MLflow) en F0/T1; el reporte Quarto pasa a **SDD-26 `report`** en T2/F1 (índice actualizado).
- `json_schema_extra` con claves `ui_*` sueltas vs modelo de metadatos UI tipado. *Sugerencia:* dict `ui_*` en v1. *Responsable:* SDD-05↔SDD-23.
- Forma de la cadena de migraciones (lineal vs grafo). *Sugerencia:* lineal por SemVer en v1.

**Riesgos.**
- **Explosión de tamaño de `NikodymConfig`** (~22 secciones) → UX de la UI. *Mitigación:* `ui_group` + secciones opcionales (`None`).
- **Drift discriminador↔Registry** → test de propiedad cruzado (SDD-24).
- **Relajación del naming CMF** (PD donde va PI) en T4 → linter/test (SDD-24).

---

### Citas

- ESPECIFICACIONES.md §3.3 (D-CFG Pydantic v2 única fuente de verdad; D-LIC sin copyleft), §4 (principios 1, 2, 3, 5, 6, 8, 9), §5.1 (config versionado, round-trip), §5.4 (CMF≠IFRS 9), §6.1/§6.2 (API estilo sklearn; clases base propias; config declarativo; Hydra solo capa fina), §6.3 (árbol), §7 (stack/licencias), §9 (lineage), §13 (glosario PI/PDI/PE), §12 (R5).
- 00-INDICE.md: SDD-05 (depende de 01; lo consumen 23/UI, 24/testing y todos los dominios), §Convenciones.
- SDD-01 (`core`): clases base, `core.config`, `core.exceptions`, `Registry`, `SeedManager`, `LineageBundle`, `config_hash`, decisiones D-CORE-1…5.
- Verificado vía context7: **Pydantic v2** (`Field(discriminator=...)`, `Literal` tags, `union_tag_invalid`, `model_validator(mode="after")→Self`, `ConfigDict(extra="forbid", frozen=True)` — no implica hashabilidad con campos mutables, `model_json_schema`/`json_schema_extra`); **scikit-learn** (`BaseEstimator`, `__init__` sin lógica, atributos `_`; `check_estimator`/`parametrize_with_checks` exigen heredar `BaseEstimator` en ≥1.6); **sktime** (`BaseForecaster` `fit(y,X,fh)`/`predict(fh,X)`/`cutoff`).
