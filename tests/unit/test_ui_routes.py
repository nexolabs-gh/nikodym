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
import subprocess
import sys
from collections.abc import Iterator
from copy import deepcopy
from pathlib import Path, PureWindowsPath
from typing import Any

import pandas as pd
import pytest
from _ui_f1 import failing_config, full_f1_config, write_behavior_parquet

from nikodym.core.config import NikodymConfig, ReproConfig, config_hash, dump_config, loads_config
from nikodym.core.config.migration import _MIGRATORS, migration
from nikodym.core.config.schema import rama_objeto
from nikodym.core.exceptions import ConfigError
from nikodym.ui import datasets as datasets_module
from nikodym.ui import presets as presets_module
from nikodym.ui import routes
from nikodym.ui.exceptions import UiDatasetError

# ─────────────────────────────── lógica pura de endpoints ───────────────────────────────


def test_schema_payload_shape() -> None:
    """``/schema`` entrega JSON-Schema, defaults, orden de secciones y defaults efectivos.

    ``effective_defaults`` entró con D-FX-5 y es **aditivo**: los tres campos previos conservan su
    significado exacto. Esta igualdad se mantiene EXACTA a propósito —no ``<=``—: el payload es
    contrato, y una clave que aparezca sin que nadie la haya decidido debe ponerse roja aquí.
    """
    payload = routes.schema_payload()
    assert set(payload) == {
        "json_schema",
        "defaults",
        "section_order",
        "effective_defaults",
    }
    assert payload["section_order"] == list(NikodymConfig.model_fields)
    assert payload["section_order"][0] == "schema_version"
    assert {"repro", "data", "report"} <= set(payload["section_order"])
    assert "properties" in payload["json_schema"]
    assert payload["defaults"]["repro"]["seed"] == 42  # defaults resueltos del config vacío
    # `defaults` NO cambia de significado: sigue siendo el config vacío con sus secciones nulas.
    assert payload["defaults"]["report"] is None
    # …y el catálogo sí sabe lo que ese config vacío ejecutaría si se activara la sección.
    catalogo = payload["effective_defaults"]
    assert set(catalogo) == {"version", "sections", "$defs"}
    assert catalogo["sections"]["report"]["html"]["render_charts"] == {
        "has_default": True,
        "value": True,
    }


def test_schema_payload_expande_dominios_f1() -> None:
    """``/schema`` entrega el schema COMPLETO: secciones F1 expandidas y apagables (no opacas).

    Con el extra ``scoring`` instalado (job del CI), el motor de formulario del front recibe los
    campos reales de cada sección de dominio F1, no el schema opaco. La materialización vive en el
    core (``build_full_json_schema``); ``nikodym.ui`` sigue domain-agnostic (ver test AST abajo).

    Se comprueban las DOS mitades del contrato, porque la sección viaja como
    ``anyOf: [<objeto>, {"type": "null"}]``: que la rama-objeto trae los campos, y que la rama nula
    está — sin ella el formulario no puede apagar la sección, que es la mitad que se perdía.
    """
    payload = routes.schema_payload()
    props = payload["json_schema"]["properties"]
    for seccion in (
        "data",
        "binning",
        "selection",
        "model",
        "scorecard",
        "calibration",
        "performance",
    ):
        rama = rama_objeto(props[seccion])
        assert rama is not None and "properties" in rama, f"{seccion} llegó opaca al front"
        assert props[seccion]["default"] is None, f"{seccion} llegó sin poder apagarse"
    assert len(payload["json_schema"]["$defs"]) > 2  # opaco traía 2 (ReproConfig/RunConfig)


def test_validate_config_valido_devuelve_hash() -> None:
    """Un config válido reconstruye el modelo y devuelve su ``config_hash``.

    La igualdad es exacta a propósito —fija la forma completa del payload—, así que incluye
    ``pipeline``, que la enmienda VALIDACION-PIPELINE suma de forma **aditiva** (D-PIPE-2). Un
    config sin secciones activas es ejecutable con pipeline vacío: no hay nada que correr, y eso
    no es un error del config.
    """
    cfg = NikodymConfig(repro=ReproConfig(seed=7))
    resultado = routes.validate_config(cfg.model_dump(mode="json", by_alias=True))
    assert resultado == {
        "valid": True,
        "config_hash": config_hash(cfg),
        "errors": [],
        "pipeline": {
            "executable": True,
            "steps": [],
            "message": None,
            "inert_artifacts": [],
        },
        # D-PRO-2, aditivo. Con `data` apagada nadie produce nada, así que el mapa trae todas las
        # claves del config con listas vacías — se publica completo a propósito, para que el front
        # no tenga que distinguir «esta sección no viene» de «no aporta nada».
        "produced_columns_by_section": {seccion: [] for seccion in NikodymConfig.model_fields},
    }


def test_validate_config_invalido_estructura_errores() -> None:
    """Un rango violado da ``valid=False`` con errores estructurados (loc/msg/type)."""
    resultado = routes.validate_config({"repro": {"seed": -1}})
    assert resultado["valid"] is False
    assert resultado["config_hash"] is None
    assert resultado["errors"], "debe listar al menos un error"
    error = resultado["errors"][0]
    assert set(error) == {"loc", "msg", "type"}
    assert error["loc"] == ["repro", "seed"]


def test_validate_config_invariante_de_dominio_no_revienta_el_endpoint() -> None:
    """Un ``ConfigError`` es ``valid=False``, NO una excepción que sale como 500.

    Encontrado en vivo al abrir la sección `stability` en el formulario: activar un campo opcional
    sin escribirle valor deja ``temporal_column=""``, y ``StabilityConfig._check_invariantes``
    levanta ``ConfigError``. Como esa excepción **no hereda de ``ValueError``**, Pydantic no la
    envuelve en ``ValidationError`` y escapaba entera: este endpoint —cuyo contrato es responder
    SIEMPRE 200 (SDD-23 §4.2)— devolvía 500, y el front lo mostraba como «backend no disponible»,
    que es una afirmación falsa sobre un backend sano.

    Seis módulos `config.py` levantan `ConfigError` al validar, así que el caso no es exclusivo de
    `stability`; por eso el arreglo vive en el endpoint y no en una sección.
    """
    resultado = routes.validate_config(
        {"stability": {"score_column": "score", "temporal_column": ""}}
    )

    assert resultado["valid"] is False
    assert resultado["config_hash"] is None
    assert resultado["pipeline"] is None
    assert resultado["errors"], "un config que no reconstruye debe decir por qué"
    error = resultado["errors"][0]
    assert set(error) == {"loc", "msg", "type"}, "misma forma que un error de Pydantic"
    assert error["type"] == "config_error"
    assert "temporal_column" in error["msg"]


@pytest.mark.parametrize(
    "rama, campo",
    [
        ("beta_regression", "covariate_cols"),
        ("fractional_response", "covariate_cols"),
        ("workout", "recovery_col"),
    ],
)
def test_un_error_de_dominio_que_pertenece_a_un_campo_llega_anclado(rama: str, campo: str) -> None:
    """D-EXI-5: el ``loc`` lo declara el emisor, así que el formulario puede llevar al usuario ahí.

    🔴 El defecto que cierra, medido en pantalla: elegir una rama modelada de LGD dejaba «Config
    inválido · 1 error» **sin campo al que saltar**, mientras el gesto simétrico —elegir una
    partición temporal sin su columna de fecha— sí marca el suyo. El traductor ponía ``loc: []``
    siempre, con la razón correcta escrita: fabricarlo del texto del mensaje sería adivinar. La
    salida no fue adivinarlo, fue que el ``raise`` lo declare.

    ⚠️ La ruta va **absoluta desde la raíz**: el ``except`` que traduce vive en el endpoint y atrapa
    la validación del ``NikodymConfig`` entero, así que ahí ya no se sabe de qué sección viene.
    """
    resultado = routes.validate_config({"provisioning_internal": {"lgd": {"method": rama}}})

    assert resultado["valid"] is False
    error = resultado["errors"][0]
    assert error["type"] == "config_error"
    assert error["loc"] == ["provisioning_internal", "lgd", campo], (
        f"el error de la rama {rama!r} no se ancló a su campo: sin `loc` el usuario lee qué le "
        "falta y no tiene dónde ponerlo"
    )
    # Y el mensaje sigue siendo el del motor, sin reescribir: el `loc` se añade, no sustituye.
    assert campo in error["msg"]


def test_toda_ruta_declarada_por_un_error_resuelve_contra_el_config() -> None:
    """El precio de que la ruta sea ABSOLUTA: sin vigilarla, un renombrado la deja en el vacío.

    Mismo trato que la clave ``exige`` del abanico (D-EXI-2): una ruta escrita a mano que ya no
    exista es peor que no anclar, porque manda al usuario a un campo que no está. Se resuelve contra
    ``model_fields``, bajando por submodelos y por las ramas de una unión discriminada.
    """
    import types
    import typing

    from nikodym.core.config.schema import cargar_configs_de_dominio

    secciones = cargar_configs_de_dominio()

    def resuelve(ruta: list[str]) -> bool:
        # 🔴 El primer tramo se resuelve contra el REGISTRO de dominio, no contra la anotación:
        # medido, `NikodymConfig.model_fields["provisioning_internal"].annotation` es `typing.Any`
        # —el blob opaco del núcleo liviano, que es diseño (SDD-23 §4.1)— así que bajar por la
        # anotación devuelve nada. La clase real vive en `cargar_configs_de_dominio()`, que es
        # exactamente cómo el motor la resuelve al coaccionar.
        if not ruta or ruta[0] not in secciones:
            return False
        if len(ruta) == 1:
            return True
        modelos: list[Any] = [secciones[ruta[0]]]
        for indice, nombre in enumerate(ruta[1:], start=1):
            # En cada tramo basta que ALGÚN modelo del nivel declare el campo: con una unión
            # discriminada, cada rama declara sólo los suyos.
            candidatos = [m for m in modelos if nombre in getattr(m, "model_fields", {})]
            if not candidatos:
                return False
            if indice == len(ruta) - 1:
                return True
            siguientes: list[Any] = []
            for modelo in candidatos:
                anotacion = modelo.model_fields[nombre].annotation
                ramas = (
                    typing.get_args(anotacion)
                    if isinstance(anotacion, types.UnionType)
                    or typing.get_origin(anotacion) is typing.Union
                    else (anotacion,)
                )
                siguientes.extend(r for r in ramas if hasattr(r, "model_fields"))
            if not siguientes:
                return False  # quedan tramos y este campo no baja a ningún submodelo
            modelos = siguientes
        return False

    # Las rutas que hoy se declaran, enumeradas: el universo es pequeño y enumerarlo es más fuerte
    # que barrer los `raise` con AST, que no ve una ruta construida por concatenación.
    rutas = [
        ["provisioning_internal", "lgd", "covariate_cols"],
        ["provisioning_internal", "lgd", "recovery_col"],
    ]
    for ruta in rutas:
        assert resuelve(ruta), f"la ruta {ruta} que un error declara no existe en el config"

    # Control negativo del propio resolvedor: una ruta inventada NO puede resolver, o este test
    # daría verde sobre cualquier cosa.
    assert not resuelve(["provisioning_internal", "lgd", "columna_que_no_existe"])
    assert not resuelve(["seccion_inventada", "campo"])


def test_los_mensajes_de_validacion_van_en_espanol() -> None:
    """La interfaz está en español y estos mensajes se pintan junto al campo: son copy público.

    «Field required» aparecía tal cual al añadir una fila al esquema del dataset —el paso más
    frecuente del recorrido por formulario—, junto con «Input should be a valid integer» y
    compañía. Se traduce por ``type``, que es contrato estable de Pydantic v2, y no por ``msg``,
    que es prosa y cambia entre versiones.
    """
    resultado = routes.validate_config({"data": {"schema": {"columns": [{}]}}})
    faltantes = [e for e in resultado["errors"] if e["type"] == "missing"]
    assert faltantes, "una fila de columna sin nombre ni dtype tiene campos obligatorios vacíos"
    assert all(e["msg"] == "Este campo es obligatorio." for e in faltantes)
    # El `type` NO se traduce: es la llave que consume un cliente programático.
    assert faltantes[0]["type"] == "missing"


def test_ningun_mensaje_de_validacion_queda_en_ingles_en_los_casos_frecuentes() -> None:
    """Barrido de los errores que produce editar el formulario, no de un caso suelto."""
    casos: list[dict[str, object]] = [
        {"data": {"schema": {"columns": [{}]}}},  # missing
        {"data": {"schema": {"columns": [{"name": 3, "dtype": "int"}]}}},  # string_type
        {"data": {"schema": {"strict": "quizas"}}},  # literal_error
        {"data": {"inventado": 1}},  # extra_forbidden
        {"binning": {"min_bin_size": 5.0}},  # less_than_equal
        {"repro": {"seed": -1}},  # greater_than_equal
    ]
    delatores = ("Field required", "Input should", "Value error, ", "Assertion failed, ")
    for caso in casos:
        for error in routes.validate_config(caso)["errors"]:
            assert not error["msg"].startswith(delatores), (
                f"mensaje sin traducir en {error['loc']}: {error['msg']}"
            )


def test_un_error_de_rango_conserva_su_cota() -> None:
    """Traducir no puede costar el dato: «mayor o igual que» sin el número no sirve."""
    resultado = routes.validate_config({"binning": {"min_bin_size": 5.0}})
    error = next(e for e in resultado["errors"] if e["loc"] == ["binning", "min_bin_size"])
    assert "0.5" in error["msg"], error["msg"]


def test_un_tipo_sin_traduccion_conserva_el_mensaje_original() -> None:
    """Nunca inventar: lo que no está mapeado viaja tal cual, no como texto genérico."""
    assert routes._mensaje_en_espanol({"type": "tipo_inexistente", "msg": "algo raro"}) == (
        "algo raro"
    )


def test_validate_config_campo_desconocido() -> None:
    """``extra='forbid'``: un campo desconocido es inválido (no se descarta en silencio)."""
    resultado = routes.validate_config({"campo_que_no_existe": 1})
    assert resultado["valid"] is False
    assert any(err["type"] == "extra_forbidden" for err in resultado["errors"])


def test_validate_config_no_depende_de_que_el_proceso_haya_pedido_el_schema() -> None:
    """D-HASH-5: ``valid`` significa lo mismo sea o no el primer request del proceso.

    Antes de la enmienda, un rango violado **dentro de una sección de dominio** devolvía
    ``valid=true`` con cero errores si el proceso aún no había importado esa capa —y publicaba un
    ``config_hash`` para ese config inválido—. Por la UI no se alcanzaba (el front no valida hasta
    tener el schema, y ``GET /api/schema`` importa los dominios), pero sí un cliente HTTP directo
    que pegue a ``/api/validate`` primero.

    En subproceso a propósito: dentro de la suite las capas ya están importadas, así que un montaje
    «natural» no reproduce el estado y sería un falso verde.
    """
    codigo = """
import json, sys
from nikodym.ui import routes
assert "nikodym.binning" not in sys.modules, "precondición: proceso frío, sin la capa"
resultado = routes.validate_config({"binning": {"min_bin_size": -1}})
assert resultado["valid"] is False, resultado
assert resultado["config_hash"] is None, "no se publica identidad de un config inválido"
assert [e["loc"] for e in resultado["errors"]] == [["binning", "min_bin_size"]], resultado
"""
    subprocess.run([sys.executable, "-c", codigo], check=True)


# --- Ejecutabilidad del pipeline (enmienda VALIDACION-PIPELINE) ---------------------------------


def test_config_inejecutable_es_valido_pero_no_ejecutable() -> None:
    """El caso que motivó la enmienda: IFRS 9 encendido sin la sección que produce su curva.

    Los dos sentidos de D-PIPE-1 en una sola aserción: el config **es válido** —reconstruye el
    modelo, que es lo que ``valid`` significa y sigue significando— y a la vez **no es
    ejecutable**. Antes, el usuario sólo se enteraba al apretar Ejecutar.
    """
    crudo = deepcopy(presets_module.get_preset("f4-ifrs9-retail")["config"])
    crudo["survival"] = None

    resultado = routes.validate_config(crudo)

    assert resultado["valid"] is True
    assert resultado["errors"] == []
    assert resultado["pipeline"]["executable"] is False
    assert resultado["pipeline"]["steps"] == []
    assert "provisioning_ifrs9" in resultado["pipeline"]["message"]


def test_preset_ejecutable_anuncia_los_pasos_que_correria() -> None:
    """Un preset de fábrica es ejecutable y publica su pipeline resuelto, en orden."""
    resultado = routes.validate_config(presets_module.get_preset("f4-ifrs9-retail")["config"])

    assert resultado["pipeline"] == {
        "executable": True,
        "steps": ["data", "survival", "provisioning_ifrs9", "report"],
        "message": None,
        "inert_artifacts": [],
    }


def test_config_que_no_reconstruye_no_inventa_veredicto_de_pipeline() -> None:
    """Sin modelo no hay pipeline que resolver: ``pipeline`` es ``None``, no un falso negativo."""
    resultado = routes.validate_config({"repro": {"seed": -1}})

    assert resultado["valid"] is False
    assert resultado["pipeline"] is None


def test_el_aviso_no_publica_codigos_de_marca(monkeypatch: pytest.MonkeyPatch) -> None:
    """El mensaje llega saneado al copy público (D-ERR-4/D-PIPE-5), con el código fuera.

    El corte se prueba aquí y no en ``check_pipeline``, que conserva el código porque es
    superficie de código: la misma frase, distinta según quién la lee.
    """
    from nikodym import api as api_module

    monkeypatch.setattr(
        routes.nikodym,
        "check_pipeline",
        lambda _config, *, artifacts=None: api_module.PipelineCheck(
            executable=False,
            message="FALTA-DATO-IFRS-4: la EAD comprometida no se modela todavía.",
            error_type="ConfigError",
            is_domain_error=True,
        ),
    )

    mensaje = routes.validate_config({})["pipeline"]["message"]

    assert mensaje is not None
    assert "FALTA-DATO-IFRS-4" not in mensaje
    assert "EAD comprometida" in mensaje


def test_un_fallo_inesperado_no_publica_su_detalle_interno(monkeypatch: pytest.MonkeyPatch) -> None:
    """Lo que no es accionable por quien configura no se publica crudo (D-ERR-5)."""
    from nikodym import api as api_module

    monkeypatch.setattr(
        routes.nikodym,
        "check_pipeline",
        lambda _config, *, artifacts=None: api_module.PipelineCheck(
            executable=False,
            message="AttributeError: 'NoneType' object has no attribute '_frame'",
            error_type="AttributeError",
            is_domain_error=False,
        ),
    )

    mensaje = routes.validate_config({})["pipeline"]["message"]

    assert mensaje is not None
    assert "_frame" not in mensaje
    assert "AttributeError" in mensaje


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


def test_config_to_yaml_no_reintroduce_report_document_materializado() -> None:
    """El ``to-yaml`` es determinista: no reinyecta ``report.document`` por la coacción.

    ``report: Any`` se coacciona a ``ReportConfig`` sólo cuando ``nikodym.report`` ya fue
    importado, y esa coacción materializa ``report.document`` (``default_factory``) que el config
    del cliente no traía. Sin ``exclude_unset`` el YAML dependería de qué se hubiera importado antes
    (no-determinista; así se colaba el bloque al capturar los fixtures de la demo tras generar un
    informe). Se fuerza el import (peor caso) y un config SIN ``document`` no debe recuperarlo.
    """
    import nikodym.report  # noqa: F401  — puebla _REPORT_CONFIG_CLS: activa la coacción (peor caso)
    from nikodym.report.config import ReportConfig

    config = NikodymConfig(report=ReportConfig()).model_dump(mode="json", by_alias=True)
    assert "document" in config["report"], "precondición: la coacción materializa document"
    del config["report"]["document"]  # el cliente no lo envía

    yaml_text = routes.config_to_yaml(config)["yaml"]
    assert "document:" not in yaml_text
    # El round-trip por hash se preserva (report es sección de infraestructura, fuera del hash).
    recargado = loads_config(yaml_text)
    assert config_hash(recargado) == config_hash(NikodymConfig.model_validate(config))


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


def test_config_from_yaml_conserva_el_config_sparse() -> None:
    """D-FX-8: un YAML parcial vuelve con la MISMA presencia de claves con que se escribió.

    Antes se devolvía la expansión completa (``model_dump`` sin ``exclude_unset``), de modo que
    abrir un archivo de veinte líneas dejaba en el formulario un documento de trescientas: cada
    default se materializaba como si el usuario lo hubiera elegido, sin que hubiera tocado nada.
    """
    yaml_parcial = 'name: parcial\nrepro:\n  seed: 7\nreport:\n  output_dir: "informes"\n'
    resultado = routes.config_from_yaml(yaml_parcial)
    config = resultado["config"]

    assert set(config) == {"name", "repro", "report"}
    assert config["repro"] == {"seed": 7}
    assert config["report"] == {"output_dir": "informes"}
    # Lo que el YAML no traía NO aparece: ni las secciones nulas ni los sub-modelos con factory.
    assert "data" not in config
    assert "sections" not in config["report"]
    assert "html" not in config["report"]


def test_config_from_yaml_conserva_null_explicito() -> None:
    """Ausente y ``null`` explícito son estados distintos, y el round-trip los distingue.

    ``exclude_unset`` conserva un ``null`` que el archivo escribió —apagar una sección es una
    decisión— y omite el que nadie escribió. Confundirlos es el defecto que D-FX-7 prohíbe en el
    formulario; el backend no puede reintroducirlo por la puerta de atrás.
    """
    con_nulo = routes.config_from_yaml("name: apagada\ndata: null\n")["config"]
    assert "data" in con_nulo and con_nulo["data"] is None

    sin_nada = routes.config_from_yaml("name: apagada\n")["config"]
    assert "data" not in sin_nada


def test_config_from_yaml_no_mueve_la_identidad() -> None:
    """D-FX-9: el ``config_hash`` es el del config **completo**, no el de la proyección.

    Ausente y default explícito tienen el mismo digest porque el hash identifica el config *que se
    ejecutaría*. Devolver menos claves no puede cambiar la identidad de la corrida.
    """
    parcial = routes.config_from_yaml("name: parcial\nrepro:\n  seed: 7\n")
    completo = NikodymConfig.model_validate({"name": "parcial", "repro": {"seed": 7}})
    assert parcial["config_hash"] == config_hash(completo)
    # Y el round-trip cerrado conserva el hash: cargar la proyección da la misma identidad.
    assert config_hash(NikodymConfig.model_validate(parcial["config"])) == parcial["config_hash"]


def test_config_to_yaml_conserva_la_misma_frontera() -> None:
    """``to-yaml`` no expande lo que ``from-yaml`` no materializó: la frontera es la misma."""
    yaml_parcial = "name: parcial\nrepro:\n  seed: 7\n"
    config = routes.config_from_yaml(yaml_parcial)["config"]
    devuelto = routes.config_to_yaml(config)["yaml"]
    assert "sections:" not in devuelto
    assert routes.config_from_yaml(devuelto)["config"] == config


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


def test_wire_dataset_source_relativo_usa_identificador_posix() -> None:
    """La ruta relativa usa `/` para conservar el mismo hash entre sistemas operativos."""
    config = {"data": {"load": {"source": None}}}

    wired = routes._wire_dataset_source(
        config, Path(".nikodym_ui") / "datasets" / "cartera.parquet"
    )

    assert wired["data"]["load"]["source"] == ".nikodym_ui/datasets/cartera.parquet"


@pytest.mark.parametrize(
    "source",
    [PureWindowsPath(r"\tmp\x.parquet"), PureWindowsPath(r"C:\tmp\x.parquet")],
)
def test_wire_dataset_source_windows_anclado_conserva_representacion_nativa(
    source: PureWindowsPath,
) -> None:
    """Una raíz o unidad Windows no se confunde con el identificador relativo portable."""
    config = {"data": {"load": {"source": None}}}

    wired = routes._wire_dataset_source(config, source)  # type: ignore[arg-type]

    assert wired["data"]["load"]["source"] == str(source)


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


def test_wire_report_output_dir_resuelve_workdir_relativo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """El manifiesto HTML recibe una salida absoluta aunque el workdir portable sea relativo."""
    monkeypatch.chdir(tmp_path)
    config = {"report": {"output_dir": "reports"}}

    wired = routes._wire_report_output_dir(config, workdir=Path(".nikodym_ui"))

    assert wired["report"]["output_dir"] == str(tmp_path / ".nikodym_ui" / "reports")


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
    """Un archivo por encima del tope por defecto levanta ``UiDatasetError`` con el tamaño."""
    monkeypatch.setattr(datasets_module, "_MAX_UPLOAD_BYTES", 4)
    with pytest.raises(UiDatasetError, match="límite"):
        datasets_module.ingest_upload(b"12345", "x.csv", workdir=tmp_path)


def test_ingest_upload_respeta_el_tope_que_le_pasan(tmp_path: Path) -> None:
    """El tope es un parámetro, no una constante privada: por HTTP lo fija ``upload_max_mb``.

    Hasta el 2026-08-02 ese campo declaraba 200 MB y **no lo leía nadie**, mientras el límite real
    eran los 100 MiB de esta capa. Un campo de configuración que miente es peor que uno ausente.
    """
    with pytest.raises(UiDatasetError, match="límite"):
        datasets_module.ingest_upload(b"12345", "x.csv", workdir=tmp_path, max_bytes=4)
    # Y el default sigue siendo el de siempre para quien llama por código sin decir nada.
    assert datasets_module.ingest_upload(_CSV_UPLOAD, "a.csv", workdir=tmp_path)["n_rows"] >= 1


def test_upload_max_mb_gobierna_el_endpoint_de_verdad(tmp_path: Path) -> None:
    """El campo de config decide el 422, que es lo que significa «conectarlo»."""
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx2")
    from _ui_client import ui_client

    from nikodym.ui.settings import UiConfig

    cliente = ui_client(UiConfig(workdir=str(tmp_path), upload_max_mb=1))
    grande = b"col\n" + b"x\n" * (2 * 1024 * 1024)
    respuesta = cliente.post("/api/upload", files={"file": ("grande.csv", grande, "text/csv")})

    assert respuesta.status_code == 422
    assert "límite admitido" in respuesta.json()["detail"]
    detalle = respuesta.json()["detail"]
    assert "1048576 bytes (1 MiB)" in detalle, "el tope que se reporta es el suyo, no el interno"


def test_el_tope_se_comprueba_antes_de_traer_el_cuerpo_a_memoria(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """🔴 El control negativo del defecto: el tope existía y no limitaba nada.

    Se comprobaba **después** de ``await file.read()``, o sea con el archivo entero ya en RAM.
    Aquí se hace fallar el `read()`: si el 422 sale igual, es que el tamaño se miró antes. Un test
    que sólo asevere el 422 pasaría con las dos implementaciones y no probaría nada.
    """
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx2")
    from _ui_client import ui_client
    from starlette.datastructures import UploadFile as StarletteUploadFile

    from nikodym.ui.settings import UiConfig

    async def _read_prohibido(self: object, size: int = -1) -> bytes:
        raise AssertionError("el cuerpo se materializó antes de comprobar el tope")

    monkeypatch.setattr(StarletteUploadFile, "read", _read_prohibido)
    cliente = ui_client(UiConfig(workdir=str(tmp_path), upload_max_mb=1))
    grande = b"col\n" + b"x\n" * (2 * 1024 * 1024)

    respuesta = cliente.post("/api/upload", files={"file": ("grande.csv", grande, "text/csv")})

    assert respuesta.status_code == 422
    assert "límite admitido" in respuesta.json()["detail"]


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

    from _ui_client import ui_client

    import nikodym
    from nikodym.core.exceptions import MissingDependencyError
    from nikodym.ui.settings import UiConfig

    def _materialize(dataset_id: str, *, workdir: Path) -> Path:
        return Path(workdir) / "datasets" / f"{dataset_id}.parquet"

    def _raise_missing(config: object, *, artifacts: object = None) -> object:
        raise MissingDependencyError("instale nikodym[tracking] para publicar al inventario.")

    monkeypatch.setattr(datasets_module, "materialize", _materialize)
    monkeypatch.setattr(nikodym, "run", _raise_missing)

    client = ui_client(UiConfig(workdir=str(tmp_path)))
    config = full_f1_config("placeholder.parquet").model_dump(mode="json", by_alias=True)
    respuesta = client.post(
        "/api/run", json={"config": config, "dataset_id": "consumo_comportamiento"}
    )

    assert respuesta.status_code == 422
    assert "nikodym[tracking]" in respuesta.json()["detail"]


# ── preflight config↔dataset (enmienda PREFLIGHT-DATASET, D-PRE-1…D-PRE-9) ────────────────────


def test_preflight_no_confunde_el_indice_del_parquet_con_una_columna(tmp_path: Path) -> None:
    """El dataset del catálogo NO puede salir incompatible con su propio preset.

    Es el falso positivo que costó detectar: el esquema Arrow lista el índice como un campo más,
    así que `read_schema().names` devolvía `loan_id` entre las columnas y el preflight acusaba a
    `data.schema.index_col` justo en el caso más común. Sólo se ve **probando contra el parquet
    real**: un test que pase los nombres a mano ya los trae separados y nunca reproduce el estado.
    """
    from nikodym.ui.routes import preflight_dataset

    resultado = preflight_dataset(
        presets_module.get_preset("f1-estandar-consumo")["config"],
        "consumo_comportamiento",
        workdir=tmp_path,
    )

    assert resultado["compatible"] is True, resultado["mismatches"]
    assert resultado["mismatches"] == []
    assert resultado["uninspected"] == []


def test_preflight_reporta_todos_los_desajustes_de_un_csv_ajeno(tmp_path: Path) -> None:
    """El caso que originó la capacidad: seis corridas seriales pasan a ser una llamada."""
    from nikodym.ui.routes import preflight_dataset, upload_dataset

    ajeno = pd.DataFrame(
        {
            "rut_operacion": ["L1", "L2", "L3"],
            "periodo_camada": ["2024Q1", "2024Q1", "2024Q2"],
            "renta_liquida": [1.0, 2.0, 3.0],
            "marca_incumplimiento": [0, 1, 0],
        }
    )
    buffer = io.BytesIO()
    ajeno.to_csv(buffer, index=False)
    subida = upload_dataset(buffer.getvalue(), "cartera_ajena.csv", workdir=tmp_path)

    resultado = preflight_dataset(
        presets_module.get_preset("f1-estandar-consumo")["config"],
        subida["dataset_id"],
        workdir=tmp_path,
    )

    assert resultado["compatible"] is False
    rutas = {m["path"] for m in resultado["mismatches"]}
    assert "data.partition.strategy.cohort_col" in rutas
    assert "binning.feature_columns" in rutas
    # Todos en una sola llamada, que es la razón de existir de la capacidad (D-PRE-2).
    assert len(resultado["mismatches"]) > 5
    # Y el copy es para un humano: sin códigos internos ni jerga de pandera.
    assert all("check:" not in m["message"] for m in resultado["mismatches"])
