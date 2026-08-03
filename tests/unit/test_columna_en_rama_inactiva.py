"""Gate de los dos supresores del preflight (`_ENMIENDA-COLUMNA-EN-RAMA-INACTIVA.md`, D-RAM-1…6).

🔴 **Son las primeras piezas del preflight que pueden CALLAR un desajuste**, y por eso se miden en
los dos sentidos. Un rol `column_role` mal declarado produce un aviso de más —molesto, visible—; un
supresor mal declarado produce un aviso de MENOS, que es exactamente el falso negativo silencioso
contra el que existe el preflight entero (D-PRE-9). El error caro aquí es el simétrico del que
arreglan.

Son **dos y distintos**, y confundirlos sería aplicar el remedio equivocado:

* `columnas_inactivas` (D-RAM-1) suprime por **rama de config**: el campo nombra una columna que
  esta configuración no va a leer. Lo reprodujo la revisión adversarial cruzada el 2026-08-03 —con
  ``ead.method='provided'`` y ``ccf_col`` inventada, `_estimate_ccf` ni se llama—.
* `columnas_que_produce` (D-RAM-6) suprime por **procedencia**: la columna existirá, pero la escribe
  el pipeline y no el archivo. Es la cara simétrica de `ROL_DERIVADA`, que mira el campo en vez del
  nombre.

⚠️ La tabla de abajo se escribe **a mano**, campo por campo, con la condición leída del motor y no
de `columnas_inactivas()`. Derivarla de lo que se comprueba haría el gate autorreferencial: mediría
que el método es determinista, no que dice la verdad. Es la clase que este repo ya pagó dos veces.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel, Field

from nikodym.core.config import NikodymConfig
from nikodym.core.config.schema import cargar_configs_de_dominio
from nikodym.core.dataset_check import (
    CLAVE_ROL,
    METODO_COLUMNAS_INACTIVAS,
    ROL_ENTRADA,
    _declaraciones,
    _rol,
    check_dataset,
)
from nikodym.core.study import _DOMAIN_CONFIG_CLASSES

#: Nombre que no está en ningún dataset: si el preflight lo mira, lo acusa.
FANTASMA = "columna_que_no_existe_en_ningun_archivo"

#: Columnas mínimas de un dataset cualquiera. Ninguna es :data:`FANTASMA`, que es el punto.
COLUMNAS = ("id", "fecha", "cartera", "exposicion", "mora", "pd", "lgd", "tasa")

#: Sección `data` mínima que construye: sus dos decisiones institucionales son obligatorias.
_DATA_MINIMA: dict[str, object] = {
    "target": {"bad_rule": {"all_of": [{"col": "mora", "op": ">", "value": 90}]}},
    "partition": {"strategy": {"type": "random"}},
}

#: 🔴 El oráculo, ESCRITO A MANO desde el código del motor (`archivo:línea` en cada fila).
#:
#: Cada entrada es: qué campo, dónde vive, qué config APAGA su rama y qué config la ENCIENDE. Las
#: dos direcciones importan y por razones distintas: la apagada prueba que el falso positivo se
#: cerró, y la encendida prueba que no se cerró de más — que es el modo de fallo peligroso.
CASOS: tuple[tuple[str, str, dict[str, object], dict[str, object]], ...] = (
    (
        # `_estimate_ccf` es la rama `else` del dispatch de `ead.py:131-135`.
        "ead.ccf_col",
        "ead",
        {"method": "provided", "ccf_col": FANTASMA},
        {"method": "ccf", "ccf_col": FANTASMA},
    ),
    (
        # `_estimate_regression` (`lgd.py:183-185`) sólo corre con beta/fractional.
        "lgd.covariate_cols",
        "lgd",
        {"method": "provided", "covariate_cols": [FANTASMA]},
        {"method": "beta_regression", "covariate_cols": [FANTASMA]},
    ),
    (
        # `_fired_notch` (`staging.py:189`) devuelve ceros sin mirar los ratings si no hay umbral.
        "staging.rating_col",
        "staging",
        {"rating_col": FANTASMA},
        {
            "rating_col": FANTASMA,
            "origination_rating_col": "cartera",
            "notch_downgrade_threshold": 2,
        },
    ),
    (
        "staging.origination_rating_col",
        "staging",
        {"origination_rating_col": FANTASMA},
        {
            "origination_rating_col": FANTASMA,
            "rating_col": "cartera",
            "notch_downgrade_threshold": 2,
        },
    ),
    (
        # `staging.py:221-228` sale con ceros si la exención está apagada, y su default es False.
        "staging.low_credit_risk_col",
        "staging",
        {"low_credit_risk_col": FANTASMA},
        {"low_credit_risk_col": FANTASMA, "low_credit_risk_exemption": True},
    ),
)


def _config_ifrs9(subseccion: str, valores: dict[str, object]) -> NikodymConfig:
    """Un config con `provisioning_ifrs9` y `valores` escritos en una de sus sub-secciones."""
    cargar_configs_de_dominio()
    return NikodymConfig.model_validate({"provisioning_ifrs9": {subseccion: valores}})


def _acusa(config: NikodymConfig, columna: str) -> bool:
    """¿El preflight señala `columna` como ausente?"""
    resultado = check_dataset(config, COLUMNAS)
    return any(m.declared == columna for m in resultado.mismatches)


@pytest.mark.parametrize(("campo", "subseccion", "apagada", "encendida"), CASOS)
def test_una_columna_de_rama_apagada_no_se_acusa(
    campo: str, subseccion: str, apagada: dict[str, object], encendida: dict[str, object]
) -> None:
    """Con la rama apagada el motor nunca abre la columna, así que exigirla es un falso positivo."""
    del encendida
    assert not _acusa(_config_ifrs9(subseccion, apagada), FANTASMA), (
        f"{campo}: el preflight acusa una columna que el motor no lee con esa configuración"
    )


@pytest.mark.parametrize(("campo", "subseccion", "apagada", "encendida"), CASOS)
def test_ancla_con_la_rama_encendida_la_misma_columna_si_se_acusa(
    campo: str, subseccion: str, apagada: dict[str, object], encendida: dict[str, object]
) -> None:
    """🔴 El control que da sentido al de arriba: sin esto, «no acusa nunca» pasaría igual.

    Es el modo de fallo caro de este mecanismo. Una `columnas_inactivas` que devolviera de más
    —o un `frozenset` con un typo que casara por accidente— dejaría el preflight mudo justo donde
    la columna sí hace falta, y el usuario lo descubriría con la corrida ya lanzada.
    """
    del apagada
    assert _acusa(_config_ifrs9(subseccion, encendida), FANTASMA), (
        f"{campo}: con su rama ACTIVA la columna sí se lee y el preflight tiene que exigirla"
    )


def test_todo_campo_declarado_inactivo_existe_y_tiene_rol() -> None:
    """Un nombre mal escrito en `columnas_inactivas` no suprime nada y no se nota (D-RAM-3).

    Dos formas de mentir sin que nada falle: nombrar un campo que no existe (el `frozenset` no casa
    y el aviso sigue saliendo, así que el autor cree haberlo cerrado) o nombrar uno que no declara
    rol (nunca se inspeccionó, y la línea sugiere que sí). Las dos se cierran aquí.
    """
    cargar_configs_de_dominio()
    vistos: set[str] = set()
    for modelo in _modelos_del_registro():
        if getattr(modelo, METODO_COLUMNAS_INACTIVAS, None) is None:
            continue
        # Se instancia con defaults, así que sólo se ve la rama por defecto de cada modelo: es
        # suficiente para lo que aquí se comprueba —la FORMA de los nombres—, y qué devuelve en cada
        # rama lo miden los dos tests de arriba contra el motor.
        for nombre in modelo().columnas_inactivas():
            vistos.add(f"{modelo.__name__}.{nombre}")
            assert nombre in modelo.model_fields, (
                f"{modelo.__name__}.columnas_inactivas() nombra «{nombre}», que no es un campo "
                f"suyo: el frozenset nunca casaría y el falso positivo seguiría vivo"
            )
            assert _rol(modelo, nombre) == ROL_ENTRADA, (
                f"{modelo.__name__}.{nombre} no declara column_role='input', así que el "
                f"preflight nunca lo inspeccionó: eximirlo no suprime nada y confunde"
            )
    # 🔴 Ancla anti-vacua, y no es teórica: la primera versión de este test recorrió CERO modelos
    # —`_DOMAIN_CONFIG_CLASSES` mapea a tuplas `(módulo, clase)`, no a clases— y «0 problemas» se
    # lee igual que «todo limpio». Los cuatro nombres van escritos, no contados: un número puede
    # tragarse una implementación que desaparezca mientras aparece otra.
    assert {
        "IfrsLgdConfig.covariate_cols",
        "IfrsStagingConfig.rating_col",
        "IfrsStagingConfig.origination_rating_col",
        "IfrsStagingConfig.low_credit_risk_col",
    } <= vistos, f"el barrido no alcanzó las declaraciones conocidas; vio {sorted(vistos)}"


def test_el_mecanismo_es_generico_y_no_un_caso_especial_de_ifrs9() -> None:
    """`_declaraciones` respeta el protocolo en cualquier modelo, no en una lista de clases."""

    class Ejemplo(BaseModel):
        modo: str = "apagado"
        columna: str = Field(default=FANTASMA, json_schema_extra={CLAVE_ROL: ROL_ENTRADA})
        siempre: str = Field(default="otra", json_schema_extra={CLAVE_ROL: ROL_ENTRADA})

        def columnas_inactivas(self) -> frozenset[str]:
            return frozenset() if self.modo == "encendido" else frozenset({"columna"})

    apagado = {c for _, _, c in _declaraciones(Ejemplo())}
    encendido = {c for _, _, c in _declaraciones(Ejemplo(modo="encendido"))}
    assert apagado == {"otra"}, "la columna de la rama apagada no debería declararse"
    assert encendido == {FANTASMA, "otra"}, "encendida, la columna vuelve a declararse"


#: 🔴 Las cuatro columnas que `data` AÑADE al frame, escritas a mano desde el motor: `target.py:36`
#: (`label_status`), `partition.py:38-39` (`partition`, `ttd`) y `data.target.target_col` para la
#: cuarta. Derivarlas de `columnas_que_produce()` haría el gate autorreferencial.
DERIVADAS = ("target", "label_status", "partition", "ttd")


@pytest.mark.parametrize("derivada", DERIVADAS)
def test_una_columna_que_el_pipeline_produce_no_se_exige_del_archivo(derivada: str) -> None:
    """Las secciones de abajo consumen la SALIDA de `data`, no el archivo del usuario (D-RAM-6).

    Medido con corridas reales: `survival.input.event_col = "target"` llega a `done` —el indicador
    de evento *es* el flag de malo, que es lo natural—, y `stability.temporal_column` sufría lo
    mismo en tres valores alcanzables **hoy en `main`**, sin un solo test que lo cubriera.
    """
    cargar_configs_de_dominio()
    assert not _acusa(_config_con_segmento(derivada), derivada), (
        f"«{derivada}» la produce el propio pipeline: exigirla del archivo es un falso positivo"
    )


def _config_con_segmento(columna: str) -> NikodymConfig:
    """Config con `data` activa y `survival.input.segment_col` apuntando a `columna`.

    Se usa `survival` y no `stability` porque `StabilityConfig` tiene un anticolisión propio
    (`config.py:213`) que rechaza `temporal_column="partition"` antes de construir — o sea que ahí
    el caso es inalcanzable por otra razón, y probarlo mediría el validador, no el preflight.
    """
    return NikodymConfig.model_validate(
        {
            "data": _DATA_MINIMA,
            "survival": {
                "input": {"duration_col": "mora", "event_col": "pd", "segment_col": columna}
            },
        }
    )


def test_ancla_una_columna_inventada_si_se_sigue_acusando() -> None:
    """🔴 El control que impide que lo de arriba se cierre de más.

    Sin esto, sumar cualquier cosa a las columnas presentes —o devolver un conjunto demasiado
    ancho— pasaría los cuatro casos y dejaría el preflight mudo, que es el falso negativo que
    justifica su existencia.
    """
    cargar_configs_de_dominio()
    assert _acusa(_config_con_segmento(FANTASMA), FANTASMA)


def test_sin_la_seccion_data_no_se_produce_nada() -> None:
    """Si el paso que las escribe no corre, sus columnas no existen: se vuelven a exigir."""
    cargar_configs_de_dominio()
    config = NikodymConfig.model_validate(
        {
            "survival": {
                "input": {"duration_col": "mora", "event_col": "pd", "segment_col": "target"}
            }
        }
    )
    assert _acusa(config, "target"), "sin `data` nadie escribe «target», así que tiene que faltar"


def test_la_columna_de_target_sale_del_CONFIG_y_no_de_una_constante() -> None:  # noqa: N802
    """Renombrar el target mueve la derivada: no está escrita a fuego en el núcleo.

    Es la diferencia entre declarar lo que el motor hace y copiar una lista de nombres, que se
    desincroniza en cuanto alguien usa el campo para lo que existe.
    """
    cargar_configs_de_dominio()
    target = {**_DATA_MINIMA["target"], "target_col": "mi_target"}  # type: ignore[dict-item]
    data = {**_DATA_MINIMA, "target": target}
    survival = {"input": {"duration_col": "mora", "event_col": "pd"}}
    nuevo = NikodymConfig.model_validate(
        {"data": data, "survival": {"input": {**survival["input"], "segment_col": "mi_target"}}}
    )
    assert not _acusa(nuevo, "mi_target")
    viejo = NikodymConfig.model_validate(
        {"data": data, "survival": {"input": {**survival["input"], "segment_col": "target"}}}
    )
    assert _acusa(viejo, "target"), "con el target renombrado, «target» ya no lo produce nadie"


def test_un_modelo_sin_el_metodo_se_comporta_igual_que_antes() -> None:
    """Aditivo de verdad: quien no lo declare no cambia (D-RAM-2)."""

    class SinMetodo(BaseModel):
        columna: str = Field(default=FANTASMA, json_schema_extra={CLAVE_ROL: ROL_ENTRADA})

    assert {c for _, _, c in _declaraciones(SinMetodo())} == {FANTASMA}


def test_los_presets_de_fabrica_siguen_compatibles() -> None:
    """Control negativo del conjunto: suprimir de más se vería aquí como un cambio de veredicto.

    No mide lo mismo que los casos de arriba —mide que no se rompió nada— y por eso va aparte: los
    presets de provisiones corren contra sus datasets reales y el preflight no tiene nada que
    decirles. Es el mismo control que cerró la declaración de los 32 roles el 2026-08-03.

    ⚠️ Las columnas se toman **separando el índice**, como hace el endpoint: el esquema Arrow lista
    el índice como un campo más, y tomarlo tal cual reporta el dataset del catálogo incompatible con
    su propio preset. Es el falso positivo más caro que este repo ha tenido, y reaparece en cuanto
    un test lee el parquet por su cuenta.
    """
    pytest.importorskip("pyarrow")
    import tempfile
    from pathlib import Path

    from nikodym.ui.datasets import materialize
    from nikodym.ui.presets import get_preset
    from nikodym.ui.routes import _columnas_del_parquet

    cargar_configs_de_dominio()
    for preset_id in ("f3-provisiones-consumo", "f4-ifrs9-retail"):
        preset = get_preset(preset_id)
        config = NikodymConfig.model_validate(preset["config"])
        with tempfile.TemporaryDirectory() as tmp:
            ruta = materialize(preset["dataset_id"], workdir=Path(tmp))
            columnas, indices = _columnas_del_parquet(ruta)
        resultado = check_dataset(config, columnas, index_columns=indices)
        assert resultado.mismatches == (), f"{preset_id}: {resultado.mismatches}"


def _modelos_del_registro() -> set[type[BaseModel]]:
    """Todos los modelos alcanzables desde el registro de dominio.

    ⚠️ `_DOMAIN_CONFIG_CLASSES` mapea a ``(módulo, clase)``, no a clases: hay que importar. Asumir lo
    contrario dejó la primera versión de este gate recorriendo cero modelos.
    """
    import importlib

    vistos: set[type[BaseModel]] = set()
    pendientes = [
        getattr(importlib.import_module(modulo), nombre)
        for modulo, nombre in _DOMAIN_CONFIG_CLASSES.values()
    ]
    while pendientes:
        actual = pendientes.pop()
        if actual in vistos or not (isinstance(actual, type) and issubclass(actual, BaseModel)):
            continue
        vistos.add(actual)
        for info in actual.model_fields.values():
            for arg in (info.annotation, *getattr(info.annotation, "__args__", ())):
                if isinstance(arg, type) and issubclass(arg, BaseModel):
                    pendientes.append(arg)
    return vistos
