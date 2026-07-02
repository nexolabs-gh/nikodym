# AUTONOMY — Nikodym RiskLib (modo auto-desarrollo)

> Playbook **específico** del proyecto para las corridas autónomas nocturnas. El **ciclo** vive en la
> skill `auto-desarrollo` §2 (rescate §4) y en el `ORQUESTA.md` del maestro AutoDesarrollo. Aquí solo lo
> propio de Nikodym. Bitácora: `AUTONOMY-LOG.md`. Cola de trabajo: bloque "Backlog priorizado" del `HANDOFF.md`.

## Cómo se opera (resumen)
- El latido está **PAUSADO**. No hay scheduler/watchdog/maestro/revisor/gates corriendo; queda solo
  `autodev-caffeine`. El worker `tmux nikodym` se cierra al terminar cada corrida.
- La corrida supervisada real del 2026-07-02 ya se ejecuto sobre B21.4. Llego a gates verdes, pero
  el revisor rechazo tras 2 ciclos; el codigo se descarto y el siguiente intento debe partir por
  agregacion real de `SensitivitySweepConfig.group_cols`.
- La maquinaria de AutoDesarrollo es **multi-motor por rol**. El perfil actual recomendado para reanudar es
  `AUTODESARROLLO_PERFIL=codex-only`, pero también existen sesiones `claude-only` o mixtas vía
  `MAESTRO_MOTOR`, `WORKER_MOTOR`/`MOTOR`, `REVISOR_MOTOR` y `PLANIFICADOR_MOTOR`.
- Un **maestro fresco** (scheduler-loop en tmux `autodev-cron`) abre una corrida, toma el primer ítem `[ ]` del
  backlog, se lo asigna a un **worker** en el tmux `nikodym`, monitorea, **revisa el diff + corre los gates +
  lo somete a un revisor independiente BLOQUEANTE + pushea él** (R7), y reescribe el HANDOFF.
- El maestro **NO** escribe código (R1); el worker sí. El worker deja el working tree VERDE pero **sin
  commitear** — el maestro revisa y commitea/pushea.

## Comandos de verificación (los 4 gates — TODOS verdes, en orden)
Sincronizar entorno (solo si hace falta; el `.venv` ya existe):
```
uv sync --no-default-groups --group test --group lint --python 3.12
```
Gates:
```
uv run --no-sync ruff check .
uv run --no-sync ruff format --check .
uv run --no-sync mypy
uv run --no-sync pytest -q --cov=nikodym --cov-report=term-missing      # cobertura 100% global
uv build
```
Gate regulatorio (100% en módulos críticos):
```
uv run --no-sync coverage run -m pytest
uv run --no-sync coverage report --include="*/nikodym/core/exceptions.py,*/nikodym/core/seeding.py,*/nikodym/provisioning/cmf/__init__.py,*/nikodym/provisioning/ifrs9/__init__.py" --fail-under=100
```
Núcleo liviano (core no arrastra data/pandera/pyarrow/pandas/tracking/mlflow):
```
uv run --no-sync python -c "import nikodym.core, sys; assert not [m for m in ('nikodym.data','pandera','pyarrow','pandas','nikodym.tracking','mlflow') if m in sys.modules]"
```

## Convenciones que el worker DEBE respetar
- **Mixto-troncal-más-incremental**: nunca avanzar en rojo; reabrir un SDD por feedback del código es esperado y barato.
- `mypy --strict` GLOBAL. Ruff (E,F,I,N,UP,B,SIM,RUF,D) con **docstrings en español**.
- **Inglés** para APIs/variables; **español** para docs/comentarios/mensajes de error.
- Tests canónicos con **golden values**; `filterwarnings=error` (un warning sin manejar rompe el test).
- Reproducibilidad total: `data_hash`/`config_hash` con endianness explícito `<u8`; normalizar `-0.0→0.0`.
- `import pandera.pandas as pa` (NUNCA `import pandera`). Prohibido `eval`/`df.eval` (allowlist de operadores).
- NO cobertura por submódulo (`--cov=nikodym.core.x` → double-load numpy). NO `model_rebuild()` (Pydantic 2.13).
  NO `Field(strict=True)` sobre uniones. Defaults de `Field` por keyword (`default=`), no posicional.
- `ruff` respeta `.gitignore`: si un paquete fuente cae bajo patrón ignorado, lo salta (verde falso) →
  verificar el wheel / `git status` al añadir subpaquetes (el patrón de datos es `/data/`, anclado a raíz).

## Commits y push
- Mensajes estilo repo: `feat(data): B2b.x — <qué> (verde, 100%)` / `docs:` / `fix:`. Ver `git log --oneline`.
- No inventar coautoría. Agregar trailer solo si la herramienta/entorno realmente lo requiere; con perfil full Codex
  no se agrega trailer de Claude. Si participaron motores distintos, documentar la combinación en HANDOFF/bitácora.
- **Push directo a `main`** autorizado (repo privado `nexolabs-gh/nikodym`). `add` EXPLÍCITO, nunca `git add .` a ciegas.

## Particularidades / bloqueos posibles
- Repo **privado** en GitHub vía HTTPS: el push necesita credencial git válida en la máquina. Si el push
  falla, dejar commit local + `⚠ push falló: <motivo>` en el HANDOFF (no reintentar a ciegas).
- Codex se **auto-actualiza** al 1er arranque y a veces el goal queda como `[Pasted Content]` sin enviar →
  el maestro manda `Enter` extra y verifica que aparezca `Working` (paso 4 del ciclo).
- Decisión de producto / normativa CMF ambigua → R0: NO improvisar; saltar el ítem o dejar `⚠ BLOQUEADO`.

## Cadencia e infraestructura
- **Scheduler-loop en tmux `autodev-cron`** (`scripts/scheduler-loop.sh`), actualmente apagado. NO launchd: en macOS launchd no
  accede a `~/Documents` por TCC (`Operation not permitted`); el tmux server, lanzado por el terminal, sí.
  Pausa 600s entre corridas; **AUTO-PAUSA** tras corridas sin avance (backlog agotado → se detiene y avisa).
- Wrapper de una corrida: `…/AutoDesarrollo/scripts/auto-ciclo-maestro.sh`. Prompt del maestro:
  `…/AutoDesarrollo/scripts/prompt-maestro-nocturno.md`. Revisor: `…/AutoDesarrollo/scripts/prompt-revisor.md`.
- Locks: OS (`/tmp/autodesarrollo-nikodym.lockd`, atómico) + aplicación (bloque "Modo autónomo" del HANDOFF).
- Logs: `…/AutoDesarrollo/logs/scheduler.log`, `maestro-<fecha>.log`, índice `cron.log`.
- Anti-sleep: `caffeinate` (el Mac debe quedar encendido/enchufado y sin cerrar la tapa).
- **Parar:** `tmux kill-session -t autodev-cron`. **Relanzar ejemplo actual:**
  `tmux new-session -d -s autodev-cron -c /Users/camilogonzalez/Documents/Proyectos/AutoDesarrollo 'AUTODESARROLLO_PERFIL=codex-only MAX_CORRIDA=5400 LIMITE_VACIAS=3 bash scripts/scheduler-loop.sh 2>&1 | tee -a logs/scheduler.log'`
  Para full Claude o mixto, cambiar `AUTODESARROLLO_PERFIL`/roles antes de relanzar.

> El ciclo completo está en la skill **auto-desarrollo** §2; rescate de corridas cortadas en §4.
