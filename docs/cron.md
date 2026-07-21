# Cron

Fire a deployed function on a schedule. One decorator argument — the
platform does the calling.

```python
import cycls

reports = cycls.Volume("daily-reports")

@cycls.function(schedule=cycls.Cron("*/5 * * * *", timezone="Asia/Riyadh"),
                volumes={"/reports": reports})
def heartbeat():
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    with open(f"/reports/{now:%Y-%m-%d}.log", "a") as f:
        f.write(f"{now.isoformat()} alive\n")
```

```bash
cycls deploy heartbeat.py
#   [DEPLOYING] Scheduled: */5 * * * * (Asia/Riyadh)
#   [DONE] Deployment complete!
```

From then on the platform calls `heartbeat()` every five minutes, Riyadh
time. Pair a schedule with a [volume](volume.md) and the output has
somewhere durable to land — a scraper feeding a dashboard is the canonical
shape.

## The mental model

**A schedule fires the deployment** — the function exactly as frozen at
deploy, called with no arguments. It's `cycls.remote("heartbeat")()` on a
timer, issued by the platform instead of your code.

**Source is truth.** The schedule exists because the line exists. Delete
`schedule=` and redeploy — the schedule is gone (`Schedule removed` in the
deploy stream). `cycls rm` removes it with the deployment. There is no
pause button, no separate schedule object to manage, nothing to drift.

## `cycls.Cron`

```python
cycls.Cron("0 3 * * *")                          # daily 03:00 UTC
cycls.Cron("0 6 * * 1", timezone="Asia/Riyadh")  # Mondays 06:00 Riyadh
```

Five-field unix cron, IANA timezone names, UTC by default. Both are
validated at deploy — a typo is an instant error, not a silent no-op.

## What can be scheduled

Bare functions only — the kind that deploy as remote endpoints. The
contradictions fail at import, with the fix in the message:

- an app or agent with `schedule=` (they serve HTTP; schedule a function
  that calls them if you need that),
- a function that takes `port` (the port contract deploys a server, which a
  schedule cannot fire).

## Semantics, honestly

- **At-least-once.** Failed runs are retried. Write idempotent outputs —
  date-keyed files like the example make a double-fire a harmless
  overwrite.
- **Runs can overlap.** A run slower than its interval doesn't block the
  next. If two runs must never race, take a lock file in your volume —
  last-write-wins is the storage's honest contract.
- **Thirty minutes is the ceiling** for a single run. Longer work belongs
  to a different tool (coming); until then, split the work or schedule it
  in slices.
- Every fire is an ordinary request: `cycls logs heartbeat` shows each one.
