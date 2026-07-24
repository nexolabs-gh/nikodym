/** Gate del bundle normal: bytes finales, fixtures demo y requests externos. */

import { createHash } from "node:crypto"
import { existsSync, mkdirSync, readdirSync, readFileSync, statSync, writeFileSync } from "node:fs"
import { createRequire } from "node:module"
import path from "node:path"
import { fileURLToPath, pathToFileURL } from "node:url"

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..")
const REQUIRE_FROM_WEB = createRequire(path.join(ROOT, "web", "package.json"))
const ts = REQUIRE_FROM_WEB("typescript")
const {
  transform: transformCss,
  transformStyleAttribute,
} = REQUIRE_FROM_WEB("lightningcss")
const FIXTURES = path.join(ROOT, "web", "src", "fixtures", "demo")
const STATIC = path.join(ROOT, "src", "nikodym", "ui", "static")
const SIGNATURES = path.join(ROOT, "scripts", "frontend_demo_fixture_signatures.json")
const EVIDENCE = path.join(ROOT, "web", "dist", "evidence")
const PROVENANCE = path.join(EVIDENCE, "frontend-provenance.json")
const REPORT = path.join(EVIDENCE, "frontend-bundle-check.json")
const FIXTURE_SENTINEL = "NIKODYM_DEMO_FIXTURE_ONLY"
const FIXTURE_WINDOW_SIZE = 96

export const digest = (bytes) => createHash("sha256").update(bytes).digest("hex")

function walk(directory) {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const absolute = path.join(directory, entry.name)
    if (entry.isSymbolicLink()) throw new Error(`Symlink prohibido: ${absolute}`)
    if (entry.isDirectory()) return walk(absolute)
    return entry.isFile() ? [absolute] : []
  })
}

function fixtureEntry(name, value) {
  if (
    value == null
    || typeof value !== "object"
    || !Number.isSafeInteger(value.size)
    || value.size < 0
    || !/^[0-9a-f]{64}$/.test(value.sha256)
    || !Array.isArray(value.windows)
    || value.windows.length === 0
  ) {
    throw new Error(`Entrada estructurada inválida: ${name}`)
  }
  return value
}

function canonicalFixtureWindows(bytes) {
  const length = Math.min(FIXTURE_WINDOW_SIZE, bytes.length)
  const last = Math.max(0, bytes.length - length)
  const offsets = [...new Set([
    0,
    Math.floor(last / 4),
    Math.floor(last / 2),
    Math.floor((last * 3) / 4),
    last,
  ])].sort((left, right) => left - right)
  return offsets.map((offset) => ({
    offset,
    length,
    base64: bytes.subarray(offset, offset + length).toString("base64"),
  }))
}

export function validateFixtureManifest(manifest, fixtureDirectory = FIXTURES) {
  if (
    manifest?.schema_version !== 2
    || manifest?.sentinel !== FIXTURE_SENTINEL
    || manifest?.files == null
    || JSON.stringify(Object.keys(manifest).sort())
      !== JSON.stringify(["files", "schema_version", "sentinel"])
  ) {
    throw new Error("Manifest de fixtures inválido")
  }
  const actual = walk(fixtureDirectory)
    .map((file) => path.relative(fixtureDirectory, file).replaceAll("\\", "/"))
    .sort()
  const declared = Object.keys(manifest.files).sort()
  if (JSON.stringify(actual) !== JSON.stringify(declared)) {
    throw new Error(`Manifest de fixtures incompleto: actual=${actual} declarado=${declared}`)
  }
  for (const name of actual) {
    const bytes = readFileSync(path.join(fixtureDirectory, name))
    const entry = fixtureEntry(name, manifest.files[name])
    if (entry.size !== bytes.length || digest(bytes) !== entry.sha256) {
      throw new Error(`Firma completa de fixture desactualizada: ${name}`)
    }
    const canonicalWindows = canonicalFixtureWindows(bytes)
    if (JSON.stringify(entry.windows) !== JSON.stringify(canonicalWindows)) {
      throw new Error(`Ventanas no canónicas de fixture: ${name}`)
    }
  }
}

function canonicalJson(bytes) {
  try {
    return Buffer.from(JSON.stringify(JSON.parse(bytes.toString("utf8"))))
  } catch {
    return null
  }
}

export function assertNoFixtureMaterial(outputs, manifest, fixtureDirectory = FIXTURES) {
  const sentinel = Buffer.from(manifest.sentinel)
  for (const output of outputs) {
    const bytes = readFileSync(output)
    const outputText = bytes.toString("latin1")
    if (bytes.includes(sentinel)) {
      throw new Error(`Sentinel demo emitido en ${path.basename(output)}`)
    }
    for (const [name, rawEntry] of Object.entries(manifest.files)) {
      const entry = fixtureEntry(name, rawEntry)
      const fixture = readFileSync(path.join(fixtureDirectory, name))
      if (digest(bytes) === entry.sha256 || bytes.includes(fixture)) {
        throw new Error(`Fixture demo emitido completo: ${name}`)
      }
      if (outputText.includes(fixture.toString("base64"))) {
        throw new Error(`Fixture demo emitido como base64 completo: ${name}`)
      }
      for (const window of entry.windows) {
        const signature = Buffer.from(window.base64, "base64")
        if (bytes.includes(signature) || outputText.includes(window.base64)) {
          throw new Error(`Ventana de fixture demo emitida: ${name}@${window.offset}`)
        }
      }
      const canonical = canonicalJson(fixture)
      if (
        canonical
        && (bytes.includes(canonical) || outputText.includes(canonical.toString("base64")))
      ) {
        throw new Error(`JSON demo inline emitido: ${name}`)
      }
    }
  }
}

function decodeHtmlEntities(value) {
  for (const match of value.matchAll(/&#/g)) {
    if (!/^&#(?:x[0-9a-f]+|\d+);/i.test(value.slice(match.index))) {
      throw new Error(`Entidad HTML numérica ambigua: ${value}`)
    }
  }
  for (const match of value.matchAll(/&(?:colon|sol)/gi)) {
    if (!/^&(?:colon|sol);/i.test(value.slice(match.index))) {
      throw new Error(`Entidad HTML nominal ambigua: ${value}`)
    }
  }
  const decoded = value.replace(
    /&(?:#(?:(x)([0-9a-f]+)|(\d+))|(colon|sol|amp));/gi,
    (_whole, hex, hexValue, decimalValue, named) => {
      if (named) {
        const entity = named.toLowerCase()
        if (entity === "colon") return ":"
        if (entity === "sol") return "/"
        return "&"
      }
      const codePoint = Number.parseInt(hex ? hexValue : decimalValue, hex ? 16 : 10)
      if (!Number.isSafeInteger(codePoint)) throw new Error("Entidad HTML inválida")
      return String.fromCodePoint(codePoint)
    },
  )
  if (/&(?:#[^;\s]*|[a-z][a-z0-9]+);/i.test(decoded)) {
    throw new Error(`Entidad HTML nominal no soportada: ${value}`)
  }
  return decoded
}

function parseTag(rawTag) {
  let position = 0
  const skipSpace = () => {
    while (/\s/.test(rawTag[position] ?? "")) position += 1
  }
  skipSpace()
  const tagMatch = rawTag.slice(position).match(/^([a-z][\w:-]*)/i)
  if (!tagMatch) throw new Error(`Tag HTML ambiguo: <${rawTag}>`)
  const tag = tagMatch[1].toLowerCase()
  position += tagMatch[0].length
  const attributes = {}
  while (position < rawTag.length) {
    skipSpace()
    if (position >= rawTag.length) break
    if (rawTag[position] === "/") {
      // WHATWG HTML §13.2.5.40: si tras `/` no viene `>`, es parse error y se reconsume
      // en «before attribute name state», o sea los atributos siguientes SÍ se parsean.
      position += 1
      continue
    }
    const nameMatch = rawTag.slice(position).match(/^([^\s"'=<>`/]+)/)
    if (!nameMatch) throw new Error(`Atributo HTML ambiguo en <${tag}>`)
    const name = nameMatch[1].toLowerCase()
    if (Object.hasOwn(attributes, name)) {
      throw new Error(`Atributo HTML duplicado en <${tag}>: ${name}`)
    }
    position += nameMatch[0].length
    skipSpace()
    let value = ""
    if (rawTag[position] === "=") {
      position += 1
      skipSpace()
      const quote = rawTag[position]
      if (quote === '"' || quote === "'") {
        position += 1
        const end = rawTag.indexOf(quote, position)
        if (end < 0) throw new Error(`Atributo HTML sin cierre en <${tag}>`)
        value = rawTag.slice(position, end)
        position = end + 1
      } else {
        const valueMatch = rawTag.slice(position).match(/^[^\s"'=<>`]+/)
        if (!valueMatch) throw new Error(`Valor HTML ambiguo en <${tag}>`)
        value = valueMatch[0]
        position += valueMatch[0].length
      }
    }
    attributes[name] = decodeHtmlEntities(value)
  }
  return { tag, attributes }
}

function parseHtmlSecuritySurface(html) {
  const nodes = []
  const lower = html.toLowerCase()
  let position = 0
  while (position < html.length) {
    const start = html.indexOf("<", position)
    if (start < 0) break
    if (html.startsWith("<!--", start)) {
      const endComment = html.indexOf("-->", start + 4)
      if (endComment < 0) throw new Error("Comentario HTML sin cierre")
      position = endComment + 3
      continue
    }
    // WHATWG HTML §13.2.5.6 «tag open state»: sólo `<!` y `</` PEGADOS abren markup
    // declaration / end tag. `< !` o `< /` son parse error, el `<` se emite como texto
    // y el `>` que sigue pertenece al tag SIGUIENTE — saltarlo lo volvería invisible.
    if (/^<[!/]/.test(html.slice(start))) {
      const endSpecial = html.indexOf(">", start + 1)
      if (endSpecial < 0) throw new Error("Sintaxis HTML sin cierre")
      position = endSpecial + 1
      continue
    }
    let quote = null
    let end = start + 1
    for (; end < html.length; end += 1) {
      const character = html[end]
      if (quote) {
        if (character === quote) quote = null
      } else if (character === '"' || character === "'") {
        quote = character
      } else if (character === ">") {
        break
      }
    }
    if (end >= html.length || quote) throw new Error("Tag HTML ambiguo o sin cierre")
    const node = parseTag(html.slice(start + 1, end))
    node.content = ""
    position = end + 1
    if (node.tag === "script" || node.tag === "style") {
      const closing = `</${node.tag}>`
      const closeStart = lower.indexOf(closing, position)
      if (closeStart < 0) throw new Error(`<${node.tag}> inline sin cierre`)
      node.content = html.slice(position, closeStart)
      position = closeStart + closing.length
    }
    nodes.push(node)
  }
  return nodes
}

const ASCII_WHITESPACE = /[\t\n\f\r ]/

/**
 * «Shared declarative refresh steps» de WHATWG HTML §7.4.6 aplicadas al atributo
 * `content` de `<meta http-equiv=refresh>`. El separador entre el tiempo y la URL puede
 * ser `;`, `,` **o whitespace**, y el prefijo `url=` es opcional: `content="0 https://x"`
 * navega igual que `content="0;url=https://x"`.
 */
function metaRefreshTarget(content) {
  let position = 0
  const at = () => content[position]
  const skipSpace = () => {
    while (position < content.length && ASCII_WHITESPACE.test(at())) position += 1
  }
  const advanceIf = (pattern) => {
    if (position < content.length && pattern.test(at())) {
      position += 1
      return true
    }
    return false
  }
  skipSpace()
  const digitsStart = position
  while (position < content.length && /[0-9]/.test(at())) position += 1
  if (position === digitsStart && at() !== ".") return null
  while (position < content.length && /[0-9.]/.test(at())) position += 1
  if (position < content.length) {
    if (at() !== ";" && at() !== "," && !ASCII_WHITESPACE.test(at())) return null
    skipSpace()
    if (at() === ";" || at() === ",") position += 1
    skipSpace()
  }
  if (position >= content.length) return null
  const remainder = content.slice(position)
  let skipQuotes = true
  if (advanceIf(/[uU]/)) {
    skipQuotes = false
    if (advanceIf(/[rR]/) && advanceIf(/[lL]/)) {
      skipSpace()
      if (advanceIf(/=/)) {
        skipSpace()
        skipQuotes = true
      }
    }
  }
  if (!skipQuotes) return remainder
  const quote = at() === "'" || at() === '"' ? at() : ""
  if (quote !== "") position += 1
  const urlString = content.slice(position)
  if (quote === "") return urlString
  const end = urlString.indexOf(quote)
  return end >= 0 ? urlString.slice(0, end) : urlString
}

function isLoopbackHost(hostname) {
  const normalized = hostname.toLowerCase()
  return normalized === "localhost" || normalized === "127.0.0.1" || normalized === "[::1]"
}

const LOCAL_URL_BASE = new URL("http://nikodym.invalid/")

function isAutomaticExternal(rawUrl, { allowPassiveData = false } = {}) {
  const value = decodeHtmlEntities(rawUrl).trim()
  if (value === "" || value.startsWith("#")) return false
  let parsed
  try {
    parsed = new URL(value, LOCAL_URL_BASE)
  } catch {
    throw new Error(`URL automática ambigua: ${rawUrl}`)
  }
  if (parsed.protocol === "data:") return !allowPassiveData
  if (parsed.protocol === "blob:") return true
  if (parsed.origin === LOCAL_URL_BASE.origin) return false
  if (["http:", "https:", "ws:", "wss:"].includes(parsed.protocol)) {
    return !isLoopbackHost(parsed.hostname)
  }
  return true
}

function cssDependencies(css, filename, { styleAttribute = false } = {}) {
  const transformer = styleAttribute ? transformStyleAttribute : transformCss
  const result = transformer({
    filename,
    code: Buffer.from(css),
    analyzeDependencies: true,
    errorRecovery: false,
  })
  if (result.warnings.length > 0) {
    throw new Error(`CSS produjo warnings: ${result.warnings.map((warning) => warning.message)}`)
  }
  if (!Array.isArray(result.dependencies)) {
    throw new Error("LightningCSS no devolvió dependencias")
  }
  return result.dependencies.map((dependency) => {
    if (dependency.type !== "import" && dependency.type !== "url") {
      throw new Error(`Dependencia CSS desconocida: ${dependency.type}`)
    }
    return dependency
  })
}

function assertCssHasNoExternalRequests(css, filename, { styleAttribute = false } = {}) {
  const offenders = []
  for (const dependency of cssDependencies(css, filename, { styleAttribute })) {
    const allowPassiveData = dependency.type === "url"
    if (isAutomaticExternal(dependency.url, { allowPassiveData })) {
      offenders.push(`${dependency.type}:${dependency.url}`)
    }
  }
  if (offenders.length) throw new Error(`Requests CSS externos: ${offenders.join(", ")}`)
}

function assertSpeculationRulesAreLocal(content) {
  let rules
  try {
    rules = JSON.parse(content)
  } catch {
    throw new Error("speculationrules no contiene JSON válido")
  }
  const visit = (value) => {
    if (typeof value === "string") {
      if (isAutomaticExternal(value)) {
        throw new Error(`speculationrules referencia URL externa: ${value}`)
      }
      return
    }
    if (Array.isArray(value)) {
      value.forEach(visit)
      return
    }
    if (value && typeof value === "object") {
      Object.values(value).forEach(visit)
    }
  }
  visit(rules)
}

function unwrapExpression(node) {
  let current = node
  while (
    ts.isParenthesizedExpression(current)
    || ts.isAsExpression(current)
    || ts.isTypeAssertionExpression(current)
    || ts.isNonNullExpression(current)
    || ts.isSatisfiesExpression(current)
    || ts.isPartiallyEmittedExpression(current)
  ) {
    current = current.expression
  }
  if (ts.isBinaryExpression(current) && current.operatorToken.kind === ts.SyntaxKind.CommaToken) {
    return unwrapExpression(current.right)
  }
  return current
}

function createJavaScriptAnalysis(javascript, filename) {
  const compilerOptions = {
    allowJs: true,
    checkJs: false,
    noLib: true,
    noResolve: true,
    target: ts.ScriptTarget.ESNext,
    module: ts.ModuleKind.ESNext,
  }
  const normalizedFilename = path.resolve(filename)
  const host = ts.createCompilerHost(compilerOptions, true)
  host.fileExists = (candidate) => path.resolve(candidate) === normalizedFilename
  host.readFile = (candidate) => (
    path.resolve(candidate) === normalizedFilename ? javascript : undefined
  )
  host.getSourceFile = (candidate, languageVersion) => (
    path.resolve(candidate) === normalizedFilename
      ? ts.createSourceFile(candidate, javascript, languageVersion, true, ts.ScriptKind.JS)
      : undefined
  )
  const program = ts.createProgram([normalizedFilename], compilerOptions, host)
  const sourceFile = program.getSourceFile(normalizedFilename)
  if (!sourceFile) throw new Error(`TypeScript no pudo parsear ${filename}`)
  const diagnostics = program.getSyntacticDiagnostics(sourceFile)
  if (diagnostics.length > 0) {
    const rendered = diagnostics.map((diagnostic) =>
      ts.flattenDiagnosticMessageText(diagnostic.messageText, "\n")
    )
    throw new Error(`JavaScript sintácticamente inválido: ${rendered.join("; ")}`)
  }
  const checker = program.getTypeChecker()
  const bindings = new Map()
  const registerBindings = (node) => {
    if (
      ts.isVariableDeclaration(node)
      && ts.isIdentifier(node.name)
      && node.initializer
    ) {
      const symbol = checker.getSymbolAtLocation(node.name)
      if (symbol) {
        const declarations = bindings.get(symbol) ?? []
        declarations.push(node)
        bindings.set(symbol, declarations)
      }
    }
    ts.forEachChild(node, registerBindings)
  }
  registerBindings(sourceFile)
  const writes = new Map()
  const isAssignmentOperator = (kind) => (
    kind >= ts.SyntaxKind.FirstAssignment && kind <= ts.SyntaxKind.LastAssignment
  )
  const isWritten = (identifier) => {
    let current = identifier
    for (let parent = identifier.parent; parent && !ts.isStatement(parent); parent = parent.parent) {
      if (
        ts.isBinaryExpression(parent)
        && isAssignmentOperator(parent.operatorToken.kind)
        && parent.left.pos <= current.pos
        && current.end <= parent.left.end
      ) {
        return true
      }
      if (
        (ts.isPrefixUnaryExpression(parent) || ts.isPostfixUnaryExpression(parent))
        && (
          parent.operator === ts.SyntaxKind.PlusPlusToken
          || parent.operator === ts.SyntaxKind.MinusMinusToken
        )
      ) {
        return true
      }
      if (
        (ts.isForInStatement(parent) || ts.isForOfStatement(parent))
        && parent.initializer.pos <= current.pos
        && current.end <= parent.initializer.end
      ) {
        return true
      }
      current = parent
    }
    return false
  }
  const registerWrites = (node) => {
    if (ts.isIdentifier(node) && isWritten(node)) {
      const symbol = checker.getSymbolAtLocation(node)
      if (symbol) writes.set(symbol, (writes.get(symbol) ?? 0) + 1)
    }
    ts.forEachChild(node, registerWrites)
  }
  registerWrites(sourceFile)
  const localFunctions = new Map()
  const registerFunctions = (node) => {
    if (ts.isFunctionDeclaration(node) && node.name) {
      const symbol = checker.getSymbolAtLocation(node.name)
      if (symbol) localFunctions.set(symbol, node)
    }
    if (
      ts.isVariableDeclaration(node)
      && ts.isIdentifier(node.name)
      && node.initializer
      && (
        ts.isArrowFunction(node.initializer)
        || ts.isFunctionExpression(node.initializer)
      )
    ) {
      const symbol = checker.getSymbolAtLocation(node.name)
      if (symbol) localFunctions.set(symbol, node.initializer)
    }
    ts.forEachChild(node, registerFunctions)
  }
  registerFunctions(sourceFile)
  const stableInitializerForSymbol = (symbol) => {
    const declarations = symbol ? bindings.get(symbol) : undefined
    if (
      !symbol
      || symbol.declarations?.length !== 1
      || declarations?.length !== 1
      || (writes.get(symbol) ?? 0) !== 0
    ) {
      return null
    }
    return declarations[0].initializer
  }
  const stableInitializer = (identifier) =>
    stableInitializerForSymbol(checker.getSymbolAtLocation(identifier))
  const returnedFunctionCache = new Map()
  const resolveLocalFunctions = (node, seen = new Set()) => {
    const expression = unwrapExpression(node)
    if (ts.isArrowFunction(expression) || ts.isFunctionExpression(expression)) {
      return new Set([expression])
    }
    if (ts.isConditionalExpression(expression)) {
      return new Set([
        ...resolveLocalFunctions(expression.whenTrue, seen),
        ...resolveLocalFunctions(expression.whenFalse, seen),
      ])
    }
    if (
      ts.isBinaryExpression(expression)
      && [
        ts.SyntaxKind.BarBarToken,
        ts.SyntaxKind.AmpersandAmpersandToken,
        ts.SyntaxKind.QuestionQuestionToken,
      ].includes(expression.operatorToken.kind)
    ) {
      return new Set([
        ...resolveLocalFunctions(expression.left, seen),
        ...resolveLocalFunctions(expression.right, seen),
      ])
    }
    if (ts.isIdentifier(expression)) {
      const symbol = checker.getSymbolAtLocation(expression)
      if (!symbol || seen.has(symbol)) return new Set()
      const direct = localFunctions.get(symbol)
      if (direct) return new Set([direct])
      const initializer = stableInitializerForSymbol(symbol)
      if (!initializer) return new Set()
      const nextSeen = new Set(seen)
      nextSeen.add(symbol)
      return resolveLocalFunctions(initializer, nextSeen)
    }
    if (ts.isCallExpression(expression)) {
      const returned = new Set()
      for (const fn of resolveLocalFunctions(expression.expression, seen)) {
        for (const value of returnedFunctions(fn, seen)) returned.add(value)
      }
      return returned
    }
    return new Set()
  }
  const returnedFunctions = (fn, seen = new Set()) => {
    if (returnedFunctionCache.has(fn)) return returnedFunctionCache.get(fn)
    const returned = new Set()
    returnedFunctionCache.set(fn, returned)
    const expressions = []
    if (ts.isArrowFunction(fn) && !ts.isBlock(fn.body)) {
      expressions.push(fn.body)
    } else if (fn.body) {
      const collectReturns = (node) => {
        if (node !== fn.body && ts.isFunctionLike(node)) return
        if (ts.isReturnStatement(node) && node.expression) {
          expressions.push(node.expression)
          return
        }
        ts.forEachChild(node, collectReturns)
      }
      collectReturns(fn.body)
    }
    for (const expression of expressions) {
      for (const value of resolveLocalFunctions(expression, seen)) returned.add(value)
    }
    return returned
  }
  const parameterArguments = new Map()
  const knownCallableParameters = new Set()
  const registerParameters = (functions, arguments_) => {
    for (const fn of functions) {
      fn.parameters.forEach((parameter, position) => {
        if (!ts.isIdentifier(parameter.name) || !arguments_[position]) return
        const symbol = checker.getSymbolAtLocation(parameter.name)
        if (!symbol) return
        const values = parameterArguments.get(symbol) ?? []
        values.push(arguments_[position])
        parameterArguments.set(symbol, values)
      })
    }
  }
  const registerCallArguments = (node) => {
    if (ts.isCallExpression(node)) {
      registerParameters(
        resolveLocalFunctions(node.expression),
        [...node.arguments],
      )
    }
    if (
      ts.isNewExpression(node)
      && ts.isIdentifier(unwrapExpression(node.expression))
      && unwrapExpression(node.expression).text === "Promise"
      && checker.getSymbolAtLocation(unwrapExpression(node.expression)) == null
      && node.arguments?.[0]
    ) {
      for (const executor of resolveLocalFunctions(node.arguments[0])) {
        for (const parameter of executor.parameters.slice(0, 2)) {
          if (!ts.isIdentifier(parameter.name)) continue
          const symbol = checker.getSymbolAtLocation(parameter.name)
          if (symbol) knownCallableParameters.add(symbol)
        }
      }
    }
    ts.forEachChild(node, registerCallArguments)
  }
  registerCallArguments(sourceFile)
  return {
    sourceFile,
    checker,
    writes,
    stableInitializer,
    stableInitializerForSymbol,
    parameterArguments,
    knownCallableParameters,
  }
}

function memberAccess(node, analysis, seen = new Set()) {
  const expression = unwrapExpression(node)
  if (ts.isPropertyAccessExpression(expression)) {
    return { object: expression.expression, name: expression.name.text }
  }
  if (ts.isElementAccessExpression(expression) && expression.argumentExpression) {
    const parts = evaluateStaticParts(expression.argumentExpression, analysis, seen)
    if (parts.every((part) => typeof part === "string")) {
      return { object: expression.expression, name: parts.join("") }
    }
  }
  return null
}

function isUnboundIdentifier(node, name, analysis) {
  const expression = unwrapExpression(node)
  const symbol = ts.isIdentifier(expression)
    ? analysis.checker.getSymbolAtLocation(expression)
    : null
  return (
    ts.isIdentifier(expression)
    && expression.text === name
    && (
      symbol == null
      || name === "globalThis" && (symbol.declarations?.length ?? 0) === 0
    )
  )
}

/** Identificadores libres que ya son el objeto global de un realm. */
const GLOBAL_OBJECT_IDENTIFIERS = new Set([
  "globalThis",
  "self",
  "window",
  "parent",
  "top",
  "frames",
])

/**
 * Miembros cuya lectura devuelve el objeto global de algún realm (el propio, el del
 * documento, el de un iframe o el de la ventana que abrió esta).
 */
const REALM_MEMBERS = new Set([
  "globalThis",
  "self",
  "window",
  "parent",
  "top",
  "frames",
  "opener",
  "defaultView",
  "contentWindow",
  "parentWindow",
])

/**
 * Un receptor es «ambiente» cuando ya es el objeto global o cuando es un identificador
 * libre del scope global (`document`, `frames`, …). Sólo sobre receptores ambiente se
 * promueve un REALM_MEMBER a objeto global: `top`, `parent`, `self` y `window` son
 * además nombres corrientes de geometría y de árboles de nodos en bundles reales, y
 * marcar `rect.top` como autoridad global rompería cualquier bundle honesto.
 */
function isAmbientReceiver(node, analysis, seen = new Set()) {
  if (isGlobalObject(node, analysis, seen)) return true
  const expression = unwrapExpression(node)
  if (!ts.isIdentifier(expression)) return false
  const symbol = analysis.checker.getSymbolAtLocation(expression)
  return symbol == null || (symbol.declarations?.length ?? 0) === 0
}

function isGlobalObject(node, analysis, seen = new Set()) {
  const expression = unwrapExpression(node)
  if (
    ts.isIdentifier(expression)
    && GLOBAL_OBJECT_IDENTIFIERS.has(expression.text)
    && isUnboundIdentifier(expression, expression.text, analysis)
  ) {
    return true
  }
  const member = memberAccess(expression, analysis, seen)
  if (
    member
    && REALM_MEMBERS.has(member.name)
    && isAmbientReceiver(member.object, analysis, seen)
  ) {
    return true
  }
  if (ts.isIdentifier(expression)) {
    const symbol = analysis.checker.getSymbolAtLocation(expression)
    if (symbol && !seen.has(symbol)) {
      const initializer = analysis.stableInitializer(expression)
      if (initializer) {
        const nextSeen = new Set(seen)
        nextSeen.add(symbol)
        return isGlobalObject(initializer, analysis, nextSeen)
      }
    }
  }
  return false
}

/**
 * Formas de declaración cuyo contenido el analizador sí sigue: o resuelven por
 * `stableInitializer`, o sólo pueden recibir autoridad por un camino ya vigilado
 * (argumento de llamada, asignación). Todo lo demás —`BindingElement` de un
 * destructuring, parámetro con default o con patrón, campo de clase, binding de
 * `catch`, import— es un enlace OPACO: el grafo de bindings no lo cubre y por lo tanto
 * no puede sostener la conclusión "este receptor es local".
 */
function isTrackedLocalDeclaration(declaration) {
  if (ts.isFunctionDeclaration(declaration) || ts.isClassDeclaration(declaration)) {
    return true
  }
  if (ts.isParameter(declaration)) {
    return ts.isIdentifier(declaration.name) && declaration.initializer == null
  }
  if (ts.isVariableDeclaration(declaration)) {
    return ts.isIdentifier(declaration.name) && !ts.isCatchClause(declaration.parent)
  }
  return false
}

/**
 * Clasifica el receptor de un acceso a miembro. Un receptor sólo es "local demostrable"
 * cuando la raíz de su cadena de accesos es un enlace declarado en este archivo: todo
 * identificador libre viene del scope global ambiente y por lo tanto es indeterminado.
 * Los sinks leídos sobre un receptor indeterminado fallan CERRADOS: se tratan como el
 * sink global homónimo y su URL se valida igual que `fetch(...)`.
 *
 * La autoridad global no puede entrar en un enlace local inmutable **de forma vigilada**
 * sin pasar por un argumento o una asignación, y esos caminos ya los cubren los chequeos
 * de escape; un enlace reasignado, en cambio, pudo recibirla después.
 *
 * `this` NO es local: en un script clásico `this === window`, así que `this.fetch(url)`
 * es exactamente `window.fetch(url)`.
 */
function isProvablyLocalReceiver(node, analysis, seen = new Set()) {
  const expression = unwrapExpression(node)
  if (isGlobalObject(expression, analysis)) return false
  const realmMember = memberAccess(expression, analysis, seen)
  if (realmMember && REALM_MEMBERS.has(realmMember.name)) return false
  if (
    ts.isObjectLiteralExpression(expression)
    || ts.isArrayLiteralExpression(expression)
    || ts.isArrowFunction(expression)
    || ts.isFunctionExpression(expression)
    || ts.isClassExpression(expression)
    || ts.isStringLiteral(expression)
    || ts.isNoSubstitutionTemplateLiteral(expression)
    || ts.isTemplateExpression(expression)
    || ts.isNumericLiteral(expression)
    || ts.isRegularExpressionLiteral(expression)
  ) {
    return true
  }
  if (ts.isIdentifier(expression)) {
    const symbol = analysis.checker.getSymbolAtLocation(expression)
    if (!symbol || (symbol.declarations?.length ?? 0) === 0 || seen.has(symbol)) return false
    if ((analysis.writes.get(symbol) ?? 0) > 0) return false
    if (!symbol.declarations.every(isTrackedLocalDeclaration)) return false
    const initializer = analysis.stableInitializer(expression)
    if (!initializer) return true
    const nextSeen = new Set(seen)
    nextSeen.add(symbol)
    return isProvablyLocalReceiver(initializer, analysis, nextSeen)
  }
  if (
    ts.isPropertyAccessExpression(expression)
    || ts.isElementAccessExpression(expression)
    || ts.isCallExpression(expression)
    || ts.isNewExpression(expression)
    || ts.isTaggedTemplateExpression(expression)
    || ts.isAwaitExpression(expression)
  ) {
    return isProvablyLocalReceiver(expression.expression, analysis, seen)
  }
  if (ts.isConditionalExpression(expression)) {
    return isProvablyLocalReceiver(expression.whenTrue, analysis, seen)
      && isProvablyLocalReceiver(expression.whenFalse, analysis, seen)
  }
  if (
    ts.isBinaryExpression(expression)
    && [
      ts.SyntaxKind.BarBarToken,
      ts.SyntaxKind.AmpersandAmpersandToken,
      ts.SyntaxKind.QuestionQuestionToken,
    ].includes(expression.operatorToken.kind)
  ) {
    return isProvablyLocalReceiver(expression.left, analysis, seen)
      && isProvablyLocalReceiver(expression.right, analysis, seen)
  }
  return false
}

function isGlobalNavigator(node, analysis, seen = new Set()) {
  if (isUnboundIdentifier(node, "navigator", analysis)) return true
  const member = memberAccess(node, analysis)
  if (member?.name === "navigator" && !isProvablyLocalReceiver(member.object, analysis)) return true
  const expression = unwrapExpression(node)
  if (ts.isIdentifier(expression)) {
    const symbol = analysis.checker.getSymbolAtLocation(expression)
    if (symbol && !seen.has(symbol)) {
      const initializer = analysis.stableInitializer(expression)
      if (initializer) {
        const nextSeen = new Set(seen)
        nextSeen.add(symbol)
        return isGlobalNavigator(initializer, analysis, nextSeen)
      }
    }
  }
  return false
}

/**
 * Receptor que ES el objeto global: uno probado, o el `this` de un script clásico.
 * Se exige esto —y no el «no demostrablemente local» general— para `open`, porque
 * `.open` es además una prop booleana ubicua de los componentes de UI (dialog, popover)
 * y tratar cualquier `x.open` como `window.open` rompería el bundle real.
 */
function isWindowLikeReceiver(node, analysis) {
  const expression = unwrapExpression(node)
  return expression.kind === ts.SyntaxKind.ThisKeyword
    || isGlobalObject(expression, analysis)
}

/** Resuelve un miembro fijo leído sobre el objeto global (`location`, `document`, …). */
function isGlobalMember(node, name, analysis, seen = new Set()) {
  if (isUnboundIdentifier(node, name, analysis)) return true
  const member = memberAccess(node, analysis)
  if (member?.name === name && isWindowLikeReceiver(member.object, analysis)) return true
  const expression = unwrapExpression(node)
  if (ts.isIdentifier(expression)) {
    const symbol = analysis.checker.getSymbolAtLocation(expression)
    if (symbol && !seen.has(symbol)) {
      const initializer = analysis.stableInitializer(expression)
      if (initializer) {
        const nextSeen = new Set(seen)
        nextSeen.add(symbol)
        return isGlobalMember(initializer, name, analysis, nextSeen)
      }
    }
  }
  return false
}

function isGlobalServiceWorker(node, analysis, seen = new Set()) {
  const member = memberAccess(node, analysis)
  if (member?.name === "serviceWorker" && isGlobalNavigator(member.object, analysis)) {
    return true
  }
  const expression = unwrapExpression(node)
  if (ts.isIdentifier(expression)) {
    const symbol = analysis.checker.getSymbolAtLocation(expression)
    if (symbol && !seen.has(symbol)) {
      const initializer = analysis.stableInitializer(expression)
      if (initializer) {
        const nextSeen = new Set(seen)
        nextSeen.add(symbol)
        return isGlobalServiceWorker(initializer, analysis, nextSeen)
      }
    }
  }
  return false
}

function isGlobalConstructor(node, name, analysis, seen = new Set()) {
  if (isUnboundIdentifier(node, name, analysis)) return true
  const member = memberAccess(node, analysis)
  if (member?.name === name && !isProvablyLocalReceiver(member.object, analysis)) return true
  const expression = unwrapExpression(node)
  if (ts.isIdentifier(expression)) {
    const symbol = analysis.checker.getSymbolAtLocation(expression)
    if (symbol && !seen.has(symbol)) {
      const initializer = analysis.stableInitializer(expression)
      if (initializer) {
        const nextSeen = new Set(seen)
        nextSeen.add(symbol)
        return isGlobalConstructor(initializer, name, analysis, nextSeen)
      }
    }
  }
  return false
}

function evaluateStaticParts(node, analysis, seen = new Set()) {
  const expression = unwrapExpression(node)
  if (ts.isStringLiteral(expression) || ts.isNoSubstitutionTemplateLiteral(expression)) {
    return [expression.text]
  }
  if (ts.isTemplateExpression(expression)) {
    const parts = [expression.head.text]
    for (const span of expression.templateSpans) {
      parts.push(...evaluateStaticParts(span.expression, analysis, seen))
      parts.push(span.literal.text)
    }
    return parts
  }
  if (
    ts.isBinaryExpression(expression)
    && expression.operatorToken.kind === ts.SyntaxKind.PlusToken
  ) {
    return [
      ...evaluateStaticParts(expression.left, analysis, seen),
      ...evaluateStaticParts(expression.right, analysis, seen),
    ]
  }
  if (ts.isIdentifier(expression)) {
    const symbol = analysis.checker.getSymbolAtLocation(expression)
    if (symbol && !seen.has(symbol)) {
      const initializer = analysis.stableInitializer(expression)
      if (initializer) {
        const nextSeen = new Set(seen)
        nextSeen.add(symbol)
        return evaluateStaticParts(initializer, analysis, nextSeen)
      }
    }
  }
  return [null]
}

function evaluateStaticString(node, analysis) {
  const parts = evaluateStaticParts(node, analysis)
  return parts.every((part) => typeof part === "string") ? parts.join("") : null
}

function dynamicPrefixClosesAuthority(prefix) {
  if (prefix.startsWith("/api/") || prefix.startsWith("./")) return true
  try {
    const parsed = new URL(prefix)
    return (
      ["http:", "https:", "ws:", "wss:"].includes(parsed.protocol)
      && isLoopbackHost(parsed.hostname)
      && prefix.startsWith(`${parsed.protocol}//${parsed.host}/`)
    )
  } catch {
    return false
  }
}

function assertUrlExpressionIsSafe(node, analysis, label) {
  if (!node) throw new Error(`${label}: sink sin argumento URL`)
  const parts = evaluateStaticParts(node, analysis)
  const dynamic = parts.some((part) => part == null)
  const prefix = parts.slice(0, parts.findIndex((part) => part == null)).join("")
  if (dynamic) {
    if (!dynamicPrefixClosesAuthority(prefix)) {
      throw new Error(
        `${label}: URL dinámica no demostrablemente local (prefijo=${JSON.stringify(prefix)})`,
      )
    }
    return
  }
  const value = parts.join("")
  if (isAutomaticExternal(value)) {
    throw new Error(`${label}: URL automática externa ${value}`)
  }
}

const CALLABLE_SINKS = new Map([
  ["fetch", { kind: "fetch", urlIndex: 0 }],
  ["importScripts", { kind: "importScripts", allUrlArguments: true }],
  ["WebSocket", { kind: "WebSocket", urlIndex: 0 }],
  ["EventSource", { kind: "EventSource", urlIndex: 0 }],
  ["Worker", { kind: "Worker", urlIndex: 0 }],
  ["SharedWorker", { kind: "SharedWorker", urlIndex: 0 }],
])

function resolveCallable(node, analysis, seen = new Set()) {
  const expression = unwrapExpression(node)
  if (ts.isConditionalExpression(expression)) {
    const whenTrue = resolveCallable(expression.whenTrue, analysis, seen)
    const whenFalse = resolveCallable(expression.whenFalse, analysis, seen)
    if (whenTrue && whenFalse && whenTrue.kind !== whenFalse.kind) {
      throw new Error("Alias condicional mezcla sinks globales distintos")
    }
    return whenTrue ?? whenFalse
  }
  if (
    ts.isBinaryExpression(expression)
    && [
      ts.SyntaxKind.BarBarToken,
      ts.SyntaxKind.AmpersandAmpersandToken,
      ts.SyntaxKind.QuestionQuestionToken,
    ].includes(expression.operatorToken.kind)
  ) {
    const left = resolveCallable(expression.left, analysis, seen)
    const right = resolveCallable(expression.right, analysis, seen)
    if (left && right && left.kind !== right.kind) {
      throw new Error("Alias lógico mezcla sinks globales distintos")
    }
    return left ?? right
  }
  if (ts.isIdentifier(expression)) {
    if (analysis.checker.getSymbolAtLocation(expression) == null) {
      const sink = CALLABLE_SINKS.get(expression.text)
      if (sink) return { ...sink, boundArguments: [] }
      // `open(...)` suelto es `window.open(...)`; sólo cuenta como identificador libre,
      // nunca como miembro genérico (`x.open` es prop booleana de UI en el bundle real).
      if (expression.text === "open") {
        return { kind: "window.open", urlIndex: 0, boundArguments: [] }
      }
    }
    const symbol = analysis.checker.getSymbolAtLocation(expression)
    if (symbol && !seen.has(symbol)) {
      const initializer = analysis.stableInitializer(expression)
      if (initializer) {
        const nextSeen = new Set(seen)
        nextSeen.add(symbol)
        return resolveCallable(initializer, analysis, nextSeen)
      }
    }
    return null
  }
  const member = memberAccess(expression, analysis, seen)
  if (member && !isProvablyLocalReceiver(member.object, analysis)) {
    const sink = CALLABLE_SINKS.get(member.name)
    if (sink) return { ...sink, boundArguments: [] }
    if (member.name === "sendBeacon") {
      return { kind: "navigator.sendBeacon", urlIndex: 0, boundArguments: [] }
    }
  }
  if (member) {
    // Navegación automática: sacan al usuario del origen local sin interacción.
    if (member.name === "open" && isWindowLikeReceiver(member.object, analysis)) {
      return { kind: "window.open", urlIndex: 0, boundArguments: [] }
    }
    if (
      (member.name === "assign" || member.name === "replace")
      && isGlobalMember(member.object, "location", analysis)
    ) {
      return { kind: `location.${member.name}`, urlIndex: 0, boundArguments: [] }
    }
    if (member.name === "register" && isGlobalServiceWorker(member.object, analysis)) {
      return { kind: "serviceWorker.register", urlIndex: 0, boundArguments: [] }
    }
    // Inyección de markup: el HTML resultante escapa por completo a este analizador,
    // así que no se valida — se prohíbe. Cero ocurrencias en el bundle real.
    if (
      (member.name === "write" || member.name === "writeln")
      && isGlobalMember(member.object, "document", analysis)
    ) {
      return { kind: `document.${member.name}`, forbidden: true, boundArguments: [] }
    }
    if (member.name === "insertAdjacentHTML") {
      return { kind: "insertAdjacentHTML", forbidden: true, boundArguments: [] }
    }
  }
  if (ts.isCallExpression(expression)) {
    const bindMember = memberAccess(expression.expression, analysis, seen)
    if (bindMember?.name === "bind") {
      const target = resolveCallable(bindMember.object, analysis, seen)
      if (target) {
        return {
          ...target,
          boundArguments: [...target.boundArguments, ...expression.arguments.slice(1)],
        }
      }
    }
  }
  return null
}

/**
 * Nombres inequívocos de navegación automática e inyección de markup. Se usan en la
 * guarda de destructuring; `assign`/`replace` quedan fuera a propósito porque son
 * nombres genéricos y allí se exigen sobre `location` probado.
 */
const MARKUP_AND_NAVIGATION_SINKS = new Set([
  "open",
  "write",
  "writeln",
  "insertAdjacentHTML",
  "register",
])

const DYNAMIC_EXECUTORS = new Set(["eval", "Function", "setTimeout", "setInterval"])

function resolveDynamicExecutor(node, analysis, seen = new Set()) {
  const expression = unwrapExpression(node)
  if (ts.isConditionalExpression(expression)) {
    const whenTrue = resolveDynamicExecutor(expression.whenTrue, analysis, seen)
    const whenFalse = resolveDynamicExecutor(expression.whenFalse, analysis, seen)
    if (whenTrue && whenFalse && whenTrue.kind !== whenFalse.kind) {
      throw new Error("Alias condicional mezcla ejecutores globales distintos")
    }
    return whenTrue ?? whenFalse
  }
  if (
    ts.isBinaryExpression(expression)
    && [
      ts.SyntaxKind.BarBarToken,
      ts.SyntaxKind.AmpersandAmpersandToken,
      ts.SyntaxKind.QuestionQuestionToken,
    ].includes(expression.operatorToken.kind)
  ) {
    const left = resolveDynamicExecutor(expression.left, analysis, seen)
    const right = resolveDynamicExecutor(expression.right, analysis, seen)
    if (left && right && left.kind !== right.kind) {
      throw new Error("Alias lógico mezcla ejecutores globales distintos")
    }
    return left ?? right
  }
  if (ts.isIdentifier(expression)) {
    if (
      DYNAMIC_EXECUTORS.has(expression.text)
      && isUnboundIdentifier(expression, expression.text, analysis)
    ) {
      return { kind: expression.text, boundArguments: [] }
    }
    const symbol = analysis.checker.getSymbolAtLocation(expression)
    if (symbol && !seen.has(symbol)) {
      const initializer = analysis.stableInitializer(expression)
      if (initializer) {
        const nextSeen = new Set(seen)
        nextSeen.add(symbol)
        return resolveDynamicExecutor(initializer, analysis, nextSeen)
      }
    }
    return null
  }
  const member = memberAccess(expression, analysis, seen)
  if (
    member
    && DYNAMIC_EXECUTORS.has(member.name)
    && !isProvablyLocalReceiver(member.object, analysis)
  ) {
    return { kind: member.name, boundArguments: [] }
  }
  if (ts.isCallExpression(expression)) {
    const bindMember = memberAccess(expression.expression, analysis, seen)
    if (bindMember?.name === "bind") {
      const target = resolveDynamicExecutor(bindMember.object, analysis, seen)
      if (target) {
        return {
          ...target,
          boundArguments: [...target.boundArguments, ...expression.arguments.slice(1)],
        }
      }
    }
  }
  return null
}

function isDefinitelyCallable(node, analysis, seen = new Set()) {
  const expression = unwrapExpression(node)
  if (ts.isArrowFunction(expression) || ts.isFunctionExpression(expression)) return true
  if (ts.isIdentifier(expression)) {
    const symbol = analysis.checker.getSymbolAtLocation(expression)
    if (!symbol || seen.has(symbol)) return false
    if (
      symbol.declarations?.length === 1
      && ts.isFunctionDeclaration(symbol.declarations[0])
    ) {
      return true
    }
    const initializer = analysis.stableInitializer(expression)
    if (initializer) {
      const nextSeen = new Set(seen)
      nextSeen.add(symbol)
      return isDefinitelyCallable(initializer, analysis, nextSeen)
    }
  }
  const member = ts.isCallExpression(expression)
    ? memberAccess(expression.expression, analysis, seen)
    : null
  return member?.name === "bind" && isDefinitelyCallable(member.object, analysis, seen)
}

function resolveXmlHttpRequest(node, analysis, seen = new Set()) {
  const expression = unwrapExpression(node)
  if (ts.isNewExpression(expression)) {
    return isGlobalConstructor(expression.expression, "XMLHttpRequest", analysis)
  }
  if (ts.isIdentifier(expression)) {
    const symbol = analysis.checker.getSymbolAtLocation(expression)
    if (symbol && !seen.has(symbol)) {
      const initializer = analysis.stableInitializer(expression)
      if (initializer) {
        const nextSeen = new Set(seen)
        nextSeen.add(symbol)
        return resolveXmlHttpRequest(initializer, analysis, nextSeen)
      }
    }
  }
  return false
}

function isSensitiveAuthority(node, analysis) {
  return Boolean(
    resolveCallable(node, analysis)
    || resolveDynamicExecutor(node, analysis)
    || isGlobalObject(node, analysis)
    || isGlobalNavigator(node, analysis)
    || isGlobalConstructor(node, "XMLHttpRequest", analysis)
    || resolveXmlHttpRequest(node, analysis),
  )
}

function isSensitiveShorthand(node, analysis) {
  const symbol = analysis.checker.getShorthandAssignmentValueSymbol(node)
  if (!symbol) {
    return (
      CALLABLE_SINKS.has(node.name.text)
      || DYNAMIC_EXECUTORS.has(node.name.text)
      || node.name.text === "navigator"
      || node.name.text === "XMLHttpRequest"
    )
  }
  const initializer = analysis.stableInitializerForSymbol(symbol)
  return initializer ? isSensitiveAuthority(initializer, analysis) : false
}

function arrayArguments(node) {
  const expression = unwrapExpression(node)
  return ts.isArrayLiteralExpression(expression) ? [...expression.elements] : null
}

function invocation(node, analysis) {
  const direct = resolveCallable(node.expression, analysis)
  if (direct) return { sink: direct, arguments: [...node.arguments] }
  const member = memberAccess(node.expression, analysis)
  if (
    member
    && isUnboundIdentifier(member.object, "Reflect", analysis)
    && (member.name === "apply" || member.name === "construct")
  ) {
    const target = node.arguments[0] ? resolveCallable(node.arguments[0], analysis) : null
    if (!target) return null
    const argumentList = node.arguments[member.name === "construct" ? 1 : 2]
    const applied = argumentList ? arrayArguments(argumentList) : null
    if (!applied) throw new Error(`Reflect.${member.name}: argumentos dinámicos`)
    return { sink: target, arguments: applied }
  }
  if (member?.name === "call" || member?.name === "apply") {
    const target = resolveCallable(member.object, analysis)
    if (!target) return null
    if (member.name === "call") {
      return { sink: target, arguments: [...node.arguments.slice(1)] }
    }
    const applied = node.arguments[1] ? arrayArguments(node.arguments[1]) : null
    if (!applied) throw new Error(`${target.kind}.apply: argumentos dinámicos`)
    return { sink: target, arguments: applied }
  }
  return null
}

function dynamicInvocation(node, analysis) {
  const direct = resolveDynamicExecutor(node.expression, analysis)
  if (direct) return { executor: direct, arguments: [...node.arguments] }
  const member = memberAccess(node.expression, analysis)
  if (
    member
    && isUnboundIdentifier(member.object, "Reflect", analysis)
    && (member.name === "apply" || member.name === "construct")
  ) {
    const target = node.arguments[0]
      ? resolveDynamicExecutor(node.arguments[0], analysis)
      : null
    if (!target) return null
    const argumentList = node.arguments[member.name === "construct" ? 1 : 2]
    const applied = argumentList ? arrayArguments(argumentList) : null
    if (!applied) throw new Error(`Reflect.${member.name}: argumentos dinámicos`)
    return { executor: target, arguments: applied }
  }
  if (member?.name === "call" || member?.name === "apply") {
    const target = resolveDynamicExecutor(member.object, analysis)
    if (!target) return null
    if (member.name === "call") {
      return { executor: target, arguments: [...node.arguments.slice(1)] }
    }
    const applied = node.arguments[1] ? arrayArguments(node.arguments[1]) : null
    if (!applied) throw new Error(`${target.kind}.apply: argumentos dinámicos`)
    return { executor: target, arguments: applied }
  }
  return null
}

/**
 * Ninguna autoridad global puede viajar como argumento, ni en `f(...)` ni en `new F(...)`:
 * pasarla a un callee opaco (envoltorio, `Proxy`, `Reflect`) escapa del análisis.
 */
function assertArgumentsKeepAuthority(argumentNodes, callee, analysis) {
  for (const [position, argument] of [...argumentNodes].entries()) {
    const calleeMember = memberAccess(callee, analysis)
    const reflectTarget = (
      calleeMember?.object
      && isUnboundIdentifier(calleeMember.object, "Reflect", analysis)
      && position === 0
    )
    if (reflectTarget) continue
    const escaped = resolveCallable(argument, analysis)
    if (escaped) {
      throw new Error(`Sink global escapa como argumento: ${escaped.kind}`)
    }
    const escapedDynamic = resolveDynamicExecutor(argument, analysis)
    if (escapedDynamic) {
      throw new Error(`Ejecutor global escapa como argumento: ${escapedDynamic.kind}`)
    }
    if (isSensitiveAuthority(argument, analysis)) {
      throw new Error("Autoridad global escapa como argumento")
    }
  }
}

function assertNoExternalRequestsInJavaScript(javascript, filename, depth = 0) {
  if (depth > 8) throw new Error("Ejecución dinámica excede profundidad verificable")
  const analysis = createJavaScriptAnalysis(javascript, filename)
  const checkInvocation = ({ sink, arguments: invocationArguments }) => {
    const allArguments = [...sink.boundArguments, ...invocationArguments]
    if (sink.forbidden) {
      throw new Error(`${sink.kind}: inyección de markup prohibida`)
    }
    if (sink.allUrlArguments) {
      if (allArguments.length === 0) {
        throw new Error(`${sink.kind}: sink sin argumento URL`)
      }
      allArguments.forEach((argument) =>
        assertUrlExpressionIsSafe(argument, analysis, sink.kind)
      )
    } else {
      assertUrlExpressionIsSafe(allArguments[sink.urlIndex], analysis, sink.kind)
    }
  }
  const checkDynamicExecution = (executor, invocationArguments) => {
    const allArguments = [...executor.boundArguments, ...invocationArguments]
    if (executor.kind === "Function") {
      const strings = allArguments.map((argument) =>
        evaluateStaticString(argument, analysis)
      )
      if (strings.some((value) => value == null)) {
        throw new Error("Function recibe parámetros/cuerpo dinámicos")
      }
      const body = strings.pop() ?? ""
      const parameters = strings.join(",")
      assertNoExternalRequestsInJavaScript(
        `function anonymous(${parameters}) {\n${body}\n}`,
        `${filename}.Function.js`,
        depth + 1,
      )
      return
    }
    const validateTimerCallback = (candidate, seen = new Set()) => {
      const code = evaluateStaticString(candidate, analysis)
      if (code != null) {
        assertNoExternalRequestsInJavaScript(
          code,
          `${filename}.${executor.kind}.parameter.js`,
          depth + 1,
        )
        return
      }
      if (isDefinitelyCallable(candidate, analysis)) return
      const callback = unwrapExpression(candidate)
      if (!ts.isIdentifier(callback)) {
        throw new Error(`${executor.kind} recibe callback dinámico no demostrable`)
      }
      const symbol = analysis.checker.getSymbolAtLocation(callback)
      if (!symbol || seen.has(symbol)) {
        throw new Error(`${executor.kind} recibe callback cíclico/no ligado`)
      }
      if (analysis.knownCallableParameters.has(symbol)) return
      const callArguments = analysis.parameterArguments.get(symbol) ?? []
      if (callArguments.length === 0) {
        throw new Error(
          `${executor.kind} recibe parámetro callback sin llamadas demostrables: `
          + `${callback.getText(analysis.sourceFile)}@${callback.pos}`,
        )
      }
      const nextSeen = new Set(seen)
      nextSeen.add(symbol)
      callArguments.forEach((argument) => validateTimerCallback(argument, nextSeen))
    }
    if (executor.kind === "setTimeout" || executor.kind === "setInterval") {
      if (!allArguments[0]) throw new Error(`${executor.kind} sin callback`)
      validateTimerCallback(allArguments[0])
      return
    }
    const code = evaluateStaticString(allArguments[0], analysis)
    if (code != null) {
      assertNoExternalRequestsInJavaScript(
        code,
        `${filename}.${executor.kind}.js`,
        depth + 1,
      )
      return
    }
    throw new Error(`${executor.kind} recibe código/callback dinámico no demostrable`)
  }
  const visit = (node) => {
    if (
      ts.isElementAccessExpression(node)
      && node.argumentExpression
      && (
        isGlobalObject(node.expression, analysis)
        || isGlobalNavigator(node.expression, analysis)
      )
      && evaluateStaticString(node.argumentExpression, analysis) == null
    ) {
      throw new Error("Acceso computado dinámico sobre autoridad global")
    }
    if (
      ts.isImportDeclaration(node)
      || ts.isExportDeclaration(node) && node.moduleSpecifier
    ) {
      assertUrlExpressionIsSafe(node.moduleSpecifier, analysis, "import/export")
    }
    if (ts.isCallExpression(node)) {
      const expression = unwrapExpression(node.expression)
      const dynamic = dynamicInvocation(node, analysis)
      if (dynamic) {
        checkDynamicExecution(dynamic.executor, dynamic.arguments)
      }
      const importMember = memberAccess(expression, analysis)
      if (
        expression.kind === ts.SyntaxKind.ImportKeyword
        || importMember?.object.kind === ts.SyntaxKind.ImportKeyword
        || ts.isMetaProperty(expression)
        && expression.keywordToken === ts.SyntaxKind.ImportKeyword
        && expression.name.text === "defer"
      ) {
        assertUrlExpressionIsSafe(node.arguments[0], analysis, "import()")
      } else {
        const resolved = invocation(node, analysis)
        if (resolved) checkInvocation(resolved)
        assertArgumentsKeepAuthority(node.arguments, expression, analysis)
        const openMember = memberAccess(expression, analysis)
        if (
          openMember?.name === "open"
          && resolveXmlHttpRequest(openMember.object, analysis)
        ) {
          assertUrlExpressionIsSafe(node.arguments[1], analysis, "XMLHttpRequest.open")
        }
      }
    }
    if (ts.isNewExpression(node)) {
      const sink = resolveCallable(node.expression, analysis)
      if (sink) checkInvocation({ sink, arguments: [...(node.arguments ?? [])] })
      const dynamicExecutor = resolveDynamicExecutor(node.expression, analysis)
      if (dynamicExecutor) {
        if (dynamicExecutor.kind !== "Function") {
          throw new Error(`new ${dynamicExecutor.kind} no es una ejecución válida`)
        }
        checkDynamicExecution(dynamicExecutor, [...(node.arguments ?? [])])
      }
      assertArgumentsKeepAuthority(
        node.arguments ?? [],
        unwrapExpression(node.expression),
        analysis,
      )
    }
    if (ts.isVariableDeclaration(node) && node.initializer) {
      if (ts.isIdentifier(node.name)) {
        const alias = resolveCallable(node.initializer, analysis)
        if (alias && analysis.stableInitializer(node.name) == null) {
          throw new Error(`Alias mutable/redeclarado de sink global: ${alias.kind}`)
        }
        const dynamicAlias = resolveDynamicExecutor(node.initializer, analysis)
        if (dynamicAlias && analysis.stableInitializer(node.name) == null) {
          throw new Error(
            `Alias mutable/redeclarado de ejecutor global: ${dynamicAlias.kind}`,
          )
        }
        if (
          (
            isGlobalObject(node.initializer, analysis)
            || isGlobalNavigator(node.initializer, analysis)
            || resolveXmlHttpRequest(node.initializer, analysis)
            || isGlobalConstructor(node.initializer, "XMLHttpRequest", analysis)
          )
          && analysis.stableInitializer(node.name) == null
        ) {
          throw new Error("Alias mutable/redeclarado de autoridad global")
        }
      } else if (ts.isObjectBindingPattern(node.name)) {
        // Fuente ambiente, no sólo objeto global probado: `const {defaultView}=document`
        // extrae autoridad de realm desde un identificador libre cualquiera.
        const globalObject = isAmbientReceiver(node.initializer, analysis)
        const globalNavigator = isGlobalNavigator(node.initializer, analysis)
        // `assign`/`replace` son nombres genéricos (`Object.assign`, `String#replace`),
        // así que sólo se vetan cuando la fuente es demostrablemente `location`.
        const globalLocation = isGlobalMember(node.initializer, "location", analysis)
        for (const element of node.name.elements) {
          const property = element.propertyName ?? element.name
          const propertyName = (
            ts.isIdentifier(property)
            || ts.isStringLiteral(property)
            || ts.isNumericLiteral(property)
          )
            ? property.text
            : evaluateStaticString(
              ts.isComputedPropertyName(property) ? property.expression : property,
              analysis,
            )
          if (
            globalObject
            && propertyName
            && (
              CALLABLE_SINKS.has(propertyName)
              || DYNAMIC_EXECUTORS.has(propertyName)
              || REALM_MEMBERS.has(propertyName)
              || MARKUP_AND_NAVIGATION_SINKS.has(propertyName)
              || propertyName === "navigator"
              || propertyName === "XMLHttpRequest"
            )
            || globalNavigator && propertyName === "sendBeacon"
            || globalNavigator && propertyName === "serviceWorker"
            || globalLocation
            && (propertyName === "assign" || propertyName === "replace")
          ) {
            throw new Error(`Destructuring de sink global prohibido: ${propertyName}`)
          }
        }
      }
    }
    if (
      ts.isArrowFunction(node)
      && !ts.isBlock(node.body)
      && isSensitiveAuthority(node.body, analysis)
    ) {
      throw new Error("Función retorna autoridad global sin invocación demostrable")
    }
    if (
      ts.isShorthandPropertyAssignment(node)
      && isSensitiveShorthand(node, analysis)
    ) {
      throw new Error(`Autoridad global almacenada en shorthand: ${node.name.text}`)
    }
    if (
      ts.isReturnStatement(node)
      && node.expression
      && isSensitiveAuthority(node.expression, analysis)
      || ts.isExportAssignment(node)
      && isSensitiveAuthority(node.expression, analysis)
      || ts.isPropertyAssignment(node)
      && isSensitiveAuthority(node.initializer, analysis)
      || ts.isPropertyDeclaration(node)
      && node.initializer
      && isSensitiveAuthority(node.initializer, analysis)
      || ts.isThrowStatement(node)
      && isSensitiveAuthority(node.expression, analysis)
      || ts.isArrayLiteralExpression(node)
      && node.elements.some((element) => isSensitiveAuthority(element, analysis))
      || ts.isBinaryExpression(node)
      && node.operatorToken.kind >= ts.SyntaxKind.FirstAssignment
      && node.operatorToken.kind <= ts.SyntaxKind.LastAssignment
      && isSensitiveAuthority(node.right, analysis)
    ) {
      throw new Error("Sink global escapa sin invocación demostrable")
    }
    ts.forEachChild(node, visit)
  }
  visit(analysis.sourceFile)
}

/**
 * Palabras que casan `/^on[a-z]+$/` sin ser handlers: no existe el evento `ce`, `ly`,
 * `line` ni `to`, así que ningún navegador las liga. Ojo con `ononline` (evento
 * `online` de window), que SÍ es handler y por eso no está aquí.
 */
const NON_HANDLER_ON_ATTRIBUTES = new Set(["once", "only", "online", "onto"])

export function assertNoAutomaticExternalRequests(indexHtml) {
  const urls = []
  let inlinePosition = 0
  for (const { tag, attributes, content } of parseHtmlSecuritySurface(indexHtml)) {
    inlinePosition += 1
    if (attributes.srcdoc) {
      throw new Error(`srcdoc no vacío prohibido en <${tag}>`)
    }
    // Un handler inline es JavaScript que corre solo, y además alcanza sinks de
    // navegación (`location=`) que el analizador de JS no cubre: se rechaza en seco.
    // El default es estructural (`on` + tipo de evento) para no quedar corto ante
    // handlers nuevos o con prefijo de vendor; las excepciones son palabras inglesas
    // que ningún navegador trata como handler porque no existe el evento homónimo.
    for (const name of Object.keys(attributes)) {
      if (/^on[a-z]+$/.test(name) && !NON_HANDLER_ON_ATTRIBUTES.has(name)) {
        throw new Error(`Handler inline prohibido en <${tag}>: ${name}`)
      }
    }
    if (attributes.src) urls.push(attributes.src)
    for (const attribute of ["srcset", "imagesrcset"]) {
      if (attributes[attribute]) {
        urls.push(
          ...attributes[attribute]
            .split(",")
            .map((candidate) => candidate.trim().split(/\s+/, 1)[0]),
        )
      }
    }
    if (tag === "object" && attributes.data) urls.push(attributes.data)
    if (attributes.poster) urls.push(attributes.poster)
    if (attributes.background) urls.push(attributes.background)
    if (tag === "base" && attributes.href) urls.push(attributes.href)
    if (!["a", "area", "link"].includes(tag) && attributes.href) urls.push(attributes.href)
    if (!["a", "area"].includes(tag) && attributes["xlink:href"]) {
      urls.push(attributes["xlink:href"])
    }
    if (tag === "link" && attributes.href) {
      const rel = new Set((attributes.rel ?? "").toLowerCase().split(/\s+/))
      const automatic = [
        "stylesheet",
        "icon",
        "preload",
        "modulepreload",
        "preconnect",
        "prefetch",
        "dns-prefetch",
        "manifest",
        "apple-touch-icon",
        "prerender",
      ]
      if (automatic.some((value) => rel.has(value))) urls.push(attributes.href)
    }
    if (
      tag === "meta"
      && attributes["http-equiv"]?.toLowerCase() === "refresh"
      && attributes.content
    ) {
      const refresh = attributes.content.match(/url\s*=\s*(.+)$/i)
      const separator = attributes.content.search(/[;,]/)
      const fallback = separator >= 0
        ? attributes.content.slice(separator + 1).trim()
        : ""
      // El algoritmo WHATWG es el objetivo real del navegador; las dos heurísticas
      // previas se conservan como candidatos extra para no aflojar nada ya cubierto.
      for (const target of [metaRefreshTarget(attributes.content), refresh?.[1], fallback]) {
        if (target) urls.push(target.replace(/^["']|["']$/g, ""))
      }
    }
    if (attributes.style) {
      assertCssHasNoExternalRequests(
        attributes.style,
        `inline-style-${inlinePosition}.css`,
        { styleAttribute: true },
      )
    }
    if (tag === "style") {
      assertCssHasNoExternalRequests(content, `inline-style-${inlinePosition}.css`)
    }
    if (tag === "script" && !attributes.src && content.trim()) {
      const type = (attributes.type ?? "").split(";", 1)[0].trim().toLowerCase()
      if (type === "speculationrules") {
        assertSpeculationRulesAreLocal(content)
      } else if (
        type === ""
        || type === "module"
        || [
          "application/javascript",
          "application/ecmascript",
          "text/javascript",
          "text/ecmascript",
        ].includes(type)
      ) {
        assertNoExternalRequestsInJavaScript(
          content,
          `inline-script-${inlinePosition}.js`,
        )
      }
    }
  }
  const offenders = urls.filter(isAutomaticExternal)
  if (offenders.length) {
    throw new Error(`Requests automáticos externos en HTML: ${offenders.join(", ")}`)
  }
}

export function assertNoExternalRequestsInOutputs(outputs) {
  const offenders = []
  for (const output of outputs) {
    const extension = path.extname(output).toLowerCase()
    const text = readFileSync(output, "utf8")
    try {
      if (extension === ".html" || extension === ".svg") {
        assertNoAutomaticExternalRequests(text)
      } else if (extension === ".css") {
        assertCssHasNoExternalRequests(text, output)
      } else if (extension === ".js" || extension === ".mjs") {
        assertNoExternalRequestsInJavaScript(text, output)
      }
    } catch (error) {
      offenders.push(`${path.basename(output)}: ${error.message}`)
    }
  }
  if (offenders.length) throw new Error(`Requests automáticos externos: ${offenders.join(", ")}`)
}

function assertUnambiguousSourceId(value) {
  if (/[\u0000-\u001f\u007f]/.test(value)) {
    throw new Error(`Source id contiene control/C0: ${JSON.stringify(value)}`)
  }
  let decoded = value
  for (let round = 0; round < 12; round += 1) {
    let next
    try {
      next = decodeURIComponent(decoded)
    } catch {
      throw new Error(`Source id contiene escape porcentual inválido: ${value}`)
    }
    if (next === decoded) {
      if (decoded !== value || decoded.includes("%")) {
        throw new Error(`Source id contiene codificación porcentual ambigua: ${value}`)
      }
      return
    }
    decoded = next
  }
  throw new Error(`Source id excede decodificación porcentual: ${value}`)
}

export function verifyFinalOutputs(outputs, provenance, staticDirectory = STATIC) {
  if (provenance?.schema_version !== 2 || !Array.isArray(provenance.outputs)) {
    throw new Error("Manifiesto de procedencia inválido")
  }
  const actual = new Map(outputs.map((absolute) => {
    const relative = path.relative(staticDirectory, absolute).replaceAll("\\", "/")
    const bytes = readFileSync(absolute)
    return [relative, { path: relative, size: bytes.length, sha256: digest(bytes) }]
  }))
  const declared = new Map()
  const foldedPaths = new Set()
  for (const entry of provenance.outputs) {
    if (
      entry == null
      || typeof entry !== "object"
      || typeof entry.path !== "string"
      || entry.path.length === 0
      || entry.path.startsWith("/")
      || entry.path.includes("\\")
      || entry.path.split("/").some((part) => part === "" || part === "." || part === "..")
      || !Number.isSafeInteger(entry.size)
      || entry.size < 0
      || !/^[0-9a-f]{64}$/.test(entry.sha256)
    ) {
      throw new Error("Output de procedencia inválido o no normalizado")
    }
    if (declared.has(entry.path) || foldedPaths.has(entry.path.toLowerCase())) {
      throw new Error(`Output duplicado/colisión en procedencia: ${entry.path}`)
    }
    if (!Array.isArray(entry.direct_source_ids) || entry.direct_source_ids.length === 0) {
      throw new Error(`Output sin direct_source_ids: ${entry.path}`)
    }
    const normalizedSources = entry.direct_source_ids.map((source) => {
      if (
        typeof source !== "string"
        || source.length === 0
        || source !== source.trim()
        || source.includes("\\")
        || source.includes("?")
        || source.includes("#")
        || source.startsWith("/")
        || path.win32.isAbsolute(source)
        || source.split("/").some((part) => part === "" || part === "." || part === "..")
      ) {
        throw new Error(`Source id no normalizado en ${entry.path}: ${String(source)}`)
      }
      assertUnambiguousSourceId(source)
      return source
    })
    if (
      new Set(normalizedSources).size !== normalizedSources.length
      || JSON.stringify(normalizedSources) !== JSON.stringify([...normalizedSources].sort())
    ) {
      throw new Error(`Source ids duplicados o no ordenados en ${entry.path}`)
    }
    declared.set(entry.path, entry)
    foldedPaths.add(entry.path.toLowerCase())
  }
  if (
    actual.size !== outputs.length
    || declared.size !== provenance.outputs.length
    || actual.size !== declared.size
    || [...actual.keys()].some((name) => !declared.has(name))
  ) {
    throw new Error("El manifiesto final no enumera exactamente los outputs en disco")
  }
  for (const [name, entry] of actual) {
    const expected = declared.get(name)
    if (expected.size !== entry.size || expected.sha256 !== entry.sha256) {
      throw new Error(`Output final incoherente con manifiesto: ${name}`)
    }
  }
}

/**
 * Ningún asset del bundle puede traer un backend absoluto embebido.
 *
 * `API_BASE` cayó durante todo B2.1 a `http://localhost:8000`, y ese literal viajó dentro del JS
 * distribuido sin que nada lo viera: este archivo analiza **atributos de HTML**, no cadenas dentro
 * del JS, así que el gate anti-request no lo cubría. Con el launcher sirviendo en 127.0.0.1:<puerto>
 * y el middleware exigiendo `Host` exacto, un origen absoluto embebido deja la UI instalada
 * navegando con toda la API muerta (enmienda B2.2, E-B2.2-9). La regla es barata y cierra la
 * regresión: el front habla same-origin, con rutas relativas.
 */
const EMBEDDED_ORIGIN = /https?:\/\/(?:localhost|127\.0\.0\.1|\[::1\])(?::\d+)?/gi

export function assertNoEmbeddedBackendOrigin(files, staticDirectory = STATIC) {
  const hallazgos = []
  for (const file of files) {
    if (!/\.(?:js|css)$/i.test(file)) continue
    const texto = readFileSync(file, "utf8")
    for (const match of texto.matchAll(EMBEDDED_ORIGIN)) {
      hallazgos.push(`${path.relative(staticDirectory, file)}: ${match[0]}`)
    }
  }
  if (hallazgos.length > 0) {
    throw new Error(
      `Origen absoluto embebido en el bundle (el front debe hablar same-origin):\n  - ${hallazgos.join("\n  - ")}`,
    )
  }
}

export function main() {
  if (!existsSync(path.join(STATIC, "index.html"))) {
    throw new Error("Falta src/nikodym/ui/static/index.html")
  }
  if (!existsSync(PROVENANCE)) throw new Error("Falta manifiesto de procedencia")
  const manifest = JSON.parse(readFileSync(SIGNATURES, "utf8"))
  const provenance = JSON.parse(readFileSync(PROVENANCE, "utf8"))
  validateFixtureManifest(manifest)
  const outputs = walk(STATIC).filter((file) => statSync(file).isFile())
  verifyFinalOutputs(outputs, provenance)
  assertNoFixtureMaterial(outputs, manifest)
  assertNoExternalRequestsInOutputs(outputs)
  assertNoEmbeddedBackendOrigin(outputs)
  const report = {
    schema_version: 2,
    files_checked: outputs.length,
    fixture_signatures_checked: Object.keys(manifest.files).length,
    provenance_sha256: digest(readFileSync(PROVENANCE)),
    status: "ok",
  }
  mkdirSync(path.dirname(REPORT), { recursive: true })
  writeFileSync(REPORT, `${JSON.stringify(report, null, 2)}\n`)
  console.log(`Bundle normal verificado: ${outputs.length} archivos, sin fixtures demo.`)
}

if (import.meta.url === pathToFileURL(process.argv[1]).href) main()
