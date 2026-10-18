/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_CLERK_PUBLISHABLE_KEY?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}

interface Window {
  // Rewardful referral tracking (snippet in index.html). The queue is defined
  // synchronously, so calls are safe before rw.js finishes loading.
  rewardful?: (action: string, opts?: Record<string, unknown>) => void;
}

// liquidGL ships no types: one function that turns an element into glass, returning the lens (or lenses).
declare module "liquid-gl" {
  const liquidGL: (options: Record<string, unknown>) => unknown;
  export default liquidGL;
}
