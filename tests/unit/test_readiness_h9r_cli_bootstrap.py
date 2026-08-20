from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
import sys
import textwrap
from collections.abc import Iterator
from pathlib import Path

import pytest

import scripts.measure_readiness_h9r as h9r_driver
from scripts.measure_readiness_h9r import (
    ROOT,
    _assert_copied_import_root_matches_record,
    _assert_record_tree_closed,
    _assert_snapshot_import_resolution,
    _canonical_json_stdlib,
    _internal_workdir_from_request,
    _prepare_harness_source_snapshot,
    _read_json_object_safe,
    _record_file_identities,
    _tree_identity_stdlib,
    _verify_harness_source_snapshot,
)
from scripts.readiness_h9r.contracts import CAPS as CONTRACT_CAPS
from scripts.readiness_h9r.copy_gate import ContractError

DRIVER = ROOT / "scripts" / "measure_readiness_h9r.py"


@pytest.fixture(autouse=True)
def _close_snapshot_leases_around_test(tmp_path: Path) -> Iterator[None]:
    del tmp_path
    h9r_driver._release_snapshot_leases_for_tests()
    yield
    h9r_driver._release_snapshot_leases_for_tests()


def _prepare_unleased(
    tmp_path: Path,
    *,
    include_product_runtime: bool = False,
) -> dict[str, object]:
    snapshot = _prepare_harness_source_snapshot(
        tmp_path,
        include_product_runtime=include_product_runtime,
    )
    h9r_driver._release_snapshot_leases_for_tests()
    return snapshot


def _isolated_command(cache: Path, *arguments: str) -> list[str]:
    cache.mkdir()
    return [
        sys.executable,
        "-I",
        "-B",
        "-S",
        "-X",
        f"pycache_prefix={cache}",
        str(DRIVER),
        *arguments,
    ]


def _run_isolated(
    cache: Path,
    *arguments: str,
    check: bool = False,
    timeout: float = 60.0,
) -> tuple[int, str, str]:
    """Ejecuta el driver aislado y decodifica sus flujos como UTF-8 exacto.

    El comando contractual usa ``-I``, así que el hijo ignora ``PYTHONUTF8`` y
    ``PYTHONIOENCODING``. Decodificar con la codificación del proceso que lanza pytest ataría el
    resultado al entorno del runner —el arranque del runbook exporta UTF-8, CI no— y volvería el
    gate irreproducible. El driver fija UTF-8 en sus flujos; esta prueba lo exige byte a byte.
    """
    completed = subprocess.run(
        _isolated_command(cache, *arguments),
        cwd=ROOT,
        check=check,
        capture_output=True,
        timeout=timeout,
    )
    return (
        completed.returncode,
        completed.stdout.decode("utf-8"),
        completed.stderr.decode("utf-8"),
    )


def test_cli_catalog_y_schemas_salen_de_snapshot_aislado(tmp_path: Path) -> None:
    catalog_cache = tmp_path / "catalog-cache"
    _, catalog_stdout, catalog_stderr = _run_isolated(catalog_cache, "catalog", check=True)
    payload = json.loads(catalog_stdout)
    assert catalog_stderr == ""
    assert payload["materialized_start_units"] == 0
    assert payload["calibration_start_enabled"] is False
    assert not list(catalog_cache.rglob("__pycache__"))

    schema_cache = tmp_path / "schema-cache"
    schema_output = tmp_path / "schemas"
    _, _, schemas_stderr = _run_isolated(
        schema_cache,
        "schemas",
        "--directory",
        str(schema_output),
        check=True,
    )
    assert schemas_stderr == ""
    assert {path.name for path in schema_output.iterdir()} == {
        "aggregate.schema.json",
        "attempt.schema.json",
        "internal-authorization-gate.schema.json",
        "internal-authorization-precommit.schema.json",
        "internal-authorization-release.schema.json",
        "post-start-failure.schema.json",
        "pre-start-failure.schema.json",
        "preflight-rejection.schema.json",
    }
    assert not list(schema_cache.rglob("__pycache__"))


@pytest.mark.parametrize("command", ["catalog", "schemas"])
def test_cli_no_publica_si_release_falla_y_retry_conserva_estado(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    command: str,
) -> None:
    if sys.platform != "win32":
        pytest.skip("el lease DACL sólo existe en Windows")
    _prepare_harness_source_snapshot(tmp_path)
    key, lease = next(iter(h9r_driver._WINDOWS_SNAPSHOT_LEASES.items()))
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
            raise SystemExit("fallo inyectado de restauración")
        original_restore()

    monkeypatch.setattr(failed_seal, "restore", fail_once)
    schema_output = tmp_path / "schemas-output"
    argv = ["catalog"] if command == "catalog" else ["schemas", "--directory", str(schema_output)]
    with pytest.raises(
        h9r_driver._SnapshotLeaseReleaseError,
        match="falló liberación explícita del lease bootstrap H9R",
    ):
        h9r_driver.main(argv)

    assert capsys.readouterr().out == ""
    assert not schema_output.exists()
    assert h9r_driver._WINDOWS_SNAPSHOT_LEASES[key] is lease
    assert lease.state == "restoring"
    assert tuple(lease.handles) == handles
    assert tuple(lease.acl_seals) == seals
    assert failed_seal.security_descriptor == descriptor != 0
    probe = failed_seal.path / "retry-probe"
    with pytest.raises(PermissionError):
        probe.mkdir()

    h9r_driver._release_snapshot_leases_for_tests()
    assert h9r_driver._WINDOWS_SNAPSHOT_LEASES == {}
    assert lease.state == "closed"
    assert lease.handles == []
    assert lease.acl_seals == []
    probe.mkdir()
    probe.rmdir()


def test_cli_closehandle_fallido_no_publica_ni_reutiliza_lease(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    if sys.platform != "win32":
        pytest.skip("los handles de snapshot sólo existen en Windows")
    snapshot = _prepare_harness_source_snapshot(tmp_path)
    lease = next(iter(h9r_driver._WINDOWS_SNAPSHOT_LEASES.values()))
    handles = tuple(lease.handles)
    seals = tuple(lease.acl_seals)
    original_close = h9r_driver._close_windows_handle_stdlib
    close_calls = 0

    def fail_close_once(handle: int) -> None:
        nonlocal close_calls
        close_calls += 1
        if close_calls == 1:
            raise SystemExit("fallo CloseHandle inyectado")
        original_close(handle)

    monkeypatch.setattr(h9r_driver, "_close_windows_handle_stdlib", fail_close_once)
    with pytest.raises(h9r_driver._SnapshotLeaseReleaseError):
        h9r_driver.main(["catalog"])

    assert capsys.readouterr().out == ""
    assert lease.state == "restored"
    assert tuple(lease.handles) == handles
    assert tuple(lease.acl_seals) == seals
    assert all(seal.security_descriptor != 0 for seal in lease.acl_seals)
    with pytest.raises(SystemExit, match="cleanup pendiente"):
        _verify_harness_source_snapshot(snapshot)

    h9r_driver._release_snapshot_leases_for_tests()
    assert lease.state == "closed"
    assert h9r_driver._WINDOWS_SNAPSHOT_LEASES == {}


def test_subprocess_release_fallido_es_nonzero_y_atexit_reintenta(tmp_path: Path) -> None:
    if sys.platform != "win32":
        pytest.skip("el lease DACL sólo existe en Windows")
    prefix = tmp_path / "subprocess-snapshot"
    marker = tmp_path / "atexit-retry.txt"
    prefix.mkdir()
    script = textwrap.dedent(
        """
        import sys
        from pathlib import Path

        import scripts.measure_readiness_h9r as driver

        prefix = Path(sys.argv[1])
        marker = Path(sys.argv[2])
        driver._prepare_harness_source_snapshot(prefix)
        lease = next(iter(driver._WINDOWS_SNAPSHOT_LEASES.values()))
        seal = lease.acl_seals[-1]
        original_restore = seal.restore
        calls = 0

        def fail_once():
            global calls
            calls += 1
            if calls == 1:
                raise SystemExit("fallo restore subprocess inyectado")
            original_restore()
            marker.write_text("atexit-restored", encoding="utf-8")

        seal.restore = fail_once
        raise SystemExit(driver.main(["catalog"]))
        """
    )
    result = subprocess.run(
        [sys.executable, "-B", "-c", script, str(prefix), str(marker)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode != 0
    assert result.stdout == ""
    assert "falló liberación explícita del lease bootstrap H9R" in result.stderr
    assert marker.read_text(encoding="utf-8") == "atexit-restored"


def test_catalog_runtime_falla_cerrado_si_caps_no_reconcilia(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bad_caps = dict(CONTRACT_CAPS)
    first_key = next(iter(bad_caps))
    bad_caps[first_key] += 1
    monkeypatch.setattr(h9r_driver, "CAPS", bad_caps)
    with pytest.raises(ContractError, match=r"catálogo H9R no reconcilia en caps"):
        h9r_driver.catalog_payload()


def test_cli_rechaza_aislamiento_incompleto(tmp_path: Path) -> None:
    for missing_flag in ("-I", "-B", "-S"):
        cache = tmp_path / f"missing-{missing_flag[1:]}"
        command = _isolated_command(cache, "catalog")
        command.remove(missing_flag)
        completed = subprocess.run(
            command,
            cwd=ROOT,
            check=False,
            capture_output=True,
            timeout=60,
        )
        assert completed.returncode != 0
        assert "exige -I -B -S" in completed.stderr.decode("utf-8")


def test_cli_rechaza_cache_preexistente(tmp_path: Path) -> None:
    cache = tmp_path / "dirty-cache"
    command = _isolated_command(cache, "catalog")
    (cache / "stale.pyc").write_bytes(b"not-bytecode")
    completed = subprocess.run(
        command,
        cwd=ROOT,
        check=False,
        capture_output=True,
        timeout=60,
    )
    assert completed.returncode != 0
    assert "directorio fresco vacío" in completed.stderr.decode("utf-8")


def test_cli_schemas_rechaza_parent_junction_sin_escribir_fuera(tmp_path: Path) -> None:
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
    try:
        with pytest.raises(SystemExit, match="no es plano"):
            h9r_driver.main(["schemas", "--directory", str(junction / "schemas")])
        assert not (external / "schemas").exists()
    finally:
        junction.rmdir()


def test_cli_harness_test_publica_runtime_y_cero_start(tmp_path: Path) -> None:
    if sys.platform != "win32" or sys.version_info[:2] != (3, 12):
        pytest.skip("harness-test exige el runtime firmado Windows/CPython 3.12")
    cache = tmp_path / "harness-cache"
    output = tmp_path / "harness-test.json"
    # El fusible sólo evita que un cuelgue bloquee la suite: no es un budget del arnés. La matriz
    # sintética midió entre 119 s y 129 s en esta torre, de modo que 120 s dejaba la prueba
    # dependiente de la carga del host.
    _, _, harness_test_stderr = _run_isolated(
        cache,
        "harness-test",
        "--output",
        str(output),
        check=True,
        timeout=600.0,
    )
    assert harness_test_stderr == ""
    artifact = json.loads(output.read_text(encoding="utf-8"))
    assert artifact["start_tokens_emitted"] == 0
    assert artifact["materialized_start_units"] == 0
    assert artifact["candidate_workloads_executed"] == 0
    assert (
        artifact["harness_runtime"]["source_snapshot"]["count"]
        == artifact["harness_modules"]["count"]
    )
    assert (
        artifact["harness_runtime"]["source_snapshot"]["files"]
        == artifact["harness_modules"]["files"]
    )
    assert {
        item["name"] for item in artifact["harness_runtime"]["source_snapshot"]["import_roots"]
    } == {
        "_cffi_backend",
        "cffi",
        "cryptography",
        "pyarrow",
        "pypdf",
        "threadpoolctl",
    }
    assert not list(cache.rglob("__pycache__"))


def test_cli_harness_test_retira_staging_si_release_falla(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if sys.platform != "win32":
        pytest.skip("el lease DACL sólo existe en Windows")
    source_snapshot = _prepare_harness_source_snapshot(tmp_path)
    key, lease = next(iter(h9r_driver._WINDOWS_SNAPSHOT_LEASES.items()))
    failed_seal = lease.acl_seals[-1]
    original_restore = failed_seal.restore
    restore_calls = 0
    harness_runtime = {
        "bootstrap_mode": "test-double-no-start",
        "source_snapshot": source_snapshot,
    }

    def fake_run_harness_self_test(
        *,
        checkout_root: Path,
        output_path: Path,
        harness_runtime: dict[str, object],
    ) -> dict[str, object]:
        del checkout_root
        artifact: dict[str, object] = {"harness_runtime": harness_runtime}
        output_path.write_bytes(
            json.dumps(
                artifact,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            + b"\n"
        )
        return artifact

    def fail_once() -> None:
        nonlocal restore_calls
        restore_calls += 1
        if restore_calls == 1:
            raise SystemExit("fallo inyectado de restauración")
        original_restore()

    monkeypatch.setattr(h9r_driver, "_SAFE_HARNESS_RUNTIME", harness_runtime)
    monkeypatch.setattr(
        h9r_driver,
        "_verify_safe_harness_dependencies",
        lambda *, activate: {"bootstrap_mode": "test-double-no-start"},
    )
    monkeypatch.setattr(
        h9r_driver,
        "_verify_harness_source_snapshot",
        lambda raw: dict(raw),
    )
    monkeypatch.setattr(h9r_driver, "run_harness_self_test", fake_run_harness_self_test)
    monkeypatch.setattr(failed_seal, "restore", fail_once)
    output = tmp_path / "harness-test.json"

    with pytest.raises(h9r_driver._SnapshotLeaseReleaseError):
        h9r_driver.main(["harness-test", "--output", str(output)])

    assert not output.exists()
    assert not list(tmp_path.glob(".harness-test.json.h9r-pending-*"))
    assert h9r_driver._WINDOWS_SNAPSHOT_LEASES[key] is lease
    assert failed_seal.security_descriptor != 0
    h9r_driver._release_snapshot_leases_for_tests()
    assert h9r_driver._WINDOWS_SNAPSHOT_LEASES == {}


def test_snapshot_de_fuentes_detecta_mutacion(tmp_path: Path) -> None:
    snapshot = _prepare_unleased(tmp_path)
    assert (Path(str(snapshot["root"])) / "import-roots").is_dir()
    copied_driver = Path(str(snapshot["root"])) / "scripts" / DRIVER.name
    copied_driver.write_bytes(copied_driver.read_bytes() + b"\n# drift\n")
    with pytest.raises(SystemExit, match="snapshot o fuentes H9R cambiaron"):
        _verify_harness_source_snapshot(snapshot)


def test_snapshot_de_fuentes_rechaza_import_root_extra_no_firmado(
    tmp_path: Path,
) -> None:
    snapshot = _prepare_unleased(tmp_path)
    (Path(str(snapshot["root"])) / "import-roots" / "extra").mkdir()
    with pytest.raises(SystemExit, match="roots extra/faltantes"):
        _verify_harness_source_snapshot(snapshot)


def test_snapshot_rechaza_pycache_extra_en_contenedor_scripts(tmp_path: Path) -> None:
    snapshot = _prepare_unleased(tmp_path)
    cache = Path(str(snapshot["root"])) / "scripts" / "__pycache__"
    cache.mkdir()
    (cache / "evil.pyc").write_bytes(b"not-signed")
    with pytest.raises(SystemExit, match=r"scripts.*extra/faltantes"):
        _verify_harness_source_snapshot(snapshot)


def test_snapshot_rechaza_pycache_dentro_de_import_root(tmp_path: Path) -> None:
    snapshot = _prepare_unleased(tmp_path)
    snapshot_root = Path(str(snapshot["root"]))
    container = snapshot_root / "import-roots" / "foo"
    container.mkdir()
    (container / "foo.py").write_bytes(b"signed")
    payload = {
        name: value
        for name, value in snapshot.items()
        if name not in {"manifest_path", "manifest_sha256", "import_roots"}
    }
    payload["import_roots"] = [
        {
            "name": "foo",
            "kind": "import_parent",
            "path": str(container),
            **_tree_identity_stdlib(container),
        }
    ]
    payload["manifest_sha256"] = hashlib.sha256(_canonical_json_stdlib(payload)).hexdigest()
    manifest_path = Path(str(snapshot["manifest_path"]))
    manifest_bytes = _canonical_json_stdlib(payload) + b"\n"
    manifest_path.write_bytes(manifest_bytes)
    rebound = {**payload, "manifest_path": str(manifest_path)}
    cache = container / "__pycache__"
    cache.mkdir()
    (cache / "evil.pyc").write_bytes(b"not-signed")
    with pytest.raises(SystemExit, match="__pycache__ no firmado"):
        _verify_harness_source_snapshot(rebound)


def test_driver_retiene_lease_windows_hasta_fin_del_proceso(tmp_path: Path) -> None:
    snapshot = _prepare_unleased(tmp_path)
    snapshot_root = Path(str(snapshot["root"]))
    source = snapshot_root / "scripts" / "readiness_h9r" / "contracts.py"
    late_source = source.parent / "late.py"
    late_import_root = snapshot_root / "import-roots" / "late"
    before = source.read_bytes()
    assert _verify_harness_source_snapshot(snapshot) == snapshot
    if sys.platform != "win32":
        assert h9r_driver._WINDOWS_SNAPSHOT_LEASES == {}
        return
    assert h9r_driver._WINDOWS_SNAPSHOT_LEASES
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
    h9r_driver._release_snapshot_leases_for_tests()
    h9r_driver._release_snapshot_leases_for_tests()
    source.write_bytes(before)
    late_source.write_bytes(b"entra tras liberar")
    late_import_root.mkdir()


def test_driver_cierre_global_detecta_mutacion_cruzada_de_fuente(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = _prepare_unleased(tmp_path)
    source = Path(str(snapshot["root"])) / "scripts" / "readiness_h9r" / "contracts.py"
    before = source.read_bytes()
    original = h9r_driver._snapshot_lease_census_stdlib
    calls = 0
    mutation_blocked = False

    def mutate_during_leased_census(
        *,
        manifest_path: Path,
        snapshot_root: Path,
        live_root: Path,
        import_root_names: set[str],
    ) -> tuple[tuple[Path, ...], tuple[Path, ...]]:
        nonlocal calls, mutation_blocked
        result = original(
            manifest_path=manifest_path,
            snapshot_root=snapshot_root,
            live_root=live_root,
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
        h9r_driver,
        "_snapshot_lease_census_stdlib",
        mutate_during_leased_census,
    )
    if sys.platform == "win32":
        assert _verify_harness_source_snapshot(snapshot) == snapshot
        assert mutation_blocked is True
        assert source.read_bytes() == before
    else:
        with pytest.raises(SystemExit, match=r"cambiaron|cambió"):
            _verify_harness_source_snapshot(snapshot)
        assert mutation_blocked is False


@pytest.mark.parametrize("target_kind", ["manifest", "source"])
def test_snapshot_de_fuentes_rechaza_hardlink_contractual(
    tmp_path: Path,
    target_kind: str,
) -> None:
    snapshot = _prepare_unleased(tmp_path)
    target = (
        Path(str(snapshot["manifest_path"]))
        if target_kind == "manifest"
        else Path(str(snapshot["root"])) / "scripts" / "readiness_h9r" / "contracts.py"
    )
    os.link(target, tmp_path / f"{target_kind}.alias")
    with pytest.raises(SystemExit, match="hardlink no permitido"):
        _verify_harness_source_snapshot(snapshot)


def test_snapshot_de_fuentes_rechaza_prefix_junction_sin_escribir_fuera(
    tmp_path: Path,
) -> None:
    if sys.platform != "win32":
        pytest.skip("junction es un reparse point de Windows")
    external = tmp_path / "external"
    external.mkdir()
    junction = tmp_path / "prefix"
    created = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(external)],
        check=False,
        capture_output=True,
    )
    if created.returncode != 0:
        pytest.skip("el host no permitió crear junction")
    try:
        with pytest.raises(SystemExit, match="no es plano"):
            _prepare_harness_source_snapshot(junction)
        assert not (external / "source-snapshot").exists()
    finally:
        junction.rmdir()


def test_snapshot_rechaza_pycache_no_firmado(tmp_path: Path) -> None:
    snapshot = _prepare_unleased(tmp_path)
    package_cache = Path(str(snapshot["root"])) / "scripts" / "readiness_h9r" / "__pycache__"
    package_cache.mkdir()
    (package_cache / "contracts.cpython-312.pyc").write_bytes(b"not-bytecode")
    with pytest.raises(SystemExit, match="__pycache__ no firmado"):
        _verify_harness_source_snapshot(snapshot)


def test_snapshot_liga_manifest_tooling_externo_sin_autoderivarlo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshot = _prepare_unleased(tmp_path)
    manifest_path = Path(str(snapshot["manifest_path"]))
    payload = {name: value for name, value in snapshot.items() if name != "manifest_path"}
    payload["source_tooling_manifest_sha256"] = "a" * 64
    core = {name: value for name, value in payload.items() if name != "manifest_sha256"}
    payload["manifest_sha256"] = hashlib.sha256(_canonical_json_stdlib(core)).hexdigest()
    manifest_path.write_bytes(_canonical_json_stdlib(payload) + b"\n")
    rebound = {**payload, "manifest_path": str(manifest_path)}
    monkeypatch.setattr(h9r_driver, "ROOT", Path(str(snapshot["root"])))
    assert _verify_harness_source_snapshot(rebound) == rebound


def test_loader_snapshot_externo_reconcilia_cinco_import_roots(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshot = _prepare_unleased(tmp_path)
    snapshot_root = Path(str(snapshot["root"]))
    import_roots: list[dict[str, object]] = []
    for name in ("_cffi_backend", "cffi", "cryptography", "pyarrow", "threadpoolctl"):
        container = snapshot_root / "import-roots" / name
        container.mkdir()
        (container / f"{name}.signed").write_bytes(name.encode("ascii"))
        import_roots.append(
            {
                "name": name,
                "kind": "import_parent",
                "path": str(container),
                **_tree_identity_stdlib(container),
            }
        )
    payload = {
        name: value
        for name, value in snapshot.items()
        if name not in {"manifest_path", "manifest_sha256", "import_roots"}
    }
    payload["import_roots"] = import_roots
    payload["source_tooling_manifest_sha256"] = "b" * 64
    payload["manifest_sha256"] = hashlib.sha256(_canonical_json_stdlib(payload)).hexdigest()
    manifest_path = Path(str(snapshot["manifest_path"]))
    manifest_bytes = _canonical_json_stdlib(payload) + b"\n"
    manifest_path.write_bytes(manifest_bytes)
    monkeypatch.setattr(h9r_driver, "ROOT", snapshot_root)
    monkeypatch.setenv("NIKODYM_H9R_HARNESS_SNAPSHOT_MANIFEST", str(manifest_path))
    monkeypatch.setenv(
        "NIKODYM_H9R_HARNESS_SNAPSHOT_MANIFEST_SHA256",
        hashlib.sha256(manifest_bytes).hexdigest(),
    )
    observed = h9r_driver._load_external_harness_snapshot("_candidate")
    assert observed is not None
    assert observed["manifest_sha256"] == payload["manifest_sha256"]
    assert {item["name"] for item in observed["import_roots"]} == {
        "_cffi_backend",
        "cffi",
        "cryptography",
        "pyarrow",
        "threadpoolctl",
    }


def test_loader_interno_rechaza_ausencia_de_snapshot_externo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("NIKODYM_H9R_HARNESS_SNAPSHOT_MANIFEST", raising=False)
    monkeypatch.delenv("NIKODYM_H9R_HARNESS_SNAPSHOT_MANIFEST_SHA256", raising=False)
    with pytest.raises(SystemExit, match="snapshot externo pre-START"):
        h9r_driver._load_external_harness_snapshot("_candidate")


def test_executor_interno_deriva_workdir_solo_desde_telemetry_control(tmp_path: Path) -> None:
    workdir = tmp_path / "attempt"
    control = workdir / "telemetry" / "control"
    control.mkdir(parents=True)
    request = control / "candidate-request.json"
    request.write_bytes(b"{}\n")
    assert _internal_workdir_from_request(request) == workdir.absolute()

    misplaced = workdir / "candidate-request.json"
    misplaced.write_bytes(b"{}\n")
    with pytest.raises(SystemExit, match="telemetry/control"):
        _internal_workdir_from_request(misplaced)


def test_entrada_cli_rechaza_ancestro_symlink_o_junction(tmp_path: Path) -> None:
    external = tmp_path / "external"
    external.mkdir()
    (external / "input.json").write_bytes(b"{}\n")
    linked = tmp_path / "linked"
    try:
        os.symlink(external, linked, target_is_directory=True)
    except OSError:
        if sys.platform != "win32":
            pytest.skip("el host no permitió crear symlink de control")
        created = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(linked), str(external)],
            check=False,
            capture_output=True,
            text=True,
        )
        if created.returncode != 0:
            pytest.skip(f"el host no permitió crear junction de control: {created.stderr}")
    try:
        with pytest.raises(SystemExit, match="symlink/reparse point"):
            _read_json_object_safe(linked / "input.json", context="entrada de control")
    finally:
        if linked.is_symlink():
            linked.unlink()
        elif os.path.lexists(linked):
            os.rmdir(linked)


def test_entrada_cli_rechaza_hardlink_antes_de_leer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.json"
    source.write_bytes(b"{}\n")
    linked = tmp_path / "linked.json"
    os.link(source, linked)
    reads: list[Path] = []

    def forbidden_read(path: Path, *args: object, **kwargs: object) -> str:
        del args, kwargs
        reads.append(path)
        raise AssertionError("el hardlink no debe abrirse")

    monkeypatch.setattr(Path, "read_text", forbidden_read)
    with pytest.raises(SystemExit, match="hardlink no permitido"):
        _read_json_object_safe(linked, context="entrada de control")
    assert reads == []


def test_bootstrap_productivo_materializa_import_roots_reales(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if sys.platform != "win32" or sys.version_info[:2] != (3, 12):
        pytest.skip("el bootstrap firmado H9R está fijado a Windows/CPython 3.12")
    snapshot = _prepare_harness_source_snapshot(tmp_path, include_product_runtime=True)
    assert _verify_harness_source_snapshot(snapshot) == snapshot
    assert {item["name"] for item in snapshot["import_roots"]} == {
        "_cffi_backend",
        "cffi",
        "cryptography",
        "pyarrow",
        "threadpoolctl",
    }
    assert all(item["files"] > 0 for item in snapshot["import_roots"])
    for item in reversed(snapshot["import_roots"]):
        monkeypatch.syspath_prepend(str(item["path"]))
    _assert_snapshot_import_resolution(snapshot)
    import pyarrow as pa
    import pyarrow.parquet as pq

    parquet_path = tmp_path / "ephemeral-probe.parquet"
    pq.write_table(pa.table({"value": [1, 2]}), parquet_path)  # type: ignore[no-untyped-call]
    import_script = (
        "import json,sys;"
        f"roots={json.dumps([str(item['path']) for item in snapshot['import_roots']])};"
        "sys.path.extend(roots);"
        "import _cffi_backend,cffi,cryptography,pyarrow,pyarrow.parquet,threadpoolctl;"
        f"table=pyarrow.parquet.read_table({str(parquet_path)!r});"
        "assert table.to_pylist()==[{'value':1},{'value':2}];"
        "print('isolated-imports-ok')"
    )
    imported = subprocess.run(
        [sys.executable, "-I", "-B", "-S", "-c", import_script],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert imported.returncode == 0, imported.stderr
    assert imported.stdout.strip() == "isolated-imports-ok"


def _fake_record_tree(site_root: Path) -> set[str]:
    package = site_root / "demo"
    dist_info = site_root / "demo-1.dist-info"
    package.mkdir(parents=True)
    dist_info.mkdir()
    (package / "__init__.py").write_bytes(b"")
    (dist_info / "RECORD").write_bytes(b"")
    return {"demo/__init__.py", "demo-1.dist-info/RECORD"}


def test_censo_record_bidireccional_rechaza_extra(tmp_path: Path) -> None:
    record_entries = _fake_record_tree(tmp_path)
    _assert_record_tree_closed(
        site_root=tmp_path,
        record_entries=record_entries,
        distribution_name="demo",
    )
    (tmp_path / "demo" / "injected.py").write_bytes(b"raise SystemExit(1)\n")
    with pytest.raises(SystemExit, match="no reconcilia RECORD"):
        _assert_record_tree_closed(
            site_root=tmp_path,
            record_entries=record_entries,
            distribution_name="demo",
        )


def test_copia_de_import_root_rechaza_payload_record_omitido(tmp_path: Path) -> None:
    container = tmp_path / "container"
    payload = container / "demo" / "a.py"
    payload.parent.mkdir(parents=True)
    payload.write_bytes(b"a")
    record = {
        "demo/a.py": ("sha256=YQ", 1),
        "demo/b.py": ("sha256=YQ", 1),
    }
    with pytest.raises(SystemExit, match=r"missing=.*demo/b.py"):
        _assert_copied_import_root_matches_record(
            container=container,
            root_name="demo",
            record_entries=record,
        )


def test_driver_record_descriptor_bound_rechaza_replace_tras_hash(
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
    original_reader = h9r_driver._read_bound_bytes_stdlib
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

    monkeypatch.setattr(h9r_driver, "_read_bound_bytes_stdlib", swap_after_record_read)
    with pytest.raises(SystemExit, match=r"no reconcilia|cambió"):
        _record_file_identities(
            site_root=site,
            distribution="demo",
            version="1.0",
            expected_record_sha256=hashlib.sha256(original_record).hexdigest(),
        )


@pytest.mark.parametrize("inventory_kind", ["tree", "sources"])
def test_driver_inventarios_retienen_version_hasta_el_cierre(
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
    original_reader = h9r_driver._read_bound_bytes_stdlib
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

    monkeypatch.setattr(h9r_driver, "_read_bound_bytes_stdlib", swap_after_read)
    with pytest.raises(SystemExit, match="cambió"):
        if inventory_kind == "tree":
            h9r_driver._tree_identity_stdlib(root)
        else:
            h9r_driver._source_inventory_stdlib(root, allow_pycache=False)


def test_driver_tree_identity_repite_censo_y_rechaza_payload_tardio(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "tree"
    root.mkdir()
    (root / "a.py").write_bytes(b"A")
    original_paths = h9r_driver._tree_paths_stdlib
    calls = 0

    def add_after_first_walk(candidate: Path) -> list[Path]:
        nonlocal calls
        paths = original_paths(candidate)
        calls += 1
        if calls == 1:
            (root / "z.py").write_bytes(b"late")
        return paths

    monkeypatch.setattr(h9r_driver, "_tree_paths_stdlib", add_after_first_walk)
    with pytest.raises(SystemExit, match="censo de archivos cambió"):
        h9r_driver._tree_identity_stdlib(root)


def test_censo_record_rechaza_junction(tmp_path: Path) -> None:
    if sys.platform != "win32":
        pytest.skip("junction es un reparse point de Windows")
    record_entries = _fake_record_tree(tmp_path / "site")
    external = tmp_path / "external"
    external.mkdir()
    junction = tmp_path / "site" / "demo" / "escape"
    created = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(external)],
        check=False,
        capture_output=True,
        text=True,
    )
    if created.returncode != 0:
        pytest.skip(f"el entorno no permitió crear junction: {created.stderr}")
    try:
        with pytest.raises(SystemExit, match="reparse point"):
            _assert_record_tree_closed(
                site_root=tmp_path / "site",
                record_entries=record_entries,
                distribution_name="demo",
            )
    finally:
        os.rmdir(junction)
