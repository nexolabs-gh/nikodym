"""Config declarativo de la capa ``provisioning.ifrs9`` (SDD-16 §5).

:class:`IfrsProvisioningConfig` es la sección ``provisioning_ifrs9`` de
:class:`~nikodym.core.config.NikodymConfig`: cálculo de la pérdida crediticia esperada contable
**IFRS 9 (ECL)** de tres etapas (PD 12m/lifetime + PIT/TTC Vasicek, LGD, EAD/CCF, staging/SICR y
motor ECL con descuento a EIR y multiescenario). Toda clase hereda de
:class:`~nikodym.core.config.NikodymBaseConfig` (``extra='forbid'`` y ``frozen=True``); cada campo
declara ``title``/``description`` y metadatos ``ui_*`` para que la UI (SDD-23) sea un editor del
mismo config. La sección es computacional (no infraestructura): cambiar la fuente de term-structure,
``rho``, el enfoque LGD/EAD, los umbrales SICR, los pesos de escenario o la convención de descuento
**entra al ``config_hash`` global**.

Nomenclatura IFRS 9 (regla dura D-CONV-1): ``pd``/``lgd``/``ead``, nunca la nomenclatura CMF.

Frontera B16.1: aquí solo viven el schema y sus validaciones determinables sin datos. La *presencia*
de columnas de datos (p. ej. que exista una fuente CCF cuando ``ead.method='ccf'``) es un contrato
de runtime que valida el motor en bloques posteriores (§6/§8), de modo que el config por defecto
``IfrsProvisioningConfig()`` siga construyendo sin argumentos.

**Experimental (fuera de la garantía SemVer 1.x).**
"""

from __future__ import annotations

import math
from typing import Literal, Self

from pydantic import Field, model_validator

from nikodym.core.config import NikodymBaseConfig
from nikodym.provisioning.ifrs9.exceptions import IfrsConfigError

__all__ = [
    "IfrsEadConfig",
    "IfrsEclConfig",
    "IfrsLgdConfig",
    "IfrsPdConfig",
    "IfrsProvisioningConfig",
    "IfrsScenarioConfig",
    "IfrsStagingConfig",
]

# Tolerancia absoluta para exigir que los pesos de escenario sumen 1 (SDD-16 §5).
_WEIGHT_SUM_TOL: float = 1e-9


def _require_non_empty_strings(values: dict[str, str], *, context: str) -> None:
    """Valida que los nombres de columnas/campos declarativos no sean vacíos."""
    empty = [name for name, value in values.items() if not value.strip()]
    if empty:
        raise IfrsConfigError(f"Los campos de {context} no pueden estar vacíos: {empty}.")


def _require_non_empty_if_set(values: dict[str, str | None], *, context: str) -> None:
    """Valida que las columnas opcionales, si se informan, no queden en blanco."""
    empty = [name for name, value in values.items() if value is not None and not value.strip()]
    if empty:
        raise IfrsConfigError(
            f"Las columnas opcionales de {context} no pueden estar vacías: {empty}."
        )


class IfrsPdConfig(NikodymBaseConfig):
    """Configuración de la PD 12m/lifetime y su transformación PIT/TTC (Vasicek)."""

    term_structure_source: Literal["survival", "markov", "forward"] = Field(
        default="survival",
        title="Proveedor de term-structure lifetime",
        description=(
            "Módulo que publica la term-structure lifetime PD por el contrato tidy CT-2 "
            "(survival estándar IFRS 9; markov/forward opt-in)."
        ),
        json_schema_extra={"ui_widget": "selectbox", "ui_group": "PD", "ui_order": 1},
    )
    base_pd_source: Literal["calibration", "term_structure"] = Field(
        default="term_structure",
        title="Fuente de PD 12m base",
        description=(
            "term_structure deriva la PD 12m de la misma curva lifetime; calibration la ancla a "
            "la PD transversal de SDD-10."
        ),
        json_schema_extra={"ui_widget": "selectbox", "ui_group": "PD", "ui_order": 2},
    )
    pit_mode: Literal["consume_pit", "apply_vasicek", "ttc_only"] = Field(
        default="consume_pit",
        title="Cómo obtener la PD PIT",
        description=(
            "consume_pit usa curvas PIT de forward; apply_vasicek transforma TTC con rho y Z; "
            "ttc_only usa la TTC sin ajuste (solo diagnóstico)."
        ),
        json_schema_extra={"ui_widget": "selectbox", "ui_group": "PD", "ui_order": 3},
    )
    rho: float | None = Field(
        default=None,
        ge=0.0,
        lt=1.0,
        title="Correlación de activos monofactorial",
        description=(
            "Correlación de activos (asset correlation) Vasicek; sin default "
            "(parámetro por cartera)."
        ),
        json_schema_extra={"ui_widget": "number_input", "ui_group": "PD", "ui_order": 4},
    )
    rho_col: str | None = Field(
        default=None,
        title="Columna de rho por fila",
        description="Columna que sobrescribe rho por fila cuando la correlación es heterogénea.",
        json_schema_extra={"ui_widget": "text_input", "ui_group": "PD", "ui_order": 5},
    )
    systemic_factor_col: str | None = Field(
        default=None,
        title="Columna del factor sistémico Z",
        description=(
            "Columna con el factor sistémico Z por escenario/período (orientación Z>0 = expansión)."
        ),
        json_schema_extra={"ui_widget": "text_input", "ui_group": "PD", "ui_order": 6},
    )
    horizon_12m_periods: int = Field(
        default=12,
        ge=1,
        title="Períodos que cubren 12 meses",
        description=(
            "Períodos de la term-structure que cubren 12 meses (mensual=12, trimestral=4, anual=1)."
        ),
        json_schema_extra={"ui_widget": "number_input", "ui_group": "PD", "ui_order": 7},
    )
    max_lifetime_periods: int | None = Field(
        default=None,
        ge=1,
        title="Tope de horizonte lifetime",
        description=(
            "Tope opcional del horizonte lifetime; None usa todo el soporte de la term-structure."
        ),
        json_schema_extra={"ui_widget": "number_input", "ui_group": "PD", "ui_order": 8},
    )

    @model_validator(mode="after")
    def _check_pd(self) -> Self:
        """Valida que las columnas opcionales de PD, si se informan, no queden en blanco."""
        _require_non_empty_if_set(
            {"rho_col": self.rho_col, "systemic_factor_col": self.systemic_factor_col},
            context="pd",
        )
        return self


class IfrsLgdConfig(NikodymBaseConfig):
    """Configuración de la LGD por los enfoques provided/beta/fractional/workout."""

    method: Literal["provided", "beta_regression", "fractional_response", "workout"] = Field(
        default="provided",
        title="Enfoque LGD",
        description=(
            "provided consume la LGD de la institución; beta/fractional/workout la modelan "
            "(nunca OLS plano, por bimodalidad)."
        ),
        json_schema_extra={"ui_widget": "selectbox", "ui_group": "LGD", "ui_order": 1},
    )
    lgd_col: str = Field(
        default="lgd",
        title="Columna LGD (provided)",
        description="Columna con la LGD entregada por la institución cuando method='provided'.",
        json_schema_extra={"ui_widget": "text_input", "ui_group": "LGD", "ui_order": 2},
    )
    recovery_col: str | None = Field(
        default=None,
        title="Columna recovery",
        description=(
            "Columna de recuperación para la identidad LGD=1-recovery y el enfoque workout."
        ),
        json_schema_extra={"ui_widget": "text_input", "ui_group": "LGD", "ui_order": 3},
    )
    lgd_floor: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        title="Piso LGD",
        description="Piso al que se acota la LGD estimada, dentro de [0, 1].",
        json_schema_extra={"ui_widget": "number_input", "ui_group": "LGD", "ui_order": 4},
    )
    lgd_cap: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        title="Techo LGD",
        description="Techo al que se acota la LGD estimada, dentro de [0, 1].",
        json_schema_extra={"ui_widget": "number_input", "ui_group": "LGD", "ui_order": 5},
    )
    covariate_cols: tuple[str, ...] = Field(
        default=(),
        title="Covariables para beta/fractional",
        description="Covariables del modelo LGD beta_regression/fractional_response.",
        json_schema_extra={"ui_widget": "text_list", "ui_group": "LGD", "ui_order": 6},
    )
    workout_discount: Literal["eir", "contractual"] = Field(
        default="eir",
        title="Descuento de recuperos workout",
        description=(
            "Tasa para descontar los flujos de recupero del enfoque workout (EIR o contractual)."
        ),
        json_schema_extra={"ui_widget": "selectbox", "ui_group": "LGD", "ui_order": 7},
    )

    @model_validator(mode="after")
    def _check_lgd(self) -> Self:
        """Valida columnas, floor/cap y requisitos por enfoque LGD de SDD-16 §5."""
        _require_non_empty_strings({"lgd_col": self.lgd_col}, context="lgd")
        _require_non_empty_if_set({"recovery_col": self.recovery_col}, context="lgd")
        vacias = [idx for idx, col in enumerate(self.covariate_cols) if not col.strip()]
        if vacias:
            raise IfrsConfigError(f"lgd.covariate_cols no puede contener nombres vacíos: {vacias}.")
        if self.lgd_floor > self.lgd_cap:
            raise IfrsConfigError("lgd.lgd_floor no puede exceder lgd.lgd_cap.")
        if self.method in ("beta_regression", "fractional_response") and not self.covariate_cols:
            raise IfrsConfigError(
                "lgd.method beta_regression/fractional_response exige covariate_cols no vacías."
            )
        if self.method == "workout" and self.recovery_col is None:
            raise IfrsConfigError(
                "lgd.method='workout' exige recovery_col para la identidad LGD=1-recovery."
            )
        return self


class IfrsEadConfig(NikodymBaseConfig):
    """Configuración de la EAD/CCF y el perfil de exposición por período."""

    method: Literal["provided", "ccf"] = Field(
        default="ccf",
        title="Enfoque EAD",
        description="provided consume la EAD entregada; ccf calcula EAD=drawn+CCF·(límite-drawn).",
        json_schema_extra={"ui_widget": "selectbox", "ui_group": "EAD", "ui_order": 1},
    )
    ead_col: str = Field(
        default="ead",
        title="Columna EAD (provided)",
        description="Columna con la EAD entregada por la institución cuando method='provided'.",
        json_schema_extra={"ui_widget": "text_input", "ui_group": "EAD", "ui_order": 2},
    )
    drawn_col: str = Field(
        default="drawn",
        title="Saldo dispuesto",
        description="Columna con el saldo dispuesto (drawn) para el enfoque CCF.",
        json_schema_extra={"ui_widget": "text_input", "ui_group": "EAD", "ui_order": 3},
    )
    limit_col: str = Field(
        default="credit_limit",
        title="Límite de crédito",
        description="Columna con el límite de crédito para el enfoque CCF.",
        json_schema_extra={"ui_widget": "text_input", "ui_group": "EAD", "ui_order": 4},
    )
    ccf_col: str | None = Field(
        default=None,
        title="Columna CCF por fila",
        description="Columna con el factor de conversión (CCF) por fila; excluyente con ccf_value.",
        json_schema_extra={"ui_widget": "text_input", "ui_group": "EAD", "ui_order": 5},
    )
    ccf_value: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        title="CCF único de config",
        description="Factor de conversión (CCF) único de config en [0, 1]; excluyente con ccf_col.",
        json_schema_extra={"ui_widget": "number_input", "ui_group": "EAD", "ui_order": 6},
    )
    exposure_profile_col: str | None = Field(
        default=None,
        title="Perfil EAD(t) longitudinal (diferido a CT-3)",
        description=(
            "Reservado para el perfil de exposición EAD(t) por período (panel longitudinal). "
            "Diferido a CT-3: informarlo no se soporta en v1 y levanta IfrsConfigError, porque "
            "una columna escalar no representa EAD(t) por período."
        ),
        json_schema_extra={"ui_widget": "text_input", "ui_group": "EAD", "ui_order": 7},
    )

    @model_validator(mode="after")
    def _check_ead(self) -> Self:
        """Valida columnas, la exclusividad ccf_col/ccf_value y el guard EAD(t) de SDD-16 §5.

        La *presencia* de una fuente CCF cuando ``method='ccf'`` es un contrato de runtime (§6/§8);
        aquí solo se prohíbe informar **ambas** fuentes a la vez, para que el config por defecto
        siga construyendo sin argumentos.

        Guard CT-3 (fail-fast): informar ``exposure_profile_col`` levanta en construcción. El perfil
        EAD(t) longitudinal real (panel fila x período) está diferido a CT-3; una columna escalar no
        puede representarlo, y honrarla aplanándola a constante sin aviso sería una degradación
        silenciosa con etiqueta falsa. Se rechaza aquí, no se degrada en silencio.
        """
        _require_non_empty_strings(
            {"ead_col": self.ead_col, "drawn_col": self.drawn_col, "limit_col": self.limit_col},
            context="ead",
        )
        if self.exposure_profile_col is not None:
            raise IfrsConfigError(
                "exposure_profile_col (perfil EAD(t) longitudinal por período) está "
                "diferido a CT-3 y no se soporta en v1: una columna escalar no "
                "representa EAD(t) por período. Use method='provided'/'ccf' (EAD "
                "desplegada constante con aviso FALTA-DATO-IFRS-4) o espere CT-3."
            )
        _require_non_empty_if_set({"ccf_col": self.ccf_col}, context="ead")
        if self.method == "ccf" and self.ccf_col is not None and self.ccf_value is not None:
            raise IfrsConfigError("ead.method='ccf' admite ccf_col o ccf_value, no ambos a la vez.")
        return self


class IfrsStagingConfig(NikodymBaseConfig):
    """Configuración del staging IFRS 9 (SICR, backstops 30/90 dpd, exención de bajo riesgo)."""

    sicr_pd_ratio_threshold: float = Field(
        default=2.0,
        gt=1.0,
        title="Ratio PD lifetime actual/origen",
        description=(
            "Umbral del ratio PD lifetime actual/origen que dispara Stage 2 (ESPEC §5.5, >=2x)."
        ),
        json_schema_extra={"ui_widget": "number_input", "ui_group": "Staging", "ui_order": 1},
    )
    sicr_pd_pit_backstop_multiple: float = Field(
        default=3.0,
        gt=1.0,
        title="Backstop PIT",
        description="Múltiplo del backstop PIT que dispara Stage 2 (ESPEC §5.5, >=3x).",
        json_schema_extra={"ui_widget": "number_input", "ui_group": "Staging", "ui_order": 2},
    )
    dpd_sicr_backstop: int = Field(
        default=30,
        ge=0,
        title="Backstop dpd Stage 2",
        description=(
            "Días de mora que activan el backstop a Stage 2 (presunción rebatible IFRS 9 5.5.11)."
        ),
        json_schema_extra={"ui_widget": "number_input", "ui_group": "Staging", "ui_order": 3},
    )
    dpd_default_backstop: int = Field(
        default=90,
        ge=0,
        title="Backstop dpd Stage 3",
        description=("Días de mora que presumen default a Stage 3 (presunción IFRS 9 B5.5.37)."),
        json_schema_extra={"ui_widget": "number_input", "ui_group": "Staging", "ui_order": 4},
    )
    days_past_due_col: str = Field(
        default="days_past_due",
        title="Días de mora",
        description="Columna con los días de mora usados por los backstops 30/90 dpd.",
        json_schema_extra={"ui_widget": "text_input", "ui_group": "Staging", "ui_order": 5},
    )
    is_default_col: str | None = Field(
        default="is_default",
        title="Flag de default",
        description="Columna booleana de default que fuerza Stage 3 con independencia de la mora.",
        json_schema_extra={"ui_widget": "text_input", "ui_group": "Staging", "ui_order": 6},
    )
    origination_pd_life_col: str | None = Field(
        default=None,
        title="PD lifetime en origen",
        description="Columna con la PD lifetime en origen para el gatillo cuantitativo de SICR.",
        json_schema_extra={"ui_widget": "text_input", "ui_group": "Staging", "ui_order": 7},
    )
    rating_col: str | None = Field(
        default=None,
        title="Rating actual",
        description="Columna con el rating actual para el gatillo de downgrade por notches.",
        json_schema_extra={"ui_widget": "text_input", "ui_group": "Staging", "ui_order": 8},
    )
    origination_rating_col: str | None = Field(
        default=None,
        title="Rating en origen",
        description="Columna con el rating en origen para el gatillo de downgrade por notches.",
        json_schema_extra={"ui_widget": "text_input", "ui_group": "Staging", "ui_order": 9},
    )
    notch_downgrade_threshold: int | None = Field(
        default=None,
        ge=1,
        title="Downgrade por notches",
        description="Caída mínima de rating (en notches) respecto a origen que dispara Stage 2.",
        json_schema_extra={"ui_widget": "number_input", "ui_group": "Staging", "ui_order": 10},
    )
    stage_override_col: str | None = Field(
        default=None,
        title="Override cualitativo de stage",
        description=(
            "Columna con override cualitativo (watchlist, forbearance) que fuerza Stage 2/3."
        ),
        json_schema_extra={"ui_widget": "text_input", "ui_group": "Staging", "ui_order": 11},
    )
    low_credit_risk_exemption: bool = Field(
        default=False,
        title="Aplicar exención de bajo riesgo crediticio",
        description=(
            "Activa la exención IFRS 9 5.5.10 (opt-in; los backstops duros dpd siempre dominan)."
        ),
        json_schema_extra={"ui_widget": "checkbox", "ui_group": "Staging", "ui_order": 12},
    )
    low_credit_risk_col: str | None = Field(
        default=None,
        title="Flag de bajo riesgo crediticio",
        description="Columna con el flag de bajo riesgo crediticio para la exención de Stage 1.",
        json_schema_extra={"ui_widget": "text_input", "ui_group": "Staging", "ui_order": 13},
    )

    @model_validator(mode="after")
    def _check_staging(self) -> Self:
        """Valida backstops dpd y columnas de rating del gatillo de notches de SDD-16 §5."""
        _require_non_empty_strings({"days_past_due_col": self.days_past_due_col}, context="staging")
        _require_non_empty_if_set(
            {
                "is_default_col": self.is_default_col,
                "origination_pd_life_col": self.origination_pd_life_col,
                "rating_col": self.rating_col,
                "origination_rating_col": self.origination_rating_col,
                "stage_override_col": self.stage_override_col,
                "low_credit_risk_col": self.low_credit_risk_col,
            },
            context="staging",
        )
        if self.dpd_default_backstop < self.dpd_sicr_backstop:
            raise IfrsConfigError(
                "staging.dpd_default_backstop debe ser >= staging.dpd_sicr_backstop."
            )
        if self.notch_downgrade_threshold is not None and (
            self.rating_col is None or self.origination_rating_col is None
        ):
            raise IfrsConfigError(
                "staging.notch_downgrade_threshold exige rating_col y origination_rating_col."
            )
        return self


class IfrsScenarioConfig(NikodymBaseConfig):
    """Configuración de la fuente y los pesos de los escenarios macro."""

    source: Literal["forward", "config", "single"] = Field(
        default="forward",
        title="Fuente de escenarios/pesos",
        description=(
            "forward toma escenarios y pesos de SDD-20; config los fija aquí; single usa w=1."
        ),
        json_schema_extra={"ui_widget": "selectbox", "ui_group": "Escenarios", "ui_order": 1},
    )
    weights: dict[str, float] = Field(
        default_factory=dict,
        title="Pesos por escenario (source='config')",
        description=(
            "Pesos por escenario cuando source='config'; deben sumar 1 y ser todos positivos."
        ),
        json_schema_extra={"ui_widget": "kv_number", "ui_group": "Escenarios", "ui_order": 2},
    )
    forbid_mean_scenario: bool = Field(
        default=True,
        title="Prohibir promediar inputs macro",
        description=(
            "Guard anti escenario medio: se ponderan outputs por escenario, nunca inputs macro."
        ),
        json_schema_extra={"ui_widget": "checkbox", "ui_group": "Escenarios", "ui_order": 3},
    )

    @model_validator(mode="after")
    def _check_scenarios(self) -> Self:
        """Valida los pesos de escenario para ``source='config'`` de SDD-16 §5."""
        if self.source != "config":
            return self
        if not self.weights:
            raise IfrsConfigError("scenarios.source='config' exige weights no vacíos.")
        vacias = [name for name in self.weights if not name.strip()]
        if vacias:
            raise IfrsConfigError(
                f"scenarios.weights no puede tener nombres de escenario vacíos: {vacias}."
            )
        no_finitos = [name for name, value in self.weights.items() if not math.isfinite(value)]
        if no_finitos:
            raise IfrsConfigError(f"scenarios.weights debe contener pesos finitos: {no_finitos}.")
        no_positivos = [name for name, value in self.weights.items() if value <= 0.0]
        if no_positivos:
            raise IfrsConfigError(
                f"scenarios.weights exige pesos estrictamente positivos: {no_positivos}."
            )
        total = math.fsum(self.weights.values())
        if not math.isclose(total, 1.0, rel_tol=0.0, abs_tol=_WEIGHT_SUM_TOL):
            raise IfrsConfigError(f"scenarios.weights debe sumar 1; suma observada={total!r}.")
        return self


class IfrsEclConfig(NikodymBaseConfig):
    """Configuración del motor ECL marginal (descuento a EIR, redondeo)."""

    eir_col: str = Field(
        default="eir",
        title="Tasa efectiva por instrumento",
        description=(
            "Columna con la tasa efectiva (EIR) por instrumento para el descuento de la ECL."
        ),
        json_schema_extra={"ui_widget": "text_input", "ui_group": "ECL", "ui_order": 1},
    )
    discount_convention: Literal["annual_eir_year_fraction", "period_eir"] = Field(
        default="annual_eir_year_fraction",
        title="Convención de descuento",
        description=(
            "annual_eir_year_fraction descuenta EIR anual por fracción de año; period_eir usa EIR "
            "por período."
        ),
        json_schema_extra={"ui_widget": "selectbox", "ui_group": "ECL", "ui_order": 2},
    )
    stage3_direct: bool = Field(
        default=False,
        title="Stage 3 como EAD·LGD directo",
        description=(
            "Si es True, Stage 3 calcula EAD·LGD descontado directo en vez de la ECL lifetime."
        ),
        json_schema_extra={"ui_widget": "checkbox", "ui_group": "ECL", "ui_order": 3},
    )
    rounding: Literal["none", "currency_2dp", "integer_currency"] = Field(
        default="none",
        title="Redondeo de ECL",
        description=(
            "Política explícita de redondeo contable de la ECL; none publica el valor económico "
            "exacto."
        ),
        json_schema_extra={"ui_widget": "selectbox", "ui_group": "ECL", "ui_order": 4},
    )

    @model_validator(mode="after")
    def _check_ecl(self) -> Self:
        """Valida que la columna de EIR del motor ECL no esté vacía."""
        _require_non_empty_strings({"eir_col": self.eir_col}, context="ecl")
        return self


class IfrsProvisioningConfig(NikodymBaseConfig):
    """Sección ``provisioning_ifrs9`` de :class:`~nikodym.core.config.NikodymConfig`."""

    schema_version: str = Field(
        default="1.0.0",
        title="Versión del sub-schema provisioning_ifrs9",
        description="Versión local del schema de provisiones IFRS 9 para migraciones futuras.",
        json_schema_extra={"ui_widget": "hidden", "ui_group": "General", "ui_order": 0},
    )
    type: Literal["standard"] = Field(
        default="standard",
        title="Tipo de sección provisioning_ifrs9",
        description="== @register('standard', domain='provisioning_ifrs9') (SDD-16 §4).",
        json_schema_extra={"ui_widget": "hidden", "ui_group": "General", "ui_order": 1},
    )
    as_of_date_col: str = Field(
        default="as_of_date",
        title="Fecha de cálculo",
        description="Columna con la fecha de cálculo o cierre contable de la provisión.",
        json_schema_extra={"ui_widget": "text_input", "ui_group": "Columnas", "ui_order": 1},
    )
    row_id_col: str | None = Field(
        default=None,
        title="Identificador de operación",
        description="Columna con el identificador de operación para trazar staging/ECL por fila.",
        json_schema_extra={"ui_widget": "text_input", "ui_group": "Columnas", "ui_order": 2},
    )
    portfolio_col: str = Field(
        default="portfolio",
        title="Cartera",
        description="Columna con la cartera para agregar y parametrizar umbrales SICR por cartera.",
        json_schema_extra={"ui_widget": "text_input", "ui_group": "Columnas", "ui_order": 3},
    )
    pd: IfrsPdConfig = Field(
        default_factory=IfrsPdConfig,
        title="PD 12m/lifetime + PIT",
        description="Configuración de PD 12m/lifetime y transformación PIT/TTC Vasicek.",
        json_schema_extra={"ui_widget": "section", "ui_group": "PD", "ui_order": 1},
    )
    lgd: IfrsLgdConfig = Field(
        default_factory=IfrsLgdConfig,
        title="LGD",
        description="Configuración de la LGD por los enfoques provided/beta/fractional/workout.",
        json_schema_extra={"ui_widget": "section", "ui_group": "LGD", "ui_order": 1},
    )
    ead: IfrsEadConfig = Field(
        default_factory=IfrsEadConfig,
        title="EAD/CCF",
        description="Configuración de la EAD/CCF y el perfil de exposición por período.",
        json_schema_extra={"ui_widget": "section", "ui_group": "EAD", "ui_order": 1},
    )
    staging: IfrsStagingConfig = Field(
        default_factory=IfrsStagingConfig,
        title="Staging/SICR",
        description="Configuración del staging IFRS 9 (SICR, backstops, exención de bajo riesgo).",
        json_schema_extra={"ui_widget": "section", "ui_group": "Staging", "ui_order": 1},
    )
    scenarios: IfrsScenarioConfig = Field(
        default_factory=IfrsScenarioConfig,
        title="Escenarios",
        description="Configuración de la fuente y los pesos de los escenarios macro.",
        json_schema_extra={"ui_widget": "section", "ui_group": "Escenarios", "ui_order": 1},
    )
    ecl: IfrsEclConfig = Field(
        default_factory=IfrsEclConfig,
        title="Motor ECL",
        description="Configuración del motor ECL marginal (descuento a EIR, redondeo).",
        json_schema_extra={"ui_widget": "section", "ui_group": "ECL", "ui_order": 1},
    )
    fail_on_falta_dato: bool = Field(
        default=True,
        title="Fallar ante brechas críticas de dato",
        description=(
            "Si es True, una brecha crítica de dato (p. ej. Vasicek sin rho/Z) falla en vez de "
            "marcar FALTA-DATO."
        ),
        json_schema_extra={"ui_widget": "checkbox", "ui_group": "General", "ui_order": 2},
    )

    @model_validator(mode="after")
    def _check_ifrs_provisioning(self) -> Self:
        """Valida columnas raíz y la consistencia PIT (Vasicek ↔ rho/Z) de SDD-16 §5."""
        _require_non_empty_strings(
            {"as_of_date_col": self.as_of_date_col, "portfolio_col": self.portfolio_col},
            context="provisioning_ifrs9",
        )
        _require_non_empty_if_set({"row_id_col": self.row_id_col}, context="provisioning_ifrs9")
        if self.fail_on_falta_dato and self.pd.pit_mode == "apply_vasicek":
            if self.pd.rho is None and self.pd.rho_col is None:
                raise IfrsConfigError(
                    "pd.pit_mode='apply_vasicek' exige rho o rho_col para la transformación "
                    "Vasicek."
                )
            if self.pd.systemic_factor_col is None and self.scenarios.source != "forward":
                raise IfrsConfigError(
                    "pd.pit_mode='apply_vasicek' exige systemic_factor_col o "
                    "scenarios.source='forward' para el factor sistémico Z."
                )
        return self
