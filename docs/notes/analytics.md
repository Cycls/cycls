# Analytics — one pipe, plugin providers, the event contract, and queries

## Architecture

One canonical event stream; destinations are plugins; routing is config.
Call sites only ever call `track()` (`client/src/lib/posthog.ts`) — it
enriches once and fans out to the providers the operator configured:

```
track("sign_up", props)                ← canonical names, ONE schema
        │
   [enrich once: agent_name, agent_domain, theme, language]
        │
   [route: per-provider event allowlist]
        ├──► posthog plugin   (product analytics)
        ├──► gtm plugin      (dataLayer.push — same names, verbatim)
        └──► future: mixpanel / amplitude / webhook / server-side sink
```

Configured from the builder — providers are config objects, like auth:

```python
cycls.Web().analytics(True)                      # shorthand: PostHog defaults
cycls.Web().analytics(
    cycls.PostHog(),                             # everything
    cycls.GTM("GTM-XXXXXXX", events=[            # marketing subset only
        "sign_up_start", "sign_up", "first_agent_use",
        "checkout_start", "purchase"]),
)
```

Rules of the pipe:

- **Names never bend to a destination.** A provider that wants different
  names owns that mapping in its own tool. We adopted GA4-conventional
  names for the funnel events (`sign_up`, `checkout_start`, `purchase`) so
  in practice nothing needs mapping anywhere.
- **Adding a destination = one plugin factory** in `PLUGINS`
  (lib/posthog.ts) + a provider class in the builder. Zero call-site edits,
  ever.
- **Every event is a small API**: rename a feature or move a button and a
  dashboard silently flatlines. Update this page in the same commit that
  touches a call site.
- **Properties are ids and enums, never content** — no prompts, titles, or
  emails on events (identify carries person fields separately).
- Client-side loses ~10-20% to blockers. Directionally sound; never
  reconcile against billing. The server's `usage` / `tool_call` logs are
  the authoritative record of turns and tools.

### The GTM provider specifically

- `cycls.GTM("GTM-…")` injects the container script server-side into every
  page (id shape-checked — it's inlined into a script tag). No container →
  no `window.dataLayer` → the plugin no-ops. One container serves every
  agent plus the marketing site (installed there by hand).
- Page views need no code: GTM's built-in **Page View** trigger fires on
  every load, and the container only exists on agent pages — that IS
  `agent_open`.
- The agency owns everything inside GTM: GA4 tags reading the events
  verbatim, Google Ads conversions on `purchase`, and the
  cycls.com ↔ cycls.ai **cross-domain linker** (ads land on .com, checkout
  happens on .ai). `purchase` is account-level (one subscription unlocks
  all agents) and attributed to the agent-domain of conversion;
  `transaction_id` dedupes double-fires.

### Schema hygiene

- **`$`-prefixed events** (`$pageview`, `$pageleave`, `$identify`, `$set`,
  `$feature_flag_called`, `$survey_shown`…) are PostHog's own — the SDK
  emits them, they carry the PostHog icon, and they are not part of this
  contract. Everything else is ours.
- **PostHog owns any fact its SDK already observes** — page views,
  identity/session, flag evaluations, surveys. We own product facts it
  cannot know. A custom event that mirrors a `$` event is a duplicate by
  definition: there is no `agent_open` (that's `$pageview`) and no
  sign-in event (that's `$identify`). The contract test denylists the
  usual mirrors. If a *destination* ever needs one of those facts (say GA
  wants logins), emit a canonical event for it and route it only there —
  with an exclude on the PostHog provider so it still sees one event per
  fact.
- `client/tests/events-contract.test.ts` fails the build if the client
  emits an event this page doesn't list — the contract is enforced.
- In PostHog → Data management → Events: mark each event here *verified*
  with its one-line description; **hide** the stale names that linger after
  renames (`signup_completed`, `public_signin_gate`,
  `plan_checkout_clicked`, `plan_subscription_completed`,
  `first_artifact`, `first_artifact_completed`, `attachment_added`,
  `canvas_working_opened`, `agent_ui_action`, `followup_shown`,
  `ask_shown`, `ui_action_unknown`, `user_signed_up`, `user_signed_in`). Historical rows can't be deleted;
  hiding keeps them out of the pickers.
- Provider-native capabilities (identify, surveys) send provider events —
  the `$survey_*` family is PostHog's, sent by the PostHog plugin, never
  through the canonical pipe.

### Super and person properties

Every event carries these **super properties** (attached at the bus, so any
event filters by them):

| Property | Source |
| --- | --- |
| `agent_domain` | `window.location.hostname` |
| `agent_subdomain` | first DNS label |
| `agent_name` | agent config (`null` if unset) |
| `theme` | `"dark"` \| `"light"` — updates on toggle |
| `language` | `"en"` \| `"ar"` — updates on toggle |

Identified users also carry **person properties** (via identify): `email`,
`name`, `first_name`, `last_name`, `avatar_url`, `created_at`, `plan_name`,
`plan_status`, `plan_amount`, `plan_period`, `plan_period_end`,
`plan_canceled_at`, `is_paid`, `org_id`, `org_name`, `language`.

---

## Event contract

### Activation

| event | fires when | key props / question |
|---|---|---|
| `sign_up_start` | signed-out visitor acts (send, sign-in button) | `has_draft` — does the public shell convert? |
| `sign_up_attempted` / `sign_in_attempted` | auth form/oauth submitted | `method`, `step` |
| `sign_up` | account created — Clerk complete for password/code; OAuth inferred on first authed load (account < 5 min old); once per browser | `method` — gate → account conversion |
| `first_agent_use` | the account's first chat ever — the server keeps a per-account marker (`activation/first_use_at` in the personal workspace) and flags `first` on the `chat_id` event once (a browser flag would re-fire per device, a per-workspace check per workspace) | the marketing funnel's activation tick; GA can't derive "first" itself |
| `message_sent` | every send | `origin` (keyboard/suggestion/example/follow_up/ask/voice/regenerate/url_param), `is_new_chat` — the funnel spine |
| `examples_shown` | gallery renders with cards | `categories`, `items` — denominator for the gallery |
| `example_category_selected` / `example_prompt_used` / `example_viewed` / `example_watched` | gallery interactions | which examples actually activate |
| `suggestion_category_selected` / `suggestion_prompt_clicked` | empty-state chips (no-examples fallback) | |

### Conversation

| event | fires when | key props / question |
|---|---|---|
| `turn_completed` | stream ends (also when stopped) | `tools` {name: count}, `tool_calls`, `duration_s`, `produced_artifact`, `errored`, `stopped`, `origin` — the shape of the work, without per-tool-call volume |
| `generation_stopped` | user hits stop mid-stream | impatience / runaway signal |
| `message_retried` / `message_regenerated` / `message_failed` | recovery paths | friction |
| `message_queued` / `queued_message_sent` / `queued_message_edited` / `queued_message_dropped` | composing while the agent works | does queueing get used? |
| `chat_loaded` / `chat_cleared` / `chat_renamed` / `chat_favorited` / `chat_deleted` | sidebar chat ops | retention behavior |

### Deliverables

| event | fires when | key props / question |
|---|---|---|
| `artifact_completed` | agent's `canvas` call | `path`, `kind` — output per session |
| `canvas_loader_shown` | the canvas opens in its loader state during a live edit | do users see work happening? |
| `file_saved` / `file_shared` / `file_deleted` / `file_renamed` / `folder_created` | files panel & canvas ops | is the workspace a real home? |
| `file_uploaded` / `file_upload_failed` | uploads, `context` = `chat_attachment` or `files_panel` | `file_type`, `file_size` |

### Sharing loop (organic acquisition)

`share_created` → `share_viewed` → `share_fork_clicked` → `share_forked`

| event | fires when | key props / question |
|---|---|---|
| `share_created` / `share_create_failed` / `share_deleted` | owner mints/revokes | `message_count` |
| `share_viewed` / `share_view_failed` | share data loads on /shared/… (404s don't count) | `type`, `example` (gallery vs organic — two different funnels), `artifacts`, `signed_in`, `referrer` |
| `share_fork_clicked` | continue-this-conversation pill | |
| `share_forked` | fork API succeeds | loop closed. Viewer is anonymous until sign-in — same-device journeys stitch, cross-device shows as two people |

### Agent interventions

| event | fires when | key props / question |
|---|---|---|
| `ui_action` | every minor agent `ui` event: `action` = `suggest`, `ask` (+ `questions`), or anything unhandled (`handled: false`) | the denominator for the chips: `followup_accepted` ÷ `ui_action{suggest}`, `ask_answered` ÷ `ui_action{ask}`. Milestone actions fire their named event instead (`open_canvas` → `artifact_completed`, `open_plan_modal` → `paywall_shown`) |
| `ask_answered` / `ask_dismissed` | clarifying-question card resolved | answered ÷ shown decides the feature's fate |
| `followup_accepted` | follow-up chip taken | `method` (click/arrow) |
| `ask_toggled` / `followups_toggled` | settings switches | opt-out rate = annoyance meter |

### Monetization

| event | fires when | key props / question |
|---|---|---|
| `paywall_shown` | the **agent** forces the plan modal | `reason` (`limit` / `plan_required`) — friction, not curiosity |
| `limit_reached` | free-tier cap specifically | |
| `plan_modal_opened` / `plan_modal_closed` | any plans view (superset of paywall) | `source`, `method` |
| `checkout_start` | checkout clicked | `plan_name`, `plan_id`, `billing_period`, `value`, `currency`, `payer_type`, `is_free` |
| `purchase` | Clerk confirms payment | same, + `transaction_id` |
| `plan_manage_clicked` | manage-subscription | |

### Voice, settings, misc

`mic_started` / `mic_stopped` / `mic_cancelled` / `mic_transcribed` /
`mic_transcription_failed` / `mic_permission_denied` · `settings_opened` ·
`theme_changed` · `language_changed` · `explore_opened` /
`explore_agent_clicked` · `source_opened` · `user_signed_out`

---

## Query cookbook (PostHog / HogQL)

Every query below can be scoped to one agent by adding
`WHERE properties.agent_domain = 'stock.cycls.ai'` (SQL) or the equivalent
property filter in the insight UI.

### Acquisition & auth

**Sign-up funnel by method** — what fraction of sign-up attempts complete,
and which method converts best?

Funnel insight: `sign_up_attempted` (grouped by `method`) → `sign_up`.

```sql
SELECT
  properties.method AS method,
  countIf(event = 'sign_up_attempted') AS attempts,
  countIf(event = 'sign_up')          AS completions,
  completions / nullIf(attempts, 0)   AS rate
FROM events
WHERE timestamp > now() - INTERVAL 30 DAY
  AND event IN ('sign_up_attempted', 'sign_up')
GROUP BY method
ORDER BY attempts DESC
```

Low rate on `oauth_google` vs `password` usually means the OAuth consent
screen is dropping people, or the return redirect is broken.

**Sign-in funnel by method** — same shape with `sign_in_attempted` →
`$identify` (PostHog's own event for "a known person appeared").

**OAuth attrition** — of users who click "Continue with Google/Apple", how
many come back signed in?

```sql
SELECT
  properties.method AS method,
  count() AS clicks,
  countIf(distinct_id IN (
    SELECT distinct_id FROM events
    WHERE event = '$identify' AND timestamp > now() - INTERVAL 1 DAY
  )) AS returned_signed_in
FROM events
WHERE event = 'sign_in_attempted'
  AND properties.step = 'oauth_redirect'
  AND timestamp > now() - INTERVAL 30 DAY
GROUP BY method
```

If `returned_signed_in / clicks` drops, the OAuth round-trip is broken on
that provider — likely a Clerk domain / redirect URL config issue.

**New vs returning** — `sign_up` marks a new account (once per
account); returning sessions are `$identify` without a `sign_up`. For
long-horizon cohorts prefer PostHog's native `$first_seen` / cohorts.

### Engagement — messaging

**Daily / weekly active senders** — trend on `message_sent`, aggregate =
unique users.

**Messages per chat** — one-shot interactions or real conversations?

```sql
SELECT
  properties.chat_id AS chat_id,
  count() AS messages,
  any(properties.agent_domain) AS agent
FROM events
WHERE event = 'message_sent'
  AND properties.chat_id IS NOT NULL
  AND timestamp > now() - INTERVAL 30 DAY
GROUP BY chat_id
ORDER BY messages DESC
```

Histogram the `messages` column. A median of 1 is a red flag — either the
answer doesn't invite a follow-up, or the agent errors on turn 2.

**New-chat starts per day** — picking up old threads, or starting fresh?

```sql
SELECT
  toDate(timestamp) AS day,
  countIf(properties.is_new_chat = true)  AS new_chats,
  countIf(properties.is_new_chat = false) AS continued_chats
FROM events
WHERE event = 'message_sent'
  AND timestamp > now() - INTERVAL 30 DAY
GROUP BY day
ORDER BY day
```

**Turn shape** — which capabilities do turns actually exercise?

```sql
SELECT
  properties.produced_artifact AS made_artifact,
  count()                      AS turns,
  avg(toFloat(properties.duration_s))  AS avg_s,
  avg(toFloat(properties.tool_calls))  AS avg_tools
FROM events
WHERE event = 'turn_completed'
  AND timestamp > now() - INTERVAL 30 DAY
GROUP BY made_artifact
```

Cross-cut with retention: do artifact-producing turns retain better?

**Failure rate on send**

```sql
SELECT
  toDate(timestamp) AS day,
  countIf(event = 'message_sent')   AS sent,
  countIf(event = 'message_failed') AS failed,
  failed / nullIf(sent, 0)          AS failure_rate
FROM events
WHERE event IN ('message_sent', 'message_failed')
  AND timestamp > now() - INTERVAL 14 DAY
GROUP BY day
ORDER BY day
```

Alert if `failure_rate > 0.02` for a day — usually upstream LLM outage or a
bad deploy.

**Retry / stop behaviour** — trends for `generation_stopped`,
`message_retried`, `message_failed`: retries ≈ failures means recovery;
retries ≫ failures means dissatisfaction.

### Activation funnels

**Gallery → first message**: `examples_shown` → `example_prompt_used` →
`message_sent` (origin = `example`).

**Time to first artifact** — the aha metric. Not a materialized event:
PostHog derives it — Trends on `artifact_completed` with the *first time
performed* aggregation, or a funnel `sign_up` → `artifact_completed` with
the *first time for user* filter. A client-side "first" flag would be
per-browser and re-fire for existing users on a new device.

**Follow-up chip acceptance**: `followup_accepted` ÷ `ui_action` where
`action = suggest`, broken down by `method` (click vs arrow). Same shape for
the ask card: `ask_answered` ÷ `ui_action{ask}`, with `ask_dismissed` as the
negative signal.

### Suggestions funnel

Funnel: `suggestion_category_selected` → `suggestion_prompt_clicked` →
`message_sent` (same session).

```sql
SELECT
  properties.category AS category,
  properties.prompt   AS prompt,
  count()             AS clicks
FROM events
WHERE event = 'suggestion_prompt_clicked'
  AND timestamp > now() - INTERVAL 30 DAY
GROUP BY category, prompt
ORDER BY clicks DESC
LIMIT 50
```

Cross-reference low-converting prompts to prune `suggestions-data.tsx`.

### Chat & share mechanics

**Chat revisit rate** — trend: `chat_loaded`, unique users. Compare to
`message_sent` uniques — a low ratio means the chat list isn't being used.

**Share creation → view conversion**

```sql
SELECT
  share_path,
  any(creator)                         AS creator,
  maxIf(timestamp, event='share_created') AS created_at,
  countIf(event='share_viewed')        AS views,
  uniqIf(distinct_id, event='share_viewed' AND distinct_id != creator)
                                       AS external_viewers
FROM (
  SELECT
    event,
    timestamp,
    distinct_id,
    properties.share_path AS share_path,
    argMinIf(distinct_id, timestamp, event='share_created') OVER (PARTITION BY properties.share_path) AS creator
  FROM events
  WHERE event IN ('share_created', 'share_viewed')
    AND timestamp > now() - INTERVAL 60 DAY
)
GROUP BY share_path
ORDER BY views DESC
```

Shares with high `views` but zero `external_viewers` are the creator
testing their own link — exclude before celebrating virality. Filter
`properties.example = false` to separate organic shares from gallery
traffic.

**Share referrers**

```sql
SELECT
  properties.referrer AS referrer,
  count() AS views,
  uniq(distinct_id) AS unique_viewers
FROM events
WHERE event = 'share_viewed'
  AND timestamp > now() - INTERVAL 30 DAY
GROUP BY referrer
ORDER BY views DESC
```

Null referrers are direct-link opens (iMessage, WhatsApp, copy-paste).

**Share failures** — trend on `share_view_failed` grouped by `error`.

### Plan / monetization funnel

Funnel insight: `plan_modal_opened` → `checkout_start` → `purchase`.
Break step 1 down by `source` (`agent_event` vs `user_menu` vs `url_param`).

**Which plan do people pick?**

```sql
SELECT
  properties.plan_name AS plan,
  properties.billing_period AS period,
  properties.payer_type AS payer,
  count() AS subscriptions
FROM events
WHERE event = 'purchase'
  AND timestamp > now() - INTERVAL 90 DAY
GROUP BY plan, period, payer
ORDER BY subscriptions DESC
```

**Abandoned checkouts** — cohort: fired `checkout_start` but no `purchase`
within 24h. Hot re-engagement targets.

**Paywall conversion** — does the agent's "you've hit the limit" moment
convert better than browsing?

```sql
SELECT
  properties.source AS source,
  count() AS opens,
  uniq(distinct_id) AS users,
  countIf(distinct_id IN (
    SELECT distinct_id FROM events
    WHERE event = 'purchase'
      AND timestamp > now() - INTERVAL 7 DAY
  )) AS converted
FROM events
WHERE event = 'plan_modal_opened'
  AND timestamp > now() - INTERVAL 30 DAY
GROUP BY source
ORDER BY opens DESC
```

`paywall_shown.reason` splits the forced opens further (`limit` vs
`plan_required`).

**Agent UI actions by kind**

```sql
SELECT
  properties.action AS action,
  count()           AS fires,
  countIf(properties.handled = false) AS unhandled
FROM events
WHERE event = 'ui_action'
  AND timestamp > now() - INTERVAL 30 DAY
GROUP BY action
ORDER BY fires DESC
```

`unhandled > 0` means an agent is emitting a `ui` action the client hasn't
been taught yet.

**Close-method distribution**

```sql
SELECT properties.method AS how_closed, count()
FROM events
WHERE event = 'plan_modal_closed'
GROUP BY how_closed
```

`dismiss > select` by 10× means the pricing page isn't landing.

### Voice

**Mic adoption** — unique users of `mic_started` ÷ unique users of
`message_sent`.

**Share of messages by origin**

```sql
SELECT
  properties.origin AS origin,
  count()           AS messages,
  uniq(distinct_id) AS users
FROM events
WHERE event = 'message_sent'
  AND timestamp > now() - INTERVAL 30 DAY
GROUP BY origin
ORDER BY messages DESC
```

`origin='voice' / total` is real voice adoption (`mic_started` only says
they tried). If `mic_started` is frequent but `origin='voice'` rare,
transcription is producing empty strings — cross-check `mic_transcribed.empty`.

**Transcription quality proxy**

```sql
SELECT
  countIf(properties.empty = true)  AS empty,
  countIf(properties.empty = false) AS transcribed,
  avgIf(toFloat(properties.audio_ms), properties.empty = false)      AS avg_audio_ms,
  avgIf(toFloat(properties.transcribe_ms), properties.empty = false) AS avg_transcribe_ms
FROM events
WHERE event = 'mic_transcribed'
  AND timestamp > now() - INTERVAL 14 DAY
```

**Mic failure breakdown** — stack `mic_permission_denied`, `mic_cancelled`,
`mic_transcription_failed`: friction at OS permission, UI intent, or
backend.

### Files

**Attachments vs files panel**

```sql
SELECT
  properties.context AS ctx,
  count()            AS uploads,
  uniq(distinct_id)  AS unique_users
FROM events
WHERE event = 'file_uploaded'
  AND timestamp > now() - INTERVAL 30 DAY
GROUP BY ctx
```

**File-type mix**

```sql
SELECT
  properties.file_type AS mime,
  count()
FROM events
WHERE event = 'file_uploaded'
GROUP BY mime
ORDER BY 2 DESC
LIMIT 20
```

**Upload failure rate**

```sql
SELECT
  toDate(timestamp) AS day,
  countIf(event='file_uploaded')      AS ok,
  countIf(event='file_upload_failed') AS fail,
  fail / nullIf(ok + fail, 0)         AS rate
FROM events
WHERE event IN ('file_uploaded', 'file_upload_failed')
GROUP BY day
ORDER BY day
```

### Cross-agent discovery

Funnel: `explore_opened` → `explore_agent_clicked`.

```sql
SELECT
  properties.agent_domain AS discovered_from,
  properties.agent_slug   AS discovered_to,
  count()                 AS clicks
FROM events
WHERE event = 'explore_agent_clicked'
  AND timestamp > now() - INTERVAL 30 DAY
GROUP BY discovered_from, discovered_to
ORDER BY clicks DESC
```

### Preferences

**Dark-vs-light across the fleet** (super property, so representative):

```sql
SELECT
  properties.theme AS theme,
  count()          AS events,
  uniq(distinct_id) AS users
FROM events
WHERE timestamp > now() - INTERVAL 14 DAY
GROUP BY theme
```

**Language mix per agent**

```sql
SELECT
  properties.agent_domain,
  properties.language,
  uniq(distinct_id) AS users
FROM events
WHERE event = 'message_sent'
  AND timestamp > now() - INTERVAL 30 DAY
GROUP BY 1, 2
ORDER BY 1, 3 DESC
```

**Toggle direction** — heavy correction of one language means
default-detection is wrong:

```sql
SELECT
  properties.to     AS switched_to,
  properties.source AS where,
  count()
FROM events
WHERE event IN ('theme_changed', 'language_changed')
  AND timestamp > now() - INTERVAL 30 DAY
GROUP BY switched_to, where
ORDER BY 3 DESC
```

### Business health dashboards

A useful starter dashboard per agent:

- Trend: DAU (unique `message_sent` senders)
- Trend: messages per day, broken down by `is_paid` person property
- Funnel: `sign_up_start` → `sign_up` → `first_agent_use` → `artifact_completed` (first time for user)
- Funnel: `plan_modal_opened` → `checkout_start` → `purchase`
- Rates: `followup_accepted`/`ui_action{suggest}`, `ask_answered`/`ui_action{ask}`
- Table: top 10 `suggestion_prompt_clicked` prompts
- Table: shares created + views last 30 days (see Share query above)
- Retention: weekly, based on `message_sent`
