# Enmienda — la gobernanza tiene que ser VISIBLE en la interfaz

| Campo | Valor |
|---|---|
| **Familia** | D-GOB (continúa: D-GOB-10 … D-GOB-16) |
| **Estado** | **APROBADA por Cami el 2026-09-03** (las cuatro respuestas de §8, sin cambios). **Revisión independiente ejecutada el 2026-09-03** (Codex, `needs-attention`): este documento se corrigió en §0.3–§0.6, §3, §6, §7 y §8.1. **Los tres puntos de §8.1 los respondió Cami el 2026-09-07** (sí, sí, latente). **D-GOB-10 implementada y gateada el 2026-09-07 (S2b)**; **D-GOB-11/12/13/14 implementadas y gateadas el 2026-09-07 (S3)**; **D-GOB-15/16 implementadas y gateadas el 2026-09-08 (S4)**: enmienda COMPLETA, abierto 1 de D-GOB cerrado |
| **Depende de** | [`_ENMIENDA-GOBERNANZA-ALCANZABLE.md`](_ENMIENDA-GOBERNANZA-ALCANZABLE.md) (D-GOB-1…9), SDD-23 (interfaz), D-SUB, D-OBL, D-VIS, D-FX-8 |
| **Lo consumen** | `ui/jobs.py`, `ui/presets.py`, `core/config/schema.py`, `web/src/lib/schema.ts`, `web/src/components/ResultsTab.tsx` |
| **Autor / Fecha** | Claude Code · 2026-09-02 |

> Cierra el **abierto 1 de D-GOB** —el último resto del bloqueador 3 del censo del 2026-08-26—.
> Toda la medición de este documento es del 2026-09-02 sobre el público
> `3cad020682cedd09c6437ec71f8bf71e790858e5`, con la interfaz **en ejecución**.

---

## 0. Qué corrige de lo ya escrito

Medir cambió el planteamiento **dos veces**, y las dos cambian lo que hay que construir. Ambas
correcciones ya están aplicadas en `DECISIONES-VIGENTES.md` §D-GOB.

1. 🔴 **«`build_full_json_schema` nunca expande las secciones INFRA» es FALSO**, y también lo es
   «entregarlo cambia el tratamiento de INFRA en la interfaz». Lo que la función expande es
   exactamente `_DOMAIN_CONFIG_CLASSES`, y **`report` está ahí siendo INFRA**: se expande en el
   schema, es una de las 14 `CONFIG_SECTIONS` del front y aparece como «Informe» en el sidebar de
   **los 10 trabajos**. Hay precedente entregado; no hay mecanismo nuevo que inventar.
2. 🔴 **«No hay ruta de UI para encender `governance`» es DEMASIADO FUERTE.** Sí la hay: importar un
   YAML. Está medida de punta a punta (§1.1). El problema real no es que la capacidad sea
   inalcanzable, sino que es **indescubrible** — y que aun encendida **no se ve en ninguna
   pantalla**.

El encuadre correcto, entonces, no es «entregar la gobernanza a la UI» sino **«hacerla descubrible y
mostrar lo que produce»**. Es menos mecanismo del que la enmienda anterior temía y más copy público
del que había contado.

**Y la revisión independiente del 2026-09-03 —más la medición que la acompañó— lo cambió una
tercera vez.** Cuatro correcciones más, ya aplicadas en §3, §6 y §7; lo que exige un OK nuevo va
en §8.1. La revisión (Codex, rango `5d6aa68..a9a1668`, `needs-attention`) está archivada íntegra
en el repo privado.

3. 🔴 **El censo de consumidores de D-GOB-10 era incompleto y su loader estaba subespecificado.**
   La versión anterior mandaba que `build_full_json_schema()` empotrara «ambos mapas» y dejaba
   `cargar_configs_de_dominio()` intacto, pero `/api/validate` y el preflight sólo llaman a ese
   loader (D-HASH-5). Reproducido en proceso fresco: un `governance` con
   `review_period_months: 999` **se acepta** antes de que alguien importe `nikodym.governance` y
   **se rechaza** después; y el `build_full_json_schema()` de hoy tampoco lo importa. Es la
   dependencia del orden de imports que D-HASH-5 cerró para los dominios, recreada para la sección
   que esta enmienda pone en pantalla. §3 D-GOB-10 fija ahora dos loaders y el censo **por
   semántica**, no por nombre.

   > 🔴 **Precisión medida el 2026-09-07 (S2b), con control negativo.** El hueco existe **en el
   > motor**: en proceso fresco `NikodymConfig` acepta el 999 sin loader y **también tras
   > `cargar_configs_de_dominio()`**, que no importa la capa; sólo la unión lo cierra. Por la ruta
   > `/api/validate` **no se manifestaba**: `nikodym.ui.serializers` importa `nikodym.governance`
   > al cargarse, así que dejar sólo el loader de dominios en `validate_config` no enrojece ningún
   > gate honesto. El gate §6.9 se reformuló: el oráculo que discrimina vive en el motor; el de la
   > interfaz queda como contrato («mismo veredicto antes y después del schema»), y la llamada a
   > la unión en las rutas es blindaje del contrato, no la corrección de un defecto observable.
4. 🔴 **D-GOB-11 no se puede entregar sola: cinco gates la atan a D-GOB-12/13/14.** Medido sobre
   `a9a1668`: `test_jobs_catalogo.py` es bidireccional —toda sección de un trabajo debe estar en
   `CONFIG_SECTIONS` y viceversa—; `test_copy_del_formulario.py` recorre las secciones del
   formulario y pone rojo el «True»/«False» de `publish_to_inventory` y
   `require_overlay_justification` (D-GOB-13); `test_jobs_decisiones.py` exige una pregunta para
   todo campo obligatorio de una sección del formulario, o sea `purpose` (D-GOB-12);
   `test_jobs_ejecutables.py` siembra el esqueleto de cada trabajo con **todas** sus secciones
   encendidas, y `purpose` sin default lo deja inválido; y los goldens de
   `test_effective_defaults.py`, `jobs.test.ts` y `RunTab.test.ts` cuentan 14 secciones y 9/4
   pestañas por trabajo. La capa «10/11» del plan no existe como unidad verde: la capa es
   **D-GOB-10** sola, y después **D-GOB-11/12/13/14 juntas**.
5. 🔴 **«Apagada de fábrica» sólo estaba definida para los presets.** `jobSkeleton`
   (`web/src/lib/jobs.ts`) y su réplica Python siembran **encendida** toda sección que el trabajo
   declara, con la proyección canónica de sus defaults. Con `governance` en los 10 trabajos, entrar
   por cualquiera la sembraría encendida y con `purpose` pendiente: la corrida no arrancaría hasta
   declararlo, en los diez. Eso contradice el «gesto explícito del usuario» de D-GOB-11 y no lo
   decidió nadie. Va a §8.1 como decisión de Cami.
6. 🔴 **D-GOB-12 prometía lo que el motor no cumple.** `GovernanceConfig.purpose` es un `str`
   obligatorio sin más: `""`, `"   "` y `"\t\n"` construyen (reproducido). Y la tarjeta de
   decisiones marca contestada una decisión escalar sin formas de respuesta por **presencia**
   (`decisionStatuses`: `hasAtPath` y cero huecos), así que `purpose: ""` saldría «contestada» y
   la ficha se firmaría sin propósito. Honrar D-GOB-12 exige una validación nueva en
   `GovernanceConfig`, que §7 excluía expresamente: va a §8.1.

---

## 1. El defecto, medido

### 1.1 La sección funciona hoy desde la interfaz, y nadie puede descubrirla

Corrida real por el navegador, sin tocar código: preset F1 + bloque `governance:` cargado con
**«Cargar un YAML existente»**, dataset `consumo_comportamiento` (6.000 filas).

| Eslabón | Medición |
|---|---|
| `POST /api/config/from-yaml` | conserva `governance` íntegro; `to-yaml` lo devuelve (round-trip) |
| Store del front | guarda el config entero; **nada lo poda** (`CONFIG_SECTIONS` sólo filtra qué se *pinta*) |
| Rótulo de la interfaz | «El config activo viene de "f1-con-gobernanza.yaml"» |
| `POST /api/run` | envía el config completo; la corrida termina `done` |
| `GET /api/results/<run_id>` | **card completo**: 24 métricas, 41 decisiones, secciones CT-2 de `performance` y `stability`, y el `purpose` que escribió el usuario |

`run_id` de la evidencia: `4b04cbdeed9a45d5b701aabbb8760eff`.

Esto es una **capacidad entregada y escondida**: quien no sepa que `governance` existe en el schema
del motor no tiene forma de llegar a ella desde la interfaz. Y el schema que la interfaz sirve no se
lo va a decir: allí `governance` es un *stub* opaco `{"default": null, "title", "description"}`, sin
`properties`.

### 1.2 Encendida o no, el card no se ve en ninguna superficie

Sobre esa misma corrida —la que **sí** tiene card completo en su API—:

- **Pantalla «Resultados»**: ninguna de trece expresiones buscadas aparece en el texto renderizado
  («Model card», «Ficha del modelo», «Gobernanza», «Propósito», «Supuestos», «Limitaciones»,
  `model_card`, `purpose`, `next_review`…), y el HTML renderizado no menciona `model_card` ni una
  vez. `ResultsTab.tsx` enumera `binning`, `calibration`, `lineage`, `model`, `performance`,
  `provisioning*`, `scorecard` y `stability`; `model_card` no está.
- **Bundle servido** (1,65 MB): **cero** ocurrencias de `model_card`, `modelCard`,
  `metric_sections`, «Model card» y «Ficha del modelo».
- **Informe**: su única ocurrencia de `model_card` es la `CardSection` `model.model_card` del anexo
  C.4 —el card **del modelo PD**, otra cosa— y el `purpose` declarado por el usuario **no aparece**
  en el documento, pese a que el informe sí tiene un capítulo «Limitaciones y supuestos».

El dato recorre motor → API → y muere ahí. Es exactamente el patrón que D-VIS declaró inaceptable
para los errores, aplicado ahora a la evidencia de gobierno.

### 1.3 Lo que falta para el formulario, medido

| Qué | Estado |
|---|---|
| `governance` en `_DOMAIN_CONFIG_CLASSES` (22 entradas) | **ausente** → el schema la deja opaca |
| `governance` en `CONFIG_SECTIONS` del front (14 entradas) | **ausente** → no hay pantalla ni sidebar |
| `governance` en `sections` de los 10 trabajos | **ausente** en los 10 |
| Campos de `GovernanceConfig` con `ui_widget`/`ui_group` | **5 de 13** (grupo «Inventario») |
| Campos sin ninguno | **8 de 13**, incluido el obligatorio `purpose` |

---

## 2. Lo que ya está construido y no hay que inventar

### 2.1 `report` es el precedente entregado de sección INFRA con formulario

`report` está en `INFRA_SECTIONS` —no entra al `config_hash`— **y** es una sección de formulario de
primera clase, presente en los 10 trabajos. Es la prueba viva de que una sección puede ser
infraestructura para la identidad de la corrida y aun así tener pantalla. `governance` pide
exactamente el mismo trato.

### 2.2 …pero `report` llegó ahí por una puerta que `governance` no puede usar

🔴 **Medición que cambia el diseño.** `report` está en `_DOMAIN_CONFIG_CLASSES` porque **es un
dominio orquestable**: aparece en `_DEFAULT_DOMAIN_ORDER` —al final, «la foto de todo lo que
corrió»— y tiene su `Step`. Y `Study._default_step_names()` deriva el pipeline **de esa lista**: toda
sección presente ahí con config no nulo se convierte en un paso a resolver contra el `REGISTRY`.

Hoy los dos mapas tienen **exactamente el mismo conjunto de 22 claves**. `governance` **no tiene
`Step`** y no debe tenerlo: no calcula nada, describe. Por lo tanto:

- meterla en `_DEFAULT_DOMAIN_ORDER` haría que `nikodym.run` intentara resolver un paso inexistente;
- meterla sólo en `_DOMAIN_CONFIG_CLASSES` rompe la correspondencia exacta entre ambas listas y
  declara «dominio orquestable» algo que no lo es.

De ahí D-GOB-10. El atajo que parecía obvio —«añadirla al mapa, como `report`»— está **medido y
descartado**, no supuesto.

### 2.3 El front ya declara el campo, laxo y sin consumidor

`results-types.ts` ya tiene `model_card: Record<string, unknown> | null` en `ResultsResponse`, con
el comentario «`model_card` viene null en el preset estándar (forma aún no explotada por la UI →
laxa)». El contrato existe; lo que no existe es el tipo real ni quien lo pinte.

---

## 3. Las decisiones que se proponen

### D-GOB-10 — `governance` se expande por una lista propia, no por el mapa de dominios

Se añade a `core/study.py` un mapa hermano y explícito:

```python
_INFRA_CONFIG_CLASSES: Final[dict[str, tuple[str, str]]] = {
    "governance": ("nikodym.governance.config", "GovernanceConfig"),
}
```

`cargar_configs_de_dominio()` conserva su significado y su nombre —**dominios orquestables**, los
que fijan pasos y entran al `config_hash`— y gana dos funciones hermanas en
`core/config/schema.py` (corrección §0.3):

- `cargar_configs_de_infra()`: el mismo loader, sobre `_INFRA_CONFIG_CLASSES`.
- `cargar_configs_expandibles()`: la unión ordenada de ambos, **las secciones que el schema
  expande**, que es lo que el formulario puede ofrecer.

`build_full_json_schema()` empota las secciones de la unión. `_DEFAULT_DOMAIN_ORDER` **no se
toca**: `governance` no es un paso y no debe aparecer en ningún pipeline.

**Por qué así y no reutilizando el mapa de dominios:** §2.2. Un mapa que se llama «clases de config
de dominio» y que además fija el orden de ejecución no puede alojar una sección sin `Step` sin
mentir sobre las dos cosas. `audit` y `tracking` quedan **fuera** de este mapa: esta enmienda no los
pone en pantalla (§7).

**Lo que arrastra, medido y clasificado por lo que cada consumidor PREGUNTA** (§0.3) —hay que
actualizarlo, no descubrirlo tarde—:

| Consumidor | Qué pregunta | Loader que le corresponde | Capa |
|---|---|---|---|
| `core/config/schema.py::build_full_json_schema` | ¿qué secciones expando? | unión | D-GOB-10 |
| `scripts/gen_schema_fixture.py` (guarda de opacidad) | ¿qué debe salir expandido? | unión | D-GOB-10 |
| `tests/unit/test_ui_schema_fixture.py` (`_dominios_disponibles` y la resta de la línea 148) | ¿qué nodos comparo con el fixture? | unión | D-GOB-10 |
| `core/config/effective_defaults.py` | ¿qué secciones tienen mapa de hijos? (D-FX-10: schema y catálogo dicen lo mismo) | unión | D-GOB-10 |
| `ui/routes.py::validate_config` y `::preflight_dataset` (D-HASH-5) | ¿`valid` significa lo mismo siempre? | unión | D-GOB-10 |
| `core/config/hashing.py:94` | ¿hay un dominio opaco que coaccionar antes de hashear? | dominios, **sin cambio**: `governance` está en `INFRA_SECTIONS` y no entra al digest | — |
| `core/dataset_check.py` (`_secciones_activas`, `_motivos_de_secciones_opacas`) | ¿qué corre? ¿qué columna no pude mirar? | dominios, **sin cambio**: `governance` no corre ni declara roles de columna | — |
| `core/study.py::_coerce_domain_config` | ¿qué paso resuelvo? | dominios, **sin cambio** | — |
| `tests/unit/test_effective_defaults.py`: `_pares_modelo_mapa` y el gate D-FX-10 (`test_un_extra_ausente_deja_su_dominio_sin_defaults_fabricados`) | ¿qué publica el **catálogo** de defaults? (espejo del generador, no del formulario) | unión | D-GOB-10 |
| `ui/option_surface.py`, `tests/unit/test_jobs_decisiones.py`, `test_copy_del_formulario.py`, `test_effective_defaults.py` (sólo sus espejos del formulario: `SECCIONES_ESPERADAS`, `ANCLAS_POR_SECCION`), `test_extra_ui_cubre_el_formulario.py`, `test_invariantes_previas.py` | ¿qué ofrece el **formulario**? | unión, **cuando la sección entre al formulario** | D-GOB-11 |

**El `config_hash` no se mueve**: `governance` sigue en `INFRA_SECTIONS`, igual que `report`. Se
gatea explícitamente, como se hizo con `audit` en D-GOB-8. Y **la validez tampoco depende del
orden de imports**: se gatea en proceso fresco (§6.9).

> 🔴 **Corrección medida el 2026-09-07, al implementar (S2b).** El censo por semántica tenía dos
> consumidores de `test_effective_defaults.py` bajo D-GOB-11 que preguntan por el **catálogo** y no
> por el formulario: `_pares_modelo_mapa` y el gate D-FX-10. Con el loader de dominios, el gate de
> paridad habría dejado sin comparar las 13 hojas de `governance` **en silencio** y el de D-FX-10
> la habría saltado. Fila añadida arriba. El resto de consumidores del árbol que importan los mapas
> o el loader —`testing/metrics.py`, `scorecard/bundle.py`, el arnés H9R y una treintena de
> tests— preguntan «¿qué corre?» o «que la sección esté tipada antes de `check_dataset`», y no
> cambian; la clasificación completa, línea a línea, vive en el `HANDOFF` de S2b. Medido al cerrar
> la capa: `_DEFAULT_DOMAIN_ORDER` intacta, `config_hash` de los cuatro presets intacto, golden del
> formulario intacto (394 hojas), golden del catálogo **1064 → 1076** (−1 descriptor de sección,
> +13 hojas, 0 valores alterados) y `$defs` 104 → 104, porque `GovernanceConfig` no tiene
> submodelos. Un consumidor más, que ningún censo nombró porque barre el **fixture** y no los
> mapas: el gate de portada de D-JUR (`test_portada_sin_jurisdiccion`) vio «CMF» en
> `governance.motor` y la sección entra a su lista de exentas con razón —el campo enumera los
> motores y el copy aprobado de D-GOB-13 también nombra CMF—; la suite completa lo destapó
> (1 failed / 6367 passed) y es lo único que enrojeció.

### D-GOB-11 — la sección entra al front como una más, en los 10 trabajos, APAGADA de fábrica

`governance` se suma a `CONFIG_SECTIONS` (pasa de 14 a 15) con etiqueta **«Gobernanza»**, y a las
`sections` de los 10 trabajos, como `report`. Sigue **apagada** en los cuatro presets: D-GOB-8 ya
decidió que el motor no inventa un propósito, y esta enmienda no lo reabre. Encenderla es un gesto
explícito del usuario, con el mismo interruptor de sección que el resto.

**Lo que la medición añade (§0.4, §0.5).** Esta decisión **no es separable** de D-GOB-12/13/14:
cinco gates vigentes las atan y ninguno se ablanda, así que se implementan juntas, después de
D-GOB-10. Y «apagada de fábrica» tiene que decir también qué hace el **esqueleto de un trabajo**,
no sólo los presets: hoy `jobSkeleton` siembra encendida toda sección del trabajo. La opción que se
recomienda en §8.1 es que el catálogo declare `governance` como **sección latente** —en el sidebar
de los 10 trabajos, sembrada en `null`— y que una decisión obligatoria de una sección apagada **no
cuente como pendiente**; encenderla desde su interruptor es lo que activa la pregunta por `purpose`.

### D-GOB-12 — `purpose` es una decisión obligatoria del usuario, no un campo más

`purpose` es `DATO-INSTITUCIONAL`: sólo la institución puede fijarlo. Va al bloque **«Tus
decisiones»** de Configuración —donde ya viven «¿qué define a un cliente malo?» y «¿cómo separas la
muestra?»—, con `ui_widget: textarea`. Con la sección encendida y `purpose` vacío, la corrida **no
arranca** y la interfaz dice qué falta y dónde, por la maquinaria de D-OBL/D-EXI que ya existe.

**Corrección de la revisión (§0.6).** Para que «`purpose` vacío no arranca» sea verdad hacen falta
tres cosas que hoy no existen, una por capa: (a) `GovernanceConfig.purpose` rechaza el texto en
blanco —se normaliza con `strip()` y exige al menos un carácter—, que es un cambio de validación en
una superficie **experimental** (`nikodym.governance`, fuera de la garantía SemVer 1.x) y por eso va
a §8.1; (b) `/api/validate` lo rechaza con el mismo criterio, por D-HASH-5 y el loader de §3
D-GOB-10; (c) la tarjeta de decisiones trata una decisión **escalar sin formas de respuesta** como
pendiente cuando su valor está en blanco —hoy `huecosPendientes` sólo mira `slots`, y una decisión
sin formas no tiene ninguno—. Con `ui_widget: textarea` el control ya existe; lo que falta es el
criterio.

### D-GOB-13 — los 13 campos reciben copy público escrito para una persona

Al pintarse la sección, **las 13 descripciones pasan a ser copy público** (tooltips derivados de
Pydantic, por `AGENTS.md`) — no sólo las 8 sin widget. Hoy todas están escritas para desarrollador.
Esta tabla **es lo que Cami aprueba**:

| Campo | Hoy | Propuesto |
|---|---|---|
| `model_name` | «Identidad en el inventario (clave del MLflow Registry).» | Nombre con el que este modelo queda registrado en tu inventario. Si lo publicas a MLflow, es la clave con la que lo encontrarás ahí. |
| `purpose` | «Declaración de propósito (SR 11-7); obligatoria para el model card.» | Para qué se va a usar este modelo y sobre qué cartera decide. Lo escribe tu institución: el motor no puede inventarlo, y sin esto la ficha del modelo no se emite. |
| `assumptions` | «Supuestos de desarrollo que se copian al model card.» | Los supuestos con los que se construyó el modelo. Se copian tal cual a la ficha, para que quien la lea sepa bajo qué condiciones vale. |
| `limitations` | «Limitaciones de uso que se copian al model card.» | Dónde **no** deberías usar este modelo. Se copian tal cual a la ficha, y son lo primero que mira una validación independiente. |
| `review_period_months` | «next_review_date = fecha de emisión + este periodo (SR 11-7).» | Cada cuántos meses toca revisar el modelo. La ficha calcula con esto la fecha de la próxima revisión, contada desde su emisión. |
| `publish_to_inventory` | «True requiere el extra tracking; False genera solo evidencia local.» | Si además de dejar la evidencia en tu carpeta quieres publicar el modelo a un inventario MLflow. Pide instalar el extra «tracking»; si lo dejas en no, todo queda local. |
| `require_overlay_justification` | «True: un overlay sin justificación es error anti earnings-management.» | Exige escribir el motivo cada vez que alguien ajusta a mano un resultado del modelo. Un ajuste sin motivo detiene la corrida: es la defensa contra maquillar cifras. |
| `cartera` | «…se publica como tag nikodym.cartera. Es descriptivo del inventario: no altera ningún cálculo.» | El segmento de cartera de este modelo, con el nombre que uses en tu institución. Es descriptivo: no cambia ningún cálculo. |
| `motor` | «Separación de motores CMF/IFRS9/scoring; tag nikodym.motor.» | Qué motor documenta esta ficha: scoring, provisiones CMF o IFRS 9. Sirve para no mezclar modelos distintos en el mismo inventario. |
| `fase` | «Fase de construcción del modelo; tag nikodym.fase.» | En qué punto de su construcción está el modelo. Queda escrito en la ficha para que se lea en contexto. |
| `estado_validacion` | «Ciclo de vida de effective challenge; tag nikodym.estado_validacion. Es ortogonal a los aliases de despliegue.» | En qué punto va la revisión independiente del modelo. Es aparte de si está o no en producción. |
| `author` | «Email o identidad del responsable; tag nikodym.autor.» | Quién responde por este modelo: correo o identificación de la persona o el equipo. |
| `scenario_log_filename` | — | **No se expone** (D-GOB-14). |

Los códigos internos (`nikodym.*` como tags, «SR 11-7», «effective challenge») salen del copy
público y se conservan donde corresponde: comentarios y SDD.

### D-GOB-14 — `scenario_log_filename` no se expone: es una subsección inerte

D-GOB-6 decidió **no escribir** `scenario_log.jsonl` porque no tiene productor, y que un archivo
vacío sería teatro. Exponer en el formulario el nombre de un archivo que nunca se escribe es
precisamente lo que D-SUB prohíbe. El campo se queda en el config para quien lo use por código, y
**fuera** de la superficie de la UI hasta que exista su productor.

> 🔴 **Implementación medida el 2026-09-07 (S3), D-GOB-11/12/13/14 juntas.** Lo que el texto de
> arriba deja abierto y la implementación fijó:
>
> - **El campo nuevo del catálogo (§8.1-3) se llama `latent_sections`.** La latencia se declara
>   por sección en `ui/jobs.py` (`_SECCIONES_LATENTES`, con su razón) y `list_jobs` la publica por
>   trabajo; `jobSkeleton` gana el paso `apagarSeccionesLatentes`, que escribe `null` explícito
>   —no omite la clave— para que dos entradas al mismo trabajo produzcan el mismo config (D-JOB-9).
>   Un gate impide que un override apunte a una sección latente.
> - **El cambio de criterio de la tarjeta es un cuarto estado, `dormant`**, excluyente con los
>   otros tres y decidido por el config (`config[sección]` en `null`), no por el catálogo: vale
>   igual para `survival` apagada a mano en «PD lifetime». Una decisión dormida no cuenta en
>   «Esto lo decides tú» ni en «quedan otras decisiones», y no ofrece «Ir al campo» porque el
>   control no está montado.
> - **La decisión escalar sin formas (§0.6-c)** está pendiente mientras su dato esté en blanco; y
>   `estaVacio` trata un texto de solo espacios como vacío para todos los huecos, el mismo criterio
>   que el `strip()` del motor.
> - **D-GOB-13, dos detalles de presentación:** el énfasis Markdown de «**no**» en `limitations`
>   no viaja al tooltip (las palabras son las mismas), y el tope de 160 caracteres del placeholder
>   —`test_copy_del_formulario`— **no aplica a un `textarea`** porque `TextareaField` no pasa
>   `placeholder` a su control: es una precisión del gate al front real, anclada a su fuente, y no
>   una relajación; sin ella el copy aprobado de `purpose` (162 caracteres) habría tenido que
>   reescribirse. Grupos del formulario: «Inventario», «Ficha del modelo», «Ajustes manuales».
> - **Consecuencias que la tabla §3 no enumeraba**, todas declaradas con razón: los tres `Literal`
>   de `governance` son tags descriptivos y no abanico (D-ABA-3), `governance` es exenta de
>   invariantes previas y declara extra `None` en el gate de `[ui]`; el ledger de opciones crece
>   475 → 491 pares. Goldens con baseline por `git archive`: formulario 513 → 527 y paridad
>   396 → 410 (los 12 campos visibles más `assumptions[]` y `limitations[]`; `scenario_log_filename`
>   ausente), catálogo 1076 y `$defs` 104 intactos, como predijo S2b.

### D-GOB-15 — el panel de Resultados pinta «Ficha del modelo», con guard por presencia

Sección nueva en `ResultsTab.tsx`, **inmediatamente después de «Artefactos de la corrida»**: es la
identidad de gobierno de la corrida y va junto al lineage, no perdida al final. Contenido: propósito,
supuestos y limitaciones; fechas de emisión y de próxima revisión; el resumen de métricas por
dominio; y el conteo de decisiones registradas con acceso a su detalle.

**Guard por presencia, nunca `!`**: `model_card` es `null` en toda corrida sin `governance` —incluidos
los tres fixtures de la demo— y la sección simplemente no se renderiza. No se fabrica un card
ausente ni se pinta un bloque vacío que aparente un control que no corrió.

### D-GOB-16 — el tipo deja de ser laxo

`model_card: Record<string, unknown> | null` pasa a una interfaz `ModelCard` explícita en
`results-types.ts`, derivada de lo que el serializador emite hoy —19 claves, medidas sobre la
respuesta real—. Un tipo laxo con consumidor es una invitación a `any`.

> 🔴 **Implementación medida el 2026-09-08 (S4), D-GOB-15/16 juntas.** Lo que el texto de arriba
> deja abierto y la implementación fijó:
>
> - **La premisa «cero “Ficha del modelo” en el bundle» (§1.2, §6.7) dejó de ser cierta con S3**:
>   el rótulo es el `ui_group` de cuatro campos de `GovernanceConfig` y viaja en `schema.json`, que
>   se empaqueta (4 ocurrencias medidas antes de S4). El gate del bundle mide lo que aportan los
>   fixtures empaquetados y exige al menos una ocurrencia propia de cada rótulo de la sección:
>   «Ficha del modelo» 4 → 5; «Próxima revisión», «Decisiones registradas» y «Métricas por
>   dominio» 0 → 1; `model_card` 0 → 2.
> - **«Fecha de emisión» es `review_date`**: la que el builder fija al construir la ficha y desde
>   la que cuenta `review_period_months` (así lo dice el copy aprobado de ese campo). `created_at`
>   es la marca de la corrida y ya se lee como «ejecutada» en la procedencia. Las dos fechas se
>   pintan como fecha calendario (AAAA-MM-DD), con la marca completa en el `title`.
> - **«Resumen de métricas por dominio»** = las métricas planas (D-GOB-2) agrupadas por su prefijo,
>   rotuladas con la sección del formulario, más la evidencia CT-2 del dominio (D-GOB-3/5)
>   aplanada a filas `subsección · clave → valor`. Nada se recalcula ni se interpreta; lo vacío se
>   marca ausente, no se omite.
> - **Lo que la ficha no pinta se declara con razón** (`MODEL_CARD_NO_PINTADO`, mismo gate en dos
>   sentidos que la procedencia): identidad y hashes, `created_at`, entorno, `data_description` y
>   `determinism_caveats` —que el motor ya copia dentro de las limitaciones—.
> - **El tipo tiene tres anidados** (`ModelCardDecision`, `ModelCardEnvironment`,
>   `ModelCardDataDescription`), en el orden de sus modelos Pydantic, y `metric_sections` se tipa
>   `Record<string, Record<string, unknown>>` porque `_publicar_metric_sections` exige un
>   `Mapping` por dominio. Las 19 claves se remidieron sobre una corrida real por el formulario de
>   S3 (`b9633af1…`, 41 decisiones), anidados incluidos.
> - **Vitest sobre el componente sin DOM ni dependencias nuevas**: `ResultsTab` se parte en un
>   wrapper del store más `ResultsPanel` por props, y el test renderiza el panel real con
>   `react-dom/server` (con card, con `null`, con los tres fixtures de la demo enteros y con una
>   corrida fallida). Los tres fixtures siguen con `model_card: null` y sin recaptura.

---

## 4. Contratos de datos (I/O)

- **Entrada**: la sección `governance` del config, tal como el motor ya la valida. Esta enmienda
  **no toca `GovernanceConfig`** salvo los `json_schema_extra` de presentación (widget, grupo) y las
  descripciones.
- **Salida**: `GET /api/results/<run_id>.model_card`, que ya existe y ya viaja completo. Esta
  enmienda **no cambia el payload**: sólo lo tipa y lo pinta.
- **Invariante**: sin `governance`, `model_card` es `null` y ninguna superficie nueva aparece. El
  comportamiento de toda corrida existente queda **byte-idéntico**.

## 5. Casos borde y errores

| Caso | Comportamiento propuesto |
|---|---|
| Sección apagada | Nada cambia; `model_card: null`; la sección de Resultados no se renderiza |
| Encendida con `purpose` vacío | La corrida no arranca; la UI dice qué falta y salta al campo (D-OBL/D-EXI) |
| Corrida `failed` con card parcial | El serializador ya devuelve `null` si el card no se puede construir; la sección no aparece |
| `publish_to_inventory` sin el extra `tracking` | El error ruidoso de `assemble_run` se conserva; la UI lo muestra como cualquier error de corrida (D-VIS) |
| Fixtures de la demo (`model_card: null`) | Siguen válidos y sin recaptura: el guard por presencia los cubre |

## 6. Tests y controles negativos preespecificados

1. **El schema expande `governance`** con sus `properties`, y `report` sigue expandida — control
   negativo: quitarla del mapa INFRA deja el *stub* opaco y pone rojo.
2. **`_DEFAULT_DOMAIN_ORDER` no contiene `governance`** — control negativo: añadirla hace que
   `nikodym.run` intente resolver un paso inexistente. Gate en ambos sentidos, como D-GOB-4.
3. **El `config_hash` de los cuatro presets no se mueve** al expandir `governance` — el mismo gate
   que ya existe para `audit`.
4. **Los 10 trabajos ofrecen la sección** y sigue apagada de fábrica en los cuatro presets.
5. **`purpose` vacío con la sección encendida no corre**, y el error nombra el campo.
6. **`scenario_log_filename` no aparece** en la superficie de opciones — control negativo:
   exponerlo pone rojo (mismo par que D-SUB).
7. **Con card, la pantalla lo pinta; sin card, no hay bloque vacío.** Vitest sobre el componente
   **más** recorrido por navegador sobre la UI viva: el bundle servido debe pasar de **cero** a
   contener «Ficha del modelo», que es el gate que hoy falla.
8. **Copy público**: ningún código interno (`nikodym.`, `SR 11-7`, `FALTA-DATO`) en los tooltips
   renderizados.
9. **La validez de `governance` no depende del orden de imports** (D-HASH-5 sobre la sección
   nueva): en un proceso fresco, `/api/validate` rechaza `review_period_months: 999` **antes** y
   **después** de pedir `/api/schema`, con el mismo veredicto. **Reformulado el 2026-09-07
   (§0.3)**: el oráculo que discrimina el loader es el del motor —`NikodymConfig` acepta el 999
   sin loader y tras el loader de dominios, y lo rechaza tras la unión— y su control negativo es
   dejar la unión en sólo dominios, que pone rojo. Dejar sólo el loader de dominios en
   `validate_config` **no** enrojece: `nikodym.ui.serializers` ya importa la capa; ese test queda
   como contrato de la interfaz.
10. **`purpose` en blanco se rechaza en las tres capas**: `GovernanceConfig` levanta con `""`,
    `"   "` y `"\t\n"`; `/api/validate` devuelve `valid=false` con el `loc` del campo; y la
    tarjeta de decisiones lo muestra pendiente, no contestado. Depende del OK de §8.1.
11. **Un trabajo con `governance` latente sigue siendo ejecutable** (`test_jobs_ejecutables`), y
    con la sección encendida y `purpose` pendiente la tarjeta lo dice y la corrida no arranca.
    Depende del OK de §8.1.

Todo cierre incluye además regenerar `gen_schema_fixture` y `gen_jobs_fixture`, revisar su diff y
reconstruir el bundle (runbook §5).

## 7. Lo que esta enmienda NO hace

- **No pone `audit` ni `tracking` en pantalla.** `audit` ya se enciende solo en los presets y la
  interfaz cablea su trail; `tracking` exige un servidor MLflow. Ninguno se pide desde el formulario.
- **No añade el capítulo de model card al informe.** Está medido que falta (§1.2) y sigue anotado
  como deuda adyacente; entra en §8 como decisión de Cami, no se cuela aquí.
- **No recaptura la demo** (D-GOB-9 conserva su OK propio).
- **No cambia `GovernanceConfig`** en campos ni tipos. La **única** validación nueva es la de
  `purpose` en blanco (§3 D-GOB-12), y sólo si Cami la aprueba en §8.1; sin ese OK, D-GOB-12 no
  se puede cumplir tal como está escrita, y esta enmienda lo dice en vez de prometerlo.
- **No reabre D-GOB-1…9**, ni la ruptura ya aceptada el 2026-09-02.
- **No toca el arnés H9R, la puerta H9R ni `30-readiness-integral.md` §6.1.**

## 8. Lo que Cami decide

1. **¿Se aprueba la enmienda D-GOB-10…16 tal como está?** Es el último resto del bloqueador 3.
2. **¿Se aprueba el copy público de la tabla de D-GOB-13?** Son 13 textos que van a la cara pública
   del producto; es la parte que no puede quedar a criterio del agente.
3. **¿El capítulo de model card en el informe entra en este alcance o se difiere?** Medido: el
   informe no lleva el propósito declarado por el usuario. Recomendación: **diferirlo** — el informe
   tiene su propio contrato de capítulos y mezclarlo aquí convierte dos trabajos en cuatro.
4. **¿La sección va en los 10 trabajos o sólo en los que emiten informe?** Hoy coinciden (los 10
   llevan `report`). Recomendación: **los 10**, por la misma razón que `report`: gobernar un modelo
   no depende de qué motor se corrió.

### Respuestas de Cami (2026-09-03)

Las cuatro se aprobaron **tal como se recomendaron**, sin cambios:

1. **Sí**: D-GOB-10…16 quedan aprobadas.
2. **Sí**: el copy público de los 13 campos es el de la tabla de D-GOB-13, palabra por palabra.
3. **Diferido**: el capítulo de model card en el informe **no entra**. Queda registrado como abierto
   propio de D-GOB en `DECISIONES-VIGENTES.md`; entrar exige su propia enmienda contra SDD-26.
4. **Los 10 trabajos**, como `report`.

En la misma decisión Cami dio el OK a **D-GOB-9** con condición: la demo se recaptura **mostrando la
ficha del modelo**, lo que exige encender `governance` en los capturadores y declarar un `purpose`
para la institución ficticia de la demo. Ese texto es copy público: se propone y aprueba en la sesión
de release de 1.13.0, antes de lanzar `recapture-demo.yml`, y la recaptura corre sobre el commit de
la release para que los fixtures firmen la versión publicada.

Orden de implementación acordado: D-GOB-10/11 (schema y catálogo) → D-GOB-12/13/14 (formulario y
copy) → D-GOB-15/16 (pantalla y tipo) → documentación → release 1.13.0 con recaptura. Cada capa con
medición previa, gates y control negativo (§6). **Pendiente antes de programar la primera capa: la
revisión independiente de este documento** (AGENTS.md: enmienda → revisión → aprobación → código);
si devuelve hallazgos, se corrige la enmienda y se vuelve a elevar sólo lo que cambie.

### 8.1 Lo que la revisión independiente deja pendiente (2026-09-03)

La revisión adversarial de Codex sobre `5d6aa68..a9a1668` devolvió `needs-attention` con seis
hallazgos, todos verificados contra el árbol. Tres son de este documento y del registro, y están
corregidos aquí (§0.3–§0.6). Los otros tres son de la **implementación de D-GOB-1…8** y son
defectos contra decisiones ya aprobadas, no cambios de contrato: `_preparar_run_dir` aparta el run
anterior **antes** de saber si el reemplazo se construye, sin restaurar si falla (D-GOB-6 prometía
la política de `Study.save`, que sí restaura); la entrada del inventario reconstruye el card con el
trail **relativo al `cwd`**, así que sale sin decisiones mientras `model_card.json` las tiene; y el
gate de D-GOB-4 no exige `gini_*`, `ks_*`, `worst_psi` ni `worst_csi_value`. Los tres se corrigen
en código, con su control negativo, **antes** de la primera capa, y quedan como abiertos 4–6 de
D-GOB en el registro. **Corregidos el 2026-09-07 (S2a)**, con sus gates y controles negativos, y
**revisados adversarialmente el mismo día**: la revisión de S2a devolvió dos hallazgos sobre la
sustitución atómica recién construida —un trail absoluto dentro del `run_dir` tocaba la corrida
previa; el descarte del temporal borraba el trail de una corrida muerta fuera del dominio—,
corregidos como S2a-bis; el registro los cierra con el detalle. Lo que sí pide un OK, porque
cambia lo aprobado:

1. **¿Se añade a `GovernanceConfig.purpose` la validación «texto no vacío tras `strip()`»?** Sin
   ella D-GOB-12 es falsa (§0.6). Es un cambio de validación en una superficie experimental: un
   config con `purpose: ""` que hoy construye dejará de hacerlo. Recomendación: **sí**.
2. **¿Se acepta el nuevo orden de capas: D-GOB-10 sola, luego D-GOB-11/12/13/14 juntas, luego
   D-GOB-15/16?** El orden aprobado (10/11 → 12/13/14) no tiene una capa «11» verde (§0.4).
   Recomendación: **sí**.
3. **¿Cómo entra `governance` al esqueleto de un trabajo?** (a) **Latente**: en el sidebar de los
   10 trabajos, sembrada en `null`; la pregunta por `purpose` aparece al encenderla, y una decisión
   de una sección apagada no cuenta como pendiente. Exige un campo nuevo del catálogo y un cambio
   de criterio en la tarjeta. (b) **Encendida**: `purpose` es una decisión pendiente en los diez
   trabajos y ninguna corrida por trabajo arranca sin propósito. Recomendación: **(a)**, porque es
   lo que D-GOB-11 ya dice —«gesto explícito del usuario»— y porque (b) convierte la gobernanza en
   peaje de trabajos que hoy no la piden.

### Respuestas de Cami (2026-09-07)

Las tres, **tal como se recomendaron**:

1. **Sí**: `GovernanceConfig.purpose` rechaza el texto en blanco tras `strip()`. Se implementa en la
   capa D-GOB-11/12/13/14, con el gate §6.10 en sus tres superficies.
2. **Sí**: el orden es D-GOB-10 → D-GOB-11/12/13/14 → D-GOB-15/16.
3. **(a) Latente**: `governance` en el sidebar de los 10 trabajos, sembrada en `null`; la pregunta
   por `purpose` aparece al encenderla, y una decisión de una sección apagada no cuenta como
   pendiente (gate §6.11).

Con la respuesta 2, **D-GOB-10 se implementó el mismo día (S2b)**: `_INFRA_CONFIG_CLASSES`, los
loaders `cargar_configs_de_infra()` y `cargar_configs_expandibles()`, la unión en el schema, en el
catálogo de defaults, en la guarda del fixture y en `/api/validate`/preflight, con los gates
§6.1–6.3 y §6.9 en `tests/unit/test_gobernanza_expandible.py` y sus controles negativos. Lo que
la implementación corrigió del censo de §3 está anotado allí mismo.

Con las respuestas 1 y 3, **D-GOB-11/12/13/14 se implementaron juntas el 2026-09-07 (S3)**: los
gates §6.4–6.6, §6.8, §6.10 (motor e interfaz) y §6.11 (`/api/run`) viven en
`tests/unit/test_gobernanza_en_pantalla.py`; la mitad del esqueleto latente en
`test_jobs_ejecutables.py`; y la tarjeta —dormidas y escalar en blanco— en
`web/src/lib/jobs.test.ts`. La nota bajo D-GOB-14 en §3 registra lo que la implementación fijó.

**D-GOB-15/16 se implementaron juntas el 2026-09-08 (S4)**: el gate §6.7 vive en
`web/src/components/ResultsTab.test.ts` (render real del panel con y sin card),
`web/src/lib/model-card.test.ts` (la proyección) y la sección final de
`tests/unit/test_gobernanza_en_pantalla.py` (espejo del tipo en los dos sentidos, claves que el
serializador emite hoy, bundle servido y fixtures de la demo), más el recorrido en navegador con
una corrida real con gobernanza y otra sin ella. La nota bajo D-GOB-16 en §3 registra lo que la
implementación fijó. Con esto la enmienda queda **completa**; siguen D-GOB-9 con su OK propio y el
capítulo del informe diferido (§8).
