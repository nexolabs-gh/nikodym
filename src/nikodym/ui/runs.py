"""Persistencia de corridas por ``run_id`` bajo el ``workdir`` (SDD-23 §4.3, §7, §9).

Cada corrida se persiste como su **payload ya serializado** (``results.json`` de
:func:`~nikodym.ui.serializers.serialize_study`) más, si la produjo, el HTML del reporte
(``report.html``). Se evita *pickle* del ``Study`` vivo (arrastra el stack ML y es frágil entre
versiones): se guarda solo lo que la UI necesita servir (decisión de implementación D-UI, §4.3).

El ``run_id`` (``uuid4().hex`` que genera ``Study.run()``) es la clave de persistencia y compone
rutas, así que se **valida** contra su forma canónica (32 hex) y se verifica que la ruta resuelta
quede dentro de ``workdir/runs`` (mismo blindaje *path traversal* que ``datasets.materialize``): un
``run_id`` con separadores o ``..`` no puede escapar del directorio de trabajo. El contenido
persistido es determinista (nada de reloj); la única no-reproducibilidad es el ``run_id`` uuid, por
diseño (§9).
"""

from __future__ import annotations

import io
import json
import re
import shutil
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

from nikodym.ui.exceptions import UiError, UiRunNotFoundError
from nikodym.ui.serializers import serialize_study

if TYPE_CHECKING:
    from nikodym.core.study import Study
    from nikodym.governance import GovernanceConfig

__all__ = [
    "load_report",
    "load_report_docx",
    "load_report_md",
    "load_report_md_bundle",
    "load_report_pdf",
    "load_results",
    "save",
]

_RUN_ID_RE = re.compile(r"\A[0-9a-f]{32}\Z")  # forma canónica de ``uuid4().hex``
_RESULTS_FILENAME = "results.json"
_REPORT_FILENAME = "report.html"
_REPORT_PDF_FILENAME = "report.pdf"
_REPORT_MD_FILENAME = "report.qmd"
_REPORT_DOCX_FILENAME = "report.docx"
_REPORT_ARTIFACTS = (("report", "result"), ("report", "manifest"))
# Sufijo del directorio hermano de figuras del ``.qmd`` (lo fija ``nikodym.report.markdown``). Se
# replica aquí como convención de nombres —no como import— para no acoplar el backend al dominio.
_FIGURES_SUFFIX = "_figuras"


def save(study: Study, *, workdir: Path, governance: GovernanceConfig | None) -> str:
    """Guarda una corrida bajo ``workdir/runs/<run_id>/`` y devuelve el ``run_id`` (SDD-23 §7).

    Escribe ``results.json`` (payload de :func:`serialize_study`) y, si la corrida los produjo, el
    reporte HTML (``report.html``), su PDF (``report.pdf``) y las **fuentes editables**: el ``.qmd``
    de Quarto (``report.qmd``, con su directorio de figuras al lado, para que compile tal cual) y el
    ``.docx`` de Word (``report.docx``). Un ``Study`` sin ``run_id`` (no ejecutado) es un error de
    uso.
    """
    run_id = study.run_context.run_id
    if run_id is None:
        raise UiError(
            "no se puede persistir un Study sin run_id: ejecute run() antes de guardarlo."
        )
    run_dir = _run_dir(workdir, run_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    payload = serialize_study(study, governance=governance)
    (run_dir / _RESULTS_FILENAME).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8"
    )
    html = _report_html(study)
    if html is not None:
        (run_dir / _REPORT_FILENAME).write_text(html, encoding="utf-8")
    pdf = _report_pdf(study)
    if pdf is not None:
        (run_dir / _REPORT_PDF_FILENAME).write_bytes(pdf)
    _save_markdown(study, run_dir)
    docx = _report_artifact_bytes(study, "docx_path")
    if docx is not None:
        (run_dir / _REPORT_DOCX_FILENAME).write_bytes(docx)
    return run_id


def load_results(run_id: str, *, workdir: Path) -> dict[str, Any]:
    """Lee el JSON de resultados de una corrida; ``run_id`` desconocido → ``UiRunNotFoundError``."""
    results_path = _run_dir(workdir, run_id) / _RESULTS_FILENAME
    if not results_path.is_file():
        raise UiRunNotFoundError(f"no existe la corrida '{run_id}' bajo el directorio de trabajo.")
    loaded: dict[str, Any] = json.loads(results_path.read_text(encoding="utf-8"))
    return loaded


def load_report(run_id: str, *, workdir: Path) -> str | None:
    """Devuelve el HTML del reporte de una corrida, o ``None`` si no existe (→ 404)."""
    report_path = _run_dir(workdir, run_id) / _REPORT_FILENAME
    if not report_path.is_file():
        return None
    return report_path.read_text(encoding="utf-8")


def load_report_pdf(run_id: str, *, workdir: Path) -> bytes | None:
    """Devuelve los bytes del PDF del reporte de una corrida, o ``None`` si no existe (→ 404)."""
    pdf_path = _run_dir(workdir, run_id) / _REPORT_PDF_FILENAME
    if not pdf_path.is_file():
        return None
    return pdf_path.read_bytes()


def load_report_md(run_id: str, *, workdir: Path) -> str | None:
    """Devuelve el ``.qmd`` (fuente editable) del reporte de una corrida, o ``None`` (→ 404)."""
    md_path = _run_dir(workdir, run_id) / _REPORT_MD_FILENAME
    if not md_path.is_file():
        return None
    return md_path.read_text(encoding="utf-8")


def load_report_md_bundle(run_id: str, *, workdir: Path) -> bytes | None:
    """Empaqueta el ``.qmd`` con su directorio de figuras en un ZIP, o ``None`` (→ 404).

    El ``.qmd`` referencia las figuras por ruta relativa (``<nombre>_figuras/*.svg``), así que
    descargarlo suelto entrega un documento con las imágenes rotas: la "base editable" solo sirve
    si viaja completa. El ZIP se arma en memoria y conserva la ruta relativa, de modo que al
    descomprimirlo ``quarto render`` compile tal cual, sin tocar nada.
    """
    run_dir = _run_dir(workdir, run_id)
    md_path = run_dir / _REPORT_MD_FILENAME
    if not md_path.is_file():
        return None

    figures_dir = run_dir / f"{md_path.stem}{_FIGURES_SUFFIX}"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr(md_path.name, md_path.read_text(encoding="utf-8"))
        if figures_dir.is_dir():
            for figure in sorted(figures_dir.iterdir()):
                if figure.is_file():
                    bundle.writestr(f"{figures_dir.name}/{figure.name}", figure.read_bytes())
    return buffer.getvalue()


def load_report_docx(run_id: str, *, workdir: Path) -> bytes | None:
    """Devuelve los bytes del ``.docx`` (Word) del reporte de una corrida, o ``None`` (→ 404)."""
    docx_path = _run_dir(workdir, run_id) / _REPORT_DOCX_FILENAME
    if not docx_path.is_file():
        return None
    return docx_path.read_bytes()


def _run_dir(workdir: Path, run_id: str) -> Path:
    """Resuelve ``workdir/runs/<run_id>`` validando el id y bloqueando *path traversal*."""
    if _RUN_ID_RE.match(run_id) is None:
        raise UiRunNotFoundError(
            f"run_id '{run_id}' inválido: debe ser un uuid4 hexadecimal de 32 caracteres."
        )
    runs_root = (Path(workdir) / "runs").resolve()
    candidate = (runs_root / run_id).resolve()
    if candidate.parent != runs_root:
        raise UiRunNotFoundError(  # pragma: no cover - inalcanzable tras el regex (sin separadores)
            f"la ruta de la corrida '{run_id}' escaparía del directorio de trabajo."
        )
    return candidate


def _report_html(study: Study) -> str | None:
    """Extrae el HTML del reporte desde los artefactos ``report`` (duck-typed, sin importar report).

    Lee ``html_path`` (ruta al HTML en disco) del artefacto ``("report","result")`` o
    ``("report","manifest")``; si apunta a un archivo existente, devuelve su contenido, si no
    ``None``. El backend permanece *domain-agnostic*: no importa ``nikodym.report``.
    """
    for domain, key in _REPORT_ARTIFACTS:
        if not study.artifacts.has(domain, key):
            continue
        html_path = getattr(study.artifacts.get(domain, key), "html_path", None)
        if isinstance(html_path, str):
            path = Path(html_path)
            if path.is_file():
                return path.read_text(encoding="utf-8")
    return None


def _report_pdf(study: Study) -> bytes | None:
    """Extrae los bytes del PDF del reporte desde los artefactos ``report`` (duck-typed).

    Espejo de :func:`_report_html`: lee ``pdf_path`` (ruta al PDF en disco) del artefacto
    ``("report","result")`` o ``("report","manifest")``; si apunta a un archivo existente devuelve
    sus bytes, si no ``None``. El backend sigue *domain-agnostic*: no importa ``nikodym.report``.
    """
    return _report_artifact_bytes(study, "pdf_path")


def _save_markdown(study: Study, run_dir: Path) -> None:
    """Guarda el ``.qmd`` **con su directorio de figuras**: sin las figuras no compila.

    El ``.qmd`` referencia sus SVG con ruta relativa (``<basename>_figuras/…``), así que copiar sólo
    el texto entregaría una fuente rota. Se copia el directorio hermano completo, conservando su
    nombre —que es el que el archivo referencia—, y la corrida persistida queda autocontenida.
    """
    source = _report_artifact_path(study, "md_path")
    if source is None:
        return
    shutil.copyfile(source, run_dir / _REPORT_MD_FILENAME)
    figures = source.with_name(f"{source.stem}{_FIGURES_SUFFIX}")
    if figures.is_dir():
        shutil.copytree(figures, run_dir / figures.name, dirs_exist_ok=True)


def _report_artifact_path(study: Study, attribute: str) -> Path | None:
    """Resuelve una ruta publicada por el reporte (``pdf_path``/``md_path``/``docx_path``).

    Duck-typing puro: lee el atributo del artefacto ``("report","result")`` o
    ``("report","manifest")`` y devuelve el ``Path`` si existe en disco. El backend permanece
    *domain-agnostic*: no importa ``nikodym.report`` ni conoce sus DTOs.
    """
    for domain, key in _REPORT_ARTIFACTS:
        if not study.artifacts.has(domain, key):
            continue
        raw_path = getattr(study.artifacts.get(domain, key), attribute, None)
        if isinstance(raw_path, str):
            path = Path(raw_path)
            if path.is_file():
                return path
    return None


def _report_artifact_bytes(study: Study, attribute: str) -> bytes | None:
    """Lee los bytes del artefacto de reporte apuntado por ``attribute``, o ``None``."""
    path = _report_artifact_path(study, attribute)
    return path.read_bytes() if path is not None else None
