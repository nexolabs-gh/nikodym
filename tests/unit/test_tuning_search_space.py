"""Tests del espacio de búsqueda de ``tuning`` (SDD-13 §4/§5/§11): specs, defaults y traducción.

Golden values de ``default_search_space`` por backend, traducción de cada spec a la llamada
``trial.suggest_*`` (con un ``FakeTrial`` que no importa optuna), validaciones del espacio y guarda
de import liviano.
"""

import subprocess
import sys

import pytest
from pydantic import ValidationError

from nikodym.tuning.exceptions import TuningSearchSpaceError
from nikodym.tuning.search_space import (
    CategoricalSpec,
    FloatSpec,
    IntSpec,
    SearchSpaceConfig,
    default_search_space,
    suggest_params,
)

BACKENDS = ["svm", "random_forest", "xgboost", "lightgbm", "catboost"]
GBDT_BACKENDS = ["xgboost", "lightgbm", "catboost"]


class FakeTrial:
    """Trial falso que registra las llamadas ``suggest_*`` sin depender de Optuna (SDD-13 §11)."""

    def __init__(self) -> None:
        self.int_calls: list[tuple[str, int, int, int, bool]] = []
        self.float_calls: list[tuple[str, float, float, bool]] = []
        self.categorical_calls: list[tuple[str, tuple[object, ...]]] = []

    def suggest_int(
        self, name: str, low: int, high: int, *, step: int = 1, log: bool = False
    ) -> int:
        self.int_calls.append((name, low, high, step, log))
        return low

    def suggest_float(self, name: str, low: float, high: float, *, log: bool = False) -> float:
        self.float_calls.append((name, low, high, log))
        return low

    def suggest_categorical(self, name: str, choices: list[object]) -> object:
        self.categorical_calls.append((name, tuple(choices)))
        return choices[0]


# ─────────────────────────── traducción de specs (suggest_params) ───────────────────────────


def test_suggest_params_traduce_cada_tipo_de_spec() -> None:
    space = SearchSpaceConfig(
        params={
            "max_depth": IntSpec(low=2, high=8),
            "learning_rate": FloatSpec(low=0.01, high=0.3, log=True),
            "kernel": CategoricalSpec(choices=("rbf", "linear")),
        }
    )
    trial = FakeTrial()
    result = suggest_params(trial, space)

    # El dict resultante recoge lo que el trial devolvió (low / primera choice), en orden.
    assert result == {"max_depth": 2, "learning_rate": 0.01, "kernel": "rbf"}
    assert list(result) == ["max_depth", "learning_rate", "kernel"]
    assert trial.int_calls == [("max_depth", 2, 8, 1, False)]
    assert trial.float_calls == [("learning_rate", 0.01, 0.3, True)]
    assert trial.categorical_calls == [("kernel", ("rbf", "linear"))]


def test_suggest_params_pasa_step_del_intspec() -> None:
    space = SearchSpaceConfig(params={"n": IntSpec(low=100, high=1000, step=50)})
    trial = FakeTrial()
    suggest_params(trial, space)
    assert trial.int_calls == [("n", 100, 1000, 50, False)]


def test_suggest_params_espacio_vacio_no_llama_al_trial() -> None:
    trial = FakeTrial()
    assert suggest_params(trial, SearchSpaceConfig()) == {}
    assert trial.int_calls == []
    assert trial.float_calls == []
    assert trial.categorical_calls == []


def test_suggest_params_categorical_enteros() -> None:
    space = SearchSpaceConfig(params={"num_leaves": CategoricalSpec(choices=(15, 31, 63))})
    trial = FakeTrial()
    result = suggest_params(trial, space)
    assert result == {"num_leaves": 15}
    assert trial.categorical_calls == [("num_leaves", (15, 31, 63))]


# ─────────────────────────── specs válidas (ramas de retorno) ───────────────────────────


def test_specs_validas_se_construyen() -> None:
    assert IntSpec(low=1, high=10).step == 1
    assert IntSpec(low=1, high=10, log=True).log is True
    assert FloatSpec(low=0.1, high=1.0).log is False
    assert FloatSpec(low=1e-3, high=1.0, log=True).log is True
    assert CategoricalSpec(choices=(1, 2, 3)).choices == (1, 2, 3)
    assert CategoricalSpec(choices=("a", "b")).kind == "categorical"


def test_searchspace_discrimina_por_kind() -> None:
    space = SearchSpaceConfig(
        params={
            "a": {"kind": "int", "low": 1, "high": 5},
            "b": {"kind": "float", "low": 0.0, "high": 1.0},
            "c": {"kind": "categorical", "choices": ["x", "y"]},
        }
    )
    assert isinstance(space.params["a"], IntSpec)
    assert isinstance(space.params["b"], FloatSpec)
    assert isinstance(space.params["c"], CategoricalSpec)


# ─────────────────────────── specs inválidas (⇒ TuningSearchSpaceError) ───────────────────────────


def test_intspec_low_mayor_o_igual_que_high() -> None:
    with pytest.raises(TuningSearchSpaceError, match="low < high"):
        IntSpec(low=5, high=3)


def test_intspec_log_con_low_no_positivo() -> None:
    with pytest.raises(TuningSearchSpaceError, match="log=True exige low > 0"):
        IntSpec(low=-1, high=5, log=True)


def test_intspec_log_con_step_distinto_de_uno() -> None:
    with pytest.raises(TuningSearchSpaceError, match="step=1"):
        IntSpec(low=1, high=10, log=True, step=2)


def test_floatspec_low_igual_que_high() -> None:
    with pytest.raises(TuningSearchSpaceError, match="low < high"):
        FloatSpec(low=1.0, high=1.0)


def test_floatspec_log_con_low_no_positivo() -> None:
    with pytest.raises(TuningSearchSpaceError, match="log=True exige low > 0"):
        FloatSpec(low=0.0, high=1.0, log=True)


def test_categorical_vacio() -> None:
    with pytest.raises(TuningSearchSpaceError, match="no vacío"):
        CategoricalSpec(choices=())


def test_categorical_heterogeneo() -> None:
    with pytest.raises(TuningSearchSpaceError, match="homogéneo"):
        CategoricalSpec(choices=("a", 1))


def test_searchspace_propaga_error_de_spec_anidada() -> None:
    # Un error de spec dentro del dict propaga TuningSearchSpaceError sin envolverse.
    with pytest.raises(TuningSearchSpaceError, match="low < high"):
        SearchSpaceConfig(params={"a": {"kind": "int", "low": 9, "high": 2}})


def test_specs_frozen_y_extra_forbid() -> None:
    spec = IntSpec(low=1, high=5)
    with pytest.raises(ValidationError, match="frozen"):
        spec.low = 3  # type: ignore[misc]
    with pytest.raises(ValidationError):
        IntSpec(low=1, high=5, campo_ajeno=1)  # type: ignore[call-arg]


# ─────────────────────────── default_search_space por backend (golden) ───────────────────────────


@pytest.mark.parametrize("backend", BACKENDS)
def test_default_search_space_no_vacio_por_backend(backend: str) -> None:
    space = default_search_space(backend)  # type: ignore[arg-type]
    assert isinstance(space, SearchSpaceConfig)
    assert space.params


def test_default_search_space_svm_golden() -> None:
    space = default_search_space("svm")
    assert set(space.params) == {"C", "kernel", "gamma"}
    c = space.params["C"]
    assert isinstance(c, FloatSpec)
    assert c.log is True and (c.low, c.high) == (0.01, 100.0)
    kernel = space.params["kernel"]
    assert isinstance(kernel, CategoricalSpec)
    assert kernel.choices == ("rbf", "linear")


def test_default_search_space_xgboost_golden() -> None:
    space = default_search_space("xgboost")
    assert set(space.params) == {
        "max_depth",
        "learning_rate",
        "subsample",
        "colsample_bytree",
        "reg_lambda",
        "min_child_weight",
    }
    md = space.params["max_depth"]
    assert isinstance(md, IntSpec) and (md.low, md.high) == (2, 8) and md.log is False
    lr = space.params["learning_rate"]
    assert isinstance(lr, FloatSpec) and lr.log is True and (lr.low, lr.high) == (0.01, 0.3)


def test_default_search_space_random_forest_golden() -> None:
    space = default_search_space("random_forest")
    assert set(space.params) == {
        "n_estimators",
        "max_depth",
        "min_samples_leaf",
        "max_features",
    }
    # RF sí tunea n_estimators: no tiene early-stopping (a diferencia de los GBDT).
    assert isinstance(space.params["n_estimators"], IntSpec)
    assert isinstance(space.params["max_features"], CategoricalSpec)


def test_default_search_space_lightgbm_golden() -> None:
    space = default_search_space("lightgbm")
    assert set(space.params) == {
        "num_leaves",
        "learning_rate",
        "subsample",
        "colsample_bytree",
        "reg_lambda",
        "min_child_samples",
    }


def test_default_search_space_catboost_golden() -> None:
    space = default_search_space("catboost")
    assert set(space.params) == {"depth", "learning_rate", "l2_leaf_reg"}


@pytest.mark.parametrize("backend", GBDT_BACKENDS)
def test_default_space_gbdt_excluye_numero_de_arboles(backend: str) -> None:
    # Nitpick A14(3): redundante con early-stopping, se excluye del espacio por defecto.
    space = default_search_space(backend)  # type: ignore[arg-type]
    assert "n_estimators" not in space.params
    assert "iterations" not in space.params


def test_default_search_space_backend_desconocido() -> None:
    with pytest.raises(TuningSearchSpaceError, match="no hay espacio de búsqueda"):
        default_search_space("no_existe")  # type: ignore[arg-type]


def test_suggest_params_sobre_default_space_xgboost() -> None:
    space = default_search_space("xgboost")
    trial = FakeTrial()
    params = suggest_params(trial, space)
    assert set(params) == set(space.params)
    # max_depth es el único IntSpec; el resto son FloatSpec.
    assert [call[0] for call in trial.int_calls] == ["max_depth"]
    assert {call[0] for call in trial.float_calls} == {
        "learning_rate",
        "subsample",
        "colsample_bytree",
        "reg_lambda",
        "min_child_weight",
    }
    assert trial.categorical_calls == []


# ─────────────────────────── import liviano (núcleo) ───────────────────────────


def test_import_search_space_liviano_por_subprocess() -> None:
    code = (
        "import sys;"
        "import nikodym.tuning.search_space;"
        "import nikodym.tuning.exceptions;"
        "blocked=[m for m in "
        "('optuna','sklearn','pandas','numpy','xgboost','lightgbm','catboost','scipy') "
        "if m in sys.modules];"
        "assert not blocked, blocked"
    )
    subprocess.run([sys.executable, "-c", code], check=True)
