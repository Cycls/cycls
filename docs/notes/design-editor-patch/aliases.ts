import { resolve } from 'node:path'

export function createOpenPencilAliases(rootDir: string) {
  const emptyNodeModule = resolve(rootDir, 'vite/empty-node-module.ts')
  // Cycls: upstream modules and components replaced for the editor in Cycls
  // (editor/patches/stubs). Before '@', which would otherwise match them first.
  const stub = (file: string) => resolve(rootDir, 'src/app/embed/stubs', file)

  return [
    { find: /^fs$/, replacement: emptyNodeModule },
    { find: /^path$/, replacement: emptyNodeModule },
    { find: /^@\/app\/tabs$/, replacement: stub('tabs.ts') },
    { find: /^@\/app\/document\/io\/save$/, replacement: stub('save.ts') },
    { find: /^@\/app\/document\/export$/, replacement: stub('export.ts') },
    { find: /^@\/app\/ai\/chat\/use$/, replacement: stub('ai-chat.ts') },
    { find: /^@\/app\/shell\/menu\/files$/, replacement: stub('menu-files.ts') },
    { find: /^@\/app\/shell\/menu\/schema$/, replacement: stub('menu-schema.ts') },
    { find: /^\.\/ChatPanel\.vue$/, replacement: stub('Empty.vue') },
    { find: /^@\/components\/CollabPanel\/CollabPanel\.vue$/, replacement: stub('Empty.vue') },
    { find: /^@\/components\/MobileHud\/MobileShareButton\.vue$/, replacement: stub('Empty.vue') },
    { find: /^@\/components\/MobileHud\/MobilePresencePopover\.vue$/, replacement: stub('Empty.vue') },
    { find: /^@\/components\/libraries\/LibraryManagerDialog\.vue$/, replacement: stub('Empty.vue') },
    { find: '@', replacement: resolve(rootDir, 'src') },
    { find: '#vue', replacement: resolve(rootDir, 'packages/vue/src') },
    { find: '#core', replacement: resolve(rootDir, 'packages/core/src') },
    { find: '#dom-css', replacement: resolve(rootDir, 'packages/dom-css/src') },
    {
      find: /^@open-pencil\/dom-css\/browser$/,
      replacement: resolve(rootDir, 'packages/dom-css/src/browser.ts')
    },
    {
      find: /^@open-pencil\/dom-css\/jsx-runtime$/,
      replacement: resolve(rootDir, 'packages/dom-css/src/jsx/runtime.ts')
    },
    {
      find: /^@open-pencil\/dom-css\/jsx-dev-runtime$/,
      replacement: resolve(rootDir, 'packages/dom-css/src/jsx/dev-runtime.ts')
    },
    {
      find: /^@open-pencil\/dom-css$/,
      replacement: resolve(rootDir, 'packages/dom-css/src/index.ts')
    },
    {
      find: /^@open-pencil\/scene-graph$/,
      replacement: resolve(rootDir, 'packages/scene-graph/src/index.ts')
    },
    { find: '@open-pencil/scene-graph', replacement: resolve(rootDir, 'packages/scene-graph/src') },
    { find: /^@open-pencil\/pen$/, replacement: resolve(rootDir, 'packages/pen/src/index.ts') },
    { find: '@open-pencil/pen', replacement: resolve(rootDir, 'packages/pen/src') },
    { find: /^@open-pencil\/kiwi$/, replacement: resolve(rootDir, 'packages/kiwi/src/index.ts') },
    { find: '@open-pencil/kiwi', replacement: resolve(rootDir, 'packages/kiwi/src') },
    { find: /^@open-pencil\/fig$/, replacement: resolve(rootDir, 'packages/fig/src/index.ts') },
    { find: '@open-pencil/fig', replacement: resolve(rootDir, 'packages/fig/src') },
    {
      find: /^@open-pencil\/mcp\/discovery$/,
      replacement: resolve(rootDir, 'packages/mcp/src/transport/discovery.ts')
    },
    {
      find: /^@open-pencil\/mcp\/transport$/,
      replacement: resolve(rootDir, 'packages/mcp/src/transport/paths.ts')
    },
    {
      // Cycls fix: the app aliases discovery + transport to source but MISSED
      // tools, so vite non-deterministically externalizes @open-pencil/mcp/tools
      // (bare-specifier boot crash). Alias it to source so it always bundles.
      find: /^@open-pencil\/mcp\/tools$/,
      replacement: resolve(rootDir, 'packages/mcp/src/tool/index.ts')
    },
    { find: /^@open-pencil\/vue$/, replacement: resolve(rootDir, 'packages/vue/src/index.ts') },
    { find: '@open-pencil/vue', replacement: resolve(rootDir, 'packages/vue/src') },
    { find: /^@open-pencil\/core$/, replacement: resolve(rootDir, 'packages/core/src/index.ts') },
    { find: '@open-pencil/core', replacement: resolve(rootDir, 'packages/core/src') },
    {
      find: 'opentype.js',
      replacement: resolve(rootDir, 'node_modules/opentype.js/dist/opentype.mjs')
    }
  ]
}
