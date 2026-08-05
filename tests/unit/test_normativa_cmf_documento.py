"""Gate: el documento normativo CMF y el manifiesto del bundle dicen lo mismo.

🔴 **Por qué existe.** El 2026-08-04 el copy publicado llamó «cotejo cerrado el 2026-06-23» a lo
que el manifiesto declara como ``extraction_date``, existiendo un cotejo **posterior y más fuerte**
—la matriz de consumo, celda por celda contra el compendio consolidado, el **2026-07-14**— escrito
en el propio ``docs/normativa_cmf_parametros.md`` que el texto enlazaba. La afirmación estaba en
cinco superficies, incluida la que se empaqueta en el wheel, y **la refutaba su propia fuente**.

Lo cazó un revisor adversarial leyendo la fuente. **Ninguna suite podía verlo**: el ``.sha256`` del
bundle cubre el YAML de matrices, no el manifiesto ni el documento, y hasta hoy *ningún test abría
el ``.md``* — las tres apariciones de su ruta en ``tests/`` son literales de string comparados
contra el ``source_reference`` que construye el motor, y nada comprobaba que esas secciones
existieran.

En un producto de riesgo eso no es una errata: las dos superficies son la trazabilidad de una tabla
que un banco usa para provisionar, y se escriben **a mano en sitios distintos**.

**Cómo se ata.** El manifiesto es dato estructurado y el documento es prosa, así que el gate
**deriva del manifiesto** —no enumera a mano— y exige que cada dato que publica esté sostenido por
el documento: fechas, anclas de sección, URLs y circulares. Añade dos cruces internos del
manifiesto (toda circular que gobierna una matriz está entre las fuentes declaradas; todo
``source_ref`` usado está en ``normativa_refs``) y **una dirección inversa acotada**: las fechas de
verificación que el documento publica tienen que ser conocidas por el manifiesto — que es
exactamente la clase del defecto de arriba.

⚠️ **Lo que NO hace, dicho en vez de callado.** La inversa completa —que todo lo que el documento
dice esté en el manifiesto— produciría falsos positivos legítimos: el §7 lista **ocho** fuentes y el
manifiesto **cinco**, porque tres son de navegación y contexto que el bundle no consume. Tampoco
valida los **valores** de las tablas: eso lo cubre ``test_cmf_matrices.py`` contra el YAML, y la
verificación contra el texto oficial es humana (B5 del ROADMAP, abierto).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

_RAIZ = Path(__file__).resolve().parents[2]
_DOC = _RAIZ / "docs" / "normativa_cmf_parametros.md"
_MANIFIESTO = _RAIZ / "src" / "nikodym" / "provisioning" / "cmf" / "data" / "manifest.json"

# Un número de circular es ``N.NNN``; el lookaround evita capturar el tramo final de una ley o
# resolución de más dígitos (``Ley N° 20.027`` no es la circular ``0.027``).
_NUMERO_CIRCULAR = re.compile(r"(?<!\d)\d\.\d{3}(?!\d)")
_FECHA_ISO = re.compile(r"(?<!\d)(20\d\d-\d\d-\d\d)(?!\d)")


def _documento() -> str:
    return _DOC.read_text(encoding="utf-8")


def _manifiesto() -> dict:
    datos: dict = json.loads(_MANIFIESTO.read_text(encoding="utf-8"))
    return datos


def _refs_de(valor: str) -> tuple[str, ...]:
    """Separa un ``source_ref`` que agrupa varias anclas (``"§4; §4.1"``)."""
    return tuple(parte.strip() for parte in valor.split(";") if parte.strip())


def _encabezados(texto: str) -> tuple[str, ...]:
    return tuple(linea for linea in texto.splitlines() if linea.startswith("#"))


def _ancla_en_encabezado(ancla: str, encabezados: tuple[str, ...]) -> bool:
    """Un ancla ``§2.c`` la sostiene el encabezado ``### 2.c ...`` de su sección.

    ⚠️ El corte tras el número es más sutil de lo que parece, y el primer criterio de este gate
    fue el equivocado: un ``(?![\\w.])`` rechaza ``## 3. Cartera consumo`` —el punto de la
    numeración cae dentro de la clase— y daba por ausentes cuatro secciones que existen. Lo que
    distingue el ancla ``§3`` de la ``§3.1`` no es el punto, sino **si tras el punto viene un
    dígito**: ``## 3. Cartera`` es §3 y ``### 3.1 Matriz`` no lo es.
    """
    numero = ancla.removeprefix("§").strip()
    patron = re.compile(rf"^#+\s+{re.escape(numero)}(?!\d)(?!\.\d)")
    return any(patron.search(encabezado) for encabezado in encabezados)


# --------------------------------------------------------------------------------------------
# Anclas anti-vacuidad: un gate que recorre cero elementos se lee igual que uno que pasa.
# --------------------------------------------------------------------------------------------


def test_las_dos_superficies_existen_y_tienen_cuerpo() -> None:
    assert _DOC.exists(), f"No existe el documento normativo en {_DOC}."
    assert _MANIFIESTO.exists(), f"No existe el manifiesto del bundle en {_MANIFIESTO}."
    texto = _documento()
    assert len(texto.splitlines()) >= 300, "El documento normativo encogió: revisar antes de tocar."
    assert texto.count("|---") >= 15, "El documento perdió tablas; el gate dejaría de medir."


def test_el_manifiesto_declara_el_conjunto_completo() -> None:
    manifiesto = _manifiesto()
    assert len(manifiesto["matrices"]) >= 10, "El manifiesto perdió matrices."
    assert len(manifiesto["official_sources"]) >= 5, "El manifiesto perdió fuentes oficiales."
    assert len(manifiesto["normativa_refs"]) >= 13, "El manifiesto perdió anclas de sección."
    assert len(manifiesto["pending_items"]) >= 2, "El manifiesto perdió sus brechas declaradas."


def test_el_manifiesto_apunta_al_documento_por_su_ruta_real() -> None:
    """El ``verifier`` cita el documento: si se renombra, el manifiesto queda apuntando al vacío."""
    citada = _manifiesto()["verifier"]
    ruta = "docs/normativa_cmf_parametros.md"
    assert ruta in citada, f"El verifier del manifiesto ya no cita {ruta!r}: {citada!r}"
    assert (_RAIZ / Path(ruta)).exists()


# --------------------------------------------------------------------------------------------
# Manifiesto → documento
# --------------------------------------------------------------------------------------------


def test_la_fecha_de_extraccion_del_manifiesto_esta_publicada_en_el_documento() -> None:
    extraccion = _manifiesto()["extraction_date"]
    assert extraccion in _documento(), (
        f"El manifiesto declara extraction_date={extraccion!r} y el documento no la publica: "
        "las dos fechas se escriben a mano en sitios distintos y acaban de divergir."
    )


@pytest.mark.parametrize("entrada", _manifiesto()["matrices"], ids=lambda e: e["matrix_id"])
def test_cada_matriz_apunta_a_una_seccion_que_existe_en_el_documento(entrada: dict) -> None:
    encabezados = _encabezados(_documento())
    for ancla in _refs_de(entrada["source_ref"]):
        assert _ancla_en_encabezado(ancla, encabezados), (
            f"La matriz {entrada['matrix_id']!r} declara source_ref={ancla!r}, y el documento "
            "normativo no tiene esa sección: la trazabilidad de la tabla apunta al vacío."
        )


@pytest.mark.parametrize("pendiente", _manifiesto()["pending_items"], ids=lambda p: p["id"])
def test_cada_brecha_declarada_apunta_a_una_seccion_que_existe(pendiente: dict) -> None:
    encabezados = _encabezados(_documento())
    for ancla in _refs_de(pendiente["source_ref"]):
        assert _ancla_en_encabezado(ancla, encabezados), (
            f"El pending_item {pendiente['id']!r} declara source_ref={ancla!r} y el documento "
            "no tiene esa sección."
        )


@pytest.mark.parametrize("ancla", _manifiesto()["normativa_refs"])
def test_cada_ancla_declarada_existe_como_seccion_del_documento(ancla: str) -> None:
    assert _ancla_en_encabezado(ancla, _encabezados(_documento())), (
        f"El manifiesto declara la referencia normativa {ancla!r} y el documento no la tiene."
    )


@pytest.mark.parametrize("fuente", _manifiesto()["official_sources"], ids=lambda f: f["id"])
def test_cada_fuente_oficial_esta_citada_en_el_documento(fuente: dict) -> None:
    texto = _documento()
    assert fuente["url"] in texto, (
        f"La fuente {fuente['id']!r} del manifiesto apunta a {fuente['url']!r} y el documento "
        "normativo no la cita: el bundle consume una fuente que su propia trazabilidad ignora."
    )
    for numero in _NUMERO_CIRCULAR.findall(fuente["circular"]):
        assert numero in texto, (
            f"La fuente {fuente['id']!r} declara la circular {numero!r} y el documento no la "
            "menciona."
        )


@pytest.mark.parametrize("entrada", _manifiesto()["matrices"], ids=lambda e: e["matrix_id"])
def test_la_norma_que_gobierna_cada_matriz_esta_citada_en_el_documento(entrada: dict) -> None:
    texto = _documento()
    for numero in _NUMERO_CIRCULAR.findall(entrada["source_normative"]):
        assert numero in texto, (
            f"La matriz {entrada['matrix_id']!r} dice regirse por la circular {numero!r} y el "
            "documento normativo no la menciona en ninguna parte."
        )


# Una vigencia que la norma no expresa como fecha de circular sino en prosa. No es una exención:
# se declara **qué frase del documento la sostiene**, de modo que si esa frase desaparece el gate
# sigue fallando. Hoy hay un solo caso, y es real: la matriz de consumo no rige desde la fecha de
# su circular (06.03.2024) sino desde un cierre contable posterior.
_VIGENCIA_EN_PROSA = {
    "consumer_standard_v2025": "cierre contable de enero 2025",
}


@pytest.mark.parametrize("entrada", _manifiesto()["matrices"], ids=lambda e: e["matrix_id"])
def test_la_vigencia_de_cada_matriz_esta_publicada_en_el_documento(entrada: dict) -> None:
    """El documento fecha las circulares en ``DD.MM.AAAA``; el manifiesto en ISO."""
    anio, mes, dia = entrada["effective_date"].split("-")
    texto = _documento()
    en_prosa = _VIGENCIA_EN_PROSA.get(entrada["matrix_id"])
    if en_prosa is not None:
        assert en_prosa in texto, (
            f"La matriz {entrada['matrix_id']!r} tiene su vigencia declarada en prosa como "
            f"{en_prosa!r}, y esa frase ya no está en el documento normativo."
        )
        return
    assert f"{dia}.{mes}.{anio}" in texto or entrada["effective_date"] in texto, (
        f"La matriz {entrada['matrix_id']!r} declara vigencia {entrada['effective_date']!r} y el "
        "documento normativo no publica esa fecha."
    )


def test_la_vigencia_en_prosa_no_se_usa_para_tapar_matrices_nuevas() -> None:
    """Ancla anti-erosión: la lista de excepciones sólo puede nombrar matrices que existen."""
    conocidas = {entrada["matrix_id"] for entrada in _manifiesto()["matrices"]}
    sobrantes = sorted(set(_VIGENCIA_EN_PROSA) - conocidas)
    assert not sobrantes, f"_VIGENCIA_EN_PROSA nombra matrices que ya no existen: {sobrantes}."
    assert len(_VIGENCIA_EN_PROSA) <= 2, (
        "La excepción de vigencia en prosa está creciendo: si son muchas, el gate dejó de medir."
    )


# --------------------------------------------------------------------------------------------
# Cruces internos del manifiesto
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize("entrada", _manifiesto()["matrices"], ids=lambda e: e["matrix_id"])
def test_la_norma_que_gobierna_cada_matriz_esta_entre_las_fuentes_declaradas(entrada: dict) -> None:
    """Una matriz no puede regirse por una circular que el manifiesto no declara como fuente."""
    manifiesto = _manifiesto()
    declaradas = {
        numero
        for fuente in manifiesto["official_sources"]
        for numero in _NUMERO_CIRCULAR.findall(fuente["circular"])
    }
    for numero in _NUMERO_CIRCULAR.findall(entrada["source_normative"]):
        assert numero in declaradas, (
            f"La matriz {entrada['matrix_id']!r} se rige por la circular {numero!r}, que no está "
            f"entre las fuentes oficiales del manifiesto ({sorted(declaradas)}). Quien audite la "
            "tabla no tiene de dónde bajarla ni con qué estado de verificación."
        )


@pytest.mark.parametrize("cotejo", _manifiesto()["verifications"], ids=lambda c: c["date"])
def test_cada_cotejo_declara_un_alcance_verificable(cotejo: dict) -> None:
    """Un cotejo sin alcance permite publicarlo como cobertura general (D-COT-1)."""
    conocidas = {entrada["matrix_id"] for entrada in _manifiesto()["matrices"]}
    ajenas = sorted(set(cotejo["matrix_ids"]) - conocidas)
    assert not ajenas, (
        f"El cotejo del {cotejo['date']} dice cubrir matrices que el bundle no tiene: {ajenas}."
    )
    assert cotejo["scope"].strip(), f"El cotejo del {cotejo['date']} no declara su alcance."
    assert cotejo["date"] in _documento(), (
        f"El manifiesto declara un cotejo el {cotejo['date']} y el documento normativo no lo "
        "registra: la evidencia del cotejo tiene que estar escrita en su fuente."
    )


def test_el_manifiesto_registra_al_menos_un_cotejo() -> None:
    """Ancla anti-vacuidad: sin cotejos, el test de fechas huérfanas pasaría por no tener nada."""
    assert len(_manifiesto()["verifications"]) >= 2, (
        "El manifiesto perdió sus cotejos declarados; el gate de fechas dejaría de medir."
    )


def test_todo_source_ref_usado_esta_declarado_en_normativa_refs() -> None:
    manifiesto = _manifiesto()
    declaradas = set(manifiesto["normativa_refs"])
    usadas = {
        ancla
        for entrada in (*manifiesto["matrices"], *manifiesto["pending_items"])
        for ancla in _refs_de(entrada["source_ref"])
    }
    assert usadas <= declaradas, (
        f"Hay source_ref en uso que no están en normativa_refs: {sorted(usadas - declaradas)}."
    )


# --------------------------------------------------------------------------------------------
# Documento → manifiesto (acotado: sólo las fechas de verificación)
# --------------------------------------------------------------------------------------------


def test_toda_fecha_de_verificacion_del_documento_la_conoce_el_manifiesto() -> None:
    """🔴 La clase exacta del defecto del 2026-08-04.

    Si el documento registra un cotejo que el manifiesto no declara, el bundle publica como su
    verificación una fecha que su propia fuente contradice — y el copy que lea el manifiesto
    afirmará algo más débil de lo que el trabajo realmente sostiene, sin que nada lo note.
    """
    manifiesto = _manifiesto()
    conocidas = {manifiesto["extraction_date"], manifiesto["effective_date"]}
    conocidas.update(entrada["effective_date"] for entrada in manifiesto["matrices"])
    conocidas.update(cotejo["date"] for cotejo in manifiesto["verifications"])

    publicadas = set(_FECHA_ISO.findall(_documento()))
    huerfanas = sorted(fecha for fecha in publicadas if fecha not in conocidas)

    assert not huerfanas, (
        f"El documento normativo publica fechas de verificación que el manifiesto no declara: "
        f"{huerfanas}. El manifiesto es lo que el motor sirve a la auditoría y lo que el copy "
        "cita, así que un cotejo registrado sólo en el documento se pierde — que es justo lo que "
        "ocurrió el 2026-08-04."
    )
