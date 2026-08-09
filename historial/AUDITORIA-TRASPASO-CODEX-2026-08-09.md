# Auditoría del traspaso a Codex — 2026-08-09

> Medición read-only de entrada sobre público `9328a9c` y privado `2841ebc`. Este informe explica
> por qué se cambió la estructura; no es fuente de estado futuro. El contrato resultante vive en
> [`../AGENTS.md`](../AGENTS.md).

## 1. Tamaño y carga histórica de las fuentes anteriores

| Fuente anterior | Líneas | Bytes | Palabras | Historia medida |
|---|---:|---:|---:|---:|
| `AGENTS.md` | 1.523 | 112.874 | 16.811 | 1.236 líneas, 81,2 % |
| `CLAUDE.md` | 2.273 | 175.714 | 28.156 | 2.077 líneas, 91,4 % |
| `HANDOFF.md` | 169 | 10.284 | 1.590 | 45 líneas de abiertos vigentes, 26,6 % |

`AGENTS.md` contenía 29 bloques históricos, 20 “Siguiente:” incompatibles y 23 snapshots de
`main`. `CLAUDE.md` contenía 32 bloques históricos y otros 20 “Siguiente:”. La cronología permitía
reconstruir qué afirmación era posterior, pero ningún archivo declaraba una autoridad de estado.

## 2. La supuesta fuente común no era común

`CLAUDE.md` importaba `@AGENTS.md`; la inclusión era unidireccional. En la práctica:

- Claude Code cargaba **3.796 líneas / 288.588 bytes** —los dos corpus—.
- Codex recibía sólo **1.523 líneas / 112.874 bytes**.
- Por basename de enlaces locales había 21 destinos compartidos, 8 sólo en AGENTS y 9 sólo en
  CLAUDE.
- AGENTS nombraba 25 familias D-* y CLAUDE 33. D-CAP, D-CRP6, D-DIR, D-FTE, D-MAX, D-PRO, D-REQ y
  D-VER sólo aparecían en CLAUDE; D-MON no aparecía en ninguno de los dos.
- La lista literal de decisiones que no se debían re-litigar no existía en AGENTS, CLAUDE ni
  HANDOFF.

La frase “fuente común para Claude Code y Codex” no se sostenía como completitud ni simetría.

## 3. Integridad y drift

- AGENTS tenía 57 ocurrencias de enlaces relativos y **18 rotas**, 16 destinos únicos. Varias
  apuntaban a `design/...` desde la raíz, donde no existe ese directorio.
- CLAUDE tenía 52/52 enlaces relativos válidos; el HANDOFF privado, 2/2.
- AGENTS declaraba `main=fb73694` cuando el HEAD real era `9328a9c`; el commit intermedio era base
  de producto, no estado del repo.
- AGENTS afirmaba PyPI 1.11.0 en un bloque y 1.10.0 en otro.
- CLAUDE conservaba P4 a la vez como pendiente y terminado.

## 4. Qué conocimiento vivía dónde

| Fuente | Contenido que sólo o principalmente estaba allí |
|---|---|
| AGENTS | identidad, idioma, licencia/modelo de negocio, copy público, CMF, SDD, seguridad Git y autorización por release; mezclado con cifras caducadas |
| CLAUDE | `127.0.0.1` vs `localhost`, cuenta de `gh`, Vitest literal, dos Ruff, build como gate real, regeneración schema/bundle, trampas de DYLD y varias invariantes técnicas |
| HANDOFF | CI pendiente, dos lentes sin veredicto, seis defectos de prosa con reproducción, último gate y verificación visual |
| `docs/design/` | razonamiento contractual completo, pero estados y prescripciones históricas que no siempre reflejaban el cierre |

Ausencias comprobadas en las tres fuentes operativas:

- `.venv/bin/python` y la razón para no usar `uv run` local;
- una lista literal única de pytest, mypy, ambos Ruff, Vitest, typecheck, lint, bundle, MkDocs y
  `uv lock`;
- prohibición durable de recapturar demo, borrar CMF o proponer covariables WoE;
- “un censo es hipótesis hasta medirlo” y “control negativo en cada cierre” como contrato, no como
  anécdota.

## 5. Auditoría de las diez familias aprobadas

En 75 archivos Markdown de `docs/design/` —28.441 líneas, unos 2,235 MB— las diez familias pedidas
sumaban **66 encabezados de decisión**:

| Familia | Encabezados |
|---|---:|
| D-JUR | 8 |
| D-MON | 7, incluido D-MON-2-bis |
| D-CAP | 3 |
| D-VER | 3 |
| D-AMB | 6 |
| D-LGD | 16, incluido D-LGD-1-bis |
| D-SUB | 4 |
| D-EXI | 7 |
| D-FTE | 5 |
| D-VIS | 7 |

AGENTS sólo nombraba por ID seis de las diez familias; fuera de la historia, sólo D-JUR-3 tenía
cobertura durable explícita.

Drift reproducido:

- D-LGD y D-SUB seguían rotuladas BORRADOR en su cabecera pese a estar implementadas.
- D-LGD prescribía migrar `options` a `answer_forms`; la decisión final y el código conservaron
  `options`.
- El índice llamaba BORRADOR a D-EXI y D-FTE pese a estar aprobadas e implementadas.
- La cola de D-EXI todavía decía que D-EXI-6 tocaría un validador; se cerró con `when` en la
  superficie.
- D-FTE llamaba abierta a la pregunta de la fuente antigua después de que Cami decidiera “no
  consta”.
- D-VIS conservaba un censo propuesto de 133; el cierre migró 98 y la revisión de completitud probó
  que D-VIS-6 seguía abierto.
- D-JUR-8 seguía escrito como nodo propuesto pese a estar implementado y demostrado.

Por eso `docs/design/` no puede ser registro de estado sin una capa canónica. Los SDD conservan
razonamiento valioso, incluso alternativas refutadas; borrarlas habría destruido evidencia.

## 6. Resultado aplicado

Cami eligió la estructura A. Se implementó así:

- `AGENTS.md`: **155 líneas / 9.602 bytes**, sólo contrato durable.
- `CLAUDE.md`: **9 líneas / 375 bytes**, shim de `@AGENTS.md` sin corpus paralelo.
- `privado/HANDOFF.md`: una foto reemplazable de una página lógica.
- `docs/operacion/RUNBOOK-CODEX.md`: comandos y trampas literales.
- `docs/design/DECISIONES-VIGENTES.md`: estado, reglas finales, correcciones y gates de las diez
  familias.
- archivos anteriores en `historial/` y `privado/historial/`, preservados byte por byte y fuera de
  las superficies vigentes que barren los gates de copy.

Además se anotaron las cabeceras/entradas cuyo estado era objetivamente falso; su cuerpo histórico
no se eliminó. La nueva jerarquía separa:

1. contrato durable;
2. estado reemplazable;
3. operación reproducible;
4. decisión canónica;
5. razonamiento e historia íntegros.
