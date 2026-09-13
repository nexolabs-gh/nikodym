"""Persistencia de corridas por ``run_id`` bajo el ``workdir`` (SDD-23 §4.3, §7, §9).

Cada corrida se persiste como su **payload ya serializado** (``results.json`` de
:func:`~nikodym.ui.serializers.serialize_study`) más, si la produjo, el HTML del reporte
(``report.html``). Se evita *pickle* del ``Study`` vivo (arrastra el stack ML y es frágil entre
versiones): se guarda solo lo que la UI necesita servir (decisión de implementación D-UI, §4.3).
La única tabla que el payload puede no traer entera es la tasa de incumplimiento por período o
cohorte —viaja hasta un tope, cierre 1 de D-SC—, y cuando se recorta la tabla completa queda al
lado, como ``eda_default_rate.csv``: el archivo existe **si y sólo si** la respuesta se recortó.

El ``run_id`` (``uuid4().hex`` que genera ``Study.run()``) es la clave de persistencia y compone
rutas, así que se **valida** contra su forma canónica (32 hex) y se verifica que la ruta resuelta
quede dentro de ``workdir/runs`` (mismo blindaje *path traversal* que ``datasets.materialize``): un
``run_id`` con separadores o ``..`` no puede escapar del directorio de trabajo.

**Qué es determinista aquí, dicho con precisión.** Lo son los **resultados de cálculo**: las cards
de dominio y sus frames ricos. No lo es la **procedencia**, y decir «el contenido persistido es
determinista (nada de reloj)» —como decía este docstring— era falso ya antes de D-LIN-1:

- ``run_id`` es un uuid, por diseño (§9).
- ``model_card.review_date`` y ``next_review_date`` salen de ``datetime.now(UTC)``
  (``governance/model_card.py``), así que **con gobernanza este archivo ya traía reloj**;
  ``environment`` describe la máquina que corrió.
- ``lineage.created_at`` se publica desde D-LIN-1; y ``git_sha``, ``git_dirty``,
  ``library_versions``, ``uv_lock_hash`` y ``determinism_caveats`` describen el árbol y el
  entorno, no el cálculo, así que dos corridas del mismo config en dos máquinas difieren en
  ellos legítimamente.

⚠️ **Corolario para quien compare dos corridas**: la comparación se hace sobre los resultados de
cálculo, **nunca** sobre el archivo entero. Un golden que congele todo `results.json` acusará
diferencias que no son diferencias. Lo fija un test que serializa dos veces el mismo ``Study`` y
exige que lo que varía esté dentro de esa lista — para que la lista no pueda quedarse corta en
silencio, que es justo lo que le pasó a la frase anterior.
"""

from __future__ import annotations

import io
import json
import re
import shutil
import tempfile
import uuid
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

from nikodym.core.spreadsheet_safety import neutralize_formula_prefixes
from nikodym.core.study import _missing_backup_path, _replace_path
from nikodym.ui.exceptions import UiError, UiRunNotFoundError
from nikodym.ui.serializers import eda_default_rate_frame, serialize_study

if TYPE_CHECKING:
    from nikodym.core.study import Study
    from nikodym.governance import GovernanceConfig

__all__ = [
    "asegurar_workdir",
    "eda_default_rate_path",
    "load_audit_trail",
    "load_report",
    "load_report_docx",
    "load_report_md",
    "load_report_md_bundle",
    "load_report_pdf",
    "load_results",
    "reservar_trail",
    "save",
]

# Contenido del veto que el workdir escribe sobre sí mismo. `*` se lee relativo al directorio que
# contiene el propio `.gitignore`, así que veta el workdir entero venga como venga su nombre.
_GITIGNORE_DEL_WORKDIR = """\
# Directorio de trabajo de la interfaz de Nikodym: datasets materializados y corridas.
# Lo escribe la propia interfaz al crearlo, para que arrancarla dentro de un repositorio no deje
# datos listos para commitear. El veto del `.gitignore` del repo cubre el nombre por defecto
# (`.nikodym_ui/`); esto cubre cualquier otro que se pase por `--workdir`.
*
"""

_RUN_ID_RE = re.compile(r"\A[0-9a-f]{32}\Z")  # forma canónica de ``uuid4().hex``
_RESULTS_FILENAME = "results.json"
_TRAIL_FILENAME = "audit_trail.jsonl"
_REPORT_FILENAME = "report.html"
_REPORT_PDF_FILENAME = "report.pdf"
_REPORT_MD_FILENAME = "report.qmd"
_REPORT_DOCX_FILENAME = "report.docx"
# La tasa por período o cohorte ENTERA, sólo cuando la respuesta la recortó (cierre 1 de D-SC).
_EDA_DEFAULT_RATE_FILENAME = "eda_default_rate.csv"
_REPORT_ARTIFACTS = (("report", "result"), ("report", "manifest"))
# Sufijo del directorio hermano de figuras del ``.qmd`` (lo fija ``nikodym.report.markdown``). Se
# replica aquí como convención de nombres —no como import— para no acoplar el backend al dominio.
_FIGURES_SUFFIX = "_figuras"


def asegurar_workdir(workdir: Path) -> Path:
    """Crea el ``workdir`` y lo deja **auto-vetado** para git; devuelve la ruta.

    El workdir nace donde se lance la interfaz, así que arrancarla dentro de un clon deja el parquet
    del dataset y el ``results.json`` de cada corrida a un ``git add .`` de distancia. El
    ``.gitignore`` del repo veta el nombre por defecto, pero no puede anticipar el que pase el
    usuario en ``--workdir``: por eso el veto se escribe **dentro** del directorio, que es lo que
    hacen las herramientas que generan caché local. No se sobrescribe si ya existe — el archivo pasa
    a ser del usuario en cuanto lo toca.
    """
    workdir.mkdir(parents=True, exist_ok=True)
    veto = workdir / ".gitignore"
    if not veto.exists():
        veto.write_text(_GITIGNORE_DEL_WORKDIR, encoding="utf-8")
    return workdir


def reservar_trail(workdir: Path) -> Path:
    """Reserva una ruta ABSOLUTA para el audit-trail antes de conocer el ``run_id`` (D-GOB-7).

    El ``run_id`` lo genera ``Study.run()``, así que no existe cuando hay que decirle al motor
    dónde escribir el trail. Se reserva un nombre único bajo ``workdir/runs`` y :func:`save` lo
    traslada a ``runs/<run_id>/audit_trail.jsonl`` en cuanto el ``run_id`` existe. Un trail
    huérfano —corrida que ni siquiera llegó a tener ``run_id``— se limpia allí mismo.
    """
    destino = asegurar_workdir(workdir) / "runs"
    destino.mkdir(parents=True, exist_ok=True)
    return (destino / f".trail-{uuid.uuid4().hex}.jsonl").resolve()


def load_audit_trail(run_id: str, *, workdir: Path) -> str | None:
    """Devuelve el JSONL del audit-trail de una corrida, o ``None`` si no existe."""
    trail = _run_dir(workdir, run_id) / _TRAIL_FILENAME
    if not trail.is_file():
        return None
    return trail.read_text(encoding="utf-8")


def save(
    study: Study,
    *,
    workdir: Path,
    governance: GovernanceConfig | None,
    trail: Path | None = None,
) -> str:
    """Guarda una corrida bajo ``workdir/runs/<run_id>/`` y devuelve el ``run_id`` (SDD-23 §7).

    Escribe ``results.json`` (payload de :func:`serialize_study`) y, si la corrida los produjo, el
    reporte HTML (``report.html``), su PDF (``report.pdf``) y las **fuentes editables**: el ``.qmd``
    de Quarto (``report.qmd``, con su directorio de figuras al lado, para que compile tal cual) y el
    ``.docx`` de Word (``report.docx``). Si el payload recortó la tasa por período o cohorte, la
    tabla completa va al lado como ``eda_default_rate.csv`` (:func:`_save_eda_default_rate`). Un
    ``Study`` sin ``run_id`` (no ejecutado) es un error de uso.

    **La corrida se publica entera o no se publica** (pasadas 3 y 4 de la revisión adversarial):
    todos los archivos se construyen en un hermano temporal ``.<run_id>.*.tmp`` de
    ``runs/<run_id>`` y el directorio se publica con un solo ``replace`` al final. Antes se
    escribía directamente en el destino, y un disco que se llenaba a mitad —el CSV grande, el
    JSON, un informe— dejaba una corrida a medias: servible con ``truncated: true`` sin su tabla, o
    con el archivo grande huérfano en un directorio que la UI no puede servir, acumulándose con
    cada reintento. Ante cualquier excepción el temporal se cierra sin dejar artefactos
    reproducibles atrás; sólo el trail —evidencia, no reproducible— se conserva en un hermano
    ``.<run_id>.failed.*`` anotado en la excepción (:func:`_apartar_corrida_fallida`). Son las
    primitivas de ``nikodym.run`` para su ``run_dir``, para que las dos políticas no diverjan.
    """
    run_id = study.run_context.run_id
    if run_id is None:
        if trail is not None:
            trail.unlink(missing_ok=True)  # trail huérfano: sin run_id no tiene dónde archivarse
        raise UiError(
            "no se puede persistir un Study sin run_id: ejecute run() antes de guardarlo."
        )
    asegurar_workdir(workdir)  # el veto de git se escribe también en el uso programático
    run_dir = _run_dir(workdir, run_id)
    run_dir.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{run_id}.", suffix=".tmp", dir=run_dir.parent))
    try:
        trail_final = _archivar_trail(trail, staging)
        payload = serialize_study(study, governance=governance, trail_path=trail_final)
        _save_eda_default_rate(study, payload, staging)
        (staging / _RESULTS_FILENAME).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8"
        )
        html = _report_html(study)
        if html is not None:
            (staging / _REPORT_FILENAME).write_text(html, encoding="utf-8")
        pdf = _report_pdf(study)
        if pdf is not None:
            (staging / _REPORT_PDF_FILENAME).write_bytes(pdf)
        _save_markdown(study, staging)
        docx = _report_artifact_bytes(study, "docx_path")
        if docx is not None:
            (staging / _REPORT_DOCX_FILENAME).write_bytes(docx)
        _publicar_corrida(staging, run_dir)
    except BaseException as exc:
        _apartar_corrida_fallida(staging, run_dir, exc)
        raise
    return run_id


def _publicar_corrida(staging: Path, run_dir: Path) -> None:
    """Sustituye ``run_dir`` por el temporal completo con un solo ``replace``.

    Un ``run_id`` es un uuid por corrida, así que un destino ya ocupado es una re-persistencia
    del mismo estudio; lo que hubiera no se mezcla ni se borra: se aparta a un hermano
    ``.<run_id>.old.*`` que se conserva —lleva un audit-trail, que es evidencia—, como hace
    ``nikodym.run`` con su ``run_dir``. Un destino vacío se retira, porque ``os.replace`` no pisa
    directorios en Windows.
    """
    if run_dir.exists():
        if any(run_dir.iterdir()):
            _replace_path(run_dir, _missing_backup_path(run_dir))
        else:
            run_dir.rmdir()
    _replace_path(staging, run_dir)


def _apartar_corrida_fallida(staging: Path, run_dir: Path, exc: BaseException) -> None:
    """Cierra el temporal de una corrida que no llegó a publicarse: sin artefactos, con su trail.

    Los archivos que ``save`` produce se reconstruyen desde el ``Study`` —y el CSV de la tasa es
    grande a propósito—: dejarlos en un directorio que la UI no sirve sólo consume disco con cada
    reintento. El trail no se reconstruye: es la evidencia de la corrida (SDD-03 §8) y se conserva
    como hermano ``.<run_id>.failed.*``, anotado en la excepción. Sin trail no queda rastro. Si el
    propio rescate falla —disco lleno, permisos—, el temporal se queda donde está y se anota ESA
    ruta: nunca se sustituye la excepción original.
    """
    conservada = staging
    try:
        for ruta in sorted(staging.rglob("*"), key=lambda p: len(p.parts), reverse=True):
            if ruta.name == _TRAIL_FILENAME and ruta.parent == staging:
                continue
            if ruta.is_dir():
                ruta.rmdir()
            else:
                ruta.unlink()
        trail = staging / _TRAIL_FILENAME
        if not trail.is_file() or trail.stat().st_size == 0:
            shutil.rmtree(staging, ignore_errors=True)
            return
        conservada = _missing_backup_path(run_dir, etiqueta="failed")
        _replace_path(staging, conservada)
    except OSError:
        conservada = staging
    exc.add_note(
        f"El audit-trail de la corrida que no se pudo persistir se conservó en '{conservada}'; "
        f"'{run_dir}' no se publicó."
    )


def _save_eda_default_rate(study: Study, payload: dict[str, Any], run_dir: Path) -> None:
    """Escribe la tasa por período o cohorte ENTERA si —y sólo si— el payload la recortó.

    El serializer publica hasta :data:`~nikodym.ui.serializers.EDA_MAX_PUBLISHED_PERIODS` filas y
    lo declara en ``eda.default_rate_window`` (cierre 1 de D-SC); la tabla completa es un artefacto
    del motor y aquí se conserva como archivo de la corrida, con las mismas columnas que la fila
    del payload y en el mismo orden, para que el panel pueda ofrecerla. Sin recorte no se
    duplica: ``results.json`` ya la trae entera. CSV UTF-8 con BOM y saltos LF, como los
    exports de datos del informe: byte-determinista y legible en Excel. Y como ellos, con las
    celdas de texto que una planilla leería como fórmula protegidas al exportar: la etiqueta de
    cohorte viene del archivo del usuario (:mod:`nikodym.core.spreadsheet_safety`).
    """
    eda = payload.get("eda")
    if not isinstance(eda, dict):
        return
    window = eda.get("default_rate_window")
    if not isinstance(window, dict) or not window.get("truncated"):
        return
    frame = eda_default_rate_frame(study)
    if frame is None:  # inalcanzable: la ventana sólo existe con el artefacto; no se fabrica
        return
    # `run_dir` es el temporal de `save`: un disco que se llena a medio camino no deja un CSV
    # parcial servible, porque la corrida entera se descarta sin publicarse.
    neutralize_formula_prefixes(frame).to_csv(
        run_dir / _EDA_DEFAULT_RATE_FILENAME,
        index=False,
        encoding="utf-8-sig",
        lineterminator="\n",
    )


def _archivar_trail(trail: Path | None, run_dir: Path) -> Path | None:
    """Traslada el trail reservado a ``<run_dir>/audit_trail.jsonl``; devuelve su ruta final.

    Es el paso que convierte el nombre provisional de :func:`reservar_trail` en la ubicación que
    SDD-03 §6 fija para el layout de la corrida. Un trail ausente —``audit`` apagado— no es un
    error: devuelve ``None`` y el model card sale sin decisiones, como antes.
    """
    if trail is None or not trail.is_file():
        return None
    destino = run_dir / _TRAIL_FILENAME
    shutil.move(str(trail), destino)
    return destino


def load_results(run_id: str, *, workdir: Path) -> dict[str, Any]:
    """Lee el JSON de resultados de una corrida; ``run_id`` desconocido → ``UiRunNotFoundError``."""
    results_path = _run_dir(workdir, run_id) / _RESULTS_FILENAME
    if not results_path.is_file():
        raise UiRunNotFoundError(f"no existe la corrida '{run_id}' bajo el directorio de trabajo.")
    loaded: dict[str, Any] = json.loads(results_path.read_text(encoding="utf-8"))
    return loaded


def eda_default_rate_path(run_id: str, *, workdir: Path) -> Path | None:
    """La ruta del CSV con la tasa por período o cohorte entera, o ``None`` si no existe (→ 404).

    Sólo existe cuando la respuesta la recortó (:func:`_save_eda_default_rate`); para una corrida
    sin recorte ``results.json`` ya trae la tabla completa, y no se fabrica ningún archivo al leer.
    Devuelve la RUTA y no los bytes a propósito: el archivo existe porque la tabla puede ser
    enorme, y el endpoint lo sirve por trozos (``FileResponse``) en vez de cargarlo entero en
    memoria dentro del event loop, que es lo que hacía la primera versión.
    """
    csv_path = _run_dir(workdir, run_id) / _EDA_DEFAULT_RATE_FILENAME
    if not csv_path.is_file():
        return None
    return csv_path


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

    El ``.qmd`` referencia las figuras por ruta relativa (``<basename>_figuras/*.svg``), así que
    descargarlo suelto entrega un documento con las imágenes rotas: la "base editable" solo sirve
    si viaja completa. El ZIP se arma en memoria y conserva la ruta relativa, de modo que al
    descomprimirlo ``quarto render`` compile tal cual, sin tocar nada.

    El directorio de figuras se busca **por lo que hay en disco**, no derivándolo del nombre del
    ``.qmd`` persistido: ``save`` normaliza el documento a ``report.qmd`` pero copia las figuras con
    el nombre que el propio documento cita (``<basename>_figuras``, y ``basename`` es configurable).
    Derivarlo del stem daba ``report_figuras``, que no existe: el ZIP salía sin una sola figura y el
    analista se bajaba el informe con las cinco imágenes rotas.
    """
    run_dir = _run_dir(workdir, run_id)
    md_path = run_dir / _REPORT_MD_FILENAME
    if not md_path.is_file():
        return None

    figure_dirs = sorted(
        path for path in run_dir.iterdir() if path.is_dir() and path.name.endswith(_FIGURES_SUFFIX)
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr(md_path.name, md_path.read_text(encoding="utf-8"))
        for figures_dir in figure_dirs:
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
