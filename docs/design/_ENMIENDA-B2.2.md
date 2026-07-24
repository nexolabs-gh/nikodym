# Enmienda SDD B2.2 — launcher, runtime y seguridad

> **Estado: APROBADA (Cami, 2026-07-24), tras una ronda de revisión adversarial independiente.**
> Habilita la programación de B2.2. Esta enmienda es la **fuente de verdad del contrato de B2.2**;
> SDD-23 y SDD-25 la referencian en vez de duplicarla, y sus decisiones se consolidan en ambos SDD
> al **cerrar** el nodo, igual que se hizo con B2.1.
>
> **Base:** `main` = `02b7997` (B2.1 cerrado, CI verde en los 16 jobs).
> **Enmienda a:** `docs/design/23-ui.md` (SDD-23) y `docs/design/25-packaging-ci.md` (SDD-25).
> **Autor / Fecha:** DanIA / 2026-07-24.
>
> **Registro de revisión — ronda 1 (2026-07-24).** Dos revisores adversariales frescos y read-only
> (lente de seguridad/runtime y lente de packaging/coherencia B2.1). **Ambos RECHAZARON** la versión
> inicial: 3 P0 y 6 P1/P2 sustantivos, todos verificados por el coordinador contra el código antes de
> integrarse. Los tres P0: el checker no podía importar el módulo movido en el job `build` del CI
> (`--no-sync`); la allowlist rechazaba `entry_points.txt`; y el bundle distribuido apunta la API a
> `http://localhost:8000`, Host que el propio middleware rechaza (E-B2.2-9). Esta versión incorpora
> las correcciones; **sigue pendiente la aprobación de Cami**.

| Campo | Valor |
|---|---|
| **Nodo** | B2.2 · launcher, runtime y seguridad (ROADMAP §B2, DAG aprobado) |
| **Habilita** | B2.3 (`[ui]`, uploads y presets) |
| **No toca** | `[ui]` composición (B2.3), clean-room Playwright (B2.4), cableado de release (B2.5) |
| **Contrato previo** | D-UI-9 y D-UI-12 (aprobadas en B2.0), SDD-23 §4.2/§7/§8, SDD-25 §5/§6 |

---

## 0. Qué cambia y qué no

B2.0 aprobó **qué** debe hacer el launcher: bind fijo `127.0.0.1`, token efímero de 256 bits, `Host`
exacto, `Origin` + token en mutadores, preflight del index antes de bind, orden API → assets →
fallback. Esta enmienda **no reabre** ninguna de esas decisiones: fija el **cómo** con el detalle que
falta para poder programar sin inventar contrato a mitad de camino, y —lección directa de B2.1—
**declara sus límites conocidos desde el día 1** (§2).

Fuera de alcance, explícito: `--host`, exposición a red (sigue siendo **D-UI-R0**, decisión de Cami),
HTTPS, multiusuario, autenticación de usuarios, `--port 0`, subpath.

---

## 1. Decisiones

### E-B2.2-1 — `RuntimeContext`: estado de lanzamiento inmutable y no serializable

`nikodym/ui/runtime.py` define:

```python
@dataclass(frozen=True, slots=True)
class RuntimeContext:
    host: str                       # siempre "127.0.0.1"
    port: int                       # puerto efectivo ya reservado (E-B2.2-4)
    workdir: Path                   # resuelto y absoluto
    static_dir: Path                # resuelto y absoluto
    index_bytes: bytes              # index leído en preflight, con el placeholder intacto
    _token: str = field(repr=False) # token efímero; NUNCA en repr/log/URL/disco
```

**Contrato.**

- El token es `secrets.token_bytes(32)` (256 bits) codificado `urlsafe_b64encode` sin padding para
  transporte. Se genera **una vez por lanzamiento** en el launcher, nunca en `create_app`.
- `repr=False` en el campo del token es **obligatorio**: un `dataclass` frozen genera un `__repr__`
  con todos los campos, y ese repr aparece en tracebacks de Uvicorn/FastAPI. Un test afirma que ni
  `repr()` ni `str()` del contexto contienen el token.
- Comparación **siempre** con `secrets.compare_digest` (timing-safe). Prohibido `==`.
- No es Pydantic y no hereda de `NikodymBaseConfig`: **no** es config del usuario, no se serializa,
  no se dumpea y no entra al `config_hash` (D-UI-3 intacta). `UiConfig` sigue siendo el único config
  de la herramienta.
- Vive en `app.state.runtime`. Prohibido: variable global, variable de entorno, archivo, query param.

*Alternativa descartada:* llevar el token en `UiConfig`. Un modelo Pydantic existe para ser volcado
(`model_dump`, YAML, `/api/schema`); meter un secreto ahí es una filtración esperando ocurrir.

### E-B2.2-2 — Middleware único: `Host` exacto siempre, `Origin` + token en mutadores

Un solo middleware, registrado antes que cualquier router, en dos escalones:

1. **Toda** request: `Host` debe ser exactamente `127.0.0.1:<puerto efectivo>`. Cualquier otro valor
   —incluido `localhost:<puerto>`— responde **403** sin tocar el routing. `localhost` se rechaza a
   propósito: puede resolver a `::1` y es la puerta de entrada clásica al DNS rebinding. El mensaje
   es accionable y en español: `abra http://127.0.0.1:<puerto>/`.
2. `POST /api/upload` y `POST /api/run`: además `Origin` exactamente `http://127.0.0.1:<puerto>` y
   header `X-Nikodym-Token` válido. Ausencia, valor vacío o mismatch ⇒ **403**. El cuerpo de la
   respuesta **nunca** repite el token recibido ni el esperado.
3. Mismos endpoints: si `allow_live_execution` es `false` ⇒ **403**, evaluado **antes** que el token.

**El tercer escalón cierra un hueco que existe hoy.** `allow_live_execution` está declarado en
`settings.py:33` y **no se lee en ninguna ruta** (grep sobre `src/`: sólo su propia definición): el
único freno documentado para servir la UI sin ejecución es hoy un no-op, pese a que SDD-23 §4.2 lo
exige en `/api/upload` y `/api/run` y §4.2 advierte que «el flag **no** se reduce a una indicación
visual del frontend». B2.2 crea el punto donde ese gate cabe; cerrar «seguridad» sin él sería
cerrarlo en falso.

**Comparación del token en `bytes`, no en `str`.** `secrets.compare_digest` lanza `TypeError` con
strings no-ASCII (verificado), y Starlette decodifica las cabeceras en latin-1: un
`X-Nikodym-Token` con un byte `0xF1` produciría un **500** en vez del 403 contratado. Se compara
sobre `bytes` (`.encode("utf-8", "surrogateescape")`).

CORS externo permanece deshabilitado (no se añade `CORSMiddleware`). El nombre del header es
`X-Nikodym-Token`, fijado aquí como contrato para que front y back no puedan divergir; del lado del
front lo envían los mutadores de `web/src/lib/api.ts`.

**El invariante de núcleo liviano manda sobre la comodidad del import.** `test_ui_server.py:272`
exige que `import nikodym.ui.server` **no** arrastre `fastapi`/`uvicorn`, y SDD-25 §6 lo declara
invariante. Por tanto `runtime.py` es puro (stdlib) y `security.py` **no importa FastAPI/Starlette a
nivel de módulo**: el import es perezoso, dentro de `create_app`. Un `from fastapi import Request` al
tope es el modo natural de romper ese test sin darse cuenta.

*Nota de alcance:* los GET de lectura (`/api/schema`, `/api/results/...`) exigen `Host` pero no
token — es lo aprobado en B2.0 y su consecuencia está escrita en **L5** (§2).

### E-B2.2-3 — Puerto: `--port` en `[1024, 65535]`, default 8000, sin `--host`

- `argparse` con `--port` (int, default 8000), `--workdir` (default `.nikodym_ui`), `--no-open`.
- Un puerto fuera de `[1024, 65535]` falla en el parseo con mensaje en español; `<1024` se rechaza
  por ser privilegiado, no por gusto.
- **No existe `--host`** (D-UI-12). No se añade tampoco una variable de entorno equivalente: una
  puerta trasera no declarada es peor que una opción declarada.
- Puerto ocupado ⇒ fallo **antes** de abrir el navegador, con mensaje que sugiere `--port <otro>`.

*Alternativa descartada:* `--port 0` (puerto efímero). Funcionaría —el puerto efectivo se conoce tras
la reserva—, pero añade superficie sin demanda y vuelve impredecible la URL que el usuario debe
reabrir. Queda como extensión futura, no como límite.

### E-B2.2-4 — Reservar el socket antes de abrir el navegador

Orden estricto del `main()`, sin excepciones:

1. Parseo de argumentos → 2. **preflight** (E-B2.2-6) → 3. `socket()` + `bind((127.0.0.1, port))`
→ 4. construir `RuntimeContext` con el puerto efectivo → 5. `create_app(settings, runtime)` →
6. **imprimir por stdout** `http://127.0.0.1:<puerto>/` → 7. `uvicorn.Server(config).run(sockets=[sock])`
→ 8. abrir el navegador **sólo** cuando `server.started` es `True`, desde un hilo, con timeout.

Verificado contra la fuente de Uvicorn instalada (0.49.0): `serve()` es una **corrutina**
(`server.py:77`); el entry point síncrono es `Server.run(sockets=...)` (`server.py:74`). Con
`serve(...)` sin `await`, el launcher no arrancaría nada y, bajo `filterwarnings=["error"]`, el
`RuntimeWarning: coroutine never awaited` sería error. `startup()` hace `loop.create_server(sock=sock)`
por cada socket y **no** vuelve a bindear, que es lo que elimina la carrera real: hoy, entre comprobar
que el puerto está libre y que Uvicorn lo tome, otro proceso puede quedarse con él y el navegador
abriría contra un servidor ajeno en `127.0.0.1`.

El `print` explícito del paso 6 no es cosmético: cuando se pasan `sockets`, Uvicorn **omite**
`_log_started_message`, así que nadie anuncia la URL. Con `--no-open`, el usuario se quedaría sin
saber dónde entrar.

Si el preflight falla, **el navegador no se abre y no se bindea nada**. Un backend a medias que
parezca una UI sana es un fallo, no una degradación aceptable (SDD-23 §8).

### E-B2.2-5 — Entry point `nikodym-ui` y `__main__`

- `pyproject.toml`: `[project.scripts]` → `nikodym-ui = "nikodym.ui.__main__:main"`.
- `nikodym/ui/__main__.py` expone `main(argv: Sequence[str] | None = None) -> int`, de modo que
  `python -m nikodym.ui` y el console script recorren exactamente el mismo camino. Los errores del
  launcher salen por stderr en español y retornan código ≠ 0; no se imprime traceback crudo.
- **Manifiesto de distribución (SDD-25 §6):** la lista `required` del wheel suma
  `nikodym/ui/__main__.py` y el `entry_points.txt` del `.dist-info`. Dos precisiones sin las cuales
  el gate falla el día que se añade `[project.scripts]`:
  - **`allowed` también cambia.** `validate_content` aplica la allowlist a **todos** los archivos del
    wheel, y los únicos `*.dist-info/*` permitidos hoy son `METADATA`, `WHEEL`, `RECORD` y
    `licenses/LICENSE`. Sin `*.dist-info/entry_points.txt` en `allowed`, el candidate se rechaza por
    «ruta fuera de allowlist» aunque el archivo esté en `required`.
  - **El placeholder se resuelve tarde.** Como el nombre del dist-info depende de la versión, la
    entrada obligatoria se declara `{dist_info}/entry_points.txt`; pero `_policy_section` valida al
    **cargar la política** que cada `required` case con algún `allowed`, sobre cadenas **sin
    resolver**. La resolución ocurre en `validate_content` (que ya recibe `content.dist_info`), y el
    patrón de `allowed` debe casar la forma sin resolver.
- El checker no se conforma con que el archivo exista: **parsea** `entry_points.txt` y exige la
  entrada `nikodym-ui = nikodym.ui.__main__:main` en el grupo `console_scripts`. Un archivo presente
  y vacío es exactamente el fallo que este gate debe cazar.

### E-B2.2-6 — Preflight: una sola implementación de la semántica canónica

**El problema.** La semántica que resuelve los recursos del index (`_IndexResources`,
`_fully_unquote`, `_local_resource_path`) vive hoy en `scripts/check_distribution_contents.py`, y
`scripts/` **no viaja en el wheel**. El launcher corre en la instalación del usuario, donde ese
archivo no existe. Copiarla crea dos fuentes de verdad sobre un gate de seguridad: exactamente la
clase de deriva silenciosa que costó tres ciclos de revisión en B2.1.

**La decisión.** Se mueve la semántica canónica a un módulo **distribuido**,
`nikodym/ui/_static_index.py`, y `scripts/check_distribution_contents.py` pasa a importarla. Reglas:

- El script **no conserva copia**; un test afirma que las funciones que usa son las del paquete
  (identidad de objeto, no igualdad de texto).
- **El checker importa del árbol fuente sincronizado, NUNCA del candidate.** Instalar el wheel y
  auditarlo con su propio código sería exactamente el modo en que un artefacto mutado se aprueba a sí
  mismo; queda prohibido por contrato.
- **El job `build` necesita el proyecto instalado, y hoy no lo está.** `ci.yml:278` y `:291` invocan
  el checker con `uv run --no-sync`, y el primer `uv sync` del job está en `ci.yml:357`, *después*.
  Hoy no importa porque el script es sólo stdlib; con esta enmienda el `import` muere con
  `ModuleNotFoundError` antes de validar un byte. **`.github/workflows/ci.yml` entra al delta (§3):**
  un `uv sync --locked --python 3.12 --no-default-groups` antes del primer checker.
- **Anclaje por sha256 del módulo, no por versión.** El checker compara el **sha256 de
  `_static_index.py` dentro del candidate** (`nikodym/ui/…` en el wheel, `src/nikodym/ui/…` en el
  sdist) contra los bytes del módulo importado. Comparar `__version__` sería a la vez insuficiente
  —permanece fija durante decenas de commits, así que un módulo divergente pasaría— y redundante,
  porque bytes idénticos ya implican semántica idéntica. *(Corregido al implementar: la versión
  añadía una restricción que no aportaba seguridad y rompía fixtures legítimos.)* La coherencia de
  versión entre wheel y sdist la cubre `validate_candidate_set`.
- Lo compartido es **puro**: parseo del index y resolución de cada referencia a una ruta relativa
  bajo `static/`. Lo que difiere es el **sustrato** de existencia, y se inyecta:
  - checker → miembros del ZIP/TAR (donde, además, `zipfile` normaliza `os.sep` a `/` al leer y al
    escribir: la garantía sobre backslashes la sostiene la stdlib en Windows y `_safe_name` en POSIX);
  - launcher → filesystem: cada recurso debe existir, ser **archivo regular** y, tras `Path.resolve()`,
    seguir dentro de `static_dir` (un symlink que escapa no existe en un ZIP pero sí en disco).
- El preflight falla con la **lista completa** de rutas faltantes o inválidas, no con la primera.

### E-B2.2-7 — Un único placeholder de token en el index; orden de rutas

**Placeholder.** El index distribuido lleva exactamente una ocurrencia de `__NIKODYM_TOKEN__`, en
`<meta name="nikodym-token" content="__NIKODYM_TOKEN__">`. El preflight cuenta las ocurrencias:
0 o ≥2 ⇒ **fallo antes de bind**. Al servir `/`, el launcher reemplaza esa única ocurrencia **en
memoria** sobre `index_bytes` y responde con `Cache-Control: no-store`. `static/index.html` nunca se
reescribe en disco.

- *Descartado:* `<script>window.__NIKODYM_TOKEN__="…"</script>` inline. El index ya tiene un inline
  (el que aplica el tema antes del paint), y añadir un segundo —éste sí con un secreto dentro—
  amplía la superficie que el gate anti-request debe analizar y bloquea una CSP estricta futura; un
  `meta` no ejecuta nada.
- **Demo estática:** en la demo no hay servidor Python que sustituya nada (Vercel sirve el build de
  `VITE_DEMO_MODE=true`, `web/src/lib/demo.ts:70`), así que el literal viaja al HTML público tal
  cual. El front debe tratar «ausente **o** igual al literal `__NIKODYM_TOKEN__`» como *sin token* y
  no romper. Sin esta regla, publicar B2.2 rompe la demo.
- Este cambio toca `web/index.html`, así que **regenera** el build versionado y su evidencia de
  procedencia B2.1. El commit debe incluir bundle regenerado y evidencia en el mismo paso, y los
  gates B2.1 (anti-request, licencias, procedencia, contenido de distribución) deben seguir verdes.

**Orden de rutas** (registro explícito, de arriba abajo):

1. router `/api/*`;
2. `/assets/*` (`StaticFiles`) y **exactamente** el conjunto de recursos de raíz que devolvió el
   preflight (`/favicon.svg`, …), uno por ruta resuelta. **No se monta `static/` en `/`**: eso
   reintroduciría la superficie duplicada que este mismo apartado elimina y expondría
   `static/index.html` crudo —con el placeholder sin sustituir— y los notices de 179 KB en URLs no
   contratadas;
3. `GET /` → index inyectado;
4. fallback SPA → index inyectado **sólo** para navegación (`Accept` que incluye `text/html`).
   *(Precisado al implementar: va como **handler de 404**, no como ruta `"/{full_path:path}"`. Una
   ruta catch-all compite con el router y con `/assets`, y FastAPI la obliga a declarar el `Request`
   como parámetro, lo que con anotaciones diferidas devolvía 422 en todas las rutas. Como handler
   de 404 sólo se entra cuando nada resolvió.)*

**`Cache-Control: no-store` va en TODA respuesta que lleve el index inyectado**, no sólo en `/`.
El fallback sirve el mismo HTML con el mismo token: si el navegador cachea `/resultados` con el token
T1 y el usuario relanza `nikodym-ui` (token T2), al reabrir desde el historial toda mutación responde
403 sin explicación — y el token queda escrito en la caché de disco del navegador, que es justo lo que
D-UI-12 prohíbe (`23-ui.md:571-572`, `:784`).

El fallback devuelve **404** para cualquier `/api/*` no resuelto y para rutas con extensión de asset.
Un fallback que responde `200 text/html` a `/assets/perdido.js` convierte un asset faltante en una
página en blanco sin error — el modo de fallo que B2.4 va a testear y que no debe existir.

**Se retira el mount `/static`** de `create_app`, andamio de B2.1: dos URLs para el mismo byte es
superficie duplicada y contradice el contrato «assets bajo `/assets`» de SDD-23 §4.2.

### E-B2.2-8 — `create_app(settings, runtime)`: el runtime es obligatorio, no opcional

La firma pasa de `create_app(settings)` a `create_app(settings, runtime)`, con `runtime`
**obligatorio**. Hoy hay **12 llamadas en 7 archivos**, no sólo en tests:

- `tests/unit/test_ui_{server,presets,routes}.py` (8) → migran a una fixture de `RuntimeContext`.
- `scripts/smoke_instalacion_pip.py:68` → **corre en el CI** (`ci.yml:312`, «Smoke de instalación
  real»). Si se olvida, el job `build` queda rojo con `TypeError`.
- `scripts/capture_demo_fixtures.py:291`, `capture_demo_fixtures_f1.py:381`,
  `capture_demo_fixtures_ifrs9.py:315` → se romperían **en silencio** hasta la próxima recaptura de
  la demo.

Como hay consumidores legítimos que no son el launcher, `runtime.py` expone una **factory pública
documentada** para construir un contexto de uso no-servidor; cada script inventándose su propia
instancia de un dataclass privado es la vía rápida a cuatro variantes divergentes.

**La fixture de test se fija aquí, o el gate de `Host` muere en la suite.** `TestClient` usa
`base_url="http://testserver"` por defecto, así que con el middleware activo ~30 tests darían 403 y
la salida barata sería `RuntimeContext(host="testserver", …)`: suite verde y el chequeo de `Host`
—único mitigante de DNS rebinding, L2— **jamás ejercitado**. Es el mismo no-op que esta decisión dice
evitar, entrando por otra puerta. Contrato: la fixture construye `RuntimeContext(host="127.0.0.1",
port=P)` y el cliente se crea con `TestClient(app, base_url=f"http://127.0.0.1:{P}")`, con `Origin` y
`X-Nikodym-Token` en los mutadores. **Prohibido** un host de prueba distinto de `127.0.0.1`.

**Dos tests no se migran: se reescriben.** `test_create_app_sin_build_no_monta_static` y
`test_create_app_monta_static_si_existe_build` (`tests/unit/test_ui_server.py:244` y `:255`, este
último exige **200** en `/static/index.html`) afirman precisamente el mount que E-B2.2-7 retira. Su
contrato nuevo es `/static/...` ⇒ **404**.

*Alternativa descartada:* `runtime: RuntimeContext | None = None`, que evitaría tocar los tests. Con
ese default, casi toda la suite construiría la app **sin** middleware de seguridad y los gates
pasarían verdes sin ejercitarlo nunca — la trampa ya registrada en este proyecto: un control gateado
por un parámetro opcional es un no-op en tests que aparenta cobertura. Un test adicional afirma que
la app que construye el launcher tiene el middleware efectivamente registrado.

### E-B2.2-9 — `API_BASE` relativo: el front apunta hoy a un Host que el middleware rechaza

**El hallazgo que casi convierte B2.2 en una entrega falsa.** `web/src/lib/api.ts:33-34` define
`API_BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000"`, ningún `.env` fija esa
variable, y **el bundle ya distribuido contiene el literal** `http://localhost:8000`
(verificado en `src/nikodym/ui/static/assets/index-afcOGJhd.js`). Todas las llamadas lo usan
(`api.ts:165`, `:279`, `:317`, `:333`, `:350`, `:360`, `schema.ts:68`).

Con E-B2.2-2 vigente, el usuario que abre `http://127.0.0.1:8000/` carga la SPA —index y assets son
same-origin y funcionan— y a continuación **cada** llamada a la API sale hacia `localhost:8000`:
distinto origen, sin `CORSMiddleware` el navegador la bloquea, y si llegara, el middleware responde
403 por `Host`. Resultado: formulario vacío, sin datasets, sin ejecutar. **Y el criterio de aceptación
tal como estaba escrito —«levanta y sirve `/` con la SPA navegable»— pasaba igual**, porque la
navegación sí funciona. Es exactamente `feature gateada por config = feature inexistente`, con el
gate en el front.

**Contrato:** `API_BASE` pasa a ser **relativo** (`""`), que es lo que SDD-23 §4.2 ya manda («consume
una API **relativa** bajo `/api`»). `web/src/lib/api.ts` entra al delta, y §4 exige un criterio que
ejercite una llamada real de la SPA servida, no sólo `GET /`.

---

## 2. Alcance y límites conocidos del modelo de seguridad

Declarados **antes** de implementar, en el espíritu de SDD-25 §6.1. Si aparece un nivel más de la
clase, **va aquí como límite conocido, no a otro ciclo de código**.

- **L1 — Malware local del mismo usuario queda fuera del modelo.** Cualquier proceso corriendo como
  el usuario puede leer la memoria del launcher o el DOM del navegador. El modelo protege contra
  **sitios web remotos y el navegador**, no contra un atacante ya dentro de la sesión.
- **L2 — DNS rebinding se mitiga por `Host` exacto**, no por CORS. Un nombre que resuelva a
  `127.0.0.1` llega con otro `Host` y se rechaza; por eso `localhost` también se rechaza.
- **L3 — Extensiones del navegador con permiso sobre `127.0.0.1` ven el token.** No hay defensa
  posible desde el servidor.
- **L4 — Sin HTTPS.** El tráfico es loopback y no sale de la máquina; otro usuario con privilegios
  de root puede capturarlo. Aceptado para uso local monousuario.
- **L5 — Los GET de lectura sólo exigen `Host`.** Un sitio remoto puede *disparar* un
  `GET /api/results/...` (CORS le impide leer la respuesta), y ese GET no muta estado. Los mutadores
  —`/api/upload`, `/api/run`— sí exigen `Origin` + token.
- **L6 — El token vive lo que vive el proceso.** No hay rotación ni expiración dentro de un
  lanzamiento; reiniciar `nikodym-ui` invalida el anterior. Suficiente para una sesión local.
- **L7 — Poner el token en el DOM convierte cualquier HTML same-origin en vector potencial.** Es una
  clase nueva que nace con B2.2: un script dentro de un HTML servido en el mismo origen puede leer
  `meta[name=nikodym-token]` y llamar a los mutadores con `Origin` y token válidos. El caso concreto
  hoy es `web/src/components/ReporteTab.tsx:303`, que embebe el informe con `<iframe srcDoc>` **sin
  `sandbox`** —y `srcdoc` hereda el origen del padre—. B2.2 **cierra ese caso** añadiendo `sandbox`
  al iframe (una línea; el informe sólo necesita renderizar). El mitigante de fondo sigue siendo el
  `autoescape=True` del renderer (`src/nikodym/report/renderer.py:146`). La **clase** queda
  declarada: todo HTML nuevo servido same-origin debe justificar por qué no necesita `sandbox`.

---

## 3. Delta por archivo

| Archivo | Cambio |
|---|---|
| `src/nikodym/ui/__main__.py` | **nuevo** — `main(argv) -> int`, argparse, preflight, reserva de socket, navegador |
| `src/nikodym/ui/runtime.py` | **nuevo** — `RuntimeContext` (E-B2.2-1) |
| `src/nikodym/ui/_static_index.py` | **nuevo** — semántica canónica movida desde `scripts/` (E-B2.2-6) |
| `src/nikodym/ui/security.py` | **nuevo** — middleware `Host`/`Origin`/token (E-B2.2-2) |
| `src/nikodym/ui/server.py` | `create_app(settings, runtime)`; retira `/static`; registra middleware, assets, `/` y fallback |
| `tests/unit/test_ui_{server,presets,routes}.py` | 8 llamadas a `create_app(...)` migran a la fixture de `RuntimeContext` (E-B2.2-8) |
| `web/index.html` + build versionado | placeholder `__NIKODYM_TOKEN__` |
| `web/src/lib/api.ts` | **`API_BASE` relativo** (E-B2.2-9); lee el `meta` y envía `X-Nikodym-Token` en los mutadores |
| `web/src/components/ReporteTab.tsx` | `sandbox` en el `<iframe srcDoc>` del informe (L7) |
| `.github/workflows/ci.yml` | `uv sync` antes del checker (P0 de E-B2.2-6); smoke del console script instalado |
| `scripts/smoke_instalacion_pip.py` | migra a la factory de `RuntimeContext`; **corre en CI**, si se olvida el job queda rojo |
| `scripts/capture_demo_fixtures{,_f1,_ifrs9}.py` | migran a la factory; si se olvidan, se rompen en silencio hasta la próxima recaptura |
| `pyproject.toml` | `[project.scripts] nikodym-ui = "nikodym.ui.__main__:main"` |
| `scripts/distribution_contents_allowlist.json` | `required` del wheel += `nikodym/ui/__main__.py`, `{dist_info}/entry_points.txt` |
| `scripts/check_distribution_contents.py` | importa `nikodym.ui._static_index`; resuelve `{dist_info}`; parsea `entry_points.txt`; afirma versión |
| `docs/design/23-ui.md` | §4.2/§4.3/§7/§8 precisadas; **D-UI-12 → implementada**; nueva **D-UI-13** (límites L1…L6) |
| `docs/design/25-packaging-ci.md` | §5 B2.2 → implementado; §6 manifiesto `required`; §6.2 nueva (alcance del preflight) |

---

## 4. Criterios de aceptación

Cada test debe verificarse **fallando con el código anterior** antes de darse por bueno
(trampa recurrente del proyecto). Aislamiento por hallazgo.

**Launcher.** `--port 80` y `--port 70000` fallan en parseo · no existe `--host` ni env equivalente ·
puerto ocupado ⇒ error accionable **sin** abrir navegador · preflight fallido ⇒ no hay bind ni
navegador · el launcher imprime la URL efectiva.

**La SPA funciona de verdad, no sólo navega.** Servir `/` **no basta como criterio**: desde la página
servida, `GET /api/schema` responde 200 y el formulario se puebla. Un criterio que sólo mire `GET /`
daría por buena una UI con toda la API muerta (E-B2.2-9). Además, el console script **instalado**
arranca: en el paso de smoke pip (`ci.yml:312`), `./.venv-pip/bin/nikodym-ui --help` y un arranque
`--no-open` — probar `main()` in-process no dice nada sobre el ejecutable que genera `pip install`.

**Seguridad.** `Host: localhost:8000` ⇒ 403 · `Host` ajeno ⇒ 403 · `/api/run` sin token ⇒ 403 · con
token mal ⇒ 403 · con `Origin` ajeno ⇒ 403 · con ambos correctos ⇒ pasa · **token con byte no-ASCII
⇒ 403, no 500** · **`allow_live_execution=false` ⇒ 403 en `/api/upload` y `/api/run`, con lectura
intacta** · el token **no** aparece en `repr(RuntimeContext)`, ni en logs, ni en la URL, ni en ningún
archivo bajo `workdir` · **toda** respuesta con index inyectado (`/` y fallback) lleva
`Cache-Control: no-store` · `static/index.html` en disco sigue con el placeholder intacto tras servir
(hash idéntico) · la fixture de tests usa `127.0.0.1` (un test falla si alguien la apunta a
`testserver`).

**Rutas.** `/api/desconocido` ⇒ 404 (no HTML) · `/assets/perdido.js` ⇒ 404 (no HTML) ·
`/cualquier/ruta` con `Accept: text/html` ⇒ index · `/static/...` ⇒ 404 (mount retirado).

**Preflight y distribución.** Index sin placeholder ⇒ falla · con dos ⇒ falla · falta un recurso
local (favicon incluido) ⇒ falla antes de bind · symlink que escapa `static/` ⇒ falla · el checker y
el launcher comparten las funciones (identidad de objeto) · wheel sin `__main__.py` o sin la entrada
en `entry_points.txt` ⇒ candidate no se promueve · `entry_points.txt` presente pero vacío ⇒ falla.

**Regresión B2.1.** Anti-request del bundle, licencias frontend y runtime, procedencia y contenido de
distribución **verdes con el bundle regenerado**. Demo: el front tolera el placeholder sin sustituir.
**Smoke pip y las tres capturas de fixtures siguen verdes** tras el cambio de firma (P1-4 del revisor:
son 4 consumidores fuera de `tests/`, uno de ellos gate del CI).

**Gates de cierre.** `ruff` · `mypy --strict` · `pytest` completo · los 6 gates de `web/` ·
CI verde en los 16 jobs antes de declarar B2.2 cerrado.

---

## 4.bis Trampa encontrada al implementar

**Un handler de ruta con parámetro-con-default es un query param.** El registro de los recursos de
raíz se escribió primero así:

```python
@app.get(f"/{resource}")
async def _recurso_de_raiz(target: str = resource) -> Any:   # ← MAL
    return FileResponse(runtime.static_dir / target)
```

Parece un closure y no lo es: FastAPI interpreta `target` como **parámetro de consulta**, de modo
que `/favicon.svg?target=<ruta>` servía cualquier archivo alcanzable desde `static_dir`. La forma
correcta es una factory que cierre sobre la ruta y un handler **sin parámetros**. Cubierto por un
test de regresión que pide `/favicon.svg?target=../secreto.txt` y exige el favicon.

---

## 5. Riesgos y decisiones abiertas

- **D-UI-R0 sigue abierta y sigue siendo de Cami:** exponer ejecución en vivo a la red. B2.2 la
  respeta fijando el bind y no ofreciendo `--host`.
- **Riesgo de arrastre:** tocar `web/index.html` regenera el bundle y su evidencia. Si el commit
  separa código y bundle, los gates B2.1 se ponen rojos por desalineación, no por un defecto real.
  Mitigación: un único commit atómico para placeholder + bundle + evidencia.
- **Riesgo de alcance:** el middleware de seguridad admite refinamiento indefinido. El corte está en
  §2: lo no cubierto se escribe como límite y se cierra el ciclo.
