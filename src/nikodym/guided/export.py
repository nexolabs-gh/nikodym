"""Excel opcional por etapa y paquete de la corrida (D-FLU-5, D-SIM-7; hallazgo #8 de INTEGRACION).

``export_excel()`` escribe en ``<run_dir>/<name>/excel/`` un libro por etapa, numerado en el orden
de las etapas (§3.2 de la enmienda) y rotulado con el mismo nombre que el resumen, más un último
libro con las decisiones. Cada libro lleva el resumen de la etapa, su **tabla de decisión** (la de
``sc.results[<etapa>]``, con rótulos en español) y las **tablas completas** que el informe publica
para ese dominio —las del anexo y las que el informe entrega por observación como exports—,
escritas por :mod:`nikodym.report.exports` con la misma protección de celdas: una tabla escrita
por las dos vías es la misma celda a celda (gate §6-9). Nunca es obligatorio ni la vía para ver un
resultado (D-SIM-7): el resultado se ve en el notebook o en pantalla.

``export(destino)`` empaqueta la carpeta del proyecto —config vigente, snapshot de datos, evidencia
de la corrida, informe y el Excel si se pidió— en un ``.zip`` que viaja entero.

Nada de esto se configura (D-FLU-12): la numeración, los nombres y qué tabla es «de decisión» son
constantes con su razón en el código.
"""

from __future__ import annotations

import json
import zipfile
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from nikodym.core.exceptions import MissingDependencyError
from nikodym.guided.summaries import STAGE_LABELS, STAGE_ORDER, StageSummary
from nikodym.report.document import table_title

if TYPE_CHECKING:
    import pandas as pd

    from nikodym.core.study import Study
    from nikodym.report.config import ReportConfig

__all__ = [
    "DECISIONS_BOOK",
    "EXCEL_SUBDIR",
    "STAGE_BOOKS",
    "pack_project",
    "write_stage_workbooks",
]

#: Subdirectorio del proyecto donde queda el Excel opcional (fuera de ``run/``, que
#: ``nikodym.run`` sustituye entero al consolidar).
EXCEL_SUBDIR: Final = "excel"

#: Las etapas con libro, en el orden de §3.2: todas menos ``report``, que no publica tablas y cuyo
#: entregable es el propio informe.
_STAGES_WITH_BOOK: Final[tuple[str, ...]] = tuple(s for s in STAGE_ORDER if s != "report")

#: Nombre de archivo de cada libro: ``01 Datos y muestras.xlsx`` … ``10 Validación formal.xlsx``.
#: El número es la posición de la etapa en el pipeline, y por eso no depende de qué etapas
#: corrieron: una corrida parcial deja los primeros libros y los números no se mueven.
STAGE_BOOKS: Final[dict[str, str]] = {
    stage: f"{numero:02d} {STAGE_LABELS[stage]}.xlsx"
    for numero, stage in enumerate(_STAGES_WITH_BOOK, start=1)
}
#: El último libro: las decisiones registradas en el trail (humanas, de la puerta y del motor).
DECISIONS_BOOK: Final = f"{len(_STAGES_WITH_BOOK) + 1:02d} Decisiones.xlsx"

_SHEET_SUMMARY: Final = "Resumen"
_SHEET_DECISION: Final = "Decisión"
_SHEET_INDEX: Final = "Índice"
_SHEET_MAX: Final = 31  # límite duro de Excel para el nombre de una hoja
_SHEET_FORBIDDEN: Final = frozenset("[]:*?/\\")

_XLSX_MISSING: Final = (
    'Exportar a Excel necesita openpyxl: instala el extra con `pip install "nikodym[excel]"` y '
    "vuelve a llamar a export_excel()."
)


def write_stage_workbooks(
    study: Study,
    summaries: Mapping[str, StageSummary],
    *,
    directory: Path,
    report_config: ReportConfig | None,
    trail_path: Path | None,
) -> tuple[Path, ...]:
    """Escribe los libros de las etapas que corrieron y el de decisiones; devuelve sus rutas.

    Los libros de una exportación anterior con el mismo nombre se reemplazan (son derivados de la
    corrida vigente, regenerables); ningún otro archivo de ``directory`` se toca.
    """
    from nikodym.report.exports import write_workbook

    if not _openpyxl_disponible():
        raise MissingDependencyError(_XLSX_MISSING)
    directory.mkdir(parents=True, exist_ok=True)
    tablas = _tablas_del_informe(study, report_config)
    escritos: list[Path] = []
    for stage in _STAGES_WITH_BOOK:
        resumen = summaries.get(stage)
        if resumen is None:
            continue
        hojas, con_indice = _hojas_de_la_etapa(stage, resumen, tablas)
        destino = directory / STAGE_BOOKS[stage]
        write_workbook(hojas, destino, index=con_indice)
        escritos.append(destino)
    decisiones = _hojas_de_decisiones(trail_path)
    if decisiones:
        destino = directory / DECISIONS_BOOK
        write_workbook(decisiones, destino, index=False)
        escritos.append(destino)
    return tuple(escritos)


def pack_project(project_dir: Path, destination: Path) -> Path:
    """Empaqueta la carpeta del proyecto en ``destination`` (``.zip``) y devuelve su ruta.

    Entran el config vigente, ``input/`` (snapshot de datos), ``run/`` (evidencia: trail,
    lineage, estudio), ``reports/`` y ``excel/`` si existe. Quedan fuera el candado y los respaldos
    laterales de corridas anteriores (``.run.old.*``, ``.reports.*``): el paquete es la corrida
    vigente, no la historia de la carpeta. Se escribe en un temporal y se publica con ``replace``.
    """
    if not project_dir.is_dir():
        raise FileNotFoundError(
            f"No hay carpeta de proyecto que empaquetar en {project_dir}: llama a run() primero."
        )
    destino = Path(destination)
    if destino.suffix.lower() != ".zip":
        destino = destino.with_suffix(".zip")
    destino.parent.mkdir(parents=True, exist_ok=True)
    temporal = destino.with_name(f".{destino.name}.tmp")
    raiz = project_dir.name
    with zipfile.ZipFile(temporal, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for ruta in sorted(_archivos_del_proyecto(project_dir)):
            zf.write(ruta, arcname=f"{raiz}/{ruta.relative_to(project_dir).as_posix()}")
    temporal.replace(destino)
    return destino


# ────────────────────────────── hojas de cada libro ──────────────────────────────


def _hojas_de_la_etapa(
    stage: str, resumen: StageSummary, tablas: Mapping[str, pd.DataFrame]
) -> tuple[dict[str, pd.DataFrame], dict[str, bool]]:
    """Resumen, tabla de decisión, tablas del informe del dominio e índice, en ese orden."""
    import pandas as pd

    hojas: dict[str, pd.DataFrame] = {}
    con_indice: dict[str, bool] = {}
    hojas[_SHEET_SUMMARY] = pd.DataFrame(
        {
            "Línea": [*resumen.lines, *(f"⚠ {alerta}" for alerta in resumen.alerts)],
        }
    )
    con_indice[_SHEET_SUMMARY] = False
    indice: list[dict[str, Any]] = [
        {"Hoja": _SHEET_SUMMARY, "Contenido": f"Resumen de «{resumen.label}»", "Filas": 0}
    ]
    if resumen.table is not None and not resumen.table.empty:
        hojas[_SHEET_DECISION] = resumen.table
        con_indice[_SHEET_DECISION] = False
        indice.append(
            {
                "Hoja": _SHEET_DECISION,
                "Contenido": f"Tabla de decisión de «{resumen.label}»",
                "Filas": len(resumen.table.index),
            }
        )
    for clave in sorted(k for k in tablas if k.startswith(f"{stage}.")):
        tabla = tablas[clave]
        hoja = _nombre_de_hoja(clave, hojas)
        hojas[hoja] = tabla
        con_indice[hoja] = True  # como los exports del informe: el índice es el identificador
        indice.append({"Hoja": hoja, "Contenido": table_title(clave), "Filas": len(tabla.index)})
    indice[0]["Filas"] = len(hojas[_SHEET_SUMMARY].index)
    hojas[_SHEET_INDEX] = pd.DataFrame(indice)
    con_indice[_SHEET_INDEX] = False
    return hojas, con_indice


def _nombre_de_hoja(clave: str, existentes: Mapping[str, Any]) -> str:
    """Nombre de hoja válido para Excel y único en el libro, legible por una persona.

    Las claves dinámicas (una tabla por variable) nombran la variable; el resto usa el título del
    informe. Se recorta a 31 caracteres y, si aun así colisiona, se numera.
    """
    partes = clave.split(".")
    if clave.startswith("binning.tables."):
        base = f"WoE — {'.'.join(partes[2:])}"
    elif clave.startswith("eda.univariate.profiles."):
        base = f"Perfil — {'.'.join(partes[3:])}"
    else:
        base = table_title(clave)
    limpio = "".join("_" if c in _SHEET_FORBIDDEN else c for c in base).strip()
    candidato = limpio[:_SHEET_MAX]
    n = 2
    while candidato in existentes:
        sufijo = f" ({n})"
        candidato = f"{limpio[: _SHEET_MAX - len(sufijo)]}{sufijo}"
        n += 1
    return candidato


def _tablas_del_informe(study: Study, report_config: ReportConfig | None) -> dict[str, Any]:
    """Las tablas que el informe publica para esta corrida, con sus claves ``dominio.tabla``.

    Es la misma recolección del ``ReportBuilder`` (tablas agregadas del anexo y tablas por
    observación de los exports): aquí no se decide qué es una tabla, se reutiliza la decisión del
    informe.
    """
    from nikodym.report.builder import ReportBuilder
    from nikodym.report.config import ReportConfig

    base = report_config if report_config is not None else ReportConfig()
    # Una corrida parcial (`run(until=)`) no tiene las cards que el informe exige: aquí no se
    # construye un informe, se recolectan las tablas de lo que sí corrió.
    config = base.model_copy(
        update={"sections": base.sections.model_copy(update={"missing_policy": "skip"})}
    )
    return dict(ReportBuilder(config).collect(study).tables)


def _hojas_de_decisiones(trail_path: Path | None) -> dict[str, pd.DataFrame]:
    """Las decisiones del trail en tres hojas: humanas, de la puerta guiada y del motor."""
    import pandas as pd

    if trail_path is None or not trail_path.is_file():
        return {}
    filas: list[dict[str, Any]] = []
    for linea in trail_path.read_text(encoding="utf-8").splitlines():
        if not linea.strip():
            continue
        evento = json.loads(linea)
        if evento.get("kind") != "decision":
            continue
        carga = evento.get("payload") or {}
        filas.append(
            {
                "Momento": evento.get("ts"),
                "Etapa": evento.get("step") or "",
                "Regla": carga.get("regla"),
                "Acción": carga.get("accion"),
                "Umbral": _celda(carga.get("umbral")),
                "Valor": _celda(carga.get("valor")),
                "Autor": carga.get("autor") or "motor",
                "Motivo": carga.get("motivo") or "",
            }
        )
    if not filas:
        return {}
    todas = pd.DataFrame(filas)
    hojas: dict[str, pd.DataFrame] = {}
    humanas = todas[todas["Autor"] == "usuario"]
    puerta = todas[todas["Autor"] == "puerta_guiada"]
    motor = todas[~todas["Autor"].isin(["usuario", "puerta_guiada"])]
    if not humanas.empty:
        hojas["Decisiones humanas"] = humanas.reset_index(drop=True)
    if not puerta.empty:
        hojas["Inferencias de la puerta"] = puerta.reset_index(drop=True)
    if not motor.empty:
        hojas["Decisiones del motor"] = motor.reset_index(drop=True)
    return hojas


def _celda(valor: Any) -> Any:
    """Un valor del trail como celda: escalares tal cual, estructuras como JSON legible."""
    if valor is None or isinstance(valor, str | int | float | bool):
        return valor
    return json.dumps(valor, ensure_ascii=False, sort_keys=True)


def _archivos_del_proyecto(project_dir: Path) -> Iterable[Path]:
    for entrada in project_dir.iterdir():
        if entrada.name.startswith("."):
            continue  # candado y respaldos laterales: no son la corrida vigente
        if entrada.is_file():
            yield entrada
        else:
            yield from (p for p in entrada.rglob("*") if p.is_file())


def _openpyxl_disponible() -> bool:
    from nikodym.report.exports import _openpyxl_disponible as disponible

    return disponible()
