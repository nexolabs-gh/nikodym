"""Gate del insumo externo que un trabajo declara (D-PUE-2/D-PUE-11).

``external_artifacts`` es la declaración **máquina-legible** de lo que un trabajo acepta traer de
fuera, y de ella sale la **allowlist** de la puerta por HTTP: una clave que ningún trabajo
disponible declare se rechaza sin materializar nada. Como el resto del catálogo, se escribe con
literales —`nikodym.ui` es *domain-agnostic* por otro gate—, así que sin nada que la ate al motor se
separaría en silencio en las dos direcciones:

- **una clave que el motor no publica** ⇒ el trabajo pide un archivo que nadie va a consumir, y la
  corrida lo declara inerte después de que el usuario ya lo subió;
- **un campo de config que el motor renombró** ⇒ el mapeo por clicks escribe en un campo que ya no
  existe, el config queda inválido y el formulario reclama por una coordenada que el usuario nunca
  vio.

El oráculo de las claves es ``REGISTRY`` —lo que los pasos declaran en ``provides``— y el de los
campos es ``model_fields``. Ninguno se escribe al lado.
"""

from __future__ import annotations

import re
import typing
from typing import Any

import pytest
from pydantic import BaseModel

from nikodym.core.config.schema import cargar_configs_de_dominio
from nikodym.core.registry import REGISTRY
from nikodym.core.study import _DOMAIN_MODULES
from nikodym.ui.jobs import artefactos_admitidos, list_jobs

_CLAVES_DE_ENTRADA = {"artifact", "label", "when", "key_question", "columns"}
_CLAVES_DE_COLUMNA = {"question", "config_paths"}


def _entradas() -> list[tuple[str, dict[str, Any]]]:
    """``(job_id, entrada)`` de todo lo que el catálogo declara como insumo externo."""
    return [(job["id"], entrada) for job in list_jobs() for entrada in job["external_artifacts"]]


def _publicadas_por(dominio: str) -> set[tuple[str, str]]:
    """Claves que los pasos registrados de un dominio declaran en ``provides``."""
    publicadas: set[tuple[str, str]] = set()
    for nombre in REGISTRY.available(dominio):
        for clave in getattr(REGISTRY.resolve(dominio, nombre), "provides", ()):
            publicadas.add((str(clave[0]), str(clave[1])))
    return publicadas


def _campo_en(path: str) -> Any | None:
    """``FieldInfo`` del campo que un path del config nombra, o ``None`` si no existe."""
    seccion, *resto = path.split(".")
    cls: Any = cargar_configs_de_dominio().get(seccion)
    if cls is None:
        return None
    campo = None
    for parte in resto:
        if not (isinstance(cls, type) and issubclass(cls, BaseModel)):
            return None
        campo = cls.model_fields.get(parte)
        if campo is None:
            return None
        cls = campo.annotation
    return campo


def test_el_barrido_no_es_vacuo() -> None:
    """Con cero entradas, todos los tests de abajo pasarían por vacuidad."""
    entradas = _entradas()
    assert len(entradas) >= 4, f"el catálogo declara sólo {len(entradas)} insumos externos"
    ids = {job_id for job_id, _ in entradas}
    assert {"provision_interna", "validar_modelo"} <= ids, ids


def test_toda_entrada_declara_sus_cinco_piezas() -> None:
    """Forma mínima: a medias deja a la interfaz sin qué pedir o sin dónde escribir la respuesta."""
    for job_id, entrada in _entradas():
        assert set(entrada) == _CLAVES_DE_ENTRADA, f"{job_id}: {sorted(entrada)}"
        assert len(entrada["artifact"]) == 2, f"{job_id}: la clave no es (dominio, clave)"
        assert entrada["key_question"].endswith("?"), f"{job_id}: la llave no se pregunta"
        assert entrada["columns"], f"{job_id}: un insumo sin columnas que mapear no se puede pedir"
        for columna in entrada["columns"]:
            assert set(columna) == _CLAVES_DE_COLUMNA, f"{job_id}: {sorted(columna)}"
            assert columna["question"].endswith("?"), f"{job_id}: {columna['question']!r}"
            assert columna["config_paths"], f"{job_id}: un rol sin campo donde escribirse"


def test_toda_clave_declarada_la_publica_un_paso_del_motor() -> None:
    """Dirección 1: no se puede pedir un archivo que ningún paso va a consumir."""
    cargar_configs_de_dominio()
    huerfanas: list[str] = []
    for job_id, entrada in _entradas():
        dominio, clave = entrada["artifact"]
        if dominio not in _DOMAIN_MODULES:
            huerfanas.append(f"{job_id}: dominio desconocido {dominio!r}")
            continue
        publicadas = _publicadas_por(dominio)
        if not publicadas:
            continue  # extra ausente: su dominio no registró pasos y no hay nada que comprobar
        if (dominio, clave) not in publicadas:
            huerfanas.append(f"{job_id}: ({dominio}, {clave}) no la publica ningún paso")
    assert huerfanas == [], huerfanas


def test_todo_campo_del_mapeo_existe_en_el_motor() -> None:
    """Dirección 2: el mapeo por clicks escribe en campos reales, no en coordenadas muertas."""
    cargar_configs_de_dominio()
    inexistentes = [
        f"{job_id}: {path}"
        for job_id, entrada in _entradas()
        for columna in entrada["columns"]
        for path in columna["config_paths"]
        if _campo_en(path) is None
    ]
    assert inexistentes == [], (
        f"campos del mapeo que el motor no tiene: {inexistentes}. Si un campo se renombró, "
        "actualiza `external_artifacts` en `nikodym/ui/jobs.py`."
    )


def test_la_condicion_apunta_a_un_campo_real_y_a_un_valor_admitido() -> None:
    """`when` es lo que evita fijar una clave que depende del config.

    ⚠️ Es el caso de `provisioning_internal`, que pide una clave **u otra** según de dónde salga la
    PD. Un `when` que apuntara a un campo inexistente, o a un valor que el campo no admite, dejaría
    la condición siempre falsa y el trabajo pediría el archivo equivocado — en silencio.
    """
    cargar_configs_de_dominio()
    for job_id, entrada in _entradas():
        condicion = entrada["when"]
        if condicion is None:
            continue
        assert set(condicion) == {"path", "equals"}, f"{job_id}: {sorted(condicion)}"
        campo = _campo_en(condicion["path"])
        assert campo is not None, f"{job_id}: `when` apunta a {condicion['path']}, que no existe"
        admitidos = typing.get_args(campo.annotation)
        if admitidos:
            assert condicion["equals"] in admitidos, (
                f"{job_id}: {condicion['path']} no admite {condicion['equals']!r}; "
                f"admite {admitidos}"
            )


def test_todo_trabajo_con_insumo_declarado_se_lo_dice_al_usuario() -> None:
    """Lo máquina-legible y el copy no pueden contradecirse.

    Un trabajo que acepta un archivo y no lo anuncia manda al usuario a una pantalla donde de
    pronto le piden algo que la landing no mencionó. El recíproco NO se exige: «PD lifetime»
    describe un insumo opcional del método que no viaja por la puerta, y eso es correcto.
    """
    mudos = [
        job["id"] for job in list_jobs() if job["external_artifacts"] and not job["external_input"]
    ]
    assert mudos == [], f"trabajos que aceptan un archivo y no lo anuncian: {mudos}"


def test_la_allowlist_solo_toma_de_los_trabajos_disponibles() -> None:
    """Un trabajo que no se puede iniciar no presta su clave para que otro la inyecte."""
    admitidos = artefactos_admitidos()
    de_no_disponibles = {
        (entrada["artifact"][0], entrada["artifact"][1])
        for job in list_jobs()
        if job["status"] == "unavailable"
        for entrada in job["external_artifacts"]
    }
    de_disponibles = {
        (entrada["artifact"][0], entrada["artifact"][1])
        for job in list_jobs()
        if job["status"] == "available"
        for entrada in job["external_artifacts"]
    }
    assert admitidos == frozenset(de_disponibles)
    assert not (admitidos & (de_no_disponibles - de_disponibles))


#: Lo que el copy de un insumo NO puede contener: la clave del artefacto, el nombre de un campo o
#: cualquier literal que sólo signifique algo dentro del código. Mismo criterio que el gate de copy
#: del catálogo y el de las decisiones obligatorias.
_JERGA = re.compile(
    r"\b(None|True|False|null|artifact|artefacto|dataset_id|config_hash|DataFrame|dataframe|"
    r"pd_column|pd_source|score_column|partition_column|target_column|calibrated_pd_frame|"
    r"raw_pd_frame|scorecard\.|calibration\.)\b"
)


def test_el_copy_del_insumo_no_habla_en_jerga_interna() -> None:
    """`label`, `key_question` y cada `question` los lee un analista; `artifact` no."""
    ofensores: list[str] = []
    for job_id, entrada in _entradas():
        textos = [("label", entrada["label"]), ("key_question", entrada["key_question"])]
        textos += [("question", columna["question"]) for columna in entrada["columns"]]
        for campo, texto in textos:
            encontrado = _JERGA.search(texto)
            if encontrado:
                ofensores.append(f"{job_id}.{campo}: «{encontrado.group(0)}»")
    assert ofensores == [], ofensores


def test_el_catalogo_devuelve_copias_del_insumo() -> None:
    """Mutar la respuesta no puede envenenar el catálogo del proceso."""
    primero = next(entrada for _, entrada in _entradas())
    primero["label"] = "PISADO"
    primero["columns"][0]["config_paths"].append("inventado")
    segundo = next(entrada for _, entrada in _entradas())
    assert segundo["label"] != "PISADO"
    assert "inventado" not in segundo["columns"][0]["config_paths"]


def test_las_dos_claves_de_validar_un_modelo_son_las_que_el_motor_exige() -> None:
    """Ancla nominal, escrita a mano: sin ella el gate sería una tautología del catálogo.

    Las dos las exigen `performance` y `stability` en su `requires`, y el motor **obliga a que
    compartan índice**. Por eso la interfaz propone una sola tabla para ambas (D-PUE-4).
    """
    if "performance" not in cargar_configs_de_dominio():
        pytest.skip("el extra de performance no está instalado")
    por_id = {job["id"]: job for job in list_jobs()}
    claves = [tuple(e["artifact"]) for e in por_id["validar_modelo"]["external_artifacts"]]
    assert claves == [("calibration", "calibrated_pd_frame"), ("scorecard", "score")]
    internas = [tuple(e["artifact"]) for e in por_id["provision_interna"]["external_artifacts"]]
    assert internas == [("calibration", "calibrated_pd_frame"), ("model", "raw_pd_frame")], (
        "el método interno pide una clave u otra según de dónde salga la PD: las dos se declaran"
    )
