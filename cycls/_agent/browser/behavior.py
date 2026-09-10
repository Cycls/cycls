"""Human-like input for the browser tool — mouse approach paths, per-key typing
cadence, and a light "settle" (mouse move + scroll) after a page loads.

Pure programmatic `click()`/`fill()` flatten the behavioral signals bot-management
scores on: the cursor teleports, text appears instantly, nothing moves before an
action. Re-introducing a little motion and timing raises the mouse-entropy /
interaction signals an ML bot-score looks for. This is general-purpose realism,
not a bypass for any specific site; every step is best-effort and falls back to
the plain action so it can never break a flow.

Toggle with `BROWSER_HUMANIZE=0`. Kept in sync with the same helpers inlined in
the cycls browser service (a standalone deploy) — the tunables below are the
contract the sync test checks.
"""
import asyncio
import os
import random

# Tunables — KEPT IN SYNC with the service copy (checked by browser_test).
MOVE_STEPS = (10, 22)        # mouse-move interpolation steps toward a target
TYPE_DELAY_MS = (35, 110)    # per-character keypress delay
PRE_DELAY_MS = (40, 160)     # small settle before a click / type
CLICK_JITTER = 0.28          # fraction of the element box to jitter the hit point off-center


def enabled():
    return os.environ.get("BROWSER_HUMANIZE", "1") != "0"


async def _sleep_ms(lo, hi):
    await asyncio.sleep(random.uniform(lo, hi) / 1000)


async def _move_to(page, x, y):
    """Approach (x, y) via a slight waypoint, then interpolated steps — more
    cursor entropy than Playwright's default teleport-to-target."""
    await page.mouse.move(x + random.uniform(-60, 60), y + random.uniform(-60, 60),
                          steps=random.randint(*MOVE_STEPS))
    await page.mouse.move(x, y, steps=random.randint(*MOVE_STEPS))


async def human_click(page, selector, timeout):
    """Scroll to the element, move the cursor to a jittered point inside it, pause,
    then click via the locator (keeps Playwright's actionability checks, so the
    right element is hit even if the coordinates drift)."""
    el = page.locator(selector).first
    await el.scroll_into_view_if_needed(timeout=timeout)
    try:
        box = await el.bounding_box()
        if box:
            x = box["x"] + box["width"] * (0.5 + random.uniform(-CLICK_JITTER, CLICK_JITTER))
            y = box["y"] + box["height"] * (0.5 + random.uniform(-CLICK_JITTER, CLICK_JITTER))
            await _move_to(page, x, y)
    except Exception:
        pass
    await _sleep_ms(*PRE_DELAY_MS)
    await el.click(timeout=timeout)


async def human_type(page, selector, text, timeout):
    """Focus the field like a person (scroll + click), clear it, then type
    character-by-character with a randomized cadence."""
    el = page.locator(selector).first
    await el.scroll_into_view_if_needed(timeout=timeout)
    await _sleep_ms(*PRE_DELAY_MS)
    try:
        await el.click(timeout=timeout)
    except Exception:
        pass
    try:
        await el.fill("")
    except Exception:
        pass
    for ch in text:
        await page.keyboard.type(ch)
        await _sleep_ms(*TYPE_DELAY_MS)


async def human_settle(page):
    """A little life after a page loads — one cursor move and a small scroll.
    Cloudflare's non-interactive challenge watches for exactly this. Best-effort."""
    try:
        vp = page.viewport_size or {"width": 1280, "height": 800}
        await page.mouse.move(random.uniform(100, vp["width"] - 100),
                              random.uniform(100, vp["height"] - 100),
                              steps=random.randint(*MOVE_STEPS))
        await _sleep_ms(*PRE_DELAY_MS)
        await page.mouse.wheel(0, random.randint(120, 480))
    except Exception:
        pass
