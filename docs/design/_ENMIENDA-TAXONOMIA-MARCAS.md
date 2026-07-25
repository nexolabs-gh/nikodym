# Enmienda SDD — taxonomía de marcas: `FALTA-DATO` vs `DATO-INSTITUCIONAL`

> **Estado: APROBADA (Cami, 2026-07-24) y EJECUTADA el mismo día**, en nueve commits verdes por sí
> mismos (`c6f203f`…`d01f5d9`). Habilita el renombrado. Esta enmienda es la **fuente de
> verdad del contrato de marcas** mientras se ejecuta; al cerrar, sus decisiones se consolidan en los
> SDD de cada capa (12, 13, 14, 16, 17, 18, 19, 20, 21, 22, 23), igual que se hizo con B2.2.
>
> **Base:** `main` = `93c5c4c`. El encuadre público ya se corrigió en `927a278` (README §Limitaciones);
> esta enmienda lleva la distinción del texto a la marca.
> **Autor / Fecha:** DanIA / 2026-07-24.

| Campo | Valor |
|---|---|
| **Problema** | Una sola marca cubre tres cosas distintas: una carencia del motor, un input que aporta la institución y un TODO de ingeniería |
| **Enmienda a** | SDD-12, 13, 14, 16, 17, 18, 19, 20, 21, 22, 23 (sección «FALTA-DATO explícitos» de cada uno) |
| **No toca** | Los identificadores Python `falta_dato` / `fail_on_falta_dato` (§4), ni el contenido de los `pending_items` del manifiesto CMF |
| **Release** | `1.6.0` — todas las capas afectadas están declaradas **experimentales**; el pipeline F1 estable no emite ninguno de los códigos que cambian |

---

## 1. El problema, medido

Censo sobre el árbol versionado: **454 ocurrencias del string en 105 archivos**, con **52 códigos
distintos** repartidos en tres grupos que hoy comparten una sola marca. Dos precisiones del censo:

- Son **52**, no 51: `FALTA-DATO-STR-LGD` (`stress/engine.py`) **no está declarado en ningún SDD**
  — nació en el código y no sigue la numeración de su familia (por eso se normaliza a `STR-8`).
- Hay además **dos códigos sin número**: `FALTA-DATO-PROV` (`orchestrator.py`) y `FALTA-DATO-FWD`
  (`forward/macro.py`), que se normalizan a `PROV-2` y `FWD-8`. Con ellos, los destinos a clasificar
  son **54**, no 52.
- Y **dos marcas desnudas sin familia**, emitidas en runtime: el motor interno cuando una fila no
  trae exposición o LGD, y `validation` cuando el backtesting no tiene columnas realizadas. Ambas
  son institucionales y quedan como `DATO-INSTITUCIONAL` a secas, sin número.
- **30 de los 52 no aparecen en `src/`**: viven sólo en la sección «FALTA-DATO explícitos» de su SDD.
  Son *decisiones de diseño*, no marcas que el motor emita. La distinción operativa que importa es
  **código emitido** (viaja a `warning_codes` / `card.falta_dato` / informe / UI) vs **ítem de SDD**.

Lo que la marca única produce hoy: el argumento de venta del producto —«el motor se niega a inventar
un supuesto que no le corresponde»— aparece rotulado como defecto propio, 35 veces.

## 2. La taxonomía (D-MARCA-1)

| Destino | Qué declara | Nº |
|---|---|---|
| **`FALTA-DATO`** | Brecha real del motor: algo que Nikodym no trae, difirió, o no verificó contra fuente oficial | 8 códigos + 2 `pending_items` CMF |
| **`DATO-INSTITUCIONAL`** | Parámetro, definición o dato de entrada que le corresponde a la institución; el motor **se niega a inventarlo** | 35 + 2 marcas desnudas |
| **sin marca publicable** | TODO de ingeniería, sin significado para un usuario → issue de GitHub | 7 |
| **cierre por resuelto** | Ítem de coordinación entre SDD que la implementación ya resolvió | 4 |

**Regla mnemónica, y criterio de clasificación de todo código futuro:**
`FALTA-DATO` = *lo debe Nikodym*. `DATO-INSTITUCIONAL` = *lo debe la institución*.

**D-MARCA-2 — Familia y número se conservan.** `FWD-1` sigue siendo `FWD-1`: sólo cambia el prefijo.
La trazabilidad contra los SDD, el CHANGELOG y los tickets históricos se mantiene intacta. Tres
excepciones, todas de normalización: `STR-LGD` → `STR-8`, `PROV` (sin número) → `PROV-2` y `FWD`
(sin número) → `FWD-8`. Los tres eran códigos nacidos en el código, nunca declarados en su SDD.

**D-MARCA-3 — La marca no la elige quien escribe el mensaje.** Ambos prefijos viven en
`nikodym/core/markers.py` y los filtros que arman la card consumen la constante compartida, no un
literal. Sin esto, un código institucional dejaría de llegar a la card en silencio (§4).

## 3. Clasificación 1×1, con la evidencia que la sostiene

Evidencia = texto canónico del SDD que lo declara y/o el sitio del código que lo emite. Se clasificó
leyendo qué declara cada código, no por el nombre de su familia: por eso `ML-1` y `ML-2` van a clases
distintas, y `STR-5` se separa del resto de `STR-*`.

### A · `FALTA-DATO` — brecha real del motor (8 + 2)

| Código | Evidencia | Por qué es brecha |
|---|---|---|
| `IFRS-4` | SDD-16 «Sin panel longitudinal, la amortización por período no está disponible» · emitido en `ifrs9/ead.py:69` | El motor no trae el panel |
| `IFRS-6` | SDD-16 «el motor v1 la ignora» · `ifrs9/engine.py:94` | Limitación del motor v1 |
| `FWD-6` | SDD-20 — ítem espejo de `IFRS-6` | La misma brecha, vista desde forward |
| `VAL-1` | SDD-22 «forma exacta del estadístico t-test ECB … a verificar por render del PDF oficial» | Verificación pendiente (principio #11) |
| `VAL-2` | SDD-22 «anclaje regulatorio y cortes exactos del semáforo» | Verificación pendiente |
| `VAL-3` | SDD-22 «convención exacta del p-valor del Jeffreys test» | Verificación pendiente |
| `STR-5` | SDD-21 «`stress` no importa ni adivina SDD-16/17» | El motor ECL no está conectado |
| `ML-1` | SDD-12 · `ml/step.py:155` «`feature_source='data_raw'` está **diferido**» | Ruta no implementada |
| `financial_guarantee_haircuts` | `manifest.json` §5.2 | Parámetro normativo no extraído |
| `ran_21_10_numeric_tables` | `manifest.json` §5.3 | Tabla normativa no extraída |

Las tres `VAL-*` son las más delicadas del conjunto y las menos visibles: no las emite el motor, viven
en docstrings y en una `description` de config. Se quedan en `FALTA-DATO` sin matices.

**Consecuencia:** `marker: Literal["FALTA-DATO"]` (`cmf/matrices.py:103`) **no cambia** —los dos
`pending_items` son brechas reales—, y tampoco cambian `report/prose.py` (`_IFRS9_WARNING_LABELS`
sólo mapea `IFRS-4`/`IFRS-6`) ni `methodology.py:161` (`IFRS-4`). **El texto del informe entregable no
se mueve.**

### B · `DATO-INSTITUCIONAL` — lo aporta la institución (35)

| Código | Evidencia (texto canónico o sitio de emisión) |
|---|---|
| `IFRS-1` | `Z` y `rho` explícitos; «no existe ruta degradada» → `IfrsConfigError` |
| `IFRS-2` | «`H_12m` depende de la granularidad … debe declararse» |
| `IFRS-3` | «SDD-16 consume `is_default`/dpd ya definidos» |
| `IFRS-5` | «Debe venir en `data.frame`; no se infiere una tasa» |
| `SUR-1` | horizonte lifetime y unidad temporal — emitido en 4 sitios de `survival/` |
| `SUR-2` | definición operacional de evento/default y censura — `kaplan_meier.py:56` |
| `SUR-3` | nivel y transformación del IC Kaplan-Meier — `kaplan_meier.py:55` |
| `SUR-4` | rol de la PD F1 en discrete hazard (covariable / offset / segmentación) |
| `SUR-5` | grano de salida: «debe definirse por datos/negocio» |
| `SUR-7` | umbrales de diagnóstico Cox/Schoenfeld: «no hay … acción normativa» |
| `SUR-8` | familia AFT default |
| `SUR-9` | pesos de observación/exposición |
| `MKV-1` | columnas `id/time/state`: «se resuelve por `MarkovInputConfig`» |
| `MKV-2` | taxonomía institucional de estados: «cada cartera debe declarar» |
| `MKV-5` | «`weight_col` existe, pero no se asume por default» |
| `FWD-1` | paths/shocks macro: «deben venir de institución/config» — `forward/config.py:662` |
| `FWD-2` | variables macro canónicas: «`factor_cols` lo declara el usuario» |
| `FWD-3` | frecuencia temporal institucional |
| `FWD-4` | naturaleza PIT/TTC: «se requiere columna o config» — `scenarios.py:64` |
| `FWD-5` | coeficientes satellite: «deben venir como coeficientes fijos auditados» — `satellite.py` ×4 |
| `FWD-7` | «el perfil institucional de EAD/LGD sigue siendo input externo» |
| `FWD-8` (ex sin número) | `macro.py` «`kind='vecm'` exige `vecm_rank` explícito»: statsmodels no lo infiere de forma estable |
| `STR-1` | shocks comparables: dependen de las magnitudes que traiga el input de forward |
| `STR-2` | escenarios oficiales: «deben venir de fuente institucional/oficial versionada» |
| `STR-3` | umbrales de capital: «el usuario los declara» |
| `STR-4` | calibración de severidades: «del usuario o análisis aprobado» |
| `STR-6` | denominadores (capital, patrimonio efectivo, RWA, cartera vigente) |
| `STR-7` | política de shock relativo: «debe declararse por factor» |
| `STR-8` (ex `STR-LGD`) | `engine.py` «`output.metrics` incluye `'lgd'` pero no está disponible» |
| `ML-2` | umbral de challenger: «decisión de gobierno … entra por config del usuario» |
| `EXP-1` | formato de reason codes: norma en EE. UU. (ECOA/FCRA), no en CMF; `top_n` configurable |
| `EXP-2` | umbral de driver material: «decisión de gobierno» |
| `PROV-1` | celda sin contraparte en los datos entregados |
| `PROV-2` (ex sin número) | imputó 0 por `coverage_policy='treat_missing_as_zero'` (política elegida) |
| `PROV-3` | comparación incompleta por `require_both=False` (política elegida) |

Las tres `PROV-*` no las declara ningún SDD: son mensajes de runtime. Entran en esta clase porque su
causa es la política o los datos que trajo quien corre la librería, nunca una carencia del motor.

### C · Sin marca publicable — TODO de ingeniería → issue (7)

`ML-3` y `EXP-3` (determinismo cross-versión de los backends y de `shap`, «documentadas como
caveat»), `TUN-1` (presupuesto de CI del tuning), `TUN-2` (evaluador de importancia de Optuna),
`UI-1` (pins de `fastapi`/`uvicorn`), `UI-2` (librería de charts del front) y `UI-3` (**ya marcado
✅ RESUELTO y aún contado como brecha abierta**).

Ninguno se emite en runtime. SDD-23 ya los rotulaba «FALTA-DATO (de ingeniería, no regulatorio)»: la
distinción existía en la cabeza del autor, no en la marca. Salen de la sección de marcas de su SDD y
quedan como issues del repo —[#1](https://github.com/nexolabs-gh/nikodym/issues/1) (UI-1),
[#2](https://github.com/nexolabs-gh/nikodym/issues/2) (UI-2),
[#3](https://github.com/nexolabs-gh/nikodym/issues/3) (TUN-1),
[#4](https://github.com/nexolabs-gh/nikodym/issues/4) (TUN-2) y
[#5](https://github.com/nexolabs-gh/nikodym/issues/5) (ML-3 + EXP-3, que son el mismo caveat)—;
`UI-3` no genera issue: ya estaba resuelto.

### D · Cierre por resuelto — coordinación entre SDD ya implementada (4)

`SUR-6`, `MKV-3`, `MKV-4` y `MKV-6` sólo decían «SDD-16 / SDD-20 debe fijar X». Esos SDD están
implementados: el contrato forward↔IFRS 9 vive en `tests/unit/test_forward_ifrs9_contract.py`, y la
naturaleza PIT/TTC quedó cubierta por `FWD-4`. Se marcan ✅ RESUELTO con su evidencia, igual que `UI-3`.

## 4. Alcance: qué se toca y qué no

**Se toca** (sólo el prefijo de los códigos B, y la marca de los C):

- `src/**`: constantes de módulo (`survival`, `forward`, `stress`, `provisioning/orchestrator`,
  `explain`), mensajes de excepción, `description=` de campos Pydantic, docstrings.
- Los **5 filtros por prefijo** — `forward/step.py:682`, `markov/step.py:541`,
  `ifrs9/engine.py:513`, `stress/engine.py:660`, `survival/step.py:634` — pasan de
  `startswith("FALTA-DATO")` a la constante compartida de `core/markers.py`. **Sin esto los códigos
  institucionales dejan de llegar a la card sin que nada falle**: es el único punto del cambio con
  modo de fallo silencioso, y por eso va primero y con test propio.
- `tests/**` (37 archivos), `docs/**` (SDD, README, ROADMAP, CHANGELOG).
- `web/src/fixtures/schema.json`, **regenerado, nunca editado a mano**: arrastra las `description` de
  los campos de config.

**No se toca (D-MARCA-4):** los identificadores Python `falta_dato` y `fail_on_falta_dato` (351
ocurrencias). Es config **pública**: vive en los 3 presets, los 3 informes HTML y `schema.json` de la
demo. Renombrarlo rompe el config de quien instaló 1.5.0 y obliga a recapturar todo el material de la
demo, a cambio de coherencia nominal. `falta_dato` queda como **término paraguas de «avisos
declarados»**, documentado como tal; si se quiere alinear, va en 2.0 con alias Pydantic y período de
deprecación.

## 5. Criterio de aceptación, y cómo quedó

1. `git grep FALTA-DATO` devuelve **sólo** los 8 códigos de la clase A, los 2 `pending_items`, el
   término paraguas y el texto que explica la taxonomía. ✅ Verificado por censo tras el último commit.
2. Ningún código de la clase B se pierde entre el motor y la card. ✅ `tests/unit/test_core_markers.py`
   fija que el predicado compartido reconoce las dos marcas, y que un warning de celda no se cuela.
3. Los números insignia de la demo no se mueven: ECL $3.423.116 · EAD $114.325.315 · 2,99 %.
   ✅ Verificados sobre el fixture recapturado. El diff de los tres sets es **sólo** lineage
   (`git_sha`, `created_at`, `run_id`): ninguna cifra ni texto de negocio cambió, tal como predecía
   §3 —el único código que el informe imprime es `IFRS-4`, que es clase A—.
4. Gates completos verdes: `ruff check`, `ruff format --check`, `mypy --strict src/`, `pytest`
   (**4232 passed / 2 skipped** con `DYLD_FALLBACK_LIBRARY_PATH`; baseline 4213 + 15 tests nuevos del
   contrato de marcas + 4 de PDF que corren con las nativas presentes) y los gates de `web/`
   (lint, typecheck, 269 tests, supply-chain, bundle y licencias), con el bundle reconstruido dos
   veces byte-idénticas.
