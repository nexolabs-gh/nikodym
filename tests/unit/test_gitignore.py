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
