"""Tests de entorno y hashing de ``nikodym.audit``."""

from __future__ import annotations

from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path

import pandas as pd
import pytest

from nikodym.audit import (
    DEFAULT_TRACKED_PACKAGES,
    AuditError,
    EnvironmentSnapshot,
    capture_environment,
    hash_dataframe,
    hash_file,
)

_GOLDEN_FILE_HASH = "06772b37982fbaa608dc92e0fb8d6623087aff97359dc8d34c0f2c618abe4de1"
_GOLDEN_UV_LOCK_HASH = "d8c9f2728aa278ebcd33ccedf3ad309a866870ad5fb93a03526b4b7655c9e911"
_GOLDEN_DATAFRAME_HASH = "d7c517674c4908b4292bf9ee2a832301e6a88fb26a3668d6f8fc64967ca9ad0b"


def test_hash_file_golden_y_errores(tmp_path: Path) -> None:
    """``hash_file`` produce sha256 estable y envuelve errores con ``AuditError``."""
    path = tmp_path / "entrada.txt"
    path.write_text("abcñ\n", encoding="utf-8")

    assert hash_file(path) == _GOLDEN_FILE_HASH

    with pytest.raises(AuditError, match="Algoritmo de hash no soportado"):
        hash_file(path, algo="no-existe")
    with pytest.raises(AuditError, match="No se pudo hashear"):
        hash_file(tmp_path / "ausente.txt")


def test_hash_dataframe_delega_a_data_hash_golden() -> None:
    """``hash_dataframe`` reusa el hash lógico de ``nikodym.data`` sin reimplementarlo."""
    index = pd.Index(["a", "b"], name="id")
    df = pd.DataFrame({"saldo": [1.0, 0.0], "mora": [0, 90]}, index=index).astype(
        {"saldo": "float64", "mora": "int64"}
    )

    assert hash_dataframe(df) == _GOLDEN_DATAFRAME_HASH
    with pytest.raises(AuditError, match="solo soporta algo='sha256'"):
        hash_dataframe(df, algo="blake2b")


def test_capture_environment_deterministico_con_inyeccion(tmp_path: Path) -> None:
    """Reloj, plataforma y versiones inyectadas generan un snapshot bit-idéntico."""
    lock = tmp_path / "uv.lock"
    lock.write_text("lock\n", encoding="utf-8")
    versions = {"nikodym": "0.1.0", "pydantic": "2.13.0"}

    snapshot = capture_environment(
        packages=("nikodym", "pydantic", "nikodym"),
        uv_lock_path=lock,
        now=lambda: datetime(2026, 6, 25, 9, 15, 0),
        version_provider=versions.__getitem__,
        python_version_provider=lambda: "3.12.9",
        platform_provider=lambda: "macOS-15-arm64",
    )

    assert snapshot == EnvironmentSnapshot(
        python_version="3.12.9",
        platform="macOS-15-arm64",
        library_versions={"nikodym": "0.1.0", "pydantic": "2.13.0"},
        uv_lock_hash=_GOLDEN_UV_LOCK_HASH,
        captured_at=datetime(2026, 6, 25, 9, 15, 0, tzinfo=UTC),
    )
    assert snapshot.model_dump(mode="json") == {
        "python_version": "3.12.9",
        "platform": "macOS-15-arm64",
        "library_versions": {"nikodym": "0.1.0", "pydantic": "2.13.0"},
        "uv_lock_hash": _GOLDEN_UV_LOCK_HASH,
        "captured_at": "2026-06-25T09:15:00Z",
    }


def test_capture_environment_defaults_y_warnings(tmp_path: Path) -> None:
    """El set default es estable; paquetes/lock ausentes producen snapshot parcial con warning."""
    lock = tmp_path / "uv.lock"
    lock.write_text("lock\n", encoding="utf-8")
    default_snapshot = capture_environment(
        uv_lock_path=lock,
        now=lambda: datetime(2026, 6, 25, 9, 15, 0, tzinfo=UTC),
        version_provider=lambda package: f"{package}-v",
        python_version_provider=lambda: "3.12.9",
        platform_provider=lambda: "macOS-15-arm64",
    )
    assert tuple(default_snapshot.library_versions) == DEFAULT_TRACKED_PACKAGES

    def missing_version(package: str) -> str:
        """Simula un paquete ausente del entorno."""
        raise metadata.PackageNotFoundError(package)

    with pytest.warns(UserWarning) as warnings_record:
        partial = capture_environment(
            packages=("ausente",),
            uv_lock_path=tmp_path / "no-lock",
            now=lambda: datetime(2026, 6, 25, 9, 15, 0, tzinfo=UTC),
            version_provider=missing_version,
            python_version_provider=lambda: "3.12.9",
            platform_provider=lambda: "macOS-15-arm64",
        )

    assert len(warnings_record) == 2
    assert partial.library_versions == {}
    assert partial.uv_lock_hash is None
    assert partial.captured_at == datetime(2026, 6, 25, 9, 15, 0, tzinfo=UTC)
