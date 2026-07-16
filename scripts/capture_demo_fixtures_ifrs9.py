"""Captura —desde una corrida F4 REAL— los fixtures de la demo IFRS 9 / ECL (nuevos, no F3).

La demo pública (``VITE_DEMO_MODE=true``, servida sin backend) monta la app sobre fixtures
enlatados en ``web/src/fixtures/demo/``. Este script captura el set del preset ``f4-ifrs9-retail``
corriendo la cadena **de verdad** contra el backend, vía ``TestClient`` sobre
:func:`nikodym.ui.server.create_app` (no hace falta levantar ``uvicorn``).

**No sobrescribe el fixture F3** (``results.json``/``preset.json``/``toyaml.json`` de provisiones,
LIVE): escribe archivos NUEVOS con sufijo ``-ifrs9`` para que el front arme una demo multi-preset.
El preset F4 tiene el **report apagado**, así que este capture NO genera PDF/DOCX/HTML de informe
(evita WeasyPrint/nativas): solo ``results``/``preset``/``toyaml``.

**Regla de oro (R1 del SDD-28):** los fixtures salen de una corrida real, nunca inventados ni
editados a mano. Si un número no sale, se arregla la corrida (o el dataset/preset), no el fixture.
Por eso el script:

1. Captura los 3 fixtures **en memoria** desde una única corrida F4 (mismo ``run_id``).
2. **Verifica el número de negocio** IFRS 9 sobre el ``results`` capturado: coverage creíble
   (1-15 %), staging ``S1 > S2 > S3`` no vacío, y que ``staging_distribution`` RECONCILIE con la
   ``card`` (conteos y ECL reportada total).
3. Solo si la verificación pasa, **escribe** los 3 archivos (atómico: o salen los 3, o ninguno).
4. Re-verifica el **artefacto ya escrito**: ``provisioning_ifrs9`` NO es null, aparece >0 veces, y
   trae ``detail_sample`` con las tres etapas — se verifica lo que la demo servirá, no el código.

    GET  /api/config/preset/f4-ifrs9-retail          -> preset-ifrs9.json
    POST /api/run (preset f4) -> run_id ; GET /api/results/{run_id} -> results-ifrs9.json
    POST /api/config/to-yaml (config del preset f4)  -> toyaml-ifrs9.json

Uso (requiere el extra ``ui`` para ``starlette.testclient`` y ``scoring`` para OptBinning)::

    uv run --no-sync python scripts/capture_demo_fixtures_ifrs9.py
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

from nikodym.ui.server import create_app
from nikodym.ui.settings import UiConfig

if TYPE_CHECKING:
    from starlette.testclient import TestClient

PRESET_ID = "f4-ifrs9-retail"
_FIXTURES_DIR = Path(__file__).resolve().parent.parent / "web" / "src" / "fixtures" / "demo"
_COVERAGE_MIN, _COVERAGE_MAX = 0.01, 0.15  # rango creíble de retail (el ⚑ checkpoint del número)


def _get(client: TestClient, path: str) -> Any:
    """``GET path`` esperando 200; devuelve la respuesta o levanta con el detalle del fallo."""
    resp = client.get(path)
    if resp.status_code != 200:
        raise RuntimeError(f"GET {path} -> {resp.status_code}: {resp.text[:500]}")
    return resp


def _post(client: TestClient, path: str, payload: dict[str, Any]) -> Any:
    """``POST path`` (JSON) esperando 200; devuelve la respuesta o levanta con el detalle."""
    resp = client.post(path, json=payload)
    if resp.status_code != 200:
        raise RuntimeError(f"POST {path} -> {resp.status_code}: {resp.text[:500]}")
    return resp


def capture(client: TestClient) -> dict[str, Any]:
    """Corre el preset F4 real y devuelve los 3 fixtures en memoria (nada se escribe aún).

    Encadena run -> run_id -> results para que los 3 fixtures vengan de la **misma** corrida.
    Levanta si algún endpoint no responde 200 o si la corrida no termina en ``done``.
    """
    preset = _get(client, f"/api/config/preset/{PRESET_ID}").json()
    config = preset["config"]
    dataset_id = preset["dataset_id"]

    run = _post(client, "/api/run", {"config": config, "dataset_id": dataset_id}).json()
    status = run.get("status")
    if status != "done":
        raise RuntimeError(f"la corrida F4 no terminó en 'done' (status={status!r})")
    run_id = run["run_id"]

    results = _get(client, f"/api/results/{run_id}").json()
    toyaml = _post(client, "/api/config/to-yaml", {"config": config}).json()

    return {
        "run_id": run_id,
        "json": {
            "preset-ifrs9.json": preset,
            "results-ifrs9.json": results,
            "toyaml-ifrs9.json": toyaml,
        },
    }


def verify_business(results: dict[str, Any]) -> dict[str, float]:
    """Comprueba que el número IFRS 9 tiene sentido de NEGOCIO y que los agregados reconcilian.

    Solo se ve corriendo la cadena entera: la ECL sale de la term-structure lifetime (survival) y el
    staging por los backstops de mora. Estos asserts son esa guardia, sobre el fixture que la demo
    sirve.
    """
    block = results.get("provisioning_ifrs9")
    if not isinstance(block, dict):
        raise RuntimeError(
            "results-ifrs9.json no trae el bloque provisioning_ifrs9: la corrida F4 no lo produjo."
        )

    n_rows = int(block["n_rows"])
    n1, n2, n3 = int(block["n_stage1"]), int(block["n_stage2"]), int(block["n_stage3"])
    total_ead = float(block["total_ead"])
    total_ecl = float(block["total_ecl_reported"])
    coverage = total_ecl / total_ead if total_ead else 0.0

    assert n1 + n2 + n3 == n_rows, "los conteos por stage no cuadran con n_rows"
    assert n2 > 0 and n3 > 0, "el staging debe repartir en Stage 2 y 3 (no todo Stage 1)"
    assert n1 > n2 > n3, f"patrón de staging irreal: S1={n1} S2={n2} S3={n3} (se espera S1>S2>S3)"
    assert total_ecl > 0.0, "la ECL reportada total debe ser positiva"
    assert _COVERAGE_MIN <= coverage <= _COVERAGE_MAX, (
        f"coverage {coverage:.2%} fuera del rango creíble ({_COVERAGE_MIN:.0%}-{_COVERAGE_MAX:.0%})"
    )

    # La distribución de staging RECONCILIA con la card (conteos y ECL reportada total).
    dist = block["staging_distribution"]
    assert [row["stage"] for row in dist] == [1, 2, 3], (
        "staging_distribution incompleta o desordenada"
    )
    assert sum(int(row["n_rows"]) for row in dist) == n_rows, (
        "staging_distribution no cuadra n_rows"
    )
    ecl_dist = sum(float(row["total_ecl_reported"]) for row in dist)
    assert abs(ecl_dist - total_ecl) <= max(1e-6, 1e-9 * total_ecl), (
        f"staging_distribution ECL ({ecl_dist:,.0f}) no reconcilia con la card ({total_ecl:,.0f})"
    )

    # La muestra por operación trae las tres etapas (no solo Stage 3).
    sample_stages = {int(row["stage"]) for row in block["detail_sample"]}
    assert sample_stages == {1, 2, 3}, (
        f"detail_sample no cubre las tres etapas: {sorted(sample_stages)}"
    )

    return {
        "n_rows": float(n_rows),
        "n_stage1": float(n1),
        "n_stage2": float(n2),
        "n_stage3": float(n3),
        "total_ead": total_ead,
        "total_ecl_reported": total_ecl,
        "coverage": coverage,
    }


def write_fixtures(captured: dict[str, Any]) -> list[tuple[str, int]]:
    """Escribe los 3 fixtures a ``web/src/fixtures/demo/`` y devuelve ``[(nombre, tamaño), ...]``.

    Formato JSON idéntico al de los fixtures F3 (``indent=1``, ``ensure_ascii=False``, salto final)
    para un diff limpio. NO toca ningún fixture existente: solo los tres archivos ``-ifrs9``.
    """
    _FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    written: list[tuple[str, int]] = []
    for name, obj in captured["json"].items():
        path = _FIXTURES_DIR / name
        path.write_text(json.dumps(obj, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        written.append((name, path.stat().st_size))
    return written


def verify_artifacts() -> None:
    """Re-verifica el fixture YA escrito (verifica el artefacto, no el código que lo produjo).

    - ``results-ifrs9.json`` trae ``provisioning_ifrs9`` NO nulo y con las claves esperadas.
    - El literal ``provisioning_ifrs9`` aparece >0 veces (no se serializó a null en silencio).
    - ``detail_sample`` está y cubre las tres etapas.
    """
    raw = (_FIXTURES_DIR / "results-ifrs9.json").read_text(encoding="utf-8")
    assert raw.count("provisioning_ifrs9") > 0, "results-ifrs9.json no menciona provisioning_ifrs9"
    results = json.loads(raw)
    block = results.get("provisioning_ifrs9")
    assert isinstance(block, dict), (
        "provisioning_ifrs9 es null en el fixture escrito (¡no debería!)"
    )
    for key in (
        "staging_distribution",
        "summary",
        "ecl_term_structure",
        "sicr_triggers",
        "detail_sample",
    ):
        assert key in block, f"el fixture provisioning_ifrs9 no trae '{key}'"
    stages = {int(row["stage"]) for row in block["detail_sample"]}
    assert stages == {1, 2, 3}, (
        f"detail_sample del fixture no cubre las tres etapas: {sorted(stages)}"
    )


def main() -> None:
    """Captura, verifica el número, escribe los 3 fixtures y re-verifica el artefacto escrito."""
    with tempfile.TemporaryDirectory() as tmp:
        app = create_app(UiConfig(workdir=tmp))
        # Import perezoso: TestClient (starlette) vive en el extra [ui], como el resto del backend.
        from starlette.testclient import TestClient

        with TestClient(app) as client:
            captured = capture(client)

    numeros = verify_business(captured["json"]["results-ifrs9.json"])
    written = write_fixtures(captured)
    verify_artifacts()

    print(f"[capture] run_id={captured['run_id']}")
    print(
        f"[verify]  n_rows={int(numeros['n_rows'])} · "
        f"S1={int(numeros['n_stage1'])} S2={int(numeros['n_stage2'])} S3={int(numeros['n_stage3'])}"
    )
    print(
        f"[verify]  total_ead={numeros['total_ead']:,.0f} · "
        f"total_ecl_reported={numeros['total_ecl_reported']:,.0f} · "
        f"coverage={numeros['coverage']:.2%}"
    )
    print("[verify]  staging_distribution reconcilia con la card; detail_sample cubre S1/S2/S3 ✅")
    print(f"✅ {len(written)} fixtures escritos en {_FIXTURES_DIR.relative_to(Path.cwd())}:")
    for name, size in written:
        print(f"   {name:<22} {size / 1024:>8.1f} kB")


if __name__ == "__main__":
    main()
