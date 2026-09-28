// Cycls embed bridge. The OpenPencil editor runs inside the Cycls canvas as an
// iframe (URL `?embed=cycls`), editing ONE design from the Cycls workspace: Cycls
// posts the .fig in, and every change goes back to that same file — the agent (which
// writes the .fig through the render service) and the person (who edits it here)
// share one document. host.ts holds the binding; the save, export and tabs stubs
// route everything that would touch the user's disk or open a second document to
// Cycls instead.
//
// Protocol 2 (postMessage, JSON). Cycls → editor, {target:'cycls-editor', type, …}:
//   load    {protocol:2, doc, name, fig, brand?}  open this document (a second load
//                                                  replaces it); `doc` tags its saves
//   written {id, ok}         the workspace has save `id` (or couldn't write it)
//   save    {}               save now
//   flush   {id}             save anything unsaved, then → flushed {id, ok}
//   command {script, intent?} a live agent edit (Figma plugin API) on this document
//   theme   {theme}          'dark' | 'light'
//   brand   {brand}          the workspace brand kit: {colors:{primary,…}, fonts:{heading,body}}
// Editor → Cycls, {source:'cycls-editor', type, …}:
//   ready {protocol:2} · loaded {doc, name} · saved {doc, id, name, fig} · flushed {id, ok}
//   error {doc?, message} · applied {doc} · commandError {doc, message}
//   newDesign {size?} · saveCopy {doc, name, fig} · export {doc, files:[{name, mime, data}]}
// `commandError` is a live agent edit that failed HERE. The server applied and saved
// the same edit before sending it (Cycls checks every edit headlessly first), so Cycls
// re-opens the saved file rather than leave this editor on a stale document.
//
// An older Cycls app sends `load` without `protocol`: its saves count as done once
// posted, and it gets no new-design, copy or export messages (host.ts).
import { decodeBase64 } from '@open-pencil/core/bytes'
import { computeAllLayouts } from '@open-pencil/core/layout'
import { fontManager } from '@open-pencil/core/text'
import { wrapEvalCode } from '@open-pencil/core/tools'
// The same prelude the service runs ahead of every script (src/figma-compat.js), so
// a live edit and the server-side check behave the same.
import FIGMA_COMPAT from './figma-compat.js?raw'
import {
  bind,
  boundDocument,
  connect,
  post,
  setHostProtocol,
  written
} from './host'

import { makeFigmaFromStore } from '@/app/automation/bridge/figma-factory'
import { readFigDocument } from '@/app/document/io/fig'
import { applyImportedDocument } from '@/app/document/io/imported-document'
import { ensureGraphFonts } from '@/app/editor/fonts'
import type { EditorStore } from '@/app/editor/session'
import { getActiveStore } from '@/app/tabs'

// --- Cycls "second player": a labeled agent cursor + presence, so the human
// SEES the agent (Super) glide onto the canvas and make the edit — like a
// teammate in the file, not elements silently mutating. Pure DOM overlay inside
// the editor iframe; no dependency on the app's collab/awareness internals.
const AGENT = { name: 'Super', color: '#8b5cf6' }
let cursorEl: HTMLDivElement | null = null
let cursorHideTimer: number | undefined

function ensureCursor(): HTMLDivElement {
  if (cursorEl) return cursorEl
  const el = document.createElement('div')
  el.id = 'cycls-agent-cursor'
  el.style.cssText = [
    'position:fixed', 'left:0', 'top:0', 'z-index:2147483647', 'pointer-events:none', 'opacity:0',
    'transition:left .55s cubic-bezier(.22,.61,.36,1),top .55s cubic-bezier(.22,.61,.36,1),opacity .25s',
    'will-change:left,top,opacity'
  ].join(';')
  el.innerHTML =
    `<svg width="22" height="22" viewBox="0 0 24 24" style="display:block;filter:drop-shadow(0 1px 2px rgba(0,0,0,.4))">` +
    `<path d="M5 3l14 7-6 2-2 6z" fill="${AGENT.color}" stroke="#fff" stroke-width="1.3" stroke-linejoin="round"/></svg>` +
    `<div id="cycls-agent-label" style="position:absolute;left:15px;top:16px;white-space:nowrap;` +
    `background:${AGENT.color};color:#fff;font:600 11px/1.45 ui-sans-serif,system-ui,sans-serif;` +
    `padding:2px 8px;border-radius:10px;box-shadow:0 1px 4px rgba(0,0,0,.4)">${AGENT.name}</div>`
  document.body.appendChild(el)
  cursorEl = el
  return el
}

// Aim at the center-ish of the largest <canvas> (the editor's drawing surface).
function canvasTarget(): { x: number; y: number } {
  let best: DOMRect | null = null
  for (const c of Array.from(document.querySelectorAll('canvas'))) {
    const r = c.getBoundingClientRect()
    if (r.width > 0 && (!best || r.width * r.height > best.width * best.height)) best = r
  }
  if (best) return { x: best.left + best.width / 2, y: best.top + best.height * 0.42 }
  return { x: window.innerWidth / 2, y: window.innerHeight / 2 }
}

function showAgent(intent?: string): void {
  const el = ensureCursor()
  const label = el.querySelector('#cycls-agent-label') as HTMLElement | null
  if (label) label.textContent = intent ? `${AGENT.name} · ${intent}` : AGENT.name
  if (cursorHideTimer) { window.clearTimeout(cursorHideTimer); cursorHideTimer = undefined }
  // If hidden, jump to a corner first (no transition) so the glide reads as "moving in".
  if (!el.style.opacity || el.style.opacity === '0') {
    el.style.transition = 'none'
    el.style.left = `${window.innerWidth - 64}px`
    el.style.top = `${window.innerHeight - 44}px`
    void el.offsetWidth // reflow so the next change animates
    el.style.transition =
      'left .55s cubic-bezier(.22,.61,.36,1),top .55s cubic-bezier(.22,.61,.36,1),opacity .25s'
  }
  const { x, y } = canvasTarget()
  el.style.opacity = '1'
  el.style.left = `${x}px`
  el.style.top = `${y}px`
}

function moveAgentTo(x: number, y: number): void {
  const el = ensureCursor()
  el.style.opacity = '1'
  el.style.left = `${x}px`
  el.style.top = `${y}px`
}

// Screen point (iframe-window coords — the cursor is position:fixed) of a node's
// center, via the LIVE camera in store.state: screen = scene*zoom + pan. This is
// the inverse of figma-factory's viewport.center calc, so it lands on the node.
function nodeScreenPoint(store: { state: { zoom: number; panX: number; panY: number } },
                         bb: { x: number; y: number; width: number; height: number }): { x: number; y: number } {
  const z = store.state.zoom || 1
  const x = (bb.x + bb.width / 2) * z + (store.state.panX || 0)
  const y = (bb.y + bb.height / 2) * z + (store.state.panY || 0)
  return {
    x: Math.max(24, Math.min(window.innerWidth - 24, x)),
    y: Math.max(24, Math.min(window.innerHeight - 24, y))
  }
}

function pulseAgent(): void {
  const svg = cursorEl?.querySelector('svg') as SVGElement | undefined
  svg?.animate?.([{ transform: 'scale(1)' }, { transform: 'scale(.7)' }, { transform: 'scale(1)' }],
    { duration: 260, easing: 'ease-out' })
}

function idleAgent(delay = 1600): void {
  if (cursorHideTimer) window.clearTimeout(cursorHideTimer)
  cursorHideTimer = window.setTimeout(() => { if (cursorEl) cursorEl.style.opacity = '0' }, delay)
}

const wait = (ms: number): Promise<void> => new Promise((r) => window.setTimeout(r, ms))

// The editor's web fonts come from the render service's /font — one complete file
// per face, the very file the export renders with. In a browser the editor would
// otherwise fetch Fontsource subset files and register them under one family name,
// and an Arabic web font (Cairo, Tajawal…) drew blank in the editor while the export
// was right. Every remote load goes through here (a document's fonts, the agent's
// live edits, a font picked in the UI, the brand kit's faces); a face the service
// lacks falls back to the stock loader.
function useServiceFonts(): void {
  const fm = fontManager as unknown as {
    loadRemoteFont(family: string, style?: string, characters?: string, signal?: AbortSignal): Promise<ArrayBuffer | null>
    markLoaded(family: string, style: string, data: ArrayBuffer, source?: string): void
    loadedData(family: string, style: string): ArrayBuffer | null
  }
  const stock = fm.loadRemoteFont.bind(fm)
  const tried = new Set<string>()
  fm.loadRemoteFont = async (family: string, style = 'Regular', characters = '', signal?: AbortSignal) => {
    const key = `${family}|${style}`
    if (!tried.has(key)) {
      tried.add(key)
      try {
        const res = await fetch(`/font?family=${encodeURIComponent(family)}&style=${encodeURIComponent(style)}`, { signal })
        if (res.ok) {
          const buffer = await res.arrayBuffer()
          if (buffer.byteLength > 1024) {
            // A recorded source (the service resolves Google Fonts first) keeps the
            // editor's font-status check from flagging the face as substituted.
            fm.markLoaded(family, style, buffer, 'google')
            return fm.loadedData(family, style)
          }
        }
      } catch {
        if (signal?.aborted) throw signal.reason
        /* fall through to the stock loader */
      }
    }
    return stock(family, style, characters, signal)
  }
}

// Open a .fig in the editor's one document store, replacing what's there — the
// upstream open path (src/app/tabs readFigForTab + showImportedGraph), without the
// new tab it would open for a second file (docs/quirks.md #30).
async function loadDocument(store: EditorStore, bytes: Uint8Array, fileName: string): Promise<void> {
  store.state.documentName = fileName.replace(/\.[^.]+$/i, '')
  const load = store.preparationController.begin({ kind: 'document-open', subject: fileName })
  let loaded = false
  try {
    load.update({ phase: 'decoding', detail: fileName })
    const graph = await readFigDocument(new File([bytes], fileName), load.signal)
    const firstPage = graph.getPages()[0]?.id
    if (firstPage) computeAllLayouts(graph, firstPage)
    load.update({ phase: 'materializing', detail: store.state.documentName })
    await applyImportedDocument(store, graph, load)
    load.signal.throwIfAborted()
    store.setDocumentSource(fileName, 'fig')
    const pageId = store.graph.getPages()[0]?.id ?? store.graph.rootId
    load.update({ phase: 'populating-page', detail: store.graph.getNode(pageId)?.name ?? null })
    await store.switchPage(pageId, { preparation: load })
    load.update({ phase: 'preparing-render', detail: store.state.documentName })
    await store.fitCurrentPageToViewport()
    loaded = true
  } catch (error) {
    if (!load.signal.aborted) {
      load.fail({
        code: 'decode-failed',
        message: error instanceof Error ? error.message : String(error),
        retryable: true
      })
    }
    throw error
  } finally {
    if (loaded) load.complete()
  }
}

// OpenPencil (0.15.1) commits a text edit, and undoes or redoes one, straight into
// the graph without laying out the text's auto-layout parents — a line typed longer
// in a stack ran over the line under it (docs/quirks.md #29). So each of those lays
// the text's parents out again, as the editor's own node updates do.
function reflowTextEdits(store: EditorStore): void {
  type Editor = {
    __cyclsReflow?: boolean
    state: { editingTextId?: string | null; currentPageId: string }
    graph: { getNode(id: string): unknown }
    runLayoutForNode(id: string): void
    requestRender(): void
    commitTextEdit?: () => void
    startTextEditing?: (id: string) => void
    undoAction?: () => unknown
    redoAction?: () => unknown
  }
  const s = store as unknown as Editor
  if (s.__cyclsReflow) return
  s.__cyclsReflow = true
  const relayout = (id: string | null | undefined) => {
    try {
      if (id && s.graph.getNode(id)) s.runLayoutForNode(id)
      s.requestRender()
    } catch (error) {
      // eslint-disable-next-line no-console
      console.log('[cycls] relayout failed', error)
    }
  }
  const commit = s.commitTextEdit?.bind(s)
  if (commit) {
    s.commitTextEdit = () => {
      const id = s.state.editingTextId
      commit()
      relayout(id)
    }
  }
  const start = s.startTextEditing?.bind(s)
  if (start) {
    s.startTextEditing = (id: string) => {
      const previous = s.state.editingTextId   // starting another commits this one
      start(id)
      if (previous && previous !== id) relayout(previous)
    }
  }
  for (const key of ['undoAction', 'redoAction'] as const) {
    const run = s[key]?.bind(s)
    if (run) {
      s[key] = () => {
        const result = run()
        relayout(s.state.currentPageId)   // whichever text it was: the page's layouts
        return result
      }
    }
  }
}

// --- Theme: Cycls's light/dark, live. The editor's theme is a useLocalStorage ref
// (src/app/shell/theme.ts), so a storage event switches it without a reload.
export function applyTheme(theme: string): void {
  if (theme !== 'dark' && theme !== 'light') return
  try {
    const oldValue = localStorage.getItem('open-pencil:theme')
    localStorage.setItem('open-pencil:theme', theme)
    window.dispatchEvent(new StorageEvent('storage', {
      key: 'open-pencil:theme', newValue: theme, oldValue, storageArea: localStorage, url: location.href
    }))
  } catch {
    /* no storage: the editor keeps the theme it booted with */
  }
  const store = boundDocument()?.store
  if (store) paintBackdrop(store, theme)
}

// The canvas backdrop follows the chrome (dark #0a0a0a / light #f3f4f6), whatever
// the document has stored.
function paintBackdrop(store: EditorStore, theme = document.documentElement.dataset.theme): void {
  const dark = (theme ?? 'dark') !== 'light'
  try {
    ;(store.state as { pageColor?: { r: number; g: number; b: number; a: number } }).pageColor =
      dark ? { r: 0.039, g: 0.039, b: 0.039, a: 1 } : { r: 0.953, g: 0.957, b: 0.965, a: 1 }
    store.requestRender()
  } catch { /* ignore */ }
}

// --- Brand kit: the workspace's brand/brand.yaml, as Cycls reads it. Its colours
// become variables in a "Brand" collection, so a person editing by hand picks the
// same colours the agent uses, and its fonts are loaded before they're picked.
// Idempotent: a variable is created when missing, and set only when brand.yaml
// changed since the last sync — so a value changed by hand stands until the brand
// itself changes. What was last synced rides in the design's first frame, as plugin
// data (`cycls.brand`): a .fig keeps neither a variable's description nor a page's
// plugin data (quirks #31); a frame's it does (slide notes ride the same way).
export type Brand = { colors?: Record<string, string>; fonts?: { heading?: string | null; body?: string | null } }

const BRAND_COLORS: Record<string, string> = {
  primary: 'Primary', secondary: 'Secondary', accent: 'Accent',
  background: 'Background', text: 'Text', neutral: 'Neutral'
}

function rgba(hex: string): { r: number; g: number; b: number; a: number } | null {
  const m = /^#([0-9a-f]{6})$/i.exec(hex.trim())
  if (!m) return null
  const n = parseInt(m[1], 16)
  return { r: ((n >> 16) & 255) / 255, g: ((n >> 8) & 255) / 255, b: (n & 255) / 255, a: 1 }
}

export function syncBrandVariables(store: EditorStore, brand: Brand | null | undefined): boolean {
  const colors = Object.entries(brand?.colors ?? {})
    .map(([key, hex]) => [key, BRAND_COLORS[key], String(hex).toLowerCase(), rgba(String(hex))] as const)
    .filter(([, name, , value]) => name && value)
  if (!colors.length) return false
  type Variable = { name: string; valuesByMode: Record<string, unknown> }
  type Collection = { id: string; name: string; defaultModeId: string }
  const graph = store.graph as unknown as {
    variableCollections: Map<string, Collection>
    createCollection(name: string): Collection
    createVariable(name: string, type: 'COLOR', collectionId: string, value: unknown): Variable
    getVariablesForCollection(id: string): Variable[]
  }
  type Holder = { type: string; getPluginData(key: string): string; setPluginData(key: string, value: string): void }
  const page = (makeFigmaFromStore(store, store.state.currentPageId) as unknown as {
    currentPage: Holder & { children: Holder[] }
  }).currentPage
  const holder = page.children.find((n) => n.type === 'FRAME') ?? page
  let synced: Record<string, string> = {}
  try { synced = JSON.parse(holder.getPluginData('cycls.brand') || '{}') } catch { /* none yet */ }

  let changed = false
  const why: string[] = []
  let collection = [...graph.variableCollections.values()].find((c) => c.name === 'Brand')
  if (!collection) {
    collection = graph.createCollection('Brand')
    changed = true
    why.push('collection')
  }
  const existing = graph.getVariablesForCollection(collection.id)
  const now: Record<string, string> = {}
  for (const [key, name, hex, value] of colors) {
    now[key] = hex
    const variable = existing.find((v) => v.name === name)
    if (!variable) {
      graph.createVariable(name, 'COLOR', collection.id, value)
      changed = true
      why.push(`+${name}`)
    } else if (synced[key] !== hex) {
      variable.valuesByMode[collection.defaultModeId] = value
      changed = true
      why.push(`${name}=${hex}`)
    }
  }
  if (changed || JSON.stringify(synced) !== JSON.stringify(now)) {
    holder.setPluginData('cycls.brand', JSON.stringify(now))
    changed = true
  }
  // eslint-disable-next-line no-console
  if (changed) console.log('[cycls] brand:', why.join(' ') || 'recorded', '| was', JSON.stringify(synced))
  return changed
}

// The brand's faces, loaded while the document settles (so the text they re-shape
// isn't taken for an edit); one already loaded isn't asked for again.
function loadBrandFonts(brand: Brand | null | undefined): void {
  const fm = fontManager as unknown as { loadedData(family: string, style: string): ArrayBuffer | null }
  const families = new Set([brand?.fonts?.heading, brand?.fonts?.body].filter((f): f is string => !!f))
  for (const family of families) {
    for (const style of ['Regular', 'Bold']) {
      if (!fm.loadedData(family, style)) void fontManager.loadFont(family, style).catch(() => null)
    }
  }
}

export function startCyclsEmbedBridge(): void {
  const params = new URLSearchParams(window.location.search)
  if (params.get('embed') !== 'cycls') return
  const parentWindow = window.parent
  if (!parentWindow || parentWindow === window) return
  connect(parentWindow)
  useServiceFonts()

  // A freshly loaded document keeps settling for a beat (fonts re-shape, the first
  // frame renders, layouts compute) before the person touches anything. Until then
  // nothing auto-saves; at the end, what the settling changed counts as saved — unless
  // the person already started editing, which saves.
  let settleUntil = 0
  let settled = false
  let touched = false
  let loading: Promise<void> = Promise.resolve()
  let pendingBrand: Brand | null = null
  for (const kind of ['pointerdown', 'keydown'] as const) {
    window.addEventListener(kind, () => { if (!settled) touched = true }, { capture: true })
  }

  let saveTimer: number | undefined
  const cancelScheduledSave = () => {
    if (saveTimer !== undefined) window.clearTimeout(saveTimer)
    saveTimer = undefined
  }
  async function saveNow(): Promise<boolean> {
    cancelScheduledSave()
    const store = boundDocument()?.store
    if (!store) return false
    try {
      return await store.saveFigFile()
    } catch (error) {
      post({ type: 'error', doc: boundDocument()?.doc, message: String((error as Error)?.message ?? error) })
      return false
    }
  }
  const scheduleSave = () => {
    cancelScheduledSave()
    saveTimer = window.setTimeout(() => {
      saveTimer = undefined
      const store = boundDocument()?.store
      if (store?.hasUnsavedChanges()) void saveNow()
    }, 1200)
  }

  function applyBrand(brand: Brand | null): void {
    const store = boundDocument()?.store
    if (!store || !brand) return
    loadBrandFonts(brand)
    try {
      if (syncBrandVariables(store, brand)) {
        store.requestRender()
        void saveNow()   // graph-level variable edits raise no change events: save them here
      }
    } catch (error) {
      // eslint-disable-next-line no-console
      console.log('[cycls] brand sync failed', error)
    }
  }

  async function open(msg: { protocol?: number; doc?: string; name?: string; fig: string; brand?: Brand }): Promise<void> {
    setHostProtocol(typeof msg.protocol === 'number' ? msg.protocol : 0)
    cancelScheduledSave()
    await loading   // one load at a time
    const store = getActiveStore()
    const name = msg.name || 'design.fig'
    const doc = typeof msg.doc === 'string' ? msg.doc : ''
    bind(null)
    settled = false
    touched = false
    pendingBrand = msg.brand ?? null
    loadBrandFonts(pendingBrand)
    await loadDocument(store, decodeBase64(msg.fig), name)
    bind({ store, doc, name })
    reflowTextEdits(store)
    // Fonts the document uses (and any fallback pack). A face that's slow to arrive
    // doesn't fail the load — the document is open and editable, and the late-fonts
    // refresh below re-shapes its text when the face lands.
    const page = store.graph.getNode(store.state.currentPageId)
    if (page) {
      try {
        await ensureGraphFonts(store.graph, page.childIds, store.renderer)
      } catch (error) {
        // eslint-disable-next-line no-console
        console.log('[cycls] load: fonts still arriving', error)
      }
    }
    paintBackdrop(store)
    settleUntil = performance.now() + 2500
    post({ type: 'loaded', doc, name })
  }

  // Apply an agent "command" — a Figma-plugin-API script — to the LIVE editor
  // (mirrors the app's automation eval-handler), so the person watches the agent's
  // edits appear on the canvas they're using. Auto-save then persists them.
  async function runCommand(script: string, intent?: string): Promise<void> {
    const bound = boundDocument()
    if (!bound) {
      post({ type: 'commandError', message: 'no document is open' })
      return
    }
    const { store, doc } = bound
    showAgent(intent) // Super glides onto the canvas before it acts
    try {
      const pageId = store.state.currentPageId
      const figma = makeFigmaFromStore(store, pageId)
      const AsyncFunction = Object.getPrototypeOf(async function () {
        /* noop */
      }).constructor
      const fn = new AsyncFunction('figma', wrapEvalCode(`${FIGMA_COMPAT}\nfigmaCompat(figma);\n${script}`))
      await wait(300) // let the cursor glide in before it acts
      await store.runMutationWithLayout(
        () => fn(figma),
        pageId,
        async () => {
          const page = store.graph.getNode(pageId)
          if (page) await ensureGraphFonts(store.graph, page.childIds, store.renderer)
        }
      )
      store.requestRender()
      // Land Super's cursor exactly on the node it just changed, then "click" it.
      try {
        const f = figma as unknown as {
          currentPage: { selection?: ReadonlyArray<{ absoluteBoundingBox?: { x: number; y: number; width: number; height: number } }> }
          getNodeById(id: string): { absoluteBoundingBox?: { x: number; y: number; width: number; height: number } } | null
        }
        let node = f.currentPage.selection?.[0] ?? null
        if (!node) {
          const id = [...((store.state as { selectedIds?: Iterable<string> }).selectedIds ?? [])][0]
          if (id != null) node = f.getNodeById(id)
        }
        const bb = node?.absoluteBoundingBox
        if (bb) {
          const p = nodeScreenPoint(store as unknown as { state: { zoom: number; panX: number; panY: number } }, bb)
          moveAgentTo(p.x, p.y)
          await wait(380)
        }
      } catch {
        /* no bounds → the cursor just stays at center */
      }
      pulseAgent()
      post({ type: 'applied', doc }) // the scene changed → auto-save persists it
    } catch (error) {
      post({ type: 'commandError', doc, message: String((error as Error)?.message ?? error) })
    } finally {
      idleAgent()
    }
  }

  async function flush(id: string): Promise<void> {
    cancelScheduledSave()
    await loading
    const store = boundDocument()?.store
    const ok = !store || !store.hasUnsavedChanges() ? true : await saveNow()
    post({ type: 'flushed', id, ok })
  }

  window.addEventListener('message', (event: MessageEvent) => {
    if (event.source !== parentWindow) return
    const msg = event.data as {
      target?: string; type?: string; protocol?: number; doc?: string; name?: string; fig?: string
      id?: string; ok?: boolean; script?: string; intent?: string; theme?: string; brand?: Brand
    }
    if (!msg || msg.target !== 'cycls-editor') return
    if (msg.type === 'load' && typeof msg.fig === 'string') {
      const fig = msg.fig
      loading = open({ ...msg, fig }).catch((error) => {
        post({ type: 'error', doc: msg.doc, message: String((error as Error)?.message ?? error) })
      })
    } else if (msg.type === 'written' && typeof msg.id === 'string') {
      written(msg.id, msg.ok === true)
    } else if (msg.type === 'save') {
      void saveNow()
    } else if (msg.type === 'flush' && typeof msg.id === 'string') {
      void flush(msg.id)
    } else if (msg.type === 'command' && typeof msg.script === 'string') {
      void runCommand(msg.script, typeof msg.intent === 'string' ? msg.intent : undefined)
    } else if (msg.type === 'theme' && typeof msg.theme === 'string') {
      applyTheme(msg.theme)
    } else if (msg.type === 'brand') {
      if (settled) applyBrand(msg.brand ?? null)
      else pendingBrand = msg.brand ?? null
    }
  })

  // Late fonts. A web-font subset (the Arabic letters of Cairo, a fallback pack)
  // can register AFTER a text node was first drawn. The renderer only re-shapes the
  // nodes it was tracking as waiting on a font, so an untracked one keeps its cached
  // picture — the glyphs it lacked stay blank (Arabic text raced: same doc, same
  // build, blank on one load in two). Whenever the font set changes, drop every
  // cached text picture so the next frame shapes with the fonts loaded now — the
  // same reset the renderer's own settleFontDemand applies to the nodes it tracked.
  // Plain property resets, not graph edits, so the document stays saved.
  let fontGeneration = fontManager.generation()
  window.setInterval(() => {
    const generation = fontManager.generation()
    if (generation === fontGeneration) return
    fontGeneration = generation
    const store = boundDocument()?.store
    const renderer = store?.renderer as unknown as {
      fontGeneration?: number
      textPictureGenerations?: Map<string, unknown>
      invalidateAllPictures?: () => void
    } | null
    if (!store || !renderer) return
    try {
      for (const node of store.graph.getAllNodes()) {
        if (node.type === 'TEXT') (node as { textPicture: Uint8Array | null }).textPicture = null
      }
      renderer.textPictureGenerations?.clear()
      renderer.fontGeneration = generation
      renderer.invalidateAllPictures?.()
      store.requestRender()
    } catch (error) {
      // eslint-disable-next-line no-console
      console.log('[cycls] font refresh failed', error)
    }
  }, 400)

  // Auto-save: once the document has settled, a change the person (or the agent)
  // makes is saved to the workspace 1.2 s after they stop. Only content changes make
  // it unsaved (store.hasUnsavedChanges — not repaints, not a late font); while it is,
  // each new frame restarts the wait.
  let seenVersion = -1
  window.setInterval(() => {
    const store = boundDocument()?.store
    if (!store) return
    if (!settled) {
      const warm = !!(store as { renderer?: { ck?: unknown } }).renderer?.ck
      if (!warm || performance.now() < settleUntil) return
      settled = true
      if (touched && store.hasUnsavedChanges()) void saveNow()
      else store.setDocumentSource(boundDocument()?.name ?? 'design.fig', 'fig')   // what settling changed is the file as saved
      if (pendingBrand) {
        const brand = pendingBrand
        pendingBrand = null
        applyBrand(brand)
      }
      return
    }
    if (!store.hasUnsavedChanges() || store.state.sceneVersion === seenVersion) return
    seenVersion = store.state.sceneVersion
    scheduleSave()
  }, 700)

  post({ type: 'ready', protocol: 2 })
}
