# An ASGI service: return a FastAPI app and get a URL.
#
#   uv run cycls run examples/apps/api.py            # localhost, reload on save
#   uv run cycls run examples/apps/api.py --remote   # live dev URL, hot-swap on save
#   uv run cycls deploy examples/apps/api.py         # production
import cycls

@cycls.app()
def fast():
    import sys
    from fastapi import FastAPI
    app = FastAPI()

    @app.get("/")
    async def read_root():
        return {"message": f"Hello from FastAPI on Python {sys.version}"}

    return app

# Or drive the loop yourself — the entrypoint's code chooses the verbs:
# @cycls.local_entrypoint
# def main():
#     fast.remote()
