"""Tests de ``report.ai``: narrativa básica, IA opt-in, privacidad y fallback."""

from __future__ import annotations

import importlib
import json
import math
import subprocess
import sys
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import BaseModel

import nikodym.report as report_pkg
import nikodym.report.ai as ai_module
from nikodym.core.exceptions import MissingDependencyError
from nikodym.core.lineage import LineageBundle
from nikodym.report.ai import AIClient, AINarrator, AIRequest, AIResponse, RuleBasedNarrator
from nikodym.report.config import AiNarrationConfig
from nikodym.report.results import ReportInputBundle, ReportSection

_EXPECTED_SECTION_IDS: tuple[str, ...] = (
    "context",
    "methodology.binning",
    "results.model",
    "results.performance",
    "limitations",
    "appendix_lineage",
)
# La narrativa determinista ES la prosa del documento (``ReportSection.body``): el narrador la
# transporta en vez de emitir el genérico "La sección X está disponible con estado included".
_EXPECTED_BASIC_TEXTS: tuple[str, ...] = (
    "La cartera es de consumo.",
    "El binning se resolvió por MIP con 8 bins.",
    "El modelo retiene 2 variables.",
    "En Desarrollo el modelo alcanza AUC 0.7432.",
    "No hay secciones obligatorias ausentes.",
    "Anexo A — Lineage y reproducibilidad: detalle íntegro de la corrida, sin resumir.",
)


class FakeAIClient:
    """Cliente IA fake in-memory para probar sin red."""

    def __init__(self, *, prefix: str = "Narrativa IA") -> None:
        self.prefix = prefix
        self.requests: list[AIRequest] = []

    def generate(self, request: AIRequest) -> AIResponse:
        """Guarda el request y devuelve texto sintético determinístico."""
        self.requests.append(request)
        section_id = request.payload["section"]["id"]
        return AIResponse(
            text=f"{self.prefix}: sección {section_id}.",
            provider="anthropic",
            model=request.model,
        )


class ErrorAIClient:
    """Cliente IA fake que simula timeout/error de proveedor."""

    def generate(self, request: AIRequest) -> AIResponse:
        """Lanza un timeout después de recibir el request."""
        raise TimeoutError(f"timeout sintético para {request.model}")


class BlankAIClient:
    """Cliente IA fake que devuelve texto vacío."""

    def generate(self, request: AIRequest) -> AIResponse:
        """Devuelve solo espacios para ejercer validación de respuesta."""
        return AIResponse(text="  ", provider="anthropic", model=request.model)


class DictAIClient:
    """Cliente IA fake que devuelve mapping validable como ``AIResponse``."""

    def generate(self, request: AIRequest) -> Any:
        """Devuelve dict para cubrir coacción Pydantic de respuesta."""
        return {"text": "Texto desde mapping validado.", "provider": None, "model": None}


class ExplosiveEnv(dict[str, str]):
    """Entorno que falla si la rama inyectada intenta leer API keys."""

    def get(self, key: str, default: Any = None) -> str | Any:
        """Falla si ``AINarrator`` consulta variables de entorno."""
        raise AssertionError(f"No se debía leer entorno: {key!r}, {default!r}")


def test_rule_based_narrator_golden_deterministico_sin_red() -> None:
    """La ruta básica es byte-determinística, sigue el orden del documento y no toca la red."""
    bundle = _bundle()
    first = RuleBasedNarrator().narrate(bundle)
    second = RuleBasedNarrator().narrate(bundle)

    assert first == second
    # Orden canónico del documento, aunque el bundle llegue desordenado (fuente única: document).
    assert tuple(block.section_id for block in first) == _EXPECTED_SECTION_IDS
    assert tuple(block.text for block in first) == _EXPECTED_BASIC_TEXTS
    assert all(block.provider == "none" for block in first)
    assert all(block.model == "rule_based_v1" for block in first)
    assert all(not block.generated for block in first)
    assert all(block.warning is None for block in first)
    # Los hashes de auditoría son estables entre corridas y distintos entre secciones.
    assert len({block.input_payload_hash for block in first}) == len(first)
    assert all(len(block.input_payload_hash) == 64 for block in first)
    assert all(len(block.prompt_hash) == 64 for block in first)


def test_ningun_bloque_cae_en_el_generico_degenerado() -> None:
    """Ninguna sección con prosa emite ya "está disponible con estado included".

    Ese texto ocupaba cinco de las once secciones del reporte viejo (eda, binning, selection,
    scorecard, calibration) y es exactamente lo que esta mejora elimina.
    """
    textos = tuple(block.text for block in RuleBasedNarrator().narrate(_bundle()))

    assert all("está disponible con estado" not in texto for texto in textos)
    assert all(texto.strip() for texto in textos)


def test_ai_narrator_disabled_o_provider_none_usa_ruta_basica() -> None:
    """La ruta básica no depende de la IA aunque exista config de narración."""
    bundle = _bundle()
    basic = RuleBasedNarrator().narrate(bundle)

    assert AINarrator(AiNarrationConfig()).enrich(bundle) == basic
    assert AINarrator(AiNarrationConfig(enabled=True, provider="none")).enrich(bundle) == basic


def test_ai_narrator_con_cliente_inyectado_no_lee_env_y_no_muta_bundle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Un cliente inyectado evita env vars, marca IA y deja intacto el bundle."""
    bundle = _bundle()
    before = _sections_json(bundle)
    fake = FakeAIClient()
    monkeypatch.setattr(ai_module.os, "environ", ExplosiveEnv())

    blocks = AINarrator(
        AiNarrationConfig(
            enabled=True,
            provider="anthropic",
            model="modelo-test",
            api_key_env="NO_DEBE_LEERSE",
        ),
        client=fake,
    ).enrich(bundle)

    assert isinstance(fake, AIClient)
    assert len(fake.requests) == len(bundle.sections)
    assert tuple(block.generated for block in blocks) == (True,) * len(bundle.sections)
    assert tuple(block.provider for block in blocks) == ("anthropic",) * len(bundle.sections)
    assert {request.model for request in fake.requests} == {"modelo-test"}
    assert {request.max_tokens for request in fake.requests} == {900}
    assert all(block.prompt_hash for block in blocks)
    assert all(block.input_payload_hash for block in blocks)
    assert _sections_json(bundle) == before


def test_ai_narrator_valida_respuesta_mapping_y_texto_vacio_degrada() -> None:
    """Respuestas mapping se aceptan; texto vacío degrada a fallback explícito."""
    mapping_blocks = AINarrator(
        AiNarrationConfig(enabled=True, provider="anthropic"),
        client=DictAIClient(),
    ).enrich(_bundle())

    assert mapping_blocks[0].generated is True
    assert mapping_blocks[0].text == "Texto desde mapping validado."
    assert mapping_blocks[0].provider == "anthropic"
    assert mapping_blocks[0].model == "claude-3-5-sonnet-latest"

    blank_blocks = AINarrator(
        AiNarrationConfig(enabled=True, provider="anthropic"),
        client=BlankAIClient(),
    ).enrich(_bundle())

    assert all(not block.generated for block in blank_blocks)
    assert all(
        block.warning is not None and "texto vacío" in block.warning for block in blank_blocks
    )


def test_ai_narrator_env_gated_sin_key_entra_a_fallback_explicito(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``enabled=True`` sin API key ejerce la rama real de fallback explícito."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    blocks = AINarrator(
        AiNarrationConfig(enabled=True, provider="anthropic"),
    ).enrich(_bundle())

    assert tuple(block.text for block in blocks) == _EXPECTED_BASIC_TEXTS
    assert all(not block.generated for block in blocks)
    assert all(block.warning is not None for block in blocks)
    assert all(
        "falta la variable de entorno 'ANTHROPIC_API_KEY'" in block.warning for block in blocks
    )


def test_ai_narrator_degrada_por_error_del_cliente_sin_propagar() -> None:
    """Un timeout del cliente IA vuelve a narrativa básica con warning explícito."""
    blocks = AINarrator(
        AiNarrationConfig(enabled=True, provider="anthropic", model="modelo-test"),
        client=ErrorAIClient(),
    ).enrich(_bundle())

    assert tuple(block.text for block in blocks) == _EXPECTED_BASIC_TEXTS
    assert all(not block.generated for block in blocks)
    assert all(block.provider == "none" for block in blocks)
    assert all(block.warning is not None and "TimeoutError" in block.warning for block in blocks)


def test_ai_payload_sanitiza_pii_antes_de_enviar_al_cliente() -> None:
    """El request IA elimina claves y valores obvios de PII/IDs."""
    fake = FakeAIClient()
    AINarrator(
        AiNarrationConfig(enabled=True, provider="anthropic", model="modelo-test"),
        client=fake,
    ).enrich(_bundle(pii=True))

    model_request = next(
        request for request in fake.requests if request.payload["section"]["id"] == "results.model"
    )
    serialized = json.dumps(model_request.payload, sort_keys=True, ensure_ascii=False).lower()

    assert "rut" not in serialized
    assert "email" not in serialized
    assert "phone" not in serialized
    assert "id_cliente" not in serialized
    assert "bad@example.com" not in serialized
    assert "+569" not in serialized
    assert "saldo" in serialized


def test_rule_based_casos_borde_de_secciones_sin_prosa() -> None:
    """Secciones ausentes, índice, anexos y datos sin prosa tienen texto propio, no genérico."""
    sections = (
        _section(id="results.binning", title="Binning WoE", status="missing", kind="data"),
        _section(
            id="results.model",
            title="Modelo PD",
            kind="data",
            body=("Párrafo uno.", "Párrafo dos."),
        ),
        _section(id="results.scorecard", title="Scorecard", kind="data"),
        _section(id="toc", title="Índice", kind="toc"),
        _section(id="appendix_tables", title="Anexo B — Tablas detalladas", kind="appendix"),
        _section(id="conclusions", title="Conclusiones", kind="prose", source_domain=None),
    )

    texts = tuple(block.text for block in RuleBasedNarrator().narrate(_bundle_with(sections)))

    assert any("La sección Binning WoE no está disponible" in text for text in texts)
    # Un body multipárrafo viaja íntegro en el bloque narrativo.
    assert "Párrafo uno.\n\nPárrafo dos." in texts
    # Una subsección de datos sin prosa remite a sus tablas, no dice "estado included".
    assert (
        "La sección Scorecard reproduce las tablas y gráficos publicados por el dominio "
        "'scorecard'." in texts
    )
    assert "El índice enumera los capítulos y anexos que componen el informe." in texts
    assert "Anexo B — Tablas detalladas: detalle íntegro de la corrida, sin resumir." in texts
    assert "La sección Conclusiones forma parte del documento." in texts


def test_sanitizacion_y_canonico_cubren_tipos_defensivos() -> None:
    """La sanitización descarta tablas, normaliza colecciones y no filtra objetos opacos."""
    cleaned = ai_module._sanitize_value(
        {
            "frame": FrameLike(),
            "model": MiniModel(value=1),
            "tags": {"b", "a"},
            "long": tuple(range(30)),
            "opaque": object(),
            "minus_zero": -0.0,
        },
        key_path=(),
    )

    assert cleaned == {
        "long": [*range(25), {"truncated_items": 5}],
        "minus_zero": 0.0,
        "model": {"value": 1},
        "opaque": {"unsupported_type": "object"},
        "tags": ["a", "b"],
    }
    assert ai_module._stable_json({"opaque": object()}) == (
        '{"opaque":{"unsupported_type":"object"}}'
    )
    assert ai_module._canonical_float(math.nan) == {"non_finite_float": "nan"}
    assert ai_module._canonical_float(math.inf) == {"non_finite_float": "inf"}
    assert ai_module._canonical_float(-math.inf) == {"non_finite_float": "-inf"}
    assert ai_module._canonical_float(-0.0) == 0.0
    with pytest.raises(ValueError, match="no contiene texto"):
        ai_module._extract_anthropic_text(SimpleNamespace(content=[]))


def test_ai_narrator_env_con_sdk_fake_usa_import_perezoso_y_cliente_real(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Con API key presente, la ruta sin cliente construye el adaptador Anthropic."""
    fake_module = FakeAnthropicModule()

    def fake_import(name: str) -> Any:
        if name == "anthropic":
            return fake_module
        return importlib.import_module(name)

    monkeypatch.setenv("ANTHROPIC_API_KEY", "key-test")
    monkeypatch.setattr(ai_module.importlib, "import_module", fake_import)

    blocks = AINarrator(
        AiNarrationConfig(enabled=True, provider="anthropic", model="modelo-real"),
    ).enrich(_bundle())

    assert fake_module.instances[0].api_key == "key-test"
    assert fake_module.instances[0].timeout == 20.0
    assert fake_module.instances[0].messages.calls[0]["model"] == "modelo-real"
    assert blocks[0].generated is True
    assert blocks[0].text.startswith("Texto Anthropic fake:")
    assert blocks[0].model == "modelo-real"


def test_ai_narrator_env_con_sdk_ausente_lanza_missing_dependency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """La ausencia de ``anthropic`` se traduce a ``MissingDependencyError`` español."""

    def fake_import(name: str) -> Any:
        if name == "anthropic":
            raise ModuleNotFoundError("anthropic")
        return importlib.import_module(name)

    monkeypatch.setenv("ANTHROPIC_API_KEY", "key-test")
    monkeypatch.setattr(ai_module.importlib, "import_module", fake_import)

    with pytest.raises(MissingDependencyError, match=r"instale nikodym\[ai\]"):
        AINarrator(
            AiNarrationConfig(enabled=True, provider="anthropic"),
        ).enrich(_bundle())


def test_report_ai_lazy_exports_y_nucleo_liviano_por_subprocess() -> None:
    """``import nikodym.report`` y sus exports IA no arrastran ``anthropic``."""
    code = (
        "import sys;"
        "import nikodym.report as report;"
        "assert 'anthropic' not in sys.modules;"
        "assert all(name in report.__all__ for name in "
        "('AIClient','AIRequest','AIResponse','RuleBasedNarrator','AINarrator'));"
        "assert report.AINarrator.__name__ == 'AINarrator';"
        "assert report.AIRequest.__name__ == 'AIRequest';"
        "assert 'anthropic' not in sys.modules"
    )
    subprocess.run([sys.executable, "-c", code], check=True)
    assert report_pkg.AINarrator is AINarrator
    assert report_pkg.RuleBasedNarrator is RuleBasedNarrator


class FakeMessages:
    """Captura llamadas a ``messages.create`` del SDK fake."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        """Guarda kwargs y devuelve una respuesta con bloques ``text``."""
        self.calls.append(kwargs)
        return SimpleNamespace(content=[SimpleNamespace(text="Texto Anthropic fake: ok.")])


class FakeAnthropicRawClient:
    """Cliente raw fake con la forma mínima del SDK Anthropic."""

    def __init__(self, *, api_key: str, timeout: float) -> None:
        self.api_key = api_key
        self.timeout = timeout
        self.messages = FakeMessages()


class FakeAnthropicModule:
    """Módulo fake retornado por ``importlib.import_module('anthropic')``."""

    def __init__(self) -> None:
        self.instances: list[FakeAnthropicRawClient] = []

    def Anthropic(self, *, api_key: str, timeout: float) -> FakeAnthropicRawClient:  # noqa: N802
        """Construye y registra clientes fake."""
        client = FakeAnthropicRawClient(api_key=api_key, timeout=timeout)
        self.instances.append(client)
        return client


class FrameLike:
    """Objeto mínimo con forma de DataFrame para sanitización."""

    columns: tuple[str, ...] = ("rut",)

    def copy(self, *, deep: bool) -> FrameLike:
        """Devuelve una copia sintética."""
        del deep
        return FrameLike()

    def select_dtypes(self) -> tuple[object, ...]:
        """Imita el método que identifica DataFrames reales."""
        return ()


class MiniModel(BaseModel):
    """Modelo Pydantic mínimo usado como payload anidado."""

    value: int


def _lineage() -> LineageBundle:
    return LineageBundle(
        git_sha="abc123",
        git_dirty=False,
        data_hash="data123",
        config_hash="cfg123",
        root_seed=42,
        uv_lock_hash="uv123",
        library_versions={"nikodym": "0.1.0"},
        determinism_caveats=[],
        created_at=datetime(2026, 6, 24, 9, 30, tzinfo=UTC),
        schema_version="1.0.0",
    )


def _section(
    *,
    id: str,
    title: str,
    status: str = "included",
    payload: dict[str, Any] | None = None,
    metric_sections: Any | None = None,
    kind: str = "data",
    body: tuple[str, ...] = (),
    source_domain: str | None = "",
) -> ReportSection:
    domain = id.partition(".")[2] or id if source_domain == "" else source_domain
    return ReportSection(
        id=id,
        title=title,
        status=status,
        source_domain=domain,
        source_key="card",
        payload={} if payload is None else payload,
        metric_sections={} if metric_sections is None else metric_sections,
        kind=kind,  # type: ignore[arg-type]
        body=body,
    )


def _bundle_with(sections: tuple[ReportSection, ...]) -> ReportInputBundle:
    lineage = _lineage()
    return ReportInputBundle(
        lineage=lineage,
        cards={},
        tables={},
        figures={},
        sections=sections,
        missing_sections=(),
    )


def _bundle(*, pii: bool = False) -> ReportInputBundle:
    """Bundle del documento nuevo, con las secciones intencionalmente desordenadas."""
    lineage = _lineage()
    sections = (
        ReportSection(
            id="results.performance",
            title="Desempeño y discriminación",
            status="included",
            source_domain="performance",
            source_key="card",
            payload={},
            metric_sections={"performance": {"auc": 0.74321, "ks": 0.31234}},
            kind="data",
            level=2,
            number="4.6",
            body=("En Desarrollo el modelo alcanza AUC 0.7432.",),
        ),
        ReportSection(
            id="appendix_lineage",
            title="Anexo A — Lineage y reproducibilidad",
            status="included",
            source_domain="report",
            source_key="appendix_lineage",
            payload=lineage.model_dump(mode="json"),
            metric_sections={},
            kind="appendix",
            level=1,
            number="A",
        ),
        ReportSection(
            id="context",
            title="Contexto del modelo y de la cartera",
            status="included",
            source_domain="report",
            source_key="context",
            payload={},
            metric_sections={},
            kind="prose",
            level=1,
            number="2",
            body=("La cartera es de consumo.",),
        ),
        ReportSection(
            id="results.model",
            title="Modelo PD",
            status="included",
            source_domain="model",
            source_key="model_card",
            payload=_model_payload(pii=pii),
            metric_sections={"model": {"p_value_max": 0.041}},
            kind="data",
            level=2,
            number="4.3",
            body=("El modelo retiene 2 variables.",),
        ),
        ReportSection(
            id="methodology.binning",
            title="Binning WoE",
            status="included",
            source_domain="binning",
            source_key="binning_card",
            payload={},
            metric_sections={},
            kind="prose",
            level=2,
            number="3.2",
            body=("El binning se resolvió por MIP con 8 bins.",),
        ),
        ReportSection(
            id="limitations",
            title="Limitaciones y supuestos",
            status="included",
            source_domain="report",
            source_key="limitations",
            payload={"missing_sections": ()},
            metric_sections={},
            kind="prose",
            level=1,
            number="6",
            body=("No hay secciones obligatorias ausentes.",),
        ),
    )
    return ReportInputBundle(
        lineage=lineage,
        cards={"model": {"selected_features": ("saldo", "mora")}},
        tables={},
        figures={},
        sections=sections,
        missing_sections=(),
    )


def _model_payload(*, pii: bool) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "selected_features": ("saldo", "mora"),
        "partition_sizes": {"dev": 100, "holdout": 50},
    }
    if pii:
        payload.update(
            {
                "rut": "12.345.678-9",
                "email": "bad@example.com",
                "phone": "+56912345678",
                "id_cliente": "cli-001",
                "selected_features": ("saldo", "email", "phone", "id_cliente", "rut"),
                "nested": {"safe": 1, "rut": "98.765.432-1"},
            }
        )
    return payload


def _sections_json(bundle: ReportInputBundle) -> tuple[dict[str, Any], ...]:
    return tuple(section.model_dump(mode="json") for section in bundle.sections)
