# Historia operativa archivada

Este directorio conserva snapshots exactos de las instrucciones episódicas anteriores al traspaso
a Codex. No es fuente de estado, autoridad ni backlog; se consulta sólo para reconstruir una
decisión o recuperar una trampa ya pagada.

| Snapshot | SHA-256 |
|---|---|
| `AGENTS-HASTA-2026-08-08.md` | `69552e1e61c410f236d030448932e6b564715ef205ba01ad63144c6de646dbe8` |
| `CLAUDE-HASTA-2026-08-08.md` | `9e76709ed3d70826f017a0a16472855ca063eebf949a08c32d7418d4770cbee0` |

Los archivos se preservan byte por byte, por lo que sus enlaces relativos conservan la forma que
tenían cuando ambos vivían en la raíz. Los symlinks `docs`, `docs_site`, `HANDOFF.md` y `privado`
son una capa de compatibilidad: hacen que todo enlace que era válido en su ubicación original siga
resolviendo en el workspace interno, sin reescribir el snapshot ni su hash. La auditoría conserva la
medición de **18 ocurrencias rotas en el origen**; la nueva ubicación hace que dos de ellas resuelvan
por accidente y quedan 16, pero el snapshot que documenta el drift no cambió.

El informe medido del cambio es
[`AUDITORIA-TRASPASO-CODEX-2026-08-09.md`](AUDITORIA-TRASPASO-CODEX-2026-08-09.md). Las fuentes
vigentes son [`../AGENTS.md`](../AGENTS.md), `HANDOFF.md` interno,
[`../docs/operacion/RUNBOOK-CODEX.md`](../docs/operacion/RUNBOOK-CODEX.md) y
[`../docs/design/DECISIONES-VIGENTES.md`](../docs/design/DECISIONES-VIGENTES.md).
