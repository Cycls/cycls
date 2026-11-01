"""A Word document's comments in Cycls's record (design/comments.py kind "doc", office/docs_comments.py): the
editor's own changes sent as they are made, and the record brought in line with the file (Word's copy)."""
import copy
import json

import pytest

from cycls._agent.design import comments
from cycls._agent.office import docs_comments

from tests.agent.design_comments_test import _client

EARLY, WRITTEN, LATE = "2026-10-27T09:00:00+00:00", "2026-10-27T10:00:00+00:00", "2026-10-27T11:00:00+00:00"
AGENT = {"id": "agent", "name": "Super", "agent": True}


@pytest.fixture(autouse=True)
def _no_refresh(monkeypatch):
    monkeypatch.setattr("cycls._agent.design.refresh.schedule", lambda *a, **k: None)


def test_a_word_document_has_comments_on_its_words():
    assert comments.commentable("reports/q3.docx") and comments.kind_of("reports/q3.docx") == "doc"
    assert comments.kind_of("b.xlsx") == "sheet" and comments.kind_of("d.fig") == "design"


def test_the_editor_adds_a_comment_by_its_word_id_and_replies_under_theirs(tmp_path):
    client = _client(tmp_path)
    assert client.put("/files/reports/q3.docx", content=b"PK docx").status_code == 200
    url = "/comments/reports/q3.docx"
    r = client.post(url, json={"text": "Is this final?", "para": "7B4164C0", "quote": "15%", "word": "3", "name": "Sara"})
    assert r.status_code == 200, r.text
    t = r.json()["thread"]
    assert (t["para"], t["quote"], t["word"]) == ("7B4164C0", "15%", "3")
    assert t["author"]["id"] == "user_1"
    r = client.post(f"{url}?id={t['id']}", json={"op": "reply", "text": "Yes", "word": "4", "name": "Sara"})
    assert r.status_code == 200, r.text
    assert r.json()["thread"]["replies"][0]["word"] == "4"
    # A comment on words stays on them.
    assert client.post(f"{url}?id={t['id']}", json={"op": "move", "para": "x"}).status_code == 400


def _record(*threads):
    return {"seq": len(threads), "threads": list(threads)}


def _mine(word, at=EARLY, **more):
    return {"id": f"t{word}", "n": int(word), "word": word, "author": {"id": "user_1", "name": "Sara", "image": "https://img/s.png"},
            "text": "Mine", "at": at, "updated": at, "resolved": False, "replies": [], **more}


def _file(word, text="Mine", author="Sara", resolved=False, replies=(), **more):
    return {"word": word, "author": author, "at": "2026-10-20T08:00:00Z", "text": text, "resolved": resolved,
            "replies": [dict(r) for r in replies], **more}


def test_a_comment_made_in_word_comes_into_the_record_under_its_authors_name():
    doc = _record()
    assert comments.mirror_threads(doc, [_file("0", "From Word", author="Omar", para="P1", quote="margins")], WRITTEN)
    [t] = doc["threads"]
    assert t["word"] == "0" and t["text"] == "From Word" and (t["para"], t["quote"]) == ("P1", "margins")
    assert t["author"] == {"id": "word:Omar", "name": "Omar"}
    assert t["at"] == "2026-10-20T08:00:00+00:00"
    assert not comments.mirror_threads(doc, [_file("0", "From Word", author="Omar", para="P1", quote="margins")], WRITTEN)


def test_who_wrote_it_in_cycls_is_kept_and_the_file_says_what_it_says_now():
    doc = _record(_mine("3"))
    assert comments.mirror_threads(doc, [_file("3", "Mine, edited in Word", resolved=True,
                                                replies=[{"word": "4", "author": "Omar", "at": None, "text": "Done"}])], WRITTEN)
    [t] = doc["threads"]
    assert t["author"]["image"] == "https://img/s.png"
    assert t["text"] == "Mine, edited in Word" and t["resolved"] is True
    assert [(r["word"], r["author"]["name"], r["text"]) for r in t["replies"]] == [("4", "Omar", "Done")]


def test_a_comment_gone_from_the_file_goes_unless_it_is_on_its_way_in():
    doc = _record(_mine("3"), _mine("5", at=LATE), {**_mine("6"), "replies": [
        {"id": "r1", "word": "7", "author": {"id": "user_1", "name": "Sara"}, "text": "old", "at": EARLY},
        {"id": "r2", "word": "8", "author": {"id": "user_1", "name": "Sara"}, "text": "new", "at": LATE}]})
    assert comments.mirror_threads(doc, [_file("6")], WRITTEN)
    # 3 was written before the file and is not in it: removed (in Word, or by the agent). 5 is newer than the file:
    # the editor saves it in a moment. Reply 7 likewise gone, 8 kept.
    assert [t["word"] for t in doc["threads"]] == ["5", "6"]
    assert [r["word"] for r in doc["threads"][1]["replies"]] == ["8"]


def test_the_agents_comments_carry_its_badge():
    doc = _record()
    comments.mirror_threads(doc, [_file("0", "Check the total", author="Super",
                                        replies=[{"word": "1", "author": "Sara", "at": None, "text": "ok"}])], WRITTEN, AGENT)
    [t] = doc["threads"]
    assert t["author"] == AGENT
    assert t["replies"][0]["author"] == {"id": "word:Sara", "name": "Sara"}


def test_the_files_comments_are_read_from_the_readers_resource():
    document = {
        "body": {"dataStream": "Revenue grew 15%\rNext\r\n", "paragraphs": [{"startIndex": 16, "paragraphId": "P1"},
                                                                          {"startIndex": 21, "paragraphId": "P2"}]},
        "resources": [{"name": docs_comments.RESOURCE, "data": json.dumps({docs_comments.SUBUNIT: [{
            "id": "2", "threadId": "2", "dT": "2026-10-20T08:00:00Z", "personId": "word:Omar", "authorName": "Omar",
            "text": {"dataStream": "Is this\rfinal?\r\n"}, "resolved": True, "startOffset": 13, "endOffset": 16, "ref": "15%",
            "children": [{"id": "3", "authorName": "Sara", "dT": "", "text": {"dataStream": "Yes\r\n"}}],
        }]})}],
    }
    assert docs_comments.file_threads(document) == [{
        "word": "2", "author": "Omar", "at": "2026-10-20T08:00:00Z", "text": "Is this\nfinal?", "resolved": True,
        "para": "P1", "quote": "15%", "replies": [{"word": "3", "author": "Sara", "at": "", "text": "Yes"}],
    }]
    assert docs_comments.file_threads({"body": {}, "resources": []}) == []


def test_the_record_is_written_only_when_the_file_differs(tmp_path):
    import asyncio
    client = _client(tmp_path)
    assert client.put("/files/q3.docx", content=b"PK docx").status_code == 200
    from types import SimpleNamespace
    ws = SimpleNamespace(subject="user_1", volume=tmp_path, base=f"file://{tmp_path}", ws=None, root=str(tmp_path / "user_1"))
    calls = []
    real = comments._update

    async def counting(*a, **k):
        calls.append(1)
        return await real(*a, **k)
    import cycls._agent.design.comments as mod
    mod._update = counting
    try:
        threads = [_file("0", "From Word", author="Omar")]
        asyncio.run(comments.mirror(ws, "q3.docx", threads, WRITTEN))
        asyncio.run(comments.mirror(ws, "q3.docx", copy.deepcopy(threads), WRITTEN))
    finally:
        mod._update = real
    assert len(calls) == 1
    doc, _ = asyncio.run(comments.read(ws, "q3.docx"))
    assert [t["text"] for t in doc["threads"]] == ["From Word"]
