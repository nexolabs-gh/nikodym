"""Registro de datasets sintéticos deterministas de crédito (SDD-23 §4.3, §6, §9).

Provee dos carteras de comportamiento realistas y **usables por el pipeline F1** (features
plausibles + ``bad_flag`` binario correlacionado + ``segmento``/``cohorte`` para partición). La
generación es **determinista y seeded** (``numpy.random.default_rng`` con una semilla constante por
dataset): nunca depende del reloj ni de ``hash()`` (que varía con ``PYTHONHASHSEED``). Así, dos
materializaciones producen el mismo contenido lógico y el ``config_hash`` de la corrida es estable
(SDD-23 §9). :func:`materialize` cachea el parquet dentro del ``workdir`` y bloquea *path traversal*
(rutas siempre bajo ``workdir/datasets``). Esta capa es *domain-agnostic*: no importa módulos de
dominio ni reimplementa fórmulas de riesgo.
"""

from __future__ import annotations

import tempfile
from hashlib import sha256
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from nikodym.ui.exceptions import UiDatasetError

__all__ = ["ingest_upload", "list_datasets", "materialize"]

# Parámetros del *upload* de datasets propios (SDD-23 §4.2): formatos admitidos, techo de tamaño y
# prefijo de id. La identidad de un dataset subido es ``uploaded_<sha256(content)[:32]>`` —hash del
# CONTENIDO, no del reloj/uuid/``hash()`` (que varía con ``PYTHONHASHSEED``)— de modo que el mismo
# archivo produce el mismo ``dataset_id`` y reusa su parquet cacheado (SDD-23 §9). Esta capa es
# *domain-agnostic*: lee con pandas directo (como :func:`_generate`), sin tocar ``nikodym.data``.
_ALLOWED_UPLOAD_SUFFIXES: frozenset[str] = frozenset({".csv", ".xlsx", ".parquet"})
_MAX_UPLOAD_BYTES = 100 * 1024 * 1024  # 100 MiB
_UPLOAD_PREFIX = "uploaded_"

# Esquema común de los datasets sintéticos: (nombre, dtype lógico, rol). El orden fija el orden de
# columnas del parquet. Los dtype usan el mismo vocabulario que ``data.ColumnSpec`` y los roles son
# consistentes con lo que ``config.data`` espera para F1 (id/feature/segment/cohort/target).
_COLUMNS: tuple[dict[str, str], ...] = (
    {"name": "loan_id", "dtype": "str", "role": "id"},
    {"name": "ingreso_mensual", "dtype": "float", "role": "feature"},
    {"name": "deuda_ingreso", "dtype": "float", "role": "feature"},
    {"name": "utilizacion_linea", "dtype": "float", "role": "feature"},
    {"name": "mora_max_12m", "dtype": "int", "role": "feature"},
    {"name": "antiguedad_meses", "dtype": "int", "role": "feature"},
    {"name": "segmento", "dtype": "str", "role": "segment"},
    {"name": "cohorte", "dtype": "str", "role": "cohort"},
    {"name": "bad_flag", "dtype": "int", "role": "target"},
)

# Registro determinista: id -> parámetros de generación. ``seed`` es CONSTANTE por dataset (jamás
# derivado de hash()/reloj) para garantizar reproducibilidad byte-lógica entre corridas.
_DATASETS: dict[str, dict[str, Any]] = {
    "consumo_comportamiento": {
        "name": "Consumo — comportamiento",
        "description": (
            "Cartera de consumo con historial de comportamiento (ingreso, DTI, utilización de "
            "línea, mora máxima 12m y antigüedad) y default binario correlacionado. Segmentada por "
            "tipo de deudor y cohortada por trimestre para partición Dev/HO/OOT."
        ),
        "n_rows": 6000,
        "seed": 20_240_706,
        "segments": ("asalariado", "independiente", "pensionado"),
        "cohorts": ("2023Q1", "2023Q2", "2023Q3", "2023Q4", "2024Q1", "2024Q2"),
        "intercept": -2.2,
        "antiguedad_low": 1,
        "antiguedad_high": 121,
    },
    "hipotecario_comportamiento": {
        "name": "Hipotecario — comportamiento",
        "description": (
            "Cartera hipotecaria de menor riesgo (default más bajo) y mayor antigüedad media; "
            "mismas features de comportamiento, segmentada por destino del crédito y cohortada por "
            "trimestre."
        ),
        "n_rows": 4000,
        "seed": 20_240_707,
        "segments": ("primera_vivienda", "inversion"),
        "cohorts": ("2022Q3", "2022Q4", "2023Q1", "2023Q2", "2023Q3"),
        "intercept": -3.4,
        "antiguedad_low": 12,
        "antiguedad_high": 241,
    },
}


def list_datasets() -> list[dict[str, Any]]:
    """Devuelve el catálogo estable de datasets sintéticos.

    Returns
    -------
    list of dict
        Un descriptor por dataset con ``id``/``name``/``description``/``columns``/``n_rows``. Cada
        columna trae ``name``/``dtype``/``role``. El orden es estable (orden de inserción del
        registro), de modo que el listado no cambia entre corridas.
    """
    return [
        {
            "id": dataset_id,
            "name": spec["name"],
            "description": spec["description"],
            "columns": [dict(column) for column in _COLUMNS],
            "n_rows": spec["n_rows"],
        }
        for dataset_id, spec in _DATASETS.items()
    ]


def ingest_upload(content: bytes, filename: str, *, workdir: Path) -> dict[str, Any]:
    """Ingesta un dataset propio subido y lo materializa a parquet canónico bajo ``workdir``.

    Valida tamaño/formato, lee el archivo con pandas según su extensión (``.csv``/``.xlsx``/
    ``.parquet``) y lo materializa en ``workdir/datasets/uploaded_<token>.parquet`` (``token`` =
    ``sha256`` del contenido: determinista ⇒ el mismo archivo reusa su parquet cacheado). Devuelve
    el ``dataset_id`` más un preview de columnas. Es *domain-agnostic*: no importa ``nikodym.data``;
    el cableado de ``data.load.source`` ocurre luego en :func:`nikodym.ui.routes.run_pipeline`,
    dejando intacta la byte-identidad del config canónico (SDD-23 §9, §11).

    Parameters
    ----------
    content : bytes
        Bytes crudos del archivo subido.
    filename : str
        Nombre original; su sufijo (``.csv``/``.xlsx``/``.parquet``) determina el lector pandas.
    workdir : Path
        Directorio de trabajo local; el parquet vive en ``workdir/datasets/uploaded_<token>``.

    Returns
    -------
    dict
        ``{dataset_id, name, n_rows, columns}`` con ``columns`` = lista de ``{name, dtype}``.

    Raises
    ------
    UiDatasetError
        Si el archivo está vacío, supera ``_MAX_UPLOAD_BYTES``, su formato no está admitido, no se
        puede leer con pandas o no contiene filas/columnas de datos.
    """
    if not content:
        raise UiDatasetError("el archivo subido está vacío; suba un archivo con datos.")
    if len(content) > _MAX_UPLOAD_BYTES:
        raise UiDatasetError(
            f"el archivo subido pesa {len(content)} bytes y supera el límite admitido de "
            f"{_MAX_UPLOAD_BYTES} bytes (100 MiB)."
        )
    suffix = Path(filename).suffix.lower()
    if suffix not in _ALLOWED_UPLOAD_SUFFIXES:
        raise UiDatasetError(
            f"formato de archivo subido no admitido: '{suffix or filename}'; use uno de "
            f"{sorted(_ALLOWED_UPLOAD_SUFFIXES)}."
        )
    dataset_id = f"{_UPLOAD_PREFIX}{sha256(content).hexdigest()[:32]}"
    frame = _read_upload(content, filename, suffix)
    if len(frame) < 1 or len(frame.columns) < 1:
        raise UiDatasetError(f"el archivo subido '{filename}' no contiene filas/columnas de datos.")
    path = _upload_path(workdir, dataset_id)
    if not path.exists():  # cache por contenido: el mismo archivo no se re-materializa
        path.parent.mkdir(parents=True, exist_ok=True)
        frame.to_parquet(path)
    return {
        "dataset_id": dataset_id,
        "name": filename,
        "n_rows": len(frame),
        "columns": [{"name": str(col), "dtype": str(frame[col].dtype)} for col in frame.columns],
    }


def materialize(dataset_id: str, *, workdir: Path) -> Path:
    """Materializa un dataset a parquet determinista bajo ``workdir`` y lo cachea.

    Parameters
    ----------
    dataset_id : str
        Identificador del dataset. Un id ``uploaded_<token>`` resuelve el parquet ya materializado
        por :func:`ingest_upload`; en otro caso es la clave del registro sintético. Uno desconocido
        (o un upload no encontrado) levanta ``UiDatasetError``.
    workdir : Path
        Directorio de trabajo local; el parquet vive en ``workdir/datasets/<id>.parquet``.

    Returns
    -------
    Path
        Ruta del parquet materializado (o el cacheado si ya existía).

    Raises
    ------
    UiDatasetError
        Si el ``dataset_id`` es desconocido, un upload no está materializado, o la ruta escaparía
        del ``workdir`` (*path traversal*).
    """
    if dataset_id.startswith(_UPLOAD_PREFIX):
        path = _upload_path(workdir, dataset_id)
        if path.exists():
            return path
        raise UiDatasetError(
            f"dataset subido '{dataset_id}' no encontrado; vuelva a subir el archivo."
        )
    if dataset_id not in _DATASETS:
        raise UiDatasetError(
            f"dataset sintético '{dataset_id}' desconocido; use uno de "
            f"{sorted(_DATASETS)} o consulte list_datasets()."
        )
    path = _dataset_path(workdir, dataset_id)
    if path.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    _generate(dataset_id).to_parquet(path)
    return path


def _dataset_path(workdir: Path, dataset_id: str) -> Path:
    """Resuelve la ruta del parquet y verifica que quede dentro de ``workdir/datasets``."""
    datasets_dir = (workdir / "datasets").resolve()
    candidate = (datasets_dir / f"{dataset_id}.parquet").resolve()
    if datasets_dir not in candidate.parents:  # defensa en profundidad ante path traversal
        raise UiDatasetError(  # pragma: no cover - inalcanzable con ids del registro (allowlist)
            f"la ruta del dataset '{dataset_id}' escaparía del directorio de trabajo."
        )
    return candidate


def _upload_path(workdir: Path, dataset_id: str) -> Path:
    """Resuelve la ruta del parquet de un upload (análogo a :func:`_dataset_path`, misma defensa).

    El ``dataset_id`` es hex puro con prefijo (``uploaded_<token>``), seguro por construcción; la
    verificación de que la ruta quede bajo ``workdir/datasets`` es defensa en profundidad.
    """
    datasets_dir = (workdir / "datasets").resolve()
    candidate = (datasets_dir / f"{dataset_id}.parquet").resolve()
    if datasets_dir not in candidate.parents:  # defensa en profundidad ante path traversal
        raise UiDatasetError(  # pragma: no cover - inalcanzable con id hex + prefijo (seguro)
            f"la ruta del dataset subido '{dataset_id}' escaparía del directorio de trabajo."
        )
    return candidate


def _read_upload(content: bytes, filename: str, suffix: str) -> pd.DataFrame:
    """Lee los bytes subidos con pandas según ``suffix`` (vía temporal); envuelve fallos de parseo.

    Escribe el contenido crudo a un archivo temporal con el sufijo correcto dentro de un directorio
    temporal autolimpiable, lo lee con el lector pandas del formato (``read_csv``/``read_excel``/
    ``read_parquet``) y descarta el temporal al salir. Cualquier error de lectura se envuelve en
    ``UiDatasetError`` (nunca un fallo opaco de pandas).
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir) / f"upload{suffix}"
        tmp_path.write_bytes(content)
        try:
            if suffix == ".csv":
                return pd.read_csv(tmp_path)
            if suffix == ".xlsx":
                return pd.read_excel(tmp_path, engine="openpyxl")
            return pd.read_parquet(tmp_path)  # engine auto → pyarrow (dep base del paquete)
        except Exception as exc:  # envuelve cualquier error de parseo de pandas (no fallo opaco)
            raise UiDatasetError(
                f"no se pudo leer el archivo subido '{filename}' como {suffix.lstrip('.')}: {exc}"
            ) from exc


def _generate(dataset_id: str) -> pd.DataFrame:
    """Genera el DataFrame determinista de un dataset (seeded; ``bad_flag`` correlacionado).

    La probabilidad de default sale de una logística sobre las features (mayor DTI/utilización/mora
    y menor ingreso/antigüedad ⇒ más riesgo) y se muestrea con un Bernoulli seeded. Es un dataset
    de ejemplo: la UI no calcula riesgo (SDD-23 §1), solo materializa datos para el motor.
    """
    spec = _DATASETS[dataset_id]
    rng = np.random.default_rng(spec["seed"])
    n_rows: int = spec["n_rows"]

    ingreso = rng.lognormal(mean=13.2, sigma=0.5, size=n_rows)
    deuda_ingreso = np.clip(rng.gamma(shape=2.0, scale=0.18, size=n_rows), 0.0, 2.5)
    utilizacion = np.clip(rng.beta(2.0, 3.0, size=n_rows), 0.0, 1.0)
    mora = np.clip(rng.poisson(lam=6.0, size=n_rows), 0, 180)
    antiguedad = rng.integers(spec["antiguedad_low"], spec["antiguedad_high"], size=n_rows)
    segmento = rng.choice(np.asarray(spec["segments"]), size=n_rows)
    cohorte = rng.choice(np.asarray(spec["cohorts"]), size=n_rows)

    ingreso_z = (np.log(ingreso) - 13.2) / 0.5
    logit = (
        spec["intercept"]
        + 1.6 * deuda_ingreso
        + 1.2 * utilizacion
        + 0.9 * (mora / 30.0)
        - 0.5 * ingreso_z
        - 0.4 * (antiguedad / 60.0)
    )
    prob_bad = 1.0 / (1.0 + np.exp(-logit))
    bad_flag = (rng.random(size=n_rows) < prob_bad).astype("int64")

    loan_id = pd.Index([f"op-{position:06d}" for position in range(n_rows)], name="loan_id")
    return pd.DataFrame(
        {
            "ingreso_mensual": np.round(ingreso, 2),
            "deuda_ingreso": np.round(deuda_ingreso, 4),
            "utilizacion_linea": np.round(utilizacion, 4),
            "mora_max_12m": mora.astype("int64"),
            "antiguedad_meses": antiguedad.astype("int64"),
            "segmento": segmento.astype(object),
            "cohorte": cohorte.astype(object),
            "bad_flag": bad_flag,
        },
        index=loan_id,
    )
