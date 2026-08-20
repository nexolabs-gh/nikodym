"""Gates estáticos de copy público y catálogo documental del arnés H9R."""

from __future__ import annotations

import ast
import hashlib
import html
import io
import json
import os
import re
import stat
import tomllib
import zipfile
from collections.abc import Iterable, Mapping, Sequence
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from typing import Any
from xml.etree import ElementTree


class CopyGateError(RuntimeError):
    """Error local del censo estático, desacoplado del runtime del arnés."""


# Alias interno para mantener compactos los oráculos sin importar ``contracts.py``.
ContractError = CopyGateError

_CAPACITY_SEPARATOR = r"\s*(?:[-\u2010-\u2015]\s*)?"
_CPU_QUANTITY = r"(?:4|four|cuatro|quad)"
_CPU_RESOURCE = r"(?:v?cpus?|cores?|processors?|procesadores?|núcleos?|nucleos?|hilos?|threads?)"
_MEMORY_QUANTITY = r"(?:8|eight|ocho)"
_MEMORY_UNIT = r"(?:gi?b|gigabytes?|gigas?)"
_MEMORY_RESOURCE = r"(?:ram|memory|memoria)"
_RESOURCE_LINK = rf"{_CAPACITY_SEPARATOR}(?:(?:of|de)\s*|:\s*)?"

CAPACITY_PATTERNS = (
    re.compile(
        rf"(?i)\b{_CPU_QUANTITY}{_CAPACITY_SEPARATOR}"
        rf"(?:(?:logical|lógicos?|logicos?){_CAPACITY_SEPARATOR})?"
        rf"{_CPU_RESOURCE}"
        rf"(?:{_CAPACITY_SEPARATOR}(?:logical|lógicos?|logicos?))?\b"
    ),
    re.compile(
        rf"(?i)\b{_CPU_RESOURCE}{_RESOURCE_LINK}{_CPU_QUANTITY}"
        rf"(?:{_CAPACITY_SEPARATOR}(?:logical|lógicos?|logicos?))?"
        rf"(?:{_CAPACITY_SEPARATOR}{_CPU_RESOURCE})?\b"
    ),
    re.compile(
        rf"(?i)\b{_MEMORY_QUANTITY}{_CAPACITY_SEPARATOR}{_MEMORY_UNIT}"
        rf"(?:{_CAPACITY_SEPARATOR}(?:of|de))?"
        rf"{_CAPACITY_SEPARATOR}{_MEMORY_RESOURCE}\b"
    ),
    re.compile(
        rf"(?i)\b{_MEMORY_QUANTITY}{_CAPACITY_SEPARATOR}g"
        rf"{_CAPACITY_SEPARATOR}{_MEMORY_RESOURCE}\b"
    ),
    re.compile(
        rf"(?i)\b8192{_CAPACITY_SEPARATOR}(?:mi?b)"
        rf"(?:{_CAPACITY_SEPARATOR}(?:of|de))?"
        rf"{_CAPACITY_SEPARATOR}{_MEMORY_RESOURCE}\b"
    ),
    re.compile(
        rf"(?i)\b{_MEMORY_RESOURCE}{_RESOURCE_LINK}{_MEMORY_QUANTITY}"
        rf"{_CAPACITY_SEPARATOR}{_MEMORY_UNIT}\b"
    ),
    re.compile(
        rf"(?i)\b{_MEMORY_RESOURCE}{_RESOURCE_LINK}8192"
        rf"{_CAPACITY_SEPARATOR}(?:mi?b)\b"
    ),
)
TEXT_SUFFIXES = {
    ".css",
    ".html",
    ".js",
    ".json",
    ".md",
    ".mjs",
    ".py",
    ".qmd",
    ".toml",
    ".ts",
    ".tsx",
    ".yaml",
    ".yml",
    ".j2",
    ".rst",
    ".svg",
    ".txt",
    ".xml",
}
RENDERED_SUFFIXES = {".docx", ".pdf"}
PUBLIC_ARCHIVE_SUFFIXES = {".zip"}
_MAX_PUBLIC_ARCHIVE_ENTRIES = 256
_MAX_PUBLIC_ARCHIVE_MEMBER_BYTES = 32 * 1024 * 1024
_MAX_PUBLIC_ARCHIVE_TOTAL_BYTES = 128 * 1024 * 1024
_MAX_PUBLIC_ARCHIVE_COMPRESSION_RATIO = 100
INTERNAL_ROOT_FILES = {"AGENTS.md", "CLAUDE.md", "HANDOFF.md"}
PUBLIC_COPY_TREES = (
    "docs_site",
    "reports",
    "site",
    "web",
    # Los tooltips Pydantic, cards del backend, paneles y prosa de informes pueden nacer
    # en cualquier subpaquete. Tokenizar Python evita convertir comentarios internos en copy.
    "src/nikodym",
)
_IGNORED_PUBLIC_TREE_PARTS = frozenset({"__pycache__", "node_modules", "coverage"})
_REPARSE_FLAG = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
_DOCX_VISIBLE_TAGS = {
    "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t",
    "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}instrText",
    "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}delText",
    "{http://schemas.openxmlformats.org/drawingml/2006/main}t",
    "{http://schemas.openxmlformats.org/officeDocument/2006/math}t",
    "{http://schemas.openxmlformats.org/drawingml/2006/chart}v",
}
_DOCX_ALT_CHUNK_TAG = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}altChunk"
_DOCX_BLOCK_TAGS = {
    "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p",
    "{http://schemas.openxmlformats.org/drawingml/2006/main}p",
}
_ACCESSIBLE_ATTRIBUTE_NAMES = frozenset(
    {
        "alt",
        "aria-description",
        "aria-label",
        "data-content",
        "data-title",
        "data-tooltip",
        "descr",
        "description",
        "label",
        "placeholder",
        "title",
        "tooltip",
    }
)
_NON_VISIBLE_HTML_CONTAINERS = frozenset({"script", "style"})
# Ancla de revisión: sólo se actualiza cuando `contracts.py` cambia de forma deliberada y esa
# revisión queda registrada. 2026-08-20: la cadena durable pasó a validar `output_isolation` del
# candidato, y tras la revisión adversarial de Codex se le añadieron la matriz cerrada
# `CANDIDATE_DENIED_OPERATIONS`, la cardinalidad exacta de raíces y el rechazo de un OUTPUT_ROOT
# declarado bajo raíz escribible. El digest se refija sobre el archivo revisado en ese cierre.
_CATALOG_CONTRACTS_SHA256 = "1525b9ca295260fd91b2f0c5a5dd05086bc770b45688543c9790c70a88e47559"
_APPROVED_DOCUMENT_SECTION_SHA256 = {
    4: "74419bba83db8dedbf2325dc3d57c419afbcebc6f31312868eb4e426581018e9",
    6: "662a49bef5c75672218c9de196b01c3b6eb04b85e0a7602e1439910504cdb4e5",
}


class _VisibleHtmlParser(HTMLParser):
    """Reconstruye texto y atributos visibles aunque el copy esté partido por tags."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.fragments: list[str] = []
        self._hidden_stack: list[str] = []
        self._hidden_buffers: list[list[str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        normalized_tag = tag.casefold()
        if normalized_tag in _NON_VISIBLE_HTML_CONTAINERS:
            self._hidden_stack.append(normalized_tag)
            self._hidden_buffers.append([])
            return
        if self._hidden_stack:
            return
        normalized_attrs = {name.casefold(): value for name, value in attrs if value is not None}
        for name, value in attrs:
            normalized_name = name.casefold()
            if normalized_name in _ACCESSIBLE_ATTRIBUTE_NAMES and value:
                self.fragments.append(value)
            elif normalized_tag == "meta" and normalized_name == "content" and value:
                # Description/OpenGraph/Twitter y demás metadata HTML son copy público aunque
                # no aparezcan como text node en el body.
                self.fragments.append(value)
            elif (
                normalized_tag == "input"
                and normalized_name == "value"
                and normalized_attrs.get("type", "text").casefold() != "hidden"
                and value
            ):
                self.fragments.append(value)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.casefold() not in _NON_VISIBLE_HTML_CONTAINERS and not self._hidden_stack:
            self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        normalized_tag = tag.casefold()
        if self._hidden_stack and normalized_tag == self._hidden_stack[-1]:
            hidden_tag = self._hidden_stack.pop()
            source = "".join(self._hidden_buffers.pop())
            if self._hidden_stack:
                return
            if hidden_tag == "script":
                self.fragments.extend(
                    _javascript_visible_fragments(source, filename="script HTML inline")
                )
            elif hidden_tag == "style":
                self.fragments.extend(_css_visible_fragments(source, filename="style HTML inline"))

    def handle_data(self, data: str) -> None:
        if self._hidden_stack:
            self._hidden_buffers[-1].append(data)
            return
        self.fragments.append(data)

    def assert_complete(self, *, filename: str) -> None:
        if self._hidden_stack or self._hidden_buffers:
            raise ContractError(f"HTML público tiene contenedor inline incompleto: {filename}")


def _normalize_visible_text(value: str) -> str:
    """Colapsa whitespace y markup inline sin depender de su separación en tokens."""
    decoded = html.unescape(value).replace("\u00a0", " ")
    decoded = re.sub(r"<[^>]*>", " ", decoded)
    decoded = re.sub(r"[*_~`#>|\[\]()]", " ", decoded)
    return " ".join(decoded.split())


def _joined_string_value(node: ast.JoinedStr) -> str:
    fragments: list[str] = []
    for value in node.values:
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            fragments.append(value.value)
        elif isinstance(value, ast.FormattedValue) and isinstance(value.value, ast.Constant):
            constant = value.value.value
            fragments.append(str(constant) if isinstance(constant, str | int | float) else " ")
        else:
            fragments.append(" ")
    return "".join(fragments)


def _python_visible_blocks(source: str, *, filename: str) -> list[tuple[int, str]]:
    try:
        module = ast.parse(source, filename=filename)
    except SyntaxError as exc:
        raise ContractError(f"Python público no se pudo parsear: {filename}") from exc
    joined_children = {
        id(child)
        for joined in ast.walk(module)
        if isinstance(joined, ast.JoinedStr)
        for child in ast.walk(joined)
        if child is not joined
    }
    blocks: list[tuple[int, str]] = []
    for node in ast.walk(module):
        if isinstance(node, ast.JoinedStr):
            blocks.append((node.lineno, _joined_string_value(node)))
        elif (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in joined_children
        ):
            blocks.append((node.lineno, node.value))
    return blocks


def _without_c_style_comments(
    source: str,
    *,
    filename: str,
    allow_line_comments: bool,
) -> str:
    """Enmascara comentarios JS/TS/CSS sin borrar strings, templates ni saltos de línea."""
    if allow_line_comments:
        return _without_javascript_comments(source, filename=filename)
    output: list[str] = []
    index = 0
    quote: str | None = None
    block_comment = False
    line_comment = False
    while index < len(source):
        character = source[index]
        following = source[index + 1] if index + 1 < len(source) else ""
        if line_comment:
            if character in "\r\n":
                line_comment = False
                output.append(character)
            else:
                output.append(" ")
            index += 1
            continue
        if block_comment:
            if character == "*" and following == "/":
                output.extend((" ", " "))
                block_comment = False
                index += 2
            else:
                output.append(character if character in "\r\n" else " ")
                index += 1
            continue
        if quote is not None:
            output.append(character)
            if character == "\\":
                if not following:
                    raise ContractError(f"fuente pública termina en escape incompleto: {filename}")
                output.append(following)
                index += 2
                continue
            if character == quote:
                quote = None
            index += 1
            continue
        if character in {"'", '"', "`"}:
            quote = character
            output.append(character)
            index += 1
            continue
        if character == "\\" and following:
            output.extend((character, following))
            index += 2
            continue
        if allow_line_comments and character == "/" and following == "/":
            output.extend((" ", " "))
            line_comment = True
            index += 2
            continue
        if character == "/" and following == "*":
            output.extend((" ", " "))
            block_comment = True
            index += 2
            continue
        output.append(character)
        index += 1
    if block_comment or quote is not None:
        raise ContractError(f"fuente pública ambigua/incompleta: {filename}")
    return "".join(output)


def _without_javascript_comments(source: str, *, filename: str) -> str:
    """Lexer conservador: preserva strings/regex/templates y enmascara comentarios ejecutables."""
    output: list[str] = []
    index = 0
    mode = "normal"
    can_start_regex = True
    regex_character_class = False
    template_expression_depths: list[int] = []
    regex_prefix_keywords = {
        "await",
        "case",
        "delete",
        "in",
        "instanceof",
        "new",
        "of",
        "return",
        "throw",
        "typeof",
        "void",
        "yield",
    }
    while index < len(source):
        character = source[index]
        following = source[index + 1] if index + 1 < len(source) else ""
        if mode == "line_comment":
            if character in "\r\n":
                mode = "normal"
                output.append(character)
            else:
                output.append(" ")
            index += 1
            continue
        if mode == "block_comment":
            if character == "*" and following == "/":
                output.extend((" ", " "))
                mode = "normal"
                index += 2
            else:
                output.append(character if character in "\r\n" else " ")
                index += 1
            continue
        if mode in {"single", "double"}:
            output.append(character)
            if character == "\\":
                if not following:
                    raise ContractError(f"fuente pública termina en escape incompleto: {filename}")
                output.append(following)
                index += 2
                continue
            expected_quote = "'" if mode == "single" else '"'
            if character == expected_quote:
                mode = "normal"
                can_start_regex = False
            elif character in "\r\n":
                raise ContractError(f"string JS público queda incompleto: {filename}")
            index += 1
            continue
        if mode == "template":
            output.append(character)
            if character == "\\":
                if not following:
                    raise ContractError(
                        f"template JS público termina en escape incompleto: {filename}"
                    )
                output.append(following)
                index += 2
                continue
            if character == "`":
                mode = "normal"
                can_start_regex = False
                index += 1
                continue
            if character == "$" and following == "{":
                output.append(following)
                template_expression_depths.append(1)
                mode = "normal"
                can_start_regex = True
                index += 2
                continue
            index += 1
            continue
        if mode == "regex":
            output.append(character if character in "\r\n" else " ")
            if character == "\\":
                if not following:
                    raise ContractError(f"regex JS público termina en escape: {filename}")
                output.append(following if following in "\r\n" else " ")
                index += 2
                continue
            if character in "\r\n":
                raise ContractError(f"regex JS público queda incompleto: {filename}")
            if character == "[":
                regex_character_class = True
            elif character == "]":
                regex_character_class = False
            elif character == "/" and not regex_character_class:
                mode = "normal"
                can_start_regex = False
            index += 1
            continue

        if character.isspace():
            output.append(character)
            index += 1
            continue
        if character == "/" and following == "/":
            output.extend((" ", " "))
            mode = "line_comment"
            index += 2
            continue
        if character == "/" and following == "*":
            output.extend((" ", " "))
            mode = "block_comment"
            index += 2
            continue
        if character in {"'", '"'}:
            mode = "single" if character == "'" else "double"
            output.append(character)
            index += 1
            continue
        if character == "`":
            mode = "template"
            output.append(character)
            index += 1
            continue
        if character == "/":
            if index > 0 and source[index - 1] == "<" and (following.isalpha() or following == ">"):
                # Un closing tag JSX/TSX no abre una regex JavaScript.
                output.append(character)
                can_start_regex = True
                index += 1
                continue
            if can_start_regex:
                output.append(" ")
                mode = "regex"
                regex_character_class = False
            else:
                output.append(character)
                can_start_regex = True
            index += 1
            continue
        if character.isalpha() or character in {"_", "$"}:
            end = index + 1
            while end < len(source) and (source[end].isalnum() or source[end] in {"_", "$"}):
                end += 1
            word = source[index:end]
            output.append(word)
            can_start_regex = word in regex_prefix_keywords
            index = end
            continue
        if character.isdigit():
            end = index + 1
            while end < len(source) and (source[end].isalnum() or source[end] in {".", "_"}):
                end += 1
            output.append(source[index:end])
            can_start_regex = False
            index = end
            continue
        output.append(character)
        if character == "{" and template_expression_depths:
            template_expression_depths[-1] += 1
            can_start_regex = True
        elif character == "}" and template_expression_depths:
            template_expression_depths[-1] -= 1
            if template_expression_depths[-1] == 0:
                template_expression_depths.pop()
                mode = "template"
            can_start_regex = False
        elif character in ")]}.":
            can_start_regex = False
        else:
            can_start_regex = True
        index += 1
    if mode == "line_comment":
        mode = "normal"
    if mode != "normal" or template_expression_depths:
        raise ContractError(f"fuente JS pública ambigua/incompleta: {filename}")
    return "".join(output)


def _static_quoted_spans(source: str, *, allow_template: bool) -> list[tuple[int, int, str]]:
    spans: list[tuple[int, int, str]] = []
    index = 0
    quotes = {"'", '"'} | ({"`"} if allow_template else set())
    while index < len(source):
        if source[index] == "\\" and index + 1 < len(source):
            # Selectores CSS escapados pueden contener comillas que no abren un string.
            index += 2
            continue
        quote = source[index]
        if quote not in quotes:
            index += 1
            continue
        start = index
        index += 1
        content: list[str] = []
        closed = False
        while index < len(source):
            character = source[index]
            following = source[index + 1] if index + 1 < len(source) else ""
            if character == "\\":
                if not following:
                    break
                content.append(following)
                index += 2
                continue
            if quote == "`" and character == "$" and following == "{":
                expression_start = index + 2
                depth = 1
                index = expression_start
                expression_quote: str | None = None
                while index < len(source) and depth:
                    current = source[index]
                    if expression_quote is not None:
                        if current == "\\":
                            index += 2
                            continue
                        if current == expression_quote:
                            expression_quote = None
                    elif current in {"'", '"', "`"}:
                        expression_quote = current
                    elif current == "{":
                        depth += 1
                    elif current == "}":
                        depth -= 1
                    index += 1
                if depth:
                    raise ContractError("template JS público tiene expresión incompleta")
                expression = source[expression_start : index - 1].strip()
                if re.fullmatch(r"\d+(?:\.\d+)?", expression):
                    content.append(expression)
                elif (
                    len(expression) >= 2
                    and expression[0] == expression[-1]
                    and expression[0] in {"'", '"'}
                ):
                    content.append(expression[1:-1])
                else:
                    content.append(" ")
                continue
            if character == quote:
                index += 1
                closed = True
                break
            if character in "\r\n" and quote != "`":
                break
            content.append(character)
            index += 1
        if not closed:
            raise ContractError("literal público JS/CSS queda incompleto")
        spans.append((start, index, "".join(content)))
    return spans


def _javascript_visible_fragments(source: str, *, filename: str) -> list[str]:
    cleaned = _without_javascript_comments(source, filename=filename)
    spans = _static_quoted_spans(cleaned, allow_template=True)
    fragments = [text for _, _, text in spans]
    chain: list[str] = []
    previous_end: int | None = None
    for start, end, text in spans:
        if previous_end is not None and re.fullmatch(r"\s*\+\s*", cleaned[previous_end:start]):
            chain.append(text)
        else:
            if len(chain) > 1:
                fragments.append("".join(chain))
            chain = [text]
        previous_end = end
    if len(chain) > 1:
        fragments.append("".join(chain))

    jsx_texts: list[str] = []
    for raw_text in re.findall(r">([^<>]+)<", cleaned, flags=re.DOTALL):
        visible = re.sub(
            r"\{\s*(\d+(?:\.\d+)?|'[^']*'|\"[^\"]*\")\s*\}",
            lambda match: match.group(1).strip("'\""),
            raw_text,
        )
        visible = re.sub(r"\{[^{}]*\}", " ", visible)
        if visible.strip():
            jsx_texts.append(visible)
    fragments.extend(jsx_texts)
    if len(jsx_texts) > 1:
        fragments.append(" ".join(jsx_texts))
    return fragments


def _css_visible_fragments(source: str, *, filename: str) -> list[str]:
    cleaned = _without_c_style_comments(
        source,
        filename=filename,
        allow_line_comments=False,
    )
    spans = _static_quoted_spans(cleaned, allow_template=False)
    fragments = [text for _, _, text in spans]
    chain: list[str] = []
    previous_end: int | None = None
    for start, end, text in spans:
        if previous_end is not None and not cleaned[previous_end:start].strip():
            chain.append(text)
        else:
            if len(chain) > 1:
                fragments.append("".join(chain))
            chain = [text]
        previous_end = end
    if len(chain) > 1:
        fragments.append("".join(chain))
    return fragments


def _without_jinja_comments(source: str, *, filename: str) -> str:
    output: list[str] = []
    index = 0
    while index < len(source):
        candidates = [
            position for marker in ("{#", "{%") if (position := source.find(marker, index)) >= 0
        ]
        if not candidates:
            output.append(source[index:])
            break
        start = min(candidates)
        output.append(source[index:start])
        closing = "#}" if source.startswith("{#", start) else "%}"
        end = source.find(closing, start + 2)
        if end < 0:
            raise ContractError(f"template Jinja público tiene bloque incompleto: {filename}")
        hidden = source[start : end + 2]
        output.append("".join(character if character in "\r\n" else " " for character in hidden))
        index = end + 2
    return "".join(output)


def _toml_visible_strings(source: str, *, filename: str) -> list[tuple[int, str]]:
    try:
        parsed: object = tomllib.loads(source)
    except tomllib.TOMLDecodeError as exc:
        raise ContractError(f"TOML público no se pudo parsear: {filename}") from exc
    strings: list[str] = []

    def visit(value: object) -> None:
        if isinstance(value, str):
            strings.append(value)
        elif isinstance(value, dict):
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(parsed)
    return [(1, value) for value in strings]


def _without_yaml_comments(source: str) -> str:
    output: list[str] = []
    block_indent: int | None = None
    for raw_line in source.splitlines(keepends=True):
        body = raw_line.rstrip("\r\n")
        newline = raw_line[len(body) :]
        stripped = body.lstrip(" ")
        indentation = len(body) - len(stripped)
        if block_indent is not None:
            if not stripped or indentation >= block_indent:
                output.append(raw_line)
                continue
            block_indent = None
        quote: str | None = None
        escaped = False
        comment_at: int | None = None
        index = 0
        while index < len(body):
            character = body[index]
            if quote is not None:
                if quote == '"' and character == "\\" and not escaped:
                    escaped = True
                    index += 1
                    continue
                if character == quote and not escaped:
                    if quote == "'" and index + 1 < len(body) and body[index + 1] == "'":
                        index += 2
                        continue
                    quote = None
                escaped = False
                index += 1
                continue
            if character in {"'", '"'}:
                quote = character
            elif character == "#" and (index == 0 or body[index - 1].isspace()):
                comment_at = index
                break
            index += 1
        visible = body if comment_at is None else body[:comment_at]
        output.append(visible + newline)
        if re.search(
            r"(?:^|[\s:-])(?:![^\s]+\s+|&[^\s]+\s+)*[>|](?:[1-9][+-]?|[+-][1-9]?)?\s*$",
            visible,
        ):
            block_indent = indentation + 1
    return "".join(output)


def _without_rst_comments(source: str) -> str:
    output: list[str] = []
    comment_indent: int | None = None
    for raw_line in source.splitlines(keepends=True):
        body = raw_line.rstrip("\r\n")
        stripped = body.lstrip(" ")
        indentation = len(body) - len(stripped)
        if comment_indent is not None:
            if not stripped or indentation > comment_indent:
                output.append("\n" if raw_line.endswith("\n") else "")
                continue
            comment_indent = None
        directive = re.match(r"^\.\.\s+[A-Za-z][\w-]*::", stripped)
        substitution = re.match(r"^\.\.\s+\|[^|]+\|\s+[A-Za-z][\w-]*::", stripped)
        if re.match(r"^\.\.(?:\s|$)", stripped) and not (directive or substitution):
            comment_indent = indentation
            output.append("\n" if raw_line.endswith("\n") else "")
            continue
        output.append(raw_line)
    return "".join(output)


def _xml_visible_fragments(root: ElementTree.Element) -> list[str]:
    fragments: list[str] = []

    def visit(node: ElementTree.Element) -> None:
        local_name = node.tag.rsplit("}", 1)[-1].casefold()
        if local_name == "script":
            self_source = "".join(node.itertext())
            fragments.extend(
                _javascript_visible_fragments(self_source, filename="script XML/SVG inline")
            )
            if node.tail:
                fragments.append(node.tail)
            return
        if local_name == "style":
            self_source = "".join(node.itertext())
            fragments.extend(_css_visible_fragments(self_source, filename="style XML/SVG inline"))
            if node.tail:
                fragments.append(node.tail)
            return
        if node.text:
            fragments.append(node.text)
        for raw_name, value in node.attrib.items():
            name = raw_name.rsplit("}", 1)[-1].casefold()
            if name in _ACCESSIBLE_ATTRIBUTE_NAMES and value:
                fragments.append(value)
        for child in node:
            visit(child)
        if node.tail:
            fragments.append(node.tail)

    visit(root)
    return fragments


def _text_visible_blocks(text: str, *, suffix: str, filename: str) -> list[tuple[int, str]]:
    if suffix == ".py":
        return _python_visible_blocks(text, filename=filename)
    if suffix == ".toml":
        return _toml_visible_strings(text, filename=filename)
    if suffix == ".html":
        parser = _VisibleHtmlParser()
        try:
            parser.feed(text)
            parser.close()
            parser.assert_complete(filename=filename)
        except ContractError:
            raise
        except Exception as exc:
            raise ContractError(f"HTML público no se pudo parsear: {filename}") from exc
        return [(1, _normalize_visible_text(" ".join(parser.fragments)))]
    if suffix in {".svg", ".xml"}:
        try:
            root = ElementTree.fromstring(text)
        except ElementTree.ParseError as exc:
            raise ContractError(f"XML público no se pudo parsear: {filename}") from exc
        fragments = _xml_visible_fragments(root)
        return [(1, _normalize_visible_text(" ".join(fragments)))]
    if suffix in {".js", ".mjs", ".ts", ".tsx"}:
        return [
            (1, normalized)
            for fragment in _javascript_visible_fragments(text, filename=filename)
            if (normalized := _normalize_visible_text(fragment))
        ]
    elif suffix == ".css":
        return [
            (1, normalized)
            for fragment in _css_visible_fragments(text, filename=filename)
            if (normalized := _normalize_visible_text(fragment))
        ]
    elif suffix == ".j2":
        text = _without_jinja_comments(text, filename=filename)
        parser = _VisibleHtmlParser()
        try:
            parser.feed(text)
            parser.close()
            parser.assert_complete(filename=filename)
        except ContractError:
            raise
        except Exception as exc:
            raise ContractError(f"template Jinja público no se pudo parsear: {filename}") from exc
        return [(1, _normalize_visible_text(" ".join(parser.fragments)))]
    elif suffix in {".yaml", ".yml"}:
        text = _without_yaml_comments(text)
    elif suffix == ".rst":
        text = _without_rst_comments(text)
    blocks: list[tuple[int, str]] = []
    line_number = 1
    for paragraph in re.split(r"((?:\r?\n){2,})", text):
        if paragraph and not re.fullmatch(r"(?:\r?\n){2,}", paragraph):
            normalized = _normalize_visible_text(paragraph)
            if normalized:
                blocks.append((line_number, normalized))
        line_number += paragraph.count("\n")
    return blocks


def _docx_visible_blocks(root: ElementTree.Element) -> list[str]:
    def visible_fragment(node: ElementTree.Element) -> str:
        fragments = [node.text or ""] if node.tag in _DOCX_VISIBLE_TAGS else []
        fragments.extend(
            value
            for raw_name, value in node.attrib.items()
            if raw_name.rsplit("}", 1)[-1].casefold() in _ACCESSIBLE_ATTRIBUTE_NAMES
        )
        return "".join(fragments)

    blocks = [
        "".join(visible_fragment(node) for node in block.iter())
        for block in root.iter()
        if block.tag in _DOCX_BLOCK_TAGS
    ]
    if any(block.strip() for block in blocks):
        return blocks
    fallback = "".join(visible_fragment(node) for node in root.iter())
    return [fallback] if fallback else []


def _reject_reparse_ancestors(path: Path, *, context: str) -> Path:
    absolute = Path(os.path.abspath(path))
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current /= part
        try:
            info = current.lstat()
        except FileNotFoundError as exc:
            raise ContractError(f"{context}: ruta o ancestro ausente") from exc
        attributes = int(getattr(info, "st_file_attributes", 0))
        if current.is_symlink() or bool(attributes & _REPARSE_FLAG):
            raise ContractError(f"{context}: symlink o reparse point no permitido")
    return absolute


def _safe_public_directory(path: Path, *, context: str) -> Path:
    absolute = _reject_reparse_ancestors(path, context=context)
    info = absolute.lstat()
    if not stat.S_ISDIR(info.st_mode):
        raise ContractError(f"{context}: se esperaba directorio regular")
    return absolute


def _safe_public_file(path: Path, *, context: str) -> Path:
    absolute = _reject_reparse_ancestors(path, context=context)
    info = absolute.lstat()
    if not stat.S_ISREG(info.st_mode):
        raise ContractError(f"{context}: se esperaba archivo regular")
    if int(getattr(info, "st_nlink", 1)) != 1:
        raise ContractError(f"{context}: hardlink no permitido")
    return absolute


def _same_public_file_version(left: os.stat_result, right: os.stat_result) -> bool:
    return bool(
        os.path.samestat(left, right)
        and int(left.st_size) == int(right.st_size)
        and int(getattr(left, "st_mtime_ns", 0)) == int(getattr(right, "st_mtime_ns", 0))
    )


def _public_file_identity(path: Path, *, context: str) -> tuple[Path, os.stat_result]:
    candidate = _safe_public_file(path, context=context)
    return candidate, candidate.lstat()


def _assert_public_file_identity(
    path: Path,
    expected: os.stat_result,
    *,
    context: str,
) -> None:
    candidate, observed = _public_file_identity(path, context=context)
    del candidate
    if not _same_public_file_version(expected, observed):
        raise ContractError(f"{context}: el archivo público cambió de versión")


def _read_bound_public_bytes(path: Path, *, context: str) -> tuple[Path, bytes, os.stat_result]:
    candidate, before = _public_file_identity(path, context=context)
    with candidate.open("rb") as handle:
        opened = os.fstat(handle.fileno())
        if not _same_public_file_version(before, opened):
            raise ContractError(f"{context}: el archivo público cambió antes de leer")
        payload = handle.read()
        after_read = os.fstat(handle.fileno())
        if not _same_public_file_version(opened, after_read) or len(payload) != int(
            after_read.st_size
        ):
            raise ContractError(f"{context}: el archivo público cambió durante la lectura")
    _assert_public_file_identity(candidate, before, context=f"{context}: lectura final")
    return candidate, payload, before


def _public_tree_paths(root: Path) -> list[Path]:
    """Recorre sin follow y rechaza entradas dinámicas que puedan escapar del censo."""
    observed: list[Path] = []
    stack = [_safe_public_directory(root, context=f"superficie pública {root}")]
    while stack:
        directory = stack.pop()
        try:
            with os.scandir(directory) as iterator:
                entries = sorted(iterator, key=lambda item: item.name.casefold())
        except OSError as exc:
            raise ContractError(f"superficie pública no se pudo censar: {directory}") from exc
        for entry in entries:
            if entry.name in _IGNORED_PUBLIC_TREE_PARTS:
                continue
            entry_path = Path(entry.path)
            try:
                info = entry.stat(follow_symlinks=False)
            except OSError as exc:
                raise ContractError(f"entrada pública no se pudo censar: {entry_path}") from exc
            attributes = int(getattr(info, "st_file_attributes", 0))
            if entry.is_symlink() or bool(attributes & _REPARSE_FLAG):
                raise ContractError(f"entrada pública es symlink/reparse point: {entry_path}")
            if entry.is_dir(follow_symlinks=False):
                stack.append(entry_path)
            elif entry.is_file(follow_symlinks=False):
                if entry_path.suffix.lower() in (
                    TEXT_SUFFIXES | RENDERED_SUFFIXES | PUBLIC_ARCHIVE_SUFFIXES
                ):
                    observed.append(entry_path)
            else:
                raise ContractError(f"entrada pública no es regular: {entry_path}")
    return observed


def public_copy_paths(root: Path) -> list[Path]:
    """Censa en ambos sentidos todas las superficies públicas declaradas por AGENTS."""
    # Todo archivo de texto/render público nuevo en la raíz (por ejemplo INSTALL.md) entra sin
    # ampliar una allowlist. Sólo se excluyen las tres autoridades operativas internas conocidas.
    root = _safe_public_directory(root, context="raíz del censo de copy")
    paths: list[Path] = []
    with os.scandir(root) as entries:
        for entry in entries:
            if entry.name in INTERNAL_ROOT_FILES:
                continue
            path = Path(entry.path)
            if (
                path.suffix.lower()
                not in TEXT_SUFFIXES | RENDERED_SUFFIXES | PUBLIC_ARCHIVE_SUFFIXES
            ):
                continue
            paths.append(_safe_public_file(path, context=f"copy público {path}"))
    candidates = [root / item for item in PUBLIC_COPY_TREES]
    for candidate in candidates:
        try:
            info = candidate.lstat()
        except FileNotFoundError:
            continue
        if not stat.S_ISDIR(info.st_mode):
            raise ContractError(f"superficie pública no es directorio regular: {candidate}")
        paths.extend(_public_tree_paths(candidate))
    return sorted(set(paths), key=lambda path: str(path).casefold())


def _scannable_lines(path: Path) -> Iterable[tuple[int, str]]:
    """Entrega copy potencial; en Python excluye comentarios y sintaxis no visible."""
    path, payload, identity = _read_bound_public_bytes(
        path,
        context=f"archivo público {path}",
    )
    if path.suffix.lower() == ".zip":
        try:
            with zipfile.ZipFile(io.BytesIO(payload)) as archive:
                entries = archive.infolist()
                names = [entry.filename for entry in entries]
                if (
                    len(entries) > _MAX_PUBLIC_ARCHIVE_ENTRIES
                    or len(names) != len(set(names))
                    or len({name.casefold() for name in names}) != len(names)
                ):
                    raise zipfile.BadZipFile(
                        "ZIP público excede el censo o contiene nombres duplicados"
                    )
                total_bytes = 0
                archive_visible: list[str] = []
                for entry in entries:
                    member = PurePosixPath(entry.filename)
                    mode = (entry.external_attr >> 16) & 0o170000
                    unsafe_name = (
                        member.is_absolute()
                        or not member.parts
                        or any(part in {"", ".", ".."} for part in member.parts)
                        or any("\\" in part or ":" in part for part in member.parts)
                    )
                    if unsafe_name or entry.flag_bits & 0x1:
                        raise zipfile.BadZipFile("ZIP público contiene una entrada insegura")
                    if entry.is_dir():
                        if mode not in {0, stat.S_IFDIR}:
                            raise zipfile.BadZipFile("ZIP público contiene un directorio inseguro")
                        continue
                    if mode not in {0, stat.S_IFREG}:
                        raise zipfile.BadZipFile("ZIP público contiene una entrada no regular")
                    suffix = member.suffix.lower()
                    if suffix not in TEXT_SUFFIXES:
                        raise zipfile.BadZipFile(
                            f"ZIP público contiene una superficie no censable: {entry.filename}"
                        )
                    total_bytes += entry.file_size
                    ratio = entry.file_size / max(entry.compress_size, 1)
                    if (
                        entry.file_size > _MAX_PUBLIC_ARCHIVE_MEMBER_BYTES
                        or total_bytes > _MAX_PUBLIC_ARCHIVE_TOTAL_BYTES
                        or ratio > _MAX_PUBLIC_ARCHIVE_COMPRESSION_RATIO
                    ):
                        raise zipfile.BadZipFile("ZIP público excede límites seguros de lectura")
                    decoded = archive.read(entry).decode("utf-8")
                    archive_visible.extend(
                        text
                        for _, text in _text_visible_blocks(
                            decoded,
                            suffix=suffix,
                            filename=f"{path}!/{entry.filename}",
                        )
                    )
        except (OSError, UnicodeDecodeError, zipfile.BadZipFile) as exc:
            raise ContractError(f"ZIP público no se pudo censar: {path}") from exc
        if not any(line.strip() for line in archive_visible):
            raise ContractError(f"ZIP público no contiene texto censable: {path}")
        _assert_public_file_identity(path, identity, context="ZIP público final")
        yield from enumerate(archive_visible, start=1)
        return
    if path.suffix.lower() == ".docx":
        try:
            with zipfile.ZipFile(io.BytesIO(payload)) as archive:
                entries = archive.infolist()
                archive_names = [entry.filename for entry in entries]
                if (
                    len(entries) > _MAX_PUBLIC_ARCHIVE_ENTRIES
                    or len(archive_names) != len(set(archive_names))
                    or len({name.casefold() for name in archive_names}) != len(archive_names)
                ):
                    raise zipfile.BadZipFile("DOCX contiene nombres ZIP duplicados")
                entries_by_name: dict[str, zipfile.ZipInfo] = {}
                total_bytes = 0
                for entry in entries:
                    member = PurePosixPath(entry.filename)
                    mode = (entry.external_attr >> 16) & 0o170000
                    if (
                        member.is_absolute()
                        or not member.parts
                        or any(part in {"", ".", ".."} for part in member.parts)
                        or any("\\" in part or ":" in part for part in member.parts)
                        or entry.flag_bits & 0x1
                    ):
                        raise zipfile.BadZipFile("DOCX contiene una entrada insegura")
                    if entry.is_dir():
                        if mode not in {0, stat.S_IFDIR}:
                            raise zipfile.BadZipFile("DOCX contiene un directorio inseguro")
                        continue
                    if mode not in {0, stat.S_IFREG}:
                        raise zipfile.BadZipFile("DOCX contiene una entrada no regular")
                    total_bytes += entry.file_size
                    ratio = entry.file_size / max(entry.compress_size, 1)
                    if (
                        entry.file_size > _MAX_PUBLIC_ARCHIVE_MEMBER_BYTES
                        or total_bytes > _MAX_PUBLIC_ARCHIVE_TOTAL_BYTES
                        or ratio > _MAX_PUBLIC_ARCHIVE_COMPRESSION_RATIO
                    ):
                        raise zipfile.BadZipFile("DOCX excede límites seguros de lectura")
                    entries_by_name[entry.filename] = entry
                part_names = sorted(
                    name
                    for name in archive_names
                    if name.startswith("word/")
                    and name.lower().endswith(".xml")
                    and "/_rels/" not in name
                )
                if "word/document.xml" not in part_names:
                    raise KeyError("word/document.xml")
                visible: list[str] = []
                for part_name in part_names:
                    root = ElementTree.fromstring(archive.read(entries_by_name[part_name]))
                    if any(node.tag == _DOCX_ALT_CHUNK_TAG for node in root.iter()):
                        raise zipfile.BadZipFile("DOCX contiene altChunk no censable")
                    visible.extend(_docx_visible_blocks(root))
        except (
            ElementTree.ParseError,
            KeyError,
            OSError,
            UnicodeDecodeError,
            zipfile.BadZipFile,
        ) as exc:
            raise ContractError(f"DOCX público no se pudo censar: {path}") from exc
        if not any(text.strip() for text in visible):
            raise ContractError(f"DOCX público no contiene texto censable: {path}")
        _assert_public_file_identity(path, identity, context="DOCX público final")
        yield from enumerate(visible, start=1)
        return
    if path.suffix.lower() == ".pdf":
        try:
            from pypdf import PdfReader

            pages = PdfReader(io.BytesIO(payload)).pages
            extracted_pages = [page.extract_text() or "" for page in pages]
        except Exception as exc:
            raise ContractError(f"PDF público no se pudo censar: {path}") from exc
        if not extracted_pages or any(not page.strip() for page in extracted_pages):
            raise ContractError(
                f"PDF público contiene una página sin texto extraíble para censar: {path}"
            )
        _assert_public_file_identity(path, identity, context="PDF público final")
        yield from (
            (page_number, _normalize_visible_text(page))
            for page_number, page in enumerate(extracted_pages, start=1)
        )
        return
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ContractError(f"texto público no es UTF-8: {path}") from exc
    blocks = _text_visible_blocks(text, suffix=path.suffix.lower(), filename=str(path))
    _assert_public_file_identity(path, identity, context="texto público final")
    yield from blocks


def scan_capacity_claims(paths: Iterable[Path]) -> list[dict[str, object]]:
    """Devuelve cada paráfrasis prohibida con ruta y línea, sin conteos con holgura."""
    findings: list[dict[str, object]] = []
    selected = list(paths)
    initial = {
        path: _public_file_identity(path, context=f"copy público inicial {path}")[1]
        for path in selected
    }
    for path in selected:
        for line_number, line in _scannable_lines(path):
            matches = [match for pattern in CAPACITY_PATTERNS for match in pattern.finditer(line)]
            maximal = [
                match
                for match in matches
                if not any(
                    other is not match
                    and other.start() <= match.start()
                    and other.end() >= match.end()
                    and (other.start(), other.end()) != (match.start(), match.end())
                    for other in matches
                )
            ]
            for match in sorted(
                {(item.start(), item.end(), item.group(0)) for item in maximal},
                key=lambda item: (item[0], item[1], item[2]),
            ):
                findings.append(
                    {
                        "path": str(path),
                        "line": line_number,
                        "literal": match[2],
                    }
                )
    for path, identity in initial.items():
        _assert_public_file_identity(path, identity, context=f"copy público final {path}")
    return findings


def assert_no_h9r_capacity_copy(root: Path) -> int:
    """Falla ante cualquier claim y devuelve el censo exacto de archivos inspeccionados."""
    paths = public_copy_paths(root)
    identities = {
        path: _public_file_identity(path, context=f"copy público inicial {path}")[1]
        for path in paths
    }
    findings = scan_capacity_claims(paths)
    if findings:
        raise ContractError(f"target H9R publicado como capacidad: {findings!r}")
    final_paths = public_copy_paths(root)
    if final_paths != paths:
        raise ContractError(
            "el árbol de copy público cambió durante el gate; "
            f"faltan={sorted(set(paths) - set(final_paths))!r}; "
            f"extra={sorted(set(final_paths) - set(paths))!r}"
        )
    for path, identity in identities.items():
        _assert_public_file_identity(path, identity, context=f"copy público al cierre {path}")
    closing_paths = public_copy_paths(root)
    if closing_paths != paths:
        raise ContractError(
            "el árbol de copy público cambió al cerrar el gate; "
            f"faltan={sorted(set(paths) - set(closing_paths))!r}; "
            f"extra={sorted(set(closing_paths) - set(paths))!r}"
        )
    return len(paths)


def _assignment(module: ast.Module, name: str) -> ast.expr:
    matches = [
        node
        for node in module.body
        if isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and node.target.id == name
        and node.value is not None
    ]
    if len(matches) != 1:
        raise ContractError(f"catálogo de código exige un binding único: {name}")
    value = matches[0].value
    assert value is not None
    return value


def _root_name(node: ast.expr) -> str | None:
    while isinstance(node, ast.Attribute | ast.Subscript):
        node = node.value
    return node.id if isinstance(node, ast.Name) else None


def _assert_no_catalog_rebindings(module: ast.Module) -> None:
    assigned = {
        "MIB",
        "GIB",
        "CAPS",
        "GEOMETRY_IDS",
        "CLASSIFICATIONS",
        "FLOW_SPECS",
        "FLOW_BY_KEY",
        "ADAPTER_IDS",
    }
    protected = assigned | {"FlowSpec", "_g"}
    stores = {name: 0 for name in protected}
    mutating_methods = {
        "__delitem__",
        "__setitem__",
        "append",
        "clear",
        "extend",
        "insert",
        "pop",
        "popitem",
        "remove",
        "reverse",
        "setdefault",
        "sort",
        "update",
    }
    function_names = [
        node.name
        for node in module.body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    ]
    class_names = [node.name for node in module.body if isinstance(node, ast.ClassDef)]
    if function_names.count("_g") != 1 or class_names.count("FlowSpec") != 1:
        raise ContractError("FlowSpec/_g deben tener una única definición canónica")

    allowed_call_assignments = {"ATTEMPT_SIDECAR_NAMES", "FLOW_SPECS", "ADAPTER_IDS"}
    allowed_derived_assignments = {
        "PREFLIGHT_MIN_AVAILABLE_PHYSICAL_BYTES",
        "PREFLIGHT_MIN_COMMIT_HEADROOM_BYTES",
        "RUN_MIN_AVAILABLE_PHYSICAL_BYTES",
        "RUN_MIN_COMMIT_HEADROOM_BYTES",
        "RUN_MIN_DISK_FREE_BYTES",
        "PREFLIGHT_MIN_DISK_FREE_BYTES",
        "FLOW_BY_KEY",
        "ADAPTER_IDS",
    }
    for position, statement in enumerate(module.body):
        if isinstance(statement, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            continue
        if isinstance(statement, ast.Expr):
            if not (
                position == 0
                and isinstance(statement.value, ast.Constant)
                and isinstance(statement.value.value, str)
            ):
                raise ContractError("catálogo runtime ejecuta una expresión top-level no permitida")
            continue
        target_names = {
            node.id
            for node in ast.walk(statement)
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store)
        }
        loaded_protected = {
            node.id
            for node in ast.walk(statement)
            if isinstance(node, ast.Name)
            and isinstance(node.ctx, ast.Load)
            and node.id in protected
        }
        if loaded_protected and not target_names.intersection(
            protected | allowed_derived_assignments
        ):
            raise ContractError(
                "catálogo runtime crea un alias top-level de un valor protegido: "
                f"{sorted(loaded_protected)!r}"
            )
        if any(isinstance(node, ast.Call) for node in ast.walk(statement)) and not (
            target_names & allowed_call_assignments
        ):
            raise ContractError("catálogo runtime ejecuta una llamada top-level no permitida")
        for node in ast.walk(statement):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store | ast.Del):
                if node.id in stores:
                    stores[node.id] += 1
            elif isinstance(node, ast.Subscript | ast.Attribute) and isinstance(
                node.ctx, ast.Store | ast.Del
            ):
                root = _root_name(node.value)
                raise ContractError(f"catálogo runtime muta por acceso indirecto: {root!r}")
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in mutating_methods
            ):
                root = _root_name(node.func.value)
                if root in protected:
                    raise ContractError(f"catálogo runtime usa mutador top-level: {root}")
    if any(stores[name] != 1 for name in assigned) or stores["FlowSpec"] or stores["_g"]:
        raise ContractError(f"catálogo runtime tiene rebindings: {stores!r}")


def _integer_expression(node: ast.expr, *, constants: Mapping[str, int] | None = None) -> int:
    if isinstance(node, ast.Constant) and isinstance(node.value, int):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mult):
        return _integer_expression(node.left, constants=constants) * _integer_expression(
            node.right,
            constants=constants,
        )
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Pow):
        return int(
            _integer_expression(node.left, constants=constants)
            ** _integer_expression(
                node.right,
                constants=constants,
            )
        )
    if isinstance(node, ast.Name) and constants is not None and node.id in constants:
        return constants[node.id]
    raise ContractError("el catálogo CAPS dejó de ser una expresión entera estática")


def _static_value(node: ast.expr, *, constants: Mapping[str, int]) -> object:
    """Evalúa sólo el subconjunto literal usado por FLOW_SPECS, sin ejecutar Python."""
    if isinstance(node, ast.Constant):
        if isinstance(node.value, str | int | float):
            return node.value
        raise ContractError("FLOW_SPECS contiene una constante no permitida")
    if isinstance(node, ast.Name) and node.id in {"MIB", "GIB"}:
        return _integer_expression(node, constants=constants)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mult):
        return _integer_expression(node, constants=constants)
    if isinstance(node, ast.Tuple):
        return tuple(_static_value(item, constants=constants) for item in node.elts)
    if isinstance(node, ast.Dict):
        result: dict[str, object] = {}
        for key_node, value_node in zip(node.keys, node.values, strict=True):
            key = _static_value(key_node, constants=constants) if key_node is not None else None
            if not isinstance(key, str):
                raise ContractError("FLOW_SPECS contiene clave no literal")
            result[key] = _static_value(value_node, constants=constants)
        return result
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "_g":
        if node.args:
            raise ContractError("_g sólo puede usar dimensiones nombradas")
        dimensions: dict[str, object] = {}
        for keyword in node.keywords:
            if keyword.arg is None:
                raise ContractError("_g no permite ** expansiones")
            dimensions[keyword.arg] = _static_value(keyword.value, constants=constants)
        return dimensions
    raise ContractError(f"FLOW_SPECS contiene expresión no permitida: {type(node).__name__}")


def _literal_tuple(node: ast.expr, name: str) -> tuple[str, ...]:
    value: Any = ast.literal_eval(node)
    if not isinstance(value, tuple) or not all(isinstance(item, str) for item in value):
        raise ContractError(f"catálogo estático inválido: {name}")
    return tuple(value)


def _ast_dump(node: ast.AST) -> str:
    return ast.dump(node, annotate_fields=True, include_attributes=False)


def _canonical_expression(source: str) -> ast.expr:
    parsed = ast.parse(f"VALUE = {source}")
    assignment = parsed.body[0]
    assert isinstance(assignment, ast.Assign)
    return assignment.value


def _class_definition(module: ast.Module, name: str) -> ast.ClassDef:
    matches = [node for node in module.body if isinstance(node, ast.ClassDef) and node.name == name]
    if len(matches) != 1:
        raise ContractError(f"catálogo de código exige una clase {name} exacta")
    return matches[0]


def _function_definition(body: Sequence[ast.stmt], name: str) -> ast.FunctionDef:
    matches = [node for node in body if isinstance(node, ast.FunctionDef) and node.name == name]
    if len(matches) != 1:
        raise ContractError(f"catálogo de código exige una función {name} exacta")
    return matches[0]


def _body_without_docstring(function: ast.FunctionDef) -> list[ast.stmt]:
    body = list(function.body)
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        body.pop(0)
    return body


def _assert_catalog_runtime_helpers(module: ast.Module) -> dict[str, int]:
    _assert_no_catalog_rebindings(module)
    constants = {
        "MIB": _integer_expression(_assignment(module, "MIB")),
        "GIB": _integer_expression(_assignment(module, "GIB")),
    }
    if constants != {"MIB": 1024**2, "GIB": 1024**3}:
        raise ContractError("MIB/GIB dejaron de ser las unidades binarias contractuales")

    geometry_helper = _function_definition(module.body, "_g")
    if (
        geometry_helper.args.args
        or geometry_helper.args.posonlyargs
        or geometry_helper.args.kwonlyargs
        or geometry_helper.args.vararg is not None
        or geometry_helper.args.kwarg is None
        or geometry_helper.args.kwarg.arg != "dimensions"
        or [_ast_dump(node) for node in _body_without_docstring(geometry_helper)]
        != [_ast_dump(ast.Return(value=ast.Name(id="dimensions", ctx=ast.Load())))]
    ):
        raise ContractError("_g dejó de preservar exactamente las dimensiones nombradas")

    flow_class = _class_definition(module, "FlowSpec")
    expected_decorator = _canonical_expression("dataclass(frozen=True)")
    if [_ast_dump(item) for item in flow_class.decorator_list] != [_ast_dump(expected_decorator)]:
        raise ContractError("FlowSpec dejó de ser dataclass frozen exacta")
    field_names = [
        node.target.id
        for node in flow_class.body
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
    ]
    if field_names != [
        "wave",
        "flow_id",
        "step",
        "workload_deadline_seconds",
        "geometries",
        "outputs",
    ]:
        raise ContractError("FlowSpec dejó de conservar sus seis campos posicionales")
    key_property = _function_definition(flow_class.body, "key")
    output_property = _function_definition(flow_class.body, "expected_output_identities")
    for property_function in (key_property, output_property):
        if [_ast_dump(item) for item in property_function.decorator_list] != [
            _ast_dump(ast.Name(id="property", ctx=ast.Load()))
        ]:
            raise ContractError(f"{property_function.name} dejó de ser property exacta")
    expected_key = ast.parse("def f(self):\n return (self.flow_id, self.step)\n").body[0]
    expected_outputs = ast.parse(
        "def f(self):\n"
        " return tuple(identity for identity in self.outputs if identity != 'manifest')\n"
    ).body[0]
    assert isinstance(expected_key, ast.FunctionDef)
    assert isinstance(expected_outputs, ast.FunctionDef)
    if [_ast_dump(node) for node in _body_without_docstring(key_property)] != [
        _ast_dump(node) for node in expected_key.body
    ]:
        raise ContractError("FlowSpec.key dejó de derivar flow_id/step")
    if [_ast_dump(node) for node in _body_without_docstring(output_property)] != [
        _ast_dump(node) for node in expected_outputs.body
    ]:
        raise ContractError("FlowSpec.expected_output_identities dejó de excluir sólo manifest")

    adapter_ids = _assignment(module, "ADAPTER_IDS")
    expected_adapter_ids = _canonical_expression(
        "{spec.key: "
        "f\"nikodym.h9r.{spec.flow_id[2:].lower().replace('-', '_')}.{spec.step}.v1\" "
        "for spec in FLOW_SPECS}"
    )
    if _ast_dump(adapter_ids) != _ast_dump(expected_adapter_ids):
        raise ContractError("ADAPTER_IDS dejó de usar la derivación contractual")
    flow_by_key = _assignment(module, "FLOW_BY_KEY")
    expected_flow_by_key = _canonical_expression("{spec.key: spec for spec in FLOW_SPECS}")
    if _ast_dump(flow_by_key) != _ast_dump(expected_flow_by_key):
        raise ContractError("FLOW_BY_KEY dejó de usar la derivación contractual")
    return constants


def _code_catalog(contracts_path: Path) -> dict[str, object]:
    """Lee el catálogo por AST: este gate no ejecuta ni importa el módulo medido."""
    contracts_path, payload, identity = _read_bound_public_bytes(
        contracts_path,
        context="catálogo de código H9R",
    )
    try:
        source = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ContractError("catálogo de código H9R no es UTF-8") from exc
    module = ast.parse(source, filename=str(contracts_path))
    constants = _assert_catalog_runtime_helpers(module)
    caps_node = _assignment(module, "CAPS")
    if not isinstance(caps_node, ast.Dict):
        raise ContractError("CAPS dejó de ser un dict estático")
    caps: dict[str, int] = {}
    for key_node, value_node in zip(caps_node.keys, caps_node.values, strict=True):
        if not isinstance(key_node, ast.Constant) or not isinstance(key_node.value, str):
            raise ContractError("CAPS contiene una clave no literal")
        caps[key_node.value] = _integer_expression(value_node, constants=constants)

    flow_node = _assignment(module, "FLOW_SPECS")
    if not isinstance(flow_node, ast.Tuple):
        raise ContractError("FLOW_SPECS dejó de ser una tupla estática")
    flows: list[tuple[str, str, str]] = []
    protocols: list[dict[str, object]] = []
    for item in flow_node.elts:
        if (
            not isinstance(item, ast.Call)
            or not isinstance(item.func, ast.Name)
            or item.func.id != "FlowSpec"
            or len(item.args) != 6
            or item.keywords
        ):
            raise ContractError("FLOW_SPECS contiene una entrada no reconocible")
        values = tuple(ast.literal_eval(argument) for argument in item.args[:3])
        if not all(isinstance(value, str) for value in values):
            raise ContractError("FLOW_SPECS contiene una identidad no literal")
        wave, flow_id, flow_step = values
        deadline = _static_value(item.args[3], constants=constants)
        geometries = _static_value(item.args[4], constants=constants)
        outputs_raw = _static_value(item.args[5], constants=constants)
        if (
            not isinstance(deadline, int | float)
            or not isinstance(geometries, dict)
            or not isinstance(outputs_raw, tuple)
            or not all(isinstance(output, str) for output in outputs_raw)
        ):
            raise ContractError("FLOW_SPECS no conserva deadline/geometrías/outputs estáticos")
        flows.append((wave, flow_id, flow_step))
        protocols.append(
            {
                "adapter_id": (
                    f"nikodym.h9r.{flow_id[2:].lower().replace('-', '_')}.{flow_step}.v1"
                ),
                "deadline_seconds": float(deadline),
                "flow_id": flow_id,
                "flow_step": flow_step,
                "geometries": geometries,
                "outputs": [output for output in outputs_raw if output != "manifest"],
                "wave": wave,
            }
        )
    result: dict[str, object] = {
        "caps": caps,
        "geometries": _literal_tuple(_assignment(module, "GEOMETRY_IDS"), "GEOMETRY_IDS"),
        "classifications": _literal_tuple(
            _assignment(module, "CLASSIFICATIONS"), "CLASSIFICATIONS"
        ),
        "flows": tuple(flows),
        "protocols": protocols,
    }
    if hashlib.sha256(payload).hexdigest() != _CATALOG_CONTRACTS_SHA256:
        raise ContractError(
            "contracts.py cambió respecto del digest contractual revisado por el gate de catálogo"
        )
    _assert_public_file_identity(
        contracts_path,
        identity,
        context="catálogo de código H9R al cierre",
    )
    return result


def _document_catalog(proposal_path: Path) -> dict[str, object]:
    proposal_path, payload, identity = _read_bound_public_bytes(
        proposal_path,
        context="catálogo documental H9R",
    )
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ContractError("catálogo documental H9R no es UTF-8") from exc
    normalized_text = text.replace("\r\n", "\n")
    for section_number, expected_digest in _APPROVED_DOCUMENT_SECTION_SHA256.items():
        start = normalized_text.find(f"## {section_number}.")
        end = normalized_text.find(f"## {section_number + 1}.", start + 1)
        if start < 0 or end < 0:
            raise ContractError(f"sección aprobada {section_number} ausente en la propuesta")
        digest = hashlib.sha256(normalized_text[start:end].encode("utf-8")).hexdigest()
        if digest != expected_digest:
            raise ContractError(
                f"sección aprobada {section_number} cambió respecto del OK byte-exacto"
            )
    cap_rows = re.findall(
        r"^\| `(C[456])` \| \d+ GiB = ([\d.]+) B \|",
        text,
        flags=re.MULTILINE,
    )
    if len(cap_rows) != 3 or [row[0] for row in cap_rows] != ["C4", "C5", "C6"]:
        raise ContractError("tabla documental de caps no tiene filas C4/C5/C6 únicas y ordenadas")
    caps = {cap_id: int(bytes_text.replace(".", "")) for cap_id, bytes_text in cap_rows}
    flows = tuple(
        re.findall(
            r"^\| (W\d+) · `(F-[^`]+)` · `([^`]+)`(?: [^|]*)? \|",
            text,
            flags=re.MULTILINE,
        )
    )
    classification_match = re.search(
        r"Catálogo cerrado de `result\.classification`:\s*```text\s*(.*?)\s*```",
        text,
        flags=re.DOTALL,
    )
    if classification_match is None:
        raise ContractError("catálogo de terminaciones ausente en la propuesta")
    classifications = tuple(classification_match.group(1).splitlines())
    geometry_header = re.search(
        r"^\| Oleada · Flow ID · step \| (G\N{MINUS SIGN}) \| (G0) \| (G\+) \|",
        text,
        re.MULTILINE,
    )
    if geometry_header is None:
        raise ContractError("catálogo de geometrías ausente en la propuesta")
    protocol_match = re.search(
        r"```json h9r-flow-catalog-v1\s*(.*?)\s*```",
        text,
        flags=re.DOTALL,
    )
    if protocol_match is None:
        raise ContractError("espejo canónico de flujos ausente en la propuesta")
    raw_protocols = protocol_match.group(1)

    def reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
        value: dict[str, object] = {}
        for key, item in pairs:
            if key in value:
                raise ContractError(f"espejo canónico de flujos duplica la clave JSON: {key}")
            value[key] = item
        return value

    try:
        protocols: object = json.loads(raw_protocols, object_pairs_hook=reject_duplicate_keys)
    except json.JSONDecodeError as exc:
        raise ContractError("espejo canónico de flujos no es JSON válido") from exc
    if not isinstance(protocols, list) or not all(isinstance(item, dict) for item in protocols):
        raise ContractError("espejo canónico de flujos no es una lista de objetos")
    canonical_protocols = json.dumps(
        protocols,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    if raw_protocols != canonical_protocols:
        raise ContractError("espejo canónico de flujos no usa JSON canónico byte-exacto")
    result: dict[str, object] = {
        "caps": caps,
        "geometries": tuple(
            value.replace("G\N{MINUS SIGN}", "G-") for value in geometry_header.groups()
        ),
        "classifications": classifications,
        "flows": flows,
        "protocols": protocols,
    }
    _assert_public_file_identity(
        proposal_path,
        identity,
        context="catálogo documental H9R al cierre",
    )
    return result


def _reconcile_h9r_catalogs(
    observed: Mapping[str, object],
    documented: Mapping[str, object],
) -> dict[str, int]:
    for family in ("caps", "geometries", "classifications", "flows", "protocols"):
        if observed.get(family) != documented.get(family):
            raise ContractError(
                f"catálogo H9R no reconcilia en {family}: "
                f"observado={observed.get(family)!r}, documento={documented.get(family)!r}"
            )
    sizes: dict[str, int] = {}
    for output_name, family in (
        ("caps", "caps"),
        ("geometries", "geometries"),
        ("classifications", "classifications"),
        ("flow_steps", "flows"),
    ):
        value = observed[family]
        if not isinstance(value, (dict, tuple)):
            raise ContractError(f"catálogo H9R no es censable: {family}")
        sizes[output_name] = len(value)
    return sizes


def assert_documented_h9r_runtime_catalog(
    root: Path,
    *,
    caps: Mapping[str, int],
    geometry_ids: Sequence[str],
    classifications: Sequence[str],
    flow_specs: Sequence[Any],
    adapter_ids: Mapping[tuple[str, str], str],
) -> dict[str, int]:
    """Reconcilia el runtime ya importado por el bootstrap firmado con el documento aprobado."""
    expected_keys = [spec.key for spec in flow_specs]
    if len(expected_keys) != len(set(expected_keys)) or set(adapter_ids) != set(expected_keys):
        raise ContractError("runtime H9R no conserva un mapping adapter exacto por flow/step")
    runtime: dict[str, object] = {
        "caps": dict(caps),
        "geometries": tuple(geometry_ids),
        "classifications": tuple(classifications),
        "flows": tuple((spec.wave, spec.flow_id, spec.step) for spec in flow_specs),
        "protocols": [
            {
                "adapter_id": adapter_ids[spec.key],
                "deadline_seconds": float(spec.workload_deadline_seconds),
                "flow_id": spec.flow_id,
                "flow_step": spec.step,
                "geometries": spec.geometries,
                "outputs": list(spec.expected_output_identities),
                "wave": spec.wave,
            }
            for spec in flow_specs
        ],
    }
    proposal_path, proposal_identity = _public_file_identity(
        root / "docs/design/_PROPUESTA-CALIBRACION-H9R-PRE-START.md",
        context="catálogo documental H9R para runtime",
    )
    sizes = _reconcile_h9r_catalogs(runtime, _document_catalog(proposal_path))
    _assert_public_file_identity(
        proposal_path,
        proposal_identity,
        context="catálogo documental H9R tras reconciliar runtime",
    )
    return sizes


def assert_documented_h9r_catalog(root: Path) -> dict[str, int]:
    """Reconcilia caps, geometrías, flujos/steps y terminaciones sin importar contratos."""
    contracts_path, contracts_identity = _public_file_identity(
        root / "scripts/readiness_h9r/contracts.py",
        context="catálogo de código H9R inicial",
    )
    proposal_path, proposal_identity = _public_file_identity(
        root / "docs/design/_PROPUESTA-CALIBRACION-H9R-PRE-START.md",
        context="catálogo documental H9R inicial",
    )
    sizes = _reconcile_h9r_catalogs(
        _code_catalog(contracts_path),
        _document_catalog(proposal_path),
    )
    _assert_public_file_identity(
        contracts_path,
        contracts_identity,
        context="catálogo de código H9R al cierre conjunto",
    )
    _assert_public_file_identity(
        proposal_path,
        proposal_identity,
        context="catálogo documental H9R al cierre conjunto",
    )
    return sizes
