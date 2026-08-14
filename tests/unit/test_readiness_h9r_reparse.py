from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

from scripts.readiness_h9r.adapters import _plain_tree_inventory
from scripts.readiness_h9r.artifacts import (
    canonical_tree_identity,
    census_root,
    final_inventory,
)
from scripts.readiness_h9r.consumer import _regular_files_no_follow
from scripts.readiness_h9r.contracts import ContractError
from scripts.readiness_h9r.supervisor import _workdir_entries


def _reparse_or_skip(target: Path, link: Path, *, directory: bool) -> None:
    if sys.platform == "win32" and directory:
        completed = subprocess.run(
            ["cmd.exe", "/d", "/c", "mklink", "/J", str(link), str(target)],
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode == 0:
            return
    try:
        os.symlink(target, link, target_is_directory=directory)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"el runner no permite crear symlinks efímeros: {exc}")


OPERATIONS: tuple[Callable[[Path], object], ...] = (
    census_root,
    final_inventory,
    canonical_tree_identity,
)


def test_censos_rechazan_raiz_redirigida_sin_seguirla(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    (target / "secret.bin").write_bytes(b"fuera")
    link = tmp_path / "redirected-root"
    _reparse_or_skip(target, link, directory=True)

    for operation in OPERATIONS:
        with pytest.raises(ContractError, match="reparse point"):
            operation(link)


def test_censo_no_confunde_reparse_dangling_con_raiz_ausente(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "dangling-root"
    _reparse_or_skip(target, link, directory=True)
    target.rmdir()
    try:
        assert os.path.lexists(link)
        with pytest.raises(ContractError, match="reparse point"):
            census_root(link)
    finally:
        if link.is_symlink():
            link.unlink()
        elif os.path.lexists(link):
            link.rmdir()


def test_censos_rechazan_redireccion_anidada(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "escaped.bin").write_bytes(b"no-censar")
    _reparse_or_skip(outside, root / "junction-like", directory=True)

    for operation in OPERATIONS:
        with pytest.raises(ContractError, match="reparse point"):
            operation(root)


def test_censos_rechazan_hardlink_sin_abrir_alias(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    observed = root / "observed.bin"
    observed.write_bytes(b"bytes")
    os.link(observed, tmp_path / "external-alias.bin")

    for operation in OPERATIONS:
        with pytest.raises(ContractError, match="hardlink"):
            operation(root)


def test_consumidor_y_adapter_no_atraviesan_junction_dinamica(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "secret.bin"
    secret.write_bytes(b"no-censar")
    _reparse_or_skip(outside, root / "junction-like", directory=True)

    with pytest.raises(ContractError, match="reparse point"):
        _regular_files_no_follow(root)
    with pytest.raises(ContractError, match="reparse point"):
        _plain_tree_inventory(root, context="test.staging")
    entries = _workdir_entries(root)
    assert not any("secret.bin" in entry for entry in entries)
    assert any("symlink_or_reparse_point" in entry for entry in entries)
