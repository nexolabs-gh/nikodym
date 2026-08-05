# Enmienda — un cotejo dice también QUIÉN lo hizo

> **Estado: APROBADA por Cami (2026-08-05).** Escrita antes de programar. Alcance: el modelo
> `CmfVerification` (`provisioning/cmf/matrices.py`) y el manifiesto del bundle. **Aditiva: cero
> cálculo, cero matrices, cero hashes.** Extiende
> [`_ENMIENDA-COTEJO-NORMATIVO.md`](_ENMIENDA-COTEJO-NORMATIVO.md) (D-COT-1…4), no la sustituye.

---

## 1. Problema

`verifications[]` registra **cuándo**, **cómo**, **qué alcance** y **qué matrices**. No registra
**quién**.

Eso bastaba mientras todos los cotejos fueran de la misma naturaleza. Deja de bastar ahora: **B5 es
validación humana experta** (Cami, celda por celda contra el texto oficial), y ése es precisamente
el trabajo cuya diferencia con un cotejo asistido es el aporte. Registrada sin autor, la entrada
queda **indistinguible** de las dos que ya existen, y un auditor que abra el manifiesto no puede
saber si una matriz la revisó una persona o un script.

⚠️ **Existe `manifest.verifier`**, pero es un texto libre **a nivel de manifiesto entero** —hoy dice
«Extraccion asistida y verificacion visual registrada en docs/…»— así que no puede atribuir una
entrada concreta. Con dos naturalezas de cotejo conviviendo, un autor global es directamente falso.

---

## 2. Decisiones

### D-VER-1 — `CmfVerification` gana `verified_by`, opcional y con default vacío

Cadena libre. **Aditivo puro**: todo manifiesto existente sigue validando sin tocarlo, y las dos
entradas actuales lo dejan vacío hasta que alguien pueda afirmar quién las hizo.

Cadena libre y no un enum de roles: el universo de verificadores no está cerrado —una persona, una
consultora, una auditoría externa— y un `Literal` obligaría a enmendar el modelo cada vez.

### D-VER-2 — Vacío significa «no consta», nunca «anónimo aceptable»

Mismo criterio que `None` en `index_columns` y en `report.currency`: la ausencia de un dato **no se
rellena con una suposición**. Una entrada sin `verified_by` no se presenta como validada por nadie
en particular; simplemente no publica autor.

### D-VER-3 — No se toca `manifest.verifier`

Sigue describiendo la procedencia del bundle como un todo, que es una pregunta distinta de quién
cotejó cada matriz. Retirarlo rompería el gate que lo ata a la ruta del documento, sin ganar nada.

---

## 3. Lo que NO cambia, medido

- **Ningún hash.** El `.sha256` sella el **YAML de matrices**; el manifiesto no está cubierto por
  ningún hash (`matrices.py`, la verificación de carga compara los tres sellos del YAML). Escribir
  en `verifications[]` es libre de identidad — ya se midió al aprobar D-COT-1.
- **Ningún cálculo, ninguna matriz, ningún `config_hash`.**
- **Ningún gate existente**, porque el campo es opcional.

---

## 4. Criterio de aceptación

1. Un manifiesto sin `verified_by` valida igual que hoy.
2. Una entrada con `verified_by` lo conserva en el round-trip del modelo.
3. **Control negativo ejecutado**: declarar un `verified_by` de tipo incorrecto rompe la validación,
   y sólo ahí.
