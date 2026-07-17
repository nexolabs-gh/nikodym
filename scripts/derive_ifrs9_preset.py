"""Deriva —y VERIFICA corriendo— la ECL IFRS 9 del preset ``f4-ifrs9-retail`` (SDD-16).

``nikodym.ui`` es *domain-agnostic* (SDD-23 §3.3): un test AST veta importar módulos de dominio
desde ``ui/``. Por eso el preset se sirve como **dict literal JSON-able**, no se construye con
``IfrsProvisioningConfig(...)`` dentro de ``ui/``. Este script vive **fuera** de ``ui/``, construye
las secciones ``survival`` (SDD-18) y ``provisioning_ifrs9`` (SDD-16) con los objetos Pydantic de
dominio, las vuelca con ``model_dump(mode="json", by_alias=True)`` y las imprime listas para pegar
en ``ui/presets.py``.

Y hace lo que ningún test de ``status == done`` hace: **corre la cadena entera y comprueba que el
número tiene sentido de NEGOCIO**. La cadena es la mínima que produce la ECL, y es **standalone
de verdad** (sin scorecard): ``data → survival → provisioning_ifrs9``. El survival ajusta con
``pd_source='none'`` sobre covariables PROPIAS del dataset (mora actual, utilización, DTI,
antigüedad) —el área IFRS 9 no depende del modelo de originación—; ``base_pd_source=
'term_structure'`` deriva la PD de la propia curva lifetime, ``pit_mode='ttc_only'`` evita pedir
``rho``/``Z`` y ``scenarios='single'`` evita pesos macro. El staging usa los backstops duros de
mora 30/90 días (presunciones IFRS 9).

**⚑ Checkpoint del número.** El ``assert`` de abajo es la guardia ejecutable: si la ECL/staging es
absurda (coverage ratio fuera de ~1-15 % de retail, todo en un solo stage, o la curva sin sentido),
FALLA en vez de dejar pasar un número bonito. IFRS 9 es EXPERIMENTAL (fuera de garantía SemVer 1.x).

Uso::

    uv run --no-sync python scripts/derive_ifrs9_preset.py
"""

from __future__ import annotations

import itertools
import pprint
import tempfile
from copy import deepcopy
from pathlib import Path

import nikodym
from nikodym.core.config import NikodymConfig
from nikodym.provisioning.ifrs9.config import (
    IfrsEadConfig,
    IfrsEclConfig,
    IfrsLgdConfig,
    IfrsPdConfig,
    IfrsProvisioningConfig,
    IfrsScenarioConfig,
    IfrsStagingConfig,
)
from nikodym.survival.config import (
    DiscreteHazardConfig,
    SurvivalConfig,
    SurvivalInputConfig,
    SurvivalTimeGridConfig,
)
from nikodym.ui import datasets
from nikodym.ui.presets import _STANDARD_CONFIG

DATASET_ID = "ifrs9_retail_latam"
HORIZON_YEARS = 5  # periodos ANUALES (== registro del dataset); grilla lifetime = 1..T años
_EXPECTED_F4_STAGES = (5_235, 477, 288)
_EXPECTED_F4_EAD = 114_325_315
_EXPECTED_F4_ECL = 3_423_116
_EXPECTED_F4_SURVIVAL = (6_000, 1_502)

# Secciones que la cadena standalone IFRS 9 NO necesita: TODO el pipeline scorecard
# (``binning``/``selection``/``model`` incluidos: con ``pd_source='none'`` survival ya no consume
# ``model.raw_pd_frame``) más calibración/performance/estabilidad/report. Se apagan para una
# corrida enfocada y robusta.
_DROP_SECTIONS = (
    "binning",
    "selection",
    "model",
    "scorecard",
    "calibration",
    "performance",
    "stability",
    "report",
)

# --- Sección survival (SDD-18): term-structure lifetime PD por discrete-time hazard. ---
# ``duration``/``event`` en años; ``pd_source='none'`` = standalone: el hazard se ajusta sobre
# covariables PROPIAS del dataset (mora actual, utilización de línea, DTI y antigüedad — numéricas
# y sin missing: supervivencia no imputa ni codifica categóricas), sin PD del scorecard.
# Horizonte fijo a T años (el dataset censura al horizonte ⇒ la grilla llega a T sin extrapolar).
_SURVIVAL_COVARIATES = (
    "days_past_due",
    "utilizacion_linea",
    "deuda_ingreso",
    "antiguedad_meses",
)
_SURVIVAL_SECTION = SurvivalConfig(
    method="discrete_hazard",
    input=SurvivalInputConfig(
        duration_col="duration",
        event_col="event",
        pd_source="none",
        covariate_cols=_SURVIVAL_COVARIATES,
    ),
    time_grid=SurvivalTimeGridConfig(time_unit="year", horizon_periods=HORIZON_YEARS),
    discrete_hazard=DiscreteHazardConfig(link="logit", pd_role="none", include_period_dummies=True),
    fail_on_falta_dato=True,
).model_dump(mode="json", by_alias=True)

# --- Sección provisioning_ifrs9 (SDD-16): staging + ECL de tres etapas. ---
# term-structure de survival; PD base derivada de la curva (no del scorecard); TTC (sin ajuste PIT);
# LGD/EAD provistas por la institución; staging por backstops duros de mora 30/90 días; un solo
# escenario. Descuento ``annual_eir_year_fraction`` con ``time_value`` en años (periodos anuales).
_IFRS9_SECTION = IfrsProvisioningConfig(
    as_of_date_col="as_of_date",
    portfolio_col="portfolio",
    pd=IfrsPdConfig(
        term_structure_source="survival",
        base_pd_source="term_structure",
        pit_mode="ttc_only",
        horizon_12m_periods=1,
    ),
    lgd=IfrsLgdConfig(method="provided", lgd_col="lgd"),
    ead=IfrsEadConfig(method="provided", ead_col="ead"),
    staging=IfrsStagingConfig(
        days_past_due_col="days_past_due",
        is_default_col="is_default",
        dpd_sicr_backstop=30,
        dpd_default_backstop=90,
    ),
    scenarios=IfrsScenarioConfig(source="single"),
    ecl=IfrsEclConfig(eir_col="eir", discount_convention="annual_eir_year_fraction"),
).model_dump(mode="json", by_alias=True)


def compose_config() -> dict:
    """Compone el config del preset F4 = F1 base (mínimo) + survival + provisioning_ifrs9."""
    cfg = deepcopy(_STANDARD_CONFIG)
    cfg["name"] = "preset-ifrs9-retail"
    for section in _DROP_SECTIONS:
        cfg[section] = None
    cfg["survival"] = deepcopy(_SURVIVAL_SECTION)
    cfg["provisioning_ifrs9"] = deepcopy(_IFRS9_SECTION)
    return cfg


def verify(cfg: dict) -> None:
    """Corre la cadena entera y comprueba que la ECL IFRS 9 tiene sentido de NEGOCIO."""
    NikodymConfig.model_validate(cfg)
    with tempfile.TemporaryDirectory() as tmp:
        source = datasets.materialize(DATASET_ID, workdir=Path(tmp))
        run_cfg = deepcopy(cfg)
        run_cfg["data"]["load"]["source"] = str(source)
        run_cfg["report"] = None  # ya está en None, defensivo (el reporte no es parte del gate)
        study = nikodym.run(NikodymConfig.model_validate(run_cfg))

    assert study.run_context.status == "done", f"la corrida falló: {study.run_context.status}"
    card = study.artifacts.get("provisioning_ifrs9", "card")
    summary = study.artifacts.get("provisioning_ifrs9", "summary")

    n1, n2, n3 = card.n_stage1, card.n_stage2, card.n_stage3
    total_ead = float(card.total_ead)
    total_ecl = float(card.total_ecl_reported)
    coverage = total_ecl / total_ead if total_ead else 0.0

    # ⚑ Guardias de negocio (solo se ven corriendo la cadena entera):
    assert n1 + n2 + n3 == card.n_rows, "los conteos por stage no cuadran con n_rows"
    assert n2 > 0 and n3 > 0, "el staging debe repartir en Stage 2 y 3 (no todo Stage 1)"
    assert n1 > n2 > n3, f"patrón de staging irreal: S1={n1} S2={n2} S3={n3} (se espera S1>S2>S3)"
    assert 0.01 <= coverage <= 0.15, (
        f"coverage ratio {coverage:.2%} fuera del rango creíble (1-15%)"
    )
    assert total_ecl > 0.0, "la ECL reportada total debe ser positiva"

    # Freeze IBK-01: cualquier deriva de las cifras insignia exige una decisión explícita.
    assert (n1, n2, n3) == _EXPECTED_F4_STAGES
    assert round(total_ead) == _EXPECTED_F4_EAD
    assert round(total_ecl) == _EXPECTED_F4_ECL
    assert f"{coverage:.2%}" == "2.99%"

    survival_card = study.artifacts.get("survival", "card")
    assert (survival_card.n_rows, survival_card.n_events) == _EXPECTED_F4_SURVIVAL
    assert survival_card.n_periods == HORIZON_YEARS

    # ⚑ Gate del fit standalone (P0 auditoría 2026-07-16): el hazard se ajusta sobre el libro
    # COMPLETO — la partición Dev/HO/OOT que el DataStep siempre produce no recorta la muestra
    # del fit (SDD-18; el informe declara n_rows como muestra de estimación y debe ser verdad).
    estimator = study.artifacts.get("survival", "estimator")
    n_fit, n_total = int(estimator.n_fit_rows_), int(estimator.n_rows_)
    assert n_fit == n_total, f"el fit del hazard usó {n_fit}/{n_total} filas (¿partición viva?)"

    # ⚑ Cobertura monótona por cartera: dentro de cada portfolio, la cobertura crece
    # estrictamente con el stage (S1 < S2 < S3 en las stages presentes) — la historia que el
    # informe cuenta al banco debe cumplirse en CADA cartera, no solo en el agregado.
    for portfolio, group in summary.groupby("portfolio"):
        by_stage = {int(row["stage"]): float(row["coverage_ratio"]) for _, row in group.iterrows()}
        coverages = [by_stage[stage] for stage in sorted(by_stage)]
        assert all(a < b for a, b in itertools.pairwise(coverages)), (
            f"cobertura no monótona en {portfolio}: {by_stage}"
        )

    print(f"[verify] status=done · n_rows={card.n_rows}")
    print(f"[verify] n_stage1={n1} n_stage2={n2} n_stage3={n3}")
    print(f"[verify] total_ead={total_ead:,.0f} · total_ecl_reported={total_ecl:,.0f}")
    print(f"[verify] coverage_ratio (ECL/EAD) = {coverage:.2%}")
    print("[verify] desglose por cartera x stage (n · EAD · ECL · coverage):")
    for _, row in summary.iterrows():
        cov = float(row["coverage_ratio"])
        print(
            f"           {row['portfolio']!s:<12} stage {int(row['stage'])} · "
            f"n={int(row['n_rows']):>4} · ead={float(row['total_ead']):>14,.0f} · "
            f"ecl={float(row['total_ecl_reported']):>12,.0f} · cov={cov:.2%}"
        )


def main() -> None:
    """Verifica el preset corriendo la cadena e imprime las secciones para pegar en presets.py."""
    verify(compose_config())
    print("\n# --- Pegar en ui/presets.py (derivado por scripts/derive_ifrs9_preset.py) ---")
    print("\n_IFRS9_SURVIVAL_SECTION = ", end="")
    pprint.pp(_SURVIVAL_SECTION, sort_dicts=False)
    print("\n_IFRS9_PROVISIONING_SECTION = ", end="")
    pprint.pp(_IFRS9_SECTION, sort_dicts=False)


if __name__ == "__main__":
    main()
