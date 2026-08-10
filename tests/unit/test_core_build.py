"""Tests de identidad de build/runtime W1."""

from __future__ import annotations

from pathlib import Path

import pytest

import nikodym.core.build as build_module
from nikodym.core.exceptions import ReproducibilityError


def test_sdist_con_pyproject_sin_git_confia_en_manifest_embebido(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_module = tmp_path / "src" / "nikodym" / "core" / "build.py"
    fake_module.parent.mkdir(parents=True)
    fake_module.touch()
    (tmp_path / "pyproject.toml").touch()
    monkeypatch.setattr(build_module, "__file__", str(fake_module))

    assert len(build_module.build_uv_lock_hash()) == 64


def test_checkout_git_sin_lock_falla_cerrado(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_module = tmp_path / "src" / "nikodym" / "core" / "build.py"
    fake_module.parent.mkdir(parents=True)
    fake_module.touch()
    (tmp_path / "pyproject.toml").touch()
    (tmp_path / ".git").touch()
    monkeypatch.setattr(build_module, "__file__", str(fake_module))

    with pytest.raises(ReproducibilityError, match="no el lock canónico"):
        build_module.build_uv_lock_hash()


def test_installed_distribution_hash_es_sha256_estable() -> None:
    first = build_module.installed_distribution_hash()
    second = build_module.installed_distribution_hash()
    assert first == second
    assert len(first) == 64
