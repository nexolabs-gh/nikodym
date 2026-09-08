"""Gates de D-GOB-11/12/13/14: la gobernanza se ve en el formulario, latente, y `purpose` decide.

Continúa ``test_gobernanza_expandible.py`` (D-GOB-10) con lo que la enmienda GOBERNANZA-EN-PANTALLA
preespecifica en su §6 para la capa 11/12/13/14, con las tres respuestas de Cami del 2026-09-07:

- §6.4 · los 10 trabajos ofrecen ``governance`` y sigue apagada de fábrica —en los cuatro presets
  **y** en el esqueleto de cada trabajo, que la declara **latente** (§8.1-3)—;
- §6.5 / §6.10 · ``purpose`` en blanco se rechaza en el motor (``GovernanceConfig`` y
  ``NikodymConfig``) y en ``/api/validate``, con el ``loc`` del campo y el mensaje en español
  (§8.1-1); la tercera capa —la tarjeta de decisiones— vive en ``web/src/lib/jobs.test.ts``;
- §6.6 · ``scenario_log_filename`` no aparece en la superficie del formulario (D-GOB-14, D-SUB);
- §6.8 / D-GOB-13 · las 12 descripciones visibles son el copy aprobado, palabra por palabra, y
  ningún código interno llega al tooltip;
- §6.11 (motor) · con la sección encendida y ``purpose`` en blanco, ``/api/run`` no arranca porque
  su precondición es la misma validación; la mitad del esqueleto vive en
  ``test_jobs_ejecutables.py``.

Y la capa D-GOB-15/16 (S4, 2026-09-08), en la sección final de este archivo:

- D-GOB-16 · el tipo ``ModelCard`` del front espeja **en los dos sentidos y en orden** los campos
  del modelo Pydantic (y sus tres anidados), y es exactamente lo que ``serialize_study`` emite HOY
  sobre una corrida F1 real con audit y gobernanza; la pantalla —render real del panel con y sin
  card— vive en ``web/src/components/ResultsTab.test.ts``;
- §6.7 · el **bundle servido** pinta la ficha: cada rótulo de la sección aporta al menos una
  ocurrencia propia por encima de las que ya viajaban en los fixtures empaquetados, y el bundle
  nombra ``model_card`` (hasta S4, cero veces); los tres fixtures de la demo siguen con
  ``model_card: null`` y el guard los cubre sin recaptura.

Controles negativos ejecutados al implementar (protocolo del runbook §6): exponer
``scenario_log_filename`` pone rojo §6.6; quitar el validador de ``purpose`` pone rojo el motor,
``/api/validate`` y la tarjeta; sembrar ``governance`` encendida en el esqueleto pone rojo el gate
de ejecutabilidad de los nueve trabajos disponibles.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

import pytest
from _ui_f1 import full_f1_config, write_behavior_parquet
from pydantic import BaseModel, ValidationError

import nikodym
from nikodym.audit import AuditConfig, EnvironmentSnapshot
from nikodym.core.config import NikodymConfig
from nikodym.core.config.schema import build_full_json_schema, rama_objeto
from nikodym.data.card import DataCardSection
from nikodym.governance.config import GovernanceConfig
from nikodym.governance.model_card import DecisionRecord, ModelCard
from nikodym.ui import routes
from nikodym.ui._static_index import resolve_local_resources
from nikodym.ui.jobs import _SECCIONES_LATENTES, list_jobs
from nikodym.ui.presets import get_preset, list_presets
from nikodym.ui.serializers import serialize_study

_RAIZ = Path(__file__).resolve().parents[2]
_SCHEMA_TS = _RAIZ / "web" / "src" / "lib" / "schema.ts"

#: El copy aprobado por Cami el 2026-09-03 (tabla §3 de la enmienda, D-GOB-13), escrito A MANO y
#: no leído del modelo: es el oráculo. «Palabra por palabra»: la única diferencia con la tabla es
#: que el énfasis Markdown de «**no**» en `limitations` no viaja a un tooltip.
COPY_APROBADO: dict[str, str] = {
    "model_name": (
        "Nombre con el que este modelo queda registrado en tu inventario. Si lo publicas a "
        "MLflow, es la clave con la que lo encontrarás ahí."
    ),
    "purpose": (
        "Para qué se va a usar este modelo y sobre qué cartera decide. Lo escribe tu "
        "institución: el motor no puede inventarlo, y sin esto la ficha del modelo no se emite."
    ),
    "assumptions": (
        "Los supuestos con los que se construyó el modelo. Se copian tal cual a la ficha, para "
        "que quien la lea sepa bajo qué condiciones vale."
    ),
    "limitations": (
        "Dónde no deberías usar este modelo. Se copian tal cual a la ficha, y son lo primero que "
        "mira una validación independiente."
    ),
    "review_period_months": (
        "Cada cuántos meses toca revisar el modelo. La ficha calcula con esto la fecha de la "
        "próxima revisión, contada desde su emisión."
    ),
    "publish_to_inventory": (
        "Si además de dejar la evidencia en tu carpeta quieres publicar el modelo a un inventario "
        "MLflow. Pide instalar el extra «tracking»; si lo dejas en no, todo queda local."
    ),
    "require_overlay_justification": (
        "Exige escribir el motivo cada vez que alguien ajusta a mano un resultado del modelo. Un "
        "ajuste sin motivo detiene la corrida: es la defensa contra maquillar cifras."
    ),
    "cartera": (
        "El segmento de cartera de este modelo, con el nombre que uses en tu institución. Es "
        "descriptivo: no cambia ningún cálculo."
    ),
    "motor": (
        "Qué motor documenta esta ficha: scoring, provisiones CMF o IFRS 9. Sirve para no mezclar "
        "modelos distintos en el mismo inventario."
    ),
    "fase": (
        "En qué punto de su construcción está el modelo. Queda escrito en la ficha para que se "
        "lea en contexto."
    ),
    "estado_validacion": (
        "En qué punto va la revisión independiente del modelo. Es aparte de si está o no en "
        "producción."
    ),
    "author": (
        "Quién responde por este modelo: correo o identificación de la persona o el equipo."
    ),
}

#: Lo que salió del copy público con D-GOB-13 y no puede volver a un tooltip: los tags del
#: inventario, la referencia regulatoria, la jerga del ciclo de validación, las marcas internas y
#: los literales de Python. Anclado abajo contra el texto viejo real, para que el detector no
#: pueda estar midiendo la nada.
_CODIGOS_INTERNOS = re.compile(
    r"nikodym\.|SR 11-7|effective challenge|FALTA-DATO|DATO-INSTITUCIONAL|Registry|JSONL|"
    r"append-only|earnings-management|\b(None|True|False)\b"
)

_TEXTOS_VIEJOS = (
    "Identidad en el inventario (clave del MLflow Registry).",
    "Declaración de propósito (SR 11-7); obligatoria para el model card.",
    "True requiere el extra tracking; False genera solo evidencia local.",
    "True: un overlay sin justificación es error anti earnings-management.",
    "Ciclo de vida de effective challenge; tag nikodym.estado_validacion.",
)

_EN_BLANCO = ("", "   ", "\t\n")


def _rama_governance() -> dict[str, Any]:
    rama = rama_objeto(build_full_json_schema()["properties"]["governance"])
    assert rama is not None, "governance quedó opaca: D-GOB-10 se rompió"
    return rama


def _config_sections_del_front() -> list[tuple[str, str]]:
    """``(key, label)`` de `CONFIG_SECTIONS`, leídos del fuente TypeScript en su orden."""
    texto = _SCHEMA_TS.read_text(encoding="utf-8")
    _, _, resto = texto.partition("export const CONFIG_SECTIONS")
    cuerpo, _, _ = resto.partition("\n]")
    return re.findall(r'key:\s*"([a-z_0-9]+)",\s*label:\s*"([^"]+)"', cuerpo)


# ─────────────────────── §6.4: en los 10 trabajos, apagada de fábrica ───────────────────────


def test_governance_es_la_decimoquinta_seccion_del_formulario_y_se_llama_gobernanza() -> None:
    """D-GOB-11: `CONFIG_SECTIONS` pasa de 14 a 15, «Gobernanza», después del informe."""
    secciones = _config_sections_del_front()
    assert len(secciones) == 15, [k for k, _ in secciones]
    assert secciones[-2][0] == "report", "el informe sigue siendo el último paso del pipeline"
    assert secciones[-1] == ("governance", "Gobernanza")


def test_los_diez_trabajos_ofrecen_governance_y_la_declaran_latente() -> None:
    """Como `report`: en los diez; y a diferencia de `report`, sembrada apagada (§8.1-3)."""
    trabajos = list_jobs()
    assert len(trabajos) == 10
    for job in trabajos:
        assert job["sections"][-1] == "governance", (job["id"], job["sections"])
        assert job["latent_sections"] == ["governance"], (job["id"], job["latent_sections"])
    # La latencia se declara UNA vez, por sección, con su razón; hoy sólo `governance` lo es.
    assert set(_SECCIONES_LATENTES) == {"governance"}
    assert len(_SECCIONES_LATENTES["governance"]) > 40


def test_el_endpoint_publica_latent_sections() -> None:
    """El front y el gate de ejecutabilidad consumen la misma clave del contrato REST."""
    for job in routes.jobs_payload()["jobs"]:
        assert job["latent_sections"] == ["governance"], job["id"]
        assert set(job["latent_sections"]) <= set(job["sections"])


def test_sigue_apagada_en_los_cuatro_presets() -> None:
    """D-GOB-8 no se reabre: ningún preset inventa un propósito."""
    ids = [p["id"] for p in list_presets()]
    assert len(ids) == 4, ids
    for preset_id in ids:
        assert get_preset(preset_id)["config"]["governance"] is None, preset_id


# ─────────────────────────── §6.5 / §6.10: `purpose` en blanco no construye ───────────────────────


@pytest.mark.parametrize("en_blanco", _EN_BLANCO, ids=["vacio", "espacios", "tab_y_salto"])
def test_governance_config_rechaza_purpose_en_blanco(en_blanco: str) -> None:
    """Capa 1 (motor, D-GOB-12 · §8.1-1): la ficha no se firma sin propósito."""
    with pytest.raises(ValidationError) as capturado:
        GovernanceConfig(purpose=en_blanco)
    errores = capturado.value.errors()
    assert [tuple(e["loc"]) for e in errores] == [("purpose",)]
    assert "en blanco" in errores[0]["msg"]


@pytest.mark.parametrize("en_blanco", _EN_BLANCO, ids=["vacio", "espacios", "tab_y_salto"])
def test_nikodym_config_rechaza_purpose_en_blanco_con_el_loc_del_campo(en_blanco: str) -> None:
    """El mismo veredicto desde la raíz del config, que es lo que `/api/run` valida primero."""
    with pytest.raises(ValidationError) as capturado:
        NikodymConfig.model_validate({"governance": {"purpose": en_blanco}})
    assert [tuple(e["loc"]) for e in capturado.value.errors()] == [("governance", "purpose")]


def test_purpose_se_normaliza_con_strip_y_un_caracter_basta() -> None:
    """La validación normaliza —no sólo rechaza—: el propósito viaja sin espacios alrededor."""
    assert GovernanceConfig(purpose="  Decidir la originación de consumo  ").purpose == (
        "Decidir la originación de consumo"
    )
    assert GovernanceConfig(purpose="x").purpose == "x"


@pytest.mark.parametrize("en_blanco", _EN_BLANCO, ids=["vacio", "espacios", "tab_y_salto"])
def test_api_validate_rechaza_purpose_en_blanco_con_loc_y_mensaje_en_espanol(
    en_blanco: str,
) -> None:
    """Capa 2 (interfaz): `valid=false`, el `loc` del campo y el mensaje tal como lo pinta el front.

    El `loc` es lo que la tarjeta de decisiones y el control del campo usan para casar el error;
    el mensaje se lee junto al campo, así que no puede llevar el prefijo inglés de Pydantic.
    """
    resultado = routes.validate_config({"governance": {"purpose": en_blanco}})
    assert resultado["valid"] is False
    assert resultado["config_hash"] is None
    errores = [e for e in resultado["errors"] if e["loc"] == ["governance", "purpose"]]
    assert len(errores) == 1, resultado["errors"]
    assert errores[0]["msg"].startswith("El propósito no puede quedar en blanco"), errores[0]
    assert not errores[0]["msg"].startswith("Value error"), errores[0]


def test_api_validate_acepta_un_purpose_real_y_governance_no_mueve_el_hash() -> None:
    """Control positivo del gate anterior, y D-GOB-10 §6.3 desde la ruta de la interfaz."""
    sin = routes.validate_config({})
    con = routes.validate_config({"governance": {"purpose": "Originación de consumo"}})
    assert con["valid"] is True, con["errors"]
    assert con["config_hash"] == sin["config_hash"], "governance es INFRA: no entra al hash"


def test_api_run_no_arranca_con_purpose_en_blanco(tmp_path: Path) -> None:
    """§6.11 (motor): la precondición de `/api/run` es la misma validación, así que no arranca.

    Se levanta `ValidationError` —el endpoint lo convierte en 422— antes de tocar el dataset: por
    eso un `dataset_id` inexistente no llega a producir su propio error.
    """
    with pytest.raises(ValidationError) as capturado:
        routes.run_pipeline(
            {"governance": {"purpose": "   "}}, "dataset-que-no-existe", workdir=tmp_path
        )
    assert [tuple(e["loc"]) for e in capturado.value.errors()] == [("governance", "purpose")]
    assert not any(tmp_path.iterdir()), "no arrancó nada: el workdir sigue vacío"


# ─────────────────────────── §6.6: `scenario_log_filename` no se expone (D-GOB-14) ────────────────


def test_scenario_log_filename_esta_oculto_en_el_schema_y_ausente_del_formulario() -> None:
    """D-SUB: el nombre de un archivo que D-GOB-6 decidió no escribir no se ofrece.

    Control negativo ejecutado: cambiar su `ui_widget` a `text_input` pone rojo este gate.
    """
    from test_copy_del_formulario import _campos_visibles

    rama = _rama_governance()
    assert rama["properties"]["scenario_log_filename"].get("ui_widget") == "hidden"
    # El campo sigue en el config para quien lo use por código: no se borra, se oculta.
    assert "scenario_log_filename" in GovernanceConfig.model_fields

    visibles = {ruta for ruta, _ in _campos_visibles()}
    assert "governance.scenario_log_filename" not in visibles
    # Control positivo del barrido: la sección SÍ se recorre, con sus 12 visibles.
    assert "governance.purpose" in visibles
    assert len({r for r in visibles if r.startswith("governance.")}) == 14  # 12 campos + 2 `[]`


# ─────────────────────────── §6.8 / D-GOB-13: copy público exacto y sin códigos internos ─────────


def test_las_doce_descripciones_visibles_son_el_copy_aprobado_palabra_por_palabra() -> None:
    """La tabla §3 de la enmienda, aprobada el 2026-09-03, contra `model_fields`."""
    campos = GovernanceConfig.model_fields
    assert set(COPY_APROBADO) == set(campos) - {"scenario_log_filename"}
    for nombre, esperado in COPY_APROBADO.items():
        assert campos[nombre].description == esperado, nombre


def test_los_trece_campos_declaran_widget_y_grupo() -> None:
    """Los 8 que no lo tenían lo ganan; `purpose` es un textarea (D-GOB-12)."""
    for nombre, campo in GovernanceConfig.model_fields.items():
        extra = campo.json_schema_extra
        assert isinstance(extra, dict), nombre
        assert extra.get("ui_widget") and extra.get("ui_group"), (nombre, extra)
        assert isinstance(extra.get("ui_order"), int), (nombre, extra)
    extra_purpose = GovernanceConfig.model_fields["purpose"].json_schema_extra
    assert isinstance(extra_purpose, dict) and extra_purpose["ui_widget"] == "textarea"
    grupos = {
        e["ui_group"]
        for c in GovernanceConfig.model_fields.values()
        if isinstance(e := c.json_schema_extra, dict) and e.get("ui_widget") != "hidden"
    }
    assert grupos == {"Inventario", "Ficha del modelo", "Ajustes manuales"}


def test_ningun_codigo_interno_llega_a_los_tooltips_de_governance() -> None:
    """§6.8: lo que se lee en pantalla —title, description, ui_help— no habla en código."""
    rama = _rama_governance()
    ofensores = [
        (nombre, campo, spec[campo])
        for nombre, spec in rama["properties"].items()
        if spec.get("ui_widget") != "hidden"
        for campo in ("title", "description", "ui_help")
        if isinstance(spec.get(campo), str) and _CODIGOS_INTERNOS.search(spec[campo])
    ]
    assert ofensores == [], ofensores


def test_el_detector_de_codigos_internos_caza_el_copy_viejo() -> None:
    """Anclado al texto real que salió con D-GOB-13: si no lo cazara, el gate no mediría nada."""
    for viejo in _TEXTOS_VIEJOS:
        assert _CODIGOS_INTERNOS.search(viejo), viejo
    # Y no acusa al copy aprobado, que nombra «MLflow» y «CMF» como productos, no como códigos.
    for aprobado in COPY_APROBADO.values():
        assert not _CODIGOS_INTERNOS.search(aprobado), aprobado


def test_la_decision_de_purpose_reusa_frases_del_copy_aprobado() -> None:
    """D-GOB-12: la pregunta de la tarjeta no es copy nuevo, sino el aprobado hecho pregunta."""
    decision = next(
        d for d in list_jobs()[0]["required_decisions"] if d["path"] == "governance.purpose"
    )
    assert decision["question"].endswith("?")
    assert decision["answer_forms"] == []
    aprobado = COPY_APROBADO["purpose"]
    assert decision["question"].strip("¿?") in aprobado
    assert decision["help"] in aprobado


# ─────────────────── §6.7 / D-GOB-15/16: la ficha se pinta y su tipo es el real ───────────────────

_RESULTS_TYPES_TS = _RAIZ / "web" / "src" / "lib" / "results-types.ts"
_STATIC = _RAIZ / "src" / "nikodym" / "ui" / "static"
_FIXTURES_DEL_BUNDLE = (
    _RAIZ / "web" / "src" / "fixtures" / "schema.json",
    _RAIZ / "web" / "src" / "fixtures" / "jobs.json",
)
_FIXTURES_DE_LA_DEMO = tuple(
    sorted((_RAIZ / "web" / "src" / "fixtures" / "demo").glob("results*.json"))
)

#: Cada interfaz del front y el modelo Pydantic que espeja. Las claves se comparan como LISTAS: el
#: mismo conjunto, en el mismo orden que declara el modelo (que es el orden en que se emiten).
_ESPEJOS_DEL_TIPO: dict[str, type[BaseModel]] = {
    "ModelCard": ModelCard,
    "ModelCardDecision": DecisionRecord,
    "ModelCardEnvironment": EnvironmentSnapshot,
    "ModelCardDataDescription": DataCardSection,
}

#: Los rótulos que la sección «Ficha del modelo» escribe en Resultados. ⚠️ «Ficha del modelo» a
#: secas ya viajaba en el bundle desde S3 —cuatro veces, como nombre de grupo del formulario
#: (`ui_group` de `GovernanceConfig`, que llega a `schema.json` y éste se empaqueta)—, así que el
#: «de cero a ≥ 1» de §6.7 se mide descontando lo que aportan los fixtures empaquetados.
_ROTULOS_DE_LA_FICHA = (
    "Ficha del modelo",
    "Próxima revisión",
    "Decisiones registradas",
    "Métricas por dominio",
)


def _claves_de_la_interfaz_ts(nombre: str) -> list[str]:
    """Las claves de ``export interface <nombre> { ... }`` en ``results-types.ts``, en su orden."""
    texto = _RESULTS_TYPES_TS.read_text(encoding="utf-8")
    cuerpo = re.search(rf"^export interface {re.escape(nombre)} \{{\n(.*?)^\}}", texto, re.S | re.M)
    assert cuerpo is not None, f"results-types.ts no declara `export interface {nombre}`"
    return re.findall(r"^  ([a-z_0-9]+)\??:", cuerpo.group(1), re.M)


def _bundle_servido() -> str:
    """El único ``.js`` que ``index.html`` referencia, resuelto como lo hace el launcher."""
    index_html = (_STATIC / "index.html").read_text(encoding="utf-8")
    scripts = [
        local for _, local in resolve_local_resources(index_html, "") if local.endswith(".js")
    ]
    assert len(scripts) == 1, scripts
    return (_STATIC / scripts[0]).read_text(encoding="utf-8")


@pytest.fixture
def card_serializado(fake_binning_process: object, tmp_path: Path) -> dict[str, Any]:
    """La ficha tal como ``/api/results`` la emite HOY sobre una corrida F1 real.

    Mismo mecanismo que ``test_ui_serializers.py`` (30 filas, binning falso), con ``audit``
    encendida sobre un trail absoluto —para que la ficha traiga decisiones y el espejo de
    ``ModelCardDecision`` no sea vacuo— y gobernanza con propósito.
    """
    del fake_binning_process
    parquet = tmp_path / "cartera.parquet"
    write_behavior_parquet(parquet)
    trail = tmp_path / "trail.jsonl"
    config = full_f1_config(
        str(parquet), audit=AuditConfig(enabled=True, trail_filename=str(trail))
    )
    study = nikodym.run(config)
    assert study.run_context.status == "done"
    payload = serialize_study(
        study, governance=GovernanceConfig(purpose="Ficha en pantalla (S4)"), trail_path=trail
    )
    card = payload["model_card"]
    assert isinstance(card, dict)
    return card


@pytest.mark.parametrize(("interfaz", "modelo"), sorted(_ESPEJOS_DEL_TIPO.items()))
def test_el_tipo_del_front_espeja_las_claves_del_modelo_pydantic(
    interfaz: str, modelo: type[BaseModel]
) -> None:
    """D-GOB-16: renombrar, añadir o quitar un campo en cualquiera de los dos lados pone rojo."""
    assert _claves_de_la_interfaz_ts(interfaz) == list(modelo.model_fields)


def test_el_tipo_del_front_declara_diecinueve_claves() -> None:
    """Ancla contra la medición de la enmienda (§3 D-GOB-16: «19 claves, medidas sobre la
    respuesta real»)."""
    assert len(_claves_de_la_interfaz_ts("ModelCard")) == 19


def test_el_serializador_emite_hoy_exactamente_las_claves_del_tipo(
    card_serializado: dict[str, Any],
) -> None:
    """D-GOB-16: el tipo se deriva de lo que el serializador emite HOY, medido, no de memoria."""
    assert list(card_serializado) == _claves_de_la_interfaz_ts("ModelCard")
    assert list(card_serializado["environment"]) == _claves_de_la_interfaz_ts(
        "ModelCardEnvironment"
    )
    descripcion = card_serializado["data_description"]
    assert descripcion is not None, "la corrida F1 deja data_card: la descripción no puede faltar"
    assert list(descripcion) == _claves_de_la_interfaz_ts("ModelCardDataDescription")
    assert card_serializado["decisions"], "sin decisiones el espejo de la decisión sería vacuo"
    for decision in card_serializado["decisions"]:
        assert list(decision) == _claves_de_la_interfaz_ts("ModelCardDecision")


def test_los_valores_emitidos_tienen_los_tipos_que_el_front_declara(
    card_serializado: dict[str, Any],
) -> None:
    """Las formas que el tipo promete: fechas ISO, métricas planas con prefijo de dominio y
    secciones por dominio."""
    card = card_serializado
    assert isinstance(card["purpose"], str) and card["purpose"]
    for fecha in ("created_at", "review_date", "next_review_date"):
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\S+", card[fecha]), (fecha, card[fecha])
    assert isinstance(card["git_dirty"], bool)
    assert isinstance(card["root_seed"], int)
    for lista in ("assumptions", "limitations", "determinism_caveats"):
        assert all(isinstance(x, str) for x in card[lista]), lista
    assert card["metrics"], "una corrida F1 completa publica métricas (D-GOB-1)"
    for clave, valor in card["metrics"].items():
        assert "." in clave, f"métrica sin prefijo de dominio: {clave!r} (D-GOB-2)"
        assert isinstance(valor, float) and math.isfinite(valor), (clave, valor)
    assert all(isinstance(seccion, dict) for seccion in card["metric_sections"].values())
    for decision in card["decisions"]:
        assert decision["step"] is None or isinstance(decision["step"], str)
        assert isinstance(decision["regla"], str) and isinstance(decision["accion"], str)


def test_sin_gobernanza_no_hay_ficha_y_la_demo_sigue_sin_ella() -> None:
    """§5: los tres fixtures traen ``model_card: null``; el guard los cubre y no se recapturan."""
    assert len(_FIXTURES_DE_LA_DEMO) == 3, [p.name for p in _FIXTURES_DE_LA_DEMO]
    for fixture in _FIXTURES_DE_LA_DEMO:
        payload = json.loads(fixture.read_text(encoding="utf-8"))
        assert "model_card" in payload, fixture.name
        assert payload["model_card"] is None, fixture.name


def test_el_bundle_servido_pinta_la_ficha_del_modelo() -> None:
    """§6.7: el bundle pasa «de cero a ≥ 1», descontando lo que ya aportaban los fixtures."""
    bundle = _bundle_servido()
    fixtures = "".join(p.read_text(encoding="utf-8") for p in _FIXTURES_DEL_BUNDLE)
    for rotulo in _ROTULOS_DE_LA_FICHA:
        en_fixtures = fixtures.count(rotulo)
        en_bundle = bundle.count(rotulo)
        assert en_bundle >= en_fixtures + 1, (
            f"{rotulo!r}: el bundle lo trae {en_bundle} veces y los fixtures empaquetados "
            f"{en_fixtures}; la sección de Resultados no aporta ninguna propia"
        )
    # El panel lee la clave del payload; hasta S4 el bundle no la nombraba ni una vez (§1.2).
    assert bundle.count("model_card") >= 1
