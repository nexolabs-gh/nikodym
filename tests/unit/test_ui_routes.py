"""Tests de la lógica pura de los endpoints y del contrato *domain-agnostic* (SDD-23 §4.2, §11).

La lógica de ``/schema``/``/validate``/``/datasets`` se prueba **sin FastAPI** (funciones puras);
el cableado HTTP se prueba en ``test_ui_server.py`` vía ``TestClient``. Aquí también viven los
tests AST de la frontera: ``nikodym.ui`` no usa ``eval``/``exec``, no importa módulos de dominio y
no reimplementa fórmulas de riesgo.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from nikodym.core.config import NikodymConfig, ReproConfig, config_hash
from nikodym.ui import datasets as datasets_module
from nikodym.ui import routes

# ─────────────────────────────── lógica pura de endpoints ───────────────────────────────


def test_schema_payload_shape() -> None:
    """``/schema`` entrega el JSON-Schema, los defaults y el orden de secciones declarado."""
    payload = routes.schema_payload()
    assert set(payload) == {"json_schema", "defaults", "section_order"}
    assert payload["section_order"] == list(NikodymConfig.model_fields)
    assert payload["section_order"][0] == "schema_version"
    assert {"repro", "data", "report"} <= set(payload["section_order"])
    assert "properties" in payload["json_schema"]
    assert payload["defaults"]["repro"]["seed"] == 42  # defaults resueltos del config vacío


def test_validate_config_valido_devuelve_hash() -> None:
    """Un config válido reconstruye el modelo y devuelve su ``config_hash``."""
    cfg = NikodymConfig(repro=ReproConfig(seed=7))
    resultado = routes.validate_config(cfg.model_dump(mode="json", by_alias=True))
    assert resultado == {"valid": True, "config_hash": config_hash(cfg), "errors": []}


def test_validate_config_invalido_estructura_errores() -> None:
    """Un rango violado da ``valid=False`` con errores estructurados (loc/msg/type)."""
    resultado = routes.validate_config({"repro": {"seed": -1}})
    assert resultado["valid"] is False
    assert resultado["config_hash"] is None
    assert resultado["errors"], "debe listar al menos un error"
    error = resultado["errors"][0]
    assert set(error) == {"loc", "msg", "type"}
    assert error["loc"] == ["repro", "seed"]


def test_validate_config_campo_desconocido() -> None:
    """``extra='forbid'``: un campo desconocido es inválido (no se descarta en silencio)."""
    resultado = routes.validate_config({"campo_que_no_existe": 1})
    assert resultado["valid"] is False
    assert any(err["type"] == "extra_forbidden" for err in resultado["errors"])


def test_datasets_payload_es_el_catalogo() -> None:
    """``/datasets`` delega en ``list_datasets`` sin transformar."""
    assert routes.datasets_payload() == datasets_module.list_datasets()


# ─────────────────────────────── contrato AST de la frontera ───────────────────────────────

_UI_DIR = Path(routes.__file__).resolve().parent
_DOMINIOS_PROHIBIDOS = frozenset(
    {
        "nikodym.binning",
        "nikodym.selection",
        "nikodym.model",
        "nikodym.calibration",
        "nikodym.scorecard",
        "nikodym.performance",
        "nikodym.stability",
        "nikodym.validation",
        "nikodym.provisioning",
        "nikodym.survival",
        "nikodym.markov",
        "nikodym.forward",
        "nikodym.stress",
        "nikodym.explain",
        "nikodym.tuning",
        "nikodym.ml",
        "nikodym.eda",
        "nikodym.data",
    }
)


def _modulos_ui() -> list[Path]:
    """Devuelve los ``.py`` del paquete ``nikodym.ui``."""
    return sorted(_UI_DIR.glob("*.py"))


def _nombres_importados(arbol: ast.AST) -> set[str]:
    """Extrae los nombres de módulo importados (``import x`` / ``from x import y``)."""
    nombres: set[str] = set()
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Import):
            nombres.update(alias.name for alias in nodo.names)
        elif isinstance(nodo, ast.ImportFrom) and nodo.module is not None and nodo.level == 0:
            nombres.add(nodo.module)
    return nombres


def test_ui_no_usa_eval_ni_exec() -> None:
    """Ningún módulo de ``nikodym.ui`` llama ``eval``/``exec`` (seguridad, §11)."""
    for ruta in _modulos_ui():
        arbol = ast.parse(ruta.read_text(encoding="utf-8"))
        for nodo in ast.walk(arbol):
            if isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Name):
                assert nodo.func.id not in {"eval", "exec"}, f"{ruta.name} usa {nodo.func.id}"


def test_ui_no_importa_modulos_de_dominio() -> None:
    """El backend es *domain-agnostic*: no importa binning/model/calibration/data/…"""
    for ruta in _modulos_ui():
        importados = _nombres_importados(ast.parse(ruta.read_text(encoding="utf-8")))
        for nombre in importados:
            for prohibido in _DOMINIOS_PROHIBIDOS:
                assert not (nombre == prohibido or nombre.startswith(prohibido + ".")), (
                    f"{ruta.name} importa el dominio prohibido {nombre}"
                )


def test_ui_no_reimplementa_formulas_de_dominio() -> None:
    """No aparecen fórmulas de riesgo reimplementadas (roc_auc/WoE) en la capa ui."""
    fuente = "\n".join(ruta.read_text(encoding="utf-8") for ruta in _modulos_ui())
    assert not re.search(r"\broc_auc\b", fuente, re.IGNORECASE)
    assert not re.search(r"\bwoe\b", fuente, re.IGNORECASE)
