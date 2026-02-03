# uv run examples/agent/openai-proxy.py
# Proxy that adds OpenAI API key server-side

import cycls


@cycls.function(pip=["httpx"])
async def openai_proxy(request: dict) -> dict:
    import os
    import httpx

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return {"error": "OPENAI_API_KEY not configured"}

    path = request.get("path", "/v1/chat/completions")
    method = request.get("method", "POST")
    body = request.get("body")

    async with httpx.AsyncClient() as client:
        resp = await client.request(
            method=method,
            url=f"https://api.openai.com{path}",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=body,
            timeout=120,
        )
        return {"status": resp.status_code, "body": resp.json()}


# openai_proxy.local()
# openai_proxy.deploy()
