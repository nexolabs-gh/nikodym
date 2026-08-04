# Enmienda SDD — el default de `provisioning` no es la regla del B-1

> **Estado:** **aprobada e implementada** (Cami, 2026-08-04, salida C: default correcto **y** título
> derivado).
> **Enmienda a:** [`17-provisioning-orchestration.md`](17-provisioning-orchestration.md) (§5, los
> campos `source_a`/`source_b`/`rule`) y a `ESPECIFICACIONES.md` §5.4.
> **Origen:** GRAVE-3 de [`_CENSO-DEFECTOS-DEL-ABANICO.md`](_CENSO-DEFECTOS-DEL-ABANICO.md) §3.
> **Decisiones:** D-MAX-1 … D-MAX-6.

## 0. El defecto

`ProvisioningConfig()` trae de fábrica `source_a='provisioning_cmf'`, `source_b='provisioning_ifrs9'`
y `rule='max'`. Es decir: **el default publica `max(CMF, IFRS 9)`**.

La regla del **Capítulo B-1 (Circular 2.346)** es `max(método estándar, método interno del banco)`
por institución, y el **Cap. A-2 num. 5** del Compendio **excluye** el deterioro de NIIF 9 sobre
colocaciones y créditos contingentes, cuyos criterios fija la CMF en los Cap. B-1 a B-3
(`ESPECIFICACIONES.md` §5.4, verificado 2026-07-13). `max(CMF, IFRS 9)` **no es una regla de ninguna
norma chilena**: es una comparación entre marcos contables.

⚠️ **El motor no miente sobre la procedencia, y eso es lo que hace el defecto sutil.** `_rule_source`
(`provisioning/orchestrator.py:765-775`) devuelve, con el default, la etiqueta
`_CROSS_FRAMEWORK_RULE_SOURCE`: *«Comparativo entre marcos contables SIN norma chilena que lo exija…»*.
Y la prosa del informe añade que el resultado *«no constituye por sí solo la regla B-1 por
institución»* (`report/prose.py:1620-1623`).

**Pero publica la cifra igual, y el capítulo se titula «La provisión a constituir — la regla del
máximo (Chile)»** — título cableado en `report/document.py:94`, **independiente de `source_b`**. Un
lector ve el titular con «(Chile)», la cifra, y el matiz enterrado en el cuerpo; la etiqueta honesta
vive sólo en el volcado del apéndice C.

La razón escrita del default es **«retrocompatibilidad»** (`provisioning/config.py:31-33`), y la
propia `description` del campo lo dice (`config.py:142-145`): *«El default (provisioning_ifrs9)
preserva el comportamiento histórico; la comparación que EXIGE la norma chilena […] es contra
provisioning_internal»*. **El código sabe cuál es la regla correcta y trae la otra por defecto.**

## 1. Lo que se midió: el coste es MUCHO menor de lo que el censo temía

El censo lo marcó con «⚠️ cambiar el default mueve `config_hash`». Medido, eso es cierto **en
general** y **falso para todo lo que hay en este repo**.

### 1.1 ✅ Ningún preset se mueve, y por una decisión ya tomada

- **F1** y **F4** traen `provisioning: null` (`ui/presets.py:340`, y el bloque de F4): la sección
  no existe, no aporta al hash.
- **F3**, el único que la activa, **escribe los tres campos explícitos** —`source_a`,
  `source_b='provisioning_internal'`, `rule='max'`— porque el repo ya tiene la regla escrita
  (`ui/presets.py:544-546`): *«los campos con default en `None` van explícitos, no omitidos»*,
  precisamente para que el hash no dependa de defaults.

Verificado además en los fixtures: `web/src/fixtures/demo/preset.json:352-353` trae `internal`, y
`results.json` publica `config_hash 857b06ee…` sobre esa configuración.

### 1.2 ✅ El golden por defecto tampoco

`NikodymConfig().provisioning` es `None` (`core/config/schema.py:424`), así que
`GOLDEN_DEFAULT_CONFIG_HASH` (`tests/repro/test_config_hash_golden.py:33`) no incluye los defaults
del sub-schema. **No se mueve.**

### 1.3 ⚠️ A quién SÍ le cambia el hash, dicho sin adornos

A un usuario externo que active `provisioning` **omitiendo `source_b`**. Su config seguiría siendo
válido y su corrida seguiría corriendo, pero **compararía contra otra cosa** y su `config_hash`
—y con él su clave de idempotencia en MLflow— cambiaría. Es exactamente el perfil de cambio que en
este repo va en **minor, nunca en patch** (precedente `1.4.0`).

Como PyPI está en `1.10.0` y no hay release autorizado, el cambio no llega a nadie hasta que Cami
autorice uno; pero la nota de contrato hay que escribirla **cuando se hace**, no cuando se publica.

### 1.4 El coste real es de tests, no de identidad

Cuatro tests de `test_provisioning_step.py` (`:119`, `:138`, `:163` y los `ProvisioningConfig()` sin
argumentos) y el golden de dump de `test_provisioning_config.py:43-74` aseveran el default actual.
⚠️ **El de `:163` no se actualiza: se cae de sentido** —construye `consume_ifrs9=False` sobre un
config donde IFRS 9 ya no sería fuente, y `_check_consumo` lo rechazaría—. Hay que reescribirlo, no
retocarle un valor.

### 1.5 🔴 Y cierra media causa de GRAVE-2

El trabajo «Comparar provisiones (CMF vs. interna)» no activa `provisioning_ifrs9`, así que con el
default **el DAG lo rechaza**. Cambiar el default cierra esa causa sola: el trabajo que se llama
«CMF vs. interna» dejaría de arrancar comparando contra IFRS 9. Está medido en
[`_ENMIENDA-TRABAJO-EJECUTABLE.md`](_ENMIENDA-TRABAJO-EJECUTABLE.md) §1.4.

## 2. Las salidas

### (A) Cambiar el default a `provisioning_internal` *(recomendada)*

El default pasa a ser la comparación que la norma exige.

- ✅ El default de fábrica pasa a ser **la regla correcta**, que es lo que un motor regulatorio debe
  traer puesto: hoy hay que saber que el default está mal para arreglarlo.
- ✅ Cierra media causa de GRAVE-2 sin escribir nada más.
- ✅ Coste medido de identidad: **cero** en este repo (§1.1, §1.2).
- ❌ Cambia comportamiento para quien omita el campo: minor con nota de contrato.
- ⚠️ `provisioning_internal` exige la PD calibrada, así que un config que active `provisioning`
  y no la tenga pasa de correr (contra IFRS 9) a no resolver. **Eso es correcto** —la comparación
  pedida necesita el método interno— pero es un fallo nuevo para una configuración que hoy corre, y
  tiene que decirlo el preflight, no el DAG a mitad de camino.

### (B) Dejar el default y arreglar sólo el TÍTULO

El capítulo deja de decir «la regla del máximo (Chile)» cuando la comparación no es la del B-1.

- ✅ No cambia ninguna cifra, ningún hash, ningún test de identidad.
- ✅ Ataca lo que de verdad engaña al lector: el titular.
- ❌ Deja el default de fábrica publicando una comparación **sin destinatario normativo**, y quien no
  toque el campo sigue obteniéndola.
- ❌ No cierra nada de GRAVE-2.

### (C) Las dos

El default correcto **y** el título que se adapta a la comparación real.

- ✅ Es lo que hace falta para que ninguna de las dos superficies mienta: el default deja de estar
  mal, y el título deja de afirmar «Chile» sobre una comparación que un usuario puede elegir y que
  legítimamente no lo es.
- ⚠️ Coste: el de (A) más un título derivado del config, que toca `report/document.py` y la prosa.

## 3. Las decisiones propuestas *(bajo la salida C)*

**D-MAX-1.** El default de `provisioning.source_b` pasa a **`provisioning_internal`**. La razón
escrita en `config.py:31-33` deja de ser «retrocompatibilidad» y pasa a ser la norma, con su cita.

**D-MAX-2.** **El título del capítulo se deriva de la comparación real.** `report/document.py:94`
deja de cablear «la regla del máximo (Chile)» y usa el mismo criterio que la prosa ya calcula
(`is_b1_binding`: fuentes `{cmf, internal}` **y** `comparison_level='total'`). Cuando no lo es, el
capítulo dice lo que es: un comparativo, sin bandera.

> 🔴 **Es el mismo defecto que D-COL-9 cerró en el mismo archivo**: una frase que se emitía sin
> ninguna condición sobre un config que no la cumplía. El precedente está a doce líneas.

**D-MAX-3.** **El cambio de default se avisa antes de correr, no a mitad del DAG.** Un config que
active `provisioning` con el default nuevo y sin la PD calibrada tiene que verlo en el preflight. El
mecanismo existe y es el mismo que `provisioning_cmf.pd_mapping` ya usa:
`requisitos_incumplidos_por_contexto`.

**D-MAX-4.** **Nota de contrato SemVer.** El cambio va en **minor** con su entrada en el CHANGELOG
diciendo a quién afecta (§1.3) y cómo restaurar el comportamiento anterior en una línea. Precedente:
`1.4.0`.

**D-MAX-5.** **El gate ancla la regla, no el valor.** Un test que sólo compruebe
`source_b == 'provisioning_internal'` se puede «arreglar» invirtiéndolo. El gate afirma la relación:
con las fuentes `{cmf, internal}` y nivel `total`, la etiqueta publicada es la del B-1; con
cualquier otra combinación, **no** lo es y el título no dice «Chile». Se mide en los dos sentidos.

**D-MAX-6.** **Lo que NO se toca:** `rule='max'` sigue siendo el default —es la regla correcta— y
`use_internal` sigue existiendo para la institución con métodos internos no objetados, que el
Cap. B-1 contempla. Tampoco se toca `comparison_level='total'`.

## 4. Alcance declarado

**Fuera:** la asimetría de consolidación (`prose.py:1636-1644`) y el perímetro «una institución por
corrida», que ya están declarados en las etiquetas del orquestador. Esta enmienda cambia **cuál
comparación es la de fábrica** y **qué dice el título**, no cómo se calcula ninguna de las dos.

## 5. Lo que cambió AL PROGRAMARLA

**5.1 🔴 D-MAX-3 queda SIN OBJETO, y se midió antes de escribir una línea.** La enmienda pedía un
aviso previo por `requisitos_incumplidos_por_contexto` para el caso «`provisioning` activo sin la PD
calibrada». Medido ejecutando `check_pipeline` sobre los dos escenarios, **el DAG ya lo cubre entero
y con mejor mensaje**:

```
provisioning_internal apagada  → executable=False
  «El paso 'provisioning' necesita 'result', que produce 'provisioning_internal', y ningún
   paso anterior lo genera: active 'provisioning_internal' antes de 'provisioning'…»

calibration apagada            → executable=False
  «El paso 'performance' necesita 'calibrated_pd_frame', que produce 'calibration'…»
```

Las fuentes de `provisioning` **sí viajan en su `requires`** (`provisioning/step.py:137-153`, que lo
reconstruye desde el config), y lo mismo `provisioning_internal` (`internal/step.py:199-201`).
Declarar un requisito aquí duplicaría un diagnóstico que el DAG ya da mejor —con el orden de los
pasos—, que es **exactamente la razón escrita en `survival/config.py`** para no declarar `model_raw`.
Se conserva la decisión escrita, sin implementación, igual que D-SEG-11: no es un olvido.

**5.2 ⚠️ El coste en tests era 40, no 5.** La medición previa contó cinco tests que aseveraban el
default; al cambiarlo salieron **40 rojos**. La diferencia no es de identidad —ningún hash se
movió— sino de **helpers compartidos**: `test_provisioning_orchestrator.py` construye sus casos con
un `_orchestrator(level, **overrides)` que hereda el default y luego le pasa un resultado de IFRS 9.
Un censo que cuenta *tests que nombran el campo* no ve los que lo heredan por un helper.

**5.3 🔴 El gate nuevo estuvo mal escrito y él mismo lo destapó.** `test_regla_del_maximo` ataba el
título a la etiqueta del lineage con `"B-1" in etiqueta`, y **tres de las cuatro etiquetas mencionan
el B-1** — incluidas las dos que existen para decir que la comparación *no* lo vincula («comparativo
diagnóstico **SIN binding B-1**», y la que cita «Cap. B-1 a B-3» para explicar qué excluye el Cap.
A-2). Buscar un substring en copy público es adivinar. El criterio quedó anclado a las dos constantes
que el orquestador elige cuando la comparación sí vincula.

**5.4 Alcance real de la corrección del título.** `DOMAIN_TITLES` pasa a llevar el título **neutro** y
`domain_title(domain, card)` pone el rótulo del país cuando corresponde. Sin card no se rotula, que
es el tercer estado y el que evita afirmar el país a ciegas en un informe parcial.
