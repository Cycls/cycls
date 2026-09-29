import { createHead } from '@unhead/vue/client'
import { createApp } from 'vue'

import { createRetainedScopePlugin, localeSetting } from '@open-pencil/vue'

import './app.css'
import cyclsTheme from './cycls-theme.css?raw'
import { applyTheme, startCyclsEmbedBridge } from '@/app/embed/cycls-bridge'
import { setRecoveryRuntimeOverride } from '@/app/document/recovery/preferences'
import { preloadFonts } from '@/app/editor/fonts'

import App from './App.vue'
import router from './router'

// The editor in Cycls (replaces upstream src/main.ts, pinned in
// editor/patches/upstream.sha256): the Cycls theme, the embed bridge, and none of
// what a standalone app needs.

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

// Light/dark (?theme=dark|light) and the language (?lang=ar|en) from Cycls before
// the app boots; the bridge follows later changes. Cycls owns the language: English
// unless it says Arabic.
const query = new URLSearchParams(location.search)
applyTheme(query.get('theme') ?? '')
localeSetting.set(query.get('lang') === 'ar' ? 'ar' : 'en')
// Every change is saved to the Cycls workspace: no crash-recovery copies in the browser.
setRecoveryRuntimeOverride(false)
// No service worker (vite/pwa.ts): remove one an earlier build installed.
void navigator.serviceWorker?.getRegistrations().then((registrations) => {
  for (const registration of registrations) void registration.unregister()
}).catch(() => undefined)

preloadFonts()
const head = createHead()
createApp(App).use(router).use(head).use(createRetainedScopePlugin()).mount('#app')
injectCyclsTheme()

startCyclsEmbedBridge()
