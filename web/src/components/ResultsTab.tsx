import { type ReactNode, useId } from "react"
import { ArrowRight, ChartColumn, CircleAlert, Play } from "lucide-react"

import { EmptyState } from "@/components/EmptyState"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import {
  EMPTY,
  discriminantRows,
  formatBool,
  formatCount,
  formatMetric,
  formatPValue,
  formatPercent,
  sortByIv,
} from "@/lib/results-format"
import type { Coefficient } from "@/lib/results-types"
import { useAppState } from "@/state/appStore"

interface ResultsTabProps {
  /** Navega a otra sección del shell (misma convención que RunTab: la navegación vive en App). */
  onNavigate: (section: string) => void
}

/**
 * Pestaña Resultados v1 SOBRIA (SDD-23 §1/§7.5): FORMATEA en tablas/definiciones los
 * artefactos que la corrida ya dejó en el store (`results`), sin gráficos ni cálculo
 * propio (CERO lógica de dominio: cada número viene del artefacto). Los visores premium
 * (forest, curvas WoE, gains/lift, histograma) son un bloque posterior; aquí no se adelantan.
 * Robusta a corridas `failed`/parciales: muestra el `error` y solo las secciones presentes.
 */
export function ResultsTab({ onNavigate }: ResultsTabProps) {
  const { results, lastRun, validation } = useAppState()

  // Sin resultados: estado vacío sobrio con CTA a Ejecutar (como RunTab navega a "resultados").
  if (results === null) {
    return (
      <Card className="shadow-card">
        <EmptyState
          icon={ChartColumn}
          title="Sin resultados todavía"
          description="Los artefactos de una corrida (discriminación, ajuste, coeficientes, IV y calibración) se muestran aquí en cuanto ejecutes el pipeline."
          tag="Resultados"
        />
        <CardContent className="-mt-6 flex justify-center pb-8">
          <Button
            variant="outline"
            size="sm"
            onClick={() => onNavigate("ejecutar")}
          >
            <Play aria-hidden="true" />
            Ve a Ejecutar y corre el preset
            <ArrowRight aria-hidden="true" />
          </Button>
        </CardContent>
      </Card>
    )
  }

  const failed = results.status === "failed"
  const configHash = validation.kind === "valid" ? validation.hash : null
  const runId = results.run_id || lastRun?.runId || null

  // Solo derivación/selección de artefactos ya calculados (helpers puros).
  const rows = discriminantRows(results.performance)
  const ivRows = sortByIv(results.binning?.iv_by_variable)
  const fit = results.model?.fit_statistics
  const coefs = results.model?.coefficients ?? []
  const finalFeatures = results.model?.final_features ?? []
  const sc = results.scorecard
  const cal = results.calibration

  return (
    <div className="space-y-6">
      {/* Lineage + estado de la corrida (identidad reproducible; sin cálculo propio). */}
      <Card className="shadow-card">
        <CardContent className="space-y-3">
          {failed ? (
            <p
              role="status"
              className="inline-flex items-center gap-1.5 text-sm font-medium text-amber-200/90"
            >
              <CircleAlert className="size-4" aria-hidden="true" />
              La corrida terminó con fallo — se muestran las secciones disponibles
            </p>
          ) : (
            <p className="text-sm font-medium text-brand-cyan">
              Artefactos de la corrida
            </p>
          )}

          <dl className="grid gap-1.5 font-mono text-xs text-brand-placeholder">
            <LineageRow label="run_id" value={runId} />
            <LineageRow label="config_hash" value={configHash} />
          </dl>

          {failed && results.error ? (
            <div className="rounded-lg border border-amber-400/25 bg-amber-400/5 px-3 py-2 text-xs text-amber-200/90">
              {results.error}
            </div>
          ) : null}
        </CardContent>
      </Card>

      {/* a. Discriminación: KS/AUC/Gini por partición. */}
      {rows.length > 0 ? (
        <ResultsSection
          title="Discriminación"
          description="Poder de ordenamiento por partición (máximos de la evaluación)."
        >
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-white/10 text-left text-[0.68rem] uppercase tracking-wide text-brand-placeholder">
                  <th className="py-2 pr-3 font-medium">Partición</th>
                  <NumHead>AUC</NumHead>
                  <NumHead>Gini</NumHead>
                  <NumHead>KS</NumHead>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.partition} className="border-b border-white/5">
                    <td className="py-2 pr-3 text-brand-offwhite">
                      {r.partition}
                    </td>
                    <NumCell>{formatMetric(r.auc)}</NumCell>
                    <NumCell>{formatMetric(r.gini)}</NumCell>
                    <NumCell>{formatMetric(r.ks)}</NumCell>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </ResultsSection>
      ) : null}

      {/* b. Ajuste del modelo: fit_statistics + variables finales. */}
      {fit || finalFeatures.length > 0 ? (
        <ResultsSection
          title="Ajuste del modelo"
          description="Estadísticos de la regresión logística sobre WoE."
        >
          {fit ? (
            <dl className="grid grid-cols-2 gap-x-6 gap-y-2 sm:grid-cols-3">
              <DefItem label="N obs (dev)" value={formatCount(fit.n_obs_dev)} />
              <DefItem
                label="Eventos (dev)"
                value={formatCount(fit.n_events_dev)}
              />
              <DefItem
                label="Pseudo-R² McFadden"
                value={formatMetric(fit.pseudo_r2_mcfadden)}
              />
              <DefItem label="AIC" value={formatMetric(fit.aic, 1)} />
              <DefItem label="BIC" value={formatMetric(fit.bic, 1)} />
              <DefItem
                label="LLR p-value"
                value={formatPValue(fit.llr_p_value)}
              />
              <DefItem label="Convergió" value={formatBool(fit.converged)} />
            </dl>
          ) : null}

          {finalFeatures.length > 0 ? (
            <div className="mt-4 space-y-1.5">
              <p className="text-[0.68rem] uppercase tracking-wide text-brand-placeholder">
                Variables finales ({finalFeatures.length})
              </p>
              <ul className="flex flex-wrap gap-1.5">
                {finalFeatures.map((f) => (
                  <li
                    key={f}
                    className="rounded-full border border-brand-accent-dark/30 bg-brand-accent/10 px-2.5 py-0.5 font-mono text-xs text-brand-accent-dark"
                  >
                    {f}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </ResultsSection>
      ) : null}

      {/* c. Coeficientes (sobrio, sin forest plot todavía). */}
      {coefs.length > 0 ? (
        <ResultsSection
          title="Coeficientes"
          description="Estimación de la regresión (una fila por término)."
        >
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-white/10 text-left text-[0.68rem] uppercase tracking-wide text-brand-placeholder">
                  <th className="py-2 pr-3 font-medium">Variable</th>
                  <NumHead>β</NumHead>
                  <NumHead>Std. error</NumHead>
                  <NumHead>Wald z</NumHead>
                  <NumHead>p-value</NumHead>
                  <th className="py-2 pl-3 text-right font-medium">Signo</th>
                </tr>
              </thead>
              <tbody>
                {coefs.map((c) => (
                  <CoefRow key={c.feature} coef={c} />
                ))}
              </tbody>
            </table>
          </div>
        </ResultsSection>
      ) : null}

      {/* d. IV por variable, ordenado desc. */}
      {ivRows.length > 0 ? (
        <ResultsSection
          title="IV por variable"
          description="Information Value total de cada variable (mayor a menor)."
        >
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-white/10 text-left text-[0.68rem] uppercase tracking-wide text-brand-placeholder">
                  <th className="py-2 pr-3 font-medium">Variable</th>
                  <NumHead>IV</NumHead>
                </tr>
              </thead>
              <tbody>
                {ivRows.map((r) => (
                  <tr key={r.feature} className="border-b border-white/5">
                    <td className="py-2 pr-3 font-mono text-brand-offwhite">
                      {r.feature}
                    </td>
                    <NumCell>{formatMetric(r.iv)}</NumCell>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </ResultsSection>
      ) : null}

      {/* e. Escala / calibración (compacto). */}
      {sc || cal ? (
        <ResultsSection
          title="Escala y calibración"
          description="Parámetros de la scorecard y del anclaje de PD."
        >
          <dl className="grid grid-cols-2 gap-x-6 gap-y-2 sm:grid-cols-3">
            {sc ? (
              <>
                <DefItem label="PDO" value={formatMetric(sc.pdo, 1)} />
                <DefItem
                  label="Score mín."
                  value={formatMetric(sc.min_score, 1)}
                />
                <DefItem
                  label="Score máx."
                  value={formatMetric(sc.max_score, 1)}
                />
              </>
            ) : null}
            {cal ? (
              <>
                <DefItem
                  label="PD objetivo"
                  value={formatPercent(cal.target_pd)}
                />
                <DefItem
                  label="Ranking preservado"
                  value={formatBool(cal.ranking_preserved)}
                />
                <DefItem label="Método" value={cal.method} mono />
              </>
            ) : null}
          </dl>
        </ResultsSection>
      ) : null}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Sub-componentes locales (presentación pura; no exportados)
// ---------------------------------------------------------------------------

/** Sección envuelta en Card con encabezado accesible (region etiquetada por su título). */
function ResultsSection({
  title,
  description,
  children,
}: {
  title: string
  description?: string
  children: ReactNode
}) {
  const headingId = useId()
  return (
    <Card className="shadow-card" aria-labelledby={headingId}>
      <CardContent className="space-y-4">
        <div className="space-y-1">
          <h2
            id={headingId}
            className="font-heading text-base font-medium text-brand-offwhite"
          >
            {title}
          </h2>
          {description ? (
            <p className="text-xs text-brand-placeholder">{description}</p>
          ) : null}
        </div>
        {children}
      </CardContent>
    </Card>
  )
}

/** Fila del lineage (dt/dd mono, truncada con title para el hover). */
function LineageRow({ label, value }: { label: string; value: string | null }) {
  return (
    <div className="flex justify-between gap-3">
      <dt className="shrink-0 text-brand-gray">{label}</dt>
      <dd className="min-w-0 truncate text-right" title={value ?? undefined}>
        {value ?? EMPTY}
      </dd>
    </div>
  )
}

/** Ítem de definición (label arriba, valor mono tabular abajo). */
function DefItem({
  label,
  value,
  mono = true,
}: {
  label: string
  value: string
  mono?: boolean
}) {
  return (
    <div className="space-y-0.5">
      <dt className="text-[0.68rem] uppercase tracking-wide text-brand-placeholder">
        {label}
      </dt>
      <dd
        className={
          mono
            ? "font-mono tabular-nums text-brand-offwhite"
            : "text-brand-offwhite"
        }
      >
        {value}
      </dd>
    </div>
  )
}

/** Encabezado numérico de tabla (alineado a la derecha). */
function NumHead({ children }: { children: ReactNode }) {
  return <th className="py-2 pl-3 text-right font-medium">{children}</th>
}

/** Celda numérica de tabla (mono, tabular, alineada a la derecha). */
function NumCell({ children }: { children: ReactNode }) {
  return (
    <td className="py-2 pl-3 text-right font-mono tabular-nums text-brand-gray">
      {children}
    </td>
  )
}

/** Fila de coeficiente: el signo esperado se marca solo si el backend lo evaluó (sign_ok). */
function CoefRow({ coef }: { coef: Coefficient }) {
  return (
    <tr className="border-b border-white/5">
      <td className="py-2 pr-3 font-mono text-brand-offwhite">
        {coef.feature}
      </td>
      <NumCell>{formatMetric(coef.beta)}</NumCell>
      <NumCell>{formatMetric(coef.standard_error)}</NumCell>
      <NumCell>{formatMetric(coef.wald_z)}</NumCell>
      <NumCell>{formatPValue(coef.p_value)}</NumCell>
      <td className="py-2 pl-3 text-right">
        {coef.sign_ok === null ? (
          <span className="text-brand-placeholder">{EMPTY}</span>
        ) : coef.sign_ok ? (
          <span className="text-brand-cyan">OK</span>
        ) : (
          <span className="text-amber-200/90">≠</span>
        )}
      </td>
    </tr>
  )
}
