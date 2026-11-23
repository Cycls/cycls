# Notifications: one inbox per person, a push when they are away, email when they choose it

**Status**: proposed (2026-11-19), revised 2026-11-22: what a person follows became routines (docs/rfc-routines.md),
and Settings gets a Notifications tab with a picker for each kind. Revised 2026-11-23: no provider is a dependency. We
keep each person's devices and push to them by the standards (Web Push in a browser, APNs and FCM on a phone), and
email goes over SMTP. Steps 1 and 2 built, on the testbed, through OneSignal; the rest waits.
Built beside it, because a notification needs it: replies in team chats (a reply tells the person it answers, as an @
does), and each team turn led by its author when the model reads it (it used to follow the turn, so a run of turns read
each name as the next one's).

A person hears about what happened to them in one place, whichever workspace it happened in: a bell in the app with
everything that concerns them, a short sound while the app is open, a push when it is not, and an email for what they
choose, their routines' findings by default. Each notification is one record in the person's inbox; push and email
are two ways of delivering that same record.

## Decisions

| | Decided |
| --- | --- |
| Where notifications live | **One inbox per person**, across all their workspaces. Each item says which workspace it came from |
| What notifies | A mention (@you, @all), a reply to your message, your task ending while you were away, a routine with something to tell you or that could not run |
| What does not | A plain new message: it stays an unread count on the chat |
| In the app | A bell with a count, the list, the count in the tab's title, and **a short sound** while the app is open |
| Settings | A **Notifications** tab: push on this device, Sounds, and a row for each kind with a picker: Push, Email, both, or off |
| Defaults | Mentions and replies: Push. Finished while you were away: Push. Routines: Push and Email |
| The bell | Keeps everything, whatever the picker says. The picker only chooses what reaches you outside the app |
| Devices | **Kept by us**, one list per person (not per organization): a device is added when they allow notifications on it, and dropped when they turn them off there or a send says it is gone |
| Push | **By the standards**, sent by our server: a browser by Web Push (VAPID), an iPhone by APNs, an Android phone by FCM. Each sender is a plugin, so no provider is a dependency |
| What a push says | **Who and what** ("Omar mentioned you"), never the message: a lock screen is seen by others, and the rest is in the bell |
| Email | **Over SMTP**, the standard every provider speaks, so changing provider is a setting. Routines by default; mentions and replies offered, off until the person turns them on |
| The email address | The verified sign-in address, never one typed in chat |
| Read | Opening the bell reads everything in it; opening a chat, on any device, reads what it has about that chat |
| Kept | The newest 30: a bell shows what is recent, and the chats keep the rest |
| Already there | A mention waits 10 seconds; whoever has read the message by then had the chat open, and is not told |

## What exists today

- **Push**: `Web().notifications(cycls.OneSignal(app_id))` gives the permission card and the subscription. The web
  client and the phone app log in to OneSignal with the person's sign-in id, and the phone opens the `path` a push
  carries. OneSignal keeps the list of each person's devices: that is what this revision takes back.
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

- writes one item into each person's inbox: a `.inbox` shelf under `{org}:{person}`, the newest 30 kept, each
  `{kind, by, text, ws, link, at}`;
- delivers it as each person's picker says for that kind:
  - **push**: to each of their devices (below), each by its kind's sender, with no wait on it: the words in the
    device's language, where it opens, and the item's id as its tag, so a retry never shows twice;
  - **email**: below;
- never fails its caller: a delivery that fails is logged.

Each person's picks and address are one record on the server, since a delivery happens while they are away: the picks
written when they change one, the address from their sign-in whenever they use the app. Routines read the same record.

It is called from three places that already know the moment:

1. A team message that mentions someone or replies to them (`server.py`, where mentions are worked out). Everyone named,
   @all as every member, and whoever wrote the message replied to; never the sender. It waits 10 seconds beside the
   message: an open team chat looks every 3 and records that its member read it, so whoever has read it by then is
   not told.
2. `_finish`, when nobody was watching the run end: its owner hears it is done, has a question for them, needs their OK,
   or failed.
3. A routine: its run's `tell`, or a run that could not start or waits on its owner (docs/rfc-routines.md).

Routes: `GET /inbox` (the items and the unread count), `POST /inbox/seen` (the bell was opened, or with `{chat}` that
chat is in front of them), and `GET` and `PATCH
/notifications` (the picks). The app reads `GET /inbox?limit=1` every 15 seconds while it is in view: the count, and the
newest, to know whether to sound. The chat list is read that often only in a team workspace, and the inbox covers
every one.

**In the app**: the bell in the top bar beside search, on a desktop and a phone, and like search it covers every
workspace. A click opens that chat in its own workspace. A new item while the app is open plays one short sound,
unless it is the chat in front of them. A page cannot play sound before the person has clicked or typed in it once;
then only the count shows.

**Settings.** Notifications becomes its own tab, a row for each kind, each with a picker, on a desktop and a phone:

```
Push on this device                       [On]
Sounds                                    [On]
Mentions and replies                  [Push ▾]
Finished while you were away          [Push ▾]
Routines · Manage              [Push, Email ▾]
```

The push switch is the row General had. Sounds is kept on the device. Manage opens the Routines tab. A kind's row
comes with the deliveries it chooses between: push from the server, then email.

**One sound at a time**: while the app is open and in view our sound plays and the push makes none: a browser must show
every push, so the service worker shows it silently and closes it at once, and the phone app tells the system not to
show it while the app is in front. When the app is not in view, the push brings the browser's or the phone's own sound.

## Devices

Each person's devices are one record, `devices`, in their own store (`{person}/.inbox`), not an organization's:
whichever organization they are in when they allow notifications, a push from any of them reaches the same devices.
Each is `{id, kind, address and keys or token, lang, added}`:

- a **browser**: the page asks permission, registers the app's service worker, subscribes it with our VAPID public key,
  and sends the subscription (an address at the browser's push service and two keys) to `POST /devices`;
- a **phone**: the app asks permission and sends its token (APNs on an iPhone, FCM on Android) to `POST /devices`.

Only the signed-in person adds their own devices, so no one can receive another's pushes. `DELETE /devices/{id}` when
they turn push off on that device or sign out there, and a send the push service answers with gone (404, 410) drops
it. The newest 10 are kept.

Senders are plugins, one for each kind of device: `Web().notifications(cycls.WebPush(), cycls.APNs(...),
cycls.FCM(...))`. Web Push needs no provider at all: the message is encrypted to the browser's keys and signed with
our VAPID key (a key pair kept as server secrets, its contact the app's own address). A phone's goes through Apple's and
Google's own services. A relay (Expo's, OneSignal's) could stand in for APNs and FCM behind the same interface.

## Email

One more delivery inside `notify`, for the kinds a person picked it for, through a plugin:
`Web().email(cycls.SMTP(host, user, password, sender))`. SMTP is the standard every email provider speaks (Resend, SES,
Postmark, Google Workspace), so changing provider is changing these settings, and the sending domain's DNS records
(SPF, DKIM) for the new one. It goes to the verified sign-in address. Clerk's default session token carries no
email, so one short claim is added in its dashboard (Sessions, Customize session token):
`"eml": "{{user.primary_email_address}}"`, and `User` reads it, as it reads `nam` and `img`. An email says who and
what, links to the item, and ends with a link that turns that email off (signed, so it works without signing in) and
one to Settings.
A routine's email ends with its own two: stop this routine, and manage. Each email carries the standard one-click
unsubscribe headers (`List-Unsubscribe`, `List-Unsubscribe-Post`, RFC 8058), which Gmail and Yahoo require of anyone
sending in bulk. A provider reports bounces in its own way, so stopping mail to an address that no longer exists is one
small hook per provider, later.

## Not now

Digests of a chat's activity, an "every message" choice for team chats, muting a chat, comments on a design, files
shared with you, workspace invites, SMS and WhatsApp, and an API for a deployment to send its own.

## Build order

With routines', in one order: docs/rfc-routines.md, Build order.

1. The inbox, `notify`, the bell, the sound and the Notifications tab, for mentions and replies.
2. Push from the server, and a task that ended while its owner was away. Built through OneSignal.
3. Our own devices and Web Push: the browser's subscription to `POST /devices`, the service worker, `cycls.WebPush`.
   Browsers leave OneSignal; the phone stays on it until step 5.
4. Email over SMTP: routines (docs/rfc-routines.md), and mentions and replies for those who turn it on.
5. The phone app: its token to `POST /devices`, `cycls.APNs` and `cycls.FCM`. OneSignal goes.

## To confirm

- Cycls Auth: the same `eml` claim.
- An iPhone receives Web Push only from a site added to its Home Screen (iOS 16.4 and later); the app is the way there.
- For step 5: an APNs key from Apple's developer account, and a Firebase project for FCM.

Sources: [Web Push (RFC 8030)](https://www.rfc-editor.org/rfc/rfc8030),
[VAPID (RFC 8292)](https://www.rfc-editor.org/rfc/rfc8292),
[message encryption (RFC 8291)](https://www.rfc-editor.org/rfc/rfc8291),
[one-click unsubscribe (RFC 8058)](https://www.rfc-editor.org/rfc/rfc8058),
[APNs](https://developer.apple.com/documentation/usernotifications/sending-notification-requests-to-apns),
[FCM HTTP v1](https://firebase.google.com/docs/cloud-messaging/send-message).
