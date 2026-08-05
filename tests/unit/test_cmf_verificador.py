"""Gate: un cotejo del bundle CMF dice también QUIÉN lo hizo (D-VER-1…3).

🔴 **Por qué existe.** ``CmfVerification.verified_by`` nació el 2026-08-05 con su enmienda aprobada
—[`_ENMIENDA-COTEJO-VERIFICADOR.md`](../../docs/design/_ENMIENDA-COTEJO-VERIFICADOR.md)— y **sin un
solo test**: ``grep -rn verified_by tests/`` daba cero, así que los criterios de aceptación 2 y 3 de
esa enmienda (round-trip del campo y control negativo de tipo) estaban escritos y sin ejercitar. Un
campo de trazabilidad que ningún gate sostiene se puede borrar, renombrar o dejar de serializar con
toda la suite en verde — y su función es justamente la contraria: distinguir un cotejo asistido de
la validación humana experta de B5, que es la diferencia que un auditor viene a leer.

**Qué se mide aquí:** el contrato del campo (opcionalidad, round-trip, tipo, ``extra="forbid"``) y
que el manifiesto empaquetado lo declare en cada entrada. **Qué NO:** el cruce del alcance de un
cotejo contra las fuentes declaradas, que vive en ``test_normativa_cmf_documento.py``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest
from pydantic import ValidationError

from nikodym.provisioning.cmf.matrices import (
    CmfMatrixManifest,
    CmfVerification,
    load_cmf_matrices,
)

_RAIZ = Path(__file__).resolve().parents[2]
_MANIFIESTO = _RAIZ / "src" / "nikodym" / "provisioning" / "cmf" / "data" / "manifest.json"

_COTEJO_BASE: dict[str, object] = {
    "date": "2026-07-14",
    "method": "Cotejo literal celda por celda contra el compendio consolidado vigente.",
    "scope": "Sólo la matriz de consumo (fuente compendio_portal_consolidado, hojas 16-18).",
    "matrix_ids": ["consumer_standard_v2025"],
}


@dataclass(frozen=True)
class _ConfigMatrices:
    """Config estructural mínima compatible con ``CmfMatrixConfigLike``."""

    active_version: str = "cmf_b1_b3_2025_01"
    require_verified_rows: bool = True
    fail_on_source_mismatch: bool = True


def _manifiesto_crudo() -> dict:
    datos: dict = json.loads(_MANIFIESTO.read_text(encoding="utf-8"))
    return datos


# --------------------------------------------------------------------------------------------
# Criterio de aceptación 1 — un manifiesto sin ``verified_by`` valida igual que antes
# --------------------------------------------------------------------------------------------


def test_un_cotejo_sin_verified_by_valida_y_su_default_es_vacio() -> None:
    """El campo es aditivo puro: ningún manifiesto anterior se rompe por no traerlo."""
    cotejo = CmfVerification.model_validate(_COTEJO_BASE)
    assert cotejo.verified_by == "", (
        "El default de verified_by dejó de ser la cadena vacía. D-VER-2: vacío significa «no "
        f"consta», y cualquier otro default sería una suposición sobre quién verificó: {cotejo!r}"
    )


# --------------------------------------------------------------------------------------------
# Criterio de aceptación 2 — el valor sobrevive el round-trip
# --------------------------------------------------------------------------------------------


def test_verified_by_sobrevive_el_round_trip_del_cotejo() -> None:
    autor = "Camilo González (validación humana experta, B5)"
    original = CmfVerification.model_validate({**_COTEJO_BASE, "verified_by": autor})
    volcado = original.model_dump(mode="json")

    assert volcado["verified_by"] == autor, (
        f"verified_by no llega al volcado del cotejo: {volcado!r}. Un campo de trazabilidad que no "
        "se serializa no existe para el auditor, que lee el manifiesto y no el objeto en memoria."
    )
    assert CmfVerification.model_validate(volcado) == original


def test_verified_by_sobrevive_el_round_trip_del_manifiesto_completo() -> None:
    """El cotejo viaja dentro del manifiesto: el round-trip que importa es el del manifiesto."""
    crudo = _manifiesto_crudo()
    autor = "Auditoría externa XYZ"
    crudo["verifications"][0]["verified_by"] = autor

    manifiesto = CmfMatrixManifest.model_validate(crudo)
    assert manifiesto.verifications[0].verified_by == autor

    revalidado = CmfMatrixManifest.model_validate(manifiesto.model_dump(mode="json"))
    assert revalidado == manifiesto, (
        "El manifiesto no reconstruye idéntico tras un volcado con verified_by poblado."
    )
    assert [cotejo.verified_by for cotejo in revalidado.verifications] == [
        cotejo.verified_by for cotejo in manifiesto.verifications
    ]


def test_el_bundle_cargado_del_disco_conserva_verified_by() -> None:
    """Ruta real de producción: ``load_cmf_matrices`` es por donde el motor lee el manifiesto."""
    bundle = load_cmf_matrices(_ConfigMatrices())
    autores = [cotejo.verified_by for cotejo in bundle.manifest.verifications]
    assert autores, "El bundle cargado no trae cotejos: el gate quedaría midiendo nada."
    assert all(isinstance(autor, str) for autor in autores), autores


# --------------------------------------------------------------------------------------------
# Criterio de aceptación 3 — control negativo de tipo, y sólo ahí
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize("valor", [123, 3.5, True, ["Cami"], {"quien": "Cami"}, None])
def test_un_verified_by_que_no_es_texto_rompe_la_validacion(valor: object) -> None:
    """Un autor numérico o nulo pasando en silencio dejaría el campo inservible como evidencia."""
    with pytest.raises(ValidationError) as excinfo:
        CmfVerification.model_validate({**_COTEJO_BASE, "verified_by": valor})
    assert any(error["loc"] == ("verified_by",) for error in excinfo.value.errors()), (
        f"La validación falló, pero no por verified_by={valor!r}: {excinfo.value.errors()!r}"
    )


def test_el_control_negativo_de_tipo_no_rechaza_el_payload_por_otra_causa() -> None:
    """Control positivo del control negativo: el mismo payload con un autor válido sí valida.

    Sin esto, el test de arriba pasaría igual si el ``_COTEJO_BASE`` fuera inválido por su cuenta —
    la trampa que este repo ya pagó con un control negativo que se cazaba a sí mismo.
    """
    cotejo = CmfVerification.model_validate({**_COTEJO_BASE, "verified_by": "Cami"})
    assert cotejo.verified_by == "Cami"


def test_un_verified_by_mal_escrito_no_pasa_en_silencio() -> None:
    """``extra="forbid"``: un ``verifiedBy`` o un ``verified_By`` sería autoría perdida y muda."""
    for typo in ("verifiedBy", "verified_By", "verified_by_"):
        with pytest.raises(ValidationError):
            CmfVerification.model_validate({**_COTEJO_BASE, typo: "Cami"})


# --------------------------------------------------------------------------------------------
# El manifiesto empaquetado
# --------------------------------------------------------------------------------------------


def test_cada_cotejo_del_manifiesto_declara_verified_by_explicitamente() -> None:
    """Política del bundle, más estricta que el modelo, y a propósito.

    El modelo acepta la ausencia (criterio 1, aditividad). El manifiesto de este repo, en cambio,
    **escribe la clave siempre**: con dos naturalezas de cotejo conviviendo, «no consta» es un dato
    que se declara, no un silencio que se deduce (D-VER-2). Así, un cotejo nuevo no puede entrar sin
    que alguien decida qué poner ahí.
    """
    cotejos = _manifiesto_crudo()["verifications"]
    assert cotejos, "El manifiesto perdió sus cotejos declarados."
    sin_campo = [cotejo["date"] for cotejo in cotejos if "verified_by" not in cotejo]
    assert not sin_campo, (
        f"Estos cotejos del manifiesto no declaran verified_by: {sin_campo}. Un cotejo sin autor "
        "declarado es indistinguible de uno asistido por script, que es justo la diferencia que "
        "D-VER-1 existe para publicar."
    )
    no_texto = [cotejo["date"] for cotejo in cotejos if not isinstance(cotejo["verified_by"], str)]
    assert not no_texto, f"verified_by no es texto en los cotejos: {no_texto}."
