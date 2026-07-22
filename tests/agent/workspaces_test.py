"""Multi-workspace Phase 2 — registry, ACL, team workspaces, admin lifecycle.

Spec: docs/workspaces.md. The stub app mounts the real routers with a
header-switched fake auth (`X-Test-User`) so one client can act as several
org members: a regular member, a second member, an org admin, and an
outsider from another org.
"""
import asyncio

from cycls.agent import state
from cycls.app.auth import User

USERS = {
    "user_1": User(id="user_1", org_id="org_1"),
    "user_2": User(id="user_2", org_id="org_1"),
    "admin_1": User(id="admin_1", org_id="org_1", org_role="admin"),
    "outsider": User(id="outsider", org_id="org_2"),
    "solo": User(id="solo"),   # no org
}


def _run(coro):
    return asyncio.run(coro)


def _orgdb(tmp_path, org="org_1"):
    return state.org_db(org, tmp_path, f"file://{tmp_path}")


def _client(tmp_path, workspaces="member"):
    from types import SimpleNamespace
    from fastapi import Depends, FastAPI, Request
    from fastapi.testclient import TestClient
    from cycls.agent.web.routers import install_routers

    def fake_auth(request: Request):
        return USERS[request.headers.get("x-test-user", "user_1")]

    stub = SimpleNamespace(prod=False, _auth_provider=None,
                           config=SimpleNamespace(workspaces=workspaces, max_upload=512))
    fapp = FastAPI()
    install_routers(stub, fapp, Depends(fake_auth), tmp_path, f"file://{tmp_path}")
    return TestClient(fapp)


def _mk_team(client, name="Research", as_user="user_1"):
    r = client.post("/workspaces", json={"name": name}, headers={"X-Test-User": as_user})
    assert r.status_code == 200, r.text
    return r.json()["id"]


# ---------------------------------------------------------------------------
# state.resolve_role — the access matrix
# ---------------------------------------------------------------------------

def test_resolve_role_personal_owner_only(tmp_path):
    orgdb = _orgdb(tmp_path)
    assert _run(state.resolve_role(USERS["user_1"], "u-user_1", orgdb)) == "owner"
    assert _run(state.resolve_role(USERS["user_2"], "u-user_1", orgdb)) is None
    # org admin gets NO content role on someone else's personal workspace
    assert _run(state.resolve_role(USERS["admin_1"], "u-user_1", orgdb)) is None


def test_resolve_role_team_membership(tmp_path):
    orgdb = _orgdb(tmp_path)
    row = _run(state.create_team_ws(orgdb, "Research", "user_1"))
    ws_id = row["id"]
    assert _run(state.resolve_role(USERS["user_1"], ws_id, orgdb)) == "owner"
    assert _run(state.resolve_role(USERS["user_2"], ws_id, orgdb)) is None
    # org admin: implicit admin on any registered team workspace
    assert _run(state.resolve_role(USERS["admin_1"], ws_id, orgdb)) == "admin"
    # unknown team: nothing, even for the admin
    assert _run(state.resolve_role(USERS["admin_1"], "t-unknown", orgdb)) is None


def test_member_of_scans_across_teams(tmp_path):
    orgdb = _orgdb(tmp_path)
    a = _run(state.create_team_ws(orgdb, "A", "user_1"))["id"]
    b = _run(state.create_team_ws(orgdb, "B", "user_2"))["id"]
    _run(orgdb.put(f"members/{b}/user_1", {"role": "editor"}))
    assert sorted(_run(state.member_of(orgdb, "user_1"))) == sorted([a, b])
    assert _run(state.member_of(orgdb, "outsider")) == []


# ---------------------------------------------------------------------------
# /workspaces — create, list, rename
# ---------------------------------------------------------------------------

def test_create_team_and_list(tmp_path):
    client = _client(tmp_path)
    ws_id = _mk_team(client)
    assert ws_id.startswith("t-")
    rows = client.get("/workspaces").json()
    assert rows[0] == {"id": "u-user_1", "name": "Personal", "type": "personal", "role": "owner"}
    team = next(r for r in rows if r["id"] == ws_id)
    assert team["name"] == "Research" and team["role"] == "owner"
    # user_2 is not a member — sees only their personal + the builtin General
    rows2 = client.get("/workspaces", headers={"X-Test-User": "user_2"}).json()
    assert [r["id"] for r in rows2] == ["u-user_2", "t-shared"]


def test_create_policy_admin_mode(tmp_path):
    client = _client(tmp_path, workspaces="admin")
    r = client.post("/workspaces", json={"name": "X"})
    assert r.status_code == 403
    r = client.post("/workspaces", json={"name": "X"}, headers={"X-Test-User": "admin_1"})
    assert r.status_code == 200


def test_create_requires_org(tmp_path):
    client = _client(tmp_path)
    r = client.post("/workspaces", json={"name": "X"}, headers={"X-Test-User": "solo"})
    assert r.status_code == 400


def test_create_validates_name(tmp_path):
    client = _client(tmp_path)
    assert client.post("/workspaces", json={"name": ""}).status_code == 400
    assert client.post("/workspaces", json={"name": "x" * 81}).status_code == 400


def test_workspace_name_unique_per_org(tmp_path):
    """Duplicate names 409 on create and rename (case-insensitive); keeping
    your own name on PATCH is fine; 'Personal' is reserved."""
    client = _client(tmp_path)
    ws_id = _mk_team(client, "Research")
    assert client.post("/workspaces", json={"name": "Research"}).status_code == 409
    assert client.post("/workspaces", json={"name": "research"}).status_code == 409
    assert client.post("/workspaces", json={"name": "Personal"}).status_code == 409
    other = _mk_team(client, "Design")
    assert client.patch(f"/workspaces/{other}", json={"name": "RESEARCH"}).status_code == 409
    # self-rename to the same name is not a conflict
    assert client.patch(f"/workspaces/{ws_id}", json={"name": "Research"}).status_code == 200
    # General is registered — its name collides too
    assert client.post("/workspaces", json={"name": "General"}).status_code == 409


def test_workspace_icon_lifecycle(tmp_path):
    """Create with an emoji icon, see it in the list, PATCH a new one,
    clear it with icon: "" — old rows never grow an icon key."""
    client = _client(tmp_path)
    r = client.post("/workspaces", json={"name": "Launch", "icon": "🚀"})
    assert r.status_code == 200 and r.json()["icon"] == "🚀"
    ws_id = r.json()["id"]

    team = next(w for w in client.get("/workspaces").json() if w["id"] == ws_id)
    assert team["icon"] == "🚀"

    r = client.patch(f"/workspaces/{ws_id}", json={"icon": "🔬"})
    assert r.json()["icon"] == "🔬" and r.json()["name"] == "Launch"
    # rename alone leaves the icon in place
    assert client.patch(f"/workspaces/{ws_id}", json={"name": "Lab"}).json()["icon"] == "🔬"

    r = client.patch(f"/workspaces/{ws_id}", json={"icon": ""})
    assert "icon" not in r.json()
    assert "icon" not in next(w for w in client.get("/workspaces").json() if w["id"] == ws_id)

    # icon-less create stays icon-less; oversized icon is a 400
    plain = client.post("/workspaces", json={"name": "Plain"}).json()
    assert "icon" not in plain
    assert client.post("/workspaces", json={"name": "X", "icon": "x" * 65}).status_code == 400


def test_builtin_general_member_routes_400(tmp_path):
    """General's membership IS the org — member operations are rejected so
    clients can't write rows that mislead."""
    client = _client(tmp_path)
    client.get("/workspaces")   # provisions General
    admin = {"X-Test-User": "admin_1"}
    assert client.get("/workspaces/t-shared/members").status_code == 400
    assert client.put("/workspaces/t-shared/members/user_2", json={"role": "editor"}, headers=admin).status_code == 400
    assert client.delete("/workspaces/t-shared/members/user_2", headers=admin).status_code == 400


def test_builtin_roles_ignore_member_rows(tmp_path):
    """A stray member row on General (pre-enforcement junk) must not change
    anyone's role — org membership alone decides."""
    orgdb = _orgdb(tmp_path)
    _run(orgdb.put("workspaces/t-shared", {"id": "t-shared", "name": "General", "type": "team", "builtin": "org"}))
    _run(orgdb.put("members/t-shared/admin_1", {"role": "editor"}))   # would downgrade the admin
    _run(orgdb.put("members/t-shared/user_1", {"role": "admin"}))     # would elevate a member
    assert _run(state.resolve_role(USERS["admin_1"], "t-shared", orgdb)) == "admin"
    assert _run(state.resolve_role(USERS["user_1"], "t-shared", orgdb)) == "editor"
    assert _run(state.resolve_role(USERS["solo"], "t-shared", orgdb)) is None


def test_builtin_general_name_locked_icon_open(tmp_path):
    """General can't be renamed; org admins may set its icon; members can't."""
    client = _client(tmp_path)
    client.get("/workspaces")   # provisions General
    admin = {"X-Test-User": "admin_1"}
    assert client.patch("/workspaces/t-shared", json={"name": "HQ"}, headers=admin).status_code == 400
    r = client.patch("/workspaces/t-shared", json={"icon": "🏠"}, headers=admin)
    assert r.status_code == 200 and r.json()["icon"] == "🏠"
    assert client.patch("/workspaces/t-shared", json={"icon": "🚀"}).status_code == 403   # plain member


def test_workspace_icon_emoji_only(tmp_path):
    """One shared icon vocabulary across clients: single emoji only —
    ZWJ sequences, flags, skin tones, keycaps pass; text and URLs 400."""
    client = _client(tmp_path)
    for i, good in enumerate(["🚀", "👨‍👩‍👧‍👦", "🇸🇦", "1️⃣", "👍🏽", "✍️", "⭐"]):
        r = client.post("/workspaces", json={"name": f"G{i}", "icon": good})
        assert r.status_code == 200, (good, r.text)
        assert r.json()["icon"] == good
    for bad in ["abc", "x", "https://x.com/a.png", "a🚀", "🚀🚀🚀🚀🚀", ":)"]:
        assert client.post("/workspaces", json={"name": "B", "icon": bad}).status_code == 400, bad


def test_rename_requires_manager(tmp_path):
    client = _client(tmp_path)
    ws_id = _mk_team(client)
    client.put(f"/workspaces/{ws_id}/members/user_2", json={"role": "editor"})
    r = client.patch(f"/workspaces/{ws_id}", json={"name": "New"},
                     headers={"X-Test-User": "user_2"})
    assert r.status_code == 403
    r = client.patch(f"/workspaces/{ws_id}", json={"name": "New"})
    assert r.status_code == 200 and r.json()["name"] == "New"


def test_admin_lifecycle_listing(tmp_path):
    client = _client(tmp_path)
    ws_id = _mk_team(client)
    # user_2 touches their personal workspace so its dir exists
    client.put("/files/hi.txt", files={"file": ("hi.txt", b"x")},
               headers={"X-Test-User": "user_2"})
    rows = client.get("/workspaces?all=1", headers={"X-Test-User": "admin_1"}).json()
    ids = {r["id"] for r in rows}
    assert {ws_id, "u-admin_1", "u-user_2"} <= ids
    # non-admins don't get the lifecycle view
    rows = client.get("/workspaces?all=1").json()
    assert "u-user_2" not in {r["id"] for r in rows}


# ---------------------------------------------------------------------------
# Team content access end-to-end (X-Workspace on chats/files)
# ---------------------------------------------------------------------------

def test_team_access_via_membership(tmp_path):
    client = _client(tmp_path)
    ws_id = _mk_team(client)
    h1 = {"X-Workspace": ws_id}
    h2 = {"X-Workspace": ws_id, "X-Test-User": "user_2"}

    # owner writes a file into the team workspace
    r = client.put("/files/plan.md", files={"file": ("plan.md", b"go")}, headers=h1)
    assert r.status_code == 200
    assert (tmp_path / "org_1" / "ws" / ws_id / "plan.md").read_bytes() == b"go"

    # non-member: 404 before, 200 after being added
    assert client.get("/files", headers=h2).status_code == 404
    client.put(f"/workspaces/{ws_id}/members/user_2", json={"role": "editor"})
    names = [f["name"] for f in client.get("/files", headers=h2).json()]
    assert names == ["plan.md"]

    # outsider from another org never resolves the team (their org has no row)
    r = client.get("/files", headers={"X-Workspace": ws_id, "X-Test-User": "outsider"})
    assert r.status_code == 404


def test_org_admin_gets_team_content_but_not_personal(tmp_path):
    client = _client(tmp_path)
    ws_id = _mk_team(client)
    admin = {"X-Test-User": "admin_1"}
    assert client.get("/files", headers={**admin, "X-Workspace": ws_id}).status_code == 200
    # lifecycle-only: someone else's personal content stays 404 for the admin
    client.put("/files/secret.txt", files={"file": ("secret.txt", b"s")})   # user_1 personal
    r = client.get("/files", headers={**admin, "X-Workspace": "u-user_1"})
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Members
# ---------------------------------------------------------------------------

def test_member_management_and_owner_protection(tmp_path):
    client = _client(tmp_path)
    ws_id = _mk_team(client)
    client.put(f"/workspaces/{ws_id}/members/user_2", json={"role": "editor"})

    members = client.get(f"/workspaces/{ws_id}/members").json()
    assert {m["user_id"]: m["role"] for m in members} == {"user_1": "owner", "user_2": "editor"}

    # editors can't manage members
    r = client.put(f"/workspaces/{ws_id}/members/outsider", json={"role": "editor"},
                   headers={"X-Test-User": "user_2"})
    assert r.status_code == 403

    # the owner row is immutable
    assert client.put(f"/workspaces/{ws_id}/members/user_1",
                      json={"role": "editor"}).status_code == 403
    assert client.delete(f"/workspaces/{ws_id}/members/user_1").status_code == 403

    # members can leave; access drops immediately
    r = client.delete(f"/workspaces/{ws_id}/members/user_2", headers={"X-Test-User": "user_2"})
    assert r.status_code == 200
    r = client.get("/files", headers={"X-Workspace": ws_id, "X-Test-User": "user_2"})
    assert r.status_code == 404


def test_invalid_role_rejected(tmp_path):
    client = _client(tmp_path)
    ws_id = _mk_team(client)
    r = client.put(f"/workspaces/{ws_id}/members/user_2", json={"role": "owner"})
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# Delete / wipe
# ---------------------------------------------------------------------------

def test_delete_team_requires_owner(tmp_path):
    client = _client(tmp_path)
    ws_id = _mk_team(client)
    client.put(f"/workspaces/{ws_id}/members/user_2", json={"role": "admin"})
    # ws-level admin manages members, but delete stays with the owner (+ org admin)
    r = client.delete(f"/workspaces/{ws_id}", headers={"X-Test-User": "user_2"})
    assert r.status_code == 403

    client.put("/files/a.txt", files={"file": ("a.txt", b"a")}, headers={"X-Workspace": ws_id})
    assert client.delete(f"/workspaces/{ws_id}").status_code == 200
    assert not (tmp_path / "org_1" / "ws" / ws_id).exists()
    # registry + ACL rows are gone: the team resolves for nobody
    r = client.get("/files", headers={"X-Workspace": ws_id})
    assert r.status_code == 404
    assert _run(_orgdb(tmp_path).get(f"workspaces/{ws_id}")) is None


def test_org_admin_can_delete_team(tmp_path):
    client = _client(tmp_path)
    ws_id = _mk_team(client)
    r = client.delete(f"/workspaces/{ws_id}", headers={"X-Test-User": "admin_1"})
    assert r.status_code == 200


def test_personal_delete_lifecycle(tmp_path):
    client = _client(tmp_path)
    client.put("/files/mine.txt", files={"file": ("mine.txt", b"m")})   # user_1 personal
    root = tmp_path / "org_1" / "ws" / "u-user_1"
    assert root.exists()

    # another member can't delete it — 404, no existence leak
    r = client.delete("/workspaces/u-user_1", headers={"X-Test-User": "user_2"})
    assert r.status_code == 404

    # org admin can (offboarding), despite never having content access
    r = client.delete("/workspaces/u-user_1", headers={"X-Test-User": "admin_1"})
    assert r.status_code == 200
    assert not root.exists()


def test_workspaces_router_absent_in_legacy_mode(tmp_path):
    client = _client(tmp_path, workspaces=None)
    assert client.get("/workspaces").status_code == 404


# ---------------------------------------------------------------------------
# Legacy migration (t-shared) + builtin org role
# ---------------------------------------------------------------------------

def _seed_legacy(tmp_path, org="org_1", user="user_1"):
    """A pre-workspaces tree: loose files + per-user chat DB at the org root."""
    from cycls.app.db import workspace
    root = tmp_path / org
    root.mkdir(parents=True, exist_ok=True)
    (root / "report.md").write_text("legacy")
    legacy_ws = workspace(f"{org}:{user}" if org != user else user,
                          tmp_path, base=f"file://{tmp_path}")
    _run(state.put_meta(legacy_ws, "c1", {"id": "c1", "title": "Old chat"}))
    _run(state.append_messages(legacy_ws, "c1", [{"role": "user", "content": "hi"}], 0))


def test_migration_moves_org_root_into_t_shared(tmp_path):
    _seed_legacy(tmp_path)
    client = _client(tmp_path)

    rows = client.get("/workspaces").json()   # first touch triggers the move
    shared = next(r for r in rows if r["id"] == "t-shared")
    assert shared["builtin"] == "org" and shared["role"] == "editor"

    # files now live inside t-shared, reachable by every org member; chats
    # stay per-user within the workspace — only their owner sees them there
    h = {"X-Workspace": "t-shared", "X-Test-User": "user_2"}
    assert [f["name"] for f in client.get("/files", headers=h).json()] == ["report.md"]
    assert client.get("/chats", headers=h).json() == []
    h1 = {"X-Workspace": "t-shared"}
    assert [c["id"] for c in client.get("/chats", headers=h1).json()] == ["c1"]
    # the org root itself is clean (only the new layout + org rows remain)
    import os as _os
    assert set(_os.listdir(tmp_path / "org_1")) == {"ws", ".org"}
    # personal workspaces start empty
    assert client.get("/chats").json() == []
    # org admin holds implicit admin on the builtin workspace
    rows = client.get("/workspaces", headers={"X-Test-User": "admin_1"}).json()
    assert next(r for r in rows if r["id"] == "t-shared")["role"] == "admin"


def test_migration_retry_merges_instead_of_nesting(tmp_path):
    """A retried move (interrupted copy left a partial dest) merges — it must
    not nest src under the existing dest dir, and the original file wins."""
    src = tmp_path / "root" / "docs"
    src.mkdir(parents=True)
    (src / "a.txt").write_text("original")
    (src / "b.txt").write_text("b")
    dst = tmp_path / "dest" / "docs"
    dst.mkdir(parents=True)
    (dst / "a.txt").write_text("trunc")

    state._merge_move(src, dst)

    assert not (dst / "docs").exists()
    assert (dst / "a.txt").read_text() == "original"
    assert (dst / "b.txt").read_text() == "b"
    assert not src.exists()


def test_fresh_org_gets_general_and_migration_is_once(tmp_path):
    client = _client(tmp_path)
    rows = client.get("/workspaces").json()   # first touch: marker + General
    general = next(r for r in rows if r["id"] == "t-shared")
    assert general["name"] == "General" and general["role"] == "editor"
    assert _run(_orgdb(tmp_path).get("migrated")) is not None
    # a legacy-looking file appearing later is NOT migrated again
    (tmp_path / "org_1" / "late.txt").write_text("x")
    state._migrated.clear()   # simulate a restart — marker row must gate it
    client.get("/workspaces")
    assert (tmp_path / "org_1" / "late.txt").exists()


def test_deleting_general_is_permanent(tmp_path):
    client = _client(tmp_path)
    client.get("/workspaces")
    r = client.delete("/workspaces/t-shared", headers={"X-Test-User": "admin_1"})
    assert r.status_code == 200
    state._migrated.clear()
    rows = client.get("/workspaces").json()   # marker gates re-provisioning
    assert not any(w["id"] == "t-shared" for w in rows)


def test_solo_user_gets_no_general(tmp_path):
    client = _client(tmp_path)
    client.get("/workspaces", headers={"X-Test-User": "solo"})
    assert _run(state.org_db("solo", tmp_path, f"file://{tmp_path}").get("workspaces/t-shared")) is None


def test_migration_solo_user_goes_to_personal(tmp_path):
    _seed_legacy(tmp_path, org="solo", user="solo")
    client = _client(tmp_path)
    h = {"X-Test-User": "solo"}
    assert [f["name"] for f in client.get("/files", headers=h).json()] == ["report.md"]
    assert (tmp_path / "solo" / "ws" / "u-solo" / "report.md").exists()
    # no phantom t-shared for org-less users
    assert _run(state.org_db("solo", tmp_path, f"file://{tmp_path}").get("workspaces/t-shared")) is None


def test_t_shared_is_per_org(tmp_path):
    """Every org's General shares the `t-shared` id, but the root derives from
    the requester's org — an outsider sees their own empty General, never
    another org's files."""
    _seed_legacy(tmp_path)
    client = _client(tmp_path)
    client.get("/workspaces")   # migrate org_1
    h = {"X-Workspace": "t-shared", "X-Test-User": "outsider"}
    r = client.get("/files", headers=h)
    assert r.status_code == 200 and r.json() == []
    assert client.get("/files/report.md", headers=h).status_code == 404


# ---------------------------------------------------------------------------
# Shares carry the minting workspace
# ---------------------------------------------------------------------------

def test_share_url_carries_ws_and_resolves(tmp_path):
    client = _client(tmp_path)
    ws_id = _mk_team(client)
    h = {"X-Workspace": ws_id}
    client.put("/chats/c1", json={"title": "Team chat"}, headers=h)
    body = client.post("/share", json={"path": "chat/c1"}, headers=h).json()
    assert body["url"].endswith(f"?ws={ws_id}")

    r = client.get(f"/share/org_1:user_1/{body['token']}/data?ws={ws_id}")
    assert r.status_code == 200 and r.json()["title"] == "Team chat"
    # without the ws hint the fallbacks (personal, t-shared) don't have the row
    assert client.get(f"/share/org_1:user_1/{body['token']}/data").status_code == 403


def test_share_bare_link_falls_back_to_personal(tmp_path):
    client = _client(tmp_path)
    client.put("/chats/c1", json={"title": "Mine"})          # personal workspace
    body = client.post("/share", json={"path": "chat/c1"}).json()
    r = client.get(f"/share/org_1:user_1/{body['token']}/data")   # no ?ws=
    assert r.status_code == 200 and r.json()["title"] == "Mine"


def test_fork_team_share_lands_in_forker_personal(tmp_path):
    client = _client(tmp_path)
    ws_id = _mk_team(client)
    h = {"X-Workspace": ws_id}
    client.put("/chats/c1", json={"title": "Team chat"}, headers=h)
    from cycls.app.db import workspace as _workspace
    team_ws = _workspace("org_1:user_1", tmp_path, base=f"file://{tmp_path}", ws=ws_id)
    _run(state.append_messages(team_ws, "c1", [{"role": "user", "content": "hi"}], 0))
    token = client.post("/share", json={"path": "chat/c1"}, headers=h).json()["token"]

    r = client.post(f"/share/org_1:user_1/{token}/fork?ws={ws_id}",
                    headers={"X-Test-User": "user_2"})
    assert r.status_code == 200
    forked = client.get("/chats", headers={"X-Test-User": "user_2"}).json()
    assert [c["title"] for c in forked] == ["Team chat"]


def test_list_chats_heals_wiped_meta(tmp_path, monkeypatch):
    """gcsfuse moves drop GCS custom metadata; the sidebar listing must fall
    back to the canonical body and rewrite the meta channel."""
    from cycls.app import db as db_mod
    from cycls.app.db import workspace

    ws = workspace("u1", tmp_path, base=f"file://{tmp_path}")
    _run(state.put_meta(ws, "c1", {"id": "c1", "title": "هلا", "updatedAt": "2026-07-06"}))

    async def wiped_scan(self, *, prefix=None, glob=None):
        yield "chat/c1/index", {}
    monkeypatch.setattr(db_mod.DB, "scan", wiped_scan)

    async def collect():
        return [(cid, meta) async for cid, meta in state.list_chats(ws)]
    rows = _run(collect())
    assert rows == [("c1", {"id": "c1", "title": "هلا", "updatedAt": "2026-07-06"})]


def test_v1_marker_org_gets_general_upgrade(tmp_path):
    _run(_orgdb(tmp_path).put("migrated", {"at": "2026-07-06", "moved": "False"}))
    client = _client(tmp_path)
    rows = client.get("/workspaces").json()
    assert any(w["id"] == "t-shared" and w["name"] == "General" for w in rows)
    marker = _run(_orgdb(tmp_path).get("migrated"))
    assert marker["v"] == "2" and marker["at"] == "2026-07-06"
