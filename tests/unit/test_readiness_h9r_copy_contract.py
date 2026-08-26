from __future__ import annotations

import ast
import os
import shutil
import subprocess
import sys
import zipfile
from collections.abc import Iterable
from pathlib import Path

import pytest

import scripts.readiness_h9r.copy_gate as copy_gate_module
from scripts.readiness_h9r.copy_gate import (
    CopyGateError,
    assert_documented_h9r_catalog,
    assert_documented_h9r_runtime_catalog,
    assert_no_h9r_capacity_copy,
    public_copy_paths,
    scan_capacity_claims,
)

ROOT = Path(__file__).resolve().parents[2]


def test_gate_estatico_no_importa_modulo_runtime_de_contratos() -> None:
    source = ROOT / "scripts/readiness_h9r/copy_gate.py"
    module = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    assert not any(
        isinstance(node, ast.ImportFrom) and node.level == 1 and node.module == "contracts"
        for node in ast.walk(module)
    )
    script = (
        "import sys;"
        f"sys.path.insert(0, {str(ROOT)!r});"
        "from scripts.readiness_h9r import copy_gate;"
        "assert copy_gate.__name__ == 'scripts.readiness_h9r.copy_gate';"
        "assert 'scripts.readiness_h9r.contracts' not in sys.modules"
    )
    completed = subprocess.run(
        [sys.executable, "-I", "-B", "-S", "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr


def test_runbook_aisla_gate_copy_de_pythonpath_y_sitecustomize(tmp_path: Path) -> None:
    poison = tmp_path / "poison"
    poison.mkdir()
    marker = tmp_path / "sitecustomize-loaded"
    (poison / "sitecustomize.py").write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).write_text('loaded')\n",
        encoding="utf-8",
    )
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(poison)
    completed = subprocess.run(
        [
            sys.executable,
            "-I",
            "-B",
            "-c",
            "import sys; assert sys.flags.isolated == 1; assert 'sitecustomize' not in sys.modules",
        ],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )
    assert completed.returncode == 0, completed.stderr
    assert not marker.exists()
    runbook = (ROOT / "docs/operacion/RUNBOOK.md").read_text(encoding="utf-8")
    assert "'@ | & $nikodymPython -I -B -" in runbook
    assert "if sys.flags.isolated != 1 or sys.dont_write_bytecode != 1:" in runbook


def test_censo_publico_cubre_superficies_y_excluye_diseno_interno() -> None:
    relative = {path.relative_to(ROOT).as_posix() for path in public_copy_paths(ROOT)}
    assert {
        "README.md",
        "CHANGELOG.md",
        "SECURITY.md",
        "SUPPORT.md",
        "pyproject.toml",
        "mkdocs.yml",
        "web/index.html",
        "web/package.json",
        "web/src/fixtures/demo/report-quarto.zip",
    } <= relative
    assert any(path.startswith("docs_site/") for path in relative)
    assert any(path.startswith("web/src/") for path in relative)
    if (ROOT / "web/dist").is_dir():
        assert any(path.startswith("web/dist/") for path in relative)
    assert any(path.startswith("src/nikodym/ui/") for path in relative)
    assert any(path.startswith("src/nikodym/report/") for path in relative)
    assert "reports" in copy_gate_module.PUBLIC_COPY_TREES
    assert not any(path.startswith("docs/design/") for path in relative)
    assert not any(path.startswith("docs/operacion/") for path in relative)
    assert assert_no_h9r_capacity_copy(ROOT) == len(relative)


@pytest.mark.parametrize(
    ("copy", "literal"),
    [
        ("Funciona con 4 CPU.", "4 CPU"),
        ("Delivered on four logical cores.", "four logical cores"),
        ("Opera sobre cuatro procesadores lógicos.", "cuatro procesadores lógicos"),
        ("Provisiona 4 vCPUs.", "4 vCPUs"),
        ("Runs on a 4-core host.", "4-core"),
        ("Runs on a four-core host.", "four-core"),
        ("Runs with four threads.", "four threads"),
        ("Runs on a quad-core host.", "quad-core"),
        ("Runs on a 4\u2011core host.", "4\u2011core"),
        ("Requiere 8 GiB de memoria.", "8 GiB de memoria"),
        ("Incluye 8 GB RAM.", "8 GB RAM"),
        ("Requires 8-GB RAM.", "8-GB RAM"),
        ("Requires eight GB RAM.", "eight GB RAM"),
        ("Requires eight-GB RAM.", "eight-GB RAM"),
        ("Requires 8G RAM.", "8G RAM"),
        ("Requires 8\u2013GB RAM.", "8\u2013GB RAM"),
        ("Needs ocho gigabytes de RAM.", "ocho gigabytes de RAM"),
        ("Reserva 8192 MiB de memoria.", "8192 MiB de memoria"),
        ("RAM: 8 GiB.", "RAM: 8 GiB"),
        ("Memoria de 8 GB.", "Memoria de 8 GB"),
        ("CPU de cuatro núcleos.", "CPU de cuatro núcleos"),
    ],
)
def test_detecta_parafrasis_de_capacidad(tmp_path: Path, copy: str, literal: str) -> None:
    path = tmp_path / "copy.md"
    path.write_text(copy, encoding="utf-8")
    findings = scan_capacity_claims([path])
    assert [(finding["line"], finding["literal"]) for finding in findings] == [(1, literal)]


@pytest.mark.parametrize(
    "copy",
    [
        "La versión v4 CPU mantiene compatibilidad de schema.",
        "The four corners of the report remain visible.",
        "The quad layout contains four panels.",
        "El octavo GB del archivo contiene el índice.",
        "The downloadable archive is 8 GB.",
        "El archivo ocupa 8192 MiB en disco.",
        "El identificador 8G2 pertenece al schema.",
    ],
)
def test_no_confunde_identificadores_o_frases_no_capacidad(tmp_path: Path, copy: str) -> None:
    path = tmp_path / "copy.md"
    path.write_text(copy, encoding="utf-8")
    assert scan_capacity_claims([path]) == []


def test_python_ignora_comentario_interno_pero_censa_string_publicable(tmp_path: Path) -> None:
    path = tmp_path / "surface.py"
    path.write_text(
        "# nota interna sobre 4 CPU\nTOOLTIP = 'capacidad de 8 GB de memoria'\n",
        encoding="utf-8",
    )
    findings = scan_capacity_claims([path])
    assert [(finding["line"], finding["literal"]) for finding in findings] == [
        (2, "8 GB de memoria")
    ]


@pytest.mark.parametrize("suffix", [".js", ".mjs", ".ts", ".tsx", ".css"])
def test_js_ts_css_ignoran_comentarios_y_conservan_copy_visible(
    tmp_path: Path,
    suffix: str,
) -> None:
    path = tmp_path / f"surface{suffix}"
    if suffix == ".css":
        path.write_text(
            "/* nota interna sobre 4 CPU */\n"
            '.card::after { content: "capacidad de 8 GB de RAM"; }\n',
            encoding="utf-8",
        )
    else:
        path.write_text(
            "// nota interna sobre 4 CPU\n"
            'const label = "capacidad de 8 GB de RAM";\n'
            "const view = <span>Disponible con four threads</span>;\n",
            encoding="utf-8",
        )
    assert [finding["literal"] for finding in scan_capacity_claims([path])] == (
        ["8 GB de RAM"] if suffix == ".css" else ["8 GB de RAM", "four threads"]
    )


def test_css_no_confunde_url_con_comentario_js(tmp_path: Path) -> None:
    path = tmp_path / "surface.css"
    path.write_text(
        'a { background: url(https://example.test/a.png); content: "4 CPU"; }\n',
        encoding="utf-8",
    )
    assert [finding["literal"] for finding in scan_capacity_claims([path])] == ["4 CPU"]


def test_js_distingue_regex_y_comentario_en_template_expression(tmp_path: Path) -> None:
    path = tmp_path / "lexer.js"
    path.write_text(
        "const double = /\"/; const single = /'/;\n"
        "const rendered = `${/* nota interna 4 CPU */ value}`;\n"
        'document.body.textContent = "8 GB RAM";\n',
        encoding="utf-8",
    )
    assert [finding["literal"] for finding in scan_capacity_claims([path])] == ["8 GB RAM"]


def test_jinja_ignora_comentario_y_conserva_copy_renderizable(tmp_path: Path) -> None:
    path = tmp_path / "surface.j2"
    path.write_text(
        '{# nota interna four threads #}<span title="capacidad de 8 GB RAM">4 CPU</span>',
        encoding="utf-8",
    )
    assert sorted(finding["literal"] for finding in scan_capacity_claims([path])) == [
        "4 CPU",
        "8 GB RAM",
    ]


def test_html_ignora_comentarios_inline_y_conserva_template_y_texto_visible(
    tmp_path: Path,
) -> None:
    path = tmp_path / "surface.html"
    path.write_text(
        "<html><script>// benchmark interno: 4 CPU</script>"
        "<style>/* benchmark interno: 8 GB RAM */</style>"
        "<template>Disponible con four threads</template>"
        '<p aria-label="capacidad de 8 GB de RAM">Disponible con 4 CPU</p></html>',
        encoding="utf-8",
    )
    assert sorted(finding["literal"] for finding in scan_capacity_claims([path])) == [
        "4 CPU",
        "8 GB de RAM",
        "four threads",
    ]


def test_html_censa_copy_generado_por_script_y_css_inline(tmp_path: Path) -> None:
    path = tmp_path / "generated.html"
    path.write_text(
        "<script>// benchmark interno 8 GB RAM\n"
        'document.body.textContent = "4 CPU";</script>'
        "<style>/* benchmark interno four threads */"
        '.badge::after { content: "8 GB RAM"; }</style>',
        encoding="utf-8",
    )
    assert sorted(finding["literal"] for finding in scan_capacity_claims([path])) == [
        "4 CPU",
        "8 GB RAM",
    ]


def test_html_rechaza_script_inline_sin_cierre(tmp_path: Path) -> None:
    path = tmp_path / "incomplete.html"
    path.write_text(
        '<script>document.body.textContent = "Disponible con 4 CPU";',
        encoding="utf-8",
    )
    with pytest.raises(CopyGateError, match="contenedor inline incompleto"):
        scan_capacity_claims([path])


def test_js_concatena_literals_y_tsx_reconstruye_texto_estatico(tmp_path: Path) -> None:
    javascript = tmp_path / "joined.js"
    javascript.write_text('document.body.textContent = "4 " + "CPU";\n', encoding="utf-8")
    tsx = tmp_path / "view.tsx"
    tsx.write_text("const view = <span>{4} logical CPUs</span>;\n", encoding="utf-8")
    assert [finding["literal"] for finding in scan_capacity_claims([javascript])] == ["4 CPU"]
    assert [finding["literal"] for finding in scan_capacity_claims([tsx])] == ["4 logical CPUs"]


def test_css_no_confunde_selector_con_copy_visible(tmp_path: Path) -> None:
    path = tmp_path / "layout.css"
    path.write_text(".four-cpu-layout { display: grid; }\n", encoding="utf-8")
    assert scan_capacity_claims([path]) == []


def test_html_censa_metadata_y_valor_visible_de_formulario(tmp_path: Path) -> None:
    path = tmp_path / "metadata.html"
    path.write_text(
        '<meta name="description" content="Disponible con 4 CPU">'
        '<meta property="og:description" content="Capacidad de 8 GB RAM">'
        '<input type="text" value="four threads">'
        '<input type="hidden" value="oculto con 4 CPU">'
        '<span data-tooltip="Disponible con 4 CPU"></span>'
        '<span aria-description="Capacidad de 8 GB RAM"></span>',
        encoding="utf-8",
    )
    assert sorted(finding["literal"] for finding in scan_capacity_claims([path])) == [
        "4 CPU",
        "4 CPU",
        "8 GB RAM",
        "8 GB RAM",
        "four threads",
    ]


@pytest.mark.parametrize(
    ("suffix", "source", "expected"),
    [
        (
            ".toml",
            '# benchmark interno: 4 CPU\nlabel = "capacidad de 8 GB de RAM"\n',
            ["8 GB de RAM"],
        ),
        (".yaml", '# benchmark interno: 8 GB RAM\nlabel: "four threads"\n', ["four threads"]),
        (".yml", 'name: ok # benchmark interno: four threads\nlabel: "4 CPU"\n', ["4 CPU"]),
        (".rst", ".. benchmark interno: 8 GB RAM\n\nDisponible con 4 CPU\n", ["4 CPU"]),
    ],
)
def test_formatos_declarativos_ignoran_comentarios_y_conservan_strings_visibles(
    tmp_path: Path,
    suffix: str,
    source: str,
    expected: list[str],
) -> None:
    path = tmp_path / f"surface{suffix}"
    path.write_text(source, encoding="utf-8")
    assert [finding["literal"] for finding in scan_capacity_claims([path])] == expected


@pytest.mark.parametrize(
    ("suffix", "source", "expected"),
    [
        (".yaml", "items:\n  - |\n    # copy visible 4 CPU\n", ["4 CPU"]),
        (".yml", "label: !!str |\n  # copy visible 8 GB RAM\n", ["8 GB RAM"]),
        (
            ".rst",
            ".. |cap| replace:: Disponible con 4 CPU\n\n|cap|\n",
            ["4 CPU"],
        ),
        (
            ".rst",
            ".. |logo| image:: logo.png\n   :alt: Disponible con 4 CPU\n\n|logo|\n",
            ["4 CPU"],
        ),
    ],
)
def test_declarativos_conservan_block_scalars_y_sustituciones_visibles(
    tmp_path: Path,
    suffix: str,
    source: str,
    expected: list[str],
) -> None:
    path = tmp_path / f"visible{suffix}"
    path.write_text(source, encoding="utf-8")
    assert [finding["literal"] for finding in scan_capacity_claims([path])] == expected


@pytest.mark.parametrize("suffix", [".svg", ".xml"])
def test_xml_svg_ignoran_script_style_y_conservan_texto_visible(
    tmp_path: Path,
    suffix: str,
) -> None:
    path = tmp_path / f"surface{suffix}"
    path.write_text(
        "<root><style>/* benchmark 4 CPU */</style>"
        "<script>// benchmark 8 GB RAM</script>"
        '<text aria-label="capacidad de 8 GB de RAM">Disponible con 4 CPU</text></root>',
        encoding="utf-8",
    )
    assert sorted(finding["literal"] for finding in scan_capacity_claims([path])) == [
        "4 CPU",
        "8 GB de RAM",
    ]


@pytest.mark.parametrize("suffix", [".svg", ".xml"])
def test_xml_svg_censan_copy_generado_por_script_inline(
    tmp_path: Path,
    suffix: str,
) -> None:
    path = tmp_path / f"generated{suffix}"
    path.write_text(
        "<svg><script>// nota interna 8 GB RAM\n"
        'document.documentElement.textContent = "Disponible con 4 CPU";'
        "</script><text>neutro</text></svg>",
        encoding="utf-8",
    )
    assert [finding["literal"] for finding in scan_capacity_claims([path])] == ["4 CPU"]


def test_python_y_zip_censan_fstrings_publicables(tmp_path: Path) -> None:
    source = tmp_path / "surface.py"
    source.write_text(
        "TOOLTIP = f'Disponible con four threads'\nOTHER = f'{4} logical CPUs'\n",
        encoding="utf-8",
    )
    assert [finding["literal"] for finding in scan_capacity_claims([source])] == [
        "four threads",
        "4 logical CPUs",
    ]

    archive_path = tmp_path / "surface.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("copy.py", "TOOLTIP = f'Disponible con four threads'\n")
    assert [finding["literal"] for finding in scan_capacity_claims([archive_path])] == [
        "four threads"
    ]


def test_reconstruye_copy_visible_partido_por_markup(tmp_path: Path) -> None:
    html = tmp_path / "claim.html"
    html.write_text("<p><strong>4</strong> logical CPUs</p>", encoding="utf-8")
    markdown = tmp_path / "claim.md"
    markdown.write_text("Disponible con **4** logical CPUs.\n", encoding="utf-8")
    svg = tmp_path / "claim.svg"
    svg.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg"><text><tspan>8</tspan>'
        "<tspan> GiB RAM</tspan></text></svg>",
        encoding="utf-8",
    )
    assert [finding["literal"] for finding in scan_capacity_claims([html])] == ["4 logical CPUs"]
    assert [finding["literal"] for finding in scan_capacity_claims([markdown])] == [
        "4 logical CPUs"
    ]
    assert [finding["literal"] for finding in scan_capacity_claims([svg])] == ["8 GiB RAM"]


def test_censa_atributos_accesibles_html_svg_y_docx(tmp_path: Path) -> None:
    html = tmp_path / "accessible.html"
    html.write_text('<button aria-label="Disponible con 4 CPU"></button>', encoding="utf-8")
    svg = tmp_path / "accessible.svg"
    svg.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" aria-label="Requiere 8 GiB RAM"/>',
        encoding="utf-8",
    )
    docx = tmp_path / "accessible.docx"
    word = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    drawing = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
    with zipfile.ZipFile(docx, "w") as archive:
        archive.writestr(
            "word/document.xml",
            f'<w:document xmlns:w="{word}" xmlns:wp="{drawing}"><w:body><w:p>'
            "<w:r><w:t>Informe neutro</w:t></w:r>"
            '<wp:docPr id="1" name="Figura" descr="Disponible con four cores"/>'
            "</w:p></w:body></w:document>",
        )
    assert [finding["literal"] for finding in scan_capacity_claims([html])] == ["4 CPU"]
    assert [finding["literal"] for finding in scan_capacity_claims([svg])] == ["8 GiB RAM"]
    assert [finding["literal"] for finding in scan_capacity_claims([docx])] == ["four cores"]


def test_censo_bidireccional_detecta_archivo_raiz_nuevo_y_svg_publico(tmp_path: Path) -> None:
    install = tmp_path / "INSTALL.md"
    install.write_text("Funciona con 4 CPU.\n", encoding="utf-8")
    assets = tmp_path / "docs_site" / "assets"
    assets.mkdir(parents=True)
    svg = assets / "claim.svg"
    svg.write_text("<svg><text>Capacidad de 8 GB RAM</text></svg>\n", encoding="utf-8")
    report = tmp_path / "reports" / "summary.md"
    report.parent.mkdir()
    report.write_text("Informe sin claims de capacidad.\n", encoding="utf-8")
    bundle = tmp_path / "web" / "dist" / "assets" / "bundle.js"
    bundle.parent.mkdir(parents=True)
    bundle.write_text("export const capacity = null;\n", encoding="utf-8")
    paths = public_copy_paths(tmp_path)
    assert {path.relative_to(tmp_path).as_posix() for path in paths} == {
        "INSTALL.md",
        "docs_site/assets/claim.svg",
        "reports/summary.md",
        "web/dist/assets/bundle.js",
    }
    with pytest.raises(CopyGateError, match="target H9R publicado"):
        assert_no_h9r_capacity_copy(tmp_path)


def test_censo_publico_rechaza_symlink_o_junction_sin_leer_destino(tmp_path: Path) -> None:
    public = tmp_path / "docs_site"
    public.mkdir()
    external = tmp_path / "external"
    external.mkdir()
    (external / "claim.md").write_text("Capacidad entregada: 4 CPU.\n", encoding="utf-8")
    linked = public / "escape"
    try:
        os.symlink(external, linked, target_is_directory=True)
    except OSError:
        if sys.platform != "win32":
            pytest.skip("el host no permitió crear symlink de control")
        created = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(linked), str(external)],
            check=False,
            capture_output=True,
            text=True,
        )
        if created.returncode != 0:
            pytest.skip(f"el host no permitió crear junction de control: {created.stderr}")
    try:
        with pytest.raises(CopyGateError, match="symlink/reparse point"):
            public_copy_paths(tmp_path)
    finally:
        if linked.is_symlink():
            linked.unlink()
        elif os.path.lexists(linked):
            os.rmdir(linked)


def test_censo_publico_rechaza_hardlink_sin_leer_destino(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.md"
    source.write_text("texto público neutro", encoding="utf-8")
    public = tmp_path / "README.md"
    os.link(source, public)

    reads = 0
    original_read_text = Path.read_text

    def observed_read_text(path: Path, *args: object, **kwargs: object) -> str:
        nonlocal reads
        reads += 1
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", observed_read_text)
    with pytest.raises(CopyGateError, match="hardlink no permitido"):
        public_copy_paths(tmp_path)
    assert reads == 0


def test_scan_rechaza_replace_durante_lectura(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "README.md"
    replacement = tmp_path / "replacement.md"
    path.write_text("Texto público neutro.\n", encoding="utf-8")
    replacement.write_text("Capacidad entregada: 4 CPU.\n", encoding="utf-8")
    original_read = copy_gate_module._read_bound_public_bytes
    swapped = False

    def swap_after_read(
        candidate: Path,
        *,
        context: str,
    ) -> tuple[Path, bytes, os.stat_result]:
        nonlocal swapped
        result = original_read(candidate, context=context)
        if not swapped:
            swapped = True
            os.replace(replacement, path)
        return result

    monkeypatch.setattr(copy_gate_module, "_read_bound_public_bytes", swap_after_read)
    with pytest.raises(CopyGateError, match="cambió"):
        scan_capacity_claims([path])


def test_gate_repite_censo_y_rechaza_archivo_publico_nuevo(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    public = tmp_path / "docs_site"
    public.mkdir()
    (public / "a.md").write_text("Texto público neutro.\n", encoding="utf-8")
    original_scan = copy_gate_module.scan_capacity_claims

    def add_after_scan(paths: Iterable[Path]) -> list[dict[str, object]]:
        findings = original_scan(paths)
        (public / "z.md").write_text("Capacidad entregada: 4 CPU.\n", encoding="utf-8")
        return findings

    monkeypatch.setattr(copy_gate_module, "scan_capacity_claims", add_after_scan)
    with pytest.raises(CopyGateError, match="árbol de copy público cambió"):
        assert_no_h9r_capacity_copy(tmp_path)


def test_gate_repite_censo_despues_de_revalidar_identidades(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    public = tmp_path / "docs_site"
    public.mkdir()
    (public / "a.md").write_text("Texto público neutro.\n", encoding="utf-8")
    original_census = copy_gate_module.public_copy_paths
    calls = 0

    def add_after_second_census(root: Path) -> list[Path]:
        nonlocal calls
        calls += 1
        paths = original_census(root)
        if calls == 2:
            (public / "z.md").write_text(
                "Capacidad entregada: 4 CPU.\n",
                encoding="utf-8",
            )
        return paths

    monkeypatch.setattr(copy_gate_module, "public_copy_paths", add_after_second_census)
    with pytest.raises(CopyGateError, match="árbol de copy público cambió al cerrar"):
        assert_no_h9r_capacity_copy(tmp_path)


def test_zip_publico_censa_qmd_y_rechaza_entradas_inseguras(tmp_path: Path) -> None:
    report = tmp_path / "web" / "src" / "fixtures" / "demo" / "report.zip"
    report.parent.mkdir(parents=True)
    with zipfile.ZipFile(report, "w") as archive:
        archive.writestr("report.qmd", "Capacidad entregada: 4 CPU.\n")
        archive.writestr("figures/chart.svg", "<svg><text>Sin claim</text></svg>\n")
    assert report in public_copy_paths(tmp_path)
    findings = scan_capacity_claims([report])
    assert [finding["literal"] for finding in findings] == ["4 CPU"]

    unsafe = tmp_path / "web" / "unsafe.zip"
    with zipfile.ZipFile(unsafe, "w") as archive:
        archive.writestr("../escape.qmd", "Sin claim.\n")
    with pytest.raises(CopyGateError, match="ZIP público no se pudo censar"):
        scan_capacity_claims([unsafe])


def test_zip_publico_falla_ante_miembro_no_censable(tmp_path: Path) -> None:
    report = tmp_path / "report.zip"
    with zipfile.ZipFile(report, "w") as archive:
        archive.writestr("screenshot.png", b"not-a-real-png")
    with pytest.raises(CopyGateError, match="ZIP público no se pudo censar"):
        scan_capacity_claims([report])


def test_docx_censa_headers_footers_notas_y_comentarios(tmp_path: Path) -> None:
    path = tmp_path / "report.docx"
    namespace = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "word/document.xml",
            f'<w:document xmlns:w="{namespace}"><w:body><w:p><w:r>'
            "<w:t>Informe público</w:t></w:r></w:p></w:body></w:document>",
        )
        archive.writestr(
            "word/header1.xml",
            f'<w:hdr xmlns:w="{namespace}"><w:p><w:r>'
            "<w:t>Disponible con four logical cores</w:t></w:r></w:p></w:hdr>",
        )
        archive.writestr(
            "word/footer1.xml",
            f'<w:ftr xmlns:w="{namespace}"><w:p><w:r><w:t>Pie neutro</w:t></w:r></w:p></w:ftr>',
        )
        archive.writestr(
            "word/footnotes.xml",
            f'<w:footnotes xmlns:w="{namespace}"><w:footnote w:id="1"><w:p><w:r>'
            "<w:t>Nota neutra</w:t></w:r></w:p></w:footnote></w:footnotes>",
        )
        archive.writestr(
            "word/comments.xml",
            f'<w:comments xmlns:w="{namespace}"><w:comment w:id="0"><w:p><w:r>'
            "<w:t>Revisión: requiere 8G RAM</w:t></w:r></w:p></w:comment></w:comments>",
        )
        archive.writestr(
            "word/glossary/document.xml",
            f'<w:glossaryDocument xmlns:w="{namespace}"><w:docPart><w:docPartBody>'
            "<w:p><w:r><w:t>Disponible con 8 GB RAM</w:t></w:r></w:p>"
            "</w:docPartBody></w:docPart></w:glossaryDocument>",
        )
        archive.writestr(
            "word/split.xml",
            f'<w:document xmlns:w="{namespace}"><w:body><w:p>'
            "<w:r><w:t>8</w:t></w:r><w:r><w:t> GiB RAM</w:t></w:r>"
            "</w:p></w:body></w:document>",
        )
    findings = scan_capacity_claims([path])
    assert sorted(finding["literal"] for finding in findings) == [
        "8 GB RAM",
        "8 GiB RAM",
        "8G RAM",
        "four logical cores",
    ]


@pytest.mark.parametrize(
    ("namespace", "prefix", "tag"),
    [
        ("http://schemas.openxmlformats.org/drawingml/2006/main", "a", "t"),
        ("http://schemas.openxmlformats.org/officeDocument/2006/math", "m", "t"),
        ("http://schemas.openxmlformats.org/drawingml/2006/chart", "c", "v"),
    ],
)
def test_docx_censa_texto_visible_drawingml_y_math(
    tmp_path: Path,
    namespace: str,
    prefix: str,
    tag: str,
) -> None:
    path = tmp_path / f"visible-{prefix}.docx"
    word_namespace = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "word/document.xml",
            f'<w:document xmlns:w="{word_namespace}"><w:body><w:p><w:r>'
            "<w:t>Informe neutro</w:t></w:r></w:p></w:body></w:document>",
        )
        archive.writestr(
            f"word/visible-{prefix}.xml",
            f'<{prefix}:root xmlns:{prefix}="{namespace}">'
            f"<{prefix}:{tag}>Disponible con 4 CPU</{prefix}:{tag}></{prefix}:root>",
        )
    assert [finding["literal"] for finding in scan_capacity_claims([path])] == ["4 CPU"]


def test_docx_y_pdf_sin_texto_censable_fallan_cerrados(tmp_path: Path) -> None:
    docx = tmp_path / "empty.docx"
    with zipfile.ZipFile(docx, "w") as archive:
        archive.writestr(
            "word/document.xml",
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"/>',
        )
    with pytest.raises(CopyGateError, match="DOCX público no contiene texto censable"):
        scan_capacity_claims([docx])

    malformed = tmp_path / "malformed.docx"
    with zipfile.ZipFile(malformed, "w") as archive:
        archive.writestr("word/document.xml", "<w:document>")
    with pytest.raises(CopyGateError, match="DOCX público no se pudo censar"):
        scan_capacity_claims([malformed])

    from pypdf import PdfWriter

    pdf = tmp_path / "image-only-equivalent.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    with pdf.open("wb") as handle:
        writer.write(handle)
    with pytest.raises(CopyGateError, match="PDF público contiene una página sin texto"):
        scan_capacity_claims([pdf])

    from pypdf import PdfReader

    mixed = tmp_path / "mixed-text-blank.pdf"
    writer = PdfWriter()
    source_page = PdfReader(ROOT / "web/src/fixtures/demo/report-f1.pdf").pages[0]
    writer.add_page(source_page)
    writer.add_blank_page(width=100, height=100)
    with mixed.open("wb") as handle:
        writer.write(handle)
    with pytest.raises(CopyGateError, match="PDF público contiene una página sin texto"):
        scan_capacity_claims([mixed])


def test_docx_rechaza_altchunk_no_censable(tmp_path: Path) -> None:
    docx = tmp_path / "altchunk.docx"
    namespace = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    relationship = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    with zipfile.ZipFile(docx, "w") as archive:
        archive.writestr(
            "word/document.xml",
            f'<w:document xmlns:w="{namespace}" xmlns:r="{relationship}"><w:body>'
            "<w:p><w:r><w:t>Informe neutro</w:t></w:r></w:p>"
            '<w:altChunk r:id="chunk1"/></w:body></w:document>',
        )
        archive.writestr("word/afchunk1.html", "Disponible con 4 CPU")
    with pytest.raises(CopyGateError, match="DOCX público no se pudo censar"):
        scan_capacity_claims([docx])


def test_catalogo_documentado_reconcilia_sin_ejecutar_contratos() -> None:
    assert assert_documented_h9r_catalog(ROOT) == {
        "caps": 3,
        "geometries": 3,
        "classifications": 15,
        "flow_steps": 15,
    }


def test_catalogo_documentado_falla_ante_deriva(tmp_path: Path) -> None:
    contracts = tmp_path / "scripts/readiness_h9r/contracts.py"
    proposal = tmp_path / "docs/design/_PROPUESTA-CALIBRACION-H9R-PRE-START.md"
    contracts.parent.mkdir(parents=True)
    proposal.parent.mkdir(parents=True)
    shutil.copyfile(ROOT / "scripts/readiness_h9r/contracts.py", contracts)
    text = (ROOT / "docs/design/_PROPUESTA-CALIBRACION-H9R-PRE-START.md").read_text(
        encoding="utf-8"
    )
    proposal.write_text(text.replace("host_oom\n", "host_oom_derivado\n", 1), encoding="utf-8")
    with pytest.raises(CopyGateError, match="classifications"):
        assert_documented_h9r_catalog(tmp_path)


@pytest.mark.parametrize(
    ("original", "replacement", "message"),
    [
        ("return dimensions", "return {}", "_g dejó"),
        ("nikodym.h9r.", "nikodym.other.", "ADAPTER_IDS dejó"),
        (
            'return tuple(identity for identity in self.outputs if identity != "manifest")',
            "return ()",
            "expected_output_identities dejó",
        ),
        ("MIB: Final = 1024**2", "MIB: Final = 1000**2", "MIB/GIB dejaron"),
    ],
)
def test_catalogo_documentado_liga_helpers_runtime_por_ast(
    tmp_path: Path,
    original: str,
    replacement: str,
    message: str,
) -> None:
    contracts = tmp_path / "scripts/readiness_h9r/contracts.py"
    proposal = tmp_path / "docs/design/_PROPUESTA-CALIBRACION-H9R-PRE-START.md"
    contracts.parent.mkdir(parents=True)
    proposal.parent.mkdir(parents=True)
    source = (ROOT / "scripts/readiness_h9r/contracts.py").read_text(encoding="utf-8")
    assert original in source
    contracts.write_text(source.replace(original, replacement, 1), encoding="utf-8")
    shutil.copyfile(ROOT / "docs/design/_PROPUESTA-CALIBRACION-H9R-PRE-START.md", proposal)
    with pytest.raises(CopyGateError, match=message):
        assert_documented_h9r_catalog(tmp_path)


@pytest.mark.parametrize(
    ("original", "replacement"),
    [
        ("100.000\N{MULTIPLICATION SIGN}50", "100.001\N{MULTIPLICATION SIGN}50"),
        ("| W1 scoring train | 7.200 s |", "| W1 scoring train | 7.201 s |"),
        ("bundle, reglas, hashes, lineage", "bundle alterado, reglas, hashes, lineage"),
    ],
)
def test_catalogo_liga_secciones_humanas_aprobadas_al_espejo_json(
    tmp_path: Path,
    original: str,
    replacement: str,
) -> None:
    contracts = tmp_path / "scripts/readiness_h9r/contracts.py"
    proposal = tmp_path / "docs/design/_PROPUESTA-CALIBRACION-H9R-PRE-START.md"
    contracts.parent.mkdir(parents=True)
    proposal.parent.mkdir(parents=True)
    shutil.copyfile(ROOT / "scripts/readiness_h9r/contracts.py", contracts)
    text = (ROOT / "docs/design/_PROPUESTA-CALIBRACION-H9R-PRE-START.md").read_text(
        encoding="utf-8"
    )
    assert original in text
    proposal.write_text(text.replace(original, replacement, 1), encoding="utf-8")
    with pytest.raises(CopyGateError, match="sección aprobada"):
        assert_documented_h9r_catalog(tmp_path)


def test_catalogo_rechaza_fila_cap_duplicada(tmp_path: Path) -> None:
    contracts = tmp_path / "scripts/readiness_h9r/contracts.py"
    proposal = tmp_path / "docs/design/_PROPUESTA-CALIBRACION-H9R-PRE-START.md"
    contracts.parent.mkdir(parents=True)
    proposal.parent.mkdir(parents=True)
    shutil.copyfile(ROOT / "scripts/readiness_h9r/contracts.py", contracts)
    text = (ROOT / "docs/design/_PROPUESTA-CALIBRACION-H9R-PRE-START.md").read_text(
        encoding="utf-8"
    )
    row = "| `C4` | 4 GiB = 4.294.967.296 B | primer cap evaluado |"
    assert row in text
    proposal.write_text(text.replace(row, f"{row}\n{row}", 1), encoding="utf-8")
    with pytest.raises(CopyGateError, match="filas C4/C5/C6 únicas"):
        assert_documented_h9r_catalog(tmp_path)


@pytest.mark.parametrize(
    "mutation",
    [
        '\nCAPS = {"C4": 1, "C5": 2, "C6": 3}\n',
        "\nFLOW_SPECS = ()\n",
        '\nCAPS["C4"] = 1\n',
    ],
)
def test_catalogo_rechaza_rebinding_o_mutacion_tardia(
    tmp_path: Path,
    mutation: str,
) -> None:
    contracts = tmp_path / "scripts/readiness_h9r/contracts.py"
    proposal = tmp_path / "docs/design/_PROPUESTA-CALIBRACION-H9R-PRE-START.md"
    contracts.parent.mkdir(parents=True)
    proposal.parent.mkdir(parents=True)
    source = (ROOT / "scripts/readiness_h9r/contracts.py").read_text(encoding="utf-8")
    contracts.write_text(source + mutation, encoding="utf-8")
    shutil.copyfile(ROOT / "docs/design/_PROPUESTA-CALIBRACION-H9R-PRE-START.md", proposal)
    with pytest.raises(CopyGateError, match=r"rebindings|indirecto|alias top-level"):
        assert_documented_h9r_catalog(tmp_path)


@pytest.mark.parametrize(
    "mutation",
    [
        "\nalias = CAPS\nalias.update({'C4': 1})\n",
        "\nglobals()['MIB'] = 1\n",
        "\nFlowSpec.expected_output_identities = property(lambda self: ())\n",
        "\nobject.__setattr__(FLOW_SPECS[0], 'outputs', ())\n",
        "\ndef mutate():\n    CAPS['C4'] = 1\nmutate()\n",
        "\nCATALOG_NOTE = 'cambio no revisado'\n",
    ],
)
def test_catalogo_estatico_rechaza_semantica_indirecta_o_fuente_no_revisada(
    tmp_path: Path,
    mutation: str,
) -> None:
    contracts = tmp_path / "scripts/readiness_h9r/contracts.py"
    proposal = tmp_path / "docs/design/_PROPUESTA-CALIBRACION-H9R-PRE-START.md"
    contracts.parent.mkdir(parents=True)
    proposal.parent.mkdir(parents=True)
    contracts.write_text(
        (ROOT / "scripts/readiness_h9r/contracts.py").read_text(encoding="utf-8") + mutation,
        encoding="utf-8",
    )
    shutil.copyfile(ROOT / "docs/design/_PROPUESTA-CALIBRACION-H9R-PRE-START.md", proposal)
    with pytest.raises(CopyGateError):
        assert_documented_h9r_catalog(tmp_path)


@pytest.mark.parametrize(
    ("original", "replacement", "message"),
    [
        (
            '"deadline_seconds":7200.0',
            '"deadline_seconds":999.0,"deadline_seconds":7200.0',
            "duplica la clave JSON",
        ),
        ('[{"adapter_id"', '[ {"adapter_id"', "JSON canónico byte-exacto"),
    ],
)
def test_catalogo_documental_rechaza_json_duplicado_o_no_canonico(
    tmp_path: Path,
    original: str,
    replacement: str,
    message: str,
) -> None:
    contracts = tmp_path / "scripts/readiness_h9r/contracts.py"
    proposal = tmp_path / "docs/design/_PROPUESTA-CALIBRACION-H9R-PRE-START.md"
    contracts.parent.mkdir(parents=True)
    proposal.parent.mkdir(parents=True)
    shutil.copyfile(ROOT / "scripts/readiness_h9r/contracts.py", contracts)
    text = (ROOT / "docs/design/_PROPUESTA-CALIBRACION-H9R-PRE-START.md").read_text(
        encoding="utf-8"
    )
    assert original in text
    proposal.write_text(text.replace(original, replacement, 1), encoding="utf-8")
    with pytest.raises(CopyGateError, match=message):
        assert_documented_h9r_catalog(tmp_path)


def test_catalogo_runtime_reconcilia_objetos_importados_reales() -> None:
    from scripts.readiness_h9r.contracts import (
        ADAPTER_IDS,
        CAPS,
        CLASSIFICATIONS,
        FLOW_SPECS,
        GEOMETRY_IDS,
    )

    assert assert_documented_h9r_runtime_catalog(
        ROOT,
        caps=CAPS,
        geometry_ids=GEOMETRY_IDS,
        classifications=CLASSIFICATIONS,
        flow_specs=FLOW_SPECS,
        adapter_ids=ADAPTER_IDS,
    ) == {
        "caps": 3,
        "geometries": 3,
        "classifications": 15,
        "flow_steps": 15,
    }


@pytest.mark.parametrize("target_name", ["contracts", "proposal"])
def test_catalogo_documentado_rechaza_hardlinks_antes_de_parsear(
    tmp_path: Path,
    target_name: str,
) -> None:
    contracts = tmp_path / "scripts/readiness_h9r/contracts.py"
    proposal = tmp_path / "docs/design/_PROPUESTA-CALIBRACION-H9R-PRE-START.md"
    contracts.parent.mkdir(parents=True)
    proposal.parent.mkdir(parents=True)
    shutil.copyfile(ROOT / "scripts/readiness_h9r/contracts.py", contracts)
    shutil.copyfile(ROOT / "docs/design/_PROPUESTA-CALIBRACION-H9R-PRE-START.md", proposal)
    target = contracts if target_name == "contracts" else proposal
    alias = tmp_path / f"{target_name}.alias"
    os.link(target, alias)
    with pytest.raises(CopyGateError, match="hardlink"):
        assert_documented_h9r_catalog(tmp_path)


@pytest.mark.parametrize("target_name", ["contracts", "proposal"])
def test_catalogo_documentado_rechaza_replace_despues_de_leer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    target_name: str,
) -> None:
    contracts = tmp_path / "scripts/readiness_h9r/contracts.py"
    proposal = tmp_path / "docs/design/_PROPUESTA-CALIBRACION-H9R-PRE-START.md"
    contracts.parent.mkdir(parents=True)
    proposal.parent.mkdir(parents=True)
    shutil.copyfile(ROOT / "scripts/readiness_h9r/contracts.py", contracts)
    shutil.copyfile(ROOT / "docs/design/_PROPUESTA-CALIBRACION-H9R-PRE-START.md", proposal)
    target = contracts if target_name == "contracts" else proposal
    replacement = tmp_path / f"{target_name}.replacement"
    shutil.copyfile(target, replacement)
    original_read = copy_gate_module._read_bound_public_bytes
    swapped = False

    def swap_after_read(
        candidate: Path,
        *,
        context: str,
    ) -> tuple[Path, bytes, os.stat_result]:
        nonlocal swapped
        result = original_read(candidate, context=context)
        if candidate == target and not swapped:
            swapped = True
            os.replace(replacement, target)
        return result

    monkeypatch.setattr(copy_gate_module, "_read_bound_public_bytes", swap_after_read)
    with pytest.raises(CopyGateError, match="cambió de versión"):
        assert_documented_h9r_catalog(tmp_path)


def test_catalogo_documentado_revalida_ambas_fuentes_al_cierre(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contracts = tmp_path / "scripts/readiness_h9r/contracts.py"
    proposal = tmp_path / "docs/design/_PROPUESTA-CALIBRACION-H9R-PRE-START.md"
    contracts.parent.mkdir(parents=True)
    proposal.parent.mkdir(parents=True)
    shutil.copyfile(ROOT / "scripts/readiness_h9r/contracts.py", contracts)
    shutil.copyfile(ROOT / "docs/design/_PROPUESTA-CALIBRACION-H9R-PRE-START.md", proposal)
    replacement = tmp_path / "contracts.replacement"
    shutil.copyfile(contracts, replacement)
    original_document_catalog = copy_gate_module._document_catalog

    def swap_code_after_document(candidate: Path) -> dict[str, object]:
        result = original_document_catalog(candidate)
        os.replace(replacement, contracts)
        return result

    monkeypatch.setattr(copy_gate_module, "_document_catalog", swap_code_after_document)
    with pytest.raises(CopyGateError, match=r"código H9R al cierre conjunto.*cambió"):
        assert_documented_h9r_catalog(tmp_path)


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ('"deadline_seconds":7200.0', '"deadline_seconds":7201.0'),
        ('"rows":500000', '"rows":500001'),
        ('"adapter_id":"nikodym.h9r.score_train.train.v1"', '"adapter_id":"otro"'),
        ('"outputs":["bundle","rules","hashes","lineage"]', '"outputs":["bundle"]'),
    ],
)
def test_catalogo_documentado_cubre_deadline_geometria_adapter_y_outputs(
    tmp_path: Path, old: str, new: str
) -> None:
    contracts = tmp_path / "scripts/readiness_h9r/contracts.py"
    proposal = tmp_path / "docs/design/_PROPUESTA-CALIBRACION-H9R-PRE-START.md"
    contracts.parent.mkdir(parents=True)
    proposal.parent.mkdir(parents=True)
    shutil.copyfile(ROOT / "scripts/readiness_h9r/contracts.py", contracts)
    text = (ROOT / "docs/design/_PROPUESTA-CALIBRACION-H9R-PRE-START.md").read_text(
        encoding="utf-8"
    )
    assert old in text
    proposal.write_text(text.replace(old, new, 1), encoding="utf-8")
    with pytest.raises(CopyGateError, match="protocols"):
        assert_documented_h9r_catalog(tmp_path)
