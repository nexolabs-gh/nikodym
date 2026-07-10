/**
 * Símbolo de marca Nikodym (la "N" como red neuronal de dos capas: nodos blancos de
 * entrada = datos crudos → nodos cyan de salida = señal priorizada). SVG inline 1:1 del
 * kit de marca (`nikodym-simbolo-fondo-oscuro.svg`), para fondos oscuros/navy. Viaja con
 * el bundle (sin request extra) y escala nítido. El tamaño se controla por className.
 */
export function NikodymMark({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 64 64"
      className={className}
      role="img"
      aria-label="Nikodym"
      xmlns="http://www.w3.org/2000/svg"
    >
      <g stroke="#2E6FF2" strokeWidth="1.8" opacity="0.42">
        <line x1="14" y1="14" x2="50" y2="14" />
        <line x1="14" y1="14" x2="50" y2="32" />
        <line x1="14" y1="32" x2="50" y2="14" />
        <line x1="14" y1="32" x2="50" y2="32" />
        <line x1="14" y1="32" x2="50" y2="50" />
        <line x1="14" y1="50" x2="50" y2="32" />
        <line x1="14" y1="50" x2="50" y2="50" />
      </g>
      <path
        d="M14 50 V14 L50 50 V14"
        fill="none"
        stroke="#FFFFFF"
        strokeWidth="5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle cx="14" cy="14" r="4.5" fill="#FFFFFF" />
      <circle cx="14" cy="32" r="4.5" fill="#FFFFFF" />
      <circle cx="14" cy="50" r="4.5" fill="#FFFFFF" />
      <circle cx="50" cy="14" r="4.5" fill="#4FC3E8" />
      <circle cx="50" cy="32" r="4.5" fill="#4FC3E8" />
      <circle cx="50" cy="50" r="4.5" fill="#4FC3E8" />
    </svg>
  )
}
