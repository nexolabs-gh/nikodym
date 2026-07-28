# Enmienda SDD — la identidad del config no puede depender de qué importó el proceso

> **Estado: APROBADA (Cami, 2026-07-27) e IMPLEMENTADA.** D-HASH-7 —recalcular la identidad de los
> configs opacos dentro de 1.x— se decidió explícitamente, sabiendo que cambia la clave de
> idempotencia de instalaciones existentes.
>
> **D-HASH-8 nació al programar**, no al diseñar: la primera implementación volvió `config_hash`
> **fallable** y eso habría tumbado el 200 incondicional de `/api/validate`. Queda escrito con su
> razón, que es la conducta esperada en este repo — reabrir un diseño por feedback del código es
> barato; dejar que documento y código se separen en silencio, no.
>
> **Base:** `main` = `c73671b` (CI verde 16/16, `1.7.0` publicado).
> **Autor / Fecha:** DanIA / 2026-07-27.

| Campo | Valor |
|---|---|
| **Problema** | El **mismo** config produce **dos `config_hash` distintos** según si el proceso ya importó la capa de dominio. La identidad criptográfica de una corrida —el ancla del lineage, del model card, del informe y de la idempotencia de MLflow— depende del orden de los `import` |
| **Enmienda a** | SDD-01 §5 (`config_hash` y su promesa de estabilidad), y la docstring de los validadores `_valida_<dominio>` de `core/config/schema.py`, que promete una garantía que no cumple |
| **No toca** | El **blob opaco** del núcleo liviano (SDD-23 §4.1/§9): `import nikodym.core.config` sigue sin arrastrar dominios, y los **18** tests `test_core_valida_<X>_como_blob_opaco_sin_importar_<X>` —más los 43 `test_nikodymconfig_<X>_core_only…`— siguen siendo contrato. Tampoco toca `INFRA_SECTIONS`, la exclusión de `data.load.source`, ni el orden lineage↔resolución que arregló el P0 de `edb3773` |
| **Release** | Cambio de comportamiento: **recalcula la identidad** de los configs que hoy se hashean opacos. Precedente directo: la exclusión de `data.load.source` en `1.4.0`, también corrección de defecto dentro de 1.x |

---

## 1. Lo que la medición dice, antes de diseñar nada

Medido el 2026-07-27 contra el árbol y **contra el servidor real**, porque en este repo el plan
escrito no ha sobrevivido a la primera medición nueve veces seguidas. Scripts en el scratchpad de
la sesión (`m1`…`m7`).

### 1.1 El defecto, reproducido por HTTP

Mismo proceso, mismo request, dos respuestas opuestas según qué se pidió antes:

```
POST /api/validate  {"config":{"binning":{"min_bin_size":-1}}}
  · como PRIMER request  → valid:true,  config_hash:"2d48c594…", errors:[]
  · tras GET /api/schema → valid:false, config_hash:null, loc:["binning","min_bin_size"]
```

Y sobre un config **válido** (el caso que importa para la identidad):

| capa `binning` importada | tipo de la sección | `config_hash` |
|---|---|---|
| no | `dict` (blob opaco) | `8fb0c28b…` |
| sí | `BinningConfig` | `e8afdfca…` |

La divergencia aparece cuando el dict **no coincide** con el `model_dump` del modelo coaccionado:
un campo con default omitido, un tipo sin normalizar. Coaccionar **es** normalizar; sin la capa no
hay normalización.

### 1.2 Lo que se midió y resultó FALSO

Tres hipótesis razonables que la medición refutó. Van escritas para que nadie las vuelva a pagar:

| hipótesis | medición |
|---|---|
| «Afecta al usuario mientras trabaja en la UI» (premisa con que se priorizó el ítem) | **Falsa.** El front no valida hasta tener el schema (`appStore.tsx:107`, `if (schema === null) return`) y `GET /api/schema` importa los dominios del mapa canónico vía `build_full_json_schema()` (verificadas 9 de las 22 entradas, incluidas todas las de F1). El log del servidor confirma el orden real: `/api/schema` → `/api/validate`. Por la UI **no se alcanza** |
| «Reabre el P0 del round-trip por otra vía» | **Falsa.** `save()` en un proceso y `load()` en otro **limpio**, sin la capa importada: los hashes coinciden y `Study.load()` pasa. `save()` escribe el config ya coaccionado y completo, así que el blob recargado vuelve a dar el mismo digest |
| «Con la sección opaca, la ruta del dataset vuelve a contaminar el hash» (el defecto que corrigió 1.4.0) | **Falsa.** El `exclude` anidado `{"data": {"load": {"source": True}}}` **sí** se aplica sobre un `dict` crudo. `/ruta/A` y `/ruta/B` dan el mismo hash con y sin la capa |

Quien sí ve el defecto: un **cliente HTTP directo** contra la API instalable, y el **uso Python puro
con dict** —que es exactamente el camino «100 % por código» del requisito 1 de la visión—.

### 1.3 Lo que hace viable el arreglo

| pregunta que decide el diseño | medición |
|---|---|
| ¿Cuánto cuesta poblar los hooks (importar las capas)? | **0,285 s**, una vez por proceso. No los 2,7 s del P3 del handoff: ésos los paga la resolución al cargar los motores pesados, no el config |
| ¿Existe ya un mecanismo canónico? | Sí. `_DOMAIN_CONFIG_CLASSES` (`core/study.py:79`, 22 dominios) es el mapa, y `build_full_json_schema()` ya lo recorre importando: poblar los hooks es su efecto colateral documentado |
| ¿Cuántos tests rompe que `config_hash` coaccione? | **Cero.** Prototipo desechable medido sobre la suite completa: **4476 passed, 6 skipped**. Verificado además que el prototipo **sí** cierra la brecha (converge a `e8afdfca…`, el hash del coaccionado) y no inventa un tercer digest |

⚠️ **Ese verde no prueba que el cambio sea inocuo para el usuario, sólo que no rompe la suite.**
Dentro de la suite las capas siempre están importadas, así que ningún test vive en el lado opaco de
la brecha. Es la misma trampa que dejó pasar el P0 de ayer.

## 2. Las decisiones

**D-HASH-1 — La identidad es la del config que SE EJECUTARÍA, no la del que se escribió.**
`config_hash` coacciona las secciones de dominio **disponibles** antes de canonicalizar. Razón: esa
semántica ya la adoptó el lineage de facto al arreglar el P0 (`edb3773` congela el lineage
**después** de resolver, o sea sobre el config coaccionado). Tener dos semánticas de identidad
conviviendo en la misma librería era la incoherencia real; esto las unifica en la que ya ganó.

**D-HASH-2 — La coacción vive en `config_hash`, NO en `model_validate`.** El blob opaco es contrato
deliberado del núcleo liviano (SDD-23 §4.1/§9) y tiene 18 tests dedicados que lo fijan a propósito
—61 contando los `core_only`—. Coaccionar en la raíz obligaría a `import nikodym.core.config` a arrastrar dominios
—varios con extras que pueden no estar instalados—. La importación es **perezosa dentro de la
función**, con precedente interno directo: `build_full_json_schema()` hace exactamente eso y vive
en el mismo módulo de núcleo.

**D-HASH-3 — Un extra ausente deja la sección opaca, y eso NO es un fallo.** La garantía que se
promete es acotada y hay que decirla con todas sus letras: *el hash no depende del **orden** de los
imports dentro de una instalación dada*. **No** se promete igualdad entre instalaciones con
distintos extras. El argumento es que un config que necesita un dominio no instalado **no se puede
ejecutar**, así que su identidad no ancla ninguna corrida. Degrada sin romper, igual que
`build_full_json_schema()`.

**D-HASH-4 — La docstring de `_valida_<dominio>` deja de prometer lo que no cumple.** Hoy dice que
exige JSON-canónico *«para no corromper el `config_hash` entre procesos»* — `core/config/schema.py:598`
y sus **14** hermanas, sobre 25 validadores. Eso protege del **no-determinismo del dict**
—sets, floats no finitos— pero no de la brecha blob-vs-coaccionado, que es precisamente una
corrupción del hash entre procesos. Se corrige el texto para que diga lo que sí garantiza. Es
comentario interno, no copy público (no aplica el gate de `test_public_copy.py`).

**D-HASH-5 — `/api/validate` puebla los hooks antes de validar.** Con D-HASH-1 el `config_hash` que
publica el endpoint ya queda correcto en frío, pero `valid` seguiría dependiendo del orden: un
cliente HTTP directo recibiría `valid:true` sobre un config inválido. Reusa el mismo helper de
D-HASH-2, cuesta 0,285 s una única vez y sólo si nadie pidió el schema antes. **No** se cambia el
significado de `valid` (D-PIPE-1 sigue en pie): se hace que signifique lo mismo siempre.

**D-HASH-6 — Se documenta que la UI no era el problema.** La medición de §1.2 va al SDD para que
nadie «arregle» el front por segunda vez. El campo `pipeline` seguirá siendo la red que caza el
config inválido en frío, porque `check_pipeline` resuelve y resolver coacciona.

**D-HASH-8 — `config_hash` sigue siendo TOTAL: si la coacción falla, no propaga.** Salió al
programar, y es un caso que el diseño no había visto: una sección opaca puede llevar un campo que
el schema del dominio prohíbe —el blob lo acepta justamente por no conocer su schema—, y entonces
coaccionar levanta `ValidationError` donde antes había un digest. Propagarlo convertiría una
función de **identidad** en una fallable y rompería llamadores que hoy responden siempre: el 200
incondicional de `/api/validate` pasaría a 500, y el ensamblado del lineage se caería en un camino
que hoy funciona. Se devuelve el hash del config sin coaccionar. No se pierde nada —un config que
no coacciona no se puede ejecutar, mismo argumento que D-HASH-3— y quien debe reportar el error es
el validador, no el hash.

**D-HASH-7 — Cambio de comportamiento declarado en el CHANGELOG.** Un usuario que hoy hashea
configs opacos con campos omitidos verá cambiar su `config_hash`, y con él la clave de idempotencia
de su inventario MLflow. Mismo trato que `1.4.0` dio a `data.load.source`: corrección de defecto
dentro de 1.x, anunciada con ejemplo. **No** se toca el algoritmo de canonicalización, que sigue
estable bajo SemVer 1.x.

## 3. Tests

**El test que prueba el arreglo tiene que correr en SUBPROCESO.** Dentro de la suite las capas ya
están importadas, así que un test «natural» nunca vive en el lado opaco de la brecha y sería un
falso verde — la trampa exacta que dejó pasar el P0 de ayer. El montaje válido es el de `m3_hash.py`:
dos `subprocess` del mismo intérprete, uno importando la capa y otro no, comparando el digest.

1. **Regresión (debe FALLAR contra el código actual):** mismo config, dos subprocesos, hash idéntico.
   Verificarlo fallando antes de aceptarlo por verde.
2. **El blob opaco sigue vivo:** los ~22 `test_core_valida_<X>_como_blob_opaco_sin_importar_<X>` no
   se tocan; su verde es la prueba de que D-HASH-2 no invadió el núcleo liviano.
3. **Extra ausente degrada sin romper:** un dominio cuyo módulo no importa deja la sección opaca y
   `config_hash` responde igual.
4. **Coste acotado:** el hash en proceso frío no dispara la carga de los motores pesados (sólo los
   `config.py` de cada dominio).

## 4. Riesgos y lo que queda abierto

- **El verde de la suite no es evidencia de inocuidad para el usuario** (§1.3). La evidencia real es
  el test en subproceso y la verificación desde PyPI en un venv limpio.
- **Un `config_hash` que cambia invalida anclas de idempotencia** en instalaciones existentes. Es el
  costo consciente de D-HASH-7; la alternativa —dejar dos identidades para el mismo config— es peor
  en una librería cuyo argumento es la reproducibilidad regulatoria.
- **Abierto:** si conviene además **cachear** el resultado de poblar los hooks en un módulo del
  núcleo, o dejar que `sys.modules` haga de caché (que ya lo hace). Se decide al programar; no
  cambia ningún contrato.
