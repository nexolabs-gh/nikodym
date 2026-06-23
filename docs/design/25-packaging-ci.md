# SDD-25 — Packaging + CI (uv, hatchling, extras, gobernanza de licencias)

| Campo | Valor |
|---|---|
| **SDD** | 25 |
| **Módulo** | Infraestructura de proyecto (`pyproject.toml`, `uv.lock`, `.github/`, `.pre-commit-config.yaml`). No es un paquete de `src/nikodym/`. |
| **Fase** | F0 |
| **Tanda de producción** | T1 (Fundación) |
| **Estado** | Aprobado |
| **Depende de** | — (no depende de ningún módulo `nikodym`; define el contenedor del que todos dependen) |
| **Lo consumen** | Todos los SDD (cada dominio declara su extra y sus deps aquí); en especial SDD-01 (`uv_lock_hash` del `LineageBundle`), SDD-24 (CI de tests), SDD-05 (extra `[sweep]`), SDD-12/13/14/18/20/23/26 (extras de dominio). |
| **Autor / Fecha** | DanIA (fan-out Tanda 1) / 2026-06-23 |

---

## 1. Propósito y responsabilidad

**Qué resuelve (una frase).** Define el **contenedor distribuible y reproducible** del proyecto: cómo se empaqueta `nikodym` (build backend, layout, versionado), qué se instala en el núcleo base vs tras qué **extra** opcional, cómo se fija el árbol de dependencias (`uv.lock`) para reproducibilidad auditada, y cómo la CI garantiza calidad ejemplar (lint/types/tests/build) — todo bajo la restricción de licencia Apache-2.0 sin copyleft en el wheel.

**Responsabilidad única (qué SÍ hace).**
- Especifica el **`pyproject.toml`** completo: `[build-system]` (hatchling), `[project]` (metadata, `dependencies` base), `[project.optional-dependencies]` (mapa de **extras de usuario**), `[dependency-groups]` (PEP 735: test/lint/docs/dev), `[tool.hatch.*]`, `[tool.uv.*]`, y la config de `ruff`/`mypy`/`pytest`/`coverage`.
- Fija la **frontera núcleo-base ↔ extras**: qué deps se instalan siempre (coherente con SDD-01 §10) y cuáles quedan tras extra con **import perezoso** y mensaje de error claro.
- Define el **piso de versiones** crítico (en especial `scikit-learn>=1.6` en los extras de dominio, requisito de D-CONV-4/`check_estimator`) y los **vetos de licencia** (copyleft fuera del wheel).
- Define la **reproducibilidad de entorno**: `uv.lock` pineado, su hash al `LineageBundle` (SDD-01 §9), y la matriz de versiones de Python soportadas.
- Define la **CI** (GitHub Actions): pre-commit, ruff, mypy (`strict = true` en todo el paquete, cubriendo la API pública), pytest, build + smoke test del wheel; el **versionado SemVer** del paquete y el **changelog**.

**Límites explícitos (qué NO hace, y quién lo hace).**
- **No define la estrategia de tests** (qué se testea, fixtures, property-based, golden values): eso es **SDD-24**. SDD-25 solo aporta la **infraestructura** que ejecuta esos tests (config de pytest/coverage, jobs de CI, matriz).
- **No define `schema_version`** del config (SemVer del *schema*, SDD-05 §5.4); aquí se define el **SemVer del paquete** (`project.version`), que es **distinto**.
- **No declara los sub-configs ni la lógica de import perezoso de cada dominio**: SDD-25 fija el **contrato** (qué extra, qué piso de versión, qué mensaje al faltar) y la utilidad común `require_extra(...)`; cada SDD de dominio la usa.
- **No empaqueta datos ni secretos**: el `.gitignore` (vetando datos/secretos) y la política de exclusión los gobierna el proyecto (AGENTS); aquí solo se asegura que el **wheel** no arrastre artefactos indebidos.

---

## 2. Contexto y ubicación en la arquitectura

- **Capa:** Ingeniería / Fundación (transversal). Es el **andamiaje del repositorio**, no un módulo Python importable. Vive en la raíz: `pyproject.toml`, `uv.lock`, `.github/workflows/`, `.pre-commit-config.yaml`, `CHANGELOG.md`, `LICENSE`.
- **Quién lo consume:** *todos*. Cada SDD de dominio que agrega una dependencia pesada **añade su extra aquí** y usa `require_extra(...)` para el import perezoso. SDD-01 lee el hash de `uv.lock` para el `LineageBundle`. SDD-24 corre sus suites bajo la CI definida aquí.
- **A quién invoca:** a `uv` (resolución/lock/sync/build), a `hatchling` (build backend), a las herramientas de CI (`ruff`, `mypy`, `pytest`, `pre-commit`). No invoca código `nikodym` en tiempo de build.

```
        pyproject.toml  ── [build-system] ─▶ hatchling.build ─▶ wheel/sdist
              │                                   (solo src/nikodym; sin tests/docs)
   ┌──────────┼───────────────────────────┬──────────────────────────┐
   ▼          ▼                           ▼                          ▼
[project]  [project.optional-           [dependency-groups]      [tool.uv] + uv.lock
 deps base  dependencies]  (extras       (PEP 735: test/lint/docs/dev (pin reproducible;
 (SDD-01)   de USUARIO, redistribuidos)   — NO redistribuidos)      hash → LineageBundle)
                                                                          │
   ┌──────────────────────── CI (.github/workflows) ────────────────────┘
   ▼ pre-commit · ruff · mypy(strict=true, todo el paquete) · pytest(matriz Py) · build + smoke
```

**Interacción con el `Study` y el config declarativo.** Indirecta pero crítica: el `config_hash` identifica el *experimento*, pero la **reproducibilidad bit a bit** (SDD-01 §9) exige además fijar el *entorno*. Eso lo aporta `uv.lock`, cuyo hash entra al `LineageBundle.uv_lock_hash`. Sin este SDD, dos corridas con el mismo config podrían divergir por versiones distintas de librerías.

---

## 3. Conceptos y fundamentos

- **`src/` layout** — el paquete vive en `src/nikodym/`, no en la raíz. Beneficio: la suite de tests corre contra el paquete **instalado** (no contra el árbol de fuentes accidentalmente importable), atrapando errores de empaquetado (módulos no incluidos, `MANIFEST` incompleto). Es la práctica recomendada por PyPA y la fijada por D-PKG (ESPEC §3.3).
- **Build backend (hatchling)** — `hatchling` es el backend de build minimalista de Hatch; produce sdist+wheel desde `pyproject.toml` puro (PEP 517/518/621), sin `setup.py`. No requiere instalar `hatch` (el gestor de entornos) para construir: basta `hatchling` en `[build-system].requires`. (Verificado context7.)
- **Extra de usuario (`[project.optional-dependencies]`)** — grupos de dependencias **opcionales que se redistribuyen en los metadatos del wheel**: `pip install nikodym[xgboost]` los resuelve. Son para funcionalidad opcional *del usuario final*. (Verificado context7: uv lee extras de esta tabla; no se sincronizan por defecto, se activan con `--extra`/`--all-extras`.)
- **Dependency group (PEP 735, `[dependency-groups]`)** — grupos **de desarrollo, NO publicados en los metadatos del paquete**: `test`, `lint`, `docs` y `dev` (este último agrega los tres vía `include-group` + `pre-commit`). Un consumidor de PyPI nunca los recibe. uv los lee de esta tabla; el grupo `dev` es especial y se sincroniza por defecto. (Verificado context7.) **Esta es la pieza que permite usar `hypothesis` (MPL-2.0, copyleft débil) sin redistribuir copyleft**: vive en `[dependency-groups].test`, jamás en el wheel.
- **`uv.lock`** — lockfile universal y multiplataforma de uv que pinea el árbol *resuelto* de dependencias (versiones exactas + hashes). `uv sync --locked` falla si el lock está desactualizado → reproducibilidad garantizada en CI. Su hash sha256 alimenta el `LineageBundle` (SDD-01 §9, ESPEC §9). (Verificado context7.)
- **Import perezoso (lazy import)** — un backend pesado (xgboost, lifelines, streamlit) **no se importa al cargar `nikodym`**, sino dentro de la función/clase que lo usa; si falta, se levanta un error claro con la instrucción de instalación del extra. Mantiene el núcleo liviano (§4 principio 9) y permite `import nikodym` sin tener todo el stack ML.
- **`check_estimator` y el piso `sklearn>=1.6`** — desde scikit-learn 1.6 los *estimator tags* y `check_estimator` exigen heredar `sklearn.base.BaseEstimator` y el sistema de tags moderno (SDD-01 D-CORE-1, SDD-05 D-CONV-4). Por eso **todo extra cuyo dominio multihereda sklearn pinea `scikit-learn>=1.6`**: por debajo, la batería de checks no funciona como se especificó.
- **SemVer del paquete vs `schema_version`** — `project.version` (SemVer del *artefacto distribuido*, gobierna PyPI) es **distinto** del `schema_version` del config (SemVer del *schema*, SDD-05). Pueden evolucionar a ritmos diferentes.

> **Fórmulas / parámetros normativos:** este SDD no contiene ninguno. La única "regla dura cuantitativa" es la **tabla de licencias** (ESPEC §7) y los **pisos de versión**, que se citan, no se inventan.

---

## 4. API pública (contrato)

SDD-25 es infraestructura; su "API" son **artefactos de configuración** (el `pyproject.toml`, los workflows) más **una utilidad de import perezoso** que sí es código Python y que todos los dominios consumen.

**4.1 Utilidad de import perezoso** (`src/nikodym/utils/optional.py`):

```python
# Firmas ilustrativas (contrato, no implementación). Docstrings/mensajes en español.

def require_extra(extra: str, *modules: str) -> tuple:
    """Importa y devuelve los módulos pesados de un extra; si falta uno, levanta
    MissingDependencyError con la instrucción de instalación.

    Ejemplo: xgb, = require_extra("xgboost", "xgboost")
    """
    ...

def has_extra(extra: str, *modules: str) -> bool:
    """True si todos los módulos del extra están importables (sin levantar)."""
    ...

# Mapa declarativo extra -> MÓDULOS importables a verificar con `require_extra`,
# fuente única del mensaje al usuario. OJO: son los nombres de IMPORT (no las
# distribuciones pip completas del extra). El conjunto de CLAVES de este mapa es,
# por contrato, EXACTAMENTE el de [project.optional-dependencies] menos "all"
# (test de biyección de §11). Las tuplas listan solo los módulos a probar, que
# legítimamente difieren de la lista completa de deps del extra en §5 (p.ej. scipy
# es transitivo de scoring y no se prueba aquí; "optbinning" el módulo, "optbinning>=0.19"
# la dist).
EXTRA_TO_DISTRIBUTIONS: dict[str, tuple[str, ...]] = {
    "scoring":     ("optbinning", "statsmodels", "scikit-learn"),
    "xgboost":     ("xgboost",),
    "lightgbm":    ("lightgbm",),
    "catboost":    ("catboost",),
    "tuning":      ("optuna",),
    "explain":     ("shap", "matplotlib"),
    "forecasting": ("statsmodels", "pmdarima"),
    "survival":    ("lifelines",),
    "tracking":    ("mlflow",),
    "ui":          ("streamlit",),
    "sweep":       ("hydra-core", "omegaconf"),
    # "all" se compone por unión (ver §5); "report" (Quarto) es binario externo, ver §8/§12.
}
```

`MissingDependencyError` vive en **`core.exceptions`** (no aquí; ver §8 y §10) y desciende de `NikodymError`, conforme a la regla de SDD-01 §4: `core.exceptions` aloja la raíz `NikodymError` y las excepciones del núcleo. `MissingDependencyError` es una excepción del núcleo porque la levanta la utilidad transversal `require_extra` (en `nikodym.utils`) y la consumen todos los dominios; por eso pertenece a `core`, no a un módulo de dominio. Su mensaje (español) nombra el extra y la línea exacta de instalación, p.ej.:

> `"La función requiere el extra 'xgboost'. Instálalo con: pip install 'nikodym[xgboost]' (o uv add 'nikodym[xgboost]')."`

**4.2 Comandos de ciclo de vida** (contrato operativo, no código):

| Acción | Comando canónico |
|---|---|
| Crear/actualizar el lock | `uv lock` |
| Entorno de desarrollo completo | `uv sync --locked --all-extras --group dev --group test` |
| Entorno mínimo (solo base) | `uv sync --locked --no-default-groups` |
| Construir wheel + sdist | `uv build` |
| Smoke test del wheel | `uv run --isolated --no-project --with dist/*.whl -c "import nikodym"` |
| Publicar (release) | `uv build && uv publish` (en CI, vía OIDC/Trusted Publishing) |

(Comandos verificados context7: `uv sync --locked --all-extras --dev`, `uv build`, smoke test con `--isolated --no-project --with dist/*.whl`, `uv publish`.)

**4.3 Ejemplo de uso extremo a extremo (consumidor):**

```bash
pip install nikodym                 # núcleo base: config, Study, lineage (sin ML pesado)
pip install 'nikodym[scoring]'      # MVP scorecard (optbinning + statsmodels + sklearn>=1.6)
pip install 'nikodym[xgboost,tracking]'   # ML gradient boosting + MLflow
pip install 'nikodym[all]'          # todo lo redistribuible (NO incluye scikit-survival, ver §5)
```

```python
import nikodym                       # siempre funciona; no arrastra xgboost/streamlit
from nikodym.ml import XGBoostModel  # el import del módulo no falla...
m = XGBoostModel()                   # ...pero usar el backend sin el extra ->
m.fit(X, y)                          # MissingDependencyError con la instrucción de instalación
```

---

## 5. Configuración (el `pyproject.toml` y la matriz de extras)

> Este es el **contrato ilustrativo** del `pyproject.toml`. Los pisos de versión son **defaults defendibles**; los pisos críticos (sklearn) son regla dura. Las distribuciones por extra siguen la tabla de licencias de ESPEC §7.

```toml
# ─────────────────────────── build backend ───────────────────────────
[build-system]
requires = ["hatchling>=1.24"]              # piso coherente con §10 (build reproducible, PyPA)
build-backend = "hatchling.build"

# ─────────────────────────── metadata (PEP 621) ──────────────────────
[project]
name = "nikodym"
description = "Librería de riesgo de crédito: scoring, ML, provisiones CMF e IFRS 9/ECL, forward-looking y stress testing."
readme = "README.md"
requires-python = ">=3.11"
license = "Apache-2.0"                     # SPDX (PEP 639); LICENSE en la raíz
license-files = ["LICENSE"]
authors = [{ name = "Nikodym", email = "admin@nxlabs.cl" }]
keywords = ["credit-risk", "ifrs9", "ecl", "cmf", "scorecard", "provisioning"]
classifiers = [
  "Development Status :: 3 - Alpha",
  "License :: OSI Approved :: Apache Software License",
  "Programming Language :: Python :: 3.11",
  "Programming Language :: Python :: 3.12",
  "Programming Language :: Python :: 3.13",
  "Intended Audience :: Financial and Insurance Industry",
  "Topic :: Scientific/Engineering",
  "Typing :: Typed",
]
dynamic = ["version"]                       # ver [tool.hatch.version]

# Núcleo BASE: se instala SIEMPRE con `pip install nikodym`. Coherente con SDD-01 §10.
# Solo deps permisivas y livianas; NADA de ML/forecasting/UI aquí.
dependencies = [
  "pydantic>=2.5",        # config, LineageBundle, AuditEvent (MIT)
  "numpy>=1.22",          # SeedSequence/Generator (BSD)
  "pandas>=2.0",          # DataFrame, contrato de I/O universal (BSD) — SDD-05 §6
  "joblib>=1.3",          # persistencia de artefactos (BSD)
  "PyYAML>=6.0",          # round-trip YAML legible (MIT)
]

[project.urls]
Homepage = "https://github.com/nexolabs-gh/nikodym"
Source = "https://github.com/nexolabs-gh/nikodym"
Documentation = "https://github.com/nexolabs-gh/nikodym#readme"
Changelog = "https://github.com/nexolabs-gh/nikodym/blob/main/CHANGELOG.md"

# ───────────────── EXTRAS de USUARIO (se redistribuyen en el wheel) ───────────────
[project.optional-dependencies]
# MVP scorecard (F1). sklearn>=1.6 OBLIGATORIO: check_estimator/tags (D-CONV-4).
scoring = [
  "optbinning>=0.19",     # Apache-2.0 — binning/WoE/monotonía (no reinventar, §4.8)
  "statsmodels>=0.14",    # BSD — inferencia/stepwise/p-values
  "scikit-learn>=1.6",    # BSD — pipeline/check_estimator; PISO 1.6 (regla dura)
  "scipy>=1.10",          # BSD — arrastrado por statsmodels/sklearn, explícito
]
# Backends ML (F2). Cada GBDT es un extra independiente (instalación selectiva).
xgboost  = ["xgboost>=2.0",  "scikit-learn>=1.6"]   # Apache-2.0
lightgbm = ["lightgbm>=4.0", "scikit-learn>=1.6"]   # MIT
catboost = ["catboost>=1.2", "scikit-learn>=1.6"]   # Apache-2.0
tuning   = ["optuna>=3.5"]                          # MIT (samplers seedeados, SDD-13)
explain  = ["shap>=0.44", "matplotlib>=3.7"]        # MIT / PSF (SDD-14)
# Forward-looking (F5).
forecasting = ["statsmodels>=0.14", "pmdarima>=2.0"]  # BSD / MIT (ARIMA/VAR, SDD-20)
survival    = ["lifelines>=0.28"]                     # MIT — KM/Cox/AFT (SDD-18). NO scikit-survival.
# Infraestructura opcional.
tracking = ["mlflow>=2.10"]                # Apache-2.0 (runs/registry, SDD-04)
ui       = ["streamlit>=1.30"]             # Apache-2.0 (editor de config, SDD-23)
sweep    = ["hydra-core>=1.3", "omegaconf>=2.3"]   # MIT / BSD-3 (barridos CLI, SDD-05 §5.6)
# Meta-extra: TODO lo redistribuible. Excluye explícitamente copyleft (scikit-survival GPL-3.0).
all = [
  "nikodym[scoring]", "nikodym[xgboost]", "nikodym[lightgbm]", "nikodym[catboost]",
  "nikodym[tuning]", "nikodym[explain]", "nikodym[forecasting]", "nikodym[survival]",
  "nikodym[tracking]", "nikodym[ui]", "nikodym[sweep]",
]

# ───────────── GRUPOS de DESARROLLO (PEP 735 — NO se redistribuyen) ─────────────
[dependency-groups]
test = [
  "pytest>=8.1",
  "pytest-cov>=5.0",
  "hypothesis>=6.100",     # MPL-2.0 (copyleft DÉBIL) — DEV-ONLY, nunca en el wheel (§3, §10)
]
lint = [
  "ruff>=0.5",
  "mypy>=1.10",
]
docs = [
  "mkdocs-material>=9.5",  # docs del repo; Quarto (binario externo) NO es dep pip (§12)
]
dev = [
  { include-group = "test" },
  { include-group = "lint" },
  { include-group = "docs" },
  "pre-commit>=3.7",
]

# ─────────────────────────── hatchling (build) ───────────────────────────
[tool.hatch.version]
path = "src/nikodym/__init__.py"           # __version__ = "x.y.z" (fuente única del SemVer)

[tool.hatch.build.targets.wheel]
packages = ["src/nikodym"]                 # SOLO el paquete; tests/docs NO entran al wheel
exclude = ["*.parquet", "*.csv"]           # defensa en profundidad: ningún dato en el wheel (§6)

[tool.hatch.build.targets.sdist]
include = ["/src", "/tests", "/CHANGELOG.md", "/LICENSE", "/README.md"]
exclude = ["/.github", "/docs", "/.venv", "*.parquet", "*.csv"]   # nunca datos en el sdist

# ─────────────────────────── uv (lock/resolución) ───────────────────────────
[tool.uv]
required-version = ">=0.5"
# default-groups: qué grupos sincroniza `uv sync` sin flags. Por defecto solo "dev"
# (que ya incluye test/lint/docs). En CI se pinea explícito con --group.

# ─────────────────────────── ruff / mypy / pytest ───────────────────────────
[tool.ruff]
line-length = 100
target-version = "py311"
[tool.ruff.lint]
select = ["E", "F", "I", "N", "UP", "B", "SIM", "RUF", "D"]   # D = docstrings (en español)
[tool.ruff.lint.pydocstyle]
convention = "numpy"

[tool.mypy]
python_version = "3.11"
mypy_path = "src"                           # src/ layout: encuentra el paquete sin requerir install
packages = ["nikodym"]
strict = true                               # STRICT por defecto en TODO el paquete (ESPEC §10, §12).
                                            # "strict" habilita el conjunto completo de flags
                                            # (disallow_untyped_defs/-calls/-incomplete-defs,
                                            # no_implicit_optional, warn_return_any,
                                            # warn_unused_ignores, disallow_subclassing_any, etc.).
                                            # La "API pública" (estimadores de dominio, SDD-05) NO
                                            # queda fuera: strict cubre core, data, binning, model,
                                            # provisioning y demás módulos del paquete.
[[tool.mypy.overrides]]
# Conjunto = TODA lib de terceros sin stubs de tipos que el paquete importe (base o extras).
# Debe cubrir las usadas en código propio bajo strict; ampliar al añadir un backend.
module = [
  "optbinning.*", "lifelines.*", "pmdarima.*", "shap.*", "catboost.*",
  "xgboost.*", "lightgbm.*", "statsmodels.*", "scipy.*",
  "mlflow.*", "streamlit.*", "hydra.*", "omegaconf.*", "pandera.*",
]
ignore_missing_imports = true               # libs sin stubs; relajar SOLO el import, no el strict del código propio

[tool.pytest.ini_options]
minversion = "8.0"
addopts = "--strict-markers --strict-config -ra"
testpaths = ["tests"]
markers = [
  "slow: marca tests lentos (excluibles con -m 'not slow')",
  "extra_ml: requiere extras de ML (xgboost/lightgbm/catboost)",
  "repro: tests de reproducibilidad determinista",
]

[tool.coverage.run]
source = ["nikodym"]
branch = true
[tool.coverage.report]
exclude_lines = ["pragma: no cover", "raise NotImplementedError", "if TYPE_CHECKING:"]
```

**Matriz de extras (resumen canónico, fuente para la doc y para `EXTRA_TO_DISTRIBUTIONS`):**

| Extra | Distribuciones | Licencia | SDD que lo usa | Piso sklearn |
|---|---|---|---|---|
| `scoring` | optbinning, statsmodels, scikit-learn, scipy | Apache/BSD ✅ | 06–11 | **≥1.6** |
| `xgboost` | xgboost (+sklearn) | Apache-2.0 ✅ | 12 | **≥1.6** |
| `lightgbm` | lightgbm (+sklearn) | MIT ✅ | 12 | **≥1.6** |
| `catboost` | catboost (+sklearn) | Apache-2.0 ✅ | 12 | **≥1.6** |
| `tuning` | optuna | MIT ✅ | 13 | — |
| `explain` | shap, matplotlib | MIT/PSF ✅ | 14 | — |
| `forecasting` | statsmodels, pmdarima | BSD/MIT ✅ | 20 | — |
| `survival` | lifelines | MIT ✅ | 18 | — |
| `tracking` | mlflow | Apache-2.0 ✅ | 04 | — |
| `ui` | streamlit | Apache-2.0 ✅ | 23 | — |
| `sweep` | hydra-core, omegaconf | MIT/BSD-3 ✅ | 05 | — |
| `all` | unión de los anteriores | sin copyleft ✅ | — | ≥1.6 |
| `report` *(reservado)* | — *(lo define SDD-26)* | permisivo (TBD) | 26 | — |
| ~~scikit-survival~~ | — | **GPL-3.0 ❌** | research only | **EXCLUIDO** |

---

## 6. Contratos de datos (I/O)

SDD-25 no procesa datos de negocio; sus "datos" son artefactos de build y CI.

**Input.**
- `pyproject.toml` (fuente de verdad de metadata, deps, extras, grupos, config de tooling).
- `uv.lock` (árbol resuelto y pineado; generado por `uv lock`, versionado en git).
- `src/nikodym/__init__.py` con `__version__` (fuente del SemVer; lo lee `[tool.hatch.version]`).

**Output.**
- **wheel** (`nikodym-<ver>-py3-none-any.whl`): contiene **solo** `src/nikodym/`, su metadata y los extras declarados en `[project.optional-dependencies]`. **No** contiene `tests/`, `docs/`, `[dependency-groups]` (PEP 735 no se publica), ni datos.
- **sdist** (`nikodym-<ver>.tar.gz`): incluye `src/` + `tests/` + `LICENSE`/`README`/`CHANGELOG`, sin `.github`/`docs`/datos.
- **hash de `uv.lock`** (sha256) → expuesto a SDD-01 para `LineageBundle.uv_lock_hash`.

**Invariantes (pre/post).**
- *Anti-copyleft (regla dura, verificable en CI):* ninguna distribución con licencia **copyleft fuerte (GPL/LGPL/AGPL)** aparece en `[project.dependencies]` ni en `[project.optional-dependencies]` (incl. resoluciones transitivas del lock). `hypothesis` (MPL-2.0, copyleft débil) **solo** en `[dependency-groups]`. `scikit-survival` (GPL-3.0) **nunca**.
- *Núcleo liviano:* `import nikodym` no importa sklearn, xgboost, lightgbm, catboost, mlflow, streamlit, lifelines ni statsmodels (verificable con un test que inspecciona `sys.modules` tras el import — §11).
- *Piso sklearn:* todo extra de la columna "≥1.6" resuelve `scikit-learn>=1.6`.
- *Wheel limpio:* el wheel construido no contiene `tests/`, `*.parquet`, `*.csv`, ni `dependency-groups` en su metadata.
- *Lock reproducible:* `uv sync --locked` no modifica el lock (falla si está desactualizado) → el árbol instalado es el pineado.
- *Versión única:* `project.version` (dynamic) == `nikodym.__version__`; el tag git de release == `v<version>`.

---

## 7. Algoritmos y flujo

> SDD-25 "ejecuta" pipelines de CI/CD, no algoritmos de cálculo. Flujo de alto nivel.

**Flujo de build (`uv build`).**
1. `uv` lee `[build-system]` → invoca `hatchling.build` (PEP 517).
2. `hatchling` resuelve la versión dinámica desde `src/nikodym/__init__.py` (`[tool.hatch.version]`).
3. Construye el **wheel** incluyendo solo `packages=["src/nikodym"]` y el **sdist** según `include/exclude`.
4. Resultado en `dist/`. `[dependency-groups]` se ignoran (PEP 735 no se publica) → el copyleft débil de test no viaja.

**Flujo de import perezoso (`require_extra`).**
1. Un método de dominio (p.ej. `XGBoostModel.fit`) llama `xgb, = require_extra("xgboost", "xgboost")`.
2. `require_extra` intenta `importlib.import_module("xgboost")`.
3. Éxito → devuelve el módulo. `ImportError`/`ModuleNotFoundError` → levanta `MissingDependencyError` con el mensaje de instalación derivado de `EXTRA_TO_DISTRIBUTIONS["xgboost"]`.
*Decisión:* el import ocurre **dentro del método que lo necesita**, no a nivel de módulo, para que `from nikodym.ml import XGBoostModel` nunca falle por ausencia del extra (solo falla al *usarlo*). *Alternativa descartada:* `try/except ImportError` a nivel de módulo con clase stub — más frágil y oculta el punto de fallo.

**Flujo de CI (push/PR → GitHub Actions).**
1. **Job `quality`** (rápido, una versión de Python): checkout → `astral-sh/setup-uv` → `uv sync --locked --group lint` → `ruff check` + `ruff format --check` → `mypy` (`strict = true`, todo el paquete; ver §5).
2. **Job `test`** (matriz `python: [3.11, 3.12, 3.13] × os: [ubuntu, macos, windows]`): `uv sync --locked --group test --extra scoring` → `pytest --cov`. Un job adicional con `--all-extras` para la suite ML (marcado `extra_ml`).
3. **Job `build`**: `uv build` → smoke test (`uv run --isolated --no-project --with dist/*.whl -c "import nikodym; print(nikodym.__version__)"`) + verificación anti-copyleft (escanea metadata del wheel y el lock).
4. **Job `lock-check`**: `uv lock --check` (el lock está al día con `pyproject.toml`).
5. **Job `release`** (solo en tag `v*`): `uv build && uv publish` vía **Trusted Publishing (OIDC)**, sin tokens en secretos.

**Pre-commit** (local, espejo del job `quality`): hooks `ruff`, `ruff-format`, `mypy`, más checks básicos (yaml/toml válidos, EOF, trailing-whitespace, "no datos grandes").

**Complejidad / rendimiento.** Irrelevante en cómputo; lo relevante es el **tiempo de CI**: cacheo de `uv` (`setup-uv` con cache), `--locked` evita re-resolución, la matriz completa solo en `main`/PR (push a ramas: subset).

---

## 8. Casos borde y manejo de errores

- **Extra ausente al usar un backend** → `MissingDependencyError` (desc. de `NikodymError`) con la línea de instalación exacta. **Nunca** un `ImportError` crudo ni un `AttributeError` confuso. (Mensaje en español, §4.1.)
- **Extra parcialmente instalado** (p.ej. `xgboost` presente pero `scikit-learn<1.6`): `require_extra` solo verifica importabilidad; el **piso de versión** lo garantiza el resolutor (`uv`/`pip`) al instalar el extra. Si alguien fuerza un downgrade manual, el fallo aflora en `check_estimator` (SDD-24), no en `require_extra` — documentado como caveat.
- **`uv.lock` desactualizado en CI** → `uv sync --locked` / `uv lock --check` **fallan** el job (no se auto-actualiza en CI; el dev corre `uv lock` localmente y commitea).
- **Resolución que arrastra copyleft transitivo** → el job anti-copyleft **falla el build** y nombra la distribución infractora. (Mitigación de R-LIC.)
- **`scikit-survival` solicitado** → no existe extra para él; si un usuario lo instala aparte, queda **fuera del wheel distribuido** y fuera del soporte (research only, ESPEC §7).
- **Quarto ausente** (SDD-26): Quarto es un **binario externo**, no una dist pip; `report` no es un extra resoluble por pip. El módulo `report` detecta `quarto` en el `PATH` y, si falta, levanta un error claro ("instala Quarto desde quarto.org") — el contrato del mensaje es de SDD-26, pero el patrón de "dependencia externa no-pip" se fija aquí.
- **Python fuera de rango** (`<3.11`) → el resolutor rechaza la instalación por `requires-python`.
- **Build con `tests/` colándose al wheel** → atrapado por el test de empaquetado (§11) que inspecciona el contenido del wheel.
- **Versión inconsistente** (`__version__` ≠ tag) → el job `release` valida `v<__version__> == tag` y aborta si difieren.

**`MissingDependencyError`** vive en **`core.exceptions`** y desciende de `NikodymError` (regla SDD-01 §4: `core.exceptions` aloja la raíz y las excepciones del núcleo). Justifica vivir en `core` —no en un módulo de dominio— porque la usan todos los dominios y `require_extra` (en `nikodym.utils`) necesita levantarla sin importar nada pesado. SDD-25 fija su mensaje (§4.1); su definición formal es de SDD-01.

---

## 9. Reproducibilidad y auditoría

- **`uv.lock` es el ancla de reproducibilidad de entorno.** Pinea versiones exactas + hashes de todo el árbol resuelto; `uv sync --locked` garantiza que el entorno instalado == el pineado. Su **hash sha256** entra al `LineageBundle.uv_lock_hash` (SDD-01 §9, ESPEC §9, §12 R3). Sin él, el `config_hash` identifica el experimento pero no el entorno → reproducibilidad incompleta.
- **`library_versions` del lineage** (SDD-01) se complementa con el lock: el bundle registra qué versiones corrieron; el lock permite **recrear** ese entorno.
- **Determinismo de build:** hatchling produce wheels deterministas dado el mismo árbol de fuentes; el versionado dinámico desde `__init__.py` evita drift entre metadata y código.
- **Auditoría de licencias:** el job anti-copyleft deja un **reporte de licencias** (artefacto de CI) por release → evidencia de que el wheel es Apache-2.0-compatible. Pieza de la "calidad ejemplar como marketing" (ESPEC §1, §10).
- **SemVer + changelog:** cada release etiqueta `v<x.y.z>` y actualiza `CHANGELOG.md` (formato *Keep a Changelog*); breaking changes → bump mayor. Trazabilidad de qué cambió entre versiones distribuidas.
- **Caveat honesto:** el lock fija versiones, pero el **determinismo numérico** de GBDT multihilo sigue siendo el de SDD-01 (`strict_determinism`); el packaging no lo resuelve, solo asegura que la *misma* versión de la lib corre.

---

## 10. Dependencias

**Internas:** ninguna en build time. En runtime, la utilidad `require_extra` vive en `nikodym.utils` y levanta `MissingDependencyError` de `core.exceptions` (única dependencia conceptual hacia `core`).

**Externas — build/CI (no se redistribuyen en el wheel salvo el backend):**

| Herramienta | Versión mín. | Licencia | Rol | Redistribuida en wheel |
|---|---|---|---|---|
| hatchling | ≥1.24 | MIT ✅ | build backend (PEP 517) | No (build-only) |
| uv | ≥0.5 | Apache-2.0/MIT ✅ | gestor/lock/build/publish | No (tooling) |
| ruff | ≥0.5 | MIT ✅ | lint + format (`[dependency-groups].lint`) | No |
| mypy | ≥1.10 | MIT ✅ | type-check `strict = true` (todo el paquete; ver §5) | No |
| pytest (+pytest-cov) | ≥8.1 / ≥5.0 | MIT ✅ | runner de tests (`test`) | No |
| hypothesis | ≥6.100 | **MPL-2.0** (copyleft débil) | property-based (`test`) | **No — dev-only (clave §3)** |
| pre-commit | ≥3.7 | MIT ✅ | hooks locales (`dev`) | No |
| mkdocs-material | ≥9.5 | MIT ✅ | docs del repo (`docs`) | No |

**Núcleo base redistribuido** (`[project.dependencies]`): pydantic, numpy, pandas, joblib, PyYAML — todas MIT/BSD (coherente con SDD-01 §10; pandas se añade por ser el contrato de I/O universal de SDD-05 §6).

**Extras redistribuidos:** ver tabla §5 — todas permisivas. **Vetado en cualquier tabla redistribuida:** GPL/LGPL/AGPL (en particular `scikit-survival` GPL-3.0). `hypothesis` (MPL-2.0) confinado a `[dependency-groups]`.

> **Verificación de licencias (context7/fuente oficial):** los pisos y licencias de las distribuciones se toman de ESPEC §7 (tabla ya verificada en Tanda 0). La **mecánica de packaging** (qué tabla redistribuye y cuál no) se verificó con la doc oficial de uv: extras (`[project.optional-dependencies]`) se publican y sincronizan con `--extra`; grupos (`[dependency-groups]`, PEP 735) son dev-only y no viajan en el wheel. Esto sustenta el confinamiento de `hypothesis`.

---

## 11. Estrategia de tests

Detalle transversal en **SDD-24**; lo específico del **empaquetado** (tests que SDD-25 aporta):

- **Build + smoke (CI).** `uv build` produce wheel+sdist; `uv run --isolated --no-project --with dist/*.whl -c "import nikodym"` confirma que el wheel instala e importa en un entorno limpio (atrapa módulos no incluidos / `src/` mal mapeado).
- **Núcleo liviano (test de aislamiento).** Tras `import nikodym` en un entorno **solo-base** (sin extras), inspeccionar `sys.modules`: ausentes `sklearn`, `xgboost`, `lightgbm`, `catboost`, `mlflow`, `streamlit`, `lifelines`, `statsmodels`. Invariante §6.
- **Import perezoso (mensaje al usuario).** En un entorno sin el extra `xgboost`, usar el backend levanta `MissingDependencyError` cuyo mensaje **contiene** `"nikodym[xgboost]"`. Test parametrizado sobre todos los extras de `EXTRA_TO_DISTRIBUTIONS`.
- **Contenido del wheel.** Abrir el `.whl` (zip) y verificar: contiene `nikodym/__init__.py`; **no** contiene `tests/`, `*.parquet`, `*.csv`; los metadatos (`METADATA`) listan los extras de `[project.optional-dependencies]` y **no** los `[dependency-groups]`.
- **Anti-copyleft.** Sobre el lock + metadata del wheel, fallar si aparece una licencia GPL/LGPL/AGPL. (Usa la clasificación SPDX de la metadata instalada.)
- **Lock al día.** `uv lock --check` no produce cambios (el lock refleja `pyproject.toml`).
- **Coherencia de versión.** `nikodym.__version__` parsea como SemVer y, en release, coincide con el tag git.
- **Coherencia extra↔config (propiedad).** El test cruza **CLAVES de extra**: `set(EXTRA_TO_DISTRIBUTIONS) == set([project.optional-dependencies]) - {"all"}` (más `report`, que está reservado y aún sin deps pip — se excluye hasta que SDD-26 lo defina). **No** compara la lista exacta de distribuciones por extra: las tuplas del mapa son los **módulos importables a probar** con `require_extra`, que legítimamente difieren de las deps del extra en §5 (p.ej. `scipy` es transitivo de `scoring` y no se prueba). Atrapa drift de claves entre `pyproject.toml` y el mapa de mensajes.
- **Matriz de Python.** La suite base corre en 3.11/3.12/3.13 (la matriz de CI es el "test").

**Fixtures.** Wheel construido en un tmpdir; entorno virtual efímero (`uv venv`) para el smoke; un módulo de dominio *dummy* que llama `require_extra("inexistente", "modulo_que_no_existe")` para validar el mensaje sin depender de un backend real.

---

## 12. Decisiones abiertas y riesgos

**Decisiones resueltas en este SDD (trazabilidad).**
- **D-PKG-1 — hatchling como build backend** (no setuptools/poetry/flit). *Porqué:* mínimo, PEP 621 puro, sin `setup.py`, versión dinámica desde `__init__.py`; lo fija D-PKG (ESPEC §3.3). *Alternativa descartada:* `poetry` (su tabla `[tool.poetry]` precede a PEP 621 y duplica metadata; menos estándar). **Reversible** sin tocar código de `nikodym` (solo `[build-system]`).
- **D-PKG-2 — Frontera núcleo-base ↔ extras.** Base = pydantic+numpy+pandas+joblib+PyYAML (livianas, permisivas, suficientes para `Study`/config/lineage). Todo ML/forecasting/UI/tracking tras extra con import perezoso. *Porqué:* núcleo liviano (§4 principio 9) + `import nikodym` siempre funciona. *Nota:* se **añade pandas a la base** (SDD-01 §10 no lo listaba) porque es el contrato de I/O universal de SDD-05 §6; se señala al integrador para conciliar con SDD-01. *Nota de alcance:* los extras `tuning` (optuna, MIT) y `explain` (shap MIT + matplotlib PSF) no figuraban en la lista ejemplar del encargo; se **derivan deliberadamente** de ESPEC §7 (stack con licencias) y de SDD-13 (tuning) / SDD-14 (explicabilidad). No son invención fuera de alcance: completan el mapa para que `[all]` y `EXTRA_TO_DISTRIBUTIONS` sean coherentes.
- **D-PKG-3 — `[dependency-groups]` (PEP 735) para test/lint/docs/dev, no extras.** *Porqué:* no se publican en el wheel → permiten `hypothesis` (MPL-2.0) sin redistribuir copyleft; uv los gestiona nativamente. *Alternativa descartada:* un extra `[dev]` (se publicaría en metadata; ensucia y arrastra copyleft débil al artefacto).
- **D-PKG-4 — `scikit-learn>=1.6` en todos los extras de dominio.** *Porqué:* `check_estimator`/tags modernos lo exigen (D-CONV-4, SDD-05 §4). *Consecuencia:* es regla dura verificable en CI, no un default ajustable.
- **D-PKG-5 — `requires-python>=3.11`, matriz 3.11–3.13.** *Porqué:* 3.11 es el piso razonable a 2026 (mejoras de typing/perf); evita cargar compat de 3.9/3.10. *Reversible* si un cliente institucional exige 3.10.
- **D-PKG-6 — Versión dinámica desde `src/nikodym/__init__.py`** (no tag VCS). *Porqué:* fuente única legible, sin acoplar el build a git en entornos sin historia. *Alternativa considerada:* `hatch-vcs` (versión desde tags) — más automático pero falla en sdist sin `.git`; reevaluable.

**Decisiones abiertas (delegadas).**
- **`report` (Quarto) no es un extra pip.** Quarto es binario externo; el contrato de detección/mensaje es de **SDD-26**. El nombre del extra `[report]` queda **reservado** en la matriz §5 para SDD-26 (que decidirá si agrega deps pip como jinja2/plotly junto al binario Quarto). *Responsable:* DanIA + autor SDD-26. Acotada a T2/F1: no bloquea este SDD.
- **Trusted Publishing (OIDC) vs token PyPI** para el job `release`. *Sugerencia:* OIDC (sin secretos). *Responsable:* DanIA al armar el repo público.
- **`hatch-vcs` (versión por tag) vs `__init__.py`** — reevaluar al primer release público (SDD-26/F1).
- **Política de `default-groups` de uv** (¿`dev` por defecto, o vacío para entornos limpios?). *Sugerencia:* default `dev` localmente, explícito en CI.
- **Email de contacto público del paquete.** El `authors.email` viaja en la metadata pública del wheel (PyPI). `admin@nxlabs.cl` es personal/administrativo; para una librería que es escaparate de la consultora Nikodym, conviene un alias de proyecto (p.ej. `contacto@`/`opensource@`). *Sugerencia:* alias de proyecto. *Responsable:* DanIA + Cami al armar el repo público (F1).

**Riesgos.**
- **R-LIC — copyleft transitivo se cuela al wheel.** *Mitigación:* job anti-copyleft que escanea el lock + metadata y falla el build; `hypothesis` confinado a `[dependency-groups]`; `scikit-survival` sin extra. (Es el riesgo regulatorio/reputacional más caro: un wheel "Apache-2.0" con GPL transitivo daña la marca Nikodym.)
- **R3 (determinismo, ESPEC §12) — entorno no pineado.** *Mitigación:* `uv.lock` + `--locked` en CI + hash al lineage.
- **Drift `pyproject.toml`↔`EXTRA_TO_DISTRIBUTIONS`↔mensajes.** *Mitigación:* test de propiedad cruzado (§11).
- **Matriz de CI lenta/cara** (3 Python × 3 OS × extras ML). *Mitigación:* matriz completa solo en `main`/PR; subset en ramas; cache de uv; suite ML marcada y separable.
- **`uv` aún evoluciona rápido (pre-1.0 histórico).** *Mitigación:* `required-version` pineado; `hatchling` como backend es estable e independiente de uv (uv solo orquesta; el build no depende de uv).

---

### Citas

- **ESPECIFICACIONES.md** §3.3 (D-LIC Apache-2.0 sin copyleft; D-PKG `uv`+`hatchling`, `pyproject.toml`, `src/` layout), §4 (principios 1 reproducibilidad, 9 núcleo liviano con extras e import perezoso, 8 no reinventar, 10 calidad ejemplar como marketing, 11 verificación de datos externos), §6.3 (árbol de paquetes), §7 (stack con licencias: tabla fuente de los extras; `scikit-survival` GPL-3.0 vetado; `hypothesis` MPL-2.0 dev-only no redistribuido; `[project.optional-dependencies]` para extras y `[dependency-groups]` PEP 735 para test/lint/docs/dev), §9 (lineage bundle incl. `uv.lock`), §10 (CI: ruff, mypy strict —aquí `strict = true` en todo el paquete, que cubre la API pública—, tests, build, pre-commit; SemVer, changelog), §11 F0 DoD (`pyproject.toml` uv+hatchling, CI), §12 (R3 determinismo → pin `uv.lock`, R5).
- **ROADMAP.md** F0 (entregables: `src/` layout, `pyproject.toml` uv+hatchling con extras declarados; CI ruff/mypy/pytest, pre-commit, plantillas issue/PR; DoD CI verde), F1 (release público v0.1.0 en PyPI).
- **00-INDICE.md** SDD-25 (Packaging+CI, F0/T1, depende de —, Ingeniería), §Convenciones (fórmulas/parámetros se citan, no se reescriben).
- **SDD-01 (`core`)** §4 (jerarquía `core.exceptions`, base para `MissingDependencyError` propuesta), §9 (`LineageBundle.uv_lock_hash`, `library_versions`, `determinism_caveats`, `strict_determinism`), §10 (deps base del núcleo: pydantic/numpy/joblib/PyYAML — este SDD añade pandas, señalado al integrador), D-CORE-1 (`core` no depende de sklearn; multiherencia en dominios).
- **SDD-05 (convenciones+config)** §4 (D-CONV-4: `check_estimator` solo en estimadores de dominio que multiheredan `BaseEstimator`, requiere sklearn ≥1.6), §5.6 (extra `[sweep]` Hydra/OmegaConf, import perezoso), §10 (sklearn dep de los extras, no de `core`).
- **Verificado vía context7 (mecánica de packaging, doc oficial):**
  - **hatchling/Hatch** (`/pypa/hatch`): `[build-system] requires=["hatchling"]` + `build-backend="hatchling.build"`; `[tool.hatch.version] path=...`; `[tool.hatch.build.targets.wheel] packages=["src/foo"]`; `[tool.hatch.build.targets.sdist] include/exclude`; `[project.optional-dependencies]` para features opcionales; `dynamic=["version"]`.
  - **uv** (`/websites/astral_sh_uv`): `uv.lock` + `uv sync --locked` (reproducibilidad, falla si desactualizado); `[dependency-groups]` (PEP 735) — `dev` especial sincronizado por defecto, leído de esa tabla, **dev-only**; `[project.optional-dependencies]` = extras, **no** sincronizados por defecto, activados con `--extra`/`--all-extras`; `uv build` (sdist+wheel); smoke test `uv run --isolated --no-project --with dist/*.whl`; `uv publish`; workflow CI `uv sync --locked --all-extras --dev` + `astral-sh/setup-uv`. La distinción extras-publicados vs dependency-groups-no-publicados sustenta el confinamiento de `hypothesis` (MPL-2.0) y la garantía anti-copyleft del wheel.
