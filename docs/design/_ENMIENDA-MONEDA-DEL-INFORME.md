# Enmienda — el informe declara su moneda en vez de suponerla

> **Estado: APROBADA por Cami (2026-08-05).** Escrita antes de programar, según la regla del repo,
> porque **cambia un contrato escrito**: SDD-28 §6.3.10 declara «CLP» como parte del entregable.
> Cami eligió el **default `None`** (D-MON-2) con su coste a la vista, por coherencia con la pieza 1:
> las dos son el mismo defecto y se resuelven en la misma dirección. Alcance: la sección `report` del config y la prosa del informe
> (`report/config.py`, `report/builder.py`, `report/prose.py`). **No toca ningún cálculo, ninguna
> matriz, ningún artefacto y ningún `config_hash`.**
>
> Origen: pieza 2 de **D-JUR-8** ([`_VEREDICTO-NORMATIVA-LOCAL.md`](_VEREDICTO-NORMATIVA-LOCAL.md)
> §4), medida en esta sesión.

---

## 1. Problema

El informe formatea **todo** monto con una sola función, `_clp` (`report/prose.py:2204-2215`), que
tiene el símbolo `"$"` y el separador de miles chileno cableados, y publica en tres sitios la frase
literal «pesos chilenos (CLP)» (`prose.py:1552-1553`, `:1698`, `:1827`) más dos rótulos
`scope="Cartera total · CLP"` (`:306`, `:315`).

🔴 **La consecuencia que importa: es la única fuga de jurisdicción que le queda al motor neutro.**
`provisioning/internal` no nombra ninguna norma —su neutralidad está declarada y defendida en
`provisioning/internal/engine.py:796-799` y `internal/config.py:5-7`— pero su provisión total sale
por `_clp` (`prose.py:1723`). Un banco peruano que corra el motor neutro recibe su provisión **en
formato de peso chileno, en el informe auditable**. Ése es exactamente el hueco que D-JUR-8 abrió.

🔴 **Y ya hay una afirmación FALSA publicada por esta causa.** `prose.py:1827` añade «Los montos van
en pesos chilenos (CLP)» al capítulo **IFRS 9**, que es un marco internacional; el fixture de la
demo pública `web/src/fixtures/demo/report-ifrs9.html` lo lleva escrito. Su dataset es
`ifrs9_retail_latam`, cuya propia descripción publicada dice (`ui/datasets.py:235-236`) que sus
montos son **«AGNÓSTICOS de moneda (sin símbolo; la moneda se rotula en la vista)»**. El informe
afirma una moneda que su fuente declara ausente. Es la misma clase de defecto que el 2026-08-04:
**copy refutado por la fuente que él mismo usa.**

⚠️ **Y el front ya resolvió esto en la dirección contraria, por escrito.**
`web/src/lib/results-format.ts:128-131` declara: *«Los montos IFRS 9 vienen SIN moneda a propósito
(no son CLP): la pantalla los formatea con un símbolo PARAMETRIZABLE. `formatClp` […] sigue siendo
CLP-específico para el dominio CMF chileno; NO se reutiliza aquí para no casar IFRS 9 con pesos
chilenos.»* La pantalla y el informe dicen hoy cosas distintas sobre las mismas cifras.

---

## 2. Lo que NO es el problema, medido

- **No es falta de diagnóstico.** El código ya lo reconoce en **tres** comentarios (`prose.py:303-306`,
  `:1695-1697`, `:1825-1826`). Lo que se eligió entonces fue *rotular* «CLP», no parametrizarlo — y
  rotular una moneda equivocada es peor que no rotularla.
- **No son las tablas del informe.** `renderer._format_float` (`renderer.py:986-1010`) imprime los
  montos **sin símbolo y sin agrupar miles, a propósito y comentado**: son volcado técnico. El
  problema es exclusivamente de la **prosa**.
- **No es el `config_hash`.** `report` está en `INFRA_SECTIONS` (`core/config/hashing.py:34`), así que
  un campo nuevo ahí **no mueve la identidad de ninguna corrida**. Medido, no supuesto.
- **No es multi-moneda.** Una cartera con varias monedas no está en alcance: el motor publica un
  único total y no hay columna con rol monetario ni conversión. Se declara como límite, §6.

---

## 3. Decisiones

### D-MON-1 — La moneda es un campo de PRESENTACIÓN, en `report`, no de dominio

Nace `currency` en `ReportConfig`, hermano de `language` (`report/config.py:370-375`), que es el
precedente exacto: un campo de presentación, en la sección `report`, editable desde el formulario.

🔴 **Por qué `report` y no `provisioning*`, que es donde están las cifras.** Tres razones medidas:

1. **La moneda no cambia ni un decimal del cálculo.** Poner en `provisioning*` un campo que no entra
   en ninguna fórmula movería el `config_hash` de todo config que lo omita —minor con nota SemVer—
   **a cambio de nada**: la identidad de la corrida dejaría de ser la del cálculo.
2. **La misma corrida publica montos de tres motores** (`provisioning_cmf`, `provisioning_internal`,
   `provisioning_ifrs9`). Declararla por motor permite tres monedas contradictorias en un mismo
   documento; declararla una vez en `report` no.
3. **El precedente del repo ya lo decidió**: la portada del entregable vive en `report` y llenarla no
   mueve el hash, «porque el informe es presentación y no cálculo».

### D-MON-2 — El default es `null`, y `null` significa «no declarada», no «CLP»

✅ **Elegida por Cami el 2026-08-05**, con el coste de §5 a la vista.

`currency: CurrencyLabel | None = None`. Con `None`:

- El símbolo pasa a `"$"` **sin rotular país**: la prosa deja de afirmar una moneda que nadie declaró.
- Las tres frases «pesos chilenos (CLP)» y los dos `scope="… · CLP"` **desaparecen** cuando no hay
  moneda declarada, y aparecen con la moneda del usuario cuando la hay.

🔴 **Por qué `None` y no `"CLP"`, aunque `"CLP"` sea más barato en tests.** Porque la doctrina del
repo es que **el motor no inventa un dato institucional**: la moneda de una cartera la sabe la
institución, no Nikodym. Un default `"CLP"` reintroduce exactamente el defecto que esta enmienda
existe para cerrar —el informe afirmando «pesos chilenos» sobre una cartera peruana— sólo que ahora
con un campo al lado que el usuario no sabe que debe tocar. Es la misma forma del `portfolio_col`
chileno de la pieza 1.

⚠️ **No lleva marca declarada.** Se evaluó emitir un `DATO-INSTITUCIONAL-*` cuando la moneda falta y
se descarta: la marca detiene la corrida con `fail_on_falta_dato=True` (su default), y detener un
informe **por una etiqueta de presentación** sería desproporcionado — el documento es correcto sin
ella, sólo menos explícito. Precedente inverso: `FALTA-DATO-IFRS-8` sí detiene, porque ahí lo que
falta cambia la **cifra**.

### D-MON-2-bis — 🔴 Símbolo y moneda son cosas distintas, y confundirlas se vio con un golden

Corregido **al implementar**. La primera versión usaba la moneda declarada como **prefijo** de los
montos, y con un código ISO eso produce `CLP697.376.974`, que no se lee. Lo cazó el golden del HTML
persistido (`test_ui_routes.py`), que exige `$697.376.974`.

**El prefijo es `$` siempre**; la moneda se declara **en prosa**, una vez por capítulo. No es un
apaño para salvar el golden: es la decisión que este informe ya había tomado —está escrita en sus
tres comentarios— *«se rotula en la primera mención de montos del capítulo, no en cada celda, para
no volver ruidosa la tabla»*. `$` marca «esto es dinero» sin afirmar de qué país, que es justo lo
que se necesita cuando nadie declaró moneda.

⚠️ Límite declarado: un informe con `currency="S/"` escribe `$697.376.974` y luego «Los montos van
en S/». Es coherente con lo que el informe hacía con CLP, pero un prefijo por moneda sería mejor;
queda fuera de alcance y anotado.

### D-MON-3 — La prosa lee la moneda por el canal que ya existe, sin tocar una sola firma

`prose.py` recibe únicamente `bundle: ReportInputBundle` y **no tiene acceso al `ReportConfig`**
(`prose.py:207`, `:357`, `:1503`, `:1792`; `builder.py:556-570`). La salida **no** es cambiar 15
firmas: es `bundle.pipeline_params` (`report/results.py:131`), que `prose._params(bundle, dominio)`
(`prose.py:2130-2132`) ya sabe leer, y que se llena recorriendo `_PARAM_DOMAINS`
(`builder.py:161-170`) — donde `"report"` hoy **no está**.

🔴 **Y ese canal resultó ser el equivocado, medido al implementarlo.** El censo afirmaba que
`_PARAM_DOMAINS` y `APPENDIX_PARAMETER_DOMAINS` son tuplas separadas que **ningún gate ata**. El
dato es cierto; la conclusión, falsa: `test_report_builder` recorre `bundle.pipeline_params` y exige
que **cada** dominio recolectado tenga su sección en el Anexo C. Meter `report` allí rompía esa
invariante — y la invariante es correcta, porque cumplirla habría metido la config de
**presentación** en el anexo de **parámetros del pipeline**, que es justo la distinción que
`INFRA_SECTIONS` mantiene.

**Lo que quedó:** un campo propio, `ReportInputBundle.currency`, que el builder llena desde
`ReportConfig`. Dice lo que es, no toca el Anexo C y no obliga a tocar ninguna firma de `prose`.

⚠️ Lección transferible, y es la tercera vez en el repo: **al revisor se le verifica el dato y la
conclusión por separado.** Aquí el dato («son tuplas separadas») era cierto y la conclusión («nada
las ata») era falsa.

### D-MON-4 — `_clp` se retira y nace `_money`, con el símbolo como parámetro OBLIGATORIO

`_clp(value)` → `_money(value, *, symbol)`, sin default. **Sin default a propósito**: es la forma
que el repo ya usó para que un entregable no pueda reintroducir en silencio el valor equivocado
—precedente del botón «Word (.docx)» que decía «esta corrida no generó un PDF»—. Un call site nuevo
que olvide la moneda **no compila**; con default, hereda el peso chileno sin que nadie lo note.

Los 15 call sites (13 líneas de `prose.py`) pasan a leer el símbolo resuelto una vez por capítulo.

### D-MON-5 — La convención numérica NO se toca, y se declara

`_num`, `_pct` y `_miles` (`prose.py:2183-2219`) siguen siendo es-CL (coma decimal, punto de miles),
igual que `renderer._thousands`. **Es coherente mientras `ReportLanguage` sea `Literal["es"]`**: el
informe se escribe en español y su convención numérica es la del idioma, no la de la moneda. Un
informe en soles escrito en español se lee con coma decimal sin ninguna incongruencia.

⚠️ Se declara aquí para que no se lea como olvido. El día que `ReportLanguage` gane un segundo valor,
la convención numérica cuelga del idioma —no de la moneda—, y esta decisión es su ancla.

### D-MON-6 — SDD-28 §6.3.10 se ENMIENDA, no se reinterpreta

Ese punto dice hoy: *«Moneda y unidades explícitas en el informe y la UI: **CLP**, con separador de
miles.»* Se enmienda a: **moneda y unidades explícitas, con la moneda declarada por quien emite el
informe**; `CLP` pasa de ser *la* moneda a ser *el ejemplo* del dataset chileno que ese SDD describe.

🔴 **Su intención se conserva entera** —«una cifra sin unidad es ilegible para quien lee provisiones
en millones»— y es precisamente el argumento a favor de esta enmienda: hoy la cifra tiene una unidad,
y para más de un lector es la **equivocada**, que es peor que no tenerla.

---

## 4. El fixture de la demo, que es el caso incómodo

`web/src/fixtures/demo/report-ifrs9.html` publica hoy «pesos chilenos (CLP)» sobre el dataset
declarado agnóstico. Con D-MON-2 esa frase deja de emitirse.

⚠️ **Actualizar ese fixture NO es recapturar la demo.** Recapturar es correr el motor y regenerar los
tres informes con su lineage, que está fuera del alcance de esta sesión por decisión de Cami. Lo que
esta enmienda exige es que el fixture **deje de afirmar lo que el motor ya no afirma**. Si la única
diferencia entre el fixture y lo que el motor produciría es esa frase, corregirla en el fixture lo
acerca a la verdad en vez de alejarlo.

**Si al implementarlo resulta que la diferencia es mayor que esa frase, el fixture NO se toca y el
desajuste se declara como deuda medida** — un fixture editado a mano que finja ser una corrida es
peor que un fixture desactualizado con su fecha a la vista.

---

## 5. La alternativa que se descarta, con su coste

**Default `"CLP"` en vez de `None`.** Es más barata: no rompe `test_ui_routes.py:753-754` (golden del
HTML persistido), ni `results-format.test.ts:1503-1534`, ni los dos fixtures de la demo. Coste total:
2 asserts.

Se descarta porque **no cierra el problema, lo mueve**: el motor neutro seguiría publicando «pesos
chilenos» de fábrica para todo el que no sepa que existe un campo nuevo, que es la población entera
de usuarios nuevos — y son exactamente ellos el motivo de D-JUR-8. Un default correcto para Chile en
un motor que se presenta como neutro es la misma clase de defecto que el `portfolio_col` de la
pieza 1, y las dos piezas deben resolverse en la misma dirección o el mensaje es incoherente.

---

## 6. Límites declarados

1. **Multi-moneda: fuera de alcance.** Una corrida declara **una** moneda. Nada en el motor convierte
   ni segrega por divisa, y no hay columna con rol monetario. No es un olvido: es alcance no pedido.
2. **Las tablas del cuerpo siguen sin declarar unidad** (`renderer.py:986-1010`), y eso **no mejora**
   con esta enmienda. Hoy se leen por el símbolo de la prosa; mañana también. Declararlo en los
   títulos de tabla (`document.py:273-276`) es trabajo aparte, medido y no incluido.
3. **El front no se unifica aquí.** `results-format.ts` mantiene sus dos políticas
   (`formatClp` CLP-only y `MONEY`/`formatMoney` parametrizable). Unificarlas exige decidir si la
   moneda viaja en la card del motor o sólo en el config del informe, y eso es contrato aparte.

---

## 7. Criterios de aceptación

1. Un informe cuyo config no declara moneda **no contiene** las cadenas «pesos chilenos», «CLP» ni
   ningún rótulo de moneda; sus montos siguen legibles.
2. Un informe con `report.currency` declarada publica **esa** moneda en las cinco superficies de
   prosa, y ninguna otra.
3. **Control negativo ejecutado**: reintroducir el símbolo cableado en `_money` pone en rojo el gate
   nuevo, y sólo ése.
4. **Gate anti-reincidencia**: ninguna superficie de prosa del informe puede nombrar una moneda que
   el config no declaró. Se prueba **inyectando** el defecto, no leyéndolo.
5. `config_hash` de los tres presets **byte a byte idéntico** antes y después, medido.
6. `test_ui_routes.py:753-754` y los fixtures de demo, resueltos según §4 con su decisión escrita.
