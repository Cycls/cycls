"""Multi-workspace Phase 2 — registry, ACL, team workspaces, admin lifecycle.

Spec: docs/rfc-workspaces.md. The stub app mounts the real routers with a
header-switched fake auth (`X-Test-User`) so one client can act as several
org members: a regular member, a second member, an org admin, and an
outsider from another org.
"""
import asyncio

import pytest

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
    # user_2 is not a member — sees only their personal
    rows2 = client.get("/workspaces", headers={"X-Test-User": "user_2"}).json()
    assert [r["id"] for r in rows2] == ["u-user_2"]


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
