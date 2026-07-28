"""Gate de cobertura del vocabulario `column_role` (D-PRE-4).

El preflight sólo ve los campos que declaran su rol. Un campo nuevo que nombre una columna y no lo
declare no rompe nada visible: simplemente **deja de comprobarse**, y el preflight sigue diciendo
«compatible» sobre un config que fallará al correr. Ése es el modo de fallo que este gate impide.

**Alcance explícito: el camino F1.** `provisioning*`, `survival`, `markov`, `forward` y `stress`
quedan fuera **a propósito** —la enmienda acota ahí su alcance— y el gate lo declara en
:data:`SECCIONES_EN_ALCANCE` en vez de callarlo: una lista corta sin explicación se lee como
cobertura total, que es justo lo que no es.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from pydantic import BaseModel, Field

from nikodym.binning.config import BinningConfig
from nikodym.calibration.config import CalibrationConfig
from nikodym.core.dataset_check import CLAVE_ROL, ROLES, _rol
from nikodym.data.config import DataConfig
from nikodym.performance.config import PerformanceConfig
from nikodym.scorecard.config import ScorecardConfig
from nikodym.selection.config import SelectionConfig
from nikodym.stability.config import StabilityConfig

#: Las siete secciones del camino F1. Ampliar el alcance es sumar aquí, no reescribir el gate.
SECCIONES_EN_ALCANCE = (
    DataConfig,
    BinningConfig,
    SelectionConfig,
    ScorecardConfig,
    CalibrationConfig,
    PerformanceConfig,
    StabilityConfig,
)

#: Clave de config de cada sección en alcance: la que abre el `path` de un desajuste
#: (``data.partition.strategy.cohort_col``) y la que el sidebar usa para navegar.
CLAVES_EN_ALCANCE = {
    DataConfig: "data",
    BinningConfig: "binning",
    SelectionConfig: "selection",
    ScorecardConfig: "scorecard",
    CalibrationConfig: "calibration",
    PerformanceConfig: "performance",
    StabilityConfig: "stability",
}

#: Catálogo de secciones navegables del formulario (front). Vive UNA vez, en `lib/schema.ts`.
_SCHEMA_TS = Path(__file__).resolve().parents[2] / "web" / "src" / "lib" / "schema.ts"

#: Sufijos que delatan un campo que nombra columnas. `name`/`col` sueltos (``ColumnSpec.name``,
#: ``Predicate.col``) no caben en un patrón por sufijo sin arrastrar falsos positivos, así que van
#: marcados igual pero este gate no los exige: cubre el patrón mayoritario, y lo dice.
SUFIJOS = ("_col", "_column", "_columns", "_cols")


def _modelos_alcanzables(raiz: type[BaseModel]) -> set[type[BaseModel]]:
    """Todos los modelos Pydantic alcanzables desde ``raiz``, incluida ella."""
    vistos: set[type[BaseModel]] = set()
    pendientes = [raiz]
    while pendientes:
        modelo = pendientes.pop()
        if modelo in vistos:
            continue
        vistos.add(modelo)
        for info in modelo.model_fields.values():
            for arg in (info.annotation, *getattr(info.annotation, "__args__", ())):
                if isinstance(arg, type) and issubclass(arg, BaseModel):
                    pendientes.append(arg)
                for anidado in getattr(arg, "__args__", ()):
                    if isinstance(anidado, type) and issubclass(anidado, BaseModel):
                        pendientes.append(anidado)
    return vistos


def _campos_de_columna() -> list[tuple[type[BaseModel], str]]:
    """Campos en alcance cuyo nombre calza con :data:`SUFIJOS`."""
    encontrados: list[tuple[type[BaseModel], str]] = []
    for seccion in SECCIONES_EN_ALCANCE:
        for modelo in _modelos_alcanzables(seccion):
            for nombre in modelo.model_fields:
                if nombre.endswith(SUFIJOS):
                    encontrados.append((modelo, nombre))
    return sorted(set(encontrados), key=lambda par: (par[0].__name__, par[1]))


def _secciones_navegables() -> set[str]:
    """Claves de `CONFIG_SECTIONS` (`web/src/lib/schema.ts`), leídas del propio catálogo.

    Se lee el archivo en vez de duplicar la lista aquí, por la misma razón que
    ``test_public_copy.py`` lee ``markers.ts``: una copia a mano se desincroniza en silencio, que
    es justo el modo de fallo que el gate persigue.
    """
    texto = _SCHEMA_TS.read_text(encoding="utf-8")
    _, _, resto = texto.partition("export const CONFIG_SECTIONS")
    bloque, _, _ = resto.partition("\n]")
    return set(re.findall(r'key:\s*"([a-z_0-9]+)"', bloque))


def test_toda_seccion_en_alcance_del_preflight_es_navegable_en_el_formulario() -> None:
    """Un desajuste cuya sección no está en el formulario es un diagnóstico inaccionable.

    El preflight devuelve la ruta del campo **para que el formulario pueda enfocarlo** (D-PRE-8).
    Si esa sección no está en `CONFIG_SECTIONS`, el usuario recibe un aviso exacto sobre un campo
    que la interfaz no ofrece: sólo le queda editar el YAML a mano. Es la definición de feature a
    medias del repo, y contradice el requisito 1 de la visión (paridad UI ↔ código).

    Ocurrió de verdad: `stability` era sección del config —y de las siete del camino F1— pero no
    estaba en el catálogo del sidebar, así que `stability.temporal_column` se reportaba sin
    destino. Se detectó conectando el preflight a la SPA, no antes.

    Ampliar el alcance del preflight (P5: `provisioning*`, `survival`, `markov`, `forward`,
    `stress`) obliga a pasar por aquí: o la sección se ofrece en el formulario, o se declara por
    qué no.
    """
    navegables = _secciones_navegables()
    assert navegables, (
        f"No se pudo leer `CONFIG_SECTIONS` de {_SCHEMA_TS.name}: si el catálogo cambió de forma, "
        "este gate quedaría verde sin comprobar nada."
    )

    ausentes = sorted(
        clave for clave in CLAVES_EN_ALCANCE.values() if clave not in navegables
    )

    assert not ausentes, (
        f"Secciones que el preflight puede señalar pero el formulario no ofrece: {ausentes}. "
        "El usuario recibiría un desajuste con su ruta exacta y ningún campo donde corregirlo. "
        f"Agrégalas a `CONFIG_SECTIONS` en {_SCHEMA_TS.name} (y su icono en `App.tsx`)."
    )


def test_todo_campo_de_columna_del_camino_f1_declara_su_rol() -> None:
    """Un campo `*_col*` sin `column_role` deja de comprobarse en silencio."""
    sin_rol = [
        f"{modelo.__name__}.{nombre}"
        for modelo, nombre in _campos_de_columna()
        if _rol(modelo, nombre) is None
    ]

    assert not sin_rol, (
        "Campos que nombran columnas sin `column_role` declarado: "
        f"{sin_rol}. Clasifícalos como 'input' (la trae el usuario), 'derived' (la produce "
        "el pipeline) o 'not_a_column' (el nombre engaña: `keep_structural_columns` es bool)."
    )


def test_ningun_rol_declarado_esta_fuera_del_vocabulario() -> None:
    """Un valor con typo (`"inputs"`) degradaría a «no clasificado» sin avisar."""
    invalidos = [
        f"{modelo.__name__}.{nombre}={_rol(modelo, nombre)!r}"
        for modelo, nombre in _campos_de_columna()
        if _rol(modelo, nombre) not in ROLES
    ]

    assert not invalidos, f"roles fuera de {sorted(ROLES)}: {invalidos}"


def test_el_gate_falla_ante_un_campo_sin_clasificar() -> None:
    """El gate se prueba INYECTANDO: uno que declara barrer una clase debe demostrarlo.

    Sin esto, `test_todo_campo_de_columna_del_camino_f1_declara_su_rol` podría estar verde por no
    encontrar nada —un recorrido roto da cero campos y cero incumplimientos— y nadie lo notaría.
    """

    class SeccionConCampoNuevo(BaseModel):
        """Modelo de laboratorio: un campo de columna que nadie clasificó."""

        cliente_col: str = Field(default="cliente", title="Columna cliente")

    assert _rol(SeccionConCampoNuevo, "cliente_col") is None

    campos = [
        (modelo, nombre)
        for modelo in _modelos_alcanzables(SeccionConCampoNuevo)
        for nombre in modelo.model_fields
        if nombre.endswith(SUFIJOS)
    ]
    assert campos == [(SeccionConCampoNuevo, "cliente_col")]


def test_el_recorrido_encuentra_los_campos_que_la_medicion_conto() -> None:
    """Ancla contra un recorrido que se rompa y devuelva de menos.

    El número sale de la medición del 2026-07-28 (26 campos `*_col*` en el camino F1) y se escribe
    a mano a propósito: derivarlo del propio recorrido haría el test tautológico.
    """
    nombres = {f"{modelo.__name__}.{nombre}" for modelo, nombre in _campos_de_columna()}

    for esperado in (
        "SchemaConfig.index_col",
        "CohortSplitConfig.cohort_col",
        "TargetConfig.target_col",
        "BinningConfig.feature_columns",
        "BinningConfig.categorical_columns",
        "StabilityConfig.temporal_column",
        "PerformanceConfig.pd_column",
        "CalibrationConfig.pd_raw_column",
    ):
        assert esperado in nombres, f"el recorrido perdió {esperado}"

    assert len(nombres) >= 26


@pytest.mark.parametrize(
    ("modelo", "campo", "rol_esperado"),
    [
        (BinningConfig, "keep_structural_columns", "not_a_column"),
        (SelectionConfig, "keep_structural_columns", "not_a_column"),
        (SelectionConfig, "feature_columns", "derived"),
        (StabilityConfig, "temporal_column", "input"),
        (StabilityConfig, "partition_column", "derived"),
    ],
)
def test_las_clasificaciones_que_el_nombre_del_campo_haria_fallar(
    modelo: type[BaseModel], campo: str, rol_esperado: str
) -> None:
    """Los cinco casos donde clasificar por el nombre da la respuesta equivocada.

    `keep_structural_columns` es un `bool`; `selection.feature_columns` refiere las variables que
    publica *binning*, no columnas del dataset; y en `stability` conviven una de entrada
    (`temporal_column`) y una derivada (`partition_column`) con el mismo aspecto. Se anclan a mano
    porque son exactamente los que una heurística por sufijo rompería.
    """
    assert _rol(modelo, campo) == rol_esperado
    assert modelo.model_fields[campo].json_schema_extra[CLAVE_ROL] == rol_esperado  # type: ignore[index]
