"""Config de gobernanza e inventario de modelos (SDD-03 §5).

Las ``description`` de esta clase son **copy público** desde D-GOB-13: la sección se pinta en el
formulario de la interfaz y cada descripción es el tooltip de su campo. El texto es el que aprobó
Cami el 2026-09-03 en la tabla §3 de ``_ENMIENDA-GOBERNANZA-EN-PANTALLA.md``, palabra por palabra;
los códigos internos que antes vivían ahí —los tags ``nikodym.*`` del inventario, «SR 11-7»,
«effective challenge»— siguen en los comentarios de al lado, que es donde corresponden.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator

from nikodym.core.config import NikodymBaseConfig

__all__ = ["GovernanceConfig"]

#: Grupos del formulario, en el orden en que se declaran los campos (el motor de formulario ordena
#: los grupos por primera aparición y los campos por ``ui_order`` dentro de cada grupo).
_GRUPO_INVENTARIO = "Inventario"
_GRUPO_FICHA = "Ficha del modelo"
_GRUPO_AJUSTES = "Ajustes manuales"


class GovernanceConfig(NikodymBaseConfig):
    """Documenta el modelo para su gobierno: model card, inventario y diario de overlays.

    Cambiar el propósito, los metadatos de inventario o la política de publicación no altera los
    resultados de la corrida ni su ``config_hash``; el cambio queda registrado en el model card
    y en el audit-trail.
    """

    # Identidad en el inventario: es la clave del MLflow Registry cuando se publica.
    model_name: str = Field(
        default="nikodym-model",
        title="Nombre lógico del modelo",
        description=(
            "Nombre con el que este modelo queda registrado en tu inventario. Si lo publicas a "
            "MLflow, es la clave con la que lo encontrarás ahí."
        ),
        json_schema_extra={
            "ui_widget": "text_input",
            "ui_group": _GRUPO_INVENTARIO,
            "ui_order": 0,
        },
    )
    # El vocabulario es libre a propósito (D-SEG-10): la taxonomía de carteras la fija la
    # institución o el régimen regulatorio que declare, y este campo no gobierna ningún cálculo
    # — su único consumidor lo publica como tag de inventario (`nikodym.cartera`). Cerrarlo en
    # español chileno no era garantía ni dentro del inventario: vuelve del Registry como texto
    # libre, sin revalidar.
    cartera: str | None = Field(
        default=None,
        title="Cartera",
        description=(
            "El segmento de cartera de este modelo, con el nombre que uses en tu institución. Es "
            "descriptivo: no cambia ningún cálculo."
        ),
        json_schema_extra={
            "ui_widget": "text_input",
            "ui_group": _GRUPO_INVENTARIO,
            "ui_order": 1,
        },
    )
    # Separación de motores en el inventario; se publica como tag `nikodym.motor`.
    motor: Literal["scoring", "cmf", "ifrs9"] | None = Field(
        default=None,
        title="Motor",
        description=(
            "Qué motor documenta esta ficha: scoring, provisiones CMF o IFRS 9. Sirve para no "
            "mezclar modelos distintos en el mismo inventario."
        ),
        json_schema_extra={
            "ui_widget": "selectbox",
            "ui_group": _GRUPO_INVENTARIO,
            "ui_order": 2,
        },
    )
    # Fase de construcción del modelo; tag `nikodym.fase`.
    fase: Literal["F0", "F1", "F2", "F3", "F4", "F5", "F6", "F7", "originacion"] | None = Field(
        default=None,
        title="Fase de construcción",
        description=(
            "En qué punto de su construcción está el modelo. Queda escrito en la ficha para que "
            "se lea en contexto."
        ),
        json_schema_extra={
            "ui_widget": "selectbox",
            "ui_group": _GRUPO_INVENTARIO,
            "ui_order": 3,
        },
    )
    # Ciclo de vida del effective challenge; tag `nikodym.estado_validacion`. Es ortogonal a los
    # aliases de despliegue del Registry.
    estado_validacion: Literal["desarrollo", "en_validacion", "validado", "retirado"] = Field(
        default="desarrollo",
        title="Estado de validación",
        description=(
            "En qué punto va la revisión independiente del modelo. Es aparte de si está o no en "
            "producción."
        ),
        json_schema_extra={
            "ui_widget": "selectbox",
            "ui_group": _GRUPO_INVENTARIO,
            "ui_order": 4,
        },
    )
    # Tag `nikodym.autor` del inventario.
    author: str | None = Field(
        default=None,
        title="Autor / responsable",
        description=(
            "Quién responde por este modelo: correo o identificación de la persona o el equipo."
        ),
        json_schema_extra={
            "ui_widget": "text_input",
            "ui_group": _GRUPO_INVENTARIO,
            "ui_order": 5,
        },
    )
    # Declaración de propósito (SR 11-7): obligatoria para el model card y `DATO-INSTITUCIONAL`,
    # por eso no tiene default (D-GOB-8) y la interfaz la pregunta como decisión del usuario
    # (D-GOB-12). Un texto en blanco tampoco es un propósito: ver `_purpose_no_vacio`.
    purpose: str = Field(
        default=...,
        title="Propósito del modelo",
        description=(
            "Para qué se va a usar este modelo y sobre qué cartera decide. Lo escribe tu "
            "institución: el motor no puede inventarlo, y sin esto la ficha del modelo no se "
            "emite."
        ),
        json_schema_extra={"ui_widget": "textarea", "ui_group": _GRUPO_FICHA, "ui_order": 1},
    )
    assumptions: tuple[str, ...] = Field(
        default_factory=tuple,
        title="Supuestos declarados",
        description=(
            "Los supuestos con los que se construyó el modelo. Se copian tal cual a la ficha, "
            "para que quien la lea sepa bajo qué condiciones vale."
        ),
        json_schema_extra={"ui_widget": "text_list", "ui_group": _GRUPO_FICHA, "ui_order": 2},
    )
    limitations: tuple[str, ...] = Field(
        default_factory=tuple,
        title="Limitaciones declaradas",
        description=(
            "Dónde no deberías usar este modelo. Se copian tal cual a la ficha, y son lo primero "
            "que mira una validación independiente."
        ),
        json_schema_extra={"ui_widget": "text_list", "ui_group": _GRUPO_FICHA, "ui_order": 3},
    )
    # `next_review_date = fecha de emisión + este periodo` (SR 11-7).
    review_period_months: int = Field(
        default=12,
        ge=1,
        le=60,
        title="Periodicidad de revisión (meses)",
        description=(
            "Cada cuántos meses toca revisar el modelo. La ficha calcula con esto la fecha de la "
            "próxima revisión, contada desde su emisión."
        ),
        json_schema_extra={
            "ui_widget": "number_input",
            "ui_group": _GRUPO_FICHA,
            "ui_order": 4,
        },
    )
    # Encendido exige el extra `tracking`; apagado, sólo evidencia local.
    publish_to_inventory: bool = Field(
        default=False,
        title="Publicar al inventario",
        description=(
            "Si además de dejar la evidencia en tu carpeta quieres publicar el modelo a un "
            "inventario MLflow. Pide instalar el extra «tracking»; si lo dejas en no, todo queda "
            "local."
        ),
        json_schema_extra={
            "ui_widget": "checkbox",
            "ui_group": _GRUPO_INVENTARIO,
            "ui_order": 6,
        },
    )
    # Nombre del JSONL append-only del diario de escenarios/overlays dentro del directorio del run.
    # 🔴 **No se expone en el formulario** (D-GOB-14): D-GOB-6 decidió no escribir ese archivo
    # porque no tiene productor, y ofrecer el nombre de un archivo que nunca se escribe sería una
    # subsección inerte (D-SUB). El campo sigue en el config para quien lo use por código; el
    # widget `hidden` es el mismo mecanismo con que el formulario omite la fontanería del config.
    scenario_log_filename: str = Field(
        default="scenario_log.jsonl",
        title="Diario de escenarios/overlays",
        description="Nombre del JSONL append-only dentro del directorio del run.",
        json_schema_extra={"ui_widget": "hidden", "ui_group": "General", "ui_order": 0},
    )
    # Encendido, un overlay sin justificación es error: la defensa anti earnings-management.
    require_overlay_justification: bool = Field(
        default=True,
        title="Exigir justificación de overlays",
        description=(
            "Exige escribir el motivo cada vez que alguien ajusta a mano un resultado del modelo. "
            "Un ajuste sin motivo detiene la corrida: es la defensa contra maquillar cifras."
        ),
        json_schema_extra={
            "ui_widget": "checkbox",
            "ui_group": _GRUPO_AJUSTES,
            "ui_order": 1,
        },
    )

    @field_validator("purpose")
    @classmethod
    def _purpose_no_vacio(cls, valor: str) -> str:
        """Un propósito en blanco no es un propósito (D-GOB-12, OK de Cami del 2026-09-07).

        ``purpose`` es obligatorio porque la ficha del modelo no se emite sin él, y hasta aquí un
        texto vacío, de solo espacios o de solo saltos de línea construía: la ficha se firmaba sin
        propósito. Se normaliza con ``strip()`` y se exige al menos un carácter. Es un cambio de
        validación en una superficie experimental (``nikodym.governance``, fuera de la garantía
        SemVer 1.x): un config con ``purpose: ""`` que antes construía deja de hacerlo, y se dice
        en el CHANGELOG.
        El mensaje va en español porque ``/api/validate`` lo pinta junto al campo tal cual.
        """
        limpio = valor.strip()
        if not limpio:
            raise ValueError(
                "El propósito no puede quedar en blanco: escribe para qué se va a usar este "
                "modelo y sobre qué cartera decide."
            )
        return limpio
