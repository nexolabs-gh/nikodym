"""Audita de forma fail-closed las licencias del cierre runtime exportado por uv."""

from __future__ import annotations

import argparse
import email.parser
import hashlib
import json
import platform
import re
import sys
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from importlib import metadata
from importlib.metadata import PackageMetadata, PackagePath
from pathlib import Path
from typing import Any, Protocol

from packaging.licenses import InvalidLicenseExpression, canonicalize_license_expression
from packaging.markers import Marker, UndefinedComparison, UndefinedEnvironmentName
from packaging.requirements import InvalidRequirement, Requirement

_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_ALLOWLIST = _ROOT / "scripts" / "runtime_license_allowlist.json"
# Directorio (relativo a la allowlist) donde vive la core metadata upstream vendorizada que respalda
# cada declaración. Anclar el canal `declarations` a bytes hasheados es lo que impide que una
# transcripción infiel —por error o a propósito— cuele una licencia que la evidencia contradice.
_EVIDENCE_DIRNAME = "runtime_license_metadata"
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_COPYLEFT_RE = re.compile(
    r"\b(?:AGPL|LGPL|GPL)(?:[-_ ]?v?\d+(?:\.\d+)?)?"
    r"(?:[-_ ]?(?:only|or-later|\+))?\b|"
    r"\bGNU\s+(?:Affero\s+General|Lesser\s+General|"
    r"Library\s+or\s+Lesser\s+General|General)\s+Public\s+License\b",
    re.IGNORECASE,
)
_GENERIC_EVIDENCE = {
    "",
    "dual license",
    "unknown",
    "license",
    "osi approved",
    "license :: osi approved",
    "see license",
    "see license file",
}

# ── Matriz de entornos soportados ────────────────────────────────────────────────────────────────
# El wheel es `py3-none-any` y `pyproject.toml` declara `requires-python = ">=3.11"` con
# clasificadores 3.11/3.12/3.13; el job `test` de `.github/workflows/ci.yml` corre
# ubuntu, macos y windows por esas tres minor. Cualquiera de esos entornos es un
# `pip install nikodym[all]` soportado, así que su cierre transitivo debe auditarse **corra donde
# corra el gate**: evaluar los markers contra el intérprete del gate auditaba sólo un corte de la
# matriz y descartaba en silencio todo pin de otra plataforma o versión.
_SUPPORTED_PLATFORMS: tuple[tuple[str, str], ...] = (
    ("linux", "x86_64"),
    ("linux", "aarch64"),
    ("darwin", "arm64"),
    ("darwin", "x86_64"),
    ("win32", "AMD64"),
)
# Dos micro-versiones por minor: el piso real de la minor y un techo sintético. Un pin marcado
# `python_full_version < '3.12'` sólo entra con el piso y uno marcado `>= '3.11.4'` sólo con el
# techo; auditar ambos extremos deja el alcance sobre-inclusivo, que es la dirección segura.
_SUPPORTED_PYTHON: tuple[str, ...] = (
    "3.11.0",
    "3.11.99",
    "3.12.0",
    "3.12.99",
    "3.13.0",
    "3.13.99",
)
_PLATFORM_SYSTEM = {"linux": "Linux", "darwin": "Darwin", "win32": "Windows"}

_LICENSE_HEADERS = ("License-Expression", "License", "Classifier")
_DECLARATION_PREFIX = "declaration:"
_SOURCE_PREFERENCE = (
    "License-Expression",
    "License",
    "Classifier",
    "allowlist",
    f"{_DECLARATION_PREFIX}License-Expression",
    f"{_DECLARATION_PREFIX}License",
    f"{_DECLARATION_PREFIX}Classifier",
)

# Mapeos verificados contra la lista SPDX oficial (https://spdx.org/licenses/, license list 3.28.0)
# y contra la metadata publicada por cada distribución en PyPI. Un classifier sin versión mapea a la
# disyunción de las variantes OSI-aprobadas de esa familia, nunca a una versión adivinada.
_CLASSIFIER_TO_SPDX = {
    "License :: OSI Approved :: Apache Software License": "Apache-2.0",
    "License :: OSI Approved :: BSD License": "BSD-2-Clause OR BSD-3-Clause",
    "License :: OSI Approved :: MIT License": "MIT",
    "License :: OSI Approved :: Mozilla Public License 2.0 (MPL 2.0)": "MPL-2.0",
    "License :: OSI Approved :: Python Software Foundation License": "PSF-2.0",
    # El classifier no dice la versión de la ZPL; las variantes OSI-aprobadas son ZPL-2.0 y ZPL-2.1
    # (ZPL-1.1 existe en SPDX pero NO es OSI-aprobada, y el classifier afirma "OSI Approved").
    # Ambas son permisivas estilo BSD (retención de avisos + marca + aviso de cambios), sin cláusula
    # recíproca. `waitress` acota la versión con `License: ZPL 2.1`.
    "License :: OSI Approved :: Zope Public License": "ZPL-2.0 OR ZPL-2.1",
}
_LEGACY_TO_SPDX = {
    "3-Clause BSD License": "BSD-3-Clause",
    "Apache 2.0": "Apache-2.0",
    "Apache License 2.0": "Apache-2.0",
    "Apache License, Version 2.0": "Apache-2.0",
    "Apache Licence 2.0": "Apache-2.0",
    "BSD": "BSD-3-Clause",
    "BSD License": "BSD-3-Clause",
    "2-clause BSD": "BSD-2-Clause",
    "MIT License": "MIT",
    "MIT license": "MIT",
    # `pywin32` declara `License: PSF` junto al classifier "Python Software Foundation License";
    # SPDX 3.28.0 identifica esa licencia como PSF-2.0, el mismo destino del classifier.
    "PSF": "PSF-2.0",
    # `waitress` declara `License: ZPL 2.1` → SPDX ZPL-2.1 ("Zope Public License 2.1").
    "ZPL 2.1": "ZPL-2.1",
}


class RuntimeLicenseError(ValueError):
    """El cierre runtime no aporta evidencia de licencia aceptable."""


class DistributionLike(Protocol):
    """Superficie mínima de ``importlib.metadata.Distribution`` usada por el gate.

    Los miembros se declaran como propiedades de sólo lectura: ``Distribution`` los expone así y un
    atributo mutable en el Protocol no aceptaría la implementación real. Los nombres del módulo
    ``importlib.metadata`` se importan directos porque el atributo ``metadata`` los taparía dentro
    del cuerpo de la clase.
    """

    @property
    def metadata(self) -> PackageMetadata:
        """Metadata core (PEP 566) de la distribución instalada."""

    @property
    def version(self) -> str:
        """Versión instalada."""

    @property
    def files(self) -> list[PackagePath] | None:
        """Rutas declaradas por el RECORD de la distribución."""

    def locate_file(self, path: PackagePath | str) -> Any:
        """Resuelve una ruta declarada por la distribución.

        El retorno queda sin acotar porque ``Distribution.locate_file`` promete el protocolo
        ``SimplePath`` privado de typeshed; el único uso lo envuelve en ``Path`` de inmediato.
        """


@dataclass(frozen=True)
class AllowlistEntry:
    """Excepción exacta para metadata incompleta respaldada por un LICENSE hasheado."""

    name: str
    version: str
    license: str
    license_file: str
    sha256: str
    rationale: str


@dataclass(frozen=True)
class DeclarationEntry:
    """Core metadata upstream, hasheada y vendorizada, de un pin no instalable aquí.

    ``sources`` se deriva **de los bytes de la evidencia**, nunca de la transcripción legible: la
    transcripción sólo se exige como subconjunto verbatim para que la allowlist no pueda afirmar
    una licencia distinta de la que el archivo respalda.
    """

    name: str
    version: str
    source: str
    metadata_file: str
    metadata_sha256: str
    rationale: str
    sources: Mapping[str, str]


@dataclass(frozen=True)
class RuntimeAllowlist:
    """Excepciones hasheadas y declaraciones verificadas aplicables al cierre."""

    entries: Mapping[str, AllowlistEntry]
    declarations: Mapping[tuple[str, str], DeclarationEntry]


@dataclass(frozen=True)
class RuntimeRequirement:
    """Distribución y pin exacto del cierre, con los entornos soportados en que aplica.

    ``environments`` vacío significa que el marcador no se cumple en ningún entorno de la matriz.
    El pin se conserva igual —y falla— para que un descarte nunca sea silencioso.
    """

    name: str
    version: str
    marker: str
    environments: tuple[str, ...]
    installable: bool
    conditional: bool


@dataclass(frozen=True)
class LicenseClassification:
    """Expresión SPDX elegida y evidencia independiente por fuente."""

    expression: str
    sources: dict[str, str]


def _environment(sys_platform: str, machine: str, python_full_version: str) -> dict[str, str]:
    return {
        "implementation_name": "cpython",
        "implementation_version": python_full_version,
        "os_name": "nt" if sys_platform == "win32" else "posix",
        "platform_machine": machine,
        "platform_python_implementation": "CPython",
        # `platform_release`/`platform_version` no son ejes de la matriz soportada; se fijan vacíos
        # para no heredar los del host y volver el alcance dependiente de la máquina que audita.
        "platform_release": "",
        "platform_system": _PLATFORM_SYSTEM[sys_platform],
        "platform_version": "",
        "python_full_version": python_full_version,
        "python_version": ".".join(python_full_version.split(".")[:2]),
        "sys_platform": sys_platform,
    }


def supported_environments() -> tuple[tuple[str, dict[str, str]], ...]:
    """Entornos PEP 508 de la matriz soportada, con su etiqueta determinista."""
    return tuple(
        (
            f"{sys_platform}-{machine}-py{python_full_version}",
            _environment(sys_platform, machine, python_full_version),
        )
        for sys_platform, machine in _SUPPORTED_PLATFORMS
        for python_full_version in _SUPPORTED_PYTHON
    )


_SUPPORTED_ENVIRONMENTS = supported_environments()
_SUPPORTED_LABELS = tuple(label for label, _environment_variables in _SUPPORTED_ENVIRONMENTS)


def normalize_name(name: str) -> str:
    """Normaliza nombres de distribución según PEP 503."""
    return re.sub(r"[-_.]+", "-", name).casefold()


def _marker_scope(marker: Marker | None) -> tuple[str, ...]:
    if marker is None:
        return _SUPPORTED_LABELS
    scope: list[str] = []
    for label, environment in _SUPPORTED_ENVIRONMENTS:
        try:
            applies = marker.evaluate(environment)
        except (UndefinedComparison, UndefinedEnvironmentName) as error:
            raise RuntimeLicenseError(f"marcador no evaluable ({marker}): {error}") from error
        if applies:
            scope.append(label)
    return tuple(scope)


def _marker_installable_here(marker: Marker | None) -> bool:
    if marker is None:
        return True
    try:
        return bool(marker.evaluate())
    except (UndefinedComparison, UndefinedEnvironmentName) as error:
        raise RuntimeLicenseError(f"marcador no evaluable ({marker}): {error}") from error


def runtime_requirements(path: Path) -> tuple[RuntimeRequirement, ...]:
    """Extrae los pins exactos del export de uv activos en la matriz soportada."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as error:
        raise RuntimeLicenseError(f"Cierre runtime ilegible: {path}") from error
    requirements: dict[tuple[str, str], RuntimeRequirement] = {}
    errors: list[str] = []
    continuation = False
    saw_editable = False
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if continuation:
            hash_match = re.fullmatch(
                r"--hash=sha256:[0-9a-f]{64}(?P<continued>\s+\\)?",
                line,
            )
            if hash_match is None:
                errors.append(f"continuación inesperada: {line}")
                continuation = False
                continue
            continuation = hash_match.group("continued") is not None
            continue
        if line == "-e .":
            if saw_editable:
                errors.append("editable local duplicado: -e .")
            saw_editable = True
            continue
        if line.startswith("-"):
            errors.append(f"opción/editable inesperado: {line}")
            continue
        continued_requirement = line.endswith("\\")
        if continued_requirement:
            line = line[:-1].strip()
        try:
            requirement = Requirement(line)
        except InvalidRequirement:
            errors.append(line)
            continue
        continuation = continued_requirement
        try:
            environments = _marker_scope(requirement.marker)
            installable = _marker_installable_here(requirement.marker)
        except RuntimeLicenseError as error:
            errors.append(f"{line}: {error}")
            continue
        specifiers = list(requirement.specifier)
        if (
            requirement.url is not None
            or requirement.extras
            or len(specifiers) != 1
            or specifiers[0].operator != "=="
            or "*" in specifiers[0].version
        ):
            errors.append(line)
            continue
        name = normalize_name(requirement.name)
        version = specifiers[0].version
        if (name, version) in requirements:
            errors.append(f"{name}: pin duplicado {version}")
            continue
        requirements[name, version] = RuntimeRequirement(
            name=name,
            version=version,
            marker=str(requirement.marker) if requirement.marker is not None else "",
            environments=environments,
            installable=installable,
            conditional=requirement.marker is not None,
        )
    if continuation:
        errors.append("continuación hash incompleta al final del cierre")
    installed_here: dict[str, str] = {}
    for requirement_entry in requirements.values():
        if not requirement_entry.installable:
            continue
        previous = installed_here.setdefault(requirement_entry.name, requirement_entry.version)
        if previous != requirement_entry.version:
            errors.append(
                f"{requirement_entry.name}: pins incompatibles "
                f"{previous}/{requirement_entry.version}"
            )
    if errors:
        joined = "\n  - ".join(sorted(errors))
        raise RuntimeLicenseError(f"Dependencias runtime no parseables:\n  - {joined}")
    if not requirements:
        raise RuntimeLicenseError("El cierre runtime no contiene distribuciones")
    return tuple(requirements[key] for key in sorted(requirements))


def requirement_names(path: Path) -> tuple[str, ...]:
    """Compatibilidad legible: nombres del cierre conservando el parser de pins exactos."""
    return tuple(requirement.name for requirement in runtime_requirements(path))


def _strict_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RuntimeLicenseError(f"Allowlist runtime inválida: {label}")
    return value


def _load_hashed_entry(raw_entry: object, position: int) -> AllowlistEntry:
    expected = {"name", "version", "license", "license_file", "sha256", "rationale"}
    if not isinstance(raw_entry, dict) or set(raw_entry) != expected:
        raise RuntimeLicenseError(f"Entrada allowlist runtime inválida: posición {position}")
    entry = AllowlistEntry(
        name=_strict_string(raw_entry["name"], f"entries[{position}].name"),
        version=_strict_string(raw_entry["version"], f"entries[{position}].version"),
        license=_strict_string(raw_entry["license"], f"entries[{position}].license"),
        license_file=_strict_string(raw_entry["license_file"], f"entries[{position}].license_file"),
        sha256=_strict_string(raw_entry["sha256"], f"entries[{position}].sha256"),
        rationale=_strict_string(raw_entry["rationale"], f"entries[{position}].rationale"),
    )
    normalized = normalize_name(entry.name)
    if entry.name != normalized:
        raise RuntimeLicenseError(
            f"Nombre allowlist runtime no canónico: {entry.name!r}/{normalized!r}"
        )
    if (
        Path(entry.license_file).is_absolute()
        or "\\" in entry.license_file
        or ".." in Path(entry.license_file).parts
        or Path(entry.license_file).as_posix() != entry.license_file
    ):
        raise RuntimeLicenseError(f"Ruta LICENSE allowlist insegura: {entry.license_file!r}")
    if _SHA256_RE.fullmatch(entry.sha256) is None:
        raise RuntimeLicenseError(f"SHA-256 allowlist inválido: {entry.name}")
    try:
        canonical_license = canonicalize_license_expression(entry.license)
    except InvalidLicenseExpression as error:
        raise RuntimeLicenseError(f"Licencia allowlist no es SPDX: {entry.license!r}") from error
    if canonical_license != entry.license or "LicenseRef-" in canonical_license:
        raise RuntimeLicenseError(f"Licencia allowlist no canónica/clasificable: {entry.license!r}")
    if _COPYLEFT_RE.search(canonical_license):
        raise RuntimeLicenseError(f"Licencia copyleft prohibida en allowlist: {entry.name}")
    return entry


def _declared_headers(raw_metadata: object, position: int) -> dict[str, list[str]]:
    label = f"declarations[{position}].metadata"
    if not isinstance(raw_metadata, dict) or not raw_metadata:
        raise RuntimeLicenseError(f"Allowlist runtime inválida: {label}")
    unknown = sorted(set(raw_metadata) - set(_LICENSE_HEADERS))
    if unknown:
        raise RuntimeLicenseError(f"Cabecera declarada no auditable en {label}: {unknown}")
    headers: dict[str, list[str]] = {}
    for header in ("License-Expression", "License"):
        if header in raw_metadata:
            headers[header] = [_strict_string(raw_metadata[header], f"{label}.{header}")]
    if "Classifier" in raw_metadata:
        classifiers = raw_metadata["Classifier"]
        if not isinstance(classifiers, list) or not classifiers:
            raise RuntimeLicenseError(f"Allowlist runtime inválida: {label}.Classifier")
        values = [
            _strict_string(classifier, f"{label}.Classifier[{index}]")
            for index, classifier in enumerate(classifiers)
        ]
        if len(values) != len(set(values)):
            raise RuntimeLicenseError(f"Classifier declarado duplicado en {label}")
        headers["Classifier"] = values
    return headers


def _safe_relative_path(value: str, label: str) -> Path:
    path = Path(value)
    if (
        path.is_absolute()
        or "\\" in value
        or ".." in path.parts
        or path.as_posix() != value
        or not path.parts
    ):
        raise RuntimeLicenseError(f"Ruta insegura en {label}: {value!r}")
    return path


def _evidence_bytes(entry: Mapping[str, object], position: int, base_dir: Path) -> bytes:
    label = f"declarations[{position}]"
    metadata_file = _strict_string(entry["metadata_file"], f"{label}.metadata_file")
    metadata_sha256 = _strict_string(entry["metadata_sha256"], f"{label}.metadata_sha256")
    relative = _safe_relative_path(metadata_file, f"{label}.metadata_file")
    if relative.parts[0] != _EVIDENCE_DIRNAME:
        raise RuntimeLicenseError(
            f"Evidencia fuera de {_EVIDENCE_DIRNAME}/ en {label}: {metadata_file!r}"
        )
    if _SHA256_RE.fullmatch(metadata_sha256) is None:
        raise RuntimeLicenseError(f"SHA-256 de evidencia inválido en {label}")
    try:
        raw = (base_dir / relative).read_bytes()
    except OSError as error:
        raise RuntimeLicenseError(f"Evidencia declarada ilegible: {metadata_file}") from error
    actual = hashlib.sha256(raw).hexdigest()
    if actual != metadata_sha256:
        raise RuntimeLicenseError(
            f"Evidencia declarada no coincide con su hash: {metadata_file} "
            f"({actual}/{metadata_sha256})"
        )
    return raw


def _evidence_headers(raw: bytes, name: str, version: str) -> dict[str, list[str]]:
    """Cabeceras de licencia de la core metadata vendorizada, tras anclar su identidad."""
    message = email.parser.BytesParser().parsebytes(raw)
    identity = {
        header: [str(value).strip() for value in message.get_all(header, [])]
        for header in ("Metadata-Version", "Name", "Version")
    }
    for header, values in identity.items():
        if len(values) != 1:
            raise RuntimeLicenseError(
                f"Evidencia de {name}=={version} debe declarar exactamente un {header}"
            )
    if normalize_name(identity["Name"][0]) != name:
        raise RuntimeLicenseError(
            f"Evidencia de otra distribución: {identity['Name'][0]!r} declarada como {name!r}"
        )
    if identity["Version"][0] != version:
        raise RuntimeLicenseError(
            f"Evidencia de otra versión de {name}: {identity['Version'][0]!r}/{version!r}"
        )
    return {
        header: [str(value) for value in message.get_all(header, [])] for header in _LICENSE_HEADERS
    }


def _assert_faithful(
    declared: Mapping[str, list[str]], evidence: Mapping[str, list[str]], name: str, version: str
) -> None:
    """Toda cabecera transcrita debe aparecer verbatim en la evidencia."""
    for header, values in declared.items():
        observed = [str(value).strip() for value in evidence.get(header, [])]
        for value in values:
            if value.strip() not in observed:
                raise RuntimeLicenseError(
                    f"Transcripción infiel en {name}=={version}: {header}={value!r} no aparece en "
                    f"la evidencia {observed[:3]!r}"
                )


def _load_declaration(raw_entry: object, position: int, base_dir: Path) -> DeclarationEntry:
    expected = {
        "name",
        "version",
        "metadata",
        "source",
        "metadata_file",
        "metadata_sha256",
        "rationale",
    }
    if not isinstance(raw_entry, dict) or set(raw_entry) != expected:
        raise RuntimeLicenseError(f"Declaración allowlist runtime inválida: posición {position}")
    name = _strict_string(raw_entry["name"], f"declarations[{position}].name")
    version = _strict_string(raw_entry["version"], f"declarations[{position}].version")
    source = _strict_string(raw_entry["source"], f"declarations[{position}].source")
    rationale = _strict_string(raw_entry["rationale"], f"declarations[{position}].rationale")
    normalized = normalize_name(name)
    if name != normalized:
        raise RuntimeLicenseError(f"Nombre declarado no canónico: {name!r}/{normalized!r}")
    # La fuente tiene que ser citable: la metadata oficial publicada por la distribución. El digest
    # ancla la copia local a esa URL, y los archivos de PyPI son inmutables, así que no caduca.
    if not source.startswith("https://"):
        raise RuntimeLicenseError(f"Fuente declarada no verificable para {name}: {source!r}")
    raw = _evidence_bytes(raw_entry, position, base_dir)
    evidence = _evidence_headers(raw, name, version)
    _assert_faithful(_declared_headers(raw_entry["metadata"], position), evidence, name, version)
    # La autoridad son los bytes de la evidencia, no la transcripción legible.
    classification = _classify_headers(evidence)
    if classification is None:
        raise RuntimeLicenseError(f"Declaración sin evidencia de licencia: {name}")
    return DeclarationEntry(
        name=name,
        version=version,
        source=source,
        metadata_file=_strict_string(
            raw_entry["metadata_file"], f"declarations[{position}].metadata_file"
        ),
        metadata_sha256=_strict_string(
            raw_entry["metadata_sha256"], f"declarations[{position}].metadata_sha256"
        ),
        rationale=rationale,
        sources=classification.sources,
    )


def load_allowlist(path: Path) -> RuntimeAllowlist:
    """Carga la allowlist exacta y rechaza cualquier estructura ambigua."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeLicenseError(f"Allowlist runtime ilegible: {path}") from error
    if not isinstance(raw, dict) or set(raw) != {"schema_version", "entries", "declarations"}:
        raise RuntimeLicenseError(
            "Allowlist runtime debe ser un objeto schema_version/entries/declarations"
        )
    if isinstance(raw["schema_version"], bool) or raw["schema_version"] != 2:
        raise RuntimeLicenseError("Allowlist runtime debe usar schema_version 2")
    raw_entries = raw["entries"]
    raw_declarations = raw["declarations"]
    if not isinstance(raw_entries, list) or not isinstance(raw_declarations, list):
        raise RuntimeLicenseError("Allowlist runtime entries/declarations deben ser listas")
    entries: dict[str, AllowlistEntry] = {}
    for position, raw_entry in enumerate(raw_entries):
        entry = _load_hashed_entry(raw_entry, position)
        normalized = normalize_name(entry.name)
        if normalized in entries:
            raise RuntimeLicenseError(f"Distribución allowlist duplicada: {entry.name}")
        entries[normalized] = entry
    declarations: dict[tuple[str, str], DeclarationEntry] = {}
    for position, raw_declaration in enumerate(raw_declarations):
        declaration = _load_declaration(raw_declaration, position, path.parent)
        key = (declaration.name, declaration.version)
        if key in declarations:
            raise RuntimeLicenseError(
                f"Declaración duplicada: {declaration.name}=={declaration.version}"
            )
        declarations[key] = declaration
    return RuntimeAllowlist(entries=entries, declarations=declarations)


def _canonical_spdx(value: str, source: str) -> str:
    try:
        expression = canonicalize_license_expression(value)
    except InvalidLicenseExpression as error:
        mapped = _LEGACY_TO_SPDX.get(value) if source == "License" else None
        if mapped is None:
            raise RuntimeLicenseError(f"{source} no es SPDX clasificable: {value!r}") from error
        expression = canonicalize_license_expression(mapped)
    if "LicenseRef-" in expression:
        raise RuntimeLicenseError(f"{source} usa LicenseRef no verificable: {expression!r}")
    return expression


def _license_ids(expression: str) -> frozenset[str]:
    return frozenset(
        token
        for token in re.findall(r"[A-Za-z0-9][A-Za-z0-9.+-]*", expression)
        if token not in {"AND", "OR", "WITH"}
    )


def _headers_from_metadata(package_metadata: metadata.PackageMetadata) -> dict[str, list[str]]:
    return {
        header: [str(value) for value in package_metadata.get_all(header, [])]
        for header in _LICENSE_HEADERS
    }


def _classify_headers(headers: Mapping[str, Sequence[str]]) -> LicenseClassification | None:
    sources: dict[str, str] = {}
    singletons: dict[str, str] = {}
    for header in ("License-Expression", "License"):
        values = list(headers.get(header, ()))
        if len(values) > 1:
            raise RuntimeLicenseError(f"Metadata duplica {header}")
        singletons[header] = values[0].strip() if values else ""
    license_expression = singletons["License-Expression"]
    if license_expression:
        sources["License-Expression"] = _canonical_spdx(license_expression, "License-Expression")

    classifiers = [
        classifier.strip()
        for classifier in headers.get("Classifier", ())
        if classifier.startswith("License ::")
        and classifier.strip().casefold() not in _GENERIC_EVIDENCE
    ]
    if len(classifiers) != len(set(classifiers)):
        raise RuntimeLicenseError("Metadata duplica classifiers de licencia")
    if classifiers:
        mapped: list[str] = []
        for classifier in classifiers:
            expression = _CLASSIFIER_TO_SPDX.get(classifier)
            if expression is None:
                raise RuntimeLicenseError(f"Classifier de licencia no clasificado: {classifier!r}")
            mapped.append(expression)
        sources["Classifier"] = canonicalize_license_expression(" OR ".join(sorted(set(mapped))))

    legacy_license = singletons["License"]
    if (
        legacy_license
        and legacy_license.casefold() not in _GENERIC_EVIDENCE
        and legacy_license.casefold() != "unknown"
        and len(legacy_license) < 500
    ):
        sources["License"] = _canonical_spdx(legacy_license, "License")

    if not sources:
        return None
    return _combine_sources(sources)


def _combine_sources(sources: Mapping[str, str]) -> LicenseClassification:
    for source, expression in sources.items():
        if _COPYLEFT_RE.search(expression):
            raise RuntimeLicenseError(f"{source} declara licencia GPL/LGPL/AGPL: {expression!r}")
    source_ids = {source: _license_ids(expression) for source, expression in sources.items()}
    common_ids = set.intersection(*(set(ids) for ids in source_ids.values()))
    if not common_ids:
        raise RuntimeLicenseError(f"Fuentes de licencia contradictorias: {dict(sources)!r}")
    preferred = next(sources[source] for source in _SOURCE_PREFERENCE if source in sources)
    return LicenseClassification(expression=preferred, sources=dict(sources))


def _validate_allowlisted(
    distribution: DistributionLike, entry: AllowlistEntry
) -> tuple[bool, str | None]:
    if distribution.version != entry.version:
        return False, (
            f"{entry.name}: versión {distribution.version!r} no coincide con allowlist "
            f"{entry.version!r}"
        )
    license_marker = ".dist-info/licenses/"
    if license_marker not in entry.license_file:
        return False, f"{entry.name}: ruta LICENSE allowlisted no sigue dist-info/licenses"
    expected_license_header = entry.license_file.split(license_marker, maxsplit=1)[1]
    license_headers = distribution.metadata.get_all("License-File", [])
    if license_headers != [expected_license_header]:
        return False, (
            f"{entry.name}: License-File debe ser singleton exacto "
            f"{expected_license_header!r}, observado={license_headers!r}"
        )
    declared_paths = {str(path) for path in distribution.files or []}
    if entry.license_file not in declared_paths:
        return False, f"{entry.name}: LICENSE allowlisted no está declarado en RECORD"
    license_path = Path(distribution.locate_file(entry.license_file))
    try:
        bytes_ = license_path.read_bytes()
    except OSError as error:
        return False, f"{entry.name}: LICENSE allowlisted ilegible: {error}"
    actual = hashlib.sha256(bytes_).hexdigest()
    if actual != entry.sha256:
        return False, (f"{entry.name}: hash LICENSE allowlisted cambió: {actual}/{entry.sha256}")
    return True, None


def _audit_environment_label() -> str:
    return f"{sys.platform}-{platform.machine()}-py{platform.python_version()}"


def audit_runtime_licenses(
    requirements_path: Path,
    report_path: Path,
    *,
    allowlist_path: Path = _DEFAULT_ALLOWLIST,
    distribution_getter: Callable[[str], DistributionLike] = metadata.distribution,
) -> dict[str, object]:
    """Audita el cierre, escribe un reporte determinista y falla ante toda ambigüedad."""
    failures: list[str] = []
    try:
        requirements_bytes = requirements_path.read_bytes()
    except OSError as error:
        requirements_bytes = b""
        failures.append(f"Cierre runtime ilegible: {requirements_path}: {error}")
    try:
        allowlist_bytes = allowlist_path.read_bytes()
    except OSError as error:
        allowlist_bytes = b""
        failures.append(f"Allowlist runtime ilegible: {allowlist_path}: {error}")
    requirements: tuple[RuntimeRequirement, ...] = ()
    allowlist = RuntimeAllowlist(entries={}, declarations={})
    if not failures:
        try:
            requirements = runtime_requirements(requirements_path)
        except RuntimeLicenseError as error:
            failures.append(str(error))
        try:
            allowlist = load_allowlist(allowlist_path)
        except RuntimeLicenseError as error:
            failures.append(str(error))
    requirements_sha256 = hashlib.sha256(requirements_bytes).hexdigest()
    packages: list[dict[str, object]] = []
    used_entries: set[str] = set()
    used_declarations: set[tuple[str, str]] = set()

    for requirement in requirements:
        name = requirement.name
        pin = f"{name}=={requirement.version}"
        declaration = allowlist.declarations.get((name, requirement.version))
        declared_sources: dict[str, str] = {}
        status = "ok"
        classification: LicenseClassification | None = None
        installed_version: str | None = None

        if declaration is not None:
            used_declarations.add((name, requirement.version))
            if not requirement.conditional:
                status = "fail_declaration"
                failures.append(
                    f"{pin}: declaración innecesaria; el pin aplica sin marcador en toda la matriz "
                    "y debe auditarse con la metadata instalada"
                )
            else:
                declared_sources = {
                    f"{_DECLARATION_PREFIX}{header}": expression
                    for header, expression in declaration.sources.items()
                }

        if status == "ok" and not requirement.environments:
            # Un pin cuyo marcador no se cumple en ningún entorno soportado no se descarta: o la
            # matriz está incompleta (falta un eje real) o el cierre trae una rama que nadie usa.
            # Las dos cosas las decide un humano; el silencio por omisión es justo lo que este gate
            # vino a erradicar.
            status = "fail_out_of_matrix"
            failures.append(
                f"{pin}: marcador {requirement.marker!r} no se cumple en ninguno de los "
                f"{len(_SUPPORTED_LABELS)} entornos soportados; amplía la matriz o retira la rama "
                "del cierre"
            )
        elif status == "ok" and not requirement.installable:
            if declaration is None:
                status = "fail_undeclared"
                failures.append(
                    f"{pin}: aplica en {len(requirement.environments)} entorno(s) soportado(s) "
                    "pero no es instalable en el entorno de auditoría y no tiene declaración "
                    "verificada en la allowlist"
                )
            else:
                try:
                    classification = _combine_sources(declared_sources)
                    status = "ok_declared"
                except RuntimeLicenseError as error:
                    status = "fail_license"
                    failures.append(f"{pin}: {error}")
        elif status == "ok":
            distribution: DistributionLike | None = None
            try:
                distribution = distribution_getter(name)
            except metadata.PackageNotFoundError:
                status = "fail_missing_distribution"
                failures.append(f"{name}: distribución no instalada")
            if distribution is not None:
                installed_version = distribution.version
                status, classification = _audit_installed(
                    requirement,
                    distribution,
                    declared_sources,
                    allowlist,
                    failures,
                    used_entries,
                )

        packages.append(
            {
                "name": name,
                "expected_version": requirement.version,
                "version": installed_version,
                "environments": len(requirement.environments),
                "installable": requirement.installable,
                # Ancla publicada de la declaración: con estas dos columnas cualquiera re-verifica
                # el reporte contra PyPI sin acceso al repo (`curl <source> | shasum -a 256`).
                "declaration_source": declaration.source if declaration is not None else None,
                "declaration_sha256": (
                    declaration.metadata_sha256 if declaration is not None else None
                ),
                "license_expression": (
                    classification.expression if classification is not None else None
                ),
                "license_sources": (classification.sources if classification is not None else {}),
                "status": status,
            }
        )

    for unused in sorted(set(allowlist.entries) - used_entries):
        failures.append(f"{unused}: entrada allowlist no utilizada por el cierre exacto")
    for unused_name, unused_version in sorted(set(allowlist.declarations) - used_declarations):
        failures.append(
            f"{unused_name}=={unused_version}: declaración no utilizada por el cierre exacto"
        )

    report: dict[str, object] = {
        "schema_version": 3,
        "requirements": {
            "filename": requirements_path.name,
            "size": len(requirements_bytes),
            "sha256": requirements_sha256,
        },
        "policy": {
            "classification_version": 3,
            "allowlist_filename": allowlist_path.name,
            "allowlist_sha256": hashlib.sha256(allowlist_bytes).hexdigest(),
            "supported_environments": list(_SUPPORTED_LABELS),
            "audit_environment": _audit_environment_label(),
            # El gate es hermético a propósito: la evidencia de cada declaración se lee de la copia
            # vendorizada y hasheada, nunca de la red. `--verify-sources` re-verifica esas copias
            # contra PyPI en una corrida aparte y explícita.
            "declaration_evidence": "local-vendored",
        },
        "packages": packages,
        "failures": sorted(failures),
        "status": "fail" if failures else "ok",
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if failures:
        raise RuntimeLicenseError("\n".join(sorted(failures)))
    return report


def _audit_installed(
    requirement: RuntimeRequirement,
    distribution: DistributionLike,
    declared_sources: Mapping[str, str],
    allowlist: RuntimeAllowlist,
    failures: list[str],
    used_entries: set[str],
) -> tuple[str, LicenseClassification | None]:
    name = requirement.name
    metadata_names = distribution.metadata.get_all("Name", [])
    package_name = normalize_name(metadata_names[0]) if len(metadata_names) == 1 else None
    if package_name is None:
        failures.append(f"{name}: metadata debe declarar exactamente un Name")
        return "fail_identity", None
    if package_name != name:
        failures.append(f"{name}: metadata Name incoherente: {package_name!r}")
        return "fail_identity", None
    if not distribution.version or distribution.version != requirement.version:
        failures.append(
            f"{name}: versión instalada {distribution.version!r} no coincide "
            f"con pin {requirement.version!r}"
        )
        return "fail_version", None
    try:
        classification = _classify_headers(_headers_from_metadata(distribution.metadata))
        if classification is not None:
            return "ok", _combine_sources({**classification.sources, **declared_sources})
    except RuntimeLicenseError as error:
        failures.append(f"{name}: {error}")
        return "fail_license", None
    entry = allowlist.entries.get(name)
    if entry is None:
        failures.append(f"{name}: licencia ausente, UNKNOWN o genérica")
        return "fail_missing_license", None
    valid, failure = _validate_allowlisted(distribution, entry)
    if not valid:
        failures.append(failure or f"{name}: allowlist inválida")
        return "fail_allowlist", None
    used_entries.add(name)
    try:
        return "ok_allowlisted", _combine_sources({"allowlist": entry.license, **declared_sources})
    except RuntimeLicenseError as error:
        failures.append(f"{name}: {error}")
        return "fail_allowlist", None


def verify_declaration_sources(
    allowlist_path: Path = _DEFAULT_ALLOWLIST,
    *,
    fetch: Callable[[str], bytes] | None = None,
) -> list[str]:
    """Re-descarga la fuente citada por cada declaración y la coteja con la copia vendorizada.

    Modo explícito y separado: exige red y **nunca** lo invoca el gate. Devuelve la lista de
    discrepancias; vacía significa que cada copia local reproduce byte a byte lo que PyPI publica.
    """
    allowlist = load_allowlist(allowlist_path)
    downloader = fetch if fetch is not None else _fetch_source
    mismatches: list[str] = []
    for (name, version), declaration in sorted(allowlist.declarations.items()):
        pin = f"{name}=={version}"
        try:
            raw = downloader(declaration.source)
        except (OSError, urllib.error.URLError) as error:
            mismatches.append(f"{pin}: fuente inaccesible ({error}); sin red no hay verificación")
            continue
        actual = hashlib.sha256(raw).hexdigest()
        if actual != declaration.metadata_sha256:
            mismatches.append(
                f"{pin}: upstream {actual} != declarado {declaration.metadata_sha256}"
            )
    return mismatches


def _fetch_source(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "nikodym-license-audit"})
    # La URL es https y su contenido queda anclado por sha256 antes de usarse.
    with urllib.request.urlopen(request, timeout=60) as response:
        return bytes(response.read())


def main() -> None:
    """CLI del gate de licencias runtime."""
    parser = argparse.ArgumentParser()
    parser.add_argument("requirements", type=Path, nargs="?")
    parser.add_argument("report", type=Path, nargs="?")
    parser.add_argument("--allowlist", type=Path, default=_DEFAULT_ALLOWLIST)
    parser.add_argument(
        "--verify-sources",
        action="store_true",
        help="Re-verifica contra PyPI la evidencia vendorizada de cada declaración (exige red).",
    )
    args = parser.parse_args()
    if args.verify_sources:
        mismatches = verify_declaration_sources(args.allowlist)
        if mismatches:
            joined = "\n".join(mismatches)
            raise SystemExit(f"Evidencia declarada no reproduce la fuente:\n{joined}")
        print("Evidencia de declaraciones re-verificada contra la fuente citada.")
        return
    if args.requirements is None or args.report is None:
        parser.error("se exigen requirements y report salvo con --verify-sources")
    try:
        report = audit_runtime_licenses(
            args.requirements,
            args.report,
            allowlist_path=args.allowlist,
        )
    except RuntimeLicenseError as error:
        raise SystemExit(f"Verificación de licencias runtime falló:\n{error}") from error
    packages = report["packages"]
    if not isinstance(packages, list):  # contrato interno, defensivo para el CLI
        raise SystemExit("Reporte runtime inválido")
    declared = sum(1 for package in packages if package["status"] == "ok_declared")
    print(
        f"Licencias runtime verificadas: {len(packages)} distribuciones "
        f"({len(packages) - declared} por metadata instalada, {declared} por declaración "
        f"verificada) sobre {len(_SUPPORTED_LABELS)} entornos soportados."
    )
    print(
        "Evidencia de las declaraciones: copia local hasheada (gate offline). Para re-verificarla "
        "contra PyPI: python scripts/check_runtime_licenses.py --verify-sources"
    )


if __name__ == "__main__":
    main()
