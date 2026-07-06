"""Tests del backend FastAPI vía ``TestClient`` y del núcleo liviano por capas (SDD-23 §4.2, §11).

Requiere el extra ``[ui]`` (fastapi) y su backend de test (``httpx2``); si faltan, los tests se
saltan (no rompen la suite base). El bootstrap ``create_app`` se cubre por *smoke* de ``TestClient``
(D-UI-10): la lógica pura ya está al 100% en ``test_ui_routes.py``.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx2")

from fastapi.testclient import TestClient

from nikodym.core.config import NikodymConfig, ReproConfig, config_hash
from nikodym.ui import server
from nikodym.ui.server import create_app
from nikodym.ui.settings import UiConfig


@pytest.fixture
def client() -> TestClient:
    """``TestClient`` sobre la app construida con ajustes por defecto."""
    return TestClient(create_app(UiConfig()))


def _f1_config() -> NikodymConfig:
    """Config F1 (data→binning→model→scorecard→calibration) para el endpoint de validación."""
    from nikodym.binning.config import BinningConfig
    from nikodym.calibration.config import CalibrationConfig
    from nikodym.data.config import (
        CohortSplitConfig,
        ColumnSpec,
        DataConfig,
        LoadingConfig,
        PartitionConfig,
        Predicate,
        Rule,
        SchemaConfig,
        TargetConfig,
    )
    from nikodym.model.config import (
        IvContributionConfig,
        ModelConfig,
        SignPolicyConfig,
        StepwiseConfig,
    )
    from nikodym.scorecard.config import ScorecardConfig

    return NikodymConfig(
        repro=ReproConfig(seed=20_240_628),
        data=DataConfig(
            load=LoadingConfig(source="cartera.parquet"),
            schema_=SchemaConfig(
                columns=(
                    ColumnSpec(name="ingreso_mensual", dtype="float", nullable=False),
                    ColumnSpec(name="segmento", dtype="str", nullable=False),
                    ColumnSpec(name="bad_flag", dtype="int", nullable=False),
                    ColumnSpec(name="cohorte", dtype="str", nullable=False),
                ),
                index_col="loan_id",
            ),
            target=TargetConfig(
                bad_rule=Rule(all_of=(Predicate(col="bad_flag", op="==", value=1),))
            ),
            partition=PartitionConfig(
                strategy=CohortSplitConfig(
                    cohort_col="cohorte", oot_cohorts=("2024Q2",), holdout_fraction=0.20
                ),
                min_bads_per_partition=0,
            ),
        ),
        binning=BinningConfig(
            feature_columns=("ingreso_mensual", "segmento"), categorical_columns=("segmento",)
        ),
        model=ModelConfig(
            stepwise=StepwiseConfig(direction="none"),
            sign_policy=SignPolicyConfig(action="flag", fail_on_forced_inverted=False),
            iv_contribution=IvContributionConfig(action="flag"),
        ),
        scorecard=ScorecardConfig(rounding_method="none"),
        calibration=CalibrationConfig(
            target_pd=0.20, anchor_source="business_input", min_fit_rows=1
        ),
    )


# ─────────────────────────────── endpoints (TestClient) ───────────────────────────────


def test_endpoint_schema(client: TestClient) -> None:
    """``GET /api/schema`` devuelve el JSON-Schema, defaults y orden de secciones."""
    respuesta = client.get("/api/schema")
    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert set(cuerpo) == {"json_schema", "defaults", "section_order"}
    assert cuerpo["section_order"] == list(NikodymConfig.model_fields)


def test_endpoint_validate_valido(client: TestClient) -> None:
    """``POST /api/validate`` con un config F1 válido → 200 ``{valid:true, config_hash}``."""
    cfg = _f1_config()
    respuesta = client.post(
        "/api/validate", json={"config": cfg.model_dump(mode="json", by_alias=True)}
    )
    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["valid"] is True
    assert cuerpo["config_hash"] == config_hash(cfg)
    assert cuerpo["errors"] == []


def test_endpoint_validate_invalido_siempre_200(client: TestClient) -> None:
    """Un config inválido responde 200 con ``valid:false`` y errores (validar es su función)."""
    respuesta = client.post("/api/validate", json={"config": {"repro": {"seed": -1}}})
    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["valid"] is False
    assert cuerpo["config_hash"] is None
    assert cuerpo["errors"][0]["loc"] == ["repro", "seed"]


def test_endpoint_datasets(client: TestClient) -> None:
    """``GET /api/datasets`` lista el catálogo sintético estable."""
    respuesta = client.get("/api/datasets")
    assert respuesta.status_code == 200
    ids = [descriptor["id"] for descriptor in respuesta.json()]
    assert ids == ["consumo_comportamiento", "hipotecario_comportamiento"]


# ─────────────────────────────── bootstrap de create_app ───────────────────────────────


def test_create_app_sin_build_no_monta_static() -> None:
    """Sin directorio de build, ``/static`` no se monta (guard, no falla)."""
    app = create_app(UiConfig())
    assert not any(getattr(ruta, "name", None) == "static" for ruta in app.routes)
    assert isinstance(app.state.settings, UiConfig)


def test_create_app_monta_static_si_existe_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Con un build presente, ``/static`` sirve el ``index.html`` de la SPA."""
    build = tmp_path / "static"
    build.mkdir()
    (build / "index.html").write_text("<!doctype html><title>nikodym</title>", encoding="utf-8")
    monkeypatch.setattr(server, "_static_dir", lambda: build)

    app = create_app(UiConfig())
    assert any(getattr(ruta, "name", None) == "static" for ruta in app.routes)
    respuesta = TestClient(app).get("/static/index.html")
    assert respuesta.status_code == 200


# ─────────────────── núcleo liviano por capas (snapshot de sys.modules) ───────────────────


def test_import_ui_liviano_fastapi_perezoso() -> None:
    """Subproceso limpio: los imports de lógica pura no traen fastapi; ``create_app`` sí."""
    code = textwrap.dedent(
        """
        import sys
        import nikodym
        import nikodym.core.config
        import nikodym.ui
        import nikodym.ui.datasets
        import nikodym.ui.settings
        import nikodym.ui.routes
        import nikodym.ui.server

        # Importar la lógica pura (incluido server) NO arrastra fastapi/uvicorn (import perezoso).
        for m in ("fastapi", "uvicorn"):
            assert m not in sys.modules, "fuga tras imports puros: " + m

        # Recién construir la app trae fastapi.
        from nikodym.ui.server import create_app
        from nikodym.ui.settings import UiConfig
        create_app(UiConfig())
        assert "fastapi" in sys.modules, "create_app no cargó fastapi"
        print("ok")
        """
    )
    completed = subprocess.run(
        [sys.executable, "-c", code],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert completed.returncode == 0, completed.stderr + completed.stdout
    assert completed.stdout.strip() == "ok"


def test_json_error_shape_es_serializable(client: TestClient) -> None:
    """Los errores de validación viajan como JSON plano (loc/msg/type), sin objetos ``ctx``."""
    cuerpo: dict[str, Any] = client.post(
        "/api/validate", json={"config": {"campo_desconocido": 1}}
    ).json()
    assert cuerpo["valid"] is False
    for error in cuerpo["errors"]:
        assert set(error) == {"loc", "msg", "type"}
