"""Puerta guiada del scorecard (SDD-31, enmienda FLUJO-GUIADO-SCORECARD; D-FLU-1…D-FLU-12).

:class:`~nikodym.guided.scorecard.Scorecard` se construye con lo que sólo la institución sabe
—los datos, qué es «malo», el identificador, el eje temporal con su frontera fuera de tiempo o una
partición aleatoria explícita—, infiere y **declara** el resto en el trail, corre el pipeline F1
completo con :func:`nikodym.run` y cuenta cada etapa con un resumen en español. Es un **cliente**
de ``nikodym.run``/``Study``: construye el ``NikodymConfig``, lo ejecuta y lee sus artefactos. El
config sigue siendo la verdad y el ``config_hash``, la identidad de la corrida (D-SIM-1).

**Estable (SemVer 1.x).** Salió en la 1.17.0 como adelanto declarado (D-SIM-1) y sus tres
puertas —código, config completo y pantalla— cerraron con la capa B de la enmienda (S18,
2026-09-21): la firma de :class:`Scorecard`, el contenido de los resúmenes y sus decisiones sólo
crecen de forma aditiva.
"""

from nikodym.guided.scorecard import Scorecard, ScorecardInputError, ScorecardRunError
from nikodym.guided.summaries import STAGE_LABELS, FinalSummary, StageSummary

__all__ = [
    "STAGE_LABELS",
    "FinalSummary",
    "Scorecard",
    "ScorecardInputError",
    "ScorecardRunError",
    "StageSummary",
]
