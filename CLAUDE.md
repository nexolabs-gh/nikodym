# CLAUDE.md — Nikodym RiskLib

@AGENTS.md

> `AGENTS.md` es la fuente de verdad del contexto de trabajo (común a Claude Code y Codex). Mantener ambos coherentes.
> Para arrancar una sesión, leer primero [`HANDOFF.md`](HANDOFF.md).
> Nikodym `1.5.0` está en PyPI (tag `v1.5.0`, 2026-07-22, cierre del bloque **B1**); el proyecto ya no está en construcción por capas sino en mejora continua. El **track pre-Interbank está completo** (IBK-01…05 cerradas); no hay bloque IBK siguiente, y el freeze de artefactos terminó con la reunión del 2026-07-22. El plan vigente son los bloques **B1…B8** del `ROADMAP`: el bloque en curso es **B2** (UI instalable), que habilita `1.6.0` — **B2.0, B2.1 y B2.2 están cerrados** (B2.2 —launcher, runtime y seguridad— el 2026-07-24, con los 16 jobs del CI verdes); sus decisiones quedaron **consolidadas en SDD-23 y SDD-25**, así que `docs/design/_ENMIENDA-B2.2.md` es ya registro histórico y no contrato vigente. El siguiente nodo es **B2.3** (`[ui]`, uploads y presets), que exige su propia enmienda antes de programar.
>
> **Taxonomía de marcas (2026-07-25, ejecutada y publicada):** un aviso declarado se marca
> `FALTA-DATO` si la carencia es **del motor** o `DATO-INSTITUCIONAL` si el dato **lo aporta la
> institución**. El contrato vive en `src/nikodym/core/markers.py` y **ningún filtro debe comparar
> el literal**: se consume `is_declared_warning()`. Un código interno **nunca** va al copy público:
> ahí se explica la limitación en el idioma del lector.
>
> ⚠️ **Cuidado con las cifras de esta taxonomía: circulan dos unidades distintas** (medido el
> 2026-07-25, cierra un pendiente que venía de dos sesiones). El «9 + 2 `pending_items`» y el «34»
> de la enmienda cuentan **fichas de SDD**, y varias de esas fichas son *requisitos de entrada
> documentados que el motor nunca emite en runtime* —de la familia IFRS, por ejemplo, sólo IFRS-4 e
> IFRS-6 se emiten—. Lo que el motor **nombra** en `src/` son **24 códigos: 9 `FALTA-DATO` y 15
> `DATO-INSTITUCIONAL`**, y ése es el universo que miden el gate `tests/unit/test_public_copy.py` y
> la página [`docs_site/avisos-declarados.md`](docs_site/avisos-declarados.md). Las dos cifras son
> correctas en su propia unidad; compararlas entre sí no significa nada.
>
> **Copy público NO es sólo la landing y el README** (2026-07-25: creerlo dejó vivos dos defectos).
> Cuenta toda superficie que lea un humano: el **tooltip del formulario del UI instalable** —una
> `description` de Pydantic viaja a `schema.json` y de ahí al `FieldRenderer`—, el panel de
> resultados, la **prosa del informe** HTML/PDF/Word, `docs_site/` y la descripción de un dataset o
> preset que el backend devuelva. **No** cuentan: `warning_codes` y `card.falta_dato` (son el dato),
> las claves de los dicts de labels, los comentarios, los tests, `docs/design/` y el volcado de
> auditoría del anexo del informe —ahí el código es la evidencia y borrarlo falsearía el audit
> trail—. Dos gates lo vigilan: `web/src/lib/public-copy.test.ts` (todo `web/src`) y
> `tests/unit/test_public_copy.py` (`docs_site/` + el `README.md` + el espejo
> `web/src/lib/markers.ts`). **El `README.md` entró al gate el 2026-07-25** (decisión de Cami): los
> códigos salieron de la portada y su documentación vive en
> [`docs_site/avisos-declarados.md`](docs_site/avisos-declarados.md), la página de referencia del
> *output* del motor. Esa página es la **única** exención nueva, por la misma razón que el anexo del
> informe: ahí el código es el dato. Dos tests atan la página al motor en los dos sentidos —un código
> emitido sin documentar, y uno documentado que ya no existe—.
>
> **Contrato de resolución de parámetros (2026-07-25, APROBADO).** El requisito 3 de la visión
> —el dato se provee, se modela o sale del histórico— se diseñó como **contrato transversal**, no
> motor por motor: [`docs/design/_CONTRATO-RESOLUCION-PARAMETROS.md`](docs/design/_CONTRATO-RESOLUCION-PARAMETROS.md).
> El censo del código mostró que el problema no es que falten vías, sino que **cada parámetro ya tiene
> su política de resolución y se contradicen entre motores**. Siete decisiones (CRP-1…CRP-7); EAD entra
> al contrato distinguiendo **resolutor** de **consumidor**.
>
> **B3.a-1 CERRADO el 2026-07-25** (`main` = `1bbf737`, CI verde). Ojo: su premisa original era
> **falsa** y el censo lo demostró — el `Literal` de `governance/config.py:27` no era la llave de
> segmentación de ningún cálculo, y la llave real (`portfolio_col`) ya era `str` libre en los tres
> motores. El bloqueo verdadero era que **nadie declaraba el dominio de valores del segmento**.
> Se reformuló y se implementó como
> [`docs/design/_ENMIENDA-SEGMENTACION.md`](docs/design/_ENMIENDA-SEGMENTACION.md) (D-SEG-1…D-SEG-11,
> de las que **el código cita diez**: D-SEG-11 quedó *sin objeto* por ser consecuencia de D-SEG-1 —si
> el régimen es atributo del motor, no queda config donde omitirlo— y se conserva escrita para el día
> que exista un segundo motor. No la busques en `src/`: no es un olvido):
> esquema de segmentación declarado (normativo / institucional / derivado del dato), que **viaja en
> el resultado** de los tres motores, y régimen garantizado por un **registro régimen→motor con test
> de cobertura** —no por el sistema de tipos, que no puede: ampliar un `Literal` compila igual sin
> motor detrás—. El contrato de resolución de parámetros es el nodo en curso: su §2 quedó enmendado
> y sus dos primeros pasos (CRP-5 y CRP-6 bloque A) están implementados — ver `ROADMAP.md` §B3.
>
> **CRP-6 — bloque A implementado el 2026-07-26 (`368bcf5`, CI 16/16); el bloque B está PENDIENTE.**
> [`docs/design/_ENMIENDA-CRP6-FLAG.md`](docs/design/_ENMIENDA-CRP6-FLAG.md), D-CRP6-1…D-CRP6-8.
> `fail_on_falta_dato` significa **una sola cosa**: *¿una marca declarada **gobernable** emitida en
> la corrida la detiene?* Dos cosas que hay que saber antes de tocar esto:
>
> - **No toda marca declarada es gobernable.** Una marca es **estructural** si el motor la emite en
>   toda corrida por una capacidad diferida propia —`FALTA-DATO-IFRS-4` aparece **incluso con la EAD
>   entregada por la institución**, medido—. Las estructurales se registran siempre y **nunca**
>   detienen: abortar por ellas dejaría el motor inservible con su propio default. El criterio vive
>   en `core/markers.py::governable_warnings()` y **no se reimplementa con un `if` por motor**. Que
>   no detengan no las absuelve: su arreglo es ampliar la capacidad, y CRP-7 tiene asignada IFRS-4.
> - **El chequeo PIT de `ifrs9` es incondicional** y no lo apaga ningún flag. El contrato mandaba
>   *renombrar* ese flag; medido, su `False` no abría ruta degradada alguna —`_apply_vasicek` levanta
>   igual— y sólo movía la validación al medio del cálculo, que es lo que CRP-5 prohíbe.
>
> ⚠️ **CRP-6 cubre seis capas de siete: NO está cumplido.** El bloque B —`survival` implementa el
> flag, y el preset declara sus intervalos de confianza porque hoy **se contradice a sí mismo**
> (`fail_on_falta_dato=True` junto a la carencia `SUR-3`)— va con el P2, el bump de versión y **una
> sola** recaptura patrón C-D, porque los tres mueven `config_hash`.
>
> Lección de método que vale para todo ítem de roadmap: tres de los cuatro puntos que el plan daba
> por bloqueantes eran nomenclatura. **Medir contra el código antes de planificar.**
>
> **Catálogo de datos externos (2026-07-25, noche).** 42 datasets públicos documentados en
> [`docs/datasets/`](docs/datasets/); los datos viven en `data/externos/raw/` (vetado, **nunca** se
> commitea) y son **efímeros** —`./descargar.sh get` los repone—. ⚠️ **Leer el §0-bis del README
> antes de planificar sobre una fila del catálogo:** once de sus justificaciones prometen casos de
> prueba que ningún motor puede correr hoy, cada uno documentado con `archivo:línea`. Misma lección
> que B3.a-1, ahora aplicada a una fuente externa: **un relevamiento es hipótesis de alcance hasta
> que se mide contra el código.**
>
> **La landing tiene un rediseño evaluado y EN COLA** (`privado/diseno-landing-2026-07-25/`): cuatro
> piezas valen la pena, pero su banda de cifras publica «0 supuestos de país en el núcleo», que es
> **falso** —el censo del contrato encontró 15 puntos y B3.a-2 está diferido a propósito— junto con
> una cifra que se contradice con la propia página y una figura sin fixture detrás. No portarlo sin
> las correcciones de §2 de esa evaluación.
>
> **Auto-desarrollo: SOLO cuando Cami lo pida explícitamente** (skill `/auto-desarrollo-claude`). En trabajo normal, usar workflows y subagentes con normalidad, sin pedir permiso cada vez — ver `AGENTS.md` §Auto-desarrollo. La maquinaria tmux/Codex multi-motor está FROZEN (histórica).
