"""Gate G7: el fixture del schema del front no puede quedarse viejo en silencio.

``web/src/fixtures/schema.json`` es el snapshot de ``GET /api/schema`` que la demo estática sirve
sin backend, y que además **viaja dentro del bundle instalable** (``web/src/lib/schema.ts`` lo
importa estáticamente). Lo regenera ``scripts/gen_schema_fixture.py``… cuando alguien se acuerda:
hasta este gate, nada comprobaba que se hubiera corrido. Ya se pagó una vez —el fixture llegó a
64 kB contra 259 kB reales, y publicó en demo.nikodym.cl un encuadre normativo que el código ya
había corregido— y el docstring de ese script lo cuenta.

Gemelo del patrón de ``test_public_copy.py``: la paridad entre una verdad Python y un artefacto
commiteado del front se verifica **desde pytest**, que es el único lado con acceso a los dos.

**Tolerancia a extras ausentes, deliberada.** ``build_full_json_schema`` deja opaco el dominio cuyo
extra no esté instalado, así que comparar todo contra el fixture (generado con ``--all-extras``)
enrojecería los jobs mínimos del CI. Se comparan sólo los dominios importables en este entorno,
con el mismo criterio que usa el propio compositor; el precedente está en
``test_config_full_schema.py::..._degrada_por_extra_ausente``.
"""

from __future__ import annotations

import copy
import importlib
import json
from pathlib import Path
from typing import Any

from nikodym.core.exceptions import MissingDependencyError
from nikodym.core.study import _DOMAIN_CONFIG_CLASSES
from nikodym.ui.routes import schema_payload

#: El artefacto commiteado que consume el front (y que el bundle instalable embebe).
_FIXTURE = Path(__file__).resolve().parents[2] / "web" / "src" / "fixtures" / "schema.json"


def _fixture() -> dict[str, Any]:
    return json.loads(_FIXTURE.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def _dominios_disponibles() -> list[str]:
    """Dominios cuyo extra ESTÁ instalado aquí, con el criterio de ``build_full_json_schema``.

    Se pregunta por el import y no por la forma del nodo JSON a propósito: así el gate no depende
    de cómo se represente una sección expandida, y sobrevive a un cambio de esa representación.
    """
    disponibles = []
    for dominio, (modulo, clase) in _DOMAIN_CONFIG_CLASSES.items():
        try:
            getattr(importlib.import_module(modulo), clase)
        except (ImportError, MissingDependencyError, AttributeError):
            continue
        disponibles.append(dominio)
    return disponibles


def _nodos(payload: dict[str, Any], dominio: str) -> dict[str, Any]:
    """Nodo raíz de un dominio más todos sus ``$defs`` prefijados, indexados por nombre."""
    schema = payload["json_schema"]
    prefijo = f"{dominio}__"
    nodos: dict[str, Any] = {dominio: schema["properties"].get(dominio)}
    nodos.update(
        {
            nombre: nodo
            for nombre, nodo in schema.get("$defs", {}).items()
            if nombre.startswith(prefijo)
        }
    )
    return nodos


def _diferencias(vivo: dict[str, Any], fixture: dict[str, Any], dominios: list[str]) -> list[str]:
    """Nombres de nodo que difieren entre el payload vivo y el fixture, para los dominios dados."""
    distintos = []
    for dominio in dominios:
        nodos_vivo = _nodos(vivo, dominio)
        nodos_fixture = _nodos(fixture, dominio)
        for nombre in sorted(set(nodos_vivo) | set(nodos_fixture)):
            if nodos_vivo.get(nombre) != nodos_fixture.get(nombre):
                distintos.append(nombre)
    return distintos


def test_el_fixture_existe() -> None:
    """Sin esto, una ruta movida dejaría el gate en verde comparando nada."""
    assert _FIXTURE.is_file(), f"no está {_FIXTURE}"


def test_hay_dominios_que_comparar() -> None:
    """Ídem: un entorno que no importara ningún dominio volvería vacuo todo lo de abajo."""
    assert len(_dominios_disponibles()) >= 1


def test_el_fixture_esta_en_formato_canonico() -> None:
    """Los bytes del archivo son los que produce el generador — nadie lo editó a mano.

    Se compara el archivo contra su propio re-dump, NO contra el payload vivo: en un job sin todos
    los extras diferirían legítimamente, y esa comparación es la de abajo.
    """
    crudo = _FIXTURE.read_text(encoding="utf-8")
    canonico = json.dumps(json.loads(crudo), indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    assert crudo == canonico, (
        "el fixture no está en el formato de `scripts/gen_schema_fixture.py` "
        "(indent=2, ensure_ascii=False, sort_keys=True): regenéralo en vez de editarlo a mano"
    )


def test_defaults_y_section_order_identicos() -> None:
    """Ambos salen de ``NikodymConfig`` y no dependen de qué extras haya: se comparan siempre."""
    vivo = schema_payload()
    fixture = _fixture()
    assert vivo["section_order"] == fixture["section_order"]
    assert vivo["defaults"] == fixture["defaults"]


def test_cada_dominio_expandido_coincide_con_el_fixture() -> None:
    """El corazón del gate: tocar un config y no regenerar el fixture pone esto en rojo."""
    distintos = _diferencias(schema_payload(), _fixture(), _dominios_disponibles())
    assert not distintos, (
        f"el fixture del schema está viejo en {len(distintos)} nodo(s): {distintos[:8]}. "
        "Corre `./.venv/bin/python scripts/gen_schema_fixture.py` y commitea el resultado "
        "junto con el bundle (`pnpm build:package` desde `web/`)."
    )


def test_la_comparacion_no_es_tautologica() -> None:
    """Que el comparador DETECTE una diferencia real, no que devuelva siempre lista vacía.

    Sin este test, un ``_diferencias`` roto —o uno que compare un nodo contra sí mismo— dejaría
    los cinco de arriba en verde sin vigilar nada. Es la lección de ``1.6.0``: un gate al 100 %
    puede no probar nada, y se ancla haciéndolo fallar a propósito.

    Se dopa el fixture contra SÍ MISMO y no contra el payload vivo, para que este test no herede
    el estado del de arriba: un fixture viejo debe dar UN rojo con su causa, no dos.
    """
    dominios = _dominios_disponibles()
    fixture = _fixture()
    dopado = copy.deepcopy(fixture)
    dopado["json_schema"]["properties"][dominios[0]] = {"description": "texto que nadie escribió"}

    assert _diferencias(fixture, fixture, dominios) == []
    assert _diferencias(fixture, dopado, dominios) == [dominios[0]]
