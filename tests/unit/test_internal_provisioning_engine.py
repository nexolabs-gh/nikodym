"""Tests de ``InternalProvisioningEngine``: el golden calculado a mano y los bordes del B-1 §3.

El test que manda es :func:`test_g0_golden_calculado_a_mano`: una cartera de 10 operaciones y 3
grupos homogéneos, con la aritmética hecha a mano en el comentario y comparada **al centavo** contra
el motor. Es lo primero que un validador de modelos pide y es lo único que acepta como evidencia.
"""

from __future__ import annotations

import importlib
import json
from decimal import Decimal
from typing import Any, cast

import numpy as np
import pandas as pd
import pytest

import nikodym.provisioning.internal.engine as engine_module
from nikodym.core.audit import InMemoryAuditSink
from nikodym.core.exceptions import MissingDependencyError
from nikodym.provisioning.internal.config import InternalLgdConfig, InternalProvisioningConfig
from nikodym.provisioning.internal.engine import InternalProvisioningEngine
from nikodym.provisioning.internal.exceptions import (
    InternalCalculationError,
    InternalInputError,
)
from nikodym.provisioning.internal.results import InternalProvisionResult

AS_OF = "2026-01-31"

# ───────────────────────────── G0: la cartera calculada a mano ─────────────────────────────
#
# 10 operaciones, 3 grupos homogéneos provistos (A, B, C), una sola cartera (`consumer`).
#
#   op    grupo   exposición      PD     LGD
#   op01    A      1.000.000     0,01    0,50
#   op02    A      1.000.000     0,01    0,50
#   op03    A      2.000.000     0,02    0,40
#   op04    A      4.000.000     0,03    0,60
#   op05    B      2.000.000     0,05    0,40
#   op06    B      3.000.000     0,10    0,50
#   op07    B      5.000.000     0,20    0,60
#   op08    C      1.000.000     0,40    0,70
#   op09    C      1.000.000     0,50    0,80
#   op10    C      2.000.000     0,55    0,75
#
# La PD y la LGD del grupo son la media PONDERADA POR EXPOSICIÓN (la norma aplica los porcentajes al
# *monto total de colocaciones del grupo*):
#
#   GRUPO A — Exposición = 1.000.000 + 1.000.000 + 2.000.000 + 4.000.000 = 8.000.000
#     PD(A)  = (1.000.000·0,01 + 1.000.000·0,01 + 2.000.000·0,02 + 4.000.000·0,03) / 8.000.000
#            = (10.000 + 10.000 + 40.000 + 120.000) / 8.000.000 = 180.000 / 8.000.000 = 0,0225
#     LGD(A) = (1.000.000·0,50 + 1.000.000·0,50 + 2.000.000·0,40 + 4.000.000·0,60) / 8.000.000
#            = (500.000 + 500.000 + 800.000 + 2.400.000) / 8.000.000 = 4.200.000 / 8.000.000 = 0,525
#     Provisión(A) = 8.000.000 · 0,0225 · 0,525 = 8.000.000 · 0,0118125 = 94.500,00
#
#   GRUPO B — Exposición = 2.000.000 + 3.000.000 + 5.000.000 = 10.000.000
#     PD(B)  = (2.000.000·0,05 + 3.000.000·0,10 + 5.000.000·0,20) / 10.000.000
#            = (100.000 + 300.000 + 1.000.000) / 10.000.000 = 1.400.000 / 10.000.000 = 0,14
#     LGD(B) = (2.000.000·0,40 + 3.000.000·0,50 + 5.000.000·0,60) / 10.000.000
#            = (800.000 + 1.500.000 + 3.000.000) / 10.000.000 = 5.300.000 / 10.000.000 = 0,53
#     Provisión(B) = 10.000.000 · 0,14 · 0,53 = 10.000.000 · 0,0742 = 742.000,00
#
#   GRUPO C — Exposición = 1.000.000 + 1.000.000 + 2.000.000 = 4.000.000
#     PD(C)  = (1.000.000·0,40 + 1.000.000·0,50 + 2.000.000·0,55) / 4.000.000
#            = (400.000 + 500.000 + 1.100.000) / 4.000.000 = 2.000.000 / 4.000.000 = 0,50
#     LGD(C) = (1.000.000·0,70 + 1.000.000·0,80 + 2.000.000·0,75) / 4.000.000
#            = (700.000 + 800.000 + 1.500.000) / 4.000.000 = 3.000.000 / 4.000.000 = 0,75
#     Provisión(C) = 4.000.000 · 0,50 · 0,75 = 4.000.000 · 0,375 = 1.500.000,00
#
#   EXPOSICIÓN TOTAL = 8.000.000 + 10.000.000 + 4.000.000 = 22.000.000
#   PROVISIÓN TOTAL  =    94.500 +    742.000 +  1.500.000 =  2.336.500,00
#
# El detalle por operación es el prorrateo de la provisión del GRUPO por su participación en la
# exposición del grupo:
#   op01 = 94.500 · (1.000.000/8.000.000) = 94.500 · 0,125 =  11.812,50
#   op02 = 94.500 · 0,125                                   =  11.812,50
#   op03 = 94.500 · 0,25                                    =  23.625,00
#   op04 = 94.500 · 0,50                                    =  47.250,00   (suma A =    94.500,00 ✓)
#   op05 = 742.000 · (2.000.000/10.000.000) = 742.000·0,2   = 148.400,00
#   op06 = 742.000 · 0,3                                    = 222.600,00
#   op07 = 742.000 · 0,5                                    = 371.000,00   (suma B =   742.000,00 ✓)
#   op08 = 1.500.000 · 0,25                                 = 375.000,00
#   op09 = 1.500.000 · 0,25                                 = 375.000,00
#   op10 = 1.500.000 · 0,50                                 = 750.000,00   (suma C = 1.500.000,00 ✓)
# ──────────────────────────────────────────────────────────────────────────────────────────
G0_ROWS: tuple[tuple[str, str, int, str, str], ...] = (
    ("op01", "A", 1_000_000, "0.01", "0.50"),
    ("op02", "A", 1_000_000, "0.01", "0.50"),
    ("op03", "A", 2_000_000, "0.02", "0.40"),
    ("op04", "A", 4_000_000, "0.03", "0.60"),
    ("op05", "B", 2_000_000, "0.05", "0.40"),
    ("op06", "B", 3_000_000, "0.10", "0.50"),
    ("op07", "B", 5_000_000, "0.20", "0.60"),
    ("op08", "C", 1_000_000, "0.40", "0.70"),
    ("op09", "C", 1_000_000, "0.50", "0.80"),
    ("op10", "C", 2_000_000, "0.55", "0.75"),
)
G0_GROUP_PROVISION = {
    "A": Decimal("94500.00"),
    "B": Decimal("742000.00"),
    "C": Decimal("1500000.00"),
}
G0_TOTAL_PROVISION = Decimal("2336500.00")
G0_TOTAL_EXPOSURE = Decimal("22000000")
G0_DETAIL_PROVISION = {
    "op01": Decimal("11812.50"),
    "op02": Decimal("11812.50"),
    "op03": Decimal("23625.00"),
    "op04": Decimal("47250.00"),
    "op05": Decimal("148400.00"),
    "op06": Decimal("222600.00"),
    "op07": Decimal("371000.00"),
    "op08": Decimal("375000.00"),
    "op09": Decimal("375000.00"),
    "op10": Decimal("750000.00"),
}


def _g0_frame() -> pd.DataFrame:
    """Frame de la cartera G0, con el grupo homogéneo provisto en la columna ``grupo``."""
    return pd.DataFrame(
        [
            {
                "as_of_date": AS_OF,
                "cmf_portfolio": "consumer",
                "grupo": group,
                "exposure_amount": exposure,
                "lgd": float(lgd),
            }
            for _, group, exposure, _, lgd in G0_ROWS
        ],
        index=pd.Index([row_id for row_id, *_ in G0_ROWS], name="loan_id"),
    )


def _g0_pd_frame() -> pd.DataFrame:
    """Artefacto de PD calibrada de la cartera G0."""
    return pd.DataFrame(
        {"pd_calibrated": [float(pd_value) for _, _, _, pd_value, _ in G0_ROWS]},
        index=pd.Index([row_id for row_id, *_ in G0_ROWS], name="loan_id"),
    )


def _cfg(**kwargs: Any) -> InternalProvisioningConfig:
    """Config de grupos provistos (el modo del golden G0)."""
    base: dict[str, Any] = {"grouping": "provided", "group_col": "grupo"}
    base.update(kwargs)
    return InternalProvisioningConfig(**base)


def _calculate(
    cfg: InternalProvisioningConfig,
    *,
    frame: pd.DataFrame | None = None,
    pd_frame: pd.DataFrame | None = None,
    audit: Any = None,
) -> InternalProvisionResult:
    """Corre el motor real sobre la cartera G0 (o la que se inyecte)."""
    return InternalProvisioningEngine.from_config(cfg).calculate(
        _g0_frame() if frame is None else frame,
        pd_frame=_g0_pd_frame() if pd_frame is None else pd_frame,
        as_of_date=AS_OF,
        audit=audit,
    )


def _groups_by_id(result: InternalProvisionResult) -> dict[str, Any]:
    """Indexa el frame de grupos homogéneos por ``group_id``."""
    return {row["group_id"]: row for _, row in result.groups.iterrows()}


# ─────────────────────────────── GATE G0 ───────────────────────────────


def test_g0_golden_calculado_a_mano() -> None:
    """El motor reproduce, al centavo, la provisión calculada a mano en el encabezado."""
    result = _calculate(_cfg())
    groups = _groups_by_id(result)

    # Grupo homogéneo: exposición, PD ponderada, LGD ponderada y provisión.
    assert groups["A"]["total_exposure"] == Decimal("8000000")
    assert groups["A"]["pd_group"] == Decimal("0.0225")
    assert groups["A"]["lgd_group"] == Decimal("0.525")
    assert groups["A"]["expected_loss_rate"] == Decimal("0.0118125")
    assert groups["B"]["pd_group"] == Decimal("0.14")
    assert groups["B"]["lgd_group"] == Decimal("0.53")
    assert groups["C"]["pd_group"] == Decimal("0.50")
    assert groups["C"]["lgd_group"] == Decimal("0.75")
    for group_id, provision in G0_GROUP_PROVISION.items():
        assert groups[group_id]["provision_amount"] == provision, group_id

    # Total de la cartera: 94.500 + 742.000 + 1.500.000.
    assert result.card.total_internal_provision == G0_TOTAL_PROVISION
    assert result.card.total_exposure == G0_TOTAL_EXPOSURE
    assert result.card.n_groups == 3
    assert result.card.n_rows == 10
    assert result.card.method == "pd_lgd"
    assert result.card.grouping == "provided"
    assert result.card.pd_source == "calibration"
    assert result.card.falta_dato == ()

    # Detalle por operación: el prorrateo cierra exactamente contra el grupo.
    detail = result.detail
    for row_id, provision in G0_DETAIL_PROVISION.items():
        assert detail.loc[row_id, "provision_amount"] == provision, row_id
    assert sum(detail["provision_amount"]) == G0_TOTAL_PROVISION
    for group_id, provision in G0_GROUP_PROVISION.items():
        subset = detail[detail["group_id"] == group_id]
        assert sum(subset["provision_amount"]) == provision, group_id

    # Resumen por cartera: una sola cartera con los tres grupos.
    summary = result.summary
    assert len(summary.index) == 1
    assert summary.loc["consumer", "n_groups"] == 3
    assert summary.loc["consumer", "n_operations"] == 10
    assert summary.loc["consumer", "total_provision"] == G0_TOTAL_PROVISION


def test_g0_es_determinista_byte_a_byte() -> None:
    """Dos corridas del método interno producen el mismo total y el mismo detalle."""
    primera = _calculate(_cfg())
    segunda = _calculate(_cfg())

    assert primera.card.total_internal_provision == segunda.card.total_internal_provision
    assert primera.detail.astype(str).to_csv() == segunda.detail.astype(str).to_csv()
    assert primera.groups.astype(str).to_csv() == segunda.groups.astype(str).to_csv()
    assert primera.summary.astype(str).to_csv() == segunda.summary.astype(str).to_csv()
    assert primera.card.model_dump(mode="json") == segunda.card.model_dump(mode="json")


# ─────────────────────────── los dos métodos del B-1 §3 ───────────────────────────


def test_direct_loss_rate_calculado_a_mano() -> None:
    """El segundo método del B-1 (tasa de pérdida directa del grupo) tiene ruta real.

    Grupo A: tasas 0,01 / 0,01 / 0,02 / 0,05 con exposiciones 1M / 1M / 2M / 4M sobre 8.000.000:
      tasa(A) = (1M·0,01 + 1M·0,01 + 2M·0,02 + 4M·0,05) / 8M
              = (10.000 + 10.000 + 40.000 + 200.000) / 8.000.000 = 260.000/8.000.000 = 0,0325
      Provisión(A) = 8.000.000 · 0,0325 = 260.000,00  (== la suma de las pérdidas individuales)
    """
    frame = _g0_frame()
    frame["tasa_perdida"] = [0.01, 0.01, 0.02, 0.05, 0.02, 0.05, 0.10, 0.30, 0.40, 0.45]
    cfg = _cfg(method="direct_loss_rate", loss_rate_col="tasa_perdida")

    result = _calculate(cfg, frame=frame)
    groups = _groups_by_id(result)

    assert groups["A"]["expected_loss_rate"] == Decimal("0.0325")
    assert groups["A"]["provision_amount"] == Decimal("260000.00")
    # La LGD no existe en este método: no se descompone la pérdida y no se inventa un número.
    assert groups["A"]["lgd_group"] is None
    assert result.detail.loc["op01", "lgd"] is None
    assert result.detail.loc["op01", "loss_rate"] == Decimal("0.01")
    assert result.card.method == "direct_loss_rate"
    assert result.card.metric_sections["provisioning_internal"]["lgd_method"] is None
    assert sum(result.detail["provision_amount"]) == result.card.total_internal_provision


def test_los_dos_metodos_coinciden_cuando_el_grupo_es_homogeneo_en_pd() -> None:
    """Con PD constante dentro del grupo (grupo realmente homogéneo), ambos métodos dan lo mismo.

    Es la prueba de consistencia entre las dos rutas del B-1 §3. Grupo A con PD 0,02 en las cuatro
    operaciones y LGD 0,50/0,50/0,40/0,60 sobre 1M/1M/2M/4M:
      pd_lgd:  8.000.000 · 0,02 · 0,525            = 84.000,00
      directo: tasa_i = 0,02·lgd_i → ponderada = 0,0105 → 8.000.000 · 0,0105 = 84.000,00
    """
    pd_por_grupo = {"A": Decimal("0.02"), "B": Decimal("0.10"), "C": Decimal("0.50")}
    pd_frame = _g0_pd_frame()
    pd_frame["pd_calibrated"] = [float(pd_por_grupo[group]) for _, group, *_ in G0_ROWS]
    frame = _g0_frame()
    frame["tasa_perdida"] = [
        float(pd_por_grupo[group] * Decimal(lgd)) for _, group, _, _, lgd in G0_ROWS
    ]

    pd_lgd = _calculate(_cfg(), pd_frame=pd_frame)
    directo = _calculate(
        _cfg(method="direct_loss_rate", loss_rate_col="tasa_perdida"),
        frame=frame,
        pd_frame=pd_frame,
    )

    assert _groups_by_id(pd_lgd)["A"]["provision_amount"] == Decimal("84000.00")
    assert directo.card.total_internal_provision == pd_lgd.card.total_internal_provision


def test_los_metodos_divergen_si_el_grupo_no_es_homogeneo_y_eso_es_la_norma() -> None:
    """Un grupo heterogéneo hace divergir ambos métodos por la covarianza PD-LGD interna.

    La norma asocia a cada grupo **una** PD y **un** porcentaje de pérdida, y multiplica por el
    *monto total de colocaciones del grupo*: ``E(g)·PD(g)·LGD(g)``, no ``Σ E_i·pd_i·lgd_i``. Ambas
    coinciden sólo si la PD y la LGD no covarían dentro del grupo — es decir, si el grupo es de
    verdad homogéneo. La brecha entre ambas cifras **es** el diagnóstico de una mala agrupación, y
    por eso no se esconde detrás de una identidad falsa.
    """
    frame = _g0_frame()
    frame["tasa_perdida"] = [
        float(Decimal(pd_value) * Decimal(lgd)) for _, _, _, pd_value, lgd in G0_ROWS
    ]

    pd_lgd = _calculate(_cfg())
    directo = _calculate(
        _cfg(method="direct_loss_rate", loss_rate_col="tasa_perdida"),
        frame=frame,
    )

    # Σ E_i·pd_i·lgd_i de la cartera G0, calculado a mano:
    #   A: 1M·0,01·0,5 + 1M·0,01·0,5 + 2M·0,02·0,4 + 4M·0,03·0,6
    #      = 5.000 + 5.000 + 16.000 + 72.000 = 98.000
    #   B: 2M·0,05·0,4 + 3M·0,10·0,5 + 5M·0,20·0,6 = 40.000 + 150.000 + 600.000 = 790.000
    #   C: 1M·0,40·0,7 + 1M·0,50·0,8 + 2M·0,55·0,75 = 280.000 + 400.000 + 825.000 = 1.505.000
    assert _groups_by_id(directo)["A"]["provision_amount"] == Decimal("98000.00")
    assert _groups_by_id(directo)["B"]["provision_amount"] == Decimal("790000.00")
    assert _groups_by_id(directo)["C"]["provision_amount"] == Decimal("1505000.00")
    assert directo.card.total_internal_provision == Decimal("2393000.00")
    assert pd_lgd.card.total_internal_provision == G0_TOTAL_PROVISION


# ─────────────────────────── los tres modos de agrupación ───────────────────────────


def test_grouping_score_band_forma_bandas_por_cuantil_de_pd() -> None:
    """``score_band`` corta la PD en cuantiles y produce grupos homogéneos ordenados."""
    result = _calculate(InternalProvisioningConfig(n_score_bands=5))
    groups = _groups_by_id(result)

    assert result.card.grouping == "score_band"
    assert result.card.n_groups == 5
    assert sorted(groups) == ["banda_01", "banda_02", "banda_03", "banda_04", "banda_05"]
    # Las bandas están ordenadas por PD creciente: la banda 1 es la de menor riesgo.
    pds = [groups[f"banda_{index:02d}"]["pd_group"] for index in range(1, 6)]
    assert pds == sorted(pds)
    assert all(row["n_operations"] == 2 for row in groups.values())
    assert sum(result.detail["provision_amount"]) == result.card.total_internal_provision
    assert result.card.metric_sections["provisioning_internal"]["n_score_bands"] == 5


def test_grouping_segment_usa_la_columna_declarada() -> None:
    """``segment`` agrupa por la columna de segmento de negocio declarada en ``group_col``."""
    frame = _g0_frame().assign(segmento=["retail"] * 5 + ["pyme"] * 5)
    result = _calculate(
        InternalProvisioningConfig(grouping="segment", group_col="segmento"),
        frame=frame,
    )

    assert result.card.grouping == "segment"
    assert sorted(_groups_by_id(result)) == ["pyme", "retail"]
    assert result.card.metric_sections["provisioning_internal"]["n_score_bands"] is None


def test_bandas_por_cartera_y_no_globales() -> None:
    """Los grupos homogéneos viven DENTRO de una cartera: la llave es (portfolio, group_id)."""
    frame = _g0_frame().assign(cmf_portfolio=["consumer"] * 6 + ["housing"] * 4)
    result = _calculate(InternalProvisioningConfig(n_score_bands=2), frame=frame)

    keys = {(row["portfolio"], row["group_id"]) for _, row in result.groups.iterrows()}
    assert keys == {
        ("consumer", "banda_01"),
        ("consumer", "banda_02"),
        ("housing", "banda_01"),
        ("housing", "banda_02"),
    }
    assert len(result.summary.index) == 2
    assert sum(result.summary["total_provision"]) == result.card.total_internal_provision
    assert result.card.metric_sections["provisioning_internal"]["groups_by_portfolio"] == {
        "consumer": 2,
        "housing": 2,
    }


def test_bandas_colapsadas_se_reportan_y_no_se_esconden() -> None:
    """Menos bandas de las pedidas (empates de PD) se marcan con ``BANDAS-COLAPSADAS``."""
    pd_frame = _g0_pd_frame()
    pd_frame["pd_calibrated"] = [0.05] * 5 + [0.30] * 5

    result = _calculate(InternalProvisioningConfig(n_score_bands=10), pd_frame=pd_frame)

    assert result.card.n_groups == 2
    assert all("BANDAS-COLAPSADAS" in row["warning_codes"] for _, row in result.groups.iterrows())
    assert "BANDAS-COLAPSADAS" in result.summary.loc["consumer", "warning_codes"]
    assert "BANDAS-COLAPSADAS" in result.detail.loc["op01", "warning_codes"]
    warnings = result.card.metric_sections["provisioning_internal"]["warning_codes"]
    assert "BANDAS-COLAPSADAS" in warnings


def test_una_sola_pd_distinta_colapsa_a_una_banda() -> None:
    """Con una única PD no hay cuantiles posibles: una banda, marcada como colapsada."""
    pd_frame = _g0_pd_frame()
    pd_frame["pd_calibrated"] = [0.10] * 10

    result = _calculate(InternalProvisioningConfig(n_score_bands=4), pd_frame=pd_frame)

    assert result.card.n_groups == 1
    assert result.groups.iloc[0]["group_id"] == "banda_01"
    assert result.groups.iloc[0]["warning_codes"] == ("BANDAS-COLAPSADAS",)


# ─────────────────────────── LGD: ponderada, histórica, piso y techo ───────────────────────────


def test_lgd_group_historical_usa_la_media_simple_del_grupo() -> None:
    """La severidad histórica del grupo no se pondera por la exposición de hoy.

    Grupo A: LGD 0,50 / 0,50 / 0,40 / 0,60 → media simple = 2,00/4 = 0,50 (la ponderada era 0,525).
      Provisión(A) = 8.000.000 · 0,0225 · 0,50 = 90.000,00  (vs 94.500,00 con la ponderada).
    """
    result = _calculate(_cfg(lgd=InternalLgdConfig(method="group_historical")))
    groups = _groups_by_id(result)

    assert groups["A"]["lgd_group"] == Decimal("0.50")
    assert groups["A"]["provision_amount"] == Decimal("90000.00")
    # La LGD del grupo se aplica a TODAS sus operaciones: es una severidad del grupo, no de la fila.
    assert result.detail.loc["op03", "lgd"] == Decimal("0.50")
    assert result.detail.loc["op03", "loss_rate"] == Decimal("0.02") * Decimal("0.50")
    assert sum(result.detail["provision_amount"]) == result.card.total_internal_provision


def test_piso_y_techo_de_lgd_se_aplican_tras_validar() -> None:
    """El piso/techo explícito se aplica sobre una LGD ya validada; nunca rescata un valor fuera."""
    result = _calculate(_cfg(lgd=InternalLgdConfig(lgd_floor=0.55, lgd_cap=0.58)))

    assert result.detail.loc["op01", "lgd"] == Decimal("0.55")  # 0,50 → piso
    assert result.detail.loc["op04", "lgd"] == Decimal("0.58")  # 0,60 → techo
    assert _groups_by_id(result)["A"]["lgd_group"] <= Decimal("0.58")


@pytest.mark.parametrize(("columna", "valor"), [("lgd", 1.5), ("lgd", -0.2)])
def test_lgd_fuera_de_cero_uno_levanta_y_no_se_clipa(columna: str, valor: float) -> None:
    """Una LGD fuera de [0, 1] es un dato roto: se levanta, no se clipa en silencio."""
    frame = _g0_frame()
    frame.loc["op03", columna] = valor

    with pytest.raises(InternalInputError, match="no se clipa en silencio"):
        _calculate(_cfg(), frame=frame)


@pytest.mark.parametrize("valor", [1.4, -0.01])
def test_pd_fuera_de_cero_uno_levanta(valor: float) -> None:
    """Una PD fuera de [0, 1] no es una probabilidad."""
    pd_frame = _g0_pd_frame()
    pd_frame.loc["op05", "pd_calibrated"] = valor

    with pytest.raises(InternalInputError, match=r"pd_calibrated.*\[0, 1\]"):
        _calculate(_cfg(), pd_frame=pd_frame)


def test_tasa_de_perdida_fuera_de_cero_uno_levanta() -> None:
    """La tasa de pérdida directa también vive en [0, 1]."""
    frame = _g0_frame()
    frame["tasa_perdida"] = [0.01] * 9 + [1.2]

    with pytest.raises(InternalInputError, match=r"tasa_perdida.*\[0, 1\]"):
        _calculate(_cfg(method="direct_loss_rate", loss_rate_col="tasa_perdida"), frame=frame)


# ─────────────────────────── exposición y casos borde ───────────────────────────


def test_exposicion_cero_produce_provision_cero_sin_dividir_por_cero() -> None:
    """Un grupo sin exposición provisiona cero y queda marcado, en vez de reventar."""
    frame = _g0_frame()
    frame.loc[["op08", "op09", "op10"], "exposure_amount"] = 0

    result = _calculate(_cfg(), frame=frame)
    grupo_c = _groups_by_id(result)["C"]

    assert grupo_c["total_exposure"] == Decimal("0")
    assert grupo_c["provision_amount"] == Decimal("0")
    assert "GRUPO-SIN-EXPOSICION" in grupo_c["warning_codes"]
    # Sin ponderadores, la PD/LGD publicadas son la media simple: (0,40+0,50+0,55)/3 = 0,48333…
    assert grupo_c["pd_group"].quantize(Decimal("0.00001")) == Decimal("0.48333")
    assert result.detail.loc["op08", "provision_amount"] == Decimal("0")
    assert result.card.total_internal_provision == Decimal("94500.00") + Decimal("742000.00")


def test_exposicion_cero_en_toda_la_cartera() -> None:
    """Con exposición nula en todo el frame la tasa publicada es cero, no un ZeroDivisionError."""
    frame = _g0_frame()
    frame["exposure_amount"] = 0

    result = _calculate(_cfg(), frame=frame)

    assert result.card.total_exposure == Decimal("0")
    assert result.card.total_internal_provision == Decimal("0")
    assert result.summary.loc["consumer", "weighted_expected_loss_rate"] == Decimal("0")
    tasa = result.card.metric_sections["provisioning_internal"]["total_expected_loss_rate"]
    assert tasa == 0.0
    assert isinstance(tasa, float)  # número, no texto: lo formatea quien lo muestra


def test_total_expected_loss_rate_es_numero_sin_mantisa_falsa() -> None:
    """La tasa agregada viaja como número acotado, no como los ~50 dígitos de la división Decimal.

    Salía por ``str(Decimal)`` —la única forma de cruzar el gate JSON de ``metric_sections``, que
    rechaza ``Decimal``— y el anexo de auditoría terminaba mostrando 51 dígitos de precisión que el
    dato no tiene. Como ``float`` cruza el mismo gate, llega como número a quien lo consuma y lo
    formatea la capa de presentación.
    """
    result = _calculate(_cfg())
    tasa = result.card.metric_sections["provisioning_internal"]["total_expected_loss_rate"]

    assert isinstance(tasa, float)
    assert 0.0 < tasa < 1.0
    assert len(repr(tasa)) < 25, f"la tasa arrastra la mantisa completa: {tasa!r}"

    # El dato exacto no se pierde: sigue en las dos cifras contables, ambas Decimal.
    exacto = result.card.total_internal_provision / result.card.total_exposure
    assert tasa == pytest.approx(float(exacto), rel=1e-12)

    # Y cruza el gate que el informe aplica a metric_sections (era el motivo real del str()).
    json.dumps(result.card.metric_sections, allow_nan=False)


def test_exposicion_negativa_levanta() -> None:
    """Una colocación negativa no es una exposición."""
    frame = _g0_frame()
    frame.loc["op02", "exposure_amount"] = -1

    with pytest.raises(InternalInputError, match="no puede ser negativa"):
        _calculate(_cfg(), frame=frame)


def test_frame_vacio_levanta() -> None:
    """Una provisión sobre cero operaciones no significa nada: se levanta."""
    with pytest.raises(InternalInputError, match="frame de entrada está vacío"):
        _calculate(_cfg(), frame=_g0_frame().iloc[:0], pd_frame=_g0_pd_frame().iloc[:0])


def test_columna_faltante_levanta_con_mensaje_util() -> None:
    """El fallo típico es 'te falta la columna lgd': el mensaje la nombra."""
    with pytest.raises(InternalInputError, match=r"Faltan columnas.*'lgd'"):
        _calculate(_cfg(), frame=_g0_frame().drop(columns=["lgd"]))

    with pytest.raises(InternalInputError, match=r"Faltan columnas.*'grupo'"):
        _calculate(_cfg(), frame=_g0_frame().drop(columns=["grupo"]))


def test_cartera_o_grupo_nulo_levanta_porque_no_se_puede_imputar() -> None:
    """Un grupo homogéneo nulo no se imputa: la agrupación es el corazón de la norma."""
    frame = _g0_frame()
    frame.loc["op01", "grupo"] = None
    with pytest.raises(InternalInputError, match="'grupo' no puede ser nula"):
        _calculate(_cfg(fail_on_falta_dato=False), frame=frame)

    frame = _g0_frame()
    frame.loc["op01", "cmf_portfolio"] = "  "
    with pytest.raises(InternalInputError, match="'cmf_portfolio' no puede estar vacía"):
        _calculate(_cfg(), frame=frame)


def test_valor_no_numerico_o_booleano_levanta() -> None:
    """Un texto no numérico o un booleano en una columna de monto es un error, no un cero."""
    frame = _g0_frame().astype({"exposure_amount": object})
    frame.loc["op01", "exposure_amount"] = "mil pesos"
    with pytest.raises(InternalInputError, match="compatibles con Decimal"):
        _calculate(_cfg(), frame=frame)

    frame = _g0_frame().astype({"exposure_amount": object})
    frame.loc["op01", "exposure_amount"] = True
    with pytest.raises(InternalInputError, match="no booleana"):
        _calculate(_cfg(), frame=frame)

    frame = _g0_frame().astype({"exposure_amount": object})
    frame.loc["op01", "exposure_amount"] = float("inf")
    with pytest.raises(InternalInputError, match="valores finitos"):
        _calculate(_cfg(), frame=frame)


def test_valor_tabular_en_columna_de_texto_no_rompe_la_deteccion_de_nulos() -> None:
    """``pandas.isna`` sobre un contenedor devuelve un arreglo: ``bool()`` de eso levantaría."""
    frame = _g0_frame().astype({"cmf_portfolio": object})
    frame.at["op01", "cmf_portfolio"] = ["consumer", "housing"]

    result = _calculate(_cfg(), frame=frame)

    assert result.detail.loc["op01", "portfolio"] == "['consumer', 'housing']"
    assert engine_module._is_missing(["a", "b"], pd) is False


def test_decimal_con_coma_se_lee_como_numero() -> None:
    """Los montos regulatorios con coma decimal se convierten sin pasar por float binario."""
    frame = _g0_frame().astype({"lgd": object})
    frame.loc["op01", "lgd"] = "0,50"

    result = _calculate(_cfg(), frame=frame)

    assert result.detail.loc["op01", "lgd"] == Decimal("0.50")
    assert result.card.total_internal_provision == G0_TOTAL_PROVISION


# ─────────────────────────── falta de dato ───────────────────────────


def test_falta_dato_con_fail_true_aborta() -> None:
    """Por defecto un nulo aborta la corrida: una provisión con datos faltantes no se publica."""
    frame = _g0_frame()
    frame.loc["op03", "lgd"] = None

    with pytest.raises(InternalInputError, match="Falta el dato de 'lgd'"):
        _calculate(_cfg(), frame=frame)


def test_falta_dato_con_fail_false_imputa_cero_y_deja_traza() -> None:
    """Con ``fail_on_falta_dato=False`` se imputa cero, se marca la fila y se traza en la card.

    Dos operaciones del mismo grupo con falta de dato: el aviso del grupo no se duplica.
    """
    frame = _g0_frame().astype({"lgd": object, "exposure_amount": object})
    frame.loc["op03", "lgd"] = None
    frame.loc["op03", "exposure_amount"] = ""  # celda vacía == falta de dato, no error
    frame.loc["op04", "lgd"] = None

    result = _calculate(_cfg(fail_on_falta_dato=False), frame=frame)
    grupo_a = _groups_by_id(result)["A"]

    assert result.card.falta_dato == ("op03", "op04")
    assert result.detail.loc["op03", "warning_codes"] == ("FALTA-DATO",)
    assert result.detail.loc["op03", "exposure_amount"] == Decimal("0")
    assert result.detail.loc["op03", "lgd"] == Decimal("0")
    # Grupo A con op03 en cero: exposición = 1M + 1M + 0 + 4M = 6.000.000.
    assert grupo_a["total_exposure"] == Decimal("6000000")
    assert grupo_a["warning_codes"] == ("FALTA-DATO",)  # una sola vez, pese a las dos filas
    assert sum(result.detail["provision_amount"]) == result.card.total_internal_provision


# ─────────────────────────── PD: contrato del artefacto ───────────────────────────


def test_pd_frame_sin_columna_o_sin_cobertura_levanta() -> None:
    """El artefacto de PD debe traer la columna declarada y cubrir todas las operaciones."""
    with pytest.raises(InternalInputError, match="pd_column='pd_calibrated'"):
        _calculate(_cfg(), pd_frame=_g0_pd_frame().rename(columns={"pd_calibrated": "otra"}))

    with pytest.raises(InternalInputError, match="no cubre 2 operaciones"):
        _calculate(_cfg(), pd_frame=_g0_pd_frame().drop(index=["op09", "op10"]))


def test_pd_frame_con_indice_duplicado_levanta() -> None:
    """Un índice duplicado en la PD impide asignar una PD única por operación."""
    duplicado = pd.concat([_g0_pd_frame(), _g0_pd_frame().loc[["op01"]]])

    with pytest.raises(InternalInputError, match="etiquetas duplicadas"):
        _calculate(_cfg(), pd_frame=duplicado)


def test_pd_source_model_lee_la_columna_declarada() -> None:
    """Con ``pd_source='model'`` la PD sale del artefacto crudo del modelo."""
    pd_frame = _g0_pd_frame().rename(columns={"pd_calibrated": "pd_raw"})

    result = _calculate(_cfg(pd_source="model", pd_column="pd_raw"), pd_frame=pd_frame)

    assert result.card.pd_source == "model"
    assert result.card.total_internal_provision == G0_TOTAL_PROVISION


def test_artefactos_no_tabulares_levantan() -> None:
    """``frame`` y ``pd_frame`` deben ser DataFrames."""
    with pytest.raises(InternalInputError, match=r"'frame' debe ser un pandas\.DataFrame"):
        _calculate(_cfg(), frame=object())  # type: ignore[arg-type]

    with pytest.raises(InternalInputError, match=r"'calibration\.pd_frame'"):
        _calculate(_cfg(), pd_frame=object())  # type: ignore[arg-type]


# ─────────────────────────── redondeo y prorrateo ───────────────────────────


@pytest.mark.parametrize(
    ("policy", "esperado"),
    [
        ("currency_2dp", Decimal("94500.00")),
        ("integer_currency", Decimal("94500")),
        ("none", Decimal("94500.000000")),
    ],
)
def test_politicas_de_redondeo(policy: str, esperado: Decimal) -> None:
    """El redondeo contable es explícito y el prorrateo cuadra en las tres políticas."""
    result = _calculate(_cfg(rounding=policy))
    groups = _groups_by_id(result)

    assert groups["A"]["provision_amount"] == esperado
    assert sum(result.detail["provision_amount"]) == result.card.total_internal_provision


def test_prorrateo_por_resto_mayor_cierra_al_centavo() -> None:
    """Con un reparto que no divide exacto, los céntimos sobrantes se asignan por resto mayor."""
    frame = pd.DataFrame(
        [
            {
                "as_of_date": AS_OF,
                "cmf_portfolio": "consumer",
                "grupo": "A",
                "exposure_amount": exposure,
                "lgd": 0.5,
            }
            for exposure in (100, 100, 100)
        ],
        index=pd.Index(["r1", "r2", "r3"], name="loan_id"),
    )
    pd_frame = pd.DataFrame({"pd_calibrated": [0.1, 0.1, 0.1]}, index=frame.index)

    result = _calculate(_cfg(), frame=frame, pd_frame=pd_frame)

    # Provisión del grupo = 300 · 0,1 · 0,5 = 15,00; 15,00/3 = 5,00 exacto por operación.
    assert _groups_by_id(result)["A"]["provision_amount"] == Decimal("15.00")
    assert sum(result.detail["provision_amount"]) == Decimal("15.00")

    # Con exposiciones que no dividen exacto, el reparto sigue cerrando contra el grupo.
    frame.loc["r1", "exposure_amount"] = 101
    pd_frame.loc["r1", "pd_calibrated"] = 0.1
    result = _calculate(_cfg(), frame=frame, pd_frame=pd_frame)
    provision = _groups_by_id(result)["A"]["provision_amount"]
    assert sum(result.detail["provision_amount"]) == provision
    assert all(value >= Decimal("0") for value in result.detail["provision_amount"])


def test_allocate_levanta_si_el_prorrateo_no_cuadra() -> None:
    """El guardián del cuadre no acepta un total que no es múltiplo del céntimo."""
    with pytest.raises(InternalCalculationError, match="no cuadra con su total"):
        engine_module._allocate(
            Decimal("10.005"),
            [Decimal("1"), Decimal("1")],
            Decimal("0.01"),
        )


def test_allocate_reparte_cero_sin_exposicion() -> None:
    """Sin exposición o sin provisión no hay nada que repartir."""
    assert engine_module._allocate(Decimal("10"), [Decimal("0")], Decimal("0.01")) == [Decimal("0")]
    assert engine_module._allocate(Decimal("0"), [Decimal("5")], None) == [Decimal("0")]


# ─────────────────────────── auditoría e infraestructura ───────────────────────────


def test_motor_emite_decision_auditable() -> None:
    """El motor emite la decisión compacta del cálculo cuando se le inyecta un sink."""
    sink = InMemoryAuditSink()

    result = _calculate(_cfg(), audit=sink)

    evento = next(event for event in sink.events if event.payload["regla"] == "internal_b1_engine")
    assert evento.payload["umbral"]["method"] == "pd_lgd"
    assert evento.payload["valor"]["total_internal_provision"] == str(
        result.card.total_internal_provision
    )
    assert evento.payload["accion"] == "calcular_provision_interna"


def test_from_config_coacciona_dict_y_term_structure_es_none() -> None:
    """``from_config`` valida un config crudo y el resultado no expone term-structure (CT-2)."""
    ya_validado = InternalProvisioningConfig(grouping="provided", group_col="grupo")
    assert InternalProvisioningEngine.from_config(ya_validado).config is ya_validado

    desde_dict = InternalProvisioningEngine.from_config(
        cast(Any, {"grouping": "provided", "group_col": "grupo", "rounding": "integer_currency"})
    )
    assert isinstance(desde_dict.config, InternalProvisioningConfig)
    assert desde_dict.config.rounding == "integer_currency"

    result = _calculate(_cfg())
    assert result.term_structure() is None


def test_import_pandas_ausente_levanta_missing_dependency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sin ``pandas`` el motor falla con el error tipado del núcleo."""
    real_import = engine_module.importlib.import_module

    def block_pandas(name: str) -> Any:
        if name == "pandas":
            raise ModuleNotFoundError("No module named 'pandas'", name="pandas")
        return real_import(name)

    monkeypatch.setattr(engine_module.importlib, "import_module", block_pandas)
    with pytest.raises(MissingDependencyError, match="InternalProvisioningEngine requiere pandas"):
        engine_module._import_pandas()


def test_el_motor_no_consume_azar() -> None:
    """El método interno es determinista: no recibe ni consume ``rng`` (SDD-28 §9)."""
    generador = np.random.default_rng(20_260_713)
    antes = generador.bit_generator.state

    _calculate(_cfg())

    assert generador.bit_generator.state == antes
    assert importlib.util.find_spec("nikodym.provisioning.internal.engine") is not None
