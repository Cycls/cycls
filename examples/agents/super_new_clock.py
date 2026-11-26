# The clock beside super-new: every five minutes it calls the agent's /routines/tick, which starts each routine whose
# time has come (docs/rfc-routines.md). The platform schedules functions, not agents, so this is the function beside it.
#     uv run cycls deploy examples/agents/super_new_clock.py
import cycls


@cycls.function(name="super-new-clock", image=cycls.Image().pip("httpx"), schedule=cycls.Cron("*/5 * * * *"))
def clock():
    import httpx
    r = httpx.post("https://super-new.cycls.ai/routines/tick", timeout=120)
    return {"status": r.status_code, "body": r.text[:300]}
