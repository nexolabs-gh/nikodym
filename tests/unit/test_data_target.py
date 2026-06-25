"""Tests de ``TargetDefinition`` (SDD-02 §4/§7): target, precedencia y mini-DSL."""

from __future__ import annotations

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from nikodym.core.audit import InMemoryAuditSink
from nikodym.core.exceptions import ConfigError, DataValidationError
from nikodym.data.config import (
    ExclusionRule,
    PerformanceWindow,
    Predicate,
    Rule,
    TargetConfig,
)
from nikodym.data.target import LabeledFrame, TargetDefinition


def _predicate(
    col: str,
    op: str,
    value: bool | int | float | str | tuple[bool | int | float | str, ...] | None = None,
) -> Predicate:
    """Construye un predicado válido en tests normales."""
    return Predicate(col=col, op=op, value=value)  # type: ignore[arg-type]


def _rule(*predicates: Predicate) -> Rule:
    """Construye una regla AND de predicados."""
    return Rule(all_of=predicates)


def _bad_rule() -> Rule:
    """Regla canónica de incumplimiento: mora máxima >= 90 días."""
    return _rule(_predicate("max_dpd_12m", ">=", 90))


def _indeterminate_rule() -> Rule:
    """Zona gris canónica: 30 <= mora máxima < 90 días."""
    return _rule(
        _predicate("max_dpd_12m", ">=", 30),
        _predicate("max_dpd_12m", "<", 90),
    )


def _fraud_exclusion() -> ExclusionRule:
    """Exclusión estructural por fraude."""
    return ExclusionRule(
        name="fraude",
        rule=_rule(_predicate("fraud_flag", "==", True)),
    )


def _never_exclusion() -> ExclusionRule:
    """Exclusión declarada sin observaciones afectadas."""
    return ExclusionRule(
        name="fallecido",
        rule=_rule(_predicate("estado", "==", "fallecido")),
    )


def _target_config() -> TargetConfig:
    """Config canónico de target para comportamiento."""
    return TargetConfig(
        bad_rule=_bad_rule(),
        indeterminate_rule=_indeterminate_rule(),
        exclusion_rules=(_fraud_exclusion(), _never_exclusion()),
    )


def _base_frame() -> pd.DataFrame:
    """Dataset mínimo con bueno, malo, indeterminado y excluido."""
    return pd.DataFrame(
        {
            "max_dpd_12m": [120, 0, 45, 120, 10],
            "fraud_flag": [False, False, False, True, False],
            "estado": ["activo", "activo", "activo", "activo", "activo"],
        },
        index=pd.Index(["op-1", "op-2", "op-3", "op-4", "op-5"], name="loan_id"),
    )


def _config_from_rule(rule: Rule) -> TargetConfig:
    """Construye ``TargetConfig`` saltando Pydantic cuando el test fuerza una regla inválida."""
    return TargetConfig.model_construct(
        target_col="target",
        bad_rule=rule,
        good_rule=None,
        indeterminate_rule=None,
        exclusion_rules=(),
        window=None,
    )


def test_from_config_conserva_target_config() -> None:
    """``from_config`` construye desde ``DataConfig.target`` / ``TargetConfig``."""
    cfg = _target_config()

    definition = TargetDefinition.from_config(cfg)

    assert definition.config is cfg


def test_apply_etiqueta_clases_summary_auditoria_y_no_muta_df_golden() -> None:
    """Etiqueta bueno/malo/indeterminado/excluido y resuelve malo+exclusión por precedencia."""
    df = _base_frame()
    original = df.copy(deep=True)
    audit = InMemoryAuditSink()

    labeled = TargetDefinition(_target_config()).apply(df, audit=audit)

    assert isinstance(labeled, LabeledFrame)
    assert labeled.target_col == "target"
    assert labeled.status_col == "label_status"
    assert str(labeled.frame["target"].dtype) == "Int8"
    assert str(labeled.frame["label_status"].dtype) == "category"
    assert labeled.frame["label_status"].astype(str).tolist() == [
        "malo",
        "bueno",
        "indeterminado",
        "excluido",
        "bueno",
    ]
    assert labeled.frame["target"].tolist() == [1, 0, pd.NA, pd.NA, 0]
    assert labeled.summary.class_counts == {
        "bueno": 2,
        "malo": 1,
        "indeterminado": 1,
        "excluido": 1,
    }
    assert labeled.summary.bad_rate == pytest.approx(1 / 3)
    assert labeled.summary.exclusions_by_reason == {"fraude": 1}
    assert labeled.summary.ambiguous_rows == 1
    assert [event.payload for event in audit.events] == [
        {
            "regla": "exclusion",
            "umbral": "fraude",
            "valor": 1,
            "accion": "marcar_excluido",
        },
        {
            "regla": "target_ambiguo",
            "umbral": "exclusion > indeterminado > malo > bueno",
            "valor": 1,
            "accion": "resolver_por_precedencia",
        },
    ]
    assert_frame_equal(df, original)


def test_invariante_target_no_nulo_solo_para_bueno_malo() -> None:
    """Cada fila tiene un estado único y ``target`` solo existe para buenos/malos."""
    labeled = TargetDefinition(_target_config()).apply(_base_frame())
    frame = labeled.frame

    assert frame["label_status"].notna().all()
    assert set(frame["label_status"].astype(str)) == {"bueno", "malo", "indeterminado", "excluido"}
    target_notna = frame["target"].notna()
    modelable = frame["label_status"].isin(["bueno", "malo"])

    assert target_notna.equals(modelable)


def test_ventana_incompleta_excluye_por_motivo_golden() -> None:
    """Una observación sin ventana madurada queda excluida por ``ventana_incompleta``."""
    df = pd.DataFrame(
        {
            "max_dpd_12m": [100, 0, 0],
            "observation_date": pd.to_datetime(["2023-01-01", "2023-01-01", "2024-06-01"]),
            "data_cutoff": pd.to_datetime(["2024-02-01", "2024-02-01", "2025-01-31"]),
        },
        index=pd.Index(["bad", "good", "censored"], name="loan_id"),
    )
    cfg = TargetConfig(
        bad_rule=_bad_rule(),
        window=PerformanceWindow(
            observation_date_col="observation_date",
            months=12,
            data_cutoff_col="data_cutoff",
        ),
    )
    audit = InMemoryAuditSink()

    labeled = TargetDefinition(cfg).apply(df, audit=audit)

    assert labeled.frame["label_status"].astype(str).tolist() == ["malo", "bueno", "excluido"]
    assert labeled.frame["target"].tolist() == [1, 0, pd.NA]
    assert labeled.summary.exclusions_by_reason == {"ventana_incompleta": 1}
    assert audit.events[0].payload == {
        "regla": "exclusion",
        "umbral": "ventana_incompleta",
        "valor": 1,
        "accion": "marcar_excluido",
    }


def test_columna_de_fecha_no_datetime_levanta_datavalidationerror() -> None:
    """La ventana exige columnas datetime antes de evaluar madurez."""
    df = pd.DataFrame(
        {
            "max_dpd_12m": [100, 0],
            "observation_date": ["2023-01-01", "2023-01-01"],
            "data_cutoff": pd.to_datetime(["2024-02-01", "2024-02-01"]),
        }
    )
    cfg = TargetConfig(
        bad_rule=_bad_rule(),
        window=PerformanceWindow(
            observation_date_col="observation_date",
            months=12,
            data_cutoff_col="data_cutoff",
        ),
    )

    with pytest.raises(DataValidationError, match="requiere columnas datetime"):
        TargetDefinition(cfg).apply(df)


def test_columna_de_fecha_inexistente_levanta_datavalidationerror() -> None:
    """Una columna de ventana ausente falla con error propio de datos."""
    df = pd.DataFrame(
        {
            "max_dpd_12m": [100, 0],
            "data_cutoff": pd.to_datetime(["2024-02-01", "2024-02-01"]),
        }
    )
    cfg = TargetConfig(
        bad_rule=_bad_rule(),
        window=PerformanceWindow(
            observation_date_col="observation_date",
            data_cutoff_col="data_cutoff",
        ),
    )

    with pytest.raises(DataValidationError, match="columna inexistente"):
        TargetDefinition(cfg).apply(df)


def test_clase_vacia_cero_malos_levanta_datavalidationerror() -> None:
    """Un target sin malos no es entrenable y falla temprano."""
    cfg = TargetConfig(bad_rule=_rule(_predicate("max_dpd_12m", ">=", 999)))

    with pytest.raises(DataValidationError, match=r"clase vacía.*malos=0"):
        TargetDefinition(cfg).apply(_base_frame())


def test_columna_inexistente_en_mini_dsl_levanta_configerror() -> None:
    """Una regla que referencia columna inexistente falla antes de construir máscaras."""
    cfg = TargetConfig(bad_rule=_rule(_predicate("mora_inexistente", ">=", 90)))

    with pytest.raises(ConfigError, match="columna inexistente"):
        TargetDefinition(cfg).apply(_base_frame())


def test_operador_fuera_de_allowlist_levanta_configerror() -> None:
    """El evaluador mantiene allowlist cerrada incluso si se salta la validación Pydantic."""
    predicate = Predicate.model_construct(col="max_dpd_12m", op="contains", value=90)
    cfg = _config_from_rule(Rule.model_construct(all_of=(predicate,), any_of=()))

    with pytest.raises(ConfigError, match="allowlist"):
        TargetDefinition(cfg).apply(_base_frame())


def test_regla_vacia_levanta_configerror() -> None:
    """Una ``Rule`` vacía forzada por ``model_construct`` falla en el evaluador."""
    cfg = _config_from_rule(Rule.model_construct(all_of=(), any_of=()))

    with pytest.raises(ConfigError, match="Regla de target vacía"):
        TargetDefinition(cfg).apply(_base_frame())


@pytest.mark.parametrize(
    ("rule", "match"),
    [
        (_rule(_predicate("max_dpd_12m", "in", 90)), "pertenencia"),
        (_rule(_predicate("max_dpd_12m", "in", ())), "tupla no vacía"),
        (_rule(_predicate("estado", "==", ("activo",))), "valor escalar"),
    ],
)
def test_value_incompatible_con_operador_levanta_configerror(rule: Rule, match: str) -> None:
    """``in``/``notin`` requieren tupla y comparadores escalares requieren escalar."""
    with pytest.raises(ConfigError, match=match):
        TargetDefinition(_config_from_rule(rule)).apply(_base_frame())


@pytest.mark.parametrize(
    ("df", "rule"),
    [
        (
            pd.DataFrame(
                {
                    "max_dpd_12m": [0, 100],
                    "fecha": pd.to_datetime(["2024-01-01", "2024-02-01"]),
                }
            ),
            _rule(_predicate("fecha", ">=", 90)),
        ),
        (
            pd.DataFrame({"max_dpd_12m": [0, 100], "flag": [False, True]}),
            _rule(_predicate("flag", ">=", 1)),
        ),
        (
            pd.DataFrame({"max_dpd_12m": [0, 100], "score": [0, 1]}),
            _rule(_predicate("score", "==", True)),
        ),
        (
            pd.DataFrame(
                {"max_dpd_12m": [0, 100], "segmento": pd.Series(["A", "B"], dtype="string")}
            ),
            _rule(_predicate("segmento", ">", "A")),
        ),
        (
            pd.DataFrame(
                {"max_dpd_12m": [0, 100], "segmento": pd.Series(["A", "B"], dtype="category")}
            ),
            _rule(_predicate("segmento", ">", "A")),
        ),
        (
            pd.DataFrame(
                {"max_dpd_12m": [0, 100], "segmento": pd.Series(["A", "B"], dtype="category")}
            ),
            _rule(_predicate("segmento", "==", 1)),
        ),
        (
            pd.DataFrame(
                {
                    "max_dpd_12m": [0, 100],
                    "duracion": pd.to_timedelta(["1 days", "2 days"]),
                }
            ),
            _rule(_predicate("duracion", ">=", 1)),
        ),
        (
            pd.DataFrame({"max_dpd_12m": [0, 100], "texto": pd.Series(["A", "B"], dtype="object")}),
            _rule(_predicate("texto", "==", 1)),
        ),
        (
            pd.DataFrame({"max_dpd_12m": [0, 100], "numero": pd.Series([1, 2], dtype="object")}),
            _rule(_predicate("numero", "==", "x")),
        ),
        (
            pd.DataFrame(
                {"max_dpd_12m": [0, 100], "flag_obj": pd.Series([False, True], dtype="object")}
            ),
            _rule(_predicate("flag_obj", "==", "true")),
        ),
        (
            pd.DataFrame({"max_dpd_12m": [0, 100], "mixto": pd.Series([1, "B"], dtype="object")}),
            _rule(_predicate("mixto", "==", 1)),
        ),
    ],
)
def test_dtypes_incompatibles_levantan_configerror_sin_warning(
    df: pd.DataFrame, rule: Rule
) -> None:
    """Comparaciones cross-dtype fallan con ``ConfigError`` antes de que pandas emita warnings."""
    with pytest.raises(ConfigError, match="Valor incompatible"):
        TargetDefinition(_config_from_rule(rule)).apply(df)


def test_mini_dsl_operadores_y_good_rule_con_golden_values() -> None:
    """El mini-DSL cubre operadores de la allowlist y respeta la precedencia documentada."""
    df = pd.DataFrame(
        {
            "num": [0, 1, 2, 4, 5, 2],
            "segmento": ["A", "B", "C", "D", "E", "B"],
            "nullable": [None, "x", None, "y", "z", "ok"],
        },
        index=pd.Index(["r1", "r2", "r3", "r4", "r5", "r6"], name="id"),
    )
    cfg = TargetConfig(
        bad_rule=Rule(
            any_of=(
                _predicate("num", ">=", 3),
                _predicate("segmento", "==", "C"),
            )
        ),
        good_rule=_rule(
            _predicate("segmento", "!=", "A"),
            _predicate("num", ">", 1),
        ),
        indeterminate_rule=Rule(
            any_of=(
                _predicate("num", "<", 1),
                _predicate("nullable", "isna"),
            )
        ),
        exclusion_rules=(
            ExclusionRule(
                name="segmento_no_observado",
                rule=Rule(any_of=(_predicate("segmento", "in", ("Z",)),)),
            ),
            ExclusionRule(
                name="notna_baja",
                rule=_rule(_predicate("nullable", "notna"), _predicate("num", "<=", 1)),
            ),
            ExclusionRule(
                name="segmento_fuera",
                rule=Rule(any_of=(_predicate("segmento", "notin", ("A", "B", "C", "D")),)),
            ),
        ),
    )

    labeled = TargetDefinition(cfg).apply(df)

    assert labeled.frame["label_status"].astype(str).tolist() == [
        "indeterminado",
        "excluido",
        "indeterminado",
        "malo",
        "excluido",
        "bueno",
    ]
    assert labeled.frame["target"].tolist() == [pd.NA, pd.NA, pd.NA, 1, pd.NA, 0]
    assert labeled.summary.class_counts == {
        "bueno": 1,
        "malo": 1,
        "indeterminado": 2,
        "excluido": 2,
    }
    assert labeled.summary.exclusions_by_reason == {"notna_baja": 1, "segmento_fuera": 1}
    assert labeled.summary.ambiguous_rows == 3


def test_columnas_object_numericas_y_bool_compatibles_sin_warning() -> None:
    """Columnas ``object`` homogéneas numéricas o booleanas se comparan de forma segura."""
    numeric_df = pd.DataFrame({"mora_obj": pd.Series([0, 90], dtype="object")})
    bool_df = pd.DataFrame({"flag_obj": pd.Series([False, True], dtype="object")})

    numeric = TargetDefinition(
        TargetConfig(bad_rule=_rule(_predicate("mora_obj", ">=", 90)))
    ).apply(numeric_df)
    boolean = TargetDefinition(
        TargetConfig(bad_rule=_rule(_predicate("flag_obj", "==", True)))
    ).apply(bool_df)

    assert numeric.frame["label_status"].astype(str).tolist() == ["bueno", "malo"]
    assert boolean.frame["label_status"].astype(str).tolist() == ["bueno", "malo"]


def test_columna_categorica_compatible_sin_warning() -> None:
    """Categorías con valor compatible se evalúan por igualdad sin warnings."""
    df = pd.DataFrame({"segmento": pd.Series(["A", "B"], dtype="category")})

    labeled = TargetDefinition(
        TargetConfig(bad_rule=_rule(_predicate("segmento", "==", "B")))
    ).apply(df)

    assert labeled.frame["label_status"].astype(str).tolist() == ["bueno", "malo"]


def test_columna_string_compatible_sin_warning() -> None:
    """Columnas ``string`` usan comparaciones textuales compatibles."""
    df = pd.DataFrame({"segmento": pd.Series(["A", "B"], dtype="string")})

    labeled = TargetDefinition(
        TargetConfig(bad_rule=_rule(_predicate("segmento", "==", "B")))
    ).apply(df)

    assert labeled.frame["label_status"].astype(str).tolist() == ["bueno", "malo"]


def test_columna_object_vacia_se_valida_y_no_excluye() -> None:
    """Una columna ``object`` sin observaciones no nulas no dispara incompatibilidad artificial."""
    df = pd.DataFrame(
        {
            "max_dpd_12m": [0, 100],
            "motivo": pd.Series([None, None], dtype="object"),
        }
    )
    cfg = TargetConfig(
        bad_rule=_rule(_predicate("max_dpd_12m", ">=", 90)),
        exclusion_rules=(
            ExclusionRule(name="motivo_vacio", rule=_rule(_predicate("motivo", "==", "x"))),
        ),
    )

    labeled = TargetDefinition(cfg).apply(df)

    assert labeled.frame["label_status"].astype(str).tolist() == ["bueno", "malo"]
    assert labeled.summary.exclusions_by_reason == {}


def test_colision_de_columnas_de_salida_levanta_datavalidationerror() -> None:
    """El etiquetado no sobrescribe columnas existentes del cliente."""
    df = _base_frame().assign(target=0)

    with pytest.raises(DataValidationError, match="sobrescribir"):
        TargetDefinition(_target_config()).apply(df)
