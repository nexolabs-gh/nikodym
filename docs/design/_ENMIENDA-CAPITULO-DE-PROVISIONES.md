# Enmienda — el capítulo de provisiones se emite si hay provisiones, no si hay comparación

> **Estado: APROBADA por Cami (2026-08-05)**, con sus tres decisiones. Escrita antes de programar.
> Alcance:
> `report/document.py` (un `ChapterSpec`) y `report/prose.py` (el titular del capítulo).
> **No toca ningún cálculo, ningún motor, ningún `config_hash`, ni la regla del máximo.**
>
> Origen: pieza 3 de **D-JUR-8**. El defecto se destapó **corriendo** la cadena neutra
> `data → provisioning_internal → report`, no leyendo el código.

---

## 1. Problema

La cadena neutra **ya corre hoy sin una línea de CMF** y llega a `done` con informe — medido:
provisión interna 238.689.868,51 sobre exposición 8.079.005.433,76, 10 grupos, HTML de 48.788 bytes.

🔴 **Pero ese informe no trae el capítulo «Provisiones regulatorias».** La provisión aparece
únicamente en el **Anexo C.2**, entre los parámetros de configuración. Medido sobre el HTML
producido: `"Provisiones regulatorias" in html` → `False`.

**La causa:** `document.py:369-374` gatea el capítulo con `requires_domain="provisioning"` — el
**orquestador**, no los motores. Y el orquestador no puede existir con un solo motor:
`provisioning/config.py:412-416` prohíbe `source_a == source_b` sobre un `Literal` de tres valores
(`:64`). ⇒ **o corres dos motores, o te quedas sin capítulo.**

**Por qué importa ahora y no antes.** Mientras el único uso real de provisiones fuera la comparación
chilena estándar-vs-interno, el orquestador siempre estaba. D-JUR-8 introduce el caso que rompe la
premisa: **un solo motor, el neutro, que es justamente el que hay que poder enseñar.** Un banco
peruano vería su provisión en un anexo técnico en vez de un capítulo de negocio.

---

## 2. 🔴 El mecanismo ya existe, y eso abarata la enmienda entera

La primera lectura sugería un contrato nuevo. **Medido, es falso: `ChapterSpec` ya tiene la variante
*any-of*.**

`document.py:300-306`:

```python
requires_any_domain: tuple[str, ...] = ()
"""Variante *any-of* de ``requires_domain``: el capítulo se emite si **al menos uno** de estos
dominios publicó card. […] un informe que no corrió ninguna etapa de scorecard (p. ej. la cadena
standalone ``data → survival → provisioning_ifrs9``) no debe traer un capítulo «Resultados» vacío.
"""
```

- Implementado en `builder.py:229-230`.
- **Con precedente vivo**: el capítulo «Resultados» ya lo usa (`document.py:349`,
  `requires_any_domain=RESULT_DOMAINS`), y tiene test (`test_report_builder.py:1027`).
- **La tupla que hace falta ya está escrita**: `PROVISION_DOMAINS` (`document.py:153-157`) es
  exactamente `("provisioning", "provisioning_cmf", "provisioning_internal")`, y ya se usa para
  construir las subsecciones del capítulo (`builder.py:299`).

⇒ El gate del capítulo es **una línea**. Lo que no es gratis es el titular (§4).

---

## 3. Lo que NO es el problema, medido

- **No es la regla del máximo.** El `Literal` de tres valores, la prohibición `source_a == source_b`
  y «máximo(estándar, interno)» **no se tocan**. Abrir el orquestador a dos internos es contrato
  aparte y exige su propio SDD; esta enmienda no lo roza.
- **No es el cuerpo del capítulo.** `_domain_subsections` (`builder.py:299`) itera
  `PROVISION_DOMAINS` y **omite** los dominios sin card (`status is None → continue`). Con sólo
  `provisioning_internal` produce **una** subsección, la del método interno. Verificado leyendo el
  bucle; no hay que tocar una línea.
- **No es el Anexo C.** Se construye desde `APPENDIX_PARAMETER_DOMAINS` (`document.py:437`), tupla
  **separada**. No se mueve.
- **No es el `config_hash`.** `report` está en `INFRA_SECTIONS` (`hashing.py:34`), y además aquí no
  nace ningún campo de config.

---

## 4. Decisiones

### D-CAP-1 — El capítulo se gatea por *any-of* sobre los tres dominios de provisiones

`ChapterSpec(id="provisions", …)` pasa de `requires_domain="provisioning"` a
`requires_any_domain=PROVISION_DOMAINS`.

**Efecto:** el capítulo se emite si corrió **cualquiera** de los tres motores. Un informe de
scorecard puro sigue sin traerlo (ninguno de los tres publicó card), que es la garantía que
`requires_domain` daba y que no se pierde.

### D-CAP-2 — 🔴 El titular deja de asumir el orquestador, y ésta es la mitad que sí cuesta

`provisions_intro` (`prose.py:1503`) hace `orq = _card(bundle, "provisioning")` y
**`if orq is None: return ()`**. Con sólo el motor interno el capítulo se emitiría **sin una línea de
introducción**: un título, y debajo directamente la subsección técnica.

Un capítulo mudo es peor que ningún capítulo — y sería exactamente el defecto que esta enmienda dice
cerrar, con otro disfraz.

`provisions_intro` gana una rama para **un solo motor**: cuando no hay orquestador pero sí hay card
de un motor, publica el titular de ese motor —cuánto se provisiona, sobre cuánta exposición, con qué
método— sin nombrar ninguna norma cuando el motor es el neutro.

⚠️ **Y esa rama NO puede citar el Cap. B-1.** `provisioning/internal/engine.py:796-799` ya declara
por qué: *«citando el Cap. B-1 aquí, un usuario de otra jurisdicción recibía una circular chilena en
su PDF»*. La rama nueva hereda esa restricción, y el gate de §6 la hace cumplir.

### D-CAP-3 — El caso «sólo CMF» y el caso «sólo IFRS 9» quedan cubiertos por construcción

D-CAP-1 no privilegia al motor neutro: un informe con **sólo** `provisioning_cmf` también gana su
capítulo, cosa que hoy tampoco tiene. No es alcance añadido — es la consecuencia de gatear por el
hecho («se calcularon provisiones») en vez de por la forma («se compararon dos fuentes»).

⚠️ `provisioning_ifrs9` tiene **su propio capítulo** (`document.py:378-383`,
`requires_domain="provisioning_ifrs9"`) y **no** está en `PROVISION_DOMAINS`. No se toca.

---

## 5. Lo que cambia para un usuario existente

Un config que hoy corre **un solo motor** de provisiones pasa a recibir **un capítulo más** en su
informe. Es aditivo y no altera ninguna cifra, pero **es un cambio de comportamiento del
entregable** y va declarado en el CHANGELOG.

⚠️ **No mueve ningún golden de los presets de fábrica**: los tres declaran el orquestador o no
declaran provisiones, así que su informe ya traía el capítulo o seguirá sin traerlo. A verificar
ejecutando, no asumir.

---

## 6. Criterios de aceptación

1. Un informe de la cadena `data → provisioning_internal → report` **contiene** el capítulo
   «Provisiones regulatorias», con su titular y la subsección del método interno.
2. Ese informe **no nombra** ninguna norma ni jurisdicción en ese capítulo.
3. Un informe de scorecard puro **sigue sin** el capítulo, y la numeración se reajusta sola.
4. Los tres presets de fábrica producen el **mismo** conjunto de capítulos que antes, medido.
5. **Control negativo ejecutado**: revertir D-CAP-1 pone en rojo el gate nuevo, y sólo ése.
6. **Gate probado inyectando el defecto**, no leyéndolo: se comprueba que un titular que cite una
   norma en la rama de un solo motor neutro pone el gate en rojo.
