"""Gate del catálogo de trabajos (D-JOB-1/3/15, `_SDD-UI-POR-TRABAJOS.md` §6).

El catálogo nombra secciones del formulario con **claves literales**, porque `nikodym.ui` es
*domain-agnostic* y no puede importar módulos de dominio para componerlas. Este gate es lo único que
ata esos literales a la realidad, y por eso mide en las **dos direcciones**:

1. toda sección que un trabajo declara **existe en el formulario** —si no, el trabajo promete una
   pestaña que no se puede abrir—;
2. toda sección del formulario **pertenece al menos a un trabajo** —si no, hay una pantalla a la que
   ningún trabajo lleva, que es la definición de «existe y el usuario no puede alcanzarlo»—.

⚠️ **Un gate que sólo mire una dirección deja pasar `validation`**, que fue exactamente el hueco que
encontró la revisión del SDD: el borrador la declaraba en dos trabajos y el formulario no la ofrece.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from nikodym.ui import jobs
from nikodym.ui.routes import jobs_payload

# Espejo del lector de `test_column_roles.py` / `test_extra_ui_cubre_el_formulario.py`: el catálogo
# de secciones navegables vive en TypeScript y aquí se lee del fuente, no se reescribe al lado.
_SCHEMA_TS = Path(__file__).resolve().parents[2] / "web" / "src" / "lib" / "schema.ts"


def _secciones_del_formulario() -> tuple[str, ...]:
    """Claves de `CONFIG_SECTIONS` leídas del fuente TypeScript, en su orden."""
    texto = _SCHEMA_TS.read_text(encoding="utf-8")
    _, _, resto = texto.partition("export const CONFIG_SECTIONS")
    cuerpo, _, _ = resto.partition("\n]")
    return tuple(re.findall(r'key:\s*"([a-z_0-9]+)"', cuerpo))


@pytest.fixture(scope="module")
def secciones() -> tuple[str, ...]:
    encontradas = _secciones_del_formulario()
    # Anti-tautología: si el regex deja de casar, «ninguna sección huérfana» se leería como éxito.
    # Es el defecto exacto que tuvo `test_copy_del_formulario.py` en su primera versión —daba verde
    # recorriendo cero campos—, así que el gate exige encontrar un catálogo con cuerpo.
    assert len(encontradas) >= 10, (
        f"no se pudo leer CONFIG_SECTIONS de {_SCHEMA_TS}: {encontradas!r}. "
        "Sin catálogo este gate no comprueba nada."
    )
    return encontradas


def test_toda_seccion_declarada_por_un_trabajo_existe_en_el_formulario(
    secciones: tuple[str, ...],
) -> None:
    """Un trabajo no puede prometer una pestaña que no se puede abrir."""
    conocidas = set(secciones)
    inexistentes = {
        job["id"]: sorted(set(job["sections"]) - conocidas)
        for job in jobs.list_jobs()
        if set(job["sections"]) - conocidas
    }
    assert not inexistentes, (
        "trabajos que declaran secciones que el formulario NO ofrece: "
        f"{inexistentes}. O la sección entra a CONFIG_SECTIONS, o sale del trabajo y se "
        "declara en `missing_sections` con su motivo (como hace `stress`)."
    )


def test_toda_seccion_del_formulario_pertenece_a_algun_trabajo(
    secciones: tuple[str, ...],
) -> None:
    """No puede haber una pantalla a la que ningún trabajo lleve."""
    cubiertas = {seccion for job in jobs.list_jobs() for seccion in job["sections"]}
    huerfanas = sorted(set(secciones) - cubiertas)
    assert not huerfanas, (
        f"secciones del formulario que ningún trabajo muestra: {huerfanas}. "
        "Con la navegación por trabajo, una sección así es inalcanzable: o entra a un trabajo, "
        "o sale del formulario."
    )


def test_las_secciones_faltantes_son_reales_y_no_estan_en_el_formulario(
    secciones: tuple[str, ...],
) -> None:
    """`missing_sections` no puede usarse para esconder una sección que SÍ existe.

    Sin este test, `missing_sections` sería la escapatoria del gate anterior: bastaría mover ahí
    cualquier sección incómoda para que dejara de comprobarse.
    """
    conocidas = set(secciones)
    mal_declaradas = {
        job["id"]: sorted(set(job["missing_sections"]) & conocidas)
        for job in jobs.list_jobs()
        if set(job["missing_sections"]) & conocidas
    }
    assert not mal_declaradas, (
        f"secciones declaradas como faltantes que el formulario SÍ ofrece: {mal_declaradas}. "
        "Si la pestaña existe, la sección va en `sections`."
    )


def test_un_trabajo_con_secciones_faltantes_no_puede_estar_disponible() -> None:
    """Si le falta una pantalla, no se puede iniciar: D-JOB-6 dice declarar, no prometer."""
    incoherentes = [
        job["id"]
        for job in jobs.list_jobs()
        if job["missing_sections"] and job["status"] == "available"
    ]
    assert not incoherentes, (
        f"trabajos marcados disponibles a los que les falta una sección: {incoherentes}"
    )


def test_todo_trabajo_no_disponible_explica_por_que_sin_jerga() -> None:
    """Un motivo vacío se lee como «no se puede y no sabemos por qué» (D-JOB-6)."""
    for job in jobs.list_jobs():
        if job["status"] != "unavailable":
            assert job["unavailable_reason"] is None, (
                f"{job['id']}: un trabajo disponible no puede traer motivo de indisponibilidad"
            )
            continue
        motivo = job["unavailable_reason"]
        assert isinstance(motivo, str) and len(motivo) > 30, (
            f"{job['id']}: motivo ausente o demasiado corto para explicar nada: {motivo!r}"
        )


def test_el_copy_del_catalogo_no_habla_en_jerga_interna() -> None:
    """Es copy público (lo lee un analista en la landing): nada de claves ni identificadores.

    El repo ya pagó esto tres veces —tooltips con `None`, «BinningProcess», «allowlist cerrada»—, y
    la regla es la misma aquí: la limitación se explica en el idioma del lector.
    """
    prohibidos = re.compile(
        r"\b(None|True|False|null|config_hash|check_pipeline|provisioning_\w+|"
        r"NikodymConfig|dataframe|DataFrame)\b"
    )
    ofensores = [
        (job["id"], campo, valor)
        for job in jobs.list_jobs()
        for campo in ("label", "description", "external_input", "unavailable_reason")
        if isinstance(valor := job[campo], str) and prohibidos.search(valor)
    ]
    assert not ofensores, f"jerga interna en copy visible del catálogo: {ofensores}"


def test_los_ids_son_unicos_y_el_orden_es_estable() -> None:
    ids = [job["id"] for job in jobs.list_jobs()]
    assert len(ids) == len(set(ids)), f"ids repetidos en el catálogo: {ids}"
    assert tuple(ids) == jobs.JOB_IDS


def test_la_jurisdiccion_se_declara_en_pareja() -> None:
    """D-JOB-8: o el trabajo es neutral, o dice de qué país es — nunca a medias.

    Un código sin etiqueta dejaría a la interfaz inventando el nombre del país, que es dominio en el
    front; una etiqueta sin código dejaría a P3 sin por dónde agarrarla.
    """
    for job in jobs.list_jobs():
        code, label = job["jurisdiction_code"], job["jurisdiction_label"]
        assert (code is None) == (label is None), (
            f"{job['id']}: jurisdicción declarada a medias ({code!r}, {label!r})"
        )


def test_el_catalogo_no_muta_el_estado_del_proceso() -> None:
    """`list_jobs` devuelve copias: mutar la respuesta no puede envenenar el catálogo."""
    primero = jobs.list_jobs()
    primero[0]["sections"].append("inventada")
    primero[0]["label"] = "pisado"
    segundo = jobs.list_jobs()
    assert "inventada" not in segundo[0]["sections"]
    assert segundo[0]["label"] != "pisado"


def test_el_endpoint_sirve_el_catalogo_completo() -> None:
    payload = jobs_payload()
    assert list(payload) == ["jobs"]
    assert [job["id"] for job in payload["jobs"]] == list(jobs.JOB_IDS)


def test_hay_al_menos_un_trabajo_disponible_y_uno_no_disponible() -> None:
    """Ancla del gate: con el catálogo vacío, todos los tests de arriba pasarían por vacuidad."""
    estados = {job["status"] for job in jobs.list_jobs()}
    assert estados == {"available", "unavailable"}
    assert len(jobs.JOB_IDS) >= 8


# --------------------------------------------------------------------------------------------
# Paridad con el fixture bundleado
# --------------------------------------------------------------------------------------------

_FIXTURE = Path(__file__).resolve().parents[2] / "web" / "src" / "fixtures" / "jobs.json"


def test_el_fixture_del_front_no_se_queda_viejo_en_silencio() -> None:
    """Gemelo de G7 (`test_ui_schema_fixture.py`): el snapshot commiteado igual al catálogo real.

    El fixture viaja **dentro del bundle instalable** y es el respaldo con el que la landing tiene
    trabajos aunque el backend no responda. Lo regenera `scripts/gen_jobs_fixture.py`… cuando
    alguien se acuerda. Con `schema.json` eso ya se pagó: llegó a 64 kB contra 259 kB reales y
    publicó un encuadre normativo que el código había corregido meses antes.

    A diferencia de G7, aquí NO hay tolerancia a extras ausentes: el catálogo es *domain-agnostic*,
    así que no existe estado del entorno que pueda degradarlo legítimamente.
    """
    fixture = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    assert fixture == jobs_payload(), (
        f"{_FIXTURE.name} quedó viejo. Corre `python scripts/gen_jobs_fixture.py` y "
        "commitea el fixture EN EL MISMO commit que el catálogo."
    )
