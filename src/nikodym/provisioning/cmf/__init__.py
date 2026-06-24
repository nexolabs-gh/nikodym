"""Motor de provisiones CMF (Chile): ``PE = PI·PDI·Exposición`` (B-1).

**Declarado, no implementado en F0.** Su código llega en F3 (SDD-15). Este módulo existe ya
para que el gate de cobertura regulatoria verifique la existencia del path (criterio Hito 0):
sin él, un ``--cov-fail-under=100`` sobre una lista vacía pasaría ``0/0 = 100 %`` por vacuidad.
Nomenclatura CMF (regla dura D-CONV-1): ``pi``/``pdi``/``pe``, nunca ``pd``/``lgd``/``ead``.
"""
