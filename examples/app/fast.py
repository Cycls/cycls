# Live cloud dev: uv run cycls run examples/app/fast.py — edit, save, the URL updates in ~1s.
# (Drop the entrypoint and the same command serves it locally in Docker instead.)
# Production: uv run cycls deploy examples/app/fast.py
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

@cycls.local_entrypoint
def main():
    fast.remote()
