"""El contexto cerrado con que una opción exige que otra sección esté activa (D-ABA-8).

Media docena de opciones del abanico metodológico no exigen una columna ni un valor, sino **que
otra sección corra**: elegir que la curva de PD venga de `survival` obliga a que `survival` esté
activa. ``requisitos_incumplidos`` recibe columnas y no puede expresarlo, y ampliarle la firma para
darle el config raíz es justo lo que D-INV-1 rechazó —acoplaría cada dominio a todos los demás—.

Lo que se prueba aquí, en este orden:

1. **El contexto no filtra el config.** Es la garantía estructural del diseño: un DTO de un solo
   campo hace que un dominio **no pueda** leer algo ajeno aunque quiera. Si alguien le añade el
   config raíz por descuido, este archivo se pone rojo.
2. **El criterio de «activo» es el del motor**, contrastado contra el pipeline que ``Study``
   resuelve de verdad. Un criterio *parecido* al del motor sería peor que ninguno: avisaría de que
   una sección está apagada cuando el motor sí la va a correr.
3. **El protocolo es genérico**, como los otros tres hermanos: cualquier ``BaseModel`` que declare
   el método participa, sin heredar del núcleo.
4. **Añade y no quita** (control negativo ejecutado): un modelo sin el método se comporta
   exactamente igual que antes, y el aviso llega como ``unmet_requirement`` —avisa, no revienta—.
"""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING, Any

import pytest
from pydantic import BaseModel

from nikodym.core.config.schema import NikodymConfig
from nikodym.core.dataset_check import (
    METODO_REQUISITOS_CONTEXTO,
    ContextoConfig,
    Requisito,
    _requisitos,
    _secciones_activas,
    check_dataset,
)
from nikodym.core.study import Study
from nikodym.ui import presets

if TYPE_CHECKING:
    from collections.abc import Iterator

_COLUMNAS: tuple[str, ...] = ("cliente", "fecha", "monto", "mora")

_PRESETS: tuple[str, ...] = (
    presets.STANDARD_PRESET_ID,
    presets.PROVISIONES_PRESET_ID,
    presets.F4_IFRS9_PRESET_ID,
)


def _config_de(preset_id: str) -> NikodymConfig:
    return NikodymConfig.model_validate(presets.get_preset(preset_id)["config"])


# --------------------------------------------------------------------------------------------
# 1. El contexto es cerrado: su tamaño ES la garantía
# --------------------------------------------------------------------------------------------


def test_el_contexto_expone_exactamente_los_campos_declarados() -> None:
    """Añadir el config raíz «para que el dominio pueda mirar una cosita más» ⇒ rojo.

    D-INV-1 rechazó darle el config raíz a cada sección porque las acopla a todas las demás.
    D-ABA-8 amplía el contexto mínimo **sin** abrir esa puerta, y lo único que sostiene la
    diferencia es que el DTO no tenga más campos que los declarados: un dominio no puede leer lo
    que no está aquí. Este gate es la parte del diseño que se puede perder en silencio.
    """
    campos = {campo.name for campo in dataclasses.fields(ContextoConfig)}
    assert campos == {"secciones_activas"}, (
        f"ContextoConfig expone {sorted(campos)}. Un campo nuevo amplía lo que CADA sección puede "
        "saber del resto del config: se decide en el SDD (D-ABA-8), no al programar."
    )


def test_el_contexto_es_inmutable() -> None:
    """Una sección no puede reescribir el contexto que recibe, ni para la siguiente."""
    contexto = ContextoConfig(secciones_activas=frozenset({"data"}))
    with pytest.raises(dataclasses.FrozenInstanceError):
        contexto.secciones_activas = frozenset()  # type: ignore[misc]


def test_ningun_campo_del_contexto_transporta_el_config() -> None:
    """Control del anterior por TIPO y no por nombre: `secciones: NikodymConfig` también es fuga."""
    for campo in dataclasses.fields(ContextoConfig):
        assert campo.type is not NikodymConfig, f"{campo.name} transporta el config raíz entero"
        assert "NikodymConfig" not in str(campo.type), (
            f"{campo.name} anota {campo.type}: el contexto no puede llevar el config raíz"
        )


# --------------------------------------------------------------------------------------------
# 2. «Activo» significa lo mismo que para el motor
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize("preset_id", _PRESETS)
def test_las_secciones_activas_son_las_que_el_motor_va_a_correr(preset_id: str) -> None:
    """Oráculo independiente: el pipeline que ``Study`` resuelve, no otra lectura del config.

    Si este gate derivara su esperado del mismo criterio que comprueba, sólo mediría que la función
    es determinista — el defecto que la sesión del 2026-08-02 encontró en un gate de paridad.
    """
    config = _config_de(preset_id)
    del_motor = frozenset(Study(config, apply_global_seed=False).check_pipeline())

    assert del_motor, "el preset debe resolver algún paso, o el gate no compara nada"
    assert _secciones_activas(config) == del_motor


def test_una_seccion_apagada_no_esta_activa() -> None:
    """Control negativo del anterior: sin esto, «devuelve todo siempre» pasaría igual."""
    config = _config_de(presets.STANDARD_PRESET_ID)
    assert "stability" in _secciones_activas(config)

    sin_stability = config.model_copy(update={"stability": None})
    assert "stability" not in _secciones_activas(sin_stability)


def test_declarar_run_steps_acota_las_secciones_activas() -> None:
    """«Activo» es *estar en la lista efectiva*, no *tener sección no nula* (D-FX-1).

    Con ``run.steps`` declarado, una sección que existe en el config **no se ejecuta**, y decirle a
    una opción del abanico que su dependencia está viva sería falso.
    """
    crudo = presets.get_preset(presets.STANDARD_PRESET_ID)["config"]
    acotado = NikodymConfig.model_validate({**crudo, "run": {"steps": ["data", "binning"]}})

    assert acotado.stability is not None, "la sección sigue existiendo: es lo que hace útil el caso"
    assert _secciones_activas(acotado) == frozenset({"data", "binning"})


# --------------------------------------------------------------------------------------------
# 3. El protocolo es genérico, y llega hasta el veredicto
# --------------------------------------------------------------------------------------------


class _SeccionConContexto(BaseModel):
    """Modelo ad-hoc que declara el protocolo sin heredar nada del núcleo."""

    metodo: str = "consume_pit"

    def requisitos_incumplidos_por_contexto(
        self, contexto: ContextoConfig
    ) -> tuple[Requisito, ...]:
        if "forward" in contexto.secciones_activas:
            return ()
        return (
            Requisito(
                path="metodo",
                declared=self.metodo,
                message="Elegiste una curva que produce otra sección, y esa sección está apagada.",
            ),
        )


class _SeccionSinProtocolo(BaseModel):
    metodo: str = "consume_pit"


def _rutas(modelo: BaseModel, contexto: ContextoConfig | None) -> list[str]:
    emitidos: Iterator[tuple[str, Requisito]] = _requisitos(
        modelo, frozenset(_COLUMNAS), prefijo="seccion.", contexto=contexto
    )
    return [ruta for ruta, _ in emitidos]


def test_el_mecanismo_es_generico_y_no_un_caso_especial_de_una_seccion() -> None:
    """Cualquier ``BaseModel`` que declare el método participa: es duck-typing, no herencia."""
    apagada = ContextoConfig(secciones_activas=frozenset({"data", "survival"}))
    assert _rutas(_SeccionConContexto(), apagada) == ["seccion.metodo"]


def test_con_la_seccion_encendida_el_mismo_modelo_no_avisa() -> None:
    """Ancla del anterior: sin esto, «avisa siempre» pasaría igual, que es medir nada."""
    encendida = ContextoConfig(secciones_activas=frozenset({"data", "forward"}))
    assert _rutas(_SeccionConContexto(), encendida) == []


def test_un_modelo_sin_el_metodo_se_comporta_igual_que_antes() -> None:
    """El protocolo AÑADE: quien no lo declara no cambia una línea de su comportamiento."""
    apagada = ContextoConfig(secciones_activas=frozenset({"data"}))
    assert _rutas(_SeccionSinProtocolo(), apagada) == []


def test_sin_contexto_no_se_pregunta() -> None:
    """El ``None`` del parámetro es «este llamador no lo computó», y no debe reventar."""
    assert _rutas(_SeccionConContexto(), None) == []


def test_el_aviso_llega_por_check_dataset_con_su_ruta_absoluta(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Integración: el dominio declara relativo (D-INV-5) y el recorrido antepone el prefijo.

    Se inyecta el método sobre una config REAL en vez de fabricar un `NikodymConfig` de mentira:
    lo que hay que probar es que el recorrido de :func:`check_dataset` lo alcanza donde las
    secciones viven de verdad, anidamiento incluido.
    """
    from nikodym.stability.config import StabilityConfig

    def _exige_forward(self: StabilityConfig, contexto: ContextoConfig) -> tuple[Requisito, ...]:
        del self
        if "forward" in contexto.secciones_activas:
            return ()
        return (Requisito(path="temporal_axis", declared="pit", message="Falta la sección."),)

    monkeypatch.setattr(StabilityConfig, METODO_REQUISITOS_CONTEXTO, _exige_forward, raising=False)

    config = _config_de(presets.STANDARD_PRESET_ID)
    assert "forward" not in _secciones_activas(config), "el preset no activa forward: es el caso"

    veredicto = check_dataset(config, _COLUMNAS)
    delatores = [m for m in veredicto.mismatches if m.message == "Falta la sección."]

    assert [m.path for m in delatores] == ["stability.temporal_axis"]
    assert delatores[0].kind == "unmet_requirement", "avisa como los demás; el front no bifurca"
    assert delatores[0].declared == "pit"


def test_el_requisito_de_contexto_avisa_y_no_revienta(monkeypatch: pytest.MonkeyPatch) -> None:
    """D-PRE-5 y D-INV-3 intactos: un contexto incumplido es un aviso, nunca una excepción."""
    from nikodym.stability.config import StabilityConfig

    def _siempre(self: StabilityConfig, contexto: ContextoConfig) -> tuple[Requisito, ...]:
        del self, contexto
        return (Requisito(path="temporal_axis", declared="x", message="Aviso, no error."),)

    monkeypatch.setattr(StabilityConfig, METODO_REQUISITOS_CONTEXTO, _siempre, raising=False)

    veredicto = check_dataset(_config_de(presets.STANDARD_PRESET_ID), _COLUMNAS)

    assert any(m.message == "Aviso, no error." for m in veredicto.mismatches)


def test_sin_el_protocolo_el_veredicto_de_los_presets_no_se_mueve() -> None:
    """Control negativo de la integración entera: hoy nadie declara el método, y nada cambió.

    Es el ancla que separa «el mecanismo está conectado» de «el mecanismo cambió algo sin que
    nadie lo pidiera». Cuando una sección real lo declare, este test seguirá midiendo lo mismo
    para las que no.
    """
    for preset_id in _PRESETS:
        config = _config_de(preset_id)
        assert not any(
            callable(getattr(getattr(config, seccion, None), METODO_REQUISITOS_CONTEXTO, None))
            for seccion in type(config).model_fields
        ), f"{preset_id}: alguna sección ya declara el método; actualiza este control"


def test_el_barrido_no_es_vacuo() -> None:
    """Un gate que recorre cero da verde y no prueba nada: pasó ya dos veces en este repo."""
    config = _config_de(presets.STANDARD_PRESET_ID)
    activas = _secciones_activas(config)

    assert len(activas) >= 5, f"sólo {len(activas)} secciones activas en F1: {sorted(activas)}"
    for ancla in ("data", "binning", "stability"):
        assert ancla in activas, f"«{ancla}» debería estar activa en el preset F1"


def _tipos_de_campo() -> dict[str, Any]:
    return {campo.name: campo.type for campo in dataclasses.fields(ContextoConfig)}


def test_las_secciones_activas_viajan_como_conjunto_inmutable() -> None:
    """Una sección no puede mutar el contexto que recibirá la siguiente."""
    assert "frozenset" in str(_tipos_de_campo()["secciones_activas"])
