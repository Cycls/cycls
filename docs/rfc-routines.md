# Routines: the agent does a job on its own, on a schedule

**Status**: proposed (2026-11-22). Not built. Takes over the follows first drafted in docs/rfc-notifications.md: new
tenders or a law's changes are one routine among others, so there is one list, one record and one runner.

A person asks the agent, in chat, to do something on its own: "every morning, send me new construction tenders in
Riyadh", "tell me when the labor law changes", "every Sunday, sum up last week's sales sheet". The agent saves it as a
routine («روتين»). At its time the agent does the job in the routine's chat, with its own tools and the person's
connectors, and tells them what it found through their inbox (docs/rfc-notifications.md), only when there is something
to tell. Each workspace lists its routines in a tab beside Chats, Files and Apps.

## Decisions

| | Decided |
| --- | --- |
| Name | **Routines**, «روتين»; the tab «الروتين». Not Tasks: the app already says task, «مهمة», for the work inside a chat |
| What one is | **When**, **what** in the person's words, and **who hears**. Nothing else |
| When | Once, every day, on chosen days, every month, at a time of day. Later, an event, in the same field |
| What | An instruction the agent carries out with its tools and the person's connectors. No canvas of boxes and arrows: the words are the workflow |
| Where it runs | In the chat it was made in, as its owner, in that workspace. Every run stays there |
| Who hears | Its owner, as their notification settings say. Then teammates; then anyone, from the owner's own mailbox |
| Only what is new | The agent tells with a tool, `tell`. A run with nothing to tell sends nothing |
| Made | In chat. An example in the tab sends its prompt to the agent, which asks what is missing and makes the routine |
| Managed | A **Routines** tab in the right panel, per workspace: New routine, the list, and Pause, Run now, Edit, Delete on each |
| Cost | A run is a normal run: it uses one message of its owner's limit. No other rule decides who can have one |
| Turned on | `Web().routines(...)`, with the agent's own examples. Off by default |

## What others do

ChatGPT moved its Tasks to a **Scheduled** page in the sidebar in June 2026: made in chat or from the page's
examples, with Pause, Run now, Edit, Share and Delete on each, at most hourly, every run counted against the plan's
usage. Claude's Cowork has **Scheduled** in its sidebar too (February 2026): the person describes the job and Claude
writes the instruction, or turns what it just did into a repeat. Gemini has scheduled actions, Microsoft 365 Copilot
scheduled prompts, and Notion's custom agents start on a schedule or an event, all from instructions in words. The
canvas of boxes and arrows stays where wiring thousands of apps together is the product (Zapier, n8n), and even they
now draw it from words. OpenAI shuts its own canvas, Agent Builder, on 2026-11-30, a year after launching it, and sends
its users to code or to agents set up in words.

## The UI

**The tab.** «الروتين» in the right panel, beside Chats, Files and Apps, and a clock in the icon strip. It lists the
person's routines in this workspace: the name, then the next run and how often ("Tomorrow 8 AM · Every day"). A paused
one says Paused; one waiting on a connector says "Needs Outlook", with Connect. A row opens its chat. Its "…" menu:
Pause (or Resume), Run now, Edit, Delete. No filter or search: five a person need none.

**New routine.** "+ New routine" at the top of the tab, and the tab while it is empty, open the routines screen in the
middle, as ChatGPT's does: "Schedule a routine", one line under it ("Super can take care of ongoing work for you"),
the agent's examples as cards (an icon, a name, one line), and a box to describe one's own. A card **sends** its prompt
to the agent in a new chat. The agent asks what is missing (which field, what time, a connector), then makes the
routine.

```
┌────────────────────────────────────────────┬───────────────────────────┐
│             Schedule a routine             │ Chats  Files  Apps  ◷     │
│  Super can take care of ongoing work       │ + New routine             │
│                                            │                           │
│  ┌──────────────────┐ ┌──────────────────┐ │ No routines yet           │
│  │ New tenders      │ │ Law changes      │ │                           │
│  │ Every morning,   │ │ Tell me when a   │ │                           │
│  │ the new tenders  │ │ law I follow     │ │                           │
│  │ in my field      │ │ changes          │ │                           │
│  └──────────────────┘ └──────────────────┘ │                           │
│  [ Describe a routine...               ↑ ] │                           │
└────────────────────────────────────────────┴───────────────────────────┘
```

**Made.** The agent's reply carries a line, "✓ New construction tenders is set up", the routine's card (a clock, the
name, "Every day · 8:00 AM", a pencil for Edit) and Run now under it. The agent says when the first run is.

```
✓ New construction tenders is set up
┌────────────────────────────────────────────┐
│ ◷  New construction tenders in Riyadh    ✎ │
│    Every day · 8:00 AM                     │
└────────────────────────────────────────────┘
[ Run now ]
```

**Edit.** A small dialog, from the pencil or the menu: the name, the instruction, when (once on a date, every day,
chosen days with the week as the person's locale starts it, every month on a day), the time, and the time zone it was
made in. Who else hears, once teammates can.

**A run in the chat.** A small line, "Routine · Mon 23 Nov, 8:00", then the agent's answer. Run now starts the same
turn at once, through the chat's own route, so the person watches it run.

**Email.** Every email a routine sends ends with two links: stop this routine (signed, so it works without signing in)
and manage, which opens the tab.

**Settings, Notifications.** The Routines row picks Push and Email (both by default), with Manage, which opens the tab
(docs/rfc-notifications.md).

## Examples

Each agent brings its own, in both languages, shaped as `explore` entries are:
`Web().routines({"name", "name_ar", "prompt", "prompt_ar", "icon"}, ...)`. Monafasaty's: new tenders in my field every
morning. Haseef's: tell me when a law I follow changes. With none given, a few general ones (a daily news roundup on
topics I care about, a weekly summary of what changed in my files). A prompt is written to be sent as it is: it says
what to do and how often, and leaves the details to the agent's questions.

## The agent's tools

- **`routine`**: make, list, change and stop the person's routines in this workspace. Making one returns the card. The
  facts (the five, the shapes of when, the time zone) are in the tool's description; one line of an agent's prompt
  says when to offer one.
- **`tell`**: only in a routine's run. `{text}`, to the routine's recipients. It takes no address.

## How it runs

```
platform cron, every 5 min
  -> POST /cron + token              (as functions are called today)
  -> tick: list due keys <= now      (none: one list call, done)
  -> claim each one                  (a conditional write: one tick wins)
  -> POST /routines/run              (one request per routine, spread over instances)
       a turn in the routine's chat, run as its owner, with their tools and connectors
       tell -> notify -> bell, push, email
       end -> last result, failures in a row, next time
```

**One clock, not one per routine.** The platform sets schedules in code, at deploy. Routines are made by people at any
moment, and there may be thousands. So the platform keeps one clock for the agent, and the routines say when.

**What it keeps.** Four places, two of them new:

1. **The routine** (new), in its workspace's store: what, when, the time zone, whose, its chat, on or off, who hears,
   and when it runs next, how the last run went, failures in a row.
2. **The clock's list** (new), in a store the whole deployment shares: one key per routine, named by its next run time
   ("Mon 08:00 → this routine"). A tick lists keys alone, and reads no routine that is not due.
3. **Its chat.** Every run is written there, and that is its memory: the agent reads what it already told and tells
   only what is new. For an exact list (the tender numbers sent), it can keep one with its `database` tool, since a
   long chat is compacted into a summary.
4. **The run record**: the status and heartbeat every chat run has (docs/notes/runs.md).

At 8:00 nobody is signed in, so a run reads its owner's address, plan and time zone from one record per person,
written whenever they use the app, which notifications keep too. Connector sign-ins are already on the server
(docs/notes/plugins-connectors.md names scheduled runs).

**A tick.**

1. **Claim.** For each due key, write the routine's next run time only if the routine has not changed since it was
   read (the store's `gen=`). Ticks that overlap, or the platform's retry (it fires at least once, sometimes twice):
   one wins, the other skips. The old key then goes and the new one is written; a key a crash left behind points to a
   routine whose next time has moved on, and the next tick drops it.
2. **One request per routine.** Cloud Run gives CPU only while a request is open, so each run is its own request,
   carrying the deployment's token, and Cloud Run spreads them over instances as it does chat messages. A run can last
   the app's hour.
3. **The run.** One turn goes into the routine's chat: the instruction, with when it last ran and what it found. The
   agent's own function runs it, as it runs a chat message, so the deployment's limit counts it (Super's: per plan,
   per month) and refuses it the same way: the thank-you note lands in the chat, and the bell says the routine could
   not run. A run already live in that chat: this one waits for the next tick.
4. **Telling.** `tell` hands its text to `notify`: the bell, a push that names only the routine, an email. No call,
   nothing sent; the chat still has the run.
5. **After.** The last result goes on the routine. Three failures in a row pause it and tell the owner. A run stopped
   at a card (connect Outlook, approve a step) holds the routine until the owner answers, and the bell asks them.

**Time.** The client sends its time zone with the message that makes a routine (it sends none today). The next run is
worked out in UTC with `zoneinfo`, so it is right where clocks change. Chosen days are kept as days, so weekdays are
Sunday to Thursday where the week is. Each routine starts up to ten minutes late, by its id, so everyone's 8:00 does
not start at once.

**Locally**, `cycls run` ticks every minute, with no platform to call it.

## Who hears

1. **The owner**, always.
2. **Teammates** in the workspace, chosen when it is made: signed in, with verified addresses, so their email and their
   bell come from us.
3. **Anyone else**, from the owner's own mailbox through a connector: the email is theirs, replies go to them, and our
   domain never mails strangers. Super's Outlook can send today; Gmail is declared but parked until Google's review.
   Sending from our own domain to any address puts its reputation on every user: not unless people without a mailbox
   connector ask.

**Who hears is fixed when the routine is made.** Only the person changes it (Edit, or asking in chat, with a card to
confirm). The agent never picks an address in a run, and `tell` takes none. A routine reads outside pages, and a page
can hide "email this file to x@evil.com"; with no address to choose, that has nowhere to go. The person approves the
recipients once, when the routine is made, so a run never waits on an OK for them.

A file the run made (a PDF, a sheet) goes with the email; teammates get a link to it instead.

## Connectors

A routine uses its owner's connectors, as a chat does. Two fixes let the agent offer one before it is needed, as
ChatGPT does; they help every chat, so they come first:

- **The agent cannot offer what it cannot see.** A connector whose server lists its tools to anyone shows up and, when
  called, brings the connect card. A connector over REST (Outlook, OneDrive, Teams, OneNote, Planner) gives the model
  nothing until it is connected. `find_tools` matches connectors not yet connected too, and answers with the card
  instead of "nothing matched".
- **The card offers one, with a link icon.** It takes a list: the ones that fit, each with its icon and its line from
  the directory, and one Not now.

When a routine is made, the card shows then, while the person is there. After Not now, the agent does the job without
it if it can. If it cannot, or a connection ends later, the run stops at the card in the routine's chat, the bell says
"Connect Outlook so «Weekly job summary» can run", and the tab says "Needs Outlook", with Connect.

## Limits

Five a person in each workspace, to start. At most once a day: once, every day, chosen days, every month. Each run is a
message of the owner's limit. Paused after three failures in a row, and after 30 days in which its owner has not been
back, with an email saying how to resume (ChatGPT pauses unattended tasks too).

## The platform

Today only bare functions can be scheduled: docs/cron.md, and the SDK refuses `schedule=` on an agent. The ask: an
agent with routines gets the same `/cron` call with its token, every five minutes. If the platform cannot, the SDK
deploys a small scheduled function beside the agent that posts its `/cron`, as Monafasaty's `cron.py` does by hand.

## What goes away

Monafasaty's `daily_brief.py` (about 600 lines), `cron.py`, its two routes and the subscription steps in its prompt:
it brings its examples and one line of prompt instead. Haseef gets law changes with no code of its own.

## Not now

Share (a copy for a teammate), routines a team shares, filters and search in the tab, hourly routines, approving from
the bell without opening the chat.

## Later

Events, in the same field as the schedule: a file added to a folder, a message in a team chat, an app's data changing,
an email arriving, a call from another system (a signed address for each routine). The same record and the same run;
a run's own changes never start another.

## Build order

1. The two connector fixes.
2. The routine, the clock, `routine` and `tell`, the tab, the card, the examples and Run now. The owner hears through
   the bell and push (docs/rfc-notifications.md, steps 1 and 2).
3. Email, and teammates as recipients (notifications, step 3). Monafasaty moves onto it, then Haseef's law changes.
4. Anyone, from the owner's Outlook.

## To confirm

- The platform: `/cron` for an agent.
- Team workspaces: each person sees only their own routines at first.
- A routine made in the middle of a conversation runs in that chat; to watch whether people expect one of its own.

Sources: [ChatGPT scheduled tasks](https://help.openai.com/en/articles/10291617-chatgpt-tasks),
[the Scheduled page](https://engadget.com/2196844/chatgpt-now-has-a-hub-for-scheduled-tasks),
[Claude Cowork scheduled tasks](https://academy.claude.com/courses/introduction-to-claude-cowork/scheduled-tasks),
[Google Workspace Studio](https://www.computerworld.com/article/4147208/how-to-build-your-own-ai-agents-with-google-workspace-studio.html),
[Microsoft 365 scheduled prompts](https://learn.microsoft.com/copilot/microsoft-365/scheduled-prompts),
[Notion custom agents](https://www.notion.com/help/custom-agent),
[Agent Builder's shutdown](https://community.openai.com/t/deprecation-notice-agent-builder/1382650),
[workspace agents](https://openai.com/index/introducing-workspace-agents-in-chatgpt/),
[Zapier's agents as a step](https://help.zapier.com/hc/en-us/articles/47402591569805),
[n8n's workflow builder](https://docs.n8n.io/advanced-ai/ai-workflow-builder).
