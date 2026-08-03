"""Gate de PARIDAD: el formulario y el motor no pueden contradecirse sobre una columna (D-PRO-7).

🔴 El defecto que cierra se vio en la pantalla, no en un test. Con
``survival.input.event_col = "target"`` el campo se pintaba en rojo —«Esa columna no está en el
dataset cargado»— mientras ``check_dataset`` decía ``compatible=True`` y la corrida llegaba a
``done``. Dos superficies del mismo producto afirmando lo contrario en la misma pantalla, y el
usuario sin forma de saber cuál miente.

Nació de una mejora: D-RAM-6 le enseñó al backend que ``data`` escribe cuatro columnas al frame y
que exigirlas del archivo es un falso positivo. El front no se enteró, y no eran dos campos sino
**32 de las 47 rutas** con ``column_role: "input"``. No existía ningún gate que cruzara las dos
superficies: es el que faltaba el día que D-RAM-6 entró.

⚠️ **El oráculo se escribe A MANO y aparte.** Derivar lo que el front ofrecería llamando a la misma
función que usa el backend mediría que la función es determinista, no que las dos superficies
coinciden — el gate autorreferencial que este repo ya pagó dos veces. Aquí
``_OFRECIBLES_POR_SECCION`` está escrito desde ``data/step.py`` y desde el config del test, y el
primer test lo contrasta contra lo que el backend publica.
"""

from __future__ import annotations

import pytest

import nikodym
from nikodym.core.config import NikodymConfig
from nikodym.core.config.schema import cargar_configs_de_dominio
from nikodym.core.dataset_check import columnas_producidas_por_seccion

#: Las columnas que trae el archivo del usuario. Ninguna se llama como una derivada, a propósito.
_COLUMNAS_ARCHIVO = ("ingreso", "mora", "fecha_obs", "duracion")

#: Las cuatro que ``DataStep`` escribe al final de su paso (``data/step.py:77-80``): el
#: ``target_col`` del config —aquí el default ``"target"``— más las tres constantes de sus módulos.
#: Escritas a mano desde el motor, no importadas: si alguien renombra una, este gate tiene que
#: enterarse por el rojo y no seguir el cambio en silencio.
_DERIVADAS = ("target", "label_status", "partition", "ttd")

#: 🔴 El oráculo. Qué nombres puede ofrecer (y aceptar sin rojo) un campo de cada sección.
#: ``data`` NO se acredita las suyas (D-RAM-7): ``DataStep`` valida su esquema en el primer chequeo
#: del primer paso, mucho antes de que el particionador escriba nada.
_OFRECIBLES_POR_SECCION: dict[str, frozenset[str]] = {
    "data": frozenset(_COLUMNAS_ARCHIVO),
    "survival": frozenset(_COLUMNAS_ARCHIVO) | frozenset(_DERIVADAS),
    "stability": frozenset(_COLUMNAS_ARCHIVO) | frozenset(_DERIVADAS),
    "binning": frozenset(_COLUMNAS_ARCHIVO) | frozenset(_DERIVADAS),
}


def _config(**secciones: object) -> NikodymConfig:
    """Config mínimo con ``data`` activa (la única que produce columnas hoy)."""
    cargar_configs_de_dominio()
    base: dict[str, object] = {
        "data": {
            "target": {"bad_rule": {"all_of": [{"col": "mora", "op": ">", "value": 90}]}},
            "partition": {"strategy": {"type": "random"}},
        },
    }
    return NikodymConfig.model_validate({**base, **secciones})


def test_lo_que_el_backend_publica_es_lo_que_el_oraculo_dice() -> None:
    """Ancla del contrato del payload, contra una lista escrita a mano desde el motor."""
    publicado = columnas_producidas_por_seccion(_config())
    assert set(publicado["data"]) == set(), "una sección no se acredita a sí misma (D-RAM-7)"
    for seccion in ("survival", "stability", "binning"):
        assert set(publicado[seccion]) == set(_DERIVADAS), seccion


#: (ruta del campo, sección, valor, ¿el backend debe acusarlo?). Los seis casos de D-PRO-6.
_CASOS: tuple[tuple[str, str, str, bool], ...] = (
    # Una columna del archivo: nadie la acusa, en ninguna sección.
    ("survival.input.event_col", "survival", "mora", False),
    ("data.schema.columns", "data", "mora", False),
    # Una columna que produce el pipeline, FUERA de la sección que la escribe: nadie la acusa.
    # Es el caso medido en pantalla, y el motivo de toda la enmienda.
    ("survival.input.event_col", "survival", "target", False),
    ("survival.input.event_col", "survival", "partition", False),
    # 🔴 La MISMA columna, DENTRO de `data`: se acusa, y tiene que seguir acusándose.
    ("data.schema.columns", "data", "partition", True),
    ("data.schema.columns", "data", "target", True),
    # Lo inventado se acusa siempre: el control negativo que impide que esto degrade a «nada se
    # acusa nunca», que pasaría todos los casos de arriba menos éste.
    ("survival.input.event_col", "survival", "columna_fantasma", True),
    ("data.schema.columns", "data", "columna_fantasma", True),
)


def _construir(ruta: str, valor: str) -> NikodymConfig:
    if ruta == "survival.input.event_col":
        return _config(survival={"input": {"duration_col": "duracion", "event_col": valor}})
    if ruta == "data.schema.columns":
        cfg = _config()
        datos = cfg.model_dump(mode="json", by_alias=True)["data"]
        datos["schema"] = {"columns": [{"name": valor, "dtype": "float"}]}
        return NikodymConfig.model_validate({"data": datos})
    raise AssertionError(f"caso no cubierto: {ruta}")


@pytest.mark.parametrize(("ruta", "seccion", "valor", "acusa"), _CASOS)
def test_el_backend_y_el_oraculo_del_front_dicen_lo_mismo(
    ruta: str, seccion: str, valor: str, acusa: bool
) -> None:
    """Para cada caso, ``check_dataset`` acusa **si y sólo si** el front lo pintaría en rojo."""
    veredicto = nikodym.check_dataset(_construir(ruta, valor), _COLUMNAS_ARCHIVO)
    acusado_por_el_motor = any(
        m.kind == "missing_column" and m.declared == valor for m in veredicto.mismatches
    )
    # Lo que el front hará: el valor no está entre lo que esa sección puede ofrecer.
    rojo_en_el_front = valor not in _OFRECIBLES_POR_SECCION[seccion]

    assert acusado_por_el_motor == acusa, (
        f"{ruta} = {valor!r}: el motor {'acusa' if acusado_por_el_motor else 'calla'} y se "
        f"esperaba lo contrario. Desajustes: {[(m.path, m.declared) for m in veredicto.mismatches]}"
    )
    assert rojo_en_el_front == acusado_por_el_motor, (
        f"{ruta} = {valor!r}: el formulario "
        f"{'lo pinta en rojo' if rojo_en_el_front else 'lo acepta'} y el motor "
        f"{'lo acusa' if acusado_por_el_motor else 'calla'}. Las dos superficies se contradicen "
        "en la pantalla, que es exactamente el defecto que D-PRO-7 existe para impedir."
    )


def test_el_indice_no_entra_en_lo_que_ofrece_un_campo_de_columna() -> None:
    """Un índice no es una columna, y ofrecerlo donde va una mata la corrida en el primer paso.

    ``data.schema.index_col`` comprueba el nombre de un índice **ya existente** y nunca hace
    ``set_index`` (``data/schema.py:36-39``), así que la simetría importa en los dos sentidos: una
    columna corriente ahí tampoco vale.
    """
    for seccion, ofrecibles in _OFRECIBLES_POR_SECCION.items():
        assert "loan_id" not in ofrecibles, seccion

    # Y el motor lo confirma: con el índice declarado y presente, no hay desajuste.
    cfg = _config()
    datos = cfg.model_dump(mode="json", by_alias=True)["data"]
    datos["schema"] = {"index_col": "loan_id"}
    veredicto = nikodym.check_dataset(
        NikodymConfig.model_validate({"data": datos}),
        _COLUMNAS_ARCHIVO,
        index_columns=("loan_id",),
    )
    assert [m.kind for m in veredicto.mismatches] == []

    # Control negativo: el mismo nombre como COLUMNA del archivo es un desajuste nombrado.
    veredicto_malo = nikodym.check_dataset(
        NikodymConfig.model_validate({"data": datos}),
        (*_COLUMNAS_ARCHIVO, "loan_id"),
        index_columns=(),
    )
    assert [m.kind for m in veredicto_malo.mismatches] == ["index_not_a_column"]
