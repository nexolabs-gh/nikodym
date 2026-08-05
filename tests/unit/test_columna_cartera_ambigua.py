"""D-AMB: un archivo con DOS columnas de cartera no elige una en silencio.

🔴 El defecto que abre esta enmienda no era un error: era una **cifra distinta sin rastro**.
D-JUR-8 movió el default de ``provisioning_internal.portfolio_col`` de ``"cmf_portfolio"`` a
``"portfolio"``. Si el archivo trae sólo el nombre antiguo, la corrida muere con un error legible.
Si trae **los dos**, la agrupación cambia y la corrida llega a ``ok`` con cero errores y cero
avisos — medido en la auditoría previa a `1.11.0`: 20 grupos y 840.182,29 pasan a 10 grupos y
839.451,51.

Y ``check_dataset`` daba ``compatible=True``, correctamente: la columna que el config nombra existe
de verdad. No estaba fallando; contestaba bien a **otra** pregunta.

⚠️ El caso no es de laboratorio: ``"portfolio"`` es también el default de
``provisioning_ifrs9.portfolio_col``, así que quien corre IFRS 9 **y** provisión interna sobre un
mismo panel tiene las dos columnas por construcción.

Las dos capas de D-AMB se prueban **por separado y por su puerta pública**, porque cubren rutas
distintas: ``check_dataset`` no lo llama quien usa la librería por código, y la card no la lee quien
sólo hace el preflight.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Final

import pandas as pd

import nikodym
from nikodym.core.config import NikodymConfig
from nikodym.core.config.hashing import config_hash
from nikodym.core.config.schema import cargar_configs_de_dominio
from nikodym.provisioning.internal.config import InternalProvisioningConfig
from nikodym.provisioning.internal.engine import InternalProvisioningEngine

AS_OF: Final = "2026-01-31"
_COLUMNAS_AMBIGUAS: Final = frozenset({"portfolio", "cmf_portfolio"})


# ─────────────────── capa (a): el preflight, por su puerta pública ───────────────────


def _mismatches_de_ambiguedad(seccion: dict[str, Any], columnas: list[str]) -> list[Any]:
    """Corre ``nikodym.check_dataset`` de verdad y filtra los avisos de invariante.

    🔴 Va por la **puerta pública** a propósito. Llamar ``requisitos_incumplidos`` a mano probaría
    que el método funciona y no que alguien lo llame: este repo ya se comió un arreglo que pasaba
    sus tests con el defecto vivo por la puerta pública. Y la sección tiene que estar **tipada**
    para que el recorrido pueda preguntarle —el estado opaco es el default y se salta en silencio—,
    de ahí el ``cargar_configs_de_dominio()``.
    """
    cargar_configs_de_dominio()
    config = NikodymConfig.model_validate({"name": "amb", "provisioning_internal": seccion})
    resultado = nikodym.check_dataset(config, columnas)
    return [m for m in resultado.mismatches if m.kind == "unmet_requirement"]


_SECCION_MINIMA: Final = {
    "pd_column": "pd",
    "exposure_col": "exposure",
    "as_of_date_col": "as_of_date",
}
_COLUMNAS_CON_AMBAS: Final = ["portfolio", "cmf_portfolio", "exposure", "pd", "as_of_date"]


def test_dos_columnas_de_cartera_sin_elegir_avisan_antes_de_correr() -> None:
    """El caso de origen: ambas columnas presentes y ``portfolio_col`` en su valor de fábrica."""
    avisos = _mismatches_de_ambiguedad(_SECCION_MINIMA, _COLUMNAS_CON_AMBAS)

    assert len(avisos) == 1, "la ambigüedad de la columna de cartera no llegó al preflight"
    aviso = avisos[0]
    assert aviso.path == "provisioning_internal.portfolio_col", (
        "la ruta debe ser absoluta para que el formulario pueda saltar al campo (D-INV-5)"
    )
    # El mensaje nombra LAS DOS columnas y la salida, no sólo el problema (D-AMB-3/D-INV-6).
    assert "portfolio" in aviso.message and "cmf_portfolio" in aviso.message
    # Copy público: ni códigos internos ni jurisdicción. `cmf_portfolio` aparece como el nombre de
    # una columna del archivo del usuario, nunca como una norma.
    for prohibido in ("FALTA-DATO", "DATO-INSTITUCIONAL", "CMF", "Chile", "B-1", "Circular"):
        assert prohibido not in aviso.message, (
            f"el aviso del motor NEUTRO nombra {prohibido!r} en copy público"
        )


def test_control_negativo_quien_declaro_la_columna_no_recibe_aviso() -> None:
    """Primera mitad del control: declarar es decidir, y avisar sería el aviso que se ignora.

    Sin esta condición el aviso saltaría en toda corrida con las dos columnas, incluida la de quien
    ya eligió — y un aviso que se dispara de más se aprende a ignorar, que es como se pierde el que
    sí importa.
    """
    assert (
        _mismatches_de_ambiguedad(
            {**_SECCION_MINIMA, "portfolio_col": "portfolio"}, _COLUMNAS_CON_AMBAS
        )
        == []
    )
    # Y también si eligió explícitamente la ANTIGUA: sigue siendo una elección suya.
    assert (
        _mismatches_de_ambiguedad(
            {**_SECCION_MINIMA, "portfolio_col": "cmf_portfolio"}, _COLUMNAS_CON_AMBAS
        )
        == []
    )


def test_control_negativo_una_sola_columna_no_es_ambigua() -> None:
    """Segunda mitad: con una sola candidata no hay nada que elegir.

    El archivo que trae **sólo** el nombre antiguo tampoco entra aquí: ése muere con
    ``InternalInputError`` nombrando la columna que falta, que es ruidoso y está bien así.
    """
    assert _mismatches_de_ambiguedad(_SECCION_MINIMA, ["portfolio", "exposure", "pd"]) == []
    assert _mismatches_de_ambiguedad(_SECCION_MINIMA, ["cmf_portfolio", "exposure", "pd"]) == []


def test_sin_los_nombres_de_columna_no_se_afirma_nada() -> None:
    """``None`` significa «no se sabe», no «no hay» (D-INV-4)."""
    assert InternalProvisioningConfig().requisitos_incumplidos(None) == ()


def test_el_aviso_no_mueve_el_config_hash_de_ningun_preset() -> None:
    """Criterio 2 de la enmienda: es aditivo y no toca la identidad de ninguna corrida.

    Los tres primeros hashes son los que la auditoría de `1.11.0` midió **idénticos** en `1.10.0` y
    en HEAD; enumerarlos a mano es lo que convierte este test en un oráculo y no en un espejo.
    """
    cargar_configs_de_dominio()
    from nikodym.ui.presets import get_preset

    esperados = {
        "f1-estandar-consumo": "ec10eb43",
        "f3-provisiones-consumo": "857b06ee",
        "f4-ifrs9-retail": "013e69dc",
    }
    for preset_id, prefijo in esperados.items():
        config = NikodymConfig.model_validate(get_preset(preset_id)["config"])
        assert config_hash(config).startswith(prefijo), (
            f"el preset {preset_id} movió su config_hash: la enmienda debía ser hash-neutra"
        )


# ─────────────────────────── capa (b): la card, para la ruta por código ───────────────────────────


def _frame_con(columnas_cartera: tuple[str, ...]) -> pd.DataFrame:
    """Cartera mínima que trae una o varias columnas candidatas a cartera."""
    filas = {
        "as_of_date": [AS_OF, AS_OF],
        "exposure_amount": [Decimal("1000000"), Decimal("2000000")],
        "lgd": [0.5, 0.4],
        "grupo": ["A", "B"],
    }
    for columna in columnas_cartera:
        filas[columna] = ["consumer", "consumer"]
    return pd.DataFrame(filas, index=pd.Index(["op01", "op02"], name="loan_id"))


def _card_de(cfg: InternalProvisioningConfig, columnas_cartera: tuple[str, ...]) -> Any:
    pd_frame = pd.DataFrame(
        {"pd_calibrated": [0.01, 0.02]}, index=pd.Index(["op01", "op02"], name="loan_id")
    )
    return (
        InternalProvisioningEngine.from_config(cfg)
        .calculate(_frame_con(columnas_cartera), pd_frame=pd_frame, as_of_date=AS_OF)
        .card
    )


def test_la_card_registra_la_ambiguedad_para_quien_corre_por_codigo() -> None:
    """D-AMB-5: sin esto, quien usa la librería como librería no ve nada.

    ⚠️ Va en ``avisos`` y **no** en ``falta_dato``: ese canal alimenta ``fail_on_falta_dato``, cuyo
    default es ``True``, así que meterlo ahí convertiría un cambio silencioso de cifra en una
    **rotura** para quien hoy corre bien, dentro de un release *minor*.
    """
    card = _card_de(
        InternalProvisioningConfig(grouping="provided", group_col="grupo"),
        ("portfolio", "cmf_portfolio"),
    )

    assert card.avisos, "la corrida con dos columnas de cartera no dejó rastro en la card"
    assert any("cmf_portfolio" in aviso for aviso in card.avisos)
    assert card.falta_dato == (), (
        "la ambigüedad entró por el canal gobernable: con fail_on_falta_dato=True detendría "
        "corridas que hoy funcionan"
    )


def test_control_negativo_una_sola_columna_deja_la_card_sin_avisos() -> None:
    """El estado normal no gana ruido: si el archivo no es ambiguo, la card calla."""
    card = _card_de(
        InternalProvisioningConfig(grouping="provided", group_col="grupo"), ("portfolio",)
    )

    assert card.avisos == ()


def test_control_negativo_columna_declarada_deja_la_card_sin_avisos() -> None:
    """Simétrico de la capa (a): el criterio es UNO SOLO y vive en el config.

    Si el engine reimplementara la condición, el preflight y el informe podrían decir cosas
    distintas sobre la misma corrida — que es exactamente el defecto que `1.11.0` cerró en la
    moneda, donde pantalla e informe afirmaban monedas distintas de las mismas cifras.
    """
    card = _card_de(
        InternalProvisioningConfig(
            grouping="provided", group_col="grupo", portfolio_col="portfolio"
        ),
        ("portfolio", "cmf_portfolio"),
    )

    assert card.avisos == ()
