"""El Deploy no retrocede producción, no pierde un commit verde y no publica a ciegas.

🔴 Hallazgos de las pasadas 6, 7, 9 y 10 de la revisión adversarial de la 1.14.0: «sólo la punta de
main llega a producción» saltaba un CI verde apenas `main` avanzaba, sin mirar si la punta nueva
tenía CI verde o un Deploy propio (A verde, B pusheado y rojo: A terminaba en verde sin publicar y
B nunca desplegaba; producción se quedaba atrás sin una falla visible). La primera versión de la
regla nueva «fallaba abierta»: si la huella de producción no respondía, publicaba —justo el
retroceso que existe para impedir—. Y la segunda modelaba dos sitios como un solo commit (docs
sellada, demo a medias) y publicaba una ref fuera de `main` o un historial divergente sin `forzar`;
la tercera prometía que el rerun repara la partida y se detenía antes de mirar el commit.
La regla vive en `scripts/deploy_no_retroceder_produccion.py` y estos tests la fijan caso a caso
sobre una historia real base → A → B con su `origin`.
"""

from __future__ import annotations

import importlib.util
import io
import shutil
import subprocess
import sys
import urllib.error
from pathlib import Path
from types import ModuleType
from typing import Any, Final

import pytest

_RAIZ: Final = Path(__file__).resolve().parents[2]
_SCRIPT: Final = _RAIZ / "scripts" / "deploy_no_retroceder_produccion.py"
_WORKFLOW: Final = _RAIZ / ".github" / "workflows" / "deploy.yml"

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None or not _SCRIPT.exists() or not _WORKFLOW.exists(),
    reason="requiere git y el checkout del repositorio (no el sdist)",
)

Historia = tuple[Path, str, str, str]


def _cargar() -> ModuleType:
    spec = importlib.util.spec_from_file_location("deploy_no_retroceder_produccion", _SCRIPT)
    assert spec is not None and spec.loader is not None
    modulo = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = modulo  # `dataclasses` resuelve las anotaciones por `sys.modules`
    spec.loader.exec_module(modulo)
    return modulo


def _git(repo: Path, *args: str) -> str:
    proceso = subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t.invalid", *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return proceso.stdout.strip()


@pytest.fixture
def historia(tmp_path: Path) -> Historia:
    """Un repositorio con base → A → B en `main`, con un `origin` real al que hacer fetch."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    shas = []
    for nombre in ("base", "A", "B"):
        _git(repo, "commit", "-q", "--allow-empty", "-m", nombre)
        shas.append(_git(repo, "rev-parse", "HEAD"))
    origen = tmp_path / "origen.git"
    _git(repo, "init", "-q", "--bare", "-b", "main", str(origen))
    _git(repo, "remote", "add", "origin", str(origen))
    _git(repo, "push", "-q", "origin", "main")
    return repo, shas[0], shas[1], shas[2]


def _decidir(m: ModuleType, deploy: str, docs: Any, demo: Any, repo: Path) -> tuple[str, str]:
    decision, motivo = m.decidir(deploy, docs, demo, repo)
    return decision, motivo


# ── Lo que producción sirve, coherente en los dos sitios ──


def test_a_verde_con_b_rojo_publica_a(historia: Historia) -> None:
    """Producción sirve `base`; `main` ya está en B (rojo): A se publica igual."""
    repo, base, a, _b = historia
    m = _cargar()
    assert _decidir(m, a, m.Sello(sha=base), m.Sello(sha=base), repo)[0] == m.PUBLICAR


def test_no_retrocede_si_produccion_ya_sirve_un_descendiente(historia: Historia) -> None:
    repo, _base, a, b = historia
    m = _cargar()
    decision, motivo = _decidir(m, a, m.Sello(sha=b), m.Sello(sha=b), repo)
    assert decision == m.SALTAR and b[:7] in motivo and a[:7] in motivo


def test_el_mismo_commit_se_puede_republicar(historia: Historia) -> None:
    """Un rerun del Deploy que quedó a medias vuelve a publicar los dos sitios."""
    repo, _base, a, _b = historia
    m = _cargar()
    assert _decidir(m, a, m.Sello(sha=a), m.Sello(sha=a), repo)[0] == m.PUBLICAR


def test_sin_huella_en_ninguno_se_publica(historia: Historia) -> None:
    """Los sitios anteriores al sello responden 404: es el arranque, no un fallo."""
    repo, _base, a, _b = historia
    m = _cargar()
    assert _decidir(m, a, m.Sello(ausente=True), m.Sello(ausente=True), repo)[0] == m.PUBLICAR


def test_con_huella_en_un_solo_sitio_vale_esa(historia: Historia) -> None:
    """El primer Deploy que sella la demo encuentra docs sellada y demo sin huella: manda docs."""
    repo, base, a, b = historia
    m = _cargar()
    assert _decidir(m, a, m.Sello(sha=base), m.Sello(ausente=True), repo)[0] == m.PUBLICAR
    assert _decidir(m, a, m.Sello(sha=b), m.Sello(ausente=True), repo)[0] == m.SALTAR
    assert _decidir(m, a, m.Sello(ausente=True), m.Sello(sha=b), repo)[0] == m.SALTAR


# ── Todo lo que la regla no puede probar se detiene, en rojo ──


def test_una_huella_que_no_se_pudo_verificar_detiene(historia: Historia) -> None:
    """🔴 Pasada 7: sin huella legible NO se publica a ciegas —se detiene, en rojo—."""
    repo, base, a, _b = historia
    m = _cargar()
    decision, motivo = _decidir(m, a, m.Sello(), m.Sello(sha=base), repo)
    assert decision == m.DETENER and "docs" in motivo and "a ciegas" in motivo
    decision, motivo = _decidir(m, a, m.Sello(sha=base), m.Sello(), repo)
    assert decision == m.DETENER and "demo" in motivo


def test_produccion_partida_solo_la_repara_un_descendiente(historia: Historia) -> None:
    """🔴 Pasadas 9 y 10: docs en B y demo en A es una publicación a medias. Un ancestro (A) no la
    pisa —retrocedería docs—; el rerun de B, o cualquier descendiente, republica los DOS sitios."""
    repo, base, a, b = historia
    m = _cargar()
    decision, motivo = _decidir(m, a, m.Sello(sha=b), m.Sello(sha=a), repo)
    assert decision == m.DETENER and "partida" in motivo and b[:7] in motivo
    decision, motivo = _decidir(m, b, m.Sello(sha=b), m.Sello(sha=a), repo)
    assert decision == m.PUBLICAR and "los dos sitios" in motivo
    assert _decidir(m, b, m.Sello(sha=a), m.Sello(sha=base), repo)[0] == m.PUBLICAR
    # …pero no con un sitio divergente: eso sigue siendo a ciegas.
    _git(repo, "checkout", "-q", "-b", "otra", base)
    _git(repo, "commit", "-q", "--allow-empty", "-m", "otra")
    divergente = _git(repo, "rev-parse", "HEAD")
    assert _decidir(m, b, m.Sello(sha=b), m.Sello(sha=divergente), repo)[0] == m.DETENER


def test_una_huella_que_main_no_conoce_detiene(historia: Historia) -> None:
    """🔴 Pasada 9: un commit que `origin/main` no conoce no se pisa a ciegas."""
    repo, _base, a, _b = historia
    m = _cargar()
    decision, motivo = _decidir(m, a, m.Sello(sha="0" * 40), m.Sello(sha="0" * 40), repo)
    assert decision == m.DETENER and "no conoce" in motivo


def test_una_huella_divergente_detiene(historia: Historia) -> None:
    """🔴 Pasada 9: un commit conocido que ni desciende de A ni es su ancestro no se pisa."""
    repo, base, a, _b = historia
    _git(repo, "checkout", "-q", "-b", "otra", base)
    _git(repo, "commit", "-q", "--allow-empty", "-m", "otra")
    divergente = _git(repo, "rev-parse", "HEAD")
    m = _cargar()
    decision, motivo = _decidir(m, a, m.Sello(sha=divergente), m.Sello(sha=divergente), repo)
    assert decision == m.DETENER and "divergente" in motivo


def test_un_commit_fuera_de_main_detiene(historia: Historia) -> None:
    """🔴 Pasada 9: un `workflow_dispatch` desde otra rama no publica sin `forzar`."""
    repo, base, _a, _b = historia
    _git(repo, "checkout", "-q", "-b", "rama", base)
    _git(repo, "commit", "-q", "--allow-empty", "-m", "rama")
    fuera = _git(repo, "rev-parse", "HEAD")
    m = _cargar()
    decision, motivo = _decidir(m, fuera, m.Sello(sha=base), m.Sello(sha=base), repo)
    assert decision == m.DETENER and "no está en main" in motivo


def test_sin_remoto_detiene(historia: Historia) -> None:
    """Si no se puede traer `origin/main`, no hay cómo situar nada: se detiene."""
    repo, base, a, _b = historia
    _git(repo, "remote", "remove", "origin")
    m = _cargar()
    decision, motivo = _decidir(m, a, m.Sello(sha=base), m.Sello(sha=base), repo)
    assert decision == m.DETENER and "origin/main" in motivo


# ── `main()` como lo corre el Deploy ──


@pytest.fixture
def entorno_del_workflow(
    historia: Historia, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[ModuleType, Path, Path, Path, Historia]:
    """`DEPLOY_SHA`, las dos huellas por URL y `GITHUB_ENV`, sin reintentos ni esperas."""
    repo, _base, a, _b = historia
    docs = tmp_path / "docs-build-sha.txt"
    demo = tmp_path / "demo-build-sha.txt"
    env_file = tmp_path / "github.env"
    env_file.write_text("", encoding="utf-8")
    monkeypatch.setenv("DEPLOY_SHA", a)
    monkeypatch.setenv("SELLO_DOCS_URL", docs.resolve().as_uri())
    monkeypatch.setenv("SELLO_DEMO_URL", demo.resolve().as_uri())
    monkeypatch.setenv("GITHUB_ENV", str(env_file))
    monkeypatch.delenv("FORZAR", raising=False)
    monkeypatch.chdir(repo)
    modulo = _cargar()
    original = modulo.leer_sello
    monkeypatch.setattr(
        modulo, "leer_sello", lambda url: original(url, intentos=1, espera=0.0, timeout=2.0)
    )
    return modulo, docs, demo, env_file, historia


def test_main_deja_saltar_solo_cuando_produccion_va_adelante(
    entorno_del_workflow: tuple[ModuleType, Path, Path, Path, Historia],
) -> None:
    modulo, docs, demo, env_file, (_repo, base, _a, b) = entorno_del_workflow
    docs.write_text(b + "\n", encoding="utf-8")  # producción ya va adelante, coherente
    demo.write_text(b + "\n", encoding="utf-8")
    assert modulo.main() == 0
    assert env_file.read_text(encoding="utf-8") == "SALTAR=1\n"

    env_file.write_text("", encoding="utf-8")
    docs.write_text(base + "\n", encoding="utf-8")  # producción va atrás: se publica
    demo.write_text(base + "\n", encoding="utf-8")
    assert modulo.main() == 0
    assert env_file.read_text(encoding="utf-8") == ""


def test_main_se_detiene_en_rojo_y_forzar_publica(
    entorno_del_workflow: tuple[ModuleType, Path, Path, Path, Historia],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """🔴 Pasada 7: sin huella → exit 1 con `::error::` y sin `SALTAR`; con `forzar`, publica."""
    modulo, _docs, _demo, env_file, _historia = entorno_del_workflow  # sin archivos: ilegibles
    assert modulo.main() == 1
    assert "::error::" in capsys.readouterr().out
    assert env_file.read_text(encoding="utf-8") == ""

    monkeypatch.setenv("FORZAR", "true")
    assert modulo.main() == 0
    assert "::warning::" in capsys.readouterr().out
    assert env_file.read_text(encoding="utf-8") == ""


# ── La lectura de una huella ──


def test_leer_sello_distingue_404_de_no_verificable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    modulo = _cargar()
    rapido = {"intentos": 1, "espera": 0.0, "timeout": 2.0}
    # Sin servicio: no verificable (ni sha ni ausente).
    caido = modulo.leer_sello((tmp_path / "no-existe.txt").resolve().as_uri(), **rapido)
    assert caido.ilegible
    # Un cuerpo que no es un SHA (una portada de error): tampoco.
    basura = tmp_path / "basura.txt"
    basura.write_text("<html>Service Unavailable</html>", encoding="utf-8")
    assert modulo.leer_sello(basura.resolve().as_uri(), **rapido).ilegible
    # Un SHA completo: verificado.
    huella = tmp_path / "build-sha.txt"
    huella.write_text("a" * 40 + "\n", encoding="utf-8")
    assert modulo.leer_sello(huella.resolve().as_uri(), **rapido).sha == "a" * 40

    # Un 404 es «sin huella», no un fallo.
    def _404(*_args: Any, **_kwargs: Any) -> Any:
        raise urllib.error.HTTPError("https://x.invalid", 404, "Not Found", None, io.BytesIO())  # type: ignore[arg-type]

    monkeypatch.setattr(modulo.urllib.request, "urlopen", _404)
    ausente = modulo.leer_sello("https://x.invalid/build-sha.txt", **rapido)
    assert ausente.ausente and not ausente.ilegible

    # Un 503 NO es un 404: sigue siendo no verificable.
    def _503(*_args: Any, **_kwargs: Any) -> Any:
        raise urllib.error.HTTPError("https://x.invalid", 503, "Unavailable", None, io.BytesIO())  # type: ignore[arg-type]

    monkeypatch.setattr(modulo.urllib.request, "urlopen", _503)
    assert modulo.leer_sello("https://x.invalid/build-sha.txt", **rapido).ilegible


def test_leer_sello_reintenta_antes_de_rendirse(monkeypatch: pytest.MonkeyPatch) -> None:
    modulo = _cargar()
    llamadas: list[int] = []

    def _caido(*_args: Any, **_kwargs: Any) -> Any:
        llamadas.append(1)
        raise urllib.error.URLError("caído")

    monkeypatch.setattr(modulo.urllib.request, "urlopen", _caido)
    monkeypatch.setattr(modulo.time, "sleep", lambda _s: None)
    assert modulo.leer_sello("https://x.invalid/build-sha.txt", intentos=3, espera=0.0).ilegible
    assert len(llamadas) == 3


# ── El workflow ──


def test_el_workflow_aplica_la_regla_y_sella_los_dos_sitios() -> None:
    texto = _WORKFLOW.read_text(encoding="utf-8")
    llamada = "python3 scripts/deploy_no_retroceder_produccion.py"
    assert texto.count(llamada) == 2
    assert texto.index(llamada) < texto.index("- name: Setup uv")
    assert texto.rindex(llamada) < texto.index("- name: Publicar docs.nikodym.cl")
    assert "cancel-in-progress: false" in texto
    # El override explícito existe y llega al script; en un `workflow_run` vale `false`.
    assert "forzar:" in texto and "FORZAR: ${{ inputs.forzar || 'false' }}" in texto
    # Los DOS sitios se sellan con el mismo commit y el chequeo en vivo espera las dos huellas.
    assert "> docs_site/build-sha.txt" in texto and "> web/dist/build-sha.txt" in texto
    assert "https://demo.nikodym.cl/build-sha.txt" in texto
