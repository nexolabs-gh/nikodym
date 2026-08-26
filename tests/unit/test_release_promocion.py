"""Gate del contrato de PUBLICACIÓN POR PROMOCIÓN de `release.yml` (D-PKG-9, SDD-25 §7.7).

🔴 El modo de fallo que este gate existe para cerrar no es un bug: es una **deriva silenciosa entre
un contrato escrito y el YAML que publica**. D-PKG-9 quedó aprobada en B2.0 —«el job de publicación
recibe los mismos wheel/sdist cuyos SHA-256 pasaron inspección y clean-room; se prohíbe reconstruir
en release»— y durante meses `release.yml` hizo exactamente lo contrario: su propio `uv build` en un
checkout limpio, `twine check` sobre ESE rebuild, y publicación sin que ninguno de los gates de
B2.1 tocara los bytes que llegaban a PyPI. Además `ci.yml` y `release.yml` disparan los dos en tags
`v*`, en paralelo y sin relación de dependencia, así que un CI rojo tampoco detenía la publicación.

⚠️ Nada lo delataba, y no por descuido: el SDD **sí** documentaba la brecha en prosa («Estado real
hoy…»), pero ningún oráculo ejecutable ataba esa prosa al YAML. Un documento que se corrige solo no
existe. Por eso este gate no comprueba estilo ni nombres: comprueba las cuatro propiedades que hacen
verdadera la promesa, y las ata **contra `ci.yml`** en vez de repetir constantes, de modo que
renombrar el artefacto candidate en un archivo y no en el otro se ponga rojo.

⚠️ **Límite declarado:** esto es un gate ESTÁTICO sobre el YAML. No ejecuta GitHub Actions, así que
no prueba que la publicación funcione de punta a punta; prueba que el workflow no puede volver a
reconstruir ni a publicar sin pasar por el candidate gateado. La verificación viva del artefacto es
`scripts/check_distribution_contents.py`, que este mismo workflow invoca.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

_RAIZ = Path(__file__).resolve().parents[2]
_RELEASE = _RAIZ / ".github" / "workflows" / "release.yml"
_CI = _RAIZ / ".github" / "workflows" / "ci.yml"

# Cualquier forma de fabricar una distribución. D-PKG-9 las prohíbe TODAS en release, no sólo la que
# estaba escrita: si mañana alguien cambia `uv build` por `python -m build`, la brecha vuelve igual.
_CONSTRUCTORES = (
    "uv build",
    "python -m build",
    "pip wheel",
    "setup.py",
    "hatch build",
    "flit build",
)


def _cargar(ruta: Path) -> dict[str, Any]:
    datos = yaml.safe_load(ruta.read_text(encoding="utf-8"))
    assert isinstance(datos, dict)
    return datos


def _disparadores(workflow: dict[str, Any]) -> dict[str, Any]:
    # PyYAML resuelve el `on:` sin comillas al booleano True; ambos archivos lo escriben `"on"`,
    # pero el gate no debe depender de esa comilla para seguir midiendo.
    for clave in ("on", True):
        if clave in workflow:
            valor = workflow[clave]
            assert isinstance(valor, dict)
            return valor
    raise AssertionError("el workflow no declara disparadores")


def _scripts(job: dict[str, Any]) -> str:
    """Concatena los `run:` del job, SIN sus comentarios de shell.

    Los comentarios explican por qué el workflow ya no reconstruye y mencionan `uv build` al
    contarlo; un gate que mirase el texto crudo se encontraría a sí mismo y daría rojo siempre.
    """
    cuerpos = []
    for paso in job["steps"]:
        bruto = paso.get("run")
        if not bruto:
            continue
        cuerpos.extend(linea for linea in bruto.splitlines() if not linea.lstrip().startswith("#"))
    return "\n".join(cuerpos)


@pytest.fixture(scope="module")
def release() -> dict[str, Any]:
    return _cargar(_RELEASE)


@pytest.fixture(scope="module")
def ci() -> dict[str, Any]:
    return _cargar(_CI)


def test_release_no_reconstruye_ninguna_distribucion(release: dict[str, Any]) -> None:
    """D-PKG-9, literal: «Se prohíbe reconstruir en release»."""
    for nombre, job in release["jobs"].items():
        cuerpo = _scripts(job)
        for constructor in _CONSTRUCTORES:
            assert constructor not in cuerpo, (
                f"el job `{nombre}` de release.yml ejecuta `{constructor}`: D-PKG-9 prohíbe "
                "reconstruir en release; hay que promover el candidate que ya gateó ci.yml"
            )


def test_release_promueve_el_mismo_artefacto_que_ci_publica(
    release: dict[str, Any], ci: dict[str, Any]
) -> None:
    """El nombre del candidate se mide en `ci.yml`, no se repite como constante.

    Se busca en el job que EJECUTA el checker de distribución —el que firma el candidate—, no por
    parecido de nombre: `ci.yml` sube además `frontend-candidate-evidence`, que es un insumo de ese
    job y no lo que se publica.
    """
    firmantes = [
        job
        for job in ci["jobs"].values()
        if "scripts/check_distribution_contents.py" in _scripts(job)
    ]
    assert len(firmantes) == 1, "no hay exactamente un job de ci.yml que firme el candidate"
    subidos = {
        paso["with"]["name"]
        for paso in firmantes[0]["steps"]
        if str(paso.get("uses", "")).startswith("actions/upload-artifact")
    }
    candidatos = {n for n in subidos if "distributions" in n}
    assert len(candidatos) == 1, f"ci.yml ya no sube un único candidate: {sorted(subidos)}"
    candidate = candidatos.pop()

    promote = _scripts(release["jobs"]["promote"])
    assert candidate in promote, (
        f"release.yml no descarga `{candidate}`, que es el artefacto que ci.yml firma como "
        "publicable (runbook §9). Si ci.yml lo renombró, hay que renombrarlo en los dos sitios"
    )
    assert "gh run download" in promote


def test_release_reejecuta_el_gate_de_contenidos_que_corre_ci(
    release: dict[str, Any], ci: dict[str, Any]
) -> None:
    """El checker no puede quedar sólo en CI: es lo que pasó durante meses."""
    checker = "scripts/check_distribution_contents.py"
    assert (_RAIZ / checker).is_file(), "el checker de contenidos no existe en el árbol"
    assert any(checker in _scripts(job) for job in ci["jobs"].values()), (
        "ci.yml dejó de invocar el checker de contenidos"
    )
    promote = _scripts(release["jobs"]["promote"])
    assert checker in promote, (
        "release.yml no re-ejecuta el gate de contenidos sobre los bytes que va a publicar"
    )
    assert "--frontend-provenance" in promote


def test_release_exige_el_ci_verde_de_ese_mismo_sha(release: dict[str, Any]) -> None:
    """Un `ci.yml` rojo tiene que detener la publicación, que antes no ocurría."""
    promote = _scripts(release["jobs"]["promote"])
    assert "gh run list" in promote and "ci.yml" in promote, (
        "el job promote no consulta los runs de ci.yml"
    )
    assert "$CANDIDATE_SHA" in promote, "la consulta no está anclada al SHA que se va a publicar"
    assert "success" in promote, "no se exige que el CI haya terminado en success"
    assert release["jobs"]["promote"]["permissions"]["actions"] == "read", (
        "sin `actions: read` el job no puede leer los runs de CI ni bajar su artefacto"
    )


def test_el_bundle_estatico_se_ata_al_arbol_versionado(release: dict[str, Any]) -> None:
    """La procedencia que viaja DENTRO del candidate no es raíz de confianza.

    🔴 Medido: mutando a la vez el wheel, el sdist y `frontend-provenance.json`, el gate de
    contenidos queda **verde** —compara el bundle contra hashes que el propio artefacto aporta—.
    Hace falta una atadura contra algo que el candidate no pueda reescribir: el árbol versionado
    en git del tag, que `ci.yml` obliga a estar limpio y a reproducirse byte a byte.
    """
    pasos = release["jobs"]["promote"]["steps"]
    atadura = [
        p
        for p in pasos
        if "git" in str(p.get("run", "")) and "nikodym/ui/static" in str(p.get("run", ""))
    ]
    assert len(atadura) == 1, (
        "no hay exactamente un paso que ate el bundle estático publicado al árbol versionado"
    )
    cuerpo = str(atadura[0]["run"])
    assert "git" in cuerpo and "show" in cuerpo, (
        "la atadura no lee el árbol versionado con `git show`"
    )
    assert "if" not in atadura[0], "la atadura del bundle estático no puede ser condicional"


def test_la_version_promovida_se_ata_al_arbol_sin_depender_del_tag(release: dict[str, Any]) -> None:
    """Un `workflow_dispatch` desde una rama no puede publicar sin atadura de versión.

    🔴 Aquí vivía un agujero heredado: la comprobación de versión colgaba de
    `if: startsWith(github.ref, 'refs/tags/')`, así que un dispatch desde rama —donde no hay tag—
    se la saltaba entera y publicaba el candidate sin que nada comparase su versión con nada.
    """
    pasos = release["jobs"]["promote"]["steps"]
    atadura = [p for p in pasos if "__version__" in str(p.get("run", ""))]
    assert atadura, "ningún paso de promote ata la versión del candidate a `__version__`"

    contra_wheel = [p for p in atadura if "zipfile" in str(p.get("run", ""))]
    assert len(contra_wheel) == 1, (
        "no hay exactamente un paso que lea la versión del wheel promovido"
    )
    assert "if" not in contra_wheel[0], (
        "la atadura de versión del candidate promovido es condicional: con `if:` de tag, un "
        "`workflow_dispatch` desde una rama publica sin comparar versión con nada"
    )


def test_publish_solo_recibe_los_bytes_que_promote_verifico(release: dict[str, Any]) -> None:
    """El traspaso entre jobs es el último tramo, y se cierra por SHA-256, no por confianza."""
    promote, publish = release["jobs"]["promote"], release["jobs"]["publish"]
    assert publish["needs"] == "promote"
    assert publish.get("environment") == "pypi"
    assert publish["permissions"]["id-token"] == "write"

    salidas = promote["outputs"]
    for clave in ("wheel_name", "wheel_sha256", "sdist_name", "sdist_sha256"):
        assert clave in salidas, f"promote no exporta `{clave}`"

    cuerpo = _scripts(publish)
    assert "sha256sum -c" in cuerpo, "publish no recomprueba los SHA-256 de lo que recibió"
    for clave in ("WHEEL_SHA256", "SDIST_SHA256"):
        assert clave in cuerpo, f"publish no consume `{clave}`"

    referenciadas = {
        m
        for paso in publish["steps"]
        for m in re.findall(r"needs\.promote\.outputs\.(\w+)", str(paso))
    }
    assert referenciadas == set(salidas), (
        f"publish consume {sorted(referenciadas)} pero promote exporta {sorted(salidas)}"
    )


def test_ambos_workflows_siguen_disparando_en_los_mismos_tags(
    release: dict[str, Any], ci: dict[str, Any]
) -> None:
    """Si sólo uno disparase en `v*`, promote esperaría un CI que nunca va a existir."""
    tags_release = _disparadores(release)["push"]["tags"]
    tags_ci = _disparadores(ci)["push"]["tags"]
    assert tags_release == ["v*"]
    assert tags_ci == ["v*"], (
        "ci.yml dejó de dispararse en tags: release.yml se quedaría esperando su run para siempre"
    )
