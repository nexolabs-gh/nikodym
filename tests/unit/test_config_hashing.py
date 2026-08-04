"""Tests de config_hash (SDD-01 §5): determinismo, exclusión de INFRA_SECTIONS, sensibilidad."""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

from nikodym.core.config import INFRA_SECTIONS, NikodymConfig, ReproConfig, config_hash


def test_es_hex_sha256() -> None:
    """El hash es un string hexadecimal SHA-256 de 64 caracteres."""
    digest = config_hash(NikodymConfig())
    assert isinstance(digest, str)
    assert len(digest) == 64
    int(digest, 16)  # no levanta -> es hex válido


def test_determinista() -> None:
    """Dos configs idénticos producen el mismo hash (DoD F0 b)."""
    assert config_hash(NikodymConfig()) == config_hash(NikodymConfig())


def test_excluye_infra_sections() -> None:
    """Cambiar 'name' (en INFRA_SECTIONS) NO cambia el hash (DoD F0 b)."""
    assert config_hash(NikodymConfig(name="alfa")) == config_hash(NikodymConfig(name="beta"))


def test_cambia_con_campo_computacional() -> None:
    """Cambiar repro.seed (sección computacional) SÍ cambia el hash."""
    uno = config_hash(NikodymConfig(repro=ReproConfig(seed=1)))
    dos = config_hash(NikodymConfig(repro=ReproConfig(seed=2)))
    assert uno != dos


def test_infra_sections_contenido_exacto() -> None:
    """INFRA_SECTIONS contiene exactamente las cinco secciones de infraestructura."""
    assert set(INFRA_SECTIONS) == {"name", "governance", "audit", "tracking", "report"}


# --- D-HASH-1: la identidad no depende del orden de los imports -------------------------------

# Config con la trampa exacta que el defecto necesitaba: una sección de dominio que puede llegar
# OPACA y **campos con default omitidos** (`max_n_bins`, `min_bin_size`, `type`… se quedan en su
# default). Un preset escribe todos los campos explícitos y por eso no lo destapa; un YAML escrito
# a mano, sí. Es justo lo que la coacción materializa y el blob opaco no.
_CONFIG_CON_SECCION_DE_DOMINIO = {"binning": {"max_n_prebins": 15}}

# El estado de imports se captura ANTES de hashear: `config_hash` importa la capa como parte del
# arreglo (D-HASH-1), así que preguntarlo después diría siempre `True` y la precondición del test
# —que los dos subprocesos estén en lados distintos de la brecha— dejaría de verificar nada.
_CODIGO_HASH_EN_SUBPROCESO = """
import json, sys
if {importar}:
    import nikodym.binning  # puebla el hook _BINNING_CONFIG_CLS
from nikodym.core.config import NikodymConfig, config_hash
cfg = NikodymConfig.model_validate({payload})
antes = {{
    "opaca": isinstance(cfg.binning, dict),
    "capa_importada": "nikodym.binning" in sys.modules,
}}
print(json.dumps({{**antes, "hash": config_hash(cfg)}}))
"""


def _hash_en_subproceso(*, importar_capa: bool) -> dict[str, object]:
    """Calcula el ``config_hash`` en un intérprete FRESCO, con o sin la capa importada.

    Tiene que ser un subproceso: dentro de la suite las capas de dominio ya están importadas por
    otros tests, así que un montaje «natural» nunca vive en el lado opaco de la brecha y daría un
    falso verde. Es la misma trampa que dejó pasar el P0 del lineage (``edb3773``).
    """
    codigo = _CODIGO_HASH_EN_SUBPROCESO.format(
        importar=importar_capa,
        payload=json.dumps(_CONFIG_CON_SECCION_DE_DOMINIO),
    )
    salida = subprocess.run(
        [sys.executable, "-c", codigo], check=True, capture_output=True, text=True
    )
    resultado: dict[str, object] = json.loads(salida.stdout)
    return resultado


def test_el_hash_no_depende_de_que_el_proceso_haya_importado_la_capa() -> None:
    """D-HASH-1: el mismo config da el mismo ``config_hash`` con y sin la capa importada.

    Antes de la enmienda, una sección de dominio opaca se canonicalizaba **sin normalizar** —los
    defaults que el dict no traía no se materializaban—, así que la identidad de una corrida
    dependía del orden de los ``import`` del proceso. Con el ancla del lineage, del model card, del
    informe y de la idempotencia de MLflow colgando de ese digest.
    """
    sin_capa = _hash_en_subproceso(importar_capa=False)
    con_capa = _hash_en_subproceso(importar_capa=True)

    # Precondiciones: los dos subprocesos tienen que estar de lados distintos de la brecha, o el
    # test no prueba nada.
    assert sin_capa["opaca"] is True, "precondición: sin la capa, la sección debe llegar OPACA"
    assert con_capa["opaca"] is False, "precondición: con la capa, la sección debe coaccionarse"
    assert sin_capa["capa_importada"] is False
    assert con_capa["capa_importada"] is True

    assert sin_capa["hash"] == con_capa["hash"]


def test_el_hash_converge_al_del_config_coaccionado() -> None:
    """D-HASH-1: la identidad es la del config que SE EJECUTARÍA, no un tercer digest.

    Cerrar la brecha «haciendo que coincidan» no bastaría: podrían coincidir en un valor nuevo y
    romper toda identidad ya publicada. El hash resultante tiene que ser exactamente el del config
    coaccionado, que es el que el lineage congela desde ``edb3773``.

    El ``import`` explícito no es decorativo: sin él, este proceso podría no haber importado la capa
    todavía —depende del orden en que pytest recorra la suite— y el «esperado» sería el hash OPACO,
    con lo que el test pasaría incluso contra el código defectuoso. Se verificó que falla sin el
    arreglo.
    """
    import nikodym.binning  # noqa: F401 - importa la capa: puebla el hook y fuerza la coacción

    esperado = config_hash(NikodymConfig.model_validate(_CONFIG_CON_SECCION_DE_DOMINIO))
    assert _hash_en_subproceso(importar_capa=False)["hash"] == esperado


def test_una_seccion_de_dominio_no_instalable_no_rompe_el_hash() -> None:
    """D-HASH-3: un dominio que no importa deja su sección opaca y el hash responde igual.

    La garantía es «el hash no depende del ORDEN de los imports dentro de una instalación dada»,
    no igualdad entre instalaciones con distintos extras: un config que necesita un dominio no
    instalado no se puede ejecutar, así que su identidad no ancla ninguna corrida. Se simula
    bloqueando el import de la capa con un *meta path finder*.
    """
    codigo = f"""
import sys, importlib.abc

class Bloqueador(importlib.abc.MetaPathFinder):
    def find_spec(self, nombre, ruta=None, destino=None):
        if nombre == "nikodym.binning" or nombre.startswith("nikodym.binning."):
            raise ImportError("extra ausente (simulado)")
        return None

sys.meta_path.insert(0, Bloqueador())
from nikodym.core.config import NikodymConfig, config_hash
cfg = NikodymConfig.model_validate({json.dumps(_CONFIG_CON_SECCION_DE_DOMINIO)})
digest = config_hash(cfg)
assert isinstance(cfg.binning, dict), "la sección queda opaca"
assert len(digest) == 64, "el hash se calcula igual"
assert "nikodym.binning" not in sys.modules
"""
    subprocess.run([sys.executable, "-c", codigo], check=True)


def test_una_seccion_opaca_invalida_no_vuelve_fallable_el_hash() -> None:
    """D-HASH-8: ``config_hash`` sigue siendo total aunque la coacción falle.

    El blob opaco acepta un campo que el schema del dominio prohíbe (no conoce su schema). Al
    coaccionar para hashear, ese config levanta ``ValidationError`` — y propagarlo convertiría una
    función de identidad en una fallable, tumbando llamadores que hoy responden siempre (el 200
    incondicional de ``/api/validate``, el ensamblado del lineage). Se devuelve el hash del config
    sin coaccionar; el error lo reporta el validador, que es su trabajo.
    """
    codigo = """
import sys
from nikodym.core.config import NikodymConfig, config_hash
cfg = NikodymConfig.model_validate({"binning": {"campo_que_no_existe": 1}})
assert isinstance(cfg.binning, dict), "precondición: la sección llega opaca"
assert "nikodym.binning" not in sys.modules, "precondición: la capa no está importada"
digest = config_hash(cfg)   # no debe levantar
assert len(digest) == 64
"""
    subprocess.run([sys.executable, "-c", codigo], check=True)


@pytest.mark.parametrize(
    ("seccion", "payload", "excepcion"),
    [
        # Desciende de ``ConfigError``. El `raise` se escribió el 2026-08-04 (D-ABA-5): cerrar un
        # defecto en el validador de un dominio CREABA un escape nuevo en la identidad.
        ("binning", {"solver": "cp"}, "ConfigError"),
        # 🔴 NO desciende de ``ConfigError``, sólo de ``NikodymError``. Este caso es el que hace
        # falsable el gate: con ``except (ValidationError, ConfigError)`` —el arreglo insuficiente
        # que parece bastar— el de arriba pasa y ÉSTE se pone rojo. Son cuatro clases así, en
        # ``stress`` y ``forward``.
        (
            "stress",
            {"scenarios": [{"name": "", "shocks": [{"factor": "pib", "value": 1.0}]}]},
            "StressScenarioError",
        ),
    ],
)
def test_un_error_de_dominio_tampoco_vuelve_fallable_el_hash(
    seccion: str, payload: dict[str, object], excepcion: str
) -> None:
    """D-ANC-10: la coacción falla de DOS formas, y atrapar sólo una dejó el defecto vivo.

    Hermano de :func:`test_una_seccion_opaca_invalida_no_vuelve_fallable_el_hash`, que prueba la
    única rama que funcionaba: un campo desconocido, o sea ``extra_forbidden`` de pydantic, que
    **sí** es ``ValidationError``. La otra familia es un ``raise`` del propio validador de dominio,
    y pydantic sólo lo envuelve si hereda de ``ValueError`` — cosa que ``NikodymError`` no hace.
    Eran **123 `raise` en 18 de las 22 secciones de dominio**, 72 de ellos alcanzables desde el
    formulario, y bastaba un ``Select`` para que ``config_hash`` dejara de ser total.

    Se mide **totalidad**, que es otra propiedad que la coherencia: los tres tests que debían cazar
    esto comparan ``f(opaco) == f(tipado)`` y son estructuralmente incapaces de verlo, porque con
    una sección inválida el lado ``tipado`` revienta al construirse.
    """
    codigo = f"""
import sys
from nikodym.core.config import NikodymConfig, config_hash
cfg = NikodymConfig.model_validate({{{seccion!r}: {payload!r}}})
assert isinstance(cfg.{seccion}, dict), "precondición: la sección llega opaca"
assert "nikodym.{seccion}" not in sys.modules, "precondición: la capa no está importada"

# Control positivo: la coacción falla de verdad, y con la excepción que este caso dice medir.
# Sin esto el test pasaría aunque el payload fuese válido — daría verde sin ejercitar nada.
from nikodym.core.config.schema import cargar_configs_de_dominio
cargar_configs_de_dominio()
try:
    NikodymConfig.model_validate(cfg.model_dump(mode="json", by_alias=True))
except Exception as exc:
    assert type(exc).__name__ == {excepcion!r}, f"esperaba {excepcion}, no {{type(exc).__name__}}"
else:
    raise AssertionError("el payload NO dispara el validador: el caso no prueba nada")

digest = config_hash(cfg)   # no debe levantar
assert len(digest) == 64
"""
    subprocess.run([sys.executable, "-c", codigo], check=True)
