"""Regenera ``web/src/fixtures/schema.json`` desde el schema REAL del backend.

El fixture es el snapshot de ``GET /api/schema`` que la demo estática (``VITE_DEMO_MODE=true``)
sirve sin backend. Hasta ahora se regeneraba **a mano**, y se desincronizó en silencio durante
decenas de commits: llegó a pesar 64 kB contra los 259 kB del schema real, con nombres de ``$defs``
de otra generación. La demo mostraba un config viejo y nadie se enteraba.

Peor: cuando se corrigió el encuadre normativo del módulo ``provisioning`` (la regla del máximo es
estándar-vs-interno, no CMF-vs-IFRS 9), el texto viejo **siguió publicado en demo.nikodym.cl**
embebido en este fixture, aunque el código ya estaba corregido.

Uso::

    uv run --no-sync python scripts/gen_schema_fixture.py

Requiere los extras instalados (``uv sync --all-extras``): ``build_full_json_schema`` deja
**opacas** las secciones cuyo extra no esté presente, así que regenerarlo en un entorno mínimo
produciría un fixture degradado.
"""

from __future__ import annotations

import json
from pathlib import Path

from nikodym.core.config.schema import rama_objeto
from nikodym.core.study import _DOMAIN_CONFIG_CLASSES
from nikodym.ui.routes import schema_payload

_FIXTURE = Path(__file__).resolve().parent.parent / "web" / "src" / "fixtures" / "schema.json"


def main() -> None:
    """Escribe el fixture con el schema, los defaults y el orden de secciones actuales."""
    payload = schema_payload()
    # Solo se vigilan los dominios COMPUTACIONALES: son los que la UI edita y los únicos que
    # `build_full_json_schema` expande. Si uno sale opaco, es que su extra no está instalado y el
    # fixture saldría degradado. (Las secciones INFRA —audit, governance, tracking— y los escalares
    # —name, schema_version— nunca se expanden: no son un problema.)
    #
    # La opacidad se pregunta con `rama_objeto` y NO con `.get("properties")`: una sección expandida
    # es apagable, y por eso viaja como `anyOf: [<objeto>, {"type": "null"}]`. Preguntar por
    # `properties` en la raíz declararía opacos los 29 dominios y abortaría con el fixture correcto.
    propiedades = payload["json_schema"]["properties"]
    opacas = [
        dominio
        for dominio in _DOMAIN_CONFIG_CLASSES
        if dominio in propiedades
        and not (rama_objeto(propiedades[dominio]) or {}).get("properties")
    ]
    if opacas:
        print(f"⚠️  Dominios OPACOS (falta su extra): {opacas}")
        print("   Corre `uv sync --all-extras` y repite, o el fixture saldrá degradado.")
        raise SystemExit(1)

    _FIXTURE.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    tamano = _FIXTURE.stat().st_size
    print(f"✅ {_FIXTURE.relative_to(Path.cwd())} regenerado ({tamano / 1024:.0f} kB)")
    print(f"   secciones: {len(payload['json_schema']['properties'])}")


if __name__ == "__main__":
    main()
