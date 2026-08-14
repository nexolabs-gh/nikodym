from __future__ import annotations

import base64
import ctypes
import hashlib
import os
import subprocess
import sys
import threading
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, cast

import pytest

import scripts.measure_readiness_h9r as h9r_driver
import scripts.readiness_h9r.runtime_snapshot as runtime_snapshot_module
from scripts.measure_readiness_h9r import _verify_harness_source_snapshot
from scripts.readiness_h9r.runtime_snapshot import (
    EXPECTED_IMPORT_ROOTS,
    PRODUCT_DISTRIBUTIONS,
    RuntimeSnapshotError,
    _assert_copied_root_matches_record,
    _record_entries,
    materialize_harness_source_snapshot,
    validate_harness_source_snapshot,
)


@pytest.fixture(autouse=True)
def _close_snapshot_leases_around_test(tmp_path: Path) -> Iterator[None]:
    del tmp_path
    runtime_snapshot_module._release_snapshot_leases_for_tests()
    h9r_driver._release_snapshot_leases_for_tests()
    yield
    runtime_snapshot_module._release_snapshot_leases_for_tests()
    h9r_driver._release_snapshot_leases_for_tests()


def _materialize(tmp_path: Path) -> dict[str, object]:
    scratch = tmp_path / "scratch"
    control = tmp_path / "telemetry" / "control"
    scratch.mkdir()
    control.mkdir(parents=True)
    identity = cast(
        dict[str, object],
        materialize_harness_source_snapshot(
            destination_root=scratch / "harness-runtime-snapshot",
            manifest_path=control / "harness-runtime-snapshot.json",
            source_tooling_manifest_sha256="a" * 64,
            include_product_runtime=False,
        ),
    )
    runtime_snapshot_module._release_snapshot_leases_for_tests()
    return identity


def test_materializa_y_reabre_snapshot_canonico_o_excl(tmp_path: Path) -> None:
    identity = _materialize(tmp_path)
    value = identity["value"]
    assert isinstance(value, dict)
    assert value["source_tooling_manifest_sha256"] == "a" * 64
    assert value["import_roots"] == []
    assert identity == validate_harness_source_snapshot(
        manifest_path=Path(str(identity["path"])),
        expected_manifest_sha256=str(identity["sha256"]),
        expected_source_tooling_manifest_sha256="a" * 64,
    )
    with pytest.raises(RuntimeSnapshotError, match="ya existe"):
        materialize_harness_source_snapshot(
            destination_root=Path(str(value["root"])),
            manifest_path=Path(str(identity["path"])),
            source_tooling_manifest_sha256="a" * 64,
            include_product_runtime=False,
        )


def test_materializacion_rechaza_parent_manifest_ausente(tmp_path: Path) -> None:
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    with pytest.raises(RuntimeSnapshotError, match=r"parents.*deben existir"):
        materialize_harness_source_snapshot(
            destination_root=scratch / "snapshot",
            manifest_path=tmp_path / "missing" / "manifest.json",
            source_tooling_manifest_sha256="a" * 64,
            include_product_runtime=False,
        )
    assert not (scratch / "snapshot").exists()


def test_snapshot_compartido_reconcilia_bootloader_driver(tmp_path: Path) -> None:
    identity = _materialize(tmp_path)
    value = identity["value"]
    assert isinstance(value, dict)
    driver_value = {**value, "manifest_path": str(identity["path"])}
    assert _verify_harness_source_snapshot(driver_value) == driver_value


def test_reapertura_rechaza_import_root_extra_no_firmado(tmp_path: Path) -> None:
    identity = _materialize(tmp_path)
    value = identity["value"]
    assert isinstance(value, dict)
    (Path(str(value["root"])) / "import-roots" / "extra").mkdir()
    with pytest.raises(RuntimeSnapshotError, match="roots extra/faltantes"):
        validate_harness_source_snapshot(
            manifest_path=Path(str(identity["path"])),
            expected_manifest_sha256=str(identity["sha256"]),
            expected_source_tooling_manifest_sha256="a" * 64,
        )


def test_reapertura_rechaza_pycache_dentro_de_import_root(tmp_path: Path) -> None:
    identity = _materialize(tmp_path)
    value = identity["value"]
    assert isinstance(value, dict)
    container = Path(str(value["root"])) / "import-roots" / "foo"
    container.mkdir()
    (container / "foo.py").write_bytes(b"signed")
    core = {
        **{name: item for name, item in value.items() if name != "manifest_sha256"},
        "import_roots": [
            {
                "name": "foo",
                "kind": "import_parent",
                "path": str(container),
                **runtime_snapshot_module._tree_identity(container),
            }
        ],
    }
    rebound = {
        **core,
        "manifest_sha256": hashlib.sha256(
            runtime_snapshot_module._canonical_json(core)
        ).hexdigest(),
    }
    manifest_bytes = runtime_snapshot_module._canonical_json(rebound) + b"\n"
    manifest_path = Path(str(identity["path"]))
    manifest_path.write_bytes(manifest_bytes)
    cache = container / "__pycache__"
    cache.mkdir()
    (cache / "evil.pyc").write_bytes(b"not-signed")
    with pytest.raises(RuntimeSnapshotError, match="__pycache__ no firmado"):
        validate_harness_source_snapshot(
            manifest_path=manifest_path,
            expected_manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
            expected_source_tooling_manifest_sha256="a" * 64,
        )


def test_reapertura_rechaza_pycache_no_firmado(tmp_path: Path) -> None:
    identity = _materialize(tmp_path)
    value = identity["value"]
    assert isinstance(value, dict)
    cache = Path(str(value["root"])) / "scripts" / "readiness_h9r" / "__pycache__"
    cache.mkdir()
    (cache / "contracts.cpython-312.pyc").write_bytes(b"no-firmado")
    with pytest.raises(RuntimeSnapshotError, match="__pycache__ no firmado"):
        validate_harness_source_snapshot(
            manifest_path=Path(str(identity["path"])),
            expected_manifest_sha256=str(identity["sha256"]),
            expected_source_tooling_manifest_sha256="a" * 64,
        )


def test_reapertura_rechaza_pycache_extra_en_contenedor_scripts(tmp_path: Path) -> None:
    identity = _materialize(tmp_path)
    value = identity["value"]
    assert isinstance(value, dict)
    cache = Path(str(value["root"])) / "scripts" / "__pycache__"
    cache.mkdir()
    (cache / "evil.pyc").write_bytes(b"no-firmado")
    with pytest.raises(RuntimeSnapshotError, match=r"scripts.*extra/faltantes"):
        validate_harness_source_snapshot(
            manifest_path=Path(str(identity["path"])),
            expected_manifest_sha256=str(identity["sha256"]),
            expected_source_tooling_manifest_sha256="a" * 64,
        )


def test_lease_windows_permanece_hasta_liberacion_del_proceso(tmp_path: Path) -> None:
    identity = _materialize(tmp_path)
    value = identity["value"]
    assert isinstance(value, dict)
    snapshot_root = Path(str(value["root"]))
    source = snapshot_root / "scripts" / "readiness_h9r" / "contracts.py"
    late_source = source.parent / "late.py"
    late_import_root = snapshot_root / "import-roots" / "late"
    before = source.read_bytes()
    observed = validate_harness_source_snapshot(
        manifest_path=Path(str(identity["path"])),
        expected_manifest_sha256=str(identity["sha256"]),
        expected_source_tooling_manifest_sha256="a" * 64,
    )
    assert observed == identity
    if sys.platform != "win32":
        assert runtime_snapshot_module._WINDOWS_SNAPSHOT_LEASES == {}
        return
    assert runtime_snapshot_module._WINDOWS_SNAPSHOT_LEASES
    with pytest.raises(PermissionError):
        source.write_bytes(before + b"\n# no debe entrar\n")
    replacement = tmp_path / "replacement.py"
    replacement.write_bytes(b"replacement")
    with pytest.raises(PermissionError):
        os.replace(replacement, source)
    with pytest.raises(PermissionError):
        source.unlink()
    with pytest.raises(PermissionError):
        late_source.write_bytes(b"no debe entrar")
    with pytest.raises(PermissionError):
        late_import_root.mkdir()
    assert not late_source.exists()
    assert not late_import_root.exists()
    runtime_snapshot_module._release_snapshot_leases_for_tests()
    runtime_snapshot_module._release_snapshot_leases_for_tests()
    source.write_bytes(before)
    late_source.write_bytes(b"entra tras liberar")
    late_import_root.mkdir()


def test_release_runtime_fallido_conserva_estado_hasta_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if sys.platform != "win32":
        pytest.skip("el lease DACL sólo existe en Windows")
    identity = _materialize(tmp_path)
    validate_harness_source_snapshot(
        manifest_path=Path(str(identity["path"])),
        expected_manifest_sha256=str(identity["sha256"]),
        expected_source_tooling_manifest_sha256="a" * 64,
    )
    key, lease = next(iter(runtime_snapshot_module._WINDOWS_SNAPSHOT_LEASES.items()))
    handles = tuple(lease.handles)
    seals = tuple(lease.acl_seals)
    failed_seal = seals[-1]
    descriptor = failed_seal.security_descriptor
    original_restore = failed_seal.restore
    restore_calls = 0

    def fail_once() -> None:
        nonlocal restore_calls
        restore_calls += 1
        if restore_calls == 1:
            raise RuntimeSnapshotError("fallo inyectado de restauración")
        original_restore()

    monkeypatch.setattr(failed_seal, "restore", fail_once)
    with pytest.raises(RuntimeSnapshotError, match="fallo inyectado de restauración"):
        runtime_snapshot_module._release_snapshot_leases_for_tests()

    assert runtime_snapshot_module._WINDOWS_SNAPSHOT_LEASES[key] is lease
    assert lease.state == "restoring"
    assert tuple(lease.handles) == handles
    assert tuple(lease.acl_seals) == seals
    assert failed_seal.security_descriptor == descriptor != 0
    probe = failed_seal.path / "retry-probe"
    with pytest.raises(PermissionError):
        probe.mkdir()

    runtime_snapshot_module._release_snapshot_leases_for_tests()
    assert runtime_snapshot_module._WINDOWS_SNAPSHOT_LEASES == {}
    assert lease.state == "closed"
    assert lease.handles == []
    assert lease.acl_seals == []
    probe.mkdir()
    probe.rmdir()


def test_rollback_precommit_fallido_queda_registrado_para_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if sys.platform != "win32":
        pytest.skip("el lease DACL sólo existe en Windows")
    identity = _materialize(tmp_path)
    original_reader = runtime_snapshot_module._read_bound_bytes
    original_restore = runtime_snapshot_module._WindowsAclSeal.restore
    restore_calls = 0

    def fail_after_acquire(
        path: Path,
        *,
        context: str,
        require_single_link: bool = True,
    ) -> tuple[Path, bytes, os.stat_result]:
        if context == "manifest del snapshot bajo lease":
            raise RuntimeSnapshotError("fallo de validación inyectado")
        return original_reader(
            path,
            context=context,
            require_single_link=require_single_link,
        )

    def fail_restore_once(self: runtime_snapshot_module._WindowsAclSeal) -> None:
        nonlocal restore_calls
        restore_calls += 1
        if restore_calls == 1:
            raise RuntimeSnapshotError("fallo de rollback inyectado")
        original_restore(self)

    monkeypatch.setattr(runtime_snapshot_module, "_read_bound_bytes", fail_after_acquire)
    monkeypatch.setattr(
        runtime_snapshot_module._WindowsAclSeal,
        "restore",
        fail_restore_once,
    )
    with pytest.raises(RuntimeSnapshotError, match="fallo de rollback inyectado"):
        validate_harness_source_snapshot(
            manifest_path=Path(str(identity["path"])),
            expected_manifest_sha256=str(identity["sha256"]),
            expected_source_tooling_manifest_sha256="a" * 64,
        )

    lease = next(iter(runtime_snapshot_module._WINDOWS_SNAPSHOT_LEASES.values()))
    assert lease.state == "restoring"
    assert lease.handles
    assert lease.acl_seals
    assert all(seal.security_descriptor != 0 for seal in lease.acl_seals)
    runtime_snapshot_module._release_snapshot_leases_for_tests()
    assert lease.state == "closed"
    assert runtime_snapshot_module._WINDOWS_SNAPSHOT_LEASES == {}


def test_closehandle_fallido_no_reutiliza_lease_degradado_y_admite_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if sys.platform != "win32":
        pytest.skip("los handles de snapshot sólo existen en Windows")
    identity = _materialize(tmp_path)
    validate_harness_source_snapshot(
        manifest_path=Path(str(identity["path"])),
        expected_manifest_sha256=str(identity["sha256"]),
        expected_source_tooling_manifest_sha256="a" * 64,
    )
    lease = next(iter(runtime_snapshot_module._WINDOWS_SNAPSHOT_LEASES.values()))
    handles = tuple(lease.handles)
    seals = tuple(lease.acl_seals)
    original_close = runtime_snapshot_module._close_windows_handle
    close_calls = 0

    def fail_close_once(handle: int) -> None:
        nonlocal close_calls
        close_calls += 1
        if close_calls == 1:
            raise RuntimeSnapshotError("fallo CloseHandle inyectado")
        original_close(handle)

    monkeypatch.setattr(runtime_snapshot_module, "_close_windows_handle", fail_close_once)
    with pytest.raises(RuntimeSnapshotError, match="fallo CloseHandle inyectado"):
        runtime_snapshot_module._release_snapshot_leases_for_tests()

    assert lease.state == "restored"
    assert tuple(lease.handles) == handles
    assert tuple(lease.acl_seals) == seals
    assert all(seal.security_descriptor != 0 for seal in lease.acl_seals)
    with pytest.raises(RuntimeSnapshotError, match="cleanup pendiente"):
        validate_harness_source_snapshot(
            manifest_path=Path(str(identity["path"])),
            expected_manifest_sha256=str(identity["sha256"]),
            expected_source_tooling_manifest_sha256="a" * 64,
        )

    runtime_snapshot_module._release_snapshot_leases_for_tests()
    assert lease.state == "closed"
    assert lease.handles == []
    assert lease.acl_seals == []
    assert runtime_snapshot_module._WINDOWS_SNAPSHOT_LEASES == {}


def test_reserva_concurrente_del_lease_tiene_un_solo_ganador(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if sys.platform != "win32":
        pytest.skip("la reserva de handles sólo existe en Windows")
    identity = _materialize(tmp_path)
    value = identity["value"]
    assert isinstance(value, dict)
    manifest_path = Path(str(identity["path"]))
    root = Path(str(value["root"]))
    files, directories = runtime_snapshot_module._snapshot_lease_census(
        manifest_path=manifest_path,
        root=root,
        import_root_names=set(),
    )
    original_init = runtime_snapshot_module._WindowsSnapshotLease.__init__
    candidates_ready = threading.Barrier(2)

    def synchronized_init(
        self: runtime_snapshot_module._WindowsSnapshotLease,
        **kwargs: Any,
    ) -> None:
        original_init(self, **kwargs)
        candidates_ready.wait(timeout=10)

    monkeypatch.setattr(
        runtime_snapshot_module._WindowsSnapshotLease,
        "__init__",
        synchronized_init,
    )

    def acquire() -> (
        tuple[runtime_snapshot_module._WindowsSnapshotLease | None, bool] | BaseException
    ):
        try:
            return runtime_snapshot_module._acquire_windows_snapshot_lease(
                manifest_path=manifest_path,
                root=root,
                files=files,
                directories=directories,
            )
        except BaseException as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = [
            future.result(timeout=30)
            for future in (executor.submit(acquire), executor.submit(acquire))
        ]

    successes = [result for result in results if isinstance(result, tuple)]
    failures = [result for result in results if isinstance(result, BaseException)]
    assert len(successes) == 1
    assert len(failures) == 1
    assert "cleanup pendiente" in str(failures[0])
    lease, fresh = successes[0]
    assert lease is not None
    assert fresh is True
    assert {lease.key: lease} == runtime_snapshot_module._WINDOWS_SNAPSHOT_LEASES
    assert lease.state == "acquiring"
    lease.activate()
    runtime_snapshot_module._release_snapshot_leases_for_tests()
    assert lease.state == "closed"


def test_restauracion_dacl_autoheredada_es_exacta_e_idempotente(tmp_path: Path) -> None:
    if sys.platform != "win32":
        pytest.skip("DACL auto-heredada sólo existe en Windows")
    directory = tmp_path / "auto-inherited"
    directory.mkdir()
    handles: list[int] = []
    handle = runtime_snapshot_module._open_windows_read_lease(
        directory,
        directory=True,
        context="directorio auto-heredado de prueba",
        handles=handles,
    )
    seal = None
    seals: list[runtime_snapshot_module._WindowsAclSeal] = []
    try:
        dacl, descriptor, _, _ = runtime_snapshot_module._windows_dacl_state(handle)
        try:
            advapi32 = runtime_snapshot_module._windows_advapi32()
            set_security_info = advapi32.SetSecurityInfo
            set_security_info.argtypes = [
                ctypes.c_void_p,
                ctypes.c_uint32,
                ctypes.c_uint32,
                ctypes.c_void_p,
                ctypes.c_void_p,
                ctypes.c_void_p,
                ctypes.c_void_p,
            ]
            set_security_info.restype = ctypes.c_uint32
            status = int(
                set_security_info(
                    ctypes.c_void_p(handle),
                    runtime_snapshot_module._WINDOWS_SE_FILE_OBJECT,
                    runtime_snapshot_module._WINDOWS_DACL_SECURITY_INFORMATION
                    | runtime_snapshot_module._WINDOWS_UNPROTECTED_DACL_SECURITY_INFORMATION,
                    None,
                    None,
                    ctypes.c_void_p(dacl),
                    None,
                )
            )
            assert status == 0
        finally:
            runtime_snapshot_module._windows_local_free(descriptor)
        control, _ = runtime_snapshot_module._windows_dacl_signature(handle)
        assert control & runtime_snapshot_module._WINDOWS_SE_DACL_AUTO_INHERITED
        sid_buffer, sid = runtime_snapshot_module._windows_current_user_sid()
        try:
            seal = runtime_snapshot_module._apply_windows_directory_seal(
                handle,
                path=directory,
                sid=sid,
                seals=seals,
            )
        finally:
            del sid_buffer
        with pytest.raises(PermissionError):
            (directory / "late").mkdir()
        seal.restore()
        seal.restore()
        seal.assert_restored()
        seal.finalize()
        seal.finalize()
        (directory / "late").mkdir()
    finally:
        if seal is not None:
            seal.restore()
            seal.assert_restored()
            seal.finalize()
        runtime_snapshot_module._close_windows_handle(handle)
        handles.clear()


def test_cierre_global_detecta_mutacion_cruzada_de_fuente(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity = _materialize(tmp_path)
    value = identity["value"]
    assert isinstance(value, dict)
    source = Path(str(value["root"])) / "scripts" / "readiness_h9r" / "contracts.py"
    before = source.read_bytes()
    original = runtime_snapshot_module._snapshot_lease_census
    calls = 0
    mutation_blocked = False

    def mutate_during_leased_census(
        *,
        manifest_path: Path,
        root: Path,
        import_root_names: set[str],
    ) -> tuple[tuple[Path, ...], tuple[Path, ...]]:
        nonlocal calls, mutation_blocked
        result = original(
            manifest_path=manifest_path,
            root=root,
            import_root_names=import_root_names,
        )
        calls += 1
        if calls == 2:
            try:
                source.write_bytes(before + b"\n# drift cruzado\n")
            except PermissionError:
                mutation_blocked = True
        return result

    monkeypatch.setattr(
        runtime_snapshot_module,
        "_snapshot_lease_census",
        mutate_during_leased_census,
    )
    if sys.platform == "win32":
        observed = validate_harness_source_snapshot(
            manifest_path=Path(str(identity["path"])),
            expected_manifest_sha256=str(identity["sha256"]),
            expected_source_tooling_manifest_sha256="a" * 64,
        )
        assert observed == identity
        assert mutation_blocked is True
        assert source.read_bytes() == before
    else:
        with pytest.raises(RuntimeSnapshotError, match=r"no reconcilia|cambió"):
            validate_harness_source_snapshot(
                manifest_path=Path(str(identity["path"])),
                expected_manifest_sha256=str(identity["sha256"]),
                expected_source_tooling_manifest_sha256="a" * 64,
            )
        assert mutation_blocked is False


def test_reapertura_detecta_payload_fuente_alterado(tmp_path: Path) -> None:
    identity = _materialize(tmp_path)
    value = identity["value"]
    assert isinstance(value, dict)
    source = Path(str(value["root"])) / "scripts" / "readiness_h9r" / "contracts.py"
    source.write_bytes(source.read_bytes() + b"\n# drift\n")
    with pytest.raises(RuntimeSnapshotError, match="fuentes del snapshot no reconcilia"):
        validate_harness_source_snapshot(
            manifest_path=Path(str(identity["path"])),
            expected_manifest_sha256=str(identity["sha256"]),
            expected_source_tooling_manifest_sha256="a" * 64,
        )


@pytest.mark.parametrize("target_kind", ["manifest", "source"])
def test_reapertura_rechaza_hardlink_contractual(
    tmp_path: Path,
    target_kind: str,
) -> None:
    identity = _materialize(tmp_path)
    value = identity["value"]
    assert isinstance(value, dict)
    target = (
        Path(str(identity["path"]))
        if target_kind == "manifest"
        else Path(str(value["root"])) / "scripts" / "readiness_h9r" / "contracts.py"
    )
    os.link(target, tmp_path / f"{target_kind}.alias")
    with pytest.raises(RuntimeSnapshotError, match="hardlink"):
        validate_harness_source_snapshot(
            manifest_path=Path(str(identity["path"])),
            expected_manifest_sha256=str(identity["sha256"]),
            expected_source_tooling_manifest_sha256="a" * 64,
        )


def test_materializacion_rechaza_parent_junction_sin_escribir_fuera(tmp_path: Path) -> None:
    if sys.platform != "win32":
        pytest.skip("junction es un reparse point de Windows")
    external = tmp_path / "external"
    external.mkdir()
    junction = tmp_path / "alias"
    created = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(external)],
        check=False,
        capture_output=True,
    )
    if created.returncode != 0:
        pytest.skip("el host no permitió crear junction")
    control = tmp_path / "control"
    control.mkdir()
    try:
        with pytest.raises(RuntimeSnapshotError, match=r"parents.*deben existir"):
            materialize_harness_source_snapshot(
                destination_root=junction / "snapshot",
                manifest_path=control / "snapshot.json",
                source_tooling_manifest_sha256="a" * 64,
                include_product_runtime=False,
            )
        assert not (external / "snapshot").exists()
    finally:
        junction.rmdir()


def test_reapertura_detecta_tooling_o_manifest_sustituido(tmp_path: Path) -> None:
    identity = _materialize(tmp_path)
    with pytest.raises(RuntimeSnapshotError, match="tooling esperado"):
        validate_harness_source_snapshot(
            manifest_path=Path(str(identity["path"])),
            expected_manifest_sha256=str(identity["sha256"]),
            expected_source_tooling_manifest_sha256="b" * 64,
        )
    with pytest.raises(RuntimeSnapshotError, match="SHA-256 externo"):
        validate_harness_source_snapshot(
            manifest_path=Path(str(identity["path"])),
            expected_manifest_sha256="c" * 64,
            expected_source_tooling_manifest_sha256="a" * 64,
        )


def test_catalogo_de_import_roots_productivos_es_cerrado() -> None:
    assert {
        "_cffi_backend",
        "cffi",
        "cryptography",
        "pyarrow",
        "threadpoolctl",
    } == EXPECTED_IMPORT_ROOTS
    assert PRODUCT_DISTRIBUTIONS == h9r_driver._PRODUCT_HARNESS_DISTRIBUTIONS


def test_root_copiado_exige_todo_payload_firmado_por_record(tmp_path: Path) -> None:
    container = tmp_path / "container"
    payload = container / "demo" / "a.py"
    payload.parent.mkdir(parents=True)
    payload.write_bytes(b"a")
    digest = hashlib.sha256(b"a").digest()
    record = {
        "demo/a.py": (digest, 1),
        "demo/b.py": (digest, 1),
    }
    with pytest.raises(RuntimeSnapshotError, match=r"missing=.*demo/b.py"):
        _assert_copied_root_matches_record(
            container=container,
            original_root_name="demo",
            record_entries=record,
        )


def test_record_descriptor_bound_rechaza_replace_tras_hash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = tmp_path / "site"
    dist = site / "demo-1.0.dist-info"
    dist.mkdir(parents=True)
    payload = site / "demo.py"
    payload.write_bytes(b"original")
    encoded = base64.urlsafe_b64encode(hashlib.sha256(b"original").digest()).rstrip(b"=").decode()
    record = dist / "RECORD"
    original_record = f"demo.py,sha256={encoded},8\ndemo-1.0.dist-info/RECORD,,\n".encode()
    record.write_bytes(original_record)
    replacement_record = tmp_path / "replacement.RECORD"
    replacement_record.write_bytes(b"demo.py,sha256=ZXZpbA,4\ndemo-1.0.dist-info/RECORD,,\n")
    replacement_payload = tmp_path / "replacement.py"
    replacement_payload.write_bytes(b"evil")
    original_reader = runtime_snapshot_module._read_bound_bytes
    swapped = False

    def swap_after_record_read(
        path: Path,
        *,
        context: str,
        require_single_link: bool = True,
    ) -> tuple[Path, bytes, os.stat_result]:
        nonlocal swapped
        result = original_reader(
            path,
            context=context,
            require_single_link=require_single_link,
        )
        if path == record and not swapped:
            swapped = True
            os.replace(replacement_record, record)
            os.replace(replacement_payload, payload)
        return result

    monkeypatch.setattr(runtime_snapshot_module, "_read_bound_bytes", swap_after_record_read)
    with pytest.raises(RuntimeSnapshotError, match=r"no reconcilia|cambió"):
        _record_entries(
            site_root=site,
            distribution="demo",
            version="1.0",
            expected_record_sha256=hashlib.sha256(original_record).hexdigest(),
        )


@pytest.mark.parametrize("inventory_kind", ["tree", "sources"])
def test_inventarios_snapshot_retienen_version_hasta_el_cierre(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    inventory_kind: str,
) -> None:
    if inventory_kind == "tree":
        root = tmp_path / "tree"
        root.mkdir()
        target = root / "mod.py"
        target.write_bytes(b"A")
    else:
        root = tmp_path / "source"
        package = root / "scripts" / "readiness_h9r"
        package.mkdir(parents=True)
        (root / "scripts" / "__init__.py").write_bytes(b"")
        (root / "scripts" / "measure_readiness_h9r.py").write_bytes(b"driver")
        target = package / "mod.py"
        target.write_bytes(b"A")
    original_reader = runtime_snapshot_module._read_bound_bytes
    swapped = False

    def swap_after_read(
        path: Path,
        *,
        context: str,
        require_single_link: bool = True,
    ) -> tuple[Path, bytes, os.stat_result]:
        nonlocal swapped
        result = original_reader(
            path,
            context=context,
            require_single_link=require_single_link,
        )
        if path == target and not swapped:
            swapped = True
            target.write_bytes(b"B-drift")
        return result

    monkeypatch.setattr(runtime_snapshot_module, "_read_bound_bytes", swap_after_read)
    with pytest.raises(RuntimeSnapshotError, match="cambió"):
        if inventory_kind == "tree":
            runtime_snapshot_module._tree_identity(root)
        else:
            runtime_snapshot_module._source_inventory(root)


def test_tree_identity_repite_censo_y_rechaza_payload_tardio(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "tree"
    root.mkdir()
    (root / "a.py").write_bytes(b"A")
    original_walk = runtime_snapshot_module._walk_files
    calls = 0

    def add_after_first_walk(
        candidate: Path,
        *,
        relative_to: Path,
        require_single_link: bool = True,
    ) -> list[Path]:
        nonlocal calls
        paths = original_walk(
            candidate,
            relative_to=relative_to,
            require_single_link=require_single_link,
        )
        calls += 1
        if calls == 1:
            (root / "z.py").write_bytes(b"late")
        return paths

    monkeypatch.setattr(runtime_snapshot_module, "_walk_files", add_after_first_walk)
    with pytest.raises(RuntimeSnapshotError, match="censo de archivos cambió"):
        runtime_snapshot_module._tree_identity(root)


def test_materializa_y_reabre_cinco_import_roots_reales(tmp_path: Path) -> None:
    if sys.platform != "win32" or sys.version_info[:2] != (3, 12):
        pytest.skip("el runtime firmado del arnés H9R está fijado a Windows/CPython 3.12")
    scratch = tmp_path / "scratch"
    control = tmp_path / "telemetry" / "control"
    scratch.mkdir()
    control.mkdir(parents=True)
    identity = materialize_harness_source_snapshot(
        destination_root=scratch / "harness-runtime-snapshot",
        manifest_path=control / "harness-runtime-snapshot.json",
        source_tooling_manifest_sha256="d" * 64,
    )
    value = identity["value"]
    assert isinstance(value, dict)
    roots = value["import_roots"]
    assert isinstance(roots, list)
    assert {root["name"] for root in roots} == EXPECTED_IMPORT_ROOTS
    assert all(root["files"] > 0 and root["logical_bytes"] > 0 for root in roots)
    assert identity == validate_harness_source_snapshot(
        manifest_path=Path(str(identity["path"])),
        expected_manifest_sha256=str(identity["sha256"]),
        expected_source_tooling_manifest_sha256="d" * 64,
    )
