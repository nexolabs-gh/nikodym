"""`POST /api/validate` responde **siempre 200**, con `valid=false` — nunca un 500.

🔴 **Es la TERCERA vez que este repo paga el mismo defecto, y por eso el gate mide la CLASE.**

`ConfigError` no hereda de `ValueError`, así que Pydantic no lo envuelve y escapa entero del
`model_validate`. Eso se corrigió en su día atrapándolo en el endpoint... pero **doce clases
`*ConfigError` de dominio no heredaban de `ConfigError`**, sino sólo de la excepción raíz de su
módulo. El `except ConfigError` no las veía y el endpoint devolvía **500** sobre configs
perfectamente alcanzables desde el formulario —medido: `provisioning_cmf.portfolio_col = ""`,
`survival.input.duration_col = ""`—, que el front muestra como «Backend no disponible»: un mensaje
falso sobre un error del usuario que él mismo puede corregir.

Dos gates, y hacen falta los dos:

- El **nominal** vigila la jerarquía, que es donde está la causa. Alcance declarado: cubre las
  excepciones cuyo nombre termina en ``ConfigError``, que es el patrón del repo. Una excepción de
  validación con otro nombre se le escapa, y por eso no basta solo.
- El **funcional** vigila el contrato de verdad: se muta cada sección a un estado inválido
  **alcanzable desde el formulario** y se exige 200. Las mutaciones se escriben **a mano** aquí: si
  se derivaran del mismo sitio que producen el error, el gate mediría su propia consistencia.
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from typing import Any

import pytest

from nikodym.core.exceptions import ConfigError
from nikodym.ui.presets import get_preset


def _cliente():  # type: ignore[no-untyped-def]
    """Cliente de la UI, gateado por el extra `[ui]`.

    ⚠️ El import va DENTRO y con `importorskip`, que es el patrón del repo: `_ui_client` arrastra
    starlette, y un import incondicional en el módulo revienta la recolección entera en los jobs
    mínimos —medido: 10 de 16 jobs del CI en rojo con los gates locales verdes—.
    """
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx2")
    from _ui_client import ui_client

    return ui_client()


#: Mutaciones ALCANZABLES desde el formulario que dejan el config inválido, escritas a mano.
#: Cada una nombra la excepción de dominio que provoca, para que el mapa no se lea como una lista
#: de casos sueltos sino como la cobertura de las familias que escapaban.
_INVALIDOS: dict[str, tuple[str, Callable[[dict[str, Any]], None]]] = {
    "provisioning_cmf.portfolio_col vacío (CmfConfigError)": (
        "f3-provisiones-consumo",
        lambda c: c["provisioning_cmf"].__setitem__("portfolio_col", ""),
    ),
    "survival.input.duration_col vacío (SurvivalConfigError)": (
        "f4-ifrs9-retail",
        lambda c: c["survival"]["input"].__setitem__("duration_col", ""),
    ),
    "data.target.bad_rule sin predicados (ValidationError de Pydantic)": (
        "f1-estandar-consumo",
        lambda c: c["data"]["target"].__setitem__("bad_rule", {"all_of": [], "any_of": []}),
    ),
    "data.partition.strategy sin sus campos (ValidationError de Pydantic)": (
        "f1-estandar-consumo",
        lambda c: c["data"]["partition"].__setitem__("strategy", {"type": "temporal"}),
    ),
    "stability.temporal_column vacío (ConfigError, el que YA se atrapaba)": (
        "f1-estandar-consumo",
        lambda c: c["stability"].__setitem__("temporal_column", ""),
    ),
}


def test_toda_excepcion_de_config_de_dominio_hereda_del_error_de_config() -> None:
    """La causa: doce clases se llamaban «ConfigError» sin serlo para el `except` del endpoint.

    ⚠️ Alcance declarado, no supuesto: esto cubre el patrón **nominal** del repo (`*ConfigError`).
    Una excepción de validación con otro nombre no la ve, y por eso el gate funcional de abajo es
    el que mide el contrato. Decir que este barrido lo cubre todo sería sobrepromesa.
    """
    import importlib
    import inspect
    import pkgutil

    import nikodym

    escapan: list[str] = []
    vistas: list[str] = []
    for mod in pkgutil.walk_packages(nikodym.__path__, "nikodym."):
        try:
            modulo = importlib.import_module(mod.name)
        except Exception:  # pragma: no cover - un extra ausente no invalida el barrido
            continue
        for nombre, obj in vars(modulo).items():
            if not (inspect.isclass(obj) and issubclass(obj, Exception)):
                continue
            if not nombre.endswith("ConfigError"):
                continue
            vistas.append(nombre)
            if not issubclass(obj, ConfigError):
                escapan.append(f"{nombre} ({obj.__module__})")

    # Ancla anti-vacuo: un barrido que recorre cero clases daría verde sin medir nada, que es
    # exactamente cómo este repo ya se quemó una vez.
    assert len(set(vistas)) >= 12, sorted(set(vistas))
    assert escapan == [], (
        f"Estas excepciones se llaman «ConfigError» y no lo son para el `except` de "
        f"`/api/validate`, así que escapan y el endpoint devuelve 500: {sorted(escapan)}"
    )


@pytest.mark.parametrize("caso", sorted(_INVALIDOS))
def test_un_config_invalido_responde_200_y_no_500(caso: str) -> None:
    """El contrato de verdad: nunca un 500, siempre `valid=false` con su mensaje legible."""
    preset_id, mutar = _INVALIDOS[caso]
    config = copy.deepcopy(get_preset(preset_id)["config"])
    mutar(config)
    with _cliente() as cliente:
        respuesta = cliente.post("/api/validate", json={"config": config})
    assert respuesta.status_code == 200, (
        f"{caso}: HTTP {respuesta.status_code}. Un config que el usuario puede escribir desde el "
        "formulario tiene que volver como error suyo, no como caída del backend."
    )
    cuerpo = respuesta.json()
    assert cuerpo["valid"] is False, caso
    assert cuerpo["errors"], f"{caso}: `valid=false` sin un solo error que enseñar"
    for error in cuerpo["errors"]:
        assert error["msg"].strip(), caso


def test_el_control_positivo_sigue_siendo_valido() -> None:
    """Sin esto, los casos de arriba pasarían con un endpoint que dijera `valid=false` siempre."""
    with _cliente() as cliente:
        for preset_id in ("f1-estandar-consumo", "f3-provisiones-consumo", "f4-ifrs9-retail"):
            config = get_preset(preset_id)["config"]
            respuesta = cliente.post("/api/validate", json={"config": config})
            assert respuesta.status_code == 200, preset_id
            assert respuesta.json()["valid"] is True, preset_id
