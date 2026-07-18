# SDD-24 — Estrategia de testing (transversal: harness de contrato, batería Nikodym, reproducibilidad, canónicos numéricos)

| Campo | Valor |
|---|---|
| **SDD** | 24 |
| **Módulo** | Transversal (`tests/` + utilidades de test reusables en `nikodym.testing`). No produce código de producción de dominio. |
| **Fase** | F0 |
| **Tanda de producción** | T1 (Fundación) |
| **Estado** | Aprobado |
| **Depende de** | SDD-01 (`core`), SDD-05 (convenciones + config) |
| **Lo consumen** | Los SDD de dominio que aportan estimadores/familias propias (02, 06–22): cada uno aplica el harness y la batería que aquí se definen. SDD-25 (packaging/CI) invoca esta suite. SDD-26 (`report`) **no** es estimador ni familia propia: usa utilidades genéricas y su batería específica de render/export, no el harness de estimadores. |
| **Autor / Fecha** | DanIA (fan-out Tanda 1) / 2026-06-23 · rev. **Tanda 1 Rev** 2026-06-24 |

---

## 1. Propósito y responsabilidad

**Qué resuelve (una frase).** Define la **estrategia de testing única y obligatoria** de toda la librería: cómo se organiza `tests/`, qué *harness de contrato* valida cada estimador (el de sklearn para los que multiheredan `BaseEstimator`, y la **batería Nikodym equivalente** para las familias propias), cómo se prueban reproducibilidad y los valores numéricos canónicos, y qué *gates* de calidad (cobertura, mypy strict, ruff) debe pasar el CI — para que "calidad ejemplar" (§4 principio 10) sea verificable, no aspiracional.

**Responsabilidad única (qué SÍ hace).**
- Fija la **estructura de `tests/`** (layout, espejo del árbol `src/`, fixtures compartidos en `conftest.py`).
- Define el **harness de contrato sklearn** (`parametrize_with_checks`/`check_estimator`) y **a qué estimadores se aplica** (solo los de dominio que multiheredan `sklearn.base.BaseEstimator`, D-CONV-4).
- Define la **batería de checks Nikodym** (`check_nikodym_estimator`) que sustituye a `check_estimator` en las familias propias (`BaseForecaster`/`BaseSurvivalEstimator`/`BaseProvisionModel`/`BaseECLModel`), enumerando exactamente qué invariantes verifica.
- Define los **tests de reproducibilidad** (mismo seed → mismo output bit a bit) y el manejo del caveat GBDT multihilo.
- Define los **tests numéricos canónicos** (asevera valores conocidos contra fórmulas **citadas** de la spec, sin reescribirlas).
- Define los **tests de propiedad transversales**: cruce unión↔Registry (anti-drift D-CONV-2), determinismo de `config_hash`, naming CMF (linter/test D-CONV-1), y la **estrategia Hypothesis reusable de `NikodymConfig`**.
- Fija los **gates de CI de calidad**: cobertura objetivo, `mypy --strict` sobre API pública, `ruff`.

**Límites explícitos (qué NO hace, y quién lo hace).**
- **No define el pipeline de CI** (jobs, matriz de versiones, build del wheel, `pre-commit`, separación de extras): eso es **SDD-25 (packaging + CI)**. SDD-24 dice *qué tests existen y qué deben verificar*; SDD-25 dice *cómo y dónde se ejecutan*.
- **No reescribe fórmulas ni parámetros normativos**: los **cita** desde `ESPECIFICACIONES.md` y `normativa_cmf_parametros.md` (00-INDICE §Convenciones). El test solo asevera el valor numérico esperado.
- **No define los tests específicos de cada dominio**: cada SDD de dominio (su §11) lista sus casos canónicos propios; SDD-24 da el **marco y las utilidades reusables** que esos tests usan.
- **No redistribuye dependencias de test**: `pytest`/`hypothesis` son `dependency-group` dev/test (PEP 735), **nunca** entran al wheel (ver §10).

---

## 2. Contexto y ubicación en la arquitectura

- **Capa:** Ingeniería (transversal). No cuelga del árbol `src/nikodym/` como dominio: vive en `tests/` y aporta un paquete de utilidades reusables `nikodym.testing` (sí distribuible, ver §10) que los SDD de dominio importan en sus tests.
- **Quién lo invoca:** el CI (SDD-25) corre `pytest` sobre `tests/`. Los autores de cada SDD de dominio importan `nikodym.testing` (estrategias Hypothesis, `check_nikodym_estimator`, fixtures de config) para no duplicar el harness.
- **A quién invoca:** a `core` (SDD-01) — `Study`, `Registry`, `SeedManager`, `config_hash`, excepciones — y al contrato de SDD-05 (convenciones, sub-configs, uniones discriminadas).

```
        SDD-25 (CI) ── ejecuta ──► pytest tests/
                                      │
   tests/  (espejo de src/)           │ importa
   ├─ unit/ · contract/ · numeric/    ▼
   ├─ property/ · repro/        nikodym.testing  (utilidades reusables, distribuible)
   └─ conftest.py                ├─ check_nikodym_estimator()   (batería de familias propias)
                                 ├─ nikodym_config_strategy()   (Hypothesis, reusable)
                                 └─ fixtures de config / golden seeds
                                      │ valida contra
                                      ▼
                          core (SDD-01) + contrato SDD-05
```

**Interacción con el `Study` y el config declarativo.** Los tests construyen `NikodymConfig` (mínimo o desde fixtures YAML), arman un `Study`, lo corren con un `InMemoryAuditSink` (de `core.audit`, sin deps de test) y aseveran sobre `study.results`, `study.artifacts` y la secuencia de `AuditEvent`. La estrategia Hypothesis de config (§5/§11) es la herramienta central de los tests de propiedad.

---

## 3. Conceptos y fundamentos

- **Harness de contrato** — conjunto de checks genéricos que un estimador debe pasar por el solo hecho de seguir el contrato (no por su lógica de dominio). Dos sabores: (a) el **estándar sklearn** (`check_estimator`/`parametrize_with_checks`), aplicable solo a los estimadores que multiheredan `sklearn.base.BaseEstimator` (D-CONV-4, SDD-05 §4.1); (b) la **batería Nikodym** (`check_nikodym_estimator`), equivalente para las familias propias cuyo contrato sklearn no calza (forecasting/survival/provision/ECL).
- **Property-based testing (Hypothesis)** — en vez de ejemplos puntuales, se afirma una **propiedad universal** ("para todo config válido, round-trip preserva igualdad") y la librería genera y *encoge* (shrink) contraejemplos. MPL-2.0 (copyleft débil por archivo) → **solo dev/test, no se redistribuye** (§7 ESPEC, §10 aquí).
- **Test canónico numérico** — asevera un valor de salida **conocido a mano** contra una fórmula que vive en la spec; el test **no** reescribe la fórmula, solo el resultado esperado (p.ej. `PE = 0.05·0.45·1000 = 22.5`). Es la defensa contra el riesgo regulatorio (un número errado).
- **Reproducibilidad bit a bit** — `(datos + config + semilla + uv.lock) → resultado idéntico` (§4 principio 1, SDD-01 §9). El test la verifica corriendo dos veces y comparando bit a bit; el único caveat tolerado es GBDT multihilo, que se marca `xfail` (o se elimina con `strict_determinism=True`).
- **Golden values (valores de oro)** — secuencias/hashes fijos *hardcodeados* en el test que capturan el comportamiento determinista esperado (p.ej. los primeros N enteros de `SeedManager(42).generator_for("binning")`). Detectan regresiones de determinismo.
- **Anti-drift** — propiedad cruzada que detecta que dos fuentes de verdad que deben coincidir se desincronizaron (discriminador `type` de las uniones vs keys del `Registry`, D-CONV-2).

> **Fórmulas / parámetros normativos:** SDD-24 no contiene ninguno propio. Toda fórmula que un test canónico asevera (PE CMF, escalado de scorecard, Vasicek PIT, ECL) **se cita** desde `ESPECIFICACIONES.md` y `normativa_cmf_parametros.md` (§11, §Citas).

---

## 4. API pública (contrato)

> SDD-24 expone una **API de utilidades de test reusables** en `nikodym.testing` (paquete liviano y distribuible, §10) y un **convenio de invocación** de pytest. Firmas ilustrativas; identificadores en inglés técnico (SDD-05 D-CONV-1), docstrings/mensajes en español.

```python
# nikodym/testing/estimator_checks.py
def check_nikodym_estimator(estimator: "BaseNikodymEstimator") -> None:
    """Batería de contrato para familias propias (forecaster/survival/provision/ECL),
    equivalente a check_estimator pero sin exigir herencia de sklearn.base.BaseEstimator
    (D-CONV-4). Levanta AssertionError describiendo la primera invariante violada.
    Lista exacta de checks en §7."""

def all_nikodym_checks() -> "list[tuple[str, Callable[[BaseNikodymEstimator], None]]]":
    """LISTA de (nombre_check, callable) para integrarse con parametrize (un nodo de
    test por check, igual que sklearn.utils.estimator_checks.parametrize_with_checks).
    Cada `callable` RECIBE una instancia del estimador en el cuerpo del test (patrón
    sklearn: el test hace `check(Estimador())` con una instancia FRESCA por check). Que
    `all_nikodym_checks()` no LIGUE ningún estimador concreto —solo enumera (nombre, check)—
    es distinto de que el callable no lo reciba: lo recibe (de ahí el tipo Callable[[BaseNikodymEstimator], None]).
    Devuelve una LISTA (materializada una sola vez) para no regenerar un Iterator al consumirlo dos veces."""

# nikodym/testing/strategies.py  (Hypothesis; import perezoso de hypothesis)
def nikodym_config_strategy(
    *, sections: "list[str] | None" = None, require_data: bool = False,
) -> "SearchStrategy[NikodymConfig]":
    """Estrategia Hypothesis que genera NikodymConfig VÁLIDOS (pasan model_validate).
    Reusable por todos los SDD de dominio. Construye sub-configs con st.builds sobre
    cada modelo Pydantic, respetando ge/le y Literal. `sections` restringe a un subset."""

def discriminated_union_tags() -> "dict[str, list[str]]":
    """Para el test anti-drift: por cada unión discriminada de NIVEL SECCIÓN (componente
    seleccionable por el Registry global, D-CONV-2), los tags `type` declarados en el schema.
    Se cruza con REGISTRY.available(domain) (§11). NO incluye las uniones discriminadas
    ANIDADAS dentro de una sección (p.ej. data.partition.strategy), que se resuelven con un
    factory LOCAL del módulo, no con el Registry global, y por tanto quedan fuera de este cruce."""

# nikodym/testing/fixtures.py  (fixtures programáticas reusables; las @fixture viven en conftest)
def minimal_study() -> "Study": ...                 # Study(NikodymConfig()) construible sin args (DoD F0)
def dummy_step_config() -> "NikodymConfig": ...      # config con un Step dummy registrado para tests
def golden_seed_sequence(name: str, n: int) -> "list[int]": ...  # valores de oro del SeedManager(42)

# nikodym/testing/reproducibility.py
def assert_bitwise_reproducible(run: "Callable[[], Any]", *, normalize: "Callable | None" = None) -> None:
    """Ejecuta `run` dos veces y asevera igualdad BIT A BIT del resultado (DataFrame/ndarray/float).
    `normalize` permite excluir campos no-deterministas legítimos (timestamps del lineage)."""
```

**Convenio de invocación (pytest).** El comando canónico (que SDD-25 cablea en CI) es:

```bash
pytest -q --strict-markers --strict-config \
       --cov=nikodym --cov-report=term-missing --cov-fail-under=90
```

`--strict-markers`/`--strict-config` hacen que un marker o opción no declarada **falle** (no se ignore silenciosamente) — coherente con `extra="forbid"` del config (un typo es error, no warning). Markers propios declarados en `pyproject.toml` (`[tool.pytest.ini_options] markers = [...]`, ver §5): `slow`, `requires_xgboost`, `requires_lightgbm`, `requires_catboost`, `requires_forecasting`, `gbdt_nondeterministic`.

**Ejemplo de uso (extremo a extremo, pseudocódigo):**

```python
# tests/contract/test_binning_contract.py  (estimador de dominio que SÍ multihereda sklearn)
from sklearn.utils.estimator_checks import parametrize_with_checks
from nikodym.binning import WoEBinner

@parametrize_with_checks([WoEBinner()])
def test_woe_binner_sklearn_contract(estimator, check):
    check(estimator)        # corre TODOS los checks de sklearn como nodos de test separados

# tests/contract/test_forecaster_contract.py  (familia propia → batería Nikodym)
import pytest
from nikodym.testing import all_nikodym_checks
from nikodym.forward import ArimaForecaster

# all_nikodym_checks() devuelve una LISTA; se materializa UNA vez (no se re-invoca para values e ids).
_CHECKS = all_nikodym_checks()
@pytest.mark.parametrize("check", [c for _, c in _CHECKS],
                         ids=[name for name, _ in _CHECKS])
def test_forecaster_nikodym_contract(check):
    check(ArimaForecaster())   # el check RECIBE una instancia FRESCA por nodo (patrón sklearn)

# tests/numeric/test_cmf_canonical.py  (canónico numérico; la fórmula la cita la spec)
def test_pe_canonico():
    # PE = PI · PDI · Exposición  (ESPEC §5.4 / normativa_cmf §0; NO se reescribe aquí)
    assert pe(pi=0.05, pdi=0.45, exposicion=1000.0) == pytest.approx(22.5, abs=1e-9)
```

---

## 5. Configuración (schema Pydantic)

**SDD-24 NO aporta una sección de config de dominio a `NikodymConfig`.** Es un módulo dev/CI: su configuración vive en `pyproject.toml` (tooling), no en el config declarativo del experimento. Por tanto **no** hay un `TestingConfig` anidado en `NikodymConfig` (la lista canónica de SDD-05 §5.1 **no** la incluye, y eso es correcto y deliberado: testing no parametriza una corrida del usuario).

Lo que SDD-24 fija es la **configuración de las herramientas de test** en `pyproject.toml`. **Regla de propiedad única (Tanda 1 Rev, C02/C12): SDD-24 es DUEÑO del CONTENIDO** de los bloques `[tool.pytest.ini_options]` y `[tool.coverage.*]` (la tabla `markers`, `filterwarnings`, `fail_under`, `exclude_also`, `minversion`); **SDD-25 los TRANSCRIBE verbatim** en el único `pyproject.toml` y **cabla** los jobs/matriz de CI (incl. el job de cobertura 100% por-módulo). SDD-25 **no** mantiene una copia divergente de la tabla de markers ni del bloque de coverage (dos copias del mismo TOML se desincronizan; con `--strict-markers` un marker no declarado FALLA la colección). El contrato de contenido es éste:

```toml
[tool.pytest.ini_options]
minversion = "8.0"
testpaths = ["tests"]
addopts = "--strict-markers --strict-config -ra"
markers = [
  "slow: test lento, excluible en el loop rápido",
  "requires_xgboost: requiere el extra [xgboost]",
  "requires_lightgbm: requiere el extra [lightgbm]",
  "requires_catboost: requiere el extra [catboost]",
  "requires_forecasting: requiere el extra [forecasting]",
  "gbdt_nondeterministic: reproducibilidad no garantizada (GBDT multihilo)",
]
filterwarnings = ["error"]   # un warning no manejado FALLA el test (proyecto regulatorio)

[tool.coverage.run]
branch = true
source = ["nikodym"]

[tool.coverage.report]
fail_under = 90            # gate de cobertura GLOBAL (ver §11). El 100% por-módulo de código
                          #   regulatorio NO es expresable aquí (coverage.report no soporta
                          #   umbrales por-path nativamente) → se materializa con jobs de CI
                          #   separados, delegado a SDD-25 (ver §11).
exclude_also = ["if TYPE_CHECKING:", "raise NotImplementedError", "^\\s*\\.\\.\\.\\s*$"]
                          # el patrón de Ellipsis va ANCLADO (^...$): excluye una línea que es SOLO '...'
                          #   (stub de Protocol/overload), no un '...' incrustado en otra expresión.
```

> **Decisión (D-TEST-1):** `filterwarnings = ["error"]` global. Un `DeprecationWarning` de una dependencia o un `RuntimeWarning` numérico **rompen el build**; los warnings legítimos se *allowlistean* explícitamente por test con `@pytest.mark.filterwarnings("ignore::...")`. Coherente con la cultura "un número errado es riesgo regulatorio" (§4 principio 11): no se silencian señales por omisión.

La estrategia Hypothesis **sí** se configura (perfiles), pero vía `settings`, no vía `NikodymConfig` (ver §9).

---

## 6. Contratos de datos (I/O)

**Estructura de `tests/` (layout, espejo del árbol `src/`).**

```
tests/
├── conftest.py              # fixtures raíz: minimal_config, minimal_study, in_memory_sink,
│                            #   synthetic_dataset, dummy_step, golden_seeds, hyp profiles
├── data/                    # datasets sintéticos deterministas (parquet/csv pequeños, versionados)
│   └── synthetic_behavior.parquet
├── configs/                 # fixtures YAML de config (round-trip, integración)
│   ├── minimo.yaml
│   ├── scorecard_completo.yaml
│   └── con_provisioning.yaml
├── unit/                    # tests unitarios por módulo (espejo de src/nikodym/<modulo>/)
│   ├── core/  ├── binning/  ├── provisioning/  └── ...
├── contract/                # harness: sklearn (check_estimator) + batería Nikodym
│   ├── test_sklearn_contract.py      # parametrize_with_checks sobre TODOS los estimadores sklearn
│   └── test_nikodym_contract.py      # check_nikodym_estimator sobre familias propias
├── numeric/                 # canónicos numéricos (PE, scorecard, Vasicek, ECL) — valores de oro
├── property/                # Hypothesis: round-trip config, config_hash, anti-drift, naming CMF
├── repro/                   # reproducibilidad bit a bit + caveat GBDT
└── integration/             # Study.run() end-to-end por pipeline (scorecard, provisioning)
```

**Input de los tests.** Fixtures: `NikodymConfig` mínimo (programático) y completos (YAML en `configs/`); datasets sintéticos deterministas (`data/`, generados con seed fija y *commiteados* — nunca datos reales, `.gitignore` los veta por defecto). Estrategias Hypothesis para inputs generados.

**Output.** Resultado de pytest (pass/fail por nodo), reporte de cobertura (`--cov`), y artefactos de CI (SDD-25): junit XML opcional. Los tests **no** producen artefactos de dominio persistentes salvo en `tmp_path` (fixture pytest, verificado context7: directorio `pathlib.Path` único por test, auto-limpiado).

**Invariantes que esta estrategia impone (verificables sobre la suite misma).**
- Todo estimador de dominio que multihereda `BaseEstimator` tiene **al menos un** test en `contract/` que lo pasa por `parametrize_with_checks`.
- Toda familia propia tiene **al menos un** test que la pasa por `check_nikodym_estimator`.
- Todo discriminador `type` de toda unión **de nivel sección** ∈ `REGISTRY.available(domain)` (test anti-drift; si falla, hay drift D-CONV-2). Las uniones anidadas (factory local) no entran en este cruce.
- Ningún identificador `pd`/`lgd`/`ead` en `provisioning/cmf` (test/linter de naming).
- `config_hash` estable bajo reordenamiento de claves y versión de PyYAML.

---

## 7. Algoritmos y flujo

> Pseudocódigo de alto nivel de cada familia de tests. El detalle de cada caso de dominio vive en el §11 del SDD respectivo.

### 7.1 Harness de contrato sklearn (estimadores de dominio)

Para cada estimador que multihereda `sklearn.base.BaseEstimator` (D-CONV-4): `parametrize_with_checks([Est()])` genera **un nodo de test por check** de sklearn (`check` recibido como callable; verificado context7 — patrón `@parametrize_with_checks`). Cubre: `clone` sin efectos, `get_params`/`set_params` consistentes, sin lógica en `__init__`, atributos `_` solo tras `fit`, `NotFittedError` antes de `fit`, idempotencia de `fit`. **No** se corre sobre las bases de `core` (que no heredan sklearn; SDD-01 §12, en sklearn ≥1.6 los tags exigen `BaseEstimator`). **Checks que un estimador legítimamente no puede pasar** (p.ej. un GBDT multihilo y un check de determinismo estricto) se declaran con `expected_failed_checks={<check>: <razón>}` de `parametrize_with_checks` (sklearn ≥1.6), **no** se silencian relajando la batería — el check sigue corriendo y se marca *xfail* con su razón.

### 7.2 Batería Nikodym (`check_nikodym_estimator`) — familias propias

Sustituto exacto para `BaseForecaster`/`BaseSurvivalEstimator`/`BaseProvisionModel`/`BaseECLModel` (D-CONV-4). **Lista cerrada de checks** (cada uno es un sub-test independiente vía `all_nikodym_checks`):

1. **`check_no_logic_in_init`** — instanciar con params arbitrarios válidos **no** lee datos, no abre ficheros, no fija atributos `_`. Tras `__init__`, `vars(est)` == solo los params públicos (SDD-05 regla dura 1).
2. **`check_get_params_mirrors_config`** — `set(est.get_params(deep=False).keys())` == `set(campos del sub-config <Dominio>Config) − {"type"}` (invariante params==campos del sub-config, SDD-05 §6). Excluye, del lado del sub-config, el **campo discriminador `type`** (`Literal` que selecciona la variante de la unión, no un hiperparámetro del `__init__`); y, del lado del estimador, `_audit` (no es hiperparámetro, SDD-01 §4).
3. **`check_set_params_roundtrip`** — `clone`/`set_params(**get_params())` reconstruye un estimador equivalente; clave inexistente → **`ValueError` propio de `BaseNikodymEstimator`** (NO el `ValueError` de sklearn; D-CORE-1), **o `ConfigError`** donde el loader de config lo envuelva (SDD-01 §4: «clave inexistente → `ValueError` propio → `ConfigError`»; SDD-05 §8). El check llama `set_params` directo sobre el estimador, por lo que acepta el `ValueError` propio **o** su envoltura `ConfigError` (`pytest.raises((ValueError, ConfigError))` con verificación de que la clase del `ValueError` es la de `core.exceptions`/base, no la de sklearn).
4. **`check_not_fitted_raises`** — llamar al método de salida (`predict`/`compute`/`predict_survival_function`) **antes** de `fit`/`compute` levanta `NotFittedError` (propio, `core.exceptions`). El check asevera **`isinstance(exc, core.exceptions.NotFittedError)`** (no identidad de tipo exacta): así cubre también la subclase dual local `NotFittedError(NikodymError, sklearn.exceptions.NotFittedError)` que un estimador sklearn-compat puede definir para capturar ambas jerarquías (D-CORE-5, SDD-01 §4) — porque hereda del `NotFittedError` de `core`. Verifica que `_check_fitted()` está cableado.
5. **`check_fitted_attrs_suffix`** — tras `fit`/`compute` existe **≥1** atributo con sufijo `_` (`coef_`, `cutoff_`, `componentes_`, …) y **no** existía antes (SDD-05 regla dura 3).
6. **`check_from_config_roundtrip`** — `cls.from_config(sub_cfg)` produce un estimador cuyo `get_params()` reproduce los campos de `sub_cfg` (params espejo; SDD-01 §4). `from_config(sub_config_de(est)) ≈ est`.
7. **`check_validate_config`** — `_validate_config()` reconstruye el sub-config desde `get_params()` y re-valida; con un param fuera de rango (violando `ge/le`) levanta `ConfigError` en `fit`/`compute`, **nunca** en `__init__`.
8. **`check_audit_default_null`** — sin sink inyectado, `est._audit` es `NullAuditSink` (no `None`); `log_decision(...)` no rompe (SDD-05 regla dura 5). Tras `clone()` cae al `NullAuditSink` de clase.
9. **`check_reproducible`** — `fit`/`compute` dos veces con el **mismo `Generator` re-derivado** (`SeedManager(seed).generator_for(name)`) produce salida bit-idéntica (familias propias deterministas; GBDT no aplica aquí, son `NikodymClassifier` sklearn-compat).

`check_nikodym_estimator(est)` corre los 9 en orden y levanta `AssertionError` con la regla violada (mensaje en español, incluyendo el valor observado — §4 principio 2).

> **Decisión (D-TEST-2):** la batería Nikodym es una **lista cerrada y versionada** (no "lo que se le ocurra a cada autor"). Añadir un check es un cambio a SDD-24, no a un test suelto — garantiza que las 4 familias propias se midan con la misma vara, igual que `check_estimator` unifica a los sklearn-compat. *Alternativa descartada:* dejar que cada familia defina sus checks ad-hoc (drift de calidad, lo que SDD-05/24 existen para evitar).

### 7.3 Reproducibilidad (mismo seed → mismo output bit a bit)

```
para cada pipeline canónico (scorecard, provisioning, survival):
  s1 = Study(config, seed=42).run();  s2 = Study(config, seed=42).run()
  assert_bitwise_reproducible: s1.results == s2.results  (DataFrame.equals, ndarray bit a bit,
                               float por igualdad exacta — NO approx en repro)
  normalize() excluye run_context timestamps y created_at del lineage (no-deterministas legítimos)
```

- **Seeding determinista** (golden values): `SeedManager(42).generator_for("binning")` genera una secuencia fija *hardcodeada*; reordenar los pasos del config **no** cambia esa secuencia (valida la derivación por **nombre**, no posicional — SDD-01 §7). `int_seed_for(name)` estable entre procesos (usa `hashlib`, no `hash()` builtin — SDD-01 §9).
- **Re-ejecución desde `Study` recargado** = bit-idéntica (valida que el azar **no** se serializa: se re-deriva de `[root_seed, hash(nombre)]`).
- **Caveat GBDT multihilo:** los tests de reproducibilidad de XGBoost/LightGBM/CatBoost multihilo se marcan `@pytest.mark.xfail(reason="GBDT multihilo no determinista", strict=False)` **o** se corren con `strict_determinism=True` (single-thread) donde se exige bit-exactitud. `strict=False`: si algún día son deterministas, no rompe (verificado context7: `pytest.param(..., marks=pytest.mark.xfail)` y `xfail(strict=...)`). El test documenta el caveat, no lo oculta (SDD-01 §9).

### 7.4 Canónicos numéricos (valores conocidos, fórmula citada de la spec)

El test **asevera el resultado**; la fórmula la define la spec y **no se reescribe** (00-INDICE §Convenciones). Casos mínimos obligatorios (cada dominio añade los suyos en su §11):

| Caso canónico | Entrada | Salida esperada | Fórmula (citada, no reescrita) |
|---|---|---|---|
| **PE CMF** | `pi=0.05, pdi=0.45, exp=1000` | `22.5` | `PE = PI · PDI · Exposición` (ESPEC §5.4; normativa_cmf §0/§2) |
| **Invariante fila** | salida de provisión | `PE == PI·PDI·Exposición` fila a fila | mismo (SDD-01 §4 `ProvisionResultLike`) |
| **Escalado scorecard** | `PDO=20` | `Factor = PDO/ln(2) ≈ 28.853900` (oro); e invariante **«doblar las odds suma +PDO=+20 al score»** (`Score(2·odds)−Score(odds)=20`) | `Score = Offset + Factor·ln(odds)`, `Factor=PDO/ln(2)` (ESPEC §5.2 punto 7) |
| **Vasicek PIT** | `PD_TTC=0.02, ρ=0.15, Z∈{0,1,−1}` | `PD_PIT(0)≈0.012953`, `PD_PIT(1)≈0.004052`, `PD_PIT(−1)≈0.035341` (oro); confirma **Z>0 ⇒ PD menor** | `PD_PIT(Z)=Φ[(Φ⁻¹(PD_TTC)−√ρ·Z)/√(1−ρ)]` (ESPEC §5.5) |
| **ECL** | `PD=0.10, LGD=0.45, EAD=1000, EIR=0.05, t=1, w=1` | `ECL ≈ 42.857143` (`= 0.10·0.45·1000/1.05`) (oro) | `ECL = Σ_k w_k·Σ_t PD_marg·LGD·EAD/(1+EIR)^t` (ESPEC §5.5) |
| **Exposición contingente** | `monto·CCF` | `Exposición = monto × factor B-3` | normativa_cmf §6 |

Verificación cruzada del caso PE: en aritmética real `0.05 × 0.45 × 1000 = 22.5`, pero en **IEEE-754** el orden de evaluación `PI·PDI·Exposición` da `22.500000000000004` (no `22.5`), así que un `== 22.5` **fallaría**; por eso el canónico usa `pytest.approx(22.5, abs=1e-9)` (como el ejemplo §4). Los valores de oro de scorecard/Vasicek/ECL se calcularon desde las fórmulas citadas (`Factor=20/ln(2)≈28.853900`; `PD_PIT(0)≈0.012953`, `PD_PIT(1)≈0.004052`, `PD_PIT(−1)≈0.035341`; `ECL≈42.857143`) y son `entrada→salida` aseverables, no solo fórmulas. Para Vasicek se asevera además la **orientación del signo** (Z>0 expansión → PD menor: `0.004052 < 0.012953 < 0.035341`) con esos casos numéricos, porque el signo `−√ρ·Z` es la trampa documentada de la spec (ESPEC §5.5). **Todos** los canónicos numéricos usan `pytest.approx` con `abs`/`rel` explícito (PE incluido: aunque el producto es "exacto" en aritmética real, IEEE-754 no lo es). La **igualdad exacta de floats** se reserva **exclusivamente** para reproducibilidad (§7.3: comparar dos corridas del mismo cómputo → mismo bit-pattern), **no** para comparar un cómputo contra un literal escrito a mano.

### 7.5 Tests de propiedad transversales (Hypothesis)

1. **Round-trip config:** `∀ cfg ∈ nikodym_config_strategy(): load(dump(cfg)) == cfg` (igualdad estructural Pydantic; SDD-05 §6).
2. **`config_hash` determinista:** dos instancias semánticamente iguales (distinto orden de kwargs / versión de PyYAML simulada) → mismo `config_hash`; mutar un campo **computacional** → hash distinto; mutar una sección de **infraestructura** (`name`/`governance`/`audit`/`tracking`/`report` = `INFRA_SECTIONS`) → **mismo** `config_hash` (excluidas por diseño, SDD-01 §5 / SDD-05 §5.5). Estrategia: genera un cfg, lo serializa con claves barajadas, re-valida, compara hash; y un caso que muta solo `tracking`/`report` y verifica hash idéntico.
3. **Anti-drift unión↔Registry (D-CONV-2):** `∀ (domain, tags) ∈ discriminated_union_tags(): set(tags) == set(REGISTRY.available(domain))`. Si una unión declara un `type` que el Registry no tiene (o viceversa), falla. Aplica **solo a las uniones discriminadas de nivel sección** (las que el Registry global resuelve, D-CONV-2); las uniones **anidadas** dentro de una sección (resueltas por un factory local del módulo, p.ej. `data.partition.strategy`) **no** entran en este cruce y se validan localmente en el test del módulo dueño. **Importa `nikodym` completo primero** (fuerza el auto-registro de todos los componentes; SDD-01 §7).
4. **`ArtifactStore`/`Registry` (invariantes):** `get` tras `set` devuelve el mismo objeto; `set` duplicado sin `overwrite` → `ArtifactExistsError`; `resolve(register(X)) == X`; registro duplicado → `DuplicateRegistrationError` (SDD-01 §11).
5. **`Study.load(Study.save(s)) ≈ s`:** reconstruye config, artefactos y un `seed_manager` **equivalente** (mismo `root_seed`, misma derivación; no idéntico en estado interno de `Generator` — SDD-01 §6).

### 7.6 Linter/test de naming CMF (D-CONV-1)

```
para cada archivo .py en src/nikodym/provisioning/cmf/:
  ast.parse → recorrer Name/arg/FunctionDef/AnnAssign/keyword
  prohibidos = {"pd","lgd","ead"}  (como identificador EXACTO, case-insensitive en snake)
  si aparece como nombre de variable/param/campo/atributo  → FALLA listando archivo:línea
  (excepción: "pd" como alias de pandas `import pandas as pd` NO se usa en cmf; si se necesita,
   se permite SOLO el alias de import, nunca un dato. Regla: en cmf los datos son pi/pdi/pe/exposicion.)
simétrico: en src/nikodym/provisioning/ifrs9/ se ESPERA pd/lgd/ead (no pi/pdi/pe como dato).
```

Implementado con `ast` (no regex, para no confundir `pd` substring de `pdo` o comentarios). Es un test pytest (`tests/property/test_naming_cmf.py`) y, opcionalmente, una regla `ruff` custom diferida a SDD-25. *Porqué un test y no solo convención:* "Relajación del naming CMF (PD donde va PI) en T4" es un **riesgo listado** (SDD-05 §12); un test lo hace imposible de mergear.

### 7.7 Estrategia Hypothesis reusable de `NikodymConfig`

`nikodym_config_strategy()` se construye con `st.builds` sobre cada modelo Pydantic de sub-config, respetando `ge/le` (→ `st.integers/floats(min,max)`) y `Literal` (→ `st.sampled_from`), y `st.none() | st.builds(<Sección>Config)` por cada sección opcional (verificado context7: `@st.composite`, `st.from_type`, `st.builds`, `st.sampled_from`). Para las uniones discriminadas, `st.one_of(st.builds(VarianteA), st.builds(VarianteB))` (el `type` lo fija el default `Literal`). Es **reusable**: cada SDD de dominio la importa y la restringe a sus secciones (`sections=[...]`). *Alternativa descartada:* `st.from_type(NikodymConfig)` puro — Pydantic + Hypothesis lo soportan parcialmente, pero genera muchos casos inválidos (rechazados por `model_validator` cross-section) que `assume()` descarta caro; `st.builds` explícito es más rápido y controlable.

---

## 8. Casos borde y manejo de errores

- **Estimador sklearn-compat que NO pasa `check_estimator`:** el test falla con el check concreto de sklearn; es bug del estimador, no del harness. La batería **no** se relaja para que pase.
- **Familia propia que un autor olvidó pasar por `check_nikodym_estimator`:** un **meta-test** (`tests/contract/test_all_families_covered.py`) recorre todas las subclases de las 4 bases propias registradas y verifica que cada una aparece en `contract/`; si falta, falla (cobertura del contrato, no del código). *Restricción:* este meta-test solo "ve" las subclases efectivamente importadas/registradas, así que debe correr en el **job `[all]`** (todos los extras instalados, `import nikodym` completo); en jobs de extra parcial daría un falso "todo cubierto". SDD-25 lo cabla en el job `[all]`.
- **Drift unión↔Registry:** el test anti-drift falla listando el `type` huérfano. Caso borde: un extra no instalado no registra sus componentes → el test corre con `nikodym` + extras de CI presentes; SDD-25 garantiza el job `[all]` donde el cruce es total. En jobs de extra parcial, el test anti-drift se restringe a los dominios cargados (marker `requires_*`).
- **Naming CMF — falso positivo:** `pdo` (points to double odds) contiene `pd` como substring; el test usa `ast` con match **exacto** de identificador, no substring, así que `pdo`/`pdi` no disparan. `import pandas as pd` no debe aparecer en `cmf` (regla: en cmf los datos son `pi/pdi/pe`); si un módulo cmf necesita pandas, importa `import pandas` o usa el alias en un módulo no-cmf.
- **Reproducibilidad rota por dependencia:** si dos corridas difieren y **no** es GBDT, el test falla (no `xfail`) — es regresión real. El `normalize()` solo excluye timestamps/`created_at`; cualquier otra diferencia es bug.
- **Float NaN/inf en canónicos:** se asevera explícitamente (un ECL que da `nan` por un descuento mal formado debe fallar el canónico, no pasar por `approx`).
- **Hypothesis `health check` / flaky:** `settings(deadline=None)` en property tests pesados (evita `DeadlineExceeded` por jitter de CI; verificado context7: `deadline` acepta `None`); `derandomize=True` en el perfil CI para reproducibilidad (verificado context7: `derandomize` es bool). Un `Falsifying example` se reproduce con `@reproduce_failure` (blob, `print_blob=True` por defecto en CI — verificado context7).
- **`tmp_path` y `Study.save`:** los tests de persistencia escriben **solo** en `tmp_path` (nunca en el repo); el test verifica `save`/`load` atómico ahí.

---

## 9. Reproducibilidad y auditoría

- **Componentes estocásticos de los tests** — Hypothesis es el único; se siembra de forma determinista por **perfiles `settings`** registrados en `conftest.py`:
  - perfil `ci`: `settings(derandomize=True, max_examples=200, deadline=None, print_blob=True)` — reproducible y exhaustivo;
  - perfil `dev`: `settings(max_examples=50, deadline=None)` — rápido para el loop local.
  Se selecciona con `HYPOTHESIS_PROFILE` (SDD-25 lo fija en CI). `derandomize=True` hace que el mismo commit genere los mismos casos (verificado context7).
- **Golden values** capturan el determinismo del `SeedManager` y de los canónicos: si una refactor cambia un valor de oro, el diff lo evidencia y exige justificación (es el audit-trail del determinismo). **Oráculos en fichero** (golden DataFrames/series guardados como parquet en `tests/data/`): se comparan en modo **lectura** por defecto; un cambio intencional se regenera con un **flag explícito** (`pytest --update-golden`, una opción declarada en `conftest.py`) que **reescribe** los oráculos y deja el diff en el commit para revisión. Sin el flag, los tests solo **leen** y comparan (nunca regeneran en silencio, que enmascararía una regresión).
- **Qué NO audita SDD-24:** los tests **no** emiten `AuditEvent` de producción; usan `InMemoryAuditSink` (de `core.audit`, sin deps de test — SDD-01 §4) para **aseverar** que el código de producción emitió la secuencia esperada (`run_start → decision → artifact → run_end`).
- **Determinismo de la suite misma** — la suite debe ser determinista (sin `time.time()`, sin `random` sin seed, sin orden de dict no determinista). `filterwarnings=["error"]` + `--strict-markers` blindan contra ruido. Caveat heredado: los tests GBDT multihilo son `xfail` (no determinismo de la **dependencia**, no de la suite).

---

## 10. Dependencias

**Internas:** SDD-01 (`core`: `Study`, `Registry`, `SeedManager`, `config_hash`, `core.exceptions`, `core.audit.InMemoryAuditSink`, bases de estimador), SDD-05 (contrato de convenciones, sub-configs, uniones discriminadas). El paquete `nikodym.testing` importa solo `core` + el dominio bajo test.

**Externas (todas dev/test — NO entran al wheel salvo `nikodym.testing`):**

| Librería | Versión mín. | Licencia | Uso | Distribución |
|---|---|---|---|---|
| pytest | ≥ 8.0 | MIT ✅ | runner, fixtures, `parametrize`, markers, `tmp_path`. Verificado (context7): `pytest.param(..., marks=xfail)`, `tmp_path` (Path único por test), `--strict-markers`, `filterwarnings`. | dev/test |
| hypothesis | ≥ 6.100 | **MPL-2.0** (copyleft débil, scope por archivo) | property-based; `@given`, `st.builds`/`composite`/`sampled_from`/`from_type`, `settings(deadline/derandomize/print_blob)`. Verificado (context7). | **dev/test — NO se redistribuye** (§7 ESPEC) |
| pytest-cov | ≥ 5.0 | MIT ✅ | cobertura (`--cov`, `--cov-fail-under`). Verificado (context7). | dev/test |
| scikit-learn | ≥ 1.6 | BSD ✅ | `sklearn.utils.estimator_checks.parametrize_with_checks`/`check_estimator` para los estimadores sklearn-compat. Verificado (SDD-01/05): en ≥1.6 los tags exigen heredar `BaseEstimator`. | extra del dominio (no de testing) |

> **Nota (job de `contract/` sklearn):** los tests de `tests/contract/test_sklearn_contract.py` **importan `sklearn`**, que llega vía los extras del dominio (no del grupo de test). El job que ejecuta `contract/` requiere esos extras instalados (típicamente `[all]`); en jobs de **extra parcial** sin sklearn, esos tests se *skipean* vía marker `requires_*` (mismo patrón que el anti-drift restringido a dominios cargados, §8). El cableado del job/matriz se **delega a SDD-25**.

> **Decisión (D-TEST-3):** `hypothesis` es **MPL-2.0** (copyleft **débil**, scope por archivo) → permitido **solo** como `dependency-group` dev/test (PEP 735), **nunca** dependencia del wheel distribuido (coherente con §7 ESPEC y el veto a copyleft en lo distribuido). Por eso `pytest`/`hypothesis` no aparecen en `[project.dependencies]` ni en ningún `[project.optional-dependencies]` de usuario (SDD-25 los pone en `[dependency-groups]`).
>
> **`nikodym.testing` SÍ se distribuye** (en el wheel): contiene `check_nikodym_estimator`, `nikodym_config_strategy` y fixtures reusables para que **usuarios** que extiendan la librería (nuevos estimadores de dominio) validen sus componentes con el mismo harness. Pero `nikodym.testing.strategies` importa `hypothesis` de forma **perezosa** (dentro de la función), de modo que importar `nikodym.testing` no arrastra `hypothesis` al runtime del usuario. **Precisión de naming (Tanda 1 Rev):** `hypothesis` vive en un **`dependency-group`** (PEP 735), **no** en un *extra* `[test]` (no existe tal extra; D-TEST-3 lo mantiene fuera de `[project.optional-dependencies]` por su MPL-2.0). Por eso el mensaje del import perezoso es: *"las estrategias Hypothesis requieren `hypothesis` (MPL-2.0): instálalo en tu entorno de test (`pip install hypothesis`) o usa el grupo de desarrollo del proyecto"* — **no** "instala el extra [test]". `check_nikodym_estimator` (sin Hypothesis) funciona con solo `pytest`/`assert`.

**Vetado:** cualquier dependencia de test copyleft fuerte (GPL); `hypothesis` (MPL-2.0) es el límite tolerado y **solo** dev/test.

---

## 11. Estrategia de tests

> Meta-sección: SDD-24 **es** la estrategia de tests. Aquí, los gates de calidad y la matriz de cobertura objetivo que el CI (SDD-25) hace cumplir.

**Gates de CI de calidad (bloqueantes).**
- **Cobertura:** `--cov-fail-under=90` global; **100%** exigido en `core/exceptions.py`, `core/seeding.py`, `provisioning/cmf` y `provisioning/ifrs9` (código regulatorio: un branch no testeado es riesgo). La cobertura de **branch** (`branch=true`) cuenta, no solo de línea. **Cómo se materializa el 100% por-módulo:** `[tool.coverage.report] fail_under = 90` solo impone el gate **global**; el 100% por-módulo se exige con **jobs de CI separados** (p.ej. `pytest --cov=nikodym.core.exceptions --cov=nikodym.core.seeding --cov=nikodym.provisioning.cmf --cov=nikodym.provisioning.ifrs9 --cov-fail-under=100`), cuyo cableado (jobs/matriz) **delega SDD-25**. SDD-24 fija el contrato (qué módulos a 100%); SDD-25 lo ejecuta.
- **Tipado:** `mypy --strict` sobre la **API pública** (lo que un usuario importa: `nikodym/__init__.py`, las clases base, los sub-configs, `nikodym.testing`). El código interno puede relajar `--strict` por módulo si SDD-25 lo justifica, pero la API pública no.
- **Lint/formato:** `ruff check` + `ruff format --check` sin errores; incluye la regla custom de naming CMF (o el test `ast` de §7.6 como respaldo).
- **Suite verde** con `filterwarnings=["error"]` y `--strict-markers`.

**Matriz de cobertura por tipo de test (qué garantiza cada uno).**

| Tipo | Carpeta | Garantiza | Obligatorio en |
|---|---|---|---|
| Contrato sklearn | `contract/` | estimadores sklearn-compat pasan `check_estimator` | binning, model, ml, calibration |
| Batería Nikodym | `contract/` | familias propias pasan los 9 checks (§7.2) | forward, survival, provisioning |
| Canónico numérico | `numeric/` | valores conocidos (PE, scorecard, Vasicek, ECL) | provisioning, scorecard, calibration |
| Reproducibilidad | `repro/` | bit a bit con misma seed; GBDT `xfail` | todo pipeline con estocásticos |
| Propiedad | `property/` | round-trip config, `config_hash`, anti-drift, naming CMF | core, todos los sub-configs |
| Integración | `integration/` | `Study.run()` end-to-end por pipeline | scorecard (F1), provisioning (F3/F4) |

**Fixtures reusables (en `conftest.py` / `nikodym.testing`):** `minimal_config` (`NikodymConfig()` sin args — DoD F0), `minimal_study`, `in_memory_sink` (`InMemoryAuditSink`), `synthetic_dataset` (determinista, seed fija), `dummy_step` (un `Step` que consume su `rng` y escribe un artefacto), `golden_seeds`, perfiles Hypothesis (`ci`/`dev`). Datasets sintéticos en `tests/data/` (versionados, nunca reales — `.gitignore` veta datos por defecto).

**DoD de testing para F0 (lo que esta estrategia debe permitir verificar desde el día 1):** `NikodymConfig()` se crea/serializa/recarga; `SeedManager` reproducible (golden); `config_hash` estable; round-trip YAML; el harness (ambos sabores) corre aunque aún haya pocos estimadores. Esto materializa el DoD F0 (ESPEC §11) por el lado de calidad.

---

## 12. Decisiones abiertas y riesgos

**Decisiones resueltas en este SDD (trazabilidad).**
- **D-TEST-1 — `filterwarnings=["error"]` global.** Un warning no manejado rompe el build; los legítimos se allowlistean por test. *Porqué:* proyecto regulatorio, no se silencian señales (§4 principio 11). *Alternativa descartada:* warnings como ruido tolerado (esconde deprecaciones y `RuntimeWarning` numéricos).
- **D-TEST-2 — La batería Nikodym es una lista cerrada y versionada de 9 checks** (§7.2), no checks ad-hoc por familia. *Porqué:* mide las 4 familias propias con la misma vara, igual que `check_estimator` unifica a los sklearn-compat (D-CONV-4). *Alternativa descartada:* checks por familia (drift de calidad).
- **D-TEST-3 — `hypothesis` (MPL-2.0) solo dev/test, jamás en el wheel;** `nikodym.testing` sí se distribuye pero importa Hypothesis de forma perezosa. *Porqué:* veto a copyleft en lo distribuido (§7 ESPEC); el harness debe estar disponible para extensores sin imponerles MPL en runtime.
- **D-TEST-4 — Naming CMF se verifica por test `ast` (match exacto de identificador), no regex.** *Porqué:* `pdo`/`pdi` contienen `pd` como substring; un regex daría falsos positivos. *Alternativa descartada:* grep/regex (frágil).
- **D-TEST-5 — SDD-24 NO aporta sección de config a `NikodymConfig`.** Es dev/CI; su configuración vive en `pyproject.toml`. (Confirmado contra SDD-05 §5.1: la lista canónica no incluye testing, y es correcto.)

**Decisiones abiertas (delegadas).**
- **Frontera exacta SDD-24 ↔ SDD-25 — RESUELTA (Tanda 1 Rev, C02/C12):** **SDD-24 es dueño del CONTENIDO** de `[tool.pytest.ini_options]` y `[tool.coverage.*]` (tabla `markers`, `filterwarnings`, `fail_under`, `exclude_also` anclado); **SDD-25 lo TRANSCRIBE verbatim** en el único `pyproject.toml` y **cabla** jobs/matriz, incl. el job `--cov-fail-under=100` por-módulo. SDD-25 no mantiene una lista de markers ni un bloque de coverage divergente (C02: con `--strict-markers` divergir rompe la colección). Ver §5.
- **Umbral de cobertura definitivo** (90% global propuesto; ¿95%?). *Responsable:* DanIA (integración) — fijar al cerrar T1.
- **Regla `ruff` custom de naming CMF vs test `ast`** (¿plugin ruff o solo el test?). *Sugerencia:* test `ast` en v1 (cero infraestructura), plugin diferido. *Responsable:* **SDD-25**.
- **`HYPOTHESIS_PROFILE` y `max_examples` en CI** (200 propuesto; coste de CI). *Responsable:* **SDD-25** (presupuesto de tiempo de CI).

**Riesgos.**
- **Falsa sensación de cobertura** (90% de líneas con asserts triviales). *Mitigación:* canónicos numéricos con valores de oro + batería de contrato + 100% en código regulatorio; revisión de integración por DanIA.
- **Drift de la batería Nikodym vs evolución de las bases de `core`** (si SDD-01 añade un invariante y la batería no lo recoge). *Mitigación:* la batería es lista versionada en SDD-24; un cambio a `core.base` exige revisar §7.2.
- **GBDT multihilo enmascarando bugs reales** bajo `xfail`. *Mitigación:* `xfail(strict=False)` + un test paralelo con `strict_determinism=True` que **sí** exige bit-exactitud (separa "no determinismo de la dependencia" de "bug nuestro").
- **Hypothesis lento/flaky en CI** infla el tiempo de build. *Mitigación:* perfiles (`ci` acotado, `deadline=None`, `derandomize=True`); `@settings(max_examples=...)` por test pesado.

---

### Citas

- **ESPECIFICACIONES.md** §4 (principios 1 reproducibilidad, 2 auditabilidad por construcción, 10 calidad ejemplar = marketing, 11 doble verificación de datos externos), §5.2 punto 7 (escalado scorecard `Score=Offset+Factor·ln(odds)`, `Factor=PDO/ln(2)`), §5.4 (`PE=PI·PDI·Exposición`, CMF≠IFRS 9), §5.5 (Vasicek PIT con orientación del signo Z; motor ECL `ECL=Σ_k w_k·Σ_t PD·LGD·EAD/(1+EIR)^t`), §6.1 (clases base propias donde sklearn no calza), §7 (stack y licencias: pytest/ruff/mypy permisivas; **hypothesis MPL-2.0 dev/test, no se redistribuye**; `scikit-survival` GPL vetado), §10 (testing: pytest+hypothesis, reproducibilidad, canónicos Vasicek/ECL/escalado; CI ruff/mypy strict/pre-commit), §11 (DoD F0).
- **normativa_cmf_parametros.md** §0/§2 (`Provisión = Exposición × PI × PDI`), §6 (Exposición contingente = `monto × factor` B-3).
- **00-INDICE.md** §Convenciones (fórmulas/parámetros se **citan**, no se reescriben); SDD-24 depende de 01, 05; lo consumen todos los dominios y SDD-25.
- **SDD-01 (`core`)** §4 (bases de estimador, `from_config`/`_validate_config`/`_check_fitted`, `NullAuditSink`, `InMemoryAuditSink`, `ProvisionResultLike` invariante `PE=PI·PDI·Exposición`), §6 (`Study.load(save())` reconstruye seed_manager equivalente; el azar no se serializa), §7 (auto-registro; seeding por nombre independiente del orden), §9 (`hashlib` no `hash()`; caveat GBDT multihilo; `strict_determinism`), §11 (canónicos seeding/`config_hash`/round-trip), §12 (D-CORE-1 check_estimator solo sobre sklearn-compat; D-CORE-3 identidad por `config_hash`).
- **SDD-05 (convenciones+config)** §4.1 (reglas duras: `__init__` sin lógica, validación en `fit`, atributos `_`, `check_estimator`/batería Nikodym, `log_decision`), §4.4/§5 (naming CMF PI/PDI/PE vs PD/LGD/EAD; D-CONV-1; sub-configs `extra="forbid"`/`frozen`/`title`+`description`/`ge`/`le`/`Literal`), §5.1 (lista canónica de secciones — testing NO está, deliberado), §6 (invariantes universales: `get_params==campos del sub-config`, discriminador ∈ keys Registry), §11 (contrato de tests que SDD-24 operativiza), §12 (D-CONV-2 anti-drift, D-CONV-4 batería Nikodym; riesgo "relajación naming CMF en T4").
- **Verificado vía context7:**
  - **pytest** (`/pytest-dev/pytest`): `pytest.param(value, marks=pytest.mark.xfail)` y `xfail(reason=...)` para casos parametrizados (caveat GBDT); `tmp_path` = `pathlib.Path` único por test, auto-limpiado; `pytest.mark` (`filterwarnings`, `skipif`, `usefixtures`); markers solo aplican a funciones de test, no a fixtures.
  - **hypothesis** (`/hypothesisworks/hypothesis`): `@st.composite` y `draw`; `st.builds`/`st.from_type`/`st.sampled_from`/`st.lists(min_size,max_size)`/`assume()` para construir y filtrar; `settings(deadline=None | timedelta | ms)`, `derandomize` y `print_blob` son bool; `print_blob=True` por defecto en CI; `@reproduce_failure(version, blob)` para replay; `hypothesis.seed` para runs reproducibles.
  - **scikit-learn** (vía SDD-01/05): `parametrize_with_checks`/`check_estimator` exigen heredar `BaseEstimator` en ≥1.6 → solo sobre estimadores de dominio sklearn-compat.
