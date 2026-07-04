"""Tests de ``TuningConfig`` (SDD-13 §5) e integración con ``NikodymConfig``.

Cubre defaults golden, validaciones de determinismo/pruner, la resolución del espacio de búsqueda
contra el backend de ``ml`` (cross-check de claves y tipos), el movimiento aditivo del
``config_hash`` global, el round-trip YAML, la rama *blob* opaco del core y el import liviano con el
hook ``_TUNING_CONFIG_CLS`` poblado.
"""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
import sys
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

import nikodym.tuning as tuning_pkg  # importa la capa: puebla el hook
from nikodym.core.config import (
    INFRA_SECTIONS,
    NikodymConfig,
    config_hash,
)
from nikodym.core.config import schema as _schema_mod
from nikodym.ml.config import MLConfig
from nikodym.tuning import (
    TuningConfig,
    TuningObjectiveConfig,
    TuningSamplerConfig,
    TuningValidationConfig,
)
from nikodym.tuning.config import _kinds_admitidos
from nikodym.tuning.exceptions import TuningConfigError, TuningSearchSpaceError
from nikodym.tuning.search_space import (
    CategoricalSpec,
    FloatSpec,
    IntSpec,
    SearchSpaceConfig,
    default_search_space,
)

# Golden del config_hash por defecto tras añadir la sección computacional `tuning`.
GOLDEN_DEFAULT_CONFIG_HASH = "2dc342f1fd7be6d5ec32bca5a4c3cc4badf1da11f6876b280f7ca9662f857f3e"
# Golden anterior (antes de B13.2, con `ml` ya presente); el hash DEBE moverse.
GOLDEN_PREVIO_SIN_TUNING = "33e1dcce02a205cb2bc0fcfb1341c80b5251c5b2e6e478e4ecd392f67f0cf746"

BACKENDS = ["svm", "random_forest", "xgboost", "lightgbm", "catboost"]


@pytest.fixture(autouse=True)
def _capa_tuning_cargada(monkeypatch: pytest.MonkeyPatch) -> None:
    """Garantiza el hook poblado sea cual sea el orden de colección."""
    monkeypatch.setattr(_schema_mod, "_TUNING_CONFIG_CLS", TuningConfig)


# ─────────────────────────── defaults golden ───────────────────────────


def test_tuning_config_defaults_golden() -> None:
    """Los defaults D-TUN de SDD-13 §5 coinciden campo a campo."""
    assert TuningConfig().model_dump(mode="json") == {
        "type": "standard",
        "schema_version": "1.0.0",
        "objective": {"metric": "auc", "direction": "maximize"},
        "optimizer": {
            "sampler": "tpe",
            "pruner": "none",
            "n_trials": 50,
            "timeout_seconds": None,
        },
        "validation": {
            "strategy": "cv",
            "n_folds": 5,
            "holdout_fraction": 0.2,
            "fit_partition": "desarrollo",
        },
        "search_space": {"params": {}},
        "refit_best": True,
        "deterministic": True,
        "n_jobs": 1,
    }


def test_subconfigs_defaults() -> None:
    """Los sub-configs exponen sus defaults defendibles."""
    assert TuningObjectiveConfig().metric == "auc"
    assert TuningSamplerConfig().n_trials == 50
    assert TuningSamplerConfig().timeout_seconds is None
    assert TuningValidationConfig().strategy == "cv"
    assert TuningValidationConfig().n_folds == 5


def test_tuning_config_frozen_y_extra_forbid() -> None:
    """El config es inmutable y rechaza campos desconocidos (SDD-05)."""
    cfg = TuningConfig()
    with pytest.raises(ValidationError, match="frozen"):
        cfg.n_jobs = 4  # type: ignore[misc]
    with pytest.raises(ValidationError):
        TuningConfig(campo_ajeno=1)  # type: ignore[call-arg]


def test_campos_declaran_title() -> None:
    """Cada campo de tuning declara title (contrato UI, SDD-05 §5.3)."""
    modelos = (
        TuningConfig,
        TuningObjectiveConfig,
        TuningSamplerConfig,
        TuningValidationConfig,
    )
    for modelo in modelos:
        for nombre, campo in modelo.model_fields.items():
            assert campo.title is not None, f"{modelo.__name__}.{nombre} sin title"


# ─────────────────────────── validaciones de config (SDD-13 §5) ───────────────────────────


def test_deterministic_con_n_jobs_mayor_a_uno_falla() -> None:
    with pytest.raises(TuningConfigError, match="n_jobs=1"):
        TuningConfig(deterministic=True, n_jobs=4)


def test_deterministic_con_timeout_falla() -> None:
    with pytest.raises(TuningConfigError, match="timeout_seconds=None"):
        TuningConfig(deterministic=True, optimizer=TuningSamplerConfig(timeout_seconds=60))


def test_pruner_con_holdout_falla() -> None:
    with pytest.raises(TuningConfigError, match="strategy='cv'"):
        TuningConfig(
            optimizer=TuningSamplerConfig(pruner="median"),
            validation=TuningValidationConfig(strategy="holdout"),
        )


def test_pruner_median_con_cv_ok() -> None:
    """El pruner 'median' con validación 'cv' es coherente (valores por fold)."""
    cfg = TuningConfig(optimizer=TuningSamplerConfig(pruner="median"))
    assert cfg.optimizer.pruner == "median"
    assert cfg.validation.strategy == "cv"


def test_modo_performance_permite_paralelismo_y_timeout() -> None:
    """Con deterministic=False se admiten n_jobs>1 y timeout (modo performance)."""
    cfg = TuningConfig(
        deterministic=False,
        n_jobs=8,
        optimizer=TuningSamplerConfig(timeout_seconds=120),
    )
    assert cfg.n_jobs == 8
    assert cfg.optimizer.timeout_seconds == 120


@pytest.mark.parametrize(
    ("factory", "field", "value"),
    [
        (TuningObjectiveConfig, "metric", "f1"),
        (TuningObjectiveConfig, "direction", "minimize"),
        (TuningSamplerConfig, "sampler", "grid"),
        (TuningSamplerConfig, "pruner", "hyperband"),
        (TuningSamplerConfig, "n_trials", 0),
        (TuningSamplerConfig, "n_trials", 10001),
        (TuningSamplerConfig, "timeout_seconds", 0),
        (TuningValidationConfig, "strategy", "loo"),
        (TuningValidationConfig, "n_folds", 1),
        (TuningValidationConfig, "n_folds", 21),
        (TuningValidationConfig, "holdout_fraction", 0.0),
        (TuningValidationConfig, "holdout_fraction", 1.0),
        (TuningConfig, "type", "custom"),
        (TuningConfig, "n_jobs", 0),
        (TuningConfig, "n_jobs", 257),
    ],
)
def test_literales_y_rangos_invalidos_rechazados(
    factory: type[Any], field: str, value: object
) -> None:
    """Valores fuera de rango o literales desconocidos violan restricciones Pydantic."""
    with pytest.raises(ValidationError):
        factory(**{field: value})


# ─────────────────────────── resolve_search_space (cross-check con ml) ───────────────────────────


def test_resolve_search_space_ml_ausente_falla() -> None:
    """Sin sección `ml` no hay challenger que tunear (SDD-13 §5)."""
    with pytest.raises(TuningConfigError, match="challenger que tunear"):
        TuningConfig().resolve_search_space(None)


@pytest.mark.parametrize("backend", BACKENDS)
def test_resolve_search_space_vacio_usa_default_por_backend(backend: str) -> None:
    """Con `search_space` vacío se resuelve el default del backend de `ml`."""
    resuelto = TuningConfig().resolve_search_space(MLConfig(backend=backend))
    assert resuelto.params == default_search_space(backend).params  # type: ignore[arg-type]


def test_resolve_search_space_custom_valido_se_devuelve() -> None:
    """Un espacio declarado con claves/tipos válidos se devuelve intacto."""
    space = SearchSpaceConfig(
        params={
            "max_depth": IntSpec(low=2, high=6),
            "learning_rate": FloatSpec(low=0.01, high=0.2, log=True),
        }
    )
    cfg = TuningConfig(search_space=space)
    resuelto = cfg.resolve_search_space(MLConfig(backend="xgboost"))
    assert resuelto is cfg.search_space
    assert set(resuelto.params) == {"max_depth", "learning_rate"}


def test_resolve_search_space_clave_desconocida_falla() -> None:
    """Una clave que no es hiperparámetro del backend levanta TuningSearchSpaceError."""
    cfg = TuningConfig(search_space=SearchSpaceConfig(params={"no_existe": IntSpec(low=1, high=9)}))
    with pytest.raises(TuningSearchSpaceError, match="no existe en el backend 'xgboost'"):
        cfg.resolve_search_space(MLConfig(backend="xgboost"))


def test_resolve_search_space_tipo_incompatible_float_sobre_entero_falla() -> None:
    """Un FloatSpec sobre un hiperparámetro entero es incompatible (SDD-13 §5)."""
    cfg = TuningConfig(
        search_space=SearchSpaceConfig(params={"max_depth": FloatSpec(low=1.0, high=8.0)})
    )
    with pytest.raises(TuningSearchSpaceError, match="'float' es incompatible"):
        cfg.resolve_search_space(MLConfig(backend="xgboost"))


def test_resolve_search_space_int_sobre_literal_falla() -> None:
    """Un IntSpec sobre un hiperparámetro categórico (Literal) es incompatible."""
    cfg = TuningConfig(search_space=SearchSpaceConfig(params={"kernel": IntSpec(low=1, high=3)}))
    with pytest.raises(TuningSearchSpaceError, match="'int' es incompatible"):
        cfg.resolve_search_space(MLConfig(backend="svm"))


def test_resolve_search_space_categorical_es_universal() -> None:
    """CategoricalSpec es compatible con cualquier hiperparámetro (enumera valores concretos)."""
    # Sobre un Literal (svm.kernel).
    cfg_lit = TuningConfig(
        search_space=SearchSpaceConfig(
            params={"kernel": CategoricalSpec(choices=("rbf", "linear"))}
        )
    )
    resuelto_lit = cfg_lit.resolve_search_space(MLConfig(backend="svm"))
    assert isinstance(resuelto_lit.params["kernel"], CategoricalSpec)
    # Sobre un entero (xgboost.max_depth).
    cfg_int = TuningConfig(
        search_space=SearchSpaceConfig(params={"max_depth": CategoricalSpec(choices=(3, 5, 7))})
    )
    resuelto_int = cfg_int.resolve_search_space(MLConfig(backend="xgboost"))
    assert isinstance(resuelto_int.params["max_depth"], CategoricalSpec)


def test_resolve_search_space_intspec_sobre_int_opcional_ok() -> None:
    """IntSpec sobre un campo ``int | None`` (random_forest max_depth) es compatible."""
    cfg = TuningConfig(
        search_space=SearchSpaceConfig(params={"max_depth": IntSpec(low=2, high=16)})
    )
    resuelto = cfg.resolve_search_space(MLConfig(backend="random_forest"))
    assert isinstance(resuelto.params["max_depth"], IntSpec)


def test_kinds_admitidos_cubre_tipos() -> None:
    """El helper deriva int/float de tipos simples y uniones, vacío para Literal/None."""
    from typing import Literal

    assert _kinds_admitidos(int) == frozenset({"int"})
    assert _kinds_admitidos(float) == frozenset({"float"})
    assert _kinds_admitidos(int | None) == frozenset({"int"})
    assert _kinds_admitidos(Literal["a", "b"] | float) == frozenset({"float"})
    assert _kinds_admitidos(Literal["a", "b"]) == frozenset()
    assert _kinds_admitidos(str) == frozenset()


# ─────────────────────────── FALTA-DATO-TUN-1: config con random_forest y n_trials bajo ──────────


def test_config_random_forest_n_trials_bajo() -> None:
    """Config barato para CI: backend liviano y pocos trials (FALTA-DATO-TUN-1)."""
    cfg = TuningConfig(optimizer=TuningSamplerConfig(n_trials=3))
    resuelto = cfg.resolve_search_space(MLConfig(backend="random_forest"))
    assert cfg.optimizer.n_trials == 3
    assert set(resuelto.params) == {
        "n_estimators",
        "max_depth",
        "min_samples_leaf",
        "max_features",
    }


# ─────────────────────────── integración con NikodymConfig ───────────────────────────


def test_nikodymconfig_tuning_instancia_pasa() -> None:
    """Una instancia `TuningConfig` se acepta y queda tipada."""
    cfg = NikodymConfig(tuning=TuningConfig())
    assert isinstance(cfg.tuning, TuningConfig)


def test_nikodymconfig_tuning_dict_coacciona() -> None:
    """Con el hook poblado, un dict se coacciona a TuningConfig."""
    cfg = NikodymConfig(tuning={"optimizer": {"n_trials": 10}})
    assert isinstance(cfg.tuning, TuningConfig)
    assert cfg.tuning.optimizer.n_trials == 10


def test_nikodymconfig_tuning_none_explicito() -> None:
    """`tuning=None` explícito pasa por el validador y queda inactivo."""
    assert NikodymConfig(tuning=None).tuning is None


def test_nikodymconfig_tuning_core_only_acepta_blob_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sin hook cargado, `tuning` acepta un blob JSON-canónico determinista."""
    monkeypatch.setattr(_schema_mod, "_TUNING_CONFIG_CLS", None)
    cfg = NikodymConfig(tuning={"optimizer": {"n_trials": 25}})
    assert cfg.tuning == {"optimizer": {"n_trials": 25}}


@pytest.mark.parametrize("blob", [{"cols": {"a", "b"}}, {"valor": math.nan}])
def test_nikodymconfig_tuning_core_only_rechaza_json_no_canonico(
    monkeypatch: pytest.MonkeyPatch,
    blob: dict[str, object],
) -> None:
    """Sin hook cargado, `tuning` rechaza sets y floats no finitos."""
    monkeypatch.setattr(_schema_mod, "_TUNING_CONFIG_CLS", None)
    with pytest.raises(ValidationError):
        NikodymConfig(tuning=blob)


# ─────────────────────────── config_hash ───────────────────────────


def test_config_hash_default_con_tuning_none_golden() -> None:
    """El golden por defecto incluye la clave computacional `tuning=None`."""
    assert config_hash(NikodymConfig()) == GOLDEN_DEFAULT_CONFIG_HASH


def test_config_hash_se_movio_por_seccion_tuning() -> None:
    """Añadir `tuning` movió el golden respecto al valor previo (no es regresión)."""
    assert GOLDEN_DEFAULT_CONFIG_HASH != GOLDEN_PREVIO_SIN_TUNING
    assert config_hash(NikodymConfig()) != GOLDEN_PREVIO_SIN_TUNING


def test_config_hash_es_puramente_aditivo_sobre_tuning() -> None:
    """Quitar `tuning:null` y `explain:null` (B14.1) reproduce el hash previo (aditivo)."""
    payload = NikodymConfig().model_dump(mode="json", by_alias=True, exclude=set(INFRA_SECTIONS))
    assert payload["tuning"] is None
    assert payload["explain"] is None
    del payload["tuning"]
    del payload["explain"]
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    previo = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    assert previo == GOLDEN_PREVIO_SIN_TUNING


def test_tuning_no_esta_en_infra_sections() -> None:
    """`tuning` es computacional: no se excluye del config_hash."""
    assert "tuning" not in INFRA_SECTIONS


@pytest.mark.parametrize(
    "tuning",
    [
        TuningConfig(optimizer=TuningSamplerConfig(sampler="random")),
        TuningConfig(optimizer=TuningSamplerConfig(n_trials=100)),
        TuningConfig(objective=TuningObjectiveConfig(metric="ks")),
        TuningConfig(search_space=SearchSpaceConfig(params={"max_depth": IntSpec(low=2, high=4)})),
    ],
)
def test_cambiar_tuning_mueve_config_hash(tuning: TuningConfig) -> None:
    """Cambiar sampler/n_trials/métrica/espacio mueve el config_hash global (computacional)."""
    base = config_hash(NikodymConfig())
    variado = config_hash(NikodymConfig(tuning=tuning))
    assert variado != base


# ─────────────────────────── round-trip YAML ───────────────────────────


def test_round_trip_yaml_preserva_tuning() -> None:
    """El dump/load YAML preserva la configuración de tuning (SDD-05)."""
    original = TuningConfig(
        optimizer=TuningSamplerConfig(sampler="random", n_trials=20),
        validation=TuningValidationConfig(strategy="holdout", holdout_fraction=0.25),
        search_space=SearchSpaceConfig(params={"learning_rate": FloatSpec(low=0.01, high=0.2)}),
    )
    texto = yaml.safe_dump(original.model_dump(mode="json"), sort_keys=False)
    recargado = TuningConfig.model_validate(yaml.safe_load(texto))
    assert recargado == original


# ─────────────────────────── import liviano y hook ───────────────────────────


def test_import_tuning_liviano_y_registra_hook_en_proceso_fresco() -> None:
    """`import nikodym.tuning` registra el hook sin arrastrar optuna/ML/tabulares."""
    code = (
        "import nikodym.tuning, nikodym.core, sys;"
        "from nikodym.core.config import NikodymConfig;"
        "from nikodym.tuning import TuningConfig;"
        "bloqueados=[m for m in "
        "('optuna','numpy','pandas','scipy','sklearn','xgboost','lightgbm','catboost',"
        "'nikodym.ml','nikodym.tuning.results') "
        "if m in sys.modules];"
        "assert not bloqueados, bloqueados;"
        "cfg=NikodymConfig(tuning={'optimizer': {'n_trials': 7}});"
        "assert isinstance(cfg.tuning, TuningConfig)"
    )
    subprocess.run([sys.executable, "-c", code], check=True)


def test_core_valida_tuning_como_blob_opaco_sin_importar_la_capa() -> None:
    """El core acepta `tuning` JSON/dict sin importar la capa de tuning."""
    code = (
        "from nikodym.core.config import NikodymConfig;"
        "import sys;"
        "cfg=NikodymConfig(tuning={'optimizer': {'n_trials': 7}});"
        "assert cfg.tuning == {'optimizer': {'n_trials': 7}};"
        "assert 'nikodym.tuning' not in sys.modules"
    )
    subprocess.run([sys.executable, "-c", code], check=True)


def test_hook_poblado_tras_import() -> None:
    """Importar la capa deja el hook `_TUNING_CONFIG_CLS` apuntando a `TuningConfig`."""
    assert tuning_pkg.TuningConfig is TuningConfig
