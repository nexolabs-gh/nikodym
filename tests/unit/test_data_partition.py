"""Tests de ``Partitioner`` (SDD-02 §4/§7): particiones, TTD y determinismo."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pandas.testing import assert_frame_equal, assert_series_equal

from nikodym.core.audit import InMemoryAuditSink
from nikodym.core.exceptions import ConfigError, DataValidationError
from nikodym.data.config import (
    CohortSplitConfig,
    PartitionConfig,
    RandomSplitConfig,
    TemporalSplitConfig,
)
from nikodym.data.partition import (
    Partition,
    Partitioner,
    PartitionResult,
    _stable_uniform,
    _validate_temporal_precedence,
)
from nikodym.data.target import LabeledFrame, TargetSummary

settings.register_profile(
    "nikodym_deterministic",
    derandomize=True,
    deadline=None,
    max_examples=25,
)
settings.load_profile("nikodym_deterministic")

ROOT_SEED = 20_240_624


def _labeled(df: pd.DataFrame) -> LabeledFrame:
    return LabeledFrame(
        frame=df,
        target_col="target",
        status_col="label_status",
        summary=TargetSummary(
            class_counts={},
            bad_rate=0.0,
            exclusions_by_reason={},
            ambiguous_rows=0,
        ),
    )


def _base_frame() -> pd.DataFrame:
    index = pd.Index([f"op-{i:02d}" for i in range(12)], name="loan_id")
    targets = pd.Series(
        [1, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0, 0],
        index=index,
        dtype="Int8",
    )
    status = pd.Categorical(
        ["malo" if value == 1 else "bueno" for value in targets],
        categories=["bueno", "malo", "indeterminado", "excluido"],
    )
    return pd.DataFrame({"target": targets, "label_status": status}, index=index)


def _rng() -> np.random.Generator:
    return np.random.default_rng(7)


def _split(cfg: PartitionConfig, df: pd.DataFrame | None = None) -> PartitionResult:
    frame = _base_frame() if df is None else df
    return Partitioner(cfg).split(_labeled(frame), root_seed=ROOT_SEED, rng=_rng())


def _random_config(**kwargs: object) -> PartitionConfig:
    return PartitionConfig(
        strategy=RandomSplitConfig(**kwargs),  # type: ignore[arg-type]
        min_bads_per_partition=0,
    )


def test_from_config_conserva_partition_config() -> None:
    cfg = _random_config(dev_fraction=0.5, holdout_fraction=0.25, oot_fraction=0.25)

    partitioner = Partitioner.from_config(cfg)

    assert partitioner.config is cfg


def test_random_split_golden_auditoria_y_no_muta_df() -> None:
    df = _base_frame()
    original = df.copy(deep=True)
    cfg = _random_config(dev_fraction=0.5, holdout_fraction=0.25, oot_fraction=0.25)
    audit = InMemoryAuditSink()

    result = Partitioner(cfg).split(_labeled(df), root_seed=ROOT_SEED, rng=_rng(), audit=audit)

    assert isinstance(result, PartitionResult)
    assert result.strategy_used == "random"
    assert result.frame["partition"].astype(str).to_dict() == {
        "op-00": "oot",
        "op-01": "holdout",
        "op-02": "desarrollo",
        "op-03": "oot",
        "op-04": "desarrollo",
        "op-05": "desarrollo",
        "op-06": "oot",
        "op-07": "desarrollo",
        "op-08": "holdout",
        "op-09": "desarrollo",
        "op-10": "desarrollo",
        "op-11": "desarrollo",
    }
    assert str(result.frame["partition"].dtype) == "category"
    assert result.frame["ttd"].tolist() == [True] * 12
    assert result.sizes == {
        "desarrollo": 7,
        "holdout": 2,
        "oot": 3,
        "fuera_de_modelo": 0,
    }
    assert result.bad_rates == {
        "desarrollo": pytest.approx(1 / 7),
        "holdout": 0.0,
        "oot": 1.0,
        "fuera_de_modelo": 0.0,
    }
    assert [event.payload for event in audit.events] == [
        {
            "regla": "partition_strategy",
            "umbral": "random",
            "valor": "random",
            "accion": "aplicar_estrategia",
        },
        {
            "regla": "partition_summary",
            "umbral": "sizes_bad_rates",
            "valor": {"sizes": result.sizes, "bad_rates": result.bad_rates},
            "accion": "reportar_particiones",
        },
    ]
    assert_frame_equal(df, original)


def test_temporal_split_golden_con_precedencia() -> None:
    df = _base_frame()
    df["fecha"] = pd.to_datetime(
        [
            "2024-01-01",
            "2024-01-02",
            "2024-01-03",
            "2024-01-04",
            "2024-01-05",
            "2024-01-06",
            "2024-02-01",
            "2024-02-02",
            "2024-02-03",
            "2024-02-04",
            "2024-02-05",
            "2024-02-06",
        ]
    )
    cfg = PartitionConfig(
        strategy=TemporalSplitConfig(date_col="fecha", oot_from="2024-02-01", holdout_fraction=0.5),
        min_bads_per_partition=0,
    )

    result = _split(cfg, df)

    assert result.frame["partition"].astype(str).to_dict() == {
        "op-00": "desarrollo",
        "op-01": "desarrollo",
        "op-02": "holdout",
        "op-03": "desarrollo",
        "op-04": "holdout",
        "op-05": "holdout",
        "op-06": "oot",
        "op-07": "oot",
        "op-08": "oot",
        "op-09": "oot",
        "op-10": "oot",
        "op-11": "oot",
    }
    assert result.sizes == {
        "desarrollo": 3,
        "holdout": 3,
        "oot": 6,
        "fuera_de_modelo": 0,
    }
    in_time = result.frame["partition"].isin([Partition.DESARROLLO.value, Partition.HOLDOUT.value])
    oot = result.frame["partition"].eq(Partition.OOT.value)
    assert result.frame.loc[in_time, "fecha"].max() < result.frame.loc[oot, "fecha"].min()


def test_cohort_split_golden() -> None:
    df = _base_frame()
    df["vintage"] = [
        "2023Q1",
        "2023Q1",
        "2023Q2",
        "2023Q2",
        "2023Q3",
        "2023Q3",
        "2024Q1",
        "2024Q1",
        "2024Q2",
        "2024Q2",
        "2024Q2",
        "2024Q2",
    ]
    cfg = PartitionConfig(
        strategy=CohortSplitConfig(
            cohort_col="vintage",
            oot_cohorts=("2024Q2",),
            holdout_fraction=0.5,
        ),
        min_bads_per_partition=0,
    )

    result = _split(cfg, df)

    assert result.frame["partition"].astype(str).to_dict() == {
        "op-00": "desarrollo",
        "op-01": "desarrollo",
        "op-02": "holdout",
        "op-03": "desarrollo",
        "op-04": "holdout",
        "op-05": "holdout",
        "op-06": "desarrollo",
        "op-07": "holdout",
        "op-08": "oot",
        "op-09": "oot",
        "op-10": "oot",
        "op-11": "oot",
    }
    assert result.sizes == {
        "desarrollo": 4,
        "holdout": 4,
        "oot": 4,
        "fuera_de_modelo": 0,
    }
    assert result.bad_rates["oot"] == pytest.approx(0.25)


def test_fuera_de_modelo_por_status_o_target_na_y_ttd_configurable() -> None:
    index = pd.Index(["dev", "oot", "indet", "excl", "target_na"], name="loan_id")
    df = pd.DataFrame(
        {
            "target": pd.Series([0, 1, pd.NA, pd.NA, pd.NA], index=index, dtype="Int8"),
            "label_status": pd.Categorical(
                ["bueno", "malo", "indeterminado", "excluido", "bueno"],
                categories=["bueno", "malo", "indeterminado", "excluido"],
            ),
            "fecha": pd.to_datetime(
                ["2024-01-01", "2024-02-01", "2024-01-05", "2024-02-05", "2024-01-10"]
            ),
        },
        index=index,
    )
    cfg = PartitionConfig(
        strategy=TemporalSplitConfig(date_col="fecha", oot_from="2024-02-01", holdout_fraction=0.0),
        ttd_includes_excluded=False,
        min_bads_per_partition=0,
    )
    audit = InMemoryAuditSink()

    result = Partitioner(cfg).split(_labeled(df), root_seed=ROOT_SEED, rng=_rng(), audit=audit)

    assert result.frame["partition"].astype(str).to_dict() == {
        "dev": "desarrollo",
        "oot": "oot",
        "indet": "fuera_de_modelo",
        "excl": "fuera_de_modelo",
        "target_na": "fuera_de_modelo",
    }
    assert result.frame["ttd"].tolist() == [True, True, False, False, False]
    assert result.sizes["fuera_de_modelo"] == 3
    assert [event.payload["regla"] for event in audit.events] == [
        "partition_strategy",
        "fuera_de_modelo",
        "partition_summary",
    ]


def test_random_stratified_es_estable_al_insertar_filas() -> None:
    df = _base_frame()
    cfg = _random_config(
        dev_fraction=0.5,
        holdout_fraction=0.25,
        oot_fraction=0.25,
        stratify_by="target",
    )
    base = _split(cfg, df).frame["partition"].copy()
    extra_index = pd.Index(["op-99", "op-98"], name="loan_id")
    extra = pd.DataFrame(
        {
            "target": pd.Series([1, 0], index=extra_index, dtype="Int8"),
            "label_status": pd.Categorical(
                ["malo", "bueno"],
                categories=["bueno", "malo", "indeterminado", "excluido"],
            ),
        },
        index=extra_index,
    )
    ampliado = pd.concat([df, extra])

    after_insert = _split(cfg, ampliado).frame.loc[df.index, "partition"]

    assert_series_equal(base, after_insert)


def test_random_holdout_cero_no_exige_particion_ni_piso_de_malos() -> None:
    cfg = PartitionConfig(
        strategy=RandomSplitConfig(dev_fraction=0.5, holdout_fraction=0.0, oot_fraction=0.5),
        min_bads_per_partition=1,
    )

    result = _split(cfg)

    assert result.sizes["holdout"] == 0
    assert set(result.frame["partition"].astype(str)) == {"desarrollo", "oot"}


def test_cohort_holdout_cero_no_exige_holdout() -> None:
    df = _base_frame()
    df["vintage"] = ["A"] * 6 + ["B"] * 6
    cfg = PartitionConfig(
        strategy=CohortSplitConfig(cohort_col="vintage", oot_cohorts=("B",), holdout_fraction=0.0),
        min_bads_per_partition=0,
    )

    result = _split(cfg, df)

    assert result.sizes["holdout"] == 0
    assert result.sizes["desarrollo"] == 6
    assert result.sizes["oot"] == 6


def test_temporal_holdout_cero_no_exige_holdout() -> None:
    df = _base_frame()
    df["fecha"] = pd.date_range("2024-01-01", periods=12, freq="D")
    cfg = PartitionConfig(
        strategy=TemporalSplitConfig(date_col="fecha", oot_from="2024-01-07", holdout_fraction=0.0),
        min_bads_per_partition=0,
    )

    result = _split(cfg, df)

    assert result.sizes["holdout"] == 0
    assert result.sizes["desarrollo"] == 6
    assert result.sizes["oot"] == 6


def test_suggest_prioriza_fecha_luego_cohorte_luego_random() -> None:
    current = PartitionConfig(
        strategy=RandomSplitConfig(),
        ttd_includes_excluded=False,
        min_bads_per_partition=3,
    )
    partitioner = Partitioner(current)
    con_fecha = _base_frame()
    con_fecha["fecha_obs"] = pd.date_range("2024-01-01", periods=12, freq="D")
    con_cohorte = _base_frame()
    con_cohorte["fecha_constante"] = pd.Timestamp("2024-01-01")
    con_cohorte["vintage"] = ["2023Q1", "2023Q2", "2024Q1", "2024Q2"] * 3

    sugerida_fecha = partitioner.suggest(_labeled(con_fecha))
    sugerida_cohorte = partitioner.suggest(_labeled(con_cohorte))
    sugerida_random = partitioner.suggest(_labeled(_base_frame()))

    assert isinstance(sugerida_fecha.strategy, TemporalSplitConfig)
    assert sugerida_fecha.strategy.date_col == "fecha_obs"
    assert sugerida_fecha.ttd_includes_excluded is False
    assert sugerida_fecha.min_bads_per_partition == 3
    assert isinstance(sugerida_cohorte.strategy, CohortSplitConfig)
    assert sugerida_cohorte.strategy.oot_cohorts == ("2024Q1", "2024Q2")
    assert isinstance(sugerida_random.strategy, RandomSplitConfig)
    assert sugerida_random.strategy.stratify_by == "target"


def test_temporal_soporta_cutoffs_con_y_sin_timezone() -> None:
    index = pd.Index(["a", "b", "c", "d"], name="loan_id")
    base = pd.DataFrame(
        {
            "target": pd.Series([0, 1, 0, 1], index=index, dtype="Int8"),
            "label_status": pd.Categorical(
                ["bueno", "malo", "bueno", "malo"],
                categories=["bueno", "malo", "indeterminado", "excluido"],
            ),
        },
        index=index,
    )
    aware = base.assign(
        fecha=pd.date_range("2024-01-01", periods=4, freq="D", tz="America/Santiago")
    )
    naive = base.assign(fecha=pd.date_range("2024-01-01", periods=4, freq="D"))

    aware_result = _split(
        PartitionConfig(
            strategy=TemporalSplitConfig(
                date_col="fecha",
                oot_from="2024-01-03",
                holdout_fraction=0.0,
            ),
            min_bads_per_partition=0,
        ),
        aware,
    )
    naive_result = _split(
        PartitionConfig(
            strategy=TemporalSplitConfig(
                date_col="fecha",
                oot_from="2024-01-03T00:00:00+00:00",
                holdout_fraction=0.0,
            ),
            min_bads_per_partition=0,
        ),
        naive,
    )

    assert aware_result.sizes["oot"] == 2
    assert naive_result.sizes["oot"] == 2


def test_colisiones_de_columnas_de_salida_levantan_datavalidationerror() -> None:
    df = _base_frame().assign(partition="cliente")
    cfg = _random_config(dev_fraction=0.5, holdout_fraction=0.25, oot_fraction=0.25)

    with pytest.raises(DataValidationError, match="sobrescribir"):
        _split(cfg, df)


def test_labeledframe_sin_columnas_requeridas_levanta_datavalidationerror() -> None:
    lf = LabeledFrame(
        frame=pd.DataFrame({"x": [1]}),
        target_col="target",
        status_col="label_status",
        summary=TargetSummary(
            class_counts={}, bad_rate=0.0, exclusions_by_reason={}, ambiguous_rows=0
        ),
    )
    cfg = _random_config(dev_fraction=0.5, holdout_fraction=0.25, oot_fraction=0.25)

    with pytest.raises(DataValidationError, match="columna\\(s\\) requeridas"):
        Partitioner(cfg).split(lf, root_seed=ROOT_SEED, rng=_rng())


def test_label_status_invalido_levanta_datavalidationerror() -> None:
    df = _base_frame()
    df["label_status"] = ["gris"] * len(df)
    cfg = _random_config(dev_fraction=0.5, holdout_fraction=0.25, oot_fraction=0.25)

    with pytest.raises(DataValidationError, match="fuera del contrato"):
        _split(cfg, df)


def test_factory_local_tipo_desconocido_levanta_configerror() -> None:
    class UnknownStrategy:
        type = "fantasma"

    cfg = PartitionConfig.model_construct(
        strategy=UnknownStrategy(),
        ttd_includes_excluded=True,
        min_bads_per_partition=0,
    )

    with pytest.raises(ConfigError, match="factory local"):
        Partitioner(cfg).split(_labeled(_base_frame()), root_seed=ROOT_SEED, rng=_rng())


def test_temporal_columna_inexistente_o_no_datetime_levanta_datavalidationerror() -> None:
    cfg_missing = PartitionConfig(
        strategy=TemporalSplitConfig(date_col="fecha", oot_from="2024-01-01"),
        min_bads_per_partition=0,
    )
    df_no_datetime = _base_frame().assign(fecha=["2024-01-01"] * 12)
    cfg_no_datetime = PartitionConfig(
        strategy=TemporalSplitConfig(date_col="fecha", oot_from="2024-01-01"),
        min_bads_per_partition=0,
    )

    with pytest.raises(DataValidationError, match="columna inexistente"):
        _split(cfg_missing)
    with pytest.raises(DataValidationError, match="requiere una columna datetime"):
        _split(cfg_no_datetime, df_no_datetime)


def test_temporal_oot_from_invalido_o_fecha_nula_levanta_error() -> None:
    df = _base_frame()
    df["fecha"] = pd.date_range("2024-01-01", periods=12, freq="D")
    cfg_bad_date = PartitionConfig(
        strategy=TemporalSplitConfig(date_col="fecha", oot_from="no-es-fecha"),
        min_bads_per_partition=0,
    )
    df_null = df.copy(deep=True)
    df_null.loc["op-00", "fecha"] = pd.NaT
    cfg_null = PartitionConfig(
        strategy=TemporalSplitConfig(date_col="fecha", oot_from="2024-01-07"),
        min_bads_per_partition=0,
    )

    with pytest.raises(ConfigError, match="oot_from inválido"):
        _split(cfg_bad_date, df)
    with pytest.raises(DataValidationError, match="fechas no nulas"):
        _split(cfg_null, df_null)


def test_particion_vacia_levanta_datavalidationerror() -> None:
    df = _base_frame().assign(fecha=pd.date_range("2024-01-01", periods=12, freq="D"))
    cfg = PartitionConfig(
        strategy=TemporalSplitConfig(date_col="fecha", oot_from="2025-01-01", holdout_fraction=0.0),
        min_bads_per_partition=0,
    )

    with pytest.raises(DataValidationError, match="partición\\(es\\) vacía"):
        _split(cfg, df)


def test_random_stratify_columna_inexistente_levanta_datavalidationerror() -> None:
    cfg = _random_config(
        dev_fraction=0.5,
        holdout_fraction=0.25,
        oot_fraction=0.25,
        stratify_by="segmento",
    )

    with pytest.raises(DataValidationError, match="stratify_by"):
        _split(cfg)


def test_cohort_columna_inexistente_u_oot_vacio_levanta_datavalidationerror() -> None:
    cfg_missing = PartitionConfig(
        strategy=CohortSplitConfig(cohort_col="vintage", oot_cohorts=("2024Q1",)),
        min_bads_per_partition=0,
    )
    df = _base_frame().assign(vintage=["2023Q1"] * 12)
    cfg_empty_oot = PartitionConfig(
        strategy=CohortSplitConfig(cohort_col="vintage", oot_cohorts=("2024Q1",)),
        min_bads_per_partition=0,
    )

    with pytest.raises(DataValidationError, match="columna inexistente"):
        _split(cfg_missing)
    with pytest.raises(DataValidationError, match="partición\\(es\\) vacía"):
        _split(cfg_empty_oot, df)


def test_min_bads_per_partition_violado_levanta_datavalidationerror() -> None:
    df = _base_frame()
    df["fecha"] = pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03", "2024-02-01"] * 3)
    cfg = PartitionConfig(
        strategy=TemporalSplitConfig(date_col="fecha", oot_from="2024-02-01", holdout_fraction=0.5),
        min_bads_per_partition=2,
    )

    with pytest.raises(DataValidationError, match="Piso de malos"):
        _split(cfg, df)


def test_modelable_vacio_levanta_particion_vacia() -> None:
    index = pd.Index(["a", "b"], name="loan_id")
    df = pd.DataFrame(
        {
            "target": pd.Series([pd.NA, pd.NA], index=index, dtype="Int8"),
            "label_status": pd.Categorical(
                ["indeterminado", "excluido"],
                categories=["bueno", "malo", "indeterminado", "excluido"],
            ),
        },
        index=index,
    )
    cfg = _random_config(dev_fraction=0.5, holdout_fraction=0.25, oot_fraction=0.25)

    with pytest.raises(DataValidationError, match="partición\\(es\\) vacía"):
        _split(cfg, df)


def test_validacion_temporal_detecta_precedencia_rota() -> None:
    dates = pd.Series(pd.to_datetime(["2024-02-01", "2024-01-01"]), index=["dev", "oot"])
    assignments = pd.Series(["desarrollo", "oot"], index=dates.index)

    with pytest.raises(DataValidationError, match="preceder al OOT"):
        _validate_temporal_precedence(dates, assignments)


def test_hash_estable_normaliza_menos_cero_y_soporta_tuplas_timestamp() -> None:
    assert _stable_uniform(ROOT_SEED, -0.0) == _stable_uniform(ROOT_SEED, 0.0)
    assert 0.0 <= _stable_uniform(ROOT_SEED, ("a", pd.Timestamp("2024-01-01"))) < 1.0
    assert _stable_uniform(ROOT_SEED, 1.5) != _stable_uniform(ROOT_SEED, 2.5)


def _property_frame(n_rows: int) -> pd.DataFrame:
    index = pd.Index([f"id-{i:03d}" for i in range(n_rows)], name="loan_id")
    targets = pd.Series([i % 2 for i in range(n_rows)], index=index, dtype="Int8")
    status = pd.Categorical(
        ["malo" if value == 1 else "bueno" for value in targets],
        categories=["bueno", "malo", "indeterminado", "excluido"],
    )
    return pd.DataFrame({"target": targets, "label_status": status}, index=index)


@given(n_rows=st.integers(min_value=12, max_value=60))
def test_property_random_determinismo_e_invariancia_a_permutacion(n_rows: int) -> None:
    df = _property_frame(n_rows)
    cfg = _random_config(
        dev_fraction=0.34,
        holdout_fraction=0.33,
        oot_fraction=0.33,
        stratify_by="target",
    )
    shuffled = df.sample(frac=1.0, random_state=13)

    first = _split(cfg, df).frame["partition"].sort_index()
    second = _split(cfg, shuffled).frame["partition"].sort_index()

    assert_series_equal(first, second)


@given(n_rows=st.integers(min_value=12, max_value=60))
def test_property_temporal_anti_leakage_y_exhaustividad(n_rows: int) -> None:
    df = _property_frame(n_rows)
    df["fecha"] = pd.date_range("2024-01-01", periods=n_rows, freq="D")
    cutoff = df["fecha"].iloc[n_rows // 2].date().isoformat()
    cfg = PartitionConfig(
        strategy=TemporalSplitConfig(date_col="fecha", oot_from=cutoff, holdout_fraction=0.0),
        min_bads_per_partition=0,
    )

    result = _split(cfg, df)
    frame = result.frame
    partitions = frame["partition"]
    in_time = partitions.isin([Partition.DESARROLLO.value, Partition.HOLDOUT.value])
    oot = partitions.eq(Partition.OOT.value)

    assert partitions.notna().all()
    assert sum(result.sizes.values()) == len(frame)
    assert frame.loc[in_time, "fecha"].max() < frame.loc[oot, "fecha"].min()
    assert frame["ttd"].all()


@given(n_rows=st.integers(min_value=12, max_value=60))
def test_property_estabilidad_por_observacion_al_insertar_filas(n_rows: int) -> None:
    df = _property_frame(n_rows)
    cfg = _random_config(dev_fraction=0.34, holdout_fraction=0.33, oot_fraction=0.33)
    base = _split(cfg, df).frame["partition"].copy()
    extra_index = pd.Index([f"extra-{i}" for i in range(10)], name="loan_id")
    extra_targets = pd.Series([i % 2 for i in range(10)], index=extra_index, dtype="Int8")
    extra = pd.DataFrame(
        {
            "target": extra_targets,
            "label_status": pd.Categorical(
                ["malo" if value == 1 else "bueno" for value in extra_targets],
                categories=["bueno", "malo", "indeterminado", "excluido"],
            ),
        },
        index=extra_index,
    )

    expanded = pd.concat([extra, df])
    after_insert = _split(cfg, expanded).frame.loc[df.index, "partition"]

    assert_series_equal(base, after_insert)
