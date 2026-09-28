// The Cycls app that iframes this editor, and the one document it is editing.
//
// One document per editor: the bridge loads it and binds it here, and every save,
// export, copy and agent command acts on the bound document, never on "the active
// tab" (docs/quirks.md #30). Everything that would make a second document asks Cycls
// instead, which opens it in its own Cycls tab. The stubs (save, export, tabs) and
// the bridge share this module.
//
// Protocol 2 (a current Cycls app) confirms every save with `written`; an older app
// (a `load` without `protocol`) never does, so for it posting the save is the save,
// and what it can't do (new design, copies, exports) says so in the editor.
import { encodeBase64 } from '@open-pencil/core/bytes'

import type { EditorStore } from '@/app/editor/session'
import { toast } from '@/app/shell/ui'

export type Bound = { store: EditorStore; doc: string; name: string }
export type ExportFile = { name: string; mime: string; bytes: Uint8Array }

let parent: Window | null = null
let protocol = 0
let bound: Bound | null = null
let nextId = 0
const pending = new Map<string, (ok: boolean) => void>()

export function connect(win: Window): void {
  parent = win
}

export function post(msg: Record<string, unknown>): void {
  parent?.postMessage({ source: 'cycls-editor', ...msg }, '*')
}

export function setHostProtocol(version: number): void {
  protocol = version
}

export function bind(next: Bound | null): void {
  // A save still waiting on the previous document's host can't land on this one.
  for (const settle of pending.values()) settle(false)
  pending.clear()
  bound = next
}

export function boundDocument(): Bound | null {
  return bound
}

export function isBound(state: unknown): boolean {
  return !!bound && bound.store.state === state
}

// The bound document's .fig to the host: `saved` out, `written` back. True once the
// host has it in the workspace (an older host: once it's posted).
export function writeDocument(data: Uint8Array): Promise<boolean> {
  if (!bound) return Promise.resolve(false)
  const id = `s${++nextId}`
  post({ type: 'saved', doc: bound.doc, id, name: bound.name, fig: encodeBase64(data) })
  if (protocol < 2) return Promise.resolve(true)
  return new Promise((resolve) => {
    const timer = window.setTimeout(() => {
      pending.delete(id)
      resolve(false)
    }, 30_000)
    pending.set(id, (ok) => {
      window.clearTimeout(timer)
      resolve(ok)
    })
  })
}

export function written(id: string, ok: boolean): void {
  pending.get(id)?.(ok)
  pending.delete(id)
}

function needsNewerHost(): boolean {
  if (protocol >= 2) return false
  toast.info('Update Cycls to do this from the editor.')
  return true
}

// The size of the design's first frame — what a new design starts as.
function firstFrameSize(): [number, number] | undefined {
  const store = bound?.store
  if (!store) return undefined
  const graph = store.graph as unknown as {
    getChildren(id: string): Array<{ type: string; width: number; height: number }>
  }
  const frame = graph.getChildren(store.state.currentPageId).find((n) => n.type === 'FRAME')
  return frame ? [Math.round(frame.width), Math.round(frame.height)] : undefined
}

export function requestNewDesign(): void {
  if (needsNewerHost()) return
  post({ type: 'newDesign', size: firstFrameSize() })
}

export function saveCopy(data: Uint8Array): void {
  if (!bound || needsNewerHost()) return
  post({ type: 'saveCopy', doc: bound.doc, name: bound.name, fig: encodeBase64(data) })
}

export function exportFiles(files: ExportFile[]): void {
  if (!bound || !files.length || needsNewerHost()) return
  post({
    type: 'export',
    doc: bound.doc,
    files: files.map((f) => ({ name: f.name, mime: f.mime, data: encodeBase64(f.bytes) }))
  })
}
