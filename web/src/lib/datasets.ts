/**
 * Lógica PURA de la pestaña Datos (sin React): normaliza las dos formas de dataset a un
 * tipo común y valida la extensión antes de subir. El catálogo (GET /api/datasets) trae
 * `id` y columnas con `role`; una subida (POST /api/upload) trae `dataset_id` y columnas
 * SIN `role`. El front las unifica en `SelectedDataset` para poder previsualizar cualquiera
 * de las dos igual. Testeable con vitest en entorno `node`, como el resto de `lib/*.test.ts`.
 */

import type { DatasetInfo, UploadedDataset } from "./api"

/**
 * Dataset elegido, normalizado desde cualquiera de las dos rutas (catálogo o subida). `role`
 * es opcional: el catálogo lo trae por columna; una subida no lo conoce y queda `undefined`.
 */
export interface SelectedDataset {
  id: string
  name: string
  nRows: number
  columns: {
    name: string
    dtype: string
    role?: string
    /**
     * Valores más frecuentes de la columna (D-COL-7). Las DOS rutas lo traen —el catálogo y una
     * subida—, a diferencia de `role`, que sólo trae el catálogo. Ausente o vacío = «no se midió».
     */
    values?: string[]
  }[]
  /**
   * El ÍNDICE del archivo (D-PRO-1). No es una columna: sólo lo puede nombrar un campo con
   * `column_role: "index"`. Lista vacía = el archivo no trae índice nombrado, que es lo normal en
   * un CSV o un Excel.
   */
  indexColumns: { name: string; dtype: string }[]
}

/** Extensiones que acepta POST /api/upload (B36b): CSV, Excel y Parquet. */
export const ALLOWED_DATA_EXTENSIONS = [".csv", ".xlsx", ".parquet"] as const

/**
 * ¿El nombre de archivo tiene una extensión de dataset aceptada? (case-insensitive). Útil para
 * dar un error local claro ANTES de subir, sin depender de que el backend rechace el archivo.
 */
export function isAllowedDataFile(filename: string): boolean {
  const lower = filename.toLowerCase()
  return ALLOWED_DATA_EXTENSIONS.some((ext) => lower.endsWith(ext))
}

/** Normaliza un item del catálogo (conserva `id` y el `role` de cada columna). */
export function fromCatalog(info: DatasetInfo): SelectedDataset {
  return {
    id: info.id,
    name: info.name,
    nRows: info.n_rows,
    columns: info.columns.map((c) => ({
      name: c.name,
      dtype: c.dtype,
      role: c.role,
      values: c.values,
    })),
    indexColumns: info.index_columns.map((c) => ({ name: c.name, dtype: c.dtype })),
  }
}

/** Normaliza la respuesta de una subida (usa `dataset_id`; sus columnas no traen `role`). */
export function fromUpload(resp: UploadedDataset): SelectedDataset {
  return {
    id: resp.dataset_id,
    name: resp.name,
    nRows: resp.n_rows,
    columns: resp.columns.map((c) => ({
      name: c.name,
      dtype: c.dtype,
      role: undefined,
      values: c.values,
    })),
    // Opcional en el payload: un backend anterior a D-PRO-1 no lo trae, y «sin índice» es
    // exactamente lo que ocurría antes de que existiera este campo.
    indexColumns: (resp.index_columns ?? []).map((c) => ({ name: c.name, dtype: c.dtype })),
  }
}

/**
 * Valores ofrecibles del dataset activo, indexados por NOMBRE de columna (D-COL-7).
 *
 * Es lo que consume `column_values_from` en el formulario. Una columna sin valores medidos **no
 * entra en el mapa**: `[]` significaría «esta columna no tiene valores», y lo que el backend dice
 * con la lista vacía es «no se midió» —demasiados valores distintos, o dataset del catálogo aún sin
 * materializar—. La diferencia decide si el widget cae a entrada libre o pinta «Sin opciones.».
 *
 * Vive aquí y no en el componente porque es LÓGICA, no presentación: vitest corre sin DOM, así que
 * dentro de `ConfigTab` no habría forma de probarla.
 */
export function columnValuesByName(
  selected: SelectedDataset | null,
): Record<string, string[]> | undefined {
  if (selected === null) return undefined
  return Object.fromEntries(
    selected.columns
      .filter((c) => c.values !== undefined && c.values.length > 0)
      .map((c) => [c.name, c.values as string[]]),
  )
}

/**
 * Reconcilia la ficha ACTIVA con un catálogo recién pedido, aunque el dataset no haya cambiado.
 *
 * 🔴 El motivo es un defecto medido: en un workdir nuevo, `GET /api/datasets` describe los datasets
 * del catálogo **sin materializar**, y por eso todas sus columnas llegan con `values: []`. Quien
 * los materializa —y escribe el perfil— es el preflight, que corre DESPUÉS de que el usuario ya
 * eligió. La ficha activa se quedaba con aquella instantánea pobre para toda la sesión, así que
 * para los datasets del catálogo las casillas de valores **no aparecían nunca** y el usuario volvía
 * a teclear a ciegas. (Las subidas no lo sufren: `POST /api/upload` mide el perfil en el acto.)
 *
 * Devuelve la MISMA referencia cuando no hay nada que aportar —dataset subido, catálogo todavía sin
 * cargar, o valores ya presentes—, de modo que el efecto que la consume no entre en bucle.
 */
export function reconcileSelected(
  selected: SelectedDataset | null,
  catalog: DatasetInfo[],
): SelectedDataset | null {
  if (selected === null) return null
  const info = catalog.find((d) => d.id === selected.id)
  if (!info) return selected
  return aportaValores(selected, info) ? fromCatalog(info) : selected
}

/** ¿El item del catálogo publica valores de alguna columna que la ficha activa todavía no tiene? */
function aportaValores(selected: SelectedDataset, info: DatasetInfo): boolean {
  const actuales = new Map(selected.columns.map((c) => [c.name, c.values ?? []]))
  return info.columns.some(
    (c) => (c.values?.length ?? 0) > 0 && (actuales.get(c.name)?.length ?? 0) === 0,
  )
}

/** Etiqueta de una opción del selector de catálogo, p.ej. `Consumo · 10.000 filas`. */
export function datasetOptionLabel(info: DatasetInfo): string {
  return `${info.name} · ${info.n_rows.toLocaleString("es-CL")} filas`
}

/** Una opción del selector de datasets de ejemplo: etiqueta visible + id que setea al elegirla. */
export interface DatasetOption {
  label: string
  value: string
}

/**
 * Modelo de la sección "Datasets de ejemplo" según el modo de despliegue (lógica pura, SDD-23 §1).
 *
 * - Backend real (`demoMode === false`) → `picker`: el usuario elige cualquiera de los datasets del
 *   catálogo y esa elección re-corre el pipeline sobre ese dataset (Resultados/Informe coherentes).
 * - Demo estática (`demoMode === true`) → `locked`: los resultados los fija el PRESET activo, NO el
 *   `datasetId` (ver `lib/demo.ts`: `demoRunPipeline`/`demoGetResults` ignoran el dataset). Dejar
 *   elegir otro dataset mostraría una ficha que no coincide con Resultados/Informe. Por eso el picker
 *   queda BLOQUEADO al único dataset del preset activo —el que cuelga de `datasetId`—, sin exponer
 *   opciones para setear otro.
 */
export type DatasetCatalogView =
  | { kind: "picker"; items: DatasetOption[]; value: string | null }
  | { kind: "locked"; dataset: DatasetInfo | null }

/**
 * Decide cómo presentar el catálogo de datasets. En la demo estática lo BLOQUEA al dataset del preset
 * activo (`datasetId`) para que la ficha nunca discrepe de la corrida real que sirven los fixtures;
 * en el backend real devuelve el picker completo, con `value` reflejando `datasetId` solo si es una
 * opción del catálogo (un id subido, fuera del catálogo, deja el selector en su placeholder).
 */
export function datasetCatalogView(
  demoMode: boolean,
  datasets: DatasetInfo[],
  datasetId: string | null,
): DatasetCatalogView {
  if (demoMode) {
    return {
      kind: "locked",
      dataset: datasets.find((d) => d.id === datasetId) ?? null,
    }
  }
  const value = datasets.some((d) => d.id === datasetId) ? datasetId : null
  return {
    kind: "picker",
    items: datasets.map((d) => ({ label: datasetOptionLabel(d), value: d.id })),
    value,
  }
}

/**
 * Qué nombres de columna puede ofrecer (y aceptar sin marcar en rojo) un campo de ESTA sección.
 *
 * Es la unión de dos procedencias que hasta D-PRO-2 el front no sabía distinguir: las columnas que
 * trae el archivo, y las que **escribe el pipeline aguas arriba** —el target, la partición—. Con
 * sólo las primeras, el formulario pintaba en rojo `survival.input.event_col = "target"` con
 * «Esa columna no está en el dataset cargado» mientras `check_dataset` la daba por buena y la
 * corrida llegaba a `done`: dos superficies del mismo producto contradiciéndose en la misma
 * pantalla, sobre 32 de las 47 rutas con rol `input`.
 *
 * 🔴 `producidas` llega YA RESUELTO por sección desde el backend y **aquí no se recompone**: cada
 * entrada excluye lo que produce la propia sección (D-RAM-7). Por eso un campo de `data` no ve
 * `partition` —y sigue marcándose en rojo, que es lo correcto: `DataStep` valida su esquema antes
 * de escribir nada— mientras uno de `survival` sí la ve. Unir las listas aquí, o buscar por otra
 * clave, reintroduciría en la interfaz el defecto que D-RAM-7 cerró en el motor.
 *
 * Devuelve `undefined` sin dataset, igual que antes: es «no hay lista que ofrecer» —el widget cae a
 * entrada libre— y no «la lista está vacía». Ofrecer sólo las producidas sin archivo cargado sería
 * un menú de dos nombres que el usuario no reconoce.
 */
export function columnasOfrecibles(
  dataset: SelectedDataset | null,
  producidas: Record<string, string[]>,
  section: string,
): string[] | undefined {
  if (dataset === null) return undefined
  const delArchivo = dataset.columns.map((c) => c.name)
  const vistas = new Set(delArchivo)
  return [...delArchivo, ...(producidas[section] ?? []).filter((c) => !vistas.has(c))]
}

/** Los nombres del ÍNDICE del dataset activo (D-PRO-5); `undefined` sin dataset. */
export function columnasDeIndice(dataset: SelectedDataset | null): string[] | undefined {
  return dataset === null ? undefined : dataset.indexColumns.map((c) => c.name)
}
