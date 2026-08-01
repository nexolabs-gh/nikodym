"""Gate del veto de datos: en un repo público, un dataset no se sube «por si acaso».

`AGENTS.md` afirma que el `.gitignore` veta datos y secretos por defecto por ser un proyecto
regulatorio. Hasta el 2026-07-25 esa afirmación era **falsa** para el directorio `data/`: su patrón
llevaba el comentario en la misma línea, y en `.gitignore` el `#` sólo abre comentario al principio
de la línea. El patrón real era el nombre literal ``/data/ # datasets en la raíz (…)``, que no
existe, así que el veto llevaba inerte desde que se escribió. Se descubrió al bajar el primer
dataset externo real: `git status` lo ofreció para commitear.

Por eso el gate no lee el `.gitignore` buscando la línea: le pregunta a git. Un patrón que *parece*
correcto y no ignora nada es exactamente el defecto que motivó este archivo.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from nikodym.ui.runs import asegurar_workdir

_RAIZ = Path(__file__).resolve().parents[2]

#: Extensiones que traen los datasets externos reales. La lista nació de bajar datos de verdad: el
#: veto original cubría lo que *produce* el proyecto (`.csv`, `.parquet`, `.xlsx`) y dejaba fuera lo
#: que traen UCI, Kaggle y los repositorios públicos (`.data`, `.zip`, `.jsonl`, `.sqlite`).
_EXTENSIONES_DE_DATOS = (
    "csv",
    "tsv",
    "psv",
    "parquet",
    "xlsx",
    "xls",
    "feather",
    "arrow",
    "orc",
    "dta",
    "sav",
    "data",
    "jsonl",
    "ndjson",
    "db",
    "sqlite",
    "sqlite3",
    "h5",
    "hdf5",
    "pkl",
    "pickle",
    "zip",
    "gz",
    "tar",
)


def _ignorado(ruta: str) -> bool:
    """Le pregunta a git, que es la única autoridad sobre lo que ignora."""
    return (
        subprocess.run(
            ["git", "check-ignore", "-q", "--no-index", ruta],
            cwd=_RAIZ,
            capture_output=True,
            check=False,
        ).returncode
        == 0
    )


def test_git_responde_en_este_arbol() -> None:
    """Sin esto, un entorno sin git dejaría todo el gate en verde sin comprobar nada."""
    completado = subprocess.run(
        ["git", "rev-parse", "--is-inside-work-tree"],
        cwd=_RAIZ,
        capture_output=True,
        check=False,
    )
    assert completado.returncode == 0, "el gate exige un árbol git para preguntar por los vetos"


@pytest.mark.parametrize("extension", _EXTENSIONES_DE_DATOS)
def test_un_dato_bajo_data_no_se_puede_commitear(extension: str) -> None:
    """La ruta donde de verdad aterrizan los datasets externos que se descargan."""
    assert _ignorado(f"data/externos/cartera.{extension}")


@pytest.mark.parametrize("extension", ("csv", "parquet", "xlsx", "xls", "dta", "sav"))
def test_un_dato_fuera_de_data_tampoco(extension: str) -> None:
    """Un dataset no deja de ser un dataset por vivir en otra carpeta."""
    assert _ignorado(f"notebooks/exploracion/cartera.{extension}")


def test_el_paquete_fuente_sigue_versionandose() -> None:
    """El veto va anclado con `/` justamente para no tragarse `src/nikodym/data/` (SDD-02)."""
    assert not _ignorado("src/nikodym/data/config.py")


def test_los_fixtures_comprimidos_de_la_demo_siguen_versionandose() -> None:
    """El error simétrico, y el más caro: un veto global de `*.zip` deja la demo stale en silencio.

    `web/src/fixtures/demo/*.zip` son artefactos versionados. Si el veto los alcanzara, la próxima
    recaptura no los añadiría, nadie lo notaría —git no avisa de lo que ignora— y el bundle
    publicado quedaría atrás del fixture.
    """
    assert not _ignorado("web/src/fixtures/demo/report-quarto-f1.zip")


def test_el_catalogo_de_datasets_sigue_versionandose() -> None:
    """El catálogo documenta con qué datos reales se valida la librería; no es un dataset.

    Vive en `docs/datasets/catalogo.csv` y cae de lleno bajo el veto global de `*.csv`. Sin la
    excepción explícita, `git add` lo ignoraría sin decir nada y la documentación del requisito 2 de
    la visión —validar contra datos externos y sucios— se perdería en silencio en el próximo clon.
    """
    assert not _ignorado("docs/datasets/catalogo.csv")


@pytest.mark.parametrize("extension", ("csv", "parquet", "zip", "gz", "xlsx"))
def test_lo_que_bajaria_el_gestor_en_su_ubicacion_versionada_esta_vetado(extension: str) -> None:
    """`descargar.sh` resuelve `raw/` relativo al script, y vive versionado en `docs/datasets/`.

    Se ejecuta desde `data/externos/`, donde es un symlink; pero basta que alguien lo invoque desde
    su ubicación real para que gigabytes de datos externos aterricen en un directorio que sí se
    commitea, en un repo público.
    """
    assert _ignorado(f"docs/datasets/raw/scorecard/cartera.{extension}")


def test_un_dataset_junto_al_catalogo_sigue_vetado() -> None:
    """El error simétrico de la excepción anterior: reincluir la carpeta entera, no un archivo.

    La excepción es de un único fichero por su ruta completa. Si alguien la relajara a
    `!/docs/datasets/`, cualquier dato que aterrizara ahí entraría al repo público.
    """
    assert _ignorado("docs/datasets/cartera.csv")


def test_ningun_patron_lleva_el_comentario_en_su_propia_linea() -> None:
    """El defecto de raíz, cazado en la forma y no sólo en el efecto.

    Un `# …` al final de un patrón no es un comentario: pasa a formar parte del nombre. La regla es
    que el comentario va en su propia línea, y esta comprobación la hace cumplir en cualquier patrón
    futuro, no sólo en el que falló.
    """
    ofensores = [
        f".gitignore:{n}: {linea.rstrip()}"
        for n, linea in enumerate(
            (_RAIZ / ".gitignore").read_text(encoding="utf-8").splitlines(), start=1
        )
        if (despojada := linea.strip()) and not despojada.startswith("#") and "#" in despojada
    ]
    assert ofensores == []


def test_el_workdir_del_ui_instalable_esta_vetado() -> None:
    """Lanzar la interfaz dentro de un clon no puede dejar datos listos para commitear.

    `python -m nikodym.ui` crea su workdir en el cwd, así que basta con arrancarla desde la raíz del
    repo —lo natural mientras se desarrolla— para que aparezcan el parquet del dataset materializado
    y el `results.json` de cada corrida. Se descubrió así, verificando el aviso de config
    inejecutable contra el servidor real: `git status` ofreció el directorio entero.
    """
    assert _ignorado(".nikodym_ui/datasets/consumo_comportamiento.parquet")
    assert _ignorado(".nikodym_ui/runs/abc123/results.json")


def test_el_workdir_esta_vetado_tambien_fuera_de_la_raiz() -> None:
    """El veto va SIN ancla `/`: el workdir sigue al cwd de quien lanza, no a la raíz del repo."""
    assert _ignorado("notebooks/.nikodym_ui/runs/abc123/results.json")


def test_el_paquete_del_ui_sigue_versionandose() -> None:
    """El error simétrico: el veto es del workdir generado, no del código que lo crea."""
    assert not _ignorado("src/nikodym/ui/__main__.py")
    assert not _ignorado("src/nikodym/ui/static/index.html")


def test_los_volcados_del_mcp_de_playwright_estan_vetados() -> None:
    """Verificar la interfaz en vivo no puede dejar la consola del navegador lista para commitear.

    Ocurrió: el 2026-07-31 se commitearon dos `.playwright-mcp/console-*.log` desde la raíz del
    repo. El volcado recoge **toda** la consola de la sesión, con las URL de lo que se estuviera
    navegando, así que en un repo público publica por dónde anduvo quien lo generó. Es el mismo modo
    de fallo que el workdir del UI, y por eso el veto va igual: sin ancla `/`, porque el MCP escribe
    en el cwd de quien lanza.
    """
    assert _ignorado(".playwright-mcp/console-2026-07-31T23-18-33-454Z.log")
    assert _ignorado("notebooks/.playwright-mcp/console-2026-08-01T10-00-00-000Z.log")


def test_el_veto_de_playwright_no_alcanza_a_su_configuracion() -> None:
    """El error simétrico: el veto es del volcado generado, no de todo lo que diga «playwright».

    Un veto por nombre de herramienta —o peor, un `*.log` global— se llevaría por delante la
    configuración o los specs de un recorrido automatizado el día que se versionen (B2.4 los
    contempla), y git no avisa de lo que ignora.
    """
    assert not _ignorado("web/playwright.config.ts")
    assert not _ignorado("tests/e2e/recorrido-f1.spec.ts")


def _ignorado_en(repo: Path, ruta: str) -> bool:
    """Igual que :func:`_ignorado`, pero sobre otro repositorio (uno temporal de test)."""
    return (
        subprocess.run(
            ["git", "check-ignore", "-q", ruta],
            cwd=repo,
            capture_output=True,
            check=False,
        ).returncode
        == 0
    )


def test_un_workdir_con_otro_nombre_se_veta_a_si_mismo(tmp_path: Path) -> None:
    """El `.gitignore` del repo cubre el nombre por DEFECTO; el workdir cubre el suyo, sea cual sea.

    `--workdir ui_work` deja los artefactos en un directorio que ningún patrón del repo nombra. No
    se arregla listando nombres —el usuario elige cualquiera—: la interfaz escribe el veto DENTRO de
    su propio workdir al crearlo, como hace toda herramienta que genera caché local.
    """
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    a_mano = tmp_path / "ui_work_a_mano"
    (a_mano / "runs").mkdir(parents=True)
    (a_mano / "runs" / "results.json").write_text("{}", encoding="utf-8")
    # El sentido contrario, que es lo que hace válido al gate: sin el veto, esto SÍ se commitearía.
    assert not _ignorado_en(tmp_path, "ui_work_a_mano/runs/results.json")

    workdir = asegurar_workdir(tmp_path / "ui_work")
    (workdir / "runs").mkdir()
    (workdir / "runs" / "results.json").write_text("{}", encoding="utf-8")
    assert _ignorado_en(tmp_path, "ui_work/runs/results.json")
    assert _ignorado_en(tmp_path, "ui_work/datasets/subido.parquet")


def test_el_veto_del_workdir_no_pisa_el_del_usuario(tmp_path: Path) -> None:
    """Si el `.gitignore` del workdir ya existe es del usuario: se respeta tal cual."""
    workdir = tmp_path / "wd"
    workdir.mkdir()
    (workdir / ".gitignore").write_text("# mío\n", encoding="utf-8")
    asegurar_workdir(workdir)
    assert (workdir / ".gitignore").read_text(encoding="utf-8") == "# mío\n"
