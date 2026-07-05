"""Tests de ``MarkovStep``: CT-1, publicación, auditoría e import liviano."""

from __future__ import annotations

import subprocess
import sys
from datetime import UTC, datetime
from typing import Any

import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

import nikodym.core.study as study_module
import nikodym.markov as markov_pkg
import nikodym.markov.step as step_module
from nikodym.core.audit import AuditEvent, InMemoryAuditSink
from nikodym.core.config import NikodymConfig
from nikodym.core.exceptions import ArtifactNotFoundError, MissingDependencyError
from nikodym.core.registry import REGISTRY
from nikodym.core.study import Study
from nikodym.markov.config import (
    MarkovConfig,
    MarkovDynamicsConfig,
    MarkovEstimationConfig,
    MarkovInputConfig,
    MarkovStateConfig,
)
from nikodym.markov.exceptions import MarkovInputError, MarkovTransformError
from nikodym.markov.results import MarkovResult
from nikodym.markov.step import MARKOV_ARTIFACTS, MarkovStep

ROOT_SEED = 20_260_629
_TERM_COLUMNS = [
    "row_id",
    "segment",
    "partition",
    "period",
    "time_value",
    "hazard",
    "survival",
    "pd_marginal",
    "pd_cumulative",
    "method",
    "pd_source",
    "scenario",
    "warning_codes",
]


def _states(states: tuple[str, ...] = ("A", "B", "default")) -> MarkovStateConfig:
    """Estados Markov canónicos para fixtures de step."""
    return MarkovStateConfig(
        states=states,
        default_state="default",
        absorbing_states=("default",),
    )


def _cfg(
    *,
    method: str = "cohort",
    states: tuple[str, ...] = ("A", "B", "default"),
    dynamics: MarkovDynamicsConfig | None = None,
    input_cfg: MarkovInputConfig | None = None,
) -> MarkovConfig:
    """Config Markov estable para ejecutar el step sin depender de scorecard."""
    if input_cfg is None:
        input_cfg = MarkovInputConfig(
            id_col="id",
            time_col="time",
            state_col="state",
            partition_col=None,
            exposure_time_col="exposure" if method == "duration" else None,
        )
    return MarkovConfig(
        input=input_cfg,
        states=_states(states),
        estimation=MarkovEstimationConfig(method=method),  # type: ignore[arg-type]
        dynamics=dynamics
        or MarkovDynamicsConfig(horizon_periods=(1, 2), embedding_policy="diagnose"),
    )


def _cohort_frame() -> pd.DataFrame:
    """Panel cohort golden con tres estados y default absorbente."""
    return pd.DataFrame(
        {
            "id": [1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6],
            "time": [1, 2, 1, 2, 1, 2, 1, 2, 1, 2, 1, 2],
            "state": [
                "A",
                "A",
                "A",
                "A",
                "A",
                "B",
                "A",
                "default",
                "B",
                "B",
                "B",
                "default",
            ],
        },
        index=pd.Index([f"obs-{i:02d}" for i in range(12)], name="obs_id"),
    )


def _duration_frame() -> pd.DataFrame:
    """Panel duration con ``Q=[[-0.2,0.2],[0,0]]``."""
    return pd.DataFrame(
        {
            "id": [1, 1, 2, 2, 3, 3, 4, 4, 5, 5],
            "time": [0, 1, 0, 1, 0, 1, 0, 1, 0, 1],
            "state": ["A", "default", "A", "A", "A", "A", "A", "A", "A", "A"],
            "exposure": [1, 0, 1, 0, 1, 0, 1, 0, 1, 0],
        }
    )


def _aj_frame() -> pd.DataFrame:
    """Panel mínimo para ejercer la ruta Aalen-Johansen del step."""
    return pd.DataFrame(
        {
            "id": [1, 1, 2, 2, 3, 3],
            "time": [0, 1, 0, 1, 0, 1],
            "state": ["A", "default", "A", "A", "A", "default"],
            "event_time": [np.nan, 0.5, np.nan, np.nan, np.nan, 0.75],
        }
    )


def _study_with_frame(cfg: MarkovConfig, frame: pd.DataFrame) -> Study:
    """Construye un ``Study`` markov con ``data.frame`` ya publicado."""
    study = Study(NikodymConfig(markov=cfg))
    study.artifacts.set("data", "frame", frame)
    return study


def _run_direct(cfg: MarkovConfig, frame: pd.DataFrame) -> MarkovResult:
    """Ejecuta ``MarkovStep`` directamente y devuelve el resultado."""
    study = _study_with_frame(cfg, frame)
    return MarkovStep.from_config(cfg).execute(study, np.random.default_rng(ROOT_SEED))


def _probability(frame: pd.DataFrame, *, from_state: str, to_state: str) -> float:
    """Extrae una probabilidad de transición tidy única."""
    row = frame[(frame["from_state"] == from_state) & (frame["to_state"] == to_state)]
    assert len(row) == 1
    return float(row.iloc[0]["probability"])


def test_from_config_registro_reexport_contrato_orden_e_import_liviano() -> None:
    """``MarkovStep`` queda registrado sin cargar pandas/scipy al importar el paquete."""
    cfg = _cfg()
    step = MarkovStep.from_config(cfg)
    sink = InMemoryAuditSink()
    step._audit = sink

    assert REGISTRY.resolve("markov", "standard") is MarkovStep
    assert markov_pkg.__getattr__("MarkovStep") is MarkovStep
    assert step.config is cfg
    assert step.name == "markov"
    assert step.requires == (("data", "frame"),)
    assert step.provides == tuple(("markov", key) for key in MARKOV_ARTIFACTS)
    assert study_module._DEFAULT_DOMAIN_ORDER[:2] == ("data", "markov")

    step.emit(
        AuditEvent(
            kind="decision",
            step="markov",
            payload={"regla": "x"},
            ts=datetime.now(UTC),
        )
    )

    code = (
        "import nikodym.core, sys;"
        "assert 'nikodym.markov' not in sys.modules;"
        "import nikodym.markov;"
        "blocked=[m for m in ('pandas','scipy','numpy','nikodym.markov.transition') "
        "if m in sys.modules];"
        "assert not blocked, blocked;"
        "assert 'MarkovStep' in nikodym.markov.__all__"
    )
    subprocess.run([sys.executable, "-c", code], check=True)

    assert sink.events[-1].payload == {"regla": "x"}


def test_execute_cohort_publica_artifacts_ct2_auditoria_y_no_mutacion() -> None:
    """El flujo cohort default publica siete claves, invariantes lifetime PD y auditoría."""
    cfg = _cfg()
    frame = _cohort_frame()
    original = frame.copy(deep=True)
    study = _study_with_frame(cfg, frame)
    sink = InMemoryAuditSink()
    study.set_audit_sink(sink)

    assert study.run(steps=["markov"]) is study

    result = study.artifacts.get("markov", "result")
    term = study.artifacts.get("markov", "term_structure")
    transition = study.artifacts.get("markov", "transition_matrix")
    assert isinstance(result, MarkovResult)
    assert isinstance(term, pd.DataFrame)
    assert isinstance(transition, pd.DataFrame)
    assert study.artifacts.get("markov", "generator") is None
    assert study.artifacts.keys()[-7:] == [("markov", key) for key in MARKOV_ARTIFACTS]
    assert tuple(term.columns) == tuple(_TERM_COLUMNS)
    assert result.term_structure() is not None
    assert result.card.metric_sections["generator_summary"] == {
        "available": False,
        "n_rows": 0,
        "source": None,
    }

    assert _probability(transition, from_state="A", to_state="default") == pytest.approx(0.25)
    assert term.loc["state:A|1", "pd_cumulative"] == pytest.approx(0.25)
    assert term.loc["state:A|2", "pd_cumulative"] == pytest.approx(0.50)
    assert term.loc["state:A|2", "pd_marginal"] == pytest.approx(0.25)
    assert term.loc["state:B|2", "pd_cumulative"] == pytest.approx(0.75)
    _assert_term_structure_contract(term)
    assert_frame_equal(study.artifacts.get("data", "frame"), original)

    decision_rules = [event.payload["regla"] for event in sink.events if event.kind == "decision"]
    assert decision_rules == [
        "markov_method",
        "markov_states",
        "markov_input_quality",
        "markov_transition_counts",
        "markov_stochastic_validation",
        "markov_generator",
        "markov_embedding",
        "markov_term_structure",
    ]


def test_duration_publica_generador_y_evaluation_times() -> None:
    """La ruta duration proyecta con ``expm`` y publica el artefacto generator."""
    cfg = _cfg(
        method="duration",
        states=("A", "default"),
        dynamics=MarkovDynamicsConfig(
            horizon_periods=(1, 2),
            evaluation_times=(1.0, 2.0),
            embedding_policy="diagnose",
        ),
    )

    result = _run_direct(cfg, _duration_frame())

    assert result.generator_frame is not None
    assert result.generator_frame.loc[1, "intensity"] == pytest.approx(0.2)
    assert result.card.metric_sections["generator_summary"]["available"] is True
    assert result.term_structure().loc["state:A|1", "pd_cumulative"] == pytest.approx(
        0.1812692469,
        abs=1e-10,
    )


def _non_embeddable_panel() -> pd.DataFrame:
    """Panel cohort cuya matriz de transición no embebe (oscilación A<->B fuerte).

    Matriz resultante P (A,B,default):
        A -> [0.10, 0.85, 0.05]
        B -> [0.80, 0.05, 0.15]
    Requiere regularización de embedding y su generador regularizado cambia la PD a default frente
    al ``P^t`` crudo (en t=1: P^t A->default=0.05, expm(Q_reg)=0.09545...).
    """
    from_a = ["A"] * 2 + ["B"] * 17 + ["default"] * 1
    from_b = ["A"] * 16 + ["B"] * 1 + ["default"] * 3
    ids: list[int] = []
    times: list[int] = []
    states: list[str] = []
    entity = 0
    for origin, targets in (("A", from_a), ("B", from_b)):
        for target in targets:
            entity += 1
            ids += [entity, entity]
            times += [1, 2]
            states += [origin, target]
    return pd.DataFrame({"id": ids, "time": times, "state": states})


def test_embedding_regularize_usa_y_publica_el_generador_regularizado() -> None:
    """M2: con embedding_policy='regularize', la PD publicada y el generador reflejan la
    regularización de verdad (no un no-op con P^t crudo y generator=None).

    Antes del fix: la term-structure usaba P^t crudo, el artefacto generator salía None y
    embedding_adjusted=True mentía. Ahora la PD se proyecta desde expm(Q_reg·t) y el generador se
    publica con source='regularized_embedding'.
    """
    cfg = _cfg(
        states=("A", "B", "default"),
        dynamics=MarkovDynamicsConfig(
            horizon_periods=(1, 2, 3),
            embedding_policy="regularize",
        ),
    )
    cfg = cfg.model_copy(
        update={
            "validation": cfg.validation.model_copy(
                update={"stochastic_tol": 1e-8, "generator_tol": 1e-8}
            )
        }
    )

    result = _run_direct(cfg, _non_embeddable_panel())

    # 1. El generador regularizado se publica (antes: None) con la fuente correcta.
    assert result.generator_frame is not None
    assert set(result.generator_frame["source"].tolist()) == {"regularized_embedding"}
    assert result.card.metric_sections["generator_summary"]["source"] == ("regularized_embedding",)

    # 2. El flag ya no miente: la regularización ocurrió y ahora afecta las salidas.
    assert result.diagnostics.embedding_status == "regularized_principal_log"
    assert result.diagnostics.embedding_adjusted is True

    # 3. La PD publicada refleja el generador regularizado (expm(Q_reg·t)), no el P^t crudo (0.05).
    term = result.term_structure_frame
    assert term is not None
    pd_cum_t1 = float(term.loc["state:A|1", "pd_cumulative"])
    assert pd_cum_t1 == pytest.approx(0.0954545454, abs=1e-9)
    assert pd_cum_t1 != pytest.approx(0.05, abs=1e-3)
    # Curva lifetime monótona y coherente por período.
    a_curve = term.loc[term["row_id"] == "state:A", "pd_cumulative"].tolist()
    assert a_curve == sorted(a_curve)


def test_aalen_johansen_proyecta_event_times_con_estimator_base() -> None:
    """La ruta Aalen-Johansen usa la función libre y mantiene un estimador publicado."""
    cfg = _cfg(
        states=("A", "default"),
        input_cfg=MarkovInputConfig(
            id_col="id",
            time_col="time",
            state_col="state",
            partition_col=None,
            transition_time_col="event_time",
        ),
        dynamics=MarkovDynamicsConfig(
            projection_mode="aalen_johansen",
            horizon_periods=(1, 2),
            embedding_policy="diagnose",
        ),
    )

    result = _run_direct(cfg, _aj_frame())

    term = result.term_structure()
    assert term is not None
    assert term["time_value"].tolist() == [0.5, 0.75]
    assert term.loc["state:A|1", "pd_cumulative"] == pytest.approx(1 / 3)
    assert result.diagnostics.projection_mode == "aalen_johansen"
    assert result.estimator.transition_matrix_frame_ is not None


@pytest.mark.parametrize(
    ("method", "states", "frame_factory"),
    [
        ("cohort", ("A", "B", "default"), _cohort_frame),
        ("duration", ("A", "default"), _duration_frame),
    ],
)
def test_period_matrices_rechaza_cohort_y_duration_sin_mislabel(
    method: str,
    states: tuple[str, ...],
    frame_factory: Any,
) -> None:
    """``period_matrices`` no cae a homogéneo etiquetado como no homogéneo."""
    cfg = _cfg(
        method=method,
        states=states,
        dynamics=MarkovDynamicsConfig(
            projection_mode="period_matrices",
            horizon_periods=(1, 2),
            embedding_policy="diagnose",
        ),
    )

    with pytest.raises(MarkovTransformError, match=r"period_matrices.*no soportado"):
        _run_direct(cfg, frame_factory())


def test_ct1_falta_data_frame_y_tipo_invalido_fallan_con_error_propio() -> None:
    """CT-1 directo levanta ``ArtifactNotFoundError`` y el tipo incorrecto falla claro."""
    cfg = _cfg()
    step = MarkovStep.from_config(cfg)
    study = Study(NikodymConfig())

    with pytest.raises(ArtifactNotFoundError, match=r"\('data', 'frame'\)"):
        step.execute(study, np.random.default_rng(ROOT_SEED))

    study.artifacts.set("data", "frame", object())
    with pytest.raises(MarkovInputError, match=r"pandas\.DataFrame"):
        step.execute(study, np.random.default_rng(ROOT_SEED))


def test_transicion_desde_absorbente_levanta_markov_input_error() -> None:
    """Una transición default→vivo queda prohibida por contrato."""
    frame = pd.DataFrame(
        {"id": [1, 1], "time": [1, 2], "state": ["default", "A"]},
    )

    with pytest.raises(MarkovInputError, match="absorbente"):
        _run_direct(_cfg(), frame)


def test_config_dict_y_helpers_de_dependencias_faltantes(monkeypatch: pytest.MonkeyPatch) -> None:
    """El step coacciona config dict y traduce imports faltantes a ``MissingDependencyError``."""
    cfg = _cfg()
    study = _study_with_frame(cfg, _cohort_frame())
    study.config = study.config.model_copy(update={"markov": cfg.model_dump(mode="json")})
    result = MarkovStep.from_config(cfg).execute(study, np.random.default_rng(ROOT_SEED))
    assert result.diagnostics.method == "cohort"

    real_import = step_module.importlib.import_module

    def fake_import(name: str) -> Any:
        if name in {"pandas", "numpy", "scipy.linalg"}:
            raise ModuleNotFoundError(name)
        return real_import(name)

    monkeypatch.setattr(step_module.importlib, "import_module", fake_import)
    with pytest.raises(MissingDependencyError, match="pandas"):
        step_module._import_pandas()
    with pytest.raises(MissingDependencyError, match="numpy"):
        step_module._import_numpy()
    with pytest.raises(MissingDependencyError, match=r"scipy\.linalg"):
        step_module._import_expm()


def test_determinismo_resultado_identico() -> None:
    """Dos ejecuciones con mismo frame/config producen salidas idénticas."""
    cfg = _cfg()
    first = _run_direct(cfg, _cohort_frame())
    second = _run_direct(cfg, _cohort_frame())

    assert_frame_equal(first.transition_matrix_frame, second.transition_matrix_frame)
    assert_frame_equal(first.term_structure(), second.term_structure())
    assert first.diagnostics == second.diagnostics
    assert first.card == second.card


def _assert_term_structure_contract(term: pd.DataFrame) -> None:
    """Verifica el contrato económico compartido con ``survival``."""
    assert tuple(term.columns) == tuple(_TERM_COLUMNS)
    assert np.allclose(term["pd_cumulative"], 1.0 - term["survival"])
    for _, group in term.groupby("row_id", sort=False):
        assert group["pd_marginal"].sum() == pytest.approx(group["pd_cumulative"].iloc[-1])
