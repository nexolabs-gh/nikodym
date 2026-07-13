"""Smoke de la instalación REAL: lo que recibe quien hace ``pip install nikodym``.

Este script existe porque el CI puede estar entero en verde mientras el paquete publicado no
arranca. El CI corre con ``uv sync --locked``, es decir, con las versiones exactas del ``uv.lock``;
el usuario de PyPI no tiene ese lock: pip resuelve **libre** dentro de los rangos que declara el
wheel, y se lleva lo más nuevo que exista ese día. Cuando el mundo se mueve —una dependencia
publica un major que rompe a otra—, el lock nos protege a nosotros y a nadie más.

Ya pasó, y en serio: con ``nikodym`` 1.1.1 recién publicado, un ``pip install nikodym[scoring,ui]``
limpio traía ``scikit-learn`` 1.9 (que eliminó el ``force_all_finite`` que ``optbinning`` invoca) y
``pandas`` 3.0 (que hace fallar la serialización de resultados). La corrida del preset estándar
—el primer gesto de cualquier usuario nuevo— moría, en las tres versiones publicadas hasta
entonces, con el CI verde.

El smoke recorre la ruta COMPLETA hasta el usuario: instala, corre el preset y verifica que el
entregable llegue entero. No basta con que ``import nikodym`` funcione: importar siempre funciona.

Uso (el CI lo llama con el intérprete de un venv donde ya instaló el wheel con pip):

    python scripts/smoke_instalacion_pip.py
"""

from __future__ import annotations

import io
import re
import sys
import zipfile
from tempfile import mkdtemp


def main() -> int:
    """Corre el preset estándar contra la instalación viva y devuelve 0 solo si llega entero."""
    fallos: list[str] = []

    import nikodym

    print(f"nikodym instalado: {nikodym.__version__}")
    for paquete in ("pandas", "sklearn", "numpy"):
        modulo = __import__(paquete)
        print(f"  {paquete:8} {getattr(modulo, '__version__', '?')}")

    from fastapi.testclient import TestClient

    from nikodym.ui.server import create_app
    from nikodym.ui.settings import UiConfig

    client = TestClient(create_app(UiConfig(workdir=mkdtemp(prefix="smoke-pip-"))))

    preset = client.get("/api/config/preset")
    if preset.status_code != 200:
        print(f"FALLO: GET /api/config/preset → {preset.status_code}")
        return 1
    payload = preset.json()

    corrida = client.post(
        "/api/run",
        json={"config": payload["config"], "dataset_id": payload["dataset_id"]},
    )
    estado = corrida.json().get("status") if corrida.status_code == 200 else None
    print(f"\ncorrida del preset estándar: {corrida.status_code} · {estado}")
    if estado != "done":
        # El motor es fail-loud pero no explosivo: devuelve un Study parcial con status "failed" en
        # vez de reventar, así que un 200 aquí NO significa que la corrida haya salido bien.
        print("FALLO: la corrida del preset no terminó en 'done'.")
        print(corrida.text[:600])
        return 1

    run_id = corrida.json()["run_id"]

    for nombre, ruta in (
        ("resultados", f"/api/results/{run_id}"),
        ("informe HTML", f"/api/report/{run_id}"),
    ):
        respuesta = client.get(ruta)
        print(f"{nombre:14} → {respuesta.status_code}")
        if respuesta.status_code != 200:
            fallos.append(f"{nombre} respondió {respuesta.status_code}")

    # La base editable: el ZIP tiene que traer las figuras que su propio documento referencia, o el
    # analista se lleva un informe que no compila (el bug del 1.1.1).
    editable = client.get(f"/api/report/{run_id}/md")
    print(f"{'base editable':14} → {editable.status_code}")
    if editable.status_code != 200:
        fallos.append(f"la base editable respondió {editable.status_code}")
    else:
        with zipfile.ZipFile(io.BytesIO(editable.content)) as paquete:
            nombres = set(paquete.namelist())
            documento = paquete.read("report.qmd").decode("utf-8")
        referenciadas = set(re.findall(r"\]\(([^)]+_figuras/[^)]+)\)", documento))
        faltantes = referenciadas - nombres
        print(f"  figuras: {len(referenciadas)} referenciadas · {len(faltantes)} faltantes")
        if not referenciadas:
            fallos.append("el documento editable no referencia ninguna figura")
        if faltantes:
            fallos.append(f"el ZIP no lleva las figuras que el documento cita: {sorted(faltantes)}")

    if fallos:
        print("\nFALLOS:")
        for fallo in fallos:
            print(f"  ✗ {fallo}")
        return 1

    print("\nOK: la instalación por pip corre el preset de punta a punta.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
