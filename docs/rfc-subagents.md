# Subagents: an agent hands work to agents of its own

**Status**: proposed (2026-11-07), branch `rfc/subagents`. Built (2026-11-08): the tool, background agents, reports
waking the parent, the limits, file holds, cost, the stored record and the web card; tried live on super-new
(2026-11-09). Still to build: messages to a
running run (the inbox below), Stop per agent, paid plans in Super and Haseef, mobile.

An agent gets one more builtin tool, `Agent`. It starts a child agent with a short label and a written brief.
The child works in the background with the same workspace and tools, while the parent carries on and the person
keeps talking to it. When a child finishes, its report arrives in the parent's run as a message, and the parent
relays what matters. The chat shows the children in one team card; clicking a row opens that child's work.

This is how the harness this was designed in works, and what nearly every major harness converged on (the survey
at the end).

## Decisions

| | Decided |
| --- | --- |
| Does the parent wait for its children? | **No.** It starts them and carries on or ends its turn; each report arrives as a message |
| What can a child do? | Everything the parent can, **Design, Docs, Sheets and Apps included**, except start agents or ask the person |
| How the chat shows them | **One team card** per turn that started agents: a row per child, the working ones first |
| What a child gets | Only its brief: a fresh context, the same workspace, user and tools |
| What comes back | Its final report, to the parent only. The person sees it by opening the child |
| Who gets agents | **Paid plans only.** Agents cost several times a turn |
| How many at once | **4** per chat |

## The tool

```json
{
  "name": "Agent",
  "input_schema": {
    "type": "object",
    "properties": {
      "description": { "type": "string", "description": "3 to 5 words, in the person's language: the row's label" },
      "prompt": { "type": "string", "description": "The brief: everything the agent needs, as it knows nothing else" }
    },
    "required": ["description", "prompt"]
  }
}
```

The tool returns at once: `Started «label» (agent a1b2c3). Its report will arrive as a message. Don't wait or check
on it, and don't guess what it will find.` The call's step row is the anchor the team card hangs from.

The tool's description carries the judgement, in our usual plain voice (no dashes, no vendor names):

- Use it for parts that stand alone and can run at once: research across several sources, separate deliverables
  (a deck, a sheet, a doc), the same work over many items.
- Don't use it for a lookup or anything a few tool calls finish; the agents cost several times a normal turn.
- Write a brief a colleague could act on without asking: the goal, the files, what to make, what to report.
- Give each agent its own files. Two agents never edit the same file. When the parts belong in one file, have each
  agent make its own part and combine them yourself once the reports are in.
- Once you've handed something off, don't also do it yourself. Relay what matters from each report.

An agent opts in the way Sheets and Docs do: `"Agent"` in `.allowed_tools([...])`. No new builder method.

**Paid plans only.** The SDK stays plan-agnostic, as with message limits: the deployment decides per request.
Super and Haseef add `"Agent"` to the request's tools when `user.plan` is a paid one, the same place they count a
free plan's 14 messages. On a free plan the parent simply does the work itself.

## How a child runs

A child is `_run` again, with a stand-in context:

- **Workspace and user**: the parent's, so files, org gates (Sheets, Docs, Video) and the person's own settings apply.
- **Messages**: the brief only. The system prompt is the parent's (operator `system`, `AGENT.md`, skills), plus a
  short preamble: you are doing one part of a larger task; you can't ask the person anything; end with a report of
  what you did, the files you made (paths), and anything you're unsure of.
- **Tools**: the parent's list minus `Agent` (no grandchildren), `Ask` and `Suggest` (they need the person).
- **Connectors**: none in this version, so there are no approvals to forward.
- **Browser**: its own session, so two agents never browse in one tab.
- **Session**: in memory. Its steps and report are kept in the chat's agents record (below), so it reloads and opens.

A step that only started agents waits for the first report before the parent speaks again. In live tests the
parent, asked to report what its agents wrote, wrote it itself before they had: anything it says earlier is a guess.

### Background, and the run's inbox

The run gets an **inbox**. Two things land in it: a child's report, and a message the person sends while the run
is open. The loop drains it before each model call. When the parent ends its turn while children are still working,
the run doesn't end: it waits on the inbox, streaming the children's progress, and wakes the parent when something
arrives. The run ends when the parent has ended its turn, no child is working, and the inbox is empty.

- A **report** goes into the parent's log as an internal user message, framed as data, never instructions:
  `<agent-report id="a1b2c3" label="…" status="done">…</agent-report>`. The chat hides it; the team card shows it.
- A **message from the person** (not built yet) while the run is open goes to the inbox instead of today's client-side queue (which
  holds it until the run ends). Children may run for minutes; the person should be able to keep talking. Stored at
  `chat/{id}/inbox/{ts}` so it reaches the run whichever instance took the request; the run lists it at each drain
  and every 2 s while it waits.
- **Stop** (the composer's) stops the whole run, children included. A row's Stop stops one child; the parent gets a
  report saying the person stopped it.

### Limits

- **4 at once** per chat. A fifth call is refused: `4 agents are already working. Start this one after a report
  arrives.`
- **No nesting**: a child has no `Agent` tool.
- **One budget**: the run's 45 minutes covers the parent and every child. At the limit everything stops, as today.
- **One message**: the person's request counts once toward a plan's limit; children and report turns don't.

### Two agents, one file

Two agents editing one file at once is a bad practice, and every harness surveyed says so. Neither knows what the
other changed: each read the file at some point, made its own plan from that copy, and writes over the other's
work or contradicts it (a deck restyled twice, a sheet's columns moved under the other's formulas). Tools that check
for a stale copy, like Sheets' retry and a design's saved version, stop a lost write but not two plans pulling the
file apart. So one file has one owner at a time:

- **Split by file.** Each agent makes its own file or its own part (a section, a set of slides, a data sheet).
- **Combine after.** The parent merges the parts once the reports are in; it is the only one that has seen them all.
- **Or go in order.** When the second part depends on the first, the parent starts the second agent after the first
  report, telling it which file to build on.

The tool's description says this, and the run enforces it. The first agent to write a file holds it until it ends:
no one else, the parent included, writes it or reads it half made (`pricing.xlsx is being worked on by «Draft the
comparison sheet». Its report will arrive as a message; use another file meanwhile.`). It covers `edit`, `read`,
Design, Sheets and Docs; `bash` stays unguarded, and the tool description says so. An open Design or
Sheets editor shows a child's edits live, as it shows the parent's today.

## Gaps the code review found, and how they closed

1. **Progress.** A tool's events reach the chat only when its batch ends. The `agent` call returns at once, so no
   tool needs to stream: the parent's loop sends the team's changes while it streams, while tools run and while it
   waits (`tools/agent.py` `Team.drain`).
2. **Cost.** `state.add_cost` read, changed and wrote the chat index with no lock, so parallel agents lost updates.
   One writer now: a lock per chat. An agent's usage is logged with the chat id and its agent id.
3. **Storage.** One record per chat, `chat/{id}/agents`, by the call that started each agent: label, brief, status,
   times, steps, report. Turn readers glob `[0-9]*`, so they never see it, and deleting the chat removes it. A
   chat's load and poll return it as `agents`; an entry left by a regenerated reply matches no step and shows nowhere.

## The wire

Old clients and the mobile app keep working: they see the `Agent` call as an ordinary step.

- Launch: the usual `{type: "step", id, tool_name: "Agent", step: "<label>", ok: true}`.
- Progress, merged into that step by id (the web and mobile clients already `Object.assign` steps by id):
  `{type: "step", id, agent: {label, brief, status, started, ended?, steps, report?}}` where `status` is
  `working | done | failed | stopped`; a row's line is its last step.
- Reload: `to_ui_messages` fills `agent` on the step from the record, so a reloaded chat looks like the live one.

## The UI (option B)

One card per turn that started agents, where the first one was started:

- **Header**: `2 of 3 agents working · 1m 20s`, later `3 agents finished · 6m 04s`.
- **Rows**, the working ones first: status (working star, ✓, stopped, failed), the label, the latest line or the
  report's first line, elapsed time. Hover: Stop.
- **Click a row**: the side panel opens on that agent: what it was asked, its steps, its report, the files it made
  (the chat's file cards), and Stop while it works.
- The composer stays open while children work; a message sent goes to the run's inbox.
- In Arabic the labels and lines are the person's language; the card keeps the steps' rule (on the left).

Mobile follows in its own change: the same card from the same `agent` field.

## Phases

1. **Harness**: `emit`; the inbox and the idle wait; the `Agent` tool and the child runner; limits; file holds; the
   cost lock; storage, reload and regenerate; Stop per child. Mocked-loop tests for each, one live test.
2. **Web**: the team card, the side panel, the composer sending to the inbox, Arabic strings.
3. **Mobile**: the card and the inbox.
4. **Later**: message a child or continue a finished one with its context; agent types a developer defines (name,
   description, prompt, tools, model); approvals forwarded from a child to the chat; a fork that inherits the
   parent's conversation.

## The survey (2026-11-07)

Coding harnesses (Claude Code, Codex, Cursor, VS Code Copilot, Gemini CLI, OpenCode, Factory, Goose, Amp, Cline,
Roo, Kilo), SDKs (Claude Agent SDK, OpenAI Agents SDK, Google ADK, LangChain deepagents, CrewAI, Microsoft Agent
Framework, Pydantic AI, Mastra, Vercel AI SDK) and products (ChatGPT Work, Claude Research and Cowork Dispatch,
Gemini Deep Research, Perplexity, Manus, Kimi).

- **The tool** is nearly the same everywhere: a label for the UI, a self-contained brief, an optional agent type and
  model. Claude Code, Factory, OpenCode and VS Code have almost identical fields.
- **Context**: a fresh child with only its brief, and only its final text back. Forking the parent's history is
  opt-in (Codex v2 is the exception).
- **Types**: a read-only explorer and a general worker are built in almost everywhere; developers add their own as a
  small file (name, description, prompt, tools, model).
- **Limits**: depth 0 to 1 by default, 3 to 20 at once, one budget for the tree. Cost scales with children (about 5x
  for 5); every vendor warns against delegating small tasks and against two children editing one file.
- **Background**: Claude Code, OpenCode, Factory and Antigravity run children in the background and notify the
  parent; Codex gives the parent explicit wait tools; Cursor, Gemini CLI and VS Code wait.
- **UI**: a compact row per child in the parent's transcript (label, latest activity, status), detail on demand in a
  panel, tab or child session. Products for non-technical users group rows by state with "needs you" first (Cowork
  Dispatch, Claude's agent view, ChatGPT's Active and Done) and never stream several transcripts at once.
