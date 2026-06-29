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

_EXPECTED_BASIC_TEXTS: tuple[str, ...] = (
    "El lineage fija config_hash=cfg123 y data_hash=data123.",
    "El modelo usa 2 variables finales. La partición OOT no está disponible.",
    "El desempeño reporta AUC=0.743210.",
    "El PSI máximo del score cae en banda review.",
    "El reporte declara secciones ausentes: scorecard.",
    "El apéndice referencia 2 tablas y 1 figura.",
)
_EXPECTED_INPUT_HASHES: tuple[str, ...] = (
    "c7fdc7e39a561354e8538464a5231e91e0ea2b0ca2262ddaff648496ee9cac93",
    "c1125c7ea2ec0db9aede310daa6b0b62182eb4dda2b1dba6c1c43180c136d6f4",
    "5ec4b83843e83e8a4018ab82df7728ac4703ac11edf77bd3f1ddf47f69709244",
    "bec436ebc5762b3e88eb8deb898e8cd5ab3933e5dd609ae9459640313e72de14",
    "59c393d42bace7eefbbf7c4270871e84b1f2369ebfadfb8623758b328a3a6ae3",
    "219d4924b8c88db7731f73e716cb5c4f5edfb401a9ea9dd25e6e541afa4728b7",
)
_EXPECTED_PROMPT_HASHES: tuple[str, ...] = (
    "03cbb46278598b38fb0a1a760ca06a1fc8d1f1bf1c8e2ef717b1771f5531271b",
    "97f744ad0917fa9b5e6ee6dbcd13715eebc6a59cd1483568d42849da9121a63c",
    "b0c7df386983061e71f8e5d18c83a175aa6ed9595f2969ff36dc47b57893cbf0",
    "7c259db052791c436c6a970e4b0a67ba446f79fbe2b0e03e0808376941a3dad9",
    "4d0dcc6597ef98db68d3ceac0751180a6c0b3a740e7ab58cbd099bcab616e8fc",
    "7e31a4df1fd9bb1a9c2d8f52113774b229fb3b4a776d33e9b4822220cbf5f1b0",
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
    """La ruta básica es byte-determinística y no depende de entorno ni red."""
    bundle = _bundle()
    first = RuleBasedNarrator().narrate(bundle)
    second = RuleBasedNarrator().narrate(bundle)

    assert first == second
    assert tuple(block.section_id for block in first) == (
        "lineage",
        "model",
        "performance",
        "stability",
        "limitations",
        "appendix",
    )
    assert tuple(block.text for block in first) == _EXPECTED_BASIC_TEXTS
    assert tuple(block.input_payload_hash for block in first) == _EXPECTED_INPUT_HASHES
    assert tuple(block.prompt_hash for block in first) == _EXPECTED_PROMPT_HASHES
    assert all(block.provider == "none" for block in first)
    assert all(block.model == "rule_based_v1" for block in first)
    assert all(not block.generated for block in first)
    assert all(block.warning is None for block in first)


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
        request for request in fake.requests if request.payload["section"]["id"] == "model"
    )
    serialized = json.dumps(model_request.payload, sort_keys=True, ensure_ascii=False).lower()

    assert "rut" not in serialized
    assert "email" not in serialized
    assert "phone" not in serialized
    assert "id_cliente" not in serialized
    assert "bad@example.com" not in serialized
    assert "+569" not in serialized
    assert "saldo" in serialized


def test_rule_based_casos_borde_de_plantillas() -> None:
    """Las plantillas cubren secciones missing, genéricas y métricas alternativas."""
    sections = (
        _section(id="binning", title="Binning WoE", status="missing"),
        _section(id="eda", title="EDA", payload={"resumen": "ok"}),
        _section(id="model", title="Modelo sin variables", payload={}),
        _section(
            id="model", title="Modelo sin partición", payload={"selected_features": ("saldo",)}
        ),
        _section(
            id="model",
            title="Modelo con OOT",
            payload={"n_variables": 3, "partition_sizes": {"oot": 7}},
        ),
        _section(id="performance", title="KS", metric_sections={"items": [{"ks": 0.25}]}),
        _section(
            id="performance",
            title="AUC no finito",
            metric_sections={"auc": math.nan, "ks": 0.15},
        ),
        _section(id="performance", title="Performance vacía"),
        _section(id="stability", title="PSI", metric_sections={"score": {"psi": 0.2}}),
        _section(id="stability", title="Band", metric_sections={"items": [{"band": "stable"}]}),
        _section(id="stability", title="Band vacía", metric_sections={"items": [{"otro": "sin"}]}),
        _section(id="stability", title="Stability vacía"),
        _section(id="limitations", title="Limitaciones", payload={"missing_sections": ()}),
        _section(id="appendix", title="Apéndice", payload={}),
    )

    texts = tuple(block.text for block in RuleBasedNarrator().narrate(_bundle_with(sections)))

    assert any("La sección Binning WoE no está disponible" in text for text in texts)
    assert "La sección EDA está disponible con estado included." in texts
    assert "La sección Modelo sin variables está disponible con estado included." in texts
    assert "El modelo usa 1 variable final." in texts
    assert "El modelo usa 3 variables finales." in texts
    assert "El desempeño reporta KS=0.250000." in texts
    assert "El desempeño reporta KS=0.150000." in texts
    assert "La sección Performance vacía está disponible con estado included." in texts
    assert "El PSI máximo del score es 0.200000." in texts
    assert "El PSI máximo del score cae en banda stable." in texts
    assert "La sección Band vacía está disponible con estado included." in texts
    assert "La sección Stability vacía está disponible con estado included." in texts
    assert "El reporte no declara secciones obligatorias ausentes." in texts
    assert "El apéndice referencia 0 tablas y 0 figuras." in texts


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
    assert ai_module._format_float(math.nan) == "nan"
    assert ai_module._format_float(math.inf) == "inf"
    assert ai_module._format_float(-math.inf) == "-inf"
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
) -> ReportSection:
    return ReportSection(
        id=id,
        title=title,
        status=status,
        source_domain=id,
        source_key="card",
        payload={} if payload is None else payload,
        metric_sections={} if metric_sections is None else metric_sections,
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
    lineage = _lineage()
    sections = (
        ReportSection(
            id="lineage",
            title="Lineage",
            status="included",
            source_domain="core",
            source_key="lineage",
            payload=lineage.model_dump(mode="json"),
            metric_sections={},
        ),
        ReportSection(
            id="model",
            title="Modelo PD",
            status="included",
            source_domain="model",
            source_key="model_card",
            payload=_model_payload(pii=pii),
            metric_sections={"model": {"p_value_max": 0.041}},
        ),
        ReportSection(
            id="performance",
            title="Desempeño",
            status="included",
            source_domain="performance",
            source_key="card",
            payload={},
            metric_sections={"performance": {"auc": 0.74321, "ks": 0.31234}},
        ),
        ReportSection(
            id="stability",
            title="Estabilidad",
            status="included",
            source_domain="stability",
            source_key="card",
            payload={},
            metric_sections={"stability": {"score_psi": {"max_psi": 0.271, "band": "review"}}},
        ),
        ReportSection(
            id="limitations",
            title="Limitaciones",
            status="included",
            source_domain="report",
            source_key="limitations",
            payload={"missing_sections": ("scorecard",)},
            metric_sections={},
        ),
        ReportSection(
            id="appendix",
            title="Apéndice",
            status="included",
            source_domain="report",
            source_key="appendix",
            payload={
                "table_keys": ("model.coefficients", "performance.metrics"),
                "figure_keys": ("eda.figures",),
            },
            metric_sections={},
        ),
    )
    return ReportInputBundle(
        lineage=lineage,
        cards={"model": {"selected_features": ("saldo", "mora")}},
        tables={},
        figures={},
        sections=sections,
        missing_sections=("scorecard",),
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
