# export  CYCLS_API_KEY=
# uv run examples/app/anthropic-agent.py
import cycls

# cycls.base_url = "https://api-572247013948.me-central1.run.app"

@cycls.app(pip=["claude-agent-sdk"], copy=[".env"], memory="2Gi")
async def anthropic_agent(context):
    from claude_agent_sdk import (
        ClaudeSDKClient,
        ClaudeAgentOptions,
        AssistantMessage,
        TextBlock,
        ToolUseBlock,
        ThinkingBlock,
        ResultMessage,
    )

    async with ClaudeSDKClient(
        options=ClaudeAgentOptions(
            allowed_tools=["Read", "Edit", "Glob", "Grep", "Bash", "WebSearch"],
            permission_mode="acceptEdits",
        )
    ) as client:
        await client.query(context.last_message)

        async for message in client.receive_response():
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        yield block.text
                    elif isinstance(block, ThinkingBlock):
                        yield {"type": "thinking", "thinking": block.thinking}
                    elif isinstance(block, ToolUseBlock):
                        yield {"type": "thinking", "thinking": f"Using tool: {block.name}"}

            elif isinstance(message, ResultMessage):
                yield {"type": "thinking", "thinking": f"Tool completed"}


# anthropic_agent.local()
anthropic_agent.deploy()
