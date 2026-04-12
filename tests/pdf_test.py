"""Tests for cycls/agent/pdf.py — pure helpers only (no subprocess calls)."""
from cycls.agent.pdf import parse_pages, MAX_PAGES_PER_READ, EXTRACT_SIZE_THRESHOLD


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
