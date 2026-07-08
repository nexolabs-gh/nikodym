import { type ReactNode, useId } from "react"
import { ArrowRight, ChartColumn, CircleAlert, Play } from "lucide-react"

import { CoefficientForestChart } from "@/components/charts/CoefficientForestChart"
import { DiscriminationChart } from "@/components/charts/DiscriminationChart"
import { GainsChart } from "@/components/charts/GainsChart"
import { IvChart } from "@/components/charts/IvChart"
import { LiftChart } from "@/components/charts/LiftChart"
import { PsiByComparisonChart } from "@/components/charts/PsiByComparisonChart"
import { ScoreHistogramChart } from "@/components/charts/ScoreHistogramChart"
import { StabilityBandLegend } from "@/components/charts/StabilityBandLegend"
import { StabilityCsiChart } from "@/components/charts/StabilityCsiChart"
import { bandColor, bandLabel } from "@/components/charts/chart-theme"
import { EmptyState } from "@/components/EmptyState"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import {
  EMPTY,
  bandsPresent,
  csiBars,
  discriminantRows,
  formatBool,
  formatCount,
  formatMetric,
  formatPValue,
  formatPercent,
  gainsSeries,
  liftByDecile,
  partitionLabel,
  primaryPartition,
  psiBars,
  scoreHistogram,
  sortByIv,
  temporalScore,
} from "@/lib/results-format"
import type { Coefficient } from "@/lib/results-types"
import { useAppState } from "@/state/appStore"

interface ResultsTabProps {
  /** Navega a otra sección del shell (misma convención que RunTab: la navegación vive en App). */
  onNavigate: (section: string) => void
}

/**
 * Pestaña Resultados (SDD-23 §1/§7.5): FORMATEA/GRAFICA los artefactos que la corrida
 * ya dejó en el store (`results`), con CERO lógica de dominio (cada número/barra viene
 * del artefacto). Visores premium (Recharts): discriminación, gains/lift por decil,
 * estabilidad (PSI/CSI), forest de coeficientes, IV por variable e histograma del score;
 * los valores exactos quedan a mano en tablas/detalle. Las curvas WoE por variable y la
 * confiabilidad de calibración son un batch posterior; aquí no se adelantan. Robusta a
 * corridas `failed`/parciales: muestra el `error` y solo las secciones presentes.
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

  // Deciles → gains/lift (2º batch de visores). Guard por presencia: si la corrida no dejó
  // la tabla de deciles, las secciones no se renderizan.
  const deciles = results.performance?.deciles
  const gains = gainsSeries(deciles)
  const liftPartition = primaryPartition(deciles)
  const lift = liftPartition ? liftByDecile(deciles, liftPartition) : []

  // Histograma de la distribución del score (binning de PRESENTACIÓN, helper testeado).
  const scoreHist = scoreHistogram(sc?.score_values)

  // Estabilidad (PSI/CSI): la sección se muestra solo si la corrida la calculó.
  const stab = results.stability ?? null
  const stabMetrics = stab?.stability_metrics ?? null
  const scorePsi = psiBars(stabMetrics, "score_psi")
  const pdPsi = psiBars(stabMetrics, "pd_psi")
  const csi = csiBars(stabMetrics)
  const temporal = temporalScore(stabMetrics)
  const hasStability =
    stab !== null &&
    (scorePsi.length > 0 ||
      pdPsi.length > 0 ||
      csi.length > 0 ||
      temporal !== null)

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

      {/* a. Discriminación: chart de barras AUC/Gini/KS por partición; valores exactos en detalle. */}
      {rows.length > 0 ? (
        <ResultsSection
          title="Discriminación"
          description="Poder de ordenamiento por partición (máximos de la evaluación, escala 0–1)."
        >
          <DiscriminationChart rows={rows} />
          <details className="group mt-2">
            <summary className="inline-flex cursor-pointer list-none items-center gap-1 text-xs text-brand-placeholder transition-colors hover:text-brand-cyan">
              <span className="text-brand-gray transition-transform group-open:rotate-90">
                ›
              </span>
              Ver valores exactos
            </summary>
            <div className="mt-3 overflow-x-auto">
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
          </details>
        </ResultsSection>
      ) : null}

      {/* a.1 Discriminación acumulada (gains/lift): la curva de ganancias vs. el azar y el
          lift por decil. Guard por presencia: sin tabla de deciles, no se renderiza. */}
      {gains.data.length > 0 || lift.length > 0 ? (
        <ResultsSection
          title="Discriminación acumulada — Gains y Lift"
          description="Curva de ganancias: % de malos capturados (eje Y) al recorrer los deciles del más al menos riesgoso (eje X); la diagonal punteada es el modelo aleatorio. El lift por decil mide cuántas veces más concentra malos que la media (1× = azar)."
        >
          {gains.data.length > 0 ? (
            <Subchart title="Curva de ganancias (captura acumulada de malos)">
              <GainsChart series={gains} />
            </Subchart>
          ) : null}
          {lift.length > 0 && liftPartition ? (
            <Subchart title={`Lift por decil — ${partitionLabel(liftPartition)}`}>
              <LiftChart rows={lift} partition={liftPartition} />
            </Subchart>
          ) : null}
        </ResultsSection>
      ) : null}

      {/* a.2 Estabilidad del score (PSI/CSI): drift de score/PD y de las variables en OOT.
          Guard por presencia: si estabilidad no corrió, la sección no se renderiza. */}
      {hasStability && stab ? (
        <ResultsSection
          title="Estabilidad del score"
          description="Deriva del score y de la PD calibrada entre particiones (PSI), y desplazamiento de cada variable (CSI). Umbrales de referencia dibujados como líneas."
        >
          <StabilityBandLegend bands={bandsPresent(stabMetrics)} />

          {/* 1+2. PSI del score y de la PD calibrada, lado a lado (mismo formato). */}
          {scorePsi.length > 0 || pdPsi.length > 0 ? (
            <div className="grid gap-x-6 gap-y-4 lg:grid-cols-2">
              {scorePsi.length > 0 ? (
                <Subchart title="PSI del score">
                  <PsiByComparisonChart
                    rows={scorePsi}
                    stableThreshold={stab.stable_threshold}
                    reviewThreshold={stab.review_threshold}
                  />
                </Subchart>
              ) : null}
              {pdPsi.length > 0 ? (
                <Subchart title="PSI de la PD calibrada">
                  <PsiByComparisonChart
                    rows={pdPsi}
                    stableThreshold={stab.stable_threshold}
                    reviewThreshold={stab.review_threshold}
                  />
                </Subchart>
              ) : null}
            </div>
          ) : null}

          {/* 3. CSI por característica (destaca la peor). */}
          {csi.length > 0 ? (
            <Subchart title="CSI por característica">
              <StabilityCsiChart
                rows={csi}
                worst={stab.worst_csi_feature}
                stableThreshold={stab.stable_threshold}
                reviewThreshold={stab.review_threshold}
              />
            </Subchart>
          ) : null}

          {/* 4. (Opcional) escalar de estabilidad temporal del score. */}
          {temporal ? (
            <div className="flex flex-wrap items-center gap-2 border-t border-white/5 pt-3 text-xs">
              <span className="text-brand-placeholder">
                PSI temporal del score
              </span>
              <span className="font-mono tabular-nums text-brand-offwhite">
                {formatMetric(temporal.value)}
              </span>
              <span
                className="inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[0.7rem]"
                style={{
                  backgroundColor: `${bandColor(temporal.band)}1a`,
                  color: bandColor(temporal.band),
                }}
              >
                <span
                  className="size-1.5 rounded-full"
                  style={{ backgroundColor: bandColor(temporal.band) }}
                  aria-hidden="true"
                />
                {bandLabel(temporal.band)}
              </span>
            </div>
          ) : null}
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

      {/* c. Coeficientes: forest plot (β ± IC) arriba, tabla completa como detalle numérico. */}
      {coefs.length > 0 ? (
        <ResultsSection
          title="Coeficientes"
          description="Estimación de la regresión: β y su intervalo de confianza por variable (excluye el intercepto)."
        >
          <CoefficientForestChart coefficients={coefs} />
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

      {/* d. IV por variable: barras horizontales ordenadas desc (el chart cubre la tabla). */}
      {ivRows.length > 0 ? (
        <ResultsSection
          title="IV por variable"
          description="Information Value total de cada variable (mayor a menor)."
        >
          <IvChart rows={ivRows} />
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

      {/* f. Distribución del score: histograma de la muestra cruda (binning de presentación).
          Guard por presencia: si `score_values` falta o viene vacío, no se renderiza. */}
      {scoreHist ? (
        <ResultsSection
          title="Distribución del score"
          description={`Histograma de los ${formatCount(scoreHist.count)} puntajes de la muestra. Eje X = score, Y = frecuencia; se marcan la media y la mediana como referencia del centro.`}
        >
          <ScoreHistogramChart histogram={scoreHist} />
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

/** Encabezado + contenedor de un sub-chart dentro de una sección (título tenue sobre el chart). */
function Subchart({
  title,
  children,
}: {
  title: string
  children: ReactNode
}) {
  return (
    <div className="space-y-1.5">
      <p className="text-[0.68rem] uppercase tracking-wide text-brand-placeholder">
        {title}
      </p>
      {children}
    </div>
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
