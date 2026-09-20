import asyncio
import json

import cycls
import pytest

from cycls._agent import tools
from cycls._app.db import workspace


def _ws(root):
    """A Workspace whose root IS `root` — build_app needs the object, not the path."""
    return workspace(root.name, root.parent, base=f"file://{root}")


@pytest.fixture
def ws(tmp_path):
    app = tmp_path / "apps" / "burnup"
    app.mkdir(parents=True)
    (app / "index.html").write_text("<h1>x</h1>")
    return tmp_path


def entry(ws):
    return ws / "apps" / "burnup" / "index.html"


def manifest(ws, payload):
    (ws / "apps" / "burnup" / "app.json").write_text(
        payload if isinstance(payload, str) else json.dumps(payload))


class TestAppIdentity:
    def test_titleises_the_folder_without_a_manifest(self, ws):
        assert tools._app_identity(entry(ws), "index.html") == {"name": "Burnup"}

    def test_uses_the_manifest_name_and_emoji(self, ws):
        manifest(ws, {"name": "Sales Portfolio", "icon": "📊"})
        assert tools._app_identity(entry(ws), "index.html") == {
            "name": "Sales Portfolio", "icon": "📊"}

    def test_passes_an_image_icon_through(self, ws):
        manifest(ws, {"name": "Burnup", "icon": "logo.png"})
        assert tools._app_identity(entry(ws), "index.html")["icon"] == "logo.png"

    @pytest.mark.parametrize("bad", ["{broken", "[]", "null", '"str"'])
    def test_a_broken_manifest_never_hides_the_app(self, ws, bad):
        manifest(ws, bad)
        assert tools._app_identity(entry(ws), "index.html") == {"name": "Burnup"}

    def test_caps_runaway_fields(self, ws):
        manifest(ws, {"name": "n" * 500, "icon": "i" * 50})
        out = tools._app_identity(entry(ws), "index.html")
        assert len(out["name"]) == 60 and len(out["icon"]) == 8

    def test_an_ordinary_file_keeps_its_own_name(self, ws):
        f = ws / "report.html"
        f.write_text("x")
        assert tools._app_identity(f, "report.html") == {"name": "report.html"}

    def test_an_index_outside_apps_is_not_an_app(self, ws):
        other = ws / "site" / "index.html"
        other.parent.mkdir()
        other.write_text("x")
        assert tools._app_identity(other, "index.html") == {"name": "index.html"}


class TestCollectSource:
    def test_keys_files_by_relative_posix_path(self, tmp_path):
        (tmp_path / "src").mkdir()
        (tmp_path / "index.html").write_text("<html>")
        (tmp_path / "src" / "main.tsx").write_text("export {}")
        assert tools._collect_source(tmp_path) == {
            "index.html": "<html>", "src/main.tsx": "export {}"}

    def test_skips_dot_dirs_node_modules_and_binaries(self, tmp_path):
        (tmp_path / "index.html").write_text("<html>")
        for d in (".git", "node_modules"):
            (tmp_path / d).mkdir()
            (tmp_path / d / "x.js").write_text("junk")
        (tmp_path / "logo.png").write_bytes(b"\x89PNG\x00\xff\xfe")
        assert set(tools._collect_source(tmp_path)) == {"index.html"}

    def test_refuses_a_source_tree_that_is_too_large(self, tmp_path, monkeypatch):
        monkeypatch.setattr(tools, "_APP_SRC_MAX_BYTES", 100)
        (tmp_path / "index.html").write_text("x" * 200)
        with pytest.raises(ValueError):
            tools._collect_source(tmp_path)


class TestBuildApp:
    @pytest.fixture
    def src(self, tmp_path):
        d = tmp_path / "apps" / "burnup" / "src"
        d.mkdir(parents=True)
        (d / "index.html").write_text("<html>")
        return d

    def _stub(self, monkeypatch, result):
        monkeypatch.setattr(cycls, "remote", lambda name, **_: (lambda **kw: result))

    def _build(self, inp, ws):
        return asyncio.run(tools._exec_build_app(inp, _ws(ws)))

    @pytest.mark.parametrize("slug", ["", "Has Caps", "a/b", "x!"])
    def test_rejects_an_unusable_slug(self, tmp_path, slug):
        out = self._build({"slug": slug, "source": "apps/burnup/src"}, tmp_path)
        assert out.startswith("Error: slug")

    def test_rejects_a_source_folder_without_an_entry(self, tmp_path):
        d = tmp_path / "s"
        d.mkdir()
        (d / "main.tsx").write_text("x")
        out = self._build({"slug": "burnup", "source": "s"}, tmp_path)
        assert "no index.html" in out

    def test_installs_the_bundle_and_writes_a_manifest(self, tmp_path, src, monkeypatch):
        self._stub(monkeypatch, {"ok": True, "html": "<html>built</html>",
                                 "bytes": 4096, "stray": []})
        out = self._build(
            {"slug": "burnup", "source": "apps/burnup/src",
             "name": "Vendor burn-up", "icon": "📈"}, tmp_path)
        app = tmp_path / "apps" / "burnup"
        assert (app / "index.html").read_text() == "<html>built</html>"
        manifest = json.loads((app / "app.json").read_text())
        assert {k: manifest[k] for k in ("name", "icon")} == {"name": "Vendor burn-up", "icon": "📈"}
        assert "Apps tab" in out

    def test_defaults_the_name_and_keeps_earlier_manifest_fields(
            self, tmp_path, src, monkeypatch):
        app = tmp_path / "apps" / "burnup"
        (app / "app.json").write_text(json.dumps({"description": "kept", "icon": "📈"}))
        self._stub(monkeypatch, {"ok": True, "html": "x", "bytes": 1, "stray": []})
        self._build({"slug": "burnup", "source": "apps/burnup/src"}, tmp_path)
        manifest = json.loads((app / "app.json").read_text())
        assert {k: manifest[k] for k in ("description", "icon", "name")} == {
            "description": "kept", "icon": "📈", "name": "Burnup"}

    def test_surfaces_the_build_log_and_installs_nothing(
            self, tmp_path, src, monkeypatch):
        self._stub(monkeypatch, {"ok": False, "error": "build failed",
                                 "log": "Unexpected token at main.tsx:3"})
        out = self._build({"slug": "burnup", "source": "apps/burnup/src"}, tmp_path)
        assert "main.tsx:3" in out and "call build_app again" in out
        assert not (tmp_path / "apps" / "burnup" / "index.html").exists()

    def test_warns_when_an_asset_could_not_be_inlined(
            self, tmp_path, src, monkeypatch):
        self._stub(monkeypatch, {"ok": True, "html": "x", "bytes": 1,
                                 "stray": ["logo-Bx1.png"]})
        out = self._build({"slug": "burnup", "source": "apps/burnup/src"}, tmp_path)
        assert "WARNING" in out and "logo-Bx1.png" in out

    def test_reports_an_unreachable_build_service(self, tmp_path, src, monkeypatch):
        def boom(name, **_):
            raise RuntimeError("no such deployment")

        monkeypatch.setattr(cycls, "remote", boom)
        out = self._build({"slug": "burnup", "source": "apps/burnup/src"}, tmp_path)
        assert "build service is unavailable" in out


class TestBuildAppHardening:
    """The build path used to fail silently, destructively, or not at all."""

    def _stub(self, monkeypatch, result):
        monkeypatch.setattr(cycls, "remote", lambda name, **_: (lambda **kw: result))

    def _build(self, inp, ws):
        return asyncio.run(tools._exec_build_app(inp, _ws(ws)))

    @pytest.fixture
    def src(self, tmp_path):
        d = tmp_path / "apps" / "burnup" / "src"
        d.mkdir(parents=True)
        (d / "index.html").write_text("<html>")
        return d

    @pytest.mark.parametrize("reply", [None, "a string", [], {"ok": True}, {"ok": True, "html": 7}])
    def test_a_malformed_reply_is_a_build_error_not_an_exception(
            self, tmp_path, src, monkeypatch, reply):
        self._stub(monkeypatch, reply)
        assert self._build({"slug": "burnup", "source": "apps/burnup/src"}, tmp_path
                           ).startswith("Build failed:")

    def test_a_failed_build_names_the_packages_that_were_available(
            self, tmp_path, src, monkeypatch):
        self._stub(monkeypatch, {"ok": False, "error": "no such module: zod",
                                 "log": "", "packages": ["zod", "sonner"]})
        assert "Available packages: zod, sonner." in self._build(
            {"slug": "burnup", "source": "apps/burnup/src"}, tmp_path)

    def test_a_rebuild_keeps_the_bundle_it_replaces(self, tmp_path, src, monkeypatch):
        self._stub(monkeypatch, {"ok": True, "html": "v1", "bytes": 2, "stray": []})
        self._build({"slug": "burnup", "source": "apps/burnup/src"}, tmp_path)
        self._stub(monkeypatch, {"ok": True, "html": "v2", "bytes": 2, "stray": []})
        self._build({"slug": "burnup", "source": "apps/burnup/src"}, tmp_path)
        assert (tmp_path / "apps" / "burnup" / "index.html").read_text() == "v2"
        kept = [p.read_text() for p in (tmp_path / ".trash").rglob("index.html")]
        assert "v1" in kept, "the replaced bundle must be recoverable"

    def test_the_manifest_records_what_produced_the_bundle(self, tmp_path, src, monkeypatch):
        self._stub(monkeypatch, {"ok": True, "html": "x", "bytes": 1, "stray": [],
                                 "version": "a5b4c9c40eb7"})
        self._build({"slug": "burnup", "source": "apps/burnup/src"}, tmp_path)
        built = json.loads((tmp_path / "apps" / "burnup" / "app.json").read_text())["built"]
        assert built["builder"] == "a5b4c9c40eb7"
        assert built["source"] == "apps/burnup/src" and built["at"].startswith("20")

    def test_an_older_builder_that_sends_no_version_still_installs(
            self, tmp_path, src, monkeypatch):
        self._stub(monkeypatch, {"ok": True, "html": "x", "bytes": 1, "stray": []})
        self._build({"slug": "burnup", "source": "apps/burnup/src"}, tmp_path)
        built = json.loads((tmp_path / "apps" / "burnup" / "app.json").read_text())["built"]
        assert built["builder"] == "unknown"

    def test_the_result_asks_for_the_data_contract(self, tmp_path, src, monkeypatch):
        self._stub(monkeypatch, {"ok": True, "html": "x", "bytes": 1, "stray": []})
        out = self._build({"slug": "burnup", "source": "apps/burnup/src"}, tmp_path)
        assert "apps/burnup/README.md" in out and "apps/burnup/data/" in out

    def test_an_oversized_file_is_refused_here_and_named(self, tmp_path):
        (tmp_path / "index.html").write_text("<html>")
        (tmp_path / "huge.tsx").write_text("x" * (tools._APP_SRC_MAX_FILE + 1))
        with pytest.raises(ValueError, match="huge.tsx"):
            tools._collect_source(tmp_path)


class TestAppCatalog:
    def test_lists_each_app_from_its_manifest(self, tmp_path):
        tools._apps_cache.clear()
        d = tmp_path / "apps" / "burnup"; d.mkdir(parents=True)
        (d / "app.json").write_text(json.dumps({"name": "Burn-up", "description": "Sprint burn-up"}))
        text = tools.app_catalog(str(tmp_path))
        assert "- burnup: Burn-up — Sprint burn-up" in text and "README.md" in text

    def test_a_workspace_with_no_apps_costs_nothing(self, tmp_path):
        tools._apps_cache.clear()
        assert tools.app_catalog(str(tmp_path)) == ""

    def test_a_broken_manifest_never_hides_the_app(self, tmp_path):
        tools._apps_cache.clear()
        d = tmp_path / "apps" / "burnup"; d.mkdir(parents=True)
        (d / "app.json").write_text("{broken")
        assert "- burnup: burnup" in tools.app_catalog(str(tmp_path))

    def test_the_scan_is_cached_because_the_volume_is_gcsfuse(self, tmp_path):
        tools._apps_cache.clear()
        (tmp_path / "apps").mkdir()
        assert tools.app_catalog(str(tmp_path)) == ""
        (tmp_path / "apps" / "late").mkdir()
        assert tools.app_catalog(str(tmp_path)) == "", "a second scan inside the TTL"


def test_the_manifest_carries_the_description_the_catalog_reads(tmp_path, monkeypatch):
    """Two readers wanted it and nothing wrote it, so every catalog line was bare."""
    (tmp_path / "apps" / "burnup" / "src").mkdir(parents=True)
    (tmp_path / "apps" / "burnup" / "src" / "index.html").write_text("<html>")
    monkeypatch.setattr(cycls, "remote",
                        lambda name, **_: (lambda **kw: {"ok": True, "html": "x", "bytes": 1, "stray": []}))
    asyncio.run(tools._exec_build_app(
        {"slug": "burnup", "source": "apps/burnup/src", "name": "Burn-up",
         "description": "Sprint burn-up over projects/*.json"}, _ws(tmp_path)))
    assert json.loads((tmp_path / "apps" / "burnup" / "app.json").read_text())[
        "description"] == "Sprint burn-up over projects/*.json"
    tools._apps_cache.clear()
    assert "Sprint burn-up over projects" in tools.app_catalog(str(tmp_path))
