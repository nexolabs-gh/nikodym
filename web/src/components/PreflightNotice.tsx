import { CircleCheck, Loader2, TriangleAlert } from "lucide-react"

import type { PreflightMismatch } from "@/lib/api"
import {
  canJumpTo,
  mismatchesForSection,
  preflightHeadline,
  type PreflightState,
} from "@/lib/preflight"

interface PreflightNoticeProps {
  state: PreflightState
  /**
   * Si viene, se pintan SÓLO los desajustes de esa sección de config (uso desde Configuración,
   * que muestra una sección por vez). Sin ella se pintan todos (uso desde Datos).
   */
  section?: string
  /** Salto al campo. Sin este callback los desajustes se listan como texto, sin navegar. */
  onJump?: (mismatch: PreflightMismatch) => void
}

/**
 * Aviso del preflight config↔dataset (enmienda PREFLIGHT-DATASET, D-PRE-8).
 *
 * Presenta el veredicto que produjo el backend: NO decide nada ni reinterpreta los mensajes, que
 * ya vienen en español y sin códigos internos y se pintan tal cual (SDD-23 §3.3). Cada desajuste
 * trae su `path`, y con él el salto al campo que lo arregla.
 *
 * **Informa, no bloquea** (D-PRE-5): este componente nunca deshabilita nada. La corrida sigue
 * siendo la autoridad sobre sí misma; el preflight sólo adelanta lo que ya se sabe antes de pagar
 * una corrida para descubrirlo.
 */
export function PreflightNotice({ state, section, onJump }: PreflightNoticeProps) {
  // Vista de una sección: sólo sus desajustes, y nada más. El «todo calza» global no se repite en
  // cada sección del formulario —sería una afirmación sobre campos que esta vista no muestra—.
  if (section !== undefined) {
    const propios = mismatchesForSection(state, section)
    if (propios.length === 0) return null
    return (
      <Panel tone="warn">
        <p className="font-medium">
          {propios.length === 1
            ? "1 campo de esta sección nombra una columna que el dataset no tiene."
            : `${propios.length} campos de esta sección nombran columnas que el dataset no tiene.`}
        </p>
        <MismatchList mismatches={propios} onJump={onJump} />
      </Panel>
    )
  }

  if (state.kind === "checking") {
    return (
      <Panel tone="muted">
        <p className="inline-flex items-center gap-1.5">
          <Loader2 className="size-3.5 animate-spin" aria-hidden="true" />
          Comparando el config con las columnas del dataset…
        </p>
      </Panel>
    )
  }

  // `idle` (sin dataset o config aún inválido) y `unreachable` no dicen nada: un veredicto que no
  // se pudo obtener no se inventa. Con el backend caído el usuario ya tiene el aviso de la
  // validación en vivo, y encimar otro sería ruido sobre la misma causa.
  if (state.kind === "idle" || state.kind === "unreachable") return null

  const titulo = preflightHeadline(state)
  if (titulo === null) return null

  if (state.kind === "ok") {
    return (
      <Panel tone="ok">
        <p className="inline-flex items-center gap-1.5">
          <CircleCheck className="size-3.5 shrink-0" aria-hidden="true" />
          {titulo}
        </p>
      </Panel>
    )
  }

  return (
    <Panel tone="warn">
      <p className="flex items-start gap-1.5 font-medium">
        <TriangleAlert className="mt-0.5 size-3.5 shrink-0" aria-hidden="true" />
        <span>{titulo}</span>
      </p>
      <p className="mt-1 opacity-90">
        Puedes ejecutar de todos modos: esto es un aviso, no un bloqueo. Corregir los nombres
        antes evita una corrida que probablemente falle.
      </p>
      <MismatchList mismatches={state.mismatches} onJump={onJump} />
      {state.uninspected.length > 0 ? (
        <p className="mt-3 opacity-90">
          {state.uninspected.length === 1
            ? `Además, la sección «${state.uninspected[0]}» no se pudo comparar: esta instalación no sabe leerla, así que no se afirma nada sobre ella.`
            : `Además, ${state.uninspected.length} secciones no se pudieron comparar (${state.uninspected.join(", ")}): esta instalación no sabe leerlas, así que no se afirma nada sobre ellas.`}
        </p>
      ) : null}
    </Panel>
  )
}

/**
 * Lista de desajustes; cada uno salta a su campo si hay `onJump` **y** su sección está en el
 * formulario. Los de una sección que el formulario no ofrece se listan como texto con la razón a
 * la vista: un botón que no lleva a ninguna parte es peor que no tener botón.
 */
function MismatchList({
  mismatches,
  onJump,
}: {
  mismatches: readonly PreflightMismatch[]
  onJump?: (mismatch: PreflightMismatch) => void
}) {
  if (mismatches.length === 0) return null
  // La lista es TOTAL por diseño (D-PRE-2) y el caso real trae 15 desajustes, que empujaban el
  // resto de la página fuera de vista. Se muestran todos, pero scrollean dentro del aviso.
  return (
    <ul className="mt-2 max-h-72 space-y-1.5 overflow-y-auto pr-1">
      {mismatches.map((m) => (
        <li key={`${m.path}·${m.declared}`}>
          {onJump && canJumpTo(m) ? (
            <button
              type="button"
              onClick={() => onJump(m)}
              className="w-full rounded-md px-2 py-1.5 text-left underline-offset-2 hover:bg-foreground/[0.06] hover:underline focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
              title="Ir al campo en Configuración"
            >
              <MismatchBody mismatch={m} />
            </button>
          ) : (
            <div className="px-2 py-1.5">
              <MismatchBody mismatch={m} />
            </div>
          )}
        </li>
      ))}
    </ul>
  )
}

/** El mensaje del motor, tal cual, con su ruta de config debajo en monoespaciada. */
function MismatchBody({ mismatch }: { mismatch: PreflightMismatch }) {
  return (
    <>
      <span className="block">{mismatch.message}</span>
      <span className="mt-0.5 block font-mono text-[0.68rem] opacity-70">
        {mismatch.path}
      </span>
      {canJumpTo(mismatch) ? null : (
        <span className="mt-0.5 block text-[0.68rem] opacity-70">
          Este campo todavía no se edita desde el formulario: ajústalo en el YAML del config.
        </span>
      )}
    </>
  )
}

/** Contenedor del aviso, con el mismo lenguaje visual que el resto de avisos del workspace. */
function Panel({
  tone,
  children,
}: {
  tone: "ok" | "warn" | "muted"
  children: React.ReactNode
}) {
  const clase =
    tone === "warn"
      ? "border-amber-400/30 bg-amber-400/[0.06] text-amber-100/90"
      : tone === "ok"
        ? "border-brand-cyan/25 bg-brand-cyan/5 text-muted-foreground"
        : "border-border bg-foreground/[0.02] text-muted-foreground"
  return (
    <div
      role="status"
      aria-live="polite"
      className={`rounded-lg border px-3 py-2.5 text-xs ${clase}`}
    >
      {children}
    </div>
  )
}
