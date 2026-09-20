"""Golden bidireccional de los campos esenciales por sección (SDD-31 D-SIM-4; enmienda §3.8).

La marca es un metadato del schema —``json_schema_extra={"ui_essential": True}``— y este gate la
ata en los dos sentidos: **una marca que no esté en el golden** pone rojo (nadie amplía los
esenciales sin decirlo aquí) y **una entrada del golden sin marca** también (nadie los pierde en
silencio). El tope vigente es **6 por sección** (Cami, 2026-09-18, SDD-31 §12.1) y se mide sobre lo
que la pantalla muestra a la vez: en una unión discriminada —la estrategia de partición— cuenta
la rama con más esenciales, no la suma de todas, porque el formulario pinta una rama por vez.
"""

from __future__ import annotations

from typing import Any, Final

from nikodym.ui.routes import schema_payload

TOPE_ESENCIALES_POR_SECCION: Final = 6

#: Los caminos marcados, por sección, tal como los pinta la tabla §3.8 de la enmienda (39 marcas
#: en 12 secciones; ``eda`` no tiene ninguna: todo default, el resumen lo muestra). Un mismo
#: camino puede vivir en varias ramas de una unión (``holdout_fraction``) y se lista una vez.
ESENCIALES_POR_SECCION: Final[dict[str, tuple[str, ...]]] = {
    "data": (
        "data.load.source",
        "data.schema.unique_keys",
        "data.target.bad_rule",
        "data.partition.strategy.cohort_col",
        "data.partition.strategy.date_col",
        "data.partition.strategy.holdout_fraction",
        "data.partition.strategy.oot_cohorts",
        "data.partition.strategy.oot_from",
    ),
    "eda": (),
    "binning": (
        "binning.categorical_columns",
        "binning.feature_columns",
        "binning.max_n_bins",
        "binning.min_bin_size",
        "binning.monotonic_trend",
    ),
    "selection": (
        "selection.correlation.threshold",
        "selection.min_iv",
        "selection.vif.threshold",
    ),
    "model": (
        "model.sign_policy.action",
        "model.stepwise.enabled",
        "model.stepwise.entry_p_value",
        "model.stepwise.exit_p_value",
    ),
    "scorecard": ("scorecard.pdo", "scorecard.target_odds", "scorecard.target_score"),
    "calibration": ("calibration.anchor_source", "calibration.target_pd"),
    "performance": ("performance.n_deciles",),
    "stability": ("stability.psi_review_threshold", "stability.psi_stable_threshold"),
    "validation": ("validation.families",),
    "report": (
        "report.document.author",
        "report.document.entity",
        "report.document.model_name",
        "report.document.portfolio",
        "report.formats",
    ),
    "governance": (
        "governance.author",
        "governance.purpose",
        "governance.review_period_months",
    ),
}

#: Lo que la pantalla muestra a la vez por sección (la rama más cargada de la partición: fecha o
#: cohorte con su frontera y su holdout). Es la cifra 2 de SDD-31 §5 para el scorecard.
ESENCIALES_VISIBLES_A_LA_VEZ: Final[dict[str, int]] = {
    "data": 6,
    "eda": 0,
    "binning": 5,
    "selection": 3,
    "model": 4,
    "scorecard": 3,
    "calibration": 2,
    "performance": 1,
    "stability": 2,
    "validation": 1,
    "report": 5,
    "governance": 3,
}


def _schema() -> tuple[dict[str, Any], dict[str, Any]]:
    schema = schema_payload()["json_schema"]
    return schema, schema.get("$defs", {})


def _resolver(nodo: Any, defs: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(nodo, dict):
        return {}
    if "$ref" in nodo:
        base = _resolver(defs.get(nodo["$ref"].rsplit("/", 1)[-1], {}), defs)
        return {**base, **{k: v for k, v in nodo.items() if k != "$ref"}}
    return nodo


def _ramas(nodo: dict[str, Any], defs: dict[str, Any]) -> list[dict[str, Any]]:
    """Las ramas objeto de una unión, resueltas; la rama nula no cuenta."""
    ramas = []
    for rama in nodo.get("anyOf") or nodo.get("oneOf") or []:
        if isinstance(rama, dict) and rama.get("type") != "null":
            resuelta = _resolver(rama, defs)
            if resuelta.get("properties") or resuelta.get("type"):
                ramas.append(resuelta)
    return ramas


def _marcas(nodo: Any, defs: dict[str, Any], prefijo: str, visto: tuple[str, ...]) -> set[str]:
    """Todos los caminos marcados bajo ``nodo``, en todas las ramas (sin ``[]`` de listas)."""
    nodo = _resolver(nodo, defs)
    salida: set[str] = set()
    if nodo.get("ui_essential") is True:
        salida.add(prefijo)
    ref = nodo.get("title", "") + str(sorted(nodo.get("properties", {})))
    if ref in visto:
        return salida
    for rama in _ramas(nodo, defs):
        salida |= _marcas({k: v for k, v in rama.items()}, defs, prefijo, (*visto, ref))
    for nombre, hijo in nodo.get("properties", {}).items():
        camino = f"{prefijo}.{nombre}" if prefijo else nombre
        salida |= _marcas(hijo, defs, camino, (*visto, ref))
    items = nodo.get("items")
    if isinstance(items, dict):
        salida |= _marcas(items, defs, prefijo, (*visto, ref))
    return salida


def _visibles_a_la_vez(nodo: Any, defs: dict[str, Any], visto: tuple[str, ...]) -> int:
    """Marcas que la pantalla muestra a la vez: en una unión, la rama con más; el nodo cuenta."""
    nodo = _resolver(nodo, defs)
    total = 1 if nodo.get("ui_essential") is True else 0
    ref = nodo.get("title", "") + str(sorted(nodo.get("properties", {})))
    if ref in visto:
        return total
    ramas = _ramas(nodo, defs)
    if len(ramas) > 1:
        return total + max(_visibles_a_la_vez(rama, defs, (*visto, ref)) for rama in ramas)
    if len(ramas) == 1:
        return total + _visibles_a_la_vez(ramas[0], defs, (*visto, ref))
    for hijo in nodo.get("properties", {}).values():
        total += _visibles_a_la_vez(hijo, defs, (*visto, ref))
    items = nodo.get("items")
    if isinstance(items, dict):
        total += _visibles_a_la_vez(items, defs, (*visto, ref))
    return total


def _secciones() -> dict[str, dict[str, Any]]:
    schema, _defs = _schema()
    return {
        nombre: hijo
        for nombre, hijo in schema.get("properties", {}).items()
        if nombre in ESENCIALES_POR_SECCION
    }


def test_el_golden_cubre_las_doce_secciones_del_scorecard() -> None:
    assert len(ESENCIALES_POR_SECCION) == 12
    assert set(_secciones()) == set(ESENCIALES_POR_SECCION)


def test_cada_marca_del_schema_esta_en_el_golden_y_cada_entrada_del_golden_esta_marcada() -> None:
    """Bidireccional: ni marcas sin declarar ni entradas sin marca (SDD-31 §11)."""
    _, defs = _schema()
    for seccion, nodo in _secciones().items():
        marcadas = _marcas(nodo, defs, seccion, ())
        esperadas = set(ESENCIALES_POR_SECCION[seccion])
        assert marcadas == esperadas, (
            f"{seccion}: marcas sin golden {sorted(marcadas - esperadas)}; "
            f"golden sin marca {sorted(esperadas - marcadas)}"
        )


def test_ninguna_seccion_muestra_mas_de_seis_esenciales_a_la_vez() -> None:
    _, defs = _schema()
    for seccion, nodo in _secciones().items():
        visibles = _visibles_a_la_vez(nodo, defs, ())
        assert visibles == ESENCIALES_VISIBLES_A_LA_VEZ[seccion], (seccion, visibles)
        assert visibles <= TOPE_ESENCIALES_POR_SECCION, (seccion, visibles)


def test_la_marca_no_es_una_hoja_del_config() -> None:
    """``ui_essential`` es metadato: no aparece como campo de ningún modelo (D-FLU-12)."""
    from nikodym.core.config.schema import NikodymConfig

    assert "ui_essential" not in NikodymConfig.model_fields
    schema, _ = _schema()
    assert "ui_essential" not in schema.get("properties", {})
