# The agent the Video tool is built against: Kimi K3 on Together (as super-dev runs it), the Video
# tool on the dev render service, Editor to read a composition back, Canvas for the file card.
#
# No Docker: serve this checkout and its built web client on localhost.
#
#   uv pip install uvicorn            # once; not a dependency of the SDK
#   uv run --no-sync python -c "import sys; sys.path.insert(0, 'examples/agents'); \
#       import video_dev; video_dev.video_dev._local(8093)"
#
# Keys: TOGETHER_API_KEY in .env (untracked); VIDEO_URL and VIDEO_SECRET are read from
# ~/.cycls/cycls-video-dev.env, which cycls-video's `scripts/deploy.py dev` writes. VIDEO_ORGS is
# "*" here, for a local run only; a deployed agent names its organisations.
import os
from pathlib import Path

import cycls

_dev = Path.home() / ".cycls" / "cycls-video-dev.env"
if _dev.exists():
    for _line in _dev.read_text().splitlines():
        if "=" in _line and not _line.startswith("#"):
            _key, _value = _line.split("=", 1)
            os.environ.setdefault(_key, _value)
os.environ.setdefault("VIDEO_ORGS", "*")

SYSTEM = ("You are Cycls Video's development agent. You make short videos with the Video tool. Before your "
          "first video in a chat, call the tool's guide. Keep replies short; let the video speak.")

llm = (
    cycls.LLM()
    .model("together/moonshotai/Kimi-K3")
    .base_url("https://api.together.xyz/v1")
    .api_key(os.environ.get("TOGETHER_API_KEY"))
    .extra_body({"reasoning_effort": "high"})
    .context(1_000_000)
    # A composition is written whole in one call: the spike's ran to 8,800 output tokens, and the
    # default cap (8,192) would cut it off mid-document.
    .max_tokens(64_000)
    .price(input=2.70, output=13.50, cache_read=0.27)
    .system(SYSTEM)
    .allowed_tools(["Video", "Editor", "Canvas"])
)


@cycls.agent(
    web=cycls.Web().auth(cycls.Clerk()).title("Video (dev)"),
    volumes={"/workspace": cycls.Volume("video-dev")},
)
async def video_dev(context):
    async for ev in llm.run(context=context):
        yield ev
