/** Genera el manifiesto exhaustivo de firmas de fixtures demo. */

import { createHash } from "node:crypto"
import { readdirSync, readFileSync, writeFileSync } from "node:fs"
import path from "node:path"
import { fileURLToPath } from "node:url"

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..")
const FIXTURES = path.join(ROOT, "web", "src", "fixtures", "demo")
const OUTPUT = path.join(ROOT, "scripts", "frontend_demo_fixture_signatures.json")
const WINDOW_SIZE = 96

const digest = (bytes) => createHash("sha256").update(bytes).digest("hex")

function walk(directory) {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const absolute = path.join(directory, entry.name)
    if (entry.isSymbolicLink()) throw new Error(`Symlink prohibido en fixtures: ${absolute}`)
    if (entry.isDirectory()) return walk(absolute)
    return entry.isFile() ? [absolute] : []
  })
}

function windows(bytes) {
  const length = Math.min(WINDOW_SIZE, bytes.length)
  const last = Math.max(0, bytes.length - length)
  const offsets = new Set([
    0,
    Math.floor(last / 4),
    Math.floor(last / 2),
    Math.floor((last * 3) / 4),
    last,
  ])
  return [...offsets].sort((a, b) => a - b).map((offset) => ({
    offset,
    length,
    base64: bytes.subarray(offset, offset + length).toString("base64"),
  }))
}

const files = Object.fromEntries(
  walk(FIXTURES)
    .sort()
    .map((absolute) => {
      const relative = path.relative(FIXTURES, absolute).replaceAll("\\", "/")
      const bytes = readFileSync(absolute)
      return [
        relative,
        {
          size: bytes.length,
          sha256: digest(bytes),
          windows: windows(bytes),
        },
      ]
    }),
)

writeFileSync(
  OUTPUT,
  `${JSON.stringify({
    schema_version: 2,
    sentinel: "NIKODYM_DEMO_FIXTURE_ONLY",
    files,
  }, null, 2)}\n`,
)
