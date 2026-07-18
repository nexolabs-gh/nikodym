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

Dos modos, según el preset:

* **F1 scorecard (por defecto).** Sin argumentos —como lo llama el CI— corre el preset estándar de
  scorecard y verifica resultados, informe HTML y la base editable con sus figuras.
* **Preset explícito (p. ej. ``f4-ifrs9-retail``).** Con un ``preset_id`` por argumento CLI o por la
  variable de entorno ``NIKODYM_SMOKE_PRESET``, corre ese preset por la vía REST y —si es un preset
  IFRS 9— exige que ``provisioning_ifrs9`` salga con staging (Stage 1/2/3) y ECL/cobertura. Es el
  gate del wheel para la demo IFRS 9, que la ruta F1 no ejerce (usa ``survival``/``lifelines``,
  fuera del extra ``scoring``).

Uso (el CI lo llama con el intérprete de un venv donde ya instaló el wheel con pip)::

    python scripts/smoke_instalacion_pip.py                    # F1 scorecard (por defecto)
    python scripts/smoke_instalacion_pip.py f4-ifrs9-retail    # IFRS 9 / ECL
    NIKODYM_SMOKE_PRESET=f4-ifrs9-retail python scripts/smoke_instalacion_pip.py
"""

from __future__ import annotations

import io
import os
import re
import sys
import zipfile
from tempfile import mkdtemp
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from starlette.testclient import TestClient

_ENV_PRESET = "NIKODYM_SMOKE_PRESET"


def _banner_versiones() -> None:
    """Imprime la versión instalada de ``nikodym`` y de las libs de núcleo."""
    import nikodym

    print(f"nikodym instalado: {nikodym.__version__}")
    for paquete in ("pandas", "sklearn", "numpy"):
        modulo = __import__(paquete)
        print(f"  {paquete:8} {getattr(modulo, '__version__', '?')}")


def _crear_cliente() -> TestClient:
    """Levanta la app FastAPI sobre un ``TestClient`` (sin ``uvicorn``), con workdir temporal."""
    from fastapi.testclient import TestClient

    from nikodym.ui.server import create_app
    from nikodym.ui.settings import UiConfig

    return TestClient(create_app(UiConfig(workdir=mkdtemp(prefix="smoke-pip-"))))


def _smoke_f1(client: TestClient) -> list[str]:
    """Corre el preset estándar de scorecard (F1) y devuelve la lista de fallos (vacía si OK)."""
    fallos: list[str] = []

    preset = client.get("/api/config/preset")
    if preset.status_code != 200:
        return [f"GET /api/config/preset → {preset.status_code}"]
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
        return ["la corrida del preset F1 no terminó en 'done'"]

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

    return fallos


def _smoke_preset(client: TestClient, preset_id: str) -> list[str]:
    """Corre un preset explícito por REST y devuelve la lista de fallos (vacía si OK).

    Para un preset IFRS 9 (``ifrs9`` en el id) exige que ``provisioning_ifrs9`` salga NO nulo, con
    staging Stage 1/2/3 y ECL/cobertura — el núcleo de la demo IFRS 9. El informe (HTML/PDF) se
    consulta *best-effort*: el PDF depende de libs nativas de WeasyPrint, así que su ausencia NO
    tumba el smoke; el núcleo (ECL) debe salir igual.
    """
    fallos: list[str] = []

    preset = client.get(f"/api/config/preset/{preset_id}")
    if preset.status_code != 200:
        return [f"GET /api/config/preset/{preset_id} → {preset.status_code}: {preset.text[:300]}"]
    payload = preset.json()

    corrida = client.post(
        "/api/run",
        json={"config": payload["config"], "dataset_id": payload["dataset_id"]},
    )
    estado = corrida.json().get("status") if corrida.status_code == 200 else None
    print(f"\ncorrida del preset {preset_id!r}: {corrida.status_code} · {estado}")
    if estado != "done":
        print(f"FALLO: la corrida de {preset_id!r} no terminó en 'done'.")
        print(corrida.text[:600])
        return [f"la corrida del preset {preset_id!r} no terminó en 'done'"]

    run_id = corrida.json()["run_id"]

    resultados = client.get(f"/api/results/{run_id}")
    print(f"{'resultados':14} → {resultados.status_code}")
    if resultados.status_code != 200:
        return [f"resultados respondió {resultados.status_code}"]
    results = resultados.json()

    if "ifrs9" in preset_id.lower():
        fallos.extend(_verificar_ifrs9(results))

    # Informe: HTML como gate blando (Jinja2, sin libs nativas); PDF puramente informativo.
    informe = client.get(f"/api/report/{run_id}")
    print(f"{'informe HTML':14} → {informe.status_code}")
    if informe.status_code != 200:
        fallos.append(f"informe HTML respondió {informe.status_code}")
    pdf = client.get(f"/api/report/{run_id}/pdf")
    print(f"{'informe PDF':14} → {pdf.status_code} (best-effort; WeasyPrint/libs nativas)")

    return fallos


def _verificar_ifrs9(results: dict[str, object]) -> list[str]:
    """Verifica el bloque ``provisioning_ifrs9`` del ``results`` de una corrida F4.

    Exige NO nulo, staging Stage 1/2/3 con reparto (no todo en una etapa) y ECL positiva; imprime
    staging + ECL + cobertura. Devuelve la lista de fallos (vacía si el número tiene sentido).
    """
    fallos: list[str] = []
    block = results.get("provisioning_ifrs9")
    if not isinstance(block, dict):
        return ["provisioning_ifrs9 es null: la corrida IFRS 9 no produjo el bloque de ECL"]

    try:
        n1, n2, n3 = int(block["n_stage1"]), int(block["n_stage2"]), int(block["n_stage3"])
        total_ead = float(block["total_ead"])
        total_ecl = float(block["total_ecl_reported"])
    except (KeyError, TypeError, ValueError) as exc:
        return [f"provisioning_ifrs9 sin las claves de staging/ECL esperadas: {exc}"]

    coverage = total_ecl / total_ead if total_ead else 0.0
    print(
        f"  IFRS 9 · staging S1={n1:,} S2={n2:,} S3={n3:,} · "
        f"ECL={total_ecl:,.0f} · EAD={total_ead:,.0f} · cobertura={coverage:.2%}"
    )
    if not (n1 > 0 and n2 > 0 and n3 > 0):
        fallos.append(f"el staging no reparte en las tres etapas (S1={n1} S2={n2} S3={n3})")
    if total_ecl <= 0.0:
        fallos.append("la ECL reportada total no es positiva")
    if not (0.0 < coverage < 1.0):
        fallos.append(f"cobertura fuera de rango sano: {coverage:.2%}")

    dist = block.get("staging_distribution")
    if not (isinstance(dist, list) and [row.get("stage") for row in dist] == [1, 2, 3]):
        fallos.append("staging_distribution ausente, incompleta o desordenada (se espera 1/2/3)")

    return fallos


def main(preset_id: str | None = None) -> int:
    """Corre el smoke del preset indicado (F1 por defecto) y devuelve 0 solo si llega entero."""
    _banner_versiones()
    client = _crear_cliente()

    if preset_id:
        print(f"\n== modo preset explícito: {preset_id!r} ==")
        fallos = _smoke_preset(client, preset_id)
    else:
        print("\n== modo scorecard F1 (por defecto) ==")
        fallos = _smoke_f1(client)

    if fallos:
        print("\nFALLOS:")
        for fallo in fallos:
            print(f"  ✗ {fallo}")
        return 1

    print("\nOK: la instalación por pip corre el preset de punta a punta.")
    return 0


if __name__ == "__main__":
    preset_cli = sys.argv[1] if len(sys.argv) > 1 else os.environ.get(_ENV_PRESET) or None
    sys.exit(main(preset_cli))
