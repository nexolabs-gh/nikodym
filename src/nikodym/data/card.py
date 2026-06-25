"""Sección de datos para el model card (SDD-02 §4; consumida por SDD-03).

``DataCardSection`` resume la población que entró al experimento: fuente normalizada, conteos de
target, particiones, exclusiones y ``data_hash``. La construcción vive en ``DataStep`` porque allí
coexisten ``TargetSummary``, ``PartitionResult`` y ``DataConfig``; gobernanza solo lee el artefacto
``("data", "data_card")``.

**Experimental (SemVer 0.x).**
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

__all__ = ["DataCardSection"]


class DataCardSection(BaseModel):
    """Resumen auditable del dataset de entrada para el model card."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    source: str
    n_rows: int
    n_features: int
    target_col: str
    bad_rate: float
    class_counts: dict[str, int]
    partition_sizes: dict[str, int]
    partition_bad_rates: dict[str, float]
    performance_window_months: int | None
    exclusions_by_reason: dict[str, int]
    data_hash: str
