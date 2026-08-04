# Enmienda SDD — el ancla que se pidió y el ancla que se usó

> **Estado:** **APROBADA** (Cami, 2026-08-04): se implementan **las tres salidas**, (a)+(b)+(c).
> La recomendación escrita en la §3 era (a)+(c); Cami eligió las tres **con el riesgo a la vista** —
> la opción declaraba que con (a) el aviso de (b) queda en su mayor parte inalcanzable—. Eso obliga a
> **medir** esa alcanzabilidad y declararla (§7), no a descubrirla: es la clase «cerrar un defecto
> deja código inalcanzable, y eso se decide».
> **Enmienda a:** [`10-calibration.md`](10-calibration.md) (§5 coherencia del ancla, §8 el paso 7 de
> `fit`, y las líneas 321 y 531 —D-CAL-2—, que quedaron **stale** respecto del código).
> **Origen:** M-7 de [`_CENSO-DEFECTOS-DEL-ABANICO.md`](_CENSO-DEFECTOS-DEL-ABANICO.md) §4.
> **Instancia de:** [`_CONTRATO-RESOLUCION-PARAMETROS.md`](_CONTRATO-RESOLUCION-PARAMETROS.md)
> CRP-3, que nombra literalmente «tasa central de calibración» y **nunca se implementó**.
> **Decisiones:** D-ANC-1 … D-ANC-12 (las tres últimas nacieron **al implementar**, ver §7).

## 0. El defecto

`CalibrationConfig.anchor_source` trae de fábrica `'development_observed'`. Con esa fuente,
`_resolve_target_pd` (`calibration/calibrator.py:611-634`) **descarta el `target_pd` que el usuario
escribió** y devuelve la media del target en Desarrollo. Las otras tres fuentes —las de
`_EXPLICIT_ANCHOR_SOURCES`— **fallan** si falta `target_pd`; ésta acepta y descarta el que sobra.

🔴 **Y los dos campos son contiguos en la pantalla.** `target_pd` (`number_input`) y `anchor_source`
(`selectbox`) viven en el mismo `ui_group: "Ancla"` (`calibration/config.py:84-105` y `:124-140`),
ninguno `hidden`, con `calibration` en `CONFIG_SECTIONS` (`web/src/lib/schema.ts:115`). El par se
arma **escribiendo un número en «PD objetivo» y no tocando el selector de al lado** — un solo gesto,
sobre el default.

## 1. Lo que se midió, y las cuatro correcciones al censo

Cuatro subagentes en paralelo: las tres salidas y una reproducción **ejecutada**. Todo lo de abajo
sale de una corrida, no de una lectura.

### 1.1 ✅ El defecto se reproduce — y el daño aguas abajo es 2,84×

Preset F1, tasa observada en Desarrollo **23,327 %**. Se escribe `target_pd=0.20` dejando
`anchor_source` en su default. La corrida termina **`done`**, y la media de `pd_calibrated` es **bit
a bit idéntica** a la del caso base (`0.2338539849`): el `0.20` es completamente inerte.

Sobre el preset **F3** (provisiones), tasa observada 6,626 %:

| caso | `total_provision` |
|---|---|
| F3 base (`target_pd=None`) | 308.644.057,91 |
| **F3 con el par del defecto** (`0.20` + `development_observed`) | **308.644.057,91** |
| F3 control (`0.20` + `business_input`) | **878.006.307,71** |

**569 millones de diferencia, cero avisos, `done` en las tres.** El usuario que creía estar anclando
a 0,20 obtiene la provisión de 0,066 y nada se lo dice.

### 1.2 🔴 El informe NO calla: publica los dos valores y se contradice

El censo dice «publica la tasa observada sin decir que se pidió otra». **Medido, es peor.** El diff
del HTML entre la corrida base y la del defecto es de 4 tokens, y uno solo es sustantivo — en el
**Anexo C.6**, dentro del mismo bloque `<dl>` y a diez líneas de distancia:

```
effective_config { … "target_pd": "0.200000", … }   ← el DESCARTADO, rotulado «config efectiva»
DT target_pd  0.233274                               ← el que de verdad gobernó
```

No es silencio: es una **afirmación falsa rotulada «config efectiva»**. Y la prosa del §3.6 es
**byte-idéntica** en los dos casos, llamando **«PD objetivo de 23,33 %»** al valor observado —o sea
usando el `title` del campo que el usuario rellenó (`config.py:88`) para nombrar el número que lo
descartó (`report/prose.py:962-963`).

**Conteo: 8 superficies en verde o en silencio** (`model_validate`, `check_pipeline`,
`check_dataset`, avisos declarados —0 en toda la corrida—, el artefacto de calibración, la prosa,
`results.json` —ni siquiera contiene el `0.20`— y el lineage) **y 1 que menciona el número
afirmando lo contrario de la verdad**.

### 1.3 🔴 `config_hash` SÍ se mueve — la identidad miente

Medido dos veces, de forma independiente:

```
NikodymConfig(calibration=CalibrationConfig())               → 478bbc35…
NikodymConfig(calibration=CalibrationConfig(target_pd=0.20)) → 08fd0b52…
```

y sobre el preset F1, `ec10eb43…` → `ab399973…`. **Dos configs con identidad criptográfica distinta
producen resultados idénticos.** Es la misma familia que corrigió `1.8.0`: la identidad debe ser la
del config *que se ejecutaría*. Aquí el digest incluye un campo que no se ejecuta.

### 1.4 Las cuatro correcciones al censo

1. **`target_pd` tiene default `None`, no `0.05`.** El `0.05` sólo sobrevive en el texto de un
   mensaje de error (`config.py:392`) y en **SDD-10 líneas 321 y 531, que quedaron stale** (se retiró
   en `60013ac`). ⇒ **el estado de fábrica NO cae en el par**, y rechazarlo no rompe ninguna corrida
   de fábrica. El censo no lo dice, y es lo que decide el coste.
2. **No existe ningún `target_pd=0.03` en producción.** El barrido lo situó en
   `src/nikodym/ml/step.py:843` («código de producción»); verificado por dos vías independientes,
   `_calibration_config_from_study` construye `CalibrationConfig()` **sin argumentos** y el `0.03`
   vive en `tests/unit/test_ml_step.py:569`. **Ninguna ruta del motor cae en el par**: hay que
   escribir el número a propósito. El dato era cierto, la conclusión no.
3. **Los sitios que rompen son 6 en 4 archivos, y su clasificación estaba invertida.** El barrido
   AST clasificó `test_calibration_config.py:169` como «dentro de función» porque el
   `decorator_list` cuelga del `FunctionDef` — pero **un decorador se ejecuta al importar**. Es
   error de recolección: tumba las **60** pruebas del módulo y, sin flags, **aborta la suite
   entera**. Y sobre-contó: la línea 150 monkeypatchea la clase a `None`, la sección queda blob
   opaco y el validador nunca corre.
4. **`max_abs_offset` es la guarda equivocada y no puede servir.** Con `development_observed` el
   offset es ~0 **por construcción** (−2,65e−16), así que el tope nunca se cruza.

### 1.5 🔴 El hallazgo que ordena la decisión: la documentación pública YA afirma la regla

- `docs_site/tutorial.md:269` — *«con `development_observed` exige que `target_pd` venga sin
  fijar»*. **Hoy es falso.**
- `docs_site/guias/modelo-calibracion.md:225` — *«En este caso `target_pd` se deja en `None`»*.
- Y el abanico **documenta el defecto en vez de señalarlo** (`ui/jobs.py:2743`): *«si además
  escribes una tasa objetivo a mano, ese número se descarta en silencio y manda el promedio
  observado»* — texto estático que aparece siempre, no un aviso condicionado al config.

Es la misma clase que ya costó cara: `docs_site/` publicó doce días un ancla que el preset ya no
tomaba. **Hoy la documentación describe el motor que queremos, no el que hay.**

### 1.6 🔴 El criterio ya está escrito DOS LÍNEAS más arriba, en el mismo validador

`calibration/config.py:376-382` **ya rechaza** `anchor_kind='point_in_time'` +
`anchor_source='development_observed'`, y su razón escrita es:

> *«etiquetar esa salida como point_in_time sería una etiqueta falsa»*

bajo el comentario de la §5 de SDD-10: *«nunca etiquetar una salida con una fuente/visión que no se
corresponde con el número realmente usado (criterio: **o se ancla de verdad, o falla**)»*.

**M-7 es el caso simétrico de ese mismo validador, sin cubrir.**

## 2. Las tres salidas, costeadas

| | (a) rechazar el config | (b) avisar en el preflight | (c) publicar pedida-vs-usada |
|---|---|---|---|
| **archivos** | 1 (`calibration/config.py`) + 4 de test | 2 (`config.py` +1 método; el gate −1 línea) | 1 (`report/prose.py`) |
| **tests** | **6 sitios en 4 archivos**; 1 a nivel de módulo ⇒ −60 recolectados y **la suite no corre** sin flag. Con flag: 3 failed / 5041 passed | 4 nuevos; suite medida **1 failed / 5103 passed** (el gate de D-ABA-9 pidiendo borrar la exención de `calibration`) | **0 a actualizar**, sólo nuevos |
| **presets / fixtures / bundle** | **cero** (los tres fijan `target_pd: None` explícito) | **cero** — `schema.json` byte-idéntico, hashes idénticos | **cero** (la cláusula no dispara en la demo; el HTML queda byte-idéntico) |
| **`config_hash`** | lo **arregla** (el par deja de existir) | no lo toca | no lo toca |
| **contrato** | 🔴 **cambio de comportamiento** ⇒ SemVer minor | 🔴 sería el **primer `unmet_requirement` cuya corrida NO falla**, y dos frases de copy dicen «es probable que la corrida falle» | aditivo |
| **cuándo se entera el usuario** | al validar, **no puede equivocarse** | antes de correr, pero **puede correr igual** (D-PRE-5: informa, no bloquea) | **después** de correr, leyendo el informe |

Detalle de lo que no se ve en la tabla:

- **(b) es viable y está probada**: un prototipo de 11 líneas sobre `requisitos_incumplidos` produce
  el aviso, **y sobrevive al estado opaco** (`check_dataset:715-717` coacciona antes de recorrer).
  El aviso llega a la pantalla **sin una línea de front**: `unmet_requirement` ya está en la unión de
  `web/src/lib/api.ts:157-166` y `calibration` es sección editable, así que el aviso es un **botón
  que salta al campo exacto**. Cero falsos positivos de fábrica, medido sobre los tres presets, los
  seis fixtures y los diez trabajos.
- **(c) es casi gratis**: el valor pedido **ya viaja** en `bundle.pipeline_params` (el config *como
  se escribió*), y `_params()` ya existe y lo usan 5 sitios de prosa (`prose.py:2121`). No hace falta
  campo nuevo en ningún DTO.
- **El precedente de (c) es fuerte**: el orquestador de provisiones publica `provision_a`,
  `provision_b`, `reported_provision` **y** `binding`, y su prosa nombra el descartado *cuantificando
  la diferencia* (`prose.py:1539-1567`). `time_value`/`time_value_years` publica el crudo junto al
  convertido *«para que la conversión sea auditable»* (`ifrs9/ecl.py:95`). Y `n_variables_requested`
  da la convención de nombres (`binning/results.py:92-94`).
- ⚠️ **Un precedente juega en contra de (c) sola**: `injected_artifacts` publica sólo la clave y no
  el origen, con razón escrita en `_ENMIENDA-PUERTA-ARTEFACTOS.md:236-240` — *«no se guarda el diff,
  se declara que no es reconstruible»*. Allí el valor no es hasheable; aquí es un `float`.

## 3. 🔴 La recomendación: **(a) + (c)**, y NO (b)

**Rechazar el par en el validador, y de paso arreglar el rótulo del informe.** Razones, en orden de
peso:

1. **El criterio ya está escrito y ya se aplica al caso simétrico** (§1.6). No se inventa una regla:
   se termina de aplicar la que la §5 de SDD-10 fijó — *o se ancla de verdad, o falla*.
2. **La documentación pública ya promete (a)** (§1.5). Hoy `docs_site/tutorial.md:269` miente.
   Implementar (a) **alinea el motor con lo que ya se publica**; cualquier otra salida obliga a
   reescribir la documentación para que describa un motor más débil.
3. **Sólo (a) arregla el `config_hash` que miente** (§1.3). (b) y (c) dejan vivas dos identidades
   distintas para resultados idénticos.
4. **Sólo (a) elimina la afirmación falsa del Anexo C.6** (§1.2), que hoy rotula «config efectiva»
   un número que no se usó.
5. **El coste medido es de tests, no de usuarios**: cero presets, cero fixtures, cero rutas de
   producción. Son 6 construcciones en 4 archivos.

**Por qué no (b), aunque esté probada y sea barata:** avisar de algo que el propio repo declara
inadmisible es más débil que rechazarlo, y el preflight **no bloquea** por diseño (D-PRE-5), así que
el usuario puede correr igual y llevarse los 569 millones de diferencia. Además introduce el primer
aviso no-fatal, lo que obliga a re-litigar el copy de los **once** avisos existentes
(`web/src/lib/preflight.ts:133-136` y `PreflightNotice.tsx:100-101` afirman *«es probable que la
corrida falle»*, falso sobre M-7). Es más coste conceptual por menos garantía.

**(c) acompaña a (a) porque cierra un hueco que (a) no toca:** con `target_pd=None` la prosa sigue
llamando **«PD objetivo»** a una tasa *observada* que nadie fijó como objetivo. El número es
correcto; el rótulo, impreciso. Cuesta una función.

⚠️ **Lo que (a) cuesta de verdad, dicho sin adornos:** un usuario externo con ese par en su YAML
**hoy corre y mañana no**. Es cambio de comportamiento ⇒ **minor**, con precedente en `1.6.0`, que
rompió dos configuraciones de fábrica a propósito tras medirlo. La contrapartida es que ese usuario
**hoy está siendo engañado**: su corrida no hace lo que él cree. Romper ruidosamente es mejor que
seguir publicando un número que él no pidió.

## 4. Decisiones

- **D-ANC-1. El par se rechaza en el `model_validator` de `CalibrationConfig`.**
  `anchor_source='development_observed'` con `target_pd is not None` levanta `ConfigError` — la clase
  del **núcleo**, para no romper el contrato «siempre 200» de `/api/validate`. Va **junto** a los dos
  chequeos de coherencia del ancla que ya existen (`config.py:376-386`), porque es el mismo criterio.
- **D-ANC-2. El error enseña las dos salidas.** No basta con negar: el mensaje dice que se deje
  `target_pd` vacío **o** se elija una fuente que sí fije la tasa, nombrando los literales exactos
  (`business_input`, `historical_default_rate`, `external_regulatory`) — las opciones se pintan
  crudas, y un copy que nombre una opción tiene que usar su literal.
- **D-ANC-3. `target_pd is not None` ES la señal de intención, y no hace falta `model_fields_set`.**
  El default es `None`, así que un número ahí sólo puede haberlo puesto alguien. Se deja escrito
  porque es lo que hace innecesario el mecanismo caro.
- **D-ANC-4. La prosa deja de llamar «PD objetivo» a una tasa observada.** `_methodology_calibration`
  (`prose.py:944`) deriva el rótulo de `anchor_source`: con `development_observed` la frase dice que
  la tasa **se estimó** de Desarrollo; con una fuente explícita, que se **fijó** en ese valor. Mismo
  criterio que D-MAX-2 (el título se deriva del dato, no se cablea).
- **D-ANC-5. No nace ningún campo en ningún DTO, ni `Resolved[T]`.** El valor pedido ya viaja en
  `bundle.pipeline_params`. Esta enmienda es la **primera instancia concreta de CRP-3**, no su
  implementación genérica: construir `Resolved[T]` para un caso sería diseñar el contrato desde su
  ejemplo más pobre.
- **D-ANC-6. El abanico deja de documentar el defecto.** `ui/jobs.py:2743` afirma que el número «se
  descarta en silencio»; con D-ANC-1 eso deja de ser cierto y pasa a decir que el motor lo rechaza.
  ⚠️ Arrastra regenerar `web/src/fixtures/jobs.json` **y** el bundle, en el mismo commit.
- **D-ANC-7. SDD-10 se corrige en sus dos líneas stale.** Las líneas 321 y 531 (D-CAL-2) describen
  `target_pd=0.05` como placeholder vivo; el default es `None` desde `60013ac`. Un SDD que contradice
  al código es el mecanismo exacto por el que este censo se equivocó cuatro veces.
- **D-ANC-8. El copy roto de `target_pd` se arregla en esta enmienda.** Su `description`
  (`config.py:88-96`) omite `business_input` y arrastra una llave `}` huérfana:
  *«Con las fuentes `'historical_default_rate', 'external_regulatory'}` es OBLIGATORIA»*. Es copy
  público —se lee **sin hover**, porque `fieldPlaceholder` cae en la `description`— y es hoy la única
  advertencia del descarte. Arrastra `schema.json` y el bundle.
- **D-ANC-9. Nace un gate de CLASE, no del caso: delimitadores desbalanceados en copy visible.**
  Medido sobre los **394 campos** que pinta el formulario: hoy hay **exactamente 1 ofensor**, el de
  D-ANC-8. El gate reusa el barrido de `test_copy_del_formulario.py` y se prueba **inyectando** el
  defecto. Su ancla anti-vacuidad exige >300 campos, porque un gate que recorre cero campos da verde.

## 5. Gates y control negativo

- Los **6 sitios de test** se ajustan a la combinación válida (`target_pd` con fuente explícita, o
  `None` con `development_observed`), no se borran: cada uno prueba otra cosa.
- **Control negativo de D-ANC-1**: un config con `development_observed` + `target_pd=None` y otro con
  `business_input` + `target_pd` **siguen validando**. Se ejecuta, no se describe.
- **Control negativo de D-ANC-9**: reintroducir la `}` huérfana ⇒ el gate se pone rojo.
- ⚠️ **La corrida completa se mide FUERA de pytest**: ajustar el binning real dentro del runner lo
  tumba con un segfault al importar el solver.
- Gates del cierre: pytest, `mypy` sin argumentos, `ruff check` **y** `format --check`,
  typecheck/lint/vitest, fixtures y bundle sin drift, `mkdocs --strict`, **CI 16/16 con `gh`**.

## 7. Lo que salió al implementar, y cambió el trabajo

### 7.1 🔴 D-ANC-10 — un defecto GRAVE preexistente que bloqueaba a D-ANC-1

`_coaccionar_secciones_opacas` (`core/config/hashing.py`) atrapaba **sólo `ValidationError`**. Pero
pydantic envuelve lo que levanta un validador **únicamente si hereda de `ValueError`**, y toda la
jerarquía `NikodymError` —`ConfigError` y las doce `*ConfigError` de dominio— no hereda de él. Así
que **escapaba entera**, contra lo que el propio docstring de la función promete (D-HASH-8:
*«config_hash sigue siendo total»*).

Alcance medido: **123 `raise` en validadores de 18 de las 22 secciones de dominio**, de los que
**72 están en secciones que el formulario ofrece**. `data` y `report` eran las dos únicas seguras, y
por accidente de estilo. Con **un solo `Select`** —`binning.solver='cp'`— `config_hash` y
`check_dataset` dejaban de responder.

⚠️ **No era la cuarta reincidencia del «siempre 200»**, y conviene decirlo porque fue la primera
hipótesis: medido con `TestClient`, los tres endpoints dan **200 / 422 / 422**. La UI está protegida
porque `ui/routes.py:136` carga los dominios **antes** de validar, así que el error salta en
`model_validate` y no dentro del hash. El escape quedaba vivo para la librería por código, para un
YAML en proceso liviano y para cualquier consumidor futuro.

🔴 **Los tres tests que debían cazarlo estaban verdes y ninguno podía fallar.** Dos eligen como
sección inválida un **campo desconocido**, o sea `extra_forbidden`, que es justo la única familia
que el `except` cubría. Y el gate de clase de secciones opacas mide `f(opaco) == f(tipado)`
—*coherencia*— mientras D-HASH-8 exige *totalidad*: con una sección inválida el lado `tipado`
revienta al construirse, así que el par ni se puede montar. **Un gate de coherencia es
estructuralmente incapaz de medir totalidad**, y `POLITICA["config_hash"] = "comprobado"` afirmaba
más de lo que su mecanismo podía sostener.

**D-ANC-10.** El `except` pasa a `(ValidationError, NikodymError)`. **`ConfigError` no basta**:
cuatro clases de `stress` y `forward` cuelgan directamente de `NikodymError`. Y `NikodymError` es el
ancho correcto, no uno de más: la promesa es *«si la coacción falla, devuelve el config sin
coaccionar»*, y un `MissingDependencyError` durante la coacción es exactamente ese caso. Nace un gate
hermano que mide **totalidad**, con dos casos —uno que desciende de `ConfigError` y otro que no—,
para que el arreglo insuficiente también salga rojo. Ambos controles negativos **ejecutados**.

### 7.2 🔴 La salida (b) se midió INALCANZABLE, y se sustituyó

Con D-ANC-1 puesto, el aviso del preflight no se dispara **por ninguno de los dos caminos que
existen**, y no por casualidad sino por construcción — un método necesita su objeto:

| camino | qué ocurre |
|---|---|
| sección **tipada** | el `model_validator` rechaza el par al construir: el objeto nunca nace |
| sección **opaca** (el default del núcleo) | la coacción falla, la sección va a `uninspected` y `check_dataset` no baja a sus campos |

Implementarlo habría sido añadir **código muerto nuevo**, ejercitable sólo por un test que lo llame
a mano — cobertura fingida. Se distingue del precedente de la guarda del transformer: aquélla ya
existía y quedó inalcanzable; ésta nacería muerta.

**Pero medirlo destapó el hueco que sí sigue vivo**, y es mayor que M-7: cuando una sección queda
opaca e inválida, el usuario lee *«esta sección no se pudo comparar: esta instalación no sabe
leerla»* — y eso es **falso** cuando la causa es un config que el motor rechaza. Vale para las 123
combinaciones, no sólo para el ancla.

**D-ANC-11.** `DatasetCheck` gana `uninspection_reasons: tuple[tuple[str, str], ...]` —extensión
**aditiva**, `uninspected` no cambia—, que publica **por qué** cada sección quedó sin mirar. El
motivo se averigua coaccionando cada sección **por separado**, y ése es el punto fino: la coacción
del config raíz es todo-o-nada, así que una sección inválida deja opacas también a las que estaban
bien. Sale nombrada **la culpable, no el vecindario**; una sección cuya capa no está instalada se
omite en silencio, con el criterio de «`None` significa *no se sabe*» de D-PRE-9.

⚠️ **Su alcance es la API por código y el contrato REST, NO la pantalla — medido, y por eso el
front se revirtió.** El primer intento pintaba el motivo en `PreflightNotice`; midiendo los
endpoints con `TestClient` resultó que por HTTP el caso **no llega**: `ui/routes.py` carga los
dominios y valida antes, así que un config inválido sale **422** de `/api/preflight` sin producir
veredicto. Y el único caso que sí llena `uninspected` en la UI —un extra ausente— no tiene motivo
que dar, así que la frase que ya existía («esta instalación no sabe leerla») **es correcta ahí**.
Pintarlo habría sido añadir una segunda rama muerta el mismo día que se descartó la primera. El
campo se conserva en el DTO y en el payload REST porque `nikodym.check_dataset` es API pública
reexportada y el endpoint transporta el veredicto entero, que es su contrato.

✅ **Y midiendo eso salió el dato que cierra el círculo: D-ANC-1 SÍ llega a la pantalla.**
`/api/validate` responde **200** con `valid=false` y el mensaje íntegro del validador, así que quien
escribe la tasa objetivo en el formulario lo lee **en vivo, sin ejecutar nada** — por la validación,
que era la superficie correcta desde el principio, y no por el preflight.

### 7.3 🔴 D-ANC-12 — el error llegaba a la pantalla MUDO, y sólo se vio abriéndola

Verificando D-ANC-1 en vivo: se activa «PD objetivo», se escribe `0.2`, y el formulario muestra
**«Config inválido · 1 error»**… **y nada más**. El mensaje —bueno, largo y con las tres salidas—
no aparecía por ningún lado.

La causa: un `ConfigError` de sección lo levanta el `model_validator` sobre **la sección entera**,
así que llega con `loc: []`. `buildErrorLookup` lo indexa bajo la cadena vacía y **ningún
`FieldRenderer` reclama esa clave**, porque ninguno tiene el path vacío. El mensaje viajaba en el
`lookup` y nadie lo miraba.

**No es de M-7**: son los **123 `raise`** del §7.1, todos con `loc: []`, y varios se arman con dos
clics. Un usuario veía un contador y ningún texto — peor que el defecto que veníamos a cerrar,
porque al menos aquél publicaba un número.

**D-ANC-12.** Nace `unanchoredError(state)` —helper **puro**, testeable con vitest sin DOM— y la
barra de estado pinta el mensaje sin campo debajo del contador. Tres tests, incluido el control
negativo (un error **con** campo no debe salir por ahí, o se duplicaría).

⚠️ **Y es la razón por la que este defecto sobrevivió tanto:** ningún test podía verlo. Vitest corre
sin DOM, así que nadie renderiza la barra; y del lado Python el endpoint devolvía el mensaje
**correcto**, así que su test pasaba con razón. El defecto vivía exactamente en la juntura que
ninguna de las dos suites cubre.

## 8. Lo que queda declarado, y no es deuda

0. ⚠️ **La demo estática conserva el rótulo anterior hasta su próxima recaptura.**
   `web/src/fixtures/demo/report-f1.html` es una captura de corrida real, y ningún gate la ata a la
   prosa —verificado: la suite completa pasa sin tocarla—, así que seguirá diciendo «con una PD
   objetivo de 23,33 %» donde el motor ya dice «que resultó ser 23,33 %». No es deuda oculta: la
   recaptura tiene su protocolo propio y va en sesión fresca.

1. **La frase «es probable que la corrida falle» de los once avisos del preflight se queda como
   está**, porque con (a) el caso de M-7 deja de llegar al preflight: se rechaza antes. Si algún día
   nace un `unmet_requirement` no-fatal, ese copy hay que partirlo en dos — y entonces sí es
   enmienda, porque afecta a los once.
2. **`max_abs_offset` no es la guarda de este defecto** y no puede serlo (§1.4).
3. **`Resolved[T]` (CRP-3) sigue sin implementar**, y esta enmienda no lo implementa: lo instancia.
   El día que un segundo parámetro necesite lo mismo, ése es el momento de construir el genérico.
