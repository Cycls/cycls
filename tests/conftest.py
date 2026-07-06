"""Shared test fixtures."""
import os

import pytest


@pytest.fixture(autouse=True)
def _no_catalog_fetch(monkeypatch):
    """Keep tests offline — the loop's catalog.refresh() must never hit models.dev."""
    from cycls.agent.harness import catalog
    monkeypatch.setattr(catalog, "refresh", lambda *a, **k: None)


@pytest.fixture(autouse=True)
def _reset_migrated():
    """Org names repeat across tests with fresh tmp_paths — clear the
    once-per-org migration cache so each test migrates its own tree."""
    from cycls.agent import state
    state._migrated.clear()


# ---- Live LLM tests ----
# Tests marked @pytest.mark.live hit real Anthropic. Off by default; opt
# in with `pytest --live`. Also auto-skips if ANTHROPIC_API_KEY is unset.

def pytest_addoption(parser):
    parser.addoption("--live", action="store_true", default=False,
                     help="run live tests against real Anthropic API")


def pytest_configure(config):
    config.addinivalue_line("markers", "live: real LLM API call (opt in with --live)")


def pytest_collection_modifyitems(config, items):
    if not config.getoption("--live"):
        skip = pytest.mark.skip(reason="live test (run with --live)")
        for item in items:
            if "live" in item.keywords:
                item.add_marker(skip)
        return
    if not os.environ.get("ANTHROPIC_API_KEY"):
        skip = pytest.mark.skip(reason="ANTHROPIC_API_KEY not set")
        for item in items:
            if "live" in item.keywords:
                item.add_marker(skip)
