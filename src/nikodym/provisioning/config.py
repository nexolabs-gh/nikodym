"""Config declarativo de la capa de orquestación ``provisioning`` (SDD-17 §5).

:class:`ProvisioningConfig` es la sección ``provisioning`` de
:class:`~nikodym.core.config.NikodymConfig`: la **capa fina** que compara dos fuentes de provisión,
aplica la **regla del máximo** al nivel de agregación configurado y publica el comparativo
auditable. Hereda de :class:`~nikodym.core.config.NikodymBaseConfig` (``extra='forbid'`` y
``frozen=True``); cada campo declara ``title``/``description`` y metadatos ``ui_*`` para que la UI
(SDD-23) sea un editor del mismo config.

.. warning::

   **Corrección normativa (2026-07-13).** Este módulo afirmaba que "la regla del máximo es norma
   citada (ESPEC §5.4)". Era **falso**: ESPEC §5.4 es un documento interno de este proyecto que no
   citaba norma alguna. Verificado contra el Compendio de Normas Contables para Bancos (CMF):

   - **Cap. B-1, hoja 10-11 (Circular N° 2.346 / 06.03.2024)**: *"La constitución de provisiones
     se efectuará considerando el mayor valor obtenido entre el respectivo método estándar y el
     método interno. (…) Esta regla se deberá aplicar para cada institución en Chile que consolida
     con el banco"*. La regla del máximo es **estándar vs. interno, a nivel de entidad**.
   - **Cap. A-2, num. 5**: el Capítulo 5.5 (deterioro) de NIIF 9 **no se aplica** a las colocaciones
     ni a los créditos contingentes; sus criterios los define la CMF en B-1 a B-3.

   Por tanto ``max(CMF, IFRS 9)`` **no es "el piso prudencial de la CMF"** y no debe presentarse
   como tal. Comparar ambos marcos sigue siendo útil (p. ej. una filial que reporta ECL a su matriz
   extranjera), pero es un comparativo **entre marcos contables**, no una exigencia local. El motor
   del **método interno** (``PD x LGD x EAD`` por grupo homogéneo, como el B-1 lo describe) lo
   diseña **SDD-28**. Ver ``docs/ESPECIFICACIONES.md`` §5.4 y ``docs/design/17-*.md`` §3.

La sección es **computacional, no infraestructura** (``provisioning`` ∉ ``INFRA_SECTIONS``): cambiar
el nivel de comparación, la clave/crosswalk de cartera, la política de cobertura o la reconciliación
numérica **cambia el ``config_hash`` global**.

Frontera B17.1: aquí solo viven el schema y sus validaciones determinables sin datos. La *presencia*
de columnas/claves en los detalles de cada motor es un contrato de runtime que valida el
orchestrator en bloques posteriores (§6/§8), de modo que ``ProvisioningConfig()`` siga construyendo
sin argumentos.

**Experimental (fuera de la garantía SemVer 1.x).**
"""

from __future__ import annotations

from typing import Literal, Self

from pydantic import Field, model_validator

from nikodym.core.config import NikodymBaseConfig
from nikodym.provisioning.exceptions import ProvisioningConfigError

ProvisioningComparisonLevel = Literal["total", "portfolio", "segment", "operation"]
ProvisioningCoveragePolicy = Literal["use_available", "fail", "treat_missing_as_zero"]
ProvisioningNumericReconciliation = Literal["decimal_quantize", "float_isclose"]
ProvisioningRoundingPolicy = Literal["none", "currency_2dp", "integer_currency"]

__all__ = [
    "ProvisioningComparisonLevel",
    "ProvisioningConfig",
    "ProvisioningCoveragePolicy",
    "ProvisioningNumericReconciliation",
    "ProvisioningRoundingPolicy",
]


def _require_non_empty_strings(values: dict[str, str], *, context: str) -> None:
    """Valida que los nombres de columnas/campos declarativos no sean vacíos."""
    empty = [name for name, value in values.items() if not value.strip()]
    if empty:
        raise ProvisioningConfigError(f"Los campos de {context} no pueden estar vacíos: {empty}.")


def _require_non_empty_if_set(values: dict[str, str | None], *, context: str) -> None:
    """Valida que las columnas opcionales, si se informan, no queden en blanco."""
    empty = [name for name, value in values.items() if value is not None and not value.strip()]
    if empty:
        raise ProvisioningConfigError(
            f"Las columnas opcionales de {context} no pueden estar vacías: {empty}."
        )


class ProvisioningConfig(NikodymBaseConfig):
    """Sección ``provisioning`` de :class:`~nikodym.core.config.NikodymConfig`."""

    schema_version: str = Field(
        default="1.0.0",
        title="Versión del sub-schema provisioning",
        description="Versión local del schema de orquestación de provisiones para migraciones.",
        json_schema_extra={"ui_widget": "hidden", "ui_group": "General", "ui_order": 0},
    )
    type: Literal["standard"] = Field(
        default="standard",
        title="Tipo de sección provisioning",
        description="== @register('standard', domain='provisioning') (SDD-17 §4).",
        json_schema_extra={"ui_widget": "hidden", "ui_group": "General", "ui_order": 1},
    )
    as_of_date_col: str = Field(
        default="as_of_date",
        title="Fecha de cálculo (heredada de los motores)",
        description="Columna con la fecha de cálculo/cierre contable, heredada de CMF e IFRS 9.",
        json_schema_extra={"ui_widget": "text_input", "ui_group": "Columnas", "ui_order": 1},
    )
    comparison_level: ProvisioningComparisonLevel = Field(
        default="total",
        title="Nivel de agregación del máximo CMF vs IFRS 9",
        description=(
            "Grano al que muerde el piso prudencial: total (sin supuestos de taxonomía), "
            "portfolio, segment u operation. El nivel cambia la provisión reportada (D-PROV-2, R0)."
        ),
        json_schema_extra={"ui_widget": "selectbox", "ui_group": "Comparación", "ui_order": 1},
    )
    cmf_portfolio_col: str = Field(
        default="portfolio",
        title="Columna de cartera en el detail/summary CMF",
        description="Columna de cartera del resultado CMF para agrupar la comparación.",
        json_schema_extra={"ui_widget": "text_input", "ui_group": "Columnas", "ui_order": 2},
    )
    ifrs9_portfolio_col: str = Field(
        default="portfolio",
        title="Columna de cartera en el detail/summary IFRS 9",
        description="Columna de cartera del resultado IFRS 9 para agrupar la comparación.",
        json_schema_extra={"ui_widget": "text_input", "ui_group": "Columnas", "ui_order": 3},
    )
    portfolio_crosswalk: dict[str, str] = Field(
        default_factory=dict,
        title="Mapeo cartera CMF → cartera IFRS 9 (si difieren)",
        description=(
            "Crosswalk explícito cartera CMF → cartera IFRS 9 cuando las taxonomías no comparten "
            "clave; nunca se adivina por similitud (D-PROV-3, R0)."
        ),
        json_schema_extra={"ui_widget": "kv_text", "ui_group": "Comparación", "ui_order": 2},
    )
    segment_col: str | None = Field(
        default=None,
        title="Columna de segmento (comparison_level='segment')",
        description="Columna de segmento provista por el usuario para comparar por segmento.",
        json_schema_extra={"ui_widget": "text_input", "ui_group": "Columnas", "ui_order": 4},
    )
    row_id_col: str = Field(
        default="row_id",
        title="Identificador de operación (comparison_level='operation')",
        description="Columna identificadora de operación para alinear el nivel más granular.",
        json_schema_extra={"ui_widget": "text_input", "ui_group": "Columnas", "ui_order": 5},
    )
    consume_cmf: bool = Field(
        default=True,
        title="Consumir el resultado CMF si está presente",
        description="Si es True, la orquestación consume el resultado del motor CMF (SDD-15).",
        json_schema_extra={"ui_widget": "checkbox", "ui_group": "Motores", "ui_order": 1},
    )
    consume_ifrs9: bool = Field(
        default=True,
        title="Consumir el resultado IFRS 9 si está presente",
        description="Si es True, la orquestación consume el resultado del motor IFRS 9 (SDD-16).",
        json_schema_extra={"ui_widget": "checkbox", "ui_group": "Motores", "ui_order": 2},
    )
    require_both: bool = Field(
        default=True,
        title="Exigir ambos motores (si no, passthrough del disponible)",
        description=(
            "El piso prudencial presupone ambos motores; con False degrada a passthrough marcado "
            "del disponible (piso incompleto, FALTA-DATO)."
        ),
        json_schema_extra={"ui_widget": "checkbox", "ui_group": "Motores", "ui_order": 3},
    )
    coverage_policy: ProvisioningCoveragePolicy = Field(
        default="use_available",
        title="Política ante celda cubierta por un solo motor",
        description=(
            "use_available reporta el motor disponible marcado; fail levanta; "
            "treat_missing_as_zero asume 0 en el faltante (opt-in sensible: subestima el piso)."
        ),
        json_schema_extra={"ui_widget": "selectbox", "ui_group": "Cobertura", "ui_order": 1},
    )
    numeric_reconciliation: ProvisioningNumericReconciliation = Field(
        default="decimal_quantize",
        title="Cómo reconciliar Decimal (CMF) y float (IFRS 9)",
        description=(
            "decimal_quantize preserva la exactitud regulatoria del CMF como dominio de reporte; "
            "float_isclose usa el dominio económico. Los originales se preservan en el detalle."
        ),
        json_schema_extra={"ui_widget": "selectbox", "ui_group": "Reconciliación", "ui_order": 1},
    )
    tie_tolerance: float = Field(
        default=1e-9,
        ge=0.0,
        title="Tolerancia absoluta de empate",
        description="Tolerancia absoluta para declarar empate (binding='tie') entre ambos motores.",
        json_schema_extra={
            "ui_widget": "number_input",
            "ui_group": "Reconciliación",
            "ui_order": 2,
        },
    )
    rounding: ProvisioningRoundingPolicy = Field(
        default="none",
        title="Redondeo de la provisión reportada",
        description=(
            "Política explícita de redondeo contable del piso reportado; none publica el valor "
            "económico exacto (heredado de D-CMF-5)."
        ),
        json_schema_extra={"ui_widget": "selectbox", "ui_group": "Reconciliación", "ui_order": 3},
    )
    fail_on_falta_dato: bool = Field(
        default=True,
        title="Fallar ante brechas críticas de dato",
        description=(
            "Si es True, una brecha crítica (p. ej. taxonomías de cartera sin crosswalk) falla en "
            "vez de marcar FALTA-DATO."
        ),
        json_schema_extra={"ui_widget": "checkbox", "ui_group": "General", "ui_order": 2},
    )

    @model_validator(mode="after")
    def _check_provisioning(self) -> Self:
        """Valida niveles, motores, crosswalk y reconciliación de SDD-17 §5.

        El nivel ``operation`` exige ``row_id_col`` presente (alineable): la validación de config lo
        asegura por el chequeo de columnas raíz no vacías; la alineación fila-a-fila real es del
        orchestrator (B17.3, §6). El detalle numérico (dominio común, empate) es de runtime.
        """
        _require_non_empty_strings(
            {
                "as_of_date_col": self.as_of_date_col,
                "cmf_portfolio_col": self.cmf_portfolio_col,
                "ifrs9_portfolio_col": self.ifrs9_portfolio_col,
                "row_id_col": self.row_id_col,
            },
            context="provisioning",
        )
        _require_non_empty_if_set({"segment_col": self.segment_col}, context="provisioning")
        crosswalk_vacios = [
            clave
            for clave, valor in self.portfolio_crosswalk.items()
            if not clave.strip() or not valor.strip()
        ]
        if crosswalk_vacios:
            raise ProvisioningConfigError(
                f"portfolio_crosswalk no admite claves ni valores vacíos: {crosswalk_vacios}."
            )
        if self.comparison_level == "segment" and self.segment_col is None:
            raise ProvisioningConfigError("comparison_level='segment' exige segment_col no nulo.")
        if (
            self.comparison_level in ("portfolio", "segment")
            and self.fail_on_falta_dato
            and not self.portfolio_crosswalk
            and self.cmf_portfolio_col != self.ifrs9_portfolio_col
        ):
            raise ProvisioningConfigError(
                f"comparison_level='{self.comparison_level}' con taxonomías de cartera distintas "
                "(cmf_portfolio_col != ifrs9_portfolio_col) exige portfolio_crosswalk explícito "
                "(o fail_on_falta_dato=False para diferirlo a FALTA-DATO)."
            )
        if not self.consume_cmf and not self.consume_ifrs9:
            raise ProvisioningConfigError(
                "consume_cmf y consume_ifrs9 no pueden ser ambos False: no hay nada que orquestar."
            )
        if self.require_both and not (self.consume_cmf and self.consume_ifrs9):
            raise ProvisioningConfigError(
                "require_both=True exige consumir ambos motores (consume_cmf y consume_ifrs9); "
                "un solo motor configurado es una contradicción declarativa."
            )
        return self
