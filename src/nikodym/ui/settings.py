"""Ajustes de la app web (:class:`UiConfig`) — SDD-23 §4.3, §5(b).

:class:`UiConfig` parametriza **la herramienta** (tema, modo de despliegue, límite de subida,
directorio de trabajo, secciones expuestas), **no** el experimento. Regla dura **D-UI-3**: no es
una sección de :class:`~nikodym.core.config.NikodymConfig`, no se registra como dominio y **no
entra al** ``config_hash``. Cambiar estos ajustes no modifica por sí mismo la identidad de un
experimento; al ejecutar, sin embargo, ``run_pipeline`` cablea una ruta bajo ``workdir`` en
``data.load.source`` y esa ruta sí pertenece al config efectivo. El default relativo preserva una
identidad portable; si el usuario configura un ``workdir`` absoluto, esa ubicación pasa a formar
parte explícita del config. Hereda de
:class:`~nikodym.core.config.NikodymBaseConfig` (``extra='forbid'``, ``frozen=True``).
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from nikodym.core.config import NikodymBaseConfig

__all__ = ["UiConfig"]


class UiConfig(NikodymBaseConfig):
    """Ajustes de la app (NO es sección de NikodymConfig; NO entra al config_hash)."""

    deploy_mode: Literal["local", "demo"] = Field("local", title="Modo de despliegue")
    theme: Literal["light", "dark", "auto"] = Field("auto", title="Tema")
    upload_max_mb: int = Field(200, ge=1, le=2048, title="Tamaño máx. de subida (MB)")
    workdir: str = Field(".nikodym_ui", title="Directorio de trabajo local (runs/datasets)")
    exposed_sections: tuple[str, ...] = Field((), title="Secciones expuestas (vacío = todas)")
    allow_live_execution: bool = Field(
        True, title="Permitir ejecución en vivo (False en demo; R0 en red)"
    )
