"""Controles del lease anti-sustitución ``windows_share_mode_lease_v1`` (capa A.1).

Cada oráculo de §8.1 de la enmienda de lease que corresponde a la pieza 1 tiene aquí su
prueba con brazo de vacuidad. Los árboles viven bajo ``tmp_path``; ninguna prueba alcanza
consumidores candidatos ni emite START.
"""

from __future__ import annotations

import ctypes
import hashlib
import io
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from scripts.readiness_h9r import material_lease
from scripts.readiness_h9r.artifacts import canonical_tree_identity
from scripts.readiness_h9r.material_lease import (
    LeaseAcquisitionError,
    LeaseCoverageError,
    LeaseOrderError,
    LeaseReleaseError,
    LeaseStreamError,
    LeaseVolumeError,
    MaterialLeaseError,
    acquire_material_lease,
)

pytestmark = pytest.mark.skipif(
    sys.platform != "win32",
    reason="el lease de material candidato sólo califica en Windows",
)

_GENERIC_READ = 0x80000000
_GENERIC_WRITE = 0x40000000
_OPEN_EXISTING = 3
_SHARE_READ_WRITE_DELETE = 0x1 | 0x2 | 0x4
_SHARING_VIOLATION = 32


def _material(tmp_path: Path) -> tuple[Path, list[dict[str, Any]], str]:
    root = tmp_path / "material"
    (root / "pkg").mkdir(parents=True)
    (root / "a.txt").write_bytes(b"alpha")
    (root / "pkg" / "b.bin").write_bytes(b"beta-bytes")
    (root / "pkg" / "py.typed").write_bytes(b"")
    identity = canonical_tree_identity(root, include_entries=True)
    return root, list(identity["entries"]), str(identity["sha256"])


def _abrir_escritura(
    path: Path, *, share: int, acceso: int = _GENERIC_WRITE
) -> tuple[int | None, int]:
    kernel32: Any = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
    ]
    kernel32.CreateFileW.restype = ctypes.c_void_p
    handle = kernel32.CreateFileW(str(path), acceso, share, None, _OPEN_EXISTING, 0, None)
    invalid_handle = ctypes.c_void_p(-1).value
    if handle in {None, invalid_handle}:
        return None, ctypes.get_last_error()
    return int(handle), 0


def _cerrar(handle: int) -> None:
    kernel32: Any = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.restype = ctypes.c_int
    assert kernel32.CloseHandle(handle)


def _exigir_escritura_exclusiva(path: Path) -> None:
    """Prueba de no-fuga: sin lease vivo, el archivo se abre en exclusiva (share=0)."""
    handle, winerror = _abrir_escritura(path, share=0)
    assert handle is not None, f"quedó un handle vivo sobre {path}: winerror={winerror}"
    _cerrar(handle)


def _junction_o_skip(link: Path, target: Path) -> None:
    completed = subprocess.run(
        ["cmd.exe", "/d", "/c", "mklink", "/J", str(link), str(target)],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        pytest.skip(f"el runner no permite crear junctions: {completed.stderr.strip()}")


def test_lease_bloquea_escritura_borrado_renombre_y_reemplazo(tmp_path: Path) -> None:
    """Oráculo «lease efectivo» de §8.1, con su brazo de vacuidad tras la liberación."""
    root, entries, tree_sha = _material(tmp_path)
    objetivo = root / "a.txt"
    sha_original = hashlib.sha256(objetivo.read_bytes()).hexdigest()
    lease = acquire_material_lease(root, expected_entries=entries, expected_tree_sha256=tree_sha)
    try:
        handle, winerror = _abrir_escritura(objetivo, share=_SHARE_READ_WRITE_DELETE)
        assert handle is None, "la apertura de escritura debía quedar bloqueada por el lease"
        assert winerror == _SHARING_VIOLATION
        with pytest.raises(PermissionError):
            objetivo.unlink()
        with pytest.raises(PermissionError):
            os.rename(objetivo, root / "a-renombrada.txt")
        reemplazo = tmp_path / "reemplazo.txt"
        reemplazo.write_bytes(b"bytes sustitutos")
        with pytest.raises(PermissionError):
            os.replace(reemplazo, objetivo)
    finally:
        lease.release()
    handle, winerror = _abrir_escritura(objetivo, share=_SHARE_READ_WRITE_DELETE)
    assert handle is not None, f"sin lease la apertura debía funcionar: winerror={winerror}"
    _cerrar(handle)
    os.replace(tmp_path / "reemplazo.txt", objetivo)
    assert hashlib.sha256(objetivo.read_bytes()).hexdigest() != sha_original


def test_lease_no_estorba_la_lectura_y_el_hash_por_handle_reconcilia(tmp_path: Path) -> None:
    root, entries, tree_sha = _material(tmp_path)
    lease = acquire_material_lease(root, expected_entries=entries, expected_tree_sha256=tree_sha)
    try:
        assert (root / "a.txt").read_bytes() == b"alpha"
        digests = lease.hash_and_verify()
        assert digests == {
            str(entry["relative_path"]): {
                "logical_bytes": int(entry["bytes"]),
                "sha256": str(entry["sha256"]),
            }
            for entry in entries
        }
    finally:
        lease.release()


def test_adquisicion_parent_first_y_lease_antes_del_primer_hash(tmp_path: Path) -> None:
    """Oráculo «orden» de §8.1: primero todo el conjunto, después el primer hash."""
    root, entries, tree_sha = _material(tmp_path)
    lease = acquire_material_lease(root, expected_entries=entries, expected_tree_sha256=tree_sha)
    try:
        lease.hash_and_verify()
        censo = lease.attestation()
        posiciones = {
            entrada["relative_path"]: indice for indice, entrada in enumerate(censo["entries"])
        }
        for relative_path, posicion in posiciones.items():
            if relative_path == ".":
                assert posicion == 0
                continue
            padre = relative_path.rsplit("/", 1)[0] if "/" in relative_path else "."
            assert posiciones[padre] < posicion, f"{padre} debía preceder a {relative_path}"
        assert censo["acquisition_completed_perf_ns"] >= censo["acquisition_started_perf_ns"]
        assert censo["first_hash_started_perf_ns"] >= censo["acquisition_completed_perf_ns"], (
            "el primer hash debía ocurrir con el conjunto ya congelado (D-LEA-8)"
        )
    finally:
        lease.release()


def test_hash_por_handle_no_reabre_por_ruta(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Oráculo «hash por handle» de §8.1: el doble hace fallar toda reapertura por ruta."""
    root, entries, tree_sha = _material(tmp_path)
    esperados = {
        str(entry["relative_path"]): {
            "logical_bytes": int(entry["bytes"]),
            "sha256": str(entry["sha256"]),
        }
        for entry in entries
    }
    lease = acquire_material_lease(root, expected_entries=entries, expected_tree_sha256=tree_sha)
    try:

        def _reapertura_prohibida(*args: Any, **kwargs: Any) -> Any:
            raise AssertionError("reapertura por ruta durante el hash bajo lease")

        with monkeypatch.context() as contexto:
            contexto.setattr("builtins.open", _reapertura_prohibida)
            contexto.setattr(io, "open", _reapertura_prohibida)
            contexto.setattr(os, "open", _reapertura_prohibida)
            contexto.setattr(Path, "open", _reapertura_prohibida)
            contexto.setattr(Path, "read_bytes", _reapertura_prohibida)
            contexto.setattr(material_lease, "_open_lease_handle", _reapertura_prohibida)
            digests = lease.hash_and_verify()
        assert digests == esperados
    finally:
        lease.release()


def test_cobertura_inversa_alta_no_declarada_reconcilia_en_rojo(tmp_path: Path) -> None:
    """Oráculo «cobertura inversa» de §8.1: un alta que permanece rompe la igualdad exacta."""
    root, entries, tree_sha = _material(tmp_path)
    (root / "pkg" / "plantado.txt").write_bytes(b"alta no declarada")
    with pytest.raises(LeaseCoverageError, match=r"alta no declarada.*plantado"):
        acquire_material_lease(root, expected_entries=entries, expected_tree_sha256=tree_sha)
    _exigir_escritura_exclusiva(root / "a.txt")


def test_cobertura_archivo_esperado_ausente_reconcilia_en_rojo(tmp_path: Path) -> None:
    root, entries, tree_sha = _material(tmp_path)
    (root / "pkg" / "b.bin").unlink()
    with pytest.raises(LeaseCoverageError, match=r"archivo esperado ausente.*b\.bin"):
        acquire_material_lease(root, expected_entries=entries, expected_tree_sha256=tree_sha)
    _exigir_escritura_exclusiva(root / "a.txt")


def test_cotejo_usa_enumeracion_independiente_del_adquisidor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Oráculo «independencia de enumeraciones» de §8.1: el defecto vive sólo en el adquisidor."""
    root, entries, tree_sha = _material(tmp_path)
    enumeracion_real = material_lease._acquire_directory_children

    def _adquisidor_defectuoso(
        directory: Path, *, deadline_monotonic: float | None = None
    ) -> list[tuple[str, bool]]:
        children = enumeracion_real(directory, deadline_monotonic=deadline_monotonic)
        return [child for child in children if child[0] != "a.txt"]

    monkeypatch.setattr(material_lease, "_acquire_directory_children", _adquisidor_defectuoso)
    with pytest.raises(LeaseCoverageError, match=r"presente en el árbol y no leaseado: a\.txt"):
        acquire_material_lease(root, expected_entries=entries, expected_tree_sha256=tree_sha)
    _exigir_escritura_exclusiva(root / "pkg" / "b.bin")


def test_falla_cerrado_con_escritor_vivo_y_sin_fugar_handles(tmp_path: Path) -> None:
    """Oráculo «fail-closed» de §8.1 al nivel del primitivo: winerror=32 y cero handles vivos."""
    root, entries, tree_sha = _material(tmp_path)
    escritor, winerror = _abrir_escritura(root / "pkg" / "b.bin", share=_SHARE_READ_WRITE_DELETE)
    assert escritor is not None, f"no se pudo abrir el escritor del control: winerror={winerror}"
    try:
        with pytest.raises(LeaseAcquisitionError, match=r"b\.bin \(winerror=32\)"):
            acquire_material_lease(root, expected_entries=entries, expected_tree_sha256=tree_sha)
    finally:
        _cerrar(escritor)
    for relative in ("a.txt", "pkg/b.bin", "pkg/py.typed"):
        _exigir_escritura_exclusiva(root / Path(relative))


def test_vista_escribible_preexistente_falla_cerrado(tmp_path: Path) -> None:
    """Cuarta revisión A.1: una sección escribible mapeada antes del lease lo rechaza.

    La hipótesis adversarial era que un tercero podía crear un file mapping
    ``PAGE_READWRITE``, mapear su vista, cerrar los handles y seguir mutando los bytes con
    el lease ya adquirido. Medido en esta torre: mientras la vista vive, el share mode de la
    sección persiste y ``CreateFileW`` con ``FILE_SHARE_READ`` devuelve ``winerror=32``, de
    modo que el arnés **no** congela material mutable. El brazo de vacuidad demuestra que el
    rechazo lo produce la vista y no el entorno.
    """
    kernel32: Any = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileMappingW.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_wchar_p,
    ]
    kernel32.CreateFileMappingW.restype = ctypes.c_void_p
    kernel32.MapViewOfFile.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_size_t,
    ]
    kernel32.MapViewOfFile.restype = ctypes.c_void_p
    kernel32.UnmapViewOfFile.argtypes = [ctypes.c_void_p]
    kernel32.UnmapViewOfFile.restype = ctypes.c_int

    root, entries, tree_sha = _material(tmp_path)
    objetivo = root / "a.txt"
    handle, winerror = _abrir_escritura(
        objetivo, share=_SHARE_READ_WRITE_DELETE, acceso=_GENERIC_READ | _GENERIC_WRITE
    )
    assert handle is not None, f"no se pudo abrir el escritor del control: winerror={winerror}"
    mapping = kernel32.CreateFileMappingW(ctypes.c_void_p(handle), None, 0x04, 0, 0, None)
    assert mapping not in {None, ctypes.c_void_p(-1).value}, ctypes.get_last_error()
    vista = kernel32.MapViewOfFile(ctypes.c_void_p(mapping), 0x0002, 0, 0, 0)
    assert vista not in {None, 0}, ctypes.get_last_error()
    _cerrar(handle)
    _cerrar(mapping)
    try:
        with pytest.raises(LeaseAcquisitionError, match=r"a\.txt \(winerror=32\)"):
            acquire_material_lease(root, expected_entries=entries, expected_tree_sha256=tree_sha)
    finally:
        assert kernel32.UnmapViewOfFile(ctypes.c_void_p(vista))
    # Vacuidad: retirada la vista, el mismo material se congela sin objeciones.
    lease = acquire_material_lease(root, expected_entries=entries, expected_tree_sha256=tree_sha)
    lease.release()


def test_ads_preexistente_rechazado_y_vacuidad(tmp_path: Path) -> None:
    """Oráculo «ADS» de §8.1: un stream alterno pone rojo; sin el stream, verde."""
    root, entries, tree_sha = _material(tmp_path)
    with open(str(root / "a.txt") + ":alterno", "w", encoding="ascii") as stream:
        stream.write("plantado")
    with pytest.raises(LeaseStreamError, match=r"stream no predeterminado.*alterno"):
        acquire_material_lease(root, expected_entries=entries, expected_tree_sha256=tree_sha)
    _exigir_escritura_exclusiva(root / "a.txt")
    os.remove(str(root / "a.txt") + ":alterno")
    lease = acquire_material_lease(root, expected_entries=entries, expected_tree_sha256=tree_sha)
    lease.release()


def test_ads_sobre_material_leaseado_lo_detecta_verify_streams(tmp_path: Path) -> None:
    """El lease no impide crear un ADS (medido en §2.1): el censo repetido debe verlo."""
    root, entries, tree_sha = _material(tmp_path)
    lease = acquire_material_lease(root, expected_entries=entries, expected_tree_sha256=tree_sha)
    try:
        lease.verify_streams()
        with open(str(root / "a.txt") + ":tardio", "w", encoding="ascii") as stream:
            stream.write("plantado")
        with pytest.raises(LeaseStreamError, match=r"stream no predeterminado.*tardio"):
            lease.verify_streams()
        os.remove(str(root / "a.txt") + ":tardio")
        lease.verify_streams()
    finally:
        lease.release()


def test_matriz_de_volumen_rechaza_filesystem_unidad_serial_y_multivolumen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Oráculo «volumen» de §8.1: la matriz cerrada rechaza todo lo no medido."""
    root, entries, tree_sha = _material(tmp_path)

    def _volumen(respuesta: dict[str, Any]) -> None:
        monkeypatch.setattr(
            material_lease,
            "_query_volume_by_handle",
            lambda handle, path: respuesta,
        )

    _volumen({"filesystem": "FAT32", "volume_serial": 1, "volume_root": "C:\\", "drive_type": 3})
    with pytest.raises(LeaseVolumeError, match=r"filesystem no calificado.*FAT32"):
        acquire_material_lease(root, expected_entries=entries, expected_tree_sha256=tree_sha)
    _volumen({"filesystem": "NTFS", "volume_serial": 1, "volume_root": "Z:\\", "drive_type": 4})
    with pytest.raises(LeaseVolumeError, match=r"unidad no calificada.*tipo 4"):
        acquire_material_lease(root, expected_entries=entries, expected_tree_sha256=tree_sha)
    _volumen({"filesystem": "NTFS", "volume_serial": 1, "volume_root": "C:\\", "drive_type": 3})
    with pytest.raises(LeaseVolumeError, match="serial del volumen no reconcilia"):
        acquire_material_lease(root, expected_entries=entries, expected_tree_sha256=tree_sha)
    monkeypatch.undo()
    _exigir_escritura_exclusiva(root / "a.txt")
    lease = acquire_material_lease(root, expected_entries=entries, expected_tree_sha256=tree_sha)
    try:
        atestacion = lease.attestation()
        assert atestacion["volume"]["filesystem"] == "NTFS"
        assert atestacion["volume"]["drive_type"] == 3
    finally:
        lease.release()
    serial = 7
    base = material_lease._LeasedEntry(
        relative_path=".",
        kind="directory",
        path=root,
        handle=0,
        volume_serial=serial,
        file_index=1,
        logical_bytes=0,
    )
    ajeno = material_lease._LeasedEntry(
        relative_path="pkg/b.bin",
        kind="file",
        path=root / "pkg" / "b.bin",
        handle=0,
        volume_serial=serial + 1,
        file_index=2,
        logical_bytes=10,
    )
    with pytest.raises(LeaseVolumeError, match=r"material multivolumen.*b\.bin"):
        material_lease._require_qualified_volume(
            {"filesystem": "NTFS", "volume_serial": serial, "volume_root": "C:\\", "drive_type": 3},
            [base, ajeno],
        )


def test_no_follow_toma_el_reparse_point_y_no_su_destino(tmp_path: Path) -> None:
    """Oráculo «no-follow» de §8.1, medido sobre el handle: se captura el punto de reparse.

    Con el pin de ancestros vivo ya no cabe interponer la junction en mitad de la
    adquisición —el ancestro fijado lo impide—, así que el flag se ejerce en su unidad:
    ``FILE_FLAG_OPEN_REPARSE_POINT`` debe devolver el reparse point, no el directorio
    destino, y el conjunto debe rechazarlo por esa vía.
    """
    destino = tmp_path / "destino"
    destino.mkdir()
    (destino / "interior.txt").write_bytes(b"interior")
    enlace = tmp_path / "enlace"
    _junction_o_skip(enlace, destino)

    handle = material_lease._open_lease_handle(enlace, directory=True)
    try:
        identidad = material_lease._census_handle_identity(handle, enlace)
        assert identidad.attributes & material_lease._FILE_ATTRIBUTE_REPARSE_POINT, (
            "el handle debía tomar el punto de reparse, no seguirlo hasta su destino"
        )
        assert identidad.file_index != os.stat(destino).st_ino, (
            "el handle no puede identificarse con el directorio destino"
        )
    finally:
        material_lease._close_handles([handle])

    # Y por la cara del conjunto: una junction dentro del árbol se rechaza al enumerar.
    root = tmp_path / "material"
    root.mkdir()
    (root / "a.txt").write_bytes(b"alpha")
    identity = canonical_tree_identity(root, include_entries=True)
    _junction_o_skip(root / "lib", destino)
    with pytest.raises(LeaseAcquisitionError, match="reparse point prohibido"):
        acquire_material_lease(
            root,
            expected_entries=identity["entries"],
            expected_tree_sha256=str(identity["sha256"]),
        )
    os.rmdir(root / "lib")
    _exigir_escritura_exclusiva(root / "a.txt")


def test_material_divergente_del_inventario_reconcilia_en_rojo(tmp_path: Path) -> None:
    """El digest firmado debe describir los bytes leaseados, no una foto vieja (D-LEA-7)."""
    root, entries, tree_sha = _material(tmp_path)
    (root / "a.txt").write_bytes(b"alfa!")
    lease = acquire_material_lease(root, expected_entries=entries, expected_tree_sha256=tree_sha)
    try:
        with pytest.raises(LeaseCoverageError, match=r"no reconcilia con el inventario: a\.txt"):
            lease.hash_and_verify()
    finally:
        lease.release()


def test_release_verificado_y_lease_no_reutilizable(tmp_path: Path) -> None:
    root, entries, tree_sha = _material(tmp_path)
    lease = acquire_material_lease(root, expected_entries=entries, expected_tree_sha256=tree_sha)
    lease.release()
    assert lease.released
    with pytest.raises(LeaseOrderError, match="liberado antes del hash"):
        lease.hash_and_verify()
    with pytest.raises(LeaseReleaseError, match="ya fue liberado"):
        lease.release()
    for relative in ("a.txt", "pkg/b.bin"):
        _exigir_escritura_exclusiva(root / Path(relative))


def test_inventario_que_no_liga_con_el_digest_se_rechaza(tmp_path: Path) -> None:
    root, entries, _ = _material(tmp_path)
    with pytest.raises(LeaseCoverageError, match="no liga con el digest agregado"):
        acquire_material_lease(root, expected_entries=entries, expected_tree_sha256="1" * 64)
    _exigir_escritura_exclusiva(root / "a.txt")


def test_directorio_vacio_no_declarado_reconcilia_en_rojo(tmp_path: Path) -> None:
    root, entries, tree_sha = _material(tmp_path)
    (root / "hueco").mkdir()
    with pytest.raises(LeaseCoverageError, match=r"directorio no declarado.*hueco"):
        acquire_material_lease(root, expected_entries=entries, expected_tree_sha256=tree_sha)
    _exigir_escritura_exclusiva(root / "a.txt")


def test_ads_tardio_pone_roja_la_liberacion_sin_llamadas_auxiliares(tmp_path: Path) -> None:
    """Hallazgo de revisión A.1: el ciclo natural adquirir→hash→release censa el ADS solo."""
    root, entries, tree_sha = _material(tmp_path)
    lease = acquire_material_lease(root, expected_entries=entries, expected_tree_sha256=tree_sha)
    with open(str(root / "a.txt") + ":tardio-release", "w", encoding="ascii") as stream:
        stream.write("plantado")
    lease.hash_and_verify()
    with pytest.raises(LeaseStreamError, match=r"stream no predeterminado.*tardio-release"):
        lease.release()
    assert lease.released, "los handles debían quedar cerrados pese al censo rojo"
    _exigir_escritura_exclusiva(root / "a.txt")
    os.remove(str(root / "a.txt") + ":tardio-release")


def test_fallo_de_closehandle_no_declara_liberado_y_permite_reintentar(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Hallazgo de revisión A.1: un CloseHandle fallido conserva el handle como vivo."""
    root, entries, tree_sha = _material(tmp_path)
    lease = acquire_material_lease(root, expected_entries=entries, expected_tree_sha256=tree_sha)
    objetivo = lease._entries[0].handle
    cierre_real = material_lease._close_handle
    fallo = {"pendiente": True}

    def _cierre_defectuoso(handle: int) -> int:
        if handle == objetivo and fallo["pendiente"]:
            fallo["pendiente"] = False
            return 6
        return cierre_real(handle)

    monkeypatch.setattr(material_lease, "_close_handle", _cierre_defectuoso)
    with pytest.raises(LeaseReleaseError, match=r"handles vivos.*winerror=6"):
        lease.release()
    assert lease.released is False, "una liberación fallida no puede declararse liberada"
    with pytest.raises(LeaseOrderError, match="liberación parcial"):
        lease.hash_and_verify()
    monkeypatch.undo()
    lease.release()
    assert lease.released
    _exigir_escritura_exclusiva(root / "a.txt")


def test_deadline_rige_dentro_de_enumeracion_y_cotejo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Hallazgo de revisión A.1: el deadline se comprueba durante los recorridos, no sólo antes."""
    root, entries, tree_sha = _material(tmp_path)
    vencido = time.monotonic() - 1.0
    with pytest.raises(MaterialLeaseError, match="preflight_rejected"):
        material_lease._acquire_directory_children(root, deadline_monotonic=vencido)
    with pytest.raises(MaterialLeaseError, match="preflight_rejected"):
        material_lease._verification_census(root, deadline_monotonic=vencido)
    reloj_real = time.monotonic
    base = reloj_real()
    llamadas = {"n": 0}

    def _reloj_que_salta() -> float:
        llamadas["n"] += 1
        return base if llamadas["n"] <= 3 else base + 1000.0

    monkeypatch.setattr(time, "monotonic", _reloj_que_salta)
    try:
        with pytest.raises(MaterialLeaseError, match="preflight_rejected"):
            acquire_material_lease(
                root,
                expected_entries=entries,
                expected_tree_sha256=tree_sha,
                deadline_monotonic=base + 500.0,
            )
    finally:
        monkeypatch.undo()
    _exigir_escritura_exclusiva(root / "a.txt")


def test_ancestro_reparse_del_ancla_reconcilia_en_rojo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Segunda revisión A.1: el ancla se censa sin reparse points al abrir y al cerrar."""
    caja = tmp_path / "caja"
    root = caja / "material"
    (root / "pkg").mkdir(parents=True)
    (root / "a.txt").write_bytes(b"alpha")
    (root / "pkg" / "b.bin").write_bytes(b"beta")
    identity = canonical_tree_identity(root, include_entries=True)
    movida = tmp_path / "caja-real"

    def _swap_ancla() -> None:
        os.rename(caja, movida)
        _junction_o_skip(caja, movida)

    def _restaurar_ancla() -> None:
        if movida.exists():
            if os.path.lexists(caja):
                os.rmdir(caja)
            os.rename(movida, caja)

    # Brazo 1: junction interpuesta ANTES de adquirir -> censo inicial rojo.
    _swap_ancla()
    try:
        with pytest.raises(
            LeaseAcquisitionError, match=r"ancla del lease: reparse point en la ruta"
        ):
            acquire_material_lease(
                root,
                expected_entries=identity["entries"],
                expected_tree_sha256=str(identity["sha256"]),
            )
    finally:
        _restaurar_ancla()
    # Brazo 2: junction interpuesta entre el censo inicial del ancla y el CreateFileW de la
    # raíz (medido: con el handle raíz vivo, renombrar un ancestro da winerror=5, así que la
    # ventana termina en el primer handle) -> censo de cierre rojo.
    apertura_real = material_lease._open_lease_handle

    def _interpone_ancla(path: Path, *, directory: bool) -> int:
        if not movida.exists():
            _swap_ancla()
        return apertura_real(path, directory=directory)

    monkeypatch.setattr(material_lease, "_open_lease_handle", _interpone_ancla)
    try:
        with pytest.raises(LeaseAcquisitionError, match=r"reparse point en un ancestro del ancla"):
            acquire_material_lease(
                root,
                expected_entries=identity["entries"],
                expected_tree_sha256=str(identity["sha256"]),
            )
    finally:
        monkeypatch.undo()
        _restaurar_ancla()
    _exigir_escritura_exclusiva(root / "a.txt")


def test_ancestro_fijado_impide_la_interposicion_transitoria(tmp_path: Path) -> None:
    """Tercera revisión A.1: el pin de ancestros cierra la carrera del señuelo.

    Medido en esta torre: un handle abierto **a través** de una junction no fija esa
    junction —se la puede retirar y recolocar—, de modo que sin pin el lease retendría un
    señuelo byte-idéntico mientras la ruta vuelve a resolver al árbol real. Con cada
    ancestro fijado por su propio handle, retirar la junction falla.
    """
    real = tmp_path / "caja-real" / "material"
    decoy = tmp_path / "caja-decoy" / "material"
    for arbol in (real, decoy):
        arbol.mkdir(parents=True)
        (arbol / "a.txt").write_bytes(b"alpha")
    identity = canonical_tree_identity(real, include_entries=True)
    caja = tmp_path / "caja"
    _junction_o_skip(caja, tmp_path / "caja-decoy")
    ruta_expuesta = caja / "material"

    # Vacuidad de la carrera: con handles abiertos por la junction pero sin fijar el
    # ancestro, la junction se retira y la ruta pasa a resolver al árbol real.
    handle_suelto = material_lease._open_lease_handle(ruta_expuesta, directory=True)
    try:
        os.rmdir(caja)
    finally:
        material_lease._close_handles([handle_suelto])
    _junction_o_skip(caja, tmp_path / "caja-decoy")

    # Con el lease vivo, cada ancestro queda fijado y la junction ya no se puede retirar.
    lease = acquire_material_lease(
        real,
        expected_entries=identity["entries"],
        expected_tree_sha256=str(identity["sha256"]),
    )
    try:
        assert lease.attestation()["pinned_ancestors"] >= 1
        with pytest.raises(PermissionError):
            os.rmdir(tmp_path / "caja-real")
    finally:
        lease.release()
        if os.path.lexists(caja):
            os.rmdir(caja)
    _exigir_escritura_exclusiva(real / "a.txt")


def test_violacion_de_streams_sobrevive_a_un_closehandle_fallido(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Segunda revisión A.1: el ADS detectado es terminal aunque otro cierre falle."""
    root, entries, tree_sha = _material(tmp_path)
    lease = acquire_material_lease(root, expected_entries=entries, expected_tree_sha256=tree_sha)
    with open(str(root / "a.txt") + ":tardio-mixto", "w", encoding="ascii") as stream:
        stream.write("plantado")
    objetivo = lease._entries[0].handle
    cierre_real = material_lease._close_handle
    fallo = {"pendiente": True}

    def _cierre_defectuoso(handle: int) -> int:
        if handle == objetivo and fallo["pendiente"]:
            fallo["pendiente"] = False
            return 6
        return cierre_real(handle)

    monkeypatch.setattr(material_lease, "_close_handle", _cierre_defectuoso)
    with pytest.raises(LeaseReleaseError, match="handles vivos"):
        lease.release()
    assert lease.released is False
    monkeypatch.undo()
    with pytest.raises(LeaseStreamError, match=r"stream no predeterminado.*tardio-mixto"):
        lease.release()
    assert lease.released, "el reintento debía completar el cierre sin volverse éxito"
    _exigir_escritura_exclusiva(root / "a.txt")
    os.remove(str(root / "a.txt") + ":tardio-mixto")


def test_rollback_fallido_conserva_los_handles_pendientes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Segunda revisión A.1: una adquisición fallida no pierde handles cuyo cierre falló."""
    root, entries, tree_sha = _material(tmp_path)
    (root / "pkg" / "plantado.txt").write_bytes(b"alta")
    cierre_real = material_lease._close_handle
    fallo = {"pendiente": True}

    def _cierre_defectuoso(handle: int) -> int:
        if fallo["pendiente"]:
            fallo["pendiente"] = False
            return 6
        return cierre_real(handle)

    monkeypatch.setattr(material_lease, "_close_handle", _cierre_defectuoso)
    with pytest.raises(LeaseReleaseError, match=r"rollback.*handles vivos") as excinfo:
        acquire_material_lease(root, expected_entries=entries, expected_tree_sha256=tree_sha)
    monkeypatch.undo()
    assert isinstance(excinfo.value.__cause__, LeaseCoverageError)
    pendientes = excinfo.value.pending_handles
    assert len(pendientes) == 1, "el dueño debía conservar exactamente el handle fallido"
    assert material_lease._close_handles(list(pendientes)) == []
    (root / "pkg" / "plantado.txt").unlink()
    for relative in ("a.txt", "pkg/b.bin"):
        _exigir_escritura_exclusiva(root / Path(relative))


def test_deadline_vencido_falla_cerrado(tmp_path: Path) -> None:
    root, entries, tree_sha = _material(tmp_path)
    with pytest.raises(MaterialLeaseError, match="preflight_rejected"):
        acquire_material_lease(
            root,
            expected_entries=entries,
            expected_tree_sha256=tree_sha,
            deadline_monotonic=time.monotonic() - 1.0,
        )
    _exigir_escritura_exclusiva(root / "a.txt")


def test_atestacion_censa_mecanismo_volumen_y_entradas(tmp_path: Path) -> None:
    root, entries, tree_sha = _material(tmp_path)
    lease = acquire_material_lease(root, expected_entries=entries, expected_tree_sha256=tree_sha)
    try:
        censo = lease.attestation()
        assert censo["mechanism"] == material_lease.CANDIDATE_MATERIAL_LEASE_MECHANISM
        assert censo["mechanism"] == "windows_share_mode_lease_v1"
        assert censo["files"] == len(entries)
        assert censo["directories"] == 2
        assert censo["released"] is False
        assert {entrada["kind"] for entrada in censo["entries"]} == {"directory", "file"}
        # D-LEA-18/D-LEA-5: el censo publica el inventario canónico ya ligado al digest.
        declarados = {item["relative_path"]: item["sha256"] for item in entries}
        for entrada in censo["entries"]:
            if entrada["kind"] == "file":
                assert entrada["sha256"] == declarados[entrada["relative_path"]]
            else:
                assert entrada["sha256"] is None
        assert isinstance(censo["acquisition_started_monotonic_ns"], int)
        assert censo["release_completed_monotonic_ns"] is None
    finally:
        lease.release()
    censo_final = lease.attestation()
    assert censo_final["released"] is True
    assert isinstance(censo_final["release_completed_monotonic_ns"], int)
    assert (
        censo_final["release_completed_monotonic_ns"]
        >= censo_final["acquisition_started_monotonic_ns"]
    )
