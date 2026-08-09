# Enmienda SDD — resumen PSI coherente y fronteras exactas

> **Estado: APROBADA por Cami (2026-08-09); A1 + B1. Implementación autorizada.**
>
> **Base medida:** `main` = `932cc9dbe146d374974f66e9f6d309daaf360909`.
> **Autor / Fecha:** Codex / 2026-08-09.
>
> **Enmienda a:** SDD-11 (estabilidad), SDD-22 (consumo en validación), prosa del informe y
> serialización de resultados. La frontera elegida también deberá quedar uniforme en selección.
>
> **No toca:** D-VIS-6, el roadmap, CMF, PyPI ni la metodología de cálculo de cada PSI individual.

| Campo | Valor |
|---|---|
| **Problema** | El resumen toma el peor valor entre PSI del score y de la PD, lo llama «PSI del score» y le asigna una banda calculada sólo con el score |
| **Segundo abierto** | El motor clasifica el umbral superior con `>=`, mientras los contratos escritos publican `>` o `≤` |
| **Release** | Extensión aditiva de resultados y cambio semántico del resumen ⇒ minor. No autoriza bump, tag ni publicación |

## 1. Evidencia medida

### 1.1 El valor y la banda describen magnitudes distintas

`_max_psi_by_comparison` conserva `max(score_psi, pd_psi)`, mientras
`_bands_by_comparison` deriva la banda exclusivamente de `score_psi`. El informe consume ambos
campos como si fueran un único dato y publica «PSI del score».

Caso ejecutado contra la base:

| PSI score | PSI PD | valor publicado | banda publicada | texto público |
|---:|---:|---:|---|---|
| 0,05 | 0,12 | 0,12 | Estable | «PSI del score 0,1200 (Estable)» |

El valor 0,12 corresponde a PD y cae en revisión, no en estable. No es un error aislado del copy:
los dos campos agregados del resultado ya son internamente incompatibles.

La discrepancia también es alcanzada por los artefactos demo vigentes. En F1 y F3 la PD tiene el
peor PSI en al menos una comparación, pero el informe lo atribuye al score. HTML, PDF, Word y el
QMD entregado dentro del ZIP conservan esa atribución.

### 1.2 La frontera superior tampoco tiene una única verdad contractual

La función ejecutada usa intervalos semiabiertos:

- `psi < stable_threshold`: estable;
- `stable_threshold <= psi < review_threshold`: revisar;
- `psi >= review_threshold`: redesarrollar.

Con los defaults, exactamente `0,25` se clasifica como redesarrollar. SDD-11, especificaciones y
copy público describen en cambio `0,10–0,25` como revisión y `>0,25` como redesarrollo. Selección y
validación comparten hoy la convención ejecutada `>=`.

## 2. Decisión A — qué representa el resumen PSI

**Decisión aprobada: A1.** Las alternativas se conservan para registrar la elección.

Las opciones son mutuamente excluyentes:

### A1. Peor PSI entre score y PD, con identidad y banda de la misma magnitud — recomendada

El resumen conserva el criterio prudente vigente (`max(score_psi, pd_psi)`), pero cada comparación
se construye como una observación indivisible: valor, banda e identidad (`score_psi` o `pd_psi`).
El informe lo rotula «peor PSI entre score y PD» y nombra cuál ganó. En empate se elige score de
forma determinista. El detalle sigue mostrando ambas series.

**Impacto:** cambia la semántica pública de la banda agregada cuando la PD es peor; añade identidad
al resultado de forma aditiva; corrige card, informe y consumidores con el criterio más prudente.

### A2. Resumen exclusivamente del score

Valor y banda agregados se calculan sólo con `score_psi`; la PD queda en el detalle separado.

**Impacto:** preserva el rótulo actual, pero deja de elevar al resumen un deterioro mayor de la PD y
cambia el significado actual de `max_psi_by_comparison`.

### A3. Sin agregado único

Se eliminan conceptualmente valor y banda únicos: todo consumidor debe presentar por separado PSI
del score y PSI de la PD, cada uno con su banda.

**Impacto:** es la representación menos ambigua, pero exige una migración mayor de API, reportes y
consumidores; no es proporcional a un cierre de prosa.

## 3. Decisión B — frontera exacta del umbral superior

**Decisión aprobada: B1.** Las alternativas se conservan para registrar la elección.

Las opciones son mutuamente excluyentes:

### B1. Conservar la verdad ejecutada: `psi >= review_threshold` redesarrolla — recomendada

Se formalizan intervalos semiabiertos y se corrigen SDD, especificaciones, gráficos y copy. Con los
defaults, `0,10` inicia revisión y `0,25` inicia redesarrollo.

**Impacto:** no cambia el motor; alinea la documentación con una convención ya compartida por
estabilidad, selección y validación. Sí formaliza una metodología pública que hoy está escrita de
otra manera.

### B2. Hacer valer el contrato escrito: sólo `psi > review_threshold` redesarrolla

Exactamente `0,25` permanece en revisión; el motor y todos sus consumidores cambian a esa frontera.

**Impacto:** cambia metodología y resultados en el punto exacto del umbral; requiere modificar y
revalidar los tres motores consumidores, además del copy.

## 4. Contrato propuesto si se aprueban A1 + B1

Para cada comparación se publican conjuntamente:

- `max_psi_by_comparison[comparison]`: mayor valor disponible entre PSI del score y de la PD;
- `psi_metric_by_comparison[comparison]`: identidad de la magnitud ganadora;
- `bands_by_comparison[comparison]`: banda derivada de ese mismo valor;
- detalle existente: ambas magnitudes individuales, sin pérdida de información.

Si sólo una magnitud está disponible, esa magnitud determina el resumen. Si ninguna lo está, no se
fabrica un valor. Los umbrales forman `[−∞, stable)`, `[stable, review)` y `[review, +∞)`.

## 5. Superficies que deberá cerrar la implementación aprobada

- agregación y model card de estabilidad;
- serialización y tipos de resultados;
- ejecutivo, resultados y conclusiones del informe;
- gráficos y leyendas de umbrales en el frontend;
- SDD-11, SDD-22, especificaciones y copy público que exprese las fronteras;
- HTML, PDF, Word y QMD finales, incluidos los artefactos demo si su recaptura recibe una
  autorización separada.

## 6. Gates de aceptación

1. Caso divergente en ambos sentidos: score peor y PD peor. Valor, identidad y banda siempre
   pertenecen a la misma observación.
2. Casos con una magnitud ausente y empate exacto, con resolución determinista.
3. Fronteras exactas `stable_threshold` y `review_threshold` verificadas en estabilidad, selección
   y validación según la opción B aprobada.
4. Ejecutivo, resultados y conclusiones no atribuyen una PD ganadora al score.
5. Gráfico, tooltip y leyenda expresan los mismos operadores que el motor.
6. Control negativo por clase: reinyectar banda basada sólo en score y un operador de frontera
   contrario debe poner el gate correspondiente en rojo por la razón esperada.
7. Verificación del artefacto consumido: resultado JSON, pantalla, HTML, PDF, Word y QMD.

## 7. Autorización y límites

Cami aprobó en la misma decisión A1, B1 y **una única recaptura canónica de la demo** después de
implementar y validar el cambio. No se autoriza publicar PyPI, iniciar D-VIS-6 ni avanzar ningún
nodo del roadmap.
