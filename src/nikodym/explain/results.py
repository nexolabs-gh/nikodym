"""DTOs puros de resultados de la capa ``explain`` (SDD-14 §4/§6).

Este módulo publica los contenedores Pydantic *frozen* (``extra='forbid'``) que la explicabilidad
unificada expone a ``report``/``governance``/``validation``: la importancia global (media |SHAP| o
``|β·WoE|`` del scorecard), las explicaciones locales con sus reason codes, la comparativa de
drivers scorecard-vs-ML, la metadata del explainer, la tarjeta CT-2 y el resultado agregado. **No**
calcula
SHAP, **no** entrena y **no** reúsa los explainers (eso vive en ``explainers``/``engine``): recibe
contribuciones ya calculadas y las normaliza a un contrato inmutable.

**Núcleo liviano (SDD-14 §9).** ``import nikodym.explain.results`` **no** importa
``shap``/``matplotlib``/``sklearn``/``pandas``/``numpy``: ``pandas`` vive solo bajo
``TYPE_CHECKING`` y se importa de forma perezosa dentro de :meth:`ExplainResult.global_frame` y
:meth:`ExplainResult.reason_codes_frame`.

**Reason codes como vista de ``shap_local`` (nitpick A15(3)).** ``ExplainResult.reason_codes`` es la
**misma** ``tuple[LocalExplanationRecord, ...]`` que ``shap_local``, filtrada/ordenada a los top-N
drivers por observación: **no** es un DTO nuevo. Un ``model_validator`` verifica que sus ``row_key``
sean un subconjunto de los de ``shap_local`` (relación de vista, no de duplicación).

**Cumplimiento CT-2.** La puerta de extensión aditiva es ``ExplainCardSection.metric_sections``
(tidy, copiada a la lectura); :meth:`ExplainResult.term_structure` retorna **siempre** ``None``
(``explain`` no es multi-período, a diferencia de IFRS 9/forward).

**Orden estable y reproducibilidad (SDD-14 §6/§9).** ``shap_global`` desciende por
``mean_abs_contribution`` con desempate lexicográfico; ``reason_codes`` por ``rank``; ``shap_local``
preserva el orden del scope. Los floats normalizan ``-0.0`` como ``0.0`` y **jamás** publican
``NaN``/``inf`` (fallan explícito). Los DataFrames y estructuras mutables se copian defensivamente
al leerlos aunque el DTO sea *frozen*.

**Experimental (SemVer 0.x).**
"""

from __future__ import annotations

import copy
import math
from collections.abc import Mapping
from numbers import Real
from typing import TYPE_CHECKING, Any, ClassVar, Literal, Self, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

if TYPE_CHECKING:
    import pandas as pd

    DataFrameLike: TypeAlias = pd.DataFrame
else:
    DataFrameLike: TypeAlias = Any

# Modelo del que provienen las contribuciones (scorecard analítico o challenger ML, SDD-14 §4).
SourceModel: TypeAlias = Literal["scorecard", "ml"]
# Dirección del driver respecto de la PD (adversa sube, protectora baja, SDD-14 §3).
Direction: TypeAlias = Literal["increases_pd", "decreases_pd"]
# Unidad de contribución de la explicación (log-odds aditivo por default, SDD-14 §4, D-EXP-4).
ContributionSpace: TypeAlias = Literal["log_odds", "probability"]
# Solape de un driver entre scorecard y challenger en la comparativa (SDD-14 §4).
Agreement: TypeAlias = Literal["both", "scorecard_only", "ml_only"]

# Columnas canónicas del tidy global (SDD-14 §6, proyección de ``ShapGlobalRecord``).
_GLOBAL_COLUMNS: tuple[str, ...] = (
    "feature",
    "mean_abs_contribution",
    "mean_signed_contribution",
    "rank",
    "source_model",
)
# Columnas canónicas del tidy explotado de reason codes (SDD-14 §6).
_REASON_CODE_COLUMNS: tuple[str, ...] = (
    "row_key",
    "rank",
    "feature",
    "direction",
    "contribution",
    "bin_label",
)

__all__ = [
    "Agreement",
    "ContributionSpace",
    "Direction",
    "DriverComparisonRecord",
    "ExplainCardSection",
    "ExplainResult",
    "ExplainerMetadata",
    "LocalExplanationRecord",
    "ReasonCode",
    "ShapGlobalRecord",
    "SourceModel",
]


class ShapGlobalRecord(BaseModel):
    """Importancia global de una feature: media |contribución| con dirección (SDD-14 §4/§6)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    feature: str
    mean_abs_contribution: float = Field(ge=0.0)
    mean_signed_contribution: float
    rank: int = Field(ge=1)
    source_model: SourceModel

    @field_validator("feature")
    @classmethod
    def _valida_feature(cls, value: str) -> str:
        """Valida que el nombre de la feature no esté vacío."""
        if not value.strip():
            raise ValueError("feature no puede estar vacío.")
        return value

    @field_validator("mean_abs_contribution", mode="before")
    @classmethod
    def _normaliza_abs(cls, value: Any) -> float:
        """Exige la importancia media |φ| finita y no negativa, con ``-0.0`` como ``0.0``."""
        return _normalize_non_negative_float(value)

    @field_validator("mean_signed_contribution", mode="before")
    @classmethod
    def _normaliza_signed(cls, value: Any) -> float:
        """Exige la dirección global finita y publica ``-0.0`` como ``0.0``."""
        return _normalize_required_float(value)


class ReasonCode(BaseModel):
    """Driver principal de la PD de una observación: dirección y magnitud (SDD-14 §3/§4)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    rank: int = Field(ge=1)
    feature: str
    direction: Direction
    contribution: float
    bin_label: str | None = None

    @field_validator("feature")
    @classmethod
    def _valida_feature(cls, value: str) -> str:
        """Valida que el nombre de la feature del reason code no esté vacío."""
        if not value.strip():
            raise ValueError("feature no puede estar vacío.")
        return value

    @field_validator("contribution", mode="before")
    @classmethod
    def _normaliza_contribution(cls, value: Any) -> float:
        """Exige la contribución φ finita y publica ``-0.0`` como ``0.0``."""
        return _normalize_required_float(value)

    @model_validator(mode="after")
    def _check_direccion(self) -> Self:
        """Valida la coherencia entre el signo de la contribución y la dirección declarada (§3)."""
        if self.contribution > 0.0 and self.direction != "increases_pd":
            raise ValueError("una contribución positiva empuja la PD hacia arriba (increases_pd).")
        if self.contribution < 0.0 and self.direction != "decreases_pd":
            raise ValueError("una contribución negativa baja la PD (decreases_pd).")
        return self


class LocalExplanationRecord(BaseModel):
    """Explicación local de una observación: base, predicción y reason codes (SDD-14 §4/§6)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    row_key: str
    partition: str
    base_value: float
    prediction: float
    pd_hat: float = Field(ge=0.0, le=1.0)
    reason_codes: tuple[ReasonCode, ...]

    @field_validator("row_key", "partition")
    @classmethod
    def _valida_texto(cls, value: str) -> str:
        """Valida que ``row_key`` y ``partition`` no estén vacíos."""
        if not value.strip():
            raise ValueError("row_key y partition no pueden estar vacíos.")
        return value

    @field_validator("base_value", "prediction", mode="before")
    @classmethod
    def _normaliza_escalares(cls, value: Any) -> float:
        """Exige base y predicción finitas y publica ``-0.0`` como ``0.0``."""
        return _normalize_required_float(value)

    @field_validator("pd_hat", mode="before")
    @classmethod
    def _normaliza_pd(cls, value: Any) -> float:
        """Exige ``pd_hat`` finita (el rango ``[0, 1]`` lo verifica la cota del campo)."""
        return _normalize_required_float(value)

    @model_validator(mode="after")
    def _check_ranks(self) -> Self:
        """Valida que los reason codes tengan rangos consecutivos desde ``1`` sin repetir (§6)."""
        ranks = [code.rank for code in self.reason_codes]
        if ranks and sorted(ranks) != list(range(1, len(ranks) + 1)):
            raise ValueError("los reason codes deben rankearse 1..N consecutivos y sin repetir.")
        return self


class DriverComparisonRecord(BaseModel):
    """Solape de un driver entre el campeón y el challenger (SDD-14 §4/§6)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    feature: str
    scorecard_rank: int | None = Field(default=None, ge=1)
    ml_rank: int | None = Field(default=None, ge=1)
    in_scorecard_topk: bool
    in_ml_topk: bool
    agreement: Agreement

    @field_validator("feature")
    @classmethod
    def _valida_feature(cls, value: str) -> str:
        """Valida que el nombre de la feature comparada no esté vacío."""
        if not value.strip():
            raise ValueError("feature no puede estar vacío.")
        return value

    @model_validator(mode="after")
    def _check_agreement(self) -> Self:
        """Valida que ``agreement`` sea coherente con la pertenencia a cada top-K (§6)."""
        esperado = {
            (True, True): "both",
            (True, False): "scorecard_only",
            (False, True): "ml_only",
        }.get((self.in_scorecard_topk, self.in_ml_topk))
        if esperado is None:
            raise ValueError("un driver comparado debe pertenecer al top-K de al menos un modelo.")
        if self.agreement != esperado:
            raise ValueError(
                f"agreement='{self.agreement}' no coincide con la pertenencia a los top-K "
                f"(esperado '{esperado}')."
            )
        return self


class ExplainerMetadata(BaseModel):
    """Metadata reproducible del explainer y del scope de la explicación (SDD-14 §4/§9)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    ml_explainer_kind: str | None
    scorecard_explained: bool
    shap_version: str | None
    contribution_space: ContributionSpace
    background_size: int | None = Field(default=None, ge=1)
    seed: int = Field(ge=0)
    deterministic: bool
    top_n_reason_codes: int = Field(ge=1)


class ExplainCardSection(BaseModel):
    """Tarjeta CT-2 de ``explain`` para model card, governance y report (SDD-14 §4/§9)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    _COPY_ON_ACCESS_FIELDS: ClassVar[frozenset[str]] = frozenset({"summary", "metric_sections"})

    summary: dict[str, str | int | float | bool]
    metric_sections: dict[str, Any] = Field(default_factory=dict)
    assumptions: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()

    @field_validator("summary", mode="before")
    @classmethod
    def _normaliza_summary(cls, value: Any) -> Any:
        """Normaliza los floats del resumen preservando el orden de inserción."""
        if not isinstance(value, Mapping):
            return value
        return {str(key): _normalize_scalar_value(item) for key, item in value.items()}

    @field_validator("metric_sections", mode="before")
    @classmethod
    def _copia_metric_sections(cls, value: Any) -> Any:
        """Copia profundamente la puerta CT-2 de métricas aditivas y normaliza sus floats."""
        if value is None:
            return {}
        if isinstance(value, Mapping):
            return _normalize_metric_payload(dict(value))
        return value

    def __getattribute__(self, name: str) -> Any:
        """Entrega copias profundas de las estructuras mutables aunque el DTO sea *frozen*."""
        value = super().__getattribute__(name)
        if name in super().__getattribute__("_COPY_ON_ACCESS_FIELDS"):
            return copy.deepcopy(value)
        return value


class ExplainResult(BaseModel):
    """Contenedor agregado de los artefactos publicados por ``explain`` (SDD-14 §4/§6)."""

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True, extra="forbid")

    _DATAFRAME_FIELDS: ClassVar[frozenset[str]] = frozenset({"scorecard_contributions"})

    shap_global: tuple[ShapGlobalRecord, ...]
    shap_local: tuple[LocalExplanationRecord, ...]
    reason_codes: tuple[LocalExplanationRecord, ...]
    scorecard_contributions: DataFrameLike | None
    comparison: tuple[DriverComparisonRecord, ...]
    explainer_metadata: ExplainerMetadata
    card: ExplainCardSection

    @field_validator("scorecard_contributions", mode="before")
    @classmethod
    def _copia_scorecard_contributions(cls, value: Any) -> Any:
        """Copia las contribuciones ``β·WoE`` o retorna ``None`` si no hay scorecard."""
        if value is None:
            return None
        if not _is_dataframe_like(value):
            raise ValueError("scorecard_contributions debe ser un pandas.DataFrame o None.")
        return _copy_dataframe(value)

    @model_validator(mode="after")
    def _check_reason_codes_view(self) -> Self:
        """Valida que ``reason_codes`` sea una vista top-N de ``shap_local`` (A15(3), §6)."""
        locales = {record.row_key for record in self.shap_local}
        externos = {record.row_key for record in self.reason_codes}
        if not externos <= locales:
            raise ValueError(
                "reason_codes es una vista top-N de shap_local: sus row_key deben estar en "
                "shap_local, no fabricar observaciones nuevas."
            )
        return self

    def __getattribute__(self, name: str) -> Any:
        """Entrega copias defensivas de los DataFrames al leerlos desde el resultado."""
        value = super().__getattribute__(name)
        if name in super().__getattribute__("_DATAFRAME_FIELDS") and _is_dataframe_like(value):
            return _copy_dataframe(value)
        return value

    def term_structure(self) -> pd.DataFrame | None:
        """Retorna ``None``: la explicación no publica estructura temporal (CT-2, SDD-14 §9).

        A diferencia de IFRS 9/forward, ``explain`` atribuye una predicción escalar por observación,
        no una curva multi-período; alimenta a ``report``/``governance`` por ``card`` +
        ``metric_sections``.
        """
        return None

    def global_frame(self) -> pd.DataFrame:
        """Materializa el tidy de :class:`ShapGlobalRecord` (SDD-14 §6).

        Preserva el orden de los registros (el step los produce descendente por
        ``mean_abs_contribution`` con desempate lexicográfico). Importa ``pandas`` de forma perezosa
        para no romper el import liviano de ``nikodym.explain``.
        """
        import pandas as pd

        records = self.shap_global
        return pd.DataFrame(
            {
                "feature": [record.feature for record in records],
                "mean_abs_contribution": [record.mean_abs_contribution for record in records],
                "mean_signed_contribution": [record.mean_signed_contribution for record in records],
                "rank": [record.rank for record in records],
                "source_model": [record.source_model for record in records],
            },
            columns=list(_GLOBAL_COLUMNS),
        )

    def reason_codes_frame(self) -> pd.DataFrame:
        """Explota los reason codes a un tidy ``(observación · factor)`` (SDD-14 §6).

        Recorre ``reason_codes`` (la vista top-N de ``shap_local``) preservando el orden de las
        observaciones y, dentro de cada una, el orden por ``rank``. Importa ``pandas`` de forma
        perezosa.
        """
        import pandas as pd

        filas: list[dict[str, Any]] = []
        for record in self.reason_codes:
            for code in record.reason_codes:
                filas.append(
                    {
                        "row_key": record.row_key,
                        "rank": code.rank,
                        "feature": code.feature,
                        "direction": code.direction,
                        "contribution": code.contribution,
                        "bin_label": code.bin_label,
                    }
                )
        return pd.DataFrame(filas, columns=list(_REASON_CODE_COLUMNS))


def _is_dataframe_like(value: object) -> bool:
    return all(hasattr(value, attribute) for attribute in ("columns", "copy", "select_dtypes"))


def _copy_dataframe(frame: Any) -> Any:
    copied = frame.copy(deep=True)
    for column in copied.columns:
        series = copied[column]
        if getattr(series.dtype, "kind", "") != "f":
            continue
        zero_mask = (series == 0.0).fillna(False)
        if bool(zero_mask.any()):
            copied[column] = series.mask(zero_mask, 0.0)
    return copied


def _normalize_scalar_value(value: Any) -> Any:
    if isinstance(value, bool) or not isinstance(value, float):
        return value
    if not math.isfinite(value):
        raise ValueError("los valores float de resumen deben ser finitos.")
    return _normalize_float(value)


def _normalize_required_float(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError("los escalares de explicación deben ser números reales.")
    candidate = float(value)
    if not math.isfinite(candidate):
        raise ValueError("los escalares de explicación deben ser finitos (ni NaN ni inf).")
    return _normalize_float(candidate)


def _normalize_non_negative_float(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError("la importancia media debe ser un número real.")
    candidate = float(value)
    if not math.isfinite(candidate):
        raise ValueError("la importancia media no puede ser NaN ni inf.")
    if candidate < 0.0:
        raise ValueError("la importancia media |φ| no puede ser negativa.")
    return _normalize_float(candidate)


def _normalize_metric_payload(value: Any) -> Any:
    if isinstance(value, float):
        if not math.isfinite(value):
            return None
        return _normalize_float(value)
    if isinstance(value, Mapping):
        return {str(key): _normalize_metric_payload(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalize_metric_payload(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_normalize_metric_payload(item) for item in value)
    return copy.deepcopy(value)


def _normalize_float(value: float) -> float:
    if value == 0.0:
        return 0.0
    return value
