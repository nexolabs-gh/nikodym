"""Esquemas de segmentación y regímenes regulatorios (``_ENMIENDA-SEGMENTACION.md``).

Un **esquema de segmentación** declara el dominio de la llave por la que se agrupan y se resuelven
los parámetros de riesgo: qué valores admite, quién los fija, con qué versión y en qué columna
viajan. Antes de esta enmienda ese dominio no existía en ninguna parte —la llave era un ``str``
libre y cada motor le imponía su propia política—, y sin dominio no se puede resolver un parámetro
*por segmento* ni registrar su procedencia (CRP-1, CRP-3).

Dos ejes que **no** hay que confundir, porque son ortogonales:

* **Quién fija el vocabulario** del esquema (:class:`SchemeOwner`) — de eso trata este módulo.
* **Por qué vía se resuelve un parámetro** (``ParameterSource`` del contrato de resolución) — un
  esquema fijado por el régimen cuyos valores llegan en una columna del dataset es
  :attr:`SchemeOwner.REGIME` como esquema y ``PROVIDED`` como dato.

Este módulo es deliberadamente liviano (sólo ``pydantic``): lo importan los tres motores de
provisiones y el orquestador, y ``import nikodym.provisioning`` debe seguir sin arrastrar pandas.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from types import MappingProxyType
from typing import Final

from pydantic import BaseModel, ConfigDict, Field, model_validator

__all__ = [
    "REGIME_REGISTRY",
    "RegimeSpec",
    "SchemeOwner",
    "SegmentationScheme",
    "known_regimes",
    "regime_scheme",
    "regime_spec",
]


class SchemeOwner(StrEnum):
    """Quién fija el vocabulario de un esquema de segmentación.

    No se reutilizan aquí los nombres de las vías del contrato de parámetros: clasificar el
    **esquema** y clasificar el **dato** son ejes distintos, y mezclarlos induce a error a quien
    implemente CRP-1.
    """

    REGIME = "regime"
    """Lo fija un régimen regulatorio, versionado (p. ej. las carteras del método estándar)."""

    INSTITUTION = "institution"
    """Lo declara la institución en su config (p. ej. sus grupos homogéneos nombrados)."""

    RUNTIME = "runtime"
    """Se construye durante la corrida y **no es enumerable** en un config.

    Es el caso del método interno con ``grouping='score_band'`` —el default—, que deriva las bandas
    por cuantiles de PD dentro de cada cartera. Un esquema así no puede validarse por pertenencia:
    lo que se registra es su procedencia.
    """


class SegmentationScheme(BaseModel):
    """Dominio declarado de una llave de segmentación."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    scheme_id: str = Field(min_length=1)
    owner: SchemeOwner
    version: str = Field(min_length=1)
    column: str = Field(min_length=1)
    values: tuple[str, ...] = ()
    closed: bool = True
    regime: str | None = None

    @model_validator(mode="after")
    def _coherencia_por_dueno(self) -> SegmentationScheme:
        """Cada dueño impone qué puede y qué no puede declarar el esquema."""
        if len(set(self.values)) != len(self.values):
            raise ValueError(f"El esquema {self.scheme_id!r} repite valores en su vocabulario.")
        if self.owner is SchemeOwner.RUNTIME:
            if self.values:
                raise ValueError(
                    f"El esquema {self.scheme_id!r} es de vocabulario derivado en la corrida: no "
                    "puede enumerar valores por adelantado."
                )
            if self.closed:
                raise ValueError(
                    f"El esquema {self.scheme_id!r} es de vocabulario derivado en la corrida, así "
                    "que no puede declararse cerrado: su dominio no existe hasta calcularlo."
                )
        if self.owner is SchemeOwner.REGIME:
            if self.regime is None:
                raise ValueError(
                    f"El esquema {self.scheme_id!r} dice venir de un régimen regulatorio y no "
                    "declara cuál."
                )
            if not self.values:
                raise ValueError(
                    f"El esquema normativo {self.scheme_id!r} no declara su vocabulario; un "
                    "vocabulario normativo vacío no es verificable contra la norma."
                )
            if not self.closed:
                raise ValueError(
                    f"El esquema normativo {self.scheme_id!r} no puede ser abierto: la norma "
                    "enumera sus segmentos."
                )
        return self

    def admits(self, value: str) -> bool:
        """¿El valor pertenece al vocabulario? Un esquema abierto admite cualquiera."""
        if not self.closed:
            return True
        return value in self.values

    def key(self, value: str) -> tuple[str, str]:
        """Llave de resolución de un parámetro por segmento.

        Es ``(esquema, valor)`` y no el valor pelado: dos esquemas distintos pueden tener ambos el
        valor ``consumer`` y colisionarían al resolver.
        """
        return (self.scheme_id, value)


class RegimeSpec(BaseModel):
    """Un régimen regulatorio implementado, con el motor que lo calcula."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    regime_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    """Copy público: lo que el usuario lee al elegir régimen."""

    engine: str = Field(min_length=1)
    """Id del motor que lo implementa. Un régimen sin motor no se declara (regla de honestidad)."""

    scheme: SegmentationScheme


# El vocabulario de carteras del método estándar chileno, declarado UNA vez. `version` es la del
# vocabulario, no la del set de matrices: los segmentos cambian con la norma, las matrices se
# reemplazan con más frecuencia y tienen su propio versionado en el manifiesto.
_CL_CMF_B1_PORTFOLIOS: Final = SegmentationScheme(
    scheme_id="cl-cmf-b1-portfolios",
    owner=SchemeOwner.REGIME,
    regime="CL-CMF-B1",
    version="2025-01",
    column="cmf_portfolio",
    values=(
        "commercial_individual",
        "commercial_group_leasing",
        "commercial_group_student",
        "commercial_group_generic_factoring",
        "consumer",
        "housing",
    ),
    closed=True,
)

# Registro régimen→motor. Es el mecanismo que hace cumplir la regla de honestidad: un régimen sólo
# figura aquí si existe el motor que lo calcula, y un test verifica esa correspondencia. El sistema
# de tipos no puede garantizarlo — ampliar un `Literal` compila igual de bien sin motor detrás.
REGIME_REGISTRY: Final[Mapping[str, RegimeSpec]] = MappingProxyType(
    {
        "CL-CMF-B1": RegimeSpec(
            regime_id="CL-CMF-B1",
            label="Chile — método estándar de la CMF (Cap. B-1)",
            engine="cmf",
            scheme=_CL_CMF_B1_PORTFOLIOS,
        )
    }
)


def known_regimes() -> tuple[str, ...]:
    """Regímenes con motor implementado, en orden estable."""
    return tuple(REGIME_REGISTRY)


def regime_spec(regime_id: str) -> RegimeSpec:
    """Devuelve el régimen registrado, o levanta nombrando los que sí existen."""
    try:
        return REGIME_REGISTRY[regime_id]
    except KeyError:
        conocidos = ", ".join(known_regimes())
        raise KeyError(
            f"Régimen regulatorio {regime_id!r} sin motor en esta versión de Nikodym. "
            f"Regímenes disponibles: {conocidos}."
        ) from None


def regime_scheme(regime_id: str) -> SegmentationScheme:
    """Esquema de segmentación del régimen indicado."""
    return regime_spec(regime_id).scheme


def scheme_by_id(scheme_id: str | None, *, column: str) -> SegmentationScheme | None:
    """Resuelve el esquema que un motor no normativo declara para su columna de cartera.

    Devuelve ``None`` cuando no se declaró ninguno: eso **no** es un error, es el estado de toda
    config anterior a esta enmienda, y aguas arriba activa la red de seguridad de D-SEG-5 en vez de
    romper la corrida. Un id que coincide con el de un esquema normativo conocido resuelve a ése
    —así una institución que usa la taxonomía de la norma puede decirlo y evitarse el crosswalk—; y
    cualquier otro id produce un esquema **institucional abierto**, porque el motor no tiene forma
    de conocer el vocabulario del banco: sólo puede registrar cuál dijo que era.
    """
    if scheme_id is None:
        return None
    for spec in REGIME_REGISTRY.values():
        if spec.scheme.scheme_id == scheme_id:
            return spec.scheme.model_copy(update={"column": column})
    return SegmentationScheme(
        scheme_id=scheme_id,
        owner=SchemeOwner.INSTITUTION,
        version="declarado",
        column=column,
        closed=False,
    )
