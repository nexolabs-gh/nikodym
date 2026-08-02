"""Gate: la capa de interfaz nunca reconstruye un objeto Python desde bytes del cliente (D-PUE-1).

La puerta de artefactos por código (`nikodym.run(config, artifacts=…)`) acepta **cualquier** objeto:
un `LabeledFrame`, un binning fiteado, lo que el paso consumidor sepa leer. Abrirla por HTTP con esa
misma generalidad habría exigido un formato de serialización de objetos, o sea el vector que
`Study.load(trust=False)` rechaza a propósito (`core/study.py:791-794`). D-ART-9 dejó HTTP fuera
justamente por esa pregunta sin contestar.

La respuesta de D-PUE-1 es que **por HTTP sólo entran tablas**: los mismos tres lectores de pandas
que `/api/upload` ya usa. La consecuencia buscada es que la puerta HTTP quede **estrictamente menos
poderosa** que la de código, y este gate es lo que impide que esa asimetría se erosione con el
tiempo — el día que alguien quiera «también aceptar el modelo serializado», se topa con un rojo y
una decisión que tomar por SDD, no con un `import` de una línea.

Se mide por AST y no con `grep` a propósito: el docstring de `ui/runs.py` **explica** por qué se
evita el pickle, y un `grep` de la palabra lo acusaría. Lo que se veta es importar el módulo o
llamar a la función, no nombrarlos al razonar.
"""

from __future__ import annotations

import ast
from pathlib import Path

_UI = Path(__file__).resolve().parents[2] / "src" / "nikodym" / "ui"

#: Módulos que reconstruyen objetos Python arbitrarios desde bytes. Importar cualquiera de ellos en
#: la capa de interfaz abre el vector que D-PUE-1 cierra.
_MODULOS_VETADOS = frozenset({"pickle", "cPickle", "joblib", "dill", "marshal", "shelve"})

#: Atributos que deserializan sin puerta segura. `yaml.safe_load` NO está aquí: es seguro y es el
#: que el motor usa para cargar un config.
_ATRIBUTOS_VETADOS = frozenset({"unsafe_load", "full_load", "Unpickler", "loads_pickle"})

#: Llamadas de la forma `<Nombre>.load(...)` que repueblan un `Study` completo desde disco.
_CARGAS_VETADAS = frozenset({"Study"})


def _archivos_de_la_capa() -> list[Path]:
    return sorted(ruta for ruta in _UI.rglob("*.py") if "__pycache__" not in ruta.parts)


def test_el_barrido_recorre_la_capa_entera() -> None:
    """Un barrido que lee cero archivos daría verde vacío, como el primer gate de copy."""
    archivos = _archivos_de_la_capa()
    assert len(archivos) >= 14, f"el barrido sólo encontró {len(archivos)} archivos en ui/."
    nombres = {ruta.name for ruta in archivos}
    for ancla in ("routes.py", "datasets.py", "runs.py", "security.py"):
        assert ancla in nombres, f"el barrido no encontró {ancla}."


def test_la_capa_ui_no_importa_deserializadores_de_objetos() -> None:
    """Ningún módulo de `nikodym/ui/` importa pickle, joblib ni sus equivalentes."""
    ofensores: list[str] = []
    for ruta in _archivos_de_la_capa():
        arbol = ast.parse(ruta.read_text(encoding="utf-8"))
        for nodo in ast.walk(arbol):
            if isinstance(nodo, ast.Import):
                for alias in nodo.names:
                    if alias.name.split(".")[0] in _MODULOS_VETADOS:
                        ofensores.append(f"{ruta.name}:{nodo.lineno} import {alias.name}")
            elif (
                isinstance(nodo, ast.ImportFrom)
                and nodo.module
                and nodo.module.split(".")[0] in _MODULOS_VETADOS
            ):
                ofensores.append(f"{ruta.name}:{nodo.lineno} from {nodo.module}")
    assert not ofensores, (
        "La capa de interfaz no puede reconstruir objetos Python desde bytes del cliente "
        f"(D-PUE-1). Ofensores: {ofensores}. Por HTTP sólo entran tablas: .csv/.xlsx/.parquet "
        "leídos con pandas."
    )


def test_la_capa_ui_no_llama_a_cargas_inseguras() -> None:
    """Ni `yaml.unsafe_load` ni `Study.load`: la UI no repuebla un `Study` desde disco ajeno."""
    ofensores: list[str] = []
    for ruta in _archivos_de_la_capa():
        arbol = ast.parse(ruta.read_text(encoding="utf-8"))
        for nodo in ast.walk(arbol):
            if not isinstance(nodo, ast.Call) or not isinstance(nodo.func, ast.Attribute):
                continue
            atributo = nodo.func
            if atributo.attr in _ATRIBUTOS_VETADOS:
                ofensores.append(f"{ruta.name}:{nodo.lineno} .{atributo.attr}()")
            if (
                atributo.attr == "load"
                and isinstance(atributo.value, ast.Name)
                and atributo.value.id in _CARGAS_VETADAS
            ):
                ofensores.append(f"{ruta.name}:{nodo.lineno} {atributo.value.id}.load()")
    assert not ofensores, (
        f"Carga insegura en la capa de interfaz (D-PUE-1): {ofensores}. "
        "`Study.load` deserializa objetos con joblib y por eso tiene su propia puerta `trust=`; "
        "la interfaz no la abre."
    )
