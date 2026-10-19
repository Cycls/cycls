"""Tests for cycls/_agent/tools/skills.py — frontmatter parsing, discovery,
precedence, the switches, the sandbox mounts, and the `skill` tool: load, draft, publish."""
import asyncio
import types

import pytest

from cycls._app.db import workspace
from cycls._agent import state
from cycls._agent.tools import skills
from cycls._agent.harness.prompts import workspace_instructions, fence_instructions


@pytest.fixture(autouse=True)
def _reset_skills_state():
    """Skills keep module-level caches (dev sources scanned once per process,
    user scans TTL'd per workspace) — isolate tests from each other."""
    skills._dev_sources = []
    skills._dev_cache.clear()
    skills._slot_cache.clear()
    yield
    skills._dev_sources = []
    skills._dev_cache.clear()
    skills._slot_cache.clear()


def _write_skill(root, dirname, name=None, description="Does a thing.", body="# Instructions", extra=""):
    d = root / dirname
    d.mkdir(parents=True)
    front = f"---\nname: {name or dirname}\ndescription: {description}\n{extra}---\n"
    (d / "SKILL.md").write_text(front + body)
    return d


def _ws(tmp_path, ws=None):
    return workspace("org:alice", tmp_path, base=f"file://{tmp_path}", ws=ws)


def _keep(ws_root, name, description="Does a thing.", body="# Instructions"):
    """A skill as publish keeps it: the next version, made the default."""
    files = {"SKILL.md": f"---\nname: {name}\ndescription: {description}\n---\n{body}".encode()}
    return skills.store(ws_root, name, files)


ALICE = types.SimpleNamespace(id="alice", org_id="org", org_role=None)


def _ctx(user=ALICE):
    return types.SimpleNamespace(user=user, chat_id="c", skills=None)


# ---- parse_frontmatter ----

def test_frontmatter_basic():
    meta, body = skills.parse_frontmatter("---\nname: pdf\ndescription: Makes PDFs.\n---\n# Body")
    assert meta == {"name": "pdf", "description": "Makes PDFs."}
    assert body == "# Body"


def test_frontmatter_quoted_values_and_unknown_keys():
    meta, _ = skills.parse_frontmatter('---\nname: "x"\nversion: \'1.0\'\n---\nbody')
    assert meta["name"] == "x"
    assert meta["version"] == "1.0"


def test_frontmatter_folded_value():
    """super-agent style `description: >-` with indented continuation lines."""
    text = "---\nname: pptx\ndescription: >-\n  Design PowerPoint decks.\n  Match brand style.\n---\nbody"
    meta, _ = skills.parse_frontmatter(text)
    assert meta["description"] == "Design PowerPoint decks. Match brand style."


def test_frontmatter_metadata_map_and_plain_text():
    """`metadata:` over `key: value` lines is a map; a bare key over prose is still text."""
    meta, _ = skills.parse_frontmatter("---\nname: pptx\ndescription: d\nmetadata:\n  title: Decks\n  title-ar: عروض\n---\nb")
    assert meta["metadata.title"] == "Decks" and meta["metadata.title-ar"] == "عروض"
    meta, _ = skills.parse_frontmatter("---\nname: x\ndescription:\n  Plain text: then more\n---\nb")
    assert meta["description"] == "Plain text: then more"


def test_skill_md_writes_what_people_see(tmp_path):
    """The form's Arabic name and description land under `metadata`, and the catalog reads them back."""
    md = skills.skill_md("pptx", "Create decks", "Body", title_ar="عروض", description_ar="إنشاء العروض")
    (tmp_path / "pptx").mkdir()
    (tmp_path / "pptx" / "SKILL.md").write_bytes(md)
    s = skills._load_skill(tmp_path / "pptx", "me")
    assert (s.name, s.description, s.title_ar, s.description_ar) == ("pptx", "Create decks", "عروض", "إنشاء العروض")
    assert b"metadata:" not in skills.skill_md("x", "d", "b")   # nothing to show, nothing written


def test_frontmatter_absent():
    meta, body = skills.parse_frontmatter("# Just markdown")
    assert meta == {} and body == "# Just markdown"


def test_frontmatter_unterminated_fence():
    text = "---\nname: x\nno closing fence"
    meta, body = skills.parse_frontmatter(text)
    assert meta == {} and body == text


# ---- discovery ----

def test_scan_nested_layout(tmp_path):
    _write_skill(tmp_path, "alpha")
    _write_skill(tmp_path, "beta")
    (tmp_path / ".hidden").mkdir()
    (tmp_path / "no-skill-md").mkdir()
    (tmp_path / "loose-file.md").write_text("not a skill")
    found = skills._scan_dir(tmp_path, "dev")
    assert [s.name for s in found] == ["alpha", "beta"]


def test_scan_single_skill_dir(tmp_path):
    d = _write_skill(tmp_path, "solo")
    found = skills._scan_dir(d, "dev")
    assert [s.name for s in found] == ["solo"]


def test_scan_missing_dir(tmp_path):
    assert skills._scan_dir(tmp_path / "nope", "user") == []


def test_load_skill_fallbacks(tmp_path):
    """No frontmatter → name from dir, description from first body line."""
    d = tmp_path / "my-skill"
    d.mkdir()
    (d / "SKILL.md").write_text("First line explains it.\n\nMore.")
    s = skills._load_skill(d, "user")
    assert s.name == "my-skill"
    assert s.description == "First line explains it."


def test_load_skill_invalid_name_skipped(tmp_path):
    d = tmp_path / "Bad_Name"
    d.mkdir()
    (d / "SKILL.md").write_text("body only")
    assert skills._load_skill(d, "user") is None


def test_load_skill_description_truncated(tmp_path):
    d = _write_skill(tmp_path, "wordy", description="x" * 2000)
    s = skills._load_skill(d, "dev")
    assert len(s.description) == skills.MAX_DESCRIPTION + 1
    assert s.description.endswith("…")


def test_the_person_wins_over_the_workspace_over_the_org_over_the_image(tmp_path):
    dev = tmp_path / "dev-skills"
    _write_skill(dev, "pdf", description="the image's")
    _write_skill(dev, "docx", description="the image's")
    skills.configure([dev])
    team, mine = _ws(tmp_path, "t-1"), _ws(tmp_path, "u-alice")
    _keep(tmp_path / "org", "docx", "the org's")
    _keep(tmp_path / "org", "style", "the org's")
    _keep(team.root, "pdf", "the team's")
    _keep(team.root, "brief", "the team's")
    _keep(mine.root, "brief", "alice's")
    catalog = skills.discover(team)
    assert {n: s.description for n, s in catalog.items()} == {
        "pdf": "the team's", "docx": "the org's", "style": "the org's", "brief": "alice's"}
    assert [catalog[n].source for n in ("docx", "pdf", "brief")] == ["org", "workspace", "me"]
    assert {n: s.source for n, s in skills.discover(mine).items()} == {"pdf": "dev", "docx": "org", "style": "org", "brief": "me"}
    assert set(skills.discover(team, hidden={"pdf"})) == {"docx", "style", "brief"}


def test_the_shipped_skills_are_known_from_boot_not_from_the_first_turn(tmp_path):
    import pickle
    import cycls
    _write_skill(tmp_path / "dev-skills", "pdf")
    pickle.loads(pickle.dumps(cycls.LLM().skills(str(tmp_path / "dev-skills"))))   # what the container does at boot
    assert set(skills.discover(_ws(tmp_path))) == {"pdf"}


def test_without_workspaces_an_org_has_one_place_and_a_solo_account_its_own(tmp_path):
    legacy = workspace("org:alice", tmp_path, base=f"file://{tmp_path}")
    assert skills.roots(legacy) == {"org": tmp_path / "org"}
    assert skills.roots(workspace("solo", tmp_path, base=f"file://{tmp_path}")) == {"me": tmp_path / "solo"}


def test_only_the_default_version_loads_and_a_folder_without_one_does_not(tmp_path):
    ws = _ws(tmp_path, "u-alice")
    _keep(ws.root, "brief", "first")
    assert _keep(ws.root, "brief", "second") == 2
    (ws.root / ".skills" / "loose").mkdir(parents=True)
    (ws.root / ".skills" / "loose" / "SKILL.md").write_text("---\nname: loose\ndescription: x\n---\n")
    found = skills.discover(ws)
    assert set(found) == {"brief"} and found["brief"].description == "second"
    assert found["brief"].dir == ws.root / ".skills" / "brief" / "v2"


def test_a_slot_scan_is_ttl_cached_and_a_publish_refreshes_it(tmp_path, monkeypatch):
    ws = _ws(tmp_path, "u-alice")
    _keep(ws.root, "one")
    now = [1000.0]
    monkeypatch.setattr(skills.time, "monotonic", lambda: now[0])
    assert set(skills.discover(ws)) == {"one"}
    (ws.root / ".skills" / "two" / "v1").mkdir(parents=True)
    (ws.root / ".skills" / "two" / "v1" / "SKILL.md").write_text("---\nname: two\ndescription: x\n---\n")
    (ws.root / ".skills" / "two" / "meta.json").write_text('{"default": 1}')
    assert set(skills.discover(ws)) == {"one"}          # within TTL — cached
    now[0] += skills._TTL + 1
    assert set(skills.discover(ws)) == {"one", "two"}   # TTL expired — rescanned
    _keep(ws.root, "three")
    assert set(skills.discover(ws)) == {"one", "two", "three"}


def test_an_org_block_and_a_persons_switch_keep_a_skill_out(tmp_path):
    ws = _ws(tmp_path, "t-1")
    for n in ("a", "b", "c"):
        _keep(ws.root, n)
    asyncio.run(state.org_db("org", tmp_path, f"file://{tmp_path}").put("skills", {"blocked": ["a"]}))
    asyncio.run(state.settings_db(ws).put("skills", {"off": ["b"]}))
    assert set(asyncio.run(skills.available(ws))) == {"c"}


# ---- sandbox mounts + read-tool resolution ----

def test_every_skill_mounts_at_its_name(tmp_path):
    dev = tmp_path / "dev-skills"
    a = _write_skill(dev, "alpha")
    skills.configure([dev])
    assert skills.mounts() == [(str(a), "/skills/alpha")]
    ws = _ws(tmp_path, "u-alice")
    _keep(ws.root, "brief")
    assert (str(ws.root / ".skills" / "brief" / "v1"), "/skills/brief") in skills.mounts(skills.discover(ws))


def test_resolve_path(tmp_path):
    dev = tmp_path / "dev-skills"
    d = _write_skill(dev, "alpha")
    (d / "scripts").mkdir()
    (d / "scripts" / "run.py").write_text("print('hi')")
    skills.configure([dev])
    assert skills.resolve_path("scripts/run.py") is None       # not /skills → workspace rules
    assert skills.resolve_path("/skills/alpha/scripts/run.py").read_text() == "print('hi')"
    with pytest.raises(ValueError, match="unknown skill"):
        skills.resolve_path("/skills/nope/x.md")
    with pytest.raises(ValueError, match="escapes"):
        skills.resolve_path("/skills/alpha/../../etc/passwd")


# ---- catalog text ----

def test_catalog_text_lists_skills(tmp_path):
    ws = _ws(tmp_path)
    _keep(ws.root, "pdf", description="Makes PDFs.")
    text = skills.catalog_text(skills.discover(ws))
    assert text.startswith("<skills>") and text.endswith("</skills>")
    assert "- pdf: Makes PDFs." in text
    assert "`skill` tool" in text


def test_catalog_text_empty():
    assert skills.catalog_text({}) == ""


# ---- the skill tool: load ----

def _run(inp, ws, ctx=None):
    return asyncio.run(skills._exec_skill(inp, ws, ctx))


def test_load_reads_the_body_and_names_the_mount(tmp_path):
    ws = _ws(tmp_path)
    _keep(ws.root, "haiku", body="# Write haikus\nAlways 5-7-5.")
    out = _run({"name": "haiku"}, ws)
    assert out.startswith("[skill: haiku — files in /skills/haiku/]")
    assert "Always 5-7-5." in out


def test_load_unknown_name_lists_available(tmp_path):
    ws = _ws(tmp_path)
    _keep(ws.root, "alpha")
    out = _run({"name": "nope"}, ws)
    assert "Error: unknown skill 'nope'" in out and "alpha" in out


def test_load_support_files(tmp_path):
    dev = tmp_path / "dev-skills"
    d = _write_skill(dev, "alpha", body="x" * (skills.MAX_SKILL_BYTES + 100))
    (d / "REFERENCE.md").write_text("deep details")
    (d / "template.pptx").write_bytes(b"PK\x00\x01" * 10)
    (tmp_path / "secret.txt").write_text("secret")
    skills.configure([dev])
    ws = _ws(tmp_path)
    assert "deep details" in _run({"name": "alpha", "path": "REFERENCE.md"}, ws)
    assert "escapes" in _run({"name": "alpha", "path": "../../secret.txt"}, ws)
    assert "binary" in _run({"name": "alpha", "path": "template.pptx"}, ws)
    out = _run({"name": "alpha"}, ws)
    assert "... (truncated)" in out and len(out) < skills.MAX_SKILL_BYTES + 500


# ---- the skill tool: publish ----

def _draft_folder(root, name="brief", description="Writes briefs.", extra=0):
    d = root / "skill-drafts" / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_bytes(f"---\r\nname: {name}\r\ndescription: {description}\r\n---\r\nBe brief.".encode())
    (d / ".DS_Store").write_bytes(b"junk")
    for i in range(extra):
        (d / f"note-{i}.md").write_text("x")
    return d


def test_publish_keeps_a_version_that_loads(tmp_path):
    ws = _ws(tmp_path, "u-alice")
    _draft_folder(ws.root)
    assert _run({"action": "publish", "name": "brief"}, ws, _ctx()).startswith("Published brief v1 for you")
    kept = ws.root / ".skills" / "brief" / "v1"
    assert sorted(p.name for p in kept.iterdir()) == ["SKILL.md"]               # junk dropped
    assert b"\r" not in (kept / "SKILL.md").read_bytes()                         # LF, so the loader reads it
    assert skills.discover(ws)["brief"].description == "Writes briefs."
    assert _run({"action": "publish", "name": "brief"}, ws, _ctx()).startswith("Published brief v2")


def test_publish_refuses_what_the_loader_would_not_read_links_and_too_much(tmp_path):
    ws = _ws(tmp_path, "u-alice")
    _draft_folder(ws.root, name="brief", description="")
    assert "description" in _run({"action": "publish", "name": "brief"}, ws, _ctx())
    _draft_folder(ws.root, name="other")
    assert "name: brief" in _run({"action": "publish", "name": "brief", "path": "skill-drafts/other"}, ws, _ctx())
    long = "a" * 65
    _draft_folder(ws.root, name=long)
    assert "at most 64" in _run({"action": "publish", "name": long}, ws, _ctx())
    d = _draft_folder(ws.root, name="leak")
    (d / "x").symlink_to(tmp_path / "org" / ".secrets")
    assert "is a link" in _run({"action": "publish", "name": "leak"}, ws, _ctx())
    _draft_folder(ws.root, name="many", extra=skills.MAX_FILES)
    assert "at most 500 files" in _run({"action": "publish", "name": "many"}, ws, _ctx())
    assert "managed" in _run({"action": "publish", "name": "brief", "path": ".skills/brief"}, ws, _ctx())


def test_only_a_teams_owners_and_admins_publish_for_it(tmp_path):
    team = _ws(tmp_path, "t-1")
    _draft_folder(team.root)
    inp = {"action": "publish", "name": "brief", "scope": "workspace"}
    assert "owners and admins" in _run(inp, team, _ctx())
    asyncio.run(state.org_db("org", tmp_path, f"file://{tmp_path}").put("members/t-1/alice", {"role": "admin"}))
    assert "for everyone in this workspace" in _run(inp, team, _ctx())
    assert skills.discover(team)["brief"].source == "workspace"


def test_only_org_admins_publish_for_the_org_and_it_reaches_every_workspace(tmp_path):
    team = _ws(tmp_path, "t-1")
    _draft_folder(team.root)
    inp = {"action": "publish", "name": "brief", "scope": "org"}
    assert "by its admins" in _run(inp, team, _ctx())
    admin = types.SimpleNamespace(id="alice", org_id="org", org_role="admin")
    assert "for everyone in the organization" in _run(inp, team, _ctx(admin))
    assert skills.discover(_ws(tmp_path, "t-2"))["brief"].source == "org"
    assert skills.discover(_ws(tmp_path, "u-bob"))["brief"].source == "org"
    legacy = workspace("org:alice", tmp_path, base=f"file://{tmp_path}")   # without workspaces: the org's, by default
    assert "by its admins" in _run({"action": "publish", "name": "brief", "path": "ws/t-1/skill-drafts/brief"}, legacy, _ctx())


def test_a_member_keeps_their_own_and_it_follows_them(tmp_path):
    team = _ws(tmp_path, "t-1")
    _draft_folder(team.root)
    _run({"action": "publish", "name": "brief", "scope": "me"}, team, _ctx())
    assert (tmp_path / "org" / "ws" / "u-alice" / ".skills" / "brief" / "v1" / "SKILL.md").exists()
    assert skills.discover(_ws(tmp_path, "t-2"))["brief"].source == "me"
    assert "use org or me" in _run({"action": "publish", "name": "brief", "scope": "workspace"},
                                   _ws(tmp_path, "u-alice"), _ctx())


# ---- the Skills tab's routes ----

def _zip(files):
    import io, zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for path, text in files.items():
            z.writestr(path, text)
    return buf.getvalue()


BRIEF = _zip({"brief/SKILL.md": "---\nname: brief\ndescription: Writes briefs.\n---\nBe brief.", "brief/.DS_Store": "x"})


def _client(tmp_path, user, ws_id="t-1"):
    from fastapi import Depends, FastAPI
    from fastapi.testclient import TestClient
    from cycls._agent.web.routers import skills_router
    ws = workspace(user, tmp_path, base=f"file://{tmp_path}", ws=ws_id)
    app = FastAPI()
    app.include_router(skills_router(Depends(lambda: ws), Depends(lambda: user)))
    return TestClient(app), ws


def test_a_member_adds_switches_downloads_and_removes_their_own(tmp_path):
    import io, zipfile
    from cycls._app.auth import User
    client, ws = _client(tmp_path, User(id="m", org_id="org", org_role="member"))
    assert client.post("/skills?scope=workspace", content=BRIEF).status_code == 403
    assert client.post("/skills?scope=me", content=BRIEF).json() == {"name": "brief", "version": 1}
    listed = client.get("/skills").json()
    assert listed["scopes"] == ["me"] and [{k: s[k] for k in ("name", "source", "version", "on", "allowed", "manage", "yours")}
                                           for s in listed["skills"]] == [
        {"name": "brief", "source": "me", "version": 1, "on": True, "allowed": True, "manage": True, "yours": True}]
    client.patch("/skills/brief", json={"on": False})
    assert client.get("/skills").json()["skills"][0]["on"] is False and asyncio.run(skills.available(ws)) == {}
    assert zipfile.ZipFile(io.BytesIO(client.get("/skills/brief/download").content)).namelist() == ["brief/SKILL.md"]
    assert client.patch("/skills/brief", json={"allowed": False}).status_code == 403
    client.delete("/skills/brief")
    assert client.get("/skills").json()["skills"] == []
    assert client.post("/skills?scope=me", content=BRIEF).json()["version"] == 2    # its versions stayed


def test_an_org_admin_adds_for_everyone_and_switches_one_off_for_everyone(tmp_path):
    from cycls._app.auth import User
    admin, _ = _client(tmp_path, User(id="a", org_id="org", org_role="admin"))
    member, _ = _client(tmp_path, User(id="m", org_id="org", org_role="member"), "t-2")
    asyncio.run(state.org_db("org", tmp_path, f"file://{tmp_path}").put("workspaces/t-1", {"id": "t-1", "type": "team"}))
    assert admin.get("/skills").json()["scopes"] == ["org", "workspace", "me"]
    admin.post("/skills?scope=org", content=BRIEF)
    assert member.get("/skills").json()["skills"][0]["source"] == "org"
    admin.patch("/skills/brief", json={"allowed": False})
    assert member.get("/skills").json()["skills"] == []
    assert admin.get("/skills").json()["skills"][0]["allowed"] is False


def test_a_skill_written_in_the_form_has_a_page_files_versions_and_a_place_it_moves_to(tmp_path):
    from cycls._app.auth import User
    asyncio.run(state.org_db("org", tmp_path, f"file://{tmp_path}").put("members/t-1/a", {"role": "admin"}))
    client, ws = _client(tmp_path, User(id="a", org_id="org", org_role="member", name="Amal"))
    form = {"description": "Weekly\nupdates.", "body": "Wins, blockers, next steps."}
    assert client.put("/skills/Weekly status report", json=form).json() == {"name": "weekly-status-report", "version": 1}
    client.put("/skills/weekly-status-report", json={**form, "body": "Three bullets."})
    page = client.get("/skills/weekly-status-report").json()
    assert (page["source"], page["version"], page["who"], page["files"]) == ("me", 2, "Amal", ["SKILL.md"])
    assert [x["v"] for x in page["versions"]] == [2, 1]
    assert "Three bullets." in client.get("/skills/weekly-status-report/file?path=SKILL.md").text
    assert "Wins, blockers" in client.get("/skills/weekly-status-report/file?path=SKILL.md&v=1").text
    assert client.get("/skills/weekly-status-report/file?path=../../x").status_code == 404
    client.post("/skills/weekly-status-report/current", json={"v": 1})
    assert client.get("/skills/weekly-status-report").json()["version"] == 1
    assert client.post("/skills/weekly-status-report/move", json={"to": "org"}).status_code == 403
    client.post("/skills/weekly-status-report/move", json={"to": "workspace"})
    assert skills.discover(ws)["weekly-status-report"].source == "workspace"
    assert "Wins, blockers" in client.get("/skills/weekly-status-report/file?path=SKILL.md").text


def test_an_upload_the_loader_would_not_read_is_refused(tmp_path):
    from cycls._app.auth import User
    client, _ = _client(tmp_path, User(id="m", org_id="org", org_role="member"))
    assert client.post("/skills", content=b"not a zip").status_code == 400
    assert client.post("/skills", content=_zip({"SKILL.md": "no frontmatter"})).status_code == 400
    assert "leaves the skill" in client.post("/skills", content=_zip({"SKILL.md": "x", "../x": "y"})).json()["detail"]


# ---- workspace instructions (AGENT.md) ----

def test_workspace_instructions_reads_file(tmp_path):
    (tmp_path / "AGENT.md").write_text("Answer in pirate speak.")
    assert workspace_instructions(tmp_path, "AGENT.md") == "Answer in pirate speak."


def test_workspace_instructions_missing_or_dir(tmp_path):
    assert workspace_instructions(tmp_path, "AGENT.md") == ""
    (tmp_path / "AGENT.md").mkdir()
    assert workspace_instructions(tmp_path, "AGENT.md") == ""


def test_workspace_instructions_binary_ignored(tmp_path):
    (tmp_path / "AGENT.md").write_bytes(b"\x00\x01\x02binary")
    assert workspace_instructions(tmp_path, "AGENT.md") == ""


def test_workspace_instructions_truncates(tmp_path):
    (tmp_path / "AGENT.md").write_text("y" * 50_000)
    out = workspace_instructions(tmp_path, "AGENT.md")
    assert out.endswith("... (truncated)")
    assert len(out) < 50_000


def test_fence_instructions_wraps_and_subordinates():
    fenced = fence_instructions("Be brief.")
    assert fenced.startswith("<workspace_instructions>")
    assert fenced.endswith("</workspace_instructions>")
    assert "Be brief." in fenced
    assert "never override system or developer policy" in fenced
