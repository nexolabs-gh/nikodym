"""Tests de los DTOs de ``provisioning.internal``: contrato de columnas y copias defensivas."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pandas as pd
import pytest
from pydantic import ValidationError

from nikodym.provisioning.internal.results import (
    DETAIL_COLUMNS,
    GROUP_COLUMNS,
    SUMMARY_COLUMNS,
    InternalProvisionCard,
    InternalProvisionRecord,
    InternalProvisionResult,
)


def _record(**kwargs: Any) -> InternalProvisionRecord:
    """Registro válido por operación."""
    base: dict[str, Any] = {
        "row_id": "op1",
        "portfolio": "consumer",
        "group_id": "banda_01",
        "exposure_amount": Decimal("1000"),
        "pd": Decimal("0.1"),
        "lgd": Decimal("0.5"),
        "loss_rate": Decimal("0.05"),
        "provision_amount": Decimal("50"),
    }
    base.update(kwargs)
    return InternalProvisionRecord(**base)


def _card(**kwargs: Any) -> InternalProvisionCard:
    """Card válida del método interno."""
    base: dict[str, Any] = {
        "as_of_date": "2026-01-31",
        "method": "pd_lgd",
        "grouping": "score_band",
        "pd_source": "calibration",
        "n_groups": 1,
        "n_rows": 1,
        "total_exposure": Decimal("1000"),
        "total_internal_provision": Decimal("50"),
    }
    base.update(kwargs)
    return InternalProvisionCard(**base)


def _frame(columns: tuple[str, ...]) -> pd.DataFrame:
    """Frame vacío con las columnas canónicas declaradas."""
    return pd.DataFrame({column: [] for column in columns}, columns=list(columns))


def _result(**kwargs: Any) -> InternalProvisionResult:
    """Resultado válido con los tres frames canónicos."""
    base: dict[str, Any] = {
        "detail": _frame(DETAIL_COLUMNS),
        "groups": _frame(GROUP_COLUMNS),
        "summary": _frame(SUMMARY_COLUMNS),
        "records": (_record(),),
        "card": _card(),
    }
    base.update(kwargs)
    return InternalProvisionResult(**base)


def test_record_normaliza_cero_y_admite_lgd_nula() -> None:
    """El cero se normaliza y la LGD es opcional (no existe en ``direct_loss_rate``)."""
    record = _record(provision_amount=Decimal("0.000"), lgd=None)

    assert record.provision_amount == Decimal("0")
    assert record.lgd is None
    assert _record(lgd=Decimal("0.000")).lgd == Decimal("0")


@pytest.mark.parametrize("campo", ["exposure_amount", "pd", "loss_rate", "provision_amount"])
def test_record_rechaza_montos_negativos_o_no_finitos(campo: str) -> None:
    """Un monto negativo o no finito no es una provisión (la finitud la guarda Pydantic)."""
    with pytest.raises(ValidationError, match="no pueden ser negativos"):
        _record(**{campo: Decimal("-1")})
    with pytest.raises(ValidationError, match="finite number"):
        _record(**{campo: Decimal("NaN")})
    with pytest.raises(ValidationError, match="finite number"):
        _record(**{campo: Decimal("Infinity")})


def test_record_rechaza_lgd_negativa() -> None:
    """La LGD opcional se valida igual cuando viene informada."""
    with pytest.raises(ValidationError, match="no pueden ser negativos"):
        _record(lgd=Decimal("-0.1"))


def test_record_es_frozen_y_cerrado() -> None:
    """El DTO es inmutable y no acepta campos desconocidos."""
    with pytest.raises(ValidationError):
        _record(campo_extra=1)
    with pytest.raises(ValidationError):
        _record().row_id = "otro"


def test_card_copia_metric_sections_al_acceder() -> None:
    """``metric_sections`` se copia al validar y al leer, aunque la card sea frozen."""
    payload = {"provisioning_internal": {"warning_codes": ["A"], "grupos": ("x",)}}
    card = _card(metric_sections=payload)

    payload["provisioning_internal"]["warning_codes"].append("B")
    assert card.metric_sections["provisioning_internal"]["warning_codes"] == ["A"]

    leido = card.metric_sections
    leido["provisioning_internal"]["warning_codes"].append("C")
    assert card.metric_sections["provisioning_internal"]["warning_codes"] == ["A"]

    assert _card(metric_sections=None).metric_sections == {}
    with pytest.raises(ValidationError):
        _card(metric_sections=["no es un mapping"])


def test_card_rechaza_montos_negativos() -> None:
    """El total de una card no puede ser negativo."""
    with pytest.raises(ValidationError, match="no pueden ser negativos"):
        _card(total_internal_provision=Decimal("-1"))


@pytest.mark.parametrize(
    ("campo", "columnas"),
    [("detail", DETAIL_COLUMNS), ("groups", GROUP_COLUMNS), ("summary", SUMMARY_COLUMNS)],
)
def test_result_exige_las_columnas_canonicas(campo: str, columnas: tuple[str, ...]) -> None:
    """Cada frame publicado debe traer exactamente las columnas canónicas de SDD-28 §4.1."""
    with pytest.raises(ValidationError, match=f"{campo} debe ser un pandas.DataFrame"):
        _result(**{campo: object()})

    with pytest.raises(ValidationError, match=f"{campo} debe tener exactamente las columnas"):
        _result(**{campo: _frame(columnas).drop(columns=[columnas[0]])})

    with pytest.raises(ValidationError, match=f"{campo} debe tener exactamente las columnas"):
        _result(**{campo: _frame(columnas[::-1])})


def test_result_entrega_copias_defensivas_de_los_frames() -> None:
    """Mutar el frame devuelto no contamina el resultado publicado."""
    detail = pd.DataFrame(
        [
            {
                "row_id": "op1",
                "portfolio": "consumer",
                "group_id": "banda_01",
                "exposure_amount": Decimal("1000"),
                "pd": Decimal("0.1"),
                "lgd": Decimal("0.5"),
                "loss_rate": Decimal("0.05"),
                "provision_amount": 50,
                "warning_codes": (),
            }
        ],
        columns=list(DETAIL_COLUMNS),
        index=pd.Index(["op1"], name="loan_id"),
    )
    result = _result(detail=detail)

    leido = result.detail
    leido.loc["op1", "provision_amount"] = 0
    assert result.detail.loc["op1", "provision_amount"] == 50

    detail.loc["op1", "provision_amount"] = 999
    assert result.detail.loc["op1", "provision_amount"] == 50


def test_result_no_expone_term_structure() -> None:
    """El método interno del B-1 §3 es puntual, no lifetime (CT-2)."""
    assert _result().term_structure() is None


def test_columnas_canonicas_publicadas() -> None:
    """El contrato de columnas es parte de la API: ``groups`` es la tabla que pide un validador."""
    assert DETAIL_COLUMNS == (
        "row_id",
        "portfolio",
        "group_id",
        "exposure_amount",
        "pd",
        "lgd",
        "loss_rate",
        "provision_amount",
        "warning_codes",
    )
    assert GROUP_COLUMNS == (
        "group_id",
        "portfolio",
        "n_operations",
        "total_exposure",
        "pd_group",
        "lgd_group",
        "expected_loss_rate",
        "provision_amount",
        "warning_codes",
    )
    assert SUMMARY_COLUMNS == (
        "portfolio",
        "n_groups",
        "n_operations",
        "total_exposure",
        "total_provision",
        "weighted_expected_loss_rate",
        "warning_codes",
    )
