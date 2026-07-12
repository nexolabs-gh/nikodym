"""Narrativa básica e IA opcional para reportes auditables (SDD-26 §3/§8/§9).

La ruta básica es determinística y no usa red: produce texto en español mediante reglas simples a
partir de :class:`~nikodym.report.results.ReportInputBundle`. La ruta IA es estrictamente opt-in,
acepta un cliente inyectable para pruebas o integraciones privadas, y solo envía payloads derivados
y sanitizados. Si falta la API key o el cliente falla, se degrada a la narrativa básica con un
``warning`` explícito.

**Experimental (fuera de la garantía SemVer 1.x).**
"""

from __future__ import annotations

import hashlib
import importlib
import json
import math
import os
import re
from collections.abc import Mapping, Sequence
from typing import Any, Final, Protocol, TypeAlias, cast, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from nikodym.report.config import AiNarrationConfig
from nikodym.report.document import section_sort_key
from nikodym.report.results import AiNarrationBlock, ReportInputBundle, ReportSection

__all__ = ["AIClient", "AINarrator", "AIRequest", "AIResponse", "RuleBasedNarrator"]

JSONValue: TypeAlias = dict[str, Any] | list[Any] | str | int | float | bool | None

_RULE_BASED_MODEL: Final = "rule_based_v1"
_DEFAULT_ANTHROPIC_MODEL: Final = "claude-3-5-sonnet-latest"
_DEFAULT_AI_MAX_TOKENS: Final = 900
_AI_EXTRA_MESSAGE: Final = "AINarrator requiere Anthropic; instale nikodym[ai]."
_PROMPT_VERSION: Final = "nikodym.report.ai.prompt.v1"
_SENSITIVE_PATTERN: Final = re.compile(
    r"(rut|email|phone|tel[eé]fono|id_cliente|cliente_id|customer_id)",
    flags=re.IGNORECASE,
)
_EMAIL_PATTERN: Final = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
_MAX_SEQUENCE_ITEMS: Final = 25
_DROP: Final = object()


class AIRequest(BaseModel):
    """Solicitud mínima enviada a un cliente IA con payload ya sanitizado."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    payload: dict[str, Any]
    model: str
    max_tokens: int = Field(gt=0)
    timeout_seconds: float = Field(gt=0.0)


class AIResponse(BaseModel):
    """Respuesta textual de un cliente IA."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str
    provider: str | None = None
    model: str | None = None


@runtime_checkable
class AIClient(Protocol):
    """Contrato mínimo de cliente IA inyectable, sin acoplar el SDK externo."""

    def generate(self, request: AIRequest) -> AIResponse:
        """Genera narrativa desde una solicitud sanitizada."""


class RuleBasedNarrator:
    """Narrador determinístico sin red: ruta básica y fallback."""

    def narrate(self, bundle: ReportInputBundle) -> tuple[AiNarrationBlock, ...]:
        """Genera un bloque básico por sección presente en orden canónico."""
        blocks: list[AiNarrationBlock] = []
        for section in _ordered_sections(bundle.sections):
            payload = _section_payload(bundle, section)
            input_hash = _hash_payload(payload)
            prompt = _prompt_for_payload(payload)
            blocks.append(
                AiNarrationBlock(
                    section_id=section.id,
                    text=_rule_based_text(section),
                    provider="none",
                    model=_RULE_BASED_MODEL,
                    generated=False,
                    prompt_hash=_hash_text(prompt),
                    input_payload_hash=input_hash,
                    warning=None,
                )
            )
        return tuple(blocks)


class AINarrator:
    """Narrador opt-in con cliente inyectable; nunca modifica bundle ni números."""

    def __init__(self, config: AiNarrationConfig, *, client: AIClient | None = None) -> None:
        """Construye el narrador desde config validado y un cliente opcional."""
        self.config = config
        self._client = client
        self._rule_based = RuleBasedNarrator()

    def enrich(self, bundle: ReportInputBundle) -> tuple[AiNarrationBlock, ...]:
        """Enriquece narrativa si IA está habilitada; si falla, vuelve a texto básico."""
        if not self.config.enabled or self.config.provider == "none":
            return self._rule_based.narrate(bundle)

        assert self.config.send_raw_data is False, (
            "La narrativa IA de report no permite enviar datos crudos."
        )

        try:
            client = self._client
            if client is None:
                api_key = os.environ.get(self.config.api_key_env)
                if not api_key:
                    return self._fallback(
                        bundle,
                        "Narrativa IA solicitada, pero falta la variable de entorno "
                        f"'{self.config.api_key_env}'; se usó narrativa básica determinística.",
                    )
                client = _build_anthropic_client(
                    api_key,
                    timeout_seconds=self.config.timeout_seconds,
                )
            return self._generate_ai_blocks(bundle, client)
        except _missing_dependency_error():
            raise
        except Exception as exc:
            # Deuda diferida: cuando AiNarrationConfig exponga fail_on_ai_error=True, esta rama
            # deberá levantar ReportAIError. Hoy el contrato aprobado es fallback elegante.
            return self._fallback(
                bundle,
                "Narrativa IA degradada a narrativa básica por error del cliente "
                f"({type(exc).__name__}: {exc}).",
            )

    def _generate_ai_blocks(
        self,
        bundle: ReportInputBundle,
        client: AIClient,
    ) -> tuple[AiNarrationBlock, ...]:
        """Llama al cliente IA con un request independiente por sección."""
        blocks: list[AiNarrationBlock] = []
        model = self.config.model or _DEFAULT_ANTHROPIC_MODEL
        for section in _ordered_sections(bundle.sections):
            payload = _section_payload(bundle, section)
            request = AIRequest(
                payload=payload,
                model=model,
                max_tokens=_DEFAULT_AI_MAX_TOKENS,
                timeout_seconds=self.config.timeout_seconds,
            )
            response = _validate_response(client.generate(request))
            text = response.text.strip()
            if not text:
                raise ValueError("El cliente IA devolvió texto vacío.")
            blocks.append(
                AiNarrationBlock(
                    section_id=section.id,
                    text=text,
                    provider=response.provider or self.config.provider,
                    model=response.model or model,
                    generated=True,
                    prompt_hash=_hash_text(_prompt_for_payload(payload)),
                    input_payload_hash=_hash_payload(payload),
                    warning=None,
                )
            )
        return tuple(blocks)

    def _fallback(
        self,
        bundle: ReportInputBundle,
        warning: str,
    ) -> tuple[AiNarrationBlock, ...]:
        """Devuelve bloques básicos con warning explícito de degradación IA."""
        return tuple(
            block.model_copy(update={"warning": warning})
            for block in self._rule_based.narrate(bundle)
        )


class _AnthropicAIClient:
    """Adaptador mínimo del SDK Anthropic real detrás del contrato ``AIClient``."""

    def __init__(self, raw_client: Any) -> None:
        self._raw_client = raw_client

    def generate(self, request: AIRequest) -> AIResponse:
        """Genera texto con ``messages.create`` a partir del prompt canónico."""
        response = self._raw_client.messages.create(
            model=request.model,
            max_tokens=request.max_tokens,
            messages=[{"role": "user", "content": _prompt_for_payload(request.payload)}],
        )
        return AIResponse(
            text=_extract_anthropic_text(response),
            provider="anthropic",
            model=request.model,
        )


def _build_anthropic_client(api_key: str, *, timeout_seconds: float) -> AIClient:
    """Importa Anthropic de forma perezosa y construye el cliente real."""
    try:
        anthropic = importlib.import_module("anthropic")
    except ModuleNotFoundError as exc:
        from nikodym.core.exceptions import MissingDependencyError

        raise MissingDependencyError(_AI_EXTRA_MESSAGE) from exc
    raw_client = anthropic.Anthropic(api_key=api_key, timeout=timeout_seconds)
    return _AnthropicAIClient(raw_client)


def _missing_dependency_error() -> type[Exception]:
    """Carga la excepción opcional solo dentro de la ruta IA."""
    from nikodym.core.exceptions import MissingDependencyError

    return MissingDependencyError


def _extract_anthropic_text(response: Any) -> str:
    """Extrae bloques de texto del objeto respuesta del SDK Anthropic."""
    parts = [
        str(text)
        for item in getattr(response, "content", ())
        if (text := getattr(item, "text", None)) is not None
    ]
    text = "\n".join(parts).strip()
    if not text:
        raise ValueError("La respuesta de Anthropic no contiene texto utilizable.")
    return text


def _validate_response(response: Any) -> AIResponse:
    if isinstance(response, AIResponse):
        return response
    return AIResponse.model_validate(response)


def _ordered_sections(sections: tuple[ReportSection, ...]) -> tuple[ReportSection, ...]:
    """Ordena por la clave canónica del documento (fuente única: ``report.document``)."""
    return tuple(sorted(sections, key=lambda section: (*section_sort_key(section.id), section.id)))


def _section_payload(bundle: ReportInputBundle, section: ReportSection) -> dict[str, Any]:
    payload = {
        "section": {
            "id": section.id,
            "title": section.title,
            "status": section.status,
            "source_domain": section.source_domain,
            "source_key": section.source_key,
        },
        "payload": section.payload,
        "metric_sections": section.metric_sections,
        "missing_sections": bundle.missing_sections,
    }
    return cast(dict[str, Any], _sanitize_value(payload, key_path=()))


def _sanitize_value(value: Any, *, key_path: tuple[str, ...]) -> JSONValue | object:
    if key_path and _is_sensitive_key(key_path[-1]):
        return _DROP
    if _is_dataframe_like(value):
        return _DROP
    if isinstance(value, BaseModel):
        return _sanitize_value(value.model_dump(mode="python"), key_path=key_path)
    if isinstance(value, Mapping):
        sanitized: dict[str, Any] = {}
        for raw_key in sorted(value, key=str):
            key = str(raw_key)
            item = _sanitize_value(value[raw_key], key_path=(*key_path, key))
            if item is not _DROP:
                sanitized[key] = item
        return sanitized
    if isinstance(value, tuple | list):
        return _sanitize_sequence(value, key_path=key_path)
    if isinstance(value, set | frozenset):
        ordered = sorted(value, key=lambda item: _stable_json(_canonical_value(item)))
        return _sanitize_sequence(ordered, key_path=key_path)
    if isinstance(value, str):
        if _is_sensitive_string(value):
            return _DROP
        return value
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, float):
        return _canonical_float(value)
    return {"unsupported_type": type(value).__name__}


def _sanitize_sequence(value: Sequence[Any], *, key_path: tuple[str, ...]) -> list[Any]:
    sanitized: list[Any] = []
    for item in value[:_MAX_SEQUENCE_ITEMS]:
        cleaned = _sanitize_value(item, key_path=key_path)
        if cleaned is not _DROP:
            sanitized.append(cleaned)
    if len(value) > _MAX_SEQUENCE_ITEMS:
        sanitized.append({"truncated_items": len(value) - _MAX_SEQUENCE_ITEMS})
    return sanitized


def _is_sensitive_key(key: str) -> bool:
    return _SENSITIVE_PATTERN.search(key) is not None


def _is_sensitive_string(value: str) -> bool:
    return _SENSITIVE_PATTERN.search(value) is not None or _EMAIL_PATTERN.search(value) is not None


def _rule_based_text(section: ReportSection) -> str:
    """Texto determinista de una sección: **la prosa real del documento**, no un genérico.

    La prosa la redacta :mod:`nikodym.report.prose` en el builder, con los parámetros y métricas
    reales de la corrida, y viaja en ``ReportSection.body``. Aquí sólo se transporta: así el bloque
    narrativo dejó de emitir el degenerado *"La sección X está disponible con estado included"* que
    ocupaba cinco de las once secciones del reporte viejo.
    """
    if section.status != "included":
        return (
            f"La sección {section.title} no está disponible; el reporte parcial no inventa números."
        )
    if section.body:
        return "\n\n".join(section.body)
    if section.kind == "toc":
        return "El índice enumera los capítulos y anexos que componen el informe."
    if section.kind == "appendix":
        return f"{section.title}: detalle íntegro de la corrida, sin resumir."
    if section.source_domain:
        return (
            f"La sección {section.title} reproduce las tablas y gráficos publicados por el "
            f"dominio '{section.source_domain}'."
        )
    return f"La sección {section.title} forma parte del documento."


def _prompt_for_payload(payload: Mapping[str, Any]) -> str:
    return (
        f"{_PROMPT_VERSION}\n"
        "Redacta en español una narrativa breve de validación de riesgo de crédito. "
        "No recalcules ni sustituyas números; usa únicamente el payload estructurado.\n"
        f"{_stable_json(payload)}"
    )


def _hash_payload(payload: Mapping[str, Any]) -> str:
    return _hash_text(_stable_json(payload))


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _stable_json(value: Any) -> str:
    return json.dumps(
        _canonical_value(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _canonical_value(value: Any) -> JSONValue:
    if isinstance(value, Mapping):
        return {str(key): _canonical_value(value[key]) for key in sorted(value, key=str)}
    if isinstance(value, tuple | list):
        return [_canonical_value(item) for item in value]
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, float):
        return _canonical_float(value)
    if isinstance(value, str):
        return value
    return {"unsupported_type": type(value).__name__}


def _canonical_float(value: float) -> float | dict[str, str]:
    if value == 0.0:
        return 0.0
    if math.isfinite(value):
        return value
    if math.isnan(value):
        return {"non_finite_float": "nan"}
    if value > 0:
        return {"non_finite_float": "inf"}
    return {"non_finite_float": "-inf"}


def _is_dataframe_like(value: object) -> bool:
    return all(hasattr(value, attribute) for attribute in ("columns", "copy", "select_dtypes"))
