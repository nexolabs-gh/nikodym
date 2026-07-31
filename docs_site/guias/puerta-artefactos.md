# Reanudar una corrida con artefactos ya calculados

`nikodym.run(..., artifacts=...)` permite apagar un paso productor y continuar desde los
resultados que ese paso habría publicado. La superficie gemela
`nikodym.check_pipeline(..., artifacts=...)` comprueba antes de correr si las mismas claves bastan.

La clave siempre es una pareja `(dominio, nombre)`. El contrato de cada paso vive en sus atributos
`requires` y `provides`, visibles en la [referencia de la API](../api.md):

- inyecta las claves que el primer paso activo declara en `requires`;
- apaga en el config toda sección activa cuyo `provides` contenga una clave inyectada;
- entrega el objeto del tipo que espera el consumidor; la puerta no duplica esa validación;
- incluye `("data", "data_hash")` cuando dispongas del hash lógico del dataset.

`DataStep` tiene además la entrada opcional `("data", "input_frame")`: la consume cuando
`data.load.source` es `None`. Es el camino para traer un `pandas.DataFrame` en memoria sin apagar
`data`; no se declara inerte aunque, por ser opcional, no forme parte de `DataStep.requires`.

Una colisión con un productor activo o un dominio inexistente vuelve el pipeline inejecutable. Una
clave válida que ningún paso consume no bloquea, pero aparece en `PipelineCheck.inert_artifacts` y
en el audit trail como advertencia.

## Ejemplo mínimo ejecutable

Este ejemplo ejecuta un pipeline vacío —todos los productores están apagados— y adopta un
`data_hash` calculado fuera de la corrida. El test del sitio ejecuta literalmente este bloque.

<!-- artifact-gate-example:start -->
```python
import nikodym
from nikodym.core.config import NikodymConfig

config = NikodymConfig()
external = {("data", "data_hash"): "a" * 64}

check = nikodym.check_pipeline(config, artifacts=external)
assert check.executable
assert check.inert_artifacts == ()  # el cierre del lineage consume data_hash

study = nikodym.run(config, artifacts=external)
assert study.run_context.status == "done"

lineage = study.lineage_bundle()
assert lineage.data_hash == "a" * 64
assert lineage.injected_artifacts == ("data.data_hash",)
assert any("no reconstruibles" in item for item in lineage.determinism_caveats)
```
<!-- artifact-gate-example:end -->

## Patrón F1: ejecutar `data` una vez y continuar desde `binning`

En F1, `BinningStep.requires` consume cuatro claves del dominio `data`. Puedes obtenerlas de una
corrida previa, apagar `data` y comprobar/correr el resto:

```python
data_artifacts = {
    ("data", key): first_study.artifacts.get("data", key)
    for key in ("frame", "labels", "splits", "special", "data_hash")
}
partial_config = first_study.config.model_copy(update={"data": None})

check = nikodym.check_pipeline(partial_config, artifacts=data_artifacts)
assert check.executable and check.steps[0] == "binning"

resumed = nikodym.run(partial_config, artifacts=data_artifacts)
assert resumed.run_context.status == "done"
```

El `config_hash` sigue identificando sólo el config computacional. El lineage enumera las claves
externas y declara el caveat porque Nikodym no puede reconstruir su contenido desde
`config + datos`. Si omites `("data", "data_hash")` al apagar `data`, el lineage conserva
`data_hash=None` y declara esa ausencia explícitamente. `Study.save()`/`Study.load(trust=True)`
preservan tanto los artefactos como esta procedencia.

!!! warning "La puerta HTTP/UI queda fuera"
    Esta versión sólo acepta objetos Python por la API de código. La UI y sus endpoints no reciben
    artefactos externos: serializarlos por red exige otro contrato de formatos, tamaño y confianza.
