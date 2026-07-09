"""Tests de la lógica pura de serialización de resultados (SDD-23 §6, §11).

Se ejercita ``serialize_study`` sobre un ``Study`` F1 finalizado (mismo mecanismo que
``test_api_run.py``: frame de 30 filas + ``fake_binning_process``), más ``to_records``/``dump_dto``
y las invariantes duras (finitud, no-mutación, card ausente no fabricada). No requiere FastAPI. Un
test de regresión corre además el **preset real** (OptBinning + categórica) en subproceso aislado.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
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
# Claves ricas graficables que el merge aditivo agrega dentro de cada objeto de dominio (§6).
_RICH_KEYS_BY_DOMAIN = {
    "binning": ("tables_by_variable",),
    "selection": ("decisions",),
    "model": ("coefficients",),
    "scorecard": ("points", "score_values"),
    "calibration": ("isotonic_knots", "reliability"),
    "performance": ("deciles", "discriminant"),
}
# Subconjunto que el preset estándar F1 produce con CONTENIDO no vacío (DoD B27, §6). Excluye
# ``isotonic_knots``: el preset calibra por ``intercept_offset`` → knots vacíos → expuestos None.
# ``reliability`` SÍ es no vacío: es la curva derivada del ``calibrated_pd_frame`` (B35a).
_NONEMPTY_RICH = (
    ("binning", "tables_by_variable"),
    ("selection", "decisions"),
    ("model", "coefficients"),
    ("scorecard", "points"),
    ("scorecard", "score_values"),
    ("calibration", "reliability"),
    ("performance", "deciles"),
    ("performance", "discriminant"),
)


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


def test_serialize_study_expone_artefactos_ricos(f1_study: Study) -> None:
    """El merge aditivo agrega las claves ricas graficables en cada objeto de dominio (§6)."""
    payload = serialize_study(f1_study, governance=_GOVERNANCE)

    # Toda clave rica está presente en su dominio (con contenido o None, según el preset).
    for domain, rich_keys in _RICH_KEYS_BY_DOMAIN.items():
        assert isinstance(payload[domain], dict), domain
        for rich_key in rich_keys:
            assert rich_key in payload[domain], (domain, rich_key)

    # Las que el preset estándar produce llegan con contenido no vacío.
    for domain, rich_key in _NONEMPTY_RICH:
        assert payload[domain][rich_key], (domain, rich_key)


def test_artefactos_ricos_shape(f1_study: Study) -> None:
    """Los frames ricos traen las columnas canónicas del motor (no se recalcula ni se recorta)."""
    payload = serialize_study(f1_study, governance=_GOVERNANCE)

    # binning: dict {feature: filas con columnas canónicas de OptBinning}.
    tables = payload["binning"]["tables_by_variable"]
    assert set(tables) == {"score", "segment"}
    fila = tables["score"][0]
    assert {"Bin", "WoE", "IV", "Event rate"} <= set(fila)

    # selection: una decisión por variable evaluada, con sus campos DTO.
    decision = payload["selection"]["decisions"][0]
    assert {"feature", "woe_column", "included", "reason", "iv"} <= set(decision)

    # model: coeficientes con beta y estadísticos.
    coef = payload["model"]["coefficients"][0]
    assert {"feature", "beta", "wald_z", "p_value"} <= set(coef)

    # scorecard: puntos por bin + array de score fila-nivel (histograma).
    punto = payload["scorecard"]["points"][0]
    assert {"feature", "bin_label", "points", "woe"} <= set(punto)
    score_values = payload["scorecard"]["score_values"]
    assert isinstance(score_values, list) and all(isinstance(v, (int, float)) for v in score_values)

    # performance: deciles + punto discriminante (KS/AUC/Gini).
    decil = payload["performance"]["deciles"][0]
    assert {"partition", "decile", "lift", "ks_at_decile", "cum_bad_capture_rate"} <= set(decil)
    disc = payload["performance"]["discriminant"][0]
    assert {"partition", "auc", "gini", "ks", "tpr_at_ks", "fpr_at_ks"} <= set(disc)


def test_artefactos_ricos_cards_intactas(f1_study: Study) -> None:
    """El merge es aditivo: la card de cada dominio sigue idéntica bajo las claves ricas nuevas."""
    payload = serialize_study(f1_study, governance=_GOVERNANCE)

    for domain, key in serializers._CARD_KEY_BY_DOMAIN.items():
        # ``stability`` está en el mapa canónico pero el fixture F1 no lo ejecuta: se salta el
        # dominio ausente (su card no está publicada) en vez de fabricarlo.
        if not f1_study.artifacts.has(domain, key):
            continue
        card = dump_dto(f1_study.artifacts.get(domain, key))
        # Cada clave/valor de la card original persiste sin cambios dentro del objeto de dominio.
        for card_key, card_value in card.items():
            assert payload[domain][card_key] == card_value, (domain, card_key)
        # Y lo único añadido son las claves ricas declaradas (sin colisión de nombres).
        assert set(payload[domain]) - set(card) == set(_RICH_KEYS_BY_DOMAIN[domain])


def test_isotonic_knots_none_si_no_isotonico(f1_study: Study) -> None:
    """El preset calibra por ``intercept_offset``: ``isotonic_knots`` presente pero None."""
    payload = serialize_study(f1_study, governance=_GOVERNANCE)
    assert "isotonic_knots" in payload["calibration"]
    assert payload["calibration"]["isotonic_knots"] is None


def test_reliability_en_payload_shape(f1_study: Study) -> None:
    """Con calibración corrida, ``calibration.reliability`` trae el shape §6 de la curva (B35a)."""
    payload = serialize_study(f1_study, governance=_GOVERNANCE)
    reliability = payload["calibration"]["reliability"]

    assert reliability["strategy"] == "quantile"
    assert reliability["n_bins"] == 10
    # ``by_partition`` es una LISTA; la primera partición del orden canónico es ``desarrollo``.
    assert isinstance(reliability["by_partition"], list)
    primera = reliability["by_partition"][0]
    assert primera["partition"] == "desarrollo"
    assert set(primera) == {"partition", "n", "brier", "ece", "bins"}
    assert set(primera["bins"][0]) == {
        "bin",
        "n",
        "mean_predicted_pd",
        "observed_default_rate",
        "ci_low",
        "ci_high",
        "pd_lo",
        "pd_hi",
    }
    # ``fuera_de_modelo`` (0 filas) se excluye: solo particiones modelables con n>0.
    assert {part["partition"] for part in reliability["by_partition"]} <= {
        "desarrollo",
        "holdout",
        "oot",
    }


def test_artefactos_ricos_ausentes_si_dominio_no_corrio(tmp_path: Path) -> None:
    """Study no ejecutado: ningún dominio es dict → no se fabrica ninguna clave rica."""
    parquet = tmp_path / "cartera.parquet"
    write_behavior_parquet(parquet)
    study = Study(full_f1_config(str(parquet)))  # construido, NO ejecutado

    payload = serialize_study(study, governance=_GOVERNANCE)
    for domain in _RICH_KEYS_BY_DOMAIN:
        assert payload[domain] is None, domain


def test_helpers_ricos_artefacto_ausente_devuelven_none() -> None:
    """Cada proyector rico devuelve None si su artefacto de origen falta (rama defensiva §6)."""

    class _SinArtefactos:
        def has(self, domain: str, key: str) -> bool:
            return False

    study = SimpleNamespace(artifacts=_SinArtefactos())
    assert serializers._domain_records(study, "model", "coefficients") is None  # type: ignore[arg-type]
    assert serializers._binning_tables(study) is None  # type: ignore[arg-type]
    assert serializers._selection_decisions(study) is None  # type: ignore[arg-type]
    assert serializers._score_values(study) is None  # type: ignore[arg-type]
    assert serializers._isotonic_knots(study) is None  # type: ignore[arg-type]
    assert serializers._reliability_curve(study) is None  # type: ignore[arg-type]


def test_isotonic_knots_proyecta_pares() -> None:
    """Con un método isotónico, los knots se proyectan a pares ``[x, y]`` bajo el guard."""

    class _ConKnots:
        def has(self, domain: str, key: str) -> bool:
            return True

        def get(self, domain: str, key: str) -> object:
            return SimpleNamespace(isotonic_knots=((0.0, 0.1), (1.0, 0.9)))

    study = SimpleNamespace(artifacts=_ConKnots())
    assert serializers._isotonic_knots(study) == [[0.0, 0.1], [1.0, 0.9]]  # type: ignore[arg-type]


def test_stability_augment_proyecta_frames() -> None:
    """La rama de estabilidad proyecta ``psi_table``/``stability_metrics`` a records (aditivo §6).

    ``psi_table`` mezcla PSI de score/PD y CSI por característica (columna ``metric``); ambos frames
    se proyectan con el guard de finitud reutilizando ``_domain_records`` (como los demás dominios).
    """
    psi_table = pd.DataFrame(
        {
            "metric": ["score_psi", "csi"],
            "comparison": ["dev_vs_oot", "dev_vs_oot"],
            "feature": ["score", "ingreso_mensual__points"],
            "bin_label": ["bin_00", "bin_00"],
            "expected_count": [10, 10],
            "actual_count": [9, 11],
            "expected_pct": [0.5, 0.5],
            "actual_pct": [0.45, 0.55],
            "component_value": [0.005, 0.004],
            "total_value": [0.02, 0.01],
            "band": ["stable", "stable"],
        }
    )
    stability_metrics = pd.DataFrame(
        {
            "metric": ["score_psi", "csi"],
            "comparison": ["dev_vs_oot", "dev_vs_oot"],
            "feature": ["score", "ingreso_mensual__points"],
            "value": [0.02, 0.01],
            "stable_threshold": [0.1, 0.1],
            "review_threshold": [0.25, 0.25],
            "band": ["stable", "stable"],
            "action": ["none", "none"],
        }
    )
    frames = {
        ("stability", "psi_table"): psi_table,
        ("stability", "stability_metrics"): stability_metrics,
    }

    class _ConEstabilidad:
        def has(self, domain: str, key: str) -> bool:
            return (domain, key) in frames

        def get(self, domain: str, key: str) -> object:
            return frames[(domain, key)]

    study = SimpleNamespace(artifacts=_ConEstabilidad())
    payload = {domain: None for domain in serializers._CARD_KEY_BY_DOMAIN}
    payload["stability"] = {"score_direction": "higher_is_lower_risk"}  # card ya presente (dict)
    serializers._augment_with_rich_artifacts(study, payload)  # type: ignore[arg-type]

    psi_records = payload["stability"]["psi_table"]
    assert len(psi_records) == 2
    assert psi_records[0]["metric"] == "score_psi"
    assert {"metric", "comparison", "feature", "bin_label", "expected_count", "band"} <= set(
        psi_records[0]
    )
    metric_records = payload["stability"]["stability_metrics"]
    assert len(metric_records) == 2
    assert {"metric", "comparison", "feature", "value", "band", "action"} <= set(metric_records[0])
    # aditivo: la clave de la card original persiste sin cambios.
    assert payload["stability"]["score_direction"] == "higher_is_lower_risk"


def test_stability_augment_frames_ausentes_a_none() -> None:
    """Estabilidad presente (card) pero sin frames ricos → claves proyectadas a None (defensivo)."""

    class _SinFrames:
        def has(self, domain: str, key: str) -> bool:
            return False

    study = SimpleNamespace(artifacts=_SinFrames())
    payload = {domain: None for domain in serializers._CARD_KEY_BY_DOMAIN}
    payload["stability"] = {"score_direction": "x"}
    serializers._augment_with_rich_artifacts(study, payload)  # type: ignore[arg-type]

    assert payload["stability"]["psi_table"] is None
    assert payload["stability"]["stability_metrics"] is None


def test_frame_records_ausente_a_null_pero_inf_falla() -> None:
    """``_frame_records`` mapea ``NaN`` (ausente) a ``null``, pero un ``Inf`` genuino falla."""
    ausente = pd.DataFrame({"iv": [0.5, float("nan")], "feature": ["a", "b"]})
    assert serializers._frame_records(ausente) == [
        {"iv": 0.5, "feature": "a"},
        {"iv": None, "feature": "b"},
    ]
    with pytest.raises(UiSerializationError):
        serializers._frame_records(pd.DataFrame({"x": [float("inf")]}))


def test_to_json_native_coacciona_numpy_y_ausentes() -> None:
    """``_to_json_native`` mapea numpy/ausentes a nativos; el ``Inf`` finito-inválido sobrevive."""
    # ndarray categórico (celda ``Bin`` de una tabla OptBinning) → lista de strings nativa.
    assert serializers._to_json_native(np.asarray(["independiente"], dtype=object)) == [
        "independiente"
    ]
    # escalares numpy → nativos (json-serializables).
    assert serializers._to_json_native(np.int64(7)) == 7
    assert serializers._to_json_native(np.bool_(True)) is True
    assert serializers._to_json_native(np.float64(1.5)) == 1.5
    # ausencia: NaN (nativo y numpy, subclase de float) → None; list/tuple recursivo.
    assert serializers._to_json_native(float("nan")) is None
    assert serializers._to_json_native(np.float64("nan")) is None
    assert serializers._to_json_native((np.int64(1), float("nan"))) == [1, None]
    # el Inf NO es ausente: sobrevive para que el guard de finitud lo rechace aguas abajo.
    assert serializers._to_json_native(float("inf")) == float("inf")


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


# ─────────────────────── preset real end-to-end (OptBinning + categórica) ───────────────────────

# El preset corre en un SUBPROCESO limpio: importar OptBinning (OR-Tools ``pywraplp``) dentro del
# proceso de pytest —con numpy/scipy/sklearn/pyarrow ya cargados— provoca un *segfault* nativo (por
# eso el resto de la suite usa ``fake_binning_process``). Un proceso hijo fresco importa OR-Tools
# limpio y ejercita el binning real, único camino que produce el ``ndarray`` por bin categórico.
_PRESET_E2E_SCRIPT = """\
import sys
from pathlib import Path

from nikodym.ui.presets import standard_preset
from nikodym.ui.routes import run_pipeline

workdir = Path(sys.argv[1])
preset = standard_preset()
# run_pipeline -> runs.save -> serialize_study -> json.dumps(allow_nan=False): si un ndarray/numpy
# colara sin coaccionar, esto lanzaria y el subproceso saldria con codigo != 0.
result = run_pipeline(preset["config"], preset["dataset_id"], workdir=workdir)
assert result["status"] == "done", result
print(result["run_id"])
"""


def test_preset_estandar_serializa_con_binning_categorico(tmp_path: Path) -> None:
    """El PRESET estándar (OptBinning real, sin fake) serializa completo pese a la categórica.

    ``segmento`` entra al binning como categórica y su tabla OptBinning trae celdas ``Bin`` como
    ``numpy.ndarray`` (``array(['independiente'])``); antes de B27-fix eso hacía crashear
    ``serialize_study`` → ``json.dumps`` (500 en ``/api/run``). Corre en subproceso limpio (ver nota
    arriba) el mismo camino del endpoint: ``run_pipeline`` → ``runs.save`` (serializa y vuelca
    ``results.json`` con ``json.dumps(allow_nan=False)``).
    """
    script = tmp_path / "run_preset_e2e.py"
    script.write_text(_PRESET_E2E_SCRIPT, encoding="utf-8")
    completed = subprocess.run(
        [sys.executable, str(script), str(tmp_path)],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONHASHSEED": "0"},
        check=False,
    )
    # (a) el subproceso terminó OK ⇒ la corrida serializó y volcó results.json sin crashear.
    assert completed.returncode == 0, completed.stderr
    run_id = completed.stdout.strip().splitlines()[-1]

    # (b) el payload persistido es JSON estricto completo (sin ndarray/numpy colado).
    results_path = tmp_path / "runs" / run_id / "results.json"
    assert results_path.is_file()
    payload = json.loads(results_path.read_text(encoding="utf-8"))

    # (c) la variable de binning CATEGÓRICA está presente con sus celdas ``Bin`` como lista de str.
    tables = payload["binning"]["tables_by_variable"]
    assert "segmento" in tables
    listas = [fila["Bin"] for fila in tables["segmento"] if isinstance(fila["Bin"], list)]
    assert listas, tables["segmento"]  # ≥1 bin categórico quedó como lista de categorías
    assert all(isinstance(cat, str) for lista in listas for cat in lista)


# ─────────────────────────────── mapa canónico ───────────────────────────────


def test_mapa_de_cards_coincide_con_report_builder() -> None:
    """El mapa local dominio→clave de card no deriva del canónico ``_CARD_ARTIFACTS``."""
    from nikodym.report.builder import _CARD_ARTIFACTS

    canonico = dict(_CARD_ARTIFACTS)
    for domain, key in serializers._CARD_KEY_BY_DOMAIN.items():
        assert canonico[domain] == key, domain
