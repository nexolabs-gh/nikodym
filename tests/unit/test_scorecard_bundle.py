"""Contrato W1 del bundle seguro, apply targetless y batch particionado."""

from __future__ import annotations

import json
import math
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest
from _ui_f1 import full_f1_config, write_behavior_parquet

import nikodym.scorecard.bundle as bundle_module
from nikodym.api import run
from nikodym.data.config import MissingConfig, SpecialValueSpec
from nikodym.scorecard.bundle import FittedScorecardBundle, fit_scorecard_bundle
from nikodym.scorecard.exceptions import ScorecardBundleError


@pytest.fixture(autouse=True)
def _usar_fake_binning_process(fake_binning_process: object) -> None:
    """Evita OR-Tools: el doble conserva tablas/splits suficientes para congelar reglas."""
    del fake_binning_process


def _study_y_frame(tmp_path: Path) -> tuple[object, pd.DataFrame]:
    source = tmp_path / "development.parquet"
    write_behavior_parquet(source)
    frame = pd.read_parquet(source)
    config = full_f1_config(str(source))
    assert config.data is not None
    data = config.data.model_copy(
        update={
            "missing": MissingConfig(
                special_values=(
                    SpecialValueSpec(columns=("score",), sentinels=(-99999.0,), label="sin_score"),
                )
            )
        }
    )
    study = run(config.model_copy(update={"data": data}))
    assert study.run_context.status == "done"
    return study, frame


def _bundle_con_llave(
    bundle: FittedScorecardBundle, *, key: str, dtype: str
) -> FittedScorecardBundle:
    manifest = bundle.manifest
    manifest["row_identity"]["unique_keys"] = [key]
    manifest["row_identity"]["unique_key_dtypes"] = {key: dtype}
    manifest["bundle_hash"] = bundle_module._bundle_hash(manifest)
    return FittedScorecardBundle(manifest=manifest, rules=bundle._rules)


def _reescribir_manifest(
    path: Path, mutation: Callable[[dict[str, Any]], None], *, canonical: bool = True
) -> None:
    manifest_path = path / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    mutation(manifest)
    manifest["bundle_hash"] = bundle_module._bundle_hash(manifest)
    text = (
        bundle_module._canonical_json(manifest)
        if canonical
        else json.dumps(manifest, ensure_ascii=False, indent=2)
    )
    manifest_path.write_bytes((text + "\n").encode("utf-8"))


def test_fit_save_load_apply_equivale_y_no_refitea(tmp_path: Path) -> None:
    """Load seguro reproduce score/PD exactos sin conservar objetos fiteables."""
    study, frame = _study_y_frame(tmp_path)
    bundle = FittedScorecardBundle.from_study(study)  # type: ignore[arg-type]
    path = bundle.save(tmp_path / "bundle")
    manifest_bytes = (path / "manifest.json").read_bytes()
    assert manifest_bytes.endswith(b"\n")
    assert b"\r\n" not in manifest_bytes
    loaded = FittedScorecardBundle.load(path)

    targetless = frame.drop(columns=["bad_flag", "cohort"])
    result = loaded.apply(targetless)
    original_score = study.artifacts.get("scorecard", "score")["score"]  # type: ignore[union-attr]
    original_pd = study.artifacts.get("calibration", "calibrated_pd_frame")[  # type: ignore[union-attr]
        "pd_calibrated"
    ]

    assert loaded.bundle_hash == bundle.bundle_hash
    assert result.summary == {"input_rows": 30, "scored_rows": 30, "not_scorable_rows": 0}
    pd.testing.assert_series_equal(
        result.application_frame["score"].astype("float64"),
        original_score.loc[targetless.index].astype("float64"),
        check_names=False,
    )
    pd.testing.assert_series_equal(
        result.application_frame["pd_calibrated"].astype("float64"),
        original_pd.loc[targetless.index].astype("float64"),
        check_names=False,
        rtol=1e-12,
        atol=1e-12,
    )


def test_apply_no_llama_fit_ignora_target_y_resuelve_por_nombre(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Spy anti-refit: el target y el orden no gobiernan ninguna salida numérica."""
    study, frame = _study_y_frame(tmp_path)
    bundle = FittedScorecardBundle.from_study(study)  # type: ignore[arg-type]

    def explode(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise AssertionError("apply intentó ajustar estado")

    from nikodym.binning.transformer import WoEBinner
    from nikodym.calibration.calibrator import PDCalibrator
    from nikodym.scorecard.scaler import PointsScaler

    monkeypatch.setattr(WoEBinner, "fit", explode)
    monkeypatch.setattr(PDCalibrator, "fit", explode)
    monkeypatch.setattr(PointsScaler, "fit", explode)

    base = frame.drop(columns=["bad_flag", "cohort"])
    adversarial = frame.copy(deep=True)
    adversarial["bad_flag"] = 1 - adversarial["bad_flag"]
    adversarial = adversarial.loc[:, list(reversed(adversarial.columns))]
    expected = bundle.apply(base).application_frame
    observed = bundle.apply(adversarial).application_frame
    pd.testing.assert_frame_equal(
        observed.loc[:, ["linear_predictor", "pd_raw", "score", "pd_calibrated"]],
        expected.loc[:, ["linear_predictor", "pd_raw", "score", "pd_calibrated"]],
    )

    with pytest.raises(ScorecardBundleError, match="predictores requeridos"):
        bundle.apply(base.drop(columns=["score"]))


def test_fit_publico_usa_el_frame_y_no_la_fuente_del_config(tmp_path: Path) -> None:
    """El argumento ``frame`` es la única fuente del fit por API Python."""
    source = tmp_path / "development.parquet"
    write_behavior_parquet(source)
    frame = pd.read_parquet(source)
    config = full_f1_config(str(tmp_path / "fuente-que-no-existe.parquet"))

    bundle = fit_scorecard_bundle(config, frame)
    assert bundle.apply(frame.drop(columns=["bad_flag", "cohort"])).summary["scored_rows"] == 30


def test_fit_publico_coacciona_igual_una_seccion_opaca(tmp_path: Path) -> None:
    """La API pública no depende del orden de imports que tipó la sección data/binning."""
    source = tmp_path / "development.parquet"
    write_behavior_parquet(source)
    frame = pd.read_parquet(source)
    typed = full_f1_config(str(source))
    opaque = typed.model_copy(
        update={
            "data": typed.data.model_dump(mode="python"),  # type: ignore[union-attr]
            "binning": typed.binning.model_dump(mode="python"),  # type: ignore[union-attr]
        }
    )

    expected = fit_scorecard_bundle(typed, frame)
    observed = fit_scorecard_bundle(opaque, frame)
    assert observed.bundle_hash == expected.bundle_hash


def test_fit_publico_resuelve_wildcard_y_rechaza_envelope_antes_de_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S3 usa el wiring público: ``*`` no puede evadir el techo de variables."""
    source = tmp_path / "development.parquet"
    write_behavior_parquet(source)
    frame = pd.read_parquet(source)
    config = full_f1_config(str(source))
    assert config.binning is not None
    wildcard = config.model_copy(
        update={"binning": config.binning.model_copy(update={"feature_columns": "*"})}
    )
    monkeypatch.setattr(bundle_module, "_MAX_TRAIN_VARIABLES", 1)

    def no_debe_ejecutarse(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise AssertionError("se creó el motor antes de validar el envelope")

    monkeypatch.setattr("nikodym.api.run", no_debe_ejecutarse)
    with pytest.raises(ScorecardBundleError, match="variables=2"):
        fit_scorecard_bundle(wildcard, frame)


def test_special_solo_en_apply_conserva_fila_y_falla_cerrado(tmp_path: Path) -> None:
    """CR-02 negativo: -99999 sin soporte no recibe WoE neutral ni desaparece."""
    study, frame = _study_y_frame(tmp_path)
    bundle = FittedScorecardBundle.from_study(study)  # type: ignore[arg-type]
    targetless = frame.drop(columns=["bad_flag", "cohort"]).iloc[:2].copy()
    targetless.iloc[1, targetless.columns.get_loc("score")] = -99999

    result = bundle.apply(targetless)
    failed = result.application_frame.iloc[1]

    assert result.application_frame.index.equals(targetless.index)
    assert failed["scoring_status"] == "not_scorable"
    assert failed["not_scorable_reason"] == "score:special_sin_soporte_en_fit"
    assert failed[["linear_predictor", "pd_raw", "score", "pd_calibrated"]].isna().all()
    assert result.woe_frame.iloc[1].filter(like="__woe").isna().all()


def test_special_as_missing_conserva_estado_y_usa_solo_bin_entrenado(tmp_path: Path) -> None:
    """El catálogo se reconoce antes del missing y H2=A sólo permite soporte observado."""
    source = tmp_path / "development.parquet"
    write_behavior_parquet(source)
    frame = pd.read_parquet(source)
    frame.loc[frame.index[:2], "score"] = -99999
    frame.to_parquet(source)
    config = full_f1_config(str(source))
    assert config.data is not None and config.binning is not None
    data = config.data.model_copy(
        update={
            "missing": MissingConfig(
                special_values=(
                    SpecialValueSpec(columns=("score",), sentinels=(-99999.0,), label="sin_score"),
                )
            )
        }
    )
    binning = config.binning.model_copy(update={"special_handling": "as_missing"})
    study = run(config.model_copy(update={"data": data, "binning": binning}))
    assert study.run_context.status == "done"
    bundle = FittedScorecardBundle.from_study(study)

    targetless = frame.drop(columns=["bad_flag", "cohort"]).iloc[:2]
    result = bundle.apply(targetless)
    special_trace = result.trace_frame.loc[result.trace_frame["feature"].eq("score")]

    assert result.application_frame["scoring_status"].tolist() == ["scored", "scored"]
    assert special_trace["raw_state"].tolist() == ["special", "special"]
    assert special_trace["warning_code"].tolist() == [
        "special_mapeado_a_missing_entrenado",
        "special_mapeado_a_missing_entrenado",
    ]
    assert special_trace["bin_id"].str.contains("score:").all()


def test_salida_y_traza_reconcilian_con_golden_manual(tmp_path: Path) -> None:
    """Golden independiente: reconstruye eta, PD y puntos desde JSON+Parquet públicos."""
    study, frame = _study_y_frame(tmp_path)
    bundle_path = FittedScorecardBundle.from_study(study).save(tmp_path / "bundle")  # type: ignore[arg-type]
    loaded = FittedScorecardBundle.load(bundle_path)
    result = loaded.apply(frame.drop(columns=["bad_flag", "cohort"]).iloc[:1])
    manifest = json.loads((bundle_path / "manifest.json").read_text(encoding="utf-8"))
    rules = pd.read_parquet(bundle_path / "bins.parquet").set_index("bin_id")
    trace = result.trace_frame
    model = manifest["model"]
    eta = float(model["intercept"])
    score_unrounded = 0.0
    score = 0.0
    for row in trace.itertuples(index=False):
        rule = rules.loc[row.bin_id]
        eta += float(model["beta"][row.feature]) * float(rule["woe"])
        score_unrounded += float(rule["raw_points"])
        score += float(rule["points"])
    if model["min_score"] is not None:
        score = max(float(model["min_score"]), score)
    if model["max_score"] is not None:
        score = min(float(model["max_score"]), score)
    pd_raw = 1.0 / (1.0 + math.exp(-eta))
    calibration = model["calibration"]
    assert calibration["method"] == "intercept_offset"
    offset = 0.0 if calibration["offset"] is None else float(calibration["offset"])
    pd_calibrated = 1.0 / (1.0 + math.exp(-(eta + offset)))
    observed = result.application_frame.iloc[0]

    assert float(observed["eta"]) == pytest.approx(eta, abs=1e-12)
    assert float(observed["pd_raw"]) == pytest.approx(pd_raw, abs=1e-12)
    assert float(observed["score_unrounded"]) == pytest.approx(score_unrounded, abs=1e-12)
    assert float(observed["score"]) == pytest.approx(score, abs=1e-12)
    assert float(observed["pd_calibrated"]) == pytest.approx(pd_calibrated, abs=1e-12)
    assert len(observed["treatment_trace_hash"]) == 64
    assert {
        "raw_value",
        "raw_state",
        "rule",
        "transformed_value",
        "raw_points",
        "points",
        "warning_code",
    } <= set(trace.columns)


def test_lineage_apply_mide_runtime_actual_separado_del_fit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    study, frame = _study_y_frame(tmp_path)
    bundle = FittedScorecardBundle.from_study(study)  # type: ignore[arg-type]
    monkeypatch.setattr("nikodym.scorecard.bundle.runtime_environment_hash", lambda: "a" * 64)
    result = bundle.apply(frame.drop(columns=["bad_flag", "cohort"]).iloc[:1])
    assert result.lineage["runtime_environment_hash"] == "a" * 64
    assert (
        result.lineage["fit_runtime_environment_hash"]
        == bundle.manifest["fit_lineage"]["runtime_environment_hash"]
    )
    assert result.lineage["runtime_matches_fit"] is False
    assert result.lineage["config_hash"] == bundle.manifest["fit_lineage"]["config_hash"]
    assert result.lineage["candidate_distribution_hash"] != "external_evidence_required"
    assert result.lineage["features"] == bundle.manifest["model"]["features"]
    assert result.lineage["treatment_policy"] == bundle.manifest["treatment_policy"]


def test_llaves_unicas_forman_identidad_y_fallan_con_null_o_dtype(
    tmp_path: Path,
) -> None:
    study, frame = _study_y_frame(tmp_path)
    base = FittedScorecardBundle.from_study(study)  # type: ignore[arg-type]
    bundle = _bundle_con_llave(base, key="client_key", dtype="str")
    targetless = frame.drop(columns=["bad_flag", "cohort"]).iloc[:3].copy()
    targetless["client_key"] = pd.Series(
        ["001", "002", "003"], index=targetless.index, dtype="string"
    )

    expected = bundle.apply(targetless).application_frame["input_row_hash"]
    changed = targetless.copy()
    changed.loc[changed.index[0], "client_key"] = "999"
    observed = bundle.apply(changed).application_frame["input_row_hash"]
    assert observed.iloc[0] != expected.iloc[0]

    with_null = targetless.copy()
    with_null.loc[with_null.index[0], "client_key"] = pd.NA
    with pytest.raises(ScorecardBundleError, match="llaves de identidad nulas"):
        bundle.apply(with_null)

    wrong_dtype = targetless.copy()
    wrong_dtype["client_key"] = pd.Series([1, 2, 3], index=targetless.index, dtype="Int64")
    with pytest.raises(ScorecardBundleError, match="Dtype incompatible en llave"):
        bundle.apply(wrong_dtype)


def test_hash_de_traza_detecta_permutacion_fisica(tmp_path: Path) -> None:
    """El digest de una fila no es conmutativo respecto del orden de sus features."""
    study, frame = _study_y_frame(tmp_path)
    bundle = FittedScorecardBundle.from_study(study)  # type: ignore[arg-type]
    result = bundle.apply(frame.drop(columns=["bad_flag", "cohort"]).iloc[:1])
    trace = result.trace_frame.copy(deep=True)
    expected = bundle_module._trace_hashes(trace, rows=1)[0]
    trace.iloc[[0, 1]] = trace.iloc[[1, 0]].to_numpy()
    observed = bundle_module._trace_hashes(trace, rows=1)[0]
    assert observed != expected


def test_bundle_corrupto_falla_antes_de_aplicar(tmp_path: Path) -> None:
    """Un byte alterado en la tabla pública invalida su SHA físico."""
    study, _frame = _study_y_frame(tmp_path)
    path = FittedScorecardBundle.from_study(study).save(tmp_path / "bundle")  # type: ignore[arg-type]
    rules = path / "bins.parquet"
    rules.write_bytes(rules.read_bytes() + b"x")

    with pytest.raises(ScorecardBundleError, match="Hash físico inválido"):
        FittedScorecardBundle.load(path)


def test_bundle_incompleto_falla_antes_de_leer_reglas(tmp_path: Path) -> None:
    study, _frame = _study_y_frame(tmp_path)
    path = FittedScorecardBundle.from_study(study).save(tmp_path / "bundle")  # type: ignore[arg-type]
    manifest_path = path / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    del manifest["model"]["calibration"]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ScorecardBundleError, match=r"manifest\.model"):
        FittedScorecardBundle.load(path)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda manifest: manifest["treatment_policy"].__setitem__(
                "missing", "inventar_woe_cero"
            ),
            "treatment_policy",
        ),
        (
            lambda manifest: manifest["special_catalog"].__setitem__("score", [{"garbage": 1}]),
            "schema inválido|sentinel|special_catalog",
        ),
        (
            lambda manifest: manifest["special_catalog"].__setitem__(
                "score", [{"type": "date", "value": "no-fecha"}]
            ),
            "inválido|canónico",
        ),
    ],
)
def test_bundle_rechaza_politica_o_codec_inventados(
    tmp_path: Path, mutation: Callable[[dict[str, Any]], None], message: str
) -> None:
    study, _frame = _study_y_frame(tmp_path)
    path = FittedScorecardBundle.from_study(study).save(tmp_path / "bundle")  # type: ignore[arg-type]
    _reescribir_manifest(path, mutation)
    with pytest.raises(ScorecardBundleError, match=message):
        FittedScorecardBundle.load(path)


def test_bundle_rechaza_manifest_semanticamente_valido_no_canonico(tmp_path: Path) -> None:
    study, _frame = _study_y_frame(tmp_path)
    path = FittedScorecardBundle.from_study(study).save(tmp_path / "bundle")  # type: ignore[arg-type]
    _reescribir_manifest(path, lambda manifest: None, canonical=False)
    with pytest.raises(ScorecardBundleError, match="bytes JSON canónicos"):
        FittedScorecardBundle.load(path)


@pytest.mark.parametrize(
    "sentinels",
    [
        [],
        [
            {"type": "float", "value": -99999.0},
            {"type": "float", "value": -77777.0},
        ],
    ],
)
def test_bundle_reconcilia_catalogo_special_con_reglas_congeladas(
    tmp_path: Path, sentinels: list[dict[str, Any]]
) -> None:
    study, _frame = _study_y_frame(tmp_path)
    path = FittedScorecardBundle.from_study(study).save(tmp_path / "bundle")  # type: ignore[arg-type]
    _reescribir_manifest(
        path, lambda manifest: manifest["special_catalog"].__setitem__("score", sentinels)
    )
    with pytest.raises(ScorecardBundleError, match="special_catalog no reconcilia"):
        FittedScorecardBundle.load(path)


def test_batch_particiona_con_rangos_hashes_y_orden_estables(tmp_path: Path) -> None:
    """Chunks 1/2/... producen una salida por fila y manifest sin gaps."""
    study, frame = _study_y_frame(tmp_path)
    bundle = FittedScorecardBundle.from_study(study)  # type: ignore[arg-type]
    source = tmp_path / "apply.csv"
    frame.drop(columns=["bad_flag", "cohort"]).reset_index().to_csv(source, index=False)

    batch = bundle.apply_file(source, tmp_path / "batch", chunk_size=7, id_column="loan_id")
    manifest = json.loads(batch.manifest_path.read_text(encoding="utf-8"))

    assert batch.rows == 30
    assert batch.chunks == 5
    assert [(chunk["start"], chunk["end"]) for chunk in manifest["chunks"]] == [
        (0, 7),
        (7, 14),
        (14, 21),
        (21, 28),
        (28, 30),
    ]
    parts = [
        pd.read_parquet(batch.output_dir / chunk["files"]["application"]["path"])
        for chunk in manifest["chunks"]
    ]
    combined = pd.concat(parts)
    assert combined["input_position"].tolist() == list(range(30))
    assert combined.index.tolist() == frame.index.tolist()
    assert manifest["apply_lineage"]["data_hash"] == manifest["input_hash"]
    assert manifest["apply_lineage"]["candidate_distribution_hash"] != (
        "external_evidence_required"
    )


def test_batch_digest_y_salida_no_dependen_del_tamano_de_chunk(tmp_path: Path) -> None:
    study, frame = _study_y_frame(tmp_path)
    bundle = FittedScorecardBundle.from_study(study)  # type: ignore[arg-type]
    source = tmp_path / "apply.csv"
    frame.drop(columns=["bad_flag", "cohort"]).reset_index().to_csv(source, index=False)

    results = [
        bundle.apply_file(source, tmp_path / f"batch-{size}", chunk_size=size, id_column="loan_id")
        for size in (1, 7, 30)
    ]
    assert len({result.input_hash for result in results}) == 1
    assert len({result.output_hash for result in results}) == 1
    outputs: list[dict[str, pd.DataFrame]] = []
    lineages = []
    for result in results:
        manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
        lineages.append(manifest["apply_lineage"])
        outputs.append(
            {
                view: pd.concat(
                    [
                        pd.read_parquet(result.output_dir / chunk["files"][view]["path"])
                        for chunk in manifest["chunks"]
                    ],
                    ignore_index=view == "trace",
                )
                for view in ("application", "woe", "trace")
            }
        )
    assert lineages[1:] == [lineages[0], lineages[0]]
    for observed in outputs[1:]:
        for view in ("application", "woe", "trace"):
            pd.testing.assert_frame_equal(observed[view], outputs[0][view])


def test_reglas_preparadas_equivalen_exactamente_y_no_aliasan(tmp_path: Path) -> None:
    """El cache del bundle conserva arrays exactos y cada apply recibe buffers nuevos."""
    study, frame = _study_y_frame(tmp_path)
    bundle = FittedScorecardBundle.from_study(study)  # type: ignore[arg-type]
    targetless = frame.drop(columns=["bad_flag", "cohort"])
    manifest = bundle.manifest
    special_catalog = manifest["special_catalog"]
    special_handling = manifest["treatment_policy"]["special_handling"]

    for feature in manifest["model"]["features"]:
        rules = bundle._rules.loc[bundle._rules["feature"].eq(feature)].copy(deep=False)
        special_values = tuple(special_catalog.get(feature, ()))
        expected = bundle_module._apply_feature(
            targetless[feature],
            rules,
            special_values=special_values,
            special_handling=special_handling,
        )
        prepared = bundle._prepared_rules[feature]
        observed = bundle_module._apply_feature(
            targetless[feature],
            prepared.rules,
            special_values=special_values,
            special_handling=special_handling,
            prepared=prepared,
        )
        for field in expected:
            np.testing.assert_array_equal(observed[field], expected[field], strict=True)
            assert not np.shares_memory(observed[field], expected[field])
        cached_to_output = {
            "numeric_woe": "woe",
            "numeric_raw_points": "raw_points",
            "numeric_points": "points",
            "numeric_bin_ids": "bin_id",
        }
        for cached, output in cached_to_output.items():
            assert not np.shares_memory(observed[output], getattr(prepared, cached))


def test_batch_csv_preserva_ids_textuales_y_hash_en_cada_frontera(tmp_path: Path) -> None:
    study, frame = _study_y_frame(tmp_path)
    bundle = FittedScorecardBundle.from_study(study)  # type: ignore[arg-type]
    targetless = frame.drop(columns=["bad_flag", "cohort"]).iloc[:6].copy()
    targetless.index = pd.Index(["0001", "0002", "0010", "0100", "1000", "1001"], name="loan_id")
    source = tmp_path / "ids.csv"
    targetless.reset_index().to_csv(source, index=False)

    batches = [
        bundle.apply_file(source, tmp_path / f"ids-{size}", chunk_size=size, id_column="loan_id")
        for size in (1, 2, 5, 6)
    ]
    assert len({batch.input_hash for batch in batches}) == 1
    for batch in batches:
        manifest = json.loads(batch.manifest_path.read_text(encoding="utf-8"))
        output = pd.concat(
            [
                pd.read_parquet(batch.output_dir / chunk["files"]["application"]["path"])
                for chunk in manifest["chunks"]
            ]
        )
        assert output.index.tolist() == targetless.index.tolist()


def test_batch_rechaza_llave_unica_repetida_entre_chunks(tmp_path: Path) -> None:
    study, frame = _study_y_frame(tmp_path)
    base = FittedScorecardBundle.from_study(study)  # type: ignore[arg-type]
    bundle = _bundle_con_llave(base, key="client_key", dtype="str")
    targetless = frame.drop(columns=["bad_flag", "cohort"]).iloc[:3].copy()
    targetless["client_key"] = pd.Series(
        ["001", "002", "001"], index=targetless.index, dtype="string"
    )
    source = tmp_path / "llaves.csv"
    targetless.reset_index().to_csv(source, index=False)

    with pytest.raises(ScorecardBundleError, match="llaves de identidad entre chunks"):
        bundle.apply_file(source, tmp_path / "rechazado", chunk_size=1, id_column="loan_id")
    assert not (tmp_path / "rechazado").exists()


def test_llave_unica_puede_coincidir_con_predictor_sin_duplicar_columna(tmp_path: Path) -> None:
    study, frame = _study_y_frame(tmp_path)
    base = FittedScorecardBundle.from_study(study)  # type: ignore[arg-type]
    bundle = _bundle_con_llave(base, key="score", dtype="int")
    targetless = frame.drop(columns=["bad_flag", "cohort"]).iloc[[0, 2, 4]].copy()

    result = bundle.apply(targetless)
    assert len(result.application_frame.index) == 3


def test_parquet_n_mas_uno_falla_por_metadata_antes_de_aplicar(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    study, frame = _study_y_frame(tmp_path)
    bundle = FittedScorecardBundle.from_study(study)  # type: ignore[arg-type]
    source = tmp_path / "apply.parquet"
    frame.drop(columns=["bad_flag", "cohort"]).iloc[:2].to_parquet(source)
    monkeypatch.setattr("nikodym.scorecard.bundle._MAX_BATCH_ROWS", 1)
    with pytest.raises(ScorecardBundleError, match="envelope S2"):
        bundle.apply_file(source, tmp_path / "rechazado", chunk_size=1)
    assert not (tmp_path / "rechazado").exists()


def test_no_finito_declarado_gana_al_guard_de_outlier(tmp_path: Path) -> None:
    study, _ = _study_y_frame(tmp_path)
    bundle = FittedScorecardBundle.from_study(study)  # type: ignore[arg-type]
    rules = bundle._rules.loc[bundle._rules["feature"].eq("score")].copy()
    special_index = rules.index[rules["kind"].eq("special")][0]
    rules.loc[special_index, "values_json"] = '[{"type":"float","value":"+inf"}]'
    rules.loc[special_index, "supported"] = True

    applied = bundle_module._apply_feature(
        pd.Series([float("inf")], name="score"),
        rules,
        special_values=({"type": "float", "value": "+inf"},),
        special_handling="separate",
    )

    assert applied["state"].tolist() == ["special"]
    assert applied["reason"].tolist() == [None]


_REAL_BUNDLE_SCRIPT = """\
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from nikodym.api import run
from nikodym.core.config import NikodymConfig
from nikodym.scorecard.bundle import FittedScorecardBundle
from nikodym.ui.datasets import materialize
from nikodym.ui.presets import standard_preset

def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

root = Path(sys.argv[1])
preset = standard_preset()
source = materialize(preset["dataset_id"], workdir=root)
frame = pd.read_parquet(source)
config = NikodymConfig.model_validate(preset["config"])
memory_data = config.data.model_copy(
    update={"load": config.data.load.model_copy(update={"source": None})}
)
study = run(
    config.model_copy(update={"data": memory_data}),
    artifacts={("data", "input_frame"): frame},
)
assert study.run_context.status == "done"
bundle = FittedScorecardBundle.from_study(study)
path = bundle.save(root / "bundle-real")
loaded = FittedScorecardBundle.load(path)
before = {name: sha256(path / name) for name in ("manifest.json", "bins.parquet")}
targetless = frame.iloc[:100]
result = loaded.apply(targetless)
after = {name: sha256(path / name) for name in ("manifest.json", "bins.parquet")}
assert result.summary == {"input_rows": 100, "scored_rows": 100, "not_scorable_rows": 0}
expected_score = study.artifacts.get("scorecard", "score").loc[targetless.index, "score"]
expected_pd = study.artifacts.get("calibration", "calibrated_pd_frame").loc[
    targetless.index, "pd_calibrated"
]
score_delta = float(
    np.max(np.abs(result.application_frame["score"].to_numpy() - expected_score.to_numpy()))
)
pd_delta = float(
    np.max(
        np.abs(result.application_frame["pd_calibrated"].to_numpy() - expected_pd.to_numpy())
    )
)
assert score_delta <= 1e-12
assert pd_delta <= 1e-12
assert before == after
print(
    json.dumps(
        {
            "bundle_hash": loaded.bundle_hash,
            "score_delta": score_delta,
            "pd_delta": pd_delta,
            **result.summary,
        },
        sort_keys=True,
    )
)
"""


def test_bundle_con_optbinning_real_en_subproceso_limpio(tmp_path: Path) -> None:
    """El artefacto final funciona con OptBinning real, no sólo con el doble unitario."""
    script = tmp_path / "bundle_real.py"
    script.write_text(_REAL_BUNDLE_SCRIPT, encoding="utf-8")
    subprocess_env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("COV_CORE_") and key != "COVERAGE_PROCESS_START"
    }
    completed = subprocess.run(
        [sys.executable, str(script), str(tmp_path)],
        cwd=tmp_path,
        env={
            **subprocess_env,
            "PYTHONHASHSEED": "0",
            "MPLCONFIGDIR": str(tmp_path / "mpl"),
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=180,
    )
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout.strip().splitlines()[-1])
    assert payload["scored_rows"] == 100
    assert payload["score_delta"] <= 1e-12
    assert payload["pd_delta"] <= 1e-12
    assert len(payload["bundle_hash"]) == 64
