"""Registro ejecutable y bidireccional de oráculos D-RDY-ABA-2/3."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from nikodym.ui import jobs

_ROOT = Path(__file__).resolve().parents[2]
_REGISTRY = _ROOT / "tests" / "fixtures" / "option_effect_oracles.txt"


@dataclass(frozen=True)
class OracleEntry:
    values: tuple[str, ...]
    dispatcher_nodes: tuple[str, ...]
    effect_nodes: tuple[str, ...]


def _nodes(raw: str) -> tuple[str, ...]:
    nodes = tuple(value for value in raw.split(";") if value)
    assert nodes, "la celda de node ids no puede quedar vacía"
    return nodes


def _registry() -> dict[str, OracleEntry]:
    entries: dict[str, OracleEntry] = {}
    for number, raw in enumerate(_REGISTRY.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw or raw.startswith("#"):
            continue
        parts = raw.split("\t")
        assert len(parts) == 4, (
            f"línea {number}: se esperaban path, valores, dispatcher nodes y effect nodes"
        )
        path, raw_values, raw_dispatchers, raw_effects = parts
        assert path not in entries, f"path duplicado en registry: {path}"
        values = tuple(raw_values.split(","))
        assert values and all(values), f"{path}: valores vacíos"
        assert len(values) == len(set(values)), f"{path}: valores duplicados"
        entries[path] = OracleEntry(values, _nodes(raw_dispatchers), _nodes(raw_effects))
    return entries


def _choices() -> list[dict[str, object]]:
    return [choice for choices in jobs._ABANICO_POR_SECCION.values() for choice in choices]


def _oracle_cases() -> dict[str, tuple[str, ...]]:
    cases: dict[str, tuple[str, ...]] = {}
    for path, entry in _registry().items():
        for value in entry.values:
            pair = f"{path}={value}"
            cases[f"option-dispatch:{pair}"] = entry.dispatcher_nodes
            cases[f"option-effect:{pair}"] = entry.effect_nodes
    return cases


def test_registry_reconcilia_exactamente_los_69_paths_sin_fallback() -> None:
    registry = _registry()
    catalog = {str(choice["path"]) for choice in _choices()}
    assert len(catalog) == 69
    assert set(registry) == catalog


def test_cada_suite_resuelve_tests_reales_del_motor() -> None:
    for path, entry in _registry().items():
        for node in (*entry.dispatcher_nodes, *entry.effect_nodes):
            relative, separator, test_name = node.partition("::")
            source = _ROOT / relative
            assert source.is_file(), f"{path}: archivo de oráculo ausente: {relative}"
            source_text = source.read_text(encoding="utf-8")
            assert separator, f"{path}: no se admiten suites amplias, falta ::test_función"
            assert test_name.startswith("test_")
            assert f"def {test_name}(" in source_text, (
                f"{path}: test de oráculo ausente: {test_name}"
            )


def test_los_203_pares_soportados_declaran_el_id_estable_del_registry() -> None:
    registry = _registry()
    cases = _oracle_cases()
    supported = 0
    for choice in _choices():
        path = str(choice["path"])
        enabled_values: list[str] = []
        for option in choice["options"]:  # type: ignore[index]
            enabled = option["estado"] in {jobs._DISPONIBLE, jobs._EXIGE_OTRO_CAMPO}
            if enabled:
                supported += 1
                enabled_values.append(str(option["value"]))
                pair = f"{path}={option['value']}"
                assert option["dispatcher_oracle"] == f"option-dispatch:{pair}"
                assert option["effect_oracle"] == f"option-effect:{pair}"
                assert path in registry
                assert cases[str(option["dispatcher_oracle"])]
                assert cases[str(option["effect_oracle"])]
            else:
                assert option["dispatcher_oracle"] is None
                assert option["effect_oracle"] is None
        assert tuple(enabled_values) == registry[path].values
    assert supported == 203
    assert len(cases) == 406


def test_el_registry_no_puede_ecoar_metadata_de_config() -> None:
    """El efecto debe vivir en un test de motor; schema/TypeAdapter no califican como oráculo."""
    forbidden = {
        "test_jobs_option_effects.py",
        "test_jobs_abanico.py",
        "test_config_full_schema.py",
    }
    for path, entry in _registry().items():
        for node in (*entry.dispatcher_nodes, *entry.effect_nodes):
            assert Path(node.split("::", 1)[0]).name not in forbidden, path


def test_dispatch_y_efecto_tienen_evidencia_declarada_por_separado() -> None:
    for path, entry in _registry().items():
        assert entry.dispatcher_nodes, f"{path}: falta dispatcher oracle"
        assert entry.effect_nodes, f"{path}: falta effect oracle"


def test_cada_id_path_value_resuelve_a_node_ids_exactos() -> None:
    cases = _oracle_cases()
    assert len(cases) == 406
    for oracle_id, nodes in cases.items():
        assert oracle_id.startswith(("option-dispatch:", "option-effect:"))
        assert all("::test_" in node for node in nodes)


def test_los_ids_de_oraculo_son_unicos_por_cada_par_soportado() -> None:
    dispatchers: set[str] = set()
    effects: set[str] = set()
    for choice in _choices():
        for option in choice["options"]:  # type: ignore[index]
            if option["estado"] not in {jobs._DISPONIBLE, jobs._EXIGE_OTRO_CAMPO}:
                continue
            dispatcher = str(option["dispatcher_oracle"])
            effect = str(option["effect_oracle"])
            assert dispatcher not in dispatchers
            assert effect not in effects
            dispatchers.add(dispatcher)
            effects.add(effect)
    assert len(dispatchers) == len(effects) == 203
