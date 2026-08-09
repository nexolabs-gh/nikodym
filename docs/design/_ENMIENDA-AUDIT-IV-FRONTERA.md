# Enmienda SDD — frontera del diagnóstico IV en audit-trail

> **Estado: PROPUESTA; requiere aprobación explícita antes de cambiar el motor.**
>
> **Base medida:** sesión de cierre de prosa del 2026-08-09.
> **Autor / Fecha:** Codex / 2026-08-09.
>
> **Enmienda a:** SDD-06 (`binning`) y su audit-trail.
>
> **No toca:** la fórmula de IV, los bins, el selector ya aprobado con `iv >= max_iv`, CMF,
> D-VIS-6, roadmap ni PyPI.

| Campo | Valor |
|---|---|
| **Problema** | Exactamente IV = 0,50 es `suspicious` y activa `selection.max_iv`, pero no emite el diagnóstico `iv_sospechoso` de binning |
| **Cambio posible** | Un evento de audit adicional en la frontera exacta; no cambia la variable, su IV ni la selección ya calculada |

## 1. Evidencia medida

- `binning.results.iv_band(0.50)` devuelve `suspicious` mediante el intervalo `IV >= 0.50`.
- `selection` activa `high_iv` cuando `iv >= max_iv`.
- `BinningStep._log_summary_diagnostics` emite `iv_sospechoso` sólo con `iv > 0.50`.
- SDD-06 aún documenta el audit como `>0.50`; SDD-07 y el copy de selección ya reflejan `>=`.

Por tanto, una variable con IV exactamente 0,50 queda clasificada y tratada como sospechosa por
dos superficies del motor, pero el audit-trail de la etapa que calculó el IV no registra ese hecho.

## 2. Opciones mutuamente excluyentes

### IV-A1. Alinear el audit a la banda inclusiva `IV >= 0,50` — recomendada

El diagnóstico `iv_sospechoso` se emite al alcanzar o superar 0,50. SDD-06 adopta los mismos
intervalos que `iv_band` y selección.

**Impacto:** cambia el comportamiento observable del audit sólo en el punto exacto 0,50. No filtra,
no elimina y no modifica resultados numéricos. El lineage queda más completo y las tres superficies
comparten una frontera.

### IV-A2. Conservar el audit estricto `IV > 0,50`

SDD-06 declara explícitamente que el evento de audit es más estrecho que la banda `suspicious` y
que el filtro de selección.

**Impacto:** no cambia el motor, pero conserva una excepción difícil de explicar: IV=0,50 es
sospechoso para card y selección, aunque no para el audit de binning. Requiere copy específico para
evitar que un consumidor infiera equivalencia entre banda y evento.

## 3. Gates si se aprueba IV-A1

1. IV=0,50 produce banda `suspicious`, evento `iv_sospechoso` y selección `high_iv`.
2. Un valor inmediatamente inferior no produce el evento; uno superior sí.
3. El evento conserva `accion="diagnosticar_sin_eliminar"` y no muta artefactos.
4. Control negativo: reponer temporalmente `>`; el caso exacto debe quedar rojo por ausencia del
   evento, no por un error de fixture o importación.

## 4. Decisión requerida

Cami debe aprobar **IV-A1** o **IV-A2**. No se programa esta rama antes de esa decisión.
