# The connect relay — one registered redirect URI for every agent.
#
#   uv run cycls run    services/connect/main.py     # localhost
#   uv run cycls deploy services/connect/main.py     # connect.cycls.ai
#
# Every agent sits on its own subdomain and every provider wants an exact registered redirect, so
# one per agent per provider does not scale — GitHub caps the list at ten, and Canva, Foodics,
# Vercel, Square, Asana and Figma refuse an unknown host outright. One URI is registered instead,
# https://connect.cycls.ai/callback, and this bounces the code back to the agent that started it.
#
# It never sees a token. It forwards an authorization code, useless without the client secret and
# the PKCE verifier, both of which stay at the agent — so the one shared component carries almost
# no blast radius, and it stores nothing.
#
# The signature check and the origin rule are the SDK's own (`cycls._agent.connectors`), the same
# code the agents run, so the two halves cannot drift apart into a broken login.
#
# Config: CYCLS_RELAY_SECRET signs the state and is shared with every agent allowed to use the
# relay; CYCLS_RELAY_ORIGINS is the comma-separated allowlist. Each agent sets CYCLS_RELAY_SECRET
# to the same value and CYCLS_RELAY_URL to https://connect.cycls.ai/callback.
import cycls

image = cycls.Image().copy(".providers.env", ".env")


@cycls.app(image=image, name="connect")
def connect():
    from urllib.parse import urlencode
    from fastapi import FastAPI, Request
    from fastapi.responses import RedirectResponse, HTMLResponse
    from cycls._agent import connectors as oauth

    app = FastAPI()

    def fail(why):
        return HTMLResponse(f"<p>Couldn't finish connecting: {why}. You can close this tab.</p>", status_code=400)

    @app.get("/callback")
    async def callback(request: Request):
        q = dict(request.query_params)
        if not (state := q.get("state")):
            return fail("no state")
        try:
            payload = oauth.verify(state, key=oauth.state_key())
            target = oauth.relay_target(payload, oauth.relay_origins())
        except (ValueError, KeyError):
            return fail("that link is not valid any more")
        # The provider's own parameters ride through untouched — an error is the agent's to render.
        return RedirectResponse(f"{target}?{urlencode(q)}", status_code=302)

    @app.get("/_health")
    async def health():
        return {"ok": True, "origins": len(oauth.relay_origins())}

    return app
