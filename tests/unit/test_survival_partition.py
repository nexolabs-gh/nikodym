"""La partición de ``survival``: un solo objeto, y ningún ajuste que cambie de población callado.

Dos contratos conviven aquí porque son el mismo defecto visto por sus dos caras.

**Unificación (D-INV-9).** El literal ``"partition"`` estaba escrito tres veces dentro de la capa
—``discrete_hazard``, ``cox_aft`` y ``step``— y ``"desarrollo"``, dos. Comparar strings no sirve
para vigilarlo: dos literales iguales pasan cualquier ``==`` y se separan en el momento en que
alguien edita uno. Por eso los asserts son de **identidad** (``is``). Un segundo bloque ata
``survival`` a ``nikodym.data.partition``, que es quien *escribe* la columna: ``survival`` no puede
importarla en top-level sin arrastrar pandas a su grafo de importación (ver el docstring de
``nikodym.survival.partition``), así que la atadura se paga aquí, donde importar pandas es gratis, y
se mide en los dos sentidos.

**Alcance del ajuste.** ``_fit_mask`` tenía **dos** salidas mudas —sin columna de partición, y con
columna pero sin ninguna fila ``desarrollo``— y las dos ajustaban sobre la población completa. La
primera es contrato de SDD-18 y se mantiene, pero ahora **se publica** en ``fit_scope_``. La segunda
levanta: los tests numéricos de este archivo son la razón, porque miden que ajustar sobre todo en
vez de sobre Desarrollo **cambia el signo del coeficiente**.
"""

from __future__ import annotations

import pathlib
from typing import Any

import numpy as np
import pandas as pd
import pytest

from nikodym.data.partition import PARTITION_COL as DATA_PARTITION_COL
from nikodym.data.partition import Partition
from nikodym.survival import cox_aft as cox_module
from nikodym.survival import discrete_hazard as dh_module
from nikodym.survival import partition as partition_module
from nikodym.survival import step as step_module
from nikodym.survival.config import (
    CoxAftConfig,
    SurvivalConfig,
    SurvivalInputConfig,
)
from nikodym.survival.cox_aft import AFTSurvivalModel, CoxPHSurvivalModel
from nikodym.survival.discrete_hazard import DiscreteTimeHazardModel
from nikodym.survival.exceptions import SurvivalInputError
from nikodym.survival.partition import (
    PARTITION_COL,
    PARTITION_DESARROLLO,
    SCOPE_DESARROLLO,
    SCOPE_POBLACION_COMPLETA,
    fit_mask,
)

# ---------------------------------------------------------------- unificación del literal


def test_los_tres_modulos_usan_el_mismo_objeto_no_un_string_igual() -> None:
    """``is``, no ``==``: un literal reescrito pasaría la igualdad y rompería la unificación."""
    assert dh_module._PARTITION_COL is PARTITION_COL
    assert cox_module._PARTITION_COL is PARTITION_COL
    assert step_module._PARTITION_COL is PARTITION_COL
    assert dh_module._fit_mask is fit_mask
    assert cox_module._fit_mask is fit_mask


def test_ningun_modulo_de_survival_reescribe_el_literal() -> None:
    """El fuente de la capa no vuelve a declarar la constante fuera de su módulo canónico."""
    canonico = pathlib.Path(partition_module.__file__)
    paquete = canonico.parent
    reincidencias = ('= "partition"', '= "desarrollo"')
    ofensores = sorted(
        archivo.name
        for archivo in paquete.glob("*.py")
        if archivo != canonico
        and any(texto in archivo.read_text(encoding="utf-8") for texto in reincidencias)
    )
    assert ofensores == []


def test_la_capa_que_lee_y_la_que_escribe_la_columna_no_pueden_separarse() -> None:
    """Bidireccional contra ``data``: si allá se renombra, aquí enrojece antes de fallar callado."""
    assert PARTITION_COL == DATA_PARTITION_COL
    assert Partition.DESARROLLO.value == PARTITION_DESARROLLO
    assert PARTITION_DESARROLLO in {miembro.value for miembro in Partition}


# ---------------------------------------------------------------- la máscara, en aislamiento


def _mask_frame(particiones: list[str | None]) -> pd.DataFrame:
    return pd.DataFrame({PARTITION_COL: particiones, "x": range(len(particiones))})


def test_sin_columna_el_alcance_es_la_poblacion_completa() -> None:
    """Contrato SDD-18: el standalone descarta la columna a propósito, y el alcance se declara."""
    frame = _mask_frame(["desarrollo", "holdout"]).drop(columns=[PARTITION_COL])
    mask, scope = fit_mask(frame, np=np)

    assert mask.tolist() == [True, True]
    assert scope == SCOPE_POBLACION_COMPLETA


def test_con_columna_solo_entra_desarrollo() -> None:
    mask, scope = fit_mask(_mask_frame(["desarrollo", "holdout", "oot", "desarrollo"]), np=np)

    assert mask.tolist() == [True, False, False, True]
    assert scope == SCOPE_DESARROLLO


def test_missing_en_la_particion_es_error() -> None:
    with pytest.raises(SurvivalInputError, match=PARTITION_COL):
        fit_mask(_mask_frame(["desarrollo", None]), np=np)


@pytest.mark.parametrize(
    "etiquetas",
    [
        pytest.param(["holdout", "oot"], id="solo-otras-particiones"),
        pytest.param(["Desarrollo", "Desarrollo"], id="mayuscula"),
        pytest.param(["dev", "dev"], id="vocabulario-propio"),
    ],
)
def test_columna_presente_sin_desarrollo_levanta_y_nombra_lo_observado(
    etiquetas: list[str | None],
) -> None:
    """El caso que ajustaba sobre todo contradiciendo la columna del propio usuario.

    El mensaje enumera las etiquetas observadas porque el motivo más probable es de vocabulario
    (``dev``, ``Desarrollo``) y sin verlas el usuario no sabe qué renombrar.
    """
    with pytest.raises(SurvivalInputError) as excinfo:
        fit_mask(_mask_frame(etiquetas), np=np)

    mensaje = str(excinfo.value)
    assert PARTITION_DESARROLLO in mensaje
    for etiqueta in set(etiquetas):
        assert str(etiqueta) in mensaje


# ---------------------------------------------------------------- por qué importa: los números


def _muestra_dev_holdout_con_efecto_opuesto() -> pd.DataFrame:
    """Dev y Holdout con el efecto de ``x`` en signo opuesto y la misma tasa base.

    Mezclarlos no «suaviza» el coeficiente: lo lleva a cero. Es la forma más legible de demostrar
    que ajustar sobre la población equivocada no es un matiz de precisión.
    """
    rng = np.random.default_rng(20260802)
    filas: list[dict[str, Any]] = []
    for particion, beta, n in ((PARTITION_DESARROLLO, 2.0, 300), ("holdout", -2.0, 300)):
        x = rng.normal(size=n)
        hazard = 1.0 / (1.0 + np.exp(-(-1.2 + beta * x)))
        for posicion in range(n):
            duracion, evento = 6, 0
            for periodo in range(1, 7):
                if rng.random() < hazard[posicion]:
                    duracion, evento = periodo, 1
                    break
            filas.append(
                {
                    PARTITION_COL: particion,
                    "x": float(x[posicion]),
                    "duracion": duracion,
                    "evento": evento,
                }
            )
    frame = pd.DataFrame(filas)
    frame.index = pd.Index([f"op{i:04d}" for i in range(len(frame))], name="row_id")
    return frame


def _cfg(method: str) -> SurvivalConfig:
    return SurvivalConfig(
        method=method,  # type: ignore[arg-type]
        input=SurvivalInputConfig(
            duration_col="duracion",
            event_col="evento",
            pd_source="none",
            covariate_cols=("x",),
        ),
        cox_aft=CoxAftConfig(ph_p_value_threshold=0.05, aft_family="weibull"),
        fail_on_falta_dato=False,
    )


def _ajustar(method: str, frame: pd.DataFrame) -> Any:
    clases = {
        "discrete_hazard": DiscreteTimeHazardModel,
        "cox_ph": CoxPHSurvivalModel,
        "aft": AFTSurvivalModel,
    }
    modelo = clases[method].from_config(_cfg(method))
    return modelo.fit(frame, duration_col="duracion", event_col="evento", covariate_cols=("x",))


def _beta_x(method: str, modelo: Any) -> float:
    if method == "discrete_hazard":
        return float(modelo.params_["x"])
    parametros = modelo.fitter_.params_
    return float(
        parametros["x"] if "x" in parametros.index else parametros.xs("x", level=-1).iloc[0]
    )


@pytest.mark.parametrize("method", ["discrete_hazard", "cox_ph"])
def test_ajustar_sobre_todo_en_vez_de_sobre_desarrollo_cambia_el_coeficiente(method: str) -> None:
    """El silencio no era cosmético: el signo del efecto se invierte hacia cero.

    Es el ancla numérica del arreglo. Sin ella, «ajusta sobre la población entera» se lee como un
    detalle de implementación; medido, el coeficiente de Desarrollo (~+1,3 a +1,9) cae a ~0.
    """
    frame = _muestra_dev_holdout_con_efecto_opuesto()
    sobre_desarrollo = _beta_x(method, _ajustar(method, frame))
    sobre_todo = _beta_x(method, _ajustar(method, frame.drop(columns=[PARTITION_COL])))

    assert sobre_desarrollo > 1.0
    assert abs(sobre_todo) < 0.2
    assert abs(sobre_desarrollo - sobre_todo) > 1.0


@pytest.mark.parametrize("method", ["discrete_hazard", "cox_ph", "aft"])
def test_los_tres_motores_levantan_cuando_la_particion_no_trae_desarrollo(method: str) -> None:
    """Fallback 2, por la ruta real de cada motor: ninguno ajusta sobre todo en silencio."""
    frame = _muestra_dev_holdout_con_efecto_opuesto().assign(**{PARTITION_COL: "holdout"})

    with pytest.raises(SurvivalInputError, match=PARTITION_DESARROLLO):
        _ajustar(method, frame)


@pytest.mark.parametrize("method", ["discrete_hazard", "cox_ph", "aft"])
def test_los_tres_motores_publican_el_alcance_del_ajuste(method: str) -> None:
    """Fallback 1: se mantiene, pero deja de ser indistinguible de un ajuste sobre Desarrollo.

    ``n_fit_rows_ == n_rows_`` no alcanza para distinguirlos: da lo mismo con el libro completo que
    con una cartera enteramente de Desarrollo.
    """
    frame = _muestra_dev_holdout_con_efecto_opuesto()

    con_particion = _ajustar(method, frame)
    sin_particion = _ajustar(method, frame.drop(columns=[PARTITION_COL]))

    assert con_particion.fit_scope_ == SCOPE_DESARROLLO
    assert con_particion.n_fit_rows_ == 300
    assert sin_particion.fit_scope_ == SCOPE_POBLACION_COMPLETA
    assert sin_particion.n_fit_rows_ == len(frame)
