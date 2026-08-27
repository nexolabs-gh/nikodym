"""Gate de copy público (lado informe): el cuerpo explica, el anexo identifica.

Hermano de :mod:`tests.unit.test_public_copy`, que cubre `docs_site/` y el README. Aquí se cubre el
artefacto que firma un validador, y el contrato tiene **dos mitades** que se prueban en los dos
sentidos (`AGENTS.md` §copy público, publicado en `docs_site/avisos-declarados.md`):

    «En el informe HTML/PDF/Word los códigos aparecen sólo en el volcado de auditoría del anexo.
    La prosa del informe explica la limitación en palabras, sin nombrar el código.»

Un gate que sólo probara la primera mitad se satisfaría **descartando** los avisos, que es el error
simétrico y peor: esconder una limitación en un producto regulatorio. Por eso el anexo se prueba en
positivo y el cuerpo en negativo, sobre el **mismo HTML renderizado**.

El HTML se construye con el builder y el renderer reales —no con un snapshot de helper— porque la
regla del repo es verificar el artefacto que consume la persona (runbook §5).
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any, Final

import pytest

from nikodym.core.lineage import LineageBundle
from nikodym.core.markers import DECLARED_MARKERS
from nikodym.report.builder import ReportBuilder
from nikodym.report.config import ReportConfig
from nikodym.report.prose import _DECLARED_WARNING_SIN_TEXTO, _declared_warning_prose
from nikodym.report.renderer import HtmlReportRenderer
from nikodym.report.results import ReportInputBundle

#: Cualquiera de las dos marcas, con o sin sufijo de familia. Mismo criterio que el gate de docs:
#: la marca pelada cuenta, porque «declaradas como FALTA-DATO» es igual de opaco para el lector.
_CODIGO_INTERNO: Final = re.compile("|".join(re.escape(m) for m in DECLARED_MARKERS))

#: Código que **no** existe en el motor. Es el corazón del gate: prueba la rama de fallback, que es
#: por donde se filtraba el código crudo cada vez que una capa emitía un aviso que el capítulo no
#: tenía tabulado. Sin este caso el gate quedaría verde con los diccionarios de hoy y se rompería
#: en silencio con el próximo código nuevo.
_CODIGO_DESCONOCIDO: Final = "FALTA-DATO-XXX-99"

#: Avisos que llegan a la prosa **pelados**, sin mensaje que recortar: si no tienen frase propia en
#: el informe, no hay ninguna otra vía que pueda redactarlos. Se enumeran por capa para que añadir
#: un código al motor sin darle frase caiga en rojo aquí.
_AVISOS_PELADOS: Final[dict[str, tuple[str, ...]]] = {
    "validation": ("FALTA-DATO-VAL-1", "FALTA-DATO-VAL-2", "FALTA-DATO-VAL-3"),
    "provisioning_ifrs9": (
        "FALTA-DATO-IFRS-4",
        "FALTA-DATO-IFRS-6",
        "FALTA-DATO-IFRS-8",
        "DATO-INSTITUCIONAL-IFRS-7",
    ),
}

#: Avisos que el motor emite como ``CÓDIGO: explicación`` (``provisioning/orchestrator.py`` y el
#: bloqueo de backtesting de ``validation/evaluator.py``). Aquí la frase ya existe: lo que el
#: informe tiene que hacer es recortar el código y conservar el texto.
_AVISOS_CON_MENSAJE: Final[tuple[str, ...]] = (
    "DATO-INSTITUCIONAL-PROV-1: celda 'consumo' sin contraparte interno.",
    "DATO-INSTITUCIONAL-PROV-2: celda 'hipotecario' imputó 0 al motor interno "
    "(treat_missing_as_zero).",
    "DATO-INSTITUCIONAL-PROV-3: comparación incompleta; solo el motor cmf está presente "
    "(require_both=False).",
    "DATO-INSTITUCIONAL-PROV-4: la taxonomía de cmf trae carteras sin equivalencia en la de "
    "interno ('consumo'); declárelas en portfolio_crosswalk.",
    "DATO-INSTITUCIONAL-VAL-4: families incluye 'backtesting' pero backtesting.enabled=False.",
)


def _lineage() -> LineageBundle:
    return LineageBundle(
        git_sha="abc123",
        git_dirty=False,
        data_hash="data123456789abcdef",
        config_hash="cfg123456789abcdef",
        root_seed=42,
        uv_lock_hash="uv123",
        library_versions={"nikodym": "1.11.0"},
        determinism_caveats=[],
        created_at=datetime(2026, 8, 26, 9, 30, tzinfo=UTC),
        schema_version="1.0.0",
    )


def _cards_envenenadas() -> dict[str, Any]:
    """Cards con **todos** los avisos que cada capa puede publicar, más uno desconocido."""
    validation_gaps = (
        *_AVISOS_PELADOS["validation"],
        "DATO-INSTITUCIONAL-VAL-4: families incluye 'backtesting' pero backtesting.enabled=False.",
        _CODIGO_DESCONOCIDO,
    )
    return {
        "validation": {
            "model_ref": "scorecard-retail",
            "overall_status": "amber",
            "n_tests": 12,
            "n_failed": 1,
            "families_run": ("calibration", "backtesting"),
            "falta_dato": validation_gaps,
        },
        "provisioning_ifrs9": {
            "total_ecl_reported": 1000.0,
            "total_ead": 100000.0,
            "falta_dato": (*_AVISOS_PELADOS["provisioning_ifrs9"], _CODIGO_DESCONOCIDO),
        },
        "provisioning": {
            "source_a": "cmf",
            "source_b": "internal",
            "rule": "max",
            "binding": "cmf",
            "comparison_level": "portfolio",
            "falta_dato": (*_AVISOS_CON_MENSAJE, _CODIGO_DESCONOCIDO),
        },
    }


def _html() -> str:
    """Renderiza el informe REAL: builder, renderer y plantillas de producción."""
    cfg = ReportConfig(sections={"missing_policy": "skip"})
    bundle = ReportInputBundle(
        lineage=_lineage(),
        cards=_cards_envenenadas(),
        results={"validation": {"model_ref": "scorecard-retail"}},
        tables={},
        figures={},
        sections=(),
    )
    bundle = bundle.model_copy(update={"sections": ReportBuilder(cfg).build_sections(bundle)})
    return HtmlReportRenderer(cfg).render(bundle)


def _secciones(html: str) -> list[str]:
    """Trocea el HTML en secciones. El renderer las emite hermanas, nunca anidadas."""
    return [f"<section{fragmento}" for fragmento in html.split("<section")[1:]]


def _cuerpo(html: str) -> list[str]:
    return [s for s in _secciones(html) if 'data-kind="appendix"' not in s]


def _anexo(html: str) -> list[str]:
    return [s for s in _secciones(html) if 'data-kind="appendix"' in s]


@pytest.fixture(scope="module")
def informe() -> str:
    return _html()


def test_el_informe_tiene_cuerpo_y_anexo_que_revisar(informe: str) -> None:
    """Sin esto, un render vacío o un `data-kind` renombrado dejaría el gate barriendo nada."""
    assert len(_cuerpo(informe)) >= 5
    assert len(_anexo(informe)) >= 2


def test_el_cuerpo_publica_los_tres_parrafos_de_aviso(informe: str) -> None:
    """El gate negativo sólo prueba algo si los párrafos que puede ensuciar existen de verdad."""
    cuerpo = "".join(_cuerpo(informe))
    assert "Brechas de dato declaradas por la validación:" in cuerpo
    assert "El orquestador reportó advertencias que el lector debe conocer:" in cuerpo
    assert "El motor reportó advertencias de datos que el lector debe conocer:" in cuerpo


def test_la_prosa_del_cuerpo_no_nombra_ningun_codigo_interno(informe: str) -> None:
    """Primera mitad del contrato: el cuerpo explica la limitación, no la identifica."""
    ofensores = [
        seccion.split(">", 1)[0][:120]
        for seccion in _cuerpo(informe)
        if _CODIGO_INTERNO.search(seccion)
    ]
    assert ofensores == []


def test_el_anexo_de_auditoria_conserva_los_codigos(informe: str) -> None:
    """Segunda mitad: ahí el código **es** el dato, y perderlo sería esconder la limitación.

    Es el gate que impide «cumplir» el contrato descartando los avisos en vez de traducirlos.
    """
    anexo = "".join(_anexo(informe))
    esperados = (
        *_AVISOS_PELADOS["validation"],
        *_AVISOS_PELADOS["provisioning_ifrs9"],
        _CODIGO_DESCONOCIDO,
    )
    ausentes = [codigo for codigo in esperados if codigo not in anexo]
    assert ausentes == []


@pytest.mark.parametrize(
    "codigo",
    (*_AVISOS_PELADOS["validation"], *_AVISOS_PELADOS["provisioning_ifrs9"]),
)
def test_cada_aviso_pelado_tiene_frase_propia(codigo: str) -> None:
    """Completitud en el otro sentido: un código pelado sin frase degradaría al texto genérico.

    El genérico es la red de seguridad del contrato, no el resultado aceptable: un aviso que el
    motor sabe explicar tiene que llegar explicado.
    """
    frase = _declared_warning_prose(codigo)
    assert frase != _DECLARED_WARNING_SIN_TEXTO.removesuffix(".")
    assert not _CODIGO_INTERNO.search(frase)


@pytest.mark.parametrize("aviso", _AVISOS_CON_MENSAJE)
def test_un_aviso_con_mensaje_conserva_el_texto_y_pierde_el_codigo(aviso: str) -> None:
    """La vía de D-ERR-4: recortar el código y conservar la explicación que el motor ya escribió."""
    frase = _declared_warning_prose(aviso)
    assert not _CODIGO_INTERNO.search(frase)
    assert len(frase) > 20


def test_un_codigo_desconocido_se_declara_sin_nombrarse() -> None:
    """La rama por la que se filtraba el código crudo antes de esta capa."""
    frase = _declared_warning_prose(_CODIGO_DESCONOCIDO)
    assert frase == _DECLARED_WARNING_SIN_TEXTO.removesuffix(".")
    assert not _CODIGO_INTERNO.search(frase)


def test_la_frase_no_termina_en_punto() -> None:
    """Quien llama enumera y cierra; sin el recorte el párrafo terminaba en `..`."""
    assert not _declared_warning_prose(_AVISOS_CON_MENSAJE[0]).endswith(".")


def test_el_mismo_aviso_repetido_no_duplica_la_frase(informe: str) -> None:
    """`validation` puede declarar dos veces el mismo código; el lector no gana leyéndolo dos veces.

    Se comprueba sobre el HTML real: la frase del semáforo aparece una sola vez en todo el cuerpo.
    """
    cuerpo = "".join(_cuerpo(informe))
    assert cuerpo.count("los cortes del semáforo verde/ámbar/rojo") == 1
