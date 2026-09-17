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
  async function runCommand(script: string): Promise<void> {
    const store = getActiveStore()
    if (!store) {
      post({ type: 'error', message: 'no active store' })
      return
    }
    try {
      const pageId = store.state.currentPageId
      const figma = makeFigmaFromStore(store, pageId)
      const AsyncFunction = Object.getPrototypeOf(async function () {
        /* noop */
      }).constructor
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
