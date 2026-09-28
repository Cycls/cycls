import { VitePWA } from 'vite-plugin-pwa'

// No service worker, in Cycls (replaces upstream vite/pwa.ts, pinned in
// editor/patches/upstream.sha256). The editor lives in a Cycls iframe and is served
// fresh by the design service; upstream's auto-updating worker could reload it in
// the middle of an edit after a deploy. This build's sw.js is a self-destroying one:
// it replaces a worker an earlier build installed, then removes itself.
export function openPencilPwaPlugin() {
  return VitePWA({ selfDestroying: true, injectRegister: false, manifest: false })
}
