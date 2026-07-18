"""Guardas del script canónico de captura F3."""

from __future__ import annotations

from pathlib import Path
from runpy import run_path

import pytest

from nikodym.core.config import NikodymConfig, config_hash
from nikodym.ui import routes
from nikodym.ui.datasets import materialize
from nikodym.ui.presets import PROVISIONES_DATASET_ID, provisiones_preset

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "capture_demo_fixtures.py"
_SYMBOLS = run_path(str(_SCRIPT))
_CAPTURE_WORKDIR_NAME = _SYMBOLS["_CAPTURE_WORKDIR_NAME"]
_canonical_capture_workdir = _SYMBOLS["_canonical_capture_workdir"]
_EXPECTED_SOURCE = f"{_CAPTURE_WORKDIR_NAME}/datasets/{PROVISIONES_DATASET_ID}.parquet"


def test_capture_workdir_estable_exclusivo_y_autolimpiable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """La captura usa una ruta fija, rechaza dos writers y limpia al terminar."""
    monkeypatch.chdir(tmp_path)
    expected = Path(_CAPTURE_WORKDIR_NAME)

    with _canonical_capture_workdir() as workdir:
        assert workdir == expected
        assert workdir.is_dir()
        with (
            pytest.raises(RuntimeError, match="ya existe"),
            _canonical_capture_workdir(),
        ):
            pytest.fail("un segundo writer no debe adquirir el mismo workdir")

    assert not expected.exists()


def test_capture_workdir_limpia_si_el_cuerpo_falla(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Un fallo de la corrida no deja datos ni bloquea la siguiente captura."""
    monkeypatch.chdir(tmp_path)

    with (
        pytest.raises(ValueError, match="fallo deliberado"),
        _canonical_capture_workdir() as workdir,
    ):
        assert workdir.is_dir()
        raise ValueError("fallo deliberado")

    assert not Path(_CAPTURE_WORKDIR_NAME).exists()


def test_capture_workdir_limpia_target_original_si_cambia_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """El finally usa el target validado y no un homónimo relativo al CWD nuevo."""
    original = tmp_path / "original"
    elsewhere = tmp_path / "elsewhere"
    original.mkdir()
    elsewhere.mkdir()
    monkeypatch.chdir(original)

    with _canonical_capture_workdir() as workdir:
        original_target = (original / workdir).resolve()
        monkeypatch.chdir(elsewhere)
        elsewhere_target = elsewhere / workdir
        elsewhere_target.mkdir()

    assert not original_target.exists()
    assert elsewhere_target.is_dir()


def _hash_en_checkout(root: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[str, str]:
    root.mkdir()
    with monkeypatch.context() as isolated:
        isolated.chdir(root)
        with _canonical_capture_workdir() as workdir:
            source = materialize(PROVISIONES_DATASET_ID, workdir=workdir)
            wired = routes._wire_dataset_source(provisiones_preset()["config"], source)
            digest = config_hash(NikodymConfig.model_validate(wired))
            return digest, source.as_posix()


def test_config_hash_captura_portable_entre_checkouts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Dos raíces físicas distintas producen la misma fuente lógica y el mismo config_hash."""
    hash_a, source_a = _hash_en_checkout(tmp_path / "checkout-a", monkeypatch)
    hash_b, source_b = _hash_en_checkout(tmp_path / "checkout-b", monkeypatch)

    assert source_a == source_b == _EXPECTED_SOURCE
    assert hash_a == hash_b
