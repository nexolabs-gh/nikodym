import { NikodymMark } from "@/components/NikodymMark"

/** Marca Nikodym para el header del sidebar: símbolo N-red + wordmark. Sin lógica.
 *  En rail angosto (< lg) se muestra solo el símbolo; el wordmark aparece en lg+.
 *  Con `onHome`, la marca es un botón que vuelve a la landing/launcher. */
export function AppHeader({ onHome }: { onHome?: () => void }) {
  const content = (
    <>
      <NikodymMark className="size-7 shrink-0" />
      <div className="hidden items-baseline gap-2 lg:flex">
        <span className="font-display text-lg font-bold tracking-tight text-brand-offwhite">
          Nikodym
        </span>
        <span className="font-mono text-[0.7rem] uppercase tracking-[0.18em] text-brand-placeholder">
          RiskLib
        </span>
      </div>
    </>
  )

  if (onHome) {
    return (
      <button
        type="button"
        onClick={onHome}
        title="Volver a los modelos"
        aria-label="Volver a los modelos"
        className="flex items-center gap-3 rounded-lg px-3 py-5 text-left transition-colors hover:bg-white/5 lg:px-4"
      >
        {content}
      </button>
    )
  }

  return <div className="flex items-center gap-3 px-3 py-5 lg:px-4">{content}</div>
}
