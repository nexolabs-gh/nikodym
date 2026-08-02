"""Registro de datasets sintéticos deterministas de crédito (SDD-23 §4.3, §6, §9).

Provee dos carteras de comportamiento realistas y **usables por el pipeline F1** (features
plausibles + ``bad_flag`` binario correlacionado + ``segmento``/``cohorte`` para partición). La
generación es **determinista y seeded** (``numpy.random.default_rng`` con una semilla constante por
dataset): nunca depende del reloj ni de ``hash()`` (que varía con ``PYTHONHASHSEED``). Así, dos
materializaciones producen el mismo contenido lógico y el mismo ``data_hash``. Cuando ``workdir``
es relativo, :func:`materialize` conserva una ruta relativa portable para que el ``config_hash`` no
dependa del checkout; una ruta absoluta sigue siendo una decisión explícita del usuario y sí forma
parte del config. El parquet se cachea bajo ``workdir/datasets`` y se bloquea *path traversal*. Esta
capa es *domain-agnostic*: no importa módulos de dominio ni reimplementa fórmulas de riesgo.
"""

from __future__ import annotations

import contextlib
import json
import tempfile
from hashlib import sha256
from pathlib import Path
from typing import Any, Final

import numpy as np
import pandas as pd

from nikodym.core.dataset_check import PerfilColumna, PerfilDataset
from nikodym.ui.exceptions import UiArtifactError, UiDatasetError

__all__ = ["ingest_upload", "list_datasets", "load_frame", "materialize", "row_count"]

# Parámetros del *upload* de datasets propios (SDD-23 §4.2): formatos admitidos, techo de tamaño y
# prefijo de id. La identidad de un dataset subido es ``uploaded_<sha256(content)[:32]>`` —hash del
# CONTENIDO, no del reloj/uuid/``hash()`` (que varía con ``PYTHONHASHSEED``)— de modo que el mismo
# archivo produce el mismo ``dataset_id`` y reusa su parquet cacheado (SDD-23 §9). Esta capa es
# *domain-agnostic*: lee con pandas directo (como :func:`_generate`), sin tocar ``nikodym.data``.
_ALLOWED_UPLOAD_SUFFIXES: frozenset[str] = frozenset({".csv", ".xlsx", ".parquet"})
_UPLOAD_PREFIX = "uploaded_"

#: Tope por defecto de una subida, en bytes, para quien usa esta capa **por código**.
#:
#: ⚠️ No es «el» tope: por HTTP lo gobierna ``UiConfig.upload_max_mb``, que es la fuente única que
#: SDD-23 §4.2 ya especificaba y que hasta el 2026-08-02 no leía nadie —declaraba 200 MB mientras
#: el límite efectivo eran estos 100 MiB *hardcoded*—. Un campo de configuración que miente es peor
#: que uno que no está, así que ahora el endpoint pasa el suyo y esta constante sólo cubre la
#: llamada directa.
_MAX_UPLOAD_BYTES = 100 * 1024 * 1024  # 100 MiB


def mensaje_de_tope(tamano: int, max_bytes: int) -> str:
    """Copy único del tope superado, para que las dos comprobaciones digan lo mismo.

    Hay dos porque el archivo se puede pesar **antes** de traerlo a memoria (lo normal) y también
    después (cuando el servidor no publica el tamaño). Dos mensajes distintos para el mismo límite
    le harían creer al usuario que son dos límites.
    """
    return (
        f"el archivo subido pesa {tamano} bytes y supera el límite admitido de "
        f"{max_bytes} bytes ({max_bytes // (1024 * 1024)} MiB)."
    )


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
            "la vista). Genérico LatAm, sin país ni institución. IFRS 9 es EXPERIMENTAL (fuera de "
            "la garantía SemVer 1.x) y la EAD se despliega CONSTANTE por período: no se modela la "
            "amortización del crédito, y el motor lo declara en cada fila del resultado."
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


def list_datasets(*, workdir: Path | None = None) -> list[dict[str, Any]]:
    """Devuelve el catálogo estable de datasets sintéticos.

    Returns
    -------
    list of dict
        Un descriptor por dataset con ``id``/``name``/``description``/``columns``/``n_rows``. Cada
        columna trae ``name``/``dtype``/``role`` y, desde D-COL-7, ``values`` con sus valores
        ofrecibles —vacío mientras el dataset no se haya materializado en este ``workdir``—. El
        orden es estable (orden de inserción del registro), de modo que el listado no cambia entre
        corridas.

    ``workdir`` es opcional a propósito: sin él el catálogo sigue respondiendo lo de siempre, sin
    valores. Así el listado nunca depende de que exista un directorio de trabajo.
    """
    return [
        {
            "id": dataset_id,
            "name": spec["name"],
            "description": spec["description"],
            "columns": [
                dict(column) | {"values": list(valores_por_columna.get(column["name"], ()))}
                for column in _columns_for(dataset_id)
            ],
            "n_rows": spec["n_rows"],
        }
        for dataset_id, spec in _DATASETS.items()
        for valores_por_columna in (_valores_publicables(dataset_id, workdir),)
    ]


def _valores_publicables(dataset_id: str, workdir: Path | None) -> dict[str, tuple[str, ...]]:
    """Valores ofrecibles de un dataset del catálogo, **sin materializarlo** (D-COL-7).

    Devuelve vacío cuando todavía no hay perfil en este ``workdir``, y eso es lo correcto: el
    catálogo se sirve para *elegir* un dataset, y materializar los cinco para adornar ese listado
    convertiría un `GET` barato en cinco generaciones de `DataFrame`. En cuanto el dataset se usa
    de verdad —la corrida o el preflight lo materializan— su perfil queda al lado y el listado
    siguiente ya los trae.

    ⚠️ Vacío significa «no se sabe», nunca «esta columna no tiene valores»: el formulario cae a la
    entrada libre, que es exactamente el comportamiento anterior a D-COL-7.
    """
    if workdir is None:
        return {}
    ruta = _ruta_perfil(workdir, dataset_id)
    if not ruta.exists():
        return {}  # no se materializó aún: no se fuerza una lectura para adornar un listado
    perfil = load_profile(dataset_id, workdir=workdir)
    if perfil is None:
        return {}
    return {columna.nombre: columna.valores_frecuentes for columna in perfil.columnas}


def _columns_for(dataset_id: str) -> tuple[dict[str, str], ...]:
    """Devuelve el esquema de columnas del dataset (los de provisiones traen un superconjunto)."""
    spec = _DATASETS[dataset_id]
    if spec.get("ifrs9"):
        return _IFRS9_COLUMNS
    if spec.get("provisioning"):
        return _PROVISIONING_COLUMNS
    return _COLUMNS


def ingest_upload(
    content: bytes, filename: str, *, workdir: Path, max_bytes: int | None = None
) -> dict[str, Any]:
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
        Si el archivo está vacío, supera ``max_bytes``, su formato no está admitido, no se
        puede leer con pandas o no contiene filas/columnas de datos.
    """
    if not content:
        raise UiDatasetError("el archivo subido está vacío; suba un archivo con datos.")
    tope = _MAX_UPLOAD_BYTES if max_bytes is None else max_bytes
    if len(content) > tope:
        # Segunda línea de defensa: por HTTP el archivo ya se pesó **antes** de traerlo a memoria.
        # Ésta cubre la llamada directa por código y el servidor que no publica el tamaño.
        raise UiDatasetError(mensaje_de_tope(len(content), tope))
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
    _guardar_perfil(workdir, dataset_id, frame)
    return {
        "dataset_id": dataset_id,
        "name": filename,
        "n_rows": len(frame),
        "columns": [
            {
                "name": str(col),
                "dtype": str(frame[col].dtype),
                # D-COL-7: los valores viajan en el mismo payload que ya trae las columnas, y no
                # por un endpoint propio — mismo criterio que D-PUE-3, que abrió la puerta de
                # artefactos sin crear ninguna ruta. Aquí además son gratis: el frame está en la
                # mano. Lista vacía = «no se ofrecen», y el formulario cae a la entrada libre.
                "values": _valores_frecuentes(frame[col]),
            }
            for col in frame.columns
        ],
    }


#: Cuántos valores distintos puede tener una columna para que ofrecer una lista de ellos sirva
#: (D-COL-7). Por encima, la lista deja de ser una ayuda y pasa a ser un muro: nadie elige entre
#: doscientas opciones, y una columna así casi nunca es la que marca la muestra o el incumplimiento.
#: El corte es del **producto**, no del dominio: se puede subir sin que ningún cálculo cambie.
_MAX_VALORES_OFRECIBLES: Final = 40

#: Cuántos se publican como mucho. Es más bajo que el corte de arriba a propósito: el catálogo lo
#: sirve por HTTP en cada carga de la interfaz, y una columna de 40 categorías largas pesa.
_TOPE_VALORES_FRECUENTES: Final = 20


def _valores_frecuentes(serie: pd.Series) -> list[str]:
    """Los valores más repetidos de una columna, en texto y de mayor a menor frecuencia.

    Devuelve **lista vacía** cuando ofrecerlos no ayudaría —columna con demasiados valores
    distintos, o vacía—, y eso significa «no se midió», nunca «no tiene valores». El consumidor cae
    entonces a la entrada libre, que es el comportamiento de siempre.

    ⚠️ Se convierte a texto **aquí** y no en el consumidor, porque es la representación con la que
    el motor compara —``_split_from_column`` hace ``astype(str)``— y con la que sus mensajes de
    error publican lo observado. Elegir de esta lista tiene que escribir exactamente el literal que
    la corrida va a buscar; si la conversión viviera en el front, un float ``1.0`` podría ofrecerse
    como «1» y no encontrar nada.
    """
    sin_nulos = serie.dropna()
    if sin_nulos.empty or sin_nulos.nunique() > _MAX_VALORES_OFRECIBLES:
        return []
    conteo = sin_nulos.astype(str).value_counts()
    return [str(valor) for valor in conteo.head(_TOPE_VALORES_FRECUENTES).index]


def _ruta_perfil(workdir: Path, dataset_id: str) -> Path:
    """Ruta del perfil junto al parquet, validada contra traversal igual que él."""
    return _validated_dataset_path(workdir, f"{dataset_id}.perfil.json", uploaded=True)


def _guardar_perfil(workdir: Path, dataset_id: str, frame: pd.DataFrame) -> None:
    """Guarda lo medido sobre los datos, al lado del parquet (D-PERF-1).

    Es el **único** sitio donde se mide el perfil, y por eso lo llaman los dos productores de un
    parquet: la ingesta de un upload y la materialización de un dataset del catálogo. Los dos
    llegan aquí con el ``DataFrame`` ya en la mano —la ingesta porque lo leyó del archivo, el
    catálogo porque lo acaba de generar—, así que medir la cardinalidad no cuesta una lectura extra
    en ninguno de los dos. Se persiste en vez de recalcularse porque quien lo consume es el
    preflight, cuyo contrato es no leer los datos (D-PRE-1); leer este JSON no lo rompe.
    """
    perfil = {
        "n_filas": len(frame),
        "columnas": [
            {
                "nombre": str(col),
                "n_unicos": int(frame[col].nunique(dropna=True)),
                "es_numerica": bool(pd.api.types.is_numeric_dtype(frame[col])),
                "valores_frecuentes": _valores_frecuentes(frame[col]),
            }
            for col in frame.columns
        ],
    }
    ruta = _ruta_perfil(workdir, dataset_id)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps(perfil, ensure_ascii=False), encoding="utf-8")


def load_profile(dataset_id: str, *, workdir: Path) -> PerfilDataset | None:
    """El perfil de un dataset ya materializado, o ``None`` si no se midió (D-PERF-2).

    ``None`` significa «no se sabe» y **no** «no hay»: un dataset que todavía no se materializó en
    este ``workdir`` no tiene perfil, y ahí el preflight debe comportarse exactamente como antes en
    vez de afirmar sobre datos que nadie midió.

    Lo tienen por igual los datasets subidos y los del catálogo: si el parquet ya existe pero su
    perfil no —el caso de todo lo materializado antes de esta enmienda—, se **repone aquí**,
    leyéndolo.

    🔴 La reposición vive en esta función y no en :func:`materialize` a propósito, y la primera
    versión lo hizo mal. Puesta en `materialize`, la paga **todo** el que materialice, incluida
    :func:`row_count`, que promete resolver el conteo *sin leer los datos* leyendo sólo el pie del
    Parquet: un parquet legado sin sidecar la convertía en una lectura completa a memoria, que es
    exactamente el contrato que esa función existe para dar. Aquí la paga sólo quien pide el perfil,
    que es quien lo va a usar. Lo destapó una revisión adversarial cruzada.
    """
    try:
        ruta = _ruta_perfil(workdir, dataset_id)
    except UiDatasetError:
        return None
    if not ruta.exists():
        _reponer_perfil(workdir, dataset_id)
    if not ruta.exists():
        return None
    try:
        crudo = json.loads(ruta.read_text(encoding="utf-8"))
        return PerfilDataset(
            n_filas=int(crudo["n_filas"]),
            columnas=tuple(
                PerfilColumna(
                    nombre=str(c["nombre"]),
                    n_unicos=int(c["n_unicos"]),
                    es_numerica=bool(c["es_numerica"]),
                    # `.get` y no `[...]`: un sidecar escrito antes de D-COL-7 no trae la clave, y
                    # tratarlo como ilegible tiraría a la basura un perfil correcto —con él, el
                    # aviso de columna identificador que ya funcionaba— por un campo que sólo
                    # alimenta una ayuda. Sin valores se cae a la entrada libre de siempre.
                    valores_frecuentes=tuple(str(v) for v in c.get("valores_frecuentes", ())),
                )
                for c in crudo["columnas"]
            ),
        )
    except (OSError, ValueError, KeyError, TypeError):
        # Un perfil ilegible se trata como ausente: degradar a «no se sabe» es correcto, y hacer
        # fallar el preflight por su caché sería peor que no tener el aviso.
        return None


def _reponer_perfil(workdir: Path, dataset_id: str) -> None:
    """Repone el perfil de un parquet que ya existe, leyéndolo (D-PERF-1).

    Sin esto el perfil sería un privilegio del primer materializado: un dataset cacheado —el caso
    **normal** desde la segunda corrida, y el único posible para todo lo materializado antes de esta
    enmienda— retorna antes de tocar ningún ``DataFrame`` y jamás ganaría el suyo.

    Se repone **leyendo el parquet**, y no regenerando el dataset ni invalidando el archivo. Medido
    sobre los cinco datasets del catálogo (4.000-6.000 filas): leerlo cuesta 1,2-2,4 ms, regenerarlo
    1,9-8,9 ms y rehacer la materialización entera 6,0-16,5 ms. Pero el tiempo no es lo que decide,
    porque se paga **una vez** por dataset y luego el sidecar está: deciden dos cosas que las otras
    dos salidas no dan. Leer el parquet perfila **los bytes que el motor va a consumir**, así que el
    perfil no puede desviarse del archivo aunque el generador cambie; e invalidar sería destructivo
    para un upload, cuyo original ya no existe y habría que volver a pedirle al usuario.

    Un fallo al reponerlo **no tumba la materialización**: se degrada a «no se sabe» (D-PERF-2),
    igual que :func:`load_profile` con un perfil ilegible. El perfil sólo alimenta un aviso, y
    :func:`materialize` está en el camino de ejecutar una corrida: romperlo por un sidecar
    —``workdir`` de sólo lectura, parquet corrupto— sería mucho peor que quedarse sin el aviso.
    """
    try:
        path = (
            _upload_path(workdir, dataset_id)
            if dataset_id.startswith(_UPLOAD_PREFIX)
            else _dataset_path(workdir, dataset_id)
        )
    except UiDatasetError:
        return
    if not path.exists():
        return  # todavía no se materializó: «no se sabe» sigue siendo la respuesta honesta
    try:
        _guardar_perfil(workdir, dataset_id, pd.read_parquet(path))
    except (OSError, ValueError):
        return


def materialize(dataset_id: str, *, workdir: Path) -> Path:
    """Materializa un dataset a parquet determinista bajo ``workdir`` y lo cachea.

    Deja además su **perfil de columnas** al lado (D-PERF-1), igual que :func:`ingest_upload` con un
    archivo subido: los datasets del catálogo no tienen por qué ser los únicos sobre los que el
    preflight no puede avisar de una columna identificador. Aquí también sale gratis —el generador
    ya devuelve el ``DataFrame``—, y en la rama de caché lo repone :func:`_asegurar_perfil`.

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
    frame = _generate(dataset_id)
    frame.to_parquet(path)
    # Se mide sobre el frame recién generado y no releyendo el parquet: es el mismo dato —el gate
    # `test_el_perfil_del_catalogo_equivale_al_de_la_ingesta` lo exige para los cinco datasets— y
    # aquí ya está en memoria, que es justo la razón por la que el perfil sale gratis.
    # Fail-soft igual que la reposición: el sidecar es accesorio y `materialize` está en el camino
    # de ejecutar una corrida. Antes esta rama quedaba FUERA de la guarda, así que un `workdir` de
    # sólo lectura tumbaba la primera materialización después de haber escrito ya el parquet.
    with contextlib.suppress(OSError):
        _guardar_perfil(workdir, dataset_id, frame)
    return path


def row_count(dataset_id: str, *, workdir: Path) -> int:
    """Filas del parquet de un dataset, **sin leer los datos** (metadatos de Parquet).

    Lo consume la comprobación del modo posicional (D-PUE-6): cuando el usuario no declara llave,
    lo único que se puede verificar sin abrir los archivos es que los dos tengan el mismo número de
    filas. Barato a propósito — el pie de página de un Parquet trae el conteo.
    """
    # `pyarrow` no trae stubs; el conteo vive en el pie del Parquet, así que no se leen los datos.
    import pyarrow.parquet as pq

    source = materialize(dataset_id, workdir=workdir)
    metadata = pq.read_metadata(source)  # type: ignore[no-untyped-call]
    return int(metadata.num_rows)


def load_frame(dataset_id: str, *, workdir: Path, key_column: str | None = None) -> pd.DataFrame:
    """Lee a ``DataFrame`` el parquet de un dataset ya materializado (D-PUE-3).

    Es la única vía por la que un archivo del usuario se convierte en un artefacto para el motor, y
    por eso **no deserializa nada**: lee el parquet que la ingesta ya produjo con pandas. Un archivo
    que no sea una tabla nunca llegó a materializarse (:func:`ingest_upload` lo habría rechazado en
    su lector), así que aquí no hay ningún ``loads`` de objeto que proteger (D-PUE-1).

    Parameters
    ----------
    dataset_id : str
        Identificador del dataset subido (o del catálogo) ya materializado.
    workdir : Path
        Directorio de trabajo donde vive el parquet.
    key_column : str | None
        Columna que identifica cada fila; pasa a ser el índice. Con ``None`` el frame conserva su
        índice posicional y la alineación queda por **orden de filas** (D-PUE-6), que es una
        decisión del usuario y no un default silencioso: quien la toma recibe su aviso y su caveat.

    Raises
    ------
    UiDatasetError
        Si el dataset no existe.
    UiArtifactError
        Si ``key_column`` no es una columna del archivo.

    Notes
    -----
    ⚠️ Las dos excepciones son **hermanas** bajo ``UiError`` y se eligen por lo que significan, no
    por su orden en un ``except``: un dataset ausente es «eso no existe» (404) y una llave que el
    archivo no trae es entrada del usuario, corregible desde la pantalla (422). Hasta el 2026-08-02
    las dos salían como ``UiDatasetError`` y una llave mal escrita respondía 404, que le dice al
    usuario algo falso sobre su propio archivo.
    """
    source = materialize(dataset_id, workdir=workdir)
    frame = pd.read_parquet(source)
    if key_column is None:
        return frame
    if key_column not in frame.columns:
        raise UiArtifactError(
            f"el archivo '{dataset_id}' no tiene la columna '{key_column}' que declaraste como "
            f"identificador; columnas disponibles: {[str(c) for c in frame.columns]}."
        )
    return frame.set_index(key_column)


def _dataset_path(workdir: Path, dataset_id: str) -> Path:
    """Resuelve la ruta del parquet y verifica que quede dentro de ``workdir/datasets``."""
    return _validated_dataset_path(workdir, dataset_id, uploaded=False)


def _upload_path(workdir: Path, dataset_id: str) -> Path:
    """Resuelve la ruta del parquet de un upload (análogo a :func:`_dataset_path`, misma defensa).

    El ``dataset_id`` es hex puro con prefijo (``uploaded_<token>``), seguro por construcción; la
    verificación de que la ruta quede bajo ``workdir/datasets`` es defensa en profundidad.
    """
    return _validated_dataset_path(workdir, dataset_id, uploaded=True)


def _validated_dataset_path(workdir: Path, dataset_id: str, *, uploaded: bool) -> Path:
    """Valida contención real, incluidos symlinks, y conserva la representación relativa."""
    raw_datasets_dir = workdir / "datasets"
    resolved_workdir = workdir.resolve()
    resolved_datasets_dir = raw_datasets_dir.resolve()
    if resolved_workdir not in resolved_datasets_dir.parents:
        qualifier = " subido" if uploaded else ""
        raise UiDatasetError(
            f"el directorio del dataset{qualifier} '{dataset_id}' escaparía del workdir."
        )

    raw_candidate = raw_datasets_dir / f"{dataset_id}.parquet"
    resolved_candidate = raw_candidate.resolve()
    if resolved_datasets_dir not in resolved_candidate.parents:
        qualifier = " subido" if uploaded else ""
        raise UiDatasetError(
            f"la ruta del dataset{qualifier} '{dataset_id}' escaparía del workdir."
        )
    return resolved_candidate if workdir.is_absolute() else raw_candidate


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
