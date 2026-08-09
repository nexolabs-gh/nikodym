# Runbook de Codex

> Procedimiento operativo durable para este checkout. El estado y los conteos vigentes están en
> `HANDOFF.md`, symlink interno no versionado en el repo público, no aquí.

## 1. Arranque literal

Ejecutar desde la raíz pública:

```bash
git status --short --branch
git rev-parse HEAD
git -C privado status --short --branch
git -C privado rev-parse HEAD
readlink HANDOFF.md
```

El resultado esperado es `main` en ambos repos y `HANDOFF.md -> privado/HANDOFF.md`. No asumir que
un árbol está limpio porque el otro lo está. Comprobar después que los HEAD coincidan con el
`HANDOFF`; si no, medir la diferencia antes de usar su estado.

Leer, en orden, `AGENTS.md`, `HANDOFF.md`, este runbook y
[`../design/DECISIONES-VIGENTES.md`](../design/DECISIONES-VIGENTES.md).

## 2. Entorno local de macOS

- Para Python local usar siempre el intérprete real del entorno:
  **`.venv/bin/python`**, no `uv run` ni el console script `nikodym-ui`.
- Motivo: el shebang del entrypoint y varios wrappers pasan por `/bin/sh`; macOS SIP puede eliminar
  `DYLD_*`. Una corrida puede terminar `done` y aun así perder el PDF. El primer proceso ejecutado
  debe ser el intérprete, sin `sh` ni `nohup` intermedios.
- `uv run` dentro de los workflows Linux de CI es deliberado; esta regla es para el checkout local
  de macOS. `uv lock --check` sí se ejecuta directamente.
- La UI sólo acepta loopback IPv4: usar **`127.0.0.1`**, nunca `localhost` —que puede resolver a
  `::1` y producir 403—. El servidor no ofrece `--host` por diseño.

Arranque local reproducible de la UI:

```bash
.venv/bin/python -m nikodym.ui --no-open
```

Abrir `http://127.0.0.1:8000`. Para otro puerto, añadir `--port 8001`. Si la corrida ejerce PDF,
confirmar el PDF final: el estado `done` no basta.

## 3. Gates canónicos

Lista literal completa. Ejecutar el conjunto proporcional al cambio; para un cierre integral,
ejecutarlos todos:

```bash
.venv/bin/python -m pytest
.venv/bin/python -m mypy
.venv/bin/ruff check .
.venv/bin/ruff format --check .
(cd web && pnpm vitest run)
(cd web && pnpm typecheck)
(cd web && pnpm lint)
(cd web && pnpm build:package)
.venv/bin/python -m mkdocs build --strict
uv lock --check
```

Reglas de lectura del resultado:

- Registrar el número real de tests passed/skipped, archivos de mypy y casos de Vitest. **No usar
  `pytest --timeout=900`**: este entorno no trae ese plugin y se ha observado exit code 0 sin correr
  tests. Un `0` sin censo no es un gate.
- Ruff son dos gates distintos: `check` no sustituye `format --check`.
- Vitest corre sin DOM salvo configuración explícita; no demuestra layout, foco, viewport ni
  navegación. Un contrato visual requiere UI viva y navegador.
- `pnpm typecheck` puede quedar verde y `pnpm build:package` fallar. El build es el gate del artefacto
  empacado, no un duplicado opcional.
- `mkdocs build --strict` deja `site/`; liberarlo al cierre.
- Tocar `pyproject.toml` exige actualizar `uv.lock` y luego `uv lock --check`. Con lock viejo, el CI
  puede dejar 15 de 16 jobs rojos antes de que arranque un test.

## 4. Qué gate añadir según lo tocado

| Superficie modificada | Evidencia adicional mínima |
|---|---|
| Config/Pydantic/schema | `.venv/bin/python scripts/gen_schema_fixture.py`; revisar diff del fixture; bundle |
| Catálogo de trabajos/abanico | `.venv/bin/python scripts/gen_jobs_fixture.py`; revisar diff; bundle |
| Front o artefactos estáticos | `pnpm build:package` dos veces si hay riesgo de no determinismo; comparar `src/nikodym/ui/static` |
| Motor regulatorio | tests canónicos/golden y cobertura de `nikodym.testing.regulatory.REGULATORY_COVERAGE_PATHS` al 100 % |
| Informe | verificar el HTML y, si aplica, PDF/Word reales; no sólo snapshots de helpers |
| UI/navegación/copy visible | recorrido en navegador por `127.0.0.1`, incluido el estado adversarial |
| Distribución/release | wheel/sdist, contenido, instalación limpia y auditoría adversarial de todo el rango de release |
| Docs | `mkdocs --strict` y lectura del sitio generado en la página afectada |

Regenerar schema/jobs no es recapturar la demo. Los scripts `capture_demo_fixtures*.py` sí lo son y
requieren un OK nuevo de Cami. Los fixtures de demo salen de corridas reales: jamás editarlos a mano.

Después de un cambio de schema o jobs:

```bash
.venv/bin/python scripts/gen_schema_fixture.py
.venv/bin/python scripts/gen_jobs_fixture.py
(cd web && pnpm build:package)
git diff -- src/nikodym/ui/static web/src/fixtures
```

Ejecutar sólo el generador que corresponda; el bloque muestra ambos para que los dos nombres queden
explícitos. Si cambia un fixture de demo con autorización, regenerar también sus firmas con
`node scripts/generate_frontend_demo_fixture_signatures.mjs` y dejar que CI valide el artefacto.

## 5. Control negativo sin perder trabajo

Cada cierre necesita al menos un control que demuestre que el oráculo se pone rojo al inyectar el
defecto prometido. Protocolo:

1. Ejecutar el gate en verde y guardar su censo.
2. Comprobar `git diff` y copiar el archivo afectado a una ruta temporal única creada con
   `mktemp -d`.
3. Inyectar el defecto mínimo con `apply_patch`; no mezclarlo con el arreglo real.
4. Ejecutar el gate y observar el fallo correcto, no cualquier rojo.
5. Restaurar el archivo desde la copia exacta y comparar `git diff` con el anterior.
6. Reejecutar el gate en verde.

**No usar `git checkout -- <archivo>` para restaurar un control negativo.** Restaura desde el
índice, no desde “antes del experimento”, y puede borrar cambios legítimos no staged. Tampoco
confiar en un `git add` como copia de seguridad.

Un gate estático debe probarse en ambos sentidos cuando afirma completitud: quitar un caso existente
y añadir un caso nuevo no clasificado. Un conteo con holgura no sustituye ese par.

## 6. Git público, repo privado y push

El root es público; `privado/` es otro repo. Nunca hacer `git add privado` desde el público. Antes de
stagear, inspeccionar tracked y untracked en ambos:

```bash
git status --short
git diff --check
git diff --stat
git ls-files --others --exclude-standard
git -C privado status --short
git -C privado diff --check
git -C privado ls-files --others --exclude-standard
```

Stagear sólo rutas resueltas y revisar también el índice —`git diff` sin `--cached` omite staged y
untracked—:

```bash
git add -- RUTAS_PUBLICAS_EXACTAS
git diff --cached --check
git diff --cached --stat
git diff --cached --name-status
git commit -m "docs: describe el cambio"
```

El mensaje se reemplaza por la descripción concreta; el punto obligatorio es que el commit público
exista y su HEAD se mida antes del push.

Antes de cada push público, seleccionar explícitamente la cuenta correcta; `gh auth status` puede
parecer sano y el push usar otra identidad:

```bash
/opt/homebrew/bin/gh auth switch --user nexolabs-gh
git push origin main
```

`main` es la rama de cierre autorizada. Si se usó worktree o branch temporal, integrar a `main`
antes de terminar. No inventar coautoría. En este punto se pushea **sólo el público**: el HANDOFF
privado necesita el HEAD público definitivo y su CI, así que se cierra después.

## 7. Verificar CI y deploy job a job

Varios commits empujados juntos pueden producir un solo run sobre el último HEAD. Por eso
`gh run list --commit <sha-intermedio>` puede devolver vacío aunque el commit sí esté contenido.
Primero mapear por `headSha` y verificar que el commit de interés sea ancestro del HEAD del run:

```bash
/opt/homebrew/bin/gh run list --workflow CI --branch main --limit 20 --json databaseId,headSha,status,conclusion,url
git merge-base --is-ancestor SHA_A_VERIFICAR SHA_DEL_RUN
/opt/homebrew/bin/gh run view RUN_ID --json jobs --jq '.jobs[] | [.name, .conclusion] | @tsv'
/opt/homebrew/bin/gh run list --workflow Deploy --branch main --limit 20 --json databaseId,headSha,status,conclusion,url
/opt/homebrew/bin/gh run view DEPLOY_RUN_ID --json jobs --jq '.jobs[] | [.name, .conclusion] | @tsv'
```

No resumir “CI verde” desde la conclusión agregada: listar todos los jobs y confirmar que ninguno
quedó rojo, cancelado o saltado indebidamente. Si falla el paso de licencias que consulta red,
inspeccionar el log antes de diagnosticar un defecto del código.

El workflow `Deploy` se dispara automáticamente sólo tras CI verde en `main`, publica docs y demo y
verifica contenido en vivo. No hace falta un deploy manual adicional. Desplegar artefactos ya
versionados no autoriza recapturar fixtures ni publicar PyPI.

## 8. Liberación y cierre

Antes de entregar:

- detener todo proceso iniciado en la sesión y cerrar el navegador automatizado;
- inspeccionar y eliminar sólo artefactos generados por la sesión: `web/dist/`, `.playwright-mcp/`,
  `site/`, `reports/` y workdirs temporales conocidos;
- no borrar por patrón amplio ni asumir que un artefacto ignorado es propio;
- verificar procesos con el binario absoluto —algunos shells no exponen `pgrep` en PATH— y revisar
  ambos repos:

```bash
/usr/bin/pgrep -fl 'nikodym\.ui|uvicorn|vite|pytest|vitest' || true
git status --short --branch
git -C privado status --short --branch
```

Sólo ahora actualizar `privado/HANDOFF.md` con HEAD público definitivo, run y jobs de CI/deploy,
gates medidos, limpieza, abiertos exactos y siguiente decisión de Cami. El archivo raíz es sólo el
symlink: nunca reemplazarlo por un archivo regular. Stagear, revisar, commitear y pushear el repo
privado **después** de esa actualización:

```bash
git -C privado add -- RUTAS_PRIVADAS_EXACTAS
git -C privado diff --cached --check
git -C privado diff --cached --stat
git -C privado diff --cached --name-status
git -C privado commit -m "docs: actualiza el relevo"
git -C privado push origin main
```

Si el CI obliga a corregir y crear otro commit público, repetir su push/verificación antes de cerrar
el HANDOFF. Confirmar al final:

```bash
test "$(readlink HANDOFF.md)" = "privado/HANDOFF.md"
git status --short --branch
git -C privado status --short --branch
```
