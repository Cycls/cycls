# uv run examples/agent/codex-agent.py
# Minimal Codex app-server agent
# https://developers.openai.com/codex/config-reference/
# https://github.com/openai/codex/blob/main/codex-rs/core/gpt_5_codex_prompt.md
# https://github.com/Piebald-AI/claude-code-system-prompts/tree/main

import cycls


@cycls.app(
    apt=["curl", "proot", "xz-utils"], copy=[".env"], memory="512Mi",  # TODO: proot remove
    run_commands=[
        "curl -fsSL https://nodejs.org/dist/v24.13.0/node-v24.13.0-linux-x64.tar.xz | tar -xJ -C /usr/local --strip-components=1",
        "npm i -g @openai/codex@0.98.0",
    ],
    auth=True,
    # force_rebuild=True,
)
async def codex_agent(context):
    agent = cycls.Agent()
    async for event in agent.run(context):
        yield event


codex_agent.local()
# codex_agent.deploy()