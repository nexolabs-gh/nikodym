"""Tests de matrices CMF versionadas: hash, goldens normativos e import liviano."""

from __future__ import annotations

import hashlib
import subprocess
import sys
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

import nikodym.provisioning.cmf.matrices as matrices_module
from nikodym.provisioning.cmf.matrices import (
    CMF_MATRIX_IDS,
    CmfMatrixBundle,
    CmfMatrixError,
    CmfMatrixRow,
    load_cmf_matrices,
    validate_cmf_matrix_bundle,
)


@dataclass(frozen=True)
class MatrixConfig:
    """Config estructural mínima compatible con ``CmfMatrixConfigLike``."""

    active_version: str = "cmf_b1_b3_2025_01"
    require_verified_rows: bool = True
    fail_on_source_mismatch: bool = True


def test_load_cmf_matrices_acepta_canonico_y_hash_fijo() -> None:
    bundle = _load()
    unchecked_bundle = load_cmf_matrices(MatrixConfig(require_verified_rows=False))
    yaml_bytes = matrices_module._read_resource_bytes("cmf_b1_b3_2025_01.yaml")
    sha_bytes = matrices_module._read_resource_bytes("cmf_b1_b3_2025_01.sha256")
    observed_sha = hashlib.sha256(yaml_bytes).hexdigest()

    assert unchecked_bundle == bundle
    assert bundle.manifest.version == "cmf_b1_b3_2025_01"
    assert observed_sha == sha_bytes.decode("utf-8").strip()
    assert observed_sha == bundle.manifest.yaml_sha256
    assert observed_sha == "6272bd0dfa5821db8def039014d7288b694b520f51ddda5a0b52349ce2e8d794"
    assert len(bundle.rows) == 144
    assert bundle.matrix_ids == CMF_MATRIX_IDS


def test_load_cmf_matrices_rechaza_yaml_alterado_y_puede_degradar_por_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_read = matrices_module._read_resource_bytes

    def altered_read(name: str) -> bytes:
        data = original_read(name)
        if name == "cmf_b1_b3_2025_01.yaml":
            return data + b"\n"
        return data

    monkeypatch.setattr(matrices_module, "_read_resource_bytes", altered_read)
    with pytest.raises(CmfMatrixError, match="Hash YAML inconsistente"):
        load_cmf_matrices(MatrixConfig())

    degraded = load_cmf_matrices(MatrixConfig(fail_on_source_mismatch=False))
    assert (
        degraded.manifest.yaml_sha256
        == "6272bd0dfa5821db8def039014d7288b694b520f51ddda5a0b52349ce2e8d794"
    )


def test_load_cmf_matrices_falla_si_version_no_existe() -> None:
    with pytest.raises(CmfMatrixError, match="No existe el recurso"):
        load_cmf_matrices(MatrixConfig(active_version="cmf_no_existe"))


def test_load_cmf_matrices_exige_filas_verificadas(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_read = matrices_module._read_resource_bytes

    def pending_read(name: str) -> bytes:
        data = original_read(name)
        if name == "cmf_b1_b3_2025_01.yaml":
            return data.replace(b"status: verified", b"status: pending", 1)
        return data

    monkeypatch.setattr(matrices_module, "_read_resource_bytes", pending_read)
    with pytest.raises(CmfMatrixError, match="filas pending"):
        load_cmf_matrices(MatrixConfig(fail_on_source_mismatch=False))


def test_las_10_matrices_tienen_fuente_vigencia_estado_y_filas_esperadas() -> None:
    bundle = _load()
    entries = {entry.matrix_id: entry for entry in bundle.manifest.matrices}
    expected_counts = {
        "commercial_individual_performing_v2014": 10,
        "commercial_individual_default_v2014": 6,
        "commercial_group_leasing_v2018": 20,
        "commercial_group_student_v2018": 16,
        "commercial_group_generic_factoring_v2020": 25,
        "commercial_group_guarantee_substitution_v2018": 2,
        "consumer_standard_v2025": 23,
        "housing_pvg_v2018": 28,
        "guarantee_aval_quality_v2018": 6,
        "contingent_b3_v2016": 8,
    }

    assert set(entries) == set(CMF_MATRIX_IDS)
    for matrix_id, expected_count in expected_counts.items():
        entry = entries[matrix_id]
        rows = bundle.get_rows(matrix_id)
        assert len(rows) == expected_count
        assert entry.status == "verified"
        assert entry.source_ref.startswith("§")
        assert entry.effective_date
        assert all(row.status == "verified" and row.source_ref.startswith("§") for row in rows)

    pending = {item.id: item for item in bundle.manifest.pending_items}
    assert pending["financial_guarantee_haircuts"].marker == "FALTA-DATO"
    assert pending["ran_21_10_numeric_tables"].status == "pending"


def test_comercial_individual_goldens_a1_b4_y_pe_decimal() -> None:
    bundle = _load()
    a1 = bundle.get_row("commercial_individual_performing_v2014", "A1")
    b4 = bundle.get_row("commercial_individual_performing_v2014", "B4")

    assert (a1.pi_percent, a1.pdi_percent, a1.pe_percent) == ("0,04", "90,0", "0,03600")
    assert (b4.pi_percent, b4.pdi_percent, b4.pe_percent) == ("45,00", "97,5", "43,87500")
    assert _dec(a1.pi_percent) * _dec(a1.pdi_percent) / Decimal("100") == Decimal("0.03600")
    assert _dec(b4.pi_percent) * _dec(b4.pdi_percent) / Decimal("100") == Decimal("43.87500")


def test_vivienda_consumo_incumplimiento_goldens_no_tautologicos() -> None:
    bundle = _load()
    vivienda = bundle.get_row("housing_pvg_v2018", "pvg_gt_90_mora_60_89")
    consumo_pi = bundle.get_row("consumer_standard_v2025", "pi_dpd_0_7_housing_no_system_dpd30_no")
    consumo_pdi = bundle.get_row("consumer_standard_v2025", "pdi_housing_no_installment_loans")
    c3 = bundle.get_row("commercial_individual_default_v2014", "C3")

    assert vivienda.dimensions == {"mora_bucket": "60_89", "pvg_bucket": "pvg_gt_90"}
    assert vivienda.pe_percent == "24,2355"
    assert consumo_pi.pi_percent == "6,6"
    assert consumo_pdi.pdi_percent == "56,6"
    assert c3.pp_percent == "25"
    assert c3.dimensions["expected_loss_range_label"] == "Mas de 20 % hasta 30 %"


def test_contingentes_b3_ocho_filas_y_f_condicional() -> None:
    rows = _load().get_rows("contingent_b3_v2016")
    ccf_by_row = {row.row_id: row.ccf_percent for row in rows}

    assert ccf_by_row == {
        "a": "100",
        "b": "20",
        "c": "20",
        "d": "50",
        "e": "35",
        "f_cae": "15",
        "f_otros": "100",
        "g": "100",
    }
    f_cae = next(row for row in rows if row.row_id == "f_cae")
    f_otros = next(row for row in rows if row.row_id == "f_otros")
    assert f_cae.dimensions["contingent_subtype"] == "cae_ley_20027"
    assert f_otros.dimensions["contingent_subtype"] == "otros"


def test_avales_escala_internacional_y_nacional_corregidas() -> None:
    rows = _load().get_rows("guarantee_aval_quality_v2018")
    by_key = {
        (row.dimensions["rating_category"], row.dimensions["rating_scale"]): (
            row.pi_percent,
            row.pdi_percent,
        )
        for row in rows
    }

    assert {category for category, _scale in by_key} == {"AA/Aa2", "A/A2", "BBB-/Baa3"}
    assert by_key[("AA/Aa2", "international")] == ("0,04", "90,0")
    assert by_key[("A/A2", "international")] == ("0,04", "90,0")
    assert by_key[("BBB-/Baa3", "international")] == ("0,10", "82,5")
    assert by_key[("A/A2", "national")] == ("0,10", "82,5")
    assert by_key[("BBB-/Baa3", "national")] == ("0,25", "87,5")


def test_bundle_lookup_determinismo_y_error_de_fila() -> None:
    first = _load()
    second = _load()

    assert first == second
    assert first.get_row("consumer_standard_v2025", "pi_default").pi_percent == "100"
    assert first.get_rows("matriz_inexistente") == ()
    with pytest.raises(CmfMatrixError, match="No existe la fila normativa"):
        first.get_row("consumer_standard_v2025", "fila_inexistente")


def test_validate_detecta_cobertura_duplicados_pe_pp_rango_manifest_y_decimal() -> None:
    bundle = _load()
    _raises_matrix_error(bundle.model_copy(update={"rows": bundle.rows[:-8]}), "10 matrices")
    duplicated = bundle.model_copy(update={"rows": (*bundle.rows, bundle.rows[0])})
    _raises_matrix_error(duplicated, "duplicada")

    bad_pe = _replace_row(
        bundle,
        "commercial_individual_performing_v2014",
        "A1",
        pe_percent="0,99",
    )
    _raises_matrix_error(bad_pe, "PE inconsistente")

    bad_pp = _replace_row(bundle, "commercial_individual_default_v2014", "C3", pp_percent="24")
    _raises_matrix_error(bad_pp, "PP inconsistente")

    missing_pp = _replace_row(bundle, "commercial_individual_default_v2014", "C3", pp_percent=None)
    _raises_matrix_error(missing_pp, "sin PP")

    bad_range_row = bundle.get_row("commercial_individual_default_v2014", "C3").model_copy(
        update={"dimensions": {"category": "C3", "expected_loss_range": "otro"}}
    )
    bad_range = _replace_row_object(bundle, bad_range_row)
    _raises_matrix_error(bad_range, "Rango de perdida")

    bad_decimal = _replace_row(
        bundle,
        "commercial_individual_performing_v2014",
        "A1",
        pi_percent="no_decimal",
    )
    _raises_matrix_error(bad_decimal, "Porcentaje invalido")

    bad_manifest = bundle.manifest.model_copy(update={"matrices": bundle.manifest.matrices[:-1]})
    _raises_matrix_error(bundle.model_copy(update={"manifest": bad_manifest}), "manifest CMF")

    deprecated_entry = bundle.manifest.matrices[0].model_copy(update={"status": "deprecated"})
    manifest_with_deprecated = bundle.manifest.model_copy(
        update={"matrices": (deprecated_entry, *bundle.manifest.matrices[1:])}
    )
    _raises_matrix_error(
        bundle.model_copy(update={"manifest": manifest_with_deprecated}),
        "incompleto o deprecado",
    )


def test_yaml_serializacion_deterministica_en_dos_pasadas() -> None:
    yaml_bytes = matrices_module._read_resource_bytes("cmf_b1_b3_2025_01.yaml")
    loaded = matrices_module.yaml.safe_load(yaml_bytes.decode("utf-8"))

    first = matrices_module.yaml.safe_dump(loaded, allow_unicode=True, sort_keys=False)
    second = matrices_module.yaml.safe_dump(loaded, allow_unicode=True, sort_keys=False)

    assert first == second


def test_import_liviano_cmf_no_carga_matrices_y_matrices_no_importa_pandas() -> None:
    source = Path(matrices_module.__file__).read_text(encoding="utf-8")
    assert "import pandas" not in source
    assert "import numpy" not in source

    code = (
        "import sys;"
        "import nikodym.provisioning.cmf;"
        "assert 'nikodym.provisioning.cmf.matrices' not in sys.modules;"
        "assert 'pandas' not in sys.modules;"
        "import nikodym.provisioning.cmf.matrices;"
        "assert 'pandas' not in sys.modules"
    )
    subprocess.run([sys.executable, "-c", code], check=True)


def _load() -> CmfMatrixBundle:
    return load_cmf_matrices(MatrixConfig())


def _dec(value: str | None) -> Decimal:
    assert value is not None
    return Decimal(value.replace(",", "."))


def _replace_row(
    bundle: CmfMatrixBundle,
    matrix_id: str,
    row_id: str,
    **updates: Any,
) -> CmfMatrixBundle:
    row = bundle.get_row(matrix_id, row_id).model_copy(update=updates)
    return _replace_row_object(bundle, row)


def _replace_row_object(bundle: CmfMatrixBundle, replacement: CmfMatrixRow) -> CmfMatrixBundle:
    rows = tuple(
        replacement
        if row.matrix_id == replacement.matrix_id and row.row_id == replacement.row_id
        else row
        for row in bundle.rows
    )
    return bundle.model_copy(update={"rows": rows})


def _raises_matrix_error(bundle: CmfMatrixBundle, message: str) -> None:
    with pytest.raises(CmfMatrixError, match=message):
        validate_cmf_matrix_bundle(bundle)
