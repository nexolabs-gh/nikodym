"""``nikodym.Scorecard``: la puerta guiada del scorecard (D-FLU-1…D-FLU-4, D-FLU-9).

Se construye con lo institucional, infiere y declara el resto, corre con :func:`nikodym.run` y
cuenta cada etapa. **No es un segundo orquestador**: arma un ``NikodymConfig`` a partir del preset
F1 y de sus argumentos, y todo lo que calcula lo calcula el motor. ``sc.config`` es la verdad;
``sc.config_hash``, la identidad; ``run()`` sobre ese config por la puerta completa reproduce los
mismos resultados (D-SIM-1).
"""

from __future__ import annotations

import hashlib
import io
import os
import shutil
from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Literal

import pandas as pd
from pydantic import ValidationError

from nikodym.core.config import NikodymConfig, RunConfig, config_hash, dump_config
from nikodym.core.exceptions import ConfigError, NikodymError
from nikodym.guided.inference import (
    AUTOR_PUERTA,
    Inferencia,
    columnas_categoricas,
    columnas_esquema,
    columnas_predictoras,
    dtype_logico,
    sugerir_oot_cohorts,
    sugerir_oot_from,
)
from nikodym.guided.summaries import (
    STAGE_LABELS,
    FinalSummary,
    StageSummary,
    SummaryContext,
    build_final_summary,
    build_stage_summary,
)
from nikodym.report.prose import _pct, _plural

__all__ = ["Scorecard", "ScorecardInputError", "ScorecardRunError"]

#: Paso con que la puerta firma sus eventos en el trail (D-FLU-3: ``step="scorecard_guided"``).
GUIDED_STEP: Final = "scorecard_guided"

#: Nombre del subdirectorio de la corrida dentro de la carpeta del proyecto. ``nikodym.run``
#: sustituye **entero** su destino al consolidar una corrida y aparta el anterior a un respaldo
#: lateral; por eso la corrida vive en un subdirectorio y el snapshot de datos, el config vigente
#: y el informe viven al lado, donde ninguna consolidación se los lleva.
_RUN_SUBDIR: Final = "run"
_REPORTS_SUBDIR: Final = "reports"
_INPUT_SUBDIR: Final = "input"
_CONFIG_NAME: Final = "config.yaml"
_MODEL_CARD_NAME: Final = "model_card.json"

_TargetRule = Mapping[str, Any]


class ScorecardInputError(ConfigError):
    """Lo que la puerta guiada rechaza **antes de correr**.

    Falta una decisión institucional o un argumento no casa con el archivo.
    """


class ScorecardRunError(NikodymError):
    """La corrida terminó fallida y se pidió ``raise_on_error=True`` (D-FLU-4, hallazgo #4)."""


@dataclass(frozen=True, slots=True)
class _Muestras:
    """Cómo se separa la muestra, ya resuelto, y las particiones que existirán."""

    strategy: dict[str, Any]
    partitions: tuple[str, ...]
    comparisons: tuple[str, ...]
    label: str
    time_column: str | None
    time_axis: Literal["none", "period", "cohort"]


class Scorecard:
    """Un scorecard de comportamiento de punta a punta, con la entrada mínima (D-FLU-1).

    Parameters
    ----------
    data
        Ruta a un CSV, Parquet o Excel, o un ``pandas.DataFrame``. Un DataFrame se persiste como
        snapshot Parquet bajo ``<run_dir>/<name>/input/`` y el config lo referencia, así que
        ``sc.to_yaml()`` reproduce la corrida por sí solo.
    target
        La columna 0/1 (o verdadero/falso) que dice quién es «malo», o una regla
        ``{"col": "dias_mora", "op": ">", "value": 90}`` con los operadores del motor.
    id
        Identificador de cada operación, opcional y recomendado: una columna (llave de unicidad)
        o el nombre del índice del archivo. Sin él se usa el índice del archivo y se declara.
    date, cohort, partition
        El eje temporal: ``date=`` particiona por fecha de corte, ``cohort=`` por añada; sin eje,
        ``partition="random"`` explícito (D-OBL-5: la estrategia no se siembra). Exactamente uno.
    oot_from, oot_cohorts
        La frontera fuera de tiempo, **obligatoria** con ``date`` (fecha ISO) o con ``cohort``
        (las cohortes reservadas). Si falta, la puerta se detiene antes de correr con el rango
        del archivo y el valor que usaría.
    holdout
        Proporción reservada como Holdout dentro de la muestra de desarrollo (0,2 de fábrica).
    name, run_dir
        Nombre de la versión del proyecto y carpeta raíz: la evidencia queda en
        ``<run_dir>/<name>/`` (§8-8: ``"nikodym-runs"`` y ``"scorecard"`` de fábrica).
    purpose, owner, review_every
        Con ``purpose`` se enciende la gobernanza y la ficha del modelo (D-GOB-8); sin él no hay
        ficha. ``owner`` y ``review_every`` (meses) completan la ficha.
    track
        Ruta o URI de MLflow: enciende el registro de la corrida (D-FLU-9). Apagado sin él.
    features, categorical
        Las predictoras y cuáles son categóricas. Si no se dan, se infieren y se declaran.
    max_bins, min_bin_size, monotonic, min_iv, max_correlation, max_vif, stepwise, p_enter,
    p_exit, sign_policy, pdo, target_score, target_odds, anchor, target_pd, deciles,
    psi_thresholds, validation, document, formats
        Los campos esenciales de cada etapa (§3.8 de la enmienda), con los valores del preset F1
        de fábrica. Cada uno escribe una hoja existente del config; lo que no está aquí se
        alcanza por ``sc.config`` (la puerta completa).
    """

    def __init__(
        self,
        data: str | Path | pd.DataFrame,
        target: str | _TargetRule,
        *,
        id: str | None = None,
        date: str | None = None,
        cohort: str | None = None,
        partition: str | None = None,
        oot_from: str | None = None,
        oot_cohorts: Sequence[str] | None = None,
        holdout: float = 0.2,
        name: str = "scorecard",
        run_dir: str | Path = "nikodym-runs",
        purpose: str | None = None,
        owner: str | None = None,
        review_every: int = 12,
        track: str | Path | None = None,
        features: Sequence[str] | None = None,
        categorical: Sequence[str] | None = None,
        max_bins: int = 6,
        min_bin_size: float = 0.05,
        monotonic: str | None = "auto_asc_desc",
        min_iv: float = 0.02,
        max_correlation: float = 0.75,
        max_vif: float = 5.0,
        stepwise: bool = True,
        p_enter: float = 0.05,
        p_exit: float = 0.05,
        sign_policy: str = "flag",
        pdo: float = 20.0,
        target_score: float = 600.0,
        target_odds: float = 50.0,
        anchor: str = "development_observed",
        target_pd: float | None = None,
        deciles: int = 10,
        psi_thresholds: tuple[float, float] = (0.10, 0.25),
        validation: Sequence[str] | None = ("discrimination", "calibration", "stability"),
        document: Mapping[str, str] | None = None,
        formats: Sequence[str] | None = None,
    ) -> None:
        if not name or not str(name).strip():
            raise ScorecardInputError("name= no puede estar vacío: es el nombre de la versión.")
        self._name = str(name).strip()
        self._project_dir = (Path(run_dir) / self._name).resolve()
        self._run_dir = self._project_dir / _RUN_SUBDIR
        self._reports_dir = self._project_dir / _REPORTS_SUBDIR
        self._config_path = self._project_dir / _CONFIG_NAME
        self._until: str | None = None
        self._study: Any = None
        self._stage_summaries: dict[str, StageSummary] = {}
        self._final: FinalSummary | None = None
        self._decisions: list[dict[str, Any]] = []
        self._pending_decisions = False
        self._echo: Callable[[str], None] = print
        self._snapshot_pendiente: tuple[Path, bytes] | None = None

        frame, source, source_label = self._cargar(data)
        inferencias: list[Inferencia] = []

        # ── identificador ────────────────────────────────────────────────────────────────
        index_col, unique_keys, id_label = self._resolver_id(frame, id)
        if id is None:
            inferencias.append(
                Inferencia(
                    regla="inferencia_identificador",
                    valor="índice del archivo",
                    motivo="no se declaró id=: cada fila se identifica por su posición",
                )
            )

        # ── target ───────────────────────────────────────────────────────────────────────
        bad_rule, columnas_target = self._regla_del_target(frame, target)
        target_col = "target" if "target" not in frame.columns else "target_nikodym"

        # ── muestras ─────────────────────────────────────────────────────────────────────
        muestras = self._resolver_muestras(
            frame,
            date=date,
            cohort=cohort,
            partition=partition,
            oot_from=oot_from,
            oot_cohorts=oot_cohorts,
            holdout=holdout,
        )

        # ── esquema, predictoras y categóricas ───────────────────────────────────────────
        fechas = (date,) if date is not None else ()
        textos = (cohort,) if cohort is not None and dtype_logico(frame[cohort]) != "str" else ()
        esquema = columnas_esquema(frame, fechas=fechas, textos=textos)
        n_texto = sum(1 for c in esquema if c["dtype"] in {"str", "category", "bool"})
        inferencias.append(
            Inferencia(
                regla="inferencia_esquema",
                valor={c["name"]: c["dtype"] for c in esquema},
                motivo="tipos leídos de los datos; nullable sólo donde hay vacíos",
            )
        )
        excluidas: dict[str, str] = {}
        if id is not None and unique_keys is not None:
            excluidas[id] = "identificador"
        for columna in columnas_target:
            excluidas[columna] = "define el incumplimiento, sería una fuga de información"
        if date is not None:
            excluidas[date] = "eje temporal de la partición"
        if cohort is not None:
            excluidas[cohort] = "cohorte de la partición"
        if features is None:
            predictoras, motivos = columnas_predictoras(frame, excluidas=excluidas)
            if not predictoras:
                raise ScorecardInputError(
                    "No queda ninguna columna predictora después de apartar el identificador, "
                    "el target y el eje temporal. Pasa features= con las columnas a modelar."
                )
            inferencias.append(
                Inferencia(
                    regla="inferencia_predictoras",
                    valor={"incluidas": list(predictoras), "excluidas": motivos},
                    motivo=(
                        "todas las columnas menos el identificador, las que definen el "
                        "incumplimiento, el eje temporal y las fechas"
                    ),
                )
            )
        else:
            predictoras = tuple(str(c) for c in features)
            faltan = [c for c in predictoras if c not in frame.columns]
            if faltan:
                raise ScorecardInputError(
                    f"features= nombra columnas que el archivo no trae: {', '.join(faltan)}."
                )
            fugas = [c for c in predictoras if c in columnas_target]
            if fugas:
                raise ScorecardInputError(
                    "features= incluye columnas que definen el incumplimiento: "
                    f"{', '.join(fugas)}. "
                    "Entrarían como predictoras de sí mismas (fuga de información)."
                )
            motivos = {}
        if categorical is None:
            categoricas = columnas_categoricas(frame, predictoras)
            inferencias.append(
                Inferencia(
                    regla="inferencia_categoricas",
                    valor=list(categoricas),
                    motivo="predictoras de texto, categoría o verdadero/falso",
                )
            )
        else:
            categoricas = tuple(str(c) for c in categorical)
            fuera = [c for c in categoricas if c not in predictoras]
            if fuera:
                raise ScorecardInputError(
                    f"categorical= nombra columnas que no son predictoras: {', '.join(fuera)}."
                )
        inferencias.append(
            Inferencia(
                regla="inferencia_muestras",
                valor={
                    "muestras": list(muestras.partitions),
                    "comparaciones": list(muestras.comparisons),
                    "eje_temporal": muestras.time_axis,
                },
                motivo="las listas de desempeño, validación y estabilidad se ajustan a las "
                "muestras que la partición declarada produce",
            )
        )
        self._inferences: tuple[Inferencia, ...] = tuple(inferencias)
        self._partition_label = muestras.label
        self._source_label = source_label
        self._inference_lines = self._lineas_de_inferencia(
            esquema=esquema,
            n_texto=n_texto,
            predictoras=predictoras,
            categoricas=categoricas,
            motivos=motivos,
            id_label=id_label,
        )

        # ── el config ────────────────────────────────────────────────────────────────────
        cfg = _config_base()
        cfg["name"] = self._name
        cfg["data"] = {
            "type": "standard",
            "load": {
                "source": source,
                "file_format": "auto",
                "backend": "pandas",
                "csv_options": {"sep": ",", "decimal": ".", "encoding": "utf-8"},
            },
            "schema": {
                "columns": esquema,
                "strict": False,
                "ordered": False,
                "index_col": index_col,
                "unique_keys": unique_keys,
            },
            "missing": {"special_values": [], "max_missing_rate": 0.99},
            "target": {
                "target_col": target_col,
                "bad_rule": bad_rule,
                "good_rule": None,
                "indeterminate_rule": None,
                "exclusion_rules": [],
                "window": None,
            },
            "partition": {
                "strategy": muestras.strategy,
                "ttd_includes_excluded": True,
                "min_bads_per_partition": 30,
            },
        }
        eda = cfg["eda"]
        if muestras.time_axis == "period":
            eda["default_rate"] = {"axis": "period", "date_col": muestras.time_column}
        elif muestras.time_axis == "cohort":
            eda["default_rate"] = {"axis": "cohort", "cohort_col": muestras.time_column}
        else:
            # Sin eje temporal la tasa se agrupa por la cohorte de la partición si existe; con
            # partición aleatoria no hay ninguna y el motor lo declara «no evaluable» (SDD-31 §8).
            eda["default_rate"] = {"axis": "period"}
        eda["univariate"] = {"columns": list(predictoras)}
        binning = cfg["binning"]
        binning["feature_columns"] = list(predictoras)
        binning["categorical_columns"] = list(categoricas)
        binning["max_n_bins"] = max_bins
        binning["min_bin_size"] = min_bin_size
        binning["monotonic_trend"] = monotonic
        selection = cfg["selection"]
        selection["min_iv"] = min_iv
        selection["correlation"]["threshold"] = max_correlation
        selection["vif"]["threshold"] = max_vif
        model = cfg["model"]
        model["stepwise"]["enabled"] = stepwise
        model["stepwise"]["entry_p_value"] = p_enter
        model["stepwise"]["exit_p_value"] = p_exit
        model["sign_policy"]["action"] = sign_policy
        scorecard = cfg["scorecard"]
        scorecard["pdo"] = pdo
        scorecard["target_score"] = target_score
        scorecard["target_odds"] = target_odds
        calibration = cfg["calibration"]
        calibration["anchor_source"] = anchor
        calibration["target_pd"] = target_pd
        performance = cfg["performance"]
        performance["n_deciles"] = deciles
        performance["partitions"] = list(muestras.partitions)
        stability = cfg["stability"]
        stability["psi_stable_threshold"], stability["psi_review_threshold"] = psi_thresholds
        stability["comparisons"] = list(muestras.comparisons)
        stability["temporal_axis"] = muestras.time_axis
        stability["temporal_column"] = muestras.time_column
        if validation is None:
            cfg["validation"] = None
        else:
            cfg["validation"]["families"] = list(validation)
            cfg["validation"]["discrimination"]["partitions"] = list(muestras.partitions)
            cfg["validation"]["stability"]["psi_stable_threshold"] = psi_thresholds[0]
            cfg["validation"]["stability"]["psi_review_threshold"] = psi_thresholds[1]
        report = cfg["report"]
        report["output_dir"] = str(self._reports_dir)
        if document:
            report["document"] = {**report.get("document", {}), **dict(document)}
        if formats is not None:
            report["formats"] = list(formats)
        if purpose is not None:
            if not str(purpose).strip():
                raise ScorecardInputError(
                    "purpose= está en blanco: la ficha del modelo exige un propósito escrito "
                    "por la institución. Omite el argumento si no quieres ficha."
                )
            cfg["governance"] = {
                "model_name": self._name,
                "purpose": str(purpose),
                "author": owner,
                "review_period_months": review_every,
            }
        if track is not None:
            cfg["tracking"] = {"enabled": True, "tracking_uri": str(track)}
        try:
            self._config: NikodymConfig = NikodymConfig.model_validate(cfg)
        except ValidationError as exc:
            from nikodym.api import _mensaje_de_validacion

            raise ScorecardInputError(
                f"Un argumento no cumple las restricciones del motor: {_mensaje_de_validacion(exc)}"
            ) from exc
        self._config, self._steps = self._resolver_pipeline(self._config)
        self._publicar_snapshot()

    # ── construcción ────────────────────────────────────────────────────────────────────

    def _publicar_snapshot(self) -> None:
        """Escribe el snapshot del DataFrame, ya validado todo, sin pisar uno existente."""
        if self._snapshot_pendiente is None:
            return
        snapshot, contenido = self._snapshot_pendiente
        self._snapshot_pendiente = None
        if snapshot.exists():
            return  # mismo contenido por construcción (el nombre es su hash)
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        temporal = snapshot.with_name(f".{snapshot.name}.{os.getpid()}.tmp")
        temporal.write_bytes(contenido)
        os.replace(temporal, snapshot)

    def _cargar(self, data: str | Path | pd.DataFrame) -> tuple[pd.DataFrame, str, str]:
        """Carga el archivo con el cargador del motor, o persiste el DataFrame como snapshot."""
        if isinstance(data, pd.DataFrame):
            if data.empty:
                raise ScorecardInputError("data= es un DataFrame vacío.")
            # El snapshot es inmutable y se nombra por su contenido: otro DataFrame con el mismo
            # `name` deja un archivo nuevo y no pisa el que referencia la evidencia de una
            # corrida anterior. Se escribe en disco sólo después de validar todo el Scorecard
            # (`_publicar_snapshot`), no aquí (pasada 1 de Codex sobre la capa A).
            buffer = io.BytesIO()
            data.to_parquet(buffer)
            contenido = buffer.getvalue()
            huella = hashlib.sha256(contenido).hexdigest()[:16]
            snapshot = self._project_dir / _INPUT_SUBDIR / f"data-{huella}.parquet"
            self._snapshot_pendiente = (snapshot, contenido)
            return (
                pd.read_parquet(io.BytesIO(contenido)),
                str(snapshot),
                f"DataFrame en memoria, guardado como {snapshot}",
            )
        ruta = Path(data).resolve()
        if not ruta.is_file():
            raise ScorecardInputError(f"data= apunta a un archivo que no existe: {ruta}")
        from nikodym.data.config import LoadingConfig
        from nikodym.data.loading import DataLoader

        try:
            frame = DataLoader.from_config(LoadingConfig(source=str(ruta))).load()
        except NikodymError as exc:
            raise ScorecardInputError(f"No se pudo leer {ruta}: {exc}") from exc
        if frame.empty:
            raise ScorecardInputError(f"El archivo no trae filas: {ruta}")
        return frame, str(ruta), str(ruta)

    @staticmethod
    def _resolver_id(
        frame: pd.DataFrame, id_: str | None
    ) -> tuple[str | None, list[str] | None, str]:
        if id_ is None:
            return None, None, "sin identificador declarado: se usa el índice del archivo"
        if id_ in frame.columns:
            return None, [id_], f"{id_} (columna, llave de unicidad)"
        if frame.index.name == id_:
            return id_, None, f"{id_} (índice del archivo)"
        raise ScorecardInputError(
            f"id={id_!r} no es una columna ni el índice del archivo. Columnas disponibles: "
            f"{', '.join(str(c) for c in frame.columns)}."
        )

    @staticmethod
    def _regla_del_target(
        frame: pd.DataFrame, target: str | _TargetRule
    ) -> tuple[dict[str, Any], tuple[str, ...]]:
        if isinstance(target, Mapping):
            faltan = [k for k in ("col", "op", "value") if k not in target]
            if faltan:
                raise ScorecardInputError(
                    "target= como regla necesita las claves col, op y value "
                    f"(faltan {', '.join(faltan)}); por ejemplo "
                    '{"col": "dias_mora", "op": ">", "value": 90}.'
                )
            columna = str(target["col"])
            if columna not in frame.columns:
                raise ScorecardInputError(
                    f"La regla del target usa la columna {columna!r}, que el archivo no trae."
                )
            predicado = {"col": columna, "op": target["op"], "value": target["value"]}
            return {"all_of": [predicado], "any_of": []}, (columna,)
        columna = str(target)
        if columna not in frame.columns:
            raise ScorecardInputError(
                f"target={columna!r} no es una columna del archivo. Columnas disponibles: "
                f"{', '.join(str(c) for c in frame.columns)}."
            )
        serie = frame[columna]
        if dtype_logico(serie) == "bool":
            valor: Any = True
        else:
            valores = set(pd.unique(serie.dropna()))
            if not valores or not valores <= {0, 1}:
                raise ScorecardInputError(
                    f"target={columna!r} tiene que ser una columna 0/1 (o verdadero/falso); trae "
                    f"otros valores. Para definir «malo» con una condición pasa una regla: "
                    f'target={{"col": "{columna}", "op": ">=", "value": 90}}.'
                )
            valor = 1
        return {"all_of": [{"col": columna, "op": "==", "value": valor}], "any_of": []}, (columna,)

    @staticmethod
    def _resolver_muestras(
        frame: pd.DataFrame,
        *,
        date: str | None,
        cohort: str | None,
        partition: str | None,
        oot_from: str | None,
        oot_cohorts: Sequence[str] | None,
        holdout: float,
    ) -> _Muestras:
        declarados = [
            n
            for n, v in (("date", date), ("cohort", cohort), ("partition", partition))
            if v is not None
        ]
        if len(declarados) > 1:
            raise ScorecardInputError(
                f"Declara un solo eje: {', '.join(declarados)} no pueden ir juntos. Usa date= "
                'para partir por fecha, cohort= por añada, o partition="random" sin eje temporal.'
            )
        if not 0.0 <= float(holdout) < 1.0:
            raise ScorecardInputError("holdout= tiene que estar entre 0 y 1 (0,2 de fábrica).")
        if date is not None:
            if date not in frame.columns:
                raise ScorecardInputError(f"date={date!r} no es una columna del archivo.")
            if oot_from is None:
                try:
                    primera, ultima, meses, sugerida = sugerir_oot_from(frame[date])
                except ValueError as exc:
                    raise ScorecardInputError(f"date={date!r}: {exc}") from exc
                raise ScorecardInputError(
                    f"Falta la frontera fuera de tiempo: oot_from=. El archivo cubre de {primera} "
                    f"a {ultima} ({meses} meses). Con los últimos "
                    f"{'12 meses' if meses >= 24 else 'meses del último cuarto'} como muestra "
                    f"fuera de tiempo la frontera sería oot_from={sugerida!r}. Es una decisión de "
                    "la institución: pásala explícita."
                )
            if pd.isna(pd.to_datetime(oot_from, errors="coerce")):
                raise ScorecardInputError(
                    f"oot_from={oot_from!r} no es una fecha legible; escríbela en ISO 8601 "
                    "(por ejemplo 2024-01-01)."
                )
            fecha_oot = pd.to_datetime(oot_from)
            partitions = ("desarrollo",) + (("holdout",) if holdout > 0 else ()) + ("oot",)
            return _Muestras(
                strategy={
                    "type": "temporal",
                    "date_col": date,
                    "oot_from": str(oot_from),
                    "holdout_fraction": float(holdout),
                },
                partitions=partitions,
                comparisons=_comparaciones(partitions),
                label=(
                    f"fuera de tiempo desde {fecha_oot.date().isoformat()} por «{date}»; "
                    f"holdout {_pct(holdout, decimals=0)} del resto"
                ),
                time_column=date,
                time_axis="period",
            )
        if cohort is not None:
            if cohort not in frame.columns:
                raise ScorecardInputError(f"cohort={cohort!r} no es una columna del archivo.")
            try:
                distintas, sugeridas = sugerir_oot_cohorts(frame[cohort])
            except ValueError as exc:
                raise ScorecardInputError(f"cohort={cohort!r}: {exc}") from exc
            if oot_cohorts is None:
                raise ScorecardInputError(
                    f"Falta la frontera fuera de tiempo: oot_cohorts=. El archivo trae "
                    f"{len(distintas)} cohortes ({', '.join(distintas)}). Reservando el último "
                    f"cuarto como muestra fuera de tiempo sería oot_cohorts={sugeridas!r}. Es una "
                    "decisión de la institución: pásala explícita."
                )
            reservadas = [str(c) for c in oot_cohorts]
            ausentes = [c for c in reservadas if c not in distintas]
            if not reservadas or ausentes:
                raise ScorecardInputError(
                    "oot_cohorts= nombra cohortes que el archivo no trae: "
                    f"{', '.join(ausentes) or '(vacío)'}. "
                    f"Cohortes disponibles: {', '.join(distintas)}."
                )
            partitions = ("desarrollo",) + (("holdout",) if holdout > 0 else ()) + ("oot",)
            return _Muestras(
                strategy={
                    "type": "cohort",
                    "cohort_col": cohort,
                    "oot_cohorts": reservadas,
                    "holdout_fraction": float(holdout),
                },
                partitions=partitions,
                comparisons=_comparaciones(partitions),
                label=(
                    f"cohortes fuera de tiempo: {', '.join(reservadas)} (columna «{cohort}»); "
                    f"holdout {_pct(holdout, decimals=0)} del resto"
                ),
                time_column=cohort,
                time_axis="cohort",
            )
        if partition is not None:
            if partition != "random":
                raise ScorecardInputError(
                    f"partition={partition!r} no existe en la puerta guiada: sin eje temporal la "
                    'única opción es partition="random". Con eje, usa date= o cohort=.'
                )
            if holdout <= 0.0:
                raise ScorecardInputError(
                    'partition="random" necesita holdout > 0: sin muestra fuera de tiempo, el '
                    "Holdout es la única muestra con que comparar el modelo."
                )
            dev = round(1.0 - float(holdout), 10)
            return _Muestras(
                strategy={
                    "type": "random",
                    "dev_fraction": dev,
                    "holdout_fraction": float(holdout),
                    "oot_fraction": 0.0,
                    "stratify_by": None,
                },
                partitions=("desarrollo", "holdout"),
                comparisons=("dev_vs_holdout",),
                label=(
                    f"partición aleatoria: {_pct(dev, decimals=0)} desarrollo y "
                    f"{_pct(holdout, decimals=0)} holdout, sin muestra fuera de tiempo"
                ),
                time_column=None,
                time_axis="none",
            )
        raise ScorecardInputError(
            "Falta el eje temporal: pasa date= (con oot_from=) o cohort= (con oot_cohorts=). Si "
            'tus datos no tienen eje temporal, declara partition="random".'
        )

    @staticmethod
    def _lineas_de_inferencia(
        *,
        esquema: list[dict[str, Any]],
        n_texto: int,
        predictoras: Sequence[str],
        categoricas: Sequence[str],
        motivos: Mapping[str, str],
        id_label: str,
    ) -> tuple[str, ...]:
        fuera = ", ".join(f"{c} ({m})" for c, m in motivos.items())
        return (
            (
                f"Se infirió: esquema de {len(esquema)} columnas ({len(esquema) - n_texto} "
                f"numéricas o de fecha, {n_texto} de texto); {len(predictoras)} "
                f"{_plural(len(predictoras), 'predictora', 'predictoras')} "
                f"({len(categoricas)} {_plural(len(categoricas), 'categórica', 'categóricas')})"
                + (f"; fuera: {fuera}" if fuera else "")
            ),
            f"Identificador: {id_label}",
        )

    @staticmethod
    def _resolver_pipeline(config: NikodymConfig) -> tuple[NikodymConfig, tuple[str, ...]]:
        """El config con sus secciones coaccionadas y los pasos en orden, comprobados sin correr.

        Un ``NikodymConfig`` recién validado lleva las secciones de dominio **opacas** (``dict``)
        si su capa no está importada; la comprobación del pipeline (D-PIPE-3) las coacciona a su
        clase real, y la puerta se queda con ESE config: es el que corre, el que exporta y el que
        las decisiones humanas editan campo a campo (medido fuera de pytest, donde nadie importa
        los dominios de antemano).
        """
        from nikodym.core.study import Study

        study = Study(config, apply_global_seed=False)
        try:
            pasos = study.check_pipeline()
        except ValidationError as exc:
            from nikodym.api import _mensaje_de_validacion

            raise ScorecardInputError(
                f"El config armado no es ejecutable: {_mensaje_de_validacion(exc)}"
            ) from exc
        except Exception as exc:
            raise ScorecardInputError(f"El config armado no es ejecutable: {exc}") from exc
        return study.config, tuple(pasos)

    # ── propiedades ─────────────────────────────────────────────────────────────────────

    @property
    def config(self) -> NikodymConfig:
        """El ``NikodymConfig`` completo que corre (la puerta completa lo ve todo)."""
        return self._config

    @property
    def config_hash(self) -> str:
        """La identidad de la corrida completa sobre el config vigente."""
        return config_hash(self._config)

    @property
    def study(self) -> Any:
        """El ``Study`` de la última corrida, o ``None`` si aún no corrió."""
        return self._study

    @property
    def steps(self) -> tuple[str, ...]:
        """Las etapas del pipeline en orden; los valores válidos de ``run(until=)``."""
        return self._steps

    @property
    def project_dir(self) -> Path:
        """``<run_dir>/<name>``: donde queda todo."""
        return self._project_dir

    @property
    def results(self) -> dict[str, pd.DataFrame]:
        """La tabla de decisión de cada etapa que ya corrió (con sus rótulos en español)."""
        return {
            etapa: resumen.table
            for etapa, resumen in self._stage_summaries.items()
            if resumen.table is not None
        }

    @property
    def inferences(self) -> tuple[Inferencia, ...]:
        """Lo que la puerta infirió y declara al trail en cada corrida."""
        return self._inferences

    def to_yaml(self) -> str:
        """El config vigente en YAML, para la puerta completa o la pantalla."""
        return dump_config(self._config)

    # ── correr ──────────────────────────────────────────────────────────────────────────

    def run(self, until: str | None = None, *, raise_on_error: bool = False) -> Scorecard:
        """Corre el pipeline completo —o hasta ``until`` inclusive— y cuenta cada etapa.

        ``until`` recorta ``run.steps`` al prefijo del pipeline: es una corrida parcial con su
        propio ``config_hash`` (D-FLU-3). Ante un fallo de dominio la corrida devuelve el estado
        y el resumen final lo dice; con ``raise_on_error=True`` se levanta
        :class:`ScorecardRunError` con el mismo diagnóstico (D-FLU-4).
        """
        import nikodym

        if until is not None and until not in self._steps:
            raise ScorecardInputError(
                f"until={until!r} no es una etapa de este pipeline. Etapas: "
                f"{', '.join(self._steps)}."
            )
        pasos = list(self._steps[: self._steps.index(until) + 1]) if until is not None else None
        config = self._config.model_copy(update={"run": RunConfig(steps=pasos)})
        self._preparar_proyecto()
        self._until = until
        self._stage_summaries = {}
        self._final = None
        self._study = nikodym.run(
            config,
            run_dir=self._run_dir,
            preamble=self._preamble(),
            on_step=self._contar_etapa,
        )
        self._pending_decisions = False
        self._final = build_final_summary(
            self._study, tuple(self._stage_summaries.values()), self._context()
        )
        self._echo(f"Ejecución: {self._final.execution}")
        self._echo(f"Validación técnica: {self._final.validation}")
        if self._study.run_context.status != "done" and raise_on_error:
            raise ScorecardRunError(self._final.execution)
        return self

    def resume(self) -> Scorecard:
        """Corrida **nueva y completa** sobre el config vigente (D-SIM-6, D-FLU-3).

        Nada se reutiliza de la corrida anterior: ``run_id``, lineage y evidencia son propios, y
        la anterior queda como respaldo lateral (``.run.old.*``) con su informe.
        """
        return self.run(until=None)

    def summary(self, stage: str | None = None) -> FinalSummary | StageSummary:
        """El resumen final (D-FLU-4) o el de una etapa que ya corrió (D-FLU-2)."""
        if stage is None:
            if self._final is None:
                self._final = build_final_summary(
                    self._study, tuple(self._stage_summaries.values()), self._context()
                )
            return self._final
        if stage not in STAGE_LABELS:
            raise ScorecardInputError(
                f"summary({stage!r}): no existe esa etapa. Etapas: {', '.join(STAGE_LABELS)}."
            )
        resumen = self._stage_summaries.get(stage)
        if resumen is None:
            raise ScorecardInputError(
                f"La etapa «{STAGE_LABELS[stage]}» no corrió todavía: llama a run() primero."
            )
        return resumen

    # ── decidir (D-FLU-3) ───────────────────────────────────────────────────────────────

    def exclude(self, columns: str | Sequence[str], *, reason: str) -> Scorecard:
        """Descarta variables en toda la corrida siguiente, con motivo.

        Escribe ``selection.force_exclude`` —con eso la variable no llega al modelo; un
        ``model.force_exclude`` sobre una variable ya descartada lo rechaza el propio motor— y la
        retira de ``force_include`` en las dos secciones (la última decisión sobre una variable
        gana). La corrida siguiente (``resume()``) emite al trail **un** evento ``decision`` con
        autor ``usuario`` y este motivo; el motor registra aparte la ejecución de la exclusión.
        """
        return self._decidir("exclude", columns, reason=reason)

    def keep(self, columns: str | Sequence[str], *, reason: str) -> Scorecard:
        """Fuerza variables a entrar al modelo, con motivo.

        Escribe ``selection.force_include`` **y** ``model.force_include`` (sólo con la primera,
        ``model`` no vería una variable que ``selection`` descartó por IV, correlación o VIF) y
        las retira de las listas contrarias. Una variable forzada que falle una validación dura
        del motor —signo invertido con la política en ``fail``— sigue fallando: ``keep`` no
        apaga ninguna guarda.
        """
        return self._decidir("keep", columns, reason=reason)

    def _decidir(self, accion: str, columns: str | Sequence[str], *, reason: str) -> Scorecard:
        motivo = str(reason).strip() if reason is not None else ""
        if not motivo:
            raise ScorecardInputError(
                f"{accion}() exige reason=: la decisión queda en el registro de auditoría con su "
                "motivo, y un motivo en blanco no le sirve a quien valide."
            )
        nombres = [columns] if isinstance(columns, str) else [str(c) for c in columns]
        if not nombres:
            raise ScorecardInputError(f"{accion}() necesita al menos una variable.")
        binning = self._config.binning
        predictoras = tuple(binning.feature_columns) if binning is not None else ()
        desconocidas = [c for c in nombres if c not in predictoras]
        if desconocidas:
            raise ScorecardInputError(
                f"{accion}(): {', '.join(desconocidas)} no está entre las predictoras de esta "
                f"corrida ({', '.join(predictoras)})."
            )
        propia = "force_exclude" if accion == "exclude" else "force_include"
        contraria = "force_include" if accion == "exclude" else "force_exclude"
        # `keep` escribe las dos secciones (sólo con `selection`, `model` no vería una variable
        # que la selección descartó). `exclude` escribe SÓLO `selection.force_exclude`: la
        # variable no llega al modelo, y `model` rechaza un override sobre una variable que no
        # está entre las seleccionadas (`model/step.py::_validate_force_overrides`; medido al
        # implementar: la enmienda §3.3 decía «las dos hojas» y está corregida). En las dos
        # secciones se retira de la lista contraria: la última decisión gana.
        escribe_en = ("selection", "model") if accion == "keep" else ("selection",)
        hojas: dict[str, list[str]] = {}
        for seccion in ("selection", "model"):
            actual = getattr(self._config, seccion)
            opuesta = [c for c in getattr(actual, contraria) if c not in nombres]
            campos: dict[str, Any] = {contraria: tuple(opuesta)}
            if seccion in escribe_en:
                lista = [c for c in getattr(actual, propia) if c not in nombres] + nombres
                campos[propia] = tuple(lista)
                hojas[f"{seccion}.{propia}"] = list(lista)
            self._actualizar_seccion(seccion, campos)
        self._decisions.append(
            {
                "regla": "decision_del_usuario",
                "umbral": None,
                "valor": hojas,
                "accion": accion,
                "autor": "usuario",
                "motivo": motivo,
                "variables": nombres,
            }
        )
        self._pending_decisions = True
        self._config, self._steps = self._resolver_pipeline(self._config)
        self._final = None
        self._echo(
            f"Decisión registrada: {accion} {', '.join(nombres)} — «{motivo}». Se aplica en la "
            "corrida siguiente: resume()."
        )
        return self

    def _actualizar_seccion(self, seccion: str, campos: Mapping[str, Any]) -> None:
        """Reconstruye una sección del config con ``campos`` y la vuelve a validar entera."""
        actual = getattr(self._config, seccion)
        volcado = actual.model_dump(mode="python", by_alias=True)
        volcado.update(campos)
        try:
            nueva = type(actual).model_validate(volcado)
        except ValidationError as exc:
            from nikodym.api import _mensaje_de_validacion

            raise ScorecardInputError(
                f"La decisión deja la sección «{seccion}» inválida: {_mensaje_de_validacion(exc)}"
            ) from exc
        self._config = self._config.model_copy(update={seccion: nueva})

    # ── comparar (D-FLU-6) ──────────────────────────────────────────────────────────────

    def compare(self, other: Scorecard) -> StageSummary:
        """Dos corridas lado a lado: cifras clave, variables finales y decisiones humanas."""
        if self._study is None or other._study is None:
            raise ScorecardInputError("compare() necesita que las dos corridas hayan corrido.")
        propio = build_final_summary(self._study, (), self._context())
        ajeno = build_final_summary(other._study, (), other._context())
        # Dos corridas pueden llevar el mismo `name` (el de fábrica, en carpetas distintas): las
        # columnas se rotulan sin ambigüedad o la tabla perdería una de las dos en silencio
        # (pasada de Codex sobre A2).
        mio, suyo = self._name, other._name
        if mio == suyo:
            mio, suyo = f"{self._name} (esta)", f"{other._name} (otra)"
        filas: list[dict[str, Any]] = [
            {"Cifra": "Ejecución", mio: propio.execution, suyo: ajeno.execution},
            {"Cifra": "Validación técnica", mio: propio.validation, suyo: ajeno.validation},
        ]
        mias = dict(propio.figures)
        suyas = dict(ajeno.figures)
        for rotulo in dict.fromkeys([*mias, *suyas]):
            filas.append(
                {"Cifra": rotulo, mio: mias.get(rotulo, "—"), suyo: suyas.get(rotulo, "—")}
            )
        filas.append(
            {
                "Cifra": "Variables finales",
                mio: ", ".join(_variables_finales(self._study)) or "—",
                suyo: ", ".join(_variables_finales(other._study)) or "—",
            }
        )
        filas.append(
            {
                "Cifra": "Decisiones humanas",
                mio: "; ".join(propio.decisions) or "ninguna",
                suyo: "; ".join(ajeno.decisions) or "ninguna",
            }
        )
        filas.append(
            {"Cifra": "Carpeta", mio: str(self._project_dir), suyo: str(other._project_dir)}
        )
        lines = (
            f"{mio}: {propio.execution} · validación técnica {propio.validation}",
            f"{suyo}: {ajeno.execution} · validación técnica {ajeno.validation}",
        )
        return StageSummary(
            stage="compare",
            label=f"Comparación: {mio} frente a {suyo}",
            lines=lines,
            table=pd.DataFrame(filas),
        )

    def _repr_html_(self) -> str:
        if self._final is None:
            return (
                f'<div class="nikodym-summary"><b>Scorecard «{self._name}»</b>: listo para '
                f"correr ({len(self._steps)} etapas). Llama a <code>run()</code>.</div>"
            )
        return self._final._repr_html_()

    def __repr__(self) -> str:
        """Nombre, carpeta y estado de la última corrida."""
        estado = "sin correr" if self._study is None else str(self._study.run_context.status)
        return (
            f"Scorecard(name={self._name!r}, project_dir={str(self._project_dir)!r}, "
            f"estado={estado!r})"
        )

    # ── mecánica ────────────────────────────────────────────────────────────────────────

    def _preparar_proyecto(self) -> None:
        """Crea la carpeta, escribe el config vigente y archiva el informe de la corrida previa."""
        self._project_dir.mkdir(parents=True, exist_ok=True)
        self._config_path.write_text(self.to_yaml(), encoding="utf-8")
        if _tiene_archivos(self._reports_dir):
            shutil.move(str(self._reports_dir), str(self._destino_del_informe_residual()))
        self._reports_dir.mkdir(parents=True, exist_ok=True)

    def _destino_del_informe_residual(self) -> Path:
        """Dónde va el `reports/` que dejó la corrida anterior: junto a SU evidencia.

        El informe se escribe fuera del `run_dir` (§3.1) y hay que archivarlo antes de que
        ``nikodym.run`` aparte la evidencia previa a ``.run.old.*``; nunca se borra nada. Tres
        casos, y el segundo es el que la pasada de Codex sobre A2-bis destapó:

        - `run/` consolidado y sin `reports` dentro: el informe es de esa corrida → `run/reports`,
          y el respaldo lateral se lo lleva completo.
        - `run/` ya lleva su `reports`: el informe residual es de una corrida que FALLÓ después
          de escribirlo y antes de consolidar (su evidencia quedó en ``.run.failed.*``) → va
          dentro del `.run.failed.*` más reciente que aún no tenga informe. Meterlo en `run/`
          mezclaría el informe de una corrida con el trail y el lineage de otra.
        - Sin `run/` (la primera corrida falló tras escribirlo): mismo criterio, y si no hay
          evidencia fallida a la que asociarlo, un hermano `.reports.old.*` independiente.
        """
        archivado_en_run = self._run_dir / _REPORTS_SUBDIR
        if self._run_dir.is_dir() and not archivado_en_run.exists():
            return archivado_en_run
        fallidas = sorted(
            (
                p
                for p in self._project_dir.iterdir()
                if p.is_dir()
                and p.name.startswith(f".{_RUN_SUBDIR}.failed.")
                and not (p / _REPORTS_SUBDIR).exists()
            ),
            key=lambda p: p.stat().st_mtime,
        )
        if fallidas:
            return fallidas[-1] / _REPORTS_SUBDIR
        return _ruta_libre(self._project_dir / f".{_REPORTS_SUBDIR}.old")

    def _preamble(self) -> tuple[tuple[str, dict[str, Any]], ...]:
        """Lo que la corrida declara al trail antes del primer paso.

        La puerta, las inferencias y las decisiones humanas con motivo, en ese orden.
        """
        import nikodym

        entrada = {
            "regla": "puerta_de_entrada",
            "umbral": None,
            "valor": {"puerta": "guiada", "version": nikodym.__version__, "hasta": self._until},
            "accion": "declarar",
            "autor": AUTOR_PUERTA,
            "motivo": "la corrida entró por nikodym.Scorecard; el config completo es la verdad",
        }
        eventos: list[tuple[str, dict[str, Any]]] = [(GUIDED_STEP, entrada)]
        eventos.extend((GUIDED_STEP, inferencia.payload()) for inferencia in self._inferences)
        eventos.extend(
            (GUIDED_STEP, {k: v for k, v in decision.items() if k != "variables"})
            for decision in self._decisions
        )
        return tuple(eventos)

    def _contar_etapa(self, stage: str, study: Any) -> None:
        """Arma y cuenta el resumen de la etapa recién terminada (gancho ``on_step``).

        Un resumen que no se puede armar es un fallo de ESTA corrida, no un detalle: se levanta
        como error de dominio para que el motor lo registre con su etapa y ``nikodym.run``
        devuelva la corrida fallida con el diagnóstico —los artefactos calculados quedan en la
        evidencia—, en vez de declarar «completada» una corrida sin resúmenes (pasada 1 de Codex
        sobre la capa A).
        """
        try:
            resumen = build_stage_summary(stage, study, self._context())
        except Exception as exc:
            raise ScorecardRunError(
                f"El resumen de la etapa «{STAGE_LABELS.get(stage, stage)}» no se pudo armar: {exc}"
            ) from exc
        self._stage_summaries[stage] = resumen
        self._echo(resumen.text(with_table=False))

    def _context(self) -> SummaryContext:
        trail: Path | None = None
        card: Path | None = None
        audit = self._config.audit
        if audit is not None:
            nombre = getattr(audit, "trail_filename", None) or (
                audit.get("trail_filename") if isinstance(audit, Mapping) else None
            )
            trail = self._run_dir / str(nombre or "audit_trail.jsonl")
        if self._config.governance is not None:
            card = self._run_dir / _MODEL_CARD_NAME
        return SummaryContext(
            project_dir=self._project_dir,
            run_dir=self._run_dir,
            source_label=self._source_label,
            partition_label=self._partition_label,
            inference_lines=self._inference_lines,
            decision_lines=tuple(self._lineas_de_decision()),
            report_dir=self._reports_dir,
            trail_path=trail,
            card_path=card,
            config_path=self._config_path,
            until=self._until,
        )

    def _lineas_de_decision(self) -> list[str]:
        lineas: list[str] = []
        for decision in self._decisions:
            variables = ", ".join(decision.get("variables", ()))
            lineas.append(f"{decision.get('accion')} {variables} — «{decision.get('motivo')}»")
        if lineas and self._pending_decisions:
            lineas.append(
                "Hay decisiones posteriores a la última corrida: llama a resume() para aplicarlas."
            )
        return lineas


def _variables_finales(study: Any) -> tuple[str, ...]:
    if study is None or not study.artifacts.has("model", "final_features"):
        return ()
    return tuple(str(v) for v in study.artifacts.get("model", "final_features"))


def _tiene_archivos(ruta: Path) -> bool:
    """Si bajo ``ruta`` hay al menos un archivo (un directorio vacío no es evidencia)."""
    return ruta.is_dir() and any(p.is_file() for p in ruta.rglob("*"))


def _ruta_libre(ruta: Path) -> Path:
    """``ruta`` si no existe; si no, el primer hermano ``<nombre>.<n>`` libre."""
    if not ruta.exists():
        return ruta
    n = 1
    while (candidata := ruta.with_name(f"{ruta.name}.{n}")).exists():
        n += 1
    return candidata


def _comparaciones(partitions: Sequence[str]) -> tuple[str, ...]:
    """Las comparaciones de estabilidad que existen con estas muestras."""
    return tuple(
        c
        for c, muestra in (("dev_vs_holdout", "holdout"), ("dev_vs_oot", "oot"))
        if muestra in partitions
    )


def _config_base() -> dict[str, Any]:
    """El preset F1 (con análisis exploratorio) como punto de partida de los defaults."""
    from nikodym.ui.presets import standard_preset

    return deepcopy(standard_preset()["config"])
