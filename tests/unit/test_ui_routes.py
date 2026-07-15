"""Tests de la lógica pura de los endpoints y del contrato *domain-agnostic* (SDD-23 §4.2, §11).

La lógica de ``/schema``/``/validate``/``/datasets`` se prueba **sin FastAPI** (funciones puras);
el cableado HTTP se prueba en ``test_ui_server.py`` vía ``TestClient``. Aquí también viven los
tests AST de la frontera: ``nikodym.ui`` no usa ``eval``/``exec``, no importa módulos de dominio y
no reimplementa fórmulas de riesgo.
"""

from __future__ import annotations

import ast
import importlib.util
import io
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from _ui_f1 import failing_config, full_f1_config, write_behavior_parquet

from nikodym.core.config import NikodymConfig, ReproConfig, config_hash, dump_config, loads_config
from nikodym.core.config.migration import _MIGRATORS, migration
from nikodym.core.exceptions import ConfigError
from nikodym.ui import datasets as datasets_module
from nikodym.ui import routes
from nikodym.ui.exceptions import UiDatasetError

# ─────────────────────────────── lógica pura de endpoints ───────────────────────────────


def test_schema_payload_shape() -> None:
    """``/schema`` entrega el JSON-Schema, los defaults y el orden de secciones declarado."""
    payload = routes.schema_payload()
    assert set(payload) == {"json_schema", "defaults", "section_order"}
    assert payload["section_order"] == list(NikodymConfig.model_fields)
    assert payload["section_order"][0] == "schema_version"
    assert {"repro", "data", "report"} <= set(payload["section_order"])
    assert "properties" in payload["json_schema"]
    assert payload["defaults"]["repro"]["seed"] == 42  # defaults resueltos del config vacío


def test_schema_payload_expande_dominios_f1() -> None:
    """``/schema`` entrega el schema COMPLETO: secciones F1 con ``properties`` (no opacas).

    Con el extra ``scoring`` instalado (job del CI), el motor de formulario del front recibe los
    campos reales de cada sección de dominio F1, no el schema opaco. La materialización vive en el
    core (``build_full_json_schema``); ``nikodym.ui`` sigue domain-agnostic (ver test AST abajo).
    """
    payload = routes.schema_payload()
    props = payload["json_schema"]["properties"]
    assert "properties" in props["binning"], "binning llegó opaca al front"
    for seccion in ("data", "selection", "model", "scorecard", "calibration", "performance"):
        assert "properties" in props[seccion], f"{seccion} llegó opaca"
    assert len(payload["json_schema"]["$defs"]) > 2  # opaco traía 2 (ReproConfig/RunConfig)


def test_validate_config_valido_devuelve_hash() -> None:
    """Un config válido reconstruye el modelo y devuelve su ``config_hash``."""
    cfg = NikodymConfig(repro=ReproConfig(seed=7))
    resultado = routes.validate_config(cfg.model_dump(mode="json", by_alias=True))
    assert resultado == {"valid": True, "config_hash": config_hash(cfg), "errors": []}


def test_validate_config_invalido_estructura_errores() -> None:
    """Un rango violado da ``valid=False`` con errores estructurados (loc/msg/type)."""
    resultado = routes.validate_config({"repro": {"seed": -1}})
    assert resultado["valid"] is False
    assert resultado["config_hash"] is None
    assert resultado["errors"], "debe listar al menos un error"
    error = resultado["errors"][0]
    assert set(error) == {"loc", "msg", "type"}
    assert error["loc"] == ["repro", "seed"]


def test_validate_config_campo_desconocido() -> None:
    """``extra='forbid'``: un campo desconocido es inválido (no se descarta en silencio)."""
    resultado = routes.validate_config({"campo_que_no_existe": 1})
    assert resultado["valid"] is False
    assert any(err["type"] == "extra_forbidden" for err in resultado["errors"])


def test_datasets_payload_es_el_catalogo() -> None:
    """``/datasets`` delega en ``list_datasets`` sin transformar."""
    assert routes.datasets_payload() == datasets_module.list_datasets()


# ─────────────────────────────── round-trip YAML (config_to_yaml / config_from_yaml) ─────────


def test_config_to_yaml_round_trip_preserva_hash() -> None:
    """``to-yaml`` de un config F1 vuelve a cargar con el MISMO ``config_hash`` (round-trip)."""
    cfg = full_f1_config("cartera.parquet")
    resultado = routes.config_to_yaml(cfg.model_dump(mode="json", by_alias=True))
    assert set(resultado) == {"yaml"}
    recargado = loads_config(resultado["yaml"])
    assert config_hash(recargado) == config_hash(cfg)


def test_config_to_yaml_config_invalido_propaga_validation_error() -> None:
    """Un config inválido propaga ``ValidationError`` (el endpoint lo traduce a 422)."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        routes.config_to_yaml({"repro": {"seed": -1}})


def test_config_from_yaml_valido_devuelve_config_y_hash() -> None:
    """``from-yaml`` de un YAML F1 válido reconstruye el ``config`` y su ``config_hash``."""
    cfg = full_f1_config("cartera.parquet")
    resultado = routes.config_from_yaml(dump_config(cfg))
    assert set(resultado) == {"config", "config_hash"}
    assert resultado["config"] == cfg.model_dump(mode="json", by_alias=True)
    assert resultado["config_hash"] == config_hash(cfg)


def test_config_from_yaml_malformado_levanta_config_error() -> None:
    """Un YAML sintácticamente roto propaga ``ConfigError`` (el endpoint lo traduce a 422)."""
    with pytest.raises(ConfigError):
        routes.config_from_yaml("clave: : : roto\n")


def test_config_from_yaml_schema_no_mapeado_levanta_config_error() -> None:
    """Un campo desconocido (``extra='forbid'``) propaga ``ConfigError`` desde ``loads_config``."""
    with pytest.raises(ConfigError):
        routes.config_from_yaml("campo_que_no_existe: 1\n")


def test_config_from_yaml_entrada_no_str_levanta_config_error() -> None:
    """Una entrada que no es ``str`` (p. ej. el ``yaml`` ausente → ``None``) da ``ConfigError``."""
    with pytest.raises(ConfigError):
        routes.config_from_yaml(None)


@pytest.fixture
def _registro_limpio() -> Iterator[None]:
    """Aísla el registro global de migradores: lo vacía y lo restaura tras el test (SDD-05 §5.4)."""
    original = dict(_MIGRATORS)
    _MIGRATORS.clear()
    try:
        yield
    finally:
        _MIGRATORS.clear()
        _MIGRATORS.update(original)


def test_config_from_yaml_migra_version_anterior(_registro_limpio: None) -> None:
    """``from-yaml`` aplica la migración de SDD-05: un ``schema_version`` viejo sube al actual."""

    @migration("0.9.0", "1.0.0")
    def _subir(raw: dict[str, Any]) -> dict[str, Any]:
        return {**raw, "schema_version": "1.0.0"}

    resultado = routes.config_from_yaml('schema_version: "0.9.0"\nname: migrado\n')
    assert resultado["config"]["schema_version"] == "1.0.0"
    assert resultado["config"]["name"] == "migrado"


# ─────────────────────────────── contrato AST de la frontera ───────────────────────────────

_UI_DIR = Path(routes.__file__).resolve().parent
_DOMINIOS_PROHIBIDOS = frozenset(
    {
        "nikodym.binning",
        "nikodym.selection",
        "nikodym.model",
        "nikodym.calibration",
        "nikodym.scorecard",
        "nikodym.performance",
        "nikodym.stability",
        "nikodym.validation",
        "nikodym.provisioning",
        "nikodym.survival",
        "nikodym.markov",
        "nikodym.forward",
        "nikodym.stress",
        "nikodym.explain",
        "nikodym.tuning",
        "nikodym.ml",
        "nikodym.eda",
        "nikodym.data",
    }
)


def _modulos_ui() -> list[Path]:
    """Devuelve los ``.py`` del paquete ``nikodym.ui``."""
    return sorted(_UI_DIR.glob("*.py"))


def _nombres_importados(arbol: ast.AST) -> set[str]:
    """Extrae los nombres de módulo importados (``import x`` / ``from x import y``)."""
    nombres: set[str] = set()
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Import):
            nombres.update(alias.name for alias in nodo.names)
        elif isinstance(nodo, ast.ImportFrom) and nodo.module is not None and nodo.level == 0:
            nombres.add(nodo.module)
    return nombres


def test_ui_no_usa_eval_ni_exec() -> None:
    """Ningún módulo de ``nikodym.ui`` llama ``eval``/``exec`` (seguridad, §11)."""
    for ruta in _modulos_ui():
        arbol = ast.parse(ruta.read_text(encoding="utf-8"))
        for nodo in ast.walk(arbol):
            if isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Name):
                assert nodo.func.id not in {"eval", "exec"}, f"{ruta.name} usa {nodo.func.id}"


def test_ui_no_importa_modulos_de_dominio() -> None:
    """El backend es *domain-agnostic*: no importa binning/model/calibration/data/…"""
    for ruta in _modulos_ui():
        importados = _nombres_importados(ast.parse(ruta.read_text(encoding="utf-8")))
        for nombre in importados:
            for prohibido in _DOMINIOS_PROHIBIDOS:
                assert not (nombre == prohibido or nombre.startswith(prohibido + ".")), (
                    f"{ruta.name} importa el dominio prohibido {nombre}"
                )


def test_ui_no_reimplementa_formulas_de_dominio() -> None:
    """No aparecen fórmulas de riesgo reimplementadas (roc_auc/WoE) en la capa ui."""
    fuente = "\n".join(ruta.read_text(encoding="utf-8") for ruta in _modulos_ui())
    assert not re.search(r"\broc_auc\b", fuente, re.IGNORECASE)
    assert not re.search(r"\bwoe\b", fuente, re.IGNORECASE)


# ─────────────────────────────── cableado de dataset (_wire_dataset_source) ───────────────────────


def test_wire_dataset_source_cablea_load_source() -> None:
    """Cablea ``data.load.source`` sin mutar el dict original (copia defensiva)."""
    config = {"data": {"load": {"source": None}, "schema": {}}}
    wired = routes._wire_dataset_source(config, Path("/tmp/x.parquet"))
    assert wired["data"]["load"]["source"] == str(Path("/tmp/x.parquet"))
    assert config["data"]["load"]["source"] is None  # el original no se mutó


def test_wire_dataset_source_sin_data_no_falla() -> None:
    """Un config sin sección ``data`` se devuelve intacto (no se inventa estructura)."""
    assert routes._wire_dataset_source({"repro": {"seed": 7}}, Path("/tmp/x.parquet")) == {
        "repro": {"seed": 7}
    }


def test_wire_dataset_source_load_no_dict_se_ignora() -> None:
    """Si ``data.load`` no es un dict, no se cablea (no se corrompe el config)."""
    wired = routes._wire_dataset_source({"data": {"load": "opaco"}}, Path("/tmp/x.parquet"))
    assert wired == {"data": {"load": "opaco"}}


# ─────────────────────────── cableado de report (_wire_report_output_dir) ──────────────────────


def test_wire_report_output_dir_cablea_absoluto_bajo_workdir(tmp_path: Path) -> None:
    """Cablea ``report.output_dir`` a ``workdir/reports`` sin mutar el dict original (copia)."""
    config = {"report": {"output_dir": "reports"}}
    wired = routes._wire_report_output_dir(config, workdir=tmp_path)
    assert wired["report"]["output_dir"] == str(tmp_path / "reports")
    assert config["report"]["output_dir"] == "reports"  # el original no se mutó


def test_wire_report_output_dir_sin_report_es_idempotente(tmp_path: Path) -> None:
    """Un config sin ``report`` (o con ``report=None``) se devuelve intacto (guarda idempotente)."""
    assert routes._wire_report_output_dir({"repro": {"seed": 7}}, workdir=tmp_path) == {
        "repro": {"seed": 7}
    }
    assert routes._wire_report_output_dir({"report": None}, workdir=tmp_path) == {"report": None}


# ─────────────────────────── run_pipeline (lógica pura, sin FastAPI) ───────────────────────────


def _fake_materialize(tmp_path: Path) -> object:
    """Devuelve un ``materialize`` que escribe el frame de 30 filas (predecible por fake bin)."""

    def materialize(dataset_id: str, *, workdir: Path) -> Path:
        path = Path(workdir) / "datasets" / f"{dataset_id}.parquet"
        path.parent.mkdir(parents=True, exist_ok=True)
        write_behavior_parquet(path)
        return path

    del tmp_path
    return materialize


def test_run_pipeline_ok_persiste_y_devuelve_done(
    fake_binning_process: object, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Una corrida válida devuelve ``{run_id, status:"done"}`` y persiste ``results.json``."""
    del fake_binning_process
    monkeypatch.setattr(datasets_module, "materialize", _fake_materialize(tmp_path))
    config = full_f1_config("placeholder.parquet").model_dump(mode="json", by_alias=True)

    result = routes.run_pipeline(config, "consumo_comportamiento", workdir=tmp_path)

    assert result["status"] == "done"
    assert (tmp_path / "runs" / result["run_id"] / "results.json").is_file()


def test_run_pipeline_preset_genera_reporte_html_determinista(tmp_path: Path) -> None:
    """La corrida del **preset F1** termina ``done`` y ``load_report`` devuelve el HTML del reporte.

    Ejercita el escaparate completo: ``run_pipeline`` corre el preset real (binning MIP, modelo,
    scorecard, calibración, performance, stability, report), persiste la corrida y sirve el HTML.
    Determinismo robusto: dos corridas (mismo ``workdir`` → mismo ``config_hash``) dan un HTML
    byte-idéntico salvo el ÚNICO campo wall-clock del lineage (``created_at``, el sello de la
    corrida); con ``ai.enabled=False`` el cuerpo del reporte no tiene otra fuente de azar. Requiere
    el extra ``scoring`` (binning MIP real): el job de dependencias mínimas lo salta.
    """
    pytest.importorskip("optbinning")
    from nikodym.ui import runs
    from nikodym.ui.presets import STANDARD_DATASET_ID, standard_preset

    def _run_and_load() -> tuple[str, str | None]:
        result = routes.run_pipeline(
            standard_preset()["config"], STANDARD_DATASET_ID, workdir=tmp_path
        )
        return result["status"], runs.load_report(result["run_id"], workdir=tmp_path)

    status_1, html_1 = _run_and_load()
    status_2, html_2 = _run_and_load()

    assert status_1 == status_2 == "done"
    for html in (html_1, html_2):
        assert html is not None and html.strip(), "load_report debe devolver HTML no vacío"
        assert "<html" in html.lower()
    run_stamp = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:\+00:00|Z)")
    assert run_stamp.sub("TS", html_1) == run_stamp.sub("TS", html_2)


def test_run_pipeline_preset_provisiones_estandar_muerde(tmp_path: Path) -> None:
    """El preset F3 corre la cadena entera y el método ESTÁNDAR es el que muerde (binding=cmf).

    Esta es la verificación que ningún test de ``status == done`` da: corre data→…→calibración→
    provisiones sobre la cartera real y comprueba el número de NEGOCIO. Si el preset heredara la
    calibración del F1 (``target_pd=0.20``), la PD se inflaría 3x, el método interno superaría al
    estándar y ``binding`` dejaría de ser ``cmf`` — el producto sin titular. Con
    ``development_observed`` el estándar (~697 M) supera al interno (~309 M) y la regla del máximo
    reporta el estándar. Requiere el extra ``scoring`` (binning MIP real); el job mínimo lo salta.
    """
    pytest.importorskip("optbinning")
    import nikodym
    from nikodym.core.config import NikodymConfig
    from nikodym.ui.presets import PROVISIONES_DATASET_ID, provisiones_preset

    # Se lee la card del ``Study`` (no ``results.json``): el serializer de las cards de provisiones
    # es el paso siguiente del track; aquí se verifica el motor, no su serialización.
    source = datasets_module.materialize(PROVISIONES_DATASET_ID, workdir=tmp_path)
    config = provisiones_preset()["config"]
    config["data"]["load"]["source"] = str(source)
    study = nikodym.run(NikodymConfig.model_validate(config))

    assert study.run_context.status == "done"
    orquestador = study.artifacts.get("provisioning", "card")
    estandar = float(orquestador.total_provision_a)
    interno = float(orquestador.total_provision_b)
    # El estándar debe morder: es la regresión que solo se ve corriendo (la trampa de calibración).
    assert estandar > interno, (
        f"el interno ({interno:.0f}) supera al estándar ({estandar:.0f}): calibración heredada mal"
    )
    assert orquestador.binding == "cmf"
    assert float(orquestador.total_reported_provision) == estandar


def test_run_pipeline_preset_provisiones_informe_trae_el_capitulo(tmp_path: Path) -> None:
    """G5: el informe del F3 trae el capítulo de provisiones con el sobrecosto, y ya no lo niega.

    Verifica el ARTEFACTO final (el HTML persistido), no el código: el capítulo condicional aparece
    con la provisión a constituir y el sobrecosto del estándar en CLP, y el informe **ya no dice**
    que las provisiones "corresponden a fases posteriores" (esa frase era verdadera hasta que el
    capítulo existió). Requiere el extra ``scoring`` (binning MIP real); el job mínimo lo salta.
    """
    pytest.importorskip("optbinning")
    from nikodym.ui import runs
    from nikodym.ui.presets import PROVISIONES_DATASET_ID, provisiones_preset

    result = routes.run_pipeline(
        provisiones_preset()["config"], PROVISIONES_DATASET_ID, workdir=tmp_path
    )
    assert result["status"] == "done"
    html = runs.load_report(result["run_id"], workdir=tmp_path)
    assert html is not None

    # (a) El capítulo existe con su titular en pesos: la provisión a constituir y el sobrecosto.
    assert "Provisiones regulatorias" in html
    assert "regla del máximo" in html.lower() or "mayor valor" in html.lower()
    assert "$697.376.974" in html  # provisión a constituir (estándar, que muerde)
    assert "$388.732.916" in html  # sobrecosto del estándar sobre el método interno
    # (b) El informe ya NO declara las provisiones como fase posterior (SDD-28 G5).
    assert "provisiones corresponden a fases posteriores" not in html.lower()
    assert "cálculo de provisiones" not in html.lower()


def test_run_pipeline_config_invalido_propaga_validation_error(tmp_path: Path) -> None:
    """Un config inválido propaga ``ValidationError`` (el endpoint lo traduce a 422)."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        routes.run_pipeline({"repro": {"seed": -1}}, "consumo_comportamiento", workdir=tmp_path)


def test_run_pipeline_dataset_desconocido_propaga_ui_dataset_error(tmp_path: Path) -> None:
    """Un ``dataset_id`` desconocido propaga ``UiDatasetError`` (el endpoint lo traduce a 404)."""
    config = full_f1_config("placeholder.parquet").model_dump(mode="json", by_alias=True)
    with pytest.raises(UiDatasetError):
        routes.run_pipeline(config, "dataset_inexistente", workdir=tmp_path)


def test_run_pipeline_corrida_fallida_status_failed(
    fake_binning_process: object, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Una corrida que falla a mitad devuelve ``status="failed"`` sin propagar (D-UI-2)."""
    del fake_binning_process
    monkeypatch.setattr(datasets_module, "materialize", _fake_materialize(tmp_path))
    config = failing_config("placeholder.parquet").model_dump(mode="json", by_alias=True)

    result = routes.run_pipeline(config, "consumo_comportamiento", workdir=tmp_path)

    assert result["status"] == "failed"


# ─────────────── upload de datasets propios (ingest_upload / upload_dataset) ───────────────

_CSV_UPLOAD = b"col_a,col_b\n1,x\n2,y\n3,z\n"  # 3 filas, 2 columnas
# El test de upload .xlsx necesita openpyxl para SERIALIZAR el archivo de prueba; el job all-extras
# lo trae y ahí corre, los mínimos lo saltan (patrón de _HAS_OPENPYXL en test_data_loading).
_HAS_OPENPYXL = importlib.util.find_spec("openpyxl") is not None


def _xlsx_bytes(frame: pd.DataFrame) -> bytes:
    """Serializa un DataFrame a bytes ``.xlsx`` (openpyxl) en memoria."""
    buffer = io.BytesIO()
    frame.to_excel(buffer, index=False, engine="openpyxl")
    return buffer.getvalue()


def _parquet_bytes(frame: pd.DataFrame) -> bytes:
    """Serializa un DataFrame a bytes ``.parquet`` en memoria."""
    buffer = io.BytesIO()
    frame.to_parquet(buffer)
    return buffer.getvalue()


def test_ingest_upload_csv_materializa_y_preview(tmp_path: Path) -> None:
    """Un CSV subido se lee, se materializa a ``uploaded_<hex>`` y da el preview de columnas."""
    result = datasets_module.ingest_upload(_CSV_UPLOAD, "cartera.csv", workdir=tmp_path)
    assert result["dataset_id"].startswith("uploaded_")
    assert len(result["dataset_id"]) == len("uploaded_") + 32
    assert result["name"] == "cartera.csv"
    assert result["n_rows"] == 3
    assert [col["name"] for col in result["columns"]] == ["col_a", "col_b"]
    parquet = tmp_path / "datasets" / f"{result['dataset_id']}.parquet"
    assert parquet.is_file()


@pytest.mark.skipif(not _HAS_OPENPYXL, reason="extra [excel] no instalado")
def test_ingest_upload_xlsx(tmp_path: Path) -> None:
    """Un ``.xlsx`` subido se lee con openpyxl y se materializa igual que un CSV."""
    frame = pd.DataFrame({"ingreso": [1000.0, 2000.0], "flag": [0, 1]})
    result = datasets_module.ingest_upload(_xlsx_bytes(frame), "cartera.xlsx", workdir=tmp_path)
    assert result["n_rows"] == 2
    assert [col["name"] for col in result["columns"]] == ["ingreso", "flag"]
    parquet = datasets_module.materialize(result["dataset_id"], workdir=tmp_path)
    assert pd.read_parquet(parquet)["flag"].tolist() == [0, 1]


def test_ingest_upload_parquet_round_trip(tmp_path: Path) -> None:
    """Un ``.parquet`` subido se materializa y ``materialize`` lo devuelve idéntico (round-trip)."""
    frame = pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]})
    result = datasets_module.ingest_upload(_parquet_bytes(frame), "d.parquet", workdir=tmp_path)
    parquet = datasets_module.materialize(result["dataset_id"], workdir=tmp_path)
    pd.testing.assert_frame_equal(pd.read_parquet(parquet), frame)


def test_ingest_upload_determinista_y_cachea(tmp_path: Path) -> None:
    """El mismo contenido da el MISMO ``dataset_id`` (sha256) y reusa su parquet cacheado."""
    primero = datasets_module.ingest_upload(_CSV_UPLOAD, "a.csv", workdir=tmp_path)
    segundo = datasets_module.ingest_upload(_CSV_UPLOAD, "b.csv", workdir=tmp_path)  # cache hit
    assert primero["dataset_id"] == segundo["dataset_id"]  # id por contenido, no por filename


def test_ingest_upload_vacio(tmp_path: Path) -> None:
    """Un archivo sin bytes levanta ``UiDatasetError`` (no se materializa)."""
    with pytest.raises(UiDatasetError, match="vacío"):
        datasets_module.ingest_upload(b"", "x.csv", workdir=tmp_path)


def test_ingest_upload_excede_limite(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Un archivo por encima de ``_MAX_UPLOAD_BYTES`` levanta ``UiDatasetError`` con el tamaño."""
    monkeypatch.setattr(datasets_module, "_MAX_UPLOAD_BYTES", 4)
    with pytest.raises(UiDatasetError, match="límite"):
        datasets_module.ingest_upload(b"12345", "x.csv", workdir=tmp_path)


def test_ingest_upload_formato_no_admitido(tmp_path: Path) -> None:
    """Una extensión fuera de la allowlist (``.txt``) levanta ``UiDatasetError``."""
    with pytest.raises(UiDatasetError, match="no admitido"):
        datasets_module.ingest_upload(b"hola mundo", "notas.txt", workdir=tmp_path)


def test_ingest_upload_archivo_corrupto(tmp_path: Path) -> None:
    """Bytes basura con sufijo ``.parquet`` que no parsean se envuelven en ``UiDatasetError``."""
    with pytest.raises(UiDatasetError, match="no se pudo leer"):
        datasets_module.ingest_upload(b"esto no es un parquet", "roto.parquet", workdir=tmp_path)


def test_ingest_upload_sin_filas(tmp_path: Path) -> None:
    """Un CSV con solo cabecera (0 filas) levanta ``UiDatasetError`` (no hay datos)."""
    with pytest.raises(UiDatasetError, match="no contiene filas"):
        datasets_module.ingest_upload(b"col_a,col_b\n", "solo_header.csv", workdir=tmp_path)


def test_materialize_upload_no_encontrado(tmp_path: Path) -> None:
    """``materialize`` de un ``uploaded_<id>`` sin parquet materializado da ``UiDatasetError``."""
    with pytest.raises(UiDatasetError, match="no encontrado"):
        datasets_module.materialize("uploaded_" + "0" * 32, workdir=tmp_path)


def test_upload_dataset_delega_en_ingest(tmp_path: Path) -> None:
    """``upload_dataset`` (pura) delega en ``ingest_upload`` con un ``filename`` válido."""
    result = routes.upload_dataset(b"a,b\n1,2\n", "x.csv", workdir=tmp_path)
    assert result["dataset_id"].startswith("uploaded_")
    assert result["n_rows"] == 1


def test_upload_dataset_filename_no_str(tmp_path: Path) -> None:
    """``upload_dataset`` con un ``filename`` no-``str`` levanta ``UiDatasetError`` (→ 422)."""
    with pytest.raises(UiDatasetError, match="string"):
        routes.upload_dataset(b"a,b\n1,2\n", None, workdir=tmp_path)


def test_run_endpoint_dependencia_faltante_422(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``/run`` traduce ``MissingDependencyError`` a 422 con el mensaje del motor (§4.2/§8)."""
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx2")
    from fastapi.testclient import TestClient

    import nikodym
    from nikodym.core.exceptions import MissingDependencyError
    from nikodym.ui.server import create_app
    from nikodym.ui.settings import UiConfig

    def _materialize(dataset_id: str, *, workdir: Path) -> Path:
        return Path(workdir) / "datasets" / f"{dataset_id}.parquet"

    def _raise_missing(config: object) -> object:
        raise MissingDependencyError("instale nikodym[tracking] para publicar al inventario.")

    monkeypatch.setattr(datasets_module, "materialize", _materialize)
    monkeypatch.setattr(nikodym, "run", _raise_missing)

    client = TestClient(create_app(UiConfig(workdir=str(tmp_path))))
    config = full_f1_config("placeholder.parquet").model_dump(mode="json", by_alias=True)
    respuesta = client.post(
        "/api/run", json={"config": config, "dataset_id": "consumo_comportamiento"}
    )

    assert respuesta.status_code == 422
    assert "nikodym[tracking]" in respuesta.json()["detail"]
