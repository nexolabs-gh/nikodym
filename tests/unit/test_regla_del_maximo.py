"""Gate de la enmienda REGLA-DEL-MÁXIMO (D-MAX-1…6).

🔴 **El defecto que cierra: el config de fábrica publicaba una comparación que ninguna norma chilena
pide.** `ProvisioningConfig()` traía `max(CMF, IFRS 9)`, y la regla del Cap. B-1 (Circular 2.346) es
`max(método estándar, método interno del banco)` por institución — el Cap. A-2 num. 5 excluye el
deterioro de NIIF 9 sobre las colocaciones. El motor **declaraba honestamente la procedencia** en su
lineage, pero publicaba la cifra igual bajo un capítulo titulado «la regla del máximo (Chile)».

⚠️ **Este gate ancla la RELACIÓN, no el valor.** Un test que sólo comprobase
`source_b == 'provisioning_internal'` se «arregla» invirtiéndolo, y el defecto vuelve con el gate
verde. Lo que se afirma aquí es que **la etiqueta regulatoria, el título del capítulo y la
comparación configurada dicen los tres lo mismo**, en las dos direcciones.
"""

from __future__ import annotations

from typing import Any

import pytest

from nikodym.provisioning.config import (
    CMF_SOURCE,
    IFRS9_SOURCE,
    INTERNAL_SOURCE,
    ProvisioningConfig,
)
from nikodym.report.document import domain_title

_CORTO = {CMF_SOURCE: "cmf", INTERNAL_SOURCE: "internal", IFRS9_SOURCE: "ifrs9"}


def _card(cfg: ProvisioningConfig) -> dict[str, Any]:
    """La parte de la card que decide el título, con los nombres cortos que publica el motor."""
    return {
        "source_a": _CORTO[cfg.source_a],
        "source_b": _CORTO[cfg.source_b],
        "comparison_level": cfg.comparison_level,
    }


# --------------------------------------------------------------------------------------------
# 1. El default de fábrica es la regla que la norma exige
# --------------------------------------------------------------------------------------------


def test_el_default_compara_estandar_contra_interno() -> None:
    """D-MAX-1. El de fábrica es la comparación del B-1, no la histórica.

    Importa que sea el DEFAULT y no una opción: hasta el 2026-08-04 había que **saber que estaba
    mal** para arreglarlo. Quien no tocara el campo obtenía `max(CMF, IFRS 9)`.
    """
    cfg = ProvisioningConfig()
    assert set(cfg.sources) == {CMF_SOURCE, INTERNAL_SOURCE}
    assert cfg.rule == "max"
    assert cfg.comparison_level == "total", "el B-1 compara por institución, no por cartera"


def test_el_comparativo_entre_marcos_sigue_siendo_alcanzable() -> None:
    """Cara simétrica: comparar contra IFRS 9 no se prohíbe, deja de ser lo de fábrica.

    Es un caso legítimo —una filial que reporta ECL a su matriz extranjera— y quitarlo habría sido
    cambiar un defecto por otro. Lo que cambia es quién lo elige: ahora, quien lo necesita.
    """
    cfg = ProvisioningConfig(source_b=IFRS9_SOURCE)
    assert set(cfg.sources) == {CMF_SOURCE, IFRS9_SOURCE}


# --------------------------------------------------------------------------------------------
# 2. El título del capítulo dice la verdad sobre la comparación que lo produjo
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kwargs", "rotula_pais", "motivo"),
    [
        ({}, True, "el default ES la regla del B-1"),
        ({"source_b": IFRS9_SOURCE}, False, "comparar entre marcos contables no lo exige la norma"),
        ({"comparison_level": "portfolio"}, False, "el B-1 es por institución, no por cartera"),
        ({"comparison_level": "segment", "segment_col": "segmento"}, False, "ídem por segmento"),
        ({"rule": "use_internal"}, True, "el B-1 contempla el interno no objetado, mismo párrafo"),
    ],
)
def test_el_titulo_rotula_el_pais_solo_cuando_corresponde(
    kwargs: dict[str, Any], rotula_pais: bool, motivo: str
) -> None:
    """D-MAX-2 y D-MAX-5, en los dos sentidos y sobre configs que construyen de verdad."""
    titulo = domain_title("provisioning", _card(ProvisioningConfig(**kwargs)))
    assert ("Chile" in titulo) is rotula_pais, f"{motivo}; el título dice: {titulo!r}"


def test_el_titulo_no_afirma_nada_sin_card() -> None:
    """Sin el dato no se rotula: afirmar el país a ciegas es el defecto que esto cierra."""
    assert "Chile" not in domain_title("provisioning", None)


# --------------------------------------------------------------------------------------------
# 3. Título y etiqueta regulatoria no pueden divergir
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kwargs",
    [
        {},
        {"source_b": IFRS9_SOURCE},
        {"comparison_level": "portfolio"},
        {"rule": "use_internal"},
    ],
)
def test_el_titulo_y_la_etiqueta_del_lineage_cuentan_la_misma_historia(
    kwargs: dict[str, Any],
) -> None:
    """🔴 La pieza que impide que el arreglo se deshaga por un lado solo.

    El motor ya elegía bien su etiqueta regulatoria: con fuentes distintas de estándar-e-interno
    devuelve *«comparativo entre marcos contables SIN norma chilena que lo exija»*. Lo que fallaba
    era que **el título no la escuchaba**. Este gate ata las dos superficies: si una empieza a decir
    «Chile» donde la otra dice «sin norma que lo exija», se pone rojo.

    ⚠️ **La primera versión de este gate estaba mal, y él mismo lo destapó.** Decidía por
    `"B-1" in etiqueta`, y **tres de las cuatro etiquetas mencionan el B-1** — incluidas las dos que
    existen justamente para decir que la comparación NO lo vincula («comparativo diagnóstico SIN
    binding B-1», y la que cita «Cap. B-1 a B-3» para explicar qué excluye el Cap. A-2). Buscar un
    substring en copy es adivinar; el criterio son las dos constantes que el motor elige cuando la
    comparación sí vincula.
    """
    from nikodym.provisioning.orchestrator import (
        _B1_INTERNAL_RULE_SOURCE,
        _B1_MAX_RULE_SOURCE,
        _rule_source,
    )

    cfg = ProvisioningConfig(**kwargs)
    etiqueta = _rule_source(cfg)
    titulo = domain_title("provisioning", _card(cfg))

    vincula_el_b1 = etiqueta in (_B1_MAX_RULE_SOURCE, _B1_INTERNAL_RULE_SOURCE)
    assert ("Chile" in titulo) is vincula_el_b1, (
        f"el título y el lineage se contradicen. título={titulo!r} · etiqueta={etiqueta[:80]!r}"
    )


def test_el_barrido_no_es_vacuo() -> None:
    """Un gate que recorre cero da verde y no prueba nada: pasó ya dos veces en este repo."""
    from nikodym.provisioning.orchestrator import _rule_source

    etiquetas = {
        _rule_source(ProvisioningConfig()),
        _rule_source(ProvisioningConfig(source_b=IFRS9_SOURCE)),
        _rule_source(ProvisioningConfig(comparison_level="portfolio")),
        _rule_source(ProvisioningConfig(rule="use_internal")),
    }
    assert len(etiquetas) == 4, (
        "las cuatro combinaciones deberían producir cuatro etiquetas distintas; si colapsan, "
        f"este gate está comparando menos de lo que cree: {len(etiquetas)}"
    )
