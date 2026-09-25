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
import json
import os
import shutil
import sys
import uuid
from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from typing import IO, Any, Final, Literal

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
    decision_line,
    partition_label,
)
from nikodym.report.prose import _miles, _plural

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
_LOCK_NAME: Final = ".lock"


@dataclass(frozen=True)
class _Target:
    """Las tres reglas del target que la puerta arma, las columnas que las definen y los vacíos.

    Con ``good_rule`` vacía el motor toma por bueno todo lo que no es malo, **incluidos los
    resultados vacíos** (operaciones sin desempeño maduro): entrarían al ajuste como no-default
    sin error alguno (pasada de cierre de Codex sobre la capa A). Un resultado vacío es
    desconocido: queda indeterminado, se puntúa y no entra al ajuste.
    """

    bad_rule: dict[str, Any]
    good_rule: dict[str, Any] | None
    indeterminate_rule: dict[str, Any]
    columnas: tuple[str, ...]
    n_vacios: int


class ScorecardInputError(ConfigError):
    """Lo que la puerta guiada rechaza **antes de correr**.

    Falta una decisión institucional o un argumento no casa con el archivo.
    """


class ScorecardRunError(NikodymError):
    """La corrida terminó fallida y se pidió ``raise_on_error=True`` (D-FLU-4, hallazgo #4).

    También cuando la corrida no pudo empezar porque otra tiene la carpeta del proyecto.
    """


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
        Ruta a un CSV, Parquet o Excel, o un ``pandas.DataFrame``. Los datos se copian al
        proyecto —un archivo, tal cual; un DataFrame, como Parquet— bajo
        ``<run_dir>/<name>/input/`` con su huella en el nombre, y el config referencia esa copia:
        la inferencia y cada corrida leen exactamente los mismos bytes, y ``config.yaml`` +
        ``input/`` reproducen la corrida por sí solos.
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
        self._name = _nombre_de_proyecto(name)
        raiz = Path(run_dir).resolve()
        self._project_dir = (raiz / self._name).resolve()
        if self._project_dir.parent != raiz:
            # Defensa en profundidad tras `_nombre_de_proyecto`: la carpeta del proyecto vive
            # SIEMPRE un nivel bajo `run_dir` (pasada 1 de Codex sobre la capa B).
            raise ScorecardInputError(
                f"name={name!r} sacaría la carpeta del proyecto de run_dir={str(run_dir)!r}."
            )
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
        # El snapshot de los datos, escrito en un temporal al cargar y publicado con su nombre
        # definitivo sólo después de validar todo (pasada 1 de Codex sobre A: nada se pisa ni se
        # deja escrito si el Scorecard no valida).
        self._snapshot_pendiente: tuple[Path, Path] | None = None
        # Huella de los bytes sobre los que se infirió: `run()` la vuelve a medir antes de correr
        # (pasadas 1 y 2 de Codex sobre la capa B: el motor relee el archivo en cada corrida).
        self._source_digest: tuple[Path, str] | None = None
        try:
            frame, source, source_label = self._cargar(data)
            self._construir(
                frame,
                source,
                source_label,
                target=target,
                id=id,
                date=date,
                cohort=cohort,
                partition=partition,
                oot_from=oot_from,
                oot_cohorts=oot_cohorts,
                holdout=holdout,
                purpose=purpose,
                owner=owner,
                review_every=review_every,
                track=track,
                features=features,
                categorical=categorical,
                max_bins=max_bins,
                min_bin_size=min_bin_size,
                monotonic=monotonic,
                min_iv=min_iv,
                max_correlation=max_correlation,
                max_vif=max_vif,
                stepwise=stepwise,
                p_enter=p_enter,
                p_exit=p_exit,
                sign_policy=sign_policy,
                pdo=pdo,
                target_score=target_score,
                target_odds=target_odds,
                anchor=anchor,
                target_pd=target_pd,
                deciles=deciles,
                psi_thresholds=psi_thresholds,
                validation=validation,
                document=document,
                formats=formats,
            )
        except BaseException:
            self._descartar_snapshot()
            raise

    def _construir(
        self,
        frame: pd.DataFrame,
        source: str,
        source_label: str,
        *,
        target: str | _TargetRule,
        id: str | None,
        date: str | None,
        cohort: str | None,
        partition: str | None,
        oot_from: str | None,
        oot_cohorts: Sequence[str] | None,
        holdout: float,
        purpose: str | None,
        owner: str | None,
        review_every: int,
        track: str | Path | None,
        features: Sequence[str] | None,
        categorical: Sequence[str] | None,
        max_bins: int,
        min_bin_size: float,
        monotonic: str | None,
        min_iv: float,
        max_correlation: float,
        max_vif: float,
        stepwise: bool,
        p_enter: float,
        p_exit: float,
        sign_policy: str,
        pdo: float,
        target_score: float,
        target_odds: float,
        anchor: str,
        target_pd: float | None,
        deciles: int,
        psi_thresholds: tuple[float, float],
        validation: Sequence[str] | None,
        document: Mapping[str, str] | None,
        formats: Sequence[str] | None,
    ) -> None:
        """Infiere, arma el config y lo comprueba; el snapshot se publica al final."""
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
        objetivo = self._regla_del_target(frame, target)
        columnas_target = objetivo.columnas
        target_col = "target" if "target" not in frame.columns else "target_nikodym"
        if objetivo.n_vacios:
            inferencias.append(
                Inferencia(
                    regla="inferencia_resultado_vacio",
                    valor={"columnas": list(columnas_target), "filas": objetivo.n_vacios},
                    motivo=(
                        "un resultado vacío es desconocido, no bueno: la fila queda "
                        "indeterminada, se puntúa y no entra al ajuste"
                    ),
                )
            )

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
            n_vacios_target=objetivo.n_vacios,
            columnas_target=columnas_target,
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
                "bad_rule": objetivo.bad_rule,
                "good_rule": objetivo.good_rule,
                "indeterminate_rule": objetivo.indeterminate_rule,
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
        """Da su nombre definitivo al snapshot ya validado todo, sin pisar uno existente."""
        if self._snapshot_pendiente is None:
            return
        snapshot, temporal = self._snapshot_pendiente
        self._snapshot_pendiente = None
        if snapshot.exists():
            temporal.unlink(
                missing_ok=True
            )  # mismo contenido por construcción: el nombre es su hash
            return
        os.replace(temporal, snapshot)

    def _descartar_snapshot(self) -> None:
        """Un Scorecard que no validó no deja su copia a medias en ``input/``."""
        if self._snapshot_pendiente is None:
            return
        _snapshot, temporal = self._snapshot_pendiente
        self._snapshot_pendiente = None
        temporal.unlink(missing_ok=True)
        for carpeta in (temporal.parent, self._project_dir):
            try:
                carpeta.rmdir()  # sólo si quedó vacía: nunca se borra evidencia ajena
            except OSError:
                break

    def _reservar_snapshot(self, contenido: bytes, sufijo: str) -> tuple[Path, Path, str]:
        """Escribe ``contenido`` en un temporal de ``input/``: (definitivo, temporal, huella).

        El nombre definitivo lleva la huella del contenido: otro archivo con el mismo ``name``
        deja un snapshot nuevo y no pisa el que referencia la evidencia de una corrida anterior.
        El temporal conserva la extensión para que el cargador infiera el formato.
        """
        digest = hashlib.sha256(contenido).hexdigest()
        snapshot = self._project_dir / _INPUT_SUBDIR / f"data-{digest[:16]}{sufijo}"
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        temporal = snapshot.with_name(f".data-{digest[:16]}.{os.getpid()}.tmp{sufijo}")
        temporal.write_bytes(contenido)
        self._snapshot_pendiente = (snapshot, temporal)
        self._source_digest = (snapshot, digest)
        return snapshot, temporal, digest

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
            snapshot, _temporal, _digest = self._reservar_snapshot(contenido, ".parquet")
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

        # Un archivo por ruta también se copia al proyecto: la inferencia y cada corrida leen
        # exactamente los MISMOS bytes (un archivo que un proceso externo reemplaza entre la
        # lectura y la corrida ya no puede entrenar otro modelo con inferencias viejas; pasada 2
        # de Codex sobre la capa B), y `config.yaml` + `input/` reproducen la corrida solos.
        contenido = ruta.read_bytes()
        snapshot, temporal, _digest = self._reservar_snapshot(contenido, ruta.suffix.lower())
        try:
            frame = DataLoader.from_config(LoadingConfig(source=str(temporal))).load()
        except NikodymError as exc:
            raise ScorecardInputError(f"No se pudo leer {ruta}: {exc}") from exc
        if frame.empty:
            raise ScorecardInputError(f"El archivo no trae filas: {ruta}")
        return frame, str(snapshot), f"{ruta} (copia en {snapshot})"

    def _verificar_fuente(self) -> None:
        """La corrida lee los mismos bytes sobre los que la puerta infirió, o no corre.

        El config referencia una ruta mutable y el motor la recarga en cada ``run()``; si el
        archivo cambió entre medio, las inferencias (esquema, predictoras, categóricas, muestras)
        describirían otros datos y la corrida entrenaría en silencio otro modelo con el mismo
        config. Aplica también al snapshot de un ``DataFrame``: su nombre lleva la huella, pero un
        archivo editado en disco ya no es el que la puerta escribió.
        """
        if self._source_digest is None:
            return
        ruta, esperado = self._source_digest
        if not ruta.is_file():
            raise ScorecardInputError(
                f"El archivo de datos ya no existe: {ruta}. Construye un Scorecard nuevo."
            )
        if _huella_del_archivo(ruta) != esperado:
            raise ScorecardInputError(
                f"El archivo {ruta} cambió desde que se construyó el Scorecard: las inferencias "
                "se hicieron sobre otro contenido. Construye un Scorecard nuevo sobre el archivo "
                "actual para volver a inferir y correr."
            )

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
    def _regla_del_target(frame: pd.DataFrame, target: str | _TargetRule) -> _Target:
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
            return _Target(
                bad_rule={"all_of": [predicado], "any_of": []},
                good_rule=None,  # bueno es todo lo que no es malo, indeterminado ni excluido
                indeterminate_rule=_regla_de_vacios(columna),
                columnas=(columna,),
                n_vacios=int(frame[columna].isna().sum()),
            )
        columna = str(target)
        if columna not in frame.columns:
            raise ScorecardInputError(
                f"target={columna!r} no es una columna del archivo. Columnas disponibles: "
                f"{', '.join(str(c) for c in frame.columns)}."
            )
        serie = frame[columna]
        malo: Any
        bueno: Any
        if dtype_logico(serie) == "bool":
            malo, bueno = True, False
        else:
            valores = set(pd.unique(serie.dropna()))
            if not valores or not valores <= {0, 1}:
                raise ScorecardInputError(
                    f"target={columna!r} tiene que ser una columna 0/1 (o verdadero/falso); trae "
                    f"otros valores. Para definir «malo» con una condición pasa una regla: "
                    f'target={{"col": "{columna}", "op": ">=", "value": 90}}.'
                )
            malo, bueno = 1, 0
        return _Target(
            bad_rule={"all_of": [{"col": columna, "op": "==", "value": malo}], "any_of": []},
            good_rule={"all_of": [{"col": columna, "op": "==", "value": bueno}], "any_of": []},
            indeterminate_rule=_regla_de_vacios(columna),
            columnas=(columna,),
            n_vacios=int(serie.isna().sum()),
        )

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
            partitions = ("desarrollo",) + (("holdout",) if holdout > 0 else ()) + ("oot",)
            strategy: dict[str, Any] = {
                "type": "temporal",
                "date_col": date,
                "oot_from": str(oot_from),
                "holdout_fraction": float(holdout),
            }
            return _Muestras(
                strategy=strategy,
                partitions=partitions,
                comparisons=_comparaciones(partitions),
                label=partition_label(strategy),
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
            strategy = {
                "type": "cohort",
                "cohort_col": cohort,
                "oot_cohorts": reservadas,
                "holdout_fraction": float(holdout),
            }
            return _Muestras(
                strategy=strategy,
                partitions=partitions,
                comparisons=_comparaciones(partitions),
                label=partition_label(strategy),
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
            strategy = {
                "type": "random",
                "dev_fraction": dev,
                "holdout_fraction": float(holdout),
                "oot_fraction": 0.0,
                "stratify_by": None,
            }
            return _Muestras(
                strategy=strategy,
                partitions=("desarrollo", "holdout"),
                comparisons=("dev_vs_holdout",),
                label=partition_label(strategy),
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
        n_vacios_target: int,
        columnas_target: Sequence[str],
    ) -> tuple[str, ...]:
        fuera = ", ".join(f"{c} ({m})" for c, m in motivos.items())
        lineas = [
            (
                f"Se infirió: esquema de {len(esquema)} columnas ({len(esquema) - n_texto} "
                f"numéricas o de fecha, {n_texto} de texto); {len(predictoras)} "
                f"{_plural(len(predictoras), 'predictora', 'predictoras')} "
                f"({len(categoricas)} {_plural(len(categoricas), 'categórica', 'categóricas')})"
                + (f"; fuera: {fuera}" if fuera else "")
            ),
            f"Identificador: {id_label}",
        ]
        if n_vacios_target:
            lineas.append(
                f"Resultado vacío en {_miles(n_vacios_target)} "
                f"{_plural(n_vacios_target, 'fila', 'filas')} ({', '.join(columnas_target)}): "
                "quedan indeterminadas: no entran al ajuste y la tarjeta las puntúa aparte"
            )
        return tuple(lineas)

    @staticmethod
    def _resolver_pipeline(config: NikodymConfig) -> tuple[NikodymConfig, tuple[str, ...]]:
        """El config con sus secciones coaccionadas y los pasos en orden, comprobados sin correr.

        Un ``NikodymConfig`` recién validado lleva las secciones de dominio **opacas** (``dict``)
        si su capa no está importada; la comprobación del pipeline (D-PIPE-3) las coacciona a su
        clase real, y la puerta se queda con ESE config: es el que corre, el que exporta y el que
        las decisiones humanas editan campo a campo (medido fuera de pytest, donde nadie importa
        los dominios de antemano).
        """
        from nikodym.api import _audit_config, _governance_config, _tracking_config
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
        # Las secciones de infraestructura no son pasos y la comprobación del pipeline no las
        # toca: sin este paso quedan opacas en un intérprete que no importó su capa, y
        # `sc.config.governance.purpose` dependería del orden de import.
        coaccionado = study.config
        tipadas = {
            "audit": _audit_config(coaccionado.audit),
            "governance": _governance_config(coaccionado.governance),
            "tracking": _tracking_config(coaccionado.tracking),
        }
        return coaccionado.model_copy(update=tipadas), tuple(pasos)

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
        """La tabla de decisión de cada etapa que ya corrió (con sus rótulos en español).

        Cada una es un ``DataFrame`` con los números intactos que se muestra como la lee una
        persona —coma decimal, miles, porcentajes—, con la misma regla del resumen de su etapa.
        """
        from nikodym.guided.summaries import TablaDeEtapa

        return {
            etapa: TablaDeEtapa.de(resumen.table, resumen.formats)
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
        :class:`ScorecardRunError` con el mismo diagnóstico (D-FLU-4). La carpeta del proyecto
        admite una corrida a la vez: si otra la tiene, se levanta :class:`ScorecardRunError`
        antes de mover nada.
        """
        if until is not None and until not in self._steps:
            raise ScorecardInputError(
                f"until={until!r} no es una etapa de este pipeline. Etapas: "
                f"{', '.join(self._steps)}."
            )
        pasos = list(self._steps[: self._steps.index(until) + 1]) if until is not None else None
        config = self._config.model_copy(update={"run": RunConfig(steps=pasos)})
        self._verificar_fuente()
        # Un solo escritor por carpeta de proyecto: dos corridas a la vez sobre el mismo
        # `run_dir/name` —los defaults, en dos notebooks— mezclarían informe y evidencia (pasada
        # de cierre de Codex sobre la capa A). El candado lo suelta el sistema operativo si el
        # proceso muere, así que nunca queda uno huérfano.
        self._project_dir.mkdir(parents=True, exist_ok=True)
        try:
            candado = _bloquear_carpeta(self._project_dir / _LOCK_NAME)
        except OSError as exc:
            raise ScorecardRunError(
                f"Otra corrida está en curso en la carpeta '{self._project_dir}' (candado "
                f"'{_LOCK_NAME}'). Espera a que termine, o usa otro name= o run_dir= para "
                "correr en paralelo."
            ) from exc
        try:
            return self._correr(config, until, raise_on_error=raise_on_error)
        finally:
            _liberar_carpeta(candado)

    def _correr(
        self, config: NikodymConfig, until: str | None, *, raise_on_error: bool
    ) -> Scorecard:
        """El intento, ya con el candado de la carpeta tomado."""
        import nikodym

        self._preparar_proyecto()
        self._until = until
        self._stage_summaries = {}
        self._final = None
        # El informe se asocia a su corrida por identidad de intento (pasadas de Codex sobre A2):
        # el `reports/` previo se aparta con el token de este intento y sólo vuelve a moverse al
        # hermano `.run.old.*` que ESTA consolidación cree; si el intento revienta, su propio
        # `reports/` va al `.run.failed.*` que ESTE intento deje, y el previo vuelve a su sitio.
        token = uuid.uuid4().hex[:8]
        previo = self._apartar_informe_previo(token)
        hermanos_antes = self._hermanos_de_corrida()
        try:
            self._study = nikodym.run(
                config,
                run_dir=self._run_dir,
                preamble=self._preamble(),
                on_step=self._contar_etapa,
            )
        except BaseException:
            self._asociar_informe_de_intento_fallido(hermanos_antes)
            self._restaurar_informe_previo(previo)
            raise
        self._archivar_informe_previo(previo, hermanos_antes)
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

        Escribe ``binning.exclude_columns`` (D-EXC-1): la variable no se tramifica, no aparece en
        las tablas y no puede detener la corrida en «Tramos y WoE». La retira de las listas
        forzadas de selección y modelo —las dos rechazan forzar una variable que el binning ya no
        publica— (la última decisión sobre una variable gana). Sus tramos fijados con
        ``set_bins()``/``merge_bins()`` quedan en suspenso, y ``keep()`` los reactiva. La corrida
        siguiente (``resume()``) emite al trail **un** evento ``decision`` con autor ``usuario`` y
        este motivo.
        """
        return self._decidir("exclude", columns, reason=reason)

    def keep(self, columns: str | Sequence[str], *, reason: str) -> Scorecard:
        """Fuerza variables a entrar al modelo, con motivo.

        Escribe ``selection.force_include`` **y** ``model.force_include`` (sólo con la primera,
        ``model`` no vería una variable que ``selection`` descartó por IV, correlación o VIF) y
        las retira de las listas contrarias y de ``binning.exclude_columns``. Una variable forzada
        que falle una validación dura del motor —signo invertido con la política en ``fail``—
        sigue fallando: ``keep`` no apaga ninguna guarda.
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
        # D-EXC-1: `exclude` escribe SÓLO `binning.exclude_columns` —la variable no se tramifica
        # y no puede detener la corrida allí— y la retira de las cuatro listas forzadas: selección
        # y modelo rechazan forzar una variable que el binning no publica (revisión adversarial
        # de la enmienda, pasada 1). `keep` la retira de `binning.exclude_columns` y escribe
        # `force_include` en las dos secciones (sólo con `selection`, `model` no vería una
        # variable que la selección descartó). La última decisión gana.
        hojas: dict[str, list[str]] = {}
        excluidas = [c for c in binning.exclude_columns if c not in nombres] if binning else []
        if accion == "exclude":
            excluidas += nombres
            hojas["binning.exclude_columns"] = list(excluidas)
        self._actualizar_seccion("binning", {"exclude_columns": tuple(excluidas)})
        for seccion in ("selection", "model"):
            actual = getattr(self._config, seccion)
            campos: dict[str, Any] = {
                lista: tuple(c for c in getattr(actual, lista) if c not in nombres)
                for lista in ("force_include", "force_exclude")
            }
            if accion == "keep":
                campos["force_include"] = (*campos["force_include"], *nombres)
                hojas[f"{seccion}.force_include"] = list(campos["force_include"])
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

    # ── tramos: merge_bins / set_bins (§8-9 (a), Cami 2026-09-20) ──────────────────────

    def bins(self, column: str) -> pd.DataFrame:
        """Los tramos de una variable numérica en la última corrida, numerados desde 1.

        Es la tabla con la que se decide ``merge_bins``/``set_bins``: número, rango, filas,
        malos, tasa de malos y WoE, leídos de la tabla de binning que el motor publicó (sin los
        tramos ``Special``/``Missing``, que no tienen corte).
        """
        tabla = self._tabla_de_tramos(column)
        from nikodym.core.tramos import rotulos_por_fila

        bordes = (
            self._study.artifacts.get("binning", "bin_edges")
            if self._study.artifacts.has("binning", "bin_edges")
            else None
        )
        # D-CPY-3: el rango con los bordes efectivos, en es-CL; la etiqueta del motor sigue siendo
        # la clave de todo lo que casa por tramo.
        legibles = rotulos_por_fila(tabla, bordes, column)
        filas: list[dict[str, Any]] = []
        for numero, (_indice, fila) in enumerate(tabla.iterrows(), start=1):
            filas.append(
                {
                    "Tramo": numero,
                    "Rango": legibles[numero - 1],
                    "Filas": int(fila.get("Count", 0)),
                    "Malos": int(fila.get("Event", 0)),
                    "Tasa de malos": float(fila.get("Event rate", float("nan"))),
                    "WoE": float(fila.get("WoE", float("nan"))),
                }
            )
        from nikodym.guided.summaries import TablaDeEtapa

        return TablaDeEtapa.de(
            pd.DataFrame(filas),
            {"Tramo": "int", "Filas": "int", "Malos": "int", "Tasa de malos": "pct", "WoE": "num3"},
        )

    def merge_bins(self, column: str, bins: Sequence[int], *, reason: str) -> Scorecard:
        """Junta dos tramos **adyacentes** de una variable numérica, con motivo.

        Los tramos se numeran como en :meth:`bins` (desde 1). Escribe la hoja
        ``binning.variable_overrides[<column>].user_splits`` con los cortes vigentes menos el
        que separaba esos dos tramos, todos fijados (``user_splits_fixed``): en la corrida
        siguiente el motor tramifica exactamente así y calcula el WoE de los tramos que resultan.
        """
        motivo = self._motivo(reason, "merge_bins")
        cortes = self._cortes_vigentes(column)
        numeros = [int(b) for b in bins]
        if len(numeros) != 2:
            raise ScorecardInputError(
                f"merge_bins() junta exactamente dos tramos adyacentes; recibió {numeros}. "
                f"Los tramos de «{column}» son:\n{self._rangos_en_texto(column)}"
            )
        primero, segundo = sorted(numeros)
        n_tramos = len(cortes) + 1
        if primero < 1 or segundo > n_tramos:
            raise ScorecardInputError(
                f"merge_bins(): el tramo {segundo if segundo > n_tramos else primero} no existe "
                f"en «{column}» ({n_tramos} tramos). Los tramos son:\n"
                f"{self._rangos_en_texto(column)}"
            )
        if segundo != primero + 1:
            raise ScorecardInputError(
                f"merge_bins(): los tramos {primero} y {segundo} de «{column}» no son adyacentes; "
                "el motor sólo junta tramos vecinos (el corte entre ellos es el que desaparece). "
                f"Los tramos son:\n{self._rangos_en_texto(column)}"
            )
        if n_tramos == 2:
            raise ScorecardInputError(
                f"merge_bins(): «{column}» tiene dos tramos; juntarlos dejaría un solo tramo, sin "
                "poder predictivo. Descarta la variable con exclude() o fija otros cortes con "
                "set_bins()."
            )
        nuevos = tuple(c for i, c in enumerate(cortes, start=1) if i != primero)
        return self._fijar_cortes(column, nuevos, accion="merge_bins", motivo=motivo)

    def set_bins(self, column: str, cuts: Sequence[float], *, reason: str) -> Scorecard:
        """Fija los cortes de una variable numérica (los límites entre tramos), con motivo.

        Escribe ``binning.variable_overrides[<column>].user_splits`` con esos cortes, todos
        fijados: en la corrida siguiente el motor tramifica exactamente así. Un tramo fijado que
        viole el tamaño mínimo o la monotonía declarada hace que el motor no tramifique la
        variable, y el resumen de «Tramos y WoE» lo dice.
        """
        motivo = self._motivo(reason, "set_bins")
        self._exigir_corrida("set_bins")
        self._exigir_numerica(column)
        try:
            nuevos = tuple(float(c) for c in cuts)
        except (TypeError, ValueError) as exc:
            raise ScorecardInputError(
                f"set_bins(): los cortes tienen que ser números; recibió {list(cuts)!r}."
            ) from exc
        if not nuevos:
            raise ScorecardInputError("set_bins() necesita al menos un corte.")
        if any(b <= a for a, b in pairwise(nuevos)):
            raise ScorecardInputError(
                f"set_bins(): los cortes tienen que ser estrictamente crecientes; recibió "
                f"{list(nuevos)}."
            )
        return self._fijar_cortes(column, nuevos, accion="set_bins", motivo=motivo)

    def _fijar_cortes(
        self, column: str, cortes: tuple[float, ...], *, accion: str, motivo: str
    ) -> Scorecard:
        """Escribe la hoja de cortes de ``column`` y registra la decisión para el trail."""
        binning = self._config.binning
        if binning is None:  # inalcanzable: `_exigir_numerica` ya lo comprobó
            raise ScorecardInputError("La corrida no tiene sección binning.")
        overrides = [o.model_dump(mode="python") for o in binning.variable_overrides]
        propio = next((o for o in overrides if o.get("name") == column), None)
        if propio is None:
            propio = {"name": column}
            overrides.append(propio)
        propio["user_splits"] = list(cortes)
        propio["user_splits_fixed"] = [True] * len(cortes)
        # Con más tramos fijados que el máximo vigente el solver no tendría solución: el tope
        # propio de la variable sube justo a los tramos que resultan, y queda declarado en la
        # misma hoja.
        tope = propio.get("max_n_bins") or binning.max_n_bins
        if tope is not None and len(cortes) + 1 > tope:
            propio["max_n_bins"] = len(cortes) + 1
        self._actualizar_seccion("binning", {"variable_overrides": overrides})
        vigente = self._config.binning
        assert vigente is not None  # recién validada
        hoja = next(
            o.model_dump(mode="python") for o in vigente.variable_overrides if o.name == column
        )
        self._decisions.append(
            {
                "regla": "decision_del_usuario",
                "umbral": None,
                "valor": {"binning.variable_overrides": [hoja]},
                "accion": accion,
                "autor": "usuario",
                "motivo": motivo,
                "variables": [column],
            }
        )
        self._pending_decisions = True
        self._config, self._steps = self._resolver_pipeline(self._config)
        self._final = None
        self._echo(
            f"Decisión registrada: {accion} {column} → cortes {list(cortes)} — «{motivo}». Se "
            "aplica en la corrida siguiente: resume()."
        )
        return self

    def _motivo(self, reason: str, accion: str) -> str:
        motivo = str(reason).strip() if reason is not None else ""
        if not motivo:
            raise ScorecardInputError(
                f"{accion}() exige reason=: la decisión queda en el registro de auditoría con su "
                "motivo, y un motivo en blanco no le sirve a quien valide."
            )
        return motivo

    def _exigir_corrida(self, accion: str) -> None:
        if self._study is None or not self._study.artifacts.has("binning", "tables"):
            raise ScorecardInputError(
                f"{accion}() decide sobre los tramos de la última corrida: llama a run() primero "
                "(al menos hasta «Tramos y WoE»)."
            )

    def _exigir_numerica(self, column: str) -> None:
        binning = self._config.binning
        predictoras = tuple(binning.feature_columns) if binning is not None else ()
        if column not in predictoras:
            raise ScorecardInputError(
                f"«{column}» no está entre las predictoras de esta corrida "
                f"({', '.join(predictoras)})."
            )
        if binning is not None and column in tuple(binning.categorical_columns):
            raise ScorecardInputError(
                f"«{column}» es categórica: los cortes fijados sólo aplican a variables "
                "numéricas. Para una categórica, agrupa sus niveles antes de cargar los datos."
            )

    def _tabla_de_tramos(self, column: str) -> pd.DataFrame:
        """La tabla de binning de ``column`` sin ``Special``/``Missing``/``Totals``."""
        self._exigir_corrida("bins")
        self._exigir_numerica(column)
        tablas = self._study.artifacts.get("binning", "tables")
        tabla = tablas.get(column) if isinstance(tablas, Mapping) else None
        if not isinstance(tabla, pd.DataFrame):
            raise ScorecardInputError(
                f"«{column}» no quedó tramificada en la última corrida (el resumen de «Tramos y "
                "WoE» dice por qué): no hay tramos que decidir."
            )
        etiquetas = tabla["Bin"].astype(str) if "Bin" in tabla.columns else pd.Series(dtype=str)
        fuera = etiquetas.isin(["Special", "Missing"]) | (tabla.index.astype(str) == "Totals")
        return tabla.loc[~fuera]

    def _cortes_vigentes(self, column: str) -> tuple[float, ...]:
        """Los cortes con que el motor tramificó ``column`` en la última corrida."""
        self._exigir_corrida("merge_bins")
        self._exigir_numerica(column)
        binner = self._study.artifacts.get("binning", "process")
        proceso = getattr(binner, "process_", None)
        try:
            if proceso is None:
                raise AttributeError("el binner no publicó su proceso ajustado")
            variable = proceso.get_binned_variable(column)
        except Exception as exc:
            raise ScorecardInputError(
                f"«{column}» no quedó tramificada en la última corrida (el resumen de «Tramos y "
                "WoE» dice por qué): no hay tramos que juntar."
            ) from exc
        return tuple(float(c) for c in getattr(variable, "splits", ()))

    def _rangos_en_texto(self, column: str) -> str:
        tabla = self.bins(column)
        return "\n".join(f"  {int(f['Tramo'])}: {f['Rango']}" for _, f in tabla.iterrows())

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

    # ── exportar (D-FLU-5) ──────────────────────────────────────────────────────────────

    def export_excel(self) -> tuple[Path, ...]:
        """Un libro Excel por etapa, numerado, en ``<run_dir>/<name>/excel/`` (D-FLU-5, D-SIM-7).

        ``01 Datos y muestras.xlsx`` … ``10 Validación formal.xlsx`` para las etapas que corrieron
        —cada uno con el resumen, la tabla de decisión y las tablas completas que el informe
        publica para ese dominio, con la misma protección de celdas que los exports del informe—
        más ``11 Decisiones.xlsx`` con las decisiones del registro de auditoría (humanas, de la
        puerta y del motor). Opcional: nunca es la vía para ver un resultado. Exige el extra
        ``excel`` (``openpyxl``); sin él se detiene con el comando de instalación.
        """
        from nikodym.guided.export import EXCEL_SUBDIR, write_stage_workbooks

        # Bajo el candado y sobre la evidencia PROPIA: otro Scorecard con el mismo `run_dir/name`
        # puede haber consolidado su corrida en `run/` —el trail que este libro leería—, y este
        # objeto escribiría sus tablas en memoria junto a decisiones ajenas (pasada 3 de Codex
        # sobre la capa B).
        candado = self._tomar_candado("exportar")
        try:
            self._exigir_evidencia_propia("export_excel")
            escritos = write_stage_workbooks(
                self._study,
                self._stage_summaries,
                directory=self._project_dir / EXCEL_SUBDIR,
                report_config=self._config.report,
                trail_path=self._context().trail_path,
            )
        finally:
            _liberar_carpeta(candado)
        self._echo(
            f"Excel por etapa: {len(escritos)} "
            f"{_plural(len(escritos), 'libro', 'libros')} en {self._project_dir / EXCEL_SUBDIR}"
        )
        return escritos

    def export(self, destination: str | Path) -> Path:
        """Empaqueta la carpeta del proyecto en un ``.zip`` (hallazgo #8 de INTEGRACION-EXTERNA).

        Entran el config vigente, el snapshot de datos, la evidencia de la corrida (``run/``), el
        informe y el Excel si se exportó; quedan fuera el candado y los respaldos de corridas
        anteriores. Devuelve la ruta del archivo escrito.
        """
        from nikodym.guided.export import pack_project

        # Una corrida PROPIA, bajo el candado: la carpeta existe desde que un DataFrame publica
        # su snapshot, y un `name` repetido puede encontrar la corrida de otro objeto (pasadas 2
        # y 3 de Codex sobre B).
        candado = self._tomar_candado("empaquetar")
        try:
            self._exigir_evidencia_propia("export")
            ruta = pack_project(self._project_dir, Path(destination))
        except FileNotFoundError as exc:
            raise ScorecardInputError(str(exc)) from exc
        finally:
            _liberar_carpeta(candado)
        self._echo(f"Paquete de la corrida: {ruta}")
        return ruta

    def _tomar_candado(self, accion: str) -> IO[bytes]:
        """El candado de la carpeta del proyecto, o :class:`ScorecardRunError` si otro lo tiene."""
        self._project_dir.mkdir(parents=True, exist_ok=True)
        try:
            return _bloquear_carpeta(self._project_dir / _LOCK_NAME)
        except OSError as exc:
            raise ScorecardRunError(
                f"Otra corrida está en curso en la carpeta '{self._project_dir}': espera a que "
                f"termine antes de {accion}."
            ) from exc

    def _exigir_evidencia_propia(self, accion: str) -> None:
        """La evidencia consolidada en ``run/`` es la de la corrida de ESTE objeto, o no se toca."""
        if self._study is None or self._study.run_context.run_id is None:
            raise ScorecardInputError(
                f"{accion}() trabaja sobre la corrida de este Scorecard: llama a run() primero."
            )
        if _run_id_en_disco(self._run_dir) != self._study.run_context.run_id:
            raise ScorecardInputError(
                f"La evidencia en {self._run_dir} no es la de la corrida de este Scorecard "
                "(otra corrida ocupó la carpeta): vuelve a correr antes de exportar."
            )

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
        """Crea la carpeta del proyecto y escribe el config vigente."""
        self._project_dir.mkdir(parents=True, exist_ok=True)
        self._config_path.write_text(self.to_yaml(), encoding="utf-8")
        self._reports_dir.mkdir(parents=True, exist_ok=True)

    # El informe se escribe fuera del `run_dir` (§3.1) y ``nikodym.run`` sustituye entero su
    # destino al consolidar; asociar cada informe a la evidencia de SU corrida —y sólo a ésa— es
    # lo que las cuatro funciones siguientes garantizan por identidad de intento, nunca por
    # heurísticas sobre qué hay en `run/` (pasadas de Codex sobre A2, A2-bis y A2-ter).

    def _hermanos_de_corrida(self) -> frozenset[str]:
        """Los `.run.old.*` y `.run.failed.*` que existen ahora.

        La diferencia con el censo posterior identifica los que este intento cree.
        """
        return frozenset(
            p.name
            for p in self._project_dir.iterdir()
            if p.is_dir()
            and (
                p.name.startswith(f".{_RUN_SUBDIR}.old.")
                or p.name.startswith(f".{_RUN_SUBDIR}.failed.")
            )
        )

    def _hermanos_nuevos(self, antes: frozenset[str], etiqueta: str) -> list[Path]:
        return sorted(
            p
            for p in self._project_dir.iterdir()
            if p.is_dir()
            and p.name.startswith(f".{_RUN_SUBDIR}.{etiqueta}.")
            and p.name not in antes
        )

    def _apartar_informe_previo(self, token: str) -> Path | None:
        """Aparta el `reports/` de la corrida previa a `.reports.prev.<token>` y deja uno limpio."""
        if not _tiene_archivos(self._reports_dir):
            return None
        apartado = self._project_dir / f".{_REPORTS_SUBDIR}.prev.{token}"
        shutil.move(str(self._reports_dir), str(apartado))
        self._reports_dir.mkdir(parents=True, exist_ok=True)
        return apartado

    def _restaurar_informe_previo(self, previo: Path | None) -> None:
        """La corrida reventó sin consolidar: el informe previo vuelve a `reports/`."""
        if previo is None:
            return
        if _tiene_archivos(self._reports_dir):
            # El informe del intento fallido no encontró evidencia a la que ir (`_asociar_…`
            # lo deja en su sitio si no hay `.run.failed.*`): se conserva aparte, nunca se pisa.
            shutil.move(
                str(self._reports_dir),
                str(_ruta_libre(previo.with_name(f".{_REPORTS_SUBDIR}.old"))),
            )
        elif self._reports_dir.exists():
            shutil.rmtree(self._reports_dir)  # vacío: no es evidencia
        shutil.move(str(previo), str(self._reports_dir))

    def _asociar_informe_de_intento_fallido(self, hermanos_antes: frozenset[str]) -> None:
        """El `reports/` que ESTE intento escribió va con la evidencia `.run.failed.*` que dejó."""
        if not _tiene_archivos(self._reports_dir):
            return
        fallidas = self._hermanos_nuevos(hermanos_antes, "failed")
        if not fallidas:
            return  # sin evidencia fallida: `_restaurar_informe_previo` lo conserva aparte
        shutil.move(str(self._reports_dir), str(fallidas[-1] / _REPORTS_SUBDIR))
        self._reports_dir.mkdir(parents=True, exist_ok=True)

    def _archivar_informe_previo(self, previo: Path | None, hermanos_antes: frozenset[str]) -> None:
        """La corrida consolidó: el informe previo va al `.run.old.*` que ESTA consolidación creó.

        Sin `.run.old.*` nuevo (no había corrida previa consolidada) queda aparte, nunca se pisa.
        """
        if previo is None:
            return
        viejas = self._hermanos_nuevos(hermanos_antes, "old")
        destino = (
            viejas[-1] / _REPORTS_SUBDIR
            if viejas
            else _ruta_libre(previo.with_name(f".{_REPORTS_SUBDIR}.old"))
        )
        shutil.move(str(previo), str(destino))

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
        # El evento lleva también `variables` —el sujeto de la decisión— además de `valor` (la
        # hoja que quedó escrita, acumulada): es lo que la línea «exclude score — «motivo»» del
        # resumen final y de la página ejecutiva del informe necesitan para decirse igual desde
        # el trail que desde la memoria (capa C). Clave aditiva del payload; `DecisionRecord` la
        # ignora como ya ignora `autor` y `motivo`.
        eventos.extend((GUIDED_STEP, dict(decision)) for decision in self._decisions)
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
        if self._config.audit is not None:
            trail = self._run_dir / self._config.audit.trail_filename
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
        lineas: list[str] = [decision_line(decision) for decision in self._decisions]
        if lineas and self._pending_decisions:
            lineas.append(
                "Hay decisiones posteriores a la última corrida: llama a resume() para aplicarlas."
            )
        return lineas


def _variables_finales(study: Any) -> tuple[str, ...]:
    if study is None or not study.artifacts.has("model", "final_features"):
        return ()
    return tuple(str(v) for v in study.artifacts.get("model", "final_features"))


def _run_id_en_disco(run_dir: Path) -> str | None:
    """El ``run_id`` que la evidencia consolidada en ``run/`` declara, o ``None`` si no hay."""
    metadatos = run_dir / "study" / "run_metadata.json"
    if not metadatos.is_file():
        return None
    try:
        valor = json.loads(metadatos.read_text(encoding="utf-8")).get("run_id")
    except (OSError, ValueError):
        return None
    return str(valor) if valor else None


def _nombre_de_proyecto(name: object) -> str:
    """``name`` como un único componente de carpeta, o :class:`ScorecardInputError`.

    Compone ``<run_dir>/<name>``: con ``..``, un separador o una ruta absoluta la carpeta del
    proyecto salía de ``run_dir`` y las corridas escribían, movían y apartaban directorios ajenos
    (pasada 1 de Codex sobre la capa B). Un nombre reservado del sistema (``CON``, ``NUL``) lo
    rechaza el propio sistema operativo al crear la carpeta.
    """
    nombre = str(name).strip() if name is not None else ""
    if not nombre:
        raise ScorecardInputError("name= no puede estar vacío: es el nombre de la versión.")
    if (
        nombre in {".", ".."}
        or "/" in nombre
        or "\\" in nombre
        or Path(nombre).is_absolute()
        or Path(nombre).name != nombre
    ):
        raise ScorecardInputError(
            f"name={name!r} tiene que ser un nombre de carpeta simple, sin separadores, «..» ni "
            "unidad: compone <run_dir>/<name>. Para correr en otro sitio usa run_dir=."
        )
    return nombre


def _huella_del_archivo(ruta: Path) -> str:
    """SHA-256 de los bytes del archivo, por bloques (los archivos de cartera son grandes)."""
    resumen = hashlib.sha256()
    with ruta.open("rb") as archivo:
        for bloque in iter(lambda: archivo.read(1 << 20), b""):
            resumen.update(bloque)
    return resumen.hexdigest()


def _regla_de_vacios(columna: str) -> dict[str, Any]:
    """La regla «resultado vacío → indeterminado» sobre la columna que define el target."""
    return {"all_of": [{"col": columna, "op": "isna", "value": None}], "any_of": []}


def _bloquear_carpeta(ruta: Path) -> IO[bytes]:
    """Candado exclusivo entre procesos sobre el archivo ``ruta`` (vacío, se crea si no existe).

    Levanta ``OSError`` si otro proceso —u otro descriptor— ya lo tiene. El sistema operativo lo
    suelta cuando el proceso termina, muera como muera: no hay candados huérfanos que limpiar.
    """
    handle = ruta.open("a+b")
    try:
        handle.seek(0)
        if sys.platform == "win32":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        raise
    return handle


def _liberar_carpeta(handle: IO[bytes]) -> None:
    """Suelta el candado tomado con :func:`_bloquear_carpeta` y cierra el archivo."""
    try:
        if sys.platform == "win32":
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()


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
