"""Carga de datasets crudos para la capa ``data`` (SDD-02 §4/§7).

``DataLoader`` normaliza las fuentes admitidas (CSV, Parquet, Excel ``.xlsx`` o ``DataFrame`` en
memoria) a un ``pandas.DataFrame``. La interfaz pública siempre devuelve pandas; ``polars`` es solo
un backend interno opcional con import perezoso y colapso explícito a pandas en la frontera. Excel
requiere el extra ``[excel]`` (``openpyxl``, import perezoso) y solo admite ``backend='pandas'``.

**Estable (SemVer 1.x).**
"""

from __future__ import annotations

import importlib
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Literal, cast

import pandas as pd

from nikodym.core.audit import AuditSink
from nikodym.core.exceptions import DataValidationError, MissingDependencyError
from nikodym.data.config import LoadingConfig

__all__ = ["DataLoader"]

FileFormat = Literal["csv", "parquet", "excel"]
DataSource = str | Path | pd.DataFrame


class DataLoader:
    """Carga el dataset crudo a ``pandas.DataFrame`` con copias defensivas."""

    def __init__(self, config: LoadingConfig | None = None) -> None:
        """Construye el cargador con las opciones declarativas de ``LoadingConfig``."""
        self.config = config or LoadingConfig()

    @classmethod
    def from_config(cls, cfg: LoadingConfig) -> DataLoader:
        """Construye un cargador desde ``DataConfig.load`` / ``LoadingConfig``."""
        return cls(cfg)

    def load(
        self, source: DataSource | None = None, *, audit: AuditSink | None = None
    ) -> pd.DataFrame:
        """Carga ``source`` como ``DataFrame`` y devuelve una copia defensiva.

        Parameters
        ----------
        source : str, pathlib.Path, pandas.DataFrame or None
            Ruta CSV/Parquet/Excel (``.xlsx``) o ``DataFrame`` en memoria. Si es ``None``, usa
            ``self.config.source``; si ambos faltan, levanta ``DataValidationError``. Excel solo se
            admite con ``backend='pandas'``.
        audit : AuditSink or None
            Reservado para la orquestación de ``DataStep``; la carga no emite decisiones todavía.

        Returns
        -------
        pandas.DataFrame
            Dataset cargado. Siempre es una copia nueva respecto de la fuente interna.
        """
        del audit
        resolved_source = self._resolve_source(source)
        if isinstance(resolved_source, pd.DataFrame):
            return self._defensive_copy(resolved_source)

        file_format = self._resolve_format(resolved_source)
        if self.config.backend == "pandas":
            frame = self._load_with_pandas(resolved_source, file_format)
        else:
            frame = self._load_with_polars(resolved_source, file_format)
        return self._defensive_copy(frame)

    def _resolve_source(self, source: DataSource | None) -> Path | pd.DataFrame:
        """Resuelve la fuente explícita o la declarada en config."""
        candidate: DataSource | None = source if source is not None else self.config.source
        if candidate is None:
            raise DataValidationError(
                "No se entregó fuente de datos: pase una ruta/DataFrame a load() o declare "
                "data.load.source en la configuración."
            )
        if isinstance(candidate, pd.DataFrame):
            return candidate
        if isinstance(candidate, str | Path):
            return Path(candidate)
        raise DataValidationError(
            "Fuente de datos no soportada: se esperaba str, pathlib.Path o pandas.DataFrame; "
            f"se recibió {type(candidate).__name__}."
        )

    def _resolve_format(self, path: Path) -> FileFormat:
        """Resuelve el formato de archivo, con inferencia por extensión si ``file_format=auto``."""
        configured_format = self.config.file_format
        if configured_format != "auto":
            return configured_format

        suffix = path.suffix.lower()
        if suffix == ".csv":
            return "csv"
        if suffix == ".parquet":
            return "parquet"
        if suffix == ".xlsx":
            return "excel"
        raise DataValidationError(
            "No se pudo inferir el formato de datos desde la extensión "
            f"'{path.suffix or '<sin extensión>'}'. Declare file_format='csv', 'parquet' o 'excel'."
        )

    def _load_with_pandas(self, path: Path, file_format: FileFormat) -> pd.DataFrame:
        """Carga ``path`` con pandas usando ``engine='pyarrow'`` explícito."""
        try:
            if file_format == "csv":
                return pd.read_csv(
                    path,
                    sep=self.config.csv_options.sep,
                    decimal=self.config.csv_options.decimal,
                    encoding=self.config.csv_options.encoding,
                    engine="pyarrow",
                )
            if file_format == "excel":
                _import_openpyxl()
                read_excel = cast(Callable[..., pd.DataFrame], pd.read_excel)
                return read_excel(path, engine="openpyxl")
            read_parquet = cast(Callable[..., pd.DataFrame], pd.read_parquet)
            return read_parquet(path, engine="pyarrow")
        except MissingDependencyError:
            raise
        except Exception as exc:
            raise DataValidationError(
                f"No se pudo cargar '{path}' como {file_format} con backend='pandas': {exc}"
            ) from exc

    def _load_with_polars(self, path: Path, file_format: FileFormat) -> pd.DataFrame:
        """Carga ``path`` con polars lazy y colapsa a pandas en la frontera pública."""
        if file_format == "excel":
            raise DataValidationError(
                "backend='polars' no admite Excel; use backend='pandas' para .xlsx."
            )
        polars = _import_polars()
        try:
            if file_format == "csv":
                lazy_frame = polars.scan_csv(
                    str(path),
                    separator=self.config.csv_options.sep,
                    encoding=self.config.csv_options.encoding,
                    decimal_comma=self._polars_decimal_comma(),
                )
            else:
                lazy_frame = polars.scan_parquet(str(path))
            return cast(pd.DataFrame, lazy_frame.collect().to_pandas())
        except DataValidationError:
            raise
        except Exception as exc:
            raise DataValidationError(
                f"No se pudo cargar '{path}' como {file_format} con backend='polars': {exc}"
            ) from exc

    def _polars_decimal_comma(self) -> bool:
        """Traduce la opción decimal de CSV al contrato de polars."""
        decimal = self.config.csv_options.decimal
        if decimal == ".":
            return False
        if decimal == ",":
            return True
        raise DataValidationError(
            "backend='polars' solo admite decimal='.' o decimal=',' para CSV; "
            f"se recibió decimal={decimal!r}."
        )

    def _defensive_copy(self, frame: pd.DataFrame) -> pd.DataFrame:
        """Devuelve una copia defensiva para impedir mutaciones aguas arriba/abajo."""
        return frame.copy(deep=True)


def _import_polars() -> ModuleType:
    """Importa ``polars`` de forma perezosa y emite un mensaje accionable si falta."""
    try:
        return importlib.import_module("polars")
    except ImportError as exc:
        raise MissingDependencyError(
            "backend='polars' requiere el extra [polars]: pip install 'nikodym[polars]' "
            "(o uv add 'nikodym[polars]')."
        ) from exc


def _import_openpyxl() -> ModuleType:
    """Importa ``openpyxl`` de forma perezosa y emite un mensaje accionable si falta."""
    try:
        return importlib.import_module("openpyxl")
    except ImportError as exc:
        raise MissingDependencyError(
            "La carga de Excel (.xlsx) requiere el extra [excel]: pip install 'nikodym[excel]' "
            "(o uv add 'nikodym[excel]')."
        ) from exc
