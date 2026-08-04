"""Gate de la enmienda TRABAJO-EJECUTABLE (D-EJE-1…7).

🔴 **Un trabajo `available` promete en la pantalla que se puede hacer, y nadie lo comprobaba.**
Medido sobre `a71d3e2`: **tres de los diez** producían un config que el motor rechaza antes de leer
una fila — quien entraba por ellos y contestaba todo lo que se le pedía obtenía un error del DAG.
Y el censo del abanico sólo había visto **dos**: el tercero salió al construir este gate.

Es la misma clase que D-OBL-11 cerró para los capítulos del informe, y aquella se descubrió
**corriendo el gate de aceptación a mano, no en la suite** (`web/src/lib/jobs.test.ts`). Esto es esa
lección convertida en gate: el defecto reaparece con cualquier trabajo nuevo.

⚠️ **Alcance declarado (D-EJE-7).** Mide que el pipeline **resuelva**, no que la corrida termine
bien: eso necesita además un dataset con las columnas correctas, que es otra pregunta y tiene su
propio mecanismo (`check_dataset`). Decir que este gate garantiza «el trabajo funciona» sería la
sobrepromesa que D-PRE-4 evita declarando su alcance.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest

pytest.importorskip("fastapi", reason="el catálogo de trabajos vive en la capa ui")

from nikodym.api import check_pipeline
from nikodym.core.config import NikodymConfig
from nikodym.core.config.effective_defaults import (
    DISCRIMINADOR,
    build_effective_defaults,
)
from nikodym.ui.jobs import list_jobs

#: Relleno de las cuatro decisiones obligatorias (D-EJE-6).
#:
#: Un esqueleto real llega con ellas **sin contestar** —son `DATO-INSTITUCIONAL` y eso es D-OBL-6—,
#: así que preguntarle al motor sobre el esqueleto crudo mediría otra cosa. Lo que este gate mide es
#: *«contestadas las obligatorias, ¿corre?»*, que es la pregunta de quien entra por el trabajo.
#:
#: ⚠️ Los valores son el **mínimo que construye**, no una recomendación metodológica: la partición
#: aleatoria es la única forma sin huecos, y el resto son nombres de columna cualesquiera. Nada de
#: esto viaja a ningún preset.
_DECISIONES_CONTESTADAS: dict[str, dict[str, Any]] = {
    "data": {
        "target": {"bad_rule": {"all_of": [{"col": "dpd", "op": ">", "value": 90}], "any_of": []}},
        "partition": {
            "strategy": {
                "type": "random",
                "dev_fraction": 0.7,
                "holdout_fraction": 0.15,
                "oot_fraction": 0.15,
                "stratify_by": None,
            }
        },
    },
    "survival": {"input": {"duration_col": "tiempo", "event_col": "evento"}},
}


def _es_descriptor(nodo: Any) -> bool:
    """Réplica de `isDescriptor` (`web/src/lib/effective-defaults.ts`): por TIPO, no presencia."""
    return isinstance(nodo, dict) and isinstance(nodo.get(DISCRIMINADOR), bool)


def _hijos_de(nodo: Any) -> dict[str, Any] | None:
    """Réplica de `childMap`: un descriptor expone `children` (o nada); un mapa desnudo, a sí."""
    if nodo is None:
        return None
    if _es_descriptor(nodo):
        hijos = nodo.get("children")
        return hijos if isinstance(hijos, dict) else None
    return nodo if isinstance(nodo, dict) else None


def _proyeccion_canonica(mapa: dict[str, Any] | None) -> dict[str, Any]:
    """Réplica de `canonicalProjection`: escribe sólo las hojas CON default, recursivamente.

    🔴 Un descriptor **sin** default se omite entero y **no se desciende a sus hijos**, aunque los
    tenga: es lo que deja fuera del esqueleto a las decisiones obligatorias (D-OBL-2), y es la razón
    de que `_DECISIONES_CONTESTADAS` exista.
    """
    salida: dict[str, Any] = {}
    if not mapa:
        return salida
    for clave, nodo in mapa.items():
        if _es_descriptor(nodo):
            if nodo[DISCRIMINADOR]:
                salida[clave] = copy.deepcopy(nodo["value"])
        else:
            salida[clave] = _proyeccion_canonica(nodo)
    return salida


def _esqueleto(job: dict[str, Any], catalogo: dict[str, Any]) -> dict[str, Any]:
    """El config que la pantalla siembra al entrar por este trabajo.

    ⚠️ **Es una réplica de `jobSkeleton` (`web/src/lib/jobs.ts`), y eso es una deuda declarada.** No
    hay forma de compararlas ejecutándolas —una es TypeScript y la otra Python—, así que lo que las
    ata es el orden de los tres pasos y un gate estático que vigila que el front no gane un cuarto
    sin que nadie lo mire (`test_la_siembra_del_front_sigue_teniendo_estos_tres_pasos`).
    """
    esqueleto: dict[str, Any] = {}
    for seccion in job["sections"]:
        nodo = catalogo["sections"].get(seccion)
        hijos = _hijos_de(nodo)
        if hijos is None:
            continue
        esqueleto[seccion] = _proyeccion_canonica(hijos)

    for ruta, valor in job["overrides"]:
        tramos = ruta.split(".")
        if tramos[0] not in esqueleto:
            continue
        nodo_actual: dict[str, Any] = esqueleto
        for tramo in tramos[:-1]:
            # Los tramos que falten se CREAN: la proyección canónica omite los submodelos
            # obligatorios enteros, y el único override que hay hoy escribe dentro de uno.
            if not isinstance(nodo_actual.get(tramo), dict):
                nodo_actual[tramo] = {}
            nodo_actual = nodo_actual[tramo]
        nodo_actual[tramos[-1]] = copy.deepcopy(valor)

    _recortar_capitulos(esqueleto, job)
    return esqueleto


def _recortar_capitulos(esqueleto: dict[str, Any], job: dict[str, Any]) -> None:
    """Réplica de `recortarCapitulosDelInforme` (D-OBL-11): intersección, nunca añadir."""
    secciones = esqueleto.get("report", {}).get("sections")
    if not isinstance(secciones, dict):
        return
    exigidos = secciones.get("required_sections")
    if not isinstance(exigidos, list):
        return
    suyas = set(job["sections"])
    secciones["required_sections"] = [c for c in exigidos if c in suyas]


def _con_decisiones_contestadas(esqueleto: dict[str, Any]) -> dict[str, Any]:
    """Contesta las obligatorias de las secciones que el trabajo declara, y sólo ésas."""
    completo = copy.deepcopy(esqueleto)
    for seccion, bloques in _DECISIONES_CONTESTADAS.items():
        if seccion not in completo:
            continue
        for clave, valor in bloques.items():
            destino = completo[seccion].setdefault(clave, {})
            if isinstance(destino, dict):
                destino.update(copy.deepcopy(valor))
            else:
                completo[seccion][clave] = copy.deepcopy(valor)
    return completo


def _claves_externas(job: dict[str, Any], config: dict[str, Any]) -> list[tuple[str, str]]:
    """Las claves que este trabajo acepta por la puerta, filtradas por su condición.

    ⚠️ **Filtrar por `when` no es un detalle**: inyectar las dos claves excluyentes de un trabajo lo
    deja ejecutable pero con una inerte, y un gate que tratara `inert_artifacts` como error daría
    falso rojo. Se inyecta lo que ese config realmente admitiría.
    """
    claves: list[tuple[str, str]] = []
    for entrada in job["external_artifacts"]:
        cuando = entrada["when"]
        if cuando is not None and _valor_en(config, cuando["path"]) != cuando["equals"]:
            continue
        dominio, clave = entrada["artifact"]
        claves.append((dominio, clave))
    return claves


def _valor_en(config: dict[str, Any], ruta: str) -> Any:
    nodo: Any = config
    for tramo in ruta.split("."):
        if not isinstance(nodo, dict):
            return None
        nodo = nodo.get(tramo)
    return nodo


@pytest.fixture(scope="module")
def catalogo() -> dict[str, Any]:
    return build_effective_defaults()


@pytest.fixture(scope="module")
def trabajos() -> list[dict[str, Any]]:
    return list_jobs()


def _ids() -> list[str]:
    return [job["id"] for job in list_jobs()]


# --------------------------------------------------------------------------------------------
# 1. La promesa: un trabajo disponible produce un config que el motor acepta
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize("job_id", _ids())
def test_un_trabajo_disponible_produce_un_config_ejecutable(
    job_id: str, trabajos: list[dict[str, Any]], catalogo: dict[str, Any]
) -> None:
    """D-EJE-1, sobre los DIEZ. El defecto reaparece con cualquier trabajo nuevo.

    Un trabajo no disponible se salta: su promesa es la contraria y el catálogo ya la declara con su
    motivo. Comprobarlo aquí exigiría que un trabajo apagado corriera, que es lo opuesto.
    """
    job = next(j for j in trabajos if j["id"] == job_id)
    if job["status"] != "available":
        pytest.skip(f"«{job['label']}» no está disponible: {job['unavailable_reason']}")

    crudo = _con_decisiones_contestadas(_esqueleto(job, catalogo))
    config = NikodymConfig.model_validate(crudo)
    veredicto = check_pipeline(config, artifacts=_claves_externas(job, crudo) or None)

    assert veredicto.executable, (
        f"«{job['label']}» está disponible en la pantalla y su esqueleto NO corre. "
        f"{veredicto.message}"
    )
    assert veredicto.steps, "un pipeline ejecutable resuelve al menos un paso"


def test_el_barrido_no_es_vacuo(trabajos: list[dict[str, Any]]) -> None:
    """Un gate que recorre cero da verde y no prueba nada: pasó ya dos veces en este repo."""
    disponibles = [j for j in trabajos if j["status"] == "available"]
    assert len(trabajos) == 10, f"el catálogo tiene {len(trabajos)} trabajos, no 10"
    assert len(disponibles) >= 7, f"sólo {len(disponibles)} disponibles: el gate mediría casi nada"
    for ancla in ("scorecard_pd", "pd_lifetime", "comparar_provisiones", "provisiones_ifrs9"):
        assert ancla in {j["id"] for j in disponibles}, f"«{ancla}» debería estar disponible"


def test_el_esqueleto_no_llega_vacio(
    trabajos: list[dict[str, Any]], catalogo: dict[str, Any]
) -> None:
    """Control del andamiaje: si la proyección se rompiera, todo saldría «ejecutable» por vacío."""
    for job in trabajos:
        esqueleto = _esqueleto(job, catalogo)
        assert set(esqueleto) == set(job["sections"]), (
            f"«{job['label']}»: el esqueleto siembra {sorted(esqueleto)} y el trabajo declara "
            f"{sorted(job['sections'])}"
        )
        assert esqueleto["data"], "la sección data no puede quedar vacía"


# --------------------------------------------------------------------------------------------
# 2. Los overrides son un dato del catálogo, no una lista suelta
# --------------------------------------------------------------------------------------------


def test_todo_override_apunta_a_una_seccion_que_el_trabajo_declara(
    trabajos: list[dict[str, Any]],
) -> None:
    """Un override sobre una sección ajena se aplicaría al vacío y no haría nada, en silencio."""
    for job in trabajos:
        for ruta, _valor in job["overrides"]:
            seccion = ruta.split(".", 1)[0]
            assert seccion in job["sections"], (
                f"«{job['label']}» siembra «{ruta}» y no declara la sección «{seccion}»"
            )


def test_todo_override_apunta_a_un_campo_que_existe(
    trabajos: list[dict[str, Any]], catalogo: dict[str, Any]
) -> None:
    """Una ruta con una errata se aplicaría igual y crearía un campo que el motor rechaza.

    Se comprueba contra el catálogo de defaults efectivos, que es el mismo dato del que sale el
    esqueleto: si el campo no está ahí, la pantalla tampoco lo pinta.
    """
    for job in trabajos:
        for ruta, valor in job["overrides"]:
            nodo: Any = catalogo["sections"]
            for tramo in ruta.split("."):
                hijos = _hijos_de(nodo)
                assert hijos is not None and tramo in hijos, (
                    f"«{job['label']}»: la ruta «{ruta}» no existe en el config del motor"
                )
                nodo = hijos[tramo]
            assert _es_descriptor(nodo), f"«{ruta}» no es una hoja: un override escribe un valor"
            assert valor != nodo.get("value"), (
                f"«{job['label']}» siembra «{ruta}» con el mismo valor que el default del motor: "
                "un override que no cambia nada es ruido que alguien mantendrá para siempre"
            )


def test_un_override_construye_el_config(
    trabajos: list[dict[str, Any]], catalogo: dict[str, Any]
) -> None:
    """Y el valor sembrado sobrevive a la validación: no lo descarta ningún coercionador."""
    for job in trabajos:
        if not job["overrides"]:
            continue
        crudo = _con_decisiones_contestadas(_esqueleto(job, catalogo))
        config = NikodymConfig.model_validate(crudo)
        volcado = config.model_dump(mode="json")
        for ruta, valor in job["overrides"]:
            assert _valor_en(volcado, ruta) == valor, (
                f"«{job['label']}»: el valor sembrado en «{ruta}» no sobrevivió a la validación"
            )


# --------------------------------------------------------------------------------------------
# 3. La réplica de la siembra no puede divergir del front sin que nadie lo note
# --------------------------------------------------------------------------------------------


def test_la_siembra_del_front_sigue_teniendo_estos_tres_pasos() -> None:
    """⚠️ El ancla de la deuda declarada en `_esqueleto`.

    `jobSkeleton` vive en TypeScript y su réplica aquí en Python; no hay forma de ejecutarlas y
    compararlas. Lo que sí se puede es exigir que el front siga haciendo **exactamente** los tres
    pasos que esta réplica reproduce, en ese orden. Si gana un cuarto, este gate se pone rojo y
    obliga a mirarlo — que es todo lo que un ancla puede prometer, y más que callarse.
    """
    from pathlib import Path

    fuente = Path(__file__).resolve().parents[2] / "web" / "src" / "lib" / "jobs.ts"
    cuerpo = fuente.read_text(encoding="utf-8")
    inicio = cuerpo.index("export function jobSkeleton(")
    cuerpo_funcion = cuerpo[inicio : cuerpo.index("\n}", inicio)]

    pasos = (
        "canonicalProjection",
        "aplicarOverridesDelTrabajo",
        "recortarCapitulosDelInforme",
    )
    for paso in pasos:
        assert paso in cuerpo_funcion, (
            f"`jobSkeleton` ya no llama a `{paso}`: la réplica de Python de este archivo dejó de "
            "describir lo que la pantalla hace"
        )

    assert cuerpo_funcion.index("aplicarOverridesDelTrabajo") < cuerpo_funcion.index(
        "recortarCapitulosDelInforme"
    ), "los overrides se aplican ANTES del recorte de capítulos; el orden es parte del contrato"
