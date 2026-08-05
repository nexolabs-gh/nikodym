# Enmienda — el manifiesto normativo registra sus COTEJOS, no sólo su extracción

> **Estado: BORRADOR — pendiente de decisión de Cami.** Escrita antes de programar, según la regla
> del repo. Alcance: el manifiesto del bundle CMF (`provisioning/cmf/data/manifest.json`) y su
> modelo (`provisioning/cmf/matrices.py`). **No toca ningún cálculo, ninguna matriz ni ningún hash.**
>
> Origen: el gate `tests/unit/test_normativa_cmf_documento.py`, escrito en esta sesión, lo destapó
> al ejecutarse por primera vez.

---

## 1. Problema

`CmfMatrixManifest` declara **una sola fecha de procedencia**: `extraction_date` (`manifest.json:4`,
hoy `2026-06-23`), que es *cuándo se extrajeron las tablas del PDF oficial*. No tiene dónde registrar
un **cotejo posterior** contra el texto vigente.

🔴 **Y ese cotejo existe, es más fuerte que la extracción, y está escrito sólo en el documento.**
`docs/normativa_cmf_parametros.md:177` registra que el **2026-07-14** las 16 celdas de PI, las 6 de
PDI y el `PI = 100 %` de incumplimiento de la matriz de consumo se contrastaron **una a una** contra
el compendio consolidado, y coinciden exactamente. Eso es un cotejo literal contra el texto vigente,
no una transcripción.

**La consecuencia ya se pagó.** El 2026-08-04 el copy publicado llamó «cotejo cerrado el 2026-06-23»
a lo que el manifiesto llama `extraction_date` — porque era la única fecha que el manifiesto
publica — y la afirmación era **falsa**: existía un cotejo posterior y más fuerte, escrito en el
propio documento que el mismo párrafo enlazaba. Estaba en cinco superficies, incluida la que se
empaqueta en el wheel. Lo cazó un revisor adversarial leyendo la fuente; ninguna suite podía verlo.

⚠️ **El defecto no es el copy: es que el manifiesto no puede decir la verdad.** Mientras la única
fecha publicable sea la de extracción, cualquier superficie que cite el bundle afirmará algo **más
débil de lo que el trabajo sostiene**, y quien intente corregirlo a mano volverá a confundir las dos
cosas.

---

## 2. Lo que NO es el problema

- **No es falta de trabajo de verificación.** El cotejo se hizo y está documentado.
- **No es que el `.md` esté mal.** El documento es correcto y más completo que el manifiesto.
- **No es un hash.** El `.sha256` del bundle cubre el YAML de matrices; el manifiesto no está
  cubierto por ningún hash, y el YAML no se toca aquí. Medido: `test_cmf_matrices.py` sigue verde.

---

## 3. Decisiones

### D-COT-1 — El manifiesto registra los cotejos con su ALCANCE, no sólo su fecha

Nace `verifications: tuple[CmfVerification, ...]` en `CmfMatrixManifest`, con default vacío
(**aditivo**: ningún manifiesto existente deja de validar). Cada entrada declara:

| campo | qué es |
|---|---|
| `date` | fecha ISO del cotejo |
| `method` | cómo se cotejó (p. ej. «render visual del PDF oficial», «cotejo literal celda por celda») |
| `scope` | qué cubrió, en una frase legible |
| `matrix_ids` | las matrices que cubre; vacío = alcance transversal |

🔴 **El `scope` es la mitad importante, no un adorno.** El error del 2026-08-04 fue de **alcance**,
no de fecha: se publicó como cobertura general algo que cubría una matriz. Una lista de fechas
peladas invita a repetirlo exactamente igual, sólo que con la fecha nueva.

### D-COT-2 — `extraction_date` no cambia de significado ni se retira

Sigue siendo *cuándo se extrajeron las tablas*. Un cotejo no es una extracción, y fundirlos es el
error que se está cerrando.

### D-COT-3 — El gate exige que toda fecha de verificación del documento la conozca el manifiesto

Ya implementado en `test_normativa_cmf_documento.py`. Es la dirección documento → manifiesto, y es
la única inversa que el gate hace: la inversa completa daría falsos positivos legítimos (el §7 del
documento lista ocho fuentes y el manifiesto cinco, porque tres son de navegación).

### D-COT-4 — Nada obliga a que las superficies visibles publiquen el cotejo, todavía

Esta enmienda **habilita** que `docs_site/norma-local.md` y el tooltip de `matrices.active_version`
digan la verdad completa; no los cambia. Hacerlo es trabajo de copy con su propio control.

---

## 4. Alternativas consideradas y por qué se descartan

| Opción | Coste | Por qué no |
|---|---|---|
| **A · `verification_dates: tuple[str, ...]`** | 1 campo, 2 valores | Más barata, pero **reintroduce la clase**: sin alcance, el copy vuelve a poder decir «todo verificado el 2026-07-14» cuando ese cotejo cubrió *una* matriz. El defecto de ayer fue de alcance |
| **C · no tocar contrato; el gate lleva una lista de fechas conocidas** | 3 líneas de test | **Tapa el defecto.** El manifiesto seguiría sin saber del cotejo, el copy seguiría citando sólo `extraction_date`, y la próxima corrección a mano volvería a fallar |

---

## 5. Coste medido

- `matrices.py`: una clase `CmfVerification` + un campo con default vacío.
- `manifest.json`: dos entradas (la extracción visual del 2026-06-23 y el cotejo del 2026-07-14).
- El gate ya está escrito; sólo cambia de dónde lee las fechas conocidas.
- **Cero cálculo, cero matrices, cero hashes, cero fixtures del front, cero bundle.**
