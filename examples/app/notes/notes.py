# uv run cycls run examples/app/notes/notes.py
"""Notes — per-user search via inverted index over a flat DB.

  docs/{doc_id}        → {id, title, body, createdAt}
  idx/{term}/{doc_id}  → 1   (inverted index)

Write path: doc + index entries written atomically in one transaction.
Search: tokenize query, prefix-scan "idx/{term}/" per term, intersect.
"""
import re
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import cycls

HTML_PATH = str(Path(__file__).parent / "notes.html")
TOKEN_RE = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> set[str]:
    return set(TOKEN_RE.findall(text.lower()))


@cycls.app(image=cycls.Image().copy(HTML_PATH, "notes.html"), auth=cycls.Clerk("cycls.ai"))
def notes():
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import HTMLResponse
    from pydantic import BaseModel

    app = FastAPI(title="Notes")

    class NoteIn(BaseModel):
        title: str = ""
        body: str

    @app.get("/")
    async def index():
        pk = notes._auth_provider.resolve(notes.prod).get("pk", "")
        html = Path("notes.html").read_text().replace("__CLERK_PK__", pk)
        return HTMLResponse(html)

    @app.get("/me")
    async def me(user=notes.auth):
        return user

    @app.post("/notes")
    async def create(body: NoteIn, ws=notes.workspace):
        nid = uuid4().hex[:12]
        doc = {
            "id": nid,
            "title": body.title,
            "body": body.body,
            "createdAt": datetime.now(timezone.utc).isoformat(),
        }
        async with cycls.DB(ws).transaction() as t:
            await t.put(f"docs/{nid}", doc)
            for term in tokenize(doc["title"] + " " + doc["body"]):
                await t.put(f"idx/{term}/{nid}", 1)
        return doc

    @app.get("/notes")
    async def list_notes(ws=notes.workspace):
        items = [d async for _, d in cycls.DB(ws).items(prefix="docs/")]
        items.sort(key=lambda d: d.get("createdAt", ""), reverse=True)
        return items

    @app.get("/search")
    async def search(q: str, ws=notes.workspace):
        terms = tokenize(q)
        if not terms:
            return []
        db = cycls.DB(ws)
        ids: set[str] | None = None
        for term in terms:
            prefix = f"idx/{term}/"
            hits = {k.removeprefix(prefix) async for k, _ in db.items(prefix=prefix)}
            ids = hits if ids is None else ids & hits
            if not ids:
                return []
        docs = []
        for nid in ids or set():
            d = await db.get(f"docs/{nid}")
            if d:
                docs.append(d)
        docs.sort(key=lambda d: d.get("createdAt", ""), reverse=True)
        return docs

    @app.delete("/notes/{nid}")
    async def delete_note(nid: str, ws=notes.workspace):
        db = cycls.DB(ws)
        doc = await db.get(f"docs/{nid}")
        if not doc:
            raise HTTPException(404, "not found")
        async with db.transaction() as t:
            await t.delete(f"docs/{nid}")
            for term in tokenize(doc["title"] + " " + doc["body"]):
                await t.delete(f"idx/{term}/{nid}")
        return {"ok": True}

    return app
