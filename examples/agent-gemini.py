"""
Example: Zero-config Gemini agent with automatic file handling

This example shows the simplest way to create a Gemini-powered agent
that automatically handles file uploads from the frontend.
"""

import cycls

agent = cycls.Agent()

@agent("gemini-chat", title="Gemini Chat", auth=False)
async def chat(context):
    llm = cycls.Gemini(
        api_key="YOUR_GOOGLE_API_KEY_HERE", 
        model="gemini-2.5-pro" 
    )
    return await llm.stream(context.messages)

agent.local()
