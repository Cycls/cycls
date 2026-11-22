# Notifications: one inbox per person, a push when they are away, email when they choose it

**Status**: proposed (2026-11-19), revised 2026-11-22: what a person follows became routines (docs/rfc-routines.md),
and Settings gets a Notifications tab with a picker for each kind. Not built. Built beside it, because a notification
needs it: replies in team chats (a reply tells the person it answers, as an @ does), and each team turn led by its
author when the model reads it (it used to follow the turn, so a run of turns read each name as the next one's).

A person hears about what happened to them in one place, whichever workspace it happened in: a bell in the app with
everything that concerns them, a short sound while the app is open, a push when it is not, and an email for what they
choose, their routines' findings by default. Each notification is one record in the person's inbox; push and email
are two ways of delivering that same record.

## Decisions

| | Decided |
| --- | --- |
| Where notifications live | **One inbox per person**, across all their workspaces. Each item says which workspace it came from |
| What notifies | A mention (@you, @all), a reply to your message, your task ending while you were away, a routine with something to tell you |
| What does not | A plain new message: it stays an unread count on the chat |
| In the app | A bell with a count, the list, the count in the tab's title, and **a short sound** while the app is open |
| Settings | A **Notifications** tab: push on this device, Sounds, and a row for each kind with a picker: Push, Email, both, or off |
| Defaults | Mentions and replies: Push. Finished while you were away: Push. Routines: Push and Email |
| The bell | Keeps everything, whatever the picker says. The picker only chooses what reaches you outside the app |
| Push | **OneSignal**, already on the web and the phone with the sign-in id as the person's id. Sent by our server |
| What a push says | **Who and what** ("Omar mentioned you"), never the message. Anyone can claim a person's OneSignal id from a browser (below) |
| Email | Routines by default. Mentions and replies are offered, off until the person turns them on |
| The email address | The verified sign-in address, never one typed in chat |
| Read | Opening the bell reads everything in it |

## What exists today

- **Push**: `Web().notifications(cycls.OneSignal(app_id))` gives the permission card and the subscription. The web
  client and the phone app log in to OneSignal with the person's sign-in id, and the phone opens the `path` a push
  carries. Nothing sends one from our server: only campaigns from OneSignal's dashboard.
- **Mentions**: a team chat's meta keeps who was named and when (`mentions`), and the chat list already says "mentioned
  since you last read". A reply now adds the person it answers there too.
- **Runs**: `_finish` is the one moment a run ends, and `run.attached` says whether anyone was still watching.
  `Web().on_run(fn)` stays the deployment's own hook.
- **Settings**: one row under General, the push permission.
- **Engagement** (docs/notes/engagement.md): who to reach with marketing, and when, is the platform's. This RFC is the
  other half: something happened that concerns a person, which only the app knows.
- **Alerts**: the tenders agent (Cycls/Etimad-tenders, "Monafasaty") emails a daily brief with its own code. Routines
  replace it (docs/rfc-routines.md).

## The shape

`notify(people, kind, text, link)`, on the server:

- writes one item into each person's inbox: a `.inbox` shelf under `{org}:{person}`, the newest 100 kept, each
  `{kind, by, text, ws, link, at}`;
- delivers it as each person's picker says for that kind:
  - **push**: one OneSignal call for all of them, with no wait on it: `POST https://api.onesignal.com/notifications`,
    `include_aliases: {external_id: [...]}`, `target_channel: "push"`, `contents` in English and Arabic (OneSignal
    picks by the device's language), the `path` in `data` for the phone, a `web_url` for the browser, and the item's id
    as the `idempotency_key`, so a retry never sends twice. Needs one server secret: OneSignal's REST key;
  - **email**: below;
- never fails its caller: a delivery that fails is logged.

Each person's picks and address are one record on the server, since a delivery happens while they are away: the picks
written when they change one, the address from their sign-in whenever they use the app. Routines read the same record.

It is called from three places that already know the moment:

1. A team message that mentions someone or replies to them (`server.py`, where mentions are worked out). Everyone named,
   @all as every member, and whoever wrote the message replied to; never the sender.
2. `_finish`, when nobody was watching the run end: its owner hears it is done, has a question for them, needs their OK,
   or failed.
3. A routine's run with something to tell: its `tell` tool (docs/rfc-routines.md).

Routes: `GET /inbox` (the items and the unread count), `POST /inbox/seen` (the bell was opened), and `GET` and `PATCH
/notifications` (the picks). The count rides on the chat list the client already reads every 15 seconds, so nothing
new connects.

**In the app**: the bell at the top of the sidebar on a desktop, in the workspace section of the menu on a phone. A click
opens that workspace and that chat at the message. A new item while the app is open plays one short sound, unless it is
the chat in front of them. A page cannot play sound before the person has clicked or typed in it once; then only the
count shows.

**Settings.** Notifications becomes its own tab, the same shape as ChatGPT's (a row for each kind, each with a picker),
on a desktop and a phone:

```
Push on this device                       [On]
Sounds                                    [On]
Mentions and replies                  [Push ▾]
Finished while you were away          [Push ▾]
Routines · Manage              [Push, Email ▾]
```

The push switch is the row General has today. Sounds is kept on the device. Manage opens the Routines tab.

**One sound at a time**: while the app is open the push is hidden and our sound plays; when it is closed, the push brings
the phone's or the browser's own. The phone SDK hides a push with `foregroundWillDisplay` and `preventDefault()`. The web
SDK has the event but does not document hiding: to try first. If it cannot, the server skips the push for anyone whose
app read the chat list in the last 30 seconds.

**Why a push says so little**: OneSignal's identity check (a token our server signs for `login`) works only on its native
iOS and Android SDKs, not on the web or React Native, which are ours. So a person can claim another's id from a browser
and receive their pushes. A push names who and what, and the rest is behind sign-in, in the bell. To carry more later:
the client hands its subscription id to our signed-in server, which sends to those ids instead of to the person's id.

## Email

One more delivery inside `notify`, for the kinds a person picked it for, through a plugin:
`Web().email(cycls.Resend(...))`. It goes to the verified sign-in address. The token must carry `email` (Clerk: the
session token's template), and `User` reads it, as it reads the name and picture. An email says who and what, links to
the item, and ends with a link that turns that email off (signed, so it works without signing in) and one to Settings.
A routine's email ends with its own two: stop this routine, and manage.

## Not now

Digests of a chat's activity, an "every message" choice for team chats, muting a chat, comments on a design, files
shared with you, workspace invites, SMS and WhatsApp, and an API for a deployment to send its own.

## Build order

1. The inbox, `notify`, the bell, the sound and the Notifications tab, for mentions and replies.
2. Push from the server, and a task that ended while its owner was away.
3. Email: routines (docs/rfc-routines.md), and mentions and replies for those who turn it on.

## To confirm

- OneSignal's web SDK: whether a page that is open can hide a push (`foregroundWillDisplay`).
- Clerk: the session token carrying the email, and the same claim from Cycls Auth.
- Email for mentions and replies: offered and off by default (proposed), or push only.

Sources: [OneSignal identity verification](https://documentation.onesignal.com/docs/en/identity-verification),
[sending with the API](https://documentation.onesignal.com/docs/en/server-sdk-reference),
[web SDK reference](https://documentation.onesignal.com/docs/en/web-sdk-reference),
[mobile SDK reference](https://documentation.onesignal.com/docs/en/mobile-sdk-reference).
