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


def test_el_manifiesto_embebido_no_derivo_del_uv_lock_del_checkout() -> None:
    """Gate explícito de la deriva ``uv.lock`` ↔ ``src/nikodym/_build_manifest.json``.

    `scripts/check_build_manifest.py` existe pero no lo invocaba **nadie**: ni un test ni un job de
    CI. La comprobación vivía sólo dentro de :func:`build_uv_lock_hash`, o sea que la deriva se
    descubría en la corrida de un usuario, no en la nuestra. Aquí queda declarada como gate: al
    correr desde este checkout la función coteja el lock real contra el manifiesto embebido.

    Es también lo que sostiene la afirmación del README: el hash del `uv.lock` viaja en el *lineage*
    de cada corrida. Si el campo pudiera salir vacío, esa promesa sería falsa.
    """
    raiz = Path(__file__).resolve().parents[2]
    if not ((raiz / "pyproject.toml").is_file() and (raiz / ".git").exists()):
        # `uv.lock` no viaja en el sdist: fuera del checkout no hay nada contra qué cotejar y la
        # función confía —correctamente— en el manifiesto embebido.
        pytest.skip("el cotejo del lock es un gate de checkout y CI")
    assert (raiz / "uv.lock").is_file(), "el checkout tiene que traer el lock canónico"
    assert len(build_module.build_uv_lock_hash()) == 64


def test_un_lock_que_no_coincide_con_el_manifiesto_falla_cerrado(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Control negativo del gate anterior: sin esto, el cotejo podría no comparar nada."""
    fake_module = tmp_path / "src" / "nikodym" / "core" / "build.py"
    fake_module.parent.mkdir(parents=True)
    fake_module.touch()
    (tmp_path / "pyproject.toml").touch()
    (tmp_path / ".git").touch()
    (tmp_path / "uv.lock").write_bytes(b"lock que no es el del manifiesto embebido\n")
    monkeypatch.setattr(build_module, "__file__", str(fake_module))

    with pytest.raises(ReproducibilityError, match=r"no coincide con uv\.lock"):
        build_module.build_uv_lock_hash()


def test_installed_distribution_hash_es_sha256_estable() -> None:
    first = build_module.installed_distribution_hash()
    second = build_module.installed_distribution_hash()
    assert first == second
    assert len(first) == 64
