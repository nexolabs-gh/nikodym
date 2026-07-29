"""Gate de las invariantes previas (enmienda INVARIANTES-PREVIAS, D-INV-1…D-INV-9).

Un config puede contradecirse a sí mismo sin que ningún campo nombre una columna que falte:
`stability.temporal_axis` distinto de `none` sobre un dataset sin columna de período, `families`
vacío, comparaciones repetidas. El motor lo diagnostica **bien**, pero recién al llegar al paso: el
caso de origen moría en el 8 de 10 con `check_dataset` y `check_pipeline` los dos en verde.

Estos tests miden las dos cosas que hacen creíble la enmienda: que cada invariante se avise
**antes** de correr, y que la cobertura esté **declarada** en vez de callada (D-INV-7).
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from nikodym.core.config import NikodymConfig
from nikodym.core.config.schema import cargar_configs_de_dominio
from nikodym.core.dataset_check import METODO_REQUISITOS, check_dataset
from nikodym.data.config import TemporalSplitConfig
from nikodym.performance.config import PerformanceConfig
from nikodym.stability.config import TEMPORAL_CANDIDATE_NAMES, StabilityConfig
from nikodym.validation.config import ValidationConfig

#: Columnas de un dataset corriente **sin** ninguna candidata a período.
SIN_PERIODO = frozenset({"BAD", "LOAN", "DEBTINC"})


# ── el caso de origen, en sus tres sentidos ───────────────────────────────────────────────────
def test_eje_temporal_sin_columna_de_periodo_avisa() -> None:
    """El caso medido con HMEQ: eje activo, ninguna candidata en el dataset."""
    requisitos = StabilityConfig(temporal_axis="period").requisitos_incumplidos(SIN_PERIODO)

    assert [r.path for r in requisitos] == ["temporal_axis"]
    assert "período" in requisitos[0].message


def test_eje_temporal_con_columna_presente_no_avisa() -> None:
    """La dirección positiva, medida en vivo: con la columna, la corrida llega a `done`.

    Sin este test el gate anterior se satisface con un aviso que salta siempre, que sería peor que
    no avisar: entrena a ignorarlo.
    """
    columnas = SIN_PERIODO | {"period"}

    assert StabilityConfig(temporal_axis="period").requisitos_incumplidos(columnas) == ()


def test_eje_temporal_sin_saber_las_columnas_no_afirma_nada() -> None:
    """`None` significa «no se sabe», no «no hay» (D-INV-4).

    Es la regresión que importa: afirmar sin el dato reintroduce el falso positivo más caro, el
    mismo que costó el rediseño de la firma de `check_dataset` en `1.9.0`.
    """
    assert StabilityConfig(temporal_axis="period").requisitos_incumplidos(None) == ()


def test_eje_temporal_apagado_no_avisa() -> None:
    """Con el eje en `none` el motor ni busca la columna, así que no hay nada que exigir."""
    assert StabilityConfig(temporal_axis="none").requisitos_incumplidos(SIN_PERIODO) == ()


def test_columna_temporal_declarada_la_gobierna_el_preflight_de_columnas() -> None:
    """Con `temporal_column` fijada no se emite requisito: ya la vigila `column_role: input`.

    Duplicarlo daría dos avisos sobre el mismo campo, uno de ellos peor redactado.
    """
    cfg = StabilityConfig(temporal_axis="period", temporal_column="mi_periodo")

    assert cfg.requisitos_incumplidos(SIN_PERIODO) == ()


def test_columna_temporal_ambigua_avisa_y_nombra_las_candidatas() -> None:
    """Dos candidatas: el motor se niega a elegir, y el aviso dice entre cuáles."""
    requisitos = StabilityConfig(temporal_axis="period").requisitos_incumplidos(
        SIN_PERIODO | {"period", "cohorte"}
    )

    assert [r.path for r in requisitos] == ["temporal_column"]
    assert "«cohorte»" in requisitos[0].message
    assert "«period»" in requisitos[0].message


def test_los_nombres_candidatos_son_los_mismos_que_mira_el_motor() -> None:
    """D-INV-9: una constante compartida vive en un sitio, o el aviso acaba mintiendo.

    Estaba triplicada (`evaluator.py`, `step.py` y la que necesitaba el aviso). El test mira las
    dos referencias que quedan y exige que sean el mismo objeto, no dos listas iguales hoy.
    """
    from nikodym.stability import evaluator, step

    assert evaluator.TEMPORAL_CANDIDATE_NAMES is TEMPORAL_CANDIDATE_NAMES
    assert step.TEMPORAL_CANDIDATE_NAMES is TEMPORAL_CANDIDATE_NAMES


# ── las demás invariantes implementadas ───────────────────────────────────────────────────────
def test_comparaciones_repetidas_avisan() -> None:
    cfg = StabilityConfig(comparisons=("dev_vs_holdout", "dev_vs_holdout"))
    requisitos = cfg.requisitos_incumplidos(SIN_PERIODO)

    assert "comparisons" in [r.path for r in requisitos]


def test_particiones_de_desempeno_repetidas_avisan() -> None:
    cfg = PerformanceConfig(partitions=("desarrollo", "desarrollo"))

    assert [r.path for r in cfg.requisitos_incumplidos(None)] == ["partitions"]


def test_familias_de_validacion_vacias_avisan() -> None:
    """`validation` corre PENÚLTIMO: sin esto, un `if` de una línea cobra la corrida entera."""
    assert [r.path for r in ValidationConfig(families=()).requisitos_incumplidos(None)] == [
        "families"
    ]


def test_familias_de_validacion_pobladas_no_avisan() -> None:
    assert ValidationConfig().requisitos_incumplidos(None) == ()


def test_fecha_de_corte_oot_ilegible_avisa() -> None:
    """`oot_from` es un `str` libre y sólo se parsea dentro del PRIMER paso del pipeline."""
    cfg = TemporalSplitConfig(date_col="fecha", oot_from="no-es-fecha")

    assert [r.path for r in cfg.requisitos_incumplidos(None)] == ["oot_from"]


def test_fecha_de_corte_oot_valida_no_avisa() -> None:
    cfg = TemporalSplitConfig(date_col="fecha", oot_from="2024-07-01")

    assert cfg.requisitos_incumplidos(None) == ()


@pytest.mark.parametrize("vacia", ["", "   ", "nan"])
def test_fecha_de_corte_oot_vacia_avisa_aunque_pandas_no_levante(vacia: str) -> None:
    """El caso más probable de todos se iba en silencio: `pandas` devuelve `NaT` sin levantar.

    Hallado por la auditoría previa a `1.10.0`: atrapar `ValueError` no basta, porque
    `pd.Timestamp("")` y `pd.Timestamp("nan")` **no** levantan — devuelven `NaT`—, así que un
    `oot_from` en blanco pasaba el chequeo cuya razón de existir es justo esa fecha.
    """
    cfg = TemporalSplitConfig(date_col="fecha", oot_from=vacia)

    requisitos = cfg.requisitos_incumplidos(None)

    assert [r.path for r in requisitos] == ["oot_from"]
    # Copy público: un valor en blanco no se cita entre comillas, se nombra la carencia.
    if vacia.strip() == "":
        assert requisitos[0].message.startswith("Falta la fecha desde la que empieza el OOT")
        assert "«" not in requisitos[0].message


# ── la integración: lo que ve quien llama a la superficie pública ─────────────────────────────
def test_check_dataset_publica_el_requisito_con_su_ruta_absoluta() -> None:
    """D-INV-5: el dominio declara rutas relativas y el recorrido les pone su prefijo.

    Sin la ruta absoluta el formulario no puede saltar al campo, que es lo que hace útil al aviso.
    """
    cargar_configs_de_dominio()
    config = NikodymConfig.model_validate(
        {"name": "t", "stability": StabilityConfig(temporal_axis="period").model_dump()}
    )

    veredicto = check_dataset(config, sorted(SIN_PERIODO))

    requisitos = [m for m in veredicto.mismatches if m.kind == "unmet_requirement"]
    assert [m.path for m in requisitos] == ["stability.temporal_axis"]
    assert veredicto.compatible is False


def test_un_requisito_incumplido_no_es_una_columna_que_falte() -> None:
    """Los dos tipos conviven en el mismo canal sin confundirse (D-INV-2)."""
    cargar_configs_de_dominio()
    config = NikodymConfig.model_validate(
        {"name": "t", "stability": StabilityConfig(temporal_axis="period").model_dump()}
    )

    veredicto = check_dataset(config, sorted(SIN_PERIODO))

    tipos = {m.kind for m in veredicto.mismatches}
    assert "unmet_requirement" in tipos
    assert "missing_column" not in tipos


# ── cobertura declarada (D-INV-7) ─────────────────────────────────────────────────────────────
#: Secciones del formulario SIN invariantes previas declaradas, cada una con su razón.
#:
#: Una lista corta y sin explicación se lee como cobertura total (D-PRE-4). Lo que dice esta tabla
#: es que se miró cada sección y se decidió, no que se olvidaron.
EXENTAS: dict[str, str] = {
    # --- camino F1: miradas una por una en el censo del 2026-07-29 ---
    "binning": "su invariante ('no queda candidata') depende de los dtypes, no sólo de los nombres",
    "selection": "sus 4 campos son `derived`: la candidatura la produce binning al correr",
    "model": "sus overrides se contrastan contra lo que sobrevivió a selection, que aún no existe",
    "scorecard": "sin invariantes medidas: el censo del 2026-07-29 no encontró ninguna",
    "calibration": "sus invariantes YA están en su `model_validator`, que es el sitio correcto",
    "report": "su invariante (`required_sections`) es ENTRE secciones, no de una: D-INV-8",
    "eda": "no impone invariantes propias sobre el dataset; su config es de presentación",
    # --- fuera del alcance F1 del preflight (D-PRE-4): ampliarlo lo decide producto ---
    "survival": "fuera del alcance F1 del preflight (D-PRE-4)",
    "provisioning": "fuera del alcance F1 del preflight (D-PRE-4)",
    "provisioning_cmf": "fuera del alcance F1 del preflight (D-PRE-4)",
    "provisioning_ifrs9": "fuera del alcance F1 del preflight (D-PRE-4)",
    "provisioning_internal": "fuera del alcance F1 del preflight (D-PRE-4)",
    "markov": "fuera del alcance F1 del preflight (D-PRE-4)",
    "forward": "fuera del alcance F1 del preflight (D-PRE-4)",
    "stress": "fuera del alcance F1 del preflight (D-PRE-4)",
    "ml": "fuera del alcance F1 del preflight (D-PRE-4)",
    "tuning": "fuera del alcance F1 del preflight (D-PRE-4)",
    "explain": "fuera del alcance F1 del preflight (D-PRE-4)",
}


def _secciones_con_protocolo(seccion: type[BaseModel]) -> bool:
    """¿La sección —o alguno de sus sub-modelos— declara el protocolo?"""
    vistos: set[type[BaseModel]] = set()
    pendientes: list[type[BaseModel]] = [seccion]
    while pendientes:
        modelo = pendientes.pop()
        if modelo in vistos:
            continue
        vistos.add(modelo)
        if callable(getattr(modelo, METODO_REQUISITOS, None)):
            return True
        for info in modelo.model_fields.values():
            for arg in (info.annotation, *getattr(info.annotation, "__args__", ())):
                if isinstance(arg, type) and issubclass(arg, BaseModel):
                    pendientes.append(arg)
                for anidado in getattr(arg, "__args__", ()):
                    if isinstance(anidado, type) and issubclass(anidado, BaseModel):
                        pendientes.append(anidado)
    return False


def test_cada_seccion_declara_su_politica_de_invariantes() -> None:
    """Toda sección de dominio implementa el protocolo o está exenta CON SU RAZÓN (D-INV-7).

    El gate mide contra el registro real de secciones —no contra una lista escrita al lado—, así
    que una sección nueva entra aquí sola y obliga a decidir.
    """
    secciones = cargar_configs_de_dominio()
    sin_politica = [
        nombre
        for nombre, modelo in sorted(secciones.items())
        if not _secciones_con_protocolo(modelo) and nombre not in EXENTAS
    ]

    assert not sin_politica, (
        f"Secciones sin política de invariantes previas: {sin_politica}. Implementa "
        f"`{METODO_REQUISITOS}(columnas)` en su config —lo que su motor exige y hoy sólo "
        "se descubre corriendo— o decláralas en `EXENTAS` **con la razón**. Una sección sin "
        "decisión escrita se lee como cobertura, y es justo lo que esta enmienda vino a evitar."
    )


def test_ninguna_exencion_sobra() -> None:
    """Una exención que ya no aplica es una mentira que envejece sola.

    Si una sección exenta implementa el protocolo, o deja de existir, la fila debe salir.
    """
    secciones = cargar_configs_de_dominio()
    sobrantes = [
        nombre
        for nombre in EXENTAS
        if nombre not in secciones or _secciones_con_protocolo(secciones[nombre])
    ]

    assert not sobrantes, (
        f"Exenciones que ya no corresponden: {sobrantes}. O la sección desapareció, o ya declara "
        f"sus invariantes: en ambos casos, saca su fila de `EXENTAS`."
    )


@pytest.mark.parametrize(
    "config",
    [
        StabilityConfig(),
        PerformanceConfig(),
        ValidationConfig(),
        TemporalSplitConfig(date_col="fecha", oot_from="2024-07-01"),
    ],
    ids=["stability", "performance", "validation", "temporal_split"],
)
def test_el_protocolo_acepta_columnas_desconocidas(config: BaseModel) -> None:
    """Toda implementación tolera `columnas=None` sin reventar (contrato de D-INV-4)."""
    requisitos = config.requisitos_incumplidos(None)  # type: ignore[attr-defined]

    assert isinstance(requisitos, tuple)
