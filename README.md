# Nikodym RiskLib

Librería Python **open-source (Apache-2.0)** de riesgo de crédito **integral**:
scoring/scorecards, ML, provisiones **CMF (Chile)** e **IFRS 9/ECL**, forward-looking y
stress testing. Paquete: `nikodym`.

> ⚠️ **Estado: en construcción (F0 — Fundación).** API inestable (SemVer 0.x honesto).
> Las superficies que crecerán (resultados/overlay/métricas/orquestación) están marcadas
> como experimentales hasta la 1.0.

## Principios

- **Reproducibilidad total**: `(datos + config + semilla) → resultado idéntico`. Lineage
  bundle (git SHA + hash de datos + config + semilla + `uv.lock`) en cada corrida.
- **Gobernanza por construcción** (SR 11-7): model card y audit-trail automáticos.
- **Config declarativo** (Pydantic v2): *el config ES el experimento*.
- **Núcleo liviano**: `import nikodym` no arrastra el stack ML; los backends pesados van
  tras *extras* opcionales con import perezoso.
- **CMF ≠ IFRS 9**: dos motores separados; la provisión es el **máximo** (piso prudencial).

## Instalación

```bash
pip install nikodym                 # núcleo base (config, Study, lineage)
pip install 'nikodym[scoring]'      # MVP scorecard (optbinning + statsmodels + sklearn>=1.6)
pip install 'nikodym[all]'          # todo lo redistribuible (sin copyleft)
```

## Desarrollo

El proyecto usa [uv](https://docs.astral.sh/uv/) + hatchling, con layout `src/`.

```bash
uv sync                              # entorno completo (grupo dev: test/lint/docs)
uv run ruff check . && uv run ruff format --check .
uv run mypy                          # type-check estricto de todo el paquete
uv run pytest                        # suite de tests
```

## Licencia

[Apache-2.0](LICENSE). Sin dependencias copyleft (GPL/LGPL/AGPL) en el wheel.
