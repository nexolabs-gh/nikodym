# CLAUDE.md — Nikodym RiskLib

@AGENTS.md

> `AGENTS.md` es la fuente de verdad del contexto de trabajo (común a Claude Code y Codex). Mantener ambos coherentes.
> Para arrancar una sesión, leer primero [`HANDOFF.md`](HANDOFF.md).
> Nikodym `1.5.0` está en PyPI (tag `v1.5.0`, 2026-07-22, cierre del bloque **B1**); el proyecto ya no está en construcción por capas sino en mejora continua. El **track pre-Interbank está completo** (IBK-01…05 cerradas); no hay bloque IBK siguiente, y el freeze de artefactos terminó con la reunión del 2026-07-22. El plan vigente son los bloques **B1…B8** del `ROADMAP`: el bloque en curso es **B2** (UI instalable), que habilita `1.6.0` — **B2.0, B2.1 y B2.2 están cerrados** (B2.2 —launcher, runtime y seguridad— el 2026-07-24, con los 16 jobs del CI verdes); sus decisiones quedaron **consolidadas en SDD-23 y SDD-25**, así que `docs/design/_ENMIENDA-B2.2.md` es ya registro histórico y no contrato vigente. El siguiente nodo es **B2.3** (`[ui]`, uploads y presets), que exige su propia enmienda antes de programar.
>
> **Taxonomía de marcas (2026-07-25, ejecutada y publicada):** un aviso declarado se marca
> `FALTA-DATO` si la carencia es **del motor** (9 códigos + 2 `pending_items` CMF) o
> `DATO-INSTITUCIONAL` si el dato **lo aporta la institución** (34). El contrato vive en
> `src/nikodym/core/markers.py` y **ningún filtro debe comparar el literal**: se consume
> `is_declared_warning()`. Un código interno **nunca** va al copy público: ahí se explica la
> limitación en el idioma del lector.
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
> **Auto-desarrollo: SOLO cuando Cami lo pida explícitamente** (skill `/auto-desarrollo-claude`). En trabajo normal, usar workflows y subagentes con normalidad, sin pedir permiso cada vez — ver `AGENTS.md` §Auto-desarrollo. La maquinaria tmux/Codex multi-motor está FROZEN (histórica).
