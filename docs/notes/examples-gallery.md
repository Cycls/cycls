# Examples gallery — showing what the agent can make

**Problem.** Activation suffers because a new user lands on an empty input box.
Nothing on the page shows what the agent can produce, so the cost of the first
message is imagination, not typing. The fix is to put finished outputs — real
artifacts with the prompts that made them — on the first screen, explorable
without an account.

**Reference.** z.ai's home screen (category chips → gallery of output cards,
hover reveals prompt/preview) and its share page (transcript beside an artifact
panel, floating "start your own conversation"). We take the *structure* only:
every surface renders with our own components — `MessageBubble`, `CanvasDoc`,
the existing empty-state hero — so the identity stays ours by construction.

## Design decisions

1. **An example IS a public share.** No new content type, no CMS, no screenshot
   pipeline. The operator uses the product, shares the chat (`POST /share`),
   and lists the share URL in config. The share system is already the data
   layer: `GET /share/{user}/{token}/data` (conversation JSON) and
   `GET /share/{user}/{token}/file/<path>` (bytes) — both public per-share.

2. **One link carries the chat AND its artifact.** Today a chat share only
   authorizes its *attachments* (`routers.py` `shared_attachment`), so the
   canvas output of a shared chat 403s. We extend the allowed set to files
   referenced by the chat's successful `Canvas` steps. No paired file share,
   one token to mint/revoke, artifact atomically part of its conversation.
   `fork` gets the same extension: "Continue this conversation" copies canvas
   files too, so the forker lands with the artifact in their workspace.

3. **Share page = transcript + canvas, canvas open by default.** The share
   view gains an `onOpenFile` (today file cards are dead there) rendering
   `CanvasDoc` in `shared` mode over the share-scoped file route. On load the
   last canvas artifact opens automatically (desktop; drawer stays closed on
   mobile until tapped). `?open=<path>` deep-links a specific file.

4. **Floating continue CTA.** "Continue this conversation" becomes a fixed
   pill, always visible while scrolling the transcript — the primary
   conversion affordance on every chat share.

5. **Examples carry no author.** `GET /examples` strips author fields; the
   share page hides the author/date chrome when opened with `?example=1`.
   Normal user-to-user shares keep attribution unchanged.

6. **No sign-in wall.** With auth configured, signed-out visitors get the
   public shell of the same empty state — hero, input box, gallery — instead
   of `<CustomSignIn />` (`App.tsx`). Sign-in appears when they *act* (send,
   fork). The draft prompt survives auth via sessionStorage. All data APIs
   stay authed; the shell needs only `/config` (inlined), `/examples`, and the
   public share routes.

7. **Signed-in users see the gallery too.** It lives in the chat's empty
   state, not on a separate landing route — every new chat shows it. The
   hardcoded `suggestions-data.tsx` chips remain the fallback when no
   examples are configured.

8. **Live previews, not screenshots.** Cards render the artifact through
   `CanvasDoc` (scaled, sandboxed, lazy) — HTML, PDF, images, spreadsheets,
   3D, code all work because the canvas dispatcher already handles them.

## API

```python
web = cycls.Web().examples({
    "Landing pages": ["https://agent.cycls.ai/shared/<user>/<tok1>", ...],
    ("Data analysis", "تحليل البيانات"): ["/shared/<user>/<tok2>?ws=t-team", ...],
})
# tuple key = (en, ar) pill label, mirroring explore's title/title_ar;
# or uncategorized: .examples(["<share-url>", ...]) — no pills, one grid
```

URLs must be shares minted by this agent (same deployment); absolute or
relative. Dict order = pill order. The builder normalizes to
`[{label, label_ar, urls}]` (Config.examples).

### `GET /examples` (public, cached 300s like `/explore`)

```json
{"categories": [{"label": "Landing pages", "label_ar": null, "items": [{
    "share": "/shared/u/tok1?example=1",
    "title": "IRONFORGE fitness studio",
    "prompt": "Design a high-end fitness studio brand official website...",
    "file": {"path": "site.html", "name": "site.html",
             "url": "/share/u/tok1/file/site.html"}}]}]}
```

`title` from chat meta, `prompt` = first user message, `file` = last
successful Canvas step (null if the chat produced none — card still shows,
preview falls back to the prompt text). Dead tokens are skipped with a warn.
Config: `Config.examples` (raw mapping, server-side), `examples_enabled` in
`config.public()` — mirrors the `explore`/`explore_enabled` pattern.

## FE

- `ExamplesGallery` (new): fetches `/examples`; category chips; cards.
  Card = scaled `CanvasDoc` preview + title; hover (always-on for touch, the
  `sm:opacity-0 group-hover` pattern) reveals **Use prompt** (fills the
  input box — tighter than clipboard: edit → send → sign-in pops → sent) and
  **View** (→ the share page).
- `chat.tsx` empty state: gallery under the input when `examples_enabled`,
  `Suggestions` otherwise.
- `shared-view.tsx`: canvas pane (desktop split / mobile drawer) via the
  existing share file transport; auto-open; `?open=`; floating CTA;
  `?example=1` hides author chrome.
- `App.tsx`: `SignedOut` → public shell (hero + input + gallery); actions
  gate through the sign-in view; draft in `sessionStorage("cycls_draft")`,
  restored by the signed-in Chat on mount.

## Later (not this pass)

- `cms(examples=url)` — same resolver, list served by a CMS; re-curate
  without redeploy (follows the `cms(brand=, explore=)` precedent).
- Per-share OG images: `og.generate()` already takes `avatars` (unused);
  share URLs should unfurl with the chat title + author.
- "Feature this share" admin action — product-native curation.

## Tests

- BE: chat share serves canvas-step files, still 403s unrelated paths; fork
  copies canvas files; `/examples` resolves cards, strips author, skips dead
  tokens; `examples_enabled` in public config.
- FE: gallery fetch/render; empty-state fallback to `Suggestions`.
