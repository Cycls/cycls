<script setup lang="ts">
// The editor's app shell, in Cycls (replaces upstream src/App.vue, pinned in
// editor/patches/upstream.sha256). Kept: the editor, theme, motion, tooltips, toasts.
// Dropped, because Cycls does it or doesn't use it: the settings dialog, crash
// recovery and its dialog, the unsaved-changes prompts and the "Leave site?" guard
// (every change is saved to the workspace), the library publish and review dialogs,
// storage sync and the desktop updater.
import { useHead } from '@unhead/vue'
import { MotionConfig } from 'motion-v'
import { TooltipProvider } from 'reka-ui'
import { computed, onMounted } from 'vue'

import { provideEditor, useI18n } from '@open-pencil/vue'

import { useEditorStore } from '@/app/editor/active-store'
import { animationsEnabled } from '@/app/shell/motion'
import { useAppTheme } from '@/app/shell/theme'
import { toast } from '@/app/shell/ui'
import AppShell from '@/components/shell/AppShell.vue'
import AppToast from '@/components/shell/AppToast.vue'

const store = useEditorStore()
const { locale } = useI18n()

useHead({
  title: 'Cycls design',
  htmlAttrs: {
    lang: locale,
    'data-motion': computed(() => (animationsEnabled.value ? 'full' : 'off'))
  }
})

provideEditor(store)
useAppTheme()

onMounted(() => {
  toast.setupGlobalErrorHandler()
})
</script>

<template>
  <MotionConfig :reduced-motion="animationsEnabled ? 'never' : 'always'">
    <TooltipProvider :delay-duration="400">
      <AppShell>
        <RouterView />
      </AppShell>
      <AppToast />
    </TooltipProvider>
  </MotionConfig>
</template>
