"""Motores de provisiones de Nikodym: CMF (Chile) e IFRS 9/ECL.

Son **dos motores separados** (D-ESPEC §5.4): :mod:`nikodym.provisioning.cmf`
(``PE = PI·PDI·Exposición``, B-1) e :mod:`nikodym.provisioning.ifrs9` (ECL). La provisión
final es el **máximo** de ambos (piso prudencial CMF). En F0 estos paths están **declarados**
pero sin implementar: su código llega en F3 (CMF) y F4 (IFRS 9). Existen ya para que el gate de
cobertura regulatoria los encuentre y no pase ``0/0 = 100 %`` por vacuidad.
"""
