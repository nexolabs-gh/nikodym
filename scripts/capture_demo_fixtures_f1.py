"""Captura —desde una corrida F1 REAL— los fixtures de la demo scorecard (nuevos, no F3 ni F4).

La demo pública (``VITE_DEMO_MODE=true``, servida sin backend) monta la app sobre fixtures
enlatados en ``web/src/fixtures/demo/``. Este script captura el set del preset
``f1-estandar-consumo`` —el **scorecard de comportamiento** puro
(data→binning→selection→model→scorecard→calibration→performance→stability→validation), SIN
provisiones— corriendo la cadena **de verdad** contra el backend, vía
:func:`nikodym.ui.server.create_app` sobre ``TestClient`` (sin ``uvicorn``).

**No sobrescribe los fixtures F3/F4** (``*.json``/``*-ifrs9.*``, LIVE): escribe archivos NUEVOS con
sufijo ``-f1`` para que el front arme una demo multi-preset. El preset F1 tiene el **report
ENCENDIDO** (los cuatro entregables), así que baja el informe completo, igual que F3/F4.

**Además recaptura el catálogo COMPARTIDO** ``datasets.json`` (el único fixture sin sufijo que
comparten los tres bundles). El fixture versionado hoy está *stale* (4 datasets, sin la cartera
IFRS 9): el preset F4 recomienda ``ifrs9_retail_latam`` —ya registrado en ``nikodym.ui.datasets``—
pero el catálogo enlatado no lo trae, así que la demo no lo lista. Este script lo refresca con la
salida real de ``GET /api/datasets``, que ya incluye ``ifrs9_retail_latam`` (n_rows 6.000).

**Regla de oro (R1 del SDD-28):** los fixtures salen de una corrida real, nunca inventados ni
editados a mano. Si un número no sale, se arregla la corrida (o el dataset/preset), no el fixture.
Por eso el script:

1. Captura los 7 fixtures ``-f1`` **en memoria** desde una única corrida F1 (mismo ``run_id``), más
   el catálogo compartido ``datasets.json``.
2. **Verifica las cifras insignia** del scorecard sobre el ``results`` capturado (patrón
   CAPTURAR-LUEGO-CONGELAR): discriminación AUC/Gini/KS por partición con sentido (identidad
   ``gini = 2·auc - 1``, desarrollo el más fuerte) y las CONGELA byte-a-byte (corrida determinista
   con ``PYTHONHASHSEED=0``). El scorecard NO produce provisiones: las cuatro cards de provisiones
   quedan nulas.
3. Solo si la verificación pasa, **escribe** los 8 archivos (atómico: o salen todos, o ninguno).
4. Re-verifica el **artefacto ya escrito**: ``scorecard``/``performance`` NO nulas, las cuatro cards
   de provisiones nulas, el ``report-f1.html`` titulado «Informe de Validación de Scorecard»
   (y NO el título IFRS 9), y el catálogo con ``ifrs9_retail_latam`` — se verifica lo que la demo
   servirá, no el código que lo produjo.

    GET  /api/datasets                              -> datasets.json (catálogo compartido)
    GET  /api/config/preset/f1-estandar-consumo      -> preset-f1.json
    POST /api/run (preset f1) -> run_id ; GET /api/results/{run_id} -> results-f1.json
    POST /api/config/to-yaml (config del preset f1)  -> toyaml-f1.json
    GET  /api/report/{run_id}                        -> report-f1.html
    GET  /api/report/{run_id}/pdf                    -> report-f1.pdf
    GET  /api/report/{run_id}/docx                   -> report-f1.docx
    GET  /api/report/{run_id}/md                     -> report-quarto-f1.zip

Uso (requiere los extras instalados —``ui``, ``scoring``, ``report``— y las libs nativas de
WeasyPrint; en macOS con Homebrew antepone ``DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib``)::

    DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib PYTHONHASHSEED=0 \
        uv run --no-sync python scripts/capture_demo_fixtures_f1.py
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

from nikodym.ui.server import create_app
from nikodym.ui.settings import UiConfig

if TYPE_CHECKING:
    from starlette.testclient import TestClient

PRESET_ID = "f1-estandar-consumo"
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_FIXTURES_DIR = _PROJECT_ROOT / "web" / "src" / "fixtures" / "demo"
_CAPTURE_WORKDIR_NAME = ".nikodym-demo-fixtures-f1"

# Título dinámico del renderer: la corrida F1 corre scorecard, así que el informe se titula como
# validación de scorecard (NO como el informe IFRS 9, que titula la cadena F4 sin scorecard).
_SCORECARD_TITLE = "Informe de Validación de Scorecard"
_IFRS9_TITLE = "Informe de Provisiones IFRS 9 / ECL"
_VALIDATION_TITLE = "Validación formal"
_DATA_TITLE = "Población, particiones y exclusiones"

# El catálogo compartido debe listar la cartera IFRS 9 (hoy el fixture versionado está stale y no la
# trae): el preset F4 la recomienda y sin ella la demo no la ofrece.
_EXPECTED_IFRS9_DATASET_ID = "ifrs9_retail_latam"
_EXPECTED_IFRS9_DATASET_ROWS = 6_000

# Freeze IBK-02 (CAPTURAR-LUEGO-CONGELAR): las cifras insignia del scorecard sobre
# ``consumo_comportamiento``, leídas de la corrida real y confirmadas idénticas en 2 corridas con
# ``PYTHONHASHSEED=0``. El capture no puede mover silenciosamente los números de la demo insignia.
_EXPECTED_N_VARIABLES = 5
_EXPECTED_DISCRIMINANT: dict[str, dict[str, float]] = {
    "desarrollo": {
        "n_total": 3_961,
        "n_bad": 924,
        "auc": 0.7123458941453674,
        "gini": 0.42469178829073484,
        "ks": 0.32014426688447106,
    },
    "holdout": {
        "n_total": 1_031,
        "n_bad": 244,
        "auc": 0.6946460932780636,
        "gini": 0.3892921865561272,
        "ks": 0.3118920157477034,
    },
    "oot": {
        "n_total": 1_008,
        "n_bad": 239,
        "auc": 0.6560957827097084,
        "gini": 0.31219156541941673,
        "ks": 0.25190569723218226,
    },
}
_PROVISIONING_KEYS = (
    "provisioning",
    "provisioning_cmf",
    "provisioning_internal",
    "provisioning_ifrs9",
)


@contextmanager
def _canonical_capture_workdir() -> Iterator[Path]:
    """Crea el workdir relativo estable, bloquea dos writers y siempre lo limpia.

    Igual que el capture F3: un ``workdir`` **relativo y canónico** bajo la raíz del checkout, para
    que ``data.load.source`` conserve el mismo identificador POSIX en macOS/Linux/Windows y no
    publique una ruta del host (``/var/folders/.../T/tmp...``) ni mueva el ``config_hash`` entre
    checkouts. El directorio se crea en exclusión mutua y se elimina aun si la corrida falla.
    """
    workdir = Path(_CAPTURE_WORKDIR_NAME)
    resolved = workdir.resolve()
    if resolved.parent != Path.cwd().resolve():  # defensa ante una edición futura del nombre
        raise RuntimeError(f"el workdir de captura escaparía del checkout: {resolved}")
    try:
        workdir.mkdir()
    except FileExistsError as exc:
        raise RuntimeError(
            f"el workdir canónico de captura ya existe: {workdir}. "
            "Comprueba que no haya otra captura activa y elimina el residuo de forma explícita."
        ) from exc
    try:
        yield workdir
    finally:
        # Limpia el target que validamos/creamos, aunque código interno haya cambiado el CWD.
        shutil.rmtree(resolved)


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
    """Corre el preset F1 real y devuelve, en memoria, los 7 fixtures ``-f1`` y el catálogo.

    Encadena run -> run_id -> results/report para que TODOS los fixtures ``-f1`` vengan de la
    **misma** corrida. Levanta si algún endpoint no responde 200 o si la corrida no termina en
    ``done``: el informe no es opcional en la demo, así que un PDF ausente (WeasyPrint sin libs
    nativas) debe reventar aquí, no descubrirse con un 404 en vivo.
    """
    # Catálogo compartido de datasets (mismo endpoint que sirve el backend real): se refresca para
    # que incluya ``ifrs9_retail_latam``, hoy ausente del fixture versionado.
    datasets = _get(client, "/api/datasets").json()

    preset = _get(client, f"/api/config/preset/{PRESET_ID}").json()
    config = preset["config"]
    dataset_id = preset["dataset_id"]

    run = _post(client, "/api/run", {"config": config, "dataset_id": dataset_id}).json()
    status = run.get("status")
    if status != "done":
        raise RuntimeError(f"la corrida F1 no terminó en 'done' (status={status!r})")
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
            "preset-f1.json": preset,
            "results-f1.json": results,
            "toyaml-f1.json": toyaml,
            # Catálogo COMPARTIDO (sin sufijo): lo consumen los tres bundles del front.
            "datasets.json": datasets,
        },
        "text": {"report-f1.html": report_html},
        "binary": {
            "report-f1.pdf": report_pdf,
            "report-f1.docx": report_docx,
            "report-quarto-f1.zip": report_quarto_zip,
        },
    }


def _assert_ifrs9_in_catalog(datasets: list[dict[str, Any]]) -> dict[str, Any]:
    """Comprueba que el catálogo lista ``ifrs9_retail_latam`` con ``n_rows`` 6.000; lo devuelve."""
    by_id = {ds.get("id"): ds for ds in datasets}
    ds = by_id.get(_EXPECTED_IFRS9_DATASET_ID)
    assert isinstance(ds, dict), (
        f"el catálogo no lista '{_EXPECTED_IFRS9_DATASET_ID}' (¿fixture stale sin recapturar?): "
        f"ids={sorted(by_id)}"
    )
    assert int(ds["n_rows"]) == _EXPECTED_IFRS9_DATASET_ROWS, (
        f"'{_EXPECTED_IFRS9_DATASET_ID}' trae n_rows={ds['n_rows']}, "
        f"se esperaba {_EXPECTED_IFRS9_DATASET_ROWS}"
    )
    return ds


def verify_business(results: dict[str, Any], datasets: list[dict[str, Any]]) -> dict[str, float]:
    """Comprueba las cifras insignia del scorecard y CONGELA los números de la demo insignia.

    Solo se ve corriendo la cadena entera: la discriminación (AUC/Gini/KS) sale del modelo ajustado
    sobre la partición real, no de un config. Estos asserts son esa guardia, sobre el fixture que la
    demo sirve: sanity de negocio (identidad ``gini = 2·auc - 1``, desarrollo el más fuerte, rango
    creíble de comportamiento) + freeze byte-a-byte de las cifras.
    """
    perf = results.get("performance")
    if not isinstance(perf, dict):
        raise RuntimeError(
            "results-f1.json no trae la card performance: la corrida F1 no la produjo."
        )
    discriminant = perf.get("discriminant")
    if not isinstance(discriminant, list) or not discriminant:
        raise RuntimeError(
            "results-f1.json no trae performance.discriminant (métricas por partición)."
        )
    by_part = {row["partition"]: row for row in discriminant}

    # Sanity de negocio por partición: la métrica está OK, los conteos cuadran y las cifras son
    # coherentes (Gini es la identidad de AUC; KS positivo; AUC en rango creíble de un scorecard de
    # comportamiento, no perfecto ni azaroso).
    for part in ("desarrollo", "holdout", "oot"):
        row = by_part[part]
        assert row["status"] == "ok", f"partición {part}: status inesperado {row['status']!r}"
        auc, gini, ks = float(row["auc"]), float(row["gini"]), float(row["ks"])
        assert int(row["n_bad"]) + int(row["n_good"]) == int(row["n_total"]), (
            f"partición {part}: n_bad + n_good != n_total"
        )
        assert 0.55 <= auc <= 0.90, f"partición {part}: AUC {auc:.4f} fuera del rango creíble"
        assert abs(gini - (2.0 * auc - 1.0)) <= 1e-9, (
            f"partición {part}: Gini {gini} no es la identidad 2·AUC-1"
        )
        assert 0.0 < ks < 1.0, f"partición {part}: KS {ks:.4f} fuera de (0, 1)"

    # Desarrollo debe ser la partición MÁS fuerte (no un patrón invertido que delataría fuga o
    # una corrida rota): AUC(desarrollo) >= holdout y >= oot.
    assert by_part["desarrollo"]["auc"] >= by_part["holdout"]["auc"], "AUC desarrollo < holdout"
    assert by_part["desarrollo"]["auc"] >= by_part["oot"]["auc"], "AUC desarrollo < oot"

    # El scorecard produjo variables (no un modelo vacío).
    scorecard = results.get("scorecard")
    assert isinstance(scorecard, dict), "results-f1.json no trae la card scorecard"
    n_variables = int(scorecard["n_variables"])
    assert n_variables > 0, "el scorecard no seleccionó ninguna variable"

    # El F1 es scorecard PURO: ninguna card de provisiones (ni la cadena IFRS 9) corrió.
    for key in _PROVISIONING_KEYS:
        assert results.get(key) is None, (
            f"results-f1.json trae '{key}' no nulo: el F1 no debe producir provisiones."
        )

    # Freeze byte-a-byte de las cifras insignia (CAPTURAR-LUEGO-CONGELAR).
    assert n_variables == _EXPECTED_N_VARIABLES
    for part, exp in _EXPECTED_DISCRIMINANT.items():
        row = by_part[part]
        assert int(row["n_total"]) == exp["n_total"], f"{part}: n_total movió"
        assert int(row["n_bad"]) == exp["n_bad"], f"{part}: n_bad movió"
        assert row["auc"] == exp["auc"], f"{part}: AUC movió ({row['auc']!r} != {exp['auc']!r})"
        assert row["gini"] == exp["gini"], f"{part}: Gini movió"
        assert row["ks"] == exp["ks"], f"{part}: KS movió"

    # El catálogo compartido debe traer la cartera IFRS 9 (el objetivo de recapturarlo).
    _assert_ifrs9_in_catalog(datasets)

    dev = by_part["desarrollo"]
    return {
        "n_variables": float(n_variables),
        "auc_dev": float(dev["auc"]),
        "gini_dev": float(dev["gini"]),
        "ks_dev": float(dev["ks"]),
        "auc_holdout": float(by_part["holdout"]["auc"]),
        "auc_oot": float(by_part["oot"]["auc"]),
    }


def write_fixtures(captured: dict[str, Any]) -> list[tuple[str, int]]:
    """Escribe los 8 fixtures a ``web/src/fixtures/demo/`` y devuelve ``[(nombre, tamaño), ...]``.

    Formato JSON idéntico al de los fixtures F3/F4 (``indent=1``, ``ensure_ascii=False``, salto
    final) para un diff limpio. NO toca ningún fixture ``-ifrs9`` ni los F3: solo los archivos
    ``-f1`` y el catálogo compartido ``datasets.json``.
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

    - ``results-f1.json`` trae ``scorecard`` y ``performance`` NO nulas, y las cuatro cards de
      provisiones NULAS (el F1 es scorecard puro).
    - ``preset-f1.json`` activa validation con discriminación, calibración y estabilidad.
    - ``report-f1.html`` se titula «Informe de Validación de Scorecard», incorpora data y la
      validación formal, y NO trae el título IFRS 9; los binarios no están vacíos.
    - ``datasets.json`` (catálogo compartido) lista ``ifrs9_retail_latam`` con ``n_rows`` 6.000.
    """
    raw = (_FIXTURES_DIR / "results-f1.json").read_text(encoding="utf-8")
    results = json.loads(raw)
    assert isinstance(results.get("scorecard"), dict), (
        "scorecard es null en el fixture escrito (¡no debería!)"
    )
    assert isinstance(results.get("performance"), dict), (
        "performance es null en el fixture escrito (¡no debería!)"
    )
    for key in _PROVISIONING_KEYS:
        assert results.get(key) is None, (
            f"'{key}' NO es null en results-f1.json: el F1 no debe traer provisiones."
        )

    preset = json.loads((_FIXTURES_DIR / "preset-f1.json").read_text(encoding="utf-8"))
    validation = preset["config"].get("validation")
    assert isinstance(validation, dict), "preset-f1.json no activa validation"
    assert validation["families"] == ["discrimination", "calibration", "stability"]
    assert validation["calibration"]["binomial_by_grade"] is False
    assert validation["backtesting"]["enabled"] is False

    html = (_FIXTURES_DIR / "report-f1.html").read_text(encoding="utf-8")
    assert html.count(_SCORECARD_TITLE) > 0, "report-f1.html no se titula como scorecard"
    assert f'<h1 class="cover-title">{_SCORECARD_TITLE}</h1>' in html, (
        "report-f1.html no trae el h1 de portada del informe de scorecard"
    )
    assert _IFRS9_TITLE not in html, (
        "report-f1.html trae el título IFRS 9: el título dinámico eligió el documento equivocado"
    )
    assert _DATA_TITLE in html, "report-f1.html no proyecta el DataCardSection"
    assert _VALIDATION_TITLE in html, "report-f1.html no trae el ValidationResult ejecutado"
    for name in ("report-f1.pdf", "report-f1.docx", "report-quarto-f1.zip"):
        size = (_FIXTURES_DIR / name).stat().st_size
        assert size > 1_000, f"{name} quedó sospechosamente chico ({size} bytes)"

    datasets = json.loads((_FIXTURES_DIR / "datasets.json").read_text(encoding="utf-8"))
    _assert_ifrs9_in_catalog(datasets)


def main() -> None:
    """Captura, verifica las cifras, escribe los 8 fixtures y re-verifica el artefacto escrito."""
    if Path.cwd().resolve() != _PROJECT_ROOT:
        raise RuntimeError(f"ejecuta la captura desde la raíz del repositorio: {_PROJECT_ROOT}")
    with _canonical_capture_workdir() as workdir:
        settings = UiConfig(workdir=str(workdir))
        app = create_app(settings)
        # Import perezoso: TestClient (starlette) vive en el extra [ui], como el resto del backend.
        from starlette.testclient import TestClient

        with TestClient(app) as client:
            captured = capture(client)

    numeros = verify_business(
        captured["json"]["results-f1.json"], captured["json"]["datasets.json"]
    )
    written = write_fixtures(captured)
    verify_artifacts()

    print(f"[capture] run_id={captured['run_id']}")
    print(
        f"[verify]  n_variables={int(numeros['n_variables'])} · "
        f"desarrollo AUC={numeros['auc_dev']:.4f} Gini={numeros['gini_dev']:.4f} "
        f"KS={numeros['ks_dev']:.4f}"
    )
    print(
        f"[verify]  AUC holdout={numeros['auc_holdout']:.4f} · oot={numeros['auc_oot']:.4f} "
        "(desarrollo es la partición más fuerte) ✅"
    )
    print(
        f"[verify]  catálogo compartido con '{_EXPECTED_IFRS9_DATASET_ID}' "
        f"(n_rows {_EXPECTED_IFRS9_DATASET_ROWS}) ✅"
    )
    print(f"✅ {len(written)} fixtures escritos en {_FIXTURES_DIR.relative_to(Path.cwd())}:")
    for name, size in written:
        print(f"   {name:<24} {size / 1024:>8.1f} kB")


if __name__ == "__main__":
    main()
