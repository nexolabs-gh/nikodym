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

import pytest
from _ui_f1 import failing_config, full_f1_config, write_behavior_parquet

from nikodym.core.config import NikodymConfig, ReproConfig, config_hash
from nikodym.ui import datasets as datasets_module
from nikodym.ui import routes
from nikodym.ui.exceptions import UiDatasetError

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


def test_schema_payload_expande_dominios_f1() -> None:
    """``/schema`` entrega el schema COMPLETO: secciones F1 con ``properties`` (no opacas).

    Con el extra ``scoring`` instalado (job del CI), el motor de formulario del front recibe los
    campos reales de cada sección de dominio F1, no el schema opaco. La materialización vive en el
    core (``build_full_json_schema``); ``nikodym.ui`` sigue domain-agnostic (ver test AST abajo).
    """
    payload = routes.schema_payload()
    props = payload["json_schema"]["properties"]
    assert "properties" in props["binning"], "binning llegó opaca al front"
    for seccion in ("data", "selection", "model", "scorecard", "calibration", "performance"):
        assert "properties" in props[seccion], f"{seccion} llegó opaca"
    assert len(payload["json_schema"]["$defs"]) > 2  # opaco traía 2 (ReproConfig/RunConfig)


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


# ─────────────────────────────── cableado de dataset (_wire_dataset_source) ───────────────────────


def test_wire_dataset_source_cablea_load_source() -> None:
    """Cablea ``data.load.source`` sin mutar el dict original (copia defensiva)."""
    config = {"data": {"load": {"source": None}, "schema": {}}}
    wired = routes._wire_dataset_source(config, Path("/tmp/x.parquet"))
    assert wired["data"]["load"]["source"] == str(Path("/tmp/x.parquet"))
    assert config["data"]["load"]["source"] is None  # el original no se mutó


def test_wire_dataset_source_sin_data_no_falla() -> None:
    """Un config sin sección ``data`` se devuelve intacto (no se inventa estructura)."""
    assert routes._wire_dataset_source({"repro": {"seed": 7}}, Path("/tmp/x.parquet")) == {
        "repro": {"seed": 7}
    }


def test_wire_dataset_source_load_no_dict_se_ignora() -> None:
    """Si ``data.load`` no es un dict, no se cablea (no se corrompe el config)."""
    wired = routes._wire_dataset_source({"data": {"load": "opaco"}}, Path("/tmp/x.parquet"))
    assert wired == {"data": {"load": "opaco"}}


# ─────────────────────────── run_pipeline (lógica pura, sin FastAPI) ───────────────────────────


def _fake_materialize(tmp_path: Path) -> object:
    """Devuelve un ``materialize`` que escribe el frame de 30 filas (predecible por fake bin)."""

    def materialize(dataset_id: str, *, workdir: Path) -> Path:
        path = Path(workdir) / "datasets" / f"{dataset_id}.parquet"
        path.parent.mkdir(parents=True, exist_ok=True)
        write_behavior_parquet(path)
        return path

    del tmp_path
    return materialize


def test_run_pipeline_ok_persiste_y_devuelve_done(
    fake_binning_process: object, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Una corrida válida devuelve ``{run_id, status:"done"}`` y persiste ``results.json``."""
    del fake_binning_process
    monkeypatch.setattr(datasets_module, "materialize", _fake_materialize(tmp_path))
    config = full_f1_config("placeholder.parquet").model_dump(mode="json", by_alias=True)

    result = routes.run_pipeline(config, "consumo_comportamiento", workdir=tmp_path)

    assert result["status"] == "done"
    assert (tmp_path / "runs" / result["run_id"] / "results.json").is_file()


def test_run_pipeline_config_invalido_propaga_validation_error(tmp_path: Path) -> None:
    """Un config inválido propaga ``ValidationError`` (el endpoint lo traduce a 422)."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        routes.run_pipeline({"repro": {"seed": -1}}, "consumo_comportamiento", workdir=tmp_path)


def test_run_pipeline_dataset_desconocido_propaga_ui_dataset_error(tmp_path: Path) -> None:
    """Un ``dataset_id`` desconocido propaga ``UiDatasetError`` (el endpoint lo traduce a 404)."""
    config = full_f1_config("placeholder.parquet").model_dump(mode="json", by_alias=True)
    with pytest.raises(UiDatasetError):
        routes.run_pipeline(config, "dataset_inexistente", workdir=tmp_path)


def test_run_pipeline_corrida_fallida_status_failed(
    fake_binning_process: object, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Una corrida que falla a mitad devuelve ``status="failed"`` sin propagar (D-UI-2)."""
    del fake_binning_process
    monkeypatch.setattr(datasets_module, "materialize", _fake_materialize(tmp_path))
    config = failing_config("placeholder.parquet").model_dump(mode="json", by_alias=True)

    result = routes.run_pipeline(config, "consumo_comportamiento", workdir=tmp_path)

    assert result["status"] == "failed"


def test_run_endpoint_dependencia_faltante_422(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``/run`` traduce ``MissingDependencyError`` a 422 con el mensaje del motor (§4.2/§8)."""
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx2")
    from fastapi.testclient import TestClient

    import nikodym
    from nikodym.core.exceptions import MissingDependencyError
    from nikodym.ui.server import create_app
    from nikodym.ui.settings import UiConfig

    def _materialize(dataset_id: str, *, workdir: Path) -> Path:
        return Path(workdir) / "datasets" / f"{dataset_id}.parquet"

    def _raise_missing(config: object) -> object:
        raise MissingDependencyError("instale nikodym[tracking] para publicar al inventario.")

    monkeypatch.setattr(datasets_module, "materialize", _materialize)
    monkeypatch.setattr(nikodym, "run", _raise_missing)

    client = TestClient(create_app(UiConfig(workdir=str(tmp_path))))
    config = full_f1_config("placeholder.parquet").model_dump(mode="json", by_alias=True)
    respuesta = client.post(
        "/api/run", json={"config": config, "dataset_id": "consumo_comportamiento"}
    )

    assert respuesta.status_code == 422
    assert "nikodym[tracking]" in respuesta.json()["detail"]
