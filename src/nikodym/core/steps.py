"""Contrato de orquestación: el ``Step`` que expresa el DAG en la firma (SDD-01 §4/§7; CT-1).

Un :class:`Step` declara sus dependencias explícitas sobre el ``ArtifactStore``: ``requires`` (las
claves ``(domain, key)`` que **lee**) y ``provides`` (las que **escribe**), tipadas como
``tuple[ArtifactKey, ...]``. La firma expresa el DAG **desde v1**; el motor v1 (``Study.run``)
ejecuta en orden de declaración del config y sólo **valida prerequisitos** (un ``requires`` ausente
del *store* → error antes de ejecutar). El scheduler topológico que reordena según el grafo
(fan-in/fan-out real de forward/stress) se difiere a F5 **sin tocar esta firma**.

Los estimadores de dominio (``fit``/``transform``/``predict``/``compute``) no implementan
``execute``/``name``: el orquestador los envuelve en un :class:`StepAdapter`, de modo que ``core``
no conoce la API de cada dominio (D-CORE-1).

**Experimental (fuera de la garantía SemVer 1.x):** la firma
``Step.requires``/``provides``/``ArtifactKey`` es estable, pero el motor de orquestación
(scheduler topológico diferido) crece en las versiones 1.x.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    import numpy

    from nikodym.core.base import BaseNikodymEstimator
    from nikodym.core.study import Study

__all__ = ["ArtifactKey", "Step", "StepAdapter"]

ArtifactKey = tuple[str, str]  # (domain, key) — la misma clave namespaced del ArtifactStore (§6)


@runtime_checkable
class Step(Protocol):
    """Lo que un dominio implementa para ser orquestable (SDD-01 §7).

    ``@runtime_checkable`` permite ``isinstance(obj, Step)`` en el despacho del motor; sólo verifica
    la *presencia* de ``name``/``requires``/``provides``/``execute``, no sus tipos ni firmas.
    """

    name: str  # == nombre de su sección de config (== domain)
    requires: tuple[ArtifactKey, ...]  # claves que LEE del ArtifactStore (() = sin upstream)
    provides: tuple[ArtifactKey, ...]  # claves que ESCRIBE (CT-1)

    def execute(self, study: Study, rng: numpy.random.Generator) -> Any:
        """Ejecuta el paso: lee de ``study.artifacts``, calcula y escribe su salida."""
        ...

    # CT-1 (Contratos transversales, Hito 0): requires/provides expresan el DAG en la firma desde
    # v1. El motor v1 ejecuta en orden de declaración (§7) y sólo VALIDA prerequisitos; el scheduler
    # topológico (orden derivado del grafo, fan-in/fan-out de forward/stress F5) se difiere a F5 sin
    # tocar esta firma.


class StepAdapter:
    """Adapta un ``BaseNikodymEstimator`` al Protocol :class:`Step` (SDD-01 §4/§7).

    El orquestador (agnóstico al dominio) envuelve cualquier estimador en un ``StepAdapter`` para
    orquestarlo sin que ``core`` importe dominios. ``name == domain``; ``requires``/``provides`` son
    las claves de I/O del dominio (§6), que en F0 se pasan al constructor (la derivación automática
    la fijará cada SDD de dominio en 06+).

    El despacho concreto de :meth:`execute` (mapeo familia → método ``transform``/``predict``/
    ``predict_proba``/``compute`` y las claves de I/O por dominio) se materializa con el primer
    estimador de dominio y ``Study.run`` (T2+); en F0 se **difiere de forma ruidosa**.
    """

    def __init__(
        self,
        domain: str,
        estimator: BaseNikodymEstimator,
        *,
        requires: tuple[ArtifactKey, ...] = (),
        provides: tuple[ArtifactKey, ...] = (),
    ) -> None:
        self.name = domain  # == domain (SDD-01 §4): única fuente del dominio del paso
        self.estimator = estimator
        self.requires = requires
        self.provides = provides

    def execute(self, study: Study, rng: numpy.random.Generator) -> Any:
        """Ejecuta el estimador envuelto (diferido a T2+).

        Los 4 pasos (leer ``requires`` de ``study.artifacts``; ``fit`` + método de familia; escribir
        ``provides``; devolver el resultado) requieren el mapeo familia → método y las claves de I/O
        que fija cada SDD de dominio (06+). En F0 no hay estimadores de dominio, así que se difiere
        de forma ruidosa (no es un no-op silencioso).
        """
        raise NotImplementedError(
            "StepAdapter.execute se materializa con el primer estimador de dominio (T2+): "
            "el mapeo familia → método y las claves de I/O los fija el SDD del dominio."
        )
