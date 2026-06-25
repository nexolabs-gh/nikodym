"""Tests del schema del config (SDD-01 §4-5, SDD-05 §5): defaults, frozen y validación."""

import pytest
from pydantic import ValidationError

from nikodym.core.config import NikodymConfig, ReproConfig, RunConfig
from nikodym.core.config import schema as _schema_mod


@pytest.fixture(autouse=True)
def _vista_core_solo(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fuerza la vista *core-only*: sin capa ``data`` cargada, la sección ``data`` es un blob opaco.

    ``nikodym.data``/``nikodym.audit`` (importados por otros tests de la sesión) pueblan hooks
    *process-wide*; aquí se neutralizan para probar el núcleo en aislamiento.
    """
    monkeypatch.setattr(_schema_mod, "_DATA_CONFIG_CLS", None)
    monkeypatch.setattr(_schema_mod, "_AUDIT_CONFIG_CLS", None)


def test_construye_sin_argumentos() -> None:
    """NikodymConfig() construye sin kwargs con todos los defaults (DoD F0 a)."""
    cfg = NikodymConfig()
    assert cfg.schema_version == "1.0.0"
    assert cfg.name == "nikodym-study"
    assert cfg.repro.seed == 42
    assert cfg.run.fail_fast is True
    assert cfg.data is None
    assert cfg.audit is None


def test_repro_defaults() -> None:
    """ReproConfig() trae seed=42 y determinismo no estricto."""
    repro = ReproConfig()
    assert repro.seed == 42
    assert repro.strict_determinism is False


def test_repro_seed_negativa_rechazada() -> None:
    """Una semilla negativa viola ge=0 (SeedSequence rechaza entropía negativa)."""
    with pytest.raises(ValidationError):
        ReproConfig(seed=-1)


def test_run_defaults() -> None:
    """RunConfig() trae steps=None y fail_fast forzado a True (v1)."""
    run = RunConfig()
    assert run.steps is None
    assert run.fail_fast is True


def test_extra_forbid_levanta() -> None:
    """Un campo desconocido (typo) levanta ValidationError, no se descarta en silencio."""
    with pytest.raises(ValidationError):
        NikodymConfig(campo_inexistente=1)


def test_frozen_reasignar_campo_levanta() -> None:
    """Reasignar un campo de un config frozen levanta ValidationError."""
    cfg = NikodymConfig()
    with pytest.raises(ValidationError):
        cfg.name = "otro"


def test_frozen_no_congela_lista_anidada() -> None:
    """frozen no hace deep-freeze: la lista interna sigue mutable -> identidad por config_hash."""
    run = RunConfig(steps=["a", "b"])
    run.steps.append("c")  # type: ignore[union-attr]  # frozen no congela el contenido de la lista
    assert run.steps == ["a", "b", "c"]


def test_cross_section_steps_inactivas_levanta() -> None:
    """run.steps no puede apuntar a una sección inactiva (None)."""
    with pytest.raises(ValidationError) as info:
        NikodymConfig(run=RunConfig(steps=["data"]))
    assert "secciones inactivas" in str(info.value)


def test_cross_section_ok_cuando_seccion_activa() -> None:
    """Si la sección referida por steps está activa (no-None), no levanta."""
    cfg = NikodymConfig(run=RunConfig(steps=["data"]), data={"x": 1})
    assert cfg.run.steps == ["data"]


def test_campos_tienen_title() -> None:
    """Cada campo de las secciones transversales declara title (contrato UI, SDD-05 §5.3)."""
    for modelo in (NikodymConfig, ReproConfig, RunConfig):
        for nombre, campo in modelo.model_fields.items():
            assert campo.title is not None, f"{modelo.__name__}.{nombre} sin title"


def test_data_acepta_dict_de_primitivas() -> None:
    """El placeholder data acepta un dict JSON-canónico de primitivas."""
    cfg = NikodymConfig(data={"load": {"source": "x.parquet", "filas": 10}})
    assert cfg.data == {"load": {"source": "x.parquet", "filas": 10}}


def test_data_rechaza_set_no_determinista() -> None:
    """Un set en data se rechaza: su orden de iteración rompería el config_hash entre procesos."""
    with pytest.raises(ValidationError):
        NikodymConfig(data={"a": {1, 2, 3}})


def test_data_rechaza_objeto_no_serializable() -> None:
    """Un objeto sin serialización JSON en data se rechaza al construir, no al hashear."""
    with pytest.raises(ValidationError):
        NikodymConfig(data={"o": object()})


@pytest.mark.parametrize("no_finito", [float("nan"), float("inf"), float("-inf")])
def test_data_rechaza_float_no_finito(no_finito: float) -> None:
    """Un float no finito en data se rechaza (se corrompería a null en el round-trip)."""
    with pytest.raises(ValidationError):
        NikodymConfig(data={"x": no_finito})
