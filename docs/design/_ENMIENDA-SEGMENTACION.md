# Enmienda SDD — la llave de segmentación gana dominio y régimen declarados

> **Estado: APROBADA (Cami, 2026-07-25).** El alcance fue reencuadrado con su OK tras medir el código: B3.a-1 tal como estaba escrito en el ROADMAP no desbloquea el
> contrato de resolución de parámetros, porque lo que supuestamente bloqueaba ya está desbloqueado.
> Esta enmienda **reemplaza** la definición de B3.a-1 por el trabajo que sí bloquea.
>
> **Base:** `main` = `913e232` (CI verde).
> **Autor / Fecha:** DanIA / 2026-07-25.
> **Revisión:** dos revisores adversariales independientes (hechos y diseño) sobre el borrador
> anterior. Sus hallazgos están incorporados; §6 registra lo que cambió y por qué.

| Campo | Valor |
|---|---|
| **Problema** | La llave de segmentación es un `str` sin dominio declarado en ninguna parte, y cada motor le impone una política distinta. No se puede montar «un parámetro se resuelve por segmento» sobre un segmento que nadie define |
| **Enmienda a** | SDD-15 (§ carteras del motor CMF), SDD-16 (§ `portfolio_col` de IFRS 9), SDD-17 (orquestación y crosswalk), SDD-03 (§5 `cartera` de governance), ROADMAP §B3 (redefine B3.a-1) |
| **Habilita** | [`_CONTRATO-RESOLUCION-PARAMETROS.md`](_CONTRATO-RESOLUCION-PARAMETROS.md), CRP-1, CRP-3, CRP-4, CRP-5 |
| **Adelanta del contrato** | **CRP-3 parcial** (la procedencia del segmento viaja en el resultado) y **CRP-6 parcial** (la semántica de `fail_on_falta_dato` en la capa `provisioning`, donde hoy no detiene nada). Declarado aquí para que el contrato lo herede, no lo contradiga |
| **No toca** | El if-chain de despacho normativo (`cmf/engine.py:761-792`), el pre-pase `.eq("consumer")` de B-1 3.2 (`cmf/engine.py:506`), matrices, tramos de mora, buckets PVB/PVG, rangos C1-C6 ni títulos del informe — todo eso es **B3.a-2** y va con la jurisdicción nueva. Tampoco introduce `Resolved[T]` ni las cuatro vías |
| **Fuera de alcance explícito** | Los otros cinco `segment_col` del paquete (`forward/config.py:284`, `survival/config.py:73`, `markov/config.py:75`, `validation/config.py:280`, y el `segment_col` del propio orquestador): tienen semánticas distintas y entran con el contrato |
| **Release** | `1.6.0`. Hay cambio de comportamiento observable y movimiento de `config_hash` (§5) |

---

## 1. El problema, medido

El ROADMAP §B3 justifica B3.a-1 así: *«un parámetro se resuelve por segmento, así que el contrato no
puede montarse sobre un segmento que es un enum chileno»*. El censo del código —tres exploradores
independientes sobre `governance`, `provisioning/cmf` y `provisioning/{config,internal,orchestrator}`
más la UI— muestra que **esa premisa es falsa**, y que el bloqueo real es otro.

### 1.1 El enum chileno no es la llave de segmentación de ningún cálculo

`governance/config.py:27` (`cartera: Literal["comercial","consumo","hipotecario","grupal"]`) tiene
**una sola lectura de atributo en todo el repo**: `api.py:110`, un pass-through que lo mete como tag
`nikodym.cartera` del inventario MLflow. (El valor sí sale en los volcados completos del config
—`core/config/loader.py:103`, `ui/routes.py:163`—: «una sola lectura» no significa «no sale a ninguna
parte», sino que ninguna lógica lo consume.) No entra al `config_hash` (`core/config/hashing.py:34`,
`governance` es `INFRA_SECTIONS`), no llega a la model card (`governance/model_card.py:151-196` sólo
lee `purpose`, `assumptions`, `limitations`, `review_period_months`), no llega al informe —el
`<dt>Cartera</dt>` es `ReportConfig.document.portfolio` (`report/renderer.py:461`), un campo homónimo
y distinto— y **no llega al `schema.json` de la UI**: `governance` no está en `_DOMAIN_CONFIG_CLASSES`
(`core/study.py:79-108`), así que `build_full_json_schema` nunca lo expande.

Corolario medido: el `json_schema_extra={"ui_widget": "selectbox"}` de `governance/config.py:31` **es
letra muerta** — el enum de carteras nunca llegó al front. Y el valor vuelve del Registry como `str`
libre sin revalidar (`tracking/inventory.py:225`).

**Ninguna rama de lógica compara contra esos cuatro literales.** Abrir el tipo cuesta: 1 declaración,
1 `description`, 1 test (`tests/unit/test_governance_config.py:53`) y 3 documentos.

### 1.2 La llave de segmentación real ya es neutra

La que los motores usan para agrupar y resolver es `portfolio_col`, y **ya es `str` libre en los
tres**. El motor interno no mira sus valores: un grep de literales de cartera (`consumer`, `comercial`,
`commercial`, `hipotec`, `mortgage`) sobre `provisioning/internal/engine.py` da **cero en el archivo
entero**; el valor se convierte a texto opaco y se usa como llave de agrupación
(`internal/engine.py:310-315`). En todo `provisioning/internal/` el único rastro chileno de
vocabulario es el `default="cmf_portfolio"` de `config.py:120`.

### 1.3 Lo único que valida el dominio de valores es el motor CMF — y ahí es correcto

`cmf/engine.py:761-792` es un if-chain de 6 comparaciones que traduce nombre-de-cartera → resolver →
`matrix_id`, y `cmf/engine.py:506` es el pre-pase `.eq("consumer")` que consolida a nivel deudor
(B-1 num. 3.2). Ése es contenido normativo chileno: **ser chileno ahí es correcto**, y es B3.a-2.

`_PORTFOLIO_ORDER` (`cmf/engine.py:96-103`), en cambio, **no es un dominio: es orden de
presentación**. Sus dos únicos consumidores (`engine.py:1939`, `engine.py:2011`) hacen `.index()` para
ordenar; nadie la itera y nadie valida pertenencia contra ella. Sus ramas `else 999` son inalcanzables,
porque `record.portfolio` es un literal reemitido por el resolver (`engine.py:824, 848, 905, 972,
1033, 1084, 1145`), nunca el valor de la fila de entrada.

**Verificado empíricamente**, no deducido: invertir el orden de la tupla y correr los cuatro archivos
de test del motor da **113 passed**, y **la suite completa da 4300 passed / 6 skipped**, idéntica al
baseline. Ningún test del repo fija ese orden — y como ese orden gobierna las filas del `summary`
publicado (`engine.py:1903`) y el orden de `metric_sections` (`engine.py:1972`), **es una brecha de
gate por sí misma**: dos artefactos canónicos que nadie protege.

### 1.4 El bloqueo real: nadie declara el dominio de valores del segmento

Éste es el hallazgo que reencuadra el trabajo. El vocabulario de carteras se declara **tres veces, de
forma desacoplada, y nada fuerza que coincidan**:

| Declaración | Dónde | Qué es |
|---|---|---|
| La tupla de orden | `cmf/engine.py:96-103` | presentación |
| El if-chain de despacho | `cmf/engine.py:761-792` | normativo |
| La tabla de la spec | `docs/design/15-provisioning-cmf.md:386-391` | documentación |

Hoy coinciden —se verificó elemento por elemento— pero por coincidencia, no por construcción. Y
**ningún contrato de datos declara el dominio**: el spec de la columna en
`web/src/fixtures/demo/datasets.json:221-225` es `{"name": "cmf_portfolio", "dtype": "str", "role":
"economic"}`, sin `isin` y sin enum.

CRP-1 y CRP-3 exigen resolver *por segmento* y que el valor viaje con su procedencia. Eso es
imposible sobre un string cuyo dominio no existe en ninguna parte. **El trabajo no es quitar el enum
chileno: es darle a la llave un dominio declarable, con dueño y régimen.**

### 1.5 Cinco defectos vivos, todos de la misma raíz

1. **El crosswalk pasa en silencio lo que no mapea.** `orchestrator.py:447` hace
   `mapped = crosswalk.get(key, key)`: una cartera sin equivalencia sigue de largo. La consecuencia
   sólo aflora aguas abajo y con otro nombre («celda sin contraparte», `orchestrator.py:504-546`,
   marca `DATO-INSTITUCIONAL-PROV-1` en `orchestrator.py:536`). Es CRP-4 violado hoy.
2. **El copy público promete algo que el código no comprueba.** La `description` de
   `fail_on_falta_dato` (`provisioning/config.py:302-303`) dice que una brecha crítica «p. ej.
   taxonomías de cartera sin equivalencia declarada en `portfolio_crosswalk`» detiene la corrida. Lo
   que el código comprueba es **otra cosa**: `config.py:395-405` compara *nombres de columna*. La
   equivalencia de taxonomías no se comprueba nunca.
3. **En la capa `provisioning`, `fail_on_falta_dato` no detiene nada.** Su único uso en runtime es
   `umbral=config.fail_on_falta_dato` dentro de un `log_decision` (`provisioning/step.py:127`), con
   acción `trazar_brechas_comparacion`. Su homónimo del motor interno **sí aborta**
   (`internal/engine.py:388`). El mismo nombre, dos comportamientos.
4. **El validador compara nombres de columna, no vocabularios.** La guarda de `config.py:396-399` es
   una conjunción de cuatro condiciones que incluye `col_a != col_b`; como los tres `*_portfolio_col`
   tienen `default="portfolio"` (`config.py:179, 185, 191`), dos fuentes con vocabularios distintos
   bajo el mismo nombre de columna **nunca** disparan la exigencia. **Ningún test cubre ese caso**:
   los dos tests de crosswalk (`tests/unit/test_provisioning_orchestrator.py:422-461`) declaran
   crosswalk explícito, o sea prueban que el remapeo *declarado* funciona, no el falso negativo.
   Además hay asimetría: se exige en `comparison_level="segment"` pero sólo se **aplica** en
   `"portfolio"` (`orchestrator.py:235`).
5. **El motor «neutro» cita a la CMF chilena en su resultado.** `internal/engine.py:792` emite
   `"CMF Cap. B-1 §3 (Circular N° 2.346): …"` dentro de `metric_sections`. No se queda en un artefacto
   interno: llega **al informe renderizado** (`report/builder.py:486-493` → `report/renderer.py:405`)
   y **a la model card** (`governance/model_card.py:190`). Un usuario de otra jurisdicción recibe una
   circular chilena en su PDF. El ROADMAP §B3:207-208 describe `internal/` como «casi neutro — su
   única atadura real es el `default="cmf_portfolio"`»; ésta es la segunda, y es la que sale al
   cliente. Sus `title`/`description` (`internal/config.py:121-122`) y el `title` de su método
   (`internal/config.py:172-180`, «Método del B-1 §3») son copy público con el mismo problema.

### 1.6 El régimen no existe como dato

Búsqueda de `jurisdic|regime|regimen|country|pais` sobre `src/` y `web/src/`: **cero campos de config,
cero enums, cero opciones de UI, cero claves de preset**. El único rastro es `"country"` como columna-
dimensión reconocida por el motor de stress (`stress/engine.py:305`), que es dato del usuario, no
régimen del motor. Por lo demás vive sólo como copy —los títulos de sección `report/document.py:94-96`
(«…la regla del máximo (Chile)», «Método estándar de la CMF de Chile») y el copy curado de
`web/src/lib/presentation.ts:10-12`— y como regla de proceso. El ROADMAP §B3 lo exige como **selector
explícito**.

## 2. Las decisiones

**D-SEG-1 — El régimen regulatorio es un dato declarado, garantizado por registro y no por tipo.**
Se declara un identificador de **régimen versionable** (`CL-CMF-B1`), no un código de país: un país
puede tener más de un régimen, y un régimen cambia de versión —las matrices ya lo saben, con
`matrix_version` y su manifiesto—.

La regla de honestidad del ROADMAP («una jurisdicción sólo aparece cuando existe su motor») **no la
puede garantizar el sistema de tipos**: ampliar un `Literal["CL"]` a `Literal["CL","PE"]` compila
igual de bien sin motor detrás. La garantía la da un **registro régimen→motor** más un test que exige
que todo valor admitido resuelva a un motor registrado, con el conjunto admitido derivado de las
claves del registro. Sin ese test, la regla es prosa.

**Dónde vive:** el régimen es **atributo del motor regulatorio** —el motor CMF lo tiene fijo por
construcción, porque *es* el método estándar chileno— y el orquestador y el preset lo **presentan**,
no lo definen. Esto es obligado por la arquitectura: las cuatro secciones de provisiones son hermanas
independientes y opcionales en `NikodymConfig` (`core/config/schema.py:372-416`), así que una corrida
sólo-CMF o sólo-interna no tiene sección `provisioning` de la que leer un campo transversal.

**D-SEG-2 — El segmento se declara como esquema, con seis atributos y tres clases.** Un esquema de
segmentación declara: **id**, **régimen** que lo respalda (si aplica), **versión**, **columna** que lo
transporta, **secuencia ordenada** de valores, y si es **cerrado** (rechaza lo desconocido) o
**abierto**. La versión y la columna no son adorno: CRP-1 define `REGULATORY` como tabla normativa
*versionada* y `PROVIDED` como «viene en una columna del dataset», así que sin esos dos campos el
contrato no puede construir su `Resolved[T]`. El orden es parte del esquema porque gobierna artefactos
publicados (§1.3).

| Clase | Quién fija el vocabulario | Cerrado | Ejemplo |
|---|---|---|---|
| **Normativo** | el régimen, versionado | sí | las 6 carteras del método estándar chileno |
| **Declarado** | la institución, en su config | se declara | sus grupos homogéneos nombrados |
| **Derivado del dato** | se construye en runtime; no es enumerable en un config | no aplica | `grouping="score_band"` —**el default**— deriva las bandas por cuantiles de PD dentro de cada cartera (`internal/engine.py:439-463`) |

La tercera clase no es hipotética: es lo que hace hoy el motor interno por defecto, y su procedencia
**ya** se registra en la card y el audit-trail (`internal/engine.py:439-445`, cuyo docstring dice que
es «lo que un validador lee para saber de dónde salieron los grupos»). Esta enmienda **absorbe ese
precedente** en vez de crear un concepto paralelo.

Dos precisiones que evitan un error de implementación:

- **Clase de esquema ≠ vía del parámetro.** Son ejes ortogonales. Un esquema normativo cuyos valores
  llegan en una columna del dataset es `REGULATORY` como esquema y `PROVIDED` como dato. No se reusan
  los nombres de `ParameterSource` para clasificar esquemas.
- **La llave de resolución es `(esquema, valor)`, no el valor pelado.** Dos esquemas pueden tener
  ambos el valor `consumer`; sin espacio de nombres, colisionan al resolver un parámetro por segmento.

**D-SEG-3 — El esquema viaja en el resultado de cada motor, no sólo en su config.** Es lo que hace
implementable todo lo demás: el orquestador recibe **objetos de resultado**, no configs de motor
(`orchestrator.py:200-235`), y las cuatro secciones no se ven entre sí. Un esquema declarado sólo en
el config del orquestador sería una afirmación del usuario que nadie puede contrastar contra lo que el
motor realmente emitió. Los tres motores publican su esquema en su card. Esto es CRP-3 —«la
procedencia entra al audit-trail y a la model card»— adelantado para el segmento, y **cambia los DTO
de card**: es cambio de artefacto publicado y va con su nota de versión.

**D-SEG-4 — El dominio se valida en un gate de entrada, y no puede quedar declarado dos veces.** La
pertenencia se valida al entrar al motor, con un error que nombra el vocabulario esperado y su
régimen, en vez de descubrirse a mitad del cómputo dentro de `_resolve_provision` (`cmf/engine.py:792`).
Es CRP-5 aplicado al segmento.

**El if-chain no se toca, pero no se le permite divergir**: un test verifica que el conjunto de valores
del esquema normativo es **exactamente** el conjunto que el despachador resuelve. Sin ese test, el
criterio «se declara en un solo lugar» sería falso el día de escribirlo: si el esquema gana un valor
que el if-chain no despacha, el `raise` salta a mitad del cómputo —justo lo que este gate elimina—, y
si pierde uno, queda una rama muerta que nadie detecta.

**D-SEG-5 — La necesidad de crosswalk se decide comparando esquemas, con red de seguridad.** Si ambas
fuentes declaran esquema, se comparan los **esquemas**: mismo esquema no exige crosswalk aunque las
columnas se llamen distinto; esquemas distintos lo exigen aunque se llamen igual. **Si a alguna fuente
le falta el esquema, se conserva la guarda actual por nombre de columna.** La regla es que esta
enmienda nunca deje **menos** validación que hoy: sustituir un chequeo tosco por uno que sólo dispara
cuando el usuario declaró algo opcional sería un retroceso disfrazado de mejora.

**Precisado al implementarlo: la comparación de esquemas es de RUNTIME, no de validación de config.**
Cuando se valida el config todavía no hay resultados, y `ProvisioningConfig` no puede leer a sus
secciones hermanas —son independientes por diseño (`core/config/schema.py:372-416`)—, así que ahí no
hay dos esquemas que comparar. La comparación real ocurre donde sí existen ambos: en el orquestador,
contrastando cada cartera remapeada contra el vocabulario que la fuente de destino publicó en su card
(D-SEG-7). El efecto buscado se obtiene igual —esquemas distintos sin crosswalk terminan en
`PROV-4`—, y la guarda de config por nombre de columna se conserva **tal cual** como red de seguridad.
Lo que **no** queda implementado es la mitad simétrica: relajar la exigencia cuando ambas fuentes
declaran el mismo esquema con columnas de nombre distinto. Exigiría que la sección del orquestador
lea las de los motores, que es un cambio de arquitectura fuera del alcance de esta enmienda.

**D-SEG-6 — En `comparison_level="segment"` el crosswalk se aplica, no se exime.** La asimetría de
§1.5.4 se corrige por el lado de aplicar (`orchestrator.py:235` pasa a cubrir ambos niveles), no por
el de eximir. La tentación contraria —«en `segment` ambas fuentes usan la misma `segment_col`, luego
hay un solo vocabulario»— confunde *mismo nombre de columna* con *misma columna*: los valores se leen
de dos frames producidos por dos motores distintos (`orchestrator.py:390-397`). Eximir ese nivel
institucionalizaría exactamente el falso negativo que D-SEG-5 existe para matar.

Se registra además un límite medido, hoy no documentado: los tres motores emiten `detail` con lista
**fija** de columnas (`cmf/engine.py:65-84`, `internal/results.py:29-39`, `ifrs9/engine.py:123-138`),
ninguno hace passthrough de una columna arbitraria del dataset. En la práctica `segment_col` sólo
puede tomar un nombre que esos motores ya emitan.

**D-SEG-7 — La marca corresponde por vocabulario de destino, no por ausencia en el crosswalk.** Un
crosswalk **parcial es correcto por diseño**: sólo se mapea lo que difiere, y lo que coincide pasa por
identidad legítima. Marcar «toda cartera ausente del crosswalk» convertiría cada identidad legítima en
brecha. La condición correcta es que el valor **no pertenezca al vocabulario de destino** —el de la
fuente B—, que es otra razón por la que el esquema debe viajar en el resultado (D-SEG-3).

La marca es **`DATO-INSTITUCIONAL`** —el motor no puede conocer la equivalencia entre dos taxonomías;
sólo la institución puede declararla, y negarse a inventarla es la conducta correcta— con código
propio **`DATO-INSTITUCIONAL-PROV-4`**, distinto de `PROV-1` («celda sin contraparte»), que es el
síntoma aguas abajo y no la causa.

Esta decisión **adelanta CRP-6** para la capa `provisioning`: hoy `fail_on_falta_dato` no detiene nada
ahí (§1.5.3), y para que la marca detenga la corrida hay que darle la semántica que el contrato fijará
para las siete capas. Se declara explícitamente para que el contrato la herede en vez de encontrarse
una variante.

**D-SEG-8 — El motor interno deja de emitir cita normativa.** No condicionada al régimen: **eliminada**.
Condicionarla obligaría al motor «neutro» a conocer el régimen y a ramificar sobre él, que es menos
neutro, no más. Y el propio diagnóstico lo pide: `Exposición · PD · LGD` por grupo homogéneo no es
chileno, luego el motor no tiene por qué atribuirse una circular. La referencia normativa la aporta la
capa que declara el régimen. Entran también el `title` del método (`internal/config.py:172-180`), los
`title`/`description` de `portfolio_col` (`internal/config.py:121-122`) y la docstring del módulo.

**D-SEG-9 — El default `cmf_portfolio` se mantiene en los dos motores.** Está en `cmf/config.py:300`
**y** en `internal/config.py:120`, y no por descuido: la regla del máximo compara ambos motores sobre
las mismas carteras. Cambiar sólo el del interno los desalinearía en toda config que no fije ambos.

**Resuelto al implementarlo: no se renombra ninguno.** El candidato natural, `"portfolio"`, es
exactamente el nombre de la columna de **salida** que los tres motores publican en su `detail`
(`cmf/engine.py:71`, `internal/results.py:31`, `ifrs9`), así que reusarlo para la columna de entrada
haría ambiguo cuál es cuál. Y el costo era real —96 tests y las fixtures— a cambio de ninguna
capacidad nueva: `portfolio_col` ya es `str` libre, así que un usuario de cualquier jurisdicción
declara el nombre que quiera. El prefijo sobrevive sólo como *default*, que es la definición de
atadura barata; lo que sí se corrige es su **copy público** (D-SEG-8), que era lo que llegaba al
usuario.

**D-SEG-10 — El enum de governance se abre y su `description` deja de mentir.** `cartera` pasa a `str`
libre —el censo confirma que ninguna lógica compara contra sus literales— y su `description` deja de
decir «Naming CMF en español». Se documenta que el valor vuelve del Registry sin revalidar
(`tracking/inventory.py:225`), que es la razón de fondo por la que el `Literal` nunca fue garantía.

**D-SEG-11 — Una config que no declara régimen no se rechaza ni se completa en silencio: se marca.**

> **Estado al implementar: sin objeto todavía, y es consecuencia de D-SEG-1.** Al decidir que el
> régimen es *atributo del motor* —el motor estándar chileno **es** su régimen, no lo elige— no queda
> ninguna config donde el usuario pueda omitirlo: no hay campo que dejar en blanco. La decisión se
> conserva escrita porque vuelve a tener objeto en cuanto exista un segundo motor y el régimen pase a
> ser elegible; ese día, además, la marca debe convertirse en error, porque recién entonces hay
> ambigüedad genuina.

Decisión de DanIA (2026-07-25) sobre la migración desde `1.5.x`, por coherencia con las dos reglas ya
vigentes del proyecto. Asumir `CL-CMF-B1` en silencio sería el motor inventando un dato institucional,
que es justo lo que la marca `DATO-INSTITUCIONAL` existe para impedir; y rechazar la config rompería a
todo usuario actual sin que haya ninguna ambigüedad real que resolver —hoy el único motor que existe
es el chileno—. Así que la corrida **sigue**, con el comportamiento de hoy, y **emite marca declarada**
señalando que el régimen no fue declarado. Retrocompatible pero ruidoso, que es exactamente lo que
CRP-4 pide. El día que exista un segundo motor, esa marca pasa a ser un error: entonces sí hay
ambigüedad genuina, y resolverla es de la institución.

**Límite explícito:** el `ui_widget: "selectbox"` muerto de `governance/config.py:31` **no se hace
efectivo aquí**. Exige expandir `governance` en `_DOMAIN_CONFIG_CLASSES` (`core/study.py:79-108`), que
arrastra las secciones INFRA completas. Queda anotado como brecha de paridad UI↔código, con su causa
medida.

## 3. Superficies afectadas

| Archivo | Cambio |
|---|---|
| `src/nikodym/provisioning/cmf/{config,engine,results}.py` | Esquema normativo declarado una vez, con versión; `_PORTFOLIO_ORDER` se deriva; gate de entrada; el esquema viaja en la card. **El if-chain no se modifica** |
| `src/nikodym/provisioning/internal/{config,engine,results}.py` | Esquema declarado/derivado en la card; cita normativa eliminada; copy neutro (D-SEG-8) |
| `src/nikodym/provisioning/ifrs9/{config,engine,results}.py` | Declara y publica su esquema — es la tercera fuente que el orquestador compara y su `portfolio_col` comparte el `default="portfolio"` que produce el falso negativo (`ifrs9/config.py:595`) |
| `src/nikodym/provisioning/config.py` | Validación por esquema con red de seguridad (D-SEG-5); presentación del régimen |
| `src/nikodym/provisioning/orchestrator.py` | Crosswalk también en `segment` (D-SEG-6); marca `PROV-4` por vocabulario de destino (D-SEG-7) |
| `src/nikodym/provisioning/step.py` | Semántica real de `fail_on_falta_dato` (hoy sólo `log_decision`, `step.py:127`) |
| `src/nikodym/governance/config.py` | Tipo y `description` de `cartera` (D-SEG-10) |
| `src/nikodym/report/document.py:94-96` | Los títulos con «(Chile)» pasan a derivarse del régimen declarado en vez de estar cableados |
| `src/nikodym/ui/presets.py`, `web/src/lib/presentation.ts` | El régimen como elección visible, con una sola opción real |
| `web/src/fixtures/demo/*.json` | Regeneración por movimiento de `config_hash` (§5) |
| `tests/unit/test_provisioning_orchestrator.py` y vecinos | Sus fixtures usan vocabulario inventado (`"comercial"`, `"empresas"`); con esquema normativo dejan de pertenecer al vocabulario CMF |
| `docs/design/{15,16,17,03,04}-*.md`, `docs/ROADMAP.md`, `docs_site/guias/desempeno-estabilidad.md:215` | La tabla de carteras deja de ser una declaración suelta; B3.a-1 se redefine |

## 4. Criterios de aceptación

1. El vocabulario normativo chileno se declara en **un solo lugar**, y un test verifica que el
   conjunto del esquema es **exactamente** el conjunto que el if-chain despacha (D-SEG-4).
2. Permutar el orden de presentación no cambia ninguna **cifra**, y el orden de filas del `summary` y
   el de `metric_sections` quedan **fijados por test**. Hoy no lo están: se midió que invertir
   `_PORTFOLIO_ORDER` deja la suite completa en 4300 passed / 6 skipped.
3. Un valor que no pertenece al vocabulario de destino emite `DATO-INSTITUCIONAL-PROV-4` —distinguible
   de `PROV-1`, que ya existe— y con `fail_on_falta_dato=True` **detiene** la corrida. Un valor que
   coincide por identidad legítima **no** se marca.
4. Dos fuentes con la **misma** columna y esquemas distintos ya no pasan sin crosswalk; dos fuentes
   con el mismo esquema y columnas distintas ya no lo exigen; y **dos fuentes sin esquema declarado y
   con columnas distintas siguen exigiéndolo** (la red de seguridad de D-SEG-5).
5. Una cartera fuera del vocabulario se rechaza en el gate de entrada, antes de iniciar el cómputo,
   con un mensaje que nombra el vocabulario esperado y su régimen.
6. El resultado del método interno no contiene ninguna referencia a una circular chilena — ni en la
   card, ni en el informe renderizado, ni en la model card (las tres rutas de §1.5.5).
7. Todo valor de régimen admitido resuelve a un motor registrado, verificado por test (D-SEG-1).
8. El preset y la UI presentan el régimen como elección explícita, con **una sola opción real** y
   ninguna opción «próximamente».
9. Todo test nuevo se verifica **fallando** contra el árbol anterior.

## 5. Riesgos y ruptura

- **`config_hash` se mueve, y con él los fixtures.** `provisioning`, `provisioning_cmf`,
  `provisioning_ifrs9` y `provisioning_internal` **no** son INFRA (`core/config/hashing.py:34`), así
  que cualquier campo nuevo cambia el hash de toda config que las traiga. Hay que regenerar los
  presets y las fixtures de la demo **en el mismo commit**, o la identidad UI↔código deja de cerrar.
  El golden de `config_hash(NikodymConfig())` no se mueve: las cuatro secciones son `None` por defecto.
- **Cambio de comportamiento observable.** Una corrida con crosswalk incompleto que hoy termina en
  verde pasará a marcar o a detenerse. Es la corrección de un defecto —hoy se comparan celdas que no
  se corresponden— pero un usuario existente lo verá como ruptura. Va en `1.6.0` con nota en el
  CHANGELOG.
- **Migración de configs `1.5.x`: resuelta en D-SEG-11** (se marca, no se rechaza ni se completa en
  silencio). El riesgo residual es de volumen: toda corrida existente empezará a emitir una marca. Se
  acepta —es una por corrida, no por fila— y desaparece en cuanto la config declara el régimen.
- **Casi todo el trabajo toca artefactos publicados, así que la recaptura de la demo va UNA sola vez,
  al final.** Medido: la cita normativa que D-SEG-8 elimina vive hoy en
  `web/src/fixtures/demo/results.json`, en `report.html` y en el bundle compilado
  `ui/static/assets/`. Sumado al movimiento de `config_hash`, recapturar decisión por decisión
  produciría estados intermedios inconsistentes. Rige el procedimiento vigente: árbol limpio y commit
  entre capturas, o el informe se declara irreproducible.
- **Sobrediseño.** El riesgo simétrico del contrato. Mitigación: tres clases porque hay tres
  comportamientos **medidos** en el árbol, y un solo régimen real; no se modela lo que no tiene motor
  detrás.
- **Solapamiento con el contrato.** Esta enmienda adelanta CRP-3 y CRP-6 sólo en lo que el segmento
  necesita, y lo declara en la cabecera para que el contrato lo herede. Si al escribirlo el esquema
  resulta insuficiente, se reabre esta enmienda: es esperado y barato.
- **La lectura del panorama LATAM sigue sin verificar.** Nada aquí escribe normativa extranjera. Antes
  de cualquier motor de régimen nuevo rige el principio no negociable #11.

## 6. Qué cambió tras la revisión adversarial

El borrador anterior fue revisado por dos agentes independientes, uno de hechos y otro de diseño.
Cambios de fondo, todos por hallazgo verificado contra el árbol:

- **Una cita era falsa.** Se afirmaba que los tests de `test_provisioning_orchestrator.py:422-461`
  trataban el falso negativo como escenario esperado; ambos declaran crosswalk explícito. El argumento
  correcto es más fuerte: *ningún* test cubre ese caso.
- **D-SEG-5 era inimplementable** sin que el esquema viaje en el resultado: el orquestador nunca ve el
  config de los motores. De ahí la decisión nueva D-SEG-3.
- **D-SEG-6 estaba invertida.** Eximir a `segment` institucionalizaba el falso negativo que D-SEG-5
  mata; se corrige aplicando el crosswalk, no eximiendo.
- **La marca de D-SEG-7 habría marcado carteras sanas**: el crosswalk es parcial por diseño y la
  identidad es legítima. La condición pasó a ser el vocabulario de destino, con código propio `PROV-4`
  porque `PROV-1` ya existe y un criterio que no lo distinga pasaría contra el árbol actual.
- **El argumento de tipo de D-SEG-1 era incorrecto**: ampliar un `Literal` compila sin motor detrás.
  Lo sustituye un registro régimen→motor con test de cobertura, y el id pasa a ser de régimen
  versionable en vez de código de país.
- **D-SEG-2 no alcanzaba para CRP-1/CRP-3**: faltaban versión, columna, orden, cierre y espacio de
  nombres de la llave, y faltaba la clase «derivada del dato», que es **el default** del motor interno.
- **D-SEG-7 (antes «cita condicionada al régimen»)** habría vuelto al motor interno menos neutro. Se
  elimina la cita.
- **Se añadieron** IFRS 9 como superficie, el movimiento de `config_hash`, el `default` compartido
  entre los dos motores (D-SEG-9) y el alcance explícito sobre los otros cinco `segment_col`.
