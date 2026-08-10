import { useCallback, useRef, useState } from "react"
import {
  CircleAlert,
  CircleCheck,
  CloudOff,
  Download,
  FilePlus2,
  Loader2,
  Sparkles,
  TriangleAlert,
  Upload,
} from "lucide-react"

import { FieldRenderer } from "@/components/FieldRenderer"
import { PreflightNotice } from "@/components/PreflightNotice"
import { applyPreset } from "@/components/RunTab"
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion"
import { Button } from "@/components/ui/button"
import { Label } from "@/components/ui/label"
import { Switch } from "@/components/ui/switch"
import { TooltipProvider } from "@/components/ui/tooltip"
import {
  ApiError,
  type ConfigFromYamlResponse,
  configFromYaml,
  configToYaml,
  getPreset,
} from "@/lib/api"
import type { SeedState } from "@/lib/bootstrap"
import {
  type AnswerForm,
  type DecisionStatus,
  type Job,
  type JobSwitch,
  type MethodologyStatus,
  decisionStatuses,
  jobSwitchForConfig,
  jobSwitchNotice,
  loadJobs,
  methodologyStatuses,
} from "@/lib/jobs"
import {
  type PrecargasDeForma,
  plantillaConPrecargas,
  precargasDeForma,
  requiredExternalArtifacts,
} from "@/lib/external-artifacts"
import { type Path, getAtPath, removeAtPath, setAtPath } from "@/lib/config-store"
import { columnValuesByName, columnasDeIndice, columnasOfrecibles } from "@/lib/datasets"
import {
  type EffectiveDefaults,
  canonicalProjection,
  childMap,
  nodeAtPath,
  usableCatalog,
} from "@/lib/effective-defaults"
import { DEMO_MODE } from "@/lib/demo-runtime"
import {
  type Defs,
  type JsonSchema,
  defaultForSchema,
  groupedFields,
  grupoTitulaASuUnicoCampo,
  resolveRef,
} from "@/lib/form-engine"
import { type SchemaSource, configSectionSchema } from "@/lib/schema"
import {
  type ValidationState,
  describeApiError,
  erroresSinSuperficie,
  pipelineWarning,
} from "@/lib/validation"
import { useAppState, type AppState } from "@/state/appStore"

const SOURCE_BANNER: Record<
  SchemaSource,
  { tone: "ok" | "warn"; text: string }
> = {
  backend: {
    tone: "ok",
    // En la demo pública NO hay backend: `loadSchema` marca la fuente como "backend" para que el
    // editor no se vea degradado (schema.ts §DEMO_MODE), así que el texto de esa rama se leería
    // como una afirmación falsa —«en vivo desde /api/schema»— en una página estática. Se dice la
    // verdad sin rebajar el tono: el schema es el mismo que publicó el backend, capturado.
    text: DEMO_MODE
      ? "Schema capturado del backend en una corrida real; esta demo no ejecuta cálculo en el navegador."
      : "Schema en vivo desde el backend (/api/schema).",
  },
  "fixture-opaque": {
    tone: "warn",
    text: "El backend devolvió una sección sin expandir; usando el snapshot local como respaldo.",
  },
  "fixture-offline": {
    tone: "warn",
    text: "Backend no disponible; usando el snapshot local del schema (fixtures/schema.json).",
  },
}

/**
 * Aviso sobrio de qué config se cargó (o `null` mientras aún no se resuelve el arranque).
 *
 * `empty` y `defaults` cargan el mismo config y dicen cosas distintas a propósito (D-JOB-2): uno es
 * el estado inicial de la sesión y el otro una acción que el usuario ejecutó desde esta pantalla.
 * Darles el mismo texto explicaría la primera pantalla con el copy de un botón que nadie pulsó.
 */
function seedNotice(seed: SeedState | null): string | null {
  switch (seed?.kind) {
    case "empty":
      return "Sesión nueva, sin configuración. Trae tus datos en «Cargar datos» y ajusta aquí lo que necesites; «Ver un ejemplo» carga uno con datos de muestra."
    case "job":
      // Nombra el trabajo y dice qué falta. Sin esto el aviso seguía diciendo «sesión nueva, sin
      // configuración» sobre un formulario que YA trae las secciones sembradas: el copy más
      // desorientador posible, porque contradice lo que el usuario está viendo.
      return `Trabajo: ${seed.label}. El formulario muestra sólo sus secciones, con los valores del motor; falta lo que sólo puedes decidir tú sobre tus datos.`
    case "preset":
      return `Cargado el ejemplo: ${seed.name} · dataset de muestra ${seed.datasetId}`
    case "fallback":
      return "Config vacío del schema (backend no disponible)."
    case "defaults":
      return "Config vacío del schema (empezar de cero)."
    default:
      return null
  }
}

/**
 * Dependencias de la carga de un YAML propio, inyectadas para poder ejercitar el flujo sin montar
 * React (mismo patrón que `applyPreset` y `bootstrapWorkspace`): las dos puertas al backend y los
 * setters del store que se escriben.
 */
export interface YamlIntakeDeps {
  fromYaml: (text: string) => Promise<ConfigFromYamlResponse>
  loadJobs: () => Promise<Job[]>
  setConfig: AppState["setConfig"]
  setJob: AppState["setJob"]
  setSeed: AppState["setSeed"]
}

/**
 * Carga el YAML del usuario y **deja la sesión en el trabajo que ese archivo trae** (D-JOB-17).
 *
 * Ésta es la conexión que faltaba: `jobForConfig` estaba escrita, documentada y probada desde que se
 * aprobó el SDD, y no la llamaba nadie —o sea que la decisión existía en el repo y no en el
 * producto—. Sin ella, cargar un YAML de IFRS 9 estando en «Scorecard» dejaba el sidebar del
 * scorecard sobre un config de IFRS 9: las secciones que el propio usuario acababa de traer no
 * tenían pestaña, y las que veía estaban apagadas en su archivo. Es exactamente el estado que
 * D-JOB-17 decidió cerrar **con esta regla y no con un aviso de sección ajena**.
 *
 * Tres decisiones que van con esto:
 *
 * 1. **Manda el config del usuario, no el trabajo que había elegido.** El archivo es suyo y es la
 *    señal más explícita que puede dar. Conservar el trabajo anterior sería preferir nuestra
 *    navegación a sus datos.
 * 2. **No se cambia en silencio: se cambia y se dice.** El cambio reescribe el sidebar entero, y una
 *    navegación que se transforma sola sin explicación es la clase de sorpresa que este repo evita.
 *    No se pide confirmación, en cambio, porque no hay decisión que ofrecer: decir «no» dejaría al
 *    usuario justo en el estado roto de arriba, y el gesto destructivo —reemplazar el config— es el
 *    que él ya pidió al elegir el archivo.
 * 3. **Si el archivo no calza con ningún trabajo, la sesión queda SIN trabajo** y el formulario
 *    muestra el config completo, tal como manda el criterio ya escrito en `jobForConfig`: esconderle
 *    parte de lo que él mismo trajo sería la mentira contraria.
 *
 * Un fallo del backend se propaga **sin escribir nada** (igual que `applyPreset`): el config vigente
 * y su trabajo siguen siendo coherentes entre sí. `loadJobs` nunca lanza —cae al fixture bundleado—,
 * así que el trabajo se resuelve incluso con el catálogo caído.
 */
export async function applyYamlConfig(
  text: string,
  fileName: string,
  jobActivo: Job | null,
  deps: YamlIntakeDeps,
): Promise<JobSwitch> {
  const result = await deps.fromYaml(text)
  const jobs = await deps.loadJobs()
  // El backend devuelve la proyección de lo que el ARCHIVO traía (`exclude_unset`, D-FX-8), no su
  // expansión completa: por eso «las secciones activas» son las que el usuario escribió y no las 14.
  const cambio = jobSwitchForConfig(jobs, result.config, jobActivo)
  deps.setConfig(result.config) // el backend es la fuente: puebla el form con el config migrado
  // Sólo si cambia: el catálogo se vuelve a pedir en cada carga, así que reescribirlo siempre
  // metería en el store un objeto nuevo equivalente al que ya había y forzaría un render de más.
  if (cambio.cambia) deps.setJob(cambio.job)
  // El config ya no es el del preset sembrado, y el `seed` es quien lo sabe: sin esta línea el
  // selector de Ejecutar seguía anunciando `f1-estandar-consumo` sobre el YAML del usuario, y
  // tocarlo resembraba el preset encima de su trabajo.
  deps.setSeed({ kind: "yaml", fileName })
  return cambio
}

/**
 * Lo que sólo el usuario puede decidir sobre SUS datos (D-OBL-6/8).
 *
 * Va al principio de Configuración y **antes** de los parámetros de detalle, porque son las
 * decisiones que definen el trabajo: qué es un cliente malo en esta cartera, cómo se separa la
 * muestra. El motor no las puede rellenar —son criterio de la institución— y hasta hace poco el
 * usuario sólo se enteraba de que faltaban cuando la corrida moría.
 *
 * No bloquea ni es un asistente: se puede responder aquí o en la sección, que es donde ya viven los
 * controles. Por eso cada tarjeta lleva un botón que enfoca el campo exacto, reusando el mismo
 * mecanismo del preflight (`setFocusField` + `data-field-path`).
 */
function RequiredDecisions({
  decisions,
  section,
  onFocus,
  onAnswerForm,
  precargas,
}: {
  decisions: DecisionStatus[]
  section: string
  onFocus: (path: string) => void
  onAnswerForm: (path: string, template: unknown) => void
  /** Lo que cada forma puede proponer con el estado actual (D-COL-8); no escribe nada. */
  precargas: (forma: AnswerForm) => PrecargasDeForma
}) {
  // Se pintan las de ESTA sección, igual que `PreflightNotice` y por la misma razón: el botón
  // enfoca un control del DOM, y el de otra sección no está montado. Ocho de los diez trabajos
  // tienen todas sus decisiones en `data`, que además es la primera sección del sidebar, así que en
  // la práctica se ven al entrar — que es lo que D-OBL-8 pide.
  const aqui = decisions.filter((d) => d.path.split(".")[0] === section)
  const fuera = decisions.filter(
    (d) => d.path.split(".")[0] !== section && !d.answered,
  ).length
  if (aqui.length === 0) return null
  const pendientes = aqui.filter((d) => !d.answered).length
  return (
    <section
      aria-labelledby="decisiones-obligatorias"
      className="rounded-lg border border-brand-cyan/25 bg-brand-cyan/[0.04] px-4 py-3"
    >
      <h3
        id="decisiones-obligatorias"
        className="text-xs font-medium uppercase tracking-wide text-eyebrow"
      >
        {pendientes > 0 ? "Esto lo decides tú" : "Tus decisiones"}
      </h3>
      <p className="mt-1 text-xs text-muted-foreground">
        {pendientes > 0
          ? "Depende de tu cartera y de tu política, así que no traemos un valor por defecto."
          : "Ya están todas respondidas; puedes cambiarlas cuando quieras."}
      </p>
      <ul className="mt-3 space-y-2.5">
        {aqui.map((decision) => (
          <li key={decision.path} className="flex items-start gap-2.5">
            {decision.answered ? (
              <CircleCheck
                className="mt-0.5 size-3.5 shrink-0 text-brand-cyan"
                aria-label="Respondida"
              />
            ) : (
              <CircleAlert
                className="mt-0.5 size-3.5 shrink-0 text-amber-300/80"
                aria-label={
                  decision.inProgress
                    ? "Te falta un dato"
                    : decision.rejected
                      ? "Revisa lo que escribiste"
                      : "Sin responder"
                }
              />
            )}
            <div className="min-w-0 flex-1">
              <p className="text-sm text-foreground">{decision.question}</p>
              <p className="mt-0.5 text-xs text-muted-foreground">{decision.help}</p>
              {/* Las formas se ofrecen mientras la decisión esté SIN EMPEZAR. Una vez elegida, el
                  usuario está rellenando sus huecos en los controles de abajo y volver a pintar
                  las alternativas invitaría a pisar lo escrito de un clic. */}
              {!decision.answered &&
              !decision.inProgress &&
              !decision.rejected &&
              decision.answer_forms.length > 0 ? (
                <ul className="mt-2 space-y-1.5">
                  {decision.answer_forms.map((forma) => {
                    const propuesto = precargas(forma)
                    return (
                      <li key={forma.id}>
                        <button
                          type="button"
                          className="w-full rounded-md border border-border/70 bg-background/40 px-2.5 py-1.5 text-left transition-colors hover:border-brand-cyan/50 hover:bg-brand-cyan/[0.06]"
                          onClick={() =>
                            onAnswerForm(
                              decision.path,
                              plantillaConPrecargas(forma.template, propuesto.propuestas),
                            )
                          }
                        >
                          <span className="block text-xs font-medium text-foreground">
                            {forma.label}
                          </span>
                          <span className="mt-0.5 block text-[11px] leading-snug text-muted-foreground">
                            {forma.help}
                          </span>
                          {/* La procedencia va DENTRO del botón y con el nombre a la vista: lo que
                              se propone tiene que verse antes del clic, no descubrirse después en
                              un campo que uno no recuerda haber llenado (D-COL-8). */}
                          {propuesto.propuestas.map((p) => (
                            <span
                              key={p.slot}
                              className="mt-1 block text-[11px] leading-snug text-brand-cyan/90"
                            >
                              Te proponemos «{p.valor}»: {p.nota}.
                            </span>
                          ))}
                          {propuesto.motivo !== null ? (
                            <span className="mt-1 block text-[11px] leading-snug text-amber-300/80">
                              {propuesto.motivo}
                            </span>
                          ) : null}
                        </button>
                      </li>
                    )
                  })}
                </ul>
              ) : null}
              {decision.inProgress ? (
                <p className="mt-1 text-xs text-amber-300/80">
                  Elegiste cómo contestarla; abajo te faltan los datos de tu cartera.
                </p>
              ) : null}
              {/* Rechazada: no falta ningún dato, así que mandar «abajo» sería falso. Y el motivo
                  puede no estar marcado en ningún campo —el `loc` del motor lleva el tag del
                  discriminador, que ningún control tiene—, de modo que éste es el único sitio donde
                  el usuario puede leerlo. Se cita tal cual lo dijo el motor: reescribirlo aquí sería
                  una segunda versión del mismo mensaje, que es como se desincronizan. */}
              {decision.rejected
                ? decision.rejectionReasons.map((motivo) => (
                    <p key={motivo} className="mt-1 text-xs text-amber-300/80">
                      Está contestada, pero el motor no acepta lo que dice: {motivo}
                    </p>
                  ))
                : null}
            </div>
            <Button
              variant="ghost"
              size="sm"
              className="shrink-0 text-xs"
              onClick={() => onFocus(decision.path)}
            >
              {decision.answered ? "Revisar" : decision.rejected ? "Corregir" : "Ir al campo"}
            </Button>
          </li>
        ))}
      </ul>
      {/* Sin esto, quien está en la primera sección no sabe que le falta algo más adelante y sólo
          se entera cuando el botón Ejecutar sigue en rojo. No se nombra la sección para no repetir
          aquí el rótulo del sidebar, que es donde se navega. */}
      {fuera > 0 ? (
        <p className="mt-3 border-t border-border/60 pt-2 text-xs text-muted-foreground">
          {fuera === 1
            ? "Queda otra decisión en una sección siguiente."
            : `Quedan otras ${fuera} decisiones en las secciones siguientes.`}
        </p>
      ) : null}
    </section>
  )
}

/**
 * El abanico metodológico: qué se puede elegir aquí, y qué cuesta cada opción (D-ABA-10).
 *
 * Va en el MISMO paso que las decisiones obligatorias y **después** de ellas: aquéllas impiden
 * correr y ésta no, así que ponerla delante colocaría lo opcional por delante de lo que bloquea.
 * D-JOB-4 pide que el método se elija al principio, antes de los parámetros de detalle; esto es ese
 * principio.
 *
 * 🔴 **Una opción que no se puede usar se muestra, no se oculta** (D-JOB-5). Esconderla deja al
 * usuario creyendo que la librería no la contempla, que es la mentira contraria — y en un producto
 * cuyo argumento es tener abanico serio, la peor forma posible de contarlo. Va en gris, con su
 * motivo, y no se puede pulsar.
 *
 * El `path` no se enseña nunca (D-ABA-11): lo que el usuario lee es la pregunta, la etiqueta de la
 * opción y su ayuda.
 */
function MethodologyChoices({
  choices,
  section,
  onChoose,
  onFocus,
}: {
  choices: MethodologyStatus[]
  section: string
  onChoose: (path: string, value: string) => void
  onFocus: (path: string) => void
}) {
  // Los de ESTA sección, por la misma razón que `RequiredDecisions`: el botón enfoca un control del
  // DOM, y el de otra sección no está montado.
  const aqui = choices.filter((c) => c.path.split(".")[0] === section)
  if (aqui.length === 0) return null
  return (
    <section
      aria-labelledby="abanico-metodologico"
      className="rounded-lg border border-border/70 bg-background/30 px-4 py-3"
    >
      <h3
        id="abanico-metodologico"
        className="text-xs font-medium uppercase tracking-wide text-eyebrow"
      >
        Cómo quieres hacerlo
      </h3>
      <p className="mt-1 text-xs text-muted-foreground">
        Todas traen una opción puesta y la corrida funciona sin tocar nada. Cámbialas si tu
        metodología pide otra cosa: aquí dice qué necesita cada una.
      </p>
      <ul className="mt-3 space-y-3">
        {aqui.map((choice) => (
          <li key={choice.path}>
            <p className="text-sm text-foreground">{choice.question}</p>
            <p className="mt-0.5 text-xs text-muted-foreground">{choice.help}</p>
            <ul className="mt-1.5 space-y-1">
              {choice.options.map((opcion) => {
                const elegida = opcion.value === choice.elegida
                const bloqueada = opcion.estado === "no_implementada"
                return (
                  <li key={opcion.value}>
                    <button
                      type="button"
                      disabled={bloqueada}
                      aria-pressed={elegida}
                      data-methodology-path={choice.path}
                      data-methodology-value={opcion.value}
                      className={
                        bloqueada
                          ? "w-full cursor-not-allowed rounded-md border border-border/40 bg-background/20 px-2.5 py-1.5 text-left opacity-60"
                          : elegida
                            ? "w-full rounded-md border border-brand-cyan/50 bg-brand-cyan/[0.08] px-2.5 py-1.5 text-left"
                            : "w-full rounded-md border border-border/70 bg-background/40 px-2.5 py-1.5 text-left transition-colors hover:border-brand-cyan/50 hover:bg-brand-cyan/[0.06]"
                      }
                      onClick={() => {
                        if (bloqueada) return
                        onChoose(choice.path, opcion.value)
                      }}
                    >
                      <span className="flex items-center gap-1.5">
                        {elegida ? (
                          <CircleCheck
                            className="size-3.5 shrink-0 text-brand-cyan"
                            aria-label="Elegida"
                          />
                        ) : null}
                        <span className="text-xs font-medium text-foreground">{opcion.label}</span>
                      </span>
                      <span className="mt-0.5 block text-[11px] leading-snug text-muted-foreground">
                        {opcion.help}
                      </span>
                      {/* El motivo va DENTRO del botón: si el usuario tiene que descubrir por qué
                          no puede usarla pasando el ratón, para él la opción sigue sin explicación
                          (D-JOB-5). Vale igual para la que se puede elegir y no cambia nada. */}
                      {opcion.motivo !== null ? (
                        <span className="mt-1 block text-[11px] leading-snug text-amber-300/80">
                          {opcion.motivo}
                        </span>
                      ) : null}
                    </button>
                  </li>
                )
              })}
            </ul>
            <Button
              variant="ghost"
              size="sm"
              className="mt-1 text-xs"
              onClick={() => onFocus(choice.path)}
            >
              Ir al campo
            </Button>
            {/* 🔴 El salto al campo que la opción ELEGIDA exige (D-EXI-2). Sin esto el usuario lee
                «hay que decirle con qué variables modelar la severidad» y no tiene dónde ponerlas:
                el error de dominio llega con `loc: []`, así que el preflight no puede enfocarlo y el
                gesto simétrico —elegir una partición temporal— sí marca su campo. Es la diferencia
                entre declarar el hueco y hacerlo accionable. */}
            {choice.options
              .filter((opcion) => opcion.value === choice.elegida && opcion.exige.length > 0)
              .flatMap((opcion) => opcion.exige)
              .map((ruta) => (
                <Button
                  key={ruta}
                  variant="ghost"
                  size="sm"
                  className="mt-1 ml-1 text-xs text-amber-300/90"
                  data-methodology-requires={ruta}
                  onClick={() => onFocus(ruta)}
                >
                  Ir a lo que falta
                </Button>
              ))}
          </li>
        ))}
      </ul>
    </section>
  )
}

/** Descarga `text` como archivo `filename` vía Blob + anchor (efecto DOM, no puro). */
function triggerDownload(text: string, filename: string) {
  const blob = new Blob([text], { type: "application/x-yaml" })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement("a")
  anchor.href = url
  anchor.download = filename
  document.body.append(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
}

/** Mensaje legible de un fallo de acción YAML: detalle del backend (422) o el error crudo. */
function yamlErrorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    return describeApiError(err.body, err.message)
  }
  return err instanceof Error ? err.message : String(err)
}

/**
 * Indicador sobrio del estado de validación en vivo (config_hash / errores / backend).
 *
 * Con `invalid` publica, bajo el contador, **todo error que esta vista no ancle a ningún campo**
 * (D-VIS-1/3): su mensaje tal cual, la sección donde vive y —si esa sección tiene pestaña— un botón
 * que lleva ahí. Es el único sitio que ve el estado entero, así que es donde la invariante «un error
 * siempre tiene superficie» se puede sostener.
 */
function HashStatus({
  state,
  seccionActiva,
  onJumpToField,
}: {
  state: ValidationState
  seccionActiva: string | null
  onJumpToField?: (path: string) => void
}) {
  switch (state.kind) {
    case "valid":
      return (
        <span
          className="inline-flex items-center gap-1.5 font-mono text-xs text-eyebrow"
          title={`config_hash: ${state.hash}`}
        >
          <CircleCheck className="size-3.5" aria-hidden="true" />
          <span className="text-muted-foreground">config_hash</span>
          {state.hash.slice(0, 12)}…
        </span>
      )
    case "invalid": {
      // D-VIS-1/3, que generaliza D-ANC-12: un error sólo se pinta junto a su campo si ese campo
      // está montado, así que basta estar en otra sección para que el mensaje desaparezca de la
      // pantalla entera y quede el contador solo. Aquí se publica todo lo que esta vista no ancla.
      const sinSuperficie = erroresSinSuperficie(state, seccionActiva)
      return (
        <span className="inline-flex flex-col gap-1 text-xs text-destructive">
          <span className="inline-flex items-center gap-1.5">
            <CircleAlert className="size-3.5" aria-hidden="true" />
            Config inválido · {state.count}{" "}
            {state.count === 1 ? "error" : "errores"}
          </span>
          {sinSuperficie.map((error) => (
            <span key={error.path} className="inline-flex flex-wrap items-baseline gap-x-1.5">
              <span className="opacity-90">{error.msg}</span>
              {error.seccionLabel !== null ? (
                error.alcanzable && onJumpToField ? (
                  <button
                    type="button"
                    onClick={() => onJumpToField(error.path)}
                    className="underline underline-offset-2 opacity-80 hover:opacity-100"
                  >
                    Ir a {error.seccionLabel}
                  </button>
                ) : (
                  <span className="opacity-70">En {error.seccionLabel}.</span>
                )
              ) : error.seccion !== null ? (
                // Sección de dominio sin pestaña (8 de 22: `forward`, `markov`, `stress`…). Se dice
                // dónde vive en vez de fingir un salto a una pestaña que no existe, que es el
                // criterio que `preflight.ts:84-91` ya declara para sus desajustes.
                <span className="opacity-70">
                  En la sección «{error.seccion}», que se edita por YAML o por código.
                </span>
              ) : null}
            </span>
          ))}
        </span>
      )
    }
    case "checking":
      return (
        <span className="inline-flex items-center gap-1.5 text-xs text-muted-foreground">
          <Loader2 className="size-3.5 animate-spin" aria-hidden="true" />
          Validando…
        </span>
      )
    case "unreachable":
      return (
        <span className="inline-flex items-center gap-1.5 text-xs text-amber-200/80">
          <CloudOff className="size-3.5" aria-hidden="true" />
          Backend no disponible — sin validación en vivo
        </span>
      )
    default:
      return null
  }
}

/**
 * Interruptor de una sección de configuración completa (activar / desactivar).
 *
 * Apagarla la pone en `null`, que es lo que el motor entiende por «esta sección no corre». Existía
 * por código desde siempre; en la UI no, porque el schema compuesto perdía la nulabilidad de la
 * sección al empotrar el sub-config y el motor de formulario no tenía cómo saber que era opcional.
 */
function SectionToggle(props: {
  sectionKey: string
  active: boolean
  onToggle: (next: boolean) => void
}) {
  const { sectionKey, active, onToggle } = props
  return (
    <div className="flex items-center gap-3 rounded-xl border border-border bg-card px-5 py-3 shadow-card">
      <Switch
        id={`section-toggle-${sectionKey}`}
        checked={active}
        onCheckedChange={onToggle}
        aria-label={active ? "Desactivar la sección" : "Activar la sección"}
      />
      <Label
        htmlFor={`section-toggle-${sectionKey}`}
        className="cursor-pointer text-sm text-foreground/90"
      >
        {active ? "Sección activa" : "Sección desactivada"}
      </Label>
      <span className="text-xs text-muted-foreground">
        {active
          ? "Se incluye en el config y se ejecuta."
          : "El motor no la corre."}
      </span>
    </div>
  )
}

/**
 * Formulario de UNA sección (`section`), agrupando sus campos por `ui_group` (contrato SDD-05
 * §5.5): si la sección declara grupos, los pinta como sub-accordions (abiertos por defecto) con el
 * título del grupo; si no (caso `data`, sub-modelos sin `ui_group`), los pinta planos en una
 * tarjeta. Los `path` de cada campo (`[section, name]`) no cambian, así que la validación en vivo,
 * el `config_hash` y el round-trip YAML siguen operando igual (B30).
 */
function ConfigSectionForm(props: {
  sectionKey: string
  schema: JsonSchema
  defs: Defs
  config: Record<string, unknown>
  setField: (path: Path, value: unknown) => void
  errors?: Map<string, string>
  datasetColumns?: string[]
  /** Los nombres del ÍNDICE del archivo (D-PRO-5); nunca se mezclan con `datasetColumns`. */
  datasetIndexColumns?: string[]
  producedColumns?: string[]
  datasetColumnValues?: Record<string, string[]>
  effectiveDefaults?: EffectiveDefaults
  disabledEnumValues?: Record<string, string[]>
}) {
  const {
    sectionKey,
    schema,
    defs,
    config,
    setField,
    errors,
    datasetColumns,
    datasetIndexColumns,
    producedColumns,
    datasetColumnValues,
    effectiveDefaults,
    disabledEnumValues,
  } = props
  // El mapa de defaults de ESTA sección. Baja con el formulario campo a campo; los dos sitios que
  // `sections` no alcanza —filas de lista y variantes— lo resuelven por `$defs` (FieldRenderer).
  const sectionDefaults = childMap(nodeAtPath(effectiveDefaults, [sectionKey]))
  const groups = groupedFields(schema)
  const required = new Set(schema.required ?? [])
  const renderField = (
    [name, fieldSchema]: [string, JsonSchema],
    titledByParent = false,
  ) => (
    <FieldRenderer
      key={name}
      name={name}
      schema={fieldSchema}
      path={[sectionKey, name]}
      value={getAtPath(config, [sectionKey, name])}
      defs={defs}
      onChange={setField}
      required={required.has(name)}
      errors={errors}
      datasetColumns={datasetColumns}
      datasetIndexColumns={datasetIndexColumns}
      producedColumns={producedColumns}
      datasetColumnValues={datasetColumnValues}
      titledByParent={titledByParent}
      defaultsBase={sectionDefaults}
      effectiveDefaults={effectiveDefaults}
      disabledEnumValues={disabledEnumValues}
    />
  )

  // Sección sin grupos declarados (p.ej. `data`: sub-modelos sin ui_group) → lista plana.
  if (groups.length <= 1) {
    const fields = groups[0]?.fields ?? []
    return (
      <div className="space-y-5 rounded-xl border border-border bg-card p-5 shadow-card">
        {fields.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            Esta sección no tiene campos configurables.
          </p>
        ) : (
          // `(f) => renderField(f)` y no `renderField` a secas: `map` pasaría el índice como
          // segundo argumento y acabaría en `titledByParent`.
          fields.map((field) => renderField(field))
        )}
      </div>
    )
  }

  // Varios grupos → un accordion por grupo, todos abiertos por defecto. La `value` es el índice
  // (no el título) para no depender de que los títulos sean únicos.
  return (
    <Accordion
      defaultValue={groups.map((_, index) => String(index))}
      className="rounded-xl border border-border bg-card px-4 shadow-card"
    >
      {groups.map((grp, index) => (
        <AccordionItem key={index} value={String(index)}>
          <AccordionTrigger className="font-display text-base">
            {grp.group ?? "General"}
          </AccordionTrigger>
          <AccordionContent>
            {/* Si el accordion ya se llama igual que su único campo, ese campo va sin su propio
                título: si no, se lee «Documento / Documento». */}
            <div className="space-y-5 pt-1 pb-2">
              {grp.fields.map((field) =>
                renderField(field, grupoTitulaASuUnicoCampo(grp)),
              )}
            </div>
          </AccordionContent>
        </AccordionItem>
      ))}
    </Accordion>
  )
}

/**
 * Pestaña Config: auto-genera el formulario desde el schema que cargó el ARRANQUE de la sesión
 * (`lib/bootstrap.ts` → provider). Desde B30 muestra SOLO la sección F1 elegida en el sidebar
 * (`section`) — no las 7 apiladas — con sus campos agrupados por `ui_group` (ver
 * `ConfigSectionForm`).
 *
 * Es un EDITOR PURO (UX1): renderiza y edita, pero NO siembra el config ni arranca su vida. La
 * siembra del preset y la validación en vivo (debounce → `POST /api/validate`) viven en el
 * provider (`state/appStore.tsx`), por dos razones: (1) sin abrir esta pestaña el config también
 * está sembrado y validado, así que Ejecutar no depende de pasar por aquí; (2) esta pestaña se
 * DESMONTA al navegar a Datos/Ejecutar, y un efecto de montaje volvía a sembrar el preset,
 * pisando las ediciones del usuario y el dataset que hubiera elegido.
 *
 * La barra superior (recargar el preset, `config_hash` en vivo, round-trip YAML) es global al
 * config y persiste al navegar entre secciones. Recargar el preset o "empezar de cero" siguen
 * aquí: son acciones EXPLÍCITAS del usuario, no siembra automática. El round-trip YAML (§3.4)
 * va **vía el backend** (no se parsea YAML en el front).
 */
export function ConfigTab({
  section,
  onJumpToField,
}: {
  section: string
  /** Salto a un campo de OTRA sección (D-VIS-3). Lo dueña `App`, que es quien navega. */
  onJumpToField?: (path: string) => void
}) {
  // El schema, el config, su validación, la siembra y el dataset elegido viven en el store
  // compartido (useAppState); solo las acciones YAML y sus estados son locales a esta pestaña.
  const {
    schema,
    config,
    setConfig,
    job,
    setJob,
    seed,
    setSeed,
    setDatasetId,
    setSelectedDataset,
    setResults,
    setLastRun,
    validation,
    preflight,
    setFocusField,
    selectedDataset,
    datasetId,
    externalInputs,
  } = useAppState()
  const [yamlError, setYamlError] = useState<string | null>(null)
  const [yamlBusy, setYamlBusy] = useState(false)
  // Qué trabajo eligió el YAML que se acaba de cargar, cuando cambió el de la sesión (D-JOB-17).
  // Es estado LOCAL y no del store porque nace y muere con esta pantalla —el sidebar ya cambió a la
  // vista— y porque `ConfigTab` no puede tener efectos: escribirlo desde el handler no necesita uno.
  const [jobNotice, setJobNotice] = useState<string | null>(null)
  const [presetBusy, setPresetBusy] = useState(false)
  const [presetError, setPresetError] = useState<string | null>(null)
  const fileInputRef = useRef<HTMLInputElement | null>(null)
  // Último valor no nulo de cada sección, para restaurarlo al reactivarla. Cubre el caso real
  // —apagar y arrepentirse— sin perder lo configurado; `variantDefaults` es poco profundo y
  // resembrar desde cero dejaría secciones como `survival` o `data` incompletas.
  const lastSectionValue = useRef<Record<string, unknown>>({})

  // "Configuración estándar": recarga el preset estándar del backend y lo resiembra por el MISMO
  // `applyPreset` que usan RunTab/enterDemo, para que —además de sembrar config/dataset/seed— CORTE
  // la corrida previa (results/lastRun). Sin ese corte (bug P0), Resultados y Reporte seguían
  // mostrando el dominio VIEJO con lineage mixto. El endpoint estándar (`getPreset`, sin id) ignora
  // el `presetId`; RunTab está DESMONTADO en esta pestaña, así que `resetOutcome` es no-op (su
  // outcome remonta idle solo al volver a Ejecutar) — el corte esencial es el de results/lastRun.
  const handleLoadPreset = useCallback(async () => {
    setPresetError(null)
    setJobNotice(null) // el aviso hablaba del config anterior; éste ya no es ése
    setPresetBusy(true)
    try {
      // Un ejemplo es un config traído de fuera igual que un YAML, así que también selecciona su
      // trabajo (D-JOB-17): sin esto, cargarlo desde IFRS 9 dejaba un config de scorecard bajo el
      // sidebar de IFRS 9. El endpoint estándar devuelve el ejemplo de scorecard.
      const cambio = await applyPreset("", job, {
        getPreset: () => getPreset(),
        loadJobs,
        setConfig,
        setJob,
        setDatasetId,
        setSelectedDataset,
        setSeed,
        setResults,
        setLastRun,
        resetOutcome: () => {},
      })
      setJobNotice(jobSwitchNotice(cambio, "ejemplo"))
    } catch (err) {
      setPresetError(yamlErrorMessage(err))
    } finally {
      setPresetBusy(false)
    }
  }, [
    job,
    setConfig,
    setJob,
    setDatasetId,
    setSelectedDataset,
    setSeed,
    setResults,
    setLastRun,
  ])

  // "Empezar de cero": siembra el config mínimo del schema (defaults vacíos) — sin backend — y CORTA
  // la corrida previa (results/lastRun). "De cero" cambia de dominio, así que Resultados y Reporte no
  // deben seguir mostrando la corrida anterior con lineage mixto (mismo P0 que el cambio de preset).
  const handleStartBlank = useCallback(() => {
    setPresetError(null)
    setJobNotice(null) // el aviso hablaba del YAML anterior; este config ya no es ése
    setConfig(structuredClone(schema?.payload.defaults ?? {}))
    setDatasetId(null) // "de cero" no trae dataset → Ejecutar queda bloqueado hasta elegir uno
    setSeed({ kind: "defaults" })
    // Corte con la corrida previa: evita el lineage mixto en Resultados/Reporte.
    setResults(null)
    setLastRun(null)
  }, [schema, setConfig, setDatasetId, setSeed, setResults, setLastRun])

  const setField = useCallback(
    (path: Path, value: unknown) => {
      // `undefined` = «vaciar este control» ⇒ se BORRA la clave y el campo vuelve a pintar su
      // valor predeterminado (D-FX-7/D-FX-8). Escribir `undefined` dejaba la clave en el objeto
      // con un valor que `JSON.stringify` descarta: el config se veía sparse por fuera y sucio por
      // dentro, y la comparación estructural de «renderizar no escribe» dejaba de ser decidible.
      // `null` NO borra: apagar algo a propósito es una decisión explícita del usuario.
      setConfig((current) =>
        value === undefined
          ? removeAtPath(current, path)
          : setAtPath(current, path, value),
      )
    },
    [setConfig],
  )

  // ⚠️ Esta pestaña NO puede tener efectos: es un editor puro, y el gate de `bootstrap.test.ts`
  // lo hace cumplir (un efecto de montaje resembraba el preset y pisaba las ediciones, UX1). El
  // foco que piden los avisos del preflight lo atiende `App`, que además es la dueña de la
  // navegación; aquí sólo se DECLARA el pedido.

  const handleDownloadYaml = async () => {
    setYamlError(null)
    setYamlBusy(true)
    try {
      const { yaml } = await configToYaml(config)
      triggerDownload(yaml, "nikodym-config.yaml")
    } catch (err) {
      setYamlError(yamlErrorMessage(err))
    } finally {
      setYamlBusy(false)
    }
  }

  const handleUploadYaml = async (
    event: React.ChangeEvent<HTMLInputElement>,
  ) => {
    const file = event.target.files?.[0]
    event.target.value = "" // permite recargar el mismo archivo
    if (!file) return
    setYamlError(null)
    setJobNotice(null)
    setYamlBusy(true)
    try {
      const text = await file.text()
      // El flujo completo —config, trabajo y seed— vive en `applyYamlConfig`, fuera del componente:
      // es lógica sin React y así se puede ejercitar en vitest, que corre sin DOM.
      const cambio = await applyYamlConfig(text, file.name, job, {
        fromYaml: configFromYaml,
        loadJobs,
        setConfig,
        setJob,
        setSeed,
      })
      setJobNotice(jobSwitchNotice(cambio, "archivo"))
    } catch (err) {
      setYamlError(yamlErrorMessage(err))
    } finally {
      setYamlBusy(false)
    }
  }

  // El schema lo carga el arranque de la sesión (provider), no esta pestaña: mientras no llega,
  // se espera. En cuanto está, el config YA viene sembrado y validado desde el store.
  if (schema === null) {
    return (
      <div className="flex items-center gap-2 py-16 text-sm text-muted-foreground">
        <Loader2 className="size-4 animate-spin" aria-hidden="true" />
        Cargando configuración…
      </div>
    )
  }

  const { payload, source, error } = schema
  const defs = payload.json_schema.$defs ?? {}
  // Catálogo de defaults efectivos (D-FX-5). `usableCatalog` descarta una versión que este front no
  // sabe interpretar: pintar defaults inventados es peor que no pintar ninguno.
  const catalogo = usableCatalog(payload.effective_defaults)
  // Columnas del dataset activo: son las OPCIONES de todo campo que declare `column_role: "input"`
  // (`binning.feature_columns`, `categorical_columns`, `data.schema.unique_keys`…). El schema no
  // puede traerlas —dependen del archivo del usuario—, así que viajan como contexto de datos.
  // `undefined` (no `[]`) cuando aún no hay dataset: el widget distingue «no hay lista» de
  // «la lista está vacía» y ofrece entrada libre en vez de un «Sin opciones.» que miente.
  // D-PRO-2: además de las del archivo, las que el pipeline ESCRIBE aguas arriba y que esta
  // sección puede nombrar. El backend las manda ya resueltas por sección (D-RAM-7 aplicado allí),
  // así que aquí sólo se busca la clave: recomponerlas reintroduciría el defecto en el front.
  const producidas =
    validation.kind === "valid" ? (validation.producedColumns ?? {}) : {}
  const datasetColumns = columnasOfrecibles(selectedDataset, producidas, section)
  // Sólo para la PRESENTACIÓN (D-PRO-4): qué opciones no vienen del archivo, para que el
  // desplegable no las rotule «del archivo» —que sería falso— y diga de dónde salen.
  const producedColumns = producidas[section] ?? []
  // Y el ÍNDICE aparte (D-PRO-1/5): no es una columna, y sólo lo puede nombrar un campo con
  // `column_role: "index"`. Publicarlo dentro de `columns` hacía que la interfaz lo ofreciera
  // donde el motor no puede leerlo.
  const datasetIndexColumns = columnasDeIndice(selectedDataset)
  // Y los VALORES observados de cada columna, que son las opciones de todo campo que declare
  // `column_values_from` (los tres de la división ya marcada en el archivo). Se indexa por nombre
  // de columna porque así lo pregunta el campo: la anotación nombra a un hermano, el hermano
  // nombra la columna. El mapeo vive en `lib/datasets` para que se pueda probar: aquí dentro,
  // vitest —que corre sin DOM— no lo alcanzaría.
  const datasetColumnValues = columnValuesByName(selectedDataset)
  // Solo la sección activa (elegida en el sidebar). La pregunta es «¿el schema cargado trae un
  // formulario para esta clave?», NO «¿está en una lista de siete?»: el filtro por whitelist es lo
  // que mantenía provisiones y survival fuera del formulario aunque el backend las mandara
  // expandidas. Así el aviso de abajo recupera su propósito real: sección opaca por extra ausente.
  const sectionEntry = configSectionSchema(payload, section)
  const sectionRenderable = sectionEntry !== null
  const resolvedSection = sectionEntry
    ? resolveRef(sectionEntry.schema, defs)
    : null

  // Una sección apagada es `null` en el config: el orquestador no puede referenciarla desde
  // `run.steps` y el motor no la ejecuta. Es exactamente lo que se puede hacer por código, y hasta
  // ahora la UI no alcanzaba porque el schema compuesto perdía la nulabilidad al empotrar.
  const sectionValue = config[section]
  const sectionActive = sectionValue !== null && sectionValue !== undefined
  const toggleSection = (next: boolean) => {
    if (next) {
      // Activar una sección es un gesto de ESTRUCTURA (D-FX-8): se escriben todas las hojas con
      // default de su proyección canónica. `defaultForSchema` queda de respaldo sin catálogo —sólo
      // ve los `default` del JSON Schema, que no existen para los submodelos con `default_factory`,
      // y por eso sembraba secciones a medias—.
      const canonica = childMap(nodeAtPath(catalogo, [section]))
      const restaurado =
        lastSectionValue.current[section] ??
        (canonica
          ? canonicalProjection(canonica)
          : resolvedSection
            ? defaultForSchema(resolvedSection, defs)
            : {})
      setField([section], restaurado)
    } else {
      if (sectionValue !== undefined) lastSectionValue.current[section] = sectionValue
      setField([section], null)
    }
  }
  const banner = SOURCE_BANNER[source]
  const errorLookup =
    validation.kind === "invalid" ? validation.lookup : undefined
  // El round-trip YAML necesita el backend (no se parsea YAML en el front): se deshabilita
  // sin conexión, con aviso claro (restricción del goal: el front funciona aunque caiga).
  const backendDown =
    source === "fixture-offline" || validation.kind === "unreachable"

  return (
    <TooltipProvider delay={200}>
      <div className="space-y-6">
        <div
          className={
            banner.tone === "ok"
              ? "rounded-lg border border-brand-cyan/25 bg-brand-cyan/5 px-3 py-2 text-xs text-muted-foreground"
              : "rounded-lg border border-amber-400/25 bg-amber-400/5 px-3 py-2 text-xs text-amber-200/80"
          }
        >
          {banner.text}
          {error ? <span className="opacity-70"> ({error})</span> : null}
        </div>

        {/* Aviso sobrio de qué config se sembró (SDD §3.2): preset estándar por defecto / vacío. */}
        {seedNotice(seed) ? (
          <p
            className={
              seed?.kind === "preset"
                ? "flex items-center gap-1.5 text-xs text-eyebrow/90"
                : "text-xs text-muted-foreground"
            }
          >
            {seed?.kind === "preset" ? (
              <CircleCheck className="size-3.5" aria-hidden="true" />
            ) : null}
            {seedNotice(seed)}
          </p>
        ) : null}

        {/* Lo que sólo el usuario puede decidir, ANTES de los parámetros de detalle (D-OBL-8). */}
        <RequiredDecisions
          // El veredicto del motor es la mitad del criterio de «contestada» (D-RES-1): sin él, un
          // config que el motor rechaza salía con el tilde verde. Ya está en el store, así que esto
          // no añade una sola llamada a la red.
          decisions={decisionStatuses(job, config as Record<string, unknown> | null, validation)}
          section={section}
          onFocus={setFocusField}
          onAnswerForm={(path, template) => {
            // La plantilla viene del backend y se escribe TAL CUAL: el front no compone config de
            // dominio (SDD-23 §11). Después se enfoca el campo, porque la forma deja huecos a
            // propósito y el usuario tiene que ir a llenarlos — salvo la que no deja ninguno.
            setField(path.split(".") as Path, template)
            setFocusField(path)
          }}
          // Lo que se puede PROPONER, calculado al pintar y sin tocar el config (D-COL-8). Es una
          // función y no un valor porque depende de la forma, y el config sólo cambia con el clic.
          //
          // ⚠️ Se pasan los insumos que el trabajo ACTUAL pide, no el mapa entero: los archivos
          // subidos sobreviven al cambio de trabajo y las formas se heredan por sección, así que
          // sin acotar aquí un artefacto de otro trabajo proponía sus columnas donde nadie lo pidió.
          precargas={(forma) =>
            precargasDeForma(
              forma,
              requiredExternalArtifacts(job, (config ?? {}) as Record<string, unknown>),
              externalInputs,
              datasetId,
            )
          }
        />

        {/* El abanico va DESPUÉS de las obligatorias, en el mismo paso (D-ABA-10): aquéllas
            impiden correr y éste no. */}
        <MethodologyChoices
          choices={methodologyStatuses(job, config as Record<string, unknown> | null)}
          section={section}
          onChoose={(path, value) => {
            // Escribe exactamente el mismo valor que escribirlo a mano en el formulario, así que
            // dos usuarios que llegan al mismo config por caminos distintos producen la misma
            // identidad (D-ABA-12). El front no compone config de dominio: el valor lo declara el
            // catálogo y aquí sólo se copia.
            setField(path.split(".") as Path, value)
          }}
          onFocus={setFocusField}
        />

        {/* Barra de estado + acciones (SDD §3.2 preset · §3.3 hash en vivo · §3.4 round-trip YAML). */}
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-border bg-foreground/[0.02] px-3 py-2">
          <div role="status" aria-live="polite" className="min-h-5">
            <HashStatus
              state={validation}
              seccionActiva={section}
              onJumpToField={onJumpToField}
            />
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={handleLoadPreset}
              disabled={presetBusy || backendDown}
              // El botón dice «ejemplo» y no «configuración estándar» desde D-JOB-2: cargar un
              // preset trae también SU dataset de muestra, así que llamarlo «estándar» invitaba a
              // leerlo como el punto de partida normal del trabajo propio, que es justo el énfasis
              // que este cambio retira.
              title={
                backendDown
                  ? "Requiere el backend"
                  : "Cargar un ejemplo listo para correr, con su dataset de muestra"
              }
            >
              {presetBusy ? (
                <Loader2 className="animate-spin" aria-hidden="true" />
              ) : (
                <Sparkles aria-hidden="true" />
              )}
              Ver un ejemplo
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={handleStartBlank}
              // En la demo estática vaciar el config deja el recorrido sin salida: `handleStartBlank`
              // borra el dataset (Ejecutar queda bloqueado) y corta la corrida, pero aquí no hay
              // backend con el cual elegir otro dataset ni volver a correr. Se apaga con el motivo
              // a la vista, en vez de ofrecer un botón que rompe la demo.
              disabled={DEMO_MODE}
              title={
                DEMO_MODE
                  ? "No disponible en la demo: sirve los resultados de tres corridas ya ejecutadas, sin backend que corra un config nuevo"
                  : "Vaciar el formulario y armar el config desde cero"
              }
            >
              <FilePlus2 aria-hidden="true" />
              Empezar de cero
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={handleDownloadYaml}
              disabled={yamlBusy || backendDown}
              title={backendDown ? "Requiere el backend" : "Descargar el YAML canónico"}
            >
              <Download aria-hidden="true" />
              Descargar YAML
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => fileInputRef.current?.click()}
              // En demo el YAML subido NO se lee: `demoConfigFromYaml` devuelve el config del preset
              // activo, así que el botón parecía funcionar y en realidad ignoraba el archivo del
              // usuario. Fingir que se cargó es peor que decir que no se puede.
              disabled={yamlBusy || backendDown || DEMO_MODE}
              title={
                DEMO_MODE
                  ? "No disponible en la demo: convertir un YAML propio exige el backend que valida el config"
                  : backendDown
                    ? "Requiere el backend"
                    : "Cargar un YAML existente"
              }
            >
              <Upload aria-hidden="true" />
              Cargar YAML
            </Button>
            <input
              ref={fileInputRef}
              type="file"
              accept=".yaml,.yml"
              onChange={handleUploadYaml}
              className="hidden"
              aria-hidden="true"
            />
          </div>
        </div>
        {/* Config válido pero inejecutable (enmienda VALIDACION-PIPELINE): se avisa MIENTRAS se
            edita, no al apretar Ejecutar. No bloquea la corrida (D-PIPE-4): el motor es la
            autoridad y registra el intento con su diagnóstico, así que quitarle al usuario la
            posibilidad de intentar sería peor que un aviso que alguna vez sobre. */}
        {pipelineWarning(validation) ? (
          <div
            role="status"
            aria-live="polite"
            className="flex items-start gap-2 rounded-lg border border-amber-400/30 bg-amber-400/[0.06] px-3 py-2 text-xs text-amber-100/90"
          >
            <TriangleAlert className="mt-0.5 size-3.5 shrink-0" aria-hidden="true" />
            <span>
              <strong className="font-medium">
                Este config todavía no se puede ejecutar.
              </strong>{" "}
              {pipelineWarning(validation)}
            </span>
          </div>
        ) : null}

        {/* Desajustes del preflight que caen en ESTA sección (D-PRE-8): el aviso se pinta junto al
            formulario que los arregla, y el click enfoca el campo exacto. */}
        <PreflightNotice
          state={preflight}
          section={section}
          onJump={setFocusField}
        />

        {/* El config traído de fuera —YAML propio o ejemplo— cambió el trabajo de la sesión
            (D-JOB-17). No es un error ni un aviso de algo que corregir: es la explicación de por qué
            el menú de la izquierda acaba de cambiar, y por eso se pinta en tono neutro y con
            `aria-live` — el sidebar cambia fuera de la vista de quien usa lector de pantalla. */}
        {jobNotice ? (
          <p
            role="status"
            aria-live="polite"
            className="flex items-start gap-2 rounded-lg border border-brand-cyan/25 bg-brand-cyan/5 px-3 py-2 text-xs text-muted-foreground"
          >
            <CircleCheck className="mt-0.5 size-3.5 shrink-0" aria-hidden="true" />
            <span>{jobNotice}</span>
          </p>
        ) : null}

        {presetError ? (
          <p className="text-xs text-destructive">{presetError}</p>
        ) : null}
        {yamlError ? (
          <p className="text-xs text-destructive">{yamlError}</p>
        ) : backendDown ? (
          <p className="text-xs text-muted-foreground">
            Round-trip YAML deshabilitado sin backend.
          </p>
        ) : null}

        {sectionRenderable && resolvedSection ? (
          <div className="space-y-4">
            {sectionEntry.nullable ? (
              <SectionToggle
                sectionKey={section}
                active={sectionActive}
                onToggle={toggleSection}
              />
            ) : null}
            {sectionActive ? (
              <ConfigSectionForm
                sectionKey={section}
                schema={resolvedSection}
                defs={defs}
                config={config}
                setField={setField}
                errors={errorLookup}
                datasetColumns={datasetColumns}
                datasetIndexColumns={datasetIndexColumns}
                producedColumns={producedColumns}
                datasetColumnValues={datasetColumnValues}
                effectiveDefaults={catalogo}
                disabledEnumValues={payload.disabled_methodology_values}
              />
            ) : (
              <p className="rounded-xl border border-dashed border-border bg-card/50 p-5 text-sm text-muted-foreground">
                Sección desactivada: el motor no la ejecuta. Al reactivarla vuelve con los valores
                que tenía.
              </p>
            )}
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">
            La sección «{section}» no está disponible en el schema cargado.
          </p>
        )}

        <details className="text-xs text-muted-foreground">
          <summary className="cursor-pointer text-muted-foreground">
            Ver config en construcción (JSON)
          </summary>
          <pre className="mt-2 max-h-64 overflow-auto rounded-lg border border-border bg-foreground/[0.02] p-3 font-mono">
            {JSON.stringify(config, null, 2)}
          </pre>
        </details>
      </div>
    </TooltipProvider>
  )
}
