"""Serialización read-only de una corrida a JSON transportable (SDD-23 §4.3, §6).

Esta capa **solo formatea** lo que el motor ya materializó: nunca recalcula un número. Toma el
``ModelCard`` consolidado (vía :class:`~nikodym.governance.ModelCardBuilder`) y las *cards* por
dominio publicadas en ``study.artifacts``, y las proyecta a estructuras JSON puras. Es **lógica
pura**, testeable sin FastAPI, y *domain-agnostic*: no importa módulos de dominio ni reimplementa
rangos, enums, finitud ni fórmulas de riesgo (SDD-23 §11).

Invariantes duras (§6): (1) **nunca** ``NaN``/``Inf`` en el JSON — un guard defensivo levanta
:class:`~nikodym.ui.exceptions.UiSerializationError` ante cualquier no-finito, en vez de emitir
tokens que rompen JSON estricto; (2) **no-mutación** — se leen DTOs frozen y copias, jamás se
escribe bajo namespaces de dominio; (3) la UI **no produce números** — todo dato serializado viene
de un artefacto de origen citable.
"""

from __future__ import annotations

import json
import warnings
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Final

import numpy as np
from pydantic import BaseModel

from nikodym.core.exceptions import NikodymError
from nikodym.core.markers import strip_declared_codes
from nikodym.governance import GovernanceConfig, ModelCardBuilder
from nikodym.methodology import build_ifrs9_methodology_card
from nikodym.ui.exceptions import UiSerializationError
from nikodym.ui.reliability import reliability_curve

if TYPE_CHECKING:
    from pathlib import Path

    import pandas as pd

    from nikodym.core.study import Study

__all__ = ["dump_dto", "public_engine_message", "serialize_study", "to_records"]

# Mapa canónico dominio → clave de su *card* en ``study.artifacts``. La clave NO es uniforme:
# binning/selection/model usan ``"<dom>_card"``; scorecard/calibration/performance/stability usan
# ``"card"``. La fuente de verdad es ``report/builder.py:_CARD_ARTIFACTS`` (SDD-23 §6); se replica
# aquí (no se importa ``report``) para conservar la frontera *domain-agnostic* del backend.
# ``tests/unit/test_ui_serializers.py`` coteja este mapa contra el canónico para detectar deriva.
_CARD_KEY_BY_DOMAIN: dict[str, str] = {
    # Análisis exploratorio (SDD-27, D-SC-5): la card trae la tasa global, cuántos períodos o
    # cohortes la componen, el eje EFECTIVO y si lo infirió el motor, la señal temporal con su
    # indicador, umbral y valor —o la causa por la que no se evaluó— y los conteos de calidad.
    # Sus tres tablas son AGREGADAS (una fila por período, por columna y por tramo de las
    # columnas descritas), nunca el frame.
    "eda": "eda_card",
    "binning": "binning_card",
    "selection": "selection_card",
    "model": "model_card",
    "scorecard": "card",
    "calibration": "card",
    "performance": "card",
    "stability": "card",
    # Validación formal (SDD-22, D-SC-9): la card trae el estado técnico, el conteo de pruebas, las
    # familias corridas, los avisos declarados y `metric_sections`, donde viajan los grados sin
    # potencia. Sus cuatro tablas son AGREGADAS por partición/test/grado/segmento —decenas de
    # filas, no miles—, así que entran enteras por `_augment`, a diferencia de los `detail` de
    # provisiones.
    "validation": "card",
    # Survival se expone porque la ficha F4 necesita la evidencia observada del ajuste (filas,
    # eventos y períodos). Es una card agregada pequeña; nunca se serializa la term-structure larga.
    "survival": "card",
    # Provisiones (SDD-28): las tres cards usan la clave ``"card"``. Solo se serializan las cards y
    # sus frames AGREGADOS (ver ``_augment``); los frames ``detail`` por operación (6.000 filas)
    # jamás entran al payload — reventarían ``/api/results``.
    "provisioning_cmf": "card",
    "provisioning_internal": "card",
    "provisioning": "card",
    # IFRS 9 / ECL (SDD-16). Misma regla que las de arriba: se serializa la card y frames AGREGADOS
    # (distribución de staging, curva ECL por período, resumen por carteraxstage, conteo de gatillos
    # SICR); el ``detail`` por operación (6.000 filas) NO entra al payload por la misma razón.
    "provisioning_ifrs9": "card",
}

# Mensaje de reserva. Desde la enmienda RUN-ERROR el mensaje del motor SÍ llega hasta aquí, por
# ``run_context.error``; este texto cubre los dos casos en que igual no hay nada mejor que decir: un
# ``Study`` recargado de un bundle guardado antes de la enmienda (sin el campo), y una excepción
# inesperada, cuyo texto es detalle interno y no información para quien usa el formulario (D-ERR-5).
_FAILURE_MESSAGE = (
    "La corrida falló durante la ejecución del pipeline. El model card parcial, el lineage y el "
    "audit-trail conservan la evidencia disponible del error de dominio."
)


def public_engine_message(message: str, *, error_type: str | None, is_domain_error: bool) -> str:
    """Convierte el diagnóstico de una excepción del motor en copy publicable (D-ERR-4/D-ERR-5).

    La **regla** es una sola para las dos superficies que publican un fallo del motor —el panel de
    resultados de una corrida fallida y el aviso de config inejecutable del formulario (D-PIPE-5)—,
    porque duplicarla es lo que permitiría que una de las dos empiece a filtrar códigos internos
    sin que nadie se entere. El **texto** de reserva sí es propio de cada superficie: una corrida
    fallida puede remitir al model card y al lineage, y un config inejecutable no tiene ninguno.

    Un error de dominio se publica con el texto que escribió el motor, **sin** el código de la
    marca cuando lo trae al frente: el código es el dato en superficie de código, no en el idioma
    del lector. Lo que no es error de dominio no se publica crudo —su texto es detalle interno— y
    se sustituye por una nota que nombra el tipo y dice dónde vive el detalle técnico.
    """
    if not is_domain_error:
        # No se nombra dónde vive el detalle técnico: la cadena que consume este texto captura la
        # excepción y no la escribe en ninguna parte, así que remitir a «el log del servidor» —como
        # decía antes— manda al lector a buscar algo que no existe. Si aparece, es un defecto de la
        # librería y lo accionable es reportarlo, no revisar el config.
        return (
            f"El motor falló con un error inesperado ({error_type or 'sin tipo'}). No es un "
            "problema de tu configuración: si vuelve a ocurrir, es un defecto de la librería y "
            "conviene reportarlo."
        )
    return strip_declared_codes(message)


def _failure_message(study: Study) -> str:
    """Compone el mensaje de fallo que ve el usuario del panel de resultados (D-ERR-4/D-ERR-5).

    Un error de dominio se publica con el texto que escribió el motor —que está redactado para un
    humano y nombra la columna, el parámetro o el paso concreto—, pero **sin** el código de la marca
    cuando el mensaje lo trae: el panel es copy público y ahí la limitación se explica en el idioma
    del lector. El mensaje íntegro, con código, sigue disponible por código en
    ``study.run_context.error.message``.
    """
    error = study.run_context.error
    if error is None:
        return _FAILURE_MESSAGE
    if not error.is_domain_error:
        return (
            f"{_FAILURE_MESSAGE} El fallo no fue un error de dominio sino uno inesperado "
            f"({error.type}); su detalle técnico vive en run_context.error."
        )
    # El saneo lo posee ``public_engine_message`` (misma regla que el aviso del formulario): aquí
    # sólo se decide el encabezado, que sí es propio del panel de una corrida.
    saneado = public_engine_message(error.message, error_type=error.type, is_domain_error=True)
    if error.step is not None:
        return f"El paso '{error.step}' falló: {saneado}"
    return saneado


def serialize_study(
    study: Study,
    *,
    governance: GovernanceConfig | None,
    trail_path: Path | None = None,
) -> dict[str, Any]:
    """Compone el JSON read-only de resultados de una corrida (SDD-23 §6).

    Parameters
    ----------
    study : Study
        Corrida finalizada (``run_context.status`` en ``"done"``/``"failed"``) o parcial.
    governance : GovernanceConfig or None
        Config de gobernanza para construir el ``ModelCard`` consolidado; ``None`` ⇒ card ausente.
    trail_path : Path or None
        Audit-trail ya archivado de esta corrida. Con él el model card trae sus ``decisions``;
        sin él sale parcial, que es lo que ocurría en toda corrida de la interfaz antes de
        D-GOB-7/8 —el trail no llegaba hasta aquí y la lista salía siempre vacía—.

    Returns
    -------
    dict
        ``{status, run_id, error, model_card, lineage, <dominio>...}``. ``error`` es ``None`` salvo
        en fallo; ``model_card`` es ``None`` si no hay gobernanza o la corrida no produjo card;
        ``lineage`` es la procedencia de la corrida (``None`` mientras no se haya congelado); cada
        clave de dominio (binning/selection/model/scorecard/calibration/performance/stability y,
        cuando la corrida las produce, provisioning_cmf/provisioning_internal/provisioning) trae su
        *card* serializada, **fusionada** con los frames ricos graficables agregados de ese dominio
        (§6), o ``None`` si el dominio no corrió (nunca se fabrica).
    """
    status = study.run_context.status
    payload: dict[str, Any] = {
        "status": status,
        "run_id": study.run_context.run_id,
        "error": _failure_message(study) if status == "failed" else None,
        "model_card": _serialize_model_card(study, governance, trail_path),
        "lineage": _serialize_lineage(study),
    }
    for domain, key in _CARD_KEY_BY_DOMAIN.items():
        payload[domain] = (
            _dump_card(domain, study.artifacts.get(domain, key))
            if study.artifacts.has(domain, key)
            else None
        )
    _augment_with_rich_artifacts(study, payload)
    return payload


#: Los DOS escalares de la card de ``eda`` cuyo ``NaN`` es una ausencia declarada y no un defecto:
#: ``stability_value`` no existe cuando la señal temporal no se evaluó —y la card dice por qué en
#: ``stability_not_evaluable_reason``—, y ``overall_default_rate`` no existe sin operaciones
#: elegibles. Ningún otro campo, de ninguna otra card, tiene ese permiso.
_EDA_AUSENCIAS_DECLARADAS: tuple[str, ...] = ("overall_default_rate", "stability_value")


def _dump_card(domain: str, card: BaseModel) -> dict[str, Any]:
    """Serializa la card de un dominio con el guard de finitud de :func:`dump_dto`.

    🔴 Sólo la card de ``eda`` pasa por una coacción, y sólo en sus dos ausencias declaradas
    (:data:`_EDA_AUSENCIAS_DECLARADAS`). La primera versión de la capa 3 mandaba TODAS las cards
    por una conversión recursiva ``NaN`` → ``null``, y eso desactivaba la invariante (1) del módulo
    para binning, calibración, desempeño y provisiones: un no-finito ahí es corrupción numérica y
    tiene que fallar ruidoso, no publicarse como ausencia. Hallazgo de la revisión adversarial de
    S9, verificado.
    """
    if domain != "eda":
        return dump_dto(card)
    dumped = card.model_dump(mode="json")
    for field in _EDA_AUSENCIAS_DECLARADAS:
        value = dumped.get(field)
        if isinstance(value, float) and value != value:
            dumped[field] = None
    # La regla del motor (D-SC-2) es «hay causa si y sólo si el indicador no es finito»: un valor
    # ausente SIN causa no es una ausencia declarada sino un contrato roto, y se dice.
    if (
        dumped.get("stability_value") is None
        and dumped.get("stability_not_evaluable_reason") is None
    ):
        raise UiSerializationError(
            "la card de eda publica el indicador de estabilidad sin valor y sin causa de no "
            "evaluabilidad: el motor promete una causa por cada indicador no finito."
        )
    _ensure_json_safe(dumped, context=type(card).__name__)
    return dumped


def _augment_with_rich_artifacts(study: Study, payload: dict[str, Any]) -> None:
    """Fusiona (merge aditivo) los frames ricos graficables en cada objeto de dominio (§6).

    Puramente aditivo: **no** toca las *cards* ya presentes ni el motor; solo lee más claves de
    ``study.artifacts`` y las proyecta bajo el guard de finitud. Las claves ricas se agregan solo
    cuando el dominio corrió (su card es un ``dict``); un artefacto rico concreto ausente entra como
    ``None`` (nunca se fabrica). No hay colisión de nombres con las claves de las cards.
    """
    if isinstance(payload["eda"], dict):
        # Las TRES tablas agregadas del análisis exploratorio (D-SC-5): la tasa por período o
        # cohorte tal cual la publica el motor —con `low_confidence` por fila—, la calidad por
        # columna con sus tres marcas, y los perfiles por variable REDUCIDOS a una fila por tramo
        # (columna, tramo, n, cobertura, tasa). Nunca el frame ni las figuras: las figuras son
        # recetas para el informe y el panel decide qué graficar por el eje efectivo de la card.
        payload["eda"]["default_rate"] = _eda_default_rate(study)
        payload["eda"]["quality"] = _eda_quality(study)
        payload["eda"]["univariate"] = _eda_univariate(study)
    if isinstance(payload["binning"], dict):
        payload["binning"]["tables_by_variable"] = _binning_tables(study)
    if isinstance(payload["selection"], dict):
        payload["selection"]["decisions"] = _selection_decisions(study)
    if isinstance(payload["model"], dict):
        payload["model"]["coefficients"] = _domain_records(study, "model", "coefficients")
    if isinstance(payload["scorecard"], dict):
        payload["scorecard"]["points"] = _domain_records(study, "scorecard", "scorecard")
        payload["scorecard"]["score_values"] = _score_values(study)
    if isinstance(payload["calibration"], dict):
        payload["calibration"]["isotonic_knots"] = _isotonic_knots(study)
        payload["calibration"]["reliability"] = _reliability_curve(study)
    if isinstance(payload["performance"], dict):
        payload["performance"]["deciles"] = _domain_records(
            study, "performance", "performance_table"
        )
        payload["performance"]["discriminant"] = _domain_records(
            study, "performance", "discriminant_metrics"
        )
    if isinstance(payload["stability"], dict):
        # Dos frames graficables (SDD-11 §6). ``psi_table`` trae los bins de PSI del score, de la
        # PD calibrada y del CSI por característica juntos; la columna ``metric`` los distingue
        # (``score_psi``/``pd_psi``/``csi``) y cada bin lleva su ``band``. ``stability_metrics``
        # resume una fila por métrica/comparación (incluye ``temporal_score``). Los CSI por
        # característica viven DENTRO de ambos frames (filas ``metric == "csi"``), no en clave
        # aparte. ``_domain_records`` aplica el guard de finitud y ``NaN`` → ``None``.
        payload["stability"]["psi_table"] = _domain_records(study, "stability", "psi_table")
        payload["stability"]["stability_metrics"] = _domain_records(
            study, "stability", "stability_metrics"
        )
    if isinstance(payload["validation"], dict):
        # Las CUATRO tablas tidy tal cual las publica el motor (SDD-22 §6), sin reagrupar ni
        # reinterpretar: el panel las pinta por familia y el veredicto sigue siendo el del motor.
        # ⚠️ `calibration` mezcla a propósito las filas de Hosmer-Lemeshow/Brier con las del test
        # por grado —es una sola tabla canónica, y la columna `grade` es la que las distingue—;
        # los grados SIN potencia no están aquí sino en `card.metric_sections`, y ésa es la razón
        # de que el panel tenga que publicar la cobertura además de la tabla (§0-20).
        for clave in ("discrimination", "calibration", "stability", "backtesting"):
            payload["validation"][clave] = _domain_records(study, "validation", clave)
    # Provisiones (SDD-28): solo frames AGREGADOS (graficables), nunca los ``detail`` por operación.
    if isinstance(payload["provisioning_cmf"], dict):
        # Desglose del método estándar por categoría CMF (~20 filas): dónde vive la provisión.
        payload["provisioning_cmf"]["summary"] = _domain_records(
            study, "provisioning_cmf", "summary"
        )
    if isinstance(payload["provisioning_internal"], dict):
        # Desglose efectivo por grupo: bandas, segmentos o grupos provistos; PD·LGD o tasa directa.
        payload["provisioning_internal"]["groups"] = _domain_records(
            study, "provisioning_internal", "groups"
        )
    if isinstance(payload["provisioning"], dict):
        # La comparación estándar-vs-interno con la fuente que muerde (``binding``): el titular.
        payload["provisioning"]["comparison"] = _domain_records(study, "provisioning", "comparison")
    # IFRS 9 / ECL (SDD-16): frames AGREGADOS graficables + una MUESTRA acotada por operación. El
    # ``detail`` COMPLETO (6.000 filas) NUNCA entra al payload (reventaría ``/api/results``, misma
    # regla que CMF/interno); el drill-down completo iría por un endpoint paginado dedicado.
    if isinstance(payload["provisioning_ifrs9"], dict):
        block = payload["provisioning_ifrs9"]
        # Distribución de staging por Stage 1/2/3 (conteo + monto + cobertura): el gráfico central.
        block["staging_distribution"] = _ifrs9_staging_distribution(study)
        # Resumen por cartera x stage tal cual lo agrega el motor (EAD, ECL, coverage).
        block["summary"] = _domain_records(study, "provisioning_ifrs9", "summary")
        # Curva de ECL por período (año): marginal, acumulada, PD marginal y factor de descuento.
        block["ecl_term_structure"] = _ifrs9_ecl_curve(study)
        # Conteo de gatillos SICR disparados (qué llevó a cada operación a Stage 2/3).
        block["sicr_triggers"] = _ifrs9_sicr_triggers(study)
        # Muestra por operación (top-N por ECL, repartida por stage) para una tabla en la UI.
        block["detail_sample"] = _ifrs9_detail_sample(study)
        # Ficha compartida con el informe. Se deriva del config EFECTIVO y de cards publicadas, no
        # del config que el usuario pueda estar editando después de esta corrida.
        methodology = build_ifrs9_methodology_card(
            config=study.config,
            # Survival es la fuente de F4, pero IFRS 9 también admite term-structures Markov o
            # forward. Una corrida válida con esas fuentes no publica necesariamente esta card.
            survival_card=payload.get("survival"),
            ifrs9_card=block,
        )
        block["methodology"] = (
            methodology.model_dump(mode="json") if methodology is not None else None
        )


def _domain_records(study: Study, domain: str, key: str) -> list[dict[str, Any]] | None:
    """Proyecta el ``DataFrame`` ``(domain, key)`` a records; ``None`` si el artefacto falta."""
    if not study.artifacts.has(domain, key):
        return None
    return _frame_records(study.artifacts.get(domain, key))


def _eda_default_rate(study: Study) -> list[dict[str, Any]] | None:
    """La tasa por período o cohorte (``DefaultRateResult.by_period``); ``None`` si falta.

    Los artefactos de ``eda`` son DTOs que envuelven su tabla: se desenvuelven aquí, en la
    frontera, en vez de pedirle al motor que publique la tabla dos veces. El ``period`` de un eje
    temporal es un ``pd.Period``: viaja como su texto, igual que en el informe.
    """
    if not study.artifacts.has("eda", "default_rate"):
        return None
    by_period = study.artifacts.get("eda", "default_rate").by_period
    return _frame_records(
        by_period.assign(
            period=by_period["period"].map(_period_label),
            period_type=by_period["period"].map(_period_type),
        )
    )


#: El mayor entero que JavaScript representa sin pérdida (``Number.MAX_SAFE_INTEGER``): un entero
#: mayor viaja como texto, porque ``JSON.parse`` fundiría dos cohortes vecinas en el mismo número.
_JS_SAFE_INTEGER: Final = 2**53 - 1


def _period_label(value: Any) -> Any:
    """Etiqueta JSON de un período o cohorte: nativa si lo es, texto si no, ausencia si falta.

    El eje temporal trae ``pd.Period`` y una cohorte puede ser **cualquier** valor de la columna del
    usuario: texto, número, o ``pd.Timestamp`` si particionó por una fecha. Los dos últimos no son
    JSON y el guard los rechazaría —hallazgo de la revisión adversarial de S9, reproducido con una
    cohorte ``datetime``—, así que viajan como su texto, igual que en las tablas del informe. Un
    número o un texto viajan tal cual y el front distingue el tipo para no fundir dos cohortes;
    la excepción es el entero fuera del rango seguro de JavaScript (``> 2**53 - 1``), que viaja
    como texto porque el navegador no lo puede leer sin pérdida (cuarta pasada de la revisión
    adversarial de S9): ``period_type`` sigue diciendo ``int``.
    """
    import pandas as pd  # local: este módulo no arrastra pandas al importarse

    if value is None or value is pd.NA or value is pd.NaT:
        return None
    native = _to_json_native(value)
    if isinstance(native, int) and not isinstance(native, bool) and abs(native) > _JS_SAFE_INTEGER:
        return str(native)
    if native is None or isinstance(native, (str, int, float, bool)):
        return native
    return str(value)


def _period_type(value: Any) -> str | None:
    """El TIPO con que el motor distinguió un período o cohorte, para que el front no funda dos.

    El motor agrupa las cohortes de forma tipo-consciente —la numérica ``2024`` y la textual
    ``"2024"`` son grupos distintos— y JSON pierde parte de esa identidad (``2024`` y ``2024.0``
    son el mismo número en JavaScript). Con el tipo al lado del valor, la pantalla puede
    distinguir dos cohortes que se escriban igual (hallazgo de la revisión adversarial de S9).
    ``bool`` va antes que ``int`` porque en Python es su subclase.
    """
    import pandas as pd  # local: este módulo no arrastra pandas al importarse

    if value is None or value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, (bool, np.bool_)):
        return "bool"
    if isinstance(value, (int, np.integer)):
        return "int"
    if isinstance(value, (float, np.floating)):
        return None if value != value else "float"
    if isinstance(value, str):
        return "str"
    if isinstance(value, pd.Period):
        return "period"
    if isinstance(value, pd.Timestamp):
        return "datetime"
    return type(value).__name__


def _eda_quality(study: Study) -> list[dict[str, Any]] | None:
    """La tabla de calidad por columna (``QualityResult.by_column``); ``None`` si falta."""
    if not study.artifacts.has("eda", "quality"):
        return None
    return _frame_records(study.artifacts.get("eda", "quality").by_column)


def _eda_univariate(study: Study) -> list[dict[str, Any]] | None:
    """Los perfiles por variable, una fila por tramo, con la columna delante (D-SC-5).

    ``UnivariateResult.profiles`` es ``{columna: tabla(tramo, n, coverage, default_rate)}`` y
    se aplana conservando el orden de perfilado y el orden de los tramos, que es el que el motor
    decidió (numéricos por cuantil, categóricos por nivel con «otros» y «missing» al final). El
    ``tramo`` de una numérica es un ``pd.Interval``: viaja como su texto, que es como lo publica
    el informe. El IV descriptivo, si se pidió, va aparte y por columna.
    """
    if not study.artifacts.has("eda", "univariate"):
        return None
    univariate = study.artifacts.get("eda", "univariate")
    rows: list[dict[str, Any]] = []
    for column, profile in univariate.profiles.items():
        for row in profile.to_dict(orient="records"):
            rows.append(
                {
                    "column": str(column),
                    "tramo": _tramo_label(row.get("tramo")),
                    "n": _to_json_native(row.get("n")),
                    "coverage": _to_json_native(row.get("coverage")),
                    "default_rate": _to_json_native(row.get("default_rate")),
                    "descriptive_iv": _to_json_native(univariate.descriptive_iv.get(column)),
                }
            )
    _ensure_json_safe(rows, context="eda.univariate")
    return rows


def _tramo_label(value: Any) -> Any:
    """Etiqueta JSON de un tramo: intervalos y niveles viajan como texto, salvo faltantes."""
    native = _to_json_native(value)
    if native is None or isinstance(native, (str, int, float, bool)):
        return native
    return str(value)


def _frame_records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    """Proyecta un ``DataFrame`` a records, coaccionando cada celda a un tipo JSON nativo (§6).

    Las celdas de los frames del motor no son siempre tipos nativos de Python: los campos
    ``float | None`` de los DTOs fila-nivel se materializan como ``NaN`` (p. ej. ``iv`` en la fila
    *intercept* de coeficientes, o ``auc``/``gini``/``ks`` de una partición sin métricas), y la
    columna ``Bin`` de una tabla OptBinning **categórica** trae ``numpy.ndarray`` por bin
    (``array(['independiente'])``), además de escalares ``numpy``. :func:`_to_json_native` los
    normaliza uniformemente: ``NaN`` → ``None`` (ausente, igual que ``model_dump`` de un DTO
    nullable); ``ndarray``/``list``/``tuple`` → lista nativa (recursiva); escalar ``numpy`` → su
    ``.item()``. **No** fabrica números. Un ``Inf`` genuino **no** es ausente: sobrevive a la
    coacción y el guard de finitud lo rechaza (falla ruidoso), como en :func:`to_records`.
    """
    records = [
        {str(column): _to_json_native(value) for column, value in row.items()}
        for row in frame.to_dict(orient="records")
    ]
    _ensure_json_safe(records, context="tabla de resultados")
    return records


def _to_json_native(value: Any) -> Any:
    """Coacciona una celda a un tipo JSON nativo (``NaN`` float → ``None``; ``Inf`` sobrevive).

    Cubre los tipos ``numpy`` que ``json.dumps`` no serializa: ``ndarray`` → lista (recursiva),
    escalar (``np.integer``/``np.floating``/``np.bool_``/``np.str_``) → su ``.item()``. Preserva la
    semántica de ausencia: ``float('nan')`` (incl. ``np.float64('nan')``, subclase de ``float``) →
    ``None``; ``Inf`` se mantiene finito-inválido para que el guard lo rechace, no lo enmascara.

    **``Decimal`` → ``float``.** Los motores de provisiones trabajan en ``Decimal`` (es una cifra
    contable), y ``json.dumps`` no lo serializa: sin esta rama, ``_ensure_json_safe`` levanta y se
    cae **todo** el payload de ``/api/results``, no solo la sección de provisiones. Se coacciona
    aquí, en la frontera, una sola vez: JSON no tiene decimales, y el número ya viene cuantizado por
    la política ``rounding`` del motor. La alternativa —emitirlo como *string*— filtraría la
    semántica de ``Decimal`` a TypeScript, que tampoco puede representarla.
    """
    if isinstance(value, Decimal):  # cifra contable de provisiones (CMF / método interno)
        return None if value.is_nan() else float(value)
    if isinstance(value, float):  # incl. np.float64 (subclase): NaN→None, resto→float nativo
        return None if value != value else float(value)
    if isinstance(value, np.ndarray):
        return [_to_json_native(item) for item in value.tolist()]
    if isinstance(value, np.generic):  # escalar numpy no-float (int/bool/str/…) → nativo, recursivo
        return _to_json_native(value.item())
    if isinstance(value, (list, tuple)):
        return [_to_json_native(item) for item in value]
    return value


def _binning_tables(study: Study) -> dict[str, list[dict[str, Any]]] | None:
    """Tablas OptBinning por variable → ``{feature: records}``; ``None`` si el artefacto falta.

    Cada valor es la tabla ``binning_table`` normalizada del motor, proyectada fila a fila con sus
    columnas canónicas de OptBinning (conteos, tasas y métricas por *bin*, con la fila ``Totals``
    incluida tal como viene). El detalle de columnas está en el mapa de serialización de SDD-23 §6.
    """
    if not study.artifacts.has("binning", "tables"):
        return None
    tables: dict[str, pd.DataFrame] = study.artifacts.get("binning", "tables")
    return {str(feature): _frame_records(frame) for feature, frame in tables.items()}


def _selection_decisions(study: Study) -> list[dict[str, Any]] | None:
    """Decisiones de selección por variable (DTOs ``VariableSelectionDecision``) → records.

    ``None`` si el resultado de selección está ausente. Se excluyen a propósito
    ``correlation_matrix``/``vif_table``/``stability`` (fuera de alcance de esta capa).
    """
    if not study.artifacts.has("selection", "result"):
        return None
    return [dump_dto(decision) for decision in study.artifacts.get("selection", "result").decisions]


def _score_values(study: Study) -> list[float] | None:
    """Columna de score fila-nivel como ``list[float]`` (para el histograma); ``None`` si ausente.

    El nombre de la columna es dinámico: se lee de ``ScorecardCardSection.score_column`` (default
    ``"score"``). Se emite el array completo (la demo está pre-cacheada) bajo el guard de finitud.
    """
    if not study.artifacts.has("scorecard", "score"):
        return None
    score_column = study.artifacts.get("scorecard", "card").score_column
    values: list[float] = study.artifacts.get("scorecard", "score")[score_column].tolist()
    _ensure_json_safe(values, context="scorecard.score_values")
    return values


def _isotonic_knots(study: Study) -> list[list[float]] | None:
    """Knots isotónicos → ``[[x, y], ...]``; ``None`` si el método no es isotónico o falta.

    ``CalibrationParameters.isotonic_knots`` es una tupla vacía cuando el método no es isotónico
    (p. ej. ``intercept_offset``): se respeta como ``None``, sin fabricar una curva de fiabilidad.
    """
    if not study.artifacts.has("calibration", "parameters"):
        return None
    knots = study.artifacts.get("calibration", "parameters").isotonic_knots
    if not knots:
        return None
    pairs = [[float(x), float(y)] for x, y in knots]
    _ensure_json_safe(pairs, context="calibration.isotonic_knots")
    return pairs


def _reliability_curve(study: Study) -> dict[str, Any] | None:
    """Curva de confiabilidad derivada del ``calibrated_pd_frame``; ``None`` si el frame falta.

    Artefacto rico derivado (no un número del motor): delega en
    :func:`nikodym.ui.reliability.reliability_curve`, que agrupa la PD calibrada en deciles de igual
    frecuencia por partición y emite predicho-vs-observado + Brier/ECE (SDD-23 §6). El propio módulo
    aplica el guard de finitud sobre su salida. ``None`` si no hay artefacto de origen (nunca se
    fabrica), igual que :func:`_isotonic_knots`/:func:`_binning_tables`.
    """
    if not study.artifacts.has("calibration", "calibrated_pd_frame"):
        return None
    return reliability_curve(study.artifacts.get("calibration", "calibrated_pd_frame"))


def _ifrs9_staging_distribution(study: Study) -> list[dict[str, Any]] | None:
    """Distribución de staging IFRS 9 por Stage 1/2/3 (conteo y monto), derivada del ``summary``.

    Agrega el ``summary`` por operación (cartera x stage) a nivel de stage y recompone la cobertura
    ``ECL/EAD`` de cada stage. Es un artefacto rico DERIVADO (como la curva de fiabilidad): agrega
    números que el motor ya materializó para graficar, sin recalcular riesgo. Bajo el guard de
    finitud vía :func:`_frame_records`. ``None`` si el ``summary`` no está publicado.
    """
    if not study.artifacts.has("provisioning_ifrs9", "summary"):
        return None
    summary = study.artifacts.get("provisioning_ifrs9", "summary")
    grouped = summary.groupby("stage", as_index=False).agg(
        n_rows=("n_rows", "sum"),
        total_ead=("total_ead", "sum"),
        total_ecl_reported=("total_ecl_reported", "sum"),
    )
    ead = grouped["total_ead"].to_numpy(dtype="float64")
    ecl = grouped["total_ecl_reported"].to_numpy(dtype="float64")
    grouped["coverage_ratio"] = np.divide(ecl, ead, out=np.zeros_like(ead), where=ead > 0.0)
    grouped = grouped.sort_values("stage").reset_index(drop=True)
    return _frame_records(grouped)


def _ifrs9_ecl_curve(study: Study) -> list[dict[str, Any]] | None:
    """Curva de ECL IFRS 9 por período, agregada desde ``ecl_term_structure``.

    Suma la ECL marginal por período y su acumulada, y publica la PD marginal ponderada por EAD y el
    factor de descuento medio de cada período. Agrega la term-structure larga por operación (que NO
    entra al payload por tamaño) a una curva de pocas filas. ``None`` si el artefacto falta.

    **El período NO es un año** (D-HOR-0): es el índice de la grilla, y el instante que le
    corresponde viaja en DOS columnas, igual que en el artefacto del motor (``ecl.py`` §columnas
    canónicas). ``time_value`` es el instante CRUDO, en la unidad en que lo emitió el productor
    de la term-structure —así la curva reconcilia fila a fila con la de ``survival``/``markov``—,
    y ``time_value_years`` es el τ **convertido a años con el que se calculó**
    ``discount_factor``. Publicar sólo el crudo dejaría un plazo que no reconstruye su propio
    factor de descuento: con una curva mensual, ``DF ** (-1/time_value) - 1`` da 1,5 % donde la
    EIR es 20 %.

    ``time_unit`` (la etiqueta textual de la unidad) **no llega hasta aquí**: se consume en
    ``engine._prepare_term_structure`` y no entra a las columnas canónicas de
    ``ecl_term_structure``. Por eso el crudo viaja sin rótulo de unidad, y el cociente contra el
    convertido es la única vía de deducirla desde el payload.

    **Semántica (importante para el front):** es el *runoff* de la ECL **LIFETIME de toda la
    cartera** (cada operación medida en TODO el horizonte, la forma de la term-structure), NO el
    desglose de la ECL reportada. Por eso ``ecl_cumulative`` del último período **no** coincide con
    ``total_ecl_reported`` de la card (que trunca por stage: Stage 1 solo 12m). El desglose que SÍ
    reconcilia con la card es ``staging_distribution`` (por Stage 1/2/3). Ambas vistas son estándar
    en un tablero IFRS 9: rotúlalas distinto (curva lifetime vs. ECL reportada por stage).
    """
    if not study.artifacts.has("provisioning_ifrs9", "ecl_term_structure"):
        return None
    ts = study.artifacts.get("provisioning_ifrs9", "ecl_term_structure")
    weighted_pd = ts["pd_marginal"].to_numpy(dtype="float64") * ts["ead"].to_numpy(dtype="float64")
    grouped = (
        ts.assign(_pd_ead=weighted_pd)
        .groupby("period", as_index=False)
        .agg(
            time_value=("time_value", "first"),
            time_value_years=("time_value_years", "first"),
            ecl_marginal=("ecl_marginal", "sum"),
            _pd_ead=("_pd_ead", "sum"),
            _ead=("ead", "sum"),
            discount_factor_mean=("discount_factor", "mean"),
            n_rows=("row_id", "count"),
        )
        .sort_values("period")
        .reset_index(drop=True)
    )
    ead = grouped["_ead"].to_numpy(dtype="float64")
    pd_ead = grouped["_pd_ead"].to_numpy(dtype="float64")
    grouped["pd_marginal_weighted"] = np.divide(
        pd_ead, ead, out=np.zeros_like(ead), where=ead > 0.0
    )
    grouped["ecl_cumulative"] = grouped["ecl_marginal"].cumsum()
    ordered = grouped[
        [
            "period",
            "time_value",
            "time_value_years",
            "ecl_marginal",
            "ecl_cumulative",
            "pd_marginal_weighted",
            "discount_factor_mean",
            "n_rows",
        ]
    ]
    return _frame_records(ordered)


def _ifrs9_sicr_triggers(study: Study) -> dict[str, int] | None:
    """Conteo de gatillos SICR disparados en el ``staging`` (qué llevó cada operación a Stage 2/3).

    Recorre la columna ``sicr_triggers`` (tupla de códigos por operación) y cuenta cada código en
    orden alfabético estable. ``None`` si el ``staging`` falta; ``{}`` si ninguna operación disparó
    un gatillo (todo Stage 1).
    """
    if not study.artifacts.has("provisioning_ifrs9", "staging"):
        return None
    staging = study.artifacts.get("provisioning_ifrs9", "staging")
    counts: dict[str, int] = {}
    for codes in staging["sicr_triggers"].tolist():
        for code in codes:
            name = str(code)
            counts[name] = counts.get(name, 0) + 1
    result = dict(sorted(counts.items()))
    _ensure_json_safe(result, context="provisioning_ifrs9.sicr_triggers")
    return result


# Operaciones por stage en la muestra ``detail_sample`` (top-10 por ECL de CADA Stage 1/2/3 → 30
# filas): garantiza que las tres etapas estén representadas (no solo Stage 3, que domina la ECL).
_IFRS9_DETAIL_SAMPLE_PER_STAGE: int = 10
_IFRS9_DETAIL_SAMPLE_COLUMNS: tuple[str, ...] = (
    "row_id",
    "portfolio",
    "stage",
    "ead",
    "lgd",
    "eir",
    "pd_12m",
    "pd_life",
    "ecl_12m",
    "ecl_lifetime",
    "ecl_reported",
)


def _ifrs9_detail_sample(study: Study) -> list[dict[str, Any]] | None:
    """Muestra por operación: top-K por ``ecl_reported`` DENTRO de cada Stage 1/2/3 (no solo el 3).

    Para una tabla "por operación" en la UI sin volcar las 6.000 filas del ``detail`` al payload
    (SDD-28). Toma las ``_IFRS9_DETAIL_SAMPLE_PER_STAGE`` operaciones de mayor ``ecl_reported`` de
    cada stage —así las tres etapas quedan representadas—, une los gatillos SICR por operación desde
    el ``staging`` y ordena el resultado por ``ecl_reported`` descendente. Publica ``loan_id``
    (== ``row_id``), ``portfolio``, ``stage``, ``ead``, ``lgd``, ``eir``, ``pd_12m``, ``pd_life``,
    ``ecl_12m``, ``ecl_lifetime``, ``ecl_reported`` y ``sicr_triggers`` (lista, vacía en Stage 1).
    ``None`` si el ``detail`` falta. Bajo el guard de finitud vía :func:`_frame_records`.
    """
    if not study.artifacts.has("provisioning_ifrs9", "detail"):
        return None
    detail = study.artifacts.get("provisioning_ifrs9", "detail")
    sample = (
        detail[list(_IFRS9_DETAIL_SAMPLE_COLUMNS)]
        .sort_values("ecl_reported", ascending=False, kind="mergesort")
        .groupby("stage", sort=False, dropna=False)
        .head(_IFRS9_DETAIL_SAMPLE_PER_STAGE)
        .sort_values("ecl_reported", ascending=False, kind="mergesort")
        .reset_index(drop=True)
    )
    triggers_by_id: dict[str, tuple[str, ...]] = {}
    if study.artifacts.has("provisioning_ifrs9", "staging"):
        staging = study.artifacts.get("provisioning_ifrs9", "staging")
        triggers_by_id = {
            str(row_id): tuple(str(code) for code in codes)
            for row_id, codes in zip(
                staging["row_id"].tolist(), staging["sicr_triggers"].tolist(), strict=True
            )
        }
    sample = sample.assign(
        sicr_triggers=[triggers_by_id.get(str(row_id), ()) for row_id in sample["row_id"].tolist()]
    ).rename(columns={"row_id": "loan_id"})
    return _frame_records(sample)


def to_records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    """Proyecta un ``DataFrame`` a ``list[dict]`` (``to_dict("records")``) con guard de finitud.

    Las claves se normalizan a ``str`` (claves JSON) y se valida que el resultado sea JSON estricto:
    cualquier float no-finito levanta :class:`~nikodym.ui.exceptions.UiSerializationError`.
    """
    records = [
        {str(column): value for column, value in row.items()}
        for row in frame.to_dict(orient="records")
    ]
    _ensure_json_safe(records, context="tabla de resultados")
    return records


def dump_dto(dto: BaseModel) -> dict[str, Any]:
    """Serializa un DTO Pydantic a JSON con guard de finitud, coaccionando ``Decimal`` a número.

    Se dumpea en ``mode="json"`` —que es quien resuelve ``datetime``, enums y demás— y **solo** se
    sustituyen los ``Decimal``, localizándolos con un segundo dump en ``mode="python"`` que conserva
    los tipos. Las cards de provisiones llevan sus totales en ``Decimal`` (es una cifra contable) y
    Pydantic los emitiría como ``"851018945.42"``: el front hace aritmética con ellos y TypeScript
    no tiene decimal, así que devolver un *string* solo trasladaría el problema una capa más allá.
    """
    dumped = _sustituye_decimales(dto.model_dump(mode="json"), dto.model_dump(mode="python"))
    _ensure_json_safe(dumped, context=type(dto).__name__)
    return dumped  # type: ignore[no-any-return]


def _sustituye_decimales(serializado: Any, tipado: Any) -> Any:
    """Devuelve ``serializado`` con los ``Decimal`` de ``tipado`` convertidos a ``float``.

    Ambos árboles vienen del **mismo** DTO (uno en ``mode="json"``, otro en ``mode="python"``), así
    que tienen forma idéntica: se recorren en paralelo y solo se toca la hoja donde el árbol tipado
    dice ``Decimal``. Todo lo demás conserva la serialización de Pydantic.
    """
    if isinstance(tipado, Decimal):
        return None if tipado.is_nan() else float(tipado)
    if isinstance(tipado, dict) and isinstance(serializado, dict):
        return {
            clave: _sustituye_decimales(serializado.get(clave), valor)
            for clave, valor in tipado.items()
        }
    if isinstance(tipado, (list, tuple)) and isinstance(serializado, (list, tuple)):
        return [
            _sustituye_decimales(hijo_json, hijo_py)
            for hijo_json, hijo_py in zip(serializado, tipado, strict=False)
        ]
    return serializado


def _serialize_lineage(study: Study) -> dict[str, Any] | None:
    """Procedencia de la corrida, o ``None`` si todavía no se congeló (D-LIN-1).

    Publica el **bundle entero**, no una selección: el anexo del informe ya lo publica completo
    (``report/builder.py``), y una lista corta escrita aquí se separaría de él en silencio la
    primera vez que el bundle ganara un campo. Extensión aditiva bajo CT-3.

    ⚠️ Incluye ``created_at``, que es el único campo de reloj del bundle, y eso **acota** el
    invariante «el contenido persistido es determinista» de ``runs.py``: dos corridas idénticas
    producen ahora dos ``results.json`` distintos en ese campo. Se decidió así porque (a) el mismo
    directorio ya persiste ``report.html`` con esa marca de tiempo dentro, así que el invariante
    describía sólo a ``results.json`` y no al directorio; (b) omitirlo dejaría el panel publicando
    una procedencia **distinta** de la del informe que documenta la misma corrida, que es
    exactamente la asimetría que esta clave existe para cerrar.
    """
    lineage = study.run_context.lineage
    if lineage is None:
        return None
    return lineage.model_dump(mode="json")


def _serialize_model_card(
    study: Study, governance: object, trail_path: Path | None = None
) -> dict[str, Any] | None:
    """Construye y serializa el ``ModelCard`` consolidado, o ``None`` si no hay card (§6/§8)."""
    resolved = _resolve_governance(governance)
    if resolved is None:
        return None
    try:
        with warnings.catch_warnings():
            # El ``ModelCardBuilder`` avisa "trail no disponible" al construir sin trail; la UI ya
            # refleja esa condición en las limitaciones del card, no la re-emite como warning.
            warnings.filterwarnings("ignore", message="trail no disponible", category=UserWarning)
            card = ModelCardBuilder(resolved).build(study, trail_path=trail_path)
    except NikodymError:
        # Corrida demasiado parcial para una card válida: ausente, no fabricada (SDD-23 §6/§8).
        return None
    return dump_dto(card)


def _resolve_governance(governance: object) -> GovernanceConfig | None:
    """Normaliza la gobernanza a ``GovernanceConfig`` (coacciona un blob/dict) o ``None``."""
    if governance is None:
        return None
    if isinstance(governance, GovernanceConfig):
        return governance
    return GovernanceConfig.model_validate(governance)


def _ensure_json_safe(value: Any, *, context: str) -> None:
    """Falla ruidoso (guard defensivo) si ``value`` no es JSON estricto: no-finito u opaco."""
    try:
        json.dumps(value, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise UiSerializationError(
            f"el artefacto '{context}' no es serializable a JSON estricto (no-finito u objeto "
            f"opaco detectado): {exc}."
        ) from exc
