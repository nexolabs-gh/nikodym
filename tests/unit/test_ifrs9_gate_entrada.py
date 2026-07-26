"""Gate único de entrada del motor IFRS 9 (CRP-5).

El contrato de resolución de parámetros exige **dos** momentos de validación y sólo dos: lo
decidible sin mirar el dato, al validar el config; lo que depende del dato, en un gate único de
entrada al motor. **Nada a mitad del cálculo.**

Estos tests cubren los tres casos que la enmienda `_ENMIENDA-CRP-IFRS9.md` §2.4 midió en runtime y
que hoy incumplen esa regla de tres formas distintas:

1. **Se calcula mal en silencio** — falta ``recovery_cost`` en el enfoque *workout* y el motor asume
   cero, subestimando la LGD 20 pp sin emitir nada (§2.4-1).
2. **Un gatillo se apaga solo** — falta la columna ``is_default`` declarada y el gatillo Stage 3
   devuelve ``False`` para toda la cartera: una operación en incumplimiento genuino sale Stage 1
   (§2.4-2).
3. **Se valida tarde** — los pesos de escenario inválidos se rechazan recién en ``EclEngine``,
   cuando ya ponderaron la PD 12m y lifetime (§2.4-4).

El gate **conserva el tipo de excepción de su dominio**: lo que cambia es el momento, no el
contrato de errores. Por eso ``IfrsStagingError`` para columnas de staging, ``IfrsLgdError`` para
LGD e ``IfrsEclError`` para pesos, igual que hoy.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import pytest

import nikodym.provisioning.ifrs9.engine as engine_module
from nikodym.provisioning.ifrs9 import IfrsProvisioningEngine, LgdEngine
from nikodym.provisioning.ifrs9.config import (
    IfrsEadConfig,
    IfrsLgdConfig,
    IfrsPdConfig,
    IfrsProvisioningConfig,
    IfrsScenarioConfig,
    IfrsStagingConfig,
)
from nikodym.provisioning.ifrs9.exceptions import (
    IfrsEclError,
    IfrsLgdError,
    IfrsStagingError,
)
from nikodym.provisioning.ifrs9.results import IfrsProvisionResult


def _frame(**overrides: Any) -> pd.DataFrame:
    """Frame económico mínimo de ``op1``, alineado con el de ``test_ifrs9_engine``."""
    base: dict[str, Any] = {
        "portfolio": "retail",
        "ead": 1000.0,
        "lgd": 0.40,
        "recovery": 0.6,
        "eir": 0.10,
        "days_past_due": 0,
        "is_default": False,
    }
    base.update(overrides)
    index = base.pop("_index", pd.Index(["op1"], name="loan_id"))
    return pd.DataFrame([base], index=index)


def _ts(
    *,
    scenario: list[Any] | None = None,
    extra: dict[str, list[Any]] | None = None,
    pd_marginal: list[float] | None = None,
    periods: list[int] | None = None,
) -> pd.DataFrame:
    """Term-structure tidy con la invariante ``pd_cumulative = 1 - survival``."""
    marginal = pd_marginal if pd_marginal is not None else [0.10, 0.08]
    n = len(marginal)
    period = periods if periods is not None else list(range(1, n + 1))
    cumulative = np.cumsum(marginal).tolist()
    data: dict[str, list[Any]] = {
        "row_id": ["op1"] * n,
        "period": period,
        "time_value": [float(p) for p in period],
        "time_unit": ["year"] * n,
        "pd_marginal": marginal,
        "scenario": scenario if scenario is not None else [None] * n,
        "warning_codes": [()] * n,
        "survival": [1.0 - c for c in cumulative],
        "pd_cumulative": cumulative,
    }
    if extra:
        data.update(extra)
    return pd.DataFrame(data)


def _cfg(
    *,
    lgd: IfrsLgdConfig | None = None,
    staging: IfrsStagingConfig | None = None,
    scenarios: IfrsScenarioConfig | None = None,
    **pd_overrides: Any,
) -> IfrsProvisioningConfig:
    """Config base ejecutable: survival, ttc_only, escenario único, EAD provista."""
    pd_kwargs: dict[str, Any] = {
        "term_structure_source": "survival",
        "pit_mode": "ttc_only",
        "horizon_12m_periods": 1,
    }
    pd_kwargs.update(pd_overrides)
    return IfrsProvisioningConfig(
        row_id_col=None,
        portfolio_col="portfolio",
        pd=IfrsPdConfig(**pd_kwargs),
        lgd=lgd if lgd is not None else IfrsLgdConfig(method="provided"),
        ead=IfrsEadConfig(method="provided"),
        scenarios=scenarios if scenarios is not None else IfrsScenarioConfig(source="single"),
        staging=staging if staging is not None else IfrsStagingConfig(),
    )


def _run(cfg: IfrsProvisioningConfig, frame: pd.DataFrame, ts: pd.DataFrame) -> IfrsProvisionResult:
    """Ejecuta ``calculate`` con la fecha de cálculo canónica de los tests."""
    return IfrsProvisioningEngine.from_config(cfg).calculate(
        frame, term_structure=ts, as_of_date="2026-01-31"
    )


# ────────────────────── 1 · workout sin recovery_cost: el cero silencioso ──────────────────────


def _workout_frame(*, with_cost: bool) -> pd.DataFrame:
    """Frame del enfoque *workout* con EAD 100 y recuperación 50, con y sin coste.

    ``recovery_time_years=0`` neutraliza el descuento —``(1+r)**0 == 1``— para que el golden mida
    la aritmética del coste y nada más.
    """
    data: dict[str, Any] = {
        "ead": [100.0],
        "recovery": [50.0],
        "recovery_time_years": [0.0],
        "contractual_rate": [0.0],
    }
    if with_cost:
        data["recovery_cost"] = [20.0]
    return pd.DataFrame(data, index=pd.Index(["op1"], name="loan_id"))


def _workout_cfg() -> IfrsLgdConfig:
    """Config *workout* con descuento contractual, para no depender de la serie ``eir``."""
    return IfrsLgdConfig(method="workout", recovery_col="recovery", workout_discount="contractual")


def test_golden_workout_con_coste_de_recuperacion() -> None:
    """Golden de referencia: 1 - (50 - 20)/100 = 0.70. Ancla la cifra correcta."""
    out = LgdEngine.from_config(_workout_cfg()).estimate(_workout_frame(with_cost=True))

    np.testing.assert_allclose(out["lgd"].to_numpy(), [0.70], rtol=1e-12)


def test_workout_sin_coste_de_recuperacion_levanta_en_vez_de_asumir_cero() -> None:
    """Sin ``recovery_cost`` el motor asumía cero y devolvía 0.50: 20 pp menos, sin avisar.

    Es la asimetría más cara del censo: su insumo hermano ``recovery_time_years`` sí levanta
    ``IfrsLgdError``. Dos columnas del mismo enfoque, una dura y otra que se inventa el valor.
    """
    with pytest.raises(IfrsLgdError, match="recovery_cost"):
        LgdEngine.from_config(_workout_cfg()).estimate(_workout_frame(with_cost=False))


def test_workout_sin_coste_de_recuperacion_no_llega_a_calcular_en_el_motor() -> None:
    """El mismo caso por la ruta del motor completo: el gate lo corta antes de estimar nada."""
    cfg = _cfg(lgd=IfrsLgdConfig(method="workout", recovery_col="recovery"))
    frame = _frame(recovery=50.0, recovery_time_years=0.0, ead=100.0)

    with pytest.raises(IfrsLgdError, match="recovery_cost"):
        _run(cfg, frame, _ts())


# ─────────────── 2 · is_default declarado y ausente: el gatillo que se apaga ───────────────


def test_is_default_declarado_pero_ausente_levanta_en_el_gate() -> None:
    """Una operación en incumplimiento genuino salía **Stage 1** y con ``warnings`` vacío.

    ``is_default_col`` trae default ``"is_default"``, así que la columna está declarada aunque el
    usuario no la escriba. Que falte del frame es una **carencia del dato**, no un opt-out, y hoy
    ``staging.py`` colapsa los dos casos en la misma condición.
    """
    cfg = _cfg()
    frame = _frame(days_past_due=200)
    frame = frame.drop(columns=["is_default"])

    with pytest.raises(IfrsStagingError, match="is_default"):
        _run(cfg, frame, _ts())


def test_is_default_opt_out_explicito_sigue_corriendo() -> None:
    """La ruta de escape es declarar ``is_default_col=None``: ahí el usuario sí eligió apagarlo.

    Sin esta distinción el gate sería un muro: lo que se exige es que la elección sea del usuario,
    no del azar de qué columnas trajo el frame.
    """
    cfg = _cfg(staging=IfrsStagingConfig(is_default_col=None))
    frame = _frame().drop(columns=["is_default"])

    result = _run(cfg, frame, _ts())

    assert result.staging["stage"].tolist() == [1]


# ──────────────── 3 · pesos de escenario inválidos: el momento, no el veredicto ────────────────


def _forward_case() -> tuple[IfrsProvisioningConfig, pd.DataFrame, pd.DataFrame]:
    """Caso multiescenario ``source='forward'`` cuyos pesos suman 0.7, no 1."""
    cfg = _cfg(
        term_structure_source="forward",
        pit_mode="consume_pit",
        scenarios=IfrsScenarioConfig(source="forward"),
    )
    frame = _frame(ead=1000.0, lgd=1.0, eir=0.0)
    ts = _ts(
        pd_marginal=[0.05, 0.08],
        periods=[1, 1],
        scenario=["base", "adverso"],
        extra={"scenario_weight": [0.5, 0.2], "pd_basis": ["pit", "pit"]},
    )
    return cfg, frame, ts


def test_pesos_de_escenario_invalidos_no_alcanzan_a_ponderar_la_pd(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El veredicto ya era correcto; el momento no.

    Los pesos se rechazaban en ``EclEngine``, después de que ``_weighted_horizons`` los usara para
    ponderar la PD 12m y lifetime. El número malo ya había entrado al cálculo. Este test no mira el
    mensaje: instrumenta la ponderación y exige que **nunca se ejecute**.
    """
    llamadas: list[int] = []
    original = engine_module._weighted_horizons

    def _espia(*args: Any, **kwargs: Any) -> Any:
        llamadas.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(engine_module, "_weighted_horizons", _espia)
    cfg, frame, ts = _forward_case()

    with pytest.raises(IfrsEclError, match="sumar 1"):
        _run(cfg, frame, ts)

    assert llamadas == [], "los pesos inválidos alcanzaron a ponderar la PD antes de ser rechazados"
