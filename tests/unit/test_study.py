"""Tests de ``core.study`` (SDD-01 §4/§6/§7; CT-1/CT-4): el orquestador ``Study``.

Cubren el DoD F0 (construir/serializar/recargar sin valores ficticios), el run trivial y con pasos
dummy (vía monkeypatch del seam de resolución), la validación CT-1 (pre-run global + por paso con
fan-in), ``fail_fast`` ruidoso, la persistencia atómica y la recarga con puerta ``trust`` +
verificación de reproducibilidad.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nikodym.core import study as study_mod
from nikodym.core.audit import InMemoryAuditSink
from nikodym.core.base import BaseNikodymEstimator
from nikodym.core.config import NikodymConfig, config_hash
from nikodym.core.config.schema import RunConfig
from nikodym.core.exceptions import (
    ArtifactNotFoundError,
    ConfigError,
    NikodymError,
    ReproducibilityError,
    UntrustedStudyError,
)
from nikodym.core.mixins import AuditableMixin
from nikodym.core.registry import REGISTRY
from nikodym.core.steps import StepAdapter
from nikodym.core.study import Study


def _config(**run_kwargs: object) -> NikodymConfig:
    return NikodymConfig(run=RunConfig(**run_kwargs)) if run_kwargs else NikodymConfig()


def _minimal_data_dict() -> dict[str, object]:
    """Blob mínimo de ``data`` para cubrir resolución perezosa sin repetir fixtures de data."""
    return {
        "target": {"bad_rule": {"all_of": [{"col": "max_dpd_12m", "op": ">=", "value": 90}]}},
        "partition": {"strategy": {"type": "random"}, "min_bads_per_partition": 0},
    }


# --- Construcción / DoD F0 --------------------------------------------------------------------


def test_study_arranca_en_created() -> None:
    """Un ``Study`` recién construido está en ``created`` con todo lo demás None."""
    study = Study(_config())
    assert study.run_context.status == "created"
    assert study.run_context.run_id is None
    assert study.run_context.lineage is None
    assert study.results == {}


def test_name_override_no_muta_config_original() -> None:
    """``name`` construye un config nuevo (frozen) sin tocar el original."""
    base = _config()
    study = Study(base, name="otro-estudio")
    assert study.config.name == "otro-estudio"
    assert base.name == "nikodym-study"


def test_dod_f0_save_load_round_trip(tmp_path: Path) -> None:
    """DoD F0: un ``Study`` vacío se guarda (sin valores ficticios) y se recarga equivalente."""
    study = Study(_config())
    destino = study.save(tmp_path / "estudio")
    assert (destino / "config.yaml").exists()
    meta = json.loads((destino / "run_metadata.json").read_text(encoding="utf-8"))
    assert meta["status"] == "created"
    assert meta["run_id"] is None and meta["lineage"] is None
    assert not (destino / "lineage.json").exists()  # se omite si no hay lineage
    recargado = Study.load(destino, trust=True)
    assert recargado.run_context.status == "created"
    assert recargado.config.name == study.config.name


# --- run trivial y con pasos (vía seam _resolve_steps) ----------------------------------------


def test_run_trivial(tmp_path: Path) -> None:
    """``run()`` sin pasos → ``done``, lineage poblado y secuencia [run_start, run_end]."""
    study = Study(_config())
    sink = InMemoryAuditSink()
    study.set_audit_sink(sink)
    assert study.run() is study
    assert study.run_context.status == "done"
    assert study.run_context.lineage is not None
    assert study.run_context.lineage.config_hash
    assert [e.kind for e in sink.events] == ["run_start", "run_end"]


def test_run_con_paso_dummy(monkeypatch: pytest.MonkeyPatch) -> None:
    """``run()`` ejecuta un paso (seam monkeypatched): escribe artefacto y emite eventos."""
    study = Study(_config())
    sink = InMemoryAuditSink()
    study.set_audit_sink(sink)

    class _Paso:
        name = "dummy"
        requires: tuple = ()
        provides: tuple = (("dummy", "out"),)

        def execute(self, study: Study, rng: object) -> int:
            study.artifacts.set("dummy", "out", 123)
            return 123

    monkeypatch.setattr(study, "_resolve_steps", lambda nombres: [_Paso()])
    study.run()
    assert study.artifacts.get("dummy", "out") == 123
    kinds = [e.kind for e in sink.events]
    assert kinds[0] == "run_start" and kinds[-1] == "run_end"
    assert "artifact" in kinds


def test_run_fail_fast_true_falla_es_guardable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Una excepción en un paso → ``failed``, ``run_end`` con error, re-levanta; Study guardable."""
    study = Study(_config())
    sink = InMemoryAuditSink()
    study.set_audit_sink(sink)

    class _Boom:
        name = "boom"
        requires: tuple = ()
        provides: tuple = ()

        def execute(self, study: Study, rng: object) -> None:
            raise RuntimeError("explotó el paso")

    monkeypatch.setattr(study, "_resolve_steps", lambda nombres: [_Boom()])
    with pytest.raises(RuntimeError, match="explotó"):
        study.run()
    assert study.run_context.status == "failed"
    assert sink.events[-1].kind == "run_end"
    assert sink.events[-1].payload["status"] == "failed"
    study.save(tmp_path / "parcial")  # el Study parcial es guardable


# --- CT-1: validación de prerequisitos --------------------------------------------------------


class _FanIn:
    """Step con fan-in de dos dominios distintos (criterio de aceptación CT-1)."""

    name = "provisioning"
    requires: tuple = (("binning", "woe"), ("calibration", "pd_calibrada"))
    provides: tuple = ()

    def execute(self, study: Study, rng: object) -> None:
        return None


def test_ct1_prerequisito_faltante_levanta() -> None:
    """CT-1: ``_check_prerequisites`` con un fan-in sin artefactos → ``ArtifactNotFoundError``."""
    study = Study(_config())
    with pytest.raises(ArtifactNotFoundError, match="binning"):
        study._check_prerequisites(_FanIn())


def test_ct1_prerequisito_satisfecho_no_levanta() -> None:
    """CT-1: con los dos artefactos del fan-in presentes, ``_check_prerequisites`` no levanta."""
    study = Study(_config())
    study.artifacts.set("binning", "woe", 1)
    study.artifacts.set("calibration", "pd_calibrada", 2)
    study._check_prerequisites(_FanIn())


def test_ct1_pre_run_global_sin_proveedor() -> None:
    """CT-1 pre-run global: un ``requires`` sin proveedor aguas arriba → ``ConfigError``."""
    study = Study(_config())

    class _Consumidor:
        name = "c"
        requires: tuple = (("up", "k"),)
        provides: tuple = ()

    with pytest.raises(ConfigError, match="inejecutable"):
        study._validate_pipeline([_Consumidor()])


def test_ct1_pre_run_global_con_proveedor() -> None:
    """CT-1 pre-run global: un proveedor aguas arriba satisface al consumidor."""
    study = Study(_config())

    class _Proveedor:
        name = "p"
        requires: tuple = ()
        provides: tuple = (("up", "k"),)

    class _Consumidor:
        name = "c"
        requires: tuple = (("up", "k"),)
        provides: tuple = ()

    study._validate_pipeline([_Proveedor(), _Consumidor()])


# --- fail_fast ruidoso ------------------------------------------------------------------------


def test_fail_fast_false_emite_warning() -> None:
    """``fail_fast=False`` emite un warning ruidoso (no es un no-op silencioso) y procede."""
    study = Study(_config(fail_fast=False))
    with pytest.warns(UserWarning, match="fail_fast=False"):
        study.run()
    assert study.run_context.status == "done"


# --- Resolución de pasos en F0 (diferida) -----------------------------------------------------


def test_run_con_steps_explicitos_difiere() -> None:
    """En F0, ``run(steps=[...])`` con nombres explícitos → ``ConfigError`` (dominios en T2)."""
    with pytest.raises(ConfigError, match="orquestación de dominios"):
        Study(_config()).run(steps=["binning"])


def test_run_step_difiere_en_f0() -> None:
    """En F0, ``run_step(name)`` → ``ConfigError`` (no hay secciones de dominio)."""
    with pytest.raises(ConfigError):
        Study(_config()).run_step("binning")


# --- lineage_bundle ---------------------------------------------------------------------------


def test_lineage_bundle_sin_run_levanta() -> None:
    """``lineage_bundle()`` sobre un Study en ``created`` levanta ``NikodymError``."""
    with pytest.raises(NikodymError, match=r"run\(\)"):
        Study(_config()).lineage_bundle()


def test_lineage_bundle_tras_run() -> None:
    """Tras ``run()``, ``lineage_bundle()`` devuelve el bundle congelado (idempotente)."""
    study = Study(_config()).run()
    bundle = study.lineage_bundle()
    assert bundle.config_hash
    assert study.lineage_bundle() is bundle


# --- set_audit_sink propaga al ArtifactStore --------------------------------------------------


def test_set_audit_sink_propaga_al_store() -> None:
    """El sink inyectado llega al ``ArtifactStore`` (un ``set`` emite ``artifact`` por él)."""
    study = Study(_config())
    sink = InMemoryAuditSink()
    study.set_audit_sink(sink)
    study.artifacts.set("data", "frame", 1)
    assert any(e.kind == "artifact" for e in sink.events)


# --- Persistencia atómica ---------------------------------------------------------------------


def test_save_atomico_no_deja_destino_a_medias(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Si ``save`` falla a mitad, el destino previo queda intacto y no hay temporales colgando."""
    study = Study(_config())
    destino = study.save(tmp_path / "estudio")
    original = (destino / "config.yaml").read_text(encoding="utf-8")

    def _boom(_cfg: object) -> str:
        raise RuntimeError("fallo al volcar config")

    monkeypatch.setattr("nikodym.core.study.dump_config", _boom)
    with pytest.raises(RuntimeError, match="fallo al volcar"):
        study.save(destino)
    assert (destino / "config.yaml").read_text(encoding="utf-8") == original
    assert not list(tmp_path.glob(".estudio.*"))  # sin temporales colgando


# --- load: seguridad y reproducibilidad -------------------------------------------------------


def test_load_trust_false_con_artefactos_rechaza(tmp_path: Path) -> None:
    """``load(trust=False)`` sobre un Study con artefactos → ``UntrustedStudyError``."""
    study = Study(_config())
    study.artifacts.set("data", "frame", [1, 2, 3])
    destino = study.save(tmp_path / "estudio")
    with pytest.raises(UntrustedStudyError, match="trust=True"):
        Study.load(destino)


def test_load_vacio_trust_false_ok(tmp_path: Path) -> None:
    """Un Study sin artefactos se carga con ``trust=False`` (no hay vector pickle)."""
    destino = Study(_config()).save(tmp_path / "estudio")
    assert Study.load(destino, trust=False).run_context.status == "created"


def test_load_config_hash_manipulado_levanta(tmp_path: Path) -> None:
    """Manipular el config guardado (config_hash distinto del lineage) → error reproducibilidad."""
    destino = Study(_config()).run().save(tmp_path / "estudio")
    config_yaml = destino / "config.yaml"
    texto = config_yaml.read_text(encoding="utf-8")
    config_yaml.write_text(texto.replace("seed: 42", "seed: 99"), encoding="utf-8")
    with pytest.raises(ReproducibilityError, match="config_hash"):
        Study.load(destino, trust=True)


def test_load_drift_versiones_advierte(tmp_path: Path) -> None:
    """Una divergencia de versiones de librerías sólo advierte (no aborta)."""
    destino = Study(_config()).run().save(tmp_path / "estudio")
    meta_path = destino / "run_metadata.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["lineage"]["library_versions"]["numpy"] = "0.0.0-fake"
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    with pytest.warns(UserWarning, match="librerías distintas"):
        Study.load(destino, trust=True)


def test_load_reconstruye_seed_manager_equivalente(tmp_path: Path) -> None:
    """El ``seed_manager`` se reconstruye equivalente (mismo root_seed y mismo stream)."""
    study = Study(_config())
    destino = study.save(tmp_path / "estudio")
    recargado = Study.load(destino, trust=True)
    assert recargado.seed_manager.root_seed == study.seed_manager.root_seed
    original = study.seed_manager.generator_for("x").integers(0, 1_000_000, size=5)
    recarga = recargado.seed_manager.generator_for("x").integers(0, 1_000_000, size=5)
    assert list(original) == list(recarga)


# --- Cobertura de rutas reales diferidas en F0 ------------------------------------------------


def test_run_step_ejecuta_via_seam(monkeypatch: pytest.MonkeyPatch) -> None:
    """``run_step`` ejecuta el paso y devuelve su resultado sin alterar ``status``."""
    study = Study(_config())

    class _Paso:
        name = "x"
        requires: tuple = ()
        provides: tuple = ()

        def execute(self, study: Study, rng: object) -> str:
            return "ok"

    monkeypatch.setattr(study, "_resolve_steps", lambda nombres: [_Paso()])
    assert study.run_step("x") == "ok"
    assert study.run_context.status == "created"


def test_run_inyecta_sink_en_paso_auditable(monkeypatch: pytest.MonkeyPatch) -> None:
    """``_run_one`` inyecta el sink en un paso ``AuditableMixin`` (su ``log_decision`` lo usa)."""
    study = Study(_config())
    sink = InMemoryAuditSink()
    study.set_audit_sink(sink)

    class _PasoAuditable(AuditableMixin):
        name = "auditable"
        requires: tuple = ()
        provides: tuple = ()

        def execute(self, study: Study, rng: object) -> None:
            self.log_decision(regla="r", umbral=1, valor=0, accion="a")

    monkeypatch.setattr(study, "_resolve_steps", lambda nombres: [_PasoAuditable()])
    study.run()
    assert any(e.kind == "decision" for e in sink.events)


def test_component_type_dict_default_y_tipo_invalido() -> None:
    """El resolver lee ``type`` desde dict opaco y rechaza discriminadores no textuales."""
    assert study_mod._component_type({}) == "standard"
    with pytest.raises(ConfigError, match="discriminador"):
        study_mod._component_type({"type": 123})


def test_resolve_step_componente_sin_from_config_levanta(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Un registro sin ``from_config`` falla con diagnóstico explícito."""
    import nikodym.data

    class _NoFactory:
        """Clase registrada inválida para cubrir el error del seam dinámico."""

    study = Study(NikodymConfig(data=nikodym.data.DataConfig.model_validate(_minimal_data_dict())))
    monkeypatch.setattr(REGISTRY, "resolve", lambda _domain, _name: _NoFactory)

    with pytest.raises(ConfigError, match="no expone from_config"):
        study._resolve_step("data")


def test_resolve_step_adapta_estimador_base(monkeypatch: pytest.MonkeyPatch) -> None:
    """Un ``BaseNikodymEstimator`` registrado se envuelve en ``StepAdapter``."""
    import nikodym.data

    class _Estimator(BaseNikodymEstimator):
        """Estimador mínimo para cubrir la rama de adaptación."""

        @classmethod
        def from_config(cls, cfg: object) -> _Estimator:
            return cls()

    study = Study(NikodymConfig(data=nikodym.data.DataConfig.model_validate(_minimal_data_dict())))
    monkeypatch.setattr(REGISTRY, "resolve", lambda _domain, _name: _Estimator)

    step = study._resolve_step("data")

    assert isinstance(step, StepAdapter)
    assert step.name == "data"
    assert step.estimator.__class__ is _Estimator


def test_resolve_step_rechaza_objeto_no_adaptable(monkeypatch: pytest.MonkeyPatch) -> None:
    """Un componente que no es ``Step`` ni estimador base falla de forma ruidosa."""
    import nikodym.data

    class _NoAdaptable:
        """Componente inválido con factory válida pero sin contrato orquestable."""

        @classmethod
        def from_config(cls, cfg: object) -> object:
            return object()

    study = Study(NikodymConfig(data=nikodym.data.DataConfig.model_validate(_minimal_data_dict())))
    monkeypatch.setattr(REGISTRY, "resolve", lambda _domain, _name: _NoAdaptable)

    with pytest.raises(ConfigError, match="no implementa Step"):
        study._resolve_step("data")


def test_registro_y_coercion_perezosa_cubren_dominios_no_data() -> None:
    """El import perezoso sólo actúa en data; la coerción convierte blobs dict de data."""
    study = Study(_config())
    study._ensure_domain_registered("binning")
    sentinel = object()
    assert study._coerce_domain_config("binning", sentinel) is sentinel

    coerced = study._coerce_domain_config("data", _minimal_data_dict())

    import nikodym.data

    assert isinstance(coerced, nikodym.data.DataConfig)
    assert study.config.data is coerced


def test_save_sobre_existente_reescribe(tmp_path: Path) -> None:
    """Re-guardar sobre un directorio existente lo reemplaza por el nuevo Study."""
    study = Study(NikodymConfig(name="primero"))
    destino = tmp_path / "estudio"
    study.save(destino)
    Study(NikodymConfig(name="segundo")).save(destino)
    assert (destino / "config.yaml").exists()
    assert Study.load(destino, trust=True).config.name == "segundo"


def test_save_usa_respaldo_inexistente_al_sobrescribir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """El respaldo lateral se crea como ruta inexistente antes de ``os.replace``."""
    destino = Study(_config()).save(tmp_path / "estudio")
    real = study_mod.os.replace

    def _assert_respaldo_inexistente(src: object, dst: object) -> None:
        if src == destino:
            assert ".old." in str(dst)
            assert not Path(dst).exists()
        real(src, dst)

    monkeypatch.setattr(study_mod.os, "replace", _assert_respaldo_inexistente)
    Study(NikodymConfig(name="nuevo")).save(destino)
    assert Study.load(destino, trust=True).config.name == "nuevo"


def test_save_reintenta_replace_transitorio(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Un ``PermissionError`` transitorio en ``os.replace`` se reintenta y termina verde."""
    destino = tmp_path / "estudio"
    real = study_mod.os.replace
    calls = 0

    def _flaky_replace(src: object, dst: object) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise PermissionError("handle transitorio")
        real(src, dst)

    monkeypatch.setattr(study_mod.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(study_mod.os, "replace", _flaky_replace)

    Study(_config()).save(destino)

    assert calls == 2
    assert (destino / "config.yaml").exists()


def test_save_reintentos_agotados_limpia_tmp(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Si el lock persiste, ``save`` falla sin dejar destino parcial ni temporales."""
    destino = tmp_path / "estudio"
    calls = 0

    def _locked_replace(_src: object, _dst: object) -> None:
        nonlocal calls
        calls += 1
        raise PermissionError("handle retenido")

    monkeypatch.setattr(study_mod.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(study_mod.os, "replace", _locked_replace)

    with pytest.raises(PermissionError, match="handle retenido"):
        Study(_config()).save(destino)

    assert calls == study_mod._REPLACE_RETRY_ATTEMPTS
    assert not destino.exists()
    assert not list(tmp_path.glob(".estudio.*"))


def test_load_con_artefactos_trust_true(tmp_path: Path) -> None:
    """``load(trust=True)`` recarga los artefactos joblib del *store*."""
    study = Study(_config())
    study.artifacts.set("data", "frame", [1, 2, 3])
    destino = study.save(tmp_path / "estudio")
    recargado = Study.load(destino, trust=True)
    assert recargado.artifacts.get("data", "frame") == [1, 2, 3]


def test_load_corrido_sin_drift_no_advierte(tmp_path: Path) -> None:
    """Recargar un Study corrido con versiones intactas no advierte (rama sin drift)."""
    destino = Study(_config()).run().save(tmp_path / "estudio")
    recargado = Study.load(destino, trust=True)
    assert recargado.run_context.status == "done"


def test_build_lineage_sin_git_es_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """Si ``git`` no está disponible, el lineage registra ``git_sha=None``/``git_dirty=False``."""

    def _falla(*args: object, **kwargs: object) -> object:
        raise OSError("git ausente")

    monkeypatch.setattr("subprocess.run", _falla)
    bundle = Study(_config())._build_lineage()
    assert bundle.git_sha is None
    assert bundle.git_dirty is False


def test_versiones_omite_librerias_no_instaladas(monkeypatch: pytest.MonkeyPatch) -> None:
    """Una librería ausente se omite del lineage (``PackageNotFoundError``)."""
    real = study_mod.metadata.version

    def _fake(libreria: str) -> str:
        if libreria == "numpy":
            raise study_mod.metadata.PackageNotFoundError(libreria)
        return real(libreria)

    monkeypatch.setattr(study_mod.metadata, "version", _fake)
    versiones = study_mod._versiones_librerias()
    assert "numpy" not in versiones
    assert "pydantic" in versiones


# --- Revisión adversarial B1c: lineage, atomicidad, git -------------------------------------


def _fake_git(sha: str, porcelain: str):  # type: ignore[no-untyped-def]
    """Devuelve un sustituto de ``subprocess.run`` que simula git con SHA y estado dados."""

    def run(cmd: list[str], **kwargs: object) -> object:
        salida = sha if "rev-parse" in cmd else porcelain

        class _Resultado:
            stdout = salida

        return _Resultado()

    return run


def test_estado_git_parsea_sha_y_estado(monkeypatch: pytest.MonkeyPatch) -> None:
    """``_estado_git`` parsea el SHA y deriva ``git_dirty`` del porcelain (ramas limpia/sucia)."""
    monkeypatch.setattr("subprocess.run", _fake_git("a" * 40, ""))
    assert study_mod._estado_git() == ("a" * 40, False)
    monkeypatch.setattr("subprocess.run", _fake_git("b" * 40, " M archivo.py"))
    assert study_mod._estado_git() == ("b" * 40, True)


def test_versiones_lineage_completas() -> None:
    """Las 5 librerías del lineage resuelven (un typo en la lista rompería esto)."""
    assert set(study_mod._versiones_librerias()) == {
        "nikodym",
        "numpy",
        "pandas",
        "pydantic",
        "PyYAML",
    }


def test_lineage_campos_completos(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tras un run real, el bundle congelado tiene todos sus campos poblados correctamente."""
    monkeypatch.setattr(study_mod, "_estado_git", lambda: ("a" * 40, False))
    study = Study(_config()).run()
    bundle = study.lineage_bundle()
    assert bundle.root_seed == 42
    assert bundle.schema_version == study.config.schema_version
    assert bundle.config_hash == config_hash(study.config)
    assert set(bundle.library_versions) == {"nikodym", "numpy", "pandas", "pydantic", "PyYAML"}
    assert bundle.git_sha == "a" * 40
    assert bundle.git_dirty is False
    assert bundle.created_at.tzinfo is not None
    assert bundle.determinism_caveats == []


def test_git_dirty_genera_caveat(monkeypatch: pytest.MonkeyPatch) -> None:
    """Un working tree sucio añade un caveat de no-reproducibilidad al lineage (SDD §8/§9)."""
    monkeypatch.setattr(study_mod, "_estado_git", lambda: ("a" * 40, True))
    bundle = Study(_config())._build_lineage()
    assert any("sucio" in c for c in bundle.determinism_caveats)


def test_git_ausente_genera_caveat(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sin git, el lineage registra un caveat de SHA ausente."""
    monkeypatch.setattr(study_mod, "_estado_git", lambda: (None, False))
    bundle = Study(_config())._build_lineage()
    assert any("git no disponible" in c for c in bundle.determinism_caveats)


def test_lineage_persiste_en_run_fallido(monkeypatch: pytest.MonkeyPatch) -> None:
    """Una corrida fallida conserva el lineage (evidencia regulatoria; invariante post-run §6)."""
    study = Study(_config())

    class _Boom:
        name = "boom"
        requires: tuple = ()
        provides: tuple = ()

        def execute(self, study: Study, rng: object) -> None:
            raise RuntimeError("explotó")

    monkeypatch.setattr(study, "_resolve_steps", lambda nombres: [_Boom()])
    with pytest.raises(RuntimeError, match="explotó"):
        study.run()
    assert study.run_context.status == "failed"
    assert study.run_context.lineage is not None
    assert study.run_context.lineage.config_hash == config_hash(study.config)


def test_save_swap_falla_restaura_previo(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Si el swap final falla al sobrescribir, el estudio previo queda intacto (no se pierde)."""
    study = Study(_config())
    destino = study.save(tmp_path / "estudio")
    original = (destino / "config.yaml").read_text(encoding="utf-8")
    real = study_mod.os.replace

    def _falla_en_tmp(src: object, dst: object) -> None:
        if ".tmp" in str(src):
            raise RuntimeError("crash en swap")
        real(src, dst)

    monkeypatch.setattr(study_mod.os, "replace", _falla_en_tmp)
    with pytest.raises(RuntimeError, match="crash en swap"):
        study.save(destino)
    assert (destino / "config.yaml").read_text(encoding="utf-8") == original


def test_save_swap_falla_destino_nuevo(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Si el swap falla guardando en un destino nuevo, no queda un directorio a medias."""
    study = Study(_config())
    destino = tmp_path / "nuevo"

    def _falla(src: object, dst: object) -> None:
        raise RuntimeError("crash")

    monkeypatch.setattr(study_mod.os, "replace", _falla)
    with pytest.raises(RuntimeError, match="crash"):
        study.save(destino)
    assert not destino.exists()


def test_save_apartado_respaldo_falla(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Si falla apartar el destino previo al respaldo, el estudio previo queda intacto."""
    study = Study(_config())
    destino = study.save(tmp_path / "estudio")
    original = (destino / "config.yaml").read_text(encoding="utf-8")
    real = study_mod.os.replace

    def _falla_al_apartar(src: object, dst: object) -> None:
        if ".old." in str(dst):  # mover destino → respaldo
            raise RuntimeError("crash al apartar")
        real(src, dst)

    monkeypatch.setattr(study_mod.os, "replace", _falla_al_apartar)
    with pytest.raises(RuntimeError, match="crash al apartar"):
        study.save(destino)
    assert (destino / "config.yaml").read_text(encoding="utf-8") == original
