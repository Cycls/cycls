"""Cycls and the design editor together, in a real browser.

The bugs found by hand on prod lived between Cycls and the editor — a design opened
in a background tab, the last tab closed right after an edit — where the unit tests
mock one side. These run both: a real Cycls server (in process, a fixed user, no
Clerk), the built web client, the deployed design editor (or E2E_EDITOR_URL), and
Chromium.

    uv run pytest tests/e2e --e2e                               # the deployed editor
    E2E_EDITOR_URL=http://localhost:7720 uv run pytest tests/e2e --e2e

The agent is scripted (no model): `open` puts designs/e2e.fig on the canvas; `edit`
makes an agent edit the way the Design tool does — the .fig written on the server
first (tests/data/e2e-after.fig), then the same edit replayed in the open editor.
"""
import base64
import os
import shutil
import socket
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.e2e
sync_api = pytest.importorskip("playwright.sync_api")

ROOT = Path(__file__).resolve().parents[2]
THEME = ROOT / "cycls" / "_agent" / "web" / "themes" / "default"
DATA = ROOT / "tests" / "data"
EDITOR = os.environ.get("E2E_EDITOR_URL", "https://cycls-design.cycls.ai").rstrip("/")
DESIGN = "designs/e2e.fig"

# The host page's record of what its editors say (the app's own listener is inside
# React; this one sits beside it on the same window).
RECORD = """(() => {
  if (window !== window.top) return;
  window.__ed = [];
  window.addEventListener('message', (e) => {
    const d = e.data || {};
    if (d.source !== 'cycls-editor') return;
    window.__ed.push({ type: d.type, doc: d.doc, id: d.id, ok: d.ok, name: d.name, features: d.features,
                       fig: typeof d.fig === 'string' ? d.fig : undefined, message: d.message });
  });
})();"""

# The editor frame as in a background browser tab: the page reads as hidden and draws
# no frames until `__show()` (as cycls-design/editor/tests/test_workspace.py).
HIDDEN = """(() => {
  if (!location.search.includes('embed=cycls')) return;
  let hidden = true;
  const held = new Map(); let next = 0;
  const raf = window.requestAnimationFrame.bind(window), caf = window.cancelAnimationFrame.bind(window);
  Object.defineProperty(Document.prototype, 'visibilityState', { configurable: true, get: () => hidden ? 'hidden' : 'visible' });
  Object.defineProperty(Document.prototype, 'hidden', { configurable: true, get: () => hidden });
  window.requestAnimationFrame = (cb) => { if (!hidden) return raf(cb); held.set(--next, cb); return next; };
  window.cancelAnimationFrame = (id) => { if (id < 0) held.delete(id); else caf(id); };
  window.__show = () => {
    hidden = false;
    document.dispatchEvent(new Event('visibilitychange'));
    for (const cb of held.values()) raf(cb);
    held.clear();
  };
})();"""


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Scripted:
    """The agent without a model, keyed on the message; it keeps each turn's context."""

    def __init__(self, root: Path):
        self.root = root
        self.contexts = []

    def __call__(self, context):
        self.contexts.append(context)
        return self._turn(context)

    async def _turn(self, context):
        from cycls._agent.design.store import read_fig, write_fig
        content = context.messages[-1].get("content", "") if context.messages else ""
        text = content if isinstance(content, str) else " ".join(
            p.get("text", "") for p in content if isinstance(p, dict))
        if "edit" in text:   # as the Design tool does: saved first (compared, kept), then replayed
            _, base = read_fig(self.root, DESIGN)
            version = await write_fig(self.root, DESIGN, (DATA / "e2e-after.fig").read_bytes(), base=base,
                                      by="agent", reason="agent", intent="Day Roast")
            yield {"type": "ui", "action": "design_command", "path": DESIGN, "version": version,
                   "script": (DATA / "e2e-edit.js").read_text(encoding="utf-8"), "intent": "Day Roast"}
            yield "Edited."
        elif "note" in text:
            yield "Noted."
        else:
            yield {"type": "ui", "action": "open_canvas", "path": DESIGN}
            yield "Opened."


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    import uvicorn
    import cycls._agent.web.server as web_server
    from cycls._agent.web.routers import install_routers
    from cycls._agent.web.server import Config
    from cycls._app.auth import User

    volume = tmp_path_factory.mktemp("volume")
    root = volume / "local"          # User(id="local") and the anonymous chat share it
    user = User(id="local")
    mp = pytest.MonkeyPatch()
    mp.setattr(web_server, "validator", lambda *a, **k: (lambda: user))
    mp.setenv("DESIGN_EDITOR_URL", EDITOR)
    mp.delenv("DESIGN_URL", raising=False)
    stub = SimpleNamespace(prod=False, _auth_provider=None,
                           config=SimpleNamespace(workspaces=None, max_upload=64))
    agent = Scripted(root)
    app = web_server.web(agent, Config(public_path=str(THEME), auth=False, volume=str(volume)),
                         extra_routers=[lambda a, auth: install_routers(stub, a, auth, volume, f"file://{volume}")])
    port = _free_port()
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=srv.run, daemon=True)
    thread.start()
    for _ in range(100):
        if srv.started:
            break
        time.sleep(0.1)
    yield SimpleNamespace(url=f"http://127.0.0.1:{port}", root=root, agent=agent)
    srv.should_exit = True
    thread.join(5)
    mp.undo()


@pytest.fixture(scope="module")
def browser():
    with sync_api.sync_playwright() as p:
        b = p.chromium.launch(channel=os.environ.get("PW_CHANNEL") or None)
        yield b
        b.close()


class Session:
    """One browser page on Cycls, with the design reset to its fixture."""

    def __init__(self, browser, server, init_script=None):
        from cycls._agent import versions
        self.server = server
        (server.root / "designs").mkdir(parents=True, exist_ok=True)
        shutil.copy(DATA / "e2e.fig", server.root / DESIGN)
        shutil.rmtree(server.root / versions.DIR, ignore_errors=True)   # each test's own history
        versions._last.clear()
        self.context = browser.new_context(viewport={"width": 1600, "height": 1000})
        self.context.add_init_script(RECORD)
        if init_script:
            self.context.add_init_script(init_script)
        self.page = self.context.new_page()
        self.console = []
        self.page.on("console", lambda m: self.console.append(f"{m.type}: {m.text}"))
        self.page.goto(server.url)

    def close(self):
        self.context.close()

    # --- what the editor said -------------------------------------------------
    def events(self, after=0):
        return self.page.evaluate("window.__ed || []")[after:]

    def mark(self):
        return len(self.events())

    def wait_for(self, kind, after=0, timeout=60, where=lambda e: True):
        end = time.time() + timeout
        while time.time() < end:
            for ev in self.events(after):
                if ev.get("type") == kind and where(ev):
                    return ev
                if ev.get("type") == "error":
                    raise AssertionError(f"the editor said {ev}")
            self.page.wait_for_timeout(200)
        raise AssertionError(f"no '{kind}' within {timeout}s: {[e.get('type') for e in self.events(after)]}")

    # --- driving Cycls ------------------------------------------------------------
    def say(self, text):
        box = self.page.locator("textarea").first
        box.fill(text)
        box.press("Enter")

    def open_design(self, timeout=90):
        n = self.mark()
        self.say("open the design")
        self.wait_for("loaded", after=n, timeout=timeout)
        # Past the editor's settle window: what changes in the first 2.5 s counts as
        # the file as saved (fonts re-shaping), so an edit then wouldn't be saved.
        self.page.wait_for_timeout(3500)
        return n

    @property
    def editor(self):
        return next(f for f in self.page.frames if f.url.startswith(EDITOR) and "embed=cycls" in f.url)

    def focus_editor(self):
        box = self.page.locator("iframe").first.bounding_box()
        self.page.mouse.click(box["x"] + box["width"] / 2, box["y"] + 60)   # empty canvas, clear of the toolbars

    def on_disk(self):
        return (self.server.root / DESIGN).read_bytes()

    def no_editor_error(self):
        assert self.page.get_by_text("Editor error").count() == 0

    def features(self):
        ready = next((e for e in self.events() if e.get("type") == "ready"), {})
        return set(ready.get("features") or [])

    def nudge(self):
        """A change of the person's own in the editor: the design's frame moved."""
        self.focus_editor()
        self.page.keyboard.press("Control+a")
        for _ in range(3):
            self.page.keyboard.press("Shift+ArrowRight")

    def versions(self):
        return self.page.evaluate("fetch('/versions/designs/e2e.fig').then((r) => r.json())")["versions"]


@pytest.fixture
def session(browser, server):
    s = Session(browser, server)
    yield s
    s.close()


# ---- 1. A design opens in the editor -----------------------------------------------

def test_a_design_opens_in_the_editor(session):
    n = session.open_design()
    ready = session.wait_for("ready", after=n)
    assert ready  # the editor is up
    session.no_editor_error()


# ---- 2. An agent edit replays live, then saves -------------------------------------

def test_an_agent_edit_replays_and_is_saved(session):
    session.open_design()
    n = session.mark()
    session.say("edit the headline")
    session.wait_for("applied", after=n)
    saved = session.wait_for("saved", after=n, timeout=30)
    session.page.wait_for_timeout(1000)   # the host's write lands
    assert session.on_disk() == base64.b64decode(saved["fig"])
    session.no_editor_error()


# ---- 3. Closing the last tab right after an edit keeps the edit ----------------------

def test_closing_the_last_tab_right_after_an_edit_keeps_it(session):
    session.open_design()
    before = session.on_disk()
    n = session.mark()
    session.focus_editor()
    session.page.keyboard.press("Control+a")
    for _ in range(3):
        session.page.keyboard.press("Shift+ArrowRight")
    session.page.get_by_label("Close e2e.fig").click()   # before the 1.2 s autosave
    saved = session.wait_for("saved", after=n, timeout=15)
    session.wait_for("flushed", after=n, timeout=15)
    session.page.wait_for_timeout(1000)
    assert session.page.locator("iframe").count() == 0   # the canvas went
    assert session.on_disk() == base64.b64decode(saved["fig"]) != before


# ---- 4. A design opened in a background tab loads once it's shown --------------------

def test_a_design_opened_hidden_loads_when_shown(browser, server):
    s = Session(browser, server, init_script=HIDDEN)
    try:
        n = s.mark()
        s.say("open the design")
        s.wait_for("ready", after=n, timeout=90)
        s.page.wait_for_timeout(12000)   # past the editor's 10 s first-frame wait
        assert not any(e["type"] in ("loaded", "error") for e in s.events(n))
        s.editor.evaluate("window.__show()")
        s.wait_for("loaded", after=n, timeout=30)
        s.no_editor_error()
    finally:
        s.close()


# ---- 5. Full screen is the editor's own box -------------------------------------------

def test_full_screen_is_the_editors_own_box(session):
    session.open_design()
    frame = session.page.locator("iframe").first.element_handle()
    session.page.get_by_label("Full screen").click()
    session.page.wait_for_timeout(1000)
    assert session.page.evaluate("(f) => document.fullscreenElement === f.parentElement", frame)
    assert session.page.get_by_text("Exit full screen").count() == 1
    session.page.evaluate("document.exitFullscreen()")


# ---- 6. A change made elsewhere isn't overwritten: the person decides ---------------------

def test_a_change_made_elsewhere_asks_and_keep_mine_writes(session):
    session.open_design()
    (session.server.root / DESIGN).write_bytes((DATA / "e2e-after.fig").read_bytes())   # another tab, a script…
    theirs = session.on_disk()
    session.nudge()
    session.page.get_by_text("This design changed elsewhere").wait_for(timeout=20000)
    assert session.on_disk() == theirs                                   # nothing written meanwhile
    n = session.mark()
    session.page.get_by_text("Keep mine").click()
    saved = session.wait_for("saved", after=n, timeout=15)
    session.page.wait_for_timeout(1000)
    assert session.on_disk() == base64.b64decode(saved["fig"])
    assert [v["reason"] for v in session.versions()][0] == "keep"         # theirs is kept, in Version history


# ---- 7. An agent edit leaves the design before it in Version history; Restore brings it back

def test_version_history_restores_what_an_agent_edit_replaced(session):
    session.open_design()
    original = session.on_disk()
    n = session.mark()
    session.say("edit the headline")
    session.wait_for("applied", after=n)
    session.page.wait_for_timeout(3000)
    assert session.page.get_by_text("This design changed elsewhere").count() == 0   # the edit's own save isn't a conflict
    session.page.get_by_label("More").last.click()
    session.page.get_by_text("Version history").click()
    row = session.page.get_by_test_id("design-version").filter(has_text="Before an agent edit")
    n = session.mark()
    row.get_by_text("Restore").click()
    session.wait_for("loaded", after=n, timeout=60)                        # the editor reopens on it
    assert session.on_disk() == original


# ---- 8. Add selection tells the agent what the person pointed at -------------------------

def test_add_selection_sends_the_selection_with_the_message(session):
    session.open_design()
    if "selection" not in session.features():
        pytest.skip("this editor doesn't report selection yet")
    session.focus_editor()
    session.page.keyboard.press("Control+a")
    session.page.get_by_test_id("add-selection").click(timeout=10000)
    assert "e2e.fig" in session.page.get_by_test_id("selection-chip").first.inner_text()
    before = len(session.server.agent.contexts)
    session.say("note this")
    session.page.get_by_text("Noted.").wait_for(timeout=30000)
    sel = session.server.agent.contexts[before].selection
    assert sel["path"] == DESIGN and sel["nodes"]


# ---- 9. The editor speaks Cycls's language ------------------------------------------------

def test_the_editor_follows_cycls_into_arabic(session):
    session.page.evaluate("document.documentElement.lang = 'ar'; window.dispatchEvent(new Event('langchange'))")
    session.open_design()
    if "lang" not in session.features():
        pytest.skip("this editor has no Arabic yet")
    # The docked canvas is narrow: the editor's compact layout, no menubar — its labels
    # are Arabic all the same.
    assert session.editor.evaluate("document.documentElement.lang") == "ar"
    text = session.editor.evaluate("document.body.innerText")
    assert sum("؀" <= c <= "ۿ" for c in text) > 10, text[:200]
