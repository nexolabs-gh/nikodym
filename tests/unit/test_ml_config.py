"""Tests de ``MLConfig`` (SDD-12 §5) e integración con ``NikodymConfig``."""

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

import nikodym.ml as ml_pkg  # importa la capa: puebla el hook
from nikodym.core.config import (
    INFRA_SECTIONS,
    NikodymConfig,
    config_hash,
)
from nikodym.core.config import schema as _schema_mod
from nikodym.core.exceptions import NikodymError
from nikodym.ml.config import (
    CatBoostParams,
    LightGBMParams,
    MLComparisonConfig,
    MLConfig,
    MLOutputConfig,
    MLTrainConfig,
    MonotonicConfig,
    RandomForestParams,
    SvmParams,
    XGBoostParams,
)
from nikodym.ml.exceptions import (
    MLBackendError,
    MLComparisonError,
    MLConfigError,
    MLDataError,
    MLDeterminismError,
    MLError,
    MLFitError,
    MLMonotonicError,
    MLPredictError,
)

# Golden del config_hash por defecto tras añadir la sección computacional `ml`.
GOLDEN_DEFAULT_CONFIG_HASH = "cbc42cfc02993f6646a744d66d2e0e348285e07761f59f434469afe2e8801610"
# Golden anterior (antes de B12.1, con validation ya presente); el hash DEBE moverse.
GOLDEN_PREVIO_SIN_ML = "70dbc51fb6c230afac21fb20fa1d28e6e766d09759d5d765d82ab5cd5aacc1a8"


@pytest.fixture(autouse=True)
def _capa_ml_cargada(monkeypatch: pytest.MonkeyPatch) -> None:
    """Garantiza el hook poblado sea cual sea el orden de colección."""
    monkeypatch.setattr(_schema_mod, "_ML_CONFIG_CLS", MLConfig)


def _ml_defaults() -> dict[str, Any]:
    """Snapshot de defaults defendibles de SDD-12 §5 (D-ML-1..11)."""
    return {
        "schema_version": "1.0.0",
        "type": "standard",
        "backend": "xgboost",
        "feature_source": "binning_woe",
        "hyperparameters": {
            "n_estimators": 500,
            "max_depth": 3,
            "learning_rate": 0.05,
            "subsample": 0.8,
            "colsample_bytree": 0.8,
            "reg_lambda": 1.0,
            "min_child_weight": 1.0,
        },
        "train": {
            "fit_partition": "desarrollo",
            "predict_partitions": ["desarrollo", "holdout", "oot"],
            "validation_fraction": 0.2,
            "early_stopping_rounds": 50,
            "class_weight": "none",
            "require_both_classes": True,
        },
        "monotonic": {
            "mode": "from_binning",
            "explicit": {},
            "on_unsupported": "warn",
        },
        "comparison": {
            "metrics": ["auc", "gini", "ks", "psi"],
            "partitions": ["desarrollo", "holdout", "oot"],
            "tie_tolerance": 1e-06,
        },
        "calibrate_challenger": False,
        "output": {
            "publish_calibrated_pd": True,
            "publish_feature_importances": True,
            "top_k_importances": 30,
        },
        "deterministic": True,
        "n_threads": 1,
        "target_column": "target",
        "partition_column": "partition",
        "pd_hat_column": "pd_hat",
    }


def _config_no_trivial() -> MLConfig:
    """Config de ML no trivial que ejercita ramas válidas del schema (no defaults)."""
    return MLConfig(
        backend="lightgbm",
        feature_source="selection_woe",
        hyperparameters=LightGBMParams(num_leaves=20, learning_rate=0.1),
        train=MLTrainConfig(
            fit_partition="dev",
            predict_partitions=("dev", "oot"),
            validation_fraction=0.3,
            early_stopping_rounds=25,
            class_weight="balanced",
            require_both_classes=False,
        ),
        monotonic=MonotonicConfig(
            mode="explicit",
            explicit={"ingreso__woe": -1, "mora__woe": 1},
            on_unsupported="error",
        ),
        comparison=MLComparisonConfig(
            metrics=("auc", "ks"),
            partitions=("dev", "oot"),
            tie_tolerance=1e-4,
        ),
        calibrate_challenger=True,
        output=MLOutputConfig(
            publish_calibrated_pd=False,
            publish_feature_importances=False,
            top_k_importances=10,
        ),
        deterministic=False,
        n_threads=8,
        target_column="malo",
        partition_column="muestra",
        pd_hat_column="pd_ml",
    )


# ─────────────────────────── defaults / round-trip ───────────────────────────


def test_mlconfig_defaults_golden() -> None:
    """``MLConfig()`` construye sin argumentos y coincide con el golden de defaults."""
    assert MLConfig().model_dump(mode="json") == _ml_defaults()


def test_subconfigs_construyen_sin_argumentos() -> None:
    """Cada sub-config construye con defaults sin argumentos (DoD F0)."""
    assert XGBoostParams().max_depth == 3
    assert RandomForestParams().n_estimators == 300
    assert LightGBMParams().num_leaves == 31
    assert CatBoostParams().depth == 4
    assert SvmParams().kernel == "rbf"
    assert MLTrainConfig().validation_fraction == 0.2
    assert MonotonicConfig().mode == "from_binning"
    assert MLComparisonConfig().tie_tolerance == 1e-6
    assert MLOutputConfig().top_k_importances == 30


def test_round_trip_yaml_mlconfig() -> None:
    """Serializar y recargar ``MLConfig`` por YAML preserva igualdad exacta."""
    cfg = _config_no_trivial()
    text = yaml.safe_dump(cfg.model_dump(mode="json"), sort_keys=False, allow_unicode=True)
    assert MLConfig.model_validate(yaml.safe_load(text)) == cfg


def test_round_trip_yaml_default() -> None:
    """El default también round-trippea exacto (hiperparámetros resueltos incluidos)."""
    cfg = MLConfig()
    text = yaml.safe_dump(cfg.model_dump(mode="json"), sort_keys=False, allow_unicode=True)
    assert MLConfig.model_validate(yaml.safe_load(text)) == cfg


# ─────────────────────────── resolución de hiperparámetros por backend ───────────────────────────


@pytest.mark.parametrize(
    ("backend", "params_cls"),
    [
        ("svm", SvmParams),
        ("random_forest", RandomForestParams),
        ("xgboost", XGBoostParams),
        ("lightgbm", LightGBMParams),
        ("catboost", CatBoostParams),
    ],
)
def test_hyperparameters_none_instancia_defaults_del_backend(
    backend: str, params_cls: type[Any]
) -> None:
    """``hyperparameters=None`` instancia los defaults del backend seleccionado."""
    cfg = MLConfig(backend=backend)
    assert isinstance(cfg.hyperparameters, params_cls)


def test_hyperparameters_dict_routea_al_backend() -> None:
    """Un ``dict`` se valida contra el modelo tipado del backend (no por unión smart)."""
    cfg = MLConfig(backend="xgboost", hyperparameters={"max_depth": 5})
    assert isinstance(cfg.hyperparameters, XGBoostParams)
    assert cfg.hyperparameters.max_depth == 5


def test_hyperparameters_instancia_correcta_pasa() -> None:
    """Una instancia del backend correcto pasa tal cual."""
    params = XGBoostParams(max_depth=7)
    cfg = MLConfig(backend="xgboost", hyperparameters=params)
    assert cfg.hyperparameters == params


def test_hyperparameters_de_otro_backend_levanta_mlconfigerror() -> None:
    """Una instancia de hiperparámetros de otro backend levanta ``MLConfigError``."""
    with pytest.raises(MLConfigError, match="hyperparameters"):
        MLConfig(backend="lightgbm", hyperparameters=XGBoostParams())


def test_hyperparameters_dict_con_campos_de_otro_backend_rechazado() -> None:
    """Un ``dict`` con campos ajenos al backend viola ``extra='forbid'`` del sub-schema."""
    with pytest.raises(ValidationError):
        MLConfig(backend="xgboost", hyperparameters={"num_leaves": 31})


def test_backend_desconocido_rechazado_por_pydantic() -> None:
    """Un backend fuera del ``Literal`` se rechaza (la resolución lo deja pasar al campo)."""
    with pytest.raises(ValidationError):
        MLConfig(backend="perceptron")


def test_input_no_dict_rechazado() -> None:
    """La resolución deja pasar un input no-dict para que Pydantic levante el error estándar."""
    with pytest.raises(ValidationError):
        MLConfig.model_validate("no-soy-un-dict")


# ─────────────────────────── validaciones §5 ───────────────────────────


def test_deterministic_con_multihilo_falla() -> None:
    """``deterministic=True`` con ``n_threads>1`` es contradictorio (§5)."""
    with pytest.raises(MLConfigError, match="deterministic"):
        MLConfig(deterministic=True, n_threads=4)


def test_multihilo_no_determinista_construye() -> None:
    """``deterministic=False`` habilita el modo performance multihilo."""
    cfg = MLConfig(deterministic=False, n_threads=8)
    assert cfg.n_threads == 8
    assert cfg.deterministic is False


def test_monotonic_explicit_vacio_falla() -> None:
    """``monotonic.mode='explicit'`` con mapa vacío levanta ``MLConfigError``."""
    with pytest.raises(MLConfigError, match="explicit"):
        MLConfig(monotonic=MonotonicConfig(mode="explicit"))


def test_monotonic_explicit_con_mapa_construye() -> None:
    """``monotonic.mode='explicit'`` con mapa no vacío construye."""
    cfg = MLConfig(monotonic=MonotonicConfig(mode="explicit", explicit={"x__woe": -1}))
    assert cfg.monotonic.explicit == {"x__woe": -1}


@pytest.mark.parametrize("backend", ["svm", "random_forest"])
def test_monotonia_en_backend_sin_soporte_con_error_levanta(backend: str) -> None:
    """Monotonía en svm/rf con ``on_unsupported='error'`` levanta ``MLMonotonicError``."""
    with pytest.raises(MLMonotonicError, match="monotonic"):
        MLConfig(
            backend=backend,
            monotonic=MonotonicConfig(mode="from_binning", on_unsupported="error"),
        )


@pytest.mark.parametrize("backend", ["svm", "random_forest"])
def test_monotonia_en_backend_sin_soporte_con_warn_construye(backend: str) -> None:
    """Con ``on_unsupported='warn'`` la constraint se difiere a runtime (no falla en config)."""
    cfg = MLConfig(
        backend=backend,
        monotonic=MonotonicConfig(mode="from_binning", on_unsupported="warn"),
    )
    assert cfg.backend == backend


def test_monotonia_off_en_backend_sin_soporte_construye() -> None:
    """``monotonic.mode='off'`` no gatilla el chequeo de soporte aunque el backend no lo tenga."""
    cfg = MLConfig(backend="svm", monotonic=MonotonicConfig(mode="off", on_unsupported="error"))
    assert cfg.monotonic.mode == "off"


@pytest.mark.parametrize("backend", ["svm", "random_forest"])
def test_data_raw_en_backend_intolerante_a_nan_levanta(backend: str) -> None:
    """``feature_source='data_raw'`` con svm/random_forest exige imputación: FALTA-DATO-ML-1."""
    with pytest.raises(MLConfigError, match="FALTA-DATO-ML-1"):
        MLConfig(backend=backend, feature_source="data_raw")


@pytest.mark.parametrize("backend", ["xgboost", "lightgbm", "catboost"])
def test_data_raw_en_gbdt_construye(backend: str) -> None:
    """``feature_source='data_raw'`` con GBDT construye (los GBDT toleran NaN nativamente)."""
    cfg = MLConfig(backend=backend, feature_source="data_raw")
    assert cfg.feature_source == "data_raw"


@pytest.mark.parametrize("backend", ["xgboost", "lightgbm", "catboost"])
def test_early_stopping_sin_validation_fraction_en_gbdt_falla(backend: str) -> None:
    """``validation_fraction=0`` con ``early_stopping_rounds`` en GBDT es contradictorio (§5)."""
    with pytest.raises(MLConfigError, match="early_stopping"):
        MLConfig(backend=backend, train=MLTrainConfig(validation_fraction=0.0))


@pytest.mark.parametrize("backend", ["xgboost", "lightgbm", "catboost"])
def test_early_stopping_desactivado_construye(backend: str) -> None:
    """``validation_fraction=0`` con ``early_stopping_rounds=None`` desactiva el early stopping."""
    cfg = MLConfig(
        backend=backend,
        train=MLTrainConfig(validation_fraction=0.0, early_stopping_rounds=None),
    )
    assert cfg.train.early_stopping_rounds is None


def test_validation_fraction_cero_en_no_gbdt_no_contradice() -> None:
    """En svm/random_forest ``validation_fraction=0`` con early stopping declarado no falla."""
    cfg = MLConfig(backend="random_forest", train=MLTrainConfig(validation_fraction=0.0))
    assert cfg.train.validation_fraction == 0.0


# ─────────────────────────── integración NikodymConfig ───────────────────────────


def test_nikodymconfig_ml_instancia() -> None:
    """Pasar una instancia ``MLConfig`` a ``NikodymConfig`` la conserva."""
    ml = MLConfig()
    cfg = NikodymConfig(ml=ml)
    assert isinstance(cfg.ml, MLConfig)
    assert cfg.ml is ml


def test_nikodymconfig_ml_dict_coacciona() -> None:
    """Un dict en ``ml`` se coacciona por el hook cargado."""
    cfg = NikodymConfig(ml={"backend": "lightgbm"})
    assert isinstance(cfg.ml, MLConfig)
    assert cfg.ml.backend == "lightgbm"
    assert isinstance(cfg.ml.hyperparameters, LightGBMParams)


def test_nikodymconfig_ml_none_explicito() -> None:
    """``ml=None`` explícito pasa por el validador y queda inactivo."""
    assert NikodymConfig(ml=None).ml is None


def test_nikodymconfig_ml_core_only_acepta_blob_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sin hook cargado, ``ml`` acepta un blob JSON-canónico determinista."""
    monkeypatch.setattr(_schema_mod, "_ML_CONFIG_CLS", None)
    cfg = NikodymConfig(ml={"backend": "xgboost"})
    assert cfg.ml == {"backend": "xgboost"}


@pytest.mark.parametrize("blob", [{"cols": {"a", "b"}}, {"valor": math.nan}])
def test_nikodymconfig_ml_core_only_rechaza_json_no_canonico(
    monkeypatch: pytest.MonkeyPatch,
    blob: dict[str, object],
) -> None:
    """Sin hook cargado, ``ml`` rechaza sets y floats no finitos."""
    monkeypatch.setattr(_schema_mod, "_ML_CONFIG_CLS", None)
    with pytest.raises(ValidationError):
        NikodymConfig(ml=blob)


# ─────────────────────────── literales y rangos Pydantic ───────────────────────────


@pytest.mark.parametrize(
    ("factory", "field", "value"),
    [
        (XGBoostParams, "max_depth", 0),
        (XGBoostParams, "max_depth", 13),
        (XGBoostParams, "learning_rate", 0.0),
        (XGBoostParams, "learning_rate", 1.5),
        (XGBoostParams, "n_estimators", 0),
        (XGBoostParams, "subsample", 0.0),
        (RandomForestParams, "n_estimators", 0),
        (RandomForestParams, "min_samples_leaf", 0),
        (LightGBMParams, "num_leaves", 1),
        (LightGBMParams, "num_leaves", 2000),
        (CatBoostParams, "depth", 0),
        (CatBoostParams, "depth", 17),
        (SvmParams, "C", 0.0),
        (SvmParams, "kernel", "poly"),
        (MonotonicConfig, "mode", "auto"),
        (MonotonicConfig, "on_unsupported", "ignore"),
        (MLTrainConfig, "validation_fraction", 1.0),
        (MLTrainConfig, "validation_fraction", -0.1),
        (MLTrainConfig, "early_stopping_rounds", 0),
        (MLTrainConfig, "class_weight", "auto"),
        (MLComparisonConfig, "tie_tolerance", 0.0),
        (MLComparisonConfig, "tie_tolerance", 0.1),
        (MLComparisonConfig, "metrics", ("f1",)),
        (MLOutputConfig, "top_k_importances", 0),
        (MLConfig, "backend", "keras"),
        (MLConfig, "feature_source", "embeddings"),
        (MLConfig, "type", "custom"),
        (MLConfig, "n_threads", 0),
        (MLConfig, "n_threads", 257),
    ],
)
def test_literales_y_rangos_invalidos_rechazados_por_pydantic(
    factory: type[Any],
    field: str,
    value: object,
) -> None:
    """Valores fuera de rango o literales desconocidos violan restricciones Pydantic."""
    with pytest.raises(ValidationError):
        factory(**{field: value})


# ─────────────────────────── config_hash ───────────────────────────


def test_config_hash_default_con_ml_none_golden() -> None:
    """El golden por defecto incluye la clave computacional ``ml=None``."""
    assert config_hash(NikodymConfig()) == GOLDEN_DEFAULT_CONFIG_HASH


def test_config_hash_se_movio_por_seccion_ml() -> None:
    """Añadir ``ml`` movió el golden respecto al valor previo (no es regresión)."""
    assert GOLDEN_DEFAULT_CONFIG_HASH != GOLDEN_PREVIO_SIN_ML
    assert config_hash(NikodymConfig()) != GOLDEN_PREVIO_SIN_ML


def test_config_hash_es_puramente_aditivo_sobre_ml() -> None:
    """Quitar ``ml:null`` (y ``tuning:null``/``explain:null`` posteriores) da el hash previo.

    B13.2 añadió ``tuning:null`` y B14.1 ``explain:null`` al payload canónico DESPUÉS de ``ml``;
    para reconstruir el estado inmediatamente anterior a ``ml`` hay que retirar las tres claves
    computacionales nuevas.
    """
    payload = NikodymConfig().model_dump(mode="json", by_alias=True, exclude=set(INFRA_SECTIONS))
    assert payload["ml"] is None
    assert payload["tuning"] is None
    assert payload["explain"] is None
    del payload["ml"]
    del payload["tuning"]
    del payload["explain"]
    del payload["provisioning_internal"]
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    previo = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    assert previo == GOLDEN_PREVIO_SIN_ML


@pytest.mark.parametrize(
    "ml",
    [
        MLConfig(backend="lightgbm"),
        MLConfig(backend="catboost"),
        MLConfig(hyperparameters=XGBoostParams(max_depth=6)),
        MLConfig(feature_source="selection_woe"),
        MLConfig(monotonic=MonotonicConfig(mode="off")),
        MLConfig(monotonic=MonotonicConfig(mode="explicit", explicit={"x__woe": -1})),
        MLConfig(calibrate_challenger=True),
        MLConfig(deterministic=False, n_threads=4),
        MLConfig(train=MLTrainConfig(validation_fraction=0.1)),
        MLConfig(comparison=MLComparisonConfig(metrics=("auc",))),
    ],
)
def test_config_hash_cambia_al_variar_ml(ml: MLConfig) -> None:
    """``ml`` no es INFRA: backend/hiperparámetros/fuente/monotonía/etc. cambian el hash."""
    base = config_hash(NikodymConfig(ml=MLConfig()))
    variado = config_hash(NikodymConfig(ml=ml))
    assert "ml" not in INFRA_SECTIONS
    assert variado != base


def test_config_hash_cambia_backend_por_hiperparametros_distintos() -> None:
    """Cambiar backend mueve el hash porque cambian los hiperparámetros resueltos."""
    xgb = config_hash(NikodymConfig(ml=MLConfig(backend="xgboost")))
    lgbm = config_hash(NikodymConfig(ml=MLConfig(backend="lightgbm")))
    assert xgb != lgbm


# ─────────────────────────── metadata UI + API pública ───────────────────────────


def test_campos_ml_tienen_metadatos_ui() -> None:
    """Todos los campos de config de ML declaran metadata de UI para SDD-23."""
    for modelo in (
        SvmParams,
        RandomForestParams,
        XGBoostParams,
        LightGBMParams,
        CatBoostParams,
        MonotonicConfig,
        MLTrainConfig,
        MLComparisonConfig,
        MLOutputConfig,
        MLConfig,
    ):
        for nombre, campo in modelo.model_fields.items():
            extra = campo.json_schema_extra
            assert campo.title is not None, f"{modelo.__name__}.{nombre} sin title"
            assert campo.description is not None, f"{modelo.__name__}.{nombre} sin description"
            assert isinstance(extra, dict), f"{modelo.__name__}.{nombre} sin ui_*"
            assert {"ui_widget", "ui_group", "ui_order"} <= set(extra)


def test_ml_public_api_minimo() -> None:
    """El paquete de ML expone config y excepciones de B12.1."""
    assert ml_pkg.MLConfig is MLConfig
    assert ml_pkg.MLError is MLError
    assert "MLConfig" in ml_pkg.__all__
    assert "MLError" in ml_pkg.__all__


def test_ml_errors_descienden_de_nikodym_error() -> None:
    """Las excepciones de ``ml`` cuelgan de la raíz propia de la librería."""
    for error_cls in (
        MLError,
        MLConfigError,
        MLDataError,
        MLBackendError,
        MLFitError,
        MLPredictError,
        MLMonotonicError,
        MLComparisonError,
        MLDeterminismError,
    ):
        assert issubclass(error_cls, NikodymError)
        assert issubclass(error_cls, MLError)


def test_ml_jerarquia_de_excepciones() -> None:
    """La jerarquía §4 respeta las relaciones de subclase declaradas."""
    assert issubclass(MLFitError, MLBackendError)
    assert issubclass(MLPredictError, MLBackendError)
    assert issubclass(MLMonotonicError, MLConfigError)


def test_ml_getattr_desconocido_levanta() -> None:
    """Un atributo desconocido del paquete levanta ``AttributeError``."""
    with pytest.raises(AttributeError, match="ml"):
        _ = ml_pkg.no_existe  # type: ignore[attr-defined]


# ─────────────────────────── import liviano (núcleo) ───────────────────────────


def test_import_ml_config_liviano_y_registra_hook_en_proceso_fresco() -> None:
    """``import nikodym.ml.config`` registra el hook sin arrastrar librerías ML ni tabulares."""
    code = (
        "import nikodym.ml.config, nikodym.core, sys;"
        "from nikodym.core.config import NikodymConfig;"
        "from nikodym.ml.config import MLConfig;"
        "bloqueados=[m for m in "
        "('numpy','pandas','pandera','pyarrow','scipy','sklearn','xgboost','lightgbm',"
        "'catboost','nikodym.tracking','mlflow','nikodym.data') "
        "if m in sys.modules];"
        "assert not bloqueados, bloqueados;"
        "cfg=NikodymConfig(ml={'backend': 'xgboost'});"
        "assert isinstance(cfg.ml, MLConfig)"
    )
    subprocess.run([sys.executable, "-c", code], check=True)


def test_core_valida_ml_como_blob_opaco_sin_importar_la_capa() -> None:
    """El core acepta ``ml`` JSON/dict sin importar la capa de ML."""
    code = (
        "from nikodym.core.config import NikodymConfig;"
        "import sys;"
        "cfg=NikodymConfig(ml={'backend': 'xgboost'});"
        "assert cfg.ml == {'backend': 'xgboost'};"
        "assert 'nikodym.ml' not in sys.modules"
    )
    subprocess.run([sys.executable, "-c", code], check=True)
