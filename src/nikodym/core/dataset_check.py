"""Compara un config con las columnas de un dataset **sin correr nada**.

Responde una pregunta que ``check_pipeline`` no puede responder: aquélla resuelve si el pipeline es
*ejecutable* como config, pero **no lee el dataset** (SDD-23, D-PIPE-1), así que un config
perfectamente ejecutable puede referirse a columnas que el archivo del usuario no tiene. Medido
sobre `1.8.0` desde PyPI: un CSV con nombres de columna propios exige **seis** ediciones del preset
F1 en seis lugares distintos, y el motor las revela **de a una** —cada corrida fallida destapa la
siguiente—. Los mensajes del motor son buenos; lo que faltaba era verlos todos juntos y antes de
pagar una corrida (enmienda `_ENMIENDA-PREFLIGHT-DATASET.md`, D-PRE-1…D-PRE-8).

**Sólo se exigen las columnas de ENTRADA** (D-PRE-3). Un campo de config que nombra una columna
puede referirse a una que el usuario debe traer (``cohort_col``) o a una que **produce el propio
pipeline** (``score_column``, ``pd_column``, ``partition_column``): de los 26 campos del camino F1
que nombran columnas, sólo seis son de entrada. Exigir las derivadas daría falsos positivos en la
mayoría de los campos, y no distinguirlas haría la comprobación inútil.

El rol vive en el ``Field`` de cada campo, junto a su declaración, y no en un registro central: es
una propiedad del campo, no un criterio transversal —a diferencia de
:func:`~nikodym.core.markers.governable_warnings`, que sí lo es—. El vocabulario lo vigila
``tests/unit/test_column_roles.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

    from nikodym.core.config import NikodymConfig

#: Clave que marca, dentro de ``json_schema_extra``, qué papel juega la columna que nombra el campo.
CLAVE_ROL = "column_role"

#: La columna la aporta el usuario en su dataset: si no está, la corrida fallará.
ROL_ENTRADA = "input"

#: La columna la produce el pipeline (score, PD, partición…): NO debe existir en el dataset crudo.
ROL_DERIVADA = "derived"

#: El campo nombra el **índice** del DataFrame, no una columna: ``data.schema.index_col``.
ROL_INDICE = "index"

#: El nombre del campo calza con el patrón ``*_columns`` pero NO nombra ninguna columna.
#:
#: Existe para que la excepción quede **declarada** y no parezca un olvido:
#: ``keep_structural_columns`` es un ``bool`` que decide si se conservan las columnas
#: estructurales, no una lista de nombres. Clasificar por el nombre del campo es justo el error
#: que este vocabulario evita.
ROL_NO_COLUMNA = "not_a_column"

ROLES = frozenset({ROL_ENTRADA, ROL_DERIVADA, ROL_INDICE, ROL_NO_COLUMNA})

#: Comodín de ``feature_columns``: «todas las disponibles». No es un nombre de columna.
COMODIN = "*"

#: Nombre del método con que una config de sección declara sus **invariantes previas**
#: (enmienda INVARIANTES-PREVIAS, D-INV-1). Es una convención de nombre y no una clase base a
#: propósito: las configs de dominio no deben heredar del núcleo para poder declarar algo suyo.
METODO_REQUISITOS = "requisitos_incumplidos"

TipoDesajuste = Literal[
    "missing_column", "index_not_a_column", "missing_index", "unmet_requirement"
]


@dataclass(frozen=True, slots=True)
class Requisito:
    """Una exigencia del propio config que la corrida va a incumplir (D-INV-1).

    A diferencia de un :class:`Mismatch` por columna, aquí **no falta ningún nombre de columna**:
    lo que falla es una combinación de campos —``temporal_axis`` ≠ ``none`` sin columna de período,
    ``comparisons`` con duplicados, ``families`` vacío—. El motor ya lo diagnostica bien; lo que
    faltaba era decirlo **antes** de pagar la corrida.
    """

    path: str
    """Ruta **RELATIVA** del campo que lo arregla, dentro de su sección (``temporal_axis``).

    Relativa a propósito (D-INV-5): la sección no sabe dónde está montada, y es el recorrido quien
    le antepone el prefijo. Así el dominio declara su invariante sin conocer al formulario que la
    va a pintar.
    """

    declared: str
    """El valor que crea la exigencia (``"period"``), para que el aviso sea concreto."""

    message: str
    """Copy público, en español y sin códigos internos, y **con la salida** (D-INV-6)."""


@dataclass(frozen=True, slots=True)
class Mismatch:
    """Un desajuste concreto entre lo que el config nombra y lo que el dataset trae."""

    path: str
    """Ruta del campo en el config, con los alias serializados (``data.partition.strategy…``).

    Es la ruta que el formulario necesita para poder enfocar el campo, así que usa el alias
    publicado —``data.schema``— y no el nombre Python del atributo —``schema_``—.
    """

    declared: str
    """Lo que el config declara y el dataset no satisface.

    ⚠️ **No siempre es un nombre de columna**, y por eso no se llama ``column``: con
    ``kind="unmet_requirement"`` transporta el valor que incumple el requisito
    —``"period"``, ``"desarrollo, desarrollo"``, ``"(ninguna)"``—, que no nombra ninguna columna.
    Ningún consumidor debe presentarlo como columna sin mirar antes ``kind``.
    """

    kind: TipoDesajuste
    """Qué es lo que no calza.

    Los tres primeros hablan de una columna: ``missing_column`` (no existe),
    ``index_not_a_column`` (existe, pero como columna corriente donde se esperaba el índice) y
    ``missing_index`` (se esperaba el índice y el nombre no está **ni** en el índice **ni** entre
    las columnas). El cuarto **no**: ``unmet_requirement`` es una invariante interna del config que
    el dataset no puede satisfacer —p. ej. un eje temporal activo sobre un archivo sin columna de
    período—, así que ``declared`` no trae una columna (D-INV-1…D-INV-9).
    """

    message: str
    """Copy público, en español y sin códigos internos: lo lee el usuario tal cual (D-PRE-8)."""


@dataclass(frozen=True, slots=True)
class DatasetCheck:
    """Veredicto de compatibilidad entre un config y las columnas de un dataset."""

    compatible: bool
    mismatches: tuple[Mismatch, ...] = field(default=())

    uninspected: tuple[str, ...] = field(default=())
    """Secciones que quedaron opacas y **no se pudieron mirar** (D-PRE-9).

    Una sección sin coaccionar no tiene `Field` que consultar, así que sobre ella la comprobación
    no sabe nada. Van aparte de ``mismatches`` porque no son un desajuste —no se afirma que estén
    mal— pero **impiden declarar compatible**: decir «todo bien» sobre lo que no se miró es la
    peor respuesta posible para quien está a punto de lanzar una corrida.
    """


def _alias(modelo: type[BaseModel], nombre: str) -> str:
    """Alias serializado del campo, que es el que ve el formulario (``schema_`` → ``schema``)."""
    info = modelo.model_fields.get(nombre)
    return (info.alias if info is not None and info.alias else nombre) or nombre


def _rol(modelo: type[BaseModel], nombre: str) -> str | None:
    """Rol declarado en el ``Field``, o ``None`` si el campo no nombra ninguna columna."""
    info = modelo.model_fields.get(nombre)
    extra = getattr(info, "json_schema_extra", None) if info is not None else None
    if not isinstance(extra, dict):
        return None
    valor = extra.get(CLAVE_ROL)
    return valor if isinstance(valor, str) else None


def _declaraciones(config: Any, prefijo: str = "") -> Iterator[tuple[str, str, str]]:
    """Recorre el config y emite ``(ruta, rol, columna)`` por cada columna declarada.

    Camina modelos Pydantic anidados, listas y tuplas. Una sección que viaje como ``dict`` —el
    *blob* opaco del núcleo liviano, SDD-23 §4.1— **se salta**: sin su modelo no hay `Field` que
    consultar, y adivinar el rol por el nombre del campo sería exactamente el criterio disperso que
    D-PRE-3 evita. Quien necesite inspeccionarla la coacciona antes (como hace `/api/preflight`).
    """
    if isinstance(config, BaseModel):
        modelo = type(config)
        for nombre in type(config).model_fields:
            valor = getattr(config, nombre, None)
            ruta = f"{prefijo}{_alias(modelo, nombre)}"
            rol = _rol(modelo, nombre)
            if rol in ROLES:
                for columna in _columnas_de(valor):
                    yield ruta, rol, columna
            yield from _declaraciones(valor, f"{ruta}.")
        return

    if isinstance(config, (list, tuple)):
        for i, elemento in enumerate(config):
            if isinstance(elemento, BaseModel):
                yield from _declaraciones(elemento, f"{prefijo.rstrip('.')}[{i}].")


def _requisitos(
    config: Any, columnas: frozenset[str] | None, prefijo: str = ""
) -> Iterator[tuple[str, Requisito]]:
    """Recorre el config y emite ``(ruta absoluta, requisito)`` por cada invariante incumplida.

    Camina igual que :func:`_declaraciones` —modelos anidados, listas y tuplas— y en cada modelo
    pregunta por el protocolo :data:`METODO_REQUISITOS`. Una sección que viaje como ``dict`` opaco
    se salta por la misma razón de siempre: sin su modelo no hay método al que preguntar.

    El dominio devuelve rutas **relativas** y aquí se les antepone el prefijo (D-INV-5).
    """
    if not isinstance(config, BaseModel):
        if isinstance(config, (list, tuple)):
            for i, elemento in enumerate(config):
                yield from _requisitos(elemento, columnas, f"{prefijo.rstrip('.')}[{i}].")
        return

    metodo = getattr(config, METODO_REQUISITOS, None)
    if callable(metodo):
        for requisito in metodo(columnas):
            yield f"{prefijo}{requisito.path}", requisito

    modelo = type(config)
    for nombre in modelo.model_fields:
        yield from _requisitos(
            getattr(config, nombre, None), columnas, f"{prefijo}{_alias(modelo, nombre)}."
        )


def _columnas_de(valor: Any) -> tuple[str, ...]:
    """Normaliza el valor de un campo de columna a una tupla de nombres reales.

    Descarta el :data:`COMODIN` y los no-``str`` (``None``, el ``bool`` de un campo que sólo parece
    de columnas): lo que queda son nombres que el dataset puede satisfacer o no.
    """
    if isinstance(valor, bool):  # antes que `str`/secuencia: un bool no nombra nada
        return ()
    if isinstance(valor, str):
        return () if valor == COMODIN else (valor,)
    if isinstance(valor, (list, tuple)):
        return tuple(x for x in valor if isinstance(x, str) and x != COMODIN)
    return ()


def _mensaje_falta(ruta: str, columna: str) -> str:
    return (
        f"El dataset no tiene la columna «{columna}», que el config declara en {ruta}. "
        f"Corrige el nombre en ese campo o usa un dataset que sí la traiga."
    )


def _mensaje_indice(ruta: str, columna: str) -> str:
    return (
        f"«{columna}» existe en el dataset, pero como columna corriente, y {ruta} espera que sea "
        f"el índice. Un archivo CSV no puede transportar un índice: deja ese campo vacío y declara "
        f"«{columna}» en las columnas esperadas o en las llaves de unicidad."
    )


def _mensaje_indice_ausente(ruta: str, columna: str) -> str:
    return (
        f"El dataset no tiene «{columna}» ni en el índice ni entre sus columnas, y {ruta} lo "
        f"declara como identificador de observación. Corrige el nombre en ese campo o deja el "
        f"campo vacío para que la corrida numere las filas."
    )


def check_dataset(
    config: NikodymConfig,
    columns: Sequence[str],
    *,
    index_columns: Sequence[str] | None = None,
) -> DatasetCheck:
    """Compara ``config`` con los nombres de columna de un dataset, sin ejecutarlo ni leerlo.

    Es **total**: devuelve *todos* los desajustes de una vez (D-PRE-2), que es su razón de existir
    —cortar en el primero reproduce el problema que viene a resolver—. Y es **informativo**: no
    bloquea nada (D-PRE-5), igual que :func:`~nikodym.check_pipeline`; la corrida sigue siendo la
    autoridad sobre sí misma.

    Parameters
    ----------
    config : NikodymConfig
        Config ya reconstruido. Las secciones que viajen como ``dict`` opaco se omiten.
    columns : Sequence[str]
        Nombres de las columnas del dataset, **sin el índice**. La UI los tiene sin leer el
        archivo: los devuelve ``POST /api/upload``.
    index_columns : Sequence[str] | None, optional
        Nombres que el dataset lleva en el **índice**. Su ausencia (``None``) significa «no se
        sabe», no «no hay»: sin ese dato un ``index_col`` que no aparece en ``columns`` es
        indistinguible de uno correcto —el índice, por definición, no está entre las columnas—, y
        afirmar que falta sería el falso positivo más caro posible (el dataset del catálogo contra
        su propio preset). Sólo cuando se declaran los índices se puede emitir ``missing_index``.

    Returns
    -------
    DatasetCheck
        ``compatible=True`` y sin desajustes, o el detalle de cada uno con su ruta de config.
    """
    # Igual que ``config_hash`` desde 1.8.0 (D-HASH-1): se mira el config que *se ejecutaría*, no
    # el que se escribió. Sin esto, un proceso que no haya importado la capa de dominio recorre
    # secciones opacas, no encuentra ni un solo campo y devuelve un `compatible=True` vacío.
    from nikodym.core.config.hashing import _coaccionar_secciones_opacas

    config = _coaccionar_secciones_opacas(config)

    presentes = set(columns)
    indices = None if index_columns is None else set(index_columns)
    desajustes: list[Mismatch] = []
    opacas = tuple(
        nombre
        for nombre in type(config).model_fields
        if isinstance(getattr(config, nombre, None), dict)
    )

    for ruta, rol, columna in _declaraciones(config):
        if rol in (ROL_DERIVADA, ROL_NO_COLUMNA):
            continue  # la produce el pipeline (o no es columna): exigirla sería un falso positivo
        if rol == ROL_INDICE:
            # El índice no está entre las columnas; que su nombre SÍ lo esté es el síntoma de un
            # dataset tabular plano (típicamente un CSV) contra un config que espera índice.
            if columna in presentes:
                desajustes.append(
                    Mismatch(ruta, columna, "index_not_a_column", _mensaje_indice(ruta, columna))
                )
            elif indices is not None and columna not in indices:
                # Tercer caso: ni índice ni columna. Antes no tenía rama y se iba en silencio, así
                # que el preflight devolvía `compatible=True` sobre un config que la corrida
                # rechaza en el primer paso — exactamente el «todo bien» sobre lo no mirado que
                # D-PRE-9 declara la peor respuesta posible. Sólo se puede afirmar con los índices
                # del dataset en la mano: ver `index_columns`.
                desajustes.append(
                    Mismatch(ruta, columna, "missing_index", _mensaje_indice_ausente(ruta, columna))
                )
            continue
        if columna not in presentes:
            desajustes.append(
                Mismatch(ruta, columna, "missing_column", _mensaje_falta(ruta, columna))
            )

    # Invariantes previas (D-INV-1/D-INV-2): lo que el config se exige a sí mismo y no cumple. No
    # hay columna que falte —el desajuste es entre campos—, así que las declara el dominio que las
    # impone y no este recorrido. Aquí las columnas SIEMPRE se conocen (son parámetro obligatorio),
    # así que van completas; el `None` del protocolo es para un consumidor que no las tenga, y
    # significa «no se sabe», no «no hay» (D-INV-4).
    for ruta, requisito in _requisitos(config, frozenset(presentes)):
        desajustes.append(
            Mismatch(ruta, requisito.declared, "unmet_requirement", requisito.message)
        )

    return DatasetCheck(
        compatible=not desajustes and not opacas,
        mismatches=tuple(desajustes),
        uninspected=opacas,
    )
