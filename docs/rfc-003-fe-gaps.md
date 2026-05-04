# RFC003 — FE follow-ups

Outstanding FE work after `rfc-003-share` lands. The backend share API is complete; this is what's wired vs what isn't.

## Wired

| Endpoint | Consumer |
|---|---|
| `POST /share` (chat) | `use-chat.ts share()` — passes path, audience, author |
| `POST /share` (file) | `use-files.ts shareFile()` — passes path only |
| `POST /share` (file, 1h TTL) | `use-files.ts openFile()` — for native browser loads |
| `GET /share` | `use-chat.ts listShares()` |
| `DELETE /share/{token}` | `use-chat.ts deleteShare()` |
| `GET /share/{user}/{token}/data` | `shared-view.tsx` |
| `GET /share/{user}/{token}/file/{path}` | SPA redirect for file shares; chat-attachment loads |
| `POST /share/{user}/{token}/fork` | `use-chat.ts forkShare()` |

## Real product gaps

### 1. Audience picker on file shares
Chat shares have a public/org-private toggle in the dialog. File shares (the files-panel dropdown "Share" item) silently mint public — no audience choice. Inconsistent with chat shares; **org-private file sharing was a v1 goal**.

Cost: ~10-15 LOC. Needs a small dialog instead of the current toast-only flow, parallel to the chat-share dialog but without the title input.

### 2. TTL picker
Both endpoints accept a `ttl` body field; the FE never exposes it. Users always get the server default (7 days). Drive-style "Anyone with link, expires in 30 days" is a common control.

Cost: ~10 LOC for a pill row in the share dialogs.

## Quality gaps

### 3. Silent failure modes
Share-related failures swallow without user feedback:
- Chat share mint fails → `.catch(() => setShareLoading(false))` in `chat.tsx`
- File share mint fails → `shareFile()` throws, the dropdown handler doesn't catch — uncaught promise rejection in console
- Fork fails → `.catch(() => {})` in `App.tsx` — user lands on the home page with no chat, no explanation

Cost: ~5-10 LOC across these for proper error toasts.

### 4. Fork in-flight feedback
When `?fork=` is processing (~1-3 seconds), there's no UI feedback — just a flash of the home page. A spinner or "Forking conversation…" message would help.

Cost: ~5 LOC.

### 5. Sign-in handoff verification (manual test, not code)
Click "Continue this conversation" while signed out → does Clerk's sign-in flow preserve the `?fork=` query param in the redirect-back URL? If not, configure `redirectUrl` on Clerk's `SignIn` component. **Pre-launch must-do.**

## Polish (low value)

### 6. Show URL on file-share success
The file-share toast says "Link copied · filename" — user doesn't see the actual URL. To verify before sending, they paste it. Adding a "Show URL" affordance or switching to a small dialog conflicts with the toast aesthetic that we explicitly settled on; defer unless requested.

### 7. Fork attribution UI
When viewing a forked chat, show "Forked from <author>" somewhere. The `forked_from` field exists in chat metadata but the FE doesn't render it.

## Out of scope (API doesn't support)

- **Edit share** (change audience/ttl after creation)
- **Reactivate revoked share** — `DELETE` just removes the row; no resurrection
- **Share usage analytics** ("this link was viewed N times") — needs deployment-level audit log

## Priority order

If picking one: **#1** (file-share audience picker). It's the only "missing v1 feature" left. Everything else is polish or internal correctness.

Recommended order if doing several:
1. #1 — file-share audience (closes a v1 inconsistency)
2. #3 — error feedback (silent failures bite)
3. #4 — fork loading state (small UX win)
4. #5 — sign-in handoff test (manual)
5. #2 — TTL picker (nice-to-have, no signal yet)
