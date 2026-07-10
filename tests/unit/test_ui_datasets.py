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
    assert [d["id"] for d in primero] == [
        "consumo_comportamiento",
        "hipotecario_comportamiento",
        "consumo_drift",
    ]

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


# ─────────────────────────── consumo_drift (deterioro temporal, B37) ───────────────────────────


def test_consumo_drift_en_catalogo() -> None:
    """``consumo_drift`` aparece en el catálogo con id/name/columns/n_rows correctos."""
    descriptor = next(d for d in list_datasets() if d["id"] == "consumo_drift")
    assert descriptor["name"] == "Consumo — con drift (deterioro)"
    assert descriptor["n_rows"] == 6000
    assert len(descriptor["columns"]) == 9  # mismas 9 columnas del esquema común
    roles = {col["role"] for col in descriptor["columns"]}
    assert roles >= _ROLES_ESPERADOS
    # mismo esquema (nombres/orden) que los datasets estables — el config F1 corre sin editar.
    otro = next(d for d in list_datasets() if d["id"] == "consumo_comportamiento")
    assert descriptor["columns"] == otro["columns"]


def test_consumo_drift_materializa_columnas_y_dtypes(tmp_path: Path) -> None:
    """``materialize('consumo_drift')`` produce un parquet con las 9 columnas y dtypes esperados."""
    frame = pd.read_parquet(materialize("consumo_drift", workdir=tmp_path))
    assert frame.index.name == "loan_id"
    assert len(frame) == 6000
    assert list(frame.columns) == [
        "ingreso_mensual",
        "deuda_ingreso",
        "utilizacion_linea",
        "mora_max_12m",
        "antiguedad_meses",
        "segmento",
        "cohorte",
        "bad_flag",
    ]
    assert frame["ingreso_mensual"].dtype == "float64"
    assert frame["deuda_ingreso"].dtype == "float64"
    assert frame["utilizacion_linea"].dtype == "float64"
    assert frame["mora_max_12m"].dtype == "int64"
    assert frame["antiguedad_meses"].dtype == "int64"
    assert frame["bad_flag"].dtype == "int64"
    assert frame["segmento"].dtype == object
    assert frame["cohorte"].dtype == object
    assert set(frame["bad_flag"].unique()) == {0, 1}


def test_consumo_drift_deterioro_temporal(tmp_path: Path) -> None:
    """El drift es medible sin dominio: la cohorte 2024Q2 está claramente peor que 2023Q1.

    Umbrales holgados pero significativos (no floats frágiles): la media de ``mora_max_12m`` sube al
    menos +3, la de ``utilizacion_linea`` al menos +0.15 y la tasa de ``bad_flag`` al menos +0.10.
    """
    frame = pd.read_parquet(materialize("consumo_drift", workdir=tmp_path))
    q1 = frame[frame["cohorte"] == "2023Q1"]
    q2 = frame[frame["cohorte"] == "2024Q2"]
    assert q2["mora_max_12m"].mean() > q1["mora_max_12m"].mean() + 3.0
    assert q2["utilizacion_linea"].mean() > q1["utilizacion_linea"].mean() + 0.15
    assert q2["bad_flag"].mean() > q1["bad_flag"].mean() + 0.10


# Golden byte-lógico de los datasets ESTABLES: si una sola llamada al rng de ``_generate`` cambiara
# (p.ej. por tocar su ruta al agregar el drift), estas medias/sumas exactas se romperían. Blinda la
# byte-identidad exigida por B37 sin depender de bytes de parquet (no canónicos cross-versión).
_GOLDEN_ESTABLES: dict[str, dict[str, float]] = {
    "consumo_comportamiento": {
        "n_rows": 6000,
        "mora_mean": 6.026333,
        "deuda_mean": 0.364034,
        "util_mean": 0.399101,
        "antiguedad_mean": 61.246833,
        "ingreso_mean": 605495.1396,
        "bad_sum": 1407,
    },
    "hipotecario_comportamiento": {
        "n_rows": 4000,
        "mora_mean": 6.023750,
        "deuda_mean": 0.363534,
        "util_mean": 0.402251,
        "antiguedad_mean": 124.201750,
        "ingreso_mean": 616444.1323,
        "bad_sum": 253,
    },
}


@pytest.mark.parametrize("dataset_id", sorted(_GOLDEN_ESTABLES))
def test_byte_identidad_datasets_existentes(dataset_id: str, tmp_path: Path) -> None:
    """Los datasets estables NO cambiaron al introducir ``consumo_drift`` (golden byte-lógico)."""
    frame = pd.read_parquet(materialize(dataset_id, workdir=tmp_path))
    golden = _GOLDEN_ESTABLES[dataset_id]
    assert len(frame) == golden["n_rows"]
    assert frame.index[0] == "op-000000"
    assert frame.index[-1] == f"op-{golden['n_rows'] - 1:06d}"
    assert frame["mora_max_12m"].mean() == pytest.approx(golden["mora_mean"], abs=1e-6)
    assert frame["deuda_ingreso"].mean() == pytest.approx(golden["deuda_mean"], abs=1e-6)
    assert frame["utilizacion_linea"].mean() == pytest.approx(golden["util_mean"], abs=1e-6)
    assert frame["antiguedad_meses"].mean() == pytest.approx(golden["antiguedad_mean"], abs=1e-6)
    assert frame["ingreso_mensual"].mean() == pytest.approx(golden["ingreso_mean"], abs=1e-4)
    assert int(frame["bad_flag"].sum()) == golden["bad_sum"]
