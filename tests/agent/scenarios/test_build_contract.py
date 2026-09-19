"""The build service is a separate deployment in another repo, so the only thing that
catches a drift between its contract and this caller is a call.

    set -a && source .env && set +a
    uv run pytest tests/agent/scenarios/test_build_contract.py --live -v
"""
import asyncio, json, os
import pytest
import cycls
from cycls._agent import tools

pytestmark = pytest.mark.live

APP = {
    "index.html": ('<!doctype html><html><head><meta charset="utf-8"><title>T</title></head>'
                   '<body><div id="root"></div><script type="module" src="/main.tsx"></script></body></html>'),
    "main.tsx": ('import {createRoot} from "react-dom/client";\n'
                 'createRoot(document.getElementById("root")).render(<h1>ok</h1>);\n'),
}


@pytest.fixture(scope="module")
def built():
    if not os.environ.get("CYCLS_API_KEY"):
        pytest.skip("CYCLS_API_KEY is unset")
    build = cycls.remote(tools.APP_BUILDER, timeout=tools._APP_BUILD_TIMEOUT)
    return build(files=APP)


def test_the_reply_has_the_shape_the_caller_subscripts(built):
    assert built.get("ok") is True, built.get("error")
    assert isinstance(built["html"], str) and built["bytes"] > 0
    assert built["stray"] == [], "an asset that cannot be inlined is blocked at runtime"


def test_the_bundle_is_self_contained_and_cannot_call_out(built):
    assert "connect-src 'none'" in built["html"], "the CSP is what bounds a generated page"
    assert "<script" in built["html"] and "src=\"/main.tsx\"" not in built["html"]


def test_the_reply_says_what_produced_it(built):
    assert len(built.get("version") or "") == 12, "app.json stamps this; a stale bundle is found by it"
    pkgs = built.get("packages") or []
    assert "react" in pkgs and len(pkgs) > 20


def test_the_tool_description_matches_the_toolchain(built):
    """Drift here is why the model hand-rolls tables it already has a library for."""
    missing = [p for p in (built.get("packages") or []) if p not in tools._BUILD_APP_TOOL["description"]]
    assert not missing, f"not offered to the model: {missing}"


def test_a_bad_build_comes_back_as_a_result_not_an_exception():
    build = cycls.remote(tools.APP_BUILDER, timeout=tools._APP_BUILD_TIMEOUT)
    # used, or vite tree-shakes the import away and the build succeeds
    r = build(files={**APP, "main.tsx": "import x from 'not-a-real-package';\nconsole.log(x);\n"})
    assert r["ok"] is False and r.get("error")
    assert r.get("packages"), "a failure must say what was available"
