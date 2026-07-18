"""Guardas del script canónico de captura F3."""

from __future__ import annotations

from pathlib import Path
from runpy import run_path

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "capture_demo_fixtures.py"
_SYMBOLS = run_path(str(_SCRIPT))
_CAPTURE_WORKDIR_NAME = _SYMBOLS["_CAPTURE_WORKDIR_NAME"]
_canonical_capture_workdir = _SYMBOLS["_canonical_capture_workdir"]


def test_capture_workdir_estable_exclusivo_y_autolimpiable(tmp_path: Path) -> None:
    """La captura usa una ruta fija, rechaza dos writers y limpia al terminar."""
    expected = tmp_path.resolve() / _CAPTURE_WORKDIR_NAME

    with _canonical_capture_workdir(root=tmp_path) as workdir:
        assert workdir == expected
        assert workdir.is_dir()
        with (
            pytest.raises(RuntimeError, match="ya existe"),
            _canonical_capture_workdir(root=tmp_path),
        ):
            pytest.fail("un segundo writer no debe adquirir el mismo workdir")

    assert not expected.exists()
