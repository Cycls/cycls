"""Live browser tests — drive a REAL browser service through the SDK client.

Off by default. Run against a self-hosted Steel (or any CDP endpoint) with:

    docker run -d --shm-size=2g --cap-add=SYS_ADMIN -p 3000:3000 \\
        ghcr.io/steel-dev/steel-browser
    BROWSER_PROVIDER=steel BROWSER_URL=http://localhost:3000 BROWSER_SECRET=x \\
        uv run pytest tests/agent/scenarios/test_browser_live.py --live

Skipped unless `--live` AND a browser service is configured — so CI stays green
without one. Asserts shapes, not exact bytes (real Chrome is non-deterministic).
"""
import asyncio

import pytest

from cycls._agent import browser

# Note: NOT marked @pytest.mark.live — that marker also requires ANTHROPIC_API_KEY
# (the LLM live tests). This one needs a browser service, not an LLM, so it gates
# on --live + browser.configured() itself.


@pytest.fixture(autouse=True)
def _need_service(request):
    if not request.config.getoption("--live"):
        pytest.skip("live browser test (run with --live)")
    if not browser.configured():
        pytest.skip("no browser service configured (set BROWSER_URL / BROWSER_SECRET)")


def test_drive_a_real_page():
    """Mint a session, navigate, read the DOM snapshot, and screenshot — the
    whole client path against a live service."""
    async def run():
        async with await browser.session("test:live") as s:
            info = await s.goto("https://example.com")
            assert "Example" in (info.get("title") or "")
            snap = await s.snapshot()
            assert "Example" in (snap.get("text") or "")
            assert isinstance(snap.get("refs"), list)          # the "More information…" link, etc.
            png = await s.screenshot()
            assert png[:8] == b"\x89PNG\r\n\x1a\n" and len(png) > 1000
    asyncio.run(run())
