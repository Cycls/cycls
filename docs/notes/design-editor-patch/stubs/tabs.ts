// One document per editor, in Cycls. The editor never opens a second tab: every path
// that would — File › New design, the command palette, the mobile menu, Mod+N / Mod+T
// where the browser lets them through — asks Cycls for a new design instead, which
// opens in its own Cycls tab. Closing the tab, opening a file or a storage document do
// nothing (Cycls opens and closes files). The first tab — the editor's one document —
// is upstream's, and so is everything else in src/app/tabs (pinned in upstream.sha256).
import * as upstream from '../../tabs/index'
import { requestNewDesign } from '../host'

export * from '../../tabs/index'

export function createTab(...args: Parameters<typeof upstream.createTab>): upstream.Tab {
  if (upstream.tabCount() === 0) return upstream.createTab(...args)
  requestNewDesign()
  return upstream.activeTab.value as upstream.Tab
}

export function createHomeTab(): upstream.Tab {
  return createTab()
}

export function showNewTab(): void {
  createTab()
}

export function createDocumentInCurrentTab(): upstream.Tab {
  return createTab()
}

export async function closeTab(_tabId: string): Promise<void> {}

export async function openFileInNewTab(..._args: unknown[]): Promise<void> {}

export async function openStorageDocumentInNewTab(..._args: unknown[]): Promise<void> {}

export function useTabsStore() {
  return {
    ...upstream.useTabsStore(),
    createTab,
    createHomeTab,
    createDocumentInCurrentTab,
    closeTab,
    openFileInNewTab,
    openStorageDocumentInNewTab
  }
}
