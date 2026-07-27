"""Gate: todo ``ui_widget`` que emite el motor tiene un widget en el front.

Los configs Pydantic declaran ``ui_widget`` en su ``json_schema_extra``; el front lo traduce con
``UI_WIDGET_ALIASES`` (``web/src/lib/form-engine.ts``). Los dos vocabularios se escribieron por
separado y **se separaron en silencio**: de los 20 literales que emitía ``src/``, el mapa conocía
cuatro. El resto caía a la resolución por tipo, que acertaba por accidente en unos (``text_input``
resuelve a texto porque el tipo es ``string``) y fallaba callada en otros:

- ``hidden`` se **renderizaba**: `schema_version` quedaba como un input de texto libre que el
  usuario podía romper, y los dos flags ``[DEPRECADO]`` como switches que podía encender.
- ``kv_text``/``kv_number``/``key_value`` son ``dict[str, X]``, o sea ``type: "object"`` **sin**
  ``properties``: resolvían a ``group`` y pintaban un fieldset vacío.

Ninguno de los dos lo cazaba un test —el front prueba la *función* de traducción, no la cobertura
del vocabulario—, y ambos son invisibles hasta que alguien abre la sección. De ahí este gate, que
ataca la causa (los dos vocabularios pueden separarse) y no el síntoma.

Se verifica desde pytest por el mismo motivo que ``test_public_copy.py``: el ``tsconfig`` de la app
expone sólo ``vite/client`` y no puede leer los configs Python, así que éste es el único lado con
acceso a los dos.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from nikodym.core.config.schema import build_full_json_schema

_FORM_ENGINE = Path(__file__).resolve().parents[2] / "web" / "src" / "lib" / "form-engine.ts"

#: Claves del objeto `UI_WIDGET_ALIASES`. Se acota el barrido al bloque de esa constante para no
#: recoger identificadores del resto del módulo.
_BLOQUE_ALIASES = re.compile(
    r"const UI_WIDGET_ALIASES: Record<string, WidgetKind> = \{(.*?)\n\}", re.DOTALL
)


def _alias_del_front() -> set[str]:
    fuente = _FORM_ENGINE.read_text(encoding="utf-8")
    bloque = _BLOQUE_ALIASES.search(fuente)
    assert bloque, "no se encontró UI_WIDGET_ALIASES en form-engine.ts (¿lo renombraron?)"
    return set(re.findall(r"^\s*([a-z_]+):", bloque.group(1), re.MULTILINE))


def _widgets_del_motor() -> dict[str, list[str]]:
    """Cada literal ``ui_widget`` del schema compuesto → los campos que lo declaran."""
    full = build_full_json_schema()
    nodos: list[dict[str, Any]] = [full["properties"], *full.get("$defs", {}).values()]
    vocabulario: dict[str, list[str]] = {}
    for nodo in nodos:
        for seccion in nodo.values():
            if not isinstance(seccion, dict):
                continue
            # Una sección expandida es apagable: sus campos viven bajo la rama-objeto del `anyOf`.
            for variante in (seccion, *seccion.get("anyOf", ())):
                if not isinstance(variante, dict):
                    continue
                for campo, spec in (variante.get("properties") or {}).items():
                    widget = spec.get("ui_widget") if isinstance(spec, dict) else None
                    if isinstance(widget, str):
                        vocabulario.setdefault(widget, []).append(campo)
    return vocabulario


def test_hay_vocabulario_que_revisar() -> None:
    """Sin esto, un walk roto dejaría el gate en verde barriendo cero campos."""
    assert len(_widgets_del_motor()) >= 10


def test_el_front_conoce_todo_ui_widget_que_el_motor_emite() -> None:
    """Un literal que el front no traduce degrada el campo en silencio, sin error visible."""
    motor = _widgets_del_motor()
    huerfanos = {
        w: sorted(set(campos))[:3] for w, campos in motor.items() if w not in _alias_del_front()
    }
    assert not huerfanos, (
        "estos `ui_widget` del motor no están en UI_WIDGET_ALIASES de form-engine.ts, así que sus "
        f"campos resuelven por tipo y pueden degradar sin avisar: {huerfanos}"
    )


def test_el_widget_oculto_sigue_declarandose() -> None:
    """`hidden` es el único alias del que depende que la fontanería NO se pinte.

    Es un literal que el front debe conocer *para omitir*, no para traducir: si desapareciera del
    mapa, sus campos volverían a resolverse por tipo y a renderizarse, que es el estado que este
    bloque corrigió. El test de arriba no lo cubre —pasaría igual si el motor dejara de emitirlo—.
    """
    assert "hidden" in _alias_del_front()
    assert "hidden" in _widgets_del_motor()
