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

// Sync the editor's light/dark to the mode Cycls passes via ?theme=<dark|light>,
// BEFORE the app boots (theme.ts reads this localStorage key on first tick).
try {
  const t = new URLSearchParams(location.search).get('theme')
  if (t === 'dark' || t === 'light') {
    localStorage.setItem('open-pencil:theme', t)
    // OpenPencil's theme store is a module-level useLocalStorage that already read
    // this key at import time — a plain setItem won't update its ref. Nudge it with
    // a storage event so the mode actually applies before the app renders.
    window.dispatchEvent(new StorageEvent('storage', {
      key: 'open-pencil:theme', newValue: t, oldValue: 'dark', storageArea: localStorage, url: location.href,
    }))
  }
} catch {
  /* no location/localStorage */
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
