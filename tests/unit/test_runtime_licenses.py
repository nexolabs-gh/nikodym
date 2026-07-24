"""Tests fail-closed del inventario de licencias runtime Python."""

from __future__ import annotations

import email.message
import hashlib
import importlib.util
import json
import sys
from importlib import metadata
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _ROOT / "scripts" / "check_runtime_licenses.py"
_SPEC = importlib.util.spec_from_file_location("check_runtime_licenses", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MODULE
_SPEC.loader.exec_module(_MODULE)
RuntimeLicenseError = _MODULE.RuntimeLicenseError
audit_runtime_licenses = _MODULE.audit_runtime_licenses
requirement_names = _MODULE.requirement_names
runtime_requirements = _MODULE.runtime_requirements
verify_declaration_sources = _MODULE.verify_declaration_sources


class _FakeDistribution:
    def __init__(
        self,
        tmp_path: Path,
        *,
        name: str = "demo-package",
        version: str = "1.0.0",
        license_expression: str | None = "MIT",
        legacy_license: str | None = None,
        classifiers: tuple[str, ...] = (),
        license_files: tuple[str, ...] = (),
        files: dict[str, bytes] | None = None,
    ) -> None:
        package_metadata = email.message.Message()
        package_metadata["Name"] = name
        if license_expression is not None:
            package_metadata["License-Expression"] = license_expression
        if legacy_license is not None:
            package_metadata["License"] = legacy_license
        for classifier in classifiers:
            package_metadata["Classifier"] = classifier
        for license_file in license_files:
            package_metadata["License-File"] = license_file
        self.metadata = package_metadata
        self.version = version
        self._root = tmp_path / f"installed-{name}"
        self._root.mkdir(parents=True)
        self.files = []
        for relative_path, content in (files or {}).items():
            path = self._root / relative_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            self.files.append(relative_path)

    def locate_file(self, path: object) -> Path:
        return self._root / str(path)


# Marcador satisfecho por cualquier intérprete soportado (`requires-python = ">=3.11"`) y por todos
# los entornos de la matriz: el pin queda condicional pero instalable donde corra la suite.
_LOCAL_MARKER = " ; python_full_version >= '3.11'"
# Marcador de una plataforma soportada que NO es la que corre la suite, sea cual sea. Se deriva del
# host para que el test valga igual en los tres sistemas de la matriz del CI.
_FOREIGN_PLATFORM = next(
    platform for platform in ("linux", "darwin", "win32") if platform != sys.platform
)
_FOREIGN_MARKER = f" ; sys_platform == '{_FOREIGN_PLATFORM}'"


def _requirements(tmp_path: Path, text: str = "demo-package==1.0.0\n") -> Path:
    path = tmp_path / "runtime-requirements.txt"
    path.write_text(text, encoding="utf-8")
    return path


def _allowlist(
    tmp_path: Path,
    entries: list[dict[str, object]] | None = None,
    declarations: list[dict[str, object]] | None = None,
) -> Path:
    path = tmp_path / "runtime-license-allowlist.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "entries": entries or [],
                "declarations": declarations or [],
            }
        ),
        encoding="utf-8",
    )
    return path


def _core_metadata(
    name: str,
    version: str,
    headers: dict[str, object],
    metadata_version: str = "2.4",
) -> bytes:
    lines = [f"Metadata-Version: {metadata_version}", f"Name: {name}", f"Version: {version}"]
    for header, value in headers.items():
        for item in [value] if isinstance(value, str) else list(value):  # type: ignore[arg-type]
            lines.append(f"{header}: {item}")
    return ("\n".join(lines) + "\n\n").encode()


def _declaration(
    tmp_path: Path,
    name: str = "demo-package",
    version: str = "1.0.0",
    package_metadata: dict[str, object] | None = None,
    *,
    evidence: dict[str, object] | None = None,
    evidence_identity: tuple[str, str] | None = None,
    metadata_file: str | None = None,
    metadata_sha256: str | None = None,
    source: str = "https://files.pythonhosted.org/packages/ab/cd/demo-1.0.0.whl.metadata",
) -> dict[str, object]:
    transcription = (
        package_metadata if package_metadata is not None else {"License-Expression": "MIT"}
    )
    identity_name, identity_version = evidence_identity or (name, version)
    raw = _core_metadata(
        identity_name,
        identity_version,
        evidence if evidence is not None else transcription,
    )
    relative = metadata_file or f"runtime_license_metadata/{name}-{version}.metadata"
    path = tmp_path / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return {
        "name": name,
        "version": version,
        "metadata": transcription,
        "source": source,
        "metadata_file": relative,
        "metadata_sha256": metadata_sha256 or hashlib.sha256(raw).hexdigest(),
        "rationale": "Core metadata oficial del wheel publicado, vendorizada y hasheada.",
    }


def _audit(
    tmp_path: Path,
    distribution: _FakeDistribution,
    *,
    requirements: Path | None = None,
    allowlist: Path | None = None,
) -> dict[str, object]:
    return audit_runtime_licenses(
        requirements or _requirements(tmp_path),
        tmp_path / "report.json",
        allowlist_path=allowlist or _allowlist(tmp_path),
        distribution_getter=lambda _name: distribution,
    )


def test_reporte_determinista_liga_hash_del_cierre(tmp_path: Path) -> None:
    requirements = _requirements(
        tmp_path,
        "demo.package==1.0.0 \\\n  --hash=sha256:" + "0" * 64 + "\n",
    )
    distribution = _FakeDistribution(tmp_path)
    report = _audit(tmp_path, distribution, requirements=requirements)
    expected_hash = hashlib.sha256(requirements.read_bytes()).hexdigest()
    assert report["status"] == "ok"
    assert report["requirements"] == {
        "filename": "runtime-requirements.txt",
        "size": len(requirements.read_bytes()),
        "sha256": expected_hash,
    }
    first = (tmp_path / "report.json").read_bytes()
    _audit(tmp_path, distribution, requirements=requirements)
    assert (tmp_path / "report.json").read_bytes() == first
    assert requirement_names(requirements) == ("demo-package",)


@pytest.mark.parametrize(
    ("license_expression", "legacy_license", "classifiers", "message"),
    [
        (None, None, (), "ausente"),
        (None, "UNKNOWN", (), "ausente"),
        (None, None, ("License :: OSI Approved",), "ausente"),
        ("GPL-3.0-only", None, (), "GPL/LGPL/AGPL"),
        ("LGPL-2.1-or-later", None, (), "GPL/LGPL/AGPL"),
        ("AGPL-3.0", None, (), "GPL/LGPL/AGPL"),
        ("Custom-Permissive-1.0", None, (), "SPDX"),
        ("LicenseRef-internal", None, (), "LicenseRef"),
    ],
)
def test_metadata_ausente_generica_copyleft_o_desconocida_falla(
    tmp_path: Path,
    license_expression: str | None,
    legacy_license: str | None,
    classifiers: tuple[str, ...],
    message: str,
) -> None:
    distribution = _FakeDistribution(
        tmp_path,
        license_expression=license_expression,
        legacy_license=legacy_license,
        classifiers=classifiers,
    )
    with pytest.raises(RuntimeLicenseError, match=message):
        _audit(tmp_path, distribution)
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert report["status"] == "fail"
    assert report["failures"]


def test_distribucion_no_instalada_falla_no_avisa(tmp_path: Path) -> None:
    def missing(_name: str) -> _FakeDistribution:
        raise metadata.PackageNotFoundError

    with pytest.raises(RuntimeLicenseError, match="no instalada"):
        audit_runtime_licenses(
            _requirements(tmp_path),
            tmp_path / "report.json",
            allowlist_path=_allowlist(tmp_path),
            distribution_getter=missing,
        )
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert report["packages"][0]["status"] == "fail_missing_distribution"


def test_allowlist_exacta_valida_archivo_y_hash(tmp_path: Path) -> None:
    license_bytes = b"MIT License\n"
    relative_path = "huey-3.0.3.dist-info/licenses/LICENSE"
    entry = {
        "name": "huey",
        "version": "3.0.3",
        "license": "MIT",
        "license_file": relative_path,
        "sha256": hashlib.sha256(license_bytes).hexdigest(),
        "rationale": "Metadata incompleta; texto MIT distribuido por el wheel.",
    }
    allowlist = _allowlist(tmp_path, [entry])
    requirements = _requirements(tmp_path, "huey==3.0.3\n")
    distribution = _FakeDistribution(
        tmp_path,
        name="huey",
        version="3.0.3",
        license_expression=None,
        license_files=("LICENSE",),
        files={relative_path: license_bytes},
    )
    report = _audit(
        tmp_path,
        distribution,
        requirements=requirements,
        allowlist=allowlist,
    )
    assert report["packages"][0]["status"] == "ok_allowlisted"
    assert report["packages"][0]["license_expression"] == "MIT"
    assert report["packages"][0]["license_sources"] == {"allowlist": "MIT"}


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("version", "3.0.2"),
        ("license_file", "huey-3.0.3.dist-info/licenses/OTHER"),
        ("sha256", "0" * 64),
    ],
)
def test_allowlist_no_tolera_version_ruta_o_hash_distinto(
    tmp_path: Path, field: str, value: str
) -> None:
    license_bytes = b"MIT License\n"
    relative_path = "huey-3.0.3.dist-info/licenses/LICENSE"
    entry = {
        "name": "huey",
        "version": "3.0.3",
        "license": "MIT",
        "license_file": relative_path,
        "sha256": hashlib.sha256(license_bytes).hexdigest(),
        "rationale": "Metadata incompleta; texto MIT distribuido por el wheel.",
    }
    entry[field] = value
    distribution = _FakeDistribution(
        tmp_path,
        name="huey",
        version="3.0.3",
        license_expression=None,
        license_files=("LICENSE",),
        files={relative_path: license_bytes},
    )
    with pytest.raises(RuntimeLicenseError):
        _audit(
            tmp_path,
            distribution,
            requirements=_requirements(tmp_path, "huey==3.0.3\n"),
            allowlist=_allowlist(tmp_path, [entry]),
        )


def test_cierre_malformado_y_allowlist_no_usada_fallan(tmp_path: Path) -> None:
    malformed = _requirements(tmp_path, "esto no es un requirement válido !!!\n")
    with pytest.raises(RuntimeLicenseError, match="no parseables"):
        requirement_names(malformed)

    entry = {
        "name": "huey",
        "version": "3.0.3",
        "license": "MIT",
        "license_file": "huey-3.0.3.dist-info/licenses/LICENSE",
        "sha256": "0" * 64,
        "rationale": "Entrada que no corresponde al cierre de prueba.",
    }
    with pytest.raises(RuntimeLicenseError, match="no utilizada"):
        _audit(
            tmp_path,
            _FakeDistribution(tmp_path),
            allowlist=_allowlist(tmp_path, [entry]),
        )


@pytest.mark.parametrize(
    "text",
    [
        "--requirement other.txt\n",
        "-r other.txt\n",
        "-e git+https://evil.test/project.git\n",
        "-e .\n-e .\n",
        "demo-package==1.0.0 \\\n  --trusted-host evil.test\n",
        "demo-package==1.0.0 \\\n  --hash=sha256:" + "0" * 64 + " \\\n",
        "demo-package==1.0.0\n  --hash=sha256:" + "0" * 64 + "\n",
    ],
)
def test_cierre_rechaza_opciones_editables_y_continuaciones_inesperadas(
    tmp_path: Path, text: str
) -> None:
    requirements = _requirements(tmp_path, text)
    with pytest.raises(RuntimeLicenseError, match="no parseables"):
        audit_runtime_licenses(
            requirements,
            tmp_path / "report.json",
            allowlist_path=_allowlist(tmp_path),
            distribution_getter=lambda _name: _FakeDistribution(tmp_path),
        )
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert report["status"] == "fail"
    assert report["failures"]


def test_reporte_fail_se_escribe_ante_cierre_o_allowlist_ilegible(tmp_path: Path) -> None:
    missing_requirements = tmp_path / "missing-requirements.txt"
    report_path = tmp_path / "report-missing-requirements.json"
    with pytest.raises(RuntimeLicenseError, match="ilegible"):
        audit_runtime_licenses(
            missing_requirements,
            report_path,
            allowlist_path=_allowlist(tmp_path),
        )
    assert json.loads(report_path.read_text(encoding="utf-8"))["status"] == "fail"

    malformed_allowlist = tmp_path / "malformed-allowlist.json"
    malformed_allowlist.write_text("{", encoding="utf-8")
    second_report = tmp_path / "report-malformed-allowlist.json"
    with pytest.raises(RuntimeLicenseError, match="Allowlist"):
        audit_runtime_licenses(
            _requirements(tmp_path),
            second_report,
            allowlist_path=malformed_allowlist,
            distribution_getter=lambda _name: _FakeDistribution(tmp_path),
        )
    assert json.loads(second_report.read_text(encoding="utf-8"))["status"] == "fail"


def test_pin_instalado_debe_coincidir_exactamente(tmp_path: Path) -> None:
    distribution = _FakeDistribution(tmp_path, version="1.0.1")
    with pytest.raises(RuntimeLicenseError, match="no coincide con pin"):
        _audit(tmp_path, distribution)
    package = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))["packages"][0]
    assert package["expected_version"] == "1.0.0"
    assert package["version"] == "1.0.1"
    assert package["status"] == "fail_version"

    ranged = _requirements(tmp_path, "demo-package>=1.0.0\n")
    with pytest.raises(RuntimeLicenseError, match="no parseables"):
        runtime_requirements(ranged)


def test_name_y_version_de_metadata_son_obligatorios(tmp_path: Path) -> None:
    missing_name = _FakeDistribution(tmp_path / "name")
    del missing_name.metadata["Name"]
    with pytest.raises(RuntimeLicenseError, match="exactamente un Name"):
        _audit(tmp_path / "name", missing_name)

    missing_version = _FakeDistribution(tmp_path / "version", version="")
    with pytest.raises(RuntimeLicenseError, match="versión instalada"):
        _audit(tmp_path / "version", missing_version)


def test_conflicto_entre_fuentes_y_headers_duplicados_fallan(tmp_path: Path) -> None:
    conflicting = _FakeDistribution(
        tmp_path,
        license_expression="MIT",
        legacy_license="Apache-2.0",
    )
    with pytest.raises(RuntimeLicenseError, match="contradictorias"):
        _audit(tmp_path, conflicting)

    duplicated = _FakeDistribution(tmp_path / "duplicate", license_expression="MIT")
    duplicated.metadata["License-Expression"] = "Apache-2.0"
    with pytest.raises(RuntimeLicenseError, match="duplica License-Expression"):
        _audit(tmp_path / "duplicate", duplicated)

    three_way_conflict = _FakeDistribution(
        tmp_path / "three-way",
        license_expression="MIT OR Apache-2.0",
        legacy_license="Apache-2.0",
        classifiers=("License :: OSI Approved :: MIT License",),
    )
    with pytest.raises(RuntimeLicenseError, match="contradictorias"):
        _audit(tmp_path / "three-way", three_way_conflict)


@pytest.mark.parametrize(
    "license_files",
    [(), ("COPYING",), ("LICENSE", "COPYING")],
)
def test_allowlist_exige_license_file_singleton_exacto(
    tmp_path: Path, license_files: tuple[str, ...]
) -> None:
    license_bytes = b"MIT License\n"
    relative_path = "huey-3.0.3.dist-info/licenses/LICENSE"
    entry = {
        "name": "huey",
        "version": "3.0.3",
        "license": "MIT",
        "license_file": relative_path,
        "sha256": hashlib.sha256(license_bytes).hexdigest(),
        "rationale": "Metadata incompleta; texto MIT distribuido por el wheel.",
    }
    distribution = _FakeDistribution(
        tmp_path,
        name="huey",
        version="3.0.3",
        license_expression=None,
        license_files=license_files,
        files={relative_path: license_bytes},
    )
    with pytest.raises(RuntimeLicenseError, match="License-File"):
        _audit(
            tmp_path,
            distribution,
            requirements=_requirements(tmp_path, "huey==3.0.3\n"),
            allowlist=_allowlist(tmp_path, [entry]),
        )


def test_pin_de_otra_plataforma_no_se_descarta_en_silencio(tmp_path: Path) -> None:
    requirements = _requirements(
        tmp_path,
        f"demo-package==1.0.0\nforeign-package==2.0.0{_FOREIGN_MARKER}\n",
    )
    with pytest.raises(RuntimeLicenseError, match="no es instalable en el entorno de auditoría"):
        _audit(tmp_path, _FakeDistribution(tmp_path), requirements=requirements)
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    packages = {package["name"]: package for package in report["packages"]}
    assert set(packages) == {"demo-package", "foreign-package"}
    assert packages["foreign-package"]["status"] == "fail_undeclared"
    assert packages["foreign-package"]["installable"] is False
    assert packages["foreign-package"]["environments"] > 0
    assert requirement_names(requirements) == ("demo-package", "foreign-package")


def test_matriz_soportada_cubre_los_tres_sistemas_y_tres_minor(tmp_path: Path) -> None:
    lines = [
        "demo-package==1.0.0",
        "solo-linux==1.0.0 ; sys_platform == 'linux'",
        "solo-mac==1.0.0 ; sys_platform == 'darwin'",
        "solo-windows==1.0.0 ; sys_platform == 'win32'",
        "solo-311==1.0.0 ; python_full_version < '3.12'",
        "solo-313==1.0.0 ; python_full_version >= '3.13'",
        "solo-intel-mac==1.0.0 ; platform_machine == 'x86_64' and sys_platform == 'darwin'",
        "solo-arm-linux==1.0.0 ; platform_machine == 'aarch64' and sys_platform == 'linux'",
        "fuera-de-matriz==1.0.0 ; python_full_version < '3.11'",
    ]
    requirements = _requirements(tmp_path, "\n".join(lines) + "\n")
    scope = {
        requirement.name: requirement.environments
        for requirement in runtime_requirements(requirements)
    }
    assert set(scope) == {
        "demo-package",
        "fuera-de-matriz",
        "solo-311",
        "solo-313",
        "solo-arm-linux",
        "solo-intel-mac",
        "solo-linux",
        "solo-mac",
        "solo-windows",
    }
    # Ningún pin alcanzable por un usuario soportado queda fuera; el único con alcance vacío es el
    # que ningún entorno de la matriz satisface, y ése no se descarta: se conserva para fallar.
    assert all(scope[name] for name in scope if name != "fuera-de-matriz")
    assert scope["fuera-de-matriz"] == ()
    assert len(scope["demo-package"]) == 30


def test_declaracion_verificada_clasifica_pin_no_instalable(tmp_path: Path) -> None:
    requirements = _requirements(tmp_path, f"waitress==3.0.2{_FOREIGN_MARKER}\n")
    allowlist = _allowlist(
        tmp_path,
        declarations=[
            _declaration(
                tmp_path,
                name="waitress",
                version="3.0.2",
                package_metadata={
                    "License": "ZPL 2.1",
                    "Classifier": ["License :: OSI Approved :: Zope Public License"],
                },
            )
        ],
    )
    report = _audit(
        tmp_path,
        _FakeDistribution(tmp_path),
        requirements=requirements,
        allowlist=allowlist,
    )
    package = report["packages"][0]
    assert package["status"] == "ok_declared"
    assert package["version"] is None
    assert package["license_expression"] == "ZPL-2.1"
    assert package["license_sources"] == {
        "declaration:License": "ZPL-2.1",
        "declaration:Classifier": "ZPL-2.0 OR ZPL-2.1",
    }


@pytest.mark.parametrize(
    ("package_metadata", "source", "message"),
    [
        ({"License-Expression": "GPL-3.0-only"}, None, "GPL/LGPL/AGPL"),
        ({"License-Expression": "LicenseRef-NVIDIA-Proprietary"}, None, "LicenseRef"),
        ({"License-Expression": "Custom-Permissive-1.0"}, None, "SPDX"),
        ({"License": "UNKNOWN"}, None, "sin evidencia de licencia"),
        ({"Classifier": ["License :: OSI Approved"]}, None, "sin evidencia de licencia"),
        ({"Classifier": ["Topic :: Utilities"]}, None, "sin evidencia de licencia"),
        (
            {"License-Expression": "MIT", "Classifier": ["License :: OSI Approved :: BSD License"]},
            None,
            "contradictorias",
        ),
        ({"License-Expression": "MIT"}, "el sitio del proyecto", "Fuente declarada no verificable"),
        ({"License-Expression": "MIT"}, "http://pypi.org/x", "Fuente declarada no verificable"),
    ],
)
def test_declaracion_rechaza_copyleft_no_spdx_o_fuente_no_citable(
    tmp_path: Path,
    package_metadata: dict[str, object],
    source: str | None,
    message: str,
) -> None:
    declaration = _declaration(
        tmp_path,
        name="foreign-package",
        version="2.0.0",
        package_metadata=package_metadata,
    )
    if source is not None:
        declaration["source"] = source
    with pytest.raises(RuntimeLicenseError, match=message):
        _audit(
            tmp_path,
            _FakeDistribution(tmp_path),
            requirements=_requirements(tmp_path, f"foreign-package==2.0.0{_FOREIGN_MARKER}\n"),
            allowlist=_allowlist(tmp_path, declarations=[declaration]),
        )


def test_declaracion_exige_pin_exacto_y_no_admite_duplicados(tmp_path: Path) -> None:
    requirements = _requirements(tmp_path, f"foreign-package==2.0.0{_FOREIGN_MARKER}\n")
    with pytest.raises(RuntimeLicenseError, match="declaración no utilizada"):
        _audit(
            tmp_path,
            _FakeDistribution(tmp_path),
            requirements=requirements,
            allowlist=_allowlist(
                tmp_path,
                declarations=[
                    _declaration(tmp_path, name="foreign-package", version="2.0.0"),
                    _declaration(tmp_path, name="foreign-package", version="1.9.0"),
                ],
            ),
        )
    duplicated = tmp_path / "duplicada"
    with pytest.raises(RuntimeLicenseError, match="Declaración duplicada"):
        _audit(
            duplicated,
            _FakeDistribution(duplicated),
            requirements=requirements,
            allowlist=_allowlist(
                duplicated,
                declarations=[
                    _declaration(duplicated, name="foreign-package", version="2.0.0"),
                    _declaration(duplicated, name="foreign-package", version="2.0.0"),
                ],
            ),
        )


def test_declaracion_prohibida_para_pin_sin_marcador(tmp_path: Path) -> None:
    with pytest.raises(RuntimeLicenseError, match="declaración innecesaria"):
        _audit(
            tmp_path,
            _FakeDistribution(tmp_path),
            allowlist=_allowlist(tmp_path, declarations=[_declaration(tmp_path)]),
        )


def test_declaracion_se_cruza_con_la_metadata_instalada(tmp_path: Path) -> None:
    requirements = _requirements(tmp_path, f"demo-package==1.0.0{_LOCAL_MARKER}\n")
    coherent = _audit(
        tmp_path,
        _FakeDistribution(tmp_path, license_expression="MIT"),
        requirements=requirements,
        allowlist=_allowlist(tmp_path, declarations=[_declaration(tmp_path)]),
    )
    package = coherent["packages"][0]
    assert package["status"] == "ok"
    assert package["license_sources"] == {
        "License-Expression": "MIT",
        "declaration:License-Expression": "MIT",
    }

    with pytest.raises(RuntimeLicenseError, match="contradictorias"):
        _audit(
            tmp_path / "conflicto",
            _FakeDistribution(tmp_path / "conflicto", license_expression="Apache-2.0"),
            requirements=requirements,
            allowlist=_allowlist(tmp_path, declarations=[_declaration(tmp_path)]),
        )


def test_pins_por_version_de_python_se_auditan_por_separado(tmp_path: Path) -> None:
    requirements = _requirements(
        tmp_path,
        f"demo-package==1.0.0{_LOCAL_MARKER}\ndemo-package==0.9.0{_FOREIGN_MARKER}\n",
    )
    report = _audit(
        tmp_path,
        _FakeDistribution(tmp_path),
        requirements=requirements,
        allowlist=_allowlist(
            tmp_path,
            declarations=[_declaration(tmp_path, version="0.9.0")],
        ),
    )
    packages = {str(package["expected_version"]): package for package in report["packages"]}
    assert set(packages) == {"1.0.0", "0.9.0"}
    assert packages["1.0.0"]["status"] == "ok"
    assert packages["0.9.0"]["status"] == "ok_declared"


def test_declaracion_infiel_no_puede_reetiquetar_la_licencia(tmp_path: Path) -> None:
    # PoC del revisor: la evidencia vendorizada manda sobre la transcripción legible. La metadata
    # real reproducida aquí es la que PyPI publica para nvidia-nccl-cu12 2.30.7, el paquete
    # propietario que el cierre acaba de dejar de arrastrar.
    requirements = _requirements(tmp_path, f"foreign-package==2.0.0{_FOREIGN_MARKER}\n")
    mentira = _declaration(
        tmp_path,
        name="foreign-package",
        version="2.0.0",
        package_metadata={"License-Expression": "Apache-2.0"},
        evidence={"License-Expression": "LicenseRef-NVIDIA-Proprietary"},
    )
    with pytest.raises(RuntimeLicenseError, match="Transcripción infiel"):
        _audit(
            tmp_path,
            _FakeDistribution(tmp_path),
            requirements=requirements,
            allowlist=_allowlist(tmp_path, declarations=[mentira]),
        )

    fiel = tmp_path / "fiel"
    fiel.mkdir()
    with pytest.raises(RuntimeLicenseError, match="LicenseRef"):
        _audit(
            fiel,
            _FakeDistribution(fiel),
            requirements=requirements,
            allowlist=_allowlist(
                fiel,
                declarations=[
                    _declaration(
                        fiel,
                        name="foreign-package",
                        version="2.0.0",
                        package_metadata={"License-Expression": "LicenseRef-NVIDIA-Proprietary"},
                    )
                ],
            ),
        )


def test_declaracion_exige_evidencia_hasheada_y_de_la_misma_distribucion(tmp_path: Path) -> None:
    requirements = _requirements(tmp_path, f"foreign-package==2.0.0{_FOREIGN_MARKER}\n")

    def audit(directory: Path, declaration: dict[str, object]) -> None:
        _audit(
            directory,
            _FakeDistribution(directory),
            requirements=requirements,
            allowlist=_allowlist(directory, declarations=[declaration]),
        )

    adulterada = tmp_path / "adulterada"
    adulterada.mkdir()
    declaration = _declaration(adulterada, name="foreign-package", version="2.0.0")
    evidence_path = adulterada / str(declaration["metadata_file"])
    evidence_path.write_bytes(evidence_path.read_bytes() + b"Classifier: License :: OSI Approved\n")
    with pytest.raises(RuntimeLicenseError, match="no coincide con su hash"):
        audit(adulterada, declaration)

    otro_paquete = tmp_path / "otro-paquete"
    otro_paquete.mkdir()
    with pytest.raises(RuntimeLicenseError, match="Evidencia de otra distribución"):
        audit(
            otro_paquete,
            _declaration(
                otro_paquete,
                name="foreign-package",
                version="2.0.0",
                evidence_identity=("otro-paquete", "2.0.0"),
            ),
        )

    otra_version = tmp_path / "otra-version"
    otra_version.mkdir()
    with pytest.raises(RuntimeLicenseError, match="Evidencia de otra versión"):
        audit(
            otra_version,
            _declaration(
                otra_version,
                name="foreign-package",
                version="2.0.0",
                evidence_identity=("foreign-package", "1.0.0"),
            ),
        )


@pytest.mark.parametrize(
    ("metadata_file", "metadata_sha256", "message"),
    [
        ("runtime_license_metadata/ausente.metadata", None, "ilegible"),
        ("../fuera.metadata", None, "insegura"),
        ("/etc/passwd", None, "insegura"),
        ("otro_directorio/x.metadata", None, "fuera de runtime_license_metadata"),
        (None, "no-es-un-hash", "SHA-256 de evidencia inválido"),
        (None, "0" * 64, "no coincide con su hash"),
    ],
)
def test_declaracion_rechaza_evidencia_ausente_insegura_o_sin_ancla(
    tmp_path: Path,
    metadata_file: str | None,
    metadata_sha256: str | None,
    message: str,
) -> None:
    declaration = _declaration(
        tmp_path,
        name="foreign-package",
        version="2.0.0",
        metadata_sha256=metadata_sha256,
    )
    if metadata_file is not None:
        declaration["metadata_file"] = metadata_file
    with pytest.raises(RuntimeLicenseError, match=message):
        _audit(
            tmp_path,
            _FakeDistribution(tmp_path),
            requirements=_requirements(tmp_path, f"foreign-package==2.0.0{_FOREIGN_MARKER}\n"),
            allowlist=_allowlist(tmp_path, declarations=[declaration]),
        )


def test_pin_fuera_de_la_matriz_no_se_descarta_en_silencio(tmp_path: Path) -> None:
    requirements = _requirements(
        tmp_path,
        "demo-package==1.0.0\nfuera-de-matriz==9.9.9 ; python_full_version < '3.11'\n",
    )
    with pytest.raises(RuntimeLicenseError, match="no se cumple en ninguno"):
        _audit(tmp_path, _FakeDistribution(tmp_path), requirements=requirements)
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    packages = {package["name"]: package for package in report["packages"]}
    assert packages["fuera-de-matriz"]["status"] == "fail_out_of_matrix"
    assert packages["fuera-de-matriz"]["environments"] == 0
    assert packages["demo-package"]["status"] == "ok"


def test_verificacion_upstream_es_un_modo_aparte_y_no_falla_en_silencio(tmp_path: Path) -> None:
    declaration = _declaration(tmp_path, name="foreign-package", version="2.0.0")
    allowlist = _allowlist(tmp_path, declarations=[declaration])
    evidence = (tmp_path / str(declaration["metadata_file"])).read_bytes()

    assert verify_declaration_sources(allowlist, fetch=lambda _url: evidence) == []

    divergente = verify_declaration_sources(allowlist, fetch=lambda _url: evidence + b"X")
    assert len(divergente) == 1
    assert "upstream" in divergente[0]

    def sin_red(_url: str) -> bytes:
        raise OSError("sin red")

    caido = verify_declaration_sources(allowlist, fetch=sin_red)
    assert len(caido) == 1
    assert "sin red no hay verificación" in caido[0]


def test_reporte_publica_el_ancla_de_cada_declaracion(tmp_path: Path) -> None:
    declaration = _declaration(tmp_path, name="foreign-package", version="2.0.0")
    report = _audit(
        tmp_path,
        _FakeDistribution(tmp_path),
        requirements=_requirements(tmp_path, f"foreign-package==2.0.0{_FOREIGN_MARKER}\n"),
        allowlist=_allowlist(tmp_path, declarations=[declaration]),
    )
    package = report["packages"][0]
    assert package["declaration_source"] == declaration["source"]
    assert package["declaration_sha256"] == declaration["metadata_sha256"]
    policy = report["policy"]
    assert policy["declaration_evidence"] == "local-vendored"


def test_classifier_versionado_converge_con_legacy_spdx(tmp_path: Path) -> None:
    distribution = _FakeDistribution(
        tmp_path,
        license_expression=None,
        legacy_license="MIT OR Apache-2.0",
        classifiers=(
            "License :: OSI Approved :: MIT License",
            "License :: OSI Approved :: Apache Software License",
        ),
    )
    report = _audit(tmp_path, distribution)
    package = report["packages"][0]
    assert package["status"] == "ok"
    assert set(package["license_sources"]) == {"License", "Classifier"}
