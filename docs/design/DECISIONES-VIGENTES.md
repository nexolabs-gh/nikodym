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
| D-GOB-1…16 | Aprobada por Cami el 2026-08-28 (1…9) y el 2026-09-03 (10…16); D-GOB-1…8 implementadas y gateadas, con los tres defectos de implementación de la revisión (abiertos 4–6) **corregidos el 2026-09-07**; ruptura D-GOB-7/8 **aceptada** el 2026-09-02; D-GOB-10…16 **aprobadas**; **revisión independiente ejecutada el 2026-09-03** (Codex, `needs-attention`): enmienda corregida y sus tres puntos de §8.1 **respondidos por Cami el 2026-09-07** (validación de `purpose` no vacío: **sí**; capas 10 → 11/12/13/14 → 15/16: **sí**; `governance` **latente** en el esqueleto de los trabajos); **D-GOB-10 implementada y gateada el 2026-09-07 (S2b)**; **D-GOB-11/12/13/14 implementadas y gateadas el 2026-09-07 (S3)**; **D-GOB-15/16 implementadas y gateadas el 2026-09-08 (S4)**, con el abierto 1 **cerrado**; D-GOB-9 con **OK condicionado**: la demo se recaptura mostrando la ficha, con un `purpose` que Cami aprueba en la release 1.13.0; abierto: el capítulo de model card en el informe, **diferido**; copy público de la gobernanza
alineado el 2026-09-09 (S5) | [`_ENMIENDA-GOBERNANZA-ALCANZABLE.md`](_ENMIENDA-GOBERNANZA-ALCANZABLE.md) · [`_ENMIENDA-GOBERNANZA-EN-PANTALLA.md`](_ENMIENDA-GOBERNANZA-EN-PANTALLA.md) |

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

**D-GOB-7/8 · La ruptura de superficie estable queda ACEPTADA.** Ratificado por Cami el
2026-09-02. Las dos decisiones juntas hacen que
`nikodym.run(NikodymConfig.model_validate(get_preset(...)["config"]))` —sin `run_dir`— levante
`ConfigError` en los **cuatro** presets, remedido sobre `3cad020`. Se acepta porque el
comportamiento previo violaba SDD-03 §8 («una instancia por run») escribiendo el trail en el `cwd`
de quien importa la librería, el error nombra el arreglo exacto y la ruptura ya está declarada en
`## [No publicado]` del CHANGELOG con su antes/después. Se anuncia como cambio de comportamiento en
la próxima release. Alternativas evaluadas y descartadas: ablandar D-GOB-7 a aviso —entrega una
garantía más débil que la aprobada— y revertir `audit` en los presets —reabre el bloqueador 3 por
su lado por defecto—.

**D-GOB-9 · La demo se recaptura aparte, con su propio OK.** **OK de Cami el 2026-09-03, con
condición**: la recaptura muestra la ficha del modelo, así que los capturadores encienden
`governance` y declaran un `purpose` para la institución ficticia de la demo. Ese `purpose` es
`DATO-INSTITUCIONAL` y copy público: lo propone el agente y lo aprueba Cami en la sesión de release
de 1.13.0, antes de lanzar `recapture-demo.yml`. Se ejecuta sobre el commit de la release, para que
los fixtures firmen la versión publicada, igual que `ddb616f` con 1.12.0. **No ejecutada aún**: los
tres fixtures siguen con `"model_card": null`.

**D-GOB-10…16 · La gobernanza tiene que ser VISIBLE en la interfaz.** Aprobadas por Cami el
2026-09-03 tal como las redacta
[`_ENMIENDA-GOBERNANZA-EN-PANTALLA.md`](_ENMIENDA-GOBERNANZA-EN-PANTALLA.md); **D-GOB-10
implementada el 2026-09-07 (S2b)**, **D-GOB-11/12/13/14 implementadas el 2026-09-07 (S3)**,
**D-GOB-15/16 implementadas el 2026-09-08 (S4)**. En una línea cada una:
**D-GOB-10** `governance` se expande por un `_INFRA_CONFIG_CLASSES` propio
en `core/study.py`, nunca por `_DOMAIN_CONFIG_CLASSES`, porque `_DEFAULT_DOMAIN_ORDER` deriva el
pipeline de esa lista y `governance` no tiene `Step`; `_DEFAULT_DOMAIN_ORDER` y el `config_hash` no
se mueven. **D-GOB-11** la sección entra a `CONFIG_SECTIONS` (14 → 15) y a los **10 trabajos**, como
`report`, apagada de fábrica en los cuatro presets. **D-GOB-12** `purpose` va al bloque «Tus
decisiones» como decisión obligatoria (D-OBL/D-EXI). **D-GOB-13** las 13 descripciones pasan a ser
copy público con el texto exacto de la tabla §3 de la enmienda. **D-GOB-14** `scenario_log_filename`
no se expone (D-SUB). **D-GOB-15** «Ficha del modelo» en Resultados tras «Artefactos de la corrida»,
con guard por presencia. **D-GOB-16** `model_card` deja de ser `Record<string, unknown>` y pasa a un
tipo `ModelCard` explícito. Las respuestas de Cami a las cuatro preguntas del §8: sí, sí, **diferir**
el capítulo del informe, los 10 trabajos. Orden de implementación —corregido el 2026-09-07 por la
respuesta 2 de §8.1—: **10 → 11/12/13/14 → 15/16**, cada capa con medición previa, gates y control
negativo (§6 de la enmienda). **Antes de la primera capa, revisión independiente de la enmienda**
(AGENTS.md): si devuelve hallazgos, se corrige el documento y se vuelve a elevar sólo lo que cambie.

> 🔴 **Revisión independiente ejecutada el 2026-09-03** (Codex, rango `5d6aa68..a9a1668`,
> `needs-attention`, seis hallazgos verificados contra el árbol; evidencia íntegra en el repo
> privado). Los tres sobre el documento están corregidos en la enmienda (§0.3–§0.6, §3, §6, §7) y
> dejan **tres decisiones nuevas en su §8.1**: la validación de `purpose` no vacío —sin ella
> D-GOB-12 es falsa—, el orden de capas **10 → 11/12/13/14 → 15/16** —cinco gates vigentes hacen
> que D-GOB-11 no sea entregable sin 12/13/14— y `governance` **latente** en el esqueleto de los
> trabajos —hoy `jobSkeleton` siembra encendida toda sección del trabajo—. **OK de Cami a los tres
> el 2026-09-07: sí, sí, latente.** Los tres hallazgos sobre la implementación de D-GOB-1…8 son los
> abiertos 4–6 de abajo, corregidos en código antes de la primera capa. Además el registro contenía
> una instrucción **sustituida** por D-GOB-10 —«sumar `governance` a `_DOMAIN_CONFIG_CLASSES`»—
> que se corrige en el abierto 1.

**D-GOB-10 · Implementada el 2026-09-07 (S2b).** `core/study.py` gana `_INFRA_CONFIG_CLASSES`
(sólo `governance`, con el porqué escrito al lado); `core/config/schema.py` gana
`cargar_configs_de_infra()` y `cargar_configs_expandibles()` —la unión ordenada, dominios primero,
sobre un solo helper de import para que la degradación por extra ausente sea la misma— y
`build_full_json_schema()` expande la unión. La consumen el catálogo de defaults efectivos
(D-FX-10), la guarda de opacidad de `gen_schema_fixture`, el gate del fixture y
`/api/validate`/`preflight`. `cargar_configs_de_dominio()` conserva su significado: quien pregunta
«¿qué corre?» —pipeline, coacción antes de hashear, preflight de columnas, `orchestrable_domains`—
no cambió. Medido: `_DEFAULT_DOMAIN_ORDER` intacta, `config_hash` de los cuatro presets intacto,
golden del formulario intacto (394 hojas), golden del catálogo 1064 → 1076 (−1 descriptor de
sección, +13 hojas, 0 valores alterados) y `$defs` 104 → 104. **D-HASH-5 sobre la sección nueva,
precisado al implementar**: el hueco existe en el motor —en proceso fresco `NikodymConfig` acepta
`review_period_months: 999` sin loader y también tras `cargar_configs_de_dominio()`, que no importa
`nikodym.governance`; sólo la unión lo cierra— y ahí se gatea con `python -I`; por `/api/validate`
no era observable porque `ui/serializers.py` importa la capa al cargarse, medido con el control
negativo «sólo el loader de dominios en `validate_config`», que **no enrojeció**: la llamada a la
unión en las rutas es blindaje del contrato, no la corrección de un defecto visible. Gates en
`test_gobernanza_expandible.py`, con controles negativos en los tres sentidos de §6 (mapa INFRA,
orden de ejecución, unión del loader). Corrección al censo de la enmienda: dos espejos del catálogo
en `test_effective_defaults.py` estaban bajo D-GOB-11 y son de D-GOB-10 (anotado en su §3). Y un
consumidor que ningún censo nombró porque barre el **fixture**: el gate de portada de D-JUR
(`test_portada_sin_jurisdiccion`) vio «CMF» en `governance.motor` al expandirse la sección; entra a
`_SECCIONES_CON_JURISDICCION` con su razón escrita —el campo enumera los motores
(`scoring`/`cmf`/`ifrs9`) y el copy aprobado de D-GOB-13 también nombra CMF: evidencia del
inventario, no titular—, y el control positivo del gate la sigue exigiendo como ofensora.

**D-GOB-11/12/13/14 · Implementadas el 2026-09-07 (S3), juntas, con las respuestas 1 y 3 de
§8.1.** `governance` es la **15.ª** entrada de `CONFIG_SECTIONS` —«Gobernanza», después de
«Informe»— y cierra las `sections` de los **diez** trabajos. «Apagada de fábrica» quedó definida
también para el esqueleto: el catálogo declara la latencia **por sección** (`_SECCIONES_LATENTES`
en `ui/jobs.py`, con su razón) y la publica por trabajo como `latent_sections`; `jobSkeleton` gana
un cuarto paso, `apagarSeccionesLatentes`, que siembra la sección en `null` explícito —también si
el config traía la sección encendida, por D-JOB-9—, y su réplica Python y el ancla estática de
`test_jobs_ejecutables.py` pasan de tres pasos a cuatro. `purpose` es la única decisión de la
sección (`_DECISIONES_POR_SECCION["governance"]`, sin formas: se escribe, no se elige; pregunta y
ayuda son frases del copy aprobado), y la tarjeta gana un cuarto estado excluyente, **`dormant`**:
una decisión cuya sección está apagada en el config no se pregunta, no cuenta en ningún contador
y no ofrece «Ir al campo»; se decide por el config y no por el catálogo, así que vale igual para
`survival` apagada a mano. La validación de `purpose` en blanco vive en las tres capas: un
`field_validator` en `GovernanceConfig` (normaliza con `strip()`, mensaje en español),
`/api/validate` con `loc = ["governance", "purpose"]` y sin el prefijo inglés de Pydantic, y la
tarjeta, donde una decisión escalar sin formas está pendiente mientras su dato esté en blanco
—criterio nuevo: hasta entonces la presencia de la clave bastaba, y `purpose: ""` habría salido
«contestada»—; `estaVacio` pasa a tratar un texto de solo espacios como vacío, para todos los
huecos. Las 12 descripciones visibles son el texto de la tabla §3 palabra por palabra —el énfasis
Markdown de «**no**» en `limitations` no viaja al tooltip—, los 8 campos sin widget lo ganan en tres
grupos («Inventario», «Ficha del modelo», «Ajustes manuales»), `purpose` es `textarea`, y
`scenario_log_filename` lleva `ui_widget: hidden`: sigue en el config por código y no aparece en el
censo del formulario. Medido con baseline por `git archive` de `58ebc36`: golden del formulario
**513 → 527** (0 desapariciones, 14 apariciones: 12 campos + `assumptions[]` y `limitations[]`),
paridad **396 → 410** por los mismos 14, catálogo **1076 → 1076** y `$defs` 104 → 104, como
predijo S2b; `config_hash` de los cuatro presets intacto. Consumidores que preguntan «¿qué ofrece el
formulario?» pasan al loader de la unión (`test_jobs_decisiones`, `test_jobs_formas_de_respuesta`,
`test_jobs_abanico`, `test_invariantes_previas`, `test_column_roles`, los espejos de
`test_effective_defaults` y `ui/option_surface.py`), y lo que eso destapó se declaró con razón:
`governance.{motor, fase, estado_validacion}` son tags descriptivos y no abanico (D-ABA-3; entran
a `_DETAIL_POLICIES` y el ledger crece 475 → 491 pares), `governance` es exenta de invariantes
previas («no corre ni declara columnas») y declara extra `None` en el gate de `[ui]`. **Una
precisión de gate, no una relajación**: el tope de 160 caracteres del placeholder no aplica a un
`textarea` porque `TextareaField` no pasa `placeholder` a su control —medido, y anclado al fuente
del front para que vuelva a aplicar si eso cambia—; sin esa precisión el copy aprobado de `purpose`
(162 caracteres) habría obligado a reescribirlo. Gates en `test_gobernanza_en_pantalla.py` (§6.4,
§6.5, §6.6, §6.8, §6.10 en motor e interfaz, §6.11 en `/api/run`), `test_jobs_ejecutables.py`
(latentes) y `web/src/lib/jobs.test.ts` (tarjeta: dormidas y escalar en blanco), con controles
negativos en los tres sentidos que pedía la sesión. El abierto 1 de abajo se cierra con D-GOB-15/16.

**D-GOB-15/16 · Implementadas el 2026-09-08 (S4), juntas.** «Ficha del modelo» es una sección de
`ResultsTab.tsx` inmediatamente después de «Artefactos de la corrida» —el primer `h2` del panel—,
montada sólo por `results.model_card ? … : null` y nunca con `!`: sin card no hay bloque, ni vacío
ni fabricado, y los tres fixtures de la demo (`model_card: null`) siguen válidos sin recaptura.
Pinta el propósito, los supuestos y las limitaciones; las fechas de **emisión** —`review_date`, la
que el builder fija al construir la ficha y desde la que cuenta `review_period_months`— y de próxima
revisión, como fecha calendario; las métricas planas agrupadas por dominio con el rótulo de su
sección del formulario y, bajo cada dominio, su evidencia estructurada CT-2 aplanada a filas
`subsección · clave → valor`; y el conteo de decisiones con un detalle desplegable, una fila por
evento del trail. Lo que la ficha **no** pinta está declarado con su razón en
`MODEL_CARD_NO_PINTADO` (`web/src/lib/model-card.ts`), con el mismo gate en dos sentidos que
`LINEAGE_NO_PINTADO`: identidad, hashes, código, semilla, `created_at`, entorno y `data_description`
ya se leen en la procedencia o llegan como métricas del dominio de datos, y `determinism_caveats` ya
viajan dentro de las limitaciones que el motor compone. `model_card` pasa de `Record<string,
unknown> | null` a `ModelCard | null`, con `ModelCardDecision`, `ModelCardEnvironment` y
`ModelCardDataDescription`: las 19 claves **remedidas el 2026-09-08** sobre `GET
/api/results/<run_id>` de una corrida real con gobernanza declarada por el formulario de S3
(`b9633af1…`: 24 métricas, 41 decisiones, secciones CT-2 de `performance` y `stability`), en el
orden del modelo Pydantic; un gate Python compara las cuatro interfaces con `model_fields` en los
dos sentidos y otro exige que lo que `serialize_study` emite hoy sea exactamente esa lista, anidados
incluidos. **Dos cosas que la enmienda no fijaba y la implementación fijó**: (1) la premisa «el
bundle tiene cero “Ficha del modelo”» era cierta el 2026-09-02 y **S3 la movió**: el rótulo es el
`ui_group` de cuatro campos de `GovernanceConfig` y viaja en `schema.json`, que se empaqueta (4
ocurrencias antes de S4); el gate del bundle mide lo que aportan los fixtures empaquetados y exige
al menos una ocurrencia propia de cada rótulo de la sección («Ficha del modelo» 4 → 5; «Próxima
revisión», «Decisiones registradas» y «Métricas por dominio» 0 → 1; `model_card` 0 → 2). (2) Para
renderizar el panel real en vitest sin DOM ni dependencias nuevas, `ResultsTab` se parte en un
wrapper que lee el store y un `ResultsPanel` por props, que el test renderiza con `react-dom/server`
a HTML estático con card, con `null`, con los tres fixtures de la demo enteros y con una corrida
fallida; un guardrail sobre el fuente exige que la única lectura del store sea el wrapper. Gates en
`web/src/components/ResultsTab.test.ts`, `web/src/lib/model-card.test.ts` y la sección final de
`test_gobernanza_en_pantalla.py`; controles negativos en los tres sentidos que pedía la sesión
(quitar el guard, pintar un bloque con card `null`, renombrar una clave del tipo). Recorrido en la
UI viva: corrida sin gobernanza (`e1a6f7d4…`, `model_card: null`, cero rótulos de la ficha) y con
ella por el interruptor y el `textarea` de S3. **El abierto 1 de abajo queda cerrado.**

**Revisión adversarial de S4 (Codex, `needs-attention`, un hallazgo medium, corregido el mismo
día).** La tabla de decisiones y la evidencia CT-2 pueden llevar códigos de aviso declarado
—`internal_falta_dato` con `fail_on_falta_dato=False` deja el código de la institución en `valor`
al imputar a cero un dato ausente, y la sección CT-2 de `provisioning_internal` publica sus
`warning_codes`—, y la ficha los publicaba mudos. Corrección en el front, sin tocar el motor: la
fila se marca «aviso declarado» —reconocido por `esAvisoDeclarado`, nunca por el literal— y la
sección explica en prosa qué significa; el código se conserva tal cual como dato de auditoría, con
el mismo criterio que el volcado del anexo del informe, y sin avisos no hay nota. Gate: render con
la decisión real de imputación y con `warning_codes` en la evidencia, nacido rojo; control
negativo: dejar la marca siempre en falso pone rojo el helper y el render. **La segunda
revisión (sobre la corrección) devolvió otro medium, también sostenido**: la nota generalizaba
«el cálculo siguió con un valor imputado» a todo aviso, y `provisioning_falta_dato` con
`DATO-INSTITUCIONAL-PROV-3` (`require_both=False`, comparación incompleta) no imputa nada.
Corregido: la nota describe el aviso como salvedad —algo que le corresponde a la institución o
una brecha del motor— y remite el significado exacto de cada código a la referencia «Avisos
declarados»; test de render con `PROV-3` que exige no atribuir imputación, nacido rojo.

**Documentación pública de D-GOB (S5, 2026-09-09), sin enmienda.** El copy público decía desde 1.0
«gobernanza (model card + audit-trail) automática» —README, portada y dos guías— y D-GOB-8 la dejó
apagada de fábrica; remedido sobre `2641e43`: `governance` es `None` por defecto y en los cuatro
presets, `audit` va encendido sólo en los presets y el lineage es de toda corrida. Y el quickstart
publicado en siete superficies —`nikodym.run(config)` sobre el preset F1, sin `run_dir`— **falla
hoy** con `ConfigError` por D-GOB-7/8 (reproducido; `run_dir` no existe en la 1.12.0 publicada, pero
el sitio se construye desde `main` y ya publicaba esa API en la guía de provisiones, el CHANGELOG y
la referencia). Corrección: el quickstart pasa `run_dir` y es un solo bloque en README, portada y
«Empezar»; el copy distingue lo que viene solo (lineage), lo que traen encendido los presets
(auditoría) y lo que se enciende (la ficha, con propósito); una guía nueva
([`docs_site/guias/gobernanza.md`](../../docs_site/guias/gobernanza.md)) explica el interruptor,
el propósito obligatorio, los supuestos y limitaciones en JSON, la periodicidad y lo que pinta
«Ficha del modelo» en Resultados, sin prometer el capítulo del informe (abierto 3) ni la demo con
ficha (D-GOB-9). Gates nacidos rojos: `test_docs_quickstart.py` ejecuta el quickstart y el tutorial
tal como se publican y exige `run_dir=` en todo fragmento con preset; `test_docs_gobernanza.py`
proscribe el automatismo, ata «apagada de fábrica» y «propósito obligatorio» al código, cita los
rótulos reales del front y del config, ejecuta el ejemplo por código de la guía y ata el catálogo
de trabajos de «Empezar» a `list_jobs()`. De paso: la portada afirmaba que el hash del `uv.lock`
«viaja vacío» y `build_uv_lock_hash()` lo firma; «Empezar» fijaba «serie 1.10.x» a mano; la
consultora se nombra Nexo Labs en todo el copy (`site_author` y la guía de provisiones decían
otra cosa). La versión «1.12.0» de portada y referencia se mueve en la release (S6).

### Defecto preexistente que D-GOB-8 destapó

Encender `audit` dejó inalcanzable el dominio `survival`: `SurvivalResult.estimator` es un
`AuditableMixin` con el sink inyectado, y su `model_copy(deep=True)` moría con
`TypeError: cannot pickle 'TextIOWrapper' instances`. Al no ser un `NikodymError`, `nikodym.run` ni
lo capturaba: la corrida entera reventaba. **Medido sobre `5d6aa68`, sin nada de D-GOB en el árbol**;
no se veía porque ningún preset traía `audit` encendido. Corregido en `AuditableMixin.__deepcopy__`,
que deja caer `_audit` al `NullAuditSink` de clase — la regla que el propio *docstring* ya declaraba
para `clone()` de scikit-learn.

### Abiertos declarados de D-GOB

1. ✅ **La ruta de UI para `governance` es un YAML, no un formulario.** *(CERRADO el
   2026-09-08, S4: el cierre está al final de este punto.)* D-GOB-8 dice que «la UI
   lo ofrece como trabajo con `purpose` requerido», y ese **formulario** no está entregado:
   `governance` aparece en cero de los 10 trabajos y en el schema de la interfaz es un *stub* opaco
   (`{"default": null, "title", "description"}`, sin `properties`).

   > 🔴 **Corrección medida el 2026-09-02.** La redacción anterior atribuía el *stub* a que
   > `build_full_json_schema` «nunca expande las secciones INFRA», y decía que entregarlo «cambia el
   > tratamiento de INFRA en la interfaz». **Las dos afirmaciones son falsas.** Lo que la función
   > expande es exactamente `_DOMAIN_CONFIG_CLASSES` (22 entradas), y **`report` está ahí siendo
   > INFRA**: se expande en el schema, es una de las 14 `CONFIG_SECTIONS` del front y se ve como
   > «Informe» en el sidebar de los trabajos. Existe por tanto un precedente **entregado** de
   > sección INFRA con formulario. `governance`, `audit` y `tracking` faltan de ambas listas, que es
   > otra cosa: entregar el formulario no cambia el tratamiento de INFRA ni mueve el `config_hash`
   > —`governance` sigue excluida por `INFRA_SECTIONS`, igual que `report`—.

   > 🔴 **Y hay una ruta que SÍ existe hoy**, medida de punta a punta sobre la interfaz viva el
   > 2026-09-02: importar un YAML con bloque `governance:` por «Cargar un YAML existente».
   > `POST /api/config/from-yaml` lo conserva —y `to-yaml` lo devuelve—, el front guarda el config
   > entero (nada lo poda) y `POST /api/run` lo envía. Corrida real del preset F1 con `governance`
   > sobre `consumo_comportamiento` (6.000 filas), `run_id 4b04cbdeed9a45d5b701aabbb8760eff`: la
   > interfaz rotula «El config activo viene de "f1-con-gobernanza.yaml"» y
   > `GET /api/results/<run_id>` devuelve el card con **24 métricas, 41 decisiones**, las secciones
   > CT-2 de `performance` y `stability`, y el `purpose` que escribió el usuario. La capacidad es
   > por tanto **alcanzable pero indescubrible**, no inalcanzable.

   Entregar el formulario exige: expandir `governance` en el schema —**por `_INFRA_CONFIG_CLASSES` y
   el loader combinado, nunca por `_DOMAIN_CONFIG_CLASSES`**, que fija el pipeline (D-GOB-10; la
   redacción anterior de esta frase decía lo contrario y la revisión del 2026-09-03 la corrigió)—,
   sumarla a `CONFIG_SECTIONS`, dar `ui_widget`/`ui_group` a **8 de sus 13 campos** —los otros 5 ya
   los tienen, en el grupo «Inventario»—, cablearla a uno o más trabajos y regenerar los fixtures.
   Eso crea **copy público nuevo** (los tooltips derivados de Pydantic lo son por `AGENTS.md`), y
   las 8 descripciones que faltan están escritas para desarrollador —«clave del MLflow Registry»,
   «SR 11-7», «True requiere el extra tracking», «JSONL append-only», «anti earnings-management»—,
   así que hay que reescribirlas. Además `scenario_log_filename` nombra un archivo que D-GOB-6
   decidió **no escribir**: exponerlo sería una subsección inerte (D-SUB). **La gobernanza sí es
   alcanzable desde `pip install` por código** —`nikodym.run(config, run_dir=...)` con una
   `GovernanceConfig` escribe el `model_card.json` completo, y hay gate sobre el archivo en disco—.

   🔴 **Y hay una segunda mitad, medida sobre la interfaz EN EJECUCIÓN: aunque se encienda
   `governance` por config, el model card no se pinta en ninguna parte.** Verificado el 2026-08-28
   levantando `nikodym-ui` sobre una corrida real del preset F1 con gobernanza declarada (cartera de
   6.000 filas): `GET /api/results/<run_id>` devuelve el card **completo** —24 métricas, 41
   decisiones y las secciones CT-2 de `performance` y `stability`—, y el bundle servido (1,65 MB)
   contiene **cero** ocurrencias de `model_card`, `modelCard`, `metric_sections`, «Model card» o
   «Ficha del modelo». `ResultsTab.tsx` enumera las claves que pinta —`binning`, `calibration`,
   `lineage`, `model`, `performance`, `provisioning*`, `scorecard`, `stability`— y `model_card` no
   está entre ellas.

   **Reconfirmado el 2026-09-02 sobre la pantalla renderizada**, no sólo sobre el bundle: en la
   corrida `4b04cbde…` —con el card completo en su API— la pestaña «Resultados» no contiene
   ninguna de trece expresiones buscadas («Model card», «Ficha del modelo», «Gobernanza»,
   «Propósito», «Supuestos», «Limitaciones», `model_card`, `purpose`, `next_review`…) y su HTML
   renderizado no menciona `model_card` ni una vez. **El informe tampoco lo lleva**: su única
   ocurrencia de `model_card` es la `CardSection` `model.model_card` del anexo C.4 —el card del
   modelo PD, otra cosa— y el `purpose` declarado por el usuario no aparece en el documento.

   Es decir: el dato llega hasta la API de la interfaz y **muere ahí**. Cerrar el bloqueador 3 por
   el lado de la interfaz son por tanto **dos** trabajos, no uno: el formulario que haga descubrible
   la sección y la superficie que muestre lo que produce. Ninguno estaba en la enmienda.

   ➡️ **Cierre aprobado por Cami el 2026-09-03**:
   [`_ENMIENDA-GOBERNANZA-EN-PANTALLA.md`](_ENMIENDA-GOBERNANZA-EN-PANTALLA.md), D-GOB-10…D-GOB-16.
   Cubre los dos trabajos, el copy público de los 13 campos y el mapa INFRA propio que exige el
   hecho de que `governance` no tenga `Step`. **Aprobada, no programada**: se implementa por capas
   (10/11 → 12/13/14 → 15/16) tras la revisión independiente del documento. Este abierto se cierra
   cuando la capa 15/16 pase su gate del bundle («Ficha del modelo» de cero a ≥ 1) y el recorrido
   en navegador.

   ➡️ **CERRADO el 2026-09-08 (S4)**: la capa D-GOB-15/16 pasó su gate del bundle —«Ficha del
   modelo» de 4 (los `ui_group` de S3 empaquetados en `schema.json`) a 5, y los rótulos propios de
   la sección de 0 a ≥ 1— y el recorrido en navegador con una corrida real con gobernanza por el
   formulario (`b9633af1…`, la ficha como primer `h2` tras la procedencia) y otra sin ella
   (`e1a6f7d4…`, sin bloque). Quedan aparte D-GOB-9 (recaptura de la demo con la ficha, OK propio) y
   el abierto 3 (la ficha en el informe), diferido.
2. `AuditConfig.capture_environment` deja de estar inerte: D-GOB-6 obliga a escribir
   `environment.json`, y escribirlo con el campo en `False` habría sido ignorar el config. Es uno
   menos de los cinco campos inertes que §7 de la enmienda dejaba fuera; los otros cuatro siguen.
3. **El informe no lleva la ficha del modelo — DIFERIDO por Cami el 2026-09-03** (§8.3 de la
   enmienda). Medido sobre la corrida `4b04cbde…`: la única ocurrencia de `model_card` en el informe
   es la `CardSection` `model.model_card` del anexo C.4 —el card del modelo PD, otra cosa— y el
   `purpose` del usuario no aparece, pese a que existe un capítulo «Limitaciones y supuestos».
   Entrar exige una enmienda propia contra SDD-26 (contrato de capítulos): no se cuela en
   D-GOB-10…16.
4. ✅ **`_preparar_run_dir` apartaba el run anterior antes de saber si el reemplazo se construía**
   (`api.py`, D-GOB-6). Movía un destino no vacío a un respaldo lateral y creaba el nuevo **antes**
   de `assemble_run` y de la corrida; un error temprano —pedir inventario sin el extra `tracking`,
   por ejemplo— dejaba la ruta canónica vacía y el run previo sólo en el respaldo, sin restaurar.
   `Study.save` sí restaura el previo si falla el swap, y el docstring de `_preparar_run_dir`
   afirmaba compartir esa política. Hallazgo de la revisión del 2026-09-03, verificado por lectura.
   **Corregido el 2026-09-07 (S2a)**: la corrida entera se construye en un hermano temporal
   `.<nombre>.*.tmp` y el destino se sustituye sólo con el artefacto completo
   (`_consolidar_run_dir`); ante cualquier excepción el temporal se descarta y el destino queda
   byte a byte como estaba. La corrida previa **se conserva** en el respaldo lateral
   `.<nombre>.old.*` —única divergencia deliberada respecto de `Study.save`, que descarta el previo:
   el `run_dir` lleva el audit-trail, evidencia append-only de SDD-03 §8, y una librería no la
   borra en silencio—. Gates en `test_run_dir.py`: centinela previo y fallo inyectado en
   `assemble_run`, en la corrida (con la comprobación, desde dentro, de que el destino sigue
   intacto mientras corre), en la escritura de la evidencia y en el propio swap.

   > 🔴 **Revisión adversarial de S2a (Codex, `8f650b8..21505b0`, 2026-09-07,
   > `needs-attention`) y corrección S2a-bis el mismo día.** Dos hallazgos sobre la sustitución
   > atómica recién construida, verificados y reproducidos con gates que nacieron rojos. (a) `run`
   > pasaba el temporal como `run_dir` y `_resolver_trail` respetaba tal cual una ruta absoluta:
   > un `trail_filename` absoluto **dentro** del `run_dir` abría en *append* el trail de la corrida
   > previa mientras la nueva se construía al lado —un fallo contaminaba la evidencia anterior; un
   > éxito publicaba una corrida sin trail con un card que leía las decisiones de las dos—. Ahora
   > `_resolver_trail(audit_cfg, run_dir, workdir)` resuelve contra el destino definitivo y
   > traslada al temporal todo lo que caiga dentro de él. (b) El `except BaseException` descartaba
   > el temporal con `rmtree`, y con él el trail que ya llevaba `run_start`, las decisiones y el
   > `run_end` con el diagnóstico (D-ERR-10): ante una excepción que no es de dominio `run` no
   > devuelve el `Study` (D-UI-2), así que borraba la única evidencia que sobrevivía —que antes de
   > S2a quedaba en el propio `run_dir`—. Ahora `_apartar_run_dir_fallido` conserva el temporal
   > como hermano `.<nombre>.failed.*` si tiene evidencia —también la corrida completa cuyo *swap*
   > falló— y anota la ruta en la excepción; sin evidencia no queda rastro. Cinco gates en
   > `test_run_dir.py` (tres nuevos, dos reescritos) y controles negativos en ambos sentidos.
   > **Segunda revisión** (`21505b0..a593be7`, `needs-attention`, un hallazgo medium): la reserva
   > del hermano `.failed.*` —un `mkdtemp`— quedaba fuera del `try`, así que con el disco lleno su
   > `OSError` sustituía a la excepción original y la nota no se añadía. Corregido en la misma
   > capa: el rescate entero va bajo el `try`, y si falla el temporal `.tmp` se queda donde está
   > con su ruta anotada. Gate con `ENOSPC` inyectado y su control negativo.
5. ✅ **La entrada del inventario y `model_card.json` no eran el mismo card.**
   `_escribir_layout_del_run` resolvía el trail contra `run_dir` (D-GOB-7) y
   `_build_inventory_entry` reconstruía otro card con `audit_cfg.trail_filename` **crudo**, relativo
   al `cwd`: con el default `audit_trail.jsonl` el inventario recibía `decisions=[]` y la
   limitación «trail ausente» mientras el archivo en disco llevaba las decisiones reales. El único
   test (`test_api_run.py::test_run_publica_inventario_solo_en_exito`) usaba una ruta absoluta y
   no comparaba decisiones. Verificado por lectura. **Corregido el 2026-09-07 (S2a)**: un solo
   `ModelCard` por corrida (`_model_card_de_la_corrida`), con el trail resuelto contra el
   directorio de la corrida, compartido por disco e inventario. Gate:
   `test_api_run.py::test_el_inventario_recibe_el_mismo_card_que_queda_en_disco`, con `run_dir`,
   trail relativo y `publish_to_inventory=True` sobre el `assemble_run` real, comparando los dos
   cards byte a byte.
6. ✅ **El gate bidireccional de D-GOB-4 no cubría cinco métricas declaradas**
   (`test_canal_metricas.py::test_toda_metrica_declarada_existe_en_el_codigo`): enumeraba seis
   dominios escalares, para `performance` sólo exigía algún `auc_*` —ni `gini_*` ni `ks_*`— y no
   incluía `stability` (`worst_psi`, `worst_csi_value`). Quitar esos productores dejaba el gate
   verde. Verificado por lectura. **Corregido el 2026-09-07 (S2a)**: el oráculo es
   `nikodym.testing.metrics.missing_declared_metrics`, que recorre toda la declaración y resuelve
   cada plantilla con el mismo criterio que `is_declared_metric`; el fixture ejerce los ocho
   dominios declarados (`performance` con `min_rows_per_partition=4`, `stability` con dos bins y
   sin eje temporal, medido sobre el frame de 30 filas). Controles negativos automatizados: el
   oráculo nombra exactamente cada una de las 18 entradas declaradas al retirarla, y quitar el
   productor de cada una de las cinco familias del hallazgo pone rojo al gate nombrándola.

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
| resumen PSI y fronteras de estabilidad | A1/B1 en [`_ENMIENDA-RESUMEN-PSI.md`](_ENMIENDA-RESUMEN-PSI.md): peor PSI score/PD con identidad y banda coherentes; `<stable`, `[stable, review)`, `≥review`. **Copy del resumen, decidido por Cami el 2026-09-03**: el rótulo «Peor PSI entre score y PD» se mantiene; los nombres de las tres bandas pasan a copy público en español (las palabras exactas se proponen y aprueban al implementar; hasta entonces `stable`/`review`/`redevelop` siguen en el motor). Cierra la única elección de producto que AGENTS.md citaba como abierta; queda pendiente de implementación |
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
- **Corrección de método (2026-09-09, S5, sin SDD): el sitio de documentación se construye con
  `mkdocs build --strict` también en CI** (job `Docs` de `ci.yml`), no sólo en `deploy.yml`. Hasta
  entonces un enlace roto o una página fuera del `nav` pasaba un CI verde y se descubría al
  desplegar, con el deploy en rojo y `main` ya avanzado. Es el mismo comando en los dos sitios;
  `deploy.yml` lo conserva porque publica exactamente lo que construye. Control negativo: un ancla
  rota en una rama temporal puso rojo el job nuevo en CI y verde el resto.

## Evidencia histórica preservada

Los corpus previos no se deduplicaron ni reescribieron:

- [`../../historial/AGENTS-HASTA-2026-08-08.md`](../../historial/AGENTS-HASTA-2026-08-08.md)
- [`../../historial/CLAUDE-HASTA-2026-08-08.md`](../../historial/CLAUDE-HASTA-2026-08-08.md)
- `privado/historial/HANDOFF-HASTA-2026-08-08-D-VIS.md`

Conservan trampas y decisiones intermedias que ya se pagaron; no gobiernan el estado actual.
