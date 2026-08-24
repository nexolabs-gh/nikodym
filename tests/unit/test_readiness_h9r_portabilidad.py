"""Portabilidad del arnés H9R: importable en todas partes, calificable sólo en Windows.

Estas pruebas corren en los tres sistemas operativos a propósito y no llevan `skipif`: su objeto
es precisamente el arranque en Linux/macOS.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

# Módulos de la stdlib que sólo existen en Windows. Un import de éstos en el cuerpo de módulo
# rompe la **colección** de pytest en Linux/macOS aunque cada prueba lleve su `skipif`: el marcador
# salta las pruebas, no la importación del archivo. Medido en CI el 2026-08-20: `import _winapi`
# a nivel de módulo dejó rojos los seis jobs no-Windows con `ModuleNotFoundError` mientras los tres
# de Windows pasaban. Este gate mueve esa detección a esta torre.
_WINDOWS_ONLY_MODULES = frozenset({"_winapi", "msvcrt", "winreg", "winsound", "nt", "_overlapped"})


def _h9r_python_files() -> list[Path]:
    root = Path(__file__).resolve().parents[2]
    files = sorted((root / "scripts" / "readiness_h9r").glob("*.py"))
    files.append(root / "scripts" / "measure_readiness_h9r.py")
    files.extend(sorted((root / "tests" / "unit").glob("test_readiness_h9r_*.py")))
    return [path for path in files if path.is_file()]


def _module_level_imports(tree: ast.Module) -> list[str]:
    names: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            names.extend(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.append(node.module.split(".")[0])
    return names


def test_ningun_modulo_h9r_importa_solo_windows_en_el_cuerpo() -> None:
    """Todo archivo H9R debe ser importable en Linux/macOS aunque sólo califique en Windows.

    El censo se hace sobre el AST y no importando: en esta torre el import funcionaría igual y no
    probaría nada.
    """
    archivos = _h9r_python_files()
    assert archivos, "el censo de archivos H9R quedó vacío"
    ofensores: list[str] = []
    for path in archivos:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for nombre in _module_level_imports(tree):
            if nombre in _WINDOWS_ONLY_MODULES:
                ofensores.append(f"{path.name}: {nombre}")
    assert not ofensores, f"import sólo-Windows en el cuerpo del módulo: {ofensores}"


def test_el_gate_de_portabilidad_detecta_un_import_solo_windows(tmp_path: Path) -> None:
    """Control negativo: el mismo criterio, aplicado a un archivo que sí ofende, debe verlo."""
    ofensor = tmp_path / "test_readiness_h9r_falso.py"
    ofensor.write_text("import _winapi\nimport os\n", encoding="utf-8")
    tree = ast.parse(ofensor.read_text(encoding="utf-8"), filename=str(ofensor))
    assert "_winapi" in _module_level_imports(tree)
    # Y el otro sentido: dentro de una función deja de ser un import de cuerpo de módulo.
    interno = tmp_path / "test_readiness_h9r_interno.py"
    interno.write_text("def f():\n    import _winapi\n    return _winapi\n", encoding="utf-8")
    tree_interno = ast.parse(interno.read_text(encoding="utf-8"), filename=str(interno))
    assert "_winapi" not in _module_level_imports(tree_interno)


def test_el_censo_de_portabilidad_cubre_el_arnes_completo() -> None:
    """Sin cobertura medida, el gate podría quedar verde por no mirar ningún archivo."""
    nombres = {path.name for path in _h9r_python_files()}
    assert "windows_sandbox.py" in nombres
    assert "windows_job.py" in nombres
    assert "material_lease.py" in nombres
    assert "measure_readiness_h9r.py" in nombres
    assert "test_readiness_h9r_output_isolation.py" in nombres
    assert "test_readiness_h9r_material_lease.py" in nombres


def test_material_lease_importa_en_cualquier_so_y_falla_cerrado_fuera_de_windows() -> None:
    """El cuerpo del módulo debe importar en Linux/macOS aunque sólo califique en Windows."""
    from scripts.readiness_h9r import material_lease

    assert material_lease.CANDIDATE_MATERIAL_LEASE_MECHANISM == "windows_share_mode_lease_v1"
    if sys.platform != "win32":
        with pytest.raises(material_lease.MaterialLeaseError, match="exige Windows"):
            material_lease.acquire_material_lease(
                Path("."),
                expected_entries=[{"relative_path": "x", "bytes": 0, "sha256": "1" * 64}],
                expected_tree_sha256="2" * 64,
            )
