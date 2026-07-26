"""Tests de la unidad temporal de la term-structure y del horizonte 12m (enmienda D-HOR-0).

`ifrs9` usa ``time_value`` como exponente de ``(1+EIR)^(-tau)`` **asumiendo años sin verificarlo**.
Medido el 2026-07-26 sobre el motor: la misma cartera, en los mismos instantes, declarada en meses
en vez de años daba **826,06 de ECL contra 1.677,76 — un -50,8 %**, en silencio. D-HOR-0 (Cami)
resolvió que **la term-structure transporta su unidad** y que ``ifrs9`` convierte antes de
descontar; si no la declara, se presume años y se emite ``DATO-INSTITUCIONAL-IFRS-7``, gobernable
por ``fail_on_falta_dato``. El aviso hermano ``FALTA-DATO-IFRS-8`` cubre el horizonte 12m que no es
conmensurable con el soporte de la curva.

Los goldens son verificables a mano: la ECL lifetime se escribe como la suma explícita
``sum(pd_marginal * lgd * ead * (1+EIR)^-anios)``, de modo que el test enuncia la fórmula del SDD-16
§3 en vez de transcribir un literal. El invariante central no es un número sino una igualdad: **la
misma economía declarada en dos unidades distintas produce la misma ECL**.

Se usa ``detail['ecl_lifetime']`` —no ``ecl_reported``— a propósito: suma el soporte completo sin
truncar por stage, así que el invariante de unidad no depende del staging ni del corte de 12 meses.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import pytest

from nikodym.provisioning.ifrs9 import IfrsProvisioningConfig, IfrsProvisioningEngine
from nikodym.provisioning.ifrs9.config import (
    IfrsEadConfig,
    IfrsEclConfig,
    IfrsLgdConfig,
    IfrsPdConfig,
    IfrsScenarioConfig,
    IfrsStagingConfig,
)
from nikodym.provisioning.ifrs9.exceptions import IfrsFaltaDatoError
from nikodym.provisioning.ifrs9.results import IfrsProvisionResult

# Marcas de esta enmienda. El código NO viaja al copy público: la prosa explica la limitación en el
# idioma del lector (gate `tests/unit/test_public_copy.py`).
_AVISO_UNIDAD = "DATO-INSTITUCIONAL-IFRS-7"
_AVISO_HORIZONTE = "FALTA-DATO-IFRS-8"
# `FALTA-DATO-IFRS-4` (perfil EAD(t) diferido a CT-3) se emite en TODA corrida: es estructural y no
# gobernable, así que aparece en `falta_dato` de cada caso sin detener nada (D-CRP6-2).
_AVISO_ESTRUCTURAL = "FALTA-DATO-IFRS-4"

# Cuatro cortes trimestrales sobre un horizonte de un año: la misma economía que la medición de la
# enmienda §5.1, expresable en dos unidades sin cambiar ni un instante del calendario.
_PD_MARGINAL = [0.05, 0.04, 0.03, 0.02]
_ANIOS = [0.25, 0.50, 0.75, 1.00]
_MESES = [3.0, 6.0, 9.0, 12.0]
_LGD = 0.40
_EAD = 1000.0
_EIR = 0.10

# ECL lifetime del SDD-16 §3 con tau EN AÑOS, escrita como la fórmula y no como un literal.
_ECL_LIFETIME_ANIOS = sum(
    pd_m * _LGD * _EAD * (1.0 + _EIR) ** (-tau)
    for pd_m, tau in zip(_PD_MARGINAL, _ANIOS, strict=True)
)


def _frame(**overrides: Any) -> pd.DataFrame:
    """Frame económico mínimo de ``op1`` con EAD y LGD entregadas por la institución."""
    base: dict[str, Any] = {
        "portfolio": "retail",
        "ead": _EAD,
        "lgd": _LGD,
        "eir": _EIR,
        "days_past_due": 0,
        "is_default": False,
    }
    base.update(overrides)
    return pd.DataFrame([base], index=pd.Index(["op1"], name="loan_id"))


def _ts(
    *,
    time_value: list[float],
    time_unit: list[Any] | str | None = None,
    periods: list[int] | None = None,
    pd_marginal: list[float] | None = None,
    row_id: list[str] | None = None,
    declara_unidad: bool = True,
) -> pd.DataFrame:
    """Term-structure tidy con unidad temporal declarada por fila.

    ``declara_unidad=False`` omite la columna entera, que es el caso de toda curva producida antes
    de esta enmienda y el de cualquier productor de terceros: la aditividad de CT-2 exige que esa
    curva siga corriendo, no que falle.
    """
    marginal = pd_marginal if pd_marginal is not None else _PD_MARGINAL
    n = len(marginal)
    period = periods if periods is not None else list(range(1, n + 1))
    cumulative = np.cumsum(marginal).tolist()
    data: dict[str, list[Any]] = {
        "row_id": row_id if row_id is not None else ["op1"] * n,
        "period": period,
        "time_value": time_value,
        "pd_marginal": marginal,
        "survival": [1.0 - c for c in cumulative],
        "pd_cumulative": cumulative,
        "scenario": [None] * n,
        "warning_codes": [()] * n,
    }
    if declara_unidad:
        data["time_unit"] = time_unit if isinstance(time_unit, list) else [time_unit] * n
    return pd.DataFrame(data)


def _cfg(**pd_overrides: Any) -> IfrsProvisioningConfig:
    """Config base: survival, ttc_only, EAD y LGD provistas, horizonte 12m = 1 período.

    ``fail_on_falta_dato=False`` explícito, contra el default ``True`` de la clase: casi todos los
    tests de aquí **inspeccionan** ``card.falta_dato``, y con el flag encendido la corrida aborta
    antes de que exista card que mirar. El test del gate lo vuelve a encender a propósito.
    """
    pd_kwargs: dict[str, Any] = {
        "term_structure_source": "survival",
        "pit_mode": "ttc_only",
        "horizon_12m_periods": 1,
    }
    pd_kwargs.update(pd_overrides)
    return IfrsProvisioningConfig(
        row_id_col=None,
        portfolio_col="portfolio",
        fail_on_falta_dato=False,
        pd=IfrsPdConfig(**pd_kwargs),
        lgd=IfrsLgdConfig(method="provided"),
        ead=IfrsEadConfig(method="provided"),
        scenarios=IfrsScenarioConfig(source="single"),
        staging=IfrsStagingConfig(),
    )


def _run(cfg: IfrsProvisioningConfig, frame: pd.DataFrame, ts: pd.DataFrame) -> IfrsProvisionResult:
    """Ejecuta ``calculate`` con la fecha de cálculo canónica de los tests."""
    return IfrsProvisioningEngine.from_config(cfg).calculate(
        frame, term_structure=ts, as_of_date="2026-01-31"
    )


def _ecl_lifetime(result: IfrsProvisionResult) -> float:
    """ECL lifetime de ``op1``: suma el soporte completo, sin truncar por stage."""
    return float(result.detail.iloc[0]["ecl_lifetime"])


# ─────────────────────────── la unidad temporal y el descuento ───────────────────────────


def test_la_misma_economia_en_dos_unidades_da_la_misma_ecl() -> None:
    """El invariante que da sentido a toda la enmienda: la unidad no puede mover la provisión.

    Mismos instantes del calendario, misma PD/LGD/EAD, mismo EIR anual. Lo único que cambia es en
    qué unidad se declara el eje temporal. Hoy esto falla con una diferencia del orden del 40-50 %.
    """
    en_anios = _run(_cfg(), _frame(), _ts(time_value=_ANIOS, time_unit="year"))
    en_meses = _run(_cfg(), _frame(), _ts(time_value=_MESES, time_unit="month"))

    np.testing.assert_allclose(_ecl_lifetime(en_anios), _ECL_LIFETIME_ANIOS, rtol=1e-12)
    np.testing.assert_allclose(_ecl_lifetime(en_meses), _ECL_LIFETIME_ANIOS, rtol=1e-12)


def test_curva_sin_unidad_declarada_presume_anos_y_lo_dice() -> None:
    """Sin unidad se presume años —no se adivina—, y la presunción queda declarada y auditable."""
    result = _run(_cfg(), _frame(), _ts(time_value=_ANIOS, declara_unidad=False))

    np.testing.assert_allclose(_ecl_lifetime(result), _ECL_LIFETIME_ANIOS, rtol=1e-12)
    assert _AVISO_UNIDAD in result.card.falta_dato


def test_period_no_es_una_unidad_convertible() -> None:
    """``"period"`` es el default de fábrica de survival y markov, y no es ninguna unidad.

    No se adivina: se trata exactamente igual que una columna ausente.
    """
    result = _run(_cfg(), _frame(), _ts(time_value=_ANIOS, time_unit="period"))

    assert _AVISO_UNIDAD in result.card.falta_dato


def test_unidad_desconocida_no_rompe_la_corrida() -> None:
    """Un literal fuera de la tabla se declara, **no** se levanta como error.

    Ancla anti-regresión del criterio de §5.2: la enmienda se eligió sobre la alternativa de años
    como convención única precisamente porque **no rompe a ningún usuario actual**. Convertir esto
    en un error rompería a todo el que nunca tocó el campo.
    """
    result = _run(_cfg(), _frame(), _ts(time_value=_ANIOS, time_unit="quincena"))

    assert result.card.falta_dato  # la corrida termina; no levanta
    assert _AVISO_UNIDAD in result.card.falta_dato


def test_fail_on_falta_dato_gobierna_la_unidad_no_declarada() -> None:
    """La marca es **gobernable**, no estructural: quien quiera fail-fast lo tiene sin nada nuevo.

    Es la consecuencia directa de CRP-6, ya cerrado en las siete capas: un código declarado que no
    está en ``_STRUCTURAL_WARNINGS`` detiene la corrida con el flag en ``True``.
    """
    cfg = _cfg().model_copy(update={"fail_on_falta_dato": True})

    with pytest.raises(IfrsFaltaDatoError, match=_AVISO_UNIDAD):
        _run(cfg, _frame(), _ts(time_value=_ANIOS, declara_unidad=False))


def test_unidades_distintas_por_fila_se_convierten_por_fila() -> None:
    """La conversión es por fila, no por frame.

    ``forward`` concatena N fuentes en un solo frame (``forward/step.py``), así que dos curvas con
    unidades distintas conviven en la misma tabla. Un escalar por frame las mezclaría en silencio.
    """
    frame = pd.concat([_frame(), _frame().rename(index={"op1": "op2"})])
    n = len(_PD_MARGINAL)
    ts = pd.concat(
        [
            _ts(time_value=_ANIOS, time_unit="year"),
            _ts(time_value=_MESES, time_unit="month", row_id=["op2"] * n),
        ],
        ignore_index=True,
    )

    result = _run(_cfg(), frame, ts)

    detail = result.detail.set_index("row_id")
    np.testing.assert_allclose(
        float(detail.loc["op1", "ecl_lifetime"]), _ECL_LIFETIME_ANIOS, rtol=1e-12
    )
    np.testing.assert_allclose(
        float(detail.loc["op2", "ecl_lifetime"]), _ECL_LIFETIME_ANIOS, rtol=1e-12
    )


def test_la_evidencia_publica_el_crudo_y_el_convertido() -> None:
    """La conversión se audita como un paso aritmético comprobable, no como un renombre.

    Con sólo el convertido, la evidencia ECL dejaría de reconciliar fila a fila con la curva que
    emitió survival. Con sólo el crudo, ``DF = (1+EIR)^-tau`` no se puede verificar desde la tabla.
    """
    result = _run(_cfg(), _frame(), _ts(time_value=_MESES, time_unit="month"))

    ts_out = result.ecl_term_structure
    np.testing.assert_allclose(ts_out["time_value"].to_numpy(), _MESES, rtol=1e-12)
    np.testing.assert_allclose(ts_out["time_value_years"].to_numpy(), _ANIOS, rtol=1e-12)


def test_period_eir_no_usa_la_unidad_pero_igual_la_declara() -> None:
    """La marca describe una propiedad del *input*, no de una rama de cálculo aguas abajo.

    ``discount_convention="period_eir"`` descuenta por el índice de período, así que la unidad no
    afecta a su ECL. Condicionar la marca a la convención haría que la misma curva sea "declarada"
    o "no declarada" según un ajuste posterior — el agujero de §5.2 por otra puerta.
    """
    cfg = _cfg().model_copy(update={"ecl": IfrsEclConfig(discount_convention="period_eir")})

    result = _run(cfg, _frame(), _ts(time_value=_ANIOS, declara_unidad=False))

    assert _AVISO_UNIDAD in result.card.falta_dato


# ─────────────────────────── el horizonte 12m contra el soporte de la curva ───────────────────────


def test_horizonte_que_cubre_toda_la_curva_se_declara() -> None:
    """Cuando el horizonte alcanza el soporte, un Stage 1 provisiona lo mismo que un Stage 2.

    La corrida termina ``done``, la card no dice nada y los totales se ven razonables: es el modo
    de fallo A de la §1, el único confirmado ejecutando el motor.
    """
    cfg = _cfg(horizon_12m_periods=len(_PD_MARGINAL))

    result = _run(cfg, _frame(), _ts(time_value=_ANIOS, time_unit="year"))

    assert _AVISO_HORIZONTE in result.card.falta_dato


def test_truncado_deliberado_no_avisa() -> None:
    """Quien fija ``max_lifetime_periods`` está truncando a propósito: avisarle es ruido.

    Pasa ya hoy —el aviso todavía no existe— y por eso va **sin** ``xfail``: es una guarda, no una
    capacidad pendiente. Su trabajo empieza en C4, cuando el predicado exista y pueda equivocarse.

    El predicado tiene que distinguir el truncado deliberado del horizonte que se comió la curva
    sin que nadie lo mirara. Un aviso que dispara sobre el caso correcto se aprende a ignorar, y
    eso lo mata.
    """
    cfg = _cfg(horizon_12m_periods=1, max_lifetime_periods=1)

    result = _run(cfg, _frame(), _ts(time_value=_ANIOS, time_unit="year"))

    assert _AVISO_HORIZONTE not in result.card.falta_dato


def test_horizonte_bajo_el_soporte_de_la_curva_se_declara() -> None:
    """El caso que el gatillo original dejaba **mudo**: el horizonte cae bajo el primer período.

    Con ``periods=[3]`` y ``H=1`` la máscara ``period <= 1`` no selecciona nada y un Stage 1
    provisiona **cero**, sin error. La versión anterior del predicado usaba una mediana sobre una
    selección vacía, que da ``NaN`` y en toda comparación devuelve ``False``.
    """
    cfg = _cfg(horizon_12m_periods=1)
    ts = _ts(time_value=[0.75], time_unit="year", periods=[3], pd_marginal=[0.05])

    result = _run(cfg, _frame(), ts)

    assert _AVISO_HORIZONTE in result.card.falta_dato


# ─────────────────────────── el productor declara su unidad ───────────────────────────


def test_declarar_la_unidad_hace_desaparecer_la_marca() -> None:
    """Contracara obligatoria: declarar la unidad hace desaparecer la marca.

    Sin esta dirección, un predicado que devolviera siempre ``True`` pasaría el resto de la suite.
    Es lo que hace a la marca **gobernable** y no estructural.

    Pasa ya hoy, pero **por la razón equivocada** (el aviso no existe todavía); desde C3 pasará por
    la correcta. Va sin ``xfail`` justamente para que el día que el predicado se pase de ansioso
    este test lo cace.
    """
    result = _run(_cfg(), _frame(), _ts(time_value=_ANIOS, time_unit="year"))

    assert _AVISO_UNIDAD not in result.card.falta_dato
    assert result.card.falta_dato == (_AVISO_ESTRUCTURAL,)
