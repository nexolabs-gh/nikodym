"""Deriva —y VERIFICA corriendo— el delta de provisiones del preset ``f3-provisiones-consumo``.

``nikodym.ui`` es *domain-agnostic* (SDD-23 §3.3): un test AST veta importar módulos de dominio
desde ``ui/``. Por eso el preset se sirve como **dict literal JSON-able**, no se construye con
``ProvisioningConfig(...)`` dentro de ``ui/``. Este script vive **fuera** de ``ui/``, construye las
secciones de provisiones con los objetos Pydantic de dominio, las vuelca con
``model_dump(mode="json", by_alias=True)`` y las imprime listas para pegar en ``ui/presets.py``.

Y hace lo que ningún test de ``status == done`` hace: **corre la cadena entera y comprueba que el
número tiene sentido de negocio**. La trampa (documentada en el HANDOFF y en la memoria del
proyecto): si el preset hereda la calibración del F1 (``target_pd=0.20``), sobre esta cartera la PD
se infla 3x, el método interno supera al estándar, la regla del máximo deja de morder y el producto
se queda sin titular. Con ``anchor_source='development_observed'`` el estándar es el que muerde
(binding=cmf), que es lo que la norma chilena reporta. El ``assert`` de abajo es esa guardia,
ejecutable.

Uso::

    uv run --no-sync python scripts/derive_provisiones_preset.py
"""

from __future__ import annotations

import pprint
import tempfile
from copy import deepcopy
from pathlib import Path

import nikodym
from nikodym.core.config import NikodymConfig
from nikodym.provisioning.cmf.config import CmfProvisioningConfig
from nikodym.provisioning.config import ProvisioningConfig
from nikodym.provisioning.internal.config import InternalProvisioningConfig
from nikodym.ui import datasets
from nikodym.ui.presets import _STANDARD_CONFIG

DATASET_ID = "provisiones_consumo"

# --- Override de calibración (el resto del F1 se hereda tal cual por composición). ---
# development_observed estima la PD ancla como el promedio observado en Desarrollo y exige target_pd
# nulo; heredar el business_input/target_pd=0.20 del F1 invierte el resultado (ver docstring).
# target_pd va explícito en None (no se omite): es la forma canónica y hace el config_hash estable
# entre entornos (con/sin la capa de dominio importada). Ver la nota en ui/presets.py.
CALIBRATION_OVERRIDE = {"anchor_source": "development_observed", "target_pd": None}

# --- Secciones de provisiones, derivadas de los objetos Pydantic de dominio. ---
PROVISIONING_SECTIONS = {
    "provisioning_cmf": CmfProvisioningConfig().model_dump(mode="json", by_alias=True),
    "provisioning_internal": InternalProvisioningConfig().model_dump(mode="json", by_alias=True),
    "provisioning": ProvisioningConfig(
        source_a="provisioning_cmf",
        source_b="provisioning_internal",
        rule="max",
        comparison_level="total",
    ).model_dump(mode="json", by_alias=True),
}


def compose_config() -> dict:
    """Compone el config del preset F3 = F1 base + override de calibración + provisiones."""
    cfg = deepcopy(_STANDARD_CONFIG)
    cfg["name"] = "preset-provisiones-consumo"
    cfg["calibration"] = {**cfg["calibration"], **CALIBRATION_OVERRIDE}
    cfg["provisioning_cmf"] = deepcopy(PROVISIONING_SECTIONS["provisioning_cmf"])
    cfg["provisioning_internal"] = deepcopy(PROVISIONING_SECTIONS["provisioning_internal"])
    cfg["provisioning"] = deepcopy(PROVISIONING_SECTIONS["provisioning"])
    cfg["provisioning_ifrs9"] = None
    return cfg


def verify(cfg: dict) -> None:
    """Corre la cadena entera y comprueba que el número tiene sentido de NEGOCIO."""
    NikodymConfig.model_validate(cfg)
    with tempfile.TemporaryDirectory() as tmp:
        source = datasets.materialize(DATASET_ID, workdir=Path(tmp))
        run_cfg = deepcopy(cfg)
        run_cfg["data"]["load"]["source"] = str(source)
        # El informe al tmp: sin esto la corrida escribe en ``./reports`` y ensucia el repo.
        run_cfg["report"]["output_dir"] = str(Path(tmp) / "reports")
        study = nikodym.run(NikodymConfig.model_validate(run_cfg))

    assert study.run_context.status == "done", f"la corrida falló: {study.run_context.status}"
    orch = study.artifacts.get("provisioning", "card")
    estandar = float(orch.total_provision_a)
    interno = float(orch.total_provision_b)
    reportada = float(orch.total_reported_provision)
    exposicion = float(study.artifacts.get("provisioning_cmf", "card").total_exposure_amount)

    # La trampa de calibración: si el interno supera al estándar, el piso no muerde (binding != cmf)
    # y el producto pierde su titular. Es lo único que solo se ve corriendo la cadena entera.
    assert estandar > interno, (
        f"el interno ({interno / 1e6:.0f}M) supera al estándar ({estandar / 1e6:.0f}M): "
        "la calibración se heredó mal (¿target_pd del F1?) y la regla del máximo no muerde."
    )
    assert orch.binding == "cmf", f"binding={orch.binding!r}, se esperaba 'cmf' (el estándar manda)"
    assert reportada == estandar, "con rule='max' la provisión reportada debe ser el estándar"
    indice = estandar / exposicion
    assert 0.04 <= indice <= 0.14, f"índice de riesgo {indice:.2%} fuera de rango creíble"

    print(f"[verify] status=done · estándar={estandar / 1e6:.0f}M · interno={interno / 1e6:.0f}M")
    print(
        f"[verify] binding={orch.binding} · reportada={reportada / 1e6:.0f}M · índice={indice:.2%}"
    )


def main() -> None:
    """Verifica el preset corriendo la cadena e imprime el delta para pegar en ``ui/presets.py``."""
    verify(compose_config())
    print("\n# --- Pegar en ui/presets.py (derivado por scripts/derive_provisiones_preset.py) ---")
    print("\n_PROVISIONES_CALIBRATION_OVERRIDE = ", end="")
    pprint.pp(CALIBRATION_OVERRIDE, sort_dicts=False)
    print("\n_PROVISIONES_SECTIONS = ", end="")
    pprint.pp(PROVISIONING_SECTIONS, sort_dicts=False)


if __name__ == "__main__":
    main()
