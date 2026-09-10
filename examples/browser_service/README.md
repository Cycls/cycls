# `cycls-browser` — the shared browser service

The heavy half of Cycls' built-in browser automation. A small FastAPI +
Playwright app that owns **real Chromium** and exposes a REST API; agents drive
it over HTTP via the SDK's `cycls` browser provider, so **no agent image ever
ships Playwright or Chromium**. Same split as office-render: the heavy dependency
lives in one service, not in every image.

See `docs/notes/browser.md` for the full design.

## Deploy

```bash
# deploys to https://cycls-browser.cycls.ai using your CYCLS_API_KEY
python examples/browser_service/browser_service.py
```

It prints a `BROWSER_SECRET` at deploy time (baked into the container). Wire it on
agents:

```
BROWSER_PROVIDER=cycls
BROWSER_URL=https://cycls-browser.cycls.ai
BROWSER_SECRET=<the printed secret>
```

Set `BROWSER_SECRET` in the environment before deploying to reuse a known secret
(otherwise a fresh one is generated each deploy).

## Run locally

```bash
python examples/browser_service/browser_service.py --local 9400   # no auth, port 9400
```

Point an agent at it with `BROWSER_PROVIDER=cycls`, `BROWSER_URL=http://localhost:9400`
(no secret needed locally).

## Notes

- **`max_instances=1` is required.** Sessions are in-memory and instance-local;
  a second instance would 404 sessions created on the first. One instance serves
  many isolated browser contexts concurrently, bounded by RAM.
- **Stealth is applied here** (this is where Chrome is launched): launch flags, a
  normalized User-Agent, a set locale/viewport/timezone, and the init-script
  patches shared with `cycls/_agent/browser/stealth.py`. It is **not** a
  Cloudflare/anti-bot bypass — good for non-hostile sites and authenticated
  flows. TLS is deliberately untouched (a real Chromium already sends a genuine
  Chrome ClientHello).
- The `_SNAPSHOT_JS` and `_STEALTH_JS` constants are duplicated from the SDK with
  "kept in sync" notes, because this file deploys standalone.
