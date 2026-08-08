# Enmienda — la fuente de un cotejo viaja EN PROSA, y por eso el gate no puede exigirla

> Estado: **BORRADOR — pendiente de decisión de Cami**. Escrita el 2026-08-08. Decisiones
> `D-FTE-1…D-FTE-5`.
>
> Enmienda a **D-COT-1** (`_ENMIENDA-COTEJO-NORMATIVO.md`) y a **D-VER-1…3**
> (`_ENMIENDA-COTEJO-VERIFICADOR.md`). Deuda 3 del HANDOFF del 2026-08-07, heredada del 2026-08-05.

## 1. Problema

`CmfVerification` (`provisioning/cmf/matrices.py:108-134`) declara `date`, `method`, `scope`,
`matrix_ids` y `verified_by`. Declara **qué** se cotejó y **quién**, pero no **contra qué documento**:
la fuente viaja dentro de la prosa de `scope`, y el gate normativo tiene que **parsearla del texto
libre** para poder cruzarla (`_ids_citados`, `test_normativa_cmf_documento.py:369`).

**Medido sobre el manifiesto vigente:**

| cotejo | fuente en su prosa | ids que el gate puede extraer |
|---|---|---|
| 2026-07-14 (el más fuerte) | «(fuente `compendio_portal_consolidado`, hojas 16-18)» | 1 |
| 2026-06-23 | «sobre el render del PDF oficial» | **0** |

El del 2026-06-23 no nombra ninguna de las seis `official_sources`. Así que el gate que cruza
`verifications → official_sources` **sólo puede comprobar que lo citado exista, no que todo cotejo
cite algo** — y lo dice por escrito en su propio docstring (`:378-381`), junto con que la salida de
raíz es un campo de contrato que exige esta enmienda.

🔴 **La consecuencia es de auditoría, no de estilo.** Un auditor que lea la tabla de cotejos del
cotejo más antiguo no puede llegar al documento contra el que se verificó, y el mecanismo que existe
para llevarlo ahí —el cruce del gate— depende de que alguien escriba el id **dentro de una frase**.
Eso es el mismo patrón que costó la afirmación falsa del 2026-08-04: un dato que sólo consta en prosa
no lo puede vigilar nada, y la prosa se degrada al reescribirse (la fórmula de recuperos del
2026-08-07 se degradó exactamente así, pasando de una `description` correcta a una frase invertida).

## 2. Por qué el mecanismo existente no alcanza

No es un olvido, y conviene decirlo porque cambia la forma de la salida:

1. **`matrix_ids` es el precedente y NO sirve aquí.** Ata el cotejo a lo cotejado, no a la evidencia.
   Son dos preguntas distintas: *qué* verifiqué y *contra qué*.
2. **`CmfManifestMatrixEntry` ya declara su fuente estructuralmente** (`source_ref`,
   `matrices.py:91`). O sea: el manifiesto **ya sabe** declarar una procedencia por campo, y los
   cotejos son la única entidad que no lo hace. La asimetría es el defecto.
3. **`manifest.verifier` no es reutilizable** por la misma razón que D-VER-3 escribió para
   `verified_by`: es texto libre del manifiesto entero.
4. **Parsear la prosa no se puede endurecer sin esto.** Exigir «todo `scope` cita un id» pondría el
   gate rojo sobre el cotejo del 2026-06-23, y ese rojo **no se arregla en el gate**: se arregla
   declarando un dato que hoy nadie tiene registrado. Un gate que sólo se puede apagar editando el
   dato es el antipatrón que este repo ya pagó («cerrar una clase editando el dato no la cierra»).

## 3. Decisiones

### D-FTE-1 — `CmfVerification` gana `source_ids: tuple[str, ...]`, con default vacío

Los ids de las `official_sources` contra las que se hizo el cotejo, declarados como **datos** y no
extraídos de una frase. Aditivo: `extra="forbid"` sigue en pie y el campo tiene default, así que el
manifiesto vigente valida sin tocarlo.

### D-FTE-2 — Vacío significa «NO CONSTA», nunca «sin fuente»

Copia literal del criterio de **D-VER-2** para `verified_by`, y por la misma razón: un cotejo sin
fuente registrada y un cotejo hecho contra nada son cosas distintas, y el manifiesto es el sitio
donde esa diferencia se lee. El precedente más amplio del repo es el mismo: `None` en
`index_columns` y en `distinct_count` significa «no se sabe», no «no hay».

🔴 **Corolario que es la mitad del valor de la enmienda: la ausencia se PUBLICA.** Un `source_ids`
vacío no puede quedar invisible, porque entonces «no consta» y «nadie miró» vuelven a leerse igual —
que es la trampa que esta sesión ya pagó una vez con un `grep` sobre un archivo no descargado. El
documento normativo lo declara con su razón, igual que el bundle declara sus `pending_items`.

### D-FTE-3 — La fuente del cotejo del 2026-06-23 NO se infiere: se declara o se deja constar

`official_sources` incluye `pdf_semilla_b1`, y su `method` dice «el render del PDF oficial». La
inferencia es plausible **y no se hace**: declarar una procedencia que nadie registró es fabricar
evidencia de auditoría, que es el defecto exacto que la revisión adversarial del 2026-08-07 encontró
en la traza (`step.py` registraba una procedencia falsa). Sólo hay dos salidas legítimas y las dos
son de Cami, que es quien hizo la extracción:

- **(a)** recuerda contra qué documento fue y lo declara → `source_ids: ["<id>"]`;
- **(b)** no consta → `source_ids: []` y el documento lo dice.

⚠️ **Esta es la única pregunta abierta de la enmienda.** El resto es implementable sin ella.

### D-FTE-4 — El gate deja de parsear prosa para el cruce, y `_COTEJOS_QUE_CITAN_FUENTE` se deriva

Con el campo puesto, el cruce `verifications → official_sources` pasa a leer `source_ids`, y la tabla
escrita a mano que hoy ata el cotejo del 2026-07-14 a su fuente
(`test_normativa_cmf_documento.py:396`) **se deriva del manifiesto** en vez de repetirlo. Un oráculo
que reimplementa lo que vigila mide determinismo, no corrección — precedente ya escrito en este repo.

⚠️ **Pero el parseo de prosa NO se borra**, y esto es deliberado: se conserva como **cara redundante**
con su papel invertido. Hoy es la única vía; pasa a comprobar que la prosa y el campo **no se
contradigan**, o sea que nadie declare `source_ids: [x]` mientras el `scope` afirma haberse cotejado
contra `y`. Es el mismo patrón con que el 2026-08-07 se ató la frase de recuperos a su aritmética.

### D-FTE-5 — Exigir fuente a todo cotejo NUEVO, no a los existentes

El gate exige `source_ids` no vacío para cualquier cotejo cuya fecha sea posterior a los dos
registrados hoy, y los dos actuales quedan como excepción **enumerada con su razón**, no por una
holgura de conteo (la holgura fue lo que dejó inerte el gate normativo del 2026-08-05: `len(...) >= 5`
con 6 declaradas). Así B5 —que es el próximo cotejo y lo hace Cami— nace obligado a declarar su
fuente **y** su `verified_by`, que es la deuda 7 del HANDOFF, sin que esto ponga rojo nada existente.

## 4. Coste, medido

| qué | medido |
|---|---|
| `config_hash` | **cero**: el manifiesto no entra en la canonicalización del config |
| `yaml_sha256` | **cero**: es el hash del **YAML de matrices**, no del manifiesto (`matrices.py:235`) |
| card / lineage | **cero**: `step.py:140` y `engine.py:2019` publican campos concretos, no el manifiesto entero |
| matrices, cálculo, PE | **cero**: la enmienda no toca una sola cifra |
| gates a tocar | `test_normativa_cmf_documento.py` (el cruce y su tabla), `test_cmf_verificador.py` |
| documento | `docs/normativa_cmf_parametros.md`: publicar la fuente de cada cotejo y, si aplica, su ausencia |

## 5. Lo que esta enmienda NO hace

- **No re-litiga nada de la normativa local.** CMF sigue siendo el caso de referencia, congelado, en
  la evidencia. Esto sólo hace auditable la procedencia de sus cotejos.
- **No cambia ninguna matriz, ni ningún hash, ni ninguna cifra publicada.**
- **No valida el bundle ante la CMF.** La Comisión no certifica implementaciones de terceros, y el
  `scope` del 2026-07-14 ya lo dice.
- **No resuelve la pregunta de vigencia de B5** —que 8 de las 10 matrices salen de un PDF «vigente
  hasta 31-12-2021» cuyo sucesor está *«revalidacion pendiente»*—. Ése es un problema de **vigencia**,
  no de procedencia, y sigue abierto tal cual.
