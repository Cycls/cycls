# Analytics — event catalog and example queries

Cycls ships a PostHog integration for any agent that opts in via
`cycls.Web().analytics(True)`. When enabled, the chat UI loads the PostHog
JS SDK, identifies signed-in users with their email / plan / org, and emits
the events documented below.

All events carry these **super properties** automatically (attached at capture
time, so you can filter *any* event by them without them being on the payload):

| Property | Source | Notes |
| --- | --- | --- |
| `agent_domain` | `window.location.hostname` | e.g. `stock.cycls.ai` |
| `agent_subdomain` | first DNS label | e.g. `stock` |
| `agent_name` | `cycls.Web()` slug | `null` if not set |
| `theme` | `"dark"` \| `"light"` | updates on toggle |
| `language` | `"en"` \| `"ar"` | updates on toggle |

Identified users also carry these **person properties** (set via
`posthog.identify`): `email`, `name`, `first_name`, `last_name`, `avatar_url`,
`created_at`, `plan_name`, `plan_status`, `plan_amount`, `plan_period`,
`plan_period_end`, `plan_canceled_at`, `is_paid`, `org_id`, `org_name`,
`language`.

Every query below can be scoped to one agent by adding
`WHERE properties.agent_domain = 'stock.cycls.ai'` (SQL) or the equivalent
property filter in the insight UI.

---

## Acquisition & auth

### Sign-up funnel by method

**Business question:** what fraction of sign-up attempts actually complete,
and which method converts best?

Funnel insight:
1. `sign_up_attempted` — grouped by property `method`
2. `user_signed_up`

Also useful as HogQL:

```sql
SELECT
  properties.method AS method,
  countIf(event = 'sign_up_attempted') AS attempts,
  countIf(event = 'user_signed_up')   AS completions,
  completions / nullIf(attempts, 0)   AS rate
FROM events
WHERE timestamp > now() - INTERVAL 30 DAY
  AND event IN ('sign_up_attempted', 'user_signed_up')
GROUP BY method
ORDER BY attempts DESC
```

**Read it as:** low rate on `oauth_google` vs `password` usually means the
OAuth consent screen is dropping people, or the return redirect is broken.

### Sign-in funnel by method

Same shape as above with `sign_in_attempted` → `user_signed_in`.

### OAuth attrition specifically

**Business question:** of users who click "Continue with Google/Apple", how
many actually come back signed in?

```sql
SELECT
  properties.method AS method,
  count() AS clicks,
  countIf(distinct_id IN (
    SELECT distinct_id FROM events
    WHERE event = 'user_signed_in' AND timestamp > now() - INTERVAL 1 DAY
  )) AS returned_signed_in
FROM events
WHERE event = 'sign_in_attempted'
  AND properties.step = 'oauth_redirect'
  AND timestamp > now() - INTERVAL 30 DAY
GROUP BY method
```

**Read it as:** if `returned_signed_in / clicks` drops, the OAuth round-trip
is broken on that provider — likely a Clerk domain / redirect URL config
issue.

### New vs returning split

`user_signed_up` is emitted when `user.createdAt` is within 5 minutes of
identify; otherwise `user_signed_in` fires. For long-horizon cohorts prefer
PostHog's native `$first_seen` / cohort features.

---

## Engagement — messaging

### Daily / weekly active senders

**Business question:** how many unique people are *actually using* the agent
(as opposed to just visiting)?

Trend insight: `message_sent`, aggregate = unique users, interval = day.

### Messages per session distribution

**Business question:** are people having one-shot interactions or real
conversations?

```sql
SELECT
  properties.session_id AS session_id,
  count() AS messages,
  any(properties.agent_domain) AS agent
FROM events
WHERE event = 'message_sent'
  AND properties.session_id IS NOT NULL
  AND timestamp > now() - INTERVAL 30 DAY
GROUP BY session_id
ORDER BY messages DESC
```

Histogram the `messages` column. A median of 1 is a red flag — either the
answer doesn't invite a follow-up, or the agent errors on turn 2.

### New-session starts per user per day

**Business question:** are returning users picking up old threads, or
starting fresh each time?

```sql
SELECT
  toDate(timestamp) AS day,
  countIf(properties.is_new_session = true)  AS new_chats,
  countIf(properties.is_new_session = false) AS continued_chats
FROM events
WHERE event = 'message_sent'
  AND timestamp > now() - INTERVAL 30 DAY
GROUP BY day
ORDER BY day
```

**Read it as:** a very low `continued_chats` share means sessions aren't
being resumed — either the session list is hard to find, or conversations
don't feel worth coming back to.

### Failure rate on message send

**Business question:** what share of `message_sent` ends in `message_failed`?

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

Alert if `failure_rate > 0.02` for a day — usually indicates upstream LLM
outage or a bad deploy.

### Retry / stop behaviour

**Business question:** are people hitting the stop button a lot? Are they
retrying because streams fail, or because they want a different answer?

Trends for `generation_stopped`, `message_retried`, `message_failed` over
the same time range will tell you whether retries are recovering from
failures (retries ≈ failures) or are dissatisfaction-driven (retries ≫
failures).

---

## Suggestions funnel

### Starter-prompt conversion

**Business question:** do suggestions actually drive people to send a
message?

Funnel insight:
1. `suggestion_category_selected`
2. `suggestion_prompt_clicked`
3. `message_sent` (same session)

### Which suggestions work

**Business question:** which individual prompts generate the most
engagement, and which are clicked but not sent?

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

Cross-reference with the low-converting ones from the funnel to prune the
list in `suggestions-data.tsx`.

---

## Session & share mechanics

### Session revisit rate

**Business question:** how often does a user reopen a past session?

Trend: `session_loaded`, unique users, interval = day.
Compare to `message_sent` unique users — low ratio means the session picker
isn't being used.

### Share link creation → view conversion

**Business question:** when a user shares, do their links actually get
visited?

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

**Read it as:** shares with high `views` but zero `external_viewers` are
the creator testing their own link — exclude them before celebrating
virality.

### Share referrers

**Business question:** where does share traffic come from?

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

Empty / null referrers are direct-link opens (iMessage, WhatsApp, copy-
paste). Twitter and LinkedIn show up with their canonical hostnames.

### Share failures

Trend on `share_view_failed` grouped by `error` surfaces broken / expired
shares people are still trying to open.

---

## Plan / monetization funnel

### Plans modal → subscription funnel

**Business question:** of users who open the plans modal, how many subscribe?

Funnel insight:
1. `plan_modal_opened`
2. `plan_checkout_clicked`
3. `plan_subscription_completed`

Break down step 1 by `source` (`user_menu` vs `url_param`) — driving traffic
from your landing page with `?plans=b2c` should outperform menu-initiated
opens (higher intent).

### Which plan do people pick?

```sql
SELECT
  properties.plan_name AS plan,
  properties.plan_period AS period,
  properties.payer_type AS payer,
  count() AS subscriptions
FROM events
WHERE event = 'plan_subscription_completed'
  AND timestamp > now() - INTERVAL 90 DAY
GROUP BY plan, period, payer
ORDER BY subscriptions DESC
```

### Abandoned checkouts

**Business question:** who clicked checkout but never completed?

Cohort: users who fired `plan_checkout_clicked` but never fired
`plan_subscription_completed` in the following 24 hours. These are hot
re-engagement targets.

### Agent-driven plan modal opens

**Business question:** when the agent programmatically opens the plans modal
(e.g. free-tier limit hit via `yield {"type": "ui", "action": "open_plan_modal"}`),
how often does it convert vs a user-initiated open?

`plan_modal_opened` carries a `source` property. Agent-triggered opens use
`source = "agent_event"`; user clicks use `source = "user_menu"`; landing-page
deep links use `source = "url_param"`.

```sql
SELECT
  properties.source AS source,
  count() AS opens,
  uniq(distinct_id) AS users,
  countIf(distinct_id IN (
    SELECT distinct_id FROM events
    WHERE event = 'plan_subscription_completed'
      AND timestamp > now() - INTERVAL 7 DAY
  )) AS converted
FROM events
WHERE event = 'plan_modal_opened'
  AND timestamp > now() - INTERVAL 30 DAY
GROUP BY source
ORDER BY opens DESC
```

**Read it as:** if `agent_event` converts at a higher rate than `user_menu`,
your agent's "you've hit the limit" moment is hotter than the browsing
user — prioritize that trigger.

### Agent UI action audit

**Business question:** which UI actions are agents firing, and how often?

```sql
SELECT
  properties.agent_domain AS agent,
  properties.action       AS action,
  count()                 AS fires
FROM events
WHERE event = 'agent_ui_action'
  AND timestamp > now() - INTERVAL 30 DAY
GROUP BY agent, action
ORDER BY fires DESC
```

Every `{"type": "ui", "action": "..."}` yielded from any agent lands here,
even ones the client doesn't currently handle — useful for discovering
when someone's started emitting a new action we haven't wired up yet.

### Close-method distribution

```sql
SELECT properties.method AS how_closed, count()
FROM events
WHERE event = 'plan_modal_closed'
GROUP BY how_closed
```

Heavy `backdrop` / `dismiss` vs `select` is the "dropped out of pricing"
signal. If `dismiss > select` by 10×, the pricing page isn't landing.

---

## Voice

### Mic adoption

**Business question:** what share of active users tries voice input?

Trend: unique users of `mic_started` / unique users of `message_sent`.

### Share of messages that came from voice

**Business question:** how much of real usage is keyboard vs voice vs
suggestions vs URL deep-link?

`message_sent` now carries an `origin` property set at send time:
`keyboard` (default), `voice` (auto-sent from transcription),
`suggestion` (clicked starter prompt), `url_param` (landed on the page
with `?q=...`).

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

**Read it as:** `voice / total` is the real voice adoption metric
(`mic_started` only tells you they tried; `origin='voice'` tells you they
actually shipped a message with it). If `mic_started` fires often but
`origin='voice'` is rare, transcription is probably producing empty
strings — cross-check with `mic_transcribed.empty`.

### Transcription quality proxy

**Business question:** how often does a recording produce zero text?

```sql
SELECT
  countIf(properties.empty = true)  AS empty,
  countIf(properties.empty = false) AS transcribed,
  avgIf(toFloat(properties.audio_ms), properties.empty = false)     AS avg_audio_ms,
  avgIf(toFloat(properties.transcribe_ms), properties.empty = false) AS avg_transcribe_ms
FROM events
WHERE event = 'mic_transcribed'
  AND timestamp > now() - INTERVAL 14 DAY
```

High `empty` share → users don't understand the mic UI, or whisper is
mishearing. Cross-check with `mic_stopped.reason = 'too_short'`.

### Mic failure breakdown

Trends stack of `mic_permission_denied`, `mic_cancelled`,
`mic_transcription_failed` — tells you whether friction is at OS permission,
UI intent, or backend transcription.

---

## Files

### Attachments vs standalone file uploads

**Business question:** do people use the files panel at all, or only inline
attachments?

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

`ctx = chat_attachment` versus `ctx = files_panel` is the split. If the
panel is near-zero the discovery UI isn't working — or the feature doesn't
match use cases.

### File-type mix

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

Drives prioritization for which file types deserve better preview / tool
handling.

### Upload failure rate

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

---

## Cross-agent discovery

### Explore-modal CTR

**Business question:** when people open the Explore dropdown, do they click
through to another agent?

Funnel:
1. `explore_opened`
2. `explore_agent_clicked`

### Which agents are most discovered-from / discovered-to

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

**Read it as:** if users of `stock.cycls.ai` heavily click through to
`tax.cycls.ai`, it's a product signal that those domains are adjacent —
worth bundling or cross-linking more prominently.

---

## Preferences

### Dark-vs-light split across the fleet

**Business question:** should we invest more in dark-mode polish?

```sql
SELECT
  properties.theme AS theme,
  count()          AS events,
  uniq(distinct_id) AS users
FROM events
WHERE timestamp > now() - INTERVAL 14 DAY
GROUP BY theme
```

Since `theme` is a super property on *every* event, this is representative
of actual usage, not just toggle clicks.

### Language mix per agent

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

### Who toggles, and in which direction

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

Heavy toggling of one language suggests default-detection is wrong (users
keep correcting it).

---

## Business health dashboards

A useful starter dashboard per agent:

- Trend: DAU (unique `message_sent` senders)
- Trend: messages per day, broken down by `is_paid` person property
- Funnel: `sign_up_attempted` → `user_signed_up` → first `message_sent`
- Funnel: `plan_modal_opened` → `plan_checkout_clicked` → `plan_subscription_completed`
- Pie: `theme` and `language` super-property split
- Table: top 10 `suggestion_prompt_clicked` prompts
- Table: shares created + views in last 30 days (see Share query above)
- Retention: weekly, based on `message_sent`
