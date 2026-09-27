"""Live design tests — drive a REAL cycls-design service through the SDK client.

Off by default. Run against a running service (local Docker or a deployed URL):

    docker run -d -p 7700:7700 cycls-design     # from the cycls-design repo
    DESIGN_URL=http://localhost:7700 \\
        uv run pytest tests/agent/scenarios/test_design_live.py --live

Skipped unless `--live` AND a design service is configured — so CI stays green
without one. Asserts shapes/signatures, not exact bytes (rendering is a real
engine).
"""
import asyncio
import io
import zipfile

import pytest

from cycls._agent import design

# Note: NOT marked @pytest.mark.live — that marker also requires ANTHROPIC_API_KEY
# (the LLM live tests). This one needs a design service, not an LLM, so it gates
# on --live + design.configured() itself.


@pytest.fixture(autouse=True)
def _need_service(request):
    if not request.config.getoption("--live"):
        pytest.skip("live design test (run with --live)")
    if not design.configured():
        pytest.skip("no design service configured (set DESIGN_URL)")


_POST = {"size": [1080, 1080], "fill": "#0f172a", "nodes": [
    {"type": "text", "text": "Agents that design.", "x": 96, "y": 360, "w": 888,
     "font": "Inter Bold", "size": 96, "color": "#ffffff", "lineHeight": 100},
    {"type": "rect", "x": 96, "y": 760, "w": 320, "h": 96, "radius": 14, "fill": "#3b82f6"},
]}


def test_render_a_post_to_png():
    """A declarative spec → a real PNG at 2× + an editable .fig."""
    async def run():
        r = await design.render(_POST, fmt="png", scale=2)
        assert r.image[:8] == b"\x89PNG\r\n\x1a\n" and len(r.image) > 5000   # a real raster
        assert r.fig[:2] in (b"PK", b"\x8b\x0a") or len(r.fig) > 1000     # the .fig source
        assert r.fmt == "png" and r.frame_id and r.preview[:2] == b"\xff\xd8"
    asyncio.run(run())


def test_render_a_deck_to_pptx():
    """A frames[] spec → a real multi-slide PowerPoint (one slide per frame) with its
    speaker notes, a preview of every slide, the same deck as a PDF, and /slides."""
    async def run():
        deck = {"frames": [
            {"size": [1920, 1080], "fill": "#0f172a", "notes": "Open with the story.", "nodes": [
                {"type": "text", "text": "Slide one", "x": 140, "y": 400,
                 "font": "Inter Bold", "size": 120, "color": "#ffffff"}]},
            {"size": [1920, 1080], "fill": "#1e3a8a", "nodes": [
                {"type": "text", "text": "Slide two", "x": 140, "y": 400,
                 "font": "Inter Bold", "size": 120, "color": "#ffffff"}]},
        ]}
        r = await design.render(deck, fmt="pptx")
        assert r.image[:4] == b"PK\x03\x04" and r.fmt == "pptx"        # a real .pptx (zip)
        z = zipfile.ZipFile(io.BytesIO(r.image))
        slides = [n for n in z.namelist() if n.startswith("ppt/slides/slide") and n.endswith(".xml")]
        assert len(slides) == 2, f"expected 2 slides, got {len(slides)}"
        assert "Open with the story." in z.read("ppt/notesSlides/notesSlide1.xml").decode()
        assert len(r.previews) == 2 and r.slides[0]["notes"] == "Open with the story."
        assert (await design.export(r.fig, fmt="pdf"))[:5] == b"%PDF-"
        s = await design.slides(r.fig)
        assert len(s["images"]) == 2 and s["sizes"][0] == [1920, 1080]
    asyncio.run(run())


def test_eval_escape_hatch():
    """A raw Figma-API script (must log __FRAME__<id>) → a real PNG."""
    async def run():
        script = (
            "const p=figma.createPage();figma.currentPage=p;"
            "const f=figma.createFrame();f.resize(400,400);"
            "f.fills=[{type:'SOLID',color:{r:0.2,g:0.5,b:0.9}}];"
            "p.appendChild(f);console.log('__FRAME__'+f.id);"
        )
        r = await design.evaluate(script, fmt="png", scale=1)
        assert r.image[:8] == b"\x89PNG\r\n\x1a\n" and r.fmt == "png"
    asyncio.run(run())
