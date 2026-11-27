"""Tests for cycls/_agent/tools/pdf.py — pure helpers only (no subprocess calls)."""
import pytest
from cycls._agent.tools import pdf
from cycls._agent.tools.pdf import parse_pages, MAX_PAGES_PER_READ, EXTRACT_SIZE_THRESHOLD


def test_parse_pages_range():
    assert parse_pages("1-5") == (1, 5)
    assert parse_pages("10-20") == (10, 20)


def test_parse_pages_single():
    assert parse_pages("3") == (3, 3)
    assert parse_pages("1") == (1, 1)


def test_parse_pages_invalid():
    assert parse_pages("") is None
    assert parse_pages(None) is None
    assert parse_pages("abc") is None
    assert parse_pages("1-") is None
    assert parse_pages("-5") is None
    assert parse_pages("a-b") is None


def test_constants():
    assert MAX_PAGES_PER_READ == 20
    assert EXTRACT_SIZE_THRESHOLD == 3 * 1024 * 1024


def test_cut_lands_between_lines_and_leaves_blank_parts_out():
    """A page is read in thirds, each cut in a gap between lines, never through one; a blank third isn't sent."""
    import io
    Image = pytest.importorskip("PIL.Image")
    from PIL import ImageDraw
    page = Image.new("L", (300, 900), 255)
    for y in range(20, 560, 30): ImageDraw.Draw(page).rectangle([20, y, 280, y + 18], fill=0)   # lines in the top two thirds
    buf = io.BytesIO(); page.save(buf, "JPEG")
    parts = [Image.open(io.BytesIO(p)) for p in pdf._cut(buf.getvalue())]
    assert len(parts) == 2
    for part in parts:
        w, h = part.size
        assert min(part.crop((0, 0, w, 1)).tobytes()) > 200 and min(part.crop((0, h - 1, w, h)).tobytes()) > 200
