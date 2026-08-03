"""El preflight no avisa sobre un paso que NO va a correr.

🔴 El defecto, medido: con ``run.steps=[]`` —cero pasos, y ``check_pipeline`` lo confirmaba con
``steps=()``— ``check_dataset`` seguía emitiendo dos ``unmet_requirement``, uno de ``performance``
y otro de ``survival``. La salida era **bit a bit idéntica** con ``None``, ``[]`` y ``['data']``:
este módulo no miraba ``run.steps`` en ninguna línea.

Es la misma familia que D-RAM-1 —un aviso sobre algo que el motor nunca abre—, en otra coordenada:
allí era una rama de config apagada, aquí un paso que la invocación excluye.

⚠️ Atenuante medido, que acota el alcance pero no lo absuelve: ``run`` **no está en
``CONFIG_SECTIONS``**, así que desde el formulario no es alcanzable. Sí lo es por YAML y por código,
que es como se usa esto **como librería** — y ``nikodym.check_dataset`` es API pública.
"""

from __future__ import annotations

import pytest

import nikodym
from nikodym.core.config import NikodymConfig
from nikodym.core.config.schema import cargar_configs_de_dominio

_COLUMNAS = ("ingreso", "mora", "fecha_obs")

#: Config con DOS secciones que declaran invariantes incumplidas a la vez, para que el filtro se
#: pueda medir por partes: si sólo hubiera una, «0 avisos» no distinguiría filtrar de romper.
_BASE: dict[str, object] = {
    "data": {
        "target": {"bad_rule": {"all_of": [{"col": "mora", "op": ">", "value": 90}]}},
        "partition": {"strategy": {"type": "random"}},
    },
    # `partitions` duplicadas → `PerformanceConfig.requisitos_incumplidos`.
    "performance": {"partitions": ["desarrollo", "desarrollo"]},
    # Grilla sin declarar → `SurvivalConfig.requisitos_incumplidos`.
    "survival": {"input": {"duration_col": "mora", "event_col": "target"}},
}


def _avisos(steps: list[str] | None) -> list[str]:
    cargar_configs_de_dominio()
    extra: dict[str, object] = {} if steps is None else {"run": {"steps": steps}}
    veredicto = nikodym.check_dataset(NikodymConfig.model_validate({**_BASE, **extra}), _COLUMNAS)
    return sorted(m.path for m in veredicto.mismatches if m.kind == "unmet_requirement")


def test_sin_declarar_steps_avisan_las_dos_secciones_activas() -> None:
    """El ancla, y la mitad que NO puede cambiar: `None` = «corren las activas».

    Sin esto, un filtro roto que devolviera siempre el conjunto vacío pasaría los tres tests de
    abajo — «cero avisos» se lee igual que «filtrado correctamente».
    """
    assert _avisos(None) == ["performance.partitions", "survival.time_grid.horizon_periods"]


@pytest.mark.parametrize(
    ("steps", "esperado"),
    [
        ([], []),
        (["data"], []),
        (["data", "performance"], ["performance.partitions"]),
        (["data", "survival"], ["survival.time_grid.horizon_periods"]),
        (
            ["data", "performance", "survival"],
            ["performance.partitions", "survival.time_grid.horizon_periods"],
        ),
    ],
)
def test_solo_avisan_los_pasos_que_la_corrida_va_a_ejecutar(
    steps: list[str], esperado: list[str]
) -> None:
    """Cada paso excluido deja de avisar, y los incluidos siguen haciéndolo.

    Se mide en los DOS sentidos con la misma tabla: los casos que esperan lista vacía prueban el
    filtro, y los que esperan avisos prueban que no se llevó por delante lo que sí corre.
    """
    assert _avisos(steps) == esperado


def test_un_paso_excluido_tampoco_exige_sus_columnas() -> None:
    """El filtro alcanza a las COLUMNAS, no sólo a las invariantes.

    Si `survival` no corre, su `duration_col` no se abre: exigirla del archivo es el mismo aviso
    falso. Arreglar sólo la mitad de los requisitos habría dejado el defecto vivo en la otra.
    """
    cargar_configs_de_dominio()
    cfg = {
        **_BASE,
        "survival": {"input": {"duration_col": "columna_fantasma", "event_col": "target"}},
    }

    con_survival = nikodym.check_dataset(NikodymConfig.model_validate(cfg), _COLUMNAS)
    assert "columna_fantasma" in [m.declared for m in con_survival.mismatches]

    sin_survival = nikodym.check_dataset(
        NikodymConfig.model_validate({**cfg, "run": {"steps": ["data"]}}), _COLUMNAS
    )
    assert "columna_fantasma" not in [m.declared for m in sin_survival.mismatches]


def test_check_pipeline_y_check_dataset_dejan_de_contradecirse() -> None:
    """El síntoma que lo destapó: uno decía «cero pasos» y el otro avisaba sobre dos."""
    cargar_configs_de_dominio()
    modelo = NikodymConfig.model_validate({**_BASE, "run": {"steps": []}})

    assert nikodym.check_pipeline(modelo).steps == ()
    assert _avisos([]) == [], "no se puede avisar sobre un pipeline que no ejecuta nada"
