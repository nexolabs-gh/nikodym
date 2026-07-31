# SDD — Tu trabajo, tus datos, tu metodología

> **Estado: BORRADOR — pendiente de aprobación de Cami.** Adelanta y **amplía** el nodo F3 «UI por
> trabajos» del plan (`privado/PLAN-IMPLEMENTACION-2026-07-31.md` §J.3), que estaba aparcado tras
> `1.11.0`.
>
> **Base:** `main` = `45bfe7b` (cierre del paquete D). **Autor / Fecha:** DanIA / 2026-07-31.

| Campo | Valor |
|---|---|
| **Problema** | La interfaz está construida alrededor de *correr las demos que traemos*, no de *hacer tu trabajo, con tus datos y tu metodología* |
| **Enmienda a** | SDD-23 §3 (navegación, siembra y secciones), §4.2 (contrato REST) |
| **No toca** | El motor, el `config_hash`, el catálogo de defaults efectivos, ni la puerta de artefactos por código |
| **Release** | Cambio observable de producto; exige CHANGELOG. Este SDD no autoriza bump, tag ni publicación |

## 1. Una sola tesis, cinco síntomas

Los cinco reproches que originan este documento no son cinco problemas: son el mismo, visto desde
cinco sitios. **La aplicación asume que vienes a ver una demostración.**

| Síntoma observado | Causa medida |
|---|---|
| Elijo scorecard y el sidebar me ofrece IFRS 9, survival y CMF | `web/src/App.tsx:138` mapea `CONFIG_SECTIONS` **entera**, sin un solo filtro |
| Un área que sólo hace LGD ve binning y provisiones ajenas | No existe el concepto «trabajo»: la unidad es el pipeline F1 completo |
| Los presets pesan más que traer datos propios | `web/src/lib/bootstrap.ts:116-120` siembra al arrancar el preset **y su `dataset_id`** sintético |
| «En PD, IFRS 9 y stress siempre hay varias metodologías» | El abanico **existe** (50+ puntos de elección, implementados) pero viaja como campos sueltos: 79 de 394 nodos visibles |
| Bancos reales, de varios países | La landing no distingue lo neutral de lo local (CMF es Chile) |

La conclusión importante es que **no hay que construir capacidad: hay que dejar de esconderla.** El
motor ya ofrece abanicos serios —4 métodos de LGD en IFRS 9, 4 de survival, 3 de calibración, 6 de
modelo macro, 5 backends de ML—, todos con implementación real fuera de su `config.py`. Lo que
falta es una interfaz que pregunte a qué viniste y te enseñe tus opciones.

## 2. Lo que se midió antes de diseñar

Ejecutado contra `45bfe7b`, no deducido: varios pasos derivan sus prerequisitos de su config, así que
el `requires` de clase engaña.

**Ejecutabilidad por trabajo aislado:**

| Trabajo | ¿Corre solo hoy? | Qué le falta |
|---|---|---|
| Scorecard PD (F1) | **Sí** | — |
| Provisiones CMF | **Sí** (`data → provisioning_cmf`) | — |
| PD lifetime (survival) | **Sí** (`data → survival`) | — |
| IFRS 9 / ECL | **No** | Exige `('survival','term_structure')`: es compuesto, no aislado |
| LGD / provisión interna | **No** | Exige la PD (`calibration` o `model`) y no hay cómo traerla por la interfaz |
| Validar un modelo existente | **No** | No existe la ruta (F4.1 del plan) |

**El hallazgo decisivo:** el motor **ya sabe** hacer trabajos aislados. Con la puerta de artefactos
del paquete B, `check_pipeline(cfg, artifacts=[('calibration','calibrated_pd_frame')])` declara
ejecutable `data → provisioning_internal`. La puerta existe **sólo por código**: el paquete B dejó la
vía HTTP/UI explícitamente fuera. Para quien usa el formulario la capacidad no existe — la definición
exacta de «feature gateada por config es feature inexistente» del propio repo.

**El abanico por dominio (censo completo, resumen):**

| Dominio | Puntos de elección | Ejemplos |
|---|---:|---|
| `provisioning_ifrs9` | 6 | LGD: `provided, beta_regression, fractional_response, workout` · PIT: `consume_pit, apply_vasicek, ttc_only` |
| `stress` | 5 | escenarios `severe/custom`, shocks de 4 orígenes, 7 métricas |
| `forward` | 5 | macro: `arima, sarima, arimax, auto_arima, var, vecm` |
| `survival` | 3 | `discrete_hazard, kaplan_meier, cox_ph, aft` |
| `calibration` | 3 | `intercept_offset, platt_scaling, isotonic` |
| `ml` | 4 | `svm, random_forest, xgboost, lightgbm, catboost` |
| `markov`, `binning`, `selection`, `model`, `provisioning*` | 15+ | — |

⚠️ **Un matiz que corrige una lectura precipitada:** `provisioning_internal.lgd.method` sólo admite
`provided` y `group_historical` —ahí no hay LGD modelada—, pero `provisioning_ifrs9.lgd.method` sí
ofrece `beta_regression`, `fractional_response` y `workout`. El abanico está, repartido de forma
desigual entre motores. Lo que **no** existe en ninguno es un regresor genérico sobre variables
WoE-izadas: un árbol de regresión para LGD, caso observado en banca, no tiene dónde encajar.

## 3. Decisiones

**D-JOB-1 — El trabajo es un concepto de primer nivel, no una consecuencia del config.** La landing
ofrece trabajos por su nombre de negocio; elegir uno fija qué secciones existen esa sesión. No se
derivan de «las secciones no nulas»: con «Empezar de cero» eso dejaría el sidebar vacío.

**D-JOB-2 — La sesión arranca VACÍA y pidiendo tus datos.** Se retira la siembra automática del
preset y su dataset. El primer paso es *elige tu trabajo* y *trae tu archivo*. Los presets siguen
existiendo como **«ver un ejemplo con datos de muestra»**, un camino explícito y secundario, nunca el
estado inicial. Es el cambio de énfasis que separa una demo de una herramienta.

**D-JOB-3 — Un trabajo declara sus secciones, sus insumos externos y su abanico.** Las tres cosas
juntas y en **una sola fuente**, que consumen landing, sidebar y preflight.

**D-JOB-4 — El abanico se elige al principio y en el idioma del negocio, no buscando un campo.** Al
entrar a un trabajo, la interfaz pregunta por las decisiones metodológicas que lo definen —qué método
de LGD, qué curva de supervivencia, qué calibración— antes de los parámetros de detalle. Cada opción
dice qué exige: `beta_regression` necesita LGD observada; `apply_vasicek` necesita `rho` y factor
sistémico. Hoy eso se descubre cuando la corrida falla.

**D-JOB-5 — Una opción del abanico que no se puede usar con TUS datos se declara, no se oculta.** Si
tu dataset no trae la columna que una metodología exige, la opción aparece con su motivo y qué
columna falta. Ocultarla deja al usuario creyendo que la librería no la tiene.

**D-JOB-6 — Un trabajo que no corre hoy se declara, no se promete.** Aparece con su estado y no se
puede iniciar. Aplica a **validar un modelo existente** y a **LGD por regresión**.

**D-JOB-7 — La puerta de artefactos se abre por HTTP/UI, acotada a lo que cada trabajo declara.** Es
lo que desbloquea los trabajos por área. No es una puerta general: el trabajo dice qué acepta de
fuera y la interfaz pide **ese** archivo con su nombre de negocio, no una clave de artefacto. Exige
su propia enmienda de seguridad (hoy `/api/upload` ya vive tras token, `Origin` y
`allow_live_execution`).

**D-JOB-8 — La jurisdicción es un atributo del trabajo.** CMF es Chile; scorecard, LGD, IFRS 9,
survival y stress son neutrales. La landing lo dice: los interesados del webinar no están todos en
Chile, y un botón «Provisiones CMF» sin contexto es ruido para un banco peruano o colombiano.

**D-JOB-9 — Ni el trabajo ni el abanico elegido entran al `config_hash`** más allá de lo que ya
cambian los campos del config. El trabajo es navegación; dos usuarios que llegan al mismo config por
caminos distintos producen la misma identidad. Lo verifica un gate.

**D-JOB-10 — Los trabajos compuestos son de primer nivel.** «PD + LGD en una corrida» tiene su botón,
su flujo y su informe; no es la suma de dos menús. Es lo que sirve al banco pequeño donde un área
hace todo.

## 4. Catálogo inicial de trabajos

| Trabajo | Secciones | Insumo externo | Jurisdicción | Estado |
|---|---|---|---|---|
| Scorecard de comportamiento (PD) | data, binning, selection, model, scorecard, calibration, performance, stability, validation, report | — | neutral | **disponible** |
| PD lifetime (curvas de supervivencia) | data, survival, report | PD del modelo | neutral | **disponible** |
| Provisiones CMF | data, provisioning_cmf, report | — | **Chile** | **disponible** |
| Provisiones IFRS 9 / ECL | data, survival, provisioning_ifrs9, report | — | neutral | **disponible** (compuesto) |
| Provisión interna / LGD | data, provisioning_internal, report | **PD calibrada** | neutral | **disponible al abrir la puerta** (D-JOB-7) |
| PD + LGD en una corrida | scorecard completo + provisioning_internal | — | neutral | **disponible** (compuesto) |
| Comparar provisiones (CMF vs interna) | data, provisioning_cmf, provisioning_internal, provisioning, report | — | Chile | **disponible** |
| Stress testing | data, stress, report | curvas o ECL según el escenario | neutral | **a medir** (`stress` no está en el formulario) |
| Validar un modelo existente | data, performance, stability, validation, report | scorecard y PD del cliente | neutral | **NO disponible** (F4.1) |
| LGD por regresión (WoE + árbol) | data, binning, + regresor | — | neutral | **NO disponible** — no hay objetivo continuo |

Las dos últimas filas son trabajo pendiente que este SDD **no** resuelve: se declaran para que la
landing diga la verdad y el roadmap sepa qué falta. Un objetivo continuo en el motor es capacidad
nueva con su propio SDD, y es lo que además abriría EAD.

## 5. Lo que queda fuera, a propósito

Del F3 original: niveles esencial/ajustes/avanzado dentro de cada sección, el preflight que
**propone** correcciones, la corrida con URL e historial y los resultados por pregunta. Son mejoras
dentro de un trabajo ya elegido; entran después y no bloquean esto.

## 6. Gates de aceptación (borrador)

- Cada trabajo muestra **exactamente** sus secciones, verificado en la pantalla: un trabajo de LGD no
  puede pintar binning, y uno de scoring no puede pintar IFRS 9.
- **La sesión arranca sin config sembrado y sin dataset**; llegar a una corrida exige traer un
  archivo. Ver un ejemplo con datos de muestra sigue siendo posible en un click explícito.
- El abanico de cada trabajo se ve **antes** que los parámetros de detalle, y cada opción declara qué
  exige. Una opción incompatible con el dataset cargado dice qué columna falta.
- Un trabajo o una opción no disponibles no se pueden iniciar, y su motivo se lee sin jerga.
- El `config_hash` no depende del trabajo por el que se llegó al config.
- Cada trabajo disponible llega a `done` con informe desde su landing, **con un dataset propio** y
  sin editar YAML.
- Una sola fuente del catálogo, y un gate que exige que toda sección del formulario pertenezca al
  menos a un trabajo, o declare por qué no.
- La puerta por HTTP conserva las guardas de `/api/upload` y suma su negativo de seguridad.

## 7. Preguntas abiertas para Cami

1. **Regresión sobre target continuo** (LGD/EAD modeladas): ¿entra al roadmap como capacidad nueva?
   Es lo que falta para el caso «LGD con WoE y árbol de regresión» y para EAD.
2. **Validar un modelo existente**: hubo interés real en el webinar y hoy no existe la ruta. ¿Va
   antes que E/G/H1?
3. **`stress` no está en el formulario** (es Python-only). ¿Entra como trabajo ahora o después?
4. **Nombres de los trabajos**: los de la tabla son de negocio. ¿Suenan a lo que diría un área de
   banco, o hay que ajustarlos antes de que lleguen a la pantalla?
