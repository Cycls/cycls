# Product events — the analytics contract

Every named event is a small API: rename a feature or move a button and a
dashboard silently flatlines. This page is the contract — event → trigger →
what question it answers. Update it in the same commit that touches a call
site.

**Conventions**
- `agent_name` / `agent_domain` ride every event as super properties
  (`setAgentDomain`), so everything segments per agent for free.
- Every `*_accepted` / `*_used` has a `*_shown` denominator — rates, not counts.
- Properties are ids and enums, never content: no prompts, titles, or emails.
- Client-side loses ~10-20% to blockers. Directionally sound; never reconcile
  against billing. The server's `usage` / `tool_call` logs are the
  authoritative record of turns and tools.
- Marketing (GTM/GA4 dataLayer) is a separate, smaller contract — the agency's
  six events. This one is the product's, and it is tool-agnostic: events flow
  through `track()` (lib/posthog.ts today), so swapping or adding a backend
  touches that one function, never the call sites.

## Activation

| event | fires when | key props / question |
|---|---|---|
| `public_signin_gate` | signed-out visitor acts (send, sign-in button) | `has_draft` — does the public shell convert? |
| `sign_up_attempted` / `sign_in_attempted` | auth form/oauth submitted | `method`, `step` |
| `signup_completed` | Clerk signup completes; OAuth inferred on first authed load (account < 5 min old), once per browser | `method` — gate → account conversion |
| `message_sent` | every send | `origin` (keyboard/suggestion/example/follow_up/ask/voice/regenerate), `is_new_chat`, `first_ever` — the funnel spine |
| `first_artifact` | user's first-ever completed artifact (per browser+agent) | `kind` — **time-to-first-artifact is the aha metric** |
| `examples_shown` | gallery renders with cards | `categories`, `items` — denominator for the gallery |
| `example_category_selected` / `example_prompt_used` / `example_viewed` / `example_watched` | gallery interactions | which examples actually activate |
| `suggestion_category_selected` / `suggestion_prompt_clicked` | empty-state chips (no-examples fallback) | |

## Conversation

| event | fires when | key props / question |
|---|---|---|
| `turn_completed` | stream ends (also when stopped) | `tools` {name: count}, `tool_calls`, `duration_s`, `produced_artifact`, `errored`, `stopped`, `origin` — the shape of the work, without per-call volume |
| `generation_stopped` | user hits stop mid-stream | impatience / runaway signal |
| `message_retried` / `message_regenerated` / `message_failed` | recovery paths | friction |
| `message_queued` / `queued_message_sent` / `queued_message_edited` / `queued_message_dropped` | composing while the agent works | does queueing get used? |
| `chat_loaded` / `chat_cleared` / `chat_renamed` / `chat_favorited` / `chat_deleted` | sidebar chat ops | retention behavior |

## Deliverables

| event | fires when | key props / question |
|---|---|---|
| `artifact_completed` | agent's `canvas` call | `path`, `kind` — output per session |
| `canvas_working_opened` | working skeleton opens during a live edit | do users see work happening? |
| `file_saved` / `file_shared` / `file_uploaded` / `file_deleted` / `file_renamed` / `folder_created` | files panel & canvas ops | is the workspace a real home? |
| `attachment_added` / `file_upload_failed` | composer attachments | `count`, `kinds` |

## Sharing loop (organic acquisition)

`share_created` → `share_viewed` → `share_fork_clicked` → `share_forked`

| event | fires when | key props / question |
|---|---|---|
| `share_created` / `share_create_failed` / `share_deleted` | owner mints/revokes | `message_count` |
| `share_viewed` / `share_view_failed` | share data loads on /shared/… (404s don't count) | `type`, `example` (gallery vs organic — two different funnels), `artifacts`, `signed_in`, `referrer` |
| `share_fork_clicked` | continue-this-conversation pill | |
| `share_forked` | fork API succeeds | loop closed. Viewer is anonymous until sign-in — same-device journeys stitch, cross-device shows as two people |

## Agent interventions

| event | fires when | key props / question |
|---|---|---|
| `ask_shown` / `ask_answered` / `ask_dismissed` | clarifying-question card | answered ÷ shown decides the feature's fate |
| `followup_shown` / `followup_accepted` | suggested follow-up chip | accepted ÷ shown, `method` (click/arrow) |
| `ask_toggled` / `followups_toggled` | settings switches | opt-out rate = annoyance meter |
| `agent_ui_action` | every `ui` event, generic | raw firehose; prefer the named events above |

## Monetization

| event | fires when | key props / question |
|---|---|---|
| `paywall_shown` | the **agent** forces the plan modal | `reason` (`limit` / `plan_required`) — friction, not curiosity |
| `limit_reached` | free-tier cap specifically | |
| `plan_modal_opened` / `plan_modal_closed` | any plans view (superset of paywall) | `source`, `method` |
| `plan_checkout_clicked` | Clerk checkout starts | = marketing's `checkout_start` |
| `plan_subscription_completed` | Clerk confirms payment | = marketing's `purchase` (subscription is account-wide; the event lands on the agent-domain of conversion) |
| `plan_manage_clicked` | manage-subscription | |

## Voice, settings, misc

`mic_started` / `mic_stopped` / `mic_cancelled` / `mic_transcribed` /
`mic_transcription_failed` / `mic_permission_denied` · `settings_opened` ·
`theme_changed` · `language_changed` · `explore_opened` /
`explore_agent_clicked` · `source_opened` · `user_signed_out`
