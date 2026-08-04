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

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Final, Protocol, runtime_checkable

if TYPE_CHECKING:
    import numpy

    from nikodym.core.base import BaseNikodymEstimator
    from nikodym.core.study import Study

__all__ = [
    "METODO_CONTRATO_VARIABLES",
    "ArtifactKey",
    "ContextoDeResolucion",
    "Step",
    "StepAdapter",
]

ArtifactKey = tuple[str, str]  # (domain, key) — la misma clave namespaced del ArtifactStore (§6)

#: Nombre del método con que una config de sección declara **de dónde salen las variables** con que
#: se ajusta un modelo en esta corrida (enmienda REQUISITOS-DECLARADOS, D-REQ-3).
#:
#: 🔴 Existe para que el núcleo **no tenga que conocer** los campos. Podría leerse
#: ``config.ml.feature_source`` en dos líneas, y sería el acoplamiento que D-INV-1 rechazó: con la
#: sección opaca —que es el estado por DEFECTO— eso es una clave de ``dict`` y el núcleo pasaría a
#: depender del vocabulario de un dominio. Con el protocolo, el núcleo transporta un mapa cuyas
#: claves **no interpreta**, y la sección decide qué significan. Mismo criterio que
#: ``METODO_CONVENCION_SCORE`` en ``core/dataset_check.py``.
METODO_CONTRATO_VARIABLES: Final = "contrato_de_variables_declarado"


@dataclass(frozen=True, slots=True)
class ContextoDeResolucion:
    """Lo que un paso puede saber de la INVOCACIÓN al construirse, y nada más (D-REQ-2).

    Es lo que recibe ``from_config_with_context``. Nació como un ``frozenset[str]`` de nombres de
    paso, y esa forma alcanzaba para el único implementador que tuvo durante meses —``report``, que
    sólo pregunta *«¿corre este dominio?»*—; dejó de alcanzar en cuanto un paso necesitó saber algo
    que **otra sección decidió**, y no sólo que existe.

    ⚠️ **Es un DTO cerrado, y su tamaño ES la garantía**, igual que en
    :class:`~nikodym.core.dataset_check.ContextoConfig`: D-INV-1 rechazó darle el config raíz a cada
    dominio para no acoplarlos entre sí, y un objeto de dos campos conserva esa restricción por
    construcción — un paso **no puede** leer un campo ajeno aunque quiera, porque no está aquí—. Lo
    que se amplía es el contexto mínimo, no la puerta.
    """

    dominios_activos: frozenset[str]
    """Los pasos que ESTA invocación va a ejecutar (D-FX-1).

    «Activo» es *estar en la lista efectiva de pasos*, no *tener sección no nula*: con
    ``run.steps=['data','binning']`` el resto está apagado para esta corrida aunque su sección
    exista. Es literalmente el criterio de :meth:`Study._resolve_steps`, que es quien lo construye.
    """

    contrato_de_variables: Mapping[str, str] = field(default_factory=dict)
    """Lo que la sección de modelado declara sobre el origen de sus variables, o ``{}``.

    Segundo campo del DTO, y la razón de que el DTO exista (D-REQ-3). ``tuning`` y ``explain``
    calculan qué artefactos leerán a partir de decisiones que se toman en la sección ``ml``; sin
    esto sólo podían **replicar su default de fábrica a mano**, y entonces la comprobación previa
    afirmaba una cosa y el paso hacía otra.

    ⚠️ **El núcleo lo transporta y no lo interpreta**: las claves las escribe quien lo declara, vía
    :data:`METODO_CONTRATO_VARIABLES`. ``{}`` significa **«no se sabe»** —nadie activo lo declara, o
    su sección no se pudo coaccionar— y entonces el paso conserva el contrato que declararía por sí
    solo, que es el comportamiento histórico (D-REQ-4).
    """


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
    #
    # DOS ATRIBUTOS OPCIONALES que el motor consulta con `getattr` y que por eso NO entran al
    # Protocol (declararlos aquí obligaría a todo Step a tenerlos):
    #
    #   optional_requires: tuple[ArtifactKey, ...]
    #       Claves que el paso ADOPTA si existen y de las que no depende. No entran a la validación
    #       de prerequisitos (`_validate_pipeline`/`_check_prerequisites`): sólo evitan que la
    #       puerta pública `nikodym.run(..., artifacts=...)` declare INERTE una clave que el paso sí
    #       consume (D-ART-5).
    #
    #   from_config_with_context(cls, sub_cfg, *, contexto: ContextoDeResolucion) -> Step
    #       Fábrica alternativa a `from_config` (D-FX-2). `Study._resolve_step` la usa **si el
    #       componente la expone**; si no, usa `from_config` sin cambio alguno. Es la vía genérica
    #       —sin casos especiales por dominio en el núcleo— para un paso cuyo contrato depende de
    #       la INVOCACIÓN: qué otros dominios corren, y qué decidieron los que sí.
    #
    #       ⚠️ Hasta D-REQ-2 el kwarg era `active_domains: frozenset[str]`. Sigue estando —es
    #       `contexto.dominios_activos`, con el mismo criterio de D-FX-1—, pero viaja dentro del
    #       DTO para que ampliar el contexto no obligue a tocar a cada implementador. Un dominio de
    #       tercero con la firma vieja recibe un `ConfigError` que nombra la esperada.


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
