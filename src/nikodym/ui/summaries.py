"""Los resúmenes por etapa y el resumen final de una corrida de la interfaz (D-FLU-8, D-SC-12).

La pestaña Resultados consume **la misma fuente** que ``Scorecard.summary()``: los constructores
de :mod:`nikodym.guided.summaries` sobre el ``Study`` que acaba de correr, serializados con las
celdas ya escritas como las lee una persona. Esta capa no redacta ni calcula nada: arma el
contexto que la puerta guiada conoce por sus argumentos —de dónde salieron los datos y cómo se
separó la muestra— a partir del config de la corrida, y llama a los mismos constructores.

Un resumen que no se pueda armar **no** tumba la persistencia de la corrida: la evidencia, el
informe y las cards ya están calculados y son lo que la persona pidió. Se publica ``error`` con
el motivo y el panel lo dice, en vez de esconder el hueco o de perder la corrida entera por una
frase.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

    from nikodym.core.study import Study
    from nikodym.guided.summaries import StageSummary

__all__ = ["serialize_summaries"]


def serialize_summaries(
    study: Study,
    *,
    source_label: str,
    run_dir: Path,
    trail_path: Path | None,
) -> dict[str, Any]:
    """``{stages: [...], final: {...}, error: str | None}`` para ``results.json``.

    ``stages`` trae, en el orden del pipeline, las etapas que dejaron artefactos (una corrida
    fallida conserva los resúmenes de lo que sí corrió); ``final`` es el resumen final con sus dos
    estados. Con ``error`` poblado, ``stages`` y ``final`` pueden venir vacíos.
    """
    # Import perezoso: la capa ``ui`` no importa dominios al cargarse (D-HASH-5: ``/api/validate``
    # responde lo mismo en un proceso frío), y los constructores de resúmenes arrastran los mapas
    # de rótulos de cada dominio.
    from nikodym.guided.summaries import (
        SummaryContext,
        build_final_summary,
        build_stage_summaries,
        partition_label_from_config,
    )

    try:
        contexto = SummaryContext(
            project_dir=run_dir,
            run_dir=run_dir,
            source_label=source_label,
            partition_label=partition_label_from_config(study.config),
            report_dir=run_dir,
            trail_path=trail_path,
        )
        etapas: tuple[StageSummary, ...] = build_stage_summaries(study, contexto)
        final = build_final_summary(study, etapas, contexto)
    except Exception as exc:  # se publica el motivo; la corrida no se pierde
        return {"stages": [], "final": None, "error": _mensaje(exc)}
    return {
        "stages": [etapa.to_dict() for etapa in etapas],
        "final": final.to_dict(),
        "error": None,
    }


def _mensaje(exc: Exception) -> str:
    texto = str(exc).strip()
    return f"El resumen por etapa no se pudo armar: {texto or type(exc).__name__}"
