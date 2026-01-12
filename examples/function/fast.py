import cycls

@cycls.function(pip=["fastapi", "uvicorn"])
def fast(port):
    from fastapi import FastAPI
    import uvicorn
    import sys
    app = FastAPI()

    @app.get("/")
    async def read_root():
        return {"message": f"Hello from a remote FastAPI service running on Python {sys.version}"}

    uvicorn.run(app, host="0.0.0.0", port=port)

fast.run(port=8000)