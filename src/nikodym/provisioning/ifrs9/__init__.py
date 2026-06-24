"""Motor de provisiones IFRS 9: pérdida crediticia esperada (ECL).

**Declarado, no implementado en F0.** Su código llega en F4 (SDD-16). Aquí vivirán las
implementaciones de ``term_structure()`` / ``metric_sections`` / ``payload`` (puertas de
extensión CT-2); su *shape* interno NO se fija ahora. El módulo existe ya para que el gate de
cobertura regulatoria verifique la existencia del path (criterio Hito 0). Nomenclatura IFRS 9
(D-CONV-1): ``pd``/``lgd``/``ead``.
"""
