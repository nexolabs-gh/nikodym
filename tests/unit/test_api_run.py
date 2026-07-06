"""Tests de ``nikodym.run`` (API pública mínima, SDD-23 §4.1) + export perezoso por capas (B23.1).

Cubre: (a) contrato de ``run`` (éxito → ``status="done"``; fallo → ``Study`` con ``status="failed"``
+ lineage, sin excepción propagada; publicación de inventario solo en éxito y solo si
``publish_to_inventory``), y (b) el **núcleo liviano por capas** verificado con snapshots de
``sys.modules`` en subprocesos limpios (tiers import → acceso a ``run`` → invoke).
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

import nikodym.api as api_module
from nikodym.audit import AuditConfig, JsonlAuditSink
from nikodym.binning.config import BinningConfig
from nikodym.calibration.config import CalibrationConfig
from nikodym.core.audit import AuditSink, FanOutSink, InMemoryAuditSink, NullAuditSink
from nikodym.core.config import NikodymConfig, ReproConfig
from nikodym.data.config import (
    CohortSplitConfig,
    ColumnSpec,
    DataConfig,
    LoadingConfig,
    PartitionConfig,
    Predicate,
    Rule,
    SchemaConfig,
    TargetConfig,
)
from nikodym.governance import GovernanceConfig, InventoryEntry, ModelInventory
from nikodym.governance.inventory import InventoryRecord
from nikodym.governance.model_card import ModelCard
from nikodym.model.config import IvContributionConfig, ModelConfig, SignPolicyConfig, StepwiseConfig
from nikodym.scorecard.config import ScorecardConfig
from nikodym.selection.config import (
    CorrelationSelectionConfig,
    SelectionConfig,
    StabilitySelectionConfig,
    VifSelectionConfig,
)

ROOT_SEED = 20_240_628


# ─────────────────────────────── fixtures y helpers ───────────────────────────────


@pytest.fixture(autouse=True)
def _usar_fake_binning_process(fake_binning_process: object) -> None:
    """Evita OR-Tools dentro del proceso pytest para los tests in-process con binning."""
    del fake_binning_process


def _raw_frame() -> pd.DataFrame:
    """Dataset crudo estable (30 filas) compartido con el smoke end-to-end de scoring."""
    index = pd.Index([f"op-{position:03d}" for position in range(30)], name="loan_id")
    score = [
        0,
        0,
        1,
        1,
        2,
        2,
        3,
        3,
        0,
        1,
        2,
        3,
        0,
        1,
        2,
        3,
        0,
        1,
        2,
        3,
        0,
        1,
        2,
        3,
        0,
        1,
        2,
        3,
        1,
        2,
    ]
    segment = [
        "A",
        "B",
        "A",
        "B",
        "A",
        "B",
        "A",
        "B",
        "Z",
        "A",
        "B",
        "Z",
        "A",
        "Z",
        "A",
        "B",
        "B",
        "Z",
        "A",
        "Z",
        "A",
        "B",
        "Z",
        "A",
        "B",
        "Z",
        "A",
        "B",
        "Z",
        "A",
    ]
    bad = [1, 0, 1, 0, 0, 1, 0, 1, 0, 1, 0, 0, 1, 0, 1, 0, 0, 1, 0, 1, 1, 0, 1, 0, 0, 1, 0, 1, 0, 1]
    cohort = ["dev"] * 24 + ["oot"] * 6
    return pd.DataFrame(
        {"score": score, "segment": segment, "bad_flag": bad, "cohort": cohort}, index=index
    )


def _write_parquet(path: Path) -> None:
    """Materializa el dataset crudo a parquet preservando el índice ``loan_id``."""
    _raw_frame().to_parquet(path)


def _data_config(*, source: str | None) -> DataConfig:
    """Config de datos F1; ``source=None`` fuerza el fallo "sin fuente de datos"."""
    return DataConfig(
        load=LoadingConfig(source=source),
        schema_=SchemaConfig(
            columns=(
                ColumnSpec(name="score", dtype="int", nullable=False),
                ColumnSpec(name="segment", dtype="str", nullable=False),
                ColumnSpec(name="bad_flag", dtype="int", nullable=False),
                ColumnSpec(name="cohort", dtype="str", nullable=False),
            ),
            index_col="loan_id",
        ),
        target=TargetConfig(bad_rule=Rule(all_of=(Predicate(col="bad_flag", op="==", value=1),))),
        partition=PartitionConfig(
            strategy=CohortSplitConfig(
                cohort_col="cohort", oot_cohorts=("oot",), holdout_fraction=0.20
            ),
            min_bads_per_partition=0,
        ),
    )


def _full_f1_config(source: str, **overrides: Any) -> NikodymConfig:
    """Config F1 completa data→binning→selection→model→scorecard→calibration desde parquet."""
    return NikodymConfig(
        repro=ReproConfig(seed=ROOT_SEED),
        data=_data_config(source=source),
        binning=BinningConfig(
            feature_columns=("score", "segment"),
            categorical_columns=("segment",),
            solver="mip",
            max_n_prebins=4,
            max_n_bins=4,
            min_bin_size=0.1,
            time_limit=5,
            monotonic_trend=None,
        ),
        selection=SelectionConfig(
            min_iv=0.0,
            correlation=CorrelationSelectionConfig(enabled=False),
            vif=VifSelectionConfig(enabled=False),
            stability=StabilitySelectionConfig(enabled=False),
        ),
        model=ModelConfig(
            stepwise=StepwiseConfig(direction="none"),
            sign_policy=SignPolicyConfig(action="flag", fail_on_forced_inverted=False),
            iv_contribution=IvContributionConfig(action="flag"),
        ),
        scorecard=ScorecardConfig(rounding_method="none"),
        calibration=CalibrationConfig(
            target_pd=0.31, anchor_source="business_input", min_fit_rows=1
        ),
        **overrides,
    )


class _SpyInventory:
    """Doble de ``ModelInventory`` que registra las entradas recibidas (verifica la publicación)."""

    def __init__(self) -> None:
        """Inicializa el registro de entradas capturadas."""
        self.entries: list[InventoryEntry] = []

    def register(self, entry: InventoryEntry) -> str:
        """Captura la entrada y devuelve un identificador de versión ficticio."""
        self.entries.append(entry)
        return f"v{len(self.entries)}"

    def get_active(self, model_name: str) -> InventoryRecord | None:
        """Sin backend real: no hay versión activa."""
        del model_name
        return None

    def list_versions(self, model_name: str) -> list[InventoryRecord]:
        """Sin backend real: no hay versiones."""
        del model_name
        return []


def _patch_assemble(
    monkeypatch: pytest.MonkeyPatch, *, sink: AuditSink, inventory: ModelInventory
) -> None:
    """Reemplaza ``assemble_run`` para inyectar un sink y un inventario espía (sin extra mlflow)."""

    def fake_assemble(config: NikodymConfig) -> tuple[AuditSink, ModelInventory]:
        del config
        return sink, inventory

    monkeypatch.setattr(api_module, "assemble_run", fake_assemble)


# ─────────────────────────────── contrato de run ───────────────────────────────


def test_run_exito_devuelve_study_done_con_artefactos(tmp_path: Path) -> None:
    """``run`` de una corrida F1 completa devuelve el ``Study`` con ``status="done"``."""
    parquet = tmp_path / "cartera.parquet"
    _write_parquet(parquet)

    study = api_module.run(_full_f1_config(str(parquet)))

    assert study.run_context.status == "done"
    assert study.artifacts.has("calibration", "result")
    assert study.run_context.lineage is not None


def test_run_fallo_devuelve_study_failed_con_lineage_sin_relanzar() -> None:
    """Un paso que falla deja ``status="failed"`` + lineage y NO propaga la excepción (D-UI-2)."""
    # data.load.source=None y sin frame inyectado → DataStep levanta ConfigError (NikodymError).
    config = NikodymConfig(data=_data_config(source=None))

    study = api_module.run(config)  # no debe relanzar

    assert study.run_context.status == "failed"
    assert study.run_context.lineage is not None  # evidencia conservada en el fallo


def test_run_publica_inventario_solo_en_exito(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """En éxito con ``publish_to_inventory`` se registra UNA entrada bien formada."""
    parquet = tmp_path / "cartera.parquet"
    _write_parquet(parquet)
    trail = tmp_path / "trail.jsonl"
    audit_cfg = AuditConfig(enabled=True, trail_filename=str(trail))
    governance = GovernanceConfig(
        model_name="scoring-f1",
        purpose="Scorecard de comportamiento F1",
        cartera="consumo",
        motor="scoring",
        fase="F1",
        author="qa@nexolabs.cl",
        publish_to_inventory=True,
    )
    spy = _SpyInventory()
    _patch_assemble(monkeypatch, sink=JsonlAuditSink(trail, config=audit_cfg), inventory=spy)

    config = _full_f1_config(str(parquet), audit=audit_cfg, governance=governance)
    study = api_module.run(config)

    assert study.run_context.status == "done"
    assert len(spy.entries) == 1
    entry = spy.entries[0]
    assert entry.model_name == "scoring-f1"
    assert entry.run_id == study.run_context.run_id
    assert isinstance(entry.model_card, ModelCard)
    # La ancla de idempotencia (model_name, config_hash) viaja completa en la entrada.
    assert entry.config_hash == entry.model_card.config_hash
    assert entry.config_hash == study.lineage_bundle().config_hash
    # Los tags nikodym.* documentados en GovernanceConfig viajan en la entrada.
    assert entry.tags == {
        "nikodym.estado_validacion": "desarrollo",
        "nikodym.cartera": "consumo",
        "nikodym.motor": "scoring",
        "nikodym.fase": "F1",
        "nikodym.autor": "qa@nexolabs.cl",
    }


def test_run_no_publica_en_fallo(monkeypatch: pytest.MonkeyPatch) -> None:
    """Con ``publish_to_inventory`` pero corrida fallida NO se registra nada."""
    governance = GovernanceConfig(purpose="F1", publish_to_inventory=True)
    spy = _SpyInventory()
    _patch_assemble(monkeypatch, sink=NullAuditSink(), inventory=spy)

    config = NikodymConfig(data=_data_config(source=None), governance=governance)
    study = api_module.run(config)

    assert study.run_context.status == "failed"
    assert spy.entries == []  # un modelo fallido no entra al inventario


def test_run_no_publica_si_publish_to_inventory_false(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Con ``publish_to_inventory=False`` no se registra aunque la corrida tenga éxito."""
    parquet = tmp_path / "cartera.parquet"
    _write_parquet(parquet)
    governance = GovernanceConfig(purpose="F1", publish_to_inventory=False)
    spy = _SpyInventory()
    _patch_assemble(monkeypatch, sink=NullAuditSink(), inventory=spy)

    config = _full_f1_config(str(parquet), governance=governance)
    study = api_module.run(config)

    assert study.run_context.status == "done"
    assert spy.entries == []


def test_run_publica_sin_audit_construye_card_parcial(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Con ``publish`` pero sin audit habilitado: la ModelCard es parcial (sin trail) y publica."""
    parquet = tmp_path / "cartera.parquet"
    _write_parquet(parquet)
    governance = GovernanceConfig(purpose="F1", publish_to_inventory=True)  # cartera/motor/… = None
    spy = _SpyInventory()
    _patch_assemble(monkeypatch, sink=NullAuditSink(), inventory=spy)

    config = _full_f1_config(str(parquet), governance=governance)  # sin audit → trail_path=None
    with pytest.warns(UserWarning, match="trail no disponible"):
        study = api_module.run(config)

    assert study.run_context.status == "done"
    assert len(spy.entries) == 1
    # Sin cartera/motor/fase/autor, solo viaja el tag de estado (default "desarrollo").
    assert spy.entries[0].tags == {"nikodym.estado_validacion": "desarrollo"}


def test_run_cierra_los_sinks_de_un_fanout(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """``run`` cierra los sumideros hijos de un ``FanOutSink`` (no fuga el descriptor del JSONL)."""
    trail = tmp_path / "trail.jsonl"
    audit_cfg = AuditConfig(enabled=True, trail_filename=str(trail))
    inner = JsonlAuditSink(trail, config=audit_cfg)
    fan = FanOutSink([inner, InMemoryAuditSink()])
    _patch_assemble(monkeypatch, sink=fan, inventory=_SpyInventory())

    # Corrida que falla (sin fuente de datos): igual debe cerrar el sink compuesto.
    study = api_module.run(NikodymConfig(data=_data_config(source=None)))

    assert study.run_context.status == "failed"
    assert inner._handle is None  # el JsonlAuditSink hijo quedó cerrado (recursión de cierre)


def test_nikodym_run_accesible_perezoso_desde_paquete_raiz() -> None:
    """``nikodym.run`` (export perezoso) es la misma función pública que ``nikodym.api.run``."""
    import nikodym

    assert nikodym.run is api_module.run
    assert nikodym.assemble_run is api_module.assemble_run
    assert {"run", "assemble_run"} <= set(dir(nikodym))  # __dir__ expone los símbolos perezosos
    with pytest.raises(AttributeError):
        _ = nikodym.simbolo_inexistente  # __getattr__ rechaza nombres no perezosos


# ─────────────────── núcleo liviano por capas (snapshots de sys.modules) ───────────────────


def test_import_nikodym_liviano_y_export_perezoso_por_capas() -> None:
    """Subproceso limpio: ``import nikodym`` no arrastra api/stack; acceder ``run`` sí, sin ML."""
    code = textwrap.dedent(
        """
        import sys
        import nikodym

        # Tier 1: import nikodym no arrastra la capa api ni su stack (audit/governance/tracking).
        assert nikodym.__version__
        for m in ("nikodym.api", "nikodym.audit", "nikodym.governance", "nikodym.tracking",
                  "fastapi"):
            assert m not in sys.modules, "tier1 fuga: " + m

        # Tier 2: acceder nikodym.run importa api + audit/governance/tracking, pero NO fastapi,
        # NO pandas y NO el stack ML de dominio.
        run = nikodym.run
        assert callable(run)
        assert callable(nikodym.assemble_run)
        for m in ("nikodym.api", "nikodym.audit", "nikodym.governance", "nikodym.tracking"):
            assert m in sys.modules, "tier2 falta: " + m
        for m in ("fastapi", "optbinning", "sklearn", "pandas", "nikodym.data", "nikodym.binning"):
            assert m not in sys.modules, "tier2 fuga: " + m

        print("ok")
        """
    )
    completed = subprocess.run(
        [sys.executable, "-c", code],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert completed.returncode == 0, completed.stderr + completed.stdout
    assert completed.stdout.strip() == "ok"


def test_invoke_run_carga_el_stack_de_computo_de_dominio(tmp_path: Path) -> None:
    """Subproceso limpio: ``import nikodym`` NO carga el dominio; invocar ``run`` sí lo carga.

    Marcadores ortools-safe: el paso de datos importa ``nikodym.data``/``pandas``. NO se usa
    ``optbinning`` como marcador porque importar OR-Tools segfaultea en algunas plataformas y la
    suite entera fakea el binning; que el stack ML tampoco viaje con el *acceso* a ``run`` se
    verifica por AUSENCIA en :func:`test_import_nikodym_liviano_y_export_perezoso_por_capas`.
    """
    parquet = tmp_path / "cartera.parquet"
    _write_parquet(parquet)
    script = tmp_path / "tier3.py"
    script.write_text(
        textwrap.dedent(
            """
            import sys
            import nikodym

            run = nikodym.run
            # Tras acceder a run, el stack de cómputo/dominio NO está cargado (frontera perezosa).
            for m in ("nikodym.data", "pandas", "optbinning", "sklearn"):
                assert m not in sys.modules, "fuga tras acceso: " + m

            from nikodym.core.config import NikodymConfig, ReproConfig
            from nikodym.data.config import (
                CohortSplitConfig, ColumnSpec, DataConfig, LoadingConfig,
                PartitionConfig, Predicate, Rule, SchemaConfig, TargetConfig,
            )

            cfg = NikodymConfig(
                repro=ReproConfig(seed=20240628),
                data=DataConfig(
                    load=LoadingConfig(source=sys.argv[1]),
                    schema_=SchemaConfig(
                        columns=(
                            ColumnSpec(name="score", dtype="int", nullable=False),
                            ColumnSpec(name="segment", dtype="str", nullable=False),
                            ColumnSpec(name="bad_flag", dtype="int", nullable=False),
                            ColumnSpec(name="cohort", dtype="str", nullable=False),
                        ),
                        index_col="loan_id",
                    ),
                    target=TargetConfig(
                        bad_rule=Rule(all_of=(Predicate(col="bad_flag", op="==", value=1),))
                    ),
                    partition=PartitionConfig(
                        strategy=CohortSplitConfig(
                            cohort_col="cohort", oot_cohorts=("oot",), holdout_fraction=0.20
                        ),
                        min_bads_per_partition=0,
                    ),
                ),
            )

            study = nikodym.run(cfg)  # invocar corre el pipeline y carga el stack de cómputo
            assert study.run_context.status == "done", study.run_context.status
            for m in ("nikodym.data", "pandas"):
                assert m in sys.modules, "no cargó el stack de cómputo al invocar: " + m
            print("ok")
            """
        )
    )
    completed = subprocess.run(
        [sys.executable, str(script), str(parquet)],
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert completed.returncode == 0, completed.stderr + completed.stdout
    assert completed.stdout.strip() == "ok"
