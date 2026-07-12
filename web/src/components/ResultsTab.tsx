import { type ReactNode, useId, useState } from "react"
import { ChartColumn, CircleAlert, Play } from "lucide-react"

import { CalibrationReliabilityChart } from "@/components/charts/CalibrationReliabilityChart"
import { CoefficientForestChart } from "@/components/charts/CoefficientForestChart"
import { DiscriminationChart } from "@/components/charts/DiscriminationChart"
import { GainsChart } from "@/components/charts/GainsChart"
import { IvChart } from "@/components/charts/IvChart"
import { LiftChart } from "@/components/charts/LiftChart"
import { PsiByComparisonChart } from "@/components/charts/PsiByComparisonChart"
import { ScoreHistogramChart } from "@/components/charts/ScoreHistogramChart"
import { StabilityBandLegend } from "@/components/charts/StabilityBandLegend"
import { StabilityCsiChart } from "@/components/charts/StabilityCsiChart"
import { WoeByBinChart } from "@/components/charts/WoeByBinChart"
import {
  bandColor,
  bandLabel,
  partitionColor,
} from "@/components/charts/chart-theme"
import { EmptyState } from "@/components/EmptyState"
import { Card, CardContent } from "@/components/ui/card"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  EMPTY,
  bandsPresent,
  binnedVariables,
  csiBars,
  csiComparisonLabel,
  discriminantRows,
  formatBool,
  formatCount,
  formatMetric,
  formatPValue,
  formatPercent,
  gainsSeries,
  liftByDecile,
  monotonicityLabel,
  partitionLabel,
  primaryPartition,
  psiBars,
  reliabilityCurve,
  scoreHistogram,
  sortByIv,
  temporalScore,
  variableBinning,
} from "@/lib/results-format"
import type {
  ReliabilityPartitionView,
  ReliabilityView,
  VariableBinning,
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
 * los valores exactos quedan a mano en tablas/detalle. Incluye la curva WoE por bin con
 * detalle por variable; la confiabilidad de calibración es un batch posterior. Robusta a
 * corridas `failed`/parciales: muestra el `error` y solo las secciones presentes.
 */
export function ResultsTab({ onNavigate }: ResultsTabProps) {
  const { results, lastRun, validation } = useAppState()

  // Variable seleccionada en el visor de WoE por bin (estado local, no store global). Se
  // declara antes de cualquier return condicional (reglas de hooks); su default real (mayor
  // IV) se resuelve más abajo contra los datos, cuando ya existen.
  const [woeVariable, setWoeVariable] = useState<string | null>(null)

  // Partición seleccionada en la tabla de detalle de confiabilidad (estado local). Su default
  // real ('oot' si está) se resuelve más abajo contra los datos, cuando ya existen.
  const [reliabilityPartition, setReliabilityPartition] = useState<string | null>(
    null,
  )

  // Sin resultados: estado vacío sobrio con CTA que NAVEGA a Ejecutar (como RunTab a "resultados").
  if (results === null) {
    return (
      <Card className="shadow-card">
        <EmptyState
          icon={ChartColumn}
          title="Sin resultados todavía"
          description="Los artefactos de una corrida (discriminación, ajuste, coeficientes, IV y calibración) se muestran aquí en cuanto ejecutes el pipeline."
          tag="Resultados"
          action={{
            label: "Ejecutar el preset",
            onClick: () => onNavigate("ejecutar"),
            icon: Play,
          }}
        />
      </Card>
    )
  }

  const failed = results.status === "failed"
  const configHash = validation.kind === "valid" ? validation.hash : null
  const runId = results.run_id || lastRun?.runId || null

  // Solo derivación/selección de artefactos ya calculados (helpers puros).
  const rows = discriminantRows(results.performance)
  const ivRows = sortByIv(results.binning?.iv_by_variable)

  // WoE por bin (3er batch): variables con tabla, ordenadas por IV desc para el selector; la
  // seleccionada cae a la de mayor IV si el estado local aún no eligió una válida.
  const woeVars = binnedVariables(results.binning)
  const activeWoeVar =
    woeVariable && woeVars.some((v) => v.feature === woeVariable)
      ? woeVariable
      : (woeVars[0]?.feature ?? null)
  const woeDetail = activeWoeVar
    ? variableBinning(results.binning, activeWoeVar)
    : null
  const fit = results.model?.fit_statistics
  const coefs = results.model?.coefficients ?? []
  const finalFeatures = results.model?.final_features ?? []
  const sc = results.scorecard
  const cal = results.calibration

  // Confiabilidad de calibración (reliability diagram, último visor). Guard por presencia:
  // si el backend no emitió `reliability` o `by_partition` viene vacío, `reliabilityCurve`
  // devuelve null y la sección no se renderiza. La tabla de detalle default a 'oot' (el drift
  // out-of-time es el caso que más importa); cae a la primera partición si OOT no está.
  const reliability = reliabilityCurve(cal)
  const activeReliabilityPartition = reliability
    ? (reliabilityPartition &&
      reliability.partitions.some((p) => p.partition === reliabilityPartition)
        ? reliabilityPartition
        : (reliability.partitions.find((p) => p.partition === "oot")?.partition ??
          reliability.partitions[0]?.partition ??
          null))
    : null

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
  const csiCmp = csiComparisonLabel(stabMetrics)
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
            <p className="text-sm font-medium text-eyebrow">
              Artefactos de la corrida
            </p>
          )}

          <dl className="grid gap-1.5 font-mono text-xs text-muted-foreground">
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
            <summary className="inline-flex cursor-pointer list-none items-center gap-1 text-xs text-muted-foreground transition-colors hover:text-eyebrow">
              <span className="text-muted-foreground transition-transform group-open:rotate-90">
                ›
              </span>
              Ver valores exactos
            </summary>
            <div className="mt-3 overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border text-left text-[0.68rem] uppercase tracking-wide text-muted-foreground">
                    <th className="py-2 pr-3 font-medium">Partición</th>
                    <NumHead>AUC</NumHead>
                    <NumHead>Gini</NumHead>
                    <NumHead>KS</NumHead>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => (
                    <tr key={r.partition} className="border-b border-border">
                      <td className="py-2 pr-3 text-foreground">
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
            <Subchart
              title={`CSI por característica${csiCmp ? ` — ${csiCmp}` : ""}`}
            >
              <StabilityCsiChart
                rows={csi}
                worst={csi[0]?.feature ?? null}
                stableThreshold={stab.stable_threshold}
                reviewThreshold={stab.review_threshold}
              />
            </Subchart>
          ) : null}

          {/* 4. (Opcional) escalar de estabilidad temporal del score. */}
          {temporal ? (
            <div className="flex flex-wrap items-center gap-2 border-t border-border pt-3 text-xs">
              <span className="text-muted-foreground">
                PSI temporal del score
              </span>
              <span className="font-mono tabular-nums text-foreground">
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
              <p className="text-[0.68rem] uppercase tracking-wide text-muted-foreground">
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
                <tr className="border-b border-border text-left text-[0.68rem] uppercase tracking-wide text-muted-foreground">
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

      {/* d.1 Análisis por variable (WoE): detalle del binning de la variable elegida (curva
          WoE por bin + tasa de default + tabla). Contigua al IV (panorámica → detalle).
          Guard por presencia: sin tablas de binning, no se renderiza. */}
      {woeVars.length > 0 && activeWoeVar && woeDetail ? (
        <ResultsSection
          title="Análisis por variable (WoE)"
          description="Weight of Evidence por bin de la variable elegida y su tasa de default (línea, eje derecho). WoE>0 = bin protector (menor riesgo); WoE<0 = mayor riesgo."
        >
          <div className="flex flex-wrap items-center gap-x-4 gap-y-3">
            <div className="min-w-56">
              <Select
                value={activeWoeVar}
                onValueChange={(v) => setWoeVariable(v)}
              >
                <SelectTrigger className="w-full" aria-label="Variable a analizar">
                  <SelectValue placeholder="Elige variable…" />
                </SelectTrigger>
                <SelectContent>
                  {woeVars.map((v) => (
                    <SelectItem key={v.feature} value={v.feature}>
                      <span className="font-mono">{v.feature}</span>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <WoeHeaderChips detail={woeDetail} />
          </div>

          <WoeByBinChart rows={woeDetail.rows} />
          <WoeDetailTable detail={woeDetail} />
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

      {/* e.1 Confiabilidad de calibración (reliability diagram): predicho vs observado por
          decil de riesgo, con la diagonal ideal y la banda de Wilson. Contigua a la escala/
          calibración (parámetros → evidencia). Guard por presencia: sin `reliability` (o con
          `by_partition` vacío), no se renderiza. */}
      {reliability ? (
        <ResultsSection
          title="Confiabilidad de calibración"
          description="Cada punto compara la PD predicha (eje X) con la tasa de default observada (eje Y) por decil de riesgo. Sobre la diagonal = el modelo SUBESTIMA el riesgo; bajo la diagonal = lo SOBREESTIMA. La banda vertical es el intervalo de Wilson 95%."
        >
          <ReliabilityChips partitions={reliability.partitions} />
          <CalibrationReliabilityChart view={reliability} />
          <ReliabilityDetail
            view={reliability}
            active={activeReliabilityPartition}
            onSelect={setReliabilityPartition}
          />
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
            className="font-heading text-base font-medium text-foreground"
          >
            {title}
          </h2>
          {description ? (
            <p className="text-xs text-muted-foreground">{description}</p>
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
      <p className="text-[0.68rem] uppercase tracking-wide text-muted-foreground">
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
      <dt className="shrink-0 text-muted-foreground">{label}</dt>
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
      <dt className="text-[0.68rem] uppercase tracking-wide text-muted-foreground">
        {label}
      </dt>
      <dd
        className={
          mono
            ? "font-mono tabular-nums text-foreground"
            : "text-foreground"
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
    <td className="py-2 pl-3 text-right font-mono tabular-nums text-muted-foreground">
      {children}
    </td>
  )
}

/** Chips del header del visor WoE: IV total + monotonicidad + nº de bins. Solo presenta. */
function WoeHeaderChips({ detail }: { detail: VariableBinning }) {
  return (
    <div className="flex flex-wrap items-center gap-2 text-xs">
      <span className="inline-flex items-center gap-1.5 rounded-full border border-brand-accent-dark/30 bg-brand-accent/10 px-2.5 py-0.5">
        <span className="text-muted-foreground">IV</span>
        <span className="font-mono tabular-nums text-brand-accent-dark">
          {formatMetric(detail.ivTotal)}
        </span>
      </span>
      <span className="rounded-full border border-border bg-foreground/[0.03] px-2.5 py-0.5 text-muted-foreground">
        {monotonicityLabel(detail.monotonicity)}
      </span>
      <span className="rounded-full border border-border bg-foreground/[0.03] px-2.5 py-0.5 text-muted-foreground">
        {detail.rows.length} {detail.rows.length === 1 ? "bin" : "bins"}
      </span>
    </div>
  )
}

/**
 * Tabla de detalle del binning de una variable: una fila por bin real y la fila Totals
 * distinguida al pie (WoE del agregado no aplica → EMPTY). Formatos consistentes con el
 * resto de la pestaña. Solo presenta valores ya normalizados por `variableBinning`.
 */
function WoeDetailTable({ detail }: { detail: VariableBinning }) {
  const { rows, total } = detail
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border text-left text-[0.68rem] uppercase tracking-wide text-muted-foreground">
            <th className="py-2 pr-3 font-medium">Bin</th>
            <NumHead>Count</NumHead>
            <NumHead>Count (%)</NumHead>
            <NumHead>Event rate</NumHead>
            <NumHead>WoE</NumHead>
            <NumHead>IV</NumHead>
            <NumHead>JS</NumHead>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.binLabel} className="border-b border-border">
              <td className="py-2 pr-3 font-mono text-foreground">
                {r.binLabel}
              </td>
              <NumCell>{formatCount(r.count)}</NumCell>
              <NumCell>{formatPercent(r.countPct)}</NumCell>
              <NumCell>{formatPercent(r.eventRate)}</NumCell>
              <NumCell>{formatMetric(r.woe)}</NumCell>
              <NumCell>{formatMetric(r.iv)}</NumCell>
              <NumCell>{formatMetric(r.js)}</NumCell>
            </tr>
          ))}
        </tbody>
        {total ? (
          <tfoot>
            <tr className="border-t border-border text-foreground">
              <td className="py-2 pr-3 font-medium">Total</td>
              <NumCell>{formatCount(total.totalCount)}</NumCell>
              <NumCell>{formatPercent(total.countPct)}</NumCell>
              <NumCell>{formatPercent(total.baseEventRate)}</NumCell>
              <NumCell>{EMPTY}</NumCell>
              <NumCell>{formatMetric(total.ivTotal)}</NumCell>
              <NumCell>{formatMetric(total.js)}</NumCell>
            </tr>
          </tfoot>
        ) : null}
      </table>
    </div>
  )
}

/**
 * Chips de calibración por partición: un chip por partición con su punto de color, el Brier
 * (4 decimales, menor = mejor) y el ECE (%). Deja claro qué partición es cada chip. Solo
 * presenta escalares ya normalizados por `reliabilityCurve`.
 */
function ReliabilityChips({
  partitions,
}: {
  partitions: ReliabilityPartitionView[]
}) {
  return (
    <div className="flex flex-wrap items-center gap-2 text-xs">
      {partitions.map((p) => (
        <span
          key={p.partition}
          className="inline-flex items-center gap-2 rounded-full border border-border bg-foreground/[0.03] px-2.5 py-0.5"
        >
          <span
            className="size-2 shrink-0 rounded-full"
            style={{ backgroundColor: partitionColor(p.partition) }}
            aria-hidden="true"
          />
          <span className="text-foreground">{partitionLabel(p.partition)}</span>
          <span className="text-muted-foreground">·</span>
          <span className="text-muted-foreground">Brier</span>
          <span className="font-mono tabular-nums text-foreground">
            {formatMetric(p.brier, 4)}
          </span>
          <span className="text-muted-foreground">·</span>
          <span className="text-muted-foreground">ECE</span>
          <span className="font-mono tabular-nums text-foreground">
            {formatPercent(p.ece, 2)}
          </span>
        </span>
      ))}
    </div>
  )
}

/**
 * Detalle numérico de confiabilidad: selector de partición (default 'oot') + tabla por bin
 * (PD predicha, default observado y su IC de Wilson). Reusa el patrón del visor WoE. Solo
 * presenta valores ya normalizados; CERO cálculo.
 */
function ReliabilityDetail({
  view,
  active,
  onSelect,
}: {
  view: ReliabilityView
  active: string | null
  onSelect: (partition: string) => void
}) {
  const detail = active
    ? (view.partitions.find((p) => p.partition === active) ?? null)
    : null
  if (!active || !detail) return null

  return (
    <div className="space-y-3">
      <div className="min-w-56 max-w-xs">
        <Select
          value={active}
          onValueChange={(v) => {
            if (v) onSelect(v)
          }}
        >
          <SelectTrigger className="w-full" aria-label="Partición a detallar">
            <SelectValue placeholder="Elige partición…" />
          </SelectTrigger>
          <SelectContent>
            {view.partitions.map((p) => (
              <SelectItem key={p.partition} value={p.partition}>
                {partitionLabel(p.partition)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border text-left text-[0.68rem] uppercase tracking-wide text-muted-foreground">
              <th className="py-2 pr-3 font-medium">Bin</th>
              <NumHead>n</NumHead>
              <NumHead>PD predicha</NumHead>
              <NumHead>Default observado</NumHead>
              <NumHead>IC Wilson 95%</NumHead>
            </tr>
          </thead>
          <tbody>
            {detail.points.map((pt) => (
              <tr key={pt.bin} className="border-b border-border">
                <td className="py-2 pr-3 font-mono text-foreground">
                  {pt.bin}
                </td>
                <NumCell>{formatCount(pt.n)}</NumCell>
                <NumCell>{formatPercent(pt.pred, 2)}</NumCell>
                <NumCell>{formatPercent(pt.obs, 2)}</NumCell>
                <NumCell>
                  [{formatPercent(pt.ciLow, 2)}, {formatPercent(pt.ciHigh, 2)}]
                </NumCell>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

/** Fila de coeficiente: el signo esperado se marca solo si el backend lo evaluó (sign_ok). */
function CoefRow({ coef }: { coef: Coefficient }) {
  return (
    <tr className="border-b border-border">
      <td className="py-2 pr-3 font-mono text-foreground">
        {coef.feature}
      </td>
      <NumCell>{formatMetric(coef.beta)}</NumCell>
      <NumCell>{formatMetric(coef.standard_error)}</NumCell>
      <NumCell>{formatMetric(coef.wald_z)}</NumCell>
      <NumCell>{formatPValue(coef.p_value)}</NumCell>
      <td className="py-2 pl-3 text-right">
        {coef.sign_ok === null ? (
          <span className="text-muted-foreground">{EMPTY}</span>
        ) : coef.sign_ok ? (
          <span className="text-eyebrow">OK</span>
        ) : (
          <span className="text-amber-200/90">≠</span>
        )}
      </td>
    </tr>
  )
}
