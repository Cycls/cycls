"""Shared test fixtures.

The SlateDB pool keeps Db handles alive across requests for performance.
For tests, we want isolation — each test uses a fresh tmp_path, and we
don't want stale handles holding open files that block tmp_path cleanup
or carry state between tests.
"""
import asyncio
import pytest

from cycls.app.workspace import shutdown_pool


@pytest.fixture(autouse=True)
def _isolate_db_pool():
    yield
    asyncio.run(shutdown_pool())
