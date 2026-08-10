"""Valida por allowlist e identidad el contenido de wheel y sdist."""

from __future__ import annotations

import argparse
import base64
import binascii
import configparser
import csv
import email.parser
import fnmatch
import hashlib
import io
import json
import re
import stat
import tarfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from nikodym.ui import _static_index
from nikodym.ui._static_index import UiStaticIndexError, resolve_local_resources

_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_POLICY = _ROOT / "scripts" / "distribution_contents_allowlist.json"

# Rutas del módulo de semántica canónica dentro de cada artefacto (enmienda B2.2, E-B2.2-6).
_SEMANTICS_MODULE = {
    "wheel": "nikodym/ui/_static_index.py",
    "sdist": "src/nikodym/ui/_static_index.py",
}

_BUILD_MANIFEST = {
    "wheel": "nikodym/_build_manifest.json",
    "sdist": "src/nikodym/_build_manifest.json",
}


class DistributionContentError(ValueError):
    """El artefacto viola el contrato de distribución."""


@dataclass(frozen=True)
class ArchiveContent:
    """Entradas regulares normalizadas y metadatos de identidad."""

    kind: str
    files: dict[str, bytes]
    version: str
    dist_info: str | None = None


@dataclass(frozen=True)
class PolicySection:
    """Patrones permitidos y rutas obligatorias para un tipo de artefacto."""

    allowed: tuple[str, ...]
    required: tuple[str, ...]


@dataclass(frozen=True)
class DistributionPolicy:
    """Política de contenido validada antes de inspeccionar candidatos."""

    wheel: PolicySection
    sdist: PolicySection
    forbidden_parts: tuple[str, ...]
    forbidden_suffixes: tuple[str, ...]


def _safe_name(raw: str) -> str:
    if not raw or "\\" in raw or re.match(r"^[A-Za-z]:", raw):
        raise DistributionContentError(f"Ruta insegura en artefacto: {raw!r}")
    path = PurePosixPath(raw)
    canonical = path.as_posix()
    if raw == "." or path.is_absolute() or ".." in path.parts or not path.parts or canonical != raw:
        raise DistributionContentError(f"Ruta no canónica en artefacto: {raw!r}")
    return canonical


def _register_name(name: str, seen: set[str], folded: set[str]) -> None:
    if name in seen:
        raise DistributionContentError(f"Entrada duplicada en artefacto: {name}")
    casefolded = name.casefold()
    if casefolded in folded:
        raise DistributionContentError(f"Colisión case-insensitive en artefacto: {name}")
    seen.add(name)
    folded.add(casefolded)


def _metadata(data: bytes, label: str) -> email.message.Message:
    try:
        return email.parser.Parser().parsestr(data.decode("utf-8"))
    except (UnicodeDecodeError, LookupError) as error:
        raise DistributionContentError(f"Metadata inválida ({label})") from error


def _normalized_distribution(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).casefold()


def _single_header(metadata: email.message.Message, name: str, label: str) -> str:
    values = metadata.get_all(name, [])
    if len(values) != 1:
        raise DistributionContentError(
            f"{label} debe declarar exactamente un {name}: encontrados={len(values)}"
        )
    return values[0].strip()


def _validate_wheel_metadata(data: bytes) -> None:
    wheel = _metadata(data, "WHEEL")
    wheel_version = _single_header(wheel, "Wheel-Version", "WHEEL")
    purelib = _single_header(wheel, "Root-Is-Purelib", "WHEEL")
    tag = _single_header(wheel, "Tag", "WHEEL")
    if wheel_version != "1.0":
        raise DistributionContentError(f"Wheel-Version interno inválido: {wheel_version!r}")
    if purelib != "true":
        raise DistributionContentError(f"Root-Is-Purelib interno inválido: {purelib!r}")
    if tag != "py3-none-any":
        raise DistributionContentError(f"Tag interno de wheel inválido: {tag!r}")
    if wheel.get_all("Build"):
        raise DistributionContentError("Build interno prohibido en WHEEL")


def _validate_project_metadata(data: bytes, label: str, version: str) -> email.message.Message:
    project = _metadata(data, label)
    expected = {
        "Metadata-Version": "2.4",
        "Name": "nikodym",
        "Version": version,
        "License-Expression": "Apache-2.0",
        "License-File": "LICENSE",
    }
    for header, expected_value in expected.items():
        actual = _single_header(project, header, label)
        if actual != expected_value:
            raise DistributionContentError(
                f"{header} incoherente en {label}: {actual!r}/{expected_value!r}"
            )
    return project


def _validate_record(files: dict[str, bytes], record_name: str) -> None:
    raw_record = files[record_name]
    if not raw_record:
        raise DistributionContentError("RECORD no puede estar vacío")
    try:
        text = raw_record.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise DistributionContentError("RECORD no es UTF-8") from error
    rows: dict[str, tuple[str, str]] = {}
    seen: set[str] = set()
    folded: set[str] = set()
    try:
        reader = csv.reader(io.StringIO(text, newline=""))
        for position, row in enumerate(reader, start=1):
            if len(row) != 3:
                raise DistributionContentError(
                    f"RECORD fila {position} debe tener exactamente 3 columnas"
                )
            raw_path, hash_field, size_field = row
            path = _safe_name(raw_path)
            _register_name(path, seen, folded)
            rows[path] = (hash_field, size_field)
    except csv.Error as error:
        raise DistributionContentError("RECORD CSV inválido") from error
    if set(rows) != set(files):
        missing = sorted(set(files) - set(rows))
        extra = sorted(set(rows) - set(files))
        raise DistributionContentError(
            f"RECORD no coincide con ZIP: faltan={missing}, sobran={extra}"
        )
    for path, data in files.items():
        hash_field, size_field = rows[path]
        if path == record_name:
            if hash_field or size_field:
                raise DistributionContentError("RECORD debe autolistarse sin hash ni tamaño")
            continue
        if not hash_field.startswith("sha256="):
            raise DistributionContentError(f"Hash RECORD inválido para {path}")
        encoded = hash_field.removeprefix("sha256=")
        if "=" in encoded or re.fullmatch(r"[A-Za-z0-9_-]{43}", encoded) is None:
            raise DistributionContentError(f"Hash RECORD no canónico para {path}")
        try:
            expected_digest = base64.urlsafe_b64decode(f"{encoded}=")
        except (ValueError, binascii.Error) as error:
            raise DistributionContentError(f"Hash RECORD ilegible para {path}") from error
        if expected_digest != hashlib.sha256(data).digest():
            raise DistributionContentError(f"Hash RECORD no coincide para {path}")
        if size_field != str(len(data)):
            raise DistributionContentError(f"Tamaño RECORD no coincide para {path}")


def _validate_wheel_identity(files: dict[str, bytes], filename: str) -> tuple[str, str]:
    roots = {
        PurePosixPath(name).parts[0]
        for name in files
        if PurePosixPath(name).parts[0].casefold().endswith(".dist-info")
    }
    if len(roots) != 1:
        raise DistributionContentError(f"Wheel debe tener un único .dist-info: {sorted(roots)}")
    dist_info = next(iter(roots))
    match = re.fullmatch(r"nikodym-(?P<version>.+)\.dist-info", dist_info)
    if match is None:
        raise DistributionContentError(f"Identidad .dist-info inválida: {dist_info}")
    version = match.group("version")
    required = {
        f"{dist_info}/METADATA",
        f"{dist_info}/WHEEL",
        f"{dist_info}/RECORD",
        f"{dist_info}/licenses/LICENSE",
    }
    missing = sorted(required - files.keys())
    if missing:
        raise DistributionContentError(f"Metadata wheel obligatoria ausente: {missing}")
    _validate_project_metadata(files[f"{dist_info}/METADATA"], "METADATA", version)
    filename_match = re.fullmatch(r"nikodym-(?P<version>[^-]+)-py3-none-any\.whl", filename)
    if filename_match is None or filename_match.group("version") != version:
        raise DistributionContentError(
            f"Basename wheel incoherente con metadata: {filename!r}/{version!r}"
        )
    _validate_wheel_metadata(files[f"{dist_info}/WHEEL"])
    _validate_record(files, f"{dist_info}/RECORD")
    return version, dist_info


def read_archive(path: Path) -> ArchiveContent:
    """Abre ZIP/TAR sin extraer y rechaza colisiones y no-regulares."""
    seen: set[str] = set()
    folded: set[str] = set()
    if path.suffix == ".whl":
        files: dict[str, bytes] = {}
        with zipfile.ZipFile(path) as archive:
            for info in archive.infolist():
                if info.is_dir():
                    raise DistributionContentError(
                        f"Directorio explícito prohibido en wheel: {info.filename!r}"
                    )
                name = _safe_name(info.filename)
                _register_name(name, seen, folded)
                if info.flag_bits & 0x1:
                    raise DistributionContentError(f"Entrada cifrada prohibida en wheel: {name}")
                mode = info.external_attr >> 16
                file_type = stat.S_IFMT(mode)
                if file_type not in {0, stat.S_IFREG}:
                    raise DistributionContentError(f"Entrada no regular en wheel: {name}")
                files[name] = archive.read(info)
        version, dist_info = _validate_wheel_identity(files, path.name)
        return ArchiveContent("wheel", files, version, dist_info)
    if path.name.endswith(".tar.gz"):
        raw_files: dict[str, bytes] = {}
        roots: set[str] = set()
        with tarfile.open(path, "r:gz") as archive:
            for member in archive.getmembers():
                if member.isdir():
                    raise DistributionContentError(
                        f"Directorio explícito prohibido en sdist: {member.name!r}"
                    )
                name = _safe_name(member.name)
                _register_name(name, seen, folded)
                roots.add(PurePosixPath(name).parts[0])
                if not member.isfile():
                    raise DistributionContentError(f"Entrada no regular en sdist: {name}")
                extracted = archive.extractfile(member)
                if extracted is None:
                    raise DistributionContentError(f"No se pudo leer entrada sdist: {name}")
                raw_files[name] = extracted.read()
        if len(roots) != 1:
            raise DistributionContentError(f"El sdist debe tener una sola raíz: {sorted(roots)}")
        root = next(iter(roots))
        match = re.fullmatch(r"nikodym-(?P<version>.+)", root)
        if match is None:
            raise DistributionContentError(f"Identidad de raíz sdist inválida: {root}")
        version = match.group("version")
        if path.name != f"{root}.tar.gz":
            raise DistributionContentError(
                f"Basename sdist incoherente con raíz: {path.name!r}/{root!r}"
            )
        prefix = f"{root}/"
        files = {name.removeprefix(prefix): data for name, data in raw_files.items()}
        if "PKG-INFO" not in files:
            raise DistributionContentError("PKG-INFO obligatorio ausente en sdist")
        _validate_project_metadata(files["PKG-INFO"], "PKG-INFO", version)
        return ArchiveContent("sdist", files, version)
    raise DistributionContentError(f"Formato no soportado: {path}")


def _matches_segments(name: str, pattern: str) -> bool:
    name_parts = PurePosixPath(name).parts
    pattern_parts = PurePosixPath(pattern).parts

    def match(position: int, pattern_position: int) -> bool:
        if pattern_position == len(pattern_parts):
            return position == len(name_parts)
        token = pattern_parts[pattern_position]
        if token == "**":
            return match(position, pattern_position + 1) or (
                position < len(name_parts) and match(position + 1, pattern_position)
            )
        return (
            position < len(name_parts)
            and fnmatch.fnmatchcase(name_parts[position], token)
            and match(position + 1, pattern_position + 1)
        )

    return match(0, 0)


def _contains_forbidden(name: str, forbidden: str) -> bool:
    name_parts = tuple(part.casefold() for part in PurePosixPath(name).parts)
    forbidden_parts = tuple(part.casefold() for part in PurePosixPath(forbidden.strip("/")).parts)
    if not forbidden_parts:
        return False
    width = len(forbidden_parts)
    return any(
        name_parts[index : index + width] == forbidden_parts for index in range(len(name_parts))
    )


def _string_list(value: object, label: str, *, nonempty: bool = False) -> tuple[str, ...]:
    if not isinstance(value, list) or (nonempty and not value):
        raise DistributionContentError(f"Política inválida: {label} debe ser una lista")
    result: list[str] = []
    for position, item in enumerate(value):
        if not isinstance(item, str) or not item:
            raise DistributionContentError(
                f"Política inválida: {label}[{position}] debe ser string no vacío"
            )
        if "\\" in item or PurePosixPath(item).as_posix() != item:
            raise DistributionContentError(
                f"Política inválida: {label}[{position}] no es canónico: {item!r}"
            )
        result.append(item)
    if len(result) != len(set(result)):
        raise DistributionContentError(f"Política inválida: {label} contiene duplicados")
    return tuple(result)


#: Placeholder de la carpeta `.dist-info`, cuyo nombre depende de la versión: una ruta literal
#: quedaría obsoleta en cada bump. Se resuelve tarde, contra el candidate concreto.
_DIST_INFO_PLACEHOLDER = "{dist_info}"


def _resolve_required(required: str, dist_info: str | None) -> str:
    """Sustituye ``{dist_info}`` por la carpeta real del candidate (o por su patrón al validar)."""
    if _DIST_INFO_PLACEHOLDER not in required:
        return required
    return required.replace(_DIST_INFO_PLACEHOLDER, dist_info if dist_info else "*.dist-info")


def _policy_section(value: object, label: str) -> PolicySection:
    if not isinstance(value, dict) or set(value) != {"allowed", "required"}:
        raise DistributionContentError(
            f"Política inválida: {label} debe contener allowed y required"
        )
    allowed = _string_list(value["allowed"], f"{label}.allowed", nonempty=True)
    required = _string_list(value["required"], f"{label}.required", nonempty=True)
    for entry in required:
        # La cobertura se comprueba al CARGAR la política, cuando aún no se conoce el candidate: el
        # placeholder se normaliza a su patrón para que `required` siga siendo un subconjunto
        # verificable de `allowed` sin depender del artefacto.
        required_path = _resolve_required(entry, None)
        if not any(_matches_segments(required_path, pattern) for pattern in allowed):
            raise DistributionContentError(
                f"Política inválida: requerido fuera de allowlist en {label}: {required_path}"
            )
    return PolicySection(allowed=allowed, required=required)


def _load_policy(path: Path) -> DistributionPolicy:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise DistributionContentError(f"Política de distribución ilegible: {path}") from error
    expected = {
        "schema_version",
        "wheel",
        "sdist",
        "forbidden_parts",
        "forbidden_suffixes",
    }
    if not isinstance(raw, dict) or set(raw) != expected:
        raise DistributionContentError(
            "Política inválida: se exige objeto con schema_version/wheel/sdist/"
            "forbidden_parts/forbidden_suffixes"
        )
    schema_version = raw["schema_version"]
    if isinstance(schema_version, bool) or schema_version != 1:
        raise DistributionContentError("Política inválida: schema_version debe ser 1")
    return DistributionPolicy(
        wheel=_policy_section(raw["wheel"], "wheel"),
        sdist=_policy_section(raw["sdist"], "sdist"),
        forbidden_parts=_string_list(raw["forbidden_parts"], "forbidden_parts"),
        forbidden_suffixes=_string_list(raw["forbidden_suffixes"], "forbidden_suffixes"),
    )


#: Console script que debe declarar el wheel para que `nikodym-ui` exista tras `pip install`.
_CONSOLE_SCRIPT = ("nikodym-ui", "nikodym.ui.__main__:main")


def _validate_console_script(content: ArchiveContent) -> None:
    """Exige que ``entry_points.txt`` DECLARE el console script, no sólo que el archivo exista.

    Un ``entry_points.txt`` presente y vacío satisface la lista de entradas obligatorias y deja al
    usuario sin el comando: es exactamente el fallo que este gate debe cazar.
    """
    if content.kind != "wheel" or content.dist_info is None:
        return
    name = f"{content.dist_info}/entry_points.txt"
    raw = content.files.get(name)
    if raw is None:  # pragma: no cover - la lista `required` ya lo cubre
        raise DistributionContentError(f"Entrada obligatoria ausente: {name}")
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise DistributionContentError(f"{name} no es UTF-8") from error
    parser = configparser.ConfigParser()
    try:
        parser.read_string(text)
    except configparser.Error as error:
        raise DistributionContentError(f"{name} no es un INI válido") from error
    script, target = _CONSOLE_SCRIPT
    declarado = (
        parser["console_scripts"].get(script) if parser.has_section("console_scripts") else None
    )
    if declarado is None:
        raise DistributionContentError(f"{name} no declara el console script {script!r}")
    if declarado.strip() != target:
        raise DistributionContentError(
            f"{name} apunta {script!r} a {declarado.strip()!r} en vez de {target!r}"
        )


def _validate_semantics_anchor(content: ArchiveContent) -> None:
    """Ancla el candidate a la semántica canónica con la que se le audita.

    El checker importa **siempre** del árbol fuente sincronizado, nunca del candidate: instalar el
    wheel y auditarlo con su propio código sería el modo en que un artefacto mutado se aprueba a sí
    mismo. Para que esa importación sea legítima, el módulo distribuido debe ser byte a byte el que
    se está usando.

    El anclaje es el **sha256 del módulo**, no la versión del candidate: comparar
    ``__version__`` sería a la vez insuficiente —permanece fija durante decenas de commits, así que
    un módulo divergente pasaría— y redundante, porque bytes idénticos ya implican semántica
    idéntica sea cual sea la versión. La coherencia de versión entre wheel y sdist la cubre
    :func:`validate_candidate_set`.
    """
    module_name = _SEMANTICS_MODULE[content.kind]
    candidate = content.files.get(module_name)
    if candidate is None:
        raise DistributionContentError(f"Semántica canónica ausente del candidate: {module_name}")
    source = _static_index.__file__
    if source is None:  # pragma: no cover - sólo bajo un loader sin archivo
        raise DistributionContentError("No se pudo localizar nikodym.ui._static_index en disco")
    local = Path(source).read_bytes()
    if hashlib.sha256(candidate).hexdigest() != hashlib.sha256(local).hexdigest():
        raise DistributionContentError(
            f"Semántica canónica divergente: {module_name} del candidate no coincide con "
            "nikodym.ui._static_index; el gate aplicaría reglas distintas de las distribuidas"
        )


def _validate_build_manifest(content: ArchiveContent) -> None:
    """Ancla el lock de build del candidate contra los bytes fuente y ``uv.lock``."""
    name = _BUILD_MANIFEST[content.kind]
    candidate = content.files.get(name)
    if candidate is None:
        raise DistributionContentError(f"Manifiesto de build ausente del candidate: {name}")
    source_path = _ROOT / "src/nikodym/_build_manifest.json"
    source = source_path.read_bytes()
    if candidate != source:
        raise DistributionContentError(
            f"Manifiesto de build divergente: {name} no coincide con la fuente."
        )
    try:
        manifest = json.loads(source)
    except json.JSONDecodeError as error:  # pragma: no cover - gate fuente dedicado
        raise DistributionContentError("Manifiesto de build fuente inválido") from error
    observed = hashlib.sha256((_ROOT / "uv.lock").read_bytes()).hexdigest()
    if manifest.get("uv_lock_sha256") != observed:
        raise DistributionContentError(
            "Manifiesto de build no coincide con uv.lock: "
            f"declarado={manifest.get('uv_lock_sha256')!r}, observado={observed}."
        )


def validate_content(content: ArchiveContent, policy: DistributionPolicy) -> None:
    """Aplica allowlist, requeridos, anclaje de semántica y referencias locales del index."""
    section = policy.wheel if content.kind == "wheel" else policy.sdist

    for name in content.files:
        if any(_contains_forbidden(name, part) for part in policy.forbidden_parts):
            raise DistributionContentError(f"Ruta prohibida: {name}")
        if any(name.casefold().endswith(suffix.casefold()) for suffix in policy.forbidden_suffixes):
            raise DistributionContentError(f"Extensión prohibida: {name}")
        if not any(_matches_segments(name, pattern) for pattern in section.allowed):
            raise DistributionContentError(f"Ruta fuera de allowlist: {name}")
    required = {_resolve_required(entry, content.dist_info) for entry in section.required}
    missing = sorted(required - content.files.keys())
    if missing:
        raise DistributionContentError(f"Entradas obligatorias ausentes: {missing}")

    _validate_console_script(content)

    _validate_semantics_anchor(content)
    _validate_build_manifest(content)

    static_prefix = "nikodym/ui/static" if content.kind == "wheel" else "src/nikodym/ui/static"
    index_name = f"{static_prefix}/index.html"
    try:
        index_html = content.files[index_name].decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise DistributionContentError("index.html no es UTF-8") from error
    try:
        resolved = resolve_local_resources(index_html, static_prefix)
    except UiStaticIndexError as error:
        raise DistributionContentError(str(error)) from error
    for resource, local in resolved:
        if local not in content.files:
            raise DistributionContentError(
                f"Recurso local del index ausente: {resource!r} -> {local}"
            )


def _load_frontend_provenance(path: Path) -> dict[str, tuple[int, str]]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise DistributionContentError(f"Procedencia frontend ilegible: {path}") from error
    if not isinstance(raw, dict) or raw.get("schema_version") != 2:
        raise DistributionContentError("Procedencia frontend debe usar schema_version 2")
    outputs = raw.get("outputs")
    if not isinstance(outputs, list) or not outputs:
        raise DistributionContentError("Procedencia frontend sin outputs")
    result: dict[str, tuple[int, str]] = {}
    folded: set[str] = set()
    for position, output in enumerate(outputs):
        if not isinstance(output, dict):
            raise DistributionContentError(f"Output de procedencia inválido: posición {position}")
        raw_path = output.get("path")
        if not isinstance(raw_path, str):
            raise DistributionContentError(f"Path de procedencia inválido: posición {position}")
        output_path = _safe_name(raw_path)
        if output_path != raw_path:
            raise DistributionContentError(f"Path de procedencia no canónico: {raw_path!r}")
        if output_path in result:
            raise DistributionContentError(f"Output de procedencia duplicado: {output_path}")
        casefolded = output_path.casefold()
        if casefolded in folded:
            raise DistributionContentError(
                f"Colisión case-insensitive en procedencia: {output_path}"
            )
        size = output.get("size")
        sha256 = output.get("sha256")
        if (
            isinstance(size, bool)
            or not isinstance(size, int)
            or size < 0
            or not isinstance(sha256, str)
            or re.fullmatch(r"[0-9a-f]{64}", sha256) is None
        ):
            raise DistributionContentError(f"Integridad inválida en procedencia: {output_path}")
        result[output_path] = (size, sha256)
        folded.add(casefolded)
    return result


def _validate_frontend_candidate(
    content: ArchiveContent, provenance: dict[str, tuple[int, str]]
) -> None:
    static_prefix = "nikodym/ui/static/" if content.kind == "wheel" else "src/nikodym/ui/static/"
    static_files = {
        name.removeprefix(static_prefix): data
        for name, data in content.files.items()
        if name.startswith(static_prefix)
    }
    if set(static_files) != set(provenance):
        missing = sorted(set(provenance) - set(static_files))
        extra = sorted(set(static_files) - set(provenance))
        raise DistributionContentError(
            f"Static no coincide exactamente con procedencia: faltan={missing}, sobran={extra}"
        )
    for name, data in static_files.items():
        expected_size, expected_sha256 = provenance[name]
        actual_sha256 = hashlib.sha256(data).hexdigest()
        if len(data) != expected_size or actual_sha256 != expected_sha256:
            raise DistributionContentError(f"Static mutado respecto de procedencia: {name}")


def validate_distribution(
    path: Path,
    policy_path: Path = _DEFAULT_POLICY,
    frontend_provenance_path: Path | None = None,
) -> ArchiveContent:
    """Valida un wheel o sdist contra la política versionada."""
    if frontend_provenance_path is None:
        raise DistributionContentError("Falta --frontend-provenance")
    policy = _load_policy(policy_path)
    content = read_archive(path)
    validate_content(content, policy)
    _validate_frontend_candidate(content, _load_frontend_provenance(frontend_provenance_path))
    return content


def validate_candidate_set(
    artifacts: list[Path],
    policy_path: Path,
    frontend_provenance_path: Path,
    reference_wheel_path: Path | None = None,
) -> tuple[ArchiveContent, ArchiveContent]:
    """Exige exactamente un wheel y un sdist coherentes entre sí."""
    wheels = [path for path in artifacts if path.suffix == ".whl"]
    sdists = [path for path in artifacts if path.name.endswith(".tar.gz")]
    if len(artifacts) != 2 or len(wheels) != 1 or len(sdists) != 1:
        raise DistributionContentError(
            "Se exige exactamente 1 wheel y 1 sdist como unidad candidate"
        )
    wheel = validate_distribution(wheels[0], policy_path, frontend_provenance_path)
    sdist = validate_distribution(sdists[0], policy_path, frontend_provenance_path)
    if wheel.version != sdist.version:
        raise DistributionContentError(
            f"Versiones candidate incoherentes: wheel={wheel.version}, sdist={sdist.version}"
        )
    wheel_license = wheel.files[f"{wheel.dist_info}/licenses/LICENSE"]
    sdist_license = sdist.files["LICENSE"]
    try:
        repository_license = (_ROOT / "LICENSE").read_bytes()
    except OSError as error:
        raise DistributionContentError("LICENSE versionado no es legible") from error
    if wheel_license != sdist_license or wheel_license != repository_license:
        raise DistributionContentError("LICENSE difiere entre wheel, sdist o archivo versionado")
    wheel_metadata = wheel.files[f"{wheel.dist_info}/METADATA"]
    if wheel_metadata != sdist.files["PKG-INFO"]:
        raise DistributionContentError("METADATA del wheel difiere de PKG-INFO del sdist")
    if reference_wheel_path is not None:
        reference = validate_distribution(
            reference_wheel_path,
            policy_path,
            frontend_provenance_path,
        )
        if (
            reference.kind != "wheel"
            or reference.version != wheel.version
            or reference.dist_info != wheel.dist_info
            or reference.files.keys() != wheel.files.keys()
        ):
            raise DistributionContentError(
                "Wheel reconstruido desde sdist difiere en identidad o mapa de archivos"
            )
        changed = sorted(name for name in wheel.files if wheel.files[name] != reference.files[name])
        if changed:
            raise DistributionContentError(
                f"Wheel reconstruido desde sdist difiere byte a byte: {changed}"
            )
    return wheel, sdist


def main() -> None:
    """Ejecuta el checker sobre uno o más artefactos."""
    parser = argparse.ArgumentParser()
    parser.add_argument("artifacts", nargs="+", type=Path)
    parser.add_argument("--policy", type=Path, default=_DEFAULT_POLICY)
    parser.add_argument("--frontend-provenance", type=Path, required=True)
    parser.add_argument("--reference-wheel", type=Path)
    args = parser.parse_args()
    validate_candidate_set(
        args.artifacts,
        args.policy,
        args.frontend_provenance,
        args.reference_wheel,
    )
    for artifact in args.artifacts:
        print(f"Contenido verificado: {artifact}")


if __name__ == "__main__":
    main()
