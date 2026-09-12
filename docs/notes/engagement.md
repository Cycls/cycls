# Engagement — channels as plugins, our UI, decisions on the platform

**Problem.** Re-engagement pulls in three directions: channels (push, email —
each a vendor SDK with its own prompt, worker and opinions), decisions (*who*
to reach, *when*, with what — segments, flags, journeys), and things to say in
the product (what's new, tips, questions). Wire each vendor into the app
directly and the app grows a scheduler and a CMS it should never own — and
swaps vendors by rewriting call sites.

**Decision.** The SDK ships the UI and the plumbing; vendors are plugins on
the page config; every decision lives on the platform. There are four roles.
A role is filled by whichever vendor the operator configures; *built today*
is what ships now, the rest are examples of what a plugin for that role would wrap.

| role | the SDK's part | the platform's part | built today | fits as a plugin |
|---|---|---|---|---|
| **analytics + flags** — the brain | send canonical events; read flags as `{enabled, payload}`; set person properties | rollout, conditions, journeys, dashboards | PostHog (GTM as an events-only destination) | Amplitude, Mixpanel, LaunchDarkly, Statsig |
| **push** — a channel | our permission card; hand the subscription to the vendor; attach the user id | segments, sending, journeys | OneSignal | Firebase Cloud Messaging, Braze, Pusher Beams |
| **email** — a channel | nothing in the client | send from the events the brain already has | Resend, driven from PostHog | Customer.io, Loops, SendGrid |
| **surveys** — questions | render the questions in our strip; send the vendor's own events | authoring, targeting, reports | PostHog surveys | Sprig, Formbricks (API-driven surveys) |

```python
cycls.Web()
    .analytics(cycls.PostHog(), cycls.GTM("GTM-XXXXXXX", events=["sign_up", "purchase"]))
    .notifications(cycls.OneSignal("<app id>"))
```

No trigger logic in the app — no "after N messages" counters, no schedules.
A flag with conditions is that counter. The one rule the client keeps is a
floor: nothing is asked before the product has done something for the person
(one finished turn in this session), and nothing shows while the agent is
streaming, over an `ask` card, or once the person starts typing.

## How a plugin works

Two halves, one shape, no call-site edits:

1. **A spec class in the builder** (`cycls/_agent/web/builder.py`) —
   `cycls.PostHog(...)`, `cycls.GTM(...)`, `cycls.OneSignal(...)` — that
   validates its inputs and becomes `{provider, ...}` on the page config
   (`analytics: [...]`, `notifications: [...]`).
2. **A factory in the client** keyed by that `provider` name, returning an
   object with the capabilities the vendor has:

   - `client/src/lib/analytics.ts` — `send(event, props)`, and optionally
     `register`, `identify`, `reset`, `setPerson`, `flags {on(cb), get(key)}`,
     `surveys {on(cb), event(name, props)}`. The pipe fans `track()` out to
     every provider; `flagsProvider()` and `surveysProvider()` return the first
     provider that brings those.
   - `client/src/lib/notifications.ts` — `request()` (ask the browser through
     the vendor, so the token lands with them), `identify(id)`, `reset()`.

A LaunchDarkly plugin would implement `flags` on top of its client's
`variation()` and `on("change")`; a Firebase push plugin would implement
`request()` with `getToken()` after `Notification.requestPermission()`. The
UI never learns which one is there.

## Two surfaces, one queue each (client/src/components/surfaces.tsx)

- **Modal** — shows on load, once per id, in one of two shapes. A *feature*:
  one thing, the words on the start side (tag, title, body, button) and its
  image on the end side. A *digest*: What's new — title, an optional line, a
  list of `items` each with an optional image, title and body, one button.
  The shape follows the data: `items` makes a digest, otherwise a feature.
- **Corner** — one small card at a time at the bottom left, in both languages
  (the canvas and the side panel live on the right). Tips first, in payload
  order, then the push prompt. Each once per id.

Both render in the UI language, from the `_ar` fields when present.

### Push (client/src/lib/notifications.ts)

The browser only grants push after a person clicks something, and if its own
prompt is answered Block the site is blocked until they dig into settings. So
the corner card asks first, in our words, and the browser's prompt fires only
on Allow — through the vendor SDK, which is what makes the token land with
them (if the SDK fails to load, the browser's prompt still records the
answer). Not now rests the card 14 days. Settings shows *Turn on* for anyone
who changed their mind and *Blocked* with the hint when the browser said no.

When the card shows is the flags provider's call: the `notification_prompt`
flag's rollout and conditions decide who, its payload
`{ "immediate": true, "snooze_days": 0 }` lifts the floor or changes the
rest. Without a flags provider the card shows after the first finished turn
to anyone the browser hasn't asked yet.

The vendor SDK is lazy: nothing ships until a subscription is wanted — on
Allow, or on load for a user who already granted permission, so the
subscription stays attached to the account (`identify(user_id)` on sign-in,
`reset()` on sign-out).

*OneSignal specifics.* The server serves
`/push/onesignal/OneSignalSDKWorker.js` — a one-line import of the vendor
worker, because a service worker must come from the site's own origin —
scoped to `/push/onesignal/` so it never touches the page. Allow calls
`Notifications.requestPermission()`, sign-in `login(id)`, sign-out `logout()`.

### Announcements

The `announcements` flag's JSON payload is the list — the flag's rollout and
conditions target it (new accounts, one agent, a percentage, "not anyone with
`announcement_seen/<id>`"), and turning the flag off pulls everything. Any
flags provider that returns a payload works.

```json
[
  { "id": "apps-launch", "type": "modal", "tag": "New", "tag_ar": "جديد", "tag_color": "#FF5400",
    "title": "Apps", "title_ar": "التطبيقات",
    "body": "Build a small app and keep it in your workspace.", "body_ar": "…",
    "image": "https://…/apps.png", "cta": "Try it", "cta_ar": "جرّب", "url": "/?tab=apps" },
  { "id": "sep-release", "type": "modal",
    "title": "What's new", "title_ar": "الجديد",
    "cta": "Got it", "cta_ar": "تمام",
    "items": [
      { "title": "Apps", "title_ar": "التطبيقات",
        "body": "Build a small app and keep it in your workspace.", "body_ar": "…",
        "image": "https://…/apps.png" }
    ],
    "from": "2026-09-01", "until": "2026-10-01" },
  { "id": "tip-canvas", "type": "corner", "tag": "Tip",
    "title": "Watch it being written", "body": "The canvas opens while the agent works.",
    "image": "https://…/canvas.png", "cta": "Try it", "url": "/?open=site.html" }
]
```

`id` and `title` are required; `type` is `modal` or `corner`; `tag` is a small
label above the title on any card, and `tag_color` (hex, `rgb()`/`hsl()`, or a
CSS color name — a color, never a stylesheet) paints it, with the text picked
dark or light to stay readable; `from`/`until` are optional ISO dates;
`immediate: true` on a corner card skips the floor; `url` makes the button a
link (external opens a new tab). Seen ids live in the browser and on the
person as `announcement_seen/<id>` (through `setPerson`, so any analytics
provider that keeps person properties can target on it).

### Surveys (client/src/components/survey-strip.tsx)

The survey is authored and targeted on the platform; the first one the
surveys provider returns renders as a quiet strip above the composer, in the
follow-up chip's family: the question in muted text, the options as small
pills, an ×. One question at a time; rating (numbers or an emoji scale),
single and multiple choice, open text; links are skipped.

The survey shape the strip renders is PostHog's (`Survey` in
`lib/analytics.ts`); another vendor's plugin maps its own into it. Events go
through the provider's `event()` in the vendor's own vocabulary so its
reports work unchanged — for PostHog: `survey shown`, `survey sent`
(`$survey_response_<question id>` per answer, `$survey_questions`,
`$survey_completed`, `$set $survey_responded/<id>`) and `survey dismissed`.
They are not canonical events on the pipe. `seenSurvey_<id>` in localStorage
keeps a survey from returning.

*PostHog specifics.* Author the survey with presentation **API** so PostHog's
widget stays out of the page; `getActiveMatchingSurveys` still applies all of
its targeting (conditions, flags, wait periods).

## Events on the pipe

`notification_prompt_shown{placement}` / `notification_prompt_answered{placement, result}`
(placement `corner`, or `settings`; result `allowed` / `denied` / `dismissed`),
and `announcement_shown` / `announcement_clicked` / `announcement_dismissed`
`{id, type}` — the contract lives in docs/notes/analytics.md.
