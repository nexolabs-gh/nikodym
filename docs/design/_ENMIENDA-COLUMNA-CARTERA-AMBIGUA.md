# Enmienda — la columna de cartera ambigua no se elige en silencio

> Estado: **APROBADA por Cami el 2026-08-05**, con D-AMB-5 en su variante de dos capas.
> Detonante: auditoría adversarial previa al release `1.11.0` (2026-08-05).
> Decisiones: **D-AMB-1 … D-AMB-6**.
> Enmienda a: D-JUR-8 (el cambio de default de `provisioning_internal.portfolio_col`) y a la nota
> que ese cambio dejó escrita en `CHANGELOG.md` y en `HANDOFF.md`.

## 1. Problema

D-JUR-8 movió el default de `provisioning_internal.portfolio_col` de `"cmf_portfolio"` a
`"portfolio"`, porque un motor jurisdiccionalmente neutro no puede pedir de fábrica la columna de un
supervisor. La decisión es correcta y **no se re-litiga**.

Lo que se escribió junto a ella sí hay que corregirlo. Tanto el `CHANGELOG` como el `HANDOFF`
afirman que la comprobación previa señala la fricción antes de correr. **Medido: es cierto sólo
cuando la columna nueva no existe.**

| dataset | 1.10.0 | 1.11.0 |
|---|---|---|
| trae sólo `cmf_portfolio` | corre | `InternalInputError: Faltan columnas exigidas … ['portfolio']` ✅ ruidoso |
| trae **`cmf_portfolio` y `portfolio`** | 20 grupos · 840.182,29 | 10 grupos · **839.451,51** · `ok`, **cero errores, cero avisos** 🔴 |

Y `check_dataset` da `compatible=True` en la segunda fila: la columna que el config nombra **existe**,
así que no hay desajuste que reportar. El preflight no está fallando; está contestando bien a otra
pregunta.

🔴 **El caso no es de laboratorio.** `"portfolio"` es también el default de
`provisioning_ifrs9.portfolio_col`, de modo que una institución que corre IFRS 9 **y** provisión
interna sobre un mismo panel tiene las dos columnas **por construcción**. La población exacta en
riesgo es quien en 1.10.0 comparaba estándar contra interno apoyándose en los defaults: al
actualizar, su provisión cambia de agrupación sin que nada se lo diga.

⚠️ La consecuencia no es un error: es **una cifra distinta en un documento auditable, sin rastro**.
Es la misma clase que D-ANC-1 (el ancla descartada en silencio) y que la asignación de partición que
`astype(str)` fabricaba: el motor toma una decisión que el usuario no tomó, y llega a `done`.

## 2. Lo que NO se propone

- **No se revierte el default.** D-JUR-8 está cerrado.
- **No se adivina.** Elegir la columna «más plausible» por nombre, por cardinalidad o por orden es
  exactamente lo que D-COL-3 prohíbe. Si hay dos candidatas, la respuesta es preguntar, no acertar.
- **No se toca `cmf/config.py`.** Su default sigue siendo `"cmf_portfolio"` por D-SEG-9 enmendado;
  la fricción la paga el caso chileno, que es la decisión ya tomada.

## 3. Decisiones

### D-AMB-1 — la ambigüedad es una propiedad del par (config, dataset), no del config

Un `portfolio_col` en su default no es ambiguo por sí solo: lo es **frente a un dataset que trae más
de una columna candidata**. Por eso esto no es un validador de forma —`_check_invariantes` no puede
verlo— sino una exigencia sobre la combinación, que es literalmente la definición de
`requisitos_incumplidos(columnas)` en D-INV-1.

### D-AMB-2 — se declara por el protocolo que ya existe, sin contrato nuevo

`InternalProvisioningConfig` implementa `requisitos_incumplidos(columnas)`. Emite un `Requisito`
cuando se cumplen **las tres** condiciones:

1. el usuario **no declaró** `portfolio_col` (`"portfolio_col" not in self.model_fields_set`);
2. `columnas is not None` —sin los nombres no se afirma nada, D-INV-4—;
3. el dataset trae **`portfolio` y `cmf_portfolio` a la vez**.

Cero campos nuevos, cero cambio de firma, cero movimiento de `config_hash`. Lo consume
`check_dataset`, así que llega **al formulario y al preflight** sin cablear nada en el front.

⚠️ La condición 1 es la que evita el falso positivo caro: quien **declaró** la columna ya tomó la
decisión, y avisarle sería el aviso que se aprende a ignorar.

### D-AMB-3 — el mensaje nombra las dos columnas y la salida, no el problema

El texto dice qué se va a usar, qué otra existe y qué escribir para decidir. Sin código interno de
aviso (regla de copy público) y sin nombrar ninguna jurisdicción: `cmf_portfolio` aparece como el
nombre de una columna del archivo del usuario, no como una norma.

### D-AMB-4 — avisa, no bloquea

Sigue D-INV-3 y D-PRE-5. Un `Requisito` informa; el botón Ejecutar no cambia de estado. La corrida
con dos columnas candidatas **es legítima** —el usuario puede querer exactamente `portfolio`—; lo
que no es legítimo es que nadie se lo haya dicho.

### D-AMB-5 — la ruta por código se cubre con un aviso NO gobernable en la card

**Decisión de Cami (2026-08-05): se cierran las dos rutas.** El preflight cubre al que usa el
formulario; quien corre por código y no llama `check_dataset` no vería nada, y una cifra que cambia
de agrupación tiene que ser explicable **en el documento**, no sólo en la pantalla previa.

Por eso el `engine` registra la ambigüedad como **aviso no gobernable** en la card, con las mismas
tres condiciones de D-AMB-2. Viaja al informe y al audit trail por el canal que las cards ya tienen.

🔴 **No gobernable, y ésa es la mitad importante.** Una marca declarada gobernable **detendría** la
corrida con el default `fail_on_falta_dato=True`, convirtiendo un cambio silencioso en una rotura
para gente que hoy corre bien — dentro de un release *minor*. El criterio de
`core/markers.py::governable_warnings()` es el que decide, y **no se reimplementa con un `if`**.

⚠️ **Tampoco se añade un código al catálogo** (`FALTA-DATO-*` / `DATO-INSTITUCIONAL-*`): esa
numeración es contrato (SDD-16 §6) y sus dos familias significan «lo debe el motor» y «lo debe la
institución». Aquí el motor **no** difirió ninguna capacidad y la institución **ya tiene dónde
escribir el dato**: lo que falta es decirle que hay dos candidatas. Es un aviso de la corrida, no
una carencia declarada.

### D-AMB-6 — el `CHANGELOG` corrige su propia afirmación

La frase que dice que la comprobación previa señala la fricción se acota: **cubre el caso de la
columna ausente, no el de las dos columnas presentes**, y ahora avisa también en el segundo. Una
nota de release que promete una protección que sólo funciona a medias es peor que no prometerla.

## 4. Criterios de aceptación

1. Con `portfolio_col` sin declarar y un dataset con **ambas** columnas, `check_dataset` emite el
   requisito nombrando las dos. **Control negativo obligatorio en los dos sentidos**: con el campo
   **declarado** no emite nada, y con el dataset trayendo **una sola** de las dos tampoco.
2. `config_hash` de los cuatro presets de fábrica, byte a byte idéntico antes y después.
3. El aviso no altera `compatible` ni el veredicto de `check_pipeline`.
4. El mensaje no nombra ninguna jurisdicción ni ningún código interno: lo hace cumplir el gate de
   portada que ya barre los defaults del formulario.
