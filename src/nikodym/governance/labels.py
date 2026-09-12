"""Las palabras con que el informe y la pantalla nombran los `Literal` de la gobernanza.

Los slugs (``scoring``/``cmf``/``ifrs9``, ``F0``…``originacion``, ``desarrollo``…``retirado``) son
el dato y siguen viajando en el config y en la ficha; las palabras son el copy (D-SC-15). Viven
aquí, junto al config que los declara, para que ninguna superficie los traduzca por su cuenta.
"""

from __future__ import annotations

from typing import Final

#: ``GovernanceConfig.motor``: qué motor documenta la ficha (la descripción del campo los nombra).
MOTOR_LABELS: Final[dict[str, str]] = {
    "scoring": "scoring",
    "cmf": "provisiones CMF",
    "ifrs9": "provisiones IFRS 9",
}

#: ``GovernanceConfig.fase``: el nombre público de cada fase es su identificador (F0…F7 se leen
#: así en el roadmap y en el formulario); sólo la originación lleva tilde.
FASE_LABELS: Final[dict[str, str]] = {
    "F0": "F0",
    "F1": "F1",
    "F2": "F2",
    "F3": "F3",
    "F4": "F4",
    "F5": "F5",
    "F6": "F6",
    "F7": "F7",
    "originacion": "originación",
}

#: ``GovernanceConfig.estado_validacion``: en qué punto va la revisión independiente.
ESTADO_VALIDACION_LABELS: Final[dict[str, str]] = {
    "desarrollo": "en desarrollo",
    "en_validacion": "en validación independiente",
    "validado": "validado",
    "retirado": "retirado",
}


def governance_label(mapping: dict[str, str], slug: str | None) -> str | None:
    """La palabra de un slug, o ``None`` si no se declaró.

    Un slug desconocido se devuelve tal cual —nunca se inventa una palabra— para que un gate lo
    acuse.
    """
    if slug is None:
        return None
    return mapping.get(slug, slug)
