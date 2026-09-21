"""La hoja ``user_splits``/``user_splits_fixed`` de ``VariableBinningConfig`` (§8-9 (a)).

Es la única excepción al presupuesto cero de perillas de FLUJO-GUIADO-SCORECARD (D-FLU-12): una
decisión humana del flujo del banco —«junta estos dos tramos», «fija estos cortes»— no existía en
ninguna puerta porque ``binning.variable_overrides`` no llevaba cortes. La hoja se cablea a
``binning_fit_params[col]["user_splits"]``/``["user_splits_fixed"]`` de OptBinning; el motor sigue
decidiendo todo lo demás.
"""

from __future__ import annotations

import pytest

from nikodym.binning import transformer as transformer_module
from nikodym.binning.config import BinningConfig, VariableBinningConfig
from nikodym.binning.exceptions import BinningFitError
from nikodym.binning.transformer import WoEBinner
from nikodym.core.exceptions import ConfigError


def _binner(**kwargs: object) -> WoEBinner:
    params: dict[str, object] = {
        "solver": "mip",
        "max_n_prebins": 4,
        "max_n_bins": 4,
        "min_bin_size": 0.1,
        "time_limit": 5,
        "monotonic_trend": None,
        "keep_structural_columns": False,
    }
    params.update(kwargs)
    return WoEBinner(**params)  # type: ignore[arg-type]


def test_los_cortes_fijados_llegan_a_optbinning_por_variable() -> None:
    override = VariableBinningConfig(
        name="score", user_splits=(0.5, 2.5), user_splits_fixed=(True, False)
    )
    params = transformer_module._build_binning_fit_params(
        _binner(feature_columns=("score", "otra"), variable_overrides=(override,)),
        ["score", "otra"],
        [],
    )
    assert params["score"]["user_splits"] == [0.5, 2.5]
    assert params["score"]["user_splits_fixed"] == [True, False]
    # Sin la hoja, la variable no recibe la clave: OptBinning busca sus cortes como siempre.
    assert "user_splits" not in params["otra"] and "user_splits_fixed" not in params["otra"]


def test_sin_user_splits_fixed_todos_los_cortes_pueden_juntarse() -> None:
    override = VariableBinningConfig(name="score", user_splits=(1.5,))
    params = transformer_module._build_binning_fit_params(
        _binner(feature_columns=("score",), variable_overrides=(override,)), ["score"], []
    )
    assert params["score"]["user_splits"] == [1.5]
    assert "user_splits_fixed" not in params["score"]


def test_los_cortes_fijados_solo_aplican_a_variables_numericas() -> None:
    override = VariableBinningConfig(name="segment", user_splits=(0.5,))
    with pytest.raises(BinningFitError, match="sólo aplican a variables numéricas"):
        transformer_module._build_binning_fit_params(
            _binner(feature_columns=("segment",), variable_overrides=(override,)),
            ["segment"],
            ["segment"],
        )


@pytest.mark.parametrize(
    ("campos", "mensaje"),
    [
        ({"user_splits": (2.5, 0.5)}, "estrictamente crecientes"),
        ({"user_splits": (1.0, 1.0)}, "estrictamente crecientes"),
        ({"user_splits": ()}, "al menos un corte"),
        ({"user_splits": (0.5,), "user_splits_fixed": (True, True)}, "misma longitud"),
        ({"user_splits_fixed": (True,)}, "sin user_splits"),
        ({"user_splits": (0.5,), "dtype": "categorical"}, "sólo aplican a variables numéricas"),
    ],
)
def test_la_hoja_rechaza_cortes_mal_formados(campos: dict[str, object], mensaje: str) -> None:
    with pytest.raises(ConfigError, match=mensaje):
        VariableBinningConfig(name="score", **campos)  # type: ignore[arg-type]


def test_la_hoja_es_aditiva_y_no_mueve_el_hash_de_un_config_sin_cortes() -> None:
    from nikodym.core.config import NikodymConfig, config_hash

    sin = NikodymConfig(binning=BinningConfig(feature_columns=("score",)))
    con_defaults = NikodymConfig(
        binning=BinningConfig(
            feature_columns=("score",),
            variable_overrides=(VariableBinningConfig(name="score"),),
        )
    )
    volcado = con_defaults.binning.variable_overrides[0].model_dump()
    assert volcado["user_splits"] is None and volcado["user_splits_fixed"] is None
    assert config_hash(sin) != config_hash(
        NikodymConfig(
            binning=BinningConfig(
                feature_columns=("score",),
                variable_overrides=(VariableBinningConfig(name="score", user_splits=(1.5,)),),
            )
        )
    )
