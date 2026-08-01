"""Gate del catálogo de defaults efectivos (enmienda DEFAULTS-EFECTIVOS-UI, D-FX-5/D-FX-6).

El catálogo existe porque JSON Schema **no aplica defaults** y no los emite para los submodelos que
nacen de un ``default_factory``. Un gate que sólo comprobara que el catálogo «tiene entradas» no
probaría nada: lo que hay que demostrar es que **coincide con la coacción real** de Pydantic, campo
por campo, y que **recorre el formulario entero** en vez de una muestra cómoda.

De ahí las tres piezas de este archivo:

1. **Paridad** contra ``FieldInfo.get_default(call_default_factory=True)`` y, en los modelos
   construibles, contra ``Cls().model_dump(mode="json", by_alias=True)``. Son las dos formas en que
   el motor materializa un default; si el catálogo se separa de cualquiera de ellas, miente.
2. **No vacuidad**: las 394 hojas que el formulario pinta hoy, con anclas nombradas. La cifra es un
   golden: moverla es legítimo —el formulario crece— pero exige actualizarla en el mismo cambio, que
   es justo lo que impide que un barrido se quede en cero sin que nadie se entere. Ya pasó con
   ``test_copy_del_formulario.py``, cuya primera versión daba verde recorriendo **cero** campos.
3. **Controles negativos**: se dopa el catálogo y el gate de paridad tiene que ponerse rojo.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from pydantic import BaseModel, TypeAdapter, ValidationError

from nikodym.core.config import NikodymConfig
from nikodym.core.config.effective_defaults import (
    DESCRIPTOR_KEYS,
    DISCRIMINADOR,
    EFFECTIVE_DEFAULTS_VERSION,
    build_effective_defaults,
    modelos_de_anotacion,
)
from nikodym.core.config.schema import build_full_json_schema, cargar_configs_de_dominio
from nikodym.core.exceptions import NikodymError
from nikodym.ml.config import MLConfig
from nikodym.ui.routes import schema_payload

#: Hojas visibles del formulario hoy. Medido con el mismo recorrido de
#: ``test_copy_del_formulario.py``: el nodo de una lista cuenta (tiene título propio en pantalla) y
#: sus ``items`` bajan a la fila editable. Subirlo o bajarlo es legítimo; hacerlo en silencio, no.
HOJAS_DEL_FORMULARIO = 394

#: Descriptores de hoja que el barrido de paridad compara, en las DOS coordenadas (`$defs` y
#: `sections`). Segundo golden, por la misma razón que el de 394: un barrido que recorra menos
#: campos de los que hay no está midiendo el config entero — y eso ya dejó pasar una divergencia.
#:
#: 1024 → 1034 el 2026-08-01 con D-OBL-2: los **10** submodelos obligatorios pasaron de mapa desnudo
#: a descriptor con hijos, y un descriptor sí se cuenta. Son `data.target`, `data.partition`,
#: `data.target.bad_rule`, `survival.input`, los tres de `forward` y sus tres copias en `$defs`;
#: están enumerados uno a uno en `test_los_submodelos_obligatorios_son_exactamente_estos`, para que
#: el golden no pueda absorber en silencio un onceavo que nadie decidió.
#:
#: ⚠️ Al implementar la enmienda este número bajó primero a **996**, y ahí estuvo el riesgo: no era
#: que hubiera menos descriptores, era que el emparejador cortaba al ver uno y dejaba de bajar por
#: los hijos de los obligatorios. Mover el golden a 996 habría enterrado 28 campos sin comparar.
DESCRIPTORES_TOTALES = 1034


#: Las 14 secciones que el formulario ofrece. Espejo de ``SECCIONES_DEL_FORMULARIO`` de
#: ``test_copy_del_formulario.py``; el gate de deriva de ese catálogo vive en
#: ``test_column_roles.py``.
SECCIONES_ESPERADAS = (
    "data",
    "binning",
    "selection",
    "model",
    "scorecard",
    "calibration",
    "performance",
    "stability",
    "survival",
    "provisioning_cmf",
    "provisioning_internal",
    "provisioning_ifrs9",
    "provisioning",
    "report",
)


def _formulario_completo() -> bool:
    """¿Están las 14 secciones del formulario expandidas en esta instalación?

    Los dos goldens de cifra —394 hojas y los descriptores— sólo son comparables con **todos** los
    extras: el job matriz del CI instala sólo ``scoring``, y ahí ``survival`` (lifelines) y las de
    provisiones no se expanden, de modo que exigir el número exacto sería un rojo por instalación,
    no por defecto. Con el extra ausente el gate sigue midiendo cobertura TOTAL de lo que sí hay:
    lo único que se relaja es la cifra, y se dice por qué en vez de callarlo.
    """
    return set(SECCIONES_ESPERADAS) <= set(cargar_configs_de_dominio())


#: Las seis de la muestra adversarial del censo (§6 de la enmienda), con su valor coaccionado real.
#: Son a mano y no derivadas del catálogo: un oráculo calculado por el código que vigila no vigila.
MUESTRA_ADVERSARIAL: tuple[tuple[tuple[str, ...], Any], ...] = (
    (("model", "stepwise", "enabled"), True),
    (("selection", "correlation", "enabled"), True),
    (("selection", "vif", "threshold"), 5.0),
    (("provisioning_cmf", "matrices", "active_version"), "cmf_b1_b3_2025_01"),
    (("provisioning_ifrs9", "pd", "pit_mode"), "consume_pit"),
    (("provisioning_ifrs9", "staging", "dpd_default_backstop"), 90),
)

#: Los dos casos vivos que el censo encontró en el preset F1 (§6): el formulario los pintaba
#: apagado y en blanco mientras el motor corría con `True` y con `show`.
CASOS_VIVOS_F1: tuple[tuple[tuple[str, ...], Any], ...] = (
    (("report", "html", "render_charts"), True),
    (("report", "document", "placeholders"), "show"),
)


def _en(catalogo: dict[str, Any], ruta: tuple[str, ...]) -> Any:
    """Baja por la coordenada ``sections`` del catálogo."""
    nodo: Any = catalogo["sections"]
    for tramo in ruta:
        assert isinstance(nodo, dict) and tramo in nodo, f"ruta inexistente en el catálogo: {ruta}"
        nodo = nodo[tramo]
    return nodo


# ---------------------------------------------------------------------------------------------
# Forma del artefacto
# ---------------------------------------------------------------------------------------------


def test_forma_versionada_y_determinista() -> None:
    """Tres coordenadas, versión declarada y bytes repetibles."""
    catalogo = build_effective_defaults()
    assert set(catalogo) == {"version", "sections", "$defs"}
    assert catalogo["version"] == EFFECTIVE_DEFAULTS_VERSION
    # Determinismo: el payload viaja al fixture versionado, así que dos llamadas iguales.
    assert json.dumps(catalogo, sort_keys=True) == json.dumps(
        build_effective_defaults(), sort_keys=True
    )
    # Y es JSON puro: nada de tuplas, Decimales ni Enums crudos.
    json.dumps(catalogo)


def test_las_claves_de_defs_son_las_del_json_schema() -> None:
    """D-FX-5: las claves de ``$defs`` son literalmente las que referencia ``json_schema``.

    Es lo que permite al front resolver una fila de lista o una variante siguiendo el ``$ref`` que
    ya tiene en la mano, sin inventar un identificador paralelo. Si Pydantic renombrara un ``$def``
    —colisión de nombres entre dos clases homónimas de un mismo dominio—, este test se pone rojo en
    vez de dejar al formulario resolviendo a ciegas.
    """
    schema = build_full_json_schema()
    defs_schema = {k for k, v in schema.get("$defs", {}).items() if "properties" in v}
    catalogo = build_effective_defaults()
    assert set(catalogo["$defs"]) == defs_schema
    assert defs_schema, "sin `$defs` el test sería vacuo"


def test_un_descriptor_se_distingue_de_un_mapa_de_hijos() -> None:
    """La regla de discriminación es decidible en todo el catálogo.

    Descriptor ⟺ ``has_default`` **booleano**. ``value`` no es reservada y no puede serlo: el config
    ya tiene campos llamados así (``data.target.bad_rule`` lleva predicados con ``value``). El día
    que un config declare un campo ``has_default``, su nodo sería un *dict* y la regla —que exige el
    tipo, no la presencia— seguiría decidiendo bien; este test lo comprueba en vez de suponerlo.
    """
    catalogo = build_effective_defaults()
    descriptores = 0

    def recorrer(nodo: Any, ruta: str) -> None:
        nonlocal descriptores
        if not isinstance(nodo, dict):
            raise AssertionError(f"nodo que no es dict en {ruta}: {type(nodo).__name__}")
        if isinstance(nodo.get(DISCRIMINADOR), bool):
            assert set(nodo) <= set(DESCRIPTOR_KEYS), f"descriptor con claves extra en {ruta}"
            descriptores += 1
            # Un submodelo obligatorio es descriptor Y tiene hijos (D-OBL-2): el recorrido sigue
            # dentro, o la comprobación de forma no alcanzaría a las hojas de `data.target`.
            nietos = nodo.get("children")
            if isinstance(nietos, dict):
                for clave, nieto in nietos.items():
                    recorrer(nieto, f"{ruta}.children.{clave}")
            return
        for clave, hijo in nodo.items():
            recorrer(hijo, f"{ruta}.{clave}")

    for coordenada in ("sections", "$defs"):
        for nombre, nodo in catalogo[coordenada].items():
            recorrer(nodo, f"{coordenada}.{nombre}")
    assert descriptores > 200, f"el recorrido no puede quedarse en {descriptores} descriptores"
    # El campo `value` existe de verdad y no rompe la regla: es una hoja como cualquier otra.
    assert isinstance(
        catalogo["$defs"]["data__Predicate"]["value"][DISCRIMINADOR],
        bool,
    )


def test_un_submodelo_apagado_publica_su_default_nulo() -> None:
    """Un submodelo cuyo default es ``None`` va como descriptor, no como mapa de hijos.

    ``data.target.good_rule`` nace apagado. Si se publicara como mapa, el formulario no tendría
    forma de saber que su valor efectivo es ``null`` y pintaría el interruptor **encendido** sobre
    un objeto que el motor no crea. Los hijos siguen alcanzables por ``$defs`` para el momento en
    que el usuario lo active.
    """
    catalogo = build_effective_defaults()
    objetivo = _hijos_de(catalogo["sections"]["data"]["target"])
    assert objetivo["good_rule"] == {"has_default": True, "value": None}
    assert objetivo["window"] == {"has_default": True, "value": None}
    # Y la proyección para activarlo vive en `$defs`.
    assert "all_of" in catalogo["$defs"]["data__Rule"]


def test_un_submodelo_obligatorio_es_descriptor_con_hijos() -> None:
    """D-OBL-2: un submodelo OBLIGATORIO declara su hueco **y** conserva sus hijos.

    Este test aseveraba lo contrario hasta el 2026-08-01 —``"has_default" not in bad_rule``—, o sea
    que **codificaba el defecto**: sin descriptor, la proyección canónica no podía omitir el campo y
    escribía ``bad_rule = {all_of: [], any_of: []}``, que el motor rechaza con «una Rule debe
    declarar al menos un predicado». Los diez trabajos del catálogo nacían con config inválido.

    Las dos mitades importan. El descriptor es lo que permite OMITIRLO (D-FX-8); los hijos son
    lo que permite al formulario seguir pintando que ``target_col`` vale ``"target"``. Un
    descriptor pelado habría arreglado el config y degradado D-FX-5.
    """
    catalogo = build_effective_defaults()
    objetivo = _hijos_de(catalogo["sections"]["data"]["target"])

    # `data.target` es obligatorio dentro de `DataConfig`.
    nodo_target = catalogo["sections"]["data"]["target"]
    assert nodo_target["has_default"] is False
    assert "value" not in nodo_target
    assert isinstance(nodo_target["children"], dict) and nodo_target["children"]

    # `bad_rule` es obligatorio dentro de `TargetConfig`, y conserva los defaults de sus hijos.
    assert objetivo["bad_rule"]["has_default"] is False
    assert "value" not in objetivo["bad_rule"]
    assert objetivo["bad_rule"]["children"]["all_of"] == {"has_default": True, "value": []}

    # `survival.input` es el mismo caso en otra sección: no era un defecto de `data`.
    if "survival" in cargar_configs_de_dominio():
        entrada = catalogo["sections"]["survival"]["input"]
        assert entrada["has_default"] is False
        assert entrada["children"]["duration_col"] == {"has_default": False}


def _hijos_de(nodo: dict[str, Any]) -> dict[str, Any]:
    """Los hijos de un nodo, sea mapa desnudo o descriptor con ``children``.

    Espejo de ``childMap`` de ``web/src/lib/effective-defaults.ts``: el front resuelve esta misma
    ambigüedad, y tenerla escrita dos veces con criterios distintos es como se separan las dos
    superficies.
    """
    if isinstance(nodo.get(DISCRIMINADOR), bool):
        hijos = nodo.get("children")
        return hijos if isinstance(hijos, dict) else {}
    return nodo


#: Los submodelos obligatorios del config, uno a uno. Escrita a MANO y no derivada del catálogo: si
#: saliera del propio recorrido sería una tautología, y este repo ya pagó ese error una vez.
SUBMODELOS_OBLIGATORIOS: tuple[str, ...] = (
    "$defs.data__ExclusionRule.rule",
    "$defs.data__TargetConfig.bad_rule",
    "$defs.forward__ForwardInputConfig.macro_source",
    "sections.data.partition",
    "sections.data.target",
    "sections.data.target.bad_rule",
    "sections.forward.input",
    "sections.forward.input.macro_source",
    "sections.forward.satellite",
    "sections.survival.input",
)


def _descriptores_con_hijos(catalogo: dict[str, Any]) -> list[str]:
    """Rutas de todo nodo que es descriptor **y** trae ``children`` (D-OBL-2)."""
    encontrados: list[str] = []

    def recorrer(nodo: Any, ruta: str) -> None:
        if not isinstance(nodo, dict):
            return
        if isinstance(nodo.get(DISCRIMINADOR), bool):
            if "children" in nodo:
                encontrados.append(ruta)
                for clave, nieto in nodo["children"].items():
                    recorrer(nieto, f"{ruta}.{clave}")
            return
        for clave, hijo in nodo.items():
            recorrer(hijo, f"{ruta}.{clave}")

    for coordenada in ("sections", "$defs"):
        for nombre, nodo in catalogo[coordenada].items():
            recorrer(nodo, f"{coordenada}.{nombre}")
    return sorted(encontrados)


def test_los_submodelos_obligatorios_son_exactamente_estos() -> None:
    """Ancla nominal del golden 1034: qué campos ganaron descriptor, no sólo cuántos.

    Un golden numérico dice que el total cuadra; no dice **cuáles**. Con sólo la cifra, convertir un
    campo opcional en obligatorio y otro obligatorio en opcional se compensaría y pasaría el gate.
    """
    if not _formulario_completo():
        pytest.skip("instalación parcial: el catálogo no publica todas las secciones")
    assert _descriptores_con_hijos(build_effective_defaults()) == list(SUBMODELOS_OBLIGATORIOS)


def test_markov_y_stress_quedan_fuera_con_su_razon() -> None:
    """D-OBL-4: la exclusión es medida, no un olvido — y por eso se asevera.

    Una lista corta sin explicación se lee como cobertura total. Estos dos siguen produciendo una
    proyección que el motor rechaza **después** de esta enmienda, y por razones distintas entre sí:

    - ``markov.input`` es un campo **no obligatorio** cuya clase no es construible. D-OBL-1 no lo
      alcanza, y no debe: el campo tiene default, así que el catálogo ya dice la verdad sobre él.
    - ``stress`` falla en el ``model_validator`` de su clase **raíz** («exige al menos un escenario,
      una sensibilidad o un reverse stress»), que ninguna proyección satisface, ni siquiera ``{}``.

    Si algún día dejan de fallar, este test se pone rojo y obliga a decidir explícitamente si entran
    al criterio, en vez de que el cambio pase inadvertido.
    """
    disponibles = cargar_configs_de_dominio()
    catalogo = build_effective_defaults()
    for seccion in ("markov", "stress"):
        if seccion not in disponibles:
            continue
        nodo = catalogo["sections"][seccion]
        assert not isinstance(nodo.get(DISCRIMINADOR), bool), (
            f"{seccion} es una sección apagable, no un submodelo obligatorio"
        )
        proyectado = _proyeccion_canonica(_hijos_de(nodo))
        # Las dos medidas son `NikodymError` (`MarkovConfigError` y `StressConfigError`); se deja
        # `ValidationError` por si la causa cambia de capa sin dejar de ser un rechazo.
        with pytest.raises((ValidationError, NikodymError)):
            disponibles[seccion].model_validate(proyectado)


def _proyeccion_canonica(mapa: dict[str, Any]) -> dict[str, Any]:
    """Réplica de ``canonicalProjection`` (``web/src/lib/effective-defaults.ts``).

    Escribe las hojas con default y **omite** las obligatorias sin default, que es lo que D-FX-8
    exige y lo que D-OBL-2 hace por fin posible para un submodelo.
    """
    salida: dict[str, Any] = {}
    for clave, nodo in mapa.items():
        if isinstance(nodo.get(DISCRIMINADOR), bool):
            if nodo[DISCRIMINADOR]:
                salida[clave] = nodo["value"]
        else:
            salida[clave] = _proyeccion_canonica(nodo)
    return salida


def test_la_proyeccion_canonica_ya_no_inventa_un_submodelo_obligatorio() -> None:
    """El gate del defecto, medido donde dolía: activar `data` y activar `survival`.

    Antes de D-OBL-2 esto escribía ``target.bad_rule = {all_of: [], any_of: []}`` y el motor lo
    rechazaba con «una Rule debe declarar al menos un predicado». Ahora el campo se OMITE y lo que
    ve el usuario es «este campo es obligatorio», que es la verdad: ``bad_rule`` es qué define un
    moroso en su cartera, y eso no lo puede inventar el motor.
    """
    disponibles = cargar_configs_de_dominio()
    catalogo = build_effective_defaults()

    proyectado = _proyeccion_canonica(_hijos_de(catalogo["sections"]["data"]))
    assert "target" not in proyectado, "un obligatorio sin default no se escribe (D-FX-8)"
    assert "partition" not in proyectado
    # Lo que sí tiene default sigue escribiéndose: la enmienda no vacía la proyección.
    assert proyectado["schema"]["strict"] is False
    assert proyectado["missing"]["max_missing_rate"] == 0.99

    if "survival" in disponibles:
        entrada = _proyeccion_canonica(_hijos_de(catalogo["sections"]["survival"]))
        assert "input" not in entrada
        assert entrada["method"] is not None


def test_has_default_false_no_trae_value() -> None:
    """``has_default=false`` OMITE ``value``; ``true`` lo trae aunque sea ``null`` (D-FX-5).

    Es la distinción que el front necesita para no confundir «sin default» con «default ``null``»:
    la primera pinta el control vacío, la segunda pinta el valor nulo que el motor usaría.
    """
    catalogo = build_effective_defaults()
    # `data.schema.columns[].name` es obligatorio: no hay default que ofrecer.
    assert catalogo["$defs"]["data__ColumnSpec"]["name"] == {"has_default": False}
    # `ge` es `float | None = None`: default explícito nulo, con `value` presente.
    assert catalogo["$defs"]["data__ColumnSpec"]["ge"] == {"has_default": True, "value": None}


# ---------------------------------------------------------------------------------------------
# Paridad con la coacción real
# ---------------------------------------------------------------------------------------------


def _pares_modelo_mapa(
    catalogo: dict[str, Any] | None = None,
) -> list[tuple[str, type[BaseModel], dict[str, Any]]]:
    """``(etiqueta, clase, mapa del catálogo)`` de **todo** modelo publicado.

    Cubre las dos coordenadas, y la segunda no es un extra: las 22 clases raíz de sección
    (``DataConfig``, ``BinningConfig``, ``ReportConfig``…) **no están en `$defs`** —el schema
    compuesto las empotra *inline*—, así que un barrido que sólo recorriera `$defs` dejaba fuera
    224 descriptores, el 32 % del catálogo. No es teoría: ahí vivía la divergencia real de
    ``ml.hyperparameters``, y el gate daba verde con ella dentro.

    ``catalogo`` se inyecta para poder correr el mismo comparador sobre un artefacto DOPADO y
    comprobar que se pone rojo; sin ese parámetro, un «control negativo» sólo compara un valor
    corrupto consigo mismo y no ejecuta el gate que dice anclar.
    """
    catalogo = catalogo if catalogo is not None else build_effective_defaults()
    dominios = cargar_configs_de_dominio()
    pares: list[tuple[str, type[BaseModel], dict[str, Any]]] = []

    def alcanzables(cls: type[BaseModel], acc: dict[str, type[BaseModel]]) -> None:
        if cls.__name__ in acc:
            return
        acc[cls.__name__] = cls
        for campo in cls.model_fields.values():
            for modelo in modelos_de_anotacion(campo.annotation):
                alcanzables(modelo, acc)

    grupos: dict[str, list[type[BaseModel]]] = {"": []}
    for campo in NikodymConfig.model_fields.values():
        grupos[""].extend(modelos_de_anotacion(campo.annotation))
    for seccion, cls in dominios.items():
        grupos[f"{seccion}__"] = [cls]

    for prefijo, raices in grupos.items():
        acc: dict[str, type[BaseModel]] = {}
        for cls in raices:
            alcanzables(cls, acc)
        for nombre, cls in acc.items():
            clave = f"{prefijo}{nombre}"
            if clave in catalogo["$defs"]:
                pares.append((clave, cls, catalogo["$defs"][clave]))

    # La coordenada `sections`, RECURSIVA. No basta el primer nivel: `sections` lleva su propia
    # copia inline de cada submodelo (`report.sections.missing_policy` vive ahí, no sólo en
    # `$defs["report__SectionPolicyConfig"]`), y una copia que nadie compara es una copia que puede
    # mentir. Lo comprobó el control negativo: dopar esa hoja no ponía rojo nada.
    def bajar(cls: type[BaseModel], mapa: Any, etiqueta: str, pila: tuple[str, ...]) -> None:
        if not isinstance(mapa, dict):
            return
        pares.append((etiqueta, cls, mapa))
        for nombre, campo in cls.model_fields.items():
            clave = campo.alias or nombre
            hijo = mapa.get(clave)
            sub = _submodelo_directo_de(campo)
            if sub is None or sub.__name__ in pila or not isinstance(hijo, dict):
                continue
            if isinstance(hijo.get(DISCRIMINADOR), bool):
                # Descriptor. Un submodelo APAGABLE se acaba aquí —su estado es el nodo—, pero uno
                # OBLIGATORIO cuelga sus hijos de `children` (D-OBL-2) y hay que seguir bajando: si
                # no, sus hojas dejan de compararse contra la coacción real. Medido al implementar
                # la enmienda: cortar aquí bajaba el barrido de 1024 a 996 descriptores, y el golden
                # habría absorbido la pérdida sin que nadie la viera.
                nietos = hijo.get("children")
                if isinstance(nietos, dict) and nietos:
                    bajar(sub, nietos, f"{etiqueta}.{clave}", (*pila, sub.__name__))
                continue
            bajar(sub, hijo, f"{etiqueta}.{clave}", (*pila, sub.__name__))

    for seccion, cls in dominios.items():
        bajar(cls, catalogo["sections"].get(seccion), f"sections.{seccion}", (cls.__name__,))
    pares.append(("sections", NikodymConfig, catalogo["sections"]))
    return pares


def _submodelo_directo_de(campo: Any) -> type[BaseModel] | None:
    """La clase del campo si es **un** submodelo; espejo del criterio del generador."""
    modelos = modelos_de_anotacion(campo.annotation)
    return modelos[0] if len(modelos) == 1 else None


def _comparar_paridad(catalogo: dict[str, Any]) -> int:
    """Compara un catálogo contra la coacción real y devuelve cuántos descriptores revisó.

    **Dos oráculos, y cuál manda depende de la clase**, porque el valor efectivo de un campo no
    siempre sale de su ``FieldInfo``:

    - Clase construible ⇒ la verdad es ``Cls().model_dump(mode="json", by_alias=True)``. Ahí ya
      corrieron los ``model_validator``, y por eso es el oráculo fuerte.
    - Clase no construible (campos obligatorios, o un validador que rechaza la instancia vacía)
      ⇒ ``FieldInfo.get_default(call_default_factory=True)``, campo a campo.

    Levanta ``AssertionError`` en la primera divergencia: es un gate, no un informe.
    """
    revisados = 0
    for etiqueta, cls, mapa in _pares_modelo_mapa(catalogo):
        try:
            volcado: dict[str, Any] | None = cls().model_dump(mode="json", by_alias=True)
        except Exception:
            volcado = None
        for nombre, campo in cls.model_fields.items():
            clave = campo.alias or nombre
            nodo = mapa[clave]
            if not (isinstance(nodo, dict) and isinstance(nodo.get("has_default"), bool)):
                continue  # submodelo: su paridad la cubren sus propias hojas
            revisados += 1
            assert nodo["has_default"] is not campo.is_required(), f"{etiqueta}.{clave}"
            if campo.is_required():
                assert "value" not in nodo, f"{etiqueta}.{clave}"
                continue
            if volcado is not None and clave in volcado:
                esperado = volcado[clave]
            else:
                esperado = TypeAdapter(campo.annotation).dump_python(
                    campo.get_default(call_default_factory=True),
                    mode="json",
                    by_alias=True,
                    warnings=False,
                )
            assert nodo["value"] == esperado, f"{etiqueta}.{clave}"
    return revisados


def test_paridad_con_la_coaccion_real() -> None:
    """El catálogo entero coincide con lo que el motor materializa, en las dos coordenadas.

    Recorre `$defs` **y** `sections`: las 22 clases raíz de sección no están en `$defs` —el schema
    compuesto las empotra inline—, así que un barrido que sólo mirara `$defs` dejaba 224
    descriptores sin comparar. No es un tecnicismo: ahí vivía la divergencia real de
    ``ml.hyperparameters``, que este gate no veía.
    """
    revisados = _comparar_paridad(build_effective_defaults())
    if not _formulario_completo():
        assert revisados > 200, f"el barrido no puede quedarse en {revisados} campos"
        return
    assert revisados == DESCRIPTORES_TOTALES, (
        f"el catálogo publica {revisados} descriptores de hoja, no {DESCRIPTORES_TOTALES}: si el "
        "cambio es legítimo, actualiza el golden en el mismo commit"
    )


def test_un_validador_de_modelo_puede_mover_el_valor_efectivo() -> None:
    """El ancla de por qué ``FieldInfo.get_default`` NO basta como única fuente.

    ``MLConfig.hyperparameters`` declara ``None`` y un ``model_validator(mode="before")`` lo rellena
    con los siete hiperparámetros del backend. El catálogo publicaba ``null`` —el default del
    campo— mientras el motor corría con el dict. Si alguien «simplifica» el generador volviendo a
    leer sólo el ``FieldInfo``, este test se pone rojo y dice por qué.
    """
    campo = MLConfig.model_fields["hyperparameters"]
    declarado = campo.get_default(call_default_factory=True)
    efectivo = MLConfig().model_dump(mode="json", by_alias=True)["hyperparameters"]
    assert declarado is None
    assert isinstance(efectivo, dict) and efectivo, "el validador debe materializarlo"
    assert declarado != efectivo, "sin divergencia, este ancla no probaría nada"

    publicado = build_effective_defaults()["sections"]["ml"]["hyperparameters"]
    assert publicado == {"has_default": True, "value": efectivo}


def test_el_reparto_de_oraculos_esta_declarado() -> None:
    """Cuántas clases se contrastan con la instancia y cuántas con el ``FieldInfo``, y cuáles.

    D-FX-5 admite las dos vías, y la que aplica depende de si la clase se puede construir vacía. Un
    barrido que se apoyara sólo en la débil dejaría de ver los validadores de relleno; uno que
    exigiera la fuerte obligaría a **inventar instancias inválidas**, que es justo lo que la
    enmienda prohíbe. Aquí se deja escrito el reparto real para que un cambio de proporción se vea.
    """
    construibles: list[str] = []
    no_construibles: list[str] = []
    for etiqueta, cls, _mapa in _pares_modelo_mapa(build_effective_defaults()):
        try:
            cls()
        except Exception:
            no_construibles.append(etiqueta)
        else:
            construibles.append(etiqueta)

    assert len(construibles) > 60, f"sólo {len(construibles)} clases con el oráculo fuerte"
    # Las no construibles existen y tienen su razón: campos obligatorios o un validador de modelo
    # que rechaza la instancia vacía. Se nombran para que la lista no crezca en silencio.
    if _formulario_completo():
        assert "sections.data" in no_construibles  # `data.schema`/`target` son obligatorios
        assert "sections.stress" in no_construibles  # exige al menos un escenario
        assert "data__Rule" in no_construibles  # exige al menos un predicado
        assert "sections.ml" in construibles  # el caso del validador de relleno
        assert "sections.report" in construibles


def test_las_variantes_publican_sus_propios_defaults() -> None:
    """Una rama de unión discriminada trae su mapa, contrastable aportando sólo lo obligatorio.

    Sin esto, elegir otra variante en el formulario dejaba sus campos en blanco aunque el modelo de
    esa variante tuviera defaults perfectamente definidos.
    """
    catalogo = build_effective_defaults()
    # Partición aleatoria: variante del discriminador `data.partition.strategy`.
    aleatoria = catalogo["$defs"]["data__RandomSplitConfig"]
    assert aleatoria["holdout_fraction"]["has_default"] is True
    from nikodym.data.config import RandomSplitConfig

    esperado = RandomSplitConfig().model_dump(mode="json", by_alias=True)
    for clave, valor in esperado.items():
        nodo = aleatoria[clave]
        if isinstance(nodo, dict) and "has_default" in nodo:
            assert nodo["value"] == valor, clave


@pytest.mark.parametrize(("ruta", "esperado"), MUESTRA_ADVERSARIAL + CASOS_VIVOS_F1)
def test_muestra_adversarial_y_casos_vivos(ruta: tuple[str, ...], esperado: Any) -> None:
    """Los seis del censo más los dos vivos de F1, con su valor escrito a mano."""
    assert _en(build_effective_defaults(), ruta) == {"has_default": True, "value": esperado}


def test_el_catalogo_no_depende_del_orden_de_imports() -> None:
    """Mismo catálogo en un proceso limpio: el resultado no puede depender de qué se importó antes.

    Es la misma trampa que produjo dos ``config_hash`` distintos en `1.8.0`. Dentro de pytest todo
    está siempre importado, así que un defecto de imports **sólo** se ve en un subproceso.
    """
    import subprocess
    import sys

    codigo = (
        "import json;"
        "from nikodym.core.config.effective_defaults import build_effective_defaults;"
        "print(json.dumps(build_effective_defaults(), sort_keys=True))"
    )
    salida = subprocess.run(
        [sys.executable, "-c", codigo], capture_output=True, text=True, check=True
    )
    assert json.loads(salida.stdout) == build_effective_defaults()


# ---------------------------------------------------------------------------------------------
# No vacuidad: el catálogo cubre el formulario ENTERO
# ---------------------------------------------------------------------------------------------


def _hojas_del_formulario() -> list[tuple[str, list[str]]]:
    """``(ruta legible, path)`` de cada nodo que el formulario pinta, sin los ocultos.

    Reusa el recorrido de ``test_copy_del_formulario`` para que las dos cifras hablen de lo mismo:
    un barrido propio daría otro número y volvería incomparables los dos gates.
    """
    from test_copy_del_formulario import _campos_visibles

    hojas: list[tuple[str, list[str]]] = []
    for ruta, _nodo in _campos_visibles():
        # `a.b[].c` → ["a", "b", "c"]: el catálogo indexa por campo, no por índice de fila.
        path = [tramo for tramo in ruta.replace("[]", "").split(".") if tramo]
        hojas.append((ruta, path))
    return hojas


#: Un ancla concreta por cada una de las 14 secciones. Escritas a mano: derivarlas del propio
#: recorrido convertiría el gate en una tautología, que es el defecto que ya se pagó una vez.
ANCLAS_POR_SECCION: dict[str, str] = {
    "data": "data.schema.columns[].name",
    "binning": "binning.feature_columns[]",
    "selection": "selection.vif.threshold",
    "model": "model.stepwise.enabled",
    "scorecard": "scorecard.pdo",
    "calibration": "calibration.target_pd",
    "performance": "performance.n_deciles",
    "stability": "stability.psi_bins",
    "survival": "survival.method",
    "provisioning_cmf": "provisioning_cmf.matrices.active_version",
    "provisioning_internal": "provisioning_internal.lgd.method",
    "provisioning_ifrs9": "provisioning_ifrs9.staging.dpd_default_backstop",
    "provisioning": "provisioning.comparison_level",
    "report": "report.document.model_name",
}


def test_el_catalogo_recorre_las_hojas_del_formulario() -> None:
    """Golden de cobertura: 394 nodos visibles y un ancla nombrada por cada una de las 14 secciones.

    Cambiar la cifra es legítimo cuando el formulario crece o encoge; hacerlo sin actualizar este
    golden y sus anclas, no. La razón está pagada: un gate que recorre cero campos da verde.
    """
    hojas = _hojas_del_formulario()
    rutas = {ruta for ruta, _ in hojas}
    disponibles = set(cargar_configs_de_dominio())
    for seccion, ancla in ANCLAS_POR_SECCION.items():
        if seccion in disponibles:
            assert ancla in rutas, f"falta el ancla {ancla}"

    if not _formulario_completo():
        # Instalación parcial (job matriz del CI, sólo `scoring`): la cifra exacta no aplica, pero
        # el barrido tiene que seguir viendo el formulario, no cero campos.
        assert len(hojas) > 200
        return
    assert len(hojas) == HOJAS_DEL_FORMULARIO, (
        f"el formulario pinta {len(hojas)} nodos, no {HOJAS_DEL_FORMULARIO}: si el cambio es "
        "legítimo, actualiza el golden y sus anclas en el mismo commit"
    )


def _ref_de(nodo: Any) -> str | None:
    """Clave del ``$def`` al que apunta un nodo del schema, bajando por la rama no nula.

    Espejo de ``refName`` del front (``web/src/lib/form-engine.ts``): el gate tiene que resolver
    **como resuelve el formulario**, o mediría otra cosa.
    """
    if not isinstance(nodo, dict):
        return None
    if isinstance(nodo.get("$ref"), str):
        return str(nodo["$ref"]).rsplit("/", 1)[-1]
    ramas = [r for r in (nodo.get("anyOf") or nodo.get("oneOf") or []) if r.get("type") != "null"]
    return _ref_de(ramas[0]) if len(ramas) == 1 else None


def test_toda_hoja_visible_resuelve_como_lo_hace_el_formulario() -> None:
    """Cada nodo que el formulario pinta alcanza su descriptor por el MISMO camino que el front.

    Es el gate no vacuo de la §6. La primera versión aceptaba una fila de lista si el nombre de su
    último tramo aparecía **en cualquier** ``$def``, y eso no medía nada: borrando
    ``data__ColumnSpec``
    entero, 36 de esas hojas seguían «resolviendo» contra entradas ajenas que casualmente tienen un
    campo ``name`` o ``col``. Ahora se baja por el schema llevando el mapa de defaults al lado
    —``$ref`` si lo hay, mapa de hijos si no—, que es exactamente lo que hace ``childDefaults``.
    """
    catalogo = build_effective_defaults()
    schema = schema_payload()["json_schema"]
    defs_schema = schema.get("$defs", {})
    defs_catalogo = catalogo["$defs"]
    disponibles = set(cargar_configs_de_dominio())

    sin_resolver: list[str] = []
    resueltos = 0

    def hijos(nodo_schema: Any, resuelto: Any, nodo_catalogo: Any) -> Any:
        """El mapa de defaults de los hijos: por ``$ref`` si lo hay, si no el mapa del nodo.

        El ``$ref`` se busca en el nodo tal cual **y** en el ya resuelto, porque una unión
        DISCRIMINADA no tiene un ``$ref`` único arriba: la rama la elige el usuario, y aquí se toma
        la misma que tomó el recorrido (la primera no nula), igual que hace el formulario con
        ``discriminatedBranchRef``.
        """
        for candidato in (_ref_de(nodo_schema), _ref_de(resuelto), resuelto.get("__ref__")):
            if candidato and candidato in defs_catalogo:
                return defs_catalogo[candidato]
        if isinstance(nodo_catalogo, dict) and not isinstance(
            nodo_catalogo.get(DISCRIMINADOR), bool
        ):
            return nodo_catalogo
        return None

    def resolver_schema(nodo: Any, visto: tuple[str, ...]) -> dict[str, Any]:
        """Baja por ``$ref`` y por la rama no nula, como el walker del gate de copy."""
        if not isinstance(nodo, dict):
            return {}
        if "$ref" in nodo:
            nombre = str(nodo["$ref"]).rsplit("/", 1)[-1]
            if nombre in visto:
                return {}
            bajado = resolver_schema(defs_schema.get(nombre, {}), (*visto, nombre))
            return {**bajado, "__ref__": nombre}
        for rama in nodo.get("anyOf") or nodo.get("oneOf") or []:
            if isinstance(rama, dict) and rama.get("type") != "null":
                hijo = resolver_schema(rama, visto)
                if hijo.get("properties") or hijo.get("items") or hijo.get("type"):
                    heredado = {k: v for k, v in nodo.items() if k not in ("anyOf", "oneOf")}
                    return {**heredado, **hijo}
        return nodo

    def recorrer(nodo: Any, mapa: Any, ruta: str, visto: tuple[str, ...] = ()) -> None:
        nonlocal resueltos
        resuelto = resolver_schema(nodo, visto)
        if resuelto.get("ui_widget") == "hidden":
            return
        if propiedades := resuelto.get("properties"):
            hijos_mapa = hijos(nodo, resuelto, mapa)
            for nombre, hijo in propiedades.items():
                nodo_hijo = hijos_mapa.get(nombre) if isinstance(hijos_mapa, dict) else None
                recorrer(hijo, nodo_hijo, f"{ruta}.{nombre}", visto)
            return
        if items := resuelto.get("items"):
            # La lista misma cuenta como nodo visible (tiene título propio en pantalla).
            if isinstance(mapa, dict):
                resueltos += 1
            else:
                sin_resolver.append(ruta)
            # Su FILA resuelve por el `$def` del elemento, nunca por el nombre suelto. Una lista de
            # escalares no tiene fila con campos: su valor lo lleva el descriptor de la lista, así
            # que el nodo `[]` se resuelve con ese mismo descriptor.
            fila = defs_catalogo.get(_ref_de(items) or "")
            recorrer(items, fila if fila is not None else mapa, f"{ruta}[]", visto)
            return
        if isinstance(mapa, dict):
            resueltos += 1
        else:
            sin_resolver.append(ruta)

    for seccion in SECCIONES_ESPERADAS:
        if seccion not in disponibles:
            continue
        nodo = (schema.get("properties") or {}).get(seccion)
        if nodo is not None:
            recorrer(nodo, catalogo["sections"].get(seccion), seccion)

    assert sin_resolver == [], "\n".join(sin_resolver)
    if _formulario_completo():
        assert resueltos == HOJAS_DEL_FORMULARIO, (
            f"resueltos {resueltos} de {HOJAS_DEL_FORMULARIO} nodos visibles"
        )
    else:
        assert resueltos > 200


def test_el_gate_de_cobertura_no_resuelve_por_coincidencia_de_nombre() -> None:
    """Control negativo: sin la entrada de ``$defs`` de una fila, sus hojas NO pueden resolver.

    Ancla del defecto que tenía la primera versión de este gate: `name`, `col`, `op` y `value`
    existen en varios modelos, así que casar por el último tramo daba por cubierto lo que no lo
    estaba. Se comprueba con el mismo helper que usa el gate real.
    """
    catalogo = build_effective_defaults()
    columnas = catalogo["$defs"]["data__ColumnSpec"]
    assert "name" in columnas
    # El nombre suelto SÍ aparece en otros modelos: por eso el criterio laxo no servía.
    otros = [k for k, m in catalogo["$defs"].items() if k != "data__ColumnSpec" and "name" in m]
    assert otros, "sin homónimos, este control negativo no probaría nada"
    # El criterio bueno es el `$ref`, y ése es único.
    assert _ref_de({"$ref": "#/$defs/data__ColumnSpec"}) == "data__ColumnSpec"
    assert _ref_de({"anyOf": [{"$ref": "#/$defs/data__Rule"}, {"type": "null"}]}) == "data__Rule"
    assert _ref_de({"anyOf": [{"$ref": "#/$defs/A"}, {"$ref": "#/$defs/B"}]}) is None


# ---------------------------------------------------------------------------------------------
# Controles negativos: el gate se pone rojo cuando debe
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "dopar",
    [
        pytest.param(
            lambda c: c["$defs"]["data__ColumnSpec"].__setitem__(
                "nullable", {"has_default": True, "value": "mentira"}
            ),
            id="hoja-de-un-$def",
        ),
        pytest.param(
            lambda c: c["sections"]["report"]["sections"].__setitem__(
                "missing_policy", {"has_default": True, "value": "warning"}
            ),
            id="hoja-de-una-raiz-de-seccion",
        ),
        pytest.param(
            lambda c: c["sections"]["ml"].__setitem__(
                "hyperparameters", {"has_default": True, "value": None}
            ),
            id="el-validador-de-relleno",
        ),
        pytest.param(
            lambda c: c["$defs"]["data__ColumnSpec"].__setitem__("name", {"has_default": True}),
            id="obligatorio-declarado-con-default",
        ),
    ],
)
def test_control_negativo_la_paridad_se_pone_roja(dopar: Any) -> None:
    """Se dopa el catálogo y **se ejecuta el comparador de verdad**, que debe fallar.

    ⚠️ La primera versión de este control no probaba nada: dopaba una copia y luego aseveraba que
    el valor corrupto era distinto del correcto, sin invocar jamás el comparador. Un gate cuyo
    control negativo no ejecuta el gate es decoración. Ahora se llama a :func:`_comparar_paridad`
    con el artefacto dopado y se exige el ``AssertionError``.

    Los cuatro casos cubren las cuatro formas de mentir: una hoja de `$defs`, una hoja de una raíz
    de sección —las 224 que el barrido no miraba—, el campo cuyo valor lo fija un validador de
    modelo, y un obligatorio disfrazado de campo con default.
    """
    catalogo = build_effective_defaults()
    assert _comparar_paridad(catalogo) > 0, "el comparador debe recorrer algo"

    dopado = json.loads(json.dumps(catalogo))
    dopar(dopado)
    with pytest.raises(AssertionError):
        _comparar_paridad(dopado)


def test_control_negativo_una_seccion_de_menos_pone_rojo_la_cobertura() -> None:
    """Quitar una sección del catálogo deja hojas del formulario sin resolver."""
    catalogo = build_effective_defaults()
    dopado = json.loads(json.dumps(catalogo))
    del dopado["sections"]["report"]

    sin_resolver = 0
    for _ruta, path in _hojas_del_formulario():
        if path[0] != "report":
            continue
        nodo: Any = dopado["sections"]
        for tramo in path:
            if not isinstance(nodo, dict) or tramo not in nodo:
                nodo = None
                break
            nodo = nodo[tramo]
        if nodo is None:
            sin_resolver += 1
    assert sin_resolver > 0, "el control negativo no dopó nada"


# ---------------------------------------------------------------------------------------------
# Contrato con el payload y con los extras
# ---------------------------------------------------------------------------------------------


def test_el_payload_publica_el_mismo_catalogo() -> None:
    """``schema_payload()`` no reinterpreta nada: publica el catálogo tal cual."""
    assert schema_payload()["effective_defaults"] == build_effective_defaults()


def test_un_extra_ausente_deja_su_dominio_sin_defaults_fabricados() -> None:
    """D-FX-10: el catálogo declara exactamente los dominios disponibles, ni uno más.

    Un dominio cuyo extra no esté instalado queda opaco en ``json_schema`` **y** ausente del
    catálogo: las dos superficies dicen lo mismo. Fabricarle defaults sería prometer un formulario
    para una capacidad que esta instalación no puede ejecutar.
    """
    disponibles = set(cargar_configs_de_dominio())
    catalogo = build_effective_defaults()
    secciones_de_dominio = {
        nombre for nombre in catalogo["sections"] if nombre in set(NikodymConfig.model_fields)
    }
    # Todo dominio disponible está expandido (mapa de hijos, no descriptor).
    for nombre in disponibles:
        nodo = catalogo["sections"][nombre]
        assert isinstance(nodo, dict) and "has_default" not in nodo, nombre
        assert nodo, f"el dominio disponible {nombre} no puede publicar un mapa vacío"
    # Y ninguna clave de `$defs` pertenece a un dominio no disponible.
    for clave in catalogo["$defs"]:
        if "__" in clave:
            seccion = clave.split("__", 1)[0]
            assert seccion in disponibles, clave
    assert secciones_de_dominio
