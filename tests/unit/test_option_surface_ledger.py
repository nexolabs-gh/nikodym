"""Gate estático del censo bidireccional completo D-RDY-ABA-6."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nikodym.ui import jobs, option_surface
from nikodym.ui.option_surface import (
    UnclassifiedOptionSurfaceError,
    classified_option_surface,
    measured_literal_pairs,
)

_LEDGER = Path(__file__).resolve().parent.parent / "fixtures" / "option_surface_ledger.json"


def test_ledger_clasifica_exactamente_cada_literal_en_ambos_sentidos() -> None:
    expected = json.loads(_LEDGER.read_text(encoding="utf-8"))
    observed = classified_option_surface()
    assert observed == expected, (
        "cambió un Literal o su clasificación; revise la superficie y regenere con "
        "`uv run --no-sync python scripts/gen_option_surface_ledger.py`"
    )
    pairs = [(entry["path"], entry["value"]) for entry in expected["entries"]]
    assert len(pairs) == len(set(pairs)) == len(measured_literal_pairs())


def test_catalogo_publico_es_subconjunto_exactamente_clasificado_del_ledger() -> None:
    ledger = json.loads(_LEDGER.read_text(encoding="utf-8"))
    indexed = {
        (entry["path"], entry["value"]): entry["classification"] for entry in ledger["entries"]
    }
    expected_by_state = {
        jobs._DISPONIBLE: "methodology_selectable",
        jobs._EXIGE_OTRO_CAMPO: "methodology_selectable_conditioned",
        jobs._NO_IMPLEMENTADA: "not_implemented_visible_disabled",
    }
    catalog_pairs = set()
    for choices in jobs._ABANICO_POR_SECCION.values():
        for choice in choices:
            for option in choice["options"]:
                pair = (choice["path"], str(option["value"]))
                catalog_pairs.add(pair)
                assert indexed[pair] == expected_by_state[option["estado"]]
    assert catalog_pairs


def test_aliases_ocultos_no_reaparecen_como_literal_ni_opcion() -> None:
    ledger = json.loads(_LEDGER.read_text(encoding="utf-8"))
    motor = set(measured_literal_pairs())
    catalog = {
        (choice["path"], str(option["value"]))
        for choices in jobs._ABANICO_POR_SECCION.values()
        for choice in choices
        for option in choice["options"]
    }
    aliases = {(alias["path"], alias["value"]) for alias in ledger["aliases"]}
    assert aliases == {
        ("model.engine", "glm_binomial"),
        ("selection.priority_order", "gini"),
        ("report.formats", "html"),
        ("markov.dynamics.projection_mode", "period_matrices"),
    }
    assert aliases.isdisjoint(motor)
    assert aliases.isdisjoint(catalog)


def test_cada_disposicion_explica_razon_y_autoridad() -> None:
    ledger = classified_option_surface()
    for entry in [*ledger["entries"], *ledger["aliases"]]:
        assert entry["reason"]
        assert entry["authority"]


def test_literal_nuevo_sin_politica_falla_sin_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """Negativo D-RDY-ABA-6: retirar una disposición no se cura con una clase automática."""
    monkeypatch.delitem(option_surface._DETAIL_POLICIES, "binning.feature_columns")
    with pytest.raises(UnclassifiedOptionSurfaceError, match="sin disposición explícita"):
        classified_option_surface()


def test_politica_obsoleta_o_solapada_falla(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(option_surface._DETAIL_POLICIES, "inventada.path", ("nuevo",))
    with pytest.raises(UnclassifiedOptionSurfaceError, match="sin Literal vigente"):
        classified_option_surface()

    monkeypatch.delitem(option_surface._DETAIL_POLICIES, "inventada.path")
    monkeypatch.setitem(option_surface._DETAIL_POLICIES, "model.optimizer", ("newton",))
    with pytest.raises(UnclassifiedOptionSurfaceError, match="solapan catálogo"):
        classified_option_surface()
