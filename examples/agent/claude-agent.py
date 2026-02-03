# export CYCLS_API_KEY=
# uv run examples/agent/claude-agent.py
import re
import cycls


def extract_session_id(messages):
    """Extract session_id from previous assistant messages."""
    for msg in reversed(messages):
        if msg.get("role") == "assistant":
            content = msg.get("content", "")
            if isinstance(content, str):
                match = re.search(r"<!--s:(.+?)-->", content)
                if match:
                    return match.group(1)
    return None


@cycls.app(pip=["claude-agent-sdk"], auth=True, copy=[".env"], memory="2Gi")
async def claude_agent(context):
    import os
    from claude_agent_sdk import (
        ClaudeSDKClient,
        ClaudeAgentOptions,
        AssistantMessage,
        ToolUseBlock,
        ThinkingBlock,
        ResultMessage,
    )
    from claude_agent_sdk.types import StreamEvent

    yield {"type": "thinking", "thinking": "Analyzing your request..."}

    # User workspace setup
    user_id = context.user.id if context.user else "default"
    user_workspace = f"/workspace/{user_id}"
    os.makedirs(user_workspace, exist_ok=True)

    session_id = extract_session_id(context.messages)

    options = ClaudeAgentOptions(
        cwd=user_workspace,
        allowed_tools=["Read", "Edit", "Write", "Glob", "Grep", "Bash", "WebSearch"],
        permission_mode="acceptEdits",
        include_partial_messages=True,
        setting_sources=["project"],
        disallowed_tools=["AskUserQuestion"],  # subtracts ~6s
        resume=session_id,
        system_prompt=f"Your working directory is {user_workspace}. Always use this directory for all file operations.",
    )

    async with ClaudeSDKClient(options=options) as client:
        await client.query(context.last_message)
        yield {"type": "thinking", "thinking": "Done.", "done": True}

        real_session_id = None
        async for message in client.receive_response():
            if isinstance(message, StreamEvent):
                delta = message.event.get("delta", {})
                if delta.get("type") == "text_delta":
                    yield delta.get("text", "")
                continue

            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, ThinkingBlock):
                        yield {"type": "thinking", "thinking": block.thinking}
                    elif isinstance(block, ToolUseBlock):
                        yield {"type": "step", "step": f"Using tool: {block.name}"}

            elif isinstance(message, ResultMessage):
                real_session_id = message.session_id

    if real_session_id:
        yield f"\u200B<!--s:{real_session_id}-->\u200B"


claude_agent.local()
# claude_agent.deploy()
