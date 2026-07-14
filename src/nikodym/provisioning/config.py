"""Config declarativo de la capa de orquestación ``provisioning`` (SDD-17 §5).

:class:`ProvisioningConfig` es la sección ``provisioning`` de
:class:`~nikodym.core.config.NikodymConfig`: la **capa fina** que compara **dos fuentes de
provisión configurables** (``source_a`` y ``source_b``), aplica la **regla** declarada (``rule``) al
nivel de agregación configurado y publica el comparativo auditable. Hereda de
:class:`~nikodym.core.config.NikodymBaseConfig` (``extra='forbid'`` y ``frozen=True``); cada campo
declara ``title``/``description`` y metadatos ``ui_*`` para que la UI (SDD-23) sea un editor del
mismo config.

.. warning::

   **Corrección normativa (2026-07-13).** Este módulo afirmaba que "la regla del máximo es norma
   citada (ESPEC §5.4)" y cableaba la comparación a ``max(CMF, IFRS 9)``. Era **falso**: ESPEC §5.4
   es un documento interno de este proyecto que no citaba norma alguna. Verificado contra el
   Compendio de Normas Contables para Bancos (CMF):

   - **Cap. B-1, hoja 10-11 (Circular N° 2.346 / 06.03.2024)**: *"La constitución de provisiones
     se efectuará considerando el mayor valor obtenido entre el respectivo método estándar y el
     método interno. En el caso de uso de los métodos internos evaluados y no objetados (…) la
     constitución de provisiones se efectuará de acuerdo con los resultados de su aplicación. Esta
     regla se deberá aplicar para cada institución en Chile que consolida con el banco"*. La regla
     del máximo es **estándar vs. interno, a nivel de entidad**; y con método interno **evaluado y
     no objetado** se usa el **interno directamente** (``rule='use_internal'``).
   - **Cap. A-2, num. 5**: el Capítulo 5.5 (deterioro) de NIIF 9 **no se aplica** a las colocaciones
     ni a los créditos contingentes; sus criterios los define la CMF en B-1 a B-3.

   Por tanto ``max(CMF, IFRS 9)`` **no es "el piso prudencial de la CMF"** y no debe presentarse
   como tal. Comparar ambos marcos sigue siendo útil (p. ej. una filial que reporta ECL a su matriz
   extranjera), pero es un comparativo **entre marcos contables**, no una exigencia local. Por
   retrocompatibilidad los defaults siguen siendo ``source_a='provisioning_cmf'`` y
   ``source_b='provisioning_ifrs9'``; la comparación que **sí** exige la norma chilena se declara
   con ``source_b='provisioning_internal'`` (SDD-28).

La sección es **computacional, no infraestructura** (``provisioning`` ∉ ``INFRA_SECTIONS``): cambiar
las fuentes, la regla, el nivel de comparación, la clave/crosswalk de cartera, la política de
cobertura o la reconciliación numérica **cambia el ``config_hash`` global**.

Frontera B17.1: aquí solo viven el schema y sus validaciones determinables sin datos. La *presencia*
de columnas/claves en los detalles de cada motor es un contrato de runtime que valida el
orchestrator (§6/§8), de modo que ``ProvisioningConfig()`` siga construyendo sin argumentos.

**Experimental (fuera de la garantía SemVer 1.x).**
"""

from __future__ import annotations

import warnings
from typing import Literal, Self

from pydantic import Field, model_validator

from nikodym.core.config import NikodymBaseConfig
from nikodym.provisioning.exceptions import ProvisioningConfigError

ProvisioningComparisonLevel = Literal["total", "portfolio", "segment", "operation"]
ProvisioningCoveragePolicy = Literal["use_available", "fail", "treat_missing_as_zero"]
ProvisioningNumericReconciliation = Literal["decimal_quantize", "float_isclose"]
ProvisioningRoundingPolicy = Literal["none", "currency_2dp", "integer_currency"]
ProvisioningSource = Literal["provisioning_cmf", "provisioning_internal", "provisioning_ifrs9"]
ProvisioningRule = Literal["max", "use_internal"]

CMF_SOURCE: ProvisioningSource = "provisioning_cmf"
INTERNAL_SOURCE: ProvisioningSource = "provisioning_internal"
IFRS9_SOURCE: ProvisioningSource = "provisioning_ifrs9"

# Nombre corto y legible de cada fuente: es el que viaja en ``binding`` / ``coverage`` /
# ``engines_present`` para que la card diga QUÉ fuente ganó, sin obligar al lector a traducir un
# rol ("a"/"b") a un motor.
SOURCE_NAMES: dict[str, str] = {
    CMF_SOURCE: "cmf",
    INTERNAL_SOURCE: "internal",
    IFRS9_SOURCE: "ifrs9",
}

__all__ = [
    "CMF_SOURCE",
    "IFRS9_SOURCE",
    "INTERNAL_SOURCE",
    "SOURCE_NAMES",
    "ProvisioningComparisonLevel",
    "ProvisioningConfig",
    "ProvisioningCoveragePolicy",
    "ProvisioningNumericReconciliation",
    "ProvisioningRoundingPolicy",
    "ProvisioningRule",
    "ProvisioningSource",
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
    source_a: ProvisioningSource = Field(
        default=CMF_SOURCE,
        title="Fuente A de la comparación",
        description=(
            "Dominio del primer resultado a comparar. El default (provisioning_cmf = método "
            "estándar del B-1) es el operando que la norma chilena pone a la izquierda del máximo."
        ),
        json_schema_extra={"ui_widget": "selectbox", "ui_group": "Fuentes", "ui_order": 1},
    )
    source_b: ProvisioningSource = Field(
        default=IFRS9_SOURCE,
        title="Fuente B de la comparación",
        description=(
            "Dominio del segundo resultado a comparar. El default (provisioning_ifrs9) preserva el "
            "comportamiento histórico; la comparación que EXIGE la norma chilena (Cap. B-1, hoja "
            "10-11) es contra provisioning_internal (método interno del banco)."
        ),
        json_schema_extra={"ui_widget": "selectbox", "ui_group": "Fuentes", "ui_order": 2},
    )
    rule: ProvisioningRule = Field(
        default="max",
        title="Regla de constitución de la provisión reportada",
        description=(
            "max: se reporta el mayor valor entre ambas fuentes (Cap. B-1, hoja 10-11, para "
            "estándar vs. interno). use_internal: el método interno está evaluado y NO objetado "
            "por la Comisión, y la provisión se constituye según el interno aunque el estándar "
            "sea mayor (mismo párrafo); exige que provisioning_internal sea una de las fuentes."
        ),
        json_schema_extra={"ui_widget": "selectbox", "ui_group": "Fuentes", "ui_order": 3},
    )
    as_of_date_col: str = Field(
        default="as_of_date",
        title="Fecha de cálculo (heredada de las fuentes)",
        description="Columna con la fecha de cálculo/cierre contable, heredada de las fuentes.",
        json_schema_extra={"ui_widget": "text_input", "ui_group": "Columnas", "ui_order": 1},
    )
    comparison_level: ProvisioningComparisonLevel = Field(
        default="total",
        title="Nivel de agregación de la regla",
        description=(
            "**La norma fija el nivel**: el Cap. B-1 (hoja 10-11) manda aplicar la regla 'para "
            "cada "
            "institución en Chile que consolida con el banco', esto es, a nivel de ENTIDAD -> "
            "'total' (el default). 'portfolio', 'segment' y 'operation' son DIAGNÓSTICOS (¿dónde "
            "muerde el estándar?), no la regla: el máximo por celda sobre-reporta respecto del "
            "máximo de entidad (Σ max ≥ max Σ) y no es la provisión a constituir."
        ),
        json_schema_extra={"ui_widget": "selectbox", "ui_group": "Comparación", "ui_order": 1},
    )
    cmf_portfolio_col: str = Field(
        default="portfolio",
        title="Columna de cartera en el detail del motor CMF",
        description="Columna de cartera del resultado CMF para agrupar la comparación.",
        json_schema_extra={"ui_widget": "text_input", "ui_group": "Columnas", "ui_order": 2},
    )
    ifrs9_portfolio_col: str = Field(
        default="portfolio",
        title="Columna de cartera en el detail del motor IFRS 9",
        description="Columna de cartera del resultado IFRS 9 para agrupar la comparación.",
        json_schema_extra={"ui_widget": "text_input", "ui_group": "Columnas", "ui_order": 3},
    )
    internal_portfolio_col: str = Field(
        default="portfolio",
        title="Columna de cartera en el detail del método interno",
        description="Columna de cartera del resultado del método interno (SDD-28) para agrupar.",
        json_schema_extra={"ui_widget": "text_input", "ui_group": "Columnas", "ui_order": 4},
    )
    portfolio_crosswalk: dict[str, str] = Field(
        default_factory=dict,
        title="Mapeo cartera de la fuente A → cartera de la fuente B (si difieren)",
        description=(
            "Crosswalk explícito de la taxonomía de cartera de la fuente A a la de la fuente B "
            "cuando no comparten clave; nunca se adivina por similitud (D-PROV-3, R0)."
        ),
        json_schema_extra={"ui_widget": "kv_text", "ui_group": "Comparación", "ui_order": 2},
    )
    segment_col: str | None = Field(
        default=None,
        title="Columna de segmento (comparison_level='segment')",
        description="Columna de segmento provista por el usuario para comparar por segmento.",
        json_schema_extra={"ui_widget": "text_input", "ui_group": "Columnas", "ui_order": 5},
    )
    row_id_col: str = Field(
        default="row_id",
        title="Identificador de operación (comparison_level='operation')",
        description="Columna identificadora de operación para alinear el nivel más granular.",
        json_schema_extra={"ui_widget": "text_input", "ui_group": "Columnas", "ui_order": 6},
    )
    consume_a: bool = Field(
        default=True,
        title="Consumir el resultado de la fuente A si está presente",
        description="Si es True, la orquestación consume el resultado publicado por source_a.",
        json_schema_extra={"ui_widget": "checkbox", "ui_group": "Fuentes", "ui_order": 4},
    )
    consume_b: bool = Field(
        default=True,
        title="Consumir el resultado de la fuente B si está presente",
        description="Si es True, la orquestación consume el resultado publicado por source_b.",
        json_schema_extra={"ui_widget": "checkbox", "ui_group": "Fuentes", "ui_order": 5},
    )
    consume_cmf: bool | None = Field(
        default=None,
        title="[DEPRECADO] Consumir el resultado CMF",
        description=(
            "DEPRECADO (usa consume_a/consume_b según la posición de provisioning_cmf). Si se "
            "informa, manda sobre el consume_* de la ranura que ocupa provisioning_cmf y emite "
            "DeprecationWarning. None = no informado."
        ),
        json_schema_extra={"ui_widget": "hidden", "ui_group": "Fuentes", "ui_order": 6},
    )
    consume_ifrs9: bool | None = Field(
        default=None,
        title="[DEPRECADO] Consumir el resultado IFRS 9",
        description=(
            "DEPRECADO (usa consume_a/consume_b según la posición de provisioning_ifrs9). Si se "
            "informa, manda sobre el consume_* de la ranura que ocupa provisioning_ifrs9 y emite "
            "DeprecationWarning. None = no informado."
        ),
        json_schema_extra={"ui_widget": "hidden", "ui_group": "Fuentes", "ui_order": 7},
    )
    require_both: bool = Field(
        default=True,
        title="Exigir ambas fuentes (si no, passthrough de la disponible)",
        description=(
            "La regla presupone ambas fuentes; con False degrada a passthrough marcado de la "
            "disponible (comparación incompleta, FALTA-DATO)."
        ),
        json_schema_extra={"ui_widget": "checkbox", "ui_group": "Fuentes", "ui_order": 8},
    )
    coverage_policy: ProvisioningCoveragePolicy = Field(
        default="use_available",
        title="Política ante celda cubierta por una sola fuente",
        description=(
            "use_available reporta la fuente disponible marcada; fail levanta; "
            "treat_missing_as_zero asume 0 en la faltante (opt-in sensible: subestima la regla)."
        ),
        json_schema_extra={"ui_widget": "selectbox", "ui_group": "Cobertura", "ui_order": 1},
    )
    numeric_reconciliation: ProvisioningNumericReconciliation = Field(
        default="decimal_quantize",
        title="Cómo reconciliar dominios numéricos (Decimal vs float)",
        description=(
            "decimal_quantize preserva la exactitud regulatoria del Decimal como dominio de "
            "reporte; float_isclose usa el dominio económico. Los originales se preservan en el "
            "detalle (CMF y el método interno publican Decimal; IFRS 9 publica float)."
        ),
        json_schema_extra={"ui_widget": "selectbox", "ui_group": "Reconciliación", "ui_order": 1},
    )
    tie_tolerance: float = Field(
        default=1e-9,
        ge=0.0,
        title="Tolerancia absoluta de empate",
        description="Tolerancia absoluta para declarar empate (binding='tie') entre ambas fuentes.",
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
            "Política explícita de redondeo contable de la provisión reportada; none publica el "
            "valor económico exacto (heredado de D-CMF-5)."
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

    @property
    def sources(self) -> tuple[ProvisioningSource, ProvisioningSource]:
        """Par ordenado de dominios comparados ``(source_a, source_b)``."""
        return (self.source_a, self.source_b)

    @property
    def consume_source_a(self) -> bool:
        """Consumo efectivo de la fuente A (el flag deprecado de su dominio manda si se informó)."""
        legacy = self._legacy_consume(self.source_a)
        return self.consume_a if legacy is None else legacy

    @property
    def consume_source_b(self) -> bool:
        """Consumo efectivo de la fuente B (el flag deprecado de su dominio manda si se informó)."""
        legacy = self._legacy_consume(self.source_b)
        return self.consume_b if legacy is None else legacy

    def _legacy_consume(self, source: ProvisioningSource) -> bool | None:
        """Devuelve el flag ``consume_*`` deprecado del dominio, o ``None`` si no se informó."""
        if source == CMF_SOURCE:
            return self.consume_cmf
        if source == IFRS9_SOURCE:
            return self.consume_ifrs9
        return None

    def portfolio_col_for(self, source: ProvisioningSource) -> str:
        """Columna de cartera declarada para el ``detail`` de la fuente indicada."""
        if source == CMF_SOURCE:
            return self.cmf_portfolio_col
        if source == IFRS9_SOURCE:
            return self.ifrs9_portfolio_col
        return self.internal_portfolio_col

    @model_validator(mode="after")
    def _check_provisioning(self) -> Self:
        """Valida fuentes, regla, niveles, crosswalk y consumo de SDD-17 §5.

        El nivel ``operation`` exige ``row_id_col`` presente (alineable): la validación de config lo
        asegura por el chequeo de columnas raíz no vacías; la alineación fila-a-fila real es del
        orchestrator (§6). El detalle numérico (dominio común, empate) es de runtime.
        """
        _require_non_empty_strings(
            {
                "as_of_date_col": self.as_of_date_col,
                "cmf_portfolio_col": self.cmf_portfolio_col,
                "ifrs9_portfolio_col": self.ifrs9_portfolio_col,
                "internal_portfolio_col": self.internal_portfolio_col,
                "row_id_col": self.row_id_col,
            },
            context="provisioning",
        )
        _require_non_empty_if_set({"segment_col": self.segment_col}, context="provisioning")
        self._check_fuentes_y_regla()
        self._check_crosswalk()
        self._check_consumo()
        return self

    def _check_fuentes_y_regla(self) -> None:
        """Exige fuentes distintas y que ``use_internal`` tenga el método interno entre ellas."""
        if self.source_a == self.source_b:
            raise ProvisioningConfigError(
                f"source_a y source_b no pueden ser la misma fuente ({self.source_a!r}): comparar "
                "un resultado consigo mismo no es una comparación."
            )
        if self.rule == "use_internal" and INTERNAL_SOURCE not in self.sources:
            raise ProvisioningConfigError(
                "rule='use_internal' exige que 'provisioning_internal' sea una de las fuentes "
                "(source_a/source_b): la norma permite constituir según el método interno evaluado "
                f"y no objetado, y aquí no hay método interno que reportar: {self.sources!r}."
            )

    def _check_crosswalk(self) -> None:
        """Valida el crosswalk de carteras y su exigibilidad según el nivel de comparación."""
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
        col_a = self.portfolio_col_for(self.source_a)
        col_b = self.portfolio_col_for(self.source_b)
        if (
            self.comparison_level in ("portfolio", "segment")
            and self.fail_on_falta_dato
            and not self.portfolio_crosswalk
            and col_a != col_b
        ):
            raise ProvisioningConfigError(
                f"comparison_level='{self.comparison_level}' con taxonomías de cartera distintas "
                f"({col_a!r} en {self.source_a} != {col_b!r} en {self.source_b}) exige "
                "portfolio_crosswalk explícito (o fail_on_falta_dato=False para diferirlo a "
                "FALTA-DATO)."
            )

    def _check_consumo(self) -> None:
        """Resuelve los ``consume_*`` deprecados, avisa de su uso y valida ``require_both``."""
        deprecados = {
            "consume_cmf": (self.consume_cmf, CMF_SOURCE),
            "consume_ifrs9": (self.consume_ifrs9, IFRS9_SOURCE),
        }
        informados = [nombre for nombre, (valor, _) in deprecados.items() if valor is not None]
        for nombre in informados:
            _, dominio = deprecados[nombre]
            if dominio not in self.sources:
                raise ProvisioningConfigError(
                    f"{nombre} solo aplica si {dominio!r} es una de las fuentes; las fuentes "
                    f"declaradas son {self.sources!r}. Usa consume_a/consume_b."
                )
        if informados:
            warnings.warn(
                f"{', '.join(informados)} está(n) DEPRECADO(s) en ProvisioningConfig: la "
                "orquestación compara fuentes configurables (source_a/source_b). Usa consume_a / "
                "consume_b según la ranura que ocupe cada motor.",
                DeprecationWarning,
                stacklevel=2,
            )
        if not self.consume_source_a and not self.consume_source_b:
            raise ProvisioningConfigError(
                "consume_a y consume_b no pueden ser ambos False: no hay nada que orquestar."
            )
        if self.require_both and not (self.consume_source_a and self.consume_source_b):
            raise ProvisioningConfigError(
                "require_both=True exige consumir ambas fuentes (consume_a y consume_b); una sola "
                "fuente configurada es una contradicción declarativa."
            )
