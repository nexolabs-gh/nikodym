"""Tests del backend FastAPI vía ``TestClient`` y del núcleo liviano por capas (SDD-23 §4.2, §11).

Requiere el extra ``[ui]`` (fastapi) y su backend de test (``httpx2``); si faltan, los tests se
saltan (no rompen la suite base). El bootstrap ``create_app`` se cubre por *smoke* de ``TestClient``
(D-UI-10): la lógica pura ya está al 100% en ``test_ui_routes.py``.
"""

from __future__ import annotations

import io
import re
import subprocess
import sys
import textwrap
import zipfile
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx2")

from _ui_f1 import failing_config, full_f1_config, write_behavior_parquet
from fastapi.testclient import TestClient

from nikodym.core.config import NikodymConfig, ReproConfig, config_hash, dump_config, loads_config
from nikodym.ui import datasets as datasets_module
from nikodym.ui import server
from nikodym.ui.server import create_app
from nikodym.ui.settings import UiConfig


@pytest.fixture
def client() -> TestClient:
    """``TestClient`` sobre la app construida con ajustes por defecto."""
    return TestClient(create_app(UiConfig()))


@pytest.fixture
def client_tmp(tmp_path: Path) -> TestClient:
    """``TestClient`` con el ``workdir`` en un tmp aislado (para /run, /results, /report)."""
    return TestClient(create_app(UiConfig(workdir=str(tmp_path))))


def _patch_materialize(monkeypatch: pytest.MonkeyPatch) -> None:
    """Materializa el frame de 30 filas (predecible por la fake binning) en vez del real."""

    def materialize(dataset_id: str, *, workdir: Path) -> Path:
        path = Path(workdir) / "datasets" / f"{dataset_id}.parquet"
        path.parent.mkdir(parents=True, exist_ok=True)
        write_behavior_parquet(path)
        return path

    monkeypatch.setattr(datasets_module, "materialize", materialize)


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
    catalogo = respuesta.json()
    ids = [descriptor["id"] for descriptor in catalogo]
    assert ids == [
        "consumo_comportamiento",
        "hipotecario_comportamiento",
        "consumo_drift",
        "provisiones_consumo",
    ]
    # El de provisiones expone un superconjunto de columnas (las económico-regulatorias que
    # consumen el motor estándar CMF y el método interno); los de F1 solo las 9 del scorecard.
    columnas = {d["id"]: [c["name"] for c in d["columns"]] for d in catalogo}
    assert set(columnas["consumo_comportamiento"]) < set(columnas["provisiones_consumo"])
    assert "exposure_amount" in columnas["provisiones_consumo"]
    assert "exposure_amount" not in columnas["consumo_comportamiento"]


def test_endpoint_upload_csv_200(client_tmp: TestClient) -> None:
    """``POST /api/upload`` con un CSV → 200 ``{dataset_id, name, n_rows, columns}``."""
    contenido = b"col_a,col_b\n1,x\n2,y\n"
    respuesta = client_tmp.post(
        "/api/upload", files={"file": ("cartera.csv", contenido, "text/csv")}
    )
    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["dataset_id"].startswith("uploaded_")
    assert cuerpo["name"] == "cartera.csv"
    assert cuerpo["n_rows"] == 2
    assert [col["name"] for col in cuerpo["columns"]] == ["col_a", "col_b"]


def test_endpoint_upload_formato_invalido_422(client_tmp: TestClient) -> None:
    """``POST /api/upload`` con una extensión no admitida (``.txt``) → 422 (mensaje string)."""
    respuesta = client_tmp.post("/api/upload", files={"file": ("notas.txt", b"hola", "text/plain")})
    assert respuesta.status_code == 422
    assert isinstance(respuesta.json()["detail"], str)


# ─────────────────────────── round-trip YAML (/config/to-yaml, /config/from-yaml) ───────────


def test_endpoint_config_to_yaml_round_trip(client: TestClient) -> None:
    """``POST /api/config/to-yaml`` → 200 ``{yaml}`` que recarga con el MISMO ``config_hash``."""
    cfg = full_f1_config("cartera.parquet")
    respuesta = client.post(
        "/api/config/to-yaml", json={"config": cfg.model_dump(mode="json", by_alias=True)}
    )
    assert respuesta.status_code == 200
    yaml_text = respuesta.json()["yaml"]
    assert config_hash(loads_config(yaml_text)) == config_hash(cfg)


def test_endpoint_config_to_yaml_invalido_422(client: TestClient) -> None:
    """Un config inválido → 422 con el detalle estructurado ``[{loc,msg,type}]``."""
    respuesta = client.post("/api/config/to-yaml", json={"config": {"repro": {"seed": -1}}})
    assert respuesta.status_code == 422
    detalle = respuesta.json()["detail"]
    assert detalle[0]["loc"] == ["repro", "seed"]
    assert set(detalle[0]) == {"loc", "msg", "type"}


def test_endpoint_config_from_yaml_valido(client: TestClient) -> None:
    """``POST /api/config/from-yaml`` con un YAML F1 → 200 ``{config, config_hash}``."""
    cfg = full_f1_config("cartera.parquet")
    respuesta = client.post("/api/config/from-yaml", json={"yaml": dump_config(cfg)})
    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["config_hash"] == config_hash(cfg)
    assert cuerpo["config"] == cfg.model_dump(mode="json", by_alias=True)


def test_endpoint_config_from_yaml_malformado_422(client: TestClient) -> None:
    """Un YAML malformado → 422 con el mensaje (string) del motor, no un 500 opaco."""
    respuesta = client.post("/api/config/from-yaml", json={"yaml": "clave: : : roto\n"})
    assert respuesta.status_code == 422
    detalle = respuesta.json()["detail"]
    assert isinstance(detalle, str)
    assert "malformado" in detalle


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


# ─────────────────────────── /run, /results, /report (B23.3) ───────────────────────────

_DOMAIN_CARDS = ("binning", "selection", "model", "scorecard", "calibration", "performance")


def test_run_config_invalido_422(client_tmp: TestClient) -> None:
    """``POST /api/run`` con un config inválido → 422 con el detalle estructurado."""
    respuesta = client_tmp.post(
        "/api/run", json={"config": {"repro": {"seed": -1}}, "dataset_id": "consumo_comportamiento"}
    )
    assert respuesta.status_code == 422
    assert respuesta.json()["detail"][0]["loc"] == ["repro", "seed"]


def test_run_dataset_desconocido_404(client_tmp: TestClient) -> None:
    """``POST /api/run`` con un ``dataset_id`` desconocido → 404."""
    config = full_f1_config("x.parquet").model_dump(mode="json", by_alias=True)
    respuesta = client_tmp.post("/api/run", json={"config": config, "dataset_id": "no_existe"})
    assert respuesta.status_code == 404


def test_run_ok_y_results_con_cards(
    client_tmp: TestClient, fake_binning_process: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Una corrida OK → 200 ``{run_id, status:"done"}``; ``/results`` sirve las cards de dominio."""
    del fake_binning_process
    _patch_materialize(monkeypatch)
    config = full_f1_config("placeholder.parquet").model_dump(mode="json", by_alias=True)

    run = client_tmp.post(
        "/api/run", json={"config": config, "dataset_id": "consumo_comportamiento"}
    )
    assert run.status_code == 200
    cuerpo = run.json()
    assert cuerpo["status"] == "done"
    run_id = cuerpo["run_id"]

    resultados = client_tmp.get(f"/api/results/{run_id}")
    assert resultados.status_code == 200
    payload = resultados.json()
    assert payload["status"] == "done"
    for domain in _DOMAIN_CARDS:
        assert isinstance(payload[domain], dict), domain


def test_run_fallida_200_status_failed(
    client_tmp: TestClient, fake_binning_process: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Una corrida que falla a mitad → 200 ``status:"failed"`` (nunca un 500 opaco)."""
    del fake_binning_process
    _patch_materialize(monkeypatch)
    config = failing_config("placeholder.parquet").model_dump(mode="json", by_alias=True)

    respuesta = client_tmp.post(
        "/api/run", json={"config": config, "dataset_id": "consumo_comportamiento"}
    )
    assert respuesta.status_code == 200
    assert respuesta.json()["status"] == "failed"


def test_results_run_id_desconocido_404(client_tmp: TestClient) -> None:
    """``GET /api/results/{run_id}`` con un id desconocido → 404."""
    assert client_tmp.get("/api/results/" + "0" * 32).status_code == 404


def test_report_presente_200_text_html(client_tmp: TestClient, tmp_path: Path) -> None:
    """``GET /api/report/{run_id}`` con un ``report.html`` presente → 200 ``text/html``."""
    run_id = "a" * 32
    run_dir = tmp_path / "runs" / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "report.html").write_text("<h1>Reporte</h1>", encoding="utf-8")

    respuesta = client_tmp.get(f"/api/report/{run_id}")
    assert respuesta.status_code == 200
    assert respuesta.headers["content-type"].startswith("text/html")
    assert respuesta.text == "<h1>Reporte</h1>"


def test_report_sin_reporte_404(client_tmp: TestClient) -> None:
    """``GET /api/report/{run_id}`` sin reporte → 404."""
    assert client_tmp.get("/api/report/" + "0" * 32).status_code == 404


def test_report_run_id_invalido_404(client_tmp: TestClient) -> None:
    """``GET /api/report/{run_id}`` con un id no-uuid → 404 (path traversal bloqueado)."""
    assert client_tmp.get("/api/report/no-uuid").status_code == 404


def test_report_pdf_presente_200_application_pdf(client_tmp: TestClient, tmp_path: Path) -> None:
    """``GET /api/report/{run_id}/pdf`` con un ``report.pdf`` presente → 200 ``application/pdf``."""
    run_id = "b" * 32
    run_dir = tmp_path / "runs" / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "report.pdf").write_bytes(b"%PDF-1.7 nikodym")

    respuesta = client_tmp.get(f"/api/report/{run_id}/pdf")
    assert respuesta.status_code == 200
    assert respuesta.headers["content-type"].startswith("application/pdf")
    assert respuesta.headers["content-disposition"] == 'attachment; filename="reporte-modelo.pdf"'
    assert respuesta.content == b"%PDF-1.7 nikodym"


def test_report_pdf_sin_reporte_404(client_tmp: TestClient) -> None:
    """``GET /api/report/{run_id}/pdf`` sin PDF → 404."""
    assert client_tmp.get("/api/report/" + "0" * 32 + "/pdf").status_code == 404


def test_report_pdf_run_id_invalido_404(client_tmp: TestClient) -> None:
    """``GET /api/report/{run_id}/pdf`` con un id no-uuid → 404 (path traversal bloqueado)."""
    assert client_tmp.get("/api/report/no-uuid/pdf").status_code == 404


def test_report_md_presente_200_zip_con_figuras(client_tmp: TestClient, tmp_path: Path) -> None:
    """``GET /api/report/{run_id}/md`` sirve la **base editable** como ZIP autocontenido → 200.

    El estado del ``run_dir`` que monta este test es el que produce ``runs.save``, no uno cómodo:
    el documento se persiste normalizado a ``report.qmd``, pero su carpeta de figuras conserva el
    ``basename`` del motor (``scorecard_report_figuras``), que es el nombre que el propio ``.qmd``
    cita. Un test que fabricaba ``report_figuras/`` —carpeta que ``save`` nunca escribe— pasaba en
    verde mientras el ZIP real salía sin una sola figura.

    La invariante que se exige aquí no depende de esos nombres: **toda figura que el documento
    referencia viaja en el paquete, con la misma ruta relativa**. Es la única condición bajo la cual
    ``quarto render`` compila sin tocar nada.
    """
    run_id = "c" * 32
    run_dir = tmp_path / "runs" / run_id
    figuras = run_dir / "scorecard_report_figuras"
    figuras.mkdir(parents=True)
    (run_dir / "report.qmd").write_text(
        "---\ntitle: Informe\n---\n\n"
        "![Gains](scorecard_report_figuras/chart-gains.svg)\n"
        "![Coef](scorecard_report_figuras/chart-coef.svg)\n",
        encoding="utf-8",
    )
    (figuras / "chart-gains.svg").write_text("<svg/>", encoding="utf-8")
    (figuras / "chart-coef.svg").write_text("<svg/>", encoding="utf-8")

    respuesta = client_tmp.get(f"/api/report/{run_id}/md")

    assert respuesta.status_code == 200
    assert respuesta.headers["content-type"].startswith("application/zip")
    assert (
        respuesta.headers["content-disposition"]
        == 'attachment; filename="reporte-modelo-quarto.zip"'
    )
    with zipfile.ZipFile(io.BytesIO(respuesta.content)) as bundle:
        nombres = set(bundle.namelist())
        assert "report.qmd" in nombres
        documento = bundle.read("report.qmd").decode("utf-8")
        assert "title: Informe" in documento

        referenciadas = set(re.findall(r"\]\(([^)]+_figuras/[^)]+)\)", documento))
        assert referenciadas, "el documento debe referenciar sus figuras por ruta relativa"
        assert referenciadas <= nombres, (
            f"el ZIP no lleva las figuras que el documento cita: {sorted(referenciadas - nombres)}"
        )


def test_report_docx_presente_200_ooxml(client_tmp: TestClient, tmp_path: Path) -> None:
    """``GET /api/report/{run_id}/docx`` sirve el Word con su media type OOXML → 200."""
    run_id = "d" * 32
    run_dir = tmp_path / "runs" / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "report.docx").write_bytes(b"PK\x03\x04 nikodym")

    respuesta = client_tmp.get(f"/api/report/{run_id}/docx")

    assert respuesta.status_code == 200
    assert respuesta.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    assert respuesta.headers["content-disposition"] == 'attachment; filename="reporte-modelo.docx"'
    assert respuesta.content == b"PK\x03\x04 nikodym"


@pytest.mark.parametrize("formato", ["md", "docx"])
def test_report_base_editable_sin_archivo_404(client_tmp: TestClient, formato: str) -> None:
    """Sin la fuente editable → 404 explícito, nunca un 200 con cuerpo vacío."""
    assert client_tmp.get(f"/api/report/{'0' * 32}/{formato}").status_code == 404


@pytest.mark.parametrize("formato", ["md", "docx"])
def test_report_base_editable_run_id_invalido_404(client_tmp: TestClient, formato: str) -> None:
    """Un ``run_id`` no-uuid → 404 (mismo blindaje de path traversal que el resto)."""
    assert client_tmp.get(f"/api/report/no-uuid/{formato}").status_code == 404
