// No AI assistant inside the editor, in Cycls — Cycls has its own agent, and it edits
// this very design. Upstream src/app/ai/chat/use.ts (pinned in upstream.sha256) sets
// up the chat session, its history (IndexedDB) and the provider keys as soon as it's
// imported; this keeps only what the rest of the editor reads: the right panel's tab,
// which can never be 'ai'.
import { customRef, ref } from 'vue'

type PanelTab = 'design' | 'code' | 'ai'

let current: PanelTab = 'design'
const activeTab = customRef<PanelTab>((track, trigger) => ({
  get() {
    track()
    return current
  },
  set(value) {
    if (value === 'ai' || value === current) return
    current = value
    trigger()
  }
}))

export function useAIChat() {
  return { activeTab, isConfigured: ref(false) }
}
