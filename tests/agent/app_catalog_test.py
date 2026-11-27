"""Ready-made apps (cycls/_agent/catalog.py, docs/notes/apps.md "Ready-made apps"): the real routers on a stub agent
with `apps_folder`, what `cycls.Web().apps(folder)` puts on it, and a header-switched fake auth."""
import json
from types import SimpleNamespace

import pytest

from cycls._agent import trash
from cycls._app.auth import User

USERS = {u: User(id=u, org_id="org_1") for u in ("user_1", "user_2")}


def _bundle(folder, slug, html="<html><body>v1</body></html>", **manifest):
    d = folder / slug
    (d / "src").mkdir(parents=True, exist_ok=True)
    (d / "index.html").write_text(html, encoding="utf-8")
    (d / "app.json").write_text(json.dumps({"name": slug.title(), **manifest}, ensure_ascii=False), encoding="utf-8")
    (d / "README.md").write_text(f"# {slug}", encoding="utf-8")
    (d / "src" / "App.tsx").write_text("export default () => null", encoding="utf-8")
    return d


@pytest.fixture
def shelf(tmp_path):
    folder = tmp_path / "apps-volume"
    _bundle(folder, "tasks", name="Tasks", name_ar="المهام", description="Who does what", category="Work")
    _bundle(folder, "crm", name="CRM")
    (folder / "broken").mkdir()   # no index.html: not an app
    return folder


def _client(tmp_path, folder, cms=None):
    from fastapi import Depends, FastAPI, Request
    from fastapi.testclient import TestClient
    from cycls._agent.web.routers import install_routers

    def fake_auth(request: Request):
        return USERS[request.headers.get("x-test-user", "user_1")]

    vol = tmp_path / "vol"
    vol.mkdir(exist_ok=True)
    stub = SimpleNamespace(prod=False, _auth_provider=None, apps_folder=str(folder),
                           config=SimpleNamespace(workspaces="member", max_upload=512, cms=cms))
    fapp = FastAPI()
    install_routers(stub, fapp, Depends(fake_auth), vol, f"file://{vol}")
    return TestClient(fapp), vol


def _app(vol, slug, user="user_1"):
    from cycls._app.db import workspace
    return workspace(USERS[user], vol, base=f"file://{vol}", ws=f"u-{user}").root / "apps" / slug


def _states(client, h=None):
    return {a["slug"]: a["state"] for a in client.get("/apps/catalog", headers=h or {}).json()["apps"]}


def test_a_workspace_installs_a_bundle_as_build_app_lands_an_app(tmp_path, shelf):
    client, vol = _client(tmp_path, shelf)
    listed = client.get("/apps/catalog").json()
    assert listed["admin"] is True and [a["slug"] for a in listed["apps"]] == ["crm", "tasks"]
    assert listed["apps"][1]["title"] == {"en": "Tasks", "ar": "المهام"} and listed["apps"][1]["state"] == "available"
    client.put("/apps/tasks/data/task-old", json={"from": "a dead app at that name"})

    r = client.post("/apps/install", json={"slug": "tasks"})
    assert r.status_code == 200 and r.json()["entry"] == "apps/tasks/index.html"
    app = _app(vol, "tasks")
    assert (app / "index.html").read_text(encoding="utf-8") == "<html><body>v1</body></html>"
    assert (app / "README.md").exists() and (app / "src" / "App.tsx").exists() and (app / "data").is_dir()
    m = json.loads((app / "app.json").read_text(encoding="utf-8"))
    assert (m["name"], m["name_ar"], m["description"]) == ("Tasks", "المهام", "Who does what") and m["catalog"]["version"]
    assert client.get("/apps/tasks/data").json()["rows"] == []   # a fresh install starts on an empty shelf
    assert _states(client)["tasks"] == "installed"
    assert client.get("/apps/catalog/tasks/preview").text == "<html><body>v1</body></html>"
    assert client.post("/apps/install", json={"slug": "nope"}).status_code == 404


def test_an_update_keeps_the_data_name_and_icon_and_trashes_the_page_it_replaces(tmp_path, shelf):
    client, vol = _client(tmp_path, shelf)
    client.post("/apps/install", json={"slug": "tasks"})
    app = _app(vol, "tasks")
    m = json.loads((app / "app.json").read_text(encoding="utf-8"))
    (app / "app.json").write_text(json.dumps({**m, "name": "Our follow-ups", "icon": "📌"}), encoding="utf-8")
    client.put("/apps/tasks/data/task-1", json={"title": "keep me"})

    (shelf / "tasks" / "index.html").write_text("<html><body>v2</body></html>", encoding="utf-8")
    assert _states(client)["tasks"] == "update"
    assert client.post("/apps/install", json={"slug": "tasks"}).status_code == 200
    assert (app / "index.html").read_text(encoding="utf-8") == "<html><body>v2</body></html>"
    m = json.loads((app / "app.json").read_text(encoding="utf-8"))
    assert (m["name"], m["icon"]) == ("Our follow-ups", "📌")
    assert client.get("/apps/tasks/data/task-1").json()["value"] == {"title": "keep me"}
    assert [e["reason"] for e in trash.list_trash(app.parent.parent) if e["path"] == "apps/tasks/index.html"] == ["update"]


def test_a_new_name_in_the_gallery_is_an_update_that_spares_a_name_the_person_chose(tmp_path, shelf):
    client, vol = _client(tmp_path, shelf)
    for slug in ("tasks", "crm"):
        client.post("/apps/install", json={"slug": slug})
    crm = _app(vol, "crm") / "app.json"
    crm.write_text(json.dumps({**json.loads(crm.read_text(encoding="utf-8")), "name": "Our clients"}), encoding="utf-8")
    for slug, name in (("tasks", "Tasks & Follow-ups"), ("crm", "Customers")):
        _bundle(shelf, slug, name=name)   # renamed in the gallery, the page as it was
    assert _states(client) == {"crm": "update", "tasks": "update"}
    for slug in ("tasks", "crm"):
        client.post("/apps/install", json={"slug": slug})
    names = {s: json.loads((_app(vol, s) / "app.json").read_text(encoding="utf-8"))["name"] for s in ("tasks", "crm")}
    assert names == {"tasks": "Tasks & Follow-ups", "crm": "Our clients"}
    assert _states(client) == {"crm": "installed", "tasks": "installed"}


def test_an_app_changed_here_gets_no_update_and_a_persons_own_is_never_touched(tmp_path, shelf):
    client, vol = _client(tmp_path, shelf)
    client.post("/apps/install", json={"slug": "tasks"})
    app = _app(vol, "tasks")
    m = json.loads((app / "app.json").read_text(encoding="utf-8"))
    (app / "app.json").write_text(json.dumps({**m, "built": {"at": "2026-11-27"}}), encoding="utf-8")   # the agent rebuilt it
    (app / "index.html").write_text("ours now", encoding="utf-8")
    (shelf / "tasks" / "index.html").write_text("<html><body>v2</body></html>", encoding="utf-8")

    mine = _app(vol, "crm")
    mine.mkdir(parents=True)
    (mine / "index.html").write_text("my own", encoding="utf-8")
    assert _states(client) == {"crm": "taken", "tasks": "changed"}
    for slug in ("tasks", "crm"):
        assert client.post("/apps/install", json={"slug": slug}).status_code == 409
    assert (app / "index.html").read_text(encoding="utf-8") == "ours now" and (mine / "index.html").read_text(encoding="utf-8") == "my own"


def test_the_cms_says_what_is_offered_in_its_order_and_a_failed_read_keeps_the_last(tmp_path, shelf, monkeypatch):
    from cycls._agent.web import routers
    rows = [{"slug": "tasks", "title": {"en": "Tasks & Follow-ups", "ar": "المهام والمتابعات"}, "description": {"en": "", "ar": ""},
             "category": {"en": "Work", "ar": "العمل"}, "icon": '<svg viewBox="0 0 24 24"><path d="M4 6h16"/></svg>',
             "picture": "/files/t.webp", "featured": True},
            {"slug": "gone", "title": {"en": "Not on the volume", "ar": ""}}]
    reads = []

    async def cms(url, token=None):
        reads.append(url)
        if len(reads) > 1:
            raise RuntimeError("down")
        return {"apps": rows}
    monkeypatch.setattr(routers, "_cms_get", cms)
    monkeypatch.setattr(routers, "EXAMPLES_TTL", -1)
    client, vol = _client(tmp_path, shelf, cms={"apps": "https://cms.test/site/apps/super"})
    for _ in range(2):   # the second read fails: the last good one stands
        (a,) = client.get("/apps/catalog").json()["apps"]
        assert a["slug"] == "tasks" and a["picture"] == "https://cms.test/files/t.webp"
    client.post("/apps/install", json={"slug": "tasks"})
    m = json.loads((_app(vol, "tasks") / "app.json").read_text(encoding="utf-8"))
    assert m["name_ar"] == "المهام والمتابعات" and m["icon"].startswith("data:image/svg+xml;utf8,%3Csvg")


def test_only_admins_install_and_the_look_is_one_of_a_few(tmp_path, shelf):
    client, _ = _client(tmp_path, shelf)
    ws = client.post("/workspaces", json={"name": "Sales"}).json()["id"]   # user_1 owns it
    client.put(f"/workspaces/{ws}/members/user_2", json={"role": "editor"})
    owner, member = {"X-Workspace": ws}, {"X-Workspace": ws, "X-Test-User": "user_2"}
    assert client.get("/apps/catalog", headers=member).json()["admin"] is False
    assert client.post("/apps/install", json={"slug": "tasks"}, headers=member).status_code == 403
    assert client.put("/apps/look", json={"look": "ocean"}, headers=member).status_code == 403
    assert client.post("/apps/install", json={"slug": "tasks"}, headers=owner).status_code == 200
    assert _states(client, member)["tasks"] == "installed"   # one copy for the whole team

    assert client.get("/apps/look", headers=member).json()["look"] is None   # until an admin picks one, each app's own
    assert client.put("/apps/look", json={"look": "custom", "color": "#0B6B5D"}, headers=owner).json()["look"] == {"look": "custom", "color": "#0b6b5d"}
    assert client.get("/apps/look", headers=member).json()["look"]["color"] == "#0b6b5d"
    for bad in ({"look": "neon"}, {"look": "custom"}, {"look": "custom", "color": "red"}, []):
        assert client.put("/apps/look", json=bad, headers=owner).status_code == 400


def test_web_apps_ships_a_folder_beside_the_agent_and_reads_a_mount_live(tmp_path, monkeypatch):
    import cycls
    monkeypatch.chdir(tmp_path)
    (tmp_path / "default_apps").mkdir()

    async def fn(context):
        yield ""
    web = cycls.Web().auth(cycls.JWT(jwks_url="https://example.com/jwks"))
    shipped = cycls.agent(web=web.apps("default_apps"), name="t", volumes={"/workspace": cycls.Volume("t")})(fn)
    assert shipped.apps_folder == "default_apps" and shipped.config.apps_catalog
    mounted = cycls.agent(web=web.apps("/apps"), name="t", volumes={"/workspace": cycls.Volume("t"), "/apps": cycls.Volume("apps").read_only()})(fn)
    assert mounted.apps_folder == "/apps"
    for bad in ("", "../apps", "/apps/../etc"):
        with pytest.raises(ValueError):
            web.apps(bad)
