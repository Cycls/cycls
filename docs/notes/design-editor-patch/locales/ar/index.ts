import type { ComponentsJSON } from '@nanostores/i18n'

import code from './code.json'
import commands from './commands.json'
import common from './common.json'
import diagnostics from './diagnostics.json'
import editor from './editor.json'
import files from './files.json'
import fonts from './fonts.json'
import media from './media.json'
import menu from './menu.json'
import pages from './pages.json'
import panels from './panels.json'
import rename from './rename.json'
import rendering from './rendering.json'
import tools from './tools.json'
import variableTypes from './variable-types.json'
import variables from './variables.json'

// Arabic for the editor Cycls embeds. Namespaces of the standalone app Cycls removes
// (AI, automation, collaboration, credentials, recovery, settings, storage, updates)
// are empty: their keys fall back to English. They must still be here — nanostores
// waits for every requested namespace before it re-renders any, so a missing one
// kept the whole editor in English.
const unused = {}

export default {
  ai: unused,
  automation: unused,
  code,
  collaboration: unused,
  commands,
  common,
  credentials: unused,
  diagnostics,
  editor,
  files,
  fonts,
  media,
  menu,
  pages,
  panels,
  recovery: unused,
  rendering,
  rename,
  settings: unused,
  storage: unused,
  tools,
  updates: unused,
  variables,
  variableTypes
} satisfies ComponentsJSON
