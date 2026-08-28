"""Gates de la gobernanza alcanzable desde los presets (D-GOB-8).

Lo que se vigila aquí es que la gobernanza deje de ser inalcanzable **sin** que el motor invente un
``DATO-INSTITUCIONAL``: ``audit`` se enciende porque no tiene ningún campo obligatorio;
``governance`` no, porque ``purpose`` sí lo tiene y sólo la institución puede fijarlo.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from nikodym.core.config import NikodymConfig, config_hash
from nikodym.core.config.hashing import INFRA_SECTIONS
from nikodym.governance.config import GovernanceConfig
from nikodym.ui.presets import get_preset, list_presets

_RAIZ = Path(__file__).resolve().parents[2]
_FIXTURES_DEMO = _RAIZ / "web" / "src" / "fixtures" / "demo"


def _configs_de_preset() -> dict[str, dict]:
    """Los cuatro presets publicados, por id."""
    salida: dict[str, dict] = {}
    for entrada in list_presets():
        pid = entrada["id"] if isinstance(entrada, dict) else entrada
        descriptor = get_preset(pid)
        salida[pid] = descriptor.get("config", descriptor)
    return salida


def test_los_cuatro_presets_encienden_audit_y_solo_audit() -> None:
    """``audit`` activo; ``governance`` y ``tracking`` siguen en ``None`` (D-GOB-8).

    Los tres valores juntos, no por separado: encender ``governance`` obligaría al preset a
    inventar un ``purpose``, y encender ``tracking`` rompería la corrida de quien no tiene un
    servidor MLflow.
    """
    configs = _configs_de_preset()
    assert len(configs) == 4, f"se esperaban 4 presets y hay {len(configs)}: {sorted(configs)}"

    for pid, cfg in configs.items():
        assert cfg["audit"] == {"enabled": True}, f"{pid}: audit debería estar encendido"
        assert cfg["governance"] is None, f"{pid}: governance no se enciende de fábrica"
        assert cfg["tracking"] is None, f"{pid}: tracking exige un servidor MLflow"


def test_purpose_no_tiene_default_y_por_eso_el_preset_no_lo_inventa() -> None:
    """La razón de D-GOB-8, comprobada en el código y no sólo escrita en el SDD.

    Si ``purpose`` ganara un default, este test se pondría rojo y habría que revisar la decisión:
    dejaría de ser cierto que un preset no puede encender ``governance`` sin inventar el dato.
    """
    campo = GovernanceConfig.model_fields["purpose"]
    assert campo.is_required(), (
        "purpose dejó de ser obligatorio: revisar D-GOB-8, cuya razón entera es que sólo la "
        "institución puede declarar el propósito de un modelo (SR 11-7)."
    )
    with pytest.raises(ValueError, match="purpose"):
        GovernanceConfig(model_name="sin-proposito")


def test_encender_audit_no_mueve_el_config_hash_de_ningun_preset() -> None:
    """🔴 Corrige la advertencia de D-GOB-8: ``audit`` es INFRA y **no** entra a la identidad.

    La enmienda anunció que encender ``audit`` movería el ``config_hash`` de los cuatro presets y
    que por eso haría falta recapturar la demo. Medido sobre el árbol, es falso: ``audit`` está en
    :data:`~nikodym.core.config.hashing.INFRA_SECTIONS`, así que la identidad lógica de la corrida
    —datos + método + semilla— no se mueve. Este gate lo fija para que la corrección no se pierda.
    """
    assert "audit" in INFRA_SECTIONS

    for pid, cfg in _configs_de_preset().items():
        con_audit = NikodymConfig.model_validate(cfg)
        apagado = copy.deepcopy(cfg)
        apagado["audit"] = None
        sin_audit = NikodymConfig.model_validate(apagado)
        assert config_hash(con_audit) == config_hash(sin_audit), (
            f"{pid}: encender audit movió el config_hash; audit dejó de ser INFRA"
        )


@pytest.mark.parametrize(
    ("fixture", "preset_id"),
    [
        ("results-f1.json", "f1-estandar-consumo"),
        ("results.json", "f3-provisiones-consumo"),
        ("results-ifrs9.json", "f4-ifrs9-retail"),
    ],
)
def test_los_fixtures_de_la_demo_conservan_su_config_hash(fixture: str, preset_id: str) -> None:
    """La demo publicada sigue firmando la identidad correcta tras D-GOB-8.

    Es la comprobación que decide si la recaptura de la demo (D-GOB-9) es obligatoria por identidad
    o sólo por contenido: si el hash se moviera, los tres fixtures quedarían firmando una corrida
    que ya no existe. No se mueve — lo que queda desalineado es ``model_card: null``, que es otra
    conversación y tiene su propio OK.
    """
    ruta = _FIXTURES_DEMO / fixture
    if not ruta.is_file():
        pytest.skip(f"fixture de demo ausente: {fixture}")

    publicado = json.loads(ruta.read_text(encoding="utf-8"))
    hash_publicado = (publicado.get("lineage") or {}).get("config_hash")
    assert hash_publicado, f"{fixture} no trae config_hash en su lineage"

    del publicado
    esperado = config_hash(NikodymConfig.model_validate(_configs_de_preset()[preset_id]))
    assert hash_publicado == esperado, (
        f"{fixture} firma {hash_publicado[:16]}… y el preset produce {esperado[:16]}…: la demo "
        "quedó desalineada y su recaptura pasa a ser obligatoria por identidad (D-GOB-9)."
    )


def test_una_corrida_de_preset_por_la_interfaz_archiva_su_trail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """El trail de un preset acaba en ``runs/<run_id>/``, y **nada** en el cwd del servidor.

    Es el gate del cableado que D-GOB-8 hizo obligatorio: con ``audit`` encendido en los cuatro
    presets y D-GOB-7 prohibiendo la ruta relativa, sin este cableado **toda** corrida de preset por
    la interfaz falla. Medido: los tres tests de ``test_ui_routes`` que corren presets se pusieron
    rojos al encender ``audit``, y este cableado es lo que los devolvió a verde.

    Se comprueba además que el model card ya trae ``decisions``, que es la razón entera por la que
    D-GOB-8 enciende ``audit``: antes la interfaz construía el card sin trail y la lista salía
    siempre vacía, con su warning silenciado.
    """
    pytest.importorskip("optbinning")
    from nikodym.ui import routes, runs
    from nikodym.ui.presets import STANDARD_DATASET_ID, standard_preset

    cwd = tmp_path / "cwd-del-servidor"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    workdir = tmp_path / "workdir"

    config = standard_preset()["config"]
    config["governance"] = {
        "model_name": "scorecard-consumo",
        "purpose": "Originación de consumo; decisión de aprobación.",
    }
    resultado = routes.run_pipeline(config, STANDARD_DATASET_ID, workdir=workdir)

    assert resultado["status"] == "done"
    run_id = resultado["run_id"]

    trail = workdir / "runs" / run_id / "audit_trail.jsonl"
    assert trail.is_file(), "el trail no quedó archivado junto a su corrida"
    assert trail.stat().st_size > 0

    assert list(cwd.iterdir()) == [], (
        f"la corrida ensució el cwd del servidor: {list(cwd.iterdir())}"
    )
    huerfanos = list((workdir / "runs").glob(".trail-*.jsonl"))
    assert not huerfanos, f"quedó un trail sin archivar: {huerfanos}"

    resultados = runs.load_results(run_id, workdir=workdir)
    card = resultados["model_card"]
    assert card is not None, "con governance declarada el card no puede salir ausente"
    assert card["decisions"], (
        "el model card salió sin decisiones: el trail no llegó al builder, que es exactamente lo "
        "que D-GOB-8 viene a arreglar"
    )
    assert card["metrics"], "el model card de la interfaz salió sin métricas (D-GOB-1…4)"
    assert "data.n_rows" in card["metrics"]


def test_un_objeto_auditable_no_arrastra_su_sink_al_copiarse(tmp_path: Path) -> None:
    """Regresión del defecto que D-GOB-8 destapó, medido antes en un árbol sin D-GOB.

    Con ``audit`` encendido, un ``AuditableMixin`` lleva un ``JsonlAuditSink`` con un descriptor de
    archivo abierto. ``SurvivalResult.estimator`` es uno de ellos, así que el
    ``result.model_copy(deep=True)`` de ``survival/step.py`` moría con
    ``TypeError: cannot pickle 'TextIOWrapper' instances`` **antes** de publicar sus artefactos —y
    como es un ``TypeError`` y no un ``NikodymError``, ``nikodym.run`` no lo capturaba: la corrida
    entera reventaba en vez de devolver un ``Study`` inspeccionable.

    No se veía porque hasta D-GOB-8 ningún preset traía ``audit`` encendido.
    """
    from copy import deepcopy

    from nikodym.audit import AuditConfig, JsonlAuditSink
    from nikodym.core.audit import NullAuditSink
    from nikodym.core.mixins import AuditableMixin

    class _Estimador(AuditableMixin):
        def __init__(self) -> None:
            self.parametro = [1, 2, 3]

    trail = tmp_path / "trail.jsonl"
    with JsonlAuditSink(trail, config=AuditConfig()) as sink:
        original = _Estimador()
        original._audit = sink

        copia = deepcopy(original)

        assert isinstance(copia._audit, NullAuditSink), (
            "la copia arrastró el sink vivo: un artefacto persistido no puede sostener un "
            "descriptor de archivo del proceso que lo creó"
        )
        # …y el resto del estado sí se copia, en profundidad.
        assert copia.parametro == [1, 2, 3]
        assert copia.parametro is not original.parametro
        # El original conserva el suyo: copiar no desarma al objeto vivo.
        assert original._audit is sink
