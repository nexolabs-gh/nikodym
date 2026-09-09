"""Gate: lo que el copy público dice de la gobernanza es lo que el motor y la interfaz hacen.

🔴 **Por qué existe.** Desde 1.0 el README, la portada y dos guías prometían «gobernanza (model card
+ audit-trail) **automática**». Medido el 2026-09-03 y remedido el 2026-09-09: ``governance`` es
``None`` por defecto y en los cuatro presets, y la ficha del modelo sólo se emite cuando la
institución declara un propósito (D-GOB-8) — el motor no lo inventa. Lo único automático en toda
corrida es el lineage; el audit-trail va encendido en los ejemplos de fábrica. Era una promesa
falsa en la primera línea del producto, y ningún test la leía.

Con S3/S4 la sección se enciende desde la interfaz y la ficha se pinta en Resultados. Esta gate ata
la página que lo explica a los **rótulos reales** del front y del config, para que la
documentación no describa una pantalla que ya no existe; y ata las afirmaciones de «apagada de
fábrica» y «propósito obligatorio» al código que las hace ciertas.

**Qué NO cubre.** Una frase nueva que vuelva a prometer automatismo con otras palabras no rompe
nada si no cae en los patrones de abajo. Se dice para que la lista no se lea como cobertura total.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_RAIZ = Path(__file__).resolve().parents[2]
_DOCS = _RAIZ / "docs_site"
_README = _RAIZ / "README.md"
_GUIA = _DOCS / "guias" / "gobernanza.md"
_WEB = _RAIZ / "web" / "src"

#: Páginas de copy público que se barren. El changelog publica el CHANGELOG técnico entero y ahí
#: la historia de la promesa vieja es legítima.
_EXENTOS = {"changelog.md"}


def _paginas() -> list[Path]:
    return [*sorted(p for p in _DOCS.rglob("*.md") if p.name not in _EXENTOS), _README]


#: Automatismo atribuido a la gobernanza, la model card o la ficha, en la misma oración. Cubre el
#: giro exacto que estuvo publicado («gobernanza … automática», «model card y audit-trail
#: automáticos», «la gobernanza automática») sin cazar frases verdaderas como «lo que sí es
#: automático en toda corrida es el lineage», que no nombra la ficha en su oración.
_AUTOMATISMO = re.compile(
    r"(?i)(?:gobernanza|model card|ficha del modelo)[^.\n]*autom[áa]tic"
    r"|autom[áa]tic[^.\n]*(?:gobernanza|model card|ficha del modelo)"
)

#: Literales que la documentación no puede volver a publicar. Control por ausencia: es el que caza
#: un `git revert` descuidado o un párrafo copiado desde el archivo histórico.
_PROSCRITAS: list[tuple[str, str]] = [
    ("README.md", "automática"),
    ("index.md", "automáticos"),
    ("index.md", "está pendiente"),
    ("concepts.md", "y produce una *model card*"),
    ("guias/desempeno-estabilidad.md", "Cada corrida finalizada produce una **model card**"),
    ("guias/desempeno-estabilidad.md", "sin trabajo extra del analista"),
    ("guias/binning-seleccion.md", "gobernanza automática"),
    ("guias/provision-sin-norma-local.md", "Nikodym Advisory"),
]

#: Afirmaciones que tienen que estar, palabra por palabra, en la superficie que las publica.
_ANCLAS: list[tuple[str, str]] = [
    ("README.md", "la ficha del modelo se emite cuando tu institución declara el propósito"),
    ("index.md", "la ficha del modelo se emite cuando tu institución declara el propósito"),
    ("concepts.md", "la ficha del modelo sólo existe si declaras la sección `governance`"),
    ("getting-started.md", "[Gobernanza y ficha del modelo](guias/gobernanza.md)"),
    ("index.md", "hash del `uv.lock` con el que se construyó el paquete"),
]

#: Rótulos de la interfaz y del config que la guía cita entre comillas. Cada uno tiene que existir
#: en la guía Y en el fuente que lo pinta: si el front cambia una etiqueta, la guía deja de cuadrar.
_ROTULOS: list[tuple[str, Path]] = [
    ("Gobernanza", _WEB / "lib" / "schema.ts"),
    ("Sección desactivada", _WEB / "components" / "ConfigTab.tsx"),
    ("Sección activa", _WEB / "components" / "ConfigTab.tsx"),
    ("Esto lo decides tú", _WEB / "components" / "ConfigTab.tsx"),
    (
        "Se pregunta cuando actives la sección con su interruptor.",
        _WEB / "components" / "ConfigTab.tsx",
    ),
    ("Este valor se escribe en formato JSON.", _WEB / "components" / "FieldRenderer.tsx"),
    ("Propósito del modelo", _RAIZ / "src" / "nikodym" / "governance" / "config.py"),
    ("Supuestos declarados", _RAIZ / "src" / "nikodym" / "governance" / "config.py"),
    ("Limitaciones declaradas", _RAIZ / "src" / "nikodym" / "governance" / "config.py"),
    ("Periodicidad de revisión (meses)", _RAIZ / "src" / "nikodym" / "governance" / "config.py"),
    ("Artefactos de la corrida", _WEB / "components" / "ResultsTab.tsx"),
    ("Ficha del modelo", _WEB / "components" / "ResultsTab.tsx"),
    ("Emitida", _WEB / "components" / "ResultsTab.tsx"),
    ("Próxima revisión", _WEB / "components" / "ResultsTab.tsx"),
    ("Decisiones registradas", _WEB / "components" / "ResultsTab.tsx"),
    ("Métricas por dominio", _WEB / "components" / "ResultsTab.tsx"),
    ("Ver el detalle de las decisiones", _WEB / "components" / "ResultsTab.tsx"),
    ("aviso declarado", _WEB / "components" / "ResultsTab.tsx"),
]


def _texto(relativo: str) -> str:
    return (_README if relativo == "README.md" else _DOCS / relativo).read_text(encoding="utf-8")


def _plano(texto: str) -> str:
    """La prosa va envuelta a 100 columnas: una frase se compara con los espacios normalizados."""
    return " ".join(texto.split())


def test_el_barrido_no_es_vacuo() -> None:
    assert len(_paginas()) >= 10
    assert _GUIA.is_file(), "la guía de gobernanza no existe"
    assert len(_ROTULOS) >= 15 and len(_PROSCRITAS) >= 8 and len(_ANCLAS) >= 5
    for relativo, _ in _PROSCRITAS + _ANCLAS:
        assert (_README if relativo == "README.md" else _DOCS / relativo).is_file(), relativo
    # Control positivo del detector: si deja de detectar, el test de abajo pasa siempre.
    assert _AUTOMATISMO.search("con gobernanza (model card + audit-trail) automática.")
    assert _AUTOMATISMO.search("*model card* y *audit-trail* automáticos.")
    assert _AUTOMATISMO.search("lo que consume la gobernanza automática (SR 11-7).")
    assert not _AUTOMATISMO.search(
        "Lo que sí es automático en **toda** corrida es el *lineage* y el *audit-trail*."
    )


@pytest.mark.parametrize("pagina", _paginas(), ids=lambda p: p.name)
def test_ninguna_pagina_atribuye_automatismo_a_la_gobernanza(pagina: Path) -> None:
    ofensores = [
        f"{pagina.name}:{n}: {linea.strip()}"
        for n, linea in enumerate(pagina.read_text(encoding="utf-8").splitlines(), start=1)
        if _AUTOMATISMO.search(linea)
    ]
    assert ofensores == []


@pytest.mark.parametrize(("relativo", "proscrita"), _PROSCRITAS)
def test_no_reaparece_la_promesa_vieja(relativo: str, proscrita: str) -> None:
    assert proscrita not in _plano(_texto(relativo)), f"{relativo} vuelve a publicar «{proscrita}»"


@pytest.mark.parametrize(("relativo", "frase"), _ANCLAS)
def test_la_afirmacion_verdadera_esta_publicada(relativo: str, frase: str) -> None:
    assert frase in _plano(_texto(relativo)), f"{relativo}: falta «{frase}»"


def test_lo_que_la_documentacion_afirma_lo_hace_el_codigo() -> None:
    """«Apagada de fábrica», «propósito obligatorio» y «el lineage firma el uv.lock», medidos.

    Si un día `governance` se enciende por defecto o `purpose` gana un default, las frases ancladas
    arriba pasan a ser falsas: este test es el que las liga al motor y no sólo al texto.
    """
    from nikodym.core.config import NikodymConfig
    from nikodym.governance.config import GovernanceConfig
    from nikodym.ui.presets import get_preset, list_presets

    assert NikodymConfig.model_fields["governance"].default is None
    assert NikodymConfig.model_fields["audit"].default is None
    assert GovernanceConfig.model_fields["purpose"].is_required()
    with pytest.raises(ValueError, match="en blanco"):
        GovernanceConfig(purpose="   ")

    ids = [p["id"] for p in list_presets()]
    assert len(ids) == 4, ids
    for preset_id in ids:
        config = get_preset(preset_id)["config"]
        assert config["governance"] is None, f"{preset_id} enciende governance de fábrica"
        assert config["audit"] == {"enabled": True}, f"{preset_id} no trae la auditoría encendida"

    from nikodym.core.build import build_uv_lock_hash

    assert re.fullmatch(r"[0-9a-f]{64}", build_uv_lock_hash())


def test_la_guia_cita_los_rotulos_reales_de_la_interfaz() -> None:
    """Cada rótulo entre comillas de la guía existe en el fuente que lo pinta, y al revés."""
    guia = _plano(_GUIA.read_text(encoding="utf-8"))
    faltan_en_guia = [rotulo for rotulo, _ in _ROTULOS if rotulo not in guia]
    assert faltan_en_guia == [], f"la guía ya no cita: {faltan_en_guia}"
    faltan_en_fuente = [
        f"{rotulo!r} en {fuente.relative_to(_RAIZ).as_posix()}"
        for rotulo, fuente in _ROTULOS
        if rotulo not in fuente.read_text(encoding="utf-8")
    ]
    assert faltan_en_fuente == [], (
        f"la interfaz ya no pinta lo que la guía cita: {faltan_en_fuente}. "
        "Cambió el copy del front o del config: actualiza la guía en la misma capa."
    )


def test_la_guia_no_promete_lo_diferido_ni_nombra_codigos_internos() -> None:
    """El capítulo del informe está diferido (abierto 3 de D-GOB) y la demo aún no lleva ficha."""
    guia = _GUIA.read_text(encoding="utf-8")
    for prohibido in ("SR 11-7", "D-GOB", "FALTA-DATO", "DATO-INSTITUCIONAL", "model_card:"):
        assert prohibido not in guia, f"la guía nombra {prohibido!r}"
    assert not re.search(r"(?i)(?:capítulo|informe)[^.\n]*(?:próxima|pronto|se añadirá)", guia)


def test_el_ejemplo_por_codigo_de_la_guia_emite_la_ficha(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ejecuta el bloque «Por código» tal cual y comprueba que la ficha lleva lo declarado.

    Es la promesa central de la guía: declarar `governance` con un propósito y pasar `run_dir`
    deja `model_card.json` en disco, con ese propósito, con decisiones del audit-trail y con las
    métricas que el canal de D-GOB publica. Sin ejecutarlo, la guía podría describir un archivo que
    el motor ya no escribe.
    """
    import tempfile

    pytest.importorskip("optbinning")
    texto = _GUIA.read_text(encoding="utf-8")
    inicio, fin = (
        "<!-- governance-example:start -->\n```python\n",
        "\n```\n<!-- governance-example:end -->",
    )
    assert texto.count(inicio) == 1 and texto.count(fin) == 1
    codigo = texto.split(inicio, 1)[1].split(fin, 1)[0]
    assert '"purpose"' in codigo and "run_dir=" in codigo and "model_card.json" in codigo
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    espacio: dict = {"__name__": "__main__"}
    exec(compile(codigo, str(_GUIA), "exec"), espacio)

    card = espacio["card"]
    assert card["purpose"] == espacio["cfg_dict"]["governance"]["purpose"]
    assert card["assumptions"] == espacio["cfg_dict"]["governance"]["assumptions"]
    assert espacio["cfg_dict"]["governance"]["limitations"][0] in card["limitations"]
    assert card["next_review_date"] > card["review_date"]
    assert len(card["decisions"]) > 0 and len(card["metrics"]) > 0
    run_dir = espacio["run_dir"]
    assert (run_dir / "model_card.md").is_file() and (run_dir / "audit_trail.jsonl").is_file()


def test_la_guia_esta_en_la_navegacion_del_sitio() -> None:
    """mkdocs --strict no enrojece por una página fuera del `nav`: sólo avisa."""
    nav = (_RAIZ / "mkdocs.yml").read_text(encoding="utf-8")
    assert "guias/gobernanza.md" in nav


def test_el_catalogo_de_trabajos_publicado_es_el_de_la_interfaz() -> None:
    """«Empezar» lista los trabajos con sus rótulos reales y en el orden de la interfaz.

    Hasta ahora describía la pantalla con «Scorecard…, Provisiones…, Validar…» y puntos suspensivos.
    La tabla se ata en dos sentidos al catálogo: ni un trabajo sin fila, ni una fila sin trabajo; y
    el que hoy no corre desde la interfaz se dice como tal, con la razón que publica el catálogo.
    """
    from nikodym.ui.jobs import list_jobs

    texto = _texto("getting-started.md")
    inicio, fin = "<!-- catalogo-trabajos:start -->", "<!-- catalogo-trabajos:end -->"
    assert texto.count(inicio) == 1 and texto.count(fin) == 1
    tabla = texto.split(inicio, 1)[1].split(fin, 1)[0]
    filas = [
        linea
        for linea in tabla.splitlines()
        if linea.startswith("| **")  # una fila por trabajo; cabecera y separador quedan fuera
    ]
    publicados = [re.match(r"\| \*\*(.+?)\*\* \|", fila).group(1) for fila in filas]  # type: ignore[union-attr]

    catalogo = list_jobs()
    assert len(catalogo) >= 10
    assert publicados == [job["label"] for job in catalogo]
    for fila, job in zip(filas, catalogo, strict=True):
        if job["status"] == "unavailable":
            assert "por código" in fila, (
                f"{job['label']} no corre desde la interfaz y la fila calla"
            )
        else:
            assert "por código" not in fila, f"{job['label']} sí corre desde la interfaz"


def test_empezar_no_fija_una_version_a_mano() -> None:
    """«Esta documentación corresponde a la serie 1.10.x» llevaba dos releases de atraso."""
    assert not re.search(r"\b1\.\d+\.x\b", _texto("getting-started.md"))


def test_la_consultora_tiene_un_solo_nombre_en_el_copy_publico() -> None:
    """README, portada, footer y guías nombran a Nexo Labs; el sitio se firma igual."""
    for relativo in ("README.md", "index.md", "guias/provision-sin-norma-local.md"):
        assert "Nexo Labs" in _texto(relativo), relativo
    mkdocs = (_RAIZ / "mkdocs.yml").read_text(encoding="utf-8")
    assert "site_author: Nexo Labs" in mkdocs
    for pagina in _paginas():
        assert "Nikodym Advisory" not in pagina.read_text(encoding="utf-8"), pagina.name
