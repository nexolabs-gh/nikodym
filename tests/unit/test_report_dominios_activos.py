"""Matriz §3.1 de la enmienda DEFAULTS-EFECTIVOS-UI: dominio apagado, política y CT-1 (D-FX-1…4).

El defecto que cierra este gate: ``ReportStep`` declaraba como prerequisito DURO la card de un
dominio que **nadie iba a correr**, así que ``check_pipeline`` rechazaba el config entero con un
``ConfigError`` del DAG —«active 'eda' antes de 'report'»— antes de que ``missing_policy`` pudiera
tomar la decisión que existe para tomar. El usuario recibía el error equivocado, en el sitio
equivocado, y sin la salida que el config ya declaraba.

Cada fila se comprueba **dos veces**: con la sección ``report`` tipada y con la misma sección como
``dict`` opaco (el estado por defecto de un config que viene de YAML sin la capa importada), porque
esa dualidad es la clase de defecto que ya se pagó tres releases seguidos
(``test_seccion_opaca_invariante.py``).

Y con **dos dominios**: ``eda`` —el caso que destapó el defecto— y ``stability``, que no tiene nada
de especial. Si el filtro estuviera escrito para ``eda``, la segunda mitad de cada test se pondría
roja: es el control que impide el parche por dominio que la enmienda prohíbe (§4, alternativa 2).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

from nikodym.core.config import NikodymConfig
from nikodym.core.exceptions import ArtifactNotFoundError, ConfigError
from nikodym.core.study import Study
from nikodym.eda.config import EdaConfig
from nikodym.eda.step import EdaStep
from nikodym.report.builder import OPTIONAL_REPORT_INPUTS
from nikodym.report.config import ReportConfig, SectionPolicyConfig
from nikodym.report.exceptions import ReportInputError
from nikodym.report.step import REPORT_REQUIRED_CARDS, ReportStep
from nikodym.stability.config import StabilityConfig
from nikodym.stability.step import StabilityStep

#: Los dos dominios de la matriz. `eda` es el caso vivo; `stability` es el control anti-parche.
DOMINIOS = ("eda", "stability")
#: Config de la sección de cada dominio, para poder activarlo en `steps=`.
_CONFIG_POR_DOMINIO: dict[str, Any] = {"eda": EdaConfig, "stability": StabilityConfig}
#: Step real de cada dominio, cuyo `execute` se sustituye para no arrastrar el pipeline entero.
_STEP_POR_DOMINIO: dict[str, Any] = {"eda": EdaStep, "stability": StabilityStep}
#: Lo que ese step declara `requires`; se pre-siembra para que el DAG sea válido sin correr `data`.
_UPSTREAM_POR_DOMINIO: dict[str, tuple[tuple[str, str], ...]] = {
    "eda": EdaStep.requires,
    "stability": StabilityStep.requires,
}
_CARD_POR_DOMINIO: dict[str, str] = dict(REPORT_REQUIRED_CARDS)


def _card(domain: str) -> dict[str, Any]:
    """Card sintética mínima con la forma que el builder sabe leer."""
    return {"summary": f"{domain}-card", "metric_sections": {domain: {"ok": 1}}}


def _config(
    *,
    tmp_path: Path,
    politica: str,
    apagado: str,
    opaco: bool,
    activar: tuple[str, ...] = (),
) -> NikodymConfig:
    """``NikodymConfig`` con ``report`` (tipado u opaco) y las secciones que se quieran activas."""
    report = ReportConfig(
        output_dir=str(tmp_path),
        sections=SectionPolicyConfig(missing_policy=politica, max_table_rows=10),
    )
    assert apagado in set(report.sections.required_sections), (
        "la fila de la matriz exige que el dominio SÍ esté en required_sections"
    )
    secciones: dict[str, Any] = {
        # Una sección opaca es un `dict` sin coaccionar: es el estado por defecto de un config
        # cargado de YAML, no un caso raro (D-HASH/`test_seccion_opaca_invariante.py`).
        "report": report.model_dump(mode="json", by_alias=True) if opaco else report
    }
    for nombre in activar:
        secciones[nombre] = _CONFIG_POR_DOMINIO[nombre]()
    return NikodymConfig(**secciones)


def _sembrar_cards(study: Study, *, salvo: str) -> None:
    """Publica las ocho cards canónicas menos la del dominio apagado."""
    for domain, key in REPORT_REQUIRED_CARDS:
        if domain != salvo:
            study.artifacts.set(domain, key, _card(domain))
    study.artifacts.set("model", "coefficients", pd.DataFrame({"variable": ["a"], "coef": [0.5]}))


# ---------------------------------------------------------------------------------------------
# Filas 1-3: dominio REQUERIDO pero APAGADO → el preflight es ejecutable y decide `missing_policy`
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("apagado", DOMINIOS)
@pytest.mark.parametrize("opaco", [False, True], ids=["tipado", "opaco"])
def test_dominio_apagado_deja_el_preflight_ejecutable(
    apagado: str,
    opaco: bool,
    tmp_path: Path,
) -> None:
    """Ninguna de las tres políticas reintroduce el ``ConfigError`` prematuro del DAG.

    Antes de D-FX-3 este ``check_pipeline`` levantaba «El paso 'report' necesita 'eda_card'…»: el
    motor rechazaba un config que él mismo sabía terminar.
    """
    for politica in ("error", "warn", "skip"):
        study = Study(
            _config(tmp_path=tmp_path, politica=politica, apagado=apagado, opaco=opaco),
            apply_global_seed=False,
        )
        assert study.check_pipeline() == ["report"]


@pytest.mark.parametrize("apagado", DOMINIOS)
@pytest.mark.parametrize("opaco", [False, True], ids=["tipado", "opaco"])
def test_politica_error_falla_en_report_no_en_el_dag(
    apagado: str,
    opaco: bool,
    tmp_path: Path,
) -> None:
    """``error`` detiene la corrida **dentro** de ``report``, con el mensaje del informe."""
    study = Study(
        _config(tmp_path=tmp_path, politica="error", apagado=apagado, opaco=opaco),
        apply_global_seed=False,
    )
    _sembrar_cards(study, salvo=apagado)

    with pytest.raises(ReportInputError, match=f"dominio='{apagado}'"):
        study.run()

    assert study.run_context.status == "failed"
    assert study.run_context.error is not None
    # El paso en curso se nombra: el fallo es del informe, no de la resolución del pipeline.
    assert study.run_context.error.step == "report"
    assert study.run_context.error.type == "ReportInputError"


@pytest.mark.parametrize("apagado", DOMINIOS)
@pytest.mark.parametrize("opaco", [False, True], ids=["tipado", "opaco"])
def test_politica_warn_termina_y_publica_la_ausencia(
    apagado: str,
    opaco: bool,
    tmp_path: Path,
) -> None:
    """``warn`` llega a ``done`` y deja la sección publicada **sin números**."""
    study = Study(
        _config(tmp_path=tmp_path, politica="warn", apagado=apagado, opaco=opaco),
        apply_global_seed=False,
    )
    _sembrar_cards(study, salvo=apagado)
    study.run()

    assert study.run_context.status == "done"
    bundle = study.artifacts.get("report", "input_bundle")
    assert apagado in bundle.missing_sections
    ausentes = [s for s in bundle.sections if s.status == "missing"]
    assert any(apagado in s.id for s in ausentes), (
        f"con warn la sección ausente se publica; secciones: {[s.id for s in bundle.sections]}"
    )


@pytest.mark.parametrize("apagado", DOMINIOS)
@pytest.mark.parametrize("opaco", [False, True], ids=["tipado", "opaco"])
def test_politica_skip_omite_pero_conserva_la_limitacion(
    apagado: str,
    opaco: bool,
    tmp_path: Path,
) -> None:
    """``skip`` omite la sección y **conserva** la limitación: no se muta ``required_sections``.

    Es la razón por la que el filtro vive en ``requires`` y no en el config: el builder necesita la
    lista original para saber qué falta.
    """
    study = Study(
        _config(tmp_path=tmp_path, politica="skip", apagado=apagado, opaco=opaco),
        apply_global_seed=False,
    )
    _sembrar_cards(study, salvo=apagado)
    study.run()

    assert study.run_context.status == "done"
    bundle = study.artifacts.get("report", "input_bundle")
    # La limitación se conserva…
    assert apagado in bundle.missing_sections
    # …y la sección NO se publica.
    assert not any(s.status == "missing" and apagado in s.id for s in bundle.sections)
    # `required_sections` sigue intacto en el config resuelto.
    assert apagado in set(study.config.report.sections.required_sections)


# ---------------------------------------------------------------------------------------------
# Filas 4-5: dominio ACTIVO. La política NO puede tapar un productor roto (CT-1 sigue vivo).
# ---------------------------------------------------------------------------------------------


def _activar_dominio(
    monkeypatch: pytest.MonkeyPatch,
    study: Study,
    dominio: str,
    *,
    publica_card: bool,
) -> None:
    """Deja ``dominio`` corriendo de verdad, con o sin publicar su card, sin arrastrar el pipeline.

    Se sustituye el ``execute`` del step REAL (no se inventa un step ni se toca el ``REGISTRY``):
    así el resolver, ``provides`` y la validación CT-1 son exactamente los de producción.
    """
    for clave in _UPSTREAM_POR_DOMINIO[dominio]:
        study.artifacts.set(clave[0], clave[1], object())
    card_key = _CARD_POR_DOMINIO[dominio]

    def _execute(self: Any, study_: Study, rng: Any) -> None:
        del rng
        if publica_card:
            study_.artifacts.set(dominio, card_key, _card(dominio))

    monkeypatch.setattr(_STEP_POR_DOMINIO[dominio], "execute", _execute)


@pytest.mark.parametrize("dominio", DOMINIOS)
@pytest.mark.parametrize("opaco", [False, True], ids=["tipado", "opaco"])
def test_dominio_activo_con_card_termina_done(
    dominio: str,
    opaco: bool,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fila 4: requerido + activo + card presente ⇒ ``done`` con **cualquier** política."""
    for politica in ("error", "warn", "skip"):
        study = Study(
            _config(
                tmp_path=tmp_path,
                politica=politica,
                apagado=dominio,
                opaco=opaco,
                activar=(dominio,),
            ),
            apply_global_seed=False,
        )
        _sembrar_cards(study, salvo=dominio)
        _activar_dominio(monkeypatch, study, dominio, publica_card=True)

        assert study.check_pipeline() == [dominio, "report"]
        study.run()
        assert study.run_context.status == "done"
        bundle = study.artifacts.get("report", "input_bundle")
        assert bundle.missing_sections == ()


@pytest.mark.parametrize("dominio", DOMINIOS)
@pytest.mark.parametrize("politica", ["error", "warn", "skip"])
@pytest.mark.parametrize("opaco", [False, True], ids=["tipado", "opaco"])
def test_productor_activo_que_incumple_ct1_falla_antes_del_builder(
    dominio: str,
    politica: str,
    opaco: bool,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fila 5: ``missing_policy`` **no** es permiso para ocultar un productor roto.

    Un paso activo que declaró la card en ``provides`` y no la publicó sigue incumpliendo CT-1:
    ``ArtifactNotFoundError`` antes de entrar al builder, para las tres políticas. Sin este control
    la doble intersección degradaría a «quitar todas las cards de ``requires``» (§4, alternativa 4).
    """
    study = Study(
        _config(
            tmp_path=tmp_path,
            politica=politica,
            apagado=dominio,
            opaco=opaco,
            activar=(dominio,),
        ),
        apply_global_seed=False,
    )
    _sembrar_cards(study, salvo=dominio)
    _activar_dominio(monkeypatch, study, dominio, publica_card=False)

    # El pipeline es ejecutable: el productor SÍ declara la card en `provides`.
    assert study.check_pipeline() == [dominio, "report"]
    with pytest.raises(ArtifactNotFoundError, match=f"'{dominio}'"):
        study.run()
    assert study.run_context.error is not None
    assert study.run_context.error.step == "report"


# ---------------------------------------------------------------------------------------------
# Fila 6: dominio NI requerido NI activo ⇒ ni figura como faltante
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("fuera", DOMINIOS)
@pytest.mark.parametrize("opaco", [False, True], ids=["tipado", "opaco"])
def test_dominio_ni_requerido_ni_activo_no_figura_como_faltante(
    fuera: str,
    opaco: bool,
    tmp_path: Path,
) -> None:
    """Fila 6: quitarlo de ``required_sections`` lo saca también de las limitaciones."""
    requeridas = tuple(d for d, _ in REPORT_REQUIRED_CARDS if d != fuera)
    report = ReportConfig(
        output_dir=str(tmp_path),
        sections=SectionPolicyConfig(required_sections=requeridas, max_table_rows=10),
    )
    seccion = report.model_dump(mode="json", by_alias=True) if opaco else report
    study = Study(NikodymConfig(report=seccion), apply_global_seed=False)
    _sembrar_cards(study, salvo=fuera)

    assert study.check_pipeline() == ["report"]
    study.run()
    assert study.run_context.status == "done"
    assert study.artifacts.get("report", "input_bundle").missing_sections == ()


# ---------------------------------------------------------------------------------------------
# El contrato del step: doble intersección, firma histórica y consumos opcionales
# ---------------------------------------------------------------------------------------------


def test_requires_es_la_doble_interseccion() -> None:
    """``requires`` = ``REPORT_REQUIRED_CARDS`` ∩ ``required_sections`` ∩ ``active_domains``."""
    cfg = ReportConfig()
    # Sin contexto: firma histórica intacta (uso standalone).
    assert ReportStep.from_config(cfg).requires == REPORT_REQUIRED_CARDS

    # Con contexto: sólo las cards de dominios que corren.
    paso = ReportStep.from_config_with_context(
        cfg, active_domains=frozenset({"model", "performance", "report"})
    )
    assert paso.requires == (("model", "model_card"), ("performance", "card"))

    # La primera intersección sigue viva: un dominio activo que el informe NO exige no entra.
    sin_modelo = ReportConfig(
        sections=SectionPolicyConfig(required_sections=("performance",)),
    )
    paso = ReportStep.from_config_with_context(
        sin_modelo, active_domains=frozenset({"model", "performance", "report"})
    )
    assert paso.requires == (("performance", "card"),)

    # Y el contexto vacío no es «no se sabe»: es «no corre nadie».
    assert ReportStep.from_config_with_context(cfg, active_domains=frozenset()).requires == ()


def test_las_cards_adoptables_son_consumos_opcionales() -> None:
    """D-FX-3: lo que el builder adopta si existe se declara en ``optional_requires``.

    Sin esto, filtrar ``requires`` convertía en **inerte** —con su aviso— una card que el informe sí
    lee, en cuanto se inyectara por ``nikodym.run(..., artifacts=...)``.
    """
    paso = ReportStep.from_config_with_context(ReportConfig(), active_domains=frozenset({"report"}))
    assert paso.requires == ()
    assert paso.optional_requires == OPTIONAL_REPORT_INPUTS
    # Las ocho canónicas están dentro aunque hayan salido de `requires`…
    assert set(REPORT_REQUIRED_CARDS) <= set(paso.optional_requires)
    # …y también las que nunca fueron obligatorias.
    for clave in (("data", "data_card"), ("validation", "card"), ("validation", "result")):
        assert clave in paso.optional_requires
    # `optional_requires` NO es un prerequisito: no participa en la validación del DAG.
    assert set(paso.optional_requires) & set(paso.requires) == set()


def test_run_step_conserva_la_comprobacion_ct1(tmp_path: Path) -> None:
    """``run_step`` resuelve SIN contexto: un paso suelto sigue exigiendo sus artefactos.

    ``['report']`` no es «el pipeline de esta invocación» sino un atajo sobre un store ya poblado;
    tratarlo como contexto dejaría la comprobación CT-1 de este método vacía.
    """
    study = Study(
        NikodymConfig(report=ReportConfig(output_dir=str(tmp_path))),
        apply_global_seed=False,
    )
    _sembrar_cards(study, salvo="stability")

    with pytest.raises(ArtifactNotFoundError, match=r"\('stability', 'card'\)"):
        study.run_step("report")


def test_el_resolver_no_conoce_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D-FX-2: el hook es genérico. Un componente cualquiera que lo exponga recibe el contexto.

    El control que impide el parche prohibido (§4, alternativa 2): si el núcleo tuviera un
    ``if name == 'report'``, este componente ajeno a ``report`` no vería nada.
    """
    visto: dict[str, Any] = {}

    class _Falso:
        name = "eda"
        requires: tuple[tuple[str, str], ...] = ()
        provides: tuple[tuple[str, str], ...] = (("eda", "eda_card"),)

        @classmethod
        def from_config(cls, cfg: Any) -> _Falso:  # pragma: no cover - no debe usarse
            raise AssertionError("con contexto disponible debe preferirse la fábrica contextual")

        @classmethod
        def from_config_with_context(cls, cfg: Any, *, active_domains: frozenset[str]) -> _Falso:
            visto["active_domains"] = active_domains
            return cls()

        def execute(self, study: Study, rng: np.random.Generator) -> None:  # pragma: no cover
            del study, rng

    from nikodym.core import registry as registry_module

    study = Study(
        NikodymConfig(eda=EdaConfig(), report=ReportConfig(output_dir=str(tmp_path))),
        apply_global_seed=False,
    )
    original = registry_module.REGISTRY.resolve

    def _resolve(domain: str, name: str) -> type:
        return _Falso if domain == "eda" else original(domain, name)

    monkeypatch.setattr(registry_module.REGISTRY, "resolve", _resolve)
    study.check_pipeline(["eda", "report"])

    assert visto["active_domains"] == frozenset({"eda", "report"})


def test_un_hook_con_firma_incompatible_habla_en_español(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Un dominio que declare mal el hook no puede filtrar un ``TypeError`` en inglés al formulario.

    El mensaje de un config inejecutable viaja al aviso de la interfaz, o sea que es copy público.
    Sin la traducción, una firma posicional daba «got some positional-only arguments passed as
    keyword arguments», que no le dice al lector ni qué dominio ni qué se esperaba.
    """

    class _FirmaMala:
        name = "eda"
        requires: tuple[tuple[str, str], ...] = ()
        provides: tuple[tuple[str, str], ...] = (("eda", "eda_card"),)

        @classmethod
        def from_config_with_context(
            cls, cfg: Any, active_domains: frozenset[str], /
        ) -> _FirmaMala:
            return cls()

        def execute(self, study: Study, rng: np.random.Generator) -> None:  # pragma: no cover
            del study, rng

    from nikodym.core import registry as registry_module

    study = Study(
        NikodymConfig(eda=EdaConfig(), report=ReportConfig(output_dir=str(tmp_path))),
        apply_global_seed=False,
    )
    original = registry_module.REGISTRY.resolve
    monkeypatch.setattr(
        registry_module.REGISTRY,
        "resolve",
        lambda dominio, nombre: _FirmaMala if dominio == "eda" else original(dominio, nombre),
    )

    with pytest.raises(ConfigError, match="firma incompatible"):
        study.check_pipeline(["eda", "report"])


def test_sin_hook_contextual_el_resolver_usa_from_config(tmp_path: Path) -> None:
    """Un componente que NO expone el hook se resuelve exactamente como antes."""
    study = Study(
        NikodymConfig(stability=StabilityConfig(), report=ReportConfig(output_dir=str(tmp_path))),
        apply_global_seed=False,
    )
    assert not hasattr(StabilityStep, "from_config_with_context")
    paso = study._resolve_step("stability", active_domains=frozenset({"stability"}))
    assert isinstance(paso, StabilityStep)


def test_el_gate_caza_el_defecto_que_cierra(tmp_path: Path) -> None:
    """Ancla del defecto: sin la segunda intersección esto era un ``ConfigError`` del DAG.

    Se construye a mano el ``requires`` que producía el código anterior (filtrar sólo por
    ``required_sections``) y se comprueba que ``_validate_pipeline`` lo rechaza. Un gate que sólo
    verifica el verde no demuestra que el rojo existiera.
    """
    study = Study(
        NikodymConfig(report=ReportConfig(output_dir=str(tmp_path))),
        apply_global_seed=False,
    )
    viejo = ReportStep.from_config(study.config.report)  # sin contexto ⇒ las ocho cards
    assert viejo.requires == REPORT_REQUIRED_CARDS
    with pytest.raises(ConfigError, match="necesita 'eda_card'"):
        study._validate_pipeline([viejo])
