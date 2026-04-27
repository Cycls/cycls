# uv run cycls run examples/app/habits.py
# uv run cycls deploy examples/app/habits.py
"""Habit tracker — the full @cycls.app surface in ~80 lines.

Demonstrates every capability the app layer exposes:
  - auth=cycls.Clerk(...)            JWT validation, every route protected
  - app.workspace                    per-user Workspace via FastAPI Depends
  - cycls.DB(ws).kv(name)            namespaced JSON storage
  - kv.items(prefix=...)             ordered prefix scan
  - kv.transaction()                 atomic multi-key writes
  - cycls.DB(ws).raw()               raw SlateDB for TTL-cached stats
  - cycls.Image()                    container build config

Routes:
  GET    /me                         the authenticated user (uses app.auth)
  POST   /habits                     create a habit
  GET    /habits                     list this user's habits
  GET    /habits/{id}                habit + recent check-ins
  POST   /habits/{id}/check          check in for today
  DELETE /habits/{id}                atomic delete (habit + all check-ins)
  GET    /stats                      cross-habit stats (TTL-cached for 5 min)
"""
import json
from datetime import date, datetime, timezone
from pathlib import Path
from uuid import uuid4

import cycls

HTML = (Path(__file__).parent / "habits.html").read_text()


@cycls.app(image=cycls.Image(), auth=cycls.Clerk("cycls.ai"))
def habits():
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import HTMLResponse
    from pydantic import BaseModel
    from slatedb.uniffi import PutOptions, Ttl, WriteOptions

    app = FastAPI(title="Habits")

    @app.get("/")
    async def index():
        pk = habits._auth_provider.resolve(habits.prod).get("pk", "")
        return HTMLResponse(HTML.replace("__CLERK_PK__", pk))

    class HabitIn(BaseModel):
        title: str
        target_per_week: int = 7

    @app.get("/me")
    async def me(user=habits.auth):
        return user

    @app.post("/habits")
    async def create(body: HabitIn, ws=habits.workspace):
        habit_id = uuid4().hex[:12]
        habit = {
            "id": habit_id,
            "title": body.title,
            "target_per_week": body.target_per_week,
            "createdAt": datetime.now(timezone.utc).isoformat(),
        }
        await cycls.DB(ws).kv("habits").put(habit_id, habit)
        return habit

    @app.get("/habits")
    async def list_habits(ws=habits.workspace):
        return [h async for _, h in cycls.DB(ws).kv("habits").items()]

    @app.get("/habits/{habit_id}")
    async def get_habit(habit_id: str, ws=habits.workspace):
        db = cycls.DB(ws)
        habit = await db.kv("habits").get(habit_id)
        if habit is None:
            raise HTTPException(404, "Not found")
        checkins = [k.split("/", 1)[1] async for k, _ in db.kv("checkins").items(prefix=f"{habit_id}/")]
        return {**habit, "checkins": checkins}

    @app.post("/habits/{habit_id}/check")
    async def check(habit_id: str, ws=habits.workspace):
        db = cycls.DB(ws)
        if await db.kv("habits").get(habit_id) is None:
            raise HTTPException(404, "Not found")
        today = date.today().isoformat()
        await db.kv("checkins").put(
            f"{habit_id}/{today}",
            {"at": datetime.now(timezone.utc).isoformat()},
        )
        return {"date": today}

    @app.delete("/habits/{habit_id}")
    async def delete_habit(habit_id: str, ws=habits.workspace):
        db = cycls.DB(ws)
        async with db.kv("habits").transaction() as t:
            if await t.get(habit_id) is None:
                raise HTTPException(404, "Not found")
            await t.delete(habit_id)
        async with db.kv("checkins").transaction() as t:
            async for k, _ in t.items(prefix=f"{habit_id}/"):
                await t.delete(k)
        return {"ok": True}

    @app.get("/stats")
    async def stats(ws=habits.workspace):
        # TTL-cached aggregate via raw SlateDB. The cache key sits outside any
        # KV namespace and expires automatically — no manual invalidation.
        db = cycls.DB(ws)
        async with db.raw() as raw:
            cached = await raw.get(b"stats:cache")
            if cached:
                return json.loads(cached)
            n_habits = 0
            async for _ in db.kv("habits").items(): n_habits += 1
            n_checkins = 0
            async for _ in db.kv("checkins").items(): n_checkins += 1
            result = {
                "habits": n_habits,
                "checkins": n_checkins,
                "computed_at": datetime.now(timezone.utc).isoformat(),
            }
            await raw.put_with_options(
                b"stats:cache",
                json.dumps(result).encode(),
                PutOptions(ttl=Ttl.EXPIRE_AFTER_TICKS(5 * 60 * 1000)),  # 5 min
                WriteOptions(await_durable=False),
            )
            return result

    return app


if __name__ == "__main__":
    habits.local()
