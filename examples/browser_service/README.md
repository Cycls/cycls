# cycls-browser — moved

The shared browser service (the `cycls` provider's backend — FastAPI + Playwright
+ real Chromium) lives in its **own repo**, the office-render sibling:

### → https://github.com/Cycls/cycls-browser

The SDK ships only the **client** (`cycls/_agent/browser/`) and the built-in
`Browser` tool; the service is deployed once from that repo. See
[`docs/notes/browser.md`](../../docs/notes/browser.md) for the design.

```bash
git clone https://github.com/Cycls/cycls-browser && cd cycls-browser
python browser_service.py        # → https://cycls-browser.cycls.ai
```
