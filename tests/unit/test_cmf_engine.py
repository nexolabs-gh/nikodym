"""Tests del motor ``provisioning.cmf.engine`` (B15.4/B15.5)."""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

import nikodym.provisioning.cmf.engine as engine_module
from nikodym.core.audit import InMemoryAuditSink
from nikodym.core.exceptions import ConfigError, MissingDependencyError
from nikodym.provisioning.cmf.config import (
    CmfExposureConfig,
    CmfGuaranteeConfig,
    CmfMatrixConfig,
    CmfPdMappingConfig,
    CmfProvisioningConfig,
)
from nikodym.provisioning.cmf.engine import CmfProvisioningEngine
from nikodym.provisioning.cmf.exceptions import (
    CmfCalculationError,
    CmfInputError,
    CmfMappingError,
    CmfMatrixError,
    CmfMissingRegulatoryDataError,
)
from nikodym.provisioning.cmf.matrices import CmfMatrixBundle, CmfMatrixRow, load_cmf_matrices


@dataclass(frozen=True)
class MatrixConfig:
    """Config estructural mínima compatible con ``CmfMatrixConfigLike``."""

    active_version: str = "cmf_b1_b3_2025_01"
    require_verified_rows: bool = True
    fail_on_source_mismatch: bool = True


def test_engine_calcula_goldens_canonicos_y_no_muta_input() -> None:
    """Los goldens SDD-15 §11 se recalculan a mano y preservan orden."""
    frame = _golden_frame()
    original = frame.copy(deep=True)
    result = _engine().calculate(frame, as_of_date="2026-01-31")
    records = {record.row_id: record for record in result.records}

    assert_frame_equal(frame, original)
    assert list(result.detail.index) == ["a1", "b4", "c3", "consumo", "pvg", "grupal"]
    assert result.card.matrix_version == "cmf_b1_b3_2025_01"
    assert result.term_structure() is None

    assert records["a1"].provision_amount == _expected(1_000_000, "0.04", "90.0")
    assert records["b4"].provision_amount == _expected(1_000_000, "45.00", "97.5")
    assert records["c3"].cmf_category == "C3"
    assert records["c3"].provision_amount == Decimal("1000") * Decimal("25") / Decimal("100")
    assert records["consumo"].provision_amount == _expected(100_000, "6.6", "56.6")
    assert records["pvg"].provision_amount == Decimal("100000") * Decimal("24.2355") / Decimal(
        "100"
    )
    assert records["grupal"].provision_amount == _expected(100_000, "4.91", "56.9")
    assert records["pvg"].method == "pvg_tabulated_pe"
    assert records["c3"].method == "default_pp"

    assert result.detail.loc["consumo", "source_reference"] == "docs/normativa_cmf_parametros.md §3"
    assert result.summary.loc["commercial_individual|standard_b1|A1", "n_rows"] == 1
    assert result.summary.loc[
        "commercial_group_generic_factoring|standard_b1|0|sin_garantia|"
        "sin_responsabilidad_cedente_o_generica",
        "total_provision_amount",
    ] == _expected(100_000, "4.91", "56.9")
    assert result.card.metric_sections["cmf_b1_engine"] == {
        "matrix_sha256": result.matrix_bundle.manifest.yaml_sha256,
        "pe_consistency_tolerance_percent": "0.0001",
        "summary_rows": 6,
        "scope": "b1_b3_aval_substitution_financial_guarantee_guardrails",
    }


def test_engine_agrega_consumo_por_deudor() -> None:
    """Consumo usa mora máxima y flags consolidados por deudor para la PI."""
    frame = pd.DataFrame(
        [
            _consumer_row(
                debtor_id="rut-1",
                days_past_due=0,
                system_dpd30_last_3m=False,
                exposure_amount=100_000,
            ),
            _consumer_row(
                debtor_id="rut-1",
                days_past_due=35,
                system_dpd30_last_3m=True,
                exposure_amount=50_000,
            ),
        ],
        index=["op1", "op2"],
    )

    result = _engine().calculate(frame, as_of_date="2026-01-31")

    assert [record.pi_percent for record in result.records] == [Decimal("66.3"), Decimal("66.3")]
    assert [record.pdi_percent for record in result.records] == [Decimal("56.6"), Decimal("56.6")]
    assert result.records[0].provision_amount == _expected(100_000, "66.3", "56.6")
    assert result.records[1].provision_amount == _expected(50_000, "66.3", "56.6")


def test_engine_mapea_pd_breaks_sin_requerir_categoria_en_frame() -> None:
    """``pd_breaks`` asigna categoría CMF desde ``pd_frame`` alineado por índice."""
    cfg = CmfProvisioningConfig(
        pd_mapping=CmfPdMappingConfig(
            method="pd_breaks",
            pd_breaks=(0.10,),
            categories=("A1", "B4"),
        )
    )
    frame = pd.DataFrame(
        [{"cmf_portfolio": "commercial_individual", "exposure_amount": 1_000_000}],
        index=["loan"],
    )
    pd_frame = pd.DataFrame({"pd_raw": [0.20]}, index=["loan"])
    original_pd = pd_frame.copy(deep=True)

    result = CmfProvisioningEngine.from_config(cfg).calculate(
        frame,
        pd_frame=pd_frame,
        as_of_date="2026-01-31",
    )

    assert_frame_equal(pd_frame, original_pd)
    assert result.records[0].cmf_category == "B4"
    assert result.records[0].pd_source_value == Decimal("0.2")
    assert result.records[0].provision_amount == _expected(1_000_000, "45.00", "97.5")


def test_engine_calcula_leasing_estudiantil_y_pvg_derivado() -> None:
    """Cubre carteras grupales y PVG derivado sin contingentes ni garantías."""
    frame = pd.DataFrame(
        [
            {
                "cmf_portfolio": "commercial_group_leasing",
                "days_past_due": 0,
                "leasing_asset_type": "inmobiliario",
                "pvb": 35,
                "exposure_amount": 100_000,
            },
            {
                "cmf_portfolio": "commercial_group_student",
                "days_past_due": 0,
                "student_payment_due": True,
                "student_loan_type": "cae",
                "exposure_amount": 100_000,
            },
            {
                "cmf_portfolio": "housing",
                "days_past_due": 60,
                "loan_balance": 95,
                "mortgage_guarantee_value": 100,
                "exposure_amount": 100_000,
            },
        ],
        index=["leasing", "student", "housing"],
    )

    result = _engine().calculate(frame, as_of_date="2026-01-31")
    records = {record.row_id: record for record in result.records}

    assert records["leasing"].provision_amount == _expected(100_000, "0.79", "0.05")
    assert records["student"].provision_amount == _expected(100_000, "5.2", "70.9")
    assert records["housing"].provision_amount == Decimal("100000") * Decimal("24.2355") / Decimal(
        "100"
    )


@pytest.mark.parametrize(
    ("row_id", "contingent_type", "contingent_subtype", "ccf_percent"),
    [
        ("a", "avales_fianzas", None, "100"),
        ("b", "cartas_credito_exterior_confirmadas", None, "20"),
        ("c", "cartas_credito_documentarias_emitidas", None, "20"),
        ("d", "boletas_garantia", None, "50"),
        ("e", "lineas_libre_disposicion", None, "35"),
        ("f_cae", "otros_compromisos_credito", "cae_ley_20027", "15"),
        ("f_otros", "otros_compromisos_credito", "otros", "100"),
        ("g", "otros_creditos_contingentes", None, "100"),
    ],
)
def test_engine_calcula_las_ocho_filas_contingentes_b3(
    row_id: str,
    contingent_type: str,
    contingent_subtype: str | None,
    ccf_percent: str,
) -> None:
    """B-3 usa la matriz verificada: ocho filas reales, cifra a cifra."""
    frame = pd.DataFrame(
        [
            _contingent_row(
                contingent_type=contingent_type,
                contingent_subtype=contingent_subtype,
                contingent_amount=1_000,
                is_default=False,
            )
        ],
        index=[row_id],
    )

    result = _engine().calculate(frame, as_of_date="2026-01-31")
    record = result.records[0]
    expected_contingent = Decimal("1000") * Decimal(ccf_percent) / Decimal("100")

    assert record.direct_exposure_amount == Decimal("0")
    assert record.contingent_exposure_amount == expected_contingent
    assert record.exposure_amount == expected_contingent
    assert record.provision_amount == _expected_decimal(expected_contingent, "0.04", "90.0")
    assert result.detail.loc[row_id, "ccf_percent"] == Decimal(ccf_percent)
    assert result.detail.loc[row_id, "contingent_exposure_amount"] == expected_contingent


def test_engine_contingente_b3_fuerza_ccf_100_en_incumplimiento() -> None:
    """El override B-3 de incumplimiento reemplaza el CCF de matriz por 100 %."""
    frame = pd.DataFrame(
        [
            _contingent_row(
                contingent_type="lineas_libre_disposicion",
                contingent_subtype=None,
                contingent_amount=1_000,
                is_default=True,
            )
        ],
        index=["default"],
    )

    result = _engine().calculate(frame, as_of_date="2026-01-31")

    assert result.records[0].contingent_exposure_amount == Decimal("1000")
    assert result.detail.loc["default", "ccf_percent"] == Decimal("100")
    assert result.records[0].provision_amount == _expected_decimal(
        Decimal("1000"),
        "0.04",
        "90.0",
    )


@pytest.mark.parametrize(
    ("frame", "error_cls", "match"),
    [
        (
            pd.DataFrame(
                [
                    {
                        "cmf_portfolio": "commercial_individual",
                        "cmf_category": "A1",
                        "exposure_amount": 0,
                        "contingent_amount": 100,
                        "is_default": False,
                    }
                ],
                index=["sin_tipo"],
            ),
            CmfInputError,
            "tipo contingente",
        ),
        (
            pd.DataFrame(
                [
                    {
                        "cmf_portfolio": "commercial_individual",
                        "cmf_category": "A1",
                        "exposure_amount": 0,
                        "contingent_amount": 100,
                        "contingent_type": "otros_compromisos_credito",
                        "is_default": False,
                    }
                ],
                index=["sin_subtipo"],
            ),
            CmfMissingRegulatoryDataError,
            "sin_subtipo",
        ),
        (
            pd.DataFrame(
                [
                    {
                        "cmf_portfolio": "commercial_individual",
                        "cmf_category": "A1",
                        "exposure_amount": 0,
                        "contingent_amount": 100,
                        "contingent_type": "tipo_no_verificado",
                        "is_default": False,
                    }
                ],
                index=["unmapped"],
            ),
            CmfMissingRegulatoryDataError,
            "Tipo contingente B-3",
        ),
        (
            pd.DataFrame(
                [
                    {
                        "cmf_portfolio": "commercial_individual",
                        "cmf_category": "A1",
                        "exposure_amount": 0,
                        "contingent_amount": 100,
                        "contingent_type": "avales_fianzas",
                    }
                ],
                index=["sin_default"],
            ),
            CmfInputError,
            "incumplimiento",
        ),
        (
            pd.DataFrame(
                [
                    {
                        "cmf_portfolio": "commercial_individual",
                        "cmf_category": "A1",
                        "exposure_amount": 0,
                        "contingent_amount": -1,
                        "contingent_type": "avales_fianzas",
                        "is_default": False,
                    }
                ],
                index=["negativo"],
            ),
            CmfInputError,
            "contingente negativa",
        ),
    ],
)
def test_engine_rechaza_contingentes_b3_invalidos(
    frame: pd.DataFrame,
    error_cls: type[Exception],
    match: str,
) -> None:
    """Los bordes B-3 fallan sin aproximaciones regulatorias."""
    with pytest.raises(error_cls, match=match):
        _engine().calculate(frame, as_of_date="2026-01-31")


def test_engine_tipo_contingente_no_mapeado_respeta_excepcion_configurada() -> None:
    """La config no-default cambia la excepción, pero no inventa CCF."""
    cfg = CmfProvisioningConfig(matrices=CmfMatrixConfig(fail_on_unmapped_contingent_type=False))
    frame = pd.DataFrame(
        [
            _contingent_row(
                contingent_type="tipo_no_verificado",
                contingent_subtype=None,
                contingent_amount=100,
                is_default=False,
            )
        ]
    )

    with pytest.raises(CmfMappingError, match="Tipo contingente B-3"):
        CmfProvisioningEngine.from_config(cfg).calculate(frame, as_of_date="2026-01-31")


def test_engine_aval_sustituye_solo_tramo_cubierto_con_formula_2d() -> None:
    """Cobertura 40 % usa PI/PDI del aval solo en el tramo avalado."""
    frame = pd.DataFrame(
        [
            {
                "cmf_portfolio": "commercial_group_generic_factoring",
                "days_past_due": 0,
                "ptvg_bucket": "sin_garantia",
                "factoring_recourse_type": "sin_responsabilidad_cedente_o_generica",
                "exposure_amount": 100_000,
                "aval_coverage_pct": 40,
                "aval_rating_scale": "national",
                "aval_rating_category": "AA / Aa2",
            }
        ],
        index=["aval"],
    )
    expected_debtor_leg = (
        Decimal("100000")
        * Decimal("60")
        / Decimal("100")
        * Decimal("4.91")
        / Decimal("100")
        * Decimal("56.9")
        / Decimal("100")
    )
    expected_aval_leg = (
        Decimal("100000")
        * Decimal("40")
        / Decimal("100")
        * Decimal("0.04")
        / Decimal("100")
        * Decimal("90.0")
        / Decimal("100")
    )

    result = _engine().calculate(frame, as_of_date="2026-01-31")
    record = result.records[0]

    assert record.guarantee_treatment == "aval_substitution"
    assert result.detail.loc["aval", "guarantee_treatment"] == "aval_substitution"
    assert record.provision_amount == expected_debtor_leg + expected_aval_leg
    assert record.pe_percent == record.provision_amount / Decimal("100000") * Decimal("100")
    assert "metodo_2_pi_pdi" in record.matrix_row_id
    assert "aa_aa2_national" in record.matrix_row_id


def test_engine_aval_con_pe_directa_cubre_metodo_1() -> None:
    """La fórmula PE directa se usa cuando la fila base no publica PI/PDI."""
    frame = pd.DataFrame(
        [
            {
                "cmf_portfolio": "commercial_individual",
                "cmf_category": "C3",
                "exposure_amount": 1_000,
                "aval_coverage_pct": 50,
                "aval_rating_scale": "international",
                "aval_rating_category": "AA/Aa2",
            }
        ],
        index=["c3_aval"],
    )
    expected = (
        Decimal("1000") * Decimal("50") / Decimal("100") * Decimal("25") / Decimal("100")
    ) + (
        Decimal("1000")
        * Decimal("50")
        / Decimal("100")
        * Decimal("0.04")
        / Decimal("100")
        * Decimal("90.0")
        / Decimal("100")
    )

    result = _engine().calculate(frame, as_of_date="2026-01-31")

    assert result.records[0].provision_amount == expected
    assert "metodo_1_pe_directa" in result.records[0].matrix_row_id


@pytest.mark.parametrize("coverage", [Decimal("-0.01"), Decimal("100.01")])
def test_engine_rechaza_aval_con_cobertura_fuera_de_rango(coverage: Decimal) -> None:
    """La cobertura de aval debe quedar dentro de [0, 100]."""
    frame = pd.DataFrame(
        [
            {
                "cmf_portfolio": "commercial_group_generic_factoring",
                "days_past_due": 0,
                "ptvg_bucket": "sin_garantia",
                "factoring_recourse_type": "sin_responsabilidad_cedente_o_generica",
                "exposure_amount": 100_000,
                "aval_coverage_pct": coverage,
                "aval_rating_scale": "national",
                "aval_rating_category": "AA/Aa2",
            }
        ]
    )

    with pytest.raises(CmfInputError, match="Cobertura de aval"):
        _engine().calculate(frame, as_of_date="2026-01-31")


def test_engine_rechaza_aval_sin_rating_verificado() -> None:
    """Un rating de aval fuera de la matriz §5.2 no se aproxima por similitud."""
    frame = pd.DataFrame(
        [
            {
                "cmf_portfolio": "commercial_group_generic_factoring",
                "days_past_due": 0,
                "ptvg_bucket": "sin_garantia",
                "factoring_recourse_type": "sin_responsabilidad_cedente_o_generica",
                "exposure_amount": 100_000,
                "aval_coverage_pct": 40,
                "aval_rating_scale": "national",
                "aval_rating_category": "CCC/Caa",
            }
        ]
    )

    with pytest.raises(CmfMappingError, match="Aval sin equivalencia"):
        _engine().calculate(frame, as_of_date="2026-01-31")


def test_engine_aval_deshabilitado_no_sustituye_tramos() -> None:
    """La sustitución por aval es opt-in vía la config existente."""
    cfg = CmfProvisioningConfig(guarantees=CmfGuaranteeConfig(enable_aval_substitution=False))
    frame = pd.DataFrame(
        [
            {
                "cmf_portfolio": "commercial_group_generic_factoring",
                "days_past_due": 0,
                "ptvg_bucket": "sin_garantia",
                "factoring_recourse_type": "sin_responsabilidad_cedente_o_generica",
                "exposure_amount": 100_000,
                "aval_coverage_pct": 40,
                "aval_rating_scale": "national",
                "aval_rating_category": "AA/Aa2",
            }
        ]
    )

    result = CmfProvisioningEngine.from_config(cfg).calculate(frame, as_of_date="2026-01-31")

    assert result.records[0].guarantee_treatment == "none"
    assert result.records[0].provision_amount == _expected(100_000, "4.91", "56.9")


def test_engine_garantia_financiera_falla_por_default_sin_haircut_verificado() -> None:
    """No se imputan aforos financieros pendientes de normativa."""
    frame = pd.DataFrame(
        [
            {
                "cmf_portfolio": "commercial_individual",
                "cmf_category": "A1",
                "exposure_amount": 1_000,
                "financial_guarantee_amount": 100,
            }
        ]
    )

    with pytest.raises(CmfMissingRegulatoryDataError, match="Garantía financiera"):
        _engine().calculate(frame, as_of_date="2026-01-31")


def test_engine_garantia_financiera_respeta_politicas_no_default() -> None:
    """Las políticas explícitas no inventan haircuts y exigen recupero cuando aplica."""
    frame = pd.DataFrame(
        [
            {
                "cmf_portfolio": "commercial_individual",
                "cmf_category": "A1",
                "exposure_amount": 1_000,
                "financial_guarantee_amount": 100,
                "recoverable_amount": 80,
            }
        ]
    )
    ignore_cfg = CmfProvisioningConfig(
        guarantees=CmfGuaranteeConfig(financial_guarantee_policy="ignore_if_missing")
    )
    recoverable_cfg = CmfProvisioningConfig(
        guarantees=CmfGuaranteeConfig(
            financial_guarantee_policy="use_recoverable_amount",
            recoverable_amount_col="recoverable_amount",
        )
    )
    negative = frame.assign(recoverable_amount=-1)

    assert CmfProvisioningEngine.from_config(ignore_cfg).calculate(
        frame,
        as_of_date="2026-01-31",
    ).records[0].provision_amount == _expected(1_000, "0.04", "90.0")
    assert CmfProvisioningEngine.from_config(recoverable_cfg).calculate(
        frame,
        as_of_date="2026-01-31",
    ).records[0].provision_amount == _expected(1_000, "0.04", "90.0")
    with pytest.raises(CmfInputError, match="recoverable_amount"):
        CmfProvisioningEngine.from_config(recoverable_cfg).calculate(
            negative,
            as_of_date="2026-01-31",
        )


def test_engine_no_regresion_fila_sin_contingente_ni_aval() -> None:
    """Una fila base sin B-3 ni aval conserva exactamente el resultado B15.4."""
    frame = pd.DataFrame(
        [
            {
                "cmf_portfolio": "commercial_individual",
                "cmf_category": "A1",
                "exposure_amount": 1_000_000,
            }
        ],
        index=["base"],
    )

    result = _engine().calculate(frame, as_of_date="2026-01-31")

    assert result.records[0].direct_exposure_amount == Decimal("1000000")
    assert result.records[0].contingent_exposure_amount == Decimal("0")
    assert result.records[0].exposure_amount == Decimal("1000000")
    assert result.records[0].provision_amount == Decimal("360.00000")
    assert result.records[0].guarantee_treatment == "none"
    assert result.detail.loc["base", "ccf_percent"] is None


def test_engine_determinismo_orden_estable_y_finitud_b15_5() -> None:
    """Dos corridas B15.5 son byte-equivalentes, ordenadas y no negativas."""
    frame = pd.DataFrame(
        [
            _contingent_row(
                contingent_type="boletas_garantia",
                contingent_subtype=None,
                contingent_amount=1_000,
                is_default=False,
            ),
            {
                "cmf_portfolio": "commercial_group_generic_factoring",
                "days_past_due": 0,
                "ptvg_bucket": "sin_garantia",
                "factoring_recourse_type": "sin_responsabilidad_cedente_o_generica",
                "exposure_amount": 100_000,
                "aval_coverage_pct": 40,
                "aval_rating_scale": "national",
                "aval_rating_category": "AA/Aa2",
            },
        ],
        index=["contingente", "aval"],
    )

    result_1 = _engine().calculate(frame, as_of_date="2026-01-31")
    result_2 = _engine().calculate(frame, as_of_date="2026-01-31")

    assert _stable_payload(result_1) == _stable_payload(result_2)
    assert list(result_1.detail.index) == ["contingente", "aval"]
    for record in result_1.records:
        for value in (
            record.exposure_amount,
            record.direct_exposure_amount,
            record.contingent_exposure_amount,
            record.pe_percent,
            record.provision_amount,
            record.pi_percent,
            record.pdi_percent,
        ):
            if value is not None:
                assert value.is_finite()
                assert value >= Decimal("0")


@pytest.mark.parametrize(
    ("policy", "expected"),
    [("currency_2dp", Decimal("0.03")), ("integer_currency", Decimal("0"))],
)
def test_engine_redondea_y_audita_politica_explicita(policy: str, expected: Decimal) -> None:
    """El redondeo se aplica sólo cuando la config lo declara."""
    cfg = CmfProvisioningConfig(exposure=CmfExposureConfig(rounding=policy))
    frame = pd.DataFrame(
        [
            {
                "cmf_portfolio": "commercial_group_generic_factoring",
                "days_past_due": 0,
                "ptvg_bucket": "sin_garantia",
                "factoring_recourse_type": "sin_responsabilidad_cedente_o_generica",
                "exposure_amount": 1,
            }
        ],
        index=["row"],
    )
    audit = InMemoryAuditSink()

    result = CmfProvisioningEngine.from_config(cfg).calculate(
        frame,
        as_of_date="2026-01-31",
        audit=audit,
    )

    assert result.records[0].provision_amount == expected
    assert audit.events[0].payload["umbral"] == {
        "rounding": policy,
        "pe_tolerance_percent": "0.0001",
    }
    assert audit.events[0].payload["accion"] == "calcular_provision_cmf"
    assert audit.events[0].payload["regla"] == "cmf_b1_b3_engine"


@pytest.mark.parametrize(
    ("bad_frame", "error_cls", "match"),
    [
        ("no dataframe", CmfInputError, "pandas.DataFrame"),
        (
            pd.DataFrame(
                [{"cmf_portfolio": "commercial_individual", "exposure_amount": 1}],
                index=["dup"],
            ).rename(index={"dup": "x"}),
            CmfInputError,
            "índice único",
        ),
        (
            pd.DataFrame([{"cmf_portfolio": "commercial_individual"}]),
            CmfInputError,
            "Faltan columnas",
        ),
        (
            pd.DataFrame(
                [
                    {
                        "cmf_portfolio": "commercial_individual",
                        "cmf_category": "A1",
                        "exposure_amount": -1,
                    }
                ]
            ),
            CmfInputError,
            "negativa",
        ),
        (
            pd.DataFrame([{"cmf_portfolio": "ifrs9", "exposure_amount": 1}]),
            CmfMappingError,
            "no soportada",
        ),
    ],
)
def test_engine_rechaza_inputs_invalidos(
    bad_frame: object,
    error_cls: type[Exception],
    match: str,
) -> None:
    """Errores de input fallan con excepciones propias y mensajes auditables."""
    if isinstance(bad_frame, pd.DataFrame) and match == "índice único":
        bad_frame = pd.concat([bad_frame, bad_frame])
    with pytest.raises(error_cls, match=match):
        _engine().calculate(bad_frame, as_of_date="2026-01-31")


@pytest.mark.parametrize(
    ("frame", "error_cls", "match"),
    [
        (
            pd.DataFrame(
                [
                    {
                        "cmf_portfolio": "commercial_individual",
                        "cmf_category": "C3",
                        "exposure_amount": 0,
                    }
                ]
            ),
            CmfCalculationError,
            "C1-C6",
        ),
        (
            pd.DataFrame([{"cmf_portfolio": "commercial_individual", "exposure_amount": 1000}]),
            CmfInputError,
            "categoría CMF",
        ),
        (
            pd.DataFrame(
                [
                    {
                        "cmf_portfolio": "commercial_individual",
                        "recoverable_amount": 1,
                        "exposure_amount": 0,
                    }
                ]
            ),
            CmfCalculationError,
            "exposición cero",
        ),
    ],
)
def test_engine_bordes_incumplimiento_individual(
    frame: pd.DataFrame,
    error_cls: type[Exception],
    match: str,
) -> None:
    """C1-C6 falla sin categoría/recupero suficiente o con E=0."""
    with pytest.raises(error_cls, match=match):
        _engine().calculate(frame, as_of_date="2026-01-31")


def test_engine_levanta_cmfmatrixerror_por_ausencia_ambiguedad_e_inconsistencia() -> None:
    """La resolución exacta de matriz no tolera ausencia, duplicados ni PE incoherente."""
    base = _load_bundle()
    frame = pd.DataFrame(
        [
            {
                "cmf_portfolio": "commercial_individual",
                "cmf_category": "A1",
                "exposure_amount": 1000,
            }
        ]
    )

    with pytest.raises(CmfMatrixError, match="Categoría individual"):
        _engine().calculate(
            frame.assign(cmf_category="Z9"),
            as_of_date="2026-01-31",
        )

    duplicated = base.model_copy(
        update={
            "rows": (
                *base.rows,
                base.get_row("commercial_individual_performing_v2014", "A1"),
            )
        }
    )
    with pytest.raises(CmfMatrixError, match="coincidencias=2"):
        CmfProvisioningEngine(CmfProvisioningConfig(), matrices=duplicated).calculate(
            frame,
            as_of_date="2026-01-31",
        )

    bad_pe_row = base.get_row("commercial_individual_performing_v2014", "A1").model_copy(
        update={"pe_percent": "0,99999"}
    )
    inconsistent = _replace_row(base, bad_pe_row)
    with pytest.raises(CmfMatrixError, match="PE inconsistente"):
        CmfProvisioningEngine(CmfProvisioningConfig(), matrices=inconsistent).calculate(
            frame,
            as_of_date="2026-01-31",
        )


def test_engine_valida_pd_breaks_y_dependencia_pandas(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bordes de PD y dependencia pandas usan errores propios."""
    cfg = CmfProvisioningConfig(
        pd_mapping=CmfPdMappingConfig(method="pd_breaks", pd_breaks=(0.1,), categories=("A1", "B4"))
    )
    frame = pd.DataFrame(
        [{"cmf_portfolio": "commercial_individual", "exposure_amount": 1}],
        index=["x"],
    )
    with pytest.raises(CmfInputError, match="exige pd_frame"):
        CmfProvisioningEngine.from_config(cfg).calculate(frame, as_of_date="2026-01-31")
    with pytest.raises(CmfInputError, match="índice único"):
        CmfProvisioningEngine.from_config(cfg).calculate(
            frame,
            pd_frame=pd.DataFrame({"pd_raw": [0.2, 0.3]}, index=["x", "x"]),
            as_of_date="2026-01-31",
        )
    with pytest.raises(CmfInputError, match="Faltan columnas"):
        CmfProvisioningEngine.from_config(cfg).calculate(
            frame,
            pd_frame=pd.DataFrame({"otra_pd": [0.2]}, index=["x"]),
            as_of_date="2026-01-31",
        )
    with pytest.raises(CmfInputError, match="todas las filas"):
        CmfProvisioningEngine.from_config(cfg).calculate(
            frame,
            pd_frame=pd.DataFrame({"pd_raw": [0.2]}, index=["otro"]),
            as_of_date="2026-01-31",
        )
    with pytest.raises(CmfInputError, match="fuera de \\[0, 1\\]"):
        CmfProvisioningEngine.from_config(cfg).calculate(
            frame,
            pd_frame=pd.DataFrame({"pd_raw": [1.2]}, index=["x"]),
            as_of_date="2026-01-31",
        )

    def fail_import(name: str) -> Any:
        if name == "pandas":
            raise ModuleNotFoundError(name)
        return importlib_import(name)

    importlib_import = engine_module.importlib.import_module
    monkeypatch.setattr(engine_module.importlib, "import_module", fail_import)
    with pytest.raises(MissingDependencyError, match="requiere pandas"):
        engine_module._import_pandas()


def test_engine_cubre_ramas_defensivas_de_helpers_privados() -> None:
    """Los helpers internos mantienen errores propios en bordes no dorados."""
    decimal = _decimal_runtime()
    pd_module = pd

    assert isinstance(
        CmfProvisioningEngine.from_config({"type": "standard"}),
        CmfProvisioningEngine,
    )
    with pytest.raises(ConfigError, match="Hiperparámetros inválidos"):
        CmfProvisioningEngine(object(), matrices=_load_bundle()).calculate(  # type: ignore[arg-type]
            pd.DataFrame([{"cmf_portfolio": "commercial_individual", "exposure_amount": 1}]),
            as_of_date="2026-01-31",
        )

    duplicated_columns = pd.DataFrame(
        [["commercial_individual", "A1", 100, 200]],
        columns=["cmf_portfolio", "cmf_category", "exposure_amount", "exposure_amount"],
    )
    with pytest.raises(CmfInputError, match="duplicadas"):
        _engine().calculate(duplicated_columns, as_of_date="2026-01-31")

    assert engine_module._dpd_bucket(1) == "1_29"
    assert engine_module._dpd_bucket(30) == "30_59"
    assert engine_module._dpd_bucket(60) == "60_89"
    assert engine_module._dpd_bucket(90) == "incumplimiento"
    assert engine_module._consumer_dpd_bucket(8) == "8_30"
    assert engine_module._consumer_dpd_bucket(61) == "61_89"
    assert engine_module._consumer_dpd_bucket(90) == "incumplimiento"
    assert engine_module._housing_mora_bucket(0) == "0"
    assert engine_module._housing_mora_bucket(1) == "1_29"
    assert engine_module._housing_mora_bucket(30) == "30_59"
    assert engine_module._housing_mora_bucket(90) == "incumplimiento"
    assert engine_module._category_from_loss_percent(Decimal("1"), decimal=decimal) == "C1"
    assert engine_module._category_from_loss_percent(Decimal("10"), decimal=decimal) == "C2"
    assert engine_module._category_from_loss_percent(Decimal("40"), decimal=decimal) == "C4"
    assert engine_module._category_from_loss_percent(Decimal("70"), decimal=decimal) == "C5"
    assert engine_module._category_from_loss_percent(Decimal("90"), decimal=decimal) == "C6"
    assert engine_module._pvb_bucket(Decimal("45")) == "pvb_gt_40_le_50"
    assert engine_module._pvb_bucket(Decimal("70")) == "pvb_gt_50_le_80"
    assert engine_module._pvb_bucket(Decimal("85")) == "pvb_gt_80_le_90"
    assert engine_module._pvb_bucket(Decimal("95")) == "pvb_gt_90"

    assert engine_module._bool_dimension("sí", column="flag", row_id="r") is True
    assert engine_module._bool_dimension("0", column="flag", row_id="r") is False
    with pytest.raises(CmfInputError, match="booleana"):
        engine_module._bool_dimension("tal vez", column="flag", row_id="r")
    with pytest.raises(CmfInputError, match="vacía"):
        engine_module._text_plain(" ", column="texto", row_id="r")
    with pytest.raises(CmfInputError, match="nula"):
        engine_module._text_value(pd.NA, column="texto", row_id="r", pd=pd_module)
    assert engine_module._is_missing([1, 2], pd_module) is False

    for value, match in [
        (True, "no booleana"),
        (" ", "vacío"),
        ("abc", "Decimal"),
        ("NaN", "finitos"),
    ]:
        with pytest.raises(CmfInputError, match=match):
            engine_module._decimal_from_value(value, column="monto", decimal=decimal)
    with pytest.raises(CmfMatrixError, match="Porcentaje inválido"):
        engine_module._decimal_from_text("abc", column="pi", row_id="row", decimal=decimal)
    with pytest.raises(CmfMatrixError, match="no finito o negativo"):
        engine_module._decimal_from_text("-1", column="pi", row_id="row", decimal=decimal)
    with pytest.raises(CmfInputError, match="enteros no negativos"):
        engine_module._int_days(Decimal("1.5"), column="days", row_id="r", decimal=decimal)

    row = _load_bundle().get_row("commercial_individual_performing_v2014", "A1")
    with pytest.raises(CmfMatrixError, match="Falta pi_percent"):
        engine_module._required_percent(None, row=row, field_name="pi_percent", decimal=decimal)
    with pytest.raises(CmfMappingError, match="leasing"):
        engine_module._canonical_asset("vehiculo")
    with pytest.raises(CmfMappingError, match="estudiantil"):
        engine_module._student_type("otro")
    with pytest.raises(CmfMappingError, match="responsabilidad"):
        engine_module._recourse_type("otro")
    with pytest.raises(CmfMappingError, match="Producto"):
        engine_module._consumer_product("otro")

    assert (
        engine_module._pi_ptvg_bucket(
            "ptvg_le_60",
            pd.Series({"ptvg_pi_bucket": "con_garantia_ptvg_gt_100"}),
        )
        == "con_garantia_ptvg_gt_100"
    )
    assert (
        engine_module._pi_ptvg_bucket(
            "con_garantia_ptvg_gt_100",
            pd.Series({"ptvg_bucket": "con_garantia_ptvg_gt_100"}),
        )
        == "con_garantia_ptvg_gt_100"
    )
    assert (
        engine_module._pi_ptvg_bucket("ptvg_le_60", pd.Series({"ptvg_bucket": "ptvg_le_60"}))
        == "con_garantia_ptvg_le_100"
    )
    assert engine_module._pvg_bucket_for_row(pd.Series({"pvg": 30}), decimal=decimal) == "pvg_le_40"
    assert (
        engine_module._pvg_bucket_for_row(pd.Series({"pvg": 50}), decimal=decimal)
        == "pvg_gt_40_le_80"
    )
    assert (
        engine_module._pvg_bucket_for_row(pd.Series({"pvg": 85}), decimal=decimal)
        == "pvg_gt_80_le_90"
    )
    with pytest.raises(CmfCalculationError, match="garantía hipotecaria cero"):
        engine_module._pvg_bucket_for_row(
            pd.Series({"loan_balance": 1, "mortgage_guarantee_value": 0}),
            decimal=decimal,
        )
    with pytest.raises(CmfInputError, match="Vivienda exige"):
        engine_module._pvg_bucket_for_row(pd.Series({"otra": 1}), decimal=decimal)
    cfg_with_recoverable = CmfProvisioningConfig(
        guarantees=CmfGuaranteeConfig(recoverable_amount_col="recupero")
    )
    assert (
        engine_module._recoverable_column(pd.Series({"recupero": 1}), cfg_with_recoverable)
        == "recupero"
    )
    assert engine_module._recoverable_column(pd.Series({"otro": 1}), cfg_with_recoverable) is None

    assert engine_module._normaliza_rating_scale("internacional") == "international"
    assert engine_module._normaliza_rating_scale("nacional") == "national"
    assert engine_module._normaliza_rating_category("AA / Aa2") == "AA/Aa2"
    with pytest.raises(CmfMappingError, match="Escala"):
        engine_module._normaliza_rating_scale("global")
    assert engine_module._requires_financial_guarantee_haircut(
        pd.Series({"financial_guarantee_requires_haircut": True}, name="r"),
        pd=pd_module,
        decimal=decimal,
    )
    assert engine_module._requires_financial_guarantee_haircut(
        pd.Series({"financial_guarantee_amount": 1}, name="r"),
        pd=pd_module,
        decimal=decimal,
    )
    assert not engine_module._requires_financial_guarantee_haircut(
        pd.Series({"financial_guarantee_amount": 0}, name="r"),
        pd=pd_module,
        decimal=decimal,
    )
    assert engine_module._requires_financial_guarantee_haircut(
        pd.Series({"guarantee_type": "garantía_financiera"}, name="r"),
        pd=pd_module,
        decimal=decimal,
    )
    assert not engine_module._requires_financial_guarantee_haircut(
        pd.Series({"guarantee_type": "hipoteca"}, name="r"),
        pd=pd_module,
        decimal=decimal,
    )
    with pytest.raises(CmfInputError, match="booleana"):
        engine_module._requires_financial_guarantee_haircut(
            pd.Series({"financial_guarantee_requires_haircut": "quizas"}, name="r"),
            pd=pd_module,
            decimal=decimal,
        )
    with pytest.raises(CmfInputError, match="negativa"):
        engine_module._requires_financial_guarantee_haircut(
            pd.Series({"financial_guarantee_amount": -1}, name="r"),
            pd=pd_module,
            decimal=decimal,
        )
    assert engine_module._financial_guarantee_observed(
        pd.Series({"financial_guarantee_amount": 1})
    ).startswith("financial_guarantee_amount=")
    assert (
        engine_module._financial_guarantee_observed(pd.Series({"otra": 1}))
        == "<sin_columna_explicita>"
    )
    assert engine_module._join_source_texts(("docs §1", "docs §1", "docs §2")) == (
        "docs §1; docs §2"
    )

    consumer_context = engine_module.RowContext(
        row_id="r",
        row=pd.Series({"cmf_product_type": "creditos_en_cuotas"}),
        pd_category=None,
        consumer_state=None,
    )
    with pytest.raises(CmfCalculationError, match="estado deudor"):
        engine_module._resolve_consumer(
            consumer_context,
            exposure=Decimal("1"),
            cfg=CmfProvisioningConfig(),
            bundle=_load_bundle(),
            decimal=decimal,
        )


def test_engine_import_liviano_y_sin_imports_pesados_top_level() -> None:
    """Importar el engine no carga pandas/pandera/pyarrow ni tracking."""
    source = Path(engine_module.__file__).read_text(encoding="utf-8")
    assert "import pandera" not in source
    assert "df.eval" not in source
    code = (
        "import sys;"
        "import nikodym.provisioning.cmf.engine;"
        "bloqueados=[m for m in ('pandas','pandera','pyarrow','nikodym.tracking','mlflow') "
        "if m in sys.modules];"
        "assert not bloqueados, bloqueados"
    )
    subprocess.run([sys.executable, "-c", code], check=True)


def _golden_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "cmf_portfolio": "commercial_individual",
                "cmf_category": "A1",
                "exposure_amount": 1_000_000,
            },
            {
                "cmf_portfolio": "commercial_individual",
                "cmf_category": "B4",
                "exposure_amount": 1_000_000,
            },
            {
                "cmf_portfolio": "commercial_individual",
                "cmf_category": None,
                "recoverable_amount": 750,
                "exposure_amount": 1_000,
            },
            _consumer_row(
                debtor_id="rut-consumo",
                days_past_due=0,
                system_dpd30_last_3m=False,
                exposure_amount=100_000,
            ),
            {
                "cmf_portfolio": "housing",
                "days_past_due": 60,
                "pvg": 95,
                "exposure_amount": 100_000,
            },
            {
                "cmf_portfolio": "commercial_group_generic_factoring",
                "days_past_due": 0,
                "ptvg_bucket": "sin_garantia",
                "factoring_recourse_type": "sin_responsabilidad_cedente_o_generica",
                "exposure_amount": 100_000,
            },
        ],
        index=["a1", "b4", "c3", "consumo", "pvg", "grupal"],
    )


def _consumer_row(
    *,
    debtor_id: str,
    days_past_due: int,
    system_dpd30_last_3m: bool,
    exposure_amount: int,
) -> dict[str, object]:
    return {
        "cmf_portfolio": "consumer",
        "debtor_id": debtor_id,
        "days_past_due": days_past_due,
        "has_housing_loan_system": False,
        "system_dpd30_last_3m": system_dpd30_last_3m,
        "cmf_product_type": "creditos_en_cuotas",
        "exposure_amount": exposure_amount,
    }


def _contingent_row(
    *,
    contingent_type: str,
    contingent_subtype: str | None,
    contingent_amount: int,
    is_default: bool,
) -> dict[str, object]:
    row: dict[str, object] = {
        "cmf_portfolio": "commercial_individual",
        "cmf_category": "A1",
        "exposure_amount": 0,
        "contingent_amount": contingent_amount,
        "contingent_type": contingent_type,
        "is_default": is_default,
    }
    if contingent_subtype is not None:
        row["contingent_subtype"] = contingent_subtype
    return row


def _expected(exposure: int, pi_percent: str, pdi_percent: str) -> Decimal:
    return (
        Decimal(str(exposure))
        * Decimal(pi_percent)
        / Decimal("100")
        * Decimal(pdi_percent)
        / Decimal("100")
    )


def _expected_decimal(exposure: Decimal, pi_percent: str, pdi_percent: str) -> Decimal:
    return exposure * Decimal(pi_percent) / Decimal("100") * Decimal(pdi_percent) / Decimal("100")


def _stable_payload(result: Any) -> tuple[str, str, tuple[str, ...], str]:
    return (
        result.detail.astype(str).to_csv(),
        result.summary.astype(str).to_csv(),
        tuple(record.model_dump_json() for record in result.records),
        result.card.model_dump_json(),
    )


def _engine() -> CmfProvisioningEngine:
    return CmfProvisioningEngine.from_config(CmfProvisioningConfig())


def _load_bundle() -> CmfMatrixBundle:
    return load_cmf_matrices(MatrixConfig())


def _replace_row(bundle: CmfMatrixBundle, replacement: CmfMatrixRow) -> CmfMatrixBundle:
    rows = tuple(
        replacement
        if row.matrix_id == replacement.matrix_id and row.row_id == replacement.row_id
        else row
        for row in bundle.rows
    )
    return bundle.model_copy(update={"rows": rows})


def _decimal_runtime() -> engine_module.DecimalRuntime:
    return engine_module.DecimalRuntime(
        decimal_cls=Decimal,
        invalid_operation_cls=InvalidOperation,
        rounding_half_up=ROUND_HALF_UP,
        zero=Decimal("0"),
        hundred=Decimal("100"),
        pe_tolerance=Decimal("0.0001"),
    )
