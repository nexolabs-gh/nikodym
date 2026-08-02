"""La partición de ``survival`` vive en UN objeto, y está atada a la capa que la produce.

Gate de la clase que D-INV-9 ya condenó una vez: el literal ``"partition"`` estaba escrito tres
veces dentro de ``survival`` —``discrete_hazard``, ``cox_aft`` y ``step``— y ``"desarrollo"``, dos.
Comparar strings no sirve para vigilarlo: dos literales iguales pasan cualquier ``==`` y se separan
en el momento en que alguien edita uno. Por eso los asserts son de **identidad** (``is``).

El segundo bloque ata ``survival`` a ``nikodym.data.partition``, que es quien *escribe* la columna.
``survival`` no puede importarla en top-level sin arrastrar pandas a su grafo de importación (ver el
docstring de ``nikodym.survival.partition``), así que la atadura se paga aquí, donde importar pandas
es gratis, y se mide en los dos sentidos.
"""

from __future__ import annotations

import pathlib

import numpy as np
import pandas as pd
import pytest

from nikodym.data.partition import PARTITION_COL as DATA_PARTITION_COL
from nikodym.data.partition import Partition
from nikodym.survival import cox_aft as cox_module
from nikodym.survival import discrete_hazard as dh_module
from nikodym.survival import partition as partition_module
from nikodym.survival import step as step_module
from nikodym.survival.exceptions import SurvivalInputError
from nikodym.survival.partition import PARTITION_COL, PARTITION_DESARROLLO, fit_mask


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


def _frame(particiones: list[str | None]) -> pd.DataFrame:
    return pd.DataFrame({PARTITION_COL: particiones, "x": range(len(particiones))})


def test_sin_columna_el_ajuste_es_sobre_la_poblacion_completa() -> None:
    """Contrato SDD-18: el standalone descarta la columna a propósito."""
    frame = _frame(["desarrollo", "holdout"]).drop(columns=[PARTITION_COL])
    assert fit_mask(frame, np=np).tolist() == [True, True]


def test_con_columna_solo_entra_desarrollo() -> None:
    frame = _frame(["desarrollo", "holdout", "oot", "desarrollo"])
    assert fit_mask(frame, np=np).tolist() == [True, False, False, True]


def test_missing_en_la_particion_es_error() -> None:
    with pytest.raises(SurvivalInputError, match=PARTITION_COL):
        fit_mask(_frame(["desarrollo", None]), np=np)
