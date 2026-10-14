# Skills: the Cycls library, a workspace's own, and your own

> **Status (2026-10-14):** built: the store, the loader, both switches, the `skill` tool's `publish`
> (`cycls/_agent/tools/skills.py`) and the Skills tab (`skills_router`, `client/src/components/skills-panel.tsx`).
> Not yet: the library, the skill creator, the import. Until the
> import runs, a workspace's old `skills/` folders no longer load.

A skill is a folder with a `SKILL.md`: frontmatter (`name`, `description`) and the instructions,
plus any scripts, templates and reference files beside it. It is the [Agent Skills](https://agentskills.io)
format Claude, Codex, Cursor and Gemini CLI read, so a skill moves between them as a file.

## Why it changes

- **Nobody can tell what is installed.** A skill is a folder name to get exactly right. The product
  team's `SKILLS/thmanyah-style/` has never loaded, because the loader reads only `skills/`.
- **Anyone changes everyone's agent.** A workspace skill loads into every member's chats, and any
  member, or an agent steered by a page it read, can write `skills/x/SKILL.md` unseen. It is the
  hole closed for app data (`.apps`) and for `AGENT.md` on forks.
- **Our skills are copied by hand.** Super carries 11 of the 25 Cycls-Skills, and the copies drift.

## Four places, one shape

| | Stored | Written by |
|---|---|---|
| **Cycls library** | a Cycls bucket, shared by every agent and org, published by CI from [Cycls-Skills](https://github.com/Cycls/Cycls-Skills) | us; agents only read it |
| **Org** | the org's `.skills`: `{org}/.skills/`, in every workspace of the org | its admins (`org_role == "admin"`) |
| **Workspace** | the team workspace's `.skills` slot: `{org}/ws/{ws}/.skills/` | its owners and admins |
| **Just me** | the person's personal workspace's `.skills`: `{org}/ws/u-{user}/.skills/` (a solo account's root) | that person |

A person's own skills load in every workspace they enter, the way their *just me* connector
grants do. In their personal workspace, *workspace* and *just me* are the same place. Without
workspaces an org has one root, which is the org's place: its members have none of their own.

Each place keeps every skill the same way: versions that never change, and a pointer to the one
that loads.

```
.skills/<name>/meta.json     {"default": 3, "versions": [{"v": 3, "at": …, "by": …}]}
.skills/<name>/v1/SKILL.md   …and its files
.skills/<name>/v3/SKILL.md
```

Publishing adds a version and points `default` at it. Rolling back moves the pointer. Removing
deletes the folder. The library has a `latest` pointer too: CI moves `latest` on every merge to
Cycls-Skills, and `default` moves only when we promote (`cycls skills promote app 8`).

`.skills` joins `MANAGED` (`cycls/_agent/paths.py`): `bash`, the file tools and `/files` never
reach it. The way in is the Skills tab and the `skill` tool.

## A turn's skills

1. The library skills the agent's code names, at their `default` (or a pinned version):
   `cycls.LLM().skills(cycls.Library("app", "pdf", "docx@4"))`. A directory still works beside it,
   for a skill shipped in the image.
2. The org's skills, over them.
3. The workspace's skills, over those.
4. The person's own, over all.
5. Minus every name the org blocked, and every name the person switched off.

A same-named skill wins upward: own over workspace over org over Cycls. Every skill's folder is mounted read-only at `/skills/<name>/`, wherever it is stored,
so a script's path never depends on its scope. The library is cached on local disk by version
(versions never change); pointers are re-read every few minutes, workspace and personal meta on
the 30s TTL the loader uses today.

## Who can do what

The same switches and roles as connectors, in the same window: the **Skills** tab of the
connectors dialog, which reads *soon* today.

| | Connectors (today) | Skills |
|---|---|---|
| Org admin (`org_role == "admin"`) | *Allowed in organization*: off hides it from every member; admins see it greyed | the same switch, by name, over any skill; publishes the org's skills |
| Each person | *Use in my chats*: their own, kept in every workspace | the same |
| Workspace owner / admin | connects and removes the team grant | adds, updates, rolls back and removes the workspace's skills |
| Member | connects *just me* | adds *just me* skills |
| Declared in the agent's code | which connectors exist | which library skills it offers; on by default |

Where the switches are stored:

- org block: the org row `skills` = `{"blocked": [...]}`, next to `connectors` (`connectors.blocked`)
- personal off: the person's `.settings` row `skills` = `{"off": [...]}`. A preference, not a
  secret, so it needs no `CYCLS_SECRET_KEY`, unlike the connectors' `_off` row.

A switched-off skill is out of the catalog, and the `skill` tool refuses it.

## The Skills tab

Beside *Connectors* in the same window, opened from the **+** menu or Settings → General. The list: search, and **Add** with *Upload a skill* (a `.skill` or `.zip`), *Create a skill*
(a form: name, description, instructions) and *Create with Cycls* (a chat that writes one). One row per
skill: where it comes from, its description, when it was updated, and the person's switch.

A skill's page: who made it and when, the switch, and two tabs. *Overview* is the description, who it is
available to, who made it and the version. *Contents* is its files and each one shown, Markdown
formatted or raw, with a picker over its versions and *Make this the current version* (a rollback).
The **⋮** menu: *Edit* (the same form, saving the next version), *Download*, *Available to* (*Just me*,
*Workspace*, *Organization*: moving it keeps its current version in the new place), *Off for everyone*
for an org admin, and *Remove* (asks twice; its versions stay).

**A new skill is the person's own**, made in the form, uploaded, or published by the agent; sharing it
with the workspace or the org is a step on its page.

Routes: `GET /skills`, `GET /skills/{name}?v=`, `GET /skills/{name}/file?path=&v=`, `PATCH /skills/{name}`
(`on`, or `allowed` for an org admin), `POST /skills?scope=` (an archive as the body),
`PUT /skills/{name}` (the form), `POST /skills/{name}/move`, `POST /skills/{name}/current`,
`DELETE /skills/{name}`, `GET /skills/{name}/download`.

## Getting a skill in

Every way ends in the same publish: validate, store a new version, point `default` at it.

- **Upload** in the Skills tab: a `.skill` (Claude's package format) or `.zip`, with `SKILL.md`
  at its root or in its one top folder. `.DS_Store`, `__MACOSX` and `__pycache__` are dropped,
  `SKILL.md` line endings become LF, and anything over 10 MB is refused.
- **From a chat**: attach the `.skill`/`.zip`, or paste a link to a skill's folder on GitHub. The
  agent puts it in `skill-drafts/<name>/` and publishes it with the `skill` tool.
- **Made with the agent**: the `skill-creator` skill (below) drafts, tests and publishes.

Publishing from a chat follows the composer switch, like any edit: *Auto* publishes, *Ask* asks.
No card of its own: what keeps a skill in check is who may publish it (a team's owners and admins;
a member only for themselves) and the switches, which take any skill out of every chat at once.

Publishes are refused with the reason when the frontmatter breaks the spec's rules: `name`
lowercase-hyphen, at most 64 characters, the same as the folder; `description` at most 1024; the
frontmatter within the first 4 KB. A version is at most 500 files and 10 MB, and a link in the
folder is refused: read outside the sandbox, it could name any file on the volume.

## Getting a skill out

**Download** gives `<name>.zip`, the folder at its root: the format Claude's upload and the
standard's tools take. The agent's built-in skills, and the library's, are not downloadable.

## The `skill` tool

| Action | |
|---|---|
| `load` | today's: the body of a skill, or one of its files |
| `publish` | `skill-drafts/<name>/` (or any folder) to a new version, `scope`: `workspace` or `me` |

Drafts are ordinary workspace files, so the agent edits them with its usual tools and a person
can see them in the file panel. To change a published skill the agent copies `/skills/<name>/`
into `skill-drafts/<name>/`.

## The skill creator

A `skill-creator` skill in the Cycls library, offered by every agent that offers skills. It is
adapted from [Anthropic's skill-creator](https://github.com/anthropics/skills/tree/main/skills/skill-creator)
(Apache-2.0: its licence travels with it, with a note of what changed). OpenAI ships the same
pair in Codex, `skill-creator` and `skill-installer`; here the installing is the `skill` tool's
`publish`, so one skill is enough.

Kept from Anthropic's:
- capturing the intent, from the chat when the person says "turn this into a skill"
- the interview: edge cases, inputs and outputs, examples, what success looks like
- how to write one: anatomy, progressive disclosure, a description that says when to use it,
  explaining why rather than shouting MUST
- testing on two or three real prompts, run by the agent itself, and improving from the
  person's feedback (Anthropic's path for Claude.ai, which has no subagents either)
- `quick_validate.py`, rewritten to our loader's rules

Changed for Cycls:
- drafts in `skill-drafts/<name>/`, finished with `skill publish`, not `package_skill.py`
- the Cycls limits: scripts may import only what the image carries (no `pip install` at run
  time), a loaded file stops at 48 KB, Arabic and RTL output, and scripts at `/skills/<name>/`
- editing a published skill keeps its name: copy `/skills/<name>/` to a draft, change, publish

Dropped: the subagent baseline runs, the benchmark viewer, and the description optimizer
(`run_loop.py` needs `claude -p`).

## Moving what is there

One operator command, run per agent (`cycls skills import <agent>`), in line with every other
migration: each workspace's `skills/<name>/` and `SKILLS/<name>/` (any case) becomes
`.skills/<name>/v1`, with the junk dropped. It reports what it moved and what it refused. The old
folders stay as ordinary files. From then on plain folders do not load.

Super's copies go: it names its library skills instead.

## Build order

1. The store and the loader: `.skills` in `MANAGED`, versions and pointers, the three scopes, the
   two switches, the `/skills/<name>/` mounts, the `skill` tool's `publish`, the import.
2. The library: the bucket, CI publishing from Cycls-Skills, `latest`/`default`,
   `cycls skills promote`, `cycls.Library(...)`, super switched over.
3. The Skills tab.
4. `skill-creator` in Cycls-Skills.
5. The docs: `docs/tutorial.md` ("Workspace instructions and skills"), this page as the reference,
   and docs.cycls.com.

## Compared with Claude

Claude's Team and Enterprise plans ([provisioning](https://support.claude.com/en/articles/13119606-provision-and-manage-skills-for-your-organization),
[using](https://support.claude.com/en/articles/12512180-use-skills-in-claude)), as of October 2026:

- **The same:** an owner provisions a skill for the whole org, on by default; each person switches
  one off but can't delete it; personal skills; versions; the open standard.
- **Theirs, not ours:** per-skill access levels (*installed by default*, *available to install*,
  *required*, *not available*); read-only sharing between people; *Publish to org* with optional
  review and a security scan; an org switch that turns user-created skills off; a partner directory.
- **Ours, not theirs:** a team workspace's own skills (Enterprise gets near with groups, through
  plugins); a skill's scripts mounted where the agent runs them.

## Sources

- [Claude: provision and manage skills for your organization](https://support.claude.com/en/articles/13119606-provision-and-manage-skills-for-your-organization): org skills on by default, each person switches them
- [Anthropic: skills in the API](https://platform.claude.com/docs/en/build-with-claude/skills-guide): versions that never change, pin one or follow the latest
- [OpenAI Codex: Agent Skills](https://developers.openai.com/codex/skills): scopes, and the `skill-creator` / `skill-installer` it ships
- [anthropics/skills](https://github.com/anthropics/skills): `skill-creator`, Apache-2.0
