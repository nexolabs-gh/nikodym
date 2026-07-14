"""Tests de ``ProvisioningStep`` (SDD-17 §4/§7/§9; CT-1): cierre del track de Provisiones (T4).

Cubre el contrato del step y su registro, los ``requires`` dinámicos (CT-1) según ``require_both`` y
``consume_*``, el cableado de ``core.study`` (orden/módulos/config classes), la publicación de las
cuatro claves y el audit trail (§9), la resolución de la fecha de cálculo heredada, el CT-1
(``ArtifactNotFoundError`` si falta un ``result`` requerido), el *passthrough* de un solo motor, la
integración end-to-end sobre AMBOS motores (``Study.run`` real cmf + ifrs9 + provisioning con golden
del máximo) y el import liviano (``import nikodym.core`` no arrastra provisioning; ``import
nikodym.provisioning`` registra el step sin cargar pandas).
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

import nikodym.core.study as study_module
import nikodym.provisioning as prov_pkg
import nikodym.provisioning.step as step_module
from nikodym.core.audit import AuditEvent, InMemoryAuditSink
from nikodym.core.config import NikodymConfig
from nikodym.core.exceptions import ArtifactNotFoundError
from nikodym.core.registry import REGISTRY
from nikodym.core.study import Study
from nikodym.provisioning import (
    PROVISIONING_ARTIFACTS,
    ProvisioningConfig,
    ProvisioningStep,
    ProvisionOrchestrationResult,
)
from nikodym.provisioning.cmf.config import CmfProvisioningConfig
from nikodym.provisioning.cmf.matrices import CmfMatrixBundle, load_cmf_matrices
from nikodym.provisioning.cmf.results import (
    CmfProvisionCard,
    CmfProvisionRecord,
    CmfProvisionResult,
)
from nikodym.provisioning.exceptions import ProvisioningInputError
from nikodym.provisioning.ifrs9.config import (
    IfrsEadConfig,
    IfrsLgdConfig,
    IfrsPdConfig,
    IfrsProvisioningConfig,
    IfrsScenarioConfig,
)
from nikodym.provisioning.ifrs9.results import (
    IfrsEclRecord,
    IfrsProvisionCard,
    IfrsProvisionResult,
    IfrsStageRecord,
)
from nikodym.provisioning.internal.config import InternalProvisioningConfig

ROOT_SEED = 20_260_703
# Golden CMF: exposición 1.000.000, categoría A1 -> provisión 360.00000 (SDD-15 §11).
EXPECTED_A1_PROVISION = Decimal("360.00000")

# ── Goldens del end-to-end estándar vs. interno (aritmética a mano, SDD-28) ──────────────────
# Dos operaciones A1 (commercial_individual), mismo grupo homogéneo "banda_alta":
#   op1: exposición 1.000.000, LGD 0,50   |   op2: exposición 3.000.000, LGD 0,60
#
# MÉTODO ESTÁNDAR (CMF B-1, matriz A1 = 0,036 %):
#   1.000.000 · 0,00036 =   360,00000
#   3.000.000 · 0,00036 = 1.080,00000
#   total estándar      = 1.440,00000
EXPECTED_STANDARD_TOTAL = Decimal("1440.00000")
#
# MÉTODO INTERNO (B-1 §3: Exposición · PD · LGD por grupo homogéneo), PD alta (0,02 / 0,10):
#   E   = 1.000.000 + 3.000.000 = 4.000.000
#   PD  = (1M·0,02 + 3M·0,10)/4M = (20.000 + 300.000)/4.000.000 = 0,08
#   LGD = (1M·0,50 + 3M·0,60)/4M = (500.000 + 1.800.000)/4.000.000 = 0,575
#   provisión = 4.000.000 · 0,08 · 0,575 = 4.000.000 · 0,046 = 184.000,00
EXPECTED_INTERNAL_HIGH = Decimal("184000.00")
#   -> max(1.440,00000 ; 184.000,00) = 184.000,00  => muerde el INTERNO
#
# Mismo grupo con PD baja (0,0001 en ambas operaciones):
#   PD = 0,0001 ; LGD = 0,575 ; provisión = 4.000.000 · 0,0001 · 0,575 = 230,00
EXPECTED_INTERNAL_LOW = Decimal("230.00")
#   -> max(1.440,00000 ; 230,00) = 1.440,00000     => muerde el ESTÁNDAR
#   -> rule='use_internal'                          => se reporta 230,00 (el interno)


# ─────────────────────────── contrato del step y registro ───────────────────────────


def test_contrato_step_y_registro() -> None:
    """El step expone el contrato CT-1 exacto de SDD-17 §4 y reenvía eventos como sink."""
    cfg = ProvisioningConfig()
    step = ProvisioningStep.from_config(cfg)
    sink = InMemoryAuditSink()
    step._audit = sink

    assert REGISTRY.resolve("provisioning", "standard") is ProvisioningStep
    assert prov_pkg.ProvisioningStep is ProvisioningStep
    assert step.config is cfg
    assert step.name == "provisioning"
    assert step.provides == tuple(("provisioning", key) for key in PROVISIONING_ARTIFACTS)
    assert PROVISIONING_ARTIFACTS == ("comparison", "summary", "result", "card")
    step.emit(AuditEvent(kind="decision", step="x", payload={"regla": "y"}, ts=datetime.now(UTC)))
    assert sink.events[-1].payload == {"regla": "y"}


# ─────────────────────────── requires dinámicos (CT-1) ───────────────────────────


def test_requires_require_both_exige_ambos() -> None:
    """``require_both=True`` (default) exige los dos ``result`` de los motores."""
    step = ProvisioningStep.from_config(ProvisioningConfig())
    assert step.requires == (
        ("provisioning_cmf", "result"),
        ("provisioning_ifrs9", "result"),
    )


def test_requires_passthrough_ambos_motores_sin_dura() -> None:
    """``require_both=False`` con ambos motores habilitados no impone dura CT-1 (al menos uno)."""
    step = ProvisioningStep.from_config(ProvisioningConfig(require_both=False))
    assert step.requires == ()


def test_requires_solo_fuente_a_cuando_b_desactivada() -> None:
    """``require_both=False`` con ``consume_b=False`` exige solo el ``result`` de la fuente A."""
    step = ProvisioningStep.from_config(ProvisioningConfig(require_both=False, consume_b=False))
    assert step.requires == (("provisioning_cmf", "result"),)


def test_requires_solo_fuente_b_cuando_a_desactivada() -> None:
    """``require_both=False`` con ``consume_a=False`` exige solo el ``result`` de la fuente B."""
    step = ProvisioningStep.from_config(ProvisioningConfig(require_both=False, consume_a=False))
    assert step.requires == (("provisioning_ifrs9", "result"),)


def test_requires_derivan_de_las_fuentes_declaradas() -> None:
    """Los ``requires`` salen de ``source_a``/``source_b``, no de constantes cableadas (SDD-28)."""
    step = ProvisioningStep.from_config(
        ProvisioningConfig(source_a="provisioning_cmf", source_b="provisioning_internal")
    )
    assert step.requires == (
        ("provisioning_cmf", "result"),
        ("provisioning_internal", "result"),
    )
    invertido = ProvisioningStep.from_config(
        ProvisioningConfig(source_a="provisioning_internal", source_b="provisioning_ifrs9")
    )
    assert invertido.requires == (
        ("provisioning_internal", "result"),
        ("provisioning_ifrs9", "result"),
    )


def test_requires_legacy_consume_ifrs9_sigue_funcionando() -> None:
    """El flag deprecado ``consume_ifrs9`` sigue recortando los ``requires`` (retrocompatible)."""
    with pytest.warns(DeprecationWarning):
        cfg = ProvisioningConfig(require_both=False, consume_ifrs9=False)
    assert ProvisioningStep.from_config(cfg).requires == (("provisioning_cmf", "result"),)


# ─────────────────────────── cableado de core.study ───────────────────────────


def test_core_study_cablea_provisioning() -> None:
    """``core.study`` cablea ``provisioning`` después de ambos motores y lo resuelve al step."""
    order = study_module._DEFAULT_DOMAIN_ORDER
    assert order.index("provisioning_ifrs9") < order.index("provisioning")
    assert order.index("provisioning_cmf") < order.index("provisioning")
    assert study_module._DOMAIN_MODULES["provisioning"] == "nikodym.provisioning"
    assert study_module._DOMAIN_CONFIG_CLASSES["provisioning"] == (
        "nikodym.provisioning.config",
        "ProvisioningConfig",
    )

    study = Study(NikodymConfig(provisioning=ProvisioningConfig()))
    assert study._default_step_names() == ["provisioning"]
    assert isinstance(study._resolve_step("provisioning"), ProvisioningStep)


# ─────────────────────────── execute: publica y audita ───────────────────────────


def test_execute_publica_cuatro_artefactos_y_audita() -> None:
    """Con ambos motores presentes, publica las 4 claves y emite el audit trail §9 completo."""
    cmf = _cmf_result(
        [{"row_id": "op1", "portfolio": "commercial", "provision": Decimal("100.00")}]
    )
    ifrs9 = _ifrs9_result([{"row_id": "op1", "portfolio": "commercial", "ecl": 60.165289}])
    cfg = ProvisioningConfig(comparison_level="portfolio")
    study = _study_with_results(cfg, cmf=cmf, ifrs9=ifrs9)
    sink = InMemoryAuditSink()
    study.set_audit_sink(sink)
    step = ProvisioningStep.from_config(study.config.provisioning)
    step._audit = sink

    result = step.execute(study, np.random.default_rng(ROOT_SEED))

    assert isinstance(result, ProvisionOrchestrationResult)
    for key in PROVISIONING_ARTIFACTS:
        assert study.artifacts.has("provisioning", key)
    # Golden del máximo: cmf 100.00 > ifrs9 60.165289 -> muerde el piso CMF.
    assert result.records[0].reported_provision == Decimal("100.00")
    assert result.records[0].binding == "cmf"
    assert study.artifacts.get("provisioning", "card").total_reported_provision == Decimal("100.00")
    stored = study.artifacts.get("provisioning", "result")
    assert stored.card.total_reported_provision == Decimal("100.00")
    assert tuple(study.artifacts.get("provisioning", "comparison").columns) == (
        "cell_id",
        "level",
        "source_a",
        "source_b",
        "provision_a",
        "provision_b",
        "reported_provision",
        "binding",
        "coverage",
        "warning_codes",
    )

    reglas = {event.payload["regla"] for event in sink.events if event.kind == "decision"}
    assert reglas == {
        "provisioning_level",
        "provisioning_engines",
        "provisioning_reconciliation",
        "provisioning_binding",
        "provisioning_coverage",
        "provisioning_falta_dato",
    }


def test_execute_no_muta_artefacto_publicado() -> None:
    """El comparativo publicado es copia defensiva: mutar el resultado no toca el ArtifactStore."""
    cmf = _cmf_result(
        [{"row_id": "op1", "portfolio": "commercial", "provision": Decimal("100.00")}]
    )
    ifrs9 = _ifrs9_result([{"row_id": "op1", "portfolio": "commercial", "ecl": 40.0}])
    cfg = ProvisioningConfig(comparison_level="portfolio")
    study = _study_with_results(cfg, cmf=cmf, ifrs9=ifrs9)
    result = ProvisioningStep.from_config(cfg).execute(study, np.random.default_rng(ROOT_SEED))

    mutable = result.comparison
    mutable.loc[0, "reported_provision"] = Decimal("0")
    assert study.artifacts.get("provisioning", "comparison").loc[0, "reported_provision"] == (
        Decimal("100.00")
    )


def test_passthrough_solo_cmf_step() -> None:
    """``require_both=False`` con solo el ``result`` CMF presente degrada a passthrough marcado."""
    cmf = _cmf_result([{"row_id": "op1", "portfolio": "commercial", "provision": Decimal("55")}])
    cfg = ProvisioningConfig(comparison_level="portfolio", require_both=False)
    study = _study_with_results(cfg, cmf=cmf, ifrs9=None)

    result = ProvisioningStep.from_config(cfg).execute(study, np.random.default_rng(ROOT_SEED))

    assert result.card.engines_present == ("cmf",)
    assert result.records[0].coverage == "cmf_only"
    assert result.records[0].binding == "cmf_only"
    assert result.term_structure() is None
    assert study.artifacts.get("provisioning", "result").card.engines_present == ("cmf",)


# ─────────────────────────── CT-1: artefactos requeridos ───────────────────────────


def test_ct1_falta_result_cmf() -> None:
    """``require_both=True`` sin el ``result`` CMF -> ``ArtifactNotFoundError`` (CT-1)."""
    ifrs9 = _ifrs9_result([{"row_id": "op1", "portfolio": "commercial", "ecl": 40.0}])
    study = _study_with_results(ProvisioningConfig(), cmf=None, ifrs9=ifrs9)
    step = ProvisioningStep.from_config(ProvisioningConfig())
    with pytest.raises(ArtifactNotFoundError, match=r"\('provisioning_cmf', 'result'\)"):
        step.execute(study, np.random.default_rng(ROOT_SEED))


def test_ct1_falta_result_ifrs9() -> None:
    """``require_both=True`` sin el ``result`` IFRS 9 -> ``ArtifactNotFoundError`` (CT-1)."""
    cmf = _cmf_result([{"row_id": "op1", "portfolio": "commercial", "provision": Decimal("10")}])
    study = _study_with_results(ProvisioningConfig(), cmf=cmf, ifrs9=None)
    step = ProvisioningStep.from_config(ProvisioningConfig())
    with pytest.raises(ArtifactNotFoundError, match=r"\('provisioning_ifrs9', 'result'\)"):
        step.execute(study, np.random.default_rng(ROOT_SEED))


def test_execute_sin_motores_presentes_falla() -> None:
    """``require_both=False`` sin ningún ``result`` presente -> ``ProvisioningInputError``."""
    cfg = ProvisioningConfig(require_both=False)
    study = _study_with_results(cfg, cmf=None, ifrs9=None)
    step = ProvisioningStep.from_config(cfg)
    with pytest.raises(ProvisioningInputError, match="al menos un motor"):
        step.execute(study, np.random.default_rng(ROOT_SEED))


# ─────────────────────────── integración end-to-end (ambos motores) ───────────────────────────


def test_end_to_end_tres_motores_study_run() -> None:
    """``Study.run`` real: cmf + ifrs9 alimentan provisioning; el piso CMF muerde (golden 360)."""
    study = _study_tres_motores()

    study.run()

    card = study.artifacts.get("provisioning", "card")
    assert card.engines_present == ("cmf", "ifrs9")
    assert card.comparison_level == "total"
    assert card.total_reported_provision == EXPECTED_A1_PROVISION
    assert card.total_provision_a == EXPECTED_A1_PROVISION
    assert card.n_binding_a == 1
    comparison = study.artifacts.get("provisioning", "comparison")
    assert comparison.loc[0, "cell_id"] == "TOTAL"
    assert comparison.loc[0, "reported_provision"] == EXPECTED_A1_PROVISION
    assert comparison.loc[0, "binding"] == "cmf"
    # El ECL IFRS 9 (< estándar CMF) queda registrado en el comparativo y es finito.
    assert 0.0 < float(comparison.loc[0, "provision_b"]) < float(EXPECTED_A1_PROVISION)
    assert study.artifacts.get("provisioning", "result").term_structure() is not None


def test_determinismo_dos_ejecuciones() -> None:
    """Dos ejecuciones con los mismos insumos publican comparison/summary equivalentes."""
    cmf = _cmf_result(
        [
            {"row_id": "op1", "portfolio": "commercial", "provision": Decimal("100")},
            {"row_id": "op2", "portfolio": "consumer", "provision": Decimal("10")},
        ],
        total=Decimal("110"),
    )
    ifrs9 = _ifrs9_result(
        [
            {"row_id": "op1", "portfolio": "commercial", "ecl": 10.0},
            {"row_id": "op2", "portfolio": "consumer", "ecl": 100.0},
        ],
        total=110.0,
    )
    cfg = ProvisioningConfig(comparison_level="portfolio")

    primera = ProvisioningStep.from_config(cfg).execute(
        _study_with_results(cfg, cmf=cmf, ifrs9=ifrs9), np.random.default_rng(ROOT_SEED)
    )
    segunda = ProvisioningStep.from_config(cfg).execute(
        _study_with_results(cfg, cmf=cmf, ifrs9=ifrs9), np.random.default_rng(ROOT_SEED)
    )

    assert_frame_equal(primera.comparison, segunda.comparison)
    assert_frame_equal(primera.summary, segunda.summary)
    assert primera.records == segunda.records
    assert primera.card == segunda.card


# ─────────── end-to-end REAL: estándar vs. interno, la regla del B-1 (SDD-28) ───────────


def test_end_to_end_estandar_vs_interno_study_run_gana_el_interno() -> None:
    """``Study.run()`` real: cmf + internal alimentan provisioning con la regla del máximo.

    Golden a mano: estándar = 1.440,00000 (dos A1) ; interno = 184.000,00 (4M · 0,08 · 0,575).
    El máximo es el interno -> la provisión a constituir es la del modelo del banco.
    """
    study = _study_estandar_e_interno()

    study.run()

    assert study.run_context.status == "done"
    estandar = study.artifacts.get("provisioning_cmf", "card").total_provision_amount
    interno = study.artifacts.get("provisioning_internal", "card").total_internal_provision
    assert estandar == EXPECTED_STANDARD_TOTAL
    assert interno == EXPECTED_INTERNAL_HIGH

    card = study.artifacts.get("provisioning", "card")
    assert card.engines_present == ("cmf", "internal")
    assert card.rule == "max"
    assert card.comparison_level == "total"  # el nivel que fija la norma (entidad)
    assert card.total_provision_a == EXPECTED_STANDARD_TOTAL
    assert card.total_provision_b == EXPECTED_INTERNAL_HIGH
    assert card.total_reported_provision == max(EXPECTED_STANDARD_TOTAL, EXPECTED_INTERNAL_HIGH)
    assert card.total_reported_provision == EXPECTED_INTERNAL_HIGH
    assert card.binding == "internal"
    assert card.internal_method == "pd_lgd"

    comparison = study.artifacts.get("provisioning", "comparison")
    assert comparison.loc[0, "cell_id"] == "TOTAL"
    assert comparison.loc[0, "source_a"] == "cmf"
    assert comparison.loc[0, "source_b"] == "internal"
    assert comparison.loc[0, "provision_a"] == EXPECTED_STANDARD_TOTAL
    assert comparison.loc[0, "provision_b"] == EXPECTED_INTERNAL_HIGH
    assert comparison.loc[0, "reported_provision"] == EXPECTED_INTERNAL_HIGH
    assert comparison.loc[0, "binding"] == "internal"


def test_end_to_end_rule_use_internal_reporta_el_interno_menor() -> None:
    """Con el estándar MAYOR que el interno, ``max`` reporta 1.440,00000 y ``use_internal`` 230,00.

    Mismos insumos, dos reglas: es la prueba de que ``rule`` no es un enum decorativo. La norma
    (B-1, hoja 10-11) permite constituir según el método interno cuando está evaluado y no objetado.
    """
    pd_baja = pd.DataFrame(
        {"pd_calibrated": [0.0001, 0.0001]}, index=pd.Index(["op1", "op2"], name="loan_id")
    )

    por_maximo = _study_estandar_e_interno(pd_frame=pd_baja)
    por_maximo.run()
    card_max = por_maximo.artifacts.get("provisioning", "card")
    assert card_max.total_provision_a == EXPECTED_STANDARD_TOTAL
    assert card_max.total_provision_b == EXPECTED_INTERNAL_LOW
    assert card_max.total_reported_provision == EXPECTED_STANDARD_TOTAL  # muerde el estándar
    assert card_max.binding == "cmf"

    por_interno = _study_estandar_e_interno(pd_frame=pd_baja, rule="use_internal")
    por_interno.run()
    card_interno = por_interno.artifacts.get("provisioning", "card")
    assert card_interno.rule == "use_internal"
    # El estándar es MAYOR y aun así se reporta el interno: la regla manda sobre el máximo.
    assert card_interno.total_provision_a == EXPECTED_STANDARD_TOTAL
    assert card_interno.total_reported_provision == EXPECTED_INTERNAL_LOW
    assert card_interno.total_reported_provision < card_max.total_reported_provision
    assert card_interno.binding == "internal"
    assert "no objetados" in card_interno.regulatory_sources[0]


# ─────────────────────────── helpers internos ───────────────────────────


def test_resolve_as_of_date_ramas() -> None:
    """``_resolve_as_of_date`` hereda la fecha, exige una sola y falla sin motores."""
    cmf = _cmf_result([{"row_id": "op1", "portfolio": "commercial", "provision": Decimal("10")}])
    ifrs9 = _ifrs9_result([{"row_id": "op1", "portfolio": "commercial", "ecl": 10.0}])
    assert step_module._resolve_as_of_date(cmf, ifrs9) == "2026-01-31"
    assert step_module._resolve_as_of_date(cmf, None) == "2026-01-31"
    assert step_module._resolve_as_of_date(None, ifrs9) == "2026-01-31"

    with pytest.raises(ProvisioningInputError, match="al menos un motor"):
        step_module._resolve_as_of_date(None, None)

    ifrs9_otra_fecha = _ifrs9_result(
        [{"row_id": "op1", "portfolio": "commercial", "ecl": 10.0}], as_of="2026-02-28"
    )
    with pytest.raises(ProvisioningInputError, match="fechas de cálculo distintas"):
        step_module._resolve_as_of_date(cmf, ifrs9_otra_fecha)


def test_provisioning_config_from_study_ramas() -> None:
    """``_provisioning_config_from_study`` coacciona dict, respeta None e instancia."""
    fallback = ProvisioningConfig()
    dict_study = SimpleNamespace(
        config=SimpleNamespace(provisioning={"comparison_level": "portfolio"})
    )
    resuelto = step_module._provisioning_config_from_study(dict_study, fallback=fallback)
    assert resuelto.comparison_level == "portfolio"

    none_study = SimpleNamespace(config=SimpleNamespace(provisioning=None))
    assert step_module._provisioning_config_from_study(none_study, fallback=fallback) is fallback

    inst_study = SimpleNamespace(config=SimpleNamespace(provisioning=fallback))
    assert step_module._provisioning_config_from_study(inst_study, fallback=fallback) is fallback


def test_load_engine_result_ramas() -> None:
    """``_load_engine_result`` respeta ``consume`` y la presencia en el ArtifactStore."""
    cmf = _cmf_result([{"row_id": "op1", "portfolio": "commercial", "provision": Decimal("10")}])
    study = _study_with_results(ProvisioningConfig(require_both=False), cmf=cmf, ifrs9=None)
    assert step_module._load_engine_result(study, "provisioning_cmf", consume=False) is None
    assert step_module._load_engine_result(study, "provisioning_ifrs9", consume=True) is None
    cargado = step_module._load_engine_result(study, "provisioning_cmf", consume=True)
    assert cargado is not None
    assert cargado.card.total_provision_amount == Decimal("10")


# ─────────────────────────── import liviano ───────────────────────────


def test_import_liviano_subprocess() -> None:
    """``import nikodym.core`` no arrastra provisioning; importarlo registra el step sin pandas."""
    code = textwrap.dedent(
        """
        import sys
        import nikodym.core
        assert not [
            m for m in ("nikodym.provisioning", "pandas", "pandera", "pyarrow")
            if m in sys.modules
        ], [m for m in sys.modules if m.startswith("nikodym.provisioning")]

        import nikodym.provisioning
        from nikodym.core.registry import REGISTRY
        assert REGISTRY.resolve("provisioning", "standard").__name__ == "ProvisioningStep"
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


# ─────────────────────────── factories ───────────────────────────


def _study_with_results(
    cfg: ProvisioningConfig,
    *,
    cmf: CmfProvisionResult | None,
    ifrs9: IfrsProvisionResult | None,
) -> Study:
    """``Study`` con los ``result`` de los motores preinyectados según corresponda."""
    study = Study(NikodymConfig(provisioning=cfg))
    if cmf is not None:
        study.artifacts.set("provisioning_cmf", "result", cmf)
    if ifrs9 is not None:
        study.artifacts.set("provisioning_ifrs9", "result", ifrs9)
    return study


def _ifrs9_step_config() -> IfrsProvisioningConfig:
    """Config IFRS 9 del end-to-end: survival, ttc_only, EAD/LGD provistas, horizonte 12m=1."""
    return IfrsProvisioningConfig(
        portfolio_col="portfolio",
        pd=IfrsPdConfig(
            term_structure_source="survival", pit_mode="ttc_only", horizon_12m_periods=1
        ),
        lgd=IfrsLgdConfig(method="provided"),
        ead=IfrsEadConfig(method="provided"),
        scenarios=IfrsScenarioConfig(source="single"),
    )


def _study_tres_motores() -> Study:
    """``Study`` con un frame compartido y term-structure para correr cmf + ifrs9 + provisioning."""
    frame = pd.DataFrame(
        [
            {
                "as_of_date": "2026-01-31",
                "cmf_portfolio": "commercial_individual",
                "cmf_category": "A1",
                "exposure_amount": 1_000_000,
                "portfolio": "retail",
                "ead": 1000.0,
                "lgd": 0.5,
                "eir": 0.10,
                "days_past_due": 0,
            }
        ],
        index=pd.Index(["loan-1"], name="loan_id"),
    )
    term_structure = pd.DataFrame(
        {
            "row_id": ["loan-1", "loan-1"],
            "period": [1, 2],
            "time_value": [1.0, 2.0],
            "survival": [0.90, 0.82],
            "pd_marginal": [0.10, 0.08],
            "pd_cumulative": [0.10, 0.18],
            "scenario": [None, None],
            "warning_codes": [(), ()],
        }
    )
    config = NikodymConfig(
        provisioning_cmf=CmfProvisioningConfig(),
        provisioning_ifrs9=_ifrs9_step_config(),
        provisioning=ProvisioningConfig(),
    )
    study = Study(config)
    study.artifacts.set("data", "frame", frame)
    study.artifacts.set("survival", "term_structure", term_structure)
    return study


def _study_estandar_e_interno(*, pd_frame: pd.DataFrame | None = None, rule: str = "max") -> Study:
    """``Study`` con ``data.frame`` + PD calibrada para correr cmf + internal + provisioning."""
    frame = pd.DataFrame(
        [
            {
                "as_of_date": "2026-01-31",
                "cmf_portfolio": "commercial_individual",
                "cmf_category": "A1",
                "exposure_amount": 1_000_000,
                "grupo": "banda_alta",
                "lgd": 0.50,
            },
            {
                "as_of_date": "2026-01-31",
                "cmf_portfolio": "commercial_individual",
                "cmf_category": "A1",
                "exposure_amount": 3_000_000,
                "grupo": "banda_alta",
                "lgd": 0.60,
            },
        ],
        index=pd.Index(["op1", "op2"], name="loan_id"),
    )
    calibrada = (
        pd_frame
        if pd_frame is not None
        else pd.DataFrame(
            {"pd_calibrated": [0.02, 0.10]}, index=pd.Index(["op1", "op2"], name="loan_id")
        )
    )
    config = NikodymConfig(
        provisioning_cmf=CmfProvisioningConfig(),
        provisioning_internal=InternalProvisioningConfig(grouping="provided", group_col="grupo"),
        provisioning=ProvisioningConfig(
            source_a="provisioning_cmf",
            source_b="provisioning_internal",
            rule=rule,  # type: ignore[arg-type]
        ),
    )
    study = Study(config)
    study.artifacts.set("data", "frame", frame)
    study.artifacts.set("calibration", "calibrated_pd_frame", calibrada)
    return study


@dataclass(frozen=True)
class _MatrixConfig:
    """Config estructural mínima compatible con ``CmfMatrixConfigLike``."""

    active_version: str = "cmf_b1_b3_2025_01"
    require_verified_rows: bool = True
    fail_on_source_mismatch: bool = True


_BUNDLE: CmfMatrixBundle = load_cmf_matrices(_MatrixConfig())


def _cmf_result(rows: list[dict[str, Any]], *, total: Decimal | None = None) -> CmfProvisionResult:
    """Construye un ``CmfProvisionResult`` sintético (montos ``Decimal``) por cartera/total."""
    total_provision = (
        total if total is not None else sum((row["provision"] for row in rows), Decimal("0"))
    )
    detail = pd.DataFrame(
        {
            "portfolio": [row["portfolio"] for row in rows],
            "method": ["standard_b1"] * len(rows),
            "cmf_category": ["A1"] * len(rows),
            "matrix_id": ["m"] * len(rows),
            "matrix_row_id": ["r"] * len(rows),
            "direct_exposure_amount": [Decimal("0")] * len(rows),
            "contingent_exposure_amount": [Decimal("0")] * len(rows),
            "exposure_amount": [Decimal("0")] * len(rows),
            "pd_source_value": [None] * len(rows),
            "pi_percent": [None] * len(rows),
            "pdi_percent": [None] * len(rows),
            "pe_percent": [Decimal("0")] * len(rows),
            "provision_amount": [row["provision"] for row in rows],
            "guarantee_treatment": ["none"] * len(rows),
            "ccf_percent": [None] * len(rows),
            "warning_codes": [()] * len(rows),
            "source_reference": ["src"] * len(rows),
            "matrix_version": ["cmf_b1_b3_2025_01"] * len(rows),
        },
        index=pd.Index([row["row_id"] for row in rows], name="row_id"),
    )
    summary = pd.DataFrame(
        {
            "portfolio": ["x"],
            "method": ["standard_b1"],
            "cmf_category": ["A1"],
            "n_rows": [len(rows)],
            "total_exposure_amount": [Decimal("0")],
            "total_provision_amount": [total_provision],
            "weighted_pe_percent": [Decimal("0")],
            "matrix_version": ["cmf_b1_b3_2025_01"],
            "warning_codes": [()],
        },
        index=pd.Index(["x|standard_b1|A1"], name="summary_id"),
    )
    records = tuple(
        CmfProvisionRecord(
            row_id=row["row_id"],
            portfolio=row["portfolio"],
            method="standard_b1",
            exposure_amount=Decimal("0"),
            direct_exposure_amount=Decimal("0"),
            contingent_exposure_amount=Decimal("0"),
            pi_percent=None,
            pdi_percent=None,
            pe_percent=Decimal("0"),
            provision_amount=row["provision"],
            matrix_id="m",
            matrix_row_id="r",
            cmf_category="A1",
        )
        for row in rows
    )
    card = CmfProvisionCard(
        matrix_version="cmf_b1_b3_2025_01",
        as_of_date="2026-01-31",
        n_rows=len(rows),
        total_exposure_amount=Decimal("0"),
        total_provision_amount=total_provision,
        portfolios=(),
        regulatory_sources=("CNC B-1 §2.1",),
    )
    return CmfProvisionResult(
        detail=detail, summary=summary, records=records, card=card, matrix_bundle=_BUNDLE
    )


def _ifrs9_result(
    rows: list[dict[str, Any]], *, total: float | None = None, as_of: str = "2026-01-31"
) -> IfrsProvisionResult:
    """Construye un ``IfrsProvisionResult`` sintético (ECL ``float``, colapsado por escenario)."""
    n = len(rows)
    ecls = [float(row["ecl"]) for row in rows]
    total_ecl = total if total is not None else sum(ecls)
    staging = pd.DataFrame(
        {
            "row_id": [row["row_id"] for row in rows],
            "portfolio": [row["portfolio"] for row in rows],
            "stage": [1] * n,
            "days_past_due": [0] * n,
            "pd_life_current": [0.02] * n,
            "pd_life_origination": [0.02] * n,
            "sicr_triggers": [()] * n,
            "low_credit_risk_exempt": [False] * n,
            "warning_codes": [()] * n,
        }
    )
    detail = pd.DataFrame(
        {
            "row_id": [row["row_id"] for row in rows],
            "portfolio": [row["portfolio"] for row in rows],
            "stage": [1] * n,
            "ead": [1000.0] * n,
            "lgd": [0.4] * n,
            "eir": [0.1] * n,
            "pd_12m": [0.1] * n,
            "pd_life": [0.1] * n,
            "ecl_12m": ecls,
            "ecl_lifetime": ecls,
            "ecl_reported": ecls,
            "scenario_weights": ['{"base": 1.0}'] * n,
            "pd_basis": ["pit"] * n,
            "warning_codes": [()] * n,
        }
    )
    ecl_term_structure = pd.DataFrame(
        {
            "row_id": [row["row_id"] for row in rows],
            "scenario": ["base"] * n,
            "period": [1] * n,
            "time_value": [1.0] * n,
            "pd_marginal": [0.1] * n,
            "lgd": [0.4] * n,
            "ead": [1000.0] * n,
            "discount_factor": [0.9] * n,
            "ecl_marginal": ecls,
        }
    )
    summary = pd.DataFrame(
        {
            "portfolio": [rows[0]["portfolio"]],
            "stage": [1],
            "scenario": ["base"],
            "n_rows": [n],
            "total_ead": [1000.0 * n],
            "total_ecl_reported": [sum(ecls)],
            "coverage_ratio": [0.0],
            "warning_codes": [()],
        }
    )
    stage_records = tuple(
        IfrsStageRecord(
            row_id=row["row_id"],
            stage=1,
            days_past_due=0,
            pd_life_current=0.02,
            pd_life_origination=0.02,
        )
        for row in rows
    )
    ecl_records = tuple(
        IfrsEclRecord(
            row_id=row["row_id"],
            stage=1,
            ead=1000.0,
            lgd=0.4,
            eir=0.1,
            ecl_12m=float(row["ecl"]),
            ecl_lifetime=float(row["ecl"]),
            ecl_reported=float(row["ecl"]),
            scenario_weights={"base": 1.0},
            pd_basis="pit",
        )
        for row in rows
    )
    card = IfrsProvisionCard(
        as_of_date=as_of,
        term_structure_source="survival",
        pit_mode="consume_pit",
        n_rows=n,
        n_stage1=n,
        n_stage2=0,
        n_stage3=0,
        total_ead=1000.0 * n,
        total_ecl_reported=total_ecl,
        scenarios=("base",),
        scenario_weights={"base": 1.0},
        dependency_versions={"pandas": "2.2.0"},
    )
    return IfrsProvisionResult(
        staging=staging,
        detail=detail,
        ecl_term_structure=ecl_term_structure,
        summary=summary,
        stage_records=stage_records,
        ecl_records=ecl_records,
        card=card,
    )
