r"""Exports de datos del reporte: las tablas **por observación**, completas y fuera del documento.

Un informe de validación no es un contenedor de datasets. Las tablas con una fila por crédito
(:data:`~nikodym.report.document.PER_OBSERVATION_TABLES`) ocupaban dos tercios del documento
truncadas a 200 filas, con lo que no servían **ni como dato** (incompletas) **ni como informe**
(ruido que nadie lee). Aquí se emiten **íntegras** —sin truncar— como archivos adjuntos, y el
documento las referencia por nombre.

Dos formatos, ambos opt-in vía ``report.formats``:

- ``csv``: un archivo por tabla (``{basename}__{clave}.csv``), UTF-8 con BOM y saltos ``\\n``. Es
  byte-determinista: el mismo frame produce el mismo archivo.
- ``xlsx``: un único libro (``{basename}__por_observacion.xlsx``) con una hoja por tabla, vía
  ``openpyxl`` (extra ``excel``, import perezoso). El ``.xlsx`` es un ZIP y **no** es
  byte-determinista (guarda marcas de tiempo); su verificación es estructural, como la del PDF.

El índice del frame se exporta **siempre**: en estas tablas es el identificador de la operación
(``loan_id``), y perderlo dejaría un dataset anónimo e inservible para conciliar contra el origen.

**Experimental (fuera de la garantía SemVer 1.x).**
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, TypeAlias

from pydantic import BaseModel, ConfigDict

from nikodym.report.config import ReportConfig
from nikodym.report.document import PER_OBSERVATION_TABLES, table_title
from nikodym.report.exceptions import ReportDependencyError, ReportExportError

if TYPE_CHECKING:
    import pandas as pd

    DataFrameLike: TypeAlias = pd.DataFrame
else:
    DataFrameLike: TypeAlias = Any

__all__ = [
    "DATA_EXPORT_FORMATS",
    "DataExportRef",
    "data_export_refs",
    "per_observation_tables",
    "write_data_exports",
]

# Formatos de ``report.formats`` que producen exports de datos (no documentos).
DATA_EXPORT_FORMATS: Final[frozenset[str]] = frozenset({"csv", "xlsx"})

_WORKBOOK_SUFFIX: Final = "__por_observacion.xlsx"
_INDEX_FALLBACK_NAME: Final = "id"
_EXCEL_SHEET_MAX: Final = 31  # límite duro de Excel para el nombre de una hoja.
_EXCEL_FORBIDDEN: Final = re.compile(r"[\[\]:*?/\\]")


class DataExportRef(BaseModel):
    """Referencia a un archivo de datos adjunto, tal como el documento lo nombra.

    Es una descripción **pura**: se deriva de la config y de las claves del bundle, sin tocar el
    disco. Así el documento puede nombrar el adjunto en el mismo render en que se decide emitirlo.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    table_key: str
    title: str
    rows: int
    filename: str
    sheet: str = ""
    """Hoja del libro ``.xlsx``; vacío cuando el adjunto es un ``.csv`` (un archivo por tabla)."""


def per_observation_tables(tables: Mapping[str, DataFrameLike]) -> tuple[str, ...]:
    """Claves de las tablas por observación presentes en el bundle, en orden canónico."""
    return tuple(sorted(key for key in tables if key in PER_OBSERVATION_TABLES))


def data_export_refs(
    tables: Mapping[str, DataFrameLike],
    *,
    config: ReportConfig,
) -> tuple[DataExportRef, ...]:
    """Describe los adjuntos que producirá ``config.formats`` para las tablas por observación.

    No escribe nada: es la fuente única de nombres de archivo, compartida por los tres renderers
    (el documento referencia el adjunto) y por :func:`write_data_exports` (que lo escribe). Si no se
    pidió ``csv`` ni ``xlsx``, devuelve ``()`` y el documento lo declara explícitamente en vez de
    referenciar un archivo inexistente.
    """
    formats = set(config.formats)
    refs: list[DataExportRef] = []
    for key in per_observation_tables(tables):
        rows = len(tables[key].index)
        if "csv" in formats:
            refs.append(
                DataExportRef(
                    table_key=key,
                    title=table_title(key),
                    rows=rows,
                    filename=f"{config.basename}__{_slug(key)}.csv",
                )
            )
        if "xlsx" in formats:
            refs.append(
                DataExportRef(
                    table_key=key,
                    title=table_title(key),
                    rows=rows,
                    filename=f"{config.basename}{_WORKBOOK_SUFFIX}",
                    sheet=_sheet_name(key),
                )
            )
    return tuple(refs)


def write_data_exports(
    tables: Mapping[str, DataFrameLike],
    *,
    config: ReportConfig,
    output_dir: str,
) -> dict[str, str]:
    """Escribe los adjuntos de datos y devuelve ``{nombre_de_archivo: ruta real}``.

    Es lo que puebla :attr:`~nikodym.report.results.ReportResult.data_exports`. Las tablas se
    escriben **completas**: ``sections.max_table_rows`` acota lo que se *muestra* en el documento,
    nunca lo que se *entrega* como dato.
    """
    refs = data_export_refs(tables, config=config)
    if not refs:
        return {}
    directory = _prepare_output_dir(output_dir)
    exports: dict[str, str] = {}
    for ref in refs:
        if not ref.sheet:
            path = _write_csv(tables[ref.table_key], directory / ref.filename)
            exports[ref.filename] = str(path)
    workbook = tuple(ref for ref in refs if ref.sheet)
    if workbook:
        sheets = {ref.sheet: tables[ref.table_key] for ref in workbook}
        path = _write_xlsx(sheets, directory / workbook[0].filename)
        exports[workbook[0].filename] = str(path)
    return exports


def _prepare_output_dir(output_dir: str) -> Path:
    """Crea el directorio de salida si falta, igual que hacen el HTML, el PDF y el ``.docx``."""
    directory = Path(output_dir)
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ReportExportError(
            "No se pudo crear el directorio de los exports de datos: dominio='report', "
            f"output_dir='{output_dir}', acción='verifique permisos de la ruta padre'."
        ) from exc
    return directory


def _write_csv(table: DataFrameLike, path: Path) -> Path:
    """Escribe un ``.csv`` completo y byte-determinista (tmp + ``replace``, como el HTML)."""
    temp_path = path.with_name(f".{path.name}.tmp")
    try:
        # ``utf-8-sig``: el BOM hace que Excel abra el CSV con los acentos correctos en Windows,
        # que es donde lo va a abrir Validación. ``lineterminator`` fijo: el default depende del SO.
        _with_named_index(table).to_csv(
            temp_path, index=True, encoding="utf-8-sig", lineterminator="\n"
        )
        temp_path.replace(path)
    except OSError as exc:
        temp_path.unlink(missing_ok=True)
        raise ReportExportError(
            "No se pudo escribir el export de datos: dominio='report', formato='csv', "
            f"clave='{path.name}', output_dir='{path.parent}', "
            "acción='verifique permisos y espacio disponible'."
        ) from exc
    return path


def _write_xlsx(sheets: Mapping[str, DataFrameLike], path: Path) -> Path:
    """Escribe un libro ``.xlsx`` con una hoja por tabla (``openpyxl``, import perezoso)."""
    import pandas as pd

    temp_path = path.with_name(f".{path.name}.tmp")
    try:
        with pd.ExcelWriter(temp_path, engine="openpyxl") as writer:
            for sheet, table in sheets.items():
                _with_named_index(table).to_excel(writer, sheet_name=sheet, index=True)
        temp_path.replace(path)
    except ImportError as exc:
        temp_path.unlink(missing_ok=True)
        raise ReportDependencyError(
            "No se pudo generar el export .xlsx: falta openpyxl. Instale `nikodym[excel]` y "
            "reintente, o pida el formato 'csv', que no requiere extras."
        ) from exc
    except OSError as exc:
        temp_path.unlink(missing_ok=True)
        raise ReportExportError(
            "No se pudo escribir el export de datos: dominio='report', formato='xlsx', "
            f"clave='{path.name}', output_dir='{path.parent}', "
            "acción='verifique permisos y espacio disponible'."
        ) from exc
    return path


def _with_named_index(table: DataFrameLike) -> DataFrameLike:
    """Garantiza que el índice tenga nombre: sin él, el identificador sale como columna anónima."""
    if table.index.name:
        return table
    renamed = table.copy(deep=True)
    renamed.index = renamed.index.rename(_INDEX_FALLBACK_NAME)
    return renamed


def _slug(table_key: str) -> str:
    """Deriva el trozo de nombre de archivo de una clave de tabla (determinista, sin puntos)."""
    return re.sub(r"[^a-z0-9]+", "_", table_key.lower()).strip("_")


def _sheet_name(table_key: str) -> str:
    """Nombre de hoja válido para Excel: sin caracteres prohibidos y de 31 caracteres como máximo.

    El recorte es por la cola: los prefijos de estas claves (``model.``/``calibration.``…) son lo
    que las distingue, así que cortar el final no genera colisiones entre las tablas conocidas.
    """
    clean = _EXCEL_FORBIDDEN.sub("_", table_key.replace(".", "_"))
    return clean[:_EXCEL_SHEET_MAX]
