# Runbook de Codex

> Procedimiento operativo durable para este checkout. El estado y los conteos vigentes están en
> `HANDOFF.md`, symlink interno no versionado en el repo público, no aquí.

## 1. Arranque literal en Windows

Windows es el checkout writer. Ejecutar en **Windows PowerShell 5.1** desde la raíz pública; no
traducir estos comandos a `cmd.exe`, WSL o Git Bash:

```powershell
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$nikodymUtf8 = New-Object System.Text.UTF8Encoding($false)
[Console]::InputEncoding = $nikodymUtf8
[Console]::OutputEncoding = $nikodymUtf8
$OutputEncoding = $nikodymUtf8
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'

$nikodymRepo = 'C:\Users\camil\OneDrive\Documents\Proyectos\Nikodym RiskLib'
Set-Location -LiteralPath $nikodymRepo

git status --short --branch
if ($LASTEXITCODE -ne 0) { throw 'git status público falló' }
git rev-parse HEAD
if ($LASTEXITCODE -ne 0) { throw 'HEAD público no se pudo leer' }
git rev-parse origin/main
if ($LASTEXITCODE -ne 0) { throw 'origin/main público no se pudo leer' }
git -C privado status --short --branch
if ($LASTEXITCODE -ne 0) { throw 'git status privado falló' }
git -C privado rev-parse HEAD
if ($LASTEXITCODE -ne 0) { throw 'HEAD privado no se pudo leer' }
git -C privado rev-parse origin/main
if ($LASTEXITCODE -ne 0) { throw 'origin/main privado no se pudo leer' }

$nikodymHandoff = Get-Item -Force -LiteralPath 'HANDOFF.md'
$nikodymHandoffTarget = [IO.Path]::GetFullPath([string]$nikodymHandoff.Target)
$nikodymExpectedHandoff = [IO.Path]::GetFullPath(
    (Join-Path $nikodymRepo 'privado\HANDOFF.md')
)
if ($nikodymHandoff.LinkType -ne 'SymbolicLink') { throw 'HANDOFF.md no es symlink' }
if ($nikodymHandoffTarget -ne $nikodymExpectedHandoff) {
    throw "target HANDOFF inesperado: $nikodymHandoffTarget"
}
if (-not (Test-Path -LiteralPath $nikodymHandoffTarget -PathType Leaf)) {
    throw "target HANDOFF ausente: $nikodymHandoffTarget"
}
$nikodymHandoff | Select-Object FullName,LinkType,Target
```

El resultado esperado es `main` limpio en ambos repos, cada `HEAD` igual a su `origin/main`, y
`HANDOFF.md` con `LinkType=SymbolicLink` y un target absoluto terminado en
`\privado\HANDOFF.md`. No asumir que un
árbol está limpio porque el otro lo está. Si un OID no coincide con el `HANDOFF`, medir log, diff y
ancestría antes de usar su estado.

Leer, en orden, `AGENTS.md`, `HANDOFF.md`, este runbook y
[`../design/DECISIONES-VIGENTES.md`](../design/DECISIONES-VIGENTES.md).

## 2. Toolchain contractual de Windows

### 2.1 Python y uv

- Usar siempre **`.venv\Scripts\python.exe`**. El alias global `python` resuelve a Microsoft Store
  y queda prohibido, igual que `py` o un intérprete descubierto por casualidad en `PATH`.
- La venv es administrada por uv y puede no exponer `pip`; no usar `python -m pip` como receta de
  mantenimiento del checkout.
- uv 0.12.2 no está en `PATH`. Invocar su ruta absoluta registrada y volver a comprobar su versión
  antes de una operación que pueda cambiar el lock o construir un clean-room:

```powershell
$nikodymPython = Join-Path $nikodymRepo '.venv\Scripts\python.exe'
$nikodymUv = 'C:\Users\camil\AppData\Local\Microsoft\WinGet\Packages\astral-sh.uv_Microsoft.Winget.Source_8wekyb3d8bbwe\uv.exe'

$nikodymPythonVersion = (& $nikodymPython --version).Trim()
if ($LASTEXITCODE -ne 0) { throw 'Python contractual falló' }
if ($nikodymPythonVersion -ne 'Python 3.12.10') {
    throw "Python inesperado: $nikodymPythonVersion"
}
$nikodymUvVersion = (& $nikodymUv --version).Trim()
if ($LASTEXITCODE -ne 0) { throw 'uv contractual falló' }
if ($nikodymUvVersion -ne 'uv 0.12.2 (46ead6098 2026-08-05 x86_64-pc-windows-msvc)') {
    throw "uv inesperado: $nikodymUvVersion"
}
& $nikodymUv lock --check
if ($LASTEXITCODE -ne 0) { throw 'uv lock --check falló' }
```

### 2.2 Node y pnpm

El runtime contractual es Node 22.22.2 con pnpm 11.15.0. Anteponer su directorio al `PATH` **del
proceso actual** y ejecutar `pnpm.CMD`; `pnpm.ps1` queda bloqueado por Execution Policy y el fallback
de Codex trae versiones distintas (Node 24.14.0/pnpm 11.16.0):

```powershell
$nikodymNodeDir = 'C:\Users\camil\AppData\Local\Programs\node-v22.22.2-win-x64'
$nikodymNode = Join-Path $nikodymNodeDir 'node.exe'
$nikodymPnpm = Join-Path $nikodymNodeDir 'pnpm.CMD'
$env:PATH = "$nikodymNodeDir;$env:PATH"

$nikodymNodeVersion = (& $nikodymNode --version).Trim()
if ($LASTEXITCODE -ne 0) { throw 'Node contractual falló' }
if ($nikodymNodeVersion -ne 'v22.22.2') { throw "Node inesperado: $nikodymNodeVersion" }
$nikodymPnpmVersion = (& $nikodymPnpm --version).Trim()
if ($LASTEXITCODE -ne 0) { throw 'pnpm.CMD contractual falló' }
if ($nikodymPnpmVersion -ne '11.15.0') { throw "pnpm inesperado: $nikodymPnpmVersion" }
```

Las dos salidas deben ser `v22.22.2` y `11.15.0`. No aceptar el verde de un comando `pnpm` sin
haber demostrado qué binario ejecutó.

### 2.3 GitHub CLI

`gh` 2.97.0 tampoco está necesariamente en `PATH`. Antes de un push, usar el binario absoluto,
seleccionar `nexolabs-gh` y verificar que quedó activo:

```powershell
$nikodymGh = 'C:\Program Files\GitHub CLI\gh.exe'
$nikodymGhVersion = @(& $nikodymGh --version)
if ($LASTEXITCODE -ne 0) { throw 'gh contractual falló' }
if ($nikodymGhVersion[0] -ne 'gh version 2.97.0 (2026-07-31)') {
    throw "gh inesperado: $($nikodymGhVersion[0])"
}
& $nikodymGh auth switch --user nexolabs-gh
if ($LASTEXITCODE -ne 0) { throw 'gh auth switch falló' }
& $nikodymGh auth status
if ($LASTEXITCODE -ne 0) { throw 'gh auth status falló' }
git remote -v
if ($LASTEXITCODE -ne 0) { throw 'remoto público no se pudo leer' }
git -C privado remote -v
if ($LASTEXITCODE -ne 0) { throw 'remoto privado no se pudo leer' }
$nikodymPublicRemote = (git remote get-url origin).Trim()
if ($LASTEXITCODE -ne 0) { throw 'URL remota pública no se pudo leer' }
$nikodymPrivateRemote = (git -C privado remote get-url origin).Trim()
if ($LASTEXITCODE -ne 0) { throw 'URL remota privada no se pudo leer' }
if ($nikodymPublicRemote -ne 'https://github.com/nexolabs-gh/nikodym.git') {
    throw "remoto público inesperado: $nikodymPublicRemote"
}
if ($nikodymPrivateRemote -ne 'https://github.com/nexolabs-gh/nikodym-privado.git') {
    throw "remoto privado inesperado: $nikodymPrivateRemote"
}
```

Nunca imprimir ni copiar el token. Los remotos esperados son `nexolabs-gh/nikodym` y
`nexolabs-gh/nikodym-privado`, ambos por HTTPS.

### 2.4 UTF-8, symlinks y reparse points

PowerShell 5.1 inicia `$OutputEncoding` como ASCII aunque la consola pueda reportar UTF-8. El bloque
de arranque lo corrige **antes** de leer `AGENTS.md` o `HANDOFF.md`; repetirlo si se abre otro
proceso PowerShell:

```powershell
$nikodymUtf8 = New-Object System.Text.UTF8Encoding($false)
[Console]::InputEncoding = $nikodymUtf8
[Console]::OutputEncoding = $nikodymUtf8
$OutputEncoding = $nikodymUtf8
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
```

Para leer texto desde PowerShell, declarar `-Encoding UTF8`. No reescribir archivos con
`Out-File`, redirección `>` o `Set-Content` sin inspeccionar después bytes/EOL: PowerShell 5.1 puede
introducir BOM o CRLF y varias superficies están firmadas. Respetar `.gitattributes` y comprobar
`git diff --check` más el diff real.

Developer Mode no está disponible, `git config --get core.symlinks` devuelve `false` y
`LongPathsEnabled=0`. El symlink `HANDOFF.md` ya existente se conserva; nunca reemplazarlo por un
archivo regular ni por una junction. Tampoco tratar cualquier `ReparsePoint` de OneDrive como una
junction. No crear symlinks/junctions nuevos para acortar un clean-room: `Path.resolve()` debe ver
la ubicación física real.

Medir esas premisas cuando la tarea dependa de ellas:

```powershell
$nikodymCoreSymlinks = (git config --get core.symlinks).Trim()
if ($LASTEXITCODE -ne 0) { throw 'core.symlinks no se pudo leer' }
if ($nikodymCoreSymlinks -ne 'false') { throw "core.symlinks inesperado: $nikodymCoreSymlinks" }
$nikodymLongPaths = Get-ItemPropertyValue `
    -Path 'HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem' `
    -Name LongPathsEnabled
if ($nikodymLongPaths -ne 0) { throw "LongPathsEnabled inesperado: $nikodymLongPaths" }
& fsutil behavior query SymlinkEvaluation
if ($LASTEXITCODE -ne 0) { throw 'SymlinkEvaluation no se pudo leer' }
```

### 2.5 Procesos y temporales

Crear cada clean-room con nombre corto fuera de OneDrive. Esta receta produce una ruta única bajo
el temp local y demuestra por frontera de directorio que no quedó dentro del checkout ni de
OneDrive:

```powershell
$nikodymTempRoot = Join-Path $env:TEMP 'nkr'
New-Item -ItemType Directory -Force -Path $nikodymTempRoot | Out-Null
$nikodymCleanRoom = Join-Path $nikodymTempRoot ([guid]::NewGuid().ToString('N'))
$nikodymCleanRoom = [IO.Path]::GetFullPath($nikodymCleanRoom)
$nikodymRepoResolved = [IO.Path]::GetFullPath($nikodymRepo)
$nikodymRepoBoundary = $nikodymRepoResolved.TrimEnd('\') + '\'
if ($nikodymCleanRoom.StartsWith($nikodymRepoBoundary, [StringComparison]::OrdinalIgnoreCase)) {
    throw "clean-room dentro del checkout: $nikodymCleanRoom"
}
$nikodymOneDriveResolved = [IO.Path]::GetFullPath($env:OneDrive)
$nikodymOneDriveBoundary = $nikodymOneDriveResolved.TrimEnd('\') + '\'
if ($nikodymCleanRoom.StartsWith($nikodymOneDriveBoundary, [StringComparison]::OrdinalIgnoreCase)) {
    throw "clean-room dentro de OneDrive: $nikodymCleanRoom"
}
New-Item -ItemType Directory -Path $nikodymCleanRoom | Out-Null
$nikodymSessionPids = New-Object 'System.Collections.Generic.HashSet[int]'
```

Conservar las rutas exactas creadas durante la sesión. Borrarlas sólo con esta comprobación; nunca
usar globs ni una variable no validada:

```powershell
function Remove-NikodymTempDirectory {
    param([Parameter(Mandatory=$true)][string]$LiteralPath)
    $nikodymDeleteTarget = [IO.Path]::GetFullPath($LiteralPath)
    $nikodymDeleteParent = [IO.Directory]::GetParent($nikodymDeleteTarget).FullName
    $nikodymExpectedParent = [IO.Path]::GetFullPath($nikodymTempRoot)
    if ($nikodymDeleteParent -ne $nikodymExpectedParent) {
        throw "borrado fuera del temp contractual: $nikodymDeleteTarget"
    }
    Remove-Item -LiteralPath $nikodymDeleteTarget -Recurse -Force
    if (Test-Path -LiteralPath $nikodymDeleteTarget) {
        throw "el temporal persiste: $nikodymDeleteTarget"
    }
}
Remove-NikodymTempDirectory -LiteralPath $nikodymCleanRoom

function Remove-NikodymTempFile {
    param([Parameter(Mandatory=$true)][string]$LiteralPath)
    $nikodymDeleteTarget = [IO.Path]::GetFullPath($LiteralPath)
    $nikodymDeleteParent = [IO.Directory]::GetParent($nikodymDeleteTarget).FullName
    $nikodymExpectedParent = [IO.Path]::GetFullPath($nikodymTempRoot)
    if ($nikodymDeleteParent -ne $nikodymExpectedParent) {
        throw "borrado fuera del temp contractual: $nikodymDeleteTarget"
    }
    Remove-Item -LiteralPath $nikodymDeleteTarget -Force
    if (Test-Path -LiteralPath $nikodymDeleteTarget) {
        throw "el temporal persiste: $nikodymDeleteTarget"
    }
}
```

Para revisar procesos, censar comando y PID; no matar por nombre global porque puede afectar trabajo
ajeno:

```powershell
Get-CimInstance Win32_Process |
    Where-Object {
        $_.ProcessId -ne $PID -and
        $_.Name -in @('python.exe','node.exe') -and
        $_.CommandLine -match 'nikodym\.ui|uvicorn|vite|pytest|vitest|measure_readiness'
    } |
    Select-Object ProcessId,ParentProcessId,Name,CommandLine
```

Al lanzar un servicio, agregar de inmediato su PID a `$nikodymSessionPids` y detener sólo los PIDs
registrados por esta sesión. El supervisor S3 debe cerrar su árbol por
Job Object; un barrido posterior es evidencia adicional, no sustituto de `KILL_ON_JOB_CLOSE`.

## 3. macOS: diagnóstico excepcional de solo lectura

El Mac no es writer ni runner ordinario. Se usa sólo si aparece una falla exclusiva de macOS, la
matriz CI no aporta evidencia suficiente y hace falta reproducirla. En ese caso:

- usar siempre **`.venv/bin/python`**, no `uv run` ni el console script `nikodym-ui`;
- el shebang y wrappers pueden pasar por `/bin/sh`; SIP puede eliminar `DYLD_*`. El primer proceso
  debe ser el intérprete, sin `sh` ni `nohup` intermedios;
- `uv run` en workflows Linux de CI sigue siendo deliberado; `uv lock --check` local sí se ejecuta
  directamente;
- usar `127.0.0.1`, nunca `localhost`, porque `::1` puede producir 403.

Arranque diagnóstico de UI:

```bash
.venv/bin/python -m nikodym.ui --no-open
# Si 8000 está ocupado:
.venv/bin/python -m nikodym.ui --no-open --port 8001
```

No existe `--host` por diseño. Abrir `http://127.0.0.1:8000` (o el puerto alternativo elegido). Si
la corrida ejerce PDF, verificar el PDF final: `done` no basta.
No commitear, pushear, recapturar ni regenerar desde el Mac.

## 4. Gates canónicos

Lista literal completa. Ejecutar el conjunto proporcional al cambio; para un cierre integral,
ejecutarlos todos:

```powershell
& $nikodymPython -m pytest
if ($LASTEXITCODE -ne 0) { throw 'pytest falló' }
& $nikodymPython -m mypy
if ($LASTEXITCODE -ne 0) { throw 'mypy falló' }
& $nikodymPython -m ruff check .
if ($LASTEXITCODE -ne 0) { throw 'ruff check falló' }
& $nikodymPython -m ruff format --check .
if ($LASTEXITCODE -ne 0) { throw 'ruff format falló' }
Push-Location -LiteralPath 'web'
try {
    & $nikodymPnpm vitest run
    if ($LASTEXITCODE -ne 0) { throw 'vitest falló' }
    & $nikodymPnpm typecheck
    if ($LASTEXITCODE -ne 0) { throw 'typecheck falló' }
    & $nikodymPnpm lint
    if ($LASTEXITCODE -ne 0) { throw 'lint frontend falló' }
    & $nikodymPnpm build:package
    if ($LASTEXITCODE -ne 0) { throw 'build:package falló' }
} finally {
    Pop-Location
}
& $nikodymPython -m mkdocs build --strict
if ($LASTEXITCODE -ne 0) { throw 'MkDocs strict falló' }
& $nikodymUv lock --check
if ($LASTEXITCODE -ne 0) { throw 'uv lock --check falló' }
```

PowerShell 5.1 no se detiene por el exit code de un ejecutable nativo. Cada gate se comprueba antes
de lanzar el siguiente; el `0` de un comando posterior nunca rescata un rojo anterior.

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

## 5. Qué gate añadir según lo tocado

| Superficie modificada | Evidencia adicional mínima |
|---|---|
| Config/Pydantic/schema | `& $nikodymPython scripts\gen_schema_fixture.py`; revisar diff del fixture; bundle |
| Catálogo de trabajos/abanico | `& $nikodymPython scripts\gen_jobs_fixture.py`; revisar diff; bundle |
| Front o artefactos estáticos | Entrar a `web`; ejecutar `& $nikodymPnpm build:package` dos veces si hay riesgo de no determinismo; comparar `src/nikodym/ui/static` |
| Motor regulatorio | tests canónicos/golden y cobertura de `nikodym.testing.regulatory.REGULATORY_COVERAGE_PATHS` al 100 % |
| Informe | verificar el HTML y, si aplica, PDF/Word reales; no sólo snapshots de helpers |
| UI/navegación/copy visible | recorrido en navegador por `127.0.0.1`, incluido el estado adversarial |
| Distribución/release | wheel/sdist, contenido, instalación limpia y auditoría adversarial de todo el rango de release |
| Docs | `& $nikodymPython -m mkdocs build --strict` y lectura del sitio generado en la página afectada |
| Driver de readiness | `& $nikodymPython -m mypy --strict scripts\measure_readiness_w1.py` y tests focales del arnés/supervisor |

Regenerar schema/jobs no es recapturar la demo. Los scripts `capture_demo_fixtures*.py` sí lo son y
requieren un OK nuevo de Cami. Los fixtures de demo salen de corridas reales: jamás editarlos a mano.

Después de un cambio de schema o jobs:

```powershell
& $nikodymPython scripts\gen_schema_fixture.py
if ($LASTEXITCODE -ne 0) { throw 'gen_schema_fixture falló' }
& $nikodymPython scripts\gen_jobs_fixture.py
if ($LASTEXITCODE -ne 0) { throw 'gen_jobs_fixture falló' }
Push-Location -LiteralPath 'web'
try {
    & $nikodymPnpm build:package
    if ($LASTEXITCODE -ne 0) { throw 'build:package falló' }
} finally { Pop-Location }
git diff -- src/nikodym/ui/static web/src/fixtures
if ($LASTEXITCODE -ne 0) { throw 'diff de fixtures falló' }
```

Ejecutar sólo el generador que corresponda; el bloque muestra ambos para que los dos nombres queden
explícitos. Si cambia un fixture de demo con autorización, regenerar también sus firmas con
`& $nikodymNode scripts\generate_frontend_demo_fixture_signatures.mjs`, comprobar
`$LASTEXITCODE` y dejar que CI valide el artefacto.

## 6. Control negativo sin perder trabajo

Cada cierre necesita al menos un control que demuestre que el oráculo se pone rojo al inyectar el
defecto prometido. Protocolo:

1. Ejecutar el gate en verde y guardar su censo.
2. Comprobar `git diff` y copiar el archivo afectado a una ruta temporal única creada bajo
   `$nikodymTempRoot` con el protocolo §2.5.
3. Inyectar el defecto mínimo con `apply_patch`; no mezclarlo con el arreglo real.
4. Ejecutar el gate y observar el fallo correcto, no cualquier rojo.
5. Restaurar el archivo desde la copia exacta y comparar `git diff` con el anterior.
6. Reejecutar el gate en verde.

**No usar `git checkout -- <archivo>` para restaurar un control negativo.** Restaura desde el
índice, no desde “antes del experimento”, y puede borrar cambios legítimos no staged. Tampoco
confiar en un `git add` como copia de seguridad.

Un gate estático debe probarse en ambos sentidos cuando afirma completitud: quitar un caso existente
y añadir un caso nuevo no clasificado. Un conteo con holgura no sustituye ese par.

## 7. Git público, repo privado y push

El root es público; `privado/` es otro repo. Nunca hacer `git add privado` desde el público. Antes de
stagear, inspeccionar tracked y untracked en ambos:

```powershell
git status --short
if ($LASTEXITCODE -ne 0) { throw 'status público falló' }
git diff --check
if ($LASTEXITCODE -ne 0) { throw 'diff --check público falló' }
git diff --stat
if ($LASTEXITCODE -ne 0) { throw 'diff --stat público falló' }
git ls-files --others --exclude-standard
if ($LASTEXITCODE -ne 0) { throw 'censo untracked público falló' }
git -C privado status --short
if ($LASTEXITCODE -ne 0) { throw 'status privado falló' }
git -C privado diff --check
if ($LASTEXITCODE -ne 0) { throw 'diff --check privado falló' }
git -C privado ls-files --others --exclude-standard
if ($LASTEXITCODE -ne 0) { throw 'censo untracked privado falló' }
```

Stagear sólo rutas resueltas y revisar también el índice —`git diff` sin `--cached` omite staged y
untracked—:

```powershell
git add -- RUTAS_PUBLICAS_EXACTAS
if ($LASTEXITCODE -ne 0) { throw 'stage público falló' }
git diff --cached --check
if ($LASTEXITCODE -ne 0) { throw 'diff cached público falló' }
git diff --cached --stat
if ($LASTEXITCODE -ne 0) { throw 'stat cached público falló' }
git diff --cached --name-status
if ($LASTEXITCODE -ne 0) { throw 'censo cached público falló' }
git commit -m "docs: describe el cambio"
if ($LASTEXITCODE -ne 0) { throw 'commit público falló' }
```

El mensaje se reemplaza por la descripción concreta; el punto obligatorio es que el commit público
exista y su HEAD se mida antes del push.

Antes de cada push público, seleccionar explícitamente la cuenta correcta; `gh auth status` puede
parecer sano y el push usar otra identidad:

```powershell
& $nikodymGh auth switch --user nexolabs-gh
if ($LASTEXITCODE -ne 0) { throw 'gh auth switch falló' }
& $nikodymGh auth status
if ($LASTEXITCODE -ne 0) { throw 'gh auth status falló' }
git push origin main
if ($LASTEXITCODE -ne 0) { throw 'push público falló' }
```

`main` es la rama de cierre autorizada. Si se usó worktree o branch temporal, integrar a `main`
antes de terminar. No inventar coautoría. En este punto se pushea **sólo el público**: el HANDOFF
privado necesita el HEAD público definitivo y su CI, así que se cierra después.

## 8. Verificar CI y deploy job a job

Varios commits empujados juntos pueden producir un solo run sobre el último HEAD. Por eso
`gh run list --commit <sha-intermedio>` puede devolver vacío aunque el commit sí esté contenido.
Primero mapear por `headSha` y verificar que el commit de interés sea ancestro del HEAD del run:

```powershell
& $nikodymGh run list --workflow CI --branch main --limit 20 --json databaseId,headSha,status,conclusion,url
if ($LASTEXITCODE -ne 0) { throw 'consulta de CI falló' }
git merge-base --is-ancestor SHA_A_VERIFICAR SHA_DEL_RUN
if ($LASTEXITCODE -ne 0) { throw 'el SHA no es ancestro del run' }
& $nikodymGh run view RUN_ID --json jobs --jq '.jobs[] | [.name, .conclusion] | @tsv'
if ($LASTEXITCODE -ne 0) { throw 'detalle de jobs CI falló' }
& $nikodymGh run list --workflow Deploy --branch main --limit 20 --json databaseId,headSha,status,conclusion,url
if ($LASTEXITCODE -ne 0) { throw 'consulta de Deploy falló' }
& $nikodymGh run view DEPLOY_RUN_ID --json jobs --jq '.jobs[] | [.name, .conclusion] | @tsv'
if ($LASTEXITCODE -ne 0) { throw 'detalle de jobs Deploy falló' }
```

No resumir “CI verde” desde la conclusión agregada: listar todos los jobs y confirmar que ninguno
quedó rojo, cancelado o saltado indebidamente. Si falla el paso de licencias que consulta red,
inspeccionar el log antes de diagnosticar un defecto del código.

El workflow `Deploy` se dispara automáticamente sólo tras CI verde en `main`, publica docs y demo y
verifica contenido en vivo. No hace falta un deploy manual adicional. Desplegar artefactos ya
versionados no autoriza recapturar fixtures ni publicar PyPI.

## 9. Descargar y verificar el candidato exacto de CI

El candidato publicable es el artefacto `candidate-distributions-with-evidence` del job Build de
`ci.yml`; **no** una reconstrucción local, un Release ni `release.yml`. Para identificar bytes, la
ancestría no basta: el `headSha` del run debe ser exactamente el `HEAD` que se va a verificar.

```powershell
$nikodymCandidateSha = (git rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0) { throw 'no se pudo leer el SHA candidato' }
$nikodymCiRowsRaw = @(
    & $nikodymGh run list -R nexolabs-gh/nikodym -w ci.yml -b main `
        -c $nikodymCandidateSha --limit 10 `
        --json databaseId,headSha,status,conclusion,url
)
if ($LASTEXITCODE -ne 0) { throw 'no se pudo consultar CI por SHA exacto' }
$nikodymCiRows = @(
    (($nikodymCiRowsRaw -join [Environment]::NewLine) | ConvertFrom-Json) |
        Where-Object { $_.headSha -eq $nikodymCandidateSha }
)
if ($nikodymCiRows.Count -lt 1) { throw 'no existe run CI con headSha exacto' }
$nikodymCi = $nikodymCiRows | Sort-Object databaseId -Descending | Select-Object -First 1
& $nikodymGh run watch $nikodymCi.databaseId -R nexolabs-gh/nikodym --exit-status
if ($LASTEXITCODE -ne 0) { throw 'el run CI candidato terminó rojo' }
$nikodymCiViewRaw = @(
    & $nikodymGh run view $nikodymCi.databaseId -R nexolabs-gh/nikodym `
        --json headSha,status,conclusion,jobs,url
)
if ($LASTEXITCODE -ne 0) { throw 'no se pudo leer el run CI candidato' }
$nikodymCiView = ($nikodymCiViewRaw -join [Environment]::NewLine) | ConvertFrom-Json
if ($nikodymCiView.headSha -ne $nikodymCandidateSha) { throw 'headSha CI no reconcilia' }
if ($nikodymCiView.status -ne 'completed' -or $nikodymCiView.conclusion -ne 'success') {
    throw 'CI candidato no quedó completed/success'
}
$nikodymBadJobs = @($nikodymCiView.jobs | Where-Object { $_.conclusion -ne 'success' })
if ($nikodymBadJobs.Count -ne 0) { throw 'hay jobs CI no exitosos' }
```

Descargar en una ruta corta externa y validar `SHA256SUMS` en ambos sentidos: cada entrada debe
existir y coincidir, y ningún archivo extra puede quedar fuera del manifiesto.

```powershell
$nikodymCandidateDir = Join-Path $nikodymTempRoot (
    'candidate-' + $nikodymCandidateSha.Substring(0,12) + '-' +
    [guid]::NewGuid().ToString('N')
)
New-Item -ItemType Directory -Path $nikodymCandidateDir | Out-Null
& $nikodymGh run download $nikodymCi.databaseId -R nexolabs-gh/nikodym `
    -n candidate-distributions-with-evidence -D $nikodymCandidateDir
if ($LASTEXITCODE -ne 0) { throw 'descarga del candidato falló' }

$nikodymManifest = Join-Path $nikodymCandidateDir 'SHA256SUMS'
if (-not (Test-Path -LiteralPath $nikodymManifest -PathType Leaf)) {
    throw 'SHA256SUMS ausente'
}
$nikodymCandidateRoot = [IO.Path]::GetFullPath($nikodymCandidateDir)
$nikodymCandidateBoundary = $nikodymCandidateRoot.TrimEnd('\') + '\'
$nikodymManifestPaths = @()
foreach ($nikodymLine in Get-Content -Encoding UTF8 -LiteralPath $nikodymManifest) {
    if ($nikodymLine -notmatch '^([0-9a-f]{64})  \./(.+)$') {
        throw "línea SHA256SUMS inválida: $nikodymLine"
    }
    $nikodymExpectedHash = $Matches[1]
    $nikodymRelative = $Matches[2] -replace '/', '\'
    $nikodymArtifact = [IO.Path]::GetFullPath(
        (Join-Path $nikodymCandidateRoot $nikodymRelative)
    )
    if (-not $nikodymArtifact.StartsWith(
        $nikodymCandidateBoundary, [StringComparison]::OrdinalIgnoreCase
    )) { throw "ruta fuera del artefacto: $nikodymRelative" }
    if (-not (Test-Path -LiteralPath $nikodymArtifact -PathType Leaf)) {
        throw "archivo manifestado ausente: $nikodymRelative"
    }
    $nikodymActualHash = (
        Get-FileHash -Algorithm SHA256 -LiteralPath $nikodymArtifact
    ).Hash.ToLowerInvariant()
    if ($nikodymActualHash -ne $nikodymExpectedHash) {
        throw "hash incorrecto: $nikodymRelative"
    }
    $nikodymManifestPaths += ('./' + ($nikodymRelative -replace '\\', '/'))
}
$nikodymActualPaths = @(
    Get-ChildItem -LiteralPath $nikodymCandidateRoot -Recurse -File |
        Where-Object { $_.FullName -ne $nikodymManifest } |
        ForEach-Object {
            './' + ($_.FullName.Substring($nikodymCandidateBoundary.Length) -replace '\\', '/')
        }
)
$nikodymManifestDiff = @(
    Compare-Object ($nikodymManifestPaths | Sort-Object) ($nikodymActualPaths | Sort-Object)
)
if ($nikodymManifestDiff.Count -ne 0) { throw 'SHA256SUMS no cubre el artefacto exactamente' }

$nikodymWheels = @(Get-ChildItem -LiteralPath $nikodymCandidateRoot -Recurse -File -Filter '*.whl')
$nikodymSdists = @(
    Get-ChildItem -LiteralPath $nikodymCandidateRoot -Recurse -File |
        Where-Object { $_.Name -like '*.tar.gz' }
)
if ($nikodymWheels.Count -ne 1 -or $nikodymSdists.Count -ne 1) {
    throw 'el candidato no contiene exactamente un wheel y un sdist'
}
$nikodymWheel = $nikodymWheels[0]
$nikodymSdist = $nikodymSdists[0]
$nikodymFrontendProvenance = Join-Path `
    $nikodymCandidateRoot 'frontend-evidence\frontend-provenance.json'
```

`core.autocrlf=true` materializa `LICENSE` con CRLF en este worktree, mientras wheel y sdist
conservan los bytes LF del índice. El checker compara esos bytes deliberadamente. No cambiar la
configuración global ni auditar el candidate contra su propio código: exportar una vista fuente
mínima del SHA exacto, con `core.autocrlf=false` sólo para ese proceso. Limitar el archive evita los
symlinks históricos que `tar.exe` no puede crear en esta torre:

```powershell
$nikodymSourceNonce = [guid]::NewGuid().ToString('N')
$nikodymSourceView = Join-Path $nikodymTempRoot (
    'source-lf-' + $nikodymCandidateSha.Substring(0,12) + '-' + $nikodymSourceNonce
)
$nikodymSourceArchive = Join-Path $nikodymTempRoot (
    'source-lf-' + $nikodymCandidateSha.Substring(0,12) + '-' +
    $nikodymSourceNonce + '.tar'
)
foreach ($nikodymSourceTarget in @($nikodymSourceView,$nikodymSourceArchive)) {
    if (Test-Path -LiteralPath $nikodymSourceTarget) {
        throw "la vista fuente ya existe: $nikodymSourceTarget"
    }
}
New-Item -ItemType Directory -Path $nikodymSourceView | Out-Null
$nikodymTar = (Get-Command tar.exe -CommandType Application -ErrorAction Stop).Source
git -c core.autocrlf=false archive --format=tar `
    --output=$nikodymSourceArchive $nikodymCandidateSha -- `
    LICENSE uv.lock `
    scripts/check_distribution_contents.py `
    scripts/distribution_contents_allowlist.json src
if ($LASTEXITCODE -ne 0) { throw 'git archive LF del candidato falló' }
& $nikodymTar -xf $nikodymSourceArchive -C $nikodymSourceView
if ($LASTEXITCODE -ne 0) { throw 'extracción de vista fuente LF falló' }

$nikodymPreviousPythonPath = [Environment]::GetEnvironmentVariable('PYTHONPATH','Process')
$env:PYTHONPATH = Join-Path $nikodymSourceView 'src'
try {
    & $nikodymPython `
        (Join-Path $nikodymSourceView 'scripts\check_distribution_contents.py') `
        --frontend-provenance $nikodymFrontendProvenance `
        $nikodymWheel.FullName $nikodymSdist.FullName
    if ($LASTEXITCODE -ne 0) { throw 'contenido del candidato falló' }
} finally {
    if ($null -eq $nikodymPreviousPythonPath) {
        Remove-Item Env:\PYTHONPATH -ErrorAction SilentlyContinue
    } else {
        $env:PYTHONPATH = $nikodymPreviousPythonPath
    }
}
```

Instalar **ese wheel** en una venv corta fuera de OneDrive, vaciar `PYTHONPATH`, cambiar el cwd
fuera del checkout y ejecutar primero S0; su bundle alimenta S3 v2. Las salidas son nombres nuevos:
nunca sobrescribir JSON v1.

```powershell
$nikodymVerifyRoot = Join-Path $nikodymTempRoot (
    'verify-' + $nikodymCandidateSha.Substring(0,12) + '-' +
    [guid]::NewGuid().ToString('N')
)
New-Item -ItemType Directory -Path $nikodymVerifyRoot | Out-Null
$nikodymVerifyVenv = Join-Path $nikodymVerifyRoot 'venv'
& $nikodymUv venv --python $nikodymPython $nikodymVerifyVenv
if ($LASTEXITCODE -ne 0) { throw 'creación de venv candidata falló' }
$nikodymVerifyPython = Join-Path $nikodymVerifyVenv 'Scripts\python.exe'
$nikodymWheelSpec = $nikodymWheel.FullName + '[scoring,ui,docx]'
& $nikodymUv pip install --python $nikodymVerifyPython $nikodymWheelSpec httpx2
if ($LASTEXITCODE -ne 0) { throw 'instalación del wheel candidato falló' }

$nikodymDriver = Join-Path $nikodymRepo 'scripts\measure_readiness_w1.py'
$nikodymS0Work = Join-Path $nikodymVerifyRoot 's0-work'
$nikodymS3Work = Join-Path $nikodymVerifyRoot 's3-v2-work'
$nikodymS0Output = Join-Path $nikodymVerifyRoot 'readiness-s0-candidate.json'
$nikodymS3Output = Join-Path $nikodymVerifyRoot 'readiness-s3-v2-candidate.json'
$nikodymPreviousPythonPath = [Environment]::GetEnvironmentVariable('PYTHONPATH','Process')
$env:PYTHONPATH = ''
Push-Location -LiteralPath $nikodymVerifyRoot
try {
    & $nikodymVerifyPython $nikodymDriver --profile S0-smoke `
        --wheel $nikodymWheel.FullName --sdist $nikodymSdist.FullName `
        --workdir $nikodymS0Work --output $nikodymS0Output `
        --source-sha $nikodymCandidateSha
    if ($LASTEXITCODE -ne 0) { throw 'S0 del candidato falló' }
    & $nikodymVerifyPython $nikodymDriver --profile S3-limite `
        --wheel $nikodymWheel.FullName --sdist $nikodymSdist.FullName `
        --workdir $nikodymS3Work --output $nikodymS3Output `
        --source-sha $nikodymCandidateSha `
        --s3-bundle (Join-Path $nikodymS0Work 'scorecard-bundle')
    if ($LASTEXITCODE -ne 0) { throw 'S3 v2 del candidato falló' }
} finally {
    Pop-Location
    if ($null -eq $nikodymPreviousPythonPath) {
        Remove-Item Env:\PYTHONPATH -ErrorAction SilentlyContinue
    } else {
        $env:PYTHONPATH = $nikodymPreviousPythonPath
    }
}
```

Reconciliar schema, estado, hashes, backend, terminación, condiciones y la matriz exacta
N−1/N/N+1:

```powershell
$nikodymS0 = Get-Content -Raw -Encoding UTF8 -LiteralPath $nikodymS0Output | ConvertFrom-Json
$nikodymS3 = Get-Content -Raw -Encoding UTF8 -LiteralPath $nikodymS3Output | ConvertFrom-Json
if ($nikodymS0.schema_version -ne 'nikodym.readiness.w1.v1') { throw 'schema S0 inesperado' }
if ($nikodymS0.profile_status -ne 'pass') { throw 'S0 candidato no dio pass' }
if ($nikodymS3.schema_version -ne 'nikodym.readiness.w1.v2') { throw 'schema S3 no es v2' }
if ($nikodymS3.profile_status -ne 'pass') { throw 'S3 candidato no dio pass' }
if ($nikodymS3.source_sha -ne $nikodymCandidateSha) { throw 'source_sha S3 no reconcilia' }
if ($nikodymS3.supervisor.backend -ne 'windows_job_object') { throw 'backend S3 inesperado' }
if ($nikodymS3.supervisor.outcome -ne 'normal') { throw 'S3 no terminó normalmente' }
if ($nikodymS3.supervisor.returncode.signed -ne 0) { throw 'worker S3 no retornó 0' }
$nikodymFalseConditions = @(
    $nikodymS3.pass_conditions.PSObject.Properties | Where-Object { $_.Value -ne $true }
)
if ($nikodymFalseConditions.Count -ne 0) { throw 'hay condiciones S3 falsas' }
$nikodymWheelHash = (
    Get-FileHash -Algorithm SHA256 -LiteralPath $nikodymWheel.FullName
).Hash.ToLowerInvariant()
$nikodymSdistHash = (
    Get-FileHash -Algorithm SHA256 -LiteralPath $nikodymSdist.FullName
).Hash.ToLowerInvariant()
if ($nikodymS3.cleanroom.wheel_sha256 -ne $nikodymWheelHash) { throw 'wheel hash S3 difiere' }
if ($nikodymS3.cleanroom.sdist_sha256 -ne $nikodymSdistHash) { throw 'sdist hash S3 difiere' }

$nikodymExpectedLimits = [ordered]@{
    train_rows = [ordered]@{'999999'='accepted';'1000000'='accepted';'1000001'='rejected'}
    train_variables = [ordered]@{'99'='accepted';'100'='accepted';'101'='rejected'}
    train_cardinality = [ordered]@{'99999'='accepted';'100000'='accepted';'100001'='rejected'}
    batch_rows = [ordered]@{'4999999'='accepted';'5000000'='accepted';'5000001'='rejected'}
}
foreach ($nikodymFamily in $nikodymExpectedLimits.Keys) {
    $nikodymExpectedCases = $nikodymExpectedLimits[$nikodymFamily]
    $nikodymObservedCases = $nikodymS3.limits.$nikodymFamily.PSObject.Properties
    if (@($nikodymObservedCases).Count -ne $nikodymExpectedCases.Count) {
        throw "cantidad de casos S3 incorrecta: $nikodymFamily"
    }
    foreach ($nikodymCase in $nikodymExpectedCases.Keys) {
        if ($nikodymS3.limits.$nikodymFamily.$nikodymCase -ne $nikodymExpectedCases[$nikodymCase]) {
            throw "clasificación S3 incorrecta: $nikodymFamily/$nikodymCase"
        }
    }
}
```

Importar ambos JSON y el manifiesto del candidato a nombres privados nuevos **antes** de borrar los
temporales. La copia debe conservar exactamente los bytes medidos:

```powershell
$nikodymEvidenceStamp = Get-Date -Format 'yyyy-MM-dd-HHmmss'
$nikodymEvidenceSuffix = $nikodymCandidateSha.Substring(0,12)
$nikodymEvidenceNonce = [guid]::NewGuid().ToString('N').Substring(0,8)
$nikodymPrivateEvidence = Join-Path $nikodymRepo 'privado\evidencia'
$nikodymPrivateS0 = Join-Path $nikodymPrivateEvidence (
    "readiness-w1-s0-candidate-$nikodymEvidenceStamp-$nikodymEvidenceSuffix-$nikodymEvidenceNonce.json"
)
$nikodymPrivateS3 = Join-Path $nikodymPrivateEvidence (
    "readiness-w1-s3-v2-$nikodymEvidenceStamp-$nikodymEvidenceSuffix-$nikodymEvidenceNonce.json"
)
$nikodymPrivateManifest = Join-Path $nikodymPrivateEvidence (
    "readiness-w1-candidate-sha256-$nikodymEvidenceStamp-$nikodymEvidenceSuffix-$nikodymEvidenceNonce.txt"
)
foreach ($nikodymDestination in @(
    $nikodymPrivateS0,$nikodymPrivateS3,$nikodymPrivateManifest
)) {
    if (Test-Path -LiteralPath $nikodymDestination) {
        throw "la evidencia privada no se sobrescribe: $nikodymDestination"
    }
}
Copy-Item -LiteralPath $nikodymS0Output -Destination $nikodymPrivateS0
Copy-Item -LiteralPath $nikodymS3Output -Destination $nikodymPrivateS3
Copy-Item -LiteralPath $nikodymManifest -Destination $nikodymPrivateManifest
if ((Get-FileHash -Algorithm SHA256 -LiteralPath $nikodymS0Output).Hash -ne
    (Get-FileHash -Algorithm SHA256 -LiteralPath $nikodymPrivateS0).Hash) {
    throw 'la copia privada S0 difiere'
}
if ((Get-FileHash -Algorithm SHA256 -LiteralPath $nikodymS3Output).Hash -ne
    (Get-FileHash -Algorithm SHA256 -LiteralPath $nikodymPrivateS3).Hash) {
    throw 'la copia privada S3 v2 difiere'
}
if ((Get-FileHash -Algorithm SHA256 -LiteralPath $nikodymManifest).Hash -ne
    (Get-FileHash -Algorithm SHA256 -LiteralPath $nikodymPrivateManifest).Hash) {
    throw 'la copia privada de SHA256SUMS difiere'
}
```

Sólo después de importar y hashear esa evidencia, eliminar los temporales mediante las funciones
validadas de §2.5:

```powershell
Remove-NikodymTempDirectory -LiteralPath $nikodymVerifyRoot
Remove-NikodymTempDirectory -LiteralPath $nikodymCandidateDir
Remove-NikodymTempDirectory -LiteralPath $nikodymSourceView
Remove-NikodymTempFile -LiteralPath $nikodymSourceArchive
```

S3 verde no convierte W1 en PASS si S2 sigue pendiente o el hardware H9=B no está demostrado.

## 10. Liberación y cierre

Antes de entregar:

- detener todo proceso iniciado en la sesión y cerrar el navegador automatizado;
- inspeccionar y eliminar sólo artefactos generados por la sesión: `web/dist/`, `.playwright-mcp/`,
  `site/`, `reports/` y workdirs temporales conocidos;
- no borrar por patrón amplio ni asumir que un artefacto ignorado es propio;
- verificar procesos por PID/comando y revisar ambos repos:

```powershell
foreach ($nikodymTrackedPid in @($nikodymSessionPids)) {
    $nikodymTrackedProcess = Get-Process -Id $nikodymTrackedPid -ErrorAction SilentlyContinue
    if ($null -ne $nikodymTrackedProcess) {
        try {
            Stop-Process -InputObject $nikodymTrackedProcess -Force -ErrorAction Stop
            Wait-Process -Id $nikodymTrackedPid -Timeout 10 -ErrorAction SilentlyContinue
        } catch {
            if ($null -ne (Get-Process -Id $nikodymTrackedPid -ErrorAction SilentlyContinue)) {
                throw "no se pudo detener PID propio: $nikodymTrackedPid"
            }
        }
    }
    if ($null -ne (Get-Process -Id $nikodymTrackedPid -ErrorAction SilentlyContinue)) {
        throw "PID propio persiste tras cleanup: $nikodymTrackedPid"
    }
}
Get-CimInstance Win32_Process |
    Where-Object {
        $_.ProcessId -ne $PID -and
        $_.Name -in @('python.exe','node.exe','uv.exe') -and
        (
            $_.Name -eq 'uv.exe' -or
            $_.CommandLine -match 'nikodym\.ui|uvicorn|vite|pytest|vitest|measure_readiness'
        )
    } |
    Select-Object ProcessId,ParentProcessId,Name,CommandLine
git status --short --branch
if ($LASTEXITCODE -ne 0) { throw 'status final público falló' }
git -C privado status --short --branch
if ($LASTEXITCODE -ne 0) { throw 'status final privado falló' }
```

Sólo ahora actualizar `privado/HANDOFF.md` con HEAD público definitivo, run y jobs de CI/deploy,
gates medidos, limpieza, abiertos exactos y siguiente decisión de Cami. El archivo raíz es sólo el
symlink: nunca reemplazarlo por un archivo regular. Stagear, revisar, commitear y pushear el repo
privado **después** de esa actualización:

```powershell
git -C privado add -- RUTAS_PRIVADAS_EXACTAS
if ($LASTEXITCODE -ne 0) { throw 'stage privado falló' }
git -C privado diff --cached --check
if ($LASTEXITCODE -ne 0) { throw 'diff cached privado falló' }
git -C privado diff --cached --stat
if ($LASTEXITCODE -ne 0) { throw 'stat cached privado falló' }
git -C privado diff --cached --name-status
if ($LASTEXITCODE -ne 0) { throw 'censo cached privado falló' }
git -C privado commit -m "docs: actualiza el relevo"
if ($LASTEXITCODE -ne 0) { throw 'commit privado falló' }
git -C privado push origin main
if ($LASTEXITCODE -ne 0) { throw 'push privado falló' }
```

Si el CI obliga a corregir y crear otro commit público, repetir su push/verificación antes de cerrar
el HANDOFF. Confirmar al final:

```powershell
$nikodymHandoff = Get-Item -Force -LiteralPath 'HANDOFF.md'
if ($nikodymHandoff.LinkType -ne 'SymbolicLink') { throw 'HANDOFF.md dejó de ser symlink' }
$nikodymHandoffTarget = [IO.Path]::GetFullPath([string]$nikodymHandoff.Target)
if ($nikodymHandoffTarget -ne $nikodymExpectedHandoff) {
    throw "target HANDOFF final inesperado: $nikodymHandoffTarget"
}
if (-not (Test-Path -LiteralPath $nikodymHandoffTarget -PathType Leaf)) {
    throw 'target HANDOFF final ausente'
}
git status --short --branch
if ($LASTEXITCODE -ne 0) { throw 'status final público falló' }
git -C privado status --short --branch
if ($LASTEXITCODE -ne 0) { throw 'status final privado falló' }
```
