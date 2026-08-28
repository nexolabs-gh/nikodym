# Decisiones vigentes

> Registro canónico de **estado e interpretación final**. Los SDD enlazados conservan el análisis,
> alternativas descartadas y texto histórico; si su cabecera o una prescripción intermedia
> contradice este registro, prevalece este archivo. El estado operativo vive en
> `HANDOFF.md`, symlink interno no versionado públicamente.

## Cómo usar este registro

- Una decisión **aprobada** no se reabre porque un agente prefiera otra solución.
- “Implementada” significa que existe evidencia en código/tests; no que toda revisión futura esté
  cerrada. Los abiertos se declaran aparte.
- Un cambio al contrato exige una enmienda nueva, evidencia adversarial y OK de Cami antes de tocar
  código.
- Los conteos de una propuesta son históricos. Para afirmar completitud hay que volver a medir el
  árbol vigente y probar el gate en negativo.

## Estado resumido

| Familia | Estado canónico | Fuente histórica principal |
|---|---|---|
| D-JUR-1…8 | Aprobada; implementada; B5 humano pendiente | [`_VEREDICTO-NORMATIVA-LOCAL.md`](_VEREDICTO-NORMATIVA-LOCAL.md) |
| D-MON-1…6 | Aprobada e implementada | [`_ENMIENDA-MONEDA-DEL-INFORME.md`](_ENMIENDA-MONEDA-DEL-INFORME.md) |
| D-CAP-1…3 | Aprobada e implementada | [`_ENMIENDA-CAPITULO-DE-PROVISIONES.md`](_ENMIENDA-CAPITULO-DE-PROVISIONES.md) |
| D-VER-1…3 | Aprobada e implementada | [`_ENMIENDA-COTEJO-VERIFICADOR.md`](_ENMIENDA-COTEJO-VERIFICADOR.md) |
| D-AMB-1…6 | Aprobada e implementada | [`_ENMIENDA-COLUMNA-CARTERA-AMBIGUA.md`](_ENMIENDA-COLUMNA-CARTERA-AMBIGUA.md) |
| D-LGD-1…15 | Aprobada e implementada | [`_ENMIENDA-LGD-MODELADA.md`](_ENMIENDA-LGD-MODELADA.md) |
| D-SUB-1…4 | Aprobada e implementada | [`_ENMIENDA-SUBSECCION-INERTE.md`](_ENMIENDA-SUBSECCION-INERTE.md) |
| D-EXI-1…7 | Aprobada e implementada | [`_ENMIENDA-OPCION-QUE-EXIGE-OTRO-CAMPO.md`](_ENMIENDA-OPCION-QUE-EXIGE-OTRO-CAMPO.md) |
| D-FTE-1…5 | Aprobada e implementada | [`_ENMIENDA-COTEJO-FUENTES.md`](_ENMIENDA-COTEJO-FUENTES.md) |
| D-VIS-1…7 | Aprobada; D-VIS-1…5/7 implementadas; completitud D-VIS-6 abierta | [`_ENMIENDA-ERROR-SIN-SUPERFICIE.md`](_ENMIENDA-ERROR-SIN-SUPERFICIE.md) |
| D-RDY-ABA-1…6 · D-RDY-H9R-1…8 | Aprobadas; protocolo pre-START H9R aprobado sólo para arnés; W0 cerrada/PASS; W1 NO PASS/bloqueada por recalibración H9; W2–W8 no iniciadas | [`30-readiness-integral.md`](30-readiness-integral.md) |
| D-LEA-0…22 (+12b/17b/17c) | Aprobada (0-a) el 2026-08-22; implementación por capas en curso; D-LEA-20 no aprobada (0-b diferido) | [`_ENMIENDA-LEASE-MATERIAL-CANDIDATO.md`](_ENMIENDA-LEASE-MATERIAL-CANDIDATO.md) |
| D-EST-1…4 | Aprobada por Cami el 2026-08-27; implementada y gateada | esta entrada (§D-EST) |
| D-GOB-1…9 | Aprobada por Cami el 2026-08-28; D-GOB-1…8 implementadas y gateadas; D-GOB-9 (recaptura de la demo) **no ejecutada**, pide OK propio; abierto: la ruta de UI para `governance` | [`_ENMIENDA-GOBERNANZA-ALCANZABLE.md`](_ENMIENDA-GOBERNANZA-ALCANZABLE.md) |

## D-RDY — readiness integral

Cami aprobó expresamente el 2026-08-09 SDD-30, D-RDY-ABA-1…6 y el siguiente bloque indivisible de
decisiones: **H1=A, H2=A, H3=A, H4=A, H5=A, H6=A, H7=A, H8=A, H9=B, H10=A y H11=A**.
El 2026-08-12 aprobó **D-RDY-H9R-1…8**, que sustituyen H9=B para todo trabajo futuro sin reescribir
W0 ni la evidencia S0/S1/S2. H1–H8, H10 y H11 permanecen sin cambios.
El 2026-08-13 aprobó el texto entonces vigente del protocolo pre-START H9R únicamente para
implementar, probar y revisar su arnés. Ese OK no autoriza START, S0, S1, S2, fixtures definitivos
ni valores finales. El mapeo estático de §10.1 se añadió después como anotación de implementación
no normativa; sus `adapter_id` y serialización JSON no se atribuyen al OK byte-exacto.

Reglas vigentes:

- la readiness se demuestra por flujo y la puerta global es acumulativa; un módulo aislado o un
  `main` verde no bastan;
- D-RDY-ABA-1…6 enmiendan D-ABA-4/5/6: `sin_efecto` deja de ser seleccionable, `disponible` y las
  opciones condicionadas exigen rama real más `effect_oracle`, `no_implementada` permanece visible
  y deshabilitada, y los aliases F1 compatibles salen del selector con deprecación durante 1.x;
- H1/H2 fijan bundle abierto y seguro y tratamiento fail-closed sin WoE inventado; H3 redondea la
  ECL final por operación; H4 conserva perfil EAD provisto más identidad de movimientos; H5 exige
  fuentes LGD finales mutuamente excluyentes; H6 rechaza pesos de escenario cero;
- H7 incluye roll-rate/vintage sólo como diagnósticos de PD temporal y exige addendum metodológico
  antes de código; H8 excluye `PortfolioStress` de la readiness inicial;
- H9=B/`S2-equipo` queda sólo como contrato histórico de W0 y evidencia preservada. D-RDY-H9R fija
  como dirección hasta 4 CPU lógicas y una máquina de 8 GB nominales, con calibración inicial en
  Windows y confinamiento efectivo del árbol. No fija todavía cap, geometría, budget, disco ni
  perfil final;
- la calibración H9R se decide por flujo cuando W1–W5 lo vuelven alcanzable. Cada START futuro es
  `candidato × flujo × intento`, usa árbol fresco y autorización propia, y conserva hashes, lineage,
  completitud y publicación atómica. La autorización S2 `0/1` está cancelada, no consumida y no
  puede revivir;
- H10 mantiene engine/batch síncronos y exige jobs UI al cruzar un umbral fijado **después de W0**.
  W0 no pudo medir UI S1/S2 y no fija una cifra por inferencia: el primer baseline alcanzable de
  W1 debe fijarla antes de implementar esa frontera, sin reabrir H10=A. H11 exige paridad semántica
  y constraints visuales propios de HTML/PDF/DOCX;
- las oleadas se ejecutan en orden W0→W8. W0 conserva su cierre/PASS histórico; W1 está NO PASS y
  bloqueada por recalibración de H9 hasta que el arnés quede implementado y revisado y, después,
  cada medición y perfil exacto reciban sus autorizaciones, revisiones y OK separados;
- 4 CPU/8 GB sólo es entorno objetivo declarado en diseño. No aparece como capacidad en copy público
  antes de un PASS gateado;
- PyPI y recaptura de demo conservan sus OK específicos; la aprobación de SDD-30 no los hereda.

Fuente contractual y matriz de flujos:
[`30-readiness-integral.md`](30-readiness-integral.md).
Baseline W0 cerrado, con segunda revisión independiente `APROBABLE`:
[`_BASELINE-READINESS-W0.md`](_BASELINE-READINESS-W0.md).
Enmienda H9R aprobada:
[`_ENMIENDA-H9-ENTORNO-REPRESENTATIVO.md`](_ENMIENDA-H9-ENTORNO-REPRESENTATIVO.md).
Protocolo pre-START aprobado el 2026-08-13 para implementar, probar y revisar únicamente el arnés;
sin autorización de START/S0/S1/S2, medición ni valores finales:
[`_PROPUESTA-CALIBRACION-H9R-PRE-START.md`](_PROPUESTA-CALIBRACION-H9R-PRE-START.md).

## D-LEA — congelación del material de ejecución candidato

Cami aprobó el 2026-08-22 el escenario **0-a** de §10.2 de la enmienda, con variante **A** (§7.1),
clausura del intérprete **incluida** (§7.2), **asumir el coste** (§7.7) y **§7.5 = sí**; §7.3 fija en
sí por §4.1. La enmienda tuvo cinco revisiones adversariales independientes.

Reglas vigentes:

- La frontera promete **consistencia del material en disco** —nadie puede sustituir, borrar,
  renombrar ni reemplazar los bytes, ni añadir material ejecutable que la evidencia no atestigüe— y
  los procesos Medium del mismo usuario quedan **dentro del TCB** (0-a). La inyección en memoria
  (0-b) **no** se promete: se difiere al blocker propio
  `candidate_process_memory_isolation_unimplemented`.
- Tres piezas: lease anti-sustitución (D-LEA-1…9), anti-inyección por los dos canales —imágenes por
  depuración (D-LEA-12) y canal Python vía audit hook (D-LEA-12b)— con clausura del intérprete
  declarada (D-LEA-13), y máquina de publicación provisional→release→promoción (D-LEA-16…18) con
  paquete durable content-addressed (D-LEA-17c).
- **D-LEA-20 no se aprobó.** El endurecimiento posterior de descendientes tiene una carrera de
  handles (F1) y el supervisor es una puerta trasera sin endurecer (F2); cerrar 0-b exige un broker
  de creación y endurecer el supervisor, materia del blocker diferido, no de esta frontera.
- **D-LEA-19:** aprobar **no** habilita START. Al **integrar** el mecanismo se retira
  `candidate_execution_material_lease_unimplemented` y se abre
  `candidate_process_memory_isolation_unimplemented`; la puerta global no baja de blockers. El flip
  ocurre con el código implementado y sus controles negativos verdes, **no** al firmar.
- La implementación es **por capas** (Anexo A de la enmienda); hasta A.4 el catálogo sigue
  declarando el blocker de lease, que es lo honesto.

Estado: **Aprobada; implementación por capas en curso.** No autoriza START, fingerprint, fixtures ni
valores finales. Fuente, decisiones y controles negativos preespecificados:
[`_ENMIENDA-LEASE-MATERIAL-CANDIDATO.md`](_ENMIENDA-LEASE-MATERIAL-CANDIDATO.md).

## D-JUR — normativa local como evidencia

Reglas vigentes:

- La normativa local de cada país está fuera del alcance general de la librería. El modelador o
  Nikodym Advisory la aterriza sobre estándares comunes.
- B3.a-2, el selector de jurisdicción y B7 quedaron sin objeto; B3.b quedó cerrado por alcance.
- CMF/Chile se conserva como caso de referencia implementado, congelado y fechado. Nunca se borra
  su motor, pruebas o evidencia; tampoco vuelve al titular o la propuesta de valor.
- D-JUR-8 ya está implementada: default neutral de cartera para el método interno, moneda declarada
  por el informe y demostración sin normativa local.
- B5 —validación humana de la evidencia normativa— sigue siendo trabajo de Cami, no una
  implementación automática del agente.

Gates principales:
[`test_portada_sin_jurisdiccion.py`](../../tests/unit/test_portada_sin_jurisdiccion.py),
[`test_docs_provision_neutra.py`](../../tests/unit/test_docs_provision_neutra.py),
[`test_ui_presets.py`](../../tests/unit/test_ui_presets.py).

## D-MON — moneda del informe

Reglas vigentes:

- La moneda es presentación del informe y vive en `report.currency`; no se infiere desde la
  jurisdicción, la fuente de provisiones ni el símbolo.
- `None` significa “no declarada” y obliga a callar la unidad, nunca a suponer CLP.
- `$` no identifica una moneda. Símbolo y moneda son conceptos distintos.
- El canal final es `ReportInputBundle.currency`, no `pipeline_params`.
- La convención de separadores numéricos la gobierna el idioma del informe.

Gates principales:
[`test_report_config.py`](../../tests/unit/test_report_config.py),
[`test_report_results.py`](../../tests/unit/test_report_results.py),
[`test_report_renderer.py`](../../tests/unit/test_report_renderer.py),
[`results-format.test.ts`](../../web/src/lib/results-format.test.ts).

## D-CAP — capítulo de provisiones

Reglas vigentes:

- El capítulo aparece por *any-of*: basta que corra una fuente de provisiones; el orquestador no es
  requisito único.
- Un capítulo emitido nunca puede quedar mudo.
- El motor neutral no cita B-1; IFRS 9 mantiene su encuadre y capítulo propios.
- Las combinaciones “sólo estándar”, “sólo interno”, “ambos sin comparador” y passthrough están
  dentro del contrato, no son bordes descartables.

Gates principales:
[`test_report_builder.py`](../../tests/unit/test_report_builder.py),
[`test_report_step.py`](../../tests/unit/test_report_step.py),
[`test_report_renderer.py`](../../tests/unit/test_report_renderer.py).

## D-VER — quién verificó un cotejo

Reglas vigentes:

- `verified_by` es libre y opcional; vacío significa “no consta” y debe publicarse como tal.
- No inventar, inferir ni completar autoría desde otra evidencia.
- `manifest.verifier` se conserva: cumple otra función y no se reutiliza ni se retira.

Gates principales:
[`test_cmf_verificador.py`](../../tests/unit/test_cmf_verificador.py) y
[`test_normativa_cmf_documento.py`](../../tests/unit/test_normativa_cmf_documento.py).

## D-AMB — columna de cartera ambigua

Reglas vigentes:

- No revertir defaults ni elegir una columna por heurística silenciosa.
- La ambigüedad pertenece al par `(config, dataset)`: se activa sólo con las condiciones exactas
  fijadas en la enmienda, no por el mero nombre de una columna.
- La salida avisa sin bloquear y nombra las candidatas y cómo resolverlo.
- La réplica en la model card es deliberadamente no gobernable: registra el aviso pero no crea
  `FALTA-DATO` ni detiene la corrida.

Gate principal: [`test_columna_cartera_ambigua.py`](../../tests/unit/test_columna_cartera_ambigua.py).

## D-LGD — LGD modelada del método interno

Reglas vigentes:

- La forma de LGD es una unión discriminada; preserva identidad y `config_hash` de configuraciones
  que no optan a las ramas nuevas.
- El motor `LgdEngine` vive en el nivel compartido de provisioning; IFRS 9 conserva compatibilidad.
- No tocar el motor CMF, la regla del máximo ni los fixtures de demo como efecto lateral.
- Las ramas modeladas consumen el frame crudo. **No usar covariables WoE** supervisadas contra el
  target de incumplimiento.
- Piso/techo son idempotentes; huecos, ajuste in-sample y procedencia de la severidad se declaran.
- La cobertura E2E y regulatoria forman parte del contrato.
- Corrección posterior que prevalece: el abanico conserva `options`. La prescripción histórica de
  migrarlo a `answer_forms` quedó descartada al medir: convertiría una elección metodológica en
  respuesta obligatoria. Se corrigieron los oráculos de uniones.

Gates principales:
[`test_internal_provisioning_lgd_modelada.py`](../../tests/unit/test_internal_provisioning_lgd_modelada.py),
[`test_provisioning_lgd.py`](../../tests/unit/test_provisioning_lgd.py),
[`test_jobs_abanico.py`](../../tests/unit/test_jobs_abanico.py) y
[`test_effective_defaults.py`](../../tests/unit/test_effective_defaults.py).

## D-SUB — subsección inerte

Reglas vigentes:

- “Inactivo” poda el campo **y todo su subárbol**.
- La inercia la declara el padre que conoce la condición; no se adivina desde el submodelo.
- El gate sólo trata un submodelo como relevante si contiene columnas consumibles y comprueba las
  ramas encendida y apagada.
- No hacer `lgd` nullable ni retirar `column_role` para evitar el problema.

Gates principales:
[`test_columna_en_rama_inactiva.py`](../../tests/unit/test_columna_en_rama_inactiva.py) y
[`test_jobs_abanico.py`](../../tests/unit/test_jobs_abanico.py).

## D-EXI — una opción exige otro campo

Reglas vigentes:

- El error de dominio se conserva; la UI añade un cuarto estado que dice qué campo falta y permite
  saltar a él.
- El criterio es exacto: unión discriminada, campo no requerido por schema y rama elegida que no se
  puede construir sin ese valor. No ampliar por semejanza verbal.
- El requisito viaja en el punto padre; el emisor del error declara el `loc`.
- D-EXI-6 se cerró en la superficie mediante `when`, filtrando un punto inerte. **No** se relajó el
  validador ni se hicieron válidas dos clases públicas que deben fallar.
- D-OBL quedó fuera de alcance.

Gates principales:
[`test_jobs_abanico.py`](../../tests/unit/test_jobs_abanico.py),
[`test_ui_routes.py`](../../tests/unit/test_ui_routes.py) y
[`jobs.test.ts`](../../web/src/lib/jobs.test.ts).

## D-FTE — fuente de un cotejo

Reglas vigentes:

- La fuente es dato estructurado. Vacío significa “no consta” y esa ausencia se publica.
- Nunca inferir procedencia desde fecha, texto vecino, URL o fuerza del cotejo.
- El parseo de prosa se conserva como cara redundante y gate cruzado, no como fuente primaria.
- Todo cotejo nuevo declara fuente y verificador; las excepciones existentes deben ser literales y
  razonadas.
- La pregunta del cotejo de 2026-06-23 está resuelta: su fuente queda vacía porque no consta.

Gate principal: [`test_normativa_cmf_documento.py`](../../tests/unit/test_normativa_cmf_documento.py).

## D-VIS — ningún error sin superficie

Reglas vigentes:

- Todo error de validación permanece visible. Un ancla suma ubicación; nunca sustituye la superficie
  global del mensaje.
- La UI publica los errores no anclables con su sección y salto, y marca la sección en el sidebar.
- `loc` se normaliza por posición en el schema, recorriendo todas las ramas de una unión y elidiendo
  sólo el tag discriminador; nunca se reescribe por parecido con el path del formulario.
- La validación captura `NikodymError` como clase; no se cambia la jerarquía para parchear un caso.
- Las **98 anclas existentes** fueron revisadas exhaustivamente: las 98 apuntan al campo correcto.
  Ese veredicto no prueba completitud.

Abierto canónico de D-VIS-6:

- El censo vigente halló 208 `raise` en los módulos de configuración inspeccionados: 98 con `loc` y
  110 sin él; 98 de estos últimos son constructores explícitos de errores de dominio.
- `provisioning/config.py` quedó con 10/10 `raise` sin `loc`; hay reproducciones inequívocas para
  `segment_col` y `portfolio_crosswalk`.
- Los siete validadores constructores de `tuning/search_space.py` abortan antes de que
  `resolve_search_space` pueda anclarlos; el comentario que justificaba la omisión es falso.
- Hay criterio inconsistente en helpers de calibration, scorecard, stability, Markov, IFRS 9 y
  forward.
- El gate actual salta todo `raise` sin `loc` y sólo exige dos rutas; podría perder 96 de 98 y seguir
  verde. D-VIS-6 no se declara cerrado hasta tener un gate bidireccional: cada error alcanzable debe
  tener `loc` estático válido o exención explícita y razonada, con controles negativos de ausencia y
  alta nueva.

Gates actuales —insuficientes para completitud, útiles para validez—:
[`test_ui_routes.py`](../../tests/unit/test_ui_routes.py) y
[`validation.test.ts`](../../web/src/lib/validation.test.ts).

## D-EST — la marca de estabilidad es derivable, no decorativa

Aprobada por Cami el 2026-08-27, al abrir el corte de la `1.12.0`. Nace de un defecto medido: la
garantía SemVer se contradecía **en las dos direcciones a la vez** y ningún gate lo notaba.

**D-EST-1 · Una sola fuente decide qué está bajo garantía.**
[`nikodym/testing/stability.py`](../../src/nikodym/testing/stability.py) enumera `STABLE_DOMAINS`,
`EXPERIMENTAL_DOMAINS` y `UNMARKED_PACKAGES`. El *docstring* de cada paquete y la nota de
[`docs_site/api.md`](../../docs_site/api.md) son **consumidores**, no fuentes: antes eran tres listas
distintas y cada una respondía otra cosa.

**D-EST-2 · `model` entra a la garantía.** Es la regresión logística PD del propio pipeline F1 y
SDD-08 la declara F1 desde su cabecera, pero `model/__init__.py` se autodeclaraba *experimental*.
Corregirlo no amplía ningún compromiso: **alinea el código con lo que `AGENTS.md` ya prometía**.

**D-EST-3 · `audit` entra a la garantía, y esto sí es decisión de producto.** No pertenece a F1, así
que su marca «Estable» era una autoconcesión sin respaldo. Cami decidió **promoverlo formalmente**
en vez de degradarlo: el trail JSONL, el hashing y el replay ya son superficie de integración de
terceros, y romperlos en un minor costaría más que sostenerlos. Lo que entra no puede romper hasta
un 2.0.

**D-EST-4 · Mover una entrada de la lista es un cambio contractual.** Entrar compromete hasta el
2.0; salir restringe una garantía publicada. Requiere decisión registrada aquí, nunca la preferencia
de quien edita. El gate
[`test_marca_estabilidad.py`](../../tests/unit/test_marca_estabilidad.py) lo vigila en ambos
sentidos, incluido el paquete nuevo que nadie clasificó.

Abierto declarado: `core` aloja el trío `run` → `Study` → `NikodymConfig`, que `api.md` sí declara
estable, pero no lleva marca de paquete. Dársela ampliaría el compromiso a **todo** `nikodym.core`,
que es más de lo que hoy está decidido. Queda en `UNMARKED_PACKAGES` con su razón escrita, no
resuelto por un agente.

## D-GOB — la gobernanza tiene que ser ALCANZABLE desde `pip install`

Aprobada por Cami el 2026-08-28. Nace del **bloqueador 3** del censo del 2026-08-26: la gobernanza
—el titular del README— no existía en ninguna ruta entregada. Tras una corrida F1 real y completa
`study.results` quedaba `{}`, y el model card salía con `metrics={}`, `metric_sections={}` y
`decisions=0`.

**D-GOB-1 · El productor es el paso; el escritor es `core`.** Un `Step` puede implementar
`metrics(study)` y `metric_sections(study)`; `Study._publicar_metricas` los llama tras `execute` y
es el **único** punto de escritura del canal. Los dos métodos se consultan con `getattr`, como
`optional_requires`: un paso que no los implemente no aporta nada y no falla. La reducción es
conocimiento de dominio y no puede vivir en `core` — AUC, Gini, KS y PSI **no son campos escalares
de ninguna** `CardSection`, así que un agregador genérico publicaría `scorecard.pdo` y
`performance.n_deciles` como «las métricas del modelo» y omitiría el AUC.

**D-GOB-2 · `metrics` es plano: `"<dominio>.<metrica>"`, `float` finito.** El prefijo lo compone
`core`; un dominio que lo devuelva ya puesto recibe `ConfigError`. Es la **única forma que los dos
consumidores aceptan sin modificarlos**, y eso está medido en ambos sentidos: con forma anidada
`ModelCardBuilder` levanta `GovernanceError` mientras `TrackingSink` la aplana sin quejarse. La
contradicción llevaba latente todo 1.x porque el canal estaba vacío. Una métrica no evaluable **se
omite**, con traza en el trail; nunca se rellena con `0.0`, `NaN` ni `None`.

**D-GOB-3/5 · `metric_sections` es un nivel por dominio**, copiado en profundidad de la puerta CT-2
que ya existía en 9 de 13 `CardSection`. Los dominios sin payload estructurado (`data`, `binning`,
`selection`, `eda`) **no** reciben la clave: `{}` y «ausente» dicen lo mismo.

**D-GOB-4 · Cada dominio declara su lista, y el gate la ata en los dos sentidos.**
[`nikodym/testing/metrics.py`](../../src/nikodym/testing/metrics.py) es la fuente canónica, igual
que `testing/stability.py` para la marca SemVer. `test_canal_metricas.py` exige que lo declarado
exista **y** que ningún dominio orquestable quede sin clasificar — la lección de D-VIS-6 aplicada
antes de que el hueco exista.

**D-GOB-6/7 · El directorio de corrida existe sólo si el llamador lo pide.**
`nikodym.run(config, run_dir=...)`. Con el default `None` nada toca el disco, que es el
comportamiento histórico. Con un `run_dir` se escribe allí el layout de SDD-03 §6 —`audit_trail.jsonl`,
`environment.json`, `model_card.json`, `model_card.md`— más `study/` (lo de `Study.save`, en un
subdirectorio porque su swap atómico borraría el trail). Cada archivo depende de que su sección esté
activa. `scenario_log.jsonl` **no** se escribe: no tiene productor, y un archivo vacío sería teatro.
El trail deja de resolverse contra el `cwd`; una ruta relativa sin `run_dir` es error explícito, una
absoluta se respeta. Cierra la violación de SDD-03 §8 («una instancia por run») que hacía que dos
corridas desde el mismo `cwd` concatenaran sus trails.

**D-GOB-8 · `audit` se enciende en los cuatro presets; `governance` no.** `audit` no tiene ningún
campo obligatorio y es lo que da `decisions` al model card. `GovernanceConfig.purpose` es
`Field(default=...)` —obligatorio— porque SR 11-7 exige declarar el propósito, y el propósito es
`DATO-INSTITUCIONAL`: un preset que lo rellenara publicaría un propósito falso en cada card.
`tracking` sigue apagado: exige un servidor MLflow.

> 🔴 **Corrección medida a la enmienda.** §D-GOB-8 anunciaba que encender `audit` movería el
> `config_hash` de los cuatro presets, y que por eso la recaptura de la demo era consecuencia
> necesaria. **Es falso**: `audit` está en `INFRA_SECTIONS`, así que no entra a la identidad de la
> corrida. Los cuatro hashes son idénticos con `audit` encendido y apagado, y los tres fixtures de
> la demo siguen firmando el hash correcto. Lo vigila
> `test_presets_gobernanza.py::test_encender_audit_no_mueve_el_config_hash_de_ningun_preset`.
> Consecuencia: **D-GOB-9 deja de ser obligatoria por identidad**; sigue pendiente por contenido
> (`model_card: null`), y conserva su OK propio.

**D-GOB-9 · La demo se recaptura aparte, con su propio OK.** No ejecutada. Los tres fixtures siguen
con `"model_card": null`, y eso se declara en vez de darse por resuelto.

### Defecto preexistente que D-GOB-8 destapó

Encender `audit` dejó inalcanzable el dominio `survival`: `SurvivalResult.estimator` es un
`AuditableMixin` con el sink inyectado, y su `model_copy(deep=True)` moría con
`TypeError: cannot pickle 'TextIOWrapper' instances`. Al no ser un `NikodymError`, `nikodym.run` ni
lo capturaba: la corrida entera reventaba. **Medido sobre `5d6aa68`, sin nada de D-GOB en el árbol**;
no se veía porque ningún preset traía `audit` encendido. Corregido en `AuditableMixin.__deepcopy__`,
que deja caer `_audit` al `NullAuditSink` de clase — la regla que el propio *docstring* ya declaraba
para `clone()` de scikit-learn.

### Abiertos declarados de D-GOB

1. 🔴 **La ruta de UI para `governance` no existe todavía.** D-GOB-8 dice que «la UI lo ofrece como
   trabajo con `purpose` requerido», y eso **no** está entregado: `governance` aparece en cero de los
   10 trabajos, y en el schema de la interfaz es un *stub* opaco (`{"default": null, "title",
   "description"}`, sin `properties`) porque `build_full_json_schema` **nunca expande las secciones
   INFRA**. Hacerlo alcanzable exige expandir una sección INFRA en la UI, dar `ui_widget`/`ui_group`
   a los campos de `GovernanceConfig` —`purpose` no tiene ninguno—, cablearla a un trabajo y
   regenerar los fixtures. Eso crea **copy público nuevo** (los tooltips derivados de Pydantic lo
   son por `AGENTS.md`) y cambia el tratamiento de INFRA en la interfaz: es más de lo que la
   enmienda midió, y por eso se eleva en vez de improvisarse.
   **La gobernanza sí es alcanzable desde `pip install` por código** —`nikodym.run(config,
   run_dir=...)` con una `GovernanceConfig` escribe el `model_card.json` completo, y hay gate sobre
   el archivo en disco—; lo que falta es el formulario.
2. `AuditConfig.capture_environment` deja de estar inerte: D-GOB-6 obliga a escribir
   `environment.json`, y escribirlo con el campo en `False` habría sido ignorar el config. Es uno
   menos de los cinco campos inertes que §7 de la enmienda dejaba fuera; los otros cuatro siguen.

## Mapa de otros contratos aprobados

Las diez familias anteriores son las que normalizó este traspaso; no son todo el diseño aprobado.
Antes de tocar una superficie de esta tabla, leer su fuente primaria. El mapa evita depender del
corpus histórico o de conocer un ID de memoria:

| Si la tarea toca… | Contratos que gobiernan |
|---|---|
| abanico de métodos, opciones o requisitos visibles | D-ABA-1…12 en [`_SDD-ABANICO-METODOLOGICO.md`](_SDD-ABANICO-METODOLOGICO.md) |
| trabajos, formas de respuesta o ejecutabilidad de UI | D-JOB en [`_SDD-UI-POR-TRABAJOS.md`](_SDD-UI-POR-TRABAJOS.md) y D-EJE en [`_ENMIENDA-TRABAJO-EJECUTABLE.md`](_ENMIENDA-TRABAJO-EJECUTABLE.md) |
| coacción, errores y anclas | D-ANC en [`_ENMIENDA-ANCLA-DESCARTADA.md`](_ENMIENDA-ANCLA-DESCARTADA.md), además de D-EXI/D-VIS |
| preflight, columnas e inercia | D-INV en [`_ENMIENDA-INVARIANTES-PREVIAS.md`](_ENMIENDA-INVARIANTES-PREVIAS.md), D-PRE en [`_ENMIENDA-PREFLIGHT-DATASET.md`](_ENMIENDA-PREFLIGHT-DATASET.md), D-PRO en [`_ENMIENDA-PROCEDENCIA-DE-COLUMNAS.md`](_ENMIENDA-PROCEDENCIA-DE-COLUMNAS.md) y D-RAM en [`_ENMIENDA-COLUMNA-EN-RAMA-INACTIVA.md`](_ENMIENDA-COLUMNA-EN-RAMA-INACTIVA.md) |
| requisitos y resolución de parámetros | CRP-1…7 en [`_CONTRATO-RESOLUCION-PARAMETROS.md`](_CONTRATO-RESOLUCION-PARAMETROS.md), D-CRP6 en [`_ENMIENDA-CRP6-FLAG.md`](_ENMIENDA-CRP6-FLAG.md) y D-REQ en [`_ENMIENDA-REQUISITOS-DECLARADOS.md`](_ENMIENDA-REQUISITOS-DECLARADOS.md) |
| decisiones obligatorias/respondidas | D-OBL en [`_ENMIENDA-DECISIONES-OBLIGATORIAS.md`](_ENMIENDA-DECISIONES-OBLIGATORIAS.md) y D-RES en [`_ENMIENDA-RESPONDIDA-SEGUN-EL-MOTOR.md`](_ENMIENDA-RESPONDIDA-SEGUN-EL-MOTOR.md) |
| evidencia normativa y segmentación | D-COT en [`_ENMIENDA-COTEJO-NORMATIVO.md`](_ENMIENDA-COTEJO-NORMATIVO.md), D-MAX en [`_ENMIENDA-REGLA-DEL-MAXIMO.md`](_ENMIENDA-REGLA-DEL-MAXIMO.md) y D-SEG en [`_ENMIENDA-SEGMENTACION.md`](_ENMIENDA-SEGMENTACION.md) |
| resumen PSI y fronteras de estabilidad | A1/B1 en [`_ENMIENDA-RESUMEN-PSI.md`](_ENMIENDA-RESUMEN-PSI.md): peor PSI score/PD con identidad y banda coherentes; `<stable`, `[stable, review)`, `≥review` |
| frontera del diagnóstico IV | IV-A1 en [`_ENMIENDA-AUDIT-IV-FRONTERA.md`](_ENMIENDA-AUDIT-IV-FRONTERA.md): banda, selección y evento `iv_sospechoso` incluyen IV=0,50; el evento sólo diagnostica, no elimina |

Regla CRP especialmente fácil de romper: `fail_on_falta_dato` significa en las siete capas “una
marca declarada **gobernable** emitida por la corrida la detiene”. Las marcas estructurales se
registran y nunca detienen; el criterio vive en `core/markers.py::governable_warnings()` y no se
reimplementa por motor. El chequeo PIT de IFRS 9 es incondicional y ningún flag lo apaga.

## Decisiones transversales que también permanecen

- CT-1…4 siguen vigentes en
  [`_CONTRATOS-TRANSVERSALES.md`](_CONTRATOS-TRANSVERSALES.md): DAG explícito en
  `Step.requires/provides`, extensiones aditivas de resultados/metrics/overlay, datos scorecard
  transversales frente a capas longitudinales propias y ensamblado de corrida en `api/runner`.
- `data_hash` firma contenido lógico por bloques, no bytes de Parquet. La idempotencia de tracking
  usa `(model_name, nikodym.config_hash)` con aliases/tags `nikodym.*`, no stages.
- El registro de avisos, el alcance de copy público, la estabilidad SemVer y el método SDD se
  resumen en [`../../AGENTS.md`](../../AGENTS.md) y no se duplican aquí.
- El índice [`00-INDICE.md`](00-INDICE.md) sigue siendo un mapa histórico de todo el diseño, no una
  fuente canónica de estados.

## Evidencia histórica preservada

Los corpus previos no se deduplicaron ni reescribieron:

- [`../../historial/AGENTS-HASTA-2026-08-08.md`](../../historial/AGENTS-HASTA-2026-08-08.md)
- [`../../historial/CLAUDE-HASTA-2026-08-08.md`](../../historial/CLAUDE-HASTA-2026-08-08.md)
- `privado/historial/HANDOFF-HASTA-2026-08-08-D-VIS.md`

Conservan trampas y decisiones intermedias que ya se pagaron; no gobiernan el estado actual.
