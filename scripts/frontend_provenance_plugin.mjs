/**
 * Procedencia fail-closed del bundle normal de Nikodym.
 *
 * `transform` conserva la unión conservadora; `generateBundle` liga fuentes
 * directas por output y emite notices; `writeBundle` hashea los bytes finales.
 */

import { createHash } from "node:crypto"
import {
  existsSync,
  lstatSync,
  mkdirSync,
  readdirSync,
  readFileSync,
  realpathSync,
  rmSync,
  writeFileSync,
} from "node:fs"
import { createRequire } from "node:module"
import path from "node:path"
import { fileURLToPath } from "node:url"

const PROJECT_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..")
const WEB_ROOT = path.join(PROJECT_ROOT, "web")
const EVIDENCE_DIR = path.join(WEB_ROOT, "dist", "evidence")
const EVIDENCE_PATH = path.join(EVIDENCE_DIR, "frontend-provenance.json")
const NOTICE_NAME = "THIRD_PARTY_NOTICES.frontend.txt"
const LEGAL_STEM = /^(?:licen[cs]e|notice|copying|copyright(?:notice)?)$/i
const LICENSE_QUALIFIER =
  /^(?:licen[cs]e)[-.](?:mit|isc|unlicense|0bsd|bsd(?:-?\d-clause)?|apache(?:-?2(?:\.0)?)?|python(?:-?2(?:\.0)?)?|cc(?:-by)?(?:-?\d(?:\.\d)*)?|blueoak(?:-?\d(?:\.\d)*)*)$/i
const TEXT_LEGAL_EXTENSION = /\.(?:txt|text|md|markdown|rst)$/i
const UTF8_FATAL = new TextDecoder("utf-8", { fatal: true })

export function sha256(value) {
  return createHash("sha256").update(value).digest("hex")
}

function decodeModuleIdToFixedPoint(value, original) {
  let decoded = value
  for (let round = 0; round < 12; round += 1) {
    let next
    try {
      next = decodeURIComponent(decoded)
    } catch {
      throw new Error(`Id de módulo no normalizable: ${original}`)
    }
    if (next === decoded) {
      if (decoded.includes("%")) {
        throw new Error(`Id de módulo conserva escape porcentual: ${original}`)
      }
      return decoded
    }
    decoded = next
  }
  throw new Error(`Id de módulo excede decodificación porcentual: ${original}`)
}

export function normalizeModuleId(id) {
  let normalized = id.replace(/^\0+/, "")
  try {
    if (/^file:\/\//i.test(normalized)) {
      const url = new URL(normalized)
      url.search = ""
      url.hash = ""
      normalized = fileURLToPath(url)
    }
  } catch {
    throw new Error(`Id de módulo no normalizable: ${id}`)
  }
  normalized = decodeModuleIdToFixedPoint(normalized, id)
  const query = normalized.indexOf("?")
  const hash = normalized.indexOf("#")
  const cut = [query, hash].filter((position) => position >= 0)
  if (cut.length) normalized = normalized.slice(0, Math.min(...cut))
  normalized = normalized.replaceAll("\\", "/")
  if (normalized.startsWith("/@fs/")) normalized = normalized.slice(4)
  if (path.isAbsolute(normalized)) normalized = path.normalize(normalized).replaceAll("\\", "/")
  if (normalized.includes("\0")) throw new Error(`Id de módulo contiene NUL: ${id}`)
  return normalized
}

export function isDemoFixtureId(id) {
  return /(?:^|\/)web\/src\/fixtures\/demo\//.test(normalizeModuleId(id))
}

function walk(directory, { skipNodeModules = false, rejectSymlinks = false } = {}) {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const absolute = path.join(directory, entry.name)
    if (entry.isSymbolicLink()) {
      if (rejectSymlinks) throw new Error(`Symlink inesperado al recolectar evidencia: ${absolute}`)
      return []
    }
    if (entry.isDirectory()) {
      if (skipNodeModules && entry.name === "node_modules") return []
      return walk(absolute, { skipNodeModules, rejectSymlinks })
    }
    return entry.isFile() ? [absolute] : []
  })
}

function assertInsideWeb(candidate, label) {
  const webRoot = realpathSync(WEB_ROOT)
  const resolved = realpathSync(candidate)
  if (resolved !== webRoot && !resolved.startsWith(`${webRoot}${path.sep}`)) {
    throw new Error(`${label} fuera de web/: ${candidate}`)
  }
  return resolved
}

function assertSafeRelative(relativePath, label) {
  if (
    typeof relativePath !== "string"
    || relativePath.length === 0
    || path.isAbsolute(relativePath)
    || path.win32.isAbsolute(relativePath)
    || relativePath.includes("\\")
    || relativePath.split("/").some((part) => part === "" || part === "." || part === "..")
  ) {
    throw new Error(`${label}: ruta relativa insegura ${String(relativePath)}`)
  }
  return relativePath
}

function assertRegularInside(root, relativePath, label) {
  assertSafeRelative(relativePath, label)
  const absolute = path.resolve(root, relativePath)
  if (!absolute.startsWith(`${root}${path.sep}`)) {
    throw new Error(`${label}: ruta escapa package root ${relativePath}`)
  }
  const stats = lstatSync(absolute)
  if (stats.isSymbolicLink() || !stats.isFile()) {
    throw new Error(`${label}: archivo legal no regular ${relativePath}`)
  }
  const resolved = realpathSync(absolute)
  if (!resolved.startsWith(`${root}${path.sep}`)) {
    throw new Error(`${label}: ruta legal resuelve fuera del paquete ${relativePath}`)
  }
  return resolved
}

function nearestPackageRoot(moduleId) {
  let current = path.dirname(moduleId)
  const boundary = path.parse(current).root
  while (current !== boundary) {
    const packageJson = path.join(current, "package.json")
    if (existsSync(packageJson)) {
      const metadata = JSON.parse(readFileSync(packageJson, "utf8"))
      if (metadata.name && metadata.version) return { root: current, metadata }
    }
    current = path.dirname(current)
  }
  throw new Error(`No se pudo atribuir el módulo externo: ${moduleId}`)
}

function declaredLicenseReferences(metadata) {
  const references = new Set()
  if (typeof metadata.license === "string") {
    const match = metadata.license.match(/^SEE LICEN[CS]E IN (.+)$/i)
    if (match) references.add(match[1])
  }
  for (const [key, value] of Object.entries(metadata)) {
    if (
      typeof value === "string"
      && /^(?:license|notice|copying|copyright|attribution).*(?:file|path)$/i.test(key)
    ) {
      references.add(value)
    }
  }
  return references
}

function isConventionalLegalBasename(basename) {
  if (LEGAL_STEM.test(basename) || LICENSE_QUALIFIER.test(basename)) return true
  const stem = basename.replace(TEXT_LEGAL_EXTENSION, "")
  return stem !== basename && (LEGAL_STEM.test(stem) || LICENSE_QUALIFIER.test(stem))
}

function collectLicenseFiles(root, metadata) {
  const candidates = new Set(
    walk(root, { skipNodeModules: true, rejectSymlinks: true })
      .filter((file) => {
        const basename = path.basename(file)
        return isConventionalLegalBasename(basename)
      })
      .map((file) => path.relative(root, file).replaceAll("\\", "/")),
  )
  for (const reference of declaredLicenseReferences(metadata)) {
    assertSafeRelative(reference, `${metadata.name}@${metadata.version}`)
    if (!existsSync(path.resolve(root, reference))) {
      throw new Error(`${metadata.name}@${metadata.version}: referencia ausente ${reference}`)
    }
    const resolved = assertRegularInside(
      root,
      reference,
      `${metadata.name}@${metadata.version}`,
    )
    candidates.add(path.relative(root, resolved).replaceAll("\\", "/"))
  }
  return [...candidates].sort().map((relativePath) => {
    const bytes = readFileSync(path.join(root, relativePath))
    try {
      UTF8_FATAL.decode(bytes)
    } catch {
      throw new Error(`${metadata.name}@${metadata.version}: licencia no es UTF-8: ${relativePath}`)
    }
    return { relative_path: relativePath, size: bytes.length, sha256: sha256(bytes) }
  })
}

export function packageEvidence(moduleId) {
  const { root, metadata } = nearestPackageRoot(moduleId)
  const safeRoot = assertInsideWeb(root, `${metadata.name}@${metadata.version}`)
  const license = typeof metadata.license === "string" ? metadata.license.trim() : ""
  const licenseFiles = collectLicenseFiles(safeRoot, metadata)
  if (!license) throw new Error(`${metadata.name}@${metadata.version}: licencia ausente/ambigua`)
  if (licenseFiles.length === 0) {
    throw new Error(`${metadata.name}@${metadata.version}: no aporta texto de licencia`)
  }
  return {
    name: metadata.name,
    version: metadata.version,
    license,
    package_root: path.relative(realpathSync(WEB_ROOT), safeRoot).replaceAll("\\", "/"),
    license_files: licenseFiles,
    author: metadata.author ?? null,
    copyright: metadata.copyright ?? null,
    attribution: metadata.attribution ?? null,
  }
}

function packageMarker(name) {
  const direct = path.join(WEB_ROOT, "node_modules", name, "package.json")
  if (existsSync(direct)) return normalizeModuleId(direct)
  const virtualStore = path.join(WEB_ROOT, "node_modules", ".pnpm")
  const candidates = readdirSync(virtualStore)
    .map((entry) => path.join(virtualStore, entry, "node_modules", name, "package.json"))
    .filter(existsSync)
  if (candidates.length !== 1) {
    throw new Error(`Runtime externo no atribuible de forma única: ${name} (${candidates.length})`)
  }
  return normalizeModuleId(candidates[0])
}

function dependencyMarker(owner, dependency) {
  const ownerPackageJson = packageMarker(owner)
  const requireFromOwner = createRequire(ownerPackageJson)
  const resolved = requireFromOwner.resolve(dependency)
  const { root } = nearestPackageRoot(resolved)
  return normalizeModuleId(path.join(root, "package.json"))
}

function virtualRuntimeMarker(rawId) {
  const id = rawId.toLowerCase()
  if (id.includes("vite") || id.includes("modulepreload")) return packageMarker("vite")
  if (id.includes("rolldown") || id.includes("commonjshelpers")) {
    return dependencyMarker("vite", "rolldown")
  }
  if (id.includes("react-refresh")) return packageMarker("react-refresh")
  return null
}

function classifyId(rawId, virtualMarkers) {
  const normalized = normalizeModuleId(rawId)
  if (isDemoFixtureId(normalized)) {
    throw new Error(`Fixture demo observado en build normal: ${normalized}`)
  }
  if (rawId.startsWith("\0") && !normalized.includes("/node_modules/")) {
    const marker = virtualRuntimeMarker(rawId)
    if (!marker) throw new Error(`Runtime virtual externo desconocido: ${rawId}`)
    virtualMarkers.add(marker)
  } else if (
    (path.isAbsolute(normalized) || path.win32.isAbsolute(normalized))
    && normalized !== PROJECT_ROOT.replaceAll("\\", "/")
    && !normalized.startsWith(`${PROJECT_ROOT.replaceAll("\\", "/")}/`)
  ) {
    throw new Error(`Módulo absoluto fuera del repositorio: ${normalized}`)
  }
  return normalized
}

export function sourceId(id) {
  if (id === "index.html") return "web/index.html"
  if (id.includes("/node_modules/")) {
    const { root, metadata } = nearestPackageRoot(id)
    const relative = path.relative(root, id).replaceAll("\\", "/")
    return `node_modules/${metadata.name}@${metadata.version}/${relative}`
  }
  if (path.isAbsolute(id) && id.startsWith(`${PROJECT_ROOT}${path.sep}`)) {
    return path.relative(PROJECT_ROOT, id).replaceAll("\\", "/")
  }
  return `virtual:${id.replaceAll("\\", "/").replace(PROJECT_ROOT.replaceAll("\\", "/"), "<root>")}`
}

export function cssPackageImports(directory) {
  const modules = []
  for (const absolute of walk(directory).filter((file) => file.endsWith(".css"))) {
    const css = readFileSync(absolute, "utf8")
    for (const match of css.matchAll(/@import\s+["']([^"']+)["']/g)) {
      const specifier = match[1]
      if (![".", "/", "http:", "https:"].some((prefix) => specifier.startsWith(prefix))) {
        const parts = specifier.split("/")
        const packageName = specifier.startsWith("@") ? `${parts[0]}/${parts[1]}` : parts[0]
        modules.push(packageMarker(packageName))
      }
    }
  }
  return modules
}

function packageList(ids, cache = new Map()) {
  const packages = new Map()
  for (const id of ids) {
    if (!id.includes("/node_modules/")) continue
    const { root } = nearestPackageRoot(id)
    const cacheKey = realpathSync(root)
    let evidence = cache.get(cacheKey)
    if (!evidence) {
      evidence = packageEvidence(id)
      cache.set(cacheKey, evidence)
    }
    packages.set(`${evidence.name}@${evidence.version}`, evidence)
  }
  return [...packages.values()].sort((a, b) =>
    `${a.name}@${a.version}`.localeCompare(`${b.name}@${b.version}`),
  )
}

function metadataText(value) {
  if (value == null) return ""
  return typeof value === "string" ? value : JSON.stringify(value)
}

export function buildNotices(packages) {
  const sections = []
  for (const pkg of packages) {
    assertSafeRelative(pkg.package_root, `${pkg.name}@${pkg.version}`)
    const root = assertInsideWeb(path.resolve(WEB_ROOT, pkg.package_root), `${pkg.name}@${pkg.version}`)
    const packageJsonPath = assertRegularInside(
      root,
      "package.json",
      `${pkg.name}@${pkg.version}`,
    )
    const packageMetadata = JSON.parse(readFileSync(packageJsonPath, "utf8"))
    if (packageMetadata.name !== pkg.name || packageMetadata.version !== pkg.version) {
      throw new Error(`${pkg.name}@${pkg.version}: package_root no coincide con identidad`)
    }
    const heading = [`===== ${pkg.name}@${pkg.version} · ${pkg.license} =====`]
    for (const field of ["author", "copyright", "attribution"]) {
      const text = metadataText(pkg[field])
      if (text) heading.push(`${field}: ${text}`)
    }
    let section = `${heading.join("\n")}\n`
    for (const licenseFile of pkg.license_files) {
      const legalPath = assertRegularInside(
        root,
        licenseFile.relative_path,
        `${pkg.name}@${pkg.version}`,
      )
      const bytes = readFileSync(legalPath)
      if (bytes.length !== licenseFile.size || sha256(bytes) !== licenseFile.sha256) {
        throw new Error(
          `${pkg.name}@${pkg.version}: evidencia cambió ${licenseFile.relative_path}`,
        )
      }
      const text = UTF8_FATAL.decode(bytes)
      section += `--- ${licenseFile.relative_path} ---\n${text}`
      if (!text.endsWith("\n")) section += "\n"
    }
    sections.push(section)
  }
  return sections.join("\n")
}

function outputSourceIds(output, virtualMarkers) {
  const raw = new Set()
  if (output.type === "chunk") {
    for (const id of Object.keys(output.modules ?? {})) raw.add(id)
  }
  for (const id of output.originalFileNames ?? []) raw.add(id)
  if (output.originalFileName) raw.add(output.originalFileName)
  const normalized = [...raw].map((id) => classifyId(id, virtualMarkers))
  return [...new Set(normalized.map(sourceId))].sort()
}

export function frontendProvenancePlugin() {
  const transformed = new Set()
  const cssSources = new Set()
  const virtualMarkers = new Set()
  const directByOutput = new Map()
  const packageCache = new Map()
  let draft = null

  return {
    name: "nikodym-frontend-provenance",
    apply: "build",
    buildStart() {
      transformed.clear()
      cssSources.clear()
      virtualMarkers.clear()
      directByOutput.clear()
      packageCache.clear()
      draft = null
      rmSync(EVIDENCE_DIR, { recursive: true, force: true })
      transformed.add(packageMarker("vite"))
      transformed.add(dependencyMarker("vite", "rolldown"))
      for (const absolute of walk(path.join(WEB_ROOT, "src")).filter((file) =>
        file.endsWith(".css")
      )) {
        const normalized = classifyId(absolute, virtualMarkers)
        transformed.add(normalized)
        cssSources.add(normalized)
      }
      for (const id of cssPackageImports(path.join(WEB_ROOT, "src"))) {
        transformed.add(id)
        cssSources.add(id)
      }
    },
    transform(_code, id) {
      const normalized = classifyId(id, virtualMarkers)
      transformed.add(normalized)
      if (normalized.endsWith(".css")) cssSources.add(normalized)
      return null
    },
    generateBundle(_options, bundle) {
      for (const marker of virtualMarkers) transformed.add(marker)
      for (const [fileName, output] of Object.entries(bundle)) {
        directByOutput.set(fileName.replaceAll("\\", "/"), outputSourceIds(output, virtualMarkers))
      }
      for (const marker of virtualMarkers) transformed.add(marker)
      const conservativePackages = packageList(transformed, packageCache)
      const conservativeSources = [...transformed].map(sourceId).sort()
      const packages = packageList(transformed, packageCache)
      const notices = buildNotices(packages)
      this.emitFile({ type: "asset", fileName: NOTICE_NAME, source: notices })
      draft = {
        schema_version: 2,
        conservative_source_ids: conservativeSources,
        conservative_packages: conservativePackages.map(({ name, version }) => ({ name, version })),
        packages,
        notices_sha256: sha256(Buffer.from(notices)),
      }
    },
    writeBundle(options) {
      if (!draft) throw new Error("Procedencia no inicializada")
      const outDir = path.resolve(options.dir)
      const outputs = walk(outDir)
        .map((absolute) => {
          const relative = path.relative(outDir, absolute).replaceAll("\\", "/")
          const bytes = readFileSync(absolute)
          let directSources = directByOutput.get(relative) ?? []
          if (relative === NOTICE_NAME) directSources = draft.conservative_source_ids
          if (relative === "index.html") directSources = ["web/index.html"]
          if (relative.endsWith(".css")) {
            directSources = [
              ...new Set([...directSources, ...[...cssSources].map(sourceId)]),
            ].sort()
          }
          if (directSources.length === 0 && existsSync(path.join(WEB_ROOT, "public", relative))) {
            directSources = [`web/public/${relative}`]
          }
          if (directSources.length === 0) {
            throw new Error(`Output sin atribución de fuente: ${relative}`)
          }
          return {
            path: relative,
            size: bytes.length,
            sha256: sha256(bytes),
            direct_source_ids: directSources,
          }
        })
        .sort((a, b) => a.path.localeCompare(b.path))
      draft.outputs = outputs
      mkdirSync(EVIDENCE_DIR, { recursive: true })
      writeFileSync(EVIDENCE_PATH, `${JSON.stringify(draft, null, 2)}\n`)
    },
  }
}
