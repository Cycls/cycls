# uv run cycls run examples/app/habits.py
# uv run cycls deploy examples/app/habits.py
"""Habit tracker — full @cycls._app surface in ~80 lines.

Demonstrates:
  - auth=cycls.Clerk(...)            JWT validation, every route protected
  - app.workspace                    per-user Workspace via FastAPI Depends
  - cycls.DB(ws).put/get/delete      flat JSON KV (key is the full path)
  - .items(prefix=...)               ordered prefix scan
  - db.delete("prefix/")             trailing-slash subtree delete

Routes:
  GET    /me                         the authenticated user (uses app.auth)
  POST   /habits                     create a habit
  GET    /habits                     list this user's habits
  GET    /habits/{id}                habit + recent check-ins
  POST   /habits/{id}/check          check in for today
  DELETE /habits/{id}                delete habit + all check-ins
  GET    /stats                      cross-habit counts
"""
import asyncio
from datetime import date, datetime, timezone
from pathlib import Path
from uuid import uuid4

import cycls

HTML_PATH = str(Path(__file__).parent / "habits.html")


@cycls.app(image=cycls.Image().copy(HTML_PATH, "habits.html"), auth=cycls.Clerk())
def habits():
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import HTMLResponse
    from pydantic import BaseModel

    app = FastAPI(title="Habits")

    @app.get("/")
    async def index():
        pk = habits._auth_provider.resolve(habits.prod).get("pk", "")
        html = Path("habits.html").read_text().replace("__CLERK_PK__", pk)
        return HTMLResponse(html)

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
        await cycls.DB(ws).put(f"habits/{habit_id}", habit)
        return habit

    @app.get("/habits")
    async def list_habits(ws=habits.workspace):
        return [h async for _, h in cycls.DB(ws).items(prefix="habits/")]

    @app.get("/habits/{habit_id}")
    async def get_habit(habit_id: str, ws=habits.workspace):
        db = cycls.DB(ws)
        habit = await db.get(f"habits/{habit_id}")
        if habit is None:
            raise HTTPException(404, "Not found")
        prefix = f"checkins/{habit_id}/"
        checkins = [k.removeprefix(prefix) async for k, _ in db.items(prefix=prefix)]
        return {**habit, "checkins": checkins}

    @app.post("/habits/{habit_id}/check")
    async def check(habit_id: str, ws=habits.workspace):
        db = cycls.DB(ws)
        if await db.get(f"habits/{habit_id}") is None:
            raise HTTPException(404, "Not found")
        today = date.today().isoformat()
        await db.put(
            f"checkins/{habit_id}/{today}",
            {"at": datetime.now(timezone.utc).isoformat()},
        )
        return {"date": today}

    @app.delete("/habits/{habit_id}")
    async def delete_habit(habit_id: str, ws=habits.workspace):
        db = cycls.DB(ws)
        if await db.get(f"habits/{habit_id}") is None:
            raise HTTPException(404, "Not found")
        await asyncio.gather(
            db.delete(f"habits/{habit_id}"),
            db.delete(f"checkins/{habit_id}/"),
        )
        return {"ok": True}

    @app.get("/stats")
    async def stats(ws=habits.workspace):
        db = cycls.DB(ws)
        n_habits = sum(1 async for _ in db.items(prefix="habits/"))
        n_checkins = sum(1 async for _ in db.items(prefix="checkins/"))
        return {
            "habits": n_habits,
            "checkins": n_checkins,
            "computed_at": datetime.now(timezone.utc).isoformat(),
        }

    return app
