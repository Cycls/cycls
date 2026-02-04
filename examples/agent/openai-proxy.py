# uv run examples/agent/openai-proxy.py
# OpenAI API proxy - deploy and use as OPENAI_BASE_URL for codex

import cycls


@cycls.app(pip=["httpx"])
async def openai_proxy(context):
    yield "This is an API proxy, not a chat interface."


@openai_proxy.server.api_route("/v1/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def proxy(path: str, request):
    import os
    import httpx
    from fastapi.responses import StreamingResponse, JSONResponse

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return JSONResponse({"error": "OPENAI_API_KEY not configured"}, status_code=500)

    body = await request.body()

    async with httpx.AsyncClient() as client:
        resp = await client.request(
            method=request.method,
            url=f"https://api.openai.com/v1/{path}",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": request.headers.get("Content-Type", "application/json"),
            },
            content=body,
            timeout=120,
        )

        if "text/event-stream" in resp.headers.get("content-type", ""):
            return StreamingResponse(resp.aiter_bytes(), media_type="text/event-stream")

        return JSONResponse(resp.json(), status_code=resp.status_code)


# openai_proxy.local()
# openai_proxy.deploy()
