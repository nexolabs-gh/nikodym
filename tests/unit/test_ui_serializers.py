"""Tests de la lógica pura de serialización de resultados (SDD-23 §6, §11).

Se ejercita ``serialize_study`` sobre un ``Study`` F1 finalizado (mismo mecanismo que
``test_api_run.py``: frame de 30 filas + ``fake_binning_process``), más ``to_records``/``dump_dto``
y las invariantes duras (finitud, no-mutación, card ausente no fabricada). No requiere FastAPI.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
from _ui_f1 import failing_config, full_f1_config, write_behavior_parquet
from pydantic import BaseModel, ConfigDict

import nikodym
from nikodym.core.study import Study
from nikodym.governance import GovernanceConfig
from nikodym.ui import serializers
from nikodym.ui.exceptions import UiSerializationError
from nikodym.ui.serializers import dump_dto, serialize_study, to_records

_GOVERNANCE = GovernanceConfig(purpose="serialización read-only F1", model_name="ui-serializer")
# Claves de golden por card: shape esperado del §6 (subconjunto probatorio, no exhaustivo).
_CARD_GOLDEN_KEYS = {
    "binning": "iv_by_variable",
    "selection": "selected_features",
    "model": "final_features",
    "scorecard": "pdo",
    "calibration": "method",
    "performance": "partitions",
}


@pytest.fixture
def f1_study(fake_binning_process: object, tmp_path: Path) -> Study:
    """``Study`` F1 finalizado (``status="done"``) con las 6 cards de dominio."""
    del fake_binning_process
    parquet = tmp_path / "cartera.parquet"
    write_behavior_parquet(parquet)
    return nikodym.run(full_f1_config(str(parquet)))


# ─────────────────────────────── serialize_study ───────────────────────────────


def test_serialize_study_done_shape_y_cards(f1_study: Study) -> None:
    """Una corrida F1 finalizada serializa status/run_id, model_card y las 6 cards al shape §6."""
    payload = serialize_study(f1_study, governance=_GOVERNANCE)

    assert payload["status"] == "done"
    assert payload["run_id"] == f1_study.run_context.run_id
    assert payload["error"] is None
    # model_card consolidado, con su lineage citable (no recalculado).
    assert isinstance(payload["model_card"], dict)
    assert payload["model_card"]["config_hash"] == f1_study.lineage_bundle().config_hash
    # cada card de dominio se serializó a su shape esperado (DTO → model_dump(mode="json")).
    for domain, golden_key in _CARD_GOLDEN_KEYS.items():
        assert isinstance(payload[domain], dict), domain
        assert golden_key in payload[domain], (domain, golden_key)


def test_serialize_study_es_json_estricto(f1_study: Study) -> None:
    """El payload es JSON estricto (sin NaN/Inf ni objetos opacos)."""
    import json

    dumped = json.dumps(serialize_study(f1_study, governance=_GOVERNANCE), allow_nan=False)
    assert isinstance(dumped, str)


def test_serialize_study_sin_governance_card_nula(f1_study: Study) -> None:
    """Sin gobernanza no se fabrica ModelCard, pero las cards de dominio siguen presentes."""
    payload = serialize_study(f1_study, governance=None)
    assert payload["model_card"] is None
    assert isinstance(payload["binning"], dict)


def test_serialize_study_governance_blob_se_coacciona(f1_study: Study) -> None:
    """Una gobernanza como dict opaco se coacciona a GovernanceConfig y produce el card."""
    payload = serialize_study(f1_study, governance={"purpose": "blob coaccionado"})  # type: ignore[arg-type]
    assert isinstance(payload["model_card"], dict)
    assert payload["model_card"]["purpose"] == "blob coaccionado"


def test_serialize_study_no_muta_artifacts(f1_study: Study) -> None:
    """Serializar no altera ``study.artifacts`` (lee copias/DTOs frozen; no-mutación §6)."""
    claves_antes = set(f1_study.artifacts.keys())
    card_antes = f1_study.artifacts.get("model", "model_card")
    dump_antes = card_antes.model_dump(mode="json")

    serialize_study(f1_study, governance=_GOVERNANCE)

    assert set(f1_study.artifacts.keys()) == claves_antes
    assert f1_study.artifacts.get("model", "model_card") is card_antes  # misma instancia
    assert card_antes.model_dump(mode="json") == dump_antes  # intacta


def test_serialize_study_parcial_sin_card_ni_artefactos(tmp_path: Path) -> None:
    """Un Study no ejecutado (status='created') → model_card null y cada card ausente → null."""
    parquet = tmp_path / "cartera.parquet"
    write_behavior_parquet(parquet)
    study = Study(full_f1_config(str(parquet)))  # construido, NO ejecutado

    payload = serialize_study(study, governance=_GOVERNANCE)

    assert payload["status"] == "created"
    assert payload["error"] is None
    assert payload["model_card"] is None  # build sobre Study no finalizado → card ausente
    assert all(payload[domain] is None for domain in _CARD_GOLDEN_KEYS)


def test_serialize_study_fallida_reporta_error(
    fake_binning_process: object, tmp_path: Path
) -> None:
    """Una corrida fallida serializa ``status="failed"`` con un mensaje de error honesto."""
    del fake_binning_process
    parquet = tmp_path / "cartera.parquet"
    write_behavior_parquet(parquet)
    study = nikodym.run(failing_config(str(parquet)))

    payload = serialize_study(study, governance=None)

    assert payload["status"] == "failed"
    assert isinstance(payload["error"], str) and payload["error"]


# ─────────────────────────────── to_records / dump_dto ───────────────────────────────


def test_to_records_proyecta_dataframe() -> None:
    """``to_records`` equivale a ``DataFrame.to_dict("records")`` con claves ``str``."""
    frame = pd.DataFrame({"a": [1, 2], "b": [1.5, 2.5]}, index=["x", "y"])
    assert to_records(frame) == [{"a": 1, "b": 1.5}, {"a": 2, "b": 2.5}]


def test_to_records_no_finito_falla_ruidoso() -> None:
    """Un no-finito colado en un frame levanta ``UiSerializationError`` (guard defensivo)."""
    frame = pd.DataFrame({"a": [1.0, float("nan")]})
    with pytest.raises(UiSerializationError):
        to_records(frame)


class _MiniDTO(BaseModel):
    model_config = ConfigDict(frozen=True)

    a: int
    b: str


class _InfDTO(BaseModel):
    model_config = ConfigDict(frozen=True)

    x: float


def test_dump_dto_serializa_modelo_frozen() -> None:
    """``dump_dto`` equivale a ``model_dump(mode="json")`` sobre un DTO frozen."""
    assert dump_dto(_MiniDTO(a=1, b="x")) == {"a": 1, "b": "x"}


def test_dump_dto_no_finito_falla_ruidoso() -> None:
    """Un DTO cuyo dump retiene un no-finito levanta ``UiSerializationError``."""
    with pytest.raises(UiSerializationError):
        dump_dto(_InfDTO(x=float("inf")))


# ─────────────────────────────── mapa canónico ───────────────────────────────


def test_mapa_de_cards_coincide_con_report_builder() -> None:
    """El mapa local dominio→clave de card no deriva del canónico ``_CARD_ARTIFACTS``."""
    from nikodym.report.builder import _CARD_ARTIFACTS

    canonico = dict(_CARD_ARTIFACTS)
    for domain, key in serializers._CARD_KEY_BY_DOMAIN.items():
        assert canonico[domain] == key, domain
