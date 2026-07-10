# Referencia de la API

Superficie pública mínima de Nikodym RiskLib. Generada automáticamente desde los *docstrings* del
código (mkdocstrings). Las APIs marcadas como experimentales pueden cambiar antes de la 1.0.

## `run`

Punto de entrada único de ejecución: recibe un `NikodymConfig` y devuelve un `Study`.

::: nikodym.run

## `Study`

Contenedor de una corrida: `RunContext` (estado + lineage), `ArtifactStore` *namespaced* y
persistencia atómica a directorio.

::: nikodym.core.study.Study

## `NikodymConfig`

Config declarativo raíz — *el config es el experimento*. Agrupa las secciones de datos, binning,
selección, modelo, scorecard, calibración y demás dominios.

::: nikodym.core.config.NikodymConfig
