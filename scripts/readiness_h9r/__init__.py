"""Paquete interno y pasivo del arnés H9R; no forma parte de la API pública.

Los consumidores importan cada submódulo de forma explícita. Mantener este ``__init__`` sin
reexports permite que gates stdlib-only como :mod:`copy_gate` no ejecuten contratos runtime por el
mero hecho de importar el paquete. Ninguna función de este árbol concede autorización START.
"""
