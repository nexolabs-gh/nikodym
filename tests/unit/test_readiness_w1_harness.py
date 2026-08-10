"""Tests focales del arnés clean-room W1, sin ejecutar los perfiles de escala."""

from __future__ import annotations

import importlib.util
import sys
import zipfile
from pathlib import Path, PurePosixPath
from types import ModuleType

import pytest


def _driver() -> ModuleType:
    path = Path(__file__).resolve().parents[2] / "scripts" / "measure_readiness_w1.py"
    spec = importlib.util.spec_from_file_location("nikodym_readiness_w1_driver", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _FakeDistribution:
    def __init__(self, root: Path, files: tuple[PurePosixPath, ...]) -> None:
        self._root = root
        self.files = files

    def locate_file(self, relative: PurePosixPath) -> Path:
        return self._root / relative


def test_hash_metadata_compara_wheel_e_instalacion_y_detecta_drift(tmp_path: Path) -> None:
    driver = _driver()
    members = {
        "nikodym/__init__.py": b"__version__ = '1.0'\n",
        "nikodym-1.0.dist-info/METADATA": b"Name: nikodym\nVersion: 1.0\n",
        "nikodym-1.0.dist-info/WHEEL": b"Wheel-Version: 1.0\n",
        "nikodym-1.0.dist-info/licenses/LICENSE": b"Apache-2.0\n",
    }
    wheel = tmp_path / "nikodym-1.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        for name, content in members.items():
            archive.writestr(name, content)
    install = tmp_path / "site-packages"
    for name, content in members.items():
        path = install / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    distribution = _FakeDistribution(
        install,
        tuple(PurePosixPath(name) for name in members),
    )

    expected = driver._wheel_metadata_hash(wheel)
    assert driver._installed_metadata_hash(distribution) == expected

    (install / "nikodym-1.0.dist-info" / "METADATA").write_text(
        "Name: nikodym\nVersion: 9.9\n", encoding="utf-8"
    )
    assert driver._installed_metadata_hash(distribution) != expected


def test_driver_no_importa_nikodym_al_cargar() -> None:
    module = _driver()
    assert "nikodym" not in module.__dict__


@pytest.mark.skipif(sys.platform != "win32", reason="API nativa específica de Windows")
def test_peak_rss_windows_usa_handle_sin_truncar() -> None:
    driver = _driver()
    assert driver._peak_rss_bytes() > 0


def test_evidencia_de_informe_exige_html_y_qmd_reales(tmp_path: Path) -> None:
    driver = _driver()
    (tmp_path / "scorecard_report.html").write_text("<html></html>", encoding="utf-8")
    (tmp_path / "scorecard_report.qmd").write_text("---\ntitle: prueba\n---\n", encoding="utf-8")

    evidence = driver._report_evidence(tmp_path)
    assert evidence["html_verified"] is True
    assert evidence["markdown_verified"] is True
    assert {item["path"] for item in evidence["files"]} == {
        "scorecard_report.html",
        "scorecard_report.qmd",
    }

    (tmp_path / "scorecard_report.qmd").unlink()
    (tmp_path / "scorecard_report.md").write_text("# salida equivocada\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match=r"HTML\+QMD"):
        driver._report_evidence(tmp_path)


def test_workdir_cleanroom_debe_quedar_fuera_del_checkout(tmp_path: Path) -> None:
    driver = _driver()
    external = tmp_path / "evidence"
    assert driver._validate_external_workdir(external) == external.resolve()

    inside = driver.ROOT / ".evidence-w1-prohibida"
    with pytest.raises(RuntimeError, match="workdir clean-room quedó dentro del checkout"):
        driver._validate_external_workdir(inside)


def test_generador_materializa_cardinalidad_exacta_con_special_soportado() -> None:
    driver = _driver()
    frame = driver._training_frame({"train_rows": 12, "variables": 2, "cardinality": 4})

    assert frame["x_000"].nunique() == 4
    assert set(frame["x_000"]) == {-88888, 0, 1, 2}
    assert int(frame["x_000"].eq(-88888).sum()) == 9
    assert set(frame.loc[frame["x_000"].eq(-88888), "bad_flag"]) == {0, 1}


def test_generador_garantiza_soporte_dev_para_cada_categoria_ordinaria() -> None:
    driver = _driver()
    frame = driver._training_frame({"train_rows": 1_000, "variables": 2, "cardinality": 100})

    desarrollo = frame.loc[frame["sample_split"].eq("DEV")]
    assert set(range(99)).issubset(set(desarrollo["x_000"]))
    assert set(desarrollo.loc[desarrollo["x_000"].eq(-88888), "bad_flag"]) == {0, 1}
    assert set(frame["sample_split"]) == {"DEV", "HOLDOUT", "OOT"}
