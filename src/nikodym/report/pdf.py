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
        Si WeasyPrint no está instalado. El import se hace dentro de la función para no romper el
        import liviano del paquete ``report``.
    """
    try:
        from weasyprint import HTML
    except ModuleNotFoundError as exc:
        raise ReportDependencyError(
            "No se pudo generar el PDF: falta WeasyPrint. Instale `nikodym[pdf]` y las librerías "
            "nativas Pango/HarfBuzz/libffi (ver docs) y reintente."
        ) from exc
    return cast(bytes, HTML(string=html, base_url=base_url).write_pdf())
