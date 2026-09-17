// Cycls embed bridge. When the OpenPencil editor runs inside the Cycls canvas as
// an iframe (URL `?embed=cycls`), it loads a `.fig` posted by the parent window
// and posts the edited `.fig` back — so the agent (which writes the `.fig` via the
// headless render service) and the human (who edits it here) share one document.
//
// It reuses the app's own open + serialize paths, so it stays a thin adapter:
//   load  → openFileInNewTab(new File([bytes], name))
//   save  → exportFigFile(getActiveStore().graph)  → bytes
//
// Wire protocol (postMessage, JSON):
//   parent → editor : { target:'cycls-editor', type:'load', name, fig:<base64> }
//                     { target:'cycls-editor', type:'save' }
//   editor → parent : { source:'cycls-editor', type:'ready' | 'loaded' | 'saved' | 'error', ... }
import { encodeBase64, decodeBase64 } from '@open-pencil/core/bytes'
import { exportFigFile } from '@open-pencil/core/io/formats/fig'
import { wrapEvalCode } from '@open-pencil/core/tools'
import { releaseFigPopulationWorker } from '#core/kiwi/fig/population/client'
import { releaseOriginalFigArchive } from '#core/kiwi/fig/session/original-archive'

import { makeFigmaFromStore } from '@/app/automation/bridge/figma-factory'
import { ensureGraphFonts } from '@/app/editor/fonts'
import { getActiveStore, openFileInNewTab } from '@/app/tabs'

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
    // eslint-disable-next-line no-console
    console.log('[cycls] save: start page=', store.state?.currentPageId, 'renderer=', !!store.renderer)
    try {
      const renderer = store.renderer
      // exportFigFile first awaits the "original archive" — a fig-population /
      // session-worker request that never resolves for an embed-loaded UNEDITED
      // doc (the worker is gone). Release both so it re-encodes the current graph
      // (synchronously, via the canUseWorker=false patch) instead of hanging.
      try {
        releaseFigPopulationWorker(store.graph)
      } catch {
        /* ignore */
      }
      try {
        releaseOriginalFigArchive(store.graph)
      } catch {
        /* ignore */
      }
      // Timeout so a stalled export surfaces as an error instead of hanging silently.
      const data = (await Promise.race([
        exportFigFile(store.graph, renderer?.ck, renderer ?? undefined, store.state.currentPageId),
        new Promise((_resolve, reject) =>
          window.setTimeout(() => reject(new Error('exportFigFile timeout (20s)')), 20000)
        )
      ])) as Uint8Array
      // eslint-disable-next-line no-console
      console.log('[cycls] save: exported', data.length, 'bytes')
      lastVersion = store.state.sceneVersion
      post({ type: 'saved', name, fig: encodeBase64(data) })
    } catch (error) {
      // eslint-disable-next-line no-console
      console.log('[cycls] save: error', error)
      post({ type: 'error', message: String((error as Error)?.message ?? error) })
    } finally {
      saving = false
    }
  }

  // Apply an agent "command" — a Figma-plugin-API script — to the LIVE editor
  // (mirrors the app's automation eval-handler), so the human watches the agent's
  // edits appear on the canvas they're using. Auto-save then persists them.
  async function runCommand(script: string, intent?: string): Promise<void> {
    const store = getActiveStore()
    if (!store) {
      post({ type: 'error', message: 'no active store' })
      return
    }
    showAgent(intent) // Super glides onto the canvas before it acts
    try {
      const pageId = store.state.currentPageId
      const figma = makeFigmaFromStore(store, pageId)
      const AsyncFunction = Object.getPrototypeOf(async function () {
        /* noop */
      }).constructor
      const fn = new AsyncFunction('figma', wrapEvalCode(script))
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
      post({ type: 'applied' }) // the scene changed → auto-save persists it
    } catch (error) {
      post({ type: 'error', message: String((error as Error)?.message ?? error) })
    } finally {
      idleAgent()
    }
  }

  window.addEventListener('message', (event: MessageEvent) => {
    if (event.source !== parentWindow) return
    const msg = event.data as { target?: string; type?: string; name?: string; fig?: string; script?: string; intent?: string }
    if (!msg || msg.target !== 'cycls-editor') return
    if (msg.type === 'command' && typeof msg.script === 'string') {
      void runCommand(msg.script, typeof msg.intent === 'string' ? msg.intent : undefined)
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
