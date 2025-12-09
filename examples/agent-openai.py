"""
Example: Zero-config gpt agent with automatic file handling

This example shows the simplest way to create a GPT-powered agent
that automatically handles file uploads from the frontend.
"""

import cycls

agent = cycls.Agent()

@agent("gpt-chat", title="Gpt Chat", auth=False)
async def chat(context):
    llm = cycls.OpenAI(
        api_key="YOUR_OPENAI_API_KEY_HERE",
        model="gpt-4o"
    )

    return await llm.stream(context.messages)

# Run locally
agent.local()
