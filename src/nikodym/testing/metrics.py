"""Fuente única de la lista de métricas que cada dominio publica al namespace canónico (D-GOB-4).

`study.results["metrics"]` es el canal que leen `governance` (el model card de SR 11-7) y `tracking`
(MLflow). Hasta 1.12.0 no lo llenaba **nadie**: una corrida F1 completa terminaba con
`results == {}` y el model card salía con `metrics={}` —el titular del README, sin contenido—.

Este módulo es la lista canónica de qué publica cada dominio, del mismo modo que
:mod:`nikodym.testing.stability` lo es para la marca SemVer y :mod:`nikodym.testing.regulatory` para
la cobertura regulatoria. Lo consumen el gate ``tests/unit/test_canal_metricas.py`` y quien quiera
preguntar, desde código, qué claves aparecerán impresas en un model card.

🔴 **La lista es corta, explícita y de dominio; no es «todo lo numérico de la card».** AUC, Gini, KS
y PSI **no son campos escalares de ninguna** ``CardSection``: viven en
``PerformanceCardSection.max_metrics_by_partition`` (un ``dict`` por partición) y en
``StabilityCardSection.max_psi_by_comparison``. Un agregador genérico que copiara los escalares
declarados publicaría ``scorecard.pdo`` y ``performance.n_deciles`` como «las métricas del modelo» y
**omitiría el AUC**. Medido antes de D-GOB-1; por eso reduce cada dominio y no el núcleo.

Añadir una métrica aquí **es** ampliar lo que se imprime en cada model card publicado: exige la
misma deliberación que cualquier superficie firmada, no la preferencia de quien edita.
"""

from __future__ import annotations

from typing import Final

__all__ = [
    "DECLARED_METRICS",
    "DOMAINS_WITHOUT_METRICS",
    "PARTITION_PLACEHOLDER",
    "declared_metric_names",
    "is_declared_metric",
    "orchestrable_domains",
]

#: Marca, dentro de un nombre declarado, el tramo que se resuelve en tiempo de corrida con la
#: identidad de una partición (``desarrollo``, ``holdout``, ``oot``, …). La lista de particiones la
#: fija el config de datos de cada institución, así que no puede enumerarse aquí sin inventar.
PARTITION_PLACEHOLDER: Final = "<particion>"

DECLARED_METRICS: Final[dict[str, tuple[str, ...]]] = {
    "data": ("n_rows", "n_features", "bad_rate"),
    "binning": ("n_variables_binned", "n_variables_skipped"),
    "selection": ("n_candidates", "n_selected", "max_abs_correlation_after_selection"),
    "model": ("n_final_features",),
    "scorecard": ("n_variables",),
    "calibration": ("target_pd", "calibrated_mean_pd_dev", "observed_default_rate_dev"),
    # Las tres de discriminación, una por partición evaluable. Una partición que sale
    # `not_evaluable` —el caso real de una cartera corta— NO aporta clave: se omite, no se rellena.
    "performance": (
        f"auc_{PARTITION_PLACEHOLDER}",
        f"gini_{PARTITION_PLACEHOLDER}",
        f"ks_{PARTITION_PLACEHOLDER}",
    ),
    # `worst_psi` es la reducción de `max_psi_by_comparison`; `worst_csi_value` ya viene reducido en
    # la card. Ambos son opcionales por construcción: sin comparación evaluable no hay peor caso.
    "stability": ("worst_psi", "worst_csi_value"),
}
"""Métricas que cada dominio publica, SIN el prefijo de dominio (lo pone ``core``)."""

DOMAINS_WITHOUT_METRICS: Final[dict[str, str]] = {
    "eda": (
        "Exploratorio: describe el frame de entrada y no produce un juicio del modelo. Su SDD "
        "declarará su lista cuando se aborde."
    ),
    "markov": "Fuera de F1; su SDD declara su lista cuando se aborde.",
    "tuning": "Fuera de F1; su SDD declara su lista cuando se aborde.",
    "ml": "Fuera de F1; su SDD declara su lista cuando se aborde.",
    "explain": "Fuera de F1; su SDD declara su lista cuando se aborde.",
    "survival": "Fuera de F1; su SDD declara su lista cuando se aborde.",
    "forward": "Fuera de F1; su SDD declara su lista cuando se aborde.",
    "stress": "Fuera de F1; su SDD declara su lista cuando se aborde.",
    "provisioning_ifrs9": "Fuera de F1; su SDD declara su lista cuando se aborde.",
    "provisioning_cmf": "Fuera de F1; su SDD declara su lista cuando se aborde.",
    "provisioning_internal": "Fuera de F1; su SDD declara su lista cuando se aborde.",
    "provisioning": "Fuera de F1; su SDD declara su lista cuando se aborde.",
    "validation": "Fuera de F1; su SDD declara su lista cuando se aborde.",
    "report": (
        "INFRA: es la foto de lo que ya corrió y no calcula nada propio. Publicar métricas suyas "
        "duplicaría las de los dominios que retrata."
    ),
}
"""Dominios que declaran **explícitamente** no publicar métricas todavía, con su razón escrita.

La puerta queda abierta y vacía, que es honesto; lo que el gate prohíbe es que un dominio nuevo
aparezca sin pasar por ninguna de las dos listas.
"""


def orchestrable_domains() -> tuple[str, ...]:
    """Enumera los dominios orquestables, leídos del orden canónico de ``core``.

    Se mide el árbol en vez de confiar en las listas de este módulo: es lo que permite que el gate
    detecte un dominio **nuevo** que nadie clasificó, que es el sentido en el que un censo se rompe
    en silencio (la lección de D-VIS-6).
    """
    from nikodym.core.study import _DEFAULT_DOMAIN_ORDER

    return tuple(sorted(_DEFAULT_DOMAIN_ORDER))


def declared_metric_names(domain: str) -> tuple[str, ...]:
    """Devuelve la lista declarada del dominio, o ``()`` si declara no publicar."""
    return DECLARED_METRICS.get(domain, ())


def is_declared_metric(domain: str, name: str) -> bool:
    """Indica si ``name`` (sin prefijo) está en la lista declarada de ``domain``.

    Resuelve :data:`PARTITION_PLACEHOLDER` contra cualquier identidad de partición no vacía, que es
    lo que permite declarar ``auc_<particion>`` una vez en vez de enumerar particiones que sólo el
    config de cada institución conoce.
    """
    for declarada in declared_metric_names(domain):
        if PARTITION_PLACEHOLDER not in declarada:
            if declarada == name:
                return True
            continue
        prefijo, _, sufijo = declarada.partition(PARTITION_PLACEHOLDER)
        if not name.startswith(prefijo) or not name.endswith(sufijo):
            continue
        resto = name[len(prefijo) : len(name) - len(sufijo) if sufijo else None]
        if resto:
            return True
    return False
