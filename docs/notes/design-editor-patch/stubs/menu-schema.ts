// The editor's menus, in Cycls: upstream's schema (src/app/shell/menu/schema.ts,
// pinned in upstream.sha256) without what Cycls handles itself or doesn't use —
// opening files and recent files, the storage workspace, autosave (it always saves to
// the workspace), closing the tab, PowerPoint/.fig selection exports, multiplayer
// cursors, theme and language (Cycls sets both), settings, the profiler and dev tools.
// The menubar, the command palette and the shortcut labels all read this schema.
import {
  APP_MENU_SCHEMA as UPSTREAM_SCHEMA,
  type AppMenuEntry,
  type AppMenuGroupSchema
} from '../../shell/menu/schema'

export * from '../../shell/menu/schema'

const REMOVED = new Set([
  'open', 'open-recent', 'open-storage-workspace', 'autosave', 'close',
  'export-pptx', 'export-fig', 'view-multiplayer-cursors', 'theme', 'language',
  'settings', 'profiler', 'dev-tools'
])

const seen = new Set<string>()

function filter(items: AppMenuEntry[]): AppMenuEntry[] {
  const kept: AppMenuEntry[] = []
  for (let item of items) {
    if (item.type !== 'separator') {
      if (REMOVED.has(item.id)) {
        seen.add(item.id)
        continue
      }
      if (item.sub) item = { ...item, sub: filter(item.sub) }
    }
    // No separator first or twice in a row once items are gone…
    if (item.type === 'separator' && (!kept.length || kept.at(-1)?.type === 'separator')) continue
    kept.push(item)
  }
  // …or last.
  while (kept.at(-1)?.type === 'separator') kept.pop()
  return kept
}

export const APP_MENU_SCHEMA: AppMenuGroupSchema[] = (UPSTREAM_SCHEMA as AppMenuGroupSchema[]).map(
  (group) => ({ ...group, items: filter(group.items) })
)

const missing = [...REMOVED].filter((id) => !seen.has(id))
if (missing.length) throw new Error(`menu-schema: upstream no longer has ${missing.join(', ')}`)
