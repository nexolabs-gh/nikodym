"""Config declarativo de la capa ``model`` (SDD-08 §5).

:class:`ModelConfig` es la sección ``model`` de
:class:`~nikodym.core.config.NikodymConfig`: ajuste logístico PD sobre variables WoE ya
seleccionadas. Toda clase hereda de :class:`~nikodym.core.config.NikodymBaseConfig`
(``extra='forbid'`` y ``frozen=True``); cada campo declara ``title``/``description`` y metadatos
``ui_*`` para que la UI (SDD-23) sea un editor del mismo config. La sección es computacional, por
lo que entra al ``config_hash`` global cuando está activa.

**Experimental (fuera de la garantía SemVer 1.x).**
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
        json_schema_extra={
            "ui_widget": "checkbox",
            "ui_group": "Stepwise",
            "ui_order": 1,
            "ui_help": (
                "Enciende o apaga la selección automática de variables paso a paso. "
                "Desactívalo si prefieres definir tú mismo qué variables entran, dejando solo "
                "los filtros de signo e IV-contribution."
            ),
        },
    )
    direction: StepwiseDirection = Field(
        default="bidirectional",
        title="Dirección del stepwise",
        description=(
            "'none' desactiva el stepwise y usa todos los candidatos salvo exclusiones, signos e "
            "IV-contribution."
        ),
        json_schema_extra={
            "ui_widget": "selectbox",
            "ui_group": "Stepwise",
            "ui_order": 2,
            "ui_help": (
                "Define si el stepwise solo agrega variables (forward), solo las retira "
                "(backward), hace ambas cosas (bidirectional) o no corre (none). "
                "'bidirectional' es lo habitual porque revisa entradas y salidas en cada "
                "iteración."
            ),
        },
    )
    criterion: StepwiseCriterion = Field(
        default="wald_pvalue",
        title="Criterio estadístico",
        description="Contraste usado para entrada/salida de variables durante el stepwise.",
        json_schema_extra={
            "ui_widget": "selectbox",
            "ui_group": "Stepwise",
            "ui_order": 3,
            "ui_help": (
                "Prueba estadística que decide si una variable entra o sale del modelo: "
                "p-value de Wald, test de razón de verosimilitud (LR), o ambos a la vez "
                "('both' es más exigente porque debe pasar los dos)."
            ),
        },
    )
    entry_p_value: float = Field(
        default=0.05,
        ge=0.0,
        le=1.0,
        title="p-value máximo de entrada",
        description="Umbral máximo para que una variable candidata entre al modelo.",
        json_schema_extra={
            "ui_widget": "number_input",
            "ui_group": "Stepwise",
            "ui_order": 4,
            "ui_help": (
                "Un candidato solo entra al modelo si su p-value es igual o menor a este "
                "umbral. Bajarlo (ej. 0.01) hace el modelo más selectivo y exige más "
                "significancia estadística para incorporar una variable."
            ),
        },
    )
    exit_p_value: float = Field(
        default=0.05,
        ge=0.0,
        le=1.0,
        title="p-value máximo para permanecer",
        description="Umbral máximo aceptado para conservar una variable dentro del modelo.",
        json_schema_extra={
            "ui_widget": "number_input",
            "ui_group": "Stepwise",
            "ui_order": 5,
            "ui_help": (
                "Umbral máximo de p-value para que una variable ya incluida se mantenga en el "
                "modelo; si su p-value sube por encima de este valor, el stepwise la retira en "
                "la siguiente iteración."
            ),
        },
    )
    max_iter: int = Field(
        default=100,
        ge=1,
        title="Máximo de iteraciones stepwise",
        description=(
            "Límite de rondas del algoritmo stepwise; no controla las iteraciones del ajuste "
            "statsmodels, que viven en ModelConfig.fit_maxiter."
        ),
        json_schema_extra={
            "ui_widget": "number_input",
            "ui_group": "Stepwise",
            "ui_order": 6,
            "ui_help": (
                "Límite de rondas que el algoritmo stepwise puede ejecutar antes de fallar. "
                "No confundir con las iteraciones internas del ajuste estadístico (campo "
                "'Iteraciones máximas del ajuste' en la sección Ajuste)."
            ),
        },
    )
    min_features: int = Field(
        default=1,
        ge=1,
        title="Mínimo de variables finales",
        description="Cantidad mínima de variables WoE finales requeridas para aceptar el modelo.",
        json_schema_extra={
            "ui_widget": "number_input",
            "ui_group": "Stepwise",
            "ui_order": 7,
            "ui_help": (
                "Número mínimo de variables WoE que debe conservar el modelo final; si el "
                "stepwise deja menos, el ajuste falla en vez de aceptar un modelo con muy "
                "pocas variables."
            ),
        },
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
        json_schema_extra={
            "ui_widget": "selectbox",
            "ui_group": "Signos beta",
            "ui_order": 1,
            "ui_help": (
                "Fijo en 'negativo': con WoE=ln(%Buenos/%Malos), una variable que realmente "
                "discrimina riesgo debe tener beta negativo. Es una constante informativa, no "
                "un valor a elegir."
            ),
        },
    )
    action: ModelPolicyAction = Field(
        default="exclude",
        title="Acción ante signo invertido",
        description="Acción cuando una variable WoE queda con beta contrario al riesgo esperado.",
        json_schema_extra={
            "ui_widget": "selectbox",
            "ui_group": "Signos beta",
            "ui_order": 2,
            "ui_help": (
                "Qué hacer cuando una variable WoE queda con signo contrario al esperado (beta "
                "positivo): 'exclude' la saca del modelo, 'flag' la deja pero la marca, 'fail' "
                "detiene el ajuste."
            ),
        },
    )
    fail_on_forced_inverted: bool = Field(
        default=True,
        title="Fallar si una variable forzada queda invertida",
        description="Impide que un override de negocio conserve una relación contraria al riesgo.",
        json_schema_extra={
            "ui_widget": "checkbox",
            "ui_group": "Signos beta",
            "ui_order": 3,
            "ui_help": (
                "Si una variable que forzaste a incluir (force_include) termina con signo "
                "invertido, este control decide si el ajuste debe fallar en vez de aceptarla "
                "igual. Protege contra relaciones económicamente absurdas impuestas por negocio."
            ),
        },
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
            "ui_help": (
                "Porcentaje máximo del IV total del modelo que puede aportar una sola "
                "variable. Si una variable concentra más poder predictivo que este umbral, el "
                "modelo queda excesivamente dependiente de un solo factor."
            ),
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
            "ui_help": (
                "Qué hacer cuando una variable supera el umbral de concentración de IV: "
                "'exclude' la saca del modelo, 'flag' la deja pero la marca, 'fail' detiene el "
                "ajuste."
            ),
        },
    )


class ModelConfig(NikodymBaseConfig):
    """Sección ``model`` de :class:`~nikodym.core.config.NikodymConfig` (SDD-08 §5)."""

    type: Literal["standard"] = Field(
        default="standard",
        title="Tipo de sección model",
        description="== @register('standard', domain='model') (D-MOD-6).",
        json_schema_extra={
            "ui_widget": "hidden",
            "ui_group": "General",
            "ui_order": 0,
            "ui_help": "Identificador interno del tipo de sección; no requiere edición.",
        },
    )
    engine: ModelEngine = Field(
        default="logit",
        title="Motor statsmodels",
        description="Logit por defecto; GLM Binomial queda reservado para pesos/familia GLM.",
        json_schema_extra={
            "ui_widget": "selectbox",
            "ui_group": "Ajuste",
            "ui_order": 1,
            "ui_help": (
                "Motor estadístico del ajuste: 'logit' es la regresión logística estándar "
                "(statsmodels Logit); 'glm_binomial' usa GLM con familia binomial y es necesario "
                "solo si vas a ponderar observaciones (sample_weight), algo que 'logit' no "
                "soporta."
            ),
        },
    )
    fit_intercept: bool = Field(
        default=True,
        title="Incluir intercepto",
        description="Incluye constante explícita para estimar la tasa base antes de scorecard.",
        json_schema_extra={
            "ui_widget": "checkbox",
            "ui_group": "Ajuste",
            "ui_order": 2,
            "ui_help": (
                "Incluye una constante (intercepto) en el modelo para capturar la tasa base de "
                "incumplimiento antes de aplicar el scorecard. Desactivarlo es inusual y obliga "
                "a que el modelo tenga al menos una variable WoE."
            ),
        },
    )
    optimizer: ModelOptimizer = Field(
        default="newton",
        title="Optimizador Logit",
        description="Método de optimización permitido para el fit de statsmodels Logit.",
        json_schema_extra={
            "ui_widget": "selectbox",
            "ui_group": "Ajuste",
            "ui_order": 3,
            "ui_help": (
                "Método numérico de optimización para el ajuste logístico (Newton-Raphson, "
                "BFGS o L-BFGS). Newton es el estándar; cámbialo solo si el ajuste no converge. "
                "No aplica cuando el motor es GLM Binomial, que siempre usa IRLS."
            ),
        },
    )
    fit_maxiter: int = Field(
        default=100,
        ge=1,
        title="Iteraciones máximas del ajuste",
        description=(
            "Iteraciones máximas del ajuste statsmodels; override deliberado de Nikodym sobre el "
            "default maxiter=35 de statsmodels. No controla StepwiseConfig.max_iter."
        ),
        json_schema_extra={
            "ui_widget": "number_input",
            "ui_group": "Ajuste",
            "ui_order": 4,
            "ui_help": (
                "Número máximo de iteraciones que puede dar el ajuste estadístico antes de "
                "declarar que no convergió. Subirlo puede ayudar en modelos con varias "
                "variables que convergen lento."
            ),
        },
    )
    tol: float = Field(
        default=1e-8,
        gt=0.0,
        title="Tolerancia de convergencia",
        description="Tolerancia numérica usada por el ajuste statsmodels cuando aplica.",
        json_schema_extra={
            "ui_widget": "number_input",
            "ui_group": "Ajuste",
            "ui_order": 5,
            "ui_help": (
                "Tolerancia numérica de convergencia del ajuste: el algoritmo se detiene "
                "cuando el cambio entre iteraciones cae por debajo de este valor. Rara vez "
                "hace falta tocarlo."
            ),
        },
    )
    alpha: float = Field(
        default=0.05,
        gt=0.0,
        lt=1.0,
        title="Nivel alpha para intervalos",
        description="Nivel alpha usado para intervalos de confianza de coeficientes.",
        json_schema_extra={
            "ui_widget": "number_input",
            "ui_group": "Inferencia",
            "ui_order": 1,
            "ui_help": (
                "Nivel de significancia para los intervalos de confianza de los coeficientes "
                "(ej. 0.05 = intervalos al 95%). No afecta el ajuste del modelo, solo el "
                "reporte de inferencia."
            ),
        },
    )

    stepwise: StepwiseConfig = Field(
        default_factory=StepwiseConfig,
        title="Stepwise",
        description="Parámetros de entrada/salida iterativa de variables dentro del modelo.",
        json_schema_extra={
            "ui_widget": "section",
            "ui_group": "Stepwise",
            "ui_order": 1,
            "ui_help": (
                "Agrupa los parámetros de la selección automática de variables por pasos: "
                "dirección, criterio estadístico y umbrales de entrada/salida."
            ),
        },
    )
    sign_policy: SignPolicyConfig = Field(
        default_factory=SignPolicyConfig,
        title="Signos beta",
        description="Política ante coeficientes WoE con signo contrario al riesgo esperado.",
        json_schema_extra={
            "ui_widget": "section",
            "ui_group": "Signos beta",
            "ui_order": 1,
            "ui_help": (
                "Agrupa la política que valida que cada variable WoE quede con el signo de "
                "riesgo esperado (beta negativo) y qué hacer cuando no lo cumple."
            ),
        },
    )
    iv_contribution: IvContributionConfig = Field(
        default_factory=IvContributionConfig,
        title="IV-contribution",
        description="Política ante concentración excesiva de IV en una variable final.",
        json_schema_extra={
            "ui_widget": "section",
            "ui_group": "IV-contribution",
            "ui_order": 1,
            "ui_help": (
                "Agrupa la política que evita que el modelo final dependa excesivamente de una "
                "sola variable, según su aporte al IV total."
            ),
        },
    )

    force_include: tuple[str, ...] = Field(
        default_factory=tuple,
        title="Forzar inclusión",
        description="Variables que negocio exige conservar salvo fallo estadístico ruidoso.",
        json_schema_extra={
            "ui_widget": "multiselect",
            "ui_group": "Variables",
            "ui_order": 1,
            "ui_help": (
                "Variables que negocio exige mantener en el modelo pase lo que pase el "
                "stepwise, salvo que fallen una validación estadística dura (p. ej. signo "
                "invertido con 'Fallar si una variable forzada queda invertida' activo)."
            ),
        },
    )
    force_exclude: tuple[str, ...] = Field(
        default_factory=tuple,
        title="Forzar exclusión",
        description="Variables que negocio exige descartar antes del ajuste del modelo.",
        json_schema_extra={
            "ui_widget": "multiselect",
            "ui_group": "Variables",
            "ui_order": 2,
            "ui_help": (
                "Variables que se descartan antes de correr el stepwise, aunque hayan pasado "
                "el binning/selección previos. Útil para vetar variables por criterio de "
                "negocio o regulatorio."
            ),
        },
    )
    fail_if_no_features: bool = Field(
        default=True,
        title="Fallar si no queda ninguna variable",
        description="Si True, una selección final vacía aborta en vez de aceptar solo intercepto.",
        json_schema_extra={
            "ui_widget": "checkbox",
            "ui_group": "Salida",
            "ui_order": 1,
            "ui_help": (
                "Si el stepwise y las políticas de signo/IV dejan el modelo sin ninguna "
                "variable, este control decide si el ajuste debe fallar (recomendado) en vez "
                "de aceptar un modelo que solo tiene el intercepto."
            ),
        },
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
