"""Paso orquestable de la capa ``data`` (SDD-02 §4/§7; CT-1).

``DataStep`` implementa el :class:`~nikodym.core.steps.Step` nativo del dominio ``data``:
carga/valida el dataset, normaliza special values, deriva el target, particiona, calcula
``data_hash`` y publica los artefactos namespaced que consumen las capas posteriores.

**Estable (SemVer 1.x).**
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Final

import numpy as np
import pandas as pd

from nikodym.core.exceptions import ConfigError
from nikodym.core.mixins import AuditableMixin
from nikodym.core.registry import register
from nikodym.core.steps import ArtifactKey
from nikodym.data.card import DataCardSection
from nikodym.data.config import DataConfig
from nikodym.data.hashing import data_hash
from nikodym.data.loading import DataLoader, DataSource
from nikodym.data.partition import Partitioner, PartitionResult
from nikodym.data.schema import SchemaValidator
from nikodym.data.special import MaskedFrame, SpecialValuePolicy
from nikodym.data.target import LabeledFrame, TargetDefinition

if TYPE_CHECKING:
    from nikodym.core.study import Study

__all__ = ["DATA_ARTIFACTS", "INPUT_FRAME_KEY", "DataStep"]

DATA_ARTIFACTS: Final[tuple[str, ...]] = (
    "frame",
    "splits",
    "labels",
    "special",
    "data_hash",
    "data_card",
)
INPUT_FRAME_KEY: Final = "input_frame"
_IN_MEMORY_SOURCE_LABEL: Final = "<dataframe>"


@register("standard", domain="data")
class DataStep(AuditableMixin):
    """Orquesta la secuencia canónica de datos y publica artefactos ``domain='data'``."""

    name: str = "data"
    requires: tuple[ArtifactKey, ...] = ()
    provides: tuple[ArtifactKey, ...] = tuple(("data", key) for key in DATA_ARTIFACTS)

    def __init__(self, config: DataConfig) -> None:
        """Construye el paso desde la sección ``DataConfig`` ya validada."""
        self.config = config

    @classmethod
    def from_config(cls, cfg: DataConfig) -> DataStep:
        """Construye ``DataStep`` desde ``NikodymConfig.data``."""
        return cls(cfg)

    def execute(self, study: Study, rng: np.random.Generator) -> PartitionResult:
        """Ejecuta load → schema → special → target → partition → hash → artefactos."""
        source = self._resolve_load_source(study)
        df = DataLoader.from_config(self.config.load).load(source, audit=self._audit)
        validated = SchemaValidator.from_config(self.config.schema_).validate(df, audit=self._audit)
        masked = SpecialValuePolicy.from_config(self.config.missing).apply(
            validated, audit=self._audit
        )
        labeled = TargetDefinition.from_config(self.config.target).apply(
            masked.frame, audit=self._audit
        )
        result = Partitioner.from_config(self.config.partition).split(
            labeled,
            root_seed=study.seed_manager.root_seed,
            rng=rng,
            audit=self._audit,
        )
        digest = data_hash(result.frame)
        self._update_lineage(study, digest)
        data_card = self._build_data_card(
            masked=masked, labeled=labeled, result=result, digest=digest
        )
        self._publish_artifacts(
            study=study,
            result=result,
            labeled=labeled,
            masked=masked,
            digest=digest,
            data_card=data_card,
        )
        return result

    def _resolve_load_source(self, study: Study) -> DataSource | None:
        """Resuelve la fuente para ``DataLoader`` sin convertir rutas en dependencia del core."""
        if self.config.load.source is not None:
            return None
        if study.artifacts.has("data", INPUT_FRAME_KEY):
            source = study.artifacts.get("data", INPUT_FRAME_KEY)
            if isinstance(source, pd.DataFrame):
                return source
            raise ConfigError(
                "El artefacto ('data', 'input_frame') debe ser un pandas.DataFrame para "
                "inyectar datos en memoria."
            )
        raise ConfigError(
            "DataStep no tiene fuente de datos: declare data.load.source o inyecte un "
            "DataFrame en study.artifacts bajo ('data', 'input_frame')."
        )

    def _update_lineage(self, study: Study, digest: str) -> None:
        """Completa ``LineageBundle.data_hash`` cuando el run ya inició el lineage."""
        if study.run_context.lineage is not None:
            study.run_context.lineage.data_hash = digest

    def _build_data_card(
        self,
        *,
        masked: MaskedFrame,
        labeled: LabeledFrame,
        result: PartitionResult,
        digest: str,
    ) -> DataCardSection:
        """Construye el resumen de datos con los campos exactos de SDD-02 §4."""
        summary = labeled.summary
        window = self.config.target.window
        return DataCardSection(
            source=_source_label(self.config.load.source),
            n_rows=len(result.frame.index),
            n_features=len(masked.frame.columns),
            target_col=labeled.target_col,
            bad_rate=summary.bad_rate,
            class_counts=summary.class_counts,
            partition_sizes=result.sizes,
            partition_bad_rates=result.bad_rates,
            performance_window_months=window.months if window is not None else None,
            exclusions_by_reason=summary.exclusions_by_reason,
            data_hash=digest,
        )

    def _publish_artifacts(
        self,
        *,
        study: Study,
        result: PartitionResult,
        labeled: LabeledFrame,
        masked: MaskedFrame,
        digest: str,
        data_card: DataCardSection,
    ) -> None:
        """Publica los seis artefactos estables del dominio ``data``."""
        study.artifacts.set("data", "frame", result.frame)
        study.artifacts.set("data", "splits", result)
        study.artifacts.set("data", "labels", labeled)
        study.artifacts.set("data", "special", masked)
        study.artifacts.set("data", "data_hash", digest)
        study.artifacts.set("data", "data_card", data_card)


def _source_label(source: str | None) -> str:
    """Normaliza la fuente al basename; para DataFrame en memoria usa una etiqueta explícita."""
    if source is None:
        return _IN_MEMORY_SOURCE_LABEL
    return Path(source).name
