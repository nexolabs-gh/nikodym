"""Gates del directorio de corrida y del layout de SDD-03 §6 en disco (D-GOB-6/7).

Contiene los tests **4 y 5** preespecificados en §6 de
``docs/design/_ENMIENDA-GOBERNANZA-ALCANZABLE.md``. Los otros cuatro viven en
``test_canal_metricas.py``.

Todo lo que se comprueba aquí se mide sobre **archivos escritos en disco**, no sobre el objeto en
memoria: el contrato de D-GOB-6 es que quien instala con ``pip`` obtenga la evidencia, y un
snapshot de helper no demuestra eso.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from _ui_f1 import full_f1_config, write_behavior_parquet

import nikodym
from nikodym.audit.config import AuditConfig
from nikodym.core.config import NikodymConfig
from nikodym.core.exceptions import ConfigError
from nikodym.core.study import Study
from nikodym.governance.config import GovernanceConfig


@pytest.fixture(autouse=True)
def _usar_fake_binning_process(fake_binning_process: object) -> None:
    """Evita OR-Tools dentro del proceso pytest para los tests in-process con binning."""
    del fake_binning_process


@pytest.fixture
def fuente_f1(tmp_path: Path) -> str:
    """Frame de comportamiento de 30 filas, el mismo que usa el resto de la capa F1."""
    source = tmp_path / "behavior.parquet"
    write_behavior_parquet(source)
    return str(source)


def _config_gobernada(fuente: str, **secciones: object) -> NikodymConfig:
    """Config F1 con las secciones de gobernanza que pida cada gate."""
    base = full_f1_config(fuente)
    return base.model_copy(update=secciones)


def _gobernanza() -> GovernanceConfig:
    """``purpose`` es obligatorio (SR 11-7): el motor no lo inventa, el test lo declara."""
    return GovernanceConfig(
        model_name="run-dir",
        purpose="Gate del directorio de corrida (D-GOB-6).",
    )


# ─────────── 4. el model card llega al usuario de `pip install`, medido en disco ───────────


def test_el_model_card_json_en_disco_trae_las_metricas(fuente_f1: str, tmp_path: Path) -> None:
    """Test 4 de §6: se mide sobre el ``model_card.json`` escrito, no sobre el objeto en memoria.

    Es la diferencia entre «el builder funciona» y «la persona recibe el archivo». Antes de D-GOB-6
    este archivo **no existía en ninguna ruta entregada**: ``nikodym.run()`` no creaba directorio
    de corrida alguno, así que el layout de SDD-03 §6 no tenía dónde anclarse.
    """
    destino = tmp_path / "corrida"
    config = _config_gobernada(fuente_f1, governance=_gobernanza(), audit=AuditConfig(enabled=True))

    study = nikodym.run(config, run_dir=destino)
    assert study.run_context.status == "done"

    card_json = destino / "model_card.json"
    assert card_json.is_file(), "el model card tiene que existir COMO ARCHIVO, no sólo en memoria"

    card = json.loads(card_json.read_text(encoding="utf-8"))
    assert card["metrics"], "un model card sin métricas no cumple el bloque que SR 11-7 exige"
    assert card["purpose"] == "Gate del directorio de corrida (D-GOB-6)."
    assert card["run_id"] == study.run_context.run_id

    # Forma plana: es la única que los dos consumidores aceptan (D-GOB-2).
    for clave, valor in card["metrics"].items():
        assert "." in clave, f"'{clave}' sin prefijo de dominio"
        assert isinstance(valor, float | int) and not isinstance(valor, bool)

    assert "data.n_rows" in card["metrics"]
    assert card["metrics"]["data.n_rows"] == 30.0

    # …y el .md de al lado cuenta lo mismo, que es lo que lee una persona.
    card_md = (destino / "model_card.md").read_text(encoding="utf-8")
    assert "## Métricas" in card_md
    assert "data.n_rows" in card_md


def test_el_layout_escribe_solo_lo_que_su_seccion_activa(fuente_f1: str, tmp_path: Path) -> None:
    """``audit`` sin ``governance`` deja trail y entorno, y **no** card (D-GOB-6)."""
    destino = tmp_path / "solo-audit"
    config = _config_gobernada(fuente_f1, audit=AuditConfig(enabled=True))

    nikodym.run(config, run_dir=destino)

    assert (destino / "audit_trail.jsonl").is_file()
    assert (destino / "environment.json").is_file()
    assert not (destino / "model_card.json").exists()
    assert not (destino / "model_card.md").exists()
    # `scenario_log.jsonl` NO se fabrica: no tiene productor y un archivo vacío sería teatro.
    assert not (destino / "scenario_log.jsonl").exists()
    # Lo que ya producía `Study.save`, en su subdirectorio para no pisar el trail.
    assert (destino / "study" / "config.yaml").is_file()
    assert (destino / "study" / "lineage.json").is_file()


def test_sin_run_dir_no_se_toca_el_disco(fuente_f1: str, tmp_path: Path, monkeypatch) -> None:
    """El default ``run_dir=None`` conserva el comportamiento histórico: cero escrituras.

    Es la mitad que hace aceptable a D-GOB-6: una librería que empieza a dejar archivos en el
    ``cwd`` de quien la importa sería una regresión, no una mejora.
    """
    cwd = tmp_path / "cwd-vacio"
    cwd.mkdir()
    monkeypatch.chdir(cwd)

    study = nikodym.run(full_f1_config(fuente_f1))

    assert study.run_context.status == "done"
    assert list(cwd.iterdir()) == [], f"la corrida dejó archivos en el cwd: {list(cwd.iterdir())}"


# ─────────── 5. dos corridas desde el mismo cwd producen DOS trails separados ───────────


def test_dos_corridas_desde_el_mismo_cwd_no_comparten_trail(
    fuente_f1: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test 5 de §6: cierra la violación de SDD-03 §8 medida en §1.4 de la enmienda.

    Antes de D-GOB-7 ``trail_filename`` se resolvía contra el ``cwd``, así que dos corridas
    lanzadas desde el mismo directorio **concatenaban** sus eventos en el mismo JSONL
    *append-only* — justo lo que SDD-03 §8 prohíbe («una instancia por run»). El control negativo
    que revierte a la ruta relativa está en ``cn_capa2`` y observa un único archivo con los eventos
    de las dos.
    """
    cwd = tmp_path / "mismo-cwd"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    config = _config_gobernada(fuente_f1, audit=AuditConfig(enabled=True))

    primera = nikodym.run(config, run_dir=tmp_path / "run-a")
    segunda = nikodym.run(config, run_dir=tmp_path / "run-b")

    assert primera.run_context.run_id != segunda.run_context.run_id

    trail_a = tmp_path / "run-a" / "audit_trail.jsonl"
    trail_b = tmp_path / "run-b" / "audit_trail.jsonl"
    assert trail_a.is_file() and trail_b.is_file()
    assert trail_a.read_bytes() != trail_b.read_bytes()

    # Cada trail contiene EXACTAMENTE un run_id, y es el suyo.
    for trail, study in ((trail_a, primera), (trail_b, segunda)):
        ids = {
            evento["payload"]["run_id"]
            for evento in _eventos(trail)
            if evento["kind"] in {"run_start", "run_end"}
        }
        assert ids == {study.run_context.run_id}, f"{trail.name} mezcla corridas: {ids}"

    # …y nada quedó en el cwd, que es la otra mitad de la violación.
    assert list(cwd.iterdir()) == []


def test_trail_relativo_sin_run_dir_es_un_error_explicito(fuente_f1: str, tmp_path: Path) -> None:
    """D-GOB-7: se rompe fuerte en vez de escribir en el ``cwd`` en silencio."""
    config = _config_gobernada(fuente_f1, audit=AuditConfig(enabled=True))

    with pytest.raises(ConfigError, match="trail_filename relativo"):
        nikodym.run(config)


def test_trail_absoluto_sin_run_dir_se_sigue_respetando(fuente_f1: str, tmp_path: Path) -> None:
    """Una ruta absoluta ya eligió dónde escribir: D-GOB-7 no se la quita."""
    trail = tmp_path / "elegido" / "mi_trail.jsonl"
    trail.parent.mkdir()
    config = _config_gobernada(
        fuente_f1, audit=AuditConfig(enabled=True, trail_filename=str(trail))
    )

    study = nikodym.run(config)

    assert study.run_context.status == "done"
    assert trail.is_file() and trail.stat().st_size > 0


# ─────────── política de sobrescritura (§5 de la enmienda) ───────────


def test_un_run_dir_no_vacio_se_aparta_en_vez_de_mezclarse(fuente_f1: str, tmp_path: Path) -> None:
    """Dos corridas no se mezclan en el mismo directorio: se aparta el previo (§5).

    Mezclarlas produciría un trail concatenado junto a un model card que no corresponde a los
    artefactos de al lado, que es peor que perder el directorio anterior.
    """
    destino = tmp_path / "reutilizado"
    config = _config_gobernada(fuente_f1, governance=_gobernanza(), audit=AuditConfig(enabled=True))

    primera = nikodym.run(config, run_dir=destino)
    eventos_primera = len(_eventos(destino / "audit_trail.jsonl"))
    assert eventos_primera > 0

    segunda = nikodym.run(config, run_dir=destino)

    card = json.loads((destino / "model_card.json").read_text(encoding="utf-8"))
    assert card["run_id"] == segunda.run_context.run_id
    assert card["run_id"] != primera.run_context.run_id

    ids = {
        evento["payload"]["run_id"]
        for evento in _eventos(destino / "audit_trail.jsonl")
        if evento["kind"] in {"run_start", "run_end"}
    }
    assert ids == {segunda.run_context.run_id}, (
        "el trail de la segunda corrida no puede traer eventos de la primera"
    )


def test_una_corrida_fallida_deja_su_evidencia(tmp_path: Path) -> None:
    """El model card de un run fallido es explícitamente válido (SDD-03 §7.1.a; §5)."""
    from _ui_f1 import failing_config

    fuente = tmp_path / "behavior.parquet"
    write_behavior_parquet(fuente)
    destino = tmp_path / "fallida"
    config = failing_config(str(fuente)).model_copy(
        update={"audit": AuditConfig(enabled=True), "governance": _gobernanza()}
    )

    study = nikodym.run(config, run_dir=destino)

    assert study.run_context.status == "failed"
    assert (destino / "audit_trail.jsonl").is_file()
    assert (destino / "study" / "run_metadata.json").is_file()
    metadata = json.loads((destino / "study" / "run_metadata.json").read_text(encoding="utf-8"))
    assert metadata["status"] == "failed"
    assert metadata["error"] is not None


def _eventos(trail: Path) -> list[dict]:
    """Lee el JSONL append-only del audit-trail."""
    return [
        json.loads(linea)
        for linea in trail.read_text(encoding="utf-8").splitlines()
        if linea.strip()
    ]


def test_study_run_directo_sigue_sin_escribir_nada(
    fuente_f1: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``Study.run()`` es el primitivo: no gana efectos de disco por D-GOB-6."""
    cwd = tmp_path / "primitivo"
    cwd.mkdir()
    monkeypatch.chdir(cwd)

    study = Study(full_f1_config(fuente_f1)).run()

    assert study.run_context.status == "done"
    assert list(cwd.iterdir()) == []
