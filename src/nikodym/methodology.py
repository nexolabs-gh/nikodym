"""Ficha metodológica derivada de config y cards de una corrida.

La transparencia metodológica es una proyección read-only: no calcula riesgo ni mantiene una
segunda copia de los parámetros. :func:`build_ifrs9_methodology_card` combina el config efectivo
con las cards que prueban qué dominios corrieron. UI e informe consumen el mismo DTO, de modo que
«configurado» nunca se confunde con «ejecutado» y ambos canales cuentan la misma historia.

**Experimental (fuera de la garantía SemVer 1.x).**
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from numbers import Integral, Real
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field

MethodologyStatus = Literal["active", "not_exercised"]

__all__ = [
    "MethodologyCard",
    "MethodologyFact",
    "MethodologyStatus",
    "build_ifrs9_methodology_card",
    "methodology_paragraphs",
]

_SURVIVAL_METHOD_LABELS: Final[dict[str, str]] = {
    "discrete_hazard": "Discrete-time hazard",
    "kaplan_meier": "Kaplan-Meier",
    "cox_ph": "Cox proportional hazards",
    "aft": "Accelerated failure time",
}
_PIT_MODE_LABELS: Final[dict[str, str]] = {
    "ttc_only": "TTC (through-the-cycle)",
    "consume_pit": "PIT (point-in-time)",
    "apply_vasicek": "PIT por ajuste de Vasicek",
}
_TIME_UNIT_LABELS: Final[dict[str, tuple[str, str]]] = {
    "year": ("año", "años"),
    "month": ("mes", "meses"),
    "quarter": ("trimestre", "trimestres"),
    "day": ("día", "días"),
}


class MethodologyFact(BaseModel):
    """Una afirmación trazable de la ficha, con estado y fuentes técnicas explícitas."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    status: MethodologyStatus
    label: str
    value: str
    detail: str
    sources: tuple[str, ...] = Field(min_length=1)


class MethodologyCard(BaseModel):
    """Ficha metodológica compartida por UI e informe."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    domain: Literal["provisioning_ifrs9"] = "provisioning_ifrs9"
    active: tuple[MethodologyFact, ...]
    not_exercised: tuple[MethodologyFact, ...]
    source_refs: tuple[str, ...] = Field(min_length=1)


def build_ifrs9_methodology_card(
    *,
    config: Any,
    survival_card: Any,
    ifrs9_card: Any,
) -> MethodologyCard | None:
    """Deriva la ficha IFRS 9 desde config efectivo y cards publicadas.

    La card IFRS 9 es la prueba mínima de ejecución. Una sección presente sólo en config no basta
    para rotularla como activa. Los números observados (filas, eventos, escenarios) salen de cards;
    los parámetros (horizonte, métodos, backstops y descuento), del config de la misma corrida.
    """
    root = _as_mapping(config)
    survival = _as_mapping(survival_card)
    ifrs9 = _as_mapping(ifrs9_card)
    survival_cfg = _as_mapping(root.get("survival"))
    ifrs9_cfg = _as_mapping(root.get("provisioning_ifrs9"))
    if not ifrs9 or not ifrs9_cfg:
        return None
    pd_cfg = _as_mapping(ifrs9_cfg.get("pd"))
    lgd_cfg = _as_mapping(ifrs9_cfg.get("lgd"))
    ead_cfg = _as_mapping(ifrs9_cfg.get("ead"))
    staging_cfg = _as_mapping(ifrs9_cfg.get("staging"))
    scenarios_cfg = _as_mapping(ifrs9_cfg.get("scenarios"))
    ecl_cfg = _as_mapping(ifrs9_cfg.get("ecl"))
    term_source = _text(ifrs9.get("term_structure_source")) or _text(
        pd_cfg.get("term_structure_source")
    )

    active: list[MethodologyFact] = []
    method = _text(survival.get("method")) or _text(survival_cfg.get("method"))
    if term_source == "survival" and survival and method is not None:
        rows = _integer(survival.get("n_rows"))
        events = _integer(survival.get("n_events"))
        time_grid = _as_mapping(survival_cfg.get("time_grid"))
        horizon = _integer(time_grid.get("horizon_periods")) or _integer(survival.get("n_periods"))
        time_unit = _text(time_grid.get("time_unit")) or _text(survival.get("time_unit"))
        detail_parts: list[str] = []
        if rows is not None:
            detail_parts.append(f"{_count(rows)} filas")
        if events is not None:
            detail_parts.append(f"{_count(events)} eventos")
        if horizon is not None:
            detail_parts.append(f"horizonte {_horizon(horizon, time_unit)}")
        active.append(
            MethodologyFact(
                id="lifetime_pd",
                status="active",
                label="Curva PD lifetime",
                value=_SURVIVAL_METHOD_LABELS.get(method, method),
                detail=" · ".join(detail_parts),
                sources=(
                    ("config.survival", "survival.card") if survival_cfg else ("survival.card",)
                ),
            )
        )

    pit_mode = _text(ifrs9.get("pit_mode")) or _text(pd_cfg.get("pit_mode"))
    if pit_mode is not None:
        detail = (
            f"La term-structure activa proviene de {term_source}."
            if term_source is not None
            else "La term-structure activa consta en la card IFRS 9."
        )
        active.append(
            MethodologyFact(
                id="pd_basis",
                status="active",
                label="Base de PD",
                value=_PIT_MODE_LABELS.get(pit_mode, pit_mode),
                detail=detail,
                sources=("config.provisioning_ifrs9.pd", "provisioning_ifrs9.card"),
            )
        )

    lgd_method = _text(lgd_cfg.get("method"))
    ead_method = _text(ead_cfg.get("method"))
    if lgd_method is not None or ead_method is not None:
        methods = []
        if lgd_method is not None:
            methods.append(f"LGD {lgd_method}")
        if ead_method is not None:
            methods.append(f"EAD {ead_method}")
        warnings = {str(code) for code in _sequence(ifrs9.get("falta_dato"))}
        ead_constant = (
            ead_method == "provided"
            and ead_cfg.get("exposure_profile_col") is None
            and "FALTA-DATO-IFRS-4" in warnings
        )
        detail = (
            "La EAD se mantiene constante por período (FALTA-DATO-IFRS-4)."
            if ead_constant
            else "Los métodos efectivos provienen del config de la corrida."
        )
        active.append(
            MethodologyFact(
                id="loss_inputs",
                status="active",
                label="LGD y EAD",
                value=" · ".join(methods),
                detail=detail,
                sources=(
                    "config.provisioning_ifrs9.lgd",
                    "config.provisioning_ifrs9.ead",
                    "provisioning_ifrs9.card",
                ),
            )
        )

    sicr = _integer(staging_cfg.get("dpd_sicr_backstop"))
    default = _integer(staging_cfg.get("dpd_default_backstop"))
    default_col = _text(staging_cfg.get("is_default_col"))
    if sicr is not None and default is not None:
        value = f"{sicr}/{default} días"
        if default_col is not None:
            value += f" + {default_col}"
        detail = f"Stage 2 desde {sicr} días; Stage 3 desde {default} días"
        detail += f" o {default_col}." if default_col is not None else "."
        active.append(
            MethodologyFact(
                id="staging",
                status="active",
                label="Staging",
                value=value,
                detail=detail,
                sources=("config.provisioning_ifrs9.staging",),
            )
        )

    scenario_names = tuple(str(name) for name in _sequence(ifrs9.get("scenarios")))
    scenario_weights = _as_mapping(ifrs9.get("scenario_weights"))
    scenario_source = _text(scenarios_cfg.get("source"))
    if scenario_names:
        rendered = tuple(
            _scenario_label(name, _real(scenario_weights.get(name))) for name in scenario_names
        )
        active.append(
            MethodologyFact(
                id="scenario",
                status="active",
                label="Escenario de cálculo",
                value=" · ".join(rendered),
                detail=(
                    "Escenario único; no hay ponderación macroeconómica múltiple."
                    if scenario_source == "single" or len(scenario_names) == 1
                    else "Ponderación de escenarios publicada por la card IFRS 9."
                ),
                sources=(
                    "config.provisioning_ifrs9.scenarios",
                    "provisioning_ifrs9.card",
                ),
            )
        )

    discount = _text(ecl_cfg.get("discount_convention"))
    eir_col = _text(ecl_cfg.get("eir_col"))
    if discount is not None:
        value = "EIR anual" if discount == "annual_eir_year_fraction" else discount
        detail = (
            f"Descuento período a período con la columna {eir_col}."
            if eir_col is not None
            else "Descuento período a período según el config efectivo."
        )
        active.append(
            MethodologyFact(
                id="discount",
                status="active",
                label="Descuento",
                value=value,
                detail=detail,
                sources=("config.provisioning_ifrs9.ecl",),
            )
        )

    not_exercised: list[MethodologyFact] = []
    if root.get("forward") is None and term_source != "forward":
        not_exercised.append(
            MethodologyFact(
                id="forward",
                status="not_exercised",
                label="Forward-looking",
                value="Capacidad no ejercida",
                detail="La sección forward está inactiva y no condiciona la PD de esta corrida.",
                sources=("config.forward", "provisioning_ifrs9.card"),
            )
        )
    if scenario_source == "single" or len(scenario_names) <= 1:
        not_exercised.append(
            MethodologyFact(
                id="macro_scenarios",
                status="not_exercised",
                label="Escenarios macroeconómicos múltiples",
                value="Capacidad no ejercida",
                detail="La corrida usa un único escenario base, sin ponderación macro múltiple.",
                sources=("config.provisioning_ifrs9.scenarios", "provisioning_ifrs9.card"),
            )
        )
    if root.get("markov") is None and term_source != "markov":
        not_exercised.append(
            MethodologyFact(
                id="markov",
                status="not_exercised",
                label="Matrices de transición Markov",
                value="Capacidad no ejercida",
                detail=(
                    f"La term-structure activa proviene de {term_source}, no de Markov."
                    if term_source is not None
                    else "Markov no proveyó la term-structure activa de esta corrida."
                ),
                sources=("config.markov", "provisioning_ifrs9.card"),
            )
        )

    source_refs: list[str] = []
    if term_source == "survival":
        if survival_cfg:
            source_refs.append("config.survival")
        if survival:
            source_refs.append("survival.card")
    elif term_source in {"forward", "markov"} and _as_mapping(root.get(term_source)):
        source_refs.append(f"config.{term_source}")
    source_refs.extend(("config.provisioning_ifrs9", "provisioning_ifrs9.card"))

    return MethodologyCard(
        active=tuple(active),
        not_exercised=tuple(not_exercised),
        source_refs=tuple(source_refs),
    )


def methodology_paragraphs(card: MethodologyCard) -> tuple[str, ...]:
    """Convierte la ficha compartida a prosa determinista para el informe."""
    paragraphs = [
        "Esta ficha metodológica se deriva del config efectivo y de las cards publicadas por la "
        "corrida; no replica parámetros ni supone que una capacidad configurada se ejecutó."
    ]
    if card.active:
        paragraphs.append("Activo en esta corrida:")
        paragraphs.extend(_fact_sentence(fact) for fact in card.active)
    if card.not_exercised:
        paragraphs.append("Capacidad no ejercida en esta corrida:")
        paragraphs.extend(_fact_sentence(fact) for fact in card.not_exercised)
    paragraphs.append("Fuentes técnicas: " + ", ".join(card.source_refs) + ".")
    return tuple(paragraphs)


def _fact_sentence(fact: MethodologyFact) -> str:
    detail = f" {fact.detail}" if fact.detail else ""
    return f"{fact.label}: {fact.value}.{detail}"


def _as_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json", by_alias=True)
    if isinstance(value, Mapping):
        return {str(key): item for key, item in value.items()}
    return {}


def _sequence(value: Any) -> tuple[Any, ...]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(value)
    return ()


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _integer(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, Integral):
        return None
    return int(value)


def _real(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, Real):
        return None
    return float(value)


def _count(value: int) -> str:
    return f"{value:,}".replace(",", ".")


def _horizon(periods: int, unit: str | None) -> str:
    singular, plural = _TIME_UNIT_LABELS.get(unit or "", ("período", "períodos"))
    return f"{periods} {singular if periods == 1 else plural}"


def _scenario_label(name: str, weight: float | None) -> str:
    label = name.capitalize()
    if weight is None:
        return label
    percentage = f"{weight * 100:.2f}".rstrip("0").rstrip(".")
    return f"{label} {percentage} %"
