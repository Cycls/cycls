import { createHead } from '@unhead/vue/client'
import { createApp } from 'vue'

import { createRetainedScopePlugin } from '@open-pencil/vue'

import './app.css'
import cyclsTheme from './cycls-theme.css?raw'
import { startCyclsEmbedBridge } from '@/app/embed/cycls-bridge'
import { preloadFonts } from '@/app/editor/fonts'
import { IS_TAURI } from '@/constants'

import App from './App.vue'
import router from './router'

// Cycls design system: inject the theme override at the END of <head> (after
// app.css + component styles) so its CSS-variable redefinitions win regardless of
// load order — the editor chrome then reads Cycls colors/font. Runtime injection
// mirrors the proven approach; a static import wouldn't guarantee precedence.
function injectCyclsTheme(): void {
  if (typeof document === 'undefined' || document.getElementById('cycls-theme')) return
  const el = document.createElement('style')
  el.id = 'cycls-theme'
  el.textContent = cyclsTheme
  document.head.appendChild(el)
}

preloadFonts()
const head = createHead()
createApp(App).use(router).use(head).use(createRetainedScopePlugin()).mount('#app')
injectCyclsTheme()

startCyclsEmbedBridge()

if (!IS_TAURI) {
  void import('virtual:pwa-register').then(({ registerSW }) => {
    registerSW({ immediate: true })
    return undefined
  })
}
