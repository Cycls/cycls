"""Shared test fixtures.

The SlateDB pool keeps Db handles alive across requests for performance.
For tests, we want isolation — each test uses a fresh tmp_path, and we
don't want stale handles holding open files that block tmp_path cleanup
or carry state between tests.
"""
import asyncio
import os

import pytest

from cycls.app.workspace import shutdown_pool


@pytest.fixture(autouse=True)
def _isolate_db_pool():
    yield
    asyncio.run(shutdown_pool())


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
