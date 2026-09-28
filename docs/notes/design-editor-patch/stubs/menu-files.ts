// No opening files from inside the editor, in Cycls: it edits one design from the
// Cycls workspace, and Cycls opens files (the canvas "+", the Files panel). What's
// left calling these — Mod+O, the desktop-only paths — does nothing. Replaces upstream
// src/app/shell/menu/files.ts (pinned in upstream.sha256), same exports.
export async function openBrowserFileFromURL(_url: URL, _init?: RequestInit): Promise<void> {}

export async function openDesignFileBatch<T>(_items: T[], ..._rest: unknown[]): Promise<void> {}

export async function readTauriDesignFile(path: string): Promise<File> {
  throw new Error(`Opening ${path} isn't available in Cycls`)
}

export async function chooseTauriOpenPaths(): Promise<string[]> {
  return []
}

export async function openFileFromPath(_path: string): Promise<void> {}

export async function activateTabForPath(_path: string): Promise<boolean> {
  return false
}

export async function openFileDialog(): Promise<void> {}

export async function importFileDialog(): Promise<void> {}
