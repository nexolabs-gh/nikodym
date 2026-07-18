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
from typing import Literal

import numpy as np
import pandas as pd
import pytest
from _ui_f1 import failing_config, full_f1_config, write_behavior_parquet
from pydantic import BaseModel, ConfigDict

import nikodym
from nikodym.core.config import NikodymConfig
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


# ─────────────────────────── provisiones (preset F3 real) ───────────────────────────


def test_serializa_las_cards_de_provisiones_del_preset_f3(tmp_path: Path) -> None:
    """El preset F3 real serializa las 3 cards de provisiones + frames AGREGADOS, sin ``detail``.

    Corre la cadena entera (no fabrica el estado: las cards las produce el motor) y verifica que
    ``serialize_study`` expone las tres cards con sus montos como NÚMERO, los frames agregados
    graficables (summary por categoría, groups por banda, comparison), y que **ningún** frame por
    operación (``detail``, 6.000 filas) entra al payload. Requiere el extra ``scoring``
    (OptBinning); el job mínimo lo salta.
    """
    pytest.importorskip("optbinning")
    from nikodym.ui import datasets
    from nikodym.ui.presets import PROVISIONES_DATASET_ID, provisiones_preset

    source = datasets.materialize(PROVISIONES_DATASET_ID, workdir=tmp_path)
    config = provisiones_preset()["config"]
    config["data"]["load"]["source"] = str(source)
    config["report"]["output_dir"] = str(tmp_path / "reports")
    study = nikodym.run(NikodymConfig.model_validate(config))
    assert study.run_context.status == "done"

    payload = serialize_study(study, governance=None)
    # El payload entero es JSON estricto (el guard es global: un Decimal colado tumbaría todo).
    json.dumps(payload, allow_nan=False)

    cmf, interno, orq = (
        payload["provisioning_cmf"],
        payload["provisioning_internal"],
        payload["provisioning"],
    )
    # (a) Las tres cards presentes con sus totales como número (float/int), no string ni Decimal.
    for total in (
        cmf["total_provision_amount"],
        interno["total_internal_provision"],
        orq["total_reported_provision"],
    ):
        assert isinstance(total, (int, float))
    # (b) La regla del máximo, visible en el payload: el estándar manda sobre el interno.
    assert cmf["total_provision_amount"] > interno["total_internal_provision"]
    assert orq["binding"] == "cmf"
    assert orq["total_reported_provision"] == cmf["total_provision_amount"]
    # (c) Frames agregados graficables, no vacíos.
    assert len(cmf["summary"]) >= 1
    assert len(interno["groups"]) >= 1
    assert len(orq["comparison"]) >= 1
    # (d) Ningún frame por operación: ``detail`` (6.000 filas) jamás entra al payload.
    assert "detail" not in cmf
    assert "detail" not in interno


# ─────────────────────────────── IFRS 9 / ECL (preset F4 real) ───────────────────────────────


@pytest.mark.parametrize("term_source", ["forward", "markov"])
def test_serializa_ifrs9_fuente_no_survival_sin_fabricar_evidencia(
    term_source: Literal["forward", "markov"],
) -> None:
    """Forward/Markov llegan a la UI sin exigir ni citar una card survival."""
    from nikodym.provisioning.ifrs9.config import (
        IfrsPdConfig,
        IfrsProvisioningConfig,
        IfrsScenarioConfig,
    )

    class _NonSurvivalIfrsCard(BaseModel):
        term_structure_source: str
        pit_mode: str = "ttc_only"
        scenarios: tuple[str, ...] = ("base",)
        scenario_weights: dict[str, float] = {"base": 1.0}
        falta_dato: tuple[str, ...] = ()

    config = NikodymConfig(
        provisioning_ifrs9=IfrsProvisioningConfig(
            pd=IfrsPdConfig(term_structure_source=term_source, pit_mode="ttc_only"),
            scenarios=IfrsScenarioConfig(source="single"),
        )
    )
    study = Study(config)
    study.artifacts.set(
        "provisioning_ifrs9",
        "card",
        _NonSurvivalIfrsCard(term_structure_source=term_source),
    )

    payload = serialize_study(study, governance=None)

    assert payload["survival"] is None
    methodology = payload["provisioning_ifrs9"]["methodology"]
    assert isinstance(methodology, dict)
    active = {fact["id"]: fact for fact in methodology["active"]}
    assert "lifetime_pd" not in active
    assert active["pd_basis"]["detail"] == (f"La term-structure activa proviene de {term_source}.")
    assert methodology["source_refs"] == [
        "config.provisioning_ifrs9",
        "provisioning_ifrs9.card",
    ]
    assert all("survival" not in ref for ref in methodology["source_refs"])

    inactive = {fact["id"]: fact for fact in methodology["not_exercised"]}
    if term_source == "forward":
        assert "forward" not in inactive
        assert inactive["markov"]["detail"] == (
            "La term-structure activa proviene de forward, no de Markov."
        )
    else:
        assert "markov" not in inactive


def test_serializa_el_bloque_ifrs9_del_preset_f4(tmp_path: Path) -> None:
    """El preset F4 serializa el bloque provisioning_ifrs9: card + frames AGREGADOS, sin ``detail``.

    Corre la cadena entera (no fabrica el estado: el staging y la ECL los produce el motor IFRS 9) y
    verifica que ``serialize_study`` expone la card CT-2 más los frames agregados graficables
    —distribución de staging por Stage 1/2/3, resumen por cartera·stage, curva de ECL por período y
    conteo de gatillos SICR— con un staging repartido REAL (Stage 2 y 3 no vacíos) y sin el
    ``detail`` por operación (6.000 filas). La cadena F4 es standalone (sin binning/OptBinning):
    requiere el extra ``scoring`` por statsmodels (discrete-time hazard); el mínimo lo salta.
    """
    pytest.importorskip("statsmodels")
    from nikodym.ui import datasets
    from nikodym.ui.presets import IFRS9_DATASET_ID, ifrs9_preset

    source = datasets.materialize(IFRS9_DATASET_ID, workdir=tmp_path)
    config = ifrs9_preset()["config"]
    config["data"]["load"]["source"] = str(source)
    study = nikodym.run(NikodymConfig.model_validate(config))
    assert study.run_context.status == "done"

    payload = serialize_study(study, governance=None)
    # El payload entero es JSON estricto (el guard es global).
    json.dumps(payload, allow_nan=False)

    block = payload["provisioning_ifrs9"]
    assert isinstance(block, dict)

    # La card de survival queda citable y alimenta la ficha; los eventos nunca se hardcodean en UI.
    survival = payload["survival"]
    assert isinstance(survival, dict)
    assert survival["method"] == "discrete_hazard"
    assert survival["n_rows"] == 6_000
    assert survival["n_events"] == 1_502

    # (a) Card CT-2: los conteos por stage cuadran y hay ECL/EAD positivos con cobertura creíble.
    n_rows = block["n_rows"]
    assert block["n_stage1"] + block["n_stage2"] + block["n_stage3"] == n_rows
    assert block["n_stage2"] > 0 and block["n_stage3"] > 0  # staging repartido real
    assert block["n_stage1"] > block["n_stage2"] > block["n_stage3"]  # patrón realista
    assert isinstance(block["total_ead"], (int, float)) and block["total_ead"] > 0
    assert isinstance(block["total_ecl_reported"], (int, float)) and block["total_ecl_reported"] > 0
    coverage = block["total_ecl_reported"] / block["total_ead"]
    assert 0.01 <= coverage <= 0.15  # rango creíble de retail (el ⚑ checkpoint del número)
    # Freeze IBK-01: cifras insignia F4, verificadas sobre la corrida REAL.
    assert block["n_rows"] == 6_000
    assert (block["n_stage1"], block["n_stage2"], block["n_stage3"]) == (5_235, 477, 288)
    assert round(block["total_ead"]) == 114_325_315
    assert round(block["total_ecl_reported"]) == 3_423_116
    assert f"{coverage:.2%}" == "2.99%"

    methodology = block["methodology"]
    assert isinstance(methodology, dict)
    active = {fact["id"]: fact for fact in methodology["active"]}
    assert active["lifetime_pd"]["detail"] == ("6.000 filas · 1.502 eventos · horizonte 5 años")
    assert active["pd_basis"]["value"] == "TTC (through-the-cycle)"
    assert active["loss_inputs"]["value"] == "LGD provided · EAD provided"
    assert active["staging"]["value"] == "30/90 días + is_default"
    assert active["scenario"]["value"] == "Base 100 %"
    assert active["discount"]["value"] == "EIR anual"
    assert {fact["id"] for fact in methodology["not_exercised"]} == {
        "forward",
        "macro_scenarios",
        "markov",
    }

    # (b) Distribución de staging por Stage 1/2/3: 3 filas que RECONCILIAN con la card.
    dist = block["staging_distribution"]
    assert [row["stage"] for row in dist] == [1, 2, 3]
    assert sum(row["n_rows"] for row in dist) == n_rows
    assert sum(row["total_ecl_reported"] for row in dist) == pytest.approx(
        block["total_ecl_reported"], rel=1e-9
    )
    coverages = [row["coverage_ratio"] for row in dist]
    assert coverages[0] < coverages[1] < coverages[2]  # cobertura crece con la severidad del stage

    # (c) Resumen por cartera·stage (agregado del motor), no vacío, con las columnas canónicas.
    summary = block["summary"]
    assert len(summary) >= 1
    assert {
        "portfolio",
        "stage",
        "n_rows",
        "total_ead",
        "total_ecl_reported",
        "coverage_ratio",
    } <= set(summary[0])

    # (d) Curva de ECL por período: acumulada no decreciente y factor de descuento en (0, 1].
    curve = block["ecl_term_structure"]
    assert len(curve) >= 1
    assert {
        "period",
        "time_value",
        "ecl_marginal",
        "ecl_cumulative",
        "pd_marginal_weighted",
        "discount_factor_mean",
    } <= set(curve[0])
    cumulative = [row["ecl_cumulative"] for row in curve]
    assert cumulative == sorted(cumulative)  # acumulada monótona no decreciente
    for row in curve:
        assert 0.0 < row["discount_factor_mean"] <= 1.0
        assert 0.0 <= row["pd_marginal_weighted"] <= 1.0

    # (e) Gatillos SICR: las presunciones DPD bajo la política v1 disparan; conteos positivos.
    triggers = block["sicr_triggers"]
    assert isinstance(triggers, dict) and triggers
    assert "dpd_default_backstop" in triggers  # 90+ días de mora → Stage 3
    assert all(isinstance(value, int) and value > 0 for value in triggers.values())

    # (f) Muestra por operación (top-N por ECL) con las tres etapas y sus campos por fila.
    detail_sample = block["detail_sample"]
    assert {row["stage"] for row in detail_sample} == {1, 2, 3}  # no solo Stage 3
    assert {
        "loan_id",
        "portfolio",
        "stage",
        "ead",
        "lgd",
        "eir",
        "pd_12m",
        "pd_life",
        "ecl_12m",
        "ecl_lifetime",
        "ecl_reported",
        "sicr_triggers",
    } <= set(detail_sample[0])
    # Ordenada por ``ecl_reported`` descendente; los gatillos SICR son una lista por operación.
    ecls = [row["ecl_reported"] for row in detail_sample]
    assert ecls == sorted(ecls, reverse=True)
    assert all(isinstance(row["sicr_triggers"], list) for row in detail_sample)
    # Coherencia stage↔gatillos: Stage 1 sin gatillos; Stage 3 con default (dpd 90 o is_default).
    for row in detail_sample:
        if row["stage"] == 1:
            assert row["sicr_triggers"] == []
        if row["stage"] == 3:
            assert {"dpd_default_backstop", "is_default"} & set(row["sicr_triggers"])

    # (g) El ``detail`` COMPLETO por operación (6.000 filas) nunca entra al payload.
    assert "detail" not in block
    assert "staging" not in block


# ─────────────────────────────── mapa canónico ───────────────────────────────


def test_mapa_de_cards_coincide_con_report_builder() -> None:
    """El mapa local dominio→clave de card no deriva del canónico ``_CARD_ARTIFACTS``."""
    from nikodym.report.builder import _CARD_ARTIFACTS

    canonico = dict(_CARD_ARTIFACTS)
    for domain, key in serializers._CARD_KEY_BY_DOMAIN.items():
        assert canonico[domain] == key, domain


def test_decimal_de_provisiones_se_serializa_como_numero() -> None:
    """Los ``Decimal`` de las cards de provisiones salen como NÚMERO, no como string ni excepción.

    Sin la coacción, ``_ensure_json_safe`` levanta ``UiSerializationError`` y se cae **todo** el
    payload de ``/api/results`` —no solo la sección de provisiones—, porque el guard es global.
    Y si se dejaran como *string* (que es lo que Pydantic hace por defecto con ``Decimal``), el
    front recibiría ``"123.45"`` donde ``results-format`` espera un número.
    """
    from decimal import Decimal

    from pydantic import BaseModel

    from nikodym.ui.serializers import _to_json_native, dump_dto

    class _CardConDecimal(BaseModel):
        total_reported_provision: Decimal
        detalle: dict[str, Decimal]
        etiqueta: str

    card = _CardConDecimal(
        total_reported_provision=Decimal("851018945.42"),
        detalle={"cmf": Decimal("697000000.00")},
        etiqueta="consumer",
    )
    volcado = dump_dto(card)

    assert volcado["total_reported_provision"] == pytest.approx(851018945.42)
    assert isinstance(volcado["total_reported_provision"], float)
    assert isinstance(volcado["detalle"]["cmf"], float)
    assert volcado["etiqueta"] == "consumer"
    # y la celda suelta de un DataFrame (el camino de `_frame_records`) también:
    assert _to_json_native(Decimal("12.34")) == pytest.approx(12.34)
