# Enmienda propuesta — congelación continua del material de ejecución candidato

> **Estado: APROBADA (0-a) el 2026-08-22 por Cami. Implementación por capas en curso — ver
> Anexo A.** Octava redacción. Cinco revisiones
> adversariales independientes, **cinco NO SHIP**. Las redacciones 1–3 acumularon dieciséis
> hallazgos; la sexta midió cuatro casillas abiertas y la cuarta revisión devolvió seis hallazgos
> más; la séptima los incorporó y la **quinta revisión** —la segunda que cubrió §0— devolvió
> **cuatro hallazgos más**, todos **verificados por medición contra el árbol vivo**.
>
> **La medición de esta ronda invirtió la recomendación.** La sexta y séptima redacción afirmaban
> que cerrar la vía de inyección en memoria (**0-b**) costaba «dos ACE en la creación» y lo
> recomendaban. Medido, es **falso**: 0-b es un **rediseño de seguridad de proceso**, no un añadido
> al lease. Por eso esta redacción **recomienda 0-a** —acotar la promesa a la consistencia del
> material **en disco**, con los procesos Medium del mismo usuario dentro del TCB— y **difiere 0-b a
> un blocker propio**. La decisión de fondo la tomó Cami el 2026-08-22 tras leer esta medición:
> corregir a 0-a y cerrar.
>
> Los cuatro hallazgos de la quinta revisión, verificados:
>
> - **F1 — carrera de handles.** Endurecer un descendiente **después** de su evento de depuración
>   deja una ventana en la que un tercero Medium abre el objeto y **cachea el handle**; endurecer no
>   revoca derechos ya concedidos. Medido: un handle abierto antes del endurecimiento **inyecta 29
>   bytes después**, aunque un open nuevo ya dé `DENEGADO(5)`. El «endurecimiento por tipo» que
>   proponía la séptima redacción (D-LEA-20) **no cierra el canal de descendientes**; se retira como
>   suficiente.
> - **F2 — el supervisor es la puerta trasera.** `SandboxProcess` retiene el handle de acceso total
>   del creador y el proceso supervisor no se endurece. Un tercero que inyecte el supervisor o use
>   `PROCESS_DUP_HANDLE` sobre él elude **todas** las DACL del candidato. Denegar
> `PROCESS_DUP_HANDLE`
>   sobre el candidato no cierra este canal.
> - **F3 — el TCB del código no puede ser vacío.** Meter «todo el código del candidato» en el TCB no
>   vuelve confiables los bytes plantados que el bypass nativo de §3.8 permite ejecutar. Bajo 0-b la
>   afirmación quedaba vacía; bajo 0-a es coherente, porque el candidato y el mismo usuario **son**
>   el TCB por decisión declarada.
> - **F4 — el texto de OK admitía ramas contradictorias.** Corregido en §10.
>
> Afirmaciones **retiradas por falsas contra el árbol vivo** a lo largo de las redacciones: la
> máscara de supervisor de §0.2 (cuarta revisión), el censo del canal Python de §3.3 —donde
> **todos** los censos previos, incluido el de la revisión, fueron inexactos—, el `TokenDefaultDacl`
> de §0.6, la prevención por parcheo de §3.7, y ahora **la recomendación de 0-b y la suficiencia de
> D-LEA-20** (quinta revisión).
>
> Cierra por diseño la frontera `candidate_execution_material_lease_unimplemented` catalogada en
> [`_PROPUESTA-CALIBRACION-H9R-PRE-START.md`](_PROPUESTA-CALIBRACION-H9R-PRE-START.md) §12.1. Este
> texto **no autoriza** START, S0, S1, S2, workloads, entrypoints calificables, fingerprint humana,
> fixtures definitivos ni valores finales. No toca hardware/cloud, metodología, API pública, PyPI ni
> la demo.
>
> El OK del 2026-08-13 autorizó implementar, probar y revisar **el arnés**. Lo que aquí se propone
> excede ese OK en cuatro puntos que por eso vuelven a Cami: el arnés pasaría a **retener handles
> del
> kernel** —y, en una variante, a **modificar descriptores de seguridad**— sobre rutas propiedad del
> operador y fuera del workdir; **crearía el candidato bajo un depurador**; el manifiesto candidato
> **ganaría declaraciones obligatorias nuevas**; y la publicación de evidencia **cambiaría de un
> paso
> a tres**. El código vigente rechaza hoy la primera frontera de forma explícita:
> `_seal_windows_snapshot_directories` sella «sólo dirs harness-owned; nunca el checkout vivo ni
> telemetría».
>
> Decisiones propuestas: **D-LEA-0** y **D-LEA-1…D-LEA-22**, más **D-LEA-12b**, **D-LEA-17b** y
> **D-LEA-17c**. Enmienda a
> [`_PROPUESTA-CALIBRACION-H9R-PRE-START.md`](_PROPUESTA-CALIBRACION-H9R-PRE-START.md) §12 y §12.1;
> no modifica D-RDY-ABA ni D-RDY-H9R.

## Registro de aprobación — 2026-08-22

Cami firmó el **texto de §10.2 en el escenario recomendado 0-a**. Configuración exacta aceptada
(las ramas quedaron en la recomendación de cada apartado; ninguna se desvió):

| Apartado | Elección firmada |
|---|---|
| §7.0 — modelo de amenaza (D-LEA-0) | **0-a** (mismo usuario Medium dentro del TCB; consistencia del material **en disco**) |
| §7.6 — camino | **aprobar ahora** |
| §7.1 — frontera del mecanismo | **A** (lease puro en sitio; se **mantiene** D-LEA-9) |
| §7.2 — clausura del intérprete | **incluir ahora** (se aprueba D-LEA-13) |
| §7.7 — precio del intento | **asumir el coste** (+136,4 %) |
| §7.5 — runtime del arnés | **sí** (se abre `trusted_harness_interpreter_closure_undeclared` como blocker propio) |
| §7.3 — evidencias de campaña | **sí**, fijada por §4.1 |

**Decisiones D-LEA aprobadas:** D-LEA-0 (fijada en 0-a), D-LEA-1…D-LEA-8, **D-LEA-9** (por variante
A), D-LEA-10, D-LEA-11, D-LEA-12, **D-LEA-12b**, **D-LEA-13** (por «incluir ahora»), D-LEA-14…D-LEA-19,
D-LEA-21, D-LEA-22, con **D-LEA-17b** y **D-LEA-17c**. **D-LEA-20 NO se aprueba**: la inyección en
memoria (0-b) se **difiere** al blocker propio `candidate_process_memory_isolation_unimplemented`.

**Qué NO autoriza esta firma** (repetido del texto de §10.2): START, S0, S1, S2, workloads,
entrypoints calificables, fingerprint humana, fixtures definitivos, valores finales, hardware/cloud,
metodología, API, PyPI, tags, releases ni recaptura de demo.

**Efecto sobre la puerta global (D-LEA-19), diferido a la integración.** Aprobar registra la
**decisión**, no un estado de código. El retiro de `candidate_execution_material_lease_unimplemented`
y la apertura de `candidate_process_memory_isolation_unimplemented` ocurren **cuando el mecanismo esté
implementado y con sus controles negativos verdes**, no al firmar: hasta entonces el catálogo sigue
declarando el blocker de lease, que es lo honesto. La reescritura de la línea de §12.1 de
[`_PROPUESTA-CALIBRACION-H9R-PRE-START.md`](_PROPUESTA-CALIBRACION-H9R-PRE-START.md) también acompaña
a la integración (capa 4 del Anexo A), no a la firma.

## TL;DR y recomendación ejecutiva

Hoy el arnés **verifica** el material candidato por hash y lo vuelve a verificar justo antes de
START, pero **no lo congela**. Entre la última verificación y el momento en que el candidato lee o
ejecuta esos bytes hay una ventana en la que cualquier proceso del mismo usuario puede sustituirlos
en sitio: medido, sobrescribir un archivo ya censado es **PERMITIDO** aun con el directorio padre
sellado, y el SHA cambia. La evidencia firmada atestiguaría un digest que ya no describe los bytes
ejecutados.

Congelar exige **tres piezas**, no una. La primera redacción proponía sólo la primera y por eso fue
rechazada:

1. **Anti-sustitución — `windows_share_mode_lease_v1`.** Un handle del kernel por archivo, sin
   seguir reparse points y con `FILE_SHARE_READ` como único modo compartido.
2. **Anti-inyección — dos gates causales, uno por canal.** El lease impide cambiar lo que existe,
   **no** impide **añadir**, y un plantado **transitorio** deja el censo final limpio. Son dos
   canales distintos: el del cargador de Windows (D-LEA-12) y el del import machinery de Python
   (D-LEA-12b).
3. **Anti-falso-éxito — provisional, release, promoción.** El código vivo publica `attempt.json` y
   **después** lo revalida contra artefactos vivos.

**Estado de los mecanismos, tras dos rondas de medición y cinco revisiones adversariales:**

| Mecanismo | Estado medido | Bajo 0-a | Dónde |
|---|---|---|---|
| **Pieza 1 — lease anti-sustitución** | acreditado; bloquea escritura, borrado, renombre, reemplazo | **recomendado** | §2 |
| **Pieza 2 — gate de imágenes (D-LEA-12)** | acreditado; el evento llega antes de `DllMain` y del callback TLS; se previene **terminando el proceso**, no parcheando | **recomendado** | §3.6, §3.7 |
| **Pieza 2 — gate del canal Python (D-LEA-12b)** | causal en los cuatro vectores; con un bypass nativo declarado que ninguna pieza cubre | **recomendado** | §3.8 |
| **Pieza 3 — máquina de estados de publicación** | acreditada por lectura del código vivo | **recomendado** | §3.1, D-LEA-16…18 |
| **0-b — cierre de la inyección en memoria** | **rediseño**: el endurecimiento posterior tiene una **carrera** (F1) y el **supervisor** queda como puerta trasera (F2) | **diferido a blocker propio** | §0.6, §0.7 |

**El precio de la pieza 2 está medido:** las dos partes, juntas, sobre la misma carga real, cuestan
**+136,4 %** del tiempo interno del candidato (1,901 s → 4,494 s). Por separado, +51,6 % y +57,1 %.
No falsea la calibración si el mismo gate está puesto en todos los intentos comparados, pero la
alarga. Ver §7.7.

**Recomendación: aprobar la variante A de §7.1 con 0-a de §7.0 y las piezas 1, 2 y 3.** Eso cierra
la sustitución de material **en disco** y el plantado transitorio, que era el núcleo de la frontera.
**0-b se difiere**: cerrarlo de verdad exige seguridad de objeto en la creación (un broker que fije
descriptores antes de publicar PID/TID, no un endurecimiento posterior), endurecer el propio
supervisor, y mediar las lecturas nativas — un rediseño de seguridad de proceso que merece enmienda
propia, no un apéndice de ésta. El texto de OK de §10 está escrito **por ramas** y ya no admite
combinaciones contradictorias.

Hay además cuatro hallazgos que Cami decide aparte: el manifiesto candidato **no identifica hoy el
intérprete que realmente corre** (§4.2); el runtime del propio arnés tiene la misma brecha en la
otra mitad del sistema (§4.3); `importlib.metadata.version()` **devuelve `None` en silencio** en vez
de propagar un fallo de lectura (§3.9); y el supervisor conserva handles de acceso total al
candidato sin endurecerse (§0.7), que es el mismo hallazgo que empuja 0-b al rediseño.

## 0. Modelo de amenaza — medido, no supuesto

Las tres primeras redacciones prometían que **«nadie»** pudiera sustituir el material. Una revisión
adversarial objetó, **por inferencia**, que un proceso Medium del mismo usuario puede inyectar
código
en la memoria del candidato sin tocar archivos. Se midió, se midió si esa vía puede cerrarse, y en
esta sexta redacción se midió además **la composición completa con el lanzador vivo**.

### 0.1 La vía existe: está medida, no inferida

El arnés crea el candidato con un duplicado del token del propio proceso al que sólo le baja la
etiqueta de integridad, y `CreateProcessAsUserW` recibe descriptores de seguridad **nulos** para
proceso e hilo —`windows_sandbox.py:730-744`, ambos argumentos literalmente `None`—, de modo que el
objeto proceso hereda la DACL por defecto del token. La integridad obligatoria es `NO_WRITE_UP`:
protege a Medium **de** Low, no al revés.

Medido sobre un hijo creado exactamente como hoy, y **completando la inyección, no sólo abriendo el
handle**:

| Operación desde un proceso Medium del mismo usuario | Resultado |
|---|---|
| `OpenProcess(VM_WRITE\|VM_OPERATION\|CREATE_THREAD\|VM_READ)` | **PERMITIDO** |
| `VirtualAllocEx` | **OK** |
| `WriteProcessMemory` | **OK, 26 bytes** |
| `ReadProcessMemory` de vuelta | **OK**, devuelve `'NIKODYM-INYECCION-EFECTIVA'` |
| `OpenThread(SUSPEND\|GET_CONTEXT\|SET_CONTEXT)` + `SuspendThread` + `SetThreadContext` | **OK** |
| `WRITE_DAC` | **PERMITIDO** |

Los bytes ajenos quedaron **presentes y releídos** en el espacio del candidato. En la quinta
redacción esta fila era sólo un `OpenProcess` exitoso; ahora la primitiva está ejercida entera. Nada
de esto produce `LOAD_DLL_DEBUG_EVENT`, pasa por el import machinery ni toca un archivo: ninguna de
las tres piezas lo vería.

### 0.2 La vía se puede cerrar sin administrador

| Escenario | Inyección real | `WRITE_DAC` | `WRITE_OWNER` | El dueño recupera |
|---|---|---|---|---|
| descriptor nulo, como hoy | **PERMITIDA** | PERMITIDO | — | — |
| DACL restrictiva **sin** `OWNER RIGHTS` | DENEGADA (5) | **PERMITIDO** | DENEGADO (5) | **sí**: reescribe la DACL con `status=0` y la inyección vuelve a estar **PERMITIDA** |
| DACL restrictiva **+ `OWNER RIGHTS` (S-1-3-4)** | **DENEGADA (5)** | **DENEGADO (5)** | **DENEGADO (5)** | **no** |

Una DACL restrictiva **sola es inútil**: el dueño conserva `WRITE_DAC` por derechos implícitos de
propietario y recupera la inyección. `OWNER RIGHTS` cierra esa vuelta. Esa parte de la quinta
redacción **queda confirmada**, y se confirmó también desde **otro proceso Medium** distinto del
creador, no sólo desde el creador.

### 0.3 Lo que la quinta redacción dejaba sin medir

Eran cuatro puntos. Tres se miden en §0.5; el cuarto —un atacante con `SeDebugPrivilege`— exige
elevación y queda **fuera** del modelo de un mismo usuario no elevado, por decisión declarada, no
por falta de medición.

### 0.4 Corrección: la máscara que §0.2 daba por buena **rompe el arnés**

La quinta redacción afirmaba que el supervisor conserva sus derechos con la máscara
`TERMINATE | SET_QUOTA | QUERY_INFORMATION | VM_READ | SYNCHRONIZE | READ_CONTROL` (`0x120511`).
**Es falso contra el árbol vivo**, y se retira.

La causa es que el arnés **no pide `PROCESS_QUERY_INFORMATION`**: pide
`PROCESS_QUERY_LIMITED_INFORMATION`, que es **otro bit**. El control de acceso de Windows es una
prueba de máscara de bits pura: conceder `0x0400` no concede `0x1000`. Medido con esa máscara exacta
sobre el lanzador vivo:

| Paso real del arnés | Con la máscara de §0.2 |
|---|---|
| `process_integrity_level` — `OpenProcess(QLI)` + `OpenProcessToken` | **FALLO, winerror 5** |
| `assign_to_job` — `OpenProcess(QLI\|SET_QUOTA\|TERMINATE)` | **FALLO(5)** |
| `process_metrics` — `OpenProcess(QLI)` | **FALLO(5)** |

Con esa DACL el candidato **nunca habría llegado al Job**.

### 0.5 La máscara real, medida del código vivo, y la composición completa

La máscara se deriva de los cinco únicos puntos en que el arnés **reabre por PID/TID** —lo demás usa
los handles de acceso total que `CreateProcessAsUserW` devuelve al creador, que la DACL no
gobierna—:

| Sitio en el árbol vivo | Derecho pedido |
|---|---|
| `windows_sandbox.py:380` `process_integrity_level` | `PROCESS_QUERY_LIMITED_INFORMATION` (`0x1000`) |
| `windows_job.py:531-536` asignación al Job | `QLI \| PROCESS_SET_QUOTA \| PROCESS_TERMINATE` (`0x1101`) |
| `windows_job.py:856-861` Job del cliente externo | idem |
| `windows_job.py:1435` `resume_suspended_process` | **hilo**: `THREAD_SUSPEND_RESUME` (`0x0002`) |
| `windows_job.py:1336` `thread_affinities` | **hilo**: `THREAD_QUERY_LIMITED_INFORMATION` (`0x0800`) |

`PROCESS_SET_INFORMATION` aparece en `windows_job.py:341-344`, pero medido: su único llamador con
`write_affinity=True` es `open_process(os.getpid())` —el PID **del propio arnés**—, así que **no**
hace falta sobre el candidato. Y `PROCESS_DUP_HANDLE`, que §0.3 preguntaba si faltaba, **no hace
falta**: denegado, los seis pasos del arnés siguen verdes.

Composición medida, con el token Low, el arranque suspendido, la asignación al Job y la máscara real
`0x1101` + `OWNER RIGHTS`:

| Paso del arnés | Resultado | | Atacante Medium | Resultado |
|---|---|---|---|---|
| `process_integrity_level` | **S-1-16-4096** | | inyección completa | **DENEGADA (5)** |
| `assign_to_job` (`KILL_ON_JOB_CLOSE`) | **OK** | | `WRITE_DAC` / `WRITE_OWNER` | **DENEGADOS (5)** |
| `IsProcessInJob` | **true** | | `PROCESS_VM_READ` | **DENEGADO (5)** |
| `resume` por `OpenThread` | **OK** | | `PROCESS_QUERY_INFORMATION` | **DENEGADO (5)** |
| `thread_affinities` | **OK** | | `PROCESS_DUP_HANDLE` | **DENEGADO (5)** |
| `process_metrics` | **OK** | | reescritura de la DACL | **imposible** |

La máscara real no sólo funciona: es **estrictamente más cerrada** que la que la quinta redacción
proponía, porque además deniega `VM_READ` y `QUERY_INFORMATION`.

**Carga real bajo esa DACL**: un candidato que importa `numpy`, `pandas`, `pyarrow`,
`pyarrow.parquet` y `sklearn` y materializa una tabla de 50.000 filas termina con `exit_code=0` e
idéntico resultado, en 2,02 s frente a 2,40 s del brazo con descriptores nulos. Es una medición
única
por celda y la diferencia está dentro del ruido: **no se afirma que la DACL sea más rápida**, sólo
que no rompe nada observable.

### 0.6 El canal del **hilo** y el de los **descendientes**

Cerrar el objeto proceso **no cierra los hilos**, y cerrar la raíz **no cierra el árbol**. Medido:

| Configuración | Hilo **primario** de la raíz | Hilos creados **después** | **Procesos descendientes** |
|---|---|---|---|
| descriptores nulos | `SetThreadContext` **OK** | `SetThreadContext` **OK** | todo **OK** |
| DACL de proceso, sin descriptor de hilo | `SetThreadContext` **OK** | `SetThreadContext` **OK** | todo **OK** |
| + descriptor de hilo (`lpThreadAttributes`) | **DENEGADO (5)** | `SetThreadContext` **OK** | todo **OK** |

`lpThreadAttributes` gobierna **sólo el hilo primario**; los hilos posteriores toman la DACL por
defecto **del token**. Y el árbol candidato **no es un proceso**: medido, la raíz engendra **tres**
descendientes —el lanzador de la venv, el intérprete real y el nieto del workload—, ninguno de los
cuales recibe `lpProcessAttributes`.

> **Corrección de la sexta redacción, forzada por la cuarta revisión adversarial.** Esa redacción
> proponía cerrar el canal fijando `TokenDefaultDacl` sobre el token Low. **Es un error y se
> retira.** `TokenDefaultDacl` es una máscara **única** aplicada a objetos de tipos distintos, y los
> bits significan cosas distintas en cada tipo. Medido con `0x80A`, que era la propuesta:
>
> | | Raíz (descriptor explícito) | Los **tres** descendientes |
> |---|---|---|
> | `process_metrics` → `OpenProcess(QLI)` | **OK** | **FALLO (5)** |
> | `assign_to_job` | **OK** | **FALLO (5)** |
> | atacante: `PROCESS_SUSPEND_RESUME` / `VM_OPERATION` / `CREATE_THREAD` | DENEGADOS | **PERMITIDOS** |
>
> Sobre un objeto proceso, `0x80A` significa `PROCESS_SUSPEND_RESUME | PROCESS_VM_OPERATION |
> PROCESS_CREATE_THREAD` y **omite** `PROCESS_QUERY_LIMITED_INFORMATION`. `process_tree_snapshot`
> reabre **cada** PID del Job con `0x1000`, de modo que la propuesta **habría roto la telemetría
> multiproceso del arnés** y, a la vez, habría regalado al atacante la suspensión de los procesos
> que el arnés mide. La medición de la sexta redacción no lo vio porque sólo abrió el PID de la
> raíz, que sí lleva descriptor explícito.

**El endurecimiento posterior parecía funcionar, pero tiene una carrera —hallazgo F1 de la quinta
revisión, verificado—.** La séptima redacción endurecía cada objeto **por su tipo** desde el canal
de depuración: en `CREATE_PROCESS_DEBUG_EVENT`/`CREATE_THREAD_DEBUG_EVENT` el objeto ya existe y
está congelado, y reabriendo por PID/TID con `WRITE_DAC` —los handles del evento conceden
`0x12367B`/`0x121C7B` **sin `WRITE_DAC`**, medido con `NtQueryObject`, así que la vía obvia falla
14/14— el arnés conserva `QLI` y `assign` sobre todo el árbol y el atacante pierde inyección y
secuestro (17/17). Contra un atacante que abre **después**, funciona.

**Pero el candidato depurado está congelado; el atacante no.** Entre el instante en que el objeto
del
descendiente existe —creado con DACL por defecto, abierto por PID— y el instante en que el gate le
cambia la DACL, un tercero Medium puede abrirlo y **retener el handle**. El acceso de un handle se
captura en el `OpenProcess`; cambiar la DACL después **no lo revoca**. Medido directamente:

| Secuencia | Resultado |
|---|---|
| el atacante abre con derechos de inyección **antes** del endurecimiento | **OK** |
| el gate endurece la DACL (reabriendo con `WRITE_DAC`) | **OK** |
| un `OpenProcess` **nuevo** con derechos de inyección | **DENEGADO (5)** |
| el handle **cacheado** escribe en la memoria del candidato | **SÍ — 29 bytes escritos** |

El endurecimiento posterior cierra la puerta a quien llega tarde y la deja abierta a quien ya
entró. Como el descendiente se crea con DACL por defecto y su PID es enumerable en cuanto existe,
la ventana es **real y no se cierra endureciendo después**. Por eso **D-LEA-20 se retira como
mecanismo suficiente**: cerrar el canal de descendientes exige **seguridad de objeto en la
creación** —que cada proceso e hilo nazca con la DACL restrictiva, no que se le aplique después—, y
eso, para procesos que el propio candidato engendra, requiere un **broker de creación** que
interponga el descriptor antes de publicar el PID. Es un rediseño, no un apéndice.

### 0.7 El supervisor es la puerta trasera —hallazgo F2, verificado—

Aunque se cerraran la carrera y todos los canales del candidato, quedaría el **supervisor**. Leído
en el árbol vivo: `SandboxProcess` (`windows_sandbox.py:535-547`) retiene el handle de **acceso
total** que `CreateProcessAsUserW` devuelve al creador, y bajo D-LEA-12 el depurador retiene además
handles de proceso e hilo por cada PID del árbol. El proceso **supervisor** no se endurece.

El SID del supervisor y el del atacante son **el mismo usuario**, así que un tercero Medium puede
**inyectar el supervisor** —cuya DACL por defecto está abierta, medido en §0.1— o abrirlo con
`PROCESS_DUP_HANDLE` y **duplicar** sus handles de acceso total al candidato. La DACL del candidato
**no se reevalúa** al duplicar un handle ya concedido. Denegar `PROCESS_DUP_HANDLE` sobre el
candidato no cierra este canal, porque el handle vulnerable lo tiene el supervisor, no el candidato.

Cerrar esto exige endurecer también el objeto proceso del supervisor —crearlo desde un launcher
confiable con DACL restrictiva y `OWNER RIGHTS`—, o declarar expresamente al mismo usuario **dentro
del TCB**, que es justo lo que hace 0-a. Es la misma brecha que §4.3 en la otra mitad del sistema.

**Y aun cerrando todo eso, 0-b no promete integridad del entorno medido.** Como el supervisor
necesita `PROCESS_TERMINATE` y `PROCESS_SET_QUOTA`, cualquier proceso del mismo usuario los
conserva: medido, un tercero puede **matar** el candidato o **asignarlo a un Job anidado con límite
de 64 MB** y `SetProcessWorkingSetSize`, alterando los caps de memoria y tiempo que el arnés
calibra sin tocar un byte del material. 0-b cerraría la integridad del código ejecutado, **no** la
del entorno medido.

### 0.8 La decisión, con el precio de 0-b ya medido

**D-LEA-0 (propuesta, dos variantes).**

- **0-a — acotar la promesa (recomendada).** Los procesos Medium del mismo usuario quedan dentro del
  TCB y la frontera promete consistencia del material **en disco**: nadie puede sustituir, borrar,
  renombrar ni reemplazar los bytes, ni añadir material ejecutable que la evidencia no atestigüe.
  Cierra con las piezas 1, 2 y 3, sin tocar la creación del proceso. La línea de §12.1 se reescribe
  para que prometa consistencia en disco, no «nadie».
- **0-b — cerrar también la vía de memoria (diferida a blocker propio).** Medido, no es «dos ACE en
  la creación»: exige seguridad de objeto **en la creación** de cada descendiente —un broker, porque
  el endurecimiento posterior tiene la carrera de §0.6—, **endurecer el supervisor** (§0.7), y aun
  así deja fuera el bypass nativo (§3.8) y la integridad del entorno medido. Es un rediseño de
  seguridad de proceso que merece su propia enmienda: se propone abrir
  `candidate_process_memory_isolation_unimplemented` y no cargarlo sobre esta frontera.

Recomendación: **0-a**. La sexta redacción invirtió la recomendación hacia 0-b porque parecía
barato;
las mediciones de la quinta revisión —la carrera de handles y la puerta trasera del supervisor—
muestran que no lo es. Acotar la promesa deja fuera un vector real, pero lo deja **declarado y con
blocker propio**, que es honesto; fingir que 0-b está cerrado con un endurecimiento que tiene una
carrera medida no lo sería.

## 1. Qué está medido y qué falta

### 1.1 Lo que el arnés ya hace

`run_preflight` valida el manifiesto candidato, prueba el runtime aislado con `-I -B -S` y hashea
ejecutable, entorno, wheel, sdist, lock y el árbol instalado completo. `_revalidate_preflight`
repite ese trabajo inmediatamente antes de START.

Es verificación **discreta**: dos fotos, sin nada que impida el cambio entre ellas ni después de la
segunda.

### 1.2 La ventana que queda abierta

1. **Entre la revalidación y el uso.** Tras el último rehash el supervisor todavía construye
   requests, reserva puerto, consume autorización y lanza el proceso.
2. **Durante el uso.** El candidato importa de forma perezosa: un módulo del árbol instalado que se
   importe tarde puede haber sido sustituido después del rehash.
3. **El árbol instalado se rehashea una sola vez**, y un rehash no impide la sustitución: la
   constata
   más tarde, y sólo si el sustituto sigue allí.

## 2. Semántica medida de la pieza 1

Medido en la torre writer (Windows 11 Pro 10.0.26200, Python 3.12.10 de `.venv`), sobre archivos
sintéticos bajo `%TEMP%\nkr`, una copia de `cmd.exe` y árboles reales de esta máquina. Ninguna
medición ejecutó START, workloads ni entrypoints calificables.

### 2.1 Lease por archivo — `CreateFileW(GENERIC_READ, FILE_SHARE_READ, OPEN_EXISTING, FILE_FLAG_OPEN_REPARSE_POINT)`

| Operación de un tercero mientras el lease está vivo | Resultado medido |
|---|---|
| abrir para escritura, `share=0` | **bloqueado**, `winerror=32` |
| abrir para escritura, `share=READ\|WRITE\|DELETE` | **bloqueado**, `winerror=32` |
| abrir para escritura **por un hardlink alterno** del mismo objeto | **bloqueado**, `winerror=32` |
| obtener handle de escritura para *memory mapping* | **bloqueado**, `winerror=32` |
| borrar | **bloqueado**, `winerror=32` |
| renombrar | **bloqueado**, `winerror=32` |
| `os.replace` / `MoveFileExW(..., REPLACE_EXISTING)` | **bloqueado**, `winerror=5` |
| leer desde el mismo proceso y desde otro proceso | permitido, SHA-256 idéntico |
| **crear un stream alterno (ADS) del archivo leaseado** | **PERMITIDO**; el stream por defecto no cambia |

Vacuidad comprobada: cerrado el lease, la apertura para escritura devuelve `OK`, el reemplazo
devuelve `OK` y el SHA-256 **cambia**. El bloqueo lo produce el lease, no el entorno.

El share mode se evalúa sobre el **objeto**, no sobre el nombre: por eso un hardlink alterno no
elude
el lease. Se evalúa, en cambio, **por stream**: el lease del stream por defecto no impide crear un
ADS. El censo actual **no enumera streams**, y ésa es una brecha de cobertura real (D-LEA-14).

### 2.2 El lease no estorba a la ejecución ni al import

| Prueba | Resultado medido |
|---|---|
| copia de `cmd.exe` sin lease, `/c exit 7` | `returncode=7` |
| misma copia **con lease vivo sobre el ejecutable** | `returncode=7` |
| adquirir el lease con un hijo del ejecutable **ya corriendo** | `OK` |
| lanzar `.venv\Scripts\python.exe` con lease sobre el propio ejecutable | `returncode=0` |
| `import pyarrow` con los 771 archivos de `pyarrow` leaseados | `returncode=0`, versión `24.0.0` |
| `import pyarrow, pandas` con los **46.316** archivos de `site-packages` leaseados | `returncode=0` |

Era el riesgo técnico que podía invalidar el mecanismo entero: **no se materializa**.

### 2.3 Falla cerrado en la adquisición

Con un escritor vivo sobre el archivo, adquirir el lease devuelve `winerror=32`; cerrado el
escritor,
`OK`. Si el material no puede congelarse, el arnés lo sabe **antes** de START.

`st_ino`/`st_dev` están disponibles en esta torre y reconcilian antes y después del `CreateFileW`,
que es el patrón que ya usa `_same_file_version`.

### 2.4 Sello DACL de directorio — qué sí y qué no

Denegar `FILE_ADD_FILE | FILE_ADD_SUBDIRECTORY | FILE_DELETE_CHILD` al SID del usuario sobre el
directorio padre, con un hijo fresco por verbo:

| Operación sobre un hijo ya existente | Resultado medido |
|---|---|
| crear archivo nuevo | **bloqueado** (`PermissionError`, `errno=13`) |
| crear subdirectorio | **bloqueado**, `winerror=5` |
| renombrar un hijo | **bloqueado**, `winerror=5` |
| **borrar un hijo existente** | **PERMITIDO** |
| **sobrescribir el contenido de un hijo en sitio** | **PERMITIDO**, y el SHA-256 cambia |
| **truncar un hijo existente** | **PERMITIDO** |

**El sello del directorio no protege el contenido de sus hijos.** Sello y lease no son alternativas:
el sello cubre altas y renombres; el lease por archivo es lo único que cubre sustitución de bytes,
borrado y reemplazo.

Un handle de directorio con `FILE_SHARE_READ` sí bloquea renombrar (`winerror=32`) y borrar
(`winerror=32`) el **propio directorio**, que es el vector de interposición por junction. Un handle
de directorio **no** impide crear un hijo nuevo: medido **PERMITIDO**.

### 2.5 Alternativa descartada: ACE de denegación por archivo

Se descarta por dos razones medidas:

- **persistencia.** Un handle desaparece cuando el proceso muere; un ACE, no. Un `Stop-Process` del
  supervisor dejaría el árbol del operador con una DACL hostil que él no puso.
- **restauración.** Restaurar la DACL original con `SetKernelObjectSecurity` **no** resultó
  byte-exacto en esta torre: hace falta la rama de auto-herencia (`SE_DACL_AUTO_INHERITED` →
  `SetSecurityInfo`) que `runtime_snapshot.py` ya implementa.

En ese experimento las filas de borrado y renombre quedaron **confundidas** —el handle que sostenía
la DACL no compartía `FILE_SHARE_DELETE`—. La única fila limpia es la de apertura para escritura, y
ninguna decisión se apoya en las dos confundidas.

### 2.6 Coste — contrafactual en el orden obligatorio, sobre mitades gemelas

Dos afirmaciones previas se **retiran** por medir el orden equivocado: «+2,6 s / ~8 %» y «+2,2 %».
Ambas venían de `hash → lease`, mientras que D-LEA-8 obliga `lease → hash`.

Diseño: un árbol frío se parte en dos mitades **gemelas** —reparto alternado en orden de tamaño—. La
mitad **tratada** recibe lease en frío, hash **con el lease vivo** y liberación. La **control**
recibe
sólo el hash en frío. Cada celda se mide una sola vez porque «frío» no se repite sobre los mismos
bytes.

| Árbol | Mitades | Tratado `lease→hash` | Control `hash` solo | Sobrecoste |
|---|---|---|---|---|
| `C:\Program Files\Git` | 4.757 / 4.757 · 214,4 / 210,8 MB | 33,479 + 3,165 + 0,036 = **36,681 s** | **34,650 s** | **+5,9 %** |
| `Python312\Lib\site-packages` base | 1.190 / 1.230 · 27,00 / 27,00 MB | 0,197 + 0,906 + 0,024 = **1,128 s** | **0,908 s** | **+28,4 %** |

- el sobrecoste **es exactamente una apertura más por archivo**; con el lease delante, el hash
  posterior baja de 34,7 s a 3,2 s. Congelar y después medir **no** duplica el trabajo;
- el porcentaje **no generaliza**: entre +5,9 % y +28,4 % según tamaño medio y estado de caché;
- un tercer brazo sobre el árbol de Node quedó **inválido** —el reparto dejó un archivo de 288 MB
  frente a 2.057— y se descartó;
- las celdas son una medición única por cuadro, sin percentiles. No hay p50/p95 y no se afirman.

Con **64.725 handles** simultáneos: pool no paginado 14.560 → 18.640 B, paginado 163.416 →
1.183.320 B, memoria privada 33 → 68 MB, liberación 2,89 s. Retener decenas de miles de handles es
barato.

`PREFLIGHT_DEADLINE_SECONDS` vale **300,0 s** (`contracts.py:121`) y el término dominante ya lo paga
el hash actual. Extrapolar de aquí a un candidato real sería inventar: ver §7.4.

### 2.7 No-follow y reparse points

Una junction creada con `_winapi.CreateJunction` —que esta torre permite sin privilegios— declara el
bit `FILE_ATTRIBUTE_REPARSE_POINT` y `is_symlink() == False`. El lease abierto con
`FILE_FLAG_OPEN_REPARSE_POINT` toma el punto de reparse y no su destino. El criterio de detección
sigue siendo el bit de atributo, como quedó fijado al cerrar
`candidate_output_os_isolation_unimplemented`.

## 3. La pieza 2: lo que el lease no cubre

### 3.1 Plantado transitorio: detectar no es prevenir

La primera redacción afirmaba que «el censo de igualdad exacta remedido tras la quiescencia detecta
cualquier alta». **Es falso** y se retira: el recenso posterior sólo ve altas **que siguen
existiendo**. Un tercero puede crear un archivo, dejar que se cargue y retirarlo antes de la
quiescencia; el intento terminaría con un árbol exactamente igual al declarado y habría ejecutado
bytes no hasheados.

Por eso la pieza 2 exige **prevenir la apertura** o **atestiguar lo efectivamente cargado**, no
comparar dos fotos.

### 3.2 `.pyc` plantado — el `pycache_prefix` es un vector vivo, ahora medido

Con un `.pyc` legítimo y una fuente sustituida después conservando **mtime y tamaño**:

| Invocación | Valor observado |
|---|---|
| sin `pycache_prefix` | `ORIGINA` — **gana el `.pyc` plantado** |
| sólo `-B`, sin `pycache_prefix` | `ORIGINA` — **`-B` no basta**: sólo desactiva la escritura |
| `-B -X pycache_prefix=<dir del arnés>` | `SUSTITU` — el `__pycache__` del árbol se ignora |

**Pero la bandera no cierra el vector: lo muda de sitio**, y esta redacción lo **ejerce de punta a
punta**. El `pycache_prefix` es una de las **tres raíces escribibles**
—`CANDIDATE_WRITABLE_ROOT_COUNT
= 3`, `contracts.py:58`— con etiqueta Low a propósito, y `_validate_pycache_isolation`
(`adapters.py:3191-3197`) comprueba `any(expected.iterdir())` **una sola vez, antes de ejecutar**.

Medido con un doble sintético que conserva esa precondición: se comprueba la vacuidad (verde), se
planta un `.pyc` válido **después**, y el import tardío devuelve **`PYC-PLANTADO`** con su marcador
ejecutado. El vector no es una hipótesis.

**El sello de altas lo cierra, y está medido.** Con el prefijo etiquetado Low y sellado contra
`FILE_ADD_FILE|FILE_ADD_SUBDIRECTORY|FILE_DELETE_CHILD`, un hijo con token Low que intenta crear
`plantado.pyc` obtiene **`PermissionError`** y el archivo **no aparece**. Vacuidad: sin sello, el
mismo hijo Low **lo crea** y el archivo queda presente. Como el prefijo es harness-owned, el sello
cae **dentro** de la frontera vigente. Retirarle la etiqueta Low sí cambiaría el contrato que su
docstring declara y necesita decisión propia.

### 3.3 Corrección del censo del canal Python — tres censos previos fueron inexactos

La quinta redacción decía «**12** `except ImportError` que guardan imports opcionales» y «**seis**
módulos consultan `importlib.metadata`». La sexta corrigió el segundo número pero mantuvo el
primero y añadió un desglose propio, también equivocado. La cuarta revisión adversarial objetó el
desglose y propuso el suyo, **que tampoco reconcilia**. El censo definitivo se hace con AST sobre
`src/nikodym`, contando cláusulas `except` que capturen `ImportError` **incluidas las de tupla**:

| Fuente | Afirmación | Veredicto |
|---|---|---|
| quinta y sexta redacción | «12 cláusulas» | **falso**: son **14** |
| cuarta revisión adversarial | «12 cláusulas; 7 con `import_module`, 5 literales y 2 variables; 1 restante» | **falso**: son 14, con **8** `import_module` —5 literales y **3** variables— y **2** restantes |
| censo AST vigente | **14** cláusulas: **4** envuelven un `import`/`from` literal · **8** llaman `importlib.import_module`, **5** con literal y **3** con el nombre en una variable · **2** no hacen ninguna de las dos cosas | medido |

Las dos cláusulas que ningún censo anterior vio son `except (ImportError, ...)` **de tupla**, que un
`grep "except ImportError"` no encuentra: `core/config/schema.py:1341` y `report/exports.py:220`.
Las dos «restantes» son `report/exports.py:220` —una **sonda** con `importlib.util.find_spec`, no un
import— y `report/exports.py:267`, que captura el import que `pandas.ExcelWriter` hace del engine
por dentro. El tercer nombre variable es `core/config/schema.py:1341`, que importa **cada módulo de
dominio** por nombre desde `_DOMAIN_CONFIG_CLASSES`: una superficie dinámica mayor que las otras
dos.

`importlib.metadata` lo importan **20 archivos**, no seis. Ese número sí reconcilia en los dos
censos posteriores.

Y una corrección **de dirección**, no sólo de conteo, que es la que importa. Los **14 nombres raíz**
que aparecían en la lista —`fastapi`, `matplotlib`, `pandas`, `uvicorn`, `optbinning`, `polars`,
`openpyxl`, `shap`, `hypothesis`, `sklearn`, `xgboost`, `lightgbm`, `catboost`, `mlflow`— están
**todos presentes** en esta torre, así que el vector real no es la ausencia sino el **sombreado**:
`adapters.py:1349` hace `sys.path[:] = [request["candidate_root"], *sys.path]`, de modo que
`candidate_root` va **primero** y un paquete plantado allí gana a **cualquier** nombre instalado,
esté o no en esa lista. **La superficie no son 14 nombres: es todo el espacio de nombres
importable.** Enumerar nombres guardados era, desde el principio, la pregunta equivocada.

`-I` y `-S` siguen aportando lo suyo: cierran `sys.path` al conjunto declarado y desactivan `.pth`.
No cierran el descubrimiento **dentro** de las raíces declaradas.

### 3.4 DLL plantada — el mecanismo alegado por la revisión es falso en este runtime

La revisión adversarial sostuvo que el orden de búsqueda de DLL incluye el **directorio de
trabajo**,
y que como el candidato corre con `staging` como CWD, una DLL plantada allí se cargaría. **Medido:
no
ocurre en CPython 3.12.**

| Escenario | Resultado medido |
|---|---|
| DLL en el CWD, carga por nombre | **NO CARGA** |
| DLL en un CWD neutral, carga por nombre | **NO CARGA** |
| vacuidad: carga por **ruta absoluta** | **CARGA** |
| vacuidad: `os.add_dll_directory(dir)` y carga por nombre | **CARGA** |
| `SetDefaultDllDirectories(LOAD_LIBRARY_SEARCH_SYSTEM32)` + `add_dll_directory` | **NO CARGA** |

Las dos filas de vacuidad prueban que la DLL era cargable. CPython carga DLL con
`LOAD_LIBRARY_SEARCH_DEFAULT_DIRS` desde 3.8: el CWD y el `PATH` no se buscan.

**Alcance exacto de la refutación.** Vale para las dos rutas primarias de carga de CPython —import
de
extensiones y `ctypes`— y **sólo** para ellas. Una extensión nativa ya cargada puede llamar
`LoadLibraryEx` con ruta absoluta o `LOAD_WITH_ALTERED_SEARCH_PATH`, y las flags por llamada
sustituyen la política del proceso. Decir que «el vector por CWD no existe» sería generalizar más
allá de lo medido. **D-LEA-11 no es por sí sola una frontera completa.**

Residuo honesto: un paquete puede llamar `os.add_dll_directory()` sobre un directorio del árbol
—pyarrow lo hace— y una DLL **nueva** allí sí entraría; el directorio de la aplicación está siempre
en la búsqueda; y una DLL dependiente de un `.pyd` se resuelve con el directorio del propio `.pyd`.

### 3.5 Acoplamiento con otra frontera abierta

Atestiguar cada imagen por PID recorre el mismo árbol de procesos que
`multiprocess_native_pool_observer_unimplemented`. Se declara el acoplamiento en vez de duplicar el
recorrido. Conviene no exagerarlo: aquel instrumental censa **PID y creation-time**, y eso **no**
aporta la garantía causal de D-LEA-12. Comparten el recorrido, no el oráculo.

### 3.6 `DEBUG_PROCESS` **sí** convive con el lanzador vivo — medido

Era la primera de las dos incógnitas que bloqueaban D-LEA-12. Medido componiendo
`DEBUG_PROCESS | CREATE_SUSPENDED | CREATE_UNICODE_ENVIRONMENT | EXTENDED_STARTUPINFO_PRESENT` con
el token Low y el Job `KILL_ON_JOB_CLOSE`:

| Elemento del lanzador vivo | Resultado |
|---|---|
| `CreateProcessAsUserW` con token Low y `DEBUG_PROCESS` | **OK** |
| `process_integrity_level` | **S-1-16-4096** |
| `assign_to_job` con `KILL_ON_JOB_CLOSE` · `IsProcessInJob` | **OK** · **true** |
| `resume_suspended_process` por `OpenThread(THREAD_SUSPEND_RESUME)` | **OK**, `suspend_previo=1` |
| composición con la DACL restrictiva de 0-b | **OK**, sin cambios |
| cobertura de **descendientes** | **sí**: 4 PID depurados en el caso con nieto |
| vacuidad: sin `DEBUG_PROCESS` | **cero eventos** |

**Tres hallazgos operativos que no estaban en ninguna redacción anterior:**

1. **`KILL_ON_JOB_CLOSE` sigue matando a un depurado.** Medido: con el hijo vivo, `exit_code=259`;
   cerrado el Job, `exit_code=0`. La contención del Job **no se debilita** por depurar.
2. **Pero el proceso terminado NO se señaliza hasta drenar el puerto de depuración.** Medido tras
   cerrar el Job: `GetExitCodeProcess` devuelve 0 —terminado— y `WaitForSingleObject` devuelve
   **`0x102` (no señalizado)**. Drenados 7 eventos pendientes, pasa a **señalizado**. El
   `process.wait(timeout)` del arnés **expiraría sobre un candidato correctamente muerto**. Es
   D-LEA-21.
3. **El puerto de depuración es del HILO, no del proceso.** `WaitForDebugEvent` desde otro hilo
   devuelve **`FALLO(6)`**. El bucle debe correr en el hilo que creó el candidato — restricción
   arquitectónica real para el supervisor. Y un puerto no drenado **contamina la siguiente medición
   del mismo hilo**: se observó en carne propia, con eventos de un caso apareciendo en el siguiente,
   y por eso cada celda de coste se mide ahora en un proceso fresco.

También medido: si el depurador muere, el depurado **muere con él** salvo
`DebugSetProcessKillOnExit(FALSE)`. El comportamiento por defecto es fail-closed y coincide con
`KILL_ON_JOB_CLOSE`.

### 3.7 `LOAD_DLL_DEBUG_EVENT` llega **antes** de todo código de inicialización

Era la segunda incógnita. Esta torre **no tiene compilador C** —medido: `cl`, `gcc`, `clang`,
`link`, `tcc` y `dumpbin` ausentes; sin Visual Studio, Windows Kits, LLVM, msys2 ni MinGW;
`vswhere` inexistente—. La exigencia de una DLL propia con marcador se cumplió **ensamblando el PE
x64 a mano**: 1.536 bytes, un import (`kernel32!CreateDirectoryW`), código RIP-relativo y `DllMain`
que crea un directorio marcador en `DLL_PROCESS_ATTACH`.

La cuarta revisión adversarial objetó, con razón, que parchear el entry point prueba que **esa** DLL
devolvió `FALSE`, no que el gate impida **todo** código de inicialización: el formato PE admite
**callbacks TLS** que corren al margen del entry point. Se rehízo el experimento con una segunda DLL
artesanal —2.048 bytes, reubicaciones `IMAGE_REL_BASED_DIR64` reales, porque la estructura TLS
guarda VA absolutas— que deja **dos** marcadores distintos: uno desde `DllMain` y otro desde un
callback TLS. Con el árbol depurado **congelado** en el evento:

| | En el evento | `LoadLibraryW` en el hijo | Marcador `DllMain` | Marcador **TLS** |
|---|---|---|---|---|
| **vacuidad**, sin depurador | — | winerror 0 | **existe** | **existe** |
| **ORDEN**, depurando sin actuar | ninguno existe | winerror 0 | existe | existe |
| **parcheando el entry point** | ninguno existe | **`NULL`, winerror 1114** | **no existe** | **EXISTE** |
| **terminando el proceso en el evento** | ninguno existe | — (proceso muerto, `exit=0xDEAD`) | **no existe** | **no existe** |

Tres lecturas, y la tercera corrige a la sexta redacción:

1. **El orden queda acreditado y además reforzado:** en el evento **no ha corrido ninguno de los
   dos**, ni `DllMain` ni el callback TLS. La fila de vacuidad prueba que ambos marcadores
   aparecerían si hubieran corrido.
2. **Parchear el entry point NO es una primitiva de prevención.** Medido: el callback TLS **ejecuta
   igual** y deja su marcador aunque `LoadLibrary` devuelva `ERROR_DLL_INIT_FAILED`. La sexta
   redacción declaraba «D-LEA-12 puede impedir la ejecución» apoyándose sólo en el parche; **esa
   afirmación se retira**.
3. **La acción fail-closed correcta es independiente del contenido del PE:** terminar el proceso
   antes de `ContinueDebugEvent`. Medido: ningún marcador aparece, ni el de `DllMain` ni el de TLS,
   y el proceso muere con el código que el gate le pasa. Eso es lo que D-LEA-12 prescribe ahora.

No se ha medido cada modalidad de inicialización que el formato PE admite —DLL sin entry point,
secciones con `Characteristics` exóticos, `LOAD_LIBRARY_AS_DATAFILE`—, y por eso el mecanismo se
apoya en la acción **independiente del contenido**, no en enumerar los sitios desde los que un PE
puede ejecutar.

> **Defecto propio, corregido y declarado.** El primer intento de esta medición dio «marcador
> ausente» también **sin depurador**, y el parche falló con `winerror 998`. Dos causas: el marcador
> se creaba en un directorio de integridad Media, donde un hijo con token Low **no puede escribir**
> —`NO_WRITE_UP`—, así que no era observable; y el parche apuntaba al proceso equivocado. La segunda
> causa es en sí un hallazgo: **`.venv\Scripts\python.exe` es un lanzador que crea un segundo
> proceso** con el `python.exe` del prefijo base, y **es ahí donde se carga la DLL**. Confirma en
> vivo
> §4.2 y obliga a que el gate indexe handles por PID.

**Sinergia con D-LEA-7.** El evento entrega un `hFile` **no nulo** del propio cargador. Medido: se
puede hashear **por ese handle** sin reabrir la ruta —227 imágenes, 235.127.568 bytes, digests
reales
para `ntdll.dll`, `kernel32.dll`, `KernelBase.dll`—. El «hash por el handle retenido» de D-LEA-7 es
alcanzable también para imágenes.

### 3.8 El canal Python: mecanismo causal para lo que CPython audita, y **nada más**

El mecanismo propuesto es un **audit hook de PEP 578** instalado por el bootstrap del arnés antes de
que corra una línea del candidato, que rechaza `open`, `import`, `exec` y `compile` cuya ruta esté
**dentro de una raíz declarada** y **fuera del inventario**. Un audit hook instalado desde Python no
se puede retirar, así que cada caso se midió en un intérprete fresco.

> **Corrección de la sexta redacción.** Esa redacción llamaba al mecanismo «no eludible». **Se
> retira la palabra.** Un hook instalado desde Python no es un sandbox: la propia documentación de
> CPython lo advierte, y este documento **mide** un bypass concreto más abajo. Lo correcto es
> enunciar la promesa por su alcance —las operaciones que CPython audita— y no por una propiedad
> que no tiene.

| Vector | Vacuidad, sin gate | Con gate |
|---|---|---|
| `.py` plantado en `candidate_root` | ejecuta; marcador presente | **`PermissionError`** por evento `open`; marcador **ausente**; el módulo inventariado sigue importando |
| **ZIP importable** | `desde-zip`; marcador presente | **bloqueado**; marcador ausente |
| **`.dist-info` plantado** | `version()` → **`9.9.9`** | `version()` → **`None`**; 3 violaciones registradas |
| **`.pyc` en `pycache_prefix` tras la vacuidad** | gana `PYC-PLANTADO`; marcador presente | **`PermissionError`** nombrando el `.pyc` |

Batería de elusión, ocho vías **por las rutas que CPython audita**, todas PASAN sin gate y todas
quedan BLOQUEADAS con gate: `import` normal · `importlib.import_module` ·
`spec_from_file_location` + `exec_module` · `exec(compile(open().read()))` · `io.open_code` +
`exec` · `SourceFileLoader.get_code` + `exec` · `open(rb).read()` + `compile('<memoria>')` + `exec`
· instalar un audit hook adicional y reintentar.

**El bypass, medido y declarado.** El gate es **por ruta** y sólo ve lo que CPython audita; una
lectura nativa no pasa por ahí:

| Lectura del mismo archivo plantado, con gate puesto | Resultado |
|---|---|
| `open()` del stdlib | **BLOQUEADO** |
| `CreateFileW` por `ctypes` + `exec(compile(src,'<memoria>'))` | **PASA y EJECUTA** |

**Y D-LEA-12 tampoco lo cubre.** La sexta redacción decía que ese caso «cae en D-LEA-12». **Es
falso y se retira:** `ctypes` llama a `kernel32` **ya cargado**, no se carga ninguna imagen nueva y
el gate de imágenes no recibe evento alguno. El bypass no está cubierto por ninguna de las dos
piezas.

Por tanto D-LEA-12b promete exactamente esto, y nada más: **impide que una entrada no inventariada
de una raíz declarada sea abierta, importada, compilada o ejecutada por las rutas que CPython
audita.** No es una frontera de seguridad frente al propio candidato.

> **Corrección forzada por la quinta revisión (F3).** La séptima redacción decía que «todo el código
> del candidato queda dentro del TCB de esta frontera» como si eso resolviera el bypass nativo.
> Objeción válida: **meter en el TCB los bytes que un atacante logre ejecutar vaciaría la
> garantía**. Bajo **0-b** —donde el modelo de amenaza incluía a terceros del mismo usuario— la
> frase
> era una garantía vacía y se retira. Bajo **0-a** es coherente y no vacía: el mismo usuario y el
> propio candidato **son** el TCB por decisión declarada, no por descuido. El bypass nativo no es
> entonces un agujero en una promesa de seguridad, sino un **límite de completitud de la
> atestación** —el gate no ve lo que CPython no audita—, y como tal se publica.

El límite honesto es que un candidato con carga nativa de plugins puede leer y ejecutar un archivo
plantado sin que ninguna de las dos piezas falle. No es hipotético y no se oculta: se publica en la
evidencia por D-LEA-22 y tiene control negativo propio en §8, cuyo rojo esperado es
**verde**, precisamente para que un cambio futuro de esa frontera se note.

### 3.9 El gate bloquea, pero la excepción **no llega al consumidor**

Hallazgo que cambia el diseño de D-LEA-12b. Con el gate puesto sobre el `.dist-info` plantado:

- `importlib.metadata.version('paquete-falso')` devuelve **`None`**, de tipo `NoneType`;
- **la `PermissionError` no llega al llamador**: la biblioteca se la traga;
- sólo el **registro propio del hook** la conserva: 3 violaciones —`METADATA`, `PKG-INFO` y el
  propio
  directorio `.dist-info`—.

`calibration/step.py:509` escribe versiones **en la evidencia**. Un `None` silencioso entraría ahí
sin
que nada falle. **Conclusión: D-LEA-12b no puede apoyarse en la propagación de la excepción.** El
hook registra, y el intento **falla cerrado sobre el registro**, no sobre lo que la biblioteca
decida
propagar. Es D-LEA-22.

> **Defecto propio, corregido y declarado.** La primera medición de este punto reportó «0
> violaciones
> registradas», lo que habría sido un falso negativo grave. La causa era mía: `textwrap.dedent`
> había
> cambiado la indentación del hook y mi `str.replace` que añadía el registro **no aplicó**. Con el
> registro realmente instalado, salen 3. Se remidió entero.

## 4. Qué exactamente hay que congelar

### 4.1 Conjunto congelado propuesto

| Grupo | Elementos |
|---|---|
| ejecutable | `runtime.python_executable` y su clausura de carga (§4.2) |
| árbol candidato | todos los archivos y todos los directorios de `runtime.installed_tree` |
| procedencia | `wheel`, `sdist`, `lock`, `runtime.environment` |
| inputs | `fixture.inputs[*]`, `fixture.bundle`, `fixture.generator.artifact`, `fixture.expected.golden`, `fixture.fixture_schema`, `fixture.config`, `fixture.catalog` |
| launch sources | autoridad, texto de autorización, trust anchor, manifiesto candidato, manifiesto fixture, config, schedule |
| campaña | cada evidencia previa consumida por `validate_campaign_progress` (§7.3) |

El runtime confiable del arnés no entra aquí: lo congela `materialize_harness_source_snapshot`. Ver
§4.3 para lo que ese snapshot **no** cubre.

### 4.2 El intérprete del candidato no está declarado — y ahora está confirmado en vivo

Medido sobre la venv writer, que es el mismo tipo de venv que produciría un candidato con `uv`:

```
executable   ...\.venv\Scripts\python.exe        (274.424 B)
prefix       ...\AppData\Local\Programs\Python\Python312
base_prefix  ...\AppData\Local\Programs\Python\Python312
sys.path     python312.zip · DLLs · Lib · Python312
```

El `python.exe` de la venv es un **lanzador**; el intérprete real vive en el prefijo base, **fuera
de
todo lo que el manifiesto candidato declara**. La medición de §3.7 lo confirma **en ejecución**: el
depurador ve dos `CREATE_PROCESS_DEBUG_EVENT` —`.venv\Scripts\python.exe` y
`AppData\Local\Programs\Python\Python312\python.exe`— y **toda la carga de imágenes ocurre en el
segundo**. Ya no es una inferencia sobre rutas: es un segundo proceso observado.

Falta además `pyvenv.cfg`: es el archivo que **decide** cuál es el prefijo base, y se lee antes de
ejecutar código. Sustituirlo cambia el intérprete entero sin tocar ningún archivo del conjunto que
la
primera redacción proponía.

Congelar «el ejecutable» de forma honesta exige declarar:

1. `pyvenv.cfg` y cualquier archivo de descubrimiento del prefijo;
2. el ejecutable y `python3xx.dll`;
3. `Lib/`, `DLLs/` y el `pythonXY.zip` si existe;
4. la clausura **transitiva** de DLL/`.pyd` que el runtime carga;
5. una **frontera explícita del TCB de Windows**: qué parte del sistema operativo se acepta como
   confiable y por tanto no se congela. Sin esa línea, «clausura completa» no tiene final.

Eso añade declaraciones obligatorias nuevas al manifiesto candidato, y por tanto es contrato.

### 4.3 Hallazgo adyacente: el runtime del propio arnés

`materialize_harness_source_snapshot` congela fuentes e import roots, pero **no** el ejecutable
Python
del arnés, ni su `pyvenv.cfg`, ni el prefijo base, ni la stdlib — y el supervisor lanza worker,
adapter y controller con ese Python vivo. Es la misma clase de brecha, en la otra mitad del sistema,
y
**está fuera del alcance de esta frontera**. Se propone abrirla como blocker propio (§7.5).

## 5. Decisiones propuestas

### Pieza 1 — anti-sustitución

**D-LEA-1.** El material de ejecución candidato queda **congelado de forma continua** desde su
validación hasta la quiescencia del árbol candidato. Congelado significa *nadie puede sustituir,
borrar, renombrar ni reemplazar esos bytes mientras el lease vive*, no *se vuelve a hashear más
veces*.

**D-LEA-2.** El mecanismo es `windows_share_mode_lease_v1`: un handle por archivo, `GENERIC_READ`
con `FILE_SHARE_READ` como único modo compartido y `FILE_FLAG_OPEN_REPARSE_POINT`; y un handle por
directorio con los mismos modos más `FILE_FLAG_BACKUP_SEMANTICS`.

**D-LEA-3.** El lease **falla cerrado**. Si cualquier elemento no puede leasearse el intento se
rechaza antes de START con `preflight_rejected` y no se emite ningún token.

**D-LEA-4.** Los directorios se adquieren **parent-first** y antes que sus archivos.

**D-LEA-5.** El conjunto congelado se coteja contra un **inventario canónico por entrada**, no
contra
un agregado. El manifiesto vigente declara de `installed_tree` sólo
`relative_path/files/logical_bytes/sha256`, y `canonical_tree_identity` **descarta** la lista de
entradas después de calcular el digest. El manifiesto gana ese inventario, ligado al digest agregado
ya existente.

**D-LEA-6.** La adquisición y el cotejo usan **enumeraciones independientes**. Cada archivo se
coteja
además por **volumen y file ID**, no sólo por ruta.

**D-LEA-7.** El hash de cada elemento se calcula **a través del handle retenido**, no reabriendo la
ruta. Medido que esto es alcanzable también para imágenes cargadas, por el `hFile` del propio evento
de depuración (§3.7).

**D-LEA-8.** El lease se adquiere **antes** del primer hash del conjunto y se mantiene mientras se
hashea. Congelar y luego medir; nunca medir y luego congelar.

**D-LEA-9.** El arnés **no modifica descriptores de seguridad de rutas que no le pertenecen**. Se
mantiene la frontera vigente de `_seal_windows_snapshot_directories`. *(Cambia si Cami elige la
variante B; ver §7.1. El sello del `pycache_prefix` de D-LEA-10 **no** la toca: ese directorio es
harness-owned.)*

### Pieza 2 — anti-inyección

**D-LEA-10.** `-X pycache_prefix=<ruta fresca, vacía y propiedad del arnés>` es parte declarada del
contrato de congelación. Medido que `-B` por sí solo **no** impide que un `.pyc` plantado gane, que
la comprobación de vacuidad es **puntual** y que el vector se ejerce plantando **después** de ella
(§3.2). El prefijo se **sella contra altas** durante todo el intento —medido: un hijo con token Low
obtiene `PermissionError` y el archivo no aparece; sin sello, lo crea— y su vacuidad se atestigua al
cierre, no sólo antes de ejecutar.

**D-LEA-11.** El candidato corre con una **clausura de búsqueda de DLL explícita**: sólo el
directorio del sistema y los directorios leaseados del conjunto congelado. Gobierna los defaults del
proceso y `os.add_dll_directory`; **no** gobierna una carga nativa con flags propios o
`LOAD_WITH_ALTERED_SEARCH_PATH` (§3.4), y por eso no basta sola.

**D-LEA-12.** El intento atestigua cada imagen cargada por cada proceso del Job candidato —ruta,
file ID y digest— mediante un **gate síncrono anterior a su ejecución**. El mecanismo es la cadena
de eventos de depuración: crear el árbol con `DEBUG_PROCESS`, procesar cada
`CREATE_PROCESS_DEBUG_EVENT`/`LOAD_DLL_DEBUG_EVENT` **indexando handles por PID**, hashear **desde
el `hFile` del evento** antes de `ContinueDebugEvent`, y **terminar el proceso que carga** una
imagen no inventariada, también antes de `ContinueDebugEvent`. Fallar cerrado ante handle nulo,
evento perdido o hueco de PID/creation-time.

> **Estado: acreditado, con la acción de prevención corregida.** Lo que la quinta redacción
> declaraba «no medido» está medido en §3.6 y §3.7: `DEBUG_PROCESS` convive con el token Low, el Job
> con `KILL_ON_JOB_CLOSE`, el arranque suspendido y la DACL de 0-b; cubre descendientes; y el evento
> llega **antes** de `DllMain` **y del callback TLS**.
>
> La acción de prevención **cambió respecto de la sexta redacción**. Aquélla proponía parchear el
> entry point; medido, un callback TLS **ejecuta igual** pese al parche y pese a
> `ERROR_DLL_INIT_FAILED`. La acción prescrita es ahora **terminar el proceso**, que no depende del
> contenido del PE y quedó medida sin ningún marcador ejecutado. Indexar por PID es obligatorio
> porque el intérprete real es un segundo proceso (§4.2).

**D-LEA-12b.** El **canal Python** tiene su propia pieza causal, porque un `.py`, un ZIP importable
o un `.dist-info` no producen imagen PE. El mecanismo es un **audit hook de PEP 578** instalado por
el bootstrap antes de que corra código del candidato, que rechaza `open`/`import`/`exec`/`compile`
sobre una entrada **no inventariada** de las raíces declaradas. Medido causal en los cuatro vectores
y resistente a las ocho vías de elusión probadas **por las rutas que CPython audita** (§3.8).

> **Alcance, no adorno.** No se afirma que sea «no eludible»: está medido que una lectura nativa por
> `ctypes` lo esquiva, y está medido que **D-LEA-12 tampoco cubre ese caso**, porque no se carga
> ninguna imagen nueva. La promesa es la del alcance auditado, y el corolario contractual —todo el
> código del candidato, Python y nativo, dentro del TCB de esta frontera— se declara en §3.8 y se
> publica en la evidencia.

**D-LEA-13.** El manifiesto candidato declara la **clausura de carga del intérprete** en los cinco
términos de §4.2, incluida la frontera explícita del TCB de Windows, y esa clausura entra en el
conjunto congelado. *(Sujeta a §7.2.)*

**D-LEA-14.** El censo enumera y **rechaza streams no predeterminados** en cada elemento del
conjunto. Medido que el lease se evalúa por stream y que un ADS puede crearse sobre un archivo
leaseado sin alterar su stream por defecto.

**D-LEA-15.** El material congelado debe residir en un **filesystem y volumen calificados** por una
matriz cerrada. Toda la evidencia de §2 proviene de NTFS local; SMB, filesystems respaldados por
nube
y material multivolumen **no están medidos** y no se dan por buenos.

### Pieza 3 — anti-falso-éxito

**D-LEA-16.** La publicación de evidencia sigue una **máquina de estados de tres pasos**, y ningún
paso posterior al release puede volver a leer material vivo:

1. **provisional** — se construye y valida la evidencia **con el lease vivo**, y ésa es la única
   validación que puede usar `verify_artifacts=True`;
2. **release** — se cierran y verifican todos los handles;
3. **promoción** — sólo entonces se escribe atómicamente el terminal `success`.

Hoy el código vivo hace lo contrario: escribe `attempt.json` y **después** lo revalida con
`verify_artifacts=True` contra artefactos vivos.

**D-LEA-17.** Un fallo de liberación tiene **clasificación propia** y publica evidencia de fallo,
nunca de éxito. La liberación es transaccional y verificada.

**D-LEA-17b.** Los consumidores **durables** validan la atestación y el inventario congelados, no
reabren material vivo. Hoy `validate_campaign_progress` revalida cada evidencia previa con
`verify_artifacts=True`, y `_attempt_summary` hace lo mismo.

**D-LEA-17c.** Cambiar el booleano **no basta y sería peor**: con `verify_artifacts=False` el
validador deja de comprobar launch sources, tooling, outputs y la mayor parte de los sidecars, y el
self-binding sólo compara el payload con los bytes que existan en ese momento. La firma Ed25519
autentica la **autoridad de START**, no el resultado. Por eso la promoción produce un **paquete
durable content-addressed** anclado **fuera** del workdir mutable.

**D-LEA-18.** La evidencia publica el censo del lease —archivos y directorios leaseados, inventario
canónico, digest del conjunto, imágenes atestiguadas y momentos de adquisición y liberación
relativos
a START y a la quiescencia—.

### Alcance

**D-LEA-19.** Cerrar esta frontera **no** habilita START. Bajo 0-a, aprobar retira
`candidate_execution_material_lease_unimplemented` de los blockers de implementación **y abre**
`candidate_process_memory_isolation_unimplemented` —la vía de memoria diferida (§0.6, §0.7)—, de
modo que la puerta global no baja de blockers: uno se sustituye por otro más acotado y honesto. La
autorización humana por unidad exacta y la fingerprint durable siguen siendo obligatorias, y
`qualifying_boundary_adapters_unavailable` y `multiprocess_native_pool_observer_unimplemented`
siguen
abiertas.

### Decisiones nuevas de esta redacción

**D-LEA-20 — retirada. El endurecimiento posterior no cierra el canal de descendientes.** La séptima
redacción proponía endurecer cada proceso e hilo descendiente por su tipo desde el canal de
depuración. Medido, tiene una **carrera** que no se cierra endureciendo después: un tercero Medium
abre el descendiente en la ventana entre su creación y el cambio de DACL, cachea el handle, y el
acceso ya concedido **no se revoca** (§0.6, F1). D-LEA-20 se retira. Bajo **0-a** no hace falta —el
mismo usuario está dentro del TCB—; bajo **0-b** haría falta seguridad de objeto **en la creación**
(un broker), que es materia del blocker diferido `candidate_process_memory_isolation_unimplemented`,
no de esta enmienda.

> Lo medido no se pierde: sirve al blocker diferido. La raíz sí puede nacer con descriptores
> explícitos (`0x1101`/`0x802` + `OWNER RIGHTS`), y `TokenDefaultDacl` **no** es la vía —medido,
> `0x80A` rompe `process_metrics`/`assign_to_job` sobre los descendientes con `winerror 5` y a la
> vez concede al atacante `PROCESS_SUSPEND_RESUME|VM_OPERATION|CREATE_THREAD` (§0.6)—. Un broker que
> interponga el descriptor antes de publicar el PID del descendiente es la dirección; su diseño y
> medición pertenecen a la enmienda de ese blocker.

**D-LEA-21 — drenaje del puerto de depuración.** El puerto de depuración pertenece al **hilo** que
creó el candidato. El supervisor mantiene el bucle en ese hilo y **drena el puerto hasta el
`EXIT_PROCESS` de cada PID depurado antes de esperar la terminación**. Medido que un candidato
muerto
por `KILL_ON_JOB_CLOSE` **no se señaliza** mientras queden eventos sin consumir, de modo que un
`wait()` ingenuo expiraría sobre un árbol correctamente terminado (§3.6). Un puerto no drenado
además **contamina la siguiente medición del mismo hilo**.

**D-LEA-22 — fallar sobre el registro, no sobre la excepción; y publicar los límites de 0-a.** Dos
cosas que las mediciones obligan a fijar:

1. Los gates de las piezas 2 **registran cada violación** y el intento falla cerrado **sobre ese
   registro**. Medido que `importlib.metadata.version()` se traga la `PermissionError` y devuelve
   `None`, y que sólo el registro propio conserva la evidencia (§3.9). Apoyarse en la propagación
   dejaría entrar un `None` a la evidencia firmada.
2. La evidencia declara explícitamente el modelo de amenaza de 0-a: los procesos Medium del mismo
   usuario están **dentro del TCB**. Por tanto la frontera **no** promete integridad frente a
   inyección en memoria, ni frente a un tercero que mate el candidato o le imponga un Job anidado
   (§0.7), ni frente a una lectura nativa que eluda el gate Python (§3.8). No son residuos
   ocultos: son la línea del TCB, publicada en la evidencia firmada, y cada uno tiene su blocker o
   su declaración. Un límite declarado es auditable; uno omitido, no.

## 6. Alternativas evaluadas

### 6.1 Rehash más frecuente

Descartada. Un rehash no impide la sustitución: la constata después, y sólo si el sustituto sigue
allí. Contra un plantado transitorio no prueba nada.

### 6.2 Copiar el material a espacio propio del arnés (variante C)

Frontera más limpia pero se descarta como recomendación: coste de una copia completa por intento
contra un presupuesto de disco sin fijar; una venv **no es relocalizable** —`pyvenv.cfg` fija `home`
absoluto y los `.exe` de `Scripts` llevan la ruta incrustada—; y el candidato dejaría de ser lo que
el
operador declaró.

### 6.3 Por qué B no es la decisión importante

B añade el sello DACL sobre directorios del operador y así **previene altas** en el árbol candidato,
que A sólo puede atestiguar. Pero no cubre el plantado **transitorio** en las raíces que el propio
arnés hace escribibles, no cubre la clausura del intérprete si no se declara, y deja una DACL ajena
alterada si el supervisor muere de forma dura. Con la pieza 2 implementada, lo que B aporta se
solapa
con la atestación. Por eso la recomendación es A **más** las piezas 2 y 3.

### 6.4 Descartada: confiar en la propagación de excepciones del gate Python

Medida y descartada en §3.9. La biblioteca estándar convierte un fallo de lectura en `None`.

## 7. Lo que Cami debe decidir

### 7.0 Modelo de amenaza — decisión previa a todo lo demás

- **0-a — acotar la promesa (recomendada).** Los procesos Medium del mismo usuario quedan dentro
  del TCB; la frontera promete consistencia del material **en disco** —sustitución, borrado,
  renombre, reemplazo y plantado transitorio— y la línea de §12.1 se reescribe para que prometa eso,
  no «nadie». Cierra con las piezas 1, 2 y 3, sin tocar la creación del proceso.
- **0-b — cerrar también la vía de memoria (diferida).** Medido en §0.6 y §0.7, no es un añadido al
  lease sino un **rediseño de seguridad de proceso**: exige seguridad de objeto en la creación de
  cada descendiente (broker), endurecer el supervisor, y aun así no cubre el bypass nativo ni la
  integridad del entorno medido. Se propone abrirlo como blocker propio
  `candidate_process_memory_isolation_unimplemented`.

Recomendación: **0-a**. La quinta revisión adversarial midió que 0-b tiene una carrera de handles
que
el endurecimiento posterior no cierra (F1) y que el supervisor es una puerta trasera sin endurecer
(F2). Cami decidió el 2026-08-22 acotar a 0-a y diferir 0-b. 0-a no deja el vector sin registrar: lo
declara en la evidencia (D-LEA-22) y le abre blocker propio.

### 7.1 Frontera del mecanismo — decisión principal

- **A (recomendada).** Lease puro en sitio, sin tocar descriptores de seguridad ajenos. Mantiene
  D-LEA-9.
- **B.** Lease más sello DACL sobre los directorios del operador. Retira D-LEA-9.
- **C.** Snapshot sellado. §6.2 explica por qué no se recomienda.

En las tres, las piezas 2 y 3 son obligatorias.

### 7.2 Clausura del intérprete — decisión independiente

- **Incluirla ahora.** El manifiesto gana la clausura de §4.2 y el operador debe declararla.
- **Diferirla.** Se abre un blocker nuevo y explícito, `candidate_interpreter_closure_undeclared`.

Recomendación: **incluirla ahora**. La medición de §3.7 la refuerza: el intérprete real es un
**segundo proceso** que hoy no está declarado en ninguna parte.

### 7.3 Alcance de los inputs

¿Entran también las **evidencias previas de campaña**, que hoy sólo se hashean? Recomendación:
**sí** — su sustitución falsearía la campaña entera, no un intento.

### 7.4 Presupuesto de preflight y de intento

Dos términos distintos, y conviene no mezclarlos:

- **preflight**: el término dominante ya lo paga el hash actual. `PREFLIGHT_DEADLINE_SECONDS` vale
  300,0 s. Recomendación: **dejarlo como está** y medirlo cuando exista un candidato real; subir un
  deadline sin candidato medido sería inventar un valor.
- **intento**: es nuevo, y es §7.7.

### 7.5 El runtime del arnés (§4.3)

¿Se abre `trusted_harness_interpreter_closure_undeclared` como blocker propio? Recomendación:
**sí**,
declararlo abierto y medido, y no mezclarlo con esta frontera.

### 7.6 Qué está cerrado, qué se difiere, y por qué la recomendación es el contrato acotado

Dos rondas de medición y cinco revisiones adversariales dejaron el cuadro nítido:

**Cerrado y acreditado —el núcleo de la frontera—:** la sustitución de material en disco (pieza 1),
el plantado transitorio por los dos canales (pieza 2, con `DEBUG_PROCESS` y el audit hook medidos
con vacuidad en §3.6–§3.8) y la máquina de estados de publicación (pieza 3). Eso es lo que la línea
de §12.1 pedía —«lease no-follow … hasta la quiescencia»— más las dos piezas que las revisiones
mostraron imprescindibles.

**Diferido a blocker propio —0-b, la inyección en memoria—:** la quinta revisión midió que cerrarlo
no es un añadido al lease sino un rediseño: el endurecimiento posterior tiene una carrera de handles
que no se cierra (§0.6, F1) y el supervisor es una puerta trasera sin endurecer (§0.7, F2). Se abre
`candidate_process_memory_isolation_unimplemented` y se conserva ahí todo lo medido.

Por tanto la recomendación es **aprobar el contrato acotado (0-a) ahora**, con las variantes de
§7.1–§7.5 y §7.7 y las ramas de §10. Lo que 0-a **no** promete queda declarado y publicado en la
evidencia (D-LEA-22): la inyección en memoria (blocker propio), el bypass nativo del canal Python
(§3.8) y la integridad del entorno medido (§0.7). Ninguno es un residuo oculto; son la línea del
TCB.

Se mantiene la alternativa de **reordenar la cola** por si Cami prefiere otro orden: dejar incluso
el
contrato acotado en espera y mover el esfuerzo a `multiprocess_native_pool_observer_unimplemented`,
cuyo instrumental se solapa con el gate de D-LEA-12 (§3.5). Cerrar aquélla primero podría abaratar
ésta.

### 7.7 El precio del intento — decisión nueva, con el número medido

Las dos piezas del punto 2 no son gratis, y el arnés existe para **medir tiempos**. Sobre la misma
carga real —`numpy`, `pandas`, `pyarrow`, `pyarrow.parquet`, `sklearn` y una tabla de 50.000 filas—,
cada celda en un proceso fresco, una medición por celda y **sin percentiles**:

| Configuración | Tiempo interno del candidato | Sobrecoste | Imágenes atestiguadas |
|---|---|---|---|
| ninguna pieza | **1,901 s** | — | — |
| sólo D-LEA-12 (depuración + hash de imágenes) | **2,881 s** | **+51,6 %** | 246 · 235.127.568 B · 0,476 s sólo de hash |
| sólo D-LEA-12b (audit hook) | **2,987 s** | **+57,1 %** | — |
| **ambas** | **4,494 s** | **+136,4 %** | 244 · 234.398.000 B · 0,487 s |

Lecturas defendibles y sus límites:

- el hash de imágenes es la parte **barata**: 0,49 s de 1,0 s de sobrecoste. Lo caro es el
  ida-y-vuelta del evento de depuración, ~250 por proceso;
- el prototipo del hook carga su inventario de 46.316 entradas normalizando cada ruta con
  `realpath`, lo que cuesta unos 10 s de arranque **fuera** del tiempo interno medido. Una
  implementación real precomputaría el conjunto normalizado; **ese coste de arranque no se atribuye
  al gate**, y por eso no aparece en la tabla;
- la carga medida es de importación intensiva. Un workload de cómputo largo diluiría el porcentaje,
  y uno de arranques repetidos lo empeoraría. **El porcentaje no generaliza.**

Opciones:

- **Asumir el coste (recomendada).** El arnés calibra un entorno objetivo de 4 CPU y 8 GB; duplicar
  el tiempo de un intento alarga la calibración, no falsea su resultado, **siempre que el mismo gate
  esté puesto en todos los intentos comparados**.
- **Atestiguar sólo imágenes fuera del TCB de Windows.** Hashear `ntdll.dll` y `kernel32.dll` en
  cada intento aporta poco si el TCB de §4.2, punto 5 ya los declara confiables. Reduciría las 246
  imágenes a las del árbol candidato. Exige fijar antes esa frontera, que es §7.2.
- **Gate sólo en un intento de control por unidad.** Barato y **no aprobable**: un plantado
  transitorio elegiría los intentos sin gate, así que esta variante **no cierra la frontera** y por
  eso §10.1 la excluye del texto de OK. Se conserva sólo para dejar constancia de que se evaluó.

Recomendación: **asumir el coste**, y evaluar la segunda opción como optimización posterior una vez
fijada la frontera del TCB. Se registra explícitamente que **el número de referencia de cualquier
cap
o geometría debe medirse con el gate puesto**, no sin él; comparar un intento con gate contra un
baseline sin gate sería comparar dos cosas distintas.

## 8. Controles negativos preespecificados

Cada uno sigue el protocolo del runbook: verde → defecto mínimo → **rojo por la causa prevista, no
por una precondición** → restauración byte-exacta verificada por SHA → verde. Ninguno se restaura
con `git checkout --`.

### 8.1 Contrato acotado (0-a): piezas 1, 2 y 3

| Oráculo | Defecto mínimo | Rojo esperado |
|---|---|---|
| lease efectivo | abrir un archivo leaseado para escritura desde otro handle | `winerror=32`; vacuidad: sin lease la misma apertura da `OK` |
| cobertura del conjunto | quitar un archivo del **adquisidor**, nunca del inventario esperado | igualdad exacta roja nombrando el archivo omitido |
| cobertura inversa | añadir un archivo no catalogado que **permanece** | igualdad exacta roja por alta no declarada |
| **plantado transitorio de DLL** | plantar una DLL, **cargarla** y retirarla antes de la quiescencia | rojo por el gate síncrono **pese a un censo final limpio**, con el proceso terminado por el gate y **ningún** marcador ejecutado; vacuidad: sin gate el marcador **aparece** |
| **callback TLS de una imagen no inventariada** | DLL con `DllMain` **y** callback TLS, cada uno con su propio marcador | ambos marcadores **ausentes**. Vacuidad obligatoria en dos pasos: sin gate aparecen los dos, y **parcheando sólo el entry point el marcador TLS aparece igual** — un control que se conforme con `ERROR_DLL_INIT_FAILED` **nace verde** |
| **plantado transitorio de `.py`** | plantar un módulo bajo un nombre importable y retirarlo | rojo por D-LEA-12b; la atestación de imágenes **no** puede ser la causa, porque no hay imagen PE |
| **plantado transitorio de ZIP importable** | añadir un ZIP importable a una raíz declarada, importarlo y retirarlo | rojo por D-LEA-12b. **El control debe leer el registro de violaciones**: el fallo se presenta como `ModuleNotFoundError`, no como `PermissionError` |
| **`.dist-info` plantado** | añadir un `.dist-info` y consultar `importlib.metadata.version` | rojo por el **registro** de D-LEA-22 antes de que la versión falsa entre en la evidencia; medido que la excepción **no** llega al consumidor y que `version()` devuelve `None` |
| **carga nativa que elude CPython** | helper nativo que llama `LoadLibraryEx` con ruta absoluta o `LOAD_WITH_ALTERED_SEARCH_PATH` | rojo por el gate síncrono de D-LEA-12, no por D-LEA-11 |
| **lectura nativa que elude ambas piezas** | `CreateFileW` por `ctypes` + `exec(compile(src,'<memoria>'))` | **verde por diseño**, y el control existe para **fijar el límite declarado** de §3.8: no lo ve D-LEA-12b, y tampoco D-LEA-12, porque no se carga imagen nueva. Si algún día se pone rojo, la promesa creció y hay que reescribirla |
| independencia de enumeraciones | inyectar el defecto sólo en el helper del adquisidor | rojo; si queda verde, las dos enumeraciones no eran independientes |
| hash por handle | doble que hace **fallar toda reapertura por ruta** | rojo si el digest se obtuvo reabriendo; sin ese doble el defecto **nace verde** |
| orden | adquirir el lease **después** del primer hash | invariante de orden roja antes de READY |
| fail-closed | mantener un escritor vivo sobre un input al lanzar el preflight | `preflight_rejected`; cero tokens START |
| liberación | forzar el fallo de un `CloseHandle` | clasificación propia de fallo de liberación; **nunca** evidencia `success` |
| promoción | matar el supervisor entre validación provisional y promoción | sin `attempt.json` de éxito; parciales censados |
| **relectura post-release** | mutar el material vivo inmediatamente después del release | **un único** terminal coherente |
| **sustitución durable autoconsistente** | reemplazar `attempt.json` y sus artefactos por un conjunto falso pero coherente | rojo por la raíz anclada de D-LEA-17c |
| **`pycache_prefix`** | plantar un `.pyc` **después** de la comprobación de vacuidad y **demostrar primero que su marcador se ejecutó** | rojo por carga del `.pyc`, no por la precondición del entrypoint |
| **alta en el `pycache_prefix`** | crear un archivo en el prefijo con el intento en curso, desde un hijo con token **Low** | rojo por el sello de altas de D-LEA-10; vacuidad: sin sello, el hijo Low **lo crea** |
| **drenaje del puerto de depuración** | cerrar el Job y esperar la terminación **sin** consumir los eventos pendientes | `WaitForSingleObject` devuelve `0x102` sobre un proceso ya terminado; drenado el puerto, queda **señalizado**. Sin este control, D-LEA-21 no tiene oráculo |
| **contaminación entre intentos** | reutilizar el hilo depurador sin drenar entre dos intentos | eventos del intento anterior aparecen en el censo del siguiente |
| ADS | crear un stream alterno en un elemento del conjunto | rojo por stream no predeterminado |
| volumen | declarar material en un filesystem no calificado | rojo por matriz de volumen |
| no-follow | interponer la junction **exactamente entre la inspección y el `CreateFileW`** | rojo que **desaparece** al restaurar `FILE_FLAG_OPEN_REPARSE_POINT`; una junction puesta antes se pone roja por D-LEA-3 aunque se retire la flag, y por eso no prueba nada |
| portabilidad | importar un módulo sólo-Windows en cuerpo de módulo | `test_readiness_h9r_portabilidad.py` rojo nombrando archivo y módulo |

### 8.2 Blocker diferido `candidate_process_memory_isolation_unimplemented` (0-b)

Estos controles **no** forman parte del contrato acotado; se preespecifican para la enmienda del
blocker diferido, con lo ya medido en §0.6–§0.7. Se conservan aquí para que ese trabajo no arranque
de cero, y para que quede escrito por qué el endurecimiento posterior **no** basta.

| Oráculo | Defecto mínimo | Rojo esperado |
|---|---|---|
| **carrera de handles (F1)** | un tercero Medium abre el descendiente **antes** del endurecimiento y **retiene** el handle | el handle cacheado **sigue inyectando** tras el endurecimiento —medido: 29 bytes escritos con un `OpenProcess` nuevo ya en `DENEGADO(5)`—. Es el control que demuestra que endurecer después **no cierra 0-b**; sólo un broker que fije el descriptor en la creación lo pondría verde |
| **puerta trasera del supervisor (F2)** | inyectar el proceso supervisor, o `PROCESS_DUP_HANDLE` sobre él, y usar el handle duplicado contra el candidato | inyección **PERMITIDA** mientras el supervisor no se endurezca, pese a cualquier DACL del candidato. Vacuidad: con el supervisor endurecido y `PROCESS_DUP_HANDLE` denegado sobre él, la duplicación falla |
| **inyección en memoria** | `VirtualAllocEx` + `WriteProcessMemory` + relectura contra el candidato real desde un proceso Medium | con 0-b **completo** (broker + supervisor endurecido): `DENEGADO (5)`. Vacuidad: sin descriptores, la escritura se completa y los bytes se releen |
| **el árbol, no la raíz** | inyección y suspensión contra **cada proceso descendiente**, no sólo el PID lanzado | con 0-b completo: `DENEGADO (5)` en los tres. Vacuidad: sin cerrar la creación, los tres quedan `PERMITIDOS`. Un control que sólo mire la raíz **nace verde** —el error de la sexta redacción— |
| **secuestro de un hilo POSTERIOR** | `SetThreadContext` sobre un hilo creado después de arrancar | con 0-b completo: `DENEGADO (5)`. Vacuidad: con sólo `lpThreadAttributes` en la raíz **tiene éxito** |
| **máscara del supervisor** | en la DACL de proceso, conceder `PROCESS_QUERY_INFORMATION` (`0x0400`) en vez de `PROCESS_QUERY_LIMITED_INFORMATION` (`0x1000`) | rojo con `winerror 5` en **exactamente tres** aperturas —`process_integrity_level`, la previa a `assign_to_job` y `process_metrics`—; los **dos** caminos de hilo quedan **verdes** e `IsProcessInJob` **no se alcanza**. Exigir «seis rojos» contradiría §0.4 |
| **recuperación por el dueño** | reabrir el candidato con `WRITE_DAC` y reescribir su DACL | con `OWNER RIGHTS`: `DENEGADO (5)`. Sin él, la reescritura tiene éxito y devuelve la inyección |

Tres notas que la experiencia de esta sesión obliga a dejar escritas:

1. El control de `pycache_prefix` necesita la nota explícita de siempre: el entrypoint vivo aborta
   con
   `SystemExit` si falta `-I -B -S -X pycache_prefix=<dir fresco vacío>` **antes** de cargar el
   tooling, así que un control que se limite a retirar la bandera se pone rojo por la precondición.
2. **Todo control que use un marcador escrito por el candidato debe crear ese marcador en una raíz
   con etiqueta Low.** Un marcador en un directorio de integridad Media **nunca aparece**, y el
   control queda verde por `NO_WRITE_UP` en vez de por el oráculo. Ocurrió al medir §3.7.
3. **Todo control que parchee memoria del candidato debe indexar handles por PID.** El intérprete
   real es un segundo proceso (§4.2); parchear en el lanzador da `winerror 998` y el control queda
   verde por un error de puntería.

## 9. Qué NO hace esta enmienda

- No autoriza START, S0, S1, S2, workloads ni entrypoints calificables.
- No fija la fingerprint humana ni consume autorización alguna.
- No materializa fixtures, unidades ni valores finales.
- No fija caps, geometrías, budgets, disco ni perfiles.
- No toca hardware/cloud, metodología de riesgo, API pública, PyPI, tags, releases ni la demo.
- No reabre D-RDY-ABA, D-RDY-H9R ni ninguna decisión aprobada.
- No retira `qualifying_boundary_adapters_unavailable` ni
  `multiprocess_native_pool_observer_unimplemented`.
- No cierra la inyección en memoria: la difiere a `candidate_process_memory_isolation_unimplemented`
  como blocker propio, con la medición de §0.6–§0.7 conservada para esa enmienda.

## 10. Texto exacto para el OK

La séptima redacción intentó una plantilla por ramas, y la quinta revisión adversarial mostró que
**seguía admitiendo combinaciones no implementables**: aprobaba D-LEA-12 —atestiguar cada imagen— y
a la vez dejaba elegir «atestiguar sólo fuera del TCB» aunque ese TCB no queda fijado si se difiere
D-LEA-13; permitía responder «no» a §7.3 aunque §4.1 incluye las evidencias de campaña de forma
incondicional; y dejaba la variante C sin rama firmable. Se reescribe cerrando esos huecos, y con
0-a como escenario recomendado el árbol de ramas se simplifica: **0-b ya no es un camino de este
OK**, sino un blocker diferido.

### 10.1 Combinaciones que **no** son válidas

| Combinación | Por qué no |
|---|---|
| **B** de §7.1 junto con D-LEA-9 | B **sustituye** D-LEA-9; aprobar ambas es contradictorio |
| **0-b** por este OK | medido como rediseño (§0.6, §0.7); se difiere a `candidate_process_memory_isolation_unimplemented`, no se aprueba aquí |
| **atestiguar sólo fuera del TCB** (§7.7) junto con **diferir** (§7.2) | esa optimización necesita la frontera del TCB de §4.2 fijada, que es exactamente lo que D-LEA-13 declara; sin «incluir ahora» no hay TCB que excluir |
| **§7.3 = no** | §4.1 incluye las evidencias de campaña en el conjunto congelado de forma incondicional; «no» las sacaría del lease y contradiría §4.1. La respuesta está fijada en **sí** y §7.3 deja de ser una casilla abierta |
| **variante C** de §7.1 | §6.2 la descarta por corrección (una venv no es relocalizable); **no tiene rama firmable** y no se ofrece en el texto |

### 10.2 Texto para aprobar (escenario recomendado: 0-a)

> Fijo el modelo de amenaza de `_ENMIENDA-LEASE-MATERIAL-CANDIDATO.md` en **0-a** de §7.0 y el
> camino
> **aprobar ahora** de §7.6, con la variante **\<A | B\>** de §7.1 y la opción
> **\<incluir ahora | diferir\>** de §7.2.
>
> Apruebo D-LEA-1…D-LEA-8, D-LEA-10, D-LEA-11, D-LEA-12, D-LEA-12b, D-LEA-14…D-LEA-19, D-LEA-21 y
> D-LEA-22, con D-LEA-17b y D-LEA-17c. D-LEA-0 queda fijada en **0-a** y la línea de §12.1 se
> reescribe para prometer consistencia en disco, no «nadie». **D-LEA-20 no se aprueba**: la
> inyección en memoria se difiere a `candidate_process_memory_isolation_unimplemented`.
>
> Con **A** apruebo además D-LEA-9; con **B**, D-LEA-9 queda **retirada** y en su lugar autorizo al
> arnés a sellar directorios del operador.
> Con **incluir ahora** apruebo además D-LEA-13, y en §7.7 elijo
> **\<asumir el coste | atestiguar sólo fuera del TCB de Windows\>**; con **diferir**, D-LEA-13
> queda
> **fuera**, se abre `candidate_interpreter_closure_undeclared` como blocker propio y §7.7 queda
> fijada en **asumir el coste**, porque «atestiguar sólo fuera del TCB» exige la clausura incluida.
>
> Respondo **\<sí | no\>** a §7.5. §7.3 queda fijada en **sí** por §4.1.
>
> Autorizo implementar, probar y revisar el mecanismo dentro del arnés. No autorizo START, S0, S1,
> S2, workloads, entrypoints calificables, fingerprint humana, fixtures definitivos, valores
> finales, hardware/cloud, metodología, API, PyPI, tags, releases ni recaptura de demo.

### 10.3 Texto para reordenar la cola

> No apruebo todavía `_ENMIENDA-LEASE-MATERIAL-CANDIDATO.md`. Elijo **reordenar** en §7.6: la
> frontera queda abierta y medida, y el esfuerzo pasa a
> `multiprocess_native_pool_observer_unimplemented`. Ninguna decisión D-LEA queda aprobada.

> **Nota histórica.** §10.3 quedó **sin ejercer**: Cami firmó §10.2 (0-a) el 2026-08-22. Se conserva
> el texto por procedencia, no como opción vigente.

## Anexo A — plan de implementación por capas (0-a)

> Añadido tras la firma del 2026-08-22. Es el **puente entre el diseño aprobado y el código**: no
> reabre ninguna D-LEA. Traduce las decisiones al árbol vivo (OID `d6d69e29…`), fija el **orden de
> capas** y ata cada capa a su control negativo de §8.1. Los números de línea citados son del árbol
> a la firma y se **re-miden al abrir la sesión de cada capa** antes de tocar nada.

### A.0 Invariantes que rigen toda la implementación

- **Un solo writer.** Codex es revisor read-only; su revisión adversarial se solicita al cerrar cada
  capa, nunca `/codex:rescue` mientras Claude sea writer.
- **Nada de START.** Ninguna capa ejecuta START, S0, S1, S2, workloads ni entrypoints calificables;
  no fija fingerprint; no materializa fixtures, unidades ni valores finales. Todo se ejerce con
  dobles sintéticos, Jobs vacíos y árboles de prueba bajo `tmp_path`, como el arnés vigente.
- **La puerta global no se mueve hasta A.4.** `CANDIDATE_EXECUTION_MATERIAL_LEASE_AVAILABLE`
  ([supervisor.py:159](../../scripts/readiness_h9r/supervisor.py)) permanece `False` mientras las
  piezas 1–3 no estén implementadas y con sus controles negativos verdes. El catálogo sigue
  declarando `candidate_execution_material_lease_unimplemented`: es honesto, no una regresión.
- **Portabilidad.** Todo módulo nuevo con símbolos sólo-Windows se importa de forma perezosa/gateada
  para que `test_readiness_h9r_portabilidad.py` siga verde en Linux/macOS. El arnés debe seguir
  importable donde no hay WinAPI.
- **Control negativo real por capa**, con el protocolo del runbook §6: verde → defecto mínimo → rojo
  **por la causa prevista** → restauración **byte-exacta verificada por SHA** desde copia en
  `%TEMP%\nkr` → verde. **Nunca `git checkout --`.**
- **Serialización de suites.** No se edita ningún archivo mientras corre una suite H9R, ni se lanzan
  spikes que creen procesos en paralelo a ella.
- **Gates focales por capa** (runbook §5.1): `pytest` de `test_readiness_h9r_*.py`, `mypy --strict`
  sobre `scripts/measure_readiness_h9r.py scripts/readiness_h9r`, `ruff check`/`format --check`
  focales, y el gate de copy/catálogo bidireccional. Gates integrales y CI 16/16 al cerrar A.4.

### A.1 Capa 1 — Pieza 1, lease anti-sustitución

Cubre **D-LEA-1…D-LEA-9** (variante A: se mantiene D-LEA-9) más **D-LEA-14** (ADS) y **D-LEA-15**
(matriz de volumen). Es la pieza mejor medida (§2) y **aditiva**: se construye el primitivo y sus
tests antes de cablearlo, sin perturbar el flujo vivo.

- **Módulo nuevo** `scripts/readiness_h9r/material_lease.py` (`windows_share_mode_lease_v1`): handle
  por archivo `GENERIC_READ | FILE_SHARE_READ | OPEN_EXISTING | FILE_FLAG_OPEN_REPARSE_POINT`; por
  directorio, además `FILE_FLAG_BACKUP_SEMANTICS`. Adquisición **parent-first** (D-LEA-4), **falla
  cerrado** (D-LEA-3), hash **por el handle retenido** (D-LEA-7), lease **antes** del primer hash
  (D-LEA-8), cotejo por **volumen + file ID** reutilizando el patrón de `_same_file_version`
  ([adapters.py:335](../../scripts/readiness_h9r/adapters.py), [artifacts.py:218](../../scripts/readiness_h9r/artifacts.py)).
- **Inventario canónico por entrada (D-LEA-5, D-LEA-6):** extender el manifiesto y
  `canonical_tree_identity` ([artifacts.py:1149](../../scripts/readiness_h9r/artifacts.py)) para que
  conserve la lista de entradas ligada al digest agregado ya existente, con **enumeraciones
  independientes** para adquirir y cotejar.
- **Cableado (A.1c):** `run_preflight` ([supervisor.py:3070](../../scripts/readiness_h9r/supervisor.py))
  adquiere el lease **antes** del primer hash; `_revalidate_preflight`
  ([supervisor.py:3633](../../scripts/readiness_h9r/supervisor.py)) lo mantiene vivo hasta la
  quiescencia. Reutilizar la rama de auto-herencia de
  [`runtime_snapshot.py`](../../scripts/readiness_h9r/runtime_snapshot.py) sólo si hiciera falta DACL;
  la variante A **no** toca descriptores ajenos (D-LEA-9).
- **Controles negativos (§8.1):** lease efectivo · cobertura del conjunto · cobertura inversa ·
  independencia de enumeraciones · hash por handle · orden · fail-closed · ADS · volumen · no-follow.
- **Nota de portabilidad:** `material_lease.py` sólo-Windows; el import queda gateado. Añadir a
  `test_readiness_h9r_portabilidad.py` la comprobación de que su cuerpo de módulo no rompe en Linux.

### A.2 Capa 2 — Pieza 2, anti-inyección

Cubre **D-LEA-10, D-LEA-11, D-LEA-12, D-LEA-12b, D-LEA-13, D-LEA-21, D-LEA-22**. Es la capa más
delicada (retiene handles del kernel, crea el candidato bajo depurador). Se subdivide:

- **A.2a — sello del `pycache_prefix` (D-LEA-10).** Extender `_validate_pycache_isolation`
  ([adapters.py:3191](../../scripts/readiness_h9r/adapters.py)): sello contra
  `FILE_ADD_FILE|FILE_ADD_SUBDIRECTORY|FILE_DELETE_CHILD` durante todo el intento y atestación de
  vacuidad **al cierre**, no sólo antes. Controles §8.1: `pycache_prefix` y alta en el prefijo.
- **A.2b — clausura de búsqueda de DLL (D-LEA-11).** Clausura explícita en el bootstrap del
  candidato (sólo system dir + directorios leaseados). Control §8.1: carga nativa que elude CPython
  (rojo por D-LEA-12, no por D-LEA-11).
- **A.2c — audit hook PEP 578 (D-LEA-12b) + fallar sobre el registro (D-LEA-22).** Hook instalado
  por el bootstrap antes de correr código del candidato; rechaza `open/import/exec/compile` sobre
  entradas no inventariadas de raíces declaradas; **registra cada violación** y el intento falla
  cerrado sobre el registro (medido: `importlib.metadata.version()` se traga la excepción, §3.9).
  Controles §8.1: `.py`/ZIP/`.dist-info` plantados, y **lectura nativa que elude ambas piezas**
  (verde por diseño — fija el límite declarado).
- **A.2d — gate de imágenes por depuración (D-LEA-12) + drenaje (D-LEA-21).** Crear el árbol con
  `DEBUG_PROCESS` desde [windows_sandbox.py:730](../../scripts/readiness_h9r/windows_sandbox.py),
  indexar handles **por PID**, hashear desde el `hFile` del evento, **terminar** el proceso que
  carga una imagen no inventariada antes de `ContinueDebugEvent`; el bucle vive en el hilo creador y
  **drena el puerto** hasta `EXIT_PROCESS` (D-LEA-21). Controles §8.1: plantado transitorio de DLL,
  callback TLS, carga nativa, drenaje del puerto, contaminación entre intentos.
- **A.2e — clausura del intérprete declarada (D-LEA-13).** Añadir al manifiesto candidato
  ([contracts.py](../../scripts/readiness_h9r/contracts.py)) los cinco términos de §4.2, incluida la
  frontera explícita del TCB de Windows, y sumarla al conjunto congelado.

### A.3 Capa 3 — Pieza 3, anti-falso-éxito

Cubre **D-LEA-16, D-LEA-17, D-LEA-17b, D-LEA-17c, D-LEA-18**. Máquina de estados
**provisional → release → promoción** en la publicación de evidencia; ningún paso posterior al
release relee material vivo.

- **Sitios:** `_attempt_summary` y `validate_campaign_progress`
  ([aggregate.py:498](../../scripts/readiness_h9r/aggregate.py),
  [aggregate.py:299](../../scripts/readiness_h9r/aggregate.py)) hoy revalidan con
  `verify_artifacts=True` contra artefactos vivos; pasan a validar la **atestación e inventario
  congelados** (D-LEA-17b). La promoción produce un **paquete durable content-addressed** anclado
  **fuera** del workdir mutable (D-LEA-17c).
- **Controles negativos (§8.1):** liberación · promoción · relectura post-release · sustitución
  durable autoconsistente.

### A.4 Capa 4 — integración y cierre de la frontera

Sólo cuando A.1–A.3 estén verdes con sus controles:

- **Flip de capacidad (D-LEA-19):** `CANDIDATE_EXECUTION_MATERIAL_LEASE_AVAILABLE = True` y añadir la
  constante y el blocker `candidate_process_memory_isolation_unimplemented` (0-b diferido) más
  `candidate_interpreter_closure_undeclared`/`trusted_harness_interpreter_closure_undeclared` (§7.5)
  en [supervisor.py:156-172](../../scripts/readiness_h9r/supervisor.py) y su
  `CALIBRATION_START_DISABLED_REASON`. La puerta **no baja de blockers**: uno se sustituye por otro.
- **Copy/catálogo:** actualizar el gate bidireccional
  ([copy_gate.py](../../scripts/readiness_h9r/copy_gate.py)) para el nuevo censo de blockers.
- **§12.1** de [`_PROPUESTA-CALIBRACION-H9R-PRE-START.md`](_PROPUESTA-CALIBRACION-H9R-PRE-START.md):
  reescribir la línea para prometer **consistencia en disco**, no «nadie» (D-LEA-0/0-a).
- **`DECISIONES-VIGENTES.md`:** cerrar la fila D-LEA de «implementación en curso» a «implementada»,
  con sus gates.
- **Cierre integral:** gates completos, control negativo del catálogo, commit público, CI 16/16 job
  a job, deploy, y actualización del `HANDOFF` privado.

### A.5 Orden y por qué

A.1 primero por ser aditiva y mejor medida; A.2 después porque es donde vive el riesgo (handles del
kernel, depurador); A.3 puede avanzar en paralelo conceptual pero se integra tras A.2; A.4 al final
para que la puerta global refleje un mecanismo **real**, nunca una promesa. Cada capa merece su
propia sesión con contexto fresco: es código de seguridad de proceso, no un refactor mecánico.
