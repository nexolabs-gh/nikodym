"""Tests de ``nikodym.check_pipeline`` y ``Study.check_pipeline`` (enmienda VALIDACION-PIPELINE).

Cubre las decisiones D-PIPE-2/D-PIPE-3/D-PIPE-6: el veredicto de ejecutabilidad sin ejecutar nada,
el primitivo *fail-loud* del núcleo frente al envoltorio que captura, la ausencia de rastro en el
``run_context`` y el export perezoso del paquete.

Los configs son los **presets reales de la UI**, no maquetas: el caso que motivó la enmienda es
exactamente el del usuario que enciende provisiones IFRS 9 y no la sección que produce su curva.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest
from pydantic import BaseModel, Field, ValidationError

import nikodym
from nikodym.api import check_pipeline
from nikodym.core.config import NikodymConfig
from nikodym.core.exceptions import ConfigError
from nikodym.core.study import Study
from nikodym.ui import presets


def _config(preset_id: str) -> dict[str, Any]:
    """Config crudo de un preset de la UI (copia: el llamador lo edita)."""
    return deepcopy(presets.get_preset(preset_id)["config"])


def _sin_survival() -> NikodymConfig:
    """Preset F4 con ``survival`` apagado: el config inejecutable que destapó la enmienda."""
    crudo = _config("f4-ifrs9-retail")
    crudo["survival"] = None
    return NikodymConfig.model_validate(crudo)


# --- El veredicto (D-PIPE-2) -------------------------------------------------------------------


def test_preset_ejecutable_publica_sus_pasos_en_orden() -> None:
    """Un preset de fábrica es ejecutable y anuncia el pipeline que correría."""
    check = check_pipeline(NikodymConfig.model_validate(_config("f4-ifrs9-retail")))

    assert check.executable is True
    assert check.steps == ("data", "survival", "provisioning_ifrs9", "report")
    assert check.message is None
    assert check.error_type is None


def test_config_vacio_es_ejecutable_con_pipeline_vacio() -> None:
    """Sin secciones activas no hay nada que correr, y eso no es un error del config."""
    check = check_pipeline(NikodymConfig.model_validate({}))

    assert check.executable is True
    assert check.steps == ()


def test_seccion_apagada_aguas_arriba_no_es_ejecutable_y_dice_por_que() -> None:
    """El caso del usuario: IFRS 9 encendido sin la sección que produce su term-structure.

    El mensaje se verifica por su CONTENIDO —el paso que falla y el artefacto que le falta—, no
    por igualdad exacta: es el diagnóstico del motor y debe poder mejorarse sin romper el test.
    """
    check = check_pipeline(_sin_survival())

    assert check.executable is False
    assert check.steps == ()
    assert check.error_type == "ConfigError"
    assert check.is_domain_error is True
    assert check.message is not None
    assert "provisioning_ifrs9" in check.message
    assert "survival" in check.message


# --- El primitivo del núcleo es fail-loud (D-PIPE-3) --------------------------------------------


def test_el_primitivo_relevanta_como_run() -> None:
    """``Study.check_pipeline`` re-levanta; capturar es trabajo del envoltorio de producto."""
    with pytest.raises(ConfigError, match="provisioning_ifrs9"):
        Study(_sin_survival()).check_pipeline()


def test_comprobar_no_deja_rastro_de_corrida() -> None:
    """Comprobar no es correr: ni ``run_id``, ni ``status``, ni ``finished_at``, ni ``error``.

    Es la diferencia con :meth:`Study.run`, que desde D-ERR-8/D-ERR-9 sí registra el intento
    fallido. Una comprobación que dejara rastro ensuciaría el audit-trail con cada tecleo del
    formulario, que la invoca con debounce.
    """
    study = Study(_sin_survival())

    with pytest.raises(ConfigError):
        study.check_pipeline()

    assert study.run_context.status == "created"
    assert study.run_context.run_id is None
    assert study.run_context.finished_at is None
    assert study.run_context.error is None


def test_el_primitivo_no_ejecuta_ningun_paso() -> None:
    """Un config ejecutable se comprueba sin producir artefactos ni resultados."""
    study = Study(NikodymConfig.model_validate(_config("f4-ifrs9-retail")))

    pasos = study.check_pipeline()

    assert pasos == ["data", "survival", "provisioning_ifrs9", "report"]
    assert list(study.artifacts.keys()) == []
    assert study.results == {}
    assert study.run_context.status == "created"


def test_steps_explicitos_tienen_prioridad_sobre_el_config() -> None:
    """El argumento ``steps`` manda sobre ``config.run.steps``, igual que en :meth:`run`."""
    study = Study(NikodymConfig.model_validate(_config("f4-ifrs9-retail")))

    assert study.check_pipeline(["data"]) == ["data"]


# --- Informar nunca tumba al llamante (D-PIPE-6) ------------------------------------------------


def test_una_excepcion_inesperada_se_declara_como_tal(monkeypatch: pytest.MonkeyPatch) -> None:
    """Lo que no es error de dominio se reporta con ``is_domain_error=False``, no se propaga.

    El formulario llama a esto en cada tecleo: una excepción que escape dejaría la validación en
    vivo caída, que es peor que cualquier fallo que quisiera reportar.
    """

    def _explota(self: Study, steps: list[str] | None = None) -> list[str]:
        raise RuntimeError("un from_config de dominio que levanta algo ajeno al motor")

    monkeypatch.setattr(Study, "check_pipeline", _explota)

    check = check_pipeline(NikodymConfig.model_validate({}))

    assert check.executable is False
    assert check.error_type == "RuntimeError"
    assert check.is_domain_error is False
    assert check.message is not None


def test_el_mensaje_conserva_el_codigo_de_marca(monkeypatch: pytest.MonkeyPatch) -> None:
    """Superficie de CÓDIGO: el mensaje va ÍNTEGRO; sanearlo es del copy público (D-ERR-4).

    Verifica que ``check_pipeline`` **no** aplica ``strip_declared_codes``: aquí el código de la
    marca es el dato, igual que en ``RunError.message``. El endpoint de la UI sí lo sanea, y ese
    corte se prueba por separado en ``test_ui_routes.py``.
    """
    codigo = "DATO-INSTITUCIONAL-IFRS-7: declare la unidad temporal de la curva."

    def _con_marca(self: Study, steps: list[str] | None = None) -> list[str]:
        raise ConfigError(codigo)

    monkeypatch.setattr(Study, "check_pipeline", _con_marca)

    check = check_pipeline(NikodymConfig.model_validate({}))

    assert check.message == codigo


# --- El ValidationError de coacción es el diagnóstico más accionable, no ruido ------------------


def test_un_valor_fuera_de_rango_en_un_subconfig_se_reporta_como_accionable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Un ``ValidationError`` de coacción cuenta como error de dominio y se publica.

    Las secciones de dominio son ``Any`` en el schema raíz, así que una restricción violada dentro
    de una de ellas no la caza ``NikodymConfig.model_validate``: la caza la coacción que hace la
    resolución. Tratarlo como «excepción inesperada» habría ocultado el diagnóstico justo en el
    caso más común de todos.

    El ``ValidationError`` se inyecta en vez de construirse desde un preset a propósito: si la
    coacción ocurre en la raíz o en la resolución **depende de qué dominios haya importado el
    proceso**, así que un test que lo montara desde un config real pasaría o fallaría según el
    orden de la suite. Ese comportamiento inestable está reportado aparte; fijarlo aquí sería
    congelarlo como si fuera el contrato.
    """

    class _SubConfig(BaseModel):
        min_bin_size: float = Field(ge=0)

    try:
        _SubConfig(min_bin_size=-1.0)
    except ValidationError as real:
        capturado = real

    def _coacciona_mal(self: Study, steps: list[str] | None = None) -> list[str]:
        raise capturado

    monkeypatch.setattr(Study, "check_pipeline", _coacciona_mal)

    check = check_pipeline(NikodymConfig.model_validate({}))

    assert check.executable is False
    assert check.is_domain_error is True, "es accionable por quien configura, no detalle interno"
    assert check.message is not None
    assert "min_bin_size" in check.message
    assert "errors.pydantic.dev" not in check.message, "una URL de Pydantic no es copy público"
    assert "input_value" not in check.message, "el volcado técnico de Pydantic tampoco"
    assert "\n" not in check.message, "el aviso es una línea, no un muro multilínea"


def test_muchos_errores_se_acotan_diciendo_cuantos_faltan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El aviso no vuelca decenas de errores, y **dice** cuántos omitió (nunca trunca callado)."""

    class _Ancho(BaseModel):
        a: int
        b: int
        c: int
        d: int
        e: int
        f: int
        g: int

    try:
        _Ancho.model_validate({})
    except ValidationError as real:
        capturado = real

    def _coacciona_mal(self: Study, steps: list[str] | None = None) -> list[str]:
        raise capturado

    monkeypatch.setattr(Study, "check_pipeline", _coacciona_mal)

    mensaje = check_pipeline(NikodymConfig.model_validate({})).message

    assert mensaje is not None
    assert "y 2 problema(s) más" in mensaje


# --- Export perezoso del paquete ----------------------------------------------------------------


def test_check_pipeline_es_superficie_publica_del_paquete() -> None:
    """``nikodym.check_pipeline`` existe y es el mismo objeto que ``nikodym.api.check_pipeline``."""
    assert nikodym.check_pipeline is check_pipeline
    assert "check_pipeline" in dir(nikodym)
    assert "PipelineCheck" in dir(nikodym)


# --- Comprobar no puede sembrar el proceso ------------------------------------------------------


def test_comprobar_no_siembra_los_rng_del_proceso(monkeypatch: pytest.MonkeyPatch) -> None:
    """El formulario llama aquí en CADA tecleo: sembrar sería un efecto de proceso, no del objeto.

    `SeedManager.apply_global` resetea el `random` global y fija el hint `PYTHONHASHSEED` que
    heredan los subprocesos (joblib/loky, GBDT). Lo fija **sólo la primera vez**, así que con la
    comprobación sembrando, ese hint quedaba anclado a la semilla del config que se estaba
    editando y no a la de la corrida que se ejecuta después — el no-determinismo silencioso que
    SDD-01 §9 existe para evitar.
    """
    import os
    import random

    monkeypatch.delenv("PYTHONHASHSEED", raising=False)
    random.seed(123)
    esperado = [random.random() for _ in range(2)]

    random.seed(123)
    primero = random.random()
    check_pipeline(NikodymConfig.model_validate({"repro": {"seed": 999}}))
    segundo = random.random()

    assert [primero, segundo] == esperado, "la comprobación pisó el stream global de random"
    assert os.environ.get("PYTHONHASHSEED") is None, "la comprobación fijó el hint de la corrida"


def test_la_corrida_si_siembra(monkeypatch: pytest.MonkeyPatch) -> None:
    """El sentido contrario, para que el arreglo no se pase de frenada: correr SÍ siembra."""
    import os

    monkeypatch.delenv("PYTHONHASHSEED", raising=False)
    with pytest.warns(UserWarning, match="PYTHONHASHSEED"):
        Study(NikodymConfig.model_validate({"repro": {"seed": 7}}))

    assert os.environ.get("PYTHONHASHSEED") is not None
