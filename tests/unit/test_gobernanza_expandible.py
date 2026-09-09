"""Gates de D-GOB-10: ``governance`` se expande por un mapa INFRA propio, nunca por el de dominios.

La enmienda GOBERNANZA-EN-PANTALLA midió y descartó el atajo obvio —«añadirla a
``_DOMAIN_CONFIG_CLASSES`` como ``report``»— porque ``_DEFAULT_DOMAIN_ORDER`` deriva el pipeline
de esa lista y ``governance`` no tiene ``Step``: describe la corrida, no la calcula. De ahí un mapa
hermano, ``_INFRA_CONFIG_CLASSES``, y dos loaders más en ``core.config.schema``. Lo que aquí se
vigila es lo que la enmienda preespecifica en su §6:

1. el schema expande ``governance`` con sus campos y ``report`` sigue expandida (§6.1);
2. ``governance`` no es un paso, y la correspondencia entre el orden y el mapa de dominios se gatea
   en los dos sentidos (§6.2);
3. el ``config_hash`` de los cuatro presets no se mueve al expandirla (§6.3);
4. la validez de la sección no depende del orden de imports, medida en un proceso **fresco**
   (§6.9, D-HASH-5 sobre la sección nueva) —donde el hueco existe: en el motor—.

Controles negativos ejecutados al implementar: quitar ``governance`` del mapa INFRA deja el stub
opaco y pone rojo (1); añadirla a ``_DEFAULT_DOMAIN_ORDER`` pone rojo (2), además de
``test_survival_step`` y el censo de ``test_canal_metricas``; dejar la unión en sólo dominios pone
rojo (4). ⚠️ Dejar sólo el loader de dominios en ``validate_config`` **no** enrojece, y se dice:
``nikodym.ui.serializers`` importa ``nikodym.governance`` al cargarse, así que por la interfaz el
hueco nunca fue observable; la llamada a la unión en las rutas es blindaje del contrato.
"""

from __future__ import annotations

import copy
import importlib
import json
import subprocess
import sys
import types
from typing import Any

import pytest

from nikodym.core.config import NikodymConfig, config_hash
from nikodym.core.config import schema as schema_mod
from nikodym.core.config.hashing import INFRA_SECTIONS
from nikodym.core.config.schema import (
    build_full_json_schema,
    cargar_configs_de_dominio,
    cargar_configs_de_infra,
    cargar_configs_expandibles,
    rama_objeto,
)
from nikodym.core.study import (
    _DEFAULT_DOMAIN_ORDER,
    _DOMAIN_CONFIG_CLASSES,
    _INFRA_CONFIG_CLASSES,
    Study,
)
from nikodym.governance.config import GovernanceConfig
from nikodym.ui.presets import get_preset, list_presets

#: Los 13 campos de ``GovernanceConfig``, escritos a mano: el gate compara contra esta lista y no
#: contra ``model_fields``, para que un campo que desaparezca del schema se note.
CAMPOS_DE_GOVERNANCE = (
    "model_name",
    "cartera",
    "motor",
    "fase",
    "estado_validacion",
    "author",
    "purpose",
    "assumptions",
    "limitations",
    "review_period_months",
    "publish_to_inventory",
    "scenario_log_filename",
    "require_overlay_justification",
)


# ─────────────────────────── §6.1: el schema la expande ───────────────────────────


def test_el_schema_expande_governance_con_sus_campos_y_report_sigue_expandida() -> None:
    """``governance`` deja de ser un stub opaco; ``report`` —el precedente INFRA— no cambia."""
    props = build_full_json_schema()["properties"]

    rama = rama_objeto(props["governance"])
    assert rama is not None, "governance quedó opaca: el mapa INFRA no la expandió"
    assert tuple(rama["properties"]) == CAMPOS_DE_GOVERNANCE
    # Sólo `purpose` es obligatorio: es la premisa de D-GOB-8 y de D-GOB-12.
    assert rama.get("required") == ["purpose"]
    # Sigue siendo apagable (`anyOf: [objeto, null]` con `default: null`) y conserva sus etiquetas.
    assert props["governance"]["default"] is None
    assert props["governance"]["title"] == "Gobernanza"
    assert {v.get("type") for v in props["governance"]["anyOf"]} >= {"null"}

    assert rama_objeto(props["report"]) is not None, "report dejó de expandirse"
    # Lo que la enmienda NO pone en pantalla (§7) sigue opaco.
    assert rama_objeto(props["audit"]) is None
    assert rama_objeto(props["tracking"]) is None


def test_los_dos_loaders_y_su_union() -> None:
    """Dominios y infraestructura son preguntas distintas; la unión va dominios primero."""
    dominios = cargar_configs_de_dominio()
    infra = cargar_configs_de_infra()
    union = cargar_configs_expandibles()

    assert infra == {"governance": GovernanceConfig}
    assert "governance" not in dominios, "governance no es un dominio orquestable"
    assert list(union) == [*dominios, *infra]
    assert union == {**dominios, **infra}


def test_el_loader_de_infra_degrada_por_extra_ausente_igual_que_el_de_dominios(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mismo helper, misma degradación: un import que falla deja la sección opaca, sin excepción."""
    real_import = importlib.import_module

    def fake_import(name: str, package: str | None = None) -> types.ModuleType:
        if name == "nikodym.governance.config":
            raise ImportError("simulado: governance ausente")
        return real_import(name, package)

    monkeypatch.setattr(schema_mod.importlib, "import_module", fake_import)

    assert cargar_configs_de_infra() == {}
    assert "governance" not in cargar_configs_expandibles()
    props = build_full_json_schema()["properties"]
    assert rama_objeto(props["governance"]) is None
    assert props["governance"]["title"] == "Gobernanza"
    # El aislamiento es por sección: un dominio F1 sigue expandiéndose.
    assert rama_objeto(props["binning"]) is not None


# ─────────────────────────── §6.2: no es un paso, en los dos sentidos ───────────────────────────


def test_governance_no_es_un_paso_y_los_mapas_no_se_solapan() -> None:
    """Añadirla a ``_DEFAULT_DOMAIN_ORDER`` haría que ``run`` pidiera un paso que no existe."""
    assert "governance" not in _DEFAULT_DOMAIN_ORDER
    assert "governance" not in _DOMAIN_CONFIG_CLASSES
    assert set(_INFRA_CONFIG_CLASSES).isdisjoint(_DOMAIN_CONFIG_CLASSES)

    for seccion in _INFRA_CONFIG_CLASSES:
        assert seccion in NikodymConfig.model_fields, seccion
        assert seccion in INFRA_SECTIONS, f"{seccion} entraría al config_hash"

    # Con la sección encendida, el pipeline por defecto sigue sin contenerla.
    study = Study(NikodymConfig(governance=GovernanceConfig(purpose="Gate de D-GOB-10")))
    assert "governance" not in study._default_step_names()


def test_el_orden_de_ejecucion_y_el_mapa_de_dominios_enumeran_lo_mismo() -> None:
    """La correspondencia exacta que D-GOB-10 preserva, gateada en ambos sentidos.

    Una sección que entre al orden sin clase, o al mapa sin orden, rompe la premisa por la que
    ``governance`` necesitó un mapa propio: «todo lo que está en el mapa de dominios corre».
    """
    assert set(_DEFAULT_DOMAIN_ORDER) == set(_DOMAIN_CONFIG_CLASSES)
    assert len(_DEFAULT_DOMAIN_ORDER) == len(set(_DEFAULT_DOMAIN_ORDER))


# ─────────────────────────── §6.3: la identidad no se mueve ───────────────────────────


def _configs_de_preset() -> dict[str, dict]:
    # Registro completo (D-JUR-9.2): «ningún preset» son los cuatro registrados, no los tres que
    # el selector ofrece. F3 sigue resolviéndose por id y su identidad tampoco puede moverse.
    salida: dict[str, dict] = {}
    for entrada in list_presets(incluir_referencia=True):
        pid = entrada["id"] if isinstance(entrada, dict) else entrada
        descriptor = get_preset(pid)
        salida[pid] = descriptor.get("config", descriptor)
    return salida


def test_expandir_governance_no_mueve_el_config_hash_de_ningun_preset() -> None:
    """Mismo gate que D-GOB-8 hizo para ``audit``: ``governance`` es INFRA y no entra al digest."""
    assert "governance" in INFRA_SECTIONS
    configs = _configs_de_preset()
    assert len(configs) == 4

    for pid, cfg in configs.items():
        assert cfg["governance"] is None, f"{pid}: governance sigue apagada de fábrica (D-GOB-8)"
        encendido = copy.deepcopy(cfg)
        encendido["governance"] = {
            "purpose": "Gate de D-GOB-10",
            "review_period_months": 6,
            "cartera": "consumo",
        }
        assert config_hash(NikodymConfig.model_validate(encendido)) == config_hash(
            NikodymConfig.model_validate(cfg)
        ), f"{pid}: encender governance movió el config_hash"


# ─────────────────────────── §6.9: la validez no depende del orden de imports ───────────────


def _en_proceso_fresco(codigo: str) -> dict[str, Any]:
    """Ejecuta ``codigo`` en un ``python -I`` y devuelve el JSON que imprime.

    Dentro de pytest todo está siempre importado, así que un defecto de imports **sólo** se ve en
    un subproceso aislado (misma trampa que produjo dos ``config_hash`` distintos en ``1.8.0``).
    """
    salida = subprocess.run(
        [sys.executable, "-I", "-c", codigo],
        capture_output=True,
        text=True,
        check=True,
    )
    resultado: dict[str, Any] = json.loads(salida.stdout)
    return resultado


_MOTOR_FRESCO = """
import json
import sys

from nikodym.core.config import NikodymConfig
from nikodym.core.config import schema
from nikodym.core.config.schema import cargar_configs_de_dominio, cargar_configs_expandibles

config = {"governance": {"purpose": "x", "review_period_months": 999}}


def acepta():
    try:
        NikodymConfig.model_validate(config)
    except Exception:
        return False
    return True


medido = {"hook_vacio_al_inicio": schema._GOVERNANCE_CONFIG_CLS is None}
medido["acepta_sin_loader"] = acepta()
cargar_configs_de_dominio()
medido["acepta_tras_dominios"] = acepta()
medido["governance_importada_por_dominios"] = "nikodym.governance" in sys.modules
cargar_configs_expandibles()
medido["acepta_tras_expandibles"] = acepta()
medido["hook_poblado_al_final"] = schema._GOVERNANCE_CONFIG_CLS is not None
print(json.dumps(medido))
"""


def test_el_loader_de_dominios_no_basta_y_la_union_cierra_el_hueco_en_proceso_fresco() -> None:
    """El hueco de D-HASH-5 sobre ``governance``, medido donde existe: en el motor.

    En un proceso fresco ``NikodymConfig`` acepta ``review_period_months: 999`` mientras nadie
    importe ``nikodym.governance`` —la sección viaja opaca—, y ``cargar_configs_de_dominio()``
    **no la importa**: por eso hace falta la unión, y por eso el catálogo, la guarda del fixture y
    las rutas la usan. Es el oráculo que discrimina el loader; control negativo: dejar la unión en
    sólo dominios pone esto en rojo. Si algún día un dominio importara ``governance``, la tercera
    aserción se pondría roja y habría que decidir explícitamente qué queda de la unión.
    """
    medido = _en_proceso_fresco(_MOTOR_FRESCO)

    assert medido["hook_vacio_al_inicio"], "el hook ya venía poblado: el proceso no está fresco"
    assert medido["acepta_sin_loader"], "la sección ya se validaba sin loader: el hueco se movió"
    assert medido["acepta_tras_dominios"], (
        "cargar_configs_de_dominio() importó governance: la unión habría dejado de hacer falta"
    )
    assert medido["governance_importada_por_dominios"] is False
    assert medido["acepta_tras_expandibles"] is False, "la unión no cerró el hueco"
    assert medido["hook_poblado_al_final"]


_INTERFAZ_FRESCA = """
import json
import tempfile
from pathlib import Path

from pydantic import ValidationError

from nikodym.ui import routes

config = {"governance": {"purpose": "x", "review_period_months": 999}}
workdir = Path(tempfile.mkdtemp())


def medir():
    veredicto = routes.validate_config(config)
    try:
        routes.preflight_dataset(config, "dataset-que-no-existe", workdir=workdir)
        preflight = "acepto"
    except ValidationError as exc:
        preflight = "rechazo:" + ";".join(".".join(map(str, e["loc"])) for e in exc.errors())
    except Exception as exc:  # noqa: BLE001 — se reporta el tipo, el test decide
        preflight = "otro:" + type(exc).__name__
    return {"validate": veredicto, "preflight": preflight}


antes = medir()
routes.schema_payload()
despues = medir()
print(json.dumps({"antes": antes, "despues": despues}))
"""


def test_la_interfaz_juzga_igual_antes_y_despues_del_schema() -> None:
    """``/api/validate`` y el preflight dan el mismo veredicto antes y después de ``/api/schema``.

    Es el contrato que D-HASH-5 promete a la interfaz, en un proceso fresco. ⚠️ **No discrimina el
    loader de ``validate_config``**, y se dice: ``nikodym.ui.serializers`` importa
    ``nikodym.governance`` al cargarse, así que en un proceso que ya importó ``routes`` el hook está
    poblado haga lo que haga el endpoint —medido al implementar con el control negativo «sólo el
    loader de dominios», que no enrojeció—. El oráculo que sí discrimina es el del motor, arriba; la
    llamada a ``cargar_configs_expandibles()`` en las rutas deja el contrato explícito en vez de
    heredarlo de esa cadena de imports.
    """
    medido = _en_proceso_fresco(_INTERFAZ_FRESCA)

    for momento in ("antes", "despues"):
        veredicto = medido[momento]["validate"]
        assert veredicto["valid"] is False, f"{momento} del schema: /api/validate aceptó 999 meses"
        assert ["governance", "review_period_months"] in [e["loc"] for e in veredicto["errors"]], (
            f"{momento}: el error no nombra el campo: {veredicto['errors']}"
        )
        assert medido[momento]["preflight"].startswith("rechazo:"), (
            f"{momento}: el preflight no rechazó el config: {medido[momento]['preflight']}"
        )
        assert "governance.review_period_months" in medido[momento]["preflight"]

    assert medido["antes"]["validate"]["errors"] == medido["despues"]["validate"]["errors"]
    assert medido["antes"]["preflight"] == medido["despues"]["preflight"]
