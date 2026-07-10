/**
 * Símbolo de marca Nikodym (la "N" como red neuronal de dos capas: nodos de entrada =
 * datos crudos → nodos de salida = señal priorizada). SVG inline 1:1 del kit de marca,
 * theme-aware: sobre navy la N es blanca y la salida cyan (`fondo-oscuro`); sobre papel
 * la N es navy y la salida azul (`fondo-claro`). Viaja con el bundle (sin request extra)
 * y escala nítido. El tamaño se controla por className.
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
      {/* Conexiones: azul acento tenue, igual en ambos temas */}
      <g stroke="#2E6FF2" strokeWidth="1.8" opacity="0.42">
        <line x1="14" y1="14" x2="50" y2="14" />
        <line x1="14" y1="14" x2="50" y2="32" />
        <line x1="14" y1="32" x2="50" y2="14" />
        <line x1="14" y1="32" x2="50" y2="32" />
        <line x1="14" y1="32" x2="50" y2="50" />
        <line x1="14" y1="50" x2="50" y2="32" />
        <line x1="14" y1="50" x2="50" y2="50" />
      </g>
      {/* Trazo de la N + nodos de entrada: navy sobre claro, blanco sobre oscuro */}
      <path
        d="M14 50 V14 L50 50 V14"
        fill="none"
        strokeWidth="5"
        strokeLinecap="round"
        strokeLinejoin="round"
        className="stroke-[#0A2240] dark:stroke-white"
      />
      <g className="fill-[#0A2240] dark:fill-white">
        <circle cx="14" cy="14" r="4.5" />
        <circle cx="14" cy="32" r="4.5" />
        <circle cx="14" cy="50" r="4.5" />
      </g>
      {/* Nodos de salida: azul sobre claro, cyan sobre oscuro */}
      <g className="fill-[#1859E0] dark:fill-brand-cyan">
        <circle cx="50" cy="14" r="4.5" />
        <circle cx="50" cy="32" r="4.5" />
        <circle cx="50" cy="50" r="4.5" />
      </g>
    </svg>
  )
}
