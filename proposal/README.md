# Proposal: a native Apps section — an agent's app catalog, installable and themable

Branch `proposal/apps-catalog`, cut from `8156ad52` (**release: 0.0.2.147**, the commit that bumps
`pyproject.toml` to the version on PyPI; the repo has no tags). Local only: not pushed, no PR, nothing
deployed, no running agent touched.

Everything here is a proposal. The code is real and tested, but it is written to be read and argued
with, not merged as is.

## The problem

Our agents ship ready-made mini-apps — 46 planned across seven agents, 20 built for Super today (tasks,
minutes, a Saudi work calendar, KPIs, a CRM…). They are shadcn/ui React apps built with the same toolchain
as `build_app`. There is no SDK surface for that today, so each agent works around it:

- **Super installs them from the agent side, on every turn** (`super-dev2/default_apps.py`): it copies
  `/app/default_apps/<slug>/` into the workspace, stamps `app.json`, trashes what it replaces, and pokes
  the SDK's private caches (`tools._apps_cache`, `routers._catalog_drop`). It works, but people cannot
  choose which apps they want. The copy happens on every turn of every chat. It also reaches into
  private names.
- **Nobody can pick or remove an app.** An app is either pushed into every workspace or not there at all.
  Removing one only lasts until the next turn copies it back in.
- **Apps cannot match the workspace's brand.** Every default app wears the kit's teal. An org that wants
  its own colors has to ask the agent to rebuild 20 apps. Each rebuild is a prompt and a build, and the
  next update from us overwrites it.

## What it looks like

Screenshots are in `screenshots/`. They were taken from the real client components, driven by
Playwright against a harness with a mocked API (see *How this was checked*).

| | |
|---|---|
| `01-plus-menu.png` | **+ menu**: an **Apps ›** entry directly under **Skills** |
| `02-plus-menu-apps-submenu.png` | its submenu: the installed apps (open in the canvas) and **Browse apps…** |
| `03-apps-catalog.png` | the connectors window, new **Apps** item in the left nav under Skills: search, category chips, cards with icon, name, category, size and description; *Yours* first, then *Discover*; Open / Remove / Update / Install; an **Update available** badge |
| `04-apps-catalog-member.png` | a member who is not an admin: what is installed, Open only, and one line saying who can change it |
| `05-apps-catalog-dark.png` | dark mode |
| `06-theme-panel.png` | **Theme**: base color, accent, radius, live preview of a shadcn card, badge, table and buttons in light *and* dark |
| `07-theme-panel-brand-color.png` | an optional brand color that replaces the accent |
| `08-app-own-look.png` | the real Tasks app (built from the kit, unchanged) with no theme set: its own teal |
| `09-app-zinc-violet.png` | the same bundle under *zinc / violet* |
| `10-app-stone-green-live.png` | then *stone / green*, **pushed live** to the open app over `cycls:command`, with no reload |
| `11-app-dark-rose-live.png` | *slate / rose* in dark mode |
| `12-apps-catalog-ar.png`, `13-theme-panel-ar.png`, `14-plus-menu-apps-ar.png` | Arabic, RTL |
| `15-…`, `16-…`, `17-…-phone.png` | phone width (390 px): the window goes full screen with the nav as tabs at the top, and the + submenu drills down in place |

The new UI copies the Connectors list next to it: the same window, the same search field, the same chips,
the same two-column cards with one 28 px state slot (+ / ✓ / update), the same pill buttons and the same
`H4` headings. No new primitive was added.

A design note on the + menu: the brief asked for a submenu. Skills in the real menu is not a submenu (it
opens the window on the Skills tab), so Apps is the only real submenu in that menu. It **replaces the
menu in place** with a back row, instead of opening a flyout beside it. A flyout next to a menu sitting at
the screen's edge has no room on a phone; the drill-down fits both screen sizes.

## API

### Declaring a catalog (server)

```python
@cycls.agent(
    web=cycls.Web().auth(cycls.Clerk()).workspaces()
        .apps("default_apps", theme={"base": "zinc", "primary": "#0b6b5d"}),   # theme: optional default
    volumes={"/workspace": cycls.Volume("super")},
)
```

`default_apps/<slug>/` is exactly what `build_app` would write, plus metadata:

```
default_apps/tasks/index.html     the built bundle
default_apps/tasks/app.json       {name, name_ar, icon, description, description_ar, category, category_ar}
default_apps/tasks/README.md      the data model, for the agent
default_apps/tasks/src/**         the source, so build_app can rebuild it
```

`.apps()` adds the folder to the image (`image.copy`). It stores the path as a **string**, never a
`Path`: the agent is pickled on the machine that deploys it, and a `WindowsPath` in that pickle kills the
container at startup with no log. We have hit that bug before when deploying from Windows.

### Routes

| | body / answer | who |
|---|---|---|
| `GET /apps/catalog` | `{admin, apps: [{slug, name, name_ar, icon, description(_ar), category(_ar), version, bytes, state, installed_name?}]}`, `state` ∈ `available` · `installed` · `update` · `conflict` | any member |
| `POST /apps/install` | `{slug}` → `{outcome: installed\|current, entry}` | workspace admin |
| `POST /apps/update` | `{slug}` → `{outcome: updated\|current}` | workspace admin |
| `POST /apps/uninstall` | `{slug}` → `{trash_id}` | workspace admin |
| `GET /apps/theme` | `{theme, default, admin}` | any member |
| `PUT /apps/theme` | `{theme: {base, color, radius, primary?}}`, or `{theme: null}` to reset | workspace admin |

The catalog routes are mounted only when the agent declares a catalog. The theme routes are always
mounted, because any app on shadcn variables can wear a theme, catalog or not. The client shows the Apps
section only when `config.apps_catalog` is set, so an existing agent looks exactly as it does today.
`/apps/catalog` and `/apps/theme` are literal paths mounted before `apps_router`; a test checks that an
app named `catalog` still reaches its own `/apps/catalog/data`.

### The theme contract with apps

```js
// cycls:init, beside what it carries today
{ type: "cycls:init", path, scope, canWrite, theme: "dark", locale: "ar",
  tokens: { light: {"--primary": "oklch(…)", "--radius": "0.5rem", …}, dark: {…} } }   // only when a theme is set

// pushed down the app's port when an admin saves, or the host flips light/dark
{ type: "cycls:command", command: { type: "theme", theme: "dark", tokens: {…} | null } }
cycls.onCommand(fn)   // same channel and names as the feat/agent-design-extensions branch
```

The shim applies the tokens itself in one `<style id="cycls-theme">`. Its selectors, `:root:root` and
`:root:root.dark, :root:root[data-theme="dark"]`, rank above an app's own `:root` and `.dark`, so it does
not matter where in the document the app's CSS lands. **Any app on shadcn variables re-skins live with
no rebuild and no app code.** That includes every app built so far, since they all use the kit's
variable names. An app that wants to keep its own look adds `<meta name="cycls-theme" content="off">`.
When no theme is set and there is no agent default, the host sends no tokens and the shim adds no style,
so today's apps are not affected.

Tokens are derived in the client (`client/src/lib/app-theme.ts`, a file with no imports). The server only
keeps the choice. That keeps the CSS in one place, and the panel's live preview needs the tokens before
anything is saved anyway. The phone client can mirror the file into its shared `src/core/apps.mjs`, the
same way it already mirrors `appScope` and `canWrite`.

The values are shadcn/ui v4's OKLCH presets: the four `components.json` base colors (neutral, zinc,
slate, stone), the accent themes (blue, green, orange, red, rose, violet, yellow), the radius scale, and
an optional brand hex whose foreground is chosen by WCAG contrast. **They were typed in by hand**, so the
test checks that every set has the right token names, not every number. Re-check them against shadcn when
upgrading.

## Data model

| what | where | why there |
|---|---|---|
| installed app | `apps/<slug>/`, identical to a `build_app` output | nothing downstream learns a new kind of thing: bridge, `appScope()`, Apps tab, `app_catalog()`, trash, rename, share |
| catalog provenance | `app.json` → `"catalog": {"version": <sha256[:12] of index.html>, "at"}` | the stamp separates our apps from a person's own; the hash marks an update whenever a redeploy changes a bundle |
| legacy stamp | `app.json` → `"default_app": {…}` (super's installer) | read the same way; the next update rewrites it as `catalog` |
| the theme | row `.theme` in the workspace's `.apps` slot | **one per workspace**, shared by its members |

**Where the code disagreed with the brief:** the brief put the theme in "the settings slot". In the code,
`state.settings_db` is per *person* (`workspace(ws.subject, …, slot=".settings")`, with no `ws=`): it
follows a person across workspaces. A workspace-wide theme has to live with the workspace, so it goes in
the `.apps` slot, which is already one shelf per workspace and already in `MANAGED`. The key `.theme`
cannot collide with any app's rows, because `build_app`'s slug alphabet has no dot (`_APP_SLUG_OK`).

## Security

- **Admin gate.** Install, update, uninstall and `PUT /apps/theme` all go through `_admin()`, the same
  check that already gates deleting or renaming an app: owner or admin of a team workspace, or the person
  in their own personal workspace. With workspaces off, `_admin` answers yes, as it does for deleting an
  app today. This proposal changes neither rule.
- **A person's app is never overwritten.** A folder at the slug that has an index.html or app.json but no
  stamp is `conflict`. Install, update and uninstall all answer 409 for it, and tests check this.
  `data/` is never touched. An update keeps the name and icon a person set and trashes the old
  `index.html`, as a rebuild does.
- **Only catalog slugs.** The slug must match `build_app`'s alphabet *and* be a key of the catalog read
  from the image. A request can never name a path.
- **Sandbox unchanged.** Same `sandbox="allow-scripts …"`, same opaque origin, same port handshake. The
  theme push travels down the port the app already has, never on the window.
- **CSP unchanged.** The style element is allowed by the `style-src 'unsafe-inline'` every bundle already
  carries. The shim only writes tokens named `--[a-z0-9-]{1,40}` with values free of `; { } < > \`, so a
  token cannot close the rule. A test feeds it `red}body{display:none` and an escape sequence, and both
  are dropped.
- **The bash sandbox cannot reach the catalog.** `/app` is a tmpfs in the bash sandbox, so the agent
  cannot `cp` from `/app/default_apps`. That is also why install has to be a route, not something the
  agent does with bash.

## Migration

- **Agents:** replace the per-turn `ensure_default_apps()` hook with `.apps("default_apps")`. Workspaces
  it already seeded show their apps as *installed* (same stamp name, same version hash). Keep the hook
  only if an agent still wants apps preinstalled: see the open questions.
- **Apps:** nothing to do. A built app that uses shadcn variables follows the theme.
  `proposal/kit-patch/` goes further for our own kit, see below.
- **Mobile host:** until it mirrors `lib/app-theme.ts` and the `wear()` part of the shim, phone users see
  the app's own look. Nothing breaks.

### The kit patch (`proposal/kit-patch/`)

This is a copy of `cycls-default-apps/kit`, patched; the original is untouched. `kit.diff` holds the
three changes:

1. `components/theme.tsx`: follows the host's light/dark pushes (`cycls.onCommand` → `{type: "theme"}`)
   instead of reading `ctx.theme` only at boot.
2. `cycls.ts`: `wearHostTokens()`, a fallback for a host that passes `ctx.tokens` without applying them
   itself (a phone shim that lags behind the web one). It never writes over the shim's own style.
3. `theme.css`: while a theme is applied (`[data-cycls-theme]`), the kit's extra colors
   (`--primary-soft`, `--border-strong`) are derived from `--primary` instead of staying teal.

Screenshots 08–11 show the Tasks app built from this patched kit, using the real toolchain.

## Open questions

1. **Preinstall.** Should `.apps()` take `install=["tasks", "calendar"]` so new workspaces start with a
   few apps, the way super does today? If so, should that happen on a workspace's first visit, or when
   it is created?
2. **Reinstall after Remove.** A fresh install starts with empty data, as `build_app` does on a fresh
   slug. To get the data back, restore the app from the trash instead. Should Install notice an
   uninstalled entry still in the trash and offer to restore it?
3. **Who may install** in an org with workspaces off. Today that is everyone, matching app deletion.
   Should it be org admins (`org_role == "admin"`)?
4. **Per-person override of light/dark** inside an app. The kit already allows it; the theme colors stay
   the workspace's. Is that the split we want?
5. **Catalog from the CMS or a bucket**, like the Skills library, rather than from the image: updates
   would ship without a redeploy. The `Catalog` class is the one seam to swap.
6. **Theme in the chat UI itself.** `Web().colors()` already sets the host's accent. Should the
   workspace theme drive that too, or should apps and the chat UI stay separate?
7. **The extensions branch.** `feat/agent-design-extensions` adds `Web().use(ext)`, `POST /apps/open`
   and `cycls:command`. This proposal uses the same command channel and names, so the two can merge. A
   catalog could also become an `Extension` later.

## Related SDK issues found on the way

Each one was checked against `8156ad52`; none of them is fixed here except the first.

1. **Purging a trashed app deleted the rows of a reinstalled one** (*fixed here*). Delete or uninstall
   `crm`, build or install a new `crm`, then empty the trash: `_drop_app_data` removed `.apps/crm/` and
   took the new app's data with it. It now skips a slug whose folder exists again. The test
   `test_purging_an_old_entry_spares_the_rows_of_a_reinstalled_app` fails without the guard (checked).
2. **`database` tool `value` is untyped.** `_DATABASE_TOOL.input_schema.properties.value` has no
   `type`, so models often send a JSON *string* (`"{\"title\": …}"`). The app then reads a string where
   it expects an object. Suggested fix: `"type": ["object", "array", "string", "number", "boolean",
   "null"]` plus a line telling the model to send the value itself, or parse a string that is valid JSON
   on `put`.
3. **The agent cannot write `cycls.me` rows.** `app_shelf()` refuses keys under `u/`, and `database`
   has no `who`. An agent can seed or fix the shared data, but cannot do the same for one person's data
   (a draft, a preference) that an app keeps with `cycls.me`.
4. **No create-only `put` for the agent.** The route has `?version=""` (create-only) and CAS, but the
   `database` tool only has last-write-wins `put`. An agent adding `task:<id>` can overwrite a row a
   person created at the same moment.
5. **`write: admin` is a plain read of `app.json` on every non-admin write**, and with workspaces off it
   lets everyone write (documented). Any member can edit `app.json` through `/files`. That includes
   removing `"write": "admin"`, since `canWrite` only limits the *bridge* to `data/`, not the files route.
6. **The 10,000-row list cap has no cursor.** `cycls.get` throws once the list is cut off (good), but
   the only way past the cap is a narrower prefix. Apps that keep one row per record (tasks, CRM) will
   reach it.
7. **`/app` is a tmpfs in the bash sandbox.** Anything shipped in the image is invisible to the agent's
   bash: catalog bundles, reference data, templates. Skills solved this with a read-only mount
   (`/skills/<name>/`). A read-only mount for `.apps()`'s folder would let the agent read a catalog app's
   README and source before it rebuilds one.

## Files changed

Server

- `cycls/_agent/catalog.py` (**new**): catalog reading, state, install/update, theme validation
- `cycls/_agent/web/routers.py`: `app_catalog_router` (6 routes), `_drop_app_caches`, the
  `_drop_app_data` guard, mounting
- `cycls/_agent/web/builder.py`: `Web.apps(catalog, *, theme=None)`
- `cycls/_agent/main.py`: `agent.apps`, image copy, `config.apps_catalog`
- `cycls/_agent/web/server.py`: `Config.apps_catalog`

Client

- `client/src/lib/app-theme.ts` (**new**): presets, `themeTokens`, `normalize`, the host's current theme
- `client/src/components/apps-catalog.tsx` (**new**): Browse + Theme panels and the preview
- `client/src/components/connectors-dialog.tsx`: an `apps` nav item under Skills
- `client/src/components/input-box.tsx`: the + menu's Apps submenu
- `client/src/components/chat.tsx`: loads the theme and wires the menu and the window
- `client/src/components/canvas.tsx`: `tokens` in `cycls:init`, theme pushes
- `client/src/components/app-bridge.ts`: `MSG.command`, the `commands` subscription
- `client/src/components/app-shim.ts`: `wear()`, `cycls:command`, `cycls.onCommand`
- `client/src/hooks/use-chat.ts`, `client/src/lib/i18n.ts`: config flag, strings in EN and AR

Docs

- `docs/notes/apps.md`: new sections "The catalog" and "The theme"
- `docs/notes/analytics.md`: `app_catalog_action`, `app_theme_saved`

Tests

- `tests/agent/app_catalog_test.py` (**new**, 35)
- `client/tests/app-theme.test.ts` (**new**, 12)
- `client/tests/apps-catalog.test.tsx` (**new**, 8)

`cycls/_agent/web/themes/default` was **not** rebuilt. The repo's publish step does that, and rebuilding
it here would mix a proposal into the shipped bundle.

## How this was checked

- `uv run pytest tests/agent/app_catalog_test.py`: **35 passed**. The full mocked suite
  (`tests/`, without `tests/function`, which needs Docker): 1055 passed, 14 failed. The **same 14 fail on
  the untouched branch point**: they are Windows-only (cp1252 reads, `:` in file names, the `rm` shim's
  POSIX subprocess).
- `cd client && npm test`: **413 passed / 413**. `npx tsc --noEmit`: clean.
- Screenshots: `proposal/harness/` is a small Vite page that mounts the real components (`InputBox`,
  `ConnectorsDialog`, `CanvasDoc` with the real shim and bridge) against an in-memory API. The app scenes
  load the Tasks bundle built from `kit-patch/` with the real toolchain. The app runs in *gallery* mode
  (the kit's demo data, hence its "Example" banner), because the harness has no workspace. To run it:
  `cd proposal/harness && mklink /J node_modules ..\..\client\node_modules && npx vite --config
  vite.config.mjs --port 5199`, then `node shoot.mjs <folder with playwright>`.
- Not checked: a real `cycls run` with Clerk sign-in, the phone app, and GCS (`DB.delete` on a prefix
  is exercised only against the file store).
