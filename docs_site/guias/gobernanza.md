# Gobernanza y ficha del modelo

La gobernanza en Nikodym tiene tres capas, y conviene saber cuál viene sola y cuál se enciende:

| Capa | Cuándo existe | Dónde queda |
|---|---|---|
| **Lineage** | En toda corrida, sin configurar nada | `study.lineage_bundle()` y la tarjeta de procedencia de Resultados |
| **Audit-trail** | Con la sección `audit` encendida — los cuatro ejemplos de fábrica la traen así | `audit_trail.jsonl` en el directorio de la corrida; la interfaz lo archiva junto a cada corrida |
| **Ficha del modelo** (*model card*) | Con la sección `governance` encendida **y un propósito declarado** | `model_card.json` y `model_card.md` en el directorio de la corrida, y la sección «Ficha del modelo» de Resultados |

La tercera capa es la única que pide algo tuyo. El propósito de un modelo —para qué se va a usar y
sobre qué cartera decide— lo fija tu institución, y el motor no lo inventa: por eso la sección llega
**apagada** en todos los trabajos y ejemplos, y sin propósito la ficha no se emite. Encenderla no
cambia ningún cálculo ni la identidad de la corrida (`config_hash`): documenta el modelo, no lo
modifica.

## Encenderla desde la interfaz

La sección **Gobernanza** está en todos los trabajos del catálogo, siempre como última sección del
grupo «Configuración» del panel lateral.

1. Entra a **Gobernanza**. Arriba de la sección está su interruptor, con el estado
   «Sección desactivada» y la nota «El motor no la corre.». Actívalo: pasa a «Sección activa».
2. Con la sección encendida, el bloque «Esto lo decides tú» pregunta por el **propósito del
   modelo**. Es un campo de texto libre («Propósito del modelo»): escribe para qué se va a usar el
   modelo y sobre qué cartera decide. Mientras la sección esté apagada, esa pregunta no cuenta como
   pendiente y la tarjeta lo dice: «Se pregunta cuando actives la sección con su interruptor.».
   Con la sección encendida y el propósito en blanco, la corrida no arranca y la tarjeta dice qué
   falta.
3. En el grupo «Ficha del modelo» puedes añadir **«Supuestos declarados»** y **«Limitaciones
   declaradas»**. Son listas y se escriben en formato JSON, una frase por elemento —el campo avisa
   «Este valor se escribe en formato JSON.» y marca el error si la lista no cierra—:

    ```json
    ["Cartera de consumo sin reestructurados", "Ventana de desarrollo 2022Q1–2024Q1"]
    ```

    Se copian tal cual a la ficha. **«Periodicidad de revisión (meses)»** fija cada cuántos meses
    toca revisar el modelo (12 por defecto, entre 1 y 60); con ella la ficha calcula la fecha de la
    próxima revisión, contada desde su emisión.
4. Los grupos «Inventario» (nombre lógico, cartera, motor, fase, estado de validación, responsable
   y si se publica a un inventario MLflow, que pide el extra `tracking`) y «Ajustes manuales» son
   opcionales; cada campo explica en su ayuda para qué sirve.
5. Ejecuta la corrida como siempre.

## Qué muestra Resultados

Cuando la corrida lleva gobernanza, la pestaña Resultados pinta la sección **«Ficha del modelo»**
inmediatamente después de «Artefactos de la corrida»:

- **Propósito**, tal como lo escribiste.
- **Supuestos** y **Limitaciones** declarados. Entre las limitaciones aparecen también las
  salvedades que el motor añade por su cuenta —por ejemplo, si la corrida no es reproducible sólo
  desde config y datos—; la ficha no oculta sus propias lagunas.
- **«Emitida»** y **«Próxima revisión»**: la fecha en que se construyó la ficha y la fecha de
  revisión que resulta de sumarle la periodicidad.
- **«Decisiones registradas»**: cuántas decisiones dejó el motor en el audit-trail, con
  «Ver el detalle de las decisiones» para desplegar la tabla —cuándo, regla, acción, umbral y
  valor, una fila por evento—.
- **«Métricas por dominio»**: las métricas planas que cada dominio publica, agrupadas con el rótulo
  de su sección del formulario y, debajo, su evidencia estructurada en filas etiqueta → valor.

Si una decisión o la evidencia de un dominio lleva un **aviso declarado**, la fila se marca como
tal: es una salvedad que el motor dejó escrita en vez de callar —un dato que le corresponde a tu
institución, o una brecha declarada del propio motor—. El código se conserva tal cual para que
puedas auditarlo; lo que significa cada uno está en [Avisos declarados](../avisos-declarados.md).

Sin gobernanza no cambia nada: no hay bloque vacío ni ficha fabricada. Con gobernanza, el informe
HTML/PDF/Word/Quarto gana el capítulo **«Ficha del modelo»**, entre la introducción y el contexto:
lo que declaraste —propósito, supuestos, limitaciones, identidad de inventario y periodicidad de
revisión— tal cual lo escribiste, con sus rótulos. Las métricas, las decisiones registradas y las
fechas de emisión y de la siguiente revisión no van en el capítulo: quedan en la ficha, que el
motor emite al cierre de la corrida cuando le das `run_dir` o publicas al inventario, y que
Resultados muestra completa. Una sola ficha por corrida: el informe remite a ella, no la duplica.

## Por código

Por código son los mismos tres ingredientes: la sección `governance` con su propósito, `run_dir`
para que la evidencia quede en disco y el preset o config que ya usas. Con el preset estándar F1:

<!-- governance-example:start -->
```python
import json
from pathlib import Path
from tempfile import mkdtemp

import nikodym
from nikodym.core.config import NikodymConfig
from nikodym.ui.datasets import materialize
from nikodym.ui.presets import standard_preset

workdir = Path(mkdtemp(prefix="nikodym-gobernanza-"))
preset = standard_preset()
data_path = materialize(preset["dataset_id"], workdir=workdir)

cfg_dict = preset["config"]
cfg_dict["data"]["load"]["source"] = str(data_path)
# La sección llega apagada (`None`); declararla es lo que emite la ficha. El propósito es tuyo.
cfg_dict["governance"] = {
    "purpose": "Scorecard de comportamiento para admisión de consumo en la cartera minorista.",
    "assumptions": ["Cartera de consumo sin reestructurados"],
    "limitations": ["No aplica a clientes con menos de seis meses de historia"],
    "review_period_months": 12,
}
config = NikodymConfig.model_validate(cfg_dict)

run_dir = workdir / "corrida"
study = nikodym.run(config, run_dir=run_dir)
assert study.run_context.status == "done"

# La ficha queda en disco, en JSON canónico y en Markdown, junto al audit-trail.
card = json.loads((run_dir / "model_card.json").read_text(encoding="utf-8"))
print(card["purpose"])
print(card["review_date"], "->", card["next_review_date"])
print(len(card["decisions"]), "decisiones registradas;", len(card["metrics"]), "métricas")
```
<!-- governance-example:end -->

Los campos de `GovernanceConfig` y la estructura de `ModelCard` están en la
[Referencia de la API](../api.md#gobernanza). La sección es experimental —fuera de la garantía
SemVer 1.x—, así que sus campos pueden crecer dentro de la serie 1.x.

## Ver también

- [Desempeño, estabilidad y gobernanza](desempeno-estabilidad.md) — qué contiene la ficha y por qué
  le habla a un validador.
- [Conceptos](../concepts.md) — el modelo mental `run` → `Study` y dónde queda la evidencia.
- [Avisos declarados](../avisos-declarados.md) — qué significa cada código que la ficha conserva.
