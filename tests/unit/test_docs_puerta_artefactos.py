"""Gate ejecutable de la guía pública de inyección de artefactos (D-ART-10)."""

from __future__ import annotations

from pathlib import Path


def test_ejemplo_publicado_de_puerta_de_artefactos_es_ejecutable() -> None:
    """Extrae y ejecuta el bloque exacto: el sitio no puede documentar una API ficticia."""
    path = Path(__file__).resolve().parents[2] / "docs_site/guias/puerta-artefactos.md"
    text = path.read_text(encoding="utf-8")
    start = "<!-- artifact-gate-example:start -->\n```python\n"
    end = "\n```\n<!-- artifact-gate-example:end -->"

    assert text.count(start) == 1 and text.count(end) == 1
    code = text.split(start, maxsplit=1)[1].split(end, maxsplit=1)[0]

    exec(compile(code, str(path), "exec"), {"__name__": "__main__"})
