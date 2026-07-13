"""Render de bajo nivel HTML→PDF vía WeasyPrint con import perezoso (SDD-26 §4/§7).

``render_pdf`` es la primitiva pura que convierte el HTML determinístico del reporte en bytes PDF
mediante WeasyPrint. El import de ``weasyprint`` es SIEMPRE perezoso (dentro de la función) para
preservar el import liviano del paquete ``report``: importar :mod:`nikodym.report` nunca debe
arrastrar WeasyPrint ni sus librerías nativas (Pango/HarfBuzz/libffi). El PDF NO es
byte-determinista —WeasyPrint embebe metadatos de creación en el binario— por lo que su verificación
es estructural (empieza con ``%PDF``, ≥1 página, texto extraíble), no por digest cross-OS.

**Experimental (fuera de la garantía SemVer 1.x).**
"""

from __future__ import annotations

from typing import cast

from nikodym.report.exceptions import ReportDependencyError

__all__ = ["render_pdf"]


def render_pdf(html: str, *, base_url: str | None = None) -> bytes:
    """Renderiza ``html`` a bytes PDF con WeasyPrint (import perezoso; SDD-26 §7).

    Parameters
    ----------
    html:
        Documento HTML standalone a convertir en PDF.
    base_url:
        Base opcional para resolver recursos relativos del HTML; ``None`` deja el default de
        WeasyPrint (sin resolución de rutas relativas externas).

    Returns
    -------
    bytes
        Contenido del PDF generado; empieza con ``%PDF``. No es byte-determinista entre corridas.

    Raises
    ------
    ReportDependencyError
        Si WeasyPrint no está instalado, o si lo está pero sus librerías NATIVAS
        (Pango/HarfBuzz/libffi) no se pueden cargar. Ambos son el mismo hecho para el llamador
        ("no hay PDF disponible aquí") y por eso comparten excepción: así
        ``PdfReportRenderer.write_pdf`` puede degradar con ``pdf.fail_if_unavailable=False`` en vez
        de tumbar la corrida entera.

        El caso de las nativas NO es exótico: ``pip install nikodym[pdf]`` trae el paquete de Python
        pero no las librerías del sistema, así que en un macOS o un Windows sin Pango el import
        levanta ``OSError``. Cuando eso escapaba crudo, una corrida que pedía PDF moría entera y el
        usuario perdía también el HTML, que sí se podía generar.
    """
    try:
        from weasyprint import HTML
    except ModuleNotFoundError as exc:
        raise ReportDependencyError(
            "No se pudo generar el PDF: falta WeasyPrint. Instale `nikodym[pdf]` y las librerías "
            "nativas Pango/HarfBuzz/libffi (ver docs) y reintente."
        ) from exc
    except OSError as exc:  # cffi/ctypes al cargar Pango, HarfBuzz o libffi
        raise ReportDependencyError(
            "No se pudo generar el PDF: WeasyPrint está instalado pero no encuentra sus librerías "
            "nativas (Pango/HarfBuzz/libffi). Instálelas en el sistema (ver docs) y reintente; el "
            f"resto del reporte no se ve afectado. Detalle: {exc}"
        ) from exc

    try:
        return cast(bytes, HTML(string=html, base_url=base_url).write_pdf())
    except OSError as exc:  # las nativas también pueden fallar al renderizar, no solo al importar
        raise ReportDependencyError(
            "No se pudo generar el PDF: WeasyPrint falló al usar sus librerías nativas "
            f"(Pango/HarfBuzz/libffi). Detalle: {exc}"
        ) from exc
