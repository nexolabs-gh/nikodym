"""Gate de CRP-6: ``fail_on_falta_dato`` significa lo mismo en todas las capas.

El contrato de resolución de parámetros define el flag con una sola pregunta —*¿una marca declarada
emitida por esta capa detiene la corrida?*— y hasta el 2026-07-25 el paquete tenía **siete
definiciones**, una de ellas no-op y otra gobernando algo que no es una marca. Este archivo ejecuta
la semántica en vez de describirla, siguiendo `_ENMIENDA-CRP6-FLAG.md` (D-CRP6-1…D-CRP6-8).

La decisión que hace posible el gate es **D-CRP6-2**, y no es cosmética: sin ella el flag es
inaplicable en IFRS 9. Una marca declarada es

**gobernable**
    si existe alguna entrada válida con la que la capa **no** la emita. El flag decide si detiene.

**estructural**
    si el motor la emite en toda corrida por una capacidad diferida propia
    (``FALTA-DATO-IFRS-4``: el perfil EAD(t) está diferido a CT-3). Se registra siempre y **nunca**
    detiene, porque el usuario no tiene ninguna acción que la evite: abortar por ella no sería
    fail-fast, sería dejar el motor inservible con su propio valor por defecto.

Con el **bloque B** (`survival`, D-CRP6-4) el gate cubre las **siete** capas y el criterio 1 de §5
pasa. La advertencia de cobertura parcial que este docstring llevaba desde el bloque A se retiró
junto con el no-op que la motivaba.

⚠️ **`survival` no declara ninguna marca estructural, y eso se midió, no se supuso.** La analogía
con IFRS 9 invita a copiar una lista de estructurales; aquí sería falsa. ``SUR-1`` y ``SUR-3`` se
comprobaron **en los dos sentidos** —aparecen sin la declaración y desaparecen con ella—, así que
las tres marcas de la capa son gobernables y la lista va vacía.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import pytest

from nikodym.core.config import NikodymConfig
from nikodym.core.markers import governable_warnings, is_declared_warning
from nikodym.core.study import Study
from nikodym.forward.config import ForwardConfig
from nikodym.forward.exceptions import ForwardScenarioError
from nikodym.provisioning.ifrs9 import IfrsProvisioningConfig, IfrsProvisioningEngine
from nikodym.provisioning.ifrs9.config import (
    IfrsEadConfig,
    IfrsLgdConfig,
    IfrsPdConfig,
    IfrsScenarioConfig,
)
from nikodym.provisioning.ifrs9.exceptions import IfrsConfigError, IfrsFaltaDatoError
from nikodym.survival.config import SurvivalConfig
from nikodym.survival.exceptions import SurvivalFaltaDatoError
from nikodym.validation.config import ValidationConfig
from nikodym.validation.exceptions import ValidationConfigError

# ───────────────────────────────── fixtures mínimas de IFRS 9 ─────────────────────────────────


def _frame() -> pd.DataFrame:
    """Una operación con la EAD **entregada** por la institución: nada que el motor invente."""
    return pd.DataFrame(
        [
            {
                "portfolio": "retail",
                "ead": 1000.0,
                "lgd": 0.5,
                "eir": 0.0,
                "days_past_due": 0,
                "is_default": False,
            }
        ],
        index=pd.Index(["op1"], name="loan_id"),
    )


def _ts(*, with_lgd: bool = False) -> pd.DataFrame:
    """Term-structure tidy mínima; con ``with_lgd`` trae la LGD de forward que IFRS 9 descarta.

    **Dos** períodos, no uno, y la unidad declarada: ambas cosas son para que la curva no dispare
    los avisos de D-HOR-0, que son ajenos a lo que este archivo prueba. Con un solo período el
    horizonte 12m (``horizon_12m_periods=1``) alcanzaría todo el soporte y ``FALTA-DATO-IFRS-8``
    —gobernable— detendría las corridas con el flag en ``True``, que es justo el escenario que estos
    tests necesitan ver terminar.
    """
    data: dict[str, Any] = {
        "row_id": ["op1", "op1"],
        "segment": ["retail", "retail"],
        "partition": ["train", "train"],
        "period": [1, 2],
        "time_value": [1.0, 2.0],
        "time_unit": ["year", "year"],
        "hazard": [0.02, 0.02],
        "survival": [0.98, 0.9604],
        "pd_marginal": [0.02, 0.0196],
        "pd_cumulative": [0.02, 0.0396],
        "method": ["kaplan_meier", "kaplan_meier"],
        "pd_source": ["survival", "survival"],
        "scenario": [None, None],
    }
    if with_lgd:
        data["lgd"] = [0.45, 0.45]
    return pd.DataFrame(data)


def _config(**overrides: Any) -> IfrsProvisioningConfig:
    """Config IFRS 9 mínimo y ejecutable, con la EAD provista y sin ajuste PIT."""
    base: dict[str, Any] = {
        "portfolio_col": "portfolio",
        "pd": IfrsPdConfig(
            term_structure_source="survival", pit_mode="ttc_only", horizon_12m_periods=1
        ),
        "lgd": IfrsLgdConfig(method="provided"),
        "ead": IfrsEadConfig(method="provided"),
        "scenarios": IfrsScenarioConfig(source="single"),
    }
    base.update(overrides)
    return IfrsProvisioningConfig(**base)


def _calculate(cfg: IfrsProvisioningConfig, ts: pd.DataFrame) -> Any:
    return IfrsProvisioningEngine.from_config(cfg).calculate(
        _frame(), term_structure=ts, as_of_date="2026-01-31"
    )


# ───────────────────────── D-CRP6-2: gobernable vs estructural ─────────────────────────


def test_marca_estructural_no_detiene_la_corrida() -> None:
    """``FALTA-DATO-IFRS-4`` se emite en toda corrida: con el flag en True **igual** termina.

    Es el criterio 2 de §5 de la enmienda y la razón de ser de D-CRP6-2. Medido antes de decidir:
    con ``method='provided'`` —la institución entrega la EAD real— la corrida más limpia posible
    emite igualmente el aviso, porque declara que el perfil EAD(t) está diferido a CT-3. Conectar el
    flag sin distinguir habría abortado **todo** IFRS 9 con su default y en los tres presets.
    """
    result = _calculate(_config(fail_on_falta_dato=True), _ts())

    assert "FALTA-DATO-IFRS-4" in result.card.falta_dato
    assert result.card.n_rows == 1


def test_marca_gobernable_detiene_con_el_flag_en_true() -> None:
    """``FALTA-DATO-IFRS-6`` sí depende de la entrada, así que el flag la gobierna.

    Sólo aparece si la term-structure trae la LGD de forward, que IFRS 9 no consume en v1
    (``engine.py`` ``_ts_lgd_present``). Existe una entrada válida sin ella → es gobernable.
    """
    with pytest.raises(IfrsFaltaDatoError, match="FALTA-DATO-IFRS-6"):
        _calculate(_config(fail_on_falta_dato=True), _ts(with_lgd=True))


def test_marca_gobernable_queda_registrada_con_el_flag_en_false() -> None:
    """Con ``False`` la misma marca no detiene: queda en el resultado y la corrida termina."""
    result = _calculate(_config(fail_on_falta_dato=False), _ts(with_lgd=True))

    assert "FALTA-DATO-IFRS-6" in result.card.falta_dato
    assert "FALTA-DATO-IFRS-4" in result.card.falta_dato


def test_governable_warnings_separa_por_el_criterio_declarado() -> None:
    """El helper transversal implementa D-CRP6-2 y no lo deja a criterio de cada capa."""
    codigos = ("FALTA-DATO-IFRS-4", "FALTA-DATO-IFRS-6", "ead_floored_limit_below_drawn")

    gobernables = governable_warnings(codigos, structural=("FALTA-DATO-IFRS-4",))

    # El estructural queda fuera; el que no es aviso declarado tampoco entra (lo marcará CRP-4).
    assert gobernables == ("FALTA-DATO-IFRS-6",)
    assert not is_declared_warning("ead_floored_limit_below_drawn")


# ───────────────── D-CRP6-3: el chequeo PIT de IFRS 9 es incondicional ─────────────────


def test_chequeo_pit_no_depende_del_flag() -> None:
    """Un config PIT inconsistente falla al validarse, con el flag en **cualquier** valor.

    Antes, ``fail_on_falta_dato=False`` dejaba construir el config y el fallo reaparecía dentro de
    ``_apply_vasicek``, a mitad del cálculo. No era una ruta degradada —no existe ninguna para
    ``rho``—: era exactamente la validación tardía que CRP-5 prohíbe.
    """
    for flag in (True, False):
        with pytest.raises(IfrsConfigError, match="rho"):
            _config(
                pd=IfrsPdConfig(
                    term_structure_source="survival",
                    pit_mode="apply_vasicek",
                    rho=None,
                    systemic_factor_col="Z",
                    horizon_12m_periods=1,
                ),
                fail_on_falta_dato=flag,
            )


# ───────────────── D-CRP6-5: `forward` pierde el AND con el segundo flag ─────────────────


def _forward_config(**overrides: Any) -> ForwardConfig:
    """Config de forward con un ``adverse`` sin trayectoria macro ni shocks: la carencia FWD-1."""
    data: dict[str, Any] = {
        "input": {
            "macro_source": {"type": "dataframe", "variable_cols": ("unemployment", "gdp")},
            "pd_basis_assumption": "pit",
        },
        "satellite": {"factor_cols": ("unemployment",)},
        "scenarios": {
            "scenarios": (
                {"name": "base", "weight": 0.60},
                {"name": "adverse", "weight": 0.30},
                {"name": "severe", "weight": 0.10, "shocks": {"unemployment": 2.0}},
            )
        },
    }
    data.update(overrides)
    return ForwardConfig.model_validate(data)


def test_forward_no_deja_que_un_segundo_flag_apague_al_primero() -> None:
    """Con ``fail_on_falta_dato=True``, la carencia detiene aunque el otro flag esté en False.

    El AND anterior era apagado silencioso: el usuario dejaba el flag principal en True y la
    carencia no lo detenía, sin que nada se lo dijera.
    """
    with (
        pytest.warns(DeprecationWarning, match="DEPRECADO"),
        pytest.raises(ForwardScenarioError, match="DATO-INSTITUCIONAL-FWD-1"),
    ):
        _forward_config(
            fail_on_falta_dato=True,
            validation={"fail_on_missing_scenario_paths": False},
        )


def test_forward_avisa_del_retiro_solo_cuando_el_flag_llega_en_false() -> None:
    """El aviso de deprecación se emite por el valor que cambia de efecto, no por el campo.

    En ``True`` el comportamiento es idéntico al anterior, así que avisar sería ruido en cada
    corrida. En ``False`` el usuario dependía de apagar la comprobación y ya no la apaga: tiene que
    enterarse.
    """
    with pytest.warns(DeprecationWarning, match="fail_on_missing_scenario_paths"):
        _forward_config(
            fail_on_falta_dato=False,
            validation={"fail_on_missing_scenario_paths": False},
        )

    import warnings as _warnings

    with _warnings.catch_warnings():
        _warnings.simplefilter("error")
        _forward_config(
            fail_on_falta_dato=False,
            validation={"fail_on_missing_scenario_paths": True},
        )


def test_forward_respeta_el_flag_en_false() -> None:
    """Con ``False`` el config construye: la carencia se registrará, no detiene."""
    cfg = _forward_config(fail_on_falta_dato=False)

    assert cfg.fail_on_falta_dato is False


# ───────────────── D-CRP6-6: `validation` nombra la marca que gobierna ─────────────────


def test_validation_nombra_su_marca_declarada() -> None:
    """El mensaje declara el código, como sus seis pares: si no, el audit trail no lo registra."""
    with pytest.raises(ValidationConfigError) as excinfo:
        ValidationConfig(families=["backtesting"], backtesting={"enabled": False})

    assert is_declared_warning(_primer_codigo(str(excinfo.value)))


def _primer_codigo(mensaje: str) -> str:
    """Extrae el primer token del mensaje, donde el contrato pone el código de la marca."""
    return mensaje.split(":", 1)[0].strip()


# ───────────────── D-CRP6-4: `survival` deja de ser un campo no-op ─────────────────


def _survival_frame() -> pd.DataFrame:
    """Libro mínimo con eventos y censura: nada degenerado que emita ``SUR-2`` de rebote."""
    duraciones = [1.0, 2.0, 3.0, 4.0, 5.0] * 8
    eventos = [1, 0, 1, 0, 1] * 8
    return pd.DataFrame(
        {"duration": duraciones, "event": eventos},
        index=pd.Index([f"op{i}" for i in range(len(duraciones))], name="loan_id"),
    )


def _survival_config(
    *, fail_on_falta_dato: bool, confidence_level: float | None, horizon_periods: int | None = 3
) -> SurvivalConfig:
    """Config Kaplan-Meier standalone; ``confidence_level=None`` es la carencia ``SUR-3``."""
    return SurvivalConfig.model_validate(
        {
            "method": "kaplan_meier",
            "input": {"duration_col": "duration", "event_col": "event", "pd_source": "none"},
            "time_grid": {
                "time_unit": "year",
                "horizon_periods": horizon_periods,
                "evaluation_times": [],
            },
            "kaplan_meier": {
                "confidence_level": confidence_level,
                "confidence_transform": None if confidence_level is None else "loglog",
            },
            "discrete_hazard": {"pd_role": "none"},
            "fail_on_falta_dato": fail_on_falta_dato,
        }
    )


def _run_survival(cfg: SurvivalConfig) -> Any:
    """Corre la cadena ``data → survival`` y devuelve el resultado publicado."""
    study = Study(NikodymConfig(survival=cfg))
    study.artifacts.set("data", "frame", _survival_frame())
    study.run(steps=["survival"])
    return study.artifacts.get("survival", "result")


def test_survival_marca_gobernable_detiene_con_el_flag_en_true() -> None:
    """La carencia ``SUR-3`` detiene la corrida, que es lo que el flag venía prometiendo.

    Hasta el bloque B este campo era un **no-op**: la propia enmienda lo condenaba y el config lo
    admitía por escrito (*"campo reservado: hoy no altera la corrida"*). Un flag de gobernanza que
    no gobierna es peor que no tenerlo — el usuario cree que su corrida está protegida.
    """
    with pytest.raises(SurvivalFaltaDatoError, match="DATO-INSTITUCIONAL-SUR-3"):
        _run_survival(_survival_config(fail_on_falta_dato=True, confidence_level=None))


def test_survival_marca_gobernable_queda_registrada_con_el_flag_en_false() -> None:
    """Con ``False`` la misma carencia no detiene: viaja en la card y la corrida termina."""
    result = _run_survival(_survival_config(fail_on_falta_dato=False, confidence_level=None))

    assert "DATO-INSTITUCIONAL-SUR-3" in result.card.falta_dato


def test_survival_sin_carencia_no_detiene_aunque_el_flag_este_en_true() -> None:
    """Declarado el intervalo, no hay marca que gobernar: el flag en ``True`` no estorba.

    Es la mitad que faltaba para probar que ``SUR-3`` es **gobernable** y no estructural: existe
    una entrada válida con la que la capa no la emite. Sin este sentido, el criterio de D-CRP6-2
    quedaría afirmado y no medido.
    """
    result = _run_survival(_survival_config(fail_on_falta_dato=True, confidence_level=0.95))

    assert result.card.falta_dato == ()


def test_survival_gobierna_la_carencia_de_grilla_del_step() -> None:
    """``SUR-1`` la emite el step, no el modelo, y el flag la gobierna igual.

    Importa porque los cuatro emisores de ``SUR-1`` (``kaplan_meier``, ``cox_aft``,
    ``discrete_hazard`` y el propio ``step``) desembocan en un **único** punto de decisión. Si el
    gate se hubiera puesto dentro de un motor, esta carencia se habría escapado.
    """
    with pytest.raises(SurvivalFaltaDatoError, match="DATO-INSTITUCIONAL-SUR-1"):
        _run_survival(
            _survival_config(fail_on_falta_dato=True, confidence_level=0.95, horizon_periods=None)
        )
