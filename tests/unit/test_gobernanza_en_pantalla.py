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

Controles negativos ejecutados al implementar (protocolo del runbook §6): exponer
``scenario_log_filename`` pone rojo §6.6; quitar el validador de ``purpose`` pone rojo el motor,
``/api/validate`` y la tarjeta; sembrar ``governance`` encendida en el esqueleto pone rojo el gate
de ejecutabilidad de los nueve trabajos disponibles.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from nikodym.core.config import NikodymConfig
from nikodym.core.config.schema import build_full_json_schema, rama_objeto
from nikodym.governance.config import GovernanceConfig
from nikodym.ui import routes
from nikodym.ui.jobs import _SECCIONES_LATENTES, list_jobs
from nikodym.ui.presets import get_preset, list_presets

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
