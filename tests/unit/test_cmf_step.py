"""Tests de ``CmfProvisioningStep``: CT-1, prerequisitos condicionales e import liviano."""

from __future__ import annotations

import subprocess
import sys
import textwrap
import warnings
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

import nikodym.core.study as study_module
import nikodym.provisioning.cmf as cmf_pkg
import nikodym.provisioning.cmf.step as step_module
from nikodym.core.audit import AuditEvent, InMemoryAuditSink
from nikodym.core.config import NikodymConfig
from nikodym.core.exceptions import ArtifactNotFoundError, MissingDependencyError
from nikodym.core.registry import REGISTRY
from nikodym.core.study import Study
from nikodym.provisioning.cmf.config import CmfPdMappingConfig, CmfProvisioningConfig
from nikodym.provisioning.cmf.exceptions import CmfConfigError, CmfInputError
from nikodym.provisioning.cmf.results import CmfProvisionCard, CmfProvisionResult
from nikodym.provisioning.cmf.step import CMF_PROVISIONING_ARTIFACTS, CmfProvisioningStep

ROOT_SEED = 20_240_629
EXPECTED_A1_PROVISION = Decimal("360.00000")
EXPECTED_B4_PROVISION = Decimal("438750.00000")


def _config(**kwargs: Any) -> CmfProvisioningConfig:
    """Config base de CMF para fixtures sintéticos."""
    return CmfProvisioningConfig(**kwargs)


def _standalone_frame() -> pd.DataFrame:
    """Frame CMF mínimo con categoría provista y fecha única."""
    return pd.DataFrame(
        [
            {
                "as_of_date": "2026-01-31",
                "cmf_portfolio": "commercial_individual",
                "cmf_category": "A1",
                "exposure_amount": 1_000_000,
            }
        ],
        index=pd.Index(["loan-a1"], name="loan_id"),
    )


def _pd_breaks_frame() -> pd.DataFrame:
    """Frame CMF sin categoría, resuelta desde PD condicional."""
    return pd.DataFrame(
        [
            {
                "as_of_date": "2026-01-31",
                "cmf_portfolio": "commercial_individual",
                "exposure_amount": 1_000_000,
            }
        ],
        index=pd.Index(["loan-b4"], name="loan_id"),
    )


def _pd_breaks_config() -> CmfProvisioningConfig:
    """Config que exige PD, labels y splits antes del cálculo."""
    return _config(
        pd_mapping=CmfPdMappingConfig(
            method="pd_breaks",
            pd_breaks=(0.10,),
            categories=("A1", "B4"),
        )
    )


def _contingent_object_frame(*, with_nan: bool) -> pd.DataFrame:
    """Frame válido con columnas contingentes en dtype object."""
    index = pd.Index(["contingente", "directo"], name="loan_id")
    frame = pd.DataFrame(
        {
            "as_of_date": ["2026-01-31", "2026-01-31"],
            "cmf_portfolio": ["commercial_individual", "commercial_individual"],
            "cmf_category": ["A1", "A1"],
            "exposure_amount": [0, 1_000_000],
            "contingent_type": ["avales_fianzas", "avales_fianzas"],
        },
        index=index,
    )
    if with_nan:
        frame["contingent_amount"] = pd.Series([Decimal("1000"), np.nan], index=index, dtype=object)
        frame["is_default"] = pd.Series([True, np.nan], index=index, dtype=object)
        return frame
    frame["contingent_amount"] = pd.Series(
        [Decimal("1000"), Decimal("0")], index=index, dtype=object
    )
    frame["is_default"] = pd.Series([False, False], index=index, dtype=object)
    return frame


def _native_contingent_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Convierte el fixture object a dtypes no-object para comparar auditoría."""
    native = frame.copy(deep=True)
    native["contingent_amount"] = pd.to_numeric(native["contingent_amount"])
    native["is_default"] = native["is_default"].astype("boolean")
    return native


def _study_with_frame(
    *,
    config: CmfProvisioningConfig | None = None,
    frame: pd.DataFrame | None = None,
    active_config: bool = True,
) -> Study:
    """Construye un ``Study`` con ``data.frame`` CMF preinyectado."""
    cfg = config or _config()
    root_config = NikodymConfig(provisioning_cmf=cfg) if active_config else NikodymConfig()
    study = Study(root_config)
    study.artifacts.set("data", "frame", _standalone_frame() if frame is None else frame)
    return study


def _execute(
    study: Study,
    *,
    config: CmfProvisioningConfig | None = None,
) -> CmfProvisionResult:
    """Ejecuta el step con semilla fija para snapshots reproducibles."""
    step = CmfProvisioningStep.from_config(config or _config())
    return step.execute(study, np.random.default_rng(ROOT_SEED))


def _snapshot(result: CmfProvisionResult) -> dict[str, Any]:
    """Devuelve un snapshot serializable estable del resultado CMF."""
    return {
        "detail": result.detail.astype(str).to_csv(),
        "summary": result.summary.astype(str).to_csv(),
        "card": result.card.model_dump(mode="json"),
    }


def _execute_with_audit_payload(frame: pd.DataFrame) -> tuple[CmfProvisionResult, dict[str, Any]]:
    """Ejecuta el step y devuelve el payload auditado de contingentes B-3."""
    study = _study_with_frame(frame=frame)
    sink = InMemoryAuditSink()
    study.set_audit_sink(sink)
    step = CmfProvisioningStep.from_config(study.config.provisioning_cmf)
    step._audit = sink
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("error")
        result = step.execute(study, np.random.default_rng(ROOT_SEED))
    assert caught == []
    payload = next(
        event.payload["valor"]
        for event in sink.events
        if event.kind == "decision" and event.payload["regla"] == "cmf_contingent_b3"
    )
    return result, payload


def test_from_config_registro_reexport_y_contrato_step_exacto() -> None:
    """``CmfProvisioningStep`` expone el contrato CT-1 exacto de SDD-15 §4."""
    cfg = _config()
    step = CmfProvisioningStep.from_config(cfg)
    sink = InMemoryAuditSink()
    step._audit = sink

    assert REGISTRY.resolve("provisioning_cmf", "standard") is CmfProvisioningStep
    assert cmf_pkg.__getattr__("CmfProvisioningStep") is CmfProvisioningStep
    assert step.config is cfg
    assert step.name == "provisioning_cmf"
    assert step.requires == (("data", "frame"),)
    assert step.provides == tuple(("provisioning_cmf", key) for key in CMF_PROVISIONING_ARTIFACTS)
    step.emit(
        AuditEvent(
            kind="decision",
            step="provisioning_cmf",
            payload={"regla": "x"},
            ts=datetime.now(UTC),
        )
    )
    assert sink.events[-1].payload == {"regla": "x"}


def test_core_study_cablea_provisioning_cmf_en_orden_por_defecto() -> None:
    """``Study`` resuelve ``provisioning_cmf`` como dominio perezoso posterior a F1."""
    order = study_module._DEFAULT_DOMAIN_ORDER
    assert order.index("calibration") < order.index("provisioning_cmf")
    assert study_module._DOMAIN_MODULES["provisioning_cmf"] == "nikodym.provisioning.cmf"
    assert study_module._DOMAIN_CONFIG_CLASSES["provisioning_cmf"] == (
        "nikodym.provisioning.cmf.config",
        "CmfProvisioningConfig",
    )

    study = Study(NikodymConfig(provisioning_cmf=CmfProvisioningConfig()))

    assert study._default_step_names() == ["provisioning_cmf"]
    assert isinstance(study._resolve_step("provisioning_cmf"), CmfProvisioningStep)


def test_ct1_falta_data_frame_levanta_artifactnotfound() -> None:
    """La dependencia dura única ``data.frame`` falla con error CT-1 tipado."""
    study = Study(NikodymConfig(provisioning_cmf=_config()))
    step = CmfProvisioningStep.from_config(study.config.provisioning_cmf)

    with pytest.raises(ArtifactNotFoundError, match=r"\('data', 'frame'\)"):
        step.execute(study, np.random.default_rng(ROOT_SEED))


def test_standalone_con_categoria_provista_no_bloquea_sin_modelo_y_publica_card() -> None:
    """El modo default no lee ``model.raw_pd_frame`` y produce la card CMF."""
    study = _study_with_frame(active_config=False)
    result = _execute(study)

    assert isinstance(result, CmfProvisionResult)
    assert isinstance(result.card, CmfProvisionCard)
    assert result.records[0].cmf_category == "A1"
    assert result.records[0].provision_amount == EXPECTED_A1_PROVISION
    assert result.card.total_provision_amount == EXPECTED_A1_PROVISION
    assert study.artifacts.get("provisioning_cmf", "card").n_rows == 1


def test_pd_breaks_sin_pd_labels_o_splits_falla_antes_de_calcular() -> None:
    """La ruta ``pd_breaks`` exige sus artefactos condicionales antes del motor."""
    cfg = _pd_breaks_config()
    study = _study_with_frame(config=cfg, frame=_pd_breaks_frame())
    step = CmfProvisioningStep.from_config(cfg)

    with pytest.raises(ArtifactNotFoundError, match=r"pd_breaks.*model.*raw_pd_frame"):
        step.execute(study, np.random.default_rng(ROOT_SEED))

    study.artifacts.set(
        "model",
        "raw_pd_frame",
        pd.DataFrame({"pd_raw": [0.20]}, index=["loan-b4"]),
    )
    with pytest.raises(ArtifactNotFoundError, match=r"pd_breaks.*data.*labels"):
        step.execute(study, np.random.default_rng(ROOT_SEED))

    study.artifacts.set("data", "labels", object())
    with pytest.raises(ArtifactNotFoundError, match=r"pd_breaks.*data.*splits"):
        step.execute(study, np.random.default_rng(ROOT_SEED))


def test_pd_breaks_valida_pd_frame_y_no_muta_inputs() -> None:
    """Con prerequisitos completos, ``pd_breaks`` asigna categoría y preserva artefactos."""
    cfg = _pd_breaks_config()
    frame = _pd_breaks_frame()
    pd_frame = pd.DataFrame({"pd_raw": [0.20]}, index=pd.Index(["loan-b4"], name="loan_id"))
    original_frame = frame.copy(deep=True)
    original_pd = pd_frame.copy(deep=True)
    study = _study_with_frame(config=cfg, frame=frame)
    study.artifacts.set("model", "raw_pd_frame", pd_frame)
    study.artifacts.set("data", "labels", SimpleNamespace(frame_index=tuple(frame.index)))
    study.artifacts.set("data", "splits", SimpleNamespace(partitions=("desarrollo",)))

    result = CmfProvisioningStep.from_config(cfg).execute(
        study,
        np.random.default_rng(ROOT_SEED),
    )

    assert result.records[0].cmf_category == "B4"
    assert result.records[0].pd_source_value == Decimal("0.2")
    assert result.records[0].provision_amount == EXPECTED_B4_PROVISION
    assert_frame_equal(study.artifacts.get("data", "frame"), original_frame)
    assert_frame_equal(study.artifacts.get("model", "raw_pd_frame"), original_pd)


def test_pd_breaks_pd_frame_invalido_o_sin_columna_falla_con_cmfconfigerror() -> None:
    """El preflight de PD usa errores de configuración antes de calcular."""
    cfg = _pd_breaks_config()
    study = _study_with_frame(config=cfg, frame=_pd_breaks_frame())
    study.artifacts.set("model", "raw_pd_frame", object())
    study.artifacts.set("data", "labels", object())
    study.artifacts.set("data", "splits", object())

    with pytest.raises(CmfConfigError, match=r"pandas\.DataFrame"):
        CmfProvisioningStep.from_config(cfg).execute(study, np.random.default_rng(ROOT_SEED))

    study = _study_with_frame(config=cfg, frame=_pd_breaks_frame())
    study.artifacts.set(
        "model",
        "raw_pd_frame",
        pd.DataFrame({"otra_pd": [0.20]}, index=["loan-b4"]),
    )
    study.artifacts.set("data", "labels", object())
    study.artifacts.set("data", "splits", object())

    with pytest.raises(CmfConfigError, match="pd_column='pd_raw'"):
        CmfProvisioningStep.from_config(cfg).execute(study, np.random.default_rng(ROOT_SEED))


def test_execute_publica_copias_y_audita_decisiones_cmf() -> None:
    """El step publica artefactos defensivos y registra decisiones SDD-15 §9."""
    study = _study_with_frame()
    sink = InMemoryAuditSink()
    study.set_audit_sink(sink)
    step = CmfProvisioningStep.from_config(study.config.provisioning_cmf)
    step._audit = sink

    result = step.execute(study, np.random.default_rng(ROOT_SEED))

    assert_frame_equal(study.artifacts.get("provisioning_cmf", "detail"), result.detail)
    assert_frame_equal(study.artifacts.get("provisioning_cmf", "summary"), result.summary)
    assert study.artifacts.get("provisioning_cmf", "matrix_bundle") == result.matrix_bundle
    stored_result = study.artifacts.get("provisioning_cmf", "result")
    assert_frame_equal(stored_result.detail, result.detail)
    assert_frame_equal(stored_result.summary, result.summary)
    assert stored_result.card == result.card
    assert stored_result.matrix_bundle == result.matrix_bundle
    assert study.artifacts.get("provisioning_cmf", "card") == result.card
    mutated_detail = result.detail
    mutated_detail.loc["loan-a1", "provision_amount"] = Decimal("0")
    assert (
        study.artifacts.get("provisioning_cmf", "detail").loc[
            "loan-a1",
            "provision_amount",
        ]
        == EXPECTED_A1_PROVISION
    )

    rules = [event.payload["regla"] for event in sink.events if event.kind == "decision"]
    assert "cmf_b1_b3_engine" in rules
    assert {
        "cmf_matrix_version",
        "cmf_pd_mapping",
        "cmf_consumer_debtor_aggregation",
        "cmf_guarantee_policy",
        "cmf_contingent_b3",
        "cmf_excluded_rows",
        "cmf_rounding_policy",
        "cmf_falta_dato",
    }.issubset(set(rules))


@pytest.mark.parametrize(("with_nan", "expected_override_rows"), [(False, 0), (True, 1)])
def test_execute_auditoria_dtype_object_contingentes_sin_futurewarning(
    with_nan: bool,
    expected_override_rows: int,
) -> None:
    """La auditoría soporta columnas object con/sin NaN sin warnings de downcast."""
    frame = _contingent_object_frame(with_nan=with_nan)
    assert frame["contingent_amount"].dtype == object
    assert frame["is_default"].dtype == object

    result, object_payload = _execute_with_audit_payload(frame)
    _, native_payload = _execute_with_audit_payload(_native_contingent_frame(frame))

    expected = {
        "input_contingent_rows": 1,
        "converted_rows": 1,
        "default_override_rows": expected_override_rows,
        "ccf_percent_counts": {"100": 1, "<NA>": 1},
    }
    assert object_payload == expected
    assert object_payload == native_payload
    assert result.detail.loc["contingente", "contingent_exposure_amount"] == Decimal("1000")


def test_reproducibilidad_detail_summary_card_y_term_structure_none() -> None:
    """Dos ejecuciones iguales producen snapshots byte-equivalentes y sin term-structure."""
    first = _execute(_study_with_frame())
    second = _execute(_study_with_frame())

    assert _snapshot(first) == _snapshot(second)
    assert first.term_structure() is None
    assert second.term_structure() is None


def test_study_run_publica_card_end_to_end() -> None:
    """``Study.run(['provisioning_cmf'])`` publica la card CMF final."""
    study = _study_with_frame()

    study.run(steps=["provisioning_cmf"])

    assert study.artifacts.get("provisioning_cmf", "card").total_provision_amount == (
        EXPECTED_A1_PROVISION
    )


def test_as_of_date_y_config_helpers_defensivos() -> None:
    """Helpers de config y fecha fallan temprano con mensajes tipados."""
    cfg = _config()
    fallback = _config()
    raw_study = SimpleNamespace(
        config=SimpleNamespace(provisioning_cmf={"exposure": {"rounding": "currency_2dp"}})
    )

    assert step_module._cmf_config_from_study(raw_study, fallback=fallback).exposure.rounding == (
        "currency_2dp"
    )
    assert (
        step_module._cmf_config_from_study(
            SimpleNamespace(config=SimpleNamespace(provisioning_cmf=None)),
            fallback=fallback,
        )
        is fallback
    )

    with pytest.raises(CmfConfigError, match="falta la columna"):
        step_module._as_of_date_from_frame(_standalone_frame().drop(columns=["as_of_date"]), cfg)
    with pytest.raises(CmfConfigError, match="no nula"):
        step_module._as_of_date_from_frame(_standalone_frame().assign(as_of_date=None), cfg)
    with pytest.raises(CmfConfigError, match="una sola fecha"):
        step_module._as_of_date_from_frame(
            pd.concat(
                [
                    _standalone_frame(),
                    _standalone_frame().assign(as_of_date="2026-02-28"),
                ]
            ),
            cfg,
        )


def test_helpers_defensivos_de_estadisticas_y_validacion() -> None:
    """Ramas defensivas de helpers quedan tipadas y deterministas."""
    cfg = _config()
    with pytest.raises(CmfInputError, match=r"data\.frame.*pandas\.DataFrame"):
        step_module._as_dataframe(object(), pd, "data.frame")

    assert step_module._consumer_aggregation_stats(pd.DataFrame({"otra": [1]}), config=cfg) == {
        "portfolio_column": "cmf_portfolio",
        "consumer_rows": 0,
        "consumer_debtors": 0,
    }
    assert step_module._consumer_aggregation_stats(
        pd.DataFrame({"cmf_portfolio": ["consumer"]}),
        config=cfg,
    ) == {
        "portfolio_column": "cmf_portfolio",
        "consumer_rows": 1,
        "consumer_debtors": 0,
    }

    detail = pd.DataFrame(
        {
            "contingent_exposure_amount": [100, 0],
            "ccf_percent": [Decimal("100"), None],
        }
    )
    frame = pd.DataFrame(
        {
            "contingent_amount": [100, 0],
            "is_default": [True, False],
        }
    )
    assert step_module._contingent_stats(frame, detail=detail, config=cfg) == {
        "input_contingent_rows": 1,
        "converted_rows": 1,
        "default_override_rows": 1,
        "ccf_percent_counts": {"100": 1, "<NA>": 1},
    }
    assert step_module._contingent_stats(
        pd.DataFrame({"contingent_amount": [50]}),
        detail=detail,
        config=cfg,
    ) == {
        "input_contingent_rows": 1,
        "converted_rows": 1,
        "default_override_rows": 0,
        "ccf_percent_counts": {"100": 1, "<NA>": 1},
    }
    assert step_module._value_counts(pd.DataFrame({"x": [1]}), "missing") == {}
    assert step_module._non_zero_count(pd.DataFrame({"x": [1]}), "missing") == 0
    assert step_module._warning_codes(pd.DataFrame({"x": [1]})) == ()
    warnings = pd.DataFrame({"warning_codes": [("A", "B"), ["B", "C"], "FALTA-DATO", None, ""]})
    assert step_module._warning_codes(warnings) == ("A", "B", "C", "FALTA-DATO")


def test_import_pandas_y_provisioning_cmf_liviano_subprocess(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``import nikodym.provisioning.cmf`` registra el step sin cargar tabulares pesados."""
    real_import = step_module.importlib.import_module

    def block_pandas(name: str) -> Any:
        if name == "pandas":
            raise ModuleNotFoundError("No module named 'pandas'", name="pandas")
        return real_import(name)

    monkeypatch.setattr(step_module.importlib, "import_module", block_pandas)
    with pytest.raises(MissingDependencyError, match="CmfProvisioningStep requiere pandas"):
        step_module._import_pandas()

    code = textwrap.dedent(
        """
        import sys
        import nikodym.provisioning.cmf
        from nikodym.core.registry import REGISTRY

        assert REGISTRY.resolve("provisioning_cmf", "standard").__name__ == "CmfProvisioningStep"
        blocked = [
            name
            for name in ("pandas", "pandera", "pyarrow")
            if name in sys.modules
        ]
        assert blocked == [], blocked
        assert "nikodym.provisioning.cmf.matrices" not in sys.modules
        print("ok")
        """
    )
    completed = subprocess.run(
        [sys.executable, "-c", code],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr + completed.stdout
    assert completed.stdout.strip() == "ok"
