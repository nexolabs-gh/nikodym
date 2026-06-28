"""Config declarativo de la capa ``model`` (SDD-08 §5).

:class:`ModelConfig` es la sección ``model`` de
:class:`~nikodym.core.config.NikodymConfig`: ajuste logístico PD sobre variables WoE ya
seleccionadas. Toda clase hereda de :class:`~nikodym.core.config.NikodymBaseConfig`
(``extra='forbid'`` y ``frozen=True``); cada campo declara ``title``/``description`` y metadatos
``ui_*`` para que la UI (SDD-23) sea un editor del mismo config. La sección es computacional, por
lo que entra al ``config_hash`` global cuando está activa.

**Experimental (SemVer 0.x).**
"""

from __future__ import annotations

from typing import Any, Literal, Self

from pydantic import Field, model_validator

from nikodym.core.config import NikodymBaseConfig
from nikodym.core.exceptions import ConfigError

ModelEngine = Literal["logit", "glm_binomial"]
ModelOptimizer = Literal["newton", "bfgs", "lbfgs"]
StepwiseDirection = Literal["none", "forward", "backward", "bidirectional"]
StepwiseCriterion = Literal["wald_pvalue", "lr_test", "both"]
ModelPolicyAction = Literal["exclude", "flag", "fail"]

__all__ = [
    "IvContributionConfig",
    "ModelConfig",
    "ModelEngine",
    "ModelOptimizer",
    "ModelPolicyAction",
    "SignPolicyConfig",
    "StepwiseConfig",
    "StepwiseCriterion",
    "StepwiseDirection",
]


class StepwiseConfig(NikodymBaseConfig):
    """Configuración del stepwise estadístico dentro del modelo logístico PD."""

    enabled: bool = Field(
        default=True,
        title="Activar stepwise",
        description="Activa la selección iterativa dentro del ajuste logístico.",
        json_schema_extra={"ui_widget": "checkbox", "ui_group": "Stepwise", "ui_order": 1},
    )
    direction: StepwiseDirection = Field(
        default="bidirectional",
        title="Dirección del stepwise",
        description=(
            "'none' desactiva el stepwise y usa todos los candidatos salvo exclusiones, signos e "
            "IV-contribution."
        ),
        json_schema_extra={"ui_widget": "selectbox", "ui_group": "Stepwise", "ui_order": 2},
    )
    criterion: StepwiseCriterion = Field(
        default="wald_pvalue",
        title="Criterio estadístico",
        description="Contraste usado para entrada/salida de variables durante el stepwise.",
        json_schema_extra={"ui_widget": "selectbox", "ui_group": "Stepwise", "ui_order": 3},
    )
    entry_p_value: float = Field(
        default=0.05,
        ge=0.0,
        le=1.0,
        title="p-value máximo de entrada",
        description="Umbral máximo para que una variable candidata entre al modelo.",
        json_schema_extra={"ui_widget": "number_input", "ui_group": "Stepwise", "ui_order": 4},
    )
    exit_p_value: float = Field(
        default=0.05,
        ge=0.0,
        le=1.0,
        title="p-value máximo para permanecer",
        description="Umbral máximo aceptado para conservar una variable dentro del modelo.",
        json_schema_extra={"ui_widget": "number_input", "ui_group": "Stepwise", "ui_order": 5},
    )
    max_iter: int = Field(
        default=100,
        ge=1,
        title="Máximo de iteraciones stepwise",
        description=(
            "Límite de rondas del algoritmo stepwise; no controla las iteraciones del ajuste "
            "statsmodels, que viven en ModelConfig.fit_maxiter."
        ),
        json_schema_extra={"ui_widget": "number_input", "ui_group": "Stepwise", "ui_order": 6},
    )
    min_features: int = Field(
        default=1,
        ge=1,
        title="Mínimo de variables finales",
        description="Cantidad mínima de variables WoE finales requeridas para aceptar el modelo.",
        json_schema_extra={"ui_widget": "number_input", "ui_group": "Stepwise", "ui_order": 7},
    )

    @model_validator(mode="before")
    @classmethod
    def _normaliza_direction_none(cls, data: Any) -> Any:
        """Trata ``direction='none'`` como alias explícito de ``enabled=False``."""
        if isinstance(data, cls):
            return data
        if isinstance(data, dict) and data.get("direction") == "none":
            normalizado = dict(data)
            normalizado["enabled"] = False
            return normalizado
        return data


class SignPolicyConfig(NikodymBaseConfig):
    """Política de validación del signo esperado de coeficientes WoE."""

    expected_beta_sign: Literal["negative"] = Field(
        default="negative",
        title="Signo esperado de beta para WoE",
        description="Con WoE=ln(%Goods/%Bads), el beta esperado para riesgo es negativo.",
        json_schema_extra={"ui_widget": "selectbox", "ui_group": "Signos beta", "ui_order": 1},
    )
    action: ModelPolicyAction = Field(
        default="exclude",
        title="Acción ante signo invertido",
        description="Acción cuando una variable WoE queda con beta contrario al riesgo esperado.",
        json_schema_extra={"ui_widget": "selectbox", "ui_group": "Signos beta", "ui_order": 2},
    )
    fail_on_forced_inverted: bool = Field(
        default=True,
        title="Fallar si una variable forzada queda invertida",
        description="Impide que un override de negocio conserve una relación contraria al riesgo.",
        json_schema_extra={"ui_widget": "checkbox", "ui_group": "Signos beta", "ui_order": 3},
    )


class IvContributionConfig(NikodymBaseConfig):
    """Política de aporte máximo individual de IV en el modelo final."""

    threshold: float = Field(
        default=0.90,
        ge=0.0,
        le=1.0,
        title="Máximo aporte individual de IV",
        description="Contribución máxima permitida de una variable al IV total del modelo final.",
        json_schema_extra={
            "ui_widget": "number_input",
            "ui_group": "IV-contribution",
            "ui_order": 1,
        },
    )
    action: ModelPolicyAction = Field(
        default="exclude",
        title="Acción ante IV-contribution excesivo",
        description="Acción cuando una variable concentra más IV que el umbral configurado.",
        json_schema_extra={
            "ui_widget": "selectbox",
            "ui_group": "IV-contribution",
            "ui_order": 2,
        },
    )


class ModelConfig(NikodymBaseConfig):
    """Sección ``model`` de :class:`~nikodym.core.config.NikodymConfig` (SDD-08 §5)."""

    type: Literal["standard"] = Field(
        default="standard",
        title="Tipo de sección model",
        description="== @register('standard', domain='model') (D-MOD-6).",
        json_schema_extra={"ui_widget": "hidden", "ui_group": "General", "ui_order": 0},
    )
    engine: ModelEngine = Field(
        default="logit",
        title="Motor statsmodels",
        description="Logit por defecto; GLM Binomial queda reservado para pesos/familia GLM.",
        json_schema_extra={"ui_widget": "selectbox", "ui_group": "Ajuste", "ui_order": 1},
    )
    fit_intercept: bool = Field(
        default=True,
        title="Incluir intercepto",
        description="Incluye constante explícita para estimar la tasa base antes de scorecard.",
        json_schema_extra={"ui_widget": "checkbox", "ui_group": "Ajuste", "ui_order": 2},
    )
    optimizer: ModelOptimizer = Field(
        default="newton",
        title="Optimizador Logit",
        description="Método de optimización permitido para el fit de statsmodels Logit.",
        json_schema_extra={"ui_widget": "selectbox", "ui_group": "Ajuste", "ui_order": 3},
    )
    fit_maxiter: int = Field(
        default=100,
        ge=1,
        title="Iteraciones máximas del ajuste",
        description=(
            "Iteraciones máximas del ajuste statsmodels; override deliberado de Nikodym sobre el "
            "default maxiter=35 de statsmodels. No controla StepwiseConfig.max_iter."
        ),
        json_schema_extra={"ui_widget": "number_input", "ui_group": "Ajuste", "ui_order": 4},
    )
    tol: float = Field(
        default=1e-8,
        gt=0.0,
        title="Tolerancia de convergencia",
        description="Tolerancia numérica usada por el ajuste statsmodels cuando aplica.",
        json_schema_extra={"ui_widget": "number_input", "ui_group": "Ajuste", "ui_order": 5},
    )
    alpha: float = Field(
        default=0.05,
        gt=0.0,
        lt=1.0,
        title="Nivel alpha para intervalos",
        description="Nivel alpha usado para intervalos de confianza de coeficientes.",
        json_schema_extra={"ui_widget": "number_input", "ui_group": "Inferencia", "ui_order": 1},
    )

    stepwise: StepwiseConfig = Field(
        default_factory=StepwiseConfig,
        title="Stepwise",
        description="Parámetros de entrada/salida iterativa de variables dentro del modelo.",
        json_schema_extra={"ui_widget": "section", "ui_group": "Stepwise", "ui_order": 1},
    )
    sign_policy: SignPolicyConfig = Field(
        default_factory=SignPolicyConfig,
        title="Signos beta",
        description="Política ante coeficientes WoE con signo contrario al riesgo esperado.",
        json_schema_extra={"ui_widget": "section", "ui_group": "Signos beta", "ui_order": 1},
    )
    iv_contribution: IvContributionConfig = Field(
        default_factory=IvContributionConfig,
        title="IV-contribution",
        description="Política ante concentración excesiva de IV en una variable final.",
        json_schema_extra={"ui_widget": "section", "ui_group": "IV-contribution", "ui_order": 1},
    )

    force_include: tuple[str, ...] = Field(
        default_factory=tuple,
        title="Forzar inclusión",
        description="Variables que negocio exige conservar salvo fallo estadístico ruidoso.",
        json_schema_extra={"ui_widget": "multiselect", "ui_group": "Variables", "ui_order": 1},
    )
    force_exclude: tuple[str, ...] = Field(
        default_factory=tuple,
        title="Forzar exclusión",
        description="Variables que negocio exige descartar antes del ajuste del modelo.",
        json_schema_extra={"ui_widget": "multiselect", "ui_group": "Variables", "ui_order": 2},
    )
    fail_if_no_features: bool = Field(
        default=True,
        title="Fallar si no queda ninguna variable",
        description="Si True, una selección final vacía aborta en vez de aceptar solo intercepto.",
        json_schema_extra={"ui_widget": "checkbox", "ui_group": "Salida", "ui_order": 1},
    )

    @model_validator(mode="after")
    def _check_force_overrides_disjuntos(self) -> Self:
        """Valida que una variable no esté simultáneamente forzada a incluir y excluir."""
        conflicto = sorted(set(self.force_include) & set(self.force_exclude))
        if conflicto:
            raise ConfigError(
                "force_include y force_exclude no pueden compartir variables; "
                f"conflicto={conflicto}."
            )
        return self
