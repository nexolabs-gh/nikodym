# Enmienda propuesta — congelación continua del material de ejecución candidato

> **Estado: PROPUESTA. No aprobada. No implementada.** Quinta redacción. Las tres primeras fueron
> sometidas a **tres** revisiones adversariales independientes que devolvieron **NO SHIP**; la quinta
> incorpora además una medición que Cami pidió antes de fijar el alcance (§0) y **todavía no ha
> pasado por revisión adversarial**: hacerlo es tarea de la sesión siguiente. Los dieciséis hallazgos están verificados uno a uno contra el árbol vivo e incorporados:
> dos resultaron **confirmados en su efecto pero falsos o sobreextendidos en el mecanismo alegado** y
> se corrigen con medición en §3.4; dos eran **errores propios de medición** y se remidieron en §2.6;
> y el último obligó a **acotar el modelo de amenaza** en §0, porque la promesa que las tres
> redacciones anteriores hacían es inalcanzable con el diseño de proceso vigente.
>
> **Esta redacción no pide el OK todavía.** Su recomendación es medir dos incógnitas acotadas y
> volver (§7.6). Lo que sí necesita ahora es la decisión de alcance de §7.0.
>
> Cierra por diseño la frontera `candidate_execution_material_lease_unimplemented` catalogada en
> [`_PROPUESTA-CALIBRACION-H9R-PRE-START.md`](_PROPUESTA-CALIBRACION-H9R-PRE-START.md) §12.1. Este
> texto **no autoriza** START, S0, S1, S2, workloads, entrypoints calificables, fingerprint humana,
> fixtures definitivos ni valores finales. No toca hardware/cloud, metodología, API pública, PyPI ni
> la demo.
>
> El OK del 2026-08-13 autorizó implementar, probar y revisar **el arnés**. Lo que aquí se propone
> excede ese OK en tres puntos que por eso vuelven a Cami: el arnés pasaría a **retener handles del
> kernel** —y, en una variante, a **modificar descriptores de seguridad**— sobre rutas propiedad del
> operador y fuera del workdir; el manifiesto candidato **ganaría declaraciones obligatorias
> nuevas**; y la publicación de evidencia **cambiaría de un paso a dos**. El código vigente rechaza
> hoy la primera frontera de forma explícita: `_seal_windows_snapshot_directories` documenta que
> sella «sólo dirs harness-owned; nunca el checkout vivo ni telemetría».
>
> Decisiones propuestas: **D-LEA-0** y **D-LEA-1…D-LEA-19**, más **D-LEA-12b**, **D-LEA-17b** y
> **D-LEA-17c** que añaden las revisiones adversariales. Enmienda a
> [`_PROPUESTA-CALIBRACION-H9R-PRE-START.md`](_PROPUESTA-CALIBRACION-H9R-PRE-START.md) §12 y §12.1;
> no modifica D-RDY-ABA ni D-RDY-H9R.

## TL;DR y recomendación ejecutiva

Hoy el arnés **verifica** el material candidato por hash y lo vuelve a verificar justo antes de
START, pero **no lo congela**. Entre la última verificación y el momento en que el candidato lee o
ejecuta esos bytes hay una ventana en la que cualquier proceso del mismo usuario puede sustituirlos
en sitio: medido, sobrescribir un archivo ya censado es **PERMITIDO** aun con el directorio padre
sellado, y el SHA cambia. La evidencia firmada atestiguaría un digest que ya no describe los bytes
ejecutados.

Congelar exige **tres piezas**, no una. La primera redacción de esta enmienda proponía sólo la
primera y por eso fue rechazada:

1. **Anti-sustitución — `windows_share_mode_lease_v1`.** Un handle del kernel por archivo, sin
   seguir reparse points y con `FILE_SHARE_READ` como único modo compartido. Medido: bloquea
   escritura, borrado, renombre, reemplazo y el handle de escritura para *mapping*; no estorba
   lecturas, ni la carga de imagen del ejecutable, ni el import de un árbol completo con `.pyd` y
   DLL; falla cerrado si alguien ya lo tiene abierto para escribir; y el kernel lo libera solo si el
   arnés muere.
2. **Anti-inyección — clausura declarada y gate síncrono sobre lo que se carga.** El lease impide
   cambiar lo que existe, **no** impide **añadir**. Y un plantado **transitorio** —crear, dejar que
   se cargue, retirar antes de la quiescencia— deja el censo final limpio. Detectar después no es
   prevenir. Son **dos canales distintos**: el del cargador de Windows, que se ataja con un gate
   anterior a la ejecución de cada imagen, y el del import machinery de Python —`.py`, ZIP
   importable, `.dist-info`—, que no produce imagen PE y necesita pieza propia.
3. **Anti-falso-éxito — provisional, release, promoción.** El código vivo publica `attempt.json` y
   **después** lo revalida contra artefactos vivos. Liberar antes deja esa revalidación sobre
   material mutable; liberar después deja publicado un `success` si un `CloseHandle` falla. Y los
   consumidores durables tampoco pueden reabrir material vivo.

Tres variantes de frontera siguen siendo mutuamente excluyentes para la pieza 1:

| | Qué hace | Muta estado del operador | Coste medido |
|---|---|---|---|
| **A — lease puro en sitio** | handles de sólo lectura sobre archivos y directorios declarados | **no** | +5,9 % a +28,4 % sobre el hash que ya se paga |
| **B — lease + sello DACL en sitio** | A, más ACE de denegación sobre directorios del operador | **sí**, y persiste si el arnés muere de forma dura | A + 0,089 ms/dir |
| **C — snapshot sellado** | copia el material a árbol propio, lo sella y ejecuta la copia | no | copia por intento; rompe la identidad declarada |

**Recomendación: A + las piezas 2 y 3, que son obligatorias en cualquier variante.** B no es la
diferencia importante: no cubre el plantado transitorio ni las altas dentro del propio workdir, y a
cambio deja una DACL ajena alterada si el supervisor muere mal. Sin la pieza 2, **ninguna variante
cierra la frontera** y esta enmienda no debe aprobarse.

**Estado honesto de la pieza 2.** Su mecanismo central está propuesto pero **sin medir**: no se ha
medido si `DEBUG_PROCESS` convive con el token Low, el Job con `KILL_ON_JOB_CLOSE` y el arranque
suspendido que el arnés ya usa, ni si `LOAD_DLL_DEBUG_EVENT` llega antes del `DllMain` de la DLL
cargada. Por eso **la recomendación de §7.6 es medir primero y aprobar después**, no aprobar ahora.

Antes que nada está §0, ahora **medido**: con el diseño vigente un proceso Medium del mismo usuario
sí puede inyectar código en la memoria del candidato sin tocar archivos —`PERMITIDO`, medido, no
inferido—, y esa vía **se cierra sin privilegios de administrador** con una DACL restrictiva más un
ACE de `OWNER RIGHTS`. La DACL sola no sirve: el dueño la reescribe y recupera la inyección. Por eso
la recomendación de §7.0 pasó de acotar la promesa a **cerrar también la vía de memoria**.

Hay además dos hallazgos que Cami decide aparte: el manifiesto candidato **no identifica hoy el
intérprete que realmente corre** (§4.2), y el runtime del propio arnés tiene la misma brecha en la
otra mitad del sistema (§4.3).

## 0. Modelo de amenaza — medido, no supuesto

Las tres redacciones anteriores prometían que **«nadie»** pudiera sustituir el material. Una revisión
adversarial objetó, **por inferencia**, que un proceso Medium del mismo usuario puede inyectar código
en la memoria del candidato sin tocar archivos. Se midió, y además se midió si esa vía puede
cerrarse. Ambas respuestas son afirmativas.

### 0.1 La vía existe: está medida, no inferida

El arnés crea el candidato con un duplicado del token del propio proceso al que sólo le baja la
etiqueta de integridad, y `CreateProcessAsUserW` recibe descriptores de seguridad **nulos** para
proceso e hilo, de modo que el objeto proceso hereda la DACL por defecto del token. La integridad
obligatoria es `NO_WRITE_UP`: protege a Medium **de** Low, no al revés.

Medido sobre un hijo inerte creado igual que hoy —descriptor nulo—, abriendo desde un proceso Medium
del mismo usuario:

| Derecho solicitado | Resultado |
|---|---|
| `PROCESS_VM_WRITE \| PROCESS_VM_OPERATION \| PROCESS_CREATE_THREAD` | **PERMITIDO** |
| `WRITE_DAC` | **PERMITIDO** |

Con el diseño de proceso vigente, la inyección directa en memoria está disponible, no produce
`LOAD_DLL_DEBUG_EVENT`, no pasa por el import machinery y no toca ningún archivo: ninguna de las tres
piezas la vería.

### 0.2 La vía **se puede cerrar sin administrador**

Se midió si una DACL restrictiva en `lpProcessAttributes` cierra esa vía, y qué pasa cuando el dueño
intenta recuperarla:

| Escenario | Inyección | `WRITE_DAC` | `WRITE_OWNER` | Derechos del supervisor |
|---|---|---|---|---|
| descriptor nulo, como hoy | PERMITIDO | PERMITIDO | — | PERMITIDO |
| DACL restrictiva simple | **DENEGADO** (5) | PERMITIDO | DENEGADO (5) | **PERMITIDO** |
| …y el dueño reescribe la DACL | **PERMITIDO otra vez** | — | — | — |
| DACL restrictiva **+ `OWNER RIGHTS` (S-1-3-4)** | **DENEGADO** (5) | **DENEGADO** (5) | **DENEGADO** (5) | **PERMITIDO** |

Las dos filas centrales son el hallazgo. Una DACL restrictiva **sola es inútil**: el dueño conserva
`WRITE_DAC` por derechos implícitos de propietario, reescribe el descriptor —se midió, `status=0`— y
recupera la inyección. Añadir un ACE de `OWNER RIGHTS` que no conceda `WRITE_DAC` cierra esa vuelta,
y el supervisor conserva `PROCESS_TERMINATE`, `PROCESS_SET_QUOTA`, `PROCESS_QUERY_INFORMATION`,
`PROCESS_VM_READ`, `SYNCHRONIZE` y `READ_CONTROL`, que es lo que necesita para asignar el Job, medir
y terminar el árbol.

**Conclusión: la frontera de proceso es viable sin privilegios de administrador**, y su coste es un
descriptor de seguridad con dos ACE en la creación del candidato. No es el rediseño de alcance mayor
que la revisión adversarial supuso.

### 0.3 Lo que esta medición todavía **no** cubre

Está medido sobre un hijo creado con `CreateProcessW` y un token corriente. **No** está medido:

- la composición con `CreateProcessAsUserW`, el token de integridad Low, el arranque suspendido y la
  asignación al Job que el arnés ya usa;
- el descriptor del **hilo** (`lpThreadAttributes`), que es objeto aparte y que
  `resume_suspended_process` necesita abrir con `THREAD_SUSPEND_RESUME`;
- si la máscara de supervisor probada es exactamente la que el arnés requiere, o si falta alguna
  —`PROCESS_DUP_HANDLE`, por ejemplo—;
- el comportamiento frente a un atacante con `SeDebugPrivilege`, que exige elevación y queda fuera
  del modelo de un mismo usuario no elevado.

### 0.4 Las dos opciones que quedan, ahora con precio

**D-LEA-0 (propuesta, dos variantes).**

- **0-a — acotar la promesa.** Los procesos Medium del mismo usuario quedan dentro del TCB y la
  frontera promete consistencia del material **en disco**. Cierra con lo ya diseñado y no añade
  trabajo.
- **0-b — cerrar también la vía de memoria.** El candidato se crea con DACL restrictiva más
  `OWNER RIGHTS`, y la promesa se mantiene amplia. El coste medido es acotado, pero exige cerrar
  antes las cuatro casillas de §0.3 y añadir controles negativos que intenten `PROCESS_VM_WRITE` y
  `PROCESS_CREATE_THREAD` contra el candidato real.

La elección sigue siendo de Cami (§7.0), pero ya no es entre «acotar» y «un rediseño enorme»: es
entre acotar y un cambio medido en la creación del proceso.

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
   importe tarde puede haber sido sustituido después del rehash. Los inputs se abren cuando el flujo
   los pide, no al validar.
3. **El árbol instalado se rehashea una sola vez**, y un rehash no impide la sustitución: la
   constata más tarde, y sólo si el sustituto sigue allí.

## 2. Semántica medida de la pieza 1

Medido el 2026-08-21 en la torre writer (Windows 11 Pro 10.0.26200, Python 3.12.10 de `.venv`),
sobre archivos sintéticos bajo `%TEMP%\nkr`, una copia de `cmd.exe` y árboles reales de esta
máquina. Ninguna medición ejecutó START, workloads ni entrypoints calificables.

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
elude el lease. Se evalúa, en cambio, **por stream**: el lease del stream por defecto no impide
crear un ADS. Está medido que el stream por defecto conserva su SHA, y que el import de Python lee
el stream por defecto; aun así el censo actual **no enumera streams**, y esa es una brecha de
cobertura real, no una hipótesis (D-LEA-14).

### 2.2 El lease no estorba a la ejecución ni al import

| Prueba | Resultado medido |
|---|---|
| copia de `cmd.exe` sin lease, `/c exit 7` | `returncode=7` |
| misma copia **con lease vivo sobre el ejecutable** | `returncode=7` |
| adquirir el lease con un hijo del ejecutable **ya corriendo** | `OK` |
| lanzar `.venv\Scripts\python.exe` con lease sobre el propio ejecutable | `returncode=0` |
| `import pyarrow` con los 771 archivos de `pyarrow` leaseados | `returncode=0`, versión `24.0.0` |
| `import pyarrow, pandas` con los **46.316** archivos de `site-packages` leaseados | `returncode=0` |

La carga de imagen y la carga de DLL/`.pyd` conviven con `FILE_SHARE_READ`. Era el riesgo técnico
que podía invalidar el mecanismo entero: **no se materializa**.

### 2.3 Falla cerrado en la adquisición

Con un escritor vivo sobre el archivo, adquirir el lease devuelve `winerror=32`; cerrado el
escritor, `OK`. Si el material no puede congelarse, el arnés lo sabe **antes** de START.

Identidad estable tras abrir: `st_ino`/`st_dev` están disponibles en esta torre y reconcilian antes
y después del `CreateFileW`, que es el patrón que ya usa `_same_file_version`.

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

**El sello del directorio no protege el contenido de sus hijos.** Denegar `FILE_DELETE_CHILD` en el
padre tampoco impide borrar un hijo, porque el borrado también se autoriza por el derecho `DELETE`
del propio hijo. Sello y lease no son alternativas: el sello cubre altas y renombres; el lease por
archivo es lo único que cubre sustitución de bytes, borrado y reemplazo.

Un handle de directorio con `FILE_SHARE_READ` sí bloquea renombrar (`winerror=32`) y borrar
(`winerror=32`) el **propio directorio**, que es el vector de interposición por junction. Un handle
de directorio **no** impide crear un hijo nuevo: medido **PERMITIDO**.

### 2.5 Alternativa descartada: ACE de denegación por archivo

Denegar escritura sobre la DACL de cada archivo también impide abrirlo para escritura y sigue
permitiendo leerlo. Se descarta por dos razones medidas:

- **persistencia.** Un handle desaparece cuando el proceso muere; un ACE, no. Un `Stop-Process` del
  supervisor dejaría el árbol del operador con una DACL hostil que él no puso.
- **restauración.** El intento naíf de restaurar la DACL original con `SetKernelObjectSecurity`
  **no** resultó byte-exacto en esta torre: hace falta la rama de auto-herencia
  (`SE_DACL_AUTO_INHERITED` → `SetSecurityInfo`) que `runtime_snapshot.py` ya implementa.

En ese experimento las filas de borrado y renombre quedaron **confundidas** —el handle que sostenía
la DACL no compartía `FILE_SHARE_DELETE`, así que el bloqueo pudo venir del modo compartido y no del
ACE—. La única fila limpia es la de apertura para escritura, y ninguna decisión se apoya en las dos
confundidas.

### 2.6 Coste — contrafactual en el orden obligatorio, sobre mitades gemelas

Dos afirmaciones previas se **retiran** por medir el orden equivocado: «+2,6 s / ~8 %» de la primera
redacción y «+2,2 %» de la segunda. Ambas venían de `hash → lease`, mientras que D-LEA-8 obliga
`lease → hash`. La medición vigente es la siguiente.

Diseño: un árbol frío se parte en dos mitades **gemelas** —reparto alternado en orden de tamaño, que
equilibra a la vez cantidad y bytes—. La mitad **tratada** recibe el orden obligatorio: lease en
frío, hash **con el lease vivo**, liberación. La mitad **control** recibe sólo el hash en frío, que
es el statu quo. Cada celda se mide una sola vez porque «frío» no se repite sobre los mismos bytes.

| Árbol | Mitades | Tratado `lease→hash` | Control `hash` solo | Sobrecoste |
|---|---|---|---|---|
| `C:\Program Files\Git` | 4.757 / 4.757 archivos · 214,4 / 210,8 MB | lease frío 33,479 s + hash 3,165 s + liberación 0,036 s = **36,681 s** | **34,650 s** | **+5,9 %** (+2,0 s) |
| `Python312\Lib\site-packages` base | 1.190 / 1.230 archivos · 27,00 / 27,00 MB | lease frío 0,197 s + hash 0,906 s + liberación 0,024 s = **1,128 s** | **0,908 s** | **+28,4 %** (+0,22 s) |

Lecturas defendibles y sus límites:

- el sobrecoste **es exactamente una apertura más por archivo**. En el brazo de Git el desglose lo
  muestra sin ambigüedad: el primer contacto cuesta ~33,5 s lo pague quien lo pague, y con el lease
  delante el hash posterior baja de 34,7 s a 3,2 s. Congelar y después medir **no** duplica el
  trabajo;
- el porcentaje **no generaliza**: entre +5,9 % y +28,4 % según el tamaño medio de archivo y el
  estado de la caché. Lo que sí es estable es el absoluto: +2,0 s sobre 4.757 archivos y +0,22 s
  sobre 1.190;
- un tercer brazo sobre el árbol de Node quedó **inválido** y se descarta: el reparto por bytes dejó
  un solo archivo de 288 MB en una mitad frente a 2.057 en la otra. Se corrigió el reparto y se
  repitió sobre un árbol frío distinto;
- las celdas son una medición única por cuadro, sin percentiles. No hay p50/p95 y no se afirman.

Coste de recursos con **64.725 handles** simultáneos: pool no paginado 14.560 → 18.640 B, pool
paginado 163.416 → 1.183.320 B, memoria privada 33 → 68 MB, liberación 2,89 s. Retener decenas de
miles de handles es barato.

Sobre el presupuesto: `PREFLIGHT_DEADLINE_SECONDS` vale 300,0 s y el término dominante ya lo paga el
hash actual —34,65 s para 4.757 archivos en frío, **sin** lease—. Extrapolar de aquí a un candidato
real sería inventar: ver §7.4.

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

Por eso la pieza 2 no es opcional: la frontera exige **prevenir la apertura**, o **atestiguar lo
efectivamente cargado**, no comparar dos fotos.

### 3.2 `.pyc` plantado — ya cubierto, y pasa a ser contrato

Con un `.pyc` legítimo y una fuente sustituida después conservando **mtime y tamaño**:

| Invocación | Valor observado |
|---|---|
| sin `pycache_prefix` | `ORIGINA` — **gana el `.pyc` plantado** |
| sólo `-B`, sin `pycache_prefix` | `ORIGINA` — **`-B` no basta**: sólo desactiva la escritura |
| `-B -X pycache_prefix=<dir del arnés>` | `SUSTITU` — el `__pycache__` del árbol se ignora |

El arnés ya lanza candidato, adapter, worker y ui-client con `-I -B -S` y
`-X pycache_prefix=<ruta fresca, vacía y propiedad del arnés>`, y `_validate_pycache_isolation`
comprueba en el ejecutor que `sys.pycache_prefix` sea exactamente esa ruta.

**Pero la bandera no cierra el vector: lo muda de sitio.** El `pycache_prefix` es una de las **tres
raíces escribibles** a las que el arnés aplica etiqueta Low a propósito, y su docstring lo justifica:
si el script candidato reactivara la escritura de bytecode, debe fallar por su propio contrato y no
por un permiso denegado de más. La consecuencia es que **el propio candidato** —y cualquier proceso
del mismo usuario— puede plantar un `.pyc` válido en ese prefijo. Y la comprobación de
`_validate_pycache_isolation` es puntual: exige el directorio **vacío antes de ejecutar**, no vacío
durante toda la corrida. Un `.pyc` plantado después de esa comprobación sería consultado por un
import tardío, no produciría imagen PE y quedaría fuera de D-LEA-12.

Por eso D-LEA-10 no puede limitarse a declarar la bandera: el prefijo es **propiedad del arnés**, así
que sellarlo contra altas cae **dentro** de la frontera vigente y no requiere autoridad nueva sobre
rutas ajenas. Retirarle la etiqueta Low, en cambio, sí cambia el contrato citado en esa docstring.

### 3.3 Módulos Python nuevos — el canal Python **no** está cerrado

La segunda redacción sostenía que «ningún módulo ya congelado importa un nombre que no existía al
congelar». **Es falso, y medido contra el código vivo del producto:**

- `src/nikodym/` contiene **12** `except ImportError` que guardan imports opcionales. Un paquete
  plantado bajo uno de esos nombres **sí** se importaría y ejecutaría, porque el código congelado ya
  contiene el `import` y hoy sólo falla por ausencia;
- `nikodym` consulta `importlib.metadata.version(...)` en al menos seis módulos —`forward/macro.py`,
  `forward/satellite.py`, `stress/engine.py`, `survival/cox_aft.py`, `stability/evaluator.py` y
  `calibration/step.py`, este último para **registrar en la evidencia las versiones ejercidas**—. Un
  `.dist-info` plantado altera esa procedencia sin ejecutar una sola instrucción nueva;
- `candidate_root` permanece en `sys.path` durante todo el workload, así que el descubrimiento sigue
  vivo mucho después del último hash.

Ninguno de esos tres vectores produce necesariamente una **imagen PE cargada**: un `.py`, un ZIP
importable o un `.dist-info` son datos para el import machinery, no módulos del cargador de Windows.
Por eso D-LEA-12, que atestigua imágenes, **no los cubre**, y por eso hace falta D-LEA-12b.

`-I` y `-S` siguen aportando lo suyo: cierran `sys.path` al conjunto declarado y desactivan el
procesado de `.pth`. No cierran el descubrimiento **dentro** de las raíces declaradas.

### 3.4 DLL plantada — el mecanismo alegado por la revisión es falso en este runtime

La revisión adversarial sostuvo que el orden de búsqueda de DLL de Windows incluye el **directorio
de trabajo**, y que como el candidato corre con `staging` —una de sus tres raíces escribibles— como
CWD, una DLL plantada allí se cargaría. **Medido: no ocurre en CPython 3.12.**

Con una copia renombrada de una DLL del sistema, cuyo nombre no existe en `System32`:

| Escenario | Resultado medido |
|---|---|
| DLL en el CWD, carga por nombre | **NO CARGA** |
| DLL en un CWD neutral, carga por nombre | **NO CARGA** |
| vacuidad: carga por **ruta absoluta** | **CARGA** |
| vacuidad: `os.add_dll_directory(dir)` y carga por nombre | **CARGA** |
| `SetDefaultDllDirectories(LOAD_LIBRARY_SEARCH_SYSTEM32)` + `add_dll_directory` | **NO CARGA** |

Las dos filas de vacuidad prueban que la DLL era cargable y que el experimento no está roto. CPython
carga DLL con `LOAD_LIBRARY_SEARCH_DEFAULT_DIRS` desde 3.8: el CWD y el `PATH` no se buscan.

**Alcance exacto de esta refutación.** Vale para las dos rutas primarias de carga de CPython —el
import de extensiones y `ctypes`— y **sólo** para ellas. Una extensión nativa ya cargada puede
llamar `LoadLibrary`/`LoadLibraryEx` por su cuenta, con ruta absoluta, con flags propios o con
`LOAD_WITH_ALTERED_SEARCH_PATH`, y las flags por llamada sustituyen la política del proceso. Decir
que «el vector por CWD no existe en este runtime» sería generalizar más allá de lo medido, y esa
frase se retira. En consecuencia, **D-LEA-11 no es por sí sola una frontera completa**: gobierna los
defaults del proceso y `os.add_dll_directory`, no toda carga nativa.

Lo que **sí** queda vivo, y es el residuo honesto:

- un paquete puede llamar `os.add_dll_directory()` sobre un directorio del árbol candidato —pyarrow
  lo hace— y una DLL **nueva** en ese directorio sí entraría en la búsqueda. El lease impide
  modificar lo existente, no añadir;
- el directorio de la aplicación —el del ejecutable— está siempre en la búsqueda;
- una DLL dependiente de un `.pyd` se resuelve con el directorio del propio `.pyd` en el conjunto.

`SetDefaultDllDirectories(LOAD_LIBRARY_SEARCH_SYSTEM32)` cierra incluso un directorio añadido a
mano, pero rompería a los paquetes que legítimamente lo necesitan. Por eso D-LEA-11 propone
**allowlist explícita de directorios leaseados** y **atestación de imágenes cargadas**, no un
endurecimiento ciego.

### 3.5 Acoplamiento con otra frontera abierta

Atestiguar cada imagen cargada por PID exige recorrer el mismo árbol de procesos que
`multiprocess_native_pool_observer_unimplemented`, que sigue abierta. Se declara el acoplamiento en
vez de duplicar el recorrido.

Conviene no exagerarlo: el instrumental asociado a aquella frontera censa **PID y creation-time**, y
eso **no** aporta la garantía que pide D-LEA-12, que es causal y anterior a la ejecución de cada
imagen. Comparten el recorrido del árbol, no el oráculo.

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

El runtime confiable del arnés no entra aquí: lo congela `materialize_harness_source_snapshot`,
dentro de espacio propio. Ver §4.3 para lo que ese snapshot **no** cubre.

### 4.2 El intérprete del candidato no está declarado

Medido sobre la venv writer, que es el mismo tipo de venv que produciría un candidato con `uv`:

```
executable   ...\.venv\Scripts\python.exe        (274.424 B)
prefix       ...\AppData\Local\Programs\Python\Python312
base_prefix  ...\AppData\Local\Programs\Python\Python312
sys.path     python312.zip · DLLs · Lib · Python312
```

El `python.exe` de la venv es un **lanzador**; el intérprete real —`python312.dll`, `DLLs\*.pyd` y
toda la biblioteca estándar— vive en el prefijo base, **fuera de todo lo que el manifiesto candidato
declara**. Y el bootstrap del candidato antepone `candidate_root` a ese `sys.path`, de modo que la
stdlib del prefijo base se importa de forma perezosa durante todo el workload.

Falta además `pyvenv.cfg`: es el archivo que **decide** cuál es el prefijo base, y se lee antes de
ejecutar código. Sustituirlo cambia el intérprete entero sin tocar ningún archivo del conjunto que
la primera redacción proponía.

Congelar «el ejecutable» de forma honesta exige, entonces, declarar:

1. `pyvenv.cfg` y cualquier archivo de descubrimiento del prefijo;
2. el ejecutable y `python3xx.dll`;
3. `Lib/`, `DLLs/` y el `pythonXY.zip` si existe;
4. la clausura **transitiva** de DLL/`.pyd` que el runtime carga;
5. una **frontera explícita del TCB de Windows**: qué parte del sistema operativo se acepta como
   confiable y por tanto no se congela. Sin esa línea, «clausura completa» no tiene final.

Eso añade declaraciones obligatorias nuevas al manifiesto candidato, y por tanto es contrato.

### 4.3 Hallazgo adyacente: el runtime del propio arnés

`materialize_harness_source_snapshot` congela fuentes e import roots, pero **no** el ejecutable
Python del arnés, ni su `pyvenv.cfg`, ni el prefijo base, ni la stdlib — y el supervisor lanza
worker, adapter y controller con ese Python vivo. Es la misma clase de brecha, en la otra mitad del
sistema, y **está fuera del alcance de esta frontera**. Se declara aquí para que no se pierda, y se
propone abrirla como blocker propio en vez de ampliarla en silencio (§7.5).

## 5. Decisiones propuestas

### Pieza 1 — anti-sustitución

**D-LEA-1.** El material de ejecución candidato queda **congelado de forma continua** desde su
validación hasta la quiescencia del árbol candidato. Congelado significa *nadie puede sustituir,
borrar, renombrar ni reemplazar esos bytes mientras el lease vive*, no *se vuelve a hashear más
veces*.

**D-LEA-2.** El mecanismo es `windows_share_mode_lease_v1`: un handle por archivo, `GENERIC_READ`
con `FILE_SHARE_READ` como único modo compartido y `FILE_FLAG_OPEN_REPARSE_POINT`; y un handle por
directorio con los mismos modos más `FILE_FLAG_BACKUP_SEMANTICS`.

**D-LEA-3.** El lease **falla cerrado**. Si cualquier elemento no puede leasearse —otro proceso lo
tiene abierto para escritura, desapareció, o es un reparse point— el intento se rechaza antes de
START con `preflight_rejected` y no se emite ningún token.

**D-LEA-4.** Los directorios se adquieren **parent-first** y antes que sus archivos, de modo que
ningún ancestro pueda renombrarse mientras se recorre el subárbol.

**D-LEA-5.** El conjunto congelado se coteja contra un **inventario canónico por entrada**, no
contra un agregado. El manifiesto vigente declara de `installed_tree` sólo
`relative_path/files/logical_bytes/sha256`, y `canonical_tree_identity` **descarta** la lista de
entradas después de calcular el digest: hoy no existe ninguna declaración por archivo contra la cual
comparar. El manifiesto gana ese inventario, ligado al digest agregado ya existente.

**D-LEA-6.** La adquisición y el cotejo usan **enumeraciones independientes**: el inventario
declarado y el recorrido del adquisidor no pueden compartir el helper cuyo defecto se quiere
detectar. Cada archivo se coteja además por **volumen y file ID**, no sólo por ruta.

**D-LEA-7.** El hash de cada elemento se calcula **a través del handle retenido**, no reabriendo la
ruta. Un digest tomado por una apertura distinta de la que sostiene la congelación no prueba que se
congeló lo que se midió.

**D-LEA-8.** El lease se adquiere **antes** del primer hash del conjunto y se mantiene mientras se
hashea. Congelar y luego medir; nunca medir y luego congelar.

**D-LEA-9.** El arnés **no modifica descriptores de seguridad de rutas que no le pertenecen**. Se
mantiene la frontera vigente de `_seal_windows_snapshot_directories`. *(Esta decisión es la que
cambia si Cami elige la variante B; ver §7.1.)*

### Pieza 2 — anti-inyección

**D-LEA-10.** `-X pycache_prefix=<ruta fresca, vacía y propiedad del arnés>` es parte declarada del
contrato de congelación, no sólo una bandera de aislamiento. Está medido que `-B` por sí solo **no**
impide que un `.pyc` plantado gane a la fuente. Y como la bandera **muda** el vector al prefijo en
vez de eliminarlo (§3.2), el prefijo se **sella contra altas** durante todo el intento —es
harness-owned, así que el sello cae dentro de la frontera vigente— y su vacuidad se atestigua al
cierre, no sólo antes de ejecutar. Si en su lugar se decidiera retirarle la etiqueta Low, eso sí
cambia el contrato que su docstring declara y necesita decisión propia.

**D-LEA-11.** El candidato corre con una **clausura de búsqueda de DLL explícita**: sólo el
directorio del sistema y los directorios leaseados del conjunto congelado. Cualquier directorio
añadido en tiempo de ejecución que no pertenezca al conjunto es condición roja. Está medido que
`SetDefaultDllDirectories(LOAD_LIBRARY_SEARCH_SYSTEM32)` cierra incluso un directorio añadido con
`os.add_dll_directory`. Esta decisión gobierna los defaults del proceso; **no** gobierna una carga
nativa que use flags propios o `LOAD_WITH_ALTERED_SEARCH_PATH` (§3.4), y por eso no basta sola.

**D-LEA-12.** El intento atestigua cada imagen cargada por cada proceso del Job candidato —ruta,
file ID y digest— mediante un **gate síncrono anterior a su ejecución**, no un censo posterior ni un
muestreo periódico. Un muestreo pierde una carga-descarga entre muestras, que es exactamente el
vector de §3.1. El mecanismo candidato es la cadena de eventos de depuración —crear el árbol con
`DEBUG_PROCESS`, procesar cada `CREATE_PROCESS_DEBUG_EVENT`/`LOAD_DLL_DEBUG_EVENT` y hashear desde
el handle del evento **antes** de `ContinueDebugEvent`, cubriendo descendientes y fallando cerrado
ante handle nulo, evento perdido o hueco de PID/creation-time—.

> **No medido.** Esta torre **no** ha medido todavía si `DEBUG_PROCESS` convive con el token de
> integridad Low, el Job con `KILL_ON_JOB_CLOSE` y el arranque suspendido que el arnés ya usa, ni si
> `LOAD_DLL_DEBUG_EVENT` se entrega **antes** de que corra el `DllMain` de la DLL cargada. Sin esas
> dos mediciones, D-LEA-12 es un requisito con mecanismo propuesto, no un mecanismo acreditado.
> Medirlas es precondición de implementar, y su resultado puede obligar a volver a esta enmienda.

**D-LEA-12b.** El **canal Python** necesita su propia pieza causal, porque un `.py`, un ZIP
importable o un `.dist-info` no producen imagen PE y D-LEA-12 no los vería (§3.3). Antes de ejecutar
o de consumir metadata, toda apertura o import desde una entrada **no inventariada** de las raíces
declaradas es condición roja. Mientras esta pieza no exista y no tenga control negativo verde, la
variante A **no** es cierre suficiente de la frontera.

**D-LEA-13.** El manifiesto candidato declara la **clausura de carga del intérprete** en los cinco
términos de §4.2, incluida la frontera explícita del TCB de Windows, y esa clausura entra en el
conjunto congelado. *(Sujeta a §7.2.)*

**D-LEA-14.** El censo enumera y **rechaza streams no predeterminados** en cada elemento del
conjunto. Está medido que el lease se evalúa por stream y que un ADS puede crearse sobre un archivo
leaseado sin alterar su stream por defecto.

**D-LEA-15.** El material congelado debe residir en un **filesystem y volumen calificados** por una
matriz cerrada. El arnés atestigua el volumen de cada elemento y rechaza uno no calificado. Toda la
evidencia de §2 proviene de NTFS local; SMB, filesystems respaldados por nube y material
multivolumen **no están medidos** y no se dan por buenos.

### Pieza 3 — anti-falso-éxito

**D-LEA-16.** La publicación de evidencia sigue una **máquina de estados de tres pasos**, y ningún
paso posterior al release puede volver a leer material vivo:

1. **provisional** — se construye y valida la evidencia **con el lease vivo**, y ésa es la única
   validación que puede usar `verify_artifacts=True`;
2. **release** — se cierran y verifican todos los handles;
3. **promoción** — sólo entonces se escribe atómicamente el terminal `success`. La relectura final
   comprueba JSON canónico y self-binding con `verify_artifacts=False`.

Hoy el código vivo hace lo contrario: escribe `attempt.json` y **después** lo revalida con
`verify_artifacts=True` contra artefactos vivos. Liberar antes de esa revalidación reintroduce el
TOCTOU; liberar después deja publicado un `success` si la revalidación falla, porque el manejador de
error observa que la evidencia ya existe y vuelve a lanzar en vez de publicar un terminal de fallo.

**D-LEA-17.** Un fallo de liberación tiene **clasificación propia** y publica evidencia de fallo,
nunca de éxito. La liberación es transaccional y verificada: cada handle se cierra exactamente una
vez y el arnés no publica éxito mientras quede uno abierto.

**D-LEA-17b.** Los consumidores **durables** validan la atestación y el inventario congelados, no
reabren material vivo. Hoy `validate_campaign_progress` revalida cada evidencia previa con
`verify_artifacts=True`, y `_attempt_summary` hace lo mismo y además verifica sidecars directamente:
mantener esas relecturas después de soltar el lease convierte un éxito durable en una campaña
irrecuperable en cuanto cambie una ruta viva, y devuelve el TOCTOU por la puerta de atrás.

**D-LEA-17c.** Cambiar el booleano **no basta y sería peor**: con `verify_artifacts=False` el
validador deja de comprobar launch sources, tooling, outputs y la mayor parte de los sidecars, y el
self-binding sólo compara el payload con los bytes que existan en ese momento —es recomputable tras
una sustitución—. La firma Ed25519 autentica la **autoridad de START**, no el resultado del intento.
Por eso la promoción produce un **paquete durable content-addressed** que incorpora o copia todos los
sidecars necesarios y cuelga de una raíz anclada **fuera** del workdir mutable. Validación de fuentes
vivas y validación de artefactos durables quedan separadas, y se censan los tres consumidores:
`validate_campaign_progress`, la agregación y los terminales de fallo.

**D-LEA-18.** La evidencia publica el censo del lease —archivos y directorios leaseados, inventario
canónico, digest del conjunto, imágenes atestiguadas y momentos de adquisición y liberación
relativos a START y a la quiescencia—, de modo que un lease que dejara de cubrir parte del árbol
caiga a un número visible en la evidencia firmada y no en un comentario.

### Alcance

**D-LEA-19.** Cerrar esta frontera **no** habilita START. Sólo retira
`candidate_execution_material_lease_unimplemented` de los blockers de implementación. La
autorización humana por unidad exacta y la fingerprint durable siguen siendo obligatorias, y
`qualifying_boundary_adapters_unavailable` y `multiprocess_native_pool_observer_unimplemented`
siguen abiertas.

## 6. Alternativas evaluadas

### 6.1 Rehash más frecuente

Descartada. Un rehash no impide la sustitución: la constata después, y sólo si el sustituto sigue
allí. Contra un plantado transitorio no prueba nada, y multiplicaría el término de coste dominante.

### 6.2 Copiar el material a espacio propio del arnés (variante C)

Frontera más limpia —el arnés sería dueño de los bytes— pero se descarta como recomendación:

- **coste**: una copia completa por intento, contra un presupuesto de disco que el protocolo todavía
  no ha fijado;
- **corrección**: una venv no es relocalizable. `pyvenv.cfg` fija `home` absoluto y los `.exe` de
  `Scripts` llevan la ruta del intérprete incrustada;
- **semántica de la evidencia**: el candidato dejaría de ser lo que el operador declaró y pasaría a
  ser una copia hecha por el arnés.

### 6.3 Por qué B no es la decisión importante

B añade el sello DACL sobre directorios del operador y así **previene altas** en el árbol candidato,
que A sólo puede atestiguar. Pero:

- no cubre el plantado **transitorio** en directorios que el propio arnés hace escribibles —`staging`
  y `candidate-runtime` llevan etiqueta Low por diseño—;
- no cubre la clausura del intérprete si ésta no se declara;
- deja una DACL ajena alterada si el supervisor muere de forma dura, justo cuando algo ya salió mal.

Con la pieza 2 implementada, lo que B aporta se solapa con la atestación de imágenes. Sin la pieza 2,
B tampoco cierra la frontera. Por eso la recomendación es A **más** las piezas 2 y 3.

## 7. Lo que Cami debe decidir

### 7.0 Modelo de amenaza — decisión previa a todo lo demás

Cami pidió medir antes de fijar el alcance, y la medición de §0 cambió el cuadro: la vía de
inyección en memoria **existe** con el diseño vigente, y **se puede cerrar sin administrador** con
una DACL restrictiva más un ACE de `OWNER RIGHTS`. La DACL sola no basta —el dueño la reescribe, y
se midió que lo consigue—.

- **0-a — acotar la promesa.** Los procesos Medium del mismo usuario quedan dentro del TCB; la
  frontera promete consistencia del material **en disco**, y la línea de §12.1 se reescribe para que
  no diga «nadie». No añade trabajo a lo ya diseñado.
- **0-b — cerrar también la vía de memoria (recomendada).** El candidato se crea con DACL
  restrictiva más `OWNER RIGHTS` y la promesa se mantiene amplia. Exige antes cerrar las cuatro
  casillas de §0.3 —composición con `CreateProcessAsUserW`, token Low, arranque suspendido y Job;
  descriptor del hilo; máscara exacta del supervisor— y añadir controles negativos que intenten
  `PROCESS_VM_WRITE` y `PROCESS_CREATE_THREAD` contra el candidato real.

Recomendación: **0-b**. Antes de medir, acotar era lo honesto porque la alternativa parecía un
rediseño de seguridad de proceso sin fondo. Con el precio medido —dos ACE en la creación, y el
supervisor conservando todo lo suyo— acotar la promesa dejaría fuera un agujero que ya sabemos
cerrar, y eso sería una decisión de comodidad, no de ingeniería. Las cuatro casillas de §0.3 se
miden en la misma sesión que las dos incógnitas de D-LEA-12, porque son el mismo tipo de trabajo
sobre el mismo lanzador.

### 7.1 Frontera del mecanismo — decisión principal

- **A (recomendada).** Lease puro en sitio, sin tocar descriptores de seguridad ajenos. Mantiene
  D-LEA-9.
- **B.** Lease más sello DACL sobre los directorios del operador. Retira D-LEA-9 y concede al arnés
  autoridad para modificar seguridad fuera de su espacio.
- **C.** Snapshot sellado. Frontera limpia y coste alto; §6.2 explica por qué no se recomienda.

En las tres, las piezas 2 y 3 son obligatorias.

### 7.2 Clausura del intérprete — decisión independiente

- **Incluirla ahora.** El manifiesto gana la clausura de §4.2 y el operador debe declararla. Es el
  cierre honesto de la frontera.
- **Diferirla.** La frontera se cierra sólo sobre lo hoy declarado y se abre un blocker nuevo y
  explícito, `candidate_interpreter_closure_undeclared`.

Recomendación: **incluirla ahora**. Diferirla deja la frontera cerrada de nombre y abierta de hecho.

### 7.3 Alcance de los inputs

¿Entran también las **evidencias previas de campaña**, que hoy sólo se hashean? Recomendación:
**sí** — son entrada de la validación de progreso y su sustitución falsearía la campaña entera, no
un intento.

### 7.4 Presupuesto de preflight

Está medido que el término dominante ya lo paga el hash actual: a ~6 ms/archivo en frío, un árbol
de decenas de miles de archivos roza los 300 s **sin lease**. Opciones: dejar el presupuesto como
está y que un árbol enorme falle por deadline —fail-closed, la conducta de la casa—, o medirlo con
un candidato real y proponer un presupuesto propio. Recomendación: **dejarlo como está** aquí y
medirlo cuando exista un candidato real; subir un deadline sin candidato medido sería inventar un
valor.

### 7.5 El runtime del arnés (§4.3)

¿Se abre `trusted_harness_interpreter_closure_undeclared` como blocker propio? Recomendación:
**sí**, declararlo abierto y medido, y no mezclarlo con esta frontera.

### 7.6 La frontera resultó más grande que su catálogo — cómo seguir

La línea de §12.1 del protocolo describe esta frontera como «lease no-follow del ejecutable, árbol
candidato e inputs hasta la quiescencia». Dos revisiones adversariales y las mediciones de este
documento muestran que un lease, por sí solo, **no** produce esa propiedad: hacen falta además un
gate anterior a la ejecución para el cargador de Windows, una pieza equivalente para el import
machinery de Python, y una máquina de estados de publicación. Es más trabajo del que la línea
sugiere, y una parte todavía no tiene mecanismo acreditado.

- **Aprobar el contrato ahora y medir `DEBUG_PROCESS` dentro de la implementación (recomendada).**
  Cami aprueba D-LEA-1…19 con las variantes de §7.1–§7.5; la primera tarea de implementación es
  medir las dos incógnitas de D-LEA-12, y si resultan negativas la enmienda vuelve a Cami con el
  mecanismo alternativo antes de escribir el resto. Se avanza sin fingir que está resuelto.
- **Medir primero y aprobar después.** Una sesión mide `DEBUG_PROCESS`, el orden de
  `LOAD_DLL_DEBUG_EVENT` frente a `DllMain` y una pieza para el canal Python; la enmienda vuelve con
  esas casillas cerradas y una tercera revisión adversarial. Es más lento y llega con menos supuestos
  abiertos.
- **Reordenar la cola.** Dejar esta frontera abierta y medida, y mover el esfuerzo a
  `multiprocess_native_pool_observer_unimplemented`, cuyo instrumental se solapa con el gate de
  D-LEA-12 (§3.5). Cerrar aquélla primero podría abaratar ésta.

Recomendación: la **segunda — medir primero y aprobar después**. La primera redacción de esta sección
recomendaba aprobar ya, y la tercera revisión adversarial mostró que eso minimizaba lo pendiente: el
mecanismo del canal Windows sigue sin acreditar, el del canal Python apareció con un bypass concreto
en el `pycache_prefix`, y la promoción durable necesita una raíz de integridad que todavía no existe.
Aprobar un contrato cuyo mecanismo central puede resultar inviable obligaría a reabrirlo igual, sólo
que después de haber gastado el OK.

Lo que falta está acotado y es medible sin START: la convivencia de `DEBUG_PROCESS` con el token Low,
el Job y el arranque suspendido; el orden de `LOAD_DLL_DEBUG_EVENT` frente a `DllMain`; y un
mecanismo no eludible para el canal Python que cubra el `pycache_prefix`. Con esas tres casillas
cerradas, la quinta redacción vuelve con una cuarta revisión adversarial y el OK se pide entonces.

## 8. Controles negativos preespecificados

Cada uno sigue el protocolo del runbook: verde → defecto mínimo → **rojo por la causa prevista, no
por una precondición** → restauración byte-exacta verificada por SHA → verde. Ninguno se restaura
con `git checkout --`.

| Oráculo | Defecto mínimo | Rojo esperado |
|---|---|---|
| lease efectivo | abrir un archivo leaseado para escritura desde otro handle | `winerror=32`; vacuidad: sin lease la misma apertura da `OK` |
| cobertura del conjunto | quitar un archivo del **adquisidor**, nunca del inventario esperado | igualdad exacta roja nombrando el archivo omitido |
| cobertura inversa | añadir un archivo no catalogado que **permanece** | igualdad exacta roja por alta no declarada |
| **plantado transitorio de DLL** | plantar una DLL, **cargarla** y retirarla antes de la quiescencia | rojo por el gate síncrono **pese a un censo final limpio**, y demostrando que el marcador de su `DllMain` **no** llegó a ejecutarse |
| **plantado transitorio de `.py`** | plantar un módulo bajo uno de los 12 nombres opcionales guardados, importarlo y retirarlo | rojo por D-LEA-12b; la atestación de imágenes **no** puede ser la causa, porque no hay imagen PE |
| **plantado transitorio de ZIP importable** | añadir un ZIP importable a una raíz declarada, importarlo y retirarlo | rojo por D-LEA-12b |
| **`.dist-info` plantado** | añadir un `.dist-info` y consultar `importlib.metadata.version` | rojo por D-LEA-12b antes de que la versión falsa entre en la evidencia |
| **carga nativa que elude CPython** | helper nativo que llama `LoadLibraryEx` con ruta absoluta o `LOAD_WITH_ALTERED_SEARCH_PATH` | rojo por el gate síncrono de D-LEA-12, no por D-LEA-11 |
| independencia de enumeraciones | inyectar el defecto sólo en el helper del adquisidor | rojo; si queda verde, las dos enumeraciones no eran independientes |
| hash por handle | doble que hace **fallar toda reapertura por ruta** y registra que los bytes salieron sólo del handle retenido | rojo si el digest se obtuvo reabriendo; con el lease vivo ambos caminos dan el mismo digest, así que sin ese doble el defecto **nace verde** |
| orden | adquirir el lease **después** del primer hash | invariante de orden roja antes de READY |
| fail-closed | mantener un escritor vivo sobre un input al lanzar el preflight | `preflight_rejected`; cero tokens START |
| liberación | forzar el fallo de un `CloseHandle` | clasificación propia de fallo de liberación; **nunca** evidencia `success` |
| promoción | matar el supervisor entre validación provisional y promoción | sin `attempt.json` de éxito; parciales censados |
| **relectura post-release** | mutar el material vivo inmediatamente después del release | **un único** terminal coherente; ni un éxito falso ni una campaña irrecuperable |
| **sustitución durable autoconsistente** | reemplazar `attempt.json` y sus artefactos por un conjunto falso pero internamente coherente | rojo por la raíz anclada de D-LEA-17c; con sólo self-binding el conjunto falso **pasaría** |
| **inyección en memoria** | abrir el candidato con `PROCESS_VM_WRITE` y `PROCESS_CREATE_THREAD` desde un proceso Medium del mismo usuario | con **0-a**: se completa, y el control documenta la frontera. Con **0-b**: `DENEGADO` (5), y la vacuidad exige que sin el ACE de `OWNER RIGHTS` la misma apertura se complete |
| **recuperación por el dueño** | reabrir el candidato con `WRITE_DAC` y reescribir su DACL | con **0-b**: `DENEGADO` (5). Sin el ACE de `OWNER RIGHTS` la reescritura **tiene éxito** y devuelve la inyección: por eso el control es obligatorio en ambos sentidos |
| **`pycache_prefix`** | en un doble que conserva las demás precondiciones, plantar un `.pyc` **después** de la comprobación de vacuidad y **demostrar primero que su marcador se ejecutó** | rojo por carga del `.pyc`, no por la precondición del entrypoint |
| **alta en el `pycache_prefix`** | crear un archivo en el prefijo con el intento en curso | rojo por el sello de altas de D-LEA-10; vacuidad: sin sello, la creación se completa |
| ADS | crear un stream alterno en un elemento del conjunto | rojo por stream no predeterminado |
| volumen | declarar material en un filesystem no calificado | rojo por matriz de volumen |
| no-follow | interponer la junction **exactamente entre la inspección y el `CreateFileW`**, o inspeccionar las flags por un seam | rojo que **desaparece** al restaurar `FILE_FLAG_OPEN_REPARSE_POINT`; una junction puesta antes se pone roja por D-LEA-3 aunque se retire la flag, y por eso no prueba nada |
| portabilidad | importar un módulo sólo-Windows en cuerpo de módulo | `test_readiness_h9r_portabilidad.py` rojo nombrando archivo y módulo |

El control de `pycache_prefix` merece la nota explícita: el entrypoint vivo aborta con `SystemExit`
si falta `-I -B -S -X pycache_prefix=<dir fresco vacío>` **antes** de cargar el tooling, así que un
control que se limite a retirar la bandera se pone rojo por la precondición y **no** prueba el
oráculo de carga.

## 9. Qué NO hace esta enmienda

- No autoriza START, S0, S1, S2, workloads ni entrypoints calificables.
- No fija la fingerprint humana ni consume autorización alguna.
- No materializa fixtures, unidades ni valores finales.
- No fija caps, geometrías, budgets, disco ni perfiles.
- No toca hardware/cloud, metodología de riesgo, API pública, PyPI, tags, releases ni la demo.
- No reabre D-RDY-ABA, D-RDY-H9R ni ninguna decisión aprobada.
- No retira `qualifying_boundary_adapters_unavailable` ni
  `multiprocess_native_pool_observer_unimplemented`.

## 10. Texto exacto para el OK

Si Cami aprueba, el texto que deja constancia es:

> Fijo el modelo de amenaza de `_ENMIENDA-LEASE-MATERIAL-CANDIDATO.md` en la opción
> **\<acotar | mantener amplia\>** de §7.0 y el camino **\<aprobar y medir | medir primero |
> reordenar\>** de §7.6. Si el camino elegido es aprobar ahora, apruebo además D-LEA-0 y
> D-LEA-1…D-LEA-19 con D-LEA-12b, D-LEA-17b y D-LEA-17c, con la variante **\<A | B | C\>** de §7.1, la
> opción **\<incluir ahora | diferir\>** de §7.2 y las respuestas **\<sí | no\>** de §7.3 y §7.5. Autorizo implementar, probar y revisar el mecanismo dentro del
> arnés. No autorizo START, S0, S1, S2, workloads, entrypoints calificables, fingerprint humana,
> fixtures definitivos, valores finales, hardware/cloud, metodología, API, PyPI, tags, releases ni
> recaptura de demo.
