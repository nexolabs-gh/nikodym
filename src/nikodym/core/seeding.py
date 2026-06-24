"""Siembra determinista del azar para reproducibilidad total (SDD-01 §7, §9).

:class:`SeedManager` deriva el stream de aleatoriedad de cada paso a partir de una única
semilla raíz y del **nombre** del paso, de forma **independiente del orden** de ejecución. La
derivación usa ``hashlib`` (estable entre procesos), nunca el ``hash()`` builtin (aleatorizado
por ``PYTHONHASHSEED``) ni ``SeedSequence.spawn()`` (posicional, dependiente del orden). El
azar **no se serializa**: se reconstruye desde ``root_seed`` (invariante de reproducibilidad).
"""

from __future__ import annotations

import hashlib
import os
import random
import warnings

import numpy as np

__all__ = ["SeedManager"]


class SeedManager:
    """Gestor de semillas determinista por nombre de paso.

    Parameters
    ----------
    root_seed : int
        Semilla raíz del experimento (``config.repro.seed``). Debe ser ``>= 0``
        (``SeedSequence`` rechaza entropía negativa).
    """

    def __init__(self, root_seed: int) -> None:
        self.root_seed = root_seed

    @staticmethod
    def _stable_hash(name: str) -> int:
        """Devuelve un hash entero del nombre, estable entre procesos.

        Usa ``hashlib.sha256`` (determinista cross-proceso), no el ``hash()`` builtin
        (aleatorizado por ``PYTHONHASHSEED``).
        """
        digest = hashlib.sha256(name.encode("utf-8")).digest()
        return int.from_bytes(digest, "big")

    def _seed_sequence(self, name: str) -> np.random.SeedSequence:
        """Construye la ``SeedSequence`` con entropía compuesta ``[root_seed, hash(name)]``."""
        return np.random.SeedSequence(entropy=[self.root_seed, self._stable_hash(name)])

    def generator_for(self, name: str) -> np.random.Generator:
        """Devuelve un ``Generator`` NumPy determinista para el paso ``name``.

        El stream es independiente del orden de los pasos y de los streams de otros nombres.
        """
        return np.random.default_rng(self._seed_sequence(name))

    def int_seed_for(self, name: str) -> int:
        """Devuelve una semilla entera ``uint32`` estable para librerías que exigen ``int``.

        Útil para ``random_state`` de scikit-learn/GBDT. Se deriva de la misma
        ``SeedSequence`` que :meth:`generator_for`, así ambas son coherentes.
        """
        state = self._seed_sequence(name).generate_state(1, dtype=np.uint32)
        return int(state[0])

    def apply_global(self) -> None:
        """Siembra los RNG globales del proceso, siendo honesto sobre sus límites.

        Siembra ``random.seed`` con una semilla derivada y **advierte** si ``PYTHONHASHSEED``
        no está fijo en el entorno (no puede cambiarse en runtime; solo tiene efecto si se fija
        antes de arrancar el intérprete). **No** llama ``np.random.seed`` legacy: el azar de
        NumPy va siempre por ``Generator`` derivado (:meth:`generator_for`).
        """
        hashseed = os.environ.get("PYTHONHASHSEED")
        if hashseed is None or hashseed == "random":
            warnings.warn(
                "PYTHONHASHSEED no está fijo en el entorno; la aleatorización de hash del "
                "proceso vivo no se puede cambiar en runtime. Fíjalo antes de arrancar el "
                "intérprete (p. ej. PYTHONHASHSEED=0) para reproducibilidad plena.",
                stacklevel=2,
            )
        random.seed(self.int_seed_for("python-random"))
