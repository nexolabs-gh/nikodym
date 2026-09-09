"""Gate: el quickstart que publican el README y el sitio se puede ejecutar tal cual.

🔴 **Por qué existe.** D-GOB-7/8 (2026-09-02) encendieron ``audit`` en los cuatro presets y
dejaron de escribir el audit-trail en el directorio de trabajo: desde entonces
``nikodym.run(config)`` con el preset F1 y sin ``run_dir`` levanta ``ConfigError``. La ruptura
está declarada en el CHANGELOG, el docstring de ``run`` la explica y la guía de provisiones ya
pasaba ``run_dir``. Pero el quickstart —el primer bloque de código que copia un lector, repetido en
``README.md``, en la portada del sitio, en «Empezar», en el tutorial y en tres guías— siguió
publicando la llamada vieja durante una semana, y nadie lo notó porque **ningún test lo
ejecutaba**: los gates de ``docs_site/`` ejecutan la guía de provisiones y la puerta de artefactos,
y cotejan cifras; el quickstart no estaba entre ellos.

**Cómo se ata.** Igual que ``test_docs_provision_neutra``: el bloque va entre marcadores HTML y se
ejecuta con el ``cwd`` en un temporal, como lo teclearía un usuario. Tres superficies publican el
mismo quickstart; se ejecuta el de «Empezar» y se exige que README y portada lleven **exactamente
el mismo código**, para que no vuelvan a divergir. El tutorial cuenta un relato continuo —datos →
config → corrida— y se ejecuta como tal, en un solo espacio de nombres. Y una regla estática cubre
los bloques que no se ejecutan: todo fragmento de ``docs_site/`` o del README que corra un preset
de fábrica tiene que decir dónde queda la evidencia.

⚠️ Lo que **no** cubre: un bloque nuevo sin marcadores no entra al gate. Se dice para que nadie
lea la tabla como cobertura total.
"""

from __future__ import annotations

import re
import tempfile
from pathlib import Path

import pytest

_RAIZ = Path(__file__).resolve().parents[2]
_DOCS = _RAIZ / "docs_site"
_README = _RAIZ / "README.md"

#: Páginas que publican el quickstart. La primera es la que se ejecuta; las demás tienen que llevar
#: el mismo bloque byte a byte.
_QUICKSTART = ("getting-started.md", "index.md")
_BLOQUE_QUICKSTART = "quickstart"

#: Bloques del tutorial en orden de lectura: cada uno usa lo que dejó el anterior (``data_path``,
#: ``config``, ``workdir``), así que ejecutarlos juntos es lo único que prueba que el relato cierra.
_TUTORIAL = ("tutorial-paso-1", "tutorial-paso-2", "tutorial-paso-3")

_FENCE_PYTHON = re.compile(r"```python\n(.*?)\n```", re.DOTALL)
_USA_PRESET = re.compile(r"standard_preset\(|get_preset\(")
_LLAMA_RUN = re.compile(r"nikodym\.run\(")


def _bloque(texto: str, nombre: str, origen: str) -> str:
    inicio = f"<!-- {nombre}:start -->\n```python\n"
    fin = f"\n```\n<!-- {nombre}:end -->"
    assert texto.count(inicio) == 1 and texto.count(fin) == 1, (
        f"{origen}: el bloque ejecutable {nombre!r} perdió sus delimitadores"
    )
    return texto.split(inicio, maxsplit=1)[1].split(fin, maxsplit=1)[0]


def _quickstart_de(archivo: Path) -> str:
    codigo = _bloque(archivo.read_text(encoding="utf-8"), _BLOQUE_QUICKSTART, archivo.name)
    # Ancla anti-vacuidad: unos delimitadores que envuelvan la nada se leen igual que un ejemplo
    # correcto. El quickstart corre el preset F1 y lee un artefacto; sin eso no es el quickstart.
    assert "standard_preset()" in codigo and "nikodym.run(" in codigo, (
        f"{archivo.name}: el quickstart extraído perdió el preset o la corrida; el gate sería vacuo"
    )
    assert 'study.artifacts.get("performance", "discriminant_metrics")' in codigo
    return codigo


def _ejecutar(codigo: str, origen: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    """Ejecuta el código publicado con el cwd y el temp del sistema dentro de ``tmp_path``.

    El quickstart usa ``mkdtemp`` a propósito —es lo que un usuario teclea—; redirigir el temp del
    proceso a ``tmp_path`` evita que cada corrida de la suite deje un workdir huérfano en el temp de
    la máquina, que es la clase de fricción por la que un gate se acaba desactivando.
    """
    pytest.importorskip("optbinning")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    espacio: dict = {"__name__": "__main__"}
    exec(compile(codigo, str(origen), "exec"), espacio)
    return espacio


def test_las_tres_superficies_publican_el_mismo_quickstart() -> None:
    """README, portada y «Empezar» divergían en comentarios y prefijos; ahora son un solo bloque."""
    referencia = _quickstart_de(_DOCS / _QUICKSTART[0])
    for archivo in (_DOCS / _QUICKSTART[1], _README):
        assert _quickstart_de(archivo) == referencia, (
            f"{archivo.name} publica un quickstart distinto del de {_QUICKSTART[0]}. Es el mismo "
            "ejemplo en tres superficies: edítalo en las tres o deja de publicarlo en una."
        )


def test_el_quickstart_publicado_es_ejecutable_y_deja_la_evidencia_que_anuncia(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Corre el bloque de «Empezar» tal cual y comprueba lo que su comentario promete.

    El comentario del paso 3 dice que en ``run_dir`` queda el audit-trail que el preset trae
    encendido y que la ficha del modelo sólo aparece si se declara ``governance``. Las dos mitades
    se miden: el trail existe y el card no, porque el preset no declara propósito (D-GOB-8).
    """
    espacio = _ejecutar(
        _quickstart_de(_DOCS / _QUICKSTART[0]), _DOCS / _QUICKSTART[0], tmp_path, monkeypatch
    )
    study = espacio["study"]
    assert study.run_context.status == "done", study.run_context.error
    run_dir = espacio["workdir"] / "corrida"
    assert (run_dir / "audit_trail.jsonl").is_file(), sorted(p.name for p in run_dir.iterdir())
    assert not (run_dir / "model_card.json").exists(), (
        "el preset F1 no declara `governance`, así que no debería haber ficha del modelo"
    )
    assert run_dir.is_relative_to(tmp_path), "la evidencia se escribió fuera del temporal del test"


def test_el_tutorial_se_ejecuta_de_corrido(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Datos → config → corrida, en un solo espacio de nombres, como lo lee un usuario."""
    texto = (_DOCS / "tutorial.md").read_text(encoding="utf-8")
    partes = [_bloque(texto, nombre, "tutorial.md") for nombre in _TUTORIAL]
    codigo = "\n".join(partes)
    assert "materialize(" in codigo and "standard_preset()" in codigo and "nikodym.run(" in codigo
    espacio = _ejecutar(codigo, _DOCS / "tutorial.md", tmp_path, monkeypatch)
    assert espacio["study"].run_context.status == "done", espacio["study"].run_context.error


def _fragmentos_con_preset() -> list[tuple[str, str]]:
    paginas = [*sorted(_DOCS.rglob("*.md")), _README]
    encontrados: list[tuple[str, str]] = []
    for pagina in paginas:
        texto = pagina.read_text(encoding="utf-8")
        for fence in _FENCE_PYTHON.findall(texto):
            if _USA_PRESET.search(fence) and _LLAMA_RUN.search(fence):
                encontrados.append((pagina.relative_to(_RAIZ).as_posix(), fence))
    return encontrados


def test_todo_fragmento_que_corre_un_preset_dice_donde_queda_la_evidencia() -> None:
    """Regla estática para los bloques que no se ejecutan (las guías repiten la receta).

    Un preset de fábrica trae la auditoría encendida, y sin ``run_dir`` la corrida no arranca. Un
    fragmento que muestre el preset y llame a ``nikodym.run`` sin decir dónde va la evidencia
    publica una llamada que falla en cuanto se copia.
    """
    fragmentos = _fragmentos_con_preset()
    # Ancla anti-vacuidad: hoy son siete (README, portada, «Empezar», tutorial y tres guías).
    assert len(fragmentos) >= 5, f"sólo se encontraron {len(fragmentos)} fragmentos con preset"
    sin_run_dir = [origen for origen, fence in fragmentos if "run_dir=" not in fence]
    assert sin_run_dir == [], (
        f"fragmentos que corren un preset sin `run_dir=`: {sin_run_dir}. Con la auditoría que el "
        "preset trae encendida, esa llamada levanta ConfigError en vez de correr."
    )
