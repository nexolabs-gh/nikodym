"""Tests de los datasets sintéticos deterministas (SDD-23 §4.3, §6, §9, §11).

Verifica: catálogo estable, roles consistentes con lo que ``config.data`` espera para F1,
determinismo byte-lógico (seeded), caché, ``dataset_id`` desconocido y bloqueo de *path traversal*.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from nikodym.ui import datasets
from nikodym.ui.datasets import list_datasets, materialize
from nikodym.ui.exceptions import UiDatasetError

_ROLES_ESPERADOS = {"id", "feature", "segment", "cohort", "target"}


def test_list_datasets_estable_y_con_roles_f1() -> None:
    """El catálogo es estable y cada dataset declara los roles que espera el pipeline F1."""
    primero = list_datasets()
    segundo = list_datasets()
    assert primero == segundo  # estable entre llamadas
    assert [d["id"] for d in primero] == ["consumo_comportamiento", "hipotecario_comportamiento"]

    for descriptor in primero:
        assert set(descriptor) == {"id", "name", "description", "columns", "n_rows"}
        roles = {col["role"] for col in descriptor["columns"]}
        assert roles >= _ROLES_ESPERADOS  # target/feature/segment/cohort/id presentes
        # exactamente un target, un segment y un cohort (consistente con la partición F1).
        assert sum(col["role"] == "target" for col in descriptor["columns"]) == 1
        assert sum(col["role"] == "segment" for col in descriptor["columns"]) == 1
        assert sum(col["role"] == "cohort" for col in descriptor["columns"]) == 1


def test_materialize_determinista_byte_logico(tmp_path: Path) -> None:
    """Dos materializaciones independientes producen el mismo contenido lógico (seeded)."""
    ruta_a = materialize("consumo_comportamiento", workdir=tmp_path / "a")
    ruta_b = materialize("consumo_comportamiento", workdir=tmp_path / "b")
    frame_a = pd.read_parquet(ruta_a)
    frame_b = pd.read_parquet(ruta_b)
    assert frame_a.equals(frame_b)
    # tamaño y target coherentes con el descriptor y correlación (ambas clases presentes).
    descriptor = next(d for d in list_datasets() if d["id"] == "consumo_comportamiento")
    assert len(frame_a) == descriptor["n_rows"]
    assert set(frame_a["bad_flag"].unique()) == {0, 1}
    assert frame_a.index.name == "loan_id"


def test_materialize_columnas_coinciden_con_el_descriptor(tmp_path: Path) -> None:
    """Las columnas materializadas (índice + datos) calzan con los ``columns`` del catálogo."""
    ruta = materialize("hipotecario_comportamiento", workdir=tmp_path)
    frame = pd.read_parquet(ruta)
    descriptor = next(d for d in list_datasets() if d["id"] == "hipotecario_comportamiento")
    nombres_descriptor = [col["name"] for col in descriptor["columns"]]
    nombres_frame = [frame.index.name, *frame.columns]
    assert nombres_frame == nombres_descriptor


def test_materialize_cachea_sin_regenerar(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Una segunda llamada devuelve el parquet cacheado sin volver a generar el DataFrame."""
    ruta_1 = materialize("consumo_comportamiento", workdir=tmp_path)
    assert ruta_1.exists()

    def _fallar(_dataset_id: str) -> pd.DataFrame:
        raise AssertionError("no debe regenerar cuando el parquet ya está cacheado")

    monkeypatch.setattr(datasets, "_generate", _fallar)
    ruta_2 = materialize("consumo_comportamiento", workdir=tmp_path)
    assert ruta_2 == ruta_1


def test_materialize_id_desconocido(tmp_path: Path) -> None:
    """Un ``dataset_id`` fuera del registro levanta ``UiDatasetError``."""
    with pytest.raises(UiDatasetError, match="desconocido"):
        materialize("no_existe", workdir=tmp_path)


def test_materialize_bloquea_path_traversal(tmp_path: Path) -> None:
    """Un id con separadores/``..`` no escapa: la allowlist lo rechaza (ruta dentro del workdir)."""
    with pytest.raises(UiDatasetError):
        materialize("../../etc/passwd", workdir=tmp_path)


def test_materialize_ruta_dentro_del_workdir(tmp_path: Path) -> None:
    """La ruta materializada queda bajo ``workdir/datasets`` (defensa ante traversal)."""
    ruta = materialize("consumo_comportamiento", workdir=tmp_path)
    datasets_dir = (tmp_path / "datasets").resolve()
    assert datasets_dir in ruta.parents
