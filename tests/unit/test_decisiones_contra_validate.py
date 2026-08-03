"""El eslabón que el gate de vitest ASUME: que los `loc` reales casan (D-RES-2, D-RES-9).

`web/src/lib/jobs.test.ts` construye el `ValidationState` **a mano**, con los `loc` medidos contra
el motor y escritos en su tabla. Eso es correcto y es lo que lo hace no autorreferencial, pero deja
una junta sin probar: **que el motor siga devolviendo esos `loc`**. Si mañana Pydantic cambiara la
forma del `loc`, o el catálogo moviera el `path` de una decisión, la tabla del front seguiría verde
sobre strings que ya no existen — y el estado de la tarjeta se decidiría con el criterio de huecos a
secas, en silencio.

Lo señaló la revisión adversarial cruzada, y tiene razón: un test integrado contra la respuesta real
de `/api/validate` es estrictamente más fuerte. Aquí se cierra esa junta y sólo esa; qué estado
produce cada caso lo sigue midiendo el front, que es quien lo calcula.

⚠️ **El cliente de UI se importa DENTRO de un helper, con `importorskip`.** `_ui_client` arrastra
starlette, y un import en el nivel de módulo revienta la **recolección** en los jobs mínimos del CI:
costó 10 de 16 jobs en rojo con todos los gates locales verdes.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

#: Config mínimo que construye y que las mutaciones de abajo modifican.
_BASE: dict[str, Any] = {
    "data": {
        "target": {"bad_rule": {"all_of": [{"col": "mora", "op": ">", "value": 90}]}},
        "partition": {"strategy": {"type": "random"}},
    }
}

#: 🔴 Los mismos casos de la tabla del front, con el `path` de su decisión. Lo que se comprueba aquí
#: es **la junta**: que algún `loc` real casa por prefijo con ese path. El estado resultante no se
#: mide aquí —lo calcula el front— y duplicarlo haría dos oráculos que se separan en silencio.
CASOS: tuple[tuple[str, str, dict[str, Any]], ...] = (
    (
        "una regla con las dos listas vacías",
        "data.target.bad_rule",
        {"all_of": [], "any_of": []},
    ),
    (
        "al azar con fracciones que no suman 1",
        "data.partition.strategy",
        {"type": "random", "dev_fraction": 0.9, "holdout_fraction": 0.9, "oot_fraction": 0.9},
    ),
    (
        "una partición temporal sin sus campos",
        "data.partition.strategy",
        {"type": "temporal"},
    ),
    (
        "una partición por cohortes sin sus campos",
        "data.partition.strategy",
        {"type": "cohort"},
    ),
    (
        "un tipo incorrecto en la raíz de la decisión",
        "data.target.bad_rule",
        "una cadena donde va un objeto",
    ),
)


def _validate(config: dict[str, Any]) -> dict[str, Any]:
    """Respuesta real de `POST /api/validate`, con el extra `[ui]` gateado aquí dentro."""
    pytest.importorskip("starlette")
    pytest.importorskip("fastapi")
    from _ui_client import ui_client

    respuesta = ui_client().post("/api/validate", json={"config": config})
    # Contrato «siempre 200» (D-ERR): un 500 aquí es el defecto que este repo ya pagó tres veces.
    assert respuesta.status_code == 200, respuesta.text
    return respuesta.json()  # type: ignore[no-any-return]


def _con(path: str, valor: Any) -> dict[str, Any]:
    config = json.loads(json.dumps(_BASE))
    nodo = config
    partes = path.split(".")
    for parte in partes[:-1]:
        nodo = nodo.setdefault(parte, {})
    nodo[partes[-1]] = valor
    return config


def _claves(payload: dict[str, Any]) -> list[str]:
    """Los `loc` tal como los normaliza `buildErrorLookup` en el front: unidos por puntos."""
    return [".".join(str(p) for p in error["loc"]) for error in payload.get("errors", ())]


@pytest.mark.parametrize(("nombre", "path", "valor"), CASOS)
def test_el_motor_devuelve_un_loc_que_casa_con_la_decision(
    nombre: str, path: str, valor: Any
) -> None:
    """Algún error real cae DENTRO de la decisión, casando por prefijo como hace el front."""
    payload = _validate(_con(path, valor))

    assert payload["valid"] is False, nombre
    casan = [c for c in _claves(payload) if c == path or c.startswith(f"{path}.")]
    assert casan, f"{nombre}: ningún `loc` de {_claves(payload)} cae dentro de {path}"


def test_ancla_un_config_bueno_no_produce_ningun_loc_en_las_decisiones() -> None:
    """🔴 Sin esto, un endpoint que devolviera errores siempre pasaría todos los casos de arriba."""
    payload = _validate(json.loads(json.dumps(_BASE)))

    for path in ("data.target.bad_rule", "data.partition.strategy"):
        casan = [c for c in _claves(payload) if c == path or c.startswith(f"{path}.")]
        assert not casan, f"el config base no debería tener errores en {path}: {casan}"


def test_el_loc_lleva_el_tag_del_discriminador_y_por_eso_no_sirve_para_enfocar() -> None:
    """⚠️ La trampa medida, escrita como aserción para que no se re-descubra.

    Pydantic **inserta** el tag de la unión discriminada en el `loc`, y ese segmento **no existe en
    el config**: `strategy.temporal.date_col` contra `strategy.date_col`. Sirve para casar por
    prefijo —que es para lo que se usa— y **nunca** para enfocar un campo.

    Si algún día dejara de insertarlo, este test se pone rojo y hay que revisar el comentario de
    `motivosDelRechazo`, no borrarlo: la afirmación habría dejado de ser cierta.
    """
    payload = _validate(_con("data.partition.strategy", {"type": "temporal"}))

    claves = _claves(payload)
    con_tag = [c for c in claves if c.startswith("data.partition.strategy.temporal.")]
    assert con_tag, f"se esperaba el tag `temporal` insertado en el loc; llegaron {claves}"
    # Y la prueba de que no es un path del config: la clave sin el tag es la que el control tiene.
    assert "data.partition.strategy.date_col" not in claves
