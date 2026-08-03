"""Gate de cobertura del vocabulario `column_role` (D-PRE-4).

El preflight sólo ve los campos que declaran su rol. Un campo nuevo que nombre una columna y no lo
declare no rompe nada visible: simplemente **deja de comprobarse**, y el preflight sigue diciendo
«compatible» sobre un config que fallará al correr. Ése es el modo de fallo que este gate impide.

**El alcance se DERIVA, no se escribe al lado.** Hasta el 2026-07-29 este gate recorría
:data:`SECCIONES_EN_ALCANCE`, una tupla de siete modelos, y por eso no cazaba el caso que le da
sentido: inyectar ``column_role: "input"`` en `markov/config.py` lo dejaba **verde** mientras el
motor emitía `markov.input.id_col` y el formulario no tenía dónde saltar. Ahora las dos preguntas
que importan se miden contra la realidad:

1. *¿Qué secciones puede señalar el preflight?* → el footprint real de `column_role` sobre el
   registro de dominio, filtrado a los roles que el motor **inspecciona** (`input`/`index`; sobre
   `derived`/`not_a_column` hace `continue`). Hoy son **siete**: las tres del camino F1 (`data`,
   `binning`, `stability`), las tres de provisiones y `survival`.
2. *¿Qué multiselect se quedaría sin opciones?* → los de secciones que el formulario OFRECE cuyos
   items no traen `enum` y no declaran rol. Es la clase de defecto que se vio en cámara con HMEQ:
   «Sin opciones.» con doce variables dentro del config.

La tupla se conserva para el criterio por sufijo, que exige clasificar todo campo `*_col*` de las
secciones en alcance. **Ese alcance ya no es «el camino F1»**: desde el 2026-08-03 se DERIVA del
catálogo de trabajos —cubre lo que algún trabajo *disponible* declara—, que es el criterio con que
Cami lo fijó para que no se desincronice cuando un trabajo se desbloquee.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from pydantic import BaseModel, Field

from nikodym.binning.config import BinningConfig
from nikodym.calibration.config import CalibrationConfig
from nikodym.core.config.schema import cargar_configs_de_dominio
from nikodym.core.dataset_check import (
    CLAVE_ROL,
    ROL_ENTRADA,
    ROL_INDICE,
    ROLES,
    _rol,
)
from nikodym.data.config import DataConfig
from nikodym.performance.config import PerformanceConfig
from nikodym.scorecard.config import ScorecardConfig
from nikodym.selection.config import SelectionConfig
from nikodym.stability.config import StabilityConfig
from nikodym.survival.config import SurvivalConfig

#: Secciones cuyo campo `*_col*` está OBLIGADO a declarar rol, por el criterio de sufijo.
#:
#: Las siete del camino F1, más `survival` desde el 2026-08-03: sus dos columnas de entrada son
#: decisiones obligatorias del catálogo y dos trabajos disponibles la declaran, así que entra al
#: alcance derivado igual que las provisiones. Ampliar el alcance es sumar aquí, no reescribir
#: el gate.
#:
#: ⚠️ Las cuatro secciones de `provisioning` NO están, y es deliberado: entrarían arrastrando los 14
#: campos cuyo consumo es **condicional**, que es justo lo que un rol estático no puede expresar.
#: Ahora existe `columnas_inactivas` (D-RAM-1) y por ahí se cierran, uno a uno y midiendo su rama;
#: meterlas aquí antes de eso obligaría a declarar en bloque lo que todavía no está medido.
SECCIONES_EN_ALCANCE = (
    DataConfig,
    BinningConfig,
    SelectionConfig,
    ScorecardConfig,
    CalibrationConfig,
    PerformanceConfig,
    StabilityConfig,
    SurvivalConfig,
)

#: Roles que el preflight INSPECCIONA. `derived` y `not_a_column` los salta
#: (`dataset_check.py` hace `continue`), así que declararlos no amplía su alcance ni puede
#: producir un aviso: sólo estos dos definen la superficie desde la que el usuario recibe una ruta.
ROLES_INSPECCIONABLES = frozenset({ROL_ENTRADA, ROL_INDICE})

#: Multiselects de texto libre que HOY no declaran rol, con la razón de por qué no.
#:
#: 🔴 **Está vacío, y llegar a vacío era el objetivo.** Tuvo dos entradas y las dos se retiraron
#: cumpliendo lo que su propia razón escrita anunciaba:
#:
#: * `"LgdConfig.covariate_cols"` era **letra muerta** —esa clase no existe, la real es
#:   `IfrsLgdConfig`—, así que la clave nunca pudo casar con nada; su razón («ampliaría el preflight
#:   a provisioning_ifrs9») describe justo lo que el 2026-08-03 se hizo a propósito.
#: * `"SurvivalInputConfig.covariate_cols"` decía «el día que se amplíe el preflight a survival, se
#:   borra esta línea». Ese día fue el 2026-08-03: la ampliación es decisión de Cami y el alcance
#:   ahora se **deriva del catálogo** —las secciones que algún trabajo *disponible* declara—, y dos
#:   trabajos disponibles declaran `survival`.
#:
#: Se conserva la estructura, no por simetría, sino porque el gate de abajo la necesita para el día
#: que aparezca un multiselect nuevo cuya declaración haya que posponer con su razón a la vista.
EXENTOS_MULTISELECT: dict[str, str] = {}

#: Catálogo de secciones navegables del formulario (front). Vive UNA vez, en `lib/schema.ts`.
_SCHEMA_TS = Path(__file__).resolve().parents[2] / "web" / "src" / "lib" / "schema.ts"

#: Sufijos que delatan un campo que nombra columnas. `name`/`col` sueltos (``ColumnSpec.name``,
#: ``Predicate.col``) no caben en un patrón por sufijo sin arrastrar falsos positivos, así que van
#: marcados igual pero este gate no los exige: cubre el patrón mayoritario, y lo dice.
SUFIJOS = ("_col", "_column", "_columns", "_cols")


def _modelos_alcanzables(raiz: type[BaseModel]) -> set[type[BaseModel]]:
    """Todos los modelos Pydantic alcanzables desde ``raiz``, incluida ella."""
    vistos: set[type[BaseModel]] = set()
    pendientes = [raiz]
    while pendientes:
        modelo = pendientes.pop()
        if modelo in vistos:
            continue
        vistos.add(modelo)
        for info in modelo.model_fields.values():
            for arg in (info.annotation, *getattr(info.annotation, "__args__", ())):
                if isinstance(arg, type) and issubclass(arg, BaseModel):
                    pendientes.append(arg)
                for anidado in getattr(arg, "__args__", ()):
                    if isinstance(anidado, type) and issubclass(anidado, BaseModel):
                        pendientes.append(anidado)
    return vistos


def _campos_de_columna() -> list[tuple[type[BaseModel], str]]:
    """Campos en alcance cuyo nombre calza con :data:`SUFIJOS`."""
    encontrados: list[tuple[type[BaseModel], str]] = []
    for seccion in SECCIONES_EN_ALCANCE:
        for modelo in _modelos_alcanzables(seccion):
            for nombre in modelo.model_fields:
                if nombre.endswith(SUFIJOS):
                    encontrados.append((modelo, nombre))
    return sorted(set(encontrados), key=lambda par: (par[0].__name__, par[1]))


def _secciones_navegables() -> set[str]:
    """Claves de `CONFIG_SECTIONS` (`web/src/lib/schema.ts`), leídas del propio catálogo.

    Se lee el archivo en vez de duplicar la lista aquí, por la misma razón que
    ``test_public_copy.py`` lee ``markers.ts``: una copia a mano se desincroniza en silencio, que
    es justo el modo de fallo que el gate persigue.
    """
    texto = _SCHEMA_TS.read_text(encoding="utf-8")
    _, _, resto = texto.partition("export const CONFIG_SECTIONS")
    bloque, _, _ = resto.partition("\n]")
    return set(re.findall(r'key:\s*"([a-z_0-9]+)"', bloque))


def _tiene_enum_en_items(modelo: type[BaseModel], nombre: str) -> bool:
    """¿Los elementos de esta lista vienen enumerados en el schema (lista CERRADA)?

    Se pregunta al JSON Schema que publica el modelo, que es exactamente lo que recibe el
    formulario, en vez de reinterpretar la anotación de tipo. Recorre las ramas de una unión
    porque los campos que importan viajan así: ``tuple[str, ...] | Literal["*"]``.
    """
    schema = modelo.model_json_schema(ref_template="#/$defs/{model}")
    defs = schema.get("$defs", {})

    def resolver(nodo: dict[str, object]) -> dict[str, object]:
        ref = nodo.get("$ref")
        while isinstance(ref, str):
            nodo = defs.get(ref.rsplit("/", 1)[-1], {})
            ref = nodo.get("$ref")
        return nodo

    campo = schema.get("properties", {}).get(_alias_de(modelo, nombre), {})
    ramas = campo.get("anyOf") or campo.get("oneOf") or [campo]
    for rama in ramas:
        resuelta = resolver(rama)
        if resuelta.get("type") != "array":
            continue
        items = resolver(resuelta.get("items") or {})
        if items.get("enum") or items.get("const") is not None:
            return True
    return False


def _alias_de(modelo: type[BaseModel], nombre: str) -> str:
    """Nombre con que el campo viaja al JSON Schema (alias si lo tiene)."""
    info = modelo.model_fields.get(nombre)
    return getattr(info, "alias", None) or nombre


def _secciones_con_rol_inspeccionable() -> dict[str, list[str]]:
    """Secciones del config con al menos un campo que el preflight PUEDE señalar.

    Se deriva del **footprint real** de `column_role` sobre el registro de dominio, no de una
    lista escrita al lado. Es la diferencia que importa: sólo `input` e `index` producen
    desajustes (`dataset_check.py` hace `continue` sobre `derived`/`not_a_column`), así que esta
    es exactamente la superficie desde la que un usuario puede recibir un aviso con una ruta.
    """
    encontradas: dict[str, list[str]] = {}
    for clave, seccion in sorted(cargar_configs_de_dominio().items()):
        campos = sorted(
            f"{modelo.__name__}.{nombre}"
            for modelo in _modelos_alcanzables(seccion)
            for nombre in modelo.model_fields
            if _rol(modelo, nombre) in ROLES_INSPECCIONABLES
        )
        if campos:
            encontradas[clave] = campos
    return encontradas


def test_toda_seccion_que_el_preflight_puede_senalar_es_navegable_en_el_formulario() -> None:
    """Un desajuste cuya sección no está en el formulario es un diagnóstico inaccionable.

    El preflight devuelve la ruta del campo **para que el formulario pueda enfocarlo** (D-PRE-8).
    Si esa sección no está en `CONFIG_SECTIONS`, el usuario recibe un aviso exacto sobre un campo
    que la interfaz no ofrece: sólo le queda editar el YAML a mano. Es la definición de feature a
    medias del repo, y contradice el requisito 1 de la visión (paridad UI ↔ código).

    Ocurrió de verdad: `stability` era sección del config —y de las siete del camino F1— pero no
    estaba en el catálogo del sidebar, así que `stability.temporal_column` se reportaba sin
    destino. Se detectó conectando el preflight a la SPA, no antes.

    ⚠️ **Este gate mide el footprint REAL, no una lista de secciones escrita a mano.** La versión
    anterior recorría `SECCIONES_EN_ALCANCE`, una tupla de siete modelos, y por eso no cazaba el
    caso que le da sentido: inyectar `column_role: "input"` en `markov/config.py` la dejaba
    **verde** mientras el motor emitía `markov.input.id_col` y el front no tenía dónde saltar.
    Ampliar el preflight a una sección nueva pasa ahora por aquí sí o sí: declarar el rol es lo
    único que hace falta para que el motor la señale, así que es lo único que este gate mira.
    """
    navegables = _secciones_navegables()
    assert navegables, (
        f"No se pudo leer `CONFIG_SECTIONS` de {_SCHEMA_TS.name}: si el catálogo cambió de forma, "
        "este gate quedaría verde sin comprobar nada."
    )

    con_rol = _secciones_con_rol_inspeccionable()
    assert con_rol, (
        "El recorrido no encontró ni una sección con `column_role` inspeccionable: si se rompió, "
        "este gate no comprueba nada y queda verde."
    )

    ausentes = {clave: campos for clave, campos in con_rol.items() if clave not in navegables}

    assert not ausentes, (
        "Secciones que el preflight puede señalar pero el formulario no ofrece: "
        f"{ {k: v for k, v in ausentes.items()} }. "
        "El usuario recibiría un desajuste con su ruta exacta y ningún campo donde corregirlo. "
        f"O agregas la sección a `CONFIG_SECTIONS` en {_SCHEMA_TS.name} (y su icono en "
        "`App.tsx`), o el campo no debe declarar un rol inspeccionable."
    )


def test_el_footprint_inspeccionable_es_el_que_la_medicion_conto() -> None:
    """Ancla contra un recorrido que devuelva de menos y deje el gate anterior vacío.

    Las tres secciones salen de la medición del 2026-07-29 y se escriben a mano a propósito:
    derivarlas del propio recorrido haría el test tautológico —el defecto que P5 le imputaba al
    gate anterior—. Si mañana el preflight amplía su alcance, esta lista cambia **a conciencia**.
    """
    assert set(_secciones_con_rol_inspeccionable()) == {
        "data",
        "binning",
        "stability",
        # 🔴 Ampliación DELIBERADA (2026-08-03, decisión de Cami): el preflight sale del camino F1
        # hacia las provisiones. La consecuencia que la motivó estaba medida y era grave por sí
        # sola: un config de provisiones que apunta a columnas inexistentes salía `compatible=True`,
        # sin un solo aviso sobre ninguna de sus columnas.
        #
        # ⚠️ `provisioning` (el orquestador) NO aparece, y es correcto: sus seis campos son
        # `derived` o `not_a_column` —sus columnas salen del `detail` que producen los motores, no
        # del archivo del usuario—, y el preflight los salta con `continue`. Que la sección tenga
        # roles declarados no la mete en esta lista; sólo la meten `input` e `index`.
        "provisioning_cmf",
        "provisioning_internal",
        "provisioning_ifrs9",
        # Segunda mitad de la misma ampliación (2026-08-03): el alcance se DERIVA del catálogo
        # —cubre lo que algún trabajo *disponible* declara—, y `survival` la declaran dos:
        # «PD lifetime» y «Provisiones IFRS 9». Sus dos columnas son además decisiones obligatorias
        # del catálogo, o sea que la interfaz ya le pedía al usuario elegirlas de su archivo
        # mientras nadie las comprobaba contra él.
        #
        # ⚠️ `markov`, `forward` y `stress` siguen fuera, y por el mismo criterio derivado: ningún
        # trabajo disponible las usa. No es una lista corta por olvido.
        "survival",
    }


def test_todo_multiselect_de_texto_libre_declara_su_rol() -> None:
    """Un `multiselect` sobre texto sin `enum` y sin rol es un control SIN OPCIONES.

    Es el defecto que se vio en cámara con HMEQ: las tres listas de binning pintaban
    «Sin opciones.» con doce variables dentro del config. La causa no era el widget sino el
    origen de sus opciones — un `enum` no puede enumerar nombres de columna, que dependen del
    archivo del usuario—, y el único dato que dice de dónde sacarlas es `column_role`.

    Este gate cubre lo que el criterio por sufijo NO ve: `force_include`/`force_exclude` no
    terminan en `_col*` y son listas de variables igual. Detectar por widget y no por nombre es
    lo que cierra la clase.

    **Alcance: las secciones que el formulario OFRECE**, no todo el registro de dominio. Un
    multiselect de `forward` o `markov` no pinta un control vacío por la razón trivial de que su
    sección no se pinta; exigirle rol sería ruido. Y el alcance se amplía solo: el día que una
    sección entre a `CONFIG_SECTIONS`, sus multiselects entran aquí sin tocar este archivo — que
    es justo lo que le faltaba a la versión que medía una tupla escrita a mano.
    """
    navegables = _secciones_navegables()
    registro = cargar_configs_de_dominio()
    en_el_formulario = [modelo for clave, modelo in registro.items() if clave in navegables]
    assert en_el_formulario, (
        "Ninguna sección del registro calza con `CONFIG_SECTIONS`: el gate quedaría vacío."
    )

    sin_rol: list[str] = []
    for seccion in en_el_formulario:
        for modelo in _modelos_alcanzables(seccion):
            for nombre, info in modelo.model_fields.items():
                extra = info.json_schema_extra
                if not isinstance(extra, dict) or extra.get("ui_widget") != "multiselect":
                    continue
                # Con `enum` la lista YA es cerrada: sus opciones salen del schema y el rol no
                # aporta nada (`ReportConfig.formats`, `StabilityConfig.comparisons`…). El
                # problema es exactamente el otro caso.
                if _tiene_enum_en_items(modelo, nombre):
                    continue
                if _rol(modelo, nombre) is not None:
                    continue
                clave = f"{modelo.__name__}.{nombre}"
                if clave in EXENTOS_MULTISELECT:
                    continue
                sin_rol.append(clave)

    assert not sin_rol, (
        f"Multiselects sin `column_role`: {sorted(sin_rol)}. El formulario no sabe de dónde sacar "
        "sus opciones y pinta un control vacío. Declara 'input' (columnas del dataset), "
        "'derived' (las produce un paso anterior) o añádelo a EXENTOS_MULTISELECT con su razón."
    )


def test_todo_campo_de_columna_del_camino_f1_declara_su_rol() -> None:
    """Un campo `*_col*` sin `column_role` deja de comprobarse en silencio."""
    sin_rol = [
        f"{modelo.__name__}.{nombre}"
        for modelo, nombre in _campos_de_columna()
        if _rol(modelo, nombre) is None
    ]

    assert not sin_rol, (
        "Campos que nombran columnas sin `column_role` declarado: "
        f"{sin_rol}. Clasifícalos como 'input' (la trae el usuario), 'derived' (la produce "
        "el pipeline) o 'not_a_column' (el nombre engaña: `keep_structural_columns` es bool)."
    )


def test_ningun_rol_declarado_esta_fuera_del_vocabulario() -> None:
    """Un valor con typo (`"inputs"`) degradaría a «no clasificado» sin avisar."""
    invalidos = [
        f"{modelo.__name__}.{nombre}={_rol(modelo, nombre)!r}"
        for modelo, nombre in _campos_de_columna()
        if _rol(modelo, nombre) not in ROLES
    ]

    assert not invalidos, f"roles fuera de {sorted(ROLES)}: {invalidos}"


def test_el_gate_falla_ante_un_campo_sin_clasificar() -> None:
    """El gate se prueba INYECTANDO: uno que declara barrer una clase debe demostrarlo.

    Sin esto, `test_todo_campo_de_columna_del_camino_f1_declara_su_rol` podría estar verde por no
    encontrar nada —un recorrido roto da cero campos y cero incumplimientos— y nadie lo notaría.
    """

    class SeccionConCampoNuevo(BaseModel):
        """Modelo de laboratorio: un campo de columna que nadie clasificó."""

        cliente_col: str = Field(default="cliente", title="Columna cliente")

    assert _rol(SeccionConCampoNuevo, "cliente_col") is None

    campos = [
        (modelo, nombre)
        for modelo in _modelos_alcanzables(SeccionConCampoNuevo)
        for nombre in modelo.model_fields
        if nombre.endswith(SUFIJOS)
    ]
    assert campos == [(SeccionConCampoNuevo, "cliente_col")]


def test_el_recorrido_encuentra_los_campos_que_la_medicion_conto() -> None:
    """Ancla contra un recorrido que se rompa y devuelva de menos.

    El número sale de la medición del 2026-07-28 (26 campos `*_col*` en el camino F1) y se escribe
    a mano a propósito: derivarlo del propio recorrido haría el test tautológico.
    """
    nombres = {f"{modelo.__name__}.{nombre}" for modelo, nombre in _campos_de_columna()}

    for esperado in (
        "SchemaConfig.index_col",
        "CohortSplitConfig.cohort_col",
        "TargetConfig.target_col",
        "BinningConfig.feature_columns",
        "BinningConfig.categorical_columns",
        "StabilityConfig.temporal_column",
        "PerformanceConfig.pd_column",
        "CalibrationConfig.pd_raw_column",
    ):
        assert esperado in nombres, f"el recorrido perdió {esperado}"

    assert len(nombres) >= 26


@pytest.mark.parametrize(
    ("modelo", "campo", "rol_esperado"),
    [
        (BinningConfig, "keep_structural_columns", "not_a_column"),
        (SelectionConfig, "keep_structural_columns", "not_a_column"),
        (SelectionConfig, "feature_columns", "derived"),
        (StabilityConfig, "temporal_column", "input"),
        (StabilityConfig, "partition_column", "derived"),
    ],
)
def test_las_clasificaciones_que_el_nombre_del_campo_haria_fallar(
    modelo: type[BaseModel], campo: str, rol_esperado: str
) -> None:
    """Los cinco casos donde clasificar por el nombre da la respuesta equivocada.

    `keep_structural_columns` es un `bool`; `selection.feature_columns` refiere las variables que
    publica *binning*, no columnas del dataset; y en `stability` conviven una de entrada
    (`temporal_column`) y una derivada (`partition_column`) con el mismo aspecto. Se anclan a mano
    porque son exactamente los que una heurística por sufijo rompería.
    """
    assert _rol(modelo, campo) == rol_esperado
    assert modelo.model_fields[campo].json_schema_extra[CLAVE_ROL] == rol_esperado  # type: ignore[index]
