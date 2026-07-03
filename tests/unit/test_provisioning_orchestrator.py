"""Tests del ``ProvisioningOrchestrator`` (SDD-17 §6/§7/§11): máximo CMF vs IFRS 9 con goldens.

Cubre los golden verificables a mano del SDD §11 (gana CMF, gana IFRS 9, empate, nivel ``total`` con
carteras reales, no-linealidad por nivel, reconciliación ``Decimal``/``float`` en el borde de
tolerancia), la política de cobertura parcial, el passthrough marcado, la alineación por operación,
el crosswalk de carteras, el redondeo, la delegación de ``term_structure()`` y la no mutación.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

import nikodym.provisioning.orchestrator as orch
from nikodym.core.audit import InMemoryAuditSink
from nikodym.core.exceptions import MissingDependencyError
from nikodym.provisioning import (
    ProvisioningConfig,
    ProvisioningOrchestrator,
    ProvisionOrchestrationResult,
)
from nikodym.provisioning.cmf.matrices import CmfMatrixBundle, load_cmf_matrices
from nikodym.provisioning.cmf.results import (
    CmfProvisionCard,
    CmfProvisionRecord,
    CmfProvisionResult,
)
from nikodym.provisioning.exceptions import (
    ProvisioningAlignmentError,
    ProvisioningConfigError,
    ProvisioningCoverageError,
    ProvisioningInputError,
)
from nikodym.provisioning.ifrs9.results import (
    IfrsEclRecord,
    IfrsProvisionCard,
    IfrsProvisionResult,
    IfrsStageRecord,
)

# ─────────────────────────── goldens del máximo (SDD §11) ───────────────────────────


def test_golden_gana_cmf() -> None:
    """cmf=100.0 > ifrs9=60.165289 (ECL golden SDD-16) -> reported=100.0, binding='cmf'."""
    cmf = _cmf_result(
        [{"row_id": "op1", "portfolio": "commercial", "provision": Decimal("100.00")}]
    )
    ifrs9 = _ifrs9_result([{"row_id": "op1", "portfolio": "commercial", "ecl": 60.165289}])
    result = _orchestrator("portfolio").compare(cmf=cmf, ifrs9=ifrs9, as_of_date="2026-01-31")

    record = result.records[0]
    assert record.cell_id == "commercial"
    assert record.cmf_provision == Decimal("100.00")
    assert record.ifrs9_ecl == 60.165289
    assert record.reported_provision == Decimal("100.00")
    assert record.binding == "cmf"
    assert record.coverage == "both"
    assert result.card.total_reported_provision == Decimal("100.00")
    assert result.card.n_binding_cmf == 1


def test_golden_gana_ifrs9() -> None:
    """ifrs9=73.0 > cmf=50.0 -> reported=73.0, binding='ifrs9'."""
    cmf = _cmf_result([{"row_id": "op1", "portfolio": "commercial", "provision": Decimal("50.0")}])
    ifrs9 = _ifrs9_result([{"row_id": "op1", "portfolio": "commercial", "ecl": 73.0}])
    record = (
        _orchestrator("portfolio").compare(cmf=cmf, ifrs9=ifrs9, as_of_date="2026-01-31").records[0]
    )

    assert record.reported_provision == Decimal("73.0")
    assert record.binding == "ifrs9"


def test_golden_empate() -> None:
    """cmf == ifrs9 == 73.0 dentro de tie_tolerance -> reported=73.0, binding='tie'."""
    cmf = _cmf_result([{"row_id": "op1", "portfolio": "commercial", "provision": Decimal("73.0")}])
    ifrs9 = _ifrs9_result([{"row_id": "op1", "portfolio": "commercial", "ecl": 73.0}])
    record = (
        _orchestrator("portfolio").compare(cmf=cmf, ifrs9=ifrs9, as_of_date="2026-01-31").records[0]
    )

    assert record.binding == "tie"
    assert record.reported_provision == Decimal("73.0")


def test_golden_total_carteras_reales() -> None:
    """Nivel total: CMF B4 provision=438750 (golden SDD-15) vs ECL 60.165289 -> muerde el piso."""
    cmf = _cmf_result(
        [{"row_id": "op1", "portfolio": "commercial", "provision": Decimal("438750")}],
        total=Decimal("438750"),
    )
    ifrs9 = _ifrs9_result(
        [{"row_id": "op1", "portfolio": "commercial", "ecl": 60.165289}], total=60.165289
    )
    result = _orchestrator("total").compare(cmf=cmf, ifrs9=ifrs9, as_of_date="2026-01-31")

    record = result.records[0]
    assert record.cell_id == "TOTAL"
    assert record.level == "total"
    assert record.cmf_provision == Decimal("438750")
    assert record.reported_provision == Decimal("438750")
    assert record.binding == "cmf"


def test_no_linealidad_por_nivel() -> None:
    """Σ max(cmf_c, ifrs9_c) >= max(Σ cmf, Σ ifrs9): el grano fino no baja la plata (D-PROV-2)."""
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

    por_cartera = _orchestrator("portfolio").compare(cmf=cmf, ifrs9=ifrs9, as_of_date="2026-01-31")
    total = _orchestrator("total").compare(cmf=cmf, ifrs9=ifrs9, as_of_date="2026-01-31")

    assert [r.cell_id for r in por_cartera.records] == ["commercial", "consumer"]
    assert [r.reported_provision for r in por_cartera.records] == [Decimal("100"), Decimal("100")]
    assert por_cartera.card.total_reported_provision == Decimal("200")
    assert total.card.total_reported_provision == Decimal("110")
    assert por_cartera.card.total_reported_provision >= total.card.total_reported_provision


def test_reconciliacion_decimal_float_borde_tolerancia() -> None:
    """cmf=Decimal('100.00') vs ifrs9=100.0000000004: tie con tol 1e-6; gana IFRS 9 sin tol."""
    cmf = _cmf_result([{"row_id": "op1", "portfolio": "c", "provision": Decimal("100.00")}])
    ifrs9 = _ifrs9_result([{"row_id": "op1", "portfolio": "c", "ecl": 100.0000000004}])

    con_tolerancia = (
        _orchestrator("portfolio", tie_tolerance=1e-6)
        .compare(cmf=cmf, ifrs9=ifrs9, as_of_date="2026-01-31")
        .records[0]
    )
    assert con_tolerancia.binding == "tie"
    # El monto CMF original NO se recuantiza en el registro (D-PROV-4).
    assert con_tolerancia.cmf_provision == Decimal("100.00")
    assert con_tolerancia.ifrs9_ecl == 100.0000000004

    sin_tolerancia = (
        _orchestrator("portfolio", tie_tolerance=0.0)
        .compare(cmf=cmf, ifrs9=ifrs9, as_of_date="2026-01-31")
        .records[0]
    )
    assert sin_tolerancia.binding == "ifrs9"


# ─────────────────────────── cobertura parcial (SDD §8/§11) ───────────────────────────


def test_cobertura_parcial_use_available() -> None:
    """Celda solo-CMF y solo-IFRS 9 con use_available -> reported del disponible, marcado *_only."""
    cmf = _cmf_result([{"row_id": "op1", "portfolio": "commercial", "provision": Decimal("30")}])
    ifrs9 = _ifrs9_result([{"row_id": "op2", "portfolio": "consumer", "ecl": 42.0}])
    result = _orchestrator("portfolio").compare(cmf=cmf, ifrs9=ifrs9, as_of_date="2026-01-31")

    por_celda = {r.cell_id: r for r in result.records}
    assert por_celda["commercial"].coverage == "cmf_only"
    assert por_celda["commercial"].binding == "cmf_only"
    assert por_celda["commercial"].reported_provision == Decimal("30")
    assert por_celda["commercial"].ifrs9_ecl is None
    assert por_celda["consumer"].coverage == "ifrs9_only"
    assert por_celda["consumer"].binding == "ifrs9_only"
    assert por_celda["consumer"].reported_provision == Decimal("42.0")
    assert por_celda["consumer"].cmf_provision is None
    assert any("sin contraparte" in nota for nota in result.card.falta_dato)


def test_cobertura_parcial_fail() -> None:
    """Celda cubierta por un solo motor con coverage_policy='fail' -> ProvisioningCoverageError."""
    cmf = _cmf_result([{"row_id": "op1", "portfolio": "commercial", "provision": Decimal("30")}])
    ifrs9 = _ifrs9_result([{"row_id": "op2", "portfolio": "consumer", "ecl": 42.0}])
    with pytest.raises(ProvisioningCoverageError, match="coverage_policy='fail'"):
        _orchestrator("portfolio", coverage_policy="fail").compare(
            cmf=cmf, ifrs9=ifrs9, as_of_date="2026-01-31"
        )


def test_cobertura_parcial_treat_missing_as_zero() -> None:
    """treat_missing_as_zero imputa 0 al faltante -> reported=max(disponible, 0), coverage both."""
    cmf = _cmf_result([{"row_id": "op1", "portfolio": "commercial", "provision": Decimal("30")}])
    ifrs9 = _ifrs9_result([{"row_id": "op2", "portfolio": "consumer", "ecl": 42.0}])
    result = _orchestrator("portfolio", coverage_policy="treat_missing_as_zero").compare(
        cmf=cmf, ifrs9=ifrs9, as_of_date="2026-01-31"
    )

    por_celda = {r.cell_id: r for r in result.records}
    # Cartera solo-CMF: ECL imputado a 0 -> gana CMF.
    assert por_celda["commercial"].coverage == "both"
    assert por_celda["commercial"].ifrs9_ecl == 0.0
    assert por_celda["commercial"].reported_provision == Decimal("30")
    assert por_celda["commercial"].binding == "cmf"
    # Cartera solo-IFRS 9: CMF imputado a 0 -> gana IFRS 9.
    assert por_celda["consumer"].coverage == "both"
    assert por_celda["consumer"].cmf_provision == Decimal("0")
    assert por_celda["consumer"].binding == "ifrs9"
    assert any("imputó 0" in nota for nota in result.card.falta_dato)


# ─────────────────────────── passthrough y flags de consumo ───────────────────────────


def test_passthrough_solo_cmf() -> None:
    """require_both=False con solo CMF -> passthrough marcado cmf_only y FALTA-DATO de piso."""
    cmf = _cmf_result([{"row_id": "op1", "portfolio": "commercial", "provision": Decimal("55")}])
    result = _orchestrator("portfolio", require_both=False).compare(
        cmf=cmf, ifrs9=None, as_of_date="2026-01-31"
    )

    record = result.records[0]
    assert record.coverage == "cmf_only"
    assert record.binding == "cmf_only"
    assert record.warnings == ("piso_incompleto",)
    assert result.card.engines_present == ("cmf",)
    assert result.card.ifrs9_term_structure_source is None
    assert result.card.cmf_matrix_version == "cmf_b1_b3_2025_01"
    assert result.term_structure() is None
    assert any("piso incompleto" in nota for nota in result.card.falta_dato)


def test_passthrough_solo_ifrs9_delegacion_term_structure() -> None:
    """require_both=False con solo IFRS 9 -> ifrs9_only y term_structure() delega en el ECL."""
    ifrs9 = _ifrs9_result([{"row_id": "op1", "portfolio": "consumer", "ecl": 42.0}])
    result = _orchestrator("portfolio", require_both=False).compare(
        cmf=None, ifrs9=ifrs9, as_of_date="2026-01-31"
    )

    record = result.records[0]
    assert record.coverage == "ifrs9_only"
    assert record.binding == "ifrs9_only"
    assert result.card.engines_present == ("ifrs9",)
    assert result.card.cmf_matrix_version is None
    delegada = result.term_structure()
    assert delegada is not None
    assert_frame_equal(delegada, ifrs9.term_structure())


def test_consume_flags_desactivan_un_motor() -> None:
    """consume_ifrs9=False ignora el resultado IFRS 9 presente y degrada a passthrough CMF."""
    cmf = _cmf_result([{"row_id": "op1", "portfolio": "commercial", "provision": Decimal("55")}])
    ifrs9 = _ifrs9_result([{"row_id": "op1", "portfolio": "commercial", "ecl": 999.0}])
    result = _orchestrator("portfolio", require_both=False, consume_ifrs9=False).compare(
        cmf=cmf, ifrs9=ifrs9, as_of_date="2026-01-31"
    )

    assert result.card.engines_present == ("cmf",)
    assert result.records[0].reported_provision == Decimal("55")


# ─────────────────────────── errores de motores ───────────────────────────


def test_ambos_motores_ausentes() -> None:
    """Sin CMF ni IFRS 9 no hay nada que orquestar."""
    with pytest.raises(ProvisioningInputError, match="al menos un motor"):
        _orchestrator("total", require_both=False).compare(
            cmf=None, ifrs9=None, as_of_date="2026-01-31"
        )


def test_require_both_falta_un_motor() -> None:
    """require_both=True exige ambos resultados; falta uno -> ProvisioningInputError."""
    cmf = _cmf_result([{"row_id": "op1", "portfolio": "commercial", "provision": Decimal("10")}])
    ifrs9 = _ifrs9_result([{"row_id": "op1", "portfolio": "commercial", "ecl": 10.0}])
    with pytest.raises(ProvisioningInputError, match="falta el resultado de IFRS 9"):
        _orchestrator("total").compare(cmf=cmf, ifrs9=None, as_of_date="2026-01-31")
    with pytest.raises(ProvisioningInputError, match="falta el resultado de CMF"):
        _orchestrator("total").compare(cmf=None, ifrs9=ifrs9, as_of_date="2026-01-31")


def test_as_of_date_vacio() -> None:
    """compare exige una fecha de cálculo no vacía."""
    cmf = _cmf_result([{"row_id": "op1", "portfolio": "commercial", "provision": Decimal("10")}])
    ifrs9 = _ifrs9_result([{"row_id": "op1", "portfolio": "commercial", "ecl": 10.0}])
    with pytest.raises(ProvisioningInputError, match="as_of_date"):
        _orchestrator("total").compare(cmf=cmf, ifrs9=ifrs9, as_of_date="   ")


# ─────────────────────────── nivel operación ───────────────────────────


def test_operation_alineado() -> None:
    """Nivel operación con row_id reconciliables -> máximo por operación."""
    cmf = _cmf_result(
        [
            {"row_id": "loan-1", "portfolio": "commercial", "provision": Decimal("80")},
            {"row_id": "loan-2", "portfolio": "consumer", "provision": Decimal("5")},
        ]
    )
    ifrs9 = _ifrs9_result(
        [
            {"row_id": "loan-1", "portfolio": "commercial", "ecl": 40.0},
            {"row_id": "loan-2", "portfolio": "consumer", "ecl": 50.0},
        ]
    )
    result = _orchestrator("operation").compare(cmf=cmf, ifrs9=ifrs9, as_of_date="2026-01-31")

    por_celda = {r.cell_id: r for r in result.records}
    assert por_celda["loan-1"].binding == "cmf"
    assert por_celda["loan-1"].reported_provision == Decimal("80")
    assert por_celda["loan-2"].binding == "ifrs9"
    assert por_celda["loan-2"].reported_provision == Decimal("50.0")


def test_operation_perimetros_no_reconciliables() -> None:
    """Nivel operación con perímetros distintos -> ProvisioningAlignmentError con el desajuste."""
    cmf = _cmf_result([{"row_id": "loan-1", "portfolio": "commercial", "provision": Decimal("80")}])
    ifrs9 = _ifrs9_result([{"row_id": "loan-9", "portfolio": "commercial", "ecl": 40.0}])
    with pytest.raises(ProvisioningAlignmentError, match="no son reconciliables"):
        _orchestrator("operation").compare(cmf=cmf, ifrs9=ifrs9, as_of_date="2026-01-31")


def test_operation_row_id_duplicado_cmf() -> None:
    """row_id CMF duplicado en operación -> ProvisioningInputError."""
    cmf = _cmf_result(
        [
            {"row_id": "loan-1", "portfolio": "commercial", "provision": Decimal("80")},
            {"row_id": "loan-1", "portfolio": "commercial", "provision": Decimal("5")},
        ]
    )
    ifrs9 = _ifrs9_result([{"row_id": "loan-1", "portfolio": "commercial", "ecl": 40.0}])
    with pytest.raises(ProvisioningInputError, match="row_id CMF duplicado"):
        _orchestrator("operation").compare(cmf=cmf, ifrs9=ifrs9, as_of_date="2026-01-31")


def test_operation_row_id_duplicado_ifrs9() -> None:
    """row_id IFRS 9 duplicado en operación -> ProvisioningInputError."""
    cmf = _cmf_result([{"row_id": "loan-1", "portfolio": "commercial", "provision": Decimal("80")}])
    ifrs9 = _ifrs9_result(
        [
            {"row_id": "loan-1", "portfolio": "commercial", "ecl": 40.0},
            {"row_id": "loan-1", "portfolio": "commercial", "ecl": 5.0},
        ]
    )
    with pytest.raises(ProvisioningInputError, match="row_id IFRS 9 duplicado"):
        _orchestrator("operation").compare(cmf=cmf, ifrs9=ifrs9, as_of_date="2026-01-31")


# ─────────────────────────── segmento y crosswalk de carteras ───────────────────────────


def test_segment_level_por_columna_compartida() -> None:
    """Nivel segmento por una columna presente en ambos detalles (aquí 'portfolio')."""
    cmf = _cmf_result([{"row_id": "op1", "portfolio": "commercial", "provision": Decimal("70")}])
    ifrs9 = _ifrs9_result([{"row_id": "op1", "portfolio": "commercial", "ecl": 40.0}])
    result = _orchestrator("segment", segment_col="portfolio").compare(
        cmf=cmf, ifrs9=ifrs9, as_of_date="2026-01-31"
    )

    record = result.records[0]
    assert record.level == "segment"
    assert record.cell_id == "commercial"
    assert record.reported_provision == Decimal("70")


def test_segment_col_ausente_en_detalle() -> None:
    """comparison_level='segment' con segment_col ausente en el detalle -> ConfigError."""
    cmf = _cmf_result([{"row_id": "op1", "portfolio": "commercial", "provision": Decimal("70")}])
    ifrs9 = _ifrs9_result([{"row_id": "op1", "portfolio": "commercial", "ecl": 40.0}])
    with pytest.raises(ProvisioningConfigError, match="segment_col"):
        _orchestrator("segment", segment_col="inexistente").compare(
            cmf=cmf, ifrs9=ifrs9, as_of_date="2026-01-31"
        )


def test_segment_col_ausente_solo_en_ifrs9() -> None:
    """segment_col presente en el detalle CMF ('method') pero ausente en IFRS 9 -> error IFRS 9."""
    cmf = _cmf_result([{"row_id": "op1", "portfolio": "commercial", "provision": Decimal("70")}])
    ifrs9 = _ifrs9_result([{"row_id": "op1", "portfolio": "commercial", "ecl": 40.0}])
    with pytest.raises(ProvisioningConfigError, match="IFRS 9"):
        _orchestrator("segment", segment_col="method").compare(
            cmf=cmf, ifrs9=ifrs9, as_of_date="2026-01-31"
        )


def test_portfolio_col_ausente_en_detalle() -> None:
    """Columna de cartera ausente en el detalle -> ProvisioningAlignmentError (no reconciliable)."""
    cmf = _cmf_result([{"row_id": "op1", "portfolio": "commercial", "provision": Decimal("70")}])
    ifrs9 = _ifrs9_result([{"row_id": "op1", "portfolio": "commercial", "ecl": 40.0}])
    orquestador = ProvisioningOrchestrator(
        ProvisioningConfig(
            comparison_level="portfolio",
            cmf_portfolio_col="ghost",
            ifrs9_portfolio_col="ghost",
        )
    )
    with pytest.raises(ProvisioningAlignmentError, match="no está en el detalle"):
        orquestador.compare(cmf=cmf, ifrs9=ifrs9, as_of_date="2026-01-31")


def test_portfolio_crosswalk_remapea_carteras() -> None:
    """El crosswalk mapea la cartera CMF a la taxonomía IFRS 9 antes de comparar (D-PROV-3)."""
    cmf = _cmf_result([{"row_id": "op1", "portfolio": "comercial", "provision": Decimal("90")}])
    ifrs9 = _ifrs9_result([{"row_id": "op1", "portfolio": "commercial", "ecl": 40.0}])
    orquestador = ProvisioningOrchestrator(
        ProvisioningConfig(
            comparison_level="portfolio",
            portfolio_crosswalk={"comercial": "commercial"},
        )
    )
    result = orquestador.compare(cmf=cmf, ifrs9=ifrs9, as_of_date="2026-01-31")

    assert [r.cell_id for r in result.records] == ["commercial"]
    assert result.records[0].coverage == "both"
    assert result.records[0].reported_provision == Decimal("90")


# ─────────────────────────── result / DTOs / auditoría / determinismo ───────────────────────────


def test_result_dtos_columnas_y_summary() -> None:
    """El resultado publica comparison/summary con columnas canónicas y records paralelos."""
    cmf = _cmf_result(
        [{"row_id": "op1", "portfolio": "commercial", "provision": Decimal("100.00")}]
    )
    ifrs9 = _ifrs9_result([{"row_id": "op1", "portfolio": "commercial", "ecl": 60.165289}])
    result = _orchestrator("portfolio").compare(cmf=cmf, ifrs9=ifrs9, as_of_date="2026-01-31")

    assert isinstance(result, ProvisionOrchestrationResult)
    assert tuple(result.comparison.columns) == orch._COMPARISON_COLUMNS
    assert tuple(result.summary.columns) == orch._SUMMARY_COLUMNS
    assert len(result.records) == len(result.comparison)
    assert result.summary.loc[0, "total_reported_provision"] == Decimal("100.00")
    assert result.summary.loc[0, "n_cells"] == 1
    metric = result.card.metric_sections["provisioning_orchestration"]
    assert metric["comparison_level"] == "portfolio"
    assert metric["floor_bite_ratio"] == 1.0
    assert metric["binding_counts"]["cmf"] == 1


def test_determinismo_dos_corridas_identicas() -> None:
    """Dos corridas con los mismos insumos y config producen comparison/summary equivalentes."""
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
    orquestador = _orchestrator("portfolio")
    primera = orquestador.compare(cmf=cmf, ifrs9=ifrs9, as_of_date="2026-01-31")
    segunda = orquestador.compare(cmf=cmf, ifrs9=ifrs9, as_of_date="2026-01-31")

    assert_frame_equal(primera.comparison, segunda.comparison)
    assert_frame_equal(primera.summary, segunda.summary)
    assert primera.records == segunda.records
    assert primera.card == segunda.card


def test_no_mutacion_de_insumos() -> None:
    """compare no muta los resultados CMF/IFRS 9 de entrada (usa copias defensivas)."""
    cmf = _cmf_result([{"row_id": "op1", "portfolio": "commercial", "provision": Decimal("100")}])
    ifrs9 = _ifrs9_result([{"row_id": "op1", "portfolio": "commercial", "ecl": 40.0}])
    cmf_detail_before = cmf.detail.copy(deep=True)
    ifrs9_detail_before = ifrs9.detail.copy(deep=True)

    _orchestrator("portfolio").compare(cmf=cmf, ifrs9=ifrs9, as_of_date="2026-01-31")

    assert_frame_equal(cmf.detail, cmf_detail_before)
    assert_frame_equal(ifrs9.detail, ifrs9_detail_before)


def test_audit_emite_decisiones() -> None:
    """Con un sink inyectado, compare emite las decisiones auditables del piso (SDD-17 §9)."""
    cmf = _cmf_result([{"row_id": "op1", "portfolio": "commercial", "provision": Decimal("100")}])
    ifrs9 = _ifrs9_result([{"row_id": "op1", "portfolio": "commercial", "ecl": 40.0}])
    sink = InMemoryAuditSink()
    _orchestrator("portfolio").compare(cmf=cmf, ifrs9=ifrs9, as_of_date="2026-01-31", audit=sink)

    reglas = {event.payload["regla"] for event in sink.events}
    assert reglas == {
        "provisioning_level",
        "provisioning_engines",
        "provisioning_reconciliation",
        "provisioning_binding",
        "provisioning_coverage",
    }
    assert all(event.kind == "decision" for event in sink.events)


def test_from_config_acepta_config_o_dict() -> None:
    """from_config acepta un ProvisioningConfig o un mapping revalidable."""
    cfg = ProvisioningConfig(comparison_level="total")
    assert ProvisioningOrchestrator.from_config(cfg).config is cfg
    desde_dict = ProvisioningOrchestrator.from_config({"comparison_level": "portfolio"})
    assert desde_dict.config.comparison_level == "portfolio"


# ─────────────────────────── reconciliación float_isclose y redondeo ───────────────────────────


def test_float_isclose_reconciliacion() -> None:
    """numeric_reconciliation='float_isclose' reporta en el dominio económico (float)."""
    cfg = ProvisioningConfig(numeric_reconciliation="float_isclose", tie_tolerance=0.0)
    gana_cmf, binding_cmf = orch._reconcile_both(Decimal("100.0"), 50.0, cfg=cfg)
    assert gana_cmf == Decimal("100.0")
    assert binding_cmf == "cmf"
    gana_ifrs9, binding_ifrs9 = orch._reconcile_both(Decimal("50.0"), 100.0, cfg=cfg)
    assert gana_ifrs9 == Decimal("100.0")
    assert binding_ifrs9 == "ifrs9"


def test_apply_rounding_politicas() -> None:
    """El redondeo contable explícito respeta none/currency_2dp/integer_currency (ROUND_HALF_UP)."""
    assert orch._apply_rounding(Decimal("100.005"), "none") == Decimal("100.005")
    assert orch._apply_rounding(Decimal("100.005"), "currency_2dp") == Decimal("100.01")
    assert orch._apply_rounding(Decimal("100.5"), "integer_currency") == Decimal("101")


def test_rounding_integrado_en_compare() -> None:
    """El redondeo se aplica a la provisión reportada publicada por compare."""
    cmf = _cmf_result([{"row_id": "op1", "portfolio": "c", "provision": Decimal("100.005")}])
    result = _orchestrator("portfolio", require_both=False, rounding="currency_2dp").compare(
        cmf=cmf, ifrs9=None, as_of_date="2026-01-31"
    )
    assert result.records[0].reported_provision == Decimal("100.01")


# ─────────────────────────── helpers numéricos (defensa en profundidad) ───────────────────────────


def test_to_decimal_normaliza_y_valida() -> None:
    """_to_decimal acepta Decimal/float finito no negativo y rechaza el resto (§8)."""
    assert orch._to_decimal(Decimal("5")) == Decimal("5")
    assert orch._to_decimal(5.5) == Decimal("5.5")
    with pytest.raises(ProvisioningInputError, match="no finito"):
        orch._to_decimal(Decimal("NaN"))
    with pytest.raises(ProvisioningInputError, match="negativo"):
        orch._to_decimal(Decimal("-1"))
    with pytest.raises(ProvisioningInputError, match="no finito"):
        orch._to_decimal(float("inf"))
    with pytest.raises(ProvisioningInputError, match="negativo"):
        orch._to_decimal(-1.0)
    with pytest.raises(ProvisioningInputError, match="no numérico"):
        orch._to_decimal(True)
    with pytest.raises(ProvisioningInputError, match="no numérico"):
        orch._to_decimal("x")


def test_to_float_normaliza_y_valida() -> None:
    """_to_float acepta float finito no negativo y rechaza el resto (§8)."""
    assert orch._to_float(5.5) == 5.5
    with pytest.raises(ProvisioningInputError, match="no numérico"):
        orch._to_float(True)
    with pytest.raises(ProvisioningInputError, match="no numérico"):
        orch._to_float("x")
    with pytest.raises(ProvisioningInputError, match="no finito"):
        orch._to_float(float("nan"))
    with pytest.raises(ProvisioningInputError, match="negativo"):
        orch._to_float(-1.0)


def test_floor_bite_ratio_maneja_cero_celdas() -> None:
    """_floor_bite_ratio devuelve None sin celdas y la fracción en otro caso."""
    assert orch._floor_bite_ratio(0, 0) is None
    assert orch._floor_bite_ratio(1, 2) == 0.5


def test_import_pandas_falla_con_mensaje_accionable(monkeypatch: pytest.MonkeyPatch) -> None:
    """_import_pandas traduce la ausencia de pandas a MissingDependencyError."""
    real_import = orch.importlib.import_module

    def _bloquea_pandas(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "pandas":
            raise ModuleNotFoundError("No module named 'pandas'", name="pandas")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(orch.importlib, "import_module", _bloquea_pandas)
    with pytest.raises(MissingDependencyError, match="requiere pandas"):
        orch._import_pandas()


# ─────────────────────────── factories ───────────────────────────


@dataclass(frozen=True)
class _MatrixConfig:
    """Config estructural mínima compatible con ``CmfMatrixConfigLike``."""

    active_version: str = "cmf_b1_b3_2025_01"
    require_verified_rows: bool = True
    fail_on_source_mismatch: bool = True


_BUNDLE: CmfMatrixBundle = load_cmf_matrices(_MatrixConfig())


def _orchestrator(level: str, **overrides: Any) -> ProvisioningOrchestrator:
    payload: dict[str, Any] = {"comparison_level": level}
    payload.update(overrides)
    return ProvisioningOrchestrator(ProvisioningConfig(**payload))


def _cmf_result(rows: list[dict[str, Any]], *, total: Decimal | None = None) -> CmfProvisionResult:
    total_provision = (
        total if total is not None else sum((row["provision"] for row in rows), Decimal("0"))
    )
    detail = pd.DataFrame(
        {
            "portfolio": [row["portfolio"] for row in rows],
            "method": ["standard_b1"] * len(rows),
            "cmf_category": [row.get("cmf_category", "A1") for row in rows],
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
            cmf_category=row.get("cmf_category", "A1"),
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


def _ifrs9_result(rows: list[dict[str, Any]], *, total: float | None = None) -> IfrsProvisionResult:
    n = len(rows)
    stages = [int(row.get("stage", 1)) for row in rows]
    ecls = [float(row["ecl"]) for row in rows]
    total_ecl = total if total is not None else sum(ecls)
    staging = pd.DataFrame(
        {
            "row_id": [row["row_id"] for row in rows],
            "portfolio": [row["portfolio"] for row in rows],
            "stage": stages,
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
            "stage": stages,
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
            stage=int(row.get("stage", 1)),
            days_past_due=0,
            pd_life_current=0.02,
            pd_life_origination=0.02,
        )
        for row in rows
    )
    ecl_records = tuple(
        IfrsEclRecord(
            row_id=row["row_id"],
            stage=int(row.get("stage", 1)),
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
        as_of_date="2026-01-31",
        term_structure_source="survival",
        pit_mode="consume_pit",
        n_rows=n,
        n_stage1=sum(1 for stage in stages if stage == 1),
        n_stage2=sum(1 for stage in stages if stage == 2),
        n_stage3=sum(1 for stage in stages if stage == 3),
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
