"""Tests de :func:`build_full_json_schema` (F7-UI, SDD-23): schema completo por composición.

``NikodymConfig.model_json_schema()`` emite las secciones de dominio OPACAS (campos ``Any`` en
runtime, núcleo liviano); ``build_full_json_schema`` las expande empotrando el ``model_json_schema``
de cada sub-config de dominio instalado, degradando por extra ausente sin romper. El core sigue
liviano: los dominios se importan solo al LLAMAR la función.
"""

from __future__ import annotations

import importlib
import types
from typing import Any

import pytest

from nikodym.core.config import NikodymConfig
from nikodym.core.config import schema as schema_mod

# Secciones del flujo F1 (deben expandirse con el extra `scoring` instalado — job del CI).
_F1_SECCIONES = (
    "data",
    "binning",
    "selection",
    "model",
    "scorecard",
    "calibration",
    "performance",
)


def test_build_full_json_schema_expande_secciones_f1() -> None:
    """Con ``[scoring]`` instalado, las secciones F1 traen ``properties`` reales (no opacas)."""
    full = schema_mod.build_full_json_schema()
    props = full["properties"]
    for seccion in _F1_SECCIONES:
        rama = schema_mod.rama_objeto(props[seccion])
        assert rama is not None, f"{seccion} quedó opaca"
        assert rama["properties"], f"{seccion} sin campos"
    # El schema opaco trae 2 ``$defs`` (ReproConfig/RunConfig); el completo empota los sub-configs.
    assert len(full["$defs"]) > 2


def test_build_full_json_schema_declara_las_secciones_apagables() -> None:
    """Una sección de dominio expandida sigue declarando que se puede apagar.

    El campo es ``Any`` con ``default=None``, y ese ``"default": null`` es el único portador de la
    nulabilidad en el schema raíz: no hay ``anyOf`` que copiar. Empotrar sustituyendo el nodo lo
    borraba, y el compuesto acababa afirmando ``type: "object"`` + ``required`` — lo contrario de
    la verdad, porque el mismo payload trae la sección en ``null`` en sus ``defaults``. Sin esto no
    hay forma de apagar una sección desde el formulario.
    """
    full = schema_mod.build_full_json_schema()
    props = full["properties"]
    for seccion in _F1_SECCIONES:
        nodo = props[seccion]
        assert nodo["default"] is None, f"{seccion} perdió su default nulo"
        assert {"type": "null"} in nodo["anyOf"], f"{seccion} no declara la rama nula"
        # …y la nulabilidad no se come los campos: la rama-objeto sigue completa.
        assert schema_mod.rama_objeto(nodo)["properties"], seccion


def test_empotrar_seccion_conserva_el_default_nulo() -> None:
    """La unidad del fix, con la sección raíz TAL COMO la emite Pydantic para un campo ``Any``.

    El test hermano de abajo usa ``props={"x": {}}``, que es justo el caso sin ``default`` que
    perder: por eso no cazaba nada. Aquí la sección raíz sí lo declara.
    """
    props: dict[str, Any] = {"x": {"default": None, "title": "X", "description": "una sección"}}
    defs: dict[str, Any] = {}
    schema_mod._empotrar_seccion(
        props, defs, "x", {"type": "object", "properties": {"a": {"type": "string"}}}
    )
    assert props["x"]["default"] is None
    assert props["x"]["anyOf"] == [
        {"type": "object", "properties": {"a": {"type": "string"}}},
        {"type": "null"},
    ]
    # Los labels de la sección van FUERA de la unión, igual que Pydantic con un ``X | None``.
    assert props["x"]["title"] == "X"
    assert props["x"]["description"] == "una sección"


def test_rama_objeto_distingue_expandido_de_opaco() -> None:
    """El helper que todo consumidor usa para no preguntarle ``properties`` a la raíz."""
    objeto = {"type": "object", "properties": {"a": {"type": "string"}}}
    # sección nullable expandida → la rama con campos
    assert schema_mod.rama_objeto({"anyOf": [objeto, {"type": "null"}], "default": None}) == objeto
    # objeto plano (sección no nullable) → él mismo
    assert schema_mod.rama_objeto(objeto) == objeto
    # opaca (lo que Pydantic emite para un campo ``Any``) → None
    assert schema_mod.rama_objeto({"default": None, "title": "X"}) is None
    assert schema_mod.rama_objeto(None) is None


def test_build_full_json_schema_conserva_labels_y_no_muta_el_cacheado() -> None:
    """Conserva ``title`` de la sección raíz (etiqueta de la UI) y NO muta el schema cacheado."""
    opaco = NikodymConfig.model_json_schema()
    full = schema_mod.build_full_json_schema()
    assert full["properties"]["binning"]["title"] == opaco["properties"]["binning"]["title"]
    # El schema cacheado de ``NikodymConfig`` sigue opaco (no se corrompió al componer una copia).
    assert "properties" not in NikodymConfig.model_json_schema()["properties"]["binning"]


def test_build_full_json_schema_shape_contrato() -> None:
    """Mismo ``shape`` JSON-Schema que ``model_json_schema`` (Draft 2020-12)."""
    full = schema_mod.build_full_json_schema()
    assert {"$defs", "properties", "title", "type"} <= set(full)
    assert full["type"] == "object"


def test_build_full_json_schema_degrada_por_extra_ausente(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Un dominio cuyo import falla (extra ausente) queda opaco, sin excepción; los demás no."""
    real_import = importlib.import_module

    def fake_import(name: str, package: str | None = None) -> types.ModuleType:
        if name == "nikodym.binning.config":
            raise ImportError("simulado: extra de binning ausente")
        return real_import(name, package)

    monkeypatch.setattr(schema_mod.importlib, "import_module", fake_import)
    full = schema_mod.build_full_json_schema()
    props = full["properties"]
    # binning quedó opaca (su import falló) pero la sección sigue presente, sin romper.
    assert schema_mod.rama_objeto(props["binning"]) is None
    assert props["binning"]["title"]
    # Otro dominio F1 no simulado como faltante SÍ expandió → aislamiento por-dominio.
    assert schema_mod.rama_objeto(props["model"]) is not None


def test_empotrar_seccion_sin_labels_no_inventa_title() -> None:
    """Rama defensiva: una sección raíz sin ``title``/``description`` se empota sin inventarlos."""
    props: dict[str, Any] = {"x": {}}  # sección raíz sin title ni description
    defs: dict[str, Any] = {}
    schema_mod._empotrar_seccion(
        props, defs, "x", {"type": "object", "properties": {"a": {"type": "string"}}}
    )
    assert props["x"]["properties"] == {"a": {"type": "string"}}
    assert "title" not in props["x"]
    assert "description" not in props["x"]
