"""The app catalog and the workspace's app theme (docs/notes/apps.md, "The catalog").

The stub app mounts the real routers with a header-switched fake auth, as workspaces_test does,
plus `apps={"catalog": <folder>}` — what `cycls.Web().apps(folder)` puts on the agent.
"""
import asyncio
import json
from types import SimpleNamespace

import pytest

from cycls._agent import catalog, state, trash
from cycls._app.auth import User

USERS = {
    "user_1": User(id="user_1", org_id="org_1"),
    "user_2": User(id="user_2", org_id="org_1"),
}


def _bundle(folder, slug, html="<html><head></head><body>v1</body></html>", **manifest):
    d = folder / slug
    (d / "src").mkdir(parents=True, exist_ok=True)
    (d / "index.html").write_text(html, encoding="utf-8")
    (d / "app.json").write_text(json.dumps({"name": slug.title(), **manifest}, ensure_ascii=False), encoding="utf-8")
    (d / "README.md").write_text(f"# {slug}\nRows task:<id>.", encoding="utf-8")
    (d / "src" / "App.tsx").write_text("export default () => null", encoding="utf-8")
    return d


@pytest.fixture
def shelf(tmp_path):
    folder = tmp_path / "image" / "default_apps"
    _bundle(folder, "tasks", name="Tasks", name_ar="المهام", icon="✅", category="Work", category_ar="العمل",
            description="Kanban of follow-ups", description_ar="لوحة المتابعات")
    _bundle(folder, "crm", name="CRM", icon="🤝", category="Sales")
    (folder / "broken").mkdir()            # no index.html: not an entry
    (folder / ".hidden").mkdir()           # not a slug
    return folder


def _client(tmp_path, folder, workspaces="member", theme=None):
    from fastapi import Depends, FastAPI, Request
    from fastapi.testclient import TestClient
    from cycls._agent.web.routers import install_routers

    def fake_auth(request: Request):
        return USERS[request.headers.get("x-test-user", "user_1")]

    vol = tmp_path / "vol"
    vol.mkdir(exist_ok=True)
    stub = SimpleNamespace(prod=False, _auth_provider=None,
                           apps={"catalog": str(folder), "theme": theme} if folder else None,
                           config=SimpleNamespace(workspaces=workspaces, max_upload=512))
    fapp = FastAPI()
    install_routers(stub, fapp, Depends(fake_auth), vol, f"file://{vol}")
    return TestClient(fapp), vol


def _personal(vol, user):
    from cycls._app.db import workspace
    return workspace(User(id=user, org_id="org_1"), vol, base=f"file://{vol}", ws=f"u-{user}").root


def _rows(client, h=None):
    return {a["slug"]: a for a in client.get("/apps/catalog", headers=h or {}).json()["apps"]}


# ---- the catalog as a list ----------------------------------------------------------------

def test_lists_every_bundle_with_its_metadata_and_state(tmp_path, shelf):
    client, _ = _client(tmp_path, shelf)
    body = client.get("/apps/catalog").json()
    assert body["admin"] is True                     # your personal workspace is yours
    rows = {a["slug"]: a for a in body["apps"]}
    assert set(rows) == {"tasks", "crm"}
    t = rows["tasks"]
    assert (t["name"], t["name_ar"], t["category_ar"], t["state"]) == ("Tasks", "المهام", "العمل", "available")
    assert len(t["version"]) == 12 and t["bytes"] == len("<html><head></head><body>v1</body></html>")


def test_no_catalog_declared_means_no_catalog_routes_but_a_theme(tmp_path):
    client, _ = _client(tmp_path, None)
    assert client.get("/apps/catalog").status_code == 404
    assert client.post("/apps/install", json={"slug": "tasks"}).status_code == 404
    assert client.get("/apps/theme").json() == {"theme": None, "default": None, "admin": True}


def test_the_literal_routes_do_not_shadow_app_data(tmp_path, shelf):
    """`/apps/catalog` is a literal path beside `/apps/{slug}/data`: an app called `catalog` keeps its rows."""
    client, _ = _client(tmp_path, shelf)
    assert client.put("/apps/catalog/data/k", json=1).status_code == 200
    assert client.get("/apps/catalog/data/k").json()["value"] == 1


# ---- install -------------------------------------------------------------------------------

def test_install_lands_the_bundle_as_build_app_would(tmp_path, shelf):
    client, vol = _client(tmp_path, shelf)
    r = client.post("/apps/install", json={"slug": "tasks"})
    assert r.status_code == 200 and r.json()["outcome"] == "installed"
    assert r.json()["entry"] == "apps/tasks/index.html"
    app = _personal(vol, "user_1") / "apps" / "tasks"
    assert (app / "index.html").read_text(encoding="utf-8").endswith("v1</body></html>")
    assert (app / "README.md").exists() and (app / "src" / "App.tsx").exists() and (app / "data").is_dir()
    m = json.loads((app / "app.json").read_text(encoding="utf-8"))
    assert m["name_ar"] == "المهام" and m["catalog"]["version"] == _rows(client)["tasks"]["version"]
    assert _rows(client)["tasks"]["state"] == "installed"
    assert client.post("/apps/install", json={"slug": "tasks"}).json()["outcome"] == "current"


def test_install_never_overwrites_a_users_own_app(tmp_path, shelf):
    client, vol = _client(tmp_path, shelf)
    mine = _personal(vol, "user_1") / "apps" / "tasks"
    mine.mkdir(parents=True)
    (mine / "index.html").write_text("my own", encoding="utf-8")
    assert _rows(client)["tasks"]["state"] == "conflict"
    assert client.post("/apps/install", json={"slug": "tasks"}).status_code == 409
    assert client.post("/apps/update", json={"slug": "tasks"}).status_code == 409
    assert client.post("/apps/uninstall", json={"slug": "tasks"}).status_code == 409
    assert (mine / "index.html").read_text(encoding="utf-8") == "my own"
    assert not (mine / "app.json").exists()


@pytest.mark.parametrize("slug", ["../tasks", "nope", "", None, "Tasks", "tasks/x"])
def test_only_a_slug_in_the_catalog_is_installable(tmp_path, shelf, slug):
    client, _ = _client(tmp_path, shelf)
    assert client.post("/apps/install", json={"slug": slug}).status_code == 404


def test_a_fresh_install_starts_on_an_empty_shelf(tmp_path, shelf):
    client, vol = _client(tmp_path, shelf)
    client.put("/apps/tasks/data/task-old", json={"from": "a dead app"})
    client.post("/apps/install", json={"slug": "tasks"})
    assert client.get("/apps/tasks/data").json()["rows"] == []


def test_the_legacy_default_app_stamp_reads_as_installed(tmp_path, shelf):
    """Workspaces super's agent-side installer (default_apps.py) seeded need no migration."""
    client, vol = _client(tmp_path, shelf)
    app = _personal(vol, "user_1") / "apps" / "tasks"
    app.mkdir(parents=True)
    (app / "index.html").write_bytes((shelf / "tasks" / "index.html").read_bytes())
    version = _rows(client)["tasks"]["version"]
    (app / "app.json").write_text(json.dumps({"name": "Tasks", "default_app": {"version": version}}), encoding="utf-8")
    assert _rows(client)["tasks"]["state"] == "installed"
    (app / "app.json").write_text(json.dumps({"name": "Tasks", "default_app": {"version": "old"}}), encoding="utf-8")
    assert _rows(client)["tasks"]["state"] == "update"
    assert client.post("/apps/update", json={"slug": "tasks"}).json()["outcome"] == "updated"
    m = json.loads((app / "app.json").read_text(encoding="utf-8"))
    assert "default_app" not in m and m["catalog"]["version"] == version


# ---- update --------------------------------------------------------------------------------

def test_update_replaces_the_bundle_keeps_data_name_and_icon_and_trashes_the_old(tmp_path, shelf):
    client, vol = _client(tmp_path, shelf)
    client.post("/apps/install", json={"slug": "tasks"})
    app = _personal(vol, "user_1") / "apps" / "tasks"
    m = json.loads((app / "app.json").read_text(encoding="utf-8"))
    (app / "app.json").write_text(json.dumps({**m, "name": "Our follow-ups", "icon": "📌"}), encoding="utf-8")
    (app / "data" / "export.csv").write_text("a,b", encoding="utf-8")
    client.put("/apps/tasks/data/task-1", json={"title": "keep me"})

    (shelf / "tasks" / "index.html").write_text("<html>v2</html>", encoding="utf-8")
    client2, _ = _client(tmp_path, shelf)          # a redeploy: the image changed, the process is new
    row = _rows(client2)["tasks"]
    assert row["state"] == "update" and row["installed_name"] == "Our follow-ups"
    assert client2.post("/apps/install", json={"slug": "tasks"}).json()["outcome"] == "current"   # install never updates
    assert client2.post("/apps/update", json={"slug": "tasks"}).json()["outcome"] == "updated"

    assert (app / "index.html").read_text(encoding="utf-8") == "<html>v2</html>"
    m = json.loads((app / "app.json").read_text(encoding="utf-8"))
    assert (m["name"], m["icon"]) == ("Our follow-ups", "📌")
    assert (app / "data" / "export.csv").read_text(encoding="utf-8") == "a,b"
    assert client2.get("/apps/tasks/data/task-1").json()["value"] == {"title": "keep me"}
    gone = [e for e in trash.list_trash(app.parent.parent) if e["path"] == "apps/tasks/index.html"]
    assert gone and gone[0]["reason"] == "update"


def test_update_of_an_app_not_installed_is_a_404(tmp_path, shelf):
    client, _ = _client(tmp_path, shelf)
    assert client.post("/apps/update", json={"slug": "crm"}).status_code == 404


# ---- uninstall -----------------------------------------------------------------------------

def test_uninstall_is_a_trash_move_and_restore_brings_it_back(tmp_path, shelf):
    client, vol = _client(tmp_path, shelf)
    client.post("/apps/install", json={"slug": "crm"})
    client.put("/apps/crm/data/deal-1", json={"v": 1})
    r = client.post("/apps/uninstall", json={"slug": "crm"})
    assert r.status_code == 200
    assert not (_personal(vol, "user_1") / "apps" / "crm").exists()
    assert _rows(client)["crm"]["state"] == "available"
    assert client.post(f"/trash/{r.json()['trash_id']}/restore").status_code == 200
    assert _rows(client)["crm"]["state"] == "installed"
    assert client.get("/apps/crm/data/deal-1").json()["value"] == {"v": 1}


def test_purging_an_old_entry_spares_the_rows_of_a_reinstalled_app(tmp_path, shelf):
    """Uninstall → reinstall → empty the trash: the purge must not take the new app's rows.
    (The same held for build_app on a reused slug before the guard in `_drop_app_data`.)"""
    client, _ = _client(tmp_path, shelf)
    client.post("/apps/install", json={"slug": "crm"})
    tid = client.post("/apps/uninstall", json={"slug": "crm"}).json()["trash_id"]
    client.post("/apps/install", json={"slug": "crm"})
    client.put("/apps/crm/data/deal-new", json={"v": 2})
    assert client.delete(f"/trash/{tid}").status_code == 200
    assert client.get("/apps/crm/data/deal-new").json()["value"] == {"v": 2}


# ---- who may ------------------------------------------------------------------------------

def _team(client):
    ws = client.post("/workspaces", json={"name": "Sales"}).json()["id"]   # user_1 owns it
    client.put(f"/workspaces/{ws}/members/user_2", json={"role": "editor"})
    return ws, {"X-Workspace": ws}, {"X-Workspace": ws, "X-Test-User": "user_2"}


def test_in_a_team_workspace_only_admins_change_the_catalog_or_theme(tmp_path, shelf):
    client, _ = _client(tmp_path, shelf)
    ws, owner, member = _team(client)
    assert client.get("/apps/catalog", headers=member).json()["admin"] is False
    for path in ("/apps/install", "/apps/update", "/apps/uninstall"):
        assert client.post(path, json={"slug": "tasks"}, headers=member).status_code == 403, path
    assert client.put("/apps/theme", json={"theme": {"base": "zinc"}}, headers=member).status_code == 403

    assert client.post("/apps/install", json={"slug": "tasks"}, headers=owner).status_code == 200
    assert _rows(client, member)["tasks"]["state"] == "installed"        # one copy for the whole team
    assert client.post("/apps/uninstall", json={"slug": "tasks"}, headers=member).status_code == 403


# ---- theme --------------------------------------------------------------------------------

def test_theme_round_trip_is_the_workspaces_choice(tmp_path, shelf):
    client, _ = _client(tmp_path, shelf, theme={"base": "stone"})
    ws, owner, member = _team(client)
    assert client.get("/apps/theme", headers=owner).json()["theme"] is None
    assert client.get("/apps/theme", headers=owner).json()["default"]["base"] == "stone"
    put = client.put("/apps/theme", json={"theme": {"base": "zinc", "color": "violet", "radius": 0.5, "primary": "#0B6B5D"}},
                     headers=owner)
    assert put.status_code == 200
    want = {"base": "zinc", "color": "violet", "radius": 0.5, "primary": "#0b6b5d"}
    assert client.get("/apps/theme", headers=member).json()["theme"] == want     # every member's apps wear it
    assert client.get("/apps/theme").json()["theme"] is None                     # another workspace does not
    assert client.put("/apps/theme", json={"theme": None}, headers=owner).json() == {"ok": True, "theme": None}
    assert client.get("/apps/theme", headers=member).json()["theme"] is None


@pytest.mark.parametrize("bad", [
    {"base": "purple"}, {"color": "teal"}, {"radius": 3}, {"radius": True}, {"radius": "0.5"},
    {"primary": "red"}, {"primary": "#fff"}, {"primary": "#12345g"}, "zinc", [],
])
def test_a_bad_theme_is_refused_naming_the_field(tmp_path, shelf, bad):
    client, _ = _client(tmp_path, shelf)
    r = client.put("/apps/theme", json={"theme": bad})
    assert r.status_code == 400 and r.json()["detail"]


def test_the_theme_row_cannot_collide_with_an_app(tmp_path, shelf):
    """`.theme` sits in the `.apps` slot, outside every slug's prefix: build_app's slugs have no dot."""
    client, _ = _client(tmp_path, shelf)
    client.put("/apps/theme", json={"theme": {"base": "slate"}})
    assert client.get("/apps/tasks/data").json()["rows"] == []
    assert not catalog.valid_slug(catalog.THEME_KEY)


# ---- the builder --------------------------------------------------------------------------

def test_web_apps_ships_the_folder_and_turns_the_section_on(tmp_path, monkeypatch):
    import cycls
    monkeypatch.chdir(tmp_path)
    (tmp_path / "default_apps").mkdir()
    web = cycls.Web().auth(cycls.JWT(jwks_url="https://example.com/jwks")).apps(
        "default_apps", theme={"base": "zinc"})
    assert web._apps == {"catalog": "default_apps",
                         "theme": {"base": "zinc", "color": "base", "radius": 0.625}}
    assert isinstance(web._apps["catalog"], str)          # never a Path: it rides the pickle


@pytest.mark.parametrize("bad", ["", "/abs/apps", "../apps"])
def test_web_apps_wants_a_relative_folder(bad):
    import cycls
    with pytest.raises(ValueError):
        cycls.Web().apps(bad)


def test_catalog_module_reads_once_per_process(tmp_path, shelf):
    c = catalog.Catalog(shelf)
    first = c.entries()
    _bundle(shelf, "later")
    assert c.entries() is first and "later" not in c.entries()
