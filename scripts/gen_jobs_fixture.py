"""Regenera ``web/src/fixtures/jobs.json`` desde el catálogo REAL del backend (D-JOB-15).

El fixture es el snapshot de ``GET /api/jobs`` que el front usa como respaldo: la demo estática no
tiene backend al que preguntar, y en el instalable el catálogo debe existir aunque el backend no
responda —sin trabajos no hay por dónde entrar—. Es el mismo patrón que ``schema.json``, y por la
misma razón se genera con un script y no a mano: ese fixture se desincronizó en silencio durante
decenas de commits cuando dependía de que alguien se acordara.

Uso::

    uv run --no-sync python scripts/gen_jobs_fixture.py

No requiere extras: el catálogo es *domain-agnostic* (claves literales), así que no hay estado del
entorno que pueda degradarlo.
"""

from __future__ import annotations

import json
from pathlib import Path

from nikodym.ui.routes import jobs_payload

_FIXTURE = Path(__file__).resolve().parent.parent / "web" / "src" / "fixtures" / "jobs.json"


def main() -> None:
    """Escribe el fixture con el catálogo de trabajos actual."""
    payload = jobs_payload()
    if not payload["jobs"]:
        raise SystemExit("❌ el catálogo vino vacío: el fixture dejaría la landing sin entrada")
    _FIXTURE.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"✅ {_FIXTURE.name} regenerado ({_FIXTURE.stat().st_size / 1024:.1f} kB)")
    print(f"   trabajos: {len(payload['jobs'])}")


if __name__ == "__main__":
    main()
