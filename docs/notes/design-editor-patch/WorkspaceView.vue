<script setup lang="ts">
// The editor workspace, in Cycls (replaces upstream src/views/WorkspaceView.vue,
// pinned in editor/patches/upstream.sha256): the one design Cycls opened and nothing
// around it. No tab bar or Home screen (one document per editor, host.ts), no
// banners about the browser, no local MCP/automation server, no collaboration
// session, no opening files from links or the desktop.
import { useEventListener } from '@vueuse/core'

import { useKeyboard } from '@/app/shell/keyboard/use'
import { activeTab, createTab } from '@/app/tabs'
import CommandPalette from '@/components/commands/CommandPalette.vue'
import EditorWorkspace from '@/components/editor/EditorWorkspace.vue'
import FontStatusBanner from '@/components/font-status/FontStatusBanner.vue'
import RenameSelectionDialog from '@/components/selection/RenameSelectionDialog.vue'

if (!activeTab.value) createTab()

useKeyboard()

useEventListener(
  document,
  'wheel',
  (event: WheelEvent) => {
    if (event.ctrlKey || event.metaKey) event.preventDefault()
  },
  { passive: false }
)
</script>

<template>
  <div data-test-id="editor-root" class="flex h-screen w-screen flex-col">
    <FontStatusBanner />
    <RenameSelectionDialog />
    <CommandPalette />
    <EditorWorkspace />
  </div>
</template>
