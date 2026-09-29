# Studio dev harness

Drive the built Studio app outside the chat — in a browser, or headless Chrome from a
script — with the real host shim and bridge in front of it and the real engine route
behind it. Used to check every change that needs WebGL (the viewport can't run in vitest)
and to compare Material Preview against a Cycles render of the same scene.

```bash
cd studio && npm run build                      # the bundle the harness serves
python dev/server.py --env <agent>/.providers.env    # :8094, workspace in dev/ws (seeded)
node dev/driver.mjs                             # headless Chrome on the host page, control on :9400
dev/drive.sh - < dev/checks/drag.js             # select, drag the gizmo, check the autosave
dev/drive.sh - < dev/checks/edit.js             # Edit mode: Tab, pick the top face, inset, extrude
uv run --with pillow python dev/compare.py dev/shots/probe.png <cycles.png> dev/shots/cmp.png
```

- `server.py` needs the SDK's Python deps (run it with an agent's venv) and, for engine
  calls, `CYCLS_API_KEY` + `CYCLS_STUDIO_ENGINE` in the env files it loads. Restart it
  after changing `route.py` — it imports the route once.
- `?late=2000` on the host URL mounts the frame at zero size and grows it after 2 s, as
  the chat's canvas does while it slides open.
- `window.__studio` is the app controller inside the frame (`evalApp`); `window.__log`
  and `window.__push(command)` (an agent `app_command`) live in the host page (`evalHost`).
