from __future__ import annotations

import _winapi
import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.readiness_h9r.adapters import (
    _candidate_output_isolation_plan,
    _validate_output_isolation,
)
from scripts.readiness_h9r.contracts import (
    CANDIDATE_OUTPUT_ISOLATION_SCHEMA_VERSION,
    ContractError,
)
from scripts.readiness_h9r.windows_job import resume_suspended_process
from scripts.readiness_h9r.windows_sandbox import (
    DENIED_OPERATIONS,
    LOW_INTEGRITY_SID,
    MEDIUM_INTEGRITY_SID,
    SANDBOX_MECHANISM,
    SandboxError,
    apply_low_integrity_label,
    census_output_isolation,
    clear_mandatory_label,
    launch_suspended_low_integrity,
    low_integrity_primary_token,
    mandatory_label,
    probe_output_root_denial,
    process_integrity_level,
    terminated_on_exit,
    token_integrity_level,
)

pytestmark = pytest.mark.skipif(
    sys.platform != "win32",
    reason="el aislamiento OS del candidato sólo califica en Windows",
)


def _censo(
    *,
    output_root: Path,
    writable_roots: list[Path],
    protected_roots: list[Path],
) -> dict[str, object]:
    """Censo con el probe de denegación real, que es la forma contractual de invocarlo."""
    return census_output_isolation(
        output_root=output_root,
        writable_roots=writable_roots,
        protected_roots=protected_roots,
        denial_probe=probe_output_root_denial(output_root, python_executable=Path(sys.executable)),
    )


def _workdir(tmp_path: Path) -> dict[str, Path]:
    """Reproduce el layout exacto del workdir del arnés, con `outputs` todavía inexistente."""
    workdir = tmp_path / "workdir"
    scratch = workdir / "scratch"
    staging = scratch / "consumer-staging"
    candidate_runtime = scratch / "candidate-runtime"
    python_cache = scratch / "python-cache"
    pycache = python_cache / "candidate-child"
    telemetry = workdir / "telemetry"
    control = telemetry / "control"
    candidate_root = tmp_path / "candidate-tree"
    for path in (
        workdir,
        scratch,
        staging,
        candidate_runtime,
        python_cache,
        pycache,
        telemetry,
        control,
        candidate_root,
    ):
        path.mkdir(parents=True)
    return {
        "workdir": workdir,
        "scratch": scratch,
        "staging": staging,
        "candidate_runtime": candidate_runtime,
        "python_cache": python_cache,
        "pycache": pycache,
        "telemetry": telemetry,
        "control": control,
        "candidate_root": candidate_root,
        "outputs": workdir / "outputs",
    }


def _label_writable_roots(paths: dict[str, Path]) -> None:
    """Etiqueta las tres raíces escribibles del layout cerrado, como hace el controller."""
    for name in ("staging", "candidate_runtime", "pycache"):
        apply_low_integrity_label(paths[name])


def _run_child(
    paths: dict[str, Path],
    body: str,
    *,
    sandboxed: bool = True,
    extra_argv: tuple[str, ...] = (),
) -> tuple[int, bytes, bytes, int | None]:
    """Ejecuta un hijo con el token de integridad Low y devuelve salida cruda e integridad."""
    script = paths["staging"] / "child.py"
    script.write_text(body, encoding="utf-8")
    stdout_path = paths["telemetry"] / "child.stdout.bin"
    stderr_path = paths["telemetry"] / "child.stderr.bin"
    for path in (stdout_path, stderr_path):
        path.unlink(missing_ok=True)
    command = [sys.executable, "-I", "-B", "-S", str(script), *extra_argv]
    environment = {
        "SYSTEMROOT": os.environ["SYSTEMROOT"],
        "PYTHONHASHSEED": "0",
    }
    with stdout_path.open("xb") as out, stderr_path.open("xb") as err:
        if not sandboxed:
            completed = subprocess.run(
                command,
                cwd=paths["staging"],
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=out,
                stderr=err,
                check=False,
                timeout=120,
            )
            observed = None
            code = completed.returncode
        else:
            with low_integrity_primary_token() as token:
                process = launch_suspended_low_integrity(
                    command,
                    token=token,
                    cwd=paths["staging"],
                    environment=environment,
                    stdout_fd=out.fileno(),
                    stderr_fd=err.fileno(),
                )
                with terminated_on_exit(process):
                    observed = int(process_integrity_level(process.pid) == LOW_INTEGRITY_SID)
                    resume_suspended_process(process.pid)
                    code = process.wait(timeout=120)
    return code, stdout_path.read_bytes(), stderr_path.read_bytes(), observed


def test_etiqueta_low_es_efectiva_y_la_ausencia_significa_media(tmp_path: Path) -> None:
    paths = _workdir(tmp_path)
    assert mandatory_label(paths["staging"]) is None
    apply_low_integrity_label(paths["staging"])
    assert mandatory_label(paths["staging"]) == LOW_INTEGRITY_SID
    assert mandatory_label(paths["workdir"]) is None
    assert mandatory_label(paths["telemetry"]) is None
    assert MEDIUM_INTEGRITY_SID != LOW_INTEGRITY_SID


def test_etiqueta_low_se_hereda_a_subdirectorios_creados_despues(tmp_path: Path) -> None:
    paths = _workdir(tmp_path)
    apply_low_integrity_label(paths["staging"])
    nested = paths["staging"] / "particiones" / "woe"
    nested.mkdir(parents=True)
    assert mandatory_label(nested) == LOW_INTEGRITY_SID


def test_censo_reconcilia_ambos_sentidos(tmp_path: Path) -> None:
    paths = _workdir(tmp_path)
    apply_low_integrity_label(paths["staging"])
    apply_low_integrity_label(paths["candidate_runtime"])
    censo = _censo(
        output_root=paths["outputs"],
        writable_roots=[paths["staging"], paths["candidate_runtime"]],
        protected_roots=[paths["workdir"], paths["telemetry"]],
    )
    assert censo["mechanism"] == SANDBOX_MECHANISM
    assert censo["candidate_token_integrity_sid"] == LOW_INTEGRITY_SID
    assert set(censo["writable_roots"].values()) == {LOW_INTEGRITY_SID}
    assert set(censo["protected_roots"].values()) == {None}
    assert censo["output_root_present"] is False
    assert censo["denial_probe"]["performed"] is True
    assert censo["denial_probe"]["returncode"] == 0


def test_probe_de_denegacion_mide_el_sistema_y_falla_si_no_deniega(tmp_path: Path) -> None:
    paths = _workdir(tmp_path)
    probe = probe_output_root_denial(paths["outputs"], python_executable=Path(sys.executable))
    assert probe == {
        "performed": True,
        "probe_integrity_sid": LOW_INTEGRITY_SID,
        "denied_operations": list(DENIED_OPERATIONS),
        "returncode": 0,
    }
    # Si el destino vive donde el token Low sí puede escribir, el probe debe declararlo rojo en
    # vez de dar por buena una garantía que el volumen no impone.
    apply_low_integrity_label(paths["staging"])
    with pytest.raises(SandboxError, match="no denegó alguna de las operaciones"):
        probe_output_root_denial(
            paths["staging"] / "outputs", python_executable=Path(sys.executable)
        )


def test_censo_rechaza_probe_no_ejecutado(tmp_path: Path) -> None:
    paths = _workdir(tmp_path)
    apply_low_integrity_label(paths["staging"])
    with pytest.raises(SandboxError, match="probe de denegación efectivamente ejecutado"):
        census_output_isolation(
            output_root=paths["outputs"],
            writable_roots=[paths["staging"]],
            protected_roots=[paths["workdir"]],
            denial_probe={"performed": False, "returncode": 0},
        )


def test_censo_rechaza_raiz_escribible_sin_etiqueta(tmp_path: Path) -> None:
    paths = _workdir(tmp_path)
    with pytest.raises(SandboxError, match="sin etiqueta Low efectiva"):
        _censo(
            output_root=paths["outputs"],
            writable_roots=[paths["staging"]],
            protected_roots=[paths["workdir"]],
        )


def test_censo_rechaza_raiz_protegida_con_etiqueta(tmp_path: Path) -> None:
    paths = _workdir(tmp_path)
    apply_low_integrity_label(paths["staging"])
    # Se etiqueta `telemetry`, no `workdir`: si se etiquetara el padre de OUTPUT_ROOT ganaría el
    # probe de denegación —una señal más fuerte— y esta prueba dejaría de ejercitar el censo.
    apply_low_integrity_label(paths["telemetry"])
    with pytest.raises(SandboxError, match="raíz protegida con etiqueta"):
        _censo(
            output_root=paths["outputs"],
            writable_roots=[paths["staging"]],
            protected_roots=[paths["workdir"], paths["telemetry"]],
        )


def test_probe_gana_al_censo_si_el_padre_de_output_root_queda_escribible(
    tmp_path: Path,
) -> None:
    """La señal medida manda sobre la declarada: si el SO no deniega, no hay garantía."""
    paths = _workdir(tmp_path)
    apply_low_integrity_label(paths["staging"])
    apply_low_integrity_label(paths["workdir"])
    with pytest.raises(SandboxError, match="no denegó alguna de las operaciones"):
        _censo(
            output_root=paths["outputs"],
            writable_roots=[paths["staging"]],
            protected_roots=[paths["workdir"]],
        )


def test_censo_rechaza_output_root_existente(tmp_path: Path) -> None:
    paths = _workdir(tmp_path)
    apply_low_integrity_label(paths["staging"])
    paths["outputs"].mkdir()
    with pytest.raises(SandboxError, match="OUTPUT_ROOT existe"):
        _censo(
            output_root=paths["outputs"],
            writable_roots=[paths["staging"]],
            protected_roots=[paths["workdir"]],
        )


def test_censo_rechaza_raiz_declarada_en_ambas_listas(tmp_path: Path) -> None:
    paths = _workdir(tmp_path)
    apply_low_integrity_label(paths["staging"])
    with pytest.raises(SandboxError, match="escribible y protegida"):
        _censo(
            output_root=paths["outputs"],
            writable_roots=[paths["staging"]],
            protected_roots=[paths["staging"]],
        )


def test_token_candidato_queda_en_integridad_low_y_difiere_del_arnes() -> None:
    with low_integrity_primary_token() as token:
        assert token_integrity_level(token) == LOW_INTEGRITY_SID
    assert process_integrity_level(os.getpid()) != LOW_INTEGRITY_SID


def test_candidato_low_no_crea_borra_ni_reemplaza_output_root(tmp_path: Path) -> None:
    paths = _workdir(tmp_path)
    apply_low_integrity_label(paths["staging"])
    outputs = paths["outputs"]
    body = (
        "import os, sys\n"
        f"outputs = r'{outputs}'\n"
        f"workdir = r'{paths['workdir']}'\n"
        f"telemetry = r'{paths['telemetry']}'\n"
        "fallos = 0\n"
        "try:\n"
        "    os.mkdir(outputs)\n"
        "    fallos |= 1\n"
        "except PermissionError:\n"
        "    pass\n"
        "try:\n"
        "    open(os.path.join(workdir, 'manifest.json'), 'xb').write(b'{}')\n"
        "    fallos |= 2\n"
        "except PermissionError:\n"
        "    pass\n"
        "try:\n"
        "    open(os.path.join(telemetry, 'boundary.jsonl'), 'wb').write(b'falsificado')\n"
        "    fallos |= 4\n"
        "except PermissionError:\n"
        "    pass\n"
        "sys.exit(fallos)\n"
    )
    code, _, stderr, low = _run_child(paths, body)
    assert low == 1
    assert stderr == b""
    assert code == 0, f"el candidato alcanzó OUTPUT_ROOT/telemetry: máscara {code}"
    assert not outputs.exists()


def test_candidato_low_no_borra_ni_reemplaza_manifiesto_publicado(tmp_path: Path) -> None:
    paths = _workdir(tmp_path)
    apply_low_integrity_label(paths["staging"])
    outputs = paths["outputs"]
    outputs.mkdir()
    manifest = outputs / "manifest.json"
    manifest.write_bytes(b'{"publicado": true}')
    body = (
        "import os, sys\n"
        f"manifest = r'{manifest}'\n"
        "fallos = 0\n"
        "try:\n"
        "    open(manifest, 'wb').write(b'falsificado')\n"
        "    fallos |= 1\n"
        "except PermissionError:\n"
        "    pass\n"
        "try:\n"
        "    os.remove(manifest)\n"
        "    fallos |= 2\n"
        "except PermissionError:\n"
        "    pass\n"
        "try:\n"
        "    os.replace(manifest, manifest + '.bak')\n"
        "    fallos |= 4\n"
        "except PermissionError:\n"
        "    pass\n"
        "sys.exit(fallos)\n"
    )
    code, _, stderr, low = _run_child(paths, body)
    assert low == 1
    assert stderr == b""
    assert code == 0, f"el candidato tocó el manifiesto: máscara {code}"
    assert manifest.read_bytes() == b'{"publicado": true}'


def test_descendiente_del_candidato_hereda_la_integridad_low(tmp_path: Path) -> None:
    """La garantía debe alcanzar a todo el árbol, no sólo al proceso raíz del candidato."""
    paths = _workdir(tmp_path)
    apply_low_integrity_label(paths["staging"])
    nieto = paths["staging"] / "nieto.py"
    nieto.write_text(
        "import os, sys\n"
        f"outputs = r'{paths['outputs']}'\n"
        "try:\n"
        "    os.mkdir(outputs)\n"
        "except PermissionError:\n"
        "    sys.exit(0)\n"
        "sys.exit(1)\n",
        encoding="utf-8",
    )
    body = (
        "import subprocess, sys\n"
        f"completed = subprocess.run([sys.executable, '-I', '-B', '-S', r'{nieto}'], check=False)\n"
        "sys.exit(completed.returncode)\n"
    )
    code, _, stderr, low = _run_child(paths, body)
    assert low == 1
    assert code == 0, stderr.decode("utf-8", errors="replace")
    assert not paths["outputs"].exists()


def test_control_negativo_sin_sandbox_el_candidato_si_alcanza_output_root(
    tmp_path: Path,
) -> None:
    """Sin el token Low la misma operación tiene éxito: el oráculo no es vacío."""
    paths = _workdir(tmp_path)
    outputs = paths["outputs"]
    body = f"import os, sys\noutputs = r'{outputs}'\nos.mkdir(outputs)\nsys.exit(0)\n"
    code, _, stderr, low = _run_child(paths, body, sandboxed=False)
    assert low is None
    assert code == 0, stderr.decode("utf-8", errors="replace")
    assert outputs.is_dir()


def test_candidato_low_escribe_en_staging_y_lee_material_protegido(tmp_path: Path) -> None:
    paths = _workdir(tmp_path)
    apply_low_integrity_label(paths["staging"])
    entrada = paths["workdir"] / "input.bin"
    entrada.write_bytes(b"entrada del candidato")
    body = (
        "import sys\n"
        f"entrada = r'{entrada}'\n"
        f"salida = r'{paths['staging'] / 'salida.bin'}'\n"
        "datos = open(entrada, 'rb').read()\n"
        "open(salida, 'xb').write(datos)\n"
        "sys.exit(0 if datos == b'entrada del candidato' else 9)\n"
    )
    code, _, stderr, low = _run_child(paths, body)
    assert low == 1
    assert stderr == b""
    assert code == 0
    assert (paths["staging"] / "salida.bin").read_bytes() == b"entrada del candidato"


def test_candidato_recibe_stdin_nul_y_no_hereda_handles_ajenos(tmp_path: Path) -> None:
    paths = _workdir(tmp_path)
    apply_low_integrity_label(paths["staging"])
    secreto = paths["telemetry"] / "secreto.bin"
    secreto.write_bytes(b"material del arnes")
    descriptor = os.open(secreto, os.O_RDONLY)
    try:
        import msvcrt

        handle = msvcrt.get_osfhandle(descriptor)
        body = (
            "import os, sys\n"
            "import msvcrt\n"
            "if sys.stdin.buffer.read() != b'':\n"
            "    sys.exit(1)\n"
            "try:\n"
            "    prestado = msvcrt.open_osfhandle(int(sys.argv[1]), os.O_RDONLY)\n"
            "    datos = os.read(prestado, 32)\n"
            "except OSError:\n"
            "    sys.exit(0)\n"
            "sys.exit(0 if datos != b'material del arnes' else 2)\n"
        )
        code, _, stderr, low = _run_child(paths, body, extra_argv=(str(handle),))
    finally:
        os.close(descriptor)
    assert low == 1
    assert stderr == b""
    assert code == 0, "el candidato leyó un handle que el arnés no le declaró"


def test_lanzamiento_rechaza_comando_o_entorno_invalido(tmp_path: Path) -> None:
    paths = _workdir(tmp_path)
    apply_low_integrity_label(paths["staging"])
    stdout_path = paths["telemetry"] / "vacio.bin"
    with stdout_path.open("xb") as handle, low_integrity_primary_token() as token:
        with pytest.raises(SandboxError, match="está vacío"):
            launch_suspended_low_integrity(
                [],
                token=token,
                cwd=paths["staging"],
                environment={},
                stdout_fd=handle.fileno(),
                stderr_fd=handle.fileno(),
            )
        with pytest.raises(SandboxError, match="contiene NUL"):
            launch_suspended_low_integrity(
                [sys.executable, "-c", "pass\0"],
                token=token,
                cwd=paths["staging"],
                environment={},
                stdout_fd=handle.fileno(),
                stderr_fd=handle.fileno(),
            )
        with pytest.raises(SandboxError, match="nombre inválido"):
            launch_suspended_low_integrity(
                [sys.executable, "-c", "pass"],
                token=token,
                cwd=paths["staging"],
                environment={"MAL=NOMBRE": "x"},
                stdout_fd=handle.fileno(),
                stderr_fd=handle.fileno(),
            )


def test_etiqueta_rechaza_destino_inexistente(tmp_path: Path) -> None:
    with pytest.raises(SandboxError, match="inexistente o no plano"):
        apply_low_integrity_label(tmp_path / "no-existe")


def test_censo_detecta_etiqueta_no_declarada_bajo_el_workdir(tmp_path: Path) -> None:
    """Enumerar las raíces nombradas prueba que están bien, no que sean las únicas."""
    paths = _workdir(tmp_path)
    apply_low_integrity_label(paths["staging"])
    intruso = paths["workdir"] / "intruso"
    intruso.mkdir()
    apply_low_integrity_label(intruso)
    with pytest.raises(SandboxError, match="etiqueta obligatoria inesperada"):
        _censo(
            output_root=paths["outputs"],
            writable_roots=[paths["staging"]],
            protected_roots=[paths["workdir"], paths["telemetry"]],
        )
    clear_mandatory_label(intruso)
    censo = _censo(
        output_root=paths["outputs"],
        writable_roots=[paths["staging"]],
        protected_roots=[paths["workdir"], paths["telemetry"]],
    )
    assert censo["output_root_present"] is False


def test_retirar_la_etiqueta_devuelve_la_ruta_a_integridad_media(tmp_path: Path) -> None:
    paths = _workdir(tmp_path)
    apply_low_integrity_label(paths["staging"])
    assert mandatory_label(paths["staging"]) == LOW_INTEGRITY_SID
    clear_mandatory_label(paths["staging"])
    assert mandatory_label(paths["staging"]) is None


def test_plan_deriva_las_raices_del_layout_cerrado(tmp_path: Path) -> None:
    paths = _workdir(tmp_path)
    pycache = paths["pycache"]
    candidate_root = paths["candidate_root"]
    plan = _candidate_output_isolation_plan(
        {"staging": paths["staging"], "pycache": pycache},
        candidate_root=candidate_root,
        workdir=paths["workdir"],
    )
    assert plan["output_root"] == paths["outputs"]
    assert plan["writable_roots"] == [
        paths["staging"],
        paths["candidate_runtime"],
        pycache,
    ]
    # El plan y la revalidación deben coincidir en cardinalidad con el contrato durable: tres
    # escribibles y seis protegidas. Si divergieran, la evidencia del productor no pasaría su
    # propio validador.
    assert len(plan["writable_roots"]) == 3
    assert len(plan["protected_roots"]) == 6
    assert candidate_root in plan["protected_roots"]
    assert paths["telemetry"] in plan["protected_roots"]
    # El snapshot de fuentes del arnés cuelga de `scratch`, que queda protegido: si estuviera
    # entre las escribibles, el candidato podría reescribir el driver que ejecuta el controller.
    assert paths["scratch"] in plan["protected_roots"]


def test_plan_rechaza_staging_que_no_deriva_del_workdir(tmp_path: Path) -> None:
    paths = _workdir(tmp_path)
    ajeno = tmp_path / "otro" / "scratch" / "consumer-staging"
    ajeno.mkdir(parents=True)
    with pytest.raises(ContractError, match="no deriva del workdir"):
        _candidate_output_isolation_plan(
            {"staging": ajeno, "pycache": paths["staging"]},
            candidate_root=tmp_path,
            workdir=paths["workdir"],
        )


def _isolation_evidence(paths: dict[str, Path]) -> dict[str, object]:
    """Evidencia completa del layout cerrado: tres raíces escribibles y seis protegidas."""
    return {
        "schema_version": CANDIDATE_OUTPUT_ISOLATION_SCHEMA_VERSION,
        "mechanism": SANDBOX_MECHANISM,
        "candidate_token_integrity_sid": LOW_INTEGRITY_SID,
        "candidate_effective_integrity_sid": LOW_INTEGRITY_SID,
        "writable_roots": {
            str(paths["staging"].resolve()): LOW_INTEGRITY_SID,
            str(paths["candidate_runtime"].resolve()): LOW_INTEGRITY_SID,
            str(paths["pycache"].resolve()): LOW_INTEGRITY_SID,
        },
        "protected_roots": {
            str(paths["workdir"].resolve()): None,
            str(paths["scratch"].resolve()): None,
            str(paths["python_cache"].resolve()): None,
            str(paths["telemetry"].resolve()): None,
            str(paths["control"].resolve()): None,
            str(paths["candidate_root"].resolve()): None,
        },
        "output_root": str(paths["outputs"]),
        "output_root_present": False,
        "container_objects_inspected": 8,
        "denial_probe": {
            "performed": True,
            "probe_integrity_sid": LOW_INTEGRITY_SID,
            "denied_operations": list(DENIED_OPERATIONS),
            "returncode": 0,
        },
        "observed_monotonic_ns": 1_234_567,
    }


def test_revalidacion_del_adapter_remide_las_etiquetas_tras_la_quiescencia(
    tmp_path: Path,
) -> None:
    paths = _workdir(tmp_path)
    _label_writable_roots(paths)
    evidencia = _isolation_evidence(paths)
    assert _validate_output_isolation(
        evidencia, output_root=paths["outputs"], staging=paths["staging"]
    )


def test_revalidacion_del_adapter_cae_si_una_raiz_perdio_su_etiqueta(tmp_path: Path) -> None:
    """El candidato pudo haber mutado etiquetas: la evidencia declarada no basta."""
    paths = _workdir(tmp_path)
    _label_writable_roots(paths)
    evidencia = _isolation_evidence(paths)
    clear_mandatory_label(paths["staging"])
    with pytest.raises(ContractError, match="perdió la etiqueta Low efectiva"):
        _validate_output_isolation(
            evidencia, output_root=paths["outputs"], staging=paths["staging"]
        )


def test_revalidacion_del_adapter_cae_si_una_raiz_protegida_quedo_etiquetada(
    tmp_path: Path,
) -> None:
    paths = _workdir(tmp_path)
    _label_writable_roots(paths)
    evidencia = _isolation_evidence(paths)
    apply_low_integrity_label(paths["telemetry"])
    with pytest.raises(ContractError, match="quedó con etiqueta obligatoria"):
        _validate_output_isolation(
            evidencia, output_root=paths["outputs"], staging=paths["staging"]
        )


@pytest.mark.parametrize(
    ("mutacion", "match"),
    [
        ({"candidate_effective_integrity_sid": MEDIUM_INTEGRITY_SID}, "mecanismo OS"),
        ({"output_root_present": True}, "mecanismo OS"),
        ({"writable_roots": {}}, "vacías o superpuestas"),
    ],
)
def test_revalidacion_del_adapter_rechaza_evidencia_degradada(
    tmp_path: Path, mutacion: dict[str, object], match: str
) -> None:
    paths = _workdir(tmp_path)
    _label_writable_roots(paths)
    evidencia = {**_isolation_evidence(paths), **mutacion}
    with pytest.raises(ContractError, match=match):
        _validate_output_isolation(
            evidencia, output_root=paths["outputs"], staging=paths["staging"]
        )


def test_censo_detecta_archivo_etiquetado_bajo_padre_protegido(tmp_path: Path) -> None:
    """El vector real: heredar la etiqueta en una raíz Low y mover el archivo a una protegida.

    La integridad obligatoria protege cada objeto y no se deriva del padre, así que ese archivo
    seguiría siendo escribible por el candidato pese a colgar de un directorio de integridad
    media. Un censo que sólo recorriera directorios lo daría por verde.
    """
    paths = _workdir(tmp_path)
    apply_low_integrity_label(paths["staging"])
    heredado = paths["staging"] / "heredado.bin"
    heredado.write_bytes(b"contenido heredado")
    assert mandatory_label(heredado) == LOW_INTEGRITY_SID
    intruso = paths["workdir"] / "intruso-archivo.bin"
    os.replace(heredado, intruso)
    assert mandatory_label(intruso) == LOW_INTEGRITY_SID
    with pytest.raises(SandboxError, match="etiqueta obligatoria inesperada"):
        _censo(
            output_root=paths["outputs"],
            writable_roots=[paths["staging"]],
            protected_roots=[paths["workdir"], paths["telemetry"]],
        )
    intruso.unlink()
    reconciliado = _censo(
        output_root=paths["outputs"],
        writable_roots=[paths["staging"]],
        protected_roots=[paths["workdir"], paths["telemetry"]],
    )
    assert reconciliado["container_objects_inspected"] > 0


def test_censo_publica_cuantos_objetos_recorrio(tmp_path: Path) -> None:
    """La amplitud del recorrido es evidencia: un censo que dejara de recorrer caería a cero."""
    paths = _workdir(tmp_path)
    apply_low_integrity_label(paths["staging"])
    censo = _censo(
        output_root=paths["outputs"],
        writable_roots=[paths["staging"]],
        protected_roots=[paths["workdir"], paths["telemetry"]],
    )
    inspeccionados = censo["container_objects_inspected"]
    assert isinstance(inspeccionados, int)
    # scratch, consumer-staging, candidate-runtime, python-cache, candidate-child, telemetry y
    # control: el contenedor tiene más de un objeto y el censo debe haberlos visto.
    assert inspeccionados >= 7
    (paths["telemetry"] / "archivo-nuevo.bin").write_bytes(b"x")
    ampliado = _censo(
        output_root=paths["outputs"],
        writable_roots=[paths["staging"]],
        protected_roots=[paths["workdir"], paths["telemetry"]],
    )
    assert ampliado["container_objects_inspected"] == inspeccionados + 1


def test_censo_rechaza_junction_dentro_del_contenedor(tmp_path: Path) -> None:
    """Una junction se crea **sin privilegios** y no se declara como symlink.

    Medido en esta torre: ``is_symlink()`` devuelve ``False`` y ``is_dir(follow_symlinks=False)``
    devuelve ``True``, así que un censo que filtrara por directorio la recorrería y leería la
    etiqueta del destino —fuera del contenedor— en vez de la del objeto que el candidato alcanza
    por esa ruta. Por eso la detección se hace por el bit ``FILE_ATTRIBUTE_REPARSE_POINT``.
    """
    paths = _workdir(tmp_path)
    apply_low_integrity_label(paths["staging"])
    externo = tmp_path / "externo"
    externo.mkdir()
    enlace = paths["workdir"] / "redirigido"
    try:
        _winapi.CreateJunction(str(externo), str(enlace))
    except OSError as exc:  # pragma: no cover - torre sin soporte de junctions
        pytest.skip(f"junctions no disponibles: {exc}")
    assert enlace.is_symlink() is False
    with pytest.raises(SandboxError, match="reparse point prohibido"):
        _censo(
            output_root=paths["outputs"],
            writable_roots=[paths["staging"]],
            protected_roots=[paths["workdir"], paths["telemetry"]],
        )


def test_censo_rechaza_symlink_dentro_del_contenedor(tmp_path: Path) -> None:
    """El otro sentido del mismo criterio, cuando la torre sí concede el privilegio."""
    paths = _workdir(tmp_path)
    apply_low_integrity_label(paths["staging"])
    externo = tmp_path / "externo"
    externo.mkdir()
    enlace = paths["workdir"] / "redirigido"
    try:
        enlace.symlink_to(externo, target_is_directory=True)
    except OSError as exc:  # pragma: no cover - torre sin privilegio de symlink
        pytest.skip(f"symlinks no disponibles: {exc}")
    with pytest.raises(SandboxError, match="reparse point prohibido"):
        _censo(
            output_root=paths["outputs"],
            writable_roots=[paths["staging"]],
            protected_roots=[paths["workdir"], paths["telemetry"]],
        )


def test_censo_rechaza_hardlink_dentro_del_contenedor(tmp_path: Path) -> None:
    """Un hardlink da un segundo nombre al mismo contenido, fuera del subárbol censado."""
    paths = _workdir(tmp_path)
    apply_low_integrity_label(paths["staging"])
    original = tmp_path / "original.bin"
    original.write_bytes(b"contenido compartido")
    alias = paths["telemetry"] / "alias.bin"
    try:
        os.link(original, alias)
    except OSError as exc:  # pragma: no cover - volumen sin soporte de hardlinks
        pytest.skip(f"hardlinks no disponibles: {exc}")
    with pytest.raises(SandboxError, match="hardlink prohibido"):
        _censo(
            output_root=paths["outputs"],
            writable_roots=[paths["staging"]],
            protected_roots=[paths["workdir"], paths["telemetry"]],
        )


def test_probe_deniega_crear_y_sobrescribir_archivo_no_solo_directorios(tmp_path: Path) -> None:
    """La matriz cubre FILE_ADD_FILE y FILE_WRITE_DATA, no sólo verbos de directorio.

    Sin estos dos, un manifiesto ya publicado podría falsificarse en sitio en vez de
    reemplazarse, y el probe seguiría verde.
    """
    paths = _workdir(tmp_path)
    assert list(DENIED_OPERATIONS) == [
        "create_directory",
        "create_file",
        "delete_file",
        "replace_file",
        "overwrite_file",
    ]
    probe = probe_output_root_denial(paths["outputs"], python_executable=Path(sys.executable))
    assert probe["denied_operations"] == list(DENIED_OPERATIONS)
    assert probe["returncode"] == 0
    # El probe no deja residuo de ninguno de los cinco verbos dentro del contenedor.
    assert sorted(item.name for item in paths["workdir"].iterdir()) == ["scratch", "telemetry"]


def test_probe_rojo_si_el_contenedor_es_escribible_por_el_candidato(tmp_path: Path) -> None:
    """Control de vacuidad del probe ampliado: donde Low sí escribe, debe ponerse rojo."""
    paths = _workdir(tmp_path)
    apply_low_integrity_label(paths["staging"])
    with pytest.raises(SandboxError, match="no denegó alguna de las operaciones"):
        probe_output_root_denial(
            paths["staging"] / "outputs", python_executable=Path(sys.executable)
        )


def test_terminated_on_exit_no_deja_huerfano_un_hijo_suspendido(tmp_path: Path) -> None:
    """close() sólo suelta handles: sin terminar, el hijo quedaría vivo y ya inmatable."""
    paths = _workdir(tmp_path)
    script = paths["staging"] / "dormilon.py"
    script.write_text("import time\ntime.sleep(600)\n", encoding="utf-8")
    stdout_path = paths["telemetry"] / "dormilon.stdout.bin"
    stderr_path = paths["telemetry"] / "dormilon.stderr.bin"
    with (
        stdout_path.open("xb") as out,
        stderr_path.open("xb") as err,
        low_integrity_primary_token() as token,
    ):
        process = launch_suspended_low_integrity(
            [sys.executable, "-I", "-B", "-S", str(script)],
            token=token,
            cwd=paths["staging"],
            environment={"SYSTEMROOT": os.environ["SYSTEMROOT"]},
            stdout_fd=out.fileno(),
            stderr_fd=err.fileno(),
        )
        pid = process.pid
        # El bloque sale por excepción con el hijo todavía suspendido: es exactamente el camino
        # que antes filtraba el proceso.
        with pytest.raises(RuntimeError, match="fallo inyectado"), terminated_on_exit(process):
            raise RuntimeError("fallo inyectado antes de reanudar")
    with pytest.raises(SandboxError):
        process_integrity_level(pid)


def test_revalidacion_exige_las_raices_exactas_del_layout(tmp_path: Path) -> None:
    """Omitir una raíz dejaría acreditado el aislamiento con cobertura parcial."""
    paths = _workdir(tmp_path)
    _label_writable_roots(paths)
    evidencia = _isolation_evidence(paths)
    sin_runtime = dict(evidencia)
    writable = dict(evidencia["writable_roots"])
    del writable[str(paths["candidate_runtime"].resolve())]
    sin_runtime["writable_roots"] = writable
    with pytest.raises(ContractError, match="exactamente las raíces escribibles"):
        _validate_output_isolation(
            sin_runtime, output_root=paths["outputs"], staging=paths["staging"]
        )
    sin_control = dict(evidencia)
    protected = dict(evidencia["protected_roots"])
    del protected[str(paths["control"].resolve())]
    sin_control["protected_roots"] = protected
    with pytest.raises(ContractError, match="exactamente las raíces protegidas"):
        _validate_output_isolation(
            sin_control, output_root=paths["outputs"], staging=paths["staging"]
        )


def test_revalidacion_rechaza_arbol_candidato_dentro_de_raiz_escribible(tmp_path: Path) -> None:
    """El candidato no puede declarar protegido un árbol que él mismo puede reescribir."""
    paths = _workdir(tmp_path)
    _label_writable_roots(paths)
    evidencia = _isolation_evidence(paths)
    protected = dict(evidencia["protected_roots"])
    del protected[str(paths["candidate_root"].resolve())]
    protected[str((paths["staging"] / "arbol").resolve())] = None
    evidencia["protected_roots"] = protected
    with pytest.raises(ContractError, match="bajo una raíz escribible"):
        _validate_output_isolation(
            evidencia, output_root=paths["outputs"], staging=paths["staging"]
        )
