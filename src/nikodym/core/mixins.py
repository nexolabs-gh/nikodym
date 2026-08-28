"""Mixins transversales de los estimadores Nikodym (SDD-01 §4).

:class:`AuditableMixin` da a todo estimador un *sink* de auditoría (``_audit``, nunca ``None``) y
el método :meth:`AuditableMixin.log_decision` que emite un :class:`~nikodym.core.audit.AuditEvent`
``"decision"`` con la regla, el umbral gatillante y el valor observado (auditabilidad por
construcción, ESPEC §4 principio 2). :class:`SerializationMixin` serializa **un** estimador fiteado
con ``joblib`` (escritura atómica) y lo recarga con una puerta de confianza ``trust`` que rechaza el
vector *pickle* por defecto.
"""

from __future__ import annotations

import os
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Self

from nikodym import __version__
from nikodym.core.audit import AuditEvent, AuditSink, NullAuditSink
from nikodym.core.exceptions import ConfigError, UntrustedStudyError

__all__ = ["AuditableMixin", "SerializationMixin"]


class AuditableMixin:
    """Da a un estimador un *sink* de auditoría y el helper :meth:`log_decision`.

    ``_audit`` es un atributo de **clase** que arranca en ``NullAuditSink`` (no-op): nunca es
    ``None``, de modo que :meth:`log_decision` es siempre seguro aunque no se haya inyectado un
    *sink* real. El orquestador (``Study``/``StepAdapter``) lo sobreescribe por instancia con el
    *sink* compuesto antes de la corrida; tras ``clone()``/``check_estimator`` de scikit-learn la
    instancia cae de nuevo al ``NullAuditSink`` de clase sin romper. ``_audit`` no es un
    hiperparámetro: como no es parámetro de ``__init__``, ``get_params`` jamás lo expone.
    """

    _audit: AuditSink = NullAuditSink()

    def __deepcopy__(self, memo: dict[int, Any]) -> Any:
        """Copia el objeto **sin** su ``_audit``, que vuelve al ``NullAuditSink`` de clase.

        🔴 Cierra un defecto medido: el *sink* es infraestructura viva —``JsonlAuditSink`` sostiene
        un descriptor de archivo abierto—, no estado del estimador, y un ``deepcopy`` lo arrastraba.
        Con ``audit`` encendido, ``SurvivalResult.estimator`` es un ``AuditableMixin`` con el sink
        inyectado, así que el ``result.model_copy(deep=True)`` de ``survival/step.py`` reventaba con
        ``TypeError: cannot pickle 'TextIOWrapper' instances`` **antes** de publicar sus artefactos.
        Y como es un ``TypeError`` y no un ``NikodymError``, ``nikodym.run`` ni siquiera lo
        capturaba: la corrida moría entera en vez de devolver un ``Study`` con ``status="failed"``.

        No se veía porque ningún preset traía ``audit`` encendido; corre con él y el dominio
        ``survival`` es inalcanzable. Medido sobre ``5d6aa68``, sin nada de D-GOB en el árbol.

        Esto no inventa una regla: es la que el docstring de arriba ya declaraba para
        ``clone()``/``check_estimator`` de scikit-learn —«la instancia cae de nuevo al
        ``NullAuditSink`` de clase sin romper»—, que hasta ahora sólo valía por el camino de
        scikit-learn. El orquestador reinyecta el sink por instancia antes de cada corrida, así que
        una copia sin sink es exactamente lo que corresponde: un artefacto persistido no debe
        sostener un archivo abierto del proceso que lo creó.
        """
        copia = self.__class__.__new__(self.__class__)
        memo[id(self)] = copia
        for nombre, valor in self.__dict__.items():
            if nombre == "_audit":
                continue  # se deja caer al NullAuditSink de clase, que nunca es None
            object.__setattr__(copia, nombre, deepcopy(valor, memo))
        return copia

    def log_decision(
        self,
        *,
        regla: str,
        umbral: Any,
        valor: Any,
        accion: str,
        step: str | None = None,
    ) -> None:
        """Registra una decisión: construye y emite un :class:`AuditEvent` ``"decision"``.

        Sólo admite argumentos por palabra clave (1:1 con el ``DecisionRecord`` de SDD-03, en
        español por contrato de auditoría). ``step`` permite atribuir la decisión al paso que la
        tomó; queda en ``None`` para estimadores sin contexto de orquestación.
        """
        event = AuditEvent(
            kind="decision",
            step=step,
            payload={"regla": regla, "umbral": umbral, "valor": valor, "accion": accion},
            ts=datetime.now(UTC),
        )
        self._audit.emit(event)


class SerializationMixin:
    """Serializa **un** estimador fiteado con ``joblib`` (escritura atómica) y lo recarga.

    Es un contrato distinto del ``Study.save`` (que persiste un directorio de corrida): aquí se
    serializa un estimador *standalone* junto con metadatos (versión del paquete). Comparte con
    ``Study.load`` el *caveat* de ``trust``: ``joblib.load`` deserializa *pickle*, que ejecuta
    código arbitrario, así que :meth:`load` rechaza el origen no verificado por defecto.
    """

    def save(self, path: str | Path) -> None:
        """Serializa el estimador a ``path`` con ``joblib`` (escritura atómica *temp+rename*)."""
        import joblib

        destino = Path(path)
        temporal = destino.with_suffix(destino.suffix + ".tmp")
        joblib.dump({"estimator": self, "nikodym_version": __version__}, temporal)
        os.replace(temporal, destino)

    @classmethod
    def load(cls, path: str | Path, *, trust: bool = False) -> Self:
        """Recarga un estimador serializado; ``trust=False`` rechaza el origen no verificado.

        ``joblib.load`` ejecuta código arbitrario vía *pickle*: con ``trust=False`` se levanta
        :class:`~nikodym.core.exceptions.UntrustedStudyError` **antes** de deserializar. Con
        ``trust=True`` se carga y se verifica que el artefacto corresponde a ``cls``.
        """
        if not trust:
            raise UntrustedStudyError(
                f"Carga de '{path}' rechazada: deserializar joblib/pickle ejecuta código "
                "arbitrario. Pase trust=True sólo si el origen del artefacto es de confianza."
            )
        import joblib

        payload = joblib.load(path)
        estimator = payload["estimator"]
        if not isinstance(estimator, cls):
            raise ConfigError(
                f"El artefacto en '{path}' no es un {cls.__name__}: "
                f"contiene un {type(estimator).__name__}."
            )
        return estimator
