"""Gate de ejecución real del trabajo «Scorecard de comportamiento (PD)» (D-SC-6).

🔴 **`test_jobs_ejecutables` mide el DAG, no la corrida**, y lo declara: `check_pipeline` resuelve
los pasos sin leer una fila. Es exactamente la mitad que no basta aquí. El default del motor
enciende el contraste de PD por grado, que exige una columna de grado de rating; el DAG no lo mira
—`_requires_for` de `validation` no cambia con ese flag— así que un catálogo sin el override
pasaría aquel gate y **rompería la corrida** al penúltimo paso, con todo el cómputo pagado.

Este es el gate «cada trabajo disponible llega a `done`» que D-JOB §6 dejó pendiente, acotado a
este trabajo porque es el que la capa 2 pone en pantalla. Corre el esqueleto que la interfaz siembra
—no un preset— sobre el dataset de la demo, con las dos decisiones obligatorias contestadas como las
contestaría quien mira ese archivo, y exige que el payload traiga la validación formal entera.

⚠️ Es lento a propósito (el pipeline F1 completo). La alternativa —comprobar sólo el config— es lo
que ya hace el gate del DAG, y es justo lo que no cierra esta clase de defecto.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("fastapi", reason="el catálogo de trabajos vive en la capa ui")
pytest.importorskip("optbinning", reason="el pipeline del scorecard exige nikodym[scoring]")

from test_jobs_ejecutables import _esqueleto

from nikodym.core.config.effective_defaults import build_effective_defaults
from nikodym.ui.jobs import list_jobs

#: El dataset de la demo, el mismo con el que se recorre el trabajo en cámara.
DATASET = "consumo_comportamiento"

#: Las dos decisiones obligatorias, contestadas como las contestaría quien mira ESE archivo.
#:
#: No salen de un preset: `bad_flag` es la columna que trae la marca ya calculada —la forma de
#: respuesta «Ya viene marcada en una columna de mi archivo»— y `cohorte` es la única con la que se
#: puede separar fuera de tiempo. Son las respuestas, no la configuración: todo lo demás del config
#: lo pone el esqueleto del trabajo.
_DECISIONES: dict[str, dict[str, Any]] = {
    "data": {
        "target": {
            "bad_rule": {"all_of": [{"col": "bad_flag", "op": "==", "value": 1}], "any_of": []}
        },
        "partition": {
            "strategy": {
                "type": "cohort",
                "cohort_col": "cohorte",
                "oot_cohorts": ["2024Q2"],
                "holdout_fraction": 0.2,
            }
        },
    },
}

#: Caché de la corrida buena: cuesta el pipeline F1 entero y tres tests la interrogan.
#:
#: ⚠️ No es una fixture de módulo, y la razón está medida: el `PYTHONHASHSEED` de la suite lo fija
#: una fixture **autouse de función** (`tests/conftest.py`), así que una fixture de módulo corre
#: ANTES y la corrida muere con el aviso de `SeedManager` convertido en error.
_CORRIDA: dict[str, Any] = {}


def _config_del_trabajo(*, con_override: bool = True) -> dict[str, Any]:
    """El config que la pantalla siembra al entrar por este trabajo, con las decisiones puestas."""
    job = copy.deepcopy(
        next(j for j in list_jobs(incluir_referencia=True) if j["id"] == "scorecard_pd")
    )
    if not con_override:
        job["overrides"] = [
            o for o in job["overrides"] if o[0] != "validation.calibration.binomial_by_grade"
        ]
    config = _esqueleto(job, build_effective_defaults())
    for seccion, bloques in _DECISIONES.items():
        for clave, valor in bloques.items():
            config[seccion].setdefault(clave, {}).update(copy.deepcopy(valor))
    return config


def _corre(config: dict[str, Any], workdir: Path) -> dict[str, Any]:
    from nikodym.ui import routes

    return routes.run_pipeline(config, DATASET, workdir=workdir)


@pytest.fixture
def corrida(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """La corrida real del esqueleto, calculada una vez para todo el módulo."""
    if not _CORRIDA:
        workdir = tmp_path_factory.mktemp("workdir-scorecard")
        _CORRIDA.update(resultado=_corre(_config_del_trabajo(), workdir), workdir=workdir)
    return _CORRIDA


def _resultados(corrida: dict[str, Any]) -> dict[str, Any]:
    from nikodym.ui import runs

    return runs.load_results(corrida["resultado"]["run_id"], workdir=corrida["workdir"])


def test_el_esqueleto_del_trabajo_corre_entero(corrida: dict[str, Any]) -> None:
    """Quien entra por el trabajo y contesta lo que se le pide llega a `done`."""
    resultado = corrida["resultado"]
    assert resultado["status"] == "done", (
        f"la corrida del esqueleto no terminó: {_resultados(corrida).get('error')}"
    )


def test_la_corrida_publica_la_validacion_formal(corrida: dict[str, Any]) -> None:
    """El payload trae la card y las cuatro tablas: es lo que el panel de Resultados lee."""
    validation = _resultados(corrida)["validation"]

    assert validation is not None, (
        "`validation` llegó nula en una corrida que la incluye: el serializer no publicó su card"
    )
    assert validation["overall_status"] in {"pass", "warn", "fail"}
    assert validation["families_run"] == ["discrimination", "calibration", "stability"]
    for clave in ("discrimination", "calibration", "stability", "backtesting"):
        assert clave in validation, f"falta la tabla «{clave}» en el payload de validación"
    assert validation["discrimination"], "la discriminación no publicó ninguna fila"
    assert validation["calibration"], "la calibración no publicó ninguna fila"
    # El backtesting NO corre en este trabajo (su familia no está activa): tabla vacía, no ausente.
    assert validation["backtesting"] == []


def test_sin_grados_en_el_archivo_el_contraste_por_grado_no_corre(corrida: dict[str, Any]) -> None:
    """El override no es cosmético: la tabla de calibración no trae ni una fila por grado.

    Es la cara positiva del control negativo de abajo. `consumo_comportamiento` no tiene columna de
    grado de rating, así que las únicas filas legítimas son las de Hosmer-Lemeshow y Brier.
    """
    tests = {fila["test"] for fila in _resultados(corrida)["validation"]["calibration"]}
    assert tests <= {"hosmer_lemeshow", "brier"}, f"apareció un test por grado: {tests}"


@pytest.mark.slow
def test_sin_el_override_del_catalogo_la_corrida_se_rompe(tmp_path: Path) -> None:
    """🔴 El control que da sentido a todo lo anterior, y el que el gate del DAG no puede dar.

    Con el override quitado el config es el default del motor: el contraste por grado encendido
    sobre un archivo que no tiene grados. `check_pipeline` lo sigue declarando ejecutable —el DAG
    no cambia—, y la corrida real muere en `validation` pidiendo la columna. Si este test pasara a
    verde con la corrida terminando bien, el override sobraría; si el de arriba se rompiera, el
    override sería lo que falta.
    """
    from nikodym.ui import runs

    resultado = _corre(_config_del_trabajo(con_override=False), tmp_path)

    assert resultado["status"] == "failed", (
        "sin el override la corrida terminó bien: o el motor dejó de exigir la columna de grado, "
        "o el esqueleto ya no siembra el default. Mídelo antes de retirar el override."
    )
    error = str(runs.load_results(resultado["run_id"], workdir=tmp_path).get("error") or "")
    assert "grade" in error, f"falló por otra razón que la columna de grado: {error!r}"
