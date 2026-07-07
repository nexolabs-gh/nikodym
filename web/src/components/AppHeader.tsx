/** Marca Nikodym para el header del sidebar: punto cyan + wordmark. Sin lógica.
 *  En rail angosto (< lg) se muestra solo el punto; el wordmark aparece en lg+. */
export function AppHeader() {
  return (
    <div className="flex items-center gap-3 px-3 py-5 lg:px-4">
      <span
        className="size-2.5 shrink-0 rounded-full bg-brand-cyan shadow-[0_0_16px_2px_rgba(79,195,232,0.45)]"
        aria-hidden="true"
      />
      <div className="hidden items-baseline gap-2 lg:flex">
        <span className="font-display text-lg font-bold tracking-tight text-brand-offwhite">
          Nikodym
        </span>
        <span className="font-mono text-[0.7rem] uppercase tracking-[0.18em] text-brand-placeholder">
          RiskLib
        </span>
      </div>
    </div>
  )
}
