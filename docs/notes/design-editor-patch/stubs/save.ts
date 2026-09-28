// Save, in Cycls: the document goes to the Cycls workspace, never to the user's disk.
// Every save path in the editor — Mod+S, File › Save, the mobile menu, the bridge's
// auto-save — comes through `saveFigFile`; true means the workspace has it, and the
// store's own wrapper (document/io/source.ts) then marks the document saved. "Save a
// copy" (Mod+Shift+S, File › Save a copy…) hands the bytes to Cycls, which asks for a
// name and writes a new file beside this one; the document itself stays as it is.
// Replaces upstream src/app/document/io/save.ts (pinned in upstream.sha256).
import { releaseFigPopulationWorker } from '#core/kiwi/fig/population/client'
import { releaseOriginalFigArchive } from '#core/kiwi/fig/session/original-archive'

import { boundDocument, isBound, saveCopy, writeDocument } from '../host'

type SaveActionsOptions = {
  state: { sceneVersion: number }
  buildFigFile: () => Uint8Array | Promise<Uint8Array>
  setSavedVersion: (version: number) => void
  onWriteSuccess?: (version: number) => void | Promise<void>
  [key: string]: unknown
}

// exportFigFile first awaits the "original archive" — a fig-population / session-worker
// request that never resolves for a document opened from bytes — so release both and
// it re-encodes the graph (synchronously: the canUseWorker=false edit). And the .fig
// writer re-emits a loaded node's auto-layout fields as the file had them, so a stack's
// gap changed here would be lost (docs/quirks.md #28): write the nodes' own instead.
function prepareSave(): void {
  const graph = boundDocument()?.store.graph
  if (!graph) return
  try { releaseFigPopulationWorker(graph) } catch { /* not populated */ }
  try { releaseOriginalFigArchive(graph) } catch { /* no archive */ }
  const nodes = (graph as unknown as { nodes: Map<string, { source?: { fig?: { layout?: unknown } } }> }).nodes
  for (const node of nodes.values()) if (node.source?.fig?.layout) node.source.fig.layout = undefined
}

function withTimeout<T>(work: Promise<T>, ms: number, what: string): Promise<T> {
  return Promise.race([
    work,
    new Promise<T>((_resolve, reject) => window.setTimeout(() => reject(new Error(`${what} timed out`)), ms))
  ])
}

export function createSaveActions(options: SaveActionsOptions) {
  const { state, buildFigFile, setSavedVersion, onWriteSuccess } = options
  let queue: Promise<unknown> = Promise.resolve()

  // One save at a time; a save asked for mid-save runs after it, with what's there then.
  function serial<T>(work: () => Promise<T>): Promise<T> {
    const next = queue.then(work, work)
    queue = next.catch(() => undefined)
    return next
  }

  async function build(): Promise<Uint8Array> {
    prepareSave()
    return withTimeout(Promise.resolve(buildFigFile()), 20_000, 'Building the .fig')
  }

  async function writeFile(data: Uint8Array, version: number): Promise<boolean> {
    if (!isBound(state)) return false
    const ok = await writeDocument(data)
    if (ok) {
      setSavedVersion(version)
      await onWriteSuccess?.(version)
    }
    return ok
  }

  const saveFigFile = () =>
    serial(async () => {
      if (!isBound(state)) return false
      const version = state.sceneVersion
      return writeFile(await build(), version)
    })

  const saveFigFileAs = async () => {
    if (isBound(state)) saveCopy(await build())
    return false
  }

  return { saveFigFile, saveFigFileAs, writeFile }
}
