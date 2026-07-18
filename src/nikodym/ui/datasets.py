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

# Esquema del dataset de PROVISIONES: superconjunto del de F1. Las columnas nuevas llevan
# ``role="economic"`` — no son features del scorecard (no entran al binning), sino los inputs
# económico-regulatorios que consumen el motor estándar CMF (Cap. B-1 §3.1.3) y el método interno
# (Cap. B-1 §3). Ver ``_generate_provisiones`` para los invariantes de coherencia.
#
# Deliberadamente AUSENTES (SDD-28 §6.2), no por olvido:
#   * ``cmf_category``  — en cartera `consumer` el motor NUNCA la lee: deriva la categoría de
#     (bucket de mora, hipotecario en el sistema, mora en el sistema). Las categorías A1-C6 son de
#     cartera COMERCIAL individual. Incluirla haría creer que en consumo la categoría es un input.
#   * ``is_default``    — el Cap. B-1 num. 3.2 tiene tres causales de incumplimiento; solo la mora
#     >= 90 días se deriva de los datos. Las otras dos (refinanciar para dejar vigente una
#     operación morosa, reestructuración forzosa/condonación) las declara el banco por esta
#     columna, que el motor lee como opcional. Se omite aquí porque esta cartera SINTÉTICA no
#     tiene deudores refinanciados: incluirla vacía no aportaría nada y añadir refinanciados
#     movería el índice de riesgo que quedó calibrado contra el sistema (8,63 % vs 8,30 % real).
#   * ``guarantee_*`` / ``financial_guarantee_*`` / ``aval_*`` / ``contingent_*`` — el motor CMF
#     OLFATEA estos nombres y con la política por defecto (`fail`) ABORTA la corrida.
_PROVISIONING_COLUMNS: tuple[dict[str, str], ...] = (
    *_COLUMNS,
    {"name": "as_of_date", "dtype": "str", "role": "economic"},
    {"name": "debtor_id", "dtype": "str", "role": "economic"},
    {"name": "cmf_portfolio", "dtype": "str", "role": "economic"},
    {"name": "cmf_product_type", "dtype": "str", "role": "economic"},
    {"name": "days_past_due", "dtype": "int", "role": "economic"},
    {"name": "has_housing_loan_system", "dtype": "bool", "role": "economic"},
    {"name": "system_dpd30_last_3m", "dtype": "bool", "role": "economic"},
    {"name": "exposure_amount", "dtype": "float", "role": "economic"},
    {"name": "lgd", "dtype": "float", "role": "economic"},
)

# Esquema del dataset IFRS 9 / ECL (SDD-16): superconjunto del de F1 con (a) las dos columnas que
# exige la capa ``survival`` (SDD-18) para ajustar la term-structure lifetime PD —``duration``/
# ``event`` (rol ``survival``)— y (b) las columnas económicas que consume el step
# ``provisioning_ifrs9``: fecha de cálculo única, cartera/segmento, EAD, LGD, tasa efectiva (EIR),
# mora en días y flag de default (rol ``economic``). Genérico LatAm y **agnóstico de moneda**: los
# montos son de escala retail sin símbolo (la moneda se rotula en el front). Las carteras son
# genéricas (Consumo/Tarjetas/Comercial/Hipotecario), sin país ni institución. Ver
# ``_generate_ifrs9_retail`` para los invariantes de coherencia.
_IFRS9_COLUMNS: tuple[dict[str, str], ...] = (
    *_COLUMNS,
    {"name": "duration", "dtype": "int", "role": "survival"},
    {"name": "event", "dtype": "int", "role": "survival"},
    {"name": "as_of_date", "dtype": "str", "role": "economic"},
    {"name": "portfolio", "dtype": "str", "role": "economic"},
    {"name": "ead", "dtype": "float", "role": "economic"},
    {"name": "lgd", "dtype": "float", "role": "economic"},
    {"name": "eir", "dtype": "float", "role": "economic"},
    {"name": "days_past_due", "dtype": "int", "role": "economic"},
    {"name": "is_default", "dtype": "bool", "role": "economic"},
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
    "consumo_drift": {
        "name": "Consumo — con drift (deterioro)",
        "description": (
            "Cartera de consumo con MISMAS features y cohortes que 'consumo_comportamiento' pero "
            "con DRIFT TEMPORAL: la cartera se DETERIORA en cohortes recientes (más mora, más "
            "utilización, más DTI, menos ingreso y antigüedad), así la tasa de default sube y un "
            "modelo entrenado en cohortes viejas se degrada en OOT. Útil para demostrar PSI/CSI y "
            "estabilidad (drift claro entre Dev y OOT=2024Q2)."
        ),
        "n_rows": 6000,
        "seed": 20_240_710,
        "segments": ("asalariado", "independiente", "pensionado"),
        "cohorts": ("2023Q1", "2023Q2", "2023Q3", "2023Q4", "2024Q1", "2024Q2"),
        "intercept": -2.2,
        "antiguedad_low": 1,
        "antiguedad_high": 121,
        "drift": True,
    },
    "provisiones_consumo": {
        "name": "Consumo — provisiones (CMF + método interno)",
        "description": (
            "Cartera de consumo con las columnas económico-regulatorias que exigen los motores de "
            "provisiones: exposición, mora en días, deudor (varias operaciones por RUT, para que "
            "la consolidación del Cap. B-1 se ejercite), tipo de producto, los dos flags de "
            "sistema (hipotecario vigente y mora de 30d o más en los últimos 3 meses) y la LGD "
            "interna. Superconjunto del dataset de scorecard: el pipeline F1 corre igual, y "
            "encima se calculan el método estándar de la CMF y el método interno "
            "(PD·LGD·Exposición por grupo homogéneo). Tasa de default de un dígito y mora "
            "truncada a 180 días (Cap. B-2: más allá se castiga)."
        ),
        "n_rows": 6000,
        # Con 5.200 deudores para 6.000 operaciones, ~30 % tiene >=2 productos: suficiente para que
        # la consolidación por deudor del B-1 se ejercite, sin inventar una cartera irreal donde
        # casi todos tienen varios créditos.
        "n_debtors": 4444,
        "seed": 20_240_713,
        "as_of_date": "2024-06-30",
        "segments": ("asalariado", "independiente", "pensionado"),
        "cohorts": ("2023Q1", "2023Q2", "2023Q3", "2023Q4", "2024Q1", "2024Q2"),
        # Recalibrado: el intercepto de F1 (-2,2) produce un 23 % de default, inverosímil para una
        # cartera de consumo chilena. Con -3,70 la tasa queda en un dígito (~6,7 %).
        "intercept": -4.15,
        "antiguedad_low": 1,
        "antiguedad_high": 121,
        "provisioning": True,
    },
    "ifrs9_retail_latam": {
        "name": "Retail LatAm — IFRS 9 / ECL (multi-cartera)",
        "description": (
            "Cartera retail multi-producto (Consumo, Tarjetas, Comercial, Hipotecario) con las "
            "columnas que exige la pérdida esperada IFRS 9 (ECL): historia de supervivencia "
            "(duración/evento) para ajustar la curva lifetime PD, más EAD, LGD, tasa efectiva "
            "(EIR), mora en días y flag de default. Superconjunto del dataset de scorecard: el "
            "pipeline F1 corre igual y encima se calcula la ECL de tres etapas (Stage 1/2/3), con "
            "staging por los backstops de mora 30/90 días (presunciones IFRS 9 5.5.11 / B5.5.37). "
            "Montos de escala retail y AGNÓSTICOS de moneda (sin símbolo; la moneda se rotula en "
            "la vista). Genérico LatAm, sin país ni institución. IFRS 9 es EXPERIMENTAL (SDD-16, "
            "fuera de la garantía SemVer 1.x) y la EAD se despliega CONSTANTE por período "
            "(limitación conocida FALTA-DATO-IFRS-4: sin perfil de amortización)."
        ),
        "n_rows": 6000,
        "seed": 20_260_715,
        "as_of_date": "2025-06-30",
        "segments": ("asalariado", "independiente", "pensionado"),
        "cohorts": ("2023Q1", "2023Q2", "2023Q3", "2023Q4", "2024Q1", "2024Q2"),
        "intercept": -4.15,
        "antiguedad_low": 1,
        "antiguedad_high": 121,
        # Horizonte lifetime en periodos ANUALES: el motor ECL descuenta con la convención
        # ``annual_eir_year_fraction`` (DF = (1+EIR)^(-time_value)), asi que ``time_value`` debe
        # estar en años. Con periodos anuales, ``time_value`` == periodo (1..T años), la EIR es
        # anual y el descuento es correcto y honesto. Ver ``_generate_ifrs9_retail``.
        "horizon_years": 5,
        "portfolios": ("Consumo", "Tarjetas", "Comercial", "Hipotecario"),
        "portfolio_weights": (0.40, 0.30, 0.15, 0.15),
        "ifrs9": True,
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
            "columns": [dict(column) for column in _columns_for(dataset_id)],
            "n_rows": spec["n_rows"],
        }
        for dataset_id, spec in _DATASETS.items()
    ]


def _columns_for(dataset_id: str) -> tuple[dict[str, str], ...]:
    """Devuelve el esquema de columnas del dataset (los de provisiones traen un superconjunto)."""
    spec = _DATASETS[dataset_id]
    if spec.get("ifrs9"):
        return _IFRS9_COLUMNS
    if spec.get("provisioning"):
        return _PROVISIONING_COLUMNS
    return _COLUMNS


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
    if spec.get("drift"):  # rama separada: los datasets sin drift no tocan una sola llamada al rng
        return _generate_drift(dataset_id)
    if spec.get("ifrs9"):  # superconjunto: survival (duration/event) + economicas IFRS 9 / ECL
        return _generate_ifrs9_retail(dataset_id)
    if spec.get("provisioning"):  # superconjunto de columnas: motor CMF + método interno
        return _generate_provisiones(dataset_id)
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


def _generate_provisiones(dataset_id: str) -> pd.DataFrame:
    """Genera la cartera de consumo con las columnas que exigen los motores de provisiones.

    Es un **superconjunto** de las 9 columnas de F1 (para que el pipeline de scorecard corra sin
    cambios) más las que piden el motor estándar CMF (Cap. B-1 §3.1.3) y el método interno
    (Cap. B-1 §3). Todo sale de **un solo proceso latente**: un dato coherente es el requisito de
    credibilidad de la demo, y una cartera con seis muestreos independientes se le nota a un
    gerente de riesgo en segundos (SDD-28 §6.3 y R1).

    Invariantes que el generador garantiza **por construcción** (los verifica el gate G1):

    1. **Deudores con varias operaciones** (~30 % con >=2). Sin esto, la consolidación por deudor
       del B-1 —la regla central de la norma en consumo— nunca se ejercita.
    2. **``days_past_due`` correlaciona con el riesgo latente, pero NO es determinista de
       ``bad_flag``.** ``bad_flag`` mira hacia adelante (ventana de desempeño) y ``days_past_due``
       es el estado de hoy: volverlos idénticos metería *target leakage*, el scorecard predeciría
       el presente, el KS saldría absurdo y el gerente dejaría de creer toda la pantalla.
    3. ``mora_max_12m >= days_past_due``: la mora máxima de 12 meses no puede ser menor que la
       mora actual (un revisor cruza esas dos columnas).
    4. **Los flags de sistema son POR DEUDOR**, no por operación (el motor CMF hace ``any()`` sobre
       el deudor). ``has_housing_loan_system`` correlaciona **negativamente** con el riesgo y
       ``system_dpd30_last_3m`` está casi implicado por la mora propia: quien está en mora contigo,
       lo está en el sistema. Estos dos booleanos **son** la provisión CMF: la PI va de 3,3 % a
       19,8 % con la misma mora en el banco (factor 6x).
    5. **``cmf_product_type`` correlaciona con ``utilizacion_linea``**: la utilización alta vive en
       tarjetas/líneas; un crédito en cuotas no tiene línea que utilizar.
    6. **``exposure_amount`` lo explican las features**: ``≈ ingreso · deuda_ingreso · κ``, en CLP
       plausible y con cola derecha (lognormal), no uniforme.
    7. **``lgd`` distribuida (Beta), nunca constante**, y anclada por **debajo** de la PDI
       normativa del producto — la PDI regulatoria es más conservadora que la LGD interna. Es lo
       que hace que el estándar muerda de forma **explicable** y no arbitraria.
    8. **Mora truncada a 180 días**: más allá, el Cap. B-2 obliga a castigar; una cartera viva con
       500 días de mora no existe.
    9. **Tasa de default de un dígito** (``intercept`` recalibrado): la cartera F1 tiene un 23 % de
       default, inverosímil para consumo chileno.

    .. note::

       **Benchmark VERIFICADO en fuente oficial (2026-07-14).** El índice de riesgo (provisión /
       colocaciones) de la **cartera de consumo del sistema bancario chileno es 8,30 %**
       (noviembre 2025). Con estos parámetros el motor estándar CMF produce **8,63 %** sobre esta
       cartera: **33 pb sobre el sistema**, dentro de la banda en que consumo se ha movido
       (8,1-8,3 % entre septiembre 2025 y mayo 2026). La cartera sintética provisiona como el
       sistema real.

       **Fuente:** CMF, *Informe del Desempeño del Sistema Bancario y Cooperativas — Noviembre
       2025*, sección 2.2 (Riesgo de crédito), pág. 5:
       *"en consumo el indicador de provisiones se expandió desde un 8,24 % hasta 8,30 %"*.
       ``https://www.cmfchile.cl/portal/estadisticas/626/articles-102371_recurso_1.pdf``

       Desagregación del mismo informe y mismo perímetro (Sistema Bancario, colocaciones a costo
       amortizado): comercial 2,63 % · **consumo 8,30 %** · vivienda 0,65 % · **total 2,59 %**.
       El 2,59 % que se citaba antes es el **agregado de todas las carteras** y **no es
       comparable** con una cartera de consumo: consumo va 3,2 veces sobre el agregado.

       **Al citarlo, no mezclar perímetros:** el Cuadro N°2 de esos informes reporta 2,61 %, que
       es el consolidado *Sistema Bancario + Cooperativas*, un perímetro distinto.

       El informe declara igualmente que la cartera es **sintética**: que caiga en el rango del
       sistema la hace defendible, no la convierte en un benchmark de mercado. Ver SDD-28 §R1.
    """
    spec = _DATASETS[dataset_id]
    rng = np.random.default_rng(spec["seed"])
    n_rows: int = spec["n_rows"]

    # --- Deudores: varias operaciones por deudor, para que la consolidación del B-1 exista ---
    # La mezcla se construye EXPLÍCITAMENTE (70 % de los deudores con un producto, 25 % con dos,
    # 5 % con tres) en vez de muestrear índices al azar: el muestreo con reemplazo colisiona y deja
    # el reparto —que es justo lo que queremos controlar— en manos del azar.
    n_debtors: int = spec["n_debtors"]
    tamanos = np.concatenate(
        [
            np.ones(round(n_debtors * 0.70), dtype="int64"),
            np.full(round(n_debtors * 0.25), 2, dtype="int64"),
            np.full(
                n_debtors - round(n_debtors * 0.70) - round(n_debtors * 0.25), 3, dtype="int64"
            ),
        ]
    )
    debtor_idx = np.repeat(np.arange(len(tamanos)), tamanos)
    if debtor_idx.size < n_rows:  # completa con deudores de una sola operación
        extra = np.arange(len(tamanos), len(tamanos) + (n_rows - debtor_idx.size))
        debtor_idx = np.concatenate([debtor_idx, extra])
    debtor_idx = debtor_idx[:n_rows]
    debtor_id = np.array([f"rut-{position:06d}" for position in debtor_idx], dtype=object)
    n_debtors = int(debtor_idx.max()) + 1

    # --- Features F1 (mismas distribuciones que `consumo_comportamiento`) ---
    ingreso = rng.lognormal(mean=13.2, sigma=0.5, size=n_rows)
    deuda_ingreso = np.clip(rng.gamma(shape=2.0, scale=0.18, size=n_rows), 0.0, 2.5)
    utilizacion = np.clip(rng.beta(2.0, 3.0, size=n_rows), 0.0, 1.0)
    antiguedad = rng.integers(spec["antiguedad_low"], spec["antiguedad_high"], size=n_rows)
    segmento = rng.choice(np.asarray(spec["segments"]), size=n_rows)
    cohorte = rng.choice(np.asarray(spec["cohorts"]), size=n_rows)

    # Riesgo latente (sin la mora todavía: la mora es CONSECUENCIA del riesgo, no una feature
    # exógena que lo cause; construirla al revés es lo que produce la fuga de información).
    ingreso_z = (np.log(ingreso) - 13.2) / 0.5
    riesgo = (
        spec["intercept"]
        + 1.6 * deuda_ingreso
        + 1.2 * utilizacion
        - 0.5 * ingreso_z
        - 0.4 * (antiguedad / 60.0)
    )

    # --- Estado de mora HOY: ordenado por el riesgo latente, pero estocástico (no determinista) ---
    # El score de mora mezcla riesgo y azar; los cortes son CUANTILES suyos, no umbrales absolutos:
    # la suma de dos uniformes NO es uniforme, y con umbrales fijos la cola de incumplimiento sale
    # ~10x mas delgada de lo pedido (medido: 0,28 % en vez de 2,5 %).
    orden = np.argsort(np.argsort(riesgo))
    pct_riesgo = orden / max(n_rows - 1, 1)
    ruido = rng.random(size=n_rows)
    score_mora = 0.75 * pct_riesgo + 0.25 * ruido
    # Masas objetivo de una cartera de consumo chilena viva: ~85 % al día y ~2 % en incumplimiento
    # (la cartera deteriorada es donde está la plata: la PI del bucket >=90d es 100 %).
    #
    # Estas masas gobiernan el ÍNDICE DE RIESGO (provisión / colocaciones) resultante, que es el
    # primer número que un gerente compara contra su propia cartera. Ver la nota del docstring: el
    # índice resultante (8,63 %) quedó verificado contra el agregado de consumo del sistema (8,30%).
    cortes = np.quantile(score_mora, [0.850, 0.905, 0.940, 0.965, 0.982])
    bucket = np.searchsorted(cortes, score_mora, side="right")
    days_past_due = np.zeros(n_rows, dtype="int64")
    for indice, (bajo, alto) in enumerate(
        ((1, 8), (8, 31), (31, 61), (61, 90), (90, 181)), start=1
    ):
        marca = bucket == indice
        # Cap. B-2: la mora se castiga; una cartera viva no tiene 500 días de mora ⇒ tope en 180.
        days_past_due[marca] = rng.integers(bajo, alto, size=int(marca.sum()))

    # `mora_max_12m` (feature F1) = peor mora de los últimos 12m ⇒ nunca menor que la mora de hoy.
    mora_max_12m = np.maximum(
        np.clip(rng.poisson(lam=6.0, size=n_rows), 0, 180), days_past_due
    ).astype("int64")

    # --- Target: la logística F1, ya con la mora observada. Estocástico ⇒ sin fuga. ---
    logit = riesgo + 0.9 * (mora_max_12m / 30.0)
    prob_bad = 1.0 / (1.0 + np.exp(-logit))
    bad_flag = (rng.random(size=n_rows) < prob_bad).astype("int64")

    # --- Flags de sistema: POR DEUDOR (el motor CMF hace any() sobre el deudor) ---
    riesgo_deudor = np.zeros(n_debtors)
    np.maximum.at(riesgo_deudor, debtor_idx, pct_riesgo)
    dpd_deudor = np.zeros(n_debtors, dtype="int64")
    np.maximum.at(dpd_deudor, debtor_idx, days_past_due)

    # Tener hipotecario en el sistema es señal de MEJOR pagador (la propia matriz de la CMF lo
    # refleja: PI 3,3 % con hipotecario vs 6,6 % sin él, a igual mora).
    p_housing = np.clip(0.55 - 0.40 * riesgo_deudor, 0.05, 0.95)
    housing_deudor = rng.random(size=n_debtors) < p_housing
    # Mora en el sistema: casi implicada por la mora propia (un deudor con 60 días de mora contigo
    # y "sin mora en el sistema" es inverosímil), pero POCO frecuente entre los que están al día.
    #
    # Este flag es el parámetro más sensible de toda la cartera: dispara la PI de 6,6 % a 19,8 %
    # para un deudor al día (factor 3x), así que su frecuencia marginal MANDA sobre la provisión
    # total. Calibrado a la baja para que el índice de riesgo resultante sea defendible.
    p_system = np.where(dpd_deudor >= 30, 0.85, np.where(dpd_deudor > 0, 0.22, 0.025))
    system_deudor = rng.random(size=n_debtors) < p_system

    has_housing_loan_system = housing_deudor[debtor_idx]
    system_dpd30_last_3m = system_deudor[debtor_idx]

    # --- Producto: correlacionado con la utilización de línea ---
    producto = np.where(
        utilizacion > 0.55,
        "tarjetas_lineas_otros",
        np.where(rng.random(size=n_rows) < 0.075, "leasing_auto", "creditos_en_cuotas"),
    ).astype(object)

    # --- Exposición: explicada por ingreso y DTI, en CLP, con cola derecha ---
    exposure_bruta = ingreso * deuda_ingreso * 6.0 * np.exp(rng.normal(0.0, 0.25, size=n_rows))
    exposure = np.round(np.clip(exposure_bruta, 50_000.0, None), 2)

    # --- LGD interna: Beta por producto, SIEMPRE por debajo de la PDI normativa del producto ---
    # PDI CMF (sin hipotecario): leasing 33,2 % · cuotas 56,6 % · tarjetas 60,3 %.
    lgd_centro: np.ndarray[Any, np.dtype[np.float64]] = np.select(
        [producto == "leasing_auto", producto == "tarjetas_lineas_otros"],
        [0.28, 0.52],
        default=0.46,
    ).astype("float64")
    # Sin hipotecario ⇒ menor garantía implícita ⇒ LGD algo mayor (coherente con la matriz).
    lgd_centro = lgd_centro + np.where(has_housing_loan_system, -0.03, 0.03).astype("float64")
    concentracion = 25.0
    lgd_muestra = rng.beta(
        lgd_centro * concentracion, (1.0 - lgd_centro) * concentracion, size=n_rows
    )
    lgd = np.round(np.clip(lgd_muestra, 0.01, 0.99), 4)

    loan_id = pd.Index([f"op-{position:06d}" for position in range(n_rows)], name="loan_id")
    return pd.DataFrame(
        {
            "ingreso_mensual": np.round(ingreso, 2),
            "deuda_ingreso": np.round(deuda_ingreso, 4),
            "utilizacion_linea": np.round(utilizacion, 4),
            "mora_max_12m": mora_max_12m,
            "antiguedad_meses": antiguedad.astype("int64"),
            "segmento": segmento.astype(object),
            "cohorte": cohorte.astype(object),
            "bad_flag": bad_flag,
            "as_of_date": np.full(n_rows, spec["as_of_date"], dtype=object),
            "debtor_id": debtor_id,
            "cmf_portfolio": np.full(n_rows, "consumer", dtype=object),
            "cmf_product_type": producto,
            "days_past_due": days_past_due,
            "has_housing_loan_system": has_housing_loan_system,
            "system_dpd30_last_3m": system_dpd30_last_3m,
            "exposure_amount": exposure,
            "lgd": lgd,
        },
        index=loan_id,
    )


def _generate_ifrs9_retail(dataset_id: str) -> pd.DataFrame:
    """Genera la cartera retail LatAm multi-producto para la ECL IFRS 9 (SDD-16).

    Es un **superconjunto** de las 9 columnas de F1 (para que el scorecard corra sin cambios) más
    (a) la historia de supervivencia que exige ``survival`` (SDD-18) —``duration``/``event``— para
    ajustar la term-structure lifetime PD, y (b) las columnas económicas que consume el step
    ``provisioning_ifrs9``: ``as_of_date`` (única por corrida), ``portfolio``, ``ead``, ``lgd``,
    ``eir``, ``days_past_due`` y ``is_default``. Todo sale de **un solo proceso latente** (un riesgo
    subyacente por operación), porque un dato coherente es el requisito de credibilidad de la demo.

    Invariantes que el generador garantiza **por construcción**:

    1. **Periodos ANUALES.** ``duration`` es el año (1..``horizon_years``) hasta el default o la
       censura. El motor ECL descuenta con ``annual_eir_year_fraction`` (``DF=(1+EIR)^(-time)``
       con ``time_value`` = periodo = año), así que la EIR es **anual** y el descuento es correcto.
       Un horizonte fijo con muchas operaciones censuradas al último año fija
       ``max_observed_period = horizon_years``: la grilla lifetime llega hasta el horizonte sin
       extrapolar (el discrete-hazard no extrapola fuera del soporte observado).
    2. **``days_past_due`` correlaciona con el riesgo latente pero NO es determinista del default
       futuro** (``event``/``bad_flag`` miran hacia adelante; la mora es el estado de hoy).
       Volverlos idénticos metería *target leakage* y el scorecard predeciría el presente.
    3. **Staging visible S1/S2/S3.** La mora se reparte para activar las presunciones DPD bajo la
       política conservadora v1:
       ~80 % al día, ~8 % 1-29 d (Stage 1), ~8 % 30-89 d (**Stage 2**, presunción 5.5.11) y ~4 %
       90+ d (**Stage 3**, presunción B5.5.37). ``is_default`` marca los 90+ d y una fracción
       reestructurada con mora <90 d (un default cualitativo, no capturado por la mora). Resultado:
       Stage 2 > Stage 3, el patrón realista (cartera al día >> en mora >> en default).
    4. **EAD, LGD y EIR por cartera.** Retail (Consumo/Tarjetas) con EAD menor y EIR/LGD mayores;
       Comercial/Hipotecario con EAD mayor y EIR/LGD menores (garantía). Montos de escala retail,
       **sin moneda** (se rotula en el front). La ``lgd`` es Beta por cartera (nunca constante).
    5. **La EAD se despliega CONSTANTE por período** en el motor (limitación conocida
       FALTA-DATO-IFRS-4: sin perfil de amortización). El dataset entrega un solo nivel de EAD por
       operación; no finge una curva de amortización.

    No se inventan parámetros regulatorios: los umbrales de staging (30/90 d) son las presunciones
    rebatibles de IFRS 9 y los defaults del motor; ``pit_mode='ttc_only'`` (sin ajuste PIT) y
    ``scenarios='single'`` evitan pedir ``rho``/``Z`` o pesos macro que no tendríamos cómo defender.

    IFRS 9 está implementado y es EXPERIMENTAL (fuera de la garantía SemVer 1.x).
    """
    spec = _DATASETS[dataset_id]
    rng = np.random.default_rng(spec["seed"])
    n_rows: int = spec["n_rows"]
    horizon: int = spec["horizon_years"]
    portfolios = np.asarray(spec["portfolios"])
    portfolio_weights = np.asarray(spec["portfolio_weights"], dtype="float64")

    # --- Features F1 (mismas distribuciones que ``consumo_comportamiento``) ---
    ingreso = rng.lognormal(mean=13.2, sigma=0.5, size=n_rows)
    deuda_ingreso = np.clip(rng.gamma(shape=2.0, scale=0.18, size=n_rows), 0.0, 2.5)
    utilizacion = np.clip(rng.beta(2.0, 3.0, size=n_rows), 0.0, 1.0)
    antiguedad = rng.integers(spec["antiguedad_low"], spec["antiguedad_high"], size=n_rows)
    segmento = rng.choice(np.asarray(spec["segments"]), size=n_rows)
    cohorte = rng.choice(np.asarray(spec["cohorts"]), size=n_rows)

    # Riesgo latente (sin la mora: la mora es CONSECUENCIA del riesgo, no una feature exógena).
    ingreso_z = (np.log(ingreso) - 13.2) / 0.5
    riesgo = (
        spec["intercept"]
        + 1.6 * deuda_ingreso
        + 1.2 * utilizacion
        - 0.5 * ingreso_z
        - 0.4 * (antiguedad / 60.0)
    )

    # --- Mora HOY: ordenada por el riesgo latente pero estocástica (cuantiles de un score) ---
    orden = np.argsort(np.argsort(riesgo))
    pct_riesgo = orden / max(n_rows - 1, 1)
    score_mora = 0.72 * pct_riesgo + 0.28 * rng.random(size=n_rows)
    # Cortes: ~80 % al día, ~8 % 1-29 d, ~8 % 30-89 d (Stage 2), ~4 % 90+ d (Stage 3).
    cortes = np.quantile(score_mora, [0.80, 0.88, 0.96])
    bucket = np.searchsorted(cortes, score_mora, side="right")  # 0,1,2,3
    days_past_due = np.zeros(n_rows, dtype="int64")
    for indice, (bajo, alto) in enumerate(((1, 30), (30, 90), (90, 181)), start=1):
        marca = bucket == indice
        # Cap. B-2: la mora se castiga; una cartera viva no supera ~180 días de mora.
        days_past_due[marca] = rng.integers(bajo, alto, size=int(marca.sum()))

    # ``mora_max_12m`` (feature F1) = peor mora de 12m ⇒ nunca menor que la mora de hoy.
    mora_max_12m = np.maximum(
        np.clip(rng.poisson(lam=6.0, size=n_rows), 0, 180), days_past_due
    ).astype("int64")

    # --- Target F1: la logística, ya con la mora observada. Estocástico ⇒ sin fuga. ---
    logit = riesgo + 0.9 * (mora_max_12m / 30.0)
    prob_bad = 1.0 / (1.0 + np.exp(-logit))
    bad_flag = (rng.random(size=n_rows) < prob_bad).astype("int64")

    # --- Survival: año hasta default (hazard anual crece con el riesgo), censura al horizonte ---
    risk_z = (riesgo - riesgo.mean()) / riesgo.std()
    # Hazard anual ~ sigmoid(-3.0 + 0.85·z): PD anual base ~4,7 %; cumulativa a T años ~20-25 %.
    hazard = 1.0 / (1.0 + np.exp(-(-3.0 + 0.85 * risk_z)))
    duration = np.full(n_rows, horizon, dtype="int64")
    event = np.zeros(n_rows, dtype="int64")
    draws = rng.random(size=(n_rows, horizon))
    for i in range(n_rows):
        for t in range(horizon):
            if draws[i, t] < hazard[i]:
                duration[i] = t + 1
                event[i] = 1
                break

    # --- Cartera (portfolio): mezcla retail-heavy ---
    portfolio = rng.choice(portfolios, size=n_rows, p=portfolio_weights)
    is_consumo = portfolio == "Consumo"
    is_tarjetas = portfolio == "Tarjetas"
    is_comercial = portfolio == "Comercial"

    # --- EAD por cartera: retail menor, comercial/hipotecario mayor; escala retail sin moneda ---
    ead_center = np.select(
        [is_consumo, is_tarjetas, is_comercial], [8000.0, 4000.0, 38000.0], default=52000.0
    )
    ead = np.round(
        np.clip(ead_center * np.exp(rng.normal(0.0, 0.35, size=n_rows)), 2000.0, 80000.0), 2
    )

    # --- LGD Beta por cartera (nunca constante); menor con garantía (hipotecario) ---
    lgd_center: np.ndarray[Any, np.dtype[np.float64]] = np.select(
        [is_consumo, is_tarjetas, is_comercial], [0.55, 0.68, 0.42], default=0.22
    ).astype("float64")
    concentracion = 30.0
    lgd = np.round(
        np.clip(
            rng.beta(lgd_center * concentracion, (1.0 - lgd_center) * concentracion, size=n_rows),
            0.03,
            0.95,
        ),
        4,
    )

    # --- EIR anual efectiva por cartera (tasa de descuento de la ECL) ---
    eir_center: np.ndarray[Any, np.dtype[np.float64]] = np.select(
        [is_consumo, is_tarjetas, is_comercial], [0.28, 0.42, 0.16], default=0.09
    ).astype("float64")
    eir = np.round(np.clip(eir_center + rng.normal(0.0, 0.015, size=n_rows), 0.03, 0.60), 4)

    # --- is_default: 90+ días de mora o una pequeña fracción reestructurada con mora <90 días ---
    restructured = (days_past_due < 90) & (rng.random(size=n_rows) < 0.010)
    is_default = (days_past_due >= 90) | restructured

    loan_id = pd.Index([f"op-{position:06d}" for position in range(n_rows)], name="loan_id")
    return pd.DataFrame(
        {
            "ingreso_mensual": np.round(ingreso, 2),
            "deuda_ingreso": np.round(deuda_ingreso, 4),
            "utilizacion_linea": np.round(utilizacion, 4),
            "mora_max_12m": mora_max_12m,
            "antiguedad_meses": antiguedad.astype("int64"),
            "segmento": segmento.astype(object),
            "cohorte": cohorte.astype(object),
            "bad_flag": bad_flag,
            "duration": duration,
            "event": event,
            "as_of_date": np.full(n_rows, spec["as_of_date"], dtype=object),
            "portfolio": portfolio.astype(object),
            "ead": ead,
            "lgd": lgd,
            "eir": eir,
            "days_past_due": days_past_due,
            "is_default": is_default,
        },
        index=loan_id,
    )


def _generate_drift(dataset_id: str) -> pd.DataFrame:
    """Genera un dataset con DRIFT temporal: la cartera se deteriora en cohortes recientes.

    A diferencia de :func:`_generate` (features de distribución **fija**), aquí los parámetros de
    cada feature corren monótonamente con la posición temporal de la cohorte ``t∈[0,1]`` (``0`` =
    cohorte más antigua, ``1`` = más reciente): en cohortes recientes sube la mora (``lam`` del
    Poisson), la utilización (``beta`` hacia 1), el DTI (``scale`` del gamma), y bajan el ingreso
    (media log) y la antigüedad. El ``bad_flag`` sale de la **MISMA** logística sobre las
    features **ya driftadas**, de modo que la tasa de default también sube en cohortes recientes
    (deterioro coherente). Mismas 9 columnas/dtypes/rangos (clip) que :func:`_generate`; sirve para
    demostrar PSI/CSI y la degradación del modelo entre Dev (cohortes viejas) y OOT (2024Q2).
    """
    spec = _DATASETS[dataset_id]
    rng = np.random.default_rng(spec["seed"])
    n_rows: int = spec["n_rows"]
    cohorts = np.asarray(spec["cohorts"])

    # Cohorte de cada fila (uniforme) y su posición temporal normalizada t∈[0,1] sobre las cohortes
    # ordenadas: t escala la magnitud del deterioro fila a fila.
    cohorte_idx = rng.integers(0, len(cohorts), size=n_rows)
    cohorte = cohorts[cohorte_idx]
    t = cohorte_idx / (len(cohorts) - 1)

    # Parámetros corridos por t (recientes = peor riesgo); rangos plausibles con el mismo clip base.
    ingreso = rng.lognormal(mean=13.2 - 0.25 * t, sigma=0.5, size=n_rows)
    deuda_ingreso = np.clip(rng.gamma(shape=2.0, scale=0.18 + 0.14 * t, size=n_rows), 0.0, 2.5)
    utilizacion = np.clip(rng.beta(2.0 + 2.6 * t, 3.0 - 1.3 * t, size=n_rows), 0.0, 1.0)
    mora = np.clip(rng.poisson(lam=4.5 + 9.0 * t, size=n_rows), 0, 180)
    antiguedad_base = rng.integers(spec["antiguedad_low"], spec["antiguedad_high"], size=n_rows)
    antiguedad = np.clip(np.round(antiguedad_base * (1.0 - 0.25 * t)), 1, 120).astype("int64")
    segmento = rng.choice(np.asarray(spec["segments"]), size=n_rows)

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
            "antiguedad_meses": antiguedad,
            "segmento": segmento.astype(object),
            "cohorte": cohorte.astype(object),
            "bad_flag": bad_flag,
        },
        index=loan_id,
    )
