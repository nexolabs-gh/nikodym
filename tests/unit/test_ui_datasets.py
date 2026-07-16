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
        "provisiones_consumo",
        "ifrs9_retail_latam",
    ]

    for descriptor in primero:
        assert set(descriptor) == {"id", "name", "description", "columns", "n_rows"}
        roles = {col["role"] for col in descriptor["columns"]}
        assert roles >= _ROLES_ESPERADOS  # target/feature/segment/cohort/id presentes
        # exactamente un target, un segment y un cohort (consistente con la partición F1).
        assert sum(col["role"] == "target" for col in descriptor["columns"]) == 1
        assert sum(col["role"] == "segment" for col in descriptor["columns"]) == 1
        assert sum(col["role"] == "cohort" for col in descriptor["columns"]) == 1


def test_provisiones_consumo_es_una_cartera_creible() -> None:
    """El dataset de provisiones cumple los invariantes que lo hacen creíble (SDD-28 §6.3).

    No es un test de "el motor no explota": es un test de **verosimilitud**. Un gerente de riesgo
    detecta un dato imposible en segundos, y a partir de ahí no vuelve a creer ninguna cifra de la
    pantalla. Cada aserción de aquí corresponde a algo que un experto miraría.
    """
    frame = datasets._generate("provisiones_consumo")

    # --- Magnitudes: la cartera se parece a una cartera de consumo chilena ---
    tasa_default = frame["bad_flag"].mean()
    assert 0.04 <= tasa_default <= 0.10, (
        f"tasa de default {tasa_default:.1%}: fuera del rango de una cartera de consumo real "
        "(la cartera F1 tiene un 23 %, que es inverosímil)"
    )
    al_dia = (frame["days_past_due"] == 0).mean()
    assert 0.70 <= al_dia <= 0.90, f"{al_dia:.0%} al día: una cartera viva no se ve así"
    incumplidas = (frame["days_past_due"] >= 90).mean()
    assert 0.01 <= incumplidas <= 0.05, (
        f"{incumplidas:.1%} en incumplimiento: ahí está la plata (PI del 100 %), tiene que existir"
    )

    # --- Cap. B-2: la mora se castiga; una cartera viva no arrastra 500 días de mora ---
    assert frame["days_past_due"].max() <= 180

    # --- Coherencia interna: lo que un revisor cruza ---
    assert (frame["mora_max_12m"] >= frame["days_past_due"]).all(), (
        "la mora máxima de 12 meses no puede ser menor que la mora de hoy"
    )

    # --- SIN FUGA: `bad_flag` mira al futuro; `days_past_due` es el estado de hoy. Si fueran
    # deterministas el uno del otro, el scorecard predeciría el presente (KS absurdo = fraude). ---
    malos_al_dia = frame.loc[frame["bad_flag"] == 1, "days_past_due"].eq(0).mean()
    assert 0.15 <= malos_al_dia <= 0.85, (
        f"solo el {malos_al_dia:.0%} de los futuros malos está hoy al día: hay fuga de información"
    )

    # --- Los flags de sistema son POR DEUDOR (el motor CMF hace any() sobre el deudor) ---
    por_deudor = frame.groupby("debtor_id")
    assert por_deudor["has_housing_loan_system"].nunique().eq(1).all()
    assert por_deudor["system_dpd30_last_3m"].nunique().eq(1).all()

    # --- La consolidación por deudor del B-1 tiene que poder ejercitarse ---
    con_varias = (por_deudor.size() > 1).mean()
    assert 0.20 <= con_varias <= 0.45, (
        f"{con_varias:.0%} de deudores con >1 operación: sin esto la consolidación del B-1 "
        "—la regla central de la norma en consumo— nunca se ejercita"
    )

    # --- LGD: distribuida, nunca constante (una LGD plana delata al dato sintético) ---
    assert frame["lgd"].between(0.0, 1.0).all()
    assert frame["lgd"].std() > 0.05
    # y por debajo de la PDI normativa del producto (la PDI regulatoria es más conservadora)
    lgd_media = frame.groupby("cmf_product_type")["lgd"].mean()
    assert lgd_media["leasing_auto"] < 0.332
    assert lgd_media["creditos_en_cuotas"] < 0.566
    assert lgd_media["tarjetas_lineas_otros"] < 0.603

    # --- Los buckets de la matriz de PI tienen masa (si no, la matriz no se ejercita) ---
    bordes = [(0, 1), (1, 8), (8, 31), (31, 61), (61, 90), (90, 181)]
    for bajo, alto in bordes:
        masa = ((frame["days_past_due"] >= bajo) & (frame["days_past_due"] < alto)).mean()
        assert masa > 0.005, f"bucket de mora [{bajo},{alto}) casi vacío: la matriz no se ejercita"

    # --- El motor CMF exige UNA sola fecha de cálculo ---
    assert frame["as_of_date"].nunique() == 1

    # --- Columnas-mina: el motor CMF las olfatea por nombre y abortaría la corrida ---
    prohibidas = {"guarantee_type", "financial_guarantee_amount", "aval_coverage_pct"}
    assert not (prohibidas & set(frame.columns))
    # y `cmf_category` NO va: en consumo el motor la deriva, no la lee (SDD-28 §6.2)
    assert "cmf_category" not in frame.columns


def test_provisiones_consumo_determinista() -> None:
    """Dos generaciones producen exactamente la misma cartera (seed constante)."""
    assert datasets._generate("provisiones_consumo").equals(
        datasets._generate("provisiones_consumo")
    )


def test_ifrs9_retail_latam_es_creible() -> None:
    """El dataset IFRS 9 cumple los invariantes que lo hacen creíble y usable por el motor (SDD-16).

    Verifica la verosimilitud de los inputs económicos y de survival que un revisor cruzaría, y que
    el staging por mora tendrá un split VISIBLE (30+ d y 90+ d con masa), sin país ni moneda.
    """
    frame = datasets._generate("ifrs9_retail_latam")

    # --- Columnas: superconjunto de F1 + survival + económicas IFRS 9; sin nulos ---
    esperadas = {
        "duration",
        "event",
        "as_of_date",
        "portfolio",
        "ead",
        "lgd",
        "eir",
        "days_past_due",
        "is_default",
    }
    assert esperadas <= set(frame.columns)
    assert not frame.isna().any().any()

    # --- Una sola fecha de cálculo (el motor IFRS 9 lo exige) ---
    assert frame["as_of_date"].nunique() == 1

    # --- Carteras genéricas LatAm (sin país ni institución) ---
    assert set(frame["portfolio"]) == {"Consumo", "Tarjetas", "Comercial", "Hipotecario"}

    # --- Magnitudes económicas de escala retail (sin moneda), plausibles ---
    assert frame["ead"].between(2000.0, 80000.0).all()
    assert frame["lgd"].between(0.0, 1.0).all() and frame["lgd"].std() > 0.05
    assert frame["eir"].between(0.03, 0.60).all()
    # LGD/EIR menores con garantía (hipotecario) que en retail sin garantía (tarjetas).
    lgd_media = frame.groupby("portfolio")["lgd"].mean()
    assert lgd_media["Hipotecario"] < lgd_media["Tarjetas"]
    eir_media = frame.groupby("portfolio")["eir"].mean()
    assert eir_media["Hipotecario"] < eir_media["Tarjetas"]

    # --- Mora: split de staging VISIBLE (algunos 30+ d → Stage 2, algunos 90+ d → Stage 3) ---
    assert frame["days_past_due"].between(0, 180).all()
    assert (frame["days_past_due"] == 0).mean() >= 0.70  # cartera mayormente al día
    assert 0.03 <= (frame["days_past_due"] >= 30).mean() <= 0.25  # Stage 2+ con masa
    assert 0.01 <= (frame["days_past_due"] >= 90).mean() <= 0.10  # Stage 3 con masa
    assert (frame["mora_max_12m"] >= frame["days_past_due"]).all()  # coherencia con la feature F1

    # --- is_default cubre los 90+ d, más una fracción reestructurada con mora <90 d ---
    assert frame.loc[frame["days_past_due"] >= 90, "is_default"].all()
    assert bool(frame.loc[frame["days_past_due"] < 90, "is_default"].any())

    # --- Survival: duración en años ∈ [1, horizonte], evento binario, censura al horizonte ---
    horizonte = datasets._DATASETS["ifrs9_retail_latam"]["horizon_years"]
    assert frame["duration"].between(1, horizonte).all()
    assert set(int(value) for value in frame["event"].unique()) <= {0, 1}
    assert 0.05 <= frame["event"].mean() <= 0.45  # cumulativa de default plausible a T años
    # quien no registra evento se observó el horizonte completo (censura a T).
    assert (frame.loc[frame["event"] == 0, "duration"] == horizonte).all()


def test_ifrs9_retail_latam_determinista() -> None:
    """Dos generaciones producen exactamente la misma cartera (seed constante)."""
    assert datasets._generate("ifrs9_retail_latam").equals(datasets._generate("ifrs9_retail_latam"))


def test_provisiones_consumo_alimenta_el_motor_cmf_real() -> None:
    """GATE G1: el dataset alimenta el motor estándar CMF **real**, sin adaptadores.

    Una lista de columnas verificada leyendo el código es una **hipótesis**; solo la ejecución la
    convierte en contrato. Este test es el que congela el esquema del dataset: si el motor pide una
    columna que no está —o rechaza una que sobra— falla aquí, no en la demo delante de un gerente.

    Verifica además que la cartera **ejercita la norma**: que la matriz de PI de consumo se aplique
    de verdad (la PE de un deudor al día sin hipotecario debe ser PI 6,6 % x PDI 56,6 % = 3,74 %) y
    que exista cartera en incumplimiento, que es donde la PI es del 100 % y donde está la plata.
    """
    from nikodym.provisioning.cmf import CmfProvisioningConfig
    from nikodym.provisioning.cmf.engine import CmfProvisioningEngine

    frame = datasets._generate("provisiones_consumo")
    resultado = CmfProvisioningEngine.from_config(CmfProvisioningConfig()).calculate(
        frame, as_of_date="2024-06-30"
    )

    tarjeta = resultado.card
    assert tarjeta.n_rows == len(frame)
    assert tarjeta.total_provision_amount > 0
    assert tarjeta.matrix_version == "cmf_b1_b3_2025_01"

    # La categoría de consumo la DERIVA el motor (bucket de mora | hipotecario | mora sistema):
    # no es un input. Si alguien mete `cmf_category` al dataset, este assert lo delata.
    categorias = set(resultado.summary["cmf_category"])
    assert any(c.startswith("incumplimiento") for c in categorias), (
        "sin cartera en incumplimiento, la PI del 100 % nunca se ejercita"
    )
    assert any(c.startswith("0_7") for c in categorias)

    # El índice de riesgo resultante. Rango AMPLIO y deliberado: el benchmark desagregado de consumo
    # de la CMF no está verificado (ver el aviso en `_generate_provisiones`). Este test protege
    # contra una regresión gruesa (un dataset que provisione 0,1 % o 40 %), NO certifica que la
    # cartera esté calibrada contra el sistema chileno.
    indice_riesgo = float(tarjeta.total_provision_amount) / float(tarjeta.total_exposure_amount)
    assert 0.04 <= indice_riesgo <= 0.14, f"índice de riesgo {indice_riesgo:.2%} fuera de rango"


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
