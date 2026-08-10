"""Tests de la severidad MODELADA del método interno (D-LGD-4…D-LGD-15).

Las dos ramas observadas leen la severidad de una celda del archivo; estas tres la **estiman**
delegando en ``LgdEngine``, el mismo motor que usa IFRS 9. Lo que se comprueba aquí no es la
aritmética del motor de LGD —eso vive en ``test_provisioning_lgd.py``— sino la juntura: que la
severidad entra por la puerta de la PD sin mutar el frame, que la conversión a ``Decimal`` es la
misma, que el piso y el techo no se aplican dos veces con efecto, y que la política de huecos del
ajuste **no** es la de las columnas.

🔴 Cada test que cierra una decisión trae su **control negativo**: la afirmación contraria se
ejecuta y se exige que falle. Un test que sólo comprueba el camino feliz no distingue una guarda
puesta de una guarda ausente.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any, get_args

import numpy as np
import pandas as pd
import pytest

import nikodym
from nikodym.core.config import NikodymConfig
from nikodym.provisioning.exceptions import LgdError
from nikodym.provisioning.internal.config import (
    InternalLgdBetaRegression,
    InternalLgdFractionalResponse,
    InternalLgdGroupHistorical,
    InternalLgdModelada,
    InternalLgdProvided,
    InternalLgdWorkout,
    InternalProvisioningConfig,
)
from nikodym.provisioning.internal.engine import (
    InternalProvisioningEngine,
    _lgd_modelada,
    _parse_rows,
    _severity_by_row,
)
from nikodym.provisioning.internal.exceptions import (
    InternalConfigError,
    InternalInputError,
)
from nikodym.provisioning.internal.step import _procedencia_de_la_lgd
from nikodym.provisioning.lgd import LgdEngine, LgdSpec
from nikodym.report.prose import (
    _INTERNAL_LGD_AJUSTADAS,
    _INTERNAL_LGD_LABELS,
    _internal_lgd_paragraphs,
)
from nikodym.ui.datasets import materialize
from nikodym.ui.presets import get_preset

AS_OF = "2026-02-28"

#: Los once atributos que ``LgdSpec`` exige. Escritos A MANO desde el protocolo
#: (`provisioning/lgd.py:96-151`), nunca derivados de él: un oráculo que se derive de lo que vigila
#: mide que la función es determinista, no que el contrato se cumple.
ATRIBUTOS_DEL_PROTOCOLO: tuple[str, ...] = (
    "method",
    "lgd_col",
    "recovery_col",
    "covariate_cols",
    "workout_discount",
    "lgd_floor",
    "lgd_cap",
    "workout_ead_col",
    "workout_cost_col",
    "workout_time_col",
    "workout_rate_col",
)


def _cartera(n: int = 120, *, seed: int = 11) -> pd.DataFrame:
    """Cartera sintética con TODO lo que las cinco ramas pueden pedir, en sus unidades correctas.

    ⚠️ ``tasa_recuperada`` es una FRACCIÓN y ``monto_recuperado`` un MONTO. No son la misma columna
    con otro nombre: las regresiones calculan ``LGD = 1 - recovery`` y el enfoque de recuperos mete
    ese valor en ``PV(recovery - cost)/EAD``. Alimentar una fracción al segundo da severidad 1,0 en
    toda la cartera **sin un solo error**, que es justo el defecto que este fixture existe para no
    reproducir.
    """
    rng = np.random.default_rng(seed)
    exposicion = rng.uniform(1e5, 5e6, n).round(2)
    tasa_recuperada = rng.uniform(0.10, 0.85, n).round(4)
    return pd.DataFrame(
        {
            "portfolio": ["comercial"] * n,
            "exposure_amount": exposicion,
            "lgd": (1.0 - tasa_recuperada).round(4),
            "ltv": rng.uniform(0.2, 0.95, n).round(3),
            "plazo": rng.integers(6, 72, n).astype(float),
            "segmento": rng.choice(["A", "B"], n),
            "tasa_recuperada": tasa_recuperada,
            "monto_recuperado": (exposicion * tasa_recuperada).round(2),
            "ead": exposicion,
            "recovery_cost": (exposicion * rng.uniform(0.0, 0.03, n)).round(2),
            "recovery_time_years": rng.uniform(0.5, 4.0, n).round(2),
            "contractual_rate": rng.uniform(0.03, 0.18, n).round(4),
        }
    )


def _pd_frame(frame: pd.DataFrame, *, seed: int = 11) -> pd.DataFrame:
    """PD calibrada por operación, con el índice del frame."""
    rng = np.random.default_rng(seed + 1)
    return pd.DataFrame({"pd_calibrated": rng.beta(2, 20, len(frame)).round(5)}, index=frame.index)


def _cfg(lgd: Any, **kwargs: Any) -> InternalProvisioningConfig:
    """Config del método interno agrupando por segmento, con la rama de LGD que se le pase."""
    return InternalProvisioningConfig(grouping="segment", group_col="segmento", lgd=lgd, **kwargs)


def _corre(cfg: InternalProvisioningConfig, frame: pd.DataFrame) -> Any:
    """Ejecuta el motor por su puerta pública y devuelve el resultado."""
    return InternalProvisioningEngine(cfg).calculate(
        frame, pd_frame=_pd_frame(frame), as_of_date=AS_OF
    )


def _provision(resultado: Any) -> Decimal:
    """Total de provisión del resumen, sin pasar por float."""
    columna = next(c for c in resultado.summary.columns if "provision" in c.lower())
    return Decimal(str(resultado.summary.iloc[0][columna]))


# ───────────────────────────── el contrato con LgdSpec (paso 4) ─────────────────────────────


@pytest.mark.parametrize(
    "rama",
    [
        InternalLgdBetaRegression(covariate_cols=("ltv",)),
        InternalLgdFractionalResponse(covariate_cols=("ltv",)),
        InternalLgdWorkout(recovery_col="monto_recuperado"),
    ],
    ids=["beta", "fractional", "workout"],
)
def test_toda_rama_modelada_satisface_el_protocolo_entero(rama: LgdSpec) -> None:
    """Las tres publican los once atributos, usen o no cada uno (decisión (a) del paso 4)."""
    faltan = [nombre for nombre in ATRIBUTOS_DEL_PROTOCOLO if not hasattr(rama, nombre)]
    assert not faltan, (
        f"{type(rama).__name__} no satisface LgdSpec: le faltan {faltan}. El motor los lee sin "
        "preguntar por la rama, así que un atributo ausente revienta al estimar, no al construir"
    )


@pytest.mark.parametrize(
    ("rama", "inertes"),
    [
        (
            InternalLgdBetaRegression(covariate_cols=("ltv",)),
            (
                "workout_discount",
                "workout_ead_col",
                "workout_cost_col",
                "workout_time_col",
                "workout_rate_col",
            ),
        ),
        (InternalLgdWorkout(recovery_col="monto_recuperado"), ("covariate_cols",)),
    ],
    ids=["regresion", "workout"],
)
def test_lo_que_la_rama_no_usa_es_propiedad_y_no_entra_al_config(
    rama: Any, inertes: tuple[str, ...]
) -> None:
    """Un atributo inerte se publica y **no** se serializa: no es un control que se pueda mover.

    Es la razón 3 de la decisión (a): un campo inerte entraría al ``model_dump``, sería visible en
    el formulario y escribible sin efecto alguno — la clase «campo declarado en rama inactiva» que
    la unión discriminada acaba de cerrar de forma estructural.
    """
    volcado = rama.model_dump()
    for nombre in inertes:
        assert hasattr(rama, nombre), f"{nombre} debe existir: el protocolo lo exige"
        assert nombre not in volcado, (
            f"{type(rama).__name__}.{nombre} entró al model_dump: si es un campo, el formulario lo "
            "pinta y el usuario puede moverlo sin que cambie una cifra"
        )
        assert nombre not in type(rama).model_fields, (
            f"{type(rama).__name__}.{nombre} es un campo, y debía ser @property inerte"
        )


def test_la_rama_de_recuperos_no_ofrece_descuento_a_la_eir() -> None:
    """El método interno no tiene EIR, así que esa opción no EXISTE en vez de existir y morir.

    Control negativo del riesgo real: si ``workout_discount`` fuese un campo con las dos opciones,
    elegir ``eir`` construiría un config válido cuya corrida el motor rechaza — la clase exacta de
    ``binning.solver='cp'``.
    """
    rama = InternalLgdWorkout(recovery_col="monto_recuperado")
    assert rama.workout_discount == "contractual"
    with pytest.raises(Exception, match="workout_discount"):
        InternalLgdWorkout(recovery_col="monto_recuperado", workout_discount="eir")


# ───────────────────────────── el estrechamiento (D-LGD-4) ─────────────────────────────


@pytest.mark.parametrize(
    ("rama", "es_modelada"),
    [
        (InternalLgdProvided(), False),
        (InternalLgdGroupHistorical(), False),
        (InternalLgdBetaRegression(covariate_cols=("ltv",)), True),
        (InternalLgdFractionalResponse(covariate_cols=("ltv",)), True),
        (InternalLgdWorkout(recovery_col="monto_recuperado"), True),
    ],
    ids=["provided", "group_historical", "beta", "fractional", "workout"],
)
def test_solo_las_tres_ramas_modeladas_delegan_en_el_motor(rama: Any, es_modelada: bool) -> None:
    """Las dos direcciones: que las modeladas deleguen, y que las observadas NO."""
    assert (_lgd_modelada(_cfg(rama)) is not None) is es_modelada
    assert isinstance(rama, InternalLgdModelada) is es_modelada


def test_con_tasa_de_perdida_directa_la_rama_de_lgd_no_gobierna_nada() -> None:
    """Con ``direct_loss_rate`` la severidad sale de otra columna: modelar sería calcular de más."""
    cfg = _cfg(
        InternalLgdFractionalResponse(covariate_cols=("ltv",)),
        method="direct_loss_rate",
        loss_rate_col="lgd",
    )
    assert _lgd_modelada(cfg) is None
    assert _severity_by_row(_cartera(), cfg=cfg) is None


def test_el_motor_de_lgd_no_muta_el_frame() -> None:
    """Contrato de ``LgdEngine``: estima sin escribir en el frame de entrada (D-LGD-4)."""
    frame = _cartera()
    antes = frame.copy(deep=True)
    cfg = _cfg(InternalLgdFractionalResponse(covariate_cols=("ltv", "plazo")))
    assert _severity_by_row(frame, cfg=cfg) is not None
    pd.testing.assert_frame_equal(frame, antes)


# ───────────────────────────── el cálculo de punta a punta ─────────────────────────────


@pytest.mark.parametrize(
    "rama",
    [
        InternalLgdFractionalResponse(covariate_cols=("ltv", "plazo")),
        InternalLgdBetaRegression(covariate_cols=("ltv", "plazo")),
        InternalLgdWorkout(recovery_col="monto_recuperado"),
    ],
    ids=["fractional", "beta", "workout"],
)
def test_una_rama_modelada_produce_una_provision_completa(rama: Any) -> None:
    """Corre de punta a punta y publica una severidad por operación, no una del grupo."""
    frame = _cartera()
    resultado = _corre(_cfg(rama), frame)
    assert _provision(resultado) > 0
    assert len(resultado.detail.index) == len(frame.index)
    assert resultado.detail["lgd"].between(0.0, 1.0).all()
    # Una severidad MODELADA varía por operación: si saliera una sola, el ajuste no está entrando.
    assert resultado.detail["lgd"].nunique() > 1


def test_oraculo_de_efecto_discrimina_las_tres_ramas_modeladas() -> None:
    """D-RDY-ABA-2/3: mismo frame, tres dispatchers y tres vectores LGD distintos."""
    frame = _cartera(n=120, seed=31)
    branches = {
        "fractional_response": InternalLgdFractionalResponse(covariate_cols=("ltv", "plazo")),
        "beta_regression": InternalLgdBetaRegression(covariate_cols=("ltv", "plazo")),
        "workout": InternalLgdWorkout(recovery_col="monto_recuperado"),
    }
    outputs = {name: _corre(_cfg(branch), frame) for name, branch in branches.items()}

    assert set(outputs) == set(branches)
    for left, right in (
        ("fractional_response", "beta_regression"),
        ("fractional_response", "workout"),
        ("beta_regression", "workout"),
    ):
        left_lgd = outputs[left].detail["lgd"].to_numpy(dtype=float)
        right_lgd = outputs[right].detail["lgd"].to_numpy(dtype=float)
        assert not np.allclose(left_lgd, right_lgd)
        assert _provision(outputs[left]) != _provision(outputs[right])


def test_la_severidad_modelada_no_exige_la_columna_de_lgd_en_el_archivo() -> None:
    """El objetivo lo valida el motor de LGD: exigir además ``lgd_col`` sería cobrarla dos veces.

    Control negativo en la misma prueba: la rama OBSERVADA sobre el mismo archivo sin esa columna
    **sí** tiene que fallar, porque ahí la severidad es esa celda.
    """
    frame = _cartera().drop(columns=["lgd"])
    rama = InternalLgdFractionalResponse(covariate_cols=("ltv",), recovery_col="tasa_recuperada")
    assert _provision(_corre(_cfg(rama), frame)) > 0

    with pytest.raises(InternalInputError, match="lgd"):
        _corre(_cfg(InternalLgdProvided()), frame)


def test_misma_severidad_por_columna_y_por_modelo_da_la_misma_provision() -> None:
    """D-LGD-5: la conversión a ``Decimal`` es la MISMA función, así que no hay canal nuevo.

    🔴 El puente se aísla del ajuste, que es lo único que hace falsable la afirmación: se toma la
    severidad que el modelo produjo, se escribe TAL CUAL en una columna y se corre la rama
    OBSERVADA sobre ella. Si el puente fuese fiel, las dos provisiones son idénticas al último
    decimal; si difiriesen, la diferencia sería del puente y no del modelo, porque el número que
    entra es el mismo.

    ⚠️ Un primer intento hizo degenerar el ajuste (severidad constante) para que reprodujera el
    dato, y el motor lo rechazó correctamente con «separación perfecta»: un modelo que no puede
    fallar tampoco puede probar nada.
    """
    frame = _cartera(n=80)
    rama = InternalLgdFractionalResponse(covariate_cols=("ltv", "plazo"))
    severidad = _severity_by_row(frame, cfg=_cfg(rama))
    assert severidad is not None

    espejo = frame.copy(deep=True)
    espejo["lgd_del_modelo"] = [severidad[label] for label in espejo.index]

    por_modelo = _provision(_corre(_cfg(rama), frame))
    por_columna = _provision(_corre(_cfg(InternalLgdProvided(lgd_col="lgd_del_modelo")), espejo))
    assert por_modelo == por_columna, (
        f"por modelo {por_modelo} y por columna {por_columna} con EL MISMO número de entrada: la "
        "diferencia sólo puede venir del puente a Decimal, que D-LGD-5 declara compartido"
    )


def test_el_piso_y_el_techo_de_la_rama_modelada_acotan_de_verdad() -> None:
    """D-LGD-6: el motor acota y ``_parse_rows`` re-aplica los MISMOS valores ⇒ idempotente.

    Control negativo: sin piso ni techo, la misma corrida deja severidades fuera de la banda.
    """
    frame = _cartera()
    rama = InternalLgdFractionalResponse(covariate_cols=("ltv", "plazo"))
    sin_banda = _corre(_cfg(rama), frame).detail["lgd"]
    assert sin_banda.min() < 0.45 or sin_banda.max() > 0.55, (
        "el control negativo no controla nada: sin banda la severidad ya cabía dentro"
    )

    acotada = InternalLgdFractionalResponse(
        covariate_cols=("ltv", "plazo"), lgd_floor=0.45, lgd_cap=0.55
    )
    con_banda = _corre(_cfg(acotada), frame).detail["lgd"]
    assert con_banda.between(0.45, 0.55).all()


# ───────────────────────────── la política de huecos (D-LGD-8) ─────────────────────────────


@pytest.mark.parametrize("flag", [True, False], ids=["aborta", "imputa"])
def test_fail_on_falta_dato_no_gobierna_el_ajuste(flag: bool) -> None:
    """Un hueco en una covariable detiene SIEMPRE, con el flag encendido o apagado.

    🔴 Es la mitad importante de D-LGD-8: imputar cero en una covariable no dañaría una fila,
    sesgaría el ajuste y contaminaría a TODAS. El flag gobierna datos que la institución no tiene,
    no insumos de un modelo.

    Control negativo dentro del mismo test: con el hueco en la COLUMNA de severidad —rama
    observada— el flag sí manda, y apagarlo deja la corrida terminar.
    """
    frame = _cartera(n=40)
    frame.loc[frame.index[3], "ltv"] = np.nan
    rama = InternalLgdFractionalResponse(covariate_cols=("ltv",))
    with pytest.raises(LgdError):
        _corre(_cfg(rama, fail_on_falta_dato=flag), frame)

    observado = _cartera(n=40)
    observado.loc[observado.index[3], "lgd"] = np.nan
    if flag:
        with pytest.raises(InternalInputError):
            _corre(_cfg(InternalLgdProvided(), fail_on_falta_dato=True), observado)
    else:
        assert (
            _provision(_corre(_cfg(InternalLgdProvided(), fail_on_falta_dato=False), observado)) > 0
        )


# ───────────────────────────── el config rechaza lo inejecutable ─────────────────────────────


def test_una_regresion_sin_variables_no_se_puede_construir() -> None:
    """Un ajuste sin covariables no es un ajuste: se rechaza en el config, no en la corrida.

    Es el precedente de ``IfrsLgdConfig``, que ya lo exige; con la unión la regla deja de ser
    condicional porque la rama ES el método.
    """
    with pytest.raises(InternalConfigError, match="covariate_cols"):
        InternalLgdBetaRegression()
    with pytest.raises(InternalConfigError, match="covariate_cols"):
        InternalLgdFractionalResponse(covariate_cols=("  ",))


def test_los_recuperos_exigen_lo_recuperado() -> None:
    """Sin la columna de monto recuperado no hay severidad que calcular."""
    with pytest.raises(InternalConfigError, match="recovery_col"):
        InternalLgdWorkout()


# ───────────────────────────── el informe lo dice (D-LGD-10) ─────────────────────────────


def _metodos_del_motor() -> frozenset[str]:
    """Los discriminadores que el config acepta, leídos del motor y no de una lista escrita al lado.

    ⚠️ Pydantic **desenvuelve el ``Annotated``**: ``model_fields['lgd'].annotation`` es ya la unión
    desnuda (``types.UnionType``) y el ``Field(discriminator=...)`` viaja aparte. Un primer intento
    bajó un nivel de más buscando el ``Annotated`` y devolvió el conjunto **vacío** — que es
    exactamente lo que el ancla anti-vacua de este gate existe para no dejar pasar.
    """
    ramas = get_args(InternalProvisioningConfig.model_fields["lgd"].annotation)
    return frozenset(str(get_args(rama.model_fields["method"].annotation)[0]) for rama in ramas)


def test_toda_forma_de_obtener_la_lgd_tiene_su_frase_en_el_informe() -> None:
    """Gate bidireccional: ni un método sin etiqueta, ni una etiqueta sin método detrás.

    🔴 Cierra la clase, no el caso. El defecto que D-LGD-10 corrige es que el informe **nunca**
    nombró el método de LGD; sin este gate, la sexta forma que alguien añada vuelve a salir muda y
    nada se pondría rojo, porque el fallback la nombra en crudo y el capítulo no queda vacío.
    """
    del_motor = _metodos_del_motor()
    etiquetadas = frozenset(_INTERNAL_LGD_LABELS)
    assert len(del_motor) == 5, f"el motor acepta {sorted(del_motor)}: ¿cambió la unión?"
    assert del_motor == etiquetadas, (
        f"el motor acepta {sorted(del_motor)} y el informe etiqueta {sorted(etiquetadas)}. Un "
        "método sin frase sale con su literal técnico en un documento que lee un regulador; una "
        "frase sin método detrás describe algo que ya no existe"
    )
    assert del_motor >= _INTERNAL_LGD_AJUSTADAS, (
        "la salvedad in-sample apunta a un método que el motor no acepta"
    )


def test_solo_las_ajustadas_arrastran_la_salvedad_in_sample() -> None:
    """D-LGD-9 aplica a lo que AJUSTA parámetros, no a lo que descuenta flujos observados.

    Control negativo incluido: los recuperos y las dos ramas observadas **no** deben traerla, o la
    salvedad se lee como boilerplate y deja de significar nada.
    """
    for metodo in _metodos_del_motor():
        card = {"metric_sections": {"provisioning_internal": {"lgd_method": metodo}}}
        parrafos = _internal_lgd_paragraphs(card)
        trae = any("fuera de la muestra" in p for p in parrafos)
        assert trae is (metodo in _INTERNAL_LGD_AJUSTADAS), (
            f"'{metodo}' {'debía' if metodo in _INTERNAL_LGD_AJUSTADAS else 'NO debía'} traer la "
            f"salvedad in-sample; publicó {parrafos}"
        )


def test_con_tasa_de_perdida_directa_el_informe_calla_sobre_la_lgd() -> None:
    """Sin descomponer la pérdida no hay método de LGD que afirmar: la card publica ``None``."""
    assert (
        _internal_lgd_paragraphs(
            {"metric_sections": {"provisioning_internal": {"lgd_method": None}}}
        )
        == ()
    )


def test_la_frase_del_informe_sale_de_una_corrida_de_verdad() -> None:
    """Ancla anti-vacua: la card real de una corrida modelada alimenta la prosa sin adaptadores."""
    frame = _cartera(n=50)
    resultado = _corre(_cfg(InternalLgdBetaRegression(covariate_cols=("ltv",))), frame)
    parrafos = _internal_lgd_paragraphs(resultado.card.model_dump(mode="json"))
    assert any("regresión beta" in p for p in parrafos), parrafos
    assert any("fuera de la muestra" in p for p in parrafos), parrafos


# ───────────────────── el gate de ACEPTACIÓN de P4 (D-LGD-12) ─────────────────────


@pytest.mark.parametrize(
    ("rama_modelada", "reproduce_la_columna"),
    [
        (
            {
                "method": "fractional_response",
                "covariate_cols": ["deuda_ingreso", "utilizacion_linea"],
            },
            False,
        ),
        ({"method": "workout", "recovery_col": "monto_recuperado"}, True),
    ],
    ids=["fractional", "workout"],
)
def test_aceptacion_una_corrida_completa_con_la_rama_modelada(
    tmp_path: Path, rama_modelada: dict[str, Any], reproduce_la_columna: bool
) -> None:
    """🔴 El gate de aceptación de P4, tal como D-LGD-12 lo define.

    ⚠️ **No** es que ``lgd_modelada`` aparezca disponible: ese gate arma el esqueleto desde los
    defaults efectivos, o sea con ``method="provided"``, y se pondría verde **sin ejercitar una sola
    vez** una rama modelada. Lo que se exige aquí es una corrida end-to-end que llegue a ``done``
    por la puerta pública, con su informe escrito, y con la provisión comparada contra el mismo dato
    por la rama observada.

    La comparación contra la observada es la mitad que importa: una corrida modelada que produjera
    exactamente la misma cifra que la columna significaría que el ajuste no está entrando en el
    número, y eso pasaría por «verde» sin ella.
    """
    pytest.importorskip("statsmodels")
    trabajo = tmp_path / "run"
    trabajo.mkdir()

    preset = get_preset("f5-provision-interna-generica")
    origen = materialize(preset["dataset_id"], workdir=trabajo)
    frame = pd.read_parquet(origen)
    # El dataset del catálogo no trae los insumos de recuperos —es el de la severidad observada—,
    # así que para esa rama se derivan del propio dato, sin inventar señal: lo recuperado es
    # exactamente el complemento de la LGD que el archivo ya declara, y sin costos ni descuento el
    # enfoque tiene que reproducirla. Que ASÍ la reproduzca es su control positivo.
    if rama_modelada["method"] == "workout":
        frame["monto_recuperado"] = (frame["exposure_amount"] * (1.0 - frame["lgd"])).round(6)
        frame["ead"] = frame["exposure_amount"]
        frame["recovery_cost"] = 0.0
        frame["recovery_time_years"] = 0.0
        frame["contractual_rate"] = 0.05
        # Columna alterna con costo REAL, para el control negativo de la identidad de abajo.
        frame["costo"] = (frame["exposure_amount"] * 0.02).round(6)
    ruta = trabajo / "cartera.parquet"
    frame.to_parquet(ruta)

    # 🔴 La PD se INYECTA en vez de calcularse, y por dos razones que se refuerzan. La primera es
    # de fidelidad: es exactamente lo que hace este trabajo en producción —su `external_input` es
    # «la PD calibrada de tu modelo»—, así que la corrida que se mide aquí es la real y no una
    # maqueta. La segunda es que ajustar el binning de verdad dentro de pytest **tumba el runner**
    # con un segfault (trampa documentada del repo); un primer intento corrió la cadena completa del
    # preset y se cayó así, sin dejar un fallo que leer.
    rng = np.random.default_rng(4)
    pd_frame = pd.DataFrame(
        {"pd_calibrated": rng.beta(2, 18, len(frame)).round(6)}, index=frame.index
    )

    def _corrida(lgd: dict[str, Any], salida: str) -> Any:
        config = json.loads(json.dumps(preset["config"]))
        config["data"] = {**config["data"], "load": {**config["data"]["load"], "source": str(ruta)}}
        config["provisioning_internal"] = {
            **config["provisioning_internal"],
            "lgd": lgd,
            # Con la PD inyectada el agrupamiento por banda de score no aporta nada y ata el gate a
            # los cuantiles de una PD sintética: se agrupa por un segmento que el archivo ya trae.
            "grouping": "segment",
            "group_col": "segmento",
        }
        config["run"] = {"steps": ["data", "provisioning_internal", "report"]}
        config["report"] = {
            **config.get("report", {}),
            "output_dir": str(trabajo / salida),
            # El preset exige los siete capítulos del scorecard, y esta corrida no lo ajusta: se
            # deja la lista vacía para que el informe emita lo que la corrida SÍ produjo. El
            # capítulo de provisiones no se pide aquí porque no es obligatorio sino condicional —lo
            # gatea el propio builder según los dominios presentes—, y exigirlo escondería que se
            # emitió por la razón correcta.
            "sections": {"required_sections": []},
        }
        return nikodym.run(
            NikodymConfig.model_validate(config),
            artifacts={("calibration", "calibrated_pd_frame"): pd_frame},
        )

    observada = _corrida({"method": "provided", "lgd_col": "lgd"}, "observada")
    modelada = _corrida(rama_modelada, "modelada")

    for nombre, study in (("observada", observada), ("modelada", modelada)):
        assert study.run_context.status == "done", (
            f"la corrida {nombre} no terminó: {study.run_context.status} / "
            f"{getattr(study.run_context, 'error', None)}"
        )

    card_obs = observada.artifacts.get("provisioning_internal", "card")
    card_mod = modelada.artifacts.get("provisioning_internal", "card")
    assert card_mod.total_internal_provision > 0
    seccion = card_mod.metric_sections["provisioning_internal"]
    assert seccion["lgd_method"] == rama_modelada["method"]
    assert card_obs.metric_sections["provisioning_internal"]["lgd_method"] == "provided"

    # 🔴 La comparación contra la rama observada es la mitad que importa, y cada rama tiene su
    # relación ESPERADA en vez de una genérica «tienen que diferir». Con la genérica, el enfoque de
    # recuperos salía rojo por ser CORRECTO: alimentado con el complemento exacto de la LGD, costo
    # cero y tiempo cero, `1 - PV(recuperos)/EAD` es algebraicamente la columna, y reproducirla al
    # centavo prueba la cadena entera —motor de LGD, mapa por etiqueta, puente a Decimal y
    # agregación— mucho mejor que una diferencia cualquiera.
    if reproduce_la_columna:
        assert card_mod.total_internal_provision == card_obs.total_internal_provision, (
            f"con costos y tiempo cero sobre el complemento exacto de la LGD, el enfoque de "
            f"recuperos DEBE reproducir la columna al centavo: dio "
            f"{card_mod.total_internal_provision} contra {card_obs.total_internal_provision}"
        )
        # …y su control negativo: si la identidad se cumpliera porque la rama está leyendo la
        # columna en vez de calcular, meter un costo real no movería nada.
        con_costo = _corrida({**rama_modelada, "workout_cost_col": "costo"}, "con_costo")
        assert con_costo.run_context.status == "done", con_costo.run_context.status
        card_costo = con_costo.artifacts.get("provisioning_internal", "card")
        assert card_costo.total_internal_provision > card_obs.total_internal_provision, (
            "añadir un costo de recuperación no movió la provisión: la rama no está calculando, "
            "está leyendo la columna de LGD"
        )
    else:
        assert card_mod.total_internal_provision != card_obs.total_internal_provision, (
            "la rama modelada produjo la MISMA provisión que la columna: el ajuste no está "
            "entrando en la cifra, y sin esta comparación la corrida pasaría por verde igual"
        )

    # El informe existe y NOMBRA el método (D-LGD-10): un capítulo mudo sobre el origen de la
    # severidad es el defecto preexistente que este paso cierra.
    reporte = modelada.artifacts.get("report", "result")
    html = Path(reporte.html_path).read_text(encoding="utf-8")
    assert "severidad" in html.lower(), "el informe no dice nada del origen de la severidad"


# ───────── lo que la revisión adversarial destapó, cada uno con su control ─────────


def test_la_frase_del_informe_sobre_recuperos_no_esta_invertida() -> None:
    """🔴 El copy decía `PV/exposición`, que es la TASA DE RECUPERACIÓN, no la severidad.

    El motor calcula ``1 - PV/EAD`` (`lgd.py:245-246`), o sea el complemento exacto. La frase
    publicaba la cifra invertida en el documento que lee un tercero, sobre toda la cartera y sin
    ningún error. Aquí se ata la frase a la aritmética con un caso calculado a mano.

    Con recuperado=50, costo=1, exposición=100, tasa=0,05 y un año:
        PV = (50 - 1) / 1,05 = 46,666…   →   LGD = 1 - 46,666…/100 = 0,5333…
    La lectura literal de la frase vieja daba 0,4667, que es su complemento.
    """
    frame = pd.DataFrame(
        {
            "rec": [50.0],
            "ead": [100.0],
            "recovery_cost": [1.0],
            "recovery_time_years": [1.0],
            "contractual_rate": [0.05],
        }
    )
    rama = InternalLgdWorkout(recovery_col="rec")
    lgd = float(LgdEngine.from_config(rama).estimate(frame)["lgd"].iloc[0])
    assert abs(lgd - 0.5333333333333333) < 1e-12, lgd

    etiqueta = _INTERNAL_LGD_LABELS["workout"]
    assert "uno menos" in etiqueta, (
        f"la frase del informe no dice que se toma el complemento y por tanto describe la tasa de "
        f"recuperación, no la severidad: {etiqueta!r}"
    )


def test_la_traza_de_auditoria_declara_la_procedencia_real_de_la_severidad() -> None:
    """La traza es lo que un validador lee para reconstruir la corrida (D-LGD-4).

    Registraba ``lgd_col`` sin condición, así que con la severidad modelada afirmaba una
    procedencia falsa —y una que la propia rama declara inerte— contradiciendo al capítulo del
    informe. Se comprueban las cuatro formas de procedencia.
    """
    observada = _procedencia_de_la_lgd(_cfg(InternalLgdProvided()))
    assert observada == {"aplicada": True, "origen": "columna", "lgd_col": "lgd"}

    regresion = _procedencia_de_la_lgd(
        _cfg(InternalLgdFractionalResponse(covariate_cols=("ltv", "plazo")))
    )
    assert regresion["origen"] == "modelada"
    assert regresion["covariate_cols"] == ["ltv", "plazo"], regresion
    assert "lgd_col" not in regresion, (
        "la traza sigue nombrando una columna como origen de una severidad modelada"
    )

    recuperos = _procedencia_de_la_lgd(_cfg(InternalLgdWorkout(recovery_col="monto_recuperado")))
    assert recuperos["origen"] == "modelada"
    assert "monto_recuperado" in recuperos["columnas"], recuperos

    directa = _procedencia_de_la_lgd(
        _cfg(InternalLgdProvided(), method="direct_loss_rate", loss_rate_col="lgd")
    )
    assert directa == {"aplicada": False, "origen": "no_aplica"}


@pytest.mark.parametrize(
    "rama",
    [InternalLgdFractionalResponse, InternalLgdWorkout],
    ids=["regresion", "workout"],
)
def test_una_columna_de_recuperacion_en_blanco_se_rechaza_en_el_config(rama: Any) -> None:
    """Una cadena vacía no es «no la declaré»: el motor la busca y aborta (misma clase que 'cp').

    🔴 Y hace daño dos veces: ``columnas_inactivas()`` decide por ``is not None``, así que con
    ``''`` suprimía el requisito de ``lgd_col`` en el preflight — le callaba al usuario la única
    columna con la que su corrida podía funcionar. El control negativo es que un nombre real sí
    construye.
    """
    extra = {"covariate_cols": ("ltv",)} if rama is InternalLgdFractionalResponse else {}
    with pytest.raises(InternalConfigError, match="recovery_col"):
        rama(recovery_col="   ", **extra)
    assert rama(recovery_col="tasa_recuperada", **extra).recovery_col == "tasa_recuperada"


def test_una_columna_de_recuperos_en_blanco_se_rechaza_en_el_config() -> None:
    """Las cuatro columnas del proceso de recuperación tampoco admiten un nombre vacío."""
    with pytest.raises(InternalConfigError, match="workout_ead_col"):
        InternalLgdWorkout(recovery_col="rec", workout_ead_col="  ")


def test_la_guarda_de_severidad_ausente_se_ejercita_directamente() -> None:
    """La guarda es defensa en profundidad, y su test la llama a mano en vez de fingir cobertura.

    ⚠️ Medido: por la ruta real es **inalcanzable**. ``LgdEngine._finalize`` exige
    ``numpy.isfinite`` antes de devolver, y ``_decimal_or_none`` sólo da ``None`` ante nulo o
    cadena vacía, así que ningún float finito produce ninguno de los dos. Se conserva —el mapa de
    severidad viene de fuera de esta función y su contrato no lo impone el tipo— pero se ejercita
    de verdad, que es el precedente del repo con la guarda del transformer de binning: código que
    no se puede alcanzar por la puerta normal no se deja con la cobertura fingida.
    """
    frame = _cartera(n=3)
    with pytest.raises(InternalInputError, match="no produjo severidad"):
        _parse_rows(
            frame,
            cfg=_cfg(InternalLgdFractionalResponse(covariate_cols=("ltv",))),
            pd_by_row=dict.fromkeys(frame.index, 0.05),
            severity_by_row=dict.fromkeys(frame.index),
            pandas=pd,
        )


def test_la_union_sigue_discriminando_por_method() -> None:
    """Un config por dict elige la rama por su discriminador, en las cinco formas."""
    esperado = {
        "provided": InternalLgdProvided,
        "group_historical": InternalLgdGroupHistorical,
        "beta_regression": InternalLgdBetaRegression,
        "fractional_response": InternalLgdFractionalResponse,
        "workout": InternalLgdWorkout,
    }
    extra: dict[str, dict[str, Any]] = {
        "beta_regression": {"covariate_cols": ["ltv"]},
        "fractional_response": {"covariate_cols": ["ltv"]},
        "workout": {"recovery_col": "monto_recuperado"},
    }
    for metodo, clase in esperado.items():
        cfg = InternalProvisioningConfig.model_validate(
            {"lgd": {"method": metodo, **extra.get(metodo, {})}}
        )
        assert type(cfg.lgd) is clase, f"'{metodo}' debía discriminar a {clase.__name__}"
