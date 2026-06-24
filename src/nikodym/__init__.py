"""Nikodym RiskLib — librería de riesgo de crédito (scoring, ML, provisiones CMF e IFRS 9).

`import nikodym` mantiene el **núcleo liviano**: no arrastra el stack ML pesado, que vive tras
*extras* opcionales con import perezoso (ver :mod:`nikodym.utils.optional`). La superficie
pública de alto nivel se irá re-exportando aquí a medida que se construye la Fundación (F0).
"""

__version__ = "0.1.0"

__all__ = ["__version__"]
