"""El chequeo en vivo de `deploy.yml` tiene que buscar las corridas que la demo publica HOY.

🔴 Medido en la release 1.13.0 (2026-09-12): `deploy.yml` verifica el bundle servido buscando por
literal los `run_id` de las dos corridas de la demo, y esos literales eran los de la captura
anterior. La recaptura (`55f775b`) cambió los `run_id` y ningún gate lo acusó: el Deploy que
construyó los fixtures nuevos pasó sólo porque leyó el bundle viejo todavía servido, y el Deploy
siguiente falló con «la demo no publica la corrida 4eb39425…» sobre un sitio que estaba bien. Los
literales viven en el workflow porque los fixtures F3 salieron del árbol (D-JUR-9.7) y la mitad
negativa necesita sus identidades; la mitad positiva, en cambio, puede y debe medirse contra los
fixtures versionados: este test la ata a ellos, para que la próxima recaptura mueva los dos lados
en el mismo commit.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Final

_RAIZ: Final = Path(__file__).resolve().parents[2]
_DEPLOY: Final = _RAIZ / ".github" / "workflows" / "deploy.yml"
_FIXTURES: Final = _RAIZ / "web" / "src" / "fixtures" / "demo"
#: Los `results-*.json` de las corridas que la demo publica (una por familia del catálogo).
_RESULTADOS_PUBLICADOS: Final = ("results-f1.json", "results-ifrs9.json")

_BLOQUE_PUBLICADO: Final = re.compile(r"for publicado in ((?:[0-9a-f]{32}\s*\\?\s*)+); do", re.S)
_BLOQUE_RETIRADO: Final = re.compile(r"for retirado in ((?:[0-9a-f]{32,64}\s*\\?\s*)+); do", re.S)


def _ids(bloque: str) -> set[str]:
    return set(re.findall(r"[0-9a-f]{32,64}", bloque))


def _run_ids_de_los_fixtures() -> dict[str, str]:
    return {
        nombre: json.loads((_FIXTURES / nombre).read_text(encoding="utf-8"))["run_id"]
        for nombre in _RESULTADOS_PUBLICADOS
    }


def test_el_deploy_busca_en_vivo_exactamente_las_corridas_de_los_fixtures() -> None:
    texto = _DEPLOY.read_text(encoding="utf-8")
    bloque = _BLOQUE_PUBLICADO.search(texto)
    assert bloque is not None, "deploy.yml ya no tiene el bucle `for publicado in …` del chequeo"
    publicados = _ids(bloque.group(1))
    esperados = _run_ids_de_los_fixtures()
    assert publicados == set(esperados.values()), (
        "los `run_id` que `deploy.yml` busca en el bundle servido no son los de los fixtures "
        f"versionados: workflow={sorted(publicados)} fixtures={esperados}. Tras una recaptura, "
        "los dos lados se mueven en el mismo commit."
    )


def test_las_corridas_retiradas_no_son_ninguna_de_las_publicadas() -> None:
    """La mitad negativa del chequeo no puede prohibir una corrida que la demo sí publica."""
    texto = _DEPLOY.read_text(encoding="utf-8")
    retirado = _BLOQUE_RETIRADO.search(texto)
    assert retirado is not None, "deploy.yml ya no tiene el bucle `for retirado in …`"
    prohibidas = _ids(retirado.group(1))
    assert prohibidas, "la mitad negativa quedó vacía"
    assert prohibidas.isdisjoint(_run_ids_de_los_fixtures().values())
