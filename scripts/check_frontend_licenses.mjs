/** Reconciliación fail-closed de licencias Node contra el bundle emitido. */

import { createHash } from "node:crypto"
import { existsSync, mkdirSync, readFileSync, realpathSync, writeFileSync } from "node:fs"
import path from "node:path"
import { fileURLToPath, pathToFileURL } from "node:url"

import { buildNotices } from "./frontend_provenance_plugin.mjs"

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..")
const WEB = path.join(ROOT, "web")
const EVIDENCE = path.join(WEB, "dist", "evidence")
const STATIC = path.join(ROOT, "src", "nikodym", "ui", "static")
const FORBIDDEN = /\b(?:AGPL|LGPL|GPL)(?:[-\s]?v?\d+(?:\.\d+)*)?\b/i
const PERMISSIVE = new Set([
  "0BSD",
  "Apache-2.0",
  "BSD-2-Clause",
  "BSD-3-Clause",
  "BlueOak-1.0.0",
  "CC-BY-4.0",
  "ISC",
  "MIT",
  "MIT AND ISC",
  "Python-2.0",
])

const keyOf = ({ name, version }) => `${name}@${version}`
const digest = (bytes) => createHash("sha256").update(bytes).digest("hex")

function nonEmptyString(value, label) {
  if (typeof value !== "string" || value.length === 0) {
    throw new Error(`Inventario pnpm inválido (${label})`)
  }
  return value
}

export function normalizePnpmLicenses(raw) {
  if (raw == null || typeof raw !== "object" || Array.isArray(raw) || raw.error) {
    throw new Error(`Inventario pnpm inválido: ${JSON.stringify(raw?.error ?? raw)}`)
  }
  const byKey = new Map()
  for (const [license, packages] of Object.entries(raw)) {
    nonEmptyString(license, "licencia")
    if (!Array.isArray(packages) || packages.length === 0) {
      throw new Error(`Inventario pnpm inválido (grupo ${license})`)
    }
    for (const [index, pkg] of packages.entries()) {
      if (pkg == null || typeof pkg !== "object" || Array.isArray(pkg)) {
        throw new Error(`Inventario pnpm inválido (${license}[${index}])`)
      }
      const name = nonEmptyString(pkg.name, `${license}[${index}].name`)
      if (!Array.isArray(pkg.versions) || !Array.isArray(pkg.paths)) {
        throw new Error(`Inventario pnpm inválido (${name}: versions/paths)`)
      }
      if (pkg.versions.length === 0 || pkg.versions.length !== pkg.paths.length) {
        throw new Error(`Inventario pnpm inválido (${name}: cardinalidad versions/paths)`)
      }
      if (pkg.license != null && pkg.license !== license) {
        throw new Error(`Inventario pnpm incoherente (${name}: ${pkg.license}/${license})`)
      }
      for (let position = 0; position < pkg.versions.length; position += 1) {
        const version = nonEmptyString(pkg.versions[position], `${name}.versions[${position}]`)
        nonEmptyString(pkg.paths[position], `${name}.paths[${position}]`)
        const entry = { name, version, license }
        const key = keyOf(entry)
        const previous = byKey.get(key)
        if (previous && previous.license !== license) {
          throw new Error(`Licencias contradictorias para ${key}`)
        }
        byKey.set(key, entry)
      }
    }
  }
  return [...byKey.values()].sort((a, b) => keyOf(a).localeCompare(keyOf(b)))
}

function validateAllowlist(allowlist, fullMap, prodKeys, provenanceKeys, lockText) {
  if (
    allowlist == null
    || typeof allowlist !== "object"
    || allowlist.schema_version !== 1
    || !Array.isArray(allowlist.entries)
  ) {
    throw new Error("Allowlist de licencias inválida")
  }
  const allowMap = new Map()
  for (const entry of allowlist.entries) {
    const key = keyOf(entry)
    if (
      !entry.name
      || !entry.version
      || entry.scope !== "build-only"
      || !entry.rationale
      || entry.license !== "MPL-2.0"
      || allowMap.has(key)
    ) {
      throw new Error(`Allowlist inválida: ${key}`)
    }
    if (!lockText.includes(`${entry.name}@${entry.version}:`)) {
      throw new Error(`Entrada allowlist ausente del lock: ${key}`)
    }
    const inventoryEntry = fullMap.get(key)
    if (inventoryEntry && inventoryEntry.license !== entry.license) {
      throw new Error(`Allowlist incoherente con inventario: ${key}`)
    }
    if (prodKeys.has(key)) throw new Error(`Build-only aparece en prod: ${key}`)
    if (provenanceKeys.has(key)) throw new Error(`Build-only aparece en procedencia: ${key}`)
    allowMap.set(key, entry)
  }
  return allowMap
}

function assertRedistributable(entry, allowMap, scope) {
  const key = keyOf(entry)
  if (FORBIDDEN.test(entry.license)) {
    throw new Error(`Copyleft prohibido en ${scope}: ${key} ${entry.license}`)
  }
  if (PERMISSIVE.has(entry.license)) return
  const exception = allowMap.get(key)
  if (!exception || exception.license !== entry.license || scope !== "full") {
    throw new Error(`Licencia fuera del conjunto cerrado en ${scope}: ${key} ${entry.license}`)
  }
}

export function reconcile({ full, prod, provenance, allowlist, lockText }) {
  const fullMap = new Map(full.map((entry) => [keyOf(entry), entry]))
  const prodMap = new Map(prod.map((entry) => [keyOf(entry), entry]))
  const provenanceMap = new Map(provenance.packages.map((entry) => [keyOf(entry), entry]))
  if (fullMap.size !== full.length || prodMap.size !== prod.length) {
    throw new Error("Inventario normalizado contiene duplicados")
  }
  for (const entry of prod) {
    const fullEntry = fullMap.get(keyOf(entry))
    if (!fullEntry || fullEntry.license !== entry.license) {
      throw new Error(`Cierre prod no es subconjunto coherente de full: ${keyOf(entry)}`)
    }
  }
  const allowMap = validateAllowlist(
    allowlist,
    fullMap,
    new Set(prodMap.keys()),
    new Set(provenanceMap.keys()),
    lockText,
  )
  for (const entry of full) assertRedistributable(entry, allowMap, "full")
  for (const entry of prod) assertRedistributable(entry, allowMap, "prod")
  for (const pkg of provenance.packages) {
    const fullEntry = fullMap.get(keyOf(pkg))
    if (!fullEntry) throw new Error(`Procedencia ausente del cierre full: ${keyOf(pkg)}`)
    if (fullEntry.license !== pkg.license) {
      throw new Error(`Licencia incoherente para ${keyOf(pkg)}: ${fullEntry.license}/${pkg.license}`)
    }
    assertRedistributable(pkg, allowMap, "procedencia")
  }
}

function verifyNotices(provenance) {
  const noticePath = path.join(STATIC, "THIRD_PARTY_NOTICES.frontend.txt")
  const actual = readFileSync(noticePath)
  const expected = Buffer.from(buildNotices(provenance.packages))
  if (!actual.equals(expected)) {
    throw new Error("THIRD_PARTY_NOTICES no coincide byte a byte con la procedencia")
  }
  if (digest(actual) !== provenance.notices_sha256) {
    throw new Error("Hash de THIRD_PARTY_NOTICES incoherente con el manifiesto")
  }
  const manifestEntry = provenance.outputs.find(
    (entry) => entry.path === "THIRD_PARTY_NOTICES.frontend.txt",
  )
  if (
    !manifestEntry
    || manifestEntry.size !== actual.length
    || manifestEntry.sha256 !== digest(actual)
  ) {
    throw new Error("THIRD_PARTY_NOTICES no está ligado al manifiesto final")
  }
  return actual
}

export function main() {
  const paths = {
    fullRaw: path.join(EVIDENCE, "frontend-licenses.full.raw.json"),
    prodRaw: path.join(EVIDENCE, "frontend-licenses.prod.raw.json"),
    provenance: path.join(EVIDENCE, "frontend-provenance.json"),
    allowlist: path.join(WEB, "frontend-build-license-allowlist.json"),
    lock: path.join(WEB, "pnpm-lock.yaml"),
  }
  for (const [name, file] of Object.entries(paths)) {
    if (!existsSync(file)) throw new Error(`Falta input ${name}: ${file}`)
  }
  realpathSync(STATIC)
  const fullRaw = readFileSync(paths.fullRaw)
  const prodRaw = readFileSync(paths.prodRaw)
  const provenanceRaw = readFileSync(paths.provenance)
  const full = normalizePnpmLicenses(JSON.parse(fullRaw))
  const prod = normalizePnpmLicenses(JSON.parse(prodRaw))
  const provenance = JSON.parse(provenanceRaw)
  const allowlist = JSON.parse(readFileSync(paths.allowlist, "utf8"))
  reconcile({ full, prod, provenance, allowlist, lockText: readFileSync(paths.lock, "utf8") })
  const notices = verifyNotices(provenance)
  mkdirSync(EVIDENCE, { recursive: true })
  writeFileSync(
    path.join(EVIDENCE, "frontend-licenses.full.json"),
    `${JSON.stringify(full, null, 2)}\n`,
  )
  writeFileSync(
    path.join(EVIDENCE, "frontend-licenses.prod.json"),
    `${JSON.stringify(prod, null, 2)}\n`,
  )
  writeFileSync(
    path.join(EVIDENCE, "frontend-license-reconciliation.json"),
    `${JSON.stringify({
      schema_version: 2,
      status: "ok",
      full_inventory_sha256: digest(fullRaw),
      prod_inventory_sha256: digest(prodRaw),
      provenance_sha256: digest(provenanceRaw),
      provenance_packages: provenance.packages.length,
      notices_sha256: digest(notices),
    }, null, 2)}\n`,
  )
  console.log(`Licencias frontend verificadas: ${provenance.packages.length} paquetes distribuidos.`)
}

if (import.meta.url === pathToFileURL(process.argv[1]).href) main()
