# Design feature — handoff / finish tomorrow

**Status: working end-to-end, validated live. Not yet committed or deployed.**

A working plan to (1) commit what's built, (2) give the render service + editor a durable
home, and (3) deploy. Everything below is self-contained — the editor patch files and build
recipe are embedded at the end so nothing is lost if the scratchpad is cleaned.

Flowchart of the whole thing (shareable): https://claude.ai/code/artifact/8fc91e53-dcef-436f-91df-fc9cc6e250fb

---

## 1. What the feature is

The agent **generates** designs (social posts + slide decks) and the human **edits** the same
design in a full Figma-like editor embedded in the chat canvas. Both halves meet at one shared
file — `designs/<name>.fig` — in the agent's workspace.

Three flows:

- **A · Generate** — agent → `Design` tool (`render`/`script`) → **cycls-design** render service
  (Bun + OpenPencil headless) → high-fidelity PNG + FIG → written to the workspace → canvas opens it.
- **B · Human edits** — canvas mounts `DesignEditorView` → embeds the OpenPencil editor in an
  own-origin iframe (`?embed=cycls`) → loads the `.fig` → hand-edits **auto-save back** to the workspace.
- **C · Agent drives it live (Option 1)** — `Design(edit, script)` returns instantly (no service
  call), emits a `design_command` UI event → FE relays it over `postMessage` → the editor bridge
  runs the Figma-plugin-API script on the **live** store → the design changes while the human
  watches → same auto-save persists it.

Validated on 2026-09-16 in the real Super UI (model `moonshotai/Kimi-K3`): rendered an Instagram
post, opened the `.fig` editor in the canvas, told the agent "make the background purple and the
button green" — the change appeared live and the log showed `PUT /files/designs/launch.fig 200`.

---

## 2. Communication channels (the exact hops)

| Hop | Channel |
|-----|---------|
| Browser → Agent | `POST /chat` |
| LLM → Design tool | in-process (`_exec_design`) |
| Design tool → render service | **HTTP** `DESIGN_URL` (+ optional `DESIGN_SECRET` bearer) |
| Tool result → FE | two-channel `{_model, _ui}`; `_ui` rides the chat stream |
| chat.tsx → DesignEditorView | window `CustomEvent("cycls:design-command")` |
| DesignEditorView ↔ editor iframe | `postMessage` (`target:"cycls-editor"` ↔ `source:"cycls-editor"`) |
| DesignEditorView ↔ workspace | `GET` / `PUT /files` (authed) |
| Editor bridge → live store | `runCommand` → `AsyncFunction(figma, …)` → `runMutationWithLayout` |

Key identifiers (grep anchors):
- Tool `edit` branch → `cycls/_agent/tools/__init__.py` → `_exec_design`, `action == "edit"`,
  returns `{_ui: {action:"design_command", path, script}}`.
- FE forward → `client/src/components/chat.tsx` → `ev.action === "design_command"` →
  `dispatchEvent("cycls:design-command")`.
- Relay + auto-save → `client/src/components/design-editor-view.tsx`.
- Editor bridge → `cycls-bridge.ts` (embedded in §7): `runCommand`, `saveBack`, auto-save poll.
- Config injection → `cycls/_agent/web/server.py` → `Config.public()` adds `design_editor_url`
  from env `DESIGN_EDITOR_URL`.

---

## 3. Current code state (as of handoff)

### SDK repo `E:\Cycls\cycls-sdk` — branch `feat/agent-design` — UNCOMMITTED

Modified:
```
client/src/components/canvas-utils.ts      # isDesignEditor(.fig), tint fig:#af52de, isRenderable
client/src/components/canvas.tsx           # route .fig → <DesignEditorView>, thread designEditorUrl
client/src/components/chat.tsx             # design_command UI-action handler; widen writeFile→BlobPart
client/src/hooks/use-chat.ts               # AppConfig.design_editor_url?: string
client/src/hooks/use-files.ts              # writeFile(path, data: BlobPart, silent)
cycls/_agent/tools/__init__.py             # Design tool: "edit" action + schema
cycls/_agent/web/server.py                 # Config.public() injects design_editor_url
cycls/_agent/web/themes/default/index.html # rebuilt theme (points at new hashed bundles)
```
Deleted (old theme bundles, replaced by rebuild):
```
cycls/_agent/web/themes/default/assets/docx-preview-DUCBFGm_.js
cycls/_agent/web/themes/default/assets/index-bGBJXmXY.js
```
Untracked (new):
```
client/src/components/design-editor-view.tsx                   # the embed component
cycls/_agent/web/themes/default/assets/docx-preview-6fTbUdgG.js # new theme bundle
cycls/_agent/web/themes/default/assets/index-oj7Bvsh-.js        # new theme bundle
docs/notes/design-editor-patch/                                 # durable editor-patch copies
docs/notes/design-editor-handoff.md                            # this file
```

> The theme `assets/*.js` are build outputs. Confirm `client/` sources are committed and the theme
> is a clean rebuild before committing, so the bundle hashes match the sources.

### Render service `E:\Cycls\cycls-design` — committed + pushed

Clean. Repo `github.com/Cycls/cycls-design`, one commit
`66e18bd feat: cycls-design — headless design service for Cycls agents`. Bun server wrapping the
OpenPencil headless CLI (`/render`, `/eval`, `/health`); Dockerfile `oven/bun:1`.

### Editor (patched OpenPencil fork) — NO repo yet

The editor is `open-pencil/open-pencil` + 3 small patches (embedded in §7, durable copies in
`docs/notes/design-editor-patch/`). The built SPA currently only lives in the scratchpad
(`op-build-out/dist-fix7`) and is served locally on `:8107`. **This is the main thing to make
durable tomorrow.**

---

## 4. What gets deployed (and what doesn't)

Only **two** new, **shared** services. Everything else ships in the `cycls` pip package.

| Deploy | What | Where | Notes |
|--------|------|-------|-------|
| **Render service** | cycls-design (Bun + OpenPencil headless) | own origin, e.g. `design.cycls.ai` | the only real cost driver (Skia/WASM CPU) |
| **Editor SPA** | patched OpenPencil static build | own origin, e.g. `design-editor.cycls.ai` | static files + WASM; CDN-cacheable |

Ships in pip / no separate deploy: the SDK connector (`cycls/_agent/design/`), the Design tool,
the FE (`DesignEditorView` etc., built into `cycls/_agent/web/themes/default`). The agent itself is
already deployed — the feature only adds env vars.

**Env vars to set on the agent deployment:**
- `DESIGN_URL` (+ optional `DESIGN_SECRET`) → gates the whole `Design` tool via `design.configured()`. Enables Flow A/C.
- `DESIGN_EDITOR_URL` → injected into `/config` as `design_editor_url`; gates the embedded editor. Enables Flow B/C.

**Consolidation option:** the Bun render server can also serve the static editor at a different
subdomain — collapsing both into **one box**. MVP = one box does render + editor; split the static
onto a CDN later if traffic grows.

---

## 5. Cost model (approximate — region/config dependent)

**Render service** (needs RAM for WASM heaps; ~2 vCPU / 2–4 GB):

| Model | Fixed/mo | Per render | Tradeoff |
|-------|---------:|-----------:|----------|
| Always-on box (DO droplet / GCE 2 vCPU/4 GB) | ~$24–48 | ~$0 | no cold starts, simplest |
| Cloud Run, scale-to-zero | ~$0 idle | sub-cent (~$0.0001–0.0002) | cold start (few sec) after idle |
| Cloud Run, min-instances=1 | ~$40–50 | ~$0 | serverless, always warm |

**Editor SPA** (static; CanvasKit WASM ~7 MB, cached after first load):
- Cloudflare Pages / Netlify / Vercel free tier → **~$0** at low–moderate traffic.
- Or GCS bucket + Cloud CDN → storage ~$0, egress ~$0.08–0.12/GB (minimal with caching).

**Per-action unit economics** (the good part — live-edit + hand-edit run in browser WASM):

| Action | Render service | LLM (agent turn) | Net |
|--------|:--------------:|:----------------:|-----|
| Generate | 1 call (~sub-cent) | ~$0.01–0.03 | LLM-dominated |
| Agent live-edit (C) | **0 calls** | ~$0.01–0.03 | **LLM only** |
| Human hand-edit (B) | 0 | 0 | ~free (`PUT /files`) |

**Recommended start:** one always-on box (~$25–50/mo, flat, shared across all agents/users)
serving both render + editor, plus normal per-turn LLM cost and negligible GCS storage.
The two numbers that move the total: always-on vs scale-to-zero, and render concurrency at peak.

---

## 6. TODO for tomorrow (ordered)

1. **Give the editor a durable home.**
   - [ ] Create repo `github.com/Cycls/cycls-design-editor` (fork of `open-pencil/open-pencil`
         pinned to the version the patches target).
   - [ ] Add the 3 patch files (§7) at their target paths (`src/main.ts`,
         `vite/aliases.ts` create-fn, `src/app/embed/cycls-bridge.ts`).
   - [ ] Add the `canUseWorker→false` export patch (§7 recipe) so `saveBack` uses
         `compressFigDataSync` (fixes the embedded save hang).
   - [ ] Commit the build recipe / Dockerfile so CI can produce the static `dist`.

2. **Deploy the two services.**
   - [ ] Render service: build `E:\Cycls\cycls-design` image, deploy to `design.cycls.ai`
         (pick always-on vs Cloud Run per §5). Set `DESIGN_SECRET` if used.
   - [ ] Editor: static-deploy the `dist` to `design-editor.cycls.ai` (own origin, required for the iframe).
   - [ ] Point the agent env at both: `DESIGN_URL`, `DESIGN_EDITOR_URL` (+ `DESIGN_SECRET`).
   - [ ] Smoke test: generate a design, open the `.fig`, hand-edit (auto-save), agent live-edit.

3. **Commit the SDK work** (branch `feat/agent-design`, **no coauthor** per repo rule).
   - [ ] Rebuild the client theme cleanly (`cd client && npm run build`) so bundle hashes match sources.
   - [ ] Stage the §3 files. Decide whether to keep `docs/notes/design-editor-*` in the repo or move out.
   - [ ] Run tests: `uv run pytest tests/agent/design_test.py -v` and `cd client && npm test`.
         Add/adjust a test for the `edit` action + `design_command` forward if not covered.
   - [ ] Commit + push; open PR.

4. **Docs.** Fold the `edit` action + editor embed into `docs/notes/design.md` and the tutorial.

5. **Later — Option 2 (multiplayer).** True co-editing via OpenPencil's built-in Yjs CRDT +
   WebRTC/Trystero, so agent and human share a live CRDT session instead of the command/auto-save
   round-trip. Bigger lift; not needed for the current UX.

### Open decisions to confirm
- Always-on box vs scale-to-zero for the render service (cold-start UX vs flat cost).
- One consolidated box (render + editor) vs two hosts.
- Whether `docs/notes/design-editor-handoff.md` + `design-editor-patch/` belong in the repo or a private notes location.

---

## 7. Appendix — editor build recipe + patch files

Durable copies of the three patch files live in `docs/notes/design-editor-patch/`.

### Build recipe (Linux container — Windows monorepo build fails on wasm paths)

```bash
# OUT = fresh empty dir for the static build (never reuse a dir a server holds open → rm EPERM)
# PATCH = folder holding aliases.ts, cycls-bridge.ts, main.ts
docker run --rm -v "$OUT:/out" -v "$PATCH:/patch" oven/bun:1 bash -lc '
  set -e
  git clone --depth 1 https://github.com/open-pencil/open-pencil /app
  cd /app
  cp /patch/main.ts        src/main.ts
  cp /patch/aliases.ts     vite/aliases.ts            # replaces createOpenPencilAliases
  mkdir -p src/app/embed
  cp /patch/cycls-bridge.ts src/app/embed/cycls-bridge.ts
  # Force synchronous fig compression in-page (the export web-worker hangs when embedded):
  sed -i "s/typeof Worker !== .undefined. \&\& IS_BROWSER/false/" \
    packages/core/src/io/formats/fig/export.ts
  bun install
  bun run build:packages
  bunx vite build
  cp -r dist/* /out/
'
# serve /out on its own origin; locally: python -m http.server 8107 --bind 127.0.0.1
```

Notes:
- Runs on **Bun**, not Node. OpenPencil 0.14.0 has an exports-map bug (`bun` conditions) — if you
  hit `Bun is not defined` / `Cannot find module '@open-pencil/mcp/discovery'`, strip the broken
  `bun` conditions (see `scripts/patch-bun-exports.js` in cycls-design for the same fix).
- The `.fig` codec renumbers node ids on save; resolve a real frame id from the saved fig via
  `find --type frame` if you need it (already handled in cycls-design's engine).

### `src/main.ts`
```ts
import { createHead } from '@unhead/vue/client'
import { createApp } from 'vue'

import { createRetainedScopePlugin } from '@open-pencil/vue'

import './app.css'
import { startCyclsEmbedBridge } from '@/app/embed/cycls-bridge'
import { preloadFonts } from '@/app/editor/fonts'
import { IS_TAURI } from '@/constants'

import App from './App.vue'
import router from './router'

preloadFonts()
const head = createHead()
createApp(App).use(router).use(head).use(createRetainedScopePlugin()).mount('#app')

startCyclsEmbedBridge()

if (!IS_TAURI) {
  void import('virtual:pwa-register').then(({ registerSW }) => {
    registerSW({ immediate: true })
    return undefined
  })
}
```

### `vite/aliases.ts` (the `createOpenPencilAliases` factory)
```ts
import { resolve } from 'node:path'

export function createOpenPencilAliases(rootDir: string) {
  const emptyNodeModule = resolve(rootDir, 'vite/empty-node-module.ts')

  return [
    { find: /^fs$/, replacement: emptyNodeModule },
    { find: /^path$/, replacement: emptyNodeModule },
    { find: '@', replacement: resolve(rootDir, 'src') },
    { find: '#vue', replacement: resolve(rootDir, 'packages/vue/src') },
    { find: '#core', replacement: resolve(rootDir, 'packages/core/src') },
    { find: '#dom-css', replacement: resolve(rootDir, 'packages/dom-css/src') },
    {
      find: /^@open-pencil\/dom-css\/browser$/,
      replacement: resolve(rootDir, 'packages/dom-css/src/browser.ts')
    },
    {
      find: /^@open-pencil\/dom-css\/jsx-runtime$/,
      replacement: resolve(rootDir, 'packages/dom-css/src/jsx/runtime.ts')
    },
    {
      find: /^@open-pencil\/dom-css\/jsx-dev-runtime$/,
      replacement: resolve(rootDir, 'packages/dom-css/src/jsx/dev-runtime.ts')
    },
    {
      find: /^@open-pencil\/dom-css$/,
      replacement: resolve(rootDir, 'packages/dom-css/src/index.ts')
    },
    {
      find: /^@open-pencil\/scene-graph$/,
      replacement: resolve(rootDir, 'packages/scene-graph/src/index.ts')
    },
    { find: '@open-pencil/scene-graph', replacement: resolve(rootDir, 'packages/scene-graph/src') },
    { find: /^@open-pencil\/pen$/, replacement: resolve(rootDir, 'packages/pen/src/index.ts') },
    { find: '@open-pencil/pen', replacement: resolve(rootDir, 'packages/pen/src') },
    { find: /^@open-pencil\/kiwi$/, replacement: resolve(rootDir, 'packages/kiwi/src/index.ts') },
    { find: '@open-pencil/kiwi', replacement: resolve(rootDir, 'packages/kiwi/src') },
    { find: /^@open-pencil\/fig$/, replacement: resolve(rootDir, 'packages/fig/src/index.ts') },
    { find: '@open-pencil/fig', replacement: resolve(rootDir, 'packages/fig/src') },
    {
      find: /^@open-pencil\/mcp\/discovery$/,
      replacement: resolve(rootDir, 'packages/mcp/src/transport/discovery.ts')
    },
    {
      find: /^@open-pencil\/mcp\/transport$/,
      replacement: resolve(rootDir, 'packages/mcp/src/transport/paths.ts')
    },
    {
      // Cycls fix: the app aliases discovery + transport to source but MISSED
      // tools, so vite non-deterministically externalizes @open-pencil/mcp/tools
      // (bare-specifier boot crash). Alias it to source so it always bundles.
      find: /^@open-pencil\/mcp\/tools$/,
      replacement: resolve(rootDir, 'packages/mcp/src/tool/index.ts')
    },
    { find: /^@open-pencil\/vue$/, replacement: resolve(rootDir, 'packages/vue/src/index.ts') },
    { find: '@open-pencil/vue', replacement: resolve(rootDir, 'packages/vue/src') },
    { find: /^@open-pencil\/core$/, replacement: resolve(rootDir, 'packages/core/src/index.ts') },
    { find: '@open-pencil/core', replacement: resolve(rootDir, 'packages/core/src') },
    {
      find: 'opentype.js',
      replacement: resolve(rootDir, 'node_modules/opentype.js/dist/opentype.mjs')
    }
  ]
}
```

### `src/app/embed/cycls-bridge.ts`
```ts
// Cycls embed bridge. When the OpenPencil editor runs inside the Cycls canvas as
// an iframe (URL `?embed=cycls`), it loads a `.fig` posted by the parent window
// and posts the edited `.fig` back — so the agent (which writes the `.fig` via the
// headless render service) and the human (who edits it here) share one document.
//
// Wire protocol (postMessage, JSON):
//   parent → editor : { target:'cycls-editor', type:'load', name, fig:<base64> }
//                     { target:'cycls-editor', type:'save' }
//                     { target:'cycls-editor', type:'command', script }
//   editor → parent : { source:'cycls-editor', type:'ready'|'loaded'|'saved'|'applied'|'error', ... }
import { encodeBase64, decodeBase64 } from '@open-pencil/core/bytes'
import { exportFigFile } from '@open-pencil/core/io/formats/fig'
import { wrapEvalCode } from '@open-pencil/core/tools'
import { releaseFigPopulationWorker } from '#core/kiwi/fig/population/client'
import { releaseOriginalFigArchive } from '#core/kiwi/fig/session/original-archive'

import { makeFigmaFromStore } from '@/app/automation/bridge/figma-factory'
import { ensureGraphFonts } from '@/app/editor/fonts'
import { getActiveStore, openFileInNewTab } from '@/app/tabs'

export function startCyclsEmbedBridge(): void {
  const params = new URLSearchParams(window.location.search)
  if (params.get('embed') !== 'cycls') return
  const parentWindow = window.parent
  if (!parentWindow || parentWindow === window) return

  let name = 'design.fig'
  let lastVersion = -1
  let saving = false

  const post = (msg: Record<string, unknown>): void => {
    parentWindow.postMessage({ source: 'cycls-editor', ...msg }, '*')
  }

  async function saveBack(): Promise<void> {
    if (saving) return
    const store = getActiveStore()
    if (!store) {
      post({ type: 'error', message: 'no active store' })
      return
    }
    saving = true
    console.log('[cycls] save: start page=', store.state?.currentPageId, 'renderer=', !!store.renderer)
    try {
      const renderer = store.renderer
      // exportFigFile first awaits the "original archive" — a fig-population /
      // session-worker request that never resolves for an embed-loaded UNEDITED
      // doc (the worker is gone). Release both so it re-encodes the current graph
      // (synchronously, via the canUseWorker=false patch) instead of hanging.
      try { releaseFigPopulationWorker(store.graph) } catch { /* ignore */ }
      try { releaseOriginalFigArchive(store.graph) } catch { /* ignore */ }
      const data = (await Promise.race([
        exportFigFile(store.graph, renderer?.ck, renderer ?? undefined, store.state.currentPageId),
        new Promise((_resolve, reject) =>
          window.setTimeout(() => reject(new Error('exportFigFile timeout (20s)')), 20000)
        )
      ])) as Uint8Array
      console.log('[cycls] save: exported', data.length, 'bytes')
      lastVersion = store.state.sceneVersion
      post({ type: 'saved', name, fig: encodeBase64(data) })
    } catch (error) {
      console.log('[cycls] save: error', error)
      post({ type: 'error', message: String((error as Error)?.message ?? error) })
    } finally {
      saving = false
    }
  }

  // Apply an agent "command" — a Figma-plugin-API script — to the LIVE editor
  // (mirrors the app's automation eval-handler), so the human watches the agent's
  // edits appear on the canvas they're using. Auto-save then persists them.
  async function runCommand(script: string): Promise<void> {
    const store = getActiveStore()
    if (!store) {
      post({ type: 'error', message: 'no active store' })
      return
    }
    try {
      const pageId = store.state.currentPageId
      const figma = makeFigmaFromStore(store, pageId)
      const AsyncFunction = Object.getPrototypeOf(async function () { /* noop */ }).constructor
      const fn = new AsyncFunction('figma', wrapEvalCode(script))
      await store.runMutationWithLayout(
        () => fn(figma),
        pageId,
        async () => {
          const page = store.graph.getNode(pageId)
          if (page) await ensureGraphFonts(store.graph, page.childIds, store.renderer)
        }
      )
      store.requestRender()
      post({ type: 'applied' }) // the scene changed → auto-save persists it
    } catch (error) {
      post({ type: 'error', message: String((error as Error)?.message ?? error) })
    }
  }

  window.addEventListener('message', (event: MessageEvent) => {
    if (event.source !== parentWindow) return
    const msg = event.data as { target?: string; type?: string; name?: string; fig?: string; script?: string }
    if (!msg || msg.target !== 'cycls-editor') return
    if (msg.type === 'command' && typeof msg.script === 'string') {
      void runCommand(msg.script)
    } else if (msg.type === 'load' && typeof msg.fig === 'string') {
      name = msg.name || 'design.fig'
      const fig = msg.fig
      void (async () => {
        try {
          await openFileInNewTab(new File([decodeBase64(fig)], name))
          lastVersion = getActiveStore()?.state.sceneVersion ?? -1
          post({ type: 'loaded', name })
        } catch (error) {
          post({ type: 'error', message: String((error as Error)?.message ?? error) })
        }
      })()
    } else if (msg.type === 'save') {
      void saveBack()
    }
  })

  // Auto-persist: watch the scene version and save the edited .fig back to the
  // parent shortly after the human stops editing (debounced), so the workspace
  // .fig stays current and the agent picks up the human's edits on its next turn.
  let saveTimer: number | undefined
  const scheduleSave = () => {
    if (saveTimer !== undefined) window.clearTimeout(saveTimer)
    saveTimer = window.setTimeout(() => { saveTimer = undefined; void saveBack() }, 1200)
  }
  window.setInterval(() => {
    const store = getActiveStore()
    if (store && lastVersion !== -1 && store.state.sceneVersion !== lastVersion) {
      lastVersion = store.state.sceneVersion   // mark seen so we don't re-trigger every tick
      scheduleSave()
    }
  }, 700)

  post({ type: 'ready' })
}
```
