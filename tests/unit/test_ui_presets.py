"""Tests del preset estándar F1 (SDD-23 §3.2, §5): validez, coherencia con el dataset y endpoint.

El preset es un config F1 COMPLETO y *domain-agnostic* (dict literal en :mod:`nikodym.ui.presets`);
aquí se verifica que (a) valida y su ``config_hash`` es estable, (b) toda columna que referencia
existe en el registro de datasets con el rol correcto —lo que da confianza de que la corrida real
correrá— y (c) el endpoint ``GET /api/config/preset`` lo sirve. El *smoke* end-to-end real (correr
el motor OR-Tools/mip y ver el scorecard) NO vive aquí: es lento y se hace fuera de la suite.
"""

from __future__ import annotations

from typing import Any

from nikodym.core.config import NikodymConfig, config_hash
from nikodym.ui import datasets as datasets_module
from nikodym.ui import routes
from nikodym.ui.presets import (
    F4_IFRS9_PRESET_ID,
    PROVISIONES_DATASET_ID,
    PROVISIONES_PRESET_ID,
    STANDARD_DATASET_ID,
    STANDARD_PRESET_ID,
    get_preset,
    list_presets,
    provisiones_preset,
    standard_preset,
)

# ``config_hash`` del preset estándar F1: identidad estable del literal (SDD-05 §5.5). Si cambia una
# sección de dominio del preset, regenerar el literal y actualizar este valor conscientemente.
# Actualizado en B32a al ACTIVAR la sección ``stability`` (antes ``None``): el preset cambió de
# verdad (estabilidad post-modelo entra al ``config_hash`` global) → hash legítimamente nuevo.
# Actualizado en SDD-28 al DECLARAR la sección computacional ``provisioning_internal`` en el schema.
# El preset F1 NO la activa (queda en ``None``), pero `model_dump` emite igual la clave, así que el
# JSON canónico gana `"provisioning_internal":null` y el hash se mueve. VERIFICADO que ese es el
# único motivo: el mismo payload sin esa clave reproduce, byte a byte, el golden anterior
# (f53ffc9f11eaac299a42c857fd7704401361603d91fba584ce439382bb1f59a9).
_EXPECTED_CONFIG_HASH = "decdb9017f555bd664469750a9f5f15f5440f08268f5af23eabcb3f5817d113b"


# ─────────────────────────────── validez y hash estable ───────────────────────────────


def test_standard_preset_shape() -> None:
    """``standard_preset`` entrega ``{id, name, description, config, dataset_id}``."""
    preset = standard_preset()
    assert set(preset) == {"id", "name", "description", "config", "dataset_id"}
    assert preset["dataset_id"] == STANDARD_DATASET_ID
    assert isinstance(preset["config"], dict)


def test_standard_preset_config_valida_y_hash_estable() -> None:
    """El config del preset reconstruye ``NikodymConfig`` y su ``config_hash`` es determinista."""
    config = standard_preset()["config"]
    model = NikodymConfig.model_validate(config)  # no debe levantar
    assert config_hash(model) == _EXPECTED_CONFIG_HASH
    # Determinismo: revalidar una copia independiente da exactamente el mismo hash.
    assert config_hash(NikodymConfig.model_validate(standard_preset()["config"])) == config_hash(
        model
    )


def test_preset_pide_los_cuatro_entregables_sin_alterar_hash() -> None:
    """El preset pide los CUATRO entregables, y ``report`` sigue siendo INFRA (no toca el hash).

    Antes pedía sólo HTML "por seguridad" (no requerir extras). El efecto real era el contrario: la
    UI no expone una sección "Reporte" donde activar los demás formatos, así que los botones de
    descarga de PDF, Word y base editable respondían 404 SIEMPRE en uso real. La función existía y
    era inalcanzable. El preset existe justamente para que todo salga sin tocar nada.

    PDF y DOCX van tras extras opcionales con ``fail_if_unavailable=False``: en una instalación
    mínima no se emiten (y la descarga da un 404 con mensaje claro) en vez de tumbar la corrida.
    """
    config = standard_preset()["config"]
    report = config["report"]
    assert isinstance(report, dict)
    assert report["formats"] == ["html", "pdf", "md", "docx"]
    assert report["pdf"]["enabled"] is True
    # Sin extra instalado NO se aborta la corrida: el HTML, que es el entregable base, sale igual.
    assert report["pdf"]["fail_if_unavailable"] is False
    assert report["docx"]["fail_if_unavailable"] is False
    # La narración por IA sigue apagada: la prosa del informe es determinista (no usa la red).
    assert report["ai"]["enabled"] is False
    assert report["html"]["include_interactive_charts"] is False
    assert report["sections"]["required_sections"] == [
        "binning",
        "selection",
        "model",
        "scorecard",
        "calibration",
        "performance",
        "stability",
    ]
    assert "eda" not in report["sections"]["required_sections"]
    # report es INFRA → excluido del config_hash: la identidad del preset NO cambia por activarlo.
    assert config_hash(NikodymConfig.model_validate(config)) == _EXPECTED_CONFIG_HASH


def test_standard_preset_devuelve_copia_defensiva() -> None:
    """Cada llamada devuelve un config nuevo: mutarlo no contamina el literal compartido."""
    primero = standard_preset()["config"]
    primero["binning"]["time_limit"] = 999
    segundo = standard_preset()["config"]
    assert segundo["binning"]["time_limit"] != 999


# ─────────────────────────── coherencia con el dataset sintético ───────────────────────────


def test_preset_coherente_con_columnas_del_dataset() -> None:
    """Toda columna cruda referenciada por el preset existe en el dataset con el rol correcto.

    Es la garantía barata (sin correr el motor) de que la corrida real materializará y binneará:
    id/target/segment/cohort y las features candidatas mapean a columnas reales de
    ``datasets._COLUMNS`` con su rol. Las columnas *derivadas* (target derivado, score, partition,
    pd_calibrated) NO se chequean: las produce el pipeline aguas abajo, no el dataset.
    """
    preset = standard_preset()
    config = preset["config"]
    role_by_name = {column["name"]: column["role"] for column in datasets_module._COLUMNS}
    data = config["data"]

    # Índice = columna de rol 'id'.
    assert role_by_name.get(data["schema"]["index_col"]) == "id"
    # Toda columna declarada en el esquema existe en el dataset.
    for column in data["schema"]["columns"]:
        assert column["name"] in role_by_name, column["name"]
    # El target se define por una regla sobre una columna de rol 'target'.
    for predicate in data["target"]["bad_rule"]["all_of"]:
        assert role_by_name.get(predicate["col"]) == "target"
    # Partición por cohorte: la columna es de rol 'cohort'.
    strategy = data["partition"]["strategy"]
    assert role_by_name.get(strategy["cohort_col"]) == "cohort"

    binning = config["binning"]
    # Toda feature candidata del binning existe en el dataset.
    for name in binning["feature_columns"]:
        assert name in role_by_name, name
    # La columna categórica del binning es el segmento (rol 'segment').
    for name in binning["categorical_columns"]:
        assert role_by_name.get(name) == "segment"
    # Las features restantes (no categóricas) son columnas numéricas de rol 'feature'.
    numericas = [n for n in binning["feature_columns"] if n not in binning["categorical_columns"]]
    assert numericas, "el preset debe declarar al menos una feature numérica"
    for name in numericas:
        assert role_by_name.get(name) == "feature"


def test_preset_oot_cohorts_existen_en_el_dataset() -> None:
    """Las cohortes reservadas como OOT existen en el dataset recomendado (partición no vacía)."""
    preset = standard_preset()
    spec = datasets_module._DATASETS[preset["dataset_id"]]
    for cohort in preset["config"]["data"]["partition"]["strategy"]["oot_cohorts"]:
        assert cohort in spec["cohorts"], cohort


# ─────────────────────────────── preset_payload (lógica pura) ───────────────────────────────


def test_preset_payload_shape_y_hash() -> None:
    """``preset_payload`` entrega las claves del contrato (incl. ``id``) con el hash del config."""
    payload = routes.preset_payload()
    assert set(payload) == {"id", "config", "config_hash", "dataset_id", "name", "description"}
    assert payload["id"] == STANDARD_PRESET_ID
    assert payload["dataset_id"] == STANDARD_DATASET_ID
    model = NikodymConfig.model_validate(payload["config"])
    assert payload["config_hash"] == config_hash(model) == _EXPECTED_CONFIG_HASH


# ─────────────────────────────── endpoint (TestClient) ───────────────────────────────


def test_endpoint_config_preset() -> None:
    """``GET /api/config/preset`` → 200 con ``{config, config_hash}`` y el config valida."""
    import pytest

    pytest.importorskip("fastapi")
    pytest.importorskip("httpx2")
    from fastapi.testclient import TestClient

    from nikodym.ui.server import create_app
    from nikodym.ui.settings import UiConfig

    client = TestClient(create_app(UiConfig()))
    respuesta = client.get("/api/config/preset")
    assert respuesta.status_code == 200
    cuerpo: dict[str, Any] = respuesta.json()
    assert cuerpo["config_hash"] == _EXPECTED_CONFIG_HASH
    assert config_hash(NikodymConfig.model_validate(cuerpo["config"])) == _EXPECTED_CONFIG_HASH


# ═══════════════════════════════ Preset F3 — provisiones ═══════════════════════════════

# ``config_hash`` del preset F3 (SDD-28). Distinto del F1 porque activa las tres secciones de
# provisiones (computacionales, entran al hash) y cambia la calibración a ``development_observed``.
# Si cambia un default de dominio, regenerar con ``scripts/derive_provisiones_preset``
# y actualizar este valor conscientemente. Estable con/sin la capa de dominio importada (el config
# deja ``target_pd: None`` explícito = su forma canónica; ver la nota en ``ui/presets.py``).
_EXPECTED_F3_CONFIG_HASH = "21bf265d8e08e8ec8e76781f32a7652fa8ff17c807f000810af73546b916e5f3"


def test_provisiones_preset_shape() -> None:
    """``provisiones_preset`` entrega ``{id, name, description, config, dataset_id}``."""
    preset = provisiones_preset()
    assert set(preset) == {"id", "name", "description", "config", "dataset_id"}
    assert preset["id"] == PROVISIONES_PRESET_ID
    assert preset["dataset_id"] == PROVISIONES_DATASET_ID
    assert isinstance(preset["config"], dict)


def test_provisiones_preset_config_valida_y_hash_estable() -> None:
    """El config del F3 reconstruye ``NikodymConfig`` y su ``config_hash`` es determinista."""
    config = provisiones_preset()["config"]
    model = NikodymConfig.model_validate(config)  # no debe levantar
    assert config_hash(model) == _EXPECTED_F3_CONFIG_HASH
    assert config_hash(NikodymConfig.model_validate(provisiones_preset()["config"])) == config_hash(
        model
    )


def test_provisiones_preset_no_hereda_la_calibracion_del_f1() -> None:
    """🔴 La trampa del track: si el F3 hereda ``target_pd=0.20`` del F1, el resultado se invierte.

    Sobre esta cartera (default ~7 %) anclar la PD a 0,20 la infla 3x, el método interno supera al
    estándar y la regla del máximo deja de morder: el producto se queda sin titular. El preset debe
    usar ``development_observed`` (que estima la PD como el promedio observado en Desarrollo) y NO
    debe traer ``target_pd``. Este test es la guardia estática; el test end-to-end en
    ``test_ui_routes`` confirma corriendo que el estándar es el que muerde.
    """
    calibration = provisiones_preset()["config"]["calibration"]
    assert calibration["anchor_source"] == "development_observed"
    # target_pd NULO: development_observed estima la PD. Un valor (0.20 del F1) sería la trampa.
    assert calibration["target_pd"] is None


def test_provisiones_preset_activa_las_tres_secciones_y_la_regla_real() -> None:
    """El F3 activa CMF + interno + orquestador con la regla estándar-vs-interno (no ifrs9)."""
    config = provisiones_preset()["config"]
    assert config["provisioning_cmf"] is not None
    assert config["provisioning_internal"] is not None
    # La comparación que exige la norma chilena es estándar (CMF) vs interno, a nivel de entidad.
    orquestador = config["provisioning"]
    assert orquestador["source_a"] == "provisioning_cmf"
    assert orquestador["source_b"] == "provisioning_internal"
    assert orquestador["rule"] == "max"
    assert orquestador["comparison_level"] == "total"
    # IFRS 9 queda fuera del camino crítico chileno (cambia de destinatario, no se compara aquí).
    assert config["provisioning_ifrs9"] is None


# Golden del F4 (mismo contrato que F1/F3): si cambia un default de dominio survival/ifrs9,
# regenerar con ``scripts/derive_ifrs9_preset.py`` y actualizar este valor conscientemente.
# Las secciones salen de ``model_dump`` de los objetos Pydantic (todos los campos explícitos),
# así que el hash es estable con/sin la capa de dominio importada (verificado en ambas
# condiciones al pinnearlo). Protege la identidad del preset justo cuando los fixtures de
# demo.nikodym.cl se recapturan contra él.
_EXPECTED_F4_CONFIG_HASH = "8c94bd4d9a406669c7c3f611d939e09963fc26cdf151fe0723bd66c973e8e23f"


def test_ifrs9_preset_config_valida_y_hash_estable() -> None:
    """El config del F4 reconstruye ``NikodymConfig`` y su ``config_hash`` es determinista."""
    config = get_preset(F4_IFRS9_PRESET_ID)["config"]
    model = NikodymConfig.model_validate(config)  # no debe levantar
    assert config_hash(model) == _EXPECTED_F4_CONFIG_HASH
    assert config_hash(
        NikodymConfig.model_validate(get_preset(F4_IFRS9_PRESET_ID)["config"])
    ) == config_hash(model)


def test_ifrs9_preset_activa_el_report_con_secciones_reducidas() -> None:
    """El F4 enciende el informe (capítulo «Provisiones IFRS 9 / ECL») sin exigir el scorecard.

    La cadena standalone ``data → survival → provisioning_ifrs9`` no corre NINGÚN dominio
    scorecard: si el report exigiera alguno (default F1, ``missing_policy='error'``), la corrida
    entera se caería. El config valida con ``required_sections`` VACÍAS; el capítulo IFRS 9 se
    activa por la presencia de la card y «Resultados» se omite solo (condicional any-of).
    """
    config = get_preset(F4_IFRS9_PRESET_ID)["config"]
    report = config["report"]
    assert isinstance(report, dict)
    assert report["formats"] == ["html", "pdf", "md", "docx"]
    assert report["basename"] == "ifrs9_ecl_report"
    assert report["sections"]["required_sections"] == []
    # Todo el pipeline scorecard queda apagado: el F4 es standalone (sin ``model.raw_pd_frame``).
    for seccion in (
        "binning",
        "selection",
        "model",
        "scorecard",
        "calibration",
        "performance",
        "stability",
    ):
        assert config[seccion] is None
    # El survival ajusta sin PD de F1, sobre covariables propias del dataset.
    survival = config["survival"]
    assert survival["input"]["pd_source"] == "none"
    assert survival["discrete_hazard"]["pd_role"] == "none"
    assert survival["input"]["covariate_cols"] == [
        "days_past_due",
        "utilizacion_linea",
        "deuda_ingreso",
        "antiguedad_meses",
    ]
    NikodymConfig.model_validate(config)


def test_provisiones_preset_devuelve_copia_defensiva() -> None:
    """Mutar el config devuelto no contamina los literales compartidos del módulo."""
    primero = provisiones_preset()["config"]
    primero["provisioning"]["rule"] = "use_internal"
    primero["calibration"]["anchor_source"] = "business_input"
    segundo = provisiones_preset()["config"]
    assert segundo["provisioning"]["rule"] == "max"
    assert segundo["calibration"]["anchor_source"] == "development_observed"


def test_provisiones_preset_columnas_regulatorias_existen_en_el_dataset() -> None:
    """Toda columna regulatoria que referencian las secciones existe en el dataset de provisiones.

    Garantía barata (sin correr el motor) de que la corrida real tendrá las columnas: exposición,
    mora, deudor, producto y LGD que piden las secciones CMF/interno viven en el catálogo del
    dataset ``provisiones_consumo`` (superconjunto de las columnas F1).
    """
    config = provisiones_preset()["config"]
    columnas = {col["name"] for col in datasets_module._columns_for(PROVISIONES_DATASET_ID)}
    cmf = config["provisioning_cmf"]
    for col in (
        cmf["as_of_date_col"],
        cmf["portfolio_col"],
        cmf["debtor_id_col"],
        cmf["days_past_due_col"],
        cmf["product_type_col"],
        cmf["exposure"]["direct_exposure_col"],
    ):
        assert col in columnas, col
    interno = config["provisioning_internal"]
    for col in (interno["portfolio_col"], interno["exposure_col"], interno["lgd"]["lgd_col"]):
        assert col in columnas, col


# ─────────────────────────── registro de presets (list / get) ───────────────────────────


def test_list_presets_cataloga_ambos_sin_config() -> None:
    """``list_presets`` devuelve los descriptores (sin ``config``) de F1, F3 y F4, en orden."""
    catalogo = list_presets()
    assert [p["id"] for p in catalogo] == [
        STANDARD_PRESET_ID,
        PROVISIONES_PRESET_ID,
        F4_IFRS9_PRESET_ID,
    ]
    for descriptor in catalogo:
        assert set(descriptor) == {"id", "name", "description", "dataset_id"}
        assert "config" not in descriptor


def test_get_preset_por_id_y_desconocido() -> None:
    """``get_preset`` resuelve por id y levanta ``KeyError`` para un id no registrado."""
    assert get_preset(PROVISIONES_PRESET_ID)["id"] == PROVISIONES_PRESET_ID
    assert get_preset(STANDARD_PRESET_ID)["id"] == STANDARD_PRESET_ID
    import pytest

    with pytest.raises(KeyError):
        get_preset("preset-inexistente")


# ─────────────────────────── endpoints del F3 (TestClient) ───────────────────────────


def test_endpoint_presets_index_y_preset_por_id() -> None:
    """``/config/presets`` cataloga; ``/config/preset/{id}`` sirve el F3; id desconocido → 404."""
    import pytest

    pytest.importorskip("fastapi")
    pytest.importorskip("httpx2")
    from fastapi.testclient import TestClient

    from nikodym.ui.server import create_app
    from nikodym.ui.settings import UiConfig

    client = TestClient(create_app(UiConfig()))

    indice = client.get("/api/config/presets")
    assert indice.status_code == 200
    assert [p["id"] for p in indice.json()["presets"]] == [
        STANDARD_PRESET_ID,
        PROVISIONES_PRESET_ID,
        F4_IFRS9_PRESET_ID,
    ]

    detalle = client.get(f"/api/config/preset/{PROVISIONES_PRESET_ID}")
    assert detalle.status_code == 200
    cuerpo: dict[str, Any] = detalle.json()
    assert cuerpo["id"] == PROVISIONES_PRESET_ID
    assert cuerpo["config_hash"] == _EXPECTED_F3_CONFIG_HASH
    assert config_hash(NikodymConfig.model_validate(cuerpo["config"])) == _EXPECTED_F3_CONFIG_HASH

    assert client.get("/api/config/preset/preset-inexistente").status_code == 404
