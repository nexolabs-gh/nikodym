"""Tests del preset estándar F1 (SDD-23 §3.2, §5): validez, coherencia con el dataset y endpoint.

El preset es un config F1 COMPLETO y *domain-agnostic* (dict literal en :mod:`nikodym.ui.presets`);
aquí se verifica que (a) valida y su ``config_hash`` es estable, (b) toda columna que referencia
existe en el registro de datasets con el rol correcto —lo que da confianza de que la corrida real
correrá— y (c) el endpoint ``GET /api/config/preset`` lo sirve. El *smoke* end-to-end real (correr
el motor OR-Tools/mip y ver el scorecard) NO vive aquí: es lento y se hace fuera de la suite.
"""

from __future__ import annotations

from typing import Any

from nikodym.core.config import NikodymConfig, config_hash
from nikodym.ui import datasets as datasets_module
from nikodym.ui import routes
from nikodym.ui.presets import STANDARD_DATASET_ID, standard_preset

# ``config_hash`` del preset estándar F1: identidad estable del literal (SDD-05 §5.5). Si cambia una
# sección de dominio del preset, regenerar el literal y actualizar este valor conscientemente.
# Actualizado en B32a al ACTIVAR la sección ``stability`` (antes ``None``): el preset cambió de
# verdad (estabilidad post-modelo entra al ``config_hash`` global) → hash legítimamente nuevo.
_EXPECTED_CONFIG_HASH = "f53ffc9f11eaac299a42c857fd7704401361603d91fba584ce439382bb1f59a9"


# ─────────────────────────────── validez y hash estable ───────────────────────────────


def test_standard_preset_shape() -> None:
    """``standard_preset`` entrega ``{id, name, description, config, dataset_id}``."""
    preset = standard_preset()
    assert set(preset) == {"id", "name", "description", "config", "dataset_id"}
    assert preset["dataset_id"] == STANDARD_DATASET_ID
    assert isinstance(preset["config"], dict)


def test_standard_preset_config_valida_y_hash_estable() -> None:
    """El config del preset reconstruye ``NikodymConfig`` y su ``config_hash`` es determinista."""
    config = standard_preset()["config"]
    model = NikodymConfig.model_validate(config)  # no debe levantar
    assert config_hash(model) == _EXPECTED_CONFIG_HASH
    # Determinismo: revalidar una copia independiente da exactamente el mismo hash.
    assert config_hash(NikodymConfig.model_validate(standard_preset()["config"])) == config_hash(
        model
    )


def test_standard_preset_devuelve_copia_defensiva() -> None:
    """Cada llamada devuelve un config nuevo: mutarlo no contamina el literal compartido."""
    primero = standard_preset()["config"]
    primero["binning"]["time_limit"] = 999
    segundo = standard_preset()["config"]
    assert segundo["binning"]["time_limit"] != 999


# ─────────────────────────── coherencia con el dataset sintético ───────────────────────────


def test_preset_coherente_con_columnas_del_dataset() -> None:
    """Toda columna cruda referenciada por el preset existe en el dataset con el rol correcto.

    Es la garantía barata (sin correr el motor) de que la corrida real materializará y binneará:
    id/target/segment/cohort y las features candidatas mapean a columnas reales de
    ``datasets._COLUMNS`` con su rol. Las columnas *derivadas* (target derivado, score, partition,
    pd_calibrated) NO se chequean: las produce el pipeline aguas abajo, no el dataset.
    """
    preset = standard_preset()
    config = preset["config"]
    role_by_name = {column["name"]: column["role"] for column in datasets_module._COLUMNS}
    data = config["data"]

    # Índice = columna de rol 'id'.
    assert role_by_name.get(data["schema"]["index_col"]) == "id"
    # Toda columna declarada en el esquema existe en el dataset.
    for column in data["schema"]["columns"]:
        assert column["name"] in role_by_name, column["name"]
    # El target se define por una regla sobre una columna de rol 'target'.
    for predicate in data["target"]["bad_rule"]["all_of"]:
        assert role_by_name.get(predicate["col"]) == "target"
    # Partición por cohorte: la columna es de rol 'cohort'.
    strategy = data["partition"]["strategy"]
    assert role_by_name.get(strategy["cohort_col"]) == "cohort"

    binning = config["binning"]
    # Toda feature candidata del binning existe en el dataset.
    for name in binning["feature_columns"]:
        assert name in role_by_name, name
    # La columna categórica del binning es el segmento (rol 'segment').
    for name in binning["categorical_columns"]:
        assert role_by_name.get(name) == "segment"
    # Las features restantes (no categóricas) son columnas numéricas de rol 'feature'.
    numericas = [n for n in binning["feature_columns"] if n not in binning["categorical_columns"]]
    assert numericas, "el preset debe declarar al menos una feature numérica"
    for name in numericas:
        assert role_by_name.get(name) == "feature"


def test_preset_oot_cohorts_existen_en_el_dataset() -> None:
    """Las cohortes reservadas como OOT existen en el dataset recomendado (partición no vacía)."""
    preset = standard_preset()
    spec = datasets_module._DATASETS[preset["dataset_id"]]
    for cohort in preset["config"]["data"]["partition"]["strategy"]["oot_cohorts"]:
        assert cohort in spec["cohorts"], cohort


# ─────────────────────────────── preset_payload (lógica pura) ───────────────────────────────


def test_preset_payload_shape_y_hash() -> None:
    """``preset_payload`` entrega las 5 claves del contrato con el hash del config servido."""
    payload = routes.preset_payload()
    assert set(payload) == {"config", "config_hash", "dataset_id", "name", "description"}
    assert payload["dataset_id"] == STANDARD_DATASET_ID
    model = NikodymConfig.model_validate(payload["config"])
    assert payload["config_hash"] == config_hash(model) == _EXPECTED_CONFIG_HASH


# ─────────────────────────────── endpoint (TestClient) ───────────────────────────────


def test_endpoint_config_preset() -> None:
    """``GET /api/config/preset`` → 200 con ``{config, config_hash}`` y el config valida."""
    import pytest

    pytest.importorskip("fastapi")
    pytest.importorskip("httpx2")
    from fastapi.testclient import TestClient

    from nikodym.ui.server import create_app
    from nikodym.ui.settings import UiConfig

    client = TestClient(create_app(UiConfig()))
    respuesta = client.get("/api/config/preset")
    assert respuesta.status_code == 200
    cuerpo: dict[str, Any] = respuesta.json()
    assert cuerpo["config_hash"] == _EXPECTED_CONFIG_HASH
    assert config_hash(NikodymConfig.model_validate(cuerpo["config"])) == _EXPECTED_CONFIG_HASH
