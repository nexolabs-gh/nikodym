"""Tests adversariales del contrato ejecutable de wheel/sdist B2.1."""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import io
import json
import stat
import sys
import tarfile
import warnings
import zipfile
from collections.abc import Callable
from pathlib import Path

import pytest

_POLICY = Path(__file__).resolve().parents[2] / "scripts" / "distribution_contents_allowlist.json"
_LICENSE_BYTES = _POLICY.parents[1].joinpath("LICENSE").read_bytes()
_SCRIPT = _POLICY.with_name("check_distribution_contents.py")
_SPEC = importlib.util.spec_from_file_location("check_distribution_contents", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MODULE
_SPEC.loader.exec_module(_MODULE)
DistributionContentError = _MODULE.DistributionContentError
read_archive = _MODULE.read_archive
validate_distribution = _MODULE.validate_distribution
validate_candidate_set = _MODULE.validate_candidate_set

_VERSION = "1.6.0"
_DIST_INFO = f"nikodym-{_VERSION}.dist-info"


def _metadata(
    version: str = _VERSION,
    name: str = "nikodym",
    *,
    metadata_version: str = "2.4",
    license_expression: str = "Apache-2.0",
    license_file: str = "LICENSE",
) -> bytes:
    return (
        f"Metadata-Version: {metadata_version}\n"
        f"Name: {name}\n"
        f"Version: {version}\n"
        f"License-Expression: {license_expression}\n"
        f"License-File: {license_file}\n"
    ).encode()


def _wheel_metadata(
    *,
    wheel_version: str = "1.0",
    purelib: str = "true",
    tag: str = "py3-none-any",
    build: str | None = None,
) -> bytes:
    fields = [
        f"Wheel-Version: {wheel_version}",
        f"Root-Is-Purelib: {purelib}",
        f"Tag: {tag}",
    ]
    if build is not None:
        fields.append(f"Build: {build}")
    return ("\n".join(fields) + "\n").encode()


def _wheel(
    tmp_path: Path,
    files: dict[str, bytes],
    name: str = f"nikodym-{_VERSION}-py3-none-any.whl",
    *,
    regenerate_record: bool = True,
) -> Path:
    materialized = dict(files)
    record_names = [filename for filename in materialized if filename.endswith(".dist-info/RECORD")]
    if regenerate_record and len(record_names) == 1:
        record_name = record_names[0]
        materialized[record_name] = _record_bytes(materialized, record_name)
    path = tmp_path / name
    with zipfile.ZipFile(path, "w") as archive:
        for filename, content in materialized.items():
            archive.writestr(filename, content)
    return path


def _record_bytes(files: dict[str, bytes], record_name: str) -> bytes:
    rows = []
    for filename, content in sorted(files.items()):
        if filename == record_name:
            continue
        digest = base64.urlsafe_b64encode(hashlib.sha256(content).digest()).decode().rstrip("=")
        rows.append(f"{filename},sha256={digest},{len(content)}")
    rows.append(f"{record_name},,")
    return ("\n".join(rows) + "\n").encode()


def _minimal_static(prefix: str) -> dict[str, bytes]:
    return {
        f"{prefix}/index.html": (
            b'<link rel="icon" href="/favicon.svg"><link rel="stylesheet" '
            b'href="/assets/app.css"><script src="/assets/app.js"></script>'
        ),
        f"{prefix}/favicon.svg": b"<svg/>",
        f"{prefix}/assets/app.css": b"body{}",
        f"{prefix}/assets/app.js": b"export{}",
        f"{prefix}/THIRD_PARTY_NOTICES.frontend.txt": b"MIT",
    }


def _minimal_wheel() -> dict[str, bytes]:
    return _minimal_static("nikodym/ui/static") | {
        f"{_DIST_INFO}/METADATA": _metadata(),
        f"{_DIST_INFO}/WHEEL": _wheel_metadata(),
        f"{_DIST_INFO}/RECORD": b"",
        f"{_DIST_INFO}/licenses/LICENSE": _LICENSE_BYTES,
    }


def _minimal_sdist() -> dict[str, bytes]:
    return _minimal_static("src/nikodym/ui/static") | {
        "PKG-INFO": _metadata(),
        "pyproject.toml": b"[build-system]",
        "LICENSE": _LICENSE_BYTES,
        "README.md": b"# Nikodym",
        "CHANGELOG.md": b"# Changelog",
    }


def _sdist(
    tmp_path: Path,
    files: dict[str, bytes],
    root: str | None = None,
    name: str | None = None,
) -> Path:
    root = root or f"nikodym-{_VERSION}"
    path = tmp_path / (name or f"{root}.tar.gz")
    with tarfile.open(path, "w:gz") as archive:
        for name, content in files.items():
            info = tarfile.TarInfo(f"{root}/{name}")
            info.size = len(content)
            archive.addfile(info, io.BytesIO(content))
    return path


def _provenance(
    tmp_path: Path,
    files: dict[str, bytes],
    kind: str,
    *,
    outputs: list[dict[str, object]] | None = None,
) -> Path:
    prefix = "nikodym/ui/static/" if kind == "wheel" else "src/nikodym/ui/static/"
    if outputs is None:
        outputs = [
            {
                "path": name.removeprefix(prefix),
                "size": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
                "direct_source_ids": ["test/source"],
            }
            for name, content in sorted(files.items())
            if name.startswith(prefix)
        ]
    path = tmp_path / f"frontend-provenance-{kind}.json"
    path.write_text(json.dumps({"schema_version": 2, "outputs": outputs}), encoding="utf-8")
    return path


def _validate(
    tmp_path: Path,
    artifact: Path,
    files: dict[str, bytes],
    kind: str,
    policy: Path = _POLICY,
) -> None:
    validate_distribution(artifact, policy, _provenance(tmp_path, files, kind))


def test_wheel_minimo_cumple_b21(tmp_path: Path) -> None:
    files = _minimal_wheel()
    _validate(tmp_path, _wheel(tmp_path, files), files, "wheel")


@pytest.mark.parametrize(
    "name",
    [
        "web/index.html",
        "nikodym/ui/static/demo.pdf",
        "nikodym/ui/static/fixtures/demo/results.json",
        "nikodym/ui/static/assets/extra.bin",
        "nikodym/ui/static/assets/nested/rogue.js",
        "nikodym/WEB/secret.py",
    ],
)
def test_wheel_rechaza_rutas_fuera_de_contrato(tmp_path: Path, name: str) -> None:
    files = _minimal_wheel() | {name: b"x"}
    with pytest.raises(DistributionContentError):
        _validate(tmp_path, _wheel(tmp_path, files), files, "wheel")


@pytest.mark.parametrize(
    "directory",
    ["privado", "PRIVADO", "secrets"],
)
def test_artefactos_rechazan_directorios_nunca_publicables(tmp_path: Path, directory: str) -> None:
    # `privado` es el repo git separado con detalle institucional y `secrets/` está vetado por
    # `.gitignore`; ambos entran como `*.py` bajo `nikodym/**`, que la allowlist sí permite, así que
    # sólo `forbidden_parts` los para. `/privado/` está anclado a la raíz en `.gitignore`: un
    # `src/nikodym/privado/` ni siquiera queda ignorado por git.
    wheel_files = _minimal_wheel() | {f"nikodym/{directory}/notas.py": b"# institucional\n"}
    wheel_directory = tmp_path / f"wheel-{directory}"
    wheel_directory.mkdir()
    with pytest.raises(DistributionContentError, match="Ruta prohibida"):
        _validate(wheel_directory, _wheel(wheel_directory, wheel_files), wheel_files, "wheel")

    sdist_files = _minimal_sdist() | {f"src/nikodym/{directory}/notas.py": b"# institucional\n"}
    sdist_directory = tmp_path / f"sdist-{directory}"
    sdist_directory.mkdir()
    with pytest.raises(DistributionContentError, match="Ruta prohibida"):
        _validate(sdist_directory, _sdist(sdist_directory, sdist_files), sdist_files, "sdist")


def test_wheel_rechaza_recurso_local_ausente(tmp_path: Path) -> None:
    files = _minimal_wheel()
    del files["nikodym/ui/static/favicon.svg"]
    with pytest.raises(DistributionContentError, match="Recurso local"):
        _validate(tmp_path, _wheel(tmp_path, files), files, "wheel")


@pytest.mark.parametrize(
    "html",
    [
        b'<img srcset="/favicon.svg 1x, /missing.svg 2x">',
        b'<object data="/missing.svg"></object>',
        b'<script src="/%252e%252e/escape.js"></script>',
        b'<script src="/assets%2fapp.js"></script>',
        b'<script src="/assets%5capp.js"></script>',
        b'<script src="/assets/app%2ejs"></script>',
        b'<script src="https://evil.test/app.js"></script>',
        b'<video src="https://evil.test/movie.mp4"></video>',
        b'<link rel="manifest" href="https://evil.test/site.webmanifest">',
        b'<link rel="prefetch" href="https://evil.test/data.json">',
        b'<link rel="dns-prefetch" href="//evil.test">',
        b'<video poster="https://evil.test/poster.jpg"></video>',
        b'<div href="https://evil.test/automatic"></div>',
        b'<svg><image href="https://evil.test/x.svg"></image></svg>',
        b'<svg><use xlink:href="https://evil.test/x.svg#icon"></use></svg>',
        b'<meta http-equiv="refresh" content="0; url=https://evil.test/">',
        b'<script src="https:&#47;&#47;evil.test/app.js"></script>',
        b'<script src="https&colon;&sol;&sol;evil.test/app.js"></script>',
        b'<script src="https://evil.test/app.js" SRC="/assets/app.js"></script>',
        b'<script src="data:text/javascript,fetch(`https://evil.test`)"></script>',
        b'<img src="blob:https://evil.test/identifier">',
        b'<link rel="preload" as="image" imagesrcset="https://evil.test/a.png 1x">',
        b'<iframe srcdoc="<script>fetch(`https://evil.test`)</script>"></iframe>',
        b'<body background="https://evil.test/background.png">',
    ],
)
def test_wheel_rechaza_recurso_generico_traversal_o_externo(tmp_path: Path, html: bytes) -> None:
    files = _minimal_wheel()
    files["nikodym/ui/static/index.html"] = html
    with pytest.raises(DistributionContentError):
        _validate(tmp_path, _wheel(tmp_path, files), files, "wheel")


def test_html_con_mayor_que_citado_y_enlaces_deliberados_pasa(tmp_path: Path) -> None:
    files = _minimal_wheel()
    files["nikodym/ui/static/index.html"] = (
        b'<a title="1 > 0" href="https://docs.test/">docs</a>'
        b'<a href="data:text/plain,documentacion">data deliberado</a>'
        b'<area href="https://docs.test/map"><link rel="canonical" '
        b'href="https://docs.test/canonical">'
    )
    _validate(tmp_path, _wheel(tmp_path, files), files, "wheel")


def test_wheel_rechaza_traversal(tmp_path: Path) -> None:
    path = _wheel(tmp_path, {"../escape": b"x"})
    with pytest.raises(DistributionContentError, match=r"canónica|insegura"):
        read_archive(path)


@pytest.mark.parametrize(
    "name",
    [
        "./entry",
        "directory\\entry",
        "directory//entry",
        "directory/./entry",
        "C:/entry",
    ],
)
def test_wheel_rechaza_ruta_raw_no_canonica(tmp_path: Path, name: str) -> None:
    with pytest.raises(DistributionContentError, match=r"canónica|insegura"):
        read_archive(_wheel(tmp_path, {name: b"x"}))


def test_archivos_rechazan_directorios_explicitos(tmp_path: Path) -> None:
    wheel = tmp_path / "explicit-directory.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("directory/", b"")
    with pytest.raises(DistributionContentError, match="Directorio explícito"):
        read_archive(wheel)

    sdist = tmp_path / "explicit-directory.tar.gz"
    with tarfile.open(sdist, "w:gz") as archive:
        directory = tarfile.TarInfo(f"nikodym-{_VERSION}")
        directory.type = tarfile.DIRTYPE
        archive.addfile(directory)
    with pytest.raises(DistributionContentError, match="Directorio explícito"):
        read_archive(sdist)


def test_wheel_rechaza_duplicados_y_colisiones_casefold(tmp_path: Path) -> None:
    for names, message in [
        (["duplicate", "duplicate"], "duplicada"),
        (["Case", "case"], "case-insensitive"),
    ]:
        path = tmp_path / f"{message}.whl"
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            with zipfile.ZipFile(path, "w") as archive:
                for name in names:
                    archive.writestr(name, b"x")
        with pytest.raises(DistributionContentError, match=message):
            read_archive(path)


def test_wheel_rechaza_entrada_no_regular(tmp_path: Path) -> None:
    path = tmp_path / "special.whl"
    with zipfile.ZipFile(path, "w") as archive:
        info = zipfile.ZipInfo("pipe")
        info.create_system = 3
        info.external_attr = (stat.S_IFIFO | 0o644) << 16
        archive.writestr(info, b"")
    with pytest.raises(DistributionContentError, match="no regular"):
        read_archive(path)


@pytest.mark.parametrize(
    ("files", "message"),
    [
        (
            _minimal_wheel() | {f"{_DIST_INFO}/METADATA": _metadata(version="9.9.9")},
            "Version incoherente",
        ),
        (
            {key: value for key, value in _minimal_wheel().items() if not key.endswith("/RECORD")},
            "obligatoria ausente",
        ),
        (
            _minimal_wheel() | {"other-1.0.dist-info/METADATA": _metadata()},
            "único .dist-info",
        ),
    ],
)
def test_wheel_rechaza_identidad_o_metadata_incoherente(
    tmp_path: Path, files: dict[str, bytes], message: str
) -> None:
    with pytest.raises(DistributionContentError, match=message):
        read_archive(_wheel(tmp_path, files))


@pytest.mark.parametrize(
    "name",
    [
        "nikodym-9.9.9-py3-none-any.whl",
        "nikodym-1.6.0-1-py3-none-any.whl",
        "nikodym-1.6.0-cp312-cp312-manylinux.whl",
        "candidate.whl",
    ],
)
def test_wheel_rechaza_basename_build_tag_o_tag_no_universal(tmp_path: Path, name: str) -> None:
    with pytest.raises(DistributionContentError, match="Basename wheel"):
        read_archive(_wheel(tmp_path, _minimal_wheel(), name))


@pytest.mark.parametrize(
    ("wheel_metadata", "message"),
    [
        (_wheel_metadata(wheel_version="1.1"), "Wheel-Version"),
        (_wheel_metadata(purelib="false"), "Root-Is-Purelib"),
        (_wheel_metadata(tag="cp312-cp312-macosx_14_0_arm64"), "Tag interno"),
        (_wheel_metadata(build="1"), "Build interno"),
        (
            _wheel_metadata() + b"Tag: py3-none-any\n",
            "exactamente un Tag",
        ),
        (
            b"Wheel-Version: 1.0\nRoot-Is-Purelib: false\n"
            b"Tag: cp312-cp312-manylinux_2_17_x86_64\nBuild: 1\n",
            "Root-Is-Purelib",
        ),
    ],
)
def test_wheel_rechaza_metadata_interna_no_universal(
    tmp_path: Path, wheel_metadata: bytes, message: str
) -> None:
    files = _minimal_wheel() | {f"{_DIST_INFO}/WHEEL": wheel_metadata}
    with pytest.raises(DistributionContentError, match=message):
        read_archive(_wheel(tmp_path, files))


@pytest.mark.parametrize(
    ("metadata", "message"),
    [
        (_metadata(metadata_version="2.3"), "Metadata-Version incoherente"),
        (_metadata(name="Nikodym"), "Name incoherente"),
        (_metadata(license_expression="MIT"), "License-Expression incoherente"),
        (_metadata(license_file="COPYING"), "License-File incoherente"),
        (_metadata() + b"Name: nikodym\n", "exactamente un Name"),
        (_metadata() + b"License-Expression: Apache-2.0\n", "exactamente un License-Expression"),
        (_metadata() + b"License-File: LICENSE\n", "exactamente un License-File"),
    ],
)
def test_wheel_rechaza_metadata_de_proyecto_ambigua_o_incoherente(
    tmp_path: Path, metadata: bytes, message: str
) -> None:
    files = _minimal_wheel() | {f"{_DIST_INFO}/METADATA": metadata}
    with pytest.raises(DistributionContentError, match=message):
        read_archive(_wheel(tmp_path, files))


def test_sdist_rechaza_metadata_de_proyecto_ambigua(tmp_path: Path) -> None:
    files = _minimal_sdist() | {"PKG-INFO": _metadata() + b"Version: 1.6.0\n"}
    with pytest.raises(DistributionContentError, match="exactamente un Version"):
        read_archive(_sdist(tmp_path, files))


def test_wheel_record_valido_cubre_exactamente_el_zip(tmp_path: Path) -> None:
    files = _minimal_wheel()
    content = read_archive(_wheel(tmp_path, files))
    assert set(content.files) == set(files)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda _rows, _record: b"", "vacío"),
        (lambda _rows, _record: b"\xff", "UTF-8"),
        (lambda _rows, _record: b"only,two\n", "3 columnas"),
        (
            lambda rows, _record: ("\n".join([*rows, rows[0]]) + "\n").encode(),
            "duplicada",
        ),
        (
            lambda rows, _record: ("\n".join(["./" + rows[0], *rows[1:]]) + "\n").encode(),
            "canónica",
        ),
        (
            lambda rows, _record: ("\n".join(rows[1:]) + "\n").encode(),
            "no coincide con ZIP",
        ),
        (
            lambda rows, _record: (
                "\n".join([*rows, "ghost,sha256=" + "A" * 43 + ",0"]) + "\n"
            ).encode(),
            "no coincide con ZIP",
        ),
        (
            lambda rows, _record: (
                "\n".join([rows[0].replace("sha256=", "md5=", 1), *rows[1:]]) + "\n"
            ).encode(),
            "Hash RECORD inválido",
        ),
        (
            lambda rows, _record: (
                "\n".join(
                    [
                        rows[0].rsplit(",", 1)[0] + "=," + rows[0].rsplit(",", 1)[1],
                        *rows[1:],
                    ]
                )
                + "\n"
            ).encode(),
            "no canónico",
        ),
        (
            lambda rows, _record: (
                "\n".join(
                    [
                        rows[0].split(",", 1)[0]
                        + ",sha256="
                        + "A" * 43
                        + ","
                        + rows[0].rsplit(",", 1)[1],
                        *rows[1:],
                    ]
                )
                + "\n"
            ).encode(),
            "no coincide",
        ),
        (
            lambda rows, _record: (
                "\n".join([rows[0].rsplit(",", 1)[0] + ",999", *rows[1:]]) + "\n"
            ).encode(),
            "Tamaño RECORD",
        ),
        (
            lambda rows, record: (
                "\n".join(
                    [
                        *rows[:-1],
                        f"{record},sha256={'A' * 43},1",
                    ]
                )
                + "\n"
            ).encode(),
            "autolistarse",
        ),
    ],
)
def test_wheel_rechaza_record_malformado_o_incoherente(
    tmp_path: Path,
    mutate: Callable[[list[str], str], bytes],
    message: str,
) -> None:
    files = _minimal_wheel()
    record_name = f"{_DIST_INFO}/RECORD"
    rows = _record_bytes(files, record_name).decode().splitlines()
    files[record_name] = mutate(rows, record_name)
    with pytest.raises(DistributionContentError, match=message):
        read_archive(_wheel(tmp_path, files, regenerate_record=False))


def test_sdist_minimo_cumple_b21(tmp_path: Path) -> None:
    files = _minimal_sdist()
    _validate(tmp_path, _sdist(tmp_path, files), files, "sdist")


def test_sdist_rechaza_symlink_y_fifo(tmp_path: Path) -> None:
    for kind in [tarfile.SYMTYPE, tarfile.FIFOTYPE]:
        path = tmp_path / f"candidate-{kind!r}.tar.gz"
        with tarfile.open(path, "w:gz") as archive:
            info = tarfile.TarInfo(f"nikodym-{_VERSION}/special")
            info.type = kind
            if kind == tarfile.SYMTYPE:
                info.linkname = "../../escape"
            archive.addfile(info)
        with pytest.raises(DistributionContentError, match="no regular"):
            read_archive(path)


def test_sdist_rechaza_entrada_duplicada(tmp_path: Path) -> None:
    path = tmp_path / "duplicate.tar.gz"
    with tarfile.open(path, "w:gz") as archive:
        for content in [b"a", b"b"]:
            info = tarfile.TarInfo(f"nikodym-{_VERSION}/duplicate")
            info.size = len(content)
            archive.addfile(info, io.BytesIO(content))
    with pytest.raises(DistributionContentError, match="duplicada"):
        read_archive(path)


@pytest.mark.parametrize(
    "required",
    ["PKG-INFO", "pyproject.toml", "LICENSE", "README.md", "CHANGELOG.md"],
)
def test_sdist_rechaza_metadata_o_documento_requerido_ausente(
    tmp_path: Path, required: str
) -> None:
    files = _minimal_sdist()
    del files[required]
    path = _sdist(tmp_path, files)
    if required == "PKG-INFO":
        with pytest.raises(DistributionContentError, match="PKG-INFO"):
            read_archive(path)
    else:
        with pytest.raises(DistributionContentError, match="obligatorias"):
            _validate(tmp_path, path, files, "sdist")


@pytest.mark.parametrize(
    ("root", "metadata", "message"),
    [
        ("otra-1.6.0", _metadata(), "raíz sdist"),
        ("nikodym-1.6.0", _metadata(version="9.9.9"), "Version incoherente"),
        ("nikodym-1.6.0", _metadata(name="otro"), "Name incoherente"),
    ],
)
def test_sdist_rechaza_identidad_incoherente(
    tmp_path: Path, root: str, metadata: bytes, message: str
) -> None:
    files = _minimal_sdist()
    files["PKG-INFO"] = metadata
    with pytest.raises(DistributionContentError, match=message):
        read_archive(_sdist(tmp_path, files, root))


def test_sdist_rechaza_basename_incoherente(tmp_path: Path) -> None:
    with pytest.raises(DistributionContentError, match="Basename sdist"):
        read_archive(
            _sdist(
                tmp_path,
                _minimal_sdist(),
                root=f"nikodym-{_VERSION}",
                name="nikodym-9.9.9.tar.gz",
            )
        )


def test_procedencia_liga_bytes_y_conjunto_exacto_de_static(tmp_path: Path) -> None:
    files = _minimal_wheel()
    artifact = _wheel(tmp_path, files)
    valid_path = _provenance(tmp_path, files, "wheel")
    validate_distribution(artifact, _POLICY, valid_path)

    mutated = files | {"nikodym/ui/static/assets/app.js": b"mutated"}
    with pytest.raises(DistributionContentError, match="mutado"):
        validate_distribution(_wheel(tmp_path, mutated), _POLICY, valid_path)

    outputs = json.loads(valid_path.read_text(encoding="utf-8"))["outputs"]
    without_css = [output for output in outputs if output["path"] != "assets/app.css"]
    with pytest.raises(DistributionContentError, match="exactamente"):
        validate_distribution(
            artifact,
            _POLICY,
            _provenance(tmp_path, files, "wheel", outputs=without_css),
        )

    with_extra = [
        *outputs,
        {
            "path": "ghost.svg",
            "size": 1,
            "sha256": hashlib.sha256(b"x").hexdigest(),
            "direct_source_ids": ["test/source"],
        },
    ]
    with pytest.raises(DistributionContentError, match="exactamente"):
        validate_distribution(
            artifact,
            _POLICY,
            _provenance(tmp_path, files, "wheel", outputs=with_extra),
        )


@pytest.mark.parametrize(
    "bad_output",
    [
        {
            "path": "../escape.js",
            "size": 1,
            "sha256": "0" * 64,
            "direct_source_ids": ["x"],
        },
        {
            "path": "A.js",
            "size": 1,
            "sha256": "0" * 64,
            "direct_source_ids": ["x"],
        },
    ],
)
def test_procedencia_rechaza_path_insegura_o_colision_casefold(
    tmp_path: Path, bad_output: dict[str, object]
) -> None:
    files = _minimal_wheel()
    outputs = [
        {
            "path": "a.js",
            "size": 1,
            "sha256": "0" * 64,
            "direct_source_ids": ["x"],
        },
        bad_output,
    ]
    with pytest.raises(DistributionContentError):
        validate_distribution(
            _wheel(tmp_path, files),
            _POLICY,
            _provenance(tmp_path, files, "wheel", outputs=outputs),
        )


def test_procedencia_rechaza_output_duplicado_integridad_y_schema(
    tmp_path: Path,
) -> None:
    files = _minimal_wheel()
    base = {
        "path": "index.html",
        "size": 1,
        "sha256": "0" * 64,
        "direct_source_ids": ["x"],
    }
    for outputs in [
        [base, base],
        [{**base, "size": -1}],
        [{**base, "sha256": "not-a-hash"}],
    ]:
        with pytest.raises(DistributionContentError):
            validate_distribution(
                _wheel(tmp_path, files),
                _POLICY,
                _provenance(tmp_path, files, "wheel", outputs=outputs),
            )
    invalid_schema = tmp_path / "invalid-schema.json"
    invalid_schema.write_text(
        json.dumps({"schema_version": 1, "outputs": [base]}), encoding="utf-8"
    )
    with pytest.raises(DistributionContentError, match="schema_version 2"):
        validate_distribution(_wheel(tmp_path, files), _POLICY, invalid_schema)


def test_candidate_set_exige_uno_de_cada_y_misma_version(tmp_path: Path) -> None:
    wheel_files = _minimal_wheel()
    sdist_files = _minimal_sdist()
    provenance = _provenance(tmp_path, wheel_files, "wheel")
    wheel = _wheel(tmp_path, wheel_files)
    sdist = _sdist(tmp_path, sdist_files)
    validate_candidate_set([wheel, sdist], _POLICY, provenance)
    for artifacts in [[wheel], [wheel, wheel], [sdist, sdist], [wheel, sdist, sdist]]:
        with pytest.raises(DistributionContentError, match="exactamente 1 wheel"):
            validate_candidate_set(artifacts, _POLICY, provenance)
    mismatched_files = _minimal_sdist() | {"PKG-INFO": _metadata(version="1.6.1")}
    mismatched_sdist = _sdist(tmp_path, mismatched_files, root="nikodym-1.6.1")
    with pytest.raises(DistributionContentError, match="Versiones candidate incoherentes"):
        validate_candidate_set([wheel, mismatched_sdist], _POLICY, provenance)


def test_candidate_set_exige_license_identica(tmp_path: Path) -> None:
    wheel_files = _minimal_wheel()
    sdist_files = _minimal_sdist() | {"LICENSE": b"mismo nombre, bytes distintos"}
    provenance = _provenance(tmp_path, wheel_files, "wheel")
    with pytest.raises(DistributionContentError, match="LICENSE difiere"):
        validate_candidate_set(
            [_wheel(tmp_path, wheel_files), _sdist(tmp_path, sdist_files)],
            _POLICY,
            provenance,
        )


def test_candidate_set_exige_metadata_completa_identica(tmp_path: Path) -> None:
    wheel_files = _minimal_wheel()
    sdist_files = _minimal_sdist() | {
        "PKG-INFO": _metadata() + b"Requires-Dist: extra-only-in-sdist\n"
    }
    provenance = _provenance(tmp_path, wheel_files, "wheel")
    with pytest.raises(DistributionContentError, match=r"METADATA.*difiere"):
        validate_candidate_set(
            [_wheel(tmp_path, wheel_files), _sdist(tmp_path, sdist_files)],
            _POLICY,
            provenance,
        )


def test_rebuild_desde_sdist_exige_mismo_mapa_y_bytes(tmp_path: Path) -> None:
    direct_files = _minimal_wheel() | {"nikodym/__init__.py": b"direct"}
    sdist_files = _minimal_sdist()
    provenance = _provenance(tmp_path, direct_files, "wheel")
    direct_directory = tmp_path / "direct"
    rebuilt_directory = tmp_path / "rebuilt"
    direct_directory.mkdir()
    rebuilt_directory.mkdir()
    direct = _wheel(direct_directory, direct_files)
    rebuilt = _wheel(rebuilt_directory, direct_files)
    sdist = _sdist(tmp_path, sdist_files)
    validate_candidate_set([rebuilt, sdist], _POLICY, provenance, direct)

    changed_files = direct_files | {"nikodym/__init__.py": b"changed"}
    changed = _wheel(rebuilt_directory, changed_files)
    with pytest.raises(DistributionContentError, match=r"reconstruido.*difiere"):
        validate_candidate_set([changed, sdist], _POLICY, provenance, direct)


def test_required_es_declarativo_para_que_b22_agregue_launcher(tmp_path: Path) -> None:
    policy = json.loads(_POLICY.read_text(encoding="utf-8"))
    policy["wheel"]["required"].append("nikodym/ui/__main__.py")
    custom = tmp_path / "policy.json"
    custom.write_text(json.dumps(policy), encoding="utf-8")
    files = _minimal_wheel()
    with pytest.raises(DistributionContentError, match="__main__"):
        _validate(tmp_path, _wheel(tmp_path, files), files, "wheel", custom)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda policy: policy.update(schema_version=2),
        lambda policy: policy.update(schema_version=True),
        lambda policy: policy.pop("forbidden_parts"),
        lambda policy: policy.update(extra=True),
        lambda policy: policy.update(wheel=[]),
        lambda policy: policy["wheel"].update(allowed="nikodym/**"),
        lambda policy: policy["wheel"].update(required=[1]),
        lambda policy: policy["wheel"].update(required=["outside/not-allowed"]),
        lambda policy: policy["wheel"].update(extra=[]),
    ],
)
def test_policy_rechaza_schema_estructura_y_tipos(tmp_path: Path, mutate: object) -> None:
    policy = json.loads(_POLICY.read_text(encoding="utf-8"))
    mutate(policy)
    custom = tmp_path / "invalid-policy.json"
    custom.write_text(json.dumps(policy), encoding="utf-8")
    files = _minimal_wheel()
    with pytest.raises(DistributionContentError, match="Política inválida"):
        _validate(tmp_path, _wheel(tmp_path, files), files, "wheel", custom)
