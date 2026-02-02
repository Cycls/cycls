# export CYCLS_API_KEY=
# uv run examples/app/anthropic-agent-client.py
import cycls

@cycls.app(pip=["claude-agent-sdk"], auth=True, copy=[".env"], memory="2Gi")
async def anthropic_agent(context):
    import os
    import asyncio
    import time
    from claude_agent_sdk import (
        ClaudeSDKClient,
        ClaudeAgentOptions,
        AssistantMessage,
        TextBlock,
        ToolUseBlock,
        ThinkingBlock,
        ResultMessage,
    )

    t0 = time.time()
    def log(msg):
        print(f"[{time.time() - t0:.2f}s] {msg}", flush=True)

    log("Request started")

    # Check CLI version and path
    import subprocess
    import shutil
    cli_path = shutil.which("claude")
    log(f"Claude CLI path: {cli_path}")
    if cli_path:
        result = subprocess.run([cli_path, "--version"], capture_output=True, text=True, timeout=10)
        log(f"Claude CLI version: {result.stdout.strip()}")

    # Skip CLI version check to speed up startup
    os.environ["CLAUDE_AGENT_SDK_SKIP_VERSION_CHECK"] = "true"

    user_id = context.user.id if context.user else "default"
    user_workspace = f"/workspace/{user_id}"

    log(f"User: {user_id}, workspace: {user_workspace}")

    # Point Claude's config to persistent user-specific directory
    os.makedirs(f"{user_workspace}/.claude", exist_ok=True)
    os.environ["CLAUDE_CONFIG_DIR"] = f"{user_workspace}/.claude"
    log("Config dir set")

    options = ClaudeAgentOptions(
        cwd=user_workspace,
        continue_conversation=True,
        allowed_tools=["Read", "Edit", "Glob", "Grep", "Bash", "WebSearch"],
        permission_mode="acceptEdits",
    )
    log("Options created")

    client = ClaudeSDKClient(options=options)
    log("Client created")

    try:
        log("Connecting...")
        await client.connect()
        log("Connected")

        log("Sending query...")
        await client.query(context.last_message)
        log("Query sent")

        first_message = True
        async for message in client.receive_response():
            if first_message:
                log(f"First message received: {type(message).__name__}")
                first_message = False

            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        if first_message:
                            log("First text block")
                        yield block.text
                    elif isinstance(block, ThinkingBlock):
                        yield {"type": "thinking", "thinking": block.thinking}
                    elif isinstance(block, ToolUseBlock):
                        log(f"Tool use: {block.name}")
                        yield {"type": "thinking", "thinking": f"Using tool: {block.name}"}

            elif isinstance(message, ResultMessage):
                log("Result message received")
                yield {"type": "thinking", "thinking": "Completed"}

        log("Stream complete")

    except asyncio.CancelledError:
        log("Client disconnected (CancelledError)")
        pass
    finally:
        log("Disconnecting...")
        await client.disconnect()
        log("Disconnected")


# anthropic_agent.local()
anthropic_agent.deploy()
