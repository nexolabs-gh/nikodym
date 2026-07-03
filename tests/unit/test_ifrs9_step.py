"""Tests de ``IfrsProvisioningStep``: CT-1, ``requires`` dinámicos, cableado e import liviano.

Cubre el contrato CT-1 exacto (``requires`` según ``term_structure_source``/``base_pd_source`` y las
seis claves ``provides``), el cableado de ``core.study`` (orden, módulos y config classes), la
ejecución end-to-end vía ``Study.run``, la equivalencia survival↔markov con el mismo ``pd_marginal``
y el import liviano (``import nikodym.core`` no arrastra provisioning; ``import
nikodym.provisioning.ifrs9`` registra el step sin cargar tabulares ni scipy).
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import numpy as np
import pandas as pd
import pytest

import nikodym.core.study as study_module
import nikodym.provisioning.ifrs9 as ifrs9_pkg
import nikodym.provisioning.ifrs9.step as step_module
from nikodym.core.audit import AuditEvent, InMemoryAuditSink
from nikodym.core.config import NikodymConfig
from nikodym.core.exceptions import ArtifactNotFoundError, MissingDependencyError
from nikodym.core.registry import REGISTRY
from nikodym.core.study import Study
from nikodym.provisioning.ifrs9 import (
    IFRS9_PROVISIONING_ARTIFACTS,
    IfrsProvisioningConfig,
    IfrsProvisioningStep,
)
from nikodym.provisioning.ifrs9.config import (
    IfrsEadConfig,
    IfrsLgdConfig,
    IfrsPdConfig,
    IfrsScenarioConfig,
)
from nikodym.provisioning.ifrs9.exceptions import IfrsConfigError, IfrsInputError

ROOT_SEED = 20_260_703
# Golden Stage 1 (EAD 1000, LGD 0.5, pd_marg 0.10/0.08, EIR 0.10, H_12m=1): 50/1.1.
_ECL_12M = 45.45454545454545


def _cfg(**pd_overrides: Any) -> IfrsProvisioningConfig:
    """Config del step: survival, ttc_only, single, EAD/LGD provistas, horizonte 12m=1."""
    pd_kwargs: dict[str, Any] = {
        "term_structure_source": "survival",
        "pit_mode": "ttc_only",
        "horizon_12m_periods": 1,
    }
    pd_kwargs.update(pd_overrides)
    return IfrsProvisioningConfig(
        portfolio_col="portfolio",
        pd=IfrsPdConfig(**pd_kwargs),
        lgd=IfrsLgdConfig(method="provided"),
        ead=IfrsEadConfig(method="provided"),
        scenarios=IfrsScenarioConfig(source="single"),
    )


def _frame() -> pd.DataFrame:
    """Frame económico de una operación con fecha de cálculo única."""
    return pd.DataFrame(
        [
            {
                "as_of_date": "2026-01-31",
                "portfolio": "retail",
                "ead": 1000.0,
                "lgd": 0.5,
                "eir": 0.10,
                "days_past_due": 0,
            }
        ],
        index=pd.Index(["op1"], name="loan_id"),
    )


def _ts() -> pd.DataFrame:
    """Term-structure tidy survival de ``op1`` (2 períodos anuales)."""
    return pd.DataFrame(
        {
            "row_id": ["op1", "op1"],
            "period": [1, 2],
            "time_value": [1.0, 2.0],
            "survival": [0.90, 0.82],
            "pd_marginal": [0.10, 0.08],
            "pd_cumulative": [0.10, 0.18],
            "scenario": [None, None],
            "warning_codes": [(), ()],
        }
    )


def _study(cfg: IfrsProvisioningConfig, *, ts_domain: str = "survival") -> Study:
    """``Study`` con ``data.frame`` y la term-structure preinyectados."""
    study = Study(NikodymConfig(provisioning_ifrs9=cfg))
    study.artifacts.set("data", "frame", _frame())
    study.artifacts.set(ts_domain, "term_structure", _ts())
    return study


def _execute(study: Study, cfg: IfrsProvisioningConfig) -> Any:
    """Ejecuta el step con semilla fija."""
    step = IfrsProvisioningStep.from_config(cfg)
    return step.execute(study, np.random.default_rng(ROOT_SEED))


# ─────────────────────────── contrato CT-1 y registro ───────────────────────────


def test_contrato_step_exacto_y_registro() -> None:
    cfg = _cfg()
    step = IfrsProvisioningStep.from_config(cfg)
    sink = InMemoryAuditSink()
    step._audit = sink

    assert REGISTRY.resolve("provisioning_ifrs9", "standard") is IfrsProvisioningStep
    assert ifrs9_pkg.IfrsProvisioningStep is IfrsProvisioningStep
    assert step.config is cfg
    assert step.name == "provisioning_ifrs9"
    assert step.provides == tuple(
        ("provisioning_ifrs9", key) for key in IFRS9_PROVISIONING_ARTIFACTS
    )
    assert IFRS9_PROVISIONING_ARTIFACTS == (
        "staging",
        "detail",
        "ecl_term_structure",
        "summary",
        "result",
        "card",
    )
    step.emit(AuditEvent(kind="decision", step="x", payload={"regla": "y"}, ts=datetime.now(UTC)))
    assert sink.events[-1].payload == {"regla": "y"}


def test_requires_dinamicos_default() -> None:
    step = IfrsProvisioningStep.from_config(_cfg())
    assert step.requires == (("data", "frame"), ("survival", "term_structure"))


@pytest.mark.parametrize("source", ["survival", "markov", "forward"])
def test_requires_por_term_structure_source(source: str) -> None:
    cfg = _cfg().model_copy(
        update={"pd": IfrsPdConfig(term_structure_source=source, pit_mode="ttc_only")}
    )
    step = IfrsProvisioningStep.from_config(cfg)
    assert step.requires == (("data", "frame"), (source, "term_structure"))


def test_requires_con_calibracion() -> None:
    cfg = _cfg(base_pd_source="calibration")
    step = IfrsProvisioningStep.from_config(cfg)
    assert step.requires == (
        ("data", "frame"),
        ("calibration", "calibrated_pd_frame"),
        ("survival", "term_structure"),
    )


def test_core_study_cablea_provisioning_ifrs9() -> None:
    order = study_module._DEFAULT_DOMAIN_ORDER
    assert order.index("survival") < order.index("provisioning_ifrs9")
    assert order.index("forward") < order.index("provisioning_ifrs9")
    assert order.index("provisioning_ifrs9") < order.index("provisioning_cmf")
    assert study_module._DOMAIN_MODULES["provisioning_ifrs9"] == "nikodym.provisioning.ifrs9"
    assert study_module._DOMAIN_CONFIG_CLASSES["provisioning_ifrs9"] == (
        "nikodym.provisioning.ifrs9.config",
        "IfrsProvisioningConfig",
    )

    study = Study(NikodymConfig(provisioning_ifrs9=_cfg()))
    assert study._default_step_names() == ["provisioning_ifrs9"]
    assert isinstance(study._resolve_step("provisioning_ifrs9"), IfrsProvisioningStep)


# ─────────────────────────── ejecución end-to-end ───────────────────────────


def test_execute_publica_seis_artefactos_y_audita() -> None:
    cfg = _cfg()
    study = _study(cfg)
    sink = InMemoryAuditSink()
    study.set_audit_sink(sink)
    step = IfrsProvisioningStep.from_config(cfg)
    step._audit = sink

    result = step.execute(study, np.random.default_rng(ROOT_SEED))

    for key in IFRS9_PROVISIONING_ARTIFACTS:
        assert study.artifacts.has("provisioning_ifrs9", key)
    np.testing.assert_allclose(result.detail.iloc[0]["ecl_reported"], _ECL_12M, rtol=1e-12)
    reglas = {
        event.payload["regla"]
        for event in sink.events
        if event.kind == "decision" and "regla" in event.payload
    }
    assert {
        "ifrs9_term_structure_source",
        "ifrs9_pit",
        "ifrs9_pd_horizon",
        "ifrs9_lgd",
        "ifrs9_ead",
        "ifrs9_staging",
        "ifrs9_scenarios",
        "ifrs9_ecl",
    } <= reglas


def test_study_run_publica_card_end_to_end() -> None:
    cfg = _cfg()
    study = _study(cfg)
    study.run(steps=["provisioning_ifrs9"])
    card = study.artifacts.get("provisioning_ifrs9", "card")
    np.testing.assert_allclose(card.total_ecl_reported, _ECL_12M, rtol=1e-12)


def test_survival_y_markov_mismo_ecl() -> None:
    cfg_s = _cfg()
    result_s = _execute(_study(cfg_s, ts_domain="survival"), cfg_s)
    cfg_m = _cfg().model_copy(
        update={
            "pd": IfrsPdConfig(
                term_structure_source="markov", pit_mode="ttc_only", horizon_12m_periods=1
            )
        }
    )
    result_m = _execute(_study(cfg_m, ts_domain="markov"), cfg_m)
    np.testing.assert_allclose(
        result_m.card.total_ecl_reported, result_s.card.total_ecl_reported, rtol=1e-12
    )


# ─────────────────────────── CT-1: artefactos requeridos ───────────────────────────


def test_ct1_falta_data_frame() -> None:
    study = Study(NikodymConfig(provisioning_ifrs9=_cfg()))
    step = IfrsProvisioningStep.from_config(_cfg())
    with pytest.raises(ArtifactNotFoundError, match=r"\('data', 'frame'\)"):
        step.execute(study, np.random.default_rng(ROOT_SEED))


def test_ct1_falta_term_structure() -> None:
    study = Study(NikodymConfig(provisioning_ifrs9=_cfg()))
    study.artifacts.set("data", "frame", _frame())
    step = IfrsProvisioningStep.from_config(_cfg())
    with pytest.raises(ArtifactNotFoundError, match=r"\('survival', 'term_structure'\)"):
        step.execute(study, np.random.default_rng(ROOT_SEED))


def test_ct1_falta_calibrated_pd() -> None:
    cfg = _cfg(base_pd_source="calibration")
    study = Study(NikodymConfig(provisioning_ifrs9=cfg))
    study.artifacts.set("data", "frame", _frame())
    study.artifacts.set("survival", "term_structure", _ts())
    step = IfrsProvisioningStep.from_config(cfg)
    with pytest.raises(ArtifactNotFoundError, match="calibrated_pd_frame"):
        step.execute(study, np.random.default_rng(ROOT_SEED))


def test_calibrated_pd_se_lee_cuando_corresponde() -> None:
    cfg = _cfg(base_pd_source="calibration").model_copy(
        update={"lgd": IfrsLgdConfig(method="provided"), "ead": IfrsEadConfig(method="provided")}
    )
    study = _study(cfg)
    study.artifacts.set(
        "calibration",
        "calibrated_pd_frame",
        pd.DataFrame({"pd_calibrated": [0.033]}, index=["op1"]),
    )
    result = _execute(study, cfg)
    np.testing.assert_allclose(result.detail.iloc[0]["pd_12m"], 0.033)


# ─────────────────────────── helpers defensivos ───────────────────────────


def test_ifrs_config_from_study_ramas() -> None:
    fallback = _cfg()
    # dict → model_validate.
    raw_study = SimpleNamespace(
        config=SimpleNamespace(provisioning_ifrs9={"pd": {"pit_mode": "ttc_only"}})
    )
    resolved = step_module._ifrs_config_from_study(raw_study, fallback=fallback)
    assert resolved.pd.pit_mode == "ttc_only"
    # None → fallback.
    none_study = SimpleNamespace(config=SimpleNamespace(provisioning_ifrs9=None))
    assert step_module._ifrs_config_from_study(none_study, fallback=fallback) is fallback
    # Instancia → se devuelve tal cual.
    inst_study = SimpleNamespace(config=SimpleNamespace(provisioning_ifrs9=fallback))
    assert step_module._ifrs_config_from_study(inst_study, fallback=fallback) is fallback


def test_as_of_date_defensivo() -> None:
    cfg = _cfg()
    with pytest.raises(IfrsConfigError, match="falta la columna"):
        step_module._as_of_date_from_frame(_frame().drop(columns=["as_of_date"]), cfg)
    with pytest.raises(IfrsConfigError, match="no nula"):
        step_module._as_of_date_from_frame(_frame().assign(as_of_date=None), cfg)
    with pytest.raises(IfrsConfigError, match="una sola fecha"):
        step_module._as_of_date_from_frame(
            pd.concat([_frame(), _frame().assign(as_of_date="2026-02-28")]), cfg
        )


def test_as_dataframe_defensivo() -> None:
    with pytest.raises(IfrsInputError, match=r"data\.frame.*pandas\.DataFrame"):
        step_module._as_dataframe(object(), pd, "data.frame")


def test_as_calibrated_dataframe_defensivo() -> None:
    with pytest.raises(IfrsConfigError, match=r"PD calibrada pandas\.DataFrame"):
        step_module._as_calibrated_dataframe(object(), pd, "calibration.calibrated_pd_frame")


def test_trigger_counts() -> None:
    staging = pd.DataFrame({"sicr_triggers": [("a", "b"), ("b",), ()]})
    assert step_module._trigger_counts(staging) == {"a": 1, "b": 2}


# ─────────────────────────── import liviano ───────────────────────────


def test_import_pandas_ausente(monkeypatch: pytest.MonkeyPatch) -> None:
    real_import = step_module.importlib.import_module

    def block_pandas(name: str) -> Any:
        if name == "pandas":
            raise ModuleNotFoundError("No module named 'pandas'", name="pandas")
        return real_import(name)

    monkeypatch.setattr(step_module.importlib, "import_module", block_pandas)
    with pytest.raises(MissingDependencyError, match="IfrsProvisioningStep requiere pandas"):
        step_module._import_pandas()


def test_import_liviano_subprocess() -> None:
    code = textwrap.dedent(
        """
        import sys
        import nikodym.core
        assert not [
            m for m in ("nikodym.provisioning", "pandas", "pandera", "pyarrow", "scipy")
            if m in sys.modules
        ], [m for m in sys.modules if m.startswith("nikodym.provisioning")]

        import nikodym.provisioning.ifrs9
        from nikodym.core.registry import REGISTRY
        assert REGISTRY.resolve("provisioning_ifrs9", "standard").__name__ == "IfrsProvisioningStep"
        blocked = [
            m for m in ("pandas", "pandera", "pyarrow", "scipy", "statsmodels")
            if m in sys.modules
        ]
        assert blocked == [], blocked
        print("ok")
        """
    )
    completed = subprocess.run(
        [sys.executable, "-c", code],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert completed.returncode == 0, completed.stderr + completed.stdout
    assert completed.stdout.strip() == "ok"
