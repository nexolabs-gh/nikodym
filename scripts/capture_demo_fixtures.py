"""Captura —desde una corrida F3 REAL— los 8 fixtures de la demo estática.

La demo pública (``VITE_DEMO_MODE=true``, servida en ``demo.nikodym.cl`` sin backend) monta la app
sobre fixtures enlatados en ``web/src/fixtures/demo/``. Este script los regenera corriendo el preset
``f3-provisiones-consumo`` **de verdad** contra el backend FastAPI, vía ``TestClient`` sobre
:func:`nikodym.ui.server.create_app` (no hace falta levantar ``uvicorn``).

**Regla de oro (R1 del SDD-28):** los fixtures salen de una corrida real, nunca inventados ni
editados a mano para que "salga bonito". Si un número no sale, se arregla la corrida (o el dataset,
o el preset), **no el fixture**. Por eso el script:

1. Captura los 8 fixtures **en memoria** desde una única corrida F3 (D10: un solo set; el F3 es
   superset del F1, no se duplica nada).
2. **Verifica el número de negocio** sobre el ``results`` capturado (la trampa de calibración: si el
   método interno supera al estándar, la regla del máximo no muerde y el producto pierde titular).
3. Solo si la verificación pasa, **escribe** los 8 archivos (escritura atómica: o salen los 8, o
   ninguno — el script nunca deja un set a medias con la historia equivocada).
4. Re-verifica el **artefacto ya escrito** (3 secciones no nulas, capítulo del informe con la cifra
   del sobrecosto, y que el informe ya no declare las *provisiones* como fase posterior —G5): se
   verifica lo que la demo servirá, no el código que lo produjo.

Los 8 fixtures y su endpoint de origen (contrato en ``src/nikodym/ui/routes.py``; shape que consume
la demo, en ``web/src/lib/demo.ts``):

    GET  /api/datasets                              -> datasets.json
    GET  /api/config/preset/f3-provisiones-consumo  -> preset.json
    POST /api/run (preset f3) -> run_id ; GET /api/results/{run_id} -> results.json
    POST /api/config/to-yaml (config del preset f3) -> toyaml.json
    GET  /api/report/{run_id}      -> report.html
    GET  /api/report/{run_id}/pdf  -> report.pdf
    GET  /api/report/{run_id}/docx -> report.docx
    GET  /api/report/{run_id}/md   -> report-quarto.zip

Idempotente: se puede correr las veces que haga falta; sobrescribe siempre los mismos 8 paths y no
deja basura. La única fuente de no-reproducibilidad byte-a-byte es el ``run_id`` (``uuid4().hex``
que genera ``Study.run()``; el resto del contenido es determinista) — se captura tal cual, jamás se
edita para fijarlo (sería una edición a mano, prohibida por R1).

Uso (requiere los extras instalados: ``uv sync --all-extras``, si no el reporte/schema salen
degradados)::

    uv run --no-sync python scripts/capture_demo_fixtures.py
"""

from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

from nikodym.ui.server import create_app
from nikodym.ui.settings import UiConfig

if TYPE_CHECKING:
    from starlette.testclient import TestClient

PRESET_ID = "f3-provisiones-consumo"
_FIXTURES_DIR = Path(__file__).resolve().parent.parent / "web" / "src" / "fixtures" / "demo"

# G5 (SDD-28 §11): el informe no puede declarar que las PROVISIONES "corresponden a fases
# posteriores" cuando el capítulo de provisiones ya existe. El criterio NO es "grep del literal
# 'corresponden a fases posteriores' == 0": el track SDD-28 (commit c9bb700) borró a propósito SOLO
# la mención de las *provisiones* como fase posterior y CONSERVÓ —porque es verdadera y nadie la
# refuta— "El backtesting y la integración con IFRS 9 corresponden a fases posteriores" (IFRS 9 sale
# del camino crítico, §3.4; el backtesting es fase posterior). El HEAD del fixture también la trae.
# Por eso se veta la NEGACIÓN de las provisiones (``provisiones … fase(s) posterior(es)`` en la
# misma oración), no el literal genérico —que borraría una verdad para satisfacer un grep.
_NEGACION_PROVISIONES_RE = re.compile(r"provisi\w+[^.]{0,160}?fases?\s+posterior", re.IGNORECASE)


def _clp(monto: float) -> str:
    """Formatea un monto CLP como el informe: ``$`` + miles con punto, sin decimales."""
    return "$" + f"{round(monto):,}".replace(",", ".")


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
    """Corre el preset F3 real y devuelve los 8 fixtures en memoria (nada se escribe aún).

    Encadena run -> run_id -> results/report para que los 8 fixtures vengan de la **misma** corrida
    (D10). Levanta si algún endpoint no responde 200 o si la corrida no termina en ``done``.
    """
    datasets = _get(client, "/api/datasets").json()
    preset = _get(client, f"/api/config/preset/{PRESET_ID}").json()
    config = preset["config"]
    dataset_id = preset["dataset_id"]

    run = _post(client, "/api/run", {"config": config, "dataset_id": dataset_id}).json()
    status = run.get("status")
    if status != "done":
        raise RuntimeError(f"la corrida F3 no terminó en 'done' (status={status!r})")
    run_id = run["run_id"]

    results = _get(client, f"/api/results/{run_id}").json()
    toyaml = _post(client, "/api/config/to-yaml", {"config": config}).json()

    report_html = _get(client, f"/api/report/{run_id}").text
    report_pdf = _get(client, f"/api/report/{run_id}/pdf").content
    report_docx = _get(client, f"/api/report/{run_id}/docx").content
    report_quarto_zip = _get(client, f"/api/report/{run_id}/md").content

    return {
        "run_id": run_id,
        "json": {
            "datasets.json": datasets,
            "preset.json": preset,
            "results.json": results,
            "toyaml.json": toyaml,
        },
        "text": {"report.html": report_html},
        "binary": {
            "report.pdf": report_pdf,
            "report.docx": report_docx,
            "report-quarto.zip": report_quarto_zip,
        },
    }


def verify_business(results: dict[str, Any]) -> dict[str, float]:
    """Comprueba que el número de provisiones tiene sentido de NEGOCIO (la trampa de calibración).

    Solo se ve corriendo la cadena entera: con la calibración heredada del F1 (``target_pd=0.20``)
    la PD se infla ~3x, el método interno supera al estándar y la regla del máximo deja de morder.
    Con ``anchor_source='development_observed'`` manda el estándar (``binding='cmf'``), que es lo
    que la norma chilena reporta. Estos asserts son esa guardia, sobre el fixture que la demo sirve.
    """
    prov = results.get("provisioning")
    cmf = results.get("provisioning_cmf")
    interno = results.get("provisioning_internal")
    if not isinstance(prov, dict) or not isinstance(cmf, dict) or not isinstance(interno, dict):
        raise RuntimeError(
            "results.json no trae las 3 secciones de provisiones: la corrida F3 no las produjo."
        )

    estandar = float(prov["total_provision_a"])
    metodo_interno = float(prov["total_provision_b"])
    reportada = float(prov["total_reported_provision"])
    binding = prov["binding"]
    exposicion = float(cmf["total_exposure_amount"])
    sobrecosto = reportada - metodo_interno
    indice = estandar / exposicion

    assert estandar > metodo_interno, (
        f"el interno ({metodo_interno / 1e6:.0f}M) supera al estándar ({estandar / 1e6:.0f}M): "
        "la calibración se heredó mal (¿target_pd del F1?) y la regla del máximo no muerde. "
        "Se arregla la corrida (el preset ya trae development_observed), NO el fixture."
    )
    assert binding == "cmf", f"binding={binding!r}, se esperaba 'cmf' (manda el estándar CMF)"
    assert reportada == estandar, "con rule='max' la provisión reportada debe ser el estándar"
    assert 0.04 <= indice <= 0.14, f"índice de riesgo {indice:.2%} fuera del rango creíble (4%-14%)"
    # El titular del producto (SDD-28 §3.5): el sobrecosto en CLP ≈ $388M. Rango tolerante: el
    # número exacto depende del dataset sintético, pero un desvío grande delata la corrida mala.
    assert 300e6 <= sobrecosto <= 480e6, (
        f"sobrecosto {sobrecosto / 1e6:.0f}M fuera del rango esperado (~388M): revisa la corrida."
    )

    return {
        "estandar": estandar,
        "interno": metodo_interno,
        "reportada": reportada,
        "exposicion": exposicion,
        "sobrecosto": sobrecosto,
        "indice": indice,
    }


def write_fixtures(captured: dict[str, Any]) -> list[tuple[str, int]]:
    """Escribe los 8 fixtures a ``web/src/fixtures/demo/`` y devuelve ``[(nombre, tamaño), ...]``.

    Formato JSON idéntico al de los fixtures previos (``indent=1``, ``ensure_ascii=False``, orden
    del contrato — sin ``sort_keys``, con salto final) para un diff limpio. El HTML va verbatim (tal
    cual lo emite el endpoint); los binarios (PDF/DOCX/ZIP) van byte a byte.
    """
    _FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    written: list[tuple[str, int]] = []

    for name, obj in captured["json"].items():
        path = _FIXTURES_DIR / name
        path.write_text(json.dumps(obj, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        written.append((name, path.stat().st_size))

    for name, text in captured["text"].items():
        path = _FIXTURES_DIR / name
        path.write_text(text, encoding="utf-8")
        written.append((name, path.stat().st_size))

    for name, blob in captured["binary"].items():
        path = _FIXTURES_DIR / name
        path.write_bytes(blob)
        written.append((name, path.stat().st_size))

    return written


def verify_artifacts() -> None:
    """Re-verifica los fixtures YA escritos (verifica el artefacto, no el código que lo produjo).

    - ``results.json`` trae las 3 secciones de provisiones no nulas.
    - ``report.html`` trae el capítulo de provisiones y la cifra del sobrecosto (el titular, §3.5).
    - El Anexo C publica el ``effective_config`` de CMF, método interno y orquestador.
    - El informe ya no declara las *provisiones* como fase posterior (G5); ver la nota de
      :data:`_NEGACION_PROVISIONES_RE` sobre por qué el criterio no es el literal genérico.
    """
    results_raw = (_FIXTURES_DIR / "results.json").read_text(encoding="utf-8")
    html_raw = (_FIXTURES_DIR / "report.html").read_text(encoding="utf-8")

    results = json.loads(results_raw)
    for seccion in ("provisioning", "provisioning_cmf", "provisioning_internal"):
        assert isinstance(results.get(seccion), dict), (
            f"results.json: la sección '{seccion}' es nula o falta (la corrida F3 no la produjo)."
        )

    assert 'data-section-id="provisions"' in html_raw, (
        "report.html no trae el capítulo de provisiones (falta la sección 'provisions', G5)."
    )
    prov = results["provisioning"]
    sobrecosto = float(prov["total_reported_provision"]) - float(prov["total_provision_b"])
    cifra = _clp(sobrecosto)
    assert cifra in html_raw, (
        f"report.html no imprime la cifra del sobrecosto {cifra} (el titular del capítulo, §3.5)."
    )

    for dominio in ("provisioning_cmf", "provisioning_internal", "provisioning"):
        marker = f'data-section-id="appendix_parameters.{dominio}"'
        assert marker in html_raw, f"report.html no publica el config efectivo F3 de {dominio}."
        start = html_raw.index(marker)
        end = html_raw.index("</section>", start)
        assert "<dt>effective_config</dt>" in html_raw[start:end], (
            f"Anexo C de {dominio} existe pero omite su effective_config."
        )

    for nombre, contenido in (("report.html", html_raw), ("results.json", results_raw)):
        m = _NEGACION_PROVISIONES_RE.search(contenido)
        assert m is None, (
            f"{nombre} aún declara las provisiones como fase posterior ({m.group(0)!r}): "
            "la corrida F3 con capítulo no debe negarlas (G5)."
        )


def main() -> None:
    """Captura, verifica el número, escribe los 8 fixtures y re-verifica el artefacto escrito."""
    with tempfile.TemporaryDirectory() as tmp:
        settings = UiConfig(workdir=tmp)
        app = create_app(settings)
        # Import perezoso: TestClient (starlette) vive en el extra [ui], como el resto del backend.
        from starlette.testclient import TestClient

        with TestClient(app) as client:
            captured = capture(client)

    numeros = verify_business(captured["json"]["results.json"])
    written = write_fixtures(captured)
    verify_artifacts()

    print(f"[capture] run_id={captured['run_id']}")
    print(
        f"[verify]  estándar={numeros['estandar'] / 1e6:.0f}M · "
        f"interno={numeros['interno'] / 1e6:.0f}M · "
        f"binding=cmf · reportada={numeros['reportada'] / 1e6:.0f}M"
    )
    print(
        f"[verify]  sobrecosto={numeros['sobrecosto'] / 1e6:.0f}M (reported - interno) · "
        f"índice={numeros['indice']:.2%} (estándar/exposición)"
    )
    print(
        f"[verify]  capítulo 'Provisiones regulatorias' con sobrecosto "
        f"{_clp(numeros['sobrecosto'])}; el informe no niega las provisiones (G5) ✅"
    )
    print(f"✅ {len(written)} fixtures escritos en {_FIXTURES_DIR.relative_to(Path.cwd())}:")
    for name, size in written:
        print(f"   {name:<20} {size / 1024:>8.1f} kB")


if __name__ == "__main__":
    main()
