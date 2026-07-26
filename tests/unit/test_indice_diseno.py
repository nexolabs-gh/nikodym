"""Gate del índice maestro de diseño: un SDD que el índice no nombra se pierde.

`docs/design/00-INDICE.md` es la puerta de entrada a los documentos de diseño, y `AGENTS.md` lo
declara como tal en su mapa de documentos. Hasta el 2026-07-25 esa puerta tenía dos documentos
detrás que no se veían desde fuera: `_ENMIENDA-RUN-ERROR.md` y `_ENMIENDA-SEGMENTACION.md`, ambos
**aprobados y ya implementados**. El segundo es B3.a-1, con once decisiones vivas en el código,
incluida la que el contrato de resolución de parámetros manda replicar como patrón de referencia
(D-SEG-7). No estaba mencionado ni por nombre de archivo ni por la palabra «segmentación».

El fallo no fue de quien escribió esas enmiendas: fue que **nada lo comprobaba**. Los SDD numerados
viven en una tabla y es difícil olvidarlos; una enmienda no tiene número ni fila, así que entrar al
índice depende de que alguien se acuerde. Este gate lo convierte en obligación, con el mismo
criterio que el resto de gates del repo: no describe la regla en prosa, la ejecuta.

Cubre el sentido que importa —todo documento existente está indexado—. El sentido simétrico (que el
índice no cite documentos inexistentes) también se verifica, porque un enlace roto manda al lector a
buscar humo, que es el mismo daño al revés.
"""

from __future__ import annotations

import re
from pathlib import Path

_RAIZ = Path(__file__).resolve().parents[2]
_DIRECTORIO = _RAIZ / "docs" / "design"
_INDICE = _DIRECTORIO / "00-INDICE.md"

#: Fila de la tabla de SDD numerados: ``| **07** | `selection` | …``. Un SDD numerado se da por
#: indexado si su número tiene fila, aunque el nombre del archivo no aparezca literal.
_FILA_NUMERADA = re.compile(r"^\| \*\*(\d+)\*\* \|", re.MULTILINE)

#: Referencias a archivos `.md` dentro del propio directorio (enlaces markdown o menciones sueltas).
_ARCHIVO_CITADO = re.compile(r"[\w.-]+\.md")

#: El propio índice y la plantilla no se indexan a sí mismos.
_EXENTOS = frozenset({"00-INDICE.md", "_PLANTILLA-SDD.md"})


def _documentos_en_disco() -> set[str]:
    """Documentos de diseño que existen, sin los que están exentos por definición."""
    return {ruta.name for ruta in _DIRECTORIO.glob("*.md")} - _EXENTOS


def _texto_del_indice() -> str:
    """Contenido del índice maestro."""
    return _INDICE.read_text(encoding="utf-8")


def _numeros_con_fila(texto: str) -> set[str]:
    """Números de SDD que tienen fila propia en la tabla del índice."""
    return set(_FILA_NUMERADA.findall(texto))


def _esta_indexado(nombre: str, texto: str, numerados: set[str]) -> bool:
    """Un documento está indexado si lo nombra el índice o si su número tiene fila en la tabla."""
    if nombre in texto:
        return True
    prefijo = nombre.split("-", 1)[0]
    return prefijo.isdigit() and prefijo in numerados


def test_todo_documento_de_diseno_esta_en_el_indice() -> None:
    """Un documento que el índice no nombra existe sólo para quien ya sabe que existe."""
    texto = _texto_del_indice()
    numerados = _numeros_con_fila(texto)
    sin_indexar = sorted(
        nombre for nombre in _documentos_en_disco() if not _esta_indexado(nombre, texto, numerados)
    )

    assert sin_indexar == [], (
        f"Documentos de diseño que el índice no menciona: {sin_indexar}. "
        f"Añádelos a docs/design/{_INDICE.name} — una enmienda sin fila en la tabla sólo entra al "
        "índice si alguien se acuerda, y por eso existe este gate."
    )


def test_el_indice_no_cita_documentos_inexistentes() -> None:
    """El error simétrico: un enlace a un archivo que ya no está manda al lector a buscar humo."""
    citados = set(_ARCHIVO_CITADO.findall(_texto_del_indice()))
    del_directorio = {nombre for nombre in citados if (_DIRECTORIO / nombre).name in citados}
    inexistentes = sorted(
        nombre
        for nombre in del_directorio
        if not (_DIRECTORIO / nombre).exists()
        # El índice también enlaza fuera de su directorio (ESPECIFICACIONES, ROADMAP); ésos se
        # resuelven contra la raíz de docs/ y no son responsabilidad de este gate.
        and not (_RAIZ / "docs" / nombre).exists()
        and not (_RAIZ / nombre).exists()
    )

    assert inexistentes == [], (
        f"El índice cita documentos que no existen: {inexistentes}. "
        "Corrija el enlace o restituya el archivo."
    )


def test_el_gate_detecta_un_documento_ausente_del_indice() -> None:
    """El gate se prueba a sí mismo: sin esto, un `assert` que nunca falla parece verde.

    Es la misma regla que el resto de gates del repo —un test que fabrica el estado que dice vigilar
    no caza nada—, aplicada al propio criterio de indexado en vez de al filesystem.
    """
    texto = _texto_del_indice()
    numerados = _numeros_con_fila(texto)

    assert not _esta_indexado("_ENMIENDA-QUE-NO-EXISTE.md", texto, numerados)
    # Y no basta con que el nombre se parezca: un número sin fila tampoco cuenta como indexado.
    assert not _esta_indexado("99-capa-inventada.md", texto, numerados)
    # Control positivo: los dos caminos de indexado reconocen lo que sí está.
    assert _esta_indexado("01-core.md", texto, numerados)
    assert _esta_indexado("_ENMIENDA-SEGMENTACION.md", texto, numerados)
