"""Tests de ``InternalProvisioningStep``: CT-1, ``requires`` dinámicos, cableado e import liviano.

Cubre el contrato CT-1 exacto (``requires`` según ``pd_source`` y las cinco claves ``provides``), el
cableado de ``core.study`` (orden, módulos y config classes), la ejecución **real** vía
``Study.run()`` y el import liviano (``import nikodym.provisioning.internal`` registra el step sin
cargar pandas).
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

import nikodym.core.study as study_module
import nikodym.provisioning.internal as internal_pkg
import nikodym.provisioning.internal.step as step_module
from nikodym.core.audit import AuditEvent, InMemoryAuditSink
from nikodym.core.config import NikodymConfig
from nikodym.core.exceptions import ArtifactNotFoundError, MissingDependencyError
from nikodym.core.registry import REGISTRY
from nikodym.core.study import Study
from nikodym.provisioning.internal import (
    INTERNAL_PROVISIONING_ARTIFACTS,
    InternalProvisioningConfig,
    InternalProvisioningStep,
)
from nikodym.provisioning.internal.exceptions import InternalConfigError, InternalInputError
from nikodym.provisioning.internal.results import InternalProvisionCard, InternalProvisionResult

ROOT_SEED = 20_260_713
AS_OF = "2026-01-31"
# Dos operaciones en un mismo grupo: E = 1.000.000 + 3.000.000 = 4.000.000
#   PD  = (1M·0,02 + 3M·0,10)/4M = (20.000 + 300.000)/4.000.000 = 0,08
#   LGD = (1M·0,50 + 3M·0,60)/4M = (500.000 + 1.800.000)/4.000.000 = 0,575
#   Provisión = 4.000.000 · 0,08 · 0,575 = 4.000.000 · 0,046 = 184.000,00
EXPECTED_PROVISION = Decimal("184000.00")


def _cfg(**kwargs: Any) -> InternalProvisioningConfig:
    """Config del step: grupo provisto para que el golden sea legible a mano."""
    base: dict[str, Any] = {"grouping": "provided", "group_col": "grupo"}
    base.update(kwargs)
    return InternalProvisioningConfig(**base)


def _frame() -> pd.DataFrame:
    """Frame económico con fecha de cierre única."""
    return pd.DataFrame(
        [
            {
                "as_of_date": AS_OF,
                "cmf_portfolio": "consumer",
                "grupo": "banda_alta",
                "exposure_amount": 1_000_000,
                "lgd": 0.50,
            },
            {
                "as_of_date": AS_OF,
                "cmf_portfolio": "consumer",
                "grupo": "banda_alta",
                "exposure_amount": 3_000_000,
                "lgd": 0.60,
            },
        ],
        index=pd.Index(["op1", "op2"], name="loan_id"),
    )


def _pd_frame(column: str = "pd_calibrated") -> pd.DataFrame:
    """Artefacto de PD por operación de la fuente declarada."""
    return pd.DataFrame({column: [0.02, 0.10]}, index=pd.Index(["op1", "op2"], name="loan_id"))


def _study(
    cfg: InternalProvisioningConfig | None = None,
    *,
    frame: pd.DataFrame | None = None,
    active_config: bool = True,
) -> Study:
    """``Study`` con ``data.frame`` y la PD calibrada preinyectados."""
    config = cfg or _cfg()
    root = NikodymConfig(provisioning_internal=config) if active_config else NikodymConfig()
    study = Study(root)
    study.artifacts.set("data", "frame", _frame() if frame is None else frame)
    study.artifacts.set("calibration", "calibrated_pd_frame", _pd_frame())
    return study


def _execute(
    study: Study,
    cfg: InternalProvisioningConfig | None = None,
) -> InternalProvisionResult:
    """Ejecuta el step con semilla fija."""
    step = InternalProvisioningStep.from_config(cfg or _cfg())
    return step.execute(study, np.random.default_rng(ROOT_SEED))


# ─────────────────────────── contrato CT-1 y registro ───────────────────────────


def test_contrato_step_exacto_y_registro() -> None:
    """``InternalProvisioningStep`` expone el contrato CT-1 exacto de SDD-28 §4.1."""
    cfg = _cfg()
    step = InternalProvisioningStep.from_config(cfg)
    sink = InMemoryAuditSink()
    step._audit = sink

    assert REGISTRY.resolve("provisioning_internal", "standard") is InternalProvisioningStep
    assert internal_pkg.__getattr__("InternalProvisioningStep") is InternalProvisioningStep
    assert step.config is cfg
    assert step.name == "provisioning_internal"
    assert step.provides == tuple(
        ("provisioning_internal", key) for key in INTERNAL_PROVISIONING_ARTIFACTS
    )
    assert INTERNAL_PROVISIONING_ARTIFACTS == ("detail", "groups", "summary", "result", "card")

    step.emit(
        AuditEvent(
            kind="decision",
            step="provisioning_internal",
            payload={"regla": "x"},
            ts=datetime.now(UTC),
        )
    )
    assert sink.events[-1].payload == {"regla": "x"}


def test_requires_dinamicos_segun_pd_source() -> None:
    """El ``requires`` cambia con la fuente de PD declarada (CT-1, patrón SDD-16 §4)."""
    calibrado = InternalProvisioningStep.from_config(_cfg())
    assert calibrado.requires == (("data", "frame"), ("calibration", "calibrated_pd_frame"))

    crudo = InternalProvisioningStep.from_config(_cfg(pd_source="model", pd_column="pd_raw"))
    assert crudo.requires == (("data", "frame"), ("model", "raw_pd_frame"))


def test_core_study_cablea_provisioning_internal_en_orden_por_defecto() -> None:
    """``Study`` resuelve ``provisioning_internal`` como dominio perezoso posterior a F1."""
    order = study_module._DEFAULT_DOMAIN_ORDER
    assert order.index("calibration") < order.index("provisioning_internal")
    assert order.index("provisioning_cmf") < order.index("provisioning_internal")
    assert order.index("provisioning_internal") < order.index("provisioning")
    assert study_module._DOMAIN_MODULES["provisioning_internal"] == "nikodym.provisioning.internal"
    assert study_module._DOMAIN_CONFIG_CLASSES["provisioning_internal"] == (
        "nikodym.provisioning.internal.config",
        "InternalProvisioningConfig",
    )

    study = Study(NikodymConfig(provisioning_internal=_cfg()))

    assert study._default_step_names() == ["provisioning_internal"]
    assert isinstance(study._resolve_step("provisioning_internal"), InternalProvisioningStep)


@pytest.mark.parametrize(
    ("dominio", "clave"),
    [("data", "frame"), ("calibration", "calibrated_pd_frame")],
)
def test_ct1_artefacto_requerido_ausente_levanta(dominio: str, clave: str) -> None:
    """Cada dependencia dura falla con error CT-1 tipado antes de calcular."""
    study = _study()
    study.artifacts._store.pop((dominio, clave))  # type: ignore[attr-defined]
    step = InternalProvisioningStep.from_config(_cfg())

    with pytest.raises(ArtifactNotFoundError, match=rf"\('{dominio}', '{clave}'\)"):
        step.execute(study, np.random.default_rng(ROOT_SEED))


# ─────────────────────────── ejecución real end-to-end ───────────────────────────


def test_study_run_real_publica_los_cinco_artefactos() -> None:
    """``Study.run()`` corre el pipeline por defecto y publica el método interno completo."""
    study = _study()

    study.run()

    assert study.run_context.status == "done"
    for key in INTERNAL_PROVISIONING_ARTIFACTS:
        assert study.artifacts.has("provisioning_internal", key), key

    card = study.artifacts.get("provisioning_internal", "card")
    assert isinstance(card, InternalProvisionCard)
    assert card.total_internal_provision == EXPECTED_PROVISION
    assert card.total_exposure == Decimal("4000000")
    assert card.n_groups == 1
    assert card.n_rows == 2
    assert card.as_of_date == AS_OF

    groups = study.artifacts.get("provisioning_internal", "groups")
    assert groups.iloc[0]["pd_group"] == Decimal("0.08")
    assert groups.iloc[0]["lgd_group"] == Decimal("0.575")
    assert groups.iloc[0]["provision_amount"] == EXPECTED_PROVISION

    detail = study.artifacts.get("provisioning_internal", "detail")
    assert sum(detail["provision_amount"]) == EXPECTED_PROVISION
    assert (
        study.artifacts.get("provisioning_internal", "summary").loc["consumer", "total_provision"]
        == EXPECTED_PROVISION
    )


def test_study_run_es_determinista_byte_a_byte() -> None:
    """Dos corridas reales producen el mismo total y el mismo detalle, byte a byte."""
    primera = _study()
    primera.run()
    segunda = _study()
    segunda.run()

    card_a = primera.artifacts.get("provisioning_internal", "card")
    card_b = segunda.artifacts.get("provisioning_internal", "card")
    assert card_a.model_dump(mode="json") == card_b.model_dump(mode="json")
    assert (
        primera.artifacts.get("provisioning_internal", "detail").astype(str).to_csv()
        == segunda.artifacts.get("provisioning_internal", "detail").astype(str).to_csv()
    )


def test_pd_source_model_corre_contra_el_artefacto_crudo() -> None:
    """Con ``pd_source='model'`` el step lee ``model.raw_pd_frame``."""
    cfg = _cfg(pd_source="model", pd_column="pd_raw")
    study = Study(NikodymConfig(provisioning_internal=cfg))
    study.artifacts.set("data", "frame", _frame())
    study.artifacts.set("model", "raw_pd_frame", _pd_frame("pd_raw"))

    study.run()

    card = study.artifacts.get("provisioning_internal", "card")
    assert card.pd_source == "model"
    assert card.total_internal_provision == EXPECTED_PROVISION


def test_execute_publica_copias_defensivas_y_audita_decisiones() -> None:
    """El step publica copias y registra las decisiones auditables de SDD-28 §9."""
    study = _study()
    sink = InMemoryAuditSink()
    study.set_audit_sink(sink)
    step = InternalProvisioningStep.from_config(study.config.provisioning_internal)
    step._audit = sink

    result = step.execute(study, np.random.default_rng(ROOT_SEED))

    assert_frame_equal(study.artifacts.get("provisioning_internal", "detail"), result.detail)
    assert_frame_equal(study.artifacts.get("provisioning_internal", "groups"), result.groups)
    assert_frame_equal(study.artifacts.get("provisioning_internal", "summary"), result.summary)
    assert study.artifacts.get("provisioning_internal", "card") == result.card
    stored = study.artifacts.get("provisioning_internal", "result")
    assert_frame_equal(stored.detail, result.detail)
    assert stored.card == result.card

    mutado = result.detail
    mutado.loc["op1", "provision_amount"] = Decimal("0")
    assert study.artifacts.get("provisioning_internal", "detail").loc[
        "op1", "provision_amount"
    ] != Decimal("0")

    reglas = [event.payload["regla"] for event in sink.events if event.kind == "decision"]
    assert "internal_b1_engine" in reglas
    assert {
        "internal_pd_source",
        "internal_grouping",
        "internal_lgd",
        "internal_b1_method",
        "internal_rounding_policy",
        "internal_falta_dato",
    }.issubset(set(reglas))


def test_step_usa_el_config_del_study_y_cae_al_propio_si_no_hay_seccion() -> None:
    """El step prefiere ``NikodymConfig.provisioning_internal`` y usa el suyo como respaldo."""
    study = _study(active_config=False)
    result = _execute(study)
    assert result.card.total_internal_provision == EXPECTED_PROVISION

    fallback = _cfg()
    crudo = SimpleNamespace(
        config=SimpleNamespace(
            provisioning_internal={
                "grouping": "provided",
                "group_col": "grupo",
                "rounding": "integer_currency",
            }
        )
    )
    resuelto = step_module._internal_config_from_study(crudo, fallback=fallback)
    assert resuelto.rounding == "integer_currency"
    assert (
        step_module._internal_config_from_study(
            SimpleNamespace(config=SimpleNamespace(provisioning_internal=None)),
            fallback=fallback,
        )
        is fallback
    )


# ─────────────────────────── bordes del step ───────────────────────────


def test_as_of_date_debe_ser_unica_y_no_nula() -> None:
    """El método interno exige una sola fecha de cierre por corrida."""
    cfg = _cfg()

    with pytest.raises(InternalConfigError, match="falta la columna"):
        step_module._as_of_date_from_frame(_frame().drop(columns=["as_of_date"]), cfg)

    with pytest.raises(InternalConfigError, match="no nula"):
        step_module._as_of_date_from_frame(_frame().assign(as_of_date=None), cfg)

    multiple = _frame()
    multiple.loc["op2", "as_of_date"] = "2026-02-28"
    with pytest.raises(InternalConfigError, match="una sola fecha de cierre"):
        step_module._as_of_date_from_frame(multiple, cfg)

    assert step_module._as_of_date_from_frame(_frame(), cfg) == AS_OF


def test_artefactos_no_tabulares_levantan_con_error_tipado() -> None:
    """Un artefacto que no es DataFrame falla con el error del dominio, no con un AttributeError."""
    with pytest.raises(InternalInputError, match=r"data\.frame.*pandas\.DataFrame"):
        step_module._as_dataframe(object(), pd, "data.frame")

    with pytest.raises(InternalConfigError, match="pd_source='calibration' exige"):
        step_module._as_pd_source_dataframe(
            object(),
            pd,
            "calibration.calibrated_pd_frame",
            pd_source="calibration",
        )

    study = _study()
    study.artifacts.set("calibration", "calibrated_pd_frame", object(), overwrite=True)
    with pytest.raises(InternalConfigError, match="pd_source='calibration' exige"):
        _execute(study)


def test_import_pandas_ausente_levanta_missing_dependency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sin ``pandas`` el step falla con el error tipado del núcleo."""
    real_import = step_module.importlib.import_module

    def block_pandas(name: str) -> Any:
        if name == "pandas":
            raise ModuleNotFoundError("No module named 'pandas'", name="pandas")
        return real_import(name)

    monkeypatch.setattr(step_module.importlib, "import_module", block_pandas)
    with pytest.raises(MissingDependencyError, match="InternalProvisioningStep requiere pandas"):
        step_module._import_pandas()


def test_lazy_export_desconocido_levanta_attributeerror() -> None:
    """El ``__getattr__`` perezoso no inventa atributos."""
    with pytest.raises(AttributeError, match="has no attribute 'NoExiste'"):
        internal_pkg.__getattr__("NoExiste")


def test_import_provisioning_internal_es_liviano_subprocess() -> None:
    """``import nikodym.provisioning.internal`` registra el step sin cargar tabulares pesados."""
    code = textwrap.dedent(
        """
        import sys
        import nikodym.provisioning.internal
        from nikodym.core.registry import REGISTRY

        resolved = REGISTRY.resolve("provisioning_internal", "standard")
        assert resolved.__name__ == "InternalProvisioningStep", resolved
        blocked = [name for name in ("pandas", "pandera", "pyarrow") if name in sys.modules]
        assert blocked == [], blocked
        assert "nikodym.provisioning.internal.engine" not in sys.modules
        assert "nikodym.provisioning.internal.results" not in sys.modules

        from nikodym.core.config import NikodymConfig
        cfg = NikodymConfig(provisioning_internal={"grouping": "provided", "group_col": "g"})
        assert type(cfg.provisioning_internal).__name__ == "InternalProvisioningConfig"
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
