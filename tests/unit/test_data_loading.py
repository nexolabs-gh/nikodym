"""Tests de ``DataLoader`` (SDD-02 §4/§7): carga CSV/Parquet/Excel y copias defensivas."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from nikodym.core.exceptions import DataValidationError, MissingDependencyError
from nikodym.data import DataLoader as ExportedDataLoader
from nikodym.data.config import CsvOptions, LoadingConfig
from nikodym.data.loading import DataLoader

# Los tests que ESCRIBEN un ``.xlsx`` (``df.to_excel``) requieren openpyxl (extra [excel]). El job
# all-extras del CI lo instala y ahí ejercitan Excel de verdad; los jobs mínimos lo saltan (mismo
# patrón que ``_HAS_XGBOOST``/… en test_ml_backends.py). El motor solo lee Excel; escribirlo en el
# test es andamiaje, así que el guard cubre la escritura sin perder cobertura donde el extra existe.
_HAS_OPENPYXL = importlib.util.find_spec("openpyxl") is not None


def test_dataloader_exportado_desde_paquete_data() -> None:
    """La API pública ``nikodym.data`` expone ``DataLoader`` junto a ``DataConfig``."""
    assert ExportedDataLoader is DataLoader


def test_from_config_conserva_loading_config() -> None:
    """``from_config`` construye desde ``DataConfig.load``/``LoadingConfig`` sin mutarlo."""
    cfg = LoadingConfig(source="cartera.csv", backend="pandas")
    loader = DataLoader.from_config(cfg)
    assert loader.config is cfg


def test_dataframe_en_memoria_passthrough_con_copia_defensiva() -> None:
    """Un ``DataFrame`` en memoria se devuelve por valor: ninguna mutación cruza la frontera."""
    fuente = pd.DataFrame(
        {"saldo": [100.0, 250.0], "mora": [0, 90]},
        index=pd.Index(["op-1", "op-2"], name="loan_id"),
    )
    cargado = DataLoader().load(fuente)

    assert_frame_equal(cargado, fuente)
    assert cargado is not fuente

    cargado.loc["op-1", "saldo"] = 999.0
    fuente.loc["op-2", "saldo"] = 777.0
    assert fuente.loc["op-1", "saldo"] == 100.0
    assert cargado.loc["op-2", "saldo"] == 250.0


def test_load_usa_source_de_config_csv_con_golden_values(tmp_path: Path) -> None:
    """Si ``load`` no recibe fuente, usa ``config.source`` e infiere CSV por extensión."""
    path = tmp_path / "cartera.csv"
    path.write_text("loan_id,saldo,max_dpd_12m\nA,100.5,0\nB,250.0,90\n", encoding="utf-8")
    loader = DataLoader.from_config(LoadingConfig(source=str(path)))

    cargado = loader.load()

    assert cargado.to_dict(orient="list") == {
        "loan_id": ["A", "B"],
        "saldo": [100.5, 250.0],
        "max_dpd_12m": [0, 90],
    }
    assert float(cargado["saldo"].sum()) == 350.5


def test_load_parquet_con_golden_values_y_copia(tmp_path: Path) -> None:
    """Lee Parquet con pyarrow, preserva el índice observacional y devuelve copia defensiva."""
    fuente = pd.DataFrame(
        {"saldo": [10.0, 20.0], "malo": [0, 1]},
        index=pd.Index(["id-1", "id-2"], name="loan_id"),
    )
    path = tmp_path / "cartera.parquet"
    fuente.to_parquet(path, engine="pyarrow")

    cargado = DataLoader().load(path)

    assert_frame_equal(cargado, fuente)
    assert cargado is not fuente
    assert int(cargado["malo"].sum()) == 1


def test_pandas_csv_usa_engine_pyarrow_y_copia_defensiva(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """La ruta CSV usa ``engine='pyarrow'`` explícito y copia incluso lo leído desde pandas."""
    leido_por_pandas = pd.DataFrame({"saldo": [1, 2]})
    observado: dict[str, Any] = {}

    def fake_read_csv(path: Path, **kwargs: Any) -> pd.DataFrame:
        observado["path"] = path
        observado["kwargs"] = kwargs
        return leido_por_pandas

    monkeypatch.setattr(pd, "read_csv", fake_read_csv)
    path = tmp_path / "entrada_sin_extension"

    cargado = DataLoader(LoadingConfig(file_format="csv")).load(path)

    assert observado["path"] == path
    assert observado["kwargs"]["engine"] == "pyarrow"
    assert observado["kwargs"]["sep"] == ","
    assert cargado is not leido_por_pandas
    cargado.loc[0, "saldo"] = 999
    assert leido_por_pandas.loc[0, "saldo"] == 1


def test_pandas_parquet_usa_engine_pyarrow(monkeypatch: pytest.MonkeyPatch) -> None:
    """La ruta Parquet usa ``engine='pyarrow'`` explícito, nunca ``auto``."""
    observado: dict[str, Any] = {}

    def fake_read_parquet(path: Path, **kwargs: Any) -> pd.DataFrame:
        observado["path"] = path
        observado["kwargs"] = kwargs
        return pd.DataFrame({"saldo": [42]})

    monkeypatch.setattr(pd, "read_parquet", fake_read_parquet)
    path = Path("cartera.bin")

    cargado = DataLoader(LoadingConfig(file_format="parquet")).load(path)

    assert observado["path"] == path
    assert observado["kwargs"] == {"engine": "pyarrow"}
    assert cargado.to_dict(orient="list") == {"saldo": [42]}


def test_source_ausente_levanta_datavalidationerror() -> None:
    """Sin fuente explícita ni ``config.source`` no hay carga posible."""
    with pytest.raises(DataValidationError, match="No se entregó fuente"):
        DataLoader().load()


def test_source_tipo_no_soportado_levanta_datavalidationerror() -> None:
    """Una fuente que no sea ruta ni ``DataFrame`` falla con mensaje propio de Nikodym."""
    with pytest.raises(DataValidationError, match="Fuente de datos no soportada"):
        DataLoader().load(object())  # type: ignore[arg-type]


def test_extension_desconocida_en_auto_levanta_datavalidationerror() -> None:
    """``file_format='auto'`` solo infiere extensiones CSV/Parquet."""
    with pytest.raises(DataValidationError, match="No se pudo inferir"):
        DataLoader().load("cartera.txt")


def test_error_de_pandas_se_envuelve_en_datavalidationerror(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Un error de I/O/parser de pandas no escapa crudo."""

    def fake_read_csv(*args: Any, **kwargs: Any) -> pd.DataFrame:
        raise ValueError("csv roto")

    monkeypatch.setattr(pd, "read_csv", fake_read_csv)

    with pytest.raises(DataValidationError, match="csv roto"):
        DataLoader(LoadingConfig(file_format="csv")).load("cartera.csv")


def test_backend_pandas_no_importa_polars(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El backend pandas/DataFrame no toca el import perezoso de ``polars``."""

    def fail_import(name: str) -> Any:
        if name == "polars":
            raise AssertionError("polars no debe importarse")
        return importlib.import_module(name)

    monkeypatch.setattr("nikodym.data.loading.importlib.import_module", fail_import)
    cargado = DataLoader().load(pd.DataFrame({"saldo": [1]}))
    assert cargado.to_dict(orient="list") == {"saldo": [1]}


def test_backend_polars_sin_extra_levanta_missingdependency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``backend='polars'`` falla con mensaje accionable si el extra no está instalado."""

    def missing_polars(name: str) -> Any:
        if name == "polars":
            raise ImportError("no hay polars")
        return importlib.import_module(name)

    monkeypatch.setattr("nikodym.data.loading.importlib.import_module", missing_polars)
    loader = DataLoader(LoadingConfig(backend="polars"))

    with pytest.raises(MissingDependencyError, match=r"backend='polars'.*nikodym\[polars\]"):
        loader.load("cartera.csv")


def test_backend_polars_csv_lazy_to_pandas_y_copia(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El backend polars usa ``scan_csv(...).collect().to_pandas()`` y copia el resultado."""
    frame_polars = pd.DataFrame({"saldo": [10.0, 20.0]})
    llamadas: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    class FakeLazyFrame:
        """Mínimo objeto lazy para simular ``polars`` en tests."""

        def collect(self) -> FakeLazyFrame:
            """Devuelve el objeto materializado simulado."""
            llamadas.append(("collect", (), {}))
            return self

        def to_pandas(self) -> pd.DataFrame:
            """Colapsa a pandas como hace polars real."""
            llamadas.append(("to_pandas", (), {}))
            return frame_polars

    def scan_csv(*args: Any, **kwargs: Any) -> FakeLazyFrame:
        llamadas.append(("scan_csv", args, kwargs))
        return FakeLazyFrame()

    fake_polars = SimpleNamespace(scan_csv=scan_csv)
    monkeypatch.setattr("nikodym.data.loading.importlib.import_module", lambda name: fake_polars)
    loader = DataLoader(
        LoadingConfig(
            backend="polars",
            csv_options=CsvOptions(sep=";", decimal=",", encoding="utf-8"),
        )
    )

    cargado = loader.load("cartera.csv")

    assert llamadas[0] == (
        "scan_csv",
        ("cartera.csv",),
        {"separator": ";", "encoding": "utf-8", "decimal_comma": True},
    )
    assert [llamada[0] for llamada in llamadas] == ["scan_csv", "collect", "to_pandas"]
    assert cargado is not frame_polars
    cargado.loc[0, "saldo"] = 999.0
    assert frame_polars.loc[0, "saldo"] == 10.0


def test_backend_polars_parquet_lazy_to_pandas(monkeypatch: pytest.MonkeyPatch) -> None:
    """La rama Parquet de polars usa ``scan_parquet`` y devuelve pandas."""
    llamadas: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    class FakeLazyFrame:
        """Mínimo objeto lazy para simular ``polars`` en Parquet."""

        def collect(self) -> FakeLazyFrame:
            """Materializa el lazy frame simulado."""
            return self

        def to_pandas(self) -> pd.DataFrame:
            """Devuelve un ``DataFrame`` canónico para el assert."""
            return pd.DataFrame({"malo": [0, 1]})

    def scan_parquet(*args: Any, **kwargs: Any) -> FakeLazyFrame:
        llamadas.append(("scan_parquet", args, kwargs))
        return FakeLazyFrame()

    fake_polars = SimpleNamespace(scan_parquet=scan_parquet)
    monkeypatch.setattr("nikodym.data.loading.importlib.import_module", lambda name: fake_polars)

    cargado = DataLoader(LoadingConfig(backend="polars")).load("cartera.parquet")

    assert llamadas == [("scan_parquet", ("cartera.parquet",), {})]
    assert cargado.to_dict(orient="list") == {"malo": [0, 1]}


def test_backend_polars_decimal_no_soportado_levanta_datavalidationerror(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Polars solo admite el selector booleano ``decimal_comma`` para ``.`` o ``,``."""
    fake_polars = SimpleNamespace(scan_csv=lambda *args, **kwargs: None)
    monkeypatch.setattr("nikodym.data.loading.importlib.import_module", lambda name: fake_polars)
    loader = DataLoader(
        LoadingConfig(
            backend="polars",
            csv_options=CsvOptions(decimal="·"),
        )
    )

    with pytest.raises(DataValidationError, match="solo admite"):
        loader.load("cartera.csv")


def test_error_de_polars_se_envuelve_en_datavalidationerror(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Un fallo del lazy backend polars no escapa como excepción externa."""

    def scan_csv(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("falló scan_csv")

    fake_polars = SimpleNamespace(scan_csv=scan_csv)
    monkeypatch.setattr("nikodym.data.loading.importlib.import_module", lambda name: fake_polars)

    with pytest.raises(DataValidationError, match="falló scan_csv"):
        DataLoader(LoadingConfig(backend="polars")).load("cartera.csv")


@pytest.mark.skipif(not _HAS_OPENPYXL, reason="extra [excel] no instalado")
def test_load_excel_backend_pandas_round_trip_con_golden_values(tmp_path: Path) -> None:
    """Lee un ``.xlsx`` real con backend='pandas' y recupera el ``DataFrame`` por round-trip."""
    fuente = pd.DataFrame(
        {
            "loan_id": ["A", "B", "C"],
            "saldo": [100.5, 250.0, 90.0],
            "max_dpd_12m": [0, 90, 30],
        }
    )
    path = tmp_path / "cartera.xlsx"
    fuente.to_excel(path, index=False, engine="openpyxl")

    cargado = DataLoader().load(path)

    assert_frame_equal(cargado, fuente)
    assert cargado is not fuente
    assert float(cargado["saldo"].sum()) == 440.5


@pytest.mark.skipif(not _HAS_OPENPYXL, reason="extra [excel] no instalado")
def test_load_excel_auto_infiere_por_extension_xlsx(tmp_path: Path) -> None:
    """``file_format='auto'`` infiere 'excel' por la extensión ``.xlsx`` y carga."""
    fuente = pd.DataFrame({"saldo": [1.0, 2.0], "malo": [0, 1]})
    path = tmp_path / "cartera.xlsx"
    fuente.to_excel(path, index=False, engine="openpyxl")
    loader = DataLoader.from_config(LoadingConfig(source=str(path)))  # 'auto' por defecto

    assert loader._resolve_format(path) == "excel"
    cargado = loader.load()
    assert cargado.to_dict(orient="list") == {"saldo": [1.0, 2.0], "malo": [0, 1]}


@pytest.mark.skipif(not _HAS_OPENPYXL, reason="extra [excel] no instalado")
def test_load_excel_explicito_lee_aunque_la_extension_sea_distinta(tmp_path: Path) -> None:
    """``file_format='excel'`` explícito lee un ``.xlsx`` aunque la extensión sea otra."""
    fuente = pd.DataFrame({"saldo": [5.0], "malo": [1]})
    path = tmp_path / "cartera.datos"  # extensión no estándar; openpyxl fija el formato .xlsx
    fuente.to_excel(path, index=False, engine="openpyxl")

    cargado = DataLoader(LoadingConfig(file_format="excel")).load(path)

    assert cargado.to_dict(orient="list") == {"saldo": [5.0], "malo": [1]}


def test_backend_polars_excel_levanta_datavalidationerror() -> None:
    """``backend='polars'`` + Excel falla explícito antes de tocar polars.

    No degrada al silencio ni instala calamine: Excel exige backend pandas.
    """
    loader = DataLoader(LoadingConfig(backend="polars", file_format="excel"))

    with pytest.raises(DataValidationError, match="no admite Excel"):
        loader.load("cartera.xlsx")


def test_backend_pandas_excel_sin_extra_levanta_missingdependency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """La carga de Excel falla con mensaje accionable si el extra ``[excel]`` no está instalado."""

    def missing_openpyxl(name: str) -> Any:
        if name == "openpyxl":
            raise ImportError("no hay openpyxl")
        return importlib.import_module(name)

    monkeypatch.setattr("nikodym.data.loading.importlib.import_module", missing_openpyxl)
    loader = DataLoader(LoadingConfig(file_format="excel"))

    with pytest.raises(MissingDependencyError, match=r"\[excel\].*nikodym\[excel\]"):
        loader.load("cartera.xlsx")
