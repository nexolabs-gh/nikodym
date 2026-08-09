# AGENTS.md — contrato operativo de Nikodym RiskLib

> Fuente común y durable para Codex y Claude Code. Este archivo contiene reglas, no crónica.
> El estado reemplazable vive en `HANDOFF.md` —symlink interno no versionado públicamente—; la historia anterior se conserva
> íntegra en [`historial/`](historial/), fuera de las superficies documentales vigentes.

## Arranque obligatorio

Antes de planificar o editar, leer en este orden:

1. `AGENTS.md` — autoridad, límites y método.
2. `HANDOFF.md` — estado medido, abiertos y siguiente decisión humana. Es un symlink interno al
   repo privado, no un archivo del repositorio público; si no existe, detenerse y avisar.
3. [`docs/operacion/RUNBOOK-CODEX.md`](docs/operacion/RUNBOOK-CODEX.md) — comandos literales,
   gates y trampas del entorno.
4. [`docs/design/DECISIONES-VIGENTES.md`](docs/design/DECISIONES-VIGENTES.md) — registro canónico
   de decisiones aprobadas y correcciones que prevalecen.
5. Sólo entonces, los apartados pertinentes que enrute el registro —o, para descubrir un SDD no
   normalizado allí, el mapa completo [`docs/design/00-INDICE.md`](docs/design/00-INDICE.md)— de
   [`docs/ESPECIFICACIONES.md`](docs/ESPECIFICACIONES.md),
   [`docs/ROADMAP.md`](docs/ROADMAP.md) y los SDD enlazados por el registro.

No hace falta leer los corpus históricos para arrancar. Se consultan sólo para reconstruir por qué
se tomó una decisión o recuperar una trampa concreta.

## Autoridad de las fuentes

- Este archivo manda sobre el modo de trabajo y los límites permanentes.
- `HANDOFF.md` manda sobre el estado actual, los abiertos medidos y el próximo paso; nunca sobre
  contratos durables.
- `DECISIONES-VIGENTES.md` manda sobre el estado y la interpretación final de las familias que
  cataloga, y enruta a los demás contratos aprobados. Los SDD conservan el razonamiento completo,
  incluso propuestas luego sustituidas.
- El runbook manda sobre cómo ejecutar y cerrar en este checkout.
- Código, tests y artefactos ejecutados son la evidencia de qué está implementado. Un texto no
  sustituye una medición.
- `00-INDICE.md` es la puerta de descubrimiento exhaustiva del diseño, no autoridad de estado.
- `ROADMAP.md` conserva el plan de producto, pero no autoriza por sí solo a iniciar una capacidad.

Si dos fuentes discrepan, no elegir por intuición: reproducir, medir, dejar trazada la discrepancia
y elevar a Cami sólo la decisión que siga siendo humana.

## Proyecto y lenguaje

Nikodym es una librería Python open-source, Apache-2.0, de riesgo de crédito: PD —scorecards, ML y
survival—, LGD/EAD, validación, provisiones IFRS 9/ECL, forward-looking y stress testing, con
informe reproducible y lineage. Paquete: `nikodym`.

Todo el trabajo del proyecto —documentación, comentarios y comunicación— se hace en español; los
términos técnicos conservan su forma original.

La librería es el escaparate reputacional de Nikodym. La calidad verificable es requisito de
producto, no un extra.

## Contratos que no se reabren por iniciativa del agente

- La librería es 100 % gratuita y se publica completa. No existe tier cerrado ni se retiene una
  capacidad para venderla; la monetización vive en integración, personalización y consultoría.
- La normativa local está fuera de la propuesta de valor y del alcance general del paquete. El
  motor implementa estándares comunes; cada jurisdicción se aterriza encima.
- Chile/CMF Cap. B-1 es un caso de referencia implementado, congelado y visible como evidencia,
  nunca el titular. **No borrar el motor CMF ni sus tests.** CMF e IFRS 9 son motores distintos; la
  regla del máximo B-1 compara método estándar con método interno del banco, no CMF con IFRS 9.
- No proponer covariables WoE para LGD. El WoE supervisado contra incumplimiento no se reutiliza
  como covariable de severidad; la LGD modelada consume el frame crudo.
- El pipeline scorecard F1 es API estable bajo SemVer 1.x. Las superficies declaradas
  experimentales pueden crecer de forma aditiva, no mediante rupturas silenciosas.
- `FALTA-DATO` significa deuda del motor; `DATO-INSTITUCIONAL`, información que sólo la institución
  puede fijar. El motor no inventa ninguna. Los consumidores usan `is_declared_warning()`, no los
  literales. Los códigos internos no van al copy público.
- Copy público incluye README, `docs_site/`, landing, metadata PyPI/web, tooltips derivados de
  Pydantic, cards del backend, panel de resultados y prosa HTML/PDF/Word. Comentarios, SDD, códigos
  internos y anexos de auditoría no son copy público.
- Una capacidad que un usuario de `pip install` no puede alcanzar no está entregada, aunque tenga
  tests internos.
- Las decisiones D-JUR, D-MON, D-CAP, D-VER, D-AMB, D-LGD, D-SUB, D-EXI, D-FTE y D-VIS ya fueron
  aprobadas. No re-litigarlas; aplicar el registro canónico, incluido el abierto de completitud
  D-VIS-6.

## Método de trabajo

- **Medir antes de escribir.** Todo censo, relevamiento o recuerdo es hipótesis hasta medirlo contra
  el código, la salida o el servicio real.
- Una capacidad nueva o un cambio contractual requiere enmienda/SDD escrito, revisión independiente
  y aprobación explícita de Cami **antes de programar**. Usar
  [`docs/design/_PLANTILLA-SDD.md`](docs/design/_PLANTILLA-SDD.md).
- Trabajar por capas: diseñar → aprobar → implementar → ejecutar gates y controles → revisar
  adversarialmente → integrar. Reabrir el diseño por evidencia de código es válido.
- Un solo writer por checkout. Fan-out, subagentes y revisores adversariales son normales: decir qué
  se lanzó y por qué; no pedir permiso por cada lectura o revisión.
- El modo auto-desarrollo sólo se activa cuando Cami lo pide explícitamente. No confundirlo con usar
  subagentes en una sesión normal.
- Cada cierre ejecuta al menos un **control negativo** pertinente: inyectar el defecto que el gate
  promete detectar, observar rojo, revertir exactamente y observar verde. Un test que nace verde no
  prueba su oráculo.
- Verificar el artefacto final que consume la persona —bundle, HTML/PDF/Word, wheel, pantalla o
  servicio—, no sólo la función intermedia.
- La información externa y normativa exige doble verificación trazada contra fuentes oficiales;
  cuando el layout importe, verificar también el documento renderizado.
- Dar una recomendación ejecutiva, no un menú interminable. Corregir primero premisas falsas y dejar
  explícita toda incertidumbre restante.

## Qué puede hacer sin preguntar

Dentro de la tarea que Cami haya puesto en alcance, el agente puede:

- leer, medir, reproducir, usar subagentes, ejecutar gates y levantar servicios locales;
- editar e implementar lo ya autorizado por la tarea y por decisiones vigentes;
- crear controles negativos temporales y revertirlos con el protocolo del runbook;
- hacer commit y push directo a `main`, y dejar actuar el deploy automático tras CI verde;
- actualizar y pushear el repo privado en el mismo cierre.

Esa autorización no amplía el objetivo de la sesión ni permite tomar decisiones de producto nuevas.

## Qué exige un OK nuevo de Cami

- Aprobar una enmienda/SDD o cambiar un contrato, una metodología o el alcance de producto.
- Publicar cada release/tag en PyPI. Un OK anterior no se hereda a la release siguiente.
- Recapturar o regenerar la demo/fixtures de demostración. El deploy automático de artefactos ya
  versionados no cuenta como recaptura.
- Borrar o reemplazar evidencia material, datos, una capacidad o una historia no recuperable.
- Resolver una elección de producto todavía abierta, como el rótulo/banda del PSI señalado en el
  `HANDOFF`.

## Prohibiciones explícitas

- No publicar en PyPI sin el OK específico de esa release.
- No recapturar la demo sin preguntar.
- No borrar CMF, sus pruebas ni su evidencia; no volver a vender normativa local como promesa.
- No proponer covariables WoE para LGD.
- No re-litigar decisiones aprobadas ni convertir un SDD histórico en cola de trabajo.
- No programar un cambio contractual antes de su enmienda aprobada.
- No declarar cerrado un censo sin medir completitud y criterio en ambos sentidos.
- No introducir datos de clientes, credenciales ni detalle institucional en el repo público.

## Git, privacidad y cierre

- Repo público: `nexolabs-gh/nikodym`, rama `main`. Todo commit es visible.
- `privado/` es otro repo Git, privado, con remoto propio. Nunca añadirlo al índice público. El
  `HANDOFF.md` de la raíz apunta a `privado/HANDOFF.md` y está ignorado en el público.
- Antes de un push, cambiar `gh` a la cuenta `nexolabs-gh` como indica el runbook. Verificar ambos
  worktrees y ambos remotos después.
- `.gitignore` es una barrera de seguridad: no flexibilizarla sin prueba positiva y negativa.
- En cada cierre: actualizar `privado/HANDOFF.md` con mediciones actuales, liberar procesos y
  artefactos temporales, ejecutar los gates proporcionales al riesgo, commit/push de público y
  privado y verificar CI job a job cuando corresponda.
- Si el cierre no cabe en una página de estado, mover el detalle durable al runbook, al registro o
  a un documento histórico; no volver a convertir `AGENTS.md` en diario.

## Memoria histórica condicionada

Antes de proponer mejoras de forward-looking, stress, validación, PDI, forecast de cartera,
conectores o Risk Leap, leer —si está disponible—
`privado/REVISION-HISTORICA-IDEAS-NIKODYM-2026-07-18.md`. Es inspiración y fuente de tests
adversariales, no metodología aprobada ni fuente normativa; respetar IHN-001…IHN-011.
