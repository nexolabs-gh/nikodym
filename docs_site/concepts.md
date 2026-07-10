# Conceptos

Modelo mental mínimo para leer el resto de la documentación.

## El config declarativo *es* el experimento

Toda corrida se describe con un único objeto `NikodymConfig` (Pydantic v2): esquema de datos,
partición, binning, selección de variables, modelo, scorecard, calibración, desempeño y
estabilidad. No hay estado oculto ni parámetros dispersos por el código: **el config es la
verdad**, y la misma estructura que se edita a mano es la que se serializa a YAML/JSON y la que
consume la UI. De ahí la propiedad central: `(datos + config + semilla) → resultado idéntico`.

## `run` → `Study`

`nikodym.run(config)` es la superficie pública única de ejecución. Ensambla el *audit sink* y el
inventario de modelos, corre el pipeline y devuelve un `Study`: el contenedor de la corrida con el
`RunContext` (estado + lineage) y el `ArtifactStore` *namespaced* por dominio. Los resultados no
viven en un `dict` plano sino en `study.artifacts.get(<dominio>, <clave>)` — p. ej.
`("scorecard", "scorecard")` o `("performance", "discriminant_metrics")`.

## El pipeline F1 (scorecard de comportamiento)

El MVP (Fase 1) es un scorecard de comportamiento. La corrida encadena estos pasos, cada uno
gobernado por su sección del config:

1. **binning** — discretiza las variables en *bins* con *Weight of Evidence* (WoE) y monotonía
   controlada (motor OptBinning).
2. **selección** — filtra variables por IV, correlación y VIF antes de modelar.
3. **modelo** — regresión logística con *stepwise* e inferencia (statsmodels).
4. **scorecard** — traduce los coeficientes a puntajes enteros (escala PDO / *target odds*).
5. **calibración** — ajusta la PD a un ancla de negocio (*through-the-cycle*).
6. **desempeño / estabilidad** — métricas de discriminación (AUC/KS/Gini) y PSI/CSI por partición.

Fases posteriores añaden ML (GBDT), survival, forward-looking, provisiones **CMF** e **IFRS 9/ECL**
y stress testing, cada una como secciones adicionales del mismo config.

## Reproducibilidad y gobernanza

Cada corrida emite un *lineage bundle* (git SHA + hash lógico de datos + `config_hash` + semilla +
`uv.lock`) y un *audit-trail*, y produce una *model card* (SR 11-7). Reejecutar el mismo config con
la misma semilla sobre los mismos datos reproduce el resultado bit a bit.
