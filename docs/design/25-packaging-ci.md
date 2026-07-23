# SDD-25 — Packaging + CI (uv, hatchling, extras, gobernanza de licencias)

> **Reapertura B2.0 — APROBADA (2026-07-23).** La fundación Python de este SDD está implementada;
> el contrato de distribución de la UI quedó aprobado, pero sus gates aún no están implementados.
> La medición clean-room de los
> artefactos oficiales PyPI `1.5.0` fijó esta línea base:
>
> - wheel `nikodym-1.5.0-py3-none-any.whl`, SHA-256
>   `5bc4ad78d6b134c199a5e392d714f35b1dac9807c59ff2a47eea4589e297f015`;
> - sdist `nikodym-1.5.0.tar.gz`, SHA-256
>   `9d7db9efabb6590db492c71ac9f2c11043d5b431d4e0ab49cfb07a92fef9e524`;
> - `pip install "nikodym[ui]==1.5.0"` instala el backend, pero faltan console script,
>   `nikodym/ui/__main__.py`, `static/index.html` y assets JS/CSS; el sdist tampoco trae una fuente
>   frontend utilizable para completar el producto durante la instalación.
>
> Los hashes se contrastaron con el JSON oficial de PyPI. La medición se realizó fuera del checkout;
> su ruta temporal no forma parte de este contrato. B2.0 habilita B2.1–B2.5, cuya implementación y
> verificación siguen pendientes.
>
> **Registro de revisión B2.0:** base
> `dd89f7d35cefb0aebb4ec2055c4ca81c171dd59e`; revisión adversarial final **sin P0/P1/P2** y
> auditoría independiente de la API **APROBADA**, ambas cerradas el 2026-07-23. Esta aprobación
> contractual no declara distribuida la UI ni cambia los artefactos `1.5.0`.

| Campo | Valor |
|---|---|
| **SDD** | 25 |
| **Módulo** | Infraestructura de proyecto (`pyproject.toml`, `uv.lock`, `.github/`). No es un paquete de `src/nikodym/`. |
| **Fase** | F0 |
| **Tanda de producción** | T1 (Fundación) |
| **Estado** | ✅ Fundación implementada; revisión B2 aprobada; gates de distribución pendientes |
| **Depende de** | — (no depende de ningún módulo `nikodym`; define el contenedor del que todos dependen) |
| **Lo consumen** | Todos los SDD (cada dominio declara su extra y sus deps aquí); en especial SDD-01 (`uv_lock_hash` del `LineageBundle`), SDD-24 (CI de tests), SDD-05 (extra `[sweep]`), SDD-12/13/14/18/20/23/26 (extras de dominio). |
| **Autor / Fecha** | DanIA (fan-out Tanda 1) / 2026-06-23 · rev. **Tanda 1 Rev** 2026-06-24 |

---

## 1. Propósito y responsabilidad

**Qué resuelve (una frase).** Define el **contenedor distribuible y reproducible** del proyecto:
cómo se empaqueta `nikodym` (build backend, layout, versionado), qué se instala en el núcleo base vs
tras qué **extra** opcional, cómo se fija el árbol de dependencias (`uv.lock`) y cómo la CI garantiza
calidad ejemplar —paquete Apache-2.0 y cierre base + meta-extra `all` permisivo; `[pdf]` opt-in,
auditado y documentado aparte.

**Responsabilidad única (qué SÍ hace).**
- Especifica el **`pyproject.toml`** completo: `[build-system]` (hatchling), `[project]` (metadata, `dependencies` base), `[project.optional-dependencies]` (mapa de **extras de usuario**), `[dependency-groups]` (PEP 735: test/lint/docs/dev), `[tool.hatch.*]`, `[tool.uv.*]`, y la config de `ruff`/`mypy`/`pytest`/`coverage`.
- Fija la **frontera núcleo-base ↔ extras**: qué deps se instalan siempre (coherente con SDD-01 §10) y cuáles quedan tras extra con **import perezoso** y mensaje de error claro.
- Preserva los **constraints vigentes** críticos (en especial `scikit-learn>=1.6,<1.8`) y los
  vetos de licencia; una reapertura de UI no re-resuelve dependencias ajenas.
- Define la **reproducibilidad de entorno**: `uv.lock` pineado, su hash al `LineageBundle` (SDD-01 §9), y la matriz de versiones de Python soportadas.
- Define la **CI** (GitHub Actions): ruff, mypy (`strict = true` en todo el paquete, cubriendo la
  API pública), pytest, build + smoke test del wheel; el **versionado SemVer** del paquete y el
  **changelog**. La dependencia de desarrollo `pre-commit` existe, pero hoy no hay
  `.pre-commit-config.yaml`; B2 no afirma ni implementa ese contrato histórico pendiente.
- Para la UI, define además la cadena reproducible `web/` → `src/nikodym/ui/static/`, su inventario
  de licencias/notices Node, el candidate wheel clean-room y la regla de publicar exactamente los
  artefactos gateados.

**Límites explícitos (qué NO hace, y quién lo hace).**
- **No define la estrategia de tests** (qué se testea, fixtures, property-based, golden values): eso es **SDD-24**. SDD-25 solo aporta la **infraestructura** que ejecuta esos tests (config de pytest/coverage, jobs de CI, matriz).
- **No define `schema_version`** del config (SemVer del *schema*, SDD-05 §5.4); aquí se define el **SemVer del paquete** (`project.version`), que es **distinto**.
- **No declara los sub-configs ni la lógica de import perezoso de cada dominio**: SDD-25 fija el **contrato** (qué extra, qué piso de versión, qué mensaje al faltar) y la utilidad común `require_extra(...)`; cada SDD de dominio la usa.
- **No empaqueta datos ni secretos**: el `.gitignore` (vetando datos/secretos) y la política de exclusión los gobierna el proyecto (AGENTS); aquí se asegura además que wheel/sdist no arrastren
  fixtures demo, `.vercel`, binarios de informes ni referencias automáticas a servicios externos.

---

## 2. Contexto y ubicación en la arquitectura

- **Capa:** Ingeniería / Fundación (transversal). Es el **andamiaje del repositorio**, no un módulo
  Python importable. Vive en la raíz: `pyproject.toml`, `uv.lock`, `.github/workflows/`,
  `CHANGELOG.md`, `LICENSE`.
- **Quién lo consume:** *todos*. Cada SDD de dominio que agrega una dependencia pesada **añade su extra aquí** y usa `require_extra(...)` para el import perezoso. SDD-01 lee el hash de `uv.lock` para el `LineageBundle`. SDD-24 corre sus suites bajo la CI definida aquí.
- **A quién invoca:** a `uv` (resolución/lock/sync/build), a `hatchling` (build backend) y a las
  herramientas de CI configuradas (`ruff`, `mypy`, `pytest`). No invoca código `nikodym` en tiempo
  de build.

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
   ▼ ruff · mypy(strict=true, todo el paquete) · pytest(matriz Py) · build + smoke
```

**Interacción con el `Study` y el config declarativo.** Indirecta pero crítica: el `config_hash` identifica el *experimento*, pero la **reproducibilidad bit a bit** (SDD-01 §9) exige además fijar el *entorno*. Eso lo aporta `uv.lock`, cuyo hash entra al `LineageBundle.uv_lock_hash`. Sin este SDD, dos corridas con el mismo config podrían divergir por versiones distintas de librerías.

---

## 3. Conceptos y fundamentos

- **`src/` layout** — el paquete vive en `src/nikodym/`, no en la raíz. Beneficio: la suite de tests corre contra el paquete **instalado** (no contra el árbol de fuentes accidentalmente importable), atrapando errores de empaquetado (módulos no incluidos, `MANIFEST` incompleto). Es la práctica recomendada por PyPA y la fijada por D-PKG (ESPEC §3.3).
- **Build backend (hatchling)** — `hatchling` es el backend de build minimalista de Hatch; produce sdist+wheel desde `pyproject.toml` puro (PEP 517/518/621), sin `setup.py`. No requiere instalar `hatch` (el gestor de entornos) para construir: basta `hatchling` en `[build-system].requires`. (Verificado context7.)
- **Extra de usuario (`[project.optional-dependencies]`)** — grupos de dependencias **opcionales que
  se redistribuyen en los metadatos del wheel**: `pip install nikodym[xgboost]` los resuelve. Son
  para funcionalidad opcional *del usuario final*. El cierre permisivo del proyecto se expresa con
  el meta-extra explícito `all` y se activa con `--extra all`; no equivale a instalar cada extra
  declarado, porque `[pdf]` queda deliberadamente fuera.
- **Dependency group (PEP 735, `[dependency-groups]`)** — grupos **de desarrollo, NO publicados en los metadatos del paquete**: `test`, `lint`, `docs` y `dev` (este último agrega los tres vía `include-group` + `pre-commit`). Un consumidor de PyPI nunca los recibe. uv los lee de esta tabla; el grupo `dev` es especial y se sincroniza por defecto. (Verificado context7.) **Esta es la pieza que permite usar `hypothesis` (MPL-2.0, copyleft débil) sin redistribuir copyleft**: vive en `[dependency-groups].test`, jamás en el wheel.
- **`uv.lock`** — lockfile universal y multiplataforma de uv que pinea el árbol *resuelto* de dependencias (versiones exactas + hashes). `uv sync --locked` falla si el lock está desactualizado → reproducibilidad garantizada en CI. Su hash sha256 alimenta el `LineageBundle` (SDD-01 §9, ESPEC §9). (Verificado context7.)
- **Import perezoso (lazy import)** — un backend pesado (xgboost, lifelines, FastAPI/Uvicorn) **no
  se importa al cargar `nikodym`**, sino dentro de la función/clase que lo usa; si falta, se levanta
  un error claro con la instrucción de instalación del extra. Mantiene el núcleo liviano (§4
  principio 9) y permite `import nikodym` sin tener todo el stack ML o web.
- **Fuente vs artefacto frontend** — `web/` es la fuente canónica. El build normal reproducible se
  versiona en `src/nikodym/ui/static/`; desde ese árbol versionado, wheel y sdist se construyen e
  instalan **sin Node**. Node/pnpm solo regeneran y verifican el artefacto antes del build Python.
- **Toolchain frontend pineado** — B2.1 fija Node `22.22.2` en `.node-version` y
  `"packageManager": "pnpm@11.15.0"` en `web/package.json`; `pnpm install --frozen-lockfile` es la
  única instalación de CI. Las herramientas de build se reclasifican a `devDependencies`; esa
  clasificación organiza el proyecto, pero **no prueba qué terminó redistribuido**. La procedencia
  autoritativa del bundle la registra Vite durante el build normal (§6).
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

    Un extra no presente en EXTRA_TO_DISTRIBUTIONS conserva el mensaje literal.
    El mapa cataloga solo extras atendidos por require_extra; otros poseen validación
    específica. El test de inclusión y los tests por composición se fijan en §11.
    """
    ...

def has_extra(extra: str, *modules: str) -> bool:
    """True si todos los módulos del extra están importables (sin levantar)."""
    ...

# Mapa extra -> MÓDULOS importables atendidos por require_extra. Es un catálogo
# de inclusión, no una expansión transitiva ni una biyección: extras como excel/docx
# poseen validación específica en su módulo, y el extra ui compone otros extras.
EXTRA_TO_DISTRIBUTIONS: dict[str, tuple[str, ...]] = {
    "scoring":     ("optbinning", "statsmodels", "sklearn"),
    "ml":          ("sklearn",),          # SVM/RF nativos de sklearn (módulo import = "sklearn")
    "xgboost":     ("xgboost",),
    "lightgbm":    ("lightgbm",),
    "catboost":    ("catboost",),
    "tuning":      ("optuna",),
    "explain":     ("shap", "matplotlib"),
    "forecasting": ("statsmodels", "pmdarima"),
    "survival":    ("lifelines",),
    "tracking":    ("mlflow",),
    "ui":          ("fastapi", "uvicorn"),
    "sweep":       ("hydra", "omegaconf"),
    "polars":      ("polars",),           # backend de carga opcional (SDD-02 D-DATA-1)
    # "all" se compone por unión según el pyproject vigente; `pdf` queda fuera por licencia.
}
```

`MissingDependencyError` vive en **`core.exceptions`** (no aquí; ver §8 y §10) y desciende de `NikodymError`, conforme a la regla de SDD-01 §4: `core.exceptions` aloja la raíz `NikodymError` y las excepciones del núcleo. `MissingDependencyError` es una excepción del núcleo porque la levanta la utilidad transversal `require_extra` (en `nikodym.utils`) y la consumen todos los dominios; por eso pertenece a `core`, no a un módulo de dominio. Su mensaje (español) nombra el extra y la línea exacta de instalación, p.ej.:

> `"La función requiere el extra 'xgboost'. Instálalo con: pip install 'nikodym[xgboost]' (o uv add 'nikodym[xgboost]')."`

**4.2 Comandos de ciclo de vida** (contrato operativo, no código):

| Acción | Comando canónico |
|---|---|
| Crear/actualizar el lock | `uv lock` |
| Entorno de desarrollo completo permisivo | `uv sync --locked --extra all --group dev --group test` |
| Tests del extra PDF separado | `uv sync --locked --extra pdf --group test` |
| Entorno mínimo (solo base) | `uv sync --locked --no-default-groups` |
| Construir wheel + sdist | `uv build` |
| Smoke test del wheel | `uv run --isolated --no-project --with dist/*.whl -c "import nikodym"` |
| Regenerar frontend | Node `.node-version` + pnpm `packageManager`; instalación frozen + `lint`/`typecheck`/`test`/`build` |
| Gate candidate UI | instalar `wheel[ui]` fuera del checkout y ejecutar el recorrido Playwright (§11) |
| Publicar (release) | `uv publish <wheel-gateado> <sdist-gateado>` vía OIDC; **sin rebuild** |

(Comandos alineados con la CI vigente: `uv sync --locked --extra all --group test`, job separado
`--extra pdf`, `uv build`, smoke test con `--isolated --no-project --with dist/*.whl`, `uv publish`.)

**4.3 Ejemplo de uso extremo a extremo (consumidor):**

```bash
pip install nikodym                 # núcleo base: config, Study, lineage (sin ML pesado)
pip install 'nikodym[scoring]'      # MVP scorecard; sklearn>=1.6,<1.8 vigente
pip install 'nikodym[xgboost,tracking]'   # ML gradient boosting + MLflow
pip install 'nikodym[all]'          # todo lo redistribuible (NO incluye scikit-survival)
```

```python
import nikodym                       # siempre funciona; no arrastra xgboost/FastAPI/Uvicorn
from nikodym.ml import XGBoostModel  # el import del módulo no falla...
m = XGBoostModel()                   # ...pero usar el backend sin el extra ->
m.fit(X, y)                          # MissingDependencyError con la instrucción de instalación
```

---

## 5. Configuración (el `pyproject.toml` y la matriz de extras)

`pyproject.toml` vigente es la **única fuente canónica**. B2 propone solamente este delta:

- `[project.scripts]`: `nikodym-ui = "nikodym.ui.__main__:main"`.
- Fila `[project.optional-dependencies].ui`: componer `nikodym[scoring,excel,docx]` y conservar
  FastAPI/Uvicorn/python-multipart; no duplicar distribuciones.
- Wheel y sdist: incluir `src/nikodym/ui/static/**`, excluir `web/**` y aplicar la allowlist
  ejecutable de §6.
- Frontend: `.node-version=22.22.2`,
  `web/package.json#packageManager="pnpm@11.15.0"`, instalación frozen y tooling de build bajo
  `devDependencies`.

**Todo lo demás queda literalmente fuera del cambio.** Se preservan, entre otros, `pandas<3`,
`pandera>=0.24`, `pyarrow>=14`, Jinja2 base, classifier **Beta**, URLs públicas y
`scikit-learn>=1.6,<1.8`/constraint `<1.8`, además de todos los extras/configuraciones de
lint/tests no nombrados. Aprobar B2 certifica este delta y sus gates; **no recertifica deuda
histórica ajena de SDD-25**.

<!-- B2-DELTA-END -->

---

## 6. Contratos de datos (I/O)

SDD-25 no procesa datos de negocio; sus "datos" son artefactos de build y CI.

**Input.**
- `pyproject.toml` (fuente de verdad de metadata, deps, extras, grupos, config de tooling).
- `uv.lock` (árbol resuelto y pineado; generado por `uv lock`, versionado en git).
- `src/nikodym/__init__.py` con `__version__` (fuente del SemVer; lo lee `[tool.hatch.version]`).

**Output.**
- **wheel** (`nikodym-<ver>-py3-none-any.whl`): contiene `src/nikodym/`, incluido el build
  versionado `nikodym/ui/static/index.html` + todos sus recursos locales, su metadata, el console
  script y los extras declarados. **No** contiene `tests/`, `docs/`, `[dependency-groups]`, fixtures
  demo, `.vercel`, datos ni binarios de informes.
- **sdist** (`nikodym-<ver>.tar.gz`): incluye `src/` —también el build estático ya versionado—,
  `tests/` y `LICENSE`/`README`/`CHANGELOG`. La fuente canónica `web/` permanece versionada en Git,
  pero **no** entra al sdist: publicar una fuente frontend parcial sería engañoso. Construir desde
  el sdist no ejecuta Node; consume `src/nikodym/ui/static/`.
- **hash de `uv.lock`** (sha256) → expuesto a SDD-01 para `LineageBundle.uv_lock_hash`.
- **evidencia frontend del candidate:** manifest autoritativo de procedencia por output/hash,
  inventarios declarativos pnpm full/prod normalizados, reconciliación y allowlist build-only
  aplicada, `THIRD_PARTY_NOTICES.frontend.txt` y resultados del gate anti-fixtures, registrados
  junto con los hashes.

**Allowlist ejecutable de distribución.** B2.1 añade
`scripts/distribution_contents_allowlist.json` (con `schema_version`, patrones permitidos y entradas
obligatorias separadas para wheel/sdist) y `scripts/check_distribution_contents.py`. El script abre
ZIP/TAR, rechaza toda ruta que no esté allowlisted, exige console script, `__main__`, index y notices,
y parsea el index del archivo: **cada** `src`/`href` local —JS, CSS, favicon u otro— debe resolver a
un archivo regular dentro de `static/`; escapes, faltantes o URLs locales no allowlisted fallan.
Así `web/src/fixtures/demo/**`, `.vercel`, datos y binarios demo quedan excluidos **por
construcción**, no por revisión visual ni globs dispersos.

**Procedencia autoritativa del bundle normal.** B2.1 añade y registra en la configuración normal de
Vite el plugin versionado `scripts/frontend_provenance_plugin.mjs`, con `apply: "build"` y hooks
conservadores `transform` + `generateBundle`:

- `transform` registra la unión de todos los módulos que Vite procesa y que contribuyen o podrían
  contribuir al build normal, incluidos CSS y módulos luego eliminados por tree-shaking. Los ids se
  normalizan (separadores, prefijos virtuales y query de Vite) antes de clasificarlos.
- `generateBundle` cruza esa unión con `chunk.modules` y todos los assets emitidos. Para cada output
  guarda ruta relativa, SHA-256 y módulos fuente; cada id bajo `node_modules` —incluido CSS— se
  resuelve al `package.json` propietario más cercano y a su package root normalizado, relativo y
  libre de rutas de máquina. Desde ese root recolecta **íntegramente todos** los archivos
  distribuidos cuyo basename coincide, sin distinguir mayúsculas, con `LICENSE*`, `LICENCE*`,
  `NOTICE*`, `COPYING*` o `COPYRIGHT*`, incluso en subdirectorios, además de
  author/copyright/attribution declarados en metadata. La entrada por paquete es
  `{name, version, license, package_root, license_files:[{relative_path, sha256}], author,
  copyright, attribution}`.
- Un módulo/asset externo no atribuible, metadata/licencia ambigua, paquete de procedencia sin al
  menos un texto de licencia, archivo de atribución declarado/referenciado pero ausente o texto no
  legible como tal **falla el build**. SPDX por sí solo no satisface el contrato.
- El resultado es `dist/evidence/frontend-provenance.json`, con `schema_version` y entradas por
  output/hash. Esa evidencia —no `dependencies`/`devDependencies` ni `pnpm licenses --prod`— define
  qué paquetes contribuyeron o pudieron contribuir al artefacto normal.
- `THIRD_PARTY_NOTICES.frontend.txt` se genera desde la unión real en orden determinista
  `name/version/relative_path`: encabezado del paquete con licencia y
  author/copyright/attribution, seguido por el contenido **verbatim completo**, sin truncar ni
  parafrasear, de cada archivo en ese orden. El manifest conserva el SHA-256 de cada fuente; la
  evidencia liga esos hashes y el SHA-256 final del notices a los hashes de outputs y al mismo
  candidate.

**Cierres declarativos y reconciliación.** Desde `web/`, pnpm 11.15.0 produce
`pnpm licenses list --json --long` (cierre full de build) y
`pnpm licenses list --prod --json --long` (cierre declarado de producción). El script
`scripts/check_frontend_licenses.mjs` los normaliza/ordena como
`dist/evidence/frontend-licenses.full.json` y `frontend-licenses.prod.json`. Son inventarios de
declaraciones, **no prueba de redistribución**.

- Todo `{name, version}` de la procedencia Vite debe existir en el cierre full y tener metadata
  coherente; una discrepancia falla. El cierre prod sirve para reconciliar clasificación, no para
  omitir un paquete que Vite sí observó.
- `web/frontend-build-license-allowlist.json` admite solo entradas exactas
  `{name, version, license, scope:"build-only", rationale}`. `lightningcss`/MPL-2.0 puede pasar
  únicamente con coincidencia exacta, presente en full y **ausente tanto de prod como de toda
  procedencia Vite**. Si aparece en un output, pierde la excepción y falla.
- Cualquier paquete de procedencia con GPL/LGPL/AGPL/MPL, licencia ausente/ambigua o atribución
  incoherente falla. También falla si los archivos/atribuciones exigidos por la procedencia no
  aparecen íntegros en notices o si no coinciden sus hashes. Full/prod y la allowlist se adjuntan
  solo como cierre y evidencia de reconciliación. Todos los JSON, textos fuente, notices y SHA-256
  quedan ligados al mismo candidate; regenerar después invalida la promoción.

**Gate anti-fixtures en contenido y procedencia.** El build local de demo puede consumir
`web/src/fixtures/demo/**`; el build normal distribuible no:

- el repositorio contiene el sentinel versionado
  `web/src/fixtures/demo/NIKODYM_DEMO_FIXTURE_ONLY` y
  `scripts/frontend_demo_fixture_signatures.json`, que cubre sin huecos cada fixture mediante
  SHA-256 y firmas de contenido/ventanas binarias específicas del fixture;
- el plugin de procedencia falla si cualquier id normalizado pertenece a
  `web/src/fixtures/demo/**`, aunque Vite termine eliminándolo;
- `scripts/check_frontend_bundle.mjs` recorre byte a byte todos los outputs y falla ante el literal
  `NIKODYM_DEMO_FIXTURE_ONLY`, un hash de fixture o cualquiera de sus firmas textuales/binarias.
  Esto detecta material inline o emitido aun si perdió su path fuente. El manifest también falla si
  aparece un fixture nuevo sin firma.

**Invariantes (pre/post).**
- *Cierre permisivo Python (regla dura, verificable en CI):* ninguna distribución con licencia
  **GPL/LGPL/AGPL** aparece en el cierre transitivo de la base +
  `[project.optional-dependencies].all`, obtenido con
  `uv export --format requirements-txt --extra all --no-dev`. El meta-extra `all` jamás referencia
  `[pdf]`. PDF es opt-in y se audita/documenta en un job separado porque
  WeasyPrint→Pyphen incorpora opciones copyleft; queda fuera de la garantía permisiva, no oculto
  dentro de ella. `hypothesis` permanece solo en development groups y `scikit-survival` no tiene
  extra.
- *Núcleo liviano:* `import nikodym` no importa sklearn, xgboost, lightgbm, catboost, mlflow,
  FastAPI, Uvicorn, lifelines ni statsmodels (verificable con un test que inspecciona `sys.modules`
  tras el import — §11).
- *Constraint sklearn:* scoring y sus consumidores resuelven `scikit-learn>=1.6,<1.8`; el ceiling
  global impide que extras hermanos lo amplíen accidentalmente.
- *UI completa:* el wheel contiene `entry_points.txt`, `nikodym/ui/__main__.py`,
  `nikodym/ui/static/index.html` y **cada** recurso local que cualquier `src`/`href` del índice
  referencia, favicon incluido. Si falta uno, escapa `static/` o no es archivo regular, el candidate
  no se promueve.
- *Wheel/sdist limpios:* no contienen `tests/` en wheel, `*.parquet`, `*.csv`, fixtures demo,
  `.vercel`, binarios de informes ni `dependency-groups` en metadata. Ningún output está trazado a
  `web/src/fixtures/demo/**` ni contiene sus sentinel/hashes/firmas. El HTML/JS/CSS no realiza
  requests automáticos a servicios externos.
- *Licencias/notices del bundle:* la procedencia Vite por output/hash es la fuente autoritativa;
  todo paquete observado reconcilia contra full y aporta todos sus textos
  LICENSE/LICENCE/NOTICE/COPYING/COPYRIGHT, hashes y metadata de atribución. Falta, truncamiento o
  hash distinto falla; un SPDX aislado no basta. `pnpm licenses` y la clasificación
  dependency/devDependency son evidencia declarativa auxiliar, no sustitutos de procedencia.
- *Fuente web completa solo en Git:* ni wheel ni sdist incluyen `web/`; ambos contienen únicamente
  el build normal versionado bajo `src/nikodym/ui/static/`.
- *Build Python sin Node:* `uv build` funciona con el árbol versionado sin tener Node/pnpm
  instalados. Regenerar `static/` sí requiere el toolchain frontend pineado.
- *Lock reproducible:* `uv sync --locked` no modifica el lock (falla si está desactualizado) → el árbol instalado es el pineado.
- *Versión única:* `project.version` (dynamic) == `nikodym.__version__`; el tag git de release == `v<version>`.

---

## 7. Algoritmos y flujo

> SDD-25 "ejecuta" pipelines de CI/CD, no algoritmos de cálculo. Flujo de alto nivel.

**Flujo de build (`uv build`).**
1. Como prerequisito de CI/release, el job frontend regenera desde `web/`, audita licencias/notices
   y exige que `src/nikodym/ui/static/` quede idéntico a Git.
2. Ya sin depender de Node, `uv` lee `[build-system]` e invoca `hatchling.build` (PEP 517).
3. `hatchling` resuelve la versión dinámica desde `src/nikodym/__init__.py`.
4. Construye wheel y sdist incluyendo el build estático versionado y aplicando las exclusiones.
5. Los hashes de ambos artefactos quedan fijados como candidates; todos los gates posteriores
   consumen esos mismos bytes.

**Flujo de import perezoso (`require_extra`).**
1. Un método de dominio (p.ej. `XGBoostModel.fit`) llama `xgb, = require_extra("xgboost", "xgboost")`.
2. `require_extra` intenta `importlib.import_module("xgboost")`.
3. Éxito → devuelve el módulo. `ImportError`/`ModuleNotFoundError` → levanta `MissingDependencyError` con el mensaje de instalación derivado de `EXTRA_TO_DISTRIBUTIONS["xgboost"]`.
*Decisión:* el import ocurre **dentro del método que lo necesita**, no a nivel de módulo, para que `from nikodym.ml import XGBoostModel` nunca falle por ausencia del extra (solo falla al *usarlo*). *Alternativa descartada:* `try/except ImportError` a nivel de módulo con clase stub — más frágil y oculta el punto de fallo.

**Flujo de CI (push/PR → GitHub Actions).**
1. **Job `quality`** (rápido, una versión de Python): checkout → `astral-sh/setup-uv` → `uv sync --locked --group lint` → `ruff check` + `ruff format --check` → `mypy` (`strict = true`, todo el paquete; ver §5).
2. **Job `test`** (matriz `python: [3.11, 3.12, 3.13] × os: [ubuntu, macos, windows]`):
   `uv sync --locked --group test --extra scoring` → `pytest --cov`. El job `test-all` usa
   exactamente `uv sync --locked --python 3.12 --extra all --group test` y corre la suite del
   meta-extra permisivo (incl. tests `requires_xgboost`/`requires_lightgbm`/`requires_catboost`/
   `requires_forecasting` y el meta-test de familias de SDD-24); `gbdt_nondeterministic` va `xfail`.
   `[pdf]` no entra: el job `test-pdf` instala `--extra pdf --group test` en Linux y ejecuta sus
   tests reales por separado.
   - **Subset en ramas (no-`main`/no-PR):** solo `python=3.12 × os=ubuntu` con `--extra scoring`
     (sin matriz completa ni `--extra all`), para feedback rápido; la matriz completa se reserva a
     `main` y PRs.
2bis. **Job `coverage-regulatory`** (cablea el 100% por-módulo que delega SDD-24 §11): `pytest --cov=nikodym.core.exceptions --cov=nikodym.core.seeding --cov=nikodym.provisioning.cmf --cov=nikodym.provisioning.ifrs9 --cov-fail-under=100` (código regulatorio: 0 branches sin testear). El gate global 90 lo impone `fail_under=90` del job `test`.
3. **Job `frontend`**: Node desde `.node-version`, Corepack exige
   `packageManager=pnpm@11.15.0`, instalación frozen; lint/typecheck/Vitest/build normal.
   El plugin Vite registrado ejecuta `transform`+`generateBundle`, emite procedencia por output/hash
   y veta cualquier módulo de fixtures demo. `check_frontend_bundle.mjs` aplica además el gate de
   sentinel/hashes/firmas. `pnpm licenses list --json --long` y `--prod --json --long` alimentan
   `check_frontend_licenses.mjs`, que reconcilia ambos cierres declarativos contra la procedencia,
   aplica la allowlist build-only exacta y genera notices **desde la procedencia**. Luego se
   verifican cero requests externos y diff/status limpio.
4. **Job `build`** (depende de `frontend`): `uv build` sin Node →
   `scripts/check_distribution_contents.py` sobre wheel/sdist + smoke de import + verificación
   anti-copyleft Python sobre
   `uv export --format requirements-txt --extra all --no-dev` y
   `License-Expression: Apache-2.0`. Registra SHA-256 de wheel/sdist candidates.
5. **Job `candidate-ui`**: fuera del checkout instala **solo** `<candidate-wheel>[ui]`, lanza
   `nikodym-ui --no-open` y ejecuta el gate Playwright de §11; no resuelve el proyecto ni reutiliza
   su entorno.
6. **Job `lock-check`**: `uv lock --check`.
7. **Job `release`** (solo en tag `v*` y con OK específico de Cami): publica por Trusted Publishing
   **exactamente el wheel y sdist cuyos hashes pasaron los gates**. No ejecuta `uv build` ni otro
   rebuild.

**Pre-commit.** `pyproject.toml` conserva la dependencia de desarrollo histórica, pero no existe una
configuración versionada de hooks. B2 no crea ni certifica `.pre-commit-config.yaml`; el gate
obligatorio es el job `quality` descrito arriba.

**Complejidad / rendimiento.** Irrelevante en cómputo; lo relevante es el **tiempo de CI**: cacheo de `uv` (`setup-uv` con cache), `--locked` evita re-resolución, la matriz completa solo en `main`/PR (push a ramas: subset).

---

## 8. Casos borde y manejo de errores

- **Extra ausente al usar un backend** → `MissingDependencyError` (desc. de `NikodymError`) con la línea de instalación exacta. **Nunca** un `ImportError` crudo ni un `AttributeError` confuso. (Mensaje en español, §4.1.)
- **Extra parcialmente instalado** (p.ej. `xgboost` presente pero `scikit-learn<1.6`): `require_extra` solo verifica importabilidad; el **piso de versión** lo garantiza el resolutor (`uv`/`pip`) al instalar el extra. Si alguien fuerza un downgrade manual, el fallo aflora en `check_estimator` (SDD-24), no en `require_extra` — documentado como caveat.
- **`uv.lock` desactualizado en CI** → `uv sync --locked` / `uv lock --check` **fallan** el job (no se auto-actualiza en CI; el dev corre `uv lock` localmente y commitea).
- **Base o meta-extra `all` arrastra copyleft transitivo** → el job anti-copyleft **falla el build**
  y nombra la distribución infractora. `[pdf]` no se mezcla con ese cierre: su job separado audita y
  documenta WeasyPrint→Pyphen y verifica que nunca sea alcanzable desde `all`.
- **`scikit-survival` solicitado** → no existe extra para él; si un usuario lo instala aparte, queda **fuera del wheel distribuido** y fuera del soporte (research only, ESPEC §7).
- **Dependencia opcional de reporte ausente** (SDD-26): WeasyPrint, python-docx, openpyxl,
  matplotlib o el cliente IA se cargan perezosamente. El formato degrada con aviso o falla según su
  config; el HTML base sigue operativo. La fuente `.qmd` no ejecuta ni requiere Quarto.
- **Python fuera de rango** (`<3.11`) → el resolutor rechaza la instalación por `requires-python`.
- **Build con `tests/` colándose al wheel** → atrapado por el test de empaquetado (§11) que inspecciona el contenido del wheel.
- **Build estático ausente/incompleto** → inspección del candidate falla si no existen console
  script, `__main__.py`, `index.html` o cualquiera de sus `src`/`href` locales (favicon incluido).
  El control negativo borra un recurso obligatorio en una instalación descartable y exige fallo
  del launcher antes de bind.
- **Metadata/texto de licencia Node ausente o ambiguo** → falla el job frontend; no se interpreta
  ausencia como permiso. También falla un archivo LICENSE/LICENCE/NOTICE/COPYING/COPYRIGHT o de
  atribución declarado/referenciado que falte, esté truncado o no coincida con su hash.
- **MPL-2.0 en Node** → `lightningcss` solo se admite en full mediante entrada build-only exacta y
  ausencia de prod/procedencia. Si contribuye o podría contribuir a cualquier output, falta del
  allowlist o no coincide exactamente en nombre/versión/licencia, falla.
- **Fixture demo llega al build normal** → falla por id de módulo en la procedencia o por el gate
  bytewise de sentinel/hash/firma; un fixture nuevo sin entrada en el manifest también falla.
- **Artefacto frontend hace requests externos** → Playwright lo bloquea y falla el candidate; fuentes
  y runtime deben ser autocontenidos.
- **El job release reconstruye** → violación del contrato: release solo puede publicar los hashes
  gateados, no bytes producidos de nuevo.
- **Versión inconsistente** (`__version__` ≠ tag) → el job `release` valida `v<__version__> == tag` y aborta si difieren.

**`MissingDependencyError`** vive en **`core.exceptions`** y desciende de `NikodymError` (regla SDD-01 §4: `core.exceptions` aloja la raíz y las excepciones del núcleo). Justifica vivir en `core` —no en un módulo de dominio— porque la usan todos los dominios y `require_extra` (en `nikodym.utils`) necesita levantarla sin importar nada pesado. SDD-25 fija su mensaje (§4.1); su definición formal es de SDD-01.

---

## 9. Reproducibilidad y auditoría

- **`uv.lock` es el ancla de reproducibilidad de entorno.** Pinea versiones exactas + hashes de todo el árbol resuelto; `uv sync --locked` garantiza que el entorno instalado == el pineado. Su **hash sha256** entra al `LineageBundle.uv_lock_hash` (SDD-01 §9, ESPEC §9, §12 R3). Sin él, el `config_hash` identifica el experimento pero no el entorno → reproducibilidad incompleta.
- **`library_versions` del lineage** (SDD-01) se complementa con el lock: el bundle registra qué versiones corrieron; el lock permite **recrear** ese entorno.
- **Determinismo de build:** el build frontend versionado se regenera con toolchain/lock pineados y
  diff limpio; hatchling consume luego ese árbol sin Node. Los SHA-256 fijados enlazan inspección,
  clean-room y publicación sin rebuild.
- **Auditoría de licencias:** los jobs Python y Node dejan inventarios de licencias/notices por
  release. Para Node, el manifest Vite por output/hash prueba procedencia y full/prod solo cierran
  declaraciones; los notices nacen del primero e incluyen todos los textos completos, metadata de
  atribución, hashes fuente y hash final. En ambos, metadata/texto ausente o ambiguo falla; una
  allowlist explícita debe resolver la excepción antes de promover el candidate.
- **SemVer + changelog:** cada release etiqueta `v<x.y.z>` y actualiza `CHANGELOG.md` (formato *Keep a Changelog*); breaking changes → bump mayor. Trazabilidad de qué cambió entre versiones distribuidas.
- **Caveat honesto:** el lock fija versiones, pero el **determinismo numérico** de GBDT multihilo sigue siendo el de SDD-01 (`strict_determinism`); el packaging no lo resuelve, solo asegura que la *misma* versión de la lib corre.

---

## 10. Dependencias

**Internas:** ninguna en build time. En runtime, la utilidad `require_extra` vive en `nikodym.utils` y levanta `MissingDependencyError` de `core.exceptions` (única dependencia conceptual hacia `core`).

**Externas — build/CI (no se redistribuyen en el wheel salvo el backend):**

| Herramienta | Versión mín. | Licencia | Rol | Redistribuida en wheel |
|---|---|---|---|---|
| hatchling | ≥1.27 | MIT ✅ | build backend (PEP 517); ≥1.27 por metadata PEP 639/License-Expression (C15) | No (build-only) |
| uv | ≥0.5 | Apache-2.0/MIT ✅ | gestor/lock/build/publish | No (tooling) |
| ruff | ≥0.5 | MIT ✅ | lint + format (`[dependency-groups].lint`) | No |
| mypy | ≥1.10 | MIT ✅ | type-check `strict = true` (todo el paquete; ver §5) | No |
| pytest (+pytest-cov) | ≥8.1 / ≥5.0 | MIT ✅ | runner de tests (`test`) | No |
| hypothesis | ≥6.100 | **MPL-2.0** (copyleft débil) | property-based (`test`) | **No — dev-only (clave §3)** |
| pre-commit | ≥3.7 | MIT ✅ | hooks locales (`dev`) | No |
| mkdocs-material | ≥9.5 | MIT ✅ | docs del repo (`docs`) | No |
| Node.js | `22.22.2` (`.node-version`) | licencias del runtime, no redistribuido | ejecutar el toolchain de `web/` | No |
| pnpm | `11.15.0` (`packageManager`) | MIT ✅ | instalación frozen, scripts e inventarios | No |

**Núcleo base redistribuido.** La lista canónica vive en `[project.dependencies]`; B2 no congela un
conteo duplicado. Incluye y preserva explícitamente pydantic, numpy, `pandas<3`, `pandera>=0.24`,
`pyarrow>=14`, joblib, Jinja2 y PyYAML, todas permisivas. Pandas es el contrato de I/O universal
(SDD-05 §6); pandera/pyarrow son base de `data` (SDD-02 §10, C01); Jinja2 sostiene el HTML
determinístico.

**Extras opcionales.** B2 modifica solo `[ui]` (§5). La garantía dura permisiva cubre la base y el
meta-extra `[all]`, no toda fila opcional indiscriminadamente: `[all]` excluye `[pdf]` y el test de
propiedad impide que lo incorpore. `[pdf]` es opt-in separado; su cierre WeasyPrint→Pyphen se
inventaría, audita y documenta aparte, sin presentarlo como parte del cierre permisivo. `hypothesis`
(MPL-2.0) permanece confinado a `[dependency-groups]`; `scikit-survival` no tiene extra.

> **Verificación de licencias (context7/fuente oficial):** los pisos y licencias de las distribuciones se toman de ESPEC §7 (tabla ya verificada en Tanda 0). La **mecánica de packaging** (qué tabla redistribuye y cuál no) se verificó con la doc oficial de uv: extras (`[project.optional-dependencies]`) se publican y sincronizan con `--extra`; grupos (`[dependency-groups]`, PEP 735) son dev-only y no viajan en el wheel. Esto sustenta el confinamiento de `hypothesis`.

---

## 11. Estrategia de tests

Detalle transversal en **SDD-24**; lo específico del **empaquetado** (tests que SDD-25 aporta):

- **Build + smoke (CI).** `uv build` sin Node produce wheel+sdist; el smoke aislado confirma import
  base y la inspección comprueba entry point, `__main__`, index/todos sus recursos locales y
  exclusiones.
- **Núcleo liviano (test de aislamiento).** Tras `import nikodym` en un entorno **solo-base** (sin
  extras), inspeccionar `sys.modules`: **ausentes** `sklearn`, `xgboost`, `lightgbm`, `catboost`,
  `mlflow`, `fastapi`, `uvicorn`, `lifelines`, `statsmodels`. **Presentes y aceptables** (deps base):
  `pandas`, `pandera`, `pyarrow`, `numpy`, `pydantic`, `joblib`, `yaml`. `polars` permanece ausente.
- **Import perezoso (mensaje al usuario).** En un entorno sin el extra `xgboost`, usar el backend levanta `MissingDependencyError` cuyo mensaje **contiene** `"nikodym[xgboost]"`. Test parametrizado sobre todos los extras de `EXTRA_TO_DISTRIBUTIONS`.
- **Contenido del wheel/sdist.** `scripts/check_distribution_contents.py` aplica la allowlist
  versionada a ambos, exige console script/`__main__`/index/notices, parsea cada `src`/`href` local
  —favicon incluido— y rechaza faltantes, escapes o cualquier entrada extra; `web/` y sus fixtures
  demo no pueden entrar.
- **Anti-copyleft (mecánica especificada, C16).** Mitigación central de R-LIC; el verificador se define explícito (un invariante "verificable en CI" cuyo verificador no esté definido no garantiza nada):
  - **Entrada/herramienta:** `uv export --format requirements-txt --extra all --no-dev` produce el
    **cierre transitivo exacto base + meta-extra `all`** del lock (no solo deps directas). Por cada
    distribución se obtiene su SPDX de la metadata instalada (`importlib.metadata` →
    `License-Expression` de core-metadata 2.4 si existe; si no, se normalizan `License` legacy y
    classifiers Trove con parser SPDX). *(pip-licenses opera sobre el entorno instalado, no sobre el
    lock; por eso se prefiere `uv export`.)*
  - **Lista CERRADA de SPDX vetados en ese cierre:** toda variante de `GPL-*`, `LGPL-*`, `AGPL-*`
    (p.ej. `GPL-2.0-only`, `GPL-3.0-or-later`, `LGPL-2.1`, `AGPL-3.0`). `MPL-2.0` permanece fuera
    porque `hypothesis` es dev-only.
  - **Política ante licencia AUSENTE/AMBIGUA: `FALLAR` por defecto** (allowlist explícita por dist conocida, no denylist): ninguna licencia no clasificada pasa en silencio — un falso negativo derrotaría la garantía.
  - **Frontera PDF comprobable:** un test sobre `pyproject.toml` exige que `[all]` no nombre
    `nikodym[pdf]`; un job distinto instala/exporta `--extra pdf`, archiva su inventario y documenta
    WeasyPrint→Pyphen. PDF no pasa ni pretende pasar el gate permisivo de `all`.
  - **Alcance:** base + `all`, alineado con `.github/workflows/ci.yml`; falla el build nombrando la
    distribución y su SPDX infractor.
- **Lock al día.** `uv lock --check` no produce cambios (el lock refleja `pyproject.toml`).
- **Coherencia de versión.** `nikodym.__version__` parsea como SemVer y, en release, coincide con el tag git.
- **Coherencia extra↔config (propiedad).** El mapa de `require_extra` es de **inclusión**:
  `set(EXTRA_TO_DISTRIBUTIONS) ⊆ set([project.optional-dependencies]) - {"all"}`; las tuplas son
  módulos importables directos, no el cierre transitivo. Tests específicos prueban que `[ui]`
  compone `scoring`/`excel`/`docx`, conserva `scikit-learn>=1.6,<1.8` y que todo extra nombrado en
  mensajes exista en `pyproject.toml`; además `[all]` excluye de forma explícita `[pdf]`.
- **Matriz de Python.** La suite base corre en 3.11/3.12/3.13 (la matriz de CI es el "test").
- **Frontend reproducible.** Node 22.22.2 + pnpm 11.15.0 + lock frozen; lint/typecheck/Vitest/build;
  procedencia Vite conservadora por output/hash; toda procedencia reconcilia con el cierre pnpm full;
  full/prod normalizados no se usan como prueba de redistribución; allowlist build-only exacta y
  notices determinísticos derivados de procedencia; regeneración deja diff/status limpios. Los tests
  crean paquetes fixture con múltiples LICENSE/LICENCE/NOTICE/COPYING/COPYRIGHT y metadata de
  atribución, verifican inclusión íntegra/verbatim en orden `name/version/path`, hashes fuente y hash
  final; negativos cubren texto de licencia ausente, referencia ausente, truncamiento y hash distinto.
- **Anti-fixtures del bundle normal.** Pruebas unitarias del plugin fijan normalización de ids
  pnpm/CSS, package root y manifest
  `{name,version,license,package_root,license_files,author,copyright,attribution}`; el build normal
  falla ante cualquier módulo bajo `web/src/fixtures/demo/**`. El manifest de firmas debe cubrir cada
  fixture y el scanner se prueba con negativos separados: módulo tree-shaken, JSON inline, sentinel
  textual y binario emitido.
- **Candidate UI clean-room.** Fuera del checkout, instalar solamente `<wheel>[ui]`; lanzar
  `nikodym-ui --no-open`; Playwright permite loopback y cero red externa. Ejecutar hasta
  `done`+resultados+HTML: `f1-estandar-consumo`/`consumo_comportamiento`,
  `f3-provisiones-consumo`/`provisiones_consumo` y
  `f4-ifrs9-retail`/`ifrs9_retail_latam`; además F1 con CSV externo y `loan_id` no nulo/único. Negativos de
  Host/Origin/token deben fallar. Playwright enumera **cada** `src`/`href` local del index —incluido
  favicon— y exige HTTP 200; PDF puede degradar, HTML no.
- **Control negativo.** Copiar la instalación a un entorno descartable, eliminar
  `static/index.html` y, en un caso separado, el favicon/u otro recurso local obligatorio; en ambos
  el launcher termina antes de bind.
- **Release por promoción.** Comparar SHA-256 de los candidates gateados con los archivos entregados
  al job de publicación; el workflow no contiene un segundo build.

**Fixtures.** Wheel construido en un tmpdir; entorno virtual efímero (`uv venv`) para el smoke; un módulo de dominio *dummy* que llama `require_extra("inexistente", "modulo_que_no_existe")` para validar el mensaje sin depender de un backend real.

---

## 12. Decisiones abiertas y riesgos

**Decisiones resueltas en este SDD (trazabilidad).**
- **D-PKG-1 — hatchling como build backend** (no setuptools/poetry/flit). *Porqué:* mínimo, PEP 621 puro, sin `setup.py`, versión dinámica desde `__init__.py`; lo fija D-PKG (ESPEC §3.3). *Alternativa descartada:* `poetry` (su tabla `[tool.poetry]` precede a PEP 621 y duplica metadata; menos estándar). **Reversible** sin tocar código de `nikodym` (solo `[build-system]`).
- **D-PKG-2 — Frontera núcleo-base ↔ extras.** La base canónica vigente (§10) incluye
  pydantic, numpy, pandas, pandera, pyarrow, joblib, Jinja2 y PyYAML; todo
  ML/forecasting/UI/tracking queda tras extra con import perezoso. *Porqué:* núcleo liviano (§4
  principio 9) + `import nikodym` siempre funciona. SDD-01 distingue dependencia de distribución de
  import del core y delega el mapa a este SDD. Los extras `tuning` y `explain` provienen de
  ESPEC §7/SDD-13/14 y permanecen en el `pyproject.toml` canónico; B2 no reabre ese mapa salvo `[ui]`.
- **D-PKG-3 — `[dependency-groups]` (PEP 735) para test/lint/docs/dev, no extras.** *Porqué:* no se publican en el wheel → permiten `hypothesis` (MPL-2.0) sin redistribuir copyleft; uv los gestiona nativamente. *Alternativa descartada:* un extra `[dev]` (se publicaría en metadata; ensucia y arrastra copyleft débil al artefacto).
- **D-PKG-4 — `scikit-learn>=1.6,<1.8` vigente.** El piso responde a `check_estimator`/tags y el
  techo operativo vive también en `constraint-dependencies`. B2 lo hereda por `scoring` y no lo
  reabre.
- **D-PKG-5 — `requires-python>=3.11`, matriz 3.11–3.13.** *Porqué:* 3.11 es el piso razonable a 2026 (mejoras de typing/perf); evita cargar compat de 3.9/3.10. *Reversible* si un cliente institucional exige 3.10.
- **D-PKG-6 — Versión dinámica desde `src/nikodym/__init__.py`** (no tag VCS). *Porqué:* fuente única legible, sin acoplar el build a git en entornos sin historia. *Alternativa considerada:* `hatch-vcs` (versión desde tags) — más automático pero falla en sdist sin `.git`; reevaluable.
- **D-PKG-7 — Frontend fuente + build versionado (APROBADA CONTRACTUALMENTE EN B2.0;
  IMPLEMENTACIÓN PENDIENTE).** `web/` es la fuente canónica;
  permanece completo en Git y no entra a wheel/sdist. `src/nikodym/ui/static/` es el build
  reproducible distribuido. Regenerarlo requiere el toolchain pineado; construir/instalar no. La
  allowlist ejecutable de contenido y el diff/status limpio cierran el contrato.
- **D-PKG-8 — Extra `[ui]` autocontenido (APROBADA CONTRACTUALMENTE EN B2.0; IMPLEMENTACIÓN
  PENDIENTE).** Compone
  `nikodym[scoring,excel,docx]` y añade FastAPI/Uvicorn/multipart, sin duplicar distribuciones ni
  cambiar constraints. Los recorridos F1/F3/F4 exigen HTML; PDF degrada explícitamente.
- **D-PKG-9 — Release por promoción (APROBADA CONTRACTUALMENTE EN B2.0; IMPLEMENTACIÓN
  PENDIENTE).** El job de publicación recibe los mismos
  wheel/sdist cuyos SHA-256 pasaron inspección y clean-room. Se prohíbe reconstruir en release.
- **D-PKG-10 — Procedencia Vite, no manifiesto de declaraciones (APROBADA CONTRACTUALMENTE EN
  B2.0; IMPLEMENTACIÓN PENDIENTE).** El plugin normal
  registrado en Vite observa módulos/assets y produce evidencia por output/hash; de ahí nacen los
  notices completos (todos los LICENSE/LICENCE/NOTICE/COPYING/COPYRIGHT y atribuciones, con hashes).
  `pnpm licenses` full/prod solo reconcilia los cierres declarados. Una licencia build-only se
  exceptúa únicamente cuando su paquete exacto está ausente de procedencia.
- **D-PKG-11 — Cierre permisivo = base + `[all]`, no todas las filas (APROBADA CONTRACTUALMENTE EN
  B2.0; IMPLEMENTACIÓN PENDIENTE).** CI usa
  `--extra all`; `[pdf]` queda fuera y un test de propiedad impide incorporarlo. Su cierre
  WeasyPrint→Pyphen se prueba, inventaría y documenta en un job opt-in separado.

**Decisiones abiertas (delegadas).**
- **Dependencias de reporte — RESUELTO.** Jinja2 está en la base para el HTML determinístico;
  `[report]` agrega figuras opcionales, `[pdf]` agrega WeasyPrint y `[docx]` agrega python-docx.
  `[pdf]` no entra en `[all]` por WeasyPrint→Pyphen y se audita en su job separado. La fuente `.qmd`
  es un export de texto y no invoca ni exige el binario Quarto. Ver SDD-26.
- **Trusted Publishing (OIDC) vs token PyPI** para el job `release`. *Sugerencia:* OIDC (sin secretos). *Responsable:* DanIA al armar el repo público.
- **`hatch-vcs` (versión por tag) vs `__init__.py`** — reevaluar al primer release público (SDD-26/F1).
- **Política de `default-groups` de uv — RESUELTO (Tanda 1 Rev):** `default-groups = ["dev"]` en `[tool.uv]` (dev incluye test/lint/docs); entorno limpio con `--no-default-groups`. Ver §5.
- **Email de contacto público del paquete.** El `authors.email` viaja en la metadata pública del wheel (PyPI). `admin@nxlabs.cl` es personal/administrativo; para una librería que es escaparate de la consultora Nikodym, conviene un alias de proyecto (p.ej. `contacto@`/`opensource@`). *Sugerencia:* alias de proyecto. *Responsable:* DanIA + Cami al armar el repo público (F1).

**Riesgos.**
- **R-LIC — copyleft se cuela al cierre anunciado como permisivo.** *Mitigación:* export exacto
  `--extra all --no-dev` → parser SPDX → lista cerrada GPL/LGPL/AGPL → fail ante metadata
  ausente/ambigua; test `[pdf] ∉ [all]`; PDF/WeasyPrint→Pyphen con inventario separado.
  `hypothesis` queda dev-only y `scikit-survival` sin extra. Detalle §11.
- **R-LIC-NODE — licencia o notice frontend no clasificado.** La cadena Node se audita
  con procedencia Vite por output/hash reconciliada contra inventarios full/prod. Una dependencia
  MPL como `lightningcss` solo puede pasar mediante allowlist build-only exacta y ausencia
  demostrada de prod **y procedencia**; metadata ambigua o presencia MPL/copyleft en un output
  falla. SPDX sin textos no basta: todo texto/atribución y sus hashes deben estar en manifest/notices.
- **R-FIXTURE — un fixture de la demo entra inline o como asset.** *Mitigación:* veto por id en el
  plugin, sentinel versionado, manifest exhaustivo de hashes/firmas textuales/binarias y scanner de
  todos los outputs; cualquiera de las señales falla el build normal.
- **Drift `web/` ↔ `static/`.** *Mitigación:* toolchain/lock pineados, regeneración en CI y
  diff/status limpio antes de construir candidates.
- **Rebuild entre gate y PyPI.** *Mitigación:* promoción por hashes; release no ejecuta build.
- **R3 (determinismo, ESPEC §12) — entorno no pineado.** *Mitigación:* `uv.lock` + `--locked` en CI + hash al lineage.
- **Drift `pyproject.toml`↔`EXTRA_TO_DISTRIBUTIONS`↔mensajes.** *Mitigación:* test de propiedad cruzado (§11).
- **Matriz de CI lenta/cara** (3 Python × 3 OS × extras ML). *Mitigación:* matriz completa solo en `main`/PR; subset en ramas; cache de uv; suite ML marcada y separable.
- **`uv` aún evoluciona rápido (pre-1.0 histórico).** *Mitigación:* `required-version` pineado; `hatchling` como backend es estable e independiente de uv (uv solo orquesta; el build no depende de uv).

---

### Citas

- **ESPECIFICACIONES.md** §3.3 (D-LIC Apache-2.0 sin copyleft; D-PKG `uv`+`hatchling`, `pyproject.toml`, `src/` layout), §4 (principios 1 reproducibilidad, 9 núcleo liviano con extras e import perezoso, 8 no reinventar, 10 calidad ejemplar como marketing, 11 verificación de datos externos), §6.3 (árbol de paquetes), §7 (stack con licencias: tabla fuente de los extras; `scikit-survival` GPL-3.0 vetado; `hypothesis` MPL-2.0 dev-only no redistribuido; `[project.optional-dependencies]` para extras y `[dependency-groups]` PEP 735 para test/lint/docs/dev), §9 (lineage bundle incl. `uv.lock`), §10 (CI histórica: ruff, mypy strict, tests, build y objetivo pre-commit; este B2 no afirma que exista hoy su archivo de configuración; SemVer, changelog), §11 F0 DoD (`pyproject.toml` uv+hatchling, CI), §12 (R3 determinismo → pin `uv.lock`, R5).
- **ROADMAP.md** F0 (entregables históricos: `src/` layout, `pyproject.toml` uv+hatchling con extras declarados y objetivo pre-commit; B2 no recertifica esa deuda), F1 (release público v0.1.0 en PyPI).
- **00-INDICE.md** SDD-25 (Packaging+CI, F0/T1, depende de —, Ingeniería), §Convenciones (fórmulas/parámetros se citan, no se reescriben).
- **SDD-01 (`core`)** §4 (jerarquía `core.exceptions`, base para `MissingDependencyError` propuesta), §9 (`LineageBundle.uv_lock_hash`, `library_versions`, `determinism_caveats`, `strict_determinism`), §10 (deps base del núcleo: pydantic/numpy/joblib/PyYAML; **conciliación ya hecha** —SDD-01 §10 distingue dep de distribución vs import de core y delega el mapa a SDD-25—: la distribución añade además pandas + pandera + pyarrow como deps base de `data`, C01), D-CORE-1 (`core` no depende de sklearn; multiherencia en dominios).
- **SDD-05 (convenciones+config)** §4 (D-CONV-4: `check_estimator` solo en estimadores de dominio que multiheredan `BaseEstimator`, requiere sklearn ≥1.6), §5.6 (extra `[sweep]` Hydra/OmegaConf, import perezoso), §10 (sklearn dep de los extras, no de `core`).
- **Verificado vía context7 (mecánica de packaging, doc oficial):**
  - **hatchling/Hatch** (`/pypa/hatch`): `[build-system] requires=["hatchling"]` + `build-backend="hatchling.build"`; `[tool.hatch.version] path=...`; `[tool.hatch.build.targets.wheel] packages=["src/foo"]`; `[tool.hatch.build.targets.sdist] include/exclude`; `[project.optional-dependencies]` para features opcionales; `dynamic=["version"]`.
  - **uv** (`/websites/astral_sh_uv`): `uv.lock` + `uv sync --locked` (reproducibilidad, falla si
    está desactualizado); `[dependency-groups]` (PEP 735) = dev-only;
    `[project.optional-dependencies]` = extras activados selectivamente con `--extra`; `uv build`,
    smoke aislado y `uv publish`. La CI vigente concreta el alcance con `--extra all`, dejando
    `[pdf]` en job separado.
- **pnpm oficial (doble verificación B2.0):**
  [`pnpm licenses`](https://pnpm.io/cli/licenses) confirma `licenses list --json --long` y el filtro
  `--prod`, sin afirmar que alguno pruebe redistribución;
  [`package.json`](https://pnpm.io/package_json) confirma el pin del package manager. Se contrastó
  además contra pnpm `11.15.0` local antes de fijar el candidato.
- **Vite oficial (procedencia B2.0):**
  [`Plugin API`](https://vite.dev/guide/api-plugin.html) documenta plugins compatibles con Rollup,
  el filtro `apply` y los hooks de build usados aquí (`transform`/`generateBundle`).
