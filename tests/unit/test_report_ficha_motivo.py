"""Gates de la capa C3 de FLUJO-GUIADO-SCORECARD: la ficha renderizada con el motivo (D-GOB-17).

Con ``purpose=`` la puerta guiada enciende la gobernanza y la ficha del modelo; desde D-GOB-17 el
``DecisionRecord`` materializa ``autor`` y ``motivo`` de cada decisión humana, y las tres
superficies de la ficha los muestran: ``model_card.json``/``model_card.md`` en la evidencia, la
tabla de decisiones de «Ficha del modelo» en Resultados (vitest) y el capítulo «Ficha del modelo»
del informe, que pasa a listar las decisiones humanas con su motivo desde la misma fuente que la
página ejecutiva. Sin decisiones humanas el capítulo lo dice con las palabras de la pantalla.
"""

from __future__ import annotations

import html as html_module
import json
import re
from pathlib import Path

import pytest
from _ui_f1 import write_stacked_behavior_parquet
from test_guided_summaries import _ofensores

from nikodym.guided import Scorecard
from nikodym.guided.summaries import SIN_DECISIONES

MOTIVO = "dato que no estará disponible al originar"
PROPOSITO = "Decidir la originación de créditos de consumo."


@pytest.fixture(autouse=True)
def _usar_fake_binning_process(fake_binning_process: object) -> None:
    del fake_binning_process


def _corrida(raiz: Path, *, name: str, decidir: bool) -> Scorecard:
    from conftest import FakeBinningProcess

    import nikodym.binning.transformer as transformer_module

    with pytest.MonkeyPatch.context() as parche:
        parche.setenv("PYTHONHASHSEED", "0")
        parche.setattr(transformer_module, "_import_binning_process", lambda: FakeBinningProcess)
        fuente = raiz / "cartera.parquet"
        write_stacked_behavior_parquet(fuente, repeats=50)
        sc = Scorecard(
            fuente,
            target="bad_flag",
            id="loan_id",
            cohort="cohort",
            oot_cohorts=["oot"],
            name=name,
            run_dir=raiz / "corridas",
            min_iv=0.0,
            purpose=PROPOSITO,
            owner="riesgo@banco.test",
            formats=["md"],
        )
        sc._echo = lambda _texto: None
        if decidir:
            sc.exclude("score", reason=MOTIVO)
        sc.run()
        assert sc.study.run_context.status == "done", sc.study.run_context.error
        return sc


@pytest.fixture(scope="module")
def corrida(tmp_path_factory: pytest.TempPathFactory) -> Scorecard:
    return _corrida(tmp_path_factory.mktemp("ficha"), name="con_decision", decidir=True)


@pytest.fixture(scope="module")
def corrida_sin_decisiones(tmp_path_factory: pytest.TempPathFactory) -> Scorecard:
    return _corrida(tmp_path_factory.mktemp("ficha-sin"), name="sin_decision", decidir=False)


def _capitulo(sc: Scorecard, section_id: str = "model_card") -> str:
    html = Path(sc.study.artifacts.get("report", "result").html_path).read_text(encoding="utf-8")
    inicio = html.index(f'data-section-id="{section_id}"')
    inicio = html.rindex("<section", 0, inicio)
    return html[inicio : html.index("</section>", inicio)]


def test_la_ficha_en_disco_materializa_autor_y_motivo(corrida: Scorecard) -> None:
    run_dir = corrida.project_dir / "run"
    ficha = json.loads((run_dir / "model_card.json").read_text(encoding="utf-8"))
    humanas = [d for d in ficha["decisions"] if d["regla"] == "decision_del_usuario"]
    assert [(d["accion"], d["autor"], d["motivo"]) for d in humanas] == [
        ("exclude", "usuario", MOTIVO)
    ]
    # Las reglas del motor no traen autor ni motivo; las declaraciones de la puerta guiada (la
    # entrada y sus inferencias) firman como `puerta_guiada` con su motivo (D-FLU-1).
    del_motor = [d for d in ficha["decisions"] if d["step"] != "scorecard_guided"]
    assert del_motor and all(d["autor"] is None and d["motivo"] is None for d in del_motor)
    de_la_puerta = [d for d in ficha["decisions"] if d["step"] == "scorecard_guided"]
    assert {d["autor"] for d in de_la_puerta} == {"usuario", "puerta_guiada"}
    assert all(d["motivo"] for d in de_la_puerta)
    markdown = (run_dir / "model_card.md").read_text(encoding="utf-8")
    assert f"decision_del_usuario → exclude — «{MOTIVO}» (usuario)" in markdown


def test_el_capitulo_ficha_del_informe_lista_las_decisiones_humanas_con_motivo(
    corrida: Scorecard,
) -> None:
    capitulo = _capitulo(corrida)
    assert "Ficha del modelo" in capitulo
    assert html_module.escape(PROPOSITO) in capitulo
    linea = corrida.summary().decisions[0]
    assert linea == f"exclude score — «{MOTIVO}»"
    assert html_module.escape(linea) in capitulo
    assert "Decisiones humanas registradas en esta corrida" in capitulo
    # Las del motor, las métricas y las fechas siguen en la ficha que el motor emite (D-SC-13…15).
    assert "quedan en la ficha del modelo" in capitulo
    assert not re.search(r"\d{4}-\d{2}-\d{2}", capitulo)


def test_sin_decisiones_humanas_el_capitulo_dice_lo_que_dice_la_pantalla(
    corrida_sin_decisiones: Scorecard,
) -> None:
    capitulo = _capitulo(corrida_sin_decisiones)
    assert html_module.escape(SIN_DECISIONES) in capitulo
    assert "Decisiones humanas registradas en esta corrida" not in capitulo


def test_la_pagina_ejecutiva_anuncia_la_ficha_condicionada_a_run_dir(corrida: Scorecard) -> None:
    """Pasada 2 de Codex sobre C1: con `governance` y sin `run_dir` la ficha no se escribe
    (D-GOB-6), y el informe no sabe si la corrida tiene carpeta de evidencia: no afirma un
    archivo que puede no existir."""
    pagina = _capitulo(corrida, "executive_summary")
    assert "Ficha del modelo" in pagina
    assert "model_card.json y model_card.md, en la carpeta de evidencia de la corrida si se" in (
        html_module.unescape(pagina)
    )
    assert "si se pidió una (run_dir)" in pagina


def test_el_capitulo_no_filtra_identificadores_del_motor(corrida: Scorecard) -> None:
    texto = html_module.unescape(re.sub(r"<[^>]+>", " ", _capitulo(corrida)))
    assert _ofensores(texto) == []


def test_el_qmd_escribe_la_decision_como_texto_literal(corrida: Scorecard) -> None:
    """El motivo lo escribió una persona: en la fuente editable va escapado, nunca como marcado."""
    qmd = Path(corrida.study.artifacts.get("report", "result").md_path).read_text(encoding="utf-8")
    encabezado = re.search(r"^## \d+ Ficha del modelo$", qmd, re.M)
    assert encabezado is not None
    capitulo = qmd[encabezado.start() : qmd.index("\n## ", encabezado.end())]
    assert MOTIVO in capitulo.replace("\\", "")
    # Line block literal de pandoc, como el resto del capítulo: la línea va con `| ` delante y la
    # puntuación escapada, así que el motivo no puede volverse marcado activo.
    linea = re.search(r"^\| .*exclude score.*$", capitulo, re.M)
    assert linea is not None
    assert linea.group(0).endswith("\\.")  # la puntuación ASCII del párrafo va escapada
