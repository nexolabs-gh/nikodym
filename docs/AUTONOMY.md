# AUTONOMY — Nikodym RiskLib (modo auto-desarrollo)

> Playbook **específico** del proyecto para las corridas autónomas nocturnas. El **ciclo** vive en la
> skill `auto-desarrollo` §2 (rescate §4) y en el `ORQUESTA.md` del maestro AutoDesarrollo. Aquí solo lo
> propio de Nikodym. Bitácora: `AUTONOMY-LOG.md`. Cola de trabajo: bloque "Backlog priorizado" del `HANDOFF.md`.

## Cómo se opera (resumen)
- Un **maestro fresco** (cron horario, Claude Opus, effort máximo) abre una corrida, toma el primer ítem
  `[ ]` del backlog, se lo asigna a un **worker Codex** (`gpt-5.5 xhigh fast`) en el tmux `nikodym`,
  monitorea, **revisa el diff + corre los gates + pushea él** (R7), y reescribe el HANDOFF.
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
- Trailer obligatorio: `Co-Authored-By: Claude <noreply@anthropic.com>`.
- **Push directo a `main`** autorizado (repo privado `nexolabs-gh/nikodym`). `add` EXPLÍCITO, nunca `git add .` a ciegas.

## Particularidades / bloqueos posibles
- Repo **privado** en GitHub vía HTTPS: el push necesita credencial git válida en la máquina. Si el push
  falla, dejar commit local + `⚠ push falló: <motivo>` en el HANDOFF (no reintentar a ciegas).
- Codex se **auto-actualiza** al 1er arranque y a veces el goal queda como `[Pasted Content]` sin enviar →
  el maestro manda `Enter` extra y verifica que aparezca `Working` (paso 4 del ciclo).
- Decisión de producto / normativa CMF ambigua → R0: NO improvisar; saltar el ítem o dejar `⚠ BLOQUEADO`.

## Cadencia e infraestructura
- Cron horario al minuto **:17** (launchd `cl.nexolabs.autodesarrollo.nikodym`, plist en `~/Library/LaunchAgents/`).
- Wrapper: `…/AutoDesarrollo/scripts/auto-ciclo-maestro.sh`. Prompt del maestro: `…/AutoDesarrollo/scripts/prompt-maestro-nocturno.md`.
- Locks: OS (`/tmp/autodesarrollo-nikodym.lockd`, atómico) + aplicación (bloque "Modo autónomo" del HANDOFF).
- Logs por corrida: `…/AutoDesarrollo/logs/maestro-<fecha>.log`; índice en `…/AutoDesarrollo/logs/cron.log`.
- Anti-sleep: `caffeinate` (el Mac debe quedar encendido/enchufado y sin cerrar la tapa).

> El ciclo completo está en la skill **auto-desarrollo** §2; rescate de corridas cortadas en §4.
