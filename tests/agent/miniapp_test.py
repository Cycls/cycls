import asyncio
import json

import cycls
import pytest

from cycls._agent import tools


@pytest.fixture
def ws(tmp_path):
    app = tmp_path / "apps" / "injaz"
    app.mkdir(parents=True)
    (app / "index.html").write_text("<h1>x</h1>")
    return tmp_path


def entry(ws):
    return ws / "apps" / "injaz" / "index.html"


def manifest(ws, payload):
    (ws / "apps" / "injaz" / "app.json").write_text(
        payload if isinstance(payload, str) else json.dumps(payload))


class TestAppIdentity:
    def test_titleises_the_folder_without_a_manifest(self, ws):
        assert tools._app_identity(entry(ws), "index.html") == {"name": "Injaz"}

    def test_uses_the_manifest_name_and_emoji(self, ws):
        manifest(ws, {"name": "Injaz Portfolio", "icon": "📊"})
        assert tools._app_identity(entry(ws), "index.html") == {
            "name": "Injaz Portfolio", "icon": "📊"}

    def test_passes_an_image_icon_through(self, ws):
        manifest(ws, {"name": "Injaz", "icon": "logo.png"})
        assert tools._app_identity(entry(ws), "index.html")["icon"] == "logo.png"

    @pytest.mark.parametrize("bad", ["{broken", "[]", "null", '"str"'])
    def test_a_broken_manifest_never_hides_the_app(self, ws, bad):
        manifest(ws, bad)
        assert tools._app_identity(entry(ws), "index.html") == {"name": "Injaz"}

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
        monkeypatch.setattr(cycls, "remote", lambda name: (lambda **kw: result))

    def _build(self, inp, ws):
        return asyncio.run(tools._exec_build_app(inp, ws))

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
        assert json.loads((app / "app.json").read_text()) == {
            "name": "Vendor burn-up", "icon": "📈"}
        assert "Apps tab" in out

    def test_defaults_the_name_and_keeps_earlier_manifest_fields(
            self, tmp_path, src, monkeypatch):
        app = tmp_path / "apps" / "burnup"
        (app / "app.json").write_text(json.dumps({"description": "kept", "icon": "📈"}))
        self._stub(monkeypatch, {"ok": True, "html": "x", "bytes": 1, "stray": []})
        self._build({"slug": "burnup", "source": "apps/burnup/src"}, tmp_path)
        assert json.loads((app / "app.json").read_text()) == {
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
        def boom(name):
            raise RuntimeError("no such deployment")

        monkeypatch.setattr(cycls, "remote", boom)
        out = self._build({"slug": "burnup", "source": "apps/burnup/src"}, tmp_path)
        assert "build service is unavailable" in out
