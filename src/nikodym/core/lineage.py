"""Modelos de trazabilidad de una corrida: ``LineageBundle`` y ``RunContext`` (SDD-01 §4).

Son metadatos de corrida que el :class:`~nikodym.core.study.Study` puebla en *runtime* (no son
config: no llevan ``frozen``/``extra="forbid"``). :class:`LineageBundle` es la evidencia
reproducible de una corrida (``config_hash``, ``data_hash``, ``root_seed``, versiones, ``git_sha``):
gobernanza en el núcleo (SR 11-7). :class:`RunContext` es el estado de vida de la corrida: arranca
en ``"created"`` y serializa **sin valores ficticios** (DoD F0), de modo que un ``Study`` vacío se
crea, serializa y recarga.

``core`` sólo define la **forma**: el ensamblado del bundle (calcular ``git_sha``, leer ``uv.lock``,
recolectar versiones, congelar ``created_at``) lo hace ``Study.run`` (no aquí); persistir el bundle
es de SDD-03 (gobernanza) y reflejarlo como ``study/lineage.json`` de SDD-04 (tracking), que lo
importan desde ``core``. ``core`` nunca importa tracking.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

__all__ = ["LineageBundle", "RunContext", "RunError"]


class LineageBundle(BaseModel):
    """Bundle de trazabilidad de una corrida (gobernanza en el núcleo, §4 principio 3, SR 11-7).

    Se construye al cierre del *run* (§7 paso 4); ``git_sha``/``data_hash``/``uv_lock_hash`` son
    ``| None`` por ausencia legítima (repo ausente, datos sin cargar, ``uv.lock`` ausente).
    ``data_hash`` es el hash del contenido lógico por bloques (no los bytes del Parquet, decisión
    D2); su cálculo vive en ``data/`` (SDD-02), aquí sólo se declara el campo. ``extra="forbid"``
    rechaza un campo intruso al revalidar el bundle desde disco (``Study.load``).

    ``injected_artifacts`` enumera las claves que entraron desde fuera de la corrida. Su default
    vacío mantiene compatibles los bundles escritos antes de la puerta D-ART-7.
    """

    model_config = ConfigDict(extra="forbid")

    git_sha: str | None
    git_dirty: bool
    data_hash: str | None
    config_hash: str
    root_seed: int
    uv_lock_hash: str | None
    library_versions: dict[str, str]
    determinism_caveats: list[str]
    created_at: datetime
    schema_version: str
    injected_artifacts: tuple[str, ...] = ()


class RunError(BaseModel):
    """Rastro estructurado del fallo que terminó una corrida (enmienda RUN-ERROR, D-ERR-2).

    Existe porque ``status="failed"`` a secas no le sirve a nadie: el diagnóstico del motor se
    emitía **sólo** al audit-trail, de modo que quien corría con el preset recomendado —que trae
    ``audit: null`` y por tanto un ``NullAuditSink``— se quedaba con la palabra ``failed`` y con el
    lineage, que son hashes. Este modelo lleva ese diagnóstico al propio ``RunContext``, que el
    usuario ya tiene en la mano.

    ``message`` guarda ``str(exc)`` **íntegro**, incluido el código de marca cuando el mensaje del
    motor lo trae al frente (``DATO-INSTITUCIONAL-FWD-1: …``): esta es superficie de código, donde
    el código es el dato, igual que en ``warning_codes`` y en el anexo de auditoría del informe. El
    copy público —el panel de la UI— publica el mensaje **sin** el código
    (:func:`~nikodym.core.markers.strip_declared_codes`, D-ERR-4).

    ``is_domain_error`` distingue un :class:`~nikodym.core.exceptions.NikodymError` —mensaje de
    dominio, redactado para un humano— de una excepción inesperada, cuyo texto puede ser un detalle
    interno sin valor para quien usa el formulario (D-ERR-5).

    ``frozen``/``extra="forbid"``: el rastro de un fallo no se reescribe ni admite claves intrusas
    al revalidarlo desde ``run_metadata.json``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    type: str
    message: str
    step: str | None
    is_domain_error: bool
    ts: datetime


class RunContext(BaseModel):
    """Estado de vida de una corrida del ``Study``.

    Arranca en ``"created"`` (``Study`` recién construido, serializable sin correr); ``run()`` lo
    transiciona ``created → running → done|failed`` y le cuelga el :class:`LineageBundle` congelado.
    No es ``frozen`` (``run()`` muta su estado); ``extra="forbid"`` rechaza un campo intruso al
    recargar ``run_metadata.json``.
    """

    model_config = ConfigDict(extra="forbid")

    # run_id/started_at son None hasta run(); así un Study recién construido (status="created")
    # serializa a run_metadata.json SIN valores ficticios (DoD F0: un Study vacío se crea, serializa
    # y recarga).
    run_id: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    status: Literal["created", "running", "done", "failed"] = "created"
    lineage: LineageBundle | None = None
    # Sólo poblado con status="failed" (D-ERR-1). El default None mantiene compatible la recarga de
    # un run_metadata.json escrito antes de la enmienda (D-ERR-7).
    error: RunError | None = None
